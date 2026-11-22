# SPDX-License-Identifier: GPL-3.0-or-later
"""Native Kdenlive selects projects, referencing full original media only.

The native MLT project format selects embedded audio streams explicitly; the
Kdenlive OTIO importer currently ignores those selections and source offsets.
"""
import json
import math
import uuid
from pathlib import Path
import xml.etree.ElementTree as ET
from review_export import frame, export_marker_rows,timeline_defaults
from review_interchange import moments, gain
from review_marker_colors import KDENLIVE


def write_kdenlive(payload,path,fps=None,name=None,apply_mix=True,decoder=None,
                   timeline_markers=False,fix_bookmarks=False):
    path=Path(path);items=list(moments(payload,fps));fps=items[0][-1]
    total=items[-1][4]+items[-1][5];count=max(len(i[0]['media']['audio']) for i in items)
    uid='{'+str(uuid.uuid4())+'}';title=name or payload['project']+' selects'
    root=ET.Element('mlt',LC_NUMERIC='C',producer='main_bin',version='7.24.0',root=str(path.resolve().parent))
    def prop(node,key,value):
        ET.SubElement(node,'property',name=key).text=str(value)
    def props(node,values):
        for k,v in values.items():prop(node,k,v)
    def node(tag,**attrs):return ET.SubElement(root,tag,{k:str(v) for k,v in attrs.items()})
    settings=timeline_defaults([i[0] for i in items],fps);w=settings['width'];h=settings['height']
    ET.SubElement(root,'profile',description=f'{w}x{h} {fps}fps',width=str(w),height=str(h),
        frame_rate_num=str(fps.numerator),frame_rate_den=str(fps.denominator),progressive='1',
        sample_aspect_num='1',sample_aspect_den='1',display_aspect_num=str(w),display_aspect_den=str(h),colorspace='709')
    black=node('producer',id='producer0',**{'in':0,'out':max(total-1,0)})
    props(black,{'mlt_service':'color','resource':'black','length':2147483647,'eof':'continue','set.test_audio':1,'kdenlive:playlistid':'black_track'})
    sources={};binentries=[]
    for clip,sfps,*_ in items:
        source=str(Path(clip['path']).resolve())
        if source in sources:continue
        bid=str(4+len(sources));cid='chain'+str(len(sources));length=max(1,frame(clip['media']['duration'],fps))
        streams=clip['media']['audio'];control_uuid='{'+str(uuid.uuid4())+'}';sources[source]=(bid,cid,length,control_uuid)
        chain=node('chain',id=cid,out=length-1)
        props(chain,{'length':length,'eof':'pause','resource':Path(source).as_posix(),
            'mlt_service':'avformat','audio_index':streams[0].get('stream_index',1) if streams else -1,
            'video_index':clip['media'].get('video_stream_index',0),'kdenlive:id':bid,
            'kdenlive:control_uuid':control_uuid,
            'kdenlive:clipname':Path(source).name,'kdenlive:folderid':-1,
            'kdenlive:active_streams':';'.join(str(s.get('stream_index',i+1)) for i,s in enumerate(streams))})
        marks=[]
        # Clip bookmarks are stored on the full bin source, once per source.
        for mark in export_marker_rows(clip,0,frame(clip['media']['duration'],sfps),sfps,fix_bookmarks,target_fps=fps):
            marks.append(dict(pos=frame(mark['frame']/sfps,fps),duration=frame(mark['duration']/sfps,fps) if mark['is_range'] else 0,
                comment='\n'.join(filter(None,(mark['name'],mark['note']))),type=mark['color_slot']))
        prop(chain,'kdenlive:markers',json.dumps(marks))
        binentries.append((cid,length))
    # Each instance has its own stream selector and editable gain. All instances
    # carry the complete source duration, including media outside the selects.
    entries=[[] for _ in range(count+1)];groups=[];guides=[];levels={}
    for n,(clip,sfps,a,b,start,length,_) in enumerate(items):
        source=str(Path(clip['path']).resolve());bid,base,full,control_uuid=sources[source]
        source_in=frame(a/sfps,fps);source_out=source_in+length-1;children=[]
        for slot in range(count+1):
            video=slot==count
            stream=None if video else count-slot-1
            if not video and stream>=len(clip['media']['audio']):continue
            cid=f'chain{len(sources)+n*(count+1)+slot}';chain=node('chain',id=cid,out=full-1)
            info={} if video else clip['media']['audio'][stream]
            props(chain,{'length':full,'eof':'pause','resource':Path(source).as_posix(),'mlt_service':'avformat',
                'audio_index':-1 if video else info.get('stream_index',stream+1),'video_index':clip['media'].get('video_stream_index',0),
                'set.test_audio':1 if video else 0,'set.test_image':0 if video else 1,
                'kdenlive:id':bid,'kdenlive:clipname':Path(source).name,'kdenlive:control_uuid':control_uuid})
            if not video:
                prop(chain,'astream',stream)
                level=20*math.log10(gain(clip,stream,apply_mix))
                if abs(level)>.0001:levels[cid]=level
            entries[slot].append((start,cid,source_in,source_out,bid))
            children.append(dict(type='Leaf',leaf='clip',data=f'{slot}:{start}'))
        if len(children)>1:groups.append(dict(type='Normal',children=children))
        if timeline_markers:
            for mark in export_marker_rows(clip,a,b,sfps,fix_bookmarks,target_fps=fps):
                guides.append(dict(pos=start+frame((mark['frame']-a)/sfps,fps),
                    duration=frame(mark['duration']/sfps,fps) if mark['is_range'] else 0,comment='\n'.join(filter(None,(mark['name'],mark['note']))),type=mark['color_slot']))
    for slot,rows in enumerate(entries):
        pl=node('playlist',id=f'playlist{slot*2}');position=0
        for start,cid,a,b,bid in rows:
            if start>position:ET.SubElement(pl,'blank',length=str(start-position))
            e=ET.SubElement(pl,'entry',producer=cid,**{'in':str(a),'out':str(b)})
            prop(e,'kdenlive:id',bid);position=start+b-a+1
            # Kdenlive imports clip effects from the playlist entry. Filters on
            # a source chain are discarded while rebuilding timeline instances.
            if cid in levels:
                prop(e,'kdenlive:activeeffect',0)
                filt=ET.SubElement(e,'filter',id='filter'+cid.removeprefix('chain'))
                props(filt,{'mlt_service':'volume','kdenlive_id':'volume','window':75,'max_gain':'20dB',
                    'channel_mask':-1,'level':f'{a}={levels[cid]:.8f}'})
        node('playlist',id=f'playlist{slot*2+1}')
        tr=node('tractor',id=f'tractor{slot}',**{'in':0,'out':total-1})
        video=slot==count
        props(tr,{'kdenlive:track_name':'Video' if video else f'Audio {count-slot}',
            'kdenlive:trackheight':64,'kdenlive:timeline_active':1})
        if not video:prop(tr,'kdenlive:audio_track',1)
        for pid in (f'playlist{slot*2}',f'playlist{slot*2+1}'):
            ET.SubElement(tr,'track',producer=pid,hide='audio' if video else 'video')
    seq=node('tractor',id=uid,**{'in':0,'out':total-1})
    props(seq,{'kdenlive:uuid':uid,'kdenlive:control_uuid':uid,'kdenlive:clipname':title,'kdenlive:id':3,
        'kdenlive:producer_type':17,'kdenlive:folderid':2,'kdenlive:maxduration':total,'kdenlive:clip_type':0,
        'kdenlive:duration':f'{float(total/fps):.9f}',
        'kdenlive:sequenceproperties.hasAudio':int(count>0),'kdenlive:sequenceproperties.hasVideo':1,
        'kdenlive:sequenceproperties.tracksCount':count+1,'kdenlive:sequenceproperties.documentuuid':uid,
        'kdenlive:sequenceproperties.activeTrack':count,'kdenlive:sequenceproperties.position':0,
        'kdenlive:sequenceproperties.zonein':0,'kdenlive:sequenceproperties.zoneout':total,
        'kdenlive:sequenceproperties.zoom':max(0,min(20,round(2+math.log(max(1,float(total/fps)/3),1.6)))),
        'kdenlive:sequenceproperties.groups':json.dumps(groups),
        'kdenlive:sequenceproperties.guides':json.dumps(guides)})
    ET.SubElement(seq,'track',producer='producer0')
    for slot in range(count+1):ET.SubElement(seq,'track',producer=f'tractor{slot}')
    for slot in range(count+1):
        transition=ET.SubElement(seq,'transition')
        props(transition,{'a_track':0,'b_track':slot+1,'mlt_service':'qtblend' if slot==count else 'mix',
            'kdenlive_id':'qtblend' if slot==count else 'mix','internal_added':237,'always_active':1})
        if slot<count:props(transition,{'sum':1,'accepts_blanks':1})
    main=node('playlist',id='main_bin')
    props(main,{'kdenlive:folder.-1.2':'Sequences','kdenlive:sequenceFolder':2,
        'kdenlive:docproperties.audioChannels':2,'kdenlive:docproperties.version':'1.1',
        'kdenlive:docproperties.documentid':uuid.uuid4().int%10**13,
        'kdenlive:docproperties.uuid':uid,'kdenlive:docproperties.activetimeline':uid,
        'kdenlive:docproperties.opensequences':uid,'kdenlive:docproperties.enableproxy':0,'xml_retain':1,
        'kdenlive:docproperties.guidesCategories':json.dumps([dict(index=i,color=c,comment=f'Bookmark {i+1}') for i,c in enumerate(KDENLIVE)])})
    ET.SubElement(main,'entry',producer=uid,**{'in':'0','out':'0'})
    for cid,length in binentries:ET.SubElement(main,'entry',producer=cid,**{'in':'0','out':str(length-1)})
    master=node('tractor',id=f'tractor{count+1}',**{'in':0,'out':total-1})
    prop(master,'kdenlive:projectTractor',1)
    ET.SubElement(master,'track',producer=uid,**{'in':'0','out':str(total-1)})
    ET.indent(root);temp=path.with_suffix('.writing')
    ET.ElementTree(root).write(temp,encoding='utf-8',xml_declaration=True);temp.replace(path)
    return dict(path=str(path),moments=len(items),frames=total,fps=str(fps))
