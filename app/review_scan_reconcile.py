# SPDX-License-Identifier: GPL-3.0-or-later
"""Reconnect unambiguous external moves without discarding reviewed records."""
from collections import defaultdict
from pathlib import Path


def path_key(value):return Path(value).as_posix().casefold()


def source_key(path,identity):
    if not identity or 'size' not in identity or 'mtime_ns' not in identity:return None
    return Path(path).name.casefold(),identity['size'],identity['mtime_ns']


def placeholder(clip):
    # Only replace the pristine row created by an earlier rescan. A second
    # reviewed record may have independent annotations and must be kept.
    fields={'id','path','decision','ranges','position','media','mix','identity','missing'}
    return not (clip.keys()-fields) and not any(clip.get(k) for k in ('ranges','position','media','mix'))


def reconcile(project,data,files):
    """Return changed/discarded IDs. Never move, write or hash media files."""
    known={path_key(c['path']):c for c in data['clips']}
    missing=defaultdict(list);present=defaultdict(list)
    folders=project.folders()
    for clip in data['clips']:
        if path_key(clip['path']) not in files and not project.checked(clip['path']).is_file():
            key=source_key(clip['path'],clip.get('identity'))
            if key is not None:missing[key].append(clip)
    for key,(relative,status,identity) in files.items():
        present[source_key(relative,identity)].append((relative,status,identity))
    changed=set();discarded=set()
    for key,clips in missing.items():
        matches=present.get(key,[])
        if len(clips)!=1 or len(matches)!=1:continue
        clip=clips[0];relative,status,identity=matches[0]
        duplicate=known.get(path_key(relative))
        if duplicate is not None and not placeholder(duplicate):continue
        old_path=project.checked(clip['path'])
        old_status=next((role for role,folder in folders.items() if old_path.is_relative_to(folder.resolve())),None)
        # Follow a manual folder move, while retaining an unrelated pending
        # sorting decision that the user has not saved yet.
        if clip['decision']==old_status:clip['decision']=status
        clip.update(path=relative,identity=identity,missing=False)
        changed.add(clip['id'])
        if duplicate is not None:
            discarded.add(duplicate['id'])
            if data.get('current_clip')==duplicate['id']:data['current_clip']=clip['id']
    if discarded:data['clips'][:]=[c for c in data['clips'] if c['id'] not in discarded]
    return changed,discarded
