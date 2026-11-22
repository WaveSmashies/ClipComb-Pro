# SPDX-License-Identifier: GPL-3.0-or-later
"""Confirmed, atomic review decisions across marked clips; media moves on Save."""
from review_folders import names


def marked_clips(project,sources,destination=None):
    return [c for c in project.data['clips'] if c['decision'] in sources and c['decision']!=destination
            and c.get('ranges') and not c.get('missing')]


def refresh_decisions(app,decisions):
    records={c['id']:c for c in app.project.data['clips']}
    for ident,destination in decisions.items():
        clip=records.get(ident)
        if clip:
            clip['decision']=destination;app.project.mark_review(clip)
    if app.clip():app.history.watch(app.clip())
    app.changed(record=False);app.update_decision_buttons()
    if not app.cleanup.refresh_comparison():app.populate()


def move_marked(app,sources,destination):
    if destination not in names(app.project):raise ValueError('Choose a managed destination folder.')
    clips=marked_clips(app.project,sources,destination)
    changes={c['id']:[c['decision'],destination] for c in clips}
    if not changes:return 0
    app.history.record_decisions(changes,'Move Marked Clips To '+names(app.project)[destination])
    refresh_decisions(app,{ident:pair[1] for ident,pair in changes.items()})
    return len(changes)


def move_marked_dialog(app):
    if not app.project or app.busy or app.loading:return
    import tkinter as tk
    from tkinter import ttk
    from review_folder_selection import FolderChoices,ordered_folders
    from review_dialogs import own_variables,reserve_footer
    from review_theme import dialog,present,show_error
    window=dialog(app.root,'Move All Clips With Marks To…')
    window.resizable(False,False)
    page=ttk.Frame(window,padding=20);page.pack(fill='both',expand=True)
    ttk.Label(page,text='Are you sure?',style='Subheading.TLabel').pack(anchor='w',pady=(0,8))
    ttk.Label(page,text='This will move ALL clips which have marked moments from the selected folders into the folder you choose below. This can be undone with the Undo button.',wraplength=620).pack(anchor='w')
    ttk.Label(page,text='Files move only when you save the project. Bookmarks alone are not marked moments.',style='Hint.TLabel',wraplength=620).pack(anchor='w',pady=(6,10))
    choices=FolderChoices(page,app.project,['Unused'],'Folders To Move From')
    choices.frame.pack(fill='x')
    summary=tk.StringVar();ttk.Label(page,textvariable=summary,style='Hint.TLabel').pack(anchor='w',pady=(10,6))
    footer=ttk.Frame(page);footer.pack(fill='x',pady=(8,0));reserve_footer(footer)
    cancel=ttk.Button(footer,text='Cancel',style='Round.TButton',command=window.destroy);cancel.grid(row=0,column=0,sticky='w',padx=(0,8),pady=3)
    buttons={}
    def apply(destination):
        try:
            count=move_marked(app,choices.selected(),destination)
            window.destroy()
            app.status.set(f'{count:,} clips with marks → {names(app.project)[destination]} on next save. Undo reverses the whole move.')
        except (ValueError,OSError) as error:show_error(window,'Could Not Move Clips',str(error))
    for index,(role,name) in enumerate(ordered_folders(app.project).items(),1):
        button=ttk.Button(footer,text=name,style='Primary.TButton' if role=='Used' else 'Round.TButton',command=lambda r=role:apply(r))
        button.grid(row=(index-1)//4,column=1+(index-1)%4,sticky='w',padx=(0,6),pady=3);buttons[role]=button
    cancel.grid_configure(row=(len(buttons)-1)//4)
    def update():
        sources=choices.selected();count=len(marked_clips(app.project,sources))
        summary.set(f'{count:,} '+('clip' if count==1 else 'clips')+' with marks in the selected folders. Choose a destination below.')
        for role,button in buttons.items():button.configure(state='normal' if marked_clips(app.project,sources,role) else 'disabled')
    choices.on_change=update;update()
    window.bulk_controls=dict(folders=choices,buttons=buttons,apply=apply,cancel=window.destroy,cancel_button=cancel,summary=summary)
    own_variables(window,summary,*choices.variables.values())
    app.shortcut_tags(window);present(window,app.root);cancel.focus_set()
    return window
