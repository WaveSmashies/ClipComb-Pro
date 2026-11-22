# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit consent before a direct Studio append, with a shared preference."""
from tkinter import ttk
from review_theme import dialog,present

MESSAGE='DO NOT TOUCH DaVinci Resolve while ClipComb Pro is importing your clips. This can break your project!'


def show_warning(app,parent,skip_warning,preference_changed,proceed):
    existing=getattr(parent,'export_warning_window',None)
    if existing is not None and existing.winfo_exists():existing.lift();return existing
    window=dialog(parent,'Export Warning');parent.export_warning_window=window
    window.resizable(False,False)
    page=ttk.Frame(window,padding=20);page.pack(fill='both',expand=True)
    ttk.Label(page,text='WARNING',style='Subheading.TLabel').pack(anchor='w',pady=(0,10))
    ttk.Label(page,text=MESSAGE,wraplength=560).pack(anchor='w')
    footer=ttk.Frame(page);footer.pack(fill='x',pady=(18,0));footer.columnconfigure(1,weight=1)
    toggle=ttk.Checkbutton(footer,text="Don't show export warning",variable=skip_warning,command=preference_changed)
    toggle.grid(row=0,column=0,sticky='w',padx=(0,18))
    def finish(accepted):
        window.destroy()
        if parent.winfo_exists():
            parent.grab_set()
            if accepted:proceed()
    continue_button=ttk.Button(footer,text='Continue',style='Primary.TButton',command=lambda:finish(True))
    continue_button.grid(row=0,column=2,padx=(0,8))
    cancel_button=ttk.Button(footer,text='Cancel',style='Round.TButton',command=lambda:finish(False))
    cancel_button.grid(row=0,column=3)
    window.warning_controls=dict(continue_action=lambda:finish(True),cancel=lambda:finish(False),
        continue_button=continue_button,cancel_button=cancel_button,skip_warning=skip_warning,toggle=toggle,
        preference_changed=preference_changed,message=MESSAGE)
    app.shortcut_tags(window);present(window,parent)
    window.protocol('WM_DELETE_WINDOW',lambda:finish(False))
    window.bind('<Escape>',lambda event:finish(False));cancel_button.focus_set()
    return window
