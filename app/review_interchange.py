# SPDX-License-Identifier: GPL-3.0-or-later
"""Editor interchange referencing original media for both video and audio."""
from fractions import Fraction
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from review_export import rate,frame,validate,marker_rows,marker_timing,export_marker_rows,timeline_defaults
from review_marker_colors import RESOLVE_OTIO


def gain(clip,index,apply_mix):
    mix=clip.get('mix',[])
    if not apply_mix or index>=len(mix):return 1.0
    return max(.00001,mix[index]['volume']/100) if mix[index]['enabled'] else .00001


def moments(payload,fps):
    clips=validate(payload);fps=timeline_defaults(clips,fps)['fps'];position=0
    for clip in clips:
        sfps=rate(clip['media']['fps'])
        for mark in clip['ranges']:
            a,b=frame(mark['start'],sfps),frame(mark['end'],sfps)
            length=max(1,frame(Fraction(b-a)/sfps,fps))
            yield clip,sfps,a,b,position,length,fps
            position+=length


def write_premiere_xml(payload,path,fps=None,name=None,apply_mix=True,decoder=None,timeline_markers=False):
    """FCP 7 XML: each original stream is an explicitly linked channel group."""
    path=Path(path);items=list(moments(payload,fps));fps=items[0][-1]
    root=ET.Element('xmeml',version='5');seq=ET.SubElement(root,'sequence',id='clip-review-sequence')
    def add(node,key,value):
        child=ET.SubElement(node,key);child.text=str(value);return child
    def xmlrate(parent,value):
        r=ET.SubElement(parent,'rate');tb=round(float(value))
        add(r,'timebase',tb);add(r,'ntsc','TRUE' if value==Fraction(tb*1000,1001) else 'FALSE')
    def timecode(node,value):
        tc=ET.SubElement(node,'timecode');add(tc,'string','00:00:00:00');add(tc,'frame',0);add(tc,'displayformat','NDF');xmlrate(tc,value)
    for value in {fps,*[i[1] for i in items]}:
        tb=round(float(value))
        if value not in (Fraction(tb),Fraction(tb*1000,1001)):
            raise ValueError('Legacy Premiere XML cannot accurately describe this frame rate. Choose FCPXML or OTIO, or a standard timeline rate.')
    total=items[-1][4]+items[-1][5]
    add(seq,'name',name or payload['project']+' selects');add(seq,'duration',total);xmlrate(seq,fps);timecode(seq,fps)
    media=ET.SubElement(seq,'media');video=ET.SubElement(media,'video');audio=ET.SubElement(media,'audio')
    chars=ET.SubElement(ET.SubElement(video,'format'),'samplecharacteristics');xmlrate(chars,fps)
    settings=timeline_defaults([i[0] for i in items],fps)
    add(chars,'width',settings['width']);add(chars,'height',settings['height'])
    add(chars,'pixelaspectratio','square');add(chars,'fielddominance','none')
    vt=ET.SubElement(video,'track');tracks=[];track_counts=[];files={}
    channel_counts=[max([int(i[0]['media']['audio'][t]['channels']) if t<len(i[0]['media']['audio']) else 0 for i in items])
                    for t in range(max(len(i[0]['media']['audio']) for i in items))]
    for count in channel_counts:
        tracks.append([ET.SubElement(audio,'track') for _ in range(count)]);track_counts.append([0]*count)
    def file_node(parent,source,value,duration,dimensions):
        key=str(source)
        if key in files:return ET.SubElement(parent,'file',id=files[key])
        fid='file-'+str(len(files)+1);files[key]=fid;node=ET.SubElement(parent,'file',id=fid)
        add(node,'name',source.name);add(node,'pathurl',source.resolve().as_uri().replace('file:///','file://localhost/'))
        add(node,'duration',duration);xmlrate(node,value);timecode(node,value)
        m=ET.SubElement(node,'media')
        v=ET.SubElement(m,'video');add(v,'duration',duration);c=ET.SubElement(v,'samplecharacteristics');xmlrate(c,value)
        add(c,'width',dimensions.get('width',1920));add(c,'height',dimensions.get('height',1080));add(c,'pixelaspectratio','square');add(c,'fielddominance','none')
        streams=dimensions.get('audio',[])
        if streams:
            au=ET.SubElement(m,'audio');c=ET.SubElement(au,'samplecharacteristics')
            sample_rate=streams[0].get('sample_rate')
            if sample_rate:add(c,'samplerate',sample_rate)
            add(au,'channelcount',sum(int(s['channels']) for s in streams))
        return node
    def item(parent,cid,title,start,end,a,b,value,duration):
        node=ET.SubElement(parent,'clipitem',id=cid);add(node,'name',title);add(node,'duration',duration);xmlrate(node,value)
        for k,v in [('start',start),('end',end),('in',a),('out',b),('enabled','TRUE')]:add(node,k,v)
        return node
    for n,(clip,sfps,a,b,start,length,_) in enumerate(items):
        source=Path(clip['path']);end=start+length;vid=f'video-{n}'
        node=item(vt,vid,source.name,start,end,a,b,sfps,frame(clip['media']['duration'],sfps))
        file_node(node,source,sfps,frame(clip['media']['duration'],sfps),dimensions=clip['media'])
        links=[(node,vid,'video',1,n+1,None)]
        for marker in marker_rows(clip,a,b,sfps):
            mark=ET.SubElement(seq if timeline_markers else node,'marker')
            at,duration=marker_timing(marker,sfps,fps if timeline_markers else sfps,local=timeline_markers)
            if timeline_markers:at+=start
            for key,value in [('name',marker['name']),('comment',marker['note']),('in',at),('out',at+duration if marker['is_range'] else -1),('pproColor',marker['premiere_color'])]:add(mark,key,value)
        channel_offset=0
        for t,info in enumerate(clip['media']['audio']):
            for ch in range(int(info['channels'])):
                cid=f'audio-{n}-{t}-{ch}';track_counts[t][ch]+=1;track_index=1+sum(channel_counts[:t])+ch
                an=item(tracks[t][ch],cid,info.get('title') or f'Track {t+1}',start,end,a,b,sfps,frame(clip['media']['duration'],sfps))
                file_node(an,source,sfps,frame(clip['media']['duration'],sfps),dimensions=clip['media'])
                st=ET.SubElement(an,'sourcetrack');add(st,'mediatype','audio');add(st,'trackindex',channel_offset+ch+1)
                filt=ET.SubElement(an,'filter');effect=ET.SubElement(filt,'effect')
                for k,v in [('name','Audio Levels'),('effectid','audiolevels'),('effecttype','audiolevels'),('mediatype','audio'),('effectcategory','audiolevels')]:add(effect,k,v)
                p=ET.SubElement(effect,'parameter');add(p,'name','Level');add(p,'parameterid','level');add(p,'value',gain(clip,t,apply_mix))
                if int(info['channels'])==2:
                    pan=ET.SubElement(ET.SubElement(an,'filter'),'effect')
                    for k,v in [('name','Audio Pan'),('effectid','audiopan'),('effecttype','audiopan'),('mediatype','audio'),('effectcategory','audiopan')]:add(pan,k,v)
                    p=ET.SubElement(pan,'parameter');add(p,'name','Pan');add(p,'parameterid','pan');add(p,'value',-1 if ch==0 else 1)
                links.append((an,cid,'audio',track_index,track_counts[t][ch],t+1))
            channel_offset+=int(info['channels'])
        for parent,*unused in links:
            for _,cid,kind,ti,ci,group in links:
                link=ET.SubElement(parent,'link');add(link,'linkclipref',cid);add(link,'mediatype',kind);add(link,'trackindex',ti);add(link,'clipindex',ci)
                if group is not None:add(link,'groupindex',group)
    ET.indent(root);temp=path.with_suffix('.writing')
    temp.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'+ET.tostring(root,encoding='utf-8'));temp.replace(path)
    return {'path':str(path),'moments':len(items),'frames':total,'fps':str(fps)}


def write_otio(payload,path,fps=None,name=None,apply_mix=True,decoder=None,resolve_metadata=False,timeline_markers=False,fix_bookmarks=False):
    # Load only for this export, keeping the playback application's startup light.
    import opentimelineio as otio
    path=Path(path);items=list(moments(payload,fps));fps=items[0][-1]
    if not resolve_metadata and any(len(item[0]['media']['audio'])>1 for item in items):
        raise ValueError('Kdenlive’s OTIO importer cannot select different embedded audio streams from the same source file. Choose Kdenlive project · Original media for Kdenlive, or the dedicated Resolve, Premiere or Final Cut export for those editors. No audio files were created.')
    rt=lambda value,rate_:otio.opentime.RationalTime(float(value),float(rate_))
    tr=lambda start,duration,rate_:otio.opentime.TimeRange(rt(start,rate_),rt(duration,rate_))
    timeline=otio.schema.Timeline(name=name or payload['project']+' selects',global_start_time=rt(0,fps))
    if resolve_metadata:timeline.metadata['Resolve_OTIO']={'Resolve OTIO Meta Version':'1.0'}
    settings=timeline_defaults([i[0] for i in items],fps)
    timeline.metadata['clip_review']={**{k:str(v) if k=='fps' else v for k,v in settings.items()},'audio_levels':'Review gain stored as metadata; adjust levels in the destination editor.'}
    video=otio.schema.Track(name='Video',kind=otio.schema.TrackKind.Video);timeline.tracks.append(video)
    audio=[otio.schema.Track(name=f'Audio {i+1}',kind=otio.schema.TrackKind.Audio)
           for i in range(max(len(i[0]['media']['audio']) for i in items))]
    for i,track in enumerate(audio):
        if resolve_metadata:track.metadata['Resolve_OTIO']={'Audio Type':'Mono' if max((int(item[0]['media']['audio'][i]['channels']) for item in items if i<len(item[0]['media']['audio'])),default=2)==1 else 'Stereo','Locked':False,'SoloOn':False}
        timeline.tracks.append(track)
    for n,(clip,sfps,a,b,start,length,_) in enumerate(items):
        reference=otio.schema.ExternalReference(target_url=Path(clip['path']).resolve().as_posix(),available_range=tr(0,frame(clip['media']['duration'],sfps),sfps))
        reference.available_image_bounds=otio.schema.Box2d(otio.schema.V2d(0,0),otio.schema.V2d(clip['media'].get('width',1920),clip['media'].get('height',1080)))
        reference.metadata['clip_review']={k:clip['media'].get(k,'') for k in ('color_primaries','color_transfer','color_space','color_range','pixel_format')}
        # Duration is on the timeline clock; source start remains in source frames.
        v=otio.schema.Clip(name=Path(clip['path']).name,media_reference=reference,source_range=otio.opentime.TimeRange(rt(a,sfps),rt(length,fps)))
        video.append(v)
        if resolve_metadata:v.metadata['Resolve_OTIO']={'Link Group ID':n+1}
        for marker in export_marker_rows(clip,a,b,sfps,fix_bookmarks and not resolve_metadata,target_fps=fps):
            clock=fps if timeline_markers else sfps
            # Kdenlive's clip importer adds the clip source start itself.
            at,duration=marker_timing(marker,sfps,clock,local=timeline_markers or fix_bookmarks and not resolve_metadata)
            if timeline_markers:at+=start
            # Kdenlive displays the OTIO comment as its bookmark label.
            comment='\n'.join(filter(None,(marker['name'],marker['note']))) if fix_bookmarks and not resolve_metadata else marker['note']
            mark=otio.schema.Marker(name=marker['name'],comment=comment,
                                    marked_range=tr(at,duration,clock),color=RESOLVE_OTIO[marker['color_slot']] if resolve_metadata else marker['otio_color'])
            mark.metadata['clip_review']={'id':marker['id'],'color_slot':marker['color_slot'],'resolve_color':marker['resolve_color']}
            if marker.get('range_role'):mark.metadata['clip_review'].update(range_id=marker['range_id'],range_role=marker['range_role'],note=marker['note'])
            mark.metadata['Resolve_OTIO']={'Note':marker['note'],'Keywords':[]}
            (timeline.tracks if timeline_markers else v).markers.append(mark)
        for i,track in enumerate(audio):
            if i>=len(clip['media']['audio']):track.append(otio.schema.Gap(source_range=tr(0,length,fps)));continue
            info=clip['media']['audio'][i]
            reference=otio.schema.ExternalReference(target_url=Path(clip['path']).resolve().as_posix(),available_range=tr(0,frame(clip['media']['duration'],sfps),sfps))
            aclip=otio.schema.Clip(name=info.get('title') or f'Track {i+1}',media_reference=reference,source_range=otio.opentime.TimeRange(rt(a,sfps),rt(length,fps)))
            aclip.metadata['clip_review']={'gain':gain(clip,i,apply_mix),'channels':int(info['channels']),'moment':n+1,'source_audio_stream':i}
            if resolve_metadata:
                aclip.metadata['Resolve_OTIO']={'Link Group ID':n+1,'Channels':[{'Source Track ID':i,'Source Channel ID':j} for j in range(int(info['channels']))]}
                db=max(-100.,20*math.log10(gain(clip,i,apply_mix)))
                effect=otio.schema.Effect(effect_name='Resolve Effect')
                effect.metadata['Resolve_OTIO']={'Display Type':1,'Effect Name':'Fairlight Clip Volume and Fades',
                    'Enabled':True,'Name':'Volume','Type':62,'Parameters':[{'Default Parameter Value':0.,'Key Frames':{},
                    'Parameter ID':'volume','Parameter Value':db,'Variant Type':'Double','maxValue':30.,'minValue':-100.}]}
                aclip.effects.append(effect)
            track.append(aclip)
    temp=path.with_suffix('.writing')
    # Single-reference Clip.1 is understood by older editor integrations too.
    otio.core.serialize_json_to_file(timeline,str(temp),{} if resolve_metadata else {'Clip':1});temp.replace(path)
    return {'path':str(path),'moments':len(items),'frames':items[-1][4]+items[-1][5],'fps':str(fps)}


def write_resolve_otio(*args,**kwargs):
    kwargs['resolve_metadata']=True
    return write_otio(*args,**kwargs)
