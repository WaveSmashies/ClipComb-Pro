# SPDX-License-Identifier: GPL-3.0-or-later
"""Shareable, validated INI palettes and matching pastel light variants."""
import colorsys,configparser
from pathlib import Path

def luminance(color):
    values=[n/255 for n in bytes.fromhex(color[1:])]
    values=[n/12.92 if n<=.04045 else ((n+.055)/1.055)**2.4 for n in values]
    return sum(v*k for v,k in zip(values,(.2126,.7152,.0722)))

def contrast(a,b):
    x,y=sorted((luminance(a),luminance(b)))
    return (y+.05)/(x+.05)

def dark_accent(color,background,minimum):
    h,l,s=colorsys.rgb_to_hls(*(n/255 for n in bytes.fromhex(color[1:])))
    l=min(.43,l);s=min(.65,s*.75)
    def hex_color():return '#'+''.join(f'{round(v*255):02x}' for v in colorsys.hls_to_rgb(h,l,s))
    while contrast(hex_color(),background)<minimum and l>.02:l=max(0,l-.01)
    return hex_color()

def light_palette(colors):
    def invert(value):
        r,g,b=[n/255 for n in bytes.fromhex(value[1:])];h,l,s=colorsys.rgb_to_hls(r,g,b)
        return '#'+''.join(f'{round(v*255):02x}' for v in colorsys.hls_to_rgb(h,1-l,s))
    result={k:invert(v) for k,v in colors.items()}
    result['level_meter']=colors.get('level_meter','#13ff0d')
    from review_theme import blend
    result['highlighted_button']=dark_accent(colors['highlighted_button'],'#ffffff',4.5)
    result['selection']=dark_accent(colors['selection'],result['panel'],3)
    result['waveform']=dark_accent(colors['waveform'],result['panel'],4.5)
    result['highlighted_clip']=blend(result['panel'],colors['highlighted_button'],.18)
    result['selection_fill']=blend(result['panel'],colors['selection'],.22)
    result['normal_button']=blend(result['panel'],colors['highlighted_button'],.08)
    result['highlighted_button_text']='#ffffff'
    from review_theme import PRESETS
    if colors==PRESETS['Grey Mann']:
        result.update(background='#c0c0c7',panel='#c8c9cc',input='#d5d5d5',border='#888888',text='#000000',muted_text='#4b4b4b',
            normal_button='#dbdae2',highlighted_button='#625c7e',button_text='#0b0b0b',highlighted_button_text='#ffffff',
            highlighted_clip='#b0b0b0',selection='#60617b',selection_fill='#dddddd',waveform='#60617b',playhead='#0b0b0b',video_background='#f2f2f2',level_meter='#13ff0d')
    if colors==PRESETS['Rose Quartz']:
        result.update(background='#ede2e9',panel='#dfcfd9',input='#dfcfd9',border='#b999a6',text='#070a11',
            muted_text='#391424',normal_button='#e2cdd8',highlighted_button='#df6889',button_text='#070a11',
            highlighted_button_text='#ffffff',highlighted_clip='#e5cad6',selection='#b5264c',selection_fill='#e6c9d5',
            waveform='#d94a72',playhead='#070a11',video_background='#eff1f6')
    return result

class ThemeStore:
    def __init__(self,base):self.folder=Path(base)/'Themes'
    def list(self):
        result={}
        if self.folder.is_dir():
            for path in sorted(self.folder.glob('*.ini'),key=lambda p:p.name.casefold()):
                try:
                    record=self.read(path);result[record['name']+' - Custom']=(path,record)
                except (OSError,ValueError,configparser.Error):pass
        return result
    def read(self,path):
        from review_theme import DEFAULT_PALETTE,valid_color
        data=configparser.ConfigParser(interpolation=None);data.read(path,encoding='utf-8-sig')
        if data.get('theme','schema',fallback='')!='1':raise ValueError('Unsupported theme file.')
        name=data.get('theme','name',fallback=path.stem)
        versions={key:{k:valid_color(data.get(key,k,fallback=v)) for k,v in DEFAULT_PALETTE.items()} for key in ('dark','light')}
        return dict(name=name,versions=versions,bookmarks=dict(data['bookmarks']) if data.has_section('bookmarks') else {})
    def save(self,name,versions,bookmarks):
        from review_folder_picker import folder_name
        from review_theme import valid_color,DEFAULT_PALETTE
        name=folder_name(name);self.folder.mkdir(exist_ok=True)
        path=self.folder/(name+'.ini');data=configparser.ConfigParser(interpolation=None)
        data['theme']={'schema':'1','name':name}
        for key in ('dark','light'):data[key]={k:valid_color(versions[key][k]) for k in DEFAULT_PALETTE}
        data['bookmarks']=bookmarks
        temporary=path.with_suffix('.ini.writing')
        with temporary.open('w',encoding='utf-8') as stream:data.write(stream)
        temporary.replace(path);return path
    def delete(self,label):
        path=self.list()[label][0]
        if path.resolve().parent!=self.folder.resolve():raise ValueError('Theme file is outside the Themes folder.')
        path.unlink()

def configured_versions(settings):
    from review_theme import PRESETS,DEFAULT_PALETTE,valid_color
    from review_brand import THEME_NAMES
    cfg=settings.data['theme'];name=cfg.get('preset','Default');name=THEME_NAMES.get(name,name)
    missing_named=name.endswith(' - Custom') and (not settings.path or name not in ThemeStore(settings.path.parent).list())
    if name=='Custom' or missing_named:
        dark={k:valid_color(cfg.get('custom_'+k,v)) for k,v in DEFAULT_PALETTE.items()}
        light={k:valid_color(cfg.get('light_custom_'+k,v)) for k,v in light_palette(dark).items()}
        return {'dark':dark,'light':light}
    if settings.path and name in (saved:=ThemeStore(settings.path.parent).list()):return saved[name][1]['versions']
    dark=dict(PRESETS.get(name,DEFAULT_PALETTE));return {'dark':dark,'light':light_palette(dark)}
