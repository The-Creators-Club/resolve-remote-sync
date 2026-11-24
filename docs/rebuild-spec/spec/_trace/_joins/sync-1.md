# Joins aimed at sync-1

## Checked

- J1 | fine
- J2 | fine
- J3 | fine
- J4 | F24
- J5 | F1
- J6 | F2, F3
- J7 | F4, F5
- J8 | F6
- J9 | F6
- J10 | F7
- J11 | fine
- J12 | fine
- J13 | fine
- J14 | fine
- J15 | fine
- J16 | F8
- J17 | fine
- J18 | F9
- J19 | F6, F10
- J20 | fine
- J21 | fine
- J22 | fine
- J23 | fine
- J24 | fine
- J25 | F11
- J26 | F12
- J27 | F13
- J28 | fine
- J29 | F14
- J30 | F15
- J31 | fine
- J32 | fine
- J33 | fine
- J34 | fine
- J35 | F16
- J36 | fine
- J37 | fine
- J38 | fine
- J39 | F17
- J40 | F18
- J41 | F10, F19, F20
- J42 | F10, F20
- J43 | fine
- J44 | fine
- J45 | F9, F21, F22
- J46 | fine
- J47 | F2
- J48 | F10, F19
- J49 | F23

## Findings

### F1: The sentences for a refused tick differ between the two pieces
- Kind: contradiction
- From: dashboard-1 / An editor or an admin ticks a project for a computer
- Here: The rules every tick and untick follow, wherever it is made
- From says: "you can only change your own projects (admins excepted)"; "unknown or inactive project '<name>'"; "this account is wired to the server: it works directly off the NAS and syncs nothing, so projects cannot be ticked for it"
- Here says: "Only the editor themself or an admin may change an editor's plan ("not allowed" otherwise)"; "unknown project '<slug>'"; "every computer on this account is wired to the server: they work directly off the NAS and sync nothing, so projects cannot be ticked for them"
- Settled by: the owner must say: which exact sentence does a person read when a tick is refused because it is someone else's computer, the project is unknown or archived, or every computer of theirs is wired?
- Fix: keep the refusal sentences in sync-1 only (both pieces list them in full today) and have dashboard-1 point to them, using whichever wording the owner picks.

### F2: Upload only carries only video originals in the other pieces, every file here
- Kind: contradiction
- From: dashboard-1 / Full sync or upload only, and switching between them (also sync-2 / The dashboard lists what each computer still owes, and never claims "nothing" when it cannot tell)
- Here: An upload-only tick sends every file up and brings down only the empty folders
- From says: "send the video originals to the server and download nothing (no proxies, no shared project files)."; sync-2: "Owed up: originals the computer holds that are not on the NAS"
- Here says: "For a project ticked upload only on a computer, every file in its folder goes up to the server, not just video."
- Settled by: SYN-028 (ruling): "every file except system clutter and temporary files goes up"
- Fix: dashboard-1 changes its upload-only description (and its "then its video originals start uploading" getting-ready line) to every file, and sync-2 counts every file not on the NAS as owed up for an upload-only tick.

### F3: Upload only brings down empty folders here, nothing at all in dashboard-1 and in the ruling
- Kind: contradiction
- From: dashboard-1 / Full sync or upload only, and switching between them
- Here: An upload-only tick sends every file up and brings down only the empty folders
- From says: "send the video originals to the server and download nothing"
- Here says: "The only thing that comes down is the project's folder structure, empty"
- Settled by: SYN-028 (ruling): "every file except system clutter and temporary files goes up, nothing comes down"
- Fix: sync-1 drops the empty folders coming down for an upload-only tick (heading, first paragraph, "A computer receives only..." list and "Each computer has its own sync plan"), unless the owner now says he wants them.

### F4: An untick takes effect at once there, only after a minute's grace here
- Kind: contradiction
- From: dashboard-1 / An editor, an admin or the editor's own computer unticks a project
- Here: Unticking can be undone within a minute at no cost
- From says: "An untick is recorded in the history, naming the computer when a computer did it, and takes effect at once."
- Here says: "For 60 seconds after an untick, nothing about it is put into effect, so unticking and pressing Undo within that minute changes nothing on any computer."
- Settled by: the owner must say: when someone unticks a project, does it stop on the computer at once, or only after a minute in which Undo costs nothing?
- Fix: dashboard-1 says the untick is recorded at once and put into effect after the minute's grace (or sync-1 drops the grace), and sync-1's own "takes effect at once" in the tick rules is made to agree.

### F5: The sentence for a computer's untick that finds the tick only on another computer differs
- Kind: differs
- From: dashboard-1 / An editor, an admin or the editor's own computer unticks a project
- Here: An editor removes a project from their computer in one action
- From says: "There is no tick for <project> under this computer's name (<computer>), but it is still ticked for another of your computers. Nothing was removed. If this computer was renamed, wait until the dashboard shows the new name, or untick it on the dashboard."
- Here says: "the dashboard has no tick for it under this computer's name (<computer>), but it is still ticked for another of your computers. If this computer was renamed, wait until the dashboard shows the new name, or untick it on the dashboard"
- Settled by: the owner must say: when the app's Remove finds the project ticked only on another of the person's computers, which sentence does the editor read?
- Fix: sync-1 shows the dashboard's sentence word for word (or dashboard-1 adopts sync-1's), so one sentence exists for this case.

### F6: The safety stop is called a stop of proxy download elsewhere, a stop of all downloads here
- Kind: differs
- From: dashboard-1 / An admin resumes a computer's stopped proxy download (also dashboard-2 / What a reply to the server check can carry out; fleet-jobs / The reasons a computer is passed over for a piece of work)
- Here: Downloads stop themselves when the server suddenly looks wrong
- From says: "\"Resume\" is offered when its proxy download stopped itself to protect footage"; fleet-jobs: "this computer's proxy download stopped itself, so it is not in a state anyone should add work to"
- Here says: "While stopped, nothing is downloaded or moved aside. Uploads keep running."
- Settled by: decision 4.2 (answered 2026-11-24 as recommended): "A: one rule for everything that comes down: a file gone from the server is moved aside into the recovery folder, never deleted, under the same safety stop and limits."
- Fix: dashboard-1, dashboard-2 and fleet-jobs say "downloads" (not "proxy download") for the safety stop and its Resume, so a builder does not stop only proxies.

### F7: The refusal for a studio-wide stop without a reason names the "tray" there and the "app" here
- Kind: contradiction
- From: dashboard-2 / An admin stops syncing on every computer at once, with a reason
- Here: An admin stops syncing on every computer with a reason
- From says: "say why: the reason is shown in every editor's tray (at least 3 characters)"
- Here says: "say why: the reason is shown in every editor's app (at least 3 characters)"
- Settled by: the owner must say: does the admin's refusal say the reason is shown in every editor's "app" or "tray"?
- Fix: describe the studio-wide stop (reason limits, length, refusal) in one piece only, with the other pointing to it; both describe it in full today.

### F8: The states a ticked project shows in the app's list differ
- Kind: contradiction
- From: editor-app / The editor sees each ticked project with what it is doing and why
- Here: The app lists this computer's ticked projects and how each is doing
- From says: "blocked, \"Waiting for its filter list from the server. It starts by itself once that arrives.\""; "Only the project being synced shows live states; the others show \"waiting\" or \"paused\"."
- Here says: "The states are \"up to date\", \"syncing now\", \"waiting its turn\", \"paused\", \"there is a problem\", \"not synced to this computer\", or \"not known\"."
- Settled by: the owner must say: which states can a ticked project show in the app's list (is "blocked" one, and can a project that is not being synced now show "up to date" or "there is a problem")?
- Fix: one closed list of states in one piece, including "blocked" (which sync-1 itself uses under "A project never syncs until these rules are in place for it"), with the other piece pointing to it.

### F9: Drive reminders follow only owed uploads there; here also when what is owed cannot be told
- Kind: contradiction
- From: editor-app / Notifications are the operating system's own, headed with the studio's name and mark (also sync-2 / When the sync drive is pulled with work owed, the editor is told what is owed and reminded until it is back)
- Here: A drive pulled out with work owed is named and reminded about
- From says: "reminders follow only while uploads the server does not yet have are owed"; sync-2: "Reminders come every 30 minutes, and only while something owed is going up"
- Here says: "When the sync drive goes away with uploads owed, or when what is owed cannot be told, the warning names what is owed" and "A drive that stays not answering gets its own repeating reminder"
- Settled by: SYN-079 (ruling): "Unplugging with uploads owed, or of unknown direction, names what is owed and reminds every 30 minutes"
- Fix: editor-app and sync-2 add the unknown-owed case (and editor-app the not-answering reminder), matching sync-1.

### F10: Other pieces keep a per-computer "stop" beside the editor's pause, which this piece and the owner removed
- Kind: contradiction
- From: fleet-jobs / The reasons a computer is passed over for a piece of work (also sync-2 / Each computer says in one sentence why it is not syncing, and since when; sync-2 / An editor sees the originals they asked for arrive; sync-2 / The app's menu says in one phrase what syncing is doing now)
- Here: Syncing waits for a short list of reasons, each in its own words; An admin stops syncing on every computer with a reason
- From says: "\"syncing is stopped on this computer\""; sync-2: "\"NOT DOWNLOADING ORIGINALS: syncing is stopped on this computer\" (an admin's stop or the computer's own)"; "\"Sync: stopped on this computer\""; "⚠ Two things are stopping sync on this computer: a stop and a pause. Clear both to sync again."
- Here says: "A stop is for the whole studio; one computer is paused at that computer."
- Settled by: decision 4.5 (answered as recommended): "A: one pause that stops everything and holds until the editor resumes; no separate stop."
- Fix: fleet-jobs and sync-2 drop every "stopped on this computer" cause, sentence and menu phrase, leaving the studio-wide stop and the editor's pause.

### F11: Pictures of originals while picking appear only with the Footage Sorter on here, always there
- Kind: contradiction
- From: proxies-and-file-moves / Picking originals shows a picture of each file and plays its proxy
- Here: An editor picks camera originals to come down to one computer
- From says: "Wherever a person picks original files (for example to bring originals down to their computer), each file has a thumbnail and plays its proxy when clicked."
- Here says: "When the Footage Sorter is on, each file shows a small picture from its proxy that opens the proxy playing in a new tab, or \"no proxy yet\"."
- Settled by: PRX-040 (ruling): "Each file in the originals picker has a thumbnail and plays its proxy; a Blackmagic RAW file without a proxy says \"no proxy yet\"."
- Fix: sync-1 drops "When the Footage Sorter is on" so the picture and playback are always offered in "Browse originals".

### F12: A proxy made on an editor's computer is sent to the server there; proxies never go up here
- Kind: contradiction
- From: proxies-and-file-moves / A proxy made on an editor's computer is never removed by syncing
- Here: A full tick sends a project's camera originals up and brings its proxies and other files down; Each kind of file travels only in its own direction
- From says: "A proxy an editor's computer made itself is sent to the server like any proxy"
- Here says: "originals brought down are never sent back, and proxies are never sent up." and "proxies only come down"
- Settled by: PRX-030 (ruling): "Clips without proxies never reach remote editors; the owner wants gaps reported and filled on editors' own computers", with OWNER_REQUIREMENTS §2: "Always available, each with a setting per computer: making proxies on editors' computers"
- Fix: sync-1 says a proxy made on this computer goes up to the server's Proxy folder (never replacing one already there) and narrows "proxies are never sent up" to proxies that came down.

### F13: Set-aside files are kept as long as promised and while the NAS lacks them there; cleared by age, size and space here
- Kind: contradiction
- From: proxies-and-file-moves / Anything set aside is kept as long as promised
- Here: The recovery folder empties itself by age and size
- From says: "Anything CC Sync sets aside instead of deleting is kept at least as long as people are told it will be, and is never removed while the NAS does not hold the same file"
- Here says: "then, if what is left is over 50 GB, the oldest batches until it is under, never the newest batch; and when the sync drive is short of free space, the oldest batches until there is enough room again"
- Settled by: the owner must say: may an editor's recovery folder clear a file before its stated keep period (when it passes 50 GB or the drive is short of space), or a file the NAS does not hold?
- Fix: whichever the owner says, sync-1's clearing rules and proxies-and-file-moves' promise are made the same, and the status sentence "Copies older than D days are removed automatically" says so if size or space can clear earlier.

### F14: Every still-changing file waits there; only camera video waits here
- Kind: missing
- From: proxies-and-file-moves / A proxy appears under its real name only when it is finished
- Here: New footage starts going up about two minutes after it stops changing (camera video only); Some files never travel at all (no such rule)
- From says: "More generally, a file whose size or time is still changing never travels; it travels once it has been still for a set time (see Sync: Files that must never sync)."
- Here says: "When a camera video file appears in, changes in, or is moved into a project ticked on this computer, it starts uploading on its own soon after it settles"; for other files "a change is noticed as it happens"
- Settled by: the owner must say: does every file (an edit project being saved, a proxy being written) wait until it has stopped changing before it travels, or only camera video?
- Fix: sync-1 states the rule for all files under "Files that must never sync" (or proxies-and-file-moves narrows its sentence to camera video).

### F15: Two free-space floors for the same drive: 20 GB or 5% for making proxies, 20 GB for downloads
- Kind: differs
- From: proxies-and-file-moves / Proxy making keeps the drive from filling
- Here: Downloads pause when the sync drive is nearly full, uploads never
- From says: "checked against the larger of 20 GB and 5% of that drive" with "Setting: Keep this much space free when making proxies"
- Here says: "Setting: Keep this much free on the sync drive. Does: below this, downloads pause, and they start again at twice it. Off turns this off. Default: 20 GB."
- Settled by: the owner must say (decision 4.14 made "one floor per computer (20 GB by default)" decide every syncing free-space verdict but did not name proxy making): should making proxies stop at the same free-space figure that pauses downloads?
- Fix: if yes, proxies-and-file-moves uses sync-1's one setting and drops its own; if no, both pieces say plainly that the two floors are separate settings.

### F16: Asking for originals from inside Resolve is described in full in both pieces
- Kind: said twice
- From: resolve-on-the-editors-computer / An editor asks for originals from inside Resolve
- Here: An editor asks for originals from inside Resolve
- From says: "A request not answered within 1 hour, or one that cannot be read, is dropped and the editor is told so."
- Here says: "If the server cannot be reached the request is kept and sent again, and no part of it is sent twice."
- Settled by: no disagreement to settle yet: both list the same six menu entries, the 2-second pick-up and the retry; only From has the 1-hour limit and Here has the console sentences
- Fix: hold the Resolve menu entries, console answers and request handling in one piece (resolve-on-the-editors-computer, which owns the Resolve side), with sync-1 keeping one line and a pointer.

### F17: A name clash is reported as never uploading for any file there, only for camera originals here
- Kind: contradiction
- From: sync-2 / A newer local file that will never upload because the server has its name is reported
- Here: The editor is told about files that will never upload because of a name clash or a wrong clock
- From says: "Each project is checked for files that exist both on the editor's computer and on the server with the same name but a different size. The first version of a name to reach the server is the one kept there"
- Here says: "The first version of a camera original's name to reach the server is the only one that ever will"
- Settled by: decision 4.4 (answered as recommended): "A: camera originals stay first-version-wins, with the editor told and the two fixes ...; every other file, in either mode, replaces the server's copy with the earlier one kept for a year."
- Fix: sync-2 limits the check and the report to camera originals (and its pointer goes to Sync: Names, where the rule is).

### F18: Files the product itself keeps from uploading are listed there but not here
- Kind: missing
- From: sync-2 / Files that are never sent are never counted as owed
- Here: Some files never travel at all
- From says: "copies the product made itself to make a file ready to edit, files marked as an original kept aside or as temporary"
- Here says: nothing (the list names unfinished, temporary, lock and partial files, YouTube downloads in progress or failed, moves in progress, empty camera files, operating-system litter, the recovery folder and other tools' bookkeeping)
- Settled by: the owner must say: do the copy made to make a downloaded clip ready to edit, and the original kept aside beside it, ever go up to the server?
- Fix: sync-1's never-travel list (which it says is "the same set ... everywhere") gains these files, or sync-2 drops them.

### F19: The reasons syncing is held come in a different order and different words in sync-2
- Kind: contradiction
- From: sync-2 / Each computer says in one sentence why it is not syncing, and since when (also sync-2 / The app's menu says in one phrase what syncing is doing now)
- Here: Syncing waits for a short list of reasons, each in its own words
- From says: "nobody is signed in on the computer | \"Not syncing: nobody is signed in to CC Sync on this computer\"" first, "the editor paused it | \"Not syncing: syncing is paused on this computer\"" ninth; menu: "Paused by the editor: \"Sync: paused\"" fifth, after the admin's stop
- Here says: "1. paused by the editor: \"Syncing is paused.\"; 2. stopped for the whole studio by an admin" and "The same reasons, in the same order and the same words, are given everywhere: in the app, on the dashboard and in alerts."
- Settled by: decision 4.20 (answered as recommended): one list, the same reasons in the same order everywhere; which order is not settled, so the owner must say: when an editor has paused and nobody is signed in, which reason is named first?
- Fix: one table of reasons, order and sentences in one piece (sync-2's is the fuller), with sync-1 pointing to it and its six-item list removed.

### F20: The sync drive's sentences differ, though this piece says they are the same everywhere
- Kind: contradiction
- From: sync-2 / Each computer says in one sentence why it is not syncing, and since when (also sync-2 / An editor sees the originals they asked for arrive)
- Here: The product watches whether the sync drive is really there
- From says: "Not syncing: the sync drive is not there on this computer"; "Not syncing: the sync drive is mapped but not answering, so nothing can be read or written"; "Not syncing: the sync drive is pointing at the wrong place"; "NOT DOWNLOADING ORIGINALS: the sync drive is not connected"
- Here says: "disconnected: \"the sync drive is disconnected\"" ... "These sentences are the same on the status line, in a notification, in the sync detail and on the dashboard."
- Settled by: decision 4.20 (answered as recommended): the same reasons, in the same words, everywhere
- Fix: sync-2 uses sync-1's three drive phrases ("the sync drive is disconnected", "... is mounted at the wrong place ...", "... is not answering ...") in its reasons table and its originals line.

### F21: sync-2 keeps a setting for drive reminders that the owner removed
- Kind: contradiction
- From: sync-2 / When the sync drive is pulled with work owed, the editor is told what is owed and reminded until it is back
- Here: A drive pulled out with work owed is named and reminded about
- From says: "Setting: Drive reminders. Does: how many minutes pass between reminders that the sync drive is away with work owed; 0 means the first notice only. Default: 30 minutes."
- Here says: "It is repeated every 30 minutes until the drive is back, across restarts" (no setting)
- Settled by: decision 4.17 (answered as recommended): "A: no setting; every 30 minutes as ruled, with the editor's \"remind me later\" and \"stop reminding me\" for one outage."
- Fix: sync-2 deletes the Drive reminders setting.

### F22: The pulled-drive warning, its reminder and "remind me later" are worded differently in the two pieces
- Kind: contradiction
- From: sync-2 / When the sync drive is pulled with work owed, the editor is told what is owed and reminded until it is back
- Here: A drive pulled out with work owed is named and reminded about
- From says: "<Your ... drive> was disconnected before syncing finished: <summary> still to go. Plug it back in to finish syncing." and "\"remind me later\": one reminder after the chosen minutes, then the usual pace"
- Here says: "<Drive> was disconnected with <owed> still to go: plug it back in to finish syncing" and "\"REMIND ME LATER\" (silences them for 2 hours: \"CC Sync will remind you about this drive again in 120 minutes.\")"
- Settled by: SYN-080 (situation, weaker): "An editor can snooze for two hours or stop reminders for this episode"; for the sentences, the owner must say: which words does the first warning and each reminder use?
- Fix: describe the pulled-drive warning, reminders and snooze in one piece only (both describe it in full today), with a fixed two-hour snooze, and the other piece pointing to it.

### F23: A YouTube clip reaches the requester's computer on its own there; it never comes down here
- Kind: contradiction
- From: youtube / Downloaded clips reach the computer of the editor who asked
- Here: A full tick sends a project's camera originals up and brings its proxies and other files down
- From says: "The clips of a job reach the computer of the editor who asked for them on their own, wherever they were downloaded, when that computer syncs the project."
- Here says: "the downloaded original goes up to the server from the computer that downloaded it and never comes down to anyone else's (a person who wants it downloads it themselves)."
- Settled by: SYN-009 (ruling): "A YouTube original goes up to the NAS only; other computers get its proxy, and a requester gets their own clip by downloading it themselves."
- Fix: youtube drops "reach the computer of the editor who asked for them on their own, wherever they were downloaded" and says the requester, like anyone else, fetches it in one click (as its own "GET IT FROM THE NAS" already says).

### F24: The board offers to sync its episode's documents right now; this piece has no such request
- Kind: missing
- From: cards-board / The board is a Markdown file kept with its episode
- Here: nowhere (only "Sync now runs every transfer this computer has switched on at once", from the app, "Who: the editor at the computer")
- From says: "A person can also ask for them to be brought up to date right now: that makes the full round trip at once and says what it did (see Sync: What syncs where)."
- Here says: nothing
- Settled by: the owner must say: can a person on the board ask, from the page, for that episode's planning documents to be synced to and from their computer at once, and be told what was done?
- Fix: if yes, sync-1 describes that request (who, from where, and the answer naming what was done) under What syncs where; if no, cards-board drops the sentence or points to the app's "Sync now".
