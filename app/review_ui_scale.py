# SPDX-License-Identifier: GPL-3.0-or-later
"""Use a 1440-pixel monitor edge as the reference for the desktop layout."""
import tkinter as tk
import time
from tkinter import ttk
from weakref import WeakKeyDictionary
from review_windows import monitor_rect,window_move_in_progress,window_rect

def monitor_scale(bounds):
    left,top,right,bottom=bounds
    return round(max(.5,min(3,min(right-left,bottom-top)/1440)),3)

class UiScale:
    def __init__(self,app):
        self.app=app;self.root=app.root;self.records=WeakKeyDictionary();self.pending=None;self.new_widgets=set();self.minimum=None
        self.bounds=monitor_rect(self.root)
        self.factor=monitor_scale(self.bounds);self.root.review_scale=self.factor;self.next_check=0
        self.monitor_timer=None;self.move_observed=False;self.scale_origin=None
        self.root.tk.call('tk','scaling',4/3*self.factor)
        self.root.bind_all('<Map>',self.mapped,add='+')
        self.root.bind('<Configure>',self.configured,add='+')

    def configured(self,event):
        if event.widget!=self.root or self.app.closed or not self.root.winfo_viewable():return
        if self.monitor_timer:self.root.after_cancel(self.monitor_timer)
        self.monitor_timer=self.root.after(140,self.monitor_settled)

    def monitor_settled(self):
        self.monitor_timer=None
        self.check_monitor()

    def mapped(self,event=None):
        widget=event.widget if event is not None else self.root
        # Combobox popdowns are Tcl-owned windows. Tk reports their path as a
        # string, not a Python widget; their theme/scale is handled by ttk.
        if not isinstance(widget,tk.Misc):return
        ancestor=widget
        while ancestor is not None:
            if getattr(ancestor,'review_manual_scale',False):return
            ancestor=getattr(ancestor,'master',None)
        if widget in self.records:return
        self.new_widgets.add(widget)
        if self.pending is None and not self.app.closed:self.pending=self.root.after_idle(lambda:self.apply_new(full=False))
    def values(self,widget,value):
        if isinstance(value,(float,int)):return (float(value),)
        if isinstance(value,(tuple,list)):return tuple(float(str(v)) for v in value)
        return tuple(float(str(v)) for v in widget.tk.splitlist(str(value))) if str(value) else ()
    def apply_new(self,full=True):
        if self.pending:self.root.after_cancel(self.pending)
        self.pending=None
        if self.app.closed:return
        pending=list(self.root.winfo_children()) if full else list(self.new_widgets)
        self.new_widgets.clear()
        visited=set()
        while pending:
            widget=pending.pop()
            if not isinstance(widget,tk.Misc):continue
            if widget in visited:continue
            visited.add(widget)
            if not widget.winfo_exists():continue
            if getattr(widget,'review_manual_scale',False):continue
            pending.extend(widget.winfo_children())
            if hasattr(widget,'review_animation'):widget.review_animation.rescale(self.factor)
            record=self.records.get(widget)
            if record is None:
                options={};keys=widget.keys()
                for name in ('padding','wraplength','length'):
                    if name in keys:
                        try:options[name]=self.values(widget,widget.cget(name))
                        except (ValueError,tk.TclError):pass
                if isinstance(widget,(tk.Frame,tk.Canvas,ttk.Frame)) or isinstance(widget,tk.Button) and widget.cget('image'):
                    for name in ('width','height'):
                        if name in keys:
                            try:options[name]=self.values(widget,widget.cget(name))
                            except (ValueError,tk.TclError):pass
                layout={};manager=widget.winfo_manager()
                if manager in ('pack','grid'):
                    info=widget.pack_info() if manager=='pack' else widget.grid_info()
                    for key in ('padx','pady','ipadx','ipady'):
                        if key in info:
                            try:layout[key]=self.values(widget,info[key])
                            except (ValueError,tk.TclError):pass
                columns={}
                if isinstance(widget,ttk.Treeview):
                    for col in widget['columns']:
                        if not widget.column(col,'stretch'):columns[col]={key:round(int(widget.column(col,key))/(self.factor if col=='activity' else 1)) for key in ('width','minwidth')}
                record=dict(options=options,layout=layout,manager=manager,columns=columns,applied=None);self.records[widget]=record
            if record['applied']==self.factor:continue
            scaled=lambda values:tuple(round(v*self.factor) for v in values)
            for key,values in record['options'].items():
                if values:
                    try:widget.configure(**{key:scaled(values) if len(values)>1 else scaled(values)[0]})
                    except tk.TclError:pass
            if record['manager']==widget.winfo_manager() and record['layout']:
                config={key:scaled(values) for key,values in record['layout'].items()}
                try:(widget.pack_configure if record['manager']=='pack' else widget.grid_configure)(**config)
                except tk.TclError:pass
            for col,values in record['columns'].items():widget.column(col,**{key:round(v*self.factor) for key,v in values.items()})
            record['applied']=self.factor
        minimum=(round(1150*self.factor),round(850*self.factor))
        if self.minimum!=minimum:self.root.minsize(*minimum);self.minimum=minimum
    def tick(self):
        now=time.monotonic()
        if self.monitor_timer is not None or now<self.next_check:return
        self.next_check=now+.5
        self.check_monitor()

    def check_monitor(self):
        if self.app.closed or not self.root.winfo_viewable():return
        if window_move_in_progress():
            self.move_observed=True
            self.monitor_timer=self.root.after(80,self.monitor_settled)
            return
        bounds=monitor_rect(self.root)
        if bounds==self.bounds:
            self.move_observed=False
            return
        origin=window_rect(self.root)[:2]
        if origin==self.scale_origin and bounds[:2]!=self.bounds[:2] and not self.move_observed:
            # A new minimum size can change the monitor with the largest
            # intersection for a window straddling the seam. Keep its scale
            # until the window moves or the user performs a native resize.
            return
        self.move_observed=False;self.bounds=bounds
        factor=monitor_scale(bounds)
        if factor==self.factor:return
        self.scale_origin=origin
        self.factor=factor;self.root.review_scale=factor;self.root.tk.call('tk','scaling',4/3*factor)
        from review_theme import install_theme
        install_theme(self.root,self.app.palette);self.apply_new()
        self.app.timeline.draw();self.app.update_transports('layout');self.app.queue_view.apply_theme()
    def close(self):
        if self.pending:self.root.after_cancel(self.pending);self.pending=None
        if self.monitor_timer:self.root.after_cancel(self.monitor_timer);self.monitor_timer=None
