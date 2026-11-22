# SPDX-License-Identifier: GPL-3.0-or-later
"""ClipComb Pro: review once, sort on save, keep source ranges for a later Resolve bridge."""
import argparse
from fractions import Fraction
from datetime import datetime
import configparser
import json
import os
from pathlib import Path
from queue import Queue, Empty
import shutil
import sys
import threading
import time
import uuid
from review_queue import QUEUE_CATEGORIES
import tkinter as tk
from types import SimpleNamespace
from tkinter import ttk, filedialog, colorchooser
from PIL import Image,ImageTk
from review_windows import initialize_dpi
initialize_dpi()

from review_brand import APP_NAME, PROJECT_URL, VERSION
from review_icons import install_app_icons, set_taskbar_identity
from review_core import (Settings, Project, STATUSES, DEFAULT_KEYS, SpeedCycle, SlowCycle, canonical_key,
                         key_from_event, mouse_binding, probe_media, PROJECT_FILE, profile_for_name)
from review_input import ExtraMouseButtons
from review_player import Mixer, find_mpv
from review_magnifier import Magnifier
from review_waveform import Waveforms,waveform_folder,delete_generated
from review_settings import PlaybackEditor, ThemeEditor, AudioEditor
from review_dialogs import ScrollPage,reserve_footer,own_variables
from review_transport import Transport
import review_audio as audio_layout
from review_export_ui import export_dialog
from review_history import History
from review_markers import Markers
from review_cleanup import Cleanup
import review_theme as theme
import review_help as help_ui
from review_timeline import RangeTimeline, timestamp
from review_timecode import timecode,fps_text
from review_theme import (install_theme, BG, PANEL, VIDEO, TEXT, MUTED, ACCENT, GREEN,
                          dialog, present, show_error, pick_path, dark_title)


def application_folder():
    return Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent


ACTION_LABELS = {
    'star':'Add / edit clip Star','review_page':'Review page','compare_page':'Compare overlaps page',
    'marker':'Add / edit bookmark at playhead','trim_file':'Trim file mode','create_trim':'Confirm Trim',
    'snap_playhead':'Snap playhead to nearby elements',
    'undo':'Undo review action','redo':'Redo review action',
    'save': 'Save project and move sorted clips', 'export': 'Export moments to editing software',
    'play': 'Play / pause', 'back': 'Skip back', 'forward': 'Skip forward',
    'back_large': 'Skip back (large)', 'forward_large': 'Skip forward (large)',
    'used': 'Mark Used', 'deleted': 'Mark Deleted', 'previous': 'Previous clip', 'next': 'Next clip',
    'kept': 'Mark Kept', 'unused': 'Mark Unused', 'remove_range': 'Delete selected moment / bookmark / missing clip',
    'fullscreen': 'Toggle fullscreen playback', 'slow': 'Decrease playback speed by 0.1×',
    'frame_back': 'Previous frame (pauses)', 'frame_forward': 'Next frame (pauses)',
    'scrub_to_mouse': 'Move playhead to mouse (hold)',
    'scrub_video': 'Toggle video while scrubbing', 'scrub_audio': 'Toggle audio while scrubbing',
    **{f'speed_{i}': f'Speed {i}× (repeat for quarter steps)' for i in range(1, 6)},
}
PROFILES = {
    'Auto by date': [],
    'File track names': [],
    'Modern OBS': ['All tracks', 'My mic · processed', 'Discord', 'Game sound', 'My mic · raw', 'Track 6'],
    'Legacy OBS': ['My mic · processed', 'Discord', 'Game sound', 'My mic · raw', 'Track 5', 'All tracks'],
}
SHORTCUT_HELP = {
 'star':'Open the color and title editor for this clip’s Star.',
 'review_page':'Switch to the Review page.',
 'compare_page':'Open overlap comparison for this clip’s scanned group.',
 'trim_file':'Open the independent keep-on-disk trim plan for this clip. Valid lossless cut points are shown; editor selections are preserved.',
 'create_trim':'Verify the current file-trim plan, then review the concrete replacement/copy operation before it is installed.',
 'snap_playhead':'Toggle magnetic snapping. Nearby selection edges and bookmarks attract the playhead; dragged bookmarks snap to the playhead and nearby elements only while enabled. Clicking a bookmark always seeks to its exact frame.',
 'marker':'Add a bookmark at the playhead, or edit the bookmark already on that exact frame. Click its diamond to seek; double-click to edit its name, description and color or delete it. Export attaches bookmarks to clips by default, with an optional timeline placement.',
 'undo':'Undo a marked-moment edit, sorting decision, track mix or audio layout change. Saved folder moves become pending moves back; no file is deleted.',
 'redo':'Reapply the last undone review action. Making a new edit clears the redo history.',
 'save':'Save the project, its marked moments and clip positions, then move clips to the folders matching your sorting decisions.',
 'export':'Export enabled In/Out selections as a timeline XML for free Resolve, or append them directly to an existing Studio timeline. Export saves pending sorting decisions. Original recordings are not rendered or trimmed.',
 'play':'Start or pause playback. At the end of a clip, starts again from the beginning.',
 'back':help_ui.HELP['app','seek_small'], 'forward':help_ui.HELP['app','seek_small'],
 'back_large':help_ui.HELP['app','seek_large'], 'forward_large':help_ui.HELP['app','seek_large'],
 'used':'Mark this clip for use in your video. On Save project, it moves into Used.',
 'deleted':'Mark this clip for your delete pile. On Save project, it moves into Deleted. ClipComb Pro never permanently deletes it.',
 'kept':'Keep this clip for personal viewing. On Save project, it moves into Kept.',
 'unused':'Return this clip to the review pile. On Save project, it moves into Unused.',
 'next':'Open the next clip in the currently filtered review queue.', 'previous':'Open the previous clip in the currently filtered review queue.',
 'remove_range':'Remove the selected In/Out mark from the project. The source video is unchanged.',
 'fullscreen':'Switch between the normal app layout and fullscreen video playback.',
 'slow':'Each press selects 0.9×, 0.8× and so on down to 0.1×, then 1×, and repeats. There is no timeout; choosing another speed starts the sequence again.',
 'frame_back':'Pause and move backward by one decoded video frame.', 'frame_forward':'Pause and move forward by one decoded video frame.',
 'scrub_to_mouse':'Hold this shortcut and move the pointer across the timeline to move the playhead. Release to finish. The video, audio and stopping toggles control the preview and playback afterward.',
 'scrub_video':help_ui.HELP['scrubbing','show_video'], 'scrub_audio':help_ui.HELP['scrubbing','play_audio'],
 **{f'speed_{i}':f'Select {i}× playback. Repeat within the speed-repeat time to cycle through {i}.25×, {i}.5× and {i}.75×, then {i}×. Audio keeps its original pitch.' for i in range(1,6)},
}
from review_tooltip_text import SHORTCUTS
SHORTCUT_HELP.update(SHORTCUTS)
ACTION_LABELS['volume_meter']='Toggle Volume Meter'
ACTION_LABELS['clear_moments']='Clear All Marked Moments'
SHORTCUT_HELP['clear_moments']='Clear all marked In/Out moments on the current clip. In Trim File, clears its keep regions. Undo restores the complete set. Bookmarks and Stars are kept.'
SHORTCUT_HELP['volume_meter']='Show or hide the live output level meter. No additional decoder or audio file is created.'
ACTION_LABELS.update(fast='Increase playback speed by 0.1×',**{f'extra{i}':f'Move To Extra Folder {i}' for i in range(1,5)})
SHORTCUT_HELP.update(slow='Decrease speed by 0.1× per press. Hold for one second to jump to 0.1×.',fast='Increase speed by 0.1× per press, up to 8×.',**{f'extra{i}':'Move the clip to this project’s extra folder on Save Project. Configure the folder in Settings → Other.' for i in range(1,5)})
from review_bindings import default_help
for _action,_text in list(SHORTCUT_HELP.items()):
    SHORTCUT_HELP[_action]=_text.rsplit('\n\nDefault: Primary ',1)[0]+'\n\n'+default_help(_action)


class ReviewApp:
    def __init__(self, root, config_folder=None, start_project=None, show_projects=True):
        self.root = root
        root.withdraw()
        from review_buttons import decorate
        root.bind_all('<Map>',decorate,add='+');root.review_buttons_hook=True
        install_app_icons(root)
        self.settings = Settings(config_folder or application_folder())
        from review_projects import ProjectStore
        self.project_store=ProjectStore(self.settings)
        self.date_audio=self.settings.data.getboolean('audio','date_profiles_enabled')
        self.history=History(self.settings.data['app']['undo_limit'])
        self.project, self.current_id, self.mixer = None, None, None
        self.events, self.generation = Queue(), 0
        self.busy, self.loading, self.pending_autoplay = False, False, None
        self.closed, self.recording_key, self.pressed = False, None, set()
        self.settings_timer = None
        self.scrub_owner = None
        self.native_mouse_down = {}
        self.frame_repeat=None;self.frame_repeat_timer=None
        self.speed = 1.0
        self.cycle = SpeedCycle(float(self.settings.data['app']['speed_reset_seconds']))
        self.slow_cycle = SlowCycle()
        self.fullscreen = False
        self.error_shown = False
        root.title(APP_NAME)
        root.geometry(self.settings.data['app']['geometry'])
        self.windowed_geometry=self.settings.data['app']['geometry']
        root.bind('<Configure>',self.window_configured,add='+')
        from review_ui_scale import UiScale
        self.ui_scale=UiScale(self)
        root.minsize(round(1150*self.ui_scale.factor),round(850*self.ui_scale.factor))
        self.status = tk.StringVar(value='Open a video project folder to begin. Decisions move files only when you save.')
        self.project_title = tk.StringVar(value='No project open')
        self.current_title = tk.StringVar(value='Choose a clip')
        zero=timecode(0,frames=self.settings.data.getboolean('app','timecode_frames'))
        self.time_label = tk.StringVar(value=f'{zero} / {zero}')
        self.fps_label=tk.StringVar(value='Video Framerate: —')
        self.last_action=tk.StringVar(value='None')
        self.speed_label = tk.StringVar(value='1×')
        self.filter = tk.StringVar(value='Unused')
        self.search = tk.StringVar()
        self.summary = tk.StringVar(value='')
        self.mix_rows = []
        self.profile = tk.StringVar(value=audio_layout.selected_profile(self.settings.data['audio']['default_profile'],self.settings.data['audio'],self.date_audio))
        self.scrub_video = tk.BooleanVar(value=self.settings.data.getboolean('scrubbing','show_video'))
        self.scrub_audio = tk.BooleanVar(value=self.settings.data.getboolean('scrubbing','play_audio'))
        self.scrub_stop = tk.BooleanVar(value=self.settings.data.getboolean('scrubbing','stop_playback'))
        self.remember_clip_position = tk.BooleanVar(value=self.settings.data.getboolean('app','remember_position'))
        self.palette = theme.palette_for_settings(self.settings)
        install_theme(root,self.palette)
        from review_windows import incremental_resize_paint
        incremental_resize_paint(root)
        self.wave_choice = tk.StringVar(value='Auto (all tracks)')
        self.wave_status = tk.StringVar(value='')
        self.waveforms = None
        self.auto_moments=tk.BooleanVar(value=self.settings.data.getboolean('app','sort_moments'))
        self.build()
        self.markers = Markers(self)
        from review_stars import Stars
        self.stars=Stars(self)
        self.cleanup = Cleanup(self)
        self.magnifier = Magnifier(self.root, self.video_frame, lambda: self.mixer, self.settings)
        from review_dual import ViewerWorkspace
        self.viewer=ViewerWorkspace(self)
        from review_render import ResizeFinish
        from review_windows import repaint_window
        self.resize_finish=ResizeFinish(root,[root,*self.layout_panes().values(),self.queue_panel,self.moments_panel,self.viewer_panel,self.timeline_panel,self.video_column,self.audio_column],repaint_window,delay=55,live_interval=33)
        self.apply_theme(self.palette)
        self.video_frame.bind('<ButtonPress-1>', self.magnifier.press, add='+')
        self.video_frame.bind('<ButtonRelease-1>', lambda e: self.magnifier.hide(), add='+')
        self.video_frame.bind('<MouseWheel>', self.magnifier.wheel, add='+')
        self.filter.trace_add('write', lambda *_: self.populate())
        self.search.trace_add('write', lambda *_: self.populate())
        root.bind_all('<KeyPress>', self.key_down, add='+')
        root.bind_class('ReviewKeys', '<KeyPress>', self.key_down)
        root.bind_class('ReviewKeys', '<KeyRelease>', self.key_up)
        root.bind_class('ReviewKeys', '<ButtonPress>', self.mouse_down)
        root.bind_class('ReviewKeys', '<ButtonRelease>', self.mouse_up)
        root.bind_class('ReviewKeys', '<Double-Button-3>', self.mouse_double_right)
        root.bind_class('ReviewKeys','<MouseWheel>',lambda e:self.magnifier.wheel(e) if self.magnifier.active else None)
        root.bind_class('ReviewAudioScroll','<MouseWheel>',self.audio_wheel)
        root.bind_all('<ButtonPress>', self.mouse_down, add='+')
        root.bind_all('<ButtonPress-1>',self.selection_clicked,add='+')
        root.bind_all('<ButtonRelease>', self.mouse_up, add='+')
        self.shortcut_tags(root)
        root.bind_all('<KeyRelease>', self.key_up, add='+')
        root.bind('<FocusOut>', lambda e: root.after_idle(self.focus_changed), add='+')
        from review_activity import UpdateTimer
        self.update_timer = UpdateTimer(root, self.tick)
        for window in (root, self.video_column):
            for event_name in ('<FocusIn>', '<FocusOut>', '<Map>', '<Unmap>'):
                window.bind(event_name, self.update_window_changed, add='+')
        self.extra_mouse = ExtraMouseButtons(self.wants_extra_mouse)
        from review_media_keys import MediaPlayPause
        self.media_keys=MediaPlayPause()
        self.apply_media_keys()
        self.root.after_idle(self.present_main)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.wake_updates()
        from review_cache_retention import CacheRetention
        self.retention=CacheRetention(self)
        if start_project:
            self.open_project(start_project)
        elif show_projects:
            root.after(100,self.start_screen)
        root.after(250,self.viewer.restore)
        if show_projects:
            from review_tutorial import offer_tutorial
            root.after(500,lambda:offer_tutorial(self,automatic=True))

    def button(self, parent, text, command, primary=False, **kwargs):
        action=kwargs.pop('shortcut_action',None)
        style='Primary.TButton' if primary else 'Round.TButton'
        try:
            parent_style=parent.cget('style') or parent.winfo_class()
            if ttk.Style(parent).lookup(parent_style,'background')==self.palette['panel']:style='Panel.'+style
        except tk.TclError:pass
        from review_buttons import title
        button=ttk.Button(parent, text=title(text), command=command,style=style, **kwargs)
        if not action:
            action={'save':'save','export':'export','undo_review':'undo','toggle_play':'play',
                    'remove_range':'remove_range','activate':'marker','trim_mode':'trim_file',
                    'render_trim':'create_trim','toggle_snapping':'snap_playhead'}.get(getattr(command,'__name__',''))
        from review_buttons import explanation
        if action:button.review_tooltip=help_ui.Tooltip(button,lambda:self.action_tip(explanation(button.cget('text')) or button.cget('text'),action() if callable(action) else action))
        elif explanation(text):button.review_tooltip=help_ui.Tooltip(button,explanation(text))
        return button

    def shortcut_tags(self, widget):
        # Act before Treeview arrows or focused-button Space bindings can consume a decision.
        if 'ReviewKeys' not in widget.bindtags():
            widget.bindtags(('ReviewKeys', *widget.bindtags()))
        parent = widget
        while parent is not None:
            if parent == getattr(self,'audio_canvas',None):
                if 'ReviewAudioScroll' not in widget.bindtags():
                    tags=tuple(t for t in widget.bindtags() if t!='ReviewKeys')
                    widget.bindtags(('ReviewKeys','ReviewAudioScroll',*tags))
                break
            parent = getattr(parent,'master',None)
        for child in list(widget.children.values()):
            self.shortcut_tags(child)

    def build(self):
        page = ttk.Frame(self.root, padding=(23, 17))
        self.page = page
        page.pack(fill='both', expand=True)
        header = ttk.Frame(page)
        header.pack(fill='x')
        from review_icons import header_logo
        self.brand_logo=ttk.Label(header)
        self.brand_logo.pack(side='left',padx=(0,10))
        self.brand_title=ttk.Label(header,text=APP_NAME,style='Heading.TLabel');self.brand_title.pack(side='left')
        from review_logo import AnimatedLogo
        self.logo=AnimatedLogo(self.brand_logo,self.settings.data.getboolean('theme','light_mode'),waiting=True)
        for text, command, primary in [('Settings', self.settings_dialog, False),
                                       ('Export to editing software', self.export, False),
                                       ('Save project', self.save, True),
                                       ('Projects', self.projects_dialog, False)]:
            self.button(header, text, command, primary).pack(side='right', padx=(7, 0))
        self.dual_button=self.button(header,'Dual Monitor Mode',lambda:self.viewer.toggle());self.dual_button.pack(side='right',padx=(7,0))
        from review_tutorial import offer_tutorial
        self.button(header,'Tutorial',lambda:offer_tutorial(self,self.root)).pack(side='right',padx=(7,0))
        ttk.Label(page, textvariable=self.project_title, style='Hint.TLabel').pack(anchor='w', pady=(1, 14))
        body = ttk.Panedwindow(page, orient='horizontal')
        self.body = body
        body.pack(fill='both', expand=True)
        self.left_stack = ttk.Panedwindow(body,orient='vertical')
        body.add(self.left_stack,weight=1)
        queue = ttk.Frame(self.left_stack, style='Panel.TFrame', padding=12)
        self.queue_panel = queue
        self.left_stack.add(queue, weight=3)
        ttk.Label(queue, text='Review Queue', style='PanelHeading.TLabel').pack(anchor='w')
        summary_row=ttk.Frame(queue,style='Panel.TFrame');summary_row.pack(fill='x',pady=(3,10))
        ttk.Label(summary_row,textvariable=self.summary,style='PanelHint.TLabel').pack(side='left')
        ttk.Label(summary_row,text='CTRL + Scroll to change thumbnail size',style='PanelHint.TLabel',font=('Segoe UI',8)).pack(side='right')
        filters = ttk.Frame(queue, style='Panel.TFrame')
        filters.pack(fill='x')
        self.filter_combo=ttk.Combobox(filters,textvariable=self.filter,state='readonly',width=13,values=QUEUE_CATEGORIES)
        self.filter_combo.pack(side='left')
        help_ui.badge(filters,help_ui.HELP['filter'],True).pack(side='left',padx=(0,6))
        ttk.Entry(filters, textvariable=self.search, width=12).pack(side='left', fill='x', expand=True)
        help_ui.badge(filters,help_ui.HELP['search'],True).pack(side='left')
        tree_frame = ttk.Frame(queue)
        tree_frame.pack(fill='both', expand=True, pady=(9, 8))
        self.tree = ttk.Treeview(tree_frame, columns=('clip','activity','state'), show='headings', selectmode='browse')
        self.tree.heading('clip', text='Clip')
        self.tree.heading('state', text='Decision')
        self.tree.column('clip', width=220, minwidth=100)
        self.tree.column('activity',width=32,minwidth=32,stretch=False,anchor='center')
        self.tree.column('state', width=75, minwidth=65, stretch=False)
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview,style='Queue.Vertical.TScrollbar')
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.tree_selected)
        self.tree.bind('<Button-3>',self.clip_context_menu)
        self.tree.tag_configure('missing', foreground=MUTED)
        from review_queue import QueueView
        self.queue_view=QueueView(self,tree_frame,filters,scrollbar)
        self.button(queue, 'Rescan project folders', self.rescan).pack(fill='x')
        main = ttk.Frame(body, padding=(15, 0, 0, 0))
        self.main_panel = main
        body.add(main, weight=4)
        ttk.Label(main, textvariable=self.current_title, style='Subheading.TLabel').pack(anchor='w', pady=(0, 8))
        self.main_stack = ttk.Panedwindow(main,orient='vertical')
        self.main_stack.pack(fill='both',expand=True)
        self.viewer_panel = ttk.Frame(self.main_stack)
        self.main_stack.add(self.viewer_panel,weight=4)
        playback = ttk.Panedwindow(self.viewer_panel, orient='horizontal')
        self.playback = playback
        playback.pack(fill='both', expand=True)
        from review_dual import VideoContainer
        self.video_column=VideoContainer(playback,bg=self.palette['background'])
        playback.add(self.video_column, weight=5)
        self.video_frame = tk.Frame(self.video_column, bg=VIDEO, takefocus=True, width=720, height=320)
        self.video_frame.pack(fill='both',expand=True)
        self.video_frame.bind('<Button-1>', lambda e: self.video_frame.focus_set())
        self.audio_column=ttk.Frame(playback,width=240)
        playback.add(self.audio_column,weight=1)
        self.history_panel=ttk.Frame(self.audio_column,height=86,padding=(10,6))
        self.history_panel.pack(side='bottom',fill='x');self.history_panel.pack_propagate(False)
        history_buttons=ttk.Frame(self.history_panel);history_buttons.pack(side='bottom',fill='x')
        self.undo_button=self.button(history_buttons,'↶ Undo',self.undo_review);self.undo_button.pack(side='left',padx=(0,5))
        self.redo_button=self.button(history_buttons,'↷ Redo',lambda:self.undo_review(True),shortcut_action='redo');self.redo_button.pack(side='left')
        ttk.Label(self.history_panel,text='Last Action:',style='Hint.TLabel').pack(anchor='w')
        self.action_label=ttk.Label(self.history_panel,textvariable=self.last_action)
        self.action_label.pack(anchor='w',fill='x')
        self.action_label.bind('<Configure>',lambda e:self.transport.resize_update.request() if hasattr(self,'transport') else None)
        self.history_panel.bind('<Configure>',self.history_panel_resized)
        help_ui.Tooltip(self.action_label,self.action_detail)
        self.undo_button.review_tooltip.text=lambda:self.action_detail(False)+'\n'+self.shortcut_hint('undo')
        self.redo_button.review_tooltip.text=lambda:self.action_detail(True)+'\n'+self.shortcut_hint('redo')
        audio = ttk.Frame(self.audio_column, style='Panel.TFrame', padding=(12, 10), width=240)
        self.audio_panel = audio
        audio.pack(fill='both',expand=True)
        ttk.Label(audio, text='Audio Mixer', style='PanelHeading.TLabel').pack(anchor='w')
        ttk.Label(audio, text='Listen to any combination', style='PanelHint.TLabel').pack(anchor='w', pady=(2, 7))
        profile_row=ttk.Frame(audio,style='Panel.TFrame');profile_row.pack(fill='x',pady=(0,5))
        help_ui.badge(profile_row,help_ui.HELP['profile'] if self.date_audio else 'Configured tracks uses the names set in Settings → Audio. File track names reads the recording metadata. This choice is saved per clip.\n\nDefault: Configured tracks.',True).pack(side='right')
        profile = ttk.Combobox(profile_row, textvariable=self.profile, values=audio_layout.profile_choices(self.date_audio), state='readonly', width=25)
        self.profile_combo=profile
        profile.pack(fill='x', pady=(0, 5))
        profile.bind('<<ComboboxSelected>>', lambda e: self.change_profile())
        track_area = ttk.Frame(audio,style='Panel.TFrame')
        track_area.pack(fill='both',expand=True)
        self.audio_canvas = tk.Canvas(track_area,bg=PANEL,highlightthickness=0,width=200,height=160)
        self.audio_scroll = ttk.Scrollbar(track_area,orient='vertical',command=self.audio_canvas.yview)
        self.audio_canvas.configure(yscrollcommand=self.audio_scroll.set)
        self.audio_canvas.pack(side='left',fill='both',expand=True)
        self.audio_frame = ttk.Frame(self.audio_canvas, style='Panel.TFrame')
        self.audio_window = self.audio_canvas.create_window(0,0,window=self.audio_frame,anchor='nw')
        self.audio_frame.bind('<Configure>',self.sync_audio_scroll)
        self.audio_canvas.bind('<Configure>',self.resize_audio_canvas)
        self.audio_overflow=False
        self.audio_hint = ttk.Label(self.audio_frame, text='Track names appear here\nwhen a clip is opened.', style='PanelHint.TLabel')
        self.audio_hint.pack(anchor='w', pady=12)
        scrub_controls = ttk.Frame(audio, style='Panel.TFrame')
        scrub_controls.pack(fill='x', pady=(6,0))
        from review_level_meter import LevelMeter
        self.level_meter=LevelMeter(scrub_controls,self)
        self.meter_on=tk.BooleanVar(value=self.settings.data.getboolean('app','volume_meter'))
        if self.meter_on.get():self.level_meter.pack(side='right',padx=(6,0),anchor='se')
        for text, variable, option in [('Show video while scrubbing',self.scrub_video,'show_video'),
                                       ('Play audio while scrubbing',self.scrub_audio,'play_audio'),
                                       ('Stop playback on\nplayhead move',self.scrub_stop,'stop_playback')]:
            row=help_ui.check(scrub_controls,text,variable,help_ui.HELP['scrubbing',option],panel=True,command=lambda key=option:self.scrub_options_changed(key))
            row.pack(anchor='w',pady=2)
            if option=='play_audio':self.scrub_audio_control=row.control
        self.scrub_audio_control.configure(state='normal' if self.scrub_video.get() else 'disabled')
        help_ui.check(scrub_controls,'Remember clip position',self.remember_clip_position,
                      help_ui.HELP['app','remember_position'],panel=True,command=self.remember_option_changed).pack(anchor='w',pady=2)
        help_ui.check(scrub_controls,'Show volume meter',self.meter_on,'Show the live post-mix audio level, including track gains and mute. No extra audio decoder or files are used.',panel=True,command=self.toggle_volume_meter).pack(anchor='w',pady=2)
        audio_buttons = ttk.Frame(audio, style='Panel.TFrame')
        audio_buttons.pack(fill='x', pady=(6, 0))
        self.button(audio_buttons, 'Mute all', lambda: self.mix_preset('mute')).pack(side='left')
        self.button(audio_buttons, 'Separate', lambda: self.mix_preset('separate')).pack(side='left', padx=(5, 0))
        audio_buttons.pack_configure(side='bottom',before=track_area)
        scrub_controls.pack_configure(side='bottom',before=track_area)
        self.transport=Transport(self.video_column,self)
        self.transport.pack(side='bottom',fill='x',pady=(5,0),before=self.video_frame)
        self.play_button=self.transport.buttons['play']
        self.back_button=self.transport.buttons['small_back'];self.forward_button=self.transport.buttons['small_forward']
        self.timeline_panel = ttk.Frame(self.main_stack)
        self.main_stack.add(self.timeline_panel,weight=2)
        wave_bar = ttk.Frame(self.timeline_panel)
        wave_bar.pack(fill='x',pady=(7,5))
        ttk.Label(wave_bar,text='Waveform',style='Hint.TLabel').pack(side='left',padx=(0,8))
        self.wave_combo = ttk.Combobox(wave_bar,textvariable=self.wave_choice,state='readonly',width=25)
        self.wave_combo.pack(side='left')
        help_ui.badge(wave_bar,help_ui.HELP['waveform']).pack(side='left',padx=4)
        self.wave_combo.bind('<<ComboboxSelected>>',self.waveform_changed)
        self.regenerate_button=self.button(wave_bar,'Regenerate Waveform',self.regenerate_waveform)
        self.regenerate_button.pack(side='left',padx=(6,0))
        ttk.Label(wave_bar,textvariable=self.wave_status,style='Hint.TLabel').pack(side='left',padx=10)
        self.timeline = RangeTimeline(self.timeline_panel, self.seek, self.ranges_changed, self.select_range, self.scrub_event)
        self.timeline.interaction_allowed=lambda:not self.busy and not self.loading and not (hasattr(self,'magnifier') and self.magnifier.active)
        self.timeline.right_interacts_existing=lambda:self.settings.data.getboolean('timeline','right_click_existing')
        self.timeline.snap_enabled=lambda:self.settings.data.getboolean('snapping','enabled')
        self.timeline.frame_time=self.frame_time
        self.timeline.frame_duration=lambda:1/float(Fraction(str(self.clip_fps())))
        self.timeline.format_time=self.format_time
        self.timeline.set_palette(self.palette)
        if hasattr(self,'markers'):self.markers.refresh();self.timeline.draw()
        if hasattr(self,'brand_logo'):
            from review_icons import header_logo
            self.logo.set_light(self.settings.data.getboolean('theme','light_mode'))
        if hasattr(self,'queue_view'):self.queue_view.apply_theme()
        self.timeline.pack(fill='both',expand=True)
        lower = ttk.Frame(self.timeline_panel)
        lower.pack(side='bottom',fill='x',pady=(6,0))
        ttk.Label(lower,text='Right-drag to mark · Drag edges to trim · Double right-click to remove',
                  style='Hint.TLabel').pack(anchor='w',pady=(0,5))
        decisions = ttk.Frame(lower)
        decisions.pack(fill='x')
        self.decision_row=decisions
        decisions.review_manual_scale=True
        self.decision_buttons={}
        from review_folders import BASE,EXTRA
        for role in BASE+EXTRA:
            button=self.button(decisions,'Move To '+role,lambda c=role:self.decide(c),role=='Used',shortcut_action=role.lower())
            button.review_tooltip=help_ui.Tooltip(button,lambda c=role:self.action_tip(self.folder_move_help(c),c.lower()))
            self.decision_buttons[role]=button
        self.use_button=self.decision_buttons['Used'];self.unused_button=self.decision_buttons['Unused']
        from review_render import FrameUpdate
        self.decision_update=FrameUpdate(decisions,self.layout_decisions)
        decisions.bind('<Configure>',self.decision_update.request,add='+')
        self.entire_button=self.button(decisions,'Use Entire Clip',self.use_entire_clip)
        self.undo_trim_button=self.button(decisions,'Undo Trim',lambda:self.cleanup.undo_trim())
        self.undo_trim_available=False
        file_actions=ttk.Frame(decisions);self.file_actions=file_actions
        self.button(file_actions,'Open file in video player',self.open_clip_external).pack(side='left',padx=(0,5))
        self.button(file_actions,'Open file location',lambda:self.open_clip_external(location=True)).pack(side='left')
        from review_bulk_sort import move_marked_dialog
        self.bulk_sort_button=self.button(file_actions,'Move All Clips With Marks To…',lambda:move_marked_dialog(self))
        self.bulk_sort_button.pack(side='left',padx=(5,0))
        self.bulk_sort_button.review_tooltip=help_ui.Tooltip(self.bulk_sort_button,'Choose source folders, then move every clip with marked In/Out moments to a destination folder. The move is one Undo action; files move on Save Project.')
        self.layout_decisions()
        self.timeline.pack_forget()
        self.timeline.pack(fill='both',expand=True)
        ranges_frame = ttk.Frame(self.left_stack, style='Panel.TFrame', padding=10)
        self.moments_panel = ranges_frame
        self.left_stack.add(ranges_frame,weight=1)
        range_header = ttk.Frame(ranges_frame, style='Panel.TFrame')
        range_header.pack(fill='x')
        ttk.Label(range_header, text='Marked Moments', style='PanelHeading.TLabel').pack(side='left')
        help_ui.badge(range_header,help_ui.HELP['export'],True).pack(side='left',padx=5)
        moment_buttons=ttk.Frame(ranges_frame,style='Panel.TFrame')
        moment_buttons.pack(side='bottom',fill='x',pady=(6,0))
        button=self.button(moment_buttons,'Edit times',self.edit_range);button.preserve_range_selection=True;button.pack(side='right')
        button=self.button(moment_buttons,'Remove',self.remove_range);button.preserve_range_selection=True;button.pack(side='right',padx=(0,5))
        help_ui.check(moment_buttons,'Automatically sort\nselections\nchronologically',self.auto_moments,
                      'Keep marked moments in source-time order. Turn off to drag the three-line handles into a custom order. This order is used by exports and Studio imports.\n\nDefault: On.',panel=True,command=self.moment_sort_changed).pack(side='left')
        range_list = ttk.Frame(ranges_frame)
        range_list.pack(fill='both',expand=True, pady=(7, 0))
        self.range_tree = ttk.Treeview(range_list, columns=('order','enabled', 'start', 'end', 'length'),
                                       show='headings', height=2, selectmode='browse')
        for key, label, width in [('order','',28),('enabled', 'Export', 52), ('start', 'In', 80), ('end', 'Out', 80), ('length', 'Length', 70)]:
            self.range_tree.heading(key, text=label)
            self.range_tree.column(key, width=width,minwidth=40)
        self.range_tree.column('order',width=28,minwidth=28,stretch=False,anchor='center')
        self.range_tree.bind('<ButtonPress-1>',self.moment_drag_start,add='+')
        self.range_tree.bind('<B1-Motion>',self.moment_drag_move,add='+')
        self.range_tree.bind('<ButtonRelease-1>',self.moment_drag_end,add='+')
        range_scroll = ttk.Scrollbar(range_list, orient='vertical', command=self.range_tree.yview)
        self.range_tree.configure(yscrollcommand=range_scroll.set)
        self.range_tree.pack(side='left', fill='both', expand=True)
        range_scroll.pack(side='right', fill='y')
        self.range_tree.bind('<<TreeviewSelect>>', self.range_selected)
        self.range_tree.bind('<Double-1>', self.range_double)
        footer=ttk.Frame(page);footer.pack(fill='x')
        reserve_footer(footer)
        ttk.Frame(footer,height=1,style='Rule.TFrame').pack(fill='x',pady=(12,6))
        footer_row=ttk.Frame(footer);footer_row.pack(fill='x')
        self.sorting_hint=tk.StringVar()
        self.refresh_sorting_hint()
        self.sorting_label=ttk.Label(footer_row,textvariable=self.sorting_hint,style='Hint.TLabel')
        self.sorting_label.pack(side='right',padx=(16,0))
        ttk.Label(footer_row,textvariable=self.status,style='Hint.TLabel').pack(side='left',fill='x',expand=True)

    def clip(self):
        if self.project:
            return next((c for c in self.project.data['clips'] if c['id'] == self.current_id), None)

    def layout_panes(self):
        return {'left':self.body,'mixer':self.playback,'queue':self.left_stack,'viewer':self.main_stack}

    def present_main(self):
        if self.closed:return
        self.ui_scale.apply_new()
        self.root.update_idletasks()
        if self.settings.data['app']['window_state']=='zoomed':self.root.state('zoomed')
        self.root.deiconify()
        # Hidden paned windows have no final allocation, especially when the
        # saved state is maximized. Restore only after Windows maps that size.
        self.restore_layout()
        self.root.after_idle(self.restore_layout)

    def restore_layout(self):
        panes=self.layout_panes()
        for key in ('left','queue','viewer','mixer'):
            self.root.update_idletasks()
            pane=panes[key]
            total=pane.winfo_width() if key in ('left','mixer') else pane.winfo_height()
            try:
                ratio=float(self.settings.data['layout'][key])
                if key=='viewer' and not .1<=ratio<=.9:ratio=.65
                if total>1 and len(pane.panes())>1:pane.sashpos(0,round(total*ratio))
            except (tk.TclError,ValueError):pass
        self.root.update_idletasks()

    def remember_layout(self):
        for key,pane in self.layout_panes().items():
            if key in ('queue','viewer') and getattr(getattr(self,'cleanup',None),'compare_sashes',None) is not None:continue
            total=pane.winfo_width() if key in ('left','mixer') else pane.winfo_height()
            if total>1 and len(pane.panes())>1:self.settings.data['layout'][key]=str(round(pane.sashpos(0)/total,4))

    def apply_theme(self,palette,marker_colors=None,light_mode=None):
        if palette!=self.palette and hasattr(self,'viewer') and self.root.winfo_viewable():
            from review_theme_transition import ThemeTransition
            with ThemeTransition(self):self._apply_theme(palette,marker_colors,light_mode)
        else:self._apply_theme(palette,marker_colors,light_mode)

    def _apply_theme(self,palette,marker_colors=None,light_mode=None):
        self.palette=dict(palette)
        if hasattr(self,'level_meter'):self.level_meter.set_palette(self.palette)
        install_theme(self.root,self.palette)
        self.video_frame.configure(bg=self.palette['video_background'])
        if self.mixer:self.mixer.set_background(self.palette['video_background'])
        self.audio_canvas.configure(bg=self.palette['panel'])
        self.timeline.palette=dict(self.palette);self.timeline.configure(bg=self.palette['panel'])
        if hasattr(self,'markers'):
            self.markers.refresh()
            if marker_colors is not None:self.timeline.marker_colors=marker_colors
        self.timeline.draw()
        from review_icons import header_logo
        self.logo.set_light(light_mode if light_mode is not None else sum(bytes.fromhex(self.palette['background'][1:]))>400)
        if hasattr(self,'viewer'):self.viewer.theme()
        self.queue_view.apply_theme()
        if self.cleanup.compare:self.cleanup.compare.apply_palette(self.palette)
        archive=getattr(self.cleanup,'archive_window',None)
        if archive and archive.root.winfo_exists():archive.apply_palette(self.palette)
        self.tree.tag_configure('missing',foreground=self.palette['muted_text'])
        from review_spinner import Spinner
        pending=list(self.root.children.values())
        while pending:
            widget=pending.pop()
            if not widget.winfo_exists():continue
            if getattr(widget,'review_theme_cover',False):continue
            pending.extend(list(widget.children.values()))
            if isinstance(widget,Spinner):widget.apply_palette(self.palette)
            if isinstance(widget,tk.Toplevel):
                widget.review_palette=self.palette
                if hasattr(widget,'about_logo'):widget.about_logo.set_light(sum(bytes.fromhex(self.palette['background'][1:]))>400)
                try:
                    widget.configure(bg=self.palette['background'])
                    if not widget.overrideredirect():dark_title(widget)
                except tk.TclError:pass  # Settings may be in its Destroy callback.
            elif isinstance(widget,ttk.Combobox):
                # Popdown listboxes are Tcl widgets, intentionally not converted
                # to Python widget objects (the source of the old KeyError).
                try:
                    popup=widget.tk.call('ttk::combobox::PopdownWindow',widget._w)
                    paths=[popup]
                    while paths:
                        path=paths.pop()
                        paths.extend(widget.tk.splitlist(widget.tk.call('winfo','children',path)))
                        if str(widget.tk.call('winfo','class',path))=='Listbox':
                            widget.tk.call(path,'configure','-background',self.palette['input'],
                                '-foreground',self.palette['text'],'-selectbackground',self.palette['highlighted_clip'],
                                '-selectforeground',self.palette['text'])
                except tk.TclError:pass
            elif isinstance(widget,tk.Text):
                widget.configure(background=self.palette['panel'],foreground=self.palette['text'],selectbackground=self.palette['highlighted_clip'])
        self.magnifier.refresh_palette() if hasattr(self,'magnifier') else None
        if hasattr(self,'transport'):self.update_transports('set_palette',self.palette)

    def track_title(self,index,track):
        title=track['title']
        aliases=self.aliases()
        if aliases:return aliases[index] if index<len(aliases) else f'Track {index+1}'
        if title.casefold() in ('soundhandler','audiohandler','core media audio','obs audio handler',''):
            return aliases[index] if index<len(aliases) else f'Track {index+1}'
        return title

    def waveform_changed(self,event=None):
        values=list(self.wave_combo['values']);choice=self.wave_choice.get()
        cfg=self.settings.data['waveform']
        cfg['enabled']='no' if choice=='Off' else 'yes'
        if choice!='Off':cfg['track']='auto' if choice=='Auto (all tracks)' else str(max(0,values.index(choice)-2))
        self.settings.save()
        self.start_waveform()

    def waveform_choices(self):
        c=self.clip()
        values=['Off','Auto (all tracks)']
        if c and c.get('media'):
            values += [f'{i+1} · {self.track_title(i,t)}' for i,t in enumerate(c['media']['audio'])]
        self.wave_combo.configure(values=values)
        cfg=self.settings.data['waveform'];track=cfg['track']
        index=int(track)+2 if track.isdigit() and int(track)+2<len(values) else 1
        self.wave_choice.set(values[index] if cfg.getboolean('enabled') else 'Off')
        self.start_waveform()

    def start_waveform(self,force=False):
        if self.waveforms:self.waveforms.cancel()
        c=self.clip();cfg=self.settings.data['waveform']
        self.timeline.set_waveform([],int(cfg['bins_per_second']),'')
        if not cfg.getboolean('enabled') or not c or not c.get('media') or not c['media']['audio']:
            self.wave_status.set('')
            return
        if self.waveforms is None:
            base=application_folder()
            paths=[base/'player/ffmpeg.exe',base/'vendor/ffmpeg/ffmpeg.exe']
            decoder=self.settings.data['tools']['ffmpeg'] or next((str(p) for p in paths if p.is_file()),None) or shutil.which('ffmpeg')
            cache=waveform_folder(self.settings.path.parent)
            self.waveforms=Waveforms(cache,decoder,int(cfg['bins_per_second']))
        track=cfg['track'];count=len(c['media']['audio'])
        index=min(int(track),count-1) if track.isdigit() else None
        title=self.track_title(index,c['media']['audio'][index]) if index is not None else 'All tracks'
        self.wave_label='Waveform · '+title
        self.wave_status.set('Preparing waveform…')
        self.waveforms.request(self.project.checked(c['path']),c['id'],c['identity'],index,c['media']['duration'],tracks=count,force=force)

    def changed(self,record=True,group=None,fields=None):
        if record and self.clip():self.history.record(self.clip(),group,fields)
        self.refresh_history()
        if self.project:
            self.project.dirty = True
            if record and self.clip():self.project.mark_review(self.clip())
            if hasattr(self,'queue_view'):self.queue_view.refresh_status()
            if hasattr(self,'viewer'):self.viewer.refresh()
            if fields and set(fields).intersection(('star','markers','ranges')):
                # Only rebuild filtered queues whose membership/order changed.
                # Marker drags otherwise need just the ordinary badge refresh.
                if self.filter.get() in ('Stars','Bookmarks','Marks','Marked') and tuple(c['id'] for c in self.visible_clips())!=self.tree.get_children():self.populate()
                elif hasattr(self,'viewer'):
                    for card in self.viewer.panels:
                        if card.category.get() in ('Stars','Bookmarks','Marks','Marked'):
                            from review_queue import filtered_clips
                            rows=filtered_clips(self.project.data['clips'],card.category.get(),card.search.get())
                            if tuple(c['id'] for c in rows)!=card.tree.get_children():card.populate()
            self.root.title(f'ClipComb Pro — {self.project.data["name"]} *')

    def action_detail(self,redo=False):
        action=self.history.next_action(redo)
        if not action:return 'Nothing to redo.' if redo else 'Nothing to undo. Last Action shows the review edit that Undo would reverse.'
        clip=next((c for c in self.project.data['clips'] if c['id']==action[0]),None) if self.project else None
        return ('Redo: ' if redo else 'Undo: ')+action[1]+('\n'+Path(clip['path']).name if clip else '')

    def refresh_history(self):
        action=self.history.next_action()
        blocked=self.busy or self.loading or bool(getattr(self,'timeline',None) and self.timeline.drag)
        display=(action,self.history.next_action(True),blocked)
        if getattr(self,'history_display',None)==display:return
        from review_folders import action_text
        self.history_display=display;self.last_action.set(action_text(self.project,action[1]) if action else 'None')
        for button,redo in ((self.undo_button,False),(self.redo_button,True)):
            button.configure(state='normal' if self.history.next_action(redo) and not blocked else 'disabled')

    def history_panel_resized(self,event):
        wrap = max(100,event.width-20)
        if getattr(self,'action_wrap',None) != wrap:
            self.action_wrap = wrap
            self.action_label.configure(wraplength=wrap)

    def clip_fps(self):
        media=(self.clip() or {}).get('media') or {}
        return media.get('fps_fraction') or media.get('fps') or 30

    def format_time(self,seconds):
        return timecode(seconds,self.clip_fps(),self.settings.data.getboolean('app','timecode_frames'))

    def regenerate_waveform(self):
        if self.busy or self.loading or not self.clip():return
        if self.wave_choice.get()=='Off':
            self.status.set('Choose an audio waveform track before regenerating.');return
        self.start_waveform(force=True)

    def folder_move_help(self,role):
        from review_folders import names
        name=names(self.project).get(role,role)
        return f'Move this clip to {name} on Save Project. '+('This is the recoverable Deleted role; no file is permanently deleted. Export includes it only if you check this folder.' if role=='Deleted' else 'Marked In/Out selections and the export folder checkboxes determine what is exported.')

    def layout_decisions(self):
        from review_folders import names
        configured=names(self.project);roles=[role for role in ('Used','Unused','Deleted','Kept','Extra1','Extra2','Extra3','Extra4') if role in configured]
        available='normal' if self.clip() else 'disabled'
        for role,button in self.decision_buttons.items():
            text='Move To '+configured.get(role,role)
            if button.cget('text')!=text:button.configure(text=text)
            if button.cget('state')!=available:button.configure(state=available)
        gap=round(5*self.ui_scale.factor);width=self.decision_row.winfo_width()
        if width<=1:width=1200*self.ui_scale.factor
        # Four folder choices per row; all buttons keep their natural text width.
        rows=[roles[:4]]+([roles[4:]] if len(roles)>4 else [])
        positions={};row=0
        for group in rows:
            used=0;column=0
            for role in group:
                button=self.decision_buttons[role];need=button.winfo_reqwidth()+gap
                if column and used+need>width:row+=1;column=0;used=0
                positions[button]=(row,column);column+=1;used+=need
            row+=1
        first=[self.decision_buttons[r] for r in roles[:4]]
        controls=[self.entire_button]+([self.undo_trim_button] if self.undo_trim_available else [])
        used=sum(b.winfo_reqwidth()+gap for b in first)
        control_row=0 if all(positions[b][0]==0 for b in first) else row
        column=len(first) if control_row==0 else 0
        for button in controls:
            need=button.winfo_reqwidth()+gap
            if used+need>width:control_row=max(row,control_row+1);column=0;used=0
            positions[button]=(control_row,column);column+=1;used+=need
        last=max(r for r,c in positions.values())
        extra=[self.decision_buttons[r] for r in roles[4:]]
        if extra and all(positions[b][0]==1 for b in extra) and sum(b.winfo_reqwidth()+gap for b in extra)+self.file_actions.winfo_reqwidth()+gap<=width:
            positions[self.file_actions]=(1,4)
        else:positions[self.file_actions]=(last+1,0)
        key=(tuple((str(b),p) for b,p in positions.items()),gap)
        if getattr(self,'decision_layout_key',None)==key:return
        self.decision_layout_key=key
        for button in (*self.decision_buttons.values(),self.entire_button,self.undo_trim_button,self.file_actions):
            if button not in positions:
                if button.winfo_manager():button.grid_remove()
                continue
            r,c=positions[button]
            button.grid(row=r,column=c,columnspan=1,sticky='w',padx=(0,gap),pady=(0,round(3*self.ui_scale.factor)))
        # Spare width follows the last column, without widening any button.
        for column in range(10):self.decision_row.columnconfigure(column,weight=1 if column==9 else 0)
        if extra and positions[self.file_actions]==(1,4):self.file_actions.grid_configure(columnspan=6,sticky='e')
        else:self.file_actions.grid_configure(columnspan=10)

    def refresh_folder_ui(self):
        from review_folders import names,categories
        configured=names(self.project);values=categories(self.project);current=self.filter.get()
        if current in configured:current=configured[current]
        if current not in values:current=configured['Unused']
        self.filter_combo.configure(values=values)
        if self.filter.get()!=current:self.filter.set(current)
        self.layout_decisions();self.refresh_sorting_hint()

    def visible_clips(self):
        if not self.project:
            return []
        from review_folders import category as folder_category
        category,search=folder_category(self.project,self.filter.get()),self.search.get().casefold()
        from review_queue import filtered_clips
        return filtered_clips(self.project.data['clips'],category,search)

    def populate(self):
        self.refresh_folder_ui()
        from review_folders import names
        folder_names=names(self.project)
        if hasattr(self,'cleanup'):self.cleanup.update_group_visibility()
        self.tree.delete(*self.tree.get_children())
        clips = self.visible_clips()
        for c in clips:
            self.tree.insert('', 'end', iid=c['id'], values=((self.cleanup.prefix(c['id']) if hasattr(self,'cleanup') else '')+Path(c['path']).name,
                             '',folder_names.get(c['decision'],c['decision']) + (' *' if self.project and self.pending(c) else '')),
                             tags=(('missing',) if c.get('missing') else ())+ (('comparison',) if hasattr(self,'cleanup') and self.cleanup.highlighted(c['id']) else ()))
        selected=(self.cleanup.selected_id if hasattr(self,'cleanup') and self.cleanup.mode=='compare' else None) or self.current_id
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.see(selected)
        if self.project:
            pending = sum(self.pending(c) for c in self.project.data['clips'])
            self.summary.set(f'{len(clips):,} clips shown · {pending:,} moves pending')
        if hasattr(self,'queue_view'):self.queue_view.show(clips)
        if hasattr(self,'viewer'):self.viewer.populate()

    def pending(self, c):
        if c.get('missing'):return False
        return not self.project.checked(c['path']).is_relative_to(self.project.folders()[c['decision']].resolve())

    def tree_selected(self, e=None):
        self.queue_view.sync_badge_colors()
        selection = self.tree.selection()
        if selection and self.cleanup.select_member(selection[0]):return
        if selection and selection[0] != self.current_id and not self.busy:
            self.load_clip(selection[0])

    def clip_context_menu(self,event,clip_id=None):
        clip_id=clip_id or self.tree.identify_row(event.y)
        if not clip_id or self.busy:return
        clip=next((c for c in self.project.data['clips'] if c['id']==clip_id),None)
        if not clip or clip['decision']!='Used':return
        if self.tree.exists(clip_id):self.tree.selection_set(clip_id)
        menu=tk.Menu(self.root,tearoff=False)
        def place():
            if self.current_id!=clip_id:self.load_clip(clip_id,autoplay=False)
            def ready():
                if self.closed:return
                if self.loading:self.root.after(50,ready);return
                if clip.get('media'):export_dialog(self,[clip_id],force=True)
                else:show_error(self.root,'Could not read clip','Open this clip once before importing it.')
            self.root.after(20,ready)
        menu.add_command(label='Place clip on existing timeline',command=place)
        menu.tk_popup(event.x_root,event.y_root)

    def navigate(self, direction):
        if self.busy:
            return
        ids = [c['id'] for c in self.active_clips() if not c.get('missing')]
        if not ids:
            return
        index = ids.index(self.current_id) if self.current_id in ids else (-1 if direction > 0 else len(ids))
        index = min(len(ids) - 1, max(0, index + direction))
        self.load_clip(ids[index])

    def remember_position(self):
        clip = self.clip()
        if clip and self.mixer and self.mixer.active:
            clip['position'] = self.mixer.position

    def load_clip(self, clip_id, autoplay=None, position=None):
        self.cleanup.activity()
        if not self.project or self.busy:
            return
        self.wake_updates()
        if hasattr(self,'cleanup'):self.cleanup.before_load()
        self.stop_frame_repeat()
        self.magnifier.hide()
        self.cancel_scrubbing()
        if self.waveforms:self.waveforms.cancel()
        self.remember_position()
        self.generation += 1
        generation = self.generation
        if self.mixer:
            self.mixer.clear()
        self.current_id = clip_id
        self.playback_display=None
        self.project.data['current_clip'] = clip_id
        c = self.clip()
        if not c:
            return
        self.current_title.set(Path(c['path']).name)
        self.timeline.set_clip(0, [])
        self.range_tree.delete(*self.range_tree.get_children())
        if c.get('missing'):
            self.loading = False
            self.update_transports('set_paused',True);self.update_transports('set_available',False)
            self.time_label.set(self.format_time(0)+' / '+self.format_time(0));self.fps_label.set('Video Framerate: —')
            self.timeline.markers=[];self.timeline.waveform=[];self.timeline.draw()
            self.wave_status.set('');self.wave_combo.configure(values=['Off','Auto (all tracks)'])
            remembered=self.current_id;self.current_id=None;self.build_audio();self.current_id=remembered
            self.status.set('This file was removed outside ClipComb Pro. Its saved decisions and ranges are retained.')
            return
        self.loading = True
        self.current_title.set(Path(c['path']).name)
        self.status.set('Opening clip…')
        self.fps_label.set('Video Framerate: —')
        self.pending_autoplay = autoplay
        self.pending_position = (c.get('position',0) if self.remember_clip_position.get() else 0) if position is None else position
        if self.tree.exists(clip_id):
            self.tree.selection_set(clip_id)
            self.tree.see(clip_id)
        elif self.tree.selection():self.tree.selection_remove(*self.tree.selection())
        self.queue_view.sync_badge_colors()
        path = self.project.checked(c['path'])
        if c.get('media'):
            self.finish_load(generation, c['media'])
            return
        ffprobe = self.settings.data['tools']['ffprobe'] or (
            application_folder()/'player/ffprobe.exe' if (application_folder()/'player/ffprobe.exe').is_file()
            else shutil.which('ffprobe'))
        if not ffprobe:
            self.loading = False
            show_error(self.root, 'FFprobe is needed', 'Set the FFprobe executable in Settings → Playback. It reads track names and clip duration.')
            return
        def worker():
            try:
                self.events.put(('media', generation, probe_media(path, ffprobe)))
            except Exception as error:
                self.events.put(('error', generation, str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def finish_load(self, generation, media):
        if generation != self.generation or not self.clip():
            return
        c = self.clip()
        c['media'] = media
        self.fps_label.set('Video Framerate: '+fps_text(media.get('fps_fraction') or media.get('fps') or 30)+' fps')
        self.profile.set(audio_layout.selected_profile(c.get('audio_profile',self.settings.data['audio']['default_profile']),self.settings.data['audio'],self.date_audio))
        if len(c['mix']) != len(media['audio']):
            # Avoid playing a mixed track and its component tracks together on initial opening.
            mixed = next((i for i, t in enumerate(media['audio']) if
                          any(w in t['title'].casefold() for w in ('all tracks', 'all audio', 'full mix'))), 0)
            if self.effective_profile() == 'Legacy OBS' and len(media['audio']) >= 6:
                mixed = 5
            c['mix'] = [{'enabled': i == mixed, 'volume': 100} for i in range(len(media['audio']))]
            era = audio_layout.layout_key(self.effective_profile())
            if era:
                enabled = {int(n) for n in self.settings.data['audio'][era + '_enabled'].split(',') if n.strip().isdigit()}
                volumes = self.settings.data['audio'][era + '_volumes'].split(',')
                c['mix'] = [{'enabled': i + 1 in enabled, 'volume': min(150, max(0, float(volumes[i]))) if i < len(volumes) else 100}
                            for i in range(len(media['audio']))]
        if not self.mixer:
            library = find_mpv(application_folder(), self.settings.data['tools']['mpv_library'])
            if not library:
                self.loading = False
                show_error(self.root, 'mpv is needed', 'Keep the player folder next to ClipComb Pro.exe, or choose libmpv-2.dll in Settings → Playback.')
                return
            self.root.update_idletasks()
            self.mixer = Mixer(library, self.video_frame, self.settings.data['tools']['hardware_decoding'],self.settings.data['audio']['output_device'])
        self.error_shown = False
        self.mixer.set_background(self.palette['video_background'])
        self.mixer.set_speed(self.speed)
        autoplay = self.settings.data.getboolean('app', 'autoplay') if self.pending_autoplay is None else self.pending_autoplay
        self.mixer.open(self.project.checked(c['path']), media, c['mix'], self.pending_position, autoplay)
        self.timeline.set_clip(media['duration'], c['ranges'])
        self.update_transports('set_available',True)
        self.build_audio()
        self.refresh_ranges()
        if getattr(self,'restored_marker',None) and self.restored_marker[0]==c['id']:
            self.timeline.selected_marker=self.restored_marker[1];self.restored_marker=None;self.timeline.draw()
        self.waveform_choices()
        self.loading = False
        self.history.watch(c)
        if 'audio_original_mix' not in c:
            import copy
            c['audio_original_mix']=copy.deepcopy(c['mix']);c['audio_original_profile']=c.get('audio_profile') or self.settings.data['audio']['default_profile']
        self.project.passive_clip(c)
        self.update_decision_buttons()
        self.queue_view.reveal(c['id'])
        self.viewer.refresh()
        self.status.set(f'{c["decision"]} · {len(media["audio"])} audio tracks · {self.effective_profile()} · Changes stay pending until Save project.')

    def effective_profile(self):
        c = self.clip()
        return audio_layout.effective_profile(c['path'] if c else '',self.profile.get(),self.settings.data['audio'],self.date_audio)

    def aliases(self):
        key=audio_layout.layout_key(self.effective_profile())
        return self.settings.data['audio'][key+'_names'].split('|') if key else []

    def build_audio(self):
        c=self.clip()
        tracks=(c.get('media') or {}).get('audio',[]) if c else []
        titles=tuple(self.track_title(i,t) for i,t in enumerate(tracks))
        if getattr(self,'audio_rows_key',None)==titles and len(self.mix_rows)==len(tracks):
            for (enabled,volume,label),mix in zip(self.mix_rows,c['mix'] if c else []):
                enabled.set(mix['enabled']);volume.set(mix['volume']);label.configure(text=f'{round(mix["volume"])}%')
            return
        self.audio_rows_key=titles
        self.audio_canvas.yview_moveto(0)
        for widget in self.audio_frame.winfo_children():
            widget.destroy()
        self.mix_rows = []
        c = self.clip()
        if not c or not c.get('media'):
            return
        aliases = self.aliases()
        for i, track in enumerate(c['media']['audio']):
            row = ttk.Frame(self.audio_frame, style='Panel.TFrame')
            row.pack(fill='x', pady=(2, 0))
            title = self.track_title(i,track)
            enabled = tk.BooleanVar(value=c['mix'][i]['enabled'])
            volume = tk.DoubleVar(value=c['mix'][i]['volume'])
            help_ui.check(row,f'{i + 1}  {title}',enabled,help_ui.HELP['track'],panel=True,
                          command=lambda n=i:self.update_mix(n)).pack(anchor='w')
            level = ttk.Frame(row, style='Panel.TFrame')
            level.pack(fill='x')
            slider = ttk.Scale(level, from_=0, to=150, variable=volume, style='Volume.Horizontal.TScale',
                               command=lambda value, n=i: self.update_mix(n))
            slider.pack(side='left', fill='x', expand=True)
            label = ttk.Label(level, text=f'{round(volume.get())}%', width=5, style='PanelHint.TLabel')
            label.pack(side='right')
            self.mix_rows.append((enabled, volume, label))
        if not c['media']['audio']:
            ttk.Label(self.audio_frame, text='No audio tracks in this file.', style='PanelHint.TLabel').pack(anchor='w')
        self.shortcut_tags(self.audio_frame)

    def update_mix(self, index):
        c = self.clip()
        if not c or index >= len(self.mix_rows):
            return
        enabled, volume, label = self.mix_rows[index]
        c['mix'][index] = {'enabled': enabled.get(), 'volume': round(volume.get())}
        label.configure(text=f'{round(volume.get())}%')
        if self.mixer:
            self.mixer.mix = c['mix']
            self.mixer.apply_mix()
        now=time.monotonic()
        previous=getattr(self,'mix_history_group',None)
        if not previous or previous[0]!=index or now-previous[1]>.5:
            token=str(now)
        else:token=previous[2]
        self.mix_history_group=(index,now,token)
        self.changed(group=('mix',token),fields=('mix',))

    def flush_settings(self):
        self.settings_timer = None
        self.settings.save()

    def change_profile(self):
        c = self.clip()
        if c:
            c['audio_profile'] = self.profile.get()
            self.build_audio()
            self.waveform_choices()
            self.changed(fields=('audio_profile',))

    def mix_preset(self, mode):
        c = self.clip()
        if not c:
            return
        aliases = self.aliases()
        if mode == 'separate' and not aliases:
            self.status.set('Choose Configured tracks and set its default audible tracks in Settings → Audio.')
            return
        profile=self.effective_profile();key=audio_layout.layout_key(profile)
        active={1,2,3} if profile=='Legacy OBS' else {2,3,4} if profile=='Modern OBS' else {int(n)-1 for n in self.settings.data['audio'][key+'_enabled'].split(',') if n.strip().isdigit()} if key else set()
        for i, setting in enumerate(c['mix']):
            setting['enabled'] = mode == 'separate' and i in active
        self.build_audio()
        if self.mixer:
            self.mixer.mix = c['mix']
            self.mixer.apply_mix()
        self.changed(fields=('mix',))

    def ranges_changed(self):
        field='trim_ranges' if hasattr(self,'cleanup') and self.cleanup.mode=='trim' else 'ranges'
        if self.clip() and (self.auto_moments.get() or field=='trim_ranges'):
            self.clip()[field].sort(key=lambda r:(r['start'],r['end']))
        self.changed(group=getattr(self.timeline,'edit_group',None) if self.timeline.drag else None,fields=(field,))
        self.refresh_ranges()

    def refresh_ranges(self):
        if hasattr(self,'markers'):self.markers.refresh()
        selected = self.timeline.selected
        existing=set(self.range_tree.get_children());wanted={r['id'] for r in self.timeline.ranges}
        for rid in existing-wanted:self.range_tree.delete(rid)
        c = self.clip()
        if c:
            for index,r in enumerate(self.timeline.ranges):
                values=('☰','✓' if r.get('enabled', True) else '—', self.format_time(r['start']), self.format_time(r['end']), self.format_time(r['end'] - r['start']))
                if r['id'] not in existing:self.range_tree.insert('',index,iid=r['id'],values=values)
                else:
                    if tuple(self.range_tree.item(r['id'],'values'))!=values:self.range_tree.item(r['id'],values=values)
                    if self.range_tree.index(r['id'])!=index:self.range_tree.move(r['id'],'',index)
        if selected and self.range_tree.exists(selected) and self.range_tree.selection()!=(selected,):
            self.range_tree.selection_set(selected)

    def select_range(self, rid):
        self.timeline.selected = rid
        if rid and self.range_tree.exists(rid):
            self.range_tree.selection_set(rid)
            self.range_tree.see(rid)

    def range_selected(self, e=None):
        selected = self.range_tree.selection()
        if selected:
            self.timeline.selected = selected[0]
            self.timeline.draw()

    def selected_range(self):
        c = self.clip()
        return next((r for r in self.timeline.ranges if r['id'] == self.timeline.selected), None) if c else None

    def range_double(self, e):
        if self.busy:return
        r = self.selected_range()
        if not r:
            return
        if self.range_tree.identify_column(e.x) == '#2':
            r['enabled'] = not r.get('enabled', True)
            self.ranges_changed()
            self.timeline.draw()
        else:
            self.seek(r['start'])

    def moment_sort_changed(self):
        self.settings.data['app']['sort_moments']='yes' if self.auto_moments.get() else 'no';self.settings.save()
        if self.clip() and self.auto_moments.get():self.ranges_changed();self.timeline.draw()

    def moment_drag_start(self,event):
        self.moment_drag_id=None
        if self.range_tree.identify_column(event.x)=='#1':
            if self.auto_moments.get():self.status.set('Turn off chronological sorting to reorder moments.');return
            self.moment_drag_id=self.range_tree.identify_row(event.y)

    def moment_drag_move(self,event):
        rid=getattr(self,'moment_drag_id',None);target=self.range_tree.identify_row(event.y)
        if rid and target and rid!=target:
            self.range_tree.move(rid,'',self.range_tree.index(target))
            self.range_tree.selection_set(rid)

    def moment_drag_end(self,event):
        rid=getattr(self,'moment_drag_id',None);self.moment_drag_id=None
        if not rid or not self.clip():return
        by_id={r['id']:r for r in self.timeline.ranges}
        self.timeline.ranges[:]=[by_id[i] for i in self.range_tree.get_children()]
        self.ranges_changed();self.timeline.draw()

    def selection_clicked(self,event):
        if not hasattr(self,'timeline'):return
        timeline=self.timeline;widget=event.widget
        keep_marker=widget==timeline and timeline.marker_hit(event.x,event.y)
        keep_range=(widget==timeline and timeline.hit(event.x,event.y)[0]) or widget==self.range_tree or getattr(widget,'preserve_range_selection',False)
        if not keep_marker:timeline.selected_marker=None
        if not keep_range:
            timeline.selected=None
            self.range_tree.selection_remove(*self.range_tree.selection())
        timeline.draw()

    def delete_selected(self):
        if self.busy:return
        if self.timeline.selected_marker:self.markers.remove();return
        if self.timeline.selected:self.remove_range();return
        clip=self.clip()
        if clip and clip.get('missing'):
            self.project.data['clips'].remove(clip);self.project.review_edits.add(clip['id']);self.project.dirty=True
            self.history.forget(clip['id']);self.reset_view(keep_history=True);self.populate()
            self.status.set('Missing clip removed from the queue. Save project to keep this change. No media file was deleted.')

    def remove_range(self):
        if self.busy:return
        c, r = self.clip(), self.selected_range()
        if c and r:
            self.timeline.ranges.remove(r)
            self.timeline.selected = None
            self.ranges_changed()
            self.timeline.draw()

    def clear_moments(self):
        if self.busy or self.loading or self.cleanup.mode=='compare' or not self.clip() or not self.timeline.ranges:return
        self.history.watch(self.clip());self.timeline.cancel_interaction()
        self.timeline.ranges.clear();self.timeline.selected=None
        self.ranges_changed();self.timeline.draw()

    def edit_range(self):
        if self.busy:return
        r = self.selected_range()
        if not r:
            self.status.set('Select a marked moment first.')
            return
        window = dialog(self.root, 'Edit marked moment')
        page = ttk.Frame(window, padding=20)
        page.pack()
        values = [tk.StringVar(value=str(r[k])) for k in ('start', 'end')]
        for i, (label, value) in enumerate(zip(('In (seconds)', 'Out (seconds)'), values)):
            ttk.Label(page, text=label).grid(row=i, column=0, sticky='w', padx=(0, 12), pady=5)
            ttk.Entry(page, textvariable=value).grid(row=i, column=1)
        def apply():
            try:
                a, b = [float(v.get()) for v in values]
                if not 0 <= a < b <= self.clip()['media']['duration']:
                    raise ValueError('The range must be inside this clip, with Out after In.')
                if self.timeline.snap_range:a,b=self.timeline.snap_range(a,b)
                r.update(start=round(a, 6), end=round(b, 6))
                self.ranges_changed()
                self.timeline.draw()
                window.destroy()
            except ValueError as error:
                show_error(window, 'Check the range', str(error))
        self.button(page, 'Apply', apply, True).grid(row=2, column=1, sticky='e', pady=(12, 0))
        present(window, self.root)

    def decide(self, category):
        c = self.clip()
        if not c or self.busy:
            return
        visible = [x['id'] for x in self.active_clips() if not x.get('missing')]
        index = visible.index(c['id']) if c['id'] in visible else -1
        next_id = visible[index + 1] if 0 <= index < len(visible) - 1 else None
        if category not in self.project.folders():return
        c['decision'] = category
        self.changed(fields=('decision',))
        self.update_decision_buttons()
        self.populate()
        from review_folders import names
        self.status.set(f'{Path(c["path"]).name} → {names(self.project)[category]} on next save.')
        if self.settings.data.getboolean('app', 'auto_advance') and next_id:
            self.load_clip(next_id)

    def seek(self, seconds):
        if self.mixer and self.mixer.active:
            self.wake_updates()
            paused = self.mixer.paused
            self.mixer.seek(seconds)
            self.mixer.set_pause(self.scrub_stop.get() or paused)

    def scrub_options_changed(self, changed=None):
        self.scrub_audio_control.configure(state='normal' if self.scrub_video.get() else 'disabled')
        for key,var in [('show_video',self.scrub_video),('play_audio',self.scrub_audio),('stop_playback',self.scrub_stop)]:
            self.settings.data['scrubbing'][key] = 'yes' if var.get() else 'no'
        if self.mixer and self.mixer.scrubbing:
            self.mixer.configure_scrub(**self.scrub_options())
        if self.settings_timer:
            self.root.after_cancel(self.settings_timer)
        self.settings_timer = self.root.after(400,self.flush_settings)

    def scrub_options(self):
        cfg = self.settings.data['scrubbing']
        return {'video':self.scrub_video.get(),'audio':self.scrub_audio.get() and self.scrub_video.get(),'stop':self.scrub_stop.get(),
                'interval':float(cfg['seek_interval_ms'])/1000,'grain':float(cfg['audio_grain_ms'])/1000}

    def scrub_event(self, phase, seconds):
        if not self.mixer or not self.mixer.ready:
            return
        if phase == 'begin':
            self.wake_updates()
            self.magnifier.hide()
            self.mixer.begin_scrub(seconds,**self.scrub_options())
        elif phase == 'move':
            self.mixer.update_scrub(seconds)
        elif phase == 'end':
            self.mixer.end_scrub(seconds)
        elif phase == 'cancel':
            self.mixer.cancel_scrub()

    def active_timeline(self):
        comparison=self.cleanup.compare if self.cleanup.mode=='compare' else None
        return comparison.timeline if comparison else self.timeline

    def cancel_scrubbing(self):
        self.scrub_owner = None
        for timeline in (self.timeline,self.active_timeline()):
            if str(self.root.tk.call('grab','current',self.root._w)) == str(timeline):timeline.grab_release()
            timeline.cancel_interaction()

    def shortcuts_allowed(self):
        from review_windows import hwnd
        import ctypes
        from ctypes import wintypes
        user=ctypes.windll.user32;user.GetForegroundWindow.restype=wintypes.HWND
        foreground=user.GetForegroundWindow()
        allowed={hwnd(self.root,True)}
        if self.viewer.detached:allowed.add(hwnd(self.video_column,True))
        if foreground not in allowed:return False
        grab=str(self.root.tk.call('grab','current',self.root._w))
        return not grab or grab in (self.root._w,self.active_timeline()._w)

    def pointer_on_timeline(self):
        timeline=self.active_timeline();x,y = self.root.winfo_pointerxy()
        return (timeline.winfo_rootx() <= x < timeline.winfo_rootx()+timeline.winfo_width()
                and timeline.winfo_rooty() <= y < timeline.winfo_rooty()+timeline.winfo_height())

    def follow_mouse(self):
        if self.scrub_owner is None:return
        if not self.shortcuts_allowed():self.cancel_scrubbing();return
        timeline=self.active_timeline();x,_ = self.root.winfo_pointerxy();x -= timeline.winfo_rootx()
        if timeline.scrubbing:timeline.move_scrub(x)
        elif timeline.begin_scrub(x):timeline.grab_set()

    def release_scrub_owner(self, owner):
        if self.scrub_owner == owner:
            self.follow_mouse();self.scrub_owner = None;timeline=self.active_timeline()
            if str(self.root.tk.call('grab','current',self.root._w)) == str(timeline):timeline.grab_release()
            timeline.end_scrub()

    def focus_changed(self):
        try:
            focus = str(self.root.tk.call('focus','-displayof',self.root._w))
            allowed={self.root._w}
            if self.viewer.detached:allowed.add(self.video_column._w)
            if not focus or str(self.root.tk.call('winfo','toplevel',focus)) not in allowed:
                self.pressed.clear()
                self.stop_frame_repeat()
                self.cancel_scrubbing()
        except (tk.TclError,KeyError):
            pass

    def key_up(self, event):
        self.pressed.discard(event.keycode)
        if event.keycode in (16,17,18):self.stop_speed_hold()
        if getattr(self,'speed_hold_owner',None)==('key',event.keycode):self.stop_speed_hold()
        if self.frame_repeat and self.frame_repeat[0]==('key',event.keycode):self.stop_frame_repeat()
        self.release_scrub_owner(('key',event.keycode))

    def wants_extra_mouse(self, button):
        return bool(self.recording_key or any(binding.split('+')[-1] == mouse_binding(button)
                    for section in ('shortcuts','shortcuts_secondary') for binding in self.settings.data[section].values()))

    def use_or_unused(self):
        self.decide('Unused' if self.clip() and self.clip()['decision']=='Used' else 'Used')

    def open_clip_external(self,location=False):
        if not self.project or not self.clip():return
        path=self.project.checked(self.clip()['path'])
        if not path.is_file():show_error(self.root,'Open clip','This clip could not be found.');return
        try:
            if location:
                import subprocess
                subprocess.Popen(['explorer.exe','/select,',str(path)])
            else:os.startfile(str(path))
        except OSError as error:show_error(self.root,'Open clip',str(error))

    def use_entire_clip(self):
        if self.busy or self.loading or not self.clip():return
        if self.cleanup.mode!='review':self.cleanup.review()
        clip=self.clip();duration=float((clip.get('media') or {}).get('duration') or self.timeline.duration or 0)
        if duration<=0:return
        self.history.watch(clip)
        clip['ranges']=[{'id':uuid.uuid4().hex,'start':0.,'end':duration,'enabled':True}]
        self.timeline.ranges=clip['ranges'];self.timeline.selected=clip['ranges'][0]['id']
        self.changed(fields=('ranges',));self.refresh_ranges();self.timeline.draw()
        self.status.set('Entire clip selected for export. Undo restores the previous selections.')

    def update_decision_buttons(self):
        clip=self.clip()
        self.bulk_sort_button.configure(state='normal' if self.project and not self.busy and any(c.get('ranges') and not c.get('missing') for c in self.project.data['clips']) else 'disabled')
        self.entire_button.configure(state='normal' if clip else 'disabled')
        from review_trim_undo import receipt_for
        self.undo_trim_available=bool(clip and receipt_for(self.project,clip))
        self.layout_decisions()

    def undo_review(self,redo=False):
        if self.busy or self.loading or self.timeline.drag:return
        entry=self.history.take(redo)
        if not entry:self.status.set('Nothing to redo.' if redo else 'Nothing to undo.');return
        clip_id,values=entry
        if clip_id is None:
            from review_bulk_sort import refresh_decisions
            refresh_decisions(self,values['decisions'])
            self.status.set(('Redid' if redo else 'Undid')+' bulk folder move. File moves stay pending until Save Project.')
            return
        clip=next((c for c in self.project.data['clips'] if c['id']==clip_id),None)
        if not clip:return
        previous_markers={m['id'] for m in clip.get('markers',[])}
        for key,value in values.items():
            if value is None:clip.pop(key,None)
            else:clip[key]=value
        self.history.watch(clip);self.changed(record=False)
        self.project.mark_review(clip)
        if 'decision' in values and self.cleanup.refresh_comparison():
            self.status.set(('Redid' if redo else 'Undid')+' overlap decision. Folder changes stay pending until Save.');return
        restored=[m for m in clip.get('markers',[]) if m['id'] not in previous_markers]
        if clip_id not in [c['id'] for c in self.visible_clips()]:self.filter.set('All')
        self.populate()
        if clip_id==self.current_id and self.mixer and self.mixer.active:
            field='trim_ranges' if self.cleanup.mode=='trim' else 'ranges'
            self.timeline.ranges=clip.setdefault(field,[]);self.timeline.selected=None
            self.profile.set(audio_layout.selected_profile(clip.get('audio_profile',self.settings.data['audio']['default_profile']),self.settings.data['audio'],self.date_audio))
            self.build_audio();self.mixer.mix=clip['mix'];self.mixer.apply_mix()
            self.refresh_ranges();self.timeline.draw();self.update_decision_buttons()
        else:
            self.restored_marker=(clip_id,restored[-1]['id']) if restored else None
            self.load_clip(clip_id,autoplay=False,position=clip.get('position',0))
        if restored:self.timeline.selected_marker=restored[-1]['id'];self.timeline.draw()
        self.status.set(('Redid' if redo else 'Undid')+' review action. Folder changes stay pending until Save.')

    def mouse_down(self, event):
        self.cleanup.activity()
        if event.num==3 and self.magnifier.active:
            self.timeline.cancel_interaction();self.magnifier.toggle_cursor();return 'break'
        key = mouse_binding(event.num,event.state)
        if not key:
            return
        if self.recording_key:
            if event.num in (1,3):return
            callback,self.recording_key = self.recording_key,None
            callback(key)
            return 'break'
        return self.dispatch_binding(key,event,('mouse',event.num))

    def mouse_up(self, event):
        if event.num==3 and self.magnifier.active:return 'break'
        if self.frame_repeat and self.frame_repeat[0]==('mouse',event.num):self.stop_frame_repeat()
        self.pressed.discard(('mouse',event.num))
        if getattr(self,'speed_hold_owner',None)==('mouse',event.num):self.stop_speed_hold()
        self.release_scrub_owner(('mouse',event.num))

    def audio_wheel(self, event):
        if not self.audio_overflow:
            self.audio_canvas.yview_moveto(0)
            return 'break'
        self.audio_canvas.yview_scroll(-max(1,abs(int(event.delta/120))) if event.delta > 0
                                      else max(1,abs(int(event.delta/120))),'units')
        return 'break'

    def resize_audio_canvas(self,event):
        if getattr(self,'audio_window_width',None)!=event.width:
            self.audio_window_width=event.width
            self.audio_canvas.itemconfigure(self.audio_window,width=event.width)
        self.sync_audio_scroll()

    def sync_audio_scroll(self,event=None):
        height=max(1,self.audio_canvas.winfo_height())
        content=self.audio_frame.winfo_reqheight()
        self.audio_overflow=content>height+1
        region = (0,0,self.audio_canvas.winfo_width(),max(content,height))
        if getattr(self,'audio_scroll_region',None)!=region:
            self.audio_scroll_region=region
            self.audio_canvas.configure(scrollregion=region)
        if self.audio_overflow:
            if not self.audio_scroll.winfo_manager():self.audio_scroll.pack(side='right',fill='y')
        elif self.audio_scroll.winfo_manager():
            self.audio_scroll.pack_forget()
            self.audio_canvas.yview_moveto(0)

    def remember_option_changed(self):
        self.settings.data['app']['remember_position']='yes' if self.remember_clip_position.get() else 'no'
        if self.settings_timer:self.root.after_cancel(self.settings_timer)
        self.settings_timer=self.root.after(400,self.flush_settings)

    def mouse_double_right(self, event):
        if self.magnifier.active:return self.mouse_down(event)
        if event.widget == self.timeline and not self.recording_key:
            self.cancel_scrubbing()
            return self.timeline.right_double(event)
        return self.mouse_down(event)

    def seek_relative(self, delta):
        if self.cleanup.mode=='compare' and self.cleanup.compare:
            view=self.cleanup.compare;view.seek(view.timeline.time+delta);return
        if self.mixer:
            # Skips are transport actions, independent of mouse-scrub policy.
            self.mixer.seek(self.mixer.position + delta)

    def toggle_volume_meter(self,keybind=False):
        enabled=not self.meter_on.get() if keybind else self.meter_on.get()
        self.meter_on.set(enabled);self.settings.data['app']['volume_meter']='yes' if enabled else 'no'
        if enabled:
            others=[w for w in self.level_meter.master.pack_slaves() if w!=self.level_meter]
            self.level_meter.pack(side='right',padx=(6,0),anchor='se',**({'before':others[0]} if others else {}))
        else:self.level_meter.pack_forget();self.level_meter.close()
        self.settings.save()

    def toggle_snapping(self):
        cfg=self.settings.data['snapping'];cfg['enabled']='no' if cfg.getboolean('enabled') else 'yes'
        self.settings.save();self.update_transports('set_palette',self.palette)
        self.status.set('Snapping '+('enabled for the playhead and bookmarks.' if cfg.getboolean('enabled') else 'disabled for the playhead and bookmarks.'))

    def shortcut_hint(self,action):
        from review_bindings import keys_for
        return ' / '.join(keys_for(self.settings.data,action))

    def refresh_sorting_hint(self):
        from review_bindings import sorting_guide
        self.sorting_hint.set(sorting_guide(self.settings.data,self.project))

    def apply_media_keys(self):
        try:
            self.media_keys.set_enabled(self.settings.data.getboolean('app','media_play_pause'))
        except OSError as error:
            self.settings.data['app']['media_play_pause']='no'
            self.status.set(str(error))
            return str(error)

    def media_play_pause(self):
        # Media buttons work in the background, but never start playback behind a dialog.
        if not self.settings.data.getboolean('app','media_play_pause') or self.busy or self.loading:return
        grab=self.root.grab_current()
        if grab is not None and grab not in (self.root,self.timeline):return
        self.toggle_play()

    def frame_time(self,seconds):
        fps=float(Fraction(str(self.clip_fps()))) or 30
        return round(seconds*fps)/fps

    def action_tip(self,text,action):
        binding=self.shortcut_hint(action)
        return text+ ('\n\nShortcut: '+binding if binding else '')

    def step_frame(self, direction, repeat=False):
        if self.cleanup.mode=='compare' and self.cleanup.compare:return self.cleanup.compare.step_frame(direction)
        if self.mixer:
            return self.mixer.step_frame(direction,repeat=repeat)

    def slow_speed(self,increase=False,minimum=False):
        speed=.1 if minimum else self.speed+.1 if increase else self.slow_cycle.press(self.speed)
        self.set_speed(speed,manual=True)

    def change_speed(self,delta):
        if not self.busy:
            self.set_speed(self.speed+delta,manual=True)

    def set_speed(self,speed,*,manual=False):
        self.speed=max(.1,min(8,round(speed,2)))
        if manual:
            self.cycle = SpeedCycle(float(self.settings.data['app']['speed_reset_seconds']))
        self.speed_label.set(f'{self.speed:g}×')
        if self.cleanup.mode=='compare' and self.cleanup.compare:self.cleanup.compare.set_speed(self.speed)
        if self.mixer:
            self.mixer.set_speed(self.speed)

    def toggle_fullscreen(self):self.viewer.toggle_fullscreen()

    def toggle_play(self):
        self.wake_updates()
        if self.cleanup.mode=='compare' and self.cleanup.compare:
            self.cleanup.compare.toggle();return
        if self.mixer:self.mixer.toggle_play()

    def key_down(self, event):
        if self.recording_key:
            key = key_from_event(event)
            if key:
                callback = self.recording_key
                self.recording_key = None
                callback(key)
            return 'break'
        return self.dispatch_binding(key_from_event(event),event,('key',event.keycode))

    def dispatch_binding(self, key, event, owner):
        self.cleanup.activity()
        if not self.shortcuts_allowed():return
        try:
            if event.widget.winfo_toplevel() != self.root and not (self.viewer.detached and event.widget.winfo_toplevel()==self.video_column):
                return
        except (AttributeError, tk.TclError):
            return
        from review_bindings import action_for
        action=action_for(self.settings.data,key,self.cleanup.mode)
        if not action:
            return
        self.wake_updates()
        editable=isinstance(event.widget,(tk.Entry,ttk.Entry,tk.Text)) and not (isinstance(event.widget,ttk.Combobox) and str(event.widget.cget('state'))=='readonly')
        if editable and action not in ('save','export','scrub_to_mouse'):
            return
        press_id = owner[1] if owner[0] == 'key' else owner
        if press_id in self.pressed:
            return 'break'
        self.pressed.add(press_id)
        if self.busy:
            return 'break'
        if action == 'scrub_to_mouse':
            self.scrub_owner = owner
            self.follow_mouse()
            return 'break'
        if action in ('frame_back','frame_forward'):
            self.step_frame(-1 if action=='frame_back' else 1)
            self.start_frame_repeat(owner,-1 if action=='frame_back' else 1)
            return 'break'
        if action.startswith('speed_'):
            self.set_speed(self.cycle.press(int(action[-1])))
        else:
            commands = {
                'star':self.stars.edit,'review_page':self.cleanup.review,'compare_page':self.cleanup.compare_group,
                'marker':self.markers.activate,'snap_playhead':self.toggle_snapping,
                'trim_file':self.cleanup.trim_mode,'create_trim':self.cleanup.render_trim,
                'undo':self.undo_review,'redo':lambda:self.undo_review(True),
                'save': self.save, 'export': self.export, 'play': self.toggle_play,
                'back': lambda: self.seek_relative(-float(self.settings.data['app']['seek_small'])),
                'forward': lambda: self.seek_relative(float(self.settings.data['app']['seek_small'])),
                'back_large': lambda: self.seek_relative(-float(self.settings.data['app']['seek_large'])),
                'forward_large': lambda: self.seek_relative(float(self.settings.data['app']['seek_large'])),
                'next': lambda: self.navigate(1), 'previous': lambda: self.navigate(-1),
                'used': lambda: self.decide('Used'), 'deleted': lambda: self.decide('Deleted'),
                'kept': lambda: self.decide('Kept'), 'unused': lambda: self.decide('Unused'),
                'remove_range': self.delete_selected,
                'clear_moments':self.clear_moments,
                'volume_meter':lambda:self.toggle_volume_meter(keybind=True),
                'fullscreen': self.toggle_fullscreen, 'slow': self.slow_speed,'fast':lambda:self.slow_speed(increase=True),
                **{f'extra{i}':lambda n=i:self.decide(f'Extra{n}') for i in range(1,5)},
                'frame_back': lambda: self.step_frame(-1), 'frame_forward': lambda: self.step_frame(1),
                'scrub_video': lambda: self.toggle_scrub_option('show_video'),
                'scrub_audio': lambda: self.toggle_scrub_option('play_audio'),
            }
            commands[action]()
            if action=='slow':self.start_speed_hold(owner)
        return 'break'

    def toggle_scrub_option(self, name):
        if name=='play_audio' and not self.scrub_video.get():return
        var = self.scrub_video if name == 'show_video' else self.scrub_audio
        var.set(not var.get())
        self.scrub_options_changed(name)

    def save(self, exporting=False):
        if not self.project or self.busy or getattr(self,'saving',False):return False
        scan_project=self.project
        resume_scan=self.cleanup.scanning and any(self.pending(c) for c in self.project.data['clips'])
        if resume_scan and not self.cleanup.pause_scan(wait=True):return False
        from review_save_ui import SaveNotice,FrozenPreview
        self.saving=True;self.queue_view.suspend();self.stop_frame_repeat();self.cancel_scrubbing()
        if self.cleanup.mode=='compare':self.cleanup.review()
        if self.waveforms:self.waveforms.cancel(wait=True)
        self.remember_position();clip=self.clip();position=self.mixer.position if self.mixer else 0
        playing=bool(self.mixer and self.mixer.active and not self.mixer.paused)
        moving=bool(clip and not clip.get('missing') and not self.project.checked(clip['path']).is_relative_to(self.project.folders()[clip['decision']].resolve()))
        frozen=None;notice=SaveNotice(self);success=False;started=time.monotonic();settled=[None]
        if self.mixer and self.mixer.ready:
            self.mixer.set_pause(True)
            if moving:
                try:frozen=FrozenPreview(self,self.mixer.capture_preview())
                except Exception:pass
        self.root.update_idletasks();self.busy=True
        if moving and self.mixer:self.mixer.clear()
        try:
            if exporting:
                path,count=self.project.export_ranges();message=f'Exported {count} marked moments → {path.name}.'
            else:
                count=self.project.save();message=f'Saved project · {count} clips moved to their chosen folders.'
            self.root.title(f'ClipComb Pro — {self.project.data["name"]}');self.busy=False;self.populate()
            if moving and self.current_id:self.load_clip(self.current_id,autoplay=False,position=position)
            elif self.clip():
                field='trim_ranges' if self.cleanup.mode=='trim' else 'ranges';self.timeline.ranges=self.clip().setdefault(field,[])
                if self.mixer:self.mixer.mix=self.clip()['mix'];self.mixer.set_pause(not playing)
                self.history.watch(self.clip());self.refresh_ranges();self.timeline.draw();self.update_decision_buttons()
            self.status.set(message);notice.success();success=True;return True
        except Exception as error:
            self.busy=False;show_error(self.root,'Could not save project',str(error));self.status.set('Save did not finish. Your pending decisions are still available.')
            if moving and self.current_id:self.load_clip(self.current_id,autoplay=False,position=position)
            elif self.mixer:self.mixer.set_pause(not playing)
            return False
        finally:
            self.busy=False;self.queue_view.resume();success_at=time.monotonic()
            def release():
                if self.closed:return
                ready=not moving or not self.mixer or not self.mixer.active or (self.mixer.ready and self.mixer.pending_seek is None and not self.mixer.engine.get('seeking',False))
                if ready and settled[0] is None:settled[0]=time.monotonic()
                if time.monotonic()-success_at<.25 or (time.monotonic()-started<20 and (not ready or time.monotonic()-(settled[0] or time.monotonic())<.07)):
                    if frozen:frozen.lift()
                    notice.window.lift();self.root.after(16,release);return
                if frozen:frozen.close()
                notice.close();self.saving=False
                if moving and success and self.mixer and self.mixer.active:self.mixer.set_pause(not playing)
                if resume_scan and self.project is scan_project:self.root.after(50,lambda:self.cleanup.scan() if not self.closed and self.project is scan_project else None)
            self.root.after(16,release)

    def export(self):
        export_dialog(self)

    def start_frame_repeat(self,owner,direction):
        self.stop_frame_repeat();self.frame_repeat=(owner,direction)
        next_due=[time.monotonic()+int(self.settings.data['app']['frame_repeat_delay_ms'])/1000]
        def repeat():
            self.frame_repeat_timer=None
            if not self.frame_repeat or self.busy:return
            now=time.monotonic();interval=1/float(self.settings.data['app']['frame_repeat_fps'])
            if now>=next_due[0] and not (self.mixer and self.mixer.step_pending is not None):
                self.step_frame(self.frame_repeat[1],repeat=True);next_due[0]=now+interval
            delay=max(4,round((next_due[0]-time.monotonic())*1000))
            self.frame_repeat_timer=self.root.after(delay,repeat)
        delay=int(self.settings.data['app']['frame_repeat_delay_ms'])
        self.frame_repeat_timer=self.root.after(delay if delay>0 else max(1,round(1000/float(self.settings.data['app']['frame_repeat_fps']))),repeat)

    def start_speed_hold(self,owner):
        self.stop_speed_hold();self.speed_hold_owner=owner
        def minimum():
            self.speed_hold_timer=None
            press_id=owner[1] if owner[0]=='key' else owner
            if press_id in self.pressed and not self.busy and self.shortcuts_allowed():self.slow_speed(minimum=True)
        self.speed_hold_timer=self.root.after(1000,minimum)

    def stop_speed_hold(self):
        if getattr(self,'speed_hold_timer',None):self.root.after_cancel(self.speed_hold_timer)
        self.speed_hold_timer=None;self.speed_hold_owner=None

    def stop_frame_repeat(self):
        self.stop_speed_hold()
        self.frame_repeat=None
        if self.frame_repeat_timer:
            self.root.after_cancel(self.frame_repeat_timer);self.frame_repeat_timer=None

    def window_configured(self,event):
        if event.widget==self.root and self.root.state()=='normal':
            if hasattr(self,'transport') and hasattr(self,'viewer'):
                self.transport.resize_update.request()
                if self.viewer.enabled and self.viewer.controls:self.viewer.controls.resize_update.request()
            import ctypes
            from ctypes import wintypes
            user=ctypes.windll.user32;user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user.GetAncestor.restype=wintypes.HWND
            user.IsZoomed.argtypes=[wintypes.HWND]
            if not user.IsZoomed(user.GetAncestor(self.root.winfo_id(),2)) and self.root.winfo_width()>1:self.windowed_geometry=self.root.geometry()

    def confirm_leave(self):
        if not self.project or not self.project.review_changed:
            return True
        result = []
        window = dialog(self.root, 'Save your review?')
        page = ttk.Frame(window, padding=20)
        page.pack()
        ttk.Label(page, text='Save your review?', style='Subheading.TLabel').pack(anchor='w')
        ttk.Label(page, text='Save moves sorted clips and keeps your marked moments.\nDiscard keeps the progress from your last save.',
                  style='Hint.TLabel').pack(anchor='w', pady=(8, 15))
        buttons = ttk.Frame(page)
        buttons.pack(fill='x')
        def choose(value):
            result.append(value)
            window.destroy()
        for label, value in [('Cancel', 'cancel'), ('Discard', 'discard'), ('Save', 'save')]:
            self.button(buttons, label, lambda v=value: choose(v), value == 'save').pack(side='left', padx=(0, 7))
        present(window, self.root)
        window.wait_window()
        if not result or result[0] == 'cancel':
            return False
        return result[0] == 'discard' or self.save()

    def open_project(self, folder, name=None,project_file=None):
        self.wake_updates()
        if self.busy or not self.confirm_leave():
            return
        if not self.cleanup.pause_scan(wait=True):return
        self.remember_position()
        self.logo.hide()
        self.reset_view()
        self.generation += 1
        if self.mixer:
            self.mixer.clear()
        self.busy = True
        self.status.set('Reading project folders…')
        def worker():
            try:
                self.events.put(('project', self.project_store.open(folder,name,project_file)))
            except Exception as error:
                self.events.put(('project_error', str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def reset_view(self,keep_history=False):
        """Drop view references, never mutate the previous project's lists."""
        self.stop_frame_repeat();self.cancel_scrubbing();self.magnifier.hide()
        self.cleanup.review(notify=False)
        if self.waveforms:self.waveforms.cancel(wait=True)
        self.generation+=1;self.current_id=None;self.loading=False
        self.pending_autoplay=None;self.pending_position=0
        if self.mixer:self.mixer.clear()
        self.current_title.set('Choose a clip');self.timeline.set_clip(0,[])
        self.range_tree.delete(*self.range_tree.get_children())
        self.wave_status.set('');self.wave_label='';self.wave_combo.configure(values=['Off','Auto (all tracks)'])
        self.wave_choice.set('Auto (all tracks)' if self.settings.data.getboolean('waveform','enabled') else 'Off')
        self.profile.set(audio_layout.selected_profile(self.settings.data['audio']['default_profile'],self.settings.data['audio'],self.date_audio))
        self.build_audio();self.sync_audio_scroll();self.markers.refresh()
        zero=self.format_time(0);self.time_label.set(f'{zero} / {zero}');self.fps_label.set('Video Framerate: —')
        self.playback_display=None;self.update_transports('set_paused',True);self.update_transports('set_available',False)
        if not keep_history:self.history.clear()
        self.refresh_history()
        self.cleanup.groups=[];self.cleanup.group_by_id={};self.cleanup.layout=[];self.cleanup.points=[]

    def projects_dialog(self):
        if self.busy:
            return
        window = dialog(self.root, 'Projects')
        page = ttk.Frame(window, padding=20)
        page.pack(fill='both', expand=True)
        brand=ttk.Frame(page);brand.pack(fill='x',pady=(0,14))
        logo_label=ttk.Label(brand);logo_label.pack(side='left',padx=(0,10))
        ttk.Label(brand,text='ClipComb Pro',style='Heading.TLabel').pack(side='left')
        from review_logo import AnimatedLogo
        window.projects_logo=AnimatedLogo(logo_label,self.settings.data.getboolean('theme','light_mode'))
        window.projects_logo.loop(4000)
        window.bind('<Destroy>',lambda e:window.projects_logo.close() if e.widget==window else None,add='+')
        title_row=ttk.Frame(page);title_row.pack(fill='x')
        ttk.Label(title_row, text='Your video projects', style='Subheading.TLabel').pack(side='left')
        from review_tutorial import offer_tutorial
        self.button(title_row,'Tutorial',lambda:offer_tutorial(self,window)).pack(side='right')
        self.button(title_row,'Archive Tools',lambda:self.cleanup.archive(window)).pack(side='right',padx=8)
        ttk.Label(page, text='Project files live in Projects beside the app. Your videos stay in their own folders.',
                  style='Hint.TLabel').pack(anchor='w', pady=(5, 12))
        sort_row=ttk.Frame(page);sort_row.pack(fill='x',pady=(0,8))
        ttk.Label(sort_row,text='Sort by').pack(side='left',padx=(0,8))
        sort=tk.StringVar(value=self.settings.data['app']['projects_sort'])
        sort_combo=ttk.Combobox(sort_row,textvariable=sort,values=['Latest','Latest Opened','A-Z','Z-A','First Created','Last Created'],state='readonly',width=18)
        sort_combo.pack(side='left')
        listing = ttk.Treeview(page, columns=('name', 'folder'), show='headings', height=9, selectmode='browse')
        listing.heading('name', text='Project')
        listing.heading('folder', text='Video folder')
        listing.column('name', width=190)
        listing.column('folder', width=440)
        listing.pack(fill='both', expand=True)
        recent = self.project_store.entries()
        def repopulate(event=None):
            def stamp(item,created=False):
                try:return (self.project_store.path_for(item) or Path(item['root'])/PROJECT_FILE).stat().st_mtime if not created else Path(item['root']).stat().st_ctime
                except OSError:return 0
            mode=sort.get()
            if mode in ('A-Z','Z-A'):recent.sort(key=lambda i:(i['name'].casefold(),i['root'].casefold()),reverse=mode=='Z-A')
            else:recent.sort(key=lambda i:stamp(i) if mode=='Latest' else i.get('opened',1 if i['root']==self.settings.data['app']['last_project'] else 0) if mode=='Latest Opened' else i.get('created',stamp(i,True)),reverse=mode!='First Created')
            listing.delete(*listing.get_children())
            for i,item in enumerate(recent):listing.insert('','end',iid=str(i),values=(item['name'],item['root']))
            if recent:listing.selection_set('0');listing.focus('0');listing.see('0')
            self.settings.data['app']['projects_sort']=mode;self.settings.save()
        repopulate();sort_combo.bind('<<ComboboxSelected>>',repopulate)
        def selected():return recent[int(listing.selection()[0])] if listing.selection() else None
        def open_item(item):
            folder=Path(item['root']);path=self.project_store.path_for(item)
            if not folder.is_dir():
                replacement=pick_path(window,'Locate video folder for '+item['name'],rename_callback=self.folder_renamed)
                if not replacement:return
                folder=Path(replacement)
            window.destroy();self.open_project(folder,project_file=path)
        def open_selected(e=None):
            if listing.selection():
                try:open_item(selected())
                except (ValueError,OSError) as error:show_error(self.root,'Could not open project',str(error))
            return 'break'
        def refresh():recent[:]=self.project_store.entries();repopulate()
        def browse():
            folder = pick_path(window, 'Choose video project folder', initial=self.settings.data['app']['last_project'] or None,rename_callback=self.folder_renamed)
            refresh()
            if folder:
                name=self.project_name_dialog(window,Path(folder).name,'Name project')
                if name is not None:window.destroy();self.open_project(folder,name)
        def import_project():
            source=filedialog.askopenfilename(parent=window,title='Open ClipComb Pro project file',initialdir=self.project_store.folder,
                                              filetypes=[('ClipComb Pro project','*.clipcomb.json'),('JSON files','*.json')])
            if not source:return
            try:
                data=self.project_store.document(source);folder=Path(data['video_root'])
                if not folder.is_dir():
                    replacement=pick_path(window,'Locate video folder for '+data['name'],rename_callback=self.folder_renamed)
                    if not replacement:return
                    folder=Path(replacement)
                path=self.project_store.import_file(source,folder)
                window.destroy();self.open_project(folder,project_file=path)
            except (ValueError,OSError) as error:show_error(self.root,'Could not open project',str(error))
        def rename_project():
            item=selected()
            if not item:return
            name=self.project_name_dialog(window,item['name'],'Rename project')
            if name is None:return
            try:
                path=self.project_store.rename(item,name,self.project)
                if self.project and self.project.path==path:
                    self.project_title.set(f'{name}  ·  {self.project.root}');self.root.title(f'ClipComb Pro — {name}'+(' *' if self.project.review_changed else ''))
                refresh()
                for i,record in enumerate(recent):
                    if self.project_store.path_for(record)==path:listing.selection_set(str(i));listing.focus(str(i));listing.see(str(i));break
            except (ValueError,OSError) as error:show_error(window,'Could not rename project',str(error))
        def delete_project():
            item=selected()
            if not item:return
            from review_theme import confirm_action
            path=self.project_store.path_for(item)
            active=bool(self.project and (self.project.path==path if path else str(self.project.root)==item['root']))
            text=f'Delete “{item["name"]}” from ClipComb Pro?\n\nIts saved review data will be removed. Your video files and video folders will not be changed.'
            if active and self.project.review_changed:text+='\n\nUnsaved review changes for this project will be discarded.'
            if not confirm_action(window,'Delete project',text,'Delete project',cancel_first=True):return
            try:
                if active and not self.cleanup.pause_scan(wait=True):return
                self.project_store.remove(item)
                if active:
                    self.project=None;self.current_id=None;self.reset_view();self.populate();self.logo.hide()
                    self.project_title.set('Open a project to begin');self.root.title('ClipComb Pro')
                self.status.set('Project removed from ClipComb Pro. Video files were not changed.');refresh()
            except (ValueError,OSError) as error:show_error(window,'Could not delete project',str(error))
        listing.bind('<Double-1>', open_selected)
        listing.bind('<Return>',open_selected);listing.bind('<space>',open_selected)
        buttons = ttk.Frame(page)
        buttons.pack(fill='x', pady=(13, 0))
        reserve_footer(buttons);window.review_minimum=(440,300)
        manage=ttk.Frame(buttons);manage.pack(fill='x',pady=(0,8))
        self.button(manage,'Rename Project',rename_project).pack(side='left')
        self.button(manage,'Delete Project',delete_project).pack(side='left',padx=6)
        self.button(manage,'Open project file…',import_project).pack(side='right')
        footer=ttk.Frame(buttons);footer.pack(fill='x')
        self.button(footer, 'New / open folder…', browse).pack(side='left')
        self.button(footer, 'Open selected', open_selected, True).pack(side='right')
        self.button(footer, 'Close', window.destroy).pack(side='right', padx=(0, 6))
        present(window, self.root)
        window.bind('<Return>',open_selected)
        window.after_idle(listing.focus_force)
        window.project_controls={'listing':listing,'sort':sort,'refresh':refresh,'open':open_selected,'rename':rename_project,'delete':delete_project,'browse':browse,'import':import_project}


    def project_name_dialog(self,parent,value,title):
        from review_projects import name_value
        window=dialog(parent,title);page=ttk.Frame(window,padding=20);page.pack(fill='both',expand=True)
        ttk.Label(page,text='Project name',style='Subheading.TLabel').pack(anchor='w')
        text=tk.StringVar(value=value);entry=ttk.Entry(page,textvariable=text,width=48);entry.pack(fill='x',pady=(10,4))
        message=tk.StringVar();ttk.Label(page,textvariable=message,style='Hint.TLabel').pack(anchor='w')
        result=[]
        def accept(event=None):
            try:result.append(name_value(text.get()))
            except ValueError as error:message.set(str(error));return 'break'
            window.destroy();return 'break'
        buttons=ttk.Frame(page);buttons.pack(anchor='e',pady=(10,0))
        self.button(buttons,'Cancel',window.destroy).pack(side='left',padx=6);self.button(buttons,'Save name',accept,True).pack(side='left')
        own_variables(window,text,message);present(window,parent);entry.focus_force();entry.selection_range(0,'end');entry.bind('<Return>',accept)
        window.name_controls={'entry':entry,'value':text,'save':accept};window.wait_window()
        if parent.winfo_exists():parent.grab_set()
        return result[0] if result else None

    def folder_renamed(self,old,new,phase):
        """Keep open/recent project references coherent after an explicit rename."""
        if phase=='before':
            if self.project and any(old==folder for folder in self.project.folders().values()):
                raise ValueError('Unused, Used, Kept and Deleted are managed project folders. Rename the project folder or a folder inside them instead.')
            affected=self.project and (self.project.root.is_relative_to(old) or any(self.project.checked(c['path']).is_relative_to(old) for c in self.project.data['clips']))
            self.rename_resume=None
            if affected:
                self.queue_view.suspend()
                self.cleanup.review(notify=False);self.cancel_scrubbing();self.magnifier.hide();self.remember_position()
                self.rename_resume=(self.current_id,self.mixer.position if self.mixer else 0)
                if self.waveforms:self.waveforms.cancel(wait=True)
                if self.mixer:self.mixer.clear()
            return
        if phase=='after':
            import uuid
            self.project_store.folders_renamed(old,new,self.project)
            projects=self.settings.data['projects']
            for key,value in list(projects.items()):
                item=json.loads(value);root=Path(item['root'])
                if root.is_relative_to(old):
                    item['root']=str(new/root.relative_to(old));del projects[key]
                    projects[uuid.uuid5(uuid.NAMESPACE_URL,item['root'].casefold()).hex]=json.dumps(item,ensure_ascii=False)
            last=Path(self.settings.data['app']['last_project'] or '.')
            if last.is_relative_to(old):self.settings.data['app']['last_project']=str(new/last.relative_to(old))
            if self.project:
                previous=self.project.root
                if previous.is_relative_to(old):
                    self.project.root=new/previous.relative_to(old);self.project.data['video_root']=str(self.project.root)
                for c in self.project.data['clips']:
                    absolute=previous/c['path']
                    if absolute.is_relative_to(old):
                        relative=str((new/absolute.relative_to(old)).relative_to(self.project.root))
                        if relative!=c['path']:c['path']=relative;self.changed(record=False)
                self.project_title.set(f'{self.project.data["name"]}  ·  {self.project.root}')
            self.settings.save();self.populate()
        resume=getattr(self,'rename_resume',None)
        if resume and resume[0]:self.load_clip(resume[0],autoplay=False,position=resume[1])
        self.rename_resume=None
        self.queue_view.resume()

    def rescan(self):
        if not self.project or self.busy:
            return
        self.project.scan()
        if self.project.dirty and not self.save():
            return
        self.open_project(self.project.root)

    def audio_devices(self):
        from review_audio_devices import devices
        library=find_mpv(application_folder(),self.settings.data['tools']['mpv_library'])
        return devices(library) if library else [('auto','Default')]

    def apply_audio_device(self):
        device=self.settings.data['audio']['output_device']
        if self.mixer:self.mixer.set_audio_device(device)
        if self.cleanup.compare:self.cleanup.compare.set_audio_device(device)
        archive=getattr(self.cleanup,'archive_window',None)
        if archive and archive.root.winfo_exists():archive.compare.set_audio_device(device)

    def open_homepage(self):
        try:os.startfile(PROJECT_URL)
        except OSError as error:show_error(self.root,'Open web page',str(error))

    def settings_dialog(self):
        window = dialog(self.root, 'ClipComb Pro settings')
        page = ttk.Frame(window, padding=20)
        page.pack(fill='both', expand=True)
        tabs = ttk.Notebook(page)
        tabs.pack(fill='both', expand=True)
        pages={name:ScrollPage(tabs) for name in ('Shortcuts','Playback','Audio','Theme','Other','About')}
        for name,scroll in pages.items():tabs.add(scroll,text=name)
        shortcuts,playback,audio_tab,theme_tab=[pages[name].inner for name in ('Shortcuts','Playback','Audio','Theme')]
        from review_brand import VERSION
        from review_logo import AnimatedLogo
        about=pages['About'].inner
        about_logo=ttk.Label(about);about_logo.pack(anchor='center',pady=(4,8))
        window.about_logo=AnimatedLogo(about_logo,self.settings.data.getboolean('theme','light_mode'),size=144)
        title=ttk.Frame(about);title.pack(anchor='center',pady=(0,18))
        ttk.Label(title,text='ClipComb Pro',style='Heading.TLabel').pack(side='left')
        ttk.Label(title,text=VERSION,style='Hint.TLabel').pack(side='left',padx=(10,0),anchor='s',pady=(0,5))
        ttk.Label(about,text='Thank you for using ClipComb Pro! This app is free and open source! ClipComb Pro makes it easy to review your stored clips captured with OBS Replay Buffer (RECOMMENDED), Nvidia Shadowplay, AMD ReLive etc, and actually get them sorted and imported into the timeline of your video editing software of choice. ClipComb Pro is specifically designed to work best with the paid Studio version of DaVinci Resolve, however it optionally works with Adobe Premiere Pro, Final Cut Pro, Kdenlive, and the free version of DaVinci Resolve.\n\nEssentially this app makes it easier than ever to sort through numerous clips of streams or gameplay, optionally trim the clip files or even merge them with nearby clips that have overlapping identical footage to save space (without losing quality!), and quickly select the parts of said clips you want to directly import into the timeline of your video editing software. Rather than manually sorting your clip files by hand, importing them into the timeline fully, then finding the part of the video you want to use and finally trimming it down.\n\nBe sure to tell others if you enjoy the app or you find it useful! Thanks!',wraplength=650,justify='center',anchor='center').pack(fill='x',pady=8)
        ttk.Button(about,text='GitHub page',style='Round.TButton',command=self.open_homepage).pack(anchor='center',pady=16)
        def about_selected(event=None):
            if tabs.select()==str(pages['About']):
                window.about_logo.set_light(sum(bytes.fromhex(self.palette['background'][1:]))>400)
                if not window.about_logo.ready:window.about_logo.loop()
            elif window.about_logo.ready:window.about_logo.hide()
        tabs.bind('<<NotebookTabChanged>>',about_selected,add='+')
        window.bind('<Destroy>',lambda e:window.about_logo.close() if e.widget==window else None,add='+')
        for scroll in pages.values():scroll.canvas.configure(height=680)
        window.review_minimum=(520,360)
        ttk.Label(about,text="Original logo and animation by WaveSmash. This app was created with OpenAI Codex under WaveSmash's direction. For more information, please check out the Github page.",style='Hint.TLabel',wraplength=650,justify='center',anchor='center').pack(fill='x',pady=(0,8))
        self.button(about,'Tutorial',lambda:__import__('review_tutorial').offer_tutorial(self,window)).pack(anchor='center',pady=(0,8))
        from review_icons import asset_folder
        changelog=asset_folder()/'changelog.txt'
        ttk.Label(about,text='Changelog',style='Subheading.TLabel',anchor='center').pack(fill='x',pady=(12,8))
        history=changelog.read_text(encoding='utf-8') if changelog.is_file() else 'Changelog unavailable in this source checkout.'
        if history.startswith('# Changelog'):history=history.split('\n',2)[-1]
        history='\n'.join(line.lstrip('# ').replace('- ','• ',1) if line.startswith(('#','- ')) else line for line in history.splitlines())
        from review_dialogs import Changelog
        window.changelog=Changelog(about,history,self.palette)
        window.changelog.pack(fill='x',pady=(0,12))
        old_palette=dict(self.palette)
        theme_saved=[False]
        reset_pending=[False]
        from review_folders import FolderEditor,names as folder_names,action_labels
        folders_editor=FolderEditor(pages['Other'].inner,self.project)
        def folder_tab_opened(event):
            if tabs.select()==str(pages['Other']):tabs.after_idle(tabs.focus_set)
        tabs.bind('<<NotebookTabChanged>>',folder_tab_opened,add='+')
        playback_editor=PlaybackEditor(playback,self.settings,pages['Other'].inner)
        audio_editor=AudioEditor(audio_tab,self.settings,self.date_audio,self.audio_devices)
        theme_editor=ThemeEditor(theme_tab,self.settings,self.palette,self.apply_theme)
        window.settings_editors={'playback':playback_editor,'audio':audio_editor,'theme':theme_editor}
        window.settings_pages=pages;window.settings_tabs=tabs;window.folder_editor=folders_editor
        bindings={section:dict(self.settings.data[section]) for section in ('shortcuts','shortcuts_secondary')}
        from review_shortcuts import ShortcutEditor
        shortcut_editor=ShortcutEditor(self,window,shortcuts,bindings,action_labels(self.project,ACTION_LABELS),SHORTCUT_HELP)
        tree,slot,value,hint=shortcut_editor.tree,shortcut_editor.slot,shortcut_editor.value,shortcut_editor.hint
        selected=shortcut_editor.selected
        def folder_labels(*_):
            labels=dict(ACTION_LABELS)
            for role,var in folders_editor.variables.items():
                if var.get().strip():labels[role.lower()]='Move To '+var.get().strip()
            for action,label in labels.items():
                if tree.exists(action):tree.set(action,'action',label)
        for var in folders_editor.variables.values():var.trace_add('write',folder_labels)
        folder_labels()
        self.shortcut_tags(window)
        def save_settings():
            try:
                canonical={section:{a:canonical_key(k) if k.strip() else '' for a,k in slots.items()}
                           for section,slots in bindings.items()}
                from review_bindings import validate
                validate(canonical,ACTION_LABELS)
                values=playback_editor.values();values.update(audio_editor.values())
                colors=theme_editor.values()
                folder_values=folders_editor.values()
                if folder_values is not None and folder_values!=folder_names(self.project):
                    if self.busy or self.loading:raise ValueError('Wait for the current clip or file operation to finish before changing project folders.')
                    if not self.cleanup.pause_scan(wait=True):return
                    self.cleanup.review(notify=False);self.cancel_scrubbing()
                    clip=self.clip();position=self.mixer.position if self.mixer else 0
                    if self.waveforms:self.waveforms.cancel(wait=True)
                    if self.mixer:self.mixer.clear()
                    from review_folders import configure as configure_folders
                    try:configure_folders(self.project,folder_values)
                    finally:
                        self.history.clear();self.populate()
                        if clip:self.load_clip(clip['id'],autoplay=False,position=position)
                if reset_pending[0]:
                    defaults=Settings().data
                    self.settings.data.remove_section('theme');self.settings.data['theme']=dict(defaults['theme'])
                    for section in ('app','tools','magnifier','scrubbing','waveform','audio','export','snapping','bookmarks','trimming','timeline','thumbnails'):
                        for key,value in defaults[section].items():
                            if key not in ('geometry','last_project','review_ui_version','review_controls_version'):
                                self.settings.data[section][key]=value
                for (section,key),value in values.items():self.settings.data[section][key]=value
                self.date_audio=self.settings.data.getboolean('audio','date_profiles_enabled')
                self.profile_combo.configure(values=audio_layout.profile_choices(self.date_audio))
                self.profile.set(audio_layout.selected_profile(self.profile.get(),self.settings.data['audio'],self.date_audio))
                theme_editor.commit()
                for section,slots in canonical.items():self.settings.data[section].update(slots)
                media_error=self.apply_media_keys()
                if media_error:
                    playback_editor.variables['app','media_play_pause'].set(False)
                    show_error(window,'Keyboard media button',media_error)
                self.settings.save()
                self.refresh_sorting_hint()
                self.retention.request()
                self.scrub_video.set(self.settings.data.getboolean('scrubbing','show_video'))
                self.scrub_audio.set(self.settings.data.getboolean('scrubbing','play_audio'))
                self.scrub_stop.set(self.settings.data.getboolean('scrubbing','stop_playback'))
                self.remember_clip_position.set(self.settings.data.getboolean('app','remember_position'))
                self.meter_on.set(self.settings.data.getboolean('app','volume_meter'));self.toggle_volume_meter()
                self.scrub_options_changed()
                self.apply_theme(colors)
                self.cleanup.join.set(self.settings.data.getboolean('trimming','join_sections'))
                self.cleanup.replace.set(self.settings.data.getboolean('trimming','replace_original'))
                self.build_audio()
                self.apply_audio_device()
                self.magnifier.reset_mode()
                if self.waveforms:self.waveforms.close();self.waveforms=None
                self.waveform_choices()
                self.cycle=SpeedCycle(float(self.settings.data['app']['speed_reset_seconds']))
                self.history.limit=int(self.settings.data['app']['undo_limit']);self.history.trim()
                self.playback_display=None;self.refresh_ranges();self.timeline.draw();self.update_transports('layout')
                theme_saved[0]=True
                self.recording_key=None
                window.destroy()
                self.status.set('Settings saved next to ClipComb Pro.exe.')
            except (ValueError,OSError) as error:
                show_error(window,'Check settings',str(error))
        def reset_settings():
            self.recording_key=None
            defaults=Settings().data;reset_pending[0]=True
            for (section,key),variable in playback_editor.variables.items():
                variable.set(defaults.getboolean(section,key) if isinstance(variable,tk.BooleanVar) else defaults[section][key])
            audio_editor.reset(defaults)
            for section in bindings:
                bindings[section].update(dict(defaults[section]))
            shortcut_editor.refresh()
            slot.set('Primary');selected()
            theme_editor.light.set(False);theme_editor.preset.set('Default');theme_editor.select()
            theme_editor.bookmarks.reset()
            hint.set('Defaults loaded. Save settings to keep them, or Cancel to discard.')
        footer=ttk.Frame(page);footer.pack(fill='x',pady=(12,0))
        reserve_footer(footer);window.settings_footer=footer
        self.button(footer,'Reset all to default',reset_settings).pack(side='left')
        from review_tutorial import offer_tutorial
        self.button(footer,'Tutorial',lambda:offer_tutorial(self,window)).pack(side='left',padx=8)
        self.button(footer,'Save settings',save_settings,True).pack(side='right')
        self.button(footer,'Cancel',window.destroy).pack(side='right',padx=(0,8))
        self.button(footer,'Open App Folder',lambda:os.startfile(str(self.settings.path.parent))).pack(side='right',padx=(0,8))
        window.reset_settings=reset_settings
        window.commit_settings=save_settings
        def settings_closed(event):
            if event.widget==window:
                self.recording_key=None
                if not theme_saved[0]:self.apply_theme(old_palette)
        window.bind('<Destroy>',settings_closed,add='+')
        own_variables(window,slot,value,hint,*folders_editor.variables.values(),*playback_editor.variables.values(),*audio_editor.variables.values(),
                      *(v for rows in audio_editor.rows.values() for row in rows for v in row),
                      theme_editor.preset,theme_editor.light,*theme_editor.variables.values(),theme_editor.bookmarks.choice)
        self.shortcut_tags(window)
        present(window,self.root)

    def tick(self):
        if self.closed:
            return
        self.cleanup.poll()
        while not self.media_keys.events.empty():
            self.media_keys.events.get()
            self.media_play_pause()
        self.refresh_history()
        while not self.extra_mouse.events.empty():
            button, down, state, x, y = self.extra_mouse.events.get()
            if down:
                self.native_mouse_down[button] = time.monotonic()
            else:
                self.native_mouse_down.pop(button,None)
            try:
                widget = self.root.winfo_containing(x,y) or self.root
            except (KeyError,tk.TclError):
                if not self.shortcuts_allowed():continue
                widget=self.root  # Native video children have no Python Tk widget.
            event = SimpleNamespace(num=button,state=state,widget=widget)
            self.mouse_down(event) if down else self.mouse_up(event)
        for button,since in list(self.native_mouse_down.items()):
            # A very fast side-button press may leave the window before Tk can
            # capture the pointer. Still notice its release instead of latching.
            if time.monotonic()-since > .1 and not self.magnifier.mouse_state({2:4,4:5,5:6}[button]) & 0x8000:
                self.native_mouse_down.pop(button,None)
                self.mouse_up(SimpleNamespace(num=button))
        self.follow_mouse()
        if self.waveforms:
            event=self.waveforms.poll()
            if event:
                _,peaks,done,message=event
                self.timeline.set_waveform(peaks,self.waveforms.bins,self.wave_label)
                self.wave_status.set('' if done and message=='Cached waveform' else message)
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == 'project':
                    self.history.clear()
                    self.project, self.busy = event[1], False
                    self.current_id = None
                    self.reset_view()
                    self.cleanup.groups=[];self.cleanup.group_by_id={}
                    if self.cleanup.saved_report():self.cleanup.read_groups(self.cleanup.saved_report())
                    self.settings.register(self.project.root, self.project.data['name'],self.project.path)
                    self.project_title.set(f'{self.project.data["name"]}  ·  {self.project.root}')
                    self.root.title(f'ClipComb Pro — {self.project.data["name"]}')
                    self.populate()
                    self.logo.project(str(self.project.root),lambda:not self.busy and not self.loading and (not self.clip() or bool(self.mixer and self.mixer.ready and self.mixer.pending_seek is None)))
                    remembered = self.project.data.get('current_clip')
                    clip = next((c for c in self.visible_clips() if c['id'] == remembered and not c.get('missing')), None)
                    clip = clip or next((c for c in self.visible_clips() if not c.get('missing')), None)
                    if clip:
                        self.load_clip(clip['id'],autoplay=False)
                    else:
                        self.status.set('No clips in this view. Choose another category or put clips into Unused.')
                elif event[0] == 'project_error':
                    self.busy = False
                    show_error(self.root, 'Could not open project', event[1])
                elif event[0] == 'media':
                    self.finish_load(event[1], event[2])
                elif event[0] == 'error' and event[1] == self.generation:
                    self.loading = False
                    self.status.set(event[2])
        except Empty:
            pass
        except Exception as error:
            self.loading = False
            self.status.set(str(error))
        if self.mixer and self.mixer.active:
            try:
                position = self.mixer.tick(time.monotonic())
                self.timeline.playback_position(position)
                display=(position,self.mixer.duration,self.mixer.transport_paused,self.clip_fps(),self.settings.data.getboolean('app','timecode_frames'))
                previous=getattr(self,'playback_display',None)
                if display!=previous:
                    self.time_label.set(f'{self.format_time(position)} / {self.format_time(self.mixer.duration)}')
                    if previous is None or previous[3]!=display[3]:self.fps_label.set('Video Framerate: '+fps_text(self.clip_fps())+' fps')
                    if previous is None or previous[2]!=display[2]:self.update_transports('set_paused',display[2])
                    self.playback_display=display
                while self.mixer.input_events:
                    action, state = self.mixer.input_events.popleft()
                    if action == 'magnify':
                        self.magnifier.press() if state in ('d', 'p') else self.magnifier.hide() if state == 'u' else None
                    elif action=='toggle-zoom-cursor' and state in ('d','p'):
                        self.magnifier.toggle_cursor()
                    elif action in ('zoom-up', 'zoom-down') and state in ('d', 'p', 'r'):
                        self.magnifier.adjust(1 if action == 'zoom-up' else -1)
                    elif action in ('size-up','size-down') and state in ('d','p','r'):
                        self.magnifier.resize(1 if action=='size-up' else -1)
            except Exception as error:
                if not self.error_shown:
                    self.error_shown = True
                    self.status.set(str(error))
                    self.mixer.clear()
        compare = self.cleanup.compare
        if compare is not None:
            compare.tick()
        if self.thumb_pool.has_results():
            self.thumb_pool.poll()
        visible, foreground = self.update_window_state()
        if visible:
            self.ui_scale.tick()
            if foreground or self.playback_realtime():
                self.level_meter.tick()
        self.update_timer.schedule(self.update_delay(visible, foreground))

    def update_window_state(self):
        from review_windows import in_foreground
        windows = (self.root, self.video_column) if self.viewer.detached else (self.root,)
        visible_windows = tuple(window for window in windows if window.state() not in ('iconic', 'withdrawn'))
        return bool(visible_windows), in_foreground(visible_windows)

    def update_window_changed(self, event):
        if event.type in (tk.EventType.Map, tk.EventType.Unmap) and event.widget not in (self.root, self.video_column):
            return
        self.wake_updates()

    def wake_updates(self):
        self.update_timer.schedule(0)

    def playback_realtime(self):
        mixer, compare = self.mixer, self.cleanup.compare
        return bool((mixer and mixer.active and (not mixer.ready or not mixer.paused or
                    mixer.pending_seek is not None or mixer.scrubbing or mixer.stepping)) or
                    self.scrub_owner is not None or self.magnifier.active or self.native_mouse_down or
                    (compare and compare.needs_realtime_updates()))

    def update_delay(self, visible, foreground):
        from review_activity import update_interval
        return update_interval(visible=visible, foreground=foreground or bool(self.recording_key),
                               realtime=self.playback_realtime(),
                               working=self.loading or self.busy or self.cleanup.scanning or self.thumb_pool.has_pending(),
                               paused_player=bool(self.recording_key or self.mixer and self.mixer.active),
                               frame_ms=int(self.settings.data['app']['ui_refresh_ms']))

    def close(self):
        if self.busy or not self.confirm_leave():
            return
        if not self.cleanup.pause_scan(wait=True):return
        if getattr(self,'tutorial_window',None):self.tutorial_window.destroy()
        self.ui_scale.close()
        self.resize_finish.close()
        self.level_meter.close()
        self.retention.close()
        self.viewer.shutdown();self.logo.close()
        self.cleanup.close()
        self.queue_view.close()
        if self.settings.data.getboolean('thumbnails','delete_on_close'):
            from review_thumbnails import delete_thumbnails
            delete_thumbnails(self.settings.path.parent)
        self.cancel_scrubbing()
        if self.waveforms:self.waveforms.close()
        if self.settings.data.getboolean('waveform','delete_on_close'):
            waveform_folder(self.settings.path.parent);delete_generated(self.settings.path.parent)
        self.extra_mouse.close()
        self.media_keys.close()
        self.remember_position()
        self.magnifier.close()
        self.remember_layout()
        if self.mixer:
            self.mixer.close()
        # Remember playback position if there are no uncommitted review changes.
        if self.project and not self.project.dirty:
            try:
                self.project.save()
            except Exception:
                pass
        self.stop_frame_repeat()
        state=self.root.state()
        self.settings.data['app']['window_state']='zoomed' if state=='zoomed' else 'normal'
        self.settings.data['app']['geometry'] = self.windowed_geometry if state=='zoomed' else self.root.geometry()
        self.settings.save()
        self.closed = True
        self.update_timer.close()
        self.root.destroy()

    def update_transports(self,method,*args):
        controls=[self.transport]
        if hasattr(self,'viewer'):controls.append(self.viewer.controls)
        compare=getattr(getattr(self,'cleanup',None),'compare',None)
        if compare and compare.transport and method in ('set_palette','layout'):controls.append(compare.transport)
        for control in controls:getattr(control,method)(*args)

    def active_clips(self):
        view=getattr(self,'active_queue',self.queue_view)
        return view.clips if view in self.thumb_pool.clients else self.visible_clips()

    def start_screen(self):
        if self.settings.data.getboolean('archive','start_on_launch'):
            self.viewer.suspended=True;self.cleanup.archive()
            archive=getattr(self.cleanup,'archive_window',None)
            if not archive or not archive.root.winfo_exists():self.viewer.resume();self.projects_dialog()
        else:self.projects_dialog()


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument('--version', action='version', version=f'{APP_NAME} {VERSION}')
    parser.add_argument('--project', help='Open a video project folder')
    args = parser.parse_args()
    set_taskbar_identity()
    root = tk.Tk()
    root.withdraw()
    if os.name == 'nt':
        from review_media_setup import offer_media_setup
        base = application_folder()
        offer_media_setup(root, base, Settings(base))
    app = ReviewApp(root, start_project=args.project)
    def exception(kind, value, traceback):
        show_error(root, APP_NAME, str(value))
    root.report_callback_exception = exception
    root.mainloop()


if __name__ == '__main__':
    main()

