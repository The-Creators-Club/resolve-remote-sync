# Sealed notes: pyinstaller+python-standard-library

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 2 notes.

### APP-S08: After a self-update the app lost its codecs and dialogs, then crashed.
- Why: A one-file packaged app started by another copy of itself reuses the parent's unpacked folder, which the exiting parent deletes moments later.
- Must: An app restarted by its own update runs as a fully independent instance and starts cleanly every time.
- Tool: PyInstaller one-file mode (version 6 and later); Python's lazily imported idna codec
- Where it bit: The app on each editor's computer

### APP-S10: Every secure download from the packaged Mac app failed certificate checks.
- Why: The packaged Mac app carried no list of trusted certificate authorities, so every https download failed with "unable to get local issuer certificate".
- Must: The Mac app verifies secure downloads against a trust store it can always find, proven on a real Mac build.
- Tool: Python frozen with PyInstaller on macOS
- Where it bit: The app on each editor's computer
