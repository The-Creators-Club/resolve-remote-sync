# Sealed notes: python-standard-library+sqlite

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 1 notes.

### SRV-S12: Row-by-row inserts held the write lock for seconds beside a busy thread.
- Why: Each row hands back the interpreter lock; a 3,800-row replace took 0.08 s quiet, 28 s beside one busy thread, 181 s beside two.
- Must: Bulk writes go in as one statement, so the write lock is held under a second whatever else the process is doing.
- Tool: Python sqlite3 module (executemany under the GIL)
- Where it bit: The server: installing it and keeping it running
