# Joins aimed at dashboard-1

## Checked

- J1 | fine
- J2 | F1
- J3 | fine
- J4 | fine
- J5 | F2
- J6 | fine
- J7 | F3
- J8 | F4
- J9 | F5, F6
- J10 | fine
- J11 | F7
- J12 | F8
- J13 | F9
- J14 | fine
- J15 | F10
- J16 | fine
- J17 | fine
- J18 | fine
- J19 | fine
- J20 | F11
- J21 | F12
- J22 | F13
- J23 | fine
- J24 | F14
- J25 | F15
- J26 | fine
- J27 | F16
- J28 | F17
- J29 | F18
- J30 | F19
- J31 | F20
- J32 | F21
- J33 | F22
- J34 | F22
- J35 | fine
- J36 | F23
- J37 | fine
- J38 | fine
- J39 | F24
- J40 | fine
- J41 | F25
- J42 | fine

## Findings

### F1: A computer that withholds information still gets notes and a "could not check" issue on the dashboard
- Kind: missing
- From: accounts-privacy-legal / Withheld information reads as not reported, never as a fault
- Here: Each computer's issues are listed worst first, each explained
- From says: "It never changes any colour, headline, note or alert. Problems that depend on a withheld kind (footage on one computer only, project folders outside the tree, a moved project folder) are not raised for that computer, and one already open is closed without a message."
- Here says: "When the open project cannot be known it reads "could not check", never fine." (and the stray-folder, moved-folder and clips-only-here issues and notes carry no exception for a withheld kind)
- Settled by: ACC-048 (situation, weaker): "Withheld categories still run, read as withheld rather than empty or zero"; the accounts piece's text is the explicit rule
- Fix: dashboard-1 should say that issues, notes and problems depending on a withheld kind are not raised for that computer, and that a withheld open project shows the "not reported" tag instead of "could not check".

### F2: Closing an episode and who is in it are leaned on in the dashboard's Projects, which does not hold the episode list
- Kind: missing
- From: cards-editor-4 / Every signed-in person sees who is working in which episode
- Here: nowhere
- From says: "Closing an episode asks first, naming who was last in it and when: "Close <episode>? <who> was last in N min ago. ...""
- Here says: nothing (the episode list is in cards-editor-5, "The Timeline Cards page lists every episode in its folders", which shows "who is in it now" but has no way to close an episode)
- Settled by: the owner must say: can a person close an open episode from the list of episodes, and if so where is that button?
- Fix: cards-editor-4 should point at cards-editor-5's Timeline Cards page instead of the dashboard's Projects, and cards-editor-5 should carry the close action and its question if the owner keeps it.

### F3: The Timeline Cards link's "stopped" means "until the app is restarted" here, but is restarted within a minute there, and the state words differ
- Kind: contradiction
- From: cards-to-resolve-and-exports / Each computer shows whether its Resolve is taking part and if not why
- Here: Each computer shows the work in progress on it
- From says: "refused ... stopped ... credential refused ... unreachable ... running ... Anything shown stopped is restarted within about a minute."
- Here says: ""cards not running" with the reason in plain words (stopped until the app is restarted, refused to start, signed out, or cannot reach the dashboard"
- Settled by: CRX-085 (situation, weaker): "Green needs a successful contact in the last 50 seconds, else it names stopped, refused or unreachable; anything shown stopped is restarted within a minute."
- Fix: dashboard-1 should drop "until the app is restarted" and use the same five state words (refused, stopped, credential refused, unreachable, running) as cards-to-resolve-and-exports.

### F4: The one list of open problems is described in both dashboard pieces with different words for its severities and its all-clear line
- Kind: contradiction
- From: dashboard-2 / An admin sees every problem open now and every kind of check
- Here: Everything the server knows is wrong is in one list; What the server checks, and whether each check ran
- From says: "or "Nothing is wrong that this server can see. All N checks ran and found nothing."; every kind of check, with its severity ("problem" or "to look at")"
- Here says: "its severity: error, warning or information" ... "N needs attention", "N worth a look", "N not checked" ... "All clear. N of M checks ran and found nothing wrong."
- Settled by: OWNER_REQUIREMENTS 1: "One way to do each thing"; for the words, the owner must say: what does an admin read when no problem is open, and what are the levels of a problem called?
- Fix: dashboard-2 should point to dashboard-1's list for the open problems and checks and keep only what is its own (the alert settings and the report preview), using dashboard-1's severity names and all-clear line, or both should adopt the owner's chosen words.

### F5: How soon the server's file counts show differs: five minutes here, about fifteen in dashboard-2
- Kind: contradiction
- From: dashboard-2 / The studio's picture on the dashboard stays fresh on its own
- Here: How fresh the dashboard's picture is; The server counts what each project holds on the NAS
- From says: "How many video files a changed project holds on the NAS | about 15 minutes (a brand-new project is counted within seconds of being found)"
- Here says: "a file that reached the server showing as on the server | within five minutes" and "A newly found project is counted first, within a minute or two."
- Settled by: DSH-051 (situation, weaker): "A file that reached the server shows as on the server within five minutes, at 500 projects as at 5."
- Fix: dashboard-2's table should say within five minutes, and both pieces should give one figure for a newly found project's first count.

### F6: Returning to a page where one was is described in full in both dashboard pieces
- Kind: said twice
- From: dashboard-2 / Returning to a page puts the person back where they were
- Here: Every page remembers where the person was on it; A link can lead to any place on a page
- From says: "Returning to a page restores where it was scrolled and which sections were open, even when parts of it arrive a moment late; a remembered position is forgotten after 8 hours."
- Here says: "the browser remembers the scroll position, which fold-out sections were open ... and is ignored after 8 hours."
- Settled by: OWNER_REQUIREMENTS 1: "One way to do each thing"
- Fix: dashboard-2 should point to dashboard-1's two behaviours instead of restating them.

### F7: The editor's diagnostics list the open Resolve project and idle time with no exception for a withheld kind
- Kind: contradiction
- From: editor-app / The editor sends the admin a full description of the computer with one button
- Here: A computer withholds kinds of information by choice
- From says: "Resolve's open project and whether the app can reach Resolve ... how long it has been idle"
- Here says: "Those kinds are never shown, never kept, and never present in the computer's diagnostics either."
- Settled by: ACC-047 (ruling): "Each category can be withheld per computer or per site; sync still runs, and the server drops withheld fields on arrival and deletes what it held."
- Fix: editor-app should say the description leaves out every kind this computer or the studio withholds, naming it as not reported.

### F8: "Work is waiting and nobody is taking it" is not among the problems the server finds
- Kind: missing
- From: fleet-jobs / Admins are warned when work waits and nobody can take it
- Here: The kinds of problem the server finds and where each leads
- From says: "An admin is warned, "work is waiting and nobody is taking it", when the oldest waiting piece has waited 6 hours or more"
- Here says: nothing
- Settled by: the owner must say: is work that nobody can take one of the problems an admin sees on the Overview, and where does its link lead?
- Fix: dashboard-1's table of kinds should gain a row for it (warning, leading to the list of shared work).

### F9: A computer that cannot report its camera cards is said to be shown on the per-computer view, which says nothing of cards
- Kind: missing
- From: footage-sorter-and-camera-cards-1 / Every card put in a reader appears within seconds, with no click
- Here: nowhere
- From says: (join) "a computer that cannot report its cards is also shown on the per-computer view."
- Here says: nothing
- Settled by: the owner must say: when a computer that should watch for camera cards cannot tell the studio about them, does the per-computer view say so?
- Fix: if yes, dashboard-1 should add a note to a computer's row for card watching that is not working (shown only when the Footage Sorter is on), and the Footage Sorter piece should say it in its behaviour text, not only in its join.

### F10: A part that cannot load leaves the menu in the Footage Sorter's piece but keeps its place in the menu here
- Kind: contradiction
- From: footage-sorter-and-camera-cards-3 / The Sorter waits while it gets ready after the server starts
- Here: Each part's state is shown on the Overview
- From says: "If its records cannot be loaded, the Sorter leaves the menu, and the overview's state of the parts says "the footage sorter could not load its data (<error>)"."
- Here says: "A part that is switched on but not working, or working badly, keeps its place in the menu; opening it shows a page saying in plain words that it is not working right now, why, and that admins have been told."
- Settled by: the owner must say: when a switched-on part is broken, does its menu entry stay and open a page saying why, or disappear?
- Fix: the Footage Sorter piece should follow dashboard-1's rule (keep the entry, show the "not working" page) unless the owner rules otherwise.

### F11: The warning about hand moves that could not be followed "stays until dismissed", but here problems close themselves and a dismiss only hides
- Kind: contradiction
- From: proxies-and-file-moves / Every hand move is recognised or the admin is told how many were not
- Here: Problems close themselves when they are over; Files moved by hand on the NAS are reported as they are followed
- From says: "the admin is shown a serious problem saying exactly how many were not followed, which stays until dismissed."
- Here says: "Every problem has a rule that closes it" ... "Dismissing asks "Dismiss this? It is only hidden. If the server finds the same problem again it comes straight back, so dismissing it is not a fix.""
- Settled by: the owner must say: does the warning that some hand moves were not followed stay until an admin dismisses it, or close by itself after a day like other one-off errors?
- Fix: whichever the owner picks, dashboard-1's closing rules should name this problem's rule and proxies-and-file-moves should say the same.

### F12: The problems about versions not reaching computers are missing from the table of kinds
- Kind: missing
- From: releases-and-updates / The server tells an admin when versions are not reaching computers
- Here: The kinds of problem the server finds and where each leads
- From says: "an update will not install | serious ... a recalled version is still running | serious ... this server cannot check for updates | warning ..." (14 kinds)
- Here says: "The vendor's release feed cannot be reached, a build from it was refused, or a build from it needs the server to be updated first | warning, error, warning | the list of builds" (only these)
- Settled by: the owner must say: are all fourteen version problems shown among the problems on the Overview, and where does each lead?
- Fix: dashboard-1's table should list the version problems with their severities and lead to the versions page or the computer, or say plainly that releases-and-updates holds the full list.

### F13: The answer to "Update now" uses different words here and in releases-and-updates
- Kind: contradiction
- From: releases-and-updates / An admin pushes a version to one computer
- Here: An admin asks one computer to do something and is told when it will happen
- From says: ""on that computer's next check-in, usually within 30 s." ... ", as an offer of a held-back version to this computer alone""
- Here says: ""on that computer's next report, usually within 30 s. It was last heard from <age>"" ... "", as an offer of a build being tried on this computer first""
- Settled by: the owner must say: which sentence does an admin read after pressing "Update now" on a computer, especially for a held-back build?
- Fix: releases-and-updates should use dashboard-1's sentences (or point to them), so one set of words serves every request aimed at one computer.

### F14: "Footage is outside the tree" and "footage on one computer only" are not among the problems the server finds
- Kind: missing
- From: resolve-on-the-editors-computer / Admins are told when footage used in Resolve is outside the shared tree
- Here: The kinds of problem the server finds and where each leads
- From says: ""footage is outside the tree", titled "footage is outside the tree in '<project>'" ... "footage on one computer only in '<first>' and N other projects""
- Here says: nothing (these appear only as a computer's issues: "N clips outside the tree in <project>", "N project(s) with clips only here")
- Settled by: RSV-065 (situation, weaker): "its editor and the dashboard are told, naming project and count"
- Fix: dashboard-1's table should gain both rows (leading to the computer), shown only when the help for the editing program is on.

### F15: Automatic pairing of a Resolve project is "exactly" one project's name here, but folds case, accents, hyphens and the last folder there
- Kind: contradiction
- From: resolve-on-the-editors-computer / A Resolve project is tied to a project in the tree
- Here: A new Resolve project with no folder leads the editor to pick or create one
- From says: "the Resolve name equals, ignoring capitals, accent spelling, and treating hyphens and underscores as spaces, either a project's whole name or the last folder of its path, for exactly one project."
- Here says: "A Resolve project is paired with a project on its own only when its name matches exactly one project's name exactly"
- Settled by: RSV-053 (ruling): "A Resolve project links automatically only when its name exactly matches one project folder's name"; DSH-048 (ruling): "only on an exact name match with one project"
- Fix: both pieces should state one rule: dashboard-1 should allow the folder's own name as RSV-053 says, and resolve-on-the-editors-computer should drop treating hyphens and underscores as spaces, which is looser than an exact match.

### F16: The three private-network problems are not among the problems the server finds
- Kind: missing
- From: server-install-and-running-2 / Admins are warned when the server's private-network link is down, about to expire or not publishing the dashboard
- Here: The kinds of problem the server finds and where each leads
- From says: ""this server's private network connection is down" ... "this server's private network key is about to expire" ... "the dashboard is not published on the private network""
- Here says: nothing
- Settled by: SRV-016 (ruling): the dashboard is "served only over https on the private network", so its loss must be told; where each leads, the owner must say
- Fix: dashboard-1's table should gain the three rows (error), each with where its link leads.

### F17: "Most computers went quiet at the same time" is not among the problems the server finds
- Kind: missing
- From: server-install-and-running-2 / Admins are warned when most computers go quiet at once
- Here: The kinds of problem the server finds and where each leads; A computer quiet for a day or red for an hour is raised as a problem
- From says: "A serious problem, "most computers went quiet at the same time", points the admin at the server and its network rather than at the editors one by one."
- Here says: nothing
- Settled by: the owner must say: when most computers go quiet at once, does the admin see one problem pointing at the server as well as one per silent computer?
- Fix: dashboard-1's table should gain the row (error, leading to the server's own health), and its silent-computer section should say how it sits beside the per-computer problems.

### F18: Nothing on the dashboard lets a person reorder a computer's sync queue
- Kind: missing
- From: sync-1 / Projects ticked on a computer sync one at a time, in the order set for that computer
- Here: Each person's sync queue shows their ticked projects in order
- From says: "An editor or an admin can move a project to the front of one computer's queue, or set any order ... Ways in: from the per-computer view, and from a person's own account page."
- Here says: "The queue shows order and progress only; projects are ticked and unticked on the Projects page."
- Settled by: SYN-004 (ruling): "An editor or admin can move a project to the front of one computer's sync queue from the screen."
- Fix: dashboard-1 should give the sync queue (and the per-computer view) a way to move a project to the front and set any order, for the editor's own computers and an admin's for anyone.

### F19: The refusals when ticking read differently in sync-1, and a person-wide tick skips wired computers there but covers "every computer" here
- Kind: contradiction
- From: sync-1 / The rules every tick and untick follow, wherever it is made
- Here: An editor or an admin ticks a project for a computer
- From says: "("not allowed" otherwise)" ... "unknown project '<slug>'" ... "every computer on this account is wired to the server: they work directly off the NAS and sync nothing, so projects cannot be ticked for them" ... "A tick for the person skips wired computers on its own"
- Here says: ""you can only change your own projects (admins excepted)"" ... ""unknown or inactive project '<name>'"" ... ""this account is wired to the server: it works directly off the NAS and syncs nothing, so projects cannot be ticked for it"" ... "When no single computer is chosen, the tick covers every computer the person has"
- Settled by: the owner must say: which words does a person read when a tick is refused, and does a tick for a whole person silently leave out their wired computers?
- Fix: sync-1 should keep the rules and point to dashboard-1 for the words, and dashboard-1 should say a person-wide tick leaves out wired computers.

### F20: The locked box of a wired computer says two different things
- Kind: contradiction
- From: sync-1 / A wired computer syncs nothing and cannot be ticked
- Here: A tick box always does what it showed
- From says: ""<computer> is wired to the NAS: it works directly off the tree, so a new sync cannot be ticked here""
- Here says: ""<name> is wired to the server: it works directly off the NAS and syncs nothing. Change it in the app on that computer.""
- Settled by: the owner must say: what does the locked tick box of a wired computer say?
- Fix: sync-1 should point to dashboard-1's sentence rather than give its own.

### F21: The warning that proxies may not fit is described in full in both sync-1 and here
- Kind: said twice
- From: sync-1 / Ticking warns when the proxies may not fit
- Here: Ticking warns when the proxies may not fit but never refuses
- From says: ""<project> is <size> of proxies. <computer> has <free> free.[ That is more than will fit.] Sync it there anyway?". Cancel unticks it again; nothing is refused."
- Here says: ""<project> is <size> of proxies. <computer> has <free> free." plus "That is more than will fit." when they are larger than the free space, then "Sync it there anyway?". The tick is never refused."
- Settled by: SYN-084 (situation, weaker): "a tick first shows its size against free space"; OWNER_REQUIREMENTS 1: "One way to do each thing"
- Fix: keep the full rule in one piece (sync-1 carries the person-wide and column variants dashboard-1 lacks) and have the other point to it.

### F22: Free-space colours use a fixed 20 GB floor here and the computer's own floor in sync-1, which also shows a "probably stopped" guess this piece forbids
- Kind: contradiction
- From: sync-1 / The dashboard shows each computer's free space and colours it (and An admin sees each computer's stops and pauses)
- Here: Each computer's free space is shown with a plain verdict
- From says: "The drive is red under 5 percent free or under the computer's own floor (20 GB, or the figure the computer reports) ... A computer below its own floor is shown as having probably stopped downloading, labelled as a guess" and "the free space at which downloads pause"
- Here says: "red under 5% free or under 20 GB free ... A low-space colour is a warning and never a stop: why a computer stopped bringing files down is told only from the reason the computer itself gave."
- Settled by: SYN-085 (situation, weaker): "uses the computer's own floor, never fires when the floor is off, and labels guesses"
- Fix: dashboard-1 should colour against each computer's own floor, show that floor, and either allow the labelled "probably stopped" guess or the owner must rule it out and sync-1 drop it.

### F23: A computer's one sentence is always a red "named fault" here, but a deliberate stop or pause is never a fault in sync-2
- Kind: contradiction
- From: sync-2 / Each computer says in one sentence why it is not syncing, and since when
- Here: Each computer leads with one headline
- From says: "A deliberate stop or pause is shown as what it is, never as a fault" (the sentences include "syncing is paused on this computer" and information lines such as "Nothing to download: this project is upload-only on this computer")
- Here says: "1. A named fault, red: the computer's own sentence saying why it is not syncing"
- Settled by: SYN-107 (situation, weaker): "a deliberate stop is not shown as a problem"
- Fix: dashboard-1 should show the sentence red only for a real fault, and a pause, an admin's stop and the information sentences in a muted colour.

### F24: Approving a computer with no known editor is refused here but allowed (belonging to nobody) in sync-2
- Kind: contradiction
- From: sync-2 / An admin approves a new computer and ties it to an editor
- Here: A new computer is approved under its owner
- From says: "Approving without choosing a known editor leaves the computer belonging to nobody, and the admin is told that the dashboard will then not manage what it receives."
- Here says: "Approving it under a name the dashboard does not know is refused unless the admin ticks CREATE NEW EDITOR"
- Settled by: DSH-066 (situation, weaker): "Approving a computer means choosing its existing owner, prefilled from what it reported; a new person only by explicit choice"
- Fix: sync-2 should drop approving to nobody and say an unknown name is refused unless the admin chooses to create a new editor.

### F25: The per-computer view is said to give each computer's reason for not downloading a YouTube clip, and says nothing of it
- Kind: missing
- From: youtube / The page always says where each job ran and why
- Here: Each computer's issues are listed worst first, each explained
- From says: "The dashboard's per-computer view also states, for any computer that should have downloaded a clip and did not, that computer's reason"
- Here says: nothing (only "youtube clips waiting for resolve: N" and "youtube import gave up")
- Settled by: the owner must say: does a computer's row on the dashboard say why it did not download a YouTube clip it was given?
- Fix: if yes, dashboard-1 should add that note (shown only when YouTube downloads are on); otherwise youtube should drop the sentence.
