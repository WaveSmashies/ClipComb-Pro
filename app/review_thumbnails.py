# SPDX-License-Identifier: GPL-3.0-or-later
"""Visible-only thumbnails: reuse Windows' cache, then decode one small frame."""
import ctypes as c
from ctypes import wintypes as w
import hashlib,io,json,os
from pathlib import Path
from queue import LifoQueue,Queue
import subprocess,threading
from PIL import Image,ImageOps

def windows_thumbnail(path):
    if os.name!='nt':return None
    class GUID(c.Structure):_fields_=[('a',w.DWORD),('b',w.WORD),('d',w.WORD),('rest',c.c_ubyte*8)]
    class SIZE(c.Structure):_fields_=[('cx',w.LONG),('cy',w.LONG)]
    class BITMAP(c.Structure):_fields_=[('type',w.LONG),('width',w.LONG),('height',w.LONG),('row',w.LONG),('planes',w.WORD),('bits',w.WORD),('data',c.c_void_p)]
    class HEADER(c.Structure):_fields_=[('size',w.DWORD),('width',w.LONG),('height',w.LONG),('planes',w.WORD),('bits',w.WORD),('compression',w.DWORD),('bytes',w.DWORD),('x',w.LONG),('y',w.LONG),('used',w.DWORD),('important',w.DWORD)]
    import uuid
    guid=GUID.from_buffer_copy(uuid.UUID('bcc18b79-ba16-442f-80c4-8a59c30c463b').bytes_le)
    ole,shell,gdi,user=c.windll.ole32,c.windll.shell32,c.windll.gdi32,c.windll.user32
    initialized=ole.CoInitializeEx(None,2);factory=c.c_void_p();bitmap=w.HANDLE()
    try:
        shell.SHCreateItemFromParsingName.argtypes=[w.LPCWSTR,c.c_void_p,c.POINTER(GUID),c.POINTER(c.c_void_p)]
        if shell.SHCreateItemFromParsingName(str(path),None,c.byref(guid),c.byref(factory))<0:return None
        table=c.cast(factory,c.POINTER(c.POINTER(c.c_void_p))).contents
        get=c.WINFUNCTYPE(c.c_long,c.c_void_p,SIZE,w.DWORD,c.POINTER(w.HANDLE))(table[3])
        if get(factory,SIZE(320,180),0x19,c.byref(bitmap))<0:return None # thumbnail only, cache only
        gdi.GetObjectW.argtypes=[w.HANDLE,c.c_int,c.c_void_p];gdi.DeleteObject.argtypes=[w.HANDLE]
        info=BITMAP();gdi.GetObjectW(bitmap,c.sizeof(info),c.byref(info))
        width,height=info.width,abs(info.height)
        if not 0<width<=4096 or not 0<height<=4096:return None
        header=HEADER(c.sizeof(HEADER),width,-height,1,32,0,width*height*4,0,0,0,0)
        pixels=c.create_string_buffer(width*height*4)
        user.GetDC.argtypes=[w.HWND];user.GetDC.restype=w.HDC;user.ReleaseDC.argtypes=[w.HWND,w.HDC]
        gdi.GetDIBits.argtypes=[w.HDC,w.HANDLE,w.UINT,w.UINT,c.c_void_p,c.c_void_p,w.UINT]
        dc=user.GetDC(None)
        try:
            if not gdi.GetDIBits(dc,bitmap,0,height,pixels,c.byref(header),0):return None
            return Image.frombytes('RGBA',(width,height),pixels.raw,'raw','BGRA').convert('RGB')
        finally:user.ReleaseDC(None,dc)
    finally:
        if bitmap:gdi.DeleteObject(bitmap)
        if factory:
            table=c.cast(factory,c.POINTER(c.POINTER(c.c_void_p))).contents
            c.WINFUNCTYPE(w.ULONG,c.c_void_p)(table[2])(factory)
        if initialized in (0,1):ole.CoUninitialize()

class Thumbnails:
    def __init__(self,folder):
        self.folder=Path(folder);self.jobs=LifoQueue();self.results=Queue();self.pending=set();self.wanted=set();self.closed=False;self.process=None;self.paused=False;self.lock=threading.Lock()
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()
    def key(self,path,identity):return hashlib.sha256(json.dumps([str(path),identity],sort_keys=True).encode()).hexdigest()[:32]
    def request(self,key,path,decoder,duration=0):
        if key not in self.pending:self.pending.add(key);self.jobs.put((key,Path(path),decoder,duration))
    def run(self):
        while not self.closed:
            job=self.jobs.get()
            if job is None or self.closed:return
            key,path,decoder,duration=job
            try:
                if self.paused or key not in self.wanted:continue
                cache=self.folder/(key+'.jpg');picture=None;from_windows=False
                if cache.exists():
                    try:
                        with Image.open(cache) as image:picture=image.convert('RGB')
                    except (OSError,ValueError):pass
                if picture is None:
                    try:picture=windows_thumbnail(path);from_windows=picture is not None
                    except (OSError,ValueError):pass
                    if picture is None and decoder:
                        for at in (min(3,duration*.15) if duration else 3,0):
                            if self.closed or key not in self.wanted:break
                            with self.lock:
                                if self.paused or self.closed:break
                                self.process=subprocess.Popen([str(decoder),'-hide_banner','-v','error','-nostdin','-ss',str(at),'-i',str(path),'-map','0:v:0','-frames:v','1','-vf','scale=320:180:force_original_aspect_ratio=decrease','-f','image2pipe','-c:v','png','-'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                            try:output,_=self.process.communicate(timeout=12)
                            except subprocess.TimeoutExpired:self.process.kill();self.process.communicate();continue
                            if output:
                                try:picture=Image.open(io.BytesIO(output)).convert('RGB');break
                                except OSError:pass
                    if picture and not from_windows:
                        picture.thumbnail((320,180));self.folder.mkdir(parents=True,exist_ok=True)
                        temporary=cache.with_suffix('.writing');picture.save(temporary,format='JPEG',quality=85);temporary.replace(cache)
                self.results.put((key,picture))
            except (OSError,ValueError):self.results.put((key,None))
            finally:self.pending.discard(key);self.process=None
    def close(self):
        self.pause();self.closed=True
        self.jobs.put(None)
        self.worker.join(timeout=2)
    def pause(self):
        with self.lock:
            self.paused=True;self.wanted=set()
            process=self.process
            if process and process.poll() is None:
                try:process.terminate();process.wait(timeout=2)
                except (OSError,subprocess.TimeoutExpired):pass

def delete_thumbnails(base):
    base=Path(base).resolve();folder=base/'Generated Thumbnails'
    if folder.is_symlink() or not folder.is_dir() or folder.resolve().parent!=base:return
    for path in folder.iterdir():
        if path.is_file() and not path.is_symlink() and (path.suffix in ('.jpg','.writing')) and len(path.stem)==32 and all(c in '0123456789abcdef' for c in path.stem):path.unlink(missing_ok=True)
    try:folder.rmdir()
    except OSError:pass
