# SPDX-License-Identifier: GPL-3.0-or-later
"""External folder moves and removal of empty, stale extra destinations."""
import copy,os,shutil,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Project,atomic_json,file_identity
from review_folders import BASE,names,configure


class FolderRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'Unused').mkdir();(self.root/'Test1').mkdir()
        self.original=self.root/'Test1'/'tutorial.mp4';self.original.write_bytes(b'original clip bytes')
        self.project=Project(self.root)
        configure(self.project,dict(names(self.project),Extra1='Test1'))
        self.clip=self.project.data['clips'][0]
        self.clip.update(star=dict(title='Keep this star',color_slot=2),position=12.,
            markers=[dict(id='b',time=2,name='Bookmark',color_slot=0)],
            ranges=[dict(id='r',start=1,end=3,enabled=True)],reviewed=True)
        self.project.save();self.ident=self.clip['id']

    def moved(self):
        target=self.root/'Unused'/self.original.name
        self.original.rename(target);self.original.parent.rmdir()
        return target

    def remove_extra(self,project=None):
        project=project or self.project
        return configure(project,{k:v for k,v in names(project).items() if k in BASE})

    def test_external_move_preserves_review_and_removal_survives_restart(self):
        target=self.moved();before=target.read_bytes()
        self.assertTrue(self.remove_extra())
        reopened=Project(self.root);self.assertEqual(len(reopened.data['clips']),1)
        clip=reopened.data['clips'][0]
        self.assertEqual(clip['id'],self.ident);self.assertEqual(clip['decision'],'Unused')
        self.assertEqual(reopened.checked(clip['path']),target);self.assertFalse(clip['missing'])
        self.assertEqual(clip['star']['title'],'Keep this star');self.assertEqual(clip['position'],12.)
        self.assertEqual(clip['markers'][0]['name'],'Bookmark');self.assertEqual(clip['ranges'][0]['end'],3)
        reopened.save();self.assertFalse((self.root/'Test1').exists())
        self.assertEqual(target.read_bytes(),before)

    def test_repairs_existing_missing_row_and_pristine_rescan_duplicate(self):
        target=self.moved();data=copy.deepcopy(self.project.data)
        data['clips'][0]['missing']=True
        data['clips'].append(dict(id='rescan-placeholder',path=str(target.relative_to(self.root)),decision='Unused',
            ranges=[],position=0,media=None,mix=[],identity=file_identity(target),missing=False))
        data['current_clip']='rescan-placeholder';atomic_json(self.project.path,data)
        reopened=Project(self.root)
        self.assertEqual([c['id'] for c in reopened.data['clips']],[self.ident])
        self.assertEqual(reopened.data['current_clip'],self.ident)
        self.assertEqual(reopened.data['clips'][0]['star'],data['clips'][0]['star'])
        self.remove_extra(reopened)
        self.assertEqual([c['id'] for c in Project(self.root).data['clips']],[self.ident])

    def test_deleted_source_keeps_annotations_without_blocking_folder_removal(self):
        self.original.unlink();self.original.parent.rmdir()
        self.remove_extra();self.project.save()
        clip=Project(self.root).data['clips'][0]
        self.assertTrue(clip['missing']);self.assertEqual(clip['decision'],'Unused')
        self.assertEqual(clip['star']['title'],'Keep this star')
        self.assertFalse((self.root/'Test1').exists())

    def test_empty_nested_directories_do_not_block_and_are_not_deleted(self):
        self.moved();nested=self.root/'Test1'/'Unused'/'empty';nested.mkdir(parents=True)
        for name in ('Used','Kept','Deleted'):(self.root/'Test1'/name).mkdir()
        self.remove_extra()
        self.assertTrue(nested.is_dir());self.assertNotIn('Extra1',names(Project(self.root)))

    def test_real_content_and_pending_sorting_decision_still_block(self):
        with self.assertRaisesRegex(ValueError,'Move clips out'):self.remove_extra()
        self.moved();(self.root/'Test1').mkdir();note=self.root/'Test1'/'keep.txt';note.write_text('keep')
        with self.assertRaisesRegex(ValueError,'Move clips out'):self.remove_extra()
        note.unlink();self.project.data['clips'][0]['decision']='Extra1'
        with self.assertRaisesRegex(ValueError,'Move clips out'):self.remove_extra()

    def test_folder_settings_do_not_commit_pending_marks_or_sorting(self):
        target=self.moved();clip=self.project.data['clips'][0]
        clip['ranges'][0]['end']=8;clip['decision']='Used';self.project.mark_review(clip)
        self.remove_extra();current=self.project.data['clips'][0]
        self.assertEqual(current['ranges'][0]['end'],8);self.assertEqual(current['decision'],'Used')
        self.assertTrue(self.project.review_changed);self.assertTrue(target.exists())
        saved=Project(self.root).data['clips'][0]
        self.assertEqual(saved['ranges'][0]['end'],3);self.assertEqual(saved['decision'],'Unused')

    def test_ambiguous_copies_are_not_reconnected_to_the_wrong_clip(self):
        target=self.moved();(self.root/'Used').mkdir(exist_ok=True)
        shutil.copy2(target,self.root/'Used'/target.name)
        self.remove_extra();clips=self.project.data['clips']
        self.assertEqual(len(clips),3)
        missing=next(c for c in clips if c['id']==self.ident)
        self.assertTrue(missing['missing']);self.assertEqual(missing['star']['title'],'Keep this star')
        self.assertEqual(sum(not c['missing'] for c in clips),2)

    def test_changed_media_and_separately_reviewed_duplicates_are_kept(self):
        target=self.moved();target.write_bytes(b'different replacement bytes')
        self.project.scan();self.assertEqual(len(self.project.data['clips']),2)
        self.assertTrue(next(c for c in self.project.data['clips'] if c['id']==self.ident)['missing'])
        target.write_bytes(b'original clip bytes')
        original=next(c for c in self.project.data['clips'] if c['id']==self.ident)
        identity=original['identity'];os.utime(target,ns=(identity['mtime_ns'],identity['mtime_ns']))
        other=next(c for c in self.project.data['clips'] if c['id']!=self.ident)
        other.update(identity=identity,star=dict(title='Independent review',color_slot=4))
        self.project.persist_metadata()
        self.remove_extra();reopened=Project(self.root)
        self.assertEqual(len(reopened.data['clips']),2)
        self.assertEqual({c['star']['title'] for c in reopened.data['clips']},{'Keep this star','Independent review'})


if __name__=='__main__':unittest.main()
