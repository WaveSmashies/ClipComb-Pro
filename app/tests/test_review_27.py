# SPDX-License-Identifier: GPL-3.0-or-later
"""Exports retain complete original media and independently mapped source audio."""
import copy,hashlib,json,tempfile,unittest
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET
from unittest.mock import patch
import opentimelineio as ot
from review_export import write_fcpxml
from review_interchange import write_resolve_otio,write_premiere_xml,write_otio
from review_kdenlive import write_kdenlive

def payload(folder):
    source=Path(folder)/'Original source.mp4';source.write_bytes(b'original fixture bytes')
    clip=dict(path=str(source),category='Used',media=dict(fps=30,duration=12,width=320,height=180,audio=[dict(channels=c,title=f'Track {i+1}',stream_index=i+1) for i,c in enumerate((1,2,2))]),
              ranges=[dict(start=2,end=4),dict(start=8,end=9)],mix=[dict(enabled=True,volume=70),dict(enabled=False,volume=100),dict(enabled=True,volume=100)],markers=[])
    return dict(schema=1,time_unit='source_seconds',project='Source references',clips=[clip])

class OriginalSourceTests(unittest.TestCase):
    def test_resolve_otio_full_handles_and_embedded_stream_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            data=payload(folder);before=copy.deepcopy(data);source=Path(data['clips'][0]['path']);digest=hashlib.sha256(source.read_bytes()).digest()
            path=Path(folder)/'selects.otio';write_resolve_otio(data,path,decoder='must not run')
            timeline=ot.adapters.read_from_file(str(path))
            self.assertEqual(len(timeline.tracks),4)
            for track in timeline.tracks:
                self.assertEqual([c.source_range.start_time.to_seconds() for c in track],[2,8])
                self.assertEqual([c.duration().to_seconds() for c in track],[2,1])
                for clip in track:
                    self.assertEqual(Path(clip.media_reference.target_url),source)
                    self.assertEqual(clip.media_reference.available_range.duration.to_seconds(),12)
            for i,track in enumerate(timeline.tracks[1:]):
                for clip in track:
                    channels=clip.metadata['Resolve_OTIO']['Channels']
                    self.assertTrue(all(c['Source Track ID']==i for c in channels))
                    self.assertEqual([c['Source Channel ID'] for c in channels],list(range((1,2,2)[i])))
            self.assertEqual({p.name for p in Path(folder).iterdir()},{source.name,path.name})
            self.assertEqual(digest,hashlib.sha256(source.read_bytes()).digest());self.assertEqual(data,before)

    def test_xml_uses_one_original_file_and_source_time_for_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            data=payload(folder);source=Path(data['clips'][0]['path']);path=Path(folder)/'selects.xml'
            write_premiere_xml(data,path,decoder='must not run');tree=ET.parse(path)
            self.assertEqual(len(tree.findall('.//file/pathurl')),1)
            self.assertEqual(tree.findtext('.//file/pathurl').lower(),source.as_uri().replace('file:///','file://localhost/').lower())
            tracks=tree.findall('.//sequence/media/audio/track')
            self.assertEqual([int(t.findtext('clipitem/sourcetrack/trackindex')) for t in tracks],[1,2,3,4,5])
            for track in tracks:self.assertEqual([int(c.findtext('in')) for c in track.findall('clipitem')],[60,240])
            self.assertEqual(tree.findtext('.//file/media/audio/channelcount'),'5')
            self.assertFalse((Path(folder)/'clip-review-audio').exists())

    def test_final_cut_source_tracks_keep_full_media_and_no_implicit_extra_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            data=payload(folder);path=Path(folder)/'selects.fcpxml';write_fcpxml(data,path,decoder='must not run')
            tree=ET.parse(path);asset=tree.find('.//resources/asset')
            self.assertEqual(len(tree.findall('.//resources/asset')),1);self.assertEqual(asset.get('duration'),'12/1s')
            for clip in tree.findall('.//spine/clip'):
                self.assertIsNotNone(clip.find('video'))
                children=clip.findall('audio');self.assertEqual([c.get('srcID') for c in children],['1','2','3'])
                self.assertEqual([c.get('srcCh') for c in children],['1','1,2','1,2'])
                self.assertTrue(all(c.get('ref')==asset.get('id') and c.get('start')=='0s' and c.get('duration')=='12/1s' for c in children))
            self.assertFalse((Path(folder)/'clip-review-audio').exists())

    def test_kdenlive_distinct_streams_full_handles_linked_groups_and_gaps(self):
        with tempfile.TemporaryDirectory() as folder:
            data=payload(folder);other=copy.deepcopy(data['clips'][0]);other['media']['audio']=[];other['ranges']=[dict(start=5,end=6)]
            data['clips'].insert(0,other);before=copy.deepcopy(data);p=Path(folder)/'selects.kdenlive'
            write_kdenlive(data,p,decoder='must not run');tree=ET.parse(p);root=tree.getroot()
            props=lambda n:{x.get('name'):x.text for x in n.findall('property')};byid={x.get('id'):x for x in root}
            tracks=[x for x in root.findall('tractor') if props(x).get('kdenlive:audio_track')=='1']
            for i,track in enumerate(tracks):
                pl=byid[track.find('track').get('producer')];self.assertEqual(pl.find('blank').get('length'),'30')
                for entry in pl.findall('entry'):
                    source=props(byid[entry.get('producer')]);self.assertEqual(source['audio_index'],str(3-i));self.assertEqual(source['length'],'360')
                    bin_source=next(x for x in root.findall('chain') if props(x).get('kdenlive:id')==source['kdenlive:id'] and props(x).get('set.test_audio') is None)
                    self.assertEqual(source['kdenlive:control_uuid'],props(bin_source)['kdenlive:control_uuid'])
                self.assertEqual([e.get('in') for e in pl.findall('entry')],['60','240'])
            main=byid['main_bin'];self.assertEqual(len(main.findall('entry')),2)
            groups=[json.loads(v) for n in root.findall('tractor') for k,v in props(n).items() if k.endswith('.groups')][0]
            self.assertEqual([len(g['children']) for g in groups],[4,4])
            effects=tree.findall('.//entry/filter');self.assertEqual(len(effects),4)
            self.assertTrue(all(props(f).get('kdenlive_id')=='volume' and '=' in props(f)['level'] for f in effects))
            self.assertEqual(data,before);self.assertEqual({x.suffix for x in Path(folder).iterdir()},{'.mp4','.kdenlive'})

    def test_xml_source_clock_stays_independent_from_timeline_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            data=payload(folder);data['clips'][0]['media']['fps']=60;p=Path(folder)/'selects.xml'
            write_premiere_xml(data,p,fps=30);tree=ET.parse(p)
            video=tree.findall('.//video/track/clipitem');self.assertEqual([x.findtext('in') for x in video],['120','480'])
            self.assertEqual([x.findtext('end') for x in video],['60','90'])
            self.assertTrue(all(x.findtext('rate/timebase')=='60' for x in video))

if __name__=='__main__':unittest.main()
