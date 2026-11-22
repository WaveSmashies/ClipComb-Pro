# SPDX-License-Identifier: GPL-3.0-or-later
"""A shared original-time clock for a trim or several coverage clips."""

from dataclasses import dataclass
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk

from review_cleanup_player import AUDIO_MODES, POLL_MS, Player, Timeline, Vlc, timestamp
from review_cleanup_theme import ACCENT, MUTED, PANEL, VIDEO


COVERAGE_COLORS = ("#71d7d0", "#f2ba7e")
CLIP_COLORS = ("#bd9aff", *COVERAGE_COLORS, "#8fb8ff", "#f39bc2", "#a9dd89")
GROUP_PANES = 4
ROLES = ("original", "trimmed", "earlier", "later", "support", "earlier_2", "later_2", "later_3", "support_2")


@dataclass(frozen=True)
class Pane:
    path: Path
    role: str
    start: float
    end: float
    offset: float = 0
    note: str = ""


class SharedTimeline(Timeline):
    def __init__(self, parent, seek):
        super().__init__(parent, seek)
        self.palette=dict(getattr(self._root(),'review_palette',{}))
        self.bands = ()
        self.lane_step = 12
        self.open_lane = None

    def set_bands(self, bands):
        if bands != self.bands:
            self.bands = bands
            self.lane_step = min(12, max(3, 104 // max(1, len(bands))))
            self.configure(height=30 + len(bands) * self.lane_step)
            self.draw()

    def draw(self):
        super().draw()
        if self.duration <= 0:
            return
        width = max(18, self.winfo_width())
        for i, (start, end, color) in enumerate(self.bands):
            left, right = (8 + min(1, max(0, point / self.duration)) * (width - 16) for point in (start, end))
            y = 30 + i * self.lane_step
            self.create_line(8, y, width - 8, y, fill=self.palette.get("border","#252b39"), width=3, capstyle="round")
            self.create_line(left, y, right, y, fill=color, width=min(5, self.lane_step - 1), capstyle="round")
        if self.bands:
            x = 8 + min(1, max(0, self.time / self.duration)) * (width - 16)
            self.create_line(x, 24, x, 31 + (len(self.bands) - 1) * self.lane_step, fill=self.palette.get("playhead",ACCENT), width=1)

    def released(self, event):
        lane = (event.y - 30 + self.lane_step // 2) // self.lane_step
        if self.open_lane and event.y >= 26 and 0 <= lane < len(self.bands) and self.duration:
            self.dragging = False
            if self.scrub:self.scrub('cancel',self.position_at(event))
            if self.open_lane(lane, self.position_at(event)):
                return
        super().released(event)


class CompareView(ttk.Frame):
    def __init__(self, parent, folder_for_vlc, settings_changed,app=None):
        super().__init__(parent)
        self.audio_device=app.settings.data['audio']['output_device'] if app else 'auto'
        self.scrub_previews={};self.source_fps=[]
        self.scrubbing=False;self.scrub_target=None;self.scrub_sent=None;self.scrub_until=0.;self.scrub_resume=False
        self.app=app;self.transport=None;self.rate=app.speed if app else 1.
        self.folder_for_vlc = folder_for_vlc
        self.settings_changed = settings_changed
        self.vlc = None
        self.players = []
        self.panes = []
        self.cards = []
        self.card_notes = []
        self.running = set()
        self.joining = {}
        self.unavailable = set()
        self.durations = []
        self.track_options = []
        self.priming = None
        self.pending = None
        self.playing = False
        self.audio_mode = "Both"
        self.audio_side = tk.StringVar(value=self.audio_mode)
        self.audio_choices = {role: 0 for role in ROLES}
        self.volume = 100
        self.volume_position = tk.DoubleVar(value=self.volume)
        self.volume_label = tk.StringVar(value="100%")
        self.info = tk.StringVar(value="Select a clip to review.")
        self.range_label = tk.StringVar()
        self.sync_label = tk.StringVar()
        self.retained = None
        self.full_timeline = False
        self.single_title = None
        self.overview = ()
        self.overview_first = 0
        self.audio_files=();self.audio_first=0
        self.open_hidden = None
        self.clock_index = 0
        self.build()
        self.timeline.scrub=self.scrub_event
        if self.app:self.app.shortcut_tags(self.timeline)
        palette=getattr(self._root(),'review_palette',{})
        for card,heading,name,surface,position,tracks in self.cards:
            surface.configure(bg=palette.get('video_background',VIDEO))
        self.timeline.configure(bg=palette.get('panel',PANEL))
        self.timer = None if self.app else self.after(POLL_MS, self.tick)

    def build(self):
        heading=ttk.Frame(self);heading.pack(fill='x')
        ttk.Label(heading,text='Compare footage',style='Subheading.TLabel').pack(side='left')
        from review_spinner import Spinner
        self.alignment_spinner=Spinner(heading);self.alignment_spinner.pack(side='left',padx=8)
        ttk.Label(self, textvariable=self.info, style="Hint.TLabel", wraplength=920).pack(anchor="w", pady=(1, 7))
        self.video_grid = ttk.Frame(self)
        self.video_grid.pack(fill="both", expand=True)
        self.video_grid.rowconfigure(0, weight=1)
        for i in range(GROUP_PANES):
            card = ttk.Frame(self.video_grid, padding=8, style="Panel.TFrame")
            heading = ttk.Label(card, text="", style="PanelHeading.TLabel")
            heading.pack(anchor="w")
            name = ttk.Label(card, text="", style="PanelHint.TLabel", width=28)
            name.pack(anchor="w", fill="x", pady=(0, 4))
            note = ttk.Label(card, text="", style="PanelHint.TLabel")
            self.card_notes.append(note)
            surface = tk.Frame(card, bg=VIDEO, height=130, width=155)
            surface.pack(fill="both", expand=True)
            surface.pack_propagate(False)
            position = tk.StringVar()
            ttk.Label(card, textvariable=position, style="PanelHint.TLabel").pack(anchor="w", pady=(4, 2))
            tracks = ttk.Combobox(card, width=19, state="disabled")
            tracks.pack(fill="x")
            tracks.bind("<<ComboboxSelected>>", lambda event, index=i: self.choose_track(index))
            self.cards.append((card, heading, name, surface, position, tracks))
        self.empty = ttk.Label(self.video_grid, text="Select a clip to start the comparison.", style="Hint.TLabel")
        self.empty.place(relx=.5, rely=.5, anchor="center")

        timeline_frame = ttk.Frame(self, padding=(8, 4), style="Panel.TFrame")
        timeline_frame.pack(fill="x", pady=(6, 4))
        self.timeline_heading = ttk.Label(timeline_frame, text="Original timeline", style="PanelHeading.TLabel")
        self.timeline_heading.pack(anchor="w")
        self.timeline = SharedTimeline(timeline_frame, self.seek)
        self.timeline.pack(fill="x")
        ttk.Label(timeline_frame, textvariable=self.range_label, style="PanelHint.TLabel").pack(anchor="w")

        controls = ttk.Frame(self)
        controls.pack(fill="x")
        self.play_button = ttk.Button(controls, text="Play", style="Primary.TButton", command=self.toggle)
        self.play_button.pack(side="left", padx=(0, 6))
        self.jump_button = ttk.Button(controls, text="Jump to overlap", style="Round.TButton", command=self.jump)
        self.jump_button.pack(side="left", padx=(0, 12))
        self.audio_label = ttk.Label(controls, text="Listen to")
        self.audio_label.pack(side="left", padx=(0, 5))
        self.audio_box = ttk.Combobox(controls, textvariable=self.audio_side, width=28, state="readonly",
                                      values=AUDIO_MODES)
        self.audio_box.pack(side="left")
        self.audio_box.bind("<<ComboboxSelected>>", self.audio_changed)
        from review_help import Tooltip
        Tooltip(self.audio_box,lambda:self.audio_side.get()+'\n\nChoose one clip, Both/All visible clips, or Muted. Choosing a clip on another page opens that page.')
        volume = ttk.Frame(controls)
        volume.pack(side="right", padx=(9, 0))
        ttk.Label(volume, text="Volume").pack(side="left", padx=(0, 6))
        self.volume_slider = ttk.Scale(volume, from_=0, to=100, length=112,
                                       variable=self.volume_position, command=self.volume_changed,
                                       style="Volume.Horizontal.TScale")
        self.volume_slider.pack(side="left")
        ttk.Label(volume, textvariable=self.volume_label, width=5, anchor="e").pack(side="left")
        ttk.Label(controls, textvariable=self.sync_label, style="Hint.TLabel").pack(side="left", padx=(9, 0))
        if self.app:
            from review_transport import Transport
            self.play_button.pack_forget()
            self.speed_label=self.app.speed_label;self.time_label=tk.StringVar();self.fps_label=tk.StringVar()
            self.transport=Transport(self,self.app,annotations=False,display=self)
            self.transport.pack(fill='x',pady=(5,0));self.transport.set_palette(self.app.palette)
            self.play_button=self.transport.buttons['play']
            self.app.shortcut_tags(self)
        self.enable(False)

    def enable(self, ready):
        for button in (self.play_button, self.jump_button):
            button.configure(state="normal" if ready else "disabled")
        self.audio_box.configure(state='readonly' if ready else 'disabled')
        if self.transport:self.transport.set_available(ready)

    def load(self, panes, duration, retained=None, full_timeline=False, overview=(), first=0,
             initial_position=None, resume=False, single_title=None,audio_files=()):
        self.reset()
        self.panes = panes
        self.retained = retained
        self.full_timeline = full_timeline
        self.single_title = single_title
        self.overview = overview
        self.overview_first = first
        self.audio_files=tuple(audio_files);self.audio_first=first
        self.timeline.open_lane = (lambda lane, point: self.open_hidden(point, lane)) if overview and self.open_hidden else None
        self.timeline_heading.configure(text="Merged timeline" if single_title else
                                        "Full timeline" if full_timeline else "Original timeline")
        self.track_options = [[] for pane in panes]
        self.durations = [duration] + [max(0, p.end + p.offset) for p in panes[1:]]
        if full_timeline:
            self.durations[0] = panes[0].end + panes[0].offset
        self.info.set(panes[0].path.name)
        self.empty.place_forget()
        coverage = any(p.role not in {"original", "trimmed"} for p in panes)
        self.update_audio_menu(coverage or full_timeline)
        self.jump_button.configure(text="Jump To Overlap" if coverage else "Jump To Trim")
        if single_title:
            self.jump_button.pack_forget()
        else:
            self.jump_button.pack(side="left", padx=(0, 12), before=self.audio_label)
        placement = list(range(len(panes))) if full_timeline else sorted(range(len(panes)), key=lambda i: (
            0 if panes[i].role == "earlier" else 1 if i == 0 else 2, i))
        for i in range(len(self.cards)):
            self.video_grid.columnconfigure(i, weight=0, uniform="")
        for i, (card, heading, name, surface, position, tracks) in enumerate(self.cards):
            card.grid_remove()
            if i < len(panes):
                column = placement.index(i)
                self.video_grid.columnconfigure(column, weight=1, uniform="preview")
                card.grid(row=0, column=column, sticky="nsew", padx=(0, 5))
                title = {"original": "Original", "trimmed": "Verified trim", "earlier": "Earlier coverage",
                         "later": "Later coverage", "support": "Supporting clip"}[panes[i].role]
                if full_timeline:
                    title = ('Overlap clip' if len(overview) > 3 else
                             "Earlier clip" if i == 0 else "Later clip" if i == len(panes) - 1 else "Middle clip")
                elif single_title:
                    title = single_title
                heading.configure(text=(f'Clip {first+i+1} · '+title if full_timeline else title), foreground=CLIP_COLORS[(first + i) % len(CLIP_COLORS)] if full_timeline else
                                  COVERAGE_COLORS[i - 1] if coverage and i else "")
                name.configure(text=panes[i].path.name, width=20 if len(panes) == 4 else 28)
                tracks.configure(width=14 if len(panes) == 4 else 19)
                note = self.card_notes[i]
                note.pack_forget()
                if full_timeline and panes[i].note:
                    note.configure(text=panes[i].note)
                    note.pack(anchor="w", before=surface, pady=(0, 3))
                position.set("")
        try:
            self.engine(len(panes))
            self.prime(initial_position if initial_position is not None else
                       min(p.start for p in panes) if full_timeline else self.jump_position(), resume)
        except (OSError, ValueError, AttributeError) as error:
            self.reset(str(error))

    def engine(self, count):
        if not self.vlc:
            folder = self.folder_for_vlc()
            if not folder:
                raise ValueError("Choose the bundled libmpv-2.dll under Playback settings.")
            self.vlc = Vlc(Path(folder));self.vlc.audio_device=self.audio_device
        while len(self.players) < count:
            self.players.append(Player(self.vlc, self.cards[len(self.players)][3]))

    def active(self):
        return self.players[:len(self.panes)]

    def reset(self, message="Select a clip to review."):
        self.scrubbing=False
        self.close_scrub_audio()
        self.source_fps=[]
        self.alignment_spinner.stop()
        for player in self.players:
            player.clear()
        self.panes = []
        self.running.clear()
        self.joining.clear()
        self.playing = False
        self.priming = self.pending = None
        self.retained = None
        self.full_timeline = False
        self.single_title = None
        self.overview = ()
        self.timeline.open_lane = None
        self.clock_index = 0
        self.enable(False)
        self.info.set(message)
        self.range_label.set("")
        self.sync_label.set("")
        self.play_button.configure(text="Play")
        self.timeline.dragging = False
        self.timeline.set_bands(())
        self.timeline.update_position(0, 0)
        for card, _, _, _, _, _ in self.cards:
            card.grid_remove()
        self.empty.place(relx=.5, rely=.5, anchor="center")

    def prime(self, position, resume):
        self.playing = False
        self.running.clear()
        self.joining.clear()
        self.pending = None
        self.priming = (position, resume, time.monotonic())
        self.warming = {}
        self.unavailable.clear()
        self.track_options = [[] for _ in self.panes]
        self.enable(False)
        for i in range(len(self.panes)):
            self.open_pane(i)

    def open_pane(self, index):
        try:
            self.players[index].open(self.panes[index].path)
        except (OSError, ValueError):
            if index == 0:
                raise
            self.unavailable.add(index)

    def bounds(self, index):
        pane = self.panes[index]
        start = max(0, pane.start, -pane.offset)
        end = min(pane.end, self.durations[index] - pane.offset)
        if not self.full_timeline:
            end = min(self.durations[0], end)
        return start, max(start, end)

    def matching(self, position):
        sides = set() if self.full_timeline else {0}
        for i in range(0 if self.full_timeline else 1, len(self.panes)):
            start, end = self.bounds(i)
            if start - .004 <= position < end - .035:
                sides.add(i)
        return sides

    def timeline_duration(self):
        if self.overview:
            return max(end for _, end, _ in self.overview)
        return max(p.end for p in self.panes) if self.full_timeline else self.durations[0]

    def timeline_position(self, index, local):
        return local - self.panes[index].offset if self.full_timeline else local

    def mapped(self, i, position):
        start, end = self.bounds(i)
        mapped = min(end, max(start, position)) + self.panes[i].offset
        return max(0, min(self.durations[i] - .02, mapped))

    def jump_position(self):
        if self.full_timeline:
            return next((p.start for p in self.panes[1:] if len(self.matching(p.start + .01)) > 1),
                        self.panes[0].start)
        if self.retained and any(p.role == "trimmed" for p in self.panes):
            return self.retained[0]
        return min((self.bounds(i)[0] for i in range(1, len(self.panes))), default=0)

    def jump(self):
        self.seek(self.jump_position())

    def scrub_options(self):
        return self.app.scrub_options() if self.app else dict(video=True,audio=False,stop=False,interval=.04,grain=.1)

    def scrub_event(self,phase,position):
        if not self.panes or self.priming:return
        if phase=='begin':
            self.scrub_resume=(self.pending[1] if self.pending else self.playing) and not self.scrub_options()['stop']
            self.pending=None;self.hold();self.scrubbing=True
            self.scrub_target=position;self.scrub_sent=None;self.scrub_until=0.
        elif phase=='move' and self.scrubbing:self.scrub_target=position
        elif phase in ('end','cancel') and self.scrubbing:
            resume=self.scrub_resume
            self.stop_scrub_audio()
            self.scrubbing=False;self.scrub_target=None;self.hold()
            if phase=='end':
                self.seek(position,resume=resume)

    def set_audio_device(self,device):
        self.audio_device=device
        if self.vlc:self.vlc.audio_device=device
        for player in self.players:player.engine.set('audio-device',device)
        for preview in self.scrub_previews.values():preview.set_audio_device(device)

    def stop_scrub_audio(self):
        for preview in self.scrub_previews.values():preview.stop()

    def close_scrub_audio(self):
        for preview in self.scrub_previews.values():preview.close()
        self.scrub_previews.clear()

    def update_scrub_audio(self,target,options):
        from review_scrub_audio import ScrubAudio
        from review_player import audio_graphs
        audible=[i for i,p in enumerate(self.active()) if i in self.matching(target) and self.audible(i) and p.audio]
        for i,player in enumerate(self.active()):
            if not options['audio'] or i not in audible:
                if i in self.scrub_previews:self.scrub_previews[i].stop()
                continue
            tracks=self.track_options[i]
            chosen=tracks[min(self.audio_choices[self.track_key(i)],len(tracks)-1)][0] if tracks else -1
            if chosen==10001:
                mix=self.vlc.review_mix or [{'enabled':j==0,'volume':100} for j in range(len(player.audio))]
                mix=[dict(mix[j]) if j<len(mix) else dict(enabled=False,volume=100) for j in range(len(player.audio))]
            else:mix=[dict(enabled=t['id']==chosen,volume=100) for t in player.audio]
            if i not in self.scrub_previews:
                self.scrub_previews[i]=ScrubAudio(self.vlc.library,player.path,len(player.audio),audio_graphs,self.audio_device)
            self.scrub_previews[i].submit(self.mapped(i,target),mix,options['grain'],False,self.volume/max(1,len(audible))**(1/3))

    def update_scrub(self):
        # Video follows the latest mouse position; independent sound fragments
        # can finish even when another video seek supersedes the previous one.
        now=time.monotonic();options=self.scrub_options();players=self.active()
        target=self.scrub_target
        if target is None:return
        self.update_scrub_audio(target,options)
        if not options['video']:return
        sent=self.scrub_sent
        settled=sent is not None and all(not p.engine.get('seeking',False) for p in players)
        if sent is None or target!=sent[0] and now-sent[1]>=max(.016,options['interval']) and (settled or now-sent[1]>.25):
            for i,player in enumerate(players):
                player.set_muted(True);player.pause(True);player.seek(self.mapped(i,target))
            self.scrub_sent=(target,now)

    def apply_palette(self,palette):
        self.timeline.configure(bg=palette['panel'])
        self.timeline.palette=palette
        self.timeline.draw()
        for _,_,_,surface,_,_ in self.cards:surface.configure(bg=palette['video_background'])
        for player in self.players:player.set_background(palette['video_background'])
        if self.transport:self.transport.set_palette(palette)

    def seek(self, position, *, resume=None):
        if self.app:self.app.wake_updates()
        if self.panes and not self.priming:
            if self.overview and not self.matching(min(position, self.timeline_duration() - .04)) and self.open_hidden:
                if self.open_hidden(position):
                    return
            if resume is None:
                resume = self.pending[1] if self.pending else self.playing
            self.align(position, resume)

    def hold(self):
        self.playing = False
        self.running.clear()
        self.joining.clear()
        for player in self.active():
            player.set_muted(True)
            player.pause(True)
            player.set_rate(self.rate)

    def align(self, position, resume):
        if self.full_timeline:
            position = min(position, self.timeline_duration() - .04)
            available = self.matching(position)
            if not available:
                self.clock_index = min(range(len(self.panes)), key=lambda i: abs(self.panes[i].start - position))
                position = self.panes[self.clock_index].start
            else:
                self.clock_index = min(available)
        else:
            position = self.mapped(0, position)
        if self.players[self.clock_index].state() in (5, 6, 7):
            self.prime(position, resume)
            return
        self.hold()
        targets = [self.mapped(i, position) for i in range(len(self.panes))]
        self.pending = (targets, resume, time.monotonic())
        self.seek_retry = False
        for player, target in zip(self.active(), targets):
            if player.state() in (3, 4):
                player.seek(target)
        self.sync_label.set("Seeking…" if self.full_timeline or self.single_title else "Seeking original…")
        self.draw(targets)

    def toggle(self):
        if self.app:self.app.wake_updates()
        if not self.panes or self.priming:
            return
        if self.scrubbing:
            self.scrub_resume = not self.scrub_resume
            self.play_button.configure(text="Pause" if self.scrub_resume else "Play")
        elif self.pending:
            targets, resume, issued = self.pending
            self.pending = targets, not resume, issued
            if resume:
                for player in self.active():player.pause(True)
            self.play_button.configure(text="Pause" if not resume else "Play")
        elif self.playing:
            self.hold()
            self.play_button.configure(text="Play")
            self.sync_label.set("")
        else:
            player = self.players[self.clock_index]
            position = self.timeline_position(self.clock_index, max(0, player.time()))
            if player.state() in (3, 4):
                self.resume(position, time.monotonic())
            else:
                restart = 0 if self.full_timeline else self.jump_position()
                self.align(restart if player.state() == 6 else position, True)
                self.play_button.configure(text="Pause")

    def set_speed(self,rate):
        self.rate=rate
        for player in self.active():player.set_rate(rate)

    def step_frame(self,direction):
        if not self.panes or self.priming:return
        player=self.players[self.clock_index]
        fps=float(player.engine.get('container-fps') or player.engine.get('estimated-vf-fps') or 30)
        position=self.timeline.time if self.pending else self.timeline_position(self.clock_index,player.time())
        self.align(max(0,position+direction/fps),False)

    def resume(self, position, now):
        self.running = {self.clock_index}
        self.playing = True
        for player in self.active():player.set_rate(self.rate)
        self.errors = [0.0] * len(self.panes)
        self.drift_since = [None] * len(self.panes)
        self.last_resync = [now] * len(self.panes)
        self.master_start = self.players[self.clock_index].time()
        self.master_started = False
        nearby = self.matching(position) - {self.clock_index}
        for index in nearby:
            player = self.players[index]
            local = player.time()
            if player.state() == 4 and not player.engine.get('seeking',False) and abs(local - self.mapped(index, position)) <= .075:
                self.running.add(index)
        self.apply_audio()
        self.players[self.clock_index].pause(False)
        for index in sorted(nearby & self.running):
            self.players[index].pause(False)
        for index in nearby - self.running:
            self.join_support(index, position, now)
        self.play_button.configure(text="Pause")

    def join_support(self, index, position, now):
        player = self.players[index]
        state = player.state()
        last, target = self.joining.get(index, (None, None))
        if index in self.unavailable or state == 7:
            return
        if state in (5, 6):
            if last is None or now - last >= .5:
                self.joining[index] = (now, None)
                self.open_pane(index)
            return
        if state not in (3, 4):
            return
        desired = self.mapped(index, position)
        advanced = target is not None and player.time() >= target + .065
        elapsed = now - last if last is not None else 0.0
        # Running VLC time samples are coarse. Give a pane time to settle
        # before treating a single discrepant clock report as a failed seek.
        tolerance = .075 if elapsed < .45 else .20
        if (advanced and self.master_started and state == 3 and now - last >= .10
                and abs(player.clock_time(now, True) - desired) <= tolerance):
            self.running.add(index)
            self.joining.pop(index, None)
            self.errors[index] = 0.0
            self.drift_since[index] = None
            self.last_resync[index] = now
        elif target is None or elapsed >= (.80 if advanced and self.master_started else 1.75):
            # A paused seek can report the requested time before the decoder
            # starts there. Confirm a running clock before routing its audio.
            player.set_muted(True)
            if state == 4:
                player.pause(False)
            target = self.mapped(index, position + .04)
            player.seek(target)
            self.joining[index] = (now, target)

    def correct(self, positions, position, now):
        if not self.master_started and self.players[self.clock_index].time() >= self.master_start + .065:
            self.master_started = True
        needed = self.matching(position) | {self.clock_index}
        for i in (self.running | self.joining.keys()) - needed:
            self.players[i].set_muted(True)
            self.players[i].pause(True)
            self.players[i].set_rate(self.rate)
            self.running.discard(i)
            self.joining.pop(i, None)
        for i in (self.running & needed) - {self.clock_index}:
            if self.players[i].state() in (5, 6, 7):
                self.running.discard(i)
        for i in (self.running & needed) - {self.clock_index}:
            error = positions[i] - self.mapped(i, position)
            self.errors[i] += .18 * (error - self.errors[i])
            filtered = self.errors[i]
            # Correct small mpv clock drift gently, instead of repeatedly
            # stopping, muting and seeking a pane that is only a few frames off.
            correction=max(-.08,min(.08,-filtered*.5))
            self.players[i].set_rate(self.rate*(1+correction) if abs(filtered)>.012 else self.rate)
            if abs(filtered) > .35:
                if self.drift_since[i] is None:
                    self.drift_since[i] = now
                elif now - self.drift_since[i] >= .5 and now - self.last_resync[i] > 1.5:
                    self.players[i].set_muted(True)
                    self.players[i].pause(True)
                    self.players[i].set_rate(self.rate)
                    self.running.discard(i)
                    continue
            else:
                self.drift_since[i] = None
        for i in needed - self.running:
            self.join_support(i, position, now)
        if len(needed) == 1:
            self.sync_label.set("" if self.single_title else
                                "One clip here" if self.full_timeline else "Original playback · no overlap here")
        elif needed <= self.running:
            self.sync_label.set("Linked playback")
        elif any(i in self.unavailable or self.players[i].state() == 7 for i in needed - {self.clock_index}):
            self.sync_label.set("Supporting preview unavailable")
        else:
            self.sync_label.set("Linking supporting preview…")

    def update_audio_menu(self, coverage):
        if self.single_title:
            self.audio_box.configure(values=(self.single_title, "Muted"))
            self.audio_side.set("Muted" if self.audio_mode == "Muted" else self.single_title)
            return
        files=self.audio_files or tuple(pane.path for pane in self.panes);first=0 if self.audio_files else self.audio_first
        labels=tuple(f'Clip {first+i+1} · {path.name}' for i,path in enumerate(files))
        self.audio_menu_modes=[f'Clip:{first+i}' for i in range(len(files))]+['Both','Muted']
        labels+=('All' if max(len(files),len(self.overview))>2 else 'Both','Muted')
        self.audio_box.configure(values=labels)
        mode={'Original':'Clip:0','Trimmed':'Clip:1'}.get(self.audio_mode,self.audio_mode)
        if mode not in self.audio_menu_modes:mode='Both'
        if mode.startswith('Clip:') and not self.audio_first<=int(mode[5:])<self.audio_first+len(self.panes):mode='Both'
        self.audio_mode=mode;self.audio_side.set(labels[self.audio_menu_modes.index(mode)])

    def audio_changed(self, event=None):
        if self.single_title:
            self.audio_mode = "Muted" if self.audio_side.get() == "Muted" else "Original"
        else:
            self.audio_mode = self.audio_menu_modes[tuple(self.audio_box.cget("values")).index(self.audio_side.get())]
            if self.audio_mode.startswith('Clip:') and self.open_hidden:
                chosen=int(self.audio_mode[5:])
                if not self.audio_first<=chosen<self.audio_first+len(self.panes):
                    position=self.timeline.time
                    if chosen<len(self.overview):
                        a,b,_=self.overview[chosen];position=max(a,min(position,b-.04))
                    self.open_hidden(position,chosen)
        self.refresh_tracks()
        self.settings_changed()

    def audible(self, i):
        if self.single_title:
            return self.audio_mode != "Muted"
        return self.audio_mode=='Both' or self.audio_mode==f'Clip:{self.audio_first+i}' or (self.audio_mode=='Original' and i==0) or (self.audio_mode=='Trimmed' and i==1)

    def set_volume(self, percent):
        self.volume = max(0, min(100, percent))
        self.volume_position.set(self.volume)
        self.volume_label.set(f"{self.volume}%")
        if not self.priming:
            self.apply_audio()

    def volume_changed(self, value):
        percent = round(float(value))
        if percent != self.volume:
            self.set_volume(percent)
            self.settings_changed()

    def track_key(self, i):
        role = self.panes[i].role
        occurrence = sum(pane.role == role for pane in self.panes[:i + 1])
        return f"{role}_{occurrence}" if occurrence > 1 else role

    def apply_audio(self):
        audible = []
        for i, player in enumerate(self.active()):
            state = player.state()
            if state not in (3, 4):
                continue
            tracks = self.track_options[i]
            index = min(self.audio_choices[self.track_key(i)], len(tracks) - 1)
            track = tracks[index][0] if self.audible(i) and tracks else -1
            selected = player.selected_track()
            if selected != track:
                player.set_muted(True)
                player.select_track(track)
            if self.playing and i in self.running and track >= 0 and state == 3 and selected == track:
                audible.append(player)
            else:
                player.set_muted(True)
        if audible:
            # mpv's volume is cubic: divide amplitude, not the volume knob.
            # Two identical aligned sources at this gain sum to the solo level.
            level = self.volume / len(audible)**(1/3)
            for player in audible:
                player.set_volume(level)
            for player in audible:
                player.set_muted(False)

    def refresh_tracks(self):
        for i, player in enumerate(self.active()):
            if tracks := player.tracks():
                self.track_options[i] = tracks
            tracks = self.track_options[i]
            box = self.cards[i][5]
            box.configure(values=[f"{j + 1} · {name}" for j, (_, name) in enumerate(tracks)],
                          state="readonly" if tracks and self.audible(i) else "disabled")
            if tracks:
                box.current(min(self.audio_choices[self.track_key(i)], len(tracks) - 1))
            else:
                box.set("")
        self.apply_audio()

    def choose_track(self, i):
        if i < len(self.panes) and 0 <= (selection := self.cards[i][5].current()) < len(self.track_options[i]):
            self.audio_choices[self.track_key(i)] = selection
            self.apply_audio()
            self.settings_changed()

    def draw(self, positions, timeline_position=None):
        original = (self.timeline_position(self.clock_index, positions[self.clock_index])
                    if timeline_position is None else timeline_position)
        bands, labels = [], []
        for i, pane in enumerate(self.panes):
            from review_timecode import fps_text
            fps=self.source_fps[i] if i<len(self.source_fps) else 0
            text = f"{timestamp(positions[i])} / {timestamp(self.durations[i])}"+(' · '+fps_text(fps)+' fps' if fps else '')
            if self.full_timeline:
                start, end = self.bounds(i)
                bands.append((start, end, CLIP_COLORS[i]))
                label = (f"#{self.overview_first + i + 1}" if len(self.overview) > 3 else
                         "Earlier" if i == 0 else "Later" if i == len(self.panes) - 1 else "Middle")
                labels.append(f"{label} {timestamp(start)}–{timestamp(end)}")
                if not start - .004 <= original <= end:
                    text += "  ·  Outside clip"
            elif i:
                start, end = self.bounds(i)
                if pane.role != "trimmed":
                    bands.append((start, end, COVERAGE_COLORS[i - 1]))
                    labels.append(f"{'Earlier' if pane.role == 'earlier' else 'Later' if pane.role == 'later' else 'Match'} "
                                  f"{timestamp(start)}–{timestamp(end)}")
                if not start - .004 <= original <= end:
                    text += "  ·  Outside match"
            self.cards[i][4].set(text)
        if self.retained:
            labels.append(f"Kept {timestamp(self.retained[0])}–{timestamp(self.retained[1])}")
        self.timeline.set_bands(self.overview or tuple(bands))
        self.timeline.update_position(self.timeline_duration(), original, self.retained)
        self.range_label.set("   •   ".join(labels))
        if self.transport:
            self.time_label.set(self.app.format_time(original)+' / '+self.app.format_time(self.timeline_duration()))
            from review_timecode import fps_text
            rates=list(dict.fromkeys(fps_text(fps) if fps else '—' for fps in self.source_fps))
            self.fps_label.set('Video Framerate: '+(' / '.join(rates)+' fps' if rates else '—'))

    def tick(self):
        try:
            if self.panes:
                if self.scrubbing:self.update_scrub()
                else:self.update_players()
            if self.transport:
                paused=not (self.scrub_resume if self.scrubbing else self.pending[1] if self.pending else self.playing)
                if paused!=self.transport.paused:self.transport.set_paused(paused)
            callback=getattr(self,'on_ready',None)
            if callback and not self.priming and not self.pending:self.on_ready=None;callback()
        except (ValueError, OSError) as error:
            self.reset(str(error))
        finally:
            if self.app is None:
                from review_activity import update_interval
                from review_windows import in_foreground
                window = self.winfo_toplevel()
                delay = update_interval(visible=bool(self.winfo_viewable()), foreground=in_foreground((window,)),
                                        realtime=self.needs_realtime_updates(), paused_player=bool(self.panes), frame_ms=POLL_MS)
                self.timer = self.after(delay, self.tick)

    def needs_realtime_updates(self):
        return bool(self.playing or self.scrubbing or self.priming or self.pending or self.joining)

    def update_players(self):
        now = time.monotonic()
        players = self.active()
        states = [p.state() for p in players]
        if states[self.clock_index] == 7 or self.priming and now - self.priming[2] > 15:
            name = "merged video" if self.single_title else "original"
            self.reset(f"The player could not prepare the {name}. You can open the file externally.")
            return
        if len(self.source_fps)!=len(players):self.source_fps=[0.]*len(players)
        for i,p in enumerate(players):
            if not self.source_fps[i]:self.source_fps[i]=float(p.engine.get('container-fps') or p.engine.get('estimated-vf-fps') or 0)
        for i, player in enumerate(players):
            if (length := player.duration()) > 0:
                self.durations[i] = length
        if self.priming:
            for i, player in enumerate(players):
                if i not in self.warming and states[i] == 4 and self.durations[i] > 0:
                    self.track_options[i] = player.tracks()
                    player.set_muted(True)
                    player.show_paused_frame()
                    self.warming[i] = now
            if (self.clock_index in self.warming and now - self.warming[self.clock_index] >= .25
                    and (all(p.has_video() for p in players) or now - self.warming[self.clock_index] >= .75)):
                position, resume, _ = self.priming
                self.priming = None
                self.hold()
                self.enable(True)
                self.refresh_tracks()
                self.align(position, resume)
            return
        self.apply_audio()
        if self.pending:
            targets, resume, issued = self.pending
            times = [player.time() for player in players]
            # The original is the master. Neither parked nor active supporting
            # panes can hold its seek or playback hostage.
            master = self.clock_index
            ready = states[master] in (3, 4) and not players[master].engine.get('seeking',False) and abs(times[master] - targets[master]) <= .075
            needed=self.matching(self.timeline_position(master,targets[master]))
            supports_ready=all(states[i] in (3,4) and not players[i].engine.get('seeking',False) and abs(times[i]-targets[i])<=.075 for i in needed)
            ready=ready and (supports_ready or now-issued>1.5)
            if ready and now - issued >= .12:
                self.pending = None
                self.sync_label.set("")
                if resume:
                    self.resume(self.timeline_position(master, times[master]), now)
                else:
                    if self.seek_retry:
                        players[master].pause(True)
                    for player, state in zip(players, states):
                        if state == 4:
                            player.show_paused_frame()
            elif (self.full_timeline or self.single_title) and not self.seek_retry and now - issued >= .45 and states[master] == 4:
                self.seek_retry = True
                players[master].set_muted(True)
                players[master].seek(targets[master])
            elif now - issued > (6 if self.seek_retry else 2):
                self.hold()
                self.pending = None
                self.play_button.configure(text="Play")
                self.sync_label.set("The player could not seek to this point.")
                self.draw(times)
                return
            self.draw(targets)
            return
        positions = [p.clock_time(now, i in self.running or i in self.joining) for i, p in enumerate(players)]
        if states[self.clock_index] == 6:
            end = self.bounds(self.clock_index)[1]
            if self.full_timeline and self.playing:
                following = self.matching(end) - {self.clock_index}
                ready = following & self.running
                if ready:
                    self.running.discard(self.clock_index)
                    self.clock_index = min(ready)
                    players[self.clock_index].set_rate(self.rate)
                elif following:
                    self.align(end, True)
                    return
                elif self.overview and self.open_hidden and self.open_hidden(end + .04):
                    return
                else:
                    self.hold()
            else:
                self.hold()
            if not self.playing:
                self.play_button.configure(text="Play")
                self.sync_label.set("")
                self.draw(positions, end)
                return
        if self.playing:
            self.correct(positions, self.timeline_position(self.clock_index, positions[self.clock_index]), now)
        if self.pending is None:
            self.draw(positions)

    def close(self):
        self.close_scrub_audio()
        self.alignment_spinner.stop()
        if self.timer is not None:
            self.after_cancel(self.timer)
        for player in self.players:
            player.close()
        if self.vlc:
            self.vlc.close()
