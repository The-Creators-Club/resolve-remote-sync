# Sealed notes: resolve-preference-files

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 3 notes.

### RSV-S08: Resolve keeps LUT locations and drive mappings in two plain-text preference files.
- Why: Both files must change together; their numbering bases can differ, Resolve's own trailing entry must stay last, and a root-owned file can be silently re-owned.
- Must: Edits are made while Resolve is closed, back up first, keep both files consistent, and preserve every existing entry and its numbering.
- Tool: editing Resolve's preference files directly
- Where it bit: Resolve on the editor's computer

### RSV-S09: Changing Resolve's drive mapping on a Mac seemed to work, then reverted.
- Why: Mac Resolve keeps it in config.dat and hidden .config.data, rebuilding the first from the second; direct IO is "MacDIO" there, and /Volumes must stay last.
- Must: Both Mac files change together with the Mac spelling, inserted before Resolve's trailing entry, also checking the App Store build's own sandbox folder.
- Tool: editing Resolve's preference files directly (macOS)
- Where it bit: Resolve on the editor's computer

### RSV-S10: Resolve's scripting switch lives in both preference files, which must agree.
- Why: The "External scripting" choice is stored as System.Scripting.Mode in config.dat and .config.data, 1 meaning Local (0 and 2 inferred).
- Must: The setting is written to both files while Resolve is closed, and reported as set only when both say Local.
- Tool: editing Resolve's preference files directly
- Where it bit: Resolve on the editor's computer
