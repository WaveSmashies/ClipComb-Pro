# SPDX-License-Identifier: GPL-3.0-or-later
"""Trim recovery and canceled copies must never lose or overwrite recordings."""
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
from review_trim_install import install
import review_trim_undo as recovery


class TrimUndoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'Unused').mkdir()
        self.source=self.root/'Unused/clip.mp4';self.source.write_bytes(b'full original')
        self.project=Project(self.root);self.clip=self.project.data['clips'][0]
        self.clip.update(media={'duration':10,'audio':[]},ranges=[dict(id='r',start=1,end=3,enabled=True)],markers=[])
        self.project.save();self.clip=self.project.data['clips'][0];self.before=copy.deepcopy(self.clip)
        self.stage=self.root/'output.tmp';self.stage.write_bytes(b'trimmed copy')
        self.result=SimpleNamespace(paths=[self.stage],checksums=[hash_file(self.stage)],source_checksum=hash_file(self.source),
            source_identity=identity(self.source.lstat()),mappings=[[(1,3,0)]],metadata=[{'duration':2,'audio':[]}],details=[{}])

    def test_restore_after_reopen_and_sort(self):
        outputs,original,_=install(self.project,self.clip,self.result,original_name=False)
        outputs[0]['decision']='Kept';self.project.save()
        reopened=Project(self.root);clip=next(c for c in reopened.data['clips'] if c['id']==self.clip['id'])
        restored=recovery.undo(reopened,clip)
        self.assertEqual(self.source.read_bytes(),b'full original')
        self.assertEqual(restored['path'],self.before['path']);self.assertEqual(restored['ranges'],self.before['ranges'])
        self.assertNotIn('trimmed_by_clipcomb',restored)
        self.assertTrue(restored['trim_undone'])
        discarded=[c for c in reopened.data['clips'] if c['decision']=='Deleted']
        self.assertEqual(len(discarded),1)
        self.assertEqual(reopened.checked(discarded[0]['path']).read_bytes(),b'trimmed copy')
        self.assertTrue(discarded[0]['trimmed_by_clipcomb']);self.assertIsNone(recovery.receipt_for(reopened,discarded[0]))
        self.assertEqual(len(Project(self.root).data['clips']),2)

    def test_original_name_and_split_outputs(self):
        second=self.root/'second.tmp';second.write_bytes(b'second trimmed copy')
        self.result.paths.append(second);self.result.checksums.append(hash_file(second))
        self.result.mappings.append([(4,6,0)]);self.result.metadata.append({'duration':2,'audio':[]})
        outputs,_,_=install(self.project,self.clip,self.result,original_name=True)
        recovery.undo(self.project,outputs[1])
        self.assertEqual(self.source.read_bytes(),b'full original')
        self.assertEqual(len([c for c in self.project.data['clips'] if c['decision']=='Deleted']),2)

    def test_occupied_original_name_refuses(self):
        install(self.project,self.clip,self.result,original_name=False)
        self.source.write_bytes(b'other recording')
        with self.assertRaisesRegex(ValueError,'occupied'):recovery.undo(self.project,self.clip)
        self.assertEqual(self.source.read_bytes(),b'other recording')

    def test_failed_save_rolls_back_all_moves(self):
        install(self.project,self.clip,self.result,original_name=True)
        before=copy.deepcopy(self.project.data)
        def fail(path,data):
            if path==self.project.path:raise OSError('simulated save failure')
            atomic_json(path,data)
        with patch('review_core.atomic_json',side_effect=fail):
            with self.assertRaisesRegex(OSError,'simulated'):recovery.undo(self.project,self.clip)
        self.assertEqual(self.source.read_bytes(),b'trimmed copy')
        self.assertEqual(self.project.data,before)
        self.assertFalse((self.project.metadata/recovery.JOURNAL).exists())
        recovery.undo(self.project,self.clip)
        self.assertEqual(self.source.read_bytes(),b'full original')

    def test_changed_trim_is_not_moved(self):
        install(self.project,self.clip,self.result,original_name=True)
        self.source.write_bytes(b'external change')
        with self.assertRaisesRegex(ValueError,'changed'):recovery.undo(self.project,self.clip)
        self.assertEqual(self.source.read_bytes(),b'external change')

    def test_legacy_receipt_recognized(self):
        outputs,_,receipt=install(self.project,self.clip,self.result,original_name=False)
        data=json.loads(receipt.read_text());data.pop('original_record');atomic_json(receipt,data)
        self.clip.pop('trim_transaction');self.clip.pop('trimmed_by_clipcomb');self.project.persist_metadata()
        reopened=Project(self.root);clip=next(c for c in reopened.data['clips'] if c['id']==self.clip['id'])
        self.assertTrue(clip['trimmed_by_clipcomb']);recovery.undo(reopened,clip)
        self.assertEqual(self.source.read_bytes(),b'full original')

    def test_canceled_copy_goes_to_deleted_without_touching_original(self):
        first=recovery.discard(self.project,self.clip,self.result)[0]
        second=recovery.discard(self.project,self.clip,self.result)[0]
        self.assertNotEqual(first,second)
        self.assertEqual(first.read_bytes(),b'trimmed copy');self.assertEqual(second.read_bytes(),b'trimmed copy')
        self.assertEqual(self.source.read_bytes(),b'full original')
        deleted=[c for c in Project(self.root).data['clips'] if c['decision']=='Deleted']
        self.assertEqual(len(deleted),2);self.assertTrue(all(c['trimmed_by_clipcomb'] for c in deleted))

    def test_interrupted_undo_recovers_on_project_open(self):
        _,original,_=install(self.project,self.clip,self.result,original_name=True)
        destination=self.root/'Deleted/canceled-trim.mp4'
        moves=[{'from':self.clip['path'],'to':str(destination.relative_to(self.root)),'sha256':self.result.checksums[0]},
               {'from':original['path'],'to':self.before['path'],'sha256':self.result.source_checksum}]
        atomic_json(self.project.metadata/recovery.JOURNAL,dict(schema=1,id='interrupted',moves=moves))
        self.source.rename(destination)
        self.project.checked(original['path']).rename(self.source)
        reopened=Project(self.root)
        self.assertEqual(self.source.read_bytes(),b'trimmed copy')
        self.assertEqual(reopened.checked(original['path']).read_bytes(),b'full original')
        self.assertFalse(destination.exists())

    def test_previous_build_undo_is_recognized(self):
        install(self.project,self.clip,self.result,original_name=False)
        restored=recovery.undo(self.project,self.clip)
        restored.pop('trim_undone');self.project.persist_metadata()
        reopened=Project(self.root)
        self.assertTrue(next(c for c in reopened.data['clips'] if c['id']==restored['id'])['trim_undone'])

    def test_pending_other_review_edits_are_not_committed_by_undo(self):
        other=self.root/'Unused/other.mp4';other.write_bytes(b'other recording')
        self.project.scan();self.project.save();self.clip=next(c for c in self.project.data['clips'] if c['path']==self.before['path'])
        install(self.project,self.clip,self.result,original_name=False)
        pending=next(c for c in self.project.data['clips'] if c['path'].endswith('other.mp4'))
        pending['decision']='Kept';self.project.mark_review(pending)
        recovery.undo(self.project,self.clip)
        self.assertEqual(pending['decision'],'Kept')
        reopened=Project(self.root)
        self.assertEqual(next(c for c in reopened.data['clips'] if c['id']==pending['id'])['decision'],'Unused')


if __name__=='__main__':unittest.main()
