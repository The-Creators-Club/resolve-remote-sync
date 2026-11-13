# Sealed notes: tkinter

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 3 notes.

### APP-S02: On a Mac, freeing the window toolkit's first interpreter crashed the process later.
- Why: macOS's menu system keeps calling into the first toolkit interpreter a process created; once it is freed, the process segfaults at random.
- Must: On macOS the first window toolkit interpreter lives for the whole process.
- Tool: Tk (tkinter) on macOS
- Where it bit: The app on each editor's computer

### APP-S03: On a Mac, installer and app windows froze, never updated, or hung for ever.
- Why: The toolkit silently drops updates scheduled from other threads, a window built off the main thread blocks with no error, and an early app-policy call aborts startup.
- Must: On macOS every window is created and updated from the main thread, and no window request can hang the app.
- Tool: Tk on macOS (Aqua Tk 9 alongside PyObjC)
- Where it bit: The app on each editor's computer

### APP-S04: The Mac sign-in form said both fields were empty after filling them.
- Why: With a hidden main window, a text variable created without an owner binds to that window, and nested event loops stopped dialogs returning.
- Must: Every dialog reads exactly what was typed and returns when closed, so it can be opened again in the same session.
- Tool: tkinter StringVar and nested mainloop
- Where it bit: The app on each editor's computer
