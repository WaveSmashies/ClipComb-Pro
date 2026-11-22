# SPDX-License-Identifier: GPL-3.0-or-later
"""Recoverable replacement of verified trims, preserving full originals in Deleted."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from review_cleanup_core import hash_file
from review_overlap_audit import identity
from review_file_trim import remap_annotations

JOURNAL='.clipcomb-trim-transaction.json'


def checked(root,relative):
    path=(root/relative).resolve()
    if not path.is_relative_to(root) or path==root:raise ValueError('Invalid path in trim transaction.')
    return path


def backup_path(project,clip):
    source=project.checked(clip['path']);folder=project.folders()['Deleted']
    folder=checked(project.root,str(folder.relative_to(project.root)))
    target=folder/(source.stem+'_ORIGINAL'+source.suffix);number=2
    while target.exists():
        target=folder/(source.stem+f'_ORIGINAL_{number}'+source.suffix);number+=1
    return target


def rename_exclusive(source,target):
    if os.name=='nt':source.rename(target)
    else:os.link(source,target);source.unlink()


def recover(root,metadata=None,project_file=None):
    """On restart, roll back uncommitted files or verify the committed result."""
    root=Path(root).resolve();metadata=Path(metadata) if metadata else root;journal=metadata/JOURNAL
    if not journal.is_file():return
    from review_core import PROJECT_FILE
    state=json.loads(journal.read_text(encoding='utf-8'))
    if state.get('schema')!=1:raise ValueError('Unknown trim recovery journal. Keep the project folder intact for recovery.')
    source=checked(root,state['source']);backup=checked(root,state['backup'])
    outputs=[(checked(root,p['path']),p['sha256']) for p in state['outputs']]
    project_file=Path(project_file) if project_file else root/PROJECT_FILE
    saved=json.loads(project_file.read_text(encoding='utf-8')) if project_file.exists() else {}
    committed=saved.get('media_transaction')==state['id']
    if committed:
        if not backup.is_file() or hash_file(backup)!=state['original_sha256']:
            raise ValueError(f'Trim committed, but its full original needs recovery review: {backup}')
        for path,digest in outputs:
            if not path.is_file() or hash_file(path)!=digest:
                raise ValueError(f'Trim committed, but this output needs recovery review: {path}')
    else:
        if backup.exists():
            if hash_file(backup)!=state['original_sha256']:raise ValueError(f'The recovery original changed: {backup}')
            if source.exists():
                digest=hash_file(source)
                if digest==state['outputs'][0]['sha256']:source.unlink()
                elif digest!=state['original_sha256']:raise ValueError(f'Trim recovery will not overwrite a changed file: {source}')
            if not source.exists():rename_exclusive(backup,source)
        elif not source.is_file() or hash_file(source)!=state['original_sha256']:
            raise ValueError('The interrupted trim requires manual recovery. Keep its journal and Deleted folder.')
        for path,digest in outputs:
            if path==source:continue
            if path.exists():
                if hash_file(path)!=digest:raise ValueError(f'Trim recovery will not remove a changed output: {path}')
                path.unlink()
    journal.unlink()


def install(project,clip,result,backup=None,original_name=True):
    from review_core import atomic_json,file_identity,PROJECT_FILE
    root=project.root;metadata=project.metadata;recover(root,metadata,project.path)
    source=project.checked(clip['path']);backup=backup or backup_path(project,clip)
    backup=checked(root,str(backup.relative_to(root)))
    if backup.exists():raise ValueError('The proposed original-backup name is now occupied. Run the trim again.')
    if identity(source.lstat())!=result.source_identity or hash_file(source)!=result.source_checksum:
        raise ValueError('The source changed after trim verification. Nothing was replaced.')
    for path,digest in zip(result.paths,result.checksums):
        if hash_file(path)!=digest:raise ValueError('A staged trim changed after verification.')
    before=copy.deepcopy(clip);old_transaction=project.data.get('transaction','');old_media=project.data.get('media_transaction')
    dirty=project.dirty;prior_ids={c['id'] for c in project.data['clips']}
    on_disk=json.loads(project.path.read_text(encoding='utf-8')) if project.path.exists() else None
    if on_disk is not None and on_disk.get('transaction','')!=old_transaction:
        raise ValueError('Another app window saved this project. Reload it before replacing media.')
    first=source if original_name else source.with_name(source.stem+'_TRIMMED'+source.suffix)
    if first!=source and first.exists():raise ValueError('The trimmed filename already exists. Rename that file before trimming again.')
    finals=[first]
    for i in range(1,len(result.paths)):
        candidate=source.with_name(first.stem+f'_PART_{i+1:02}'+source.suffix)
        if candidate.exists():raise ValueError(f'This output filename already exists: {candidate.name}')
        finals.append(candidate)
    transaction=uuid.uuid4().hex
    journal={'schema':1,'id':transaction,'source':clip['path'],'backup':str(backup.relative_to(root)),
             'original_sha256':result.source_checksum,
             'outputs':[{'path':str(p.relative_to(root)),'sha256':d} for p,d in zip(finals,result.checksums)]}
    backup.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.clipcomb-trim-install-',dir=source.parent) as temporary:
        stage=Path(temporary).resolve()
        if not stage.is_relative_to(root) or not stage.name.startswith('.clipcomb-trim-install-'):
            raise ValueError('The trim staging folder leaves its project.')
        staged=[]
        for i,(path,digest) in enumerate(zip(result.paths,result.checksums)):
            target=stage/f'{i:04}{source.suffix}'
            with path.open('rb') as inp,target.open('xb') as out:
                shutil.copyfileobj(inp,out,4*1024**2);out.flush();os.fsync(out.fileno())
            if hash_file(target)!=digest:raise ValueError('The installation copy failed verification.')
            staged.append(target)
        # Recheck after the potentially lengthy copy, immediately before any move.
        if identity(source.lstat())!=result.source_identity or hash_file(source)!=result.source_checksum:
            raise ValueError('The original changed while preparing installation.')
        latest=json.loads(project.path.read_text(encoding='utf-8')) if project.path.exists() else None
        if latest!=on_disk:raise ValueError('The saved project changed during trim preparation. Nothing was replaced.')
        atomic_json(metadata/JOURNAL,journal)
        try:
            rename_exclusive(source,backup)
            for path,target in zip(staged,finals):rename_exclusive(path,target)
            for path,digest in zip(finals,result.checksums):
                if hash_file(path)!=digest:raise ValueError('Installed trim failed verification.')
            if hash_file(backup)!=result.source_checksum:raise ValueError('The full original backup failed verification.')
            original=copy.deepcopy(before)
            original.update(id=uuid.uuid4().hex,path=str(backup.relative_to(root)),decision='Deleted',
                            identity=file_identity(backup),missing=False,changed_source=False)
            project.data['clips'].append(original)
            outputs=[]
            for i,(target,mapping) in enumerate(zip(finals,result.mappings)):
                record=clip if i==0 else copy.deepcopy(before)
                if i:record['id']=uuid.uuid4().hex
                record['ranges'],record['markers']=remap_annotations(before,mapping)
                position=next((before.get('position',0)-a+base for a,b,base in mapping if a<=before.get('position',0)<b),0)
                record.update(path=str(target.relative_to(root)),identity=file_identity(target),media=copy.deepcopy(result.metadata[i]),
                              position=position,trim_ranges=[],missing=False,changed_source=False,
                              trimmed_by_clipcomb=True,trim_transaction=transaction,
                              provenance=[{'source_id':original['id'],'source_path':original['path'],'start':a,'end':b,'output_start':base} for a,b,base in mapping])
                if i:project.data['clips'].append(record)
                outputs.append(record)
            receipt=metadata/f'clipcomb-trim-{transaction}.json'
            atomic_json(receipt,dict(journal,original=original,original_record=before,verification=result.details,
                                    mapping=result.mappings,active_ids=[c['id'] for c in outputs]))
            # Persist this operation's clip records. Other unsaved decisions stay
            # staged in memory and do not get committed by an unrelated trim.
            saved=copy.deepcopy(on_disk) if on_disk is not None else copy.deepcopy(project.data)
            changed_ids={original['id'],*(c['id'] for c in outputs)}
            saved['clips']=[c for c in saved.get('clips',[]) if c['id'] not in changed_ids]
            saved['clips'].extend(copy.deepcopy([original,*outputs]))
            saved['transaction']=transaction;saved['media_transaction']=transaction
            atomic_json(project.path,saved)
            project.data.update(transaction=transaction,media_transaction=transaction)
            project.data['clips'].sort(key=lambda c:(Path(c['path']).name.casefold(),c['id']))
            project.dirty=dirty
            recover(root,metadata,project.path)
            for record in [original,*outputs]:
                project.review_baseline[record['id']]=project.review_digest(record);project.review_edits.discard(record['id'])
            return outputs,original,receipt
        except BaseException:
            committed=False
            try:committed=json.loads(project.path.read_text(encoding='utf-8')).get('media_transaction')==transaction
            except (OSError,ValueError):pass
            if not committed:
                try:recover(root,metadata,project.path)
                finally:
                    clip.clear();clip.update(before)
                    project.data['clips'][:]=[c for c in project.data['clips'] if c['id'] in prior_ids]
                    project.data['transaction']=old_transaction
                    if old_media is None:project.data.pop('media_transaction',None)
                    else:project.data['media_transaction']=old_media
                    project.dirty=dirty
            raise
