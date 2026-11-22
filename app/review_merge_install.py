# SPDX-License-Identifier: GPL-3.0-or-later
"""Commit a new merged clip and retain every source in the project's Deleted folder."""
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from review_cleanup_core import hash_file,export_lock,connection,RESERVE_BYTES,DATABASE
from review_cleanup_actions import protect_media,check_file
from review_cleanup_merge import merge_dependencies
from review_trim_install import checked,rename_exclusive

JOURNAL='.clipcomb-merge-transaction.json'


def unique(folder,name,reserved=()):
    target=folder/name;number=2
    while target.exists() or target.is_symlink() or target in reserved:
        target=folder/(Path(name).stem+f'_{number}'+Path(name).suffix);number+=1
    return target


def output_path(project,merge,original_name=False):
    folder=checked(project.root,str(project.folders()['Unused'].relative_to(project.root)))
    source=merge.clips[0].path
    if original_name:return source
    if original_name:return source
    return unique(folder,source.stem+'_MERGED'+source.suffix)


def recover(root,metadata=None,project_file=None):
    from review_core import PROJECT_FILE
    root=Path(root).resolve();metadata=Path(metadata) if metadata else root;journal=metadata/JOURNAL
    if not journal.is_file():return
    state=json.loads(journal.read_text(encoding='utf-8'))
    if state.get('schema')!=1:raise ValueError('Unknown merge recovery journal. Keep this project intact for recovery.')
    target=checked(root,state['output']['path']);digest=state['output']['sha256']
    entries=[(checked(root,e['source']),checked(root,e['backup']),e['sha256']) for e in state['originals']]
    project_file=Path(project_file) if project_file else root/PROJECT_FILE
    saved=json.loads(project_file.read_text(encoding='utf-8')) if project_file.exists() else {}
    if saved.get('media_transaction')==state['id']:
        for path,expected in [(target,digest),*((backup,sha) for _,backup,sha in entries)]:
            if not path.is_file() or hash_file(path)!=expected:raise ValueError(f'Merge recovery needs review: {path}')
        # Earlier archive actions continue to depend on the same complete media,
        # now in Deleted. This update is idempotent across an interrupted commit.
        updates=state.get('ledger_updates',[])
        if updates:
            ledger=Path(state['ledger'])
            if list(check_file(ledger/DATABASE)[:2])!=state['ledger_identity']:
                raise ValueError('The archive ledger changed. Keep the merge recovery journal.')
            with connection(ledger) as db:
                for update in updates:
                    row=db.execute('SELECT details FROM review_actions WHERE id=? AND state=\'done\'',(update['id'],)).fetchone()
                    if row is None or json.loads(row[0]) not in (update['before'],update['after']):
                        raise ValueError('An earlier archive action changed during merge recovery. Keep the merge journal.')
                    db.execute('UPDATE review_actions SET details=? WHERE id=?',(json.dumps(update['after']),update['id']))
    else:
        # Validate every affected file before removing or restoring anything.
        target_is_original=any(target==source and not backup.exists() and target.exists() and hash_file(target)==sha for source,backup,sha in entries)
        if target.exists() and not target_is_original and hash_file(target)!=digest:raise ValueError(f'Merge recovery will not remove a changed output: {target}')
        for source,backup,sha in entries:
            if backup.exists() and hash_file(backup)!=sha:raise ValueError(f'The recovery original changed: {backup}')
            if source.exists() and not (source==target and not target_is_original and hash_file(source)==digest) and hash_file(source)!=sha:raise ValueError(f'Merge recovery will not overwrite a changed file: {source}')
            if not source.exists() and not backup.exists():raise ValueError(f'A merge original needs manual recovery: {source}')
        if target.exists() and not target_is_original:target.unlink()
        for source,backup,_ in reversed(entries):
            if source!=backup and backup.exists() and not source.exists():rename_exclusive(backup,source)
    journal.unlink()


def install(project,merge,record,ledger,progress=lambda text:None,target=None):
    from review_core import atomic_json,file_identity
    root=project.root;metadata=project.metadata;recover(root,metadata,project.path);ledger=Path(ledger)
    target=target or output_path(project,merge);target=checked(root,str(target.relative_to(root)))
    if target.exists() and target not in [c.path for c in merge.clips]:raise ValueError('The proposed merged filename is now occupied. Prepare the merge again.')
    on_disk=json.loads(project.path.read_text(encoding='utf-8')) if project.path.exists() else None
    if on_disk is not None and on_disk.get('transaction','')!=project.data.get('transaction',''):
        raise ValueError('Another app window saved this project. Reload it before merging.')
    before=copy.deepcopy(project.data);dirty=project.dirty
    by_path={str(project.checked(c['path'])).casefold():c for c in project.data['clips']}
    records=[by_path[str(c.path).casefold()] for c in merge.clips]
    deleted=checked(root,str(project.folders()['Deleted'].relative_to(root)))
    reserved=set();backups=[]
    for clip in merge.clips:
        backup=clip.path if clip.path.parent==deleted else unique(deleted,clip.path.name,reserved)
        reserved.add(backup);backups.append(backup)
    transaction=uuid.uuid4().hex
    entries=[dict(source=str(c.path.relative_to(root)),backup=str(b.relative_to(root)),sha256=sha)
             for c,b,sha in zip(merge.clips,backups,merge.original_checksums)]
    replacements={str(c.path):str(b) for c,b in zip(merge.clips,backups)}
    updates=[]
    for action in merge.dependencies:
        details={k:v for k,v in action.items() if k not in {'id','kind','source','recovery','state'}}
        new=copy.deepcopy(details)
        new['supports']=[replacements.get(p,p) for p in details.get('supports',[])]
        if str(action['source']) in replacements and not new['supports']:new['supports']=[replacements[str(action['source'])]]
        updates.append(dict(id=action['id'],before=details,after=new))
    state=dict(schema=1,id=transaction,originals=entries,output=dict(path=str(target.relative_to(root)),sha256=merge.checksum),
               ledger=str(ledger),ledger_updates=updates)
    if updates:state['ledger_identity']=list(check_file(ledger/DATABASE)[:2])
    with export_lock(ledger),ExitStack() as guards:
        for folder in sorted({metadata}):
            guards.enter_context(export_lock(folder,'.replay-trim-safety.lock'))
        guards.enter_context(protect_media(merge.path));check_file(merge.path)
        if hash_file(merge.path)!=merge.checksum:raise ValueError('The verified merge changed before installation.')
        if merge_dependencies(ledger,merge.clips)!=merge.dependencies:raise ValueError('Earlier archive records changed. Prepare the merge again.')
        for path,(file_id,checksum) in merge.dependency_files.items():
            guards.enter_context(protect_media(path));check_file(path,file_id)
            if hash_file(path)!=checksum:raise ValueError('An earlier archive dependency changed. Nothing was moved.')
        for clip,sha in zip(merge.clips,merge.original_checksums):
            if checked(root,str(clip.path.relative_to(root)))!=clip.path:raise ValueError('A merge input leaves its project.')
            guards.enter_context(protect_media(clip.path,moving=True));check_file(clip.path,clip.file_id)
            if hash_file(clip.path)!=sha:raise ValueError('A source changed after merge verification. Nothing was moved.')
        if shutil.disk_usage(root).free<merge.path.stat().st_size+RESERVE_BYTES:raise ValueError('Insufficient space to stage the merge.')
        target.parent.mkdir(parents=True,exist_ok=True);deleted.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.clipcomb-merge-install-',dir=target.parent) as temporary:
            stage=Path(temporary)/target.name
            progress('Staging the verified merge…')
            with merge.path.open('rb') as inp,stage.open('xb') as out:
                shutil.copyfileobj(inp,out,4*1024**2);out.flush();os.fsync(out.fileno())
            if hash_file(stage)!=merge.checksum:raise ValueError('The installation copy failed verification.')
            for clip,sha in zip(merge.clips,merge.original_checksums):
                check_file(clip.path,clip.file_id)
                if hash_file(clip.path)!=sha:raise ValueError('A source changed during merge preparation.')
            latest=json.loads(project.path.read_text(encoding='utf-8')) if project.path.exists() else None
            if latest!=on_disk:raise ValueError('The saved project changed. Nothing was moved.')
            atomic_json(metadata/JOURNAL,state)
            try:
                progress('Moving originals to Deleted and installing the new merged clip…')
                for clip,backup in zip(merge.clips,backups):
                    if clip.path!=backup:rename_exclusive(clip.path,backup)
                rename_exclusive(stage,target)
                if hash_file(target)!=merge.checksum:raise ValueError('Installed merge failed verification.')
                for clip,backup,sha in zip(records,backups,merge.original_checksums):
                    if hash_file(backup)!=sha:raise ValueError('An original backup failed verification.')
                    clip.update(path=str(backup.relative_to(root)),decision='Deleted',identity=file_identity(backup),missing=False,changed_source=False)
                merged=copy.deepcopy(record)
                merged.update(id=uuid.uuid4().hex,path=str(target.relative_to(root)),decision='Unused',identity=file_identity(target),
                              media=None,position=0,trim_ranges=[],missing=False,changed_source=False,merged_by_clipcomb=True)
                # Preserve source ids, but point provenance at the retained originals.
                for span in merged.get('provenance',[]):
                    source=next((c for c in records if c['id']==span['source_id']),None)
                    if source:span['source_path']=source['path']
                project.data['clips'].append(merged)
                receipt=metadata/f'clipcomb-merge-{transaction}.json'
                atomic_json(receipt,dict(state,original_records=[c for c in before['clips'] if c['id'] in {r['id'] for r in records}],
                                        merged=merged,track_placements=merge.track_placements))
                saved=copy.deepcopy(on_disk) if on_disk is not None else copy.deepcopy(before)
                affected={c['id'] for c in records}
                saved['clips']=[c for c in saved.get('clips',[]) if c['id'] not in affected]+copy.deepcopy([*records,merged])
                saved.update(transaction=transaction,media_transaction=transaction,current_clip=merged['id'])
                atomic_json(project.path,saved)
                project.data.update(transaction=transaction,media_transaction=transaction,current_clip=merged['id'])
                recover(root,metadata,project.path)
                for clip in [*records,merged]:
                    project.review_baseline[clip['id']]=project.review_digest(clip);project.review_edits.discard(clip['id'])
                project.data['clips'].sort(key=lambda c:(Path(c['path']).name.casefold(),c['id']));project.dirty=dirty
                return merged,receipt
            except BaseException:
                committed=False
                try:committed=json.loads(project.path.read_text(encoding='utf-8')).get('media_transaction')==transaction
                except (OSError,ValueError):pass
                if not committed:
                    try:recover(root,metadata,project.path)
                    finally:
                        # Restore record objects referenced by the active UI.
                        original_by_id={c['id']:c for c in before['clips']}
                        for clip in records:
                            original=original_by_id[clip['id']];clip.clear();clip.update(original)
                        project.data.clear();project.data.update(before);project.dirty=dirty
                raise
