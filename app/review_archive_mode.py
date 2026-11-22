# SPDX-License-Identifier: GPL-3.0-or-later
"""Legacy archive tools as a dedicated app mode, without requiring a project."""
import tkinter as tk
from tkinter import ttk
from review_cleanup_archive import ReviewApp as ArchiveApp
from review_theme import dialog,present
from review_dialogs import own_variables
from review_core import Project
from review_icons import apply_window_icon

def confirm_archive(app,parent=None):
    if not app.settings.data.getboolean('archive','show_warning'):return True
    parent=parent or app.root;window=dialog(parent,'Archive Tools');page=ttk.Frame(window,padding=22);page.pack(fill='both',expand=True)
    ttk.Label(page,text='Are you sure?',style='Subheading.TLabel').pack(anchor='w')
    message=('These tools are already integrated into the main ClipComb Pro app. The Archive Tools menu is a legacy option DEDICATED to finding and trimming / combing overlapping clips in your storage. The main app provides this functionality, however this option still exists in case you prefer to ONLY use this functionality.\n\n'
             'NOTE: The Archive Tools menu is not fully integrated into the Projects system of ClipComb Pro. Think of it like managing or trimming your clips OUTSIDE of ClipComb Pro.')
    ttk.Label(page,text=message,wraplength=610,justify='left').pack(anchor='w',pady=16)
    options=ttk.Frame(page);options.pack(fill='x',pady=(0,16))
    skip=tk.BooleanVar(value=False);ttk.Checkbutton(options,text="Don't Show Again",variable=skip).pack(side='left')
    start=tk.BooleanVar(value=app.settings.data.getboolean('archive','start_on_launch'));ttk.Checkbutton(options,text='Always start in Archive Tools',variable=start).pack(side='right')
    result=[];buttons=ttk.Frame(page);buttons.pack(fill='x')
    def accept():
        if skip.get():app.settings.data['archive']['show_warning']='no';app.settings.save()
        app.settings.data['archive']['start_on_launch']='yes' if start.get() else 'no';app.settings.save()
        result.append(True);window.destroy()
    app.button(buttons,'Back',window.destroy).pack(side='left');app.button(buttons,'Open',accept,True).pack(side='right')
    window.archive_warning_controls={'open':accept,'back':window.destroy,'skip':skip,'start':start}
    own_variables(window,skip,start);present(window,parent);window.wait_window()
    if parent!=app.root and parent.winfo_exists():parent.grab_set()
    return bool(result)

class ArchiveWindow(ArchiveApp):
    def __init__(self,root,host):
        super().__init__(root,host)
        variables=[v for owner in (self,self.compare) for v in vars(owner).values() if isinstance(v,tk.Variable)]
        variables.extend(card[4] for card in self.compare.cards)
        own_variables(root,*(v for v in variables if isinstance(v,tk.Variable)))
        self.logo.project('archive',lambda:self.settings_ready and not self.busy and not self.compare.priming)
    def close(self):
        if self.busy:return super().close()
        app=self.host.app;project_root=app.project.root if app.project else None
        self.logo.close()
        super().close();app.busy=False
        app.root.deiconify();app.root.state(self.main_state);app.viewer.resume()
        if project_root:
            try:
                app.project.scan();app.reset_view();app.populate()
                clip=next((c for c in app.visible_clips() if not c.get('missing')),None)
                if clip:app.load_clip(clip['id'],autoplay=False)
                app.status.set('Archive tools closed. Project sources were rescanned; review changed sources before exporting.')
            except (OSError,ValueError) as error:app.status.set(str(error))
        else:app.root.after_idle(app.projects_dialog)
        if hasattr(app,'queue_view'):app.queue_view.resume()

def open_archive(host,parent=None):
    app=host.app
    if not confirm_archive(app,parent):return
    if not app.confirm_leave():return
    if app.project and app.project.review_changed:
        app.project=app.project_store.open(app.project.root,project_file=app.project.path);app.current_id=None;app.history.clear()
    host.review(notify=False);app.stop_frame_repeat();app.cancel_scrubbing();app.magnifier.hide()
    if app.waveforms:app.waveforms.cancel(wait=True)
    app.remember_position()
    if app.mixer:app.mixer.clear()
    if hasattr(app,'queue_view'):app.queue_view.suspend()
    for window in list(app.root.winfo_children()):
        if isinstance(window,tk.Toplevel) and window.title()=='Projects':window.destroy()
    state=app.root.state();geometry=app.root.geometry();app.viewer.suspend();app.root.withdraw()
    window=tk.Toplevel(app.root);window.withdraw();window.review_palette=app.palette;apply_window_icon(window)
    try:
        archive=ArchiveWindow(window,host);archive.main_state=state
        app.busy=True;window.geometry(geometry);window.state(state);window.deiconify()
        window.bind('<Escape>',lambda e:archive.close());host.archive_window=archive
    except BaseException:
        window.destroy();app.root.deiconify();app.root.state(state);app.busy=False;app.viewer.resume()
        if hasattr(app,'queue_view'):app.queue_view.resume()
        raise
