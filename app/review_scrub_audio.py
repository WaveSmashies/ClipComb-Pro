# SPDX-License-Identifier: GPL-3.0-or-later
"""Best-effort sound fragments; never hold up the main video preview clock."""
import threading
import time
from mpv_native import Mpv


class ScrubAudio:
    def __init__(self,library,path,count,graphs,audio_device='auto'):
        self.audio_device=audio_device
        self.library,self.path,self.count,self.graphs=library,str(path),count,graphs
        self.lock,self.wake=threading.Lock(),threading.Event()
        self.goal,self.closed,self.session=None,False,0
        self.playing,self.fragments,self.error=False,0,None
        self.engine=None
        self.thread=threading.Thread(target=self.run,daemon=True,name='Scrub audio')
        self.thread.start()

    def set_audio_device(self,device):
        self.audio_device=device
        if self.engine:
            with self.engine.lock:
                if self.engine.handle:self.engine.set('audio-device',device)

    def submit(self,target,mix,grain,muted,volume):
        with self.lock:
            self.goal=(self.session,target,[dict(m) for m in mix],grain,muted,volume)
        self.wake.set()

    def stop(self):
        with self.lock:self.goal=None;self.session+=1
        # Immediately silence any in-flight fragment before normal playback.
        if self.engine:
            with self.engine.lock:
                if self.engine.handle:self.engine.set('mute',True);self.engine.set('pause',True)
        self.playing=False
        self.wake.set()

    def run(self):
        engine=None
        try:
            engine=Mpv(self.library,{'config':'no','load-scripts':'no','vid':'no','vo':'null',
                'audio-device':self.audio_device,'audio-display':'no','pause':'yes','mute':'yes','keep-open':'yes','idle':'yes',
                'audio-channels':'stereo','audio-buffer':'0.03','demuxer':'lavf',
                'demuxer-max-bytes':str(32*1024*1024),'demuxer-max-back-bytes':str(16*1024*1024)})
            self.engine=engine
            ready,loaded,last,inflight,until=False,False,None,None,None
            applied=[]
            while not self.closed:
                with self.lock:goal=self.goal
                if not loaded and goal:
                    merge,filters=self.graphs(self.count,goal[2])
                    engine.set('lavfi-complex',merge);engine.set('af',filters);engine.set('aid','no')
                    applied=[min(1.5,max(0,m['volume']/100)) if m['enabled'] else 0 for m in goal[2]]
                    engine.set('start',str(goal[1]));engine.command('loadfile',self.path,asynchronous=True)
                    loaded=True
                restarted=False
                for event,error,serial,data in engine.events():
                    if event==8:ready=True
                    elif event==21:restarted=True
                if restarted and goal:applied=[None]*self.count
                now=time.monotonic()
                if goal is None:
                    if self.playing:engine.set('pause',True);engine.set('mute',True)
                    self.playing=False;inflight=until=last=None
                elif ready:
                    for i,m in enumerate(goal[2]):
                        value=min(1.5,max(0,m['volume']/100)) if m['enabled'] else 0
                        if value!=applied[i]:
                            try:engine.command('af-command','review','volume',str(value),f'volume@track{i}')
                            except RuntimeError:break
                            applied[i]=value
                    token=(goal[0],goal[1])
                    if until is not None and now>=until:
                        engine.set('pause',True);engine.set('mute',True)
                        self.playing=False;until=None
                    if inflight:
                        sent_goal,sent_at=inflight
                        raw=engine.get('time-pos')
                        if not engine.get('seeking',False) and raw is not None and abs(raw-sent_goal[1])<.12 and (restarted or now-sent_at>.15):
                            # A stopped/replaced hold must never start a stale fragment.
                            with self.lock:
                                if self.goal and self.goal[0]==sent_goal[0]:
                                    engine.set('volume',self.goal[5]);engine.set('mute',self.goal[4] or not any(m['enabled'] and m['volume']>0 for m in self.goal[2]))
                                    engine.set('pause',False);self.playing=True;self.fragments+=1
                                    until=now+self.goal[3]
                            inflight=None
                        elif now-sent_at>1:inflight=None;last=None
                    if inflight is None and until is None and token!=last:
                        engine.set('pause',True);engine.set('mute',True)
                        engine.command('seek',f'{goal[1]:.9f}','absolute+exact',asynchronous=True)
                        inflight=(goal,now);last=token
                self.wake.wait(.004 if goal else None);self.wake.clear()
        except Exception:
            import traceback
            self.error=traceback.format_exc()
        finally:
            self.playing=False
            if engine:engine.close()
            self.engine=None

    def close(self):
        self.stop();self.closed=True;self.wake.set()
        self.thread.join(5)
        if self.thread.is_alive():raise RuntimeError('The scrub audio preview is still releasing its clip. Please try saving again.')
