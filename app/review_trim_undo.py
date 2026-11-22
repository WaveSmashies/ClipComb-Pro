# SPDX-License-Identifier: GPL-3.0-or-later
"""Restore trim originals with a recoverable, no-overwrite file-move journal."""
import copy
import json
from pathlib import Path
import shutil
import uuid

from review_cleanup_core import hash_file
from review_trim_install import checked,rename_exclusive

JOURNAL='.clipcomb-undo-trim-transaction.json'


def receipt_for(project,clip):
    token=clip.get('trim_transaction','')
    if len(token)!=32 or any(c not in '0123456789abcdef' for c in token):return None
    path=project.metadata/f'clipcomb-trim-{token}.json'
    return path if path.is_file() else None


def attach_receipts(project):
    """Recognize older installed trims from receipts, never from filenames."""
    clips={c['id']:c for c in project.data['clips']}
    for path in project.metadata.glob('clipcomb-trim-*.json'):
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            first=clips.get(data['active_ids'][0]);before=data.get('original_record')
            if first and before and data['original']['id'] not in clips and first['path']==data['source'] and first.get('identity')==before.get('identity') and not first.get('trim_transaction'):
                first['trim_undone']=True
            for ident in data['active_ids']:
                clip=clips.get(ident)
                if clip and not clip.get('trim_transaction') and any(
                        p.get('source_id')==data['original']['id'] for p in clip.get('provenance',[])):
                    clip.update(trimmed_by_clipcomb=True,trim_transaction=data['id'])
        except (OSError,ValueError,KeyError,TypeError):continue


def unique_deleted(project,name,reserved=()):
    folder=project.folders()['Deleted'];folder.mkdir(parents=True,exist_ok=True)
    candidate=checked(project.root,str((folder/name).relative_to(project.root)))
    stem,suffix=candidate.stem,candidate.suffix;number=2
    while candidate.exists() or candidate in reserved:
        candidate=folder/f'{stem}_{number}{suffix}';number+=1
    return candidate


def discard(project,clip,result):
    """Keep canceled rendered outputs in Deleted; do not touch the source."""
    source=Path(clip['path']);targets=[]
    for i,(path,digest) in enumerate(zip(result.paths,result.checksums)):
        suffix='' if len(result.paths)==1 else f'_PART_{i+1:02}'
        target=unique_deleted(project,source.stem+'_TRIMMED'+suffix+source.suffix,targets)
        # Work files can live on a different volume. Exclusive copy prevents overwrite.
        with path.open('rb') as inp,target.open('xb') as out:shutil.copyfileobj(inp,out,4*1024**2)
        if hash_file(target)!=digest:raise ValueError('The canceled trim copy failed verification: '+str(target))
        targets.append(target)
    project.scan()
    for clip in project.data['clips']:
        if project.checked(clip['path']) in targets:clip['trimmed_by_clipcomb']=True
    project.persist_metadata()
    return targets


def recover(root,metadata,project_file):
    root=Path(root).resolve();journal=Path(metadata)/JOURNAL
    if not journal.is_file():return
    state=json.loads(journal.read_text(encoding='utf-8'))
    if state.get('schema')!=1:raise ValueError('Unknown Undo trim recovery record.')
    saved=json.loads(Path(project_file).read_text(encoding='utf-8'))
    committed=saved.get('media_transaction')==state['id']
    moves=[(checked(root,m['from']),checked(root,m['to']),m['sha256']) for m in state['moves']]
    if committed:
        for _,target,digest in moves:
            if not target.is_file() or hash_file(target)!=digest:raise ValueError('Undo trim needs recovery review: '+str(target))
    else:
        for source,target,digest in reversed(moves):
            if source.is_file() and hash_file(source)==digest:continue
            if not target.is_file() or hash_file(target)!=digest or source.exists():
                raise ValueError('Undo trim will not overwrite a changed file: '+str(source))
            rename_exclusive(target,source)
    journal.unlink()


def undo(project,clip):
    from review_core import atomic_json,file_identity
    recover(project.root,project.metadata,project.path)
    receipt=receipt_for(project,clip)
    if receipt is None:raise ValueError('The original trim record is unavailable.')
    data=json.loads(receipt.read_text(encoding='utf-8'))
    records={c['id']:c for c in project.data['clips']}
    original=records.get(data['original']['id'])
    outputs=[records.get(i) for i in data['active_ids']]
    if not original or any(c is None or c.get('trim_transaction')!=data['id'] for c in outputs):
        raise ValueError('A later trim changed this set of clips. Undo the later trim first.')
    backup=project.checked(original['path']);target=project.checked(data['source'])
    paths=[project.checked(c['path']) for c in outputs]
    if target.exists() and target not in paths:raise ValueError('The original filename is occupied. No files were moved.')
    saved=json.loads(project.path.read_text(encoding='utf-8'))
    if saved.get('transaction','')!=project.data.get('transaction',''):
        raise ValueError('This project changed in another window. Reopen it before undoing the trim.')
    moves=[];destinations=[]
    for record,path,expected in zip(outputs,paths,data['outputs']):
        if not path.is_file() or hash_file(path)!=expected['sha256']:raise ValueError('A trimmed copy changed. No files were moved.')
        destination=unique_deleted(project,path.name,destinations);destinations.append(destination)
        moves.append({'from':str(path.relative_to(project.root)),'to':str(destination.relative_to(project.root)),'sha256':expected['sha256']})
    if not backup.is_file() or hash_file(backup)!=data['original_sha256']:
        raise ValueError('The full original is missing or changed. No files were moved.')
    moves.append({'from':original['path'],'to':data['source'],'sha256':data['original_sha256']})
    token=uuid.uuid4().hex;journal=project.metadata/JOURNAL
    atomic_json(journal,{'schema':1,'id':token,'moves':moves})
    try:
        target.parent.mkdir(parents=True,exist_ok=True)
        for move in moves:rename_exclusive(project.checked(move['from']),project.checked(move['to']))
        restored=copy.deepcopy(data.get('original_record') or data['original'])
        restored.update(id=data['active_ids'][0],path=data['source'],identity=file_identity(target),missing=False,changed_source=False,trim_undone=True)
        if 'original_record' not in data:
            restored['decision']=next((name for name,path in project.folders().items() if target.parent==path),'Unused')
        discarded=[]
        for record,destination in zip(outputs,destinations):
            item=copy.deepcopy(record)
            item.update(id=uuid.uuid4().hex,path=str(destination.relative_to(project.root)),decision='Deleted',identity=file_identity(destination))
            # A canceled/undone copy remains a trimmed clip, but cannot restore the same original twice.
            item.pop('trim_transaction',None);discarded.append(item)
        affected={original['id'],*data['active_ids']}
        changed=[restored,*discarded]
        saved['clips']=[c for c in saved['clips'] if c['id'] not in affected]+copy.deepcopy(changed)
        saved.update(transaction=token,media_transaction=token)
        atomic_json(project.path,saved)
        project.data['clips'][:]=[c for c in project.data['clips'] if c['id'] not in affected]+changed
        project.data.update(transaction=token,media_transaction=token)
        for ident in affected:project.review_baseline.pop(ident,None);project.review_edits.discard(ident)
        for item in changed:project.review_baseline[item['id']]=project.review_digest(item)
        recover(project.root,project.metadata,project.path)
        return restored
    except BaseException:
        recover(project.root,project.metadata,project.path)
        raise
