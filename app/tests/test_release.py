# SPDX-License-Identifier: GPL-3.0-or-later
"""Branding, public defaults and compatibility with private settings/projects."""
import configparser
from pathlib import Path
import sys
import tempfile
import unittest
import runpy
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_brand import APP_NAME, VERSION
from review_core import PROJECT_FILE, JOURNAL_FILE, Project, Settings


class ReleaseTests(unittest.TestCase):
    def test_source_package_excludes_personal_and_generated_files(self):
        builder = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tools/build_release.py'))
        files = builder['source_files']
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('clip_review.py', 'README.md', 'ClipComb Pro.ini.example', 'tests/test_example.py',
                         'clip-review.ini','ClipComb Pro.ini', 'recording.mp4', 'qa/private.py', 'player/libmpv-2.dll',
                         'dist/ClipComb Pro/Source.zip', 'cache/connection.request.json',
                         'assets/tutorial/player.html','tools/TutorialHost.cs','tutorial/ClipComb Tutorial.exe'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            with patch.dict(files.__globals__, ROOT=root):
                included = {p.relative_to(root).as_posix() for p in files()}
            self.assertEqual(included, {'clip_review.py', 'README.md', 'ClipComb Pro.ini.example', 'tests/test_example.py','assets/tutorial/player.html','tools/TutorialHost.cs'})

    def test_new_defaults_are_generic(self):
        settings = Settings()
        self.assertEqual(APP_NAME, 'ClipComb Pro')
        self.assertEqual(VERSION, '1.0.0')
        self.assertFalse(settings.data.getboolean('audio', 'date_profiles_enabled'))
        self.assertEqual(settings.data['audio']['default_profile'], 'Configured tracks')
        self.assertEqual(settings.data['audio']['configured_enabled'], '1')
        self.assertEqual(settings.data['export']['timeline_name'], 'ClipComb Pro selects')
        self.assertFalse(settings.data['projects'])
        self.assertEqual(settings.data['app']['last_project'], '')

    def test_old_ini_and_project_remain_usable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = configparser.ConfigParser()
            old['audio'] = {'date_profiles_enabled': 'yes', 'default_profile': 'Auto by date',
                            'layout_change': '2022-01-02T03:04:05', 'modern_names': 'Custom|Names'}
            old['shortcuts'] = {'used': 'F24'}
            with (root / 'clip-review.ini').open('w', encoding='utf-8') as file:
                old.write(file)
            settings = Settings(root)
            settings.save()
            self.assertEqual(settings.path.name,'ClipComb Pro.ini')
            self.assertFalse((root/'clip-review.ini').exists())
            for section in old:
                for key in old[section]:
                    self.assertEqual(settings.data[section][key], old[section][key])
            self.assertEqual(PROJECT_FILE, 'clip-review.project.json')
            self.assertEqual(JOURNAL_FILE, '.clip-review-save.json')
            (root / 'Unused').mkdir()
            clip = root / 'Unused' / 'fixture.mp4'
            clip.write_bytes(b'temporary fixture')
            project = Project(root)
            project.data['clips'][0]['ranges'] = [{'id': 'r', 'start': 1, 'end': 2, 'enabled': True}]
            project.save()
            self.assertEqual(Project(root).data['clips'][0]['ranges'][0]['id'], 'r')
            self.assertEqual(clip.read_bytes(), b'temporary fixture')


if __name__ == '__main__':
    unittest.main()
