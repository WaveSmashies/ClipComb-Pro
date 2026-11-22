# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit, recoverable cleanup of a single clip from the review UI."""

import ctypes
from ctypes import wintypes
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import uuid

from review_overlap_audit import (
    Clip, RECOVERY_FOLDER, covers_packets, find_match, identity, is_redirected,
    pair_coverage, probe, proposed_range, video_alignment,
)
from review_cleanup_core import (
    DATABASE, RESERVE_BYTES, archive_clip, check_report_identities, connection, export_lock,
    hash_file, list_copies, recorded_media, stream_labels, verify_labels, verify_retained,
    verify_slice, witnesses,
)


SAFETY_BINDING = ".replay-trim-ledger.json"
SAFETY_BACKUP = ".replay-trim-ledger-backup.json"
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x1
FILE_SHARE_DELETE = 0x4
OPEN_EXISTING = 3


def actions(destination):
    if not (destination / DATABASE).is_file():
        return []
    with connection(destination) as db:
        rows = db.execute("SELECT id, kind, source, recovery, state, details FROM review_actions ORDER BY rowid").fetchall()
    return [dict(id=ident, kind=kind, source=source, recovery=recovery, state=state, **json.loads(details))
            for ident, kind, source, recovery, state, details in rows]


def check_file(path, expected=None):
    info = path.lstat()
    if is_redirected(info) or not stat.S_ISREG(info.st_mode) or path.resolve(strict=True) != path:
        raise ValueError(f"Expected a regular file at {path}.")
    value = identity(info)
    if expected is not None and list(value) != list(expected):
        raise ValueError(f"{path.name} changed since verification.")
    return value


def extended(path):
    value = str(path)
    return "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value


@contextmanager
def protect_media(path, moving=False):
    if os.name != "nt":
        raise ValueError("Archive cleanup requires Windows file protection.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_file = kernel.CreateFileW
    open_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                          wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    open_file.restype = wintypes.HANDLE
    close_file = kernel.CloseHandle
    close_file.argtypes = [wintypes.HANDLE]
    close_file.restype = wintypes.BOOL
    share = FILE_SHARE_READ | (FILE_SHARE_DELETE if moving else 0)
    handle = open_file(extended(path), GENERIC_READ, share, None, OPEN_EXISTING, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.WinError(ctypes.get_last_error())
        raise ValueError(f"Could not protect {path.name} during cleanup.\n{error}") from error
    try:
        yield
    finally:
        close_file(handle)


def existing_recovery_receipts(root):
    def fail(error):
        raise error

    for directory, folders, files in os.walk(root, onerror=fail):
        if SAFETY_BACKUP in files:
            marker = Path(directory) / SAFETY_BACKUP
            check_file(marker)
            saved = json.loads(marker.read_text(encoding="utf-8"))
            ledger = Path(saved["ledger"])
            if list(check_file(ledger)[:2]) != saved["identity"]:
                raise ValueError(f"The cleanup ledger changed. Check {ledger}.")
            yield from (action for action in actions(ledger.parent) if Path(action["source"]).parent == Path(directory))
        for name in folders[:]:
            folder = Path(directory) / name
            if name.casefold() == RECOVERY_FOLDER.casefold():
                folders.remove(name)
                if is_redirected(folder.lstat()):
                    raise ValueError(f"The recovery folder is redirected. Check {folder}.")
                for run in folder.iterdir():
                    if is_redirected(run.lstat()):
                        raise ValueError(f"A recovery entry is redirected. Check {run}.")
                    if not run.is_dir():
                        continue
                    receipt = run / "recovery.json"
                    try:
                        check_file(receipt)
                    except FileNotFoundError:
                        continue
                    yield json.loads(receipt.read_text(encoding="utf-8"))
            elif is_redirected(folder.lstat()) or (folder / DATABASE).is_file():
                folders.remove(name)


def bind_cleanup_folders(root, destination, folders):
    ledger = destination / DATABASE
    with connection(destination):
        ledger_id = check_file(ledger)[:2]
    binding = {"ledger": str(ledger), "identity": list(ledger_id)}
    missing = []
    for folder in folders:
        for name in (SAFETY_BINDING, SAFETY_BACKUP):
            marker = folder / name
            try:
                check_file(marker)
            except FileNotFoundError:
                missing.append(marker)
                continue
            saved = json.loads(marker.read_text(encoding="utf-8"))
            if Path(saved["ledger"]) != ledger or saved["identity"] != binding["identity"]:
                raise ValueError(f"This archive folder uses another cleanup ledger. Open its original review folder.\n{saved['ledger']}")
    if not missing:
        return

    known = {action["id"]: action for action in actions(destination)}
    for receipt in existing_recovery_receipts(root):
        affected = {Path(path).parent for path in [receipt["source"], *receipt.get("supports", [])]}
        if receipt["kind"] == "delete_trimmed" or affected.isdisjoint(folders):
            continue
        action = known.get(receipt["id"])
        if not action or Path(action["recovery"]) != Path(receipt["recovery"]):
            raise ValueError(f"An earlier cleanup of {Path(receipt['source']).name} belongs to another review ledger. "
                             "Open the review folder used for that cleanup.")
    for marker in missing:
        with marker.open("x", encoding="utf-8") as file:
            json.dump(binding, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())


def current_record(destination, record_id):
    record = next((r for r in list_copies(destination)
                   if r["id"] == record_id and r["state"] == "verified"), None)
    if not record or "audio_names" not in record:
        raise ValueError("A current verified trimmed copy is required.")
    return record


def supporting_paths(record):
    return record.get("coverage_references", [record["reference"]])


def validate_recovery_path(action, destination):
    source, recovery = Path(action["source"]), Path(action["recovery"])
    roots = {source.parent / RECOVERY_FOLDER, destination / RECOVERY_FOLDER}
    if action.get("recovery_root"):
        root = Path(action["recovery_root"])
        if not root.is_absolute() or root.name != RECOVERY_FOLDER:
            raise ValueError("The recorded recovery folder is invalid.")
        roots.add(root)
    if not any(recovery == root / action["id"] / source.name for root in roots):
        raise ValueError(f"Unexpected recovery path for {source.name}.")
    return recovery


def check_dependencies(destination, source):
    for record in list_copies(destination):
        if record["state"] == "verified" and source in map(Path, supporting_paths(record)):
            raise ValueError(f"Keep this original. The verified copy of {Path(record['source']).name} uses it as coverage.")
    for action in actions(destination):
        if (action["state"] in {"started", "done"} and (not action.get("manual_overlap") or action["state"] == "started")
                and source in map(Path, action.get("supports", []))):
            raise ValueError(f"Keep this original. It covers an earlier cleanup of {Path(action['source']).name}.")


def verify_replacement_dependencies(root, destination, source, replacement, ffprobe, protect=None):
    """Prove earlier archive edits remain covered by the files that will be active."""
    affected = [action for action in actions(destination) if action["kind"] != "delete_trimmed"
                and (not action.get("manual_overlap") or action["state"] == "started")
                and action["state"] in {"started", "done"}
                and source.path in map(Path, action.get("supports", []))]
    if not affected:
        return {}
    records = {record["id"]: record for record in list_copies(destination)}
    inputs = {}
    media = {}

    def read(path, expected=None):
        if protect:
            protect(path)
        file_id = check_file(path, expected)
        if path in inputs and inputs[path] != file_id:
            raise ValueError(f"{path.name} changed while checking earlier coverage.")
        if path not in inputs:
            clip = Clip(path, file_id[2], file_id, source.capture_time, "coverage check")
            media[path] = probe(clip, ffprobe, 180)
            inputs[path] = file_id
        return media[path]

    for action in affected:
        previous = Path(action["source"])
        recovery = Path(action["recovery"])
        try:
            if action["state"] != "done":
                raise ValueError("An earlier cleanup still needs recovery review.")
            validate_recovery_path(action, destination)
            if not previous.is_relative_to(root):
                raise ValueError("The earlier recovery path is outside this archive.")
            if not recovery.is_file():
                raise ValueError("The full recovery copy is needed to recheck the earlier cut.")
            original = read(recovery, action.get("recovery_identity", action["original_identity"]))
            if action.get("recovery_sha256") and hash_file(recovery) != action["recovery_sha256"]:
                raise ValueError("The earlier recovery file checksum differs.")
            proofs = []
            for path in map(Path, action["supports"]):
                if path == source.path:
                    peer = replacement
                else:
                    peer = archive_clip(root, str(path.relative_to(root))).path
                if proof := pair_coverage(original, read(peer), str(path)):
                    proofs.append(proof)
            if (forwarded := action.get("coverage_via_merge")) and "spans" in forwarded:
                if not all(covers_packets(proofs, i, start, end) for i, (start, end) in enumerate(forwarded["spans"])):
                    raise ValueError("Some packets carried forward by the merge would no longer be covered.")
            elif action.get("copy_id") and not forwarded:
                prior = records[action["copy_id"]]
                if Path(prior["source"]) != previous:
                    raise ValueError("The earlier verified copy belongs to a different original.")
                if action["kind"] == "replace_original":
                    kept = archive_clip(root, str(previous.relative_to(root))).path
                elif prior["state"] == "verified":
                    kept = Path(prior["output"])
                else:
                    raise ValueError("The earlier verified copy is unavailable.")
                retained = read(kept)
                if hash_file(kept) != prior["copy_sha256"]:
                    raise ValueError("The earlier retained copy has changed.")
                verify_slice(original, retained, original.start + prior["trim_start_seconds"],
                             original.start + prior.get("retained_end_seconds", original.duration), proofs)
            elif not all(covers_packets(proofs, i, 0, len(track.hashes))
                         for i, track in enumerate(original.tracks)):
                raise ValueError("Some of the earlier clip's encoded packets would no longer be covered.")
        except (OSError, ValueError, KeyError) as error:
            raise ValueError(f"Cannot verify continued coverage for {previous.name}.\n{error}") from error
    return inputs


def verify_original(root, source, row, record, ffprobe, overlap):
    peers = [archive_clip(root, entry["clip"]) for entry in witnesses(row)]
    check_report_identities(row, source, peers)
    if not peers or any(peer.path == source.path or peer.file_id[1] and peer.file_id[:2] == source.file_id[:2]
                        for peer in peers):
        raise ValueError("The source cannot serve as its own coverage.")
    if record:
        check_file(source.path, record["source_identity"])
        if [str(peer.path) for peer in peers] != supporting_paths(record):
            raise ValueError("The verified copy uses a different set of supporting clips.")
        if [list(peer.file_id) for peer in peers] != record["coverage_identities"]:
            raise ValueError("A supporting original changed after the copy was verified.")
    elif not row.get("source_identity") or list(source.file_id) != json.loads(row["source_identity"]):
        raise ValueError("Scan the archive again to confirm the fully covered clip.")

    media = probe(source, ffprobe, 180)
    if record:
        names = verify_labels(media, stream_labels(source.path, ffprobe), stream_labels(record["output"], ffprobe))
        if names != record["audio_names"]:
            raise ValueError("The verified audio track names no longer match the original.")
    if row.get("coverage"):
        proofs = []
        for peer in peers:
            proof = pair_coverage(media, probe(peer, ffprobe, 180), str(peer.path))
            if proof is None:
                raise ValueError(f"Could not verify coverage from {peer.path.name}.")
            proofs.append(proof)
        if record:
            copy = recorded_media(record, ffprobe, source)
            verify_slice(media, copy, media.start + record["trim_start_seconds"],
                         media.start + record["retained_end_seconds"], proofs)
        else:
            plan = proposed_range(media, proofs, overlap)
            if not plan or plan[0] != "redundant":
                raise ValueError("The supporting clips no longer cover every video and audio packet.")
    else:
        if not record:
            raise ValueError("A verified copy is required.")
        proof = find_match(media, probe(peers[0], ffprobe, 180), peers[0], None,
                           record["requested_overlap_seconds"])
        if not proof:
            raise ValueError("The original overlap could not be reverified.")
        copy = recorded_media(record, ffprobe, source)
        verify_retained(media, copy, media.start + record["trim_start_seconds"], proof.shared_end)
    return peers


def recovery_path(path, run_id, destination):
    recovery = destination / RECOVERY_FOLDER
    recovery.mkdir(exist_ok=True)
    if recovery.resolve(strict=True) != recovery or is_redirected(recovery.lstat()):
        raise ValueError("The recovery folder is redirected.")
    folder = recovery / run_id
    folder.mkdir()
    return folder / path.name


def same_volume(source, target):
    return source.stat().st_dev == target.parent.stat().st_dev


def copy_verified(source, target, checksum):
    before = check_file(source)
    if shutil.disk_usage(target.parent).free < before[2] + RESERVE_BYTES:
        raise ValueError("There is insufficient room in the selected recovery folder.")
    with source.open("rb") as read, target.open("xb") as write:
        shutil.copyfileobj(read, write, 4 * 1024 ** 2)
        write.flush()
        os.fsync(write.fileno())
    shutil.copystat(source, target)
    if hash_file(target) != checksum:
        raise ValueError(f"The recovery checksum differs for {source.name}.")
    check_file(source, before)
    return check_file(target)


def prepare_recovery_file(source, target, checksum):
    return check_file(source) if same_volume(source, target) else copy_verified(source, target, checksum)


def move_to_recovery(source, target, checksum):
    if same_volume(source, target):
        source.rename(target)
    else:
        if hash_file(target) != checksum:
            raise ValueError("The verified recovery copy changed before moving the original.")
        source.unlink()


def restore_recovery(source, target, checksum):
    if same_volume(source, target):
        source.rename(target)
    else:
        copy_verified(source, target, checksum)


def replace_file(path, staged, backup):
    if os.name != "nt":
        raise ValueError("Replacing a clip in place requires Windows.")
    api = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
    api.argtypes = [wintypes.LPCWSTR] * 3 + [wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID]
    api.restype = wintypes.BOOL

    local_backup = backup
    folder = None
    if not same_volume(path, backup):
        folder = tempfile.TemporaryDirectory(prefix=".review-work-replace-", dir=path.parent)
        local_backup = Path(folder.name) / path.name
    if not api(extended(path), extended(staged), extended(local_backup), 0, None, None):
        error = ctypes.WinError(ctypes.get_last_error())
        if not path.exists() and local_backup.is_file():
            try:
                local_backup.rename(path)
            except OSError as rollback:
                raise ValueError(f"The original is in recovery at {backup}. Automatic restoration failed: {rollback}") from error
        raise error
    if folder:
        folder.cleanup()


def cleanup(root, destination, row, kind, record_id, ffprobe, overlap, manual_overlap=False):
    if kind not in {"delete_original", "delete_trimmed", "replace_original"}:
        raise ValueError("Unknown cleanup action.")
    if manual_overlap and (kind != "delete_original" or record_id or not row.get("source_identity")):
        raise ValueError("Manual overlap removal requires a current comparison and a full recovery file.")
    with export_lock(destination), ExitStack() as locks:
        source = archive_clip(root, row["clip"])
        peer_paths = [] if kind == "delete_trimmed" else [
            archive_clip(root, entry["clip"]).path for entry in witnesses(row)]
        folders = {path.parent for path in [source.path, *peer_paths]}
        for folder in sorted(folders):
            locks.enter_context(export_lock(folder, ".replay-trim-safety.lock"))
        record = current_record(destination, record_id) if record_id else None
        if any(action["state"] == "started" and Path(action["source"]) == source.path
               for action in actions(destination)):
            raise ValueError("An earlier cleanup of this clip still needs recovery review.")
        if record and Path(record["source"]) != source.path:
            raise ValueError("The selected copy belongs to a different original.")
        copy = Path(record["output"]) if record else None
        moving = copy if kind == "delete_trimmed" else source.path
        protected = set()

        def protect(path):
            if path not in protected:
                locks.enter_context(protect_media(path, path == moving))
                protected.add(path)

        for path in [source.path, *peer_paths]:
            protect(path)
        if copy:
            protect(copy)
        check_file(source.path, source.file_id)
        copy_id = check_file(copy) if copy else None
        if copy and hash_file(copy) != record["copy_sha256"]:
            raise ValueError("The trimmed copy changed since verification.")
        peers = []
        dependencies = {}
        if kind == "delete_trimmed":
            if record is None:
                raise ValueError("Select a verified trimmed copy first.")
            if list(source.file_id) != record["source_identity"] and hash_file(source.path) != record["copy_sha256"]:
                raise ValueError("The full original or its verified replacement must still exist to remove the trimmed copy.")
            target, target_id = copy, copy_id
        else:
            if record is None and not manual_overlap and (kind != "delete_original" or row["status"] != "redundant"):
                raise ValueError("Make a verified trimmed copy before removing the original.")
            if kind == "delete_original":
                check_dependencies(destination, source.path)
            if manual_overlap:
                peers = [archive_clip(root, entry["clip"]) for entry in witnesses(row)]
                check_report_identities(row, source, peers)
                original = probe(source, ffprobe, 180)
                if not any(peer.file_id[:2] != source.file_id[:2] and
                           video_alignment(original, probe(peer, ffprobe, 180)) for peer in peers):
                    raise ValueError("No remaining clip could verify a video overlap. Scan again.")
            else:
                peers = verify_original(root, source, row, record, ffprobe, overlap)
            if kind == "replace_original":
                dependencies = verify_replacement_dependencies(root, destination, source, copy, ffprobe, protect)
            target, target_id = source.path, source.file_id
        if kind == "replace_original" and shutil.disk_usage(target.parent).free < copy_id[2] + RESERVE_BYTES:
            raise ValueError("There is not enough room to stage the replacement next to the original.")

        bind_cleanup_folders(root, destination, folders)
        target_hash = record["copy_sha256"] if kind == "delete_trimmed" else hash_file(target)
        run_id = uuid.uuid4().hex
        backup = recovery_path(target, run_id, destination)
        recovery_id = prepare_recovery_file(target, backup, target_hash)
        if backup.is_file():
            protect(backup)
        details = {"target": str(target), "copy_id": record_id,
                   "verified_copy": str(copy) if copy else None,
                   "original_identity": list(source.file_id),
                   "recovery_sha256": target_hash, "recovery_identity": list(recovery_id),
                   "recovery_root": str(destination / RECOVERY_FOLDER),
                   "supports": [str(peer.path) for peer in peers]}
        if manual_overlap:
            details["manual_overlap"] = True
        receipt = dict(id=run_id, kind=kind, source=str(source.path), recovery=str(backup), **details)
        with (backup.parent / "recovery.json").open("x", encoding="utf-8") as file:
            json.dump(receipt, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        with connection(destination) as db:
            db.execute("INSERT INTO review_actions VALUES (?, ?, ?, ?, ?, ?, ?)", (
                run_id, datetime.now(timezone.utc).isoformat(), kind, str(source.path), str(backup),
                "started", json.dumps(details),
            ))

        staged = (Path(locks.enter_context(tempfile.TemporaryDirectory(prefix=".review-work-replacement-", dir=target.parent)))
                  / target.name) if kind == "replace_original" else None
        try:
            if kind == "replace_original":
                with copy.open("rb") as read, staged.open("xb") as write:
                    shutil.copyfileobj(read, write, 4 * 1024 ** 2)
                    write.flush()
                    os.fsync(write.fileno())
                if hash_file(staged) != record["copy_sha256"]:
                    raise ValueError("The staged replacement did not match the verified copy.")
                os.utime(staged, ns=(source.path.stat().st_atime_ns, source.file_id[3]))
            check_file(source.path, source.file_id)
            check_file(target, target_id)
            if copy:
                check_file(copy, copy_id)
            for peer in peers:
                check_file(peer.path, peer.file_id)
            for path, file_id in dependencies.items():
                check_file(path, file_id)
            if kind == "replace_original":
                replace_file(target, staged, backup)
                if hash_file(target) != record["copy_sha256"]:
                    raise ValueError("Replacement needs manual review. Check the original and recovery paths.")
            else:
                if (same_volume(target, backup) and backup.exists()) or backup.is_symlink():
                    raise ValueError("The recovery destination is occupied.")
                move_to_recovery(target, backup, target_hash)
            check_file(backup, recovery_id)
            if hash_file(backup) != target_hash:
                raise ValueError("The recovery file checksum differs. Keep the recovery folder for manual review.")
            with connection(destination) as db:
                if kind == "delete_trimmed":
                    db.execute("UPDATE copies SET state='trimmed_in_recovery', output=? WHERE id=?",
                               (str(backup), record_id))
                db.execute("UPDATE review_actions SET state='done' WHERE id=?", (run_id,))
        except Exception as error:
            status = "started"
            try:
                check_file(target, target_id)
                if not backup.exists():
                    status = "failed"
            except (OSError, ValueError):
                pass
            with connection(destination) as db:
                db.execute("UPDATE review_actions SET state=? WHERE id=?", (status, run_id))
            raise ValueError(f"{error}\nRecovery location: {backup.parent}") from error
    return receipt
