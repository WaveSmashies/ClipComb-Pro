# SPDX-License-Identifier: GPL-3.0-or-later
"""Build an app-only candidate; never collect a developer's player or settings."""
import argparse
import hashlib
from importlib import metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from review_brand import APP_NAME, VERSION
from review_core import Settings,CONFIG_FILE


def source_files():
    for path in sorted(ROOT.rglob('*')):
        relative = path.relative_to(ROOT)
        if any(p in {'__pycache__', '.git', '.venv', 'venv', 'build', 'dist', 'qa',
                     'vendor', 'player', 'bridge', 'cache', 'Generated Waveforms'} for p in relative.parts):
            continue
        if path.is_file() and (relative.as_posix() in {
                '.gitignore', '.gitattributes', 'LICENSE', CONFIG_FILE+'.example',
                'requirements.txt', 'requirements-dev.txt'} or
                (relative.parts[0] in {'assets', 'artwork'} and path.suffix.lower() in {'.png', '.ico', '.af', '.blend', '.jpg','.json','.gif','.html','.txt'}) or
                (path.suffix.lower() in {'.py', '.md', '.yml', '.txt','.manifest','.cs'} and
                 (len(relative.parts) == 1 or relative.parts[0] in {'tests', 'tools', 'docs', 'licenses', '.github'}))):
            yield path


def add_licenses(destination):
    destination.mkdir()
    python_root = Path(sys.base_prefix)
    required = {
        'Python.txt': [python_root / 'LICENSE.txt', python_root / 'LICENSE'],
        'Tcl.txt': [python_root / 'tcl/tcl8.6/license.terms', python_root / 'tcl/tcl8.7/license.terms', ROOT / 'licenses/Tcl-8.6.txt'],
        'Tk.txt': [python_root / 'tcl/tk8.6/license.terms', python_root / 'tcl/tk8.7/license.terms'],
    }
    for package, filename, needle in [
        ('Pillow', 'Pillow.txt', 'license'),
        ('PyInstaller', 'PyInstaller.txt', 'copying.txt'),
        ('opentimelineio', 'OpenTimelineIO.txt', 'license.txt'),
        ('opentimelineio', 'OpenTimelineIO-NOTICE.txt', 'notice.txt'),
    ]:
        distribution = metadata.distribution(package)
        required[filename] = [Path(distribution.locate_file(p)) for p in distribution.files or []
                              if Path(p).name.lower() == needle or
                              (package == 'Pillow' and Path(p).name.lower() == 'license')]
    for filename, candidates in required.items():
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            raise RuntimeError(f'Missing required license: {filename}. Check the installed dependency.')
        shutil.copy2(path, destination / filename)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / f'{APP_NAME}-{VERSION}-app-only')
    parser.add_argument('--tutorial-runtime',type=Path,help='Built WebView2 host folder; see tools/build_tutorial.py')
    parser.add_argument('--folder-only',action='store_true',help='Deliver a folder with a Source subfolder; create no ZIP archives.')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Build the Windows app on Windows.')
    target = args.output.resolve()
    archive = Path(str(target) + '.zip')
    sources = target.parent / f'{APP_NAME}-{VERSION}-Source.zip'
    checksum = target.parent / f'{APP_NAME}-{VERSION}-SHA256SUMS.txt'
    if any(p.exists() for p in (target, archive, sources, checksum)):
        parser.error('The destination already exists. Choose a new output folder.')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='clipcomb-build-') as folder:
        temp = Path(folder)
        staged = temp / target.name
        staged.mkdir()
        version = tuple(int(p) for p in VERSION.split('.')) + (0,)
        version_file = temp / 'version.txt'
        version_file.write_text(
            f"VSVersionInfo(ffi=FixedFileInfo(filevers={version!r}, prodvers={version!r}, "
            "mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)), "
            "kids=[StringFileInfo([StringTable('040904b0', ["
            f"StringStruct('ProductName', {APP_NAME!r}), StringStruct('FileDescription', {APP_NAME!r}), "
            f"StringStruct('FileVersion', {VERSION!r}), StringStruct('ProductVersion', {VERSION!r}), "
            f"StringStruct('OriginalFilename', {APP_NAME + '.exe'!r})])]), "
            "VarFileInfo([VarStruct('Translation', [1033,1200])])])", encoding='utf-8')
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                        '--onefile', '--windowed', '--exclude-module', 'numpy',
                        '--exclude-module', 'opentimelineio.console', '--exclude-module', 'opentimelineio.test_utils',
                        '--collect-data', 'opentimelineio', '--name', APP_NAME,
                        '--icon', str(ROOT / 'assets/logo.ico'),
                        '--manifest',str(ROOT/'tools/ClipCombPro.manifest'),
                        '--add-data', str(ROOT / 'assets') + os.pathsep + 'assets',
                        '--version-file', str(version_file), '--distpath', str(staged),
                        '--workpath', str(temp / 'work'), '--specpath', str(temp),
                        str(ROOT / 'clip_review.py')], check=True, cwd=ROOT)
        bridge = staged / 'bridge'
        bridge.mkdir()
        for name in ('review_resolve.py','review_resolve_sync.py','review_export.py','review_marker_colors.py','review_marker_ranges.py'):
            shutil.copy2(ROOT / name, bridge / name)
        for name in ('README.md', '1 User Guide (Read Me!).MD', 'BUILDING.md', 'LICENSE',
                     'COPYRIGHT.md', 'THIRD-PARTY.md', 'CHANGELOG.md', 'CONTRIBUTING.md'):
            shutil.copy2(ROOT / name, staged / name)
        shutil.copytree(ROOT / 'docs', staged / 'docs')
        shutil.copytree(ROOT / 'assets', staged / 'assets')
        readme_image = Path('artwork/timeline-1.gif')
        (staged / readme_image).parent.mkdir(parents=True)
        shutil.copy2(ROOT / readme_image, staged / readme_image)
        add_licenses(staged / 'licenses')
        if args.tutorial_runtime:
            tutorial=args.tutorial_runtime.resolve()
            required=('ClipComb Tutorial.exe','Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll','LICENSE.txt','SDK.json')
            if not all((tutorial/name).is_file() for name in required):raise ValueError('Tutorial host or required notices are missing.')
            (staged/'tutorial').mkdir()
            for name in required:shutil.copy2(tutorial/name,staged/'tutorial'/name)
        # Do not overwrite a user's settings when extracting an upgrade.
        shutil.copy2(ROOT/(CONFIG_FILE+'.example'),staged/(CONFIG_FILE+'.example'))
        if args.folder_only:
            for path in source_files():
                destination=staged/'Source'/path.relative_to(ROOT);destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,destination)
        else:
            with zipfile.ZipFile(staged / 'Source.zip', 'w', zipfile.ZIP_DEFLATED) as z:
                for path in source_files():z.write(path, path.relative_to(ROOT))
            shutil.copy2(staged / 'Source.zip', sources)
        shutil.copytree(staged, target)
    if not args.folder_only:
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in sorted(target.rglob('*')):
                if path.is_file():z.write(path, Path(target.name) / path.relative_to(target))
    paths = (target / f'{APP_NAME}.exe',) if args.folder_only else (target / f'{APP_NAME}.exe', archive, sources)
    checksum.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(target.parent).as_posix()}\n'
                                for p in paths), encoding='utf-8')
    print(f'Built {target if args.folder_only else archive}. The app offers media setup on first launch.')


if __name__ == '__main__':
    main()
