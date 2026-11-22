# SPDX-License-Identifier: GPL-3.0-or-later
"""Existing Studio edits survive bookmark sync, optional relinking and failures."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import file_identity,Project
from review_folders import configure,names
from review_resolve import append,prepare
from review_export import timeline_defaults,write_fcpxml
from review_interchange import write_resolve_otio,write_premiere_xml
from review_kdenlive import write_kdenlive


class Markers:
    def __init__(self,ident):self.ident=ident;self.markers={};self.fail_next=False
    def GetUniqueId(self):return self.ident
    def GetMarkers(self):return copy.deepcopy(self.markers)
    def AddMarker(self,at,color,name,note,duration,custom=''):
        if self.fail_next:self.fail_next=False;return False
        if at in self.markers:return False
        self.markers[at]=dict(color=color,name=name,note=note,duration=duration,customData=custom);return True
    def DeleteMarkerAtFrame(self,at):return self.markers.pop(at,None) is not None


class Source:
    def __init__(self,path):self.path=path
    def GetUniqueId(self):return 'source'
    def GetAudioMapping(self):return '{"track_mapping":{}}'
    def GetClipProperty(self,key):return self.path if key=='File Path' else '30'


class Item(Markers):
    def __init__(self,info,number):
        super().__init__('item'+str(number));self.info=info;self.speed=100
    def GetMediaPoolItem(self):return self.info['mediaPoolItem']
    def GetStart(self):return self.info['recordFrame']
    def GetEnd(self):return self.GetStart()+self.GetDuration()
    def GetDuration(self):return self.GetSourceEndFrame()-self.GetSourceStartFrame()
    def GetSourceStartFrame(self):return self.info['startFrame']
    def GetSourceEndFrame(self):return self.info['endFrame']
    def GetSpeed(self):return {'Percentage':self.speed}


class Timeline(Markers):
    def __init__(self):super().__init__('timeline');self.items=[]
    def GetName(self):return 'Selects'
    def GetEndFrame(self):return max((i.GetEnd() for i in self.items),default=0)
    def GetStartFrame(self):return 0
    def GetSetting(self,key):return '30'
    def GetTrackCount(self,kind):return 1 if kind=='video' else 0
    def GetIsTrackLocked(self,*args):return False
    def GetIsTrackEnabled(self,*args):return True
    def GetItemListInTrack(self,kind,index):return list(self.items) if kind=='video' else []
    def DeleteClips(self,items,ripple):self.items=[i for i in self.items if i not in items];return True


class Environment:
    def __init__(self,folder):
        root=Path(folder);source=root/'Unused/source.mp4';source.parent.mkdir();source.write_bytes(b'original')
        self.source=Source(str(source));self.timeline=Timeline();self.imports=0;self.relinks=0;self.saves=0
        self.pool=SimpleNamespace(GetCurrentFolder=lambda:None,ImportMedia=self.import_media,AppendToTimeline=self.append_items,RelinkClips=self.relink)
        project=SimpleNamespace(GetUniqueId=lambda:'project',GetName=lambda:'Disposable',GetMediaPool=lambda:self.pool,
            GetTimelineCount=lambda:1,GetTimelineByIndex=lambda i:self.timeline,GetCurrentTimeline=lambda:self.timeline,SetCurrentTimeline=lambda t:True)
        self.manager=SimpleNamespace(GetCurrentProject=lambda:project,SaveProject=self.save)
        self.resolve=SimpleNamespace(GetProjectManager=lambda:self.manager)
        self.clip=dict(id='clip',path=str(source),identity=file_identity(source),category='Used',media=dict(fps=30,duration=10,width=1920,height=1080,audio=[]),
            ranges=[dict(start=1,end=3)],markers=[dict(id='m1',time=1.5,name='First',note='',color_slot=0)])
        self.request=dict(payload=dict(schema=1,time_unit='source_seconds',project='QA',root=str(root),managed_folders=['Unused','Used','Test1'],clips=[self.clip]),
            project_id='project',timeline_id='timeline',expected_end=0,skip_existing=False)
    def import_media(self,paths):self.imports+=1;return [self.source]
    def append_items(self,infos):
        item=Item(infos[0],len(self.timeline.items)+1);self.timeline.items.append(item);return [item]
    def relink(self,clips,folder):
        self.relinks+=1
        for clip in clips:clip.path=str(Path(folder)/Path(clip.path).name)
        return True
    def save(self):self.saves+=1;return True
    def initial(self):
        result=append(self.resolve,self.request)
        self.request.update(expected_end=self.timeline.GetEndFrame(),skip_existing=True,existing_imports=result['imports'])
        return self.timeline.items[0]
    def move(self):
        old=Path(self.clip['path']);new=old.parents[1]/'Test1'/old.name;new.parent.mkdir();old.rename(new);self.clip['path']=str(new)
    def prepared(self):
        result=prepare(self.resolve,self.request);self.request['plan_token']=result['plan_token'];return result


class StudioUpdateTests(unittest.TestCase):
    def test_saved_moves_and_folder_renames_prove_old_locations(self):
        with tempfile.TemporaryDirectory() as folder:
            e=Environment(folder);e.initial();e.request['existing_imports']=[]
            project=Project(folder);clip=project.data['clips'][0]
            clip.update(id='clip',media=e.clip['media'],ranges=e.clip['ranges'],markers=e.clip['markers'],decision='Used');project.save()
            configure(project,dict(names(project),Used='Selected clips'))
            manifest,_=project.export_ranges();e.request['payload']=json.loads(manifest.read_text())
            move=e.prepared()['moved_sources'][0]
            self.assertEqual(move['old'],e.source.path)
            self.assertEqual(Path(move['new']).parent.name,'Selected clips')
    def test_similar_names_alone_are_not_proof_a_source_moved(self):
        with tempfile.TemporaryDirectory() as folder:
            e=Environment(folder);e.initial();e.move();e.request['existing_imports']=[]
            self.assertEqual(e.prepared()['moved_sources'],[])

    def test_new_edited_and_removed_bookmarks_sync_without_duplicate_footage(self):
        with tempfile.TemporaryDirectory() as folder:
            e=Environment(folder);item=e.initial();item.AddMarker(70,'Red','Editor note','Keep',1,'editor')
            e.clip['markers'][0]['name']='Renamed';e.clip['markers'].append(dict(id='m2',time=2,name='New',color_slot=2))
            e.prepared();result=append(e.resolve,e.request)
            self.assertEqual((result['moments'],result['skipped'],e.imports,len(e.timeline.items)),(0,1,1,1))
            self.assertEqual(item.GetMarkers()[45]['name'],'Renamed');self.assertEqual(item.GetMarkers()[60]['name'],'New')
            self.assertEqual(item.GetMarkers()[70]['customData'],'editor')
            e.clip['markers']=[];e.prepared();append(e.resolve,e.request)
            self.assertEqual(list(item.GetMarkers()),[70])

    def test_prepare_is_read_only_and_repair_or_decline_does_not_duplicate(self):
        for repair in (False,True):
            with self.subTest(repair=repair),tempfile.TemporaryDirectory() as folder:
                e=Environment(folder);item=e.initial();e.move();saves=e.saves;before=item.GetMarkers();old=e.source.path
                result=e.prepared();self.assertEqual(len(result['moved_sources']),1)
                self.assertEqual((e.saves,e.relinks,item.GetMarkers()),(saves,0,before))
                e.clip['markers'].append(dict(id='m2',time=2,name='New',color_slot=2));e.prepared()
                e.request['repair_links']=repair;result=append(e.resolve,e.request)
                self.assertEqual((result['moments'],e.imports,len(e.timeline.items)),(0,1,1))
                self.assertEqual(e.relinks,int(repair));self.assertEqual(e.source.path,e.clip['path'] if repair else old)

    def test_changed_marks_do_not_rewrite_existing_bookmarks(self):
        with tempfile.TemporaryDirectory() as folder:
            e=Environment(folder);item=e.initial();before=item.GetMarkers()
            e.clip['ranges'][0]['end']=2.5;e.clip['markers'][0]['name']='Changed'
            e.prepared();result=append(e.resolve,e.request)
            self.assertEqual(result['moments'],0);self.assertEqual(item.GetMarkers(),before)

    def test_retimed_existing_clip_is_not_updated(self):
        with tempfile.TemporaryDirectory() as folder:
            e=Environment(folder);item=e.initial();item.speed=50;before=item.GetMarkers();e.clip['markers'][0]['name']='Changed'
            e.prepared();append(e.resolve,e.request);self.assertEqual(item.GetMarkers(),before)

    def test_editor_marker_collision_and_stale_confirmation_preserve_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            e=Environment(folder);item=e.initial();e.prepared();before=item.GetMarkers()
            item.AddMarker(60,'Red','Editor note','',1,'editor')
            with self.assertRaisesRegex(ValueError,'changed'):append(e.resolve,e.request)
            e.clip['markers'].append(dict(id='m2',time=2,name='Conflict',color_slot=0));saves=e.saves
            with self.assertRaisesRegex(ValueError,'editor-created'):prepare(e.resolve,e.request)
            self.assertEqual(e.saves,saves);self.assertEqual(item.GetMarkers()[45],before[45])

    def test_failed_bookmark_write_restores_previous_bookmarks(self):
        with tempfile.TemporaryDirectory() as folder:
            e=Environment(folder);item=e.initial();before=item.GetMarkers();e.clip['markers'][0]['name']='Updated';e.prepared();item.fail_next=True
            with self.assertRaisesRegex(RuntimeError,'bookmark'):append(e.resolve,e.request)
            self.assertEqual(item.GetMarkers(),before);self.assertEqual(len(e.timeline.items),1)

    def test_timeline_bookmarks_follow_existing_item_position(self):
        with tempfile.TemporaryDirectory() as folder:
            e=Environment(folder);item=e.initial();e.request['timeline_markers']=True;item.info['recordFrame']=300;e.request['expected_end']=360
            e.prepared();append(e.resolve,e.request)
            self.assertFalse(item.GetMarkers());self.assertEqual(e.timeline.GetMarkers()[315]['name'],'First')


class ExportMaximumTests(unittest.TestCase):
    def test_independent_maxima_and_manual_fps_override(self):
        clips=[dict(media=dict(fps=120,width=2560,height=1440)),dict(media=dict(fps=60,width=3840,height=2160))]
        self.assertEqual(timeline_defaults(clips)['fps'],120)
        self.assertEqual((timeline_defaults(clips)['width'],timeline_defaults(clips)['height']),(3840,2160))
        self.assertEqual(timeline_defaults(clips,24)['fps'],24)
    def test_all_writers_use_only_exported_clips_and_preserve_source_clocks(self):
        import opentimelineio as ot
        with tempfile.TemporaryDirectory() as folder:
            e=Environment(folder);first=copy.deepcopy(e.clip);first['media'].update(fps=120,width=2560,height=1440)
            second=copy.deepcopy(e.clip);second['media'].update(fps=60,width=3840,height=2160,color_primaries='bt2020',color_transfer='smpte2084')
            excluded=copy.deepcopy(e.clip);excluded.update(category='Deleted');excluded['media'].update(fps=240,width=7680,height=4320)
            data=dict(e.request['payload'],clips=[first,second,excluded],export_folders=['Used'])
            for writer,ext in ((write_fcpxml,'fcpxml'),(write_premiere_xml,'xml'),(write_kdenlive,'kdenlive'),(write_resolve_otio,'otio')):
                path=Path(folder)/('export.'+ext);result=writer(data,path);self.assertEqual(result['fps'],'120')
                if ext=='otio':
                    timeline=ot.adapters.read_from_file(str(path));meta=timeline.metadata['clip_review'];self.assertEqual((meta['width'],meta['height']),(3840,2160))
                    self.assertEqual([c.source_range.start_time.rate for c in timeline.tracks[0]],[120,60])
                else:
                    tree=ET.parse(path)
                    node=tree.find('.//format[@id="timeline-format"]') if ext=='fcpxml' else tree.find('.//profile') if ext=='kdenlive' else tree.find('.//sequence/media/video/format/samplecharacteristics')
                    dims=(node.get('width'),node.get('height')) if ext!='xml' else (node.findtext('width'),node.findtext('height'))
                    self.assertEqual(dims,('3840','2160'))
                    if ext=='fcpxml':self.assertIn('PQ',node.get('colorSpace'));self.assertEqual(tree.find('.//library').get('colorProcessing'),'wide-hdr')


if __name__=='__main__':unittest.main()
