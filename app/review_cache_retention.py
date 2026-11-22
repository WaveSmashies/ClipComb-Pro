# SPDX-License-Identifier: GPL-3.0-or-later
"""Expire only this app's generated cache files; never source media or scan progress."""
from pathlib import Path
import re,threading,time

AGE_SECONDS=30*24*60*60

def expire_generated(base,kind,now=None,cancel=None):
    base=Path(base).resolve();folder=base/('Generated Thumbnails' if kind=='thumbnails' else 'Generated Waveforms')
    if folder.is_symlink() or not folder.is_dir() or folder.resolve().parent!=base:return 0
    cutoff=(time.time() if now is None else now)-AGE_SECONDS;removed=0
    try:
        for path in folder.iterdir():
            if cancel and cancel.is_set():break
            try:
                if path.is_symlink() or not path.is_file() or path.stat().st_mtime>cutoff:continue
                if kind=='thumbnails':
                    if not re.fullmatch(r'[0-9a-f]{32}\.jpg',path.name):continue
                else:
                    if not re.fullmatch(r'[0-9a-f]{64}\.peaks',path.name):continue
                    with path.open('rb') as file:
                        if file.read(5)!=b'CRWV1':continue
                path.unlink();removed+=1
            except OSError:continue
    except OSError:pass
    return removed

class CacheRetention:
    def __init__(self,app):
        self.app=app;self.cancel=threading.Event();self.worker=None;self.closed=False
        self.timer=app.root.after(24*60*60*1000,self.daily);self.request()
    def request(self):
        if self.closed:return
        self.cancel.set();self.cancel=threading.Event();cancel=self.cancel
        base=self.app.settings.path.parent
        kinds=[kind for kind in ('thumbnails','waveform') if self.app.settings.data.getboolean(kind,'delete_after_30_days')]
        def run():
            for kind in kinds:
                if cancel.is_set():break
                expire_generated(base,kind,cancel=cancel)
        self.worker=threading.Thread(target=run,daemon=True,name='ClipComb cache cleanup');self.worker.start()
    def daily(self):
        self.request()
        if not self.closed:self.timer=self.app.root.after(24*60*60*1000,self.daily)
    def close(self):
        self.closed=True;self.cancel.set();self.app.root.after_cancel(self.timer)
        if self.worker:self.worker.join(timeout=.5)
