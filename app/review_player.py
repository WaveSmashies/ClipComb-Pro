# SPDX-License-Identifier: GPL-3.0-or-later
"""One mpv demuxer, one multitrack audio graph, one A/V clock."""
from collections import deque
from pathlib import Path
import shutil
import time
from PIL import Image
from mpv_native import Mpv
from review_scrub_audio import ScrubAudio


def find_mpv(base, configured=''):
    candidates = [Path(configured)] if configured else []
    candidates += [Path(base)/'player/libmpv-2.dll', Path(base)/'libmpv-2.dll',
                   Path(base)/'vendor/mpv/libmpv-2.dll']
    executable = shutil.which('mpv')
    if executable:
        candidates.append(Path(executable).parent/'libmpv-2.dll')
    for path in candidates:
        if path.is_dir():
            path /= 'libmpv-2.dll'
        if path.is_file():
            return path
    return None


def gain(setting):
    return min(1.5, max(0, setting['volume']/100)) if setting['enabled'] else 0.0


def audio_graphs(count, mix):
    """Keep decoders connected; adjust gains with af-command, without audio flushes.

    amerge preserves each stereo pair. The ordinary AF graph selects those pairs
    and hosts addressable gain filters; mpv cannot send AF commands to its complex
    graph. No audio stream is reopened or sought when adjusting these controls.
    """
    if not count:
        return '', ''
    if count > 32:
        raise ValueError('This mixer supports up to 32 audio streams per clip.')
    inputs = ';'.join(f'[aid{i+1}]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[s{i}]'
                      for i in range(count))
    merge = inputs + ';' + ''.join(f'[s{i}]' for i in range(count)) + f'amerge=inputs={count}[ao]'
    split = f'asplit={count}' + ''.join(f'[s{i}]' for i in range(count))
    controls = ';'.join(f'[s{i}]pan=stereo|c0=c{2*i}|c1=c{2*i+1},volume@track{i}={gain(mix[i]):.4f}[m{i}]'
                        for i in range(count))
    filters = '@review:lavfi=[' + split + ';' + controls + ';' + ''.join(f'[m{i}]' for i in range(count))
    return merge, filters + f'amix=inputs={count}:normalize=0:duration=longest:dropout_transition=0],scaletempo2=min-speed=0.1:max-speed=8'


class Mixer:
    def __init__(self, library, frame, hwdec='auto',audio_device='auto'):
        self.library,self.audio_preview=library,None
        self.audio_device=audio_device
        self.engine = Mpv(library, {
            'config': 'no', 'load-scripts': 'no', 'osc': 'no', 'osd-level': '0',
            'input-default-bindings': 'no', 'input-vo-keyboard': 'no',
            'input-builtin-dragging': 'no', 'input-builtin-drag-and-drop': 'no',
            'wid': str(frame.winfo_id()), 'vo': 'gpu-next', 'gpu-api':'d3d11','gpu-context': 'd3d11',
            'target-colorspace-hint':'auto','tone-mapping':'auto','d3d11-output-format':'auto',
            'hwdec-software-fallback':'yes',
            'hwdec': hwdec, 'hwdec-codecs': 'all', 'video-sync': 'audio',
            'audio-device':audio_device,'audio-pitch-correction': 'yes', 'audio-channels': 'stereo', 'audio-buffer': '0.1',
            'keep-open': 'yes', 'idle': 'yes', 'pause': 'yes', 'demuxer': 'lavf',
            'background':'color','border-background':'color','background-color':getattr(frame._root(),'review_palette',{}).get('video_background','#090b10'),
            'demuxer-max-bytes': str(256*1024*1024), 'demuxer-max-back-bytes': str(128*1024*1024),
            'hr-seek': 'yes', 'hr-seek-framedrop': 'yes', 'cache': 'auto',
        })
        self.frame = frame
        self.active, self.ready, self.paused, self.ended = False, False, True, False
        self.speed, self.position, self.duration = 1.0, 0.0, 0.0
        self.mix, self.applied_gains = [], []
        self.pending_seek = None
        self.input_events, self.logs = deque(), deque(maxlen=30)
        self.loading_at = 0
        self.scrubbing = False
        self.output_mute=None;self.audio_restore_pending=False;self.audio_restart_seen=False
        self.stepping=False;self.step_pending=None;self.step_queue=deque();self.step_serial=0
        # script-binding delivers down and up to this API client, including on the
        # native video child window which Tk's frame bindings cannot receive.
        bindings = '\n'.join(f'{key} script-binding {self.engine.name}/{action}' for key, action in (
            ('MBTN_LEFT', 'magnify'), ('MBTN_RIGHT','toggle-zoom-cursor'), ('WHEEL_UP', 'zoom-up'), ('WHEEL_DOWN', 'zoom-down'),
            ('Ctrl+WHEEL_UP','size-up'),('Ctrl+WHEEL_DOWN','size-down')))
        self.engine.command('define-section', 'review-mouse', bindings, 'force')
        self.engine.command('enable-section', 'review-mouse')

    def set_audio_device(self,device):
        if device==self.audio_device:return
        self.engine.set('audio-device',device);self.audio_device=device
        if self.audio_preview:self.audio_preview.set_audio_device(device)

    def set_background(self,color):
        if getattr(self,'background',None)==color:return
        self.engine.set('background-color',color);self.background=color

    def open(self, path, metadata, mix, position=0, autoplay=True):
        self.clear()
        self.logs.clear()
        self.path, self.metadata, self.mix = Path(path), metadata, mix
        self.duration = metadata['duration']
        # MPEG-TS has no container seek index; its demuxer can land on the NEXT
        # keyframe. Decode a short preroll to reach the requested frame precisely.
        self.seek_preroll=5 if self.path.suffix.lower() in ('.ts','.mts','.m2ts') else 0
        self.engine.set('hr-seek-demuxer-offset',self.seek_preroll)
        self.position = min(max(0, position), max(0, self.duration-.05))
        self.paused, self.ended, self.active = not autoplay, False, True
        merge, filters = audio_graphs(len(metadata['audio']), mix)
        self.engine.set('lavfi-complex', merge)
        self.engine.set('af', filters)
        self.engine.set('aid', 'no')
        self.engine.set('pause', self.paused)
        self.engine.set('speed', self.speed)
        self.engine.set('start', str(self.position))
        self.applied_gains = [gain(m) for m in mix]
        self.audio_restore_pending=False;self.audio_restart_seen=False
        self.engine.set('mute',True);self.output_mute=True
        self.engine.command('loadfile', str(self.path), asynchronous=True)
        self.loading_at = time.monotonic()
        self.pending_seek = self.position
        self.pending_seek_at, self.pending_seek_restarted = self.loading_at, False

    def clear(self):
        if self.stepping:self.engine.set('framedrop',self.step_framedrop)
        self.stepping=False;self.step_pending=None;self.step_queue.clear()
        self.cancel_scrub()
        if self.audio_preview:
            self.audio_preview.close();self.audio_preview=None
        if self.active:
            self.engine.command('stop')  # Release file handles before Save renames a source.
        self.active, self.ready, self.paused, self.ended = False, False, True, False
        self.pending_seek = None
        self.input_events.clear()
        for _ in self.engine.events():
            pass

    def sync_output_mute(self):
        muted=self.scrubbing or self.audio_restore_pending or any(value is None for value in self.applied_gains) or not any(gain(m)>0 for m in self.mix)
        if muted!=self.output_mute:self.engine.set('mute',muted);self.output_mute=muted

    def apply_mix(self):
        if not self.active or not self.ready or self.stepping:
            return
        self.sync_output_mute()
        for i, setting in enumerate(self.mix):
            value = gain(setting)
            if value != self.applied_gains[i]:
                try:self.engine.command('af-command', 'review', 'volume', f'{value:.4f}', f'volume@track{i}')
                except RuntimeError:
                    # AF nodes can briefly be absent while a seek reinitializes
                    # audio. Retry on the next poll instead of closing playback.
                    return
                self.applied_gains[i] = value
        self.sync_output_mute()

    def set_pause(self, paused):
        if not paused:self.end_steps()
        self.paused = bool(paused)
        if self.active:
            self.sync_output_mute()
            self.engine.set('pause', self.paused)

    def seek(self, seconds):
        if not self.active:
            return
        self.end_steps()
        self.position = min(max(0, seconds), max(0, self.duration-.001))
        self.pending_seek, self.ended = self.position, False
        self.audio_restore_pending=bool(self.metadata['audio']);self.audio_restart_seen=False
        self.sync_output_mute()
        self.pending_seek_at, self.pending_seek_restarted = time.monotonic(), False
        self.engine.command('seek', f'{self.position:.9f}', 'absolute+exact', asynchronous=True)

    def begin_scrub(self, seconds, video=True, audio=False, stop=True, interval=.035, grain=.1):
        if not self.active or not self.ready:
            return
        self.cancel_scrub()
        self.end_steps()
        self.scrub_was_paused = self.paused or bool(self.engine.get('pause', True))
        self.scrub_pause_request = None
        self.scrubbing = True
        self.scrub_mute = False  # Clip mute is derived from current mix, not the temporary seek guard.
        self.scrub_volume = self.engine.get('volume',100)
        self.scrub_inflight, self.scrub_last, self.scrub_grain_until = None, None, None
        self.scrub_restart_seen=False
        self.scrub_next_at = 0
        self.configure_scrub(video, audio, stop, interval, grain)
        self.engine.set('pause', True)
        self.sync_output_mute()
        self.paused = True
        self.update_scrub(seconds)

    def configure_scrub(self, video=True, audio=False, stop=True, interval=.035, grain=.1):
        self.scrub_video, self.scrub_audio, self.scrub_stop = video, video and audio, stop
        self.scrub_interval, self.scrub_grain = max(.008, interval), max(.01, grain)
        if self.scrubbing:
            self.sync_output_mute()
            self.engine.set('pause',True)
            if not self.scrub_audio and self.audio_preview:self.audio_preview.stop()

    def update_scrub(self, seconds):
        if self.scrubbing:
            self.position = min(max(0, seconds), max(0, self.duration-.001))
            self.scrub_target = self.position
            if self.scrub_audio and self.metadata['audio']:
                if not self.audio_preview:
                    self.audio_preview=ScrubAudio(self.library,self.path,len(self.metadata['audio']),audio_graphs,self.audio_device)
                self.audio_preview.submit(self.position,self.mix,self.scrub_grain,self.scrub_mute,self.scrub_volume)

    @property
    def transport_paused(self):
        if not self.scrubbing:
            return self.paused
        if self.scrub_pause_request is not None:
            return self.scrub_pause_request
        return self.scrub_stop or self.scrub_was_paused

    def toggle_play(self):
        if not self.active:
            return
        if self.scrubbing:
            self.scrub_pause_request = not self.transport_paused
        elif self.ended or self.position >= self.duration - .05:
            self.seek(0)
            self.set_pause(False)
        else:
            self.set_pause(not self.paused)

    def end_scrub(self, seconds):
        if not self.scrubbing:
            self.seek(seconds)
            return
        stop = self.transport_paused
        if self.audio_preview:self.audio_preview.stop()
        self.scrubbing = False
        self.engine.set('pause', True)
        self.engine.set('speed', self.speed)
        target=min(max(0,seconds),max(0,self.duration-.001))
        if self.scrub_video and self.scrub_last is not None and abs(target-self.scrub_last)<1e-7:
            # Hand the already-issued preview seek back to normal playback.
            # Restarting the same decode here doubles work on long GOP clips.
            self.position=target;self.pending_seek=target;self.ended=False
            self.pending_seek_at=time.monotonic()
            self.pending_seek_restarted=self.scrub_restart_seen or self.scrub_inflight is None
            self.audio_restart_seen=self.pending_seek_restarted
            self.audio_restore_pending=bool(self.metadata['audio']) and self.scrub_inflight is not None
        else:self.seek(target)
        self.sync_output_mute()
        self.set_pause(stop)

    def cancel_scrub(self):
        if self.audio_preview:self.audio_preview.stop()
        if self.scrubbing:
            self.scrubbing = False
            self.engine.set('pause', True)
            self.engine.set('speed', self.speed)
            self.sync_output_mute()
            self.paused = True

    def _scrub_tick(self, now, restarted):
        # Only one preview seek may be in flight. New mouse positions replace the
        # desired target; flooding mpv would continually cancel its frame decode.
        if self.scrub_inflight is not None:
            if restarted:self.scrub_restart_seen=True
            target, sent = self.scrub_inflight
            raw = self.engine.get('time-pos')
            finished = not self.engine.get('seeking', False) and raw is not None and abs(raw-target) < .08
            if finished and (restarted or now-sent > .2):
                self.scrub_inflight = None
            elif self.scrub_restart_seen and now-sent>.05 and not self.engine.get('seeking',False) and raw is not None and raw>target+.1 and self.seek_preroll and self.seek_preroll<60:
                self.seek_preroll=min(60,max(15,self.seek_preroll*2))
                self.engine.set('hr-seek-demuxer-offset',self.seek_preroll)
                self.engine.command('seek',f'{target:.9f}','absolute+exact',asynchronous=True)
                self.scrub_inflight=(target,now);self.scrub_restart_seen=False
                return self.position
            else:
                return self.position
        if self.scrub_video and self.scrub_target != self.scrub_last and now >= self.scrub_next_at:
            self.engine.set('pause', True)
            self.sync_output_mute()
            self.engine.command('seek', f'{self.scrub_target:.9f}', 'absolute+exact', asynchronous=True)
            self.scrub_inflight = self.scrub_target, now
            self.scrub_restart_seen=False
            self.scrub_last = self.scrub_target
            self.scrub_next_at = now+self.scrub_interval
        return self.position

    def end_steps(self):
        if not self.stepping:return
        self.engine.set('pause',True)
        self.step_pending=None;self.step_queue.clear();self.stepping=False
        merge,filters=audio_graphs(len(self.metadata['audio']),self.mix)
        self.engine.set('lavfi-complex',merge);self.engine.set('af',filters)
        self.applied_gains=[gain(m) for m in self.mix]
        self.engine.set('framedrop',self.step_framedrop)

    def step_frame(self, direction, repeat=False):
        if not self.active or not self.ready:
            return False
        if self.step_pending is not None:
            if not repeat:self.step_queue.append(direction)
            return False
        if self.step_queue:
            if not repeat:self.step_queue.append(direction)
            return False
        return self._send_frame(direction)

    def _send_frame(self,direction):
        self.engine.set('pause',True);self.paused=True
        if not self.stepping:
            self.stepping=True;self.step_framedrop=self.engine.get('framedrop','vo')
            # A paused frame inspection needs no audio decoding. In particular,
            # six OBS streams otherwise get decoded again on every back-seek.
            self.engine.set('lavfi-complex','');self.engine.set('af','');self.engine.set('aid','no')
            self.engine.set('framedrop','no')
            if self.metadata['audio']:
                # Switching the graph schedules an internal refresh seek. A
                # back-step sent during that seek would be ignored by mpv.
                self.step_pending={'phase':'prepare','direction':direction}
                return True
        return self._issue_frame(direction)

    def _issue_frame(self,direction):
        self.pending_seek, self.ended = None, False
        self.step_serial+=1
        self.step_pending={'serial':self.step_serial,'from':self.engine.get('time-pos',self.position),'direction':direction,'reply':False}
        self.engine.command('frame-back-step' if direction < 0 else 'frame-step', asynchronous=True,request=self.step_serial)
        return True

    def set_speed(self, speed):
        self.speed = min(8, max(.1, float(speed)))
        if self.active:
            self.engine.set('speed', self.speed)  # Never pause, reopen audio or seek.

    def capture(self):
        """Read this player's decoded frame, never the desktop."""
        if not self.ready:
            return None
        raw = self.engine.command('screenshot-raw', 'video', 'rgba')
        return Image.frombytes('RGBA', (raw['w'], raw['h']), raw['data'], 'raw', 'RGBA', raw['stride']).convert('RGB')

    def capture_preview(self):
        raw=self.engine.command('screenshot-raw','window','rgba')
        return Image.frombytes('RGBA',(raw['w'],raw['h']),raw['data'],'raw','RGBA',raw['stride']).convert('RGB')

    def tick(self, now):
        if not self.active:
            return self.position
        restarted = False
        for event, error, serial, data in self.engine.events():
            if event == 2:
                self.logs.append(data)
            elif event == 8:
                self.ready = True
                if not self.metadata.get('elementary'):
                    self.duration = self.engine.get('duration', self.duration) or self.duration
            elif event == 16 and data and data[0] == 'key-binding':
                self.input_events.append((data[1], data[2][0]))
            elif event == 21:
                restarted = True
                self.pending_seek_restarted = True
            elif event == 5:
                if error < 0:raise ValueError('The player could not complete this operation: ' + self.engine.error_string(error).decode())
                if self.step_pending and serial==self.step_pending.get('serial'):self.step_pending['reply']=True
        if not self.ready:
            if now-self.loading_at > 30 or self.engine.get('idle-active', False) and now-self.loading_at > 2:
                errors = [line[2] for line in self.logs if line[1] in ('error', 'fatal')]
                raise ValueError(errors[-1] if errors else 'mpv could not decode this clip.')
            return self.position
        # mpv rebuilds AF nodes after seeks. Runtime volume commands do not
        # change their construction options, so restore the current gains.
        if restarted and not self.stepping:
            self.applied_gains=[None]*len(self.mix);self.audio_restart_seen=True
        if self.audio_restore_pending and self.audio_restart_seen and not self.engine.get('seeking',False):self.audio_restore_pending=False
        self.apply_mix()
        if self.scrubbing:
            return self._scrub_tick(now, restarted)
        raw = self.engine.get('time-pos')
        seeking = self.engine.get('seeking', False)
        if raw is not None:
            # Keep requested position during paused seeking. A missing clock report
            # must never become a zero playhead. Rapid seeks replace the pending target.
            if self.pending_seek is not None:
                tolerance = max(.12, self.speed*.25)
                elapsed = max(0, now-self.pending_seek_at)
                # Autoplay may already be beyond the requested point by the time
                # a busy UI polls. Accept its advanced clock after a restart;
                # otherwise it would stay pinned to the seek target indefinitely.
                allowance = max(tolerance, elapsed*self.speed+.15) if not self.paused else tolerance
                reached = self.pending_seek-tolerance <= raw <= self.pending_seek+allowance
                if not seeking and reached and (self.pending_seek_restarted or elapsed > .2):
                    self.pending_seek = None
                elif not seeking and self.pending_seek_restarted and elapsed>.05 and raw>self.pending_seek+allowance and self.seek_preroll and self.seek_preroll<60:
                    self.seek_preroll=min(60,max(15,self.seek_preroll*2))
                    self.engine.set('hr-seek-demuxer-offset',self.seek_preroll)
                    self.seek(self.pending_seek)
            if self.pending_seek is None:
                self.position = min(self.duration, max(0, raw))
        self.ended = bool(self.engine.get('eof-reached', False))
        if self.stepping:
            # Native forward stepping temporarily unpauses the decoder. It is
            # still a paused inspection from the user's point of view.
            self.paused=True
            step=self.step_pending
            if step and step.get('phase')=='prepare':
                if restarted and not seeking and raw is not None:self._issue_frame(step['direction'])
            elif step and step['reply'] and not seeking and self.engine.get('pause',True):
                changed=raw is not None and abs(raw-step['from'])>1e-7
                boundary=self.ended or (step['direction']<0 and raw is not None and raw<=1e-7)
                if changed or boundary:self.step_pending=None
            elif not step and self.step_queue:
                self._send_frame(self.step_queue.popleft())
        else:self.paused = True if self.ended else self.engine.get('pause', self.paused)
        return self.position

    def close(self):
        self.clear()
        self.engine.close()
