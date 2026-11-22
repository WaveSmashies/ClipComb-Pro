# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in Windows media Play/Pause key, released completely when disabled.

An optional native listener handles only the media Play/Pause key. Other keys
pass through immediately and are never retained. A separate Windows message
thread sleeps between events; all player/Tk work stays on the UI thread.
"""
import ctypes as c
from ctypes import wintypes as w
import os
from queue import SimpleQueue
import threading


class MediaKeyData(c.Structure):
    _fields_=[('key',w.DWORD),('scan',w.DWORD),('flags',w.DWORD),
              ('time',w.DWORD),('extra',c.c_size_t)]


class MediaPlayPause:
    KEY=0xB3
    QUIT=0x12

    def __init__(self):
        self.events=SimpleQueue()
        self.worker=None
        self.thread_id=None
        self.error=None
        self.handle=None
        self.callback=None
        self.down=False

    def set_enabled(self,enabled):
        if enabled and self.worker and self.worker.is_alive():return
        self.close()
        if not enabled:return
        if os.name!='nt':raise OSError('The keyboard media button is available on Windows only.')
        self.ready=threading.Event()
        self.stopping=threading.Event()
        self.error=None
        self.worker=threading.Thread(target=self._listen,name='ClipComb media key',daemon=True)
        self.worker.start()
        if not self.ready.wait(2):
            self.close()
            raise OSError('The keyboard media button did not respond. The setting remains off.')
        if self.error:
            self.close()
            raise OSError(self.error)

    def _listen(self):
        try:
            self.user=c.WinDLL('user32',use_last_error=True)
            kernel=c.WinDLL('kernel32',use_last_error=True)
            kernel.GetCurrentThreadId.restype=w.DWORD
            kernel.GetModuleHandleW.argtypes=[w.LPCWSTR]
            kernel.GetModuleHandleW.restype=w.HMODULE
            callback_type=c.WINFUNCTYPE(c.c_ssize_t,c.c_int,w.WPARAM,w.LPARAM)
            self.user.SetWindowsHookExW.argtypes=[c.c_int,callback_type,w.HINSTANCE,w.DWORD]
            self.user.SetWindowsHookExW.restype=w.HHOOK
            self.user.CallNextHookEx.argtypes=[w.HHOOK,c.c_int,w.WPARAM,w.LPARAM]
            self.user.CallNextHookEx.restype=c.c_ssize_t
            self.user.UnhookWindowsHookEx.argtypes=[w.HHOOK]
            self.user.UnhookWindowsHookEx.restype=w.BOOL
            self.user.GetMessageW.argtypes=[c.POINTER(w.MSG),w.HWND,w.UINT,w.UINT]
            self.user.GetMessageW.restype=c.c_int
            self.user.PostThreadMessageW.argtypes=[w.DWORD,w.UINT,w.WPARAM,w.LPARAM]
            self.user.PostThreadMessageW.restype=w.BOOL
            self.user.PeekMessageW.argtypes=[c.POINTER(w.MSG),w.HWND,w.UINT,w.UINT,w.UINT]
            self.user.PeekMessageW.restype=w.BOOL
            message=w.MSG()
            self.user.PeekMessageW(c.byref(message),None,0,0,0)
            self.thread_id=kernel.GetCurrentThreadId()
            def receive(code,message,pointer):
                if code>=0 and message in (0x100,0x101,0x104,0x105):
                    key=c.cast(pointer,c.POINTER(MediaKeyData)).contents.key
                    if key==self.KEY:
                        down=message in (0x100,0x104)
                        if down and not self.down:self.events.put(True)
                        self.down=down
                        return 1
                return self.user.CallNextHookEx(self.handle,code,message,pointer)
            self.callback=callback_type(receive)
            self.handle=self.user.SetWindowsHookExW(13,self.callback,kernel.GetModuleHandleW(None),0)
            if not self.handle:
                self.error='Could not enable the media Play/Pause button. The setting remains off.'
                return
            self.ready.set()
            if self.stopping.is_set():return
            while self.user.GetMessageW(c.byref(message),None,0,0)>0:pass
        except Exception:
            self.error='Could not enable the media Play/Pause button. The setting remains off.'
        finally:
            if self.handle:self.user.UnhookWindowsHookEx(self.handle)
            self.handle=None
            self.ready.set()

    def close(self):
        if self.worker:
            self.stopping.set()
            if self.worker.is_alive() and self.thread_id:
                self.user.PostThreadMessageW(self.thread_id,self.QUIT,0,0)
            self.worker.join(2)
            if self.worker.is_alive():raise OSError('The keyboard media button could not be released yet. Please close ClipComb Pro before using it in another app.')
            self.worker=None
        self.thread_id=None
        self.callback=None
        self.down=False
        while not self.events.empty():self.events.get()
