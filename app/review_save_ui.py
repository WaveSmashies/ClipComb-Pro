# SPDX-License-Identifier: GPL-3.0-or-later
"""Save feedback and an owned snapshot window above the native video surface."""
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk,ImageOps
from review_theme import dialog

class SaveNotice:
    def __init__(self,app):
        self.window=dialog(app.root,'Saving project');self.window.overrideredirect(True)
        edge='#34404e' if sum(bytes.fromhex(app.palette['background'][1:]))>400 else '#d3dbe6'
        self.window.configure(bg=edge);self.label=ttk.Label(self.window,text='Save in progress...',style='Subheading.TLabel',padding=22)
        self.label.pack(padx=2,pady=2);self.window.update_idletasks()
        x=app.root.winfo_rootx()+(app.root.winfo_width()-self.window.winfo_reqwidth())//2;y=app.root.winfo_rooty()+(app.root.winfo_height()-self.window.winfo_reqheight())//2
        self.window.geometry(f'{x:+d}{y:+d}');self.window.deiconify();self.window.lift()
    def success(self):self.label.configure(text='Save successful');self.window.update_idletasks()
    def close(self):self.window.destroy()

class ProgressNotice:
    def __init__(self,app,text):
        from review_spinner import Spinner
        self.window=dialog(app.root,text);self.window.overrideredirect(True)
        edge='#34404e' if sum(bytes.fromhex(app.palette['background'][1:]))>400 else '#d3dbe6'
        self.window.configure(bg=edge)
        page=ttk.Frame(self.window,padding=(32,20));page.pack(padx=2,pady=2)
        self.spinner=Spinner(page,88);self.spinner.pack();self.spinner.start()
        ttk.Label(page,text=text,style='Subheading.TLabel').pack(pady=(8,0))
        self.window.update_idletasks()
        x=app.root.winfo_rootx()+(app.root.winfo_width()-self.window.winfo_reqwidth())//2
        y=app.root.winfo_rooty()+(app.root.winfo_height()-self.window.winfo_reqheight())//2
        self.window.geometry(f'{x:+d}{y:+d}');self.window.deiconify();self.window.lift()
    def close(self):self.spinner.stop();self.window.destroy()

class FrozenPreview:
    def __init__(self,app,picture):
        self.app=app;frame=app.video_frame;self.window=tk.Toplevel(frame.winfo_toplevel());self.window.withdraw();self.window.overrideredirect(True)
        self.window.transient(frame.winfo_toplevel());width,height=max(1,frame.winfo_width()),max(1,frame.winfo_height())
        self.photo=ImageTk.PhotoImage(ImageOps.pad(picture,(width,height),method=Image.Resampling.BILINEAR,color=app.palette['video_background']),master=app.root)
        tk.Label(self.window,image=self.photo,bd=0).pack();self.window.geometry(f'{width}x{height}{frame.winfo_rootx():+d}{frame.winfo_rooty():+d}')
        self.window.deiconify();self.window.lift();self.window.update_idletasks()
    def lift(self):self.window.lift()
    def close(self):self.window.destroy();self.photo=None
