# ClipComb Pro licensing

The project-authored application code, documentation and original logo artwork are licensed under **GPL-3.0-or-later**, unless an individual file states otherwise. You may use, study, modify and redistribute them under those terms. No purchase or royalty payment to the ClipComb Pro author is required. The complete license is in LICENSE.

GPL is a copyleft license: redistributed modified versions retain the GPL freedoms and applicable source-distribution requirements. It also permits commercial redistribution; offering ClipComb Pro for free does not prohibit someone else from charging for a redistributed copy.

## Original artwork

The original ClipComb Pro logo and animation artwork were made by WaveSmash in
Blender and Affinity. WaveSmash retains copyright in that original artwork. The
application implementation was generated with OpenAI Codex under WaveSmash's
direction; the artwork credit does not claim that WaveSmash manually wrote the code.

Forks may keep and use the existing logo under the GPL grant above. No rebranding
requirement or new artwork restriction is imposed here. Please retain the artwork
credit and do not falsely claim to have created WaveSmash's logo or imply endorsement
of an unrelated product. GPL permission is not a transfer of copyright ownership.
The app name is a branding/trademark matter rather than a copyright in a name;
this notice does not claim a registered trademark. No copyright symbol needs to
be drawn into the logo itself.

The ClipComb Pro logo was created entirely by the project author in Blender and Affinity, without stock assets. `assets/logo.ico` is the supplied IconV2 icon, and `assets/logo.png` is its largest frame for window icons. The unchanged IconV2 file, editable Blender and Affinity files, and associated image exports are included in `artwork/clipcomb-source`, under GPL-3.0-or-later. Blender and Affinity themselves are not bundled.

The author also supplied the dark/light intro, outro and hold artwork. Originals are retained in `artwork/clipcomb-source/animation`. `tools/prepare_logo_animation.py` prepares the compact runtime atlases and frame timings in `assets/animation`. The light intro's combined intro/hold/outro export is limited to its first 31 intro frames; the originals remain unchanged. Included frames keep their original order and GIF delays. This original animation artwork is covered by the same project license.

## Dependencies

The project does not claim authorship of Python, Tcl/Tk, Pillow, OpenTimelineIO, PyInstaller, libmpv or FFmpeg. They retain their respective copyrights and license terms. Full notices for bundled Python components accompany the public app-only executable. The separate media engines are not part of that public binary archive; see THIRD-PARTY.md and docs/MEDIA-TOOLS.md.
