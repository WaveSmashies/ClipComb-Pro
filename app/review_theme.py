# SPDX-License-Identifier: GPL-3.0-or-later
"""Dark Windows theme and small native-looking dialogs."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import string
import re
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageDraw,ImageTk
from review_icons import apply_window_icon


BG = "#101218"
PANEL = "#181c26"
INPUT = "#202533"
BORDER = "#31394b"
TEXT = "#eef1f8"
MUTED = "#a4aec3"
ACCENT = "#bd9aff"
ACCENT_DARK = "#4a386a"
GREEN = "#a0e4bd"
VIDEO = "#090b10"

DEFAULT_PALETTE = {
    'background': BG, 'panel': PANEL, 'input': INPUT, 'border': BORDER,
    'text': TEXT, 'muted_text': MUTED, 'normal_button': INPUT,
    'highlighted_button':'#a47df0', 'button_text':TEXT, 'highlighted_button_text':'#111019',
    'highlighted_clip':ACCENT_DARK, 'selection':ACCENT, 'selection_fill':ACCENT_DARK,
    'waveform':'#b39ae0', 'playhead':TEXT, 'video_background':VIDEO,'level_meter':'#13ff0d',
}
COLOR_LABELS = {
    'background':'Background','panel':'Panels','input':'Inputs / headings','border':'Borders',
    'text':'Text','muted_text':'Secondary text','normal_button':'Normal buttons',
    'highlighted_button':'Highlighted buttons / sliders','button_text':'Normal button text',
    'highlighted_button_text':'Highlighted button text','highlighted_clip':'Highlighted clip',
    'selection':'Selection edges / highlight','selection_fill':'In/Out selection fill',
    'waveform':'Audio waveform','playhead':'Playhead / range numbers','video_background':'Video background','level_meter':'Volume meter',
}
def blend(color,other,amount):
    a,b = bytes.fromhex(color[1:]),bytes.fromhex(other[1:])
    return '#'+''.join(f'{round(x*(1-amount)+y*amount):02x}' for x,y in zip(a,b))


PRESETS = {'Default':DEFAULT_PALETTE}
for _name,_accent,_bg,_panel in (
    ('Lavender','#cbbaff','#15111f','#241c32'),('Rose','#ffb4c8','#1d1219','#30202a'),
    ('Peach','#ffbd8d','#1d1511','#30251e'),('Kachow','#ffaaa5','#211315','#352125'),('Sunshine','#f2d463','#1b180f','#2d291d'),
    ('Mint','#a4d990','#101a15','#1c2b23'),('Sky','#9acbff','#101722','#1c2838'),
):
    PRESETS[_name] = dict(DEFAULT_PALETTE,background=_bg,panel=_panel,
                         highlighted_button=_accent,selection=_accent,waveform=_accent,level_meter='#13ff0d',
                         input=_panel,border=blend(_panel,_accent,.26),
                         normal_button=blend(_panel,_accent,.09),muted_text=blend(_accent,'#d5dae5',.48),
                         highlighted_clip=blend(_panel,_accent,.24),selection_fill=blend(_panel,_accent,.24))

PRESETS['Kachow']=dict(DEFAULT_PALETTE,background='#211315',panel='#352125',input='#352125',
    border='#6a4546',muted_text='#ebc1c4',normal_button='#472d31',highlighted_button='#ff726a',
    highlighted_clip='#8d1b1e',selection='#ff6b64',selection_fill='#654244',waveform='#ff645b',level_meter='#13ff0d')

from review_brand import THEME_NAMES
PRESETS['Grey Mann']=dict(DEFAULT_PALETTE,background='#141414',panel='#1e1e1e',input='#292929',border='#3d3d3d',
    text='#f3f3f3',muted_text='#b3b3b3',normal_button='#292929',highlighted_button='#acb7bf',button_text='#f3f3f3',
    highlighted_button_text='#141414',highlighted_clip='#505050',selection='#b9bfdf',selection_fill='#505050',
    waveform='#b3b5c8',playhead='#eef1f8',video_background='#090b10',level_meter='#13ff0d')
PRESETS={THEME_NAMES.get(name,name):colors for name,colors in PRESETS.items()}


def valid_color(value):
    if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(value)):
        raise ValueError('Use a six-digit color, such as #bd9aff.')
    return value.lower()


def palette_for_settings(settings):
    from review_theme_files import configured_versions
    return dict(configured_versions(settings)['light' if settings.data.getboolean('theme','light_mode') else 'dark'])


def dark_title(window):
    batch=getattr(window._root(),'review_theme_batch',None)
    if batch is not None:batch.add(window);return
    user = ctypes.windll.user32
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    hwnd = user.GetAncestor(window.winfo_id(), 2)
    setter = ctypes.windll.dwmapi.DwmSetWindowAttribute
    setter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    setter.restype = ctypes.c_long
    value = ctypes.c_int(0 if sum(bytes.fromhex(getattr(window,'review_palette',DEFAULT_PALETTE)['background'][1:]))>400 else 1)
    if setter(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)):
        setter(hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
    colors = getattr(window,'review_palette',DEFAULT_PALETTE)
    applied={'hwnd':hwnd,'background':colors['background'],'results':{}}
    for attribute, color in ((34, colors['border']), (35, colors['background']), (36, colors['text'])):
        red, green, blue = bytes.fromhex(color[1:])
        value = ctypes.c_uint32(red | green << 8 | blue << 16)
        applied['results'][attribute]=setter(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
    window.review_chrome_applied=applied


def theme_image(root,picture):
    scale=getattr(root,'review_scale',1)
    if scale!=1:picture=picture.resize((max(1,round(picture.width*scale)),max(1,round(picture.height*scale))),Image.Resampling.LANCZOS)
    pool=getattr(root,'review_image_pool',[]);index=root.review_image_index;root.review_image_index+=1
    if index<len(pool):
        photo=pool[index]
        if (int(root.tk.call('image','width',str(photo))),int(root.tk.call('image','height',str(photo))))!=picture.size:
            root.tk.call(str(photo),'configure','-width',picture.width,'-height',picture.height)
        photo.paste(picture)
    else:pool.append(ImageTk.PhotoImage(picture,master=root))
    root.review_image_pool=pool
    return pool[index]


def rounded_image(root, color, edge, size=28, radius=10):
    # Build the complete background in memory instead of one Tcl call per pixel.
    picture=Image.new('RGBA',(size,size))
    ImageDraw.Draw(picture).rounded_rectangle((0,0,size-1,size-1),radius=radius,fill=color,outline=edge,width=1)
    return theme_image(root,picture)


def control_image(root,fill,edge,kind='field',tick=None):
    scale=4
    width,height=(32,28) if kind=='check' else (32,32)
    im=Image.new('RGBA',(width*scale,height*scale))
    draw=ImageDraw.Draw(im)
    if kind=='arrow':
        draw.line([(10*scale,13*scale),(16*scale,19*scale),(22*scale,13*scale)],fill=edge,width=2*scale,joint='curve')
    else:
        box=(2*scale,2*scale,(25 if kind=='check' else 30)*scale,(25 if kind=='check' else 30)*scale)
        draw.rounded_rectangle(box,radius=(5 if kind=='check' else 8)*scale,fill=fill,outline=edge,width=scale)
        if tick:
            draw.line([(7*scale,14*scale),(11*scale,18*scale),(20*scale,9*scale)],fill=tick,width=3*scale,joint='curve')
    return theme_image(root,im.resize((width,height),Image.Resampling.LANCZOS))


def round_popup(root,event):
    path=str(event.widget)
    def update():
        try:
            user,gdi=ctypes.windll.user32,ctypes.windll.gdi32
            user.GetAncestor.argtypes,user.GetAncestor.restype=[wintypes.HWND,wintypes.UINT],wintypes.HWND
            user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
            user.SetWindowRgn.argtypes=[wintypes.HWND,wintypes.HANDLE,wintypes.BOOL]
            gdi.CreateRoundRectRgn.argtypes=[ctypes.c_int]*6;gdi.CreateRoundRectRgn.restype=wintypes.HANDLE
            gdi.DeleteObject.argtypes=[wintypes.HANDLE]
            hwnd=user.GetAncestor(int(root.tk.call('winfo','id',path),0),2)
            rect=wintypes.RECT();user.GetWindowRect(hwnd,ctypes.byref(rect))
            region=gdi.CreateRoundRectRgn(0,0,rect.right-rect.left+1,rect.bottom-rect.top+1,12,12)
            if not user.SetWindowRgn(hwnd,region,True):gdi.DeleteObject(region)
        except (tk.TclError,ValueError):pass
    root.after_idle(update)


def install_theme(root, palette=None):
    scale=getattr(root,'review_scale',1)
    root.review_image_index=0
    colors = dict(palette or DEFAULT_PALETTE)
    root.review_palette = colors
    BG,PANEL,INPUT,BORDER,TEXT,MUTED,ACCENT,ACCENT_DARK = (colors[k] for k in (
        'background','panel','input','border','text','muted_text','selection','selection_fill'))
    root.configure(bg=BG)
    for key, value in {
        "*TCombobox*Listbox.background": INPUT,
        "*TCombobox*Listbox.foreground": TEXT,
        "*TCombobox*Listbox.selectBackground": ACCENT_DARK,
        "*TCombobox*Listbox.selectForeground": TEXT,
    }.items():
        root.option_add(key, value)
    style = ttk.Style(root)
    if style.theme_use()!='clam':style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, focuscolor=ACCENT, troughcolor=BG, font=("Segoe UI", 10))
    style.configure("Heading.TLabel", font=("Segoe UI", 25, "bold"))
    style.configure("Subheading.TLabel", font=("Segoe UI", 12, "bold"))
    style.configure("Hint.TLabel", foreground=MUTED)
    style.configure("Accent.TLabel", foreground=ACCENT, font=("Segoe UI", 10, "bold"))
    style.configure('Speed.TLabel',foreground=ACCENT,font=('Segoe UI',26,'bold'))
    style.configure('Timecode.TLabel',foreground=TEXT,font=('Consolas',13))
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("Panel.TLabel", background=PANEL)
    style.configure("PanelHint.TLabel", background=PANEL, foreground=MUTED)
    style.configure("PanelHeading.TLabel", background=PANEL, font=("Segoe UI", 12, "bold"))
    style.configure('Help.TLabel',foreground=ACCENT,font=('Segoe UI',11,'bold'),background=BG)
    style.configure('PanelHelp.TLabel',foreground=ACCENT,font=('Segoe UI',11,'bold'),background=PANEL)
    style.configure("Rule.TFrame", background=BORDER)
    style.configure("Volume.Horizontal.TScale", background=ACCENT, troughcolor=PANEL)
    style.configure("TEntry", fieldbackground=INPUT, insertcolor=TEXT, padding=(9, 6))
    style.configure('TSpinbox',fieldbackground=INPUT,background=INPUT,foreground=TEXT,insertcolor=TEXT,
                    arrowcolor=TEXT,padding=(5,4),bordercolor=BORDER,lightcolor=BORDER,darkcolor=BORDER)
    style.map('TSpinbox',fieldbackground=[('readonly',INPUT)],foreground=[('disabled',MUTED)])
    style.configure("TCombobox", fieldbackground=INPUT, background=INPUT, arrowcolor=TEXT, padding=(7, 4))
    style.map("TCombobox", fieldbackground=[("readonly", INPUT)],
              selectbackground=[("readonly", INPUT)], selectforeground=[("readonly", TEXT)])
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, rowheight=31, borderwidth=0)
    style.map("Treeview", background=[("selected", colors['highlighted_clip'])], foreground=[("selected", TEXT)])
    style.configure('TCheckbutton',background=BG,foreground=TEXT)
    style.map('TCheckbutton',background=[('active',BG)],foreground=[('disabled',MUTED)])
    style.configure('Panel.TCheckbutton',background=PANEL,foreground=TEXT)
    style.map('Panel.TCheckbutton',background=[('active',PANEL),('!active',PANEL)])
    style.configure('Volume.Horizontal.TScale',background=colors['highlighted_button'],troughcolor=PANEL)
    style.configure("Treeview.Heading", background=INPUT, foreground=MUTED, padding=(8, 7),
                    font=("Segoe UI", 9, "bold"), relief="flat")
    style.map("Treeview.Heading", background=[("active", BORDER)])
    for name in ("TScrollbar", "Horizontal.TScrollbar", "Vertical.TScrollbar"):
        style.configure(name, background=BORDER, troughcolor=PANEL, bordercolor=PANEL,
                        lightcolor=BORDER, darkcolor=BORDER, arrowcolor=MUTED,
                        arrowsize=9, gripcount=0, borderwidth=0)
        style.map(name, background=[("pressed", ACCENT_DARK), ("active", "#4b5671"), ("!active", BORDER)])
    style.configure('Queue.Vertical.TScrollbar',arrowsize=18)
    style.configure("TNotebook", borderwidth=0, tabmargins=(0, 0, 0, 7))
    style.layout('TNotebook.Tab',[('Notebook.tab',{'sticky':'nswe','children':[('Notebook.padding',{'side':'top','sticky':'nswe','children':[('Notebook.label',{'side':'top','sticky':''})]})]})])
    style.configure("TNotebook.Tab", padding=(22, 9), background=PANEL, foreground=MUTED,
                    font=("Segoe UI", 10, "bold"), borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", ACCENT_DARK), ("active", INPUT), ("!active", PANEL)],
              foreground=[("selected", TEXT)], lightcolor=[("selected", ACCENT_DARK), ("!selected", BORDER)],
              padding=[("selected", (22, 9)), ("!selected", (22, 9))])

    images = []
    generation = round(scale*1000)
    root.review_theme_generation = generation
    for label, colors in {
        "Round": (root.review_palette['normal_button'],
                  '#2c3446' if root.review_palette == DEFAULT_PALETTE else blend(root.review_palette['normal_button'],TEXT,.08),
                  '#383650' if root.review_palette == DEFAULT_PALETTE else blend(root.review_palette['normal_button'],ACCENT,.18)),
        "Primary": (root.review_palette['highlighted_button'],
                    '#b494fa' if root.review_palette == DEFAULT_PALETTE else blend(root.review_palette['highlighted_button'],'#ffffff',.12),
                    '#9468e5' if root.review_palette == DEFAULT_PALETTE else blend(root.review_palette['highlighted_button'],'#000000',.1)),
    }.items():
        base, hover, pressed = colors
        states = [rounded_image(root, color, edge) for color, edge in (
            (base, MUTED), (hover, '#ffffff'), (pressed, '#ffffff'), (PANEL, BORDER), (base, MUTED))]
        images.extend(states)
        element = f"Review{generation}.{label}.button"
        if element not in style.element_names():style.element_create(element, "image", states[0], ("disabled", states[3]),
                             ("pressed", states[2]), ("active", states[1]), ("focus", states[4]),
                             border=max(1,round(12*scale)), padding=0, sticky="nsew")
        style.layout(f"{label}.TButton", [
            (element, {"sticky": "nsew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nswe"})]})
            ]})
        ])
        style.configure(f"{label}.TButton", padding=(12, 7),
                        background=BG,borderwidth=0,relief='flat',foreground=root.review_palette['highlighted_button_text' if label == 'Primary' else 'button_text'], anchor="center")
        style.map(f"{label}.TButton", foreground=[("disabled", MUTED)],background=[('disabled',BG),('!disabled',BG)])
        style.configure(f'Panel.{label}.TButton',background=PANEL)
        style.map(f'Panel.{label}.TButton',background=[('disabled',PANEL),('!disabled',PANEL)])
    root.replay_theme_images = images
    check_states=[control_image(root,fill,edge,'check',tick) for fill,edge,tick in (
        (INPUT,BORDER,None),(root.review_palette['highlighted_button'],ACCENT,root.review_palette['highlighted_button_text']),
        (INPUT,ACCENT,None),(blend(INPUT,PANEL,.5),BORDER,None),
        (blend(root.review_palette['highlighted_button'],PANEL,.6),BORDER,MUTED))]
    images.extend(check_states)
    element=f'Review{generation}.Checkbutton.indicator'
    if element not in style.element_names():style.element_create(element,'image',check_states[0],('disabled','selected',check_states[4]),
                         ('disabled',check_states[3]),('selected',check_states[1]),('active',check_states[2]),
                         ('focus',check_states[2]),sticky='w')
    for name in ('TCheckbutton','Panel.TCheckbutton'):
        style.layout(name,[('Checkbutton.padding',{'sticky':'nswe','children':[
            (element,{'side':'left','sticky':'w'}),('Checkbutton.label',{'side':'left','sticky':'nswe'})]})])
        style.configure(name,padding=0)
    field_states=[control_image(root,INPUT,edge) for edge in (BORDER,ACCENT)]
    arrow=control_image(root,None,TEXT,'arrow');images.extend([*field_states,arrow])
    field=f'Review{generation}.Combobox.field';chevron=f'Review{generation}.Combobox.downarrow'
    if field not in style.element_names():style.element_create(field,'image',field_states[0],('focus',field_states[1]),('active',field_states[1]),border=max(1,round(11*scale)),padding=0,sticky='nswe')
    if chevron not in style.element_names():style.element_create(chevron,'image',arrow,sticky='e')
    style.layout('TCombobox',[(field,{'sticky':'nswe','children':[
        (chevron,{'side':'right','sticky':'ns'}),('Combobox.padding',{'sticky':'nswe','children':[
            ('Combobox.textarea',{'sticky':'nswe'})]})]})])
    style.configure('TCombobox',padding=(10,6,2,6),borderwidth=0)
    scale=getattr(root,'review_scale',1)
    for name in ('.','Heading.TLabel','Subheading.TLabel','Accent.TLabel','Speed.TLabel','Timecode.TLabel','PanelHeading.TLabel','Help.TLabel','PanelHelp.TLabel','Treeview.Heading','TNotebook.Tab'):
        configured=style.configure(name) or {}
        if configured.get('font'):
            from tkinter.font import Font
            details=Font(root,font=configured['font']).actual()
            style.configure(name,font=(details['family'],-round(abs(details['size'])*96/72*scale),details['weight'],details['slant']))
    for name in ('TEntry','TSpinbox','TCombobox','Treeview.Heading','TNotebook.Tab','Round.TButton','Primary.TButton'):
        padding=style.configure(name,'padding')
        if padding:style.configure(name,padding=tuple(round(float(v)*scale) for v in root.tk.splitlist(padding)))
    style.configure('Treeview',rowheight=round(31*scale))
    style.map('TNotebook.Tab',padding=[('selected',(round(22*scale),round(9*scale))),('!selected',(round(22*scale),round(9*scale)))])
    if not getattr(root,'review_popup_bound',False):
        root.bind_class('ComboboxPopdown','<Map>',lambda e:round_popup(root,e),add='+')
        root.review_popup_bound=True
    dark_title(root)


def dialog(parent, title):
    window = tk.Toplevel(parent)
    window.withdraw()
    apply_window_icon(window)
    window.title(title)
    window.transient(parent)
    window.review_palette = getattr(parent,'review_palette',DEFAULT_PALETTE)
    window.configure(bg=window.review_palette['background'])
    window.bind('<Map>',lambda event:dark_title(window) if event.widget==window else None,add='+')
    return window


def present(window, parent, *, work_area=None):
    window.update_idletasks()
    # Forms fit their content; dialogs with scrolling explicitly opt into a
    # smaller minimum. Never allow a popup to collapse into just its title bar.
    width,height=window.winfo_reqwidth(),window.winfo_reqheight()
    minimum=getattr(window,'review_minimum',(width,height))
    if work_area:
        left,top,right,bottom=work_area
        scale=getattr(parent,'review_scale',1)
        # The client area needs room for the native frame and title bar.
        right-=round(16*scale)
        bottom-=round(52*scale)
        width=min(width,right-left)
        height=min(height,bottom-top)
        minimum=(min(minimum[0],width),min(minimum[1],height))
    window.minsize(max(220,minimum[0]),max(100,minimum[1]))
    x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
    y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
    if work_area:
        x=max(left,min(x,right-width))
        y=max(top,min(y,bottom-height))
        window.geometry(f"{width}x{height}+{x}+{y}")
    else:
        window.geometry(f"+{x}+{y}")
    dark_title(window)
    window.deiconify()
    window.update_idletasks();dark_title(window)
    window.grab_set()
    window.bind("<Escape>", lambda event: window.destroy())


def show_error(parent, title, message):
    existing = getattr(parent,'review_error_window',None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        return
    window = dialog(parent, title)
    parent.review_error_window = window
    page = ttk.Frame(window, padding=20)
    page.pack(fill="both", expand=True)
    ttk.Label(page, text=title, style="Subheading.TLabel").pack(anchor="w", pady=(0, 8))
    ttk.Label(page, text=message, wraplength=520, justify="left").pack(anchor="w", pady=(0, 15))
    okay = ttk.Button(page, text="Close", style="Primary.TButton", command=window.destroy)
    okay.pack(anchor="e")
    present(window, parent)
    okay.focus_set()


def reveal_paths(paths):
    """Select each set of sibling items in its Explorer folder."""
    shell, ole = ctypes.windll.shell32, ctypes.windll.ole32
    pointer = ctypes.c_void_p
    shell.SHParseDisplayName.argtypes = [wintypes.LPCWSTR, pointer, ctypes.POINTER(pointer), wintypes.DWORD, pointer]
    shell.SHParseDisplayName.restype = ctypes.c_long
    shell.ILFindLastID.argtypes = [pointer]
    shell.ILFindLastID.restype = pointer
    shell.SHOpenFolderAndSelectItems.argtypes = [pointer, wintypes.UINT, ctypes.POINTER(pointer), wintypes.DWORD]
    shell.SHOpenFolderAndSelectItems.restype = ctypes.c_long
    ole.CoInitializeEx.argtypes = [pointer, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [pointer]
    ole.CoTaskMemFree.restype = None
    groups = {}
    for path in paths:
        groups.setdefault(path.parent, []).append(path)
    result = ole.CoInitializeEx(None, 2)
    if result < 0 and result != -2147417850:  # COM may already be initialized in a different apartment.
        raise OSError(f"Explorer could not initialize (0x{result & 0xffffffff:08X}).")
    try:
        for folder, items in groups.items():
            parsed = []
            try:
                for path in (folder, *items):
                    pidl = pointer()
                    status = shell.SHParseDisplayName(str(path), None, ctypes.byref(pidl), 0, None)
                    if status < 0 or not pidl:
                        raise OSError(f"Explorer could not locate {path}.")
                    parsed.append(pidl)
                children = (pointer * len(items))(*(shell.ILFindLastID(pidl) for pidl in parsed[1:]))
                status = shell.SHOpenFolderAndSelectItems(parsed[0], len(children), children, 0)
                if status < 0:
                    raise OSError(f"Explorer could not select the items in {folder} (0x{status & 0xffffffff:08X}).")
            finally:
                for pidl in parsed:
                    ole.CoTaskMemFree(pidl)
    finally:
        if result >= 0:
            ole.CoUninitialize()


def confirm_action(parent, title, message, action,cancel_first=False,cancel_text="Cancel"):
    window = dialog(parent, title)
    page = ttk.Frame(window, padding=20)
    page.pack(fill="both", expand=True)
    ttk.Label(page, text=title, style="Subheading.TLabel").pack(anchor="w", pady=(0, 8))
    ttk.Label(page, text=message, wraplength=560, justify="left").pack(anchor="w", pady=(0, 15))
    buttons = ttk.Frame(page)
    buttons.pack(fill="x")
    accepted = []

    def confirm():
        accepted.append(True)
        window.destroy()

    cancel = ttk.Button(buttons, text=cancel_text, style="Round.TButton", command=window.destroy)
    cancel.pack(side="left" if cancel_first else "right")
    ttk.Button(buttons, text=action, style="Primary.TButton", command=confirm).pack(side="right", padx=(8, 0) if cancel_first else (0, 8))
    present(window, parent)
    cancel.focus_set()
    window.wait_window()
    return bool(accepted)


def pick_path(parent, title, initial=None, csv=False, rename_callback=None):
    from review_folder_picker import FolderPicker
    return FolderPicker(parent,title,initial,csv,rename_callback).run()

