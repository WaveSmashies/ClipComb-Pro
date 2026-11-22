# SPDX-License-Identifier: GPL-3.0-or-later
"""Project persistence and reversible folder sorting, independent of the player/UI."""
import configparser
import copy
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import time
import uuid

STATUSES = ('Unused', 'Used', 'Kept', 'Deleted')
EXTENSIONS = {'.mp4', '.mkv', '.mov', '.ts', '.m2ts', '.mts', '.avi', '.webm', '.m4v',
              '.mpv', '.mpeg', '.mpg', '.mpe', '.m2v', '.m1v', '.mxf', '.flv', '.f4v',
              '.wmv', '.asf', '.vob', '.ogv', '.ogg', '.3gp', '.3g2', '.qt', '.nut', '.y4m'}
PROJECT_FILE = 'clip-review.project.json'
JOURNAL_FILE = '.clip-review-save.json'
CONFIG_FILE = 'ClipComb Pro.ini'
LEGACY_CONFIG_FILE = 'clip-review.ini'
DEFAULT_KEYS = {
    'marker':'F',
    'star':'G','review_page':'R','compare_page':'C',
    'trim_file':'T','create_trim':'T','snap_playhead':'N',
    'undo':'Ctrl+Z','redo':'Ctrl+Shift+Z',
    'save': 'Ctrl+S', 'export': 'Ctrl+Shift+E', 'play': 'Space',
    'back': 'Z', 'forward': 'X', 'back_large': 'Shift+Z', 'forward_large': 'Shift+X',
    'used': 'W', 'deleted': 'A', 'previous': 'Q', 'next': 'E',
    'kept': 'D', 'unused': 'S', 'remove_range': 'Tab','clear_moments':'Alt+X',
    'fullscreen': 'Escape', 'slow': 'Shift+1', 'frame_back': 'Left', 'frame_forward': 'Right',
    'scrub_to_mouse': 'MouseMiddle', 'scrub_video': 'V', 'scrub_audio': 'Alt+S',
    **{f'speed_{i}': str(i) for i in range(1, 6)},
}
DEFAULT_SECONDARY_KEYS={key:('Backspace' if key=='remove_range' else '') for key in DEFAULT_KEYS}
DEFAULT_KEYS={key:value for key,value in DEFAULT_KEYS.items() if key!='slow' and not key.startswith('speed_')}
DEFAULT_KEYS.update({f'extra{i}':'' for i in range(1,5)})
DEFAULT_KEYS.update(volume_meter='M',slow='Shift+1',fast='Shift+2',**{f'speed_{i}':str(i) for i in range(1,6)})
DEFAULT_SECONDARY_KEYS={key:DEFAULT_SECONDARY_KEYS.get(key,'') for key in DEFAULT_KEYS}


def atomic_json(path, data):
    path = Path(path)
    temp = path.with_name(path.name + '.writing')
    with temp.open('w', encoding='utf-8') as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class Settings:
    def __init__(self, folder=None):
        self.path = Path(folder) / CONFIG_FILE if folder is not None else None
        self.legacy=None
        self.data = configparser.ConfigParser(interpolation=None)
        if self.path:
            source=self.path
            old=self.path.with_name(LEGACY_CONFIG_FILE)
            if not source.exists() and old.is_file():
                source=old;info=old.stat();self.legacy=(old,info.st_mtime_ns,info.st_size)
            if source.is_file():
                with source.open(encoding='utf-8-sig') as stream:self.data.read_file(stream)
        defaults = {
            'app': {'geometry': '1500x950', 'last_project': '', 'auto_advance': 'yes',
                    'autoplay': 'yes', 'volume_meter':'yes', 'media_play_pause':'no', 'seek_small': '2', 'seek_large': '5', 'speed_reset_seconds': '3', 'ui_refresh_ms':'16',
                    'remember_position':'yes','undo_limit':'50','window_state':'normal','frame_repeat_fps':'10',
                    'projects_sort':'Latest','sort_moments':'yes','frame_repeat_delay_ms':'400','timecode_frames':'yes','queue_view':'List','transport_scale':'1'},
            'tools': {'mpv_library': '', 'ffprobe': '', 'ffmpeg':'', 'hardware_decoding': 'auto','resolve_folder':''},
            'export': {'fps':'Auto (highest clip)','mode':'file','skip_existing':'yes','apply_mix':'yes','timeline_name':'ClipComb Pro selects','format':'OTIO · Resolve (clip markers)','timeline_markers':'no','fix_bookmarks':'yes','dont_show_warning':'no'},
            'bookmarks': {'palette':'DaVinci Resolve','custom_colors':''},
            'timeline': {'right_click_existing':'yes'},
            'snapping': {'enabled':'yes'},
            'tutorial': {'dont_show':'no','first_run_seen':'no','completed':'no','skipped':'no'},
            'trimming': {'original_name':'no','replace_original':'yes','join_sections':'yes'},
            'magnifier': {'zoom': '3', 'step': '0.5', 'maximum': '20',
                          'width': '480', 'height': '300', 'refresh_ms': '4', 'capture_ms':'16','smoothing':'yes','mode':'Automatic','show_cursor':'yes'},
            'scrubbing': {'show_video': 'yes', 'play_audio': 'no', 'stop_playback': 'yes',
                          'seek_interval_ms': '16', 'audio_grain_ms': '35'},
            'waveform': {'enabled':'yes','track':'auto','bins_per_second':'50','cache_directory':'Generated Waveforms','delete_on_close':'no','delete_after_30_days':'yes'},
            'layout': {'left':'0.26','mixer':'0.79','queue':'0.68','viewer':'0.65'},
            'theme': {'preset':'Default','light_mode':'no'},
            'archive': {'show_warning':'yes','start_on_launch':'no'},
            'thumbnails': {'size':'170','delete_on_close':'no','delete_after_30_days':'yes'},
            'dual': {'enabled':'no','geometry':'','fullscreen':'no','primary_category':'Unused','panels':'[{"category":"Used","mode":"List"},{"category":"Kept","mode":"List"},{"category":"Deleted","mode":"List"}]'},
            'audio': {'output_device':'auto','date_profiles_enabled':'no','default_profile':'Configured tracks','layout_change': '2025-07-28T20:25:00',
                      'configured_names':'Track 1|Track 2|Track 3|Track 4|Track 5|Track 6',
                      'configured_enabled':'1','configured_volumes':'100,100,100,100,100,100',
                      'modern_names': 'All tracks|My mic · processed|Discord|Game sound|My mic · raw|Track 6',
                      'legacy_names': 'My mic · processed|Discord|Game sound|My mic · raw|Track 5|All tracks',
                      'modern_enabled': '3,4,5', 'legacy_enabled': '2,3,4',
                      'modern_volumes': '100,100,100,100,100,100', 'legacy_volumes': '100,100,100,100,100,100'},
            'shortcuts': DEFAULT_KEYS, 'shortcuts_secondary':DEFAULT_SECONDARY_KEYS, 'projects': {},
        }
        for section, items in defaults.items():
            if section not in self.data:
                self.data[section] = {}
            for key, value in items.items():
                if key not in self.data[section]:
                    if section=='shortcuts' and key in ('star','review_page','compare_page','fast','volume_meter','clear_moments') and any(value in self.data[s].values() for s in ('shortcuts','shortcuts_secondary') if s in self.data):value=''
                    self.data[section][key] = value
        if self.data['app'].get('review_ui_version','1') == '1':
            for section,key,old,new in [('magnifier','width','320','480'),('magnifier','height','200','300'),
                    ('magnifier','refresh_ms','120','16'),('scrubbing','audio_grain_ms','100','35'),
                    ('scrubbing','seek_interval_ms','35','16')]:
                if self.data[section].get(key) == old:
                    self.data[section][key] = new
            self.data['app']['review_ui_version'] = '2'
        from review_brand import THEME_NAMES
        self.data['theme']['preset']=THEME_NAMES.get(self.data['theme']['preset'],self.data['theme']['preset'])
        if self.data['bookmarks']['palette']=='Resolve':self.data['bookmarks']['palette']='DaVinci Resolve'
        if not self.data['app'].get('cache_retention_version'):
            for section in ('thumbnails','waveform'):
                self.data[section].update(delete_on_close='no',delete_after_30_days='yes')
            self.data['app']['cache_retention_version']='1'
        for section in ('thumbnails','waveform'):
            if self.data.getboolean(section,'delete_after_30_days'):self.data[section]['delete_on_close']='no'
        if self.data['app'].get('review_controls_version','1')=='1':
            if self.data['magnifier']['refresh_ms']=='16':self.data['magnifier']['refresh_ms']='4'
            self.data['app']['review_controls_version']='2'
        self.data['waveform']['cache_directory']='Generated Waveforms'
        if not self.data['app'].get('selection_delete_version'):
            if not self.data['shortcuts_secondary']['remove_range']:self.data['shortcuts_secondary']['remove_range']='Backspace'
            self.data['app']['selection_delete_version']='1'
        if self.data['app'].get('history_defaults_version','1')=='1':
            if self.data['app']['undo_limit']=='200':self.data['app']['undo_limit']='50'
            self.data['app']['history_defaults_version']='2'
        if self.data['dual'].get('layout_version')!='3':
            try:panels=json.loads(self.data['dual']['panels'])
            except (TypeError,ValueError):panels=None
            old_default=[{'category':'Used','mode':'List'},{'category':'Deleted','mode':'List'}]
            if not isinstance(panels,list) or not panels or panels==old_default:self.data['dual']['panels']=defaults['dual']['panels']
            self.data['dual']['layout_version']='3'
        if not self.data['app'].get('arrow_defaults_version'):
            old={'previous':'Left','next':'Right','frame_back':',','frame_forward':'.'}
            if all(self.data['shortcuts'][k]==v for k,v in old.items()):
                for key in old:self.data['shortcuts'][key]=DEFAULT_KEYS[key]
            self.data['app']['arrow_defaults_version']='2'
        if self.legacy:self.save()

    def save(self):
        import io
        buffer=io.StringIO();self.data.write(buffer);content=buffer.getvalue()
        if not self.legacy and self.path.is_file() and self.path.read_text(encoding='utf-8')==content:return
        temp = self.path.with_suffix('.ini.writing')
        temp.write_text(content,encoding='utf-8')
        os.replace(temp, self.path)
        if self.legacy:
            old,mtime,size=self.legacy
            try:
                info=old.stat()
                if (info.st_mtime_ns,info.st_size)==(mtime,size):old.unlink()
            except OSError:pass  # The new file is complete; retain a changed/locked legacy copy.
            self.legacy=None

    def register(self, root, name,project_file=None):
        key = uuid.uuid5(uuid.NAMESPACE_URL, str(Path(root).resolve()).casefold()).hex
        try:previous=json.loads(self.data['projects'].get(key,'{}'))
        except ValueError:previous={}
        now=time.time()
        path=Path(project_file) if project_file else Path(root)/PROJECT_FILE
        created=path.stat().st_ctime if path.exists() else now
        item={'root': str(root), 'name': name,'created':previous.get('created',created),'opened':now}
        if project_file:item['project_file']=str(path.relative_to(self.path.parent))
        self.data['projects'][key] = json.dumps(item, ensure_ascii=False)
        self.data['app']['last_project'] = str(root)
        self.save()

    def projects(self):
        result = []
        for value in self.data['projects'].values():
            try:
                result.append(json.loads(value))
            except (ValueError, TypeError):
                pass
        return result


def canonical_key(value):
    parts = [p.strip() for p in value.split('+')]
    if not parts or not parts[-1]:
        raise ValueError('Enter a key, such as Ctrl+S or F24.')
    modifiers = set()
    aliases = {'control': 'Ctrl', 'ctrl': 'Ctrl', 'shift': 'Shift', 'alt': 'Alt'}
    for part in parts[:-1]:
        if part.lower() not in aliases:
            raise ValueError('Only Ctrl, Shift and Alt modifiers are supported.')
        modifiers.add(aliases[part.lower()])
    key = parts[-1]
    names = {'space': 'Space', 'left': 'Left', 'right': 'Right', 'up': 'Up', 'down': 'Down',
             'delete': 'Delete', 'backspace': 'Backspace', 'escape': 'Escape', 'return': 'Enter',
             'enter': 'Enter', 'home': 'Home', 'end': 'End', 'prior': 'PageUp', 'next': 'PageDown',
             'pageup': 'PageUp', 'pagedown': 'PageDown', 'tab': 'Tab',
             'comma': ',', 'period': '.', 'minus': '-', 'equal': '=',
             'bracketleft': '[', 'bracketright': ']', 'semicolon': ';',
             'apostrophe': "'", 'slash': '/', 'backslash': '\\', 'grave': '`',
             'mouseleft': 'MouseLeft', 'mouse1': 'MouseLeft', 'left click': 'MouseLeft',
             'mousemiddle': 'MouseMiddle', 'mouse2': 'MouseMiddle', 'middle click': 'MouseMiddle',
             'mouseright': 'MouseRight', 'mouse3': 'MouseRight', 'right click': 'MouseRight',
             'mousex1': 'MouseX1', 'mouse4': 'MouseX1', 'mousex2': 'MouseX2', 'mouse5': 'MouseX2'}
    if key.lower() in names:
        key = names[key.lower()]
    elif key.upper().startswith('F') and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        key = key.upper()
    elif len(key) == 1 and (key.isalnum() or key in ',.-=[];\'/\\`'):
        key = key.upper()
    else:
        raise ValueError('Use a key (including F1–F24), or MouseLeft / MouseMiddle / MouseRight / MouseX1 / MouseX2.')
    return '+'.join([m for m in ('Ctrl', 'Alt', 'Shift') if m in modifiers] + [key])


def key_from_event(event):
    # Windows VK codes identify F13–F24 even if Tcl gives them an unknown keysym.
    vk = getattr(event, 'keycode', 0)
    if 112 <= vk <= 135:
        key = f'F{vk - 111}'
    elif 48 <= vk <= 57:
        key = chr(vk)  # Shift+1 has keysym "exclam" but is still the 1 key.
    else:
        key = {188: ',', 190: '.', 189: '-', 187: '=', 219: '[', 221: ']',
               186: ';', 222: "'", 191: '/', 220: '\\', 192: '`'}.get(vk, event.keysym)
    if len(key) == 1:
        key = key.upper()
    mods = [name for mask, name in ((4, 'Ctrl'), (0x20000, 'Alt'), (1, 'Shift')) if event.state & mask]
    try:
        return canonical_key('+'.join(mods + [key]))
    except ValueError:
        return None


def mouse_binding(button, state=0):
    key = {1:'MouseLeft', 2:'MouseMiddle', 3:'MouseRight', 4:'MouseX1', 5:'MouseX2'}.get(button)
    if not key:
        return None
    mods = [name for mask, name in ((4,'Ctrl'), (0x20000,'Alt'), (1,'Shift')) if state & mask]
    return '+'.join(mods+[key])


class SpeedCycle:
    def __init__(self, timeout=3):
        self.timeout, self.last, self.base, self.step = timeout, -100, None, 0

    def press(self, base, now=None):
        now = time.monotonic() if now is None else now
        self.step = (self.step + 1) % 4 if self.base == base and now - self.last <= self.timeout else 0
        self.base, self.last = base, now
        return base + self.step * .25


class SlowCycle:
    """Decrease the current rate by a tenth, stopping at the supported minimum."""
    def press(self,current=1.):return max(.1,round(current-.1,2))


def profile_for_name(filename, cutoff):
    match = re.search(r'(\d{4}-\d{2}-\d{2})[ _](\d{2})[-:](\d{2})[-:](\d{2})', str(filename))
    if not match:
        return 'File track names'
    try:
        recorded = datetime.fromisoformat(f'{match[1]}T{match[2]}:{match[3]}:{match[4]}')
        return 'Legacy OBS' if recorded < datetime.fromisoformat(cutoff) else 'Modern OBS'
    except ValueError:
        return 'File track names'


def file_identity(path):
    s = Path(path).stat()
    return {'size': s.st_size, 'mtime_ns': s.st_mtime_ns}


def remember_source_move(clip,old_path):
    moves=clip.setdefault('studio_source_moves',[])
    record={'path':old_path,'identity':clip.get('identity')}
    if record not in moves:moves.append(record)


class Project:
    def __init__(self, root, name=None,project_file=None):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError('Choose an existing video project folder.')
        self.path = Path(project_file).resolve() if project_file else self.root / PROJECT_FILE
        saved=read_json(self.path) if self.path.exists() else {}
        ident=saved.get('project_id',uuid.uuid5(uuid.NAMESPACE_URL,str(self.root).casefold()).hex)
        if project_file and not re.fullmatch('[0-9a-f]{32}',ident):raise ValueError('Invalid project identifier.')
        self.metadata=(self.path.parent/'.Project Data'/ident) if project_file else self.root
        if project_file and not self.metadata.resolve().is_relative_to(self.path.parent):raise ValueError('The project data folder is redirected outside Projects.')
        if project_file:self.metadata.mkdir(parents=True,exist_ok=True)
        from review_folders import recover as recover_folders
        recover_folders(self.root,self.metadata,self.path)
        from review_trim_install import recover as recover_trim
        recover_trim(self.root,self.metadata,self.path)
        from review_merge_install import recover as recover_merge
        recover_merge(self.root,self.metadata,self.path)
        from review_trim_undo import recover as recover_undo_trim
        recover_undo_trim(self.root,self.metadata,self.path)
        self.recover()
        self.data = read_json(self.path) if self.path.exists() else {
            'schema': 1, 'name': name or self.root.name, 'clips': [], 'current_clip': '', 'transaction': ''}
        if self.data.get('schema') != 1:
            raise ValueError('This project was created by a newer version of ClipComb Pro.')
        self.dirty = False
        self.scan()
        from review_trim_undo import attach_receipts
        attach_receipts(self)
        self.reset_review_baseline()

    def persist_metadata(self):
        """Write review data without sorting, renaming or creating media folders."""
        disk=read_json(self.path) if self.path.exists() else {}
        if disk.get('transaction','')!=self.data.get('transaction',''):raise ValueError('This project changed in another window. Reopen it before saving.')
        updated=copy.deepcopy(self.data);updated['transaction']=uuid.uuid4().hex
        atomic_json(self.path,updated);self.data['transaction']=updated['transaction']

    def review_digest(self,clip):
        import hashlib
        fields=('ranges','markers','trim_ranges','decision','mix','audio_profile','star')
        values={k:(clip.get(k) or []) if k in ('ranges','markers','trim_ranges','mix') else clip.get(k) for k in fields}
        return hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).digest()

    def reset_review_baseline(self):
        self.review_baseline={c['id']:self.review_digest(c) for c in self.data['clips']}
        self.review_edits=set()

    def passive_clip(self,clip):
        if clip['id'] not in self.review_edits:self.review_baseline[clip['id']]=self.review_digest(clip)

    def mark_review(self,clip):
        clip['reviewed']=True
        if 'audio_original_mix' in clip:
            clip['audio_modified']=clip.get('mix',[])!=clip['audio_original_mix'] or (clip.get('audio_profile') or clip.get('audio_original_profile'))!=clip.get('audio_original_profile')
        if self.review_digest(clip)!=self.review_baseline.get(clip['id']):self.review_edits.add(clip['id'])
        else:self.review_edits.discard(clip['id'])

    @property
    def review_changed(self):return bool(self.review_edits)

    def folders(self):
        children = {p.name.casefold(): p for p in self.root.iterdir() if p.is_dir()}
        from review_folders import names
        return {status:children.get(name.casefold(),self.root/name) for status,name in names(self).items()}

    def checked(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError('A project file points outside its project folder.')
        return path

    def report_path(self,relative):
        from review_folders import remap
        for mapping in self.data.get('folder_renames',[]):relative=remap(relative,self.root,mapping)
        return self.checked(relative)

    def scan(self):
        from review_scan_reconcile import reconcile,path_key
        found={}
        for status, folder in self.folders().items():
            if not folder.exists():
                continue
            self.checked(folder.relative_to(self.root))
            for directory, dirs, files in os.walk(folder, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not Path(directory, d).is_symlink())
                for filename in sorted(files, key=str.casefold):
                    path = Path(directory, filename)
                    if path.suffix.lower() not in EXTENSIONS or path.is_symlink():
                        continue
                    rel = str(path.relative_to(self.root))
                    found[path_key(rel)]=(rel,status,file_identity(path))
        relocated,discarded=reconcile(self,self.data,found)
        if relocated:
            self.dirty=True
            if hasattr(self,'review_baseline'):
                for clip in self.data['clips']:
                    if clip['id'] in relocated:self.passive_clip(clip)
                for ident in discarded:
                    self.review_baseline.pop(ident,None);self.review_edits.discard(ident)
        known={path_key(c['path']) for c in self.data['clips']}
        for key,(rel,status,identity) in found.items():
            if key not in known:
                self.data['clips'].append({'id':uuid.uuid4().hex,'path':rel,'decision':status,'ranges':[],
                    'position':0,'media':None,'mix':[],'identity':identity})
                self.dirty=True
        for clip in self.data['clips']:
            clip['missing'] = not self.checked(clip['path']).is_file()
            if not clip['missing']:
                scanned=found.get(path_key(clip['path']))
                identity=scanned[2] if scanned else file_identity(self.checked(clip['path']))
                if identity != clip['identity']:
                    clip.update(identity=identity, media=None, position=0, changed_source=True)
                    for r in clip['ranges']:
                        r['enabled'] = False
                    self.dirty = True
        self.data['clips'].sort(key=lambda c: (Path(c['path']).name.casefold(), c['id']))
        return found

    def recover(self):
        journal_path = self.metadata / JOURNAL_FILE
        if not journal_path.exists():
            return
        journal = read_json(journal_path)
        saved = read_json(self.path) if self.path.exists() else {}
        if saved.get('transaction') != journal['transaction']:
            for move in reversed(journal['moves']):
                src, dst = self.checked(move['src']), self.checked(move['dst'])
                if dst.exists() and not src.exists():
                    if file_identity(dst) != move['identity']:
                        raise ValueError('A file changed during interrupted saving; recovery was paused to protect it.')
                    os.rename(dst, src)
                elif not src.exists() or dst.exists():
                    raise ValueError('Interrupted saving needs attention: both copies exist or a file is missing.')
        journal_path.unlink()

    def save(self):
        disk = read_json(self.path) if self.path.exists() else {}
        if disk.get('transaction', '') != self.data.get('transaction', ''):
            raise ValueError('This project was saved in another window. Reopen it before saving here.')
        folders = self.folders()
        moves, targets = [], set()
        for clip in self.data['clips']:
            status = clip['decision']
            if status not in folders:
                raise ValueError('Unknown clip destination.')
            src = self.checked(clip['path'])
            if not src.exists():
                if clip.get('missing'):
                    continue
                raise ValueError(f'{src.name} is missing. Rescan before saving.')
            if file_identity(src) != clip['identity']:
                raise ValueError(f'{src.name} changed outside ClipComb Pro. Reopen the project before sorting it.')
            dst = folders[status] / src.name
            self.checked(dst.relative_to(self.root))
            # Already in the correct category: preserve any nested path.
            if src.is_relative_to(folders[status].resolve()):
                continue
            key = str(dst).casefold()
            if dst.exists() or key in targets:
                raise ValueError(f'{dst.name} already exists in {status}. No clips were moved.')
            targets.add(key)
            moves.append({'id': clip['id'], 'src': clip['path'], 'dst': str(dst.relative_to(self.root)),
                          'identity': file_identity(src)})
        for folder in folders.values():
            self.checked(folder.relative_to(self.root))
            folder.mkdir(exist_ok=True)
        transaction = uuid.uuid4().hex
        journal = {'transaction': transaction, 'moves': moves}
        atomic_json(self.metadata / JOURNAL_FILE, journal)
        updated = copy.deepcopy(self.data)
        by_id = {c['id']: c for c in updated['clips']}
        try:
            for move in moves:
                os.rename(self.checked(move['src']), self.checked(move['dst']))
                remember_source_move(by_id[move['id']],move['src'])
                by_id[move['id']]['path'] = move['dst']
            updated['transaction'] = transaction
            atomic_json(self.path, updated)
        except Exception:
            self.recover()
            raise
        self.data, self.dirty = updated, False
        self.reset_review_baseline()
        (self.metadata / JOURNAL_FILE).unlink()
        return len(moves)

    def export_ranges(self,folders=None):
        self.save()
        from review_folder_selection import export_folders,ordered_folders
        folders=export_folders(self) if folders is None else [role for role in ordered_folders(self) if role in folders]
        clips = []
        for clip in self.data['clips']:
            ranges = [r for r in clip['ranges'] if r.get('enabled', True)]
            if ranges and clip['decision'] in folders and not clip.get('missing'):
                duration = (clip.get('media') or {}).get('duration')
                if any(not 0 <= r['start'] < r['end'] or duration and r['end'] > duration + .001 for r in ranges):
                    raise ValueError(f'Check the marked ranges in {Path(clip["path"]).name} before exporting.')
                clips.append({'id': clip['id'], 'path': str(self.checked(clip['path'])),
                              'relative_path': clip['path'], 'category': clip['decision'],
                              'identity':clip.get('identity'),
                              'studio_source_moves':[str(self.root/m['path']) for m in clip.get('studio_source_moves',[])
                                                     if m.get('identity')==clip.get('identity')],
                              'media': clip.get('media'), 'mix':clip.get('mix',[]),'audio_profile':clip.get('audio_profile'),
                              'markers':clip.get('markers',[]),'provenance':clip.get('provenance',[]),'ranges': ranges})
        payload = {'schema': 1, 'project': self.data['name'], 'time_unit': 'source_seconds','export_folders':folders,
                   'resolve_import_implemented': True, 'clips': clips}
        path = self.root / 'clip-review-export.json'
        atomic_json(path, payload)
        return path, sum(len(c['ranges']) for c in clips)


def probe_media(path, executable):
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    process = subprocess.run([str(executable), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                             capture_output=True, timeout=45, **options)
    if process.returncode:
        raise ValueError(process.stderr.decode('utf-8', 'replace')[-700:] or 'Cannot read this video.')
    raw = json.loads(process.stdout)
    streams = raw.get('streams', [])
    video = next((s for s in streams if s['codec_type'] == 'video'), {})
    container = raw.get('format', {}).get('format_name', '')
    elementary = container in ('mpegvideo', 'h264', 'hevc', 'av1', 'm4v')
    rate = (video.get('r_frame_rate') if elementary else video.get('avg_frame_rate'))
    if not rate or rate in ('0/0', '0/1'):
        rate = video.get('r_frame_rate') or '0/1'
    numerator, denominator = rate.split('/')
    fps = float(numerator)/(float(denominator) or 1)
    duration = float(raw.get('format', {}).get('duration') or video.get('duration') or 0)
    if video and (elementary or not math.isfinite(duration) or duration <= 0) and fps > 0:
        # Elementary streams have no container duration/index. Their bitrate-based
        # estimates can be wildly wrong; count frames once in the background.
        counted = subprocess.run([str(executable), '-v', 'error', '-select_streams', 'v:0', '-count_frames',
                                  '-show_entries', 'stream=nb_read_frames', '-of', 'json', str(path)],
                                 capture_output=True, timeout=180, **options)
        if counted.returncode == 0:
            frames = json.loads(counted.stdout).get('streams', [{}])[0].get('nb_read_frames')
            if frames and str(frames).isdigit():
                duration = int(frames)/fps
    audio = []
    for s in streams:
        if s['codec_type'] == 'audio':
            tags = {k.lower(): v for k, v in s.get('tags', {}).items()}
            audio.append({'index': len(audio), 'stream_index': s['index'],
                          'title': tags.get('title') or tags.get('handler_name') or '',
                          'sample_rate':int(s.get('sample_rate') or 48000),
                          'channels': s.get('channels', 0)})
    return {'duration': duration, 'fps': fps, 'fps_fraction':rate, 'width':video.get('width',1920),'height':video.get('height',1080),'audio': audio, 'container': container,
            'elementary': elementary, 'video_stream_index':video.get('index',0), 'video_codec': video.get('codec_name', ''),
            'pixel_format':video.get('pix_fmt',''),'color_range':video.get('color_range',''),
            'color_primaries':video.get('color_primaries',''),'color_transfer':video.get('color_transfer',''),
            'color_space':video.get('color_space','')}
