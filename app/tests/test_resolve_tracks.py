# SPDX-License-Identifier: GPL-3.0-or-later
"""Track reuse and rollback against stateful Resolve API doubles, no user media."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_resolve import append,choose_tracks


class Item:
    serial=0
    def __init__(self,start,end):
        Item.serial+=1;self.ident=f'item-{Item.serial}';self.start,self.end=start,end
    def GetUniqueId(self):return self.ident
    def GetStart(self):return self.start
    def GetEnd(self):return self.end
    def GetDuration(self):return self.end-self.start
    def GetSourceAudioChannelMapping(self):return '{"track_mapping":{"1":{"mute":false}}}'
    def SetProperties(self,values):return True


class Timeline:
    def __init__(self,video=1,audio=6):
        self.formats={'video':[None]*video,'audio':['stereo']*audio}
        self.items={(kind,i+1):[Item(0,100)] for kind,formats in self.formats.items() for i in range(len(formats))}
        self.added=[];self.deleted=[];self.locked=set();self.disabled=set();self.fail_link=False
    def GetUniqueId(self):return 'timeline'
    def GetName(self):return 'Test selects'
    def GetEndFrame(self):return max((item.end for items in self.items.values() for item in items),default=0)
    def GetStartFrame(self):return 0
    def GetSetting(self,key):return '30'
    def GetTrackCount(self,kind):return len(self.formats[kind])
    def GetIsTrackLocked(self,kind,index):return (kind,index) in self.locked
    def GetIsTrackEnabled(self,kind,index):return (kind,index) not in self.disabled
    def GetTrackSubType(self,kind,index):return self.formats[kind][index-1]
    def GetItemListInTrack(self,kind,index):return list(self.items[kind,index])
    def AddTrack(self,kind,subtype=None):
        self.formats[kind].append(subtype);index=len(self.formats[kind]);self.items[kind,index]=[];self.added.append((kind,index));return True
    def DeleteTrack(self,kind,index):
        assert not self.items[kind,index] and index==len(self.formats[kind])
        self.formats[kind].pop();del self.items[kind,index];return True
    def DeleteClips(self,items,ripple):
        assert not ripple
        self.deleted.extend(item.GetUniqueId() for item in items)
        for key in self.items:self.items[key]=[item for item in self.items[key] if item not in items]
        return True
    def SetClipsLinked(self,items,linked):return not self.fail_link
    def ids(self):return {item.GetUniqueId() for items in self.items.values() for item in items}


class Source:
    def GetAudioMapping(self):
        return json.dumps({'track_mapping':{str(i+1):dict(channel_idx=[2*i+1,2*i+2]) for i in range(6)}})
    def GetClipProperty(self,key):return '30'


class Pool:
    def __init__(self,timeline):self.timeline=timeline;self.calls=[];self.partial_failure=False
    def GetCurrentFolder(self):return None
    def ImportMedia(self,paths):return [Source()]
    def AppendToTimeline(self,infos):
        info=infos[0];self.calls.append(info)
        kind='video' if info['mediaType']==1 else 'audio';count=1 if kind=='video' else 6;items=[]
        for i in range(count):
            item=Item(info['recordFrame'],info['recordFrame']+info['endFrame']-info['startFrame'])
            self.timeline.items[kind,info['trackIndex']+i].append(item);items.append(item)
            if kind=='audio' and self.partial_failure and i==2:raise RuntimeError('Injected partial audio failure')
        return items


def environment(folder,timeline):
    source=Path(folder)/'fixture.mp4';source.touch();pool=Pool(timeline)
    project=SimpleNamespace(GetUniqueId=lambda:'project',GetName=lambda:'Test project',GetMediaPool=lambda:pool,
        GetTimelineCount=lambda:1,GetTimelineByIndex=lambda i:timeline,GetCurrentTimeline=lambda:timeline,
        SetCurrentTimeline=lambda target:True)
    manager=SimpleNamespace(GetCurrentProject=lambda:project,SaveProject=lambda:True)
    resolve=SimpleNamespace(GetProjectManager=lambda:manager)
    clip=dict(path=str(source),media=dict(fps=30,duration=10,audio=[dict(channels=2) for _ in range(6)]),
              ranges=[dict(start=1,end=3)],mix=[dict(enabled=True,volume=100) for _ in range(6)])
    request=dict(payload=dict(schema=1,time_unit='source_seconds',clips=[clip]),project_id='project',
                 timeline_id='timeline',expected_end=timeline.GetEndFrame(),skip_existing=False)
    return resolve,pool,request


class ResolveTrackTests(unittest.TestCase):
    def test_repeated_import_reuses_one_video_and_six_audio_tracks(self):
        with tempfile.TemporaryDirectory() as folder:
            timeline=Timeline();original=timeline.ids();resolve,pool,request=environment(folder,timeline)
            for _ in range(2):
                request['expected_end']=timeline.GetEndFrame();result=append(resolve,request)
                self.assertEqual(result['tracks_added'],dict(video=0,audio=0))
            self.assertEqual(timeline.added,[]);self.assertEqual(timeline.GetTrackCount('video'),1);self.assertEqual(timeline.GetTrackCount('audio'),6)
            self.assertTrue(original<=timeline.ids());self.assertEqual(timeline.deleted,[])
            self.assertEqual([c['trackIndex'] for c in pool.calls],[1,1,1,1])
            self.assertTrue(all(len(items)==3 for items in timeline.items.values()))

    def test_only_missing_tracks_are_added(self):
        with tempfile.TemporaryDirectory() as folder:
            timeline=Timeline(video=0,audio=2);resolve,_,request=environment(folder,timeline)
            result=append(resolve,request)
            self.assertEqual(result['tracks_added'],dict(video=1,audio=4))
            request['expected_end']=timeline.GetEndFrame();second=append(resolve,request)
            self.assertEqual(second['tracks_added'],dict(video=0,audio=0))

    def test_compatible_block_and_locked_tracks_are_respected(self):
        timeline=Timeline(audio=7);timeline.formats['audio'][0]='mono'
        self.assertEqual(choose_tracks(timeline,dict(video=1,audio=7),[2]*6),(1,2))
        timeline.formats['audio'][0]='stereo';timeline.locked.add(('audio',1))
        timeline.disabled.add(('video',1))
        self.assertEqual(choose_tracks(timeline,dict(video=1,audio=7),[2]*6),(2,2))

    def test_failure_rolls_back_only_new_clips_on_reused_tracks(self):
        with tempfile.TemporaryDirectory() as folder:
            timeline=Timeline();original=timeline.ids();resolve,_,request=environment(folder,timeline)
            timeline.fail_link=True
            with self.assertRaisesRegex(RuntimeError,'link'):append(resolve,request)
            self.assertEqual(timeline.ids(),original);self.assertTrue(original.isdisjoint(timeline.deleted))
            self.assertEqual(len(timeline.deleted),7);self.assertEqual(timeline.added,[])

    def test_partially_returned_audio_is_removed_without_touching_existing_clips(self):
        with tempfile.TemporaryDirectory() as folder:
            timeline=Timeline();original=timeline.ids();resolve,pool,request=environment(folder,timeline)
            pool.partial_failure=True
            with self.assertRaisesRegex(RuntimeError,'partial audio'):append(resolve,request)
            self.assertEqual(timeline.ids(),original);self.assertTrue(original.isdisjoint(timeline.deleted))
            self.assertEqual(len(timeline.deleted),4)

    def test_failed_import_removes_its_new_empty_tracks(self):
        with tempfile.TemporaryDirectory() as folder:
            timeline=Timeline(video=0,audio=2);original=timeline.ids();resolve,pool,request=environment(folder,timeline)
            pool.partial_failure=True
            with self.assertRaises(RuntimeError):append(resolve,request)
            self.assertEqual(timeline.ids(),original);self.assertEqual(timeline.GetTrackCount('video'),0);self.assertEqual(timeline.GetTrackCount('audio'),2)


if __name__=='__main__':unittest.main()
