# SPDX-License-Identifier: GPL-3.0-or-later
"""User-supplied app artwork for the root window and every owned dialog."""
import ctypes
from pathlib import Path
import sys
import tkinter as tk
from PIL import Image, ImageTk


def asset_folder():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'


def set_taskbar_identity():
    if sys.platform == 'win32':
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('ClipCombPro.Desktop')


def install_app_icons(root):
    """Load once; Tk's default applies to future top-level windows as well."""
    if getattr(root, 'replaysift_icons', None):
        return
    folder = asset_folder()
    with Image.open(folder / 'logo.png') as image:
        source = image.convert('RGBA')
        root.replaysift_icons = tuple(ImageTk.PhotoImage(
            source.resize((size, size), Image.Resampling.LANCZOS), master=root)
            for size in (16, 24, 32, 48, 64, 128, 256))
    root.iconphoto(True, *root.replaysift_icons)
    root.replaysift_icon_path = str(folder / 'logo.ico')
    if sys.platform == 'win32':
        root.iconbitmap(default=root.replaysift_icon_path)
        root.iconbitmap(root.replaysift_icon_path)


def apply_window_icon(window):
    """Explicit assignment also covers dialogs created by another parent."""
    root = window._root()
    if getattr(root, 'replaysift_icon_path', None) and sys.platform == 'win32':
        window.iconbitmap(root.replaysift_icon_path)
    elif getattr(root, 'replaysift_icons', None):
        window.iconphoto(False, *root.replaysift_icons)


def header_logo(root,light=False):
    if not light:return root.replaysift_icons[3]
    if not hasattr(root,'clipcomb_light_logo'):
        path=asset_folder()/'ClipComb Logo No Outline.png'
        if not path.is_file():return root.replaysift_icons[3]
        with Image.open(path) as picture:
            root.clipcomb_light_logo=ImageTk.PhotoImage(picture.convert('RGBA').resize((48,48),Image.Resampling.LANCZOS),master=root)
    return root.clipcomb_light_logo
