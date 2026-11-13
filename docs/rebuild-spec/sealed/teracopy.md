# Sealed notes: teracopy

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 3 notes.

### SRT-S01: On Windows, card and drive copies go through the owner's chosen copier.
- Why: A build swapped in a home-made copier against the plan; that was ruled a mistake and reversed, the home-made one kept only for a Mac or a PC without it.
- Must: On Windows, card and drive backups run through the owner's chosen copier; any other copier is only a fallback where it is missing.
- Tool: TeraCopy
- Where it bit: The Footage Sorter and camera cards

### SRT-S02: The copier loses jobs sent at once, and its history format differs by version.
- Why: Several jobs handed to the running copier at once lost all but one; its history marks copied-and-verified as result 3; version 3.17 keeps history in another layout.
- Must: Copier jobs launch one at a time, each confirmed in its history before the next, read correctly from whichever version is installed, with matching hashes required.
- Tool: TeraCopy (history database; 3.x layout differs; 211 MB/s with verify against 188 for a plain copier)
- Where it bit: The Footage Sorter and camera cards

### SRT-S03: The copier's verify is one global setting, and unchecked results look queued.
- Why: Verify-after-copy is one global setting, and with it off a finished file reports the same result code as a queued one.
- Must: What landed is decided by looking at the disk, not the copier's result, and the global verify setting is restored even after a crashed run.
- Tool: TeraCopy 4.0.5 (global TestAlways setting, result code 2)
- Where it bit: The Footage Sorter and camera cards
