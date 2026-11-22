# SPDX-License-Identifier: GPL-3.0-or-later
"""Live post-mix peak display, using the existing mpv audio filter only.

No second decoder, media reads, temporary audio, or disk logging. Disabled meters
remove their filter; active meters sample metadata at 25 Hz with visual decay.
"""
import math,time
import tkinter as tk

FILTER='@level_meter:lavfi=[astats=metadata=1:reset=1:measure_perchannel=Peak_level:measure_overall=Peak_level]'


def peak(data,volume=100):
    try:db=float((data or {}).get('lavfi.astats.Overall.Peak_level','-inf'))
    except (TypeError,ValueError):return 0.
    return 10**(db/20)*(volume/100)**3 if math.isfinite(db) else 0.


class LevelMeter(tk.Canvas):
    def __init__(self,parent,app):
        super().__init__(parent,width=46,height=136,highlightthickness=0)
        self.app=app;self.engines=set();self.checked={};self.last=0.;self.level=-60.;self.paint_key=None
        self.set_palette(app.palette)
    def set_palette(self,colors):self.colors=colors;self.configure(bg=colors['panel']);self.paint_key=None;self.draw()
    def remove(self,engine):
        if getattr(engine,'handle',None):
            try:engine.command('af','remove','@level_meter',asynchronous=True,request=1<<61)
            except RuntimeError:pass
        self.engines.discard(engine);self.checked.pop(engine,None)
    def sources(self):
        app=self.app;compare=app.cleanup.compare if app.cleanup.mode=='compare' else None
        if compare:return [(p.engine,compare.playing and i in compare.running) for i,p in enumerate(compare.active()) if p.ready]
        mixer=app.mixer
        return [(mixer.engine,not mixer.paused)] if mixer and mixer.active and mixer.ready else []
    def tick(self):
        now=time.monotonic()
        if now-self.last<.04:return
        elapsed=min(.2,now-self.last);self.last=now
        enabled=self.app.settings.data.getboolean('app','volume_meter')
        sources=self.sources() if enabled else [];current={engine for engine,_ in sources}
        for engine in self.engines-current:self.remove(engine)
        amplitude=0.
        for engine,playing in sources:
            try:
                if engine not in self.engines or self.checked.get(engine)!=engine.af_revision:
                    filters=engine.get('af') or []
                    if not any(f.get('label')=='level_meter' for f in filters):engine.command('af','add',FILTER,asynchronous=True,request=1<<61)
                    self.engines.add(engine);self.checked[engine]=engine.af_revision
                data=engine.request_property('af-metadata/level_meter') if playing else None
                if playing and not engine.read_values.get('mute',True) and not engine.read_values.get('seeking',False):
                    amplitude+=peak(data,float(engine.read_values.get('volume',100)))
            except (RuntimeError,ValueError):pass
        db=max(-60,min(0,20*math.log10(amplitude))) if amplitude>0 else -60.
        self.level=max(db,self.level-36*elapsed) if enabled else -60.
        self.draw()
    def draw(self):
        scale=getattr(self._root(),'review_scale',1)
        key=(round(self.level),self.winfo_height(),scale,tuple(self.colors.items()))
        if key==self.paint_key:return
        self.paint_key=key;self.delete('all');height=max(120,self.winfo_height()/scale);bottom=height-15
        self.create_rectangle(23,6,39,bottom,fill=self.colors['input'],outline=self.colors['border'])
        for db in (0,-12,-24,-36,-48,-60):
            y=6+(-db/60)*(bottom-6)
            self.create_text(19,y,text=str(db),anchor='e',fill=self.colors['muted_text'],font=('Segoe UI',7))
        if self.level>-60:
            top=bottom-(self.level+60)/60*(bottom-7)
            self.create_rectangle(24,top,38,bottom-1,fill=self.colors['level_meter'],outline='')
        if scale!=1:self.scale('all',0,0,scale,scale)
    def close(self):
        for engine in tuple(self.engines):self.remove(engine)
