# SPDX-License-Identifier: GPL-3.0-or-later
"""Cursor overrides scoped to this app; no system cursor replacement."""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import struct
import tkinter as tk


def reticle_bytes():
    xor=bytearray(128)
    for x,y in [(x,i) for x in (15,16) for i in range(3,29)]+[(i,y) for y in (15,16) for i in range(3,29)]:
        xor[(31-y)*4+x//8]|=0x80>>(x%8)
    image=struct.pack('<IiiHHIIiiII',40,32,64,1,1,0,256,0,0,2,0)+b'\0\0\0\0\xff\xff\xff\0'+bytes(xor)+b'\xff'*128
    return struct.pack('<HHH',0,2,1)+struct.pack('<BBBBHHII',32,32,2,0,16,16,len(image),22)+image


class LoupeCursor:
    def __init__(self,root,frame):
        self.root,self.frame=root,frame;self.saved=[];self.hooks={};self.active=False;self.cursor=None
        self.user=c.windll.user32
        self.user.SetCursor.argtypes=[w.HANDLE];self.user.SetCursor.restype=w.HANDLE
        self.user.LoadCursorFromFileW.argtypes=[w.LPCWSTR];self.user.LoadCursorFromFileW.restype=w.HANDLE
        self.user.DestroyCursor.argtypes=[w.HANDLE]
        self.user.GetWindowLongPtrW.argtypes=[w.HWND,c.c_int];self.user.GetWindowLongPtrW.restype=c.c_ssize_t
        self.user.SetWindowLongPtrW.argtypes=[w.HWND,c.c_int,c.c_ssize_t];self.user.SetWindowLongPtrW.restype=c.c_ssize_t
        self.user.CallWindowProcW.argtypes=[c.c_void_p,w.HWND,w.UINT,w.WPARAM,w.LPARAM];self.user.CallWindowProcW.restype=c.c_ssize_t
        self.user.IsWindow.argtypes=[w.HWND]
        callback=c.WINFUNCTYPE(c.c_ssize_t,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
        def proc(hwnd,message,wp,lp):
            previous=self.hooks.get(hwnd)
            if not previous:return 0
            if self.active and message==0x20:self.user.SetCursor(self.cursor);return 1
            result=self.user.CallWindowProcW(previous,hwnd,message,wp,lp)
            if self.active and message==0x200:self.user.SetCursor(self.cursor)
            return result
        self.proc=callback(proc)
    def start(self,show,base):
        self.stop();self.active=True
        cursor='none'
        if show:
            path=Path(base)/'cache/cursors/invert-reticle-2x.cur';path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():path.write_bytes(reticle_bytes())
            self.cursor=self.user.LoadCursorFromFileW(str(path))
            if not self.cursor:raise OSError('Could not create magnifier reticle')
            # Tk parses cursor specifications as Tcl lists. Preserve spaces and
            # backslashes in portable folder paths as one list item.
            cursor=('@'+path.as_posix(),)
        pending=[self.root]
        while pending:
            widget=pending.pop();pending.extend(list(widget.children.values()))
            try:
                old=widget.cget('cursor');widget.configure(cursor=cursor);self.saved.append((widget,old))
            except tk.TclError:pass
        enum=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        def install(hwnd,unused):
            self.hooks[hwnd]=self.user.GetWindowLongPtrW(hwnd,-4)
            self.user.SetWindowLongPtrW(hwnd,-4,c.cast(self.proc,c.c_void_p).value)
            return True
        self.user.EnumChildWindows.argtypes=[w.HWND,enum,w.LPARAM]
        self.user.EnumChildWindows(self.frame.winfo_id(),enum(install),0)
        self.user.SetCursor(self.cursor)
    def stop(self):
        self.active=False
        for hwnd,previous in list(self.hooks.items()):
            if self.user.IsWindow(hwnd) and self.user.GetWindowLongPtrW(hwnd,-4)==c.cast(self.proc,c.c_void_p).value:
                self.user.SetWindowLongPtrW(hwnd,-4,previous)
        self.hooks.clear()
        for widget,old in self.saved:
            try:widget.configure(cursor=old)
            except tk.TclError:pass
        self.saved.clear()
        if self.cursor:self.user.DestroyCursor(self.cursor);self.cursor=None
