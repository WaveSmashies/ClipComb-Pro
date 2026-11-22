# SPDX-License-Identifier: GPL-3.0-or-later
"""The direct-import warning is enabled by default and remains user controlled."""
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Settings
from review_export_warning import MESSAGE


class StudioWarningPreference(unittest.TestCase):
    def test_older_settings_gain_warning_and_saved_choice_survives_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=Settings(folder);del settings.data['export']['dont_show_warning'];settings.save()
            updated=Settings(folder);self.assertFalse(updated.data.getboolean('export','dont_show_warning'))
            updated.data['export']['dont_show_warning']='yes';updated.save()
            self.assertTrue(Settings(folder).data.getboolean('export','dont_show_warning'))
            self.assertFalse(Settings().data.getboolean('export','dont_show_warning'))

    def test_warning_text_matches_requested_message(self):
        self.assertEqual(MESSAGE,'DO NOT TOUCH DaVinci Resolve while ClipComb Pro is importing your clips. This can break your project!')


if __name__=='__main__':unittest.main()
