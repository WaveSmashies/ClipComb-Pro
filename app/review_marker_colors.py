# SPDX-License-Identifier: GPL-3.0-or-later
"""Stable bookmark color slots. Display customization never changes export meaning."""
import re

NAMES=('Blue','Cyan','Green','Yellow','Red','Pink','Purple','Fuchsia','Rose','Lavender',
       'Sky','Mint','Lemon','Sand','Cocoa','Cream')
RESOLVE=('#008dff','#00d2d8','#38dc00','#ffb500','#ff4510','#ff4ee3','#a900ff','#b90075',
         '#ff9bba','#a99acb','#92d3ef','#a8dd00','#e1e660','#cda15d','#715041','#fff0dc')
PREMIERE=('#508cff','#2ec8d2','#54a854','#e59a51','#d25e55','#ba75cf','#8b66ba','#ba75cf',
          '#d25e55','#8b66ba','#508cff','#54a854','#e5cf55','#e59a51','#e59a51','#eeeeee')
KDENLIVE=('#3daee9','#1abc9c','#2ecc71','#f1c40f','#e74c3c','#e477c7','#9b59b6','#9b59b6',
          '#e74c3c','#9b59b6','#3daee9','#2ecc71','#f1c40f','#f39c12','#f39c12','#eeeeee')
# Standard FCPXML bookmarks have no arbitrary color attribute. Display that
# standard blue consistently, rather than turning bookmarks into to-do/chapter types.
PRESETS={'DaVinci Resolve':RESOLVE,'Premiere Pro':PREMIERE,'Final Cut Pro':('#3988e8',)*16,'Kdenlive':KDENLIVE}
COLOR_NAMES={'DaVinci Resolve':NAMES,
 'Premiere Pro':('Blue','Cyan','Green','Orange','Red','Purple','Violet','Purple','Red','Violet','Blue','Green','Yellow','Orange','Orange','White'),
 'Kdenlive':('Blue','Turquoise','Green','Yellow','Red','Pink','Purple','Purple','Red','Purple','Blue','Green','Yellow','Orange','Orange','White')}


def color_name(index,colors,config=None):
    if config and config.get('palette')=='Final Cut Pro':return ''
    selected=config.get('palette','') if config else ''
    base=selected if selected in PRESETS else config.get('base_palette','') if config else ''
    if base not in PRESETS or config is not None and tuple(colors)!=tuple(palette(config)):
        base=max(PRESETS,key=lambda name:sum(a==b for a,b in zip(colors,PRESETS[name])))
    if base=='Final Cut Pro' or colors[index].lower()!=PRESETS[base][index].lower():return ''
    return COLOR_NAMES[base][index].lower()
OTIO=('BLUE','CYAN','GREEN','YELLOW','RED','PINK','PURPLE','MAGENTA','PINK','PURPLE',
      'CYAN','GREEN','YELLOW','ORANGE','ORANGE','WHITE')
PREMIERE_INDEX=(6,7,0,3,1,2,2,2,1,2,6,0,4,3,3,5)
# Resolve's OTIO reader recognizes nine colors. Unsupported OTIO colors such
# as ORANGE otherwise silently become Green; use its nearest supported label.
RESOLVE_OTIO=('BLUE','CYAN','GREEN','YELLOW','RED','PINK','PURPLE','PINK','PINK','MAGENTA',
              'CYAN','GREEN','YELLOW','YELLOW','BLACK','WHITE')


def slot(marker):
    try:return max(0,min(15,int(marker.get('color_slot',0))))
    except (ValueError,TypeError):return 0


def palette(config):
    values=config.get('custom_colors','').split(',')
    if config.get('palette','DaVinci Resolve')=='Custom' and len(values)==16 and all(re.fullmatch(r'#[0-9a-fA-F]{6}',s) for s in values):return tuple(values)
    return PRESETS.get(config.get('palette','DaVinci Resolve'),RESOLVE)


class PaletteEditor:
    def __init__(self,parent,settings):
        import tkinter as tk
        from tkinter import ttk,colorchooser
        from review_help import label
        self.settings=settings;self.colors=list(palette(settings.data['bookmarks']))
        self.base_palette=(settings.data['bookmarks'].get('base_palette') or max(PRESETS,key=lambda name:sum(a==b for a,b in zip(self.colors,PRESETS[name])))) if settings.data['bookmarks']['palette']=='Custom' else settings.data['bookmarks']['palette']
        self.on_change=lambda:None
        box=ttk.LabelFrame(parent,text='Bookmark colors',padding=12);box.pack(fill='x',pady=(14,0))
        row=ttk.Frame(box);row.pack(fill='x')
        label(row,'Display palette','Choose bookmark display colors. Slot numbers have stable export meanings: changing custom slot 4 to pink still exports Resolve slot 4 (Yellow/amber). Editors with fewer native colors use the nearest supported color. Standard Final Cut bookmarks support blue; this does not turn them into chapter/to-do markers.\n\nDefault: Resolve; new bookmarks use slot 1, Blue.').pack(side='left',padx=(0,8))
        name=settings.data['bookmarks']['palette'];self.choice=tk.StringVar(value='DaVinci Resolve' if name=='Resolve' else name)
        combo=ttk.Combobox(row,textvariable=self.choice,values=[*PRESETS,'Custom'],state='readonly',width=19)
        combo.pack(side='left');combo.bind('<<ComboboxSelected>>',self.select)
        self.swatches=[];swatches=ttk.Frame(box);swatches.pack(fill='x',pady=9)
        for i,color in enumerate(self.colors):
            button=tk.Button(swatches,text=str(i+1),width=3,bg=color,fg='#111111',relief='flat',
                             command=lambda n=i:self.pick(n))
            button.grid(row=i//8,column=i%8,padx=3,pady=3);self.swatches.append(button)
        ttk.Label(box,text='Click a swatch to customize it. Export color identity follows the slot number,\nnot the custom display color. Final Cut’s standard bookmarks have one color.',style='Hint.TLabel').pack(anchor='w')

    def refresh(self):
        for i,button in enumerate(self.swatches):button.configure(bg=self.colors[i],activebackground=self.colors[i])

    def select(self,event=None):
        if self.choice.get()=='Custom':
            config=dict(self.settings.data['bookmarks']);config['palette']='Custom'
            self.colors=list(palette(config))
        else:self.base_palette=self.choice.get();self.colors=list(PRESETS[self.choice.get()])
        self.refresh()
        self.on_change()

    def pick(self,index):
        from tkinter import colorchooser
        color=colorchooser.askcolor(self.colors[index],parent=self.swatches[index].winfo_toplevel())[1]
        if color:self.choice.set('Custom');self.colors[index]=color;self.refresh();self.on_change()

    def commit(self):
        self.settings.data['bookmarks'].update(palette=self.choice.get(),base_palette=self.base_palette,custom_colors=','.join(self.colors))

    def reset(self):
        self.base_palette='DaVinci Resolve';self.choice.set('DaVinci Resolve');self.colors=list(RESOLVE);self.refresh()
        self.on_change()
