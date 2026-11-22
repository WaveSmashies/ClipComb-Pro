# Building ClipComb Pro

Use 64-bit Windows and Python with Tkinter. Windows CI runs the tests on Python 3.10 and 3.12.

From a PowerShell window in this folder:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m unittest discover -s tests -p "test_*.py" -v
.venv\Scripts\python clip_review.py
```

If prompted, click **Download Tools** on first launch. See [MEDIA-TOOLS.md](docs/MEDIA-TOOLS.md) for manual setup. Running the source creates `ClipComb Pro.ini` in this folder. An existing `clip-review.ini` is migrated automatically. For a clean portable executable:

```powershell
.venv\Scripts\python tools\build_release.py
```

The build writes an **app-only** folder and ZIP under `dist`, plus a source ZIP and SHA-256 checksums. The folder contains `ClipComb Pro.exe`, the direct Resolve bridge, default settings and license notices. It does not include libmpv, FFprobe or FFmpeg, personal preferences, test media or generated caches. Do not copy a development INI into a public archive.

The build uses pinned application/build dependencies. It collects their installed license notices and fails if required notices are unavailable. PyInstaller creates a Windows GUI application, so build on Windows. `tools/build_release.py --output SOME_NEW_FOLDER` selects another destination. It refuses an existing destination to avoid overwriting preferences or mixing public/private files.

Add `--folder-only` to create no ZIP files. That build includes a complete
`Source` subfolder instead of `Source.zip`, and writes executable checksums.

## Embedded tutorial

The optional embedded player uses the installed Microsoft Edge WebView2 Runtime
and a small host built from `tools/TutorialHost.cs`. It has no Python browser
dependency and never accesses a user's ordinary browser profile. Build the host
on 64-bit Windows with .NET Framework 4.6.2 or newer:

```powershell
python tools\build_tutorial.py --output dist\tutorial-runtime
python tools\build_release.py --folder-only --tutorial-runtime dist\tutorial-runtime
```

The first command downloads a pinned official Microsoft SDK package, verifies its
SHA-256, compiles the host and includes Microsoft's BSD license. Use
`--sdk-package PATH_TO_NUPKG` for an existing matching package. The Runtime itself
is not redistributed; if unavailable, Watch On YouTube opens the system browser.
The built `tutorial` folder must accompany the executable. Its separate WebView2
profile is created next to the app only when opening the tutorial. YouTube needs
an internet connection; no video is downloaded into the release.

## Binary distribution

The Windows ZIP includes the app's corresponding source. ClipComb Pro downloads the media tools directly from their distributors on first launch. See [THIRD-PARTY.md](THIRD-PARTY.md).

The Windows workflow runs unit tests and builds an app-only candidate. It uploads build artifacts for review; it has no publishing step or repository-write permission.
