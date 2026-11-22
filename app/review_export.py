# SPDX-License-Identifier: GPL-3.0-or-later
"""Source-range interchange. Times are half-open source seconds, never timecode."""
import copy
import math
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET
from review_marker_colors import slot,NAMES,OTIO,PREMIERE_INDEX
from review_marker_ranges import duration as marker_duration


def rate(value):
    f=Fraction(str(value)).limit_denominator(1001000)
    for n in (24,30,48,60,120):
        ntsc=Fraction(n*1000,1001)
        if abs(float(f-ntsc))<.002:return ntsc
    if f<=0:raise ValueError('A positive frame rate is required.')
    return f


def frame(seconds,fps):
    value=Fraction(str(seconds))*rate(fps)
    return (value.numerator*2+value.denominator)//(2*value.denominator)


def timeline_defaults(clips,fps=None):
    """Independent maxima: fastest source clock and largest source raster."""
    media=[c['media'] for c in clips]
    largest=max(media,key=lambda m:(int(m.get('width',1920))*int(m.get('height',1080)),int(m.get('width',1920))))
    colors=[source_color(m) for m in media]
    color=next((c for c in ('9-16-9 (Rec. 2020 PQ)','9-18-9 (Rec. 2020 HLG)','9-1-9 (Rec. 2020)') if c in colors),'1-1-1 (Rec. 709)')
    return dict(fps=rate(fps) if fps else max(rate(m.get('fps_fraction') or m['fps']) for m in media),
                width=int(largest.get('width',1920)),height=int(largest.get('height',1080)),color_space=color)


def source_color(media):
    transfer=media.get('color_transfer','')
    if transfer=='smpte2084':return '9-16-9 (Rec. 2020 PQ)'
    if transfer=='arib-std-b67':return '9-18-9 (Rec. 2020 HLG)'
    primaries=media.get('color_primaries')
    return {'bt2020':'9-1-9 (Rec. 2020)','bt709':'1-1-1 (Rec. 709)',
            'smpte170m':'6-1-6 (Rec. 601 NTSC)','bt470bg':'5-1-6 (Rec. 601 PAL)'}.get(primaries)


def validate(payload):
    if payload.get('schema')!=1 or payload.get('time_unit')!='source_seconds':
        raise ValueError('This is not a supported ClipComb Pro ranges file.')
    clips=[]
    for source in payload.get('clips',[]):
        clip=copy.deepcopy(source)
        folders=payload.get('export_folders')
        if clip.get('missing') or (clip.get('category') not in folders if isinstance(folders,list) else clip.get('category')=='Deleted'):continue
        ranges=[r for r in clip.get('ranges',[]) if r.get('enabled',True)]
        if not ranges:continue
        path=Path(clip['path'])
        if not path.is_absolute() or not path.is_file():raise ValueError(f'Source file is missing: {path}')
        media=clip.get('media') or {}
        if not media.get('fps') or not media.get('duration'):raise ValueError(f'Open this clip once to read its media information: {path.name}')
        for r in ranges:
            a,b=float(r['start']),float(r['end'])
            if not all(math.isfinite(x) for x in (a,b)) or not 0<=a<b<=float(media['duration'])+.001:
                raise ValueError(f'Invalid marked moment in {path.name}.')
            if frame(b,media['fps'])<=frame(a,media['fps']):raise ValueError(f'A marked moment is shorter than one source frame: {path.name}')
        clip['ranges']=ranges
        clips.append(clip)
    if not clips:raise ValueError('There are no enabled marked moments to export from the selected folders. Missing clips are excluded.')
    return clips


def marker_rows(clip,a,b,fps):
    rows=[]
    for marker in clip.get('markers',[]):
        try:
            time=float(marker['time'])
            if not math.isfinite(time):continue
            position=frame(time,fps)
        except (KeyError,ValueError,TypeError):continue
        span=marker_duration(marker)
        finish=frame(time+span,fps) if span else position+1
        if span and finish>position:
            position,finish=max(a,position),min(b,finish)
            included=finish>position
        else:
            included=a<=position<b;finish=position+1
        if included:
            color=slot(marker)
            rows.append({'frame':position,'local_frame':position-a,'duration':max(1,finish-position),'is_range':bool(span),
                         'id':str(marker.get('id','')),
                         'name':str(marker.get('name') or 'Bookmark'),'note':str(marker.get('note') or ''),
                         'color_slot':color,'resolve_color':NAMES[color],'otio_color':OTIO[color],
                         'premiere_color':PREMIERE_INDEX[color]})
    return rows


def marker_timing(marker,source_fps,target_fps,local=False):
    """Convert both span boundaries together, avoiding fractional-rate drift."""
    start=marker['local_frame'] if local else marker['frame']
    at=frame(Fraction(start)/rate(source_fps),target_fps)
    finish=frame(Fraction(start+marker['duration'])/rate(source_fps),target_fps)
    return at,max(1,finish-at) if marker['is_range'] else 1


def export_marker_rows(clip,a,b,fps,point_pairs=False,target_fps=None):
    rows=marker_rows(clip,a,b,fps)
    if not point_pairs:return rows
    result=[]
    for marker in rows:
        if not marker['is_range']:
            result.append(marker);continue
        # The out boundary is exclusive. Use the last included frame so the
        # second bookmark remains on its clip even when the span ends at a cut.
        target_fps=rate(target_fps or fps)
        last=a+Fraction(max(0,frame(Fraction(b-a)/rate(fps),target_fps)-1))*rate(fps)/target_fps
        start=min(marker['frame'],last);finish=min(marker['frame']+marker['duration']-1,last)
        collapsed=frame(Fraction(start-a)/rate(fps),target_fps)==frame(Fraction(finish-a)/rate(fps),target_fps)
        common=dict(marker,duration=1,is_range=False,range_id=marker['id'])
        if collapsed:
            result.append(dict(common,frame=start,local_frame=start-a,name='1 / 2 '+marker['name'],range_role='both'))
        else:
            result.append(dict(common,id=marker['id']+':start',frame=start,local_frame=start-a,name='1 '+marker['name'],range_role='start'))
            result.append(dict(common,id=marker['id']+':end',name='2 '+marker['name'],range_role='end',
                               frame=finish,local_frame=finish-a))
    return result


def fcpxml_marker_note(marker,fps):
    # Final Cut has point markers, not duration markers. Retain the span as
    # readable information on that same bookmark instead of changing its type.
    if not marker['is_range']:return marker['note']
    def clock(value):
        minutes,seconds=divmod(float(Fraction(value)/rate(fps)),60)
        hours,minutes=divmod(int(minutes),60)
        return (f'{hours:02}:' if hours else '')+f'{minutes:02}:{seconds:06.3f}'
    span=f"Bookmark range: {clock(marker['frame'])}–{clock(marker['frame']+marker['duration'])} in source clip."
    return '\n'.join(filter(None,(marker['note'],span)))


def write_fcpxml(payload,path,fps=None,name=None,apply_mix=True,decoder=None,timeline_markers=False,fix_bookmarks=False):
    clips=validate(payload);settings=timeline_defaults(clips,fps);fps=settings['fps']
    def seconds(value):
        f=Fraction(value);return f'{f.numerator}/{f.denominator}s'
    root=ET.Element('fcpxml',version='1.8');resources=ET.SubElement(root,'resources')
    ET.SubElement(resources,'format',id='timeline-format',name='FFVideoFormatRateUndefined',
                  frameDuration=seconds(1/fps),width=str(settings['width']),height=str(settings['height']),colorSpace=settings['color_space'])
    library=ET.SubElement(root,'library',colorProcessing='wide-hdr' if 'PQ' in settings['color_space'] or 'HLG' in settings['color_space'] else 'wide' if '2020' in settings['color_space'] else 'standard')
    sequence=ET.SubElement(ET.SubElement(ET.SubElement(library,'event',name='ClipComb Pro'),
                                      'project',name=name or payload['project']+' selects'),'sequence',
                           format='timeline-format',tcStart='0s',tcFormat='NDF',duration='0s')
    spine=ET.SubElement(sequence,'spine');position=0;count=0;global_marks=[]
    # Final Cut represents project-level annotations on a primary storyline
    # gap. Connected clips keep their own source clocks and audio children.
    parent=ET.SubElement(spine,'gap',name='Timeline bookmarks',start='0s',offset='0s',duration='0s') if timeline_markers else spine
    for ci,clip in enumerate(clips):
        m=clip['media'];sfps=rate(m['fps']);source_duration=Fraction(frame(m['duration'],sfps),1)/sfps
        fid=f'format-{ci}';aid=f'asset-{ci}'
        source_format=ET.SubElement(resources,'format',id=fid,name='FFVideoFormatRateUndefined',frameDuration=seconds(1/sfps),width=str(m.get('width',1920)),height=str(m.get('height',1080)))
        if color:=source_color(m):source_format.set('colorSpace',color)
        asset=ET.SubElement(resources,'asset',id=aid,name=Path(clip['path']).name,src=Path(clip['path']).as_uri(),start='0s',
                      duration=seconds(source_duration),format=fid,hasVideo='1',hasAudio='1' if m['audio'] else '0')
        if m['audio']:
            asset.set('audioSources',str(len(m['audio'])));asset.set('audioChannels',str(sum(int(t['channels']) for t in m['audio'])))
            if m['audio'][0].get('sample_rate'):asset.set('audioRate',str(m['audio'][0]['sample_rate']))
        for r in clip['ranges']:
            a,b=frame(r['start'],sfps),frame(r['end'],sfps);length=max(1,frame(Fraction(b-a)/sfps,fps))
            # A composite AV clip keeps every component together. Its children
            # span the full original, so extending the parent also reveals the
            # original audio beyond the exported mark rather than silence.
            node=ET.SubElement(parent,'clip',name=Path(clip['path']).name,start=seconds(Fraction(a)/sfps),
                               offset=seconds(Fraction(position)/fps),duration=seconds(Fraction(length)/fps),format=fid)
            if timeline_markers:node.set('lane','1')
            ET.SubElement(node,'video',ref=aid,start='0s',offset='0s',duration=seconds(source_duration))
            for i,t in enumerate(m['audio']):
                setting=clip.get('mix',[])[i] if i<len(clip.get('mix',[])) else {'enabled':True,'volume':100}
                audio=ET.SubElement(node,'audio',ref=aid,name=t.get('title') or f'Track {i+1}',start='0s',
                                    offset='0s',duration=seconds(source_duration),lane=str(-i-1),
                                    enabled='1',role=f'dialogue.cr_track_{i+1}',srcID=str(i+1),srcCh=','.join(str(j+1) for j in range(int(t['channels']))))
                if apply_mix:
                    db=20*math.log10(max(.00001,setting['volume']/100)) if setting['enabled'] else -100
                    ET.SubElement(audio,'adjust-volume',amount=f'{db:.8f}dB')
            for marker in export_marker_rows(clip,a,b,sfps,fix_bookmarks,target_fps=fps):
                if timeline_markers:
                    at,_=marker_timing(marker,sfps,fps,local=True)
                    global_marks.append((position+at,marker,fcpxml_marker_note(marker,sfps)))
                else:ET.SubElement(node,'marker',start=seconds(Fraction(marker['frame'])/sfps),
                                   duration=seconds(1/sfps),value=marker['name'],note=fcpxml_marker_note(marker,sfps))
            count+=1;position+=length
    if timeline_markers:
        parent.set('duration',seconds(Fraction(position)/fps))
        for at,marker,note in global_marks:
            ET.SubElement(parent,'marker',start=seconds(Fraction(at)/fps),duration=seconds(1/fps),value=marker['name'],note=note)
    sequence.set('duration',seconds(Fraction(position)/fps));ET.indent(root)
    target=Path(path);tmp=target.with_suffix('.writing');tmp.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'+ET.tostring(root,encoding='utf-8'));tmp.replace(target)
    return {'path':str(target),'moments':count,'frames':position,'fps':str(fps)}
