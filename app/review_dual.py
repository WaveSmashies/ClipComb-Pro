# SPDX-License-Identifier: GPL-3.0-or-later
"""Detach the existing Tk video container, keeping mpv and its clock alive."""
import ctypes as c
from ctypes import wintypes as w
import json,math,re,time
import tkinter as tk
from tkinter import ttk
from review_queue import QueueView,QUEUE_CATEGORIES
from review_theme import dark_title
from review_windows import monitor_rect,place_window,client_rect,window_rect,hwnd,window_dpi,window_move_in_progress

class VideoContainer(tk.Frame,tk.Wm):pass

class QueueCard:
    def __init__(self,manager,category,mode):
        self.manager=manager;app=manager.app;self.frame=ttk.Frame(manager.cards,padding=6,style='Panel.TFrame')
        controls=ttk.Frame(self.frame,style='Panel.TFrame');controls.pack(fill='x',pady=(0,6))
        self.category=tk.StringVar(value='Marks' if category=='Marked' else category);self.search=tk.StringVar()
        self.category_combo=ttk.Combobox(controls,textvariable=self.category,state='readonly',values=QUEUE_CATEGORIES,width=13);self.category_combo.pack(side='left')
        ttk.Entry(controls,textvariable=self.search,width=7).pack(side='left',fill='x',expand=True,padx=4)
        container=ttk.Frame(self.frame);container.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(container,columns=('clip','activity','state'),show='headings',selectmode='browse')
        for name,title,width in [('clip','Clip',180),('activity','',32),('state','Decision',65)]:
            self.tree.heading(name,text=title);self.tree.column(name,width=width,minwidth=32 if name=='activity' else 60,stretch=name=='clip')
        scroll=ttk.Scrollbar(container,orient='vertical',command=self.tree.yview,style='Queue.Vertical.TScrollbar');scroll.pack(side='right',fill='y');self.tree.pack(side='left',fill='both',expand=True)
        self.view=QueueView(app,container,controls,scroll,tree=self.tree);self.view.mode=mode
        self.programmatic=False;self.selection_timer=None
        self.tree.bind('<<TreeviewSelect>>',self.selected)
        self.tree.bind('<Button-3>',lambda e:app.clip_context_menu(e,self.tree.identify_row(e.y)))
        self.category.trace_add('write',lambda *_:self.populate());self.search.trace_add('write',lambda *_:self.populate())
        from review_dialogs import own_variables
        own_variables(self.frame,self.category,self.search)
        app.shortcut_tags(self.frame);self.populate()
    def selected(self,event=None):
        self.view.sync_badge_colors()
        selected=self.tree.selection()
        if not self.programmatic and selected and selected[0]!=self.manager.app.current_id:self.view.select(selected[0])
    def sync_selection(self):
        self.programmatic=True
        if self.selection_timer:self.frame.after_cancel(self.selection_timer)
        app=self.manager.app
        current=(app.cleanup.selected_id if app.cleanup.mode=='compare' else None) or app.current_id
        if current and self.tree.exists(current):
            if self.tree.selection()!=(current,):self.tree.selection_set(current)
        elif self.tree.selection():self.tree.selection_remove(*self.tree.selection())
        self.view.sync_badge_colors()
        def done():self.programmatic=False;self.selection_timer=None
        self.selection_timer=self.frame.after_idle(done)
    def populate(self):
        self.programmatic=True
        app=self.manager.app;category=self.category.get();query=self.search.get().casefold()
        from pathlib import Path
        from review_queue import filtered_clips
        from review_folders import category as folder_category,names
        from review_folders import categories
        self.category_combo.configure(values=categories(app.project))
        if category in names(app.project):category=names(app.project)[category]
        if category not in categories(app.project):category='All'
        if self.category.get()!=category:self.category.set(category);return
        clips=filtered_clips(app.project.data['clips'] if app.project else [],folder_category(app.project,category),query)
        self.tree.delete(*self.tree.get_children())
        from pathlib import Path
        for clip in clips:self.tree.insert('','end',iid=clip['id'],values=(app.cleanup.prefix(clip['id'])+Path(clip['path']).name,'',names(app.project).get(clip['decision'],clip['decision'])),tags=('comparison',) if app.cleanup.highlighted(clip['id']) else ())
        self.sync_selection()
        self.view.show(clips)
    def close(self):
        if self.selection_timer:self.frame.after_cancel(self.selection_timer)
        self.view.close();self.frame.destroy()

class ViewerWorkspace:
    def __init__(self,app):
        self.app=app;self.window=app.video_column;self.enabled=False;self.detached=False;self.fullscreen=False;self.panels=[];self.closing=False;self.suspended=False
        self.dashboard=ttk.Frame(app.playback);row=ttk.Frame(self.dashboard);row.pack(fill='x',pady=5)
        ttk.Label(row,text='Review queue panels').pack(side='left');self.count=tk.StringVar(value='4 / 6')
        ttk.Label(row,textvariable=self.count).pack(side='left',padx=8)
        app.button(row,'−',self.remove).pack(side='left');app.button(row,'+',self.add).pack(side='left',padx=4)
        from review_render import FrameUpdate
        self.cards=ttk.Frame(self.dashboard);self.cards.pack(fill='both',expand=True);self.layout_key=None
        self.resize_update=FrameUpdate(self.cards,self.layout);self.cards.bind('<Configure>',self.resize_update.request)
        from review_transport import Transport
        self.controls=Transport(self.dashboard,app);self.controls.pack(side='bottom',fill='x',before=self.cards,pady=(5,0))
        self.decoration_key=None;self.decoration_timer=None
        self.window.bind('<Map>',lambda e:self.request_decorations() if e.widget==self.window else None,add='+')
        self.window.bind('<Configure>',lambda e:self.request_decorations() if e.widget==self.window else None,add='+')
        self.window.bind('<FocusIn>',lambda e:self.request_decorations(),add='+');self.window.bind('<FocusOut>',lambda e:self.request_decorations(),add='+')
        self.group_restoring=False;self.restore_after=0
        app.root.bind('<Unmap>',self.main_unmapped,add='+')
        app.root.bind('<Map>',lambda e:self.restore_group(force=True) if e.widget==app.root else None,add='+')
        app.root.bind('<FocusIn>',lambda e:self.restore_group(),add='+')
        self.window.bind('<Unmap>',self.player_unmapped,add='+')
        self.window.bind('<Map>',lambda e:self.restore_group(force=True) if e.widget==self.window else None,add='+')
        self.window.bind('<FocusIn>',lambda e:self.restore_group(),add='+')
        app.root.bind_all('<ButtonPress>',self.group_clicked,add='+')
    def main_unmapped(self,event):
        if event.widget!=self.app.root or not self.enabled or self.suspended:return
        if self.app.root.state()=='iconic':
            self.restore_after=time.monotonic()+.3
            if self.window.state()!='iconic':
                if self.fullscreen:self.window.overrideredirect(False)
                self.window.iconify()
    def player_unmapped(self,event):
        if event.widget==self.window:self.restore_after=time.monotonic()+.3
    def group_clicked(self,event):
        if event.widget.winfo_toplevel() in (self.app.root,self.window):self.restore_group(force=True)
    def restore_group(self,force=False):
        if not self.enabled or self.suspended or self.group_restoring or self.closing or self.app.closed:return
        if not force and time.monotonic()<self.restore_after:return
        self.group_restoring=True
        try:
            for window in (self.app.root,self.window):
                if window.state()=='iconic':window.deiconify()
            if self.fullscreen:self.window.overrideredirect(True);self.fit_fullscreen()
        finally:self.group_restoring=False
    def request_decorations(self):
        if not self.detached or self.closing or self.app.closed:return
        if self.decoration_timer is None:
            self.decoration_timer=self.app.root.after(80,self.finish_decoration_request)
    def finish_decoration_request(self):
        self.decoration_timer=None
        self.refresh_decorations()
    def refresh_decorations(self):
        if not self.detached or self.closing or self.app.closed:return
        if window_move_in_progress():
            self.request_decorations()
            return
        bounds=monitor_rect(self.window)
        key=(hwnd(self.window,True),window_dpi(self.window),bounds,self.fullscreen,tuple(self.app.palette.items()))
        if key==self.decoration_key:return
        self.decoration_key=key
        from review_ui_scale import monitor_scale
        self.window.review_scale=monitor_scale(bounds)
        if not self.fullscreen:dark_title(self.window)
        self.app.update_transports('layout')
    def restore(self):
        if self.app.closed or self.suspended:return
        if self.app.settings.data.getboolean('dual','enabled'):self.enable(restore=True)
    def center_geometry(self):
        root=self.app.root;width=max(480,min(1100,int(root.winfo_width()*.7)));height=max(320,min(750,int(root.winfo_height()*.7)))
        return f'{width}x{height}{root.winfo_rootx()+(root.winfo_width()-width)//2:+d}{root.winfo_rooty()+(root.winfo_height()-height)//2:+d}'
    def center_native(self):
        left,top,right,bottom=client_rect(self.app.root)
        width=max(480,min(1100,round((right-left)*.7)));height=max(320,min(750,round((bottom-top)*.7)))
        place_window(self.window,(left+right-width)//2,(top+bottom-height)//2,width,height)
    def detach(self,geometry=None):
        if self.detached:return
        app=self.app;app.magnifier.hide();self.sash=app.playback.sashpos(0);self.sash_ratio=self.sash/max(1,app.playback.winfo_width())
        self.detached=True;self.window.review_scale=app.ui_scale.factor
        app.playback.forget(self.window);app.root.tk.call('wm','manage',self.window._w)
        self.window.title('ClipComb Pro - Player');self.window.protocol('WM_DELETE_WINDOW',self.close_window)
        self.window.geometry(geometry or self.center_geometry());self.window.minsize(360,240);self.window.review_palette=app.palette;dark_title(self.window)
        from review_icons import apply_window_icon
        apply_window_icon(self.window)
        self.detached=True;app.magnifier.source_window=self.window;app.magnifier.reset_mode();self.window.deiconify()
        if not geometry:self.window.update_idletasks();self.center_native()
        self.decoration_key=None;self.refresh_decorations()
    def redock(self):
        if not self.detached:return
        app=self.app;app.magnifier.hide();app.root.tk.call('wm','forget',self.window._w);app.playback.insert(0,self.window,weight=5)
        self.detached=False;app.magnifier.source_window=app.root;app.magnifier.reset_mode()
        def restore():
            if not app.closed and not self.detached and len(app.playback.panes())>1:app.playback.sashpos(0,round(app.playback.winfo_width()*self.sash_ratio))
        app.root.after_idle(restore);app.root.after(100,restore)
    def toggle(self):
        if self.app.busy:return
        self.disable() if self.enabled else self.enable()
    def enable(self,restore=False):
        if self.enabled:return
        if self.fullscreen:self.toggle_fullscreen()
        app=self.app;cfg=app.settings.data['dual'];geometry=cfg['geometry'] if restore and cfg['geometry'] else None
        self.detach(geometry);self.enabled=True;app.playback.insert(0,self.dashboard,weight=5)
        app.root.after_idle(lambda:app.playback.sashpos(0,round(app.playback.winfo_width()*self.sash_ratio)) if self.enabled and len(app.playback.panes())>1 else None)
        try:specs=json.loads(cfg['panels'])
        except (ValueError,TypeError):specs=[{'category':n,'mode':'List'} for n in ('Used','Kept','Deleted')]
        for spec in specs[:5]:self.add(spec.get('category','All'),spec.get('mode',app.queue_view.mode))
        if restore and cfg.get('primary_category'):app.filter.set(cfg['primary_category'])
        self.window.update_idletasks()
        # An unavailable display must not leave a restored window unreachable.
        left,top,right,bottom=monitor_rect(self.window,True)
        if self.window.winfo_rootx()+self.window.winfo_width()<left+40 or self.window.winfo_rootx()>right-40 or self.window.winfo_rooty()>bottom-40 or self.window.winfo_rooty()+self.window.winfo_height()<top+40:self.center_native()
        cfg['enabled']='yes';self.app.dual_button.configure(text='Single Monitor Mode')
        if restore and cfg.getboolean('fullscreen'):self.toggle_fullscreen()
        self.layout()
    def store(self):
        cfg=self.app.settings.data['dual'];cfg['enabled']='yes' if self.enabled else 'no';cfg['primary_category']=self.app.filter.get()
        if self.detached:cfg['geometry']=self.normal_geometry if self.fullscreen else self.window.geometry()
        cfg['fullscreen']='yes' if self.fullscreen else 'no'
        if self.enabled:cfg['panels']=json.dumps([{'category':card.category.get(),'mode':card.view.mode} for card in self.panels])
    def disable(self):
        self.store()
        if self.fullscreen:self.toggle_fullscreen()
        for card in self.panels:card.close()
        self.panels=[];self.app.playback.forget(self.dashboard);self.enabled=False;self.redock()
        self.app.settings.data['dual']['enabled']='no';self.app.dual_button.configure(text='Dual Monitor Mode');self.app.active_queue=self.app.queue_view
    def add(self,category=None,mode=None):
        if len(self.panels)>=5:return
        preferred=['Used','Kept','Deleted','Marks','All']
        card=QueueCard(self,category or preferred[len(self.panels)],mode or self.app.queue_view.mode);self.panels.append(card);self.layout()
    def remove(self):
        if not self.panels:return
        card=self.panels.pop()
        if getattr(self.app,'active_queue',None)==card.view:self.app.active_queue=self.app.queue_view
        card.close();self.layout()
    def layout(self):
        columns=3 if self.cards.winfo_width()>1300 else 2
        if len(self.panels)==1:columns=1
        key=(tuple(id(p) for p in self.panels),columns)
        if self.layout_key==key:return
        self.layout_key=key
        for i in range(5):self.cards.columnconfigure(i,weight=0);self.cards.rowconfigure(i,weight=0)
        for i,card in enumerate(self.panels):
            card.frame.grid(row=i//columns,column=i%columns,sticky='nsew',padx=3,pady=3);self.cards.columnconfigure(i%columns,weight=1);self.cards.rowconfigure(i//columns,weight=1)
        self.count.set(f'{len(self.panels)+1} / 6')
    def populate(self):
        for card in self.panels:card.populate()
    def refresh(self):
        for card in self.panels:
            card.sync_selection()
            if getattr(self.app,'active_queue',None)==card.view:card.view.reveal(self.app.current_id)
            else:card.view.refresh_status()
    def theme(self):
        self.window.configure(bg=self.app.palette['background'])
        self.controls.set_palette(self.app.palette)
        if self.detached:self.window.review_palette=self.app.palette;dark_title(self.window)
        for card in self.panels:card.view.apply_theme()
    def toggle_fullscreen(self):
        app=self.app;app.magnifier.hide()
        if not self.fullscreen:
            self.detach();self.normal_geometry=self.window.geometry();self.normal_bounds=window_rect(self.window);self.transport_pack=app.transport.pack_info();app.transport.pack_forget()
            left,top,right,bottom=monitor_rect(self.window)
            self.window.overrideredirect(True);self.window.update_idletasks()
            self.fullscreen=True;self.fullscreen_bounds=(left,top,right,bottom)
            self.fit_fullscreen();self.window.lift()
            app.root.after_idle(self.fit_fullscreen);app.root.after(100,self.fit_fullscreen)
        else:
            self.window.overrideredirect(False);self.window.geometry(self.normal_geometry);app.transport.pack(**self.transport_pack);self.fullscreen=False
            self.window.update_idletasks();left,top,right,bottom=self.normal_bounds;place_window(self.window,left,top,right-left,bottom-top)
            if not self.enabled:self.redock()
        app.fullscreen=self.fullscreen;app.video_frame.focus_set()
    def fit_fullscreen(self):
        if not self.fullscreen or self.app.closed:return
        left,top,right,bottom=self.fullscreen_bounds
        place_window(self.window,left,top,right-left,bottom-top)
    def close_window(self):
        if self.fullscreen:self.toggle_fullscreen()
        if self.enabled:self.disable()
    def suspend(self):
        self.suspended=True
        if self.detached:self.window.withdraw()
    def resume(self):
        self.suspended=False
        if self.detached:self.window.deiconify()
        else:self.restore()
    def shutdown(self):
        self.store();self.closing=True
        if self.decoration_timer:self.app.root.after_cancel(self.decoration_timer);self.decoration_timer=None
        if self.fullscreen:self.toggle_fullscreen()
        for card in self.panels:card.close()
        self.panels=[];self.app.fullscreen=False
