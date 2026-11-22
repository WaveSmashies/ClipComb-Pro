# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only Studio reconciliation and scoped, reversible bookmark updates."""
from collections import defaultdict
import hashlib,json,os
from pathlib import Path
from review_export import frame,rate,marker_rows,marker_timing


def path_key(path):return os.path.normcase(os.path.normpath(str(path)))


def media_id(media):return media.GetUniqueId()


def ranges(clip):
    return sorted([frame(r['start'],clip['media']['fps']),frame(r['end'],clip['media']['fps'])] for r in clip['ranges'])


def receipt(clip,item,media,signature=None):
    return dict(clip_id=clip['id'],identity=clip.get('identity'),media_id=media_id(media),item_id=item.GetUniqueId(),
                path=media.GetClipProperty('File Path'),a=item.GetSourceStartFrame(),b=item.GetSourceEndFrame(),
                ranges=signature if signature is not None else ranges(clip))


def tag(clip,item,marker):return 'clipcomb:v2:'+str(clip.get('id',clip['path']))+':'+str(item.GetUniqueId())+':'+marker['id']


def plan(clips,payload,target,records=()):
    rows=[];seen={c.get('id',c['path']):[] for c in clips};matches=[];moves={};imports=[]
    by_path=defaultdict(list);by_old_path=defaultdict(list);by_id={};saved_by_media=defaultdict(list)
    signatures={c.get('id',c['path']):ranges(c) for c in clips}
    for clip in clips:
        by_path[path_key(clip['path'])].append(clip)
        if clip.get('id'):by_id[clip['id']]=clip
        for old in clip.get('studio_source_moves',[]):by_old_path[path_key(old)].append(clip)
    for record in records:
        if record.get('media_id'):saved_by_media[record['media_id']].append(record)
    for index in range(1,target.GetTrackCount('video')+1):
        for item in target.GetItemListInTrack('video',index) or []:
            media=item.GetMediaPoolItem()
            if not media:continue
            old=media.GetClipProperty('File Path')
            if not old:continue
            ident=media_id(media);saved=saved_by_media[ident];old_key=path_key(old)
            recorded_ids={r['clip_id'] for r in saved if r.get('clip_id') in by_id and r.get('identity') and r['identity']==by_id[r['clip_id']].get('identity')}
            candidates=by_path[old_key] or [by_id[cid] for cid in recorded_ids] or by_old_path[old_key]
            if not candidates and not Path(old).exists():
                # Older builds wrote the exact source path and ClipComb ID to
                # the export manifest, but did not record Resolve's media ID.
                candidates=[by_id[cid] for cid in dict.fromkeys(payload.get('previous_sources',{}).get(old_key,[])) if cid in by_id]
            if len(candidates)!=1:continue
            clip=candidates[0];a,b=item.GetSourceStartFrame(),item.GetSourceEndFrame()
            # A replaced file is not a relocated original, even if it has the
            # same name. Never redirect an online, different source.
            if path_key(old)!=path_key(clip['path']) and Path(old).is_file():
                stat=Path(old).stat()
                if clip.get('identity')!={'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}:continue
            seen[clip.get('id',clip['path'])].append((a,b))
            previous=next((r for r in saved if r.get('item_id')==item.GetUniqueId() and r.get('clip_id')==clip.get('id')),None)
            rows.append((clip,item,media,a,b,previous))
            if path_key(old)!=path_key(clip['path']) and not Path(old).exists():
                if Path(old).name.casefold()!=Path(clip['path']).name.casefold():continue
                stat=Path(clip['path']).stat()
                if clip.get('identity')!={'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}:raise ValueError('A moved source changed on disk. Rescan in ClipComb Pro before trying to relink it.')
                move=dict(media_id=ident,old=old,new=clip['path'])
                if ident in moves and path_key(moves[ident]['new'])!=path_key(clip['path']):raise ValueError('A Resolve source matches more than one managed clip. No links were changed.')
                moves[ident]=move
    for clip,item,media,a,b,previous in rows:
        signature=previous.get('ranges') if previous else sorted([list(r) for r in set(seen[clip.get('id',clip['path'])])])
        if clip.get('id'):imports.append(receipt(clip,item,media,signature))
        current_signature=signatures[clip.get('id',clip['path'])]
        exact=[a,b] in current_signature
        expected=frame((b-a)/float(rate(clip['media']['fps'])),target.GetSetting('timelineFrameRate'))
        speed=item.GetSpeed() if callable(getattr(item,'GetSpeed',None)) else None
        unretimed=not speed or float(speed.get('Percentage',100))==100
        if clip.get('id') and exact and signature==current_signature and abs(item.GetDuration()-expected)<=1 and unretimed and (not previous or previous.get('identity')==clip.get('identity')):
            matches.append((clip,item,a,b))
    snapshot=[(item.GetUniqueId(),media_id(media),media.GetClipProperty('File Path'),a,b,item.GetStart(),item.GetDuration(),item.GetMarkers()) for clip,item,media,a,b,previous in rows]
    snapshot.extend((target.GetMarkers(),target.GetSetting('timelineFrameRate'),list(moves.values()),[item.GetUniqueId() for _,item,_,_ in matches]))
    token=hashlib.sha256(json.dumps(snapshot,sort_keys=True,default=str).encode()).hexdigest()
    return dict(seen=seen,matches=matches,moves=list(moves.values()),imports=imports,rows=rows,token=token)


def marker_operations(plan,target,timeline_marks):
    """Preflight every collision before changing any marker or media link."""
    groups={};tfps=rate(target.GetSetting('timelineFrameRate'))
    def group(owner):return groups.setdefault(owner.GetUniqueId(),dict(owner=owner,desired={},prefixes=set(),legacy=defaultdict(list)))
    for clip,item,a,b in plan['matches']:
        prefix='clipcomb:v2:'+clip['id']+':'+item.GetUniqueId()+':'
        local=group(item);global_=group(target)
        for g in (local,global_):g['prefixes'].add(prefix)
        for marker in marker_rows(clip,a,b,clip['media']['fps']):
            legacy='clipcomb:'+marker['id'];start=item.GetStart()-target.GetStartFrame()
            local['legacy'][legacy].append((-float('inf'),float('inf')))
            global_['legacy'][legacy].append((start,start+item.GetDuration()))
            g=global_ if timeline_marks else local
            at,duration=marker_timing(marker,clip['media']['fps'],tfps,local=timeline_marks)
            if timeline_marks:at+=round(item.GetStart()-target.GetStartFrame())
            value=dict(color=marker['resolve_color'],name=marker['name'],note=marker['note'],duration=duration,customData=tag(clip,item,marker))
            if at in g['desired'] and g['desired'][at]!=value:raise ValueError('Two ClipComb bookmarks occupy the same timeline frame. Use clip bookmarks or move one bookmark before importing.')
            g['desired'][at]=value
    operations=[]
    for g in groups.values():
        current=g['owner'].GetMarkers() or {}
        def owned(at,value):
            custom=value.get('customData') or ''
            return any(a<=at<b for a,b in g['legacy'].get(custom,())) or any(custom.startswith(p) for p in g['prefixes'])
        previous={at:value for at,value in current.items() if owned(at,value)}
        for at,value in g['desired'].items():
            if at in current and at not in previous:raise ValueError('An editor-created bookmark occupies a ClipComb bookmark frame. Move one of the bookmarks and retry; nothing was changed.')
        touched={*previous,*g['desired']}
        def same(a,b):return all(a.get(k)==b.get(k) for k in ('color','name','note','duration','customData'))
        if any(at not in previous or not same(previous[at],value) for at,value in g['desired'].items()) or previous.keys()!=g['desired'].keys():
            operations.append(dict(owner=g['owner'],before={at:current[at] for at in touched if at in current},after=g['desired'],touched=touched))
    return operations


def add_marker(owner,at,value):
    return owner.AddMarker(at,value['color'],value.get('name',''),value.get('note',''),value.get('duration',1),value.get('customData',''))


def write_markers(operation,key):
    owner=operation['owner'];current=owner.GetMarkers() or {}
    for at in operation['touched']:
        if at in current and not owner.DeleteMarkerAtFrame(at):raise RuntimeError('Resolve could not update a ClipComb bookmark.')
    for at,value in operation[key].items():
        if not add_marker(owner,at,value):raise RuntimeError('Resolve could not attach a ClipComb bookmark.')


def repair_links(pool,plan):
    repaired=0
    sources={media_id(media):media for clip,item,media,a,b,previous in plan['rows']}
    for move in plan['moves']:
        media=sources[move['media_id']]
        if Path(move['old']).name.casefold()!=Path(move['new']).name.casefold():raise ValueError('Relinking requires the original filename. No source media was replaced.')
        ok=pool.RelinkClips([media],str(Path(move['new']).parent))
        if not ok or path_key(media.GetClipProperty('File Path'))!=path_key(move['new']):
            raise RuntimeError(f'Resolve could not repair {Path(move["new"]).name}. {repaired} successfully repaired links were retained; refresh and retry.')
        repaired+=1
    return repaired
