# SPDX-License-Identifier: GPL-3.0-or-later
"""One Tk update timer, paced by playback, pending work and window visibility."""
import time


def update_interval(*, visible, foreground, realtime=False, working=False, paused_player=False, frame_ms=16):
    if not visible:
        return 1000
    if realtime:
        return max(8, frame_ms)
    if not foreground:
        return 400
    if paused_player:
        return 55  # Native video input can arrive while the clip is paused.
    return 80 if working else 200


class UpdateTimer:
    def __init__(self, root, callback):
        self.root = root
        self.callback = callback
        self.token = None
        self.deadline = 0.0
        self.closed = False
        self.running = False
        self.wake_pending = False

    def schedule(self, delay):
        if self.closed:
            return
        if self.running and delay == 0:
            self.wake_pending = True
            return
        deadline = time.monotonic() + delay / 1000
        if self.token is not None:
            if self.deadline <= deadline:
                return
            self.root.after_cancel(self.token)
        self.deadline = deadline
        self.token = self.root.after(delay, self.run)

    def run(self):
        self.token = None
        if not self.closed:
            self.running = True
            try:
                self.callback()
            finally:
                self.running = False
                if self.wake_pending:
                    self.wake_pending = False
                    self.schedule(0)

    def close(self):
        self.closed = True
        if self.token is not None:
            self.root.after_cancel(self.token)
            self.token = None
