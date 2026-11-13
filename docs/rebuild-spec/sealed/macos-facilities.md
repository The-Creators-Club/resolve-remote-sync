# Sealed notes: macos-facilities

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 3 notes.

### APP-S06: Multi-line safety notifications never appeared on a Mac.
- Why: The Mac notification was built as a script string, which cannot hold a newline, so every multi-line notice silently failed; the Windows balloon also cut long text.
- Must: Notification text is collapsed to one line before the Mac call, and every notification is tested on each system at its real length and characters.
- Tool: AppleScript "display notification" (macOS) and the Windows tray balloon
- Where it bit: The app on each editor's computer

### APP-S16: Re-running the Mac installer erased the whole remote-access configuration.
- Why: macOS's built-in text-processing tool rejects a multi-line variable, produced empty output, and the script wrote that over the config, destroying unrelated entries.
- Must: An installer re-run replaces a config only when the new one is complete and keeps every other section; otherwise it leaves it untouched.
- Tool: awk on macOS (BWK awk)
- Where it bit: The app on each editor's computer

### RSV-S11: A Mac's open-files listing cuts command names to nine characters.
- Why: By default the listing truncates command names to 9 characters, so "davinci resolve" never matched when finding Resolve's process.
- Must: Finding Resolve's process on a Mac never depends on a truncated command name.
- Tool: lsof on macOS (needs +c 0)
- Where it bit: Resolve on the editor's computer
