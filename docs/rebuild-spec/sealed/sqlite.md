# Sealed notes: sqlite

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 6 notes.

### BRO-S16: Replacing the live search database by plain copy risks corrupting it.
- Why: Copying over a database in write-ahead mode, or leaving old journal files beside a replaced copy, can corrupt it, and the search kept serving the old file until restarted.
- Must: A new index is staged beside the live one, integrity-checked, refused on a large row shrink, swapped atomically keeping the previous copy, and reloaded by search on change.
- Tool: SQLite (write-ahead log mode)
- Where it bit: The b-roll archive

### SRT-S12: A three-character substring index cannot find two-character Chinese words.
- Why: A trigram index matches only queries of three or more characters, but two characters, such as 颱風, is a common Chinese word length.
- Must: A two-character Chinese query finds every name containing it.
- Tool: SQLite FTS5 trigram tokenizer (needs 3.34 or newer)
- Where it bit: The Footage Sorter and camera cards

### MUS-S04: After the library file was replaced, the running server kept serving the old one.
- Why: An open connection stays on the file it opened; replacing the file by rename leaves it reading the deleted old copy until reopened.
- Must: After the search data is replaced on the NAS, the next search reads the new data without a server restart.
- Tool: SQLite (a connection is bound to the file it opened, not to the path)
- Where it bit: Music

### MUS-S05: A rollback reported "restored" but silently lost recent changes.
- Why: Recent commits live in two side files beside the main file; moving the main file back without them discards every change since the last checkpoint.
- Must: Any move, backup or rollback of the library carries its side files with it, and a rollback reported as "restored" loses no committed change.
- Tool: SQLite in WAL mode (the -wal and -shm sidecar files)
- Where it bit: Music

### MUS-S06: A deleted highest record's number is handed to the next new record.
- Why: Without the auto-increment option, a new record gets one more than the current highest number, reusing a deleted top record's number.
- Must: Nothing stored outside the library's records, such as a preview file, is keyed by a record number that can be reused.
- Tool: SQLite (INTEGER PRIMARY KEY without AUTOINCREMENT reuses the top rowid)
- Where it bit: Music

### SRV-S13: Picking the newest saved database copy by name chose a journal file.
- Why: The database keeps files ending -wal and -shm beside each copy, so choosing the newest previous copy by name picked one of those.
- Must: A rollback picks only whole database copies and refuses journal files.
- Tool: SQLite
- Where it bit: The server: installing it and keeping it running
