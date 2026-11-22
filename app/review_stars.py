# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional colored clip Stars: review-queue metadata with no timeline/export role."""
import copy
import tkinter as tk
from tkinter import ttk
from review_theme import dialog,present
from review_dialogs import own_variables

DEFAULT_TOOLTIP="Stars do not have any effect on the clip or your project. They are just for organization."


def tooltip(clip,colors=None,config=None):
    from review_marker_colors import slot,RESOLVE,color_name
    star=clip.get('star') or {};index=slot(star)
    name=color_name(index,colors or RESOLVE,config)
    return star.get('title','').strip() or 'This clip has a'+(' '+name if name else '')+' star. '+DEFAULT_TOOLTIP


class Stars:
    def __init__(self,app):self.app=app
    def edit(self):
        app=self.app;clip=app.clip()
        if not clip or app.busy or app.loading:return
        window=dialog(app.root,'Clip Star');page=ttk.Frame(window,padding=18);page.pack(fill='both',expand=True)
        star=clip.get('star') or {};title=tk.StringVar(value=star.get('title',''));color=tk.IntVar(value=star.get('color_slot',0))
        ttk.Label(page,text='Title (optional)').pack(anchor='w')
        title_row=ttk.Frame(page);title_row.pack(fill='x',pady=(4,12))
        entry=ttk.Entry(title_row,textvariable=title,width=40);entry.pack(side='left',fill='x',expand=True)
        from review_help import badge
        badge(title_row,DEFAULT_TOOLTIP).pack(side='right',padx=(6,0))
        ttk.Label(page,text='Star color').pack(anchor='w');swatches=ttk.Frame(page);swatches.pack(pady=8)
        from review_marker_colors import slot
        from review_queue import symbol
        images=[];buttons=[]
        def refresh():
            for i,button in enumerate(buttons):button.configure(relief='sunken' if i==color.get() else 'flat')
        def choose(index):color.set(index);refresh()
        for i,value in enumerate(app.timeline.marker_colors):
            picture=symbol(window,'favorite',value);images.append(picture)
            button=tk.Button(swatches,image=picture,width=31,height=31,bd=2,bg=app.palette['panel'],activebackground=app.palette['input'],command=lambda n=i:choose(n))
            button.grid(row=i//8,column=i%8,padx=2,pady=2);buttons.append(button)
            from review_marker_colors import color_name
            from review_help import Tooltip
            name=color_name(i,app.timeline.marker_colors,app.settings.data['bookmarks'])
            if name:Tooltip(button,name.title())
        refresh();window.star_images=images
        controls=ttk.Frame(page);controls.pack(fill='x',pady=(12,0))
        def commit(value):
            app.history.watch(clip)
            if value is None:clip.pop('star',None)
            else:clip['star']=value
            app.changed(fields=('star',));app.update_transports('layout');window.destroy()
        ttk.Button(controls,text='Remove Star',command=lambda:commit(None),style='Round.TButton',state='normal' if star else 'disabled').pack(side='left')
        ttk.Button(controls,text='Save Star',command=lambda:commit(dict(title=title.get().strip(),color_slot=color.get())),style='Primary.TButton').pack(side='right')
        ttk.Button(controls,text='Cancel',command=window.destroy,style='Round.TButton').pack(side='right',padx=7)
        window.star_controls=dict(title=title,color=color,save=lambda:commit(dict(title=title.get().strip(),color_slot=color.get())),remove=lambda:commit(None))
        def enter(event=None):window.star_controls['save']();return 'break'
        entry.bind('<Return>',enter);entry.bind('<KP_Enter>',enter)
        window.star_entry=entry
        own_variables(window,title,color);present(window,app.root);entry.focus_set()
