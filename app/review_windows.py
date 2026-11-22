# SPDX-License-Identifier: GPL-3.0-or-later
"""Use physical screen pixels consistently across mixed-DPI Windows monitors.

Windows can virtualize coordinates using the caller's current DPI context:
https://learn.microsoft.com/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows
Set the app policy before Tk creates windows; scope native geometry queries too.
"""
import ctypes as c
from ctypes import wintypes as w
from contextlib import contextmanager
import os

def initialize_dpi():
    if os.name!='nt':return
    user=c.windll.user32
    try:
        user.SetProcessDpiAwarenessContext.argtypes=[c.c_void_p]
        user.SetProcessDpiAwarenessContext(c.c_void_p(-4))
        user.SetThreadDpiAwarenessContext.argtypes=[c.c_void_p]
        user.SetThreadDpiAwarenessContext.restype=c.c_void_p
        user.SetThreadDpiAwarenessContext(c.c_void_p(-4))
    except AttributeError:
        try:c.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError,OSError):pass

@contextmanager
def physical():
    user=c.windll.user32;previous=None
    try:
        user.SetThreadDpiAwarenessContext.argtypes=[c.c_void_p]
        user.SetThreadDpiAwarenessContext.restype=c.c_void_p
        previous=user.SetThreadDpiAwarenessContext(c.c_void_p(-4))
    except AttributeError:pass
    try:yield user
    finally:
        if previous:user.SetThreadDpiAwarenessContext(previous)

def hwnd(widget,top=False):
    handle=widget.winfo_id()
    if top:
        user=c.windll.user32;user.GetAncestor.argtypes=[w.HWND,w.UINT];user.GetAncestor.restype=w.HWND
        handle=user.GetAncestor(handle,2)
    return handle


def in_foreground(windows):
    if not windows:
        return False
    if os.name != 'nt':
        return any(window.focus_displayof() is not None for window in windows)
    foreground = c.windll.user32.GetForegroundWindow
    foreground.restype = w.HWND
    active = foreground()
    return any(hwnd(window, True) == active for window in windows)


def primary_button_held():
    if os.name != 'nt':
        return False
    user = c.windll.user32
    state = user.GetAsyncKeyState
    state.argtypes, state.restype = [c.c_int], c.c_short
    button = 2 if user.GetSystemMetrics(23) else 1  # SM_SWAPBUTTON
    return bool(state(button) & 0x8000)

def window_move_in_progress():
    """Check the current UI thread's native move or resize loop."""
    if os.name != 'nt':
        return False
    class GuiThreadInfo(c.Structure):
        _fields_ = [('size',w.DWORD),('flags',w.DWORD),('active',w.HWND),('focus',w.HWND),
                    ('capture',w.HWND),('menu_owner',w.HWND),('move_size',w.HWND),('caret',w.HWND),
                    ('caret_rect',w.RECT)]
    info=GuiThreadInfo()
    info.size=c.sizeof(info)
    get_info=c.windll.user32.GetGUIThreadInfo
    get_info.argtypes=[w.DWORD,c.POINTER(GuiThreadInfo)]
    get_info.restype=w.BOOL
    return bool(get_info(c.windll.kernel32.GetCurrentThreadId(),c.byref(info)) and info.flags&2)

def incremental_resize_paint(widget):
    """Let Tk invalidate changed areas instead of erasing every child on resize.

    CS_HREDRAW/CS_VREDRAW force whole-client repaints in addition to Tk's own
    layout/exposure handling. The classes belong to this process; no display or
    system setting changes. Keep the normal native video child paint policy.
    """
    if os.name!='nt':return
    user=c.windll.user32
    user.GetClassLongPtrW.argtypes=[w.HWND,c.c_int];user.GetClassLongPtrW.restype=c.c_size_t
    user.SetClassLongPtrW.argtypes=[w.HWND,c.c_int,c.c_ssize_t];user.SetClassLongPtrW.restype=c.c_size_t
    for handle in (hwnd(widget),hwnd(widget,True)):
        style=user.GetClassLongPtrW(handle,-26)
        if style&3:user.SetClassLongPtrW(handle,-26,style&~3)

def repaint_window(widget):
    """Invalidate stale resize pixels without changing visibility or geometry."""
    if os.name!='nt':return
    user=c.windll.user32
    user.RedrawWindow.argtypes=[w.HWND,c.c_void_p,w.HANDLE,w.UINT]
    user.RedrawWindow.restype=w.BOOL
    # Asynchronous paint, including children. No erase, synchronous flush or
    # WM_SETREDRAW: the native video window remains visible and keeps its clock.
    user.RedrawWindow(hwnd(widget,True),None,None,0x0001|0x0080)

def pointer():
    point=w.POINT();user=c.windll.user32
    user.GetPhysicalCursorPos.argtypes=[c.POINTER(w.POINT)]
    if not user.GetPhysicalCursorPos(c.byref(point)):raise OSError('Cannot read pointer position')
    return point.x,point.y

def window_dpi(widget):
    with physical() as user:
        try:
            user.GetDpiForWindow.argtypes=[w.HWND]
            return user.GetDpiForWindow(hwnd(widget,True)) or 96
        except AttributeError:return 96

def client_rect(widget):
    with physical() as user:
        handle=hwnd(widget);rect=w.RECT();origin=w.POINT()
        user.GetClientRect.argtypes=[w.HWND,c.POINTER(w.RECT)];user.ClientToScreen.argtypes=[w.HWND,c.POINTER(w.POINT)]
        if not user.GetClientRect(handle,c.byref(rect)) or not user.ClientToScreen(handle,c.byref(origin)):raise OSError('Cannot read window bounds')
        return origin.x,origin.y,origin.x+rect.right,origin.y+rect.bottom

def window_rect(widget):
    with physical() as user:
        rect=w.RECT();user.GetWindowRect.argtypes=[w.HWND,c.POINTER(w.RECT)]
        if not user.GetWindowRect(hwnd(widget,True),c.byref(rect)):raise OSError('Cannot read window bounds')
        return rect.left,rect.top,rect.right,rect.bottom

def place_window(widget,x,y,width=None,height=None):
    with physical() as user:
        user.SetWindowPos.argtypes=[w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT]
        flags=0x0010|0x0004|(0x0001 if width is None else 0)
        if not user.SetWindowPos(hwnd(widget,True),None,round(x),round(y),round(width or 0),round(height or 0),flags):raise OSError('Cannot place window')

def monitor_rect(widget,work=False):
    class INFO(c.Structure):_fields_=[('size',w.DWORD),('monitor',w.RECT),('work',w.RECT),('flags',w.DWORD)]
    with physical() as user:
        user.MonitorFromWindow.argtypes=[w.HWND,w.DWORD];user.MonitorFromWindow.restype=w.HANDLE
        user.GetMonitorInfoW.argtypes=[w.HANDLE,c.POINTER(INFO)]
        info=INFO();info.size=c.sizeof(INFO)
        if not user.GetMonitorInfoW(user.MonitorFromWindow(hwnd(widget,True),2),c.byref(info)):raise OSError('Cannot read display bounds')
        rect=info.work if work else info.monitor
        return rect.left,rect.top,rect.right,rect.bottom
