# Sealed notes: resolve-project-library-direct

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 19 notes.

### CFI-S25: Resolve stores each clip's transcription as a compressed list of timed words.
- Why: Each media-pool item holds its words with start and end seconds, pause markers, paragraph breaks and a language, offset by start timecode as nominal seconds (01:00:00:00 is 3600).
- Must: Read this way, Resolve's text is reproduced exactly (7 of 7 references), times are nominal seconds never converted through timecode, and cue breaks need not match.
- Tool: reading Resolve's project library directly (zstd protobuf per media-pool item)
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S26: Transcriptions with speaker detection or a zero start were lost from the export.
- Why: With speaker detection on, a speaker table precedes the words (15 of 98 clips lost); a word at 0.0 omits its start; "no speaker" is 2^64-1 or 2^64-2.
- Must: Records are recognised by their word entries wherever placed (as few as 3), missing times read as 0.0, and the language field accepted only when it looks like one.
- Tool: reading Resolve's project library directly
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S27: Resolve 20 changed its stored transcript layout and every transcript read as missing.
- Why: Resolve 20 put an extra length field in front of the stored data, so a reader expecting the older shape returned nothing.
- Must: Every layout seen so far is read, and an unreadable transcript is reported by clip as unreadable, never treated as absent.
- Tool: reading Resolve's project library directly
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S28: Writing corrected transcripts back into Resolve's library was never proven.
- Why: The stored transcript round-trips byte for byte, but whether Resolve reads a rewritten one was never verified.
- Must: No transcript is written into Resolve's library until a sandbox test shows Resolve reading it back correctly.
- Tool: writing Resolve's project library directly (46-byte header with two length fields, then a zstd frame)
- Where it bit: Timeline Cards: footage in, ready to cut

### CRX-S01: Reading a timeline from Resolve's library could describe the wrong one, or shift clips.
- Why: The read answered for whichever timeline was current, not the one asked, and titles were skipped uncounted, so every later clip was one position off.
- Must: A read of a timeline confirms it is the requested one, and track positions count every item, titles included.
- Tool: reading Resolve's project library directly (its database; compressed transcription records)
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### CRX-S02: Resolve's stored project data has no timeline item ids and stale file paths.
- Why: The library gives each clip's pool id, name and file path cheaply, but holds no timeline item id, and its stored media path can be out of date.
- Must: Item identity, start, length, clip colour, source in-point and rate are read live from Resolve; only clip name and path may come from stored data.
- Tool: reading Resolve's project library directly
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### CRX-S03: A timeline written straight into Resolve's shared library damaged a live project.
- Why: A direct write left 63 audio clips naming videos that did not name them back, and copied an outlier save counter of 665 billion that Resolve itself had written.
- Must: Nothing is written directly into a library editors work in; any test-library write uses Resolve's real save counter, ignoring outliers, and every link is mutual.
- Tool: writing Resolve's project library database directly
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### CRX-S04: Writes into Resolve's library land only while the project is closed.
- Why: Resolve never re-reads an open timeline and saves back only what its own edits dirtied, so a write under an open project was partly overwritten.
- Must: The library is written only while no Resolve holds the project, is verified before commit, undoable to an identical state, and the project is always reopened afterwards.
- Tool: writing Resolve's project library directly
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### CRX-S05: A whole episode can be written into Resolve's library in under two seconds.
- Why: A 490-cut timeline was written in 1.5 s and opened with picture, sound and links; grades and effects are not carried on new cuts.
- Must: A written timeline is verified before commit, backed up, undoable row for row, and refused for grade-carrying or multi-track timelines it cannot reproduce.
- Tool: writing Resolve's project library directly
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### CRX-S06: Reading Resolve's live library must not hold it open or bypass its locks.
- Why: A reader held one transaction open on the live library for the life of the process, a writer switched off its lock check, and real libraries were protected by name.
- Must: Reads never stay open between uses, writes always check Resolve's lock, and every real library is protected whatever its name.
- Tool: reading and writing Resolve's project library database directly
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### CRX-S07: Where Resolve stores audio fade handles.
- Why: Fades sit in an item's effects record, not in columns, as audio fade in and out in frames at the timeline rate (36 and 59 on a live check).
- Must: Writing a fade merges it into existing effects, leaves clip volume untouched, clamps to the cut's length, and reads back as written.
- Tool: reading and writing Resolve's project library directly (item effects record)
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### CRX-S08: Resolve stores a timeline clip's colour in a hidden record with its own order.
- Why: Colour is field 5 (zigzag, 2 times index 1-16) of the item's lockable record; proven 1 Green, 2 Teal, 3 Blue, 5 Pink, 6 Tan, 7 Brown, 10 Chocolate, 15 Violet.
- Must: Use the proven index table and verify the rest; clear a colour with the scripted clear call (setting empty does not clear); count each change as an undo step.
- Tool: reading Resolve's project library directly (item colour record)
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### RSV-S01: Read directly, Resolve's project library answers in milliseconds and shows multicam angles.
- Why: The media pool lists in 31 ms against 20 s by scripting, media ids equal scripting's unique ids, angles show; but link columns are empty, subtitle tracks must be skipped, frames are text.
- Must: Reads are read-only with 5 s timeouts, scoped to one project via association tables, video and audio tracks only, matching scripting's results, falling back to scripting on any surprise.
- Tool: reading Resolve's project library directly (PostgreSQL or disk library, zstd-compressed protobuf clip blobs)
- Where it bit: Resolve on the editor's computer

### RSV-S02: A direct library read misses unsaved edits and keeps stale per-cut paths.
- Why: A whole timeline reads in about 11 ms, live clip paths matching Resolve's on 1,298 of 1,298; edits since the last save are absent, and per-cut paths go stale after relinks.
- Must: Trust the clip's current pool path, never the per-cut path, and fall back to asking Resolve when the read fails or the format changes.
- Tool: reading Resolve's project library directly
- Where it bit: Resolve on the editor's computer

### RSV-S03: How Resolve's library stores timelines, rates, markers and multicams.
- Why: Rate is a double plus a drop-frame byte; extents are start and duration; frames are text; a multicam is a sequence; markers sit in a compressed blob; the save stamp is a counter.
- Must: A timeline read from the library matches what Resolve's scripting reports for every cut's id, start, length, clip and rate.
- Tool: reading Resolve's project library directly
- Where it bit: Resolve on the editor's computer

### RSV-S04: A plain imported clip's frame rate is missing where the library usually keeps it.
- Why: Plain clips (235 of 235 downloads) lack a rate on the media record; it is in the video info's typed dictionary, a pad byte after each type tag.
- Must: A plain clip's rate (16 bytes: little-endian double plus drop flag) is read from the video info record, and the decoder is tested on downloaded clips.
- Tool: reading Resolve's project library directly
- Where it bit: Resolve on the editor's computer

### RSV-S05: Leaked library connections can lock the whole studio out of Resolve's project server.
- Why: The network library server allows 100 connections; failed readers leaked theirs, one retry per 3 s per computer would exhaust it in minutes; library-wide listings return other projects' clips.
- Must: Every connection closes on every failure path, retries come at most once a minute, reads list one project only, and Resolve use is never held up.
- Tool: reading Resolve's project library directly
- Where it bit: Resolve on the editor's computer

### RSV-S06: A quarter of in-points read from the library are one frame off Resolve's.
- Why: Read with Resolve closed, a 490-cut timeline matched on all items and 137 of 140 cards, but 114 of 490 in-points read one frame higher, with no pattern found.
- Must: Library reads give cards identical to the live read or report the difference, tolerate a one-frame in-point gap, and frame-exact work uses Resolve's own figure.
- Tool: reading Resolve's project library directly
- Where it bit: Resolve on the editor's computer

### RSV-S07: Resolve's list of project libraries can miss the shared database libraries.
- Why: The scripting call that lists project libraries did not return every database library, but Resolve's own log names each one it connects to.
- Must: Every project library is found from the scripting list, Resolve's log and the disk library folders, and each is read read-only, once per library.
- Tool: reading Resolve's project libraries and log directly
- Where it bit: Resolve on the editor's computer
