# Joins aimed at proxies-and-file-moves

## Checked

- J1 | fine
- J2 | fine
- J3 | fine
- J4 | F1
- J5 | F2
- J6 | F3
- J7 | F4
- J8 | fine
- J9 | fine
- J10 | F5, F6
- J11 | F7
- J12 | fine
- J13 | F8
- J14 | F9, F10
- J15 | fine
- J16 | fine
- J17 | F11
- J18 | fine
- J19 | F12, F13
- J20 | fine
- J21 | F14, F15
- J22 | fine

## Findings

### F1: renaming a b-roll collection is said to be a move every computer follows, but moves here exist only inside projects
- Kind: missing
- From: broll / An admin sets how each collection is described and transcribed
- Here: An admin moves a file or folder on the server and every computer follows
- From says: "Changing it later renames the collection's folder in the archive in one move, never copying it again, and every computer and Resolve follow the move (see Proxies and file moves: Moves that reach every computer)."
- Here says: "An admin names something inside a project and where it goes" and refuses "an unknown or inactive project at either end"; ways in are only "from the project's own page, and from the Footage Sorter"
- Settled by: BRO-017 (ruling): "a later rename moves, never recopies"; whether editors' copies and Resolve follow it is not said by any ruling, so the owner must say: when an admin renames a b-roll collection, do the archive clips already on editors' computers move with it and does Resolve follow, as for a project move?
- Fix: proxies-and-file-moves should say that a collection rename in the b-roll archive is a move that reaches every computer holding its clips (and which computers those are), or broll should drop the claim that every computer follows.

### F2: a raw camera file in Timeline Cards waits for a proxy that is never made when the help for the editing program is off
- Kind: missing
- From: cards-footage-in / Every take is lined up by sound to within a frame
- Here: Raw camera clips get their proxies from Blackmagic Proxy Generator
- From says: "A raw file with no proxy yet waits for one to be made (see Proxies and file moves: Raw camera formats and Blackmagic Proxy Generator), and the interview's page names the camera it is waiting for."
- Here says: "When the help for the editing program is off: raw clips are still counted as having no proxy, the generator is never opened"; and the generator only runs on an editor's computer that syncs the clip, with the editor away and every other proxy done
- Settled by: the owner must say: when Timeline Cards is on and no raw proxy can be made (the help for the editing program off, or no computer with the generator holds the clip), is a raw camera file dropped in refused with a sentence, or does the interview wait for it? (OWNER_REQUIREMENTS 6: "Everything up to the finished cut works with no editing program at all.")
- Fix: both: proxies-and-file-moves should say how raw clips dropped into Timeline Cards get their proxy (which computer, and what happens with the help off), and cards-footage-in should say what the person sees when none can be made.

### F3: "move it through the product" is advised for a project folder, but the product offers no way to move a whole project
- Kind: missing
- From: dashboard-1 / Each computer's issues are listed worst first, each explained
- Here: An admin moves a file or folder on the server and every computer follows
- From says: "move it back, or move it through the product so every computer follows (see Proxies and file moves: Moving footage through the product)"
- Here says: the move form takes "a file or folder in this project" and refuses "never the project's own identity mark"; a project folder is followed only when "moved or renamed by hand on the NAS"
- Settled by: the owner must say: can an admin move or rename a whole project from the dashboard so every computer follows, or is moving it by hand on the NAS the only way?
- Fix: either proxies-and-file-moves adds a way to move a whole project through the product, or dashboard-1's advice drops "move it through the product" and points at moving it back (or at the hand move on the NAS being followed).

### F4: hand moves are recognised "however many", but the dashboard caps them at 500 at once
- Kind: contradiction
- From: dashboard-1 / Files moved by hand on the NAS are reported as they are followed
- Here: Every hand move is recognised or the admin is told how many were not
- From says: "At most 500 moves are taken at once; beyond that the first 500 (by project and path) are followed and a serious problem opens"
- Here says: "Every hand move is recognised however many happen at once and however the NAS is looked over."
- Settled by: PRX-082 (situation, weaker): "Moves past 500 per scan ... were dropped, then treated as deletions and re-uploaded"; "Every hand move is recognised however many there are"
- Fix: dashboard-1 should drop the fixed 500 limit and say only that, if a look ever finds more than can be followed, the serious problem names how many were not (staying until dismissed, as here).

### F5: proxy making is shared work here, but the computer's own work outside the shared queue in fleet-jobs
- Kind: contradiction
- From: fleet-jobs / A computer's own heavy work comes first
- Here: Clips with no proxy are found and their proxies are made
- From says: "A computer's own heavy work for its own editor (making proxies for it, see Proxies and file moves: Making proxies on editors' computers) comes before shared work."; project proxies are not in "The kinds of shared work and what each needs"
- Here says: "Making a proxy is heavy work of the kind the studio's computers share: which able and free computer makes a given proxy is decided as for all such work (see Work shared out across the computers: Choosing who runs what)"
- Settled by: JOB-013 (ruling) has the editor send a clip's proxy to a chosen computer, while OWNER_REQUIREMENTS 2 lists "making proxies on editors' computers, and sharing heavy work across the studio's computers" as two things; the owner must say: is a clip's proxy made only by the computer that holds it for its own editor, or by any free computer in the studio?
- Fix: once answered, either fleet-jobs adds project proxies as a kind of shared work, or proxies-and-file-moves says proxies are made by the computer holding the clip, outside the shared queue.

### F6: which goes first, a computer's proxy making or b-roll describing
- Kind: contradiction
- From: fleet-jobs / A computer's own heavy work comes first
- Here: What proxy making on a computer is doing, in one line
- From says: "A computer's own heavy work for its own editor (making proxies for it ...) comes before shared work. While it is busy with its own heavy work, it takes no shared work"
- Here says: "held back because other heavy work on this computer goes first, with the reason (for example \"indexing b-roll first\")"
- Settled by: the owner must say: when a computer has both its own missing proxies and b-roll to describe, which does it do first?
- Fix: fleet-jobs, proxies-and-file-moves and broll ("Making proxies on that computer waits while describing runs") should state the same order.

### F7: the editor's pick of which computer makes a clip's proxy is not described here
- Kind: missing
- From: fleet-jobs / Choosing a computer is a pick from the studio's known computers
- Here: nowhere
- From says: "an editor choosing which computer makes a clip's proxy from its preview, see Proxies and file moves: Making proxies on editors' computers"
- Here says: nothing
- Settled by: JOB-013 (ruling): "The editor picks which computer makes a clip's proxy, from the preview."
- Fix: proxies-and-file-moves should describe, beside a clip's preview and on each incoming clip, the pick that sends that clip's proxy making to a chosen computer at once.

### F8: whether a camera's own proxy keeps its camera ending (Sony "S03") or takes its clip's exact name
- Kind: differs
- From: footage-sorter-and-camera-cards-1 / Where a card's files land
- Here: Every proxy on the server has its original beside it
- From says: "Proxies copied off a card land in a Proxy folder inside the dated folder holding their originals, with matching base names, so the editing program finds them beside their clips."
- Here says: "Proxies that cameras make themselves are also matched with their known endings removed (Sony's ending \"S03\", in any letter case ...)", while "A clip counts as having a proxy when a QuickTime or MP4 file of the same name sits in the \"Proxy\" folder"
- Settled by: PRX-002 (given, weaker): Resolve pairs proxies by exact file name, so a proxy one character off never attaches
- Fix: footage-sorter-and-camera-cards-1 should say plainly that a camera proxy is renamed to its clip's exact name when copied off the card, and proxies-and-file-moves should say whether a camera proxy still carrying its ending counts as the clip's proxy.

### F9: who may make a move every computer follows: an admin here, anyone signed in (or nobody) in the Sorter
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / Moves in the folders editors sync reach every editor's computer
- Here: An admin moves a file or folder on the server and every computer follows
- From says: "Footage in the folders editors' computers sync is moved so that every editor's copy follows"; its sorted moves run with "the move itself needs nobody", and moving elsewhere or putting back is "Who: anyone signed in."
- Here says: "Who: an admin (\"only an admin can move files on the server\")." with the Footage Sorter as a way in, and history records "who asked (an admin, or \"detected\" for a hand move on the NAS)"
- Settled by: the owner must say: may anyone signed in move footage inside a project through the Footage Sorter, with every editor's copy following, or only an admin?
- Fix: proxies-and-file-moves should say who may move through the Sorter and what the history records as "who asked" for a Sorter move nobody started, or the Sorter should require an admin for moves inside projects.

### F10: two different refusal sentences for a Sorter move that editors' copies cannot follow
- Kind: differs
- From: footage-sorter-and-camera-cards-2 / Moves in the folders editors sync reach every editor's computer
- Here: A move made in the Footage Sorter inside a project reaches every editor's copy
- From says: "inside Projects, so every editor's copy must follow; this server has no way to make that happen for it"
- Here says: "<path> is in no CC Sync project, so no editor's copy can follow it"
- Settled by: the owner must say: when the Sorter cannot make editors' copies follow a move in the synced folders, what one sentence does the person see?
- Fix: both pieces should name the same condition and the same sentence, with the full refusal in proxies-and-file-moves and a pointer from the Sorter.

### F11: a proxy's timecode: "exactly what the timecode track states" against "none when the original has none" and drop-frame rewriting
- Kind: contradiction
- From: resolve-on-the-editors-computer / What Resolve checks when a proxy is attached
- Here: A proxy's timecode matches its original's in the form Resolve reads
- From says: "a proxy whose timecode is missing or differs from its source's is refused, so every proxy carries exactly the timecode its source's timecode track states"
- Here says: "Every proxy carries its original's start timecode, or none when the original has none" and, for Sony at 29.97/59.94 without a timecode track, "it is written that way" in drop-frame form
- Settled by: PRX-003 and PRX-004 (given, weaker): "or none when the original has none"; "names the same frame in the same drop-frame form Resolve reads from the original"
- Fix: resolve-on-the-editors-computer should replace its rule with a pointer to this piece's timecode rule (same frame, in the form Resolve reads, none when the original has none).

### F12: the ranking of candidate files when relinking a missing clip differs
- Kind: contradiction
- From: resolve-on-the-editors-computer / An editor relinks offline clips to files found in the tree
- Here: A missing clip whose file is already in the tree is relinked, never copied
- From says: "ranked by the longest matching end of the path, then by the folder most other clips were found in, then by the larger file"
- Here says: "the one whose folder path matches the clip's old path most closely wins; only when that leaves a tie does the largest file (the original) beat a smaller one (a proxy)"; and candidates have "the same name and size"
- Settled by: PRX-090 (ruling): "the closest matching folder path wins; only when that leaves a tie does the largest file, the original, beat a proxy"
- Fix: resolve-on-the-editors-computer should drop "the folder most other clips were found in" as a step before size (or the owner adds it to the ruling), and both should agree whether size must match.

### F13: relinking missing clips to files in the tree is described in full in both pieces
- Kind: said twice
- From: resolve-on-the-editors-computer / An editor relinks offline clips to files found in the tree
- Here: A missing clip whose file is already in the tree is relinked, never copied
- From says: "For each clip the product looks for files of the same name in the shared tree ... the editor sees each pick before it is made and chooses another candidate"
- Here says: "the person sees each candidate's path, size and a preview, and picks one before anything is relinked"
- Settled by: PRX-089, PRX-090 (ruling), PRX-091 (ruling)
- Fix: keep the full description in one piece (resolve-on-the-editors-computer, where the editor acts) and leave a pointer in the other.

### F14: the blocked project's message differs when its moved folder cannot be followed
- Kind: contradiction
- From: sync-2 / When an admin renames or moves a project on the server, every editor's copy follows by itself
- Here: A project folder moved on the server is followed before anything syncs
- From says: "{name} is not syncing because CC Sync could not move its folder. Your files are safe where they are. Close it in Resolve and in Explorer, then it retries by itself."
- Here says: "the project shows as blocked with the reason: \"Could not move this project's folder\""
- Settled by: the owner must say: what sentence does an editor see when their copy of a moved project could not follow?
- Fix: proxies-and-file-moves should drop its own sentence and point to sync-2's messages.

### F15: following a project moved on the server is described in full in both pieces, with a stray folder at the new place handled differently
- Kind: said twice
- From: sync-2 / When an admin renames or moves a project on the server, every editor's copy follows by itself
- Here: A project folder moved on the server is followed before anything syncs
- From says: "The new place already holds a synced copy of the project: the old folder is left where it is ... and syncing continues from the new one." / "The new place holds files but is not a synced copy: the move is refused."
- Here says: "A stray folder at the new place (for example one holding only proxies) never counts as the move; the move completes only into the folder really moved."
- Settled by: PRX-062 per this piece's trace (the "could not move this project's folder" message shown and cleared); for the proxies-only folder, the owner must say: when an editor's computer already has a folder holding only proxies at a project's new place, does its copy still move there?
- Fix: keep the editor-side description in sync-2, add the proxies-only case there, and reduce proxies-and-file-moves to the server side with a pointer.
