# Third-party components

ClipComb Pro's application source is GPL-3.0-or-later; the full license is in LICENSE. The public app-only build includes the app's source and the notices for the Python components it bundles. Media engines are obtained separately; they are not included in the public source or app-only ZIP.

The original app logo and its editable Blender and Affinity sources are covered by the project's GPL-3.0-or-later grant in COPYRIGHT.md. They do not add a stock-art license or royalty requirement.

## Python, Tcl/Tk, Pillow and PyInstaller

The executable embeds the build environment's Python and Tcl/Tk, plus Pillow 12.3.0. Python uses the PSF license and associated historical notices; Tcl/Tk and Pillow have their own permissive licenses. The release builder copies their full installed license notices into `licenses`. PyInstaller 6.21.0 has a bootloader exception that permits generated executables to be distributed under the application's license; its COPYING text is included as well.

- Python: https://www.python.org/psf/license/
- Tcl/Tk: https://www.tcl.tk/software/tcltk/license.html
- Pillow: https://github.com/python-pillow/Pillow/tree/12.3.0
- PyInstaller: https://github.com/pyinstaller/pyinstaller/tree/v6.21.0

## Embedded tutorial

The optional tutorial host uses the Windows WebView2 Runtime and Microsoft's
Microsoft.Web.WebView2 SDK 1.0.4314.35. The three SDK redistributables retain
Microsoft's BSD-style license, included in `tutorial/LICENSE.txt` when bundled.
The host's complete C# source is in `tools/TutorialHost.cs`, under the project GPL.
The WebView2 Runtime is a separately installed Windows browser component; it is
not copied into ClipComb Pro. The tutorial uses an isolated app profile and an
official YouTube privacy-enhanced embed, with normal controls and branding intact.
No video is downloaded, re-encoded, or redistributed as part of the app.
Playback is subject to YouTube's service terms and the video's embed permissions.

- SDK and license: https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.4314.35
- Runtime: https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution
- Embed requirements: https://developers.google.com/youtube/terms/required-minimum-functionality

## OpenTimelineIO details

OTIO export uses the official OpenTimelineIO 0.18.1 library. Its Apache-2.0 license and NOTICE are copied into `licenses/OpenTimelineIO.txt` and `licenses/OpenTimelineIO-NOTICE.txt`. Source: https://github.com/AcademySoftwareFoundation/OpenTimelineIO/tree/v0.18.1 .

## Separately obtained media engines

Playback uses the stable libmpv C interface directly; no third-party Python mpv wrapper is used. FFprobe reads metadata. FFmpeg generates audio-only waveform peaks, extracts marked audio portions for file exports, and remuxes verified file trims and overlap merges. The overlap tools reuse project-authored code from the earlier private Replay Trim Review app and use the same libmpv/FFmpeg dependencies; VLC is not required or bundled. These tools have their own licensing terms, which also depend on how their distributors build and link them.

The private development environment tested these unmodified builds:

- shinchiro libmpv `mpv-dev-x86_64-20261111-git-bcde6b93cc.7z`, mpv revision `bcde6b93cc`.
- shinchiro FFmpeg `ffmpeg-x86_64-git-cd4e96eb3.7z`, FFmpeg revision `cd4e96eb3`.
- Gyan FFprobe `ffmpeg-9.0.2-essentials_build`, revision `946fcce07b`.

Build releases and upstream sources:

- https://github.com/shinchiro/mpv-winbuild-cmake/releases/tag/20261111
- https://github.com/shinchiro/mpv-winbuild-cmake
- https://github.com/mpv-player/mpv/tree/bcde6b93cc
- https://github.com/FFmpeg/FFmpeg/tree/cd4e96eb3
- https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2

## All-in-one distributions

The Windows ZIP ships ClipComb Pro. On first launch, ClipComb Pro offers to download the [official libmpv 0.42.0 build](https://github.com/mpv-player/mpv/releases/tag/v0.42.0) and the [FFmpeg 9.0.2 Essentials build from Gyan](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2) directly from their distributors. Setup verifies each archive's SHA-256 and retains its license notice. The [media tools guide](docs/MEDIA-TOOLS.md) also describes manual setup.
