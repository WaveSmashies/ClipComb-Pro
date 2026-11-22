# SPDX-License-Identifier: GPL-3.0-or-later
"""File-based export and direct Studio append, with background connection work."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk
import uuid
from review_core import atomic_json,profile_for_name,read_json
from review_export import write_fcpxml,validate
from review_interchange import write_premiere_xml,write_otio,write_resolve_otio
from review_kdenlive import write_kdenlive
from review_audio import track_names
from review_dialogs import ScrollPage,own_variables
from review_help import badge,check,label
from review_theme import dialog,present,show_error,reveal_paths


def export_dialog(app,clip_ids=None,force=False):
    if not app.project or app.busy:return
    window=dialog(app.root,'Export marked moments')
    page=ttk.Frame(window,padding=20);page.pack(fill='both',expand=True)
    ttk.Label(page,text='Export marked moments',style='Subheading.TLabel').pack(anchor='w')
    description='Export enabled marked moments from the checked folders. Missing clips are skipped.\nExport saves pending sorting decisions first. Folder choices belong to this project.'
    if clip_ids:
        selected=next((c for c in app.project.data['clips'] if c['id'] in clip_ids),None)
        description='Selected clip: '+(Path(selected['path']).name if selected else 'selection')+'\nUses enabled marks, or the whole clip if there are none. Its folder must be checked below.'
    ttk.Label(page,text=description,wraplength=580,
              style='Hint.TLabel').pack(anchor='w',pady=(6,12))
    cfg=app.settings.data['export'];mix=tk.BooleanVar(value=cfg.getboolean('apply_mix'))
    from review_folder_selection import FolderChoices,export_folders,remember_export_folders
    common=ttk.Frame(page);common.pack(fill='x',pady=(0,12))
    folder_controls=[]
    common_options=ttk.Frame(common);common_options.pack(side='left',fill='both',expand=True,pady=8)
    def folder_changed():
        previous=export_folders(app.project)
        try:remember_export_folders(app.project,folders.selected())
        except (ValueError,OSError) as error:
            folders.set_selected(previous);show_error(window,'Could Not Save Export Folders',str(error))
        update_summary()
    check(common_options,'Carry review audio levels',mix,'Keep every source audio track separate and editable. Tracks silenced during review receive minimum Inspector volume instead of a mute or disabled state. Uncheck to import all tracks at their original level.\n\nDefault: On.').pack(anchor='w',pady=(0,12))
    timeline_marks=tk.BooleanVar(value=cfg.getboolean('timeline_markers'))
    check(common_options,'Bookmarks on timeline instead of inside clips',timeline_marks,'Place bookmarks at their final timeline positions. Leave off to attach them to each selected clip so they move and copy with it. Resolve Studio preserves all 16 native colors; file formats use their supported palettes. Standard Final Cut bookmarks are blue, and project-level bookmarks use a primary-storyline gap. This choice is remembered.\n\nDefault: Off.').pack(anchor='w',pady=(0,12))
    tabs=ttk.Notebook(page);tabs.pack(fill='both',expand=True)
    file_tab=ttk.Frame(tabs);studio_tab=ttk.Frame(tabs)
    file_footer=ttk.Frame(file_tab,padding=(14,8));file_footer.pack(side='bottom',fill='x')
    studio_footer=ttk.Frame(studio_tab,padding=(14,8));studio_footer.pack(side='bottom',fill='x')
    file_page=ScrollPage(file_tab,14);studio_page=ScrollPage(studio_tab,14);files=file_page.inner;studio=studio_page.inner
    file_page.pack(fill='both',expand=True);studio_page.pack(fill='both',expand=True)
    tabs.add(file_tab,text='Timeline file · Other editors / Resolve');tabs.add(studio_tab,text='Existing timeline · Studio')
    window.review_minimum=(500,390)
    fps=tk.StringVar(value='Auto (highest clip)' if cfg['fps'].startswith('Auto') else cfg['fps']);name=tk.StringVar(value=cfg['timeline_name'])
    formats={'OTIO · Resolve (clip markers)':('otio',write_resolve_otio),
             'FCPXML · Final Cut Pro':('fcpxml',write_fcpxml),
             'XML · Premiere / legacy editors':('xml',write_premiere_xml),
             'Kdenlive project · Original media':('kdenlive',write_kdenlive)}
    selected_format={'FCPXML · Resolve / Final Cut':'FCPXML · Final Cut Pro','OTIO · Kdenlive / other editors':'Kdenlive project · Original media'}.get(cfg.get('format'),cfg.get('format'))
    file_format=tk.StringVar(value=selected_format if selected_format in formats else next(iter(formats)))
    label(files,'File format','Resolve OTIO preserves clip markers, descriptions, linked audio and Inspector levels. Resolve currently drops clip markers from XML; use FCPXML for Final Cut and legacy XML for Premiere. Other editors may interpret markers and audio levels differently.\n\nDefault: OTIO · Resolve (clip markers).').grid(row=0,column=0,sticky='w',pady=6)
    format_combo=ttk.Combobox(files,textvariable=file_format,values=list(formats),state='readonly',width=32);format_combo.grid(row=0,column=1,sticky='ew')
    label(files,'Timeline name','Name of the new selects timeline created when you import the file. You can then copy its clips into an existing timeline.\n\nDefault: ClipComb Pro selects.').grid(row=1,column=0,sticky='w',pady=6)
    ttk.Entry(files,textvariable=name,width=30).grid(row=1,column=1,sticky='ew')
    label(files,'Timeline frame rate','Choose or type any positive frame rate, including a fraction such as 60000/1001. Auto uses the highest frame rate among the clips being exported. Timeline dimensions use the largest exported clip. Legacy Premiere XML requires whole-number or standard NTSC rates.\n\nDefault: Auto (highest clip).').grid(row=2,column=0,sticky='w',pady=6)
    ttk.Combobox(files,textvariable=fps,values=['Auto (highest clip)','23.976','24','25','29.97','30','50','59.94','60','120','144','240'],width=24).grid(row=2,column=1,sticky='ew')
    fix_bookmarks=tk.BooleanVar(value=cfg.getboolean('fix_bookmarks',fallback=True))
    fix_help='Final Cut Pro uses point bookmarks. Enable this to export each extended bookmark as two point bookmarks: "1 Something funny" at the start and "2 Something funny" on the last included frame. Both keep the original notes. A one-frame section uses one bookmark labeled "1 / 2 Something funny". Point bookmarks stay points. Your ClipComb Pro project keeps its original extended bookmark. Resolve, Premiere and native Kdenlive projects retain bookmark ranges.\n\nDefault: On.'
    fix_row=check(files,'Fix bookmarks for Final Cut Pro',fix_bookmarks,fix_help)
    fix_row.grid(row=3,column=0,columnspan=2,sticky='w',pady=(10,0))
    file_hint=tk.StringVar()
    def format_changed(event=None):
        compatible=file_format.get().startswith('FCPXML')
        fix_row.control.configure(state='normal' if compatible else 'disabled')
        prefix='References the complete original clips for video and every audio stream. No media copies or extracted audio files are created. Extend trims into the original footage and copy clips into your main edit.\n\n'
        if file_format.get()=='OTIO · Resolve (clip markers)':detail='Resolve: File → Import → Timeline, then select the .otio file. Use the same timeline frame rate selected above when importing; Resolve can otherwise use the project rate. Bookmarks, descriptions, linked audio and Inspector levels are retained. OTIO uses Resolve’s supported color subset. Copy imported clips into your existing edit as needed. No Studio scripting connection is needed.'
        elif file_format.get().startswith('FCPXML'):detail='Final Cut: File → Import → XML. Final Cut has point bookmarks. With the compatibility fix off, range endpoints remain in the bookmark note. Use Resolve OTIO when importing into Resolve; its XML importer does not reliably select embedded audio streams.'
        elif file_format.get().startswith('XML'):detail='Premiere: File → Import, then select the .xml file. Bookmarks retain their spans. Stereo streams use linked channel pairs. Original OBS video must be supported by your editor.'
        else:detail='Kdenlive: File → Open, then select the .kdenlive project. Each embedded audio stream has its own editable track, grouped with its video. Bookmark ranges and review levels are retained. Copy clips into a destination project with the same frame rate and enough audio tracks. Native projects avoid Kdenlive OTIO source-offset and audio-stream import limitations. Verified with Kdenlive 26.08.3.'
        if compatible and fix_bookmarks.get():detail+='\n\nExtended bookmarks export as numbered start/end bookmarks with the compatibility fix enabled.'
        file_hint.set(prefix+detail)
    format_combo.bind('<<ComboboxSelected>>',format_changed);format_changed()
    fix_bookmarks.trace_add('write',lambda *_:format_changed())
    ttk.Label(files,textvariable=file_hint,wraplength=580,style='Hint.TLabel').grid(row=4,column=0,columnspan=2,sticky='w',pady=12)
    format_summary=tk.StringVar()
    ttk.Label(files,textvariable=format_summary,wraplength=580,style='Hint.TLabel').grid(row=5,column=0,columnspan=2,sticky='w',pady=(0,10))
    folders=FolderChoices(files,app.project,export_folders(app.project),'Folders To Export',folder_changed)
    folders.frame.grid(row=6,column=0,columnspan=2,sticky='ew',pady=(0,8));folder_controls.extend(folders.controls)
    def update_summary(*_):
        from review_export import timeline_defaults
        clips=[c for c in app.project.data['clips'] if c['decision'] in folders.selected() and not c.get('missing') and c.get('media') and
               (not clip_ids or c['id'] in clip_ids) and (clip_ids or any(r.get('enabled',True) for r in c.get('ranges',[])))]
        if not clips:format_summary.set('No marked clips in the checked folders.');return
        try:settings=timeline_defaults(clips,None if fps.get().startswith('Auto') else fps.get())
        except (ValueError,ZeroDivisionError):format_summary.set('Enter a positive timeline frame rate.');return
        color=settings['color_space'].split('(',1)[-1].rstrip(')')
        text=f'Timeline target · {float(settings["fps"]):g} fps · {settings["width"]} × {settings["height"]} · {color}'
        if file_format.get().startswith('OTIO'):text+='\nMatch these settings in Resolve’s import options; Resolve may use its project settings instead.'
        if 'PQ' in color or 'HLG' in color:text+='\nHDR footage detected. Check color management in your editor, especially when mixing SDR and HDR. Final Cut XML carries HDR project and source color spaces.'
        format_summary.set(text)
    for variable in (fps,file_format):variable.trace_add('write',update_summary)
    update_summary()
    message=tk.StringVar(value='Refresh to read the open Resolve project and its existing timelines.')
    ttk.Label(studio,textvariable=message,style='Hint.TLabel',wraplength=580).pack(anchor='w',pady=(0,10))
    row=ttk.Frame(studio);row.pack(fill='x')
    target=tk.StringVar();combo=ttk.Combobox(row,textvariable=target,state='readonly',width=39);combo.pack(side='left',fill='x',expand=True)
    badge(row,'Choose an existing timeline in the open Studio project. Use a dedicated selects timeline, then copy its clips into your main edit. Import appends at the end, reuses unlocked/enabled tracks with compatible audio layouts, and adds only the missing tracks. Existing clips and track names stay intact. Refresh after editing or switching projects.\n\nDefault: The current timeline.').pack(side='left',padx=5)
    skip=tk.BooleanVar(value=False if force else cfg.getboolean('skip_existing',fallback=True))
    skip_warning=tk.BooleanVar(value=cfg.getboolean('dont_show_warning',fallback=False))
    def warning_preference_changed():
        previous=cfg.get('dont_show_warning','no')
        try:
            cfg['dont_show_warning']='yes' if skip_warning.get() else 'no';app.settings.save()
        except OSError as error:
            cfg['dont_show_warning']=previous;skip_warning.set(previous=='yes')
            show_error(window,'Could Not Save Export Warning Preference',str(error))
    check(studio,'Skip moments already on this timeline',skip,'Skip footage already covered by video on the chosen timeline. When marked moments are unchanged, add or update ClipComb bookmarks on matching existing clips without duplicating footage. Editor-created bookmarks are preserved. If originals have moved, choose whether to repair their shared Resolve media links before importing. Other moments can still be appended. Uncheck to re-add footage.\n\nDefault: On (off for the right-click Place clip action).').pack(anchor='w',pady=(10,0))
    state={'connection':None,'working':False,'confirming':False,'pending_request':None};results=queue.Queue()
    status=tk.StringVar(value='');status_label=ttk.Label(page,textvariable=status,style='Hint.TLabel',wraplength=600);status_label.pack(side='bottom',anchor='w',pady=(12,0),before=tabs)
    pending_preferences=[None]
    selected_mode=['studio' if force or cfg.get('mode')=='studio' else 'file']
    def shared_preferences():
        if pending_preferences[0]:window.after_cancel(pending_preferences[0]);pending_preferences[0]=None
        values=dict(timeline_name=name.get().strip() or 'ClipComb Pro selects',apply_mix='yes' if mix.get() else 'no',format=file_format.get(),timeline_markers='yes' if timeline_marks.get() else 'no',fix_bookmarks='yes' if fix_bookmarks.get() else 'no')
        if not force:values.update(mode=selected_mode[0],skip_existing='yes' if skip.get() else 'no')
        try:
            from review_export import rate
            candidate=fps.get().strip()
            if candidate.startswith('Auto'):values['fps']='Auto (highest clip)'
            else:rate(candidate);values['fps']=candidate
        except (ValueError,ZeroDivisionError):pass
        if any(cfg.get(key)!=value for key,value in values.items()):cfg.update(values);app.settings.save()
    def schedule_preferences(*_):
        selected_mode[0]='studio' if tabs.select()==str(studio_tab) else 'file'
        if pending_preferences[0]:window.after_cancel(pending_preferences[0])
        pending_preferences[0]=window.after(250,shared_preferences)
    def preferences():
        remember_export_folders(app.project,folders.selected());shared_preferences()
    def payload():
        if not folders.selected():raise ValueError('Check at least one folder to export.')
        remember_export_folders(app.project,folders.selected())
        if not app.save():raise ValueError('Save did not finish. Nothing was exported.')
        path,_=app.project.export_ranges(folders.selected());data=json.loads(path.read_text(encoding='utf-8'))
        if clip_ids:
            data['clips']=[c for c in data['clips'] if c['id'] in clip_ids]
            if not data['clips']:
                import copy
                for source in app.project.data['clips']:
                    if source['id'] not in clip_ids or source.get('missing') or source['decision'] not in folders.selected():continue
                    clip=copy.deepcopy(source);clip['path']=str(app.project.checked(source['path']));clip['category']=source['decision']
                    clip['ranges']=[{'id':'whole-clip','start':0,'end':(clip.get('media') or {}).get('duration',0),'enabled':True}]
                    data['clips'].append(clip)
        for clip in data['clips']:
            names=track_names(clip['path'],clip.get('audio_profile',app.settings.data['audio']['default_profile']),app.settings.data['audio'],app.date_audio)
            for i,t in enumerate((clip.get('media') or {}).get('audio',[])):
                if names:
                    t['title']=names[i] if i<len(names) else f'Track {i+1}'
        validate(data);preferences();return data
    def file_export():
        try:
            data=payload();extension,writer=formats[file_format.get()];path=app.project.root/('clip-review-timeline.'+extension)
            args=(data,path,None if fps.get().startswith('Auto') else fps.get(),name.get().strip() or cfg['timeline_name'],mix.get())
            global_marks=timeline_marks.get()
            options={'timeline_markers':global_marks}
            if writer in (write_fcpxml,write_otio):options['fix_bookmarks']=fix_bookmarks.get()
            state['working']=True;app.busy=True;status.set('Writing timeline file…')
            for b in buttons+folder_controls:b.configure(state='disabled')
            def worker():
                try:results.put(('xml',writer(*args,**options),None))
                except Exception as error:results.put(('xml',None,str(error)))
            threading.Thread(target=worker,daemon=True).start()
        except Exception as error:show_error(window,'Could not export timeline',str(error))
    def call(request,kind):
        if state['working']:return
        folder=app.settings.data['tools']['resolve_folder'].strip()
        install=Path(folder or (Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Blackmagic Design/DaVinci Resolve'))
        interpreter=install/'ResolvePython/ResolvePython.exe'
        if not interpreter.is_file():show_error(window,'Resolve Studio needed','Find the Resolve installation folder under Settings → Playback. Direct import uses the Python interpreter included with Resolve Studio 21.1 or newer.');return
        base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
        helper=base/'bridge/review_resolve.py' if getattr(sys,'frozen',False) else base/'review_resolve.py'
        cache=app.settings.path.parent/'cache/resolve';cache.mkdir(parents=True,exist_ok=True)
        token=uuid.uuid4().hex;src=cache/(token+'.request.json');dst=cache/(token+'.response.json');atomic_json(src,request)
        state['working']=True;app.busy=True;status.set('Reading Resolve…' if kind=='inspect' else ('Checking existing clips… ' if kind=='prepare' else 'Importing and updating moments… ')+'DO NOT TOUCH DaVinci Resolve until the import is finished!')
        (refresh_spinner if kind=='inspect' else import_spinner).start(12)
        for b in buttons+folder_controls:b.configure(state='disabled')
        def worker():
            try:
                p=subprocess.run([str(interpreter),str(helper),str(src),str(dst)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=600)
                if not dst.is_file():raise RuntimeError(p.stderr.decode('utf-8','replace')[-600:] or 'Resolve helper did not return a response.')
                response=json.loads(dst.read_text(encoding='utf-8'))
                if not response['ok']:raise RuntimeError(response['error'])
                results.put((kind,response['result'],None))
            except subprocess.TimeoutExpired:results.put((kind,None,'The Resolve operation timed out. Check the destination timeline before retrying; the import may be partial.'))
            except Exception as error:results.put((kind,None,str(error)))
            finally:
                src.unlink(missing_ok=True);dst.unlink(missing_ok=True)
        threading.Thread(target=worker,daemon=True).start()
    def refresh():call({'action':'inspect'},'inspect')
    def append_to_destination(connection,destination):
        try:
            manifest=app.project.root/'clip-review-export.json'
            previous=read_json(manifest).get('clips',[]) if manifest.is_file() else []
        except (OSError,ValueError,AttributeError):previous=[]
        try:data=payload()
        except Exception as error:show_error(window,'Could not prepare import',str(error));return
        from review_resolve_sync import path_key
        current={clip['id']:clip for clip in data['clips']}
        old_paths={}
        for clip in previous:
            if clip.get('id') not in current or not clip.get('path'):continue
            now=current[clip['id']];media=clip.get('media') or {}
            if all(media.get(k)==now['media'].get(k) for k in ('fps','duration','width','height')) and clip.get('identity',now['identity'])==now['identity']:
                old_paths.setdefault(path_key(clip['path']),[]).append(clip['id'])
        receipt_key=connection['project_id']+'|'+destination['id']
        try:
            receipts=app.project.metadata/'resolve-imports.json'
            existing=(read_json(receipts) if receipts.is_file() else {}).get(receipt_key,[])
        except (OSError,ValueError) as error:show_error(window,'Could Not Read Previous Imports',str(error));return
        request={'action':'prepare','payload':data,'project_id':connection['project_id'],'timeline_id':destination['id'],
              'expected_end':destination['end'],'apply_mix':mix.get(),'skip_existing':skip.get(),'timeline_markers':timeline_marks.get(),'existing_imports':existing}
        data['previous_sources']=old_paths
        state['pending_request']=request;call(request,'prepare')
    def finish_preparation(result,repair=False):
        request=state['pending_request'];state['confirming']=False
        if not request:return
        request=dict(request,action='append',plan_token=result['plan_token'],repair_links=repair)
        call(request,'append')
    def choose_relink(result):
        prompt=dialog(window,'Moved Source Clips');window.export_relink_window=prompt;prompt.resizable(False,False)
        state['confirming']=True
        body=ttk.Frame(prompt,padding=20);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Moved Source Clips',style='Subheading.TLabel').pack(anchor='w')
        ttk.Label(body,text='ClipComb Pro found moved originals used by the selected Resolve timeline. Repair these links automatically, or leave them unchanged and continue?\n\nResolve shares media links across timelines. Repairing a source also fixes other timelines using the same media pool clip.',wraplength=620).pack(anchor='w',pady=12)
        locations=ScrollPage(body,8);locations.canvas.configure(width=620,height=min(290,145*len(result['moved_sources'])))
        locations.pack(fill='both',expand=True)
        for move in result['moved_sources']:
            ttk.Label(locations.inner,text=Path(move['new']).name+'\nFrom: '+move['old']+'\nTo: '+move['new'],wraplength=590,justify='left').pack(anchor='w',pady=(0,12))
        footer=ttk.Frame(body);footer.pack(fill='x',pady=(14,0))
        def finish(choice):
            prompt.destroy();window.grab_set();state['confirming']=False
            if choice is None:state['pending_request']=None;status.set('Import cancelled. Resolve was not changed.')
            else:finish_preparation(result,choice)
        ttk.Button(footer,text='Cancel',style='Round.TButton',command=lambda:finish(None)).pack(side='left')
        ttk.Button(footer,text='Repair Links',style='Primary.TButton',command=lambda:finish(True)).pack(side='right')
        ttk.Button(footer,text='Leave Links Unchanged',style='Round.TButton',command=lambda:finish(False)).pack(side='right',padx=8)
        prompt.relink_controls=dict(repair=lambda:finish(True),leave=lambda:finish(False),cancel=lambda:finish(None),moves=result['moved_sources'])
        app.shortcut_tags(prompt);present(prompt,window);prompt.protocol('WM_DELETE_WINDOW',lambda:finish(None));prompt.bind('<Escape>',lambda event:finish(None))
    def send():
        if state['working'] or state['confirming']:return
        connection=state['connection']
        if not connection:show_error(window,'Choose a timeline','Refresh the connection, then select an existing timeline.');return
        values=list(combo['values'])
        if target.get() not in values:show_error(window,'Choose a timeline','Select an existing destination timeline.');return
        destination=connection['timelines'][values.index(target.get())]
        if skip_warning.get():append_to_destination(connection,destination)
        else:
            from review_export_warning import show_warning
            show_warning(app,window,skip_warning,warning_preference_changed,lambda:append_to_destination(connection,destination))
    buttons=[]
    from review_spinner import Spinner
    refresh_row=ttk.Frame(studio_footer);refresh_row.pack(fill='x',pady=(0,8))
    button=ttk.Button(refresh_row,text='Refresh connection',style='Round.TButton',command=refresh);button.pack(side='left');buttons.append(button)
    refresh_spinner=Spinner(refresh_row);refresh_spinner.pack(side='left',padx=8)
    import_row=ttk.Frame(studio_footer);import_row.pack(fill='x')
    button=ttk.Button(import_row,text='Append moments to selected timeline',style='Primary.TButton',command=send);button.pack(side='left');buttons.append(button)
    import_spinner=Spinner(import_row);import_spinner.pack(side='left',padx=8)
    ttk.Label(studio,text='Use a dedicated selects timeline, then copy the imported clips into your main edit. Available compatible tracks are reused; missing tracks are added.\nChoose whether existing moments are skipped or re-added above.\nDO NOT TOUCH DaVinci Resolve until the import is finished!\nRequires Studio 21.1+ and External scripting set to Local.',style='Hint.TLabel',wraplength=580).pack(anchor='w',pady=12)
    studio_folders=FolderChoices(studio,app.project,folders.selected(),'Folders To Export',folder_changed,variables=folders.variables)
    studio_folders.frame.pack(fill='x',pady=(0,8));folder_controls.extend(studio_folders.controls)
    warning_toggle=ttk.Checkbutton(studio,text="Don't show export warning",variable=skip_warning,command=warning_preference_changed)
    warning_toggle.pack(anchor='w',pady=(0,8));folder_controls.append(warning_toggle)
    button=ttk.Button(file_footer,text='Export timeline file',style='Primary.TButton',command=file_export);button.pack(anchor='w');buttons.append(button)
    def close():
        if not state['working'] and not state['confirming']:shared_preferences();window.destroy()
    window.protocol('WM_DELETE_WINDOW',close)
    def poll():
        if not window.winfo_exists():return
        try:
            kind,result,error=results.get_nowait();state['working']=False;app.busy=False
            refresh_spinner.stop();import_spinner.stop()
            for b in buttons+folder_controls:b.configure(state='normal')
            if error:status.set(error);show_error(window,'Resolve import',error)
            elif kind=='inspect':
                state['connection']=result;message.set('Project: '+result['project'])
                values=[f'{i+1}. {t["name"]} ({t["fps"]} fps)' for i,t in enumerate(result['timelines'])];combo.configure(values=values)
                index=next((i for i,t in enumerate(result['timelines']) if t['current']),0)
                target.set(values[index] if values else '')
                status.set('Choose a timeline, then append. Existing edits are preserved.' if values else 'Create a timeline in Resolve, then refresh.')
            elif kind=='xml':
                status.set(f'Exported {result["moments"]} moments → {Path(result["path"]).name}. Import this file in your editor.')
                app.status.set(status.get())
                try:reveal_paths([Path(result['path'])])
                except OSError:status.set(status.get()+'\nSaved in: '+str(Path(result['path']).parent))
            elif kind=='prepare':
                if result['moved_sources']:choose_relink(result)
                else:finish_preparation(result)
            else:
                status.set(f'Appended {result["moments"]} moments; skipped {result.get("skipped",0)} already present → {result["timeline"]}.')
                if result.get('bookmarks_updated'):status.set(status.get()+f' Updated {result["bookmarks_updated"]} bookmarks.')
                if result.get('sources_relinked'):status.set(status.get()+f' Repaired {result["sources_relinked"]} source links.')
                if result.get('sources_left_offline'):status.set(status.get()+f' Left {result["sources_left_offline"]} source links unchanged.')
                request=state['pending_request']
                if 'imports' in result and request:
                    try:
                        receipts=app.project.metadata/'resolve-imports.json';saved=read_json(receipts) if receipts.is_file() else {}
                        key=request['project_id']+'|'+request['timeline_id']
                        by_item={record['item_id']:record for record in saved.get(key,[])}
                        by_item.update({record['item_id']:record for record in result['imports']})
                        saved[key]=list(by_item.values());atomic_json(receipts,saved)
                    except (OSError,ValueError) as error:status.set(status.get()+' Import finished, but its local update history could not be saved: '+str(error))
                state['pending_request']=None
                added=result.get('tracks_added')
                if added is not None:
                    status.set(status.get()+ (' Reused existing tracks.' if not any(added.values()) else f' Added tracks: {added["video"]} video, {added["audio"]} audio.'))
                app.status.set(status.get());state['connection']=None
        except queue.Empty:pass
        window.after(80,poll)
    tabs.select(studio_tab if force or cfg.get('mode')=='studio' else file_tab)
    app.shortcut_tags(window)
    # Measure after padding and wrapping have been scaled for this display.
    app.ui_scale.new_widgets.add(window)
    app.ui_scale.apply_new(full=False)
    window.update_idletasks()
    for scroll in (file_page,studio_page):
        scroll.canvas.configure(height=scroll.inner.winfo_reqheight())
    from review_windows import monitor_rect
    present(window,app.root,work_area=monitor_rect(app.root,work=True))
    window.bind('<Escape>',lambda e:close())
    window.export_controls={'refresh':refresh,'send':send,'file_export':file_export,'state':state,'target':target,'combo':combo,'tabs':tabs,'mix':mix}
    window.export_controls.update(skip=skip,refresh_spinner=refresh_spinner,import_spinner=import_spinner,file_format=file_format,timeline_markers=timeline_marks,preferences=preferences,fix_bookmarks=fix_bookmarks,fix_bookmarks_control=fix_row.control,fix_bookmarks_help=fix_help)
    window.export_controls.update(folders=folders,studio_folders=studio_folders,payload=payload,skip_warning=skip_warning,fps=fps,name=name,
        warning_toggle=warning_toggle,warning_preference_changed=warning_preference_changed,format_summary=format_summary)
    for variable in (mix,timeline_marks,fps,name,file_format,fix_bookmarks,skip):variable.trace_add('write',schedule_preferences)
    tabs.bind('<<NotebookTabChanged>>',schedule_preferences,add='+')
    window.bind('<Destroy>',lambda event:shared_preferences() if event.widget==window else None,add='+')
    own_variables(window,mix,timeline_marks,fps,name,file_format,file_hint,format_summary,message,target,skip,status,fix_bookmarks,skip_warning,*folders.variables.values())
    poll()
