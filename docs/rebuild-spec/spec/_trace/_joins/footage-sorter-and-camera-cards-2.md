# Joins aimed at footage-sorter-and-camera-cards-2

## Checked

- J1 | F1
- J2 | fine
- J3 | F2
- J4 | fine
- J5 | F3
- J6 | fine
- J7 | fine
- J8 | F4
- J9 | fine
- J10 | F5, F6, F7
- J11 | F8, F9
- J12 | fine
- J13 | F10

## Findings

### F1: Timeline Cards expects card footage to reach the episode on its own; the Sorter never says it sends anything to Timeline Cards
- Kind: missing
- From: cards-footage-in / Clips dropped in become an interview ready to cut
- Here: nowhere
- From says: "footage brought in from camera and recorder cards reaches the same place on its own (see The Footage Sorter and camera cards: Sorting into shoots, people and cameras)"
- Here says: nothing (the only mention of Timeline Cards is "When Timeline Cards is off: the studio's interview transcripts are not compared; every other clue still works.")
- Settled by: the owner must say: when an interview's camera and recorder cards are copied and sorted in the Footage Sorter, does that interview arrive in Timeline Cards and start processing by itself, or must a person still drop its clips onto the episode?
- Fix: if yes, this piece gains a behaviour under "Sorting into shoots, people and cameras" saying which sorted footage (for example clips filed in an Interviewees folder) is handed to Timeline Cards, when, and what happens with Timeline Cards off; if no, cards-footage-in drops the sentence from its "Ways in".

### F2: This piece says card copies to staging always get time folders; part 1 sends clips that cannot have one to a "loose" folder
- Kind: contradiction
- From: footage-sorter-and-camera-cards-1 / Where a card's files land
- Here: Footage is filed in day-and-camera time folders
- From says: "clips that cannot have one (stills, no time, unknown camera) go to \"<day> <card label, serial or drive> loose\""
- Here says: "No time folder is made for ... stills, other files, clips with no recording time, or clips with no camera label: those land straight in the assigned folder. Card copies into the NAS's staging folder always use time folders."
- Settled by: the owner must say: when a card is copied into the NAS's staging folder, do its stills and clips with no time or no known camera go into one "loose" folder for that card?
- Fix: this piece should say that staging copies use time folders whatever the layout choice, and that clips which cannot have one go to the card's "loose" folder described in part 1.

### F3: Part 1 says recorder sound is never placed by the recorder's own time stamp alone; this piece places it by the recorder's clock alone
- Kind: contradiction
- From: footage-sorter-and-camera-cards-1 / A recorder's reset clock is corrected from its neighbouring files
- Here: Each recording gets one verdict; The Sorter proposes where each sound recording belongs
- From says: "recorder sound is placed by its content and the cameras' times, never by the recorder's own time stamp alone"
- Here says: "**inferred**, when only the recorder's clock places it" and "The recorder's clock overlaps the clips of a shoot folder ... 0.8 when exactly one folder really overlaps" (0.8 is high confidence, which is offered as a sound suggestion on the main clip list)
- Settled by: SRT-145 (ruling: "trying time, then waveform, then transcript"), which outranks SRT-032 (given: "never by the recorder's own timestamp")
- Fix: part 1 should say the recorder's own time is a clue tried first that sound and speech may overrule, not that it never places a recording alone.

### F4: Rescan is described in both pieces, and they disagree on how long the page follows it and on asking again
- Kind: contradiction
- From: footage-sorter-and-camera-cards-3 / A full look through every footage folder
- Here: Rescan reads every source and destination again
- From says: "asking again while one runs says so and shows the count it has reached" and "the page stays usable and keeps loading however long the look takes"
- Here says: "Rescan (ignored and disabled while one runs) shows \"Scanning… <n> clips\", updated about every second, until it ends (the page stops watching after one hour)"
- Settled by: the owner must say: when a full look runs longer than an hour, does the page keep showing its progress until it ends, and does pressing Rescan again during one say so or do nothing?
- Fix: keep the full description in part 3 only and make this piece's "Rescan reads every source and destination again" a pointer to it with the messages it alone owns ("Scan complete", "Moved outside the app").

### F5: Two different refusals for a move in a project that every editor's copy cannot follow
- Kind: contradiction
- From: proxies-and-file-moves / A move made in the Footage Sorter inside a project reaches every editor's copy
- Here: Moves in the folders editors sync reach every editor's computer
- From says: "The clip and its destination must each be inside an active CC Sync project; otherwise the move fails with \"<path> is in no CC Sync project, so no editor's copy can follow it\". ... Moves into a project from outside every project (for example from a transfer folder) are plain moves on the server."
- Here says: "When the server cannot make every editor's copy follow, the move of such footage is refused: \"inside Projects, so every editor's copy must follow; this server has no way to make that happen for it\""
- Settled by: the owner must say: when the Sorter would move footage out of a synced project to a folder no project covers (or the reverse), is the move refused, and with what words?
- Fix: proxies-and-file-moves should own the rule and its one sentence, and this piece should point to it instead of giving its own refusal text.

### F6: A proxy that cannot follow: this piece holds the whole clip back, the move piece moves the original and leaves the proxy
- Kind: contradiction
- From: proxies-and-file-moves / A move made in the Footage Sorter inside a project reaches every editor's copy
- Here: Every move is checked before it starts; Moves in the folders editors sync reach every editor's computer
- From says: "the move is made exactly as \"Move on the server and on every computer\"" (whose result includes "moved, some proxies stayed ... these proxy files did not move")
- Here says: "a plan that would leave a proxy behind holds that clip back" and "A clip is never moved in part."
- Settled by: SRT-133 (situation, weaker: "a clip with any conflicting file stays whole where it is and is listed for a person to decide")
- Fix: proxies-and-file-moves should say a Sorter move is held back whole when a proxy cannot follow, rather than "made exactly as" the admin move with its "some proxies stayed" outcome.

### F7: The Sorter's move is "made exactly as" an admin-only action, but here it needs nobody and anyone can move or put back
- Kind: contradiction
- From: proxies-and-file-moves / A move made in the Footage Sorter inside a project reaches every editor's copy
- Here: Sorted footage moves into its folder on its own; What was moved can be seen, moved elsewhere or put back
- From says: "the move is made exactly as \"Move on the server and on every computer\"" (whose Who is "an admin (\"only an admin can move files on the server\")")
- Here says: "Who: anyone signed in sees moves and held-back clips; the move itself needs nobody." and, for Move it elsewhere and Put it back, "Who: anyone signed in."
- Settled by: DECISIONS.md page 2, answer 5: "The Footage Sorter moves originals into their final folders on its own, with no approval, and a person can overrule by hand afterwards."
- Fix: proxies-and-file-moves should say the Sorter's move reaches every computer the same way but needs no admin and is never refused for lack of one.

### F8: The nightly cloud backup's switch and time are a setting in both pieces, under two names and two defaults
- Kind: said twice
- From: server-install-and-running-1 / The off-site backup's state, schedule and run now
- Here: The NAS's footage goes to the cloud backup every night
- From says: "An admin sets \"Nightly at\" (on or off, and a time) ... \"Run now\"" (and its setting "Nightly off-site backup ... Default: on, at 04:15")
- Here says: "The record's page has its on and off switch, its time and Run now" and "Setting: Nightly cloud backup of footage. ... Default: off until a cloud backup is set up."
- Settled by: OWNER_REQUIREMENTS.md: "one place a setting comes from"; SRT-108 (ruling) keeps the controls reachable from the record's page
- Fix: this piece should keep only a pointer to the server's "Nightly off-site backup" setting, shown on the record's page, and drop its own setting line, name and default.

### F9: What the nightly cloud backup carries: "the NAS's footage" here, only ticked projects' proxies, audio, stills, graphics and project files there
- Kind: contradiction
- From: server-install-and-running-1 / The off-site backup's state, schedule and run now
- Here: The NAS's footage goes to the cloud backup every night
- From says: "for every project ticked for off-site backup, its 1080p proxies, audio, stills, graphics and project files, plus every Resolve project" (section "The NAS copies the studio's work off site every night", which the leaning behaviour belongs to)
- Here says: "The cloud backup of the NAS's footage runs every night and sends only new and changed files."
- Settled by: the owner must say: does the nightly off-site copy carry the camera originals on the NAS, or only the proxies, sound, stills, graphics and project files of projects ticked for it?
- Fix: whichever he says, this piece's heading and sentence should name exactly what goes (its own "cloud proxy" badge and "No cloud proxy" filter already assume proxies only).

### F10: sync-2's "Project for new footage" leans on footage being dropped in and filed here, and this piece has no such drop or choice
- Kind: missing
- From: sync-2 / A computer or a person can have a chosen project that new footage lands in
- Here: nowhere
- From says: "Each computer, or a person as a whole, can have a chosen project that new footage dropped in on it lands in."
- Here says: nothing (footage is placed by calendar events, title rules, the roster and hand assignment; no computer's or person's chosen project is used anywhere)
- Settled by: the owner must say: when footage is dropped in on a computer that has a chosen project, what puts it in that project, and does the Footage Sorter use that choice when it suggests or files footage from that computer?
- Fix: either this piece says how the Sorter uses a computer's chosen project (for example as a suggestion for clips with no calendar match), or sync-2 points its join at the piece that really owns dropping footage in.
