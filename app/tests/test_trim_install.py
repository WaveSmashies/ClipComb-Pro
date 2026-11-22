# SPDX-License-Identifier: GPL-3.0-or-later
"""File replacement must preserve originals across failures and restarts."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Project,atomic_json
from review_cleanup_core import hash_file
from review_overlap_audit import identity
import review_trim_install as trim
TEST_ROOT = None


class TrimReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=TEST_ROOT);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'Unused').mkdir()
        self.source=self.root/'Unused/clip.mp4';self.source.write_bytes(b'full original media')
        (self.root/'Unused/other.mp4').write_bytes(b'other media')
        self.project=Project(self.root);self.clip=next(c for c in self.project.data['clips'] if c['path'].endswith('clip.mp4'))
        self.clip.update(media={'duration':10,'fps':30,'audio':[]},position=3,
                         ranges=[{'id':'r','start':2,'end':7,'enabled':True}],
                         markers=[{'id':'m','time':3,'name':'Bookmark','note':'Description','color_slot':3}])
        self.project.save();self.before=copy.deepcopy(self.clip)
        self.staged=self.root/'staged.mp4';self.staged.write_bytes(b'verified trimmed media')
        self.result=SimpleNamespace(paths=[self.staged],checksums=[hash_file(self.staged)],
                    source_checksum=hash_file(self.source),source_identity=identity(self.source.lstat()),
                    mappings=[[(2,8,0)]],metadata=[{'duration':6,'fps':30,'audio':[]}],details=[{}])

    def test_suffix_keeps_original_in_deleted(self):
        outputs,original,_=trim.install(self.project,self.clip,self.result,original_name=False)
        self.assertTrue(outputs[0]['path'].endswith('_TRIMMED.mp4'))
        self.assertEqual(self.project.checked(original['path']).read_bytes(),b'full original media')
        self.assertFalse(self.source.exists())

    def test_suffix_save_failure_restores_source(self):
        original=atomic_json
        def fail(path,data):
            if path==self.project.path:raise OSError('simulated')
            return original(path,data)
        with patch('review_core.atomic_json',side_effect=fail):
            with self.assertRaises(OSError):trim.install(self.project,self.clip,self.result,original_name=False)
        self.assertEqual(self.source.read_bytes(),b'full original media')
        self.assertFalse(self.source.with_name('clip_TRIMMED.mp4').exists())

    def test_replace_preserves_name_backup_annotations_and_other_pending_decisions(self):
        other=next(c for c in self.project.data['clips'] if c is not self.clip)
        other['decision']='Kept';self.project.dirty=True
        outputs,original,receipt=trim.install(self.project,self.clip,self.result)
        self.assertEqual(outputs[0]['id'],self.before['id'])
        self.assertEqual(self.source.read_bytes(),b'verified trimmed media')
        self.assertEqual(self.project.checked(original['path']).read_bytes(),b'full original media')
        self.assertEqual(original['path'],str(Path('Deleted/clip_ORIGINAL.mp4')))
        self.assertEqual(original['decision'],'Deleted')
        self.assertEqual(outputs[0]['markers'][0]['time'],1)
        self.assertEqual(outputs[0]['markers'][0]['color_slot'],3)
        self.assertEqual(outputs[0]['position'],1)
        saved=Project(self.root)
        self.assertEqual(next(c for c in saved.data['clips'] if c['id']==other['id'])['decision'],'Unused')
        self.assertEqual(other['decision'],'Kept');self.assertTrue(self.project.dirty)
        self.assertTrue(receipt.exists());self.assertFalse((self.root/trim.JOURNAL).exists())

    def test_existing_original_backups_are_never_overwritten(self):
        deleted=self.root/'Deleted';deleted.mkdir(exist_ok=True)
        prior=deleted/'clip_ORIGINAL.mp4';prior.write_bytes(b'previous backup')
        self.assertEqual(trim.backup_path(self.project,self.clip).name,'clip_ORIGINAL_2.mp4')
        _,original,_=trim.install(self.project,self.clip,self.result)
        self.assertEqual(prior.read_bytes(),b'previous backup')
        self.assertTrue(original['path'].endswith('clip_ORIGINAL_2.mp4'))

    def test_publish_failure_rolls_back_source_and_project(self):
        rename=trim.rename_exclusive
        def fail(source,target):
            if target==self.source:raise OSError('simulated installation failure')
            return rename(source,target)
        with patch.object(trim,'rename_exclusive',side_effect=fail):
            with self.assertRaisesRegex(OSError,'simulated'):trim.install(self.project,self.clip,self.result)
        # Recovery uses the same rename helper, so retry after the interruption.
        trim.recover(self.root)
        self.assertEqual(self.source.read_bytes(),b'full original media')
        self.assertEqual(self.clip,self.before)
        self.assertEqual(len(self.project.data['clips']),2)

    def test_unsaved_transaction_is_recovered_on_project_open(self):
        backup=trim.backup_path(self.project,self.clip);backup.parent.mkdir(exist_ok=True)
        state={'schema':1,'id':'interrupted','source':self.clip['path'],
               'backup':str(backup.relative_to(self.root)),'original_sha256':self.result.source_checksum,
               'outputs':[{'path':self.clip['path'],'sha256':self.result.checksums[0]}]}
        atomic_json(self.root/trim.JOURNAL,state)
        self.source.rename(backup);self.source.write_bytes(self.staged.read_bytes())
        Project(self.root)
        self.assertEqual(self.source.read_bytes(),b'full original media')
        self.assertFalse(backup.exists());self.assertFalse((self.root/trim.JOURNAL).exists())

    def test_recovery_will_not_overwrite_unrecognized_media(self):
        backup=trim.backup_path(self.project,self.clip);backup.parent.mkdir(exist_ok=True)
        state={'schema':1,'id':'interrupted','source':self.clip['path'],
               'backup':str(backup.relative_to(self.root)),'original_sha256':self.result.source_checksum,
               'outputs':[{'path':self.clip['path'],'sha256':self.result.checksums[0]}]}
        atomic_json(self.root/trim.JOURNAL,state);self.source.rename(backup);self.source.write_bytes(b'externally changed')
        with self.assertRaisesRegex(ValueError,'changed file'):trim.recover(self.root)
        self.assertEqual(self.source.read_bytes(),b'externally changed')
        self.assertEqual(backup.read_bytes(),b'full original media')

    def test_source_changes_are_rejected_before_any_move(self):
        self.source.write_bytes(b'changed original')
        with self.assertRaisesRegex(ValueError,'source changed'):trim.install(self.project,self.clip,self.result)
        self.assertEqual(self.source.read_bytes(),b'changed original')
        self.assertFalse((self.root/trim.JOURNAL).exists())


if __name__=='__main__':unittest.main()
