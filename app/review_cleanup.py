# SPDX-License-Identifier: GPL-3.0-or-later
"""Integrated overlap comparison and explicit, verified file trimming."""
import copy
import csv
from datetime import datetime
import json
from pathlib import Path
from queue import Queue,Empty
import shutil
import threading
import time
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import uuid

from review_core import file_identity
from review_player import find_mpv
from review_help import badge,check
from review_theme import confirm_action,show_error,dialog,present
from review_overlap_audit import audit,probe,video_alignment,RECOVERY_FOLDER
from review_cleanup_core import archive_clip
from review_cleanup_comparison import CompareView,Pane,CLIP_COLORS
from review_file_trim import cut_points,snap_keep,create_trim,install_new_copies,remap_annotations
from review_trim_install import install as replace_trim,backup_path
from review_cancel import ScanCancelled


class Cleanup:
    def __init__(self,app):
        self.app=app;self.mode='review';self.compare=None;self.points=[]
        self.groups=[];self.group_by_id={};self.layout=[];self.page=0
        self.events=Queue();self.worker=None;self.pending=None;self.scan_root=None
        self.scan_cancel=threading.Event()
        self.scanning=False;self.scan_worker=None;self.scan_events=Queue();self.scan_serial=0;self.resume_scan_root=None
        self.last_activity=time.monotonic();self.scan_progress='Starting scan…'
        self.notice=None;self.selected_id=None;self.compare_sashes=None
        cfg=app.settings.data['trimming']
        self.join=tk.BooleanVar(value=cfg.getboolean('join_sections'))
        self.replace=tk.BooleanVar(value=cfg.getboolean('replace_original'))
        self.label=tk.StringVar(value='Overlap scan runs only when requested.')
        bar=ttk.Frame(app.main_panel);self.bar=bar
        bar.pack(fill='x',before=app.main_stack,pady=(0,6))
        self.mode_buttons={}
        for mode,text,command in [('review','Review',self.review),('compare','Compare overlaps',self.compare_group),('trim','Trim file',self.trim_mode)]:
            button=app.button(bar,text,command);button.pack(side='left',padx=(0,5));self.mode_buttons[mode]=button
        self.set_mode('review')
        app.markers.attach(bar)
        app.button(bar,'Scan overlaps',self.scan).pack(side='right',padx=5)
        self.archive_button=app.button(bar,'Archive tools…',self.archive);self.archive_button.pack(side='right')
        from review_spinner import Spinner
        self.scan_meter=ttk.Progressbar(bar,length=120,mode='determinate',maximum=100)
        self.spinner=Spinner(bar)
        self.bottom_scan=ttk.Frame(bar)
        self.bottom_meter=ttk.Progressbar(self.bottom_scan,length=90,mode='determinate',maximum=100);self.bottom_meter.pack(side='right',padx=6)
        self.bottom_spinner=Spinner(self.bottom_scan);self.bottom_spinner.pack(side='right')
        self.scan_status=tk.StringVar();self.scan_note=ttk.Label(self.bottom_scan,textvariable=self.scan_status,style='Hint.TLabel',anchor='e')
        from review_help import Tooltip
        Tooltip(self.scan_note,lambda:self.scan_status.get())
        self.cancel_scan_button=app.button(self.bottom_scan,'Stop Scan',self.pause_scan)
        self.archive_badge=badge(bar,'Review edits moments for your video editor. Compare overlaps aligns clips using matching encoded packets. Trim file makes verified lossless copies at valid keyframe boundaries. Archive tools preserves the full audit, batch-copy, merge and recoverable cleanup workflow.\n\nDefault: Review; no scan starts automatically.');self.archive_badge.pack(side='right')
        self.options=ttk.Frame(app.main_panel)
        self.hint=ttk.Label(self.options,textvariable=self.label,style='Hint.TLabel',wraplength=850)
        self.hint.pack(anchor='w')
        self.trim_options=ttk.Frame(self.options)
        check(self.trim_options,'Join kept sections',self.join,
              'Join all enabled keep regions into one verified file. Turn off to create one file per region. All audio streams are retained. Container priming can add a short hold at each join; the confirmation reports it.\n\nDefault: On.',command=self.save_options).pack(side='left')
        app.button(self.trim_options,'Trim video',self.render_trim,True).pack(side='right')
        self.compare_options=ttk.Frame(self.options)
        app.button(self.compare_options,'Next linked clips',self.next_page).pack(side='left')
        app.button(self.compare_options,'Merge group…',self.merge).pack(side='left',padx=6)
        self.clip_delete_options=ttk.Frame(self.options)
        self.comparison_members=[]

    def save_options(self):
        self.app.settings.data['trimming'].update(join_sections='yes' if self.join.get() else 'no',
                                                replace_original='yes' if self.replace.get() else 'no')
        self.app.settings.save()

    def tools(self):
        result={};base=self.app.settings.path.parent
        for name in ('ffmpeg','ffprobe'):
            path=self.app.settings.data['tools'][name] or (base/f'player/{name}.exe')
            if not Path(path).is_file():path=shutil.which(name)
            if not path:raise ValueError(f'Set {name} in Settings → Playback before using file tools.')
            result[name]=str(path)
        return result

    def library(self):
        return find_mpv(self.app.settings.path.parent,self.app.settings.data['tools']['mpv_library'])

    def work(self):
        path=self.app.settings.path.parent/'Cleanup Work'
        path.mkdir(exist_ok=True)
        if self.app.project:
            import hashlib
            key=hashlib.sha256(str(self.app.project.root).casefold().encode()).hexdigest()[:16]
            path/=key;path.mkdir(exist_ok=True)
        return path

    def job(self,worker,done,onerror=None):
        if self.app.busy:return
        if self.scanning:
            self.resume_scan_root=self.app.project.root
            if not self.pause_scan(wait=True):return
        self.app.busy=True;self.pending=done;self.pending_error=onerror
        self.app.queue_view.suspend()
        self.spinner.pack(side='right',padx=6);self.spinner.start(12)
        def run():
            try:self.events.put(('done',worker()))
            except ScanCancelled:self.events.put(('cancelled',None))
            except Exception as error:self.events.put(('error',str(error)))
        self.worker=threading.Thread(target=run,daemon=True);self.worker.start()

    def progress(self,text):self.events.put(('progress',text))

    def poll(self):
        self.scan_priority()
        self.poll_scan()
        while True:
            try:kind,value=self.events.get_nowait()
            except Empty:return
            if kind=='progress':self.app.status.set(value);self.label.set(value)
            else:
                done=self.pending;failed=getattr(self,'pending_error',None);self.pending=None;self.pending_error=None;self.app.busy=False
                self.spinner.stop();self.spinner.pack_forget()
                self.cancel_scan_button.pack_forget()
                if kind=='cancelled':self.app.status.set('Scan canceled. Original recordings were not changed.')
                elif kind=='error':
                    self.clear_notice()
                    if failed:failed()
                    self.app.status.set(value);show_error(self.app.root,'File tools',value)
                elif done:
                    try:done(value)
                    except Exception as error:
                        self.clear_notice()
                        self.app.status.set(str(error));show_error(self.app.root,'File tools',str(error))
                if not self.app.busy:self.app.queue_view.resume()
                if not self.app.busy and self.resume_scan_root:
                    root=self.resume_scan_root;self.resume_scan_root=None
                    if self.app.project and self.app.project.root==root:self.scan()

    def pause_scan(self,wait=False):
        if not self.scanning:return True
        self.scan_cancel.set();self.scan_status.set('Stopping… completed results are saved')
        if wait and self.scan_worker:
            self.scan_worker.join(timeout=3)
            if self.scan_worker.is_alive():self.app.status.set('Waiting for the scan to stop. Try again shortly.');return False
            self.poll_scan()
        return True

    def activity(self):
        self.last_activity=time.monotonic()
        if self.scanning:self.scan_cancel.background=True

    def scan_priority(self):
        if not self.scanning:return
        app=self.app
        playing=(app.mixer and app.mixer.active and not app.mixer.paused) or (self.compare and self.compare.playing)
        if playing or app.timeline.drag or (hasattr(app,'magnifier') and app.magnifier.active):self.last_activity=time.monotonic()
        self.scan_cancel.background=time.monotonic()-self.last_activity<5
        self.update_scan_note()

    def update_scan_note(self):
        mode='Stopping' if self.scan_cancel.is_set() else 'Review priority' if self.scan_cancel.background else 'Full speed'
        from review_scan_feedback import display
        text,_=display(self.scan_progress,mode)
        if self.scan_status.get()!=text:self.scan_status.set(text)

    def poll_scan(self):
        while True:
            try:ticket,kind,value=self.scan_events.get_nowait()
            except Empty:return
            if ticket!=self.scan_serial:continue
            if kind=='progress':
                self.scan_progress=value;self.update_scan_note()
                import re
                match=re.search(r'(Indexed|Compared) (\d+)/(\d+)',value)
                if match:
                    fraction=int(match[2])/max(1,int(match[3]));amount=70*fraction if match[1]=='Indexed' else 70+29*fraction
                    self.scan_meter['value']=amount;self.bottom_meter['value']=amount
                continue
            self.scan_meter.pack_forget();self.bottom_scan.pack_forget();self.bottom_spinner.stop()
            self.scanning=False;self.cancel_scan_button.pack_forget();self.scan_note.pack_forget()
            if not self.app.busy:self.spinner.stop();self.spinner.pack_forget()
            if kind=='done' and self.app.project is self.scan_project:
                self.app.project.data['overlap_report']=str(value);self.app.project.dirty=True;self.read_groups(value)
                import hashlib
                key=hashlib.sha256(str(self.app.project.root).casefold().encode()).hexdigest()[:16]
                if 'overlap_reports' not in self.app.settings.data:self.app.settings.data['overlap_reports']={}
                self.app.settings.data['overlap_reports'][key]=str(value);self.app.settings.save()
                self.app.status.set(f'Found {len(self.groups)} linked overlap groups. Links appear in both List and Grid views.')
            elif kind=='cancelled':self.app.status.set('Scan canceled. Completed clip indexes and comparisons are saved; Scan overlaps resumes them.')
            elif kind=='error':self.app.status.set('Overlap scan stopped: '+str(value))

    def update_group_visibility(self):
        active={c['id'] for c in self.app.project.data['clips'] if c['decision']!='Deleted' and not c.get('missing')} if self.app.project else set()
        self.visible_groups={}
        for number,group in enumerate(self.groups,1):
            members=[i for i in group if i in active]
            if len(members)>1:
                for ident in members:self.visible_groups[ident]=(number,members)

    def prefix(self,clip_id):
        value=getattr(self,'visible_groups',{}).get(clip_id)
        if not value:return ''
        number,group=value
        return ('┏ ' if clip_id==group[0] else '┗ ' if clip_id==group[-1] else '┃ ')+f'[{number}] '

    def saved_report(self):
        if not self.app.project:return None
        import hashlib
        key=hashlib.sha256(str(self.app.project.root).casefold().encode()).hexdigest()[:16]
        candidates=[self.app.settings.data.get('overlap_reports',key,fallback=''),self.app.project.data.get('overlap_report')]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():return candidate
        reports=sorted(self.work().glob('overlaps-*.csv'),key=lambda p:p.stat().st_mtime,reverse=True)
        return reports[0] if reports else None

    def ready(self):
        return self.app.project and self.app.clip() and not self.app.busy and not self.app.loading

    def before_load(self):
        if self.mode!='review':self.review(notify=False)

    def highlighted(self,clip_id):
        return self.mode=='compare' and any(row[0]==clip_id for row in self.layout)

    def select_member(self,clip_id):
        if not self.highlighted(clip_id):return False
        self.selected_id=clip_id
        for view in tuple(self.app.thumb_pool.clients):
            if view.tree.exists(clip_id) and view.tree.selection()!=(clip_id,):view.tree.selection_set(clip_id)
            view.refresh_status()
        self.app.status.set('Selected overlap clip: '+Path(self.selected_clip()['path']).name)
        return True

    def selected_clip(self):
        return next((c for c in self.app.project.data['clips'] if c['id']==self.selected_id),self.app.clip())

    def clear_notice(self):
        if self.notice:self.notice.close();self.notice=None

    def comparison_layout(self,enabled):
        app=self.app
        if enabled:
            app.remember_layout()
            self.compare_sashes=(app.main_stack.sashpos(0),app.left_stack.sashpos(0))
            app.main_stack.forget(app.timeline_panel);app.left_stack.forget(app.moments_panel)
        elif self.compare_sashes is not None:
            positions=self.compare_sashes;self.compare_sashes=None
            app.main_stack.add(app.timeline_panel,weight=2);app.left_stack.add(app.moments_panel,weight=1)
            def restore():
                if not self.app.closed and self.mode!='compare':
                    app.main_stack.sashpos(0,positions[0]);app.left_stack.sashpos(0,positions[1])
            app.root.update_idletasks();restore();app.root.after(40,restore)

    def review(self,notify=True):
        if self.app.busy:return
        if self.mode=='review':return
        self.mode='review';self.options.pack_forget();self.trim_options.pack_forget();self.compare_options.pack_forget();self.clip_delete_options.pack_forget()
        self.selected_id=None;self.clear_notice()
        if self.app.clip():self.app.current_title.set(Path(self.app.clip()['path']).name)
        if self.compare:
            self.compare.close();self.compare.destroy();self.compare=None
            self.app.video_frame.pack(fill='both',expand=True)
            self.app.transport.pack(side='bottom',fill='x',pady=(5,0),before=self.app.video_frame)
        self.comparison_layout(False)
        self.app.timeline.cut_points=[];self.app.timeline.snap_range=None
        if self.app.clip():self.app.timeline.ranges=self.app.clip()['ranges']
        self.app.refresh_ranges();self.app.timeline.draw()
        self.set_mode('review')
        self.app.populate()
        if notify:self.app.status.set('Review mode · mark moments for your video. Compare overlaps opens a scanned overlap group; Trim file edits the separate on-disk keep plan.')

    def set_mode(self,mode):
        self.mode=mode
        for key,button in getattr(self,'mode_buttons',{}).items():
            button.configure(style='Primary.TButton' if mode==key else 'Round.TButton')

    def overlap_folders(self):
        return {folder.name.casefold() for role, folder in self.app.project.folders().items() if role != 'Deleted'}

    def scan(self):
        if not self.app.project or self.app.busy or self.scanning:return
        root=self.app.project.root;work=self.work();tools=self.tools()
        report=work/f'overlaps-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.csv'
        self.scan_root=root;self.scan_project=self.app.project;self.scanning=True;self.scan_serial+=1;ticket=self.scan_serial
        self.scan_cancel.clear();self.cancel_scan_button.pack(side='right',padx=6,before=self.bottom_meter)
        self.scan_progress='Starting scan…'
        self.scan_meter['value']=0;self.bottom_meter['value']=0
        self.bottom_scan.pack(side='right',after=self.archive_badge,padx=8,fill='x',expand=True);self.bottom_spinner.start()
        self.scan_priority()
        self.scan_note.pack(side='right',padx=5,fill='x',expand=True)
        self.update_scan_note()
        args=SimpleNamespace(limit=0,offset=0,lookback=0,window_seconds=0,probe_timeout=600,overlap=10,
                             scan_cache=work/'scan-cache.sqlite3',include_folders=self.overlap_folders())
        def run():
            from review_cancel import background_thread
            with background_thread(self.scan_cancel):
                try:
                    audit(args,root,report,tools['ffprobe'],lambda text:self.scan_events.put((ticket,'progress',text)),self.scan_cancel)
                    result=('done',report)
                except ScanCancelled:result=('cancelled',None)
                except Exception as error:result=('error',str(error))
                if result[0]!='done':
                    try:report.unlink(missing_ok=True)
                    except OSError:pass
            self.scan_events.put((ticket,*result))
        self.scan_worker=threading.Thread(target=run,daemon=True);self.scan_worker.start()

    def read_groups(self,path):
        self.groups=[];self.group_by_id={}
        if not self.app.project:return
        project=self.app.project
        folders=self.overlap_folders()
        ids={}
        for clip in project.data['clips']:
            if clip.get('missing') or clip.get('decision')=='Deleted':continue
            source_path=project.checked(clip['path'])
            parts=source_path.relative_to(project.root).parts
            if len(parts)>1 and parts[0].casefold() in folders:ids[str(source_path).casefold()]=clip['id']
        graph={}
        try:
            with Path(path).open(encoding='utf-8-sig',newline='') as file:
                for row in csv.DictReader(file):
                    if not row.get('clip'):continue
                    source=ids.get(str(self.app.project.report_path(row['clip'])).casefold())
                    if not source:continue
                    peers=json.loads(row.get('matches') or row.get('coverage') or '[]')
                    if row.get('reference'):peers.append({'clip':row['reference']})
                    for peer in peers:
                        target=ids.get(str(self.app.project.report_path(peer['clip'])).casefold())
                        if target and target!=source:
                            graph.setdefault(source,set()).add(target);graph.setdefault(target,set()).add(source)
        except (OSError,ValueError,KeyError):return
        seen=set();order={c['id']:i for i,c in enumerate(self.app.project.data['clips'])}
        for clip_id in graph:
            if clip_id in seen:continue
            group=[];pending=[clip_id]
            while pending:
                item=pending.pop()
                if item in seen:continue
                seen.add(item);group.append(item);pending.extend(graph[item]-seen)
            group.sort(key=lambda i:order[i]);self.groups.append(group)
            for i in group:self.group_by_id[i]=group
        self.graph=graph;self.app.populate()

    def current_group(self):return self.group_by_id.get(self.app.current_id,[])

    def compare_group(self):
        if self.mode=='compare':return
        if not self.ready():return
        group=self.current_group()
        active={c['id'] for c in self.app.project.data['clips'] if c['decision']!='Deleted' and not c.get('missing')}
        group=[i for i in group if i in active]
        if len(group)<2:
            self.explain_comparison();return
        self.review();tools=self.tools();project=self.app.project
        clips=[archive_clip(project.root,next(c['path'] for c in project.data['clips'] if c['id']==i)) for i in group]
        edges=[{group.index(j) for j in self.graph[i] if j in group} for i in group]
        self.app.mixer.set_pause(True);self.app.status.set('Aligning overlap group using matching encoded video packets…')
        from review_save_ui import ProgressNotice
        self.notice=ProgressNotice(self.app,'Aligning overlapping clips…')
        def run():
            media=[probe(c,tools['ffprobe'],600) for c in clips]
            offsets={0:0.};pending=[0]
            while pending:
                i=pending.pop(0)
                for j in edges[i]-offsets.keys():
                    match=video_alignment(media[i],media[j])
                    if match:
                        offsets[j]=offsets[i]+media[i].start+match.shift-media[j].start;pending.append(j)
            if len(offsets)!=len(clips):raise ValueError('A clip no longer aligns with this scan. Run Scan overlaps again.')
            anchor=min(-o for o in offsets.values())
            return [(group[i],clips[i],-offsets[i]-anchor,media[i].duration,media[i].start) for i in range(len(clips))]
        def finish(layout):
            self.layout=layout;self.comparison_members=list(layout);self.page=0;self.set_mode('compare')
            self.selected_id=self.app.current_id;self.comparison_layout(True)
            self.app.video_frame.pack_forget();self.app.transport.pack_forget()
            self.compare=CompareView(self.app.video_column,self.library,lambda:None,app=self.app)
            self.compare.on_ready=self.clear_notice
            self.compare.open_hidden=self.open_lane
            self.compare.pack(fill='both',expand=True)
            self.options.pack(fill='x',after=self.app.main_stack,pady=4);self.compare_options.pack(fill='x')
            self.show_page()
            self.app.populate()
        self.job(run,finish)

    def explain_comparison(self):
        window=dialog(self.app.root,'Compare overlaps');page=ttk.Frame(window,padding=20);page.pack(fill='both',expand=True)
        text=('Click "Scan overlaps" to find clips which have overlapping footage. When the process is complete, press this button again while a clip with an overlap is selected. '
              'This will switch to the overlap comparison window. This feature allows you to find and COMBINE clips which have overlapping footage, to save some storage space and make editing easier. '
              'After a clip has been combined, it appears as a new clip in your Review queue. It is recommended to check for overlapping clips and merge them BEFORE you use the review queue to get clips into your video editing software timeline.')
        ttk.Label(page,text=text,wraplength=600,justify='left').pack(pady=(0,16))
        buttons=ttk.Frame(page);buttons.pack(anchor='e')
        def scan():window.destroy();self.scan()
        self.app.button(buttons,'Scan overlaps',scan,True).pack(side='left',padx=6)
        self.app.button(buttons,'Ok',window.destroy).pack(side='left');present(window,self.app.root)
        return window

    def show_page(self,position=None,resume=False):
        self.build_clip_delete_buttons()
        self.app.current_title.set(f'Comparing {len(self.layout)} overlapping clips')
        first=self.page*4;visible=self.layout[first:first+4]
        overview=tuple((start,start+duration,CLIP_COLORS[i%len(CLIP_COLORS)]) for i,(_,_,start,duration,_) in enumerate(self.layout))
        panes=[Pane(c.path,'original' if i==0 else 'later',start,start+duration,-start)
               for i,(_,c,start,duration,_) in enumerate(visible)]
        self.compare.load(panes,max(b for _,b,_ in overview),full_timeline=True,overview=overview,first=first,
                          initial_position=position,resume=resume,audio_files=tuple(row[1].path for row in self.layout))
        self.compare.vlc.review_mix=copy.deepcopy(self.app.clip().get('mix',[]))
        self.compare.vlc.hwdec=self.app.settings.data['tools']['hardware_decoding']
        self.label.set(f'Compare overlaps · clips {first+1}–{first+len(visible)} of {len(self.layout)}. Per-pane track menus also offer Review mixer.')

    def next_page(self):
        if not self.compare or not self.ready():return
        if self.page+1<(len(self.layout)+3)//4:
            self.page+=1;self.show_page();return
        group=self.current_group()
        if len(self.groups)<2:
            if self.page:self.page=0;self.show_page()
            else:self.app.status.set('This is the only linked overlap group. Scan overlaps to check for more.')
            return
        following=self.groups[(self.groups.index(group)+1)%len(self.groups)]
        self.app.load_clip(following[0],autoplay=False)
        def opened():
            if self.app.closed or not self.app.project or self.app.current_id!=following[0]:return
            if self.app.loading:self.app.root.after(30,opened)
            else:self.compare_group()
        opened()

    def open_lane(self,position,lane=None):
        if lane is None:return False
        page=lane//4
        if page==self.page:return False
        self.page=page;self.show_page(position,self.compare.playing);return True

    def trim_mode(self):
        if self.mode=='trim' or not self.ready():return
        self.review();clip=self.app.clip();path=self.app.project.checked(clip['path']);tools=self.tools()
        self.app.status.set('Reading valid lossless cut boundaries…')
        def finish(points):
            self.set_mode('trim');self.points=points
            self.app.timeline.ranges=clip.setdefault('trim_ranges',[])
            self.app.timeline.cut_points=points
            self.app.timeline.snap_range=lambda a,b:snap_keep(points,a,b)
            self.options.pack(in_=self.app.timeline_panel,fill='x',before=self.app.timeline,pady=4);self.trim_options.pack(fill='x')
            self.label.set(f'TRIM FILE · right-drag sections to KEEP ON DISK. Handles snap outward to {len(points)} valid boundaries. Your editor selections remain separate.')
            self.app.refresh_ranges();self.app.timeline.draw()
        self.job(lambda:cut_points(probe(archive_clip(path.parent,path.name),tools['ffprobe'],600)),finish)

    def render_trim(self):
        if not self.ready() or self.mode!='trim':return
        clip=self.app.clip();ranges=copy.deepcopy(clip.get('trim_ranges',[]));project=self.app.project
        join=self.join.get();replace=True;original_name=self.app.settings.data.getboolean('trimming','original_name');work=self.work();tools=self.tools()
        self.app.mixer.set_pause(True)
        def finish(result):
            try:
                before=project.checked(clip['path']).stat().st_size;after=sum(p.stat().st_size for p in result.paths)
                text=(f'Create {len(result.paths)} verified trimmed {"file" if len(result.paths)==1 else "files"}?\n\n'
                      f'Full original: {before/1e6:.1f} MB\nKept footage: {after/1e6:.1f} MB\n\n'
                      'Every retained encoded packet, track name and timing was checked, and the copies decoded successfully. Markers and editor selections will be mapped to the new clips.\n\n'
                      +(('The trimmed file keeps the original filename. ' if original_name else 'The trimmed file receives _TRIMMED in its name. ')+'The full source moves immediately to:\n'+str(backup_path(project,clip))+'\n\nUse Undo trim below the timeline to restore the complete original from Deleted. Existing editor projects may need relinking because source times change.' if replace else 'The full original stays in its current folder. No space is reclaimed until you choose to remove it.'))
                if not replace:text+='\n\nThe source’s editor selections will be disabled after transferring to the copies, to avoid exporting both versions. You can undo that review change.'
                padding=[g for d in result.details for g in d.get('join_padding_seconds',[])]
                if padding:text+='\n\nContainer priming adds '+', '.join(f'{max(0,g)*1000:.1f} ms' for g in padding)+' of hold at the joins. Create separate copies to avoid joining.'
                backup=backup_path(project,clip) if replace else None
                if not confirm_action(self.app.root,'Verified trim ready',text,'Replace with verified trim' if replace else 'Create trimmed copies',cancel_text='Cancel and delete trimmed copy'):
                    from review_trim_undo import discard
                    def discarded(paths):
                        result.folder.cleanup();self.trim_result=None;self.app.populate()
                        self.app.status.set('Trim canceled. Trimmed copies moved to Deleted; the original is unchanged.')
                    self.trim_result=result
                    self.job(lambda:discard(project,clip,result),discarded,lambda:result.folder.cleanup())
                    return
                self.app.magnifier.hide();self.app.mixer.clear()
                if self.app.waveforms:self.app.waveforms.cancel(wait=True)
                def install():return replace_trim(project,clip,result,backup,original_name=original_name) if replace else install_new_copies(project,clip,result)
                def installed(value):
                    result.folder.cleanup()
                    self.trim_result=None
                    if replace:
                        copies,original,receipt=value
                        self.app.history.clear()
                    else:
                        copies=value;self.app.history.watch(clip)
                        for marked in clip['ranges']:marked['enabled']=False
                        self.app.changed(fields=('ranges',))
                    self.review();self.refresh_saved_groups();self.app.populate()
                    if copies:
                        self.app.filter.set('All');self.app.load_clip(copies[0]['id'],autoplay=False)
                    self.app.status.set('Trimmed video installed. Full original: '+original['path'] if replace else 'Verified trimmed copies created. Save project to retain mapped moments, markers and sorting decisions.')
                def failed():
                    result.folder.cleanup();self.trim_result=None
                    self.review(notify=False);self.app.populate();self.app.load_clip(clip['id'],autoplay=False)
                self.job(install,installed,failed)
                # Keep staged files alive until install completes.
                self.trim_result=result
            finally:
                if not self.app.busy:result.folder.cleanup()
        self.job(lambda:create_trim(project.checked(clip['path']),work,ranges,tools,self.progress,join),finish)

    def refresh_saved_groups(self):
        report=self.saved_report()
        if report:self.read_groups(report)
        else:self.groups=[];self.group_by_id={};self.graph={}

    def undo_trim(self):
        if not self.ready() or not self.app.clip():return
        from review_trim_undo import undo,receipt_for
        clip=self.app.clip();project=self.app.project
        receipt=receipt_for(project,clip)
        if receipt is None:return
        data=json.loads(receipt.read_text(encoding='utf-8'))
        if not confirm_action(self.app.root,'Undo trim',
                'Restore the full original to '+data['source']+'?\n\nAll copies from this trim will move to Deleted. The original selections and bookmarks will be restored.', 'Undo trim'):return
        self.review(notify=False);self.app.magnifier.hide();self.app.mixer.clear()
        if self.app.waveforms:self.app.waveforms.cancel(wait=True)
        def finished(restored):
            self.app.history.clear();self.app.filter.set('All');self.refresh_saved_groups();self.app.populate()
            self.app.load_clip(restored['id'],autoplay=False)
            self.app.status.set('Trim undone. The original is restored; trimmed copies are in Deleted.')
        self.job(lambda:undo(project,clip),finished,lambda:self.app.load_clip(clip['id'],autoplay=False))

    def build_clip_delete_buttons(self):
        from review_help import Tooltip
        for child in self.clip_delete_options.winfo_children():child.destroy()
        self.clip_delete_options.pack(fill='x')
        from review_folders import names
        deleted=names(self.app.project)['Deleted']
        for number,(ident,clip,*_) in enumerate(self.layout,1):
            button=self.app.button(self.clip_delete_options,f'Move Clip {number} To {deleted}',lambda i=ident:self.delete_overlap_clip(i))
            button.grid(row=(number-1)//4,column=(number-1)%4,sticky='w',padx=(0,6),pady=3)
            Tooltip(button,clip.path.name+'\nMoves to '+deleted+' when you save the project. Undo restores this review decision.')

    def delete_overlap_clip(self,ident):
        if self.app.busy:return
        clip=next((c for c in self.app.project.data['clips'] if c['id']==ident),None)
        if not clip:return
        self.app.history.watch(clip);clip['decision']='Deleted'
        self.app.history.record(clip,fields=('decision',));self.app.project.mark_review(clip)
        self.app.changed(record=False);self.app.history.watch(self.app.clip());self.refresh_comparison()
        self.app.status.set(Path(clip['path']).name+' marked Deleted. Save moves the file; Undo restores it.')

    def refresh_comparison(self):
        if self.mode!='compare' or not self.comparison_members:return False
        records={c['id']:c for c in self.app.project.data['clips']}
        self.layout=[row for row in self.comparison_members if row[0] in records and records[row[0]]['decision']!='Deleted' and not records[row[0]].get('missing')]
        position=self.compare.timeline.time if self.compare else 0
        if not self.layout:
            # Keep this session available for Undo even after the final removal.
            self.compare.reset('All clips in this comparison are marked Deleted. Undo restores them.')
            self.build_clip_delete_buttons();self.app.populate();return True
        self.page=min(self.page,(len(self.layout)-1)//4)
        self.show_page(position=position);self.app.populate()
        return True

    def merge(self):
        if not self.ready() or not self.layout:return
        from review_cleanup_merge import prepare_merge
        from review_merge_install import install as install_merge,output_path
        project=self.app.project;tools=self.tools();work=self.work()
        rows=sorted(self.layout,key=lambda row:(row[1].capture_time,str(row[1].path)))
        ids=[r[0] for r in rows];clips=tuple(r[1] for r in rows)
        edges=[{ids.index(j) for j in self.graph[i] if j in ids} for i in ids]
        annotations={c['id']:copy.deepcopy(c) for c in project.data['clips'] if c['id'] in ids}
        def finish(merge):
            try:
                target=output_path(project,merge,self.app.settings.data.getboolean('trimming','original_name'))
                text=(f'Merge {len(clips)} clips together into 1 clip?\n{target.name}\n\n'
                      f'New length: {merge.duration:.2f} seconds. All audio tracks are preserved.\n\n'
                      'The original files are moved into the Deleted folder of this project.\n'
                      "Keep this in mind - in case you've already used those clips in video editing software (DaVinci Resolve etc). "
                      "If you merged and replaced a file which was already used, the clip won't line up right and you will need to fix it "
                      '(ClipComb Pro and this merge feature are intended to be used BEFORE editing).')
                if not confirm_action(self.app.root,'Merge clips',text,'Replace originals with merged copy',cancel_first=True):return
                record=copy.deepcopy(annotations[ids[0]])
                ranges=[];markers=[];seen=set();provenance=[]
                for row,placement in zip(rows,merge.track_placements):
                    item_id,original,_,duration,start=row
                    base=start+placement[merge.video_index]['shift_seconds']-merge.output_start
                    rr,mm=remap_annotations(annotations[item_id],[(0,duration,base)])
                    ranges.extend(rr)
                    for marker in mm:
                        key=(round(marker['time'],4),marker['name'],marker.get('note',''))
                        if key not in seen:markers.append(marker);seen.add(key)
                    provenance.append({'source_id':item_id,'source_path':annotations[item_id]['path'],
                                       'start':0,'end':duration,'output_start':base})
                record.update(ranges=ranges,markers=markers,provenance=provenance)
                self.review();self.app.mixer.clear()
                if self.app.waveforms:self.app.waveforms.cancel(wait=True)
                def install():
                    return install_merge(project,merge,record,work,self.progress,target)
                def installed(result):
                    merged,receipt=result
                    project.scan();self.read_groups(self.saved_report()) if self.saved_report() else None
                    self.app.history.clear();self.app.filter.set('Unused');self.app.populate()
                    self.app.load_clip(merged['id'],autoplay=False)
                    merge.folder.cleanup();self.merge_result=None
                    self.app.status.set('Merged clip added to Unused. All originals are in Deleted; mapped moments and bookmarks are saved.')
                def failed():
                    merge.folder.cleanup();self.merge_result=None;self.app.populate();self.app.load_clip(ids[0],autoplay=False)
                self.job(install,installed,failed);self.merge_result=merge
            finally:
                if not self.app.busy:merge.folder.cleanup()
        self.job(lambda:prepare_merge(work,clips,edges,tools,self.progress,ledger=work),finish)

    def archive(self,parent=None):
        if self.app.busy:return
        from review_archive_ui import open_archive
        open_archive(self,parent)

    def map_archive_merge(self,merge,receipt):
        if not self.app.project:return
        from review_file_trim import map_project_merge
        map_project_merge(self.app.project,merge,receipt)
        self.app.project.scan();self.app.project.save()

    def map_archive_replacement(self,receipt,record):
        if not self.app.project:return
        if receipt['kind']!='replace_original' or not record:return
        from review_core import atomic_json
        clip=next((c for c in self.app.project.data['clips'] if str(self.app.project.checked(c['path'])).casefold()==str(receipt['source']).casefold()),None)
        if not clip:return
        original=copy.deepcopy(clip);a=record['trim_start_seconds'];b=record['retained_end_seconds']
        base=receipt.get('video_origin',0.)
        clip['ranges'],clip['markers']=remap_annotations(clip,[(a,b,base)])
        clip.update(media=None,identity=file_identity(self.app.project.checked(clip['path'])),position=0)
        clip['provenance']=[{'source_id':clip['id'],'source_path':clip['path'],'start':a,'end':b,'output_start':base}]
        atomic_json(Path(receipt['recovery']).parent/'clipcomb-annotations.json',{'original':original,'trimmed':copy.deepcopy(clip)})
        self.app.project.dirty=True
        self.app.project.scan();self.app.project.save()

    def close(self):
        self.clear_notice()
        self.pause_scan(wait=True);self.spinner.stop()
        if self.compare:self.compare.close()
        for name in ('trim_result','merge_result'):
            result=getattr(self,name,None)
            if result:result.folder.cleanup()
