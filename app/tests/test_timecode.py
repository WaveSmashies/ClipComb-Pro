# SPDX-License-Identifier: GPL-3.0-or-later
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from review_timecode import timecode,fps_text
from review_history import History

class TimecodeTests(unittest.TestCase):
    def test_source_frames(self):
        self.assertEqual(timecode(59/60,60),'00:00.59')
        self.assertEqual(timecode(92+18/60,60),'01:32.18')
        self.assertEqual(timecode(119/120,120),'00:00.119')
        self.assertEqual(timecode(3600,60),'01:00:00.00')
        self.assertEqual(timecode(1.001,'30000/1001'),'00:01.00')
        self.assertEqual(timecode(59.999,60),'01:00.00')
        self.assertEqual(timecode(92.3,60,False),'01:32.300')
        self.assertEqual(fps_text('60000/1001'),'59.94')
    def test_action_peeks_follow_undo_redo(self):
        c={'id':'a','ranges':[],'decision':'Unused','mix':[]};h=History();h.watch(c)
        self.assertIsNone(h.next_action())
        c['decision']='Used';h.record(c);self.assertEqual(h.next_action(),('a','Mark Used'))
        c['ranges']=[{'id':'one','start':1,'end':2}];h.record(c)
        self.assertEqual(h.next_action()[1],'Add marked moment')
        c.update(h.take()[1]);h.watch(c)
        self.assertEqual(h.next_action()[1],'Mark Used');self.assertEqual(h.next_action(True)[1],'Add marked moment')
        c.update(h.take(True)[1]);h.watch(c);self.assertEqual(h.next_action()[1],'Add marked moment')

if __name__=='__main__':unittest.main()
