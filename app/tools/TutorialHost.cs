// SPDX-License-Identifier: GPL-3.0-or-later
// ClipComb Pro's WebView2 host. Microsoft SDK components retain their BSD notices.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

class TutorialHost : Form {
    [DllImport("user32.dll")] static extern IntPtr SetParent(IntPtr child,IntPtr parent);
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr hwnd,out Rect rect);
    [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr hwnd,int index);
    [DllImport("user32.dll")] static extern int SetWindowLong(IntPtr hwnd,int index,int value);
    [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr context);
    [StructLayout(LayoutKind.Sequential)] struct Rect {public int Left,Top,Right,Bottom;}
    IntPtr parent;string profile,assets;WebView2 web;System.Windows.Forms.Timer resize;
    TutorialHost(string[] args) {
        parent=new IntPtr(long.Parse(args[0]));profile=args[1];assets=args[2];
        FormBorderStyle=FormBorderStyle.None;ShowInTaskbar=false;Text="ClipComb Pro Tutorial Player";BackColor=Color.Black;
        web=new WebView2();web.Dock=DockStyle.Fill;Controls.Add(web);
        Shown+=async delegate {
            SetWindowLong(Handle,-16,(GetWindowLong(Handle,-16)&~unchecked((int)0x80000000))|0x40000000);
            SetParent(Handle,parent);
            resize=new System.Windows.Forms.Timer();resize.Interval=100;
            resize.Tick+=delegate {Rect r;if(!IsWindow(parent)){Close();return;}if(GetClientRect(parent,out r))Bounds=new Rectangle(0,0,r.Right,r.Bottom);};
            resize.Start();
            var input=new Thread(delegate(){Console.ReadLine();try{BeginInvoke((Action)delegate{Hide();web.Visible=false;SetParent(Handle,IntPtr.Zero);Close();});}catch{}});input.IsBackground=true;input.Start();
            try {
                var options=new CoreWebView2EnvironmentOptions("--disk-cache-size=16777216 --media-cache-size=16777216");
                var environment=await CoreWebView2Environment.CreateAsync(null,profile,options);
                await web.EnsureCoreWebView2Async(environment);
                web.CoreWebView2.Settings.AreDevToolsEnabled=false;
                web.CoreWebView2.SetVirtualHostNameToFolderMapping("clipcombpro.desktop",assets,CoreWebView2HostResourceAccessKind.DenyCors);
                web.CoreWebView2.NewWindowRequested+=delegate(object sender,CoreWebView2NewWindowRequestedEventArgs e){
                    e.Handled=true;Uri url;if(Uri.TryCreate(e.Uri,UriKind.Absolute,out url)&&url.Scheme=="https")Process.Start(new ProcessStartInfo(e.Uri){UseShellExecute=true});
                };
                web.CoreWebView2.NavigationCompleted+=delegate(object sender,CoreWebView2NavigationCompletedEventArgs e){Console.WriteLine(e.IsSuccess?"READY":"ERROR: Tutorial page could not load.");Console.Out.Flush();};
                web.CoreWebView2.Navigate("https://clipcombpro.desktop/player.html");
            } catch(Exception ex){Console.WriteLine("ERROR: "+ex.Message);Console.Out.Flush();Close();}
        };
        FormClosed+=delegate{if(resize!=null)resize.Dispose();web.Dispose();};
    }
    [STAThread] static void Main(string[] args) {
        if(args.Length==1&&args[0]=="--probe"){Console.WriteLine(CoreWebView2Environment.GetAvailableBrowserVersionString());return;}
        if(args.Length!=3)return;
        SetProcessDpiAwarenessContext(new IntPtr(-4));Application.EnableVisualStyles();Application.Run(new TutorialHost(args));
    }
}
