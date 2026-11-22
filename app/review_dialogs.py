# SPDX-License-Identifier: GPL-3.0-or-later
"""Scrollable dialog pages: small windows keep content reachable."""
import tkinter as tk
from tkinter import ttk


def own_variables(window,*variables):
    """Release dialog-only Tcl state on the UI thread, before cyclic GC.

    Background decoding can trigger Python's cycle collector after a dialog
    closes. Detaching already-disposed variables prevents later finalizers
    from calling Tk from that worker thread.
    """
    def dispose(event):
        if event.widget!=window:return
        for variable in variables:
            try:variable.__del__()
            except tk.TclError:pass
            finally:variable._tk=None
    window.bind('<Destroy>',dispose,add='+')


class ScrollPage(ttk.Frame):
    def __init__(self,parent,padding=12):
        super().__init__(parent)
        self.canvas=tk.Canvas(self,highlightthickness=0,bd=0,width=720,height=560)
        self.vertical=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.horizontal=ttk.Scrollbar(self,orient='horizontal',command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self.horizontal.set,yscrollcommand=self.vertical.set)
        self.canvas.grid(row=0,column=0,sticky='nsew');self.vertical.grid(row=0,column=1,sticky='ns');self.horizontal.grid(row=1,column=0,sticky='ew')
        self.rowconfigure(0,weight=1);self.columnconfigure(0,weight=1)
        self.inner=ttk.Frame(self.canvas,padding=padding)
        self.item=self.canvas.create_window(0,0,anchor='nw',window=self.inner)
        self.pending=None;self.layout_key=None;self.visible_bars=(False,False)
        self.inner.bind('<Configure>',self.schedule);self.canvas.bind('<Configure>',self.schedule)
        self.bind('<Map>',self.schedule)
        self.top=self.winfo_toplevel()
        self.wheel_id=self.top.bind('<MouseWheel>',self.wheel,add='+')
        self.bind('<Destroy>',self.destroyed,add='+')
        self.vertical.grid_remove();self.horizontal.grid_remove()
    def destroyed(self,event):
        if event.widget==self:
            if self.pending:self.after_cancel(self.pending);self.pending=None
            try:self.top.unbind('<MouseWheel>',self.wheel_id)
            except tk.TclError:pass
    def schedule(self,event=None):
        if self.pending is None:self.pending=self.after_idle(self.sync)
    def sync(self,event=None):
        if self.pending:self.after_cancel(self.pending);self.pending=None
        if not self.winfo_exists():return
        background=getattr(self.top,'review_palette',{}).get('background','#101218')
        width,height=self.canvas.winfo_width(),self.canvas.winfo_height()
        reqw,reqh=self.inner.winfo_reqwidth(),self.inner.winfo_reqheight()
        key=(width,height,reqw,reqh,background)
        if key==self.layout_key:return
        self.layout_key=key
        if self.canvas.cget('background')!=background:self.canvas.configure(bg=background)
        self.canvas.itemconfigure(self.item,width=max(width,reqw),height=max(height,reqh))
        self.canvas.configure(scrollregion=(0,0,max(width,reqw),max(height,reqh)))
        visible=(reqh>height+1,reqw>width+1)
        for axis,bar,show,was in zip(('y','x'),(self.vertical,self.horizontal),visible,self.visible_bars):
            if show==was:continue
            if show:bar.grid()
            else:bar.grid_remove();getattr(self.canvas,axis+'view_moveto')(0)
        self.visible_bars=visible
    def wheel(self,event):
        if not self.winfo_viewable():return
        # A native text view scrolls its own content without moving a canvas child.
        if isinstance(event.widget,tk.Text):return
        widget=event.widget
        while widget is not None and widget!=self:widget=getattr(widget,'master',None)
        if widget!=self:return
        axis='x' if event.state&1 else 'y'
        if getattr(self,'horizontal' if axis=='x' else 'vertical').winfo_ismapped():
            getattr(self.canvas,axis+'view_scroll')(-1 if event.delta>0 else 1,'units');return 'break'


class Changelog(ttk.Frame):
    """Bounded native text scrolling, even when given a very long history."""
    def __init__(self,parent,text,palette):
        super().__init__(parent)
        self.text=tk.Text(self,width=64,height=11,wrap='word',state='normal',
                          borderwidth=0,highlightthickness=0,padx=12,pady=8,
                          font=('Segoe UI',10),background=palette['panel'],foreground=palette['text'],
                          selectbackground=palette['highlighted_clip'],cursor='arrow',takefocus=True)
        self.scrollbar=ttk.Scrollbar(self,orient='vertical',command=self.text.yview)
        self.scrollbar.pack(side='right',fill='y');self.text.pack(fill='both',expand=True)
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.text.tag_configure('center',justify='center')
        self.text.insert('1.0',text,'center');self.text.configure(state='disabled')


def reserve_footer(footer):
    """Pack footer first so expanding content cannot push actions off-screen."""
    siblings=footer.master.pack_slaves()
    before=next((w for w in siblings if w!=footer),None)
    footer.pack_configure(side='bottom',**({'before':before} if before else {}))
