# SPDX-License-Identifier: GPL-3.0-or-later
"""Capture either shortcut directly in its cell, with cancellation and timeout."""
import tkinter as tk
from tkinter import ttk
from review_core import DEFAULT_KEYS,DEFAULT_SECONDARY_KEYS,canonical_key
from review_help import Tooltip
from review_bindings import secondary_text

class ShortcutEditor:
    def __init__(self,app,window,parent,bindings,labels,help_text):
        self.app,self.window,self.bindings=app,window,bindings;self.timer=None;self.capturing=None
        self.slot=tk.StringVar(value='Primary');self.value=tk.StringVar();self.hint=tk.StringVar(value='Double-click a Primary or Secondary binding. Press Escape to cancel; or just wait 5 seconds.')
        box=ttk.Frame(parent);box.pack(fill='both',expand=True)
        self.tree=tree=ttk.Treeview(box,columns=('action','key','secondary','help'),show='headings',height=13,selectmode='browse')
        for key,title,width in [('action','Action',335),('key','Primary',125),('secondary','Secondary',125),('help','?',30)]:
            tree.heading(key,text=title);tree.column(key,width=width,minwidth=30 if key=='help' else 90,stretch=key!='help',anchor='center' if key=='help' else 'w')
        tree.pack(side='left',fill='both',expand=True);scroll=ttk.Scrollbar(box,orient='vertical',command=tree.yview);scroll.pack(side='right',fill='y');tree.configure(yscrollcommand=scroll.set)
        for action in DEFAULT_KEYS:tree.insert('','end',iid=action,values=(labels[action],bindings['shortcuts'][action],secondary_text(bindings,action),'?'))
        row=ttk.Frame(parent);row.pack(fill='x',pady=(10,0))
        ttk.Button(row,text='Clear',style='Round.TButton',command=self.clear).pack(side='right')
        ttk.Button(row,text='Reset Shortcut To Default',style='Round.TButton',command=self.reset_selected).pack(side='right',padx=6)
        ttk.Label(parent,textvariable=self.hint,style='Hint.TLabel',wraplength=620).pack(anchor='w',pady=8)
        self.hovered=None;self.tooltip=Tooltip(tree,lambda:help_text.get(self.hovered,''))
        def hover(event):
            action=tree.identify_row(event.y) if tree.identify_column(event.x)=='#4' else None
            if self.hovered!=action:self.tooltip.hide();self.hovered=action;self.tooltip.enter() if action else None
        tree.bind('<Motion>',hover,add='+');tree.bind('<ButtonRelease-1>',self.clicked,add='+');tree.bind('<<TreeviewSelect>>',self.selected)
        tree.bind('<Double-Button-1>',self.begin);window.bind('<Destroy>',lambda e:self.cancel() if e.widget==window else None,add='+')
        window.shortcut_editor={'tree':tree,'slot':self.slot,'value':self.value,'apply':self.apply,'bindings':bindings,'begin':self.begin,'capture':self,'cancel':self.cancel}
    def section(self):return 'shortcuts' if self.slot.get()=='Primary' else 'shortcuts_secondary'
    def column(self):return 'key' if self.slot.get()=='Primary' else 'secondary'
    def refresh(self):
        for action in DEFAULT_KEYS:
            self.tree.set(action,'key',self.bindings['shortcuts'][action]);self.tree.set(action,'secondary',secondary_text(self.bindings,action))
    def selected(self,event=None):
        if self.tree.selection():self.value.set(self.bindings[self.section()][self.tree.selection()[0]])
    def clicked(self,event):
        column=self.tree.identify_column(event.x)
        if column in ('#2','#3'):self.slot.set('Primary' if column=='#2' else 'Secondary');self.selected()
    def begin(self,event):
        action=self.tree.identify_row(event.y);column=self.tree.identify_column(event.x)
        if not action or column not in ('#2','#3'):return
        self.cancel();self.tree.selection_set(action);self.slot.set('Primary' if column=='#2' else 'Secondary')
        self.capturing=(action,self.section(),self.column());self.tree.set(action,self.column(),'Press any key...')
        self.hint.set('Press any key... Middle and side mouse buttons work. '+('Escape binds fullscreen; wait 5 seconds to cancel.' if action=='fullscreen' else 'Escape cancels.'));self.tree.focus_set()
        self.app.recording_key=self.receive
        self.app.wake_updates()
        self.timer=self.window.after(5000,self.cancel)
        return 'break'
    def receive(self,key):
        if not self.capturing:return
        if key=='Escape' and self.capturing[0]!='fullscreen':self.cancel();return
        if key.split('+')[-1] in ('MouseLeft','MouseRight'):
            self.app.recording_key=self.receive;return
        try:
            action,section,column=self.capturing;binding=canonical_key(key);self.cancel()
            self.bindings[section][action]=binding;self.refresh();self.value.set(binding)
            self.hint.set('Binding updated. Save settings to keep it.')
        except ValueError:self.app.recording_key=self.receive
    def cancel(self):
        if self.timer:
            try:self.window.after_cancel(self.timer)
            except tk.TclError:pass
            self.timer=None
        if self.capturing:
            action,section,column=self.capturing
            try:self.refresh();self.hint.set('Capture canceled. The binding was kept.')
            except tk.TclError:pass
        self.capturing=None
        if self.app.recording_key==self.receive:self.app.recording_key=None
    def apply(self):
        if self.tree.selection():
            action=self.tree.selection()[0];value=canonical_key(self.value.get()) if self.value.get().strip() else ''
            self.bindings[self.section()][action]=value;self.refresh()
    def clear(self):self.cancel();self.value.set('');self.apply();self.hint.set('Binding cleared. Save settings to keep it.')
    def reset_selected(self):
        self.cancel()
        if not self.tree.selection():return
        action=self.tree.selection()[0]
        self.value.set((DEFAULT_KEYS if self.section()=='shortcuts' else DEFAULT_SECONDARY_KEYS)[action])
        self.apply();self.hint.set('Selected shortcut reset. Save Settings to keep it.')
