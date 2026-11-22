# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
from review_core import (Project, Settings, SpeedCycle, SlowCycle, canonical_key, key_from_event, mouse_binding, profile_for_name,
                         atomic_json, file_identity, PROJECT_FILE, JOURNAL_FILE)

TEST_ROOT = None


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'Unused').mkdir()
        self.first = self.root / 'Unused' / 'Replay 2025-07-04 18-53-08.mp4'
        self.second = self.root / 'Unused' / 'Replay 2025-07-31 16-51-59.mp4'
        self.first.write_bytes(b'original first clip')
        self.second.write_bytes(b'original second clip')

    def test_stage_save_resume_export_preserves_bytes(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.first, self.second)}
        p = Project(self.root)
        c, other = p.data['clips']
        c['decision'] = 'Used'
        c['ranges'] = [{'id': 'a', 'start': 1.125, 'end': 2.375, 'enabled': True},
                       {'id': 'b', 'start': 4, 'end': 5, 'enabled': False}]
        other['decision'] = 'Deleted'
        other['ranges'] = [{'id': 'z', 'start': 0, 'end': 1, 'enabled': True}]
        self.assertTrue(self.first.exists())
        self.assertFalse(p.path.exists())
        self.assertEqual(p.save(), 2)
        self.assertFalse(self.first.exists())
        for folder in ('Used', 'Deleted'):
            for path in (self.root / folder).iterdir():
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before[path.name])
        resumed = Project(self.root)
        self.assertEqual(len(resumed.data['clips']), 2)
        out, count = resumed.export_ranges()
        self.assertEqual(count, 1)
        payload = json.loads(out.read_text())
        self.assertEqual(payload['clips'][0]['ranges'][0]['start'], 1.125)
        self.assertTrue(Path(payload['clips'][0]['path']).exists())

    def test_collision_moves_nothing(self):
        (self.root / 'Used').mkdir()
        target = self.root / 'Used' / self.first.name
        target.write_bytes(b'unrelated existing file')
        p = Project(self.root)
        next(c for c in p.data['clips'] if c['path'].startswith('Unused'))['decision'] = 'Used'
        with self.assertRaisesRegex(ValueError, 'already exists'):
            p.save()
        self.assertTrue(self.first.exists())
        self.assertEqual(target.read_bytes(), b'unrelated existing file')

    def test_failure_rolls_back_prior_moves(self):
        p = Project(self.root)
        for c in p.data['clips']:
            c['decision'] = 'Used'
        real_rename = os.rename
        count = [0]
        def failing(src, dst):
            count[0] += 1
            if count[0] == 2:
                raise PermissionError('simulated locked second clip')
            return real_rename(src, dst)
        with patch('review_core.os.rename', side_effect=failing):
            with self.assertRaises(PermissionError):
                p.save()
        self.assertTrue(self.first.exists() and self.second.exists())
        self.assertFalse((self.root / JOURNAL_FILE).exists())

    def test_crash_recovery_restores_original_path(self):
        p = Project(self.root)
        p.save()
        (self.root / 'Used').mkdir(exist_ok=True)
        identity = file_identity(self.first)
        destination = self.root / 'Used' / self.first.name
        atomic_json(self.root / JOURNAL_FILE, {'transaction': 'interrupted', 'moves': [
            {'src': str(self.first.relative_to(self.root)), 'dst': str(destination.relative_to(self.root)), 'identity': identity}]})
        os.rename(self.first, destination)
        Project(self.root)
        self.assertTrue(self.first.exists())
        self.assertFalse(destination.exists())

    def test_external_modification_is_not_moved(self):
        p = Project(self.root)
        p.data['clips'][0]['decision'] = 'Used'
        self.first.write_bytes(b'changed while reviewing')
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            p.save()
        self.assertTrue(self.first.exists())

    def test_other_window_save_is_detected(self):
        p1, p2 = Project(self.root), Project(self.root)
        p1.save()
        with self.assertRaisesRegex(ValueError, 'another window'):
            p2.save()

    def test_escape_path_is_rejected(self):
        p = Project(self.root)
        with self.assertRaises(ValueError):
            p.checked('../outside.mp4')


class InputTests(unittest.TestCase):
    def test_mouse_bindings_and_modifiers(self):
        for button,name in enumerate(('MouseLeft','MouseMiddle','MouseRight','MouseX1','MouseX2'),1):
            self.assertEqual(mouse_binding(button),name)
            self.assertEqual(canonical_key(f'Ctrl+Shift+{name}'),f'Ctrl+Shift+{name}')
            self.assertEqual(mouse_binding(button,5),f'Ctrl+Shift+{name}')
        self.assertEqual(canonical_key('middle click'),'MouseMiddle')
        self.assertEqual(canonical_key('Alt+Mouse5'),'Alt+MouseX2')

    def test_slower_speed_uses_current_rate_and_never_wraps(self):
        cycle = SlowCycle()
        rate=2.
        for expected in (1.9,1.8,1.7):
            rate=cycle.press(rate);self.assertEqual(rate,expected)
        self.assertEqual(cycle.press(2.25),2.15)
        self.assertEqual(cycle.press(.1),.1)

    def test_shift_digit_and_frame_keys(self):
        for vk, sym, state, expected in [(49, 'exclam', 1, 'Shift+1'), (188, 'comma', 0, ','),
                                         (190, 'period', 0, '.'), (190, 'greater', 1, 'Shift+.')]:
            self.assertEqual(key_from_event(SimpleNamespace(keycode=vk, keysym=sym, state=state)), expected)
        self.assertEqual(canonical_key('comma'), ',')

    def test_quarter_steps_and_three_second_reset(self):
        cycle = SpeedCycle()
        self.assertEqual([cycle.press(1, n) for n in range(5)], [1, 1.25, 1.5, 1.75, 1])
        self.assertEqual(cycle.press(1, 5), 1.25)
        self.assertEqual(cycle.press(1, 9), 1)
        self.assertEqual(cycle.press(3, 10), 3)
        self.assertEqual(cycle.press(3, 11), 3.25)

    def test_function_keys_all_24(self):
        for n in range(1, 25):
            self.assertEqual(canonical_key(f'Ctrl+F{n}'), f'Ctrl+F{n}')
            self.assertEqual(key_from_event(SimpleNamespace(keycode=111 + n, state=4, keysym='unknown')), f'Ctrl+F{n}')
        self.assertEqual(canonical_key('control+shift+s'), 'Ctrl+Shift+S')

    def test_cutoff_uses_filename_not_current_folder(self):
        cutoff = '2025-07-28T20:25:00'
        self.assertEqual(profile_for_name('Used/Replay 2025-07-04 18-53-08.mp4', cutoff), 'Legacy OBS')
        self.assertEqual(profile_for_name('Kept/Replay 2025-07-31 16-51-59.mp4', cutoff), 'Modern OBS')
        self.assertEqual(profile_for_name('2025-07-28 20-25-00.mp4', cutoff), 'Modern OBS')
        self.assertEqual(profile_for_name('Funny moment.mp4', cutoff), 'File track names')

    def test_config_is_single_portable_ini(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            s = Settings(folder)
            s.data['shortcuts']['used'] = 'F24'
            s.save()
            self.assertEqual(Settings(folder).data['shortcuts']['used'], 'F24')
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['ClipComb Pro.ini'])


if __name__ == '__main__':
    unittest.main()
