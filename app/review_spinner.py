# SPDX-License-Identifier: GPL-3.0-or-later
"""Small activity wheel, using the theme's accent color."""
import tkinter as tk

class Spinner(tk.Canvas):
    def __init__(self,parent,size=24):
        colors=getattr(parent._root(),'review_palette',{})
        self.size=size
        super().__init__(parent,width=size,height=size,highlightthickness=0,bg=colors.get('background','#101218'))
        self.color=colors.get('selection','#bd9aff');self.timer=None;self.angle=0;self.running=False
        self.bind('<Destroy>',lambda e:self.stop())
        self.bind('<Map>',lambda e:self.spin() if self.running and self.timer is None else None)
        self.bind('<Unmap>',lambda e:self.cancel_timer())
    def apply_palette(self,colors):
        self.configure(bg=colors['background']);self.color=colors['selection']
        self.itemconfigure('all',outline=self.color)

    def start(self,unused=None):
        if self.running:return
        self.running=True;self.spin()
    def spin(self):
        self.timer=None
        if not self.running or not self.winfo_viewable():return
        colors=getattr(self._root(),'review_palette',{})
        self.configure(bg=colors.get('background','#101218'));self.color=colors.get('selection','#bd9aff')
        self.delete('all');self.angle=(self.angle+24)%360
        inset=self.size/6
        self.create_arc(inset,inset,self.size-inset,self.size-inset,start=self.angle,extent=260,outline=self.color,width=max(3,self.size/9),style='arc')
        self.timer=self.after(30,self.spin)
    def cancel_timer(self):
        if self.timer:
            try:self.after_cancel(self.timer)
            except tk.TclError:pass
            self.timer=None
    def stop(self):
        self.running=False
        self.cancel_timer()
        try:self.delete('all')
        except tk.TclError:pass
