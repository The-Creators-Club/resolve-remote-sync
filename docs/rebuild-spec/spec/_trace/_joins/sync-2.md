# Joins aimed at sync-2

## Checked

- J1 | F1, F2
- J2 | F3
- J3 | F4
- J4 | F5
- J5 | F6
- J6 | fine
- J7 | F7
- J8 | F8
- J9 | F9
- J10 | fine
- J11 | fine
- J12 | F10
- J13 | fine
- J14 | F11
- J15 | F3

## Findings

### F1: The dashboard draws the computer's reason sentence as a red fault, but sync-2's list of reasons includes information sentences that are never a fault
- Kind: contradiction
- From: dashboard-1 / Each computer leads with one headline
- Here: Saying truthfully what the sync is doing / Each computer says in one sentence why it is not syncing, and since when
- From says: "1. A named fault, red: the computer's own sentence saying why it is not syncing (see Sync: Saying truthfully what the sync is doing)"
- Here says: "| nothing is ticked (information, never a fault) | "Nothing ticked for this computer" |" and "| the project is upload only here (information) | "Nothing to download: this project is upload-only on this computer" |"
- Settled by: DSH-012 (ruling): "A computer with nothing ticked leads with a neutral line and is never an error, warning, alert, blocked state, open issue or expected syncer, even when quiet."
- Fix: dashboard-1 should say that only the fault reasons of sync-2's list take headline slot 1 in red, and the two information reasons (nothing ticked, upload only here) take the muted information slot 5.

### F2: The dashboard's "cannot sign in" reason is not among the computer's reasons for not syncing
- Kind: missing
- From: dashboard-1 / Each computer leads with one headline
- Here: nowhere (the reason table under "Each computer says in one sentence why it is not syncing, and since when" has only "nobody is signed in")
- From says: "and "cannot sign in" with the reason when it is running but cannot prove who it belongs to"
- Here says: nothing
- Settled by: the owner must say: when a computer is running but the server turns it away, is that given as one of its reasons for not syncing, in the same words in the app and on the dashboard?
- Fix: sync-2 should add a row for a computer that is running but turned away (cannot sign in, or its account suspended or removed), with its sentence, in its place in the order; or dashboard-1 should say this headline is the dashboard's own and not the computer's sentence.

### F3: Who a new computer belongs to: the person who signed in on it, or the editor an admin chooses when approving it
- Kind: contradiction
- From: editor-app / The finish page says whether the computer is ready, and what happens next (and sync-1 / Each computer has its own sync plan)
- Here: Computers joining and changing / An admin approves a new computer and ties it to an editor; A computer belongs to a person only once it is tied to a known editor
- From says: "It says the app is installed and signed in as the editor, that nothing syncs until the admin approves this computer, and that the computer is already waiting on the dashboard for that approval with the editor's name"
- Here says: "An admin approves it and ties it to an editor by choosing that editor; the computer is named after the editor so that it is matched to them" and "A computer is linked to a person only when it has been tied to an editor the dashboard knows"
- Settled by: the owner must say: when an editor signs in on a new computer, is it theirs at once (as accounts-privacy-legal says: "An editor's computer belongs to the person who signed in on it ... Nothing else is needed: no code passed to an admin, no approval"), with the admin's approval only letting files start to move, or is it nobody's until an admin approves it and picks the editor?
- Fix: sync-2 should say the computer already belongs to the person who signed in and the admin's approval only lets its transfers start (dropping "ties it to an editor by choosing", "named after the editor" and "belonging to nobody"), unless the owner answers otherwise, in which case accounts-privacy-legal and editor-app change instead.

### F4: The menu's sync line sends the editor to Settings to resume downloads, but the menu prompt is the one place to do it
- Kind: contradiction
- From: editor-app / The menu holds about ten everyday lines
- Here: Saying truthfully what the sync is doing / The app's menu says in one phrase what syncing is doing now
- From says: ""► Resume downloads…" after downloading stopped itself as a safety measure or because the sync drive was nearly full: the one place in the app where downloads are started again"
- Here says: "2. Downloading stopped itself as a safety measure: "Sync: downloading stopped (see Settings)"."
- Settled by: the owner must say: when downloading has stopped itself, does the editor start it again from the app's menu, from its settings window, or from either?
- Fix: sync-2 should change "(see Settings)" to point at the menu's "► Resume downloads…" line, unless the owner says the settings window holds it, in which case editor-app drops "the one place in the app".

### F5: sync-2 promises syncing is always brought back, but the editor can switch automatic restarts off
- Kind: contradiction
- From: editor-app / The app keeps its own work going when part of it stops
- Here: Saying truthfully what the sync is doing / Syncing comes back by itself when it stops running
- From says: "By hand: the editor turns automatic recovery off in the app's settings; the status then says "... it is not being restarted: automatic restarts are switched off on this computer"."
- Here says: "Syncing on a computer that dies, for whatever reason and at whatever time, is brought back within a minute or two"
- Settled by: the owner must say: may an editor switch off the app bringing its own syncing back by itself when it stops?
- Fix: sync-2 should add "unless the editor has switched automatic restarts off on that computer (see The app on each editor's computer)", and say the computer then shows as stopped with that reason; or editor-app drops the setting if the owner says no.

### F6: The wrong-clock warning has two sentences, and one says sync will not work while the other says a wrong clock never stops syncing
- Kind: contradiction
- From: editor-app / The editor is told when the dashboard is not hearing from the computer, and when the clock is wrong
- Here: Clocks and file age / Each computer's clock is measured against the server's and a gap is shown
- From says: "When this computer's clock is 60 seconds or more off the server's: "⚠ This computer's clock is <how far ahead or behind> the server's. Sync will not work correctly until it is fixed""
- Here says: "A difference of more than 60 seconds is shown ... "This computer's clock is <N ahead of/behind> the server's. Turn on setting the time automatically." ... so a wrong clock never stops anything from syncing."
- Settled by: SYN-122 (given, weaker): "a gap over a minute is shown to the editor and admin, and no age rule trusts a computer's clock alone."
- Fix: editor-app should use sync-2's sentence and threshold ("more than 60 seconds", "Turn on setting the time automatically.") and drop "Sync will not work correctly until it is fixed".

### F7: An upload-only project's empty folders: sync-2 says they never come down, the owner said they do
- Kind: contradiction
- From: proxies-and-file-moves / A new project gets the studio's folder template without disturbing what is there (and sync-1 / Each computer has its own sync plan: "upload only (every file goes up and only the project's empty folders come down)")
- Here: Project folders on an editor's computer / A ticked project's folder layout is made on the editor's computer, empty folders included
- From says: "See Sync: Project folders on an editor's computer."
- Here says: "It never happens for an upload-only project, and never while the sync drive is missing"
- Settled by: DECISIONS.md page 2, ANSWERED 2026-11-24, item 2: "A project ticked "upload only" DOES bring its empty folder structure down, so the editor sees where originals go. Nothing else comes down."
- Fix: sync-2 should say the folder layout, empty folders included, is made for upload-only projects too (and nothing else comes down for them), keeping "never while the sync drive is missing".

### F8: sync-2 fixes footage to the private network, while the owner requires the way footage travels to be chosen by measurement
- Kind: contradiction
- From: server-install-and-running-2 / The dashboard is reached only through the studio's private network
- Here: Speed and routes / Footage travels only over the studio's own private network
- From says: "Which way footage itself travels between the NAS and an editor's computer far from the studio is chosen from measurements of real transfers (see Sync: Speed and routes), and nothing here rules a way in or out."
- Here says: "Footage and project files move only over the studio's own private and local network, never through outside relay services" (and nowhere says the way is chosen by measurement)
- Settled by: OWNER_REQUIREMENTS.md section 1: "Before the way footage travels is settled, every candidate way of moving it is measured for real, not assumed"; and decisions/page-05-sync-2.md, 5.2 held back: "the fastest way to a far-off computer may turn out to run through an outside service, which 5.2's recommendation would forbid. Put back to him before it is applied."
- Fix: sync-2 should state that the way footage travels is chosen from the measurements OWNER_REQUIREMENTS describes, and hold "only over the studio's own private network" as an open question (sync-2-Q2) rather than a rule.

### F9: sync-1 has the app on the computer say whether it is safe to close; sync-2 shows it only on the dashboard
- Kind: missing
- From: sync-1 / The editor can see whether it is safe to close the laptop
- Here: What is owed / Every editor is told whether it is safe to shut down or unplug their computer
- From says: "The app shows one line saying whether it is safe to close this computer"
- Here says: "Ways in: on the overview, beside what is moving now, and at the head of the sync list on the overview and on a person's own view of their computers." and "(the dashboard cannot know which computer the browser is on)"
- Settled by: the owner must say: does the app on the editor's own computer show the safe-to-close line, or only the dashboard? (SYN-099, situation, weaker, says only "The editor sees one line saying whether it is safe to close".)
- Fix: sync-2 should add the app as a way in, with the wording it uses there for this computer, if the owner says the app shows it; otherwise sync-1 changes "The app shows" to the dashboard.

### F10: Files dated in the future: sync-1 says they will not upload, sync-2 says they upload like any other
- Kind: contradiction
- From: sync-1 / The editor is told about files that will never upload because of a name clash or a wrong clock
- Here: Clocks and file age / Files dated in the future are shown to the editor until their date is fixed (and A file is sent only once it has stopped changing)
- From says: ""⚠ N files are dated in the future, so they will NOT upload (first: <name>, dated YYYY-MM-DD). ... One a few hours ahead uploads by itself once that time passes."
- Here says: "They upload like any other file, and the list stays until the dates are put right." and "A file whose date is in the future uploads like any other once it has stopped changing."
- Settled by: SYN-124 (situation, weaker): "Future-dated files upload like any other, and the editor sees which file and date are wrong until they are fixed."
- Fix: sync-1 should reword the future-dated warning so it says the files do upload and only their dates are wrong, matching sync-2.

### F11: Conflict copies: sync-1 has the admin see each one with its path, sync-2 shows up to 20 examples
- Kind: contradiction
- From: sync-1 / Files edited on two computers at once are both kept
- Here: Saying truthfully what the sync is doing / A file changed in two places at once keeps both versions
- From says: "the admin sees each such file with its path on the computer's row, and how many the computer holds"
- Here says: "The product counts the conflict copies, shows the count and up to 20 examples on the dashboard"
- Settled by: SYN-063 (situation, weaker): "Conflict copies of any file type are found and shown to the editor and admin with their paths"; it sets no limit, so the owner must say whether past 20 every path is still shown.
- Fix: sync-1 should say the admin sees the count and up to 20 of the files with their paths (marked as cut when there are more), matching sync-2, unless the owner wants every path shown, in which case sync-2 drops the limit.
