# Sealed notes: docker+truenas

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 1 notes.

### SRT-S08: A rename between two separately mounted folders fails even on one dataset.
- Why: Staging and the project tree were mounted separately, so a rename between them failed with a cross-device error although both sat on one dataset.
- Must: Whatever performs moves sees staging and project folders under one mount, so a move between them is a rename.
- Tool: Docker bind mounts on TrueNAS (EXDEV)
- Where it bit: The Footage Sorter and camera cards
