# The project library tools, and interview preparation

Terms used throughout this section:

- **Project library**: the PostgreSQL database in which DaVinci Resolve keeps its projects. One library is one database on the database host; the tools treat every database on the host (except the built-in `postgres` database and template databases) as a library.
- **Timeline**: a Resolve edit. **Item**: one cut placed on a timeline track. **Pool clip**: a clip in Resolve's media pool (a file, a multicam clip, a compound clip or a timeline used as a clip).
- **Pair**: the video item on V1 and the audio item on A1 that Resolve keeps linked to each other for one cut.
- **Cut list**: the list of cuts the Timeline Cards page sends (one entry per cut: which pool clip, which source frames, how much black before it, and optional colour, markers, fades and gap note).
- **Allowlist**: the list of library names a writing tool has been told it may write to.
- **Lock**: the project's "open in a Resolve" marker. When a Resolve has the project open, the library records that Resolve's id on the project; the tools read this as "the project is open".

---

# Part 1: the project library tools

## What all three tools have in common
(source: library/__init__.py, library_reader.py, library_writer.py, library_edits.py)

- They read and write Resolve's project library directly over the network. They never talk to Resolve itself, never start it, never use its scripting connection, and work the same whether Resolve is running, closed, or on a machine that is asleep.
- Database connection defaults (every tool): user `postgres`, password `DaVinci`, port 5432, connection timeout 10 seconds. The password is fixed in the code; there is no setting, environment variable or flag for user or password on the command line (callers that use the tools as a library may pass their own).
- Command-line default database host for every tool: `192.168.0.102`. Overridden with `--host H` where the command accepts it.
- The tools need the `psycopg2` (PostgreSQL) and `zstandard` (compression) Python packages, but only at the moment they connect or decompress; without them the tools can still be loaded by other programs.
- All three are reachable from the pipeline's single command-line front door as `py -3.12 pipeline.py library-reader`, `pipeline.py library-writer` and `pipeline.py library-edits`, listed under a "library" heading with the descriptions "read a timeline out of the project library (no Resolve)", "write a conformed timeline into the library" and "move / trim / split / delete / insert, in place".
- Everything they know about time is in frames. A timeline position is a timeline frame; a source position is a frame at the clip's own rate.
- Everything they say is printed to the console with a prefix: `[writer]` for the writer, `[edits]` for the in-place editor. The reader prints nothing except in its demonstration command.

## Reading: which libraries, projects and timelines exist
(source: library_reader.py)

- **List libraries**: every database on the host except `postgres` and template databases, sorted by name.
- **List projects in a library**: each project's id, name, the position of the timeline Resolve had open at its last save (or -1 for none), and last-modified time; sorted by project name.
- **List timelines in a project**: in Resolve's own order. For each: id, name, its position in the project's list, last-modified time, a `current` flag (true for the timeline Resolve had open at the project's last save), and a `helper` flag.
- **Helper timelines**: a timeline is flagged as a helper when its name contains " - ANGLE ", " - SYNC" or " - FRAMESYNC", written either with a long dash or with two hyphens. These are the per-camera timelines the pipeline's multicam syncing leaves behind. Helpers are still listed; they are only flagged so a picker can rank them lower.
- **What "current" means**: what was open at the LAST SAVE in Resolve, not what is open now.
- Everything the reader returns is the state as of Resolve's last save. Unsaved work in a running Resolve is invisible.

## Reading: one timeline
(source: library_reader.py)

- **Read a timeline** returns: its name, its project's name, frame rate, rounded frame rate, drop-frame flag, start frame, last-modified time (seconds since 1970), the cut items, and the timeline markers.
- **Which track is read**: only the video track with the lowest track number (V1), even if V1 is empty and the cuts are on V2. Items on any other video track are not read. Audio tracks are only consulted for fades (below).
- **Per item**: its id (the same id Resolve's scripting gives an item), start frame on the timeline, duration in timeline frames, the pool clip it points at, the pool clip's name (falling back to the item's own name), source in-point at the clip's own rate (or nothing if absent), the clip's own frame rate (or nothing if unreadable), the item's clip colour, and its audio fade-in and fade-out in timeline frames.
- Items are returned sorted by start frame.
- **Audio fades** are read from the first audio track (A1) and matched to the V1 item that starts on the same frame. A fade that cannot be decoded, a missing audio track, or any error at all reads as "no fade" (0 and 0); reading never fails because of fades. A fractional fade is rounded to the nearest frame.
- **Clip colour**: one of 16 names (Green, Teal, Blue, Purple, Pink, Tan, Brown, Apricot, Beige, Chocolate, Lime, Navy, Olive, Orange, Violet, Yellow) or none. Anything that cannot be decoded reads as "no colour". Eight of the sixteen name-to-number assignments (Purple, Apricot, Beige, Lime, Navy, Olive, Orange, Yellow) are inferences, not observations; a wrong one shows a cut in the wrong colour.
- **Markers**: each marker's frame (relative to the timeline start), colour, name, note, duration (at least 1) and an always-empty `customData`. Sorted by frame.
  - A timeline with no marker record has no markers (empty list).
  - A marker record that exists but cannot be decoded gives "unknown" (nothing), not an empty list, so a caller can keep markers it learned elsewhere.
  - Marker colour names: Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream. An unknown colour number reads as Blue. The number-to-name order has never been checked against a real Resolve answer.
  - If a marker carries more than three text fields, every text field except the last two is joined with spaces into the note.
- **Refusals while reading a timeline** (each stops the read with an error message):
  - "no timeline <id> in <library>"
  - "timeline '<name>' has no sequence" / "timeline '<name>' has no sequence row"
  - "sequence <id> has no video track"
  - "item <id> has a non-numeric Start/Duration (...)"
  - "FrameRate blob does not hold a frame rate: <hex>" when the stored rate is not strictly between 1 and 1000 frames per second, or "expected 8 bytes at offset 0, got N" when it is too short.
  - "MediaExtents is N bytes, not 16" when the timeline's extent is malformed.
- **Known one-frame disagreement** (documented in the code as unresolved): on one measured timeline about a quarter of items had a source in-point one frame higher in the library than Resolve's scripting reported. The reader returns the library's value.

## Reading: frame rates, drop frame and start timecode
(source: library_reader.py)

- A frame rate is read as a decimal number (for example 29.97002997) plus a drop-frame flag.
- Drop-frame timecode is understood for rounded rates of 30 (2 frame numbers dropped per minute except every tenth minute) and 60 (4 dropped). Any other drop-frame rate is computed with 2 dropped.
- A clip's start timecode is turned into "nominal seconds" (01:00:00;00 is exactly 3600.0 even at 29.97), which is what transcript timing elsewhere uses.

## Reading: pool clips, their files, multicams and transcriptions
(source: library_reader.py)

- **All clips in a library**: every pool clip's id and name, sorted by name then id. Two projects in one library can contain clips of the same name; the list includes both.
- **Clips of one project**: walks the project's media pool folder tree from its root and returns only clips in it. Clips whose name ends in `.mp4` and does not contain "Subclip" are listed first, then the rest, each group by name. A project name that does not exist returns an empty list.
- **Facts about one clip** (name, frame rate, start timecode in nominal seconds), or nothing if the clip is not in the library:
  - a multicam or compound clip takes its rate and start from the sequence it is;
  - a plain clip takes its own stored rate; if its stored start is unreadable, the start is taken as 01:00:00:00 (3600.0);
  - a plain clip with no stored rate (seen on downloaded YouTube clips) takes rate and start frame from its video info; if that is unreadable too, nothing.
- **Current file of every clip**: for the whole library, each pool clip's file path as it is now (directory plus file name), so a relink is reflected. Clips with no video information (audio-only clips, timelines, compound clips) are absent. The file path snapshot stored on a timeline item is deliberately not used here.
- **Is this clip a sequence**: finds the sequence a multicam clip, compound clip or nested timeline is, three ways; nothing for a plain media file.
- **The video of a sequence**: for any sequence (multicam, compound, nested timeline), its frame rate, start frame, duration in seconds, and every video track that has items (empty tracks left out), lowest track first. Per item: start, duration, source in-point (all in the sequence's frames), the file's own rate, the file path (current file; else the item's snapshot; else empty for a nested compound), name, the pool clip it points at, and a "retime" flag that is true when the item carries a speed change. The speed change itself is not decoded. Items whose rate cannot be decoded are silently skipped.
- **Multicam angles**: the video of the sequence a multicam clip is; each video track is one angle, the lowest is Angle 1. Audio tracks of the multicam are not read. A clip that is not a sequence gives nothing.
- **Resolve's own transcription of a clip**: the decompressed transcription record stored for a pool clip, if it looks like a transcription; else nothing. (What the transcription contains is handled by the transcripts section.)

## Reading: "has this timeline changed" fingerprint
(source: library_reader.py)

- Produces a short text token for a timeline built from: its id; its sequence's save counter, last-changed stamp and the timeline's modified time; and the count, latest start and largest in-point of its V1 items.
- Meant to be polled every couple of seconds; any change in the token means "re-read". The code records about 2 milliseconds per poll against about 25 milliseconds for a full read.
- A change on any track other than V1 that leaves those numbers alone is not seen.

## Reading: connection behaviour
(source: library_reader.py)

- One connection per library, opened on first use and kept for the life of the program.
- On any database error the connection is closed and the query is tried once more on a fresh connection; a second failure raises "<library>: <error>".
- Reading connections run without holding a transaction open (each query stands alone), so a long-running reader does not hold locks on Resolve's live library.

## Reading: the demonstration command
(source: library_reader.py)

- `py -3.12 pipeline.py library-reader <host> [library]`
  - `<host>` defaults to `192.168.0.102`; `[library]` defaults to the first library on the host.
  - Prints "libraries: <comma list>", then for each project in the chosen library "<name> (current timeline index N)", then each timeline as its position, name, a `*` after the current one, and its modified time as local `YYYY-MM-DD HH:MM`.
  - Read only. No flags.

## Writing: conform a cut list into a NEW timeline
(source: library_writer.py)

- **What it does**: builds a brand-new timeline in an existing project, straight in the library, from a cut list. It only adds rows; no existing timeline, item or clip is changed. The only existing rows it changes are two counters: the save counter of the bin that receives the new timeline, and the project's last-modified time.
- **Inputs**: library name, project name, new timeline name, the cut list, optional extra timeline markers, optional template timeline, optional "the project may be open" override.
- **Each cut may carry**:
  - `mp_uid` (required): the pool clip.
  - `src_in`, `src_out` (required): source frames at the clip's own rate.
  - `gap`: timeline frames of black before this cut (negative is treated as 0).
  - `person`: used only in messages.
  - `color`: a clip colour name for this cut (one of the 16 above). Absent means the cut keeps the colour the template item had.
  - `marks`: markers placed on this cut's first frame.
  - `gap_note`: text for a marker spanning this cut's black gap.
  - `fade_in`, `fade_out`: audio fades in timeline frames.
  - `_dur`, `_v_uid`: set only by the in-place editor's pinning (below); when `_dur` is present the cut's duration is that exact number of timeline frames.
- **Where each cut lands**: starting at the template timeline's start frame, each cut is placed after its gap; its length in timeline frames is `round((src_out - src_in) x timeline rate / clip rate)`, and never less than 1 frame. Cuts butt end to end in list order.
- **The clip's rate** used for that sum: the clip's own rate as the reader finds it; failing that, the rate stored on the template item; failing that, the timeline's rate.
- **The new timeline's settings** (frame rate, drop frame, start timecode and every other stored sequence setting) are copied from a template timeline in the same project. The template is chosen in this order: the one named by `--source` (or passed by id); else the timeline Resolve had open at the project's last save; else the first non-helper timeline in project order; else the first timeline.
- **Tracks**: the new timeline always has exactly one video track and one audio track, copied from the template's lowest video track and lowest audio track, whatever else the template has.
- **Each cut becomes a linked pair** (V1 video item and A1 audio item) cloned from an existing linked pair of the same clip somewhere in the project: preferably on the template timeline, otherwise the one with the lowest start frame. The new pair is re-linked so each half names the other.
  - Consequence for MULTICAM clips: the angle a cut shows is whatever angle that template item was on. The cut list cannot choose an angle.
  - Consequence for SPEED: a speed change on the template item is copied to every new cut of that clip.
- **What a new item does NOT carry over from its template**: colour grade, auxiliary grade, thumbnail, Fusion composition, original-clip link, owner, group, clip group, text, render cache, per-item markers, linked-item sync, and all effects. So new cuts arrive ungraded and without effects, except the audio fade it is asked for.
- **The timeline's own pool clip** is placed in the same media-pool bin as the template timeline's pool clip, at the end of that bin. The timeline is appended at the end of the project's timeline list.
- **Save counter**: every new or updated row that has Resolve's library-wide save counter gets "the counter + 1". The counter is found by taking the top 50 distinct values from each of 13 tables, sorting them, and walking up until a step of more than 100,000; everything above that step is treated as an outlier and ignored. When outliers are ignored it prints "DbSavedTime: ignored N value(s) far above the save counter (C), largest X".
- **Clip colour per cut**: when a cut names a colour, the new video item's small per-item record is rewritten with that colour (built from nothing if the template had none). An unknown name is refused (see gates). A cut with no colour keeps the template's.
- **Audio fades per cut**: written onto the AUDIO item only, as Resolve's audio fade effect, fade-in and fade-out in timeline frames. Each fade is rounded to a whole frame, must be a number and not negative (else refused), and is clamped to the cut's own length (longer is silently shortened). Fade-in and fade-out together may still exceed the cut. Zero means no fade. Video fades are never written.
- **Markers** (timeline markers on the new timeline):
  - Each cut's `marks` land on that cut's first frame.
  - Extra timeline markers are placed at their own frame (relative to the timeline start).
  - Resolve keeps one marker per frame: a second marker wanting an already-used frame is dropped and counted.
  - Marker colour names are matched without regard to case; an unknown colour becomes Blue. Duration is at least 1. `customData` is never written.
  - **Gap notes**: a cut with a `gap_note` and a gap of at least 1 frame gets a Green marker spanning the gap: name = the note text with runs of whitespace collapsed, note = "Gap note from Timeline Cards (N.N s)" (the gap's length in seconds), duration = the gap. It sits on the gap's first frame; if that frame already has a marker and the gap is longer than 1 frame, it moves one frame in and becomes one frame shorter; if there is still no free frame it is dropped and counted. Gap notes are placed after all other markers so other markers never move.
  - The result carries a `marker_note` sentence, built from: "N marker(s) wanted a frame that already had one and were dropped (Resolve keeps one per frame)"; "N gap note(s) had no free frame in their gap and were dropped"; and, whenever any marker was written, "customData is not in Resolve's marker encoding and was not written".
- **Gates, all checked before anything is written** (each one a refusal; nothing is written):
  1. The library is not in the allowlist: "the library '<name>' is not in this writer's allowlist (allowed: <list or none>) -- nothing was written". An empty allowlist refuses everything.
  2. The library is one of the five real libraries (`FF5`, `FF3`, `FF1`, `Base Drone`, `The Creators Club`), even if allowlisted: "the library '<name>' holds real work, and since 2026-09-29 no conform or edit is written into one: the first (Ordered V7 in FF5) left 63 half-linked clips that crash Resolve (docs/REPRO-RIGHTS-V7-DAMAGE.md). Conform through Resolve, or into FF5lab -- nothing was written". In practice only the sandbox copy `FF5lab` (or any other non-listed library) can receive a conform.
  3. Empty or blank timeline name: "the new timeline needs a name".
  4. Empty cut list: "nothing to conform -- the cut list is empty".
  5. No project of that name: "no project named '<name>' in this library"; more than one: "N projects are named '<name>' -- refusing to guess which".
  6. The project is open in a Resolve (lock set) and the override was not given: "the project '<name>' is OPEN in a Resolve (LockId <id>), which never re-reads a timeline it holds -- a conform would silently diverge. Close the project (or let the agent close and reopen it) and try again."
  7. The name is already used by a timeline in that project (exact, case-sensitive match): "this project already has a timeline named '<name>' -- pick another name".
  8. The project has no timelines to copy settings from: "the project '<name>' has no timeline to use as a template"; a named template not in the project: "the source timeline <id> is not in the project '<name>'"; the template lacks a video or audio track: "the template timeline '<name>' has N video and M audio track(s) -- a conform needs one of each to copy".
  9. A cut with no clip: "a cut has no mp_uid -- a cut with no clip cannot be conformed".
  10. A clip that has never been on a timeline in this project, or whose items there are not linked video+audio: "cannot conform: <clip name> (<id prefix>), ... has never been on a timeline in this project, so there is no item row to clone from" or "... is on a timeline but its video and audio items are not linked, so a conformed pair could not be linked either". (If some clips are missing and others unlinked, all are named under the "never been on a timeline" wording.)
  11. Per cut, numbered from 1: missing or non-numeric source frames ("cut N has no usable src_in/src_out (...)"); empty span ("cut N (<person>) is empty: src_in X is not below src_out Y"); negative start ("cut N (<person>) starts before the clip does (src_in X)"); past the end of a multicam or compound clip whose length the library knows ("cut N (<person>) runs past the end of its clip: src_out X but the clip is Y frames"). Plain files have no end check here.
  12. Per cut: an unknown colour ("cut N (<person>) asks for clip colour '<c>', which is not one of Resolve's 16"); a fade that is not a number ("cut N (<person>) has a fade_in that is not a number of frames (...)"); a negative fade ("cut N (<person>) asks for a fade_in of -X frames").
- **One transaction, checked before it counts**: the whole timeline is written in one database transaction, then read back inside that transaction and compared with the plan: name, frame rate, start frame, number of V1 items, each cut's start, duration, source in-point, clip and item id, each pair naming its partner in both directions, the audio item's start/duration/in-point equal to the video item's, the order numbers on both tracks being 0, 1, 2... by start frame, and the number of markers read back. Any disagreement undoes the whole transaction and reports "the new timeline did not read back as planned, so nothing was written: <first 8 problems> (+N more)". A timeline that cannot be read back at all: "the new timeline does not read back at all (<error>) -- rolled back".
- **Backup (undo) file**, written just before the transaction is committed:
  - Folder: the writer's backup folder; by default `library_backups/` beside the tool's own source file; the Timeline Cards server can set another.
  - Name: `<UTC time YYYYMMDDTHHMMSSZ>-<library name, unsafe characters replaced by _, at most 40 characters>-conform-<first 8 characters of the new timeline id>.json`.
  - Contents: format version 1, time, host, library, project, kind `conform`, the new timeline's id and name, number of cuts, the save-counter value used, every created row's key, and the previous values of the two updated counters.
  - Never deleted by any of these tools. If the program dies between writing the file and committing, the file describes rows that never appeared, and a restore treats them as already gone.
- **What the conform reports**: the new timeline's id, name, number of cuts, number of rows written, length in frames and seconds, number of markers, the marker note, gap notes written and dropped, ids of the new sequence, pool clip and two tracks, which template was used, project name and id, the new timeline's position in the project, the save-counter value, how many cuts lost a grade (`ungraded`), how many lost effects (`uneffected`), how many were recoloured, how many carry a fade (with "N cut(s) carry an audio fade"), how many identifiers inside the sequence record were refreshed, the backup path and the time taken.
- **Console lines while it works**: "[writer] gate: library '<l>' allowed, project '<p>' closed" (or "OPEN but allow_open was passed"); "[writer] template: '<name>' (sequence <id>, <fps> fps[ drop], start <frame>)"; "[writer] plan: N cut(s), F frames (S s), C clip(s)"; one line per table with its row count; "[writer] verified: ..."; "[writer] committed '<name>' = <id>: N cut(s), R row(s) in T s; backup <path>".
- **Warning at start-up**: when any of the five real libraries is in the allowlist: "[writer] WARNING: '<name>' is a REAL library and it is in the write allowlist; only restore and delete_timeline will touch it (docs/REPRO-RIGHTS-V7-DAMAGE.md)".
- **The "project may be open" override**: lets a conform go ahead with the project locked. The command line offers it as `--allow-open`. The code's own comments say the Timeline Cards server passes it only inside a close-and-reopen handshake with the Resolve agent; that handshake is not in these files.
- **Source in-point is written exactly as given**: no correction for the known one-frame disagreement.

## Writing: delete a timeline (the undo of a conform)
(source: library_writer.py)

- Deletes one timeline and every row reachable through it: its items, their joins and per-item records, its tracks, sequence container, sequence, version table and versions, its pool clip and the clip's bin entry, its marker record, and its entry in the project's list.
- **Gates** (refusal, nothing written):
  - Library not allowlisted (as above). Real libraries ARE allowed here if allowlisted.
  - No such project / several of that name (as above).
  - Project open and no override: "... a delete would silently diverge ...".
  - Timeline not in the project: "there is no timeline <id> in the project '<name>'".
  - Timeline is the project's current one while the project is open (even WITH the override): "that timeline is the project's current one and the project is OPEN in a Resolve -- close it first".
  - Timeline used as a clip on another timeline: "that timeline is used as a clip on N item(s) of other timelines -- refusing to delete it".
  - Another sequence claims its pool clip: "another sequence claims that timeline's pool clip -- refusing to delete it".
  - Another timeline shares its sequence: "another timeline shares this one's sequence -- refusing to delete it".
- Deletions that the database already performed through its own cascades are checked and counted rather than treated as failures; a row that is still there after its delete raises "<table> <key> would not delete -- rolled back".
- Afterwards: the project's timeline list and the bin's clip list are renumbered to have no holes; the project's "current timeline" pointer is moved down by one if it pointed after the deleted one, or set to "none" (-1) if it pointed at it; the bin's save counter and the project's modified time are bumped.
- Final check: if any item still hangs off the deleted sequence, everything is undone: "N item(s) still hang off the deleted sequence -- rolled back".
- Reports the timeline id and name, rows deleted, how many went by cascade, rows per table, time taken. Console: "[writer]   <table> -N row(s)" per table, then "[writer] deleted timeline <id> ('<name>'): N row(s) (K went by FK cascade) in T s". When renumbering was needed: "[writer] renumbered <table>: N row(s) contiguous from 0".
- No backup file is written for a delete.

## Writing: restore from a backup file
(source: library_writer.py)

- Takes a backup file written by a conform or by an in-place edit and puts the library back.
- Gate: the backup's library must be allowlisted; real libraries are allowed (undo).
- For a **conform** backup: deletes the timeline (with all the delete gates above, and without the "project may be open" override, so a restore of a conform into an open project is refused). If the timeline is already gone, prints "[writer] restore: timeline <id> is already gone" and carries on. Then puts the two counters back to their recorded values.
- For an **edit** backup: deletes every row the edit created, re-inserts every row the edit deleted with all its original columns (blobs, grades and ids intact), and puts every changed column back. Order numbers on tracks are moved out of the way first and back afterwards so they cannot collide. **No lock check is made for an edit restore**: it runs even if the project is open in Resolve.
- Console: "[writer] restored from <path>: N row(s) deleted, M re-inserted, K put back".
- Not reachable from `library-writer`'s command line; reachable through `library-edits undo` (below) and by programs.

## Writing: is the project open? (lock probe)
(source: library_writer.py)

- Returns the id of the Resolve that has the project open, or "nobody". Read only; not gated by the allowlist.

## Writing: command line (`library-writer`)
(source: library_writer.py)

- `py -3.12 pipeline.py library-writer conform <library> <project> <name> <cuts.json> [--source <timeline name>] [--allow <library>] [--host H] [--markers <marks.json>] [--allow-open]`
  - `<cuts.json>` is either a bare list of cuts or `{"cuts": [...], "markers": [...]}`.
  - `--markers <file>` replaces any markers found in the cuts file.
  - `--source` names the template timeline in that project; if no timeline of that name exists it prints "[writer] no timeline '<name>' to use as the template" and exits 1.
  - `--allow` may be repeated; without it nothing can be written.
  - `--allow-open` passes the "project may be open" override.
  - On success prints the result as indented JSON (internal fields left out) and exits 0.
- `py -3.12 pipeline.py library-writer delete <library> <project> <timeline name> [--allow <library>] [--host H] [--allow-open]`
  - Finds the timeline by exact name; if several share the name, the first in project order is deleted.
  - "[writer] no project '<p>' in <l>" or "[writer] no timeline '<t>' in <l> / <p>" then exit 1.
- `py -3.12 pipeline.py library-writer lock <library> <project> [--host H]`
  - Prints "[writer] <l> / <p>: OPEN, LockId <id>" and exits 1, or "... closed (no LockId)" and exits 0.
- Any gate refusal or failed check prints "[writer] REFUSED: <message>" and exits 1.
- A missing argument or unknown command prints the usage text and exits 2.
- Any other failure (for example a malformed record in the library, or a database that cannot be reached) is not caught and ends with a Python error trace.

## Editing in place: make an existing timeline BE a cut list
(source: library_edits.py)

- **What it does**: rewrites an existing timeline in the library so that it matches a cut list: cuts that are already right are left alone, others are moved, trimmed, extended, split, deleted or inserted, and removed material can be banked onto an "OffCuts" timeline. It reproduces the end result of Timeline Cards' keystroke edits without pressing keys.
- **Two operations**: **plan** (works out what would change, writes nothing, no allowlist check, legal on real libraries) and **apply** (plans again on its own connection, then writes in one transaction, verifies, backs up and commits).
- **Cut list**: the conform's cut fields, plus three that name an existing item:
  - `uid`: the V1 item this cut is, or was trimmed or split from;
  - `dur`: its exact length in timeline frames;
  - `head`: timeline frames taken off the original item's head by trims and splits (0 = untouched; negative = extended at the head).
- **Pinning**: a cut whose `uid` names a V1 item of this timeline with the same clip, and whose `dur` is at least 1, is "pinned": its source in-point becomes the item's own in-point plus `head` converted to the clip's rate, its length becomes exactly `dur`, and its source out-point follows. Pinned cuts are matched to their own item first. Cuts without a usable `uid` (an insert from a transcript, a clip the timeline never had) are matched by source span. This exists so that an untouched cut stays exactly as it was even if the page's own arithmetic was a frame off.
- **Matching cuts to existing items** (each existing item used at most once, same clip only):
  1. pinned cuts to their named item;
  2. then, in list order, items whose source span equals the cut's exactly;
  3. then items whose source span contains the cut's (a trim);
  4. then items whose span merely overlaps the cut's (an extend).
  - Ties go to the item whose current start is nearest the cut's target start, then the earlier start, then the lower id.
- **What happens to each cut** (one kind per cut):
  - **kept**: start, length and in-point already right; nothing about the item is written; its grade, effects, colour and per-item record stay.
  - **moved**: only its start changes.
  - **trimmed**: its in-point and/or length change (head trim, tail trim, extend within the clip), start may change too.
  - **new**: no existing item could be reused; a fresh linked pair is cloned. The clone source is the FIRST existing item of the same clip on this timeline (so a multicam insert inherits that item's angle, speed change, rate and link layout), or, if this timeline has none, the project-wide template pair the conform would use. A split is one kept or trimmed half plus one new half.
  - **removed**: an existing item no cut wanted: deleted (and banked first, if banking).
  - **faded** (independent of the five above): the cut's audio fade differs from what its audio item carries. Only the audio item's effects are changed, merged so every other effect and the clip volume on that item stay. A cut list that changes nothing but a fade is not a no-op.
- **Summary counts**: kept, trimmed, moved, new, faded, pinned, removed, banked, shifted (items whose start changed at all) and markers.
- **No-op**: if nothing is new, nothing removed, nothing faded and everything kept (and, on apply, the markers asked for are byte-identical to the ones there, or none were asked for), apply writes nothing, makes no backup, prints "[edits] '<name>' already IS this cut list: nothing to write", and returns 0 rows.
- **Clip colour is not applied in place**: a cut's `color` is checked (an unknown colour is refused) but never written. Kept, moved and trimmed items keep their colour; new items copy their clone source's colour.
- **Gap notes in place**: gap notes are only turned into markers when markers are passed (see the markers defect below).
- **Banking onto OffCuts** (on by default; `--no-bank` turns it off, which means removed items are simply deleted):
  - The OffCuts timeline is found in the same project by name, ignoring case; default name `OffCuts`, changed with `--offcuts NAME`.
  - Each removed pair is copied (cloned from the very rows being removed, so same clip, same source span, same length, same angle) onto the OffCuts timeline's lowest video and audio tracks, butted one after another after the last item already there (or at its start if empty).
  - The copied length is the removed item's length in the edited timeline's frames, unchanged even if OffCuts has a different frame rate.
  - OffCuts's extent, save counters and modified time are updated.
  - Refusals: "this project has no timeline named '<name>' to bank the removed cuts onto, and this module does not create timelines -- make it in Resolve, or discard the cuts instead (bank off)"; "N timelines are named '<name>' -- refusing to guess which to bank onto"; "that IS the '<name>' timeline -- refusing to bank its own cuts onto it"; "the '<name>' timeline has no V1/A1 pair to bank onto". These are only checked when something is actually removed.
  - Console: "[edits] banked N pair(s) onto '<name>' after frame F".
- **Markers in place**: only touched when markers are passed; existing markers are never shifted to follow moved cuts. An empty marker list deletes the marker record. **Defect**: passing any markers (a `markers` key in the cuts file, `--markers`, or a program passing a list) makes plan and apply stop with a Python error ("too many values to unpack") before anything is written, because the editor expects two answers from the marker planner and gets three. The command line does not catch this error, so the person sees a Python error trace.
- **Gates, all before any write** (nothing written):
  - apply only: library allowlisted and not one of the five real libraries (messages as for the conform).
  - apply only: project not open, unless `--allow-open` (message as above with "an in-place edit").
  - No project / several of that name.
  - Timeline not in the project: "there is no timeline <id> in this project -- nothing was written".
  - Timeline lacks a video or audio track: "the timeline '<name>' has N video and M audio track(s) -- an in-place edit needs one of each".
  - Items on more than one video track: "the timeline '<name>' carries items on N video tracks (V1/V2...) -- multi-track is out of scope for an in-place edit: editing V1 alone would leave the other tracks hanging over the new geometry".
  - Any V1 item without a linked audio partner: "N item(s) of the timeline '<name>' have no linked audio partner (<id>...) -- an in-place edit only knows linked V1/A1 pairs".
  - Audio partners spread over more than one audio track: "the timeline '<name>' has its audio partners spread over N tracks -- out of scope".
  - Different item counts on the video and audio track: "the timeline '<name>' has N item(s) on V1 but M on A1 -- the pairs do not line up, so this is not a timeline to renumber".
  - Empty cut list: "the cut list is empty -- an in-place edit that empties a timeline is not something this module will do".
  - Every clip, span, colour and fade gate of the conform (gates 9 to 12 above).
  - The banking refusals above.
- **What apply writes, in order**: bank removed pairs onto OffCuts; change start/length/in-point on both halves of every moved or trimmed pair (only the columns that changed); rewrite fades on audio items; insert new pairs (with their fades); delete removed pairs (their track joins, per-item records, then the items); renumber both tracks by start frame; update the sequence's extent and the save counters of the sequence, its container, the timeline's bin, the timeline's modified time and the project's modified time; markers if passed.
- **Verification inside the transaction** (any problem undoes everything): the edited timeline's V1 item count, each cut's start, length, in-point, clip and item id; every pair still exists and names its partner both ways; each audio item's geometry equals its video item's; every removed item is gone; on both tracks the order numbers are 0, 1, 2... by start and no two items overlap ("<track>: an item at X overlaps the one ending at Y"); for banking, OffCuts's item count, each banked piece's position, length, in-point and clip, and its linking; marker count. Reported as "the edited timeline did not read back as planned, so nothing was written: <first 8 problems> (+N more)". A track whose item count and join count disagree: "track <id> has N item(s) but M join row(s) -- rolled back".
- **Dry run** (`--dry-run`): does everything (plan, write, verify, write the backup file) and then undoes the transaction. The backup file is left on disk describing rows that were never kept. Console: "[edits] DRY RUN: N row(s) written and verified, then ROLLED BACK".
- **Backup file**: same folder as the writer's; name `<UTC time>-<library>-edit-<first 8 of timeline id>.json`. Contents: kind `edit`, library, project, timeline id and name, cut count, save counter used, the summary, the OffCuts timeline id, every created row's key, every updated row's previous values, every deleted row in full (binary columns stored as hex), and `pre`: the timeline's items (ids, start, length, in-point) before the edit. Written before the commit; never deleted.
- **Undo** (`library-edits undo`): runs the writer's restore (above), then, for an edit backup, re-reads the timeline and checks every item is back with the same id, start, length and in-point. If not: "the restore ran but the timeline does not read back as it was before the edit: <first 6 problems> (+N more)"; the restore has already been committed at that point, so this message means "look at it by hand". On success: "[edits] undone: '<name>' reads back exactly as it was (N item(s))".
- **Pin without editing**: a read-only operation that pins a cut list against a timeline (as above) and returns the pinned list, for a caller that wants to conform a NEW timeline from a draft of an existing one without the page's rounding. No allowlist check.
- **Console during plan**: "[edits] plan '<name>': N cut(s) -- K kept, M moved, T trimmed, W new, R removed (P pinned to their items, S shift)[, F faded][ (banked to '<OffCuts>')][ -- NO-OP]".
- **Console during apply**: "[edits] gate: library '<l>' allowed, project '<p>' closed; timeline '<t>' N item(s) -> M cut(s)", a line per table with +/-/~ counts, "[edits] verified: ...", "[edits] committed '<t>': N row(s) -- ... in T s; backup <path>".
- **Apply reports**: the summary, timeline id and name, cut count, item count before, length in frames and seconds, OffCuts id and name, marker note, no-op flag, rows written, backup path, the ids of banked pieces, dry-run flag and time taken.

## Editing in place: command line (`library-edits`)
(source: library_edits.py)

- `py -3.12 pipeline.py library-edits plan <library> <project> <timeline> <cuts.json> [--host H] [--offcuts NAME] [--no-bank] [--markers <marks.json>]`
- `py -3.12 pipeline.py library-edits apply <library> <project> <timeline> <cuts.json> --allow <library> [--dry-run] [--allow-open] [--markers <marks.json>] [--offcuts NAME] [--no-bank] [--host H]`
- `py -3.12 pipeline.py library-edits undo <backup.json> --allow <library> [--host H]`
- `<timeline>` is a timeline name in that project, or a timeline id (anything 36 characters long with four hyphens is taken as an id without checking). An unknown name prints "[edits] no timeline '<t>' in <l> / <p>" and exits 1.
- `<cuts.json>` as for the writer; `--markers` replaces the file's markers (and triggers the markers defect above).
- Output: the plan, apply result or undo result as indented JSON (internal fields left out); exit 0.
- Refusals: "[edits] REFUSED: <message>", exit 1. Usage errors: usage text, exit 2. Other errors: Python error trace.

## The limits of what these tools understand, in one place
(source: library_reader.py, library_writer.py, library_edits.py)

- **Timelines**: read: V1 only for cuts, A1 only for fades. Conform: builds V1 + A1 only. In-place edit: only timelines whose items are all on one video track, with every item linked to an audio item on one audio track, equal counts on both.
- **Clips**: anything with a linked video+audio item already somewhere in the project can be conformed; a clip that has never been on a timeline there cannot. Audio-only clips cannot be conformed (a video item of the clip is required). End-of-clip check only for multicam and compound clips.
- **Multicam**: the angle of a conformed or inserted cut is inherited from an existing item of that clip; it cannot be chosen. Reading a multicam gives its angles' video tracks only.
- **Transitions**: none are read or written. Nothing in the code handles transitions.
- **Speed changes**: detected (flag only) when reading a sequence's video; copied unchanged onto new items from their clone source; never decoded or written deliberately.
- **Fades**: audio fades only, on the audio item, in whole timeline frames. Video fades: never read or written.
- **Grades and effects**: kept on items an in-place edit keeps, moves or trims; dropped on every newly created item (conform and inserts), apart from the audio fade.
- **Markers**: timeline markers only; per-item markers are cleared on new items; one per frame; `customData` lost; marker colour mapping unverified.
- **Clip colours**: 16 names, half of them inferred.
- **Frame rates**: any rate strictly between 1 and 1000 frames per second; drop frame understood for 29.97 and 59.94 families; mixed clip and timeline rates handled by rate conversion with rounding to whole frames.
- **What a person sees on something not understood**: a refusal sentence (writer and editor, prefixed REFUSED, exit 1); a Python error trace for undecodable records hit outside a gate (for example a sequence whose frame rate does not decode while choosing a template); and, in reading, silent fallbacks: unknown colour or fade reads as none, an unreadable marker record reads as "unknown", items with undecodable rates are skipped when reading a sequence's video.

## The backup file kept in the source folder
(source: library/library_backups/20260916T054807Z-FF5-conform-b3e2ee47.json)

- One undo file sits in the tools' default backup folder inside the source tree: the conform of "Reproductive Rights - Ordered V7" (335 cuts) into the real library `FF5`, project "Reproductive Rights Fight", made 2026-09-16 05:48 UTC against host 192.168.0.102.
- It records a save-counter value of 665,525,076,087, while the bin counter it replaced was 14,145. This is the outlier situation the writer's counter logic now guards against.
- It is the input `library-edits undo <file> --allow FF5` (or a program's restore) would need to take that timeline back out. Nothing in these files runs it automatically.
- Read: the header, the first entries and the "updated" block at the end; the middle (about 11,700 lines) is the list of created row keys and was not read line by line.

---

# Part 2: interview preparation (the canvas-sorter instruction file)

This part is an instruction file that an AI assistant (Claude Code) follows step by step. It is treated here as the program it effectively is. It has two halves, kept apart below: preparing the TRANSCRIPT, then building the planning CANVAS. Statements about what the helper scripts do are what the instruction file tells the assistant; those scripts belong to other sections, and only the few places checked against them are marked as checked.

## How the instructions are started, and the four ways they run
(source: skills/canvas-sorter/SKILL.md)

- **Trigger**: the assistant loads these instructions when a person asks to prep or paragraph interview transcripts, build a planning canvas, sort or theme transcripts, recreate a "Canvas Reference", or mentions theme proposals or the Canvas Theme Picker.
- **Interactive mode** (a person asked in chat): all steps in order; Step 0 is skipped for interviewees who already have a prepped transcript; Step 3 uses a background watcher to wait for the person's theme choice. If the person did not name an episode, the assistant must ask which one.
- **Launcher-driven mode**: headless runs (`claude -p`) started by the Theme Picker web page, one per phase, each possibly on a different AI model. The prompt names the phase:
  - **PREP phase**: Step 0 only, for the interviewees named in the prompt.
  - **PROPOSE phase**: Steps 1 and 2; write the proposal file to the exact path given, then stop. No watcher, no assigning.
  - **ASSIGN phase** (the launcher calls it "build"): Step 4 only. The prompt names a proposal file whose selection is already filled in and the exact path for the assignments file. Write it and stop; do NOT run the canvas builder, because the launcher runs it itself as soon as the assistant exits.
- **How helper scripts are run**: `py -3.12 <script>` (falling back to `python`), every script taken from `E:\Projects\Editing\Resolve\MulticamPipeline\` (called `<PIPE>` in the instructions). Checked: each named script exists there as a small forwarding file that runs the real script inside the pipeline package.
- **Reference examples the output must look like**: transcripts like `X:\Vault\2025\FF4\Garbage\Interviewees\Anbo\Anbo_Transcript.md`; canvases like `X:\Vault\2025\FF4\Garbage\Script Docs\Garbage Canvas Reference.canvas` (and the Erosion episode's equivalents).

## TRANSCRIPT: what it needs from outside itself
(source: skills/canvas-sorter/SKILL.md)

- An **episode folder** in an Obsidian notes vault, for example `X:\Vault\2025\FF4\Garbage`, containing `Interviewees\<Name>\` folders, one per interviewee.
- Each interviewee folder holds one of:
  - a **prepped transcript**: a Markdown file whose blocks end in `^xxxxxx` block references. Its name varies (`Anbo_Transcript.md`, `<Chinese name> <romanised name>.md`); it is recognised by having references, not by its name;
  - only a **raw transcript** Markdown file: a run-on automatic transcription with `(...)` markers, usually in simplified Chinese, with the interviewer's questions buried inline. This needs Step 0;
  - an older `*(paragraphs).canvas` file (older episodes), usable as it is.
- A **work folder** for drafts: `E:\Projects\Editing\Transcripts\canvas-theme-picker\work\`.
- For the optional coverage check: a subtitle (SRT) export of Resolve's transcription, and optionally an audio-only render of the same timeline.

## TRANSCRIPT step 0a: check that Resolve's transcription is complete
(source: skills/canvas-sorter/SKILL.md)

- **Why**: Resolve's transcription can silently drop a section (a cut-off tail, or a passage in the middle) with no error and no visible seam.
- **Person's action**: export the transcription as subtitles (SRT) as well as text.
- **Basic check**: `py -3.12 <PIPE>\check_transcript_coverage.py --srt "<export.srt>"`. Per the instructions it needs only the SRT; it flags any stretch with no subtitle that is an outlier against that file's own median gap between subtitles (no fixed threshold), and prints subtitle density per minute so a thinned stretch shows up.
- **Tail check**: add `--duration <timeline length>`; it compares the last subtitle with that length, which is how a truncated end shows.
- **Media check**: add `--media "<audio render>"`. Must be an audio-only render (Deliver, Audio Only) of the SAME timeline the subtitles came from, never a source clip, because subtitle times are in timeline time. The script checks the time bases agree and refuses to run if they do not. The timeline start timecode (usually 01:00:00:00) is detected automatically; `--offset` overrides it. With media it runs voice detection to tell real skips from genuine pauses.
- **Recovery**: `--recover --lang zh` (with `--media`) re-transcribes only the confirmed missing windows with faster-whisper and prints the missing text.
- **Result**: exit code 1 means something is missing.
- The instructions do not say what the assistant should do with the recovered text, and do not make the check a condition for Step 0.

## TRANSCRIPT step 0: write the paragraphed draft
(source: skills/canvas-sorter/SKILL.md)

- Done for each interviewee without a prepped transcript.
- **Reads**: the raw transcript `.md`.
- **Writes**: a draft at `work\<Episode>_<Name>_draft.md` (the work folder above). Long transcripts are written in appended pieces so nothing is cut off.
- **Paragraph rules**:
  - One interviewer question per block.
  - One coherent answer point per block. Text split by `(...)` markers is merged: the markers are dropped and the pieces joined with a space.
  - Off-topic chatter (sound checks, a door closing, translation logistics) goes in its own small blocks.
  - Target granularity: like the Anbo reference, about 1 to 6 sentences per block.
  - **Length cap**: aim for about 20 seconds of speech per block (about 90 Mandarin characters or 50 English words); never more than 60 seconds. A long answer must be split even if it is one point, at its own internal turns (a new example, a move from problem to solution, a "but", a change of subject).
  - Splitting must happen in the draft, before references are added: once a block has a reference, splitting it changes the reference and orphans its place on any canvas.
- **Question marking**: every line of an interviewer-question block starts with `# ` (hash and space), in both languages.
- **Translation layout** (Mandarin interviews): the English translation line(s) first, then the original Mandarin verbatim (without the `(...)` markers) as a single line. Simplified or traditional characters are kept exactly as they are; no conversion. English interviews stay English only.
- **Never correct the original-language line**: it must be character for character what the raw transcript says, including mishearings (for example a misheard 河三 stays 河三 even when 核三 was meant); the same for misheard names and terms in English interviews. Reason given: later tools (Timeline Cards, the canvas timeline tools) find each block in Resolve's word stream by exact text match, so one corrected character breaks that block's timing. Corrections go only in the translation line.
- One blank line between blocks. No block references in the draft.
- The assistant translates itself; it must not hand translation to sub-assistants.

## TRANSCRIPT step 0: finalize (add references)
(source: skills/canvas-sorter/SKILL.md; checked against transcripts/finalize_transcript.py where marked)

- **Command**: `py -3.12 <PIPE>\finalize_transcript.py <draft> "<interviewee folder>\<raw file name without extension>_Transcript.md"`.
- **Writes**: the final transcript beside the raw one, named `<raw stem>_Transcript.md`, with a unique block reference added to every block. (Checked: references are 6 characters; references already in the draft are kept.)
- **Refusals**:
  - it refuses to overwrite an existing final transcript (checked: "ERROR: <path> already exists - refusing to overwrite."; the script's own header mentions an exception for a file it generated itself, not read further here);
  - it estimates spoken duration per block and refuses any draft with a block over 60 seconds (checked: the 60-second limit, a `--max-seconds N` option to change it and `--allow-long` to override). The instructions tell the assistant to split long answers rather than use `--allow-long`.

## TRANSCRIPT step 0: spot-check and report
(source: skills/canvas-sorter/SKILL.md)

- Block count should roughly follow the raw content's natural question-and-answer rhythm. A well-paragraphed interview of about an hour comes out at 60 to 200 blocks, median block about 10 to 30 seconds of tape. Far fewer means under-splitting: go back and split.
- **Reports**: per-interviewee block counts.

---

## CANVAS: what it needs from outside itself
(source: skills/canvas-sorter/SKILL.md)

- Prepped transcripts (with references) in the episode's `Interviewees\<Name>\` folders, or legacy paragraph canvases.
- The Theme Picker's two folders: proposals `E:\Projects\Editing\Transcripts\canvas-theme-picker\proposals\` and work files `E:\Projects\Editing\Transcripts\canvas-theme-picker\work\`. These are a shared contract with the Theme Picker web page. Later phases may run in a different session, so files go there, never in a temporary scratch folder.
- The episode's `Script Docs\` folder for the output canvas.
- The Editing Launcher, with a "Multicam Pipeline" card in the "Resolve - Media & Projects" group (the real label uses a long dash; checked: the card exists in the launcher's tool list), for the person to pick themes.
- Obsidian, to open and arrange the canvas afterwards.

## CANVAS step 1: extract every paragraph
(source: skills/canvas-sorter/SKILL.md)

- **Command**: `py -3.12 <PIPE>\extract_paragraphs.py <episode folder> "E:\Projects\Editing\Transcripts\canvas-theme-picker\work\<Episode>_paragraphs.jsonl"`.
- **What it does** (per the instructions): takes every referenced block from each interviewee's transcript (falling back to a legacy canvas), builds each card's text with a source link of the form `_Source: [[...#^ref|...]]_`, and estimates each card's height from its text.
- Only the ONE Markdown file with the most references in each interviewee folder is read; a second transcript file in the same folder is ignored.
- **Reports**: any interviewee that still "needs prep".

## CANVAS step 2: propose themes
(source: skills/canvas-sorter/SKILL.md)

- **Reads**: the paragraphs file, in pieces if large (episodes run 300 to 700 paragraphs). No paragraph is assigned in this step.
- **At most 25 themes** (a hard ceiling; fewer is fine). Two are always present: **Personal Stories** (how each contributor came to this, who they are) and **Ending** (the closing beat: what it was all for, the next generation, where this leaves us). So at most 23 come from the content.
- **Rules for a theme**:
  - Broad containers, not narrow topics; the test is how much of the episode fits in it.
  - If two candidates would draw on the same passages, they are one theme.
  - Each should plausibly hold 20 or more paragraphs from 2 or more interviewees; less is a detail inside a bigger theme.
  - 80 or more paragraphs suggests two stories under one label: look for the seam and propose two. (The instructions also say a theme of 100 or more is almost always two or three stories.)
  - A large single-interviewee story (a campaign, a place, an event) is a valid theme if substantial enough to carry a section.
  - Short, punchy labels.
  - Sanity check: if every paragraph were assigned now, most should land somewhere; if many would not, merge and retry.
- **Order**: strongest first (most supporting paragraphs, then most interviewees), with honest evidence counts. This order is only for choosing; it is not the canvas order.
- **Writes**: the proposal file `proposals\<Episode>.json` (or the exact path a PROPOSE prompt gives), containing: `episode`, `created` (date), `episode_dir`, `paragraphs_jsonl` (the step 1 path), `output_canvas` (for example `<episode>\Script Docs\<Episode> Canvas.canvas`), `target_count` (the example shows 18; the instructions give no rule for choosing it), `themes` (each with `name`, a one-or-two-sentence `description`, and `evidence` such as "5 interviewees, ~25 paragraphs (names...)"), and `selected: null`.
- `selected: null` means "waiting for the person". The assistant must never fill in `selected`. A `model` field the page may add is ignored.

## CANVAS step 3: wait for the person's choice (interactive mode only)
(source: skills/canvas-sorter/SKILL.md)

- **Tells the person**: open the Editing Launcher, the "Resolve - Media & Projects" group, the Multicam Pipeline card; pick themes (about `target_count`, any number allowed, names editable there) and press Save.
- **Starts in the background**: `py -3.12 <PIPE>\wait_for_selection.py "<proposals folder>\<Episode>.json"`, which notifies the assistant when the selection is saved.
- If saving in the picker also starts its own headless build and the launcher's job panel already shows a build, the assistant must not build a second time; it checks whether the output canvas has appeared.

## CANVAS step 4: assign every paragraph to a theme
(source: skills/canvas-sorter/SKILL.md)

- **Reads**: the proposal's `selected` list, entries of the form `{"original": <proposed name>, "name": <possibly renamed>}`; material is matched against `original`, and `name` goes on the canvas. Entries may carry `"custom": true` and a `description`: themes the person typed in. They are treated exactly like proposed themes and matched against the person's description (or, if that is thin or empty, the name). Then re-reads the paragraphs file.
- **Rules**:
  - Every paragraph goes to exactly one theme; none twice, none thrown away. If it fits two, the single most relevant.
  - Each paragraph's `key` is copied verbatim from the paragraphs file (keys are derived from interviewee and reference, so they cannot be guessed or renumbered).
  - Place aggressively: a serviceable home beats a leftover.
  - Interviewer questions (marked `"question": true`) go in the same theme as the answer they set up, directly above it. Only a question that sets nothing up ("Could you repeat that?", "Shall we start again?", "Do you want some water?") goes to Uncategorised. (Stated as a deliberate departure from the reference canvases, which dropped questions.)
  - **Uncategorised** is for non-content only: sound checks, door noise, filming and scheduling logistics, restarts, goodbyes. Listing those keys under Uncategorised or leaving them out gives the same result.
  - Judge on substance, from either language.
  - Within a theme, order keys as a story (setup, detail, punchline), not transcript order. The builder keeps this order within each interviewee column.
  - Each theme gets a `role`: `personal` (opening), `ending` (closing), or `body`/none. Body themes are listed in the order a viewer should meet them (context before consequence, problem before response, specific case before what it means), never by size. "Personal Stories" and "Ending" get their role from their names if `role` is left off.
- **Writes**: `work\<Episode>_assignments.json` (or the path the ASSIGN prompt gives): `{"themes": [{"name", "role", "keys": [...]}]}`.
- **Reports**: the Uncategorised count, saying so plainly if it exceeds 10% of the episode; and why the middle themes run in the chosen order.

## CANVAS step 5: build the canvas (interactive mode only)
(source: skills/canvas-sorter/SKILL.md; spot-checked against canvas/build_canvas.py and canvas/reflow_grid.py)

- **Command**: `py -3.12 <PIPE>\build_canvas.py <paragraphs file> <assignments file> "<output_canvas from the proposal>"`. In launcher-driven runs the launcher runs this, not the assistant.
- Never overwrite a canvas whose name ends in ` Reference.canvas`.
- **Layout (per the instructions)**: one group per theme, all groups in a single left-to-right row; one column per interviewee inside a group, wrapping to more columns so no column is more than 10 cards tall; cards recoloured with a fixed per-interviewee palette. Groups are written in the assignment order, banded personal first, then body, then ending, with Uncategorised pinned last; never re-sorted within a band. (Checked: the builder's column height comes from a grid setting whose default is 8 cards, not 10, and the card width is 600 pixels.)
- **Coverage**: a paragraph listed twice keeps its first placement; leftovers are swept into a final Uncategorised group; the builder prints a `coverage:` line, which the assistant must check reads N/N with no MISMATCH.
- **Reports to the person**: themes built, paragraphs placed versus swept into Uncategorised, the coverage line, the colour-to-interviewee legend the builder prints, the output path; and that groups can be dragged freely in Obsidian, heights are estimates, and running the Obsidian fit-height script afterwards is optional.

## CANVAS step 6: add a later interview to a canvas already in use
(source: skills/canvas-sorter/SKILL.md)

- Never re-run the builder on a canvas being worked on: it rebuilds from scratch and discards the layout.
- The new interview is prepped with Step 0 first (it needs references).
- **Commands**: `py -3.12 <PIPE>\add_to_canvas.py "<folder>\<Name>_Transcript.md" "<canvas>" --group "<group label>"` (all cards into one group), or `... --assign assign.json` where the file is `{"<group label>": ["ref", ...]}` (split across groups; anything not listed is not placed, with no Uncategorised sweep).
- **Options**: `--skip ref1,ref2` leaves out chatter blocks; `--dry-run` previews.
- **What it does (per the instructions)**: appends the cards as new 600-pixel columns on the right of the target group, widens the group, shifts the rest of the row so nothing overlaps; reuses the interviewee's existing colour on that canvas (an interviewee is identified by the `Interviewees/<Name>/` folder, so `Brian Online.md` matches `Brian_Transcript.md`); skips references already on the canvas so re-runs are safe; keeps the canvas file's JSON formatting; writes a timestamped `.bak` copy; refuses to write if its own overlap or containment check fails.
- Caveat stated: a second transcript file in the same interviewee folder is invisible to a later full re-extract (Step 1 reads only the file with the most references), so a full rebuild would lose it.

## CANVAS: which AI model for which headless phase
(source: skills/canvas-sorter/SKILL.md)

- The Theme Picker lets each phase use its own model. Suggested defaults:
  - PREP (paragraphing and translation): Sonnet 5; Haiku 4.5 only for a rough throwaway pass.
  - PROPOSE: Fable 5 (or Opus 4.8).
  - BUILD/ASSIGN (about 500 paragraphs into about 12 themes, plus story ordering): Opus 4.8; Sonnet 5 acceptable; Fable 5 if the story order really matters.

---

# Part 3: the standalone Timeline Cards container for the NAS (`deploy\`)

What it installs: a Docker container named `timeline-cards` on the TrueNAS NAS (192.168.0.102), running the Timeline Cards web page server (the "library half", without the Resolve keystroke engine, which stays on the editing PC as an agent) on port 8800, published on the NAS's LAN and tailnet addresses. Its files on the NAS go under `/mnt/tank/apps/timeline-cards`.

## The install helper (`install_nas.py`)
(source: deploy/install_nas.py)

- Python standard library only; uses the system's OpenSSH `ssh` and `scp`.
- **Three modes**:
  - `python deploy/install_nas.py` (default, dry run): touches no network. Reads the site file, fills in the compose template, checks it, prints a summary and the finished YAML, and ends with "Dry run. --check tests SSH; --apply copies the tree. Neither installs anything."
  - `--check`: also tests that the NAS answers SSH (runs `true` there; changes nothing). Prints "[ssh] reachable" or "[ssh] FAILED (exit N)".
  - `--apply`: also copies the code and the rendered compose to the NAS, then prints the manual install steps. Nothing is ever built, installed, started or stopped by the script.
  - `--site <file>`: the site file; default `deploy/site.toml`. If it is missing, the dry run (only) falls back to `site.example.toml` and says "[site] <path> does not exist -- rendering the EXAMPLE instead. Copy it to site.toml and edit before installing." With `--check` or `--apply` a missing site file is "no such site file: <path> (copy site.example.toml)", exit 1.
- **Values it fills in** (from the site file sections `[nas]`, `[vault]`, `[net]`, `[app]`, `[db]`, `[media]`, `[fleet]`, `[claude]`):
  - image tag (default `timeline-cards:1`), the app's folder on the NAS, the vault's host path, the episode folder as the container sees it, port (default 8800), LAN and tailnet bind addresses, user id (default 3000) and group id (default 3001), time zone (default `Asia/Taipei`), browser key, agent token, an optional cut-list project file, database host and library name, the list of libraries the container may write (joined with commas; empty = no writing), backup folder, footage share host path and its path translation, fleet dashboard URL, user, password and path roots, Claude OAuth token and Anthropic API key.
  - The agent token comes from the `CARDS_TOKEN` environment variable first, then the site file. The fleet password and both Claude credentials also come from their environment variables first (`CARDS_FLEET_PASSWORD`, `CARDS_CLAUDE_OAUTH_TOKEN`, `CARDS_ANTHROPIC_API_KEY`).
  - With no token anywhere it renders `REPLACE_ME` and prints "[token] CARDS_TOKEN is not in the environment and site.toml has none: rendering REPLACE_ME. Export it before --apply." This does NOT stop `--apply`; the rendered file then carries `REPLACE_ME`.
  - A `[whisper] hf_token` key present in the real site file is not read by this script.
- **Template filling rules**: only `${NAME}`, `${NAME:-default}` and `${NAME:?message}`; comment lines are left alone. An empty `${NAME:?message}` is a problem named with its message; an empty bare `${NAME}` is a problem "NAME: no value in site.toml". A port line whose address came out empty is dropped entirely (so a blank address never publishes on every interface). One missing bind address is a warning ("[compose] no CARDS_BIND_LAN -- that ports line is dropped"); both missing is a problem ("... (BOTH: nothing can reach this app)").
- **Note on defaults**: because blank values fall back to the template's defaults, a blank database host renders as `192.168.0.102` and a blank library name as `FF5`.
- **Checks it prints**:
  - "[compose] NOT DOCUMENTED in the header: <names>" for any variable used in the body that the template's header comment does not mention.
  - "[compose] unset variable -- <problem>".
  - A shape check of the rendered YAML with a tiny built-in reader (even indentation, mappings and lists only): exactly a `timeline-cards` service with image, user, environment, ports, volumes, restart, healthcheck and logging; restart `unless-stopped`; at least one port, each of the form address:port:port; a read-write `/vault` mount; a `/data` volume; a non-empty token. Success: "[compose] shape ok: one service, N published address(es), /vault rw, /data, healthcheck, restart unless-stopped"; failure: "[compose] BAD: <why>".
  - "[vendor] ...": whether the copy of the shared theme file `webtheme.py` at the repository root matches the original in `E:\Projects\Editing\Launcher\webtheme.py` (line endings ignored): "matches", "STALE: ... copy it again before building", "MISSING: ...", or "present (the Launcher original is not on this machine, so it was not compared)".
  - Every value, with secrets (token, browser key, fleet password, both Claude credentials) shown as "set (N chars, ...<last 4 characters>)" or "(unset)".
  - Any problem with `--check` or `--apply`: "[stop] fix the problems above first.", exit 1.
- **Host key gate** (for `--check` and `--apply`): the NAS's SSH key must already be in `~/.ssh/known_hosts` (plain or hashed entries; `@cert-authority` and `@revoked` lines ignored; `host` or `[host]:22` accepted) AND equal the key pinned in the site file's `[nas] ssh_hostkey`. Refusals: "no entry for <host> in ~/.ssh/known_hosts. Connect once by hand (ssh <host>) with the fingerprint from the TrueNAS console in front of you, then re-run."; "site.toml has no [nas] ssh_hostkey to match known_hosts against -- copy it from ccsync's site.toml or from the NAS console."; "the key in known_hosts for <host> is NOT the one site.toml pins. Somebody re-imaged the NAS -- or is answering for it. Do not re-trust it from here." There is no flag to trust a new key.
- **SSH settings**: batch mode (no prompts), strict host key checking, 10-second connect timeout, user from `[nas] admin_user` (default `root`).
- **What `--apply` copies**:
  - refuses if `ssh` or `scp` is not on the PATH ("[apply] ssh/scp not on PATH (Windows: the OpenSSH client optional feature)") or `[nas] apps_root` is empty;
  - creates `<apps_root>/src/deploy` and `<apps_root>/data` on the NAS;
  - copies `reorder_web.py`, `requirements.txt`, `webtheme.py` and the whole `multicam_pipeline` folder into `<apps_root>/src/`, and `Dockerfile`, `run.sh`, `compose.yaml`, `README.md` into `<apps_root>/src/deploy/`;
  - writes the rendered YAML to `<apps_root>/compose.rendered.yaml`;
  - on failure: "[apply] could not create ..." or "[apply] failed (exit N) -- nothing was installed"; on success "[apply] tree copied."
- **Manual steps it prints after `--apply`** (also printed when `--check` failed and the copy was skipped): build the image over SSH (`cd <apps_root>/src && docker build -f deploy/Dockerfile -t <image> .`); `chown -R <uid>:<gid> <apps_root>/data`; check the vault folder and episode exist; in the TrueNAS web interface use Apps, Discover Apps, Custom App, Install via YAML, paste the rendered YAML, name the app `timeline-cards`; open the page URL (`[net] url`, or `http://<tailnet bind>:<port>/`) and start the agent on the editing PC, whose `cards_agent.json` must carry the same token.

## The app definition (`compose.yaml`)
(source: deploy/compose.yaml)

- A template with `${CARDS_...}` placeholders, documented in its header; meant to be filled by `install_nas.py` because TrueNAS's "Install via YAML" does no substitution and cannot build images.
- One service and container, both `timeline-cards`; image `${CARDS_IMAGE}` (default `timeline-cards:1`), built on the NAS, never pulled from a registry.
- Runs as `${CARDS_UID}:${CARDS_GID}` (default 3000:3001).
- Environment passed to the container: port (default 8800), episode root (default `/vault`), agent token (REQUIRED: the app refuses to start without it, message "set CARDS_TOKEN -- the agent secret, same value as creator-1's cards_agent.json"), browser key (blank = no gate), time zone, project file, database host (default `192.168.0.102`), library name (default `FF5`), write allowlist (default blank = no writing), backup folder, footage path translation, the four fleet values, and the two Claude credentials.
- Published ports: the LAN address and the tailnet address, each port to the same port. Nothing else.
- Storage: the vault host path at `/vault` read-write; `<apps_root>/data` at `/data` read-write; the footage share at `/media` read-only.
- Restart policy `unless-stopped`.
- Health check every 60 seconds (timeout 10 s, 3 retries, 60 s start grace): fetches `http://127.0.0.1:<port>/api/state?v=-1` with an 8-second timeout and is healthy only if the reply is JSON containing `version`. It does not care whether the Resolve agent is connected.
- Log cap: Docker's json-file driver, 20 MB per file, 5 files.

## The image recipe (`Dockerfile`)
(source: deploy/Dockerfile)

- Base image `python:3.12-slim`, not pinned to a digest.
- A build stage on `node:22-bookworm-slim` installs `@anthropic-ai/claude-code` version 2.1.251 with npm (needs internet at build time); only the `node` program and the installed package are copied into the final image, and `claude` is linked into `/usr/local/bin`. The build fails if `node --version` or `claude --version` fails.
- Installs `ffmpeg` and `libpq5` from Debian, then the Python packages in the repository's `requirements.txt`.
- Copies `reorder_web.py`, the whole `multicam_pipeline` folder, `webtheme.py` and `deploy/run.sh` into `/app`. The keystroke script `ripple_keys.ahk` and the top-level forwarding scripts are not copied.
- Converts `run.sh` line endings from Windows to Unix and checks its syntax at build time.
- Makes `/app` readable by everyone and writable by no one at run time.
- Creates user `cards` (uid 3000, group 3001) and runs as 3000:3001 unless overridden.
- Environment: `HOME=/data`, `CARDS_DATA=/data`, `CLAUDE_BIN=/usr/local/bin/claude`, unbuffered Python output, no bytecode files.
- Declares port 8800; same health check as the compose file; starts `/bin/sh /app/deploy/run.sh`.
- Consequences stated in its comments and the runbook: the page's own restart button and the saving of the root-folder choice cannot work in this container (read-only `/app`); restart the app from TrueNAS instead.

## The container start script (`run.sh`)
(source: deploy/run.sh)

- Turns environment variables into the server's command line `python /app/reorder_web.py <port> --remote-agent --token <token> --host all --no-browser --root <root>` plus optional flags, and runs it. Every message starts with `[cards]`.
- **Stops the container (exit 1)** when:
  - no `CARDS_TOKEN`: "CARDS_TOKEN is not set. It is the shared secret between this server and creator-1's agent (cards_agent.json). Generate one with: openssl rand -hex 24 -- and put the SAME value in both.";
  - the root folder does not exist: "--root <root> does not exist in the container. Check the vault bind mount ...";
  - `CARDS_PROJECT` is set but is not a file: "CARDS_PROJECT=<path> is not a file in the container. ...";
  - `CARDS_DB_WRITE_ALLOW` is set but `CARDS_DB_HOST` is not: "CARDS_DB_WRITE_ALLOW is set but CARDS_DB_HOST is not: there is no library to write. Set both, or neither."
- **Warns and carries on** when: the root is not writable ("WARNING: <root> is not writable by uid U:G ..."); a footage path translation is set but `/media` is not mounted; the fleet URL is set but user, password or roots is missing (then derived media is made locally).
- **Adds flags**: `--project` (with two explanatory lines), `--db-host` and `--db-name` (prints "project library: <name or <first one>> on <host>", or "no CARDS_DB_HOST: cards come only from the agent's pushes."), `--db-write-allow` and `--db-backups` (prints "library conform ON for: <list>" and the backup folder, default `/data/library_backups`; or "no CARDS_DB_WRITE_ALLOW: conform goes through the agent only."), `--media-map`, `--fleet-url/--fleet-user/--fleet-password/--fleet-roots` (all four or none), `--key` ("browser key set: open the page once as ?key=... per device." or "no CARDS_KEY: every device that can reach this port gets the page (and the page drives Resolve through the agent).").
- **Reports which Claude credential is in force** (never refuses): no CLI found; OAuth token; API key; an interactive login file under `/data/.claude` (marked unverified); or none ("translate, semantic search and summaries will fail on the first call").
- Final line: "serving <root> on :<port> (library half; Resolve is on the agent)".
- The agent token and fleet password are passed on the server's command line inside the container.

## The site files, the runbook and the ignore file
(source: deploy/site.toml, deploy/site.example.toml, deploy/site.example.toml.orig, deploy/README.md, deploy/.gitignore)

- `site.example.toml`: the committed example of the site answers, with comments; `write_allow` empty; secrets blank.
- `site.toml`: this site's real answers; excluded from git by `.gitignore` (which also excludes `compose.rendered.yaml`). It currently records image tag `timeline-cards:74`, uid:gid 3003:3000, vault `/mnt/tank/web` with episode `/vault/Vault/2026/FF5/Civil Defence`, footage `/mnt/tank/TheCreatorsPool/Creators_Club` mapped from `P:/`, database host 192.168.0.102 library `FF5`, write allowlist `FF5lab`. It also holds, in plain text, a browser key, a Claude OAuth token and a Hugging Face token (values not repeated here), despite the example's instruction to keep credentials out of the file.
- `site.example.toml.orig`: an older copy of the example (no project, fleet or Claude sections; write allowlist `FF5lab`). Nothing reads it.
- `README.md`: the runbook (prerequisites, first install, the SSH route used on 2026-08-27, upgrading by building a new image tag and updating the app, rolling back by pointing at the previous tag, the optional fleet). Documentation only; it runs nothing.

## Is any of this still used
(source: deploy/*, Launcher/tools.json, cards_agent.json, grep of E:\Projects\Editing)

- The Editing Launcher still has a "Timeline Cards (NAS)" card that simply redirects the browser to `http://truenas.tail26290e.ts.net:8800/`, the address this container serves.
- The editing PC's `cards_agent.json` still names `http://truenas.tail26290e.ts.net:8800/` as the server the Resolve agent connects to.
- The real `site.toml` names image tag 74, so the container was rebuilt many times through this route.
- Nothing in the CC Sync repository's code refers to these files: the CC Sync dashboard's own `/cards` mount ships Timeline Cards by a different route (outside this section).
- Whether the `timeline-cards` container is still running on the NAS today could not be determined from the files (it would require asking the NAS).

---

## Looks redundant or overlapping

- Three copies of the rule "where does each cut land" (the writer's planner, the in-place editor reusing it, and, per comments, the Resolve keystroke engine's conform in the cards section). The library conform exists to produce the same result as the keystroke conform by another route.
- Two ways to conform a cut list into Resolve: through Resolve's own scripting and keystrokes (other sections) and straight into the library (this section). The straight-in route is now refused for every real library, leaving only the sandbox `FF5lab` writable.
- Two kinds of in-place editing: the keystroke engine (other sections) and `library_edits` (this section), whose OffCuts banking deliberately reproduces the keystroke engine's.
- Three nearly identical "renumber order numbers through a large offset" routines (writer delete, writer restore, editor re-rank).
- Two marker decoders in the reader and writer (a friendly one and an exact one) and two blob-unframing routines (the reader's small one and the writer's full one).
- Several near-identical "find the V1/A1 track" queries across reader, writer and editor.
- The reader's "connection kept open forever" pool and the writer's "fresh connection per call" are two connection styles for the same database.
- The `deploy\` container duplicates what the CC Sync dashboard's `/cards` mount provides (Timeline Cards served from the NAS), with its own install script, secrets handling, health check and runbook.
- `site.example.toml.orig` duplicates `site.example.toml` (older and unused).
- The root-level forwarding scripts for the canvas-sorter instructions duplicate the package entry points (`pipeline.py <name>` also reaches them).
- The demonstration command of the reader (`library-reader`) is a debugging listing that overlaps the Timeline Cards page's own picker.

## Claims the code does not back

- `library_edits.py` says markers passed to an in-place edit are rewritten; in the code, passing any markers makes plan and apply fail with "too many values to unpack" before writing anything (the marker planner returns three values, the editor expects two).
- `library_edits.py` says `LibraryWriter.restore` re-inserts deleted rows "through the new `_insert_rows`"; there is no such function; it uses the ordinary row insert.
- `library_edits.py` says a split's new half is cloned "from its surviving sibling"; the code clones from the FIRST existing item of the same clip on the timeline, which need not be the sibling.
- `library_writer.py`'s header lists "every cut's source span is ... inside the clip's extent where clip_facts knows it"; the end check uses the clip's sequence extent and only exists for multicam and compound clips, not for plain files whose rate clip_facts knows.
- The in-place editor accepts a cut's `color` and checks it, but never writes it; nothing in the docstring says colour is ignored in place.
- `library_writer.py` says the writer's backup folder holds backups that "restore()/delete_timeline() can undo exactly"; a conform backup cannot be restored while the project is open (delete refuses without the override, and restore does not pass one), and an edit restore performs no open-project check at all.
- `site.example.toml` and the compose header say a blank database host means "agent-only cards"; when rendered through `install_nas.py`, a blank host is replaced by the template's default `192.168.0.102` (and a blank library name by `FF5`).
- `deploy/README.md` says the Dockerfile copies "the six Python files"; it copies `reorder_web.py`, the whole package and `webtheme.py`. It also says to `chown -R 3000:3001` the data folder, while the script's printed steps use the site's uid:gid (3003:3000 on this site).
- The `Dockerfile`'s comments say `deploy/vendor/` carries the theme file copy; it is copied from the repository root.
- `site.example.toml` tells the user to keep the token and Claude credentials out of the file; the real `site.toml` contains a Claude OAuth token and a Hugging Face token in plain text.
- The canvas-sorter instructions say the canvas builder wraps columns at 10 cards; the builder's column height comes from a grid setting whose default is 8.

## Could not determine

- Whether the `timeline-cards` container in `deploy\` is still installed and running on the NAS, and whether anyone still uses the Launcher's "Timeline Cards (NAS)" card.
- Whether any caller passes markers to the in-place editor (the Timeline Cards agent calls `apply` with a markers argument; whether it is ever not empty was not followed into the cards section).
- Whether the eight inferred clip-colour names and the marker colour order match Resolve; the code itself says they are unverified.
- What `check_transcript_coverage.py`, `extract_paragraphs.py`, `wait_for_selection.py` and `add_to_canvas.py` actually do beyond their existence: those scripts belong to other sections; only the finalizer's 60-second limit, overwrite refusal and 6-character references, and the builder's 8-card column default and 600-pixel width were spot-checked.
- The exception in `finalize_transcript.py` for overwriting a file it generated itself (mentioned in its header, not read).
- Whether the backup file in `library/library_backups/` was ever used to undo the FF5 conform it records.
- Which exact Resolve versions the library layout knowledge holds for; the code cites Resolve 21.0.1 only.
