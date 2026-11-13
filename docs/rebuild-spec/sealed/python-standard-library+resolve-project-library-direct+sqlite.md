# Sealed notes: python-standard-library+resolve-project-library-direct+sqlite

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 1 notes.

### CFI-S29: With a disk-stored Resolve library, every transcript came back empty.
- Why: The database library refuses by default a connection used on another thread than the one that opened it, and the failure was swallowed.
- Must: Network and disk Resolve libraries are tested end to end, and a read failing every time is shown as an error, never as empty transcripts.
- Tool: reading Resolve's disk project database with Python's sqlite3
- Where it bit: Timeline Cards: footage in, ready to cut
