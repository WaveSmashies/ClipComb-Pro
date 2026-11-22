# SPDX-License-Identifier: GPL-3.0-or-later
import copy,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Project,Settings
from review_theme import PRESETS,palette_for_settings
from review_theme_files import ThemeStore,light_palette
from review_cancel import capture,ScanCancelled
from review_queue import managed
TEST_ROOT = None

class Review04Tests(unittest.TestCase):
    def test_discovery_and_passive_metadata_are_not_review_progress(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temporary:
            root=Path(temporary);(root/'Unused').mkdir();(root/'Unused/a.mp4').write_bytes(b'fixture')
            project=Project(root);self.assertTrue(project.dirty);self.assertFalse(project.review_changed)
            clip=project.data['clips'][0];clip.update(media={'fps':30},position=10,mix=[{'enabled':True,'volume':100}]);project.passive_clip(clip)
            self.assertFalse(project.review_changed);self.assertFalse(managed(clip))
            clip['markers']=[{'id':'m','time':2}];project.mark_review(clip);self.assertTrue(project.review_changed);self.assertTrue(managed(clip))
            clip['markers']=[];project.mark_review(clip);self.assertFalse(project.review_changed)
            project.save();self.assertFalse(Project(root).review_changed)
    def test_missing_clip_keeps_its_review_records_and_category(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temporary:
            root=Path(temporary);(root/'Used').mkdir();path=root/'Used/a.mp4';path.write_bytes(b'fixture')
            project=Project(root);clip=project.data['clips'][0];clip['markers']=[{'id':'m','time':2}];project.save();path.unlink()
            resumed=Project(root);self.assertTrue(resumed.data['clips'][0]['missing']);self.assertEqual(resumed.data['clips'][0]['decision'],'Used')
            self.assertEqual(resumed.data['clips'][0]['markers'],clip['markers']);self.assertFalse(resumed.review_changed)
    def test_light_palettes_and_named_theme_roundtrip(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temporary:
            root=Path(temporary);settings=Settings(root);original=copy.deepcopy(dict(settings.data['theme']))
            for name,colors in PRESETS.items():
                light=light_palette(colors)
                self.assertGreater(sum(bytes.fromhex(light['background'][1:])),sum(bytes.fromhex(colors['background'][1:])))
                from review_theme_files import contrast
                self.assertGreaterEqual(contrast(light['highlighted_button'],light['highlighted_button_text']),3 if name=='Rose Quartz' else 4.5)
            store=ThemeStore(root);dark=dict(PRESETS['Elephant Daisy']);versions={'dark':dark,'light':light_palette(dark)}
            path=store.save('Lava Red',versions,{'palette':'Resolve'})
            self.assertEqual(store.list()['Lava Red - Custom'][1]['versions'],versions)
            self.assertEqual(dict(settings.data['theme']),original)
            settings.data['theme'].update(preset='Lava Red - Custom',light_mode='yes')
            self.assertEqual(palette_for_settings(settings),versions['light'])
            store.delete('Lava Red - Custom');self.assertFalse(path.exists())
    def test_cancel_terminates_the_owned_probe_quickly(self):
        event=threading.Event();timer=threading.Timer(.2,event.set);timer.start();start=time.monotonic()
        try:
            with self.assertRaises(ScanCancelled):capture([sys.executable,'-c','import time; time.sleep(30)'],cancel=event,timeout=40,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        finally:timer.cancel()
        self.assertLess(time.monotonic()-start,2)

if __name__=='__main__':unittest.main()
