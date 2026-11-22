# Media tools

On first launch, click **Download Tools** to install libmpv, FFmpeg and FFprobe directly from their distributors. The one-time download requires internet access. After setup, you can review clips offline.

For offline setup or to supply your own builds, add these Windows x64 files in a `player` folder beside `ClipComb Pro.exe` (or beside `clip_review.py` when running the source):

```text
ClipComb Pro.exe
bridge/
licenses/
player/
  libmpv-2.dll
  ffprobe.exe
  ffmpeg.exe
```

1. Find a libmpv Windows build through [mpv's installation page](https://mpv.io/installation/). A development build includes `libmpv-2.dll`; a player-only download may not. Extract the DLL and any accompanying runtime dependencies according to the build's instructions.
2. Find an FFmpeg Windows build through [FFmpeg's download page](https://ffmpeg.org/download.html#build-windows). Extract `ffmpeg.exe` and `ffprobe.exe` from its `bin` folder. Keep any required accompanying DLLs for shared builds.
3. Put those files in `player`, then reopen ClipComb Pro. Alternatively, Settings → Playback accepts their individual paths.

Do not rename a 32-bit library or an `mpv.exe` to `libmpv-2.dll`; ClipComb Pro needs an actual 64-bit libmpv library. Prefer an official project-linked distributor and retain the distributor's notices.

Automatic setup uses the [official libmpv 0.42.0 release](https://github.com/mpv-player/mpv/releases/tag/v0.42.0) and [Gyan's FFmpeg and FFprobe 9.0.2 Essentials build](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2). Other builds need to support the libmpv stable C API, gpu-next/D3D11, `scaletempo2`, and the FFmpeg filters used for multistream mixing.

Playback does not contact a service, require an AI connection, or require DaVinci Resolve. Direct timeline import is optional and has its own Studio requirement.
