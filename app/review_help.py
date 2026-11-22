# SPDX-License-Identifier: GPL-3.0-or-later
"""Small, keyboard-accessible help badges and mouse-following tooltips."""
import tkinter as tk
from tkinter import ttk
from review_core import Settings,DEFAULT_KEYS
from review_tooltip_text import wording

DEFAULTS=Settings().data
def default_help(section,key,text=None):
    value=DEFAULTS[section][key]
    shown={'yes':'On','no':'Off','':'Blank (automatic)'}.get(value,value)
    return (text or HELP[section,key])+f'\n\nDefault: {shown}.'

HELP = {
 ('app','media_play_pause'):'Some keyboards have a "Media" button which can be used to pause or play video players on your system. If you\'re already familiar with them, and want to use it to pause or resume playback in ClipComb Pro... you can.\n\nNOT RECOMMENDED.',
 ('archive','show_warning'):'Show the warning when entering Archive Tools. Turn this back on to see a warning you previously dismissed.',
 ('timeline','right_click_existing'):'Right-click an existing In/Out mark to select and drag it. Left-click moves the playhead instead when this is enabled. This setting applies only to In/Out marks: bookmarks above them always accept left clicks and drags. Alt-drag a point bookmark to extend it, then drag either end to resize. Clicking a bookmark always jumps to it, even with snapping off. Double-click a bookmark to edit it. Right-drag empty space to make a new In/Out mark.',
 ('thumbnails','delete_after_30_days'):'Delete ClipComb-generated thumbnails that are at least 30 days old. Checked on startup and daily while the app stays open. Windows thumbnails and recordings are untouched. Enabling this turns off cleanup on app close.',
 ('waveform','delete_after_30_days'):'Delete generated waveform cache files that are at least 30 days old. Checked on startup and daily while the app stays open. They regenerate when needed. Enabling this turns off cleanup on app close.',
 ('thumbnails','delete_on_close'):'Delete ClipComb-generated thumbnails when the app closes normally. Windows thumbnails and recordings are untouched. Enabling this turns off 30-day cleanup.',
 ('archive','start_on_launch'):'Open ClipComb Pro directly in Archive Tools. You can return with Back to ClipComb Pro. The warning preference is separate.',
 ('app','seek_small'): 'How far the small Skip back and Skip forward commands jump, in seconds. Skipping keeps the clip playing if it was playing, and paused if it was paused.',
 ('app','seek_large'): 'How far the large skip shortcuts jump, in seconds. These shortcuts preserve the current playing or paused state.',
 ('app','speed_reset_seconds'): 'Press the same speed shortcut again within this time to add 0.25×, up to three extra steps. After this time, the next press starts at that shortcut’s whole-number speed.',
 ('app','autoplay'): 'Start playback when you open or switch to a clip. Turn off to open clips paused.',
 ('app','auto_advance'): 'After sorting a clip to another folder, advance to the next clip in the Review Queue. This includes custom extra folders & the default folders if you\'ve renamed them.\n\nClips are only moved to their selected folder on project save.',
 ('app','remember_position'): 'When you return to a clip, resume at the last position you watched. Turn off to open each clip at its beginning. Saving the project does not reset the clip you are watching.',
 ('scrubbing','show_video'): 'Show preview frames as you drag the playhead or hold Move playhead to mouse. Turn off to update the video only when you release the control.',
 ('scrubbing','play_audio'): 'Play short sound fragments from the enabled mixer tracks while scrubbing. Video follows the mouse independently; the sound may lag slightly behind it. When Show video while scrubbing is off, this toggle is locked and remembers your choice.',
 ('scrubbing','stop_playback'): 'Pause after moving the playhead with the mouse or holding Move playhead to mouse. When off, playback resumes only if it was playing before the move. Skip and frame-step commands are independent of this setting.',
 ('scrubbing','audio_grain_ms'): 'Length of each sound fragment while scrubbing, in milliseconds. Shorter fragments feel more immediate; longer ones make voices easier to recognize. Video preview does not wait for these fragments.',
 ('waveform','enabled'): 'Display an audio waveform under the timeline. Only the current clip is analyzed, in the background. Small cached peak files make later visits faster. A fixed compressed display scale keeps quiet sound visible beside louder speech; this never changes playback volume.',
 ('waveform','delete_on_close'): 'Delete generated waveform caches when the app closes normally. Recordings and exported audio are untouched. Enabling this turns off 30-day cleanup.',
 ('app','undo_limit'): 'Maximum review actions kept for Undo/Redo during this app session. Includes marked moments, sorting, audio levels and audio layout. Zero disables history. Compressed history has a 64 MB storage budget and 1,000,000-action cap; older actions expire first. Huge numbers never preallocate memory. Saved folder moves undo as pending moves, committed with Save. Settings, exported files and edits already sent to Resolve are not part of review Undo.',
 ('magnifier','width'): 'Width of the magnifier picture in pixels. Hold the left mouse button over the video to open it; release to close.',
 ('magnifier','height'): 'Height of the magnifier picture in pixels. The picture stays centered on your pointer and can extend over the other panels.',
 ('magnifier','mode'): 'Live overlay uses Windows to continuously display a magnified part of this app’s video, without repeatedly copying frames. Frame capture uses the decoded video image instead and offers precise pixel scaling. Automatic uses the live overlay when available.',
 ('magnifier','refresh_ms'): 'How often the magnifier follows the pointer. This controls movement, not the live overlay’s video refresh, which Windows handles. Smaller values follow the mouse more often and use more processing.',
 ('magnifier','capture_ms'): 'How often Frame capture mode requests a new video image during playback. This has no effect on Live overlay mode. A paused image is reused.',
 ('magnifier','smoothing'): 'Use smooth scaling in Frame capture mode. Turn off for crisp, square source pixels when inspecting detail. Live overlay uses Windows scaling.',
 ('magnifier','show_cursor'): 'Hide the pointer while holding the magnifier by default. When enabled, replace it with a small + reticle that inverts the pixels beneath it. The original pointer returns when the magnifier closes. This applies only within ClipComb Pro.',
 ('app','frame_repeat_fps'): 'While holding either bound frame-step control, pause and step at this many frames per second. Releasing the control or leaving the app stops repetition. Decoder speed can limit backward stepping on long GOP recordings.',
 ('app','frame_repeat_delay_ms'): 'Wait this many milliseconds after the initial single-frame step before a held key or frame button starts repeating. A quick tap always moves just one frame. Zero begins repeating at the configured frame-step interval.',
 ('app','timecode_frames'): 'When enabled, the timecode of the video is displayed as\nminutes:seconds:frames\nWhen disabled, the timecode is displayed as\nminutes:seconds:milliseconds\n\nVariable Frame Rate (VFR) clips show the files reported average frame rate.\nBookmarks and exports retain their positions regardless of this setting.',
 ('audio','layout_change'): 'This is the cutoff date for new and old audio track formatting. See the "Use audio layouts by date" toggle above. With Auto by date, clips dated before this date and time use Older Recordings. Clips dated at or after it use Newer Recordings. Use this if you changed your audio track layout at some point. If you’re unsure, disable "Use audio layouts by date".',
 ('tools','mpv_library'): 'Optional location of libmpv-2.dll, the playback engine. Leave blank to use the copy included with ClipComb Pro. A change takes effect after restarting the app.',
 ('tools','ffprobe'): 'Optional path to FFprobe, which reads clip duration, codec and track information. Leave blank to find the included copy automatically.',
 ('tools','ffmpeg'): 'Optional path to FFmpeg, used to generate audio waveform peaks. Leave blank to find the included copy automatically.',
 ('tools','hardware_decoding'): 'Auto uses GPU decoding when the adapter, driver and codec support it. D3D11VA works on supported AMD, Intel and NVIDIA GPUs, including integrated graphics. Software uses CPU decoding. NVDEC is specific to NVIDIA. Copy-back modes copy decoded frames back into system memory. Restart the app after changing this setting.',
 ('tools','resolve_folder'): 'Optional DaVinci Resolve installation folder, for example C:\\Program Files\\Blackmagic Design\\DaVinci Resolve. Leave blank to use the usual installation location. Direct timeline import uses Resolve Studio’s bundled Python; no MagicScript or separate Python installation is needed.',
 'profile': 'Choose how audio tracks are named. Auto by date picks the legacy or modern OBS layout from the clip’s filename date. File track names uses the recording’s metadata. Modern OBS and Legacy OBS force those layouts for this clip.',
 'track': 'Checked means this audio track is audible; unchecked mutes it. You can listen to several tracks together. Avoid enabling All tracks alongside the same separated tracks, which would double their sound. The slider adjusts this track from 0% to 150%.',
 'waveform': 'Choose which source audio track the waveform shows. Auto looks for the combined All tracks stream, or uses an enabled track if there is no combined stream. Off hides the waveform. This does not change what you hear.',
 'palette': 'Choose the original Default theme, a pastel palette, or Custom. Editing any color switches to Custom. Preview applies the colors temporarily; Save settings keeps them.',
 'shortcuts': 'Each action can have two shortcuts. Double-click a Primary or Secondary cell, then press a key, middle mouse button or side button. Left and right mouse clicks are excluded. Escape or five seconds without input cancels capture. Clear removes the selected binding. F1–F24 and modifiers are supported. Save settings keeps changes.',
 'filter': 'Limit the review queue by decision, or show Stars, Bookmarks or Marks. Stars and Bookmarks sort by color slot, Blue first; Bookmarks uses the earliest bookmark on each clip. Marks shows clips with In/Out selections in the normal clip order. All shows every category.',
 'search': 'Filter the review queue by clip file name. Clear this box to show all clips in the selected category.',
 'export': 'Double-click the Export cell to include or exclude this marked moment from the exported ranges file. This never deletes the source footage.',
}
for _key in list(HELP):
    if _key==('audio','layout_change'):
        from review_date_picker import display_cutoff
        HELP[_key]+=f"\n\nDefault: {display_cutoff(DEFAULTS['audio']['layout_change'])}."
    elif _key==('tools','hardware_decoding'):HELP[_key]+='\n\nDefault: auto (recommended).'
    elif isinstance(_key,tuple):HELP[_key]=default_help(*_key,HELP[_key])
for _key,_value in {'profile':'Auto by date','track':'Discord, game and raw mic enabled; 100% levels','waveform':'Auto (all tracks), enabled',
                     'palette':'Default palette','shortcuts':'Primary bindings as listed; all Secondary bindings blank','filter':'Unused','search':'Blank','export':'New marks included'}.items():
    HELP[_key]+=f'\n\nDefault: {_value}.'
HELP={key:wording(text) for key,text in HELP.items()}
HELP['shortcuts']='Each action has Primary and Secondary bindings. Double-click a cell to capture a key or a middle/side mouse button. Escape cancels capture; for fullscreen, Escape binds to Escape and waiting 5 seconds cancels. Clear removes the selected binding. Trim file mode and Confirm Trim may share a key: it opens Trim first, then confirms while already in Trim. Other conflicting actions need separate bindings. Delete is an automatic third binding for Delete Selected Moment / Bookmark / Missing Clip, unless Delete is assigned manually to any action. Its fallback is shown beside Secondary, such as Backspace / Delete. Save settings keeps changes.\n\nDefault: Primary bindings as listed; Secondary Backspace for deletion, plus the automatic Delete fallback. Other Secondary bindings are blank.'
HELP['scrubbing','play_audio']+='\n\nWARNING: This setting CAN slow down scrubbing quite a bit depending on your system. On most systems, the performance cost is worth the extra functionality. But it is still worth testing for yourself.'


def tooltip_position(pointer,bounds,size):
    x,y=pointer;left,top,right,bottom=bounds;width,height=size
    x=x+16 if x<(left+right)/2 else x-width-16
    y=y+22 if y<(top+bottom)/2 else y-height-14
    return max(left+6,min(x,right-width-6)),max(top+6,min(y,bottom-height-6))


class Tooltip:
    def __init__(self,widget,text,position=None,hold=None):
        previous=getattr(widget,'review_tooltip',None)
        if previous:previous.hide()
        widget.review_tooltip=self
        self.widget,self.text,self.window,self.timer=widget,(lambda:wording(text())) if callable(text) else wording(text),None,None
        self.custom_position,self.hold=position,hold
        widget.bind('<Enter>',self.enter,add='+')
        widget.bind('<Motion>',self.motion,add='+')
        widget.bind('<Leave>',self.leave,add='+')
        widget.bind('<ButtonPress>',self.hide,add='+')
        widget.bind('<FocusOut>',self.hide,add='+')
        widget.bind('<Destroy>',self.hide,add='+')
        widget.bind('<Escape>',self.hide,add='+')
    def enter(self,event=None):
        if not self.timer and not self.window:self.timer=self.widget.after(350,self.show)
    def leave(self,event=None):
        if not self.hold or not self.hold():self.hide()
    def motion(self,event=None):
        if self.window:self.refresh();self.position()
    def refresh(self):
        if self.window and callable(self.text):
            text=self.text()
            if text!=self.shown_text:self.tip_label.configure(text=text);self.shown_text=text
    def position(self):
        from review_windows import pointer,client_rect,place_window
        x,y=pointer()
        self.window.update_idletasks()
        width,height=self.window.winfo_reqwidth(),self.window.winfo_reqheight()
        owner=self.widget.winfo_toplevel()
        left,top,right,bottom=client_rect(owner)
        pinned=self.custom_position((left,top,right,bottom),(width,height)) if self.custom_position else None
        x,y=pinned if pinned is not None else tooltip_position((x,y),(left,top,right,bottom),(width,height))
        place_window(self.window,x,y,width,height)
    def show(self):
        self.timer=None
        if not self.hovered():return
        root=self.widget._root()
        previous=getattr(root,'active_review_tooltip',None)
        if previous and previous is not self:previous.hide()
        root.active_review_tooltip=self
        text=self.text() if callable(self.text) else self.text
        if not text:return
        self.window=tk.Toplevel(self.widget,takefocus=False)
        self.window.withdraw();self.window.overrideredirect(True);self.window.attributes('-topmost',True)
        colors=getattr(self.widget._root(),'review_palette',{})
        self.window.configure(bg=colors.get('border','#31394b'))
        from review_windows import window_dpi,client_rect
        from review_ui_scale import monitor_scale
        from review_windows import monitor_rect
        self.window.review_manual_scale=True
        owner=self.widget.winfo_toplevel();scale=monitor_scale(monitor_rect(owner));bounds=client_rect(owner)
        wrap=min(round(390*scale),max(round(150*scale),bounds[2]-bounds[0]-round(42*scale)))
        self.shown_text=text
        self.tip_label=tk.Label(self.window,text=text,wraplength=wrap,justify='left',padx=round(12*scale),pady=round(9*scale),
                 font=('Segoe UI',-round(10*96/72*scale)),background=colors.get('input','#202533'),
                 foreground=colors.get('text','#eef1f8'));self.tip_label.pack(padx=1,pady=1)
        self.window.deiconify();self.position();self.watch_timer=self.widget.after(50,self.follow)
    def hovered(self):
        try:
            if not self.widget.winfo_viewable():return False
            if self.hold and self.hold():return True
            x,y=self.widget.winfo_pointerxy();tkapp=self.widget.tk
            if str(tkapp.call('winfo','containing','-displayof',self.widget._w,x,y))!=self.widget._w:return False
            grab=str(tkapp.call('grab','current',self.widget._w))
            return not grab or str(tkapp.call('winfo','toplevel',grab))==str(self.widget.winfo_toplevel())
        except tk.TclError:return False
    def follow(self):
        self.watch_timer=None
        if not self.window or not self.hovered():self.hide();return
        self.refresh();self.position();self.watch_timer=self.widget.after(50,self.follow)
    def hide(self,event=None):
        if getattr(self,'watch_timer',None):
            try:self.widget.after_cancel(self.watch_timer)
            except tk.TclError:pass
            self.watch_timer=None
        if self.timer:
            try:self.widget.after_cancel(self.timer)
            except tk.TclError:pass
            self.timer=None
        if self.window:
            window,self.window=self.window,None
            try:window.destroy()
            except tk.TclError:pass


def badge(parent,text,panel=False):
    icon=ttk.Label(parent,text='?',style='PanelHelp.TLabel' if panel else 'Help.TLabel',
                   cursor='question_arrow',takefocus=True,width=2,anchor='center')
    icon.tooltip=Tooltip(icon,text)
    icon.review_help=True;icon.review_help_text=text
    return icon


def label(parent,text,help_text,**kwargs):
    row=ttk.Frame(parent)
    row.review_help_label=text
    ttk.Label(row,text=text,**kwargs).pack(side='left')
    badge(row,help_text).pack(side='left',padx=(5,0))
    return row


def check(parent,text,variable,help_text,panel=False,command=None):
    row=ttk.Frame(parent,style='Panel.TFrame' if panel else 'TFrame')
    row.review_help_label=text
    row.control=ttk.Checkbutton(row,text=text,variable=variable,command=command,style='Panel.TCheckbutton' if panel else 'TCheckbutton')
    row.control.pack(side='left')
    badge(row,help_text,panel).pack(side='left',padx=(4,0))
    return row

HELP["trimming","original_name"]='When trimming a clip or using "Compare overlaps" to merge overlapping clips, the resulting file name will end with _TRIMMED or _MERGED, to easily note the original clips have been altered. By enabling this setting, the new trimmed or merged version will NOT have the _TRIMMED or _MERGED added at the end, seamlessly replacing the original version entirely. Note this can interfere with your existing video editor timeline if the original has been used in a video project. (Regardless of this setting, the original version is moved to the Deleted folder on trim or merge. Though the Deleted folder in your ClipComb Pro project\'s folder is never automatically emptied, you must delete the contents yourself, just to be safe.)'
