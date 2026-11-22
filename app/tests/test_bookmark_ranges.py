# SPDX-License-Identifier: GPL-3.0-or-later
"""Duration bookmarks remain the same annotations through editing and export."""
import copy
from fractions import Fraction
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_export import marker_rows,marker_timing,write_fcpxml,export_marker_rows
from review_interchange import write_otio,write_resolve_otio,write_premiere_xml
from review_file_trim import remap_annotations
from review_resolve import append


def payload(folder):
    source=Path(folder)/'source.mp4';source.touch()
    clip=dict(id='clip',path=str(source),category='Used',media=dict(fps=30,duration=10,audio=[]),
              ranges=[dict(start=2,end=5)],
              markers=[dict(id='span',time=1,duration=5,name='Same bookmark',note='Original note',color_slot=0),
                       dict(id='point',time=3,name='Point',note='',color_slot=3)])
    return dict(schema=1,time_unit='source_seconds',project='Bookmarks',clips=[clip])


class BookmarkRangeTests(unittest.TestCase):
    def test_compatibility_pairs_in_final_cut_and_kdenlive_exports(self):
        import opentimelineio as ot
        with tempfile.TemporaryDirectory() as folder:
            data=payload(folder);before=copy.deepcopy(data)
            for global_marks in (False,True):
                path=Path(folder)/'paired.fcpxml';write_fcpxml(data,path,fps=60,timeline_markers=global_marks,fix_bookmarks=True)
                markers=ET.parse(path).findall('.//marker')
                self.assertEqual([m.get('value') for m in markers],['1 Same bookmark','2 Same bookmark','Point'])
                self.assertEqual([m.get('note') for m in markers],['Original note','Original note',''])
                self.assertEqual(markers[0].get('start'),'0/1s' if global_marks else '2/1s')
                self.assertEqual(Fraction(markers[1].get('start')[:-1]),Fraction(89 if global_marks else 149,30))
                path=Path(folder)/'paired.otio';write_otio(data,path,fps=60,timeline_markers=global_marks,fix_bookmarks=True)
                timeline=ot.adapters.read_from_file(str(path))
                markers=timeline.tracks.markers if global_marks else timeline.tracks[0][0].markers
                self.assertEqual([m.name for m in markers],['1 Same bookmark','2 Same bookmark','Point'])
                self.assertEqual([m.marked_range.start_time.value for m in markers],[0,178,60] if global_marks else [0,89,30])
                self.assertEqual(markers[0].comment.splitlines(),['1 Same bookmark','Original note'])
                self.assertTrue(all(m.marked_range.duration.value==1 for m in markers))
                self.assertEqual(markers[0].metadata['clip_review']['range_id'],'span')
                self.assertEqual(markers[1].metadata['clip_review']['range_role'],'end')
            self.assertEqual(data,before)

    def test_compatibility_respects_cut_end_and_single_frame_sections(self):
        clip=dict(markers=[dict(id='span',time=0,duration=3,name='Something funny')])
        rows=export_marker_rows(clip,0,360,120,True,target_fps=30)
        self.assertEqual([m['name'] for m in rows],['1 Something funny','2 Something funny'])
        self.assertEqual(marker_timing(rows[1],120,30,local=True),(89,1))
        short=export_marker_rows(clip,0,1,120,True,target_fps=30)
        self.assertEqual([m['name'] for m in short],['1 / 2 Something funny'])
        self.assertEqual(short[0]['frame'],0)

    def test_resolve_export_keeps_native_span_even_if_compatibility_flag_is_passed(self):
        import opentimelineio as ot
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'resolve.otio';write_resolve_otio(payload(folder),path,fix_bookmarks=True)
            marker=ot.adapters.read_from_file(str(path)).tracks[0][0].markers[0]
            self.assertEqual(marker.name,'Same bookmark');self.assertEqual(marker.comment,'Original note')
            self.assertEqual(marker.marked_range.duration.value,90)

    def test_intersections_and_fractional_rate_boundaries(self):
        clip=dict(markers=[dict(id='span',time=1,duration=5),dict(id='point',time=2),dict(id='end',time=5)])
        rows=marker_rows(clip,60,150,30)
        self.assertEqual([(r['frame'],r['duration']) for r in rows],[(60,90),(60,1)])
        self.assertEqual(marker_timing(rows[0],30,60,local=True),(0,180))
        # Rounding the two boundaries together avoids a frame of excess length.
        self.assertEqual(marker_timing(dict(frame=1,local_frame=0,duration=1,is_range=True),30,24),(1,1))
        self.assertEqual(marker_timing(dict(frame=1,local_frame=0,duration=2,is_range=True),30,24),(1,1))

    def test_trim_remaps_intersections_and_gives_split_spans_unique_ids(self):
        original=dict(markers=[dict(id='span',time=1,duration=8,name='Range',note='Keep',color_slot=4)],ranges=[])
        before=copy.deepcopy(original)
        _,markers=remap_annotations(original,[(2,4,0),(6,8,2.1)])
        self.assertEqual([(m['time'],m['duration']) for m in markers],[(0,2),(2.1,2)])
        self.assertNotEqual(markers[0]['id'],markers[1]['id'])
        self.assertTrue(all(m['name']=='Range' and m['note']=='Keep' and m['color_slot']==4 for m in markers))
        self.assertEqual(original,before)

    def test_otio_and_premiere_keep_clip_and_timeline_spans(self):
        import opentimelineio as ot
        with tempfile.TemporaryDirectory() as folder:
            data=payload(folder)
            for global_marks in (False,True):
                for writer in (write_otio,write_resolve_otio):
                    path=Path(folder)/'markers.otio';writer(data,path,fps=60,timeline_markers=global_marks)
                    timeline=ot.adapters.read_from_file(str(path))
                    markers=timeline.tracks.markers if global_marks else timeline.tracks[0][0].markers
                    self.assertEqual(markers[0].name,'Same bookmark');self.assertEqual(markers[0].comment,'Original note')
                    self.assertEqual(markers[0].marked_range.start_time.value,0 if global_marks else 60)
                    self.assertEqual(markers[0].marked_range.duration.value,180 if global_marks else 90)
                    self.assertEqual(markers[1].marked_range.duration.value,1)
                path=Path(folder)/'markers.xml';write_premiere_xml(data,path,fps=60,timeline_markers=global_marks)
                root=ET.parse(path);marks=root.findall('.//sequence/marker' if global_marks else './/video/track/clipitem/marker')
                self.assertEqual(int(marks[0].findtext('out'))-int(marks[0].findtext('in')),180 if global_marks else 90)
                self.assertEqual(marks[0].findtext('comment'),'Original note')
                self.assertEqual(marks[1].findtext('out'),'-1')

    def test_final_cut_keeps_the_same_bookmark_with_range_in_note(self):
        with tempfile.TemporaryDirectory() as folder:
            for global_marks in (False,True):
                path=Path(folder)/'markers.fcpxml';write_fcpxml(payload(folder),path,fps=60,timeline_markers=global_marks)
                markers=ET.parse(path).findall('.//marker')
                self.assertEqual(markers[0].get('value'),'Same bookmark')
                self.assertIn('Original note',markers[0].get('note'))
                self.assertIn('00:02.000–00:05.000',markers[0].get('note'))
                self.assertEqual(markers[0].get('duration'),'1/60s' if global_marks else '1/30s')
                self.assertEqual(markers[1].get('note'),'')

    def test_resolve_api_receives_span_duration_for_clip_and_timeline(self):
        with tempfile.TemporaryDirectory() as folder:
            for global_marks in (False,True):
                resolve=MagicMock();project=resolve.GetProjectManager().GetCurrentProject();target=project.GetTimelineByIndex.return_value
                project.GetUniqueId.return_value='project';project.GetTimelineCount.return_value=1
                target.GetUniqueId.return_value='timeline';target.GetEndFrame.return_value=0
                target.GetTrackCount.return_value=0;target.GetStartFrame.return_value=0;target.GetSetting.return_value='60'
                target.GetMarkers.return_value={}
                mp=project.GetMediaPool();source=MagicMock();mp.ImportMedia.return_value=[source]
                source.GetAudioMapping.return_value='{"track_mapping":{}}';source.GetClipProperty.return_value='30'
                video=MagicMock();video.GetDuration.return_value=180;video.GetEnd.return_value=180
                video.GetUniqueId.return_value='imported-video'
                mp.AppendToTimeline.return_value=[video]
                request=dict(payload=payload(folder),project_id='project',timeline_id='timeline',expected_end=0,
                             skip_existing=False,timeline_markers=global_marks)
                append(resolve,request)
                calls=(target if global_marks else video).AddMarker.call_args_list
                self.assertEqual(calls[0].args[:5],(0 if global_marks else 120,'Blue','Same bookmark','Original note',180))
                self.assertTrue(calls[0].args[5].startswith('clipcomb:v2:'))
                self.assertTrue(calls[0].args[5].endswith(':imported-video:span'))
                self.assertEqual(calls[1].args[4],1)


if __name__=='__main__':unittest.main()
