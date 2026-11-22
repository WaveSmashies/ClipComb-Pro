# SPDX-License-Identifier: GPL-3.0-or-later
"""Extra mouse buttons for this application's Tk thread only.

Tk 8.6 on Windows does not translate WM_XBUTTON messages consistently. A
thread-local hook routes them through the same shortcut recorder/dispatcher;
it does not monitor other applications or install a system-wide input hook.
"""
import ctypes as c
from ctypes import wintypes as w
import os
from queue import SimpleQueue


class MouseHookPoint(c.Structure):
    _fields_ = [('point', w.POINT), ('hwnd', w.HWND), ('hit', w.UINT),
                ('extra', c.c_size_t)]


class MouseHookData(MouseHookPoint):
    _fields_ = [('mouse_data', w.DWORD)]


class ExtraMouseButtons:
    def __init__(self, wants):
        self.events = SimpleQueue()
        self.handle, self.callback = None, None
        if os.name != 'nt':
            return
        self.user, kernel = c.windll.user32, c.windll.kernel32
        result = c.c_ssize_t
        callback_type = c.WINFUNCTYPE(result, c.c_int, w.WPARAM, w.LPARAM)
        self.user.SetWindowsHookExW.argtypes = [c.c_int, callback_type, w.HINSTANCE, w.DWORD]
        self.user.SetWindowsHookExW.restype = w.HHOOK
        self.user.CallNextHookEx.argtypes = [w.HHOOK, c.c_int, w.WPARAM, w.LPARAM]
        self.user.CallNextHookEx.restype = result
        self.user.UnhookWindowsHookEx.argtypes = [w.HHOOK]
        self.user.GetKeyState.argtypes, self.user.GetKeyState.restype = [c.c_int], c.c_short
        def receive(code, message, pointer):
            if code == 0 and message in (0x207, 0x208, 0x209, 0x20B, 0x20C, 0x20D):
                if message in (0x207, 0x208, 0x209):
                    data = c.cast(pointer, c.POINTER(MouseHookPoint)).contents
                    button = 2
                else:
                    data = c.cast(pointer, c.POINTER(MouseHookData)).contents
                    button = {1: 4, 2: 5}.get(data.mouse_data >> 16)
                if button and wants(button):
                    state = sum(mask for vk,mask in ((0x10,1),(0x11,4),(0x12,0x20000))
                                if self.user.GetKeyState(vk) < 0)
                    down = message not in (0x208, 0x20C)
                    # Windows can invoke the hook from inside Tk's message loop.
                    # Leave all Tk calls to the app's scheduled queue drain.
                    self.events.put((button, down, state, data.point.x, data.point.y))
                    return 1
            return self.user.CallNextHookEx(self.handle, code, message, pointer)
        self.callback = callback_type(receive)
        self.handle = self.user.SetWindowsHookExW(7, self.callback, None, kernel.GetCurrentThreadId())
        if not self.handle:
            raise OSError('Could not enable extra mouse buttons for ClipComb Pro.')

    def close(self):
        if self.handle:
            self.user.UnhookWindowsHookEx(self.handle)
            self.handle = None
