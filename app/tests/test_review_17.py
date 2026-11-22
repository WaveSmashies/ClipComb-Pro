# SPDX-License-Identifier: GPL-3.0-or-later
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Settings
from review_queue import managed,kinds_for,activity_text
from review_stars import tooltip,DEFAULT_TOOLTIP
from review_history import History

class ClipStarTests(unittest.TestCase):
    def test_star_is_separate_from_activity(self):
        clip=dict(id='clip',decision='Unused',star=dict(color_slot=6,title=''))
        self.assertFalse(managed(clip));self.assertEqual(kinds_for(clip),['favorite'])
        self.assertEqual(tooltip(clip),'This clip has a purple star. '+DEFAULT_TOOLTIP)
        clip['star']['title']='Check microphone';self.assertEqual(tooltip(clip),'Check microphone')
        self.assertEqual(activity_text(clip),'No review changes.')
        clip['audio_modified']=True;self.assertFalse(managed(clip));self.assertNotIn('Audio mixer',activity_text(clip))
    def test_star_undo_is_independent(self):
        clip=dict(id='clip',decision='Unused',ranges=[],markers=[])
        history=History();history.watch(clip);clip['star']=dict(color_slot=3,title='Pick')
        history.record(clip,fields=('star',))
        self.assertEqual(history.take(),('clip',{'star':None}))
        self.assertEqual(history.take(True),('clip',{'star':dict(color_slot=3,title='Pick')}))
    def test_new_device_and_cursor_defaults(self):
        settings=Settings()
        self.assertEqual(settings.data['audio']['output_device'],'auto')
        self.assertTrue(settings.data.getboolean('magnifier','show_cursor'))

if __name__=='__main__':unittest.main()
