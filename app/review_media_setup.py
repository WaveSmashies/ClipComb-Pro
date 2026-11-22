# SPDX-License-Identifier: GPL-3.0-or-later
"""Install verified media tools directly from their distributors on first use."""
from hashlib import sha256
from pathlib import Path
from queue import Empty, Queue
import shutil
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

from review_player import find_mpv


MPV = (
    'https://github.com/mpv-player/mpv/releases/download/v0.42.0/libmpv-v0.42.0-x86_64-w64-mingw32-gpl.zip',
    'b99e0d183024ae479d1b36a93fa262c0297dfb025b99715b98da377ffb6c2913',
    65_742_725,
    {'libmpv-2.dll': 'libmpv-2.dll', 'LICENSE.GPL': 'libmpv-LICENSE.GPL'},
)
FFMPEG = (
    'https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip',
    '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba',
    114_768_076,
    {
        'ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe': 'ffmpeg.exe',
        'ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe': 'ffprobe.exe',
        'ffmpeg-9.0.2-essentials_build/LICENSE': 'FFmpeg-LICENSE.txt',
    },
)


def missing_tools(base, tools):
    missing = set()
    if not find_mpv(base, tools['mpv_library']):
        missing.add('libmpv-2.dll')
    for name in ('ffmpeg', 'ffprobe'):
        filename = f'{name}.exe'
        if not (tools[name] or (base / 'player' / filename).is_file() or shutil.which(name)
                or (name == 'ffmpeg' and (base / 'vendor/ffmpeg' / filename).is_file())):
            missing.add(filename)
    return missing


def download_tools(base, missing, progress, open_url=urlopen):
    player = base / 'player'
    player.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='.setup-', dir=player) as directory:
        staging = Path(directory)
        archive = staging / 'download.zip'
        for label, package in (('libmpv', MPV), ('FFmpeg', FFMPEG)):
            url, checksum, size, members = package
            if missing.isdisjoint(members.values()):
                continue
            request = Request(url, headers={'User-Agent': 'ClipComb-Pro'})
            downloaded = 0
            digest = sha256()
            with open_url(request, timeout=30) as response, archive.open('wb') as output:
                while block := response.read(256 * 1024):
                    downloaded += len(block)
                    if downloaded > size:
                        raise ValueError(f'The {label} download is larger than expected.')
                    digest.update(block)
                    output.write(block)
                    progress(label, downloaded, size)
            if digest.hexdigest() != checksum:
                raise ValueError(f'The {label} download failed verification. Please try again.')
            progress(label, size, size)
            with ZipFile(archive) as package_zip:
                for member, filename in members.items():
                    if filename in missing or not filename.endswith(('.exe', '.dll')):
                        with package_zip.open(member) as source, (staging / filename).open('wb') as dest:
                            shutil.copyfileobj(source, dest)
        archive.unlink(missing_ok=True)
        for path in staging.iterdir():
            try:
                path.rename(player / path.name)
            except FileExistsError:
                pass  # On Windows another instance may have completed setup first.


def offer_media_setup(root, base, settings):
    tools = settings.data['tools']
    if not missing_tools(base, tools):
        return
    import tkinter as tk
    from tkinter import ttk
    from review_theme import dialog, install_theme, palette_for_settings, present

    install_theme(root, palette_for_settings(settings))
    window = dialog(root, 'Set Up Media Tools')
    window.transient('')
    window.resizable(False, False)
    page = ttk.Frame(window, padding=20)
    page.pack(fill='both', expand=True)
    ttk.Label(page, text='Set Up Media Tools', style='Subheading.TLabel').pack(anchor='w')
    ttk.Label(page, wraplength=420, justify='left', text=(
        'ClipComb Pro needs libmpv and FFmpeg to play and review clips. '
        'Download the missing tools directly from their distributors (up to 181 MB). '
        'Setup only runs once and needs an internet connection.'
    )).pack(anchor='w', pady=(8, 12))
    status = tk.StringVar(master=window)
    ttk.Label(page, textvariable=status, wraplength=420).pack(anchor='w')
    bar = ttk.Progressbar(page, maximum=100, length=400)
    bar.pack(fill='x', pady=(5, 12))
    buttons = ttk.Frame(page)
    buttons.pack(fill='x')
    skip = ttk.Button(buttons, text='Set Up Later', style='Round.TButton', command=window.destroy)
    skip.pack(side='left')
    result = Queue()
    latest = None

    def worker(missing):
        nonlocal latest

        def progress(label, count, total):
            nonlocal latest
            latest = (label, count * 100 // total)

        try:
            download_tools(base, missing, progress)
        except (OSError, ValueError, KeyError, BadZipFile) as error:
            result.put(str(error))
        else:
            result.put('')

    def poll():
        if latest is not None:
            label, percent = latest
            status.set(f'Setting up {label}… {percent}%')
            bar.configure(value=percent)
        try:
            error = result.get_nowait()
        except Empty:
            window.after(100, poll)
            return
        if not error:
            window.destroy()
            return
        status.set(f'Setup failed. {error}')
        install.configure(text='Try Again', state='normal')
        skip.configure(state='normal')
        window.protocol('WM_DELETE_WINDOW', window.destroy)
        window.bind('<Escape>', lambda _event: window.destroy())

    def start():
        nonlocal latest
        missing = missing_tools(base, tools)
        if not missing:
            window.destroy()
            return
        latest = None
        status.set('Connecting to the download server…')
        bar.configure(value=0)
        install.configure(state='disabled')
        skip.configure(state='disabled')
        window.protocol('WM_DELETE_WINDOW', lambda: None)
        window.bind('<Escape>', lambda _event: 'break')
        Thread(target=worker, args=(missing,), daemon=True).start()
        window.after(100, poll)

    install = ttk.Button(buttons, text='Download Tools', style='Primary.TButton', command=start)
    install.pack(side='right')
    width, height = root.winfo_screenwidth(), root.winfo_screenheight()
    present(window, root, work_area=(0, 0, width, height))
    window.geometry(f'+{max(0, (width-window.winfo_width())//2)}+{max(0, (height-window.winfo_height())//2)}')
    install.focus_set()
    root.wait_window(window)
