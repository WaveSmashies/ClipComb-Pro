# SPDX-License-Identifier: GPL-3.0-or-later
"""Always-available tutorial and a per-launch reminder until explicitly hidden."""
import os
import tkinter as tk
from tkinter import ttk
from review_theme import dialog,present
from review_dialogs import own_variables

STEPS=()
VIDEO='https://youtu.be/nMiXShHDSD8'
RESOLVE_WORKFLOW='Use a dedicated selects timeline for ClipComb Pro imports, then copy clips into your main editing timeline. ClipComb reuses compatible tracks and adds only missing tracks.'


def should_start(config):return not config.getboolean('dont_show',fallback=False)


def offer_tutorial(app,parent=None,automatic=False):
    cfg=app.settings.data['tutorial']
    if automatic:
        if getattr(app,'tutorial_offered',False) or not should_start(cfg):return
        app.tutorial_offered=True
    existing=getattr(app,'tutorial_window',None)
    if existing and existing.winfo_exists():existing.lift();return existing
    previous=app.root.grab_current();archive=getattr(app.cleanup,'archive_window',None)
    parent=parent or previous or (archive.root if archive and archive.root.winfo_exists() else app.root)
    if app.mixer and app.mixer.active:app.mixer.set_pause(True)
    if app.cleanup.compare and app.cleanup.compare.playing:app.cleanup.compare.hold()
    app.cancel_scrubbing();app.stop_frame_repeat()
    window=dialog(parent,'Tutorial');app.tutorial_window=window
    page=ttk.Frame(window,padding=20);page.pack(fill='both',expand=True)
    text=tk.Text(page,height=4,width=90,wrap='word',bd=0,highlightthickness=0,bg=app.palette['background'],fg=app.palette['text'],font=('Segoe UI',11))
    text.pack(fill='x',pady=(0,12));text.tag_configure('emphasis',font=('Segoe UI',11,'bold','italic'))
    text.insert('end','Never used ClipComb Pro? It is ');text.insert('end','HIGHLY RECOMMENDED','emphasis')
    text.insert('end'," to watch the tutorial! It includes some basic information on how the app works, how to sort clips, how to import them into your editing software and just what all these darn settings are for.")
    text.configure(state='disabled')
    surface=tk.Frame(page,bg='#000000',width=800,height=450);surface.pack(fill='both',expand=True)
    status=tk.StringVar(value='Loading tutorial…');ttk.Label(page,textvariable=status,style='Hint.TLabel').pack(anchor='w',pady=(4,6))
    buttons=ttk.Frame(page);buttons.pack(fill='x')
    skip=tk.BooleanVar(value=cfg.getboolean('dont_show',fallback=False))
    ttk.Checkbutton(buttons,text="Don't show this again",variable=skip).pack(side='left')
    app.button(buttons,'Close',lambda:window.destroy(),True).pack(side='right')
    app.button(buttons,'Watch On YouTube',lambda:os.startfile(VIDEO)).pack(side='right',padx=8)
    from review_tutorial_host import EmbeddedTutorial
    host=EmbeddedTutorial(app,surface,status);window.tutorial_host=host
    destroy_window=window.destroy
    def destroy():
        host.close()
        destroy_window()
    window.destroy=destroy
    window.protocol('WM_DELETE_WINDOW',destroy)
    def closed(event):
        if event.widget!=window:return
        host.close();cfg['dont_show']='yes' if skip.get() else 'no';app.settings.save();app.tutorial_window=None
        if previous and previous.winfo_exists():previous.grab_set()
    window.bind('<Destroy>',closed,add='+')
    window.tutorial_controls=dict(skip=skip,close=window.destroy,status=status)
    own_variables(window,skip,status);window.review_minimum=(680,520);present(window,parent)
    return window
