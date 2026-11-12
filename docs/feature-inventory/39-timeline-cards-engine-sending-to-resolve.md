# Timeline Cards, the engine: sending a cut to Resolve, reading it back, and the cut-list rules

Terms used throughout this section:

- **Cut**: one piece of interview footage on a timeline, defined by a media
  pool clip (normally a multicam clip), a source in-frame and a source
  out-frame. On the page each cut is drawn as a **card**.
- **Cut list**: the editor's arrangement of cuts, gaps and section markers,
  saved as a `.cut.md` text file (rules in "The cut-list file format" below).
- **Conform**: building a NEW Resolve timeline from a cut list.
- **Agent**: a process on the computer that runs DaVinci Resolve which takes
  jobs (conform, release, reload, edits) from the Timeline Cards server and
  carries them out in Resolve.
- **V1 / A1**: video track 1 and audio track 1 of a Resolve timeline.
- **Record frame**: a frame position on the timeline (as opposed to a frame
  inside the source clip).
- **Undo frame**: one step on Resolve's own project-wide undo history.
- **Offcuts timeline**: a Resolve timeline named `offcuts` that receives every
  piece removed by a live delete or trim.
- **Live mode / immediate mode**: the older way of working in which every edit
  on the page is performed at once in Resolve by keystrokes. **Independent
  mode / draft**: the newer way, in which the page edits a cut list and Resolve
  only sees the result when it is conformed.

## The Resolve engine: connection and reading the open timeline (live mirror)

(source: resolve_engine.py, config.py constants)

- **Connection guard.** The engine never connects to Resolve unless a guard
  says it may. Two ways to run:
  - With an outside "bridge" (the CC Sync companion's own Resolve connection):
    the engine asks the bridge whether Resolve can be talked to and for the
    Resolve object; it never opens its own scripting connection. A bridge
    whose "ready" check raises is treated as ready (fails open).
  - With no bridge (standalone use): the engine uses the pipeline's own
    guarded connect, which refuses unless Resolve's script server is up and
    Resolve has registered with it.
  - The engine publishes a contract version number (currently 1); the CC Sync
    companion refuses to start an engine built against a different number.
- **"Resolve not ready" is a waiting state, not a failure.** When the bridge
  answers no Resolve (closed or launching), the engine waits 0.1 s and asks
  again; it does not count this toward a reconnect, and it still serves any
  pending release/reload request while waiting.
  - Message held internally: "DaVinci Resolve is not accepting scripting
    connections yet (closed or starting up)".
- **No project open** refuses with "no project is open in Resolve" (counted as
  a failure, after first serving any pending release/reload).
- **Project database link.** On first connect, if the engine has no link to
  Resolve's project library database, it reads the current database
  connection details for the open project and opens it; a failure is
  recorded as "project database: <error>" and the engine carries on without it.
- **The sweep (every 1 s).** Reads the current timeline: its id, frame rate,
  whether the timecode is drop-frame (a `;` in the current timecode), start
  frame, and every item on V1 (id, start, duration). Then per-item facts
  (only recomputed when an item is new or its duration changed): media pool
  clip id and name, the clip's file path on this machine (read once per clip,
  cached for good, empty for timelines and compounds), the clip's frame rate,
  the source in-frame, and the item's clip colour. Then all timeline markers
  (frame, colour, name, note, duration, custom data).
  - The source out-frame is never read from Resolve; it is computed as
    source-in plus the item's timeline duration converted to the clip's own
    frame rate (minimum 1 frame).
  - Items with no media pool clip (generators, titles) are carried with their
    name and no source span.
  - When the bridge can supply per-clip facts from the project library (V1
    video rows only), those are used instead of asking Resolve per clip; any
    row of an unknown shape makes the engine fall back to asking Resolve.
  - Changing to a different timeline clears the per-item cache.
  - The cards themselves are then built by the media library half (not this
    section's part) from these facts.
- **Playhead read (every 0.1 s).** Current timecode and the video item under
  the playhead. When the playhead is on a known cut with a transcript, it
  also publishes which clip and which second of the clip's source the
  playhead is on (rounded to 1 ms), so the page can highlight the spoken word.
- **Jump.** When the page asks to jump to a frame, the engine sets Resolve's
  playhead to that frame's timecode.
- **No timeline open.** Not treated as a failure: the engine walks the whole
  media pool (clip ids and names only, no other properties) so a conform can
  still find clips by name, publishes a "no timeline" state with the reason
  "no timeline is open", and re-walks the pool at most every 120 s or when it
  has not yet published the state. Pool walk failure is logged ("the media
  pool walk failed: ...") and ignored.
- **Multicam bin scan (every 60 s, or on request).** Walks the media pool
  folder named `Multicams` (and its sub-folders) and, for each multicam clip,
  refreshes the live clip handle, its name and file path, and loads its
  transcript entry so it shows in the transcripts menu before it is on any
  timeline. A clip's transcript entry is reloaded when it had none, when its
  transcript file name is missing, or when the transcript file's modified
  time changed or the file vanished. Failures are ignored (best effort).
- **Whole-pool name walk (every 120 s)** while a timeline is open, too, so a
  conform can resolve clips outside the `Multicams` bin.
- **Transcript retry.** A clip that had no transcription in the project
  library is re-asked every 60 s (Resolve writes them on save).
- **Failure handling.** A sweep error is retried quietly twice (0.5 s apart,
  keeping the last good state on screen); the third consecutive error drops
  the connection, publishes the error, and waits 2 s before reconnecting.
- **Stop.** The engine can be told to stop; it never interrupts an edit,
  conform or release in progress, finishes it, then exits before the next
  sweep and stops its keystroke helper. A project closed for a library write
  ("held", below) is left closed on stop.
- **Combined engine.** A single process can run the media library and this
  Resolve half together ("SyncEngine"); stopping it stops both halves.

## Live edits performed in Resolve by keystrokes (immediate mode)

(source: resolve_engine.py, config.py KEY_DEFAULTS / AHK_CANDIDATES)

- **How keystrokes are sent.** Every live edit is Resolve's own command sent
  as a keystroke through an AutoHotkey v2 helper script that brings Resolve
  to the front, sends, and hands focus back. Windows only in practice.
  - AutoHotkey is looked for at: the `AUTOHOTKEY` environment variable,
    `%LOCALAPPDATA%\Programs\AutoHotkey\v2\AutoHotkey64.exe`,
    `C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe`, then `AutoHotkey64` or
    `AutoHotkey` on PATH. None found: "AutoHotkey v2 not found -- moves are
    performed by Resolve itself through keystrokes; install AutoHotkey v2 or
    set AUTOHOTKEY to its exe".
  - If Resolve would not come to the front, the send raises and nothing is
    sent.
- **Key bindings follow Resolve's keyboard preset.** The engine reads the
  editor's Resolve keyboard preset file (re-read whenever its modified time
  changes) and uses the first binding of each command; any command not bound
  uses Resolve's default. If the preset cannot be read: log "could not read
  Resolve's keyboard preset: ... -- using defaults". Defaults:
  - Deselect all `Ctrl+Shift+A`; select clip at playhead `Shift+V`; ripple
    cut `Ctrl+Shift+X`; paste insert `Ctrl+Shift+V`; match frame `F`; insert
    `F9`; split clip `Ctrl+\`; ripple trim start to playhead `Shift+[`;
    ripple trim end to playhead `Shift+]`; undo `Ctrl+Z`; redo
    `Ctrl+Shift+Z`; focus the timeline panel `Ctrl+4`.
- **Parking the playhead.** Before any keystroke, the playhead is moved to
  the target frame, the engine waits 0.35 s, reads it back, and retries once.
  If it still is not there: "the playhead would not park at <tc> (it reads
  <tc> -- is Resolve playing, or off the Edit page?) -- nothing changed".
- **Every edit checks the timeline has not moved under the page.** If
  Resolve's current timeline is not the one mirrored: "the current timeline
  changed under the mirror -- nothing applied; try again". Reorder, delete,
  split, trim and extend also compare the V1 order the page saw with the
  live order; a difference refuses with "the timeline changed while you were
  dragging -- nothing applied, re-synced" (reorder) or "the timeline changed
  -- nothing deleted / split / removed / extended, re-synced".
- **The playhead the click saw wins** over a fresh read; after each edit the
  playhead is put back where it was (except after an insert, below).
- **Edits are one at a time**: while one runs the engine reports busy and the
  page's other edit posts bounce.

### Move (reorder)

- The new order is reached with the fewest single-cut moves: cuts that are
  already on the longest run in target order stay; each other cut is moved
  to just before the next unmoved cut after it (or to the end).
- Each move: park in the middle of the cut, focus timeline, deselect all,
  select at playhead, ripple cut (everything after closes up), park at the
  destination, paste insert (everything after moves out; a destination
  inside another cut splits that cut). Two Resolve undo frames per move.
- Checks after the ripple cut (Resolve's select-at-playhead also takes
  clips on other tracks whose auto-select is on):
  - V1 must lose exactly this cut; no other video track may lose anything;
    audio may lose at most the cut's own linked items (or whatever A1 has
    under the playhead).
  - Nothing cut and nothing else taken: "Resolve did not cut the clip (is the
    Edit page open, with the timeline visible?) -- nothing changed".
  - Nothing cut but other tracks lost items: undone, "select-at-playhead
    took <N clips on Vn, N extra audio items> instead of the cut
    (auto-select must be on for V1 and A1 only) -- undone, nothing changed".
  - A different V1 clip went: undone, "select-at-playhead picked a different
    clip (auto-select must be on for V1 and A1 only) -- undone, nothing
    changed".
  - The right cut went but extra items too: undone, "select-at-playhead also
    took ... -- undone, nothing changed".
- Checks after the paste: V1 must have the same count or one more (a split)
  and a new item of the cut's duration exactly at the destination frame.
  Otherwise the cut (and the paste, if one landed) is undone: "paste insert
  did not land at frame N (landed elsewhere | nothing pasted) -- undone,
  nothing changed". If the playhead would not park for the paste, the cut is
  undone: "the playhead would not park at frame N for the paste (is Resolve
  playing?) -- the cut was undone, nothing changed".
- Waits for Resolve to apply a key: polls V1 every 0.15 s for up to 3 s (6 s
  after a paste or insert).
- A batch of several moves publishes the timeline after each move so the
  page can animate each card into place.
- A failure partway through a batch keeps the earlier moves (undoable as one
  entry) and reports "<error> (N of M move(s) applied)".
- Success note: "N cut(s) moved by Resolve in X.Xs -- N undo step(s) in
  Resolve, Ctrl+Z here undoes the lot".

### Delete

- Each cut is ripple-cut as above (one undo frame), then the clipboard copy
  is pasted onto the end of the `offcuts` timeline ("banked").
- Cuts already gone are skipped. A failure partway keeps what was done
  (undoable) and reports "<error> (N of M deleted)".
- Nothing deleted: "nothing to delete -- those cuts are gone".
- Success: "N cut(s) ripple-deleted by Resolve in X.Xs -- N undo step(s) in
  Resolve -- banked to offcuts" (or "-- <warning>" if banking failed).

### The offcuts timeline (banking removed pieces)

- If no timeline named `offcuts` (case-insensitive) exists, one is created
  empty with project defaults, and the previous timeline is made current
  again. Failure: "could not create the offcuts timeline".
- Banking: switch to offcuts, wait 0.6 s, park at its end, paste insert,
  verify exactly one new item landed at the end, switch back. Costs 3
  Resolve undo frames.
- Banking never fails the edit. If the paste goes nowhere ("paste into
  offcuts went nowhere"), lands wrong (undone, "paste into offcuts landed
  wrong -- undone"), or the edit is on the offcuts timeline itself
  ("editing the offcuts timeline itself"), the note says "the piece stayed on
  the clipboard, not banked to offcuts: <reason>" so the editor can paste by
  hand.
- Switching back is tried 3 times, 0.5 s apart; failure: "could not switch
  back to the edited timeline".

### Split (text cursor in a card as a blade)

- The cursor's position in the transcript (clip seconds) is converted to a
  timeline frame inside the cut (allowing for a clip whose frame rate
  differs from the timeline's).
- Refusals: "that cut is no longer on the timeline"; cursor at the edge:
  "the cursor is at the edge of the cut -- nothing to split"; "no cut spans
  frame N".
- Uses Resolve's Split Clip with nothing selected (one undo frame). Verified:
  V1 gains one item starting at the frame, and A1 gains one per audio item
  under the blade (waits up to 2 s).
  - Nothing split: "Resolve did not split the clip (is the Edit page open,
    with auto-select on for V1?) -- nothing changed".
  - Wrong place: undone, "the split did not land at frame N -- undone,
    nothing changed".
  - Picture split but not audio: undone, "the split cut the picture but not
    its audio (turn auto-select on for A1) -- undone, nothing changed".
- Success: "split the cut at N (X.X s in) by Resolve in X.Xs -- one undo
  step".

### Trim (remove a stretch of words from inside a cut)

- The selection's start and end (clip seconds) become timeline frames.
  Empty selection: "the selection is empty -- nothing removed". A selection
  covering the whole cut becomes a plain delete.
- Steps: split at the start (if inside the cut), split at the end (if inside),
  ripple cut the piece between, bank it to offcuts.
- Piece not where the splits left it: "the piece to remove is not where the
  splits left it". A failure partway keeps done steps undoable and reports
  "<error> (N of M step(s) done -- undo in the header takes them back)".
- Success: "removed X.X s from the cut by Resolve in X.Xs (N split(s) +
  ripple cut) -- N undo step(s) -- banked to offcuts".

### Extend (pull one edge of a cut to the playhead, rippling)

- The edge nearer the playhead ("in" or "out") moves to the playhead; all
  later cuts ride along.
- Refusals before touching Resolve: "that cut has no source to extend from";
  "the playhead is on that edge already -- nothing to extend"; "that would
  leave nothing of the cut -- delete it instead"; lengthening the in-edge
  before the clip's first frame: "the clip starts X.X s later than that --
  there is no more source before this cut"; lengthening the out-edge past the
  clip's last frame (when its frame count is known, read once per clip):
  "the clip runs out X.X s before that -- there is no more source after this
  cut".
- Shortening = the trim path exactly (the removed piece is banked). Note:
  "pulled the in/out point in X.X s to the playhead -- <trim note>".
- Lengthening = select the cut, park at the target frame (outside the cut),
  send ripple trim start/end to playhead, verify the cut now has the expected
  start and duration.
  - Nothing changed at all: "Resolve did not move the in/out point (no more
    source there? is the Edit page open, with auto-select on for V1 and A1?)
    -- nothing changed".
  - Wrong result: undone; "the in/out point did not land on <tc> -- undone,
    nothing changed", or if the undo did not restore it: "... -- AND THE UNDO
    DID NOT TAKE -- Ctrl+Z in Resolve".
  - Success: "extended the in/out point X.X s to the playhead by Resolve in
    X.Xs -- N cut(s) rippled, N undo step(s)".

### Insert (put a transcript passage into the timeline at the playhead)

- Refusal: "can't place '<name>' -- not a media pool clip".
- Position: the playhead (never before the timeline start); with no playhead,
  after the card named in the request, otherwise the end.
- When a cut of the same clip is already on V1: park in it, Match Frame
  (loads the clip into the source viewer), set the source in/out marks to
  the span, park at the target, Insert (F9). Inside a cut this splits it.
  Verified: a new item within 1 frame of the expected length at the target.
  - "SetMarkInOut refused the span".
  - Nothing inserted: "Resolve did not insert -- the source viewer did not
    take the clip (click in the timeline once and retry); nothing changed".
  - Wrong place: undone, "insert did not land at frame N -- undone, nothing
    changed".
  - The clip's in/out marks are cleared afterwards.
- When no cut of the clip is on V1: the cut is appended at the end through
  the API (V1 + A1, linked) and then ripple-moved into place. Failure to
  append: "could not append the cut to V1 (audio blocked)"; a failed move
  removes the appended cut: "insert failed: <error>".
- After an insert the playhead is placed just past the inserted cut, so the
  next insert follows it.
- Success: "inserted at N by Resolve | appended via the API (no cut of this
  clip was on V1) in X.Xs -- split the cut at the playhead".

### Overlay (place a cut above, at the playhead)

- Places the cut on the first video track above V1 that is free over its
  span (adding a new video track if none is), and its audio on the first
  free audio track above A1 (adding a new stereo track if needed), at the
  playhead; with no playhead, after the named card or at the end. Nothing
  on V1 moves.
- Refusals: "clip not available"; "could not add a video track"; "overlay
  placement failed on Vn". Audio that lands in the wrong place is removed.
- The two placed items are linked. Note: "placed on Vn+An linked | (link
  failed) | (video only) at the playhead -- nothing moved".
- Undo deletes the placed items: "overlay removed (N item(s))".

### Timeline markers (live)

- Add (key M on the lane): a marker at the frame (default colour Blue,
  duration at least 1, every field carried). Refusals: "that frame is before
  the timeline starts"; "there is a marker on that frame already"; "Resolve
  would not add a marker there". Note: "<Colour> marker at frame N".
- Remove: "no marker at the head to remove"; "Resolve would not remove that
  marker". Note: "removed the marker at frame N".
- Move / rename / recolour: one delete + add with every original field
  (note, duration, custom data) kept. Refusals: "that marker is not on the
  timeline any more"; "that frame is before the timeline starts"; "there is
  a marker on that frame already"; "Resolve would not take that marker off";
  if the re-add fails the marker is put back on its old frame and "Resolve
  would not put a marker on frame N". Notes: "moved the marker to frame N" /
  "changed the marker at frame N".
- Markers ride every ripple edit: after a move, delete, trim, extend or
  insert, each marker past the edit point is put back over the same content
  (a marker inside a moved cut comes back at the same offset in its new
  place; a marker inside deleted/trimmed frames is dropped with them). A
  marker the editor added since is never touched; one whose new frame is
  taken goes back on its old frame; one that fits nowhere is logged as LOST.
  Nothing is done when markers are already correct.

### Clip colour (live)

- Sets the named colour on each listed cut; no colour clears it back to the
  bin clip's own colour. Refusals: "'<x>' is not a clip colour this pipeline
  sets"; "no cut to colour"; "Resolve would not colour that cut (is a dialog
  open?)"; "none of those cuts are on the timeline any more -- re-synced".
- Note: "N cut(s) set <colour> | back to the clip's colour (N had gone)".
- Undo puts each cut's previous colour back: "put N cut(s) back to their
  colour".

### Undo (the page's undo button for live edits)

- Up to 20 undo entries kept.
- For a keystroke edit: refuses if the timeline is not exactly as the edit
  left it: "the timeline changed in Resolve since that edit -- use Ctrl+Z in
  Resolve instead". Otherwise sends Ctrl+Z one at a time (budget = the
  edit's undo frames plus untracked frames above it), after each one waiting
  up to 2 s and comparing the timeline with the recorded chain of states:
  a step that changed nothing visible is passed over; a state the tool did
  not produce is redone and refused: "undo reached a timeline state this
  tool did not produce -- that step was redone; finish with Ctrl+Z in
  Resolve"; running out of budget: "undo stopped after N step(s) without
  reaching the previous state -- finish with Ctrl+Z in Resolve" (the entry
  stays undoable).
  - Afterwards the edited timeline is made current again (waits up to 2.5 s
    first), any piece banked to offcuts is deleted from offcuts, and markers
    are restored to how they were if the Ctrl+Z walk did not already do it.
  - Note: "undid <label> in Resolve (N Ctrl+Z)".
- Nothing to undo: "nothing to undo".
- Legacy rebuild undo (an older stored snapshot): deletes the differing span
  (video, linked audio, and stray unlinked A1 audio wholly inside the span),
  re-appends the snapshot's cuts explicitly on V1/A1, links them, verifies
  positions, durations and audio; on failure rolls back and reports
  "rebuild verification failed (audio missing on N cut(s), something is
  blocking A1) at frame(s) ... -- the previous order was restored
  automatically" or "... rollback also failed; press undo in the header to
  restore the pre-edit state". Other refusals: "can't place '<name>' -- not
  a media pool clip"; "DeleteClips failed -- timeline unchanged?". Success:
  "N cut(s) rebuilt in X.Xs (delete X, append X, verify X)".
  Audio partially crossing the span edge is left in place with a logged
  warning.

### Rendering a reference WAV for one multicam (live mode)

- On request, for one multicam: clears its in/out marks, builds or reuses a
  timeline named "<clip name> [xscript]" from it, renders audio only (all
  frames) into the interviewee's folder under the clip's name, and switches
  Resolve straight back to the timeline the editor was on.
- Progress percentage is published once a second. Gives up after 15 minutes:
  "still rendering after 15 minutes -- check Resolve's Deliver page".
- Refusals: "could not build the render timeline '<name>'"; "Resolve refused
  the render settings"; "Resolve refused to queue the render job"; finished
  but not "Complete" or no WAV found: "the render ended as '<status>' and left
  no WAV in <folder>".
- Always returns Resolve to the editor's timeline, even on failure. The page
  is told busy meanwhile.

### Running a whisper transcription for missing clips (agent machine)

- Request carries clip ids, the media folder and the episode root.
  Refusals: "transcribe: no clip ids"; "transcribe: no episode root at
  <root>"; "transcribe: no media folder at <media>"; "a whisper run is already
  going -- one at a time"; "none of those [id]s are under <media>".
- Finds video files (.mp4, .mov, .mkv, .m4v, .webm) whose names contain
  "[<id>]", skipping any folder named `proxy`, and runs the pipeline's
  `transcribe` command (`py -3.12 pipeline.py transcribe --root <root>
  --folder ...`) in the background with no console window on Windows.
- Answers at once: "whisper started: N of M clip(s) found, N folder(s)".
  Progress lines of the form "[n/N] name" are published (current item cut to
  80 characters); the end records exit status ("exit N" on failure).

## Conform through the Resolve API on the editor's machine (what is built in Resolve)

(source: resolve_engine.py `_apply_conform`, `_place_span`)

This is what the agent does when it receives a "conform" job. It needs no
timeline open, only a project.

- **Order of operations:**
  1. Refuse if no name: "the new timeline needs a name". Refuse if no cuts:
     "nothing to conform -- the draft is empty".
  2. Refuse if Resolve is showing a modal dialog (detected by Resolve not
     reporting its current page): "Resolve is showing a dialog (a message
     box, a transcription in progress...) and answers no edit until it is
     closed -- close it and conform again". Nothing is placed.
  3. Refresh clip handles: rescan the `Multicams` bin and walk the whole
     media pool (failures logged and ignored).
  4. Import missing media: each clip the job lists as "to import" is
     imported from its source path. Matched back by file name (exact, or one
     name containing the other). Errors: "importing N clip(s) failed:
     <error>"; "<file> did not import -- nothing was placed".
  5. Every cut's clip must now be known: "clip <person or id> is not in the
     bin scan yet".
  6. Choose the timeline name: if taken, "<name> (2)", "(3)" ... up to 99.
     Logged "'<asked>' exists -- building '<name>' instead".
  7. Optional target bin: if the job names a bin, it must exist anywhere in
     the media pool ("there is no bin called '<x>' in this project's media
     pool, so nothing was built") and be made current ("Resolve would not
     make the bin '<x>' current, so nothing was built"). The editor's
     previously current bin is put back afterwards. Without a bin the new
     timeline lands in whatever bin is current in Resolve.
  8. Create an empty timeline: "could not create timeline '<name>' (is the
     name taken?)". Resolve switches to it.
  9. Optional frame rate: if the job carries one, custom timeline settings
     are switched on and the timeline frame rate set while it is empty
     (refusal only logged). Blank keeps the project default.
  10. Place the cuts (below).
  11. If no cut at all landed: the empty timeline is deleted, Resolve goes
      back to the previous timeline, and the conform fails with "none of the
      N cut(s) landed on the new timeline (removed it) -- see [place] lines in
      the agent log for the reason".
  12. Markers (below), then gap notes (below).
- **Placement of cuts.** Cuts are laid end to end from the timeline's start
  frame; each cut's leading gap (in frames) is added before it. Each cut
  occupies exactly its source span in record frames (one record frame per
  source frame, even on a mixed-rate timeline).
  - Video is appended explicitly to track V1 and audio explicitly to A1
    (independent of the destination-track buttons in Resolve's UI), in
    batches of 40 cuts per call. A batch that returns nothing is retried one
    cut at a time; each refused cut is logged "REFUSED at <frame> (...) --
    Resolve returned nothing for it".
  - Each video item is linked to its audio item. If Resolve gives no answer
    (a dialog), linking is retried 5 times with growing waits (0.5 s, 1 s ...
    2.5 s); an unlinked pair is logged, not fatal.
  - A cut whose video landed without audio is counted "landed without
    audio".
  - Clip colour: the cut's own colour from the cut list (must be a colour
    name this pipeline knows, otherwise "'<x>' is not a clip colour this
    pipeline sets"), else the interviewee's colour; a failure to set it is
    only logged.
- **Markers.** Two kinds of marker input, both placed after all cuts:
  - A list of markers at frames relative to the timeline start (this is how
    a `.cut.md`'s section markers arrive; they sit at the head of the next
    cut's gap).
  - Markers attached to a particular cut, placed at that cut's first record
    frame.
  - Resolve allows one marker per frame; a second on the same frame is
    refused and counted.
- **Gap notes.** If any cut carries a note for the gap before it, each such
  gap gets a Fusion Text+ title of exactly the gap's length, or a duration
  marker where a title cannot go (the placing itself is in another file,
  `gap_notes.py`, not this section's part). Placement never fails the
  conform.
- **Audio fades are never applied by this route** (Resolve's API has no fade
  call). They are counted and reported.
- **Result note** (shown to the editor): "conformed N cut(s) onto the new
  timeline '<name>' in X.Xs -- N marker(s) carried over (N would not go on)
  -- <gap note summary> -- cut(s) a, b did NOT land -- N cut(s) landed
  without audio -- N audio fade(s) not applied: the Resolve API cannot set
  fades, conform through the library instead". The result also carries the
  name actually built and the count of dropped fades.

## Releasing and reopening the Resolve project for a library write ("hold")

(source: resolve_engine.py `_apply_release`, `_apply_reload`, `_serve_held`)

- **Release** (a job from the server that wants to write the project's rows
  in Resolve's project library database itself): save the project, close it,
  and stop sweeping until a reload arrives.
  - No project open at all: the engine holds anyway and answers "no project
    is open in Resolve -- nothing to release (<reason>)".
  - The open project must be the one named: "Resolve has '<a>' open, not
    '<b>' -- nothing was closed".
  - "Resolve would not name the open project: ..."; "no project manager:
    ..."; save failure: "'<name>' would not save (...) -- it was NOT closed"
    or "'<name>' would not save -- it was NOT closed"; close failure:
    "'<name>' would not close: ..." or "Resolve refused to close '<name>' (a
    render or a modal dialog?) -- nothing was written".
  - Success: "released <name>".
- **While held**, the engine does not reconnect, sweep or publish cards. It
  publishes one error state: "<project> is closed while the library is
  written from the NAS", and serves only incoming jobs.
- **Automatic reopen after 300 s.** A hold nobody ends reopens the project
  by itself; if that fails, the hold is dropped anyway.
- **Reload**: reopen the named project (or the held one), take fresh
  handles, and optionally open a named timeline.
  - "reload: which project?"; "cannot reach Resolve to reopen '<name>': ...
    -- open it by hand"; "Resolve would not reopen '<name>' -- open it by
    hand"; "'<name>' is open again but this agent cannot see it yet: ...".
  - Notes: "reopened <name> on '<timeline>'", "reopened <name> -- but there
    is no timeline called '<x>' in it (open it by hand)", "reopened <name> --
    '<x>' would not open (open it by hand)".
- Release and reload are served even when Resolve has no timeline open or
  the connection just failed; a conform is also served with no timeline open.

## The cut-list engine: serving a `.cut.md` file as cards, with no Resolve (draft mode)

(source: project_engine.py)

- **What it serves.** A cut-list file is read, every clip name in it is
  resolved to a clip, and the cuts become cards exactly as a timeline's
  items would (words, person, colour, translations, markers, lane, search
  are all the media library's, not this section's part).
- **Started from the command line** with a project file, an episode root,
  and optionally a project-library database (host, name, port, user,
  password), a media-path map, and `--readonly`. It can also start with no
  file open (then only an agent-capable engine serves anything).
- **Read-only mode** (`--readonly`): every mutating route is refused with
  "this project file was opened read-only (--readonly): nothing here may
  change it", except conform (`/api/conform`), which builds a timeline and
  does not edit the file. The page is told the file is read-only. In
  read-only mode the Google-translate draft cache is kept in memory only.
- **Card identity.** Each cut's id is `cut:` + the first 10 hex characters of
  a SHA-1 of "clip|in|out" (seconds to 6 decimals), with `#n` appended for
  the 2nd, 3rd... identical cut. The same file always gives the same ids;
  a trim or split therefore renames a cut, and the page is sent a
  "renamed" map (old id -> new id) so it keeps its selection.
- **Clip resolution** (per clip name, first time seen): exact name in the
  project library; else the rename table `conform.map.json` (looked for
  beside the cut list, one folder up, and in `<root>\Script Docs`, keys
  case-insensitive); else a synthetic id `clip:<name>`. How each clip was
  resolved ("library", "map", "name") is published and counted in the log.
  - Clip frame rate and start timecode: the library's real values win over
    the file's recorded ones.
  - The person named on a cut seeds the clip's interviewee and colour.
  - A clip with no media path gets one from any
    `<root>\Script Docs\*transcripts.json` (montage transcript list),
    matched by exact name, then by case-folded stem, then by a `[<id>]`
    tag in the name. Re-read only when those files change.
- **Where a clip's words come from**, in order:
  - If the file is `timing: srt`: the vault's `.srt` first.
  - Then the whisper sidecar `<stem>_words.json` (in the clip's own `Clips\`
    folder or its interviewee's folder). Its recorded source file also
    becomes the clip's media path.
  - Then the project library's transcription.
  - Then (if not already tried) the `.srt`: `<clip name>.srt` in the clip's
    `Clips\` folder, the interviewee's folder (named on the cut, or guessed
    by fuzzy stem match against the interviewee folders), or beside the
    media file.
  - For whisper words, the `.srt` is also loaded to locate the transcript
    document's paragraphs.
- **Transcript document built from a `.srt`** when the words came from a
  `.srt` beside the media and there is no `_Transcript.md`: paragraphs break
  at a 2.0 s silence, at the first sentence end after 8 s, and always at
  20 s; each paragraph gets a stable 6-character ref ("s" + 5 base-36 chars)
  derived from its text. Paragraphs with at least 20% Chinese characters are
  treated as Chinese. Nothing is written to the vault, and these refs are
  never written into the cut list.
- **Re-slicing on load.** Every cut's words (and its transcript `^ref`) are
  re-derived from the transcript at each load or reload; the file is not
  written until the next edit. Highlights are refitted onto the new words
  (a highlight whose words all went is dropped). Log: "N cut(s) re-sliced
  from the transcript at load (the file had older words)".
- **Audio warm-up.** On load (and for newly added clips on reload) the audio
  extraction of every clip is queued in the background.
- **Card geometry.** Cards start at the file's timeline start timecode
  (default 01:00:00:00). Each cut's leading gap (seconds) is converted to
  timeline frames; its source in/out are converted at the clip's real rate
  (learned facts, then the file's, then the timeline rate); its timeline
  length is source length scaled to the timeline rate (min 1 frame). Fades
  are converted to timeline frames; the manual gain (dB) is carried.
- **Markers from the file.** A `## §` section heading becomes a marker
  (default Blue), a `## ◆` note heading and every `- (note)` / `- (unmatched)`
  bullet become Green markers ("(unmatched) " prefixed on the name), each at
  the start of the cut that follows. `## Alternates`, `## staged ...` and
  `## ⧉ ...` sections are not in the cut.
- **The shelf ("staged") and alternates.** Every cut under `## staged`,
  `## staged — <category>` or `## Alternates` is listed (never dropped) with
  its clip, span, person, words, translation (exact Claude translation,
  else the instant Google draft, which asking queues), colour, length and
  category. Categories are listed in document order, empty ones included.
- **Saved sequences.** Each `## ⧉ <name>` section is listed whole: its cuts
  (with the black before each, fades, gain, translation), count, total
  length, and its note bullets.
- **Every published state also carries**: that it is a project, read-only
  or not, file name and path, timing kind, revision, source canvas, the
  timeline the last conform built and when, the divergence summary (below),
  the shelf, the count of untranslated cards including the shelf, the
  categories, the sequences, how each clip was resolved, the redo depth, and
  the project picker menu.
- **Watching the file (every page poll, at most once a second).** If the
  file changed on disk (size/modified time moved AND the content hash
  differs from what this engine last wrote) it is reloaded and the redo
  stack is cleared: "changed on disk, reloaded". So a hand edit in
  Obsidian shows on the page within about a second. Not done while an edit
  is running, or in read-only mode.
- **Google-draft republish.** When background Google translations land, the
  cards are rebuilt at most every 12 s, and only when no edit has been made
  for 5 s.

### Editing the file (one writer, every edit a revision)

- All edits are queued and applied one at a time by a single writer thread,
  in arrival order. The page's edit request is answered once the new state
  is published (or the page polls). A refusal is reported on the state
  (with a short error sentence and an error kind), not as an HTTP error.
  Unknown edit kind: "a project file cannot do that here (<kind>)".
- **Single-writer guard on every write.** If the file on disk is not the one
  this engine loaded (by stat and content hash), it is reloaded and the
  edit refused: "the project file changed on disk -- reloaded, redo your
  edit". Nothing is ever overwritten.
- **Each write**: revision number +1, `written: <timestamp> by Timeline
  Cards` stamped, the previous bytes copied into the history folder, the new
  text written through a temp file and rename, redo stack cleared. Note
  shown: "<what> -- rev N".
- **Stale-order refusal.** Edits that send the order the page saw are
  refused if the list changed: "the cut list changed -- re-synced, try
  again". A cut id not in the list: "that cut is no longer in the cut list".
- **Reorder** ("N cut(s) moved"): cuts placed in the target order; a drop in
  front of a cut can join that cut's section along with a block of cuts
  that travelled. A gap can move in the same edit ("N cut(s) moved, the gap
  with them"), so a drop between a gap and its cut is one revision.
- **Delete = stage into the cut's own section.** The cut leaves the list and
  goes to the shelf category named after the section heading it sat under
  (last `## §` heading before it; a cut before any heading, or a heading
  that cannot be a category name, goes to the plain `## staged`). The
  category is created if needed. The cut's leading gap is reset to 0.
  Note: "N cut(s) deleted -- staged under ## staged — <name>".
- **Stage** (to the shelf): to the plain shelf, a named category, or to a
  spot before/after a staged card (that card's category; legacy
  `## Alternates` rows are not used as anchors). Note: "N cut(s) staged --
  kept under ## staged".
- **Unstage** (back into the cut): before or after a named cut, or at the
  end. "that staged cut is no longer in the file". Note: "back in the cut:
  <clip>".
- **Move within the shelf**: to before/after another staged card (joining
  its section), or to the end of its own. Dropped on itself: no-op "that
  staged cut is already there" (no revision).
- **File staged cuts under a category** (empty = plain shelf; created on
  demand). Refusals: "that staged cut is no longer in the file", "no staged
  cut named"; all already there: no-op "already in that category". Note:
  "N staged cut(s) filed under ## <title>".
- **New empty category**: "a category needs a name"; exists: no-op "that
  category already exists". Note: 'the category "<name>"'.
- **Delete a category**: its cuts go to the plain shelf, never deleted.
  "which category? none was named"; 'no category called "<name>"'. Note:
  'the category "<name>" removed, N cut(s) back on the plain shelf'.
- **Save a run as a sequence**: the selected cuts must be adjacent: "select
  the cuts to save as a sequence"; "a sequence is a run of cuts next to each
  other - select one unbroken stretch". The run's cuts, every gap including
  the black before its first cut, and note bullets strictly inside the run
  move into a new `## ⧉ <name>` section. Name: the one given, else
  "<person>: <first words> (N cuts, X.Xs)" cut to 60 characters with
  "...", unique by " (2)", " (3)" ... Note: 'N cut(s) saved as the sequence
  "<name>"'.
- **Restore a sequence**: back whole (with its notes) before/after a named
  cut or at the end; the sequence leaves the store. 'no saved sequence
  called "<name>"'; 'the sequence "<name>" has no cuts in it'. Note: 'the
  sequence "<name>" is back in the cut (N cuts)'.
- **Rename a sequence**: "a sequence needs a name"; same name: no-op "that is
  already its name"; 'there is already a sequence called "<x>"'.
- **Delete a sequence**: 'the sequence "<name>" deleted' (undo brings it
  back).
- Sequence and category names follow heading rules; the category-name error
  is reworded to "a sequence name".
- **Paste copied cuts** (copy/cut/paste of lane cards): "nothing to paste -
  copy some cuts first". Every cut is checked against known clips first
  ("a copied cut's clip is not in this episode - nothing pasted"); none are
  built if any fails. A cut still in the file anywhere (lane, shelf,
  sequence) is copied from the file with its exact spans, fades, colour,
  note and highlights; otherwise it is rebuilt from the frames with the
  card's colour, note, highlights, fades and gain. Gaps between cuts copied
  side by side are kept; the black before the first is the lane's. Inserted
  before/after a named cut or at the end. Note: "N cuts pasted".
- **Split** at a source second: "split into two cuts".
- **Trim** (remove seconds a..b, snapped to frames, clamped to the cut): if
  it covers the whole cut it becomes a delete with the note "<clip> trimmed
  away -- staged under <where>"; else "X.X s taken out of the cut".
- **Extend** an edge to a timeline frame: "that edge is there already --
  nothing to extend"; note "the in/out point out/in X.X s".
- **Insert** a transcript span: the clip is registered in the file's
  `clips:` block on first use (rate, start timecode, library id if real).
  Position: at a timeline frame (inside a cut, that cut is split and the new
  cut goes between the halves; otherwise before the cut that starts at or
  after it), else after a named cut, else at the end. Note: "inserted X.X s
  of <clip>".
- **Insert straight onto the shelf** (paste of a transcript paragraph while
  the shelf tab is open): "staged X.X s of <clip>".
- **Gap**: sets the black before a cut (absolute frames, converted to
  seconds); with `from`, moves it from another cut in one revision. Notes:
  "a gap of X.X s before the cut", "the gap is gone", "the gap moved: X.X s
  before the cut".
- **Audio fades** (absolute seconds, a missing end left unchanged): "fade in
  X.X s, fade out X.X s" or "the fades are gone".
- **Manual gain** (absolute dB, several cuts in one revision): "no cut to set
  a gain on"; notes "gain +X.X dB on N cuts" / "gain reset on N cuts".
- **Clip colour**: "N cut(s) <colour>" or "back to the interviewee's colour".
- **Markers**: add (before the cut at that frame; a section or a note, with
  colour, name and kind), remove ("that marker is not in this cut list"),
  move/recolour/rename (to before the cut at the new frame). Notes: "a
  section / a note in the cut list", "the marker is gone", "the marker
  moved". Two markers on one frame are told apart by name.
- **Move a section** (overview drag): the heading and all its cuts move
  before another section heading or to the end. Refusals: "only a section
  heading moves like that -- drag a note marker onto the cut it belongs to
  instead"; "a section lands before another section, not on a marker inside
  one"; no-op "that section is already there". Note: 'the section "<x>"
  moved'.
- **Note on a card** goes into the file as `- note:` under the cut (queued
  like any edit; "an edit is already being applied -- wait a moment" if
  one is running). A note on a GAP stays in the vault's
  `timeline_notes.json` instead. Note: "note on a cut".
- **Highlight** (`==text==`) on a card or shelf card: modes set (default),
  add, clear. Each phrase must fit the card's own words; a fit that keeps
  less than 60% of the asked characters is refused: '"<phrase>" is not in
  that card. Its words are: "<first 120 chars>"'. Clear with none: no-op
  "that card has no highlight on it". Notes: "highlighted N phrase(s) on a
  cut", "the highlight off a cut".
- On cards, the file's `- note:` beats any note in the notes store, and the
  highlights are refitted onto the card's displayed words.
- **Undo** = put back the newest revision from the history folder and delete
  it from the history; the replaced text goes on an in-memory redo stack.
  "nothing to undo -- this is the first revision of the file". Note: "back
  to rev N". The undo button is offered whenever the history has a
  revision (so it survives restarts).
- **Redo** (this session only): "nothing to redo"; note "forward to rev N".
  The undone text stays undoable.

### Picking, opening and creating cut lists

- **The menu** on every state: every cut list in the root's
  `Script Docs\Cuts\` (scanned at most every 5 s, forced on open), the live
  Resolve timeline row where there is one, the Cuts folder path, which file
  is open (name, revision, timeline, last conform, cut count, timing,
  title, read-only, load error), whether the engine can go live, read-only
  flag, and source. A folder that will not list is logged and shown empty.
- **Open another file in place**: must end `.cut.md` ("a project file is a
  .cut.md -- <x> is not one"), exist ("no such project file: <path>"), and
  be inside this root's `Script Docs\Cuts` folder ("<x> is not in this
  episode's Script Docs\Cuts folder -- switch the episode root first").
  Already open: "<x> is already open". Refused while an edit is running:
  "an edit is being applied -- wait a moment, then switch". A file that
  will not parse is served as an error state: "<x> did not open: <error>".
  The choice is remembered per root. Note: "<x> is open".
- **Go back to the live timeline** (a project server with no agent):
  "this server has no Resolve to go back to -- start it with --remote-agent
  (and an agent) as well as --project".
- **New cut list** (refused read-only): from `empty` (header, no cuts) or
  from a `canvas`; anything else: "a new project comes `from` a canvas or
  from empty, not '<x>'". New files take the open file's frame rate,
  drop-frame flag and timeline start, or the defaults (default rate,
  default drop, 01:00:00:00). A canvas conversion is two calls: a dry run
  that answers counts and writes nothing, then the real one. An existing
  name is refused (in the picker module). The new file is opened at once.
  If a project library was named but cannot be reached, a warning is added:
  "no project library reachable (<why>): this cut list will be made with
  .srt timing, not word timing".
- **Prewarm a canvas conversion** (fired while the editor types a name):
  "a prewarm names the canvas to convert"; one at a time ("already
  warming"); failures are silent.
- **Every transcript in the episode** (picker's third section): every
  `*_transcript.md` under `Interviewees\<person>\` and `Clips\<stem>\`, with
  person, clip, colour and whether it is already loaded. Opening one by
  itself reads the single `.srt` beside it (if exactly one) for timing; with
  none it is readable but has no word timing. "no such transcript in this
  episode"; "that transcript would not open: <error>".
- **Whisper corpus clips**: every `Clips\<stem>\<stem>_words.json` is
  registered as `clip:<stem>` (names only) and read only when the
  transcript panel, a quote match, a play, or an insert first needs it.
- **Switching episode root** clears all clip resolutions, facts, the corpus,
  and the picker caches.

### The timeline the file names, and how far it has drifted ("divergence")

- The file's `timeline:` names the Resolve timeline its last conform built.
  The engine keeps that timeline's cards to compare with (never shows
  them), from the agent's live push when there is one, otherwise from the
  project library: a cheap fingerprint check every 5 s (on page polls), and
  a full read only when the fingerprint changed.
- Refusals finding it in the library: "this server has no project library to
  read a timeline from (--db-host / --db-name)"; "this file names no
  timeline yet -- conform it first, or say which one to compare with"; "no
  project '<p>' in <db> -- the file's `project:` has to name one"; "no
  timeline '<t>' in <db> / <p>".
- Every state carries a small divergence summary (computed after an edit is
  confirmed, not before; marked pending while stale). If it cannot be
  computed: summary "could not be compared" with the error.
- **GET /api/diff**: the whole classified list, or "there is no timeline here
  to compare this file with -- connect the agent, or give the server a
  --db-host".
- **POST /api/project/update** (refused read-only): rewrite the file from
  the timeline. Source chosen: `from: agent` ("no agent has pushed a
  timeline here -- the library is the other way"), `from: library` or a
  named timeline ("the project library answered with no timeline"), else
  whatever is available ("there is no timeline here to update this file
  from: no agent is pushing one and no project library was named").
  - Different timeline from the one the file names is refused without
    `force: true`: "this project file was built from '<a>' and the cards
    here are '<b>' -- updating it from a different timeline needs force:
    true".
  - `dry: true` answers counts and the classified rows, writes nothing.
  - Already the same: "the file and <timeline> are already in step --
    nothing to write".
  - Otherwise queued as one revision ("an edit is already being applied --
    wait a moment" if busy). Note: "<file> <- <timeline>: <summary> -- rev
    N". The whole cut list is replaced.

## Cut-list editing rules (what each draft edit does to the document)

(source: project_edit.py)

- **Section headings stay with their cuts, not with a position.** Every
  heading and note bullet remembers the cut it comes before and the cut it
  comes after. After any edit it is put back before the cut it preceded;
  if that cut is gone or moved, before the next unmoved cut that followed
  it; else after the cut it followed; else after the last unmoved cut
  before; else at its old position (so a heading whose whole section was
  deleted stays, at the end). Result: a dragged card joins the section it
  was dropped into, and nothing else in the document changes section.
- **Which cuts "moved" in a reorder** is decided as: if the page names the
  block of cuts it moved and they are one contiguous run in the new order,
  exactly those; otherwise the cuts not on the longest run still in their
  old order. Ties (an adjacent swap across a section boundary) are resolved
  the same way every time.
- **Dropping a block in front of a cut** keeps the headings directly above
  that cut above the block, so the block joins the top of that section
  rather than the heading sliding below it. Ignored unless the block is
  exactly the cuts now in front of that cut.
- Reorder refusal: "that re-order is not a re-order of this cut list" (the
  new order must contain exactly the same cuts).
- **Delete**: the black before a deleted cut is NOT deleted; it moves onto
  the next surviving cut (consecutive deletes pool their gaps). Only when no
  cut survives after it does the gap go. Refusal: "that cut is no longer in
  the cut list".
- **Every edit edge is snapped to the clip's own frame grid** (seconds ->
  frame -> seconds at the clip's rate), so the file's seconds always map back
  to the frame a conform will place.
- **Trim** (remove source seconds a..b, clamped to the cut):
  - "the selection is empty -- nothing removed" (under 1 frame).
  - Whole cut: "that is the whole cut -- delete it instead".
  - Head or tail: the cut's in or out moves.
  - A bite out of the middle leaves two adjoining cuts; the fade-out moves
    to the second half; both keep the note, colour, highlights, person and
    manual gain.
  - Fades are shortened so neither is longer than the cut (fade-in plus
    fade-out may still exceed the cut; overlapping fades are allowed).
- **Split** at a source second: "the blade is at the edge of the cut --
  nothing to split" (less than 1 frame either side). The gap stays on the
  first half; the fade-out goes to the second half; everything else is
  copied to both.
- **Insert**: after a cut, before a cut, or at the end.
- **Insert a run (sequence or paste)**: the whole run goes in, in order, in
  one step, inside the section of the cut it was put against (rows directly
  in front of the "before" cut move in front of the run; rows directly
  after the "after" cut move after it). The run's own note bullets go back
  in front of the cut that followed each one. Spans, gaps and fades are
  untouched. "that sequence has no cuts in it"; "that cut is no longer in
  the cut list".
- **Extend** one edge by a number of source seconds (positive lengthens):
  "edge is 'in' or 'out'"; "the clip starts X.X s later than that -- there
  is no more source before this cut"; "the clip runs out X.X s before that
  -- there is no more source after this cut" (only when the clip length is
  known; the draft engine does not pass it); "that would leave nothing of
  the cut -- delete it instead". Fades are re-clamped.
- **Gap**: seconds, never negative, rounded to 6 decimals; 0 removes it.
- **Fades**: seconds, never negative, either end may be left unchanged;
  clamped to the cut's length.
- **Manual gain**: absolute dB, rounded to 0.1 dB, clamped to +/-30, 0
  removes it. Survives a trim; both halves of a split keep it.
- **Colour**: a known clip colour name, or none.
- **Note**: trimmed text; empty removes it.
- **Markers in a cut list are headings or note bullets.** The kind the page
  asks for wins; with no kind, Green means a note and anything else a
  section. A note with no name becomes a `- (note)` bullet; otherwise a
  `## ` heading (unnamed section headings are called "Section"), default
  colour Blue for sections and Green for notes.
  - Add: before the given cut, or at the end. Nothing else moves.
  - Remove: "that marker is not in this cut list".
  - Move / rename / recolour / change kind: recolouring never changes the
    kind; the kind changes only when asked.
- **Move a whole section** (heading plus every row under it up to the next
  heading): before another heading or to the end. "only a section heading
  can be moved that way"; "that section is no longer in this cut list"; "a
  section cannot be moved inside itself".

## The cut-list file format (`.cut.md`)

(source: cutlist.py)

- **Where it lives**: `<Episode>\Script Docs\Cuts\<name>.cut.md`, a Markdown
  file in the vault, editable in Obsidian.
- **A cut's identity** is (clip NAME, source seconds in, source seconds out),
  never a Resolve database id. Seconds are written to 6 decimal places,
  which recover the exact frame at every frame rate.
- **Frontmatter** (between `---` lines), written in this order: `kind:
  timeline-cards/cut-list`, `rev`, `written`, `project`, `vault_root`,
  `canvas`, `timeline`, then only when present `conformed` and
  `updated_from_timeline`, then `fps` (whole numbers as "25.0", others to 8
  decimals such as 29.97002997), `drop` (true/false), `tl_start` (default
  "01:00:00:00"), `timing` (`word` or `srt`, default word), and `clips:` with
  one line per clip, sorted by name: `Name: {fps: .., start_tc: "..", uid:
  ..}` (the uid is a hint only; a conform always re-resolves by name).
- **Under the frontmatter** every written file carries a comment block
  telling a human: the writer is generative; words, the "(12.4s)" and the
  transcript link are rewritten on every save; spans, bullet order, notes
  and colours are data and are kept. A `timing: srt` file also carries a
  note that its text was matched from `.srt` cues and a span can carry a
  neighbouring sentence, and that a whisper `<clip>_words.json` or the
  project library gives word timing.
- **Title**: one `# Title` line; a second is refused ("a cut list has one
  title; this is a second one").
- **Headings**:
  - `## § name` = a section marker (default colour Blue).
  - `## ◆ name` = a note/placeholder marker (default Green).
  - `## ⧉ name` = a saved sequence (out of the cut).
  - `## Alternates...` = out of the cut, listed.
  - `## staged` / `## staged — <category>` (any of the separators ` - `,
    `:`, `/`, `|`, en/em dash, middle dot accepted when read; always written
    as ` — `) = the shelf, out of the cut.
  - Any other `## ` heading = plain, in the cut.
  - A colour is an HTML comment at the end of the heading line, written
    starting at column 66: `<!-- Rose -->`.
- **A cut bullet**: `- **Person** \`Clip name\` 724.233333 → 736.673333
  (12.4s) <!-- Colour -->`. When read, the arrow may also be `->`, `-->`,
  en dash or em dash; the person, duration and colour are optional.
  Continuation lines under it: `  [[<Person or clip>_Transcript#^ref]]`
  (the link), `  > words` (the quote, possibly several lines, highlights as
  `==text==`), `  - fade: in 0.5s out 1.2s` (only if any fade),
  `  - gain: +12.0 dB` (only if non-zero; sign always written), `  - note:
  text` (more lines indented).
- **A gap**: `- gap 2.0s`, optionally followed by `<!-- note: ... -->` lines
  (the gap's note, one per line).
- **A note bullet**: `- (note) text` or `- (unmatched) text` (nothing is
  silently dropped).
- **Colours**: a canvas hex colour is mapped to the nearest Resolve clip
  colour. "Brown" is never written: it is written as "Chocolate".
- **Reading is tolerant** of extra blank lines, a missing quote, a missing
  duration, CRLF or LF, multi-line comments, transcript names containing
  square brackets, and a fade line under a note. **Reading is loud**
  (always with a line number) about: no frontmatter ("a cut list starts
  with a --- frontmatter block"), unclosed frontmatter, a bad frontmatter
  line, a clip entry without `{...}` or without fps, a file of another kind
  ("this is a '<x>' file, not timeline-cards/cut-list"), a bad timing value,
  an unreadable bullet ("cannot read this bullet: ..."), a line that is not a
  bullet/heading/blank, and a negative fade ("a fade in cannot be -1.0
  seconds long").
- **Gain** read from the file is rounded to 0.1 dB and clamped to +/-30 dB
  (a typed -40 becomes -30); unit and sign optional when read.
- **Gaps are normalised**: consecutive gap lines before a cut are summed and
  become one; a gap is always attached to the cut after it.
- **Highlights**: only balanced `==...==` pairs are markup; a lone `==` is
  kept as typed. When written, each highlight is put on its first free
  occurrence at or after the previous one, so repeated phrases round-trip;
  a highlight no longer in the text is dropped. When words change, each
  highlight is refitted as the longest run of letters/digits it shares with
  the new words (case-insensitive); under 2 matching characters it is
  dropped.
- **Writing is deterministic**: the same cut list always produces the same
  bytes, LF line endings. Saved through `<file>.tmp` and a rename; if the
  rename is refused by another reader's lock it is retried 5 times (10 ms,
  20 ms ... apart) and then the file is written directly.
- **History (undo)**: before each overwrite, the previous file is copied to
  `Cuts\.history\<name>.<rev>.cut.md`. The newest 200 revisions are kept;
  older ones survive only if their revision number is a multiple of 10.
- **Quick peek** (for the picker): frontmatter plus a count of cut bullets
  outside alternates/shelf/sequences, and the title, without building the
  whole model.
- **Exact frame arithmetic**: seconds -> frames is round-half-up of
  seconds x exact rate (29.97 is treated as exactly 30000/1001, and so on for
  the other NTSC rates); frames -> seconds is exact division.
- **Turning a cut list into a conform job**: for every in-cut cut, the clip
  name is resolved to a media pool clip and its rate; source in/out are
  converted to frames at the CLIP's rate (out at least in + 1); the gap
  before it is converted to TIMELINE frames at the file's rate; fades are
  converted to timeline frames (only when present); the gap's note, the
  person and the colour ride along. Any clip that will not resolve refuses
  the whole conform: "these clips are not in the media pool, so the conform
  is refused: <names>".
- **Building a cut list from cards** (a timeline read back): clip facts
  from the cards; a marker at or before a card opens a heading before it
  (section if its kind is section, otherwise a note heading; markers with no
  name or note are skipped); spans converted back to seconds at the clip's
  rate; gaps at the timeline rate; person, link, words, note, colour,
  highlights, fades and gain carried.
- **Marker kind when only a colour is known** (a marker read off a Resolve
  timeline): any colour in the section-colour rotation is a section, Green
  is a note, anything else (Red) is a plain "marker", which becomes a note
  heading in a cut list.
- **Category names** (shelf headings, also sequence names): whitespace
  collapsed, leading separators removed; refused if they contain `<!--`,
  `-->` or start with `#` ("a category name cannot contain a comment or a
  #") or are over 60 characters ("a category name is a heading, not a
  paragraph").

## Timecode and frame-rate handling

(source: timecode.py, cutlist.py, resolve_engine.py)

- Timecode to absolute frame and back, drop-frame aware: a `;` in a timecode
  means drop-frame; 2 frame numbers are dropped per minute except every
  tenth minute (4 at 60 fps). A timecode that is not four fields gives
  nothing.
- The live engine decides drop-frame from whether Resolve's current
  timecode contains `;`, and uses the rounded timeline rate as the
  timecode base.
- Mixed-rate clips: a cut's timeline length is its source length scaled from
  the clip's rate to the timeline's rate in the live mirror and the draft
  cards; the API conform places one record frame per source frame instead.
  Inserts are speed-conformed by Resolve and verified within 1 frame.

## Conforming a cut-list file into a Resolve timeline (planning, routes, stamping)

(source: project_conform.py)

### Resolving clip names (refuse, never guess)

- Every cut's clip NAME must resolve to a media pool clip, by: exact name in
  the clip index; else the rename table `conform.map.json` (lower-cased
  keys), searched beside the file, one folder up, and in
  `<root>\Script Docs`; the CLI can add one more map file. Synthetic
  `clip:<name>` ids (vault-only clips) never count as resolved.
- The clip index is, depending on the caller: the draft engine's resolved
  names (plus, with an agent, the clips the agent's Resolve has in its
  pool), the project library, or a plain name list. No source at all
  refuses every conform.
- Each clip's frame rate for the frame arithmetic: the library's real rate;
  else the whisper sidecar's measured rate; else the file's per-clip rate;
  else the file's timeline rate.
- How each name was resolved ("library", "agent", "map", "import") is
  counted in the report.

### The plan (computed, nothing written)

- Refusals: "this project file has no cuts in the cut -- nothing to
  conform"; every unresolved name at once: "these clip(s) are not in the
  media pool, so the conform is refused -- add a conform.map.json line for a
  renamed clip, or import it: <names>". When an agent is connected the
  message adds whose pool and when it was last read: " (the media pool of
  <machine>'s Resolve, walked HH:MM:SS | not yet)". Internal consistency
  failure: "the cut list and the conform list disagree (N cuts, N bullets)
  -- this is a bug".
- Builds the cut list for the builder (see "Turning a cut list into a
  conform job" above), plus, per cut, the note for the gap before it: the
  file's own `<!-- note: -->` on the gap wins; otherwise the gap note the
  page stored in `<root>\Script Docs\timeline_notes.json` under the draft's
  id and the card's id.
- Record positions: gaps added, each cut's length = source span scaled to
  the timeline rate (min 1 frame). The timeline rate is the one the editor
  asked for, else the file's.
- Markers: each `## §` heading (default Blue) and `## ◆` heading (default
  Green) becomes a marker named after the heading, and each `- (note)` /
  `- (unmatched)` bullet a Green marker ("(unmatched) " prefixed, the text as
  its note), placed at the start of the GAP before the next cut (so a
  section that opens on black is marked at the black), duration 1. Frames
  are relative to the timeline start.
- Report counts: cuts, markers, notes, unmatched, alternates (excluding
  saved sequences), clip names, gaps, gaps with notes, total gap frames,
  cuts with fades (clamped to the cut), cuts with a manual gain, total
  frames and duration, rate, start timecode, drop-frame, timing, and how
  clips resolved.
- Suggested timeline name: the file's `timeline:`, else its title, else its
  project, else (when the request gives none) the file name without
  `.cut.md`.

### The dry-run table (CLI)

- One line per cut: number, clip (30 chars), source in and out as the clip's
  own timecode (the clip's start timecode plus the frame), timeline
  timecode, length in seconds, colour, person; a "(gap)" line before each gap
  with its timecode, length and note (40 chars).
- Totals line: "N cut(s) of N clip(s), N gap(s) (X.Xs), N marker(s): N
  frames = X.X min at X fps [drop]".
- Extra lines when relevant: "N cut(s) carry an audio fade: the LIBRARY
  route writes them, the Resolve API route cannot"; the manual-gain sentence
  (below); "N gap note(s): the AGENT route puts each one in a title over its
  gap where one fits, else a marker; the LIBRARY route always writes a marker
  spanning the gap"; "N alternate(s) and N unmatched card(s) are NOT in the
  cut (they stay in the file)"; "clips resolved: N by library, ..."; for an
  srt file: "timing: srt -- the spans were cut at .srt cue granularity; they
  conform frame-exactly as written".
- **Manual gain is never carried into Resolve** by any route. Every route
  says: "N cut(s) carry a manual gain that is not yet carried into Resolve:
  the timeline will play them at the clips' own level".

### Stamping the file after a successful conform

- The file is re-read, `timeline:` set to the name built, `conformed:` set
  to "<ISO time> via <route>", revision +1, saved with a history copy.

### The command line: `pipeline.py conform-project <file.cut.md>` (library route)

- Flags: `--root` (default: two folders up from `Script Docs\Cuts`),
  `--db-host`, `--db-name`, `--db-user`, `--db-pass`, `--db-port`,
  `--timeline` (new timeline name; default the file's stem),
  `--project-name` (default the file's `project:`), `--conform-map` (an
  extra rename table), `--folder BIN` (always refused here: "a bin for the
  new timeline can only be chosen on the machine with Resolve: conform with
  route "agent", or leave the bin out and move the timeline in Resolve"),
  `--apply` (actually write; default is a dry run), `--db-write-allow NAMES`
  (comma-separated libraries this run may write), `--db-backups` (where the
  writer puts its row backup), `--no-handshake` (only changes the wording
  of the refusal; this route never closes Resolve's project).
- **Dry run by default**: prints the table, any problems as "NOTE: ...", and
  "would write N cut(s) and N marker(s) into <lib> / <project> as '<name>' --
  dry run, NOTHING was written (pass --apply)".
- Checks (fatal with `--apply`, printed as NOTE on a dry run): no project
  named ("this file does not say which Resolve project it belongs to
  (`project:` in the frontmatter) -- pass --project-name"); project not in
  the library ("no project named '<p>' in the library '<db>' -- pass
  --project-name"); name already taken ("'<p>' already has a timeline named
  '<n>' -- pick another name (--timeline)"). Failure to list existing
  timelines is printed and ignored.
- `--apply` gates before anything is read: "--apply needs --db-host and
  --db-name"; "<lib> is not a library this run may write (--db-write-allow:
  ...) -- nothing was written".
- If Resolve has the project open (library lock): "Resolve on <machine> has
  '<p>' open, and this route has no agent to close it -- close the project in
  Resolve and try again".
- Writes through the library writer (which backs up first), stamps the file,
  prints "built '<name>' (<id>): N cut(s), N row(s), backup <path><gap notes
  clause>", "stamped <file>: timeline: <name> (rev N; the previous revision
  is under Cuts/.history)", and "Resolve sees it the next time the project
  is opened."
- Exit code 2 on a refusal or an unreadable cut list, else 0. The CLI also
  reads gap notes from `timeline_notes.json` (read only).

### POST /api/conform on a draft server (choosing a route)

- "this draft has not finished loading yet" until the file is loaded.
- Body: `name` (default the file's stem), `dry`, `route` or `via`
  (`agent`, `library`, `auto`; anything else: "route must be 'agent',
  'library' or auto"), `fps` (pin the new timeline's rate), `folder` (bin).
- **Automatic import of missing media**: for every in-cut clip the pool does
  not hold, if its `Clips\<stem>\<stem>_words.json` records a source path,
  the clip is marked to be imported by the agent from that path (as the
  agent machine sees it) instead of refusing.
- **Route choice** (`auto`): the agent when one is connected and Resolve is
  reachable (an open timeline is NOT required); else the library when this
  server may write it; else refused: "<why no agent>, and this server cannot
  write the project library either -- start the agent on the machine with
  Resolve (reorder_web.py --agent), or restart this server with --db-host /
  --db-name and --db-write-allow <library>".
  - Asked `agent` with none usable: "<why> -- open Resolve on that machine
    and start the agent, or conform with route "library"". When the agent is
    connected but Resolve is not reachable, why = "<machine>: Resolve is not
    reachable" (or the agent's own reason).
  - Asked `library` without write access: "this server cannot write the
    project library: start it with --db-host / --db-name and
    --db-write-allow <library>".
- **Dry answer**: route, name, note ("N cut(s) of N clip(s), N marker(s),
  X.X min -- into Resolve on <machine> | <lib> / <project> as '<name>' |
  -- but <why>" plus "-- importing N clip(s) from the corpus first", "-- N
  gap note(s) as titles where one fits the gap, else markers | markers over
  their gaps", "-- timeline pinned to X fps", "-- into the <bin> bin"),
  counts, imports, duration, library, project, how clips resolved, and why
  when no route.
- **Agent route**: one conform job (name, cuts, markers, optional fps, bin,
  imports) is queued for the agent; the request answers at once: "N cut(s)
  sent to <machine>: Resolve is building '<name>' - N audio fade(s) will not
  be applied: the Resolve API cannot set fades, conform through the library
  instead - N gap note(s) go on as titles where one fits the gap, else as
  markers - <gain sentence>". The file is stamped when the agent's result
  comes back.
- **Library route**: refused if a bin was asked (the sentence above), or if
  clips need importing ("N clip(s) are not in the media pool and the library
  route cannot import media -- conform via the agent (API) instead"), or no
  writer, or "this draft does not say which library and project to build
  in", or "<lib> is not a library this server may write (--db-write-allow:
  ...)". If Resolve holds the project: with an agent connected, the agent is
  told to save and close it, the rows are written, and the project is
  reopened even if the write failed; with no agent: "Resolve on <machine>
  has '<p>' open and this server has no agent to close it -- close the
  project in Resolve". The file is stamped, the cards republished (undo
  button off), and the answer: "built '<name>' in the library: N cut(s)<gap
  notes clause><reload note, or -- Resolve sees it the next time the project
  is opened> - <gain sentence>". This request waits for the write.

## Reading a timeline back and comparing it with the cut list

(source: project_diff.py)

- **Two sides compared as spans.** The file's in-cut cuts (source frames at
  the clip's rate, gap and fades in the file's timeline frames, colour) and
  the timeline's items (source in from Resolve, source out derived from the
  item's duration at the clip's rate, gap converted to the file's rate,
  colour only if one was set on the item, not the interviewee colour).
- **Clips match by name stem** (the clip name with the multicam suffix
  removed, case-insensitive), never by a database id.
- **Matching** a file cut to a timeline item, in three passes, each item
  used once: (1) exactly the same span; (2) one span contains the other;
  (3) the spans overlap. Within a pass the item nearest in order wins, then
  the lowest index.
- **"Moved"** = matched cuts not on the longest run that is still in order.
- **Split detection**: an unmatched item whose span lies inside the file cut
  its neighbour was matched to is the other half of a split.
- **Classes, one per cut, in this precedence**: split ("one cut in the file,
  N on the timeline" / "the other half of a cut the file holds whole"),
  trimmed ("in|out|both: in +N, out +N frame(s)"), moved ("cut N in the file
  is cut N on the timeline"), gap ("the black before it is N frame(s), not
  N"), colour (only when the FILE names a colour and the timeline differs;
  "<x>, not <y>"), fade ("the audio fades are N in / N out, not N in / N
  out"), unchanged, added ("on the timeline only (X.Xs)"), removed ("in the
  file only (X.Xs)"). Each row also lists the secondary differences.
- **Markers**: the file's section headings and note bullets (anchored to the
  index of the cut that follows) against the timeline's markers (anchored
  to the first item starting at or after the marker; nameless markers
  skipped), matched by name. Rows: "the marker '<x>' is in the file only",
  "... is on the timeline only", "the marker '<x>': it is at cut N, not N and
  it is <colour>, not <colour>".
- **Summary line** on the page's chip: counts joined by " · " in the order
  moved, trimmed, split, new, removed, gap, colour, fade, marker; or "in
  step" when nothing differs. "Same" means nothing differs at frame
  accuracy.
- **Reading a saved timeline from the project library** (read only): its
  items as cards with clip names, rates and start timecodes, gaps between
  items, item colours, and markers converted to absolute frames. A shape
  fingerprint (names, spans, starts, colours, markers) decides whether the
  comparison has to be redone.

### Rewriting the file from the timeline ("update")

- The new cut list is built from the timeline's items and markers, keeping
  what only the file knows:
  - per matched cut: its note, manual gain, person, transcript link and
    words (when the timeline has none);
  - every clip keeps the file's full clip NAME (not the stem) and its start
    timecode;
  - a heading whose name matches a marker keeps the file's kind (section
    or note); its colour is the marker's (the file's only when the marker
    has none);
  - a marker that was a note bullet in the file (still Green) comes back as
    a bullet inside the section it interrupted;
  - markers after the last cut become empty trailing headings;
  - alternates, shelf and saved sequences are carried over whole;
  - frontmatter keeps canvas, timing, project, vault root and title, keeps
    `conformed`, and gains `timeline:` and `updated_from_timeline: <time>
    from <timeline>`.
  - A cut's colour comes only from an explicit item colour.

### Command line: `pipeline.py diff-project` and `pipeline.py update-project`

- Arguments: the `.cut.md` file; `--root` (accepted, unused);
  `--db-host` and `--db-name` (required); `--db-port`, `--db-user`,
  `--db-pass`; `--db-project` (the library project, when the file's
  `project:` names something else); `--timeline` (compare with another
  timeline); `--update` (rewrite the file; dry unless `--apply`); `--apply`;
  `--force` (update from a timeline the file does not name); `--limit N`
  (print at most N differing rows, then "... (N more)").
- No timeline named: "this file names no timeline (`timeline:` in the
  frontmatter) -- conform it first, or pass --timeline" (exit 2). Lookup
  refusals: "no project '<p>' in <db>"; "no timeline '<t>' in <db> / <p> --
  there is: <names>".
- Prints a table (file cut number, timeline number, class, clip, detail)
  for every differing row, then "N cut(s) in the file, N on <timeline>:
  <summary>" and "(read N item(s) in X.X s, compared in X.XX s)".
- Diff only: exit 0 if the same, 1 if they differ.
- Update: a different timeline without `--force` is refused ("this file was
  built from '<a>' and these cards are '<b>' -- pass --force to update it
  from a different timeline", exit 2); already the same: "the file and
  '<t>' are already in step -- nothing to write" (exit 0); dry: "DRY RUN --
  <file> would become rev N: N cut(s), N section(s). Add --apply to write
  it." (exit 1); applied: written with a history copy, `written: <time> by
  update-project`, "written: <file> is rev N, from '<t>' (the previous
  revision is under Cuts/.history)" (exit 0).

## A cut-list server that also has a Resolve agent (file plus agent)

(source: project_agent.py)

- **Started** as `reorder_web.py <port> --remote-agent --token <t>
  --project <file.cut.md> --root <episode>` (also accepts a project library,
  `--readonly`, a media map, `--db-write-allow`, a backup folder). With no
  `--project` it starts "live" (showing the agent's timeline) and then
  re-opens the cut list this root was last left on, else its newest one; a
  failure is logged ("the last project of this root did not re-open: ...").
- **Two modes, switchable in place**: a file open (the file is what the page
  shows and edits) or live (no file: the page shows the agent's Resolve
  timeline exactly as a plain agent server would).
- **While a file is open, the agent's pushes are used only for**:
  - clip facts (name, media pool id, rate, start timecode, media path) so
    this file's clip names can be resolved against the agent's Resolve pool
    with no project database; when the agent names clips the file could not
    resolve before, the log says "<machine> names N of this file's clips:
    ...";
  - the agent's name, last-seen time, project database details, the time it
    last walked its pool, and Resolve's keyboard preset (cached for the
    lane);
  - a caption of what Resolve has open there ("project", "timeline"), shown
    in the header, or nothing when Resolve is closed/starting;
  - whether Resolve is reachable, and separately whether it has no timeline
    open (no timeline is NOT a reason to refuse a conform);
  - the agent's whisper progress, shown on the page;
  - the timeline's cards and markers, kept only for the divergence
    comparison (never shown as cards). A push with no cards leaves the last
    comparison in place.
  - The agent's playhead is ignored.
  - A push without a full state answers "resend" until a full state has
    been received (full pushes carry the clips).
- **Edits never reach Resolve while a file is open.** Only four job kinds may
  go to the agent: conform, release, reload, transcribe. Anything else:
  "a project file is edited in the file, not in Resolve -- the '<kind>' was
  not sent to the agent".
- **Agent-server routes refused while a file is open**: pick a timeline
  ("this server is showing a project file, not a timeline: there is nothing
  to pick, and every edit rewrites the file"), apply a staged plan ("a
  project file has no staged plan: its edits are already in the file
  (conform it instead)"), undo a library apply ("nothing was applied into a
  timeline from here -- undo a project file's edit with Ctrl+Z"). Live, all
  three work as on a plain agent server.
- **Conform** while a file is open goes through the cut-list conform above;
  only one agent job at a time: "the agent already has a request in flight
  -- wait a moment". When the agent's result for that conform comes back
  successful, the file is stamped with the timeline name Resolve actually
  built (which may be "<name> (2)") and "via agent", and the note gains " --
  <file> stamped with '<name>' (rev N)"; a stamp failure is appended: " --
  but the file could not be stamped: <error>". The stamped file is then
  republished.
- **Transcribe the cut's missing clips on the agent machine** ("here"):
  needs the agent connected with Resolve reachable (no timeline needed) and
  at least one clip stem; otherwise it falls back to the fleet path (not
  this section's part). It derives the vault root on the agent as
  `X:\<path after /vault/>` and the media folder as
  `P:\Projects\<episode path>\Youtube`, and the clip ids from `[id]` tags in
  the names. Refusals: "cannot derive the episode's media folder from '<root>'
  -- run pipeline.py transcribe by hand"; "no [id] tags in those clip names
  -- run pipeline.py transcribe by hand"; "the agent already has a request
  in flight -- wait a moment". Answer: "whisper queued on <machine>: N
  clip(s)".
- **Go live** (close the file): "the live timeline is already open" if
  already; refused while an edit runs; remembers "no file" for this root;
  shows the last-seen mirror at once with "no Resolve agent yet -- the live
  view fills from the library or the agent's next push"; asks the agent to
  resend a full state. Note: "the live timeline".
- **The live row in the menu** names the project and timeline the agent last
  reported.
- **Switching episode root**: the root's remembered (else newest) cut list
  opens; with none, a file from another root gives way to the live view; a
  file in the new root is reloaded.
- **Housekeeping** on each page poll: the file watch, then the agent link's
  own (a job the agent took and never answered is timed out, in the agent
  link module).

## The project picker: listing, making and remembering cut lists

(source: project_pick.py, config.py PICK_FILE / DATA_DIR)

- **Where**: everything is per episode root. Cut lists are
  `<root>\Script Docs\Cuts\*.cut.md`; canvases are
  `<root>\Script Docs\*.canvas` (the Cuts folder is not searched for them).
- **The list**: every cut list in the Cuts folder, newest modified first
  (then by name), each with file, name, revision, timeline, last conform,
  cut count, title (or project), timing, modified time. A file that will not
  parse is still listed with its error. No Cuts folder = no projects.
- **The canvas list**: name, path, modified time, newest first.
- **New file names**: whitespace and quotes trimmed, a trailing `.cut.md`
  dropped. Refused: empty ("give the new project a name"); any folder part,
  "." or "..", or any of `\ / : * ? " < > |` ("a project name is a file name:
  no folders, no \ / : * ? " < > | in it"); an existing file ("<x> already
  exists -- pick another name (nothing here overwrites a cut list)").
- **New empty cut list**: revision 1, `written: <time> by Timeline Cards
  (new, empty)`, project = the root folder's name (or the stem), title = the
  name, the given rate/drop/start, timing word, no cuts; no history copy.
- **New from a canvas**: "no such canvas: <path>". The canvas kind
  (montage or interview) is detected unless given; montage canvases and
  interview canvases are converted by the canvas converter (not this
  section's part). `written: <time> by Timeline Cards (new from canvas)`.
  - Dry run answers: kind, canvas file, name, target file, cut count
    (montage: cuts; interview: matched cards), notes, timing, alternates,
    cards put on the shelf, unmatched/skipped count, source clips, a
    per-clip "<clip>: <what timed it>" line (whisper, library, .srt, or its
    error), and the shelf categories the canvas groups become.
  - The real write titles the document with the NEW file's name (the
    canvas name stays in `canvas:`), saves with no history copy, and clears
    the conversion cache.
  - **Conversion cache**: one conversion kept for 30 minutes, keyed on the
    canvas path, its modified time and size, the root, kind, rates, drop,
    start, timing, project, and the same library connection. The dry run and
    the write reuse it. Only one conversion runs at a time across the
    server; a second caller for the same canvas waits and then reuses it.
  - **Prewarm**: converts into that cache in the background as soon as a
    canvas is picked (before a name is typed). Never raises; failures are
    logged: "the canvas prewarm did not finish: ...".
- **Memory of the last file per root**: kept in `cards_pick.json` in the
  data folder (`CARDS_DATA` environment variable, else beside the server
  code), under `projects`, keyed by the normalised root path. The file is
  shared with the live view's library pick; writes read, merge and
  atomically replace so neither loses the other's key. A failed write is
  logged ("the pick was not saved: ...").
  - Choosing the live timeline is remembered as `:live`.
- **Which file a root opens on**: the remembered one if it still exists;
  none if the editor last chose live; otherwise the newest cut list that
  parses; otherwise none.

## The Resolve agent on an editor's computer, and the server end that talks to it

(source: agent.py, config.py AGENT_* / RELEASE_WAIT_S / RELOAD_WAIT_S / LIB_POLL_S / MIRROR_* / KEYS_FILE)

Two halves: the **agent** (runs next to Resolve, no web server of its own,
nothing needs forwarding to that PC) and the **server end** (a Timeline
Cards server, for example the container on the NAS, whose cards come from
the agent or, when it is away, from Resolve's project library).

### The agent process (`reorder_web.py --agent`)

- Started with the server address, a shared token, the episode root, an
  optional machine name (default: the computer's host name) and an
  optional outside Resolve connection ("bridge"); with none it uses its own
  guarded connection. A bare address gets `http://` in front.
- It runs the full Resolve engine locally (the sweep and every edit, as in
  the sections above) and plays the browser's part towards the server.
- **Push loop (every 0.1 s tick)**: when the engine's state version changed,
  POST the full state to `/agent/state` with: token, machine name, the
  state, timeline id and rate, the clip facts (every media pool clip it
  knows: name, rate and start timecode for clips with a transcript, and the
  media file path; vault-only `clip:` ids are never sent), when it last
  walked the media pool, Resolve's keyboard preset for the lane, the
  project database details, and the playhead (90 s timeout). When only the
  playhead moved, or at least every 5 s as a heartbeat, a playhead-only
  ping (20 s timeout); if the server answers `resend`, the next tick pushes
  the full state. Network failures are logged ("push failed: ... (retry in
  Ns)") and retried with backoff doubling from 1 s up to 30 s; after a
  failure the whole state is resent.
- **Pull loop**: long-polls `/agent/pending?wait=25&token=...` (client
  timeout 45 s), backoff 1 s doubling to 30 s on failure. A playhead jump
  and a WAV render request ride along on any answer and are handed to the
  engine. A request with an id is applied.
- **Applying one request**: it is handed to the local engine's queue and the
  agent waits for the engine to finish it, up to 480 s (4 x 120 s). If the
  engine never picks it up: "the Resolve engine never picked that edit up
  (no timeline open?)". The result is POSTed to `/agent/result` with ok,
  note, error, inserted cut id, the timeline name a conform actually built,
  and the cut-id renames; posting is retried 5 times (waits 1, 2, 4, 8, 16
  s). Requests carry the token in an `X-Cards-Token` header (and in the
  body or query).
- The agent never stops on network errors; Ctrl+C ends it.

### Server end: is the agent there, and is its Resolve usable

- **Agent present** = heard from within the last 40 s. Away text: "no
  Resolve agent has connected yet" or "Resolve agent away since HH:MM:SS".
- **Token check**: constant-time comparison; an empty token never matches.
- **Resolve state** as last reported: ok, "no timeline" (Resolve open with no
  timeline: "<machine>: Resolve open, no timeline (conform is available)"),
  or gone ("<machine>: Resolve is not reachable (<error>)").
- Agent info published on every state: connected, last seen, name, Resolve
  state and note, and when that machine last walked its pool.
- A server nobody has pushed to yet is a working page (amber note): "no
  Resolve agent yet -- pick a cut list or canvas; the agent is only needed to
  conform or edit live".

### Server end: sending jobs to the agent (the rules)

- One job at a time; ids are increasing numbers.
- Refusals when queuing:
  - no agent: "<away text> -- the edit was not sent";
  - Resolve gone (or no timeline, for an edit): "<stale or resolve text> --
    the edit was not sent". Exceptions: release and reload always go; a
    conform goes unless Resolve is truly unreachable (no timeline is fine).
  - the page is showing a different timeline from the one the agent has open
    (edits only; conform, release, reload exempt): "<machine> has <timeline>
    open, not <picked> -- open it in Resolve to edit".
- **Stale job**: a job no agent collected within 120 s is dropped: "<away
  text> -- the edit was dropped".
- **Lost job**: if the agent polls again while a job it took is still
  unanswered, that job is abandoned: "the Resolve agent went away with that
  <kind> -- it was never confirmed".
- If the reply carrying a job never reached the agent, the job (and any jump
  or render request) is put back in the queue.
- A result for a job that is no longer open: "that request is no longer
  open".
- Long-poll wait is capped at 25 s; the server checks for new work every
  0.5 s while waiting.

### Server end: what a push does

- A playhead-only ping updates the playhead and answers `resend` until a full
  state has arrived since the server started.
- A full push binds the project database the agent named, learns the clip
  facts (and queues each new clip's transcript read in the background so
  transcripts and search work while the agent sleeps: "transcript ready:
  <clip>"), records the pool-walk time, and caches the keyboard preset to
  `cards_lane_keys.json` in the data folder (so a restarted server keeps the
  lane's keys).
- A push with no cards and an error (or not connected) marks Resolve gone,
  keeps the last cards on screen marked stale ("<machine>: <error> since
  HH:MM:SS -- showing the timeline as last seen at HH:MM"), and refuses edits.
- A push with cards clears that, remembers which timeline the agent is live
  on (saved in `cards_pick.json`), and publishes the cards (re-grouped and
  with this server's own notes and plans), unless the page has picked a
  different timeline, in which case the push is held back and only its facts,
  heartbeat and render progress are taken.
- The served state always carries this server's own episode root and name,
  where the cards came from, and the pick.

### Server end: the mirror (last good timeline on disk)

- After pushes, the last good state (cards, clip facts, names, media paths,
  database details, playhead) is written to `cards_mirror.json` in the data
  folder, at most once per 3 s burst, atomically. Failures are logged.
- At start the mirror is shown at once, marked "showing the timeline as last
  seen at HH:MM -- no push since this server started", and it is the
  "follow Resolve" target until the agent speaks. Not used by a cut-list
  server.

### Server end: reading the timeline from Resolve's project library (agent away)

- **Which source wins**: the agent when it is present, its Resolve is usable,
  and it is on the picked timeline (it can see unsaved edits); otherwise the
  project library if the server knows where it is and something is picked;
  otherwise whatever is already shown.
- **Library sweep** every 2 s in the background (woken early on a pick): a
  cheap fingerprint first, a full read only when the timeline was saved
  since. Cards are built from the saved items (source out derived from
  duration at the clip's rate, audio fades from the library's audio rows)
  and markers. Stale line: "from the project library, saved HH:MM:SS (<why:
  machine has <timeline> open | machine: <error> | away text>)". The
  playhead is shown only if the agent is on the same timeline. Undo is off
  for library-sourced cards. Errors are logged and recorded.
- **Where the library is**: `--db-host` / `CARDS_DB_HOST`, `--db-name` /
  `CARDS_DB_NAME`, else what the agent pushed.
- **Default timeline with no agent ever**: the current timeline of THIS
  episode's Resolve project (a library project named exactly like the root
  folder, else one whose name starts with it); none if no project matches.
  Cached; a miss is retried at most every 30 s.
- **POST /api/library/pick**: `{"follow": true}` goes back to whatever the
  agent has open; otherwise `{db, project, tl}` is looked up in the library.
  Refusals: "pick a library and a timeline"; "this server does not know
  where the project library is (--db-host)"; "no timeline <id> in <db>". The
  pick is saved to `cards_pick.json` (merged with the cut-list memory) and
  shown at once.
- **GET /api/library**: the host, the list of libraries, the chosen library's
  projects, and the chosen (or first) project's timelines, plus the pick,
  source, agent's timeline and last error. With no library known: "this
  server does not know where the project library is (--db-host /
  CARDS_DB_HOST)".

### Server end: writing Resolve's project library directly (no Resolve needed)

- **Writer availability** (lazy, never fatal): off unless `--db-write-allow`
  / `CARDS_DB_WRITE_ALLOW` names at least one library ("this server may not
  write any project library (--db-write-allow / CARDS_DB_WRITE_ALLOW is
  empty)"); needs a known host ("this server does not know where the project
  library is (--db-host)"; retried after an agent push); "library_writer is
  not available: ..."; "the library writer would not start: ...". Backups
  go to `--db-backups` / `CARDS_DB_BACKUPS`, default `library_backups` in the
  data folder.
- The in-place editor is built on the writer the same way ("library_edits is
  not available: ...", "the library editor would not start: ...").
- "Ready" = a writer exists and the library being shown is on the allow
  list.

### Server end: POST /api/conform for a live timeline's draft (independent mode)

- Body: `name`, `cuts` (from the page), `via` (`agent`, `library`, `auto`;
  else "via must be agent, library or auto"), `markers`, `handshake`.
  "the new timeline needs a name"; "nothing to conform -- the draft is
  empty". Each gap's note is attached from this server's notes store.
- `auto`: the agent when present and Resolve is reachable (no timeline
  needed), else the library.
- **Agent**: queued as a conform job ("an edit is already being applied --
  wait a moment" if busy). What the agent then does is "Conform through the
  Resolve API" above.
- **Library route** (all gates checked before anything happens):
  - no writer: "<away text>, and this server cannot build it in the library
    either: <why>" (agent away) or "this server cannot write the project
    library: <why>";
  - "this server does not know which library and project to build in --
    pick a timeline in the options drawer first";
  - "<db> is not a library this server may write (--db-write-allow: ...)";
  - "could not read <project>'s lock in <db>: ...";
  - Resolve holds the project and no agent: "Resolve on <machine> has the
    project open and no agent is connected to close it -- close the project
    or start the agent"; and with `handshake: false`: "Resolve on <machine>
    has the project open and this request refused the close/reopen -- close
    the project in Resolve first";
  - busy: "an edit is already being applied -- wait a moment".
  - Then in the background: if locked, the close half (below); progress note
    "conforming into the library…"; cuts that name an item of the picked
    timeline are pinned to that item's own saved span (failure logged, spans
    sent as they are); the write; the reopen half; then the page is moved to
    the new timeline and it is read back. Note: "built '<name>' in the
    library: N cut(s), X.X s -- N marker(s)<gap notes clause><reopen note>".
    Any failure is reported with the reopen note appended, and the page is
    never left waiting.

### The close/reopen handshake (so a library write is not lost)

- Why: Resolve does not re-read its project library while it has the
  project open, so a write under an open project would be silently
  overwritten.
- **Close half**: page note "closing <project> on <machine> so the library
  can be written…"; the agent is asked to release (save and close) the
  project and must answer within 60 s ("the agent did not answer the release
  in 60 s"); a refusal: "the agent did not release <project>: <reason>".
  Then the lock must be gone; if another machine still holds it: "<machine>
  still has the project open after the close -- nothing was written".
- **Reopen half** (always attempted once the project was closed, even if
  the write failed): the agent is asked to reload the project on the new
  timeline (or the same timeline, for an in-place apply), within 120 s.
  Notes: " -- Resolve reloaded"; " -- Resolve was NOT reopened (<reason>):
  open <project> in Resolve by hand"; " -- Resolve could not be reopened
  (<reason>): open <project> by hand". A successful reload clears the
  "Resolve gone" state and asks the agent for a full state.
- Only one handshake request at a time: "the agent already has a request in
  flight -- the <kind> was not sent". Handshake results do not count as an
  edit result.

### Applying a staged draft into the timeline it was staged on (in place)

- **POST /api/plan/apply** body: `tl`, `rev`, `cuts`, `markers`, `bank`
  (default on: removed pieces go to an offcuts timeline in the library),
  `via`, `handshake`, `dry_run`.
- Gates in order: "via must be agent, library or auto"; "which timeline's
  draft? -- no tl was sent"; "nothing to apply -- the cut list is empty"; "a
  cut with no clip cannot be applied -- every cut needs its mp_uid"; the
  page's draft revision must match the server's, else a conflict answer
  carrying the current plan; "nothing is staged -- there is no draft to
  apply into the library".
- `auto` becomes `agent` when the agent is present, Resolve usable and the
  cards are not library-sourced; `agent` answers `{ok: false, via: agent,
  hint: "run the queue from the page"}` (the page then replays the edits as
  keystrokes).
- Library: "this server cannot write the project library: <why>"; "this
  server cannot edit the project library in place: <why>"; the target
  timeline (the pick, else the last swept id, else looked up by the name the
  page sent; if the pick and the page disagree, the page's name wins) or
  "this server does not know which timeline to write the draft into (<db> /
  <project> / <timeline>) -- pick the timeline in the options drawer first"
  / "could not look '<name>' up in <db>: ..."; allow list; lock read; lock
  with no agent / handshake refused (same sentences as the conform); busy.
- Background: if the project is open, the change is planned first; if it is
  a preview or the timeline already equals the draft, nothing is closed or
  written. Otherwise close, "applying the draft into the library…", apply,
  reopen on the same timeline.
- Notes: "applied the draft into the library: N moved · N trimmed · N new ·
  N removed → <offcuts name> · N marker(s), N rows, X.X s"; "'<timeline>'
  already is the draft: nothing was written"; "preview only (nothing
  written) -- ...".
- After a real apply, the server clears the draft for every device (ops
  emptied, mode back to immediate, recorded as "library apply"), remembers
  the backup for undo (in memory only, per timeline), and re-reads the
  timeline.
- **POST /api/plan/undo_library** `{backup, tl, handshake}`: "which backup?
  -- no backup path was sent"; only a backup this server wrote this session
  ("this server did not write that backup -- undo it with library_edits.py
  by hand"); writer/editor, lock and busy gates as above. Background: close
  if needed, "undoing the last library apply…", restore and re-verify,
  reopen. Note: "undone: N row(s) put back into '<timeline>'<reopen note>".
- The state carries the last in-place apply's backup, time, summary and note
  per timeline so the page can offer the undo.

### Notes and marks written on the server while cards come from the agent

- When a note, stack mark or summary changes on the server, the last state is
  re-grouped with the new notes and served again (nothing on that server
  sweeps).

## The guard before connecting to Resolve's scripting server

(source: resolve/resolve_script_server.py)

- **What it decides**: whether any script may connect to Resolve's
  scripting API right now, without connecting. It reads the operating
  system's TCP table and process list only.
- **Four answers**:
  - READY: a listener on TCP 1144 owned by Resolve's script server process
    (`fuscript.exe` / `fuscript`), and an established connection to 1144
    from that server's parent process (or a process named `resolve.exe` /
    `resolve` / `davinci resolve`), not this process itself. Reason "Resolve
    (pid N) is registered with its script server".
  - STARTING: the server is up but Resolve has not registered. Reason
    "script server pid N is up but Resolve has not registered with it yet".
  - ABSENT: nothing listening on 1144. Reason "no script server listening on
    1144".
  - UNKNOWN: port 1144 held by something else ("port 1144 is held by <name>,
    not Fusion's script server"), the table could not be read ("probe
    failed: ..."), or an unsupported platform ("no script-server probe on
    <system>").
- **Connect only on READY or UNKNOWN** (fail open only when the probe itself
  is in doubt). STARTING and ABSENT both mean "do not connect". Never raises.
- **Answers are cached for 0.25 s.**
- **Platforms**: Windows reads the IPv4 and IPv6 TCP tables and the process
  snapshot directly (no subprocess). macOS runs `lsof -nP -iTCP:1144 -F
  pcRnT` with a 5 s timeout (lsof's "nothing matched" is ABSENT); any parse
  failure is UNKNOWN. Linux and anything else: always UNKNOWN, so it always
  connects.

## Driving Resolve's own UI where the API cannot (`pipeline.py resolve-ui`)

(source: resolve/resolve_ui.py) Windows only (Win32, UI Automation,
AutoHotkey v2). Safe while Resolve is launching: it never touches the
scripting server. Every command is also an importable function.

- **`windows [--all] [--title T]`**: lists Resolve's top-level windows (found
  by `Resolve.exe` process ids via `tasklist`): handle, visible flag, class,
  position, size, title. Hidden dialogs only with `--all`. None: "(none -- is
  Resolve running?)".
- **`tree [--title T] [--depth 3] [--limit 400]`**: the UI Automation tree
  under a window (default the main window), one indented line per control
  with its type, name and rectangle; "... (limit reached, raise --limit)".
- **`menu "File > Project Settings..."`**: brings Resolve to the front and
  invokes a menu item by its path; each step matched case-insensitively with
  "..." matching Resolve's ellipsis character. **`menu --list MENU`**: lists
  a menu's items ("--- separator ---" for separators). Refusals: "empty menu
  path"; "no top-level menu '<x>' (have: ...)"; "menu '<x>' did not open";
  "no item '<x>' under '<path>' (have: ...)"; "submenu '<x>' did not open";
  "no menu bar found on the Resolve window". Open menus are dismissed with
  Escape on failure or after listing. Submenus are waited for up to 1.5 s.
- **`wait --title T [--timeout 10] [--gone]`**: blocks until a matching
  window is visible (or gone), polling every 0.15 s; "'<t>' still there |
  missing after N s".
- **`shot [--title T] [--out file.png]`**: screenshot of a window, captured
  even when behind other windows; if the result is almost black (Resolve's
  OpenGL viewers), Resolve is brought to the front and the screen area is
  grabbed instead. Default output `%TEMP%\resolve_<title>.png`. "window has no
  area: ...".
- **`keys "^+a" "e"`**: sends AutoHotkey key expressions to Resolve via the
  same helper script the live edits use (it activates Resolve, blocks stray
  input while typing, restores the previous window). Prints "sent" or
  "FAILED (code 2)" when Resolve would not come to the front; the exit code
  is the helper's.
- **`click --at X,Y [--title T] [--right] [--double]`**: clicks a point
  relative to a window's top-left; exits 2 if Resolve is not found or does not
  become active within 3 s. "--at wants X,Y".
- **`press --title T NAME [--control ButtonControl|any]`**: invokes a named
  control (for example a dialog's Save button), searching 6 levels deep. "no
  <control> named '<x>' in '<title>'".
- **`close --title T`**: sends the window a close message (which cancels most
  dialogs).
- Window matching: a title containing the text, case-insensitive; several
  hits must include exactly one exact match ("'<t>' is ambiguous: [...]");
  none: "no visible window matching '<t>'". "Resolve is not running" when no
  main window.
- AutoHotkey looked for at `AUTOHOTKEY`, then the per-user and Program Files
  v2 paths: "AutoHotkey v2 not found -- install it or set AUTOHOTKEY to
  AutoHotkey64.exe". Missing `uiautomation` package: "uiautomation is not
  installed -- `py -3.12 -m pip install uiautomation`. ...".
- The process sets itself per-monitor DPI-aware on import so clicks land
  correctly on high-DPI screens.

## Waiting for a theme selection (`pipeline.py wait-for-selection`)

(source: resolve/wait_for_selection.py)

- Arguments: a proposal JSON file and an optional timeout in seconds
  (default 7200, two hours). Reads the file every 5 s; when its `selected`
  list is non-empty it prints that list as JSON and exits 0. A file being
  written or not yet created is ignored. On timeout prints "TIMEOUT: no
  selection was saved in the Theme Picker" and exits 2. (Nothing to do with
  Resolve despite living in this folder.)

## Building per-camera angle timelines from a bin (`pipeline.py build-angle-timelines`)

(source: resolve/build_angle_timelines.py)

- Purpose: cameras that split a recording into many files make Resolve's
  multicam builder see every file as an angle. This lays each camera's files
  on its own timeline (one timeline per angle), or all cameras on one
  timeline, so the multicam can then be made by hand in Resolve ("Create New
  Multicam Clip Using Selected Clips", Angle Sync: Sound).
- Flags: `--bin NAME` (required; searched anywhere in the media pool, "no bin
  named '<x>' in project '<p>'"), `--angles a,b` (camera prefixes, angle 1
  first; default largest group first, ties by name), `--fps N` (timeline
  rate; required when the bin mixes rates), `--single` (one timeline with
  camera N on video N / audio N), `--sync auto|wall|tc` (default auto),
  `--prefix` (timeline name prefix; default the bin name), `--apply`
  (default is a dry run: "dry run -- nothing created. Re-run with --apply.").
- Clips considered: media of type "Video + Audio", "Video" or "Audio" with a
  start timecode, frame count and rate (timelines, multicams, stills and
  compounds are skipped). None: "no timed clips in that bin".
- Camera grouping by file name: the text before the first `_` or `-`
  (`fx3_20260521_9490.MP4` -> `fx3`, `A001_06271102_C250.braw` -> `A001`),
  else the name with its trailing number removed (`party04120164` ->
  `party`). Unknown prefix in `--angles`: "no clips match camera prefix ...
  (found: ...)".
- Mixed frame rates without `--fps`: refused, naming the rates and the drift
  ("bin mixes frame rates ... -- one camera must be conformed to the other.
  Pass --fps to choose the timeline rate (the drift within a take is X%,
  about X frames per minute).").
- Placement clocks:
  - `wall`: each file at its "Date Created" time (1 s resolution), one zero
    shared by all cameras. A file with no readable date: "no readable Date
    Created on N clip(s), e.g. <x> -- use --sync tc".
  - `auto`: per camera, its timecode read as a time of day if it stays within
    3 s of Date Created across all files (free-run timecode), else Date
    Created. Prints the clock chosen per camera.
  - `tc`: each camera by its own source timecode from its own first frame.
- The dry-run report: per angle, file count, total material, span, start,
  and each file's time, offset timecode, frame count and any "<-- GAP".
  "NOTE: N camera groups detected, not 2." when not two.
- Build (per angle): timeline "<prefix> — ANGLE n (<camera>)" created in the
  bin, custom settings with the chosen rate and drop-frame flag, every file
  appended whole (video and audio together, linked) at its offset; gaps kept.
  Any existing name: "timeline(s) already exist: ... -- rename or delete them
  first". Not every file placed: "timeline '<x>': Resolve placed N of N
  clips". Ends with the hand-step instruction.
- `--single`: timeline "<prefix> — SYNC", one video and one stereo audio
  track per camera, tracks named "n <camera>". Ends with "Both cameras are on
  one timeline in <bin> -- V1/A1 and V2/A2 share the same zero, so what lines
  up vertically happened at the same moment."
- Drop-frame timecode handling as elsewhere (2 frames per minute dropped
  except every tenth; 4 at 60 fps).

## Frame-accurate audio sync of a two-camera SYNC timeline (`pipeline.py sync-angles`)

(source: resolve/sync_angles.py)

- Measures how far each take of each camera sits from the reference camera
  by comparing loudness envelopes, and optionally builds a corrected copy.
- Picks the timeline named by `--timeline` ("no timeline '<x>' (have:
  ...)") or the single one whose name ends in "SYNC" ("name the timeline with
  --timeline (found N ending in SYNC)"). Reference camera on video track
  `--ref-track` (default 2; "no clips on video track N").
- Audio is decoded with ffmpeg to mono 8 kHz and reduced to a 250-per-second
  loudness envelope, cached in `%TEMP%\sync_angles_env` keyed by file name
  and modified time.
- Per camera: first a whole-track constant offset searched within
  `--coarse-window` seconds (default 300; 0 disables), printed with its
  correlation. Then each take is matched within `--window` seconds (default
  4) of where it should be. A match counts if its correlation is at least
  `--min-peak` (0.35) and it beats the best rival more than 0.5 s away by
  `--min-margin` (0.05). Takes shorter than `--min-seconds` (3), silent, or
  with no reference audio under them get no measurement. The median of the
  good matches is the consensus; a good match more than `--tolerance` seconds
  (1.5) from it is an "outlier". Every take without a good match is moved by
  the consensus.
- Printed per take: frames and seconds of correction, peak, margin, and
  "WEAK/OUTLIER -> consensus +N f" or "no reference audio -> consensus";
  per camera "N/N matched: consensus ..., spread ..." or "nothing matched".
- Without `--apply`: "measure only -- nothing changed. Re-run with --apply to
  rebuild."
- `--apply`: a NEW timeline (`--out`, default "<name> FRAMESYNC"; an
  existing name is refused) with the same rate, drop-frame, track count and
  track names, every take re-placed with the same source in/out at its
  corrected position; if anything would land before the start, all tracks
  shift together. "track N (<name>): placed N of N" on failure. The original
  is left untouched: "Original timeline is untouched; compare the two before
  deleting either."

## Slipping angle-timeline picture onto its audio, in place (`pipeline.py resync-angles`)

(source: resolve/resync_angles.py)

- For every timeline whose name contains "— ANGLE" (optionally filtered by
  `--only <text>`, repeatable; none: "no ANGLE timelines match"), measures
  each V1 video item against the A1 audio under it and, with `--apply`,
  re-lays the picture so it matches. Audio track 1 never moves.
- Measurement: 6 probes (`--probes`) spread across the item; each takes a
  15 s window of the A1 audio and searches ±40 s of the camera's own audio
  around where it should be (ffmpeg, mono 8 kHz, only that window decoded).
  A probe counts at a correlation of at least 0.15 (`--min-peak`). An item
  needs at least 3 good probes and half of those that ran; the good probes
  must agree within 2 frames of their median. Otherwise "UNSURE -- N of N
  probes matched (peak >= X), N needed" or "the probes disagree: ..." and it
  is left alone. The camera audio file is found by the angle-building
  module's audio-path rule; if that fails: "NOT MEASURED: <reason>".
- Printed per item: the picture correction in seconds, drift across probes,
  probes matched, peaks, and "in sync" (under `--min-frames`, default 1) or
  "SLIP +N frames"; "-- DRIFT over a frame: a slip cannot fix it" when the
  probes spread more than a frame. Summary "N item(s) to slip, N not
  measurable". `--report file.json` writes every measurement.
- Without `--apply`: "dry run -- nothing changed. Re-run with --apply."
- `--apply`, per item: delete the V1 item and append the same clip again,
  video only, at the same record frame from the corrected source frame, same
  length (cut short at the end of the file); if the picture would start
  before its file, the item starts later instead. If Resolve lands it a frame
  off, it is deleted and re-laid once with the difference. The item's colour
  is restored. A1 is compared before and after; any change stops the run:
  "A1 CHANGED -- stop. ...". Refusals: "Resolve refused to delete <item> --
  nothing changed"; "the append of <item> FAILED after its delete -- V1 has a
  hole at record frame N; source a-b"; "the second append ... FAILED". The
  previously open timeline is made current again at the end.

## Putting the Zoom recording on A1 of every angle timeline (`pipeline.py zoom-into-angles`)

(source: resolve/zoom_into_angles.py)

- Flags: `--root` (episode root in the vault; required; "no Interviewees
  under <root>"), `--media` (media Interviewees root; default
  `P:\Projects\2026\FF5\Film 1 + 2\Interviewees`), `--only <text>`
  (repeatable), `--min-peak` (default 0.25), `--join-tolerance S` (default
  20), `--no-normalize`, `--normalize-only`, `--apply`.
- Needs a project open ("no project open in Resolve") and timelines named
  "<name> — ANGLE n" ("no '<name> - ANGLE n' timelines in this project").
- Matching an angle timeline to people: the vault interviewee folder and the
  media folder are matched by their romanised words as a set (Chinese
  characters ignored; one name may carry an extra given name if at least two
  words match). A trailing session number ("母母女子 2") is dropped if needed.
- Reference: the `*Multicam.wav` in the vault interviewee folder. Zoom files:
  names like `######_###.wav` in the media folder, longest first. Missing
  reference or folder: "(no reference WAV or no media folder)"; no Zoom: "**
  no Zoom recording -- left as it is **"; nothing correlates: "** nothing
  correlated above X -- left as it is **".
- Every Zoom file whose loudness envelope correlates at or above the minimum
  is placed at its measured offset. A split recording's later part is
  expected where the previous part ended; if its measured offset is more than
  the join tolerance away, the expected position is used and the run says
  so.
- Per angle timeline: if A1 already carries exactly those Zoom files it is
  skipped. Otherwise the new audio covers exactly the record span the old A1
  audio covered (or the whole timeline if A1 was empty), never more; source
  frames are counted at the WAV clip's own rate. Printed: timeline, Zoom
  files, offsets, peaks, coverage %, and what A1 had.
- `--apply`: deletes the old A1 items, appends the Zoom parts (audio only),
  then sets Resolve's per-item loudness normalisation to EBU R128 -23 LUFS
  (unless `--no-normalize`; "note: Resolve refused R128 on <item> -- the
  audio is placed, its loudness is untouched"). Stops with exit 1 if Resolve
  placed fewer parts ("A1 is now PART-BUILT, fix by hand") or the timeline's
  length changed ("LENGTH MOVED a -> b frames"). Success: "ok <timeline>: A1
  replaced, N frames, length unchanged (N)".
- `--normalize-only`: places nothing; sets R128 on every A1 item of every
  angle timeline ("would set" dry, "set" or "Resolve REFUSED" applied); stops
  if a length moves; "A1 is empty" where there is none.
- Summary: "[DRY RUN: ]N angle timeline(s) would be rewritten | rewritten, N
  interviewee(s) skipped", then "re-run with --apply to write them".

## One interviewee bin to frame-accurate angle timelines (`pipeline.py interview-angles`)

(source: resolve/interview_angles.py)

Reads one interviewee bin (its own clips only, never sub-bins), decides what
is an interview take, splits the day into sessions, lays every recording
device on one clock, measures audio sync from the files before building,
and then builds one "ANGLE" timeline per camera with every take already in
place. It stops before the multicam (hand step: select the ANGLE timelines
-> "Create New Multicam Clip Using Selected Clips", Angle Sync: Timecode).

- **What each angle timeline holds**: that camera's picture, video only, on
  V1; the chosen sound device's audio, audio only, on A1 (the same audio on
  every angle). A stereo A1 is added if the timeline has none. Timelines are
  named "<prefix> — ANGLE n (<device>)" (prefix default the bin name, plus
  " <session>" when the bin has several sessions) and put in a sub-bin
  `--angles-bin` (default "Angles", created if missing: "could not create the
  sub-bin '<x>'"). Custom timeline settings: the chosen rate and drop-frame
  flag.
- **Devices** from file names: `*_Wireless PRO.wav` = "lav"; `######_###.wav`
  = "zoom"; `########_ff...` = "ff"; otherwise the camera rule of
  build-angle-timelines (text before the first `_`/`-`, else name minus
  trailing digits).
- **What is excluded** (each printed with the reason): `--exclude` names;
  non-media types ("not media (Type '<x>')"); no start timecode / duration /
  rate; no readable Date Created; under `--min-clip` seconds (default 3) unless
  `--include`d ("N s, under the 3 s floor"); a video clip shorter than
  `--min-take` (default 300 s) unless another camera's long take overlaps it
  in wall time ("<len> stray: no interview take of another camera overlaps
  it"); audio outside the span of the kept video ("<len> of audio outside the
  interview") unless it is dated on another calendar day than most of the
  video, which keeps it. `--devices a,b` keeps only those devices ("--devices
  ... names none of ..."). Nothing left: "nothing in that bin looks like an
  interview take". Audio-only items with an empty frame count get it from
  their duration timecode.
- **Clocks per device**: a device's timecode is used as time of day if every
  clip has a start timecode and a date, none is 00:00:00, and every clip's
  timecode is within `--tod-tolerance` (60 s) of its Date Created; takes
  crossing midnight are corrected by a day. Otherwise Date Created (1 s
  resolution). `--clock DEVICE=tc|wall` (repeatable) forces it ("--clock
  wants DEVICE=tc or DEVICE=wall, not '<x>'"); `tc` on a record-run camera
  butt-joins its takes from the first take's date. Timecode is read as the
  label (frames divided by 30).
- **Wrong-day devices**: a device whose clips are dated on another day than
  most video is moved so its first clip starts at the reference's first
  take, and left to the audio sync (noted in its clock line).
- **Sessions**: kept video sorted by time; a gap over `--session-gap` (30
  min) after everything so far starts a new session. With several sessions,
  `--apply` refuses until `--session N` is given ("N sessions in that bin --
  name one with --session N (or --no-sessions to lay them out together)");
  a dry run builds session 1. "bin has N session(s), not N". `--no-sessions`
  treats the whole bin as one.
- **Timeline rate**: `--fps`, else the rate shot by the most cameras (ties to
  the lower). Drop-frame: `--drop auto|on|off` (auto: on if any kept clip at
  that rate has drop-frame timecode). Mixed rates are allowed and noted:
  "NOTE: this bin mixes ... fps. Resolve retimes the odd one out onto the
  timeline ... its frame boundaries fall up to half a frame off the grid you
  cut on."
- **Reference device for sync**: `--reference`, else zoom, else lav, else the
  camera with the most frames ("no device '<x>' (have: ...)"). No video at
  all: "no video device in that session".
- **Audio sync** (skipped with `--no-sync`): envelopes from the files (as in
  sync-angles); BRAW files are decoded from their `Proxy\<stem>.mp4` sibling,
  and a missing proxy refuses: "<file> is BRAW and ffmpeg cannot decode it;
  its proxy <path> is missing. Generate proxies for that camera, or
  --no-sync to lay the bin out by clock alone." Per device: coarse offset
  within `--coarse-window` (default 900 s; 0 off), then per take within
  `--window` (4 s), with `--min-peak` 0.35, `--min-margin` 0.05,
  `--min-seconds` 3, `--tolerance` 1.5 s, consensus and outliers as in
  sync-angles. Takes with no audio track ("no audio track") or digital
  silence get the device's consensus. If no device correlates with the
  reference above 0.10: "WARNING: NOTHING in this bin matched the reference
  '<x>'. ... check it, then --reference (and --sound) another device."
- `--offset DEVICE=SECONDS` (or hh:mm:ss.s; repeatable): forces that device's
  offset instead of measuring ("--offset wants DEVICE=SECONDS"; "--offset
  names no kept device '<x>'"). Verdict "forced (--offset)".
- `--compact SECONDS`: any stretch longer than this that NO device covers is
  shrunk to 2 s ("compacted N stretch(es) nothing covered: <dur> removed").
- `--start-at` / `--end-at` (layout seconds or hh:mm:ss.s, as printed by the
  dry run after rebasing): trims every clip to that window and re-zeroes;
  clips wholly outside are excluded ("ends before --start-at" / "starts after
  --end-at"); nothing left: "--start-at/--end-at leave nothing on the
  timeline". Everything is shifted together so nothing sits before frame 0
  ("everything rebased +N f ...").
- **Angle order**: `--angles` ("no video device named ... (have: ...)"), else
  Blackmagic-style `A###` cameras, then `fx3...`, then the rest by name.
- **A1 sound device**: `--sound`, else the Zoom. **No Zoom is a refusal**
  unless `--sound` names another device: "REFUSING: no ZOOM recording in this
  bin (audio devices: ...). The Zoom is the interview's own microphone ...
  To build anyway, say which device A1 comes from: --sound <device>". "no
  device '<x>' to take A1 from (have: ...)".
- **Report** (always): devices, reference, A1 source, clock per device,
  sessions (marking the one being built), every take (device, file, clock,
  timeline position, nudge, peak, margin, verdict with seconds), EXCLUDED
  list, and TIMELINES with clip counts and lengths.
- `--plan-out FILE`: writes the whole plan as JSON ("plan written to ...").
  `--plan-in FILE`: builds a saved plan without measuring anything.
  `--media-pool-json FILE`: plans from a media pool dump without Resolve
  (dry run only; with `--apply`: "--media-pool-json is a dry run: it has no
  media pool items to append"; "no bin named '<x>' in that dump"); ends "dry
  run from a dump -- Resolve was never opened."
- Without `--apply`: "dry run -- nothing created. Re-run with --apply." "no
  bin named '<x>' in project '<p>'".
- **Build** (`--apply`): refuses existing names ("timeline(s) already exist:
  ... -- rename them first") and clips no longer in the bin ("not in the bin
  any more: ..."). Each timeline gets all its V1 and A1 items in one append
  (source in/out in each clip's own frame rate, end exclusive). Fewer placed
  than asked: "timeline '<x>': Resolve placed N of N items. It is left in the
  bin, half built: delete it by hand before the next run, which will refuse
  the name." Nothing existing is deleted or moved.
- **Verify after build**: reads each timeline back; V1 and A1 item counts
  must match the plan ("<-- WANTED N"), first and last item positions are
  printed, and every item's source in-point (as Resolve reports it) must be
  within one frame of the plan's, else "Error: ... starts X s into its file,
  the plan says X s (+X s) -- this angle is OUT OF SYNC; delete it before
  making a multicam". A Resolve that cannot report it: "(this Resolve cannot
  report <item>'s source time -- NOT checked)". Exit code 1 if verification
  failed, else 0.
- The audio-path rule (BRAW -> proxy) is also used by resync-angles.

## Making a multicam clip by driving Resolve's dialog (`pipeline.py multicam-ui`)

(source: resolve/multicam_ui.py, resolve/ref/angle_sync_timecode.png) Windows
only. Uses posted window messages (no AutoHotkey, no foreground window
needed, works in a disconnected remote session, does not move the editor's
mouse), UI Automation for menus, and screenshots of the dialog as its only
read-back.

- **Command**: `--bin NAME` (required), `--name NAME` (required),
  `--angle-sync Timecode|Sound` (default Timecode), `--timeout S` (default
  120: how long to wait for the clip to appear), `--dry-run` (open the
  dialog, fill it, screenshot it, Cancel, create nothing), `--shot-dir DIR`
  (where the dialog screenshot `new_multicam_clip.png` goes; default
  `%TEMP%`). Prints "multicam: <name>" or "FAILED: <reason>" (exit 1).
- **Pre-checks**: angle sync must be Timecode or Sound; Resolve's main window
  must exist ("DaVinci Resolve is not running"); no "New Multicam Clip" dialog
  may already be open ("a 'New Multicam Clip' dialog is already open --
  something else is mid-multicam. Deal with that one first."); a project must
  be open ("no project is open"). The bin is found by exact or normalised
  name anywhere in the pool; none: "no bin named '<x>' (have: ...)"; two or
  more: "N bins are named '<x>' -- rename one". A multicam of that name
  already in the bin (not on a dry run): "'<bin>' already holds a multicam
  called '<name>'".
- **Message-box janitor**: while it works, every 0.4 s it closes any Resolve
  window titled "Message" (which would otherwise freeze the scripting API).
- **Every API write is retried** up to 10 times, 0.7 s apart: "<what> never
  took effect -- a modal dialog is probably up in front of Resolve".
- **Step 1, select the whole bin**: make the bin current (verified by id),
  right-click a media-pool grid point to give the pool keyboard focus, close
  stray popups, run Edit > Select All, and check the selection is exactly the
  bin's clips by id; up to 4 tries. "bin '<x>' is empty: nothing to make a
  multicam of"; "Edit > Select All did not select the bin: N of N clips
  selected. The media pool probably does not have keyboard focus, or another
  script moved the current folder." One clip is allowed (a one-angle
  multicam).
- **Step 2, open the dialog**: right-click one of four fixed grid points
  (rotating), find the context menu item "Create New Multicam Clip Using
  Selected Clips..." and reach it by arrow keys (checking which item has
  focus, up to 40 steps: "walked 40 items of the context menu without '<x>'
  ever taking focus"), press Enter, wait up to 15 s for the dialog; up to 5
  tries. "could not open 'New Multicam Clip': the media pool context menu
  never carried '<item>' (tried 5 times). Is the media pool in list view, or
  scrolled so that (430, 200) is not over a clip?"
- **Dialog size check**: must be within 12 px of 450x463, else "New Multicam
  Clip is WxH, not 450x463: the field coordinates in this module were
  measured on the smaller one and would click the wrong thing. Screenshot it
  (pipeline.py resolve-ui shot --title 'New Multicam Clip') and re-measure."
- **Step 3, fill the dialog** (no clicks inside it): End + 160 Backspaces to
  clear the name field, type the name character by character (Chinese names
  survive); if the name cell's pixels never changed: "the Multicam Clip Name
  field never changed: the dialog did not open with it focused, so nothing
  typed landed anywhere". If the Angle Sync cell already reads as the wanted
  value (compared with a saved reference image; only Timecode has one), stop.
  Otherwise Tab 4 times, then probe with one Down at a time (up to 6 more
  Tabs) until only the Angle Sync combo moves, undoing any other combo that
  moved ("stepped <field> while looking for the Angle Sync combo and could not
  put it back -- cancel the dialog by hand and check that field"; "could not
  find the Angle Sync combo in the dialog's tab order (4 + 6 tabs tried)").
  Then Down until the value stops moving (3 misses = the end; "the Angle Sync
  list did not end after 7 Downs ..."), then Up the right number of rows for
  the order In, Out, Timecode, Sound, Marker ("Angle Sync stopped N row(s)
  above the bottom on the way to '<x>'"). Frame Rate, Multicam Audio and Angle
  Name must be unchanged, else "<field> changed while setting Angle Sync: the
  Tabs landed on the wrong control, so this dialog is not safe to Create".
  All other dialog defaults are left as Resolve has them (including moving
  the source clips into an "Original Clips" sub-bin).
- **Step 4, Create**: click Create; the dialog must close within 20 s
  ("Create did not close the dialog: Resolve refused the clip (a screenshot
  of the dialog will say why)"). Then poll the bin every 1 s, up to the
  timeout, for a Multicam clip with that name. If exactly one new multicam
  appears whose name is the start of the wanted name (dropped keystrokes), it
  is renamed through the API and checked ("the multicam arrived named '<a>'
  and the API would not rename it to '<b>'"). Timeout: "no multicam called
  '<x>' appeared in '<bin>' within Ns (N new clip(s) in the bin)".
- **Always on the way out**: an open dialog is cancelled (Cancel, then a close
  message; the dialog blocks every Resolve script while open), popups are
  closed, and the media pool is put back on the bin it was showing
  ("WARNING: SetCurrentFolder (restore) never took effect ..." if not).
- Importable as `create_multicam(bin, name, angle_sync, timeout, dry_run,
  shot_dir)`.

## Looks redundant or overlapping

- Four ways to get a cut list into Resolve, each with its own checks and
  messages: the agent's API conform (new timeline, appends + links), the
  library writer conform from a draft or a `.cut.md` (rows written into the
  database with a close/reopen handshake), the in-place library apply of a
  staged draft, and the page replaying edits as keystrokes ("run the queue
  from the page"). Plus the live keystroke editor itself.
- The live keystroke editor (move, delete, split, trim, extend, insert,
  overlay, marker, colour, undo) and the draft cut-list editor implement the
  same gestures twice, with different results: a live delete banks to an
  `offcuts` timeline, a draft delete stages to the shelf, and the library
  apply banks to an "OffCuts" timeline in the database.
- Two live undo mechanisms: the Ctrl+Z state walk and the legacy
  delete-and-re-append span rebuild with rollback.
- Timecode/frame conversion is written three times: `cards/timecode.py`,
  `build_angle_timelines` (`tc_to_frames`/`frames_to_tc`), and
  `interview_angles.tod_of_tc`.
- `conform.map.json` is searched and parsed twice, in the draft engine and in
  the conform planner, with the same folder list.
- Marker colour-to-kind rules exist twice and differ: `cutlist.marker_kind`
  (whole section-colour rotation = section, Green = note, else "marker") and
  `project_edit.marker_row` (Green = note, anything else = section).
- Audio cross-correlation is implemented four times: `sync_angles`
  (envelopes, coarse + fine), `interview_angles.measure` (a copy of the same
  rules, by its own comment), `resync_angles.best_match` (raw audio), and
  `zoom_into_angles.best_lag` (envelopes, whole-file).
- `build_angle_timelines` (wall-clock layout, then `sync_angles` to measure
  and rebuild) is superseded by `interview_angles` (does both in one pass)
  according to the latter's own description; both remain as commands.
- `resync_angles` and `zoom_into_angles` are one-off repairs of timelines
  `interview_angles` built wrongly; `zoom_into_angles` carries a hard-coded
  default media path for one episode (`P:\Projects\2026\FF5\Film 1 +
  2\Interviewees`).
- AutoHotkey is located by two different candidate lists (`cards/config.py`
  also searches PATH; `resolve_ui.py` does not).
- When the agent is away, cards come from two fallbacks: the on-disk mirror
  of the last push and the project-library sweep, each with its own stale
  message.
- The timeline-vs-file comparison has three entry points: the divergence
  chip on every state, `GET /api/diff`, and the `diff-project` command line;
  "update from timeline" exists both as a route and as `update-project`.
- The reference WAV render in the live engine repeats part of stage 2 of the
  transcript pipeline; the agent's whisper run repeats `pipeline.py
  transcribe` with hard-coded drive letters, beside a separate fleet path.
- The agent server tracks "Resolve gone" twice (`AgentLink._resolve_gone`
  and `ProjectAgentEngine._note_resolve`) with different republish
  behaviour.

## Claims the code does not back

- `project_conform.plan` and `ProjectEngine.items_and_markers` say their
  record-frame arithmetic is `_apply_conform`'s (each cut's length = source
  span scaled to the timeline rate). `_apply_conform` actually places one
  record frame per SOURCE frame (`rec += src_out - src_in`). For a clip whose
  rate differs from the timeline's, the dry-run durations, the draft cards'
  positions, and the marker frames the planner sends to the agent do not
  match where the agent places the cuts.
- `resolve_engine._apply_conform`'s docstring says "one API append per cut";
  cuts are appended in batches of 40 (retried one by one only when a batch
  returns nothing).
- `resolve_script_server.state()` says it returns READY, STARTING or UNKNOWN;
  it also returns ABSENT.
- `resolve/__init__.py` lists five modules; the package also holds
  `interview_angles`, `multicam_ui`, `resync_angles` and `zoom_into_angles`.
- `build_angle_timelines`' description says `--sync wall` is the default;
  the default is `auto`. Its description also says all cameras share ONE
  zero; in `auto` and `tc` modes the build (and `--single`) rebases each
  camera to its own first clip, so the shared zero computed for `auto` is
  thrown away and the `--single` closing message ("V1/A1 and V2/A2 share the
  same zero") is only true for `wall`.
- `sync_angles` says a take with no usable match is "reported, and left where
  it is"; the code moves every such take by the camera's consensus offset.
- `resync_angles` describes a `--agree` option; there is none (agreement is
  fixed at 2 frames of the median).
- `interview_angles`' description and its `--reference`/`--sound` help say
  the default is lav, then Zoom, then each camera's own audio. The code
  prefers Zoom, then lav, for the reference; and for A1 it refuses to build
  without a Zoom unless `--sound` is given.
- `project_agent` says three job kinds may go to the agent while a file is
  open; four can (`transcribe` as well).
- `project_diff`'s class table omits the `fade` class the code reports.
- `project_diff.update_from_timeline` says a section keeps the file's kind
  "and colour"; the colour is taken from the timeline's marker (the file's
  only when the marker has none).
- `ProjectEngine.tick` says "twice a second at most"; the file is checked at
  most once a second.
- `ProjectEngine`'s description speaks of "the twelve edit routes"; the draft
  worker accepts about thirty edit kinds (stage, sequences, paste, fade,
  gain, highlight, section move and more).
- `project_edit.extend` documents a refusal for lengthening past the end of
  the clip; the draft engine never passes the clip length, so in draft mode
  an out point can be extended past the end of the source without refusal.
- `zoom_into_angles` prints "DRY RUN: N angle timeline(s) would be
  rewritten", but N is only counted on `--apply`, so a dry run always says 0.
- `resolve_engine`'s live `_apply_transcribe` sets the progress text with a
  needless encode/decode of "starting…"; harmless, noted only because the
  text shown is "starting…" (with an ellipsis character) rather than plain.

## Could not determine

- The HTTP routes themselves (exact paths, methods, who may call them, status
  codes): the route wiring lives in the server/handler files, which this
  section was told not to read. Route names above (`/agent/state`,
  `/agent/pending`, `/agent/result`, `/api/conform`, `/api/library`,
  `/api/library/pick`, `/api/plan/apply`, `/api/plan/undo_library`,
  `/api/project/new`, `/api/project/prewarm`, `/api/project/update`,
  `/api/diff`, and the edit routes such as `api/reorder`) come from the
  engine code and its comments. The agent authenticates with a shared token
  (constant-time compare); whether every `/agent/*` route checks it could
  not be confirmed here.
- What the AutoHotkey helper `ripple_keys.ahk` and `keys.KeyHelper` do
  exactly, and how many undo frames `marker_frames(n)` counts (not in this
  part).
- Where Resolve's keyboard preset file is read from (`resolve_keymap.PREF`,
  outside this part) and what `lane_keys()` sends to the server.
- Exactly how gap notes become Text+ titles or markers (`gap_notes.py`), what
  the library writer and in-place editor write, back up and verify
  (`library_writer`, `library_edits`), and how a canvas becomes a cut list
  (`canvas_to_cutlist`): all outside this part.
- The error "kind" categories a draft refusal carries (`offline.error_kind`).
- Behaviour of the live keystroke editor on macOS or Linux: it depends on
  AutoHotkey and Windows window activation and would fail with "AutoHotkey v2
  not found"; whether any caller prevents that earlier is not visible here.
- Whether the mixed-rate conform mismatch noted above causes visible marker
  drift in practice (depends on Resolve's own retiming, not testable here).
