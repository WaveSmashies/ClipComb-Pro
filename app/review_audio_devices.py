# SPDX-License-Identifier: GPL-3.0-or-later
"""Output device choices use the same playback backend as the app."""
import tkinter as tk
from tkinter import ttk
from mpv_native import Mpv


def devices(library):
    player=Mpv(library,{'config':'no','load-scripts':'no','vo':'null','vid':'no','idle':'yes'})
    try:
        return [('auto','Default')]+[(d['name'],d['description']) for d in player.get('audio-device-list',[]) if d['name'].startswith('wasapi/')]
    finally:player.close()


class DevicePicker(ttk.LabelFrame):
    def __init__(self,parent,variable,enumerate_devices):
        super().__init__(parent,text='Audio Device',padding=12)
        self.variable,self.enumerate=variable,enumerate_devices;self.rows=[]
        self.label=tk.StringVar();self.box=ttk.Combobox(self,textvariable=self.label,state='readonly',width=48)
        self.box.pack(side='left',fill='x',expand=True)
        self.box.bind('<<ComboboxSelected>>',lambda e:self.variable.set(self.rows[self.box.current()][0]))
        ttk.Button(self,text='Refresh',command=self.refresh,style='Round.TButton').pack(side='left',padx=(8,0))
        self.trace=self.variable.trace_add('write',self.show)
        self.bind('<Destroy>',lambda event:self.variable.trace_remove('write',self.trace) if event.widget==self else None)
        self.refresh()
    def refresh(self):
        try:self.rows=self.enumerate()
        except (OSError,RuntimeError,ValueError):self.rows=[('auto','Default')]
        current=self.variable.get()
        if current not in [r[0] for r in self.rows]:self.rows.append((current,'Unavailable · '+current))
        labels=[name for _,name in self.rows]
        # Duplicate friendly names can refer to different endpoints.
        labels=[name+f' ({i+1})' if labels.count(name)>1 else name for i,name in enumerate(labels)]
        self.box.configure(values=labels);self.show()
    def show(self,*_):
        for i,(ident,_) in enumerate(self.rows):
            if ident==self.variable.get():self.box.current(i);return
