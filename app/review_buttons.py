# SPDX-License-Identifier: GPL-3.0-or-later
"""Consistent button captions and brief explanations of common actions."""
def title(text):
    if text.startswith('Move To '):return text
    return ' '.join(word[:1].upper()+word[1:] for word in text.split(' '))

ARCHIVE='Archive Tools is a separate workspace for scanning an archive, reviewing overlap reports, and making verified copies or merges. It keeps its own working folder and history. Read the ? explanation before changing files.'
STOP_SCAN='Stopping the scan keeps your progress. You can resume scanning later.\nOverlap scanning is slowed while using the Review features so you can continue working, however this still requires a decent chunk of CPU usage and may make the app feel less responsive. Waveform generation is particularly effected by scanning.'
HELP={
 'open working folder':'Open the folder containing archive scan progress, reports and generated copies.',
 'save project':'Save the project and move clips to the folders selected by your sorting decisions.',
 'projects':'Open, create, rename or manage ClipComb Pro projects.',
 'settings':'Change shortcuts, playback, audio, themes and project folders.',
 'review':'Review the selected clip and mark moments or bookmarks for your video editor.',
 'compare overlaps':'Open the selected overlap group with aligned playback and a shared timeline.',
 'bookmarks':'Add, edit or navigate bookmarks on the current clip.',
 'mute all':'Disable every audio mixer track. The waveform selection is independent of this mix.',
 'open file in video player':'Open the current source clip in your system’s default video player.',
 'open file location':'Open File Explorer with the current clip selected.',
 'undo trim':'Restore the complete original and move this trim’s copies to the recoverable Deleted-role folder.',
 'edit times':'Enter precise In and Out times for the selected moment.',
 'remove':'Remove the selected item from this list.',
 'rescan project folders':'Refresh the clip list after files were added, moved or renamed outside ClipComb Pro.',
 'save settings':'Keep the staged settings changes. Project folder changes apply only to the open project.',
 'reset all to default':'Load factory app settings. Save Settings keeps them; Cancel discards the staged changes.',
 'clear':'Clear the selected shortcut slot. Save Settings keeps the change.',
 'refresh':'Refresh the available choices from the system.',
 'use in video':'Move this clip to the Used folder on Save Project. Marked In/Out moments determine what is exported.',
 'keep personally':'Move this clip to Kept on Save Project. The clip remains available for review.',
 'delete pile':'Move this clip to the recoverable Deleted folder on Save Project. No file is permanently deleted.',
 'back to unused':'Move this clip to Unused on Save Project, ready to review again.',
 'use entire clip':'Replace the In/Out selections with one selection covering the whole clip. Undo restores the previous selections.',
 'scan overlaps':'Find identical overlapping footage in the project’s managed folders, excluding the Deleted folder. Stop Scan keeps completed progress so you can resume later.',
 'scan archive':'Folder containing your clips with possible overlaps',
 'stop scan':STOP_SCAN,
 'export to editing software':'Export marked In/Out moments and bookmarks to the selected editing software. Pending sorting decisions are saved first.',
 'dual monitor mode':'Move the video viewer to a separate window and show additional review queues. Useful with a second monitor.',
 'trim file':'Plan which parts of the source file to keep, using verified lossless cut points. Editor In/Out selections stay separate.',
 'trim video':'Create and verify the trimmed copy using the current keep plan, then review the replacement confirmation.',
 'separate':'Enable the separate audio tracks and turn off the combined All Tracks track. This avoids hearing the same audio twice. Track choices follow the selected audio layout.',
 'archive tools':ARCHIVE,
 'regenerate waveform':'Discard only this clip’s selected waveform cache and generate it again. Use this to retry a stalled or incomplete waveform. Your clip is unchanged.',
 'reset shortcut to default':'Restore the selected shortcut slot to its factory binding. Save Settings keeps the change.',
}


def explanation(text):
    label=text.rstrip('… .').casefold()
    return HELP.get(label)


def decorate(event):
    from tkinter import ttk,Button
    from review_help import Tooltip
    button=event.widget
    if not isinstance(button,(ttk.Button,Button)):return
    text=button.cget('text')
    if text:button.configure(text=title(str(text)))
    if not getattr(button,'review_tooltip',None) and (help_text:=explanation(str(text))):
        button.review_tooltip=Tooltip(button,help_text)
