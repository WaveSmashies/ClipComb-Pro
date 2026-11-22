# SPDX-License-Identifier: GPL-3.0-or-later
"""Live, compositor-rendered crop of this app only; no screenshot polling."""
import ctypes as c
from ctypes import wintypes as w
from review_windows import client_rect,window_rect


class Properties(c.Structure):
    _fields_=[('flags',w.DWORD),('destination',w.RECT),('source',w.RECT),
              ('opacity',c.c_ubyte),('visible',w.BOOL),('client_only',w.BOOL)]


class LiveLoupe:
    def __init__(self,root,window):
        self.root,self.window=root,window
        self.user,self.dwm=c.windll.user32,c.windll.dwmapi
        self.user.GetAncestor.argtypes,self.user.GetAncestor.restype=[w.HWND,w.UINT],w.HWND
        self.user.GetWindowRect.argtypes=[w.HWND,c.POINTER(w.RECT)]
        self.dwm.DwmRegisterThumbnail.argtypes=[w.HWND,w.HWND,c.POINTER(c.c_void_p)]
        self.dwm.DwmRegisterThumbnail.restype=c.c_long
        self.dwm.DwmUpdateThumbnailProperties.argtypes=[c.c_void_p,c.POINTER(Properties)]
        self.dwm.DwmUpdateThumbnailProperties.restype=c.c_long
        self.dwm.DwmUnregisterThumbnail.argtypes=[c.c_void_p]
        self.handle=c.c_void_p()
        self.source_hwnd=self.destination_hwnd=None
        self.connect()

    def connect(self):
        source=self.user.GetAncestor(self.root.winfo_id(),2)
        destination=self.user.GetAncestor(self.window.winfo_id(),2)
        if source==self.source_hwnd and destination==self.destination_hwnd and self.handle:return
        self.close();self.handle=c.c_void_p()
        status=self.dwm.DwmRegisterThumbnail(destination,source,c.byref(self.handle))
        if status:raise OSError(f'Windows live preview is unavailable ({status:#x}).')
        self.source_hwnd,self.destination_hwnd=source,destination;self.signature=None

    def update(self,frame,px,py,width,height,zoom):
        # Tk may replace a wrapper HWND on a DPI/style/focus transition. DWM
        # registrations belong to that native window, not to the Tk widget.
        self.connect()
        left_window,top_window,_,_=window_rect(self.root)
        # Clip to the video pane. Near its edge, leave the corresponding part of
        # the loupe black rather than magnifying other controls or distorting it.
        left,top=px-width/(2*zoom),py-height/(2*zoom)
        right,bottom=left+width/zoom,top+height/zoom
        fx,fy,fr,fb=client_rect(frame)
        x1,y1=max(left,fx),max(top,fy)
        x2,y2=min(right,fr),min(bottom,fb)
        visible=x2>x1 and y2>y1
        src=tuple(round(v) for v in (x1-left_window,y1-top_window,x2-left_window,y2-top_window))
        dst=tuple(round(v) for v in (2+(x1-left)*zoom,2+(y1-top)*zoom,2+(x2-left)*zoom,2+(y2-top)*zoom))
        signature=(src,dst,visible)
        self.last_geometry={'source':src,'destination':dst,'visible':visible,'frame':(fx,fy,fr,fb),'window':(left_window,top_window)}
        if signature!=self.signature:
            # DWM rejects reversed/empty rectangles even with fVisible=False.
            # Hide without replacing the last valid source/destination crop.
            props=Properties(0x1f,w.RECT(*dst),w.RECT(*src),255,True,False) if visible else Properties(flags=8,visible=False)
            status=self.dwm.DwmUpdateThumbnailProperties(self.handle,c.byref(props))
            if status:raise OSError(f'Windows could not update the live magnifier ({status:#x}).')
            self.signature=signature

    def close(self):
        if self.handle:self.dwm.DwmUnregisterThumbnail(self.handle);self.handle=None
