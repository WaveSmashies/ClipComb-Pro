# SPDX-License-Identifier: GPL-3.0-or-later
"""Project-local folder names with recoverable directory renames, never deletion."""
import copy,json,os,uuid
from pathlib import Path

BASE=('Unused','Used','Kept','Deleted')
EXTRA=tuple(f'Extra{i}' for i in range(1,5))
JOURNAL='.clipcomb-folders-transaction.json'
RESERVED={'all','stars','bookmarks','marks','marked','.project data','projects','cleanup work','replay trim recovery','clip-review.project.json','clip-review-export.json'}


def names(project=None):
    configured=project.data.get('folders',{}) if project else {}
    return {**{key:configured.get(key,key) for key in BASE},
            **{key:configured[key] for key in EXTRA if configured.get(key)}}


def validate(values):
    from review_folder_picker import folder_name
    result={}
    for key in BASE+EXTRA:
        value=str(values.get(key,'')).strip()
        if not value and key in EXTRA:continue
        value=folder_name(value)
        if len(value)>80 or value.casefold() in RESERVED or value.startswith('.clipcomb'):
            raise ValueError('Choose a folder name of up to 80 characters that is not reserved by ClipComb Pro.')
        if value.casefold() in {n.casefold() for n in result.values()}:
            raise ValueError('Each project folder must have a different name.')
        result[key]=value
    return result


def category(project,value):
    return next((key for key,label in names(project).items() if label==value),value)


def categories(project=None):return ('All',*names(project).values(),'Stars','Bookmarks','Marks')


def action_labels(project,labels):
    result=dict(labels)
    for key,value in names(project).items():result[key.lower()]=f'Move To {value}'
    return result


def action_text(project,text):
    return 'Mark '+names(project).get(text[5:],text[5:]) if text.startswith('Mark ') else text


def remap(value,root,mapping):
    if isinstance(value,list):return [remap(item,root,mapping) for item in value]
    if isinstance(value,dict):
        return {key:(item if key in ('name','title','note','decision','folders','folder_renames','export_folders','studio_source_moves') else remap(item,root,mapping)) for key,item in value.items()}
    if not isinstance(value,str):return value
    normalized=value.replace('\\','/')
    for old,new in mapping:
        for prefix,replacement in ((old,new),((root/old).as_posix(),(root/new).as_posix())):
            if normalized.casefold()==prefix.casefold() or normalized.casefold().startswith(prefix.casefold()+'/'):
                updated=replacement+normalized[len(prefix):]
                return updated.replace('/','\\') if '\\' in value else updated
    return value


def recover(root,metadata,project_file):
    from review_core import read_json,atomic_json
    root=Path(root).resolve();metadata=Path(metadata).resolve();path=metadata/JOURNAL
    if not path.is_file():return
    state=read_json(path)
    if state.get('schema')!=1:raise ValueError('Unknown folder recovery record.')
    def checked(name):
        candidate=root/name
        if candidate.is_symlink() or candidate.resolve().parent!=root:raise ValueError('Folder recovery path leaves the project.')
        return candidate
    entries=[tuple(checked(entry[key]) for key in ('old','temp','new')) for entry in state['moves']]
    committed=Path(project_file).is_file() and read_json(project_file).get('folder_transaction')==state['transaction']
    if not committed:
        if state['phase']=='installing':
            for old,temp,new in entries:
                if not temp.exists() and new.exists():os.rename(new,temp)
        for old,temp,new in entries:
            if temp.exists():
                if old.exists():raise ValueError('Folder recovery will not overwrite an existing folder.')
                os.rename(temp,old)
        for document in state['documents']:
            target=metadata/document['name']
            if target.resolve().parent!=metadata:raise ValueError('Invalid folder recovery metadata path.')
            atomic_json(target,document['before'])
    path.unlink()


def configure(project,values):
    from review_core import atomic_json,read_json
    values=validate(values);old=names(project)
    if old==values:return False
    recover(project.root,project.metadata,project.path)
    if any((project.metadata/name).exists() for name in ('.clip-review-save.json','.clipcomb-trim-transaction.json','.clipcomb-merge-transaction.json','.clipcomb-undo-trim-transaction.json')):
        raise ValueError('Finish the pending file operation before changing project folders.')
    saved=read_json(project.path) if project.path.exists() else copy.deepcopy(project.data)
    if saved.get('transaction','')!=project.data.get('transaction',''):
        raise ValueError('This project changed in another window. Reopen it before renaming folders.')
    old_paths=project.folders();root=project.root
    if any(path.is_symlink() or path.resolve().parent!=root for path in old_paths.values()):
        raise ValueError('Project folders must be ordinary folders inside the project.')
    # Refresh stale/moved clip records before checking occupancy. Apply the same
    # path repair to the saved checkpoint without committing pending review edits.
    found=project.scan()
    from review_scan_reconcile import reconcile
    reconcile(project,saved,found)
    removed=old.keys()-values.keys()
    def occupied(folder):
        for directory,dirs,files in os.walk(folder,followlinks=False):
            if files or any(Path(directory,name).is_symlink() for name in dirs):return True
        return False
    for key in removed:
        if any(c['decision']==key and project.checked(c['path']).is_file() for c in project.data['clips']) or occupied(old_paths[key]):
            raise ValueError('Move clips out of '+old[key]+' before removing that extra folder.')
    changed=[key for key in values if key in old and old[key]!=values[key]]
    mapping=[(old_paths[key].name,values[key]) for key in changed]
    old_sources={old_paths[key].resolve() for key in changed if old_paths[key].exists()}
    for key in changed:
        target=root/values[key]
        if target.is_symlink() or target.resolve().parent!=root:raise ValueError('Project folders must be ordinary folders inside the project.')
        if target.exists() and target.resolve() not in old_sources:
            raise ValueError(values[key]+' already exists. Choose another name; folders are never merged or overwritten.')
    for key in values.keys()-old.keys():
        target=root/values[key]
        if target.is_symlink() or target.resolve().parent!=root or target.exists() and not target.is_dir():
            raise ValueError('An extra folder must be an ordinary folder inside the project.')
    transaction=uuid.uuid4().hex
    updated=remap(copy.deepcopy(project.data),root,mapping);updated['folders']=values;updated['transaction']=transaction
    updated['folder_transaction']=transaction
    updated.setdefault('folder_renames',[]).append(mapping)
    # Save folder paths against the last saved review, leaving pending marks and
    # sorting decisions pending. Save Settings must not silently save a review.
    persisted=remap(saved,root,mapping);persisted.update(folders=values,transaction=transaction,folder_transaction=transaction)
    from review_core import remember_source_move
    for before,after in ((project.data,updated),(saved,persisted)):
        old_paths_by_id={clip['id']:clip['path'] for clip in before.get('clips',[])}
        for clip in after['clips']:
            old_path=old_paths_by_id.get(clip['id'])
            if old_path and old_path!=clip['path']:remember_source_move(clip,old_path)
    # Missing records keep their annotations, but cannot keep a destination that
    # no longer exists in this project's configuration.
    for document in (updated,persisted):
        if isinstance(document.get('export_folders'),list):document['export_folders']=[role for role in document['export_folders'] if role in values]
        for clip in document['clips']:
            if clip['decision'] in removed:clip.update(decision='Unused',missing=True)
    persisted.setdefault('folder_renames',[]).append(mapping)
    documents=[]
    for pattern in ('clipcomb-trim-*.json','clipcomb-merge-*.json'):
        for path in project.metadata.glob(pattern):
            if path.is_symlink():raise ValueError('A recovery record is redirected outside project metadata.')
            before=read_json(path);after=remap(before,root,mapping)
            if before!=after:documents.append(dict(name=path.name,before=before,after=after))
    moves=[dict(old=old_paths[key].name,temp=f'.clipcomb-folder-{transaction}-{index}',new=values[key])
           for index,key in enumerate(changed) if old_paths[key].exists()]
    state=dict(schema=1,transaction=transaction,phase='staging',moves=moves,documents=documents)
    journal=project.metadata/JOURNAL;atomic_json(journal,state)
    try:
        for entry in moves:os.rename(root/entry['old'],root/entry['temp'])
        state['phase']='installing';atomic_json(journal,state)
        for entry in moves:os.rename(root/entry['temp'],root/entry['new'])
        for document in documents:atomic_json(project.metadata/document['name'],document['after'])
        for name in values.values():(root/name).mkdir(exist_ok=True)
        atomic_json(project.path,persisted)
    except Exception:
        recover(root,project.metadata,project.path)
        raise
    project.data=updated;project.scan();journal.unlink()
    return True


class FolderEditor:
    def __init__(self,parent,project):
        import tkinter as tk
        from tkinter import ttk
        self.project=project;self.variables={}
        box=ttk.LabelFrame(parent,text='Project Folders',padding=12);box.pack(fill='x',pady=(0,12))
        ttk.Label(box,text='Names and extra folders apply only to this project. Saving settings renames\nexisting folders and keeps their contents. Four main folders are required.\nChoose which folders to include on the export screen.\nExtra folders can also use existing folders inside the project.',style='Hint.TLabel').grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,8))
        configured=names(project)
        def clear_inactive_selection(entry):
            if entry.winfo_exists() and entry.focus_get()!=entry:entry.selection_clear()
        for row,key in enumerate(BASE+EXTRA,1):
            ttk.Label(box,text=key+' folder' if key in BASE else 'Extra folder '+key[-1]+' (optional)').grid(row=row,column=0,sticky='w',padx=(0,12),pady=3)
            variable=tk.StringVar(value=configured.get(key,''));self.variables[key]=variable
            entry=ttk.Entry(box,textvariable=variable,state='normal' if project else 'disabled',width=35,exportselection=False)
            entry.grid(row=row,column=1,sticky='ew')
            # Notebook traversal can leave a native inactive selection behind.
            # Keep selection while editing, but clear it when leaving the field.
            for event in ('<FocusOut>','<Map>'):
                entry.bind(event,lambda _event,entry=entry:entry.after_idle(clear_inactive_selection,entry),add='+')
        if not project:ttk.Label(box,text='Open a project to customize its folders.',style='Hint.TLabel').grid(row=9,column=0,columnspan=2,sticky='w')
        box.columnconfigure(1,weight=1)
    def values(self):return validate({key:var.get() for key,var in self.variables.items()}) if self.project else None
