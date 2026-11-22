# SPDX-License-Identifier: GPL-3.0-or-later
"""Verified stream-copy keep regions. Originals are never overwritten here."""
from dataclasses import dataclass
import bisect
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from review_overlap_audit import Clip, identity, probe, PACKET_TIMING, duration_tolerance
from review_cleanup_core import (archive_clip, hash_file, run_media, stream_labels,
                                 track_name_options, verify_labels, verify_slice, RESERVE_BYTES)


@dataclass
class TrimResult:
    folder: object
    paths: list
    intervals: list
    checksums: list
    source_checksum: str
    source_identity: tuple
    mappings: list
    details: list
    metadata: list


def cut_points(media):
    video=media.tracks[media.video]
    return sorted(set([0.,media.duration]+[round(t-media.start,6) for i in video.keyframes
                                            if 0 <= (t:=video.pts[i])-media.start < media.duration]))


def snap_keep(points,start,end):
    """Snap outward, so the displayed keep range includes the requested footage."""
    a=points[max(0,bisect.bisect_right(points,start+1e-6)-1)]
    b=points[min(len(points)-1,bisect.bisect_left(points,end-1e-6))]
    return a,b


def keep_intervals(ranges,points):
    result=[]
    for r in sorted(ranges,key=lambda r:r['start']):
        if not r.get('enabled',True):continue
        a,b=snap_keep(points,r['start'],r['end'])
        if b<=a:continue
        if result and a<=result[-1][1]+1e-6:result[-1]=(result[-1][0],max(b,result[-1][1]))
        else:result.append((a,b))
    if not result:raise ValueError('Mark at least one nonempty keep region in Trim file mode.')
    return result


def staged_clip(path,source):
    info=path.stat()
    return Clip(path,info.st_size,identity(info),source.capture_time,'verified trim')


def create_trim(source,work,ranges,tools,progress,join=True):
    source=Path(source).resolve();work=Path(work);work.mkdir(parents=True,exist_ok=True)
    original=archive_clip(source.parent,source.name)
    if source.suffix.lower() not in {'.mp4','.mov','.mkv','.ts'}:
        raise ValueError('Verified file trimming currently supports MP4, MOV, MKV and TS. Other formats can still be reviewed and exported to an editor.')
    ffmpeg,ffprobe=tools['ffmpeg'],tools['ffprobe']
    progress('Reading keyframes and all encoded streams…')
    media=probe(original,ffprobe,600);intervals=keep_intervals(ranges,cut_points(media))
    if intervals==[(0.,media.duration)]:raise ValueError('These keep regions retain the entire file. There is nothing to trim.')
    if shutil.disk_usage(work).free < original.size*(2 if join else 1)+RESERVE_BYTES:
        raise ValueError('The working drive needs enough free space for the verified copies.')
    checksum=hash_file(source);labels=stream_labels(source,ffprobe)
    folder=tempfile.TemporaryDirectory(prefix='trim-',dir=work)
    try:
        parts=[];outputs=[];details=[];mappings=[]
        video=media.tracks[media.video]
        for index,(a,b) in enumerate(intervals):
            progress(f'Copying and verifying keep region {index+1} of {len(intervals)}…')
            target=Path(folder.name)/f'part-{index:04}{source.suffix.lower()}'
            first=next((i for i in video.keyframes if abs(video.pts[i]-media.start-a)<.002),0)
            stop=len(video.hashes) if b>=media.duration-.002 else next(i for i in video.keyframes if abs(video.pts[i]-media.start-b)<.002)
            following=next((video.pts[i]-media.start for i in video.keyframes if i>first),media.duration)
            lead=max(0,video.pts[first]-video.dts[first]) if video.dts[first] is not None else 0
            # Container seek indexes may land on the preceding GOP (notably AV1).
            # Try bounded positions within this GOP; accept only exact packet proof.
            seeks=[0] if first==0 else [a+lead+.001,a+(following-a)*.5,a+(following-a)*.9]
            for attempt,seek_at in enumerate(seeks):
                target=Path(folder.name)/f'part-{index:04}-{attempt}{source.suffix.lower()}'
                seek=['-ss',f'{seek_at:.6f}'] if seek_at else []
                run_media([ffmpeg,'-hide_banner','-v','error','-xerror','-nostdin','-n',*seek,
                           '-protocol_whitelist','file','-i',str(source),*(['-frames:v',str(stop-first)] if b<media.duration-.002 else []),'-map','0','-map_metadata','0',
                           '-map_chapters','-1',*track_name_options(media,labels,source.suffix.lower()),
                           '-c','copy','-avoid_negative_ts','make_zero' if a>.001 else 'disabled',str(target)],timeout=1800)
                output=probe(staged_clip(target,original),ffprobe,600)
                try:_,tracks=verify_slice(media,output,media.start+a,media.start+b,[],require_coverage=False)
                except ValueError:
                    if attempt==len(seeks)-1:raise
                    target.unlink();continue
                break
            verify_labels(media,labels,stream_labels(target,ffprobe))
            # Mapping uses the verified packet PTS shift, including container priming.
            output_origin=output.tracks[output.video].pts[0]-output.start
            mappings.append([(a,b,output_origin)])
            details.append({'start':a,'end':b,'tracks':tracks,'video_origin':output_origin})
            parts.append(target);outputs.append(output)
        paths=parts
        if join and len(parts)>1:
            progress('Joining kept regions and checking every retained packet…')
            manifest=Path(folder.name)/'parts.ffconcat'
            manifest.write_text('ffconcat version 1.0\n'+''.join(f"file '{p.name}'\n" for p in parts),encoding='utf-8')
            target=Path(folder.name)/('joined'+source.suffix.lower())
            run_media([ffmpeg,'-hide_banner','-v','error','-xerror','-nostdin','-n','-f','concat','-safe','1','-auto_convert','0',
                       '-protocol_whitelist','file','-i',str(manifest),'-map','0','-map_metadata','0',
                       *track_name_options(media,labels,source.suffix.lower()),'-c','copy',str(target)],timeout=1800)
            joined=probe(staged_clip(target,original),ffprobe,600)
            if [t.signature for t in joined.tracks]!=[t.signature for t in media.tracks]:
                raise ValueError('The joined copy changed the stream configuration.')
            positions=[]
            for stream,new in enumerate(joined.tracks):
                cursor=0;stream_positions=[]
                for output in outputs:
                    old=output.tracks[stream];n=len(old.hashes)
                    if new.hashes[cursor:cursor+n]!=old.hashes:raise ValueError(f'Joined stream {stream+1} changed encoded packets.')
                    shift=new.pts[cursor]-old.pts[0]
                    tolerance=duration_tolerance(old,new)
                    for j in range(n):
                        k=cursor+j
                        boundary_duration=(j==n-1 and k+1<len(new.hashes) and new.dts[k] is not None
                                           and new.dts[k+1] is not None
                                           and abs(new.durations[k]-(new.dts[k+1]-new.dts[k]))<=tolerance)
                        if (abs(new.pts[k]-old.pts[j]-shift)>PACKET_TIMING
                            or abs(new.durations[k]-old.durations[j])>tolerance and not boundary_duration
                            or new.side_data.get(k)!=old.side_data.get(j)
                            or new.dts[k] is not None and old.dts[j] is not None
                            and abs(new.dts[k]-old.dts[j]-shift)>PACKET_TIMING):
                            raise ValueError(f'Timing or packet metadata changed in joined stream {stream+1}.')
                    stream_positions.append(new.pts[cursor]-joined.start)
                    cursor+=n
                if cursor!=len(new.hashes):raise ValueError('Unexpected packets in the joined copy.')
                positions.append(stream_positions)
            verify_labels(media,labels,stream_labels(target,ffprobe))
            gaps=[]
            for i in range(1,len(intervals)):
                gap=positions[media.video][i]-positions[media.video][i-1]-(intervals[i-1][1]-intervals[i-1][0])
                gaps.append(round(gap,6))
            details.append({'join_padding_seconds':gaps,
                            'note':'Encoded packets are unchanged. Container priming can add a short hold between kept sections.'})
            mappings=[[(a,b,positions[media.video][i]) for i,(a,b) in enumerate(intervals)]]
            paths=[target]
        for i,path in enumerate(paths):
            progress(f'Decoding output {i+1} of {len(paths)} to check for errors…')
            run_media([ffmpeg,'-hide_banner','-v','error','-xerror','-err_detect','explode','-nostdin',
                       '-protocol_whitelist','file','-i',str(path),'-map','0:v','-map','0:a?','-f','null','-'],timeout=3600)
        if identity(source.lstat())!=original.file_id or hash_file(source)!=checksum:
            raise ValueError('The original changed during verification. No copies were installed.')
        from review_core import probe_media
        metadata=[probe_media(path,ffprobe) for path in paths]
        return TrimResult(folder,paths,intervals,[hash_file(p) for p in paths],checksum,original.file_id,mappings,details,metadata)
    except BaseException:
        folder.cleanup();raise


def remap_annotations(source,mapping):
    from review_marker_ranges import duration as marker_duration
    ranges=[];markers=[]
    used_marker_ids=set()
    for a,b,base in mapping:
        for r in source.get('ranges',[]):
            start,end=max(a,r['start']),min(b,r['end'])
            if end>start:ranges.append(dict(r,id=uuid.uuid4().hex,start=start-a+base,end=end-a+base))
        for marker in source.get('markers',[]):
            span=marker_duration(marker)
            start,finish=max(a,marker['time']),min(b,marker['time']+span)
            if (span and finish>start) or (not span and a<=marker['time']<b):
                mapped=dict(marker,time=start-a+base)
                if span:mapped['duration']=finish-start
                if mapped.get('id') in used_marker_ids:mapped['id']=uuid.uuid4().hex
                used_marker_ids.add(mapped.get('id'));markers.append(mapped)
    return ranges,markers


def install_new_copies(project,source_clip,result):
    """Publish exclusive new files and a receipt; retain the full original."""
    source=project.checked(source_clip['path'])
    if identity(source.lstat())!=result.source_identity or hash_file(source)!=result.source_checksum:
        raise ValueError('The source changed after verification. Run Trim file again.')
    added=[];prior_ids={c['id'] for c in project.data['clips']};created=[]
    try:
        for index,(path,checksum,mapping) in enumerate(zip(result.paths,result.checksums,result.mappings)):
            if hash_file(path)!=checksum:raise ValueError('The staged copy changed after verification.')
            target=source.with_name(f'{source.stem} - trimmed {index+1}-{uuid.uuid4().hex[:6]}{source.suffix}')
            with target.open('xb') as out,path.open('rb') as inp:
                created.append(target);shutil.copyfileobj(inp,out,4*1024**2)
                out.flush();os.fsync(out.fileno())
            if hash_file(target)!=checksum:raise ValueError('The installed file failed its checksum check.')
            added.append((target,mapping,checksum))
        project.scan()
        for index,(target,mapping,checksum) in enumerate(added):
            clip=next(c for c in project.data['clips'] if c['path']==str(target.relative_to(project.root)))
            clip['ranges'],clip['markers']=remap_annotations(source_clip,mapping)
            clip['media']=result.metadata[index]
            for key in ('mix','audio_profile'): 
                if key in source_clip:clip[key]=copy.deepcopy(source_clip[key])
            clip['provenance']=[{'source_id':source_clip['id'],'source_path':source_clip['path'],
                                 'start':a,'end':b,'output_start':base} for a,b,base in mapping]
        receipt=project.metadata/f'clipcomb-trim-{uuid.uuid4().hex}.json'
        with receipt.open('x',encoding='utf-8') as file:
            json.dump({'source':source_clip['path'],'source_sha256':result.source_checksum,
                       'copies':[{'path':str(t.relative_to(project.root)),'sha256':s,'mapping':m} for t,m,s in added],
                       'verification':result.details},file,indent=2)
        project.dirty=True
        return [next(c for c in project.data['clips'] if c['path']==str(t.relative_to(project.root))) for t,_,_ in added]
    except BaseException:
        project.data['clips'][:]=[c for c in project.data['clips'] if c['id'] in prior_ids]
        for path in created:
            try:path.unlink()
            except OSError:pass
        raise


def map_project_merge(project,merge,receipt):
    from review_core import file_identity,atomic_json
    by_path={str(project.checked(c['path'])).casefold():c for c in project.data['clips']}
    target=by_path.get(str(merge.clips[0].path).casefold())
    if not target:return
    originals={};ranges=[];markers=[];seen=set();provenance=[]
    for i,(original,placement) in enumerate(zip(merge.clips,merge.track_placements)):
        clip=by_path.get(str(original.path).casefold())
        if not clip:continue
        originals[clip['id']]=copy.deepcopy(clip)
        base=merge.source_starts[i]+placement[merge.video_index]['shift_seconds']-merge.output_start
        duration=merge.source_durations[i]
        rr,mm=remap_annotations(clip,[(0,duration,base)]);ranges.extend(rr)
        for m in mm:
            key=(round(m['time'],4),round(m.get('duration',0),4),m['name'],m.get('note',''),m.get('color_slot',0))
            if key not in seen:markers.append(m);seen.add(key)
        provenance.append({'source_id':clip['id'],'source_path':clip['path'],'start':0,'end':duration,'output_start':base})
    target.update(ranges=ranges,markers=markers,provenance=provenance,media=None,
                  identity=file_identity(merge.clips[0].path),position=0)
    atomic_json(Path(receipt)/'clipcomb-annotations.json',{'originals':originals,'merged':copy.deepcopy(target)})
    project.dirty=True
