# SPDX-License-Identifier: GPL-3.0-or-later
"""Small, timed logo animations loaded off the UI thread after media is ready."""
import json,threading,time
from queue import Queue,Empty
import tkinter as tk
from PIL import Image,ImageTk
from review_icons import asset_folder

class AnimatedLogo:
    def __init__(self,label,light=False,show=None,hide=None,waiting=False,size=48):
        self.size=size;self.label=label;self.root=label._root();self.light=light;self.show=show or (lambda:None)
        self.base_size=size;self.size=max(16,round(size*getattr(self.root,'review_scale',1)));self.waiting_enabled=waiting;self.load_revision=0
        label.review_animation=self
        self.hide_widget=hide or (lambda:None)
        self.ready=False;self.started=False;self.active=False;self.closed=False;self.token=0;self.timer=None
        self.frames={};self.results=Queue();self.loading=set();self.project_key=None;self.project_serial=0;self.pending=set()
        self.loop_delay=None
        self.animation_pending=set()
        with Image.open(asset_folder()/'animation/blank.png') as blank:self.blank=ImageTk.PhotoImage(blank.convert('RGBA').resize((self.size,self.size),Image.Resampling.LANCZOS),master=self.root)
        self.waiting={}
        for mode in ('dark','light'):
            if waiting:
                with Image.open(asset_folder()/f'animation/{mode}-waiting.png') as picture:self.waiting[mode]=ImageTk.PhotoImage(picture.convert('RGBA').resize((self.size,self.size),Image.Resampling.LANCZOS),master=self.root)
            else:self.waiting[mode]=self.blank
        label.configure(image=self.waiting[self.mode()],cursor='hand2');label.bind('<Button-1>',lambda e:self.clicked())
        self.poll_timer=None
    def after(self,delay,callback,animation=False):
        token=[]
        def run():self.pending.discard(token[0]);self.animation_pending.discard(token[0]);callback()
        token.append(self.root.after(delay,run));self.pending.add(token[0])
        if animation:self.animation_pending.add(token[0])
        return token[0]
    def cancel_animation(self):
        for timer in self.animation_pending:
            try:self.root.after_cancel(timer)
            except tk.TclError:pass
            self.pending.discard(timer)
        self.animation_pending.clear()
    def mode(self):return 'light' if self.light else 'dark'
    def rescale(self,scale):
        size=max(16,round(self.base_size*scale))
        if size==self.size or self.closed:return
        self.cancel_animation();self.token+=1;self.load_revision+=1;self.size=size;self.frames.clear();self.loading.clear()
        with Image.open(asset_folder()/'animation/blank.png') as picture:self.blank=ImageTk.PhotoImage(picture.convert('RGBA').resize((size,size),Image.Resampling.LANCZOS),master=self.root)
        for mode in ('dark','light'):
            if self.waiting_enabled:
                with Image.open(asset_folder()/f'animation/{mode}-waiting.png') as picture:self.waiting[mode]=ImageTk.PhotoImage(picture.convert('RGBA').resize((size,size),Image.Resampling.LANCZOS),master=self.root)
            else:self.waiting[mode]=self.blank
        self.label.configure(image=self.waiting[self.mode()])
        if self.started:self.play(['intro'] if self.active else [])
    def set_light(self,value):
        if self.light==value:return
        self.light=value;self.token+=1
        if self.started:self.play(['intro'] if self.active else [])
        else:self.label.configure(image=self.waiting[self.mode()])
    def hide(self):
        self.cancel_animation()
        self.token+=1;self.project_serial+=1;self.ready=self.started=self.active=False;self.project_key=None;self.loop_delay=None;self.label.configure(image=self.waiting[self.mode()])
    def loop(self,hold_ms=4000):
        self.ready=True;self.loop_delay=hold_ms;self.play(['intro'])
    def project(self,key,condition):
        if self.project_key==key:return
        self.project_key=key;self.ready=True;self.project_serial+=1;ticket=self.project_serial
        def check():
            if self.closed or ticket!=self.project_serial:return
            if not condition():self.after(100,check);return
            def begin():
                if ticket!=self.project_serial or self.closed:return
                if condition():self.play(['intro'])
                else:check()
            self.after(180,begin)
        self.after(60,check)
    def load(self,mode):
        if mode in self.loading or (mode,'hold') in self.frames:return
        self.loading.add(mode)
        output_size=self.size;revision=self.load_revision
        def run():
            try:
                folder=asset_folder()/'animation';data={}
                for action in ('intro','outro'):
                    info=json.loads((folder/f'{mode}-{action}.json').read_text())
                    with Image.open(folder/f'{mode}-{action}.png') as atlas:
                        size=info['size'];columns=info['columns'];frames=[]
                        for i in range(len(info['durations'])):
                            x,y=(i%columns)*size,(i//columns)*size
                            frames.append(atlas.crop((x,y,x+size,y+size)).resize((output_size,output_size),Image.Resampling.LANCZOS))
                    data[action]=(frames,info['durations'])
                with Image.open(folder/f'{mode}-hold.png') as image:data['hold']=([image.convert('RGBA').resize((output_size,output_size),Image.Resampling.LANCZOS)],[100])
                self.results.put((mode,data,revision))
            except Exception:self.results.put((mode,{},revision))
        threading.Thread(target=run,daemon=True).start()
        if self.poll_timer is None:self.poll_timer=self.after(40,self.poll)
    def poll(self):
        if self.closed:return
        try:
            mode,data,revision=self.results.get_nowait()
            if revision==self.load_revision:
                for action,(frames,durations) in data.items():self.frames[mode,action]=([ImageTk.PhotoImage(frame,master=self.root) for frame in frames],durations)
                self.loading.discard(mode)
        except Empty:pass
        self.poll_timer=self.after(40,self.poll) if self.loading else None
    def clicked(self):
        if self.started and not self.active:self.play(['outro','intro'])
    def play(self,actions):
        if self.closed or not self.ready:return
        self.cancel_animation()
        self.started=True;self.active=bool(actions);self.token+=1;token=self.token;mode=self.mode();self.load(mode)
        def begin():
            if self.closed or token!=self.token:return
            if mode in self.loading:self.timer=self.after(30,begin,animation=True);return
            if (mode,'hold') not in self.frames:return
            self.show();step(0,0)
        def step(sequence,index):
            if self.closed or token!=self.token:return
            if sequence>=len(actions):
                self.label.configure(image=self.frames[mode,'hold'][0][0]);self.active=False
                if self.loop_delay:self.after(self.loop_delay,lambda:self.play(['outro','intro']) if token==self.token and not self.closed else None,animation=True)
                return
            frames,durations=self.frames[mode,actions[sequence]]
            self.label.configure(image=frames[index])
            next_sequence,next_index=(sequence,index+1) if index+1<len(frames) else (sequence+1,0)
            self.timer=self.after(durations[index],lambda:step(next_sequence,next_index),animation=True)
        begin()
    def close(self):
        self.closed=True;self.token+=1
        for timer in self.pending:
            try:self.root.after_cancel(timer)
            except tk.TclError:pass
        self.pending.clear()
        self.animation_pending.clear()
        self.frames.clear();self.waiting.clear();self.blank=None
