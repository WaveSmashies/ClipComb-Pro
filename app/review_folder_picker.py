# SPDX-License-Identifier: GPL-3.0-or-later
"""Folder navigation and explicit create/rename actions in the themed picker."""
import ctypes
import math
import os
from pathlib import Path
import re
import string
import subprocess
import tkinter as tk
from tkinter import ttk


def folder_name(value):
    value=value.strip()
    if (not value or value in ('.','..') or re.search(r'[<>:"/\\|?*\x00-\x1f]',value)
        or value.endswith(('.',' ')) or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?',value)):
        raise ValueError('Enter a valid folder name without slashes, reserved names or trailing dots.')
    return value


class FolderPicker:
    def __init__(self,parent,title,initial=None,csv=False,rename_callback=None):
        from review_theme import dialog,present
        from review_dialogs import reserve_footer
        self.parent,self.csv,self.rename_callback=parent,csv,rename_callback
        self.window=dialog(parent,title);self.window.folder_picker=self
        self.folder=None;self.paths=[];self.result=[]
        page=ttk.Frame(self.window,padding=16);page.pack(fill='both',expand=True)
        bar=ttk.Frame(page);bar.pack(fill='x',pady=(0,8))
        self.value=tk.StringVar();self.hint=tk.StringVar()
        self.entry=ttk.Entry(bar,textvariable=self.value,width=56);self.entry.pack(side='left',fill='x',expand=True,padx=(0,8))
        ttk.Button(bar,text='Go',style='Round.TButton',command=self.go).pack(side='left')
        ttk.Button(bar,text='Up',style='Round.TButton',command=self.up).pack(side='left',padx=(6,0))
        self.items=ttk.Treeview(page,columns=('name',),show='headings',height=12,selectmode='browse')
        self.items.heading('name',text='Folders and CSV files' if csv else 'Folders');self.items.column('name',width=540)
        self.items.pack(fill='both',expand=True)
        ttk.Label(page,textvariable=self.hint,style='Hint.TLabel',wraplength=540).pack(anchor='w',pady=(7,7))
        footer=ttk.Frame(page);footer.pack(fill='x');reserve_footer(footer)
        manage=ttk.Frame(footer);manage.pack(fill='x',pady=(0,8))
        for label,command in [('Create Folder',self.create),('Rename Folder',self.rename),('Open in Explorer',self.explore)]:
            ttk.Button(manage,text=label,style='Round.TButton',command=command).pack(side='left',padx=(0,6))
        buttons=ttk.Frame(footer);buttons.pack(fill='x')
        ttk.Button(buttons,text='Cancel',style='Round.TButton',command=self.window.destroy).pack(side='right')
        ttk.Button(buttons,text='Select CSV' if csv else 'Select folder',style='Primary.TButton',command=self.choose).pack(side='right',padx=(0,6))
        self.entry.bind('<Return>',self.go)
        self.items.bind('<Double-1>',lambda e:self.choose(e,True));self.items.bind('<Return>',lambda e:self.choose(e,True))
        self.window.review_minimum=(440,340)
        from review_dialogs import own_variables
        own_variables(self.window,self.value,self.hint)
        initial=Path(initial) if initial else Path.home()
        self.navigate(initial if initial.is_dir() else initial.parent)
        present(self.window,parent);self.entry.focus_set()

    def navigate(self,folder,select=None,top=False):
        try:
            if folder is None:
                drives=ctypes.windll.kernel32.GetLogicalDrives()
                paths=[Path(f'{letter}:\\') for i,letter in enumerate(string.ascii_uppercase) if drives&(1<<i)]
            else:
                paths=sorted((p for p in folder.iterdir() if p.is_dir() or self.csv and p.suffix.casefold()=='.csv'),
                             key=lambda p:(not p.is_dir(),p.name.casefold()))
        except OSError as error:self.hint.set(str(error));return
        self.folder,self.paths=folder,paths;self.value.set(str(folder) if folder else '');self.hint.set('')
        self.items.delete(*self.items.get_children())
        for i,path in enumerate(paths):self.items.insert('','end',iid=str(i),values=(('›  ' if path.is_dir() else '    ')+(path.name or str(path)),))
        if select in paths:
            index=paths.index(select);self.items.selection_set(str(index));self.items.focus(str(index))
            if top:
                rowheight=int(ttk.Style(self.window).lookup('Treeview','rowheight') or 31)
                # Padding permits even the final real folder to sit at the top,
                # exactly as requested for Up navigation. These are not paths.
                count=max(12,math.ceil(self.items.winfo_height()/rowheight))
                for i in range(count):self.items.insert('','end',iid=f'padding-{i}',values=('',))
                self.items.yview_moveto(index/max(1,len(self.items.get_children())))
            else:self.items.see(str(index))

    def selected(self):
        rows=self.items.selection()
        return self.paths[int(rows[0])] if rows and rows[0].isdecimal() and int(rows[0])<len(self.paths) else None

    def up(self):
        old=self.folder
        self.navigate(old.parent if old and old.parent!=old else None,select=old,top=True)

    def go(self,event=None):
        raw=self.value.get().strip().strip('"')
        if not raw:self.navigate(None);return
        path=Path(raw).expanduser()
        if path.is_dir():self.navigate(path)
        elif self.csv and path.is_file() and path.suffix.casefold()=='.csv':self.result.append(str(path));self.window.destroy()
        else:self.hint.set('Enter an existing folder or select one from the list.')

    def choose(self,event=None,open_folder=False):
        path=self.selected() if event is not None or self.value.get()==str(self.folder) else None
        path=path or (Path(self.value.get().strip().strip('"')).expanduser() if self.value.get().strip() else None)
        if path is None:return
        if path.is_dir() and (self.csv or open_folder):self.navigate(path)
        elif path.is_dir() and not self.csv or self.csv and path.is_file() and path.suffix.casefold()=='.csv':
            self.result.append(str(path));self.window.destroy()
        else:self.hint.set('Choose an existing CSV file.' if self.csv else 'Choose an existing folder.')

    def name_dialog(self,title,initial,accept):
        from review_theme import dialog,present
        window=dialog(self.window,title);page=ttk.Frame(window,padding=18);page.pack(fill='both',expand=True)
        ttk.Label(page,text=title,style='Subheading.TLabel').pack(anchor='w')
        name=tk.StringVar(value=initial);entry=ttk.Entry(page,textvariable=name,width=40);entry.pack(fill='x',pady=12)
        error=tk.StringVar();ttk.Label(page,textvariable=error,style='Hint.TLabel',wraplength=400).pack(anchor='w')
        buttons=ttk.Frame(page);buttons.pack(fill='x',pady=(10,0))
        def commit(event=None):
            try:accept(folder_name(name.get()));window.destroy()
            except (OSError,ValueError) as problem:error.set(str(problem))
        ttk.Button(buttons,text='Create' if not initial else 'Rename',style='Primary.TButton',command=commit).pack(side='right')
        ttk.Button(buttons,text='Cancel',style='Round.TButton',command=window.destroy).pack(side='right',padx=6)
        window.folder_name_controls={'value':name,'commit':commit}
        from review_dialogs import own_variables
        own_variables(window,name,error)
        present(window,self.window);entry.focus_set();entry.selection_range(0,'end');entry.bind('<Return>',commit)

    def create(self):
        parent=self.folder or self.selected()
        if not parent or not parent.is_dir():self.hint.set('Open a parent folder first.');return
        def accept(name):
            target=parent/name;target.mkdir(exist_ok=False);self.navigate(parent,select=target)
        self.name_dialog('Create folder','',accept)

    def rename(self):
        old=self.selected() or self.folder
        if not old or not old.name or not old.is_dir():self.hint.set('Select a folder to rename.');return
        def accept(name):
            target=old.with_name(name)
            if target.exists() and target!=old:raise ValueError('A folder with that name already exists.')
            if self.rename_callback:self.rename_callback(old,target,'before')
            try:old.rename(target)
            except BaseException:
                if self.rename_callback:self.rename_callback(old,target,'failed')
                raise
            if self.rename_callback:self.rename_callback(old,target,'after')
            self.navigate(target.parent,select=target,top=True)
        self.name_dialog('Rename folder',old.name,accept)

    def explore(self):
        path=self.selected() or self.folder
        if not path or not path.is_dir():self.hint.set('Select a folder first.');return
        subprocess.Popen([str(Path(os.environ.get('WINDIR','C:/Windows'))/'explorer.exe'),str(path)])

    def run(self):
        self.window.wait_window()
        return self.result[0] if self.result else None
