# Changelog

## 1.0.0 — review input and export layout

- Limit project overlap scans to managed folders. Keep Archive Tools scanning the selected archive.
- Queue Play or Pause during scrubbing and apply it when the playhead is released.
- Add speed buttons with 1×, Shift+click 0.25×, and Ctrl+click 0.1× steps.
- Keep the current interface scale while moving a window between monitors, then apply the destination scale after release.
- Pin bookmark tooltips above the timeline while hovering or dragging.
- Keep short Review Queue grids at the top when scrolled.
- Handle middle mouse button presses safely while scrubbing or recording a shortcut.
- Size the export dialog to show its settings and folder choices on open. Keep scrolling available on smaller displays.

## 0.34.0 — tutorial and review settings

- Show the ClipComb Pro tutorial in the embedded player and the Watch On YouTube button.
- Give Review Queue badges room to extend left in List view and restore them immediately when switching back from Grid. Reserve the asterisk for marked moments.
- Pick the audio layout cutoff with a calendar and time controls. Preserve existing cutoffs.
- Choose hardware decoding from a dropdown. Software is CPU decoding. Confirm any change to a manual mode. Auto remains the default and supports Windows GPU decoding across vendors.

## 0.33.0 — lower idle work and smoother resizing

- Pace app updates by window state and playback activity. A minimized window checks once per second. A paused window in the background checks about two or three times per second. Playback, seeks and scrubbing keep the fast update rate while visible.
- Skip recurring logo and thumbnail checks when they have no work. Refresh dual-monitor window decoration when it changes, and stop repainting hidden spinners.
- Reuse the waveform image during resize and redraw the exact waveform once at the final size. Keep transport controls centered with fewer layout calls and refresh stale Windows pixels during drag.

## 0.32.0 — Studio bookmark updates and export settings

- Update ClipComb bookmarks on matching unchanged moments in Resolve Studio when Skip moments already on this timeline is enabled. Keep original timeline clips, linked audio and editor-created bookmarks in place.
- Show old and new paths when an exported original has moved. Repair its Resolve media pool link, continue without relinking, or cancel the Studio import.
- Remember shared export settings across projects and keep folder selections within each project. Show the export warning switch only on the Studio tab and its warning dialog.
- Auto uses the fastest included clip and the largest included raster. Show the picked settings in the export dialog. Final Cut XML carries HDR project and source color settings. Resolve may use its project settings for OTIO imports.
- Open Settings → Other without highlighting the first folder name.

## 0.31.0 — Review Queue toggle and folder-name selection

- Show the destination view on the Review Queue toggle: Grid while viewing a list, and List while viewing a grid. Keep the icon correct after switching views or changing themes, including the dual-monitor queue.
- Clear inactive selections in project folder-name fields when leaving a field or returning to Other settings. Normal selection and editing remain available in the active field.

## 0.30.0 — fixed bulk dialog and Studio export confirmation

- Prevent user resizing of Move All Clips With Marks To… while fitting the window automatically to its contents.
- Arrange folder checkboxes in four evenly spaced columns, adding a second row when needed in both export and bulk sorting. Put Cancel on the bottom destination-button row.
- Before direct Resolve Studio imports, show WARNING with: DO NOT TOUCH DaVinci Resolve while ClipComb Pro is importing your clips. This can break your project! Continue proceeds; Cancel, Escape and closing the warning do not save the project or begin an import.
- Add Don't show export warning at the warning's bottom left and below Folders To Export in each export tab. The shared app preference defaults off, persists immediately, and can be unchecked to restore the warning. Timeline-file exports and connection refreshes do not show this warning.

## 0.29.0 — project export folders and bulk marked-clip sorting

- Place folder checkboxes horizontally below the text and options inside each export tab, and use a horizontal source-folder row in the bulk-move confirmation.
- Add one export checkbox per managed folder, with Used first and initially selected alone. Remember the choice in the project, including an explicitly empty selection, rather than changing global defaults. Renamed folders keep their role's selection; removed and recreated extra folders do not inherit an old selection.
- Apply folder choices to timeline files, direct Resolve imports and single-clip placement. Deleted can be exported when explicitly checked; missing clips remain excluded. Remembering export choices does not commit pending marks or sorting decisions.
- Add Move All Clips With Marks To… beside the file-opening buttons. The confirmation lists source folders, Cancel, and every managed destination. Stage sorting decisions for all marked clips in the checked sources; keep bookmarks alone and missing clips out. One Undo/Redo reverses/reapplies the entire operation, including pending return moves after a save.
- Remove the MagicScript reference and display: DO NOT TOUCH DaVinci Resolve until the import is finished! No interaction-blocking feature is added.

## 0.28.0 — extra folder removal and moved clip recovery

- Reconnect a uniquely matching clip moved between project folders outside the app, preserving its original ID, star, bookmarks, marked moments, audio settings and saved position.
- Repair the pristine duplicate rows left by earlier rescans. Keep separately reviewed records and ambiguous copies rather than guessing or discarding annotations.
- Allow removal of empty or missing extra folders despite stale missing clip records or empty nested directories. Retain missing clip annotations, and continue blocking actual contents or pending moves into the folder. Never delete a folder or clip during this change.
- Refresh file locations before rescan saves, and apply folder recovery to the saved checkpoint separately so Save Settings does not commit pending review edits.

## 0.27.0 — original media exports and held bookmark details

- Reference full original media for both video and audio in file exports. Remove audio extraction and the requirement for a clip-review-audio folder. Original source handles remain available beyond marked moments.
- Map Resolve OTIO audio directly to each original embedded stream, preserving linked selections, bookmarks and review levels. Recommend this route for Resolve instead of its limited multistream XML importer.
- Add native Kdenlive project export with explicit embedded stream selection, original source offsets, grouped video/audio, editable levels and native range bookmarks. Replace the Kdenlive OTIO choice, whose importer loses stream selections and later source offsets.
- Keep Final Cut components inside a composite AV clip with full original source ranges. Preserve Premiere XML source frame clocks independently from the timeline rate. These two editors still need application-level validation on their respective platforms.
- Pin held bookmark details above the timeline, update times throughout dragging, keep details visible outside the bookmark/timeline, and hide them on release or cancellation.

## 0.26.0 — dropdowns and startup layout

- Fix dropdown errors by excluding Tcl-owned combobox popup paths from Python widget scaling. Check opening and selecting items in main-window and Settings dropdowns.
- Restore splitter positions after the main window maps at its saved normal/maximized size. Recover a nearly collapsed saved timeline and show only one zero-time label when no clip is open.
- Keep the faster live resize path, then request one asynchronous cleanup paint after resizing settles. Include the Star/snapping controls when checking transport text space so narrower panels do not overlap the frame-rate text.

## 0.25.0 — smoother layout and visible date-based audio

- Keep the main window hidden until its initial size, theme and layout are ready, avoiding the small white startup window.
- Show only this version's changes in About. Use a bounded native text scroller, and coalesce unchanged scroll-page geometry. Preserve the full history in CHANGELOG.md.
- Reserve the Review Queue scrollbar before the list/grid and double its width. Keep it visible when narrowing primary or secondary queues.
- Size sorting buttons to their text. Keep the four main folders on the first row and extra folders on the second, with file-opening actions on the right when space allows.
- Reuse unchanged button layouts, coalesce transport resizing, retain live image references while replacing icons and avoid scanning every widget whenever an existing control remaps. Remove redundant full-client Windows resize repaints while keeping normal Tk exposure handling and native video rendering.
- Expose Use audio layouts by date in Audio settings, with an explanation, change date and newer/older track layouts. Keep it off by default; preserve saved settings, per-clip choices and mixes. Apply changes without restarting.

## 0.24.0 — display scaling, bookmarks and faster Star edits

- Center About text, use WaveSmash's supplied credit/disclosure wording and add the scrollable changelog below Tutorial.
- Add Alt+X to clear all marked moments on the current clip, with Undo; in Trim File it clears the keep plan. Keep Bookmarks and Stars.
- Update bookmark tooltip timecodes while dragging and snap either edge of a moved bookmark range to the playhead without changing its duration.
- Apply the video background color to the actual video renderer and overlap players. Verify 9:16 playback and portrait detached-player framing.
- Scale the desktop layout from its 1440p reference: 75% at 1080p and 150% at 4K. Resize fonts, controls, theme images, queue icons, logos and timeline lanes, and preserve readable transport text when manually shrinking buttons. Reserve Audio Mixer controls before the scrollable track list on shorter windows.
- Minimize the detached player with the main window, keep the main window open when only the player is minimized, and restore both when either is reopened or deliberately focused.
- Apply tutorial title colors when its native window maps. Hide the browser host and child before detaching it on close, preventing the top-left thumbnail flash.
- Use #13ff0d as the default meter color in every built-in dark/light palette. Show native Star color names in its popup; omit customized/Final Cut names.
- Remove the full queue rebuild on Star save. A 1,000-row disposable benchmark fell from 1.6 seconds to about 0.04–0.08 seconds. Keep filtered membership/sorting updates.
- Replace repeated synchronous meter reads with bounded asynchronous metadata requests. Reattach filters only when their audio graph changes; optional meter commands cannot become playback errors. Scrub/resume checks use small fixtures, without scanning or editing personal recordings.
- Reuse an already-issued preview seek on scrub release instead of decoding the same point again. Increase MPEG-TS preroll during paused preview when necessary. Preserve final-target accuracy, stop/resume policy and all-tracks-muted behavior.

## 0.23.0 — readable controls, live metering and tutorial

- Keep playback speed, timecode and frame rate text at their normal monitor size when shrinking transport buttons. Continue adapting controls to narrow layouts.
- Fit Playback settings horizontally, update project folder shortcut labels as they are typed, and clarify the sorting/advance tooltip.
- Return scan progress to the toolbar immediately left of Archive Tools, keeping the right-hand controls fixed as filenames change.
- Highlight the Star control for starred clips with a black icon. Use native palette color names, omit customized color names and Final Cut color references. Simplify disabled magnet cap outlines and update Grey Mann light colors.
- Add a compact live volume meter beside Audio Mixer options, a Show volume meter toggle, M shortcut and theme color. Read existing player filter metadata without a second decoder or temporary audio files; remove the filter when disabled.
- Add Tutorial buttons in the main window, Settings footer and About page. Show a startup reminder until Don't show this again is checked. Embed the official YouTube player through an isolated WebView2 host, with a system-browser fallback. Include host source, reproducible build tool and Microsoft SDK notices.
- Correct the derived light logo intro sequence and cancel obsolete animation callbacks; keep original artwork unchanged. Credit WaveSmash for the original logo and animation and permit forks to keep the logo under the existing GPL grant.

## 0.22.0 — overlap seeking, scan feedback and project folders

- Fix precise seeking in MPEG-TS files with long keyframe gaps, increasing preroll only when a seek overshoots. Use asynchronous comparison seeks; stay paused during retries and respond immediately to pause requests. Start settled panes together and gently correct small drift. Skip redundant speed writes. Check staggered clips and master handoff with small native fixtures.
- Rebuild overlap labels after filtering and sorting. Show when only one group member is visible and list hidden partners in the queue tooltip. Resolve saved overlap paths after project folder renames.
- Show filename-first progress, clip counts, priority, spinner, progress bar and Stop Scan in Review and Archive Tools. Keep completed cache progress. Update archive help, Working Folder terminology, common button explanations and capitalization.
- Add Settings → Other for organization/storage and media tool paths. Store project-specific names for the four main sorting folders and up to four extra folders. Update sorting buttons, shortcuts, queue filters, secondary queues and footer. Keep the recoverable Deleted role excluded from export.
- Rename folders with a recoverable staged transaction; never merge or overwrite existing folders. Update clip paths and trim receipts, preserve pending review work and the saved review checkpoint, and block folder changes during file operations. Support ordinary existing folders as extra categories.
- Add Shift+2 for 0.1x speed increases. Hold the decrease binding for one second to select 0.1x; keep ordinary tap behavior. Put both above the numbered speed shortcuts. Add Reset Shortcut To Default for the selected slot.
- Show the extension cursor over bookmarks while Alt is held. Add Regenerate Waveform beside the waveform selector to retry only the current clip/track while retaining a previous cache until successful replacement.
- Add Grey Mann with the exact supplied dark and light palettes. Keep Use Entire Clip as the full-clip selection action alongside the renamed Move To folder buttons.

## 0.21.0 — sorting guide, bookmark details and stable waveform scale

- Set sorting defaults to W Used, S Unused, A Deleted and D Kept. Keep saved custom bindings. Show the four actions and their actual configured primary/secondary keys at the bottom of the window; refresh on settings save.
- Show bookmark name before its timestamp/range. Inset a range's colored bar to the inner arrow faces symmetrically. Draw the playhead above the bar but below bookmark handles and point icons; avoid an inverted bar on very short spans.
- Add opt-in keyboard media Play/Pause support in Playback settings, off by default. Handle one toggle per press, including in the background, with a dialog/busy guard. Remove the native listener completely on disabling or closing; never retain unrelated keyboard input.
- Replace whole-clip peak normalization with a fixed soft logarithmic display scale. Late loud speech no longer shrinks previously drawn gameplay below a pixel. Silence stays silent and louder sound stays larger. Source audio, playback gain and all-stream peak generation are unchanged; existing caches need no regeneration or rewrite.
- Verify configured/footer controls, repeated media-listener enable/disable, held-key suppression, actual synthetic-media playback, dialog guards, tooltip ordering, range bounds/layering and progressive waveform stability. Use disposable fixtures and narrowly scoped read-only measurements of the one reported recording.

## 0.20.0 — theme image lifetime, scalable queue badges and Resolve track reuse

- Keep strong image references on displayed badge widgets, grid items and view buttons. Repaint visible icons during a theme change and restore them on Cancel without waiting for scrolling. Bound the shared colored-icon cache and release hidden widget images.
- Cache queue row IDs and clip lookups when the queue changes. Badge redraws process only visible rows, without enumerating the full Treeview or rebuilding a project-sized lookup each time.
- Verify 1,000 synthetic rows with 5,000 logical icons using 90 visible badge widgets: about 1.5 ms median badge redraw at both 100 and 1,000 rows on the test machine, with stable image counts during repeated theme changes. No synthetic recordings are scanned or decoded.
- Reuse compatible unlocked/enabled Resolve tracks, including an existing one-video/six-audio layout. Extend a partial compatible audio block only by its missing tracks. Preserve existing names and channel layouts.
- Snapshot pre-import clip IDs on reused tracks so rollback removes only newly imported items, including partial API results. Native Resolve tests confirm repeated import adds no tracks, a one-audio layout gains only five audio tracks, and an injected failure preserves previous clips.
- Explain the dedicated selects-timeline workflow in How To and Studio export help. Report whether tracks were reused or added. Keep the full narrated tutorial deferred for the user's script.

## 0.19.0 — controls, contextual shortcuts and bookmark spans

- Adopt the user's captured 0.18 keyboard layout as the defaults: F bookmark, G Star, W/S/D/A sorting, Q/E clip navigation, Tab deletion, and Alt+S scrub audio. Preserve existing custom configs.
- Default T to both Trim file mode and Confirm Trim. Allow that meaningful shared binding in either slot; dispatch only the page-appropriate action per press. Re-selecting Review, Compare or Trim preserves the current page.
- Show an automatic Delete fallback beside the secondary deletion binding (Backspace / Delete by default). Disable and hide it when Delete is explicitly assigned to any action; retain its custom action instead.
- Keep live shortcut hints, default help and the settings editor consistent with actual bindings.
- Synchronize queue icon backgrounds with the actual selected row before clip loading begins, updating only visible labels whose color changed.
- Move the bookmark lane above In/Out marks without reducing waveform space. Bookmarks always accept left clicks; the right-click-only preference applies solely to In/Out marks.
- Alt-drag a point bookmark in either direction to extend the same bookmark. Resize either endpoint without Alt, move the body without changing duration, and retain names, notes, color, Undo/Redo and project persistence.
- Preserve bookmark spans through trim/merge annotation mapping, OTIO, Premiere XML and direct Resolve import. Clip spans at exported selections and convert both boundaries together across frame rates. Add the matching helper to the Studio bridge.
- Final Cut point markers retain range endpoints in their notes. OTIO retains span data, while Kdenlive's current importer may ignore its duration; describe these format limits in the export window.
- Add the remembered export option Fix bookmarks for Final Cut Pro / Kdenlive, On by default for those formats. Export each span as numbered start/end point bookmarks, preserving the original project annotation. Keep the ending point inside the cut, including mixed-rate timelines; combine coincident endpoints as 1 / 2 on one-frame sections. Leave native Resolve and Premiere spans intact. Adapt OTIO labels and clip-relative marker coordinates for Kdenlive's importer.

## 0.18.0 — combined waveforms, queue filters and shortcut focus

- Combine all audio streams for Auto waveforms instead of selecting a single stream. Prevent opposite-phase cancellation and truncation by shorter streams; use distinct compact caches for combined results.
- Keep fully disabled mixes muted through seeking and unpause, including audio filter restarts; restore enabled tracks after the seek finishes.
- Add Stars, Bookmarks and Marks queue filters in the main and detached queues. Sort Stars and Bookmarks by color slot; use the earliest bookmark and retain ordinary clip order for Marks.
- Add the Star title help badge and clearer organization tooltips. Enter saves the Star. Add S for Stars, R for Review and C for Compare overlaps, preserving conflicting existing custom bindings.
- Allow playback shortcuts from readonly main-window controls. Let held Move Playhead to Mouse start from any main-window area, including native video children; suspend main shortcuts in popups and other applications.

## 0.17.0 — persistent audio gains, devices and clip Stars

- Restore mixer gains after mpv restarts audio filters on seek; retry gain commands while filters are temporarily unavailable. Apply the same restoration to scrub-audio workers. Verify audible output, rather than mute flags alone.
- Stop writing per-clip audible-track changes into the default date-based layouts for later clips. Preserve saved clip mixes.
- Add Audio Device selection and Refresh at the top of Audio settings, defaulting to Windows’ default output. Use the chosen device throughout playback and scrub audio.
- Add titled, colored clip Stars beside the magnet and in list/grid queues. Preserve them in project documents and Undo, without timeline/export annotations or the activity asterisk.
- Add Open file in video player and Open file location below the timeline. Remove audio-only activity indicators.
- Rename the shortcut label Confirm Trim, simplify the Escape capture hint, and default the magnifier cursor On for fresh configurations.

## 0.16.0 — final testing defaults and interaction fixes

- Remove the enabled-for-export count from activity tooltips.
- Apply the active app palette throughout Archive Tools and retain theme images safely when it closes. Center source frame rates vertically beside the timecode.
- Single left-click seeks without selecting a bookmark when right-click interaction is enabled. Double left-click always edits; opening any bookmark editor pauses at that bookmark.
- Display Automatic (RECOMMENDED) for magnifier rendering while retaining its stored value.
- Open the temporary Google URL using Windows’ default browser handler, removing the dynamically imported module missing from the previous executable.
- Deliver a clean preview with default preferences and no personal projects, custom themes, scan history or caches.

## 0.15.0 — comparison scrubbing, themes and bookmarks

- Route the held playhead shortcut to the visible comparison timeline. Use independent audio preview workers so continuous video seeks do not starve scrub sound; release workers on comparison close/page changes. Show source frame rates per pane and in the controls.
- Hold an in-memory picture of visible app windows during theme preparation instead of toggling native child visibility. Recolor existing comparison canvases and video surrounds.
- Add a bookmark badge after the activity star, using the earliest bookmark color without widening the activity column. List actual review work and undone trims in the star tooltip. Recognize older restored trims from receipts.
- Edit bookmarks on double right-click when right-click interaction is enabled; direct clicks always jump exactly even with snapping disabled.
- Shorten trim chunks and give their waveform more height.
- Temporarily open Google from About’s GitHub page button for browser-launch testing. Free trimming/re-encoding remains deferred.

## 0.14.0 — trim recovery and comparison review

- Move canceled verified trim copies to Deleted, preserving the full source.
- Identify trims with scissors badges in list and grid queues. Add receipt-based Undo trim, including restart recovery, split outputs, prior file names and annotations.
- Add Use entire clip as one enabled Review selection, with normal Undo support.
- Preview comparison frames and optional audio while dragging, honoring the scrubbing toggles and resuming playback according to the existing stop setting.
- Replace ambiguous selected-clip overlap actions with one numbered delete action per member. Refresh the remaining comparison and support Undo/Redo.
- Clarify the Discard prompt: Discard keeps the progress from your last save.

## 0.13.0 — trim correctness, naming and About

- Keep trim moves on the cut grid without expanding the selected chunk count. Clamp pointer times and let left click scrub when right-click mark interaction is enabled.
- Stop stream-copy trims by verified video packet count and retry bounded in-GOP seek positions when container indexes select the preceding keyframe. Preserve full tail audio, packet/timing validation and decode checks.
- Rename the action Trim video. Move full trim originals to Deleted and use _TRIMMED by default. Add the shared opt-in original-name setting for trims and merges, with recoverable installation and no overwrite of unrelated files.
- Add the larger looping About logo, supplied description, version and disabled GitHub placeholder.


## 0.12.0 — preserve playback during themes and reduce resize work

- Keep video surfaces and their parent chain visible during theme changes. Queue non-erasing Tk repaints without recursively clearing native video children.
- Coalesce resize callbacks at a 16 ms cadence instead of running at every idle gap. Reuse waveform peak aggregation when only panel height changes.
- Retain all 0.11 fixes. Real mixed-DPI dragging still needs user validation; no claim of completely seamless resizing on every system.


## 0.11.0 — UI refresh and resource fixes

- Reuse audio controls and marked-moment rows; avoid rebuilding the review queue on every ordinary clip switch. Keep queue badges visible while marks move.
- Reuse theme images and ttk elements instead of permanently accumulating elements on each theme change. Batch native painting without screenshot overlay windows.
- Restore the frame-rate label after switching between clips with matching rates. Ignore Deleted originals when constructing active overlap groups and recover available report pointers.
- Add the main window's waiting logo frames, taller Settings, About, the Archive Tools warning toggle, generic editing-software export wording, and the audio-scrubbing performance warning.
- Add approximate scan progress beside the spinner and at the bottom of the window. Avoid rewriting unchanged settings.
- Resizing remains a known limitation; this version does not claim editor-grade smooth resizing or exhaustive hardware validation.

## 0.10.0 — portable project documents and project management

- Store each project's readable JSON document in Projects beside the app. Keep main-app save/trim/merge journals and receipts in Projects/.Project Data; retain media in its video folders. Import older video-side project records with verification before removing unchanged legacy metadata.
- Ask for a name after choosing a video folder, prefilled with its folder name. Add Rename Project and Delete Project in Projects. Rename preserves unrelated pending review choices; deletion removes the project record without saving or sorting any recordings, including an active project with unsaved decisions.
- Add Open project file for shared documents, automatic discovery of copied project files and a video-folder location prompt for missing paths. Respect files removed manually. Reject malformed documents, paths outside the store and project removal/renaming during unresolved recovery.
- Keep folder-rename references and Archive Tools' return to project review connected to the new project documents.

## 0.9.0 — integrated overlap review and new merged clips

- Make Next linked clips page through large groups, then open the next group. Explain how to scan when Compare overlaps is used on an unlinked clip.
- Show a centered, outlined alignment wheel. Hide the regular timeline and Marked moments while comparing, and restore their panel sizes on return. Highlight every group member in List/Grid and extra queue panels while retaining an individually chosen target.
- Use the normal skip/play/frame transport without snapping/bookmark buttons in integrated comparison. Handle Space before focused buttons, and route frame stepping and playback rates to the synchronized comparison.
- Correct simultaneous audio normalization for mpv's cubic volume curve, preserving the combined level of aligned matching sources.
- Add Move selected to Deleted · keep others, with undoable review decisions, alongside Keep selected · move others to Deleted.
- Install each main-app merge as a new, distinct Unused clip with a chain badge and mapped annotations. Move every complete source into Deleted using collision-safe names; journal media and project changes for failure/restart recovery. Preserve earlier archive dependencies on the complete originals.
- Rewrite the merge confirmation and retain the Archive Tools recovery-ledger workflow.

## 0.8.0 — overlap audio, adaptive scans and cache retention

- Default overlap audio to Both, or All for groups with three or more clips. List each clip by number and filename, including other pages; choosing a hidden clip opens its page. Both/All mixes the visible clips without creating unbounded playback clients.
- Use lower scan/probe priority during playback and review activity. Return to normal priority after five idle seconds, and lower it again as work resumes. Retain completed packet indexes and comparisons on disk when scans are canceled or the app closes.
- Default both generated-cache cleanup options to 30-day retention. On-close cleanup defaults off; each type's two options switch one another off. Check expiry on startup, on setting changes and daily, scoped to owned cache files. Scan checkpoints, recordings and exported audio are excluded.
- Add Open App Folder beside Cancel in Settings. Rename the bookmark display palette to DaVinci Resolve, accepting the old stored name and theme files.
- Right-click while magnifying toggles the zoom cursor and consumes the click before timeline actions. Enable right-click selection/dragging of existing marks by default; turning the option off restores drawing over them.
- Support folder-only builds with complete source in a Source subfolder. Private previews no longer require version ZIP archives.

## 0.7.0 — revised help and review interaction fixes

- Import the author's 67 help edits, retain Default lines and live shortcuts, and remove the requested Projects sort help. Clarify audio levels, OTIO/XML exports, the speed minimum and fullscreen-only Escape capture.
- Rename Mint to Michael House-Key, Sunshine to Jarate, Sky to Gotta Go Fast, Rose to Rose Quartz, Lavender to Grimace Shake and Peach to Elephant Daisy. Migrate saved built-in names without changing their colors or custom theme names. Use the author's IconV2 artwork for app/window icons.
- Open projects paused regardless of clip autoplay. Keep autoplay available for later clip selections. Ignore logo clicks while an intro or outro/intro sequence is running, including in Projects and Archive Tools.
- Handle modifier-key releases before native widget/menu bindings so audio-scrubbing shortcuts keep working. Preserve the selected scrubbing preferences when Settings is saved.
- Subtract 0.1× from the current rate for the slower-speed shortcut, down to 0.1×. Let Escape bind fullscreen while retaining capture cancellation for other actions. Re-entering the current Trim File mode does nothing.
- Coalesce resize work, reuse unchanged transport/panel layouts, cache thumbnail paths/decoder lookup and avoid repeated cache-size scans. Cache the waveform as a raster instead of repeatedly painting a complex native polygon. Keep video decoding and playback unchanged.
- Apply themes behind temporary covers, with holes for live video, then reveal the completed repaint and caption colors together. Build button backgrounds in memory instead of per-pixel Tcl calls.
- Continuous resize updates are verified, but dense layouts still hitch in the local Windows tests. This preview does not claim Resolve-level resize smoothness.

## 0.6.0 — background scans and adaptable controls

- Keep playback, seeking, bookmarks, moments and sorting available during overlap scans. Run scanning at background priority; cache completed indexes and comparisons so cancel/restart resumes progress. Pause around source moves and resume afterward.
- Show linked overlap group numbers and brackets in both List and Grid, including extra queue panels. Replace the scan's white block with a themed spinner.
- Default dual-monitor mode to four total panels: Unused, Used, Kept and Deleted. Added panels default to Marked and All; custom choices remain remembered.
- Swap Left/Right frame stepping with comma/period clip navigation, while preserving custom bindings. Route Space to playback after transport button clicks.
- Adapt transport controls to monitor resolution and DPI, add a drag handle above Play and remember manual sizing. Refresh the player's themed title bar when native handles or display settings change.
- Match Rose light mode to the supplied pink palette. Replace timecode/search help and preserve the locked audio-scrubbing preference when video scrubbing is off.
- Retain earlier previews and project formats. No new runtime dependencies or publishing.

## 0.5.1 — mixed-DPI fixes and logo polish

- Set per-monitor DPI awareness before creating windows and in the EXE manifest. Use physical pixels for fullscreen, live zoom and tooltip positioning; size tooltip text using its owning window's DPI. Reconnect DWM magnification when Tk replaces a native wrapper window.
- Reserve the logo slot before project load and use the author's corrected transparent hold images. Add a Projects header that immediately plays intro, holds for four seconds, then loops outro/intro.
- Keep playback controls above the main timeline as well as beneath the detached player. The main controls remain available while the player is fullscreen.
- Preserve the saved extra queue panels when closing with dual-monitor mode off, and repair empty layouts written by the previous preview. Use one List/Grid toggle per panel.
- Match Kachow to the author's supplied red palette. Set the default waveform to #b39ae0 and make generated light-theme accents darker with stronger waveform, selection and button contrast.
- Keep old previews and personal preferences; no publishing or new dependencies.
- Rename the portable settings file to ClipComb Pro.ini, with atomic migration of clip-review.ini. Prefer an existing new file. Public app-only upgrades contain an example instead of an initialized INI, so extracting an update does not overwrite preferences.

## 0.5.0 — animated logo and dual-monitor workspace

- Play the author's dark/light intro after a project is ready, then keep its hold image. Clicking plays outro, intro and hold. Include the same animation in Archive Tools.
- Add Dual Monitor Mode with a detached native player, live magnifier, nearest-monitor fullscreen and up to six configurable review queues. Restore window positions at startup; manually reopening the detached player centers it over the main app.
- Share one thumbnail worker and memory budget across every queue. Reuse Windows thumbnails without copying them, preload nearby rows, resize with Ctrl+wheel and default generated-thumbnail cleanup to on.
- Add pastel red Kachow between Peach and Sunshine, success feedback with a contrasting border, an archive-alignment spinner and a remembered Archive Tools startup option.
- Keep the current playback engine loaded during metadata-only saves; cover required file-move reloads with the last decoded frame. Preserve the Audio Mixer sash through fullscreen cycles.
- Restore selection on undone bookmark deletions, clear stale review stars after all edits are removed, center grid badges below names and fix the playhead cap. Relabel the export shortcut for editing software generally.
- Keep existing preview folders unchanged. No new runtime dependencies or publishing.

## 0.4.1 — queue scaling check

- Keep review-status badges aligned with visible clips when the queue is scrolled and heading height changes with display scaling.

## 0.4.0 — queue and theme preview

- Preview every theme change immediately; Save settings commits the choice and Cancel restores the original. Add pastel light variants and the author's light-mode header logo.
- Save and delete shareable named theme INI files in Themes beside the EXE. Themes include dark/light palettes and bookmark colors.
- Add a virtual thumbnail grid, themed list/grid controls, Windows thumbnail-cache reuse and background single-frame fallback. Load thumbnails only for visible clips, keep a bounded image cache, and pause thumbnail reads around file operations.
- Add large review-status stars and missing-file X badges. Missing records retain their category and annotations until explicitly forgotten; Delete/Backspace removes the selected missing record without deleting media.
- Highlight selected bookmarks with a white border, center a three-pixel playhead, and delete selected bookmarks or In/Out marks with configurable Delete/Backspace bindings. Fix duplicate Undo tooltips and outline magnet tips in both states.
- Capture shortcuts directly by double-clicking Primary/Secondary cells. Escape or five seconds cancels; middle and side mouse buttons are supported. Keep only Clear below the table.
- Separate passive discovery/metadata from review progress, preventing unwanted save prompts on untouched projects and settings changes.
- Add cancelable overlap scans, including interruption of the active FFprobe process. Archive Tools opens from Projects without a project, displays a remembered warning, occupies the app window and offers a return control.
- Update the live zoom caption. Keep existing file formats, review data and saved settings compatible. Add no new runtime dependencies; nothing is published.

## 0.3.0 — private bookmark and trim preview

- Add transport bookmark and magnet controls, with a rotated magnet and white tips. Snapping controls both playhead and bookmark movement; clicking a bookmark always seeks to its frame.
- Add bookmark deletion, 16 stable color slots, editor display palettes and custom swatches. Direct Studio import preserves all 16 Resolve colors; OTIO uses its supported subset. Export can place bookmarks on the timeline instead of clips.
- Add folder creation, renaming and Explorer access, with Up navigation selecting the previous folder.
- Clear all clip-specific view state when switching to an empty project, without changing the previous project's annotations.
- Size the magnifier with Ctrl+wheel while preserving its aspect ratio; enlarge the optional invert reticle. Keep the live compositor renderer unchanged.
- Default verified trims to replacement under the original filename. Preserve complete sources in Deleted as _ORIGINAL, with exclusive numbered backups, transaction recovery and mapped annotations. Joining kept sections defaults on; separate-copy mode remains available.
- Add bindable T for Trim file, dynamic shortcut tooltips, visible active modes and a deferred tutorial entry point.
- Fix mixed-rate bookmark placement in direct Studio imports and source ranges in legacy XML. Document Resolve's OTIO import-rate requirement.
- No publishing is performed. No new runtime dependencies are added.

## 0.2.0 — private integration preview

- Rename the app to ClipComb Pro and use the author's new Blender/Affinity logo everywhere.
- Add compact source bookmarks with editable names/notes, Undo, hover details and a customizable E shortcut.
- Add dedicated Resolve OTIO export with clip markers, notes, linked audio and Inspector levels; retain XML exports for other editors.
- Integrate overlap brackets, linked mpv comparison, group merging and full archive tools in the review workspace.
- Add a separate lossless Trim file mode with visible keyframe boundaries, verified copies, join padding disclosure and annotation remapping.
- Keep legacy project/config/ledger filenames compatible. No publishing is performed.


## 0.2.0 — Preview

- First release candidate under the ClipComb Pro name.
- Project-based clip reviewing and save-time sorting into Unused, Used, Kept and Deleted.
- Multistream audio mixer, hardware-assisted playback, adjustable speed, scrubbing and frame inspection.
- Multiple reorderable marked moments, waveforms, live magnifier, themes and customizable shortcuts.
- Bounded Undo/Redo with action descriptions and a default limit of 50.
- Source-frame timecode by default, plus source frame-rate display.
- File-based timeline interchange and direct append to existing Resolve Studio timelines.
- Preserved project/config compatibility with the earlier Clip Review private builds.

The public app-only package obtains media engines separately. Fresh installs use generic audio names; existing private audio layouts remain available through their saved INI.
