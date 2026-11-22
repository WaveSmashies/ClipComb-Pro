# SPDX-License-Identifier: GPL-3.0-or-later
import ctypes as c,os,sys,tempfile,threading,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Settings
from review_cache_retention import expire_generated,AGE_SECONDS
from review_cancel import background_thread,capture,ScanCancelled
from review_marker_colors import palette,RESOLVE,PRESETS

class Review08Tests(unittest.TestCase):
    def test_expiry_keeps_recent_unowned_and_scan_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);now=time.time()
            def make(directory,name,data,age):
                path=root/directory/name;path.parent.mkdir(exist_ok=True);path.write_bytes(data)
                os.utime(path,(now-age,now-age));return path
            old=make('Generated Thumbnails','a'*32+'.jpg',b'thumbnail',AGE_SECONDS+1)
            fresh=make('Generated Thumbnails','b'*32+'.jpg',b'thumbnail',AGE_SECONDS-1)
            other=make('Generated Thumbnails','my-picture.jpg',b'personal',AGE_SECONDS+1)
            peaks=make('Generated Waveforms','c'*64+'.peaks',b'CRWV1data',AGE_SECONDS)
            invalid=make('Generated Waveforms','d'*64+'.peaks',b'not app data',AGE_SECONDS+1)
            progress=make('Cleanup Work','scan-cache.sqlite3',b'completed indexes',AGE_SECONDS+1)
            self.assertEqual(expire_generated(root,'thumbnails',now),1);self.assertFalse(old.exists())
            self.assertEqual(expire_generated(root,'waveform',now),1);self.assertFalse(peaks.exists())
            self.assertTrue(all(p.exists() for p in (fresh,other,invalid,progress)))

    def test_new_retention_defaults_and_old_palette_migrate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'ClipComb Pro.ini'
            path.write_text('[thumbnails]\ndelete_on_close=yes\n[bookmarks]\npalette=Resolve\n',encoding='utf-8')
            settings=Settings(temporary)
            for section in ('thumbnails','waveform'):
                self.assertTrue(settings.data.getboolean(section,'delete_after_30_days'))
                self.assertFalse(settings.data.getboolean(section,'delete_on_close'))
            self.assertEqual(settings.data['bookmarks']['palette'],'DaVinci Resolve')
            self.assertEqual(palette(settings.data['bookmarks']),RESOLVE);self.assertNotIn('Resolve',PRESETS)
            settings.data['thumbnails'].update(delete_on_close='yes',delete_after_30_days='no');settings.save()
            settings=Settings(temporary);self.assertTrue(settings.data.getboolean('thumbnails','delete_on_close'))
            self.assertFalse(settings.data.getboolean('thumbnails','delete_after_30_days'))

    @unittest.skipUnless(os.name=='nt','Windows process scheduling')
    def test_running_probe_changes_priority_and_remains_cancelable(self):
        cancel=threading.Event();cancel.background=True;errors=[]
        def run():
            try:
                with background_thread(cancel):capture([sys.executable,'-c','import time; time.sleep(8)'],cancel,capture_output=True,timeout=10)
            except BaseException as error:errors.append(error)
        worker=threading.Thread(target=run);worker.start()
        kernel=c.windll.kernel32;kernel.OpenProcess.argtypes=[c.c_uint32,c.c_int,c.c_uint32];kernel.OpenProcess.restype=c.c_void_p
        kernel.GetPriorityClass.argtypes=[c.c_void_p];kernel.GetPriorityClass.restype=c.c_uint32;kernel.CloseHandle.argtypes=[c.c_void_p]
        def priority():
            process=getattr(cancel,'current_process',None)
            if not process:return None
            handle=kernel.OpenProcess(0x1000,False,process.pid)
            if not handle:return None
            try:return kernel.GetPriorityClass(handle)
            finally:kernel.CloseHandle(handle)
        def wait_for(value):
            end=time.monotonic()+3
            while priority()!=value:
                self.assertLess(time.monotonic(),end,(priority(),value,errors));time.sleep(.01)
        try:
            wait_for(0x4000);cancel.background=False;wait_for(0x20)
            cancel.background=True;wait_for(0x4000)
        finally:cancel.set();worker.join(timeout=3)
        self.assertFalse(worker.is_alive());self.assertIsInstance(errors[0],ScanCancelled)

if __name__=='__main__':unittest.main()
