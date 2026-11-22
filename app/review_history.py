# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded, compressed per-clip edit history; never snapshots the whole project."""
from collections import deque
import copy,json,time,zlib

FIELDS=('ranges','decision','mix','audio_profile','markers','trim_ranges','audio_modified','star')
def snapshot(clip):return {k:copy.deepcopy(clip[k]) for k in FIELDS if k in clip}
def limit_value(value):
    s=str(value).strip()
    if not s.isdecimal():raise ValueError('Undo actions must be a non-negative whole number.')
    return 1000000 if len(s)>7 else min(1000000,int(s))

def describe(delta):
    delta={k:v for k,v in delta.items() if k!='audio_modified'}
    if len(delta)!=1:return 'Edit clip'
    key,(before,after)=next(iter(delta.items()))
    if key=='star':return 'Edit clip Star' if after else 'Remove clip Star'
    if key=='markers':
        if len(after or [])>len(before or []):return 'Add clip marker'
        if len(after or [])<len(before or []):return 'Remove clip marker'
        return 'Edit clip marker'
    if key=='trim_ranges':return 'Adjust file trim plan'
    if key=='decision':return 'Mark '+str(after)
    if key=='audio_profile':return 'Change audio layout'
    if key=='mix':
        if after and not any(m['enabled'] for m in after):return 'Mute all tracks'
        if any(a.get('volume')!=b.get('volume') for a,b in zip(before or [],after or [])):return 'Adjust track volume'
        return 'Change audible tracks'
    if key=='ranges':
        before,after=before or [],after or []
        if len(after)>len(before):return 'Add marked moment'
        if len(after)<len(before):return 'Remove marked moment'
        if [r.get('id') for r in before]!=[r.get('id') for r in after]:return 'Reorder marked moments'
        if any(a.get('enabled',True)!=b.get('enabled',True) for a,b in zip(before,after)):return 'Change moment export selection'
        return 'Adjust marked moment'
    return 'Edit clip'

class History:
    def __init__(self,limit=50,budget=64*1024*1024):
        self.undo,self.redo=deque(),deque();self.limit=limit_value(limit);self.budget=budget;self.bytes=0
        self.current_id,self.baseline=None,None
    def watch(self,clip):self.current_id,self.baseline=clip['id'],snapshot(clip) if self.limit else None
    def clear(self):self.undo.clear();self.redo.clear();self.bytes=0;self.current_id=self.baseline=None
    def forget(self,clip_id):
        for name in ('undo','redo'):
            entries=getattr(self,name)
            for entry in list(entries):
                if entry[0]==clip_id:entries.remove(entry);self.bytes-=len(entry[1])+256
                elif entry[0] is None:
                    changes=json.loads(zlib.decompress(entry[1]))
                    if clip_id not in changes:continue
                    del changes[clip_id];index=entries.index(entry);del entries[index];self.bytes-=len(entry[1])+256
                    if changes:
                        data=zlib.compress(json.dumps(changes,separators=(',',':')).encode(),3)
                        entries.insert(index,(None,data,None,entry[3]));self.bytes+=len(data)+256
        if self.current_id==clip_id:self.current_id=self.baseline=None
    def trim(self):
        while self.undo and (len(self.undo)>self.limit or self.bytes>self.budget):self.bytes-=len(self.undo.popleft()[1])+256
        while self.redo and (len(self.redo)>self.limit or self.bytes>self.budget):self.bytes-=len(self.redo.popleft()[1])+256
    def record(self,clip,group=None,fields=None):
        if not self.limit:self.current_id,self.baseline=clip['id'],None;return
        if self.current_id!=clip['id'] or self.baseline is None:self.watch(clip);return
        # A volume-slider event must not copy a potentially huge range list.
        # Compare only the fields the action can change, then copy actual edits.
        delta={}
        for k in (FIELDS if fields is None else fields):
            before,after=self.baseline.get(k),clip.get(k)
            if before!=after:
                after=copy.deepcopy(after);delta[k]=[before,after];self.baseline[k]=after
        if not delta:return
        for entry in self.redo:self.bytes-=len(entry[1])+256
        self.redo.clear()
        if not self.limit:return
        key=(clip['id'],group) if group else None
        if key and self.undo and self.undo[-1][2]==key:
            old=self.undo.pop();self.bytes-=len(old[1])+256;previous=json.loads(zlib.decompress(old[1]))
            for k,v in previous.items():delta[k]=[v[0],delta[k][1] if k in delta else v[1]]
        data=zlib.compress(json.dumps(delta,separators=(',',':')).encode(),3)
        if len(data)>min(self.budget,8*1024*1024):self.clear();self.watch(clip);return
        self.undo.append((clip['id'],data,key,describe(delta)));self.bytes+=len(data)+256;self.trim()
    def next_action(self,redo=False):
        entries=self.redo if redo else self.undo
        return (entries[-1][0],entries[-1][3]) if entries else None
    def record_decisions(self,changes,label):
        if not self.limit:raise ValueError('Enable Undo history in Settings before moving multiple clips at once.')
        data=zlib.compress(json.dumps(changes,separators=(',',':')).encode(),3)
        if len(data)+256>min(self.budget,8*1024*1024):raise ValueError('This move is too large to keep in Undo history. Choose fewer source folders.')
        for entry in self.redo:self.bytes-=len(entry[1])+256
        self.redo.clear();self.undo.append((None,data,None,label));self.bytes+=len(data)+256;self.trim()
    def take(self,redo=False):
        source,target=(self.redo,self.undo) if redo else (self.undo,self.redo)
        if not source:return None
        entry=source.pop();target.append(entry)
        changes=json.loads(zlib.decompress(entry[1]))
        if entry[0] is None:return None,{'decisions':{ident:pair[1 if redo else 0] for ident,pair in changes.items()}}
        return entry[0],{k:v[1 if redo else 0] for k,v in changes.items()}
