# SPDX-License-Identifier: GPL-3.0-or-later
"""Project documents, naming and deletion must not move or alter recordings."""
import copy,json,os,shutil,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Settings,Project,PROJECT_FILE,JOURNAL_FILE,atomic_json,file_identity
from review_projects import ProjectStore,JOURNALS,name_value

class PortableProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.app=self.folder/'App';self.app.mkdir()
        self.video=self.folder/'Recordings';(self.video/'Unused').mkdir(parents=True)
        for name in ('a.mp4','b.mp4'):(self.video/'Unused'/name).write_bytes((name+' original').encode())
        (self.video/'notes.txt').write_text('User notes',encoding='utf-8')
        self.settings=Settings(self.app);self.settings.save();self.store=ProjectStore(self.settings)
    def snapshot(self):
        return {str(p.relative_to(self.video)):(p.read_bytes(),p.stat().st_mtime_ns) for p in self.video.rglob('*') if p.is_file()}
    def item(self,project):return dict(root=str(project.root),name=project.data['name'],project_file=str(project.path.relative_to(self.app)))
    def test_create_writes_readable_project_only_beside_app(self):
        before=self.snapshot();p=self.store.open(self.video,'My video')
        self.assertEqual(self.snapshot(),before);self.assertEqual(p.path.parent,self.app/'Projects')
        data=json.loads(p.path.read_text(encoding='utf-8'));self.assertEqual(data['name'],'My video')
        self.assertEqual(Path(data['video_root']),self.video);self.assertEqual(len(data['clips']),2)
        self.assertFalse((self.video/PROJECT_FILE).exists());self.assertFalse((self.video/'Used').exists())
        self.assertEqual(len(list((self.app/'Projects').glob('*.clipcomb.json'))),1)
    def test_rename_keeps_unsaved_decisions_staged_and_never_sorts(self):
        p=self.store.open(self.video);before=self.snapshot();old=p.path
        p.data['clips'][0]['decision']='Used';p.mark_review(p.data['clips'][0]);p.dirty=True
        with patch.object(Project,'save',side_effect=AssertionError('Rename must not save/sort media')):
            new=self.store.rename(self.item(p),'Renamed project',p)
        self.assertEqual(p.path,new);self.assertFalse(old.exists());self.assertEqual(self.snapshot(),before)
        self.assertEqual(json.loads(new.read_text())['clips'][0]['decision'],'Unused')
        self.assertEqual(p.data['clips'][0]['decision'],'Used');self.assertTrue(p.review_changed)
        self.assertEqual(self.store.open(self.video).data['name'],'Renamed project')
    def test_remove_discards_project_only_even_with_pending_sorting(self):
        p=self.store.open(self.video);self.settings.register(self.video,p.data['name'],p.path)
        p.data['clips'][0]['decision']='Deleted';before=self.snapshot()
        with patch.object(Project,'save',side_effect=AssertionError('Delete must not save/sort media')):self.store.remove(self.item(p))
        self.assertEqual(self.snapshot(),before);self.assertFalse(p.path.exists());self.assertEqual(self.store.entries(),[])
        self.assertEqual(self.settings.data['app']['last_project'],'')
    def test_manual_file_removal_is_respected(self):
        p=self.store.open(self.video);self.settings.register(self.video,p.data['name'],p.path);p.path.unlink()
        self.assertEqual(self.store.entries(),[])
        fresh=self.store.open(self.video);self.assertTrue(fresh.path.exists());self.assertEqual(len(fresh.data['clips']),2)
    def test_migrate_legacy_document_and_receipt_preserves_media_and_annotations(self):
        legacy=Project(self.video,'Old project');legacy.data['clips'][0]['markers']=[dict(id='m',name='Keep',time=2)];legacy.save()
        receipt=self.video/'clipcomb-trim-old.json';atomic_json(receipt,dict(source='Unused/a.mp4',copies=[],verification=[]))
        unrelated=self.video/'clipcomb-trim-personal.json';atomic_json(unrelated,dict(my_notes='Keep this file'))
        before={p.name:p.read_bytes() for p in (self.video/'Unused').iterdir()}
        self.settings.register(self.video,'Old project')
        p=self.store.open(self.video)
        self.assertFalse((self.video/PROJECT_FILE).exists());self.assertFalse(receipt.exists());self.assertTrue(unrelated.exists())
        self.assertEqual(p.data['clips'][0]['markers'][0]['name'],'Keep');self.assertTrue((p.metadata/receipt.name).exists())
        self.assertEqual({p.name:p.read_bytes() for p in (self.video/'Unused').iterdir()},before)
    def test_duplicate_names_and_filename_characters_are_safe(self):
        first=self.store.open(self.video,'Name / with : symbols')
        other=self.folder/'Other';(other/'Unused').mkdir(parents=True)
        second=self.store.open(other,'Name / with : symbols')
        self.assertNotEqual(first.path,second.path);self.assertEqual(len(self.store.entries()),2)
        self.assertEqual(first.path.parent,self.store.folder)
    def test_shared_document_can_relink_to_copied_video_folder(self):
        p=self.store.open(self.video,'Shared review');p.data['clips'][0]['markers']=[dict(id='m',name='Bookmark',time=2)];p.persist_metadata()
        shared=self.folder/'Shared.clipcomb.json';shutil.copy2(p.path,shared)
        other=self.folder/'Friend clips';shutil.copytree(self.video,other)
        imported=self.store.import_file(shared,other);opened=self.store.open(other,project_file=imported)
        self.assertEqual(opened.root,other);self.assertNotEqual(opened.data['project_id'],p.data['project_id'])
        self.assertEqual(opened.data['clips'][0]['markers'][0]['name'],'Bookmark');self.assertTrue(shared.exists())
    def test_portable_save_journal_recovers_without_a_video_side_project_file(self):
        p=self.store.open(self.video);source=self.video/p.data['clips'][0]['path'];destination=self.video/'Used'/source.name;destination.parent.mkdir()
        atomic_json(p.metadata/JOURNAL_FILE,dict(transaction='interrupted',moves=[dict(src=str(source.relative_to(self.video)),dst=str(destination.relative_to(self.video)),identity=file_identity(source))]))
        source.rename(destination);self.store.open(self.video)
        self.assertTrue(source.exists());self.assertFalse(destination.exists());self.assertFalse((p.metadata/JOURNAL_FILE).exists())
        self.assertFalse((self.video/JOURNAL_FILE).exists())
    def test_pending_recovery_prevents_removal_and_relink(self):
        p=self.store.open(self.video);atomic_json(p.metadata/JOURNALS[1],{})
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'interrupted'):self.store.remove(self.item(p))
        with self.assertRaisesRegex(ValueError,'interrupted'):self.store.rename(self.item(p),'New name',p)
        other=self.folder/'Elsewhere';other.mkdir()
        with self.assertRaisesRegex(ValueError,'interrupted'):self.store.open(other,project_file=p.path)
        self.assertTrue(p.path.exists());self.assertEqual(self.snapshot(),before)
    def test_rename_write_failure_restores_original_document(self):
        p=self.store.open(self.video);old=p.path;before=old.read_bytes();writer=atomic_json
        calls=[]
        def fail_once(path,data):
            calls.append(path)
            if len(calls)==1:raise OSError('simulated write failure')
            return writer(path,data)
        with patch('review_projects.atomic_json',side_effect=fail_once):
            with self.assertRaisesRegex(OSError,'simulated'):self.store.rename(self.item(p),'New name',p)
        self.assertEqual(old.read_bytes(),before);self.assertEqual(p.path,old)
    def test_delete_rejects_paths_outside_the_store(self):
        p=self.store.open(self.video);before=self.snapshot()
        with self.assertRaises(ValueError):self.store.remove(dict(root=str(self.video),project_file='../Outside.clipcomb.json'))
        self.assertTrue(p.path.exists());self.assertEqual(self.snapshot(),before)
    def test_malformed_identifiers_and_blank_names_are_rejected(self):
        p=self.store.open(self.video);data=json.loads(p.path.read_text());data['project_id']='../outside';atomic_json(p.path,data)
        with self.assertRaisesRegex(ValueError,'identifier'):self.store.open(self.video,project_file=p.path)
        for name in ('','   ','bad\nname','x'*121):
            with self.assertRaises(ValueError):name_value(name)
    def test_manual_document_copy_is_found_without_registry(self):
        p=self.store.open(self.video);self.assertEqual(self.settings.projects(),[])
        self.assertEqual(self.store.entries()[0]['name'],p.data['name'])
    def test_missing_videos_do_not_prevent_rename_or_delete(self):
        p=self.store.open(self.video);self.video.rename(self.folder/'Unplugged')
        new=self.store.rename(self.item(p),'Offline project')
        self.store.remove(dict(root=str(self.video),name='Offline project',project_file=str(new.relative_to(self.app))))
        self.assertFalse(new.exists());self.assertTrue((self.folder/'Unplugged/Unused/a.mp4').exists())
    def test_failed_metadata_write_keeps_transaction_usable(self):
        p=self.store.open(self.video);before=p.data['transaction']
        with patch('review_core.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):p.persist_metadata()
        self.assertEqual(p.data['transaction'],before);p.persist_metadata()
    def test_read_only_legacy_metadata_is_not_resurrected_after_deletion(self):
        legacy=Project(self.video,'Read-only old project');legacy.data['clips'][0]['markers']=[dict(id='m',time=1,name='Old bookmark')];legacy.save()
        source=self.video/PROJECT_FILE;unlink=Path.unlink
        def locked(path,*args,**kwargs):
            if path==source:raise PermissionError('read-only legacy metadata')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',locked):
            p=self.store.open(self.video);self.assertTrue(source.exists());self.store.remove(self.item(p))
            fresh=self.store.open(self.video)
        self.assertFalse(fresh.data['clips'][0].get('markers'));self.assertTrue(source.exists())
    @unittest.skipUnless(os.name=='nt','Windows file installation')
    def test_trim_receipts_and_recovery_stay_with_portable_project(self):
        from review_cleanup_core import hash_file
        from review_overlap_audit import identity
        from review_trim_install import install
        p=self.store.open(self.video);clip=p.data['clips'][0];source=p.checked(clip['path'])
        staged=self.folder/'verified.mp4';staged.write_bytes(b'verified trimmed media')
        result=SimpleNamespace(paths=[staged],checksums=[hash_file(staged)],source_checksum=hash_file(source),source_identity=identity(source.lstat()),
                    mappings=[[(2,8,0)]],metadata=[dict(duration=6,fps=30,audio=[])],details=[{}])
        outputs,original,receipt=install(p,clip,result)
        self.assertEqual(receipt.parent,p.metadata);self.assertFalse(list(self.video.glob('clipcomb-*.json')))
        self.assertFalse(any((self.video/name).exists() for name in JOURNALS));self.assertFalse((self.video/PROJECT_FILE).exists())
        opened=self.store.open(self.video);self.assertEqual(len(opened.data['clips']),3)
        before=self.snapshot();self.store.remove(self.item(opened));self.assertEqual(self.snapshot(),before)
        self.assertTrue(p.checked(original['path']).exists());self.assertTrue(p.checked(outputs[0]['path']).exists())

if __name__=='__main__':unittest.main()
