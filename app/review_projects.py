# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable, readable project documents. Project management never sorts media."""
import copy
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from review_core import Project,PROJECT_FILE,JOURNAL_FILE,atomic_json,read_json

EXTENSION='.clipcomb.json'
JOURNALS=(JOURNAL_FILE,'.clipcomb-trim-transaction.json','.clipcomb-merge-transaction.json','.clipcomb-undo-trim-transaction.json','.clipcomb-folders-transaction.json')


def name_value(value):
    value=str(value).strip()
    if not value or len(value)>120 or any(ord(c)<32 for c in value):raise ValueError('Enter a project name between 1 and 120 characters.')
    return value


class ProjectStore:
    def __init__(self,settings):
        self.settings=settings;self.base=settings.path.parent.resolve();self.folder=self.base/'Projects';self.errors=[]
        self.folder.mkdir(exist_ok=True)
        if self.folder.resolve()!=self.folder:raise ValueError('Projects must be a normal folder beside ClipComb Pro.')

    def owned(self,path):
        path=Path(path).absolute()
        if path.parent!=self.folder or path.resolve()!=path or path.is_symlink() or not path.name.casefold().endswith(EXTENSION):
            raise ValueError('Choose a ClipComb project file inside this app’s Projects folder.')
        return path

    def document(self,path):
        data=read_json(path)
        if not isinstance(data,dict) or data.get('schema')!=1 or not isinstance(data.get('clips'),list) or not isinstance(data.get('video_root'),str) or not data['video_root']:
            raise ValueError('This is not a supported ClipComb Pro project file.')
        if not isinstance(data.get('name'),str) or not Path(data['video_root']).is_absolute():raise ValueError('The project name or video-folder path is invalid.')
        name_value(data['name'])
        if not re.fullmatch('[0-9a-f]{32}',data.get('project_id','')):raise ValueError('This project has an invalid identifier.')
        return data

    def filename(self,name,ident):
        safe=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',name).strip(' .')[:65] or 'Project'
        path=self.folder/f'{safe} - {ident[:12]}{EXTENSION}';number=2
        while path.exists():
            path=self.folder/f'{safe} - {ident[:12]} ({number}){EXTENSION}';number+=1
        return path

    def entries(self):
        self.errors=[];items=[];recent=self.settings.projects();roots=set()
        for path in self.folder.iterdir():
            if not path.name.casefold().endswith(EXTENSION):continue
            try:
                self.owned(path);data=self.document(path)
                relative=str(path.relative_to(self.base))
                prior=next((i for i in recent if i.get('project_file')==relative),{})
                item=dict(root=data['video_root'],name=data['name'],project_file=relative,created=data.get('created',path.stat().st_ctime),opened=prior.get('opened',0))
                items.append(item);roots.add(str(Path(item['root']).resolve()).casefold())
            except (OSError,ValueError,KeyError,TypeError) as error:self.errors.append(f'{path.name}: {error}')
        # Older previews indexed projects by video folder. Import on first open.
        # A missing portable file is intentionally absent, even if its old index remains.
        for item in recent:
            if item.get('project_file') or not isinstance(item.get('root'),str):continue
            if str(Path(item['root']).resolve()).casefold() not in roots:items.append(item)
        return items

    def path_for(self,item):
        value=item.get('project_file')
        return self.owned(self.base/value) if value else None

    def existing(self,root):
        key=str(Path(root).resolve()).casefold()
        return next((i for i in self.entries() if str(Path(i['root']).resolve()).casefold()==key and i.get('project_file')),None)

    def cleanup_legacy(self,project):
        migration=project.data.get('legacy_import')
        if not migration:return
        for source in [*project.root.glob('clipcomb-trim-*.json'),*project.root.glob('clipcomb-merge-*.json')]:
            if source.is_symlink() or not source.is_file():continue
            try:payload=source.read_bytes()
            except OSError:continue
            try:record=json.loads(payload)
            except ValueError:continue
            if not isinstance(record,dict) or not ('verification' in record and ('original' in record or 'copies' in record) or 'track_placements' in record and 'merged' in record):continue
            target=project.metadata/source.name
            if target.exists() and read_json(target)!=record:raise ValueError('A recovery record with this name already exists. No original record was removed.')
            if not target.exists():atomic_json(target,record)
            if read_json(target)!=record:raise ValueError('A recovery record could not be imported.')
            if source.read_bytes()==payload:
                try:source.unlink()
                except PermissionError:pass  # The imported copy is complete; read-only legacy metadata may remain.
        source=project.root/PROJECT_FILE
        if source.is_file() and not source.is_symlink() and hashlib.sha256(source.read_bytes()).hexdigest()==migration['sha256']:
            # Only remove the exact project document we successfully imported.
            try:source.unlink()
            except PermissionError:pass
        project.data.pop('legacy_import',None)
        project.persist_metadata()

    def open(self,root,name=None,project_file=None):
        root=Path(root).resolve()
        if not root.is_dir():raise ValueError('The video folder cannot be found. Use Locate video folder in Projects.')
        if project_file:
            path=self.owned(project_file);data=self.document(path)
        else:
            item=self.existing(root)
            path=self.path_for(item) if item else None
        if path:
            data=self.document(path)
            metadata=self.folder/'.Project Data'/data['project_id']
            if str(root)!=data['video_root'] and any((metadata/name).exists() for name in JOURNALS):
                raise ValueError('Finish this project’s interrupted operation using its original video folder before locating a different folder.')
            project=Project(root,project_file=path)
            if project.data['video_root']!=str(root):
                project.data['video_root']=str(root);project.persist_metadata()
            self.cleanup_legacy(project)
            if name and name!=project.data['name']:self.rename(dict(root=str(root),project_file=str(path.relative_to(self.base))),name,project)
            return project
        # Recover any interrupted operation under the old layout before importing.
        legacy=root/PROJECT_FILE
        key=uuid.uuid5(uuid.NAMESPACE_URL,str(root).casefold()).hex
        removed=self.settings.data.get('removed_projects',key,fallback='')
        portable_before=any(i.get('project_file') and Path(i['root'])==root for i in self.settings.projects())
        if removed or portable_before:
            # A deleted document starts fresh even when a read-only legacy copy
            # remains on the video drive. Never resurrect its old review choices.
            ident=uuid.uuid4().hex;value=name_value(name or root.name)
            path=self.filename(value,ident)
            atomic_json(path,dict(schema=1,name=value,clips=[],current_clip='',transaction='',project_id=ident,video_root=str(root),created=time.time()))
            project=Project(root,project_file=path);project.persist_metadata();return project
        source_digest=hashlib.sha256(legacy.read_bytes()).hexdigest() if legacy.is_file() else None
        project=Project(root,name)
        if name:project.data['name']=name_value(name)
        ident=uuid.uuid4().hex;path=self.filename(project.data['name'],ident)
        project.data.update(project_id=ident,video_root=str(root),created=time.time(),transaction=uuid.uuid4().hex)
        if source_digest:project.data['legacy_import']={'sha256':source_digest}
        atomic_json(path,project.data)
        project.path=path;project.metadata=self.folder/'.Project Data'/ident;project.metadata.mkdir(parents=True)
        self.cleanup_legacy(project)
        return project

    def rename(self,item,name,active=None):
        name=name_value(name);path=self.path_for(item)
        if path is None:
            # Import old metadata without invoking Save (which sorts recordings).
            if any((Path(item['root'])/name).exists() for name in JOURNALS):raise ValueError('Open this project to finish its interrupted operation before renaming its project record.')
            project=self.open(item['root']);path=project.path
        data=self.document(path);before=copy.deepcopy(data)
        metadata=self.folder/'.Project Data'/data['project_id']
        if any((metadata/name).exists() for name in JOURNALS):raise ValueError('Open this project to finish its interrupted operation before renaming its project record.')
        if data['name']==name:self.settings.register(item['root'],name,path);return path
        if active and active.path==path and active.data.get('transaction','')!=data.get('transaction',''):
            raise ValueError('This project changed in another window. Reopen it before renaming.')
        data['name']=name;data['transaction']=uuid.uuid4().hex
        target=self.filename(name,data['project_id'])
        # Rename is confined to metadata in one directory. Roll back on write failure.
        path.rename(target)
        try:atomic_json(target,data)
        except BaseException:
            atomic_json(target,before);target.rename(path);raise
        if active and active.path==path:
            active.path=target;active.data.update(name=name,transaction=data['transaction'])
        self.settings.register(item['root'],name,target)
        return target

    def remove(self,item):
        path=self.path_for(item)
        if path:
            data=self.document(path)
            metadata=self.folder/'.Project Data'/data['project_id']
            if any((metadata/name).exists() for name in JOURNALS):raise ValueError('This project has an interrupted file operation. Open it to finish recovery before deleting its project record.')
            # No folder recursion, no media paths and no call to Project.save.
            migration=data.get('legacy_import')
            legacy=Path(item['root'])/PROJECT_FILE
            if migration and legacy.is_file() and not legacy.is_symlink() and hashlib.sha256(legacy.read_bytes()).hexdigest()==migration['sha256'] and not any((legacy.parent/name).exists() for name in JOURNALS):
                try:legacy.unlink()
                except PermissionError:pass
            path.unlink()
        else:
            root=Path(item['root']);legacy=root/PROJECT_FILE
            if any((root/name).exists() for name in JOURNALS):raise ValueError('Open this project to finish recovery before deleting its project record.')
            if legacy.is_file() and not legacy.is_symlink():
                data=read_json(legacy)
                if not isinstance(data,dict) or data.get('schema')!=1 or not isinstance(data.get('clips'),list):raise ValueError('The old project record is not recognized; no files were removed.')
                try:legacy.unlink()
                except PermissionError:pass
        if not self.settings.data.has_section('removed_projects'):self.settings.data.add_section('removed_projects')
        key=uuid.uuid5(uuid.NAMESPACE_URL,str(Path(item['root']).resolve()).casefold()).hex
        self.settings.data['removed_projects'][key]='yes'
        section=self.settings.data['projects']
        for key,value in list(section.items()):
            try:record=json.loads(value)
            except ValueError:continue
            if record.get('root') and Path(record['root'])==Path(item['root']) and (not path or not record.get('project_file') or record.get('project_file')==item.get('project_file')):del section[key]
        if self.settings.data['app']['last_project'] and Path(self.settings.data['app']['last_project'])==Path(item['root']):self.settings.data['app']['last_project']=''
        self.settings.save()

    def import_file(self,source,root=None):
        source=Path(source).resolve();data=self.document(source)
        try:return self.owned(source)
        except ValueError:pass
        data=copy.deepcopy(data);data['project_id']=uuid.uuid4().hex;data.pop('legacy_import',None)
        if root:data['video_root']=str(Path(root).resolve())
        path=self.filename(data['name'],data['project_id']);atomic_json(path,data)
        return path

    def folders_renamed(self,old,new,active=None):
        """Update documents after an explicitly requested Explorer-style folder rename."""
        for item in self.entries():
            path=self.path_for(item)
            if not path:continue
            data=self.document(path);previous=Path(data['video_root']);changed=False
            next_root=new/previous.relative_to(old) if previous.is_relative_to(old) else previous
            if next_root!=previous:data['video_root']=str(next_root);changed=True
            for clip in data['clips']:
                absolute=previous/clip['path']
                if absolute.is_relative_to(old):
                    relative=str((new/absolute.relative_to(old)).relative_to(next_root))
                    if relative!=clip['path']:clip['path']=relative;changed=True
            if changed:
                if active and active.path==path and active.data.get('transaction','')!=data.get('transaction',''):raise ValueError('The project changed in another window. Reopen it before renaming folders.')
                data['transaction']=uuid.uuid4().hex;atomic_json(path,data)
                if active and active.path==path:active.data['transaction']=data['transaction']
