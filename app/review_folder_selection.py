# SPDX-License-Identifier: GPL-3.0-or-later
"""Project-scoped folder choices shared by export and bulk sorting."""
import uuid
from review_folders import names,EXTRA


def ordered_folders(project):
    configured=names(project)
    return {role:configured[role] for role in ('Used','Unused','Kept','Deleted',*EXTRA) if role in configured}


def export_folders(project):
    saved=project.data.get('export_folders')
    selected=saved if isinstance(saved,list) else ['Used']
    return [role for role in ordered_folders(project) if role in selected]


def remember_export_folders(project,selected):
    """Persist just this preference against the last saved review checkpoint."""
    from review_core import read_json,atomic_json
    selected=[role for role in ordered_folders(project) if role in selected]
    if project.data.get('export_folders')==selected:return
    if not project.path.exists():
        project.data['export_folders']=selected;project.dirty=True;return
    saved=read_json(project.path)
    if saved.get('transaction','')!=project.data.get('transaction',''):
        raise ValueError('This project changed in another window. Reopen it before changing export folders.')
    transaction=uuid.uuid4().hex;saved.update(export_folders=selected,transaction=transaction)
    atomic_json(project.path,saved)
    project.data.update(export_folders=selected,transaction=transaction)


class FolderChoices:
    def __init__(self,parent,project,selected,title,on_change=None,variables=None):
        import tkinter as tk
        from tkinter import ttk
        self.frame=ttk.LabelFrame(parent,text=title,padding=(10,6));self.variables=variables if variables is not None else {};self.controls=[]
        self.on_change=on_change
        for index,(role,name) in enumerate(ordered_folders(project).items()):
            variable=self.variables.get(role)
            if variable is None:variable=tk.BooleanVar(value=role in selected);self.variables[role]=variable
            control=ttk.Checkbutton(self.frame,text=name,variable=variable,command=self.changed)
            control.grid(row=index//4,column=index%4,sticky='w',padx=(0,20),pady=3);self.controls.append(control)
        for column in range(4):self.frame.columnconfigure(column,weight=1,uniform='folder_choices')
    def selected(self):return [role for role,var in self.variables.items() if var.get()]
    def changed(self):
        if self.on_change:self.on_change()
    def set_selected(self,selected):
        for role,var in self.variables.items():var.set(role in selected)
