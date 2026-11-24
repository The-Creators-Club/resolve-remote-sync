# Joins aimed at fleet-jobs

## Checked

- J1 | fine
- J2 | F16
- J3 | F17
- J4 | F4, F5
- J5 | F1, F2, F3
- J6 | fine
- J7 | F12
- J8 | F8, F9, F10
- J9 | F13
- J10 | fine
- J11 | fine
- J12 | F14
- J13 | fine
- J14 | F15
- J15 | F10, F11
- J16 | F1, F2
- J17 | F1, F2
- J18 | fine
- J19 | F3, F6
- J20 | F7
- J21 | fine
- J22 | F10

## Findings

### F1: b-roll and music drops let the person who dropped them skip the wait, pause, and run while someone works; fleet-jobs allows the wait to be skipped only by lending at the computer or by an admin
- Kind: contradiction
- From: broll / Describing keeps the computer it runs on usable; music / A person chooses whether their drop is analysed now or while they are away; music / An editor sees music analysis on their computer while it is doing it
- Here: The person at a computer can lend it to shared work for a while; An admin can start waiting work now, on a chosen computer
- From says: "\"Start now\", from the page or from the app on that computer, makes a waiting drop work at once until it ends or is paused" and "\"Foreground\" means at once, while they work, using one processor core and not the graphics card" and "While describing runs on a computer someone is working at, it stays under the site's share of that computer's capacity"
- Here says: "Ways in: from the app on that computer only. Nothing on the dashboard lends a computer." and "Who: an admin." (start now), with no per-drop "Foreground", pause, or share of capacity anywhere
- Settled by: decision page 17.7 (ANSWERED 2026-11-24, recommendation A): "the same pause, resume, start now and cancel exist on the music page and in the app on the computer doing the work"; for "Foreground" and the 60% share the owner must say: may a person dropping b-roll or music have it analysed on their own computer at once while they keep working there?
- Fix: fleet-jobs should name the dropper's start now, pause, resume and cancel of an analysis drop (from the page and from the app) as a further way past the wait and say how much of a working computer such work may take, or broll and music drop those controls if the owner rules otherwise.

### F2: when the person comes back, b-roll and music analysis pause after the current step, but fleet-jobs finishes the running piece
- Kind: contradiction
- From: broll / Describing keeps the computer it runs on usable; music / A person chooses whether their drop is analysed now or while they are away; music / An editor sees music analysis on their computer while it is doing it
- Here: Work already running is finished when the person comes back
- From says: "The conditions are checked again between every step of every clip, so a person coming back loses at most the step in progress" and "Indexing music… D of T (stops when you're back)"
- Here says: "When someone starts using the keyboard or mouse, or opens Resolve, the computer takes no new shared work, but finishes the piece it is running."
- Settled by: the owner must say: when the person comes back to a computer analysing their b-roll or music, does it stop after the current step or finish the piece it is on? (JOB-003, a situation lesson and weaker, only forbids killing a long job.)
- Fix: fleet-jobs should state the analysis kinds' pause-after-the-step rule as an exception, or broll and music should drop "(stops when you're back)" and the per-step check.

### F3: which goes first on one computer, its own proxies or b-roll describing, is said both ways
- Kind: contradiction
- From: broll / Describing keeps the computer it runs on usable (also proxies-and-file-moves / What proxy making on a computer is doing, in one line)
- Here: A computer's own heavy work comes first
- From says: "Making proxies on that computer waits while describing runs, and says so (\"indexing b-roll first\")."
- Here says: "A computer's own heavy work for its own editor (making proxies for it, see Proxies and file moves: Making proxies on editors' computers) comes before shared work."
- Settled by: the owner must say: when a computer has both its own proxies to make and b-roll to describe, which does it do first?
- Fix: one of fleet-jobs (own work first) or broll and proxies-and-file-moves ("indexing b-roll first") changes to match the owner's answer.

### F4: b-roll describing starts with the computer the clips were dropped from, but the ranking has no such preference
- Kind: missing
- From: broll / An editor adds footage by dropping it on the b-roll page or choosing it on their own computer
- Here: The best-placed able computer is asked first
- From says: "That work is done on a computer of the studio's that is able and free (see Work shared out across the computers), starting with the computer the clips were dropped from when it is able"
- Here says: nothing (the ranking lists transcribing, preview copies, sound and waveforms, and card and drive work; analysing b-roll or music has no suitability rule)
- Settled by: decision page 16.1 (ANSWERED 2026-11-24, recommendation B): "the work is done on a computer of the studio's that is able and free, the dropper's own first when it can, otherwise another"
- Fix: fleet-jobs should add to the ranking that analysing b-roll prefers the computer the clips were dropped from.

### F5: clips indexed "in place" lie only on the dropper's computer, but fleet-jobs only shares work on files in the studio's shared folders
- Kind: contradiction
- From: broll / An editor adds footage by dropping it on the b-roll page or choosing it on their own computer
- Here: Work names its files inside the studio's shared folders; Media for Timeline Cards is made by the studio's computers first, and by the server when none can
- From says: "clips chosen this way are worked on where they lie, never copied through the browser, and are marked \"indexed in place\""
- Here says: "A path that climbs out of its folder, a full path, an empty path, or one with unprintable characters fails the piece with a sentence saying so." and "Work is shared out only for files in the studio's shared folders; anything else is made by the server."
- Settled by: the owner must say: when an editor indexes clips that lie only on their own computer, is that work always done by that computer?
- Fix: fleet-jobs should say how a piece of work on files that lie on one computer only is named and that it is meant for that computer, or broll should drop indexing in place.

### F6: proxies-and-file-moves calls proxy making shared work decided like all others; fleet-jobs calls it the computer's own work and has no proxy kind
- Kind: contradiction
- From: proxies-and-file-moves / Clips with no proxy are found and their proxies are made
- Here: A computer's own heavy work comes first; The kinds of shared work and what each needs
- From says: "Making a proxy is heavy work of the kind the studio's computers share: which able and free computer makes a given proxy is decided as for all such work (see Work shared out across the computers: Choosing who runs what)"
- Here says: "A computer's own heavy work for its own editor (making proxies for it, see Proxies and file moves: Making proxies on editors' computers) comes before shared work." (the kinds table has no editing-proxy kind)
- Settled by: JOB-013 (ruling) says the editor can send a clip's proxy to a chosen computer, so proxies are not only the computer's own work; whether they are otherwise shared out automatically, the owner must say: is a missing proxy always made by the computer that holds the original, or by whichever able computer is free?
- Fix: either fleet-jobs adds editing proxies as a shared kind (with its needs, limit, tries and tick) and drops "own heavy work", or proxies-and-file-moves drops "decided as for all such work" and keeps proxies local except the editor's pick.

### F7: proxy making keeps its own quiet time and its own Resolve hold-back, with a different default and different people allowed to change them
- Kind: contradiction
- From: proxies-and-file-moves / Proxies are made only while nobody is at the computer
- Here: A computer takes shared work only while nobody is using it
- From says: "Setting: Wait this long without input before making proxies. ... Default: 5 minutes. Who: an editor for their own computer, or an admin." and (Proxy making gives way to Resolve) "Setting: Make no proxies while Resolve is open. ... Default: off."
- Here says: "Setting: Quiet time before shared work. ... Who: the computer's own person, on the computer." and "Setting: Hold shared work back while Resolve is open. ... Default: on."
- Settled by: decision page 16.7 (ANSWERED 2026-11-24, recommendation A): "one quiet time and one Resolve hold-back per computer, the ones shared work already has, used by describing too"
- Fix: proxies-and-file-moves should drop its two settings and use the computer's quiet time and Resolve hold-back from fleet-jobs.

### F8: transcription runs on a processor when no computer has a usable graphics card or a person picks one; fleet-jobs never runs it without a graphics card and lets only an admin pick
- Kind: contradiction
- From: cards-footage-in / What transcribing needs and what a person sees while it runs
- Here: The kinds of shared work and what each needs; Media for Timeline Cards is made by the studio's computers first, and by the server when none can; An admin can start waiting work now, on a chosen computer
- From says: "Only when no computer of the studio's has one, or when a person picks a computer without one, does it run on that computer's processor, and the person is told the reason and that it will be much slower."
- Here says: "a graphics card with at least the memory the work states (6 GB unless the work says otherwise)" and "Transcription is never taken over by the server: it needs a graphics card." and start now "Who: an admin."
- Settled by: decision page 22.4 (ANSWERED 2026-11-24, recommendation A): "wait for a computer with a usable card; run on a processor only when the studio has no such computer, or when a person picks one"
- Fix: fleet-jobs should let transcription run on a processor when no computer in the studio has a usable graphics card or a person picks one, say who may pick, and tell the person it will be much slower.

### F9: a person watching a transcription sees progress at least every 3 seconds, but fleet-jobs only promises it moves every 30 seconds
- Kind: contradiction
- From: cards-footage-in / What transcribing needs and what a person sees while it runs
- Here: Progress is shown as it goes, never as a made-up zero
- From says: "While a recording is transcribed the person sees, at least every 3 seconds: which recording of how many, the percentage, minutes done of the total, lines so far, the language and the time left."
- Here says: "Progress moves at least every 30 seconds while work runs; a long transcription shows its progress as it goes (also whenever it has moved by 1%)."
- Settled by: the owner must say: how often must a person watching a transcription on another computer see its progress move?
- Fix: one of the two figures changes so that both pieces give the same promise, and fleet-jobs adds lines so far, the language and time left if the 3-second view is kept.

### F10: other pieces send work to the shared queue that is not one of fleet-jobs' kinds
- Kind: missing
- From: cards-footage-in / Clips dropped in become an interview ready to cut; footage-sorter-and-camera-cards-2 / Every sound recording is listened to for names and introductions; youtube / Every clip lands as a single MP4 file with H.264 picture and AAC sound at a constant frame rate
- Here: The kinds of shared work and what each needs
- From says: "The heavy work (lining up, transcribing, previews) is done on a computer of the studio's that is able and free" and "Every sound recording that arrives is listened to on its own, as heavy work on one of the studio's computers able and free" and "Converting is heavy work, done on a computer of the studio's that is able and free"
- Here says: nothing (the table lists transcribing, preview copies, sound, waveforms, b-roll and music analysis, card copies, drive copies and drive reads only)
- Settled by: OWNER_REQUIREMENTS section 2: "sharing heavy work across the studio's computers (the second also with a setting per kind of work)"
- Fix: fleet-jobs should add kinds (with who asks, what they need, their tick, limit, tries and quiet time) for lining clips up by their sound, listening to Footage Sorter recordings for names, and converting YouTube downloads, or each of those pieces should say the work is not shared.

### F11: the Footage Sorter transcribes recordings, but transcription exists only while Timeline Cards is on and only for an episodes folder
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / Every sound recording is listened to for names and introductions
- Here: The kinds of shared work and what each needs; A computer transcribes an episode's folder
- From says: "Every recording is transcribed in full, with its language identified and speakers told apart, and camera clips with at least 20 seconds of sound are transcribed too."
- Here says: "When Timeline Cards is off: the four Timeline Cards kinds do not exist, and no computer shows a tick for them." and "A transcription names a folder in the Timeline Cards episodes and its episode"
- Settled by: the owner must say: with Timeline Cards off and the Footage Sorter on, are the Sorter's recordings still transcribed on the studio's computers?
- Fix: fleet-jobs should let transcription be asked for by the Footage Sorter, on its own folders, and exist while either part is on, or the Sorter should say it listens only when Timeline Cards is on.

### F12: playing a clip whose sound is not ready moves its preparation to the front, but fleet-jobs orders waiting work oldest first
- Kind: missing
- From: cards-editor-2 / Every clip is made ready to play without anyone asking
- Here: Waiting work is taken in a fair order
- From says: "Playing a clip that is not ready yet moves its preparation to the front, rather than starting more work at once"
- Here says: "Waiting work is taken oldest first, except that sound and waveforms go ahead of preview copies, so an editor can listen to a clip before they can watch it. Work an admin started now goes first."
- Settled by: the owner must say: when an editor plays a clip whose sound is not made yet, does its making go ahead of all other waiting work?
- Fix: fleet-jobs should add that playing a clip in Timeline Cards puts that clip's waiting media first, or cards-editor-2 should drop the sentence.

### F13: a lent computer is "lending until" on one page and "volunteering until" on the other, and a piece's warning exists only in dashboard-1
- Kind: differs
- From: dashboard-1 / Each computer shows the work in progress on it
- Here: Each computer's shared-work state on the dashboard; The person at a computer can lend it to shared work for a while
- From says: "\"lending until <time>\": somebody at that computer chose to take shared work now" and "\"<kind of work>: N%\" ... marked as a warning when the work reported one (see Work shared out across the computers: Progress)"
- Here says: "\"volunteering until <time>\" while its person has lent it" and "the work running now: \"<kind> on <file>, <n>%\"" (no warning a piece can report)
- Settled by: the owner must say: which words does the dashboard use for a computer its person has lent to shared work?
- Fix: dashboard-1 and fleet-jobs should use one phrase and one row form, and fleet-jobs should say what a piece's warning is or dashboard-1 should drop it.

### F14: the app's menu line while an admin-started piece runs is a different sentence in each piece
- Kind: contradiction
- From: editor-app / The menu carries a line for each piece of work under way
- Here: A computer says in one sentence whether it is taking shared work and why not
- From says: "\"CC Sync is <transcribing|converting|running a job> for the studio while you work because <reason>\", only when an admin has sent a piece of work to this computer whatever it is doing"
- Here says: "The computer's state is one sentence, shown in its menu and its settings window and on the dashboard" with "\"Your admin asked this computer to run a fleet job now.\" when the admin started it now"
- Settled by: the owner must say: what does the app's menu say while a piece of work an admin started now runs on the computer, and is there a line while the person has lent it?
- Fix: editor-app and fleet-jobs should give the one same sentence for this state.

### F15: a card copy starts at once for anyone, even offline, but fleet-jobs holds it behind fleet settings, other work and the connection, and lets only an admin start it now
- Kind: contradiction
- From: footage-sorter-and-camera-cards-1 / There is one card copy, and it starts at once on the computer the card is in
- Here: An admin can start waiting work now, on a chosen computer; A short loss of the server or the network does not cost a running job
- From says: "It starts at once, whether or not someone is using that computer, with no wait for the computer to be free." and "Who: anyone signed in, and the editor at the computer the card is in, even with no network."
- Here says: "It still waits ... while the computer is already doing shared work or its own heavy work, while shared work is off on it, and while that kind is unticked on it." and "Who: an admin." and "While the server cannot be reached, a computer takes no new work."
- Settled by: the owner must say: does a card copy start at once on the computer the card is in even when that computer is doing other work, has shared work or card copies switched off, or cannot reach the server?
- Fix: fleet-jobs should say card copies are started by whoever starts them in the Sorter or field backup and which holds they skip (or that they are not shared work at all), or the Sorter should state those holds.

### F16: a suspended person's computer is refused for shared work everywhere, yet fleet-jobs lets it hand in a finished piece
- Kind: contradiction
- From: accounts-privacy-legal / Stopping a person takes effect everywhere at once
- Here: A computer whose access is refused says so and takes no work
- From says: "every computer of theirs is refused wherever it reaches the server (reporting, signing in, reading its plan, moving files, shared work, ...)"
- Here says: "A piece it had already finished can still be handed in."
- Settled by: JOB-026 (situation, weaker than a ruling): "On suspension a running job stops within one check-in, a finished one can still be handed in, and no new work is taken under that account."
- Fix: accounts-privacy-legal should except handing in a piece of shared work already finished from the refusal.

### F17: asking a computer from the dashboard to change its shared-work settings is described in full in both pieces
- Kind: said twice
- From: accounts-privacy-legal / A person or an admin asks one of the person's computers to change its settings
- Here: An admin or the computer's owner can ask a computer from the dashboard to change its shared-work settings
- From says: "The request waits until the computer next checks in, and is shown as waiting until the computer answers \"applied\" or \"refused\"; a request not answered within 14 days expires, and says so."
- Here says: "One ask per computer waits at a time. ... \"<computer> was not in touch for 14 days, so the request was dropped.\""
- Settled by: OWNER_REQUIREMENTS section 1: "One way to do each thing: one way of telling a computer something, one place a setting comes from"
- Fix: accounts-privacy-legal should keep only that the account page is a way in and point to fleet-jobs for the ask, its states and its expiry.
