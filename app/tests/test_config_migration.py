# SPDX-License-Identifier: GPL-3.0-or-later
import configparser,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Settings,CONFIG_FILE,LEGACY_CONFIG_FILE

class ConfigMigrationTests(unittest.TestCase):
    def old_file(self,folder):
        data=configparser.ConfigParser(interpolation=None)
        data['shortcuts']={'used':'F24'};data['theme']={'preset':'Kachow'}
        data['cleanup']={'source':'D:/Example clips'};data['projects']={'example':'saved project'}
        path=Path(folder)/LEGACY_CONFIG_FILE
        with path.open('w',encoding='utf-8-sig') as out:data.write(out)
        return path,data
    def test_legacy_settings_migrate_once_with_all_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            old,data=self.old_file(folder);settings=Settings(folder)
            self.assertEqual(settings.path.name,CONFIG_FILE);self.assertTrue(settings.path.exists());self.assertFalse(old.exists())
            for section in data:
                for key,value in data[section].items():self.assertEqual(settings.data[section][key],value)
            settings.save();self.assertEqual(Settings(folder).data['shortcuts']['used'],'F24')
            self.assertEqual({p.name for p in Path(folder).iterdir()},{CONFIG_FILE})
    def test_new_file_wins_if_both_exist(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=Settings(folder);settings.data['shortcuts']['used']='F23';settings.save()
            old,_=self.old_file(folder);before=old.read_bytes()
            self.assertEqual(Settings(folder).data['shortcuts']['used'],'F23');self.assertEqual(old.read_bytes(),before)
    def test_failed_atomic_write_keeps_the_legacy_file(self):
        with tempfile.TemporaryDirectory() as folder:
            old,_=self.old_file(folder);before=old.read_bytes()
            with patch('review_core.os.replace',side_effect=OSError('simulated write failure')):
                with self.assertRaises(OSError):Settings(folder)
            self.assertEqual(old.read_bytes(),before);self.assertFalse((Path(folder)/CONFIG_FILE).exists())

if __name__=='__main__':unittest.main()
