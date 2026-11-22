# SPDX-License-Identifier: GPL-3.0-or-later
"""Contextual trim shortcuts and an overridable automatic Delete fallback."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Settings,DEFAULT_KEYS,DEFAULT_SECONDARY_KEYS
from review_bindings import action_for,keys_for,secondary_text,validate
from review_cleanup import Cleanup
from clip_review import ReviewApp,ACTION_LABELS,SHORTCUT_HELP


def bindings():
    return dict(shortcuts=dict(DEFAULT_KEYS),shortcuts_secondary=dict(DEFAULT_SECONDARY_KEYS))


class ContextualShortcuts(unittest.TestCase):
    def test_defaults_match_captured_controls(self):
        expected=dict(marker='F',star='G',review_page='R',compare_page='C',trim_file='T',create_trim='T',
                      used='W',deleted='A',kept='D',unused='S',previous='Q',next='E',remove_range='Tab',scrub_audio='Alt+S')
        self.assertEqual({k:DEFAULT_KEYS[k] for k in expected},expected)
        self.assertEqual(DEFAULT_SECONDARY_KEYS['remove_range'],'Backspace')
        validate(bindings(),ACTION_LABELS)

    def test_shared_trim_dispatch_is_one_action_per_press(self):
        app=MagicMock()
        app.root=object();app.viewer.detached=False;app.shortcuts_allowed.return_value=True
        app.settings=Settings();app.pressed=set();app.busy=False
        app.cleanup.mode='review'
        app.cleanup.trim_mode.side_effect=lambda:setattr(app.cleanup,'mode','trim')
        event=SimpleNamespace(widget=SimpleNamespace(winfo_toplevel=lambda:app.root))
        self.assertEqual(ReviewApp.dispatch_binding(app,'T',event,('key',84)),'break')
        app.cleanup.trim_mode.assert_called_once();app.cleanup.render_trim.assert_not_called()
        # A repeat event from the same held key must not immediately confirm.
        ReviewApp.dispatch_binding(app,'T',event,('key',84));app.cleanup.render_trim.assert_not_called()
        app.pressed.clear()
        ReviewApp.dispatch_binding(app,'T',event,('key',84))
        app.cleanup.render_trim.assert_called_once();app.cleanup.trim_mode.assert_called_once()

    def test_shared_key_works_across_primary_and_secondary(self):
        value=bindings();value['shortcuts']['create_trim']='';value['shortcuts_secondary']['create_trim']='T'
        validate(value,ACTION_LABELS)
        for mode in ('review','compare'):self.assertEqual(action_for(value,'T',mode),'trim_file')
        self.assertEqual(action_for(value,'T','trim'),'create_trim')
        value['shortcuts']['star']='T'
        with self.assertRaises(ValueError):validate(value,ACTION_LABELS)

    def test_page_reselection_is_a_no_op(self):
        cleanup=MagicMock();cleanup.app.busy=False
        cleanup.mode='review';Cleanup.review(cleanup);cleanup.app.refresh_ranges.assert_not_called()
        cleanup.mode='trim';Cleanup.trim_mode(cleanup);cleanup.ready.assert_not_called();cleanup.job.assert_not_called()
        cleanup.mode='compare';Cleanup.compare_group(cleanup);cleanup.ready.assert_not_called();cleanup.review.assert_not_called()

    def test_delete_fallback_display_and_override(self):
        value=bindings()
        self.assertEqual(secondary_text(value,'remove_range'),'Backspace / Delete')
        self.assertEqual(keys_for(value,'remove_range'),['Tab','Backspace','Delete'])
        self.assertEqual(action_for(value,'Delete'),'remove_range')
        value['shortcuts_secondary']['remove_range']='H'
        self.assertEqual(secondary_text(value,'remove_range'),'H / Delete')
        for section in ('shortcuts','shortcuts_secondary'):
            custom=copy.deepcopy(value);custom[section]['play']='Delete'
            self.assertEqual(secondary_text(custom,'remove_range'),'H')
            self.assertEqual(action_for(custom,'Delete'),'play')
            self.assertNotIn('Delete',keys_for(custom,'remove_range'))
        value['shortcuts']['play']='Ctrl+Delete'
        self.assertEqual(action_for(value,'Delete'),'remove_range')

    def test_custom_config_and_live_help_are_preserved(self):
        self.assertIn('Primary F;',SHORTCUT_HELP['marker'])
        self.assertIn('Primary W;',SHORTCUT_HELP['used'])
        self.assertIn('Secondary Backspace / Delete.',SHORTCUT_HELP['remove_range'])
        with tempfile.TemporaryDirectory() as folder:
            config=Settings(folder);config.data['shortcuts']['star']='Mouse4';config.save()
            self.assertEqual(Settings(folder).data['shortcuts']['star'],'Mouse4')


if __name__=='__main__':unittest.main()
