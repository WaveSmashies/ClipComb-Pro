# SPDX-License-Identifier: GPL-3.0-or-later
"""Merges retain new identities, originals and recoverability across interruptions."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Project,atomic_json
from review_cleanup_core import hash_file,connection
from review_cleanup_core import archive_clip
import review_merge_install as merge_install
from review_cleanup_comparison import CompareView,Pane

@unittest.skipUnless(os.name=='nt','Windows protected file operations')
class MergeInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'Video';(self.root/'Unused').mkdir(parents=True)
        for name in ('a','b','other'):(self.root/'Unused'/f'{name}.mp4').write_bytes((name+' original').encode())
        self.project=Project(self.root);self.project.save();self.records=self.project.data['clips'][:2]
        self.ledger=Path(self.temp.name)/'Work';self.ledger.mkdir()
        self.staged=Path(self.temp.name)/'merged.mp4';self.staged.write_bytes(b'verified merged video')
        self.sources=tuple(archive_clip(self.root,c['path']) for c in self.records)
        self.merge=SimpleNamespace(clips=self.sources,path=self.staged,checksum=hash_file(self.staged),
                    original_checksums=tuple(hash_file(c.path) for c in self.sources),dependencies=(),dependency_files={},track_placements=[])
        self.record=copy.deepcopy(self.records[0]);self.record.update(markers=[dict(id='mark',time=3,name='Bookmark')],
                    provenance=[dict(source_id=c['id'],source_path=c['path'],start=0,end=10,output_start=i*5) for i,c in enumerate(self.records)])
    def install(self):return merge_install.install(self.project,self.merge,self.record,self.ledger)
    def test_original_name_merge_and_rollback(self):
        target=merge_install.output_path(self.project,self.merge,True)
        original=atomic_json
        def fail(path,data):
            if path==self.project.path:raise OSError('simulated')
            return original(path,data)
        with patch('review_core.atomic_json',side_effect=fail):
            with self.assertRaises(OSError):merge_install.install(self.project,self.merge,self.record,self.ledger,target=target)
        self.assertEqual(hash_file(target),self.merge.original_checksums[0])
        merged,_=merge_install.install(self.project,self.merge,self.record,self.ledger,target=target)
        self.assertEqual(self.project.checked(merged['path']),target)
        self.assertEqual(hash_file(target),self.merge.checksum)
        self.assertTrue(all(c['decision']=='Deleted' for c in self.project.data['clips'] if c['id'] in {r['id'] for r in self.records}))

    def test_new_clip_originals_and_unrelated_pending_changes_survive_reopen(self):
        other=self.project.data['clips'][2];other['decision']='Kept';self.project.dirty=True
        ids={c['id'] for c in self.records};merged,receipt=self.install()
        self.assertNotIn(merged['id'],ids);self.assertEqual(merged['decision'],'Unused');self.assertTrue(merged['merged_by_clipcomb'])
        self.assertEqual(merged['markers'][0]['name'],'Bookmark');self.assertEqual(len(self.project.data['clips']),4)
        for c in self.records:
            self.assertEqual(c['decision'],'Deleted');self.assertTrue(self.project.checked(c['path']).is_file());self.assertFalse(c['missing'])
        reopened=Project(self.root);new=next(c for c in reopened.data['clips'] if c['id']==merged['id'])
        self.assertTrue(new['merged_by_clipcomb']);self.assertEqual(reopened.checked(new['path']).read_bytes(),b'verified merged video')
        self.assertEqual(next(c for c in reopened.data['clips'] if c['id']==other['id'])['decision'],'Unused')
        self.assertEqual(other['decision'],'Kept');self.assertTrue(self.project.dirty);self.assertTrue(receipt.is_file())
        self.assertFalse((self.root/merge_install.JOURNAL).exists())
    def test_colliding_deleted_and_merged_names_are_preserved(self):
        (self.root/'Deleted').mkdir(exist_ok=True);(self.root/'Deleted/a.mp4').write_bytes(b'previous deleted')
        (self.root/'Unused/a_MERGED.mp4').write_bytes(b'previous merge')
        merged,_=self.install()
        self.assertEqual(Path(merged['path']).name,'a_MERGED_2.mp4');self.assertEqual(Path(self.records[0]['path']).name,'a_2.mp4')
        self.assertEqual((self.root/'Deleted/a.mp4').read_bytes(),b'previous deleted')
    def test_publish_failure_restores_all_originals(self):
        rename=merge_install.rename_exclusive
        def fail(source,target):
            if target.name.endswith('_MERGED.mp4'):raise OSError('simulated publish failure')
            return rename(source,target)
        with patch.object(merge_install,'rename_exclusive',side_effect=fail):
            with self.assertRaisesRegex(OSError,'simulated'):self.install()
        self.assertTrue(all(c.path.is_file() for c in self.sources));self.assertEqual(len(self.project.data['clips']),3)
        self.assertFalse((self.root/merge_install.JOURNAL).exists())
    def test_project_write_failure_rolls_back_media_and_records(self):
        original=atomic_json
        def fail(path,data):
            if path==self.project.path:raise OSError('simulated project write failure')
            return original(path,data)
        with patch('review_core.atomic_json',side_effect=fail):
            with self.assertRaisesRegex(OSError,'simulated'):self.install()
        self.assertTrue(all(c.path.is_file() for c in self.sources));self.assertTrue(all(c['decision']=='Unused' for c in self.records))
        self.assertEqual(len(Project(self.root).data['clips']),3)
    def make_interrupted(self,committed=False):
        target=merge_install.output_path(self.project,self.merge);backups=[]
        (self.root/'Deleted').mkdir(exist_ok=True)
        for c in self.sources:
            backup=self.root/'Deleted'/c.path.name;backups.append(backup);c.path.rename(backup)
        target.write_bytes(self.staged.read_bytes())
        state=dict(schema=1,id='interrupted',originals=[dict(source=str(c.path.relative_to(self.root)),backup=str(b.relative_to(self.root)),sha256=s)
                   for c,b,s in zip(self.sources,backups,self.merge.original_checksums)],output=dict(path=str(target.relative_to(self.root)),sha256=self.merge.checksum))
        atomic_json(self.root/merge_install.JOURNAL,state)
        if committed:
            saved=json.loads(self.project.path.read_text());saved['media_transaction']='interrupted';atomic_json(self.project.path,saved)
        return target,backups
    def test_restart_rolls_back_uncommitted_moves(self):
        target,backups=self.make_interrupted();Project(self.root)
        self.assertFalse(target.exists());self.assertTrue(all(c.path.is_file() for c in self.sources));self.assertFalse(any(b.exists() for b in backups))
    def test_restart_keeps_committed_media(self):
        target,backups=self.make_interrupted(True);merge_install.recover(self.root)
        self.assertTrue(target.exists());self.assertTrue(all(b.exists() for b in backups))
    def test_recovery_preserves_external_edits(self):
        target,backups=self.make_interrupted();self.sources[0].path.write_bytes(b'external media')
        with self.assertRaisesRegex(ValueError,'changed file'):Project(self.root)
        self.assertEqual(self.sources[0].path.read_bytes(),b'external media');self.assertTrue(target.exists());self.assertTrue(all(b.exists() for b in backups))
    def test_source_changed_after_verification_is_rejected(self):
        self.sources[1].path.write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError,'changed'):self.install()
        self.assertTrue(all(c.path.exists() for c in self.sources));self.assertFalse((self.root/merge_install.JOURNAL).exists())
    def test_prior_archive_dependencies_follow_complete_originals(self):
        from review_cleanup_merge import merge_dependencies
        details={'supports':[str(self.sources[0].path)],'original_identity':list(self.sources[1].file_id)}
        with connection(self.ledger) as db:
            db.execute('INSERT INTO review_actions VALUES (?,?,?,?,?,?,?)',('earlier','now','replace_original','old.mp4','backup.mp4','done',json.dumps(details)))
        self.merge.dependencies=merge_dependencies(self.ledger,self.sources)
        self.install()
        with connection(self.ledger) as db:
            after=json.loads(db.execute('SELECT details FROM review_actions WHERE id=?',('earlier',)).fetchone()[0])
        self.assertEqual(after['supports'],[str(self.project.checked(self.records[0]['path']))])
        self.assertEqual(after['original_identity'],details['original_identity'])

class CompareGainTests(unittest.TestCase):
    def test_identical_clips_sum_to_solo_amplitude_at_every_volume(self):
        class Player:
            def state(self):return 3
            def selected_track(self):return 1
            def set_muted(self,value):self.muted=value
            def set_volume(self,value):self.volume=value
        for count in (1,2,3,4):
            for volume in (25,60,100):
                view=SimpleNamespace(playing=True,running=set(range(count)),volume=volume,track_options=[[(1,'Sound')]]*count,
                       audio_choices={'original':0},track_key=lambda i:'original',audible=lambda i:True)
                players=[Player() for _ in range(count)];view.active=lambda:players
                CompareView.apply_audio(view)
                self.assertAlmostEqual(sum((p.volume/100)**3 for p in players),(volume/100)**3)
                self.assertTrue(all(not p.muted for p in players))

if __name__=='__main__':unittest.main()
