# SPDX-License-Identifier: GPL-3.0-or-later
"""Verified packet union and recoverable installation of an overlap group."""

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from review_overlap_audit import (AUDIO_ALIGNMENT, PACKET_TIMING, RECOVERY_FOLDER, Clip, covers_packets,
                                  duration_tolerance, packet_alignment, pair_coverage, probe, video_alignment)
from review_cleanup_actions import (actions, bind_cleanup_folders, check_file, protect_media, recovery_path,
                                   move_to_recovery, prepare_recovery_file, replace_file, restore_recovery,
                                   supporting_paths, validate_recovery_path)
from review_cleanup_core import (RESERVE_BYTES, archive_clip, connection, export_lock, hash_file, list_copies,
                                run_media, stream_labels, track_name_options, verify_labels, verify_slice)


MAX_AUDIO_SHIFT = .022


@dataclass(frozen=True)
class TrackPlacement:
    first: int
    shift: float


@dataclass(frozen=True)
class Segment:
    clip: int
    start: int
    end: int


@dataclass
class PreparedMerge:
    clips: tuple
    folder: tempfile.TemporaryDirectory
    path: Path
    checksum: str
    audio_names: list
    duration: float
    audio_shift: float
    contributors: tuple
    original_checksums: tuple
    track_placements: tuple
    dependencies: tuple
    dependency_files: dict
    dependency_spans: dict
    output_start: float = 0.0
    video_index: int = 0
    source_starts: tuple = ()
    source_durations: tuple = ()


def audio_matches(track, peer, video_shift):
    offsets = {i for i, pts in enumerate(peer.pts) if abs(pts - track.pts[0] - video_shift) <= AUDIO_ALIGNMENT}
    offsets.update(-i for i, pts in enumerate(track.pts) if abs(peer.pts[0] - pts - video_shift) <= AUDIO_ALIGNMENT)
    return [(offset, proof[2]) for offset in offsets if (proof := packet_alignment(track, peer, offset))]


def place_peer(original, peer, placements):
    alignment = video_alignment(original, peer)
    if alignment is None:
        return None
    video_index = original.video
    left = alignment.span[0]
    track, other = original.tracks[video_index], peer.tracks[video_index]
    right = [i for i in other.keyframes if other.hashes[i] == track.hashes[left]
             and abs(other.pts[i] - track.pts[left] - alignment.shift) <= duration_tolerance(track, other)]
    if len(right) != 1:
        return None
    anchor = placements[video_index]
    video = TrackPlacement(anchor.first + left - right[0], anchor.shift - alignment.shift)
    options = {}
    for i, (a, b) in enumerate(zip(original.tracks, peer.tracks)):
        if i == video_index:
            continue
        start = placements[i]
        options[i] = [TrackPlacement(start.first - offset, start.shift - shift)
                      for offset, shift in audio_matches(a, b, alignment.shift)
                      if abs(start.shift - shift - video.shift) <= MAX_AUDIO_SHIFT]
    result = {video_index: video}
    if options:
        first = next(iter(options))
        alignments = []
        for reference in options[first]:
            matching = {i: [choice for choice in choices if abs(choice.shift - reference.shift) <= .0001]
                        for i, choices in options.items()}
            if all(len(choices) == 1 for choices in matching.values()):
                alignments.append({i: choices[0] for i, choices in matching.items()})
        if len(alignments) != 1:
            return None
        result.update(alignments[0])
    return tuple(result[i] for i in range(len(original.tracks)))


def place_group(media, edges):
    first = media[0]
    signature = [(track.signature, track.tick) for track in first.tracks]
    if any(item.video != first.video or [(t.signature, t.tick) for t in item.tracks] != signature for item in media):
        raise ValueError("The clips use different stream layouts, codecs or timestamp scales.")
    placed = {0: tuple(TrackPlacement(0, 0.0) for _ in first.tracks)}
    pending = [0]
    while pending:
        i = pending.pop(0)
        for j in sorted(edges[i] - placed.keys()):
            if match := place_peer(media[i], media[j], placed[i]):
                placed[j] = match
                pending.append(j)
    if len(placed) != len(media):
        raise ValueError("The entire group could not be aligned using matching video and audio packets. "
                         "A source may have changed or have incompatible audio timing.")
    return [placed[i] for i in range(len(media))]


def track_segments(media, placements, track):
    """Cover an interval using the fewest extending sources, splicing at their starts."""
    starts = [row[track].first for row in placements]
    ends = [start + len(item.tracks[track].hashes) for start, item in zip(starts, media)]
    cursor = min(starts)
    selected = []
    while cursor < max(ends):
        choices = [i for i, (start, end) in enumerate(zip(starts, ends)) if start <= cursor < end]
        if not choices:
            raise ValueError(f"There is a packet gap on stream {track + 1}.")
        index = max(choices, key=lambda i: (ends[i], -starts[i], -i))
        if selected and starts[index] <= starts[selected[-1]]:
            raise ValueError(f"No safe source boundary on stream {track + 1}.")
        selected.append(index)
        cursor = ends[index]
    return [Segment(index, 0, starts[selected[i + 1]] - starts[index] if i + 1 < len(selected)
                    else ends[index] - starts[index]) for i, index in enumerate(selected)]


def concat_escape(path):
    value = path.as_posix()
    if "\n" in value or "\r" in value:
        raise ValueError("Clip paths cannot contain a line break.")
    return "'" + value.replace("'", "'\\''") + "'"


def packet_filter(media, placements, pieces, order, track, stride, origin):
    by_clip = {piece.clip: piece for piece in pieces}
    offsets, ranges = [], []
    input_index = 0
    for position, i in enumerate(order):
        item = media[i]
        if piece := by_clip.get(i):
            ranges.append(f"between(n,{input_index + piece.start},{input_index + piece.end - 1})")
            shift = placements[i][track].shift - origin - (position * stride - item.start)
            offsets.append((piece.end - piece.start, round(shift / item.tracks[track].tick)))
        input_index += len(item.tracks[track].hashes)
    delta = str(offsets[0][1])
    count = 0
    for (length, previous), (_, offset) in zip(offsets, offsets[1:]):
        count += length
        if offset != previous:
            delta += f"+({offset - previous})*gte(N,{count})"
    return f"noise=amount=0:drop='not({'+'.join(ranges)})',setts=pts='PTS+({delta})':dts='DTS+({delta})'"


def verify_merge(media, placements, output, origin):
    signatures = [track.signature for track in media[0].tracks]
    if [track.signature for track in output.tracks] != signatures or output.video != media[0].video:
        raise ValueError("The merged file's stream layout or codec settings changed.")
    for i, track in enumerate(output.tracks):
        first = min(row[i].first for row in placements)
        last = max(row[i].first + len(item.tracks[i].hashes) for row, item in zip(placements, media))
        if len(track.hashes) != last - first:
            raise ValueError(f"Merged stream {i + 1} has missing or extra packets.")
        for item, row in zip(media, placements):
            source = item.tracks[i]
            start = row[i].first - first
            stop = start + len(source.hashes)
            if track.hashes[start:stop] != source.hashes:
                raise ValueError(f"Merged stream {i + 1} did not preserve every source packet.")
            shift = row[i].shift - origin
            tolerance = duration_tolerance(source, track)
            for index, pts in enumerate(source.pts):
                j = start + index
                expected_dts, actual_dts = source.dts[index], track.dts[j]
                if (abs(track.pts[j] - pts - shift) > tolerance
                        or (expected_dts is None) != (actual_dts is None)
                        or expected_dts is not None and abs(actual_dts - expected_dts - shift) > tolerance
                        or track.side_data.get(j) != source.side_data.get(index)):
                    raise ValueError(f"Merged stream {i + 1} changed packet timing or playback metadata.")
                change = track.durations[j] - source.durations[index]
                if change < -tolerance or change > tolerance and j != stop - 1:
                    raise ValueError(f"Merged stream {i + 1} changed a packet's duration.")


def merge_dependencies(destination, clips):
    paths = {clip.path for clip in clips}
    history = actions(destination)
    affected = {action["id"]: action for action in history
                if action["kind"] != "delete_trimmed" and (not action.get("manual_overlap") or action["state"] == "started")
                and action["state"] in {"started", "done"}
                and (paths.intersection(map(Path, action.get("supports", ())))
                     or Path(action["source"]) in paths)}
    installed = {action["copy_id"]: action for action in history
                 if action["state"] == "done" and action["kind"] != "delete_trimmed" and action.get("copy_id")}
    for record in list_copies(destination):
        if record["state"] != "verified" or not paths.intersection(map(Path, supporting_paths(record))):
            continue
        action = installed.get(record["id"])
        if action is None:
            raise ValueError(f"The uninstalled review copy of {Path(record['source']).name} still uses this group as coverage.")
        affected[action["id"]] = action
    if any(action["state"] != "done" for action in affected.values()):
        raise ValueError("An earlier cleanup still needs recovery review.")
    return tuple(affected.values())


def read_dependency(path, ffprobe, inputs, identity=None, expected_hash=None):
    with protect_media(path):
        file_id = check_file(path, identity)
        checksum = hash_file(path)
        if expected_hash and checksum != expected_hash:
            raise ValueError(f"The earlier file checksum differs: {path.name}.")
        inputs[path] = file_id, checksum
        return probe(Clip(path, file_id[2], file_id, datetime.now(timezone.utc), "merge coverage"), ffprobe, 180)


def dependency_audio_range(output, dependencies, ffprobe, destination):
    """Find the audio shifts that preserve complete footage from earlier archive edits."""
    low, high = -MAX_AUDIO_SHIFT, MAX_AUDIO_SHIFT
    inputs = {}
    full, partial = {}, []
    for action in dependencies:
        source, recovery = Path(action["source"]), Path(action["recovery"])
        validate_recovery_path(action, destination)
        try:
            original = read_dependency(recovery, ffprobe, inputs, action.get("recovery_identity", action["original_identity"]), action.get("recovery_sha256"))
            if ([track.signature for track in original.tracks] != [track.signature for track in output.tracks]
                    or original.video != output.video):
                raise ValueError("The earlier file uses a different stream layout.")
            video = video_alignment(original, output)
            if video is None or video.span != (0, len(original.tracks[original.video].hashes)):
                partial.append((action, original))
                continue
            prior = action.get("track_placements") if action["kind"] == "merge_original" else None
            for i, (track, merged) in enumerate(zip(original.tracks, output.tracks)):
                if i == original.video:
                    continue
                placements = []
                for offset, shift in audio_matches(track, merged, video.shift):
                    if offset < 0:
                        continue
                    proof = packet_alignment(track, merged, offset)
                    if proof and proof[:2] == (0, len(track.hashes)):
                        placements.append(shift - video.shift)
                if len(placements) != 1:
                    raise ValueError(f"The merged file could not uniquely place every earlier packet on stream {i + 1}.")
                previous = prior[i]["shift_seconds"] - prior[original.video]["shift_seconds"] if prior else 0
                delta = placements[0] - previous
                limit = PACKET_TIMING - max(track.tick, merged.tick)
                low, high = max(low, -limit - delta), min(high, limit - delta)
                if low > high:
                    raise ValueError("The earlier edits require incompatible audio timing.")
            full[action["id"]] = [(0, len(track.hashes)) for track in original.tracks]
        except (OSError, ValueError, KeyError, IndexError) as error:
            raise ValueError(f"Cannot carry forward coverage for {source.name}.\n{error}") from error
    return low, high, inputs, full, partial


def verify_partial_dependencies(output, partial, media, destination, ffprobe, inputs):
    """Preserve earlier cuts whose retained footage sits outside the selected group."""
    records = {record["id"]: record for record in list_copies(destination)} if partial else {}
    spans = {}
    for action, original in partial:
        source = Path(action["source"])
        try:
            proof = pair_coverage(original, output, "verified merge")
            if proof is None:
                raise ValueError("The merged file could not verify the earlier overlap on every track.")
            forwarded = action.get("coverage_via_merge")
            if forwarded and "spans" in forwarded:
                required = [(i, start, end) for i, (start, end) in enumerate(forwarded["spans"])]
            elif action.get("manual_overlap"):
                peers = [media[Path(path)] for path in action["supports"]]
                proofs = [pair_coverage(original, peer, str(path)) for peer, path in zip(peers, action["supports"])]
                if not proofs or any(prior is None for prior in proofs):
                    raise ValueError("Could not verify the prior manual overlap on every track.")
                required = [(i, start, end) for prior in proofs for i, (start, end) in enumerate(prior.spans)]
            elif action.get("copy_id"):
                record = records[action["copy_id"]]
                if Path(record["source"]) != source or record["state"] != "verified":
                    raise ValueError("The earlier retained copy is unavailable.")
                retained = read_dependency(Path(record["output"]), ffprobe, inputs, expected_hash=record["copy_sha256"])
                verify_slice(original, retained, original.start + record["trim_start_seconds"],
                             original.start + record.get("retained_end_seconds", original.duration), [proof])
                required = []
            else:
                required = [(i, 0, len(track.hashes)) for i, track in enumerate(original.tracks)]
            if any(not covers_packets([proof], i, start, end) for i, start, end in required):
                raise ValueError("Some packets covered by the earlier edit would no longer be covered.")
            spans[action["id"]] = list(proof.spans)
        except (OSError, ValueError, KeyError, IndexError) as error:
            raise ValueError(f"Cannot carry forward coverage for {source.name}.\n{error}") from error
    return spans


def prepare_merge(destination, clips, edges, tools, progress, ledger=None):
    if len(clips) < 2 or len({clip.file_id[:2] for clip in clips}) != len(clips):
        raise ValueError("Select at least two distinct archive clips.")
    if clips[0] != min(clips, key=lambda clip: (clip.capture_time, str(clip.path))):
        raise ValueError("The first merge input must be the oldest clip.")
    if any(clip.path.suffix.lower() != clips[0].path.suffix.lower() for clip in clips) or clips[0].path.suffix.lower() not in {".mp4", ".mov"}:
        raise ValueError("Merge All currently requires matching MP4 or MOV containers.")
    if shutil.disk_usage(destination).free < sum(clip.size for clip in clips) + RESERVE_BYTES:
        raise ValueError("There is insufficient room to prepare the merged video.")
    dependencies = merge_dependencies(destination if ledger is None else ledger, clips)
    with ExitStack() as guards:
        for clip in clips:
            guards.enter_context(protect_media(clip.path))
            check_file(clip.path, clip.file_id)
        media = []
        for i, clip in enumerate(clips, 1):
            progress(f"Checking clip {i}/{len(clips)} · {clip.path.name}")
            media.append(probe(clip, tools["ffprobe"], 180))
        labels = stream_labels(clips[0].path, tools["ffprobe"])
        for clip in clips[1:]:
            verify_labels(media[0], labels, stream_labels(clip.path, tools["ffprobe"]))
        placements = place_group(media, edges)
        video = media[0].video
        pieces = [track_segments(media, placements, i) for i in range(len(media[0].tracks))]
        order = sorted({piece.clip for track in pieces for piece in track},
                       key=lambda i: (placements[i][video].first, i))
        ranks = {clip: i for i, clip in enumerate(order)}
        if any([ranks[p.clip] for p in track] != sorted(ranks[p.clip] for p in track) for track in pieces):
            raise ValueError("The audio and video require an incompatible splice order.")
        origin = min(min(track.pts) + placement.shift for item, row in zip(media, placements)
                     for track, placement in zip(item.tracks, row))
        stride = math.ceil(max(item.duration for item in media)) + 2
        folder = tempfile.TemporaryDirectory(prefix=".review-work-merge-", dir=destination)
        directory = Path(folder.name)
        final = directory / clips[0].path.name
        try:
            concat = directory / "sources.ffconcat"
            concat.write_text("ffconcat version 1.0\n" + "".join(
                f"file {concat_escape(clips[i].path)}\nduration {stride}\n" for i in order), encoding="utf-8")
            def render():
                filters = []
                for i, track in enumerate(pieces):
                    filters.extend((f"-bsf:{i}", packet_filter(media, placements, track, order, i, stride, origin)))
                progress("Joining encoded packets without re-encoding…")
                run_media([tools["ffmpeg"], "-hide_banner", "-v", "error", "-xerror", "-nostdin", "-n", "-copyts",
                           "-f", "concat", "-safe", "0", "-auto_convert", "0", "-protocol_whitelist", "file,concat",
                           "-i", str(concat), "-protocol_whitelist", "file", "-i", str(clips[0].path), "-map", "0",
                           "-map_metadata", "1", "-map_chapters", "-1", "-c", "copy", "-copytb", "1",
                           "-avoid_negative_ts", "disabled", *filters,
                           *track_name_options(media[0], labels, final.suffix.lower()), str(final)], timeout=1800)
                progress("Verifying every merged video and audio packet…")
                identity = check_file(final)
                result = probe(Clip(final, identity[2], identity, clips[0].capture_time, "merged"), tools["ffprobe"], 600)
                verify_merge(media, placements, result, origin)
                return result

            output = render()
            progress("Checking coverage for earlier archive edits…")
            low, high, dependency_files, spans, partial = dependency_audio_range(output, dependencies, tools["ffprobe"], destination if ledger is None else ledger)
            if not low <= 0 <= high:
                bias = (low + high) / 2
                placements = [tuple(TrackPlacement(p.first, p.shift + (bias if i != video else 0))
                                    for i, p in enumerate(row)) for row in placements]
                if any(abs(row[i].shift - row[video].shift) > MAX_AUDIO_SHIFT
                       for row in placements for i in range(len(row))):
                    raise ValueError("Earlier edits would require too large an audio timing adjustment.")
                origin = min(min(track.pts) + p.shift for item, row in zip(media, placements)
                             for track, p in zip(item.tracks, row))
                final.unlink()
                output = render()
                low, high, final_dependencies, spans, partial = dependency_audio_range(output, dependencies, tools["ffprobe"], destination if ledger is None else ledger)
                if not low <= 0 <= high or final_dependencies != dependency_files:
                    raise ValueError("The merged result could not preserve verified coverage for earlier edits.")
            spans.update(verify_partial_dependencies(output, partial, {clip.path: item for clip, item in zip(clips, media)},
                                                     destination if ledger is None else ledger, tools["ffprobe"], dependency_files))
            names = verify_labels(media[0], labels, stream_labels(final, tools["ffprobe"]))
            progress("Decoding the merged result to check playback…")
            run_media([tools["ffmpeg"], "-hide_banner", "-v", "error", "-xerror", "-err_detect", "explode",
                       "-nostdin", "-protocol_whitelist", "file", "-i", str(final), "-map", "0:v", "-map", "0:a?",
                       "-f", "null", "-"], timeout=1800)
            checksums = tuple(hash_file(clip.path) for clip in clips)
            for clip in clips:
                check_file(clip.path, clip.file_id)
            shift = max(abs(row[i].shift - row[video].shift) for row in placements for i in range(len(row)))
            first_packets = [min(row[i].first for row in placements) for i in range(len(media[0].tracks))]
            track_placements = tuple(tuple({"first_packet": p.first - first_packets[i], "shift_seconds": p.shift - origin}
                                           for i, p in enumerate(row)) for row in placements)
            return PreparedMerge(clips, folder, final, hash_file(final), names, output.duration, shift,
                                 tuple(clips[i].path for i in order), checksums, track_placements,
                                 dependencies, dependency_files, spans, output.start, video,
                                 tuple(m.start for m in media),tuple(m.duration for m in media))
        except BaseException:
            folder.cleanup()
            raise


def write_receipt(path, data):
    with path.open("x", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())


def install_merge(root, destination, merge, progress):
    clips = merge.clips
    oldest = clips[0].path
    transaction = uuid.uuid4().hex
    with export_lock(destination), ExitStack() as guards:
        folders = {clip.path.parent for clip in clips}
        for folder in sorted(folders):
            if not folder.is_relative_to(root) or folder.resolve(strict=True) != folder:
                raise ValueError("A merge input is outside the active archive.")
            guards.enter_context(export_lock(folder, ".replay-trim-safety.lock"))
        guards.enter_context(protect_media(merge.path))
        merged_id = check_file(merge.path)
        if hash_file(merge.path) != merge.checksum:
            raise ValueError("The verified merged file changed before installation.")
        if shutil.disk_usage(oldest.parent).free < merged_id[2] + RESERVE_BYTES:
            raise ValueError("There is insufficient room to stage the merged video beside the originals.")
        if merge_dependencies(destination, clips) != merge.dependencies:
            raise ValueError("Earlier cleanup records changed after verification. Prepare the merge again.")
        for path, (file_id, checksum) in merge.dependency_files.items():
            guards.enter_context(protect_media(path))
            check_file(path, file_id)
            if hash_file(path) != checksum:
                raise ValueError(f"The earlier recovery file changed: {path.name}.")
        unfinished = {Path(action["source"]) for action in actions(destination) if action["state"] == "started"}
        checksums = {}
        for clip, expected in zip(clips, merge.original_checksums):
            path = archive_clip(root, str(clip.path.relative_to(root))).path
            if path in unfinished:
                raise ValueError(f"An earlier cleanup of {path.name} still needs recovery review.")
            guards.enter_context(protect_media(path, moving=True))
            check_file(path, clip.file_id)
            checksums[path] = hash_file(path)
            if checksums[path] != expected:
                raise ValueError(f"{path.name} changed after the merged copy was verified.")
        bind_cleanup_folders(root, destination, folders)

        entries = []
        for clip, placement in zip(clips, merge.track_placements):
            ident = uuid.uuid4().hex
            backup = recovery_path(clip.path, ident, destination)
            recovery_id = prepare_recovery_file(clip.path, backup, checksums[clip.path])
            if backup.is_file():
                guards.enter_context(protect_media(backup))
            details = {"target": str(clip.path), "copy_id": None, "original_identity": list(clip.file_id),
                       "recovery_sha256": checksums[clip.path], "recovery_identity": list(recovery_id),
                       "recovery_root": str(destination / RECOVERY_FOLDER), "supports": [str(oldest)],
                       "merge_id": transaction, "merged_path": str(oldest), "merged_sha256": merge.checksum,
                       "audio_names": merge.audio_names, "audio_shift_seconds": merge.audio_shift,
                       "track_placements": placement}
            receipt = dict(id=ident, kind="merge_original", source=str(clip.path), recovery=str(backup), **details)
            entries.append(receipt)
        anchor = Path(entries[0]["recovery"])
        staged = Path(guards.enter_context(tempfile.TemporaryDirectory(prefix=".review-work-merge-install-", dir=oldest.parent))) / oldest.name
        progress("Staging the verified merge on the archive drive…")
        with merge.path.open("rb") as read, staged.open("xb") as write:
            shutil.copyfileobj(read, write, 4 * 1024 ** 2)
            write.flush()
            os.fsync(write.fileno())
        if hash_file(staged) != merge.checksum:
            raise ValueError("The staged installation did not match the verified merge.")
        os.utime(staged, ns=(oldest.stat().st_atime_ns, clips[0].file_id[3]))
        check_file(merge.path, merged_id)
        for clip in clips:
            check_file(clip.path, clip.file_id)
        for entry in entries:
            write_receipt(Path(entry["recovery"]).parent / "recovery.json", entry)
        write_receipt(anchor.parent / "merge.json", {"id": transaction, "originals": entries,
                      "coverage_carried_forward": [action["id"] for action in merge.dependencies]})

        utc = datetime.now(timezone.utc).isoformat()
        ids = [(entry["id"],) for entry in entries]
        with connection(destination) as db:
            db.executemany("INSERT INTO review_actions VALUES (?, ?, ?, ?, ?, ?, ?)", [
                (entry["id"], utc, "merge_original", entry["source"], entry["recovery"], "started",
                 json.dumps({key: value for key, value in entry.items()
                             if key not in {"id", "kind", "source", "recovery"}})) for entry in entries])

        moved = []
        try:
            progress("Installing the merge and moving the originals into recovery…")
            replace_file(oldest, staged, anchor)
            if hash_file(oldest) != merge.checksum:
                raise ValueError("The installed video checksum differs from the verified merge.")
            for clip, entry in zip(clips[1:], entries[1:]):
                check_file(clip.path, clip.file_id)
                backup = Path(entry["recovery"])
                move_to_recovery(clip.path, backup, checksums[clip.path])
                moved.append((clip.path, backup))
            for clip, entry in zip(clips, entries):
                backup = Path(entry["recovery"])
                check_file(backup, entry["recovery_identity"])
                if hash_file(backup) != checksums[clip.path]:
                    raise ValueError(f"The recovery checksum differs for {clip.path.name}.")
            with connection(destination) as db:
                for action in merge.dependencies:
                    details = {key: value for key, value in action.items()
                               if key not in {"id", "kind", "source", "recovery", "state"}}
                    details["supports"] = [str(oldest)]
                    details["coverage_via_merge"] = {"id": transaction, "sha256": merge.checksum,
                                                     "spans": merge.dependency_spans[action["id"]]}
                    db.execute("UPDATE review_actions SET details=? WHERE id=? AND state='done'",
                               (json.dumps(details), action["id"]))
                db.executemany("UPDATE review_actions SET state='done' WHERE id=?", ids)
        except Exception as error:
            try:
                for path, backup in reversed(moved):
                    if not path.exists():
                        restore_recovery(backup, path, checksums[path])
                if anchor.is_file():
                    check_file(anchor, entries[0]["recovery_identity"])
                    if oldest.is_file() and hash_file(oldest) == merge.checksum and not staged.exists():
                        oldest.rename(staged)
                    if not oldest.exists():
                        try:
                            restore_recovery(anchor, oldest, checksums[oldest])
                        except OSError:
                            if staged.is_file() and not oldest.exists():
                                staged.rename(oldest)
                            raise
                for clip in clips:
                    if hash_file(clip.path) != checksums[clip.path]:
                        raise ValueError(f"The restored original checksum differs for {clip.path.name}.")
                with connection(destination) as db:
                    db.executemany("UPDATE review_actions SET state='failed' WHERE id=?", ids)
            except Exception as rollback:
                raise ValueError(f"{error}\nRecovery review is required. Merge receipt: {anchor.parent}\n{rollback}") from error
            raise ValueError(f"{error}\nThe original clips are back at their archive paths.") from error
    return oldest, anchor.parent
