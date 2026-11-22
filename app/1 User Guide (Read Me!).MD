# Reviewing and exporting

## Tutorial and playback controls

Tutorial is available at the top right of the main window, and also in Settings → About.

[Tutorial](https://youtu.be/nMiXShHDSD8)

Drag the handle above Play to resize the buttons. There are a few handles in the
main page which you can use to resize different parts of the app.

The layout uses a 1440p reference, with 75% sizing at 1080p and 150% at 4K.

Right click and drag the empty space above the audio waveform to create **Marked Moments**.
Double right click a marked moment to delete it (or select the moment and press Delete / Backspace / Tab).
Hold right click to move them around, or right click the ends to adjust their length and position.
(You can enable left clicking marked moments in the settings, disabled by default
so you don't accidentally move them while moving the playhead.)
Clicking down the scroll wheel brings the playhead to the mouse.
Alt+X clears all current marked moments, Undo (CTRL+Z) restores them.

Sorting keybinds move selected clips into different folders. By default they are:
W Used, S Unused, A Deleted and D Kept. The footer at the bottom left of the main window
shows your actual current bindings and project folder names (if they are customized).
R selects Review.
C selects Compare Overlaps and T opens Trim File; T again confirms the trim plan.
F adds/edits a bookmark and G adds/edits a clip Star.
Q/E to move to the previous/next clip.
You can change the folder names of your project in Settings → Other.

**Click the logo to make it move!**

## Projects and saving

The Review Queue is a list by default, but can be switched to a grid view.
Thumbnails reuse Windows' existing thumbnail cache when available; otherwise a background
worker extracts a small video frame to the `Generated Thumbnails` folder beside the .exe.
Ctrl+Scroll over the grid view to adjust the thumbnail size.
Generated thumbnails are deleted automatically after 30 days.
(The files are only able to be automatically deleted if the app is opened once after that time.)
"Delete thumbnails after 30 days" defaults on. If you turn it off, don't forget to empty the `Generated Thumbnails`
folder from time to time so it doesn't get too big. Same goes for the `Generated Waveforms` folder.

A large asterisk marks a clip with one or more marked In/Out moments. A missing clip stays in its
previous category with an X, keeping its last saved work. Hover your mouse over the X for help.
Select that clip and press Delete or Backspace to forget its queue record.
This never deletes a media file.

A project references a folder containing `Unused`, `Used`, `Kept` and `Deleted`.
Its review data is a readable `<name> - <ID>.clipcomb.json` document in
the `Projects` folder beside the EXE. Videos stay in their existing folders. When choosing
a video folder, enter a project name. Projects take on the folder's name by default.

To share a project, first save the project, then copy its `.clipcomb.json`
file from the `Projects` folder beside the exe. Be sure to include the clip files too!

`Deleted` is a folder of clips for you to discard later; the app never empties it.
Once you have moved a clip to a different folder, the file is not actually moved until you save the project.
Undo does not undo a Resolve import, exported files, settings, or external file operations.

## Audio and viewing

Hold left click over the playback window to enable the zoom window.
The scroll wheel increases the zoom level, CTRL+Scroll the size.
Right click to toggle the crosshair in the zoom window.

Dual Monitor Mode detaches the video player into a separate
window. You can move it to another display. Press Escappe to toggle fullscreen.
The main player area becomes extra review queues. Use −/+ to add or remove these queue windows.

Playback controls adapt to the monitor's resolution and display scaling, using
1440p as the baseline. Drag the small handle above Play upward to enlarge both
playback bars or downward to shrink them. Double-click resets the manual size.

Selected bookmarks have white borders. Selected marked moments are similarly highlighted.
Select a bookmark or In/Out mark and press Delete/Backspace to remove it.
Those bindings can be changed.

You can change keybinds in Settings → Shortcuts. Scroll click and side buttons are bindable.
Press Escape wait or five seconds to cancel rebinding, keeping the old one.
Clear removes the selected binding. Be sure to save the settings!

You can change the theme in Settings → Theme. You can choose between light and dark mode.
You can also create custom themes and save them as files you can share with others.
(If you make a custom theme, don't forget the light mode is ALSO saved. So be sure to customize it too.)

Settings → Audio includes **Use audio layouts by date**, off by default. Enable it to dynamically change
the audio track layout of your clips by date. Admittedly this feature is a bit complicated and hard to explain.
Basically if you've ever changed your audio track layout at some point (like if your microphone track used to
be Track 1 and you later made it Track 2), this feature will account for that by allowing you to label
and control the volume of your older and newer clips independantly, rather than just making 1 track layout
in ClipComb Pro which is only accurate to some of your recordings.

Timecode defaults to `Minutes:Sseconds.Frames` with the source frame count, and Video Framerate shows the clip rate.
In Settings → Playback you can switch it to milliseconds. `Minutes:Seconds:Miliseconds`

Waveform peaks are generated for the current clip and cached in the `Generated Waveforms` folder beside the app.
Delete waveforms after 30 days defaults on. If you turn it off, don't forget to empty the `Generated Waveforms`
folder from time to time so it doesn't get too big. Same goes for the `Generated Thumbnails` folder.

## Exporting

The export screen lists every managed folder, including renamed defaults and extra folders.
Enabled folders determine which enabled marked moments are exported to your editing software.
Missing clips are always skipped. An empty folder selection exports nothing.
(Changing these checkboxes does not confirm pending review edits or move clip files.)

**For DaVinci Resolve Studio**, ClipComb Pro can hook into Resolve to import clips
directly on the currently open timeline. First you will need to enable this hooking behavior.
Open DaVinci Resolve Studio → DaVinci Resolve (at the top left of of the main window) → Preferences → System → General → External scripting using → Local
**This requires DaVinci Resolve Studio 21.1 or newer**
It is NOT recommended to import your clips directly into your main working timeline.
Instead, BE SURE TO CREATE AN EXTRA TIMELINE WITH THE CORRECT FRAMERATE AND
RESOLUTION TO IMPORT CLIPS INTO!
**DO NOT TOUCH DAVINCI RESOLVE WHILE CLIPS ARE IMPORTING OR THEY MAY NOT IMPORT CORRECTLY**

**For the Other Editors**, ClipComb Pro creates a timeline file which you import into
your editing software, so you can copy the clips from that timeline into your main timeline easily.
ClipComb Pro always creates this timeline at the highest resolution / framerate clip.
So for example if you sorted and imported one 1080p 120fps clip, and one 4K 60fps clip,
the timeline file it creates would be 4K 120fps to account for the highest possible combination.
- **DaVinci Resolve (free version):** choose **OTIO · Resolve (clip markers)**, then File → Import → Timeline. Match the import frame rate, resolution and color settings to the choices displayed by ClipComb Pro. Resolve can take settings from the project. This carries clip bookmarks, linked AV, independent original audio streams and Inspector levels. Copy selections into your main edit. Resolve Studio 21.2 tests verified six stereo streams from one original MP4 and full source handles. The free edition was not installed. This uses its ordinary timeline import without a Studio scripting connection. Your Resolve edition must support the original codecs.
- **Kdenlive:** choose **Kdenlive project · Original media**, then File → Open the `.kdenlive` file. Each original audio stream has its own track, grouped with its video. Range bookmarks and levels use Kdenlive's native format. Copy the group into another project with matching frame rate and enough audio tracks. Kdenlive 26.08.3 was tested opening, saving, extending all seven components together, and pasting into a separate project with the original file and six stream selections intact. Native export avoids the OTIO importer's source-offset and stream-selection limitations. Use Fit Zoom to Project if needed.
- **Adobe Premiere Pro:** choose legacy XML, then File → Import. Original channels use linked channel groups with stereo placement and editable levels. Source and timeline frame rates can differ; legacy XML accepts integer/standard NTSC rates.
- **Final Cut Pro:** choose FCPXML, then File → Import → XML. Each select is a composite AV clip whose video and audio refer to the full original. PQ or HLG footage sets an HDR project color space and retains source color tags. Check color management when mixing SDR, PQ and HLG. Cmd+V inserts copied clips. Option+V pastes them as connected clips. Keeping projects in the same library avoids the separate media-copy choices involved in transfers between libraries.



Enabled marked moments are exported in clip order, then each clip's Marked moments order.
Turn off automatic chronological sorting to drag moments into a custom order.

Bookmarks export **INSIDE** individual clips by default. Enable **Bookmarks on timeline instead of inside clips**
to put them on the timeline above their respective clips.
Direct Studio import preserves all 16 of Resolve's bookmark colors.
Resolve OTIO uses its supported nine-color subset, with unsupported shades mapped to nearby supported colors.
Standard Final Cut bookmarks are blue. Its project-level bookmarks are represented on a primary-storyline gap with the video connected above it.

**Move All Clips With Marks To…** is at the bottom right of the main window.
This allows you to move all clips which have at least 1 marked moment into
a specific folder. This is very useful if you've marked several clips but forgot
to move them to the Used folder. It is always recommended to move all marked clips
to the Used folder before importing them into your video editor.

If you used the DaVinci Resolve Studio to export your clips into resolve,
ClipComb Pro can see if you've moved clips to a different managed folder after
importing them into resolve, and attempt to re-link them on your timeline.

## Portable storage and compatibility

All global settings live in `ClipComb Pro.ini` beside the app.
Projects and generated caches also stay in the portable app folder.
Put the app in a writable folder. You DO NOT need to move your clips to
the ClipComb Pro folder.

The app uses libmpv's hardware/software decode fallback and color metadata handling.
Frame rate, resolution and HDR compatibility depend on the decoder,
GPU, Windows/display configuration and the destination editor.
Actual HDR display accuracy was not physically calibrated.
Multichannel audio streams are reviewed in stereo; export retains separate streams.
Unsupported, damaged or proprietary files may not work.

## Bookmarks, overlaps and lossless file trimming

Press F or the diamond button to add a bookmark at the playhead.
Press again to edit its name, description and color, or delete it.
Bookmarks sit above marked moments. Hover for details; click to seek,
double-click to edit, or drag to move.
Directly clicking a bookmark always moves the playhead to it.
Alt-drag extends a bookmark into a range. Both point and range bookmarks carry into export.
Final Cut does not support bookmark ranges, so the compatibility export setting instead
exports ranged bookmarks as 2 bookmarks, one for each end.
The magnet button (N by default) controls playhead snapping on the timeline.
Settings → Theme lets you change the bookmark colors, though they will still
appear as the nearest supported bookmark color in your editing software.

Choose Scan overlaps to scan for clips in your project which share overlapping footage.
Scanning runs in the background, slowed if you continue working in ClipComb Pro.
Cancel Scan stops the current scan in progress.
Clicking Scan Overlaps again will resume the scan.

Brackets and matching group numbers identify linked clips in the Review Queue.
Select a linked clip and choose Compare Overlaps to review the linked overlapping clips.
This supports up to 4 clips playing at once, however the app can handle up to 20
overlapping clips in one link.
From here you can choose to delete any of these overlapping clips, or MERGE them
into one larger file containing the footage of all clips,
seamlessly aligned without losing any quality or audio. The resulting
file has _MERGED added to the end of the file name by default, this can be disabled.
These new merged clips are placed in the Unused folder, ready to review.
The original un-merged overlaps get moved to Deleted.
**It is recommended to scan and manage overlaps before reviewing your**
**clips in ClipComb Pro. Marked moments, stars, and bookmarks are not carried**
**from any overlapping clips into their resulting merge.**
After you've handled all your overlapping clips, be sure to delete
any of the original overlaps from the Deleted folder, as ClipComb Pro does not delete them for you.
(after you've double checked the merged copy isn't broken, and that the originals were not included
in any video editor project first by mistake.)

The Archive Tools button in the main window switches ClipComb Pro to an app dedicated
solely to finding and managing overlapping clips. This was actually what ClipComb Pro
was initially designed to do, before I realized it could be SO MUCH more.
This legacy setting is still present in case you don't even need the rest
of the features of ClipComb Pro.

Select Trim File to switch to the file trimming view. This allows you to select portions
of clips and trim the rest. This only allows selecting large chunks of the video, however
these chunks are on keyframes. So the resulting trim is able to remove unwanted footage
from a clip, all without losing ANY visual quality because it's not re-encoding.
After trimming, the original file is moved to the Deleted folder, and the new trimmed
copy is created in the Unused folder, with _TRIMMED added to the new file name.
**It is recommended to do any trimming before adding bookmarks or marked moments.**
**Marked moments, stars, and bookmarks are not carried**
**from the original clips into their resulting trimmed copy.**
After you've handled trimming clips you want to trim, be sure to delete
any of the original clips from the Deleted folder, as ClipComb Pro does not delete them for you.
(after you've double checked the trimmed copy isn't broken, and that the original was not included
in any video editor project first by mistake.)
