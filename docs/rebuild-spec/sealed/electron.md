# Sealed notes: electron

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 2 notes.

### CE2-S06: The desktop wrapper's window ran at 20 frames a second.
- Why: The packaged desktop window spent about 49 ms presenting each frame, while the same page in a browser app window held 144.
- Must: Measure frame rate in the window the editor actually uses, and ship whichever window kind meets the performance goal.
- Tool: Electron
- Where it bit: Timeline Cards: the editor

### APP-S15: The desktop app's own window ran the editor at 20 fps; the browser ran 144.
- Why: The same page ran 144 fps in Chrome but about 20 in the app shell's window, each frame stalling about 49 ms on hand-off to Windows; driver settings did not cure it.
- Must: The desktop app shows the editor at the same frame rate as the plain browser on the same computer.
- Tool: Electron
- Where it bit: The app on each editor's computer
