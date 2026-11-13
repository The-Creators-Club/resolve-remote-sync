# Sealed notes: restic

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 1 notes.

### SRT-S09: The cloud backup tool counts a file only when it finishes.
- Why: Its live progress jumps per finished file, so an instantaneous speed is meaningless.
- Must: Cloud upload speed shown to a person is smoothed over about two minutes.
- Tool: restic --json status
- Where it bit: The Footage Sorter and camera cards
