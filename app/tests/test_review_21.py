# SPDX-License-Identifier: GPL-3.0-or-later
"""Sorting guide, stable audio display and opt-in media-key lifecycle."""
import ctypes as c
import os,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_bindings import sorting_guide
from review_core import Settings
from review_waveform import display_amplitude
from review_media_keys import MediaPlayPause,MediaKeyData
from clip_review import ReviewApp


class Review21(unittest.TestCase):
    def test_footer_uses_saved_custom_keys_and_unbound_actions(self):
        config=Settings()
        self.assertEqual(sorting_guide(config.data),'W - Mark clip Used | S - Mark Unused | A - Mark Deleted | D - Mark Kept')
        with tempfile.TemporaryDirectory() as folder:
            saved=Settings(folder)
            saved.data['shortcuts'].update(used='Mouse4',unused='',deleted='J')
            saved.data['shortcuts_secondary']['used']='Up'
            saved.save()
            self.assertEqual(sorting_guide(Settings(folder).data),'Mouse4 / Up - Mark clip Used | Unbound - Mark Unused | J - Mark Deleted | D - Mark Kept')

    def test_waveform_has_fixed_scale_and_keeps_quiet_gameplay_visible(self):
        # Measured from the reported clip: gameplay median .003317, speech peak .86364.
        gameplay=round(.003317*65535);speech=round(.86364*65535)
        old_height=gameplay/speech*50
        self.assertLess(old_height,1)
        self.assertGreater(display_amplitude(gameplay)*50,10)
        self.assertGreater(display_amplitude(speech),display_amplitude(gameplay))
        self.assertEqual(display_amplitude(0),0)
        self.assertAlmostEqual(display_amplitude(65535),1)
        values=[display_amplitude(n) for n in (0,1,10,100,1000,10000,65535)]
        self.assertEqual(values,sorted(values))
        self.assertLess(display_amplitude(2)*50,.3)  # Tiny background noise stays tiny.

    def test_media_key_defaults_off_and_respects_dialogs(self):
        app=MagicMock();app.settings=Settings();app.busy=False;app.loading=False
        app.root.grab_current.return_value=None
        ReviewApp.media_play_pause(app);app.toggle_play.assert_not_called()
        app.settings.data['app']['media_play_pause']='yes'
        ReviewApp.media_play_pause(app);app.toggle_play.assert_called_once()
        app.root.grab_current.return_value=object()
        ReviewApp.media_play_pause(app);app.toggle_play.assert_called_once()
        app.root.grab_current.return_value=None;app.busy=True
        ReviewApp.media_play_pause(app);app.toggle_play.assert_called_once()

    @unittest.skipUnless(os.name=='nt','Windows media key')
    def test_native_media_listener_repeat_and_release(self):
        media=MediaPlayPause();self.addCleanup(media.close)
        media.set_enabled(False);self.assertIsNone(media.worker)
        for _ in range(3):
            media.set_enabled(True);worker=media.worker
            media.set_enabled(True);self.assertIs(media.worker,worker)
            self.assertTrue(media.handle)
            data=MediaKeyData(media.KEY,0,0,0,0)
            for _ in range(4):self.assertEqual(media.callback(0,0x100,c.addressof(data)),1)
            self.assertTrue(media.events.get(timeout=2))
            self.assertTrue(media.events.empty())
            self.assertEqual(media.callback(0,0x101,c.addressof(data)),1)
            self.assertEqual(media.callback(0,0x100,c.addressof(data)),1)
            self.assertTrue(media.events.get(timeout=2))
            media.close();self.assertFalse(worker.is_alive());self.assertTrue(media.events.empty())
            self.assertIsNone(media.handle);self.assertIsNone(media.callback)


if __name__=='__main__':unittest.main()
