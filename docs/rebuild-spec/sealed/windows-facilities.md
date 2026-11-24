# Sealed notes: windows-facilities

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 7 notes.

### CE1-145: Windows turns a refusal into a reset if the request body was not read.
- Why: A server refusing an upload before reading its body makes Windows reset the connection, so slow clients, a phone for one, never see the refusal.
- Must: Every refusal reaches the client as the server's own message, with the body read, within a size limit, before answering.
- Tool: Windows' network stack, when a server running on Windows refuses a request
- Where it bit: Timeline Cards: the editor

### APP-052: On Windows, two clock readings a moment apart are often identical.
- Why: Windows' clock ticks every 15.6 ms, so identifiers taken from the time collided (6 distinct of 10), muting new warnings and double-counting relaunches.
- Must: Nothing uses a clock reading as a unique identifier; two events in the same instant stay distinct.
- Tool: Windows' system clock
- Where it bit: The app on each editor's computer

### SRT-S04: The copy tool gives a file its full size the moment it starts writing.
- Why: A progress view counting files by size alone would call unfinished files done, because the tool pre-sizes each file.
- Must: A file counts as done only when its size and timestamp both match the source, or a check proves its contents.
- Tool: robocopy
- Where it bit: The Footage Sorter and camera cards

### SRT-S13: The script language turns lists of one or none into something else.
- Why: Returning a one-item list gave a single item and an empty list read as missing, so a one-file card silently stopped card detection.
- Must: Card detection works for cards holding zero, one or many files, and a failure in detection is reported, never swallowed.
- Tool: PowerShell array unrolling
- Where it bit: The Footage Sorter and camera cards

### REL-S01: Install and release scripts died on harmless error-stream text.
- Why: With stop-on-error, a native command's redirected error output becomes fatal, and a script with no explicit exit returns the last command's code.
- Must: Scripts judge each external command by its exit code only and always exit with their own explicit status.
- Tool: Windows PowerShell 5.1
- Where it bit: Releases and updates

### RSV-S13: Resolve's windows expose little to automation.
- Why: The main window has no child windows; the menu bar is exposed with submenus under their items; dialogs are hidden, reused top-level windows; buttons are named, fields anonymous.
- Must: A Resolve dialog is judged open only by whether it is visible, never by its window existing.
- Tool: Windows UI Automation on Resolve
- Where it bit: Resolve on the editor's computer

### SYN-S34: Keeping Windows awake silently failed after a single nudge.
- Why: A Windows keep-awake request belongs to the thread that made it and vanishes with it; without the continuous flag it resets the idle timer only once.
- Must: Sleep is held off exactly as long as work is moving and always released afterwards.
- Tool: Windows SetThreadExecutionState (ES_CONTINUOUS, per-thread)
- Where it bit: Sync
