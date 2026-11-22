# SPDX-License-Identifier: GPL-3.0-or-later
"""Centered, click-through loupe with pointer motion independent of frame capture."""
import ctypes as c
from ctypes import wintypes as w
from queue import Queue, Empty
import threading
import time
import tkinter as tk
from PIL import Image, ImageTk
from review_theme import DEFAULT_PALETTE
from review_live_loupe import LiveLoupe
from review_loupe_cursor import LoupeCursor
from review_windows import pointer,client_rect,place_window


class Magnifier:
    def __init__(self,root,frame,player,settings):
        self.root,self.frame,self.player,self.settings=root,frame,player,settings
        self.zoom=max(1,float(settings.data['magnifier']['zoom']))
        self.active,self.busy,self.closed=False,False,False
        self.window,self.image,self.photo=None,None,None
        self.results,self.generation=Queue(),0
        self.last_capture,self.started=0,0
        self.image_token,self.draw_token=None,None
        self.frame_number=0
        self.live,self.live_failed,self.period_active=None,False,False
        self.live_layout,self.live_draw=None,None
        self.cursor=LoupeCursor(root,frame)
        self.user=c.windll.user32
        self.mouse_state=self.user.GetAsyncKeyState
        self.mouse_state.argtypes,self.mouse_state.restype=[c.c_int],c.c_short
        self.user.GetAncestor.argtypes,self.user.GetAncestor.restype=[w.HWND,w.UINT],w.HWND
        self.user.GetWindowLongPtrW.argtypes,self.user.GetWindowLongPtrW.restype=[w.HWND,c.c_int],c.c_ssize_t
        self.user.SetWindowLongPtrW.argtypes,self.user.SetWindowLongPtrW.restype=[w.HWND,c.c_int,c.c_ssize_t],c.c_ssize_t
        self.user.SetWindowPos.argtypes=[w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT]
        self.user.SetLayeredWindowAttributes.argtypes=[w.HWND,w.DWORD,c.c_ubyte,w.DWORD]
        root.bind_all('<ButtonRelease-1>',lambda e:self.hide(),add='+')
        self.timer=root.after(16,self.animate)

    def animate(self):
        if self.closed:return
        self.tick(time.monotonic())
        self.timer=self.root.after(max(2,int(self.settings.data['magnifier']['refresh_ms'])) if self.active else 16,self.animate)

    def press(self,event=None):
        mixer=self.player()
        if not mixer or not mixer.ready:return
        self.active,self.started,self.last_capture=True,time.monotonic(),0
        self.resize_aspect=int(self.settings.data['magnifier']['width'])/int(self.settings.data['magnifier']['height'])
        # Retry the live compositor on each new hold, rather than retaining a
        # transient DWM failure for the lifetime of the application.
        self.live_failed=False
        self.cursor.start(self.settings.data.getboolean('magnifier','show_cursor'),self.settings.path.parent)
        if not self.period_active:
            self.period_active=c.windll.winmm.timeBeginPeriod(1)==0
        self.image_token,self.draw_token=None,None
        self.frame.focus_set()

    def adjust(self,direction):
        if not self.active:return
        cfg=self.settings.data['magnifier']
        self.zoom=round(min(float(cfg['maximum']),max(1,self.zoom+direction*float(cfg['step']))),2)
        cfg['zoom']=str(self.zoom)
        self.draw()

    def toggle_cursor(self):
        if not self.active:return
        cfg=self.settings.data['magnifier'];show=not cfg.getboolean('show_cursor')
        cfg['show_cursor']='yes' if show else 'no'
        self.cursor.start(show,self.settings.path.parent);self.settings.save()

    def wheel(self,event):
        if event.state&4:self.resize(1 if event.delta>0 else -1)
        else:self.adjust(1 if event.delta>0 else -1)
        return 'break' if self.active else None

    def resize(self,direction):
        if not self.active:return
        cfg=self.settings.data['magnifier'];width,height=int(cfg['width']),int(cfg['height'])
        aspect=getattr(self,'resize_aspect',width/height)
        self.resize_aspect=aspect
        factor=1.1 if direction>0 else 1/1.1
        factor=min(factor,1600/width,1200/height) if direction>0 else max(factor,128/width,128/height)
        cfg['width']=str(round(width*factor));cfg['height']=str(round(int(cfg['width'])/aspect))
        self.live_layout=None;self.draw_token=None;self.draw()

    def hide(self):
        if self.active:self.generation+=1
        self.active=False
        self.cursor.stop()
        if self.period_active:c.windll.winmm.timeEndPeriod(1);self.period_active=False
        self.image=None
        self.image_token,self.draw_token=None,None
        if self.window:self.window.withdraw()

    def tick(self,now):
        while True:
            try:generation,token,image,aspect=self.results.get_nowait()
            except Empty:break
            self.busy=False
            if generation==self.generation and self.active and image is not None:
                self.image,self.aspect,self.image_token=image,aspect,token
                self.frame_number+=1
        if not self.active or self.closed:return
        if now-self.started>.12 and not self.mouse_state(1)&0x8000:
            self.hide();return
        if not str(self.root.tk.call('focus','-displayof',self.root._w)):
            self.hide();return
        mixer=self.player()
        if not mixer or not mixer.ready:
            self.hide();return
        if self.settings.data['magnifier']['mode']!='Frame capture' and not self.live_failed:
            try:
                self.draw_live()
                return
            except (OSError,tk.TclError):
                self.live_failed=True
                if self.live:self.live.close();self.live=None
        token=(id(mixer),str(mixer.path),mixer.position,mixer.paused)
        interval=max(.016,int(self.settings.data['magnifier']['capture_ms'])/1000)
        if not self.busy and token!=self.image_token and now-self.last_capture>=interval:
            self.busy,self.last_capture=True,now
            generation=self.generation
            def capture():
                image,aspect=None,1
                try:
                    image=mixer.capture()
                    params=mixer.engine.get('video-out-params',{})
                    aspect=params['dw']/params['dh'] if params.get('dw') and params.get('dh') else image.width/image.height
                except Exception:pass
                self.results.put((generation,token,image,aspect))
            threading.Thread(target=capture,daemon=True).start()
        self.draw()

    def make_window(self):
        self.window=tk.Toplevel(self.root,takefocus=False)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes('-topmost',True)
        self.label=tk.Label(self.window,bd=0)
        self.label.pack(padx=2,pady=(2,0))
        self.caption=tk.Label(self.window,font=('Segoe UI',9),bd=0)
        self.caption.pack(fill='x',padx=2,pady=(0,2))
        self.window.update_idletasks()
        self.hwnd=None;self.native_style()
        self.refresh_palette()

    def native_style(self):
        current=self.user.GetAncestor(self.window.winfo_id(),2)
        if current==getattr(self,'hwnd',None):return
        self.hwnd=current
        # The loupe is centered over the pointer: pass mouse input through to the
        # video and never activate this overlay or steal its button-up event.
        style=self.user.GetWindowLongPtrW(self.hwnd,-20)
        self.user.SetWindowLongPtrW(self.hwnd,-20,style|0x08000000|0x00080000|0x20)
        self.user.SetLayeredWindowAttributes(self.hwnd,0,255,2)

    def refresh_palette(self):
        colors=getattr(self.root,'review_palette',DEFAULT_PALETTE)
        if self.window:
            self.window.configure(bg=colors['selection'])
            self.label.configure(bg=colors['panel'])
            self.caption.configure(bg=colors['panel'],fg=colors['text'])

    def draw(self):
        if self.active and self.live and self.settings.data['magnifier']['mode']!='Frame capture':
            self.draw_live();return
        if not self.active or self.image is None:return
        if self.live:self.live.close();self.live=None
        cfg=self.settings.data['magnifier']
        width,height=int(cfg['width']),int(cfg['height'])
        px,py=pointer()
        fx,fy,fr,fb=client_rect(self.frame)
        fw,fh=max(1,fr-fx),max(1,fb-fy)
        display_w,display_h=min(fw,fh*self.aspect),min(fh,fw/self.aspect)
        source_w,source_h=self.image.size
        cx=(px-fx-(fw-display_w)/2)/display_w*source_w
        cy=(py-fy-(fh-display_h)/2)/display_h*source_h
        crop_w=width/self.zoom*source_w/display_w;crop_h=height/self.zoom*source_h/display_h
        signature=(px,py,width,height,self.zoom,self.frame_number,cfg['smoothing'],fw,fh)
        if self.window is None:self.make_window()
        self.label.configure(width=0,height=0)
        if self.label.winfo_manager()!='pack':
            self.caption.place_forget();self.label.pack(padx=2,pady=(2,0));self.caption.pack(fill='x',padx=2,pady=(0,2))
        if signature!=self.draw_token:
            smooth=self.settings.data.getboolean('magnifier','smoothing')
            image=self.image.transform((width,height),Image.Transform.EXTENT,
                (cx-crop_w/2,cy-crop_h/2,cx+crop_w/2,cy+crop_h/2),
                resample=Image.Resampling.BICUBIC if smooth else Image.Resampling.NEAREST,fillcolor='black')
            if self.photo is None or self.photo.width()!=width or self.photo.height()!=height:
                self.photo=ImageTk.PhotoImage(image)
                self.label.configure(image=self.photo)
                self.window.geometry(f'{width+4}x{height+26}')
            else:self.photo.paste(image)
            self.caption.configure(text=f'{self.zoom:g}x - Live Zoom - Scroll Wheel: Zoom - CTRL+Scroll: Size')
            self.draw_token=signature
        # Center the picture itself at the pointer, with no constraint to the
        # playback pane. The overlay may extend over any other part of the app.
        x,y=int(px-width/2-2),int(py-height/2-2)
        self.last_geometry=(x,y,width+4,height+26)
        if self.window.state()=='withdrawn':self.window.deiconify()
        place_window(self.window,x,y,width+4,height+26)
        self.native_style()

    def draw_live(self):
        cfg=self.settings.data['magnifier'];width,height=int(cfg['width']),int(cfg['height'])
        if self.window is None:self.make_window()
        if self.live is None:self.live=LiveLoupe(getattr(self,'source_window',self.root),self.window)
        if self.live_layout!=(width,height,self.zoom):
            self.label.configure(image='',width=1,height=1,bg='black')
            self.label.pack_forget();self.caption.pack_forget()
            self.caption.place(x=2,y=height+2,width=width,height=22)
            self.window.configure(bg='black');self.window.geometry(f'{width+4}x{height+26}')
            self.caption.configure(text=f'{self.zoom:g}x - Live Zoom - Scroll Wheel: Zoom - CTRL+Scroll: Size')
            self.live_layout=(width,height,self.zoom)
        px,py=pointer()
        signature=(px,py,width,height,self.zoom,*client_rect(self.frame))
        self.live.connect()
        if signature==self.live_draw and self.live.signature is not None and self.window.state()!='withdrawn':return
        x,y=int(px-width/2-2),int(py-height/2-2)
        self.last_geometry=(x,y,width+4,height+26)
        if self.window.state()=='withdrawn':self.window.deiconify()
        place_window(self.window,x,y,width+4,height+26)
        self.native_style()
        self.live.update(self.frame,px,py,width,height,self.zoom)
        self.live_draw=signature

    def reset_mode(self):
        self.hide();self.live_failed=False
        if self.live:self.live.close();self.live=None
        if self.window:self.window.destroy();self.window=None
        self.photo=None
        self.live_layout,self.live_draw=None,None

    def close(self):
        self.hide();self.closed=True
        if self.live:self.live.close();self.live=None
        if self.timer:self.root.after_cancel(self.timer);self.timer=None
        if self.window:self.window.destroy();self.window=None
