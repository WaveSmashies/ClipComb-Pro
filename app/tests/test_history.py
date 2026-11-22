# SPDX-License-Identifier: GPL-3.0-or-later
import copy,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from review_history import History,limit_value
from review_waveform import waveform_folder,delete_generated,write_peaks
from array import array
from review_resolve import covered

class HistoryTests(unittest.TestCase):
    def test_default_and_targeted_copies(self):
        h=History();self.assertEqual(h.limit,50)
        c={'id':'a','ranges':[{'start':i,'end':i+1} for i in range(10000)],'mix':[{'enabled':True,'volume':100}]}
        h.watch(c);baseline=h.baseline['ranges']
        for i in range(50):
            c['mix'][0]['volume']=i;h.record(c,fields=('mix',))
            self.assertIs(h.baseline['ranges'],baseline)
        self.assertLess(h.bytes,20000)
        c['ranges'][0]['end']=.5;h.record(c,fields=('ranges',))
        self.assertEqual(h.take()[1]['ranges'][0]['end'],1)
    def test_delta_undo_redo_and_new_edit(self):
        c={'id':'a','ranges':[],'decision':'Unused','mix':[]};h=History(200);h.watch(c)
        c['ranges']=[{'id':'r','start':1,'end':2}];h.record(c)
        c['decision']='Used';h.record(c)
        cid,fields=h.take();self.assertEqual(fields,{'decision':'Unused'});c.update(fields);h.watch(c)
        cid,fields=h.take(True);self.assertEqual(fields,{'decision':'Used'});c.update(fields);h.watch(c)
        c.update(h.take()[1]);h.watch(c);c['decision']='Kept';h.record(c)
        self.assertIsNone(h.take(True))
    def test_drag_coalesces_and_limits_do_not_preallocate(self):
        h=History('9'*100);self.assertEqual(h.limit,1000000);self.assertEqual(h.bytes,0)
        c={'id':'x','decision':'Unused','ranges':[{'id':'r','start':1,'end':3}]};h.watch(c)
        for value in range(2,100):c['ranges'][0]['start']=value;h.record(c,'one-drag')
        self.assertEqual(len(h.undo),1);self.assertEqual(h.take()[1]['ranges'][0]['start'],1)
        h=History(2,budget=500);h.watch(c)
        for i in range(100):c['decision']=str(i);h.record(c)
        self.assertLessEqual(h.bytes,500);self.assertLessEqual(len(h.undo),2)
    def test_cleanup_is_scoped_and_migrates(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);old=base/'cache/waveforms';old.mkdir(parents=True)
            write_peaks(old/('a'*64+'.peaks'),array('H',[1,2]),50)
            folder=waveform_folder(base);self.assertTrue((folder/('a'*64+'.peaks')).exists())
            other=folder/'keep.txt';other.write_text('personal file')
            delete_generated(base);self.assertTrue(other.exists());self.assertFalse(list(folder.glob('*.peaks')))
    def test_existing_range_coverage(self):
        self.assertTrue(covered([(0,100),(100,200)],30,180))
        self.assertFalse(covered([(0,99),(100,200)],30,180))
        self.assertFalse(covered([(10,50)],10,51))

if __name__=='__main__':unittest.main()
