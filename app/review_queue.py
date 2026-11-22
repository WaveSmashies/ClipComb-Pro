# SPDX-License-Identifier: GPL-3.0-or-later
"""Virtual thumbnail grid and large status badges for the existing review queue."""
from collections import OrderedDict
from pathlib import Path
import math,shutil
from queue import Empty
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageDraw,ImageTk
from review_help import Tooltip
from review_thumbnails import Thumbnails

QUEUE_CATEGORIES=('All','Unused','Used','Kept','Deleted','Stars','Bookmarks','Marks')

def filtered_clips(clips,category,query=''):
    from review_marker_colors import slot
    result=[c for c in clips if (category=='All' or category in ('Marked','Marks') and c.get('ranges') or category=='Stars' and c.get('star') or category=='Bookmarks' and c.get('markers') or c['decision']==category) and query.casefold() in Path(c['path']).name.casefold()]
    if category in ('Stars','Bookmarks'):
        result.sort(key=lambda c:(slot(c['star'] if category=='Stars' else first_bookmark(c)),Path(c['path']).name.casefold(),c['id']))
    return result

def managed(clip):
    return bool(clip.get('ranges') or clip.get('markers') or clip.get('trim_ranges') or clip.get('provenance') or clip.get('trim_undone') or clip.get('decision')!='Unused')

def kinds_for(clip):
    flags = (('favorite','star'),('scissors','trimmed_by_clipcomb'),('chain','merged_by_clipcomb'),
             ('missing','missing'),('star','ranges'),('bookmark','markers'))
    return [kind for kind,field in flags if clip.get(field)]


def list_badge_layout(box, left_edge, count, scale):
    """Use filename space before shrinking a row's badges."""
    left, _, column_width, _ = box
    right = left + column_width
    available = max(0, right - left_edge)
    size = round(24*scale)
    gap = max(1,round(2*scale))
    total = count*size+(count-1)*gap
    if total > available:
        gap = 0
        size = min(size,available//count)
        total = count*size
    start = min(left+(column_width-total)//2,right-total)
    return start, size, size+gap

def first_bookmark(clip):
    return min(clip.get('markers',[]),key=lambda m:(m['time'],m['id']),default=None)

def activity_text(clip):
    lines=[]
    ranges=clip.get('ranges',[]);bookmarks=clip.get('markers',[]);trims=clip.get('trim_ranges',[])
    if bookmarks:lines.append(f"{len(bookmarks)} bookmark(s)")
    if ranges:lines.append(f"{len(ranges)} marked moment(s)")
    if trims:lines.append(f"{len(trims)} section(s) in the file trim plan")
    if clip.get('trimmed_by_clipcomb'):lines.append('Trimmed by ClipComb Pro')
    if clip.get('trim_undone'):lines.append('A trim was undone; the original was restored')
    if clip.get('merged_by_clipcomb'):lines.append('Merged by ClipComb Pro')
    if clip.get('provenance'):lines.append('Source footage mapping retained')
    if clip.get('decision')!='Unused':lines.append('Sorting decision: '+clip.get('decision','Unused'))
    return '\n'.join(lines) or 'No review changes.'

def symbol(root,kind,color,size=24):
    size=max(8,round(size*getattr(root._root(),'review_scale',1)))
    scale=4;picture=Image.new('RGBA',(size*scale,size*scale));draw=ImageDraw.Draw(picture)
    if kind=='star':
        for i in range(6):
            a=i*math.pi/3;draw.line((size*scale/2,size*scale/2,(.5+.37*math.cos(a))*size*scale,(.5+.37*math.sin(a))*size*scale),fill=color,width=4*scale)
    elif kind=='missing':
        for a,b in [((.23,.23),(.77,.77)),((.23,.77),(.77,.23))]:draw.line(tuple(v*size*scale for point in (a,b) for v in point),fill=color,width=4*scale)
    elif kind=='scissors':
        for box in ((.09,.62,.39,.92),(.61,.62,.91,.92)):
            draw.ellipse(tuple(v*size*scale for v in box),outline=color,width=2*scale)
        for a,b in [((.28,.67),(.79,.09)),((.72,.67),(.21,.09))]:
            draw.line(tuple(v*size*scale for point in (a,b) for v in point),fill=color,width=2*scale)
    elif kind=='chain':
        for box in ((.12,.37,.59,.73),(.41,.27,.88,.63)):
            draw.rounded_rectangle(tuple(v*size*scale for v in box),radius=.14*size*scale,outline=color,width=3*scale)
        draw.line((.4*size*scale,.56*size*scale,.6*size*scale,.44*size*scale),fill=color,width=3*scale)
    elif kind=='favorite':
        draw.polygon([((.5+(.4 if i%2==0 else .18)*math.cos(-math.pi/2+i*math.pi/5))*size*scale,(.5+(.4 if i%2==0 else .18)*math.sin(-math.pi/2+i*math.pi/5))*size*scale) for i in range(10)],fill=color)
    elif kind=='bookmark':
        draw.polygon([(x*size*scale,y*size*scale) for x,y in ((.5,.14),(.86,.5),(.5,.86),(.14,.5))],fill=color)
    elif kind=='grid':
        for x in (.12,.56):
            for y in (.12,.56):draw.rectangle((x*size*scale,y*size*scale,(x+.32)*size*scale,(y+.32)*size*scale),fill=color)
    elif kind=='list':
        for y in (.2,.48,.76):
            draw.rectangle((.1*size*scale,y*size*scale,.65*size*scale,(y+.09)*size*scale),fill=color)
            draw.ellipse((.8*size*scale,y*size*scale,.9*size*scale,(y+.1)*size*scale),fill=color)
    return ImageTk.PhotoImage(picture.resize((size,size),Image.Resampling.LANCZOS),master=root)

class QueueView:
    def __init__(self,app,parent,controls,scrollbar,tree=None):
        self.app,self.parent,self.tree,self.scrollbar=app,parent,tree or app.tree,scrollbar
        self.mode=app.settings.data['app'].get('queue_view','List');self.clips=[];self.clip_by_id={};self.row_ids=();self.display_badges={};self.photos=OrderedDict();self.failed=set();self.overlays=[];self.images={};self.timer=None
        from review_thumb_pool import ThumbnailPool
        if not hasattr(app,'thumb_pool') or app.thumb_pool.closed:app.thumb_pool=ThumbnailPool(app)
        self.pool=app.thumb_pool;self.pool.clients.add(self);self.thumbnails=self.pool.service;self.photos=self.pool.photos;self.failed=self.pool.failed
        self.wanted=set();self.visible_keys=set();self.variants=set()
        self.tree.bind('<FocusIn>',lambda e:setattr(app,'active_queue',self),add='+')
        self.canvas=tk.Canvas(parent,highlightthickness=0,takefocus=True);self.grid_scroll=ttk.Scrollbar(parent,orient='vertical',command=self.scroll,style='Queue.Vertical.TScrollbar')
        from review_render import FrameUpdate
        self.resize_update=FrameUpdate(self.canvas,self.draw)
        self.canvas.configure(yscrollcommand=self.grid_scroll.set);self.canvas.bind('<Configure>',self.resize_update.request);self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Button-1>',self.clicked);self.canvas.bind('<Button-3>',self.context);self.canvas.bind('<Motion>',self.hover)
        self.hover_id=None;self.tip=Tooltip(self.canvas,lambda:self.help(self.hover_id) if self.hover_id else '')
        self.toggle_button=ttk.Button(controls,style='Panel.Round.TButton',command=self.toggle_mode,takefocus=True)
        self.toggle_button.pack(side='left',padx=(3,0));self.buttons={'mode':self.toggle_button}
        Tooltip(self.toggle_button,lambda:self.mode+' view · Click to switch to '+('List' if self.mode=='Grid' else 'Grid')+' view')
        app.shortcut_tags(self.canvas)
        self.link_hovered=None;self.link_tip=Tooltip(self.tree,self.link_help)
        self.tree.bind('<Motion>',self.link_hover,add='+')
        self.tree.bind('<Configure>',lambda e:self.schedule_badges(),add='+')
        self.tree.bind('<Map>',lambda e:self.schedule_badges(),add='+')
        self.tree.configure(yscrollcommand=self.list_scroll)
        self.apply_theme()
    def link_hover(self,event):
        ident=self.tree.identify_row(event.y) if self.tree.identify_column(event.x)=='#1' else None
        if ident!=self.link_hovered:
            self.link_tip.hide();self.link_hovered=ident
            if ident and self.link_help():self.link_tip.enter()

    def link_help(self):
        group=getattr(getattr(self.app,'cleanup',None),'visible_groups',{}).get(self.link_hovered)
        if not group or not self.app.project:return ''
        number,members=group;records={clip['id']:clip for clip in self.app.project.data['clips']}
        hidden=sum(ident not in self.clip_by_id for ident in members)
        return f'Overlap Group {number} · {len(members)} Clips'+(f' · {hidden} outside this queue filter' if hidden else '')+'\n'+'\n'.join(records[ident]['path'] for ident in members if ident in records)

    def help(self,clip_id,kind=None):
        clip=self.clip_by_id.get(clip_id)
        if not clip:return ''
        if kind=='favorite' or kind is None and getattr(self,'hover_kind',None)=='favorite':
            from review_stars import tooltip
            return tooltip(clip,self.app.timeline.marker_colors,self.app.settings.data['bookmarks'])
        if kind=='bookmark' or kind is None and getattr(self,'hover_kind',None)=='bookmark':
            marker=first_bookmark(clip)
            return 'Bookmarks: '+str(len(clip.get('markers',[])))+('\nFirst: '+marker.get('name','Bookmark') if marker else '')
        if kind=='scissors' or kind is None and getattr(self,'hover_kind',None)=='scissors':return 'This clip was trimmed by ClipComb Pro.'
        if kind=='chain' or kind is None and getattr(self,'hover_kind',None)=='chain':return 'This clip was merged by ClipComb Pro.'
        if kind=='star' or kind is None and getattr(self,'hover_kind',None)=='star':return f"Marked moments: {len(clip.get('ranges',[]))}"
        if clip.get('missing'):return 'This clip cannot be found in the last folder ClipComb Pro managed it in.\n'+(self.app.shortcut_hint('remove_range') or 'Delete / Backspace')+' to remove it from the queue.'
        return activity_text(clip)
    def apply_theme(self):
        palette=self.app.palette;self.canvas.configure(bg=palette['panel'])
        self.tree.tag_configure('comparison',background=palette['highlighted_clip'],foreground=palette['text'])
        scale=getattr(self.app.root,'review_scale',1)
        self.tree.column('activity',width=round(84*scale),minwidth=round(84*scale),stretch=False)
        root=self.app.root;key=(palette['text'],palette['highlighted_button'],scale)
        if getattr(root,'review_symbol_key',None)!=key:
            root.review_symbol_key=key
            root.review_symbols={name:symbol(root,name,palette['text'] if name in ('star','missing','chain','scissors') else palette['highlighted_button']) for name in ('star','missing','chain','scissors','grid','list')}
        self.images=root.review_symbols
        self.update_mode_button()
        if self.mode=='Grid':self.draw()
        else:self.sync_badge_colors(refresh_images=True);self.schedule_badges()
    def badge_image(self,clip,kind,size=None):
        scale=getattr(self.app.root,'review_scale',1)
        usual_size=round(24*scale)
        size=usual_size if size is None else size
        if kind not in ('bookmark','favorite'):
            if size==usual_size:return self.images[kind]
            color=self.app.palette['text']
        else:
            from review_marker_colors import slot
            color=self.app.timeline.marker_colors[slot(clip['star'] if kind=='favorite' else first_bookmark(clip))]
        key=(kind,color,scale,size)
        root=self.app.root
        if not isinstance(getattr(root,'bookmark_badges',None),OrderedDict):root.bookmark_badges=OrderedDict(getattr(root,'bookmark_badges',{}))
        if key not in root.bookmark_badges:
            root.bookmark_badges[key]=symbol(root,kind,color,size/scale)
            # Widgets retain the pictures they actually display. Eviction only
            # drops reusable cache entries, never a live widget's last reference.
            while len(root.bookmark_badges)>64:root.bookmark_badges.popitem(last=False)
        root.bookmark_badges.move_to_end(key)
        return root.bookmark_badges[key]

    def update_mode_button(self):
        target='List' if self.mode=='Grid' else 'Grid'
        picture=self.images[target.lower()]
        self.toggle_button.configure(image=picture,text=target,compound='image',style='Panel.Round.TButton',padding=(4,3))
        self.toggle_button.review_image=picture
    def toggle_mode(self):self.set_mode('List' if self.mode=='Grid' else 'Grid')
    def set_mode(self,name):
        self.mode=name
        if self==getattr(self.app,'queue_view',None):self.app.settings.data['app']['queue_view']=name;self.app.settings.save()
        self.show(self.clips);self.apply_theme()
    def show(self,clips):
        self.clips=list(clips)
        self.clip_by_id={clip['id']:clip for clip in self.clips};self.row_ids=tuple(self.clip_by_id)
        # Rebuild every displayed link label when filtering/sorting changes, not
        # only when a new scan is loaded. Hidden peers must not look like a pair.
        cleanup=getattr(self.app,'cleanup',None)
        for clip in self.clips:
            if not self.tree.exists(clip['id']):continue
            group=getattr(cleanup,'visible_groups',{}).get(clip['id']) if cleanup else None
            prefix=''
            if group:
                number,members=group;visible=[ident for ident in members if ident in self.clip_by_id]
                if len(visible)==1:prefix=f'↔ [{number} · 1/{len(members)}] '
                else:prefix=('┏ ' if clip['id']==visible[0] else '┗ ' if clip['id']==visible[-1] else '┃ ')+f'[{number}] '
            self.tree.set(clip['id'],'clip',prefix+Path(clip['path']).name)
        self.update_mode_button()
        if self.mode=='Grid':
            self.hide_badges()
            self.tree.pack_forget();self.scrollbar.pack_forget()
            self.canvas.pack_forget();self.grid_scroll.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True);self.draw()
        else:
            self.canvas.delete('all');self.display_badges.clear()
            self.canvas.pack_forget();self.grid_scroll.pack_forget();self.wanted=set();self.visible_keys=set();self.variants=set();self.pool.wanted()
            if not self.tree.winfo_manager():
                self.scrollbar.pack(side='right',fill='y');self.tree.pack(side='left',fill='both',expand=True)
            self.schedule_badges()
    def list_scroll(self,*args):self.scrollbar.set(*args);self.schedule_badges()
    def hide_badge(self,overlay):
        overlay.place_forget();overlay.configure(image='');overlay.review_image=None
    def hide_badges(self):
        for overlay in self.overlays:self.hide_badge(overlay)
    def sync_badge_colors(self,refresh_images=False):
        if self.mode!='List':return
        selected=set(self.tree.selection());colors={}
        for overlay in self.overlays:
            clip_id=getattr(overlay,'clip_id',None)
            if not clip_id or not overlay.winfo_manager() or not self.tree.exists(clip_id):continue
            if clip_id not in colors:
                highlighted=clip_id in selected or 'comparison' in self.tree.item(clip_id,'tags')
                colors[clip_id]=self.app.palette['highlighted_clip' if highlighted else 'panel']
            color=colors[clip_id]
            if refresh_images:
                clip=self.clip_by_id.get(clip_id)
                if not clip or overlay.kind not in kinds_for(clip):self.hide_badge(overlay);continue
                picture=self.badge_image(clip,overlay.kind,overlay.badge_size)
                overlay.configure(image=picture,bg=color);overlay.review_image=picture
            elif str(overlay.cget('bg'))!=color:overlay.configure(bg=color)
    def schedule_badges(self):
        if self.timer or self.mode!='List':return
        self.timer=self.app.root.after_idle(self.badges)
    def badges(self):
        self.timer=None
        if self.mode!='List' or not self.tree.winfo_viewable():
            self.hide_badges()
            return
        ids=self.row_ids
        if not ids:self.hide_badges();return
        start=min(len(ids)-1,int(self.tree.yview()[0]*len(ids)))
        rowheight=int(ttk.Style(self.tree).lookup('Treeview','rowheight') or 31)
        visible=ids[start:start+max(1,self.tree.winfo_height()//rowheight+2)]
        index=0;by_id=self.clip_by_id;selected_ids=set(self.tree.selection());scale=getattr(self.app.root,'review_scale',1)
        for clip_id in visible:
            clip=by_id.get(clip_id)
            if not clip or not self.tree.exists(clip_id):continue
            kinds=kinds_for(clip)
            if not kinds:continue
            box=self.tree.bbox(clip_id,'activity')
            if not box:continue
            start,size,step=list_badge_layout(box,2,len(kinds),scale)
            if size<8:continue
            selected=clip_id in selected_ids or 'comparison' in self.tree.item(clip_id,'tags')
            for slot,kind in enumerate(kinds):
                if index==len(self.overlays):
                    overlay=tk.Label(self.tree,bd=0,cursor='hand2');self.overlays.append(overlay)
                    overlay.bind('<Button-1>',lambda e,o=overlay:self.select(o.clip_id));overlay.bind('<MouseWheel>',lambda e:self.tree.yview_scroll(-int(e.delta/120),'units'))
                    overlay.tooltip=Tooltip(overlay,lambda o=overlay:self.help(o.clip_id,o.kind))
                overlay=self.overlays[index];overlay.clip_id=clip_id;overlay.kind=kind;overlay.badge_size=size
                picture=self.badge_image(clip,kind,size)
                overlay.configure(image=picture,bg=self.app.palette['highlighted_clip' if selected else 'panel']);overlay.review_image=picture
                overlay.place(x=start+slot*step,y=box[1]+(box[3]-size)//2,width=size,height=size);index+=1
        for overlay in self.overlays[index:]:self.hide_badge(overlay)
    def refresh_status(self):
        if self.mode=='Grid':self.draw()
        else:self.sync_badge_colors();self.schedule_badges()
    def geometry(self):
        width=max(48,self.canvas.winfo_width()-16)
        target=max(48,min(1200,int(self.app.settings.data['thumbnails']['size'])))
        columns=max(1,int(width//target));cell=width/columns
        return columns,cell,int(max(28,(cell-14)*9/16)+76)
    def grid_extent(self,columns,height):
        content_height=math.ceil(len(self.clips)/columns)*height+16
        return max(self.canvas.winfo_height(),content_height)
    def at(self,x,y):
        columns,width,height=self.geometry();column=int((x-8)//width);row=int((self.canvas.canvasy(y)-8)//height);index=row*columns+column
        return self.clips[index] if 0<=column<columns and 0<=index<len(self.clips) else None
    def select(self,clip_id):
        self.app.active_queue=self
        if self.app.cleanup.select_member(clip_id):self.sync_badge_colors();return
        if self.tree.selection()!=(clip_id,):self.tree.selection_set(clip_id)
        self.sync_badge_colors()
        self.tree.focus(clip_id);self.canvas.focus_set() if self.mode=='Grid' else self.tree.focus_set()
        if self.app.current_id!=clip_id:self.app.load_clip(clip_id)
        self.refresh_status()
    def reveal(self,clip_id):
        if self.mode=='Grid':
            index=next((i for i,c in enumerate(self.clips) if c['id']==clip_id),None)
            if index is not None:
                columns,_,height=self.geometry();y=(index//columns)*height;top=self.canvas.canvasy(0);visible=self.canvas.winfo_height();total=self.grid_extent(columns,height)
                if y<top:self.canvas.yview_moveto(y/total)
                elif y+height>top+visible:self.canvas.yview_moveto(max(0,y+height-visible)/total)
        self.refresh_status()
    def clicked(self,event):
        clip=self.at(event.x,event.y)
        if clip:self.select(clip['id'])
    def context(self,event):
        clip=self.at(event.x,event.y)
        if clip:self.app.clip_context_menu(event,clip['id'])
    def hover(self,event):
        clip=self.at(event.x,event.y);columns,width,height=self.geometry();local_x=(event.x-8)%width;local_y=(self.canvas.canvasy(event.y)-8)%height
        middle=(width-7)/2;kinds=kinds_for(clip) if clip else []
        slot=int((local_x-middle+len(kinds)*13)//26)
        status=clip and 0<=slot<len(kinds) and height-38<local_y<height-8
        kind=kinds[slot] if status else 'status'
        selected=clip['id'] if status else None
        if (selected,kind)!=(self.hover_id,getattr(self,'hover_kind',None)):
            self.tip.hide();self.hover_id=selected;self.hover_kind=kind
            if selected:self.tip.enter()
    def highlighted(self,clip_id):
        cleanup=getattr(self.app,'cleanup',None)
        return clip_id==self.app.current_id or bool(cleanup and cleanup.highlighted(clip_id))
    def scroll(self,*args):self.canvas.yview(*args);self.draw()
    def wheel(self,event):
        if event.state&4:
            cfg=self.app.settings.data['thumbnails'];size=int(cfg['size']);cfg['size']=str(max(48,min(1200,round(size*(1.12 if event.delta>0 else 1/1.12)))))
            self.app.settings.save()
            for view in tuple(self.pool.clients):view.draw()
        else:self.canvas.yview_scroll(-int(event.delta/120),'units');self.draw()
        return 'break'
    def draw(self):
        if self.mode!='Grid':return
        canvas=self.canvas;canvas.delete('all');self.display_badges.clear();columns,width,height=self.geometry();image_w=max(24,int(width-20));image_h=max(20,int((width-20)*9/16))
        canvas.configure(scrollregion=(0,0,max(1,canvas.winfo_width()),self.grid_extent(columns,height)))
        row=max(0,int(canvas.canvasy(0)//height));end_row=int((canvas.canvasy(0)+canvas.winfo_height())//height)+1
        first=max(0,row-1)*columns;last=min(len(self.clips),(end_row+1)*columns)
        prefirst=max(0,row-3)*columns;prelast=min(len(self.clips),(end_row+4)*columns)
        palette=self.app.palette;wanted=set();visible_keys=set();variants=set();keys={};requests=[]
        decoder=self.pool.decoder()
        for i in range(prefirst,prelast):
            clip=self.clips[i]
            if clip.get('missing') or not self.app.project:continue
            path=self.pool.checked_path(self.app.project,clip['path']);key=self.thumbnails.key(path,clip['identity']);keys[i]=key;wanted.add(key)
            if first<=i<last:visible_keys.add(key);variants.add((key,image_w,image_h))
            if key not in self.pool.raw and key not in self.failed:requests.append((first<=i<last,key,path,(clip.get('media') or {}).get('duration',0)))
        self.wanted,self.visible_keys,self.variants=wanted,visible_keys,variants;self.pool.wanted()
        for visible,key,path,duration in sorted(requests,key=lambda r:r[0]):self.thumbnails.request(key,path,decoder,duration)
        if requests:self.pool.request_updates()
        for i in range(first,last):
            clip=self.clips[i];x=8+(i%columns)*width;y=8+(i//columns)*height;selected=self.highlighted(clip['id'])
            canvas.create_rectangle(x,y,x+width-7,y+height-7,fill=palette['highlighted_clip' if selected else 'panel'],outline=palette['selection'] if selected else palette['border'])
            key=keys.get(i);photo=self.pool.photo(key,image_w,image_h) if key else None
            if photo:canvas.create_image(x+(width-7)/2,y+8+image_h/2,image=photo)
            else:
                canvas.create_rectangle(x+6,y+6,x+width-13,y+image_h+10,fill=palette['video_background'],outline='')
                canvas.create_text(x+(width-7)/2,y+8+image_h/2,text='×' if clip.get('missing') else '▶',fill=palette['muted_text'],font=('Segoe UI',max(9,min(22,image_h//3))))
            title=Path(clip['path']).name;limit=max(9,int((width-18)/6)*2)
            if len(title)>limit:title=title[:limit-1]+'…'
            canvas.create_text(x+(width-7)/2,y+image_h+14,text=title,anchor='n',width=width-18,fill=palette['text'],font=('Segoe UI',9))
            kinds=kinds_for(clip)
            for slot,kind in enumerate(kinds):
                picture=self.badge_image(clip,kind);self.display_badges[str(picture)]=picture
                canvas.create_image(x+(width-7)/2+(slot-(len(kinds)-1)/2)*26,y+height-22,image=picture,tags=(kind,))
            cleanup=getattr(self.app,'cleanup',None);group=getattr(cleanup,'visible_groups',{}).get(clip['id']) if cleanup else None
            if group:
                number=group[0];color=palette['highlighted_button']
                canvas.create_line(x+13,y+4,x+3,y+4,x+3,y+height-11,x+13,y+height-11,fill=color,width=4,tags=('overlap-link',))
                canvas.create_rectangle(x+8,y+7,x+105,y+27,fill=palette['panel'],outline='',tags=('overlap-link',))
                canvas.create_text(x+13,y+17,text=f'Overlap group {number}',anchor='w',fill=color,font=('Segoe UI',9,'bold'),tags=('overlap-link',))
        self.pool.trim()
    def poll(self):pass
    def close(self):
        if self.timer:self.app.root.after_cancel(self.timer)
        self.hide_badges();self.overlays.clear();self.canvas.delete('all');self.display_badges.clear()
        self.toggle_button.configure(image='');self.toggle_button.review_image=None
        self.pool.remove(self)
    def suspend(self):self.pool.pause()
    def resume(self):self.pool.resume()
