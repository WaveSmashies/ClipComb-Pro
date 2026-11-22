# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import sys
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_export import marker_rows,write_fcpxml
from review_interchange import write_premiere_xml,write_otio
from review_interchange import write_resolve_otio
from review_file_trim import snap_keep,keep_intervals,remap_annotations
from review_history import History


class MarkersTrimTests(unittest.TestCase):
    def test_snap_outward_and_combine(self):
        points=[0,2,4,6,8,10]
        self.assertEqual(snap_keep(points,2.2,3.8),(2,4))
        self.assertEqual(snap_keep(points,2,4),(2,4))
        self.assertEqual(keep_intervals([{'start':1,'end':3},{'start':3,'end':5}],points),[(0,6)])
        with self.assertRaises(ValueError):keep_intervals([],points)

    def test_mapping_intersections_and_markers(self):
        source={'ranges':[{'id':'r','start':3,'end':9,'enabled':True}],
                'markers':[{'id':str(i),'time':i,'name':str(i),'note':'test'} for i in (1,3,5,7,9)]}
        ranges,markers=remap_annotations(source,[(2,4,0),(6,8,2.1)])
        self.assertEqual([(r['start'],r['end']) for r in ranges],[(1,2),(2.1,4.1)])
        self.assertEqual([(m['name'],m['time']) for m in markers],[('3',1),('7',3.1)])
        self.assertEqual(source['ranges'][0]['start'],3)

    def test_history_markers_and_trim_remain_separate(self):
        clip={'id':'c','ranges':[],'markers':[],'trim_ranges':[]}
        history=History();history.watch(clip)
        clip['markers'].append({'id':'m','time':2,'name':'Hello','note':'Description'})
        history.record(clip,fields=('markers',))
        self.assertEqual(history.next_action()[1],'Add clip marker')
        self.assertEqual(history.take()[1],{'markers':[]})

    def test_marker_half_open_source_frames(self):
        clip={'markers':[{'time':i,'name':str(i)} for i in (1,2,3,4,float('nan'))]}
        result=marker_rows(clip,60,120,30)
        self.assertEqual([(m['frame'],m['local_frame']) for m in result],[(60,0),(90,30)])

    def test_all_interchange_formats_keep_clip_notes(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);source=folder/'source.mp4';source.write_bytes(b'fixture')
            clip={'id':'c','path':str(source),'category':'Used','media':{'fps':30,'duration':10,'audio':[], 'width':1280,'height':720},
                  'ranges':[{'id':'r','start':2,'end':5}],'markers':[{'id':'m','time':3,'name':'Find me','note':'Keep this note'}]}
            payload={'schema':1,'time_unit':'source_seconds','project':'Test','clips':[clip]}
            fcpx=folder/'selects.fcpxml';write_fcpxml(payload,fcpx)
            m=ET.parse(fcpx).find('.//clip/marker')
            self.assertEqual((m.get('start'),m.get('value'),m.get('note')),('3/1s','Find me','Keep this note'))
            xml=folder/'selects.xml';write_premiere_xml(payload,xml)
            m=ET.parse(xml).find('.//clipitem/marker')
            self.assertEqual((m.findtext('in'),m.findtext('comment')),('90','Keep this note'))
            otio=folder/'selects.otio';write_otio(payload,otio)
            import opentimelineio as ot
            timeline=ot.adapters.read_from_file(str(otio));marker=timeline.tracks[0][0].markers[0]
            self.assertEqual(marker.comment,'Keep this note')
            self.assertEqual(marker.marked_range.start_time.value,90)

    def test_timeline_placement_and_mixed_rate_color_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);source=folder/'source.mp4';source.write_bytes(b'fixture')
            clip={'id':'c','path':str(source),'category':'Used','media':{'fps':30,'duration':10,'audio':[]},
                  'ranges':[{'start':2,'end':5},{'start':6,'end':8}],
                  'markers':[{'id':'m','time':7,'name':'Orange slot','note':'Description','color_slot':3}]}
            payload={'schema':1,'time_unit':'source_seconds','project':'Test','clips':[clip]}
            rows=marker_rows(clip,180,240,30)
            self.assertEqual((rows[0]['resolve_color'],rows[0]['premiere_color']),('Yellow',3))
            path=folder/'timeline.otio';write_resolve_otio(payload,path,fps=60,timeline_markers=True)
            import opentimelineio as ot
            timeline=ot.adapters.read_from_file(str(path));marker=timeline.tracks.markers[0]
            self.assertEqual(marker.marked_range.start_time.value,240)
            self.assertEqual(marker.marked_range.start_time.rate,60)
            self.assertEqual(marker.metadata['clip_review']['color_slot'],3)
            self.assertFalse(timeline.tracks[0][1].markers)
            path=folder/'timeline.xml';write_premiere_xml(payload,path,fps=60,timeline_markers=True)
            root=ET.parse(path)
            self.assertEqual(root.findtext('.//sequence/marker/in'),'240')
            self.assertEqual(root.findtext('.//sequence/marker/pproColor'),'3')
            self.assertEqual(root.findtext('.//video/track/clipitem/in'),'60')
            self.assertFalse(root.findall('.//clipitem/marker'))
            path=folder/'timeline.fcpxml';write_fcpxml(payload,path,fps=60,timeline_markers=True)
            root=ET.parse(path);gap=root.find('.//spine/gap')
            self.assertEqual(gap.find('marker').get('start'),'4/1s')
            self.assertEqual(len(gap.findall('clip')),2)
            self.assertFalse(root.findall('.//clip/marker'))


if __name__=='__main__':unittest.main()
