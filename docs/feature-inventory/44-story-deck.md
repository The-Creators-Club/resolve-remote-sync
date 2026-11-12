# Story Deck: reading, noting and ordering the film with the agents

**PARTIAL, and a record only.** The owner cut Story Deck from the rebuild on
2026-11-12 ("story deck gets canned, the game thing is annoying") while this
section was being read, and the reader was stopped. It covers the Python
side in full (the server, the rules, the stages, the agents, the quests, the
notes, the build). The page itself (`storydeck/page`, `storydeck/lab`) and
the `tools/storydeck_*` files were NOT read, and the three closing lists
were never written. Nothing in the rebuild plan's later steps uses this.

Terms used throughout:

- **Card** (also **tile**): one transcript paragraph from the themed canvas, identified by its number `n` (its 1-based position in the canvas's reading order) and usually by a six-character `^ref` (the block id in the transcript note).
- **Lane**: a row of cards. A lane has a **kind**: `draft` (a topic group as Claude made it on the themed canvas), `film` (a section of the new cut), `staged` (a shelf of set-aside cards, also called a staged-only bin) or `bin` (the interviewer questions and chatter bin). Each lane holds cards in three **zones**: `order` (the playing order), `stage` (set aside from the playing order, on the lane's own shelf) and `held` (staged at the deal; dealt to the lane's shelf without ever playing).
- **Frosted** lane: a lane the notes say has not been read yet. It keeps source order and agents may not touch it.
- **Structure Notes**: the editor's markdown file `<Episode> - Structure Notes.md` (sections Rules for the re-order, The shape, Moves, Lines to build on, Open, Inbox, Raw notes).
- **Spine**: the list of **beats** (acts and numbered beats such as `1.1 Name`) taken from the notes' Shape section, or sketched on the board.
- **Pin**: a card fixed to a lane by the editor; agents can never move it.
- **Named card**: a `^ref` the notes place in a particular lane (beat).
- **Proposal** (also **ghost**): something an agent suggests; it changes nothing until the editor takes it.
- **Quest**: a question put to the editor (title, cards, consequence, 2-4 options plus "keep it open").
- **Stage**: one of seven ordering stages, 0 to 6, each locked in turn.
- **Work folder**: the folder Story Deck keeps its state in.
- "Alex" is how the code and the agents' prompts refer to the editor; it is the only person role.

## Starting the program
(source: storydeck_web.py, storydeck/server.py)

- Started from the command line: `storydeck_web.py --canvas "<Episode> Canvas (Claude).canvas" [--notes "<Episode> - Structure Notes.md"] [--work <folder>] [--port 8823] [--model fable] [--no-browser]`.
- `--canvas`: the themed `.canvas` file. Required unless `--work` points at a folder that already holds a board. Refusal: "--canvas is needed" when neither is given; "no such canvas: <path>" when the file does not exist.
- `--notes`: the Structure Notes file. Default: `<Episode> - Structure Notes.md` in the same folder as the canvas, used only if it exists. Refusal: "no such notes file: <path>".
- `--work`: the work folder. Default: `<base>\<Episode>\storydeck-<YYYY-MM-DD>` (today's date), where `<base>` is `$STORYDECK_WORK` if set, else `<Editing checkout>\Transcripts\canvas-theme-picker\work`.
- Episode name is taken from the canvas file name: ` (Claude)`, ` - Ordered`, ` - Ordered Vn` and a trailing ` Canvas` are stripped (`Disaster Preparedness Canvas (Claude).canvas` -> `Disaster Preparedness`).
- `--port`: default 8823. `--model`: the agents' model, a short name ("fable" default; "opus", "sonnet" and full `claude-...` ids also accepted).
- `--no-browser`: without it the default browser is opened at the page 0.6 s after start.
- Listens on 127.0.0.1 only; there is no option to listen on another address.
- If the port cannot be opened it prints "Story Deck: cannot listen on 127.0.0.1:<port> (<reason>)" and exits with code 1.
- On start it prints the episode, card and lane counts, the work folder, the notes path (or "(none)"), where speaker colours come from ("interviewee_colors.json (N)" or "the canvas's own, else a built-in palette"), and the URL.
- Opening a work folder:
  - A folder holding `board.json` is opened as it is (its board is the editor's work), replaying any events in `events.jsonl` that the snapshot has not seen (recovery after a crash between the log line and the save). A torn last log line is ignored.
  - A folder holding only the structure-notes skill's files (`sections.json`, `assignment.json`, `seq/<KEY>.json`, `splices/*.json`, `cards.jsonl`) is rebuilt into a board: film lanes from `sections`, staged lanes from `staged_only`, an `INTRO` lane when any card is assigned to it, a question bin (key `Q`) of unassigned cards from the question groups, dropped cards from the drop groups, splices from every `splices/*.json`. Cards come from the source canvas if it still exists, else from `cards.jsonl` (then without colour or transcript path).
  - Otherwise a new board is made from the canvas: one draft lane per canvas group in canvas order (keys `D01`, `D02`...); a group whose label starts with "Staged" becomes a `staged` lane, one starting with "Uncat" becomes a `bin` lane. Bin labels become the board's question groups. The folder is created with `board.json` and the skill's files.
- Lanes that the notes' "Read so far" line says are not yet read are marked frosted at start (in memory, saved with the next change).
- Speaker colours: from `interviewee_colors.json` beside the canvas (`colors[who].hex`, six-digit hex only); else the colour the canvas gave that speaker's first card; else one of eight built-in colours chosen by a hash of the name (so a speaker keeps a colour).
- Never calls DaVinci Resolve.

## Who may call the server, and the HTTP rules
(source: storydeck/handler.py, storydeck/routes_play.py)

- Every request must carry a `Host` header of `127.0.0.1:<port>`, `localhost:<port>` or `[::1]:<port>`; otherwise 403 `{"error": "bad host"}` (defence against DNS rebinding).
- A POST with an `Origin` header that is not one of those three is refused 403 "bad origin".
- A POST must have `Content-Type: application/json`; otherwise 405 "this route does not take that verb".
- POST body larger than 1 MiB: 400 "body too large". Unparseable body: 400 "the body is not JSON". A body that is not a JSON object: 400.
- PUT, DELETE and PATCH are refused 405. A POST no route answers: 405. A GET no route answers: 404 "not found".
- Any unexpected error in a route: 500 with the error's type and message.
- Responses over 1 KiB of JSON, HTML, CSS or JS are gzip-compressed when the browser accepts gzip. Fonts are cached for a day; everything else is sent `no-cache` (JSON `no-store`).
- A rule refusal is 409 `{error, rule, name, message}` where `name` is the rule's human name (see "Rule names shown to the editor").
- An unknown card, lane or bad field is 400; an unknown proposal 404.

## Routes: page and board
(source: storydeck/handler.py, storydeck/view.py)

- `GET /` (or `/index.html`): the page.
- `GET /static/<file>`: only `.css`, `.js`, `.woff2` and `.txt` files under the page folder; hidden files, parent folders and other extensions are not served (404).
- `GET /api/health`: `{"ok": true}`.
- `GET /api/board`: the whole board as the page draws it:
  - the current stage (number, of 6, name, goal, progress) and all seven stages with their state (locked, open, stale, future), the stale list and whether all are done;
  - the film's playing seconds, the runtime target, and the total seconds of montage slots;
  - the splices and the cards that want a splice;
  - the contest threshold (default 0.6);
  - whether notes were found, their "Read so far" text and "Last tidied" date;
  - totals (cards, lanes, seconds);
  - speakers (short name and colour);
  - every lane: key, label, kind, act, frosted, how many cards are read, seconds, card numbers, which cards lie face down (all cards of a staged lane; the stage and held zones of other lanes), the rules it breaks, playing seconds, fixed way in and out, named refs (non-draft lanes), "what it is for" (the plain text of the beats pointing at it, at most 420 characters), its beat ids, whether its order is decided ("sequenced"), its montage slots;
  - every card: number, ref, speaker, question flag, English, Chinese, seconds (rounded to 0.1), the beats that name it, kind, the rules it breaks;
  - the spine (the board's own beats, else the notes' Shape) with each beat's act number, act name, named refs as chips (each with card number, speaker and question flag) and how many refs are Claude's interpretation;
  - the stickies (id, attached card or pair, text, time, which lane they sit in);
  - the rule findings and their counts by severity.
- Before the Deal (no film lane yet, or the current stage is below 2) the "every card placed" warning is left out of the board view, since nothing is placed yet.
- A draft lane with no read marker, not named unread by the notes, is shown as fully read when the notes have any "Read so far" text.
- Short speaker names: the Latin part of the folder name, reduced to the surname: `詹忠翰 Chung-Han Chan` -> Chan; `李鴻源 Lee Hong-Yuan` -> Lee (hyphenated given name last means surname first); `Ma, Kuo-Fong` -> Ma; a doubled name `Kulas Umo Kulas Umo` -> Kulas; a name with no Latin letters is kept whole.

## What the editor's changes are recorded as (the board's one door, undo and redo)
(source: storydeck/model.py, storydeck/ops.py, storydeck/routes_play.py)

- Every change to the board is one logged event appended to `events.jsonl` in the work folder (id, time, author `alex`, `agent` or `seed`, the change and its inverse), and `board.json` is rewritten after each event.
- Several changes made together (a multi-card move, a lock with its renumbering, a batch of takes) are one event and one undo step; a batch either applies whole or not at all.
- Undo reverses the newest live event; redo re-applies the newest undone one; a new change clears the redo stack. Undo and redo are themselves logged, so the undo and redo stacks are rebuilt from the log when the folder is reopened (undo survives a restart).
- Refusals on undo/redo: "nothing to undo", "nothing to redo".
- When an undone event was a taken proposal, the proposal goes back to pending (marked as undone) and the proposals it had superseded become pending again; redo makes it taken again and re-supersedes them.
- After undo or redo, the Inbox of the notes is re-synced with the stickies (an undone sticky's Inbox line is removed, a redone one comes back).
- Changes only a person may make; an agent attempting them is refused "an agent cannot <op>" (rule "human-only"): pin, unpin, unlock, relock, marking a lane read, settings (including stage locks, runtime target, montage slots, "sequenced"), moving a lane, answering a quest, restoring or dropping a quest.
- An agent change that would move a pinned card is refused "card N is pinned; an agent can only suggest" (rule "pinned"); one that touches a frosted lane (as source or target) is refused "lane K is frosted (unread): agents keep out" (rule "frosted").
- The editor's own moves are dry-run first on a scratch copy and refused when they would ADD a rule error (errors already standing never refuse a move).
- Every change response carries the logged event in words, the part of the board that changed, and the play state (pins, unlocked cards, fixed ways in and out, can-undo, can-redo, proposals, rule names, agents' status).
- Wording of the log (what the history shows): "moved Aldrich ^wv5jae to <lane> (position 3), from <lane>", "set X aside", "brought X back into play", "pinned X", "unpinned X", "unlocked ^ref (<why>)", "locked ^ref again", "marked <lane> read to N", "opened the lane <label>", "changed lane <label> (<fields>)", "removed lane <key>", "moved lane <label>", "set the runtime target", "changed the montage slots", "marked a lane's order as decided", lock and reopen notes such as "locked stage 2, Deal (412 of 600 cards placed)", "added a note", "changed a note", "removed a note", "added/changed/moved/removed a beat of the shape", "raised the question <title>", "answered a question (<words>)", "took a question off the board", "put a question back", a batch as its first three parts "; and N more", "undid: <what>", "redid: <what>". An event made by taking a proposal is prefixed with the proposal's label and records who took it.

## Routes: the editor's moves
(source: storydeck/routes_play.py)

- `POST /api/move {n, lane, index?, zone?}`: put card n into lane at position `index` (end when absent) of zone `order` (default), `stage` or `held`. A move to the place the card already holds is a no-op (no event). A pinned card's pin follows it to the new lane. Unknown lane: 400 "no lane ...". Non-numeric index: 400.
- `POST /api/move {ns: [...], lane, index?, zone?}`: move a selection as one event; the cards land together, in the order given, in front of the first unselected card at `index` of the lane as it is without them. Zone must be order, stage or held. No-op if nothing would change.
- `POST /api/stage {n | ns}`: set aside.
  - A card in a film lane's playing order goes to that lane's shelf (stage zone). Not in a playing order: "card N is not in a lane's playing order".
  - A card still in a draft lane goes onto a staged shelf named `staged -- <draft lane label>`, created the first time it is needed (key `S01`, `S02`..., placed after the last staged lane).
  - A card already in a staged or bin lane, or in no lane: 400 "card N is already off the film: drag it into a lane to play it".
- `POST /api/unstage {n | ns, index?}`: bring back from the shelf into the playing order at `index` (each following card one further on). A card not staged: "card N is not staged".
- `POST /api/pin {n | ns, lane?, index?}`: pin each card (to its current lane unless `lane` is given). A card in no lane: "card N is in no lane to pin it to".
- `POST /api/unpin {n | ns}`: unpin. Not pinned: "card N is not pinned".
- `POST /api/unlock {ref, why}`: let a named card leave its lane. `why` is required: 400 "unlocking a named card needs a reason: say why". Unknown ref: "no card ^ref".
- `POST /api/relock {ref}`: lock it again. Not unlocked: "^ref is not unlocked".
- `POST /api/undo`, `POST /api/redo`: see above; the answer carries the whole fresh board and any Inbox changes.
- `GET /api/play`: pins, unlocked, gates, can_undo, can_redo, proposals (every pending one plus the newest 400 of the rest), rule names, agents' status, and the newest 200 events in words.
- `GET /api/events?limit=200&since=0`: the log in words.

## The rules of the game and the findings they raise
(source: storydeck/rules.py, storydeck/routes_play.py)

The rules run after every change; findings show on cards and lanes and their counts on the page. Severities: error, warning, exempt (listed but not a defect).

- **A card plays once** (`plays-once`, error): a card found in more than one place ("[N] ^ref is in 2 places (...): a card plays once"); the same `^ref` playing twice in the film ("^ref plays twice in the film ([a] and [b])").
- **Questions stay out of the film** (`question-in-film`): an interviewer question card (every line starts "# ") in a film lane's playing order is an error ("... is an interviewer question in the film (<lane>); only a card the notes name may play, so stage it"), unless the notes name that very ref for that lane, which is exempt ("... exempt, named in the notes for <lane>"). Frosted lanes are skipped except in the build check.
- **Named card stays in its lane** (`named-lane`): a ref named for two lanes (error "^ref is named for both A and B: a card plays once, ask Alex"); a named ref not on the canvas (warning); a named card not in its lane's playing order and not unlocked (error "... is named for <lane> but sits in <lane>/<zone>" or "in no lane").
- **Fixed in and out** (`gates`, warning): a lane's fixed way in must be its first playing card and its fixed way out its last ("<lane>'s fixed in should be [N] ^ref but is ^x / empty"); a gate ref not on the canvas.
- **Every card placed** (`placed`): cards in no film, staged or bin lane and not dropped: warning while playing, error in the build check ("N card(s) are neither placed nor staged").
- **Intro after the first line** (`intro-after-first`, warning): a speaker with more than one INTRO card ("keep the best, stage the rest"); an INTRO card whose speaker has no line in the film ("their INTRO ... will be staged"); a hand-placed intro playing before the speaker's first line.
- **Splice must be exact** (`splice-substring`, error): each "play" text of a splice must be found exactly once in the card's English (words in order, any whitespace between) and highlights must not overlap; a splice on an unknown card.
- **Unread lane keeps its order** (`frosted-order`, error): a frosted lane's cards out of ascending source order.
- How the film plays (used by the rules and the build): the film lanes' playing orders in lane order, with each speaker's INTRO card inserted after that speaker's first consecutive block; an intro whose speaker never plays is left out.
- Rule names shown to the editor: "A card plays once", "Questions stay out of the film", "Named card stays in its lane", "Fixed in and out", "Every card placed", "Intro after the first line", "Splice must be exact", "Unread lane keeps its order", "Pinned", "Unread lane", "Only Alex may do that", "Stage is locked", "Not a film lane", "Every card stays".

## The seven stages (the campaign)
(source: storydeck/stages.py, storydeck/routes_stages.py)

- Stages, with name, glyph and goal text shown on the page:
  - 0 "Read and note" (稿): "Read the themed canvas lane by lane and write your notes as you go. Lanes you have not read are carried forward, frosted."
  - 1 "Skeleton" (壹): "Turn the shape into the film's lanes: acts, what each lane is for, the fixed ways in and out, and the cards the notes name."
  - 2 "Deal" (貳): "Deal every card into a lane. Settle what two lanes want and what the agents are not sure of."
  - 3 "Sequence" (參): "Put each lane in playing order, as one conversation. Choose between competing orders; pin what must stay."
  - 4 "Joins" (肆): "Judge every join as a reply. Choose a bridge for each amber or red one."
  - 5 "Splices" (伍): "Trim every splice to exactly the words that play."
  - 6 "Build" (陸): "Read the dry run, build the new canvas, and check it against the pool."
- States: each stage is locked, stale (locked, but an earlier stage was reopened since), open (the current stage) or future. The **current stage** is the first that is not locked or is stale.
- Progress measure per stage (shown on the stage bar):
  - 0: "N of M lanes read" over draft lanes that hold cards; full once there are no draft lanes with cards left and other lanes exist.
  - 1: "N of M beats have a lane"; with no beats, the count of film lanes.
  - 2: "N of M cards placed" (cards in any non-draft lane, or dropped), plus ", K contested".
  - 3: "N of M lanes sequenced" over open film lanes with two cards or more.
  - 4: "N of M joins settled" plus ", K to choose" or ", K not judged".
  - 5: "N of M splices set", or "no splices wanted".
  - 6: "built: <file name>" once a build result exists, else "not built yet".
- **Lock in** (`POST /api/stages/<n>/lock {confirm?}`):
  - Only the current stage can be locked: otherwise "<Stage> is already locked" or "<Stage> is not open yet: lock in stage K first".
  - Stage number above 6: 404 "no stage N".
  - Errors block the lock (409 `{errors, warnings}`, message "<Stage> cannot be locked in: <first error>"). Warnings need a confirm (409 `{needs_confirm: true, warnings}`, "<Stage> has loose ends"); sending `confirm: true` locks anyway.
  - From stage 2 on, any rule error except "placed" blocks the lock (first 8 listed).
  - Stage 0: no checks.
  - Stage 1: error "there are no film lanes yet: lay out the shape, or add a lane"; warnings "N beat(s) have no lane: <ids>" (first 6) and up to 4 named-lane clashes.
  - Stage 2: warnings "N card(s) are neither placed nor staged: they stay in their draft lanes, and the build will refuse them" and "N contested card(s) are still open".
  - Stage 3: warning "N lane(s) have no order chosen: <labels>" (first 5) and every fixed in/out warning.
  - Stage 4: warnings "N amber or red join(s) still to choose (K red)" and "N join(s) have not been judged".
  - Stage 5: warning "N card(s) want a splice and have none".
  - Stage 6: error "nothing has been built yet: build the canvas first"; warning "the verify report has problems: ..." (first 3).
  - Locking stage 1 first renumbers the film lanes' labels `NN - Title` in film order; locking stage 4 first adds "SPLICE n: <play texts, each to 80 chars, joined by ' / '>" lines to each lane's notes for every splice the lane holds that its notes do not already mention.
  - Each lock records time, revision count (incremented each time the stage is locked again), the files written, the progress label and who locked it; it is one undoable event and clears that stage's stale mark.
- Files each lock writes into the work folder (in the structure-notes skill's formats, so the skill's own scripts can carry on from that step):
  - Stage 1: `sections.json` (with `question_cards`, the bin's questions from outside the question groups), `cards.jsonl`, `chunks/chunkNN.md` (old chunk files removed first), `structure_notes_plain.md` (the notes up to "## Inbox", wikilinks reduced to `^ref`), `STYLE.md` (copied from the pipeline's docs if present), `BRIEF.md`, `SEQUENCE.md`, and the empty subfolders `assign`, `targets`, `seq`, `splices`, `verify`.
  - Stage 2: `sections.json`, `assign/chunk01.json` (`[n, KEY, k|s]` rows for body cards), `assignment.json`, `targets/<KEY>.md` for every film lane, every staged lane and INTRO (when intros are on): "# Cards placed in KEY (N cards, source order)" then each card `[n] who ^ref ~Ns (old <first 2 chars of old section>)` with " **NAMED IN THE NOTES**" where named, its English (or "(no English) " plus 80 Chinese characters) and "ZH opens: <14 chars>… ZH ends: …<14 chars>".
  - Stage 3: `seq/<KEY>.json` for every film lane, empty ones included (`order`, `stage`, `notes`).
  - Stage 4: `seq/<KEY>.json` again and `BRIEF.md`/`SEQUENCE.md`.
  - Stage 5: `splices/storydeck.json` (removed when there are no splices).
  - Stage 0 and 6: nothing.
- Placement chunks (stage 1): body cards (not in a question group or drop group) grouped by old section, about 45,000 English characters per chunk; a section over 1.4 times that is split on its own. Each chunk file lists "## OLD SECTION <name>" headings and "[n] who ^ref ~Ns" lines with the English.
- **Reopen** (`POST /api/stages/<n>/reopen`): removes the lock; every later locked stage becomes stale (its lock stays and must be locked in again). Not locked: 409 "stage N is not locked". One undoable event, logged as "reopened stage N, <Stage>: <later stages> now stale".
- **The stage gate**: a change that would alter what a locked stage decided is refused (409, rule "stage-locked", "<Stage> is locked: reopen stage N to <what>"), for the editor and the agents alike, including dry runs:
  - Stage 1 owns: adding or removing a lane (except a staged shelf), reordering lanes, a lane's gates, named cards or kind, the montage slots.
  - Stage 2 owns: a card between lanes, onto or off a shelf held at the deal, taking a card out of its lane. Sweeping a never-dealt draft card into a bin or shelf is not counted.
  - Stage 3 owns: marking a lane sequenced.
  - Stage 4 owns: the order inside a lane, setting a card aside or bringing it back.
  - Stage 5 owns: the splices.
- An agent run of a locked stage (skeleton, deal, sequence, joins, splices) is refused "<Stage> is locked: reopen stage N to run it again". Tidy is never refused this way.
- `GET /api/stages`: the overview plus the lock check the current stage would get now.

## Stage 0: reading the canvas and writing notes
(source: storydeck/routes_notes.py, storydeck/notes.py)

- **Read markers** (`POST /api/read {lane, count | all, mode: set|max}`): how many cards of a draft lane are read. Only a draft lane: "only a draft lane is read". Unknown lane: 404. Needs `count` or `all`: "count or all is needed". `mode: max` never lowers the marker. The count is clamped to 0..lane size. Marking any card of a frosted lane read un-frosts it.
- Before the first marker change, lanes the notes already call read get a marker for all their cards (recorded as author "seed"), so rewriting the notes cannot forget them.
- After every read change, the notes' "Read so far" text (between `**Read so far:**` and `**Last tidied:**`) is rewritten: "through *A*, *B*; part of *C* (12 of 40). Not yet read: *D* → *G*." Three or more consecutive draft lanes are written as a run `*A* → *B*`; nothing read gives "nothing yet". The text is wrapped to 80 columns; everything outside that span is left byte for byte, including line endings. Notes without such a line are left alone (the answer says so). The answer carries the before/after text and a diff.
- Reading which lanes are unread from the notes: in the text after "Not yet read", each `*Lane label*` names a lane, and `*A* → *B*` (or `->`) names every lane from A to B in canvas order.
- **Stickies** (the editor's notes on the board):
  - `POST /api/note {text, n | between: [a, b] | neither}`: a note on one card, on the gap between two cards, or free. Empty text: "a note needs some words". Bad `between`: "between is two card numbers". Unknown card: 404.
  - `POST /api/note/<id>/edit {text}`: empty refused "a note needs some words (delete it instead)". Unknown id: 404.
  - `POST /api/note/<id>/delete`.
  - Note ids are `note1`, `note2`...; each carries the time it was written.
- **Stickies become Inbox lines** in the Structure Notes, automatically:
  - A new sticky is appended as the last entry of the Inbox, after a blank line. A card note: `<lane label> — <Speaker> [[<path>#^ref|^ref]] — <text>`; a between note: `<lane label> — <Who ^ref> → <Who ^ref> — <text>`; a free note: just the text. Speaker is the short surname.
  - A line that would read as a markdown heading or rule is escaped with a backslash so it cannot split the Inbox.
  - With no Inbox section, one is created at the end of the file after a `---` rule, with the format hint ("Raw notes go here. One line each is enough: ...").
  - Editing a sticky replaces its line in place; deleting (or undoing) it removes the line and the blank line before it. A line that has already been moved out of the Inbox (by the editor or by Tidy) is never re-added; a changed or removed sticky whose line is gone is reported "absent".
  - Which sticky wrote which line is kept in `inbox-ledger.json` in the work folder.
  - If the file had no final newline, the first added line gives it one, and removing every line takes it away again.
- **The spine** (beats), editable on the board. The first spine edit copies the notes' Shape into the board as its own spine (recorded as author "seed"); after that the board's spine is used instead of the notes' Shape.
  - `POST /api/spine/add {name, what?, act?, after?, new_act?}`: a beat named "New beat" by default; after a given beat, at the end of a given act, or at the end of a new act "Act N: <name>" (default name "new act"). Its id is `<act number>.<next minor>` (empty id if the act has no number).
  - `POST /api/spine/edit {id, name?, what?}`: "a beat needs a name"; "nothing to change".
  - `POST /api/spine/move {id, before? | act?}`: before another beat (taking its act) or to the end of an act. "a beat cannot go before itself".
  - `POST /api/spine/delete {id}`.
  - `POST /api/spine/name {id, n, remove?}`: name a tile in a beat (tag it); a ref is named by only one beat, so it is removed from any other beat. "this tile has no ^ref to name it by".
  - `POST /api/spine/act {act, name}`: rename an act for all its beats, keeping "Act N: ". "an act needs a name"; unknown act 404.
  - Unknown beat: 404 "no beat ...".
- Reading the Shape from the notes: `### ` headings are acts; lines `**1.1 Name** (*Old section*)` are beats; every `^ref` in a beat's text is collected; a ref inside a `*Claude: ...*` passage is Claude's interpretation and is not counted as named by the editor.

## Stage 0: Tidy (an agent cleans up the Inbox) and the notes edits it proposes
(source: storydeck/routes_notes.py, storydeck/agents.py, storydeck/routes_build.py)

- `POST /api/tidy`: starts the Tidy agent (202 `{run}`). Refused 409 "Tidy is already running" while one runs.
- The agent receives every Inbox line and the cards whose refs they mention, and is asked to give one `notes` edit per line (section shape, moves, lines, open or inbox, plus the markdown to fold in) and to raise every ambiguity (a quote or ref not found, a vague destination, two notes wanting one card, a contradiction, whether a run goes past a topic change) as a quest. An empty Inbox: the agent is told to say so.
- Each quest it raises immediately becomes a board quest (see Quests); a quest with the same title and cards already open is not raised twice.
- A newer Tidy run supersedes the older run's still-pending notes edits.
- `GET /api/quests`: the quests panel's view: every quest, Tidy's pending and taken notes edits (section, text, why, time), the last three Tidy remarks, and the latest Tidy run (state, errors, number of refused ops and the first six refusals), with counts of open and answered quests.
- `POST /api/tidy/edits/<id>/apply {confirm}`: without `confirm`, a preview: the section name, the block, and a unified diff (1 line of context, at most 80 lines). With `confirm`, writes it. If the file's length changed since the preview, the insertion is redone on the current text. The edit is appended as the last thing in the section: directly under a list when both are list items, else as a paragraph after a blank line; a missing section is created at the end of the file after `---`. Refusals: not a pending notes edit (409), unknown (404), no notes file (409 "there are no Structure Notes beside this canvas to write into").
- `POST /api/tidy/edits/<id>/decline`.

## Quests (questions put to the editor)
(source: storydeck/quests.py, storydeck/routes_build.py, storydeck/stages.py)

- A quest has a title, the cards it is about (refs), the consequence, 2 to 4 options (ids a, b, c, d), a status (open, answered, kept-open), the answer and its date.
- Who raises them: the Tidy agent, the Skeleton agent, the "ask" steering turn (any quest op is turned into a board quest), the skeleton layout (a ref two beats name), and the editor (`POST /api/quests {title, cards[], consequence, options[2..4], open_match?}`; "a quest needs a title/consequence"; "a quest offers 2-4 options (the editor can always keep it open)").
- The skeleton layout's quest for a ref two beats name: title "^ref is named by A and B", consequence "A card plays once. If it stays in A, B has to work without it; if it moves, A loses it.", options "Keep it in A", "Give it to B", "Neither: back to the pool".
- Answering is always preview, then answer:
  - `POST /api/quests/<id>/preview {option | text | keep_open}`: the exact diff the answer would write to the Structure Notes, the section it lands in, the added block and a token. Refusals: already answered (409); no option/text/keep-open ("an answer needs an option, or his own words, or keep-it-open"); unknown option; no notes file (409).
  - `POST /api/quests/<id>/answer {option | text | keep_open, token}`: requires the preview's token ("preview the answer first: an answer is written with the token of its preview"); if the notes changed so the write would differ, 409 `{stale: true}` "the notes changed since the preview: look at it again" and nothing is written. Writes the notes, then records the answer on the board (undoable on the board; the notes write itself is not undone).
  - `POST /api/quests/<id>/decline`: takes the quest off the board (undoable; the notes are untouched).
- Where an answer is written in the notes (each an insertion; everything else byte-identical; refs written as full Obsidian wikilinks `[[path#^ref|^ref]]`; wrapped to 80 columns, never breaking inside a link):
  - Answered, landing in the Shape: a line `(decided <date>: <decision>)` under the beat.
  - Answered, landing in Moves: a `- [ ] <decision> (decided <date>)` checkbox in that section's `**<section>**` group (group created at the end of Moves if missing).
  - Answered, landing in Lines: a bullet in "Lines to build on".
  - Where it lands: the option's own landing, else the one Shape beat that names the quest's cards, else nowhere but the record.
  - Kept open: a bullet `**<title>.** <links>. <consequence> (Kept open <date>.)` in "Open", or, if the quest has `open_match`, "(Kept open <date>.)" appended to the matching Open bullet.
  - Answered with `open_match`: "(Decided <date>: see Raw notes.)" appended to the matching Open bullet.
  - Every answer: a record under "Raw notes, as written" in a block `**Answers to questions, <date>**` (created when that day has none): `- **<title>** (<links>): <answer words>. Landed in <place>.`
  - Missing sections (Open, Moves, Lines to build on, Raw notes, as written) are created at the end of the file after `---`. A Shape beat that does not exist: "the Shape has no beat N".
- The decision text is the editor's own words, else the option's decision, else its label.

## The agents
(source: storydeck/agents.py, storydeck/ops.py, storydeck/stream.py)

- Every agent turn is one Claude call. The model gets no tools and no files: the board is put in the prompt. It must answer one JSON object `{"ops": [...]}` (a code fence, prose around it, a bare list or a single op are tolerated). An answer with no JSON is an error for that call.
- Requires Claude through the Timeline Cards Claude door (`cards.claude.run_claude`): a host's runner when one exists, else the Claude Code command-line tool on this machine signed in. The model is chosen by `--model` (default "fable").
- Every prompt carries a preamble: the role ("You are the editor's assistant on a documentary ... in Story Deck"), standing rules (never pre-cut to runtime; a ref is a pointer, not a boundary; a card plays once; specific beats blanket; ask, don't guess; relevance over speaker, one conversation, no voiceover; interviewer questions never play unless named; staging is light), the house style (`docs/STYLE.md` of the pipeline), the ops reference, the Structure Notes (wikilinks reduced to `^ref`) and the brief (`BRIEF.md` + `SEQUENCE.md` from the work folder).
- Every turn also carries the constraints the agent must not touch: the editor's pins, the cards he placed by hand (his live, not-undone moves), the named cards per lane (minus unlocked ones), frosted lanes, unlocked refs, the lanes whose order was taken, and the last 12 declined proposals; and a one-line-per-lane digest of the board (key, label, kind, act, counts and playing time, named refs, gates, FROSTED, the first 200 characters of the lane's notes).
- Card lines shown to the agent: `[n] Speaker ^ref ~Ns in LANE/zone  INTERVIEWER QUESTION`, then up to 700 English characters (2,000 in a whole-canvas turn), and the Chinese reduced to its first and last 12 characters.
- Two kinds of turn:
  - **Serial turns** (tidy, ask, and the whole-canvas deal and sequence) share one Claude conversation per board and model, kept in a session file in the work folder (`storydeck<model suffix>.md`). The first turn carries the preamble; later turns are short. If the notes changed since the conversation last read them, the next turn carries the new notes ("THE STRUCTURE NOTES HAVE CHANGED..."). If the provider lost the conversation (or reports it "already in use") it is re-opened once and the page is told "The Claude session was lost (new machine or a cleared store); re-reading the notes."; losing it twice: "the Claude session was lost twice running; try again". One serial turn runs at a time.
  - **Fan-out turns** (deal chunks, sequence lane groups, joins per lane, splice batches) run up to 6 at a time, each a stand-alone call with the same preamble.
- Timeouts: 900 s per call; 2,400 s for a whole-canvas turn.
- **Whole canvas or chunks**: deal and sequence use one whole-canvas turn when the estimated size (preamble, every card, lane digest, placement map) is at most the token budget (default 600,000; a board setting `token_budget` overrides; tokens estimated as one per Chinese character plus one per three other characters). Over the budget they fall back to chunks and the page is told "The canvas is about Nk tokens, over the Mk a single turn may carry, so <the deal / the sequencing> runs in chunks instead (each sees its own cards and the notes, not the whole film)." The run request may force either path (`whole: true/false`). In a conversation that already received every card of the same canvas, later whole-canvas turns send only where the cards are now (`storydeck<model suffix>.corpus.json` records this).
- Which ops each agent may answer with (others are refused "op X is not part of the Y stage", rule "stage"): tidy: quest, notes, say; skeleton: lane, quest, say; deal: place, stage, say; sequence: order, stage, say; joins: join, say; splices: splice, say; ask: all kinds.
- **Starting a run**: `POST /api/agents/run {stage, lanes?, cards?, chunk?, whole?}` with stage tidy, skeleton, deal, sequence, joins or splices (else 400 "stage is one of ..."). Answers 202 with the run (id, stage, state, mode whole/chunks, token estimate, calls). Refused when that stage is locked.
- **Skeleton agent** (stage 1): first adopts the notes' Shape as the board's spine if the board has none; then asks for one `lane` op per film section in film order: label "NN - Title", act, what it is for, its beat id, fixed in/out only where the editor's own words fix them, named cards; `key` to change an existing lane; unread draft sections stay frosted; ambiguities as quests. Up to 60 named cards are shown in full.
- **Deal agent** (stage 2): deals every card still in an unfrosted draft lane and not pinned (optionally only the given lanes) into the film lanes and staged shelves that are not frosted. Refused "there are no film lanes to deal into yet (stage 1, the skeleton, makes them)". One `place` op per card with a confidence 0-1 (low when two lanes want it; both places given when a card is genuinely wanted twice), a `stage` op with a lane for clearly weak cards, interviewer questions to the bin. Chunks are 40 cards each (overridable by `chunk`).
- **Sequence agent** (stage 3): orders each unfrosted film lane with two cards or more (INTRO included), up to three competing orders per lane, honouring fixed ways in and out and pins. In chunk mode adjacent lanes are paired when together they hold at most 60 cards, and each group is told the card the lane before ends on and the card the lane after opens on.
- **Joins agent** (stage 4): one call per unfrosted film lane (INTRO excluded) judging every adjacent pair in the lane plus the hand-off into the next lane's first card: green (the next card answers, continues or objects), amber (works with a splice or small change), red (topic jump), with 1-3 bridge options for amber and red.
- **Splices agent** (stage 5): the cards that want a splice (from join splice options, pending or taken, and "SPLICE n: ..." lines in lane notes, plus any `cards` named in the request, marked "requested"), skipping cards that already have a splice unless named, skipping frosted lanes; batches of 5; asks for exact verbatim spans on whole sentences or clauses.
- **Ask** (steering): `POST /api/agents/ask {text, n?, lane?, ns?, action?}` (202 `{run}`). A serial turn in the board's conversation with the editor's words, the card pointed at plus two cards either side, or the whole lane, or the given cards. "ask needs some text". Context actions with fixed wording:
  - `why_here`: explain why card N belongs (or not) where it is; a `say`, plus a proposal only if it should move.
  - `better_join`: look for a better join into and out of card N: join judgements with bridges, order/stage only if clearly better.
  - `who_else`: who else says something like card N; a `say` naming them, plus a proposal if a better place exists.
  - `openings`: three competing orders for the lane, each starting on a different card, labelled.
  - `dramatic`: the order that withholds and pays off; one order or up to three competing ones.
  - Unknown action: "no action X (one of ...)".
- `POST /api/agents/cancel {run}`: marks the run cancelled; calls not yet started are skipped, calls already running finish. Unknown run: "no run ...".
- `GET /api/agents/status`: every run of this session, pending proposal count, model, conversation id and turn count. Runs are kept in memory only (lost on restart).
- A run's state: running, done, error (every call failed) or cancelled. A call's state: pending, running, done, error, cancelled, with its proposals, refusals and seconds.
- **Live stream** `GET /api/agents/events`: server-sent events, reconnect after 3 s, keepalive every 15 s; the last 500 events are remembered and replayed to a page that reconnects with `Last-Event-ID`; a slow page loses its oldest events (queue of 2,000) rather than holding up the agents. Event types: `proposal_added`, `proposal_updated`, `agent_started`, `agent_done` (proposals, number refused, seconds), `agent_error`, `say`, `op_refused` (the op, rule and message), `run_done`.

## What an agent can propose, and what taking or declining it does
(source: storydeck/ops.py, storydeck/routes_play.py)

- Each op in an answer is checked against the live board and the rules; a valid one becomes a pending proposal laid over the board, an invalid one is refused and shown as an `op_refused` event. Ops are checked one at a time so the editor's moves can interleave with a long answer. Errors standing before the answer never refuse an op; only an error the op would ADD does (it is dry-run on a scratch copy).
- Kinds of proposal:
  - **place** `{n, lane, conf}`: deal a card into a lane (the playing order of a film lane, the held shelf of a staged lane). Refused into a draft lane ("... is a draft lane (Claude's topic group): deal into the film lanes", rule "lane-kind") or from or into a frosted lane. Confidence clamped to 0-1, default 0.5.
  - **stage** `{n, why, lane?}`: set a card aside to its own lane's shelf, or with `lane` deal it straight to that lane's held shelf. Without a lane the card must be in a film lane's playing order ("card N is not in a film lane's playing order: name the lane to shelve it in").
  - **order** `{lane, order[], stage[], label, why, alt_of}`: a lane's full playing order, setting `stage` cards aside. Must list every card of the playing order exactly once ("never-drop": "order + stage must hold every card of lane K's playing order; missing ..."; duplicates: "listed twice: a card plays once"); cards must come from that lane's order or staged shelf, not another lane or its held shelf; the fixed way in must be first and the fixed way out last ("<lane>'s way in is fixed: ^ref must be first"); an order that would move a pinned card is refused ("this order would move pinned card(s) ..."). Several orders for one lane in one answer, or ones naming `alt_of`, are grouped as competing alternatives.
  - **join** `{a, b, grade, why, options[]}`: a judgement of a pair; both cards must be in a lane; up to 4 options of kind splice (play exact text of card n, default b; each text must be found exactly once), swap (swap b with card n of the same lane; n = a flips the pair), pull (bring card n in between from a shelf or the pool) or note (advice). A swap or pull that names no card, swaps b with itself, or pulls a card already in the join is kept as a note with an explanation.
  - **splice** `{n, play[], why}`: the exact spans of a card that play; card must be in a lane, not frosted.
  - **quest** `{title, cards, consequence, options[2..4]}`: becomes a board quest at once (the proposal is marked taken and points at it).
  - **say** `{text}`: a remark; delivered at once (shown as a message), nothing to take ("a say is only a remark; there is nothing to take").
  - **notes** `{section, text, why}`: an edit to the Structure Notes (Tidy only); sections shape, moves, lines, open, inbox.
  - **lane** `{label, act, what, beat, gate_in, gate_out, named[], after, key}`: a film lane of the skeleton, or (with `key`) a change to an existing open film lane's given fields. A new lane needs a label; a film lane of the same label already existing is refused; an unknown beat or `after` lane is refused.
- Cards may be named by number, "[12]", "12" or ^ref; lanes by key or label (case-insensitive).
- Competing proposals: a new proposal for the same slot (the same card for place/stage, the same lane for order, the same card for splice, the same pair for join, the same lane for lane) from a different call supersedes the older pending one.
- Statuses: pending, taken, declined, superseded.
- `POST /api/proposals/<id>/take {option?}`: re-checks the proposal against the board as it is now (a refused take leaves it pending) and applies it as one undoable event authored by the agent. For a join, `option` picks a bridge (no option = accept the grade alone, no board change). A taken proposal supersedes its pending rivals (other orders of the same lane group, other answers for the same card). What a take does:
  - place: the card moves to the end of the lane's playing order (film) or its held shelf (staged).
  - stage: to its lane's shelf, or to the named lane's held shelf.
  - order: the lane's cards are moved into the proposed positions and the stage cards set aside; pinned cards are not moved.
  - splice: sets the card's splice.
  - lane: adds a film lane (next free key `L01`...) after the given lane or after the last film lane, brings its named cards into its playing order and points its beat at it; or edits an existing lane's changed fields.
  - join bridge splice: sets that card's splice; swap: swaps the two cards in the lane's order (refused if either is pinned or not in the lane's playing order); pull: moves the card to just after card a (refused if it already plays in another film lane: "a pull comes from a shelf or the pool").
  - notes: written into the Structure Notes (appended to that section).
- `POST /api/proposals/<id>/decline`: marks it declined; nothing else changes. Declined proposals are listed to later agent turns as constraints.
- A proposal that is not pending cannot be taken or declined ("proposal X is <status>, not pending").
- `GET /api/proposals?status=&kind=&lane=`: filtered list.
- Proposals are stored on the board, so they survive a restart.

## Stage 1: the skeleton (film lanes) by hand and by layout
(source: storydeck/stages.py, storydeck/routes_stages.py)

- `POST /api/skeleton/layout`: lays out the spine as film lanes in one undo step (adopting the notes' Shape first if the board has no spine). Refused "the shape has no beats yet: sketch them in stage 0 (or write the notes' shape)". Idempotent: only beats without a lane are laid out. For each such beat:
  - a film lane labelled `NN - <beat name>` under the beat's act, placed after the lane of the nearest earlier beat that has one (else before the first film lane);
  - its fixed way in/out from the beat's own words: "opens/starts/begins on/with ... ^ref" and "ends/lands/closes on/with ... ^ref" within 40 characters, and only for a ref the editor wrote;
  - its named cards moved into its playing order and pinned there;
  - a ref already named by an existing lane, or by another beat with a stronger claim (the beat whose words fix it, else the first to name it), is not taken; it becomes a quest and the beat records it as `claimed_elsewhere`;
  - montage slots from the beat's words: bold text containing "montage", else up to two words before "montage" (inline code ignored, leading a/an/the dropped, capitalised).
  - Unread (frosted) draft lanes with cards are carried forward as frosted film lanes `NN - <label>` under act "Not read yet", cards in source order, and the draft lane removed ("<label> is unread: carried forward frosted, in draft order").
  - An `INTRO` film lane (act "Introductions") is added when intros are on and none exists; a question bin (key `Q`, label "Staged -- Interviewer questions and chatter" by default) when any card is a question and there is no bin.
  - Notes are returned for named refs not on the canvas.
- `POST /api/lane {action, ...}` (each one undoable; the editor's precheck applies):
  - `add {label, kind film|staged, act?, after?}`: new key `L01`...; film lanes go after `after` or after the last film lane, staged at the end. "a lane needs a name"; "a lane is a film lane or a staged bin"; "no lane X to follow".
  - `edit {lane, set: {label, act, notes, gate_in, gate_out, named}}`: gates and named cards accept numbers or refs. Other fields: "a lane's X cannot be edited here"; empty: "nothing to change"; empty label: "a lane needs a name".
  - `act {from, to}`: renames an act on every film lane and beat in it. "no lane is in the act X".
  - `thaw {lane}`: "I have read this lane": un-frosts it and stages every interviewer question in its playing order that the notes do not name. Not frosted: 409.
  - `delete {lane}`: only an empty lane ("<label> still holds N cards: move them first (or merge it into another lane)"); beats pointing at it are unlinked.
  - `move {lane, index | dir}`: only film lanes other than INTRO ("only film lanes are reordered"); by one step left/right, or to an index. "that lane is already at the end".
  - `merge {lane, into}`: only film lanes; every card moves to the end of the target (same zones), pins follow, montage slots and beats re-pointed, named refs combined, the source lane removed. "merge into which lane?".
  - Unknown lane: 404; unknown action: "no lane action X".
- `POST /api/montage {action add|edit|delete, ...}`: montage slots (named placeholders for montages, with a lane, an "after" card and seconds): add `{lane, label, after?, seconds?}` ("a montage slot needs a name"), edit `{id, label?, lane?, after?, seconds?}`, delete `{id}` ("no montage slot ..."). Ids `m1`, `m2`...
- `POST /api/target {seconds}`: the runtime target (information only). Empty or 0 clears it. Below 0 or above 24 hours: "a target runtime of N seconds is not sensible".

## Stage 2: the deal
(source: storydeck/stages.py, storydeck/routes_stages.py)

- **Contested cards**: a card with pending placements into two or more lanes ("two lanes want it"), or whose best placement confidence is below the threshold (default 0.6, board setting `contest_conf`) ("not sure"). `GET /api/deal/contest` lists them with every candidate lane, confidence and proposal, plus the ids of the confident placements.
- `POST /api/deal/prime`: puts every named card into its lane's playing order and pins it there (open film lanes; unlocked cards are left where they are). Answers how many were pinned.
- `POST /api/deal/take {lane?}`: takes every confident pending placement (one candidate lane, confidence at or above the threshold), optionally only those into one lane, as ONE event. Each is re-checked; one the rules now forbid stays pending and is reported; two placements of the same card in the batch: the second refused; if the combined change cannot be laid down, none of it is.
- `POST /api/deal/settle {n, lane | null, stage?}`: settles a contested card in one step: `lane: null` declines every placement of it (it stays where it is); `stage: true` puts it on that lane's held shelf ("staging a card needs the lane whose shelf it goes on"); a lane an agent proposed takes that proposal; any other lane is the editor's own move. The card's other pending placements become superseded.
- `POST /api/deal/sweep`: moves every card still in a draft lane (not dropped) to the end of the first bin lane, one undo step (the way out when the Deal was locked with cards left over and the build refuses them). "there is no bin lane to sweep into".

## Stages 3 to 5: sequence, joins, splices by hand
(source: storydeck/stages.py, storydeck/routes_stages.py)

- `POST /api/sequence/keep {lane, on?}`: "this order is fine": marks (or with `on: false` unmarks) a lane as sequenced without taking an order proposal. A lane also counts as sequenced once an order proposal for it is taken.
- **Join status**: per pair, the latest pending or taken join judgement. Settled = graded green, or taken (a bridge chosen or the grade accepted); open = amber or red still pending.
- `POST /api/joins/accept {grade?}`: accepts every pending join of a grade (green by default) as it is, with no bridge and no board change. Unknown grade refused.
- `POST /api/splice {n, play[], why?}`: the editor's own splice. Each text must be found exactly once in the English (409 "... is not found exactly once in the card: a splice is an exact substring") and start and end on whole words (409 "a splice starts and ends on whole words"). `play: []` clears it. Reason defaults to "trimmed by Alex". Pending splice proposals for that card become superseded.
- Cards that want a splice: from join splice options (pending or taken), "SPLICE n: ..." lines in lane notes, and pending splice proposals.

## Stage 6: build the new canvas
(source: storydeck/build.py, storydeck/routes_build.py, storydeck/workfolder.py)

- `GET /api/build/dry-run`: everything short of writing the new canvas:
  - the build check (rules with "every card placed" and frosted-lane questions as errors); with errors it stops and reports them (`ok: false`, `refused: true`) and writes nothing;
  - writes the skill's files into the work folder (`sections.json` with the output path and `question_cards`, `cards.jsonl`, `assignment.json`, `seq/<KEY>.json` for every film section, `splices/storydeck.json`, `BRIEF.md`, `SEQUENCE.md`);
  - makes `plan.json`: per film section, a "Staged -- <label>" group (its staged and held cards) then the section's playing order; staged-only lanes; the question bin (unassigned question-group cards plus the bin's own questions); dropped cards. INTRO cards go after the speaker's first consecutive block in the film, or are staged (into the first staged-only lane, else the first section) when the speaker has no line ("no line in the film, intro staged: <who>"). Refuses on a section whose seq file is missing, has a duplicate, a card both ordered and staged, or does not match its placed cards, or a plan that does not cover every card exactly once;
  - makes a scratch copy of the source canvas, `src_with_flags.canvas`, applying splices as `==highlights==` (a card already highlighted is left alone; a play text not found exactly once is skipped and logged; a highlight never crosses a line break) and adding one yellow (#ffd500) flag card per film section, "⚑ **TRANSITION / FLAG**", the section label in capitals, the lane's notes (card numbers rewritten as their ^refs, lane keys rewritten as "section NN") and "_Re-ordered <date> from the structure notes; old card numbers shown as their ^refs._", in a group "zz flags (scaffold)" to the right of everything; writes `plan_final.json` with each section's flag card first. Refuses when the canvas numbering no longer matches ("card numbering no longer matches the canvas at [N]: re-read the canvas into the board") or the flags moved the numbering;
  - runs the pipeline's `resequence_canvas --dry-run` into `out_dryrun.canvas`;
  - answers: where the build would write, rows per group (label, cards, seconds, minutes, staged, flag), playing minutes, staged cards, total cards, dropped count, runtime target, where each section's cards came from (old sections with counts), highlights applied and skipped, flags, lane keys left in flag text, the notes-named questions that will play, the log and the tool's output. A failing tool: "resequence-canvas --dry-run failed: <last 400 chars>".
- `POST /api/build`: refused 409 `{refused: true, findings}` "build refused: N rule error(s): ..." while the build check has errors; any failed step 409 with its message. Otherwise runs the dry run, then writes the new canvas next to the source canvas at the first free name of `<Episode> - Ordered.canvas`, `<Episode> - Ordered V2.canvas`, ... (never overwrites; re-checked at the last moment; the board's own output path is used if set and free), then verifies:
  - runs the pipeline's `story_flow_extract` on the new canvas and on the source against the pool (with the notes-named questions allowed), into `verify/` and `verify/source/`;
  - problems: cards playing twice, interviewer questions in the cut, unused pool paragraphs differing between built and source, flag cards still carrying lane keys;
  - writes `build_result.json` (path, ok, dry run, verify report, folder, tool output) in the work folder; this is what stage 6's progress and lock check read.
- The source canvas, the pool and the notes are never written by the build. The only file written outside the work folder is the new canvas.
- **Status block in the notes** (after a build):
  - `GET /api/build/status-preview`: the diff of the block and a token. "nothing has been built yet: build first" (409) when there is no build.
  - `POST /api/build/status {token}`: writes it (token required: "preview the status block first..."; 409 `{stale}` when the notes moved since the preview). The block sits after the title line between `<!-- storydeck:status -->` and `<!-- /storydeck:status -->`, replacing an earlier one: "> **Story Deck build, <date>.** New canvas: [[<file>]]. N sections, M cards playing (about K min), S staged.", "> Fixed ins and outs and named cards: all honoured / N not honoured (...)", the question cards named and playing, "> Verified: no duplicates, no questions in the cut but the named ones, the unused pool unchanged (N)." or the problems, "> Beat to new section: 1.1 → 01, ...", "> The Moves below still describe the old canvas and are unchanged."

## Files Story Deck reads and writes
(source: storydeck/workfolder.py, storydeck/model.py, storydeck/notes.py, storydeck/agents.py, storydeck/brief.py)

- Reads: the themed canvas (cards, groups, colours; never written); `interviewee_colors.json` beside it; the Structure Notes (re-read on every board request, since the editor edits it in Obsidian while Story Deck runs); the pipeline's `docs/STYLE.md`.
- Writes in the work folder: `board.json`, `events.jsonl`, `inbox-ledger.json`, the Claude session and corpus records, the skill's files (`sections.json`, `cards.jsonl`, `assignment.json`, `seq/`, `splices/storydeck.json`, `assign/`, `targets/`, `chunks/`, `verify/`), `structure_notes_plain.md`, `STYLE.md`, `BRIEF.md`, `SEQUENCE.md`, `plan.json`, `plan_final.json`, `src_with_flags.canvas`, `out_dryrun.canvas`, `build_result.json`.
- Writes in the Structure Notes (small insertions, each leaving the rest of the file byte-identical): the "Read so far" text, Inbox lines from stickies, Tidy's notes edits, quest answers, the build status block.
- Writes beside the canvas: the new `<Episode> - Ordered[ Vn].canvas`.
- Mapping of the board to the skill's files: a film lane's playing order and stage zone are its kept ("k") cards, its held cards are staged ("s"); a staged lane's cards are all "s"; INTRO cards are "k" under key INTRO; draft and bin lanes are not in the skill's files. A notes-named question in a film lane's order is forced into the assignment ("force") and passed to the verifier as allowed.
- `BRIEF.md`: "# <Episode> — the re-order brief", a paragraph (runtime "of about N minutes" when a target is set, the canvas file name, the date, the instruction to read `STYLE.md` and `structure_notes_plain.md`), the `cards.jsonl` field legend, "## Target sections" by act (each `- `KEY` — label — <beat what>; Named in the notes for this section: Speaker ^ref "first 90 characters..."; FIXED way in/out: ...; Notes 1.1, 1.2.`), staged-only targets, the INTRO rule (at most one self-introduction per speaker, after their first substantive line), the question and drop groups, and "## Placing a card" (five fixed rules: relevance decides; named cards are pointers whose neighbours may travel; specific beats blanket; staging is light; interviewer questions never play except a named one), plus any `brief_overrides` from the board settings numbered from 6.
- `SEQUENCE.md`: "# The row, and what each section must hand to the next", explanation, a table key | section | in | out: in is "FIXED: <quote>", "THE FILM OPENS HERE" for the first, else "yours"; out is "FIXED: <quote>", "THE FILM ENDS HERE. Order the cards so the ending builds, and put your best choice last" for the last, else "hand to KEY, whose first card is <quote>, so END on something it replies to" or "hand to KEY: what this section must hand over so the join works as a reply".
- Requires the structure-notes skill's file formats and a canvas readable by the pipeline's canvas loader; the build and verify run the pipeline's own `resequence_canvas` and `story_flow_extract` modules as separate processes.

