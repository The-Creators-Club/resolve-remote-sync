# Timeline Cards: sending to Resolve, the projects sheet and keep-on-this-device, the video window, the montage builder, markers

Terms used throughout:

- **Cut list**: one `.cut.md` file, the document the editor edits. Its **key** is its vault-relative path, `<episode>/Script Docs/Cuts/<name>.cut.md`.
- **Episode**: a vault folder that contains a `Script Docs` folder.
- **Cut**: one span of one clip in the cut list. **Gap**: a stretch of black between cuts, a row of its own. **Heading / marker**: a `## §` section, a `## ◆` note heading, a plain heading, or a `- (note)` row.
- **Shelf** (also "bench", "staged"): cuts kept beside the cut list but not in it.
- **Op**: one edit, sent through the editor's store, synced to every device and undoable. A **batch** op is several ops applied as one undo step.
- **Proposal**: a set of ops shown as a preview first, applied only when accepted, as one undo step.
- **Project library**: DaVinci Resolve's PostgreSQL project database.
- **Companion** (in this section): a Python child process the editor server starts to talk to a running Resolve. It is not the CC Sync tray companion.
- **Toolbar slot / keys slot / palette / overlay slot**: the editor shell's shared places where a feature registers a header button, a keyboard shortcut, a command-palette entry, or a floating panel.

Every `/api/...` route below is additionally subject to the editor server's general origin and host checks, which live outside this part.

## 1. Resolve and exports panel: the dialog itself

(source: features/resolve/client.ts, styles.ts)

- One modal dialog titled "Resolve and exports" with four tabs: "Send to Resolve", "Export", "Import", "Live". On a window 700 px wide or narrower the tab labels shorten to "Send", "Export", "Import", "Live".
- The dialog bar shows the open cut list's file name (without `.cut.md`), or "no cut list open".
- A Close button (icon only) in the bar; a "Close" button in every tab's footer; a click on the dark backdrop closes it.
- Escape anywhere in the dialog closes it.
- Left and Right arrow keys move between tabs when a tab has focus, and between the Export format tiles when a tile has focus (wrap-around).
- While the dialog is open, every key typed in it is kept from the editor's own shortcuts (Space does not play, Delete does not delete).
- Focus returns to whatever had it before the dialog opened.
- On a window 700 px wide or narrower the dialog is a bottom sheet the full width, up to 92% of the height; on a touch screen its close button and expanders grow to 44 px.
- Text typed into the timeline-name field keeps its caret across redraws; a button that becomes busy hands focus to the dialog so Escape and Tab keep working.
- Ways in:
  - Toolbar button "Export" (download icon, tooltip "Resolve and exports: export, import, send, follow", order 80): opens the dialog on the Export tab, or closes it if it is open.
  - Toolbar button "Send to Resolve" (order 81, tooltip "A dry run first, then the conform into the project library"): shown ONLY when the page has no header Send button of its own (`.hdr-send`). Opens the Send tab with a fresh dry run.
  - The header's own red "Send to Resolve" button (drawn by the views, outside this part) calls the same entry point. When the panel later closes after a successful send, a toast says "Sent to Resolve."; when it closes without a send, nothing is said; a failure toasts "Send to Resolve failed: <reason>".
  - Palette entries: "Send to Resolve" (keywords conform, timeline, library); "Export OTIO, FCPXML, EDL or the script" (opens Export); "Download the script as Markdown (.md)" (shows Ctrl+S); "Download the script as plain text (.txt)" (shows Ctrl+Shift+S); "Import a timeline from Resolve" (opens Import); "Follow Resolve's playhead" (opens Live); "Compare the cut list with its Resolve timeline" (compares now and opens Import).
  - Keyboard Ctrl+S: downloads the plain script as Markdown, from anywhere, including while typing in a text field. The browser's own "save page" is suppressed.
  - Keyboard Ctrl+Shift+S: downloads the plain script as plain text, same rules.
  - A standalone "Export" launcher button plus the drift chip can also be drawn into a host element by an older hand-mount; when the platform mounts the feature it adopts that panel and removes the hand-mounted launcher, so only one panel exists per page.
- Network errors: "the editor server cannot be reached"; a non-OK answer shows the server's `error` sentence, else "the server answered <status>".

## 2. Send to Resolve (the conform)

(source: features/resolve/client.ts, server.ts, bridge.py, python.ts)

### 2.1 The Send tab

- Lead text: the cut goes to Resolve through the existing conform; first a dry run; nothing is written until Send is pressed.
- "Timeline name" text field, pre-filled with the cut list's file name. Typing in it throws away the current dry run and any "sent" result. Enter in the field runs the dry run.
- "Check the plan" / "Check again" button (shows "Checking" while busy) runs the dry run. Opening the Send tab with no dry run yet starts one automatically.
- After a dry run that succeeded, five figures: cuts, clips, running time (m:ss), markers, gaps.
- Below the figures: every "gate" (a reason a write would be refused) as a warning line, then every note as an info line.
- "Since the last send: in step" or "Since the last send: <summary>" heading, with the diff text (first 60 lines) when the timeline the file names differs from the file.
- An expander "The conform table, cut by cut" with the full plan table.
- A refused plan shows the refusal sentence as an error ("The conform was refused." if none was given).
- Footer line says why the primary is or is not available: "Check the plan first.", "The conform is refused: nothing can be sent.", "This server can only show the plan.", "Sent.", or "Writes <n> cuts into <library> / <project>."
- Red primary "Send to Resolve" (shows "Sending" while busy): enabled only when the dry run succeeded, the server says it can write, and nothing has been sent yet in this dialog session.
- On success: the server's stamp op (sets the cut list's `timeline:` and `conformed:` fields) is applied through the store as one edit; the panel shows "Built <name> (<timeline>): <n> cuts. <notes>"; news text "Built <name> in Resolve: <n> cut(s)." with " The cut list could not record it." appended when the stamp edit was refused. When opened from the header button, the toast is left to the header ("Sent to Resolve."); otherwise this news is toasted.
- On failure: "Send to Resolve failed: <reason>" as an error toast and in the panel.

### 2.2 Routes

- `POST /api/resolve/conform/plan` body `{key, project, name?}`: the dry run. Anyone who can reach the API may call it.
  - The client sends its own in-memory project; the server checks its shape and its internal consistency.
  - Refusals: 400 `bad-body` ("the request is not an object"), 400 `bad-key`, 400 `bad-project` ("the project is not a cut list" / "the project is not consistent: <first problem>").
  - Body limit: 16 MB plus 8 MB.
  - `name` is trimmed and cut to 200 characters; default is the file's stem (the old module's rule).
  - If the browser hangs up before the answer, the Python call is cancelled.
  - Answer: `ok`, `refused`, `name`, `library`, `project`, `table`, `rows` (number, clip, person, start, duration, gap, colour, how the clip was found), `report`, `gates`, `diff`, `canApply`, `notes`.
- `POST /api/resolve/conform/apply` body `{key, project, name?, confirm: true}`: the write.
  - Refusals: 400 `not-confirmed` when `confirm` is not exactly `true` ("a conform writes the project library: send confirm: true after the dry run"); 409 `no-library` when no library is configured; 409 `not-allowed` when the library is not in the write allowlist; plus the plan route's refusals.
  - A write that has started is always let finish, even if the browser hangs up.
  - Answer: `{ok, name, timeline, cuts, backup, stamp, notes}`. The stamp is an op `setMeta {timeline: <name>, conformed: "<local ISO time> via <route>"}` for the client to apply; the server never writes the cut list itself.
- Error mapping from the Python helper: a refusal (the old modules' "ConformRefused"/"WriterRefused") becomes 409 `refused` with the sentence; `timeout` or `busy` 504; `no-python` or `closed` 503; anything else 502 `bridge-<code>`.
- At most 2 Resolve-helper calls run at once across the server; each must finish within 120 s, queue wait included.

### 2.3 What the dry run and the write do

- The cut list's text is rendered from the client's project and re-read by the old Python conform code (unchanged, read-only).
- Clip resolution: with a configured library, clips are resolved against the library's media pool (through `LibraryTokens`, for the project named by `TC_RESOLVE_PROJECT` or the file's `project:`). Without a library, clips are resolved from the file's own `clips:` uids, which is enough to show a plan but not to write.
- Gap notes from the episode folder are read for the plan; if they cannot be read the note "gap notes not read: <error>" is added and the plan continues.
- Gates (each makes a write impossible and is shown on the dry run):
  - "this file does not say which Resolve project it belongs to (`project:` in the frontmatter)".
  - "this server has no project library configured (TC_RESOLVE_DB_HOST / TC_RESOLVE_DB_NAME): the plan resolves clips by the file's own uids, and nothing can be written".
  - "no project named <p> in the library <l>".
  - "<project> already has a timeline named <name> -- pick another name".
- When the library has the timeline the file's `timeline:` names, the diff against it is computed and shown.
- A failure reading the library adds the note "could not read the library: <error>".
- Note when the library is not allowlisted: "<library> is not a library this server may write (TC_RESOLVE_WRITE_ALLOW: <list or nothing>)".
- When the plan carries gains, the old module's gain note is added.
- `canApply` is true only when a library is configured, it is in the allowlist, the file names a project, and there are no gates.
- The write: re-runs the plan; refuses with the first gate plus " -- nothing was written"; re-checks the allowlist; checks the project lock: if Resolve has the project open somewhere, refuses with "Resolve on <machine> has <project> open, and the editor has no agent to close it -- close the project in Resolve and try again"; otherwise writes the timeline and markers into the library through the old library writer, which keeps a pre-write backup in `TC_RESOLVE_BACKUP_DIR`. Port default 5432.
- After a write the note "Resolve sees it the next time the project is opened." is added.
- Nothing here ever talks to a running Resolve; only the PostgreSQL library.

### 2.4 Configuration (environment only)

- `TC_RESOLVE_DB_HOST`, `TC_RESOLVE_DB_NAME`: both required for a library to be configured.
- `TC_RESOLVE_DB_PORT`, `TC_RESOLVE_DB_USER`, `TC_RESOLVE_DB_PASS`: optional.
- `TC_RESOLVE_WRITE_ALLOW`: comma list of library names a conform may write. Empty (the default) means dry runs only.
- `TC_RESOLVE_BACKUP_DIR`: where the writer keeps its backup.
- `TC_RESOLVE_PROJECT`: the Resolve project name when the file's `project:` is not it.
- `TC_RESOLVE_FAKES=<scenario.json>`: swaps the library, the writer and Resolve for test fakes. DEV ONLY (tests).
- `GET /api/resolve/status`: answers the export and script formats, whether a library is configured, its name, whether it may be written, and the companion's last known status. Makes no Resolve or library call.

## 3. "In step with Resolve" drift chip

(source: features/resolve/client.ts, server.ts, bridge.py, python.ts, styles.ts)

- A standing header button (toolbar order 79) that says whether the Resolve timeline the cut list names (`timeline:`) still holds the same cut, frame for frame:
  - "In step with Resolve" (green icon).
  - "Resolve differs: <summary>" (gold), summary such as "2 trimmed · 1 moved".
  - "Resolve: not compared" (dim), when the comparison failed.
  - No chip at all when there is nothing to compare: no library configured, or the cut list names no timeline.
- Its tooltip says the full sentence plus "Last compared <date time>." when known; the label is cut short at 34 characters with the full text in the tip.
- Click: opens the Import tab with the drift said in full, focuses "Update the cut list from this timeline", and flashes that button gold for 1.2 s.
- Import tab's drift box: "<timeline> and this cut list are in step, frame for frame" / "<timeline> has drifted from this cut list: <summary>" / "<timeline> was not compared: <reason>"; "Last compared <time>, from the project library" or "Not compared yet"; a "Compare now" button ("Comparing" while busy); an expander "What differs, cut by cut" with the diff text (first 40 lines on the server) when it differs.
- When the state is "differs", the Import tab's read button becomes the primary and reads "Update the cut list from this timeline".
- Background schedule (client):
  - Asks every 10 s while the page is visible.
  - After an edit, asks again 3 s after editing pauses.
  - When the cut list or its `timeline:` changes (a send stamps a new one), the chip clears and a new comparison runs after 0.3 s.
  - A hidden page asks nothing; returning to visibility asks again if 10 s have passed.
  - A failed ask backs off: 20 s, 40 s, then 60 s at most; shown as "not compared" with the reason.
  - An "off" answer hides the chip and stops asking until the list or its timeline changes.
  - "Compare now" and the palette entry force a comparison.
- Route `POST /api/resolve/drift` body `{key, project}`:
  - No library: answers "off" without reading anything ("this server has no project library configured").
  - No `timeline:`: answers "off" ("this cut list names no Resolve timeline yet: send it to Resolve first").
  - Otherwise compares through the old diff code. A comparison of the same cut list text, timeline and project name younger than 5 s is answered from memory. Only one comparison per cut list runs at a time; requests arriving meanwhile share it. At most 32 cut lists are remembered.
  - Runs on a separate helper registration: one at a time, 30 s timeout, so it never takes a slot a Send is waiting for.
  - A failure is an answer, never an error page: state "unknown", summary "could not be compared", with the reason and a time.
  - Same body refusals as the plan route.
- Never automatic: the way back from drift is always the Import proposal.

## 4. Export: timeline files and the plain script

(source: features/resolve/client.ts, exports.ts, media.ts, levels.ts, script.ts, server.ts)

### 4.1 The Export tab

- A radio group of four tiles (Final Cut Pro XML is selected by default):
  - "Final Cut Pro XML" (.fcpxml): "Resolve, Final Cut and Premiere read it. Carries the most of the cut." Carries gain, levelling, fades, notes, markers. Lacks colour.
  - "OpenTimelineIO" (.otio): "The open interchange format. Round-trips back into the editor exactly." Carries markers, everything in metadata. Lacks gain, fades.
  - "CMX3600 EDL" (.edl): "The oldest format: straight cuts and markers. Every tool reads it." Carries markers, notes. Lacks gain, fades, colour.
  - "Script" (.md or .txt): "The words of the cut to read, print or send..." Carries sections, speakers, timecodes, notes, gap notes. Lacks translations, timing.
- For timeline formats:
  - "Media" choice: "Source files" (default; "The files the transcripts were made from; the lite audio where there is none.") or "Lite audio" ("The editor's own Opus copies: same timing, not the camera audio.").
  - "Levelling" switch "Bake automatic levelling into the gain" (default on). Active only for FCPXML; for the others it is disabled with the hint "<format> has no clip gain: cuts play at source level."
- For Script: "File" choice "Markdown (.md)" (hint mentions Ctrl+S) or "Plain text (.txt)" (hint mentions Ctrl+Shift+S).
- Before a download, a note says what the format does not carry (or, for the script, that it is the words as spoken in each clip's own language and the English lines stay in the editor).
- Primary "Download" ("Exporting" while busy): downloads every file the server returns. Changing format, media or script type clears the last result.
- After a download: "Downloaded <names>", "<n> clips linked, <m> offline, <k> cuts levelled", and an open expander "What the file does not carry (<n>)" listing every loss as a warning.
- Toast/news: "Downloaded <names>." Download errors show in the tab. Ctrl+S / Ctrl+Shift+S failures toast "The script download failed: <reason>"; with no cut list open they toast "Open a cut list first: there is nothing to download." Only one keyboard script download runs at a time.
- Files are saved through a temporary blob link, revoked after 30 s.

### 4.2 Route `POST /api/resolve/export`

- Body `{key, project, format, media?, level?}`. `format` is `otio`, `fcpxml`, `edl`, `md` or `txt`; anything else is 400 `bad-format` ("the format must be one of otio, fcpxml, edl, md, txt"). Same body refusals as the plan route.
- `media` is `lite` or (anything else) `original`. `level` is on unless explicitly `false`.
- Answer: `files` (name, MIME type, text), `dropped` (every loss as a sentence), `media` (per clip: original, lite or missing), `levelled` (cuts levelled, clips without peaks).
- The OTIO / FCPXML / EDL writers themselves are the editor's shared exporters (outside this part); this route prepares their input.

### 4.3 Media paths in exported timelines

- Original media: for each clip the cut uses, the `source` recorded in `<clip>_words.json` under `<Episode>/Interviewees/<who>/`. If a file with that name sits beside the words file (a vault copied to another machine), that local copy wins; otherwise the recorded path is used as written.
- Montage sources: `<Episode>/Clips/<stem>/<stem>_words.json` (folder matched by the clip's media stem, exactly then case-insensitively), same local-copy rule.
- Words files over 64 MB are ignored.
- Fallback: the audio the editor plays (found the way the media service finds it: `Script Docs/remote_audio/<clip>.ogg`, a montage extraction, a fit-stem name), marked "lite".
- Notes added to the losses list: "no transcribed source file found for <clips>: linked to the editor's lite audio (remote_audio/*.ogg) instead"; with Lite audio chosen, "linked to the editor's lite audio...: same timing as the source, not the camera audio"; "no media in the vault for <clips>: left offline (relink in the target tool)".
- A clip name is only ever compared against directory listings, never joined into a path.

### 4.4 Baked automatic levelling (FCPXML only)

- Each cut's exported gain = its manual gain + the editor's automatic level for that cut, computed from the same `.peaks` waveform files and the same functions the editor's playback uses: the speech level around the cut's middle, brought to the median level of the clips in the cut, rounded to 0.1 dB and clamped to ±30 dB.
- Peaks are read only: an export never starts ffmpeg. Peaks files over 64 MB are skipped.
- A peaks file older than its audio by more than 2 s is stale and not used; the peaks the server made in memory this session (read-only runs) are used instead when present.
- Shelf cuts are untouched.
- Losses-list sentences replace the exporter's "levelling is playback only" note: "automatic levelling is baked into the gain of <n> cut(s), so they play as they did in the editor" and "no peaks for <clips> (play them once in the editor to make them): those cuts carry their manual gain only".

### 4.5 The plain script (.md / .txt)

- One file named after the cut list's `timeline:`, else its title, else its project, else the cut list's file name, else "Timeline Cards". Characters Windows refuses (`\ / : * ? " < > |` and control characters) become `_`; trailing dots and spaces are removed; at most 150 UTF-16 units, never splitting a surrogate pair.
- Markdown starts with `# <name>`.
- A section or plain heading becomes `## <title>` (Markdown) or the title underlined with `=` (text). The heading's kind decides this, never its colour.
- A `◆` note heading or a `- (note)` row becomes `> ◆ <text>` / `-- <text> --`; an "unmatched" note row is prefixed "unmatched: ".
- Each cut: a header line with the speaker in bold, then an em-dash character, then the record timecode (Markdown, with a hard line break) or `Speaker <timecode>` (text). The timecode is where the conform plan places the cut on the timeline.
- Then the cut's words as spoken: when a cut has lines in a non-Latin script, those are kept and the Latin gloss lines beside them dropped; an all-Latin cut drops only plainly English lines beside non-English ones. Lines that would read as Markdown structure (`# `, `> `, `- `, `1. `, `===`) are escaped.
- Then the cut's note: `> 📝 <note>` or `   [note: <note>]`.
- A gap's note comes before the cut after it: `> 📝 gap: <note>` or `   [gap note: <note>]`. Notes come from the gap rows in the cut list itself.
- A cut with no words is left out and counted.
- Losses list always says "the words as spoken only: translations are not in the script", plus "<n> cut(s) with no words are left out", plus a gap-note read failure sentence if one happened (the download still happens).

## 5. Import: a timeline file or the Resolve timeline as a proposal

(source: features/resolve/client.ts, importers.ts, ops.ts, server.ts, bridge.py)

### 5.1 The Import tab

- Lead text: the editor compares the timeline with the cut list cut by cut, shows every change first; accepting is one undoable step; a cut the timeline left out goes to the shelf, never away.
- A drop zone "Drop an OTIO, FCPXML or EDL file here" (highlighted while a file is dragged over it; only on the Import tab with no preview showing) and a "Choose a file" button (file picker accepts `.otio, .fcpxml, .xml, .edl`, JSON and plain text).
- Client refuses a file over 16 MB ("That file is over 16 MB: it is not a timeline.") and an unreadable file ("That file could not be read.").
- "or" divider, then "The Resolve timeline this list names: <timeline>", hint "Read from the project library, never from a live Resolve.", and a "Read the timeline" button (or the primary "Update the cut list from this timeline" when drift says "differs").
- The preview: title "Update from <timeline name>", source line ("OTIO", "FCPXML", "EDL" or "Resolve timeline", plus the file name), count chips in the order trimmed, moved, new, staged, gap, colour, fade, gain, marker, same; a list of every change (kind, cut number, clip, reason); warnings.
- When the timeline and cut list are already in step: "The timeline and the cut list are in step: there is nothing to change." and a "Done" button.
- Otherwise: footer "One step: Undo puts it all back.", "Discard" and primary "Accept the changes".
- Accept checks first that the preview still applies to the current cut list; if not: "That preview is gone. Import it again." or "The cut list changed since this preview, so it was not applied: <reason>. Import it again." If the edit is refused: "Not applied: <reason>". On success the toast/news "<title>: accepted as one step (Undo puts it back)." and the tab shows "<title>: accepted. Undo puts the cut list back as it was."
- Imports go through the editor's shared proposal pipeline (source "resolve-import"). Discard, a new import, or the panel going away gives up the open proposal. If another surface settles the proposal, the preview clears.

### 5.2 Routes

- `POST /api/resolve/import` body `{key, project, format?, name?, data}`: 400 `bad-data` ("there is no file to import") when `data` is empty; format detected when not given; 400 `bad-format` ("that file is not an OTIO, FCPXML or EDL timeline"); 422 `unreadable` with the reader's sentence; 422 `no-proposal` when no proposal can be built.
- `POST /api/resolve/timeline/read` body `{key, project, timeline?}`: reads the named (or the file's `timeline:`) timeline from the project library and answers a proposal that also sets `timeline:`. Errors: no library ("this server has no project library configured..."), no timeline name ("this cut list names no timeline (`timeline:`) -- send it to Resolve first, or name one"), both surfaced through the bridge error mapping; 422 `no-proposal`. Cancelled if the browser hangs up.

### 5.3 Reading the formats

- Format detection looks at the bytes first (JSON with `OTIO_SCHEMA`; `<fcpxml`; a `TITLE:` line or a CMX event line) and only then the file extension (`.otio`, `.fcpxml`/`.xml`, `.edl`).
- Limits: 16 MB of text; at most 20 000 clips or events; XML nested at most 256 deep. A file with no readable clips is refused ("this <format> has no clips the editor can read").
- Clip names are matched to the project's clips ignoring a media extension (`.mov .mp4 .mxf .wav .ogg .m4a .mkv .braw .avi .aif .aiff`), repeated whitespace, case and Unicode normalisation.
- Source times are converted from the clip's own timecode to seconds from the media's first frame, using the clip's `start_tc` from the cut list (falling back to the file's own available-range or asset start when the cut list does not know the clip).
- OTIO: the track carrying the editor's own metadata wins, then the first audio track with clips, then any track with clips; warning "this timeline has <n> tracks: only <name> is read" when several have clips. Gaps advance time; transitions are read as straight cuts (warning); other nested items are skipped (warning); clips without a source range are skipped (warning). The editor's own metadata (cut id, person, colour, gain, fades, note) round-trips exactly. Marker colours map: BLUE→Blue, CYAN→Cyan, GREEN→Green, YELLOW→Yellow, RED→Red, PINK→Pink, PURPLE→Purple, MAGENTA→Fuchsia, ORANGE→Sand, WHITE→Cream, BLACK→Cocoa.
- FCPXML (1.8 to 1.11): spine items `gap`, `asset-clip`, `clip` (with nested audio/video reference) and `mc-clip`; transitions read as straight cuts; other spine items skipped with a warning; fades read from `adjust-volume`; markers on gaps and clips (the editor's own kind/colour encoding in the marker note is honoured); `<note>` read. Clip volume is NOT read back (warning: the export baked levelling into it). Markers after the last clip cannot be carried, so the cut list's own trailing headings are kept.
- EDL (CMX3600): `TITLE:`, `FCM: DROP FRAME`, events, `* FROM CLIP NAME:`, `* COMMENT:` (notes), Resolve marker comments (`|C:ResolveColor<colour> |M:<title> |D:<n>`). Dissolves, wipes and keys are read as straight cuts (warning). Audio and video events with the same record span count once. `BL` (black) events are gaps. An EDL starting at 00:00:00:00 rather than the cut list's start is counted from its first event's hour. No markers in the file: warning "this EDL carries no markers: the sections stay where they were".
- A Resolve library read takes each card's clip, source in/out, timeline position and its own clip colour (only when the item has one), and the timeline's markers.

### 5.4 How a proposal is built

- Cuts are matched to the cut list by the editor's own cut id when the file carries it (OTIO from this editor), then by clip name and source span in three passes: exact, contained, overlapping; ties go to the nearest in order, then the lowest index. Never by a Resolve uid.
- A cut id that names a shelf cut brings that cut back from the shelf ("back from the shelf").
- An edge within half a frame of the cut list's value keeps the cut list's value; for a clip at a different rate than the timeline the tolerance is one and a half frames. So an untouched cut never comes back "trimmed".
- A matched cut keeps what only the cut list knows: person, reference, words, highlights, note (unless the timeline states one), manual gain (unless the file carries gain), fades (unless stated), colour (unless stated).
- An unclaimed clip inside a matched neighbour's span is the second half of a blade: it copies that cut's person, words and note under a new id.
- A clip starting before its media is skipped with a warning. A changed cut shorter than the minimum cut length is lengthened to the minimum; an untouched legacy cut under one frame keeps its span. Fades longer than the cut are clamped.
- Black before a cut becomes a gap row (the existing gap id is reused where there was one); gaps under the minimum gap length are dropped.
- Sections: when the timeline has markers, they ARE the sections. A marker whose id or title the cut list knows keeps the cut list's kind and id (a colour change is kept as a recolour, but the kind's default export colour is not counted as one); an unknown marker becomes a `## §` section, or a `## ◆` note when Green or Red; untitled markers are ignored unless they are note rows. Each marker stands in front of the first clip that has not ended by it. A file with no markers keeps every heading in front of the cut it stood in front of.
- A cut that is not on the timeline is moved to the shelf under the staged category "Not on the timeline", never deleted.
- The cut list's `updated_from_timeline` is stamped "<UTC time> from <timeline name>".
- The result is checked for consistency and the ops are proven to apply as one batch before anything is shown. A proposal whose only change is the stamp is treated as "in step" (no ops). Warning "the cut order after accepting may differ from the timeline's: check the preview" if the applied result differs in order.
- Preview row kinds: Trimmed ("in <a> to <b>, out <c> to <d>"), Moved ("was cut <n>", by longest increasing order), Gap, Colour ("colour <a> to <b>", "speaker" when none), Fade, Gain, New ("new on the timeline: <in> to <out>"), Staged ("not on the timeline: staged under 'Not on the timeline'"), Marker ("new heading/note '<title>'" or "'<title>' is not on the timeline: removed"), and an unshown Same count.

## 6. Live: following Resolve's playhead

(source: features/resolve/client.ts, server.ts, companion.ts, companion.py, live.ts)

### 6.1 The Live tab

- Lead text: with Resolve open on this edit's timeline the editor can follow its playhead and move it to the selected cut; it never connects while Resolve is starting.
- Status box with a dot (live, "syncing" while Resolve is starting, off otherwise), a sentence and a second line ("Resolve timeline: <name>", "Scripting: <ready/starting/absent/unknown>", or "Check to see whether Resolve is there"), and a "Check" button ("Checking" while busy).
- Status sentences: "Following <timeline>", "Resolve has <project> open, with no timeline", "Resolve has no project open", "Resolve is starting: waiting before connecting", "Resolve is not running", "Resolve: <error>", "Resolve is not connected", "Waiting for the companion", "Not following Resolve", "Not checked yet".
- Switch "Follow Resolve's playhead": while on, the editor polls Resolve's playhead every 250 ms when connected and every 2 s when not, and moves the editor's playhead there when the editor is NOT playing and the two differ by more than half a frame.
- Switch "Move Resolve to the cut I select": while on, every change of the first selected cut jumps Resolve to that cut.
- Footer: "Selected: <person or clip>" or "Select a cut to jump Resolve to it."; button "Jump Resolve here" (disabled with nothing selected).

### 6.2 Routes

- `POST /api/resolve/companion/status`: asks the companion for its status (it connects only if the guard allows).
- `POST /api/resolve/companion/playhead` body `{project?}`: Resolve's playhead as editor seconds. Without a usable project it answers plain timeline seconds; with one, it maps Resolve's whole-frame timeline back to editor time through the export plan (the timeline Resolve got lays each cut end to end in whole frames, so a plain conversion would drift over hundreds of cuts). Drop-frame timecode is honoured.
- `POST /api/resolve/companion/jump` body `{key, project, cut | t}`: moves Resolve's playhead to a cut's first frame (after its gap) or to an editor time. Refusals: 400 `bad-value` ("jump needs a cut or a time in seconds"); 404 `not-found` ("that cut is no longer in the cut list"); 400 `bad-value` ("that time has no timecode on this timeline"). If Resolve is not connected, answers `ok: false` with the status. Uses the timeline's own start and rate as seen by the companion, else the cut list's. Failure sentence from the companion: "no timeline is open in Resolve", "Resolve is not connected", "Resolve did not move to <tc>".
- `POST /api/resolve/companion/stop`: stops the companion process.

### 6.3 The companion process

- Started on the first ask, as a separate Python process (the same interpreter as the server's Python pool: `TC_PYTHON` / `TC_PY`, else `py -3.12`; window hidden on Windows). One JSON request per line in, one answer per line out.
- Stopped after 60 s with no ask; stopped on server close (asked to quit, killed after 1.5 s).
- Each ask times out after 4 s ("Resolve did not answer in time"). More than 16 asks waiting is refused ("Resolve is not answering"). A line over 1 MB is dropped.
- A companion that dies is restarted on the next ask, at most 5 times in any minute ("the Resolve companion keeps stopping: not restarted for a minute").
- The Resolve connection rule: before every connect it asks the Resolve script-server guard (a TCP-table check, no connection). It connects only when the guard says READY, or UNKNOWN (fail open when the table cannot be read); never on STARTING or ABSENT. Between attempts it waits `TC_RESOLVE_RETRY_S` seconds (default 3) without touching Resolve. One connection is held for the process's life; a lost connection is dropped and the guard is asked again.
- Commands: status (guard, connected, project, timeline, error), playhead (current timecode, start timecode, timeline frame rate), jump (set current timecode), quit.
- `TC_RESOLVE_FAKES` replaces the guard and Resolve with fakes. DEV ONLY.

## 7. Resolve feature: development harness

(source: features/resolve/dev/entry.ts, dev/serve.ts, dev/shoot.ts, tsconfig.json)

- DEV ONLY: a bundle of the whole editor plus this feature, mounted both by hand and through the platform; a server on a test port (49740 to 49759) over a copy of the test vault with fake library ("FF5", writable) and fake Resolve (guard READY, retry 0 s); a screenshot script `npx tsx features/resolve/dev/shoot.ts [scene...]` writing `features/resolve/shots/<scene>--<size>.png` for scenes send, export, script, import, live at 1440x900 and 390x844. Requires `TC_FIXTURES`. Nothing here can reach a real Resolve.
- `tsconfig.json`: type-checking configuration only.

## 8. The projects sheet ("Cut lists")

(source: features/projects/client.ts, names.ts, ops.ts, styles.ts, entry.ts)

### 8.1 Opening and closing it

- The header crumb (the open cut list's name, drawn by the views) is turned into the sheet's trigger: role button, focusable, tooltip "Switch cut list or episode", a small chevron after it. Click, Enter or Space opens the sheet.
- The empty-editor state's "Open a cut list" button opens the sheet on the lists page; its "New from canvas" button opens it on the canvas page (on the newest episode when no list is open).
- Desktop: a 600 px dialog in the middle (at most 760 px tall), red rule on top. Phone (700 px or narrower, or a coarse pointer): a bottom sheet the full width, 92% of the height, 48 px row actions shown as icons with full accessible names ("Duplicate E1 V2").
- The sheet is modal: keys typed in it never reach the editor; Tab and Shift+Tab cycle inside it.
- Escape on any inner page (name form, confirm, canvases, episodes, offline) steps back to the lists page; Escape on the lists page closes the sheet.
- A close button (shows "Esc") and a click on the backdrop close it. Focus returns to what had it.
- Every time the sheet opens it re-reads the server (another device may have made a list).
- Sheet title changes: "Cut lists", "Episodes", "New from canvas", "Offline".
- Loading lines: "Reading the vault", "Reading <episode>", "Reading the vault’s episodes". A failed read shows the error and a "Try again" button (clears every cache and re-reads).
- Any request that cannot reach the server says "the server cannot be reached: cut lists are listed and made by the server, so this needs a connection".
- Answers that arrive for a page the person has already left are dropped.

### 8.2 The lists page

- Episode box: "Episode <name>" and a "Change episode" button.
- The episode shown first: the open list's episode, else the episode with the newest cut list.
- An "Offline" row (see section 10): one line saying what is kept on this device ("<n> cut lists on this device · <size>", "Nothing kept on this device for offline yet.", "Downloading <name> for offline…") or "Working offline: edits wait on this device." (gold), and a button "Offline" or "Offline settings".
- "Cut lists" list, newest first (by modification time, then name). Each row:
  - The FILE NAME (not the title).
  - A muted line: "from <title>" only when the title differs from the file name, "<n> cut(s)", "rev <n>", or "cannot be read" for a file that will not open.
  - Tags: "Open now" (the open list), "Last opened here" (gold; the list this device last left this episode on, remembered per device in localStorage `tc.projects.lastByEpisode`, at most 200 episodes), "On this device" or "On this device (part)" (kept for offline, or kept by the separate keep-on-this-device feature).
  - Clicking a row opens that list (clicking the open list just closes the sheet).
  - Row buttons: "Keep" (only when the separate keep-on-this-device feature is loaded: closes the sheet and hands the list to that feature, which is inventoried elsewhere; offered for any list, writable server or not), "Duplicate" and "Rename" (only when the server can write cut lists).
- Empty episode: "No cut lists in <episode> yet. Make one from a canvas, or start an empty one."
- "Start a cut list" section (writable servers only): "From a canvas" (disabled with tooltip "There is no .canvas in <episode>'s Script Docs" when there is none) and "Empty cut list". A read-only server says "This server cannot make cut lists (the vault is read-only and there is no working copy)."
- Under the dashboard mount only, a footer: "Signed in as <user>" and an "All episodes" link back to the dashboard's episode list. While offline, the link is refused with "You are offline: the episode list needs the server, so this cut list stays open"; otherwise pending edits are flushed before leaving.

### 8.3 Opening another cut list

- Opening a list flushes the store's pending edits to the device's storage first, then reloads the page with `?key=<key>` (audio, media and persistence are bound at page start).
- The list being opened is remembered as this episode's "Last opened here" list.
- The remembered list is only marked, never opened automatically.

### 8.4 The episodes page

- "Back to the cut lists" button.
- Every episode of the vault (and of the working copy): its last folder name, "<n> cut list(s) · <n> canvas(es)", "in <parent folders>" when nested, "Open now" on the open one. Click shows its lists.
- Empty vault: "No episode folders with a Script Docs folder in this vault." / "This vault has no episode folders yet (an episode is a folder with a Script Docs folder in it)."

### 8.5 New from a canvas

- Canvas page: "Back to the cut lists"; heading "Make a cut list from a canvas"; "The canvas is read, never written. You see what it will make before the file is made."; every `.canvas` in the episode's Script Docs, newest first, with "changed <date>". Empty: "There is no .canvas in <episode>'s Script Docs."
- Picking a canvas immediately asks the server to start converting it (prewarm, fire and forget) while the name is typed. Only one canvas at a time: a second pick while busy says "still working on <canvas>: one at a time".
- Name page: "A cut list from <canvas>"; "First the canvas is read and you see what it will make; nothing is written until you say so."; field "Name of the new cut list" (pre-filled with the canvas name, hint ".cut.md is added"); "Cancel" and primary "Check the canvas" ("Reading the canvas" while busy). This is a dry run.
- Confirm page: "Make <name>.cut.md from this <interview|montage> canvas?"; counts Cuts, Notes, Alternates, Unmatched (gold when above zero), Staged (only when above zero), Timing (Word or SRT); a list of what timed each clip; "The shelf gets <n> categories, one per section." when present; the conversion's warning (for example "no word timing for any clip: the spans come from the .srt cues (timing: srt)"); "<n> card(s) could not be found in their transcript and will be listed as unmatched notes, so nothing is dropped."; "Cancel" and primary "Make <name>" ("Making <name>").
- Cancel on the confirm page returns to the lists with "Nothing was made: <name> was cancelled".
- Make writes the file and opens it (page reload).
- The new list's timeline shape (frame rate, drop frame, start timecode) is copied from the open cut list, else 29.97 drop frame at 01:00:00:00.

### 8.6 Empty, duplicate, rename, retitle

- "Empty cut list": "A new, empty cut list"; "A header and no cuts, in <episode>. Insert from a transcript to fill it."; field "Name"; "Create" ("Creating"). Opens the new list.
- "Duplicate": "Duplicate <name>"; "A copy of the list as it is now, with its own history from here on."; field "Name of the copy" pre-filled with a free name ("<name> copy", "<name> copy 2", ... compared case-insensitively); "Duplicate" ("Duplicating"). For the open list the copy waits for the server's file to reach the version this device sees. Opens the copy.
- "Rename" on a list that is NOT open: "Rename <name>"; "Renames the file. It can only be renamed while nobody has it open."; field "New name"; "Rename" ("Renaming"). Stays on the lists page afterwards.
- "Rename" on the OPEN list becomes a title change instead: "Rename the open list"; "The list's title changes on every device, and Undo takes it back. The file keeps its name (<file>.cut.md) while it is open; rename the file from another list."; field "Title". Sent as one undoable edit that sets the title; control characters become spaces, whitespace collapses, at most 200 characters, empty clears the title (the file name then names the list); an unchanged title just closes the sheet; a refused edit shows its reason.
- Name rules (checked identically on client and server): trimmed, surrounding double quotes stripped, a typed `.cut.md` dropped. Refusals: "give the cut list a name"; "a cut list name is a file name: no folders, and none of \ / : * ? " < > | in it" (also for `.`, `..` and control characters); "a cut list name cannot start with a dot (that is a hidden file)"; "a cut list name cannot end with a dot or a space"; "<name> is a name Windows keeps for itself; pick another" (CON, PRN, AUX, NUL, COM0-9, LPT0-9); "a cut list name is at most 120 characters". The input itself is capped at 200 characters.
- Typing in the name field clears the last refusal at once. Enter submits.
- UNREACHABLE: a sheet action "retitle" exists in the click handler, but no button draws it; the retitle form is reached only through "Rename" on the open list.

## 9. Projects: server routes

(source: features/projects/server.ts, bridge.py, names.ts, worker.ts)

- Where things are: canvases and transcripts are read from the vault; cut lists are read and created where the sync service keeps them (the working copy of a read-only run, else the vault). A list made on a read-only run lands in the working copy and the vault is untouched.
- The server "can write" unless the vault is read-only AND there is no working copy; when it cannot, every write route answers 403 `read-only` ("this server does not write cut lists (the vault is read-only and there is no working copy)").
- Episode discovery: every folder (not hidden, not `Script Docs`, not `node_modules`) up to 4 levels below the vault root (and the working copy) that contains `Script Docs`. Remembered for 10 s; forgotten after any create, duplicate or rename. An episode named in a request that is not in the list triggers one fresh scan before refusing with 404 `no-episode` ("there is no episode folder <ep> in this vault").
- Episode argument rules: forward slashes, no empty, `.`, `..`, hidden or padded segment, none of `: * ? " < > |` or control characters ("that is not an episode folder of this vault"); naming `Script Docs` itself is refused ("name the episode folder, not its Script Docs"); missing: "no episode named". All 400 `bad-name`.
- `GET /api/projects/episodes`: every episode with name, list count, canvas count, newest list time, and `writable`.
- `GET /api/projects/episode?ep=<episode>`: the episode's cut lists (key, file name, title, cut count, version, modified time, or error "cannot be read"), newest first; its canvases by name with modified time, newest first; `writable`.
- `POST /api/projects/prewarm` body `{episode, canvas, shape?}`: starts converting the canvas in the Python worker and answers `{started: true}` at once. Failures are only logged ("canvas prewarm did not finish"). Writable servers only. Body limit 64 KB (all write routes).
- `POST /api/projects/new` body `{episode, name, from, canvas?, dry?, shape?}`:
  - `from` defaults to `canvas` when a canvas is given, else `empty`; any other value is 400 `bad-from` ("a new cut list comes from a canvas or from empty").
  - A name that exists in the working copy or the vault is refused BEFORE any conversion: 409 `exists` ("<name>.cut.md already exists -- pick another name (nothing here overwrites a cut list)").
  - Empty: writes a header with no cuts; project = the episode folder's name; title = the name; stamped "<local time> by Timeline Cards (new, empty)"; rev 1.
  - Canvas: 400 `bad-canvas` ("name the canvas to make the cut list from"); 404 `no-canvas` ("there is no canvas <name> in <episode>'s Script Docs"). A canvas is named, never a path: the server resolves it against the folder listing, and the Python side re-checks that the path is a `.canvas` in that folder.
  - `dry: true`: answers the conversion's report and writes nothing.
  - Otherwise the old Python conversion produces the text (stamped "by Timeline Cards (new from canvas)"); it is re-read through the editor's own format reader and consistency-checked (500 `bridge` if it does not read or is not valid); the title is the new file's name; then written.
  - Python failures: 503 `busy`; the old module's own sentence as 422 `canvas` ("that canvas did not read: <reason>"), or 409 `exists` when it says "already exists"; anything else 503 `bridge`.
- `POST /api/projects/duplicate` body `{key, name?, version?}`: 400 `bad-key` (including "that cut list is not in an episode's Script Docs/Cuts folder"); 409 `exists`; waits up to 3 s (checking every 80 ms) for the source file's `rev:` to reach `version`, else 409 `not-saved-yet` ("the cut list is still being saved; try again in a moment"); 404 `not-found` ("that cut list is not there any more"); 422 `unreadable`. The copy gets rev 1, title = new name, stamp "<time> by Timeline Cards (copy of <source>)".
- `POST /api/projects/rename` body `{key, name}`:
  - Same name: answers the same key.
  - 404 `not-found`; 409 `exists` (a case-only rename of the same file is allowed); 409 `exists` ("<name> still has editor history from an earlier file of that name; pick another name") when the new name's editor-history folder already exists.
  - Takes the cut list's own lock; if the sync service (here or on another machine) has it open: 409 `open` ("that cut list is open in the editor (here or on another device): close it there, or wait about ten minutes after the last edit, then rename it").
  - Moves the file and its editor-history folder together; on failure the history folder is moved back.
  - Records a forwarding line from the old key to the new one, so a device with offline edits under the old key lands them on the renamed list.
  - Moves the list's chat history (the chat feature's turns and open proposals) with it. Failures of either are only logged.
- Writing rule for every new file: written to a hidden temp name and flushed to disk, then hard-linked into place, which fails if the name exists (two devices making one name at once get one file and one refusal). Where hard links are not allowed it copies exclusively instead. Nothing here overwrites a cut list.
- Timeline shape argument: frame rate between 1 and 240 (else 29.97), drop frame (default true), start timecode `hh:mm:ss:ff` or `;ff` (else 01:00:00:00).
- The Python helper runs pinned to one worker, one call at a time, 120 s timeout per call, so the prewarm's one-entry conversion cache is there for the dry run and the write.
- UNREACHABLE: the Python helper also has `ping` and `canvases` commands that no route calls.
- `GET /sw.js`: the editor's service worker, served as the offline layer (section 10.4) followed by the build's own `sw.js`, `no-cache`. 404 ("no service worker in this build") when the build has no `sw.js`. Re-read from disk whenever either file changes, so a rebuild is picked up without a restart.

## 10. Keep a cut list on this device (offline)

(source: features/projects/offline-ui.ts, offline.ts, offline-store.ts, offline-key.ts, offline-sw.js, worker.ts)

### 10.1 The Offline page

- Reached from the lists page's "Offline" button, from the header "Offline" badge, or programmatically.
- "Back to the cut lists" button; a status note (ok, warning or error) for the last action.
- "Work offline" switch (section 10.3), with its sentence: "Nothing goes to the server while this is on, even with a network. Edits wait on this device." / "On: nothing goes to the server. Edits wait here until you switch this off."
- "This cut list" section (when a list is open; else "Open a cut list to download it."):
  - Name and episode; "On this device: <size> · <whole clips | the cut’s audio> · [smaller audio] · [video] · <complete | part (<held> of <planned>)> · <date time>" or "Not on this device yet."
  - Explanation: keeps the cut list, its transcripts and word timing, the waveforms and the audio the lane plays (and the video if chosen), so playing and editing work with no network; edits wait and go to the server later.
  - Three switches (disabled while downloading; each change re-sizes the plan):
    - "Whole clips": "Keeps every clip whole, so you can insert from the transcripts offline. Larger." Off by default: only the audio under every cut and shelf item, with 10 s of handle each side, merged and clamped to the clip.
    - "Smaller audio": "Half the size again. Speech stays clear; music loses its top end." Keeps audio at 24 kHz.
    - "Include the video": "The 480p proxy of each clip, for the video window." Asking for it starts the server making proxies.
  - When the page opens on a list already kept, the switches start as that copy was made.
  - Sizes shown before anything is fetched: Audio, Video ("Off", "None yet" or a size), Transcripts ("~<size>", an estimate), Clips; "Working out what a download takes" while sizing.
  - Expander "Size of each clip": table of clip, audio size ("no audio"), video size.
  - Warnings: "<n> clip(s) have no audio on the server yet (<first three>, …), so they will be silent offline." and "<n> video proxies are still being made: download again in a while to take them."
  - Primary button: "Download for offline · <total size>", or for an existing copy "Download again · <size>" (when mode, video, quality or device rate differ), "Download the rest" (part copy), or "Update the copy". Disabled while working offline (tooltip "Switch Work offline off to download"), when the browser keeps nothing ("This browser keeps nothing for this site"), or when sizing failed.
  - While downloading: a progress bar, "<done size> of <total size> · <n> of <m> · <what>" (what: "the cut list and its transcripts", "audio for <clip>", "video for <clip>", "starting", "everything is already on this device"), and "Stop the download".
  - "Remove from this device", then "Remove <size> from this device?" with "Keep it" and red "Remove".
- "Other cut lists on this device": every other kept list, newest first, with episode and the kept line; a click opens it (page reload); a per-row remove with confirm. Empty: "None yet. Open another cut list and download it to keep several side by side." Then "Using <usage> of the <quota> this browser allows." and "Kept until you remove it." or "The browser may clear it if the device runs short of space; a download asks it not to."
- "A copy of your edits" section (when a list is open): "<n> edit(s) are on this device and not on the server yet. A copy in your Downloads folder survives the browser being cleared." or "Every edit is on the server. A copy is only worth saving while edits are waiting here." Buttons "Save a copy" (primary while edits wait) and "Restore from a file".
- The lists page tags each kept list "On this device" / "(part)" and updates its Offline row as downloads progress (progress repainted at most four times a second).
- Sizes are written "830 KB", "212 MB", "1.4 GB".

### 10.2 Download for offline

- What is fetched for a cut list: the project; its media source list; the episode's listing and the episodes list (so switching between kept lists works offline); per clip the lane's word timing, the waveform peaks and the decoded audio windows the audio engine will ask for (exactly its chunk URLs at this device's playback rate); with video, each clip's 480p proxy (sized with a HEAD request) and the video state; when the transcripts service answers, the transcript source list and every transcript referencing a used clip (whole and per clip).
- Audio is kept as 16-bit samples (half the server's 32-bit float), or at 24 kHz with Smaller audio.
- Media of an episode (audio windows, peaks, audio files, video proxies, lane words) is filed per EPISODE, so two cut lists of one episode share one copy; documents are filed per cut list.
- Only what the device does not already hold is fetched, plus every document again (they must be current); a clip whose audio hash changed is fetched again whole; every audio window is fetched again when the quality changed.
- 3 requests at a time. A network failure is retried twice (after 1 s, then 2 s) before "the server stopped answering (<reason>)". A 503 is retried up to 6 times, waiting the server's Retry-After (capped at 5 s) or 1 s. A 404 on an optional item (no words, no transcript yet) is skipped; any other failure of a required item stops the download. A redirect is treated as "the server asked to sign in again".
- The kept record is written every 24 items, so a download cut short is a usable part copy; "Download again continues from there".
- The device is asked to keep the storage persistently.
- A full device stops with "This device is out of room. What came down is kept; free some space, or remove another cut list below, then download again."
- Outcomes: "<name> is on this device: <size>, ready to work offline." (plus " Part of it is not on the server yet (see below); download again later to take the rest." when incomplete); "Download stopped. What came down is kept; Download again continues from there."; "The download stopped: <reason>. What came down is kept; Download again continues from there."
- A copy is "complete" only when every required item is held and every clip had audio.
- Refusals: "This browser does not let the editor keep anything (private browsing, or storage is turned off), so nothing can be downloaded here."; "You are working offline: switch Work offline off to download."; "this cut list is not in an episode folder, so it cannot be kept"; sizing failures "the server cannot be reached, and a download needs it: connect, then try again" or the server's sentence.
- Removing a kept list deletes only items no other kept list names: "<name> was removed from this device (<size> freed). The cut list itself is on the server." / "It could not be removed: <reason>".
- Storage: browser IndexedDB database `tc-offline` with stores `items`, `kits`, `settings`. A browser that refuses IndexedDB keeps nothing (the page says so).

### 10.3 Work offline (by choice)

- One switch, stored in localStorage `tc.offline.force` (read before the sync socket opens) and in the offline store's settings (read by the service worker), and told to a running service worker at once.
- While on: the page refuses to open the `/sync` socket and closes any open one (code 4000, "working offline"); the store therefore shows offline and keeps edits on the device; the service worker refuses every `/api` and `/media` request it holds no kept copy for (a network error, exactly as with no network).
- In the Windows and Android apps (page served from 127.0.0.1:47823, or a `CardsNative` bridge present) the app's local server is also told: `POST /__app/api/offline {on}`.
- Turning it off reconnects the sync and, if needed, re-sizes the download plan.
- A gold "Offline" badge sits beside the header crumb while it is on ("Working offline by choice: open the offline settings"); clicking it opens the Offline page. On a phone the badge is icon-only, 44 px.

### 10.4 The service-worker offline layer

- The editor's service worker is served as this layer followed by the build's own worker; the layer answers first and only for what it owns.
- It owns same-origin GET/HEAD requests to kept routes: `/media/pcm`, `/media/peaks`, `/media/audio`, `/api/video/file`, `/api/lane/words` (filed per episode) and `/api/project`, `/media/sources`, `/api/video/state`, `/api/transcripts/sources`, `/api/transcripts/doc`, `/api/projects/episode`, `/api/projects/episodes` (filed per cut list). Query parameters are sorted; audio window numbers normalised. Media addressed by id is never kept.
- Audio windows, audio files and video proxies: served from the kept copy first, network only when not kept.
- Documents: network first with a 4 s deadline; a good answer refreshes the kept copy (only for items already kept) and is put into the build worker's data cache for project, sources and peaks; a 5xx or a network failure falls back to the kept copy, then to the build worker's cache.
- While working offline: kept answers only, everything else under `/api` or `/media` is a network error, including non-GET requests. If the worker has just started and does not know the setting yet, it asks the store first.
- Video proxies are served with byte ranges (206, or 416 for a range outside the file); every kept answer carries `x-tc-offline: 1`.
- Kept 16-bit audio is turned back into 32-bit float; a window kept at another rate (Smaller audio, or the output device changed since the download) is resampled linearly to the asked rate; if no window at the asked rate is kept, windows at 48, 44.1, 24, 22.05, 16 and 8 kHz are tried in that order.
- Uses IndexedDB rather than the browser cache because the build's worker deletes other caches when it updates.

### 10.5 A copy of the edits, and restoring it

- "Save a copy": flushes pending edits, then downloads `<list>.tc-offline.json` containing the edits this device has not had confirmed, the version and snapshot they were made on, and a note explaining the file. Messages: "Saved <file> to your Downloads folder, with <n> edit(s) the server has not confirmed yet." / "...Every edit is on the server already, so it holds only the cut list as this device last saw it." / "This browser keeps nothing between visits, so there is no copy to save." / "The copy was not saved: <reason>".
- "Restore from a file" (accepts `.json` and `.tc-offline.json`): refuses a file over 64 MB ("that file is far too big to be a copy of edits"), non-JSON ("that file is not a copy of edits (it is not JSON)"), another kind ("that file is not a Timeline Cards copy of edits"), a newer version ("that copy was written by a newer editor (version <v>)"), no key ("that copy does not say which cut list it is for"), another list ("that copy is of <name>: open that cut list first, then restore it there"), no edits ("that copy has no edits in it"), a damaged edit ("edit <n> in that copy is damaged, so nothing was restored"). All prefixed "Nothing was restored: ". "This browser keeps nothing between visits, so a copy cannot be restored here." when there is no device storage.
- Edits already waiting on the device (same edit id) are skipped: "Nothing to restore: every edit in that copy is already waiting on this device." The rest are saved as a separate pending slot; "<n> edit(s) restored. Reloading to send them to the server."; the page reloads after 0.9 s and the sync client sends them (an edit the server already has is applied once).

### 10.6 The apps keep what is open (automatic)

- Only inside the Windows / Android apps; off with localStorage `tc.offline.autoKeep` = `off`.
- 20 s after the page starts, then every 10 minutes: when not working offline, no download is running, a list is open and the sync connection is live, it downloads the open list's cut audio (not whole clips, no video), fetching only what is missing, silently (no success note unless something was fetched; failures say nothing).
- DORMANT where the separate keep-on-this-device feature is loaded: it stands down entirely and lets that feature keep the open list as real files.

## 11. Dashboard mount mode (serving the editor under a path prefix)

(source: features/projects/host.ts, worker.ts)

- Run as its own entry point: the same server and services as the normal start, discovered the same way, wrapped in a prefix and trust layer.
- Settings (environment): `TC_MOUNT_BASE` (default `/cards`; must be a plain path such as `/cards` or `/cards/edit`, else start-up fails); `TC_PROXY_SECRET` (required, at least 16 characters, else start-up fails "the dashboard mount needs TC_PROXY_SECRET (at least 16 characters), the secret the proxy sends"); `TC_ALLOWED_ORIGINS` (comma list added to the allowed origins); `TC_MOUNT_HOME` (where "All episodes" goes, default `<base>/`); `TC_PROXY_USER_HEADER` (default `X-TC-User`); `TC_TRUSTED_PROXIES` (comma list of proxy addresses). Plus the normal server settings. If a working copy is configured, cut lists are mirrored into it at start.
- Trust: every request and every socket upgrade must carry the shared secret in `X-TC-Proxy-Secret` (checked through the server's trusted-proxy login), else 403 `not-signed-in` ("open the editor through the dashboard (this address is not signed in)"); a refused socket gets a bare `HTTP/1.1 403 Forbidden`.
- The signed-in user name comes from the user header (believed only with the secret, and only from the trusted addresses when those are set) and is shown in the sheet's footer.
- Prefix: anything outside `<base>/` is 404 ("the editor lives under <base>/"); `<base>` alone redirects 301 to `<base>/`; `<base>/x` is served as `/x`.
- Page paths (`/`, `/index.html`, and any extension-less path not under `/api`, `/media`, `/sync`, `/assets`) answer the built `index.html` with a small script injected before `</head>` that moves every same-origin URL under the base: fetch, XMLHttpRequest, WebSocket, EventSource, `window.open`, and `src`/`href` on media, source, image, script and link elements. URLs under `/__app/` (the native apps' local server) are never moved. The script also exposes the base, user and home to the page.
- Every other HTML response passes through a rewrite that moves root-relative `src`/`href` under the base and inserts the same script first in `<head>` (so the video pop-out page works under the mount); every non-HTML response passes untouched and unbuffered.
- `<base>/sw.js`: the offline layer plus the build's worker with its path test made base-aware, header `Service-Worker-Allowed: <base>/`. If the build's worker changed shape so it cannot be patched, no worker is served (404, logged "sw.js changed shape: no service worker is served under the dashboard mount").
- Stops cleanly on SIGINT, SIGTERM, SIGHUP, SIGBREAK.

## 12. Native app shells (apps-shell)

(source: features/projects/apps-shell/ws-forward.cjs, WsTunnel.java, app.config.editor.json)

- DORMANT: three files meant to be copied into the separate Windows and Android app projects; nothing in the editor loads them.
- `ws-forward.cjs` (Windows app local server): forwards a WebSocket upgrade to the real server, rewriting `Host`, and `Origin`/`Referer` from the local `127.0.0.1`/`localhost` origin to the target's; drops hop-by-hop headers and `x-cards-keep`; drops any header containing a line break; supports http and https targets; 4 s connect timeout; closes the socket at once when the app is working offline or has no target; then joins the two sockets byte for byte.
- `WsTunnel.java` (Android app local server): the same header rewrite and byte pumping, 4 s connect timeout, TLS for https targets, no read timeout once joined.
- `app.config.editor.json`: an app configuration whose first-run server is the dashboard's `/cards/edit/` address, port 47823, version 1.1.0. Its own comment says it is not built or published.

## 13. Projects feature: entry for tests

(source: features/projects/entry.ts)

- DEV ONLY: a copy of the editor's start-up with the sheet mounted and its two empty-state callbacks passed to the views; if the editor cannot start it shows "The editor could not start: <reason>". Exposes the sheet as `window.tcProjects`.

## 14. The video window

(source: features/video/client.ts, slave.ts, shared.ts, popout.ts, video.css, index.ts)

### 14.1 Turning it on and off

- A floating panel titled "Video" showing the PICTURE of the clip under the playhead, from that clip's 480p proxy. It never plays sound: the editor's audio engine is the clock and the only sound.
- Off by default. Remembered per browser (localStorage `tc_video` = 1/0): a page that last had it on opens with it on (unless another window already holds it, then it is marked as elsewhere).
- Toolbar button "Video" (order 70, shows "Shift V"): pressed while the window is up here or in a pop-out. Tooltip "Show the video window", "Hide the video window", or (held by a pop-out) label "Video (in another window)" with tooltip "The video window is open in another window: bring it here" and a gold dot on the button.
- Keyboard Shift+V: on/off (heard through the editor shell's shared key listener); when a pop-out holds it, Shift+V brings it back here instead.
- The panel's own close button (shows "Shift V").
- No buttons at all when no cut list is open.
- With the window off, every video element is freed and the server is asked for nothing.
- If mounted by an older caller without the shell's slots, the button and key work from private slots and move to the shell's slots as soon as the shell starts (checked every 100 ms for up to 20 s). One video window per document; a second mount adopts the first.

### 14.2 The panel

- Bar: a move grip (desktop panel only), "Video", the speaker or clip name under the head (tooltip: the clip), the source time `m:ss.t` (or `h:mm:ss.t`), and buttons: "Window size" (cycles small, medium, large), "Open in its own window" (only when windows can talk to each other), "Close the video window".
- A black 16:9 stage; when there is no picture, a centred sentence on a faint hatched background:
  - "Asking the server for this cut list’s video proxies…" before the first answer.
  - "No cut under the head." (a gap or past the end).
  - "The video proxy would not play." (the element reported an error for that clip; that clip is not tried again until the window reopens).
  - "Making the video proxy… <done> of <total>" or "Waiting for the server to make the video proxy… <done> of <total>".
  - "No video for this clip: a multicam is a sequence, it has no file of its own." / "...its media is sound only." / "...its media file was not found." / "...the file has no video track." / "No video for this clip: <ffmpeg reason>".
  - "Open a cut list: the window shows the clip under the head." when there is no project.
- Sizes: small 240 px, medium 360 px (default), large 560 px wide; remembered (`tc_video_size`).
- Free resize from the bottom-right corner: width follows the pointer, height follows 16:9; 200 to 1280 px and never wider than the viewport minus 16 px; remembered (`tc_video_w`). Keyboard on the corner handle: Right/Up grow 20 px, Left/Down shrink 20 px, 80 px with Shift. Choosing a size clears the free width.
- Drag by the bar (not its buttons) to move; the whole panel is always kept inside the viewport; the spot is remembered (`tc_video_pos`) and clamped on the next open and on every window resize. Keyboard on the grip: arrows move 16 px, 64 px with Shift.
- Default place: top right under the header. On a phone (700 px or narrower) it starts at top right at most two thirds of the screen wide and has no pop-out button. On touch screens the bar, grip, resize handle and buttons are 44 px.
- A small panel hides the clip name below 330 px wide and the time below 290 px.

### 14.3 Keeping the picture on the sound

- Picture follows the audio engine's playhead and playback rate (varispeed).
- Paused: the picture is paused on the head's source frame; while scrubbing, at most one seek every 100 ms, and the last position is re-applied up to 4 times (every 120 ms) so the final scrub position always lands.
- Playing: within 0.035 s of the sound it is left alone; up to 0.3 s off, the playback rate is nudged by up to ±8% (half the drift per second); beyond 0.3 s it seeks. After a seek, drift is judged again only after 0.25 s.
- A seek while playing aims ahead by the seek latency it has measured (smoothed, at most 2 s; ignored below 0.15 s), so a seek over a slow network lands on time instead of behind.
- When Play is pressed, the picture holds on the head's frame until the sound actually starts moving the head (at most 2 s).
- Past the end of the proxy (the camera stopped before the sound) the last picture holds instead of looping or re-seeking.
- The next cut's element is seeked to its in-point up to 1.5 s (times the playback rate) before the join, so the picture changes on the join; a following cut of the same clip that continues exactly (within 0.05 s) keeps one element; a non-continuous cut of the same clip gets a second element.
- At most 3 video elements alive; the least recently used is freed first, never the one showing or the one being prepared.
- Elements are muted, volume 0, re-muted on any volume change; the proxies have no audio track anyway. Playback rate clamped to 0.0625 to 16.
- The panel asks the server for proxy state with `on=1` when it opens, then again every 4 s while any clip is being made or the clip under the head is unknown; after a failed ask, again in 8 s. A clip whose proxy has just become ready gets a fresh element. A change of the cut list's clips asks again.

### 14.4 Pop-out (the video window in its own browser window)

- "Open in its own window" opens `/video/window?key=<key>` as a popup named `tc-video`, width max(480, 1.4 x panel width), height width x 9/16 + 48. A MOVE: the panel closes here at once. If the browser blocks the popup, the panel stays here.
- The pop-out page has no store, sync or audio: the main editor window sends it frames over a BroadcastChannel about 30 times a second while playing and on every change while paused; between frames the pop-out carries the clock forward itself (at most 1 s on stale news).
- The pop-out shows "Waiting for the editor window: play or move the head there." until the first frame; its bar has "Back to the main window".
- Pop-out page titles: "Video · <cut list name>". With no `key`: "This window needs a cut list: open it from the editor." A browser without BroadcastChannel adds "This browser cannot talk between windows."
- The pop-out closes itself when the main window reclaims the video (Shift+V or the toolbar button there), on "Bring windows back", or on its own "Back to the main window". If the browser refuses to let a script close it, after 0.4 s it says "The video is back in the main window. You can close this one."
- A pop-out that closes, or crashes and stops its heartbeat, gives the video back to the main window, which reopens it.

## 15. Several windows on one cut list

(source: features/video/windows.ts, panels.ts, panelsDom.ts, client.ts)

### 15.1 Coordination between windows

- All editor windows on the same cut list talk over a BroadcastChannel named `tc-editor:<key>` and a registry in localStorage `tc_windows`. Each window beats every 2 s; a window silent for 6 s is considered gone. A window leaving (page hide) removes itself before giving back its panels, so a reload never leaves a stale entry; coming back from the back/forward cache rejoins.
- Selection and paused playhead are shared instantly: selecting cuts in one window selects them (those that exist) in the others; moving the paused head moves it in the others.
- While one window plays, it sends its head about 30 times a second; other windows that are not playing move their head to follow (never their sound).
- One window plays at a time: starting playback in one pauses every other.
- Edits travel through each window's own sync connection, not this channel.
- No window repeats a message it received (no echo loops).

### 15.2 Toolbar buttons (desktop with BroadcastChannel; not on phones, which are 700 px wide or narrower, or landscape phones under 500 px tall)

- "Bring windows back" (order 71): only while other editor windows are open; tooltip "Close the other <n> windows and bring everything back here". Sends one recall message: every second editor window opened from here closes itself (a window the browser will not let a script close stays as a plain editor window); every panel that was out comes back here at once; the video comes back if it was out.
- "Windows" (order 72): opens the Windows menu. Tooltip "Move the lane, transcript, chat or overview to a window of its own (for a second screen)" or "<n> panels are in another window. Move a panel out, or bring it back". A gold dot while any panel is out.

### 15.3 The Windows menu

- Rows: Lane ("The timeline with the words in its clips"), Transcript ("The transcript beside the cut"), Ask Claude ("Ask Claude for changes"), Overview ("Sections and markers"), each "Move out" (pop it out) or "Elsewhere" (gold; "In another window: bring it back here"); Cards ("A second view of the cards", "New window"); separator; "Whole editor" ("This cut list in another window", "New window"); "Bring everything back" (only when other windows are open or a panel is out).
- Up/Down/Home/End move between rows; Escape closes the menu and returns focus to the Windows button; a press outside closes it; it is placed under the Windows button (else centred near the top).
- "Whole editor" opens this page again with `?tcwin=pop` in a new window named `tc-editor-<time>`.

### 15.4 One panel per window (`?panel=`)

- A window opened with `?panel=lane|transcript|chat|overview|cards` shows only that panel under a 48 px bar: the panel's name in red, "<episode> · <cut list>", a message line, and "Back to the main window" (or, for cards, "Close this window"). The editor's header, status line and phone chrome are hidden. Window title "<Panel> · Timeline Cards".
- Popping out is a MOVE: the panel closes in this window at once and opens in the new one, which claims it. If the new window never claims it within 12 s, the panel comes back.
- Popup sizes (on a 1440 x 900 screen unless the real screen is known): lane 90% of the screen wide and 620 to 760 px tall (never short enough to fall into the phone layout); transcript 620 px wide; chat 480; overview 460; cards up to 1200 px or 80% wide; each 90% of the screen tall; at least 360 x 320. Window names `tc-panel-<panel>`, so opening a panel twice reuses its window.
- A blocked popup: "The browser blocked the new window. Allow pop-ups for the editor, then try again." (warning toast).
- Only one window holds each of lane, transcript, chat and overview. A panel opened by its own button or key in a window where it was elsewhere takes it back; the holder closes it (a panel window that held only it goes home and closes).
- Exception: a whole editor window never loses its lane to another whole editor window, only to a lane pop-out (two tabs on one list both keep their lanes).
- A panel a window restores at start (for example the overview remembering it was open) never steals it from the window that has it; it closes instead.
- The main window is home: a panel nobody holds any more (its window closed or crashed) reopens there.
- In the main window, while the lane is in another window, the lane area is replaced by a 32 px bar "Lane is in another window" with "Bring it here" ("Close the lane window and put the lane back here").
- A panel window keeps trying to open its panel for 10 s (its feature may load late); then "The <panel> could not open in this window. Close it and use the main window."
- A panel window whose own panel is closed (its close button or Escape) goes home and closes itself; if the browser refuses after 0.4 s: "The <panel> is back in the main window. You can close this one." (cards: "Everything is in the main window. You can close this one.")
- "cards" is not a claim: any number of extra cards windows may be open; a recall closes them too.
- Each window checks its panels every 250 ms.
- Not available inside a single-panel window: the Windows menu and "Bring windows back".
- The other panels are reached through the handles their features expose (transcripts, chat, markers); the lane moves by layout only.

## 16. Video: server

(source: features/video/server.ts, resolve.ts, proxy.ts, shared.ts)

### 16.1 Routes

- `GET /api/video/state?project=<key>[&on=1]`: for every clip the cut list names (first 500), its picture state `vid` (ready), `vidwait` (being made or queued), or `none`, with a reason sentence per clip, and "<done> of <total>" proxies made since the server started. `on=1` means the page has the window up: only then is an encode queued. Without `on=1`, a clip with no proxy yet answers `none`, "The video window is off." Refusals: 400 `bad-key` ("project is required").
- `GET` and `HEAD /api/video/file?project=<key>&clip=<clip>`: the 480p proxy as `video/mp4` with byte ranges. Starts nothing. Only a clip the cut list names: else 404 `not-found` ("the cut list does not use that clip"). No proxy yet: 404 `not-ready` ("no proxy for that clip yet" / "the proxy went away"). Missing parameters: 400. Its ETag is derived from the proxy's name and size (not its time stamp).
- `GET /video/window`: the pop-out page (links the editor's built stylesheet and the window's own).
- `GET /video/window.js`: the pop-out script, built on first request from source (or read pre-built beside a bundled server). 500 ("the pop-out script would not build") if it cannot be built.
- `GET /video/window.css`: the window's stylesheet.
- The cut list's clips are read from the working copy first, then the vault; remembered for 2 s (a playing video makes a range request every few hundred ms; at most 256 lists remembered). Where each clip's picture comes from is remembered for 30 s (at most 4096 entries).

### 16.2 Where a clip's picture comes from

- In order:
  1. A proxy the old app already made, `<Episode>/Script Docs/remote_audio/source/<clip>.480p.mp4`, reused read-only, provided it is not older than the media it was made from.
  2. The `source` recorded in `<Episode>/Clips/<stem>/<stem>_words.json` (a montage source; folder matched exactly then case-insensitively) or `<Episode>/Interviewees/<who>/<clip>_words.json` (an interview), mapped through `TC_MEDIA_MAP`.
  3. A video file in `<Episode>/Clips/<stem>/` named after the stem.
- A source with an audio extension means "sound only" (or "multicam" for a clip whose name ends " multicam"). A clip ending " multicam" with nothing found is "a multicam is a sequence". Otherwise "its media file was not found".
- Words files over 64 MB are ignored. Clip names are only compared with directory entries.
- `TC_MEDIA_MAP` (environment): `P:/=/media;Q:/=/mnt/q` pairs mapping a recorded path prefix (separators normalised, case-insensitive) to a local one; an unmapped absolute path is used as is. Default: no mapping.

### 16.3 Making proxies

- Made only when a page with the window up asks (`on=1`), ONE at a time, in a queue of at most 64 waiting ("Waiting for the server to make the video proxy…" beyond that), each queued once.
- First a probe of the first video stream (codec, size, frame rate; 60 s timeout). No video stream: fails "the file has no video track".
- Encode: H.264, `veryfast`, CRF 26, height capped at 480 lines and made even, never enlarged; a keyframe every second (the group of pictures is the source's own frame rate, rounded); no audio, subtitle or data tracks; yuv420p; web-optimised so playback can start before the end; 60 minute timeout.
- Written to a temporary file and renamed into place only when ffmpeg succeeds; leftover temporary files are removed when the server starts.
- A failure is remembered (per media file version, at most 1024) and reported; a changed media file (size or time stamp) gets a new proxy and a new try.
- Cache folder: `TC_VIDEO_CACHE`, default `<TC_MEDIA_CACHE or system temp/tc-media-cache>/video`. Cap: `TC_VIDEO_CACHE_BYTES`, default 8 GiB. After each new proxy, the least recently used are deleted until under the cap, never the one just made nor one served in the last minute. Serving a proxy marks it used (its file time is bumped at most once a minute).
- Stopping the server cancels the queue and the running encode.

## 17. The montage builder

(source: features/montage/client.ts, ops.ts, server.ts, bridge.py, styles.ts)

### 17.1 The panel

- A drawer titled "Montage builder". Ways in: toolbar button "Montage" (order 30, shows "Alt M", tooltip "Describe a montage and Claude cuts it from the corpus", pressed while open); keyboard Alt+M toggles it; it is also registered as an overlay. Close button (shows "Esc") and Escape close it; focus returns.
- Desktop: a 468 px drawer at the right, from under the header down to the top of the lane, at least 600 px tall (it reaches over the lane's right-hand end when the panels are shorter, or up over it when the lane is docked on top). Phone (700 px or narrower): the whole screen.
- Every key typed in the panel is kept from the editor's shortcuts.
- "Describe the montage" text box (5 rows, at most 8000 characters, spell-checked), with an example placeholder. Ctrl+Enter (or Cmd+Enter) sends; plain Enter is a newline. With a proposal showing, the box shrinks to 64 px.
- Buttons: primary "Cut the montage" (shows "Ctrl Enter"; secondary once a proposal is showing) and "Revise it" (enabled only after a montage exists in this conversation; tooltip "Change the last montage: same conversation, a sentence, seconds" or "Cut a montage first, then ask for changes"). Both disabled when Claude is unavailable, the status could not be read, or the episode has no corpus (the tooltip says why).
- While working: a busy "Cutting" / "Revising" and a red "Stop".
- Status line (with an icon by tone): "asking the server…"; "starting…"; "reading the corpus, part <k> of <n>…" / "reading the corpus…"; "cutting the montage…" / "revising the montage…"; "finding the words in each clip…"; a lost-session note prefixed; failure or cancellation reasons; "the montage builder needs claude on this server: <reason>"; "this episode has no corpus yet: transcribe some clips into Clips\ first"; "the corpus is already in this conversation: ask for a change and it comes back in seconds"; "say what the montage should be, and claude reads the corpus once (<n> clips)"; "<n> cuts in <n> sections (answered in <s> s): look it over below, then insert it or discard it".
- Session line: "Conversation <first 8 characters of id> · <n> turns" and "Start a new conversation" (tooltip "Forget this conversation: the next montage reads the corpus again"; hidden while working). After a reset: "a new conversation: the next montage reads the corpus again".
- Local messages: "say what the montage should be first" (empty box), "the montage builder could not be reached: <reason>".
- Polling only while the panel is open: every 1 s while a montage is being cut, every 10 s idle, every 5 s after a failed read. A change of cut list resets the panel and asks again.

### 17.2 The proposal and inserting it

- "Proposed" box: "<n> cuts · <total seconds> · <n> notes"; "Asked: <text>" or "Revised: <text>"; a warning "<n> cuts named a clip that is not in the corpus, and went nowhere: <up to four clip names>."; the sections ("§ 1", "§ 2", ... and their titles), each listing its cuts: clip name (any trailing `[id]` tag hidden), length, a gold "Whole segment" chip when the exact words were not found and the whole transcript segment is used, the words (marked with the clip's language from its transcript, else the language detected from the script, else none), and "Why: <Claude's reason>". Unmatched quotes show a red "Not found" chip and "Kept as a note: nothing Claude proposed is thrown away."
- A new proposal scrolls into view.
- Footer "Insert it" choice: "At the end of the cut" (default), "At the start of the cut", "Before the selected cut (cut <n>)" (when a cut is selected), and "Before <§ / ◆ heading>" for every heading. An option that no longer exists falls back to the end. The choice is never rebuilt while it has focus.
- Footer sentence: "Lands <where>. Its sections become § sections." or "...Inside a section, its sections become note rows, so the cuts after it stay where they are." plus " The cut goes from <m:ss> to <m:ss>." and " One undo takes it all out." If the montage cannot be placed, the reason replaces it and Insert is disabled.
- "Insert into the cut" (primary): builds the ops against the cut list as it is at that moment and applies them as ONE batch through the shared proposal pipeline (source "montage", titled "Montage: <first 120 characters of the request>"), so it is one undo step and syncs like any edit. The new cuts are then selected. "inserted <n> cuts <where>. Undo takes it all out again." On refusal: "the montage was not inserted: <reason>"; when it cannot be placed: the reason or "the montage could not be placed: <reason>".
- "Discard": "discarded: nothing was changed".
- An inserted or discarded proposal is never offered again on this page, and the server is told so no other page offers it.

### 17.3 Where it lands

- At the end, at the start (when the cut list starts with a heading), or before a heading: each montage section becomes a `## §` section heading (built at the end, then moved in front of the chosen heading).
- Before a cut in the middle of a section: each montage section becomes a `- (note)` row "montage: <title>", so the following cuts stay in their section. A cut that opens its section (no cut between it and the heading above) counts as "before that heading".
- At the start with no heading first: before the first cut, as note rows. An empty cut list: at the end.
- Where sentences: "at the end of the cut", "at the start of the cut", "before § <title>", "before cut <n>, inside its section".
- Refusals: "that section is no longer in the cut list -- pick another place"; "that cut is no longer in the cut list -- pick another place"; "the montage has nothing to insert -- ask for it another way".
- Nothing is dropped: an unmatched quote becomes a note row "unmatched: <clip> -- <quote>"; a cut whose clip name cannot be written in a cut list, whose span is not a time, or that is shorter than the minimum cut length becomes a note row "unmatched: <clip> -- <quote> (<reason>)".
- New cuts carry the words (or the quote) as their text and Claude's reason as their note. A corpus clip the cut list has never used is added to the cut list's clip facts (its frame rate, start 00:00:00:00).

### 17.4 Routes

- `GET /api/montage?key=<key>`: the current job, whether Claude is available, the number of corpus clips under `<Episode>/Clips/` (a listing only, remembered 15 s), the conversation id and turns, whether the corpus is already in the conversation, and any status error (for example "the montage builder needs Python 3.12 on the server: <reason>").
- `POST /api/montage {key, text, revise}`: starts a montage (or a revision) and answers the job at once. Refusals: 503 `closed` ("the server is shutting down"); 400 `empty` ("say what the montage should be first"); 400 `too-long` ("a montage note is at most 8000 characters"); 400 `bad-key`; 404 `not-found` ("that cut list is not in the vault"); 409 `busy` ("a montage is already being cut for this cut list"); 503 `busy` ("<n> montages are being cut already -- try again when one is done", at most 2 at once across the server).
- `POST /api/montage/cancel {key}`: stops the running one and kills Claude; the job ends "stopped: nothing was changed".
- `POST /api/montage/dismiss {key, job, how}`: marks a finished proposal accepted or discarded (any `how` other than "accepted" counts as discarded).
- `POST /api/montage/reset {key}`: forgets the conversation; 409 `busy` ("a montage is being cut: stop it first") while one runs.
- Every route needs a valid key for an existing cut list (400 `bad-key` "no project key" when missing).
- Job stages: queued, opening, describing, resolving, done, failed, cancelled. One job kept per cut list, in memory; nothing writes the cut list.

### 17.5 How a montage is cut

- The episode's corpus (its transcribed clips under `Clips`) is digested by the old Python code into parts; a missing corpus fails "this episode has no corpus yet: transcribe some clips into Clips\ first (pipeline.py transcribe --folder ...)".
- The corpus goes into one Claude conversation once, part by part, without extended thinking; later requests are one sentence into the same conversation, so a revision comes back in seconds. A conversation that did not finish reading the corpus is thrown away and the corpus goes in again from part one.
- The request turn uses thinking and may write one JSON answer file into a temporary folder inside the shared Claude runner's working folder (`<temp>/tc-editor-claude-cwd/montage/desc-*`), removed after each turn.
- A lost conversation (the provider no longer knows its id) is re-opened with a new id once, and the status says "the Claude session was lost (new machine or a rebuilt container); re-reading the corpus". Lost twice: "the Claude session could not be opened: the provider refused the id twice running" or "the Claude session was lost twice running -- give it a moment and retry".
- Revise refusals: "there is no montage to revise yet: cut one first"; "the corpus has changed since the last montage, so there is no montage to revise in this conversation: cut it again".
- Claude's quotes are matched back to the clips' words by the old matcher (frame-accurate, falling back to the whole segment); a quote found nowhere is kept as unmatched; a clip not in the corpus is listed as dropped. A corpus re-transcribed while the montage was being cut is refused: "the corpus changed while the montage was being cut -- ask again and it reads the new one". No placeable cuts at all: "the model proposed no cuts this server could place -- try saying it another way"; no sections: "the model's answer has no sections -- try saying it another way".
- Other failure sentences: "the montage builder needs claude: <reason>"; "the corpus could not be read into the conversation: <reason>"; "the model run produced no usable output: <reason>"; "the montage helper answered without the corpus prompts"; "the montage helper answered with something that is not a montage"; "the montage took longer than <n> min and was stopped".
- Limits: wall clock per montage `TC_MONTAGE_TIMEOUT_MS` (default 60 minutes); each Python call 120 s; each Claude turn's timeout and the model come from the old configuration (900 s and "sonnet" if it gives none); at most 200 sections, 2000 cuts per section, quotes of 2000 characters.
- The conversation record is kept by the shared AI session store (one per cut list, keyed by the corpus), not beside the cut list in the vault.
- Stopping the server cancels every running montage.

## 18. Markers and sections: the overview panel

(source: features/markers/client.ts, ops.ts, styles.ts)

### 18.1 Opening it

- A floating panel "Overview" (top right, 440 px wide; on a phone a full-screen sheet). Ways in: toolbar button "Overview" (order 10, shows "O", pressed while open); keyboard O toggles it; its own close button (shows "O"). Whether it was open is remembered per device (localStorage `tc_markers_open`).
- Keyboard O and M are ignored with any modifier, while typing in a text field, during text composition, or (for M) on key repeat.
- Escape inside the panel steps back: cancels a drag, then a picked-up section, then the add form, then the editor, then closes the panel.
- Bar aside: "<n> sections · <n> markers".
- With no cut list: "Open a cut list to see its sections."

### 18.2 The list

- Every marker in document order: `## §` sections (a coloured tag "§ <number>" taken from a "1.1 - Name" title, and the name), `## ◆` note headings, plain headings, and `- (note)` rows (italic; flag icon for a note starting "⚑", the planner's lead-in markup stripped; "Empty note" when empty). Headings inside a § section are indented.
- Each heading shows "<n> cuts · <m:ss>" (a § counts up to the next §; any other heading up to the next heading; gaps add length) or "empty".
- The heading the playhead is under is highlighted.
- Click a marker (or its name): "take me there": the playhead goes to the start of the cut it stands in front of and that cut is selected (or the head goes to the marker's time when nothing follows it); the marker is selected; on a phone the panel closes on the way.
- Per row buttons: a fold button for headings (see 18.6), "AI summary of this section (up to the next marker)" / "Summarise this section again" / "Summarising" (sparkle), and "Edit this marker" / "Edit this note" / "Close the editor" (pencil).
- Empty cut list of markers: "No sections or markers yet. Add a section to start one at the selected cut."

### 18.3 Adding and editing

- "Add section" and "Add note" buttons (pressing again cancels). "New markers go <where>": "in front of cut <n>, <speaker or clip>", "in front of the gap", "in front of the selected cut", or "at the end of the cut". The place is the first selected cut or gap, else the item under the playhead, else the end.
- Add form: "New section" with "Name" (at most 120 characters, placeholder "Section") and a colour picker pre-set to the first colour of the rotation that neither the neighbouring § before nor after wears; or "New note" with "Note" (at most 400 characters). "Goes <where>. Select a cut or move the head to put it elsewhere." Buttons "Add section"/"Add note" and "Cancel" (Esc). Enter adds. A section with no name is called "Section"; a note with no text is refused ("Write the note first."). Says "Section/Note "<name>" added <where>."
- Editor under a heading: "Name" field (Enter or leaving the field saves; Escape restores; an empty name keeps the old one); "Kind" choice Section / Note / Heading (a colour is not a kind: changing one does not change the other); "Colour" swatches (the marker colour palette, a radio group); "Move to cut <n>" / "Move to the end" (moves it in front of the selected cut or the cut under the head; "It already stands there." when it does; "Moved in front of cut <n>. Ctrl+Z puts it back."); red "Delete" ("<name>" deleted. Ctrl+Z brings it back."); "Done".
- Editor under a note row: "Note" field (at most 400), move, delete, done.
- Every change is one undoable edit; an edit that changes nothing is not sent. A refused edit says its reason ("that edit was refused").
- Status line under the list: info messages clear after 6 s; warnings and errors stay.

### 18.4 Moving sections

- A § section moves with everything up to the next § (its cuts, notes and sub-headings), as one undo step. It lands only in front of another § or at the end.
- Mouse: drag the grip, or drag the section's name (a press that does not move 4 px stays a click). A cyan line shows where it will land; near the panel's top or bottom edge (40 px) the list scrolls.
- Touch: a long press (350 ms) anywhere on a section row (not on its buttons) picks it up, with a short vibration where supported; moving 10 px before then cancels (a scroll). A tap on the grip also picks it up. Then "Moving "<name>": tap the section it should come before (tap it again to cancel)."; tapping another section drops it there; a "Put it at the end of the cut" button appears at the end of the list; tapping a non-section says "A section lands in front of another section. Tap a section, or "Put it at the end of the cut"."
- Keyboard on the grip: Up / Down move it one slot ("It is already the first section." / "It is already the last section."). See "Claims" for the Alt detail.
- Messages: "Section "<name>" moved. Ctrl+Z puts it back." / "...moved up/down..."
- Section numbers follow the order: every § titled "<whole number> - Name" is renumbered in the new order, counting from the smallest number there was, with no holes, keeping zero-padding width ("07"); "1.1"-style and unnumbered titles are left alone; only when at least two sections are numbered.

### 18.5 Ruler and keyboard marker

- The sections ruler: the whole cut as coloured segments by section (a hatched "Before the first section" segment when the first § is not at 0), ticks for other markers, the playhead line, "0:00" and the total length. Clicking a segment jumps there.
- Keyboard M (panel open or shut): a § section heading in front of the cut (or gap) under the playhead, untitled, in the offered rotation colour. "Section added in front of cut <n>. Ctrl+Z takes it off." Refusals: "There is no cut under the head to mark." and "Cut <n> already starts a section ("<title>")." / "That gap already starts a section (...)". Through the shell it is told in a toast; standalone, on the panel's status line.
- Game-pad toggle (called by the editor's pad input, LT + L3): the same as M, but when a § already stands directly in front of the cut under the head and the head is within 0.5 s of that cut's start, it takes the section off instead ("Section taken off in front of cut <n>. Ctrl+Z puts it back.").

### 18.6 Folding sections in the cards list

(source: features/markers/fold.ts, styles.ts, client.ts)

- Every section head in the cards list gets a chevron fold button ("Fold <name> away and read its summary" / "Open <name>", shows "W"); W on that button (no modifiers) toggles it. The overview carries the same toggle per heading row ("Fold <name> away in the cards list" / "Open <name> in the cards list") on the same state.
- A folded section hides its notes, cards and gaps and keeps its head, plus one row "AI summary": the summary stored under the heading in the cut list, with a gold "Out of date" chip when the section's words changed since; "Summarising…" while one is being written; or "No summary yet." (or "The summary did not come back: <reason>") with a "Summarise" button (disabled with a reason: "Section summaries are not available here", the Claude-unavailable sentence, or "Nothing transcribed in this section to summarise").
- Folding the section currently scrolled past keeps its head in view.
- A fold is a way of looking, not an edit: it is per device, per cut list, in localStorage `tc_sec_closed`, keyed by the section's title (`Title#2` for the second of that name), so trims, moves and reloads keep it and a rename opens it. At most 500 folded sections per list and 200 lists remembered (the least recently touched forgotten first).
- Showing a cut that is inside a folded section (a new keyboard focus, or a new single selection from a click, a jump, the overview) opens that section. Playback runs through folded sections without opening them.
- The opening rows before any heading have no fold.

## 19. Markers: section summaries

(source: features/markers/client.ts, server.ts, summary.ts, ops.ts)

### 19.1 In the panel

- The sparkle button asks Claude for a one- or two-sentence summary of the section's words (each cut as "<person>: <words>", up to the next heading of any kind; note rows do not end a section). Disabled with "Nothing in this section to summarise", "Section summaries are not available here", or "The summary needs the claude CLI on the server: <reason>".
- Refusals before sending: "Nothing transcribed between this marker and the next, so there is nothing to summarise."; "The summary did not start: <reason>".
- When this page's answer comes back it is written into the cut list as ONE undoable edit under the heading, with a fingerprint of the words it was written from: "Summary of "<title>" written into the cut list. Ctrl+Z takes it out." If the section is gone: "The summary came back, but its section is no longer in this cut list." A failed run: "The summary did not come back: <reason>".
- Under each heading: the stored summary, a gold "Out of date" chip when the words changed since, and a "Remove this summary" button ("Summary removed from the cut list. Ctrl+Z brings it back.").
- An answer this page did not ask for (another device, a reload) that the cut list does not have: "A new summary is ready", the text, "Keep it" (or "Use this one" when a summary exists; writes it: "Summary written into the cut list. Ctrl+Z takes it out.") and "Discard".
- The panel polls for running summaries every 1.5 s, even when shut if this page is waiting for one of its own answers; it stops after about 10 minutes. "Summaries could not be read: <reason>" on the status line when the list fails.
- A change of cut list forgets all summary state.

### 19.2 Routes

- `GET /api/markers/summaries?key=<key>`: whether Claude is available (and why not), and the answers held for that cut list (per section: text, error, words fingerprint, title, running, time, the asking page's request id).
- `POST /api/markers/summary?key=<key>` body `{section, title, body, hash, req?}`: starts one summary and answers `{ok, running}` at once. A summary already running for that section answers the same without starting another.
  - Refusals: 400 `bad-key`; 404 `not-found` ("there is no such cut list"); 400 `invalid` (not an object, a field not text, `section` or `hash` empty, `hash` not 1 to 32 hex digits, `req` not a short id); 413 `too-large` (section over 320, title over 300, body over 60 000 characters); 422 `empty-section` ("nothing transcribed between this marker and the next"); 503 `closing`; 503 `no-ai` ("the section summary needs the claude CLI: <reason>"); 429 `busy` ("other summaries are still being written; try again in a moment") when 2 are already running across the server.
  - Request body limit about 244 KB.
- The prompt asks for ONE sentence, two at most, 35 words in all, plain English, no preamble; the section title and body are filled in (an empty title is "marker"). Model `claude-sonnet-5`, no thinking, 5 minute timeout, through the server's shared Claude runner.
- An empty answer is a failure ("claude returned nothing").
- Answers are held in memory only: 30 minutes, at most 400 per cut list and 200 cut lists. The server writes no file; the page turns the answer into an edit.

## 20. Markers: development and drift checks

(source: features/markers/bridge.py, dev/entry.ts, dev/serve.ts, dev/shoot.ts, tsconfig.json)

- DEV ONLY: `bridge.py` reads the old app's summary model, prompt and section-naming rule so tests can hold the TypeScript copies to them; no running server registers it.
- DEV ONLY: a test page with the editor and only this feature, a server on ports 48660 to 48679 over a copy of the test vault with a fake Claude that answers summaries, and a screenshot script (`npx tsx features/markers/dev/shoot.ts`) writing `features/markers/shots/<scene>--<size>.png` for overview, editing, adding, folded and moving at 1440x900, 390x844 and 844x390. Requires `TC_FIXTURES`.
- `tsconfig.json`: type-checking configuration only.

## Looks redundant or overlapping

- Two ways to keep a cut list on this device: this part's "Download for offline" (PCM windows in the browser's IndexedDB) and the separate keep-on-this-device feature reached by the sheet's "Keep" button and "On this device" tag. The automatic keep in the apps (10.6) stands down whenever the keep feature is loaded, so in that build it is dead code.
- Two Send to Resolve buttons: the views' header button and this feature's toolbar "Send to Resolve", which only shows when the header one is absent.
- Two launchers for the Resolve panel and for the overview: a hand-mounted launcher and the platform toolbar item; the platform adopts the hand-mounted panel and removes its launcher. The video window has the same double mount (private slots, then adoption).
- Two plain-script download paths: the Export tab's Script tile and Ctrl+S / Ctrl+Shift+S (plus two palette entries).
- The Resolve "drift" diff appears three times: the chip, the Import tab's drift box, and the Send tab's "Since the last send" diff, each computed by a separate call.
- "Import a timeline file" and "Read the Resolve timeline" produce the same proposal through two routes.
- Section folding has two controls on one state: the fold button in the cards list and the fold button in the overview.
- Summaries are offered from three places: the overview's sparkle button, the folded section's "Summarise" button, and the "A new summary is ready" keep/discard row.
- Three popup mechanisms in the video folder: the video pop-out page (`/video/window`), the `?panel=` single-panel windows, and the `?tcwin=pop` whole-editor windows, each with its own recall rules.
- `offlineKey` exists twice (offline-key.ts and a copy inside offline-sw.js).
- The video feature's folder also carries the whole multi-window system (lane, transcript, chat, overview, cards windows), which is not about video.
- The dashboard-mount host and the native-app shells overlap with the CC Sync dashboard's own `/cards/edit` proxy (inventoried elsewhere): the host's prefix rewriting exists because the client uses root-relative URLs.
- The projects server serves `/sw.js`, which has nothing to do with projects.

## Claims the code does not back

- features/projects/offline.ts says the downloader's `x-tc-offline-fetch` header makes the worker layer let the request through to the server, and README section 5 says these requests "pass straight through". offline-sw.js never looks at that header: a kept audio window, audio file or video proxy is served from the kept copy even to the downloader, and while working offline the layer refuses the downloader too.
- features/resolve/companion.ts says "one outstanding ask per kind at most: a poll that is still waiting is answered by the same promise". The code makes a new request every time and only refuses when more than 16 are waiting; the header's "at most 16 asks wait" is in fact 17.
- features/markers/server.ts says "writes per cut list are serialised and atomic". The service writes no file at all (it holds answers in memory).
- features/markers/client.ts (grip tooltip and `aria-keyshortcuts`) says Alt+Up / Alt+Down moves a section. The code moves it on Up / Down with or without Alt (and with Shift); only Ctrl and Meta are excluded.
- features/montage/README.md says a clip whose transcript does not name its language is marked `zh` only when its words are Han script. The code marks whatever language the script detector returns (Russian, Ukrainian, Japanese, Korean, Chinese and others).
- features/resolve/README.md says the script's gap notes come from the gapnotes sidecar, read through `gapNotesOf`. The running code takes them from the gap rows in the cut list (a sidecar reader is only an injectable test hook).
- features/resolve/README.md's file table lists bridge.py's commands as conform-plan, conform-apply, timeline-read, ping; it also has timeline-diff.
- features/projects/README.md lists a `canvases` command among the bridge's uses; no route calls it.
- features/video/shared.ts defines the sentence "No video: ffmpeg is not available on the server." (`WHY.noFfmpeg`); nothing ever shows it.

## Could not determine

- Whether `router.get('/sw.js')` in features/projects/server.ts also answers HEAD (the handler checks for HEAD, but whether the router routes HEAD to a GET handler is outside this part).
- What the rename refusal's "wait about ten minutes after the last edit" corresponds to: the rename takes the lock with a 30 s staleness rule; the ten minutes is presumably the sync service's own lock lifetime, outside this part.
- The exact MARKER_COLOURS / SECTION_COLOURS palettes and rotation order, the minimum cut and gap lengths, and the ±30 dB gain limit's source constants: they live in core/src/model.ts, outside this part.
- Whether the old conform's "a clip the media pool does not have refuses the conform" (resolve README) holds: that rule lives in project_conform.py, outside this part.
- The montage Claude turn timeouts and model actually used: they come from `multicam_pipeline/cards/config.py` (MONTAGE_MODEL, MONTAGE_OPEN_TIMEOUT, MONTAGE_TIMEOUT), outside this part; 900 s and "sonnet" are only the fallbacks.
- How the editor shell's key slot treats Ctrl+S "inText" and Shift+V (repeat, typing) beyond what this part requests; the binding is in client/platform.
- The Python interpreter default per platform for the companion and the pools (README says `py -3.12` on Windows, `python3` elsewhere); it is decided in server/pybridge, outside this part.
