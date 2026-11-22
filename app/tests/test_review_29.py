# SPDX-License-Identifier: GPL-3.0-or-later
"""Project export scopes and one-action bulk sorting, including saved move Undo."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Project,read_json
from review_folders import names,configure,BASE
from review_folder_selection import ordered_folders,export_folders,remember_export_folders
from review_bulk_sort import move_marked,marked_clips
from review_history import History
from review_export import validate
from review_interchange import write_resolve_otio
from clip_review import ReviewApp


class FolderExportAndSort(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.p=Project(self.root);configure(self.p,dict(names(self.p),Extra1='Test1',Extra2='Spare'))
        for role,folder in self.p.folders().items():
            (folder/(role+'.mp4')).write_bytes(('source '+role).encode())
        self.p.scan()
        for c in self.p.data['clips']:
            c.update(media=dict(duration=8,fps=30,fps_fraction='30/1',audio=[]),
                ranges=[dict(id=c['id']+'r',start=1,end=3,enabled=c['decision']!='Extra1')],
                star=dict(title=c['decision'],color_slot=0))
        self.p.save();self.original={c['id']:c['decision'] for c in self.p.data['clips']}

    def app(self,limit=50):
        h=History(limit);current=self.p.data['clips'][0];h.watch(current)
        app=SimpleNamespace(project=self.p,history=h,clip=lambda:current,busy=False,loading=False,timeline=SimpleNamespace(drag=None),
            status=SimpleNamespace(set=Mock()),update_decision_buttons=Mock(),populate=Mock(),cleanup=SimpleNamespace(refresh_comparison=Mock(return_value=False)))
        def changed(**kwargs):self.p.dirty=True
        app.changed=changed
        return app

    def test_used_only_default_for_each_project_and_renamed_roles(self):
        self.assertEqual(list(ordered_folders(self.p)),['Used','Unused','Kept','Deleted','Extra1','Extra2'])
        self.assertEqual(export_folders(self.p),['Used'])
        path,count=self.p.export_ranges();payload=read_json(path)
        self.assertEqual(count,1);self.assertEqual([c['category'] for c in payload['clips']],['Used'])
        remember_export_folders(self.p,['Used','Kept','Extra1'])
        configure(self.p,dict(names(self.p),Used='Selects',Extra1='Renamed Test'))
        reopened=Project(self.root)
        self.assertEqual(export_folders(reopened),['Used','Kept','Extra1']);self.assertEqual(ordered_folders(reopened)['Extra1'],'Renamed Test')
        other=self.root/'Other';other.mkdir();self.assertEqual(export_folders(Project(other)),['Used'])

    def test_preferences_persist_without_committing_pending_marks_or_moves(self):
        c=next(c for c in self.p.data['clips'] if c['decision']=='Unused');path=self.p.checked(c['path'])
        c['decision']='Kept';c['ranges'][0]['end']=6;self.p.mark_review(c);self.p.dirty=True
        remember_export_folders(self.p,['Deleted','Extra1'])
        saved=read_json(self.p.path)
        saved_clip=next(row for row in saved['clips'] if row['id']==c['id'])
        self.assertEqual(saved_clip['decision'],'Unused');self.assertEqual(saved_clip['ranges'][0]['end'],3)
        self.assertEqual(export_folders(Project(self.root)),['Deleted','Extra1'])
        self.assertTrue(path.exists());self.assertTrue(self.p.review_changed)
        self.assertEqual(c['decision'],'Kept');self.assertEqual(c['ranges'][0]['end'],6)

    def test_deleted_requires_explicit_selection_and_carries_to_resolve_writer(self):
        path,count=self.p.export_ranges(['Deleted']);payload=read_json(path)
        self.assertEqual(count,1);self.assertEqual([c['category'] for c in validate(payload)],['Deleted'])
        output=self.root/'scope.otio';write_resolve_otio(payload,output)
        self.assertIn('Deleted.mp4',output.read_text());self.assertNotIn('Unused.mp4',output.read_text())
        legacy=dict(payload);legacy.pop('export_folders')
        with self.assertRaisesRegex(ValueError,'no enabled'):validate(legacy)
        payload['export_folders']=['Used']
        with self.assertRaises(ValueError):validate(payload)

    def test_empty_selection_and_removed_custom_folder_remain_unchecked(self):
        remember_export_folders(self.p,[]);self.assertEqual(export_folders(Project(self.root)),[])
        path,count=self.p.export_ranges();self.assertEqual(count,0)
        with self.assertRaises(ValueError):validate(read_json(path))
        remember_export_folders(self.p,['Extra2'])
        c=next(c for c in self.p.data['clips'] if c['decision']=='Extra2');c['decision']='Unused';self.p.save()
        configure(self.p,{k:v for k,v in names(self.p).items() if k!='Extra2'})
        configure(self.p,dict(names(self.p),Extra2='New Folder'))
        self.assertEqual(export_folders(self.p),[])

    def test_bulk_target_and_sources_one_undo_redo_preserve_annotations(self):
        app=self.app();before={c['id']:copy.deepcopy(c) for c in self.p.data['clips']}
        self.assertEqual(move_marked(app,['Unused','Extra1'],'Kept'),2)
        self.assertEqual(len(app.history.undo),1)
        self.assertTrue(self.p.review_changed)
        for c in self.p.data['clips']:
            self.assertEqual(c['decision'],'Kept' if self.original[c['id']] in ('Unused','Extra1') else self.original[c['id']])
            self.assertEqual(c['ranges'],before[c['id']]['ranges']);self.assertEqual(c['star'],before[c['id']]['star'])
            self.assertTrue(self.p.checked(c['path']).is_file())
        ReviewApp.undo_review(app)
        self.assertEqual({c['id']:c['decision'] for c in self.p.data['clips']},self.original)
        self.assertFalse(self.p.review_changed)
        ReviewApp.undo_review(app,True)
        self.assertEqual(sum(c['decision']=='Kept' for c in self.p.data['clips']),3)

    def test_saved_bulk_move_undo_stages_return_without_moving_until_save(self):
        app=self.app();c=next(c for c in self.p.data['clips'] if c['decision']=='Unused');original=self.p.checked(c['path']);content=original.read_bytes()
        move_marked(app,['Unused'],'Extra1');self.assertTrue(original.exists())
        self.p.save()
        c=next(row for row in self.p.data['clips'] if row['id']==c['id']);moved=self.p.checked(c['path'])
        self.assertEqual(moved.parent.name,'Test1');self.assertFalse(original.exists())
        ReviewApp.undo_review(app);self.assertTrue(moved.exists());self.assertFalse(original.exists())
        self.p.save();self.assertEqual(original.read_bytes(),content)

    def test_missing_and_bookmark_only_are_excluded_and_noop_keeps_history(self):
        app=self.app();c=next(c for c in self.p.data['clips'] if c['decision']=='Unused')
        c['ranges']=[];c['markers']=[dict(time=1,name='Bookmark')]
        other=next(c for c in self.p.data['clips'] if c['decision']=='Extra1');other['missing']=True
        self.assertEqual(marked_clips(self.p,['Unused','Extra1']),[])
        self.assertEqual(move_marked(app,['Unused','Extra1'],'Used'),0);self.assertFalse(app.history.undo)

    def test_bulk_failure_keeps_decisions_and_other_window_preferences_rejected(self):
        app=self.app(limit=0)
        with self.assertRaisesRegex(ValueError,'Undo history'):move_marked(app,['Unused'],'Used')
        with self.assertRaises(ValueError):move_marked(app,['Unused'],'Not a role')
        self.assertEqual({c['id']:c['decision'] for c in self.p.data['clips']},self.original)
        other=Project(self.root);remember_export_folders(other,['Unused'])
        with self.assertRaisesRegex(ValueError,'another window'):remember_export_folders(self.p,['Kept'])


class BatchHistoryTests(unittest.TestCase):
    def test_batch_is_bounded_can_forget_one_member_and_clears_redo(self):
        h=History(2);h.record_decisions({'a':['Unused','Used'],'b':['Kept','Used']},'Move Marked Clips To Used')
        self.assertLess(h.bytes,1000);h.forget('a')
        self.assertEqual(h.take(),(None,{'decisions':{'b':'Kept'}}))
        c=dict(id='x',decision='Unused',ranges=[]);h.watch(c);c['decision']='Used';h.record(c)
        self.assertIsNone(h.take(True));self.assertEqual(h.take()[0],'x')


if __name__=='__main__':unittest.main()
