# SPDX-License-Identifier: GPL-3.0-or-later
"""Coalesce resize work at a frame cadence, including during a continuous drag."""
import tkinter as tk

class FrameUpdate:
    def __init__(self,widget,callback,interval=16,settled=None,dragging=None):
        self.widget,self.callback,self.interval=widget,callback,interval
        self.settled=settled;self.dragging=dragging;self.timer=None;self.settle_timer=None
        widget.bind('<Destroy>',self.destroy,add='+')
    def request(self,event=None):
        if self.timer is None:
            self.timer=self.widget.after(self.interval,self.run)
        if self.settled:
            if self.settle_timer:self.widget.after_cancel(self.settle_timer)
            self.settle_timer=self.widget.after(65,self.finish)
    def run(self):
        self.timer=None
        if self.widget.winfo_exists():self.callback()
    def finish(self):
        self.settle_timer=None
        if self.dragging and self.widget.winfo_viewable() and self.dragging():
            self.settle_timer=self.widget.after(33,self.finish)
            return
        if self.timer:self.widget.after_cancel(self.timer);self.timer=None
        if self.widget.winfo_exists():self.settled()
    def destroy(self,event):
        if event.widget==self.widget:
            for token in (self.timer,self.settle_timer):
                if token:
                    try:self.widget.after_cancel(token)
                    except tk.TclError:pass
            self.timer=self.settle_timer=None


class ResizeFinish:
    """One cleanup paint after a resize settles, keeping live resize work cheap."""
    def __init__(self,root,widgets,paint,delay=80,live_interval=None):
        self.root,self.paint,self.delay=root,paint,delay
        self.live_interval=live_interval;self.live_timer=None
        self.timer=None;self.sizes={};self.closed=False
        self.widgets=set(widgets)
        for widget in self.widgets:widget.bind('<Configure>',self.request,add='+')
        root.bind('<Destroy>',self.destroy,add='+')
    def request(self,event):
        if event.widget not in self.widgets:return
        if self.closed or event.widget==self.root and not self.root.winfo_viewable():return
        size=(event.width,event.height)
        if self.sizes.get(event.widget)==size:return
        self.sizes[event.widget]=size
        if self.live_interval and self.live_timer is None:
            self.live_timer=self.root.after(self.live_interval,self.paint_live)
        if self.timer:self.root.after_cancel(self.timer)
        self.timer=self.root.after(self.delay,self.run)
    def paint_live(self):
        self.live_timer=None
        if not self.closed and self.root.winfo_viewable():self.paint(self.root)
    def run(self):
        self.timer=None
        if not self.closed and self.root.winfo_viewable():self.paint(self.root)
    def close(self):
        self.closed=True
        if self.timer:self.root.after_cancel(self.timer);self.timer=None
        if self.live_timer:self.root.after_cancel(self.live_timer);self.live_timer=None
    def destroy(self,event):
        if event.widget==self.root:self.close()
