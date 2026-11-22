# SPDX-License-Identifier: GPL-3.0-or-later
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Settings
from review_brand import THEME_NAMES
from review_theme import PRESETS,palette_for_settings
from review_tooltip_text import wording,SHORTCUTS
from review_help import HELP

class Review07Tests(unittest.TestCase):
    def test_theme_rename_migrates_old_preferences_and_keeps_custom_names(self):
        for old,new in THEME_NAMES.items():
            with self.subTest(old=old),tempfile.TemporaryDirectory() as folder:
                settings=Settings(folder);settings.data['theme']['preset']=old;settings.save()
                settings=Settings(folder);self.assertEqual(settings.data['theme']['preset'],new)
                self.assertEqual(palette_for_settings(settings),PRESETS[new])
                settings.data['theme']['preset']=old+' - Custom';settings.save()
                self.assertEqual(Settings(folder).data['theme']['preset'],old+' - Custom')
        self.assertEqual(list(PRESETS),['Default','Grimace Shake','Rose Quartz','Elephant Daisy','Kachow','Jarate','Michael House-Key','Gotta Go Fast','Grey Mann'])

    def test_edited_help_keeps_live_keybinds_and_correct_export_and_speed_details(self):
        original='Add a bookmark, jump to one, or edit its name, description and color. Click a diamond to seek; double-click to edit. Drag to move it; the magnet controls snapping to the playhead and nearby elements.\n\nShortcut: Ctrl+E / F24'
        text=wording(original);self.assertNotIn('Click a diamond',text);self.assertTrue(text.endswith('Shortcut: Ctrl+E / F24'))
        self.assertIn('OTIO or XML',SHORTCUTS['export']);self.assertIn('minimum of 0.1x',SHORTCUTS['slow'])
        self.assertIn('Opening a project always starts paused',HELP['app','autoplay'])
        self.assertIn('Escape binds to Escape',HELP['shortcuts']);self.assertIn('Secondary Backspace',HELP['shortcuts'])
        self.assertIn('Default: auto (recommended).',HELP['tools','hardware_decoding'])

if __name__=='__main__':unittest.main()
