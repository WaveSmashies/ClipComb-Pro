# SPDX-License-Identifier: GPL-3.0-or-later
"""Owned browser host, isolated from personal browser profiles."""
from pathlib import Path
from queue import Queue,Empty
import subprocess,threading
import tkinter as tk
from review_icons import asset_folder


class EmbeddedTutorial:
    def __init__(self,app,surface,status):
        self.process=None;self.timer=None;self.surface=surface;self.status=status;self.events=Queue();self.closed=False
        candidates=[app.settings.path.parent/'tutorial/ClipComb Tutorial.exe',Path(__file__).resolve().parent.parent/'tutorial-runtime/ClipComb Tutorial.exe']
        host=next((path for path in candidates if path.is_file()),None)
        if not host:status.set('Embedded player unavailable. You can watch the tutorial in your browser.');return
        surface.update_idletasks()
        try:self.process=subprocess.Popen([str(host),str(surface.winfo_id()),str(app.settings.path.parent/'Tutorial Browser Data'),str(asset_folder()/'tutorial')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError:status.set('Embedded player unavailable. You can watch the tutorial in your browser.');return
        def messages():
            try:
                for line in self.process.stdout:self.events.put(line.strip())
            except (OSError,ValueError):pass
        threading.Thread(target=messages,daemon=True).start();self.poll()
    def poll(self):
        if self.closed:return
        try:
            while True:
                message=self.events.get_nowait()
                self.status.set('' if message=='READY' else 'Embedded player unavailable. You can watch in your browser.' if message.startswith('ERROR') else message)
        except Empty:pass
        self.timer=self.surface.after(100,self.poll)
    def close(self):
        if self.closed:return
        self.closed=True
        if self.timer:
            try:self.surface.after_cancel(self.timer)
            except tk.TclError:pass
        if self.process:
            if self.process.poll() is None:
                try:self.process.stdin.write('close\n');self.process.stdin.flush();self.process.wait(timeout=2)
                except (OSError,subprocess.TimeoutExpired):self.process.terminate();self.process.wait(timeout=2)
            self.process.stdin.close();self.process.stdout.close()
