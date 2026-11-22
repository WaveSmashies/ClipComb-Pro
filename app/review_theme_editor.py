# SPDX-License-Identifier: GPL-3.0-or-later
"""Live palette editing; active preferences are committed only by Save settings."""
import tkinter as tk
from tkinter import ttk,colorchooser
import review_theme as theme
from review_theme_files import ThemeStore,configured_versions,light_palette
from review_marker_colors import PaletteEditor
from review_help import label,check
from review_dialogs import own_variables

class ThemeEditor:
    def __init__(self,parent,settings,palette,preview):
        self.settings,self.preview,self.parent=settings,preview,parent
        self.loading=True;self.timer=None;self.store=ThemeStore(settings.path.parent)
        self.versions=configured_versions(settings);self.was_light=settings.data.getboolean('theme','light_mode')
        self.light=tk.BooleanVar(value=self.was_light);self.preset=tk.StringVar(value=settings.data['theme']['preset'])
        if self.preset.get() not in theme.PRESETS and self.preset.get() not in self.store.list():self.preset.set('Custom')
        row=ttk.Frame(parent);row.pack(fill='x',pady=(0,12))
        label(row,'Color palette','Changes apply immediately. Save settings keeps your choice; Cancel restores it. Theme files in Themes beside the EXE can be shared.\n\nDefault: Default, Light mode off.').pack(side='left',padx=(0,8))
        self.choice=ttk.Combobox(row,textvariable=self.preset,state='readonly',width=23)
        self.choice.pack(side='left');self.choice.bind('<<ComboboxSelected>>',self.select);self.refresh_choices()
        check(row,'Light mode',self.light,'Use the matching light palette, keeping the pastel hue. Each saved theme includes dark and light colors.\n\nDefault: Off.',command=self.toggle_light).pack(side='left',padx=12)
        self.variables={};self.swatches={};grid=ttk.Frame(parent);grid.pack(fill='x')
        for index,(key,title) in enumerate(theme.COLOR_LABELS.items()):
            row,col=(index%8,index//8*3) if index<16 else (8+(index-16)//2,((index-16)%2)*3)
            label(grid,title,'This color updates the app immediately. Enter #RRGGBB or choose the swatch.\n\nDefault: '+theme.DEFAULT_PALETTE[key]+'.').grid(row=row,column=col,sticky='w',pady=5,padx=(0,8))
            value=tk.StringVar();self.variables[key]=value
            swatch=tk.Button(grid,width=3,relief='flat',command=lambda k=key:self.pick(k));swatch.grid(row=row,column=col+1,padx=(0,6));self.swatches[key]=swatch
            ttk.Entry(grid,textvariable=value,width=10).grid(row=row,column=col+2,padx=(0,16))
            value.trace_add('write',lambda *_,k=key:self.edited(k))
        buttons=ttk.Frame(parent);buttons.pack(fill='x',pady=(15,0))
        ttk.Button(buttons,text='Save Theme',style='Round.TButton',command=self.save_theme).pack(side='left')
        self.delete_button=ttk.Button(buttons,text='Delete Theme',style='Round.TButton',command=self.delete_theme);self.delete_button.pack(side='left',padx=8)
        ttk.Button(buttons,text='Original colors',style='Round.TButton',command=self.original).pack(side='left')
        ttk.Label(parent,text='Changes are live. Save settings keeps them; Cancel restores your previous theme.\nSaved theme files live in Themes beside the app.',style='Hint.TLabel').pack(anchor='w',pady=12)
        self.bookmarks=PaletteEditor(parent,settings);self.bookmarks.on_change=self.show_preview
        self.loading=False;self.display()
    def refresh_choices(self):self.choice.configure(values=[*theme.PRESETS,'Custom',*self.store.list()])
    def remember(self):
        try:self.versions['light' if self.was_light else 'dark']=self.values()
        except ValueError:pass
    def display(self):
        self.loading=True
        for key,value in self.versions['light' if self.light.get() else 'dark'].items():
            self.variables[key].set(value);self.swatches[key].configure(bg=value,activebackground=value)
        self.was_light=self.light.get();self.loading=False
        self.delete_button.configure(state='normal' if self.preset.get() in self.store.list() else 'disabled')
        self.show_preview()
    def select(self,event=None):
        name=self.preset.get()
        if name in theme.PRESETS:
            dark=dict(theme.PRESETS[name]);self.versions={'dark':dark,'light':light_palette(dark)}
        elif name in (saved:=self.store.list()):
            record=saved[name][1];self.versions=record['versions']
            if record['bookmarks']:
                from review_marker_colors import palette
                name=record['bookmarks'].get('palette','DaVinci Resolve')
                self.bookmarks.choice.set('DaVinci Resolve' if name=='Resolve' else name)
                self.bookmarks.colors=list(palette(record['bookmarks']));self.bookmarks.refresh()
                from review_marker_colors import PRESETS
                self.bookmarks.base_palette=record['bookmarks'].get('base_palette') or (name if name in PRESETS else max(PRESETS,key=lambda key:sum(a==b for a,b in zip(self.bookmarks.colors,PRESETS[key]))))
        self.display()
    def toggle_light(self):self.remember();self.display()
    def edited(self,key):
        if self.loading:return
        self.preset.set('Custom')
        try:
            value=theme.valid_color(self.variables[key].get());self.swatches[key].configure(bg=value,activebackground=value)
            self.versions['light' if self.light.get() else 'dark'][key]=value
            self.show_preview()
        except ValueError:pass
    def pick(self,key):
        chosen=colorchooser.askcolor(self.variables[key].get(),parent=self.parent.winfo_toplevel())[1]
        if chosen:self.variables[key].set(chosen)
    def values(self):return {key:theme.valid_color(value.get()) for key,value in self.variables.items()}
    def show_preview(self):
        if self.loading:return
        try:self.preview(self.values(),marker_colors=self.bookmarks.colors,light_mode=self.light.get())
        except (ValueError,tk.TclError):pass
    def original(self):self.preset.set('Default');self.select()
    def save_theme(self):
        window=theme.dialog(self.parent.winfo_toplevel(),'Save Theme');page=ttk.Frame(window,padding=18);page.pack(fill='both',expand=True)
        ttk.Label(page,text='Theme name').pack(anchor='w');name=tk.StringVar(value=self.preset.get().removesuffix(' - Custom') if self.preset.get() in self.store.list() else '')
        entry=ttk.Entry(page,textvariable=name,width=35);entry.pack(fill='x',pady=10)
        def save():
            try:
                self.remember();title=name.get().strip();label_=title+' - Custom'
                if label_ in self.store.list() and not theme.confirm_action(window,'Replace theme?',f'Replace {title} in your Themes folder?','Replace'):return
                self.store.save(title,self.versions,{'palette':self.bookmarks.choice.get(),'base_palette':self.bookmarks.base_palette,'custom_colors':','.join(self.bookmarks.colors)})
                self.refresh_choices();self.preset.set(label_);self.display();window.destroy()
            except (ValueError,OSError) as error:theme.show_error(window,'Could not save theme',str(error))
        ttk.Button(page,text='Save',style='Primary.TButton',command=save).pack(side='right');ttk.Button(page,text='Cancel',command=window.destroy,style='Round.TButton').pack(side='right',padx=6)
        window.theme_name_controls={'name':name,'save':save};own_variables(window,name);theme.present(window,self.parent.winfo_toplevel());entry.focus_set();entry.bind('<Return>',lambda e:save())
    def delete_theme(self):
        name=self.preset.get()
        if name not in self.store.list():return
        if theme.confirm_action(self.parent.winfo_toplevel(),'Delete theme?',f'Delete {name.removesuffix(" - Custom")} from your Themes folder?','Delete'):
            self.store.delete(name);self.refresh_choices();self.preset.set('Custom');self.display()
    def commit(self):
        self.remember();cfg=self.settings.data['theme'];cfg.update(preset=self.preset.get(),light_mode='yes' if self.light.get() else 'no')
        for version,prefix in [('dark','custom_'),('light','light_custom_')]:cfg.update({prefix+k:v for k,v in self.versions[version].items()})
        self.bookmarks.commit();return self.values()
