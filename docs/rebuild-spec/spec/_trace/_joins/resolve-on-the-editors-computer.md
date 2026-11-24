# Joins aimed at resolve-on-the-editors-computer

## Checked

- J1 | fine
- J2 | fine
- J3 | fine
- J4 | fine
- J5 | F1
- J6 | fine
- J7 | F2
- J8 | F3
- J9 | fine
- J10 | F4
- J11 | F5
- J12 | fine
- J13 | fine
- J14 | F6
- J15 | fine
- J16 | fine
- J17 | fine
- J18 | F7, F8
- J19 | F9
- J20 | fine
- J21 | fine
- J22 | F10
- J23 | F7
- J24 | F2
- J25 | fine

## Findings

### F1: The rule for never connecting during Resolve's start-up is described in full in both pieces
- Kind: said twice
- From: cards-to-resolve-and-exports / Timeline Cards never connects to Resolve while Resolve is still starting
- Here: Connecting to Resolve's scripting: launch, stalls and death / The product never harms a Resolve session
- From says: "Timeline Cards connects only when it shows the script server listening AND Resolve itself connected to it. When Resolve is closed, or the server is up but Resolve has not registered yet, Timeline Cards waits"
- Here says: "The product connects to Resolve only when Resolve's scripting helper is listening AND Resolve itself has registered with it. [...] With no helper (Resolve closed) it stays quiet; with a helper but no Resolve registered yet, it holds off every request until Resolve has registered."
- Settled by: RSV-001 (a given, weaker): "Nothing on the computer, helpers included, connects until the script server is listening and Resolve itself is connected to it; only an unreadable check may connect anyway."
- Fix: cards-to-resolve-and-exports keeps only its own waiting message ("Resolve is starting: waiting before connecting") and points here for the facts and the rule, since the app is the one part that talks to Resolve.

### F2: The two counts of clips outside the tree and clips only on this computer are worded differently on every surface, though this piece promises one wording
- Kind: differs
- From: dashboard-1 / Each computer's issues are listed worst first, each explained (also sync-2 / Each computer says in one sentence why it is not syncing, and since when)
- Here: Connecting to Resolve's scripting: launch, stalls and death / The app's menu says whether it can see Resolve and what is wrong in the open project
- From says: "\"N clips outside the tree in <project>\" [...] [, N of them under the wrong drive letter] [...] \"N project(s) with clips only here\"" and (sync-2) "\"N clip(s) in the open project are outside the tree and will never upload\""
- Here says: "\"N clips outside the tree\", \"N missing\", \"N on the wrong drive\", \"N other projects with clips only here\" [...] The counts use the same words, and mean the same, in the menu, the settings window and on the dashboard."
- Settled by: ALL-044 (a situation, weaker): "one event is worded the same everywhere it appears."
- Fix: this piece fixes one wording for each count (its own settings window, which says "N clips are stored outside your synced folder", included) and dashboard-1 and sync-2 use exactly those words.

### F3: The site setting for the folders every computer gets has two names
- Kind: differs
- From: dashboard-2 / Every setting of the site
- Here: Colour look-up tables (LUTs) / Every editor's computer receives the shared LUT library and stills gallery without ticking anything
- From says: "Setting: Shared libraries. Does: the folders every computer gets whatever it has ticked, for example colour look-up tables. Default: the product's standard shared libraries."
- Here says: "Setting: Shared asset libraries. Does: which folders under Assets reach every editor's computer without being ticked. Default: the LUT library and the Resolve gallery."
- Settled by: OWNER_REQUIREMENTS.md section 5: "Every page, part and setting therefore has a plain name and a few search words in this specification."
- Fix: dashboard-2 uses the name "Shared asset libraries" with this piece's default (the LUT library and the Resolve gallery) and the "under Assets" limit, or both pieces agree on one name.

### F4: The warning that the drive letter is wrong names the first offline clip here, but its exact sentence elsewhere names none
- Kind: contradiction
- From: editor-app / Windows warns when the drive letter does not lead to the synced folder, and repairs it in one click
- Here: Missing clips, relinking and refreshing / The product watches the open timeline and sorts every clip by where its file is
- From says: "\"Resolve is looking for your media on P: but P: is not pointing at your synced folder, so clips will show offline. Your uploads and downloads are still running.\""
- Here says: "One warning per breakage, naming the first such clip."
- Settled by: the owner must say: does the warning that the studio's drive letter is wrong name the first clip that is offline because of it?
- Fix: either editor-app's sentence gains the clip's name, or this piece drops "naming the first such clip".

### F5: The editor is told never to restart the app for Resolve, yet this piece's advice tells them to
- Kind: contradiction
- From: editor-app / The editor can restart the app
- Here: Connecting to Resolve's scripting: launch, stalls and death / What the editor is told when Resolve cannot be reached
- From says: "The app's link to Resolve is renewed on its own whenever Resolve quits and is started again; the editor never has to restart the app for it"
- Here says: "Quit and reopen Resolve. If that does not help, quit the CC Sync app, quit Resolve, start the CC Sync app, then start Resolve." and "If this is Studio, quit and reopen Resolve; if that does not help, also restart the CC Sync app."
- Settled by: RSV-004 (a given, weaker): "recovery advice says: close the app, close Resolve, start the app, start Resolve."
- Fix: editor-app limits its sentence to the ordinary case (Resolve quitting and starting again) and points here for the recovery advice that may include restarting the app.

### F6: Resolve reading a grade file kept beside its original is relied on but never stated here
- Kind: missing
- From: footage-sorter-and-camera-cards-2 / Where each file of a sorted clip goes
- Here: nowhere
- From says: "a grade file beside its original, stay beside their clip (Resolve reads the grade there)"
- Here says: nothing
- Settled by: the owner must say: when camera files are filed into the tree, must a grade file stay beside its original so that Resolve picks the grade up on every computer?
- Fix: this piece adds that fact about Resolve (which grade files it reads beside an original) under Missing clips, relinking and refreshing, or the Sorter drops the claim and its pointer.

### F7: Relinking Resolve after the studio moves a file or a project folder is pointed at here but not described here
- Kind: missing
- From: proxies-and-file-moves / Resolve's clips follow a moved file now or when the project next opens (also sync-2 / When an admin renames or moves a project on the server, every editor's copy follows by itself)
- Here: Missing clips, relinking and refreshing / The product watches the open timeline and sorts every clip by where its file is
- From says: "Every Resolve project that uses a moved file is relinked when it next opens, and the editor is told." and (sync-2) "Relinking Resolve continues in Resolve on the editor's computer: Missing clips, relinking and refreshing."
- Here says: "If this computer itself moved that file when the studio moved it, the editor is offered to point the clip at its new place."
- Settled by: PRX-075 (a situation, weaker): "Every Resolve project using a moved file is relinked when it next opens, the editor is told, and an offline moved clip gets a one-click relink."
- Fix: this piece adds the automatic relink after a move (at once or when the project next opens, the editor told, recorded for undo) beside its one-click offer, or says plainly that proxies-and-file-moves holds it and stops being the pointed-at place.

### F8: A relink after a move retries every 5 minutes, but changes made unasked are limited to once per 15 minutes and 8 a day
- Kind: contradiction
- From: proxies-and-file-moves / Resolve's clips follow a moved file now or when the project next opens
- Here: Missing clips, relinking and refreshing / Changes the product makes in Resolve unasked are limited and retried by themselves
- From says: "the relink waits, and is tried again when the open project changes and at most every 5 minutes, for up to 30 days, until it succeeds."
- Here says: "Changes made without anyone pressing a button (repointing a clip to the shared spelling, attaching proxies) run for a given project and kind at most once every 15 minutes, and at most 8 times a day per project across all kinds"
- Settled by: the owner must say: does a relink that follows a file the studio moved count against the limit on changes the product makes in a Resolve project unasked?
- Fix: this piece names move relinks either inside or outside its list of changes made unasked, and proxies-and-file-moves states the same retry timing.

### F9: Candidates for an offline clip are ranked in a different order, against the owner's ruling
- Kind: contradiction
- From: proxies-and-file-moves / A missing clip whose file is already in the tree is relinked, never copied
- Here: Missing clips, relinking and refreshing / An editor relinks offline clips to files found in the tree
- From says: "the one whose folder path matches the clip's old path most closely wins; only when that leaves a tie does the largest file (the original) beat a smaller one (a proxy)"
- Here says: "ranked by the longest matching end of the path, then by the folder most other clips were found in, then by the larger file"
- Settled by: PRX-090 (ruling): "Among same-named candidates the closest matching folder path wins; only when that leaves a tie does the largest file, the original, beat a proxy; identical backups are no conflict."
- Fix: this piece puts the larger file straight after the path match (any "folder most other clips were found in" rule only after size) and says identical backups are no conflict; the two pieces then describe it once, with the other pointing.

### F10: Asking for originals from Resolve's Scripts menu is described in full in both pieces, and only this one carries the owner's answer on dropped requests
- Kind: said twice
- From: sync-1 / An editor asks for originals from inside Resolve
- Here: Grading from the server's originals / An editor asks for originals from inside Resolve
- From says: "If the server cannot be reached the request is kept and sent again, and no part of it is sent twice."
- Here says: "A request not answered within 1 hour, or one that cannot be read, is dropped and the editor is told so."
- Settled by: decisions page 15, question 15.5, answered 2026-11-24 ("accept all the recommendations"): "A: the editor gets a notification that the request was dropped, and why."
- Fix: one piece holds the menu entries, the console answers and the notification (with the dropped-request notice), and the other keeps only a pointer; sync-1's pointer to "Bins, clip sorting and imports" should name "Grading from the server's originals" instead.
