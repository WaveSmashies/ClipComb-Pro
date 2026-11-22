# SPDX-License-Identifier: GPL-3.0-or-later
"""One thumbnail worker and one shared byte-budgeted cache across all queues."""
from collections import OrderedDict
from pathlib import Path
import shutil
from queue import Empty
from PIL import Image,ImageTk,ImageOps
from review_thumbnails import Thumbnails

class ThumbnailPool:
    def __init__(self,app):
        self.app=app;self.service=Thumbnails(app.settings.path.parent/'Generated Thumbnails')
        self.raw=OrderedDict();self.photos=OrderedDict();self.failed=set();self.clients=set();self.closed=False;self.budget=32*1024**2
        self.paths={};self.decoder_setting=None;self.decoder_path=None
    def has_results(self):return not self.service.results.empty()
    def has_pending(self):return bool(self.service.pending)
    def request_updates(self):
        if self.has_pending() and hasattr(self.app,'update_timer'):
            self.app.update_timer.schedule(80)
    def wanted(self):self.service.wanted=set().union(*(v.wanted for v in self.clients)) if self.clients else set()
    def checked_path(self,project,path):
        key=(project.root,path)
        if key not in self.paths:
            if len(self.paths)>4096:self.paths.clear()
            self.paths[key]=project.checked(path)
        return self.paths[key]
    def decoder(self):
        setting=self.app.settings.data['tools']['ffmpeg'] or str(self.app.settings.path.parent/'player/ffmpeg.exe')
        if setting!=self.decoder_setting:
            self.decoder_setting=setting;self.decoder_path=setting if Path(setting).is_file() else shutil.which('ffmpeg')
        return self.decoder_path
    def photo(self,key,width,height):
        variant=(key,width,height)
        if variant in self.photos:self.photos.move_to_end(variant);return self.photos[variant]
        if key not in self.raw:return None
        self.raw.move_to_end(key);picture=ImageOps.contain(self.raw[key],(width,height),Image.Resampling.BILINEAR)
        result=ImageTk.PhotoImage(picture,master=self.app.root);result.review_bytes=picture.width*picture.height*4;self.photos[variant]=result;return result
    def trim(self):
        protected=set().union(*(v.variants for v in self.clients)) if self.clients else set()
        raw_visible=set().union(*(v.visible_keys for v in self.clients)) if self.clients else set()
        total=sum(im.width*im.height*3 for im in self.raw.values())+sum(im.review_bytes for im in self.photos.values())
        for key in list(self.photos):
            if total<=self.budget:break
            if key not in protected:total-=self.photos.pop(key).review_bytes
        for key in list(self.raw):
            if total<=self.budget:break
            if key not in raw_visible:
                im=self.raw.pop(key);total-=im.width*im.height*3
    def poll(self):
        if self.closed:return
        changed=set()
        while True:
            try:key,picture=self.service.results.get_nowait()
            except Empty:break
            if picture is None:self.failed.add(key)
            else:self.raw[key]=picture;self.raw.move_to_end(key);changed.add(key)
        for view in tuple(self.clients):
            if changed & view.wanted:view.draw()
        self.trim()
    def pause(self):self.service.pause()
    def resume(self):
        self.paths.clear()
        self.service.paused=False
        for view in tuple(self.clients):view.refresh_status()
    def remove(self,view):
        self.clients.discard(view);self.wanted()
        if not self.clients:
            self.closed=True;self.service.close();self.raw.clear();self.photos.clear()
