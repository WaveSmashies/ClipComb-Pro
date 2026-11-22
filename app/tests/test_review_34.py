# SPDX-License-Identifier: GPL-3.0-or-later
"""Review Queue badges keep their spacing and represent distinct annotations."""
import unittest

from review_queue import kinds_for, list_badge_layout


class QueueBadgeTests(unittest.TestCase):
    def test_asterisk_requires_a_marked_moment(self):
        clip = dict(star={'color':0}, markers=[{'time':1}], trimmed_by_clipcomb=True,
                    merged_by_clipcomb=True, provenance=[{}], decision='Used', trim_ranges=[{}])
        self.assertEqual(kinds_for(clip), ['favorite','scissors','chain','bookmark'])
        clip['ranges'] = [{'start':1,'end':2,'enabled':False}]
        self.assertEqual(kinds_for(clip), ['favorite','scissors','chain','star','bookmark'])

    def test_five_badges_extend_left_and_leave_decision_column_clear(self):
        box = (240,40,84,31)
        start,size,step = list_badge_layout(box,2,5,1)
        self.assertLess(start,box[0])
        self.assertEqual(size,24)
        self.assertGreaterEqual(step,size)
        self.assertEqual(start+step*4+size,324)

    def test_narrow_queue_keeps_spacing_and_both_edges_visible(self):
        start,size,step = list_badge_layout((19,40,63,24),2,5,.75)
        self.assertGreaterEqual(start,2)
        self.assertGreaterEqual(step,size)
        self.assertLessEqual(start+4*step+size,82)
