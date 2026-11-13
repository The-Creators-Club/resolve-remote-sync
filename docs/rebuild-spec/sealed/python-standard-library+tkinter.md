# Sealed notes: python-standard-library+tkinter

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 1 notes.

### APP-S01: The app vanished with no error, no log line and no trace, seven times.
- Why: The window toolkit aborts the process when a window interpreter is freed on any thread but its creator, which garbage collection of a reference cycle on another thread does.
- Must: Every window interpreter is created, used and freed on one thread, proven by a test in a child process whose exit code is the assertion.
- Tool: Tcl/Tk through Python's tkinter (Tcl_AsyncDelete abort)
- Where it bit: The app on each editor's computer
