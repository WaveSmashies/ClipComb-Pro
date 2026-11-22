# SPDX-License-Identifier: GPL-3.0-or-later
"""Project folder safety, rollback, aliases, UI defaults and scan feedback."""
import copy,csv,io,json,os,sys,tempfile,unittest
from array import array
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Project,Settings,DEFAULT_KEYS,atomic_json
from review_folders import names,configure,validate,JOURNAL,categories,action_labels
from review_scan_feedback import display
from review_theme import PRESETS
from review_theme_files import light_palette
from review_overlap_audit import inventory
from review_buttons import title,HELP
from review_waveform import Waveforms,cache_key,write_peaks,read_peaks


class FolderTests(unittest.TestCase):
    def project(self,root):
        (root/'Unused/nested').mkdir(parents=True)
        (root/'Unused/nested/a.mp4').write_bytes(b'original recording bytes')
        (root/'Deleted').mkdir();(root/'Deleted/b.mp4').write_bytes(b'recoverable original')
        p=Project(root);p.save()
        return p

    def test_rename_extra_roles_persistence_and_other_project_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=self.project(root)
            before={c['id']:p.checked(c['path']).read_bytes() for c in p.data['clips']}
            values=dict(names(p),Unused='Inbox',Used='Selects',Kept='Favorites',Deleted='Trash',Extra1='Bloopers',Extra2='Maybe',Extra3='Later',Extra4='Test4')
            self.assertTrue(configure(p,values));p.save();reopened=Project(root)
            self.assertEqual(names(reopened),values)
            for clip in reopened.data['clips']:self.assertEqual(reopened.checked(clip['path']).read_bytes(),before[clip['id']])
            self.assertEqual(reopened.report_path('Unused/nested/a.mp4'),root/'Inbox/nested/a.mp4')
            self.assertEqual(reopened.report_path('Deleted/b.mp4'),root/'Trash/b.mp4')
            clip=next(c for c in reopened.data['clips'] if c['decision']=='Unused');clip['decision']='Extra4'
            ident=clip['id'];reopened.save();moved=next(c for c in reopened.data['clips'] if c['id']==ident)
            self.assertEqual(reopened.checked(moved['path']),root/'Test4/a.mp4')
            self.assertEqual(action_labels(reopened,{'extra1':'Extra'})['extra1'],'Move To Bloopers')
            self.assertIn('Maybe',categories(reopened))
            with self.assertRaisesRegex(ValueError,'Move clips out'):configure(reopened,{k:v for k,v in values.items() if k!='Extra4'})
            other=root/'Other';other.mkdir();self.assertEqual(names(Project(other)),dict(Unused='Unused',Used='Used',Kept='Kept',Deleted='Deleted'))

    def test_rename_updates_trim_receipt_without_changing_annotations(self):
        with tempfile.TemporaryDirectory() as temp:
            p=self.project(Path(temp));clip=p.data['clips'][0]
            clip['markers']=[dict(name='Unused/a joke',note='Deleted/not a path',time=1)]
            receipt=p.metadata/'clipcomb-trim-test.json'
            atomic_json(receipt,dict(source='Unused/nested/a.mp4',backup='Deleted/b.mp4',original_record=copy.deepcopy(clip)))
            configure(p,dict(names(p),Unused='Inbox',Deleted='Trash'))
            record=json.loads(receipt.read_text())
            self.assertEqual(record['source'],'Inbox/nested/a.mp4');self.assertEqual(record['backup'],'Trash/b.mp4')
            self.assertEqual(record['original_record']['markers'],clip['markers'])

    def test_swaps_and_interrupted_install_restore_all_originals(self):
        for interrupted in (False,True):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);p=self.project(root);original=os.rename;counter=[0]
                def rename(source,target):
                    counter[0]+=1
                    if interrupted and counter[0]==3:raise OSError('Injected interrupted folder rename')
                    return original(source,target)
                values=dict(names(p),Unused='Deleted',Deleted='Unused')
                if interrupted:
                    with patch('review_folders.os.rename',side_effect=rename),self.assertRaises(OSError):configure(p,values)
                    self.assertEqual((root/'Unused/nested/a.mp4').read_bytes(),b'original recording bytes')
                    self.assertEqual((root/'Deleted/b.mp4').read_bytes(),b'recoverable original')
                    self.assertFalse((p.metadata/JOURNAL).exists())
                else:
                    configure(p,values)
                    self.assertEqual((root/'Deleted/nested/a.mp4').read_bytes(),b'original recording bytes')
                    self.assertEqual((root/'Unused/b.mp4').read_bytes(),b'recoverable original')
                    self.assertEqual(p.report_path('Unused/nested/a.mp4'),root/'Deleted/nested/a.mp4')

    def test_folder_settings_preserve_unsaved_review_and_the_last_saved_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            p=self.project(Path(temp));clip=next(c for c in p.data['clips'] if c['decision']=='Unused');ident=clip['id']
            clip['ranges']=[dict(id='pending',start=1,end=2,enabled=True)];clip['decision']='Used';p.mark_review(clip)
            configure(p,dict(names(p),Unused='Inbox',Used='Selects'))
            current=next(c for c in p.data['clips'] if c['id']==ident)
            self.assertTrue(current['ranges']);self.assertEqual(current['decision'],'Used');self.assertTrue(p.review_changed)
            reopened=Project(p.root);checkpoint=next(c for c in reopened.data['clips'] if c['id']==ident)
            self.assertEqual(checkpoint['ranges'],[]);self.assertEqual(checkpoint['decision'],'Unused')
            self.assertTrue(reopened.checked(checkpoint['path']).is_file());self.assertEqual(names(reopened)['Unused'],'Inbox')

    def test_crash_recovery_before_and_after_metadata_commit(self):
        for commit in (False,True):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);p=self.project(root)
                old=copy.deepcopy(p.data);oldpath=root/'Unused';stage=root/'.clipcomb-folder-test-0';new=root/'Inbox'
                os.rename(oldpath,stage);os.rename(stage,new)
                state=dict(schema=1,phase='installing',transaction='test',moves=[dict(old='Unused',temp=stage.name,new='Inbox')],documents=[])
                atomic_json(p.metadata/JOURNAL,state)
                if commit:
                    p.data['folder_transaction']='test';p.data['folders']=dict(names(p),Unused='Inbox')
                    for clip in p.data['clips']:
                        if clip['path'].startswith('Unused'):clip['path']=clip['path'].replace('Unused','Inbox',1)
                    atomic_json(p.path,p.data)
                restored=Project(root)
                self.assertTrue((new if commit else oldpath).is_dir())
                self.assertFalse((p.metadata/JOURNAL).exists())
                self.assertTrue(all(not c['missing'] for c in restored.data['clips']))

    def test_reject_invalid_or_conflicting_names_and_exclude_custom_trash(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=self.project(root)
            for value in ('../outside','All','Stars','CON','Used',''):
                with self.assertRaises(ValueError):validate(dict(names(p),Deleted=value))
            (root/'Occupied').mkdir();(root/'Occupied/keep.txt').write_text('untouched')
            with self.assertRaises(ValueError):configure(p,dict(names(p),Unused='Occupied'))
            self.assertEqual((root/'Occupied/keep.txt').read_text(),'untouched')
            configure(p,dict(names(p),Deleted='Trash'))
            clips,_=inventory(root,exclude_folders=['Trash'])
            self.assertEqual(len(clips),1)

    def test_overlap_scope_uses_managed_folder_names_and_filters_legacy_links(self):
        from review_cleanup import Cleanup
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.project(root)
            configure(project, dict(names(project), Unused='Inbox', Deleted='Trash', Extra1='Bloopers'))
            for path in ('Bloopers/extra.mp4', 'Outside/folder.mp4', 'loose.mp4', 'Inbox/Replay Trim Recovery/backup.mp4'):
                file = root / path
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b'video fixture')
            project.scan()
            cleanup = Cleanup.__new__(Cleanup)
            cleanup.app = SimpleNamespace(project=project, populate=lambda: None)
            scoped, _ = inventory(root, include_folders=cleanup.overlap_folders())
            archive, _ = inventory(root)
            self.assertEqual({clip.path.name for clip in scoped}, {'a.mp4', 'extra.mp4'})
            self.assertEqual({clip.path.name for clip in archive}, {'a.mp4', 'b.mp4', 'extra.mp4', 'folder.mp4', 'loose.mp4'})
            self.assertFalse(inventory(root, include_folders=())[0])
            # A legacy report can mention an unmanaged path or a clip moved
            # into the Deleted folder since the report was written.
            project.data['clips'].append(dict(path='Outside/folder.mp4', decision='Unused', id='outside'))
            report = root / 'legacy.csv'
            with report.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, ['clip', 'matches'])
                writer.writeheader()
                writer.writerow(dict(clip='Unused/nested/a.mp4', matches=json.dumps([
                    dict(clip=path) for path in ('Bloopers/extra.mp4', 'Outside/folder.mp4', 'Deleted/b.mp4')
                ])))
            cleanup.read_groups(report)
            self.assertEqual(len(cleanup.groups), 1)
            self.assertEqual({Path(clip['path']).name for clip in project.data['clips'] if clip['id'] in cleanup.groups[0]},
                             {'a.mp4', 'extra.mp4'})


class OtherChanges(unittest.TestCase):
    def test_regenerate_bypasses_only_the_requested_waveform_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.mp4';path.write_bytes(b'recording unchanged')
            identity=dict(size=19);cache=Path(folder)/(cache_key('clip',identity,('all-streams-max-v1',1),50)+'.peaks')
            write_peaks(cache,array('H',[10]*50),50)
            wave=Waveforms(folder,'decoder')
            try:
                wave.request(path,'clip',identity,None,1,tracks=1);wave.worker.join(2)
                self.assertEqual(wave.poll()[3],'Cached waveform')
                class Decoder:
                    stdout=io.BytesIO(array('f',[.1]*8000).tobytes())
                    def poll(self):return 0
                    def wait(self):return 0
                with patch('review_waveform.subprocess.Popen',return_value=Decoder()) as decode:
                    wave.request(path,'clip',identity,None,1,tracks=1,force=True);wave.worker.join(2)
                    event=wave.poll();self.assertTrue(event[2]);self.assertGreater(min(event[1]),6000);decode.assert_called_once()
                self.assertGreater(min(read_peaks(cache,50)),6000)
                self.assertEqual(path.read_bytes(),b'recording unchanged')
            finally:wave.close()
    def test_defaults_and_scan_text(self):
        self.assertEqual(DEFAULT_KEYS['fast'],'Shift+2');self.assertEqual(DEFAULT_KEYS['slow'],'Shift+1')
        order=list(DEFAULT_KEYS);self.assertLess(order.index('slow'),order.index('fast'));self.assertLess(order.index('fast'),order.index('speed_1'))
        self.assertEqual(display('Indexed 105/946 · long name.mp4','Review priority')[0],'long name.mp4 · Indexed 105/946 · Review priority')
        self.assertEqual(display('Compared 2/4 clips')[1],84.5)
        self.assertEqual(title('Export to editing software'),'Export To Editing Software')
        self.assertIn('combined All Tracks',HELP['separate'])
    def test_grey_mann_matches_both_supplied_palettes(self):
        dark=PRESETS['Grey Mann'];light=light_palette(dark)
        self.assertEqual((dark['background'],dark['selection'],dark['waveform']),('#141414','#b9bfdf','#b3b5c8'))
        self.assertEqual((light['background'],light['highlighted_button'],light['waveform']),('#c0c0c7','#625c7e','#60617b'))


if __name__=='__main__':unittest.main()
