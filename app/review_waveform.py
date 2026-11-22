# SPDX-License-Identifier: GPL-3.0-or-later
"""Lazy audio-only peak generation. No video decoding or temporary PCM files."""
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
from queue import Queue, Empty
import subprocess
import threading
import time
import zlib


def display_amplitude(peak):
    """Fixed soft logarithmic scale: late loud audio never shrinks earlier sound.

    Cached peaks remain linear/full scale. This affects only the picture, not
    playback, decoding or the relative contributions of the source streams.
    Zero stays zero; quiet gameplay remains visible beside loud microphone audio.
    """
    return math.log1p(999*min(65535,max(0,peak))/65535)/math.log(1000)


def cache_key(clip_id, identity, track, bins):
    payload=json.dumps([clip_id,identity,track,bins,1],sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def waveform_folder(base):
    base=Path(base).resolve();folder=base/'Generated Waveforms'
    folder.mkdir(exist_ok=True)
    old=base/'cache/waveforms'
    if old.is_dir() and not old.is_symlink():
        for source in old.glob('*.peaks'):
            if source.is_symlink():continue
            try:
                with source.open('rb') as file:valid=file.read(5)==b'CRWV1'
                if valid:
                    if not (folder/source.name).exists():source.replace(folder/source.name)
                    else:source.unlink()
            except OSError:pass
    return folder


def delete_generated(base):
    base=Path(base).resolve();folder=base/'Generated Waveforms'
    if not folder.is_dir() or folder.is_symlink():return
    if folder.resolve().parent!=base:return
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file():continue
        try:
            if path.suffix=='.peaks':
                with path.open('rb') as file:valid=file.read(5)==b'CRWV1'
                if not valid:continue
            elif not (path.suffix=='.writing' and len(path.name.split('.')[0])==64):continue
            path.unlink()
        except OSError:pass
    try:folder.rmdir()
    except OSError:pass


def write_peaks(path, peaks, bins):
    header=json.dumps({'bins':bins,'count':len(peaks)}).encode()
    data=b'CRWV1'+len(header).to_bytes(4,'little')+header+zlib.compress(peaks.tobytes(),6)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(f'.{threading.get_ident()}.writing')
    temp.write_bytes(data)
    os.replace(temp,path)


def read_peaks(path, bins):
    data=path.read_bytes()
    if data[:5]!=b'CRWV1': raise ValueError('Unknown waveform cache format')
    size=int.from_bytes(data[5:9],'little')
    header=json.loads(data[9:9+size])
    peaks=array('H');peaks.frombytes(zlib.decompress(data[9+size:]))
    if header['bins']!=bins or len(peaks)!=header['count']: raise ValueError('Invalid waveform cache')
    return peaks


class Waveforms:
    def __init__(self, cache_folder, executable, bins=50):
        self.folder,self.executable,self.bins=Path(cache_folder),executable,int(bins)
        self.events=Queue()
        self.generation=0
        self.lock=threading.Lock()
        self.process,self.worker=None,None

    def cancel(self, wait=False):
        self.generation+=1
        with self.lock:
            process=self.process
            if process and process.poll() is None:
                try:process.terminate()
                except OSError:pass
        if wait and self.worker and self.worker.is_alive():
            self.worker.join(3)

    def request(self,path,clip_id,identity,track,duration,tracks=1,force=False):
        self.cancel()
        generation=self.generation
        selection=('all-streams-max-v1',tracks) if track is None else track
        cached=self.folder/(cache_key(clip_id,identity,selection,self.bins)+'.peaks')
        def generate():
            process=None
            try:
                if cached.is_file() and not force:
                    try:
                        peaks=read_peaks(cached,self.bins)
                        self.events.put((generation,peaks,True,'Cached waveform'))
                        return
                    except (ValueError,OSError,zlib.error,KeyError):
                        pass
                if not self.executable:
                    self.events.put((generation,array('H'),True,'Waveform decoder unavailable'))
                    return
                options={'creationflags':subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name=='nt' else {}
                args=[str(self.executable),'-nostdin','-v','error','-threads','1','-filter_threads','1','-filter_complex_threads','1','-i',str(path)]
                channels=1
                if track is None:
                    channels=max(1,int(tracks))
                    # amerge stops at its shortest input; pad shorter streams so
                    # a quiet/short track cannot hide later sound on another.
                    pad=f',apad=whole_dur={duration:.9f}' if duration>0 else ''
                    filters=';'.join(f"[0:a:{i}]aresample=8000,aformat=channel_layouts=stereo,aeval=exprs='max(abs(val(0)),abs(val(1)))':channel_layout=mono{pad}[w{i}]" for i in range(channels))
                    if channels==1:filters+=';[w0]anull[out]'
                    else:filters+=';'+''.join(f'[w{i}]' for i in range(channels))+f'amerge=inputs={channels}[out]'
                    args+=['-filter_complex',filters,'-map','[out]']
                else:args+=['-map',f'0:a:{track}','-ac','1']
                args+=['-vn','-sn','-dn','-ar','8000','-f','f32le','pipe:1']
                with self.lock:
                    if generation!=self.generation:return
                    process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,**options)
                    self.process=process
                peaks=array('H');pending=array('f');last=time.monotonic();samples_per_bin=(8000//self.bins)*channels
                while generation==self.generation:
                    data=process.stdout.read(8000*4*channels//4)
                    if not data:break
                    samples=array('f');samples.frombytes(data[:len(data)-len(data)%4]);pending.extend(samples)
                    count=len(pending)//samples_per_bin
                    for index in range(count):
                        a=index*samples_per_bin
                        value=max(map(abs,pending[a:a+samples_per_bin]),default=0)
                        peaks.append(min(65535,round(value*65535)))
                    del pending[:count*samples_per_bin]
                    if time.monotonic()-last>.15:
                        progress=min(99,round(len(peaks)/max(1,duration*self.bins)*100))
                        self.events.put((generation,array('H',peaks),False,f'Waveform {progress}%'))
                        last=time.monotonic()
                if generation!=self.generation:return
                if pending:
                    peaks.append(min(65535,round(max(map(abs,pending))*65535)))
                if process.wait()!=0:
                    self.events.put((generation,array('H'),True,'Waveform unavailable for this track'))
                    return
                write_peaks(cached,peaks,self.bins)
                self.events.put((generation,peaks,True,''))
            except Exception:
                if generation==self.generation:
                    self.events.put((generation,array('H'),True,'Waveform unavailable'))
            finally:
                if process:
                    if process.poll() is None:
                        try:process.terminate()
                        except OSError:pass  # It may have exited between poll and terminate.
                    process.wait()
                    process.stdout.close()
                with self.lock:
                    if self.process is process:self.process=None
        self.worker=threading.Thread(target=generate,daemon=True)
        self.worker.start()

    def poll(self):
        latest=None
        while True:
            try:event=self.events.get_nowait()
            except Empty:break
            if event[0]==self.generation:latest=event
        return latest

    def close(self):
        self.cancel(wait=True)
