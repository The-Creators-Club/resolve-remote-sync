# Sealed notes: pyinstaller

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 4 notes.

### ACC-S01: A single-file program cannot carry a lesser-GPL library.
- Why: A single-file build unpacks libraries to a new temporary folder each launch, so recipients cannot replace a lesser-GPL library as that licence requires.
- Must: Lesser-GPL libraries ship as separate replaceable files with their full licence text and how to replace them, never inside a single-file build.
- Tool: PyInstaller one-file builds with LGPL libraries (pystray, psycopg2)
- Where it bit: Accounts, privacy and the legal paperwork

### APP-S09: A handed-over new build was judged dead because the wrong process was watched.
- Why: The spawned process of a one-file packaged app is an unpacker that starts the real app as a child, often taking over two seconds.
- Must: When handing over to a new build, either the spawned process or its child counts as the new app, waiting up to thirty seconds.
- Tool: PyInstaller one-file executables
- Where it bit: The app on each editor's computer

### APP-S12: Code writing to standard output crashed inside the packaged windowed app.
- Why: In the packaged windowed build standard output does not exist, so imported code that wrapped it failed at import.
- Must: Code loaded inside the packaged app never assumes a console exists.
- Tool: PyInstaller windowed builds
- Where it bit: The app on each editor's computer

### APP-S13: A single-file self-extracting app writes hundreds of megabytes per start.
- Why: Each start unpacked 108 to 232 MB to the temp folder, each forced kill left two 108 MB folders, and security software reads the pattern as malware.
- Must: Starting the app writes no large temporary files, leaves nothing behind after a forced kill, and is not flagged by common security software.
- Tool: PyInstaller one-file packaging
- Where it bit: The app on each editor's computer
