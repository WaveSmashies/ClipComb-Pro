# SPDX-License-Identifier: GPL-3.0-or-later
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_queue import kinds_for,first_bookmark,activity_text

class BookmarkStatusTests(unittest.TestCase):
    def test_earliest_runtime_controls_badge_color(self):
        clip=dict(decision='Unused',markers=[dict(id='late',time=8,color_slot=3),dict(id='early',time=2,color_slot=7)],trimmed_by_clipcomb=True,merged_by_clipcomb=True)
        self.assertEqual(first_bookmark(clip)['color_slot'],7)
        self.assertEqual(kinds_for(clip),['scissors','chain','bookmark'])
    def test_tooltip_lists_actual_work_and_restoration(self):
        clip=dict(decision='Kept',markers=[dict(id='m',time=2)],ranges=[dict(start=1,end=3,enabled=True),dict(start=4,end=5,enabled=False)],trim_ranges=[dict(start=0,end=8)],trim_undone=True,audio_modified=True)
        text=activity_text(clip)
        for label in ('1 bookmark','2 marked moment','file trim plan','trim was undone','Sorting decision: Kept'):self.assertIn(label,text)
        self.assertNotIn('enabled for export',text)
        self.assertNotIn('Audio mixer modified',text)
        self.assertNotIn('star',kinds_for(dict(decision='Unused',trim_undone=True)))
        self.assertEqual(activity_text(dict(decision='Unused')),'No review changes.')

if __name__=='__main__':unittest.main()
