# Joins aimed at editor-app

## Checked

- J1 | F1, F2, F3
- J2 | F4
- J3 | F5, F6
- J4 | F7, F8
- J5 | fine
- J6 | fine
- J7 | F9
- J8 | fine
- J9 | F10, F11
- J10 | fine
- J11 | fine
- J12 | F12
- J13 | F13
- J14 | fine
- J15 | fine
- J16 | fine
- J17 | F8
- J18 | fine
- J19 | F14
- J20 | F15
- J21 | F16
- J22 | F17, F18
- J23 | F19, F20
- J24 | fine
- J25 | fine
- J26 | F21
- J27 | fine
- J28 | fine
- J29 | F22, F23
- J30 | F23
- J31 | F24
- J32 | F25
- J33 | F26
- J34 | F27
- J35 | fine
- J36 | fine

## Findings

### F1: Whether a newly signed-in computer must wait for an admin's approval before it syncs
- Kind: contradiction
- From: accounts-privacy-legal / A computer becomes a person's when they sign in on it
- Here: Installing and setting up / The finish page says whether the computer is ready, and what happens next (also Uninstalling / Uninstalling removes the app and every way into the studio's server, never the media)
- From says: "Nothing else is needed: no code passed to an admin, no approval, nothing pasted."
- Here says: "\"DONE: WAITING FOR YOUR ADMIN TO APPROVE THIS COMPUTER\". It says ... that nothing syncs until the admin approves this computer"; and at uninstall "a reinstall is a NEW computer: your admin must approve it again"
- Settled by: the owner must say: does a new editor's computer start syncing as soon as the editor signs in on it, or does it wait for an admin to approve it? (ruling ACC-007, "with no other step", points to no approval; answered page 8.14, "a repair-by-reinstall should not cost an admin's approval", assumes approval exists; sync-2 "An admin approves a new computer and ties it to an editor" also has it)
- Fix: if there is no approval, editor-app drops the "waiting for your admin to approve" finish page and the approval wording at uninstall (and sync-2 its approval step); if there is, accounts-privacy-legal drops "no approval".

### F2: A person's sign-ins capped at 16 computers is a way a computer's sign-in ends that the accounts piece says does not exist
- Kind: contradiction
- From: accounts-privacy-legal / A computer becomes a person's when they sign in on it
- Here: Signing in, the computer's identity and the licence / The editor signs in with the username and password their admin gave them
- From says: "It ends only when an admin withdraws it, when the person's access is stopped or removed, or when the person signs out on that computer"
- Here says: "a person may have at most 16 computers signed in, the least recently used one beyond that being signed out (see Accounts, privacy and the legal paperwork: How a computer proves who it belongs to)"
- Settled by: the owner must say: when a person signs in on a seventeenth computer, is their least recently used computer signed out, or can a person keep any number of computers signed in?
- Fix: if the cap stays, accounts-privacy-legal adds it to its list of how a computer's sign-in ends; otherwise editor-app drops the cap and its pointer.

### F3: The sentence for a computer whose sign-in the server refused differs, and editor-app's sends the editor to the admin
- Kind: contradiction
- From: accounts-privacy-legal / A refused computer is told why, and the admin sees it
- Here: Telling the editor what is wrong / A failed transfer is explained in plain words
- From says: "On the editor's computer a withdrawn sign-in reads \"this computer's sign-in was revoked: sign in again from the CC Sync tray\"."
- Here says: "the server refused this computer's sign-in | \"The server rejected this computer's login. <where to copy diagnostics>.\""
- Settled by: APP-125 (situation, weaker): "A rejected credential tells the editor once, reads differently from \"server unreachable\" everywhere, offers signing in again first"; and editor-app's own rule "an editor is never sent to their admin ... for something one click fixes"
- Fix: editor-app's transfer table row points to signing in again (one sentence shared with accounts-privacy-legal and with "A sign-in never expires on its own"), not to copying diagnostics.

### F4: "A value set on the computer always wins" against a reporting kind the studio switched off
- Kind: contradiction
- From: accounts-privacy-legal / An editor chooses what their computer reports (and "Four kinds of reporting can be switched off")
- Here: Settings, records and background work / A value set on the computer always wins
- From says: "a computer can never switch back on what the studio switched off"; "A kind the studio switched off shows off ... and cannot be changed here"
- Here says: "Anything set on the computer itself wins. A blank or zero value from the site never switches anything off on a computer."
- Settled by: the owner must say: when the studio has switched a kind of reporting off, can an editor switch it back on for their own computer? (accounts-privacy-legal says plainly no)
- Fix: editor-app's precedence rule names the exception: the studio's reporting switches (and any other site-only limit) are never overridden from the computer.

### F5: Closing the licence window: stops the automatic offer, or counts as unanswered and comes back
- Kind: contradiction
- From: accounts-privacy-legal / A computer accepts the licence before it first syncs
- Here: Signing in, the computer's identity and the licence / Nothing syncs until the licence is accepted, and the app asks within a minute
- From says: "again every minute until the window has actually been shown once ... Declining or closing the window stops the automatic offer"
- Here says: "offers it again until it has been answered, counts closing it as unanswered"
- Settled by: APP-130 (situation, weaker): "returns until answered, treats closing as unanswered"
- Fix: accounts-privacy-legal says closing the window counts as unanswered and the offer returns; only DECLINE stops the automatic offer (or editor-app says the same if the owner prefers).

### F6: A new licence version: syncing stops until accepted, or keeps going while it waits
- Kind: contradiction
- From: accounts-privacy-legal / A new licence version asks everyone again without stopping their sync
- Here: Signing in, the computer's identity and the licence / Nothing syncs until the licence is accepted, and the app asks within a minute
- From says: "The computer keeps syncing while it waits, and shows \"waiting for the licence to be accepted\" as its state"
- Here says: "Nothing syncs on a computer until someone there has accepted the current licence"
- Settled by: ACC-055 (situation, weaker): "A licence change asks each editor at once without stopping their sync"
- Fix: editor-app limits "nothing syncs" to a computer that has never accepted any licence, and says a newer version is asked for while syncing goes on.

### F7: Where the b-roll progress window is opened from: the menu, or the settings window
- Kind: differs
- From: broll / The computer doing the work shows what describing is doing, and the person at it can pause, resume, start now or cancel
- Here: Windows, dialogs and notifications / Long background work has a progress window the editor can close and reopen
- From says: "The progress window \"INDEXING B-ROLL\" ... opens from the menu, or by itself when a drop starts or a download begins"
- Here says: "It opens by itself once when a piece of work starts (if the editor closes it, it stays closed for that piece of work) and from the \"SHOW ... PROGRESS\" buttons in the settings window."
- Settled by: the owner must say: does the editor reopen the b-roll progress window from the app's menu or from its settings window, and does it open again by itself when the one-off download begins after the editor closed it?
- Fix: broll and editor-app name the same place to open it from and the same rule for opening by itself.

### F8: The b-roll and music indexing lines and their buttons have no home in the app
- Kind: missing
- From: music / An editor sees music analysis on their computer while it is doing it (and broll / The computer doing the work shows what describing is doing...)
- Here: nowhere (The menu holds about ten everyday lines; The menu carries a line for each piece of work under way)
- From says: "the app on it shows a line and buttons ... Buttons: \"RESUME MUSIC INDEXING\" when paused; otherwise \"INDEX MUSIC NOW (don't wait until I'm away)\" ... \"PAUSE MUSIC INDEXING\"; then \"SHOW MUSIC INDEXING PROGRESS\" and \"CANCEL THIS MUSIC DROP…\""
- Here says: nothing; the only indexing line listed is "\"N b-roll clips could not be indexed: <first file name> (<reason>), and M more\"", with no music failure line and no indexing buttons
- Settled by: the owner must say: where on the editor's computer does the editor see what b-roll and music analysis are doing and press pause, index now or cancel: in the menu or in the settings window?
- Fix: editor-app lists the b-roll and music lines and buttons in the menu or the settings window (each absent while its part is off), including the music failure line.

### F9: Opening the Timeline Cards editor in a window of its own is nowhere in the app
- Kind: missing
- From: cards-editor-5 / The app on the editor's computer opens the editor in a window of its own
- Here: nowhere
- From says: "the editor can also be opened in a window of its own, with no browser around it, from the app on the editor's computer ... and updates itself with the app, from its settings"
- Here says: nothing (no menu line, window or setting mentions Timeline Cards)
- Settled by: answered page 28.1: "A: the one app on the editor's computer opens the editor in a window of its own with this menu, and updates with that app."
- Fix: editor-app adds the way in (a menu line or settings button, present only while Timeline Cards is on) and that the window is part of the one app and its updates.

### F10: Shared-work time shown read-only and "changed on the computer", against settings an admin can ask a computer to change
- Kind: contradiction
- From: dashboard-1 / What computers can be asked to change is shown before asking
- Here: Settings, records and background work / The admin sees, read-only, the settings each computer last reported
- From says: "the dashboard shows which of its settings can be changed from the dashboard ... how long it lends itself to shared work (0 to 100000 minutes), its sync-drive reminder"
- Here says: "The per-computer view of the dashboard shows, read-only ...: how long the computer lends itself to shared work (\"<n> min\"; changed on the computer, in its settings)"
- Settled by: the owner must say: can a person or an admin ask one of the person's computers, from the dashboard, to change how long it lends itself to shared work and its sync-drive reminder? (accounts-privacy-legal "A person or an admin asks one of the person's computers to change its settings" says yes)
- Fix: editor-app says these can be asked for from the dashboard and are applied by the computer, or dashboard-1 and accounts-privacy-legal drop the asking.

### F11: Wired or remote said to be changeable by an admin from the dashboard
- Kind: contradiction
- From: accounts-privacy-legal / A person or an admin asks one of the person's computers to change its settings (read beside J9's leaning behaviour)
- Here: Settings, records and background work / The settings each computer holds
- From says: "Whether a computer is wired or remote can never be asked for from the dashboard; it is set only on the computer."
- Here says: "wired or remote, keeping proxies, ... each changed by the editor in this window for their own computer or by an admin from the dashboard"
- Settled by: APP-131 (ruling): "The wired-or-remote choice made in setup becomes that computer's own setting, and nothing derived from the person's account ever changes it."
- Fix: editor-app takes "wired or remote" out of the list of settings an admin changes from the dashboard.

### F12: Installing or updating switches the start at sign-in back on after Task Manager turned it off
- Kind: missing
- From: footage-sorter-and-camera-cards-1 / The app on an editor's computer watches for cards and drives
- Here: Starting, staying running and crashing / The app starts whenever the editor signs in to the computer, and set-up confirms it is running
- From says: "If Windows Task Manager has switched the app's start at sign-in off, installing or updating the app switches it back on."
- Here says: nothing beyond "set to start whenever they sign in to the computer"
- Settled by: the owner must say: when an editor has switched the app's start at sign-in off in Windows Task Manager, does installing or updating the app switch it back on?
- Fix: editor-app states the rule (it belongs to starting at sign-in for the whole app, not to card watching) and footage-sorter points to it.

### F13: Whether field backup is on by default on a computer
- Kind: missing
- From: footage-sorter-and-camera-cards-1 / An editor can copy a card with no network at all
- Here: The tray or menu-bar icon and its menu / Field backup opens from the menu
- From says: "Field backup is on by default on every computer while the Footage Sorter is on."
- Here says: "While the camera cards part is on and field backup is on for this computer, \"Field backup...\" in the menu opens the field backup page" (no default given)
- Settled by: answered page 8.2: "A: keep it, shown only while the camera cards part is on and off by default per computer."
- Fix: footage-sorter-and-camera-cards-1 changes its default to off, and editor-app states that default.

### F14: The shutdown warning while music analysis fetches what it needs is worded two ways
- Kind: contradiction
- From: music / Analysing music keeps the computer it runs on usable
- Here: Starting, staying running and crashing / A computer doing heavy work stays awake and warns before shutting down
- From says: "a shutdown is met with \"still indexing music (N track(s) left)\" or \"still downloading the music analysis\""
- Here says: "\"still indexing <b-roll|music> (N <clips|tracks> left)\" or \"still downloading what <b-roll|music> analysis needs\""
- Settled by: the owner must say: which words does the shutdown warning use while a computer is indexing music or fetching what music analysis needs?
- Fix: music quotes editor-app's sentences (or points to them) instead of giving its own.

### F15: The app's own status page that a browser can open is nowhere in the app
- Kind: missing
- From: music / An editor sends a track to Resolve on their own computer in one of three ways
- Here: nowhere
- From says: "followed by the address of the app's own status page to open in a tab, and the advice that if that page answers that all is well, the browser is to blame, not the app"
- Here says: nothing
- Settled by: the owner must say: should an editor be able to open a page in their own browser that says whether the app on their computer is running and can take requests?
- Fix: editor-app describes that page (its address and what it says) under the product's pages reaching Resolve, or music drops the pointer.

### F16: Staying awake for proxy making is not in the app's stay-awake rule, and the 8-hour cap is unclear for it
- Kind: missing
- From: proxies-and-file-moves / A computer making proxies stays awake and says why it should not shut down
- Here: Starting, staying running and crashing / A computer doing heavy work stays awake and warns before shutting down
- From says: "While any proxy is being made the computer is kept from sleeping. ... See The app on each editor's computer: Starting, staying running and crashing."
- Here says: "While the computer is doing heavy work for b-roll or music ... This holds only while work is really moving or moved recently, and never for longer than 8 hours in a row. For syncing, see Sync"
- Settled by: the owner must say: does a computer making proxies stop being kept awake after 8 hours in a row, as b-roll and music analysis do?
- Fix: editor-app names proxy making in its stay-awake rule (with or without the cap), and proxies-and-file-moves says the same.

### F17: The message after going back from a crashing version differs
- Kind: contradiction
- From: releases-and-updates / A new version that keeps crashing puts the previous one back by itself
- Here: Starting, staying running and crashing / A version that cannot stay up is replaced by the version before
- From says: "\"The last update kept crashing, so CC Sync went back to v<version>.\""
- Here says: "\"⚠ The vX update kept crashing, so CC Sync went back to the previous version. Your admin has been told\""
- Settled by: answered page 8.11: "one rule says one thing to the editor and admin"
- Fix: both pieces use one sentence; editor-app should point to releases-and-updates for it rather than give its own.

### F18: No previous version to go back to: the app is left down, or carries on
- Kind: contradiction
- From: releases-and-updates / A new version that keeps crashing puts the previous one back by itself
- Here: Starting, staying running and crashing / A version that cannot stay up is replaced by the version before
- From says: "Then the app carries on, says why in the start-up log, and the server is told ... None of this can stop the app from starting when it would otherwise start."
- Here says: "If there is no earlier version to go back to, the app is left down and the admin is told that a person must step in."
- Settled by: the owner must say: when a new version keeps crashing and there is no earlier version to go back to, does the app keep being started again, or is it left down until a person steps in?
- Fix: one of the two pieces changes to the owner's answer, and editor-app then points to releases-and-updates for it.

### F19: An installer link that works without signing in, against a download that tells anyone not signed in to sign in
- Kind: contradiction
- From: releases-and-updates / Anyone signed in can download the app and the installer
- Here: Installing and setting up / An editor gets the installer for a new computer, or to repair one
- From says: "Neither signed in nor a computer with credentials: told to sign in."
- Here says: "an admin can hand them the installer as a file or as a download link that works from anywhere without signing in"
- Settled by: answered page 8.12: "the link an admin hands over is the only other way in a new editor needs, since they cannot sign in yet"
- Fix: releases-and-updates adds the admin-handed link as the one way to download the installer without signing in.

### F20: The sentences for "nothing published" and "file missing" differ between the two pieces
- Kind: contradiction
- From: releases-and-updates / Anyone signed in can download the app and the installer
- Here: Installing and setting up / An editor gets the installer for a new computer, or to repair one
- From says: "Nothing current: \"no current <platform> <kind> is published\" ... The file is missing on the server: \"the file for that version is missing on the server\""
- Here says: "\"No <platform> installer has been published for this studio yet, so there is nothing to download. Ask whoever set this dashboard up for the installer.\" ... \"installer file is missing on the server: re-publish it\""
- Settled by: the owner must say: what is a person told when the installer they ask for has not been published, or its file has gone from the server?
- Fix: releases-and-updates says the installer page's sentences apply to the installer (pointing to editor-app), or editor-app uses releases-and-updates' sentences.

### F21: Resolve missing at set-up: a note on a finished install, or a step that failed
- Kind: contradiction
- From: resolve-on-the-editors-computer / Installing the app sets Resolve up for the studio
- Here: Installing and setting up / The finish page says whether the computer is ready, and what happens next (and "Set-up checks that it can finish before it changes anything")
- From says: "Outcomes, each a note on the install's finish page: ... Resolve not found and never opened (\"Could not find DaVinci Resolve on this computer ... Install Studio, open it once, quit it, then run this installer again\")"
- Here says: "Set-up says done only after the app is installed and visibly running, the computer has reported in to the dashboard, its project drive answers and Resolve can be reached; otherwise it names the step that failed."
- Settled by: the owner must say: when Resolve is not installed, or cannot be reached, on a computer being set up, does set-up finish as ready with a note, or say the computer is not ready?
- Fix: editor-app and resolve-on-the-editors-computer state one outcome (and editor-app says what "Resolve can be reached" means when the help for the editing program is off).

### F22: The pointer to editor-app for the Windows folder checks leads nowhere
- Kind: missing
- From: sync-1 / Choosing the sync folder on macOS checks the drive is really mounted
- Here: Installing and setting up (only "Set-up checks that it can finish before it changes anything")
- From says: "See The app on each editor's computer: Installing and setting up, for Windows."
- Here says: "The editor's local project folder can never be a bare drive or volume root ... choosing one is refused with the reason." (no list of Windows checks)
- Settled by: the owner must say: nothing new; the Windows checks are written in full in sync-2 / "The editor picks the folder for the project tree when setting up"
- Fix: sync-1 points to sync-2 for the Windows checks instead of to editor-app.

### F23: A whole drive as the folder: refused for every computer here, only for a remote editor there
- Kind: contradiction
- From: sync-2 / The editor picks the folder for the project tree when setting up (and sync-1 / Choosing the sync folder on macOS checks the drive is really mounted)
- Here: Installing and setting up / Set-up checks that it can finish before it changes anything
- From says: "is a whole drive on its own such as D:\\ for a remote editor (it must be a folder)"; the suggestion for a computer straight off the server on Windows is "the site's drive letter"
- Here says: "The editor's local project folder can never be a bare drive or volume root (a whole disk such as D:\\ or a whole volume on a Mac); choosing one is refused with the reason."
- Settled by: the owner must say: may a computer that works straight off the server use a whole drive (such as P:\\) as its project tree root?
- Fix: editor-app limits the refusal to a remote editor's computer, matching sync-2's checks.

### F24: The status sentence for a computer that is not set up differs
- Kind: contradiction
- From: sync-2 / The app's menu says in one phrase what syncing is doing now
- Here: Telling the editor what is wrong / A computer that is not fully set up names what is missing
- From says: "3. The computer is not set up, or the licence is not accepted: \"Sync: not set up yet\"." and "The same sentences, word for word, are used wherever the app says why syncing is held"
- Here says: "While a problem stands, the sync status reads \"NOT SYNCING: this computer isn't fully set up: <first problem, or 'see the log'>\""
- Settled by: answered page 8.8: "A: one status sentence, used in the menu and the window alike"
- Fix: editor-app's status sentence for "not set up" (and for the licence, "NOT SYNCING: <the licence sentence>") is sync-2's, with the longer explanation kept to the settings window's WHAT IS NOT SET UP list.

### F25: A failed attempt to bring syncing back writes a crash report there, and none here
- Kind: contradiction
- From: sync-2 / Syncing comes back by itself when it stops running
- Here: Starting, staying running and crashing / Every crash is written down on the computer and counted for the admin
- From says: "A failed attempt is logged, kept as a local crash report and counted (\"N failed attempt(s) since the app started\")"
- Here says: "A failure the app recovers from by itself writes no crash report and never advises a restart."
- Settled by: APP-114 (situation, weaker): "A failure the app recovers from by itself writes no crash report and never advises a restart."
- Fix: sync-2 drops "kept as a local crash report" and counts failed attempts as recoveries (which editor-app already shows to editor and admin).

### F26: The warning that the computer cannot be recognised after a rename is worded two ways
- Kind: contradiction
- From: sync-2 / An editor is told once when their computer may not be recognised after a rename, and syncing carries on
- Here: Signing in, the computer's identity and the licence / When the identity cannot be read, the editor can give the computer a new one
- From says: "\"Syncing is not affected, but this computer cannot be recognised again if it is renamed. The Settings window can repair this, and your admin may want to look first.\""
- Here says: "\"⚠ CC Sync cannot read this computer's id file, so the server cannot recognise this computer again if you rename it. Syncing is not affected.\" with \"GIVE THIS COMPUTER A NEW ID\""
- Settled by: APP-129 (situation, weaker): "One confirmed button says it gives this computer a new identity (never \"repair\")"
- Fix: sync-2 points to editor-app's sentence and button instead of its own wording with "repair".

### F27: Who adds another address allowed to send to Resolve: the editor at the computer, or only an admin for the site
- Kind: contradiction
- From: whole-product / Only the studio's own dashboard can make the app on an editor's computer act
- Here: Settings, records and background work / The product's pages reach Resolve on the editor's computer through the app, and only the studio's pages may
- From says: "An admin or the editor puts it right by correcting the address, or by adding the other address the dashboard is reached by ... the address is set by an admin or the editor at that computer"
- Here says: "Setting: Other web addresses allowed to send to Resolve. ... Who: an admin. Applies to: the site."
- Settled by: the owner must say: may an editor, at their own computer, add another address whose pages may send to Resolve there, or only an admin, for the whole studio?
- Fix: whole-product and editor-app name the same person and the same reach (computer or site) for adding an address.
