# SPDX-License-Identifier: GPL-3.0-or-later
"""The scheduler leaves active playback fast and lets a restored window wake immediately."""
import unittest
from unittest.mock import Mock

from review_activity import UpdateTimer, update_interval


class UpdateClockTests(unittest.TestCase):
    def test_minimized_deadline_wins_even_if_playing_or_processing(self):
        self.assertEqual(update_interval(visible=False, foreground=False, realtime=True, working=True), 1000)

    def test_focus_only_limits_quiet_player(self):
        self.assertEqual(update_interval(visible=True, foreground=True, paused_player=True), 55)
        self.assertEqual(update_interval(visible=True, foreground=False, paused_player=True), 400)
        self.assertEqual(update_interval(visible=True, foreground=False, realtime=True), 16)
        self.assertEqual(update_interval(visible=True, foreground=True, working=True), 80)

    def test_restore_replaces_sleeping_timer_and_pending_frame_is_not_delayed(self):
        root = Mock()
        root.after.side_effect = ['minimized','restore']
        callback = Mock()
        timer = UpdateTimer(root, callback)
        timer.schedule(1000)
        timer.schedule(0)
        timer.schedule(16)
        root.after_cancel.assert_called_once_with('minimized')
        self.assertEqual(root.after.call_count, 2)
        timer.run()
        callback.assert_called_once()
        self.assertIsNone(timer.token)
