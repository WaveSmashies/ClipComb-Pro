# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the optional Windows embedded tutorial host with the official WebView2 SDK."""
import argparse,hashlib,json,os,shutil,subprocess,tempfile,urllib.request,zipfile
from pathlib import Path

VERSION='1.0.4314.35'
URL=f'https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/{VERSION}/microsoft.web.webview2.{VERSION}.nupkg'
SHA256='90778deb1b77e36292828b4b5833c9255c27533f40e0ddd55891ae718944edc4'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--sdk-package',type=Path,help='Use an already downloaded official NuGet package.')
    args=parser.parse_args()
    if os.name!='nt':parser.error('Build on Windows with .NET Framework 4.6.2 or later.')
    target=args.output.resolve()
    if target.exists():parser.error('Choose a new output folder.')
    with tempfile.TemporaryDirectory(prefix='clipcomb-webview-') as temp:
        folder=Path(temp);package=args.sdk_package or folder/'sdk.nupkg'
        if not args.sdk_package:urllib.request.urlretrieve(URL,package)
        if hashlib.sha256(package.read_bytes()).hexdigest()!=SHA256:raise ValueError('SDK checksum mismatch.')
        with zipfile.ZipFile(package) as archive:
            for name in ('lib/net462/Microsoft.Web.WebView2.Core.dll','lib/net462/Microsoft.Web.WebView2.WinForms.dll','build/native/x64/WebView2Loader.dll','LICENSE.txt'):
                (folder/Path(name).name).write_bytes(archive.read(name))
        compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+',
            '/out:'+str(folder/'ClipComb Tutorial.exe'),'/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',
            '/reference:'+str(folder/'Microsoft.Web.WebView2.Core.dll'),'/reference:'+str(folder/'Microsoft.Web.WebView2.WinForms.dll'),
            str(Path(__file__).with_name('TutorialHost.cs'))],check=True)
        target.mkdir(parents=True)
        for name in ('ClipComb Tutorial.exe','Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll','LICENSE.txt'):shutil.copy2(folder/name,target/name)
        (target/'SDK.json').write_text(json.dumps(dict(package='Microsoft.Web.WebView2',version=VERSION,url=URL,sha256=SHA256,host_source_sha256=hashlib.sha256(Path(__file__).with_name('TutorialHost.cs').read_bytes()).hexdigest()),indent=2)+'\n',encoding='utf-8')
    print('Tutorial host built with official SDK notices:',target)

if __name__=='__main__':main()
