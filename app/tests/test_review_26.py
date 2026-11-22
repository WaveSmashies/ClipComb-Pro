# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from review_ui_scale import UiScale
from review_render import ResizeFinish
from review_core import Settings


class LayoutRegressions(unittest.TestCase):
    def test_tcl_owned_popdown_is_not_queued_for_python_scaling(self):
        scale=UiScale.__new__(UiScale)
        scale.mapped(SimpleNamespace(widget='.profile.popdown.f.l'))
        scale.mapped(SimpleNamespace(widget='.filter.popdown'))
        self.assertFalse(hasattr(scale,'new_widgets'))

    def test_resize_finishes_with_one_paint_and_cancels_on_close(self):
        root=Mock();root.winfo_viewable.return_value=True
        root.after.side_effect=lambda delay,callback:'timer'
        widget=Mock();paint=Mock();finish=ResizeFinish(root,[widget],paint)
        for width in range(100,200):finish.request(SimpleNamespace(widget=widget,width=width,height=200))
        paint.assert_not_called();self.assertEqual(root.after.call_count,100)
        finish.run();paint.assert_called_once_with(root)
        finish.request(SimpleNamespace(widget='.combobox.popdown.f.l',width=200,height=200))
        finish.request(SimpleNamespace(widget=widget,width=199,height=200))
        self.assertEqual(root.after.call_count,100)
        finish.request(SimpleNamespace(widget=widget,width=210,height=200));finish.close();finish.run()
        self.assertEqual(paint.call_count,1);self.assertIsNone(finish.timer)

    def test_monitor_scale_waits_for_release_and_ignores_its_own_size_change(self):
        source = (0, 0, 2560, 1440)
        destination = (2560, 0, 6400, 2160)
        root = Mock()
        root.winfo_viewable.return_value = True
        app = SimpleNamespace(root=root, closed=False, palette={}, timeline=Mock(),
                              update_transports=Mock(), queue_view=Mock())
        with patch('review_ui_scale.monitor_rect', return_value=source) as monitor, \
             patch('review_ui_scale.window_move_in_progress', return_value=True) as moving, \
             patch('review_ui_scale.window_rect', return_value=(2500, 50, 4700, 1250)) as frame, \
             patch('review_theme.install_theme') as install:
            scale = UiScale(app)
            scale.apply_new = Mock()
            monitor.return_value = destination
            for _ in range(4):
                scale.monitor_settled()
                self.assertEqual(scale.factor, 1)
            install.assert_not_called()

            moving.return_value = False
            scale.monitor_settled()
            self.assertEqual(scale.factor, 1.5)
            install.assert_called_once_with(root, app.palette)
            scale.apply_new.assert_called_once()

            monitor.return_value = source
            scale.monitor_settled()
            self.assertEqual(scale.factor, 1.5)
            install.assert_called_once()

            frame.return_value = (200, 50, 2000, 1150)
            scale.monitor_settled()
            self.assertEqual(scale.factor, 1)
            self.assertEqual(install.call_count, 2)

    def test_date_audio_factory_defaults_stay_off(self):
        settings=Settings().data
        self.assertFalse(settings.getboolean('audio','date_profiles_enabled'))
        self.assertEqual(settings['audio']['default_profile'],'Configured tracks')


if __name__=='__main__':unittest.main()
