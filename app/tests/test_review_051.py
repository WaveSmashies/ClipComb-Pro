# SPDX-License-Identifier: GPL-3.0-or-later
import json,sys,tempfile,unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Settings
from review_theme import PRESETS,DEFAULT_PALETTE
from review_theme_files import light_palette,contrast,luminance
from review_icons import asset_folder

class Review051Tests(unittest.TestCase):
    def test_old_empty_dual_layout_is_repaired_but_deliberate_new_layout_survives(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=Settings(folder);settings.data['dual'].pop('layout_version');settings.data['dual']['panels']='[]';settings.save()
            settings=Settings(folder);self.assertEqual([s['category'] for s in json.loads(settings.data['dual']['panels'])],['Used','Kept','Deleted'])
            settings.data['dual']['panels']='[]';settings.save()
            self.assertEqual(Settings(folder).data['dual']['panels'],'[]')
    def test_light_accents_have_visible_contrast(self):
        for name,dark in PRESETS.items():
            with self.subTest(name=name):
                light=light_palette(dark)
                self.assertGreaterEqual(contrast(light['waveform'],light['panel']),{'Rose Quartz':2.7,'Grey Mann':3.6}.get(name,4.5))
                self.assertGreaterEqual(contrast(light['selection'],light['panel']),3)
                self.assertGreaterEqual(contrast(light['highlighted_button'],light['highlighted_button_text']),3 if name=='Rose Quartz' else 4.5)
                self.assertLess(luminance(light['waveform']),luminance(dark['waveform']))
    def test_author_palette_colors(self):
        self.assertEqual(DEFAULT_PALETTE['waveform'],'#b39ae0')
        self.assertEqual(PRESETS['Kachow']['highlighted_button'],'#ff726a')
        self.assertEqual(PRESETS['Kachow']['waveform'],'#ff645b')
        self.assertEqual(PRESETS['Kachow']['highlighted_clip'],'#8d1b1e')
    def test_blank_and_replacement_holds_are_transparent(self):
        for name in ('blank.png','dark-hold.png','light-hold.png'):
            with self.subTest(name=name),Image.open(asset_folder()/'animation'/name) as picture:
                self.assertEqual(picture.convert('RGBA').getpixel((0,0))[3],0)
                if name=='blank.png':self.assertEqual(picture.getchannel('A').getextrema(),(0,0))

if __name__=='__main__':unittest.main()
