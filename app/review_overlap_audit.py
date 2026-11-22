# SPDX-License-Identifier: GPL-3.0-or-later
"""Report-only overlap audit for OBS replay archives. Python 3.10+, FFprobe."""

import argparse
from collections import OrderedDict, defaultdict
import csv
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from review_cancel import checkpoint,capture


EXTENSIONS = {".mp4", ".mkv", ".mov", ".ts", ".m4v", ".webm", ".flv", ".avi"}
RECOVERY_FOLDER = "Replay Trim Recovery"
REVIEW_LEDGER = "replay-review.sqlite3"
OBS_DATE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})[ _T](\d{2})[-_.:](\d{2})[-_.:](\d{2})(?!\d)")
AUDIO_ALIGNMENT = 0.15
PACKET_TIMING = 0.005


@dataclass(frozen=True)
class Clip:
    path: Path
    size: int
    file_id: tuple
    capture_time: datetime
    time_source: str


@dataclass
class Track:
    signature: tuple
    hashes: list
    pts: list
    dts: list
    durations: list
    keyframes: list
    side_data: dict = field(default_factory=dict)
    tick: float = .000001


@dataclass
class Media:
    tracks: list
    duration: float
    start: float
    video: int


@dataclass
class Match:
    reference: Clip
    cut: float
    shared_end: float
    video_overlap: float


@dataclass
class Coverage:
    reference: str
    spans: list
    offset: float
    start: float
    end: float


@dataclass
class VideoAlignment:
    span: tuple
    shift: float
    start: float
    end: float
    offset: float


def duration_tolerance(left, right):
    return min(PACKET_TIMING, max(left.tick, right.tick) + .000001)


def packet_alignment(target, reference, offset):
    left, right = max(0, -offset), max(0, offset)
    count = min(len(target.hashes) - left, len(reference.hashes) - right)
    if count <= 0 or target.hashes[left:left + count] != reference.hashes[right:right + count]:
        return None
    shift = reference.pts[right] - target.pts[left]
    tolerance = duration_tolerance(target, reference)
    for i in range(count):
        a, b = left + i, right + i
        if abs(reference.pts[b] - target.pts[a] - shift) > PACKET_TIMING:
            return None
        if target.side_data.get(a) != reference.side_data.get(b):
            return None
        if i == count - 1 and reference.durations[b] + .000001 < target.durations[a]:
            return (left, a, shift) if i else None
        if i != count - 1 and abs(reference.durations[b] - target.durations[a]) > tolerance:
            return None
        if reference.dts[b] is not None and target.dts[a] is not None:
            if abs(reference.dts[b] - target.dts[a] - shift) > PACKET_TIMING:
                return None
    return left, left + count, shift


def pair_coverage(target, reference, name):
    """Prove a contiguous alignment, allowing either clip to contain the other."""
    return compare_pair(target, reference, name)[0]


def video_alignment(target, reference):
    video, other = target.tracks[target.video], reference.tracks[reference.video]
    if not video.keyframes or not other.keyframes or video.keyframes[0] or other.keyframes[0]:
        return None
    offsets = {index for index in other.keyframes if other.hashes[index] == video.hashes[0]}
    offsets.update(-index for index in video.keyframes if video.hashes[index] == other.hashes[0])
    alignments = [match for offset in offsets if (match := packet_alignment(video, other, offset))]
    if len(alignments) != 1:
        return None
    start, stop, shift = alignments[0]
    if stop - start < 4:
        return None
    visible_start = min(video.pts[start:stop])
    visible_end = max(p + d for p, d in zip(video.pts[start:stop], video.durations[start:stop]))
    if visible_end - visible_start < 1:
        return None
    return VideoAlignment((start, stop), shift, max(0, visible_start - target.start),
                          min(target.duration, visible_end - target.start), shift + target.start - reference.start)


def compare_pair(target, reference, name):
    video = video_alignment(target, reference)
    if video is None:
        return None, 0, ""
    seconds = video.end - video.start
    shift = video.shift
    if [track.signature for track in target.tracks] != [track.signature for track in reference.tracks]:
        return None, seconds, "Stream layout or codec settings differ."
    spans, shifted = [], []
    for index, (track, peer) in enumerate(zip(target.tracks, reference.tracks)):
        if index == target.video:
            spans.append(video.span)
            continue
        offsets = {i for i, pts in enumerate(peer.pts) if abs(pts - track.pts[0] - shift) <= AUDIO_ALIGNMENT}
        offsets.update(-i for i, pts in enumerate(track.pts) if abs(peer.pts[0] - pts - shift) <= AUDIO_ALIGNMENT)
        matches = [match for offset in offsets if (match := packet_alignment(track, peer, offset))]
        audio = [match for match in matches if abs(match[2] - shift) <= PACKET_TIMING]
        if not audio:
            if matches:
                delta = min((match[2] - shift for match in matches), key=abs) * 1000
                shifted.append((index + 1, delta, len(matches) == 1))
                continue
            return None, seconds, f"Could not match every encoded packet on stream {index + 1}."
        # In silence, several packet offsets can agree. Credit only their intersection.
        first, last = max(a[0] for a in audio), min(a[1] for a in audio)
        if first >= last:
            return None, seconds, f"Audio alignment is ambiguous on stream {index + 1}."
        spans.append((first, last))
    if shifted:
        stream, delta, _ = shifted[0]
        if (len(shifted) == len(target.tracks) - 1
                and all(unique and abs(other - delta) < .05 for _, other, unique in shifted)):
            return None, seconds, f"All {len(shifted)} audio tracks match with a fixed {abs(delta):.2f} ms timing difference."
        return None, seconds, f"Audio timing differs by {abs(delta):.2f} ms on stream {stream}."
    return Coverage(name, spans, video.offset, video.start, video.end), seconds, ""


def merged_spans(supports, track):
    merged = []
    for start, end in sorted(proof.spans[track] for proof in supports):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def covers_packets(supports, track, start, end):
    return start >= end or any(a <= start and b >= end for a, b in merged_spans(supports, track))


def proposed_range(media, supports, overlap):
    if not supports:
        return None
    spans = [merged_spans(supports, i) for i in range(len(media.tracks))]
    if all(ranges == [(0, len(track.hashes))] for track, ranges in zip(media.tracks, spans)):
        return "redundant", 0.0, 0.0, 0.0, 0.0

    heads, tails = [], []
    for track, ranges in zip(media.tracks, spans):
        total = len(track.hashes)
        first, end = ranges[0]
        start, last = ranges[-1]
        if first == 0:
            heads.append(covered_until(track, end))
        if last == total:
            edge = max((pts + duration for pts, duration in
                        zip(track.pts[:start], track.durations[:start])), default=media.start)
            tails.append(max(edge, min(track.pts[start:])))
    head_limit = min(heads) if len(heads) == len(media.tracks) else media.start
    tail_limit = max(tails) if len(tails) == len(media.tracks) else media.start + media.duration
    video = media.tracks[media.video]
    keys = [video.pts[i] for i in video.keyframes if i and video.pts[i] > media.start]
    start = max((key for key in keys if media.start + .5 <= key <= head_limit - overlap), default=media.start)
    limit = media.start + media.duration
    end = min((key for key in keys if tail_limit + overlap <= key <= limit - .5), default=limit)
    if start >= end:
        return None
    if start == media.start and end == limit:
        return None
    return ("candidate", start - media.start, end - media.start,
            head_limit - start if start > media.start else 0.0,
            end - tail_limit if end < limit else 0.0)


def select_coverage(media, supports, overlap):
    result = proposed_range(media, supports, overlap)
    if result is None:
        return None, []
    # Keep only witnesses needed to prove this specific plan.
    retained = supports[:]
    for proof in supports:
        alternatives = [item for item in retained if item is not proof]
        if proposed_range(media, alternatives, overlap) == result:
            retained = alternatives
    return result, retained


def is_redirected(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def ordering(path, info):
    match = OBS_DATE.search(path.stem)
    if match:
        day, hour, minute, second = match.groups()
        try:
            return datetime.fromisoformat(f"{day}T{hour}:{minute}:{second}"), "OBS filename"
        except ValueError:
            pass
    return datetime.fromtimestamp(info.st_mtime), "file modified time"


def inventory(root,cancel=None,exclude_folders=(),*,include_folders=None):
    if any(part.casefold() == RECOVERY_FOLDER.casefold() for part in root.parts):
        return [], ["The recovery folder is excluded from archive scans."]
    clips = []
    warnings = []
    if any((parent / REVIEW_LEDGER).is_file() for parent in (root, *root.parents)):
        return [], ["Review folders are excluded from archive scans."]
    excluded = {name.casefold() for name in exclude_folders}
    included = None if include_folders is None else {name.casefold() for name in include_folders}
    for folder, subfolders, filenames in os.walk(root, onerror=lambda error: warnings.append(str(error))):
        checkpoint(cancel)
        directory = Path(folder)
        if directory == root:
            subfolders[:] = [name for name in subfolders
                             if name.casefold() not in excluded and (included is None or name.casefold() in included)]
            if included is not None:
                filenames = []
        for name in subfolders[:]:
            if name.casefold() == RECOVERY_FOLDER.casefold():
                subfolders.remove(name)
                continue
            try:
                child = directory / name
                if is_redirected(child.lstat()):
                    subfolders.remove(name)
                    warnings.append(f"Skipped redirected folder {child}")
                elif (child / REVIEW_LEDGER).is_file():
                    subfolders.remove(name)
            except OSError as error:
                subfolders.remove(name)
                warnings.append(str(error))
        for name in filenames:
            checkpoint(cancel)
            path = directory / name
            if path.suffix.lower() not in EXTENSIONS:
                continue
            try:
                info = path.lstat()
                if is_redirected(info) or not stat.S_ISREG(info.st_mode):
                    warnings.append(f"Skipped redirected or non-regular file {path}")
                    continue
                capture_time, time_source = ordering(path, info)
                clips.append(Clip(path, info.st_size, identity(info), capture_time, time_source))
            except (OSError, OverflowError, ValueError) as error:
                warnings.append(str(error))
    return sorted(clips, key=lambda clip: (clip.capture_time, str(clip.path).casefold(), str(clip.path))), warnings


def probe(clip, ffprobe, timeout,cancel=None):
    if identity(clip.path.lstat()) != clip.file_id:
        raise ValueError("Source changed after inventory")
    result = capture(
        [ffprobe, "-v", "error", "-protocol_whitelist", "file",
         "-show_packets", "-show_streams", "-show_format",
         "-show_data_hash", "sha256", "-show_entries",
         "packet=stream_index,pts,dts,duration,flags,data_hash:packet_side_data:stream_side_data:"
         "stream=index,codec_type,codec_name,time_base,extradata_hash,width,height,"
         "pix_fmt,color_range,color_space,color_transfer,color_primaries,channels,"
         "channel_layout,sample_rate,sample_fmt:"
         "format=start_time,duration", "-of", "json", str(clip.path)],
        cancel=cancel,stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode or result.stderr.strip():
        message = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ValueError(message[0] if message else f"FFprobe exited with {result.returncode}")
    if identity(clip.path.lstat()) != clip.file_id:
        raise ValueError("Source changed during probe")

    data = json.loads(result.stdout)
    streams = data["streams"]
    video = [position for position, stream in enumerate(streams) if stream["codec_type"] == "video"]
    if len(video) != 1 or any(stream["codec_type"] not in {"video", "audio"} for stream in streams):
        raise ValueError("Expected one video stream and only audio alongside it")
    layout_fields = ("codec_type", "codec_name", "extradata_hash", "width", "height",
                     "pix_fmt", "color_range", "color_space", "color_transfer",
                     "color_primaries", "channels", "channel_layout", "sample_rate", "sample_fmt",
                     "side_data_list")
    tracks = {}
    scales = {}
    for stream in streams:
        index = stream["index"]
        scale = float(Fraction(stream["time_base"]))
        if not math.isfinite(scale) or scale <= 0 or not stream.get("codec_name"):
            raise ValueError("Invalid track timing or codec")
        scales[index] = scale
        tracks[index] = Track(tuple(stream.get(field) for field in layout_fields), [], [], [], [], [], tick=scale)
    for packet_number,packet in enumerate(data["packets"]):
        if packet_number%4096==0:checkpoint(cancel)
        index = packet["stream_index"]
        track, scale = tracks[index], scales[index]
        flags = packet["flags"]
        # AAC priming can be explicitly marked discard with Skip Samples. It is
        # valid decoder metadata, not a corrupt packet; preserve and verify it.
        priming = (track.signature[0] == 'audio' and int(packet.get('pts',0)) < 0
                   and any(d.get('side_data_type') == 'Skip Samples' and d.get('skip_samples',0)>0
                           for d in packet.get('side_data_list',[])))
        if "C" in flags or "D" in flags and not priming:
            raise ValueError("Packet is flagged corrupt or discard")
        if packet.get("side_data_list"):
            track.side_data[len(track.hashes)] = packet["side_data_list"]
        track.hashes.append(packet["data_hash"])
        track.pts.append(int(packet["pts"]) * scale)
        track.dts.append(int(packet["dts"]) * scale if "dts" in packet else None)
        track.durations.append(int(packet.get("duration", 0)) * scale)
        if "K" in flags:
            track.keyframes.append(len(track.hashes) - 1)
    if any(not track.hashes for track in tracks.values()):
        raise ValueError("Empty media stream")
    duration = float(data["format"]["duration"])
    start = float(data["format"].get("start_time", 0))
    if not math.isfinite(duration) or not math.isfinite(start) or duration <= 0:
        raise ValueError("Invalid file duration")
    return Media(list(tracks.values()), duration, start, video[0])


def shared_count(earlier, current, index):
    count = len(earlier.hashes) - index
    if count > len(current.hashes) or earlier.hashes[index:] != current.hashes[:count]:
        return 0
    pts_shift = earlier.pts[index] - current.pts[0]
    tolerance = duration_tolerance(earlier, current)
    for position in range(count):
        old = index + position
        if abs(earlier.pts[old] - current.pts[position] - pts_shift) > PACKET_TIMING:
            return 0
        if earlier.side_data.get(old) != current.side_data.get(position):
            return 0
        if abs(earlier.durations[old] - current.durations[position]) > tolerance:
            # The muxer can shorten or omit the duration of the final packet.
            if position != count - 1:
                return 0
        old_dts, new_dts = earlier.dts[old], current.dts[position]
        if old_dts is not None and new_dts is not None:
            if abs(old_dts - new_dts - pts_shift) > PACKET_TIMING:
                return 0
    return count


def covered_until(track, count):
    # Presentation order can differ from packet order around a video cut.
    end = max(pts + duration for pts, duration in zip(track.pts[:count], track.durations[:count]))
    if count < len(track.pts):
        end = min(end, min(track.pts[count:]))
    return end


def complete_shared_count(earlier, current, index):
    count = shared_count(earlier, current, index)
    if count and earlier.durations[-1] + .000001 < current.durations[count - 1]:
        return count - 1
    return count


def find_match(current, earlier, reference, earlier_cut, overlap):
    if ([track.signature for track in current.tracks]
            != [track.signature for track in earlier.tracks]):
        return None
    video = current.tracks[current.video]
    prior_video = earlier.tracks[earlier.video]
    if not video.keyframes or video.keyframes[0] != 0:
        return None

    alignments = []
    for index in prior_video.keyframes:
        if prior_video.hashes[index] != video.hashes[0]:
            continue
        count = complete_shared_count(prior_video, video, index)
        if count:
            alignments.append((index, count))
    if len(alignments) != 1:
        return None

    index, count = alignments[0]
    if count == len(video.hashes):
        return None
    if earlier_cut is not None and min(prior_video.pts[index:]) < earlier_cut + AUDIO_ALIGNMENT:
        return None
    shift = prior_video.pts[index] - video.pts[0]
    video_end = covered_until(video, count)
    common_end = video_end

    for position, track in enumerate(current.tracks):
        if position == current.video:
            continue
        old = earlier.tracks[position]
        expected = track.pts[0] + shift
        ends = []
        for audio_index, pts in enumerate(old.pts):
            if abs(pts - expected) > PACKET_TIMING:
                continue
            matched = complete_shared_count(old, track, audio_index)
            if matched:
                if earlier_cut is not None and pts < earlier_cut + AUDIO_ALIGNMENT:
                    return None
                ends.append(covered_until(track, matched))
        if not ends:
            return None
        # Repeated silence can yield several matches. Use the shortest verified coverage.
        common_end = min(common_end, min(ends))

    safe_keys = [
        video.pts[key] for key in video.keyframes
        if key < count and current.start + 0.5 <= video.pts[key] <= common_end - overlap
        and min(video.pts[key:]) >= video.pts[key] - PACKET_TIMING
    ]
    if not safe_keys:
        return None
    return Match(reference, max(safe_keys), common_end, video_end - video.pts[0])


def safe_csv(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def audit(args, root, report, ffprobe, progress=print,cancel=None):
    from review_scan_cache import ScanCache
    path=getattr(args,'scan_cache',None);cache=ScanCache(path) if path else None
    original=progress
    if cache:progress=lambda message:original(message+(f' · {cache.hits} cached results reused' if cache.hits else ''))
    try:return _audit(args,root,report,ffprobe,progress,cancel,cache)
    finally:
        if cache:cache.close()

def _audit(args, root, report, ffprobe, progress=print,cancel=None,disk_cache=None):
    checkpoint(cancel)
    clips, warnings = inventory(root,cancel,getattr(args,'exclude_folders',()),
                                include_folders=getattr(args,'include_folders',None))
    end = min(len(clips), args.offset + args.limit) if args.limit else len(clips)
    start = min(args.offset, end)
    cache = OrderedDict()
    fields = ("status", "clip", "reference", "capture_time", "time_source", "original_seconds",
              "matched_video_overlap_seconds", "proposed_head_trim_seconds",
              "proposed_tail_trim_seconds", "retained_end_seconds", "head_overlap_kept_seconds",
              "tail_overlap_kept_seconds", "coverage", "source_identity",
              "minimum_shared_seconds_after_cut", "proposed_clip_seconds",
              "source_bytes", "estimated_bytes_saved", "audio_tracks", "note", "matches")

    def media(clip):
        checkpoint(cancel)
        try:
            if identity(clip.path.lstat()) != clip.file_id:
                return "Source changed after inventory"
        except OSError as error:
            return str(error)
        if clip.path not in cache:
            try:
                value=disk_cache.media(clip) if disk_cache else None
                if value is None:
                    value=probe(clip,ffprobe,args.probe_timeout,cancel)
                    if disk_cache:disk_cache.save_media(clip,value)
                cache[clip.path]=value
            except (OSError, ValueError, KeyError, OverflowError, ZeroDivisionError,
                    subprocess.SubprocessError) as error:
                cache[clip.path] = str(error)
        cache.move_to_end(clip.path)
        if len(cache) > 16:
            cache.popitem(last=False)
        return cache[clip.path]

    def relative(path):
        return str(path.relative_to(root))

    rows = {}
    details = {}
    starts = defaultdict(list)
    contains = defaultdict(list)
    protected, planned = set(), set()
    with report.open("x", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for warning in warnings:
            writer.writerow({"status": "inventory_warning", "note": safe_csv(warning)})
        scope_start, scope_end = max(0, start - args.lookback), min(len(clips), end + args.lookback)
        for position in range(scope_start, scope_end) if start < end else ():
            checkpoint(cancel)
            clip = clips[position]
            row = {"clip": relative(clip.path), "source_bytes": clip.size,
                   "capture_time": clip.capture_time.isoformat(sep=" "),
                   "time_source": clip.time_source}
            current = media(clip)
            if isinstance(current, str):
                row.update(status="skipped", note=current)
            else:
                row.update(original_seconds=round(current.duration, 3), audio_tracks=len(current.tracks) - 1)
                row.update(status="no_match", note="No independently verified trim in this scan.")
                video = current.tracks[current.video]
                if video.keyframes and video.keyframes[0] == 0:
                    keys = {video.hashes[i] for i in video.keyframes}
                    first = video.hashes[0]
                    starts[first].append(position)
                    for key in keys:
                        contains[key].append(position)
                    details[position] = current.duration, first, keys
            if start <= position < end:
                rows[position] = row
            progress(f"Indexed {position - scope_start + 1}/{scope_end - scope_start} · {clip.path.name}")

        possible = {}
        comparison_positions=[i for i in rows if i in details]
        for comparison_index,position in enumerate(comparison_positions):
            progress(f'Compared {comparison_index}/{len(comparison_positions)} clips')
            clip = clips[position]
            duration, first, keys = details[position]
            peers = set(contains[first])
            for key in keys:
                peers.update(starts[key])
            peers.discard(position)
            if not peers:
                continue
            current = media(clip)
            if isinstance(current, str):
                rows[position].update(status="skipped", note=current)
                continue
            proofs, positions, matches = [], {}, []
            for other in sorted(peers, key=lambda i: (abs(i - position), i)):
                checkpoint(cancel)
                reference = clips[other]
                gap = abs((clip.capture_time - reference.capture_time).total_seconds())
                if args.window_seconds and gap > args.window_seconds:
                    continue
                if clip.file_id[1] and reference.file_id[:2] == clip.file_id[:2]:
                    continue
                previous = media(reference)
                if isinstance(previous, str):
                    continue
                name = relative(reference.path)
                pair_key=[clip.file_id,reference.file_id,relative(clip.path),name]
                result=disk_cache.pair(pair_key) if disk_cache else None
                if result is None:
                    result=compare_pair(current,previous,name)
                    if disk_cache:disk_cache.save_pair(pair_key,result)
                proof,seconds,reason=result
                if seconds:
                    matches.append({"clip": name, "seconds": round(seconds, 3), "verified": proof is not None,
                                    "reason": reason, "identity": reference.file_id})
                if proof:
                    proofs.append(proof)
                    positions[proof.reference] = other
            initial = proposed_range(current, proofs, args.overlap)
            if matches:
                rows[position]["matches"] = json.dumps(matches, ensure_ascii=False)
                rows[position]["source_identity"] = json.dumps(clip.file_id)
                rows[position]["note"] = ("Verified overlap leaves no eligible cut with the current overlap setting."
                                          if proofs else "Matching video did not pass full coverage verification.")
            if initial:
                status, head, finish, _, _ = initial
                priority = 0 if status == "redundant" else 1 if head > 0 and finish < duration - .002 else 2
                possible[position] = priority, proofs, positions
        # Prefer fully covered clips and cuts supported from both ends. Once
        # used as evidence, a clip remains intact for this plan.
        for position in sorted(possible, key=lambda i: (possible[i][0], details[i][0], i)):
            checkpoint(cancel)
            if position in protected:
                continue
            _, proofs, positions = possible[position]
            clip = clips[position]
            duration = details[position][0]
            current = media(clip)
            if isinstance(current, str):
                rows[position].update(status="skipped", note=current)
                continue
            proofs = [proof for proof in proofs if positions[proof.reference] not in planned]
            result, supports = select_coverage(current, proofs, args.overlap)
            if not result:
                rows[position]["note"] = "A related clip is scheduled to change in this plan. Rescan after cleanup."
                continue
            status, head, finish, before, after = result
            tail = duration - finish if status == "candidate" else 0
            kept = finish - head
            protected.update(positions[proof.reference] for proof in supports)
            planned.add(position)
            rows[position].update(
                status=status, reference=relative(clips[positions[supports[0].reference]].path),
                proposed_head_trim_seconds=round(head, 6), proposed_tail_trim_seconds=round(tail, 6),
                retained_end_seconds=round(finish, 6), proposed_clip_seconds=round(kept, 3),
                head_overlap_kept_seconds=round(before, 3), tail_overlap_kept_seconds=round(after, 3),
                minimum_shared_seconds_after_cut=round(min((n for n in (before, after) if n), default=0), 3),
                matched_video_overlap_seconds=round(max(proof.end - proof.start for proof in supports), 3),
                estimated_bytes_saved=int(clip.size * max(0, 1 - kept / duration)),
                source_identity=json.dumps(clip.file_id),
                coverage=json.dumps([{"clip": proof.reference, "offset": round(proof.offset, 6),
                                      "start": round(proof.start, 6), "end": round(proof.end, 6),
                                      "identity": clips[positions[proof.reference]].file_id}
                                     for proof in supports], ensure_ascii=False),
                note=("Every encoded packet is covered by the listed originals. Review only."
                      if status == "redundant" else "Estimated bytes from duration; export verification required."),
            )
        for position, row in rows.items():
            checkpoint(cancel)
            if position in protected:
                row.update(status="reference", note="Keep intact as coverage for another proposed edit.")
            writer.writerow({field: safe_csv(value) for field, value in row.items()})
    candidates = sum(row["status"] == "candidate" for row in rows.values())
    redundant = sum(row["status"] == "redundant" for row in rows.values())
    estimated_bytes = sum(row.get("estimated_bytes_saved", 0) for row in rows.values())
    progress(f"Scanned {end - start} of {len(clips)} inventoried clips. "
             f"{candidates} trim candidates, {redundant} fully covered, "
             f"{estimated_bytes / 1024 ** 3:.2f} GiB estimated reduction.")
    if end < len(clips):
        progress(f"Next batch in the same unchanged folder inventory: --offset {end} with a new report file.")


def main():
    parser = argparse.ArgumentParser(
        description="Audit encoded replay overlap and write a CSV. Originals are opened only for reading.",
        epilog="Requires FFprobe. Example: python review_overlap_audit.py \"D:/Clips\" "
               "--report \"D:/Review/overlap.csv\" --limit 30",
    )
    parser.add_argument("source", type=Path, help="Any folder containing replay clips, searched recursively")
    parser.add_argument("--report", type=Path, required=True, help="New CSV path outside the source tree")
    parser.add_argument("--overlap", type=float, default=10, help="Minimum shared seconds to retain (default 10)")
    parser.add_argument("--limit", type=int, default=30, help="Number of report rows to scan (0 for all, default 30)")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many clips in the sorted inventory")
    parser.add_argument("--lookback", type=int, default=12, help="Extra reference clips on either side of a batch (default 12)")
    parser.add_argument("--window-seconds", type=int, default=0,
                        help="Optional max difference between capture times (default 0, no time limit)")
    parser.add_argument("--probe-timeout", type=int, default=120, help="FFprobe timeout per clip, in seconds")
    parser.add_argument("--ffprobe", default="ffprobe", help="FFprobe executable or its full path")
    args = parser.parse_args()
    if (not math.isfinite(args.overlap) or args.overlap < 1 or args.limit < 0 or args.offset < 0
            or args.lookback < 1 or args.window_seconds < 0 or args.probe_timeout < 1):
        parser.error("Invalid overlap, limit, offset, lookback, window, or timeout")
    ffprobe = shutil.which(args.ffprobe)
    if not ffprobe:
        parser.error("FFprobe not found. Install FFmpeg or pass --ffprobe with the executable path")
    try:
        root = args.source.resolve(strict=True)
        report = args.report.parent.resolve(strict=True) / args.report.name
        if not root.is_dir() or report.suffix.lower() != ".csv" or report.is_relative_to(root):
            parser.error("Use an existing source folder and a new CSV outside it")
        audit(args, root, report, ffprobe)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Audit stopped: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
