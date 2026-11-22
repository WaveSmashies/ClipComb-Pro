# SPDX-License-Identifier: GPL-3.0-or-later
"""Theme-aware vector transport icons, generated only on palette changes."""
import tkinter as tk
import math
from tkinter import ttk
from PIL import Image,ImageDraw,ImageTk
from review_help import Tooltip


SPEED_TOOLTIP = (
    "Change clip playback speed.\n"
    "Click once to change speed by 1x\n"
    "Shift+Click to change speed by 0.25x\n"
    "CTRL+Click to change speed by 0.1x\n\n"
    "Note: You can also change the speed directly with keyboard shortcuts. Find them in the settings."
)


def icon(root,name,color,size=30,capped=True):
    scale=4;im=Image.new('RGBA',(size*scale,size*scale));d=ImageDraw.Draw(im)
    def poly(points):d.polygon([(int(x*size*scale),int(y*size*scale)) for x,y in points],fill=color)
    def bar(x):d.rectangle((x*size*scale,.2*size*scale,(x+.08)*size*scale,.8*size*scale),fill=color)
    if name=='play':poly([(.31,.18),(.81,.5),(.31,.82)])
    elif name=='pause':bar(.28);bar(.61)
    elif name=='bookmark':poly([(.5,.19),(.81,.5),(.5,.81),(.19,.5)])
    elif name=='favorite':
        poly([(.5+(.4 if i%2==0 else .18)*math.cos(-math.pi/2+i*math.pi/5),.5+(.4 if i%2==0 else .18)*math.sin(-math.pi/2+i*math.pi/5)) for i in range(10)])
    elif name=='snap':
        d.arc((.18*size*scale,.25*size*scale,.82*size*scale,.86*size*scale),0,180,fill=color,width=int(.16*size*scale))
        for x in (.18,.66):
            d.rectangle((x*size*scale,.14*size*scale,(x+.16)*size*scale,.56*size*scale),fill=color)
            d.rectangle((x*size*scale,.14*size*scale,(x+.16)*size*scale,.30*size*scale),fill='#ffffff',outline='#242424' if capped else None,width=max(1,scale))
            if not capped:d.line((x*size*scale,.30*size*scale,(x+.16)*size*scale,.30*size*scale),fill='#242424',width=scale)
        im=im.rotate(-45,resample=Image.Resampling.BICUBIC)
    else:
        back=name.endswith('back');large=name.startswith('large');frame=name.startswith('frame')
        def triangle(a,b):poly([(b if back else a,.23), (a if back else b,.5), (b if back else a,.77)])
        if large:triangle(.14,.47);triangle(.5,.83)
        else:triangle(.24 if not frame else .35,.74 if not frame else .75)
        if frame:bar(.18 if back else .78)
    return ImageTk.PhotoImage(im.resize((size,size),Image.Resampling.LANCZOS),master=root)


class Transport(ttk.Frame):
    def __init__(self,parent,app,annotations=True,display=None):
        super().__init__(parent,height=70);self.app=app;self.paused=True;self.images={};self.buttons={};self.palette=None;self.render_key=None;self.scale=1
        self.review_manual_scale=True
        display=display or app
        self.speed_row=ttk.Frame(self)
        self.speed_slot=ttk.Frame(self.speed_row)
        self.speed_slot.pack(side='left')
        self.speed=ttk.Label(self.speed_slot,textvariable=display.speed_label,style='Speed.TLabel')
        self.speed.place(x=0,rely=.5,anchor='w')
        self.speed_buttons={}
        for name,direction in (('large_back',-1),('large_forward',1)):
            button=ttk.Button(self.speed_row,text='Decrease Speed' if direction<0 else 'Increase Speed',
                              command=lambda d=direction:app.change_speed(d),
                              compound='image',style='Transport.Round.TButton',takefocus=True)
            button.pack(side='left',padx=(4,0))
            button.bind('<ButtonRelease-1>',lambda event,d=direction:self.modified_speed_click(event,d))
            Tooltip(button,SPEED_TOOLTIP)
            self.speed_buttons[name]=button
        self.timecode=ttk.Label(self,textvariable=display.time_label,style='Timecode.TLabel');self.timecode.place(x=0,y=40)
        self.framerate=ttk.Label(self,textvariable=display.fps_label,style='Hint.TLabel')
        Tooltip(self.framerate,'Source video frame rate. The frame timecode uses this clip’s nominal non-drop-frame rate. Fractional rates keep their original timing.')
        self.main=ttk.Frame(self);self.frames=ttk.Frame(self);self.magnet=ttk.Frame(self)
        self.grip=tk.Canvas(self,width=42,height=10,highlightthickness=0,cursor='sb_v_double_arrow')
        self.grip.bind('<ButtonPress-1>',self.resize_begin);self.grip.bind('<B1-Motion>',self.resize_move);self.grip.bind('<ButtonRelease-1>',lambda e:app.settings.save())
        self.grip.bind('<Double-Button-1>',self.resize_reset)
        Tooltip(self.grip,'Drag up to enlarge the playback controls or down to shrink them. Double-click to reset. Controls also adapt to the monitor.\n\nDefault: Automatic monitor size (100%).')
        for name,action,help_ in [
            ('large_back',lambda:app.seek_relative(-float(app.settings.data['app']['seek_large'])),'Large skip back'),
            ('small_back',lambda:app.seek_relative(-float(app.settings.data['app']['seek_small'])),'Small skip back'),
            ('play',app.toggle_play,'Play / pause'),
            ('small_forward',lambda:app.seek_relative(float(app.settings.data['app']['seek_small'])),'Small skip forward'),
            ('large_forward',lambda:app.seek_relative(float(app.settings.data['app']['seek_large'])),'Large skip forward'),
            ('frame_back',None,'Previous frame · hold to repeat'),('frame_forward',None,'Next frame · hold to repeat'),
            ('bookmark',lambda:app.markers.activate(),'Add bookmark / edit bookmark at playhead'),
            ('favorite',lambda:app.stars.edit(),'Add or edit clip Star'),
            ('snap',app.toggle_snapping,'Snap playhead to nearby elements')]:
            if not annotations and name in ('bookmark','snap','favorite'):continue
            button=ttk.Button(self.magnet if name in ('snap','favorite') else self.frames if name.startswith('frame') or name=='bookmark' else self.main,command=action or (lambda:None),
                              text=help_,compound='image',style='Transport.Primary.TButton' if name=='play' else 'Transport.Round.TButton',takefocus=True)
            button.pack(side='left',padx=3);self.buttons[name]=button
            action_names={'large_back':'back_large','small_back':'back','small_forward':'forward','large_forward':'forward_large','bookmark':'marker','snap':'snap_playhead'}
            def describe(n=name,h=help_):
                if n=='favorite':
                    from review_stars import DEFAULT_TOOLTIP
                    return app.action_tip(DEFAULT_TOOLTIP,'star')
                if n.startswith(('large','small')):
                    key='seek_large' if n.startswith('large') else 'seek_small'
                    h+=f' ({float(app.settings.data["app"][key]):g} s)'
                if n=='snap':h+=' · '+('On' if app.settings.data.getboolean('snapping','enabled') else 'Off')
                return app.action_tip(h,action_names.get(n,n))
            button.review_tooltip=Tooltip(button,describe)
            if name.startswith('frame'):
                direction=-1 if name.endswith('back') else 1
                def press(event,n=name,d=direction):
                    if app.busy:return 'break'
                    if app.frame_repeat and app.frame_repeat[0]==('transport',str(self.buttons[n])):return 'break'
                    app.step_frame(d);app.start_frame_repeat(('transport',str(self.buttons[n])),d)
                def release(event,n=name):
                    if app.frame_repeat and app.frame_repeat[0]==('transport',str(self.buttons[n])):app.stop_frame_repeat()
                button.bind('<ButtonPress-1>',press);button.bind('<ButtonRelease-1>',release)
                button.bind('<KeyPress-Return>',press);button.bind('<KeyRelease-Return>',release)
        from review_render import FrameUpdate
        self.resize_update=FrameUpdate(self,self.layout);self.layout_key=None
        self.bind('<Configure>',self.resize_update.request)
        for widget in (self.timecode,self.framerate,self.speed_row):
            widget.bind('<Configure>',self.resize_update.request)

    def modified_speed_click(self,event,direction):
        if not event.state & (1 | 4):
            return  # Let ttk process an ordinary click.
        button=event.widget
        pressed=button.instate(('pressed','!disabled'))
        button.state(('!pressed',))
        if pressed and 0<=event.x<button.winfo_width() and 0<=event.y<button.winfo_height():
            self.app.change_speed(direction*(.1 if event.state&4 else .25))
        return 'break'

    def layout(self,event=None):
        self.render()
        s=self.scale;i=self.info_scale
        width=self.winfo_width();main_w=self.main.winfo_reqwidth();frames_w=self.frames.winfo_reqwidth();magnet_w=self.magnet.winfo_reqwidth()
        info_width=max(self.speed_row.winfo_reqwidth(),self.timecode.winfo_reqwidth()+self.framerate.winfo_reqwidth()+12*s)
        compact=width<max(950*s,2*(info_width+main_w//2+magnet_w+32*s));narrow=width<max(570*s,main_w+2*frames_w+34*s)
        viewer=getattr(self.app,'viewer',None)
        main_control=viewer.controls if viewer and viewer.enabled else self.app.transport if hasattr(self.app,'transport') else self
        history_min=(sum(w.winfo_reqheight() for w in self.app.history_panel.pack_slaves())+12) if hasattr(self.app,'history_panel') and self==main_control else 0
        key=(main_w,frames_w,magnet_w,info_width,s,i,compact,narrow,history_min,self==main_control,self.timecode.winfo_reqheight(),self.framerate.winfo_reqheight())
        if self.layout_key==key:
            if self.layout_width!=width:self.center_controls(width,main_w,s,narrow)
            return
        self.layout_key=key
        y=max(round((113 if compact else 44)*s),round((95 if compact else 44)*i))
        frame_y=math.ceil(y+(self.main.winfo_reqheight()+self.frames.winfo_reqheight())/2+8*s) if narrow else y
        controls_bottom=max(y+self.main.winfo_reqheight()/2,frame_y+self.frames.winfo_reqheight()/2)+8
        self.configure(height=max(history_min,math.ceil(controls_bottom),round((188 if narrow else 142 if compact else 106)*s),round(80*i)))
        self.speed_row.place(x=0,y=round(5*i));self.timecode.place(x=0,y=round(55*i))
        self.framerate.place(x=self.timecode.winfo_reqwidth()+round(12*s),y=round(55*i)+self.timecode.winfo_reqheight()/2,anchor='w')
        if hasattr(self.app,'history_panel') and self==main_control:self.app.history_panel.configure(height=self.winfo_reqheight())
        # The play/pause icon is the exact center of the five skip/play controls.
        self.main.place(y=y,anchor='center')
        self.magnet.place(y=y,anchor='e')
        self.frames.place(y=frame_y,anchor='center' if narrow else 'w')
        self.grip.place(y=y-round(29*s),anchor='s')
        self.center_controls(width,main_w,s,narrow)
    def center_controls(self,width,main_width,scale,narrow):
        self.layout_width=width
        center=width//2
        self.main.place_configure(x=center)
        self.magnet.place_configure(x=center-main_width//2-round(12*scale))
        self.frames.place_configure(x=center if narrow else center+main_width//2+round(14*scale))
        self.grip.place_configure(x=center)
    def resize_begin(self,event):self.drag_size=(event.y_root,float(self.app.settings.data['app']['transport_scale']))
    def resize_move(self,event):
        start,value=self.drag_size;value=max(.5,min(3,value*2**((start-event.y_root)/140)))
        self.app.settings.data['app']['transport_scale']=f'{value:.3f}'
        self.resize_update.request()
        viewer=getattr(self.app,'viewer',None)
        other=viewer.controls if viewer and viewer.enabled else None
        if other and other!=self:other.resize_update.request()
        if getattr(self.app,'transport',self)!=self:self.app.transport.resize_update.request()
    def resize_reset(self,event=None):self.app.settings.data['app']['transport_scale']='1';self.app.update_transports('layout');self.app.settings.save();return 'break'
    def set_palette(self,palette):
        self.palette=dict(palette);self.layout()
    def render(self):
        if self.palette is None:return
        auto=getattr(self.winfo_toplevel(),'review_scale',getattr(self.app.root,'review_scale',1))
        self.scale=round(auto*max(.5,min(3,float(self.app.settings.data['app']['transport_scale']))),3)
        self.info_scale=max(auto,self.scale)
        starred=bool((self.app.clip() or {}).get('star'))
        s=self.scale;i=self.info_scale
        key=(tuple(round(v*s) for v in (3,7,8,10,30,35,42)),tuple(round(v*i) for v in (12,15,32)),tuple(self.palette.items()),self.app.settings.data['snapping']['enabled'],starred)
        if self.render_key==key:return
        self.render_key=key;palette=self.palette;s=self.scale;i=self.info_scale
        speed_font=('Segoe UI',-round(32*i),'bold')
        self.speed.configure(font=speed_font);self.timecode.configure(font=('Consolas',-round(15*i)))
        speed_width=int(self.tk.call('font','measure',speed_font,'8.88×'))
        self.speed_slot.configure(width=speed_width+round(6*i),height=self.speed.winfo_reqheight())
        self.framerate.configure(font=('Segoe UI',-round(12*i)))
        self.grip.configure(width=round(42*s),height=round(10*s),bg=palette['background']);self.grip.delete('all')
        self.grip.create_line(round(7*s),round(5*s),round(35*s),round(5*s),fill=palette['muted_text'],width=max(2,round(3*s)),capstyle='round')
        snap=self.app.settings.data.getboolean('snapping','enabled')
        images={name:icon(self,name,'#000000' if name=='favorite' and starred else palette['highlighted_button_text'] if name in ('play','pause') or name=='snap' and snap or name=='favorite' and starred else palette['highlighted_button'] if name=='bookmark' else palette['button_text'],size=round(30*s),capped=name!='snap' or snap)
                     for name in [*self.buttons,'pause']}
        for name,button in self.buttons.items():button.configure(image=images[name],padding=(round(8*s),round(8*s)));button.pack_configure(padx=max(1,round(3*s)))
        for name,button in self.speed_buttons.items():
            picture=icon(self,name,palette['button_text'],size=max(8,round(16*i)))
            button.configure(image=picture,padding=(round(4*i),round(2*i)))
            button.pack_configure(padx=(max(2,round(4*i)),0))
            images['speed_'+name]=picture
        self.images=images
        if 'snap' in self.buttons:self.buttons['snap'].configure(style='Transport.Primary.TButton' if snap else 'Transport.Round.TButton')
        if 'favorite' in self.buttons:self.buttons['favorite'].configure(style='Transport.Primary.TButton' if starred else 'Transport.Round.TButton')
        self.set_paused(self.paused)
    def set_paused(self,paused):
        self.paused=paused
        if self.images:self.buttons['play'].configure(image=self.images['play' if paused else 'pause'],text='Play' if paused else 'Pause')

    def set_available(self,available):
        self.render()
        for name,button in self.buttons.items():
            if name!='snap':button.configure(state='normal' if available else 'disabled')
        for button in self.speed_buttons.values():
            button.configure(state='normal' if available else 'disabled')
