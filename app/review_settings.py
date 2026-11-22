# SPDX-License-Identifier: GPL-3.0-or-later
"""Playback and palette editors, leaving changes staged until Settings is saved."""
from datetime import datetime
import tkinter as tk
from tkinter import ttk,colorchooser
import review_theme as theme
import review_help as help_ui


DECODERS = {
    'auto':'Auto', 'no':'Software', 'd3d11va':'D3D11VA (Windows GPU)',
    'd3d11va-copy':'D3D11VA (copy back)', 'nvdec':'NVDEC (NVIDIA)', 'nvdec-copy':'NVDEC (copy back)',
}
DECODER_WARNING = "It is NOT recommended to change this setting if you don't know what you're doing."


class PlaybackEditor:
    def __init__(self,parent,settings,other=None):
        self.settings,self.variables,self.rules=settings,{},{}
        miscellaneous=ttk.LabelFrame(other,text='Organization And Storage',padding=12) if other else None
        if miscellaneous:miscellaneous.pack(fill='x',pady=(0,12))
        misc_row=[0]
        misc_keys={('app','auto_advance'),('app','undo_limit'),('timeline','right_click_existing'),('archive','start_on_launch'),('archive','show_warning'),('trimming','original_name'),
                   *((section,key) for section in ('thumbnails','waveform') for key in ('delete_on_close','delete_after_30_days'))}
        def destination(box,row,section,key):
            if miscellaneous is not None and (section,key) in misc_keys:
                row=misc_row[0];misc_row[0]+=1;box=miscellaneous
            return box,row
        left=ttk.LabelFrame(parent,text='Playback',padding=(8,12))
        right=ttk.LabelFrame(parent,text='Magnifier',padding=(6,12))
        left.grid(row=0,column=0,sticky='nsew',padx=(0,6));right.grid(row=0,column=1,sticky='nsew')
        def number(box,row,section,key,label,low,high,integer=False):
            box,row=destination(box,row,section,key)
            help_ui.label(box,label,help_ui.HELP[section,key]).grid(row=row,column=0,sticky='w',pady=5,padx=(0,4))
            var=tk.StringVar(value=settings.data[section][key]);self.variables[section,key]=var
            self.rules[section,key]=(low,high,integer,label)
            ttk.Entry(box,textvariable=var,width=9).grid(row=row,column=1,sticky='e')
        def check(box,row,section,key,label):
            box,row=destination(box,row,section,key)
            var=tk.BooleanVar(value=settings.data.getboolean(section,key));self.variables[section,key]=var
            control=help_ui.check(box,label,var,help_ui.HELP[section,key],command=lambda:self.retention_changed(section,key))
            control.grid(row=row,column=0,columnspan=2,sticky='w',pady=5)
        number(left,0,'app','seek_small','Small skip (seconds)',.1,120)
        number(left,1,'app','seek_large','Large skip (seconds)',.1,120)
        number(left,2,'app','speed_reset_seconds','Speed-repeat reset (seconds)',.1,120)
        number(left,3,'scrubbing','audio_grain_ms','Scrub audio fragment (ms)',10,200,True)
        number(left,15,'app','frame_repeat_fps','Held frame steps / second',1,120)
        number(left,16,'app','frame_repeat_delay_ms','Frame hold delay (ms)',0,10000,True)
        check(left,17,'app','timecode_frames','Show frames in timecode')
        check(left,18,'archive','start_on_launch','Always start in Archive Tools')
        check(left,19,'archive','show_warning','Show Archive Tools warning')
        check(left,20,'trimming','original_name','Rename trims and merges to original clip name')
        check(left,21,'app','media_play_pause','Keyboard media Play/Pause button')
        ttk.Label(left,text='When enabled, controls ClipComb Pro while open,\nincluding in the background.',style='Hint.TLabel').grid(row=22,column=0,columnspan=2,sticky='w')
        check(left,4,'app','autoplay','Play automatically on opening a clip')
        check(left,5,'app','auto_advance','Advance after a sorting decision')
        check(left,6,'scrubbing','stop_playback','Stop playback on playhead move')
        check(left,7,'waveform','enabled','Show audio waveforms')
        check(left,8,'app','remember_position','Remember clip position')
        check(left,9,'thumbnails','delete_on_close','Delete thumbnails on app close')
        check(left,10,'thumbnails','delete_after_30_days','Delete thumbnails after 30 days')
        check(left,11,'waveform','delete_on_close','Delete waveforms on app close')
        check(left,12,'waveform','delete_after_30_days','Delete waveforms after 30 days')
        check(left,13,'timeline','right_click_existing','Right click interacts with existing marks')
        ttk.Label(left,text='Waveforms load only for the current clip.\nPreviously generated peaks are cached.',
                  style='Hint.TLabel').grid(row=14,column=0,columnspan=2,sticky='w',pady=(6,0))
        number(right,0,'magnifier','width','Window width (pixels)',128,1600,True)
        number(right,1,'magnifier','height','Window height (pixels)',128,1200,True)
        number(right,2,'magnifier','refresh_ms','Pointer update interval (ms)',2,100,True)
        number(right,3,'magnifier','capture_ms','Video refresh interval (ms)',8,200,True)
        check(right,4,'magnifier','smoothing','Smooth image scaling')
        help_ui.label(right,'Rendering method',help_ui.HELP['magnifier','mode']).grid(row=5,column=0,sticky='w',pady=5)
        automatic='Automatic (RECOMMENDED)'
        mode=tk.StringVar(value=automatic if settings.data['magnifier']['mode']=='Automatic' else settings.data['magnifier']['mode']);self.variables['magnifier','mode']=mode
        mode.trace_add('write',lambda *_:mode.set(automatic) if mode.get()=='Automatic' else None)
        ttk.Combobox(right,textvariable=mode,values=[automatic,'Live overlay','Frame capture'],state='readonly',width=27).grid(row=5,column=0,columnspan=2,sticky='e',padx=(132,0))
        ttk.Label(right,text='Live overlay refreshes through Windows.\nCapture interval applies only to Frame capture.',
                  style='Hint.TLabel').grid(row=6,column=0,columnspan=2,sticky='w',pady=8)
        number(right,7,'app','undo_limit','Saved Undo actions',0,float('inf'),True)
        check(right,8,'magnifier','show_cursor','Show cursor while magnifying')
        tools=ttk.LabelFrame(other or parent,text='Media Tools',padding=12)
        if other:tools.pack(fill='x',pady=(0,12))
        else:tools.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(12,0))
        for row,(section,key,label) in enumerate([
            ('tools','mpv_library','libmpv-2.dll (blank = bundled)'),
            ('tools','ffprobe','FFprobe (blank = bundled / auto)'),
            ('tools','ffmpeg','FFmpeg waveform decoder (blank = bundled / auto)'),
            ('tools','hardware_decoding','Hardware decoding'),
            ('tools','resolve_folder','Resolve installation folder (blank = automatic)'),
        ]):
            help_ui.label(tools,label,help_ui.HELP[section,key]).grid(row=row,column=0,sticky='w',padx=(0,12),pady=4)
            var=tk.StringVar(value=settings.data[section][key]);self.variables[section,key]=var
            if (section,key)==('tools','hardware_decoding'):
                self.decoder=ttk.Combobox(tools,values=tuple(DECODERS.values()),state='readonly',width=34)
                self.decoder.grid(row=row,column=1,sticky='ew')
                self.decoder.set(DECODERS.get(var.get(),'Auto'))
                var.trace_add('write',lambda *_,value=var:self.decoder.set(DECODERS.get(value.get(),'Auto')))
                self.decoder.bind('<<ComboboxSelected>>',self.decoder_changed)
            else:
                ttk.Entry(tools,textvariable=var,width=34).grid(row=row,column=1,sticky='ew')
        tools.columnconfigure(1,weight=1)
        parent.columnconfigure(0,weight=1);parent.columnconfigure(1,weight=1)

    def decoder_changed(self, event=None):
        var=self.variables['tools','hardware_decoding']
        selected=next((key for key,label in DECODERS.items() if label==self.decoder.get()),'auto')
        if selected==var.get():return
        if selected!='auto':
            parent=self.decoder.winfo_toplevel()
            previous=parent.grab_current()
            accepted=theme.confirm_action(parent,'Are you sure?',DECODER_WARNING,'Change Decoder')
            if previous and previous.winfo_exists():previous.grab_set()
            if not accepted:
                self.decoder.set(DECODERS.get(var.get(),'Auto'))
                return
        var.set(selected)

    def retention_changed(self,section,key):
        if section in ('thumbnails','waveform') and key in ('delete_on_close','delete_after_30_days') and self.variables[section,key].get():
            other='delete_on_close' if key=='delete_after_30_days' else 'delete_after_30_days'
            self.variables[section,other].set(False)

    def values(self):
        values={}
        for (section,key),var in self.variables.items():
            value=var.get()
            if isinstance(var,tk.BooleanVar):value='yes' if value else 'no'
            elif (section,key) in self.rules:
                if (section,key)==('app','undo_limit'):
                    from review_history import limit_value
                    values[section,key]=str(limit_value(value));continue
                low,high,integer,label=self.rules[section,key]
                try:parsed=float(value)
                except ValueError:raise ValueError(label+' must be a number.')
                if not low<=parsed<=high or integer and parsed!=int(parsed):
                    raise ValueError(f'{label} must be between {low:g} and {high:g}'+(' (whole numbers).' if integer else '.'))
                value=str(int(parsed)) if integer else str(parsed)
            else:value=value.strip().strip('"')
            values[section,key]=value
        if values['magnifier','mode']=='Automatic (RECOMMENDED)':values['magnifier','mode']='Automatic'
        if values['magnifier','mode'] not in ('Automatic','Live overlay','Frame capture'):
            raise ValueError('Choose Automatic, Live overlay or Frame capture for the magnifier.')
        if values['tools','hardware_decoding'] not in DECODERS:
            raise ValueError('Choose a hardware decoding option from the dropdown.')
        for section in ('thumbnails','waveform'):
            if values[section,'delete_after_30_days']=='yes':values[section,'delete_on_close']='no'
        return values


class AudioEditor:
    def __init__(self,parent,settings,date_enabled,enumerate_devices=lambda:[('auto','Default')]):
        self.variables={};self.rows={};self.settings=settings;self.date_enabled=date_enabled
        from review_audio_devices import DevicePicker
        device=tk.StringVar(value=settings.data['audio'].get('output_device','auto'));self.variables['audio','output_device']=device
        self.device_picker=DevicePicker(parent,device,enumerate_devices);self.device_picker.pack(fill='x',pady=(0,12))
        enabled=tk.BooleanVar(value=settings.data.getboolean('audio','date_profiles_enabled'))
        self.variables['audio','date_profiles_enabled']=enabled
        row=ttk.Frame(parent);row.pack(fill='x',pady=(0,12))
        tip="If you're ever changed the audio track layout of your clips, this feature is for you. It automatically changes the audio track layout by date. So for example if your microphone is on Track 1 in your older recordings, but you later switched it to Track 3, this makes it easy to account for the different track layout without changing the default track layout for all the clips you're managing.\n\nIf you're unsure what that means, leave this setting off."
        toggle=ttk.Checkbutton(row,text='Use audio layouts by date',variable=enabled,command=self.date_changed);toggle.pack(side='left')
        help_ui.Tooltip(toggle,tip);help_ui.badge(row,tip).pack(side='left')
        from review_audio import profile_choices
        default=tk.StringVar(value=settings.data['audio']['default_profile'])
        choices=profile_choices(enabled.get())
        self.date_default=default.get() if default.get() not in profile_choices(False) else 'Auto by date'
        if default.get() not in choices:default.set('Configured tracks')
        self.variables['audio','default_profile']=default
        row=ttk.Frame(parent);row.pack(fill='x',pady=(0,12))
        help_ui.label(row,'Default audio layout','Used when a clip has no saved layout. Existing clip choices and mixes stay intact.\n\nDefault: Configured tracks.').pack(side='left',padx=(0,4))
        self.default_combo=ttk.Combobox(row,textvariable=default,values=choices,state='readonly',width=23);self.default_combo.pack(side='left')
        row=ttk.Frame(parent);row.pack(fill='x',pady=(0,12));self.date_row=row
        help_ui.label(row,'Track format change date',help_ui.HELP['audio','layout_change']).pack(side='left',padx=(0,4))
        cutoff=tk.StringVar(value=settings.data['audio']['layout_change']);self.variables['audio','layout_change']=cutoff
        from review_date_picker import DateTimePicker
        self.date_picker=DateTimePicker(row,cutoff);self.date_picker.pack(side='left')
        self.mix_help=ttk.Label(parent,text='Name tracks and choose starting levels for newly opened clips.\nSaved clip mixes are preserved. You can still change their levels in the mixer.',style='Hint.TLabel');self.mix_help.pack(anchor='w',pady=(0,12))
        tabs=ttk.Notebook(parent);tabs.pack(fill='both',expand=True)
        layouts=[('configured','Configured tracks'),('modern','Newer recordings'),('legacy','Older recordings')];self.pages={}
        for key,title in layouts:
            page=ttk.Frame(tabs,padding=12);tabs.add(page,text=title);self.pages[key]=page
            for column,title_ in enumerate(['Track','Name','Audible','Level %']):
                help_ui.label(page,title_, 'Track name and initial mix for this layout. Controls correspond to source audio stream numbers, not speaker channels.\n\nDefault: Names and levels from the original layout; 100% volume.').grid(row=0,column=column,sticky='w',padx=5,pady=(0,8))
            names=settings.data['audio'][key+'_names'].split('|')
            enabled={int(n) for n in settings.data['audio'][key+'_enabled'].split(',') if n.strip().isdigit()}
            levels=settings.data['audio'][key+'_volumes'].split(',')
            self.rows[key]=[]
            for i in range(max(6,len(names))):
                name=tk.StringVar(value=names[i] if i<len(names) else f'Track {i+1}')
                on=tk.BooleanVar(value=i+1 in enabled);level=tk.StringVar(value=levels[i] if i<len(levels) else '100')
                self.rows[key].append((name,on,level))
                defaults=help_ui.DEFAULTS['audio'];factory_names=defaults[key+'_names'].split('|');factory_levels=defaults[key+'_volumes'].split(',')
                description=f'Audio stream {i+1}. The name is shown in the mixer and exports for this layout. Audible and Level set its starting mix for clips without saved levels.\n\nDefault name: {factory_names[i] if i<len(factory_names) else "Track "+str(i+1)}. Audible: {"On" if str(i+1) in defaults[key+"_enabled"].split(",") else "Off"}. Level: {factory_levels[i] if i<len(factory_levels) else "100"}%.'
                help_ui.label(page,str(i+1),description).grid(row=i+1,column=0,padx=5,pady=5)
                ttk.Entry(page,textvariable=name,width=32).grid(row=i+1,column=1,sticky='ew',padx=5)
                ttk.Checkbutton(page,variable=on).grid(row=i+1,column=2,padx=15)
                ttk.Spinbox(page,textvariable=level,from_=0,to=150,width=7).grid(row=i+1,column=3,padx=5)
            page.columnconfigure(1,weight=1)
        self.tabs=tabs
        self.date_changed(initial=True)
    def date_changed(self,initial=False):
        from review_audio import profile_choices
        enabled=self.variables['audio','date_profiles_enabled'].get();default=self.variables['audio','default_profile']
        self.default_combo.configure(values=profile_choices(enabled))
        if enabled:
            self.date_row.pack(fill='x',pady=(0,12),before=self.mix_help)
            for key in ('modern','legacy'):self.tabs.add(self.pages[key])
            if not initial and default.get()=='Configured tracks':default.set(self.date_default)
        else:
            self.date_row.pack_forget()
            for key in ('modern','legacy'):self.tabs.hide(self.pages[key])
            if default.get() not in profile_choices(False):self.date_default=default.get();default.set('Configured tracks')
        self.date_enabled=enabled
    def values(self):
        import math
        values={key:('yes' if var.get() else 'no') if isinstance(var,tk.BooleanVar) else var.get().strip() for key,var in self.variables.items()}
        if self.date_enabled:datetime.fromisoformat(values['audio','layout_change'])
        for key,rows in self.rows.items():
            names=[];enabled=[];levels=[]
            for i,(name,on,level) in enumerate(rows):
                title=name.get().strip() or f'Track {i+1}'
                if '|' in title:raise ValueError('Track names cannot contain |.')
                try:number=float(level.get())
                except ValueError:raise ValueError('Audio levels must be numbers from 0 to 150%.')
                if not math.isfinite(number) or not 0<=number<=150:raise ValueError('Audio levels must be from 0 to 150%.')
                names.append(title);levels.append(f'{number:g}')
                if on.get():enabled.append(str(i+1))
            values['audio',key+'_names']='|'.join(names);values['audio',key+'_enabled']=','.join(enabled);values['audio',key+'_volumes']=','.join(levels)
        return values
    def reset(self,defaults):
        for (section,key),var in self.variables.items():var.set(defaults.getboolean(section,key) if isinstance(var,tk.BooleanVar) else defaults[section][key])
        self.date_default='Auto by date'
        self.date_changed(initial=True)
        for key,rows in self.rows.items():
            names=defaults['audio'][key+'_names'].split('|');enabled=defaults['audio'][key+'_enabled'].split(',');levels=defaults['audio'][key+'_volumes'].split(',')
            for i,(name,on,level) in enumerate(rows):
                name.set(names[i] if i<len(names) else f'Track {i+1}');on.set(str(i+1) in enabled);level.set(levels[i] if i<len(levels) else '100')


from review_theme_editor import ThemeEditor
