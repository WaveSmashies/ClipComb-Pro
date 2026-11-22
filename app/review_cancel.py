# SPDX-License-Identifier: GPL-3.0-or-later
"""Cooperative cancellation, including the currently owned probe process."""
import subprocess,time,threading,os
from contextlib import contextmanager
_priority=threading.local()

def sync_priority(event):
    if os.name!='nt' or getattr(_priority,'event',None) is not event:return
    import ctypes as c
    kernel=c.windll.kernel32;background=bool(getattr(event,'background',True))
    if getattr(_priority,'background',None)!=background:
        kernel.GetCurrentThread.restype=c.c_void_p
        kernel.SetThreadPriority.argtypes=[c.c_void_p,c.c_int]
        if background:
            _priority.active=bool(kernel.SetThreadPriority(kernel.GetCurrentThread(),0x10000))
        elif getattr(_priority,'active',False):
            kernel.SetThreadPriority(kernel.GetCurrentThread(),0x20000);_priority.active=False
        _priority.background=background
    process=getattr(event,'current_process',None)
    key=(process.pid,background) if process else None
    if process and process.poll() is None and getattr(_priority,'process',None)!=key:
        kernel.OpenProcess.argtypes=[c.c_uint32,c.c_int,c.c_uint32];kernel.OpenProcess.restype=c.c_void_p
        kernel.SetPriorityClass.argtypes=[c.c_void_p,c.c_uint32];kernel.CloseHandle.argtypes=[c.c_void_p]
        handle=kernel.OpenProcess(0x0200,False,process.pid)
        if handle:
            try:kernel.SetPriorityClass(handle,0x4000 if background else 0x20)
            finally:kernel.CloseHandle(handle)
        _priority.process=key

@contextmanager
def background_thread(event=None):
    event=event if event is not None else threading.Event()
    _priority.event=event;_priority.background=None;_priority.active=False;_priority.process=None
    sync_priority(event)
    try:yield
    finally:
        event.background=False;sync_priority(event);_priority.event=None
class ScanCancelled(Exception):pass
def checkpoint(event):
    if event is not None and event.is_set():raise ScanCancelled('Scan canceled. Original recordings were not changed.')
    if event is not None:sync_priority(event)
def capture(args,cancel=None,**kwargs):
    if cancel is None:return subprocess.run(args,**kwargs)
    checkpoint(cancel);timeout=kwargs.pop('timeout',None);kwargs.pop('capture_output',None)
    if getattr(cancel,'background',False):kwargs['creationflags']=kwargs.get('creationflags',0)|getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0)
    process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs)
    cancel.current_process=process
    deadline=time.monotonic()+timeout if timeout else None
    try:
        while True:
            checkpoint(cancel)
            if deadline and time.monotonic()>deadline:raise subprocess.TimeoutExpired(args,timeout)
            try:
                out,err=process.communicate(timeout=.15)
                checkpoint(cancel);return subprocess.CompletedProcess(args,process.returncode,out,err)
            except subprocess.TimeoutExpired:pass
    except BaseException:
        if process.poll() is None:process.kill()
        process.communicate();raise
    finally:
        if getattr(cancel,'current_process',None) is process:cancel.current_process=None
