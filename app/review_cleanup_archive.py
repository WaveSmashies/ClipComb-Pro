# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows review interface for lossless OBS replay copies."""

from argparse import Namespace
import configparser
import csv
from datetime import datetime
import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from review_help import badge
from review_cancel import ScanCancelled

from review_overlap_audit import RECOVERY_FOLDER, Coverage, audit, covers_packets, pair_coverage, probe, video_alignment
from review_cleanup_core import (
    archive_clip, export_candidate, hash_file, list_copies,
    read_candidates, review_directory, run_media, tools_at, witnesses, write_copy_index,
)
from review_cleanup_actions import actions, check_file, cleanup, validate_recovery_path
from review_cleanup_comparison import CLIP_COLORS, GROUP_PANES, CompareView, Pane
from review_cleanup_merge import install_merge, prepare_merge
from review_cleanup_player import AUDIO_MODES, timestamp
from review_cleanup_theme import ACCENT, GREEN, MUTED, confirm_action, dark_title, install_theme, pick_path, reveal_paths, show_error


def application_folder():
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def report_rows(path):
    proposals = read_candidates(path)
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = csv.DictReader(file)
        for row in rows:
            if row["status"] in {"candidate", "redundant"} or not row.get("matches"):
                continue
            matches = sorted(json.loads(row["matches"]), key=lambda match: match["seconds"], reverse=True)
            if matches:
                proposals.append(dict(row, status="overlap_review", review_matches=matches,
                                      matched_video_overlap_seconds=matches[0]["seconds"]))
    return proposals


def review_witnesses(row):
    return row["review_matches"] if row["status"] == "overlap_review" else witnesses(row)


SETTINGS_FILE = "replay-review.ini"


def vlc_executable():
    on_path = shutil.which("vlc.exe")
    if on_path:
        return Path(on_path)
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        folder = os.environ.get(variable)
        if folder:
            candidate = Path(folder) / "VideoLAN" / "VLC" / "vlc.exe"
            if candidate.is_file():
                return candidate
    return None


def vlc_folder():
    executable = vlc_executable()
    return executable.resolve().parent if executable else None


def coverage_label(entry):
    offset = entry.get("offset")
    return "Earlier coverage" if offset is not None and offset > .1 else (
        "Later coverage" if offset is not None and offset < -.1 else "Supporting clip")


class ReviewApp:
    def __init__(self, root, host=None):
        self.host = host
        if not getattr(root._root(),'review_buttons_hook',False):
            from review_buttons import decorate
            root.bind_all('<Map>',decorate,add='+');root._root().review_buttons_hook=True
        from review_theme import DEFAULT_PALETTE
        self.palette=dict(host.app.palette if host else getattr(root._root(),'review_palette',DEFAULT_PALETTE))
        self.root = root
        root.title("ClipComb Pro - Archive Tools")
        root.geometry("1320x820")
        root.minsize(1050, 675)
        self.source = tk.StringVar()
        self.destination = tk.StringVar()
        self.ffmpeg_folder = None
        self.scan_limit = tk.StringVar(value="0")
        self.offset = tk.StringVar(value="0")
        self.overlap = tk.StringVar(value="10")
        self.cap = tk.StringVar(value="5")
        self.status = tk.StringVar(value="Choose a source archive and a separate working folder to begin.")
        self.detail = tk.StringVar(value="Select a proposed cut to inspect it.")
        self.rows = []
        self.records = {}
        self.archive_actions = {}
        self.latest_actions = {}
        self.merges = {}
        self.queue_history = {}
        self.failures = {}
        self.processing = {}
        self.preview_key = None
        self.preview_row = None
        self.preview_mode = "coverage"
        self.coverage_page = 0
        self.visible_supports = []
        self.group_items = {}
        self.group_by_clip = {}
        self.group_layout = []
        self.group_page = 0
        self.group_edges = {}
        self.merge_installing = False
        self.preview_generation = 0
        self.events = Queue()
        self.busy = False
        self.scan_cancel=threading.Event();self.scanning=False;self.close_after_cancel=False
        self.source_root = None
        self.plan_overlap = None
        self.report_path = None
        self.report_source = None
        self.report_overlap = None
        self.settings_ready = False
        self.settings_timer = None
        self.action_buttons = []
        self.settings_entries = []
        self.build()
        for variable in (self.source, self.destination, self.scan_limit, self.offset, self.overlap, self.cap):
            variable.trace_add("write", self.schedule_settings)
        root.bind("<Configure>", self.window_changed, add="+")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.drain_timer = root.after(100, self.drain)
        self.load_timer = root.after(150, self.load_project)

    def tools(self):
        return self.host.tools() if self.host else tools_at(self.ffmpeg_folder)

    def button(self, parent, label, callback, action=True, primary=False):
        from review_buttons import title
        button = ttk.Button(parent, text=title(label), command=callback,
                            style="Primary.TButton" if primary else "Round.TButton")
        if action:
            self.action_buttons.append(button)
        from review_buttons import explanation
        if explanation(label):
            from review_help import Tooltip
            button.review_tooltip=Tooltip(button,explanation(label))
        return button

    def build(self):
        install_theme(self.root,self.palette)
        page = ttk.Frame(self.root, padding=(23, 17))
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        heading=ttk.Label(page,text='ClipComb Pro - Archive Tools',style='Heading.TLabel');heading.grid(row=0,column=0,sticky='w',padx=(60,0))
        logo=ttk.Label(page);logo.grid(row=0,column=0,sticky='w')
        from review_logo import AnimatedLogo
        self.logo=AnimatedLogo(logo,light=self.host.app.settings.data.getboolean('theme','light_mode') if self.host else False)
        if self.host:self.button(page,'Back to ClipComb Pro',self.close,action=False).place(relx=1,anchor='ne')
        ttk.Label(page, text="Find duplicate footage and review verified cuts side by side.",
                  style="Hint.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 15))
        self.tabs = ttk.Notebook(page)
        self.tabs.grid(row=2, column=0, sticky="nsew")
        discover = ttk.Frame(self.tabs)
        self.review_tab = ttk.Frame(self.tabs)
        self.tabs.add(discover, text="Find & configure")
        self.tabs.add(self.review_tab, text="Processing & review")
        self.tabs.bind("<<NotebookTabChanged>>", self.tab_changed)
        discover.columnconfigure(0, weight=1)
        discover.rowconfigure(2, weight=1)
        paths = ttk.Frame(discover, style="Panel.TFrame", padding=(13, 10))
        paths.grid(row=0, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        for number, (label, variable) in enumerate((("Source archive", self.source), ("Working folder", self.destination))):
            label_row=ttk.Frame(paths,style='Panel.TFrame')
            label_row.grid(row=number,column=0,sticky='w',pady=3)
            ttk.Label(label_row, text=label, width=15, style="Panel.TLabel").pack(side='left')
            badge(label_row,'Folder containing your clips with possible overlaps' if number==0 else 'Folder containing scan logs / progress, and copies of clips with your merges. If you\'re unsure what this means, just create a folder next to your clips named "Clip Review" or something similar and select that.',True).pack(side='left')
            entry = ttk.Entry(paths, textvariable=variable)
            entry.grid(row=number, column=1, sticky="ew", padx=(0, 6), pady=2)
            self.settings_entries.append(entry)
            self.button(paths, "Browse…", lambda current=variable: self.pick_directory(current)).grid(
                row=number, column=2, sticky="ew")

        controls = ttk.Frame(discover)
        controls.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        self.button(controls, "Scan archive", self.scan, primary=True).pack(side="left", padx=(0, 6))
        self.scan_row=ttk.Frame(page)
        from review_spinner import Spinner
        self.cancel_scan_button=self.button(self.scan_row,'Stop Scan',self.cancel_scan,action=False)
        self.cancel_scan_button.pack(side='right',padx=(6,0));self.cancel_scan_button.configure(state='disabled')
        self.scan_meter=ttk.Progressbar(self.scan_row,length=180,maximum=100);self.scan_meter.pack(side='right',padx=6)
        self.scan_spinner=Spinner(self.scan_row);self.scan_spinner.pack(side='right')
        self.scan_text=tk.StringVar();ttk.Label(self.scan_row,textvariable=self.scan_text,style='Hint.TLabel',anchor='w').pack(side='left',fill='x',expand=True)
        self.scan_row.grid(row=6,column=0,sticky='ew',pady=5);self.scan_row.grid_remove()
        self.button(controls, "Load audit CSV…", self.load_report).pack(side="left", padx=(0, 12))
        for label, variable, width in (
            ("Scan limit", self.scan_limit, 6), ("Offset", self.offset, 6),
            ("Overlap (s)", self.overlap, 5), ("Batch cap (GiB)", self.cap, 5),
        ):
            label_row=ttk.Frame(controls);label_row.pack(side='left',padx=(5,3))
            ttk.Label(label_row,text=label).pack(side='left')
            explanations={'Scan limit':'Number of clips to scan in this batch. 0 scans the entire folder. RECOMMENDED: 0',
                          'Offset':'If your last scan was only for 10 files, scanning again would result in the same 10 files. Setting this value to 10 would show you the NEXT 10 files.',
                          'Overlap (s)':'Keep this many seconds of duplicated footage at proposed cuts, to leave editing room. Every omitted packet still needs verified coverage.\n\nDefault: 10 seconds.',
                          'Batch cap (GiB)':'Maximum total size of verified copies made by one export batch. This limits disk output, not review playback.\n\nDefault: 5 GiB.'}
            badge(label_row,explanations[label]).pack(side='left')
            entry = ttk.Entry(controls, textvariable=variable, width=width)
            entry.pack(side="left", padx=(0, 5))
            self.settings_entries.append(entry)
        self.button(controls, "FFmpeg folder…", self.pick_ffmpeg).pack(side="right")

        table = ttk.Frame(discover)
        table.grid(row=2, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        columns = (
            ("clip", "Replay", 360), ("length", "Original", 86), ("overlap", "Shared", 80),
            ("trim", "Trim start", 87), ("tail", "Trim end", 87), ("keep", "Overlap kept", 104),
            ("audio", "Audio tracks", 88), ("state", "Copy status", 130),
        )
        self.tree = ttk.Treeview(table, columns=[key for key, _, _ in columns],
                                 show="headings", selectmode="browse", height=12)
        for key, title, width in columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=70, stretch=key in {"clip", "state"},
                             anchor="w" if key in {"clip", "state"} else "center")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=horizontal.set)
        self.tree.bind("<<TreeviewSelect>>", self.selection_changed)
        self.tree.bind("<Double-1>", lambda event: self.review_selected())
        self.tree.tag_configure("verified", foreground=GREEN)

        ttk.Label(page, textvariable=self.detail, justify="left", wraplength=980).grid(
            row=3, column=0, sticky="ew", pady=(8, 3))
        exports = ttk.Frame(discover)
        exports.grid(row=3, column=0, sticky="ew", pady=(9, 0))
        self.button(exports, "Make selected copy", lambda: self.export(False), primary=True).pack(side="left", padx=(0, 5))
        self.button(exports, "Make all pending copies", lambda: self.export(True)).pack(side="left")
        self.button(exports, "Review selected", self.review_selected, action=False).pack(side="left", padx=(5, 0))
        self.button(exports, "Overlap details", self.overlap_details, action=False).pack(side="left", padx=(5, 0))
        self.button(exports, "Save copy index", self.save_index).pack(side="right")
        self.button(exports, "Open Working Folder", self.open_review, action=False).pack(side="right", padx=(0, 5))
        self.build_review()
        self.apply_palette(self.palette)
        ttk.Frame(page, height=1, style="Rule.TFrame").grid(row=4, column=0, sticky="ew", pady=(7, 5))
        ttk.Label(page, textvariable=self.status, style="Hint.TLabel", wraplength=1020).grid(
            row=5, column=0, sticky="w")

    def build_review(self):
        self.review_tab.rowconfigure(0, weight=1)
        self.review_tab.columnconfigure(1, weight=1)
        queue = ttk.Frame(self.review_tab, style="Panel.TFrame", padding=11)
        queue.grid(row=0, column=0, sticky="nsw", padx=(0, 13))
        ttk.Label(queue, text="Processing queue", style="PanelHeading.TLabel").pack(anchor="w")
        self.queue_summary = tk.StringVar(value="No copies queued")
        ttk.Label(queue, textvariable=self.queue_summary, style="PanelHint.TLabel").pack(anchor="w", pady=(1, 8))
        self.queue = ttk.Treeview(queue, columns=("clip", "status"), selectmode="browse", show="tree headings", height=10)
        self.queue.column("#0", width=42, minwidth=42, stretch=False)
        self.group_brackets = self.make_group_brackets()
        self.queue.heading("clip", text="Replay")
        self.queue.heading("status", text="Status")
        self.queue.column("clip", width=210)
        self.queue.column("status", width=105)
        self.queue.tag_configure("Verified", foreground=GREEN)
        self.queue.tag_configure("Queued", foreground=MUTED)
        self.queue.tag_configure("Processing", foreground=ACCENT)
        self.queue.tag_configure("Skipped", foreground="#f0aeaa")
        self.queue.tag_configure("Fully covered", foreground=ACCENT)
        self.queue.tag_configure("Overlap review", foreground=ACCENT)
        self.queue.tag_configure("Remaining clip", foreground=ACCENT)
        queue_scroll = ttk.Scrollbar(queue, orient="vertical", command=self.queue.yview)
        queue_scroll.pack(side="right", fill="y")
        self.queue.configure(yscrollcommand=queue_scroll.set)
        self.queue.pack(side="left", fill="both", expand=True)
        self.queue.bind("<<TreeviewSelect>>", self.queue_changed)
        main = ttk.Frame(self.review_tab)
        main.grid(row=0, column=1, sticky="nsew")
        evidence = ttk.Frame(main)
        evidence.pack(fill="x", pady=(0, 7))
        self.coverage_button = self.button(evidence, "Coverage", lambda: self.set_preview_mode("coverage"),
                                           action=False, primary=True)
        self.coverage_button.pack(side="left", padx=(0, 5))
        self.trim_button = self.button(evidence, "Trim comparison", lambda: self.set_preview_mode("trim"),
                                       action=False)
        self.trim_button.pack(side="left")
        self.more_coverage = self.button(evidence, "Next supporting clips", self.next_coverage, action=False)
        self.coverage_counter = tk.StringVar()
        ttk.Label(evidence, textvariable=self.coverage_counter, style="Hint.TLabel").pack(side="left", padx=8)
        self.next_group = self.button(evidence, "Next clips", self.next_group_page, action=False)
        self.compare = CompareView(main, self.host.library if self.host else vlc_folder, self.schedule_settings)
        if self.host:self.compare.set_audio_device(self.host.app.settings.data['audio']['output_device'])
        self.compare.open_hidden = self.open_group_lane
        self.compare.pack(fill="both", expand=True)
        links = ttk.Frame(main)
        links.pack(fill="x", pady=(7, 0))
        self.preview_links = [self.button(links, label, lambda kind=kind: self.open_video(kind, self.queue), action=False)
                              for label, kind in (("Open original externally", "original"),
                                                  ("Open copy externally", "copy"),
                                                  ("Open supporting clips", "support"))]
        for button in self.preview_links:
            button.pack(side="left", padx=(0, 5))
        self.merged_link = self.button(links, "Open merged video externally", self.open_merged_external, action=False)
        self.button(links, "Open review folder", self.open_review, action=False).pack(side="right")
        self.group_actions = ttk.Frame(main)
        cleanup_bar = ttk.Frame(main)
        cleanup_bar.pack(fill="x", pady=(7, 0))
        self.cleanup_buttons = []
        for label, kind in (("Delete Original…", "delete_original"), ("Delete Trimmed…", "delete_trimmed"),
                            ("Replace Original…", "replace_original")):
            button = self.button(cleanup_bar, label, lambda action=kind: self.cleanup_selected(action))
            button.pack(side="left", padx=(0, 5))
            self.cleanup_buttons.append(button)
        self.recovery_button = self.button(cleanup_bar, "Open recovery folder", self.open_recovery, action=False)
        self.recovery_button.pack(side="right")
        self.button(cleanup_bar, "Rescan archive", self.scan).pack(side="right", padx=(0, 5))
        self.group_remove = [self.button(self.group_actions, "", lambda index=i: self.remove_group_clip(index))
                             for i in range(GROUP_PANES)]
        self.merge_all = self.button(self.group_actions, "Merge All…", self.merge_group, primary=True)
        style = ttk.Style(self.root)
        for i, color in enumerate(CLIP_COLORS):
            style.configure(f"Clip{i}.Round.TButton", foreground=color)
            style.map(f"Clip{i}.Round.TButton", foreground=[("disabled", MUTED)])

    def apply_palette(self,palette):
        self.palette=dict(palette);self.root.review_palette=self.palette
        self.root.configure(bg=palette['background']);dark_title(self.root)
        self.tree.tag_configure('verified',foreground=palette['highlighted_button'])
        for state in ('Verified','Processing','Fully covered','Overlap review','Remaining clip'):
            self.queue.tag_configure(state,foreground=palette['highlighted_button'])
        self.queue.tag_configure('Queued',foreground=palette['muted_text'])
        self.queue.tag_configure('Skipped',foreground=palette['muted_text'])
        self.compare.apply_palette(palette)
        previous=[str(image) for image in self.group_brackets]
        self.group_brackets=self.make_group_brackets()
        for row in self.queue.get_children():
            image=self.queue.item(row,'image')
            if image and image[0] in previous:self.queue.item(row,image=self.group_brackets[previous.index(image[0])])
        style=ttk.Style(self.root)
        for i in range(len(CLIP_COLORS)):style.map(f'Clip{i}.Round.TButton',foreground=[('disabled',palette['muted_text'])])

    def make_group_brackets(self):
        height = int(ttk.Style(self.root).lookup("Treeview", "rowheight"))
        mid = height // 2
        images = []
        for start, end in ((mid, height), (0, height), (0, mid + 4)):
            image = tk.PhotoImage(master=self.root, width=21, height=height)
            image.put(self.palette['highlighted_button'], to=(3, start, 7, end))
            image.put(self.palette['highlighted_button'], to=(3, mid, 20, mid + 4))
            images.append(image)
        return images

    def error(self, title, message):
        show_error(self.root, title, message)

    def pick_directory(self, variable):
        path = self.choose_folder("Choose a folder", variable.get())
        if path:
            variable.set(path)

    def choose_folder(self, title, initial):
        folder = Path(initial).expanduser() if initial else application_folder()
        while not folder.is_dir() and folder.parent != folder:
            folder = folder.parent
        if not folder.is_dir():
            folder = Path.home()
        return filedialog.askdirectory(parent=self.root, title=title, initialdir=str(folder), mustexist=True)

    def pick_ffmpeg(self):
        path = self.choose_folder("Choose the folder containing ffmpeg.exe and ffprobe.exe", self.ffmpeg_folder)
        if path:
            try:
                tools_at(path)
            except ValueError as error:
                self.error("FFmpeg not found", str(error))
                return
            self.ffmpeg_folder = path
            if self.host:
                self.host.app.settings.data['tools'].update(tools_at(path))
                self.host.app.settings.save()
            self.status.set("FFmpeg is ready.")
            self.schedule_settings()

    def paths(self):
        if not self.source.get().strip() or not self.destination.get().strip():
            raise ValueError("Choose the source archive and a separate review folder.")
        source = Path(self.source.get()).resolve(strict=True)
        if not source.is_dir():
            raise ValueError("Choose a folder for the source archive.")
        return source, review_directory(source, Path(self.destination.get()))

    def requested_overlap(self):
        overlap = float(self.overlap.get())
        if not math.isfinite(overlap) or overlap < 1:
            raise ValueError("Enter an overlap of at least one second.")
        return overlap

    def load_project(self):
        if self.load_timer:
            self.root.after_cancel(self.load_timer)
            self.load_timer = None
        folder = self.host.app.settings.path.parent if self.host else application_folder()
        path = folder / SETTINGS_FILE
        settings = configparser.ConfigParser(interpolation=None)
        self.settings_ready = False
        try:
            if self.host:
                for old,new in (('archive','cleanup'),('preview','cleanup.preview'),('window','cleanup.window'),('tools','cleanup.tools')):
                    if new in self.host.app.settings.data:settings[old]=dict(self.host.app.settings.data[new])
                if not settings.has_option('archive','source') and self.host.app.project:
                    if 'archive' not in settings:settings['archive']={}
                    settings['archive']['source']=str(self.host.app.project.root)
                    settings['archive']['review']=str(self.host.work())
                    settings['archive']['report']=str(self.host.app.project.data.get('overlap_report',''))
                    settings['archive']['report_source']=str(self.host.app.project.root)
            elif path.is_file():
                with path.open(encoding="utf-8-sig") as file:
                    settings.read_file(file)
            elif (legacy := folder / "replay-review-project.json").is_file():
                data = json.loads(legacy.read_text(encoding="utf-8-sig"))
                settings["archive"] = {key: str(data[key]) for key in ("source", "review", "report", "overlap")}
        except (ValueError, OSError, KeyError, configparser.Error) as error:
            self.status.set(f"Could not read {SETTINGS_FILE}: {error}")
            return
        try:
            for key, variable in (("source", self.source), ("review", self.destination)):
                value = settings.get("archive", key, fallback="")
                variable.set(str(folder / value) if value else "")
            for key, variable in (("scan_limit", self.scan_limit), ("offset", self.offset),
                                  ("overlap", self.overlap), ("batch_cap_gib", self.cap)):
                variable.set(settings.get("archive", key, fallback=variable.get()))
            tools = settings.get("tools", "ffmpeg_folder", fallback="")
            self.ffmpeg_folder = str(folder / tools) if tools else None
            audio = settings.get("preview", "audio", fallback="Both")
            self.compare.audio_mode = audio if audio in AUDIO_MODES or audio in ('Clip:0','Clip:1','Clip:2','Clip:3') else "Both"
            self.compare.update_audio_menu(False)
            try:
                volume = settings.getint("preview", "volume", fallback=100)
            except ValueError:
                volume = 100
            self.compare.set_volume(volume)
            for role in self.compare.audio_choices:
                try:
                    self.compare.audio_choices[role] = max(0, settings.getint("preview", f"track_{role}", fallback=0))
                except ValueError:
                    self.compare.audio_choices[role] = 0
            self.set_preview_mode(settings.get("preview", "mode", fallback="coverage"))
            geometry = settings.get("window", "geometry", fallback="")
            if geometry:
                try:
                    self.root.geometry(geometry)
                except tk.TclError:
                    pass
            report = settings.get("archive", "report", fallback="")
            report_source = settings.get("archive", "report_source", fallback=self.source.get())
            self.report_path = folder / report if report else None
            self.report_source = folder / report_source if report_source else None
            self.report_overlap = settings.get("archive", "report_overlap", fallback=self.overlap.get())
            if report and report_source and Path(self.source.get()).resolve() == (folder / report_source).resolve():
                self.apply_report(self.report_path, float(self.report_overlap))
            if settings.get("window", "tab", fallback="find") == "review":
                self.tabs.select(self.review_tab)
        except (ValueError, OSError, KeyError, configparser.Error) as error:
            self.status.set(f"Saved project could not be opened: {error}")
        finally:
            self.settings_ready = True

    def window_changed(self, event):
        if event.widget is self.root:
            self.schedule_settings()

    def schedule_settings(self, *args):
        if not self.settings_ready:
            return
        if self.settings_timer:
            self.root.after_cancel(self.settings_timer)
        self.settings_timer = self.root.after(350, self.save_settings)

    def save_settings(self):
        self.settings_timer = None
        if not self.settings_ready:
            return
        folder = self.host.app.settings.path.parent if self.host else application_folder()
        path = folder / SETTINGS_FILE

        def location(value):
            if not value:
                return ""
            resolved = Path(value).resolve()
            return str(resolved.relative_to(folder)) if resolved.is_relative_to(folder) else str(resolved)

        settings = configparser.ConfigParser(interpolation=None)
        staged = None
        try:
            settings["archive"] = {
                "source": location(self.source.get()), "review": location(self.destination.get()),
                "scan_limit": self.scan_limit.get(), "offset": self.offset.get(),
                "overlap": self.overlap.get(), "batch_cap_gib": self.cap.get(),
                "report": location(self.report_path), "report_source": location(self.report_source),
                "report_overlap": str(self.report_overlap or self.overlap.get()),
            }
            settings["tools"] = {"ffmpeg_folder": location(self.ffmpeg_folder)}
            settings["preview"] = {"audio": self.compare.audio_mode, "mode": self.preview_mode,
                                   "volume": str(self.compare.volume),
                                   **{f"track_{role}": str(value) for role, value in self.compare.audio_choices.items()}}
            settings["window"] = {
                "geometry": self.root.geometry(),
                "tab": "review" if self.tabs.select() == str(self.review_tab) else "find",
            }
            if self.host:
                for old,new in (('archive','cleanup'),('preview','cleanup.preview'),('window','cleanup.window'),('tools','cleanup.tools')):
                    self.host.app.settings.data[new]=dict(settings[old])
                self.host.app.settings.save()
                return
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=folder, prefix=".replay-review-", delete=False) as file:
                staged = Path(file.name)
                settings.write(file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(staged, path)
        except (OSError, ValueError) as error:
            self.status.set(f"Could not save {SETTINGS_FILE}: {error}")
        finally:
            if staged:
                staged.unlink(missing_ok=True)

    def apply_report(self, path, plan_overlap=None):
        source, destination = self.paths()
        overlap = self.requested_overlap() if plan_overlap is None else plan_overlap
        if not math.isfinite(overlap) or overlap < 1:
            raise ValueError("The saved report has an invalid overlap setting.")
        rows = report_rows(path)
        self.source_root, self.plan_overlap = source, overlap
        self.report_path = path.resolve()
        self.report_source, self.report_overlap = source, overlap
        self.failures = {}
        self.processing = {}
        self.clear_preview()
        self.rows = rows
        self.refresh_copies(destination)
        self.fill()
        self.report_summary(f"Loaded {path.name}.")
        self.schedule_settings()

    def load_report(self):
        path = pick_path(self.root, "Open an audit report", self.destination.get(), csv=True)
        if path:
            try:
                self.apply_report(Path(path))
            except Exception as error:
                self.error("Could not open audit", str(error))

    def overlap_details(self):
        if not self.report_path or self.busy:
            return
        try:
            with self.report_path.open(encoding="utf-8-sig", newline="") as report:
                reader = csv.DictReader(report)
                if "matches" not in (reader.fieldnames or ()):
                    self.status.set("This report predates overlap details. Scan the archive to see every match found.")
                    return
                rows = {row["clip"]: row for row in reader if row["clip"]}
            pairs = {}
            for name, row in rows.items():
                for match in json.loads(row["matches"] or "[]"):
                    key = tuple(sorted((name, match["clip"])))
                    prior = pairs.get(key)
                    if not prior or match["verified"] and not prior["verified"]:
                        pairs[key] = match
        except (ValueError, OSError, KeyError) as error:
            self.error("Could not load overlap details", str(error))
            return
        window = tk.Toplevel(self.root)
        window.title("Overlap details")
        window.geometry("1050x490")
        window.transient(self.root)
        dark_title(window)
        panel = ttk.Frame(window, padding=14)
        panel.pack(fill="both", expand=True)
        verified = sum(match["verified"] for match in pairs.values())
        ttk.Label(panel, text=f"{len(pairs)} matching pairs  ·  {verified} verified  ·  "
                  f"{len(pairs) - verified} video matches held for verification",
                  style="Subheading.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(panel, text="Rescan after cleanup to reconsider clips that were serving as coverage.",
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 8))
        table = ttk.Frame(panel)
        table.pack(fill="both", expand=True)
        columns = (("first", "Clip", 245), ("second", "Matching clip", 245),
                   ("shared", "Shared video", 100), ("result", "Scan result", 410))
        view = ttk.Treeview(table, columns=[key for key, _, _ in columns], show="headings")
        for key, title, width in columns:
            view.heading(key, text=title)
            view.column(key, width=width, stretch=key == "result")
        bar = ttk.Scrollbar(table, orient="vertical", command=view.yview)
        view.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        view.pack(fill="both", expand=True)
        for (first, second), match in sorted(pairs.items()):
            if match["verified"]:
                status = {rows.get(name, {}).get("status") for name in (first, second)}
                if status & {"candidate", "redundant"}:
                    result = "Verified overlap · one clip has a proposed action"
                elif "reference" in status:
                    result = "Verified overlap · a clip is reserved as coverage in this plan"
                else:
                    result = "Verified overlap · no independent cut in this plan"
            else:
                result = match["reason"]
            view.insert("", "end", values=(first, second, self.seconds(match["seconds"]), result))

    def run_job(self, task, finish, failed=None):
        if self.busy:
            return
        self.busy = True
        for control in (*self.action_buttons, *self.settings_entries):
            control.configure(state="disabled")

        def work():
            try:
                self.events.put(("done", (finish, task())))
            except ScanCancelled:
                self.events.put(('cancelled',None))
            except Exception as error:
                self.events.put(("error", (str(error), failed)))

        threading.Thread(target=work, daemon=True).start()

    def drain(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.status.set('Overlap scan in progress. Stop Scan keeps completed progress.' if self.scanning else value)
                    if self.scanning:
                        from review_scan_feedback import display
                        text,amount=display(value,'Stopping' if self.scan_cancel.is_set() else 'Full speed')
                        self.scan_text.set(text)
                        if amount is not None:self.scan_meter['value']=amount
                    continue
                if kind == "processing":
                    self.update_processing(*value)
                    continue
                if kind in {"preview", "merged_preview"}:
                    generation, comparison, error = value
                    if generation == self.preview_generation and self.tabs.select() == str(self.review_tab):
                        self.compare.alignment_spinner.stop()
                        if error:
                            self.compare.reset(error)
                        elif kind == "merged_preview":
                            path, duration = comparison
                            self.compare.load([Pane(path, "original", 0, duration)], duration, single_title="Merged video")
                        else:
                            self.compare.load(*comparison)
                    continue
                if kind == "group_preview":
                    generation, layout, error = value
                    if generation==self.preview_generation:self.compare.alignment_spinner.stop()
                    if generation == self.preview_generation and self.tabs.select() == str(self.review_tab):
                        if error:
                            self.compare.reset(error)
                        else:
                            self.group_layout = layout
                            self.show_group_page()
                    continue
                if kind == "external":
                    path, error = value
                    try:
                        if error:
                            raise ValueError(error)
                        self.launch_player(path)
                    except (OSError, ValueError) as problem:
                        self.error("Could not open video", str(problem))
                    continue
                self.busy = False
                self.scanning=False;self.cancel_scan_button.configure(state='disabled');self.scan_spinner.stop();self.scan_row.grid_remove()
                for control in (*self.action_buttons, *self.settings_entries):
                    control.configure(state="normal")
                if kind=='cancelled':
                    self.status.set('Scan canceled. Original recordings were not changed.')
                    if self.close_after_cancel:self.close();return
                elif kind == "error":
                    message, failed = value
                    self.status.set("The operation stopped.")
                    self.error("Operation stopped", message)
                    if failed:
                        try:
                            failed()
                        except Exception as error:
                            self.error("Could not reload the review ledger", str(error))
                    self.queue_changed()
                else:
                    callback, result = value
                    try:
                        callback(result)
                    except Exception as error:
                        self.error("Could not display result", str(error))
        except Empty:
            pass
        if self.close_after_cancel and not self.busy:self.close();return
        self.drain_timer = self.root.after(100, self.drain)

    def report_status(self, message):
        self.events.put(("status", message))

    def scan(self):
        if self.busy:return
        try:
            source, destination = self.paths()
            tools = self.tools()
            limit, offset = int(self.scan_limit.get()), int(self.offset.get())
            overlap = self.requested_overlap()
            if limit < 0 or offset < 0:
                raise ValueError("Scan limit and offset must be zero or higher.")
        except (ValueError, OSError) as error:
            self.error("Check scan settings", str(error))
            return
        path = destination / f"audit-{datetime.now():%Y%m%d-%H%M%S-%f}.csv"
        self.status.set("Reading the archive inventory…")
        self.scan_cancel.clear();self.scanning=True;self.cancel_scan_button.configure(state='normal')
        self.scan_meter['value']=0;self.scan_text.set('Reading the archive inventory… · Full speed');self.scan_row.grid();self.scan_spinner.start()

        def task():
            args = Namespace(limit=limit, offset=offset, overlap=overlap, lookback=12,
                             window_seconds=0, probe_timeout=120,scan_cache=destination/'scan-cache.sqlite3')
            try:audit(args, source, path, tools["ffprobe"], self.report_status,self.scan_cancel)
            except ScanCancelled:path.unlink(missing_ok=True);raise
            with path.open(encoding="utf-8-sig", newline="") as report:
                scanned = sum(bool(row["clip"]) for row in csv.DictReader(report))
            return report_rows(path), scanned

        def finish(result):
            rows, scanned = result
            self.source_root, self.plan_overlap = source, overlap
            self.report_path = path
            self.report_source, self.report_overlap = source, overlap
            self.rows, self.failures = rows, {}
            self.processing = {}
            self.clear_preview()
            self.refresh_copies(destination)
            self.fill()
            self.report_summary(f"Scanned {scanned} clips.")
            self.schedule_settings()

        self.run_job(task, finish)

    def cancel_scan(self):
        if self.scanning:
            self.scan_cancel.set();self.cancel_scan_button.configure(state='disabled');self.status.set('Stopping scan…');self.scan_text.set('Stopping scan… completed progress is kept')

    def report_summary(self, prefix):
        review = sum(row["status"] == "overlap_review" for row in self.rows)
        self.status.set(f"{prefix} {len(self.rows) - review} proposed actions · {review} overlap review clips.")

    def refresh_copies(self, destination):
        self.records = {}
        for record in list_copies(destination):
            if record["state"] == "verified":
                self.records.setdefault(os.path.normcase(record["source"]), []).append(record)
        self.archive_actions = {}
        self.latest_actions = {}
        self.merges = {}
        for action in actions(destination):
            if action["state"] not in {"started", "done"}:
                continue
            key = os.path.normcase(action["source"])
            self.latest_actions[key] = action
            if action["state"] == "started" or action["kind"] in {"delete_original", "replace_original", "merge_original"}:
                self.archive_actions[key] = action
            if action["kind"] == "merge_original" and action["state"] == "done":
                self.merges.setdefault(action["merge_id"], []).append(action)

    def row_path(self, row):
        path = self.source_root / row["clip"]
        if row["clip"].startswith(("'=", "'+", "'-", "'@")) and not path.exists():
            return self.source_root / row["clip"][1:]
        return path

    def archive_action_for(self, row):
        path = self.row_path(row)
        action = self.archive_actions.get(os.path.normcase(str(path)))
        if not action:
            return None
        if action["state"] == "started":
            return action
        try:
            source = archive_clip(self.source_root, row["clip"])
            if list(source.file_id) == action.get("original_identity"):
                return None
        except (OSError, ValueError):
            pass
        return action

    def record_for(self, row):
        if row["status"] != "candidate":
            return None
        action = self.archive_action_for(row)
        if action:
            records = self.records.get(os.path.normcase(action["source"]), [])
            return next((record for record in records if record["id"] == action.get("copy_id")), None)
        try:
            source = archive_clip(self.source_root, row["clip"])
            references = [archive_clip(self.source_root, entry["clip"]) for entry in witnesses(row)]
            cut = float(row["proposed_head_trim_seconds"])
            end = float(row.get("retained_end_seconds") or row.get("original_seconds") or 0)
        except (OSError, ValueError, KeyError):
            return None
        records = self.records.get(os.path.normcase(str(source.path)), [])
        return next((
            record for record in reversed(records)
            if "audio_names" in record
            and abs(record["trim_start_seconds"] - cut) < 0.001
            and abs(record["retained_end_seconds"] - end) < 0.002
            and record["coverage_references"] == [str(clip.path) for clip in references]
            and record["coverage_identities"] == [list(clip.file_id) for clip in references]
            and record["source_identity"] == list(source.file_id)
        ), None)

    def fill(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        queue_selected = self.queue.selection()
        self.queue.delete(*self.queue.get_children())
        self.row_ids = {}
        self.queue_history = {}
        self.queue_counts = {"Verified": 0, "Queued": 0, "Processing": 0, "Skipped": 0,
                             "Proposed": 0, "Fully covered": 0, "In recovery": 0, "Replaced": 0,
                             "Check recovery": 0, "Overlap review": 0, "Remaining clip": 0, "Merged": 0}
        for index, row in enumerate(self.rows):
            self.row_ids[row["clip"]] = str(index)
            record = self.record_for(row)
            queued = "Verified" if record else self.processing.get(row["clip"])
            if queued == "Verified" and not record:
                queued = "Proposed"
            if row["status"] == "redundant":
                queued = "Fully covered"
            elif row["status"] == "overlap_review":
                queued = None
            action = self.archive_action_for(row)
            if action:
                if action["state"] == "started":
                    queued = "Check recovery"
                elif action["kind"] == "merge_original" and action["source"] == action["merged_path"]:
                    queued = "Merged"
                else:
                    queued = "Replaced" if action["kind"] == "replace_original" else "In recovery"
            if row["status"] == "overlap_review":
                state = queued or "Overlap review"
            else:
                state = f"Verified · {record['audio_tracks']} audio" if record and not action else queued or "Pending"
            if queued:
                self.queue.insert("", "end", iid=str(index), values=(Path(row["clip"]).stem, queued), tags=(queued,))
                self.queue_counts[queued] += 1
            self.tree.insert("", "end", iid=str(index), values=(
                row["clip"], self.seconds(row.get("original_seconds")), self.seconds(row.get("matched_video_overlap_seconds")),
                self.seconds(row["proposed_head_trim_seconds"]) if row["status"] != "redundant" else "—",
                self.seconds(row.get("proposed_tail_trim_seconds") or "0") if row["status"] == "candidate" else "—",
                self.seconds(row["minimum_shared_seconds_after_cut"]) if row["status"] != "redundant" else "All",
                row.get("audio_tracks", ""), state,
            ), tags=("verified",) if record else ())
        if self.rows:
            item = selected[0] if selected and int(selected[0]) < len(self.rows) else "0"
            self.tree.selection_set(item)
            self.tree.see(item)
        self.fill_merge_history()
        self.fill_overlap_groups()
        children = self.queue.get_children()
        if children:
            first_reviewable = next((item for item in children if self.queue.set(item, "status")
                                     not in {"Replaced", "Merged", "In recovery"}), children[0])
            item = queue_selected[0] if queue_selected and queue_selected[0] in children else first_reviewable
            self.queue.selection_set(item)
            self.queue.see(item)
        self.update_queue_summary()
        self.selection_changed()
        self.queue_changed()

    def fill_merge_history(self):
        if not self.source_root:
            return
        report_paths = {self.row_path(row) for row in self.rows}
        for members in self.merges.values():
            for action in members:
                path = Path(action["source"])
                if path in report_paths or not path.is_relative_to(self.source_root):
                    continue
                row = {"clip": str(path.relative_to(self.source_root)), "status": "merge_history"}
                if self.archive_action_for(row) != action:
                    continue
                state = "Merged" if action["source"] == action["merged_path"] else "In recovery"
                item = f"merge-{action['id']}"
                self.queue_history[item] = row
                self.queue.insert("", "end", iid=item, values=(path.stem, state), tags=(state,))
                self.queue_counts[state] += 1

    def fill_overlap_groups(self):
        self.group_items = {}
        self.group_by_clip = {}
        edges = {}
        for row in self.rows:
            if row["status"] != "overlap_review":
                continue
            name = row["clip"]
            for match in row["review_matches"]:
                peer = match["clip"]
                if peer != name:
                    edges.setdefault(name, set()).add(peer)
                    edges.setdefault(peer, set()).add(name)
        self.group_edges = edges
        live = set()
        for name in edges:
            try:
                clip = archive_clip(self.source_root, name)
            except (OSError, ValueError):
                continue
            action = self.archive_action_for({"clip": name})
            if action and action["kind"] == "merge_original":
                row = self.rows[int(self.row_ids[name])] if name in self.row_ids else {}
                if list(clip.file_id) != json.loads(row.get("source_identity") or "null"):
                    continue
            live.add(name)
        insertion = next((i for i, item in enumerate(self.queue.get_children())
                          if self.queue.set(item, "status") in {"Replaced", "Merged", "In recovery"}),
                         len(self.queue.get_children()))
        while live:
            pending = [min(live)]
            names = []
            while pending:
                name = pending.pop()
                if name in live:
                    live.remove(name)
                    names.append(name)
                    pending.extend(edges[name] & live)
            names.sort(key=lambda name: (Path(name).name, name))
            state = "Overlap review" if len(names) > 1 else "Remaining clip"
            items = tuple(f"overlap-{name}" for name in names)
            for i, (item, name) in enumerate(zip(items, names)):
                bracket = self.group_brackets[0 if i == 0 else 2 if i == len(names) - 1 else 1] if len(names) > 1 else ""
                self.queue.insert("", insertion, iid=item, image=bracket, values=(Path(name).stem, state), tags=(state,))
                insertion += 1
                self.group_items[item] = (tuple(names), items)
                self.group_by_clip[name] = item
            self.queue_counts[state] += len(names)

    def update_queue_summary(self):
        counts = self.queue_counts
        active = counts["Queued"] + counts["Processing"]
        self.queue_summary.set(
            f"{active} active  ·  {counts['Verified']} verified  ·  {counts['Fully covered']} covered"
            f"  ·  {counts['Replaced'] + counts['Merged'] + counts['In recovery']} handled  ·  {counts['Skipped']} skipped"
            + (f"  ·  {counts['Check recovery']} need recovery review" if counts["Check recovery"] else "")
            + (f"  ·  {counts['Overlap review']} overlap review" if counts["Overlap review"] else "")
            + (f"  ·  {counts['Remaining clip']} remaining" if counts["Remaining clip"] else "")
            if any(counts.values()) else "No copies queued"
        )

    def update_processing(self, clip, state, record, note):
        self.processing[clip] = state
        if note:
            self.failures[clip] = note
        if record:
            self.records.setdefault(os.path.normcase(record["source"]), []).append(record)
        item = self.row_ids.get(clip)
        if item is None:
            return
        if self.queue.exists(item):
            previous = self.queue.set(item, "status")
            self.queue_counts[previous] -= 1
            self.queue.item(item, values=(Path(clip).stem, state), tags=(state,))
        else:
            self.queue.insert("", "end", iid=item, values=(Path(clip).stem, state), tags=(state,))
        self.queue_counts[state] += 1
        self.tree.set(item, "state", f"Verified · {record['audio_tracks']} audio" if record else state)
        self.tree.item(item, tags=("verified",) if record else ())
        self.update_queue_summary()
        if self.tree.selection() == (item,):
            self.selection_changed()
        if self.queue.selection() == (item,):
            self.queue_changed()

    @staticmethod
    def seconds(value):
        return f"{float(value):.2f} s" if value else "—"

    def selected(self, tree=None):
        items = (tree if tree is not None else self.tree).selection()
        if not items:
            raise ValueError("Select a proposed cut in the list.")
        if tree is self.queue and items[0] in self.queue_history:
            return self.queue_history[items[0]]
        return self.rows[int(items[0])]

    def selection_changed(self, event=None, tree=None):
        if tree is None:
            if self.tabs.select() == str(self.review_tab):
                return
            tree = self.tree
        if not tree.selection():
            self.detail.set("Select a proposed cut to inspect it.")
            return
        row = self.selected(tree)
        record = self.record_for(row)
        action = self.archive_action_for(row)
        if action and action["kind"] == "merge_original":
            if action["state"] == "started":
                self.detail.set(f"Merge was interrupted. Check recovery.\n{action['recovery']}")
            else:
                members = self.merges.get(action["merge_id"], ())
                self.detail.set(f"Merged video · {Path(action['merged_path']).name}\n"
                                f"{len(members)} original clips recorded in recovery. Use Recovered originals to locate them.")
            return
        if row["status"] == "merge_history" and not action:
            self.detail.set("This merge record has changed. Rescan the archive.")
            return
        note = "Pending verification."
        if action:
            note = f"Original recovery path: {action['recovery']}"
            if action["state"] == "started":
                note = f"Cleanup was interrupted. Check the archive and recovery folder.\n{action['recovery']}"
        elif record:
            names = ", ".join(name or "(unnamed)" for name in record["audio_names"])
            note = f"Verified copy · {names}"
        elif row["status"] == "redundant":
            note = "Fully covered by the supporting clips. Review only."
        elif row["status"] == "overlap_review":
            matches = review_witnesses(row)
            note = "Overlap review only. " + " · ".join(
                f"{Path(match['clip']).name}: {match['reason'] or 'Verified match; no cut scheduled for this clip.'}"
                for match in matches[:2])
        elif row["clip"] in self.failures:
            note = self.failures[row["clip"]]
        evidence = "  ·  ".join(f"{coverage_label(entry)}: {entry['clip']}" for entry in review_witnesses(row))
        self.detail.set(f"Coverage: {evidence}\n{note}")

    def clear_preview(self, message="Select a verified copy from the processing list."):
        self.preview_generation += 1
        self.preview_key = None
        self.compare.reset(message)
        if 'align' in message.casefold():self.compare.alignment_spinner.start()

    def tab_changed(self, event=None):
        if self.tabs.select() == str(self.review_tab):
            self.queue_changed()
        else:
            if self.preview_key:
                self.clear_preview()
            self.selection_changed()
        self.schedule_settings()

    def set_preview_mode(self, mode):
        self.preview_mode = mode if mode in {"coverage", "trim"} else "coverage"
        self.coverage_button.configure(style="Primary.TButton" if self.preview_mode == "coverage" else "Round.TButton")
        self.trim_button.configure(style="Primary.TButton" if self.preview_mode == "trim" else "Round.TButton")
        self.queue_changed()
        self.schedule_settings()

    def next_coverage(self):
        self.coverage_page += 1
        self.queue_changed()

    def show_supports(self, supports):
        if len(supports) > 2:
            earlier = next((entry for entry in supports if coverage_label(entry) == "Earlier coverage"), None)
            later = next((entry for entry in supports if coverage_label(entry) == "Later coverage"), None)
            if earlier and later:
                supports = [earlier, later] + [entry for entry in supports if entry not in (earlier, later)]
        count = (len(supports) + 1) // 2
        if count > 1:
            self.coverage_page %= count
            self.more_coverage.pack(side="left", padx=(6, 0), before=self.more_coverage.master.winfo_children()[-1])
            self.coverage_counter.set(f"Coverage {self.coverage_page + 1} of {count}")
        else:
            self.more_coverage.pack_forget()
            self.coverage_counter.set("")
            self.coverage_page = 0
        self.visible_supports = supports[self.coverage_page * 2:self.coverage_page * 2 + 2]

    def review_selected(self):
        selection = self.tree.selection()
        if not selection:
            self.status.set("Select a replay to review.")
            return
        item = selection[0]
        row = self.selected()
        if row["status"] == "overlap_review":
            item = self.group_by_clip.get(row["clip"])
            if not item:
                self.status.set("No remaining partner for this overlap. Rescan the archive.")
                return
        if not self.queue.exists(item):
            self.processing[row["clip"]] = "Proposed"
            self.fill()
        self.queue.selection_set(item)
        self.queue.see(item)
        self.tabs.select(self.review_tab)
        self.queue_changed()

    @staticmethod
    def checked_copy(record, destination):
        path = Path(record["output"])
        if path.resolve(strict=True) != path or not path.is_relative_to(destination):
            raise ValueError("The recorded copy moved outside the review folder.")
        if hash_file(path) != record["copy_sha256"]:
            raise ValueError("The copy has changed since verification.")
        return path

    def queue_changed(self, event=None):
        if self.tabs.select() != str(self.review_tab) or self.merge_installing:
            return
        selection = self.queue.selection()
        group = self.group_items.get(selection[0]) if selection else None
        self.group_controls(bool(group))
        if group:
            names, items = group
            if set(selection) != set(items):
                self.queue.selection_set(items)
            self.open_overlap_group(names)
            return
        self.selection_changed(tree=self.queue)
        read_only = bool(self.queue.selection() and self.selected(self.queue)["status"] == "overlap_review")
        self.trim_button.configure(state="disabled" if read_only else "normal")
        for button in self.cleanup_buttons:
            button.configure(state="disabled" if self.busy or read_only else "normal")
        if not self.queue.selection():
            self.preview_row = None
            self.show_supports([])
            self.clear_preview()
            return
        row = self.selected(self.queue)
        action = self.archive_action_for(row)
        if action and action["kind"] == "merge_original" and action["state"] == "done":
            self.open_completed_merge(action)
            return
        if action:
            self.preview_row = None
            self.show_supports([])
            message = ("Cleanup was interrupted. Check the archive and the recovery folder."
                       if action["state"] == "started" else
                       "The full original is in recovery. Use Open recovery folder to find it.")
            self.clear_preview(message)
            return
        if row["status"] == "merge_history":
            self.clear_preview("This merge record has changed. Rescan the archive.")
            return
        record = self.record_for(row)
        try:
            supports = review_witnesses(row)
        except (ValueError, KeyError) as error:
            self.clear_preview(str(error))
            return
        if row["clip"] != self.preview_row:
            self.preview_row = row["clip"]
            self.coverage_page = 0
        is_trim = self.preview_mode == "trim" and not read_only
        self.show_supports([] if is_trim else supports)
        if is_trim and not record:
            self.clear_preview("Make a verified copy to compare the trim. Coverage shows the supporting clips.")
            return
        chosen = self.visible_supports[:]
        key = (row["clip"], self.preview_mode, record["id"] if is_trim else tuple(p["clip"] for p in chosen))
        if key == self.preview_key:
            return
        try:
            root, destination = self.paths()
            if root != self.source_root:
                raise ValueError("Load the report for the current archive to review these clips.")
            source = archive_clip(root, row["clip"])
            if row.get("source_identity") and list(source.file_id) != json.loads(row["source_identity"]):
                raise ValueError("The original changed since the scan. Run a fresh scan.")
            duration = float(row.get("original_seconds") or 0)
            retained = None if row["status"] != "candidate" else (
                float(row["proposed_head_trim_seconds"]), float(row.get("retained_end_seconds") or duration))
        except (ValueError, OSError) as error:
            self.clear_preview(str(error))
            return
        self.clear_preview("Opening supporting footage…" if chosen else "Checking the trimmed copy before opening the comparison…")
        self.preview_key = key
        generation = self.preview_generation

        def verify():
            try:
                panes = [Pane(source.path, "original", 0, duration)]
                if is_trim:
                    path = self.checked_copy(record, destination)
                    kept = record["trim_start_seconds"], record["retained_end_seconds"]
                    panes.append(Pane(path, "trimmed", *kept, -kept[0]))
                else:
                    kept = retained
                    for entry in chosen:
                        peer = archive_clip(root, entry["clip"])
                        if entry.get("identity") and list(peer.file_id) != entry["identity"]:
                            raise ValueError(f"{peer.path.name} changed since the scan. Run a fresh scan.")
                        if all(key in entry for key in ("start", "end", "offset")):
                            start, end, offset = (float(entry[key]) for key in ("start", "end", "offset"))
                        else:
                            ffprobe = self.tools()["ffprobe"]
                            original, support = probe(source, ffprobe, 180), probe(peer, ffprobe, 180)
                            coverage = (video_alignment(original, support) if read_only else
                                        pair_coverage(original, support, entry["clip"]))
                            if coverage is None:
                                raise ValueError("Could not align the supporting clip. Run a fresh scan.")
                            start, end, offset = coverage.start, coverage.end, coverage.offset
                        role = "earlier" if offset > .1 else "later" if offset < -.1 else "support"
                        panes.append(Pane(peer.path, role, start, end, offset))
                comparison = (panes, duration, kept)
                self.events.put(("preview", (generation, comparison, None)))
            except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
                self.events.put(("preview", (generation, None, str(error))))

        threading.Thread(target=verify, daemon=True).start()

    def group_controls(self, active):
        self.merged_link.pack_forget()
        self.recovery_button.configure(text="Open Recovery Folder")
        if active:
            for control in (*self.preview_links, *self.cleanup_buttons, self.trim_button, self.more_coverage):
                control.pack_forget()
            self.coverage_button.configure(text="Full Clips", style="Primary.TButton")
        else:
            self.next_group.pack_forget()
            self.group_actions.pack_forget()
            for control in self.group_remove:
                control.pack_forget()
            for control in (*self.preview_links, *self.cleanup_buttons):
                control.pack(side="left", padx=(0, 5))
            self.coverage_button.configure(text="Coverage", style="Primary.TButton" if self.preview_mode == "coverage" else "Round.TButton")
            self.trim_button.pack(side="left", after=self.coverage_button)

    @staticmethod
    def checked_merged(root, action):
        path = Path(action["merged_path"])
        clip = archive_clip(root, str(path.relative_to(root)))
        if hash_file(clip.path) != action["merged_sha256"]:
            raise ValueError("The merged video changed since verification.")
        check_file(clip.path, clip.file_id)
        return clip.path

    def open_completed_merge(self, action):
        self.show_supports([])
        for control in (*self.preview_links, *self.cleanup_buttons, self.trim_button):
            control.pack_forget()
        self.coverage_button.configure(text="Merged Video", style="Primary.TButton")
        self.merged_link.pack(side="left", padx=(0, 5))
        self.recovery_button.configure(text="Recovered Originals…")
        key = ("completed merge", action["merge_id"])
        if key == self.preview_key:
            return
        self.clear_preview("Checking the merged video before playback…")
        self.preview_key = key
        generation = self.preview_generation
        try:
            root, _ = self.paths()
            if root != self.source_root:
                raise ValueError("Load a report for the current archive.")
            ffprobe = self.tools()["ffprobe"]
        except (ValueError, OSError) as error:
            self.clear_preview(str(error))
            return

        def verify():
            try:
                path = self.checked_merged(root, action)
                result = run_media([ffprobe, "-v", "error", "-protocol_whitelist", "file",
                                    "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                                   timeout=45)
                duration = float(result)
                if not math.isfinite(duration) or duration <= 0:
                    raise ValueError("The merged video's duration could not be read.")
                self.events.put(("merged_preview", (generation, (path, duration), None)))
            except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
                self.events.put(("merged_preview", (generation, None, str(error))))

        threading.Thread(target=verify, daemon=True).start()

    def open_merged_external(self):
        try:
            root, _ = self.paths()
            if root != self.source_root:
                raise ValueError("Load a report for the current archive.")
            action = self.archive_action_for(self.selected(self.queue))
            if not action or action["kind"] != "merge_original" or action["state"] != "done":
                raise ValueError("Select a completed merge first.")
        except (ValueError, OSError) as error:
            self.error("Could not open merged video", str(error))
            return
        self.status.set("Checking the merged video's checksum…")

        def verify():
            try:
                path = self.checked_merged(root, action)
                self.events.put(("external", (path, None)))
            except (ValueError, OSError, KeyError) as error:
                self.events.put(("external", (None, str(error))))

        threading.Thread(target=verify, daemon=True).start()

    def open_overlap_group(self, names):
        key = ("overlap group", names)
        if key == self.preview_key:
            return
        self.clear_preview("Aligning the full clips…")
        self.preview_key = key
        self.group_layout = []
        self.group_page = 0
        self.coverage_counter.set("")
        self.next_group.pack_forget()
        self.group_actions.pack_forget()
        self.merge_all.pack_forget()
        for button in self.group_remove:
            button.pack_forget()
        self.detail.set("Colored lanes show full clip spans. The coverage label above each preview checks the actual packets.")
        generation = self.preview_generation
        root = self.source_root
        edges = self.group_edges
        try:
            if self.paths()[0] != root:
                raise ValueError("Load a report for the current archive.")
            ffprobe = self.tools()["ffprobe"]
        except (OSError, ValueError) as error:
            self.clear_preview(str(error))
            return

        def verify():
            try:
                clips = {name: archive_clip(root, name) for name in names}
                starts = {names[0]: 0.0}
                durations = {}
                pending = [names[0]]
                cache = {}

                def read(name):
                    if name not in cache:
                        if len(cache) == 8:
                            cache.pop(next(iter(cache)))
                        cache[name] = probe(clips[name], ffprobe, 180)
                    durations[name] = cache[name].duration
                    return cache[name]

                while pending and len(starts) < len(clips):
                    name = pending.pop()
                    original = read(name)
                    for peer in sorted(edges[name].intersection(clips).difference(starts)):
                        if match := video_alignment(original, read(peer)):
                            starts[peer] = starts[name] - match.offset
                            pending.append(peer)
                if len(starts) != len(clips):
                    raise ValueError("A clip in this group changed or could not align. Rescan the archive.")
                layout = []
                for name in sorted(starts, key=lambda name: (clips[name].capture_time, name)):
                    original = read(name)
                    video_matches, proofs = [], []
                    for peer in sorted(edges[name].intersection(clips)):
                        support = read(peer)
                        alignment = video_alignment(original, support)
                        if not alignment:
                            continue
                        video_matches.append(Coverage(peer, [alignment.span], alignment.offset,
                                                      alignment.start, alignment.end))
                        if proof := pair_coverage(original, support, peer):
                            proofs.append(proof)
                    if all(covers_packets(proofs, i, 0, len(track.hashes)) for i, track in enumerate(original.tracks)):
                        note = "Video and audio covered"
                    elif covers_packets(video_matches, 0, 0, len(original.tracks[original.video].hashes)):
                        note = "Video covered · check audio"
                    else:
                        note = "Full coverage unverified"
                    layout.append((clips[name], starts[name], durations[name], note))
                self.events.put(("group_preview", (generation, layout, None)))
            except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
                self.events.put(("group_preview", (generation, None, str(error))))

        threading.Thread(target=verify, daemon=True).start()

    def group_pages(self):
        last = max(0, len(self.group_layout) - GROUP_PANES)
        return [*range(0, last, GROUP_PANES - 1), last]

    def show_group_page(self, position=None, resume=False):
        layout = self.group_layout
        pages = self.group_pages()
        start_index = pages[self.group_page]
        self.visible_group = layout[start_index:start_index + GROUP_PANES]
        anchor = min(start for _, start, _, _ in layout)
        panes = [Pane(clip.path, "original" if i == 0 else "later", start - anchor,
                      start - anchor + duration, anchor - start, note)
                 for i, (clip, start, duration, note) in enumerate(self.visible_group)]
        overview = tuple((start - anchor, start - anchor + duration, CLIP_COLORS[i % len(CLIP_COLORS)])
                         for i, (_, start, duration, _) in enumerate(layout))
        self.compare.load(panes, max(end for _, end, _ in overview), None, True, overview, start_index,
                          position, resume,audio_files=tuple(row[0].path for row in layout))
        self.coverage_counter.set("1 remaining clip" if len(layout) == 1 else f"{len(layout)} linked clips" if len(pages) == 1 else
                                  f"Clips {start_index + 1}–{start_index + len(panes)} of {len(layout)}")
        if len(pages) > 1:
            self.next_group.pack(side="left", padx=(6, 0))
        self.group_actions.pack(fill="x", pady=(5, 0), before=self.cleanup_buttons[0].master)
        for i, button in enumerate(self.group_remove):
            if i < len(panes) and len(layout) > 1:
                label = "Earlier" if i == 0 else "Later" if i == len(panes) - 1 else "Middle"
                caption = f"Recover clip {start_index + i + 1}…" if len(layout) > 3 else f"Move {label} to recovery…"
                button.configure(text=__import__('review_buttons').title(caption), width=max(18, len(caption) + 1),
                                 style=f"Clip{(start_index + i) % len(CLIP_COLORS)}.Round.TButton",
                                 state="disabled" if self.busy else "normal")
                button.pack(side="left", padx=(0, 5))
            else:
                button.pack_forget()
        self.merge_all.configure(state="disabled" if self.busy else "normal")
        if len(layout) > 1:
            self.merge_all.pack(side="left", padx=(8, 0))
        else:
            self.merge_all.pack_forget()

    def next_group_page(self):
        if self.group_layout:
            self.group_page = (self.group_page + 1) % len(self.group_pages())
            self.show_group_page()

    def open_group_lane(self, position, lane=None):
        overview = self.compare.overview
        if not overview or not self.group_layout:
            return False
        if lane is None:
            point = min(position, self.compare.timeline_duration() - .04)
            lane = next((i for i, (start, end, _) in enumerate(overview) if start <= point < end - .035), None)
            if lane is None:
                return False
        first = self.group_pages()[self.group_page]
        if first <= lane < first + GROUP_PANES:
            return False
        self.group_page = next(i for i, start in enumerate(self.group_pages()) if start <= lane < start + GROUP_PANES)
        start, end, _ = overview[lane]
        self.show_group_page(max(start, min(position, end - .04)), self.compare.playing)
        return True

    def remove_group_clip(self, index):
        selected = self.queue.selection()
        if (self.busy or not selected or selected[0] not in self.group_items or not self.group_layout
                or not self.compare.full_timeline or self.compare.priming or index >= len(self.visible_group)):
            return
        clip = self.visible_group[index][0]
        remaining = [other.path for other, _, _, _ in self.group_layout if other.path != clip.path]
        try:
            root, destination = self.paths()
            if root != self.source_root:
                raise ValueError("Load a report for the current archive.")
            name = str(clip.path.relative_to(root))
            peers = [other for other, _, _, _ in self.group_layout
                     if str(other.path.relative_to(root)) in self.group_edges.get(name, ())]
            if not peers:
                raise ValueError("There is no remaining matching clip in this group.")
            ffprobe = self.tools()["ffprobe"]
            row = {"clip": name, "status": "overlap_review", "source_identity": json.dumps(clip.file_id),
                   "coverage": json.dumps([{"clip": str(peer.path.relative_to(root)), "identity": peer.file_id,
                                             "start": 0, "end": 0, "offset": 0} for peer in peers])}
        except (OSError, ValueError) as error:
            self.error("Cannot move this clip", str(error))
            return
        message = (f"Move the full clip to recovery?\n\n{clip.path}\n\nRecovery folder\n{destination / RECOVERY_FOLDER}\n\n"
                   "This clip may contain unique footage or audio. Moving it removes the whole clip from the archive. "
                   "Keep the recovery copy if you might need that footage.")
        if not confirm_action(self.root, "Move clip to recovery", message, "Move to recovery"):
            return
        self.clear_preview("Closing playback before moving the clip…")
        self.group_layout = []
        self.status.set("Checking the overlap and recovery destination…")

        def finish(result):
            self.refresh_copies(destination)
            self.fill()
            item = next((self.group_by_clip.get(str(path.relative_to(root))) for path in remaining
                         if str(path.relative_to(root)) in self.group_by_clip), self.row_ids.get(name))
            if item and self.queue.exists(item):
                self.queue.selection_set(item)
                self.queue.see(item)
                self.queue_changed()
            self.status.set(f"Moved {clip.path.name} to recovery. Use Open recovery folder to find it.")

        self.run_job(lambda: cleanup(root, destination, row, "delete_original", None, ffprobe,
                                     self.plan_overlap, manual_overlap=True), finish)

    def merge_group(self):
        selected = self.queue.selection()
        if self.busy or not selected or selected[0] not in self.group_items or len(self.group_layout) < 2:
            return
        try:
            root, destination = self.paths()
            if root != self.source_root:
                raise ValueError("Load a report for the current archive.")
            clips = tuple(item[0] for item in self.group_layout)
            names, _ = self.group_items[selected[0]]
            indices = {clip.path: i for i, clip in enumerate(clips)}
            report_indices = {name: indices[archive_clip(root, name).path] for name in names}
            edges = [set() for clip in clips]
            for name, index in report_indices.items():
                edges[index].update(report_indices[peer] for peer in self.group_edges[name] if peer in report_indices)
            tools = self.tools()
        except (OSError, ValueError, KeyError) as error:
            self.error("Cannot merge this group", str(error))
            return

        self.clear_preview("Checking all clips in the group…")
        self.status.set(f"Preparing a verified merge of {len(clips)} clips…")

        def prepare():
            return prepare_merge(destination, clips, edges, tools, self.report_status)

        def prepared(merge):
            oldest = merge.clips[0].path
            duration = timestamp(merge.duration)
            names = ", ".join(name or "(unnamed)" for name in merge.audio_names) or "No audio tracks"
            timing = (f"\n\nMatching audio packets will use one continuous timeline. The largest placement adjustment "
                      f"between audio and video is {merge.audio_shift * 1000:.2f} ms."
                      if merge.audio_shift > .0001 else "")
            coverage = (f"\n\nThe merged file also preserves coverage for {len(merge.dependencies)} earlier archive edits."
                        if merge.dependencies else "")
            message = (f"Install a verified {duration} merge of {len(merge.clips)} clips at the oldest clip's path?\n\n"
                       f"{oldest}\n\nAudio tracks · {names}{timing}{coverage}\n\n"
                       f"All full originals will move to {destination / RECOVERY_FOLDER}. The merge uses the original encoded packets.")
            try:
                accepted = confirm_action(self.root, "Merge All", message, "Install verified merge")
            except Exception:
                merge.folder.cleanup()
                raise
            if not accepted:
                merge.folder.cleanup()
                self.status.set("Merge canceled. The original clips are available for review.")
                self.queue_changed()
                return
            self.clear_preview("Closing playback before installing the merge…")
            self.merge_installing = True

            def install():
                try:
                    return install_merge(root, destination, merge, self.report_status)
                finally:
                    merge.folder.cleanup()

            def refresh():
                self.merge_installing = False
                self.refresh_copies(destination)
                self.fill()

            def finish(result):
                path, recovery = result
                if self.host:self.host.map_archive_merge(merge,recovery)
                refresh()
                item = next((str(i) for i, row in enumerate(self.rows) if self.row_path(row) == path), None)
                if item and self.queue.exists(item):
                    self.queue.selection_set(item)
                    self.queue.see(item)
                    self.queue_changed()
                self.status.set(f"Merged {len(clips)} clips into {path.name}. Recovery manifest: {recovery}")

            self.run_job(install, finish, refresh)

        self.run_job(prepare, prepared)

    def export(self, all_pending):
        try:
            root, destination = self.paths()
            if root != self.source_root:
                raise ValueError("The source changed. Load the matching report or scan again.")
            if self.requested_overlap() != self.plan_overlap:
                raise ValueError("The overlap setting changed. Scan again to make a new plan.")
            tools = self.tools()
            gib = float(self.cap.get())
            if not math.isfinite(gib) or gib <= 0:
                raise ValueError("Enter a positive batch cap.")
            budget = int(gib * 1024 ** 3)
            self.refresh_copies(destination)
            selected = self.rows if all_pending else [self.selected()]
            rows = [row for row in selected if row["status"] == "candidate"
                    and not self.archive_action_for(row) and not self.record_for(row)]
            if not rows:
                self.status.set("No trim copies are pending. Fully covered clips are review-only.")
                self.fill()
                return
            overlap = self.plan_overlap
        except Exception as error:
            self.error("Check export settings", str(error))
            return
        self.status.set("Preparing the verified copy batch…")
        self.processing.update({row["clip"]: "Queued" for row in rows})
        self.fill()
        self.tabs.select(self.review_tab)

        def task():
            remaining, completed, failures = budget, 0, {}
            for number, row in enumerate(rows, 1):
                self.report_status(f"[{number}/{len(rows)}] Checking and copying {row['clip']}…")
                self.events.put(("processing", (row["clip"], "Processing", None, None)))
                try:
                    result = export_candidate(root, destination, row, tools, remaining, overlap)
                    remaining -= result["copy_bytes"]
                    completed += 1
                    self.events.put(("processing", (row["clip"], "Verified", result, None)))
                except Exception as error:
                    failures[row["clip"]] = str(error)
                    self.events.put(("processing", (row["clip"], "Skipped", None, str(error))))
            return completed, failures

        def finish(result):
            completed, failures = result
            self.failures.update(failures)
            self.refresh_copies(destination)
            self.fill()
            self.status.set(f"Batch finished. {completed} verified copies, {len(failures)} skipped.")

        self.run_job(task, finish)

    def cleanup_selected(self, kind):
        if self.busy:
            return
        try:
            row = self.selected(self.queue)
            if row["status"] == "overlap_review":
                raise ValueError("This overlap is available for preview only.")
            root, destination = self.paths()
            if root != self.source_root:
                raise ValueError("Load the report for the current archive first.")
            self.refresh_copies(destination)
            record = self.record_for(row)
            prior_action = self.archive_action_for(row)
            if prior_action and prior_action["state"] == "started":
                raise ValueError("An earlier cleanup of this clip still needs recovery review.")
            if kind != "delete_trimmed" and prior_action:
                raise ValueError("The original was already moved to recovery.")
            if kind == "delete_trimmed" and not self.row_path(row).is_file():
                raise ValueError("Restore the original before moving its only active trimmed copy to recovery.")
            if not record and (kind != "delete_original" or row["status"] != "redundant"):
                raise ValueError("A verified trimmed copy is required for this action.")
            ffprobe = self.tools()["ffprobe"] if kind != "delete_trimmed" else None
        except (ValueError, OSError, KeyError) as error:
            self.error("Cleanup unavailable", str(error))
            return
        title, explanation = {
            "delete_original": ("Delete Original", "Move the full original out of the archive."),
            "delete_trimmed": ("Delete Trimmed", "Move the verified trimmed copy out of the review folder."),
            "replace_original": ("Replace Original", "Put the verified trim at the original path using the original filename."),
        }[kind]
        target = Path(record["output"]) if kind == "delete_trimmed" else self.row_path(row)
        message = (f"{explanation}\n\n{target}\n\nRecovery folder\n{destination / RECOVERY_FOLDER}\n\n"
                   "It can be restored from there. Storage is reclaimed when you clear that recovery copy.")
        if not confirm_action(self.root, title, message, title):
            return
        self.clear_preview("Closing playback and checking the selected files…")
        self.status.set(f"{title} · checking the selected clip…")
        record_id = record["id"] if record else None
        overlap = self.plan_overlap

        def task():
            result=cleanup(root, destination, row, kind, record_id, ffprobe, overlap)
            if self.host and kind=='replace_original':
                metadata=json.loads(run_media([ffprobe,'-v','error','-select_streams','v:0','-read_intervals','%+#1',
                    '-show_packets','-show_format','-show_entries','packet=pts_time:format=start_time','-of','json',str(target)]))
                result['video_origin']=float(metadata['packets'][0]['pts_time'])-float(metadata['format'].get('start_time',0))
            return result

        def finish(result):
            if self.host:self.host.map_archive_replacement(result,record)
            self.processing[row["clip"]] = "Proposed"
            self.refresh_copies(destination)
            self.fill()
            if kind == "delete_trimmed":
                self.status.set(f"Completed. Recovery: {Path(result['recovery']).parent}")
            else:
                self.status.set("Completed. Use Rescan archive to find follow-up cuts. Open recovery folder shows the full original.")

        def failed():
            self.refresh_copies(destination)
            self.fill()

        self.run_job(task, finish, failed)

    def open_recovery(self):
        try:
            _, destination = self.paths()
            self.refresh_copies(destination)
            selection = self.queue.selection()
            if selection and selection[0] in self.group_items:
                action = None
            else:
                row = self.selected(self.queue)
                action = self.latest_actions.get(os.path.normcase(str(self.row_path(row))))
            if action and action["kind"] == "merge_original" and action["state"] == "done":
                self.show_recovered_originals(action)
                return
            path = (Path(action["recovery"]).parent if action else destination / RECOVERY_FOLDER).resolve(strict=True)
            explorer = Path(os.environ["WINDIR"]) / "explorer.exe"
            subprocess.Popen([str(explorer), str(path)])
        except (OSError, ValueError) as error:
            self.error("Could not open recovery folder", str(error))

    def show_recovered_originals(self, action):
        members = self.merges.get(action["merge_id"], ())
        window = tk.Toplevel(self.root)
        window.title("Recovered originals")
        window.geometry("970x400")
        window.transient(self.root)
        dark_title(window)
        panel = ttk.Frame(window, padding=14)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text=f"Recovered originals for {Path(action['merged_path']).name}",
                  style="Subheading.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(panel, text="Explorer can select the recovery folders together. Select a row to highlight that video file.",
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 8))
        table = ttk.Frame(panel)
        table.pack(fill="both", expand=True)
        view = ttk.Treeview(table, columns=("original", "state", "folder"), show="headings", selectmode="browse")
        for key, label, width in (("original", "Original clip", 275), ("state", "Status", 110), ("folder", "Recovery folder", 530)):
            view.heading(key, text=label)
            view.column(key, width=width, stretch=key == "folder")
        bar = ttk.Scrollbar(table, orient="vertical", command=view.yview)
        view.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        view.pack(fill="both", expand=True)
        available = {}
        for i, member in enumerate(members):
            source, recovery = Path(member["source"]), Path(member["recovery"])
            item = str(i)
            try:
                validate_recovery_path(member, self.paths()[1])
                check_file(recovery, member.get("recovery_identity", member["original_identity"]))
                available[item] = recovery
                state = "In recovery"
            except FileNotFoundError:
                state = "File missing"
            except (OSError, ValueError):
                state = "Check file"
            view.insert("", "end", iid=item, values=(source.name, state, str(recovery.parent)))
        if available:
            view.selection_set(next(iter(available)))

        def reveal(all_folders=False):
            items = list(dict.fromkeys(path.parent for path in available.values())) if all_folders else [
                available[item] for item in view.selection() if item in available]
            if items:
                try:
                    reveal_paths(items)
                except OSError as error:
                    show_error(window, "Could not open Explorer", str(error))

        footer = ttk.Frame(panel)
        footer.pack(fill="x", pady=(9, 0))
        open_selected = ttk.Button(footer, text="Show selected original in Explorer", style="Round.TButton", command=reveal)
        open_selected.pack(side="left")
        ttk.Button(footer, text="Show all recovery folders in Explorer", style="Round.TButton",
                   command=lambda: reveal(True), state="normal" if available else "disabled").pack(side="left", padx=8)
        ttk.Button(footer, text="Close", style="Round.TButton", command=window.destroy).pack(side="right")

        def selection_changed(event=None):
            open_selected.configure(state="normal" if any(item in available for item in view.selection()) else "disabled")

        view.bind("<<TreeviewSelect>>", selection_changed)
        view.bind("<Double-1>", lambda event: reveal())
        selection_changed()

    def open_video(self, kind, tree=None):
        try:
            row = self.selected(tree)
            root, destination = self.paths()
            if root != self.source_root:
                raise ValueError("The source changed. Load its report again.")
            if kind == "copy":
                self.refresh_copies(destination)
                record = self.record_for(row)
                if not record:
                    raise ValueError("Make a verified copy for this replay first.")
                self.status.set("Checking the copy against its recorded checksum…")

                def verify():
                    try:
                        path = self.checked_copy(record, destination)
                        self.events.put(("external", (path, None)))
                    except (ValueError, OSError) as error:
                        self.events.put(("external", (None, str(error))))

                threading.Thread(target=verify, daemon=True).start()
                return
            if kind == "support":
                for entry in self.visible_supports or review_witnesses(row)[:2]:
                    self.launch_player(archive_clip(root, entry["clip"]).path)
                return
            else:
                path = archive_clip(root, row["clip"]).path
            self.launch_player(path)
        except Exception as error:
            self.error("Could not open video", str(error))

    def launch_player(self, path):
        os.startfile(str(path), "open")
        self.status.set(f"Opened {path.name} in the default Windows player.")

    def open_review(self):
        try:
            if not self.destination.get().strip():
                raise ValueError("Choose a review folder first.")
            destination = Path(self.destination.get()).resolve(strict=True)
            if not destination.is_dir():
                raise ValueError("Choose an existing review folder.")
            explorer = Path(os.environ["WINDIR"]) / "explorer.exe"
            subprocess.Popen([str(explorer), str(destination)])
        except (OSError, ValueError) as error:
            self.error("Could not open review folder", str(error))

    def save_index(self):
        try:
            _, destination = self.paths()
            index = destination / f"verified-copies-{datetime.now():%Y%m%d-%H%M%S-%f}.csv"
            write_copy_index(destination, index)
            self.status.set(f"Saved {index.name} in the review folder.")
        except Exception as error:
            self.error("Could not save index", str(error))

    def close(self):
        if self.busy:
            if self.scanning:self.close_after_cancel=True;self.cancel_scan();return
            self.status.set("Please wait for the current operation to finish before closing.")
        else:
            self.root.after_cancel(self.drain_timer)
            if self.load_timer:
                self.root.after_cancel(self.load_timer)
            if self.settings_timer:
                self.root.after_cancel(self.settings_timer)
            self.save_settings()
            self.compare.close()
            self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    ReviewApp(window)
    window.mainloop()
