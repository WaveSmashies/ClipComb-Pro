# Contributing

Run the Windows unit tests described in BUILDING.md. They use temporary test projects and do not need personal recordings or media engines. For playback changes, use a small generated recording and check pause/resume, seeking, speed changes and separate audio streams. For frame stepping, verify every displayed source frame in both directions; do not improve speed by dropping frames.

Keep changes focused. Preserve existing project documents, the safe Save transaction, custom shortcuts and per-clip mixes. A sorting decision is staged; file moves occur only on Save/export. Tests must never point at a personal clip archive.

Please include expected/actual behavior, reproduction steps, Windows version, ClipComb Pro version, container, codec, frame rate, stream count and relevant GPU information in a playback report. Remove private filenames and paths from reports unless you intentionally want to share them.

Changes are contributed under GPL-3.0-or-later, the app's existing license. See THIRD-PARTY.md before adding or redistributing dependencies.
