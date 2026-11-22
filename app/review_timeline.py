# SPDX-License-Identifier: GPL-3.0-or-later
import tkinter as tk
import uuid
import math
from review_theme import BG, PANEL, BORDER, TEXT, MUTED, ACCENT, ACCENT_DARK, DEFAULT_PALETTE,blend
from review_marker_colors import RESOLVE,slot
from review_marker_ranges import duration as marker_duration,end as marker_end,boundaries as marker_boundaries
from review_waveform import display_amplitude


def timestamp(seconds):
    minutes, seconds = divmod(max(0, seconds), 60)
    hours, minutes = divmod(int(minutes), 60)
    return (f'{hours:02}:' if hours else '') + f'{minutes:02}:{seconds:06.3f}'


class RangeTimeline(tk.Canvas):
    def __init__(self, parent, seek, changed, selected, scrub=None):
        super().__init__(parent, height=200, bg=PANEL, highlightthickness=0, takefocus=True)
        self.palette = dict(DEFAULT_PALETTE)
        self.format_time=timestamp
        self.waveform,self.wave_bins,self.wave_label = [],50,''
        self.seek, self.changed, self.selected_callback = seek, changed, selected
        self.scrub_callback = scrub
        self.duration, self.position, self.ranges, self.selected = 0, 0, [], None
        self.markers, self.selected_marker = [], None
        self.marker_seek_id=None
        self.marker_edit, self.marker_changed = None, None
        self.marker_clicked=None;self.marker_scrub_clicked=None;self.marker_colors=RESOLVE
        self.snap_enabled=lambda:True;self.frame_time=lambda t:t;self.frame_duration=lambda:1/30
        self.cut_points, self.snap_range = [], None
        self.interaction_allowed = lambda: True
        self.drag, self.ghost = None, None
        self.scrubbing, self.right_origin = False, None
        self.right_selecting=False;self.right_interacts_existing=lambda:True
        from review_render import FrameUpdate
        from review_windows import primary_button_held
        self.resize_update=FrameUpdate(self,lambda:self.draw(resizing=True),settled=self.draw,dragging=primary_button_held)
        self.bind('<Configure>', self.resize_update.request)
        self.bind('<Button-1>', self.left_down)
        self.bind('<B1-Motion>', self.left_move)
        self.bind('<ButtonRelease-1>', self.left_up)
        self.bind('<Button-3>', self.right_down)
        self.bind('<B3-Motion>', self.right_move)
        self.bind('<ButtonRelease-3>', self.right_up)
        self.bind('<Double-Button-3>', self.right_double)
        self.bind('<Double-Button-1>', self.marker_double)
        self.bind('<Motion>', self.hover)
        self.alt_down=False
        for key in ('Alt_L','Alt_R'):
            self.bind_all('<KeyPress-'+key+'>',lambda e:self.alt_hover(True),add='+')
            self.bind_all('<KeyRelease-'+key+'>',lambda e:self.alt_hover(False),add='+')
        self.bind('<Leave>', lambda e: self.configure(cursor='arrow') if not self.drag else None)

    @property
    def unit(self):return getattr(self._root(),'review_scale',1)

    def x(self, seconds):
        return 16*self.unit + min(1, max(0, seconds / (self.duration or 1))) * max(1, self.winfo_width() - 32*self.unit)

    def seconds(self, x):
        return min(self.duration,max(0,self.frame_time(self.duration * min(1, max(0, (x - 16*self.unit) / max(1, self.winfo_width() - 32*self.unit))))))

    def snapped(self,position,targets=None,force=False):
        if not force and not self.snap_enabled():return position
        if targets is None:targets=[0,self.duration]+[r[k] for r in self.ranges for k in ('start','end')]+marker_boundaries(self.markers)
        nearby=[t for t in targets if abs(self.x(t)-self.x(position))<=10*self.unit]
        return min(nearby,key=lambda t:abs(t-position)) if nearby else position

    def set_clip(self, duration, ranges):
        self.cancel_interaction()
        self.duration, self.ranges, self.selected = duration, ranges, None
        self.markers, self.selected_marker, self.cut_points = [], None, []
        self.marker_seek_id=None
        self.snap_range=None
        self.position, self.drag, self.ghost = 0, None, None
        self.waveform,self.wave_label = [],''
        self.wave_revision=getattr(self,'wave_revision',0)+1
        self.draw()

    def playback_position(self, position):
        if self.marker_seek_id:
            marker=next((m for m in self.markers if m['id']==self.marker_seek_id),None)
            if marker and abs(self.frame_time(position)-self.frame_time(marker['time']))<1e-7:position=marker['time']
            else:self.marker_seek_id=None
        # The playback clock must not compete with the pointer while scrubbing.
        if self.scrubbing or self.position==position:return
        self.position = position
        self.draw_playhead()

    def begin_scrub(self, x, direct_marker=None):
        if not self.interaction_allowed():return False
        if not self.duration or self.drag and not self.scrubbing:
            return False
        self.focus_set()
        self.scrubbing, self.drag = True, 'seek'
        self.direct_marker=(direct_marker,x) if direct_marker else None
        self.position = direct_marker['time'] if direct_marker else self.snapped(self.seconds(x))
        if self.scrub_callback:
            self.scrub_callback('begin', self.position)
        else:
            self.seek(self.position)
        self.draw()
        return True

    def move_scrub(self, x):
        if self.scrubbing:
            direct=getattr(self,'direct_marker',None)
            if direct and abs(x-direct[1])>=3:self.direct_marker=None;direct=None
            self.position = direct[0]['time'] if direct else self.snapped(self.seconds(x))
            if self.scrub_callback:
                self.scrub_callback('move', self.position)
            self.draw_playhead()

    def end_scrub(self, x=None):
        if not self.scrubbing:
            return
        direct=getattr(self,'direct_marker',None)
        if x is not None:
            self.position = direct[0]['time'] if direct and abs(x-direct[1])<3 else self.snapped(self.seconds(x))
        self.scrubbing, self.drag = False, None
        if self.scrub_callback:
            self.scrub_callback('end', self.position)
        else:
            self.seek(self.position)
        if direct:
            callback=self.marker_scrub_clicked or self.marker_clicked
            if callback:callback(direct[0]['id'])
        self.direct_marker=None
        self.draw()

    def cancel_interaction(self):
        if getattr(self,'review_tooltip',None):self.review_tooltip.hide()
        if self.scrubbing and self.scrub_callback:
            self.scrub_callback('cancel', self.position)
        self.scrubbing, self.drag, self.ghost, self.right_origin = False, None, None, None
        self.right_selecting=False

    def lane_geometry(self):
        return tuple(round(v*self.unit) for v in ((72,76,45,80,100) if self.cut_points else (92,96,45,100,128)))

    def hit(self, x, y):
        if not 55*self.unit <= y <= self.lane_geometry()[1]+3*self.unit:
            return None, None
        edges = [(abs(x-self.x(r[edge])), r, edge) for r in self.ranges for edge in ('start','end')]
        if edges:
            distance, r, edge = min(edges, key=lambda c: (c[0], c[1]['id'] != self.selected))
            if distance <= 9*self.unit:
                return r, edge
        hits = [r for r in self.ranges if self.x(r['start']) <= x <= self.x(r['end'])]
        if hits:
            r = next((r for r in hits if r['id'] == self.selected), hits[-1])
            return r, 'body'
        return None, None

    def hover(self, e):
        if self.drag:
            mode = 'seek' if self.scrubbing else self.drag[1]
        else:
            marker,mode=self.marker_part(e.x,e.y)
            if marker and (getattr(e,'state',0)&(8|0x20000) or self.alt_down):mode='extend'
            if not marker:_, mode = self.hit(e.x, e.y)
        self.configure(cursor='size_we' if mode in ('start','end','extend') else 'fleur' if mode == 'body' else 'arrow')

    def alt_hover(self,down):
        from types import SimpleNamespace
        self.alt_down=down
        x,y=self.winfo_pointerxy();x-=self.winfo_rootx();y-=self.winfo_rooty()
        if 0<=x<self.winfo_width() and 0<=y<self.winfo_height():self.hover(SimpleNamespace(x=x,y=y,state=0))

    def draw(self,resizing=False):
        BG,PANEL,BORDER,TEXT,MUTED,ACCENT,ACCENT_DARK = (self.palette[k] for k in (
            'background','panel','border','text','muted_text','selection','selection_fill'))
        self.delete('all')
        width = self.winfo_width();s=self.unit
        self.create_line(16*s, 32*s, width - 16*s, 32*s, fill=BORDER, width=2)
        for i in range(7) if self.duration>0 else (0,):
            t = self.duration * i / 6
            x = self.x(t)
            self.create_line(x, 27*s, x, 34*s, fill=MUTED)
            self.create_text(x, 15*s, text=self.format_time(t), fill=MUTED, font=('Segoe UI', 9),
                             anchor='w' if i == 0 else 'e' if i == 6 else 'center')
        band_bottom,handle_bottom,marker_y,wave_line,wave_top=self.lane_geometry()
        for i, r in enumerate(self.ranges):
            color = ACCENT if r['id'] == self.selected else ACCENT_DARK
            x1, x2 = self.x(r['start']), self.x(r['end'])
            self.create_rectangle(x1, 58*s, x2, band_bottom, fill=color if r.get('enabled', True) else BG,
                                  outline=ACCENT if r['id'] == self.selected else BORDER, width=2)
            for x in (x1, x2):
                self.create_line(x, 55*s, x, handle_bottom, fill=ACCENT, width=3)
            if x2 - x1 > 30:
                self.create_text((x1+x2)/2+1,(58*s+band_bottom)/2+1,text=str(i+1),fill='#15121b',font=('Segoe UI',10 if self.cut_points else 16,'bold'))
                self.create_text((x1+x2)/2,(58*s+band_bottom)/2,text=str(i+1),fill=self.palette['playhead'],font=('Segoe UI',10 if self.cut_points else 16,'bold'))
        if self.ghost:
            ghost=self.snap_range(*sorted(self.ghost)) if self.snap_range else sorted(self.ghost)
            self.create_rectangle(self.x(ghost[0]), 58*s, self.x(ghost[1]), band_bottom,
                                  outline=TEXT, fill=ACCENT_DARK, dash=(4, 3), width=2)
        previous=-100
        for point in self.cut_points:
            x=self.x(point)
            if x-previous>=2:
                self.create_line(x,37*s,x,handle_bottom+2,fill=self.palette['muted_text'],dash=(2,3))
                previous=x
        for marker in sorted(self.markers,key=lambda m:m['time']):
            x=round(self.x(marker['time']))
            color=self.marker_colors[slot(marker)];edge='#ffffff' if marker['id']==self.selected_marker else '#000000'
            if marker_duration(marker):
                finish=round(self.x(marker_end(marker)))
                # Stop at the inside faces of the two arrow handles.
                if finish-x>10*s:
                    self.create_rectangle(x+5*s,marker_y-3*s,finish-5*s,marker_y+3*s,fill=blend(color,PANEL,.65),outline='',tags='bookmark-range')
                self.create_polygon(x,marker_y,x+5*s,marker_y-5*s,x+5*s,marker_y+5*s,fill=color,outline=edge,tags=('bookmark-icon','bookmark-start'))
                self.create_polygon(finish,marker_y,finish-5*s,marker_y-5*s,finish-5*s,marker_y+5*s,fill=color,outline=edge,tags=('bookmark-icon','bookmark-end'))
            else:
                self.create_polygon(x,marker_y-5*s,x+5*s,marker_y,x,marker_y+5*s,x-5*s,marker_y,
                    fill=color,outline=edge,width=1,tags='bookmark-icon')
        self.draw_waveform(resizing)
        self.draw_playhead()
        if not self.duration:
            self.create_text(width / 2, 60*s, text='Choose a clip to start reviewing', fill=MUTED)

    def set_palette(self,palette):
        self.palette=dict(palette)
        self.configure(bg=palette['panel'])
        self.draw()

    def set_waveform(self,peaks,bins,label=''):
        self.waveform,self.wave_bins,self.wave_label = peaks,bins,label
        self.wave_revision=getattr(self,'wave_revision',0)+1
        self.draw()

    def draw_waveform(self,resizing=False):
        height=self.winfo_height();s=self.unit
        wave_line=self.lane_geometry()[3];wave_top=self.lane_geometry()[4]
        if height<wave_top+13 or not self.duration:return
        self.create_line(16*s,wave_line,self.winfo_width()-16*s,wave_line,fill=self.palette['border'])
        if self.wave_label:
            self.create_text(18*s,wave_line+13*s,text=self.wave_label,anchor='w',fill=self.palette['muted_text'],font=('Segoe UI',9))
        width=max(1,round(self.winfo_width()-32*s))
        picture_height=max(1,height-wave_top-12)
        key=(width,picture_height,getattr(self,'wave_revision',0),self.duration,self.wave_bins,self.palette['panel'],self.palette['waveform'],self.palette['border'])
        if getattr(self,'wave_image_key',None)==key:
            self.create_image(16*s,wave_top,image=self.wave_image,anchor='nw');return
        from PIL import Image,ImageDraw,ImageTk
        if resizing and getattr(self,'wave_raster_key',None)==key[2:]:
            # Stretch the last exact image during the drag. Rebuild from the
            # original peaks at the final size when the resize settles.
            picture=self.wave_raster.resize((width,picture_height),Image.Resampling.BILINEAR)
            self.wave_preview=ImageTk.PhotoImage(picture,master=self)
            self.create_image(16*s,wave_top,image=self.wave_preview,anchor='nw')
            return
        picture=Image.new('RGB',(width,picture_height),self.palette['panel']);paint=ImageDraw.Draw(picture)
        center=picture_height/2
        paint.line((0,center,width,center),fill=self.palette['border'])
        count=max(1,round(self.duration*self.wave_bins))
        sample_key=(width,getattr(self,'wave_revision',0),self.duration,self.wave_bins)
        if getattr(self,'wave_sample_key',None)!=sample_key:
            amplitudes=[]
            for x in range(width):
                a=int(x/width*count);b=max(a+1,int((x+1)/width*count))
                if a>=len(self.waveform):break
                amplitudes.append(display_amplitude(max(self.waveform[a:min(b,len(self.waveform))],default=0)))
            self.wave_amplitudes=amplitudes;self.wave_sample_key=sample_key
        top,bottom=[],[]
        for x,peak in enumerate(self.wave_amplitudes):
            amplitude=peak*max(1,(height-wave_top-14)/2)
            top.extend((x,center-amplitude));bottom.extend((x,center+amplitude))
        if len(top)>=4:
            reverse=[v for i in range(len(bottom)-2,-1,-2) for v in bottom[i:i+2]]
            points=top+reverse
            paint.polygon(list(zip(points[::2],points[1::2])),fill=self.palette['waveform'])
        self.wave_raster=picture;self.wave_raster_key=key[2:]
        self.wave_preview=None
        self.wave_image=ImageTk.PhotoImage(picture,master=self);self.wave_image_key=key
        self.create_image(16*s,wave_top,image=self.wave_image,anchor='nw')

    def draw_playhead(self):
        s=self.unit;x=round(self.x(self.position));bottom=max(94*s,self.winfo_height()-8*s)
        color=self.palette['playhead']
        if getattr(self,'cap_color',None)!=(color,s):
            self.cap_color=(color,s)
            from PIL import Image,ImageDraw,ImageTk
            picture=Image.new('RGBA',(max(3,round(13*s)),max(2,round(8*s))))
            ImageDraw.Draw(picture).polygon(((0,0),(picture.width-1,0),(picture.width//2,picture.height-1)),fill=color)
            self.cap_image=ImageTk.PhotoImage(picture,master=self)
        if self.find_withtag('playhead-line'):
            self.coords('playhead-line',x,26*s,x,bottom)
            self.coords('playhead-cap',x,26*s)
        else:
            self.create_line(x,26*s,x,bottom,fill=color,width=3,tags=('playhead','playhead-line'))
            self.create_image(x,26*s,image=self.cap_image,anchor='n',tags=('playhead','playhead-cap'))
        self.tag_raise('playhead')
        self.tag_raise('bookmark-icon')

    def left_down(self, e):
        if not self.interaction_allowed():return
        self.focus_set()
        if not self.duration:
            return
        if self.scrubbing:
            return
        marker,part=self.marker_part(e.x,e.y)
        if marker:
            self.selected=None
            alt=bool(getattr(e,'state',0)&(8|0x20000))
            mode=part
            if alt and not marker_duration(marker):mode='extend'
            elif alt and part=='body':mode='start' if e.x<(self.x(marker['time'])+self.x(marker_end(marker)))/2 else 'end'
            self.selected_marker=marker['id'];self.drag=('marker',mode,uuid.uuid4().hex,e.x,marker['time'],marker_duration(marker),self.position)
            self.marker_dragged=False
            self.draw();return
        if self.right_interacts_existing() and not self.right_selecting:
            self.begin_scrub(e.x);return
        r, mode = self.hit(e.x, e.y)
        if r:
            self.selected_marker=None
            self.edit_group=uuid.uuid4().hex
            self.selected, self.drag = r['id'], (r, mode, self.seconds(e.x), r['start'], r['end'])
            self.selected_callback(r['id'])
        else:
            self.begin_scrub(e.x)
        self.hover(e)
        self.draw()

    def left_move(self, e):
        if self.drag and self.drag[0]=='marker':
            _,mode,group,origin,start,length,playhead=self.drag
            if abs(e.x-origin)<3 and not self.marker_dragged:return
            self.marker_dragged=True
            marker=next((m for m in self.markers if m['id']==self.selected_marker),None)
            if marker:
                delta=self.seconds(e.x)-self.seconds(origin)
                targets=[0,self.duration,playhead]+[r[k] for r in self.ranges for k in ('start','end')]+marker_boundaries([m for m in self.markers if m is not marker])
                step=self.frame_duration();last=max(0,math.ceil(self.duration/step-1e-6)-1)*step
                if mode=='body':
                    proposed=start+delta
                    if self.snap_enabled():
                        choices=[(abs(target-(proposed+offset)),target-offset) for offset in ((0,length) if length else (0,)) for target in targets if abs(self.x(target)-self.x(proposed+offset))<=10*self.unit]
                        if choices:proposed=min(choices,key=lambda value:value[0])[1]
                    new_start=min(max(0,self.duration-length if length else last),max(0,proposed))
                    new_length=length
                else:
                    anchor=start+length if mode=='start' else start
                    edge=start+length if mode=='end' else start
                    target=min(self.duration,max(0,self.snapped(edge+delta,targets)))
                    if mode=='start':target=min(target,anchor)
                    elif mode=='end':target=max(target,anchor)
                    new_start,new_finish=sorted((anchor,target));new_length=new_finish-new_start
                    if new_length<step*.5:new_start=min(last,anchor);new_length=0.
                if marker['time']!=new_start or marker_duration(marker)!=new_length:
                    marker['time']=new_start
                    if new_length:marker['duration']=new_length
                    else:marker.pop('duration',None)
                    if self.marker_changed:self.marker_changed(group)
                    else:self.draw()
            return
        if self.drag == 'seek':
            self.move_scrub(e.x)
            return
        elif self.drag:
            r, edge, origin, start, end = self.drag
            t = self.seconds(e.x)
            if edge == 'body':
                delta = min(self.duration-end, max(-start, t-origin))
                if self.snap_range and self.cut_points:
                    points=self.cut_points
                    first=min(range(len(points)),key=lambda i:abs(points[i]-start))
                    last=min(range(len(points)),key=lambda i:abs(points[i]-end))
                    span=last-first
                    target=min(range(len(points)),key=lambda i:abs(points[i]-(start+delta)))
                    target=max(0,min(len(points)-1-span,target))
                    r.update(start=points[target],end=points[target+span])
                else:r.update(start=start+delta,end=end+delta)
            else:
                r[edge] = min(t, r['end'] - .05) if edge == 'start' else max(t, r['start'] + .05)
            if self.snap_range and edge!='body':
                points=self.cut_points
                valid=[p for p in points if p<r['end']] if edge=='start' else [p for p in points if p>r['start']]
                if valid:r[edge]=min(valid,key=lambda p:abs(p-t))
            self.changed()
        self.draw()

    def left_up(self, e):
        if self.drag and self.drag[0]=='marker' and not self.marker_dragged:
            if self.marker_clicked:self.marker_clicked(self.selected_marker)
        if self.drag == 'seek':
            self.end_scrub(e.x)
        self.drag = None
        self.hover(e)

    def right_down(self, e):
        if not self.interaction_allowed():return
        self.right_selecting=False
        if self.marker_hit(e.x,e.y) or self.right_interacts_existing() and self.hit(e.x,e.y)[0]:
            self.ghost=self.right_origin=None;self.right_selecting=True;self.left_down(e);return 'break'
        self.focus_set()
        if self.duration and not self.scrubbing:
            self.right_origin = e.x
            self.ghost = (self.seconds(e.x), self.seconds(e.x))

    def right_move(self, e):
        if not self.interaction_allowed():return 'break'
        if self.right_selecting:self.left_move(e);return 'break'
        if self.ghost:
            self.ghost = self.ghost[0], self.seconds(e.x)
            self.draw()

    def right_up(self, e):
        if not self.interaction_allowed():self.cancel_interaction();return 'break'
        if self.right_selecting:
            self.right_selecting=False;self.left_up(e);return 'break'
        if self.ghost:
            a, b = sorted((self.ghost[0], self.seconds(e.x)))
            if self.snap_range:a,b=self.snap_range(a,b)
            if b - a >= .05 and self.right_origin is not None and abs(e.x-self.right_origin) >= 3:
                r = {'id': uuid.uuid4().hex, 'start': a, 'end': b, 'enabled': True}
                self.ranges.append(r)
                self.selected = r['id']
                self.changed()
                self.selected_callback(r['id'])
        self.ghost = None
        self.right_origin = None
        self.draw()

    def right_double(self, e):
        if not self.interaction_allowed():return 'break'
        self.right_selecting=False;self.drag=None
        marker=self.marker_hit(e.x,e.y)
        if marker:
            self.ghost=self.right_origin=None
            if self.marker_edit:self.marker_edit(marker['id'])
            return 'break'
        r, _ = self.hit(e.x, e.y)
        self.ghost, self.right_origin = None, None
        if r:
            self.ranges.remove(r)
            if self.selected == r['id']:
                self.selected = None
            self.changed()
        self.draw()
        self.hover(e)
        return 'break'

    def marker_hit(self,x,y):
        return self.marker_part(x,y)[0]

    def marker_part(self,x,y):
        if not abs(y-self.lane_geometry()[2])<=8*self.unit:return None,None
        hits=[]
        for marker in self.markers:
            left,right=self.x(marker['time']),self.x(marker_end(marker))
            if marker_duration(marker):
                if min(abs(x-left),abs(x-right))<=7*self.unit:
                    part='start' if abs(x-left)<=abs(x-right) else 'end';distance=min(abs(x-left),abs(x-right))
                elif left<=x<=right:part='body';distance=9
                else:continue
            elif abs(x-left)<=8*self.unit:part='body';distance=abs(x-left)
            else:continue
            hits.append((distance,marker['id']!=self.selected_marker,marker,part))
        if not hits:return None,None
        _,_,marker,part=min(hits,key=lambda hit:hit[:2]);return marker,part

    def marker_double(self,e):
        if not self.interaction_allowed():return 'break'
        marker=self.marker_hit(e.x,e.y)
        if marker and self.marker_edit:
            self.cancel_interaction();self.selected_marker=marker['id']
            self.marker_edit(marker['id']);return 'break'
