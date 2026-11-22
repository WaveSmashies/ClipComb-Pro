# SPDX-License-Identifier: GPL-3.0-or-later
"""Source bookmarks with a dedicated lane, editable notes and review Undo."""
import tkinter as tk
from tkinter import ttk
import uuid
import math
from review_theme import dialog, present
from review_help import Tooltip
from review_marker_colors import palette,slot,NAMES
from review_marker_ranges import duration as marker_duration,end as marker_end
from review_dialogs import own_variables


class Markers:
    def __init__(self, app):
        self.app = app
        timeline = app.timeline
        timeline.marker_edit = self.edit
        timeline.marker_changed = self.changed
        timeline.marker_clicked=self.jump
        timeline.marker_scrub_clicked=lambda ident:self.jump(ident,select=False)
        self.ids = []
        self.hovered_id=None
        self.tooltip=Tooltip(timeline,self.hover_text,position=self.tip_position,hold=self.dragging)
        timeline.bind('<ButtonPress-1>',self.drag_start,add='+')
        timeline.bind('<ButtonPress-3>',self.drag_start,add='+')
        timeline.bind('<ButtonRelease-1>',self.drag_end,add='+')
        timeline.bind('<ButtonRelease-3>',self.drag_end,add='+')
        timeline.bind('<Motion>',self.hover,add='+')
        timeline.bind('<B1-Motion>',self.hover,add='+')
        timeline.bind('<B3-Motion>',self.hover,add='+')

    def attach(self,parent):
        button=self.app.button(parent,'Bookmarks ▾',self.menu)
        button.pack(side='left',padx=5)
        Tooltip(button,lambda:self.app.action_tip('Add or edit a bookmark. Click to seek, double-click to edit its name, description and color. Drag to move it; Alt-drag a point left or right to make a bookmark range, then drag either end to resize without Alt. Bookmarks always accept left clicks. The magnet controls snapping while dragging.','marker'))

    def menu(self):
        app=self.app;colors=app.palette
        menu=tk.Menu(app.root,tearoff=False,bg=colors['input'],fg=colors['text'],
                     activebackground=colors['highlighted_clip'],activeforeground=colors['text'])
        binding=app.settings.data['shortcuts'].get('marker','')
        menu.add_command(label='Add / edit bookmark'+(' · '+binding if binding else ''),command=self.activate)
        if self.selected():
            menu.add_command(label='Edit selected bookmark…',command=self.edit)
            menu.add_command(label='Remove selected bookmark',command=self.remove)
        if app.timeline.markers:
            menu.add_separator()
            for marker in sorted(app.timeline.markers,key=lambda m:m['time']):
                menu.add_command(label=app.format_time(marker['time'])+'  '+marker['name'],
                                 command=lambda i=marker['id']:self.jump(i))
        x,y=app.root.winfo_pointerxy()
        try:menu.tk_popup(x,y)
        finally:menu.grab_release()

    def jump(self,marker_id,select=True):
        self.app.timeline.selected_marker=marker_id if select else None
        marker=next((m for m in self.app.timeline.markers if m['id']==marker_id),None)
        if marker:
            from review_export import frame,rate
            fps=rate(self.app.clip_fps());number=frame(marker['time'],fps)
            # Exact seeking returns the first presentation timestamp at or after
            # the target. Start at this displayed frame's half-frame boundary:
            # a container's fractional start offset must not land one frame late.
            target=max(0,(number-.5)/float(fps)+1e-7)
            self.app.seek(target);self.app.timeline.position=marker['time'];self.app.timeline.marker_seek_id=marker_id;self.app.timeline.draw()

    def hover(self,event):
        if self.dragging():
            if not self.tooltip.window:self.tooltip.show()
            self.tooltip.refresh();self.tooltip.position();return
        marker=self.app.timeline.marker_hit(event.x,event.y)
        marker_id=marker['id'] if marker else None
        if marker_id!=self.hovered_id:
            self.tooltip.hide();self.hovered_id=marker_id
            if marker:self.tooltip.enter()
        elif marker and not self.tooltip.window and not self.tooltip.timer:self.tooltip.enter()
        self.tooltip.refresh()

    def hover_text(self):
        marker=self.tooltip_marker()
        if not marker:return ''
        time=self.app.format_time(marker['time'])
        if marker_duration(marker):time+=' – '+self.app.format_time(marker_end(marker))
        return marker['name']+' · '+time+ ('\n'+marker['note'] if marker.get('note') else '')

    def dragging(self):
        drag=self.app.timeline.drag
        return bool(drag and drag[0]=='marker')

    def drag_marker(self):
        return next((m for m in self.app.timeline.markers if m['id']==self.app.timeline.selected_marker),None)

    def tooltip_marker(self):
        if self.dragging():return self.drag_marker()
        timeline=self.app.timeline
        x,y=timeline.winfo_pointerxy()
        return timeline.marker_hit(x-timeline.winfo_rootx(),y-timeline.winfo_rooty())

    def tip_position(self,bounds,size):
        marker=self.tooltip_marker()
        if not marker:return None
        from review_windows import client_rect
        timeline=self.app.timeline;left,top,right,bottom=client_rect(timeline);w,h=size
        center=left+timeline.x(marker['time']+marker_duration(marker)/2)
        pad=round(8*timeline.unit)
        return max(bounds[0]+pad,min(round(center-w/2),bounds[2]-w-pad)),max(bounds[1]+pad,top-h-pad)

    def drag_start(self,event):
        if self.dragging():
            self.tooltip.hide();self.hovered_id=self.app.timeline.selected_marker;self.tooltip.show()

    def drag_end(self,event):
        self.tooltip.hide();self.hovered_id=None

    def refresh(self):
        clip = self.app.clip()
        self.app.timeline.markers = clip.setdefault('markers', []) if clip else []
        self.app.timeline.marker_colors=palette(self.app.settings.data['bookmarks'])
        rows = sorted(self.app.timeline.markers, key=lambda m: (m['time'], m['id']))
        self.ids = [m['id'] for m in rows]

    def selected(self):
        return next((m for m in self.app.timeline.markers if m['id'] == self.app.timeline.selected_marker), None)

    def add(self):
        app = self.app
        if not app.clip() or app.busy or app.loading or not app.mixer or not app.mixer.ready:
            return
        from review_export import rate
        fps=float(rate(app.clip_fps()))
        position=min(max(0,math.ceil(app.timeline.duration*fps-1e-6)-1)/fps,round(app.timeline.position*fps)/fps)
        marker = {'id': uuid.uuid4().hex, 'time': max(0, position),
                  'name': f'Bookmark {len(app.timeline.markers) + 1}', 'note': '', 'color_slot':0}
        app.timeline.markers.append(marker)
        app.timeline.selected_marker = marker['id']
        self.changed()
        app.status.set('Bookmark added. Alt-drag it left or right to mark a span; double-click or press the bookmark shortcut again here to edit it.')

    def activate(self):
        app=self.app
        if app.busy or app.loading or not app.clip():return
        from review_export import frame,rate
        fps=rate(app.clip_fps());position=frame(app.timeline.position,fps)
        existing=next((m for m in app.timeline.markers if frame(m['time'],fps)==position),None)
        if existing:self.edit(existing['id'])
        else:self.add()

    def changed(self, group=None):
        self.app.changed(group=group, fields=('markers',))
        self.refresh()
        self.app.timeline.draw()

    def remove(self):
        marker = self.selected()
        if marker and not self.app.busy:
            self.app.timeline.markers.remove(marker)
            self.app.timeline.selected_marker = None
            self.changed()

    def edit(self, marker_id=None):
        if marker_id:
            self.app.timeline.selected_marker = marker_id
        marker = self.selected()
        if not marker or self.app.busy:
            return
        self.app.cancel_scrubbing()
        if self.app.mixer:self.app.mixer.set_pause(True)
        self.jump(marker['id'])
        window = dialog(self.app.root, 'Edit bookmark')
        page = ttk.Frame(window, padding=18)
        page.pack(fill='both', expand=True)
        ttk.Label(page, text='Name').pack(anchor='w')
        name = tk.StringVar(value=marker['name'])
        entry = ttk.Entry(page, textvariable=name, width=48)
        entry.pack(fill='x', pady=(3, 10))
        ttk.Label(page, text='Description').pack(anchor='w')
        description = tk.Text(page, height=6, width=48, wrap='word',
                              bg=self.app.palette['input'], fg=self.app.palette['text'],
                              insertbackground=self.app.palette['text'])
        description.insert('1.0', marker.get('note', ''))
        description.pack(fill='both', expand=True, pady=(3, 10))
        color_row=ttk.Frame(page);color_row.pack(fill='x',pady=(0,10))
        ttk.Label(color_row,text='Color').pack(side='left',padx=(0,9))
        chosen=tk.IntVar(value=slot(marker));colors=palette(self.app.settings.data['bookmarks'])
        color_buttons=[]
        def select_color(index):
            chosen.set(index)
            for i,button in enumerate(color_buttons):button.configure(relief='sunken' if i==index else 'flat')
        for i,color in enumerate(colors):
            button=tk.Button(color_row,bg=color,activebackground=color,width=2,height=1,bd=2,
                             relief='sunken' if i==chosen.get() else 'flat',command=lambda n=i:select_color(n))
            button.pack(side='left',padx=1);color_buttons.append(button)
            Tooltip(button,f'{i+1} · {NAMES[i]}\nThe numbered color identity is retained when exported, regardless of custom display colors.')
        buttons = ttk.Frame(page)
        buttons.pack(fill='x')
        def save():
            marker.update(name=name.get().strip() or 'Bookmark', note=description.get('1.0', 'end-1c'),color_slot=chosen.get())
            self.changed()
            window.destroy()
        self.app.button(buttons, 'Save marker', save, True).pack(side='right')
        self.app.button(buttons, 'Cancel', window.destroy).pack(side='right', padx=6)
        def delete():
            self.app.timeline.selected_marker=marker['id'];self.remove();window.destroy()
        self.app.button(buttons,'Delete bookmark',delete).pack(side='left')
        window.bookmark_controls={'name':name,'description':description,'color':chosen,'save':save,'delete':delete}
        own_variables(window,name,chosen)
        present(window, self.app.root)
        entry.focus_set()
