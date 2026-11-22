# SPDX-License-Identifier: GPL-3.0-or-later
"""mpv playback clients for the original overlap comparison interface."""
import time
from pathlib import Path
import tkinter as tk
from mpv_native import Mpv
from review_player import audio_graphs
from review_cleanup_theme import ACCENT, ACCENT_DARK, BORDER, PANEL

AUDIO_MODES = ("Original", "Trimmed", "Both", "Muted")
POLL_MS = 16


class Vlc:
    """Compatibility context: uses libmpv only; does not load VLC."""
    def __init__(self, folder):
        self.library=Path(folder)
        if self.library.is_dir():self.library/= 'libmpv-2.dll'
        self.review_mix=None
        self.hwdec='auto';self.audio_device='auto'
    def close(self):pass


class Player:
    def __init__(self, context, frame):
        self.context=context
        self.engine=Mpv(context.library, {
            'config':'no','load-scripts':'no','osc':'no','osd-level':'0',
            'input-default-bindings':'no','input-vo-keyboard':'no','input-builtin-dragging':'no',
            'wid':str(frame.winfo_id()),'vo':'gpu-next','gpu-api':'d3d11','gpu-context':'d3d11',
            'target-colorspace-hint':'auto','tone-mapping':'auto','d3d11-output-format':'auto',
            'hwdec':context.hwdec,'hwdec-codecs':'all','hwdec-software-fallback':'yes',
            'keep-open':'yes','idle':'yes','pause':'yes','hr-seek':'yes',
            'background':'color','border-background':'color','background-color':getattr(frame._root(),'review_palette',{}).get('video_background','#090b10'),
            'audio-device':context.audio_device,'audio-pitch-correction':'yes','audio-channels':'stereo','mute':'yes',
            'demuxer-max-bytes':str(64*1024*1024),'demuxer-max-back-bytes':str(32*1024*1024)})
        self.path=None;self.ready=False;self.failed=False;self.closed=False
        self.rate=1.;self.audio=[];self.track=1;self._muted=True;self._volume=100
        self.seek_target=None;self.seek_at=0.;self.seek_restarted=False;self.preroll=0.
    def poll(self):
        for event,error,request,data in self.engine.events():
            if event==8:self.ready=True
            if event==7 and error<0:self.failed=True
            if event==21:self.seek_restarted=True
        if self.ready:
            tracks=self.engine.get('track-list') or []
            self.audio=[t for t in tracks if t.get('type')=='audio']
            if self.seek_target is not None and not self.engine.get('seeking',False) and (self.seek_restarted or time.monotonic()-self.seek_at>.2):
                position=float(self.engine.get('time-pos') or 0)
                if position>self.seek_target+.1 and self.preroll and self.preroll<60:
                    # Long-GOP transport streams may need more than five seconds
                    # of preroll. Retry while PAUSED rather than running silently
                    # for several seconds past a target we never reached.
                    self.preroll=min(60,max(15,self.preroll*2))
                    self.engine.set('hr-seek-demuxer-offset',self.preroll)
                    self._seek(self.seek_target)
                elif abs(position-self.seek_target)<=.1:self.seek_target=None
    def open(self,path):
        self.clear();self.path=Path(path);self.track=1;self._muted=True;self.failed=False
        # Unindexed transport streams can otherwise land on the NEXT keyframe.
        self.preroll=5 if self.path.suffix.lower() in ('.ts','.mts','.m2ts') else 0
        self.engine.set('hr-seek-demuxer-offset',self.preroll)
        self.engine.set('pause',True);self.engine.set('mute',True)
        self.engine.command('loadfile',str(path),'replace')
    def clear(self):
        if self.closed:return
        self.engine.set('mute',True);self.engine.command('stop')
        self.path=None;self.ready=False;self.audio=[]
        self.seek_target=None
    def close(self):
        if not self.closed:
            self.clear();self.engine.close();self.closed=True
    def state(self):
        self.poll()
        if self.failed:return 7
        if not self.path:return 0
        if not self.ready:return 1
        if self.engine.get('eof-reached'):return 6
        return 4 if self.engine.get('pause') else 3
    def time(self):
        self.poll();return float(self.engine.get('time-pos') or 0)
    def duration(self):return float(self.engine.get('duration') or 0)
    def has_video(self):return self.ready and bool(self.engine.get('video-params'))
    def seek(self,seconds):self._seek(max(0,seconds))
    def _seek(self,seconds):
        self.seek_target=seconds;self.seek_at=time.monotonic();self.seek_restarted=False
        self.engine.command('seek',seconds,'absolute+exact',asynchronous=True)
    def pause(self,paused):self.engine.set('pause',bool(paused))
    def set_background(self,color):self.engine.set('background-color',color)
    def show_paused_frame(self):pass
    def set_rate(self,rate):
        rate=min(8,max(.1,round(rate,3)))
        if abs(rate-self.rate)<.002:return
        self.rate=rate;self.engine.set('speed',rate)
    def clock_time(self,now,running):return self.time()
    def tracks(self):
        self.poll()
        values=[(int(t['id']),t.get('title') or f'Track {i+1}') for i,t in enumerate(self.audio)]
        return [(10001,'Review mixer')] + values if values else []
    def selected_track(self):return self.track
    def select_track(self,track):
        if track==self.track:return True
        if track==10001 and self.audio:
            mix=self.context.review_mix or [{'enabled':i==0,'volume':100} for i in range(len(self.audio))]
            mix=[mix[i] if i<len(mix) else {'enabled':False,'volume':100} for i in range(len(self.audio))]
            complex_,af=audio_graphs(len(self.audio),mix)
            self.engine.set('lavfi-complex',complex_);self.engine.set('af',af)
        else:
            self.engine.set('af','');self.engine.set('lavfi-complex','')
            self.engine.set('aid',track if track>=0 else 'no')
        self.track=track;return True
    def set_volume(self,percent):
        if percent!=self._volume:self.engine.set('volume',percent);self._volume=percent
    def set_muted(self,muted):
        if muted!=self._muted:self.engine.set('mute',bool(muted));self._muted=muted


def timestamp(seconds):
    minutes, seconds = divmod(max(0, seconds), 60)
    return f"{int(minutes):02}:{seconds:05.2f}"


class Timeline(tk.Canvas):
    def __init__(self, parent, seek):
        super().__init__(parent, height=30, background=PANEL, highlightthickness=0, takefocus=True)
        self.palette=dict(getattr(self._root(),"review_palette",{}))
        self.duration = 0
        self.time = 0
        self.markers = None
        self.seek = seek
        self.dragging = False
        self.scrub = None
        self.bind("<Configure>", lambda event: self.draw())
        self.bind("<Button-1>", self.clicked)
        self.bind("<ButtonRelease-1>", self.released)
        self.bind("<B1-Motion>", self.dragged)
        self.bind("<Left>", lambda event: self.seek(max(0, self.time - 1)))
        self.bind("<Right>", lambda event: self.seek(min(self.duration, self.time + 1)))

    def draw(self):
        self.delete("all")
        width = max(18, self.winfo_width())
        x = lambda seconds: 8 + min(1, max(0, seconds / self.duration)) * (width - 16)
        self.create_line(8, 15, width - 8, 15, fill=self.palette.get("border",BORDER), width=5, capstyle="round")
        if self.duration <= 0:
            return
        start, end = self.markers or (0, self.duration)
        self.create_line(x(start), 15, x(end), 15, fill=self.palette.get("selection_fill",ACCENT_DARK), width=7, capstyle="round")
        if self.markers:
            for point in (start, end):
                self.create_line(x(point), 5, x(point), 25, fill=self.palette.get("selection",ACCENT), width=2)
        position = x(self.time)
        self.create_oval(position - 5, 10, position + 5, 20, fill=self.palette.get("playhead",ACCENT), outline="")

    def update_position(self, duration, position, markers=None):
        if self.dragging:
            return
        if (duration, position, markers) != (self.duration, self.time, self.markers):
            self.duration, self.time, self.markers = duration, position, markers
            self.draw()

    def clicked(self, event):
        self.focus_set()
        self.dragging = bool(self.duration)
        if self.dragging and self.scrub:self.scrub('begin',self.position_at(event))
        self.dragged(event)

    @property
    def scrubbing(self):return self.dragging

    def begin_scrub(self,x):
        if not self.duration:return False
        self.focus_set();self.dragging=True
        self.time=self.position_at(type('Point',(),{'x':x})())
        if self.scrub:self.scrub('begin',self.time)
        self.draw();return True

    def move_scrub(self,x):
        if self.dragging:
            self.time=self.position_at(type('Point',(),{'x':x})())
            if self.scrub:self.scrub('move',self.time)
            self.draw()

    def end_scrub(self,x=None):
        if not self.dragging:return
        if x is not None:self.move_scrub(x)
        self.dragging=False
        if self.scrub:self.scrub('end',self.time)
        else:self.seek(self.time)

    def cancel_interaction(self):
        if self.dragging and self.scrub:self.scrub('cancel',self.time)
        self.dragging=False

    def position_at(self, event):
        return self.duration * min(1, max(0, (event.x - 8) / max(1, self.winfo_width() - 16)))

    def dragged(self, event):
        if self.duration:
            self.time = self.position_at(event)
            self.draw()
            if self.dragging and self.scrub:self.scrub('move',self.time)

    def released(self, event):
        self.dragging = False
        if self.duration:
            if self.scrub:self.scrub('end',self.position_at(event))
            else:self.seek(self.position_at(event))
