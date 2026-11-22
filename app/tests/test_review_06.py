# SPDX-License-Identifier: GPL-3.0-or-later
import csv,json,shutil,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Settings,DEFAULT_KEYS
from review_overlap_audit import audit,probe,compare_pair
from review_cancel import ScanCancelled
from review_theme import PRESETS
from review_theme_files import light_palette

class Review06Tests(unittest.TestCase):
    def test_defaults_and_custom_keys(self):
        self.assertEqual({k:DEFAULT_KEYS[k] for k in ('previous','next','frame_back','frame_forward')},{'previous':'Q','next':'E','frame_back':'Left','frame_forward':'Right'})
        with tempfile.TemporaryDirectory() as folder:
            s=Settings(folder);s.data['app'].pop('arrow_defaults_version');s.data['shortcuts'].update(previous='Left',next='Right',frame_back=',',frame_forward='.');s.save()
            s=Settings(folder);self.assertEqual(s.data['shortcuts']['previous'],'Q')
            s.data['app'].pop('arrow_defaults_version');s.data['shortcuts']['previous']='F24';s.save();self.assertEqual(Settings(folder).data['shortcuts']['previous'],'F24')
        self.assertEqual([r['category'] for r in json.loads(Settings().data['dual']['panels'])],['Used','Kept','Deleted'])
    def test_author_rose_palette(self):
        rose=light_palette(PRESETS['Rose Quartz']);self.assertEqual(rose['highlighted_button'],'#df6889');self.assertEqual(rose['waveform'],'#d94a72');self.assertEqual(rose['panel'],'#dfcfd9')
    def test_cancel_resume_reuses_completed_indexes_and_pairs(self):
        base=Path(__file__).resolve().parents[1];fixture=base/'qa/resolve-fixture.mp4'
        decoder=base.parents[1]/'outputs/ClipComb Pro - 0.5.1 Preview/player/ffprobe.exe'
        if not fixture.exists() or not decoder.exists():self.skipTest('Local synthetic media integration fixture is not in public source')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'clips';root.mkdir()
            for name in ('first.mp4','second.mp4'):shutil.copy2(fixture,root/name)
            args=SimpleNamespace(limit=0,offset=0,lookback=0,window_seconds=0,probe_timeout=30,overlap=10,scan_cache=Path(folder)/'scan.sqlite3')
            cancel=threading.Event()
            def progress(text):
                if text.startswith('Indexed 1/'):cancel.set()
            with patch('review_overlap_audit.probe',wraps=probe) as read:
                with self.assertRaises(ScanCancelled):audit(args,root,Path(folder)/'cancel.csv',str(decoder),progress,cancel)
                self.assertEqual(read.call_count,1)
            with patch('review_overlap_audit.probe',wraps=probe) as read:
                audit(args,root,Path(folder)/'resumed.csv',str(decoder),lambda _:None)
                self.assertEqual(read.call_count,1)
            with patch('review_overlap_audit.probe',wraps=probe) as read,patch('review_overlap_audit.compare_pair',wraps=compare_pair) as compare:
                audit(args,root,Path(folder)/'cached.csv',str(decoder),lambda _:None)
                self.assertEqual(read.call_count,0);self.assertEqual(compare.call_count,0)
            uncached=SimpleNamespace(**vars(args));uncached.scan_cache=None
            audit(uncached,root,Path(folder)/'fresh.csv',str(decoder),lambda _:None)
            self.assertEqual((Path(folder)/'fresh.csv').read_bytes(),(Path(folder)/'cached.csv').read_bytes())
            (root/'first.mp4').touch()
            with patch('review_overlap_audit.probe',wraps=probe) as read:
                audit(args,root,Path(folder)/'changed.csv',str(decoder),lambda _:None);self.assertEqual(read.call_count,1)

if __name__=='__main__':unittest.main()
