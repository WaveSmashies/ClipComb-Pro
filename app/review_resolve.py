# SPDX-License-Identifier: GPL-3.0-or-later
"""Direct Studio connection in Resolve's own interpreter. No plugin or AI needed."""
import json
import math
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from review_export import validate,frame,rate,marker_rows,marker_timing
import review_resolve_sync as sync


def covered(intervals,a,b):
    cursor=a
    for start,end in sorted(intervals):
        if end<cursor:continue
        if start>cursor+.01:return False
        cursor=max(cursor,end)
        if cursor>=b-.01:return True
    return False


def channel_count(subtype):
    value=str(subtype).casefold().replace(' ','').replace('_','').replace('-','')
    named={'mono':1,'stereo':2,'lrc':3,'lcr':3,'lrcs':4,'lcrs':4,'quad':4,
           '5.0':5,'5.0film':5,'5.1':6,'5.1film':6,'7.0':7,'7.0film':7,'7.1':8,'7.1film':8}
    if value.startswith('adaptive') and value[8:].isdigit():return int(value[8:])
    return named.get(value)


def choose_tracks(timeline,before,channels):
    def usable(kind,index):
        return not timeline.GetIsTrackLocked(kind,index) and timeline.GetIsTrackEnabled(kind,index)
    video=next((i for i in range(1,before['video']+1) if usable('video',i)),before['video']+1)
    if not channels:return video,1
    existing={i:channel_count(timeline.GetTrackSubType('audio',i)) if usable('audio',i) else None
              for i in range(1,before['audio']+1)}
    # Resolve appends a source's audio streams as a consecutive group. Prefer
    # an existing compatible block; extend a partial block only by its deficit.
    candidates=[]
    for start in range(1,before['audio']+2):
        if all(start+i>before['audio'] or existing[start+i]==count for i,count in enumerate(channels)):
            candidates.append((max(0,start+len(channels)-1-before['audio']),start))
    return video,min(candidates)[1]


def connect():
    try:import DaVinciResolveScript as dvr
    except ImportError:
        sys.path.insert(0,str(Path(os.environ.get('PROGRAMDATA','C:/ProgramData'))/'Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting/Modules'))
        import DaVinciResolveScript as dvr
    resolve=dvr.scriptapp('Resolve')
    if not resolve:raise RuntimeError('Cannot connect to Resolve Studio. Open Resolve and set Preferences → System → General → External scripting to Local. If it is already Local, restart Resolve and ClipComb Pro.')
    return resolve


def inspect(resolve):
    project=resolve.GetProjectManager().GetCurrentProject()
    if not project:raise ValueError('Open a Resolve project first.')
    current=project.GetCurrentTimeline()
    current_id=current.GetUniqueId() if current else None
    timelines=[]
    for i in range(1,project.GetTimelineCount()+1):
        t=project.GetTimelineByIndex(i)
        timelines.append({'id':t.GetUniqueId(),'name':t.GetName(),'fps':t.GetSetting('timelineFrameRate'),
                          'end':t.GetEndFrame(),'current':t.GetUniqueId()==current_id})
    return {'project':project.GetName(),'project_id':project.GetUniqueId(),'timelines':timelines}


def destination(resolve,request):
    project=resolve.GetProjectManager().GetCurrentProject()
    if not project or project.GetUniqueId()!=request['project_id']:raise ValueError('The open Resolve project changed. Refresh the connection and choose the destination again.')
    target=None
    for i in range(1,project.GetTimelineCount()+1):
        candidate=project.GetTimelineByIndex(i)
        if candidate.GetUniqueId()==request['timeline_id']:target=candidate;break
    if not target:raise ValueError('The selected timeline no longer exists. Refresh the connection.')
    if target.GetEndFrame()!=request['expected_end']:raise ValueError('The destination timeline changed since you selected it. Refresh before importing.')
    return project,target


def prepare(resolve,request):
    clips=validate(request['payload']);project,target=destination(resolve,request)
    planned=sync.plan(clips,request['payload'],target,request.get('existing_imports',[]))
    if request.get('skip_existing',True):sync.marker_operations(planned,target,request.get('timeline_markers',False))
    return dict(moved_sources=planned['moves'],plan_token=planned['token'])


def append(resolve,request):
    clips=validate(request['payload']);project,target=destination(resolve,request)
    state={'project':project.GetName()};mp=project.GetMediaPool()
    for clip in clips:clip['_export_ranges']=sync.ranges(clip)
    planned=sync.plan(clips,request['payload'],target,request.get('existing_imports',[])) if request.get('skip_existing',True) or request.get('plan_token') else None
    if request.get('plan_token') and request['plan_token']!=planned['token']:raise ValueError('Resolve clips or bookmarks changed while the import was being confirmed. Refresh before importing.')
    operations=sync.marker_operations(planned,target,request.get('timeline_markers',False)) if planned and request.get('skip_existing',True) else []
    skipped=0
    if request.get('skip_existing',True):
        selected=[]
        for clip in clips:
            intervals=planned['seen'][clip.get('id',clip['path'])];keep=[]
            for marked in clip['ranges']:
                a,b=frame(marked['start'],clip['media']['fps']),frame(marked['end'],clip['media']['fps'])
                if covered(intervals,a,b):skipped+=1
                else:keep.append(marked);intervals.append((a,b))
            if keep:clip['ranges']=keep;selected.append(clip)
        clips=selected
    if not resolve.GetProjectManager().SaveProject():raise RuntimeError('Resolve could not save the project before importing. Nothing was appended.')
    previous=project.GetCurrentTimeline();folder=mp.GetCurrentFolder()
    before={}
    for typ in ('video','audio'):
        before[typ]=target.GetTrackCount(typ)
    start=target.GetEndFrame();position=start;created=[];new_tracks=[];created_markers=[];used_tracks=[];baseline=None
    changed_markers=[];imports=list(planned['imports']) if planned else [];relinked=0
    try:
        for operation in operations:
            changed_markers.append(operation);sync.write_markers(operation,'after')
        # Resolve may reuse an existing media pool item. Read its mapping, but
        # never change source attributes shared by existing edits.
        sources=[]
        for clip in clips:
            got=mp.ImportMedia([clip['path']])
            if not got:raise ValueError('Resolve could not import '+Path(clip['path']).name+'. Check that this Resolve edition supports its container and codec.')
            item=got[0];mapping=json.loads(item.GetAudioMapping() or '{}').get('track_mapping',{})
            if len(mapping)!=len(clip['media']['audio']):
                raise ValueError('The Resolve audio mapping differs from the recording: '+item.GetName()+'. Restore its original audio track layout in Clip Attributes before importing.')
            channel=1
            for i,track in enumerate(clip['media']['audio']):
                expected=list(range(channel,channel+track['channels']))
                if mapping[str(i+1)].get('channel_idx')!=expected:
                    raise ValueError('The source audio channels were remapped in Resolve: '+item.GetName()+'. Restore the original audio layout in Clip Attributes before importing.')
                channel+=track['channels']
            sources.append((clip,item))
        if not project.SetCurrentTimeline(target):raise RuntimeError('Could not activate the selected timeline.')
        count=max((len(c['media']['audio']) for c in clips),default=0)
        channels=[max((int(c['media']['audio'][i]['channels']) for c in clips if len(c['media']['audio'])>i),default=2) for i in range(count)]
        vtrack,atrack=choose_tracks(target,before,channels)
        if clips and vtrack>before['video']:
            if not target.AddTrack('video'):raise RuntimeError('Could not add a video track.')
            new_tracks.append(('video',vtrack))
        for i,number in enumerate(channels):
            if atrack+i<=before['audio']:continue
            subtype='mono' if number==1 else 'stereo' if number==2 else f'adaptive_{number}'
            if not target.AddTrack('audio',subtype):raise RuntimeError('Could not add an audio track.')
            new_tracks.append(('audio',atrack+i))
        used_tracks=([('video',vtrack)]+[('audio',atrack+i) for i in range(count)]) if clips else []
        baseline={(kind,index):{item.GetUniqueId() for item in target.GetItemListInTrack(kind,index) or []} for kind,index in used_tracks}
        tfps=rate(target.GetSetting('timelineFrameRate'));moments=0
        for clip,item in sources:
            sfps=rate(item.GetClipProperty('FPS') or clip['media']['fps'])
            for selected in clip['ranges']:
                a,b=frame(selected['start'],sfps),frame(selected['end'],sfps)
                info={'mediaPoolItem':item,'startFrame':a,'endFrame':b,'recordFrame':position}
                video=mp.AppendToTimeline([dict(info,mediaType=1,trackIndex=vtrack)]) or []
                created.extend(video)
                if len(video)!=1:raise RuntimeError('Resolve could not append the selected video range.')
                for marker in marker_rows(clip,a,b,sfps):
                    at,duration=marker_timing(marker,sfps,tfps,local=request.get('timeline_markers',False))
                    if request.get('timeline_markers',False):
                        at+=round(position-target.GetStartFrame())
                        if at in (target.GetMarkers() or {}):raise RuntimeError('An existing timeline bookmark occupies an imported bookmark frame. The import was rolled back without changing that bookmark.')
                        if not target.AddMarker(at,marker['resolve_color'],marker['name'],marker['note'],duration,sync.tag(clip,video[0],marker)):
                            raise RuntimeError('Resolve could not attach a timeline bookmark. Import was rolled back.')
                        created_markers.append(at)
                    elif not video[0].AddMarker(at,marker['resolve_color'],marker['name'],marker['note'],duration,sync.tag(clip,video[0],marker)):
                        raise RuntimeError('Resolve could not attach a clip bookmark. Import was rolled back.')
                if clip['media']['audio']:
                    created.extend(mp.AppendToTimeline([dict(info,mediaType=2,trackIndex=atrack)]) or [])
                audio=[]
                for i in range(len(clip['media']['audio'])):
                    found=[x for x in target.GetItemListInTrack('audio',atrack+i) or []
                           if abs(x.GetStart()-position)<.01 and x.GetUniqueId() not in baseline['audio',atrack+i]]
                    created.extend(found);audio.extend(found)
                    if len(found)!=1:raise RuntimeError('Resolve did not create every source audio track.')
                    local_mapping=json.loads(found[0].GetSourceAudioChannelMapping() or '{}')
                    if any(m.get('mute') for m in local_mapping.get('track_mapping',{}).values()):
                        for mapping in local_mapping['track_mapping'].values():mapping['mute']=False
                        if not found[0].SetSourceAudioChannelMapping(json.dumps(local_mapping)):raise RuntimeError('Could not unmute the imported source channels.')
                    setting=(clip.get('mix') or [])[i] if i<len(clip.get('mix') or []) else {'enabled':True,'volume':100}
                    if request.get('apply_mix',True):
                        # Leave source mappings and clip enable state alone.
                        # Silence is editable with the normal Inspector volume.
                        db=20*math.log10(max(.00001,setting['volume']/100)) if setting['enabled'] else -100
                        if not found[0].SetProperties({'AudioVolume':max(-100,db)}):raise RuntimeError('Could not apply an audio level.')
                if audio and not target.SetClipsLinked([*video,*audio],True):raise RuntimeError('Could not link the imported video and audio.')
                expected=max(1,frame((b-a)/float(sfps),tfps))
                if abs(video[0].GetDuration()-expected)>1:raise RuntimeError('Resolve interpreted the source range with an unexpected duration. Import was rolled back.')
                if clip.get('id') and clip.get('identity'):imports.append(sync.receipt(clip,video[0],item,clip['_export_ranges']))
                position=video[0].GetEnd();moments+=1
        if planned and request.get('repair_links'):relinked=sync.repair_links(mp,planned)
        if relinked:
            for record in imports:
                move=next((m for m in planned['moves'] if m['media_id']==record['media_id']),None)
                if move:record['path']=move['new']
        if not resolve.GetProjectManager().SaveProject():raise RuntimeError('Resolve could not save the import.')
        return {'moments':moments,'skipped':skipped,'project':state['project'],'timeline':target.GetName(),'start':start,'end':position,
                'tracks_added':{kind:sum(t==kind for t,_ in new_tracks) for kind in ('video','audio')},
                'bookmarks_updated':sum(len(o['after']) for o in operations),'sources_relinked':relinked,
                'sources_left_offline':len(planned['moves'])-relinked if planned else 0,'imports':imports}
    except Exception as error:
        # Reused tracks contain existing edits. Remove only items absent from
        # their pre-import snapshots, including partially returned API results.
        markers_cleaned=all([target.DeleteMarkerAtFrame(at) for at in created_markers])
        for operation in reversed(changed_markers):
            try:sync.write_markers(operation,'before')
            except Exception:markers_cleaned=False
        remaining=[]
        for typ,index in used_tracks if baseline is not None else new_tracks:
            original=baseline.get((typ,index),set()) if baseline is not None else set()
            remaining.extend(item for item in target.GetItemListInTrack(typ,index) or [] if item.GetUniqueId() not in original)
        cleaned=not remaining or target.DeleteClips(remaining,False)
        for typ,index in reversed(new_tracks):
            if not target.GetItemListInTrack(typ,index):target.DeleteTrack(typ,index)
        if previous:project.SetCurrentTimeline(previous)
        if not cleaned or not markers_cleaned:raise RuntimeError(str(error)+' Resolve could not restore every item from this failed import. Check the tracks and bookmarks before retrying.') from error
        if relinked:raise RuntimeError(str(error)+f' {relinked} successfully repaired source links were retained.') from error
        raise
    finally:
        if folder:mp.SetCurrentFolder(folder)


if __name__=='__main__':
    try:
        request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        resolve=connect()
        result=inspect(resolve) if request['action']=='inspect' else prepare(resolve,request) if request['action']=='prepare' else append(resolve,request)
        response={'ok':True,'result':result}
    except Exception as error:response={'ok':False,'error':str(error)}
    target=Path(sys.argv[2]);tmp=target.with_suffix('.writing')
    tmp.write_text(json.dumps(response,ensure_ascii=False),encoding='utf-8');tmp.replace(target)
