# The app on each editor's computer

The app on each editor's computer is the one program that keeps that computer part of the studio: it syncs the editor's projects, keeps an eye on Resolve, receives the clips and tracks sent from the product's pages, takes its share of heavy work, and tells the editor in plain words what is happening and what is wrong. Every editor's computer, Windows or macOS, runs it. It starts when the editor signs in to the computer, stays out of the way in the Windows tray or the macOS menu bar, and comes back by itself if it dies. It is part of the core and cannot be switched off. There is one app with one version on every computer and every switchable part is in it, but its menu lines, windows and notices for a switchable part appear only while that part is on: with a part off, nothing on the editor's computer mentions it.

## Installing and setting up

### The app runs on supported Windows computers and Apple silicon Macs

The app runs on Windows 10 22H2 and Windows 11 on x64 processors, and on Macs with Apple silicon. Nothing else is supported. Set-up on an Intel Mac or on an unsupported Windows stops before it changes anything, with a message naming what is supported.

There is one program for Windows and one for macOS. It never opens a console window. On Windows the program carries the product's name, mark and description; on both systems it names the vendor, never the customer, as its publisher. On macOS it carries the vendor's own stable developer identity, so that macOS keeps the permissions the editor granted it from one version to the next. It is never packed in a way that makes antivirus programs flag it.

- Windows and macOS: on Windows the app lives in the system tray; on macOS it lives in the menu bar and is started at sign-in.

### An editor gets the installer for a new computer, or to repair one

Anyone signed in to the dashboard can download the installer. The download is the full clean-install and repair package (never the bare app), named with its version. The page offering it is headed "INSTALLER", "for a new editor computer, or to repair one", and says: "The full clean-install and repair package for a new editor computer. Save it to that computer's own disk: running it off the shared drive locks the file for everyone, and the setup wizard refuses it." For each system it shows the version, the size, "published <ago>", a shortened checksum (the full one on pointing at it) and a download button. The one that matches the browser is marked "this computer" and is what a single click downloads: a Mac gets the macOS installer, Windows gets the Windows one, and any other browser (Linux, a browser that hides its system) is shown the choice instead of a guess. On a phone the page adds: "On a phone: this package cannot be run here. Download it and send it to the editor's own computer, Windows or macOS, and run it there."

With nothing published for a system: "Nothing published for this platform yet." A link followed when nothing is published says "No <platform> installer has been published for this studio yet, so there is nothing to download. Ask whoever set this dashboard up for the installer.", with a line telling admins how to publish one (see Releases and updates: Making and publishing a release). A published installer whose file has gone says "installer file is missing on the server: re-publish it".

A new editor has no sign-in and is not yet on the studio's private network, so an admin can hand them the installer as a file or as a download link that works from anywhere without signing in. The installer carries a "start here" note: copy the installer to the Desktop first and run it from there; how to get past the operating system's warnings (see "The download page walks the editor past the operating system's warnings"); how Resolve is connected; how updates arrive; how to uninstall; and never to map a server share to a drive letter by hand.

- Who: anyone signed in to the dashboard, and anyone an admin hands the file or link to.
- Ways in: the installer page of the dashboard, a file or download link an admin hands to a new editor.
- Name and search words: Installer download. Search words: installer, new computer, repair, set up, download app.
- Phone and desk: on a phone the page explains that the package must be run on the editor's own computer.

### The installer refuses to run from the project drive, a network location or a removable disk

Before anything else the installer checks where it is running from, and refuses to go on from a place the install would pull out from under itself or lock for everyone. On Windows it refuses when it runs from the studio's project drive letter or from a network path, telling the editor that the install is about to remove that drive from under itself, that running it off the server locks the file for everyone, and to copy the installer to the Desktop and run it from there. On macOS it refuses only when it runs from a network share or a removable or external disk, and runs from the home folder (Downloads, the Desktop) or Applications; its refusal tells the editor to copy the app into Downloads or onto the Desktop. If the check cannot tell, it does not refuse. A retry button checks again once the editor has moved it.

- Windows and macOS: the refusal is worded for each system, as above.

### One set-up wizard takes a computer from nothing to signed in and working, and is safe to run again

The same wizard runs on Windows and on macOS, with the same steps. Its welcome page says that it sets up or refreshes this computer, removes every trace of earlier versions, installs the current app (which keeps itself up to date from the dashboard from then on) and signs it in; on Windows it adds that it sets up the project drive, on macOS that it points Resolve's drive mapping at the local copy of the project tree. It says the editor needs two things from their admin: the dashboard address, and the username and password the admin set up for them. It says it is safe to run again at any time. A small line shows the installer's version and the version of the app it carries ("?" when unknown). The Windows and macOS installers share one version number.

The pages come in this order, some only when they apply:

1. "THE LAST INSTALL DID NOT FINISH" (only when one did not; see "An install cut short is offered to be finished, and nothing syncs until it is").
2. The licence (see Accounts, privacy and the legal paperwork: The licence a person accepts).
3. Welcome.
4. Wrong account (Windows only, only when it applies).
5. Step 1: how this computer reaches the footage, remote editor or physically connected to the server, and the dashboard address (see Sync: Wired or remote, and "The editor types the dashboard address and it is checked before going on").
6. Step 2: joining the studio's private network (remote editors only).
7. Step 3: signing in.
8. Step 4: what this computer reports (see Accounts, privacy and the legal paperwork: What the product records about a person).
9. Step 5: install.
10. A finish page, one for a remote editor and one for a computer wired to the server.

Back returns one page; from the sign-in page it returns to the network page for a remote editor and to step 1 for a wired computer. The wizard never asks for a value it already has: a re-run starts from what this computer was set to before.

- Who: the editor at the computer, with the address, username and password their admin gave them.
- Windows and macOS: the same wizard, licence, sign-in, reporting choices, 200 GB space warning, NOT READY verdicts and finish pages on both. Only Windows checks the running account and makes a drive letter; on macOS Resolve's own drive mapping is used instead, and an external sync drive is checked and remembered.

### Only one set-up runs at a time on a computer

A second set-up started on a computer while one is running is refused before it changes anything, saying that another set-up is already running on this computer and to let it finish or close it first.

### On Windows set-up under a different account from the one signed in is refused

Everything the app installs belongs to one person, so an install running under another account would give the signed-in person nothing. When the editor leaves the welcome page, the wizard compares the account signed in at the screen with the account it is running as, ignoring letter case and any domain part. On a mismatch it shows WRONG ACCOUNT: "You are running as X but Y is signed in. Everything this installs is per-user, so Y would get nothing. Y does not need to sign in again: close this and start the installer again by double-clicking it, and do not choose Run as administrator or type another account's password if Windows asks (it does not need administrator rights)." then "Nothing on this computer has been changed.", with only a close button. If the signed-in account cannot be told, it never refuses.

- Windows and macOS: Windows only. A Mac install has no such check.

### A remote editor joins the studio's private network inside the wizard

Step 2, for remote editors only, says that the project server lives on the studio's private network: install the network's app, sign in to it with the invite the admin sent, then come back and check. A status line shows whether the network's app is installed or not, refreshed when the page opens and after every check. A button opens the network app's download page for this system. The dashboard address is shown below.

"Check connection" runs one check at a time (greyed, showing "checking...", while it runs). It first asks whether this computer has joined the network ("not joined yet: open its icon in the tray (menu bar on a Mac) and sign in"), then asks the dashboard whether it is up, waiting up to 10 seconds and never following a redirect. Each failure is told plainly:

| What went wrong | What the editor is told |
|---|---|
| no address set | the address is missing, go back and enter it |
| the name does not exist on this network | the address does not exist here: check the spelling with your admin |
| no answer in time | did not answer in time: if you just joined, wait a few seconds and check again |
| refused | the address exists but nothing serves the dashboard on that port: check the port with your admin |
| answered with an error code | the address is right: tell your admin |
| answered with a redirect | CC Sync never follows one: ask for the direct address |
| plain http to the public internet | refused, as in "The editor types the dashboard address and it is checked before going on" |
| anything else | the error itself |

Success shows "connected: the dashboard is answering", and only then is Next enabled and focused.

- Who: a remote editor.
- Windows and macOS: on Windows a button installs the network's app with Windows' own package installer (in its own window), then says "installed: sign in to it from its tray icon, then press check connection" or "did not install: try the download page". On macOS the editor installs it from the download page.

### Set-up checks that it can finish before it changes anything

Before removing anything, set-up checks that it has what it needs to finish: the app it carries, the site's settings, a valid sign-in, and a usable place for the editor's copy of the projects. If it cannot finish, it stops with nothing removed and says why.

- The editor's local project folder can never be a bare drive or volume root (a whole disk such as D:\ or a whole volume on a Mac); choosing one is refused with the reason.
- When the chosen place has less than 200 GB free, set-up warns with the figure and lets the editor go on. It never refuses on space, and says nothing when space cannot be measured.
- Before asking an editor to launch Resolve once, set-up checks that Resolve is installed; if it is not, it says that Resolve Studio must be installed first.
- One set-up run uses one drive letter and one tree name: the site's, else the copy of the site's settings kept from the same dashboard if it is less than 30 days old, else it stops and says it could not get the studio's settings.

### The install shows every step live, can be retried, and gives up after 30 minutes

While installing, the install and back buttons are disabled and every step appears in the log as it happens (see "Every install step is shown live and kept in a log the editor can copy"). On any failure the install button becomes "[ RETRY INSTALL ]" and back works again. An install that runs over 30 minutes is stopped, with a message that it may be stuck on a prompt or a stalled download and to run the installer again. An install that stops part-way says plainly that it did NOT finish, which is different from finishing with something missing. Any unexpected error shows "install failed: <reason>" with retry.

### Closing the wizard in the middle of an install asks first

The wizard closes freely on every page except while an install is running. Then a yes or no question, with no as the default, says the install is part-way through and that closing now leaves this computer with no CC Sync and, for a Windows remote editor, no project drive letter (for a wired computer or any Mac, just no CC Sync). Yes stops the install and everything it started, then closes. If the question cannot be shown, the window stays open.

### An install cut short is offered to be finished, and nothing syncs until it is

The computer records that an install is under way just before the install starts removing earlier versions, and clears the record only when a finish page is reached. A record that cannot be read still counts as an unfinished install; if the record cannot be written, the install log carries a warning.

While the record stands, the wizard opens on "THE LAST INSTALL DID NOT FINISH". It says the computer was part-way through an install and that until it is finished there is no CC Sync ("Nothing is syncing" for a remote editor; for a wired computer, that the drive mappings, or a Mac's server mounts, were not touched but the app is not running), when it started if known, and that finishing is safe, is the only fix, and will ask for the sign-in again. The role choice is set to the interrupted run's. The buttons are close, and finish the install, which goes on to the licence page.

Meanwhile the app, if it is there, does not sync, and says: "The last install of CC Sync on this computer did not finish, so this computer may have no <drive> drive and a half-written setup. Nothing will sync until it is finished. Run the CC Sync installer again and choose FINISH THE INSTALL." The drive is named from the studio's settings, else "your media drive". When the app cannot tell whether an install was interrupted, it does not refuse.

### Every install leaves exactly one copy of the app and keeps the sign-in, settings and identity

Every install, whether it succeeds or fails, first stops any running copy of the app, removes every way an earlier version started itself at sign-in (including those of versions with older names), and removes every earlier copy of the app from wherever one was put (retrying a locked file, then setting it aside with a warning), so exactly one copy is left. It stops only what CC Sync itself started: a program of the same kind that the editor runs for their own purposes is left alone and named in a warning. If removing an earlier start-at-sign-in entry is denied, the warning gives the exact command for an administrator to run and says not to re-run the installer as administrator.

An install never removes the computer's sign-in, its settings, its identity (so the admin does not have to approve it again) or its record of the external sync drive. A wired computer's drives are never touched. Every action goes in the install log; none of it stops the install.

### Everything set-up fetches is checked before it is used

Anything the computer needs for the parts that are on is installed whenever that part is on, whatever other parts are off; what is already on the computer at the right version is reused. Everything set-up downloads is fetched at an exact known version and checked against a known fingerprint before it is unpacked. On a mismatch the editor sees "CHECKSUM MISMATCH" with the expected and actual values, and that the download was NOT installed and has been deleted. Each install's real result is checked, and what is installed is found without a restart. A piece that cannot be installed at all makes the computer NOT READY, with a line saying what will never work on this computer without it.

Set-up changes nothing on the computer that the product does not need, and nothing it does not say: the editor's own entries in the command search path are kept exactly as written, the computer's other file sharing keeps working, and no unrelated system setting changes unannounced.

- Windows and macOS: macOS quarantines downloaded programs and silently refuses to run them in the background, so everything set-up places on a Mac is cleared to run before it is started, and a helper that fails to start is reported to the editor.

### The computer only ever talks to its own studio's server

Set-up records the identity of the studio's server so that the computer refuses a server that does not match. When the site publishes no identity for its server, set-up says plainly that this computer will not verify the server's identity. A server's identity includes any port given, so two servers on one NAS are never confused and settings remembered for one are never applied to the other. After set-up for a new site the computer holds only that site's sign-in and reports only to that site's server. Connections the editor set up for their own purposes are left exactly as they were; if one this product made pointed somewhere else, set-up warns with the old and new values and replaces only that one, keeping a copy first and leaving it untouched if replacing it would lose anything ("it was LEFT UNTOUCHED, nothing was lost").

### The finish page says whether the computer is ready, and what happens next

Set-up says done only after the app is installed and visibly running, the computer has reported in to the dashboard, its project drive answers and Resolve can be reached; otherwise it names the step that failed. An install on a fresh or a used computer ends with the app running, syncing without any hand edits once approved, and the computer waiting for the admin's approval.

When a remote editor's install finishes with no problems, the finish page is headed "DONE: WAITING FOR YOUR ADMIN TO APPROVE THIS COMPUTER". It says the app is installed and signed in as the editor, that nothing syncs until the admin approves this computer, and that the computer is already waiting on the dashboard for that approval with the editor's name and the computer's name (see Sync: Computers joining and changing). It shows the dashboard address, the support contact from the site's settings, where the install log is, and a copy-log button.

A wired computer's finish page is described in Sync: Wired or remote.


#### Lessons

- Met: APP-001, APP-002, APP-003, APP-004, APP-005, APP-006, APP-007, APP-008, APP-009, APP-010, APP-011, APP-012, APP-013, APP-014, APP-015, APP-016, APP-017, APP-018, APP-019, APP-020, APP-021, APP-022, APP-023, APP-024, APP-025, APP-026, APP-027.

## Security warnings, permissions and certificates

### The download page walks the editor past the operating system's warnings

Where Windows or macOS warns about a program it does not recognise, the installer page and the installer's "start here" note walk the editor through it, including allowing it again after an update and checking the download's checksum against the one the page shows.

- Windows: expect "Windows protected your PC": choose More info, then Run anyway. If there is no Run anyway, open the file's Properties, tick Unblock, press OK and run it again. Smart App Control must be turned off first, or it blocks the installer with no way past.
- macOS: open the program once and click Done, then in System Settings, Privacy & Security, click Open Anyway and give the Mac's password; open it again and click Open. This may repeat after an update.

- Windows and macOS: the two walk-throughs above.

### On macOS the app checks at every start that it may read the sync drive, and says how to allow it

macOS can withdraw the app's permission to read the sync drive, most often after an update. At every start, and while the sync drive is mounted, the app checks whether macOS is refusing it the drive (as opposed to the drive being out). When it is, the editor is told: "macOS is blocking access to the sync volume. Give CC Sync Full Disk Access again in System Settings → Privacy & Security → Full Disk Access." The same appears in the diagnostics, and syncing waits until access is back.

- Windows and macOS: macOS only.

### On Windows an expired certificate left in the computer's store never stops the app reaching the server

A fact about Windows: an expired intermediate certificate left in a person's certificate store can make every secure connection a program makes fail with "certificate has expired" while the browser works fine. The app connects securely whenever Windows itself would: it ignores certificates in the stores whose expiry is certainly past, and keeps one whose date cannot be read.

- Windows and macOS: Windows only; nothing of the kind happens on macOS.

### The computer's sign-in and settings are readable only by the editor

Everything the app keeps on the computer that holds its sign-in or settings is readable and writable only by the editor's own account (plus the system and administrators on Windows). Every install and update restricts it so, says that it restricted the files that hold the computer's sign-in, and repairs the permissions of everything inside. At every start on Windows the app checks that it can read and write all of its own records; if anything is unreadable it takes them back for the editor's account and checks again. This never stops the app starting. If a safety stop cannot be saved because of it, the editor and the dashboard are told (see Sync: Safety stops).

### Everything set-up fetches is reused or downloaded at a known version

Where something the computer needs cannot be fetched from its publisher at the known version, set-up tries the system's own package installer and warns when the result is not the known version. Where set-up adds a program to the editor's command path, its message says to restart the terminal, or sign out and back in, to pick it up.

- See "Everything set-up fetches is checked before it is used" for the fingerprint check and the NOT READY verdict.

#### Lessons

- Met: APP-028, APP-029, APP-030, APP-031.

## Drive letters and network drives

### On Windows a remote editor's copy of the projects appears at the studio's drive letter

Resolve stores every clip by its full path, so every computer must see the studio's footage at the same place. On Windows that place is a drive letter, the site's (P: unless the studio set another). A remote editor's own copy of the projects is presented at that letter, made fresh on each install, back by itself every time the editor signs in, and labelled in Explorer with the studio's name from the site's settings. It is mapped in the editor's own normal session, so Explorer and Resolve both see it. The editor's folder is reachable from this computer only: it is never offered to other computers on any network the computer joins.

Setting the drive up fully may need one administrator approval during the install. If the editor declines it, or it cannot be done, the drive still works but Explorer shows the disk's own name instead of the studio's, and the editor is told that running the installer again and approving gives it the studio's name. If the drive cannot be set to come back at sign-in, the editor is told it will not come back after signing in again, given the command to run by hand, and told NOT to re-run the installer as administrator. Mapping the drive gives up within 30 seconds, and no password is ever shown on screen or in a command while it is done.

- Windows and macOS: on macOS no drive letter is made; set-up points Resolve's own drive mapping at the editor's local copy instead (see Resolve on the editor's computer: Setting Resolve up: edition, scripting switch, preferences).

### A drive letter already in use is never taken

If the studio's drive letter is already used by anything CC Sync did not create (a disk, a mapping to anything, including a disconnected or unavailable one, or a share on the server), it is left alone, the drive part of the install is skipped, and the computer is NOT READY. The message says the letter is already used for that target and was not made by this installer: disconnect it yourself (Explorer, This PC, right-click the drive, Disconnect) and run the installer again, or ask the admin; and if this computer works straight off the server, run the wizard again and choose physically connected instead. If Windows would not say what the drive letters point at, the message says to sign out and back in, then run the installer again.

A mapping is removed or replaced only when it is provably the product's own. When that is unsure, or what the editor chose and what the computer shows disagree, it is left in place and the editor asked. When a remote editor's install replaces the product's own mapping and it will not let go, the editor is told that something has files open on the drive, to close those programs and retry. A wired computer's drives are never removed.

### Installing from an administrator window is warned against

The install is meant to run as the ordinary signed-in person. A drive letter mapped from an elevated window is invisible to the editor's normal session, so when the install is run from one it warns and maps the drive in the normal session instead. If it cannot, it ends with a block saying the drive had to be mapped from the elevated window, to sign out and back in (or restart) before opening Resolve, and not to re-run the installer to "fix" it. A program with no console asks for any network credentials in its own window, never at a console prompt.

- Windows and macOS: Windows only.

### Windows warns when the drive letter does not lead to the synced folder, and repairs it in one click

When the studio's drive letter is mapped elsewhere or not at all, or Resolve has clips on a letter this computer lacks, the editor is shown: "Resolve is looking for your media on P: but P: is not pointing at your synced folder, so clips will show offline. Your uploads and downloads are still running." with "REPAIR P: NOW" (the studio's letter in place of P:). Repair is refused for a letter mapped by something else, saying what it points at. A failed repair says "CC Sync could not repair the drive mapping. <where to copy diagnostics>." Nothing is said while the letter is deliberately pointed at the server for grading (see Resolve on the editor's computer: Grading from the server's originals).

A drive that cannot be found by a check run early at sign-in or from an elevated window counts as "cannot tell", never as missing; a disconnected mapping counts as present, and every removal of a mapping is confirmed afterwards.

- When the help for the editing program is off: the warning still appears, without naming Resolve: "Your media drive P: is not pointing at your synced folder. Your uploads and downloads are still running."
- Windows and macOS: Windows only.

### Background work never mistakes an unseen drive for missing files

A fact about Windows: a mapped drive letter exists only in the desktop session that mapped it, not for work running in the background or in a remote session. Anything the app does outside the editor's desktop reaches the footage by the server's real address, never reports files missing because a letter cannot be seen there, and names plainly a share it cannot reach.

A fact about macOS: when the NAS is not mounted, its mount path is an ordinary folder on the start-up disk, and anything written there fills the start-up disk. Nothing is written under a mount path unless the share is confirmed mounted immediately before writing.

- Windows and macOS: the two facts above.

### The studio's drive letter and tree name cannot change under installed computers

Once any computer is installed, the studio's drive letter and tree name are not changed silently: the dashboard refuses to change them while computers are installed and says why (every Resolve project stores its clips on that letter), so no computer is ever left on a letter the others have left.

- Who: an admin.

#### Lessons

- Met: APP-032, APP-033, APP-034, APP-035, APP-036, APP-037, APP-038, APP-040, APP-041, APP-042, APP-043, APP-044.

## Starting, staying running and crashing

### The app starts whenever the editor signs in to the computer, and set-up confirms it is running

The app is installed for the editor's own account and set to start whenever they sign in to the computer. Every install leaves an entry in the Start menu (on a Mac, the app in the person's own programs folder) named after the product, which starts the installed app. Set-up starts the app at once and checks about 3 seconds later: "the app is running (check your tray)" (menu bar on a Mac), or a warning that it did not stay running, how to start it by hand and where its log is. Started from a remote session, the app is started in the editor's own desktop session, not in the remote one.

Everything the app needs keeps running while it runs, on Windows and on macOS alike: any long-running part of the app's work that stops is brought back (see "The app keeps its own work going when part of it stops"), and nothing the app needs dies with an update. A wrong or unreadable setting never stops the app starting: it starts, shows its icon and names the setting that is wrong (see "A damaged settings file never runs the computer on the wrong settings").

### Only one copy of the app ever runs on a computer

Starting the app while it is already running does nothing except say so. On Windows a message titled with the product's name reads "CC Sync is already running. Look for the CC Sync icon in your system tray (you may need to click the ^ arrow next to the clock)." On macOS an alert reads "CC Sync is already running." with "Look for the CC Sync icon in the menu bar." When the running app has no icon (see "On Windows the icon comes back by itself, and a computer without it keeps working"), starting it again opens its settings window instead.

A copy left over from a crash or a restart never stops the app from starting, and a reused process number from before a reboot is never taken for a running copy. When the check itself cannot work, the app starts anyway. When a new version takes over from the running one (an update, or the editor's restart), it waits for the old one to be fully gone, never leaves the computer with no app running, and never leaves two running.

- Windows and macOS: on Windows the taskbar shows the product's own icon for the app's windows.

### An app that dies on its own is started again within about ten seconds, and says so

When the app dies without being asked to (a crash, a crash inside the system's own code, a Force Quit on macOS, a pulled power cord), it is started again about 10 seconds later, unless someone started it in the meantime, at most three times in an hour. After three relaunches within an hour it is left down until the next sign-in to the computer, and the admin is told. It is never relaunched after Quit, after the editor signs out of the computer or shuts it down, after an update or a hand start replaced it, after an uninstall, or when it was ended on purpose (on Windows, ended from the command line). A freshly updated version that died before finishing its start is relaunched too.

The next start writes down that the last run did not end cleanly: "CC Sync (version V, started T) stopped without ever starting a shutdown", with when it was relaunched if it was, and what the system recorded at the moment it died, or a note to look in the Windows Event Log. The relaunched app notes that it was down for about 10 seconds and which relaunch this is. A deliberate stop (an update, Quit, an operator ending it, a shutdown or sign-out) is never counted as a crash: on the system's end-of-session notice the app records a clean exit at once, a cancelled shutdown records nothing, and a real power loss still counts as a crash.

The relaunch limit holds exactly, even when the app cannot save its records (a failed save is reported to the dashboard), and counts and waits survive the computer's clock stepping backwards or forwards.

- On its own: relaunches the app after a death nobody asked for.
- By hand: the editor turns automatic relaunch off in the app's settings; a crash then leaves the computer without the app until the next sign-in.
- Setting: Start CC Sync again after a crash. Does: relaunches the app about 10 seconds after it dies on its own, at most three times an hour. Default: on. Who: the editor on that computer. Applies to: a computer. Search words: crash, relaunch, restart, keeps closing, vanished.

### A version that cannot stay up is replaced by the version before

When a newly installed version keeps failing to start, the computer goes back to the version it ran before, the failed version is never installed again by itself, and the editor and the admin are told: "⚠ The vX update kept crashing, so CC Sync went back to the previous version. Your admin has been told". If there is no earlier version to go back to, the app is left down and the admin is told that a person must step in. See Releases and updates: Rolling back and withdrawing a build.


### Every crash is written down on the computer and counted for the admin

Every unexpected error in any part of the app writes a crash report on the computer, readable only by the editor's account: when, which version, which part of the app's work, whether it is an installed copy, the system, the error and the last 200 lines of the app's log. Passwords, keys and sign-in details are replaced with "<redacted>". Reports never overwrite one another; at most 20 are kept, the oldest going first. A failure the app recovers from by itself writes no crash report and never advises a restart.

The dashboard is told how many reports a computer holds and the newest one's name; the diagnostics list the newest 3. An admin is warned "background tasks have crashed" when a computer holds any crash report.

- Ways in: the editor's diagnostics, the per-computer view of the dashboard, the admin's alerts.

### The app keeps its own work going when part of it stops

Each piece of work the app does in the background (keeping an eye on Resolve, reading its media pool, working through this computer's projects, keeping the projects' files in step) is judged alive by whether it is doing its work, not by whether it exists. When one stops, or makes no progress for about 30 minutes (longer for a project whose turn is long), the app brings it back by itself, checking about once a minute: the first time at once, then after waits that grow from one minute, doubling, to at most ten minutes. After six in an hour it stops trying and says "this needs a person, not another restart" until the hour has passed. It never does this while the app is shutting down, nor while a window or a copy into the synced folder is open that it would cut off. A file-change watch that hangs (as one can on a drive formatted exFAT on a Mac) never freezes the app: the menu, the Resolve checks and syncing carry on.

What the editor and admin see:

- When syncing itself has stopped and is being brought back, the app's status and the dashboard say so, with the error once it has failed three times (see Sync: Saying truthfully what the sync is doing, "Syncing comes back by itself when it stops running"); a damaged installation says "Ask your admin to re-run the CC Sync installer on this computer."
- A notification when syncing was not running and has been brought back, and once, on the third failure, that it will not start, with the error.
- Three recoveries of one piece of work within an hour put a line in the app's menu, and in the settings window: "⚠ CC Sync keeps restarting its syncing (N times in the last hour), so syncing is stopping and starting. Copy diagnostics for your admin".
- The admin sees, per piece of work, how many recoveries in the last 24 hours and the last hour, when, and the last error; these survive a restart of the app and are kept for 24 hours. When there have been 3 or more in 24 hours the admin is warned "CC Sync keeps restarting itself", with the fix: ask the editor to copy diagnostics.

Nothing is brought back while the editor has paused syncing or an admin has stopped it for the whole studio, or while that cannot be told. Every automatic retry grows its wait to at most 30 minutes, never piles up duplicates, and starts again promptly once the other end answers. Long work that keeps making progress is never cut off by a fixed clock; it is stopped only when it has made no progress for a set time. Anything the app schedules keeps running on battery, and work that stops anyway shows on the computer and the dashboard.

- On its own: brings back background work that stopped or stopped progressing.
- By hand: the editor turns automatic recovery off in the app's settings; the status then says "... it is not being restarted: automatic restarts are switched off on this computer".
- Setting: Bring stopped work back automatically. Does: lets the app restart its own syncing and background work when it stops. Default: on. Who: the editor on that computer. Applies to: a computer. Search words: restart, recover, stopped, background, watchdog.

### The editor can restart the app

"Restart CC Sync" in the menu and "RESTART CC SYNC NOW" in the settings window restart the app in place. A restart is refused, and nothing is restarted, while work it would cut off is under way: "Can't restart while a CC Sync window is open or media is being copied in. Try again once it's done." If the restart fails, the editor is told and the app carries on running. No automatic restart or update ever starts during a copy, a relink or a sharing job.

The app's link to Resolve is renewed on its own whenever Resolve quits and is started again; the editor never has to restart the app for it (see Resolve on the editor's computer: Connecting to Resolve's scripting: launch, stalls and death).

- Who: the editor at the computer.
- Ways in: the menu, the settings window.

### Quitting stops everything cleanly and asks first if media is being copied in

The menu line reads "Quit CC Sync (nothing syncs until you start it again, or sign in to this computer again)", with "Restart CC Sync" beside it. Quit stops everything the app started, waiting up to 40 seconds for each, and leaves nothing running behind it: shared work the computer held goes back to the other computers (see Work shared out across the computers: Stopping and cancelling), indexing carries on from where it reached at the next start, a reminder about a sync drive pulled with work owed is kept, and the next start does not report a crash. At every start, anything a previous run left running is stopped first. On macOS, if a window is still stuck 10 seconds after Quit, the app ends itself so it can be started again.

When media is being copied into the synced folder, Quit first asks: "CC Sync is copying file I of N into your synced folder. Quitting now abandons the file it is on. The rest is not copied and Resolve is not pointed at it. Quit anyway?" with "Keep copying" (the default, and focused) and "Quit anyway". Without a file number or total the question reads "CC Sync is copying N files into your synced folder.", "CC Sync is copying a file into your synced folder." or "CC Sync is copying files into your synced folder." Left unanswered for 2 minutes, the quit goes ahead. If the app cannot tell whether a copy is running, or cannot show the question, it quits. An open question never freezes the app's other windows.

- Who: the editor at the computer.

### A computer doing heavy work stays awake and warns before shutting down

While the computer is doing heavy work for b-roll or music (analysing, or downloading the one-off analysis download it needs), it is kept from idle sleep, and a shutdown is met with "still indexing <b-roll|music> (N <clips|tracks> left)" or "still downloading what <b-roll|music> analysis needs". This holds only while work is really moving or moved recently, and never for longer than 8 hours in a row. For syncing, see Sync: Uploads that cannot resume, shutdown and sleep.

- When the b-roll archive is off: nothing is said about b-roll work.
- When music is off: nothing is said about music work.
- Windows and macOS: a Mac laptop on battery sleeps when its lid is closed whatever the app does. When uploads are owed, the editor is warned that closing the lid on battery stops them, and the dashboard shows this as the reason the computer stopped.

### On Windows the icon comes back by itself, and a computer without it keeps working

At start the app keeps trying to place its icon for about two minutes; notifications raised meanwhile (at least the five newest) are shown once it is up. If Windows never accepts it, syncing carries on, the admin is told, and the editor is shown a window saying CC Sync is running without its icon and that starting CC Sync again from the Start menu opens its settings. When the Windows taskbar restarts (Explorer restarting, for example), the icon is put back by itself, retrying about once a minute until it is, and keeps updating; meanwhile the menu never goes unresponsive for more than about 2.5 seconds.

- Windows and macOS: Windows only.

### On macOS the app says when the menu bar has no room for its icon

About 3 seconds after starting, the app checks whether macOS really placed its menu-bar item where it can be seen (not hidden behind the camera notch of a notched screen, not left off a full bar). If it is not visible, the editor is told: "CC Sync is running, but the menu bar is full so its icon can't be shown. Free a menu bar slot (System Settings, Control Center) and restart CC Sync." The dashboard shows whether that computer is reporting, whatever its menu bar shows.

- Windows and macOS: macOS only.

#### Lessons

- Met: APP-045, APP-046, APP-047, APP-048, APP-049, APP-050, APP-051, APP-054, APP-055, APP-056, APP-057, APP-058, APP-059, APP-060, APP-061, APP-062, APP-063, APP-064, APP-065, APP-066.

## The tray or menu-bar icon and its menu

### On macOS the app lives only in the menu bar

On macOS the app has no Dock icon, no application menu and no entry in the app switcher: it is reached only from its menu-bar icon. If macOS will not allow that, it keeps a Dock icon and carries on.

- Windows and macOS: on Windows the app's icon sits in the system tray.

### The icon shows at a glance whether all is well, needs attention, or has a problem

The icon is the bare product mark; its shape never changes, only its colour and its brightness. It has three states, decided in this order (the first that applies wins):

| State | When | Colour and motion |
|---|---|---|
| Problem | a transfer has failed; this computer is not set up; this computer's clock is wrong against the server's; a transfer has stopped moving; keeping the projects' shared files (audio, graphics, subtitles, project files) in step has stopped working on this computer | red, breathing |
| Needs attention | the sync drive is away (unplugged, not answering, or mounted in the wrong place); nobody is signed in; syncing is paused or stopped; any other reason syncing is held; Resolve has not answered the app for more than 20 seconds; something is transferring | amber: breathing while files are really moving, steady otherwise |
| All well | signed in, not paused, set up, caught up and nothing holding syncing | green, steady |

Whenever anything holds syncing, the icon leaves green. Nothing being ticked for this computer never changes the icon, and a computer wired to the server, which syncs nothing, shows green unless something is wrong. If the app cannot work out its own state, the icon shows "needs attention". Breathing is one slow breath every 3 seconds, never dimmer than about half brightness, and only while there is a problem or while bytes are really moving (a transfer that claims to be syncing with no server connected does not count); when it stops, the icon returns to full brightness. The icon reads clearly on light and dark taskbars and menu bars. The icon and its hover line are brought up to date within about two seconds of a change.

### Hovering over the icon shows one short line saying what this computer's syncing is doing

The line always fits the space Windows allows (128 units, counted the way Windows counts them, emoji and rare Chinese characters included); a longer sentence is shortened in the middle so its closing instruction survives. The first that applies is shown:

1. "CC Sync: NOT SET UP (nothing syncs)".
2. The sync drive is away: "CC Sync: PAUSED (<phrase>)", or "CC Sync: PAUSED (<phrase>, <what is owed> still to go)" when something is still owed. The phrase is "drive disconnected", "the drive is mounted at the wrong place" or "the drive is not answering".
3. "CC Sync: not signed in (nothing syncs)".
4. "CC Sync: PAUSED".
5. "CC Sync: PROBLEM with <kind of transfer>", where the kind is "Uploads", "Proxies", "Everything else, both ways" or "Originals you asked for".
6. Something moving: "CC Sync: syncing · <end of the project's name, about 40 characters> · <speed>/s · <time> left".
7. The reason syncing is held: "CC Sync: <sentence>".
8. "CC Sync: waiting, not connected to the server (N files owed)".
9. Files that will never upload because the server holds a file of the same name and a different size: "CC Sync: will not upload <up to three names with sizes>", for example "A001.mov (yours 4.2 GB, the server's 3.1 GB)".
10. A YouTube download running on this computer: "CC Sync: downloading YouTube clip 3/12 (...)".
11. Otherwise "CC Sync: up to date".

When the whole line stays within 120 characters, "syncing" and "up to date" also carry, in this order: proxies being made here (" · making N proxy files", or " · making proxies", with ", next at P%" for the clip furthest along; otherwise " · N need proxies" or " · 1 needs a proxy"); one piece of analysis, b-roll before music (" · fetching what <b-roll|music> analysis needs P%" or " · indexing <b-roll|music> D/T"); and, on "up to date" only, the Resolve counts that did not fit on the menu (" · Resolve: <phrases>").

- When the b-roll archive is off: no b-roll phrase. When music is off: no music phrase. When YouTube downloads are off: line 10 never appears. When the help for the editing program is off: no Resolve phrase.

### The app's status line says where syncing has got to

The app has one status sentence, the same words in its menu and at the top of its window (see Sync: Saying truthfully what the sync is doing, "The app's menu says in one phrase what syncing is doing now"). Besides the states written there, it says:

- "starting up" while the app starts;
- "Waiting for the server: this computer has no plan saved yet" when the server cannot be reached and this computer has never received its list of projects;
- "Waiting for the server: using the plan saved on this computer" when the server cannot be reached, so the last list received is being used;
- "Nothing to sync yet: no projects are ticked for this computer" when the server answered with an empty list (a normal, calm state, never a warning);
- which project is being synced, "syncing <project> (<n>/<total>)", or "uploading <project> (<n>/<total>)" when that project is ticked upload only;
- "idle between passes".

The project is named by its label, else by its place on the server.

### Clicking the icon opens the menu at once, and it never shifts or freezes while open

A click opens the menu within half a second, and highlighting follows the pointer instantly, every time, whatever Resolve or the sync is doing. While the menu is open nothing about the icon, its hover line or the menu itself changes, so an item never moves under the pointer; changes wait until it closes and appear within about a quarter of a second of it closing. The app never asks Resolve anything while the menu is open, and long readings of a big timeline or media pool are paced so the menu keeps answering throughout. With the dashboard unreachable the menu is exactly as quick as online: the dashboard is tried again on a schedule, never on every refresh.

Greyed lines cannot be clicked; lines with an on or off state show a tick; an empty group of lines never leaves a stray divider. Every line stays short, about 80 characters at most, with the full explanation in a window.

- Windows and macOS: on Windows a right-click, a left-click and a double-click all open the same menu at the pointer, and the menu always opens fully clear of the taskbar, docked or auto-hidden, on whichever edge of whichever screen it sits. On macOS the item sits in the menu bar and a click opens the menu.

### The menu holds about ten everyday lines

The menu is short: about ten everyday lines. This computer's role and every other control live in the settings window the menu opens. As a starting point, from the top:

1. The running version, greyed.
2. Who is signed in, greyed, with a sign-in line when nobody is (see "The menu says who is signed in and offers to sign in").
3. What syncing is doing now, in one phrase (see Sync: Saying truthfully what the sync is doing, "The app's menu says in one phrase what syncing is doing now").
4. The prompts that apply now (below), and the lines for work under way (see "The menu carries a line for each piece of work under way").
5. "Sync now", which starts every transfer this computer has switched on at once instead of waiting (see Sync: Studio-wide stops and the editor's pause).
6. Pause or resume syncing: the editor's one pause, which stops everything and holds across restarts, sign-in and updates until they resume (see Sync: Studio-wide stops and the editor's pause).
7. "Open my sync drive".
8. "Open dashboard".
9. "Settings…".
10. "Restart CC Sync" and "Quit CC Sync (nothing syncs until you start it again, or sign in to this computer again)".

The prompts each appear only while their condition holds, and the group can be empty:

- "► Accept the licence agreement to start syncing…" while the licence holds syncing (see "Nothing syncs until the licence is accepted, and the app asks within a minute").
- "Set up '<project name>' on the server…" while the project open in Resolve has no home on the server.
- "► N LUT(s) only on this computer: share with the team" (see Resolve on the editor's computer: Colour look-up tables (LUTs)).
- "► Resume downloads…" after downloading stopped itself as a safety measure or because the sync drive was nearly full: the one place in the app where downloads are started again (an admin can also do it from the dashboard; see Sync: Safety stops, and Sync: Disk space).
- "► Stop the YouTube download".
- An offered version of the app (see Releases and updates: Offering an update to a computer).

Every line answers when clicked: it either does what it says or says "not now" with the same reason that is holding syncing.

- When a part is off: its prompts and lines are absent. With the help for the editing program off, the project set-up prompt and the LUT prompt are absent; with YouTube downloads off, the YouTube prompt is absent.

### The editor opens their sync drive from the menu

"Open my sync drive" opens the sync folder in Explorer or Finder. With none set up: "This computer has no sync drive set up yet: open Settings, THIS COMPUTER." If the folder is not there: "CC Sync cannot open <path> right now: it is not there. If it is on a drive you unplug, plug it back in." If opening fails: "CC Sync could not open <path>." Every path shown to the editor uses their own system's separators, so it can be pasted into Finder or Explorer. Wherever the app offers "show in folder" for a file, it opens the containing folder with the file selected, for paths with spaces and Chinese characters alike.

### The editor opens the dashboard from the menu

"Open dashboard" is present only when the dashboard's address is known. It opens the address the site publishes for people's browsers, reachable from wherever the computer is, and the address this computer reports to only when the site publishes none. Every other link the app opens in the browser (the help pages, the project set-up page) uses the same address. If no browser can be launched: "Couldn't open a browser. The dashboard is at <address>".

### Field backup opens from the menu

While the camera cards part is on and field backup is on for this computer, "Field backup..." in the menu opens the field backup page (see The Footage Sorter and camera cards: Downloading originals and sharing folders). If that page cannot be opened, only it is lost; the rest of the app carries on.

- When camera cards with the Footage Sorter is off: the line is absent.

#### Lessons

- Met: APP-070, APP-071, APP-072, APP-073, APP-074, APP-075, APP-077, APP-078, APP-079, APP-080, APP-081, APP-082, APP-083, APP-084, APP-085, APP-086.

## Windows, dialogs and notifications

### Notifications are the operating system's own, headed with the studio's name and mark

Every notification is the operating system's own message, shown at the app's icon and headed with the studio's brand (read at the moment it is shown) and the product's mark; on Windows the taskbar and notifications show the product, never the program file's own icon or an inner name. With no icon, notifications wait (see "On Windows the icon comes back by itself, and a computer without it keeps working").

A notification too long for the system (over 250 characters) is shortened by cutting the middle, keeping its opening and its last sentence, so the closing instruction survives; its title is cut to 60 characters. On macOS, line breaks inside a notification become spaces. The same notification is repeated at most once every 30 minutes, and the first one is never held back. A sync drive pulled out gives one warning, and reminders follow only while uploads the server does not yet have are owed (see Sync: The sync drive).

Any download the app starts announces itself: a notification names it and says where to see its progress, and another says when it is ready.

### The app's windows never block one another

Any number of the app's windows can open and close, together or one after another, in any order, without the app ending; asking for a window that is already open brings it forward instead of opening a second. A prompt the app raises by itself (a question about a project, a licence, a new project with no home) is never lost because another window is open, never merged with a prompt about a different project, and never shown twice; a prompt that is not urgent may instead be asked again later. Every window can always be closed, a second piece of work in the same window finishes normally, and quitting always works. A window that fails while opening is closed and the failure reported, and the next click opens one working window. A folder picker left open never silently holds back fixes, settings or updates: the app says what is waiting on it, and an update waiting on an open window shows that on the dashboard.

Actions that would cut off what an open window is doing (a restart, an update) say so and wait (see "The editor can restart the app").


### Nothing the app runs ever flashes a console window on Windows

Every transfer, check and helper the app runs on Windows runs without a console window appearing, whether the app was started by set-up, at sign-in or after an update.

- Windows and macOS: Windows only.

### Confirmations default to the safe answer and every window works from the keyboard

A confirmation has a heading, its text, CANCEL (or another chosen label for not going ahead) and the action. It stays on top of other windows; the focus starts on CANCEL; Escape cancels; Enter presses only the focused button, so it never confirms by itself; closing the window cancels; and if it cannot be shown, the answer is cancel. A notice has one OK button, and Enter and Escape both close it. Every question is a correct sentence in every one of its wordings.

In every window Tab reaches each button with a visible focus ring, Enter (the keypad Enter too) and Space press the focused one, and a disabled button ignores them. Every window shows the product mark as its icon, as does its taskbar button on Windows.

The set-up wizard is one window whose pages replace each other. It grows taller on its own when a page needs room (never wider, never shrinking, never taller than the screen less a margin), and each page's buttons are the last thing to lose space. An enabled Next takes focus when a page opens; on form pages the first empty field does. Enter in a text field presses the page's main action (Next on the role page, verify on the sign-in page), and Enter never presses a disabled button.

### Long background work has a progress window the editor can close and reopen

Every long piece of work on the computer (proxies being made here, b-roll analysis, music analysis) has a progress window. It opens by itself once when a piece of work starts (if the editor closes it, it stays closed for that piece of work) and from the "SHOW ... PROGRESS" buttons in the settings window. It is never forced on top. It holds:

- a heading ("INDEXING B-ROLL", "INDEXING MUSIC", or the proxies' heading) and an optional second line;
- three bars: what is being fetched (for example the one-off download analysis needs, with its size), the current item ("<label> - P%", with its step), and overall ("D of T clips · F failed · ~12 min left", or "estimating…" until 2 items are done; "tracks" for music), the time left following recent items more than older ones;
- a note line: the current warning, or what the work is waiting for (for the editor to be away, for Resolve to close);
- in red, up to 5 failures as "✗ <name>: <reason>", then "and N more";
- PAUSE, RESUME, START NOW and CANCEL, each enabled only when it can act; START NOW runs work that was waiting for the editor to be away or for Resolve to close.

It updates several times a second. Closing it leaves the work running, and it can be opened again; when the work finishes (every item done or failed) it closes itself 4 seconds later. Only one window per piece of work opens. Each new warning also appears once as a notification. The page in the browser shows the same progress (see The b-roll archive: Bringing new footage in, and Music: Adding tracks to the library).

- When the b-roll archive is off: no b-roll progress. When music is off: no music progress.

### The editor sees each ticked project with what it is doing and why

The app's window lists every project ticked for this computer (see Sync: What syncs where, "The app lists this computer's ticked projects and how each is doing"). Each row has the project's name, its mode, its state, the state of its uploads, its proxy downloads and its other project files, and a sentence:

- blocked, with the reason, when a move made on the server could not be followed on this computer;
- blocked, "Waiting for its filter list from the server. It starts by itself once that arrives." when the product cannot yet confirm which files in that project must never sync;
- paused, "Sync is paused on this computer.";
- syncing, "Syncing now (N of M).";
- waiting, "Waiting its turn." for projects still due this round, and waiting with no sentence otherwise.

Only the project being synced shows live states; the others show "waiting" or "paused". Proxy downloads show "off" for an upload-only project or a computer that keeps no proxies; other project files show "off" for an upload-only project. The same window lists the projects waiting for their filter list, one sentence for each shared library or included folder that is not working (the only place in the app it is listed; the status sentence names it only when it is what holds syncing, and the dashboard shows it too), and the last few moves made on the server to this computer's projects with what happened to each (old and new place, when, and whether Resolve was relinked; see Proxies and file moves: Following a move on an editor's computer). An empty plan says to tick projects on the dashboard.


### When the project open in Resolve has no home on the server, the editor is asked once

When the project open in Resolve has no home on the server, the editor is asked once ever for that project (names compared ignoring letter case, remembered across restarts), and only while it is the project open. The question, headed "NEW PROJECT", reads: "Project '<name>' isn't set up on the server. No media will sync for it until it has a home. Set it up now? (Opens the dashboard in your browser.)" "SET UP NOW" opens the dashboard's page for setting up a project, with the Resolve project's name filled in (see The dashboard: Projects). Declining, closing, or having no screen to ask on counts as asked, and a notification says "You can set up '<name>' later: open the CC Sync menu and choose Set up '<name>' on the server." While the project still has no home, the menu line "Set up '<name>' on the server…" opens the same page with no question. When the dashboard stops naming it, or another project is opened, the line goes.

- Ways in: the one-time question, the menu line.
- When the help for the editing program is off: nothing is asked and the line never appears.

#### Lessons

- Met: APP-087, APP-088, APP-089, APP-090, APP-091, APP-092, APP-093, APP-094, APP-096, APP-097, APP-098, APP-099, APP-100, APP-101, APP-102, APP-103.

## Telling the editor what is wrong

### At start the app says at once if this computer will not sync, and confirms a finished update

Shortly after starting, the app shows one of:

- "NOT SYNCING: CC Sync isn't fully set up on this computer. <where to copy diagnostics>." when a setting is missing or wrong;
- otherwise, when the licence has not been accepted, "NOT SYNCING: <the licence sentence>", and the licence is offered (see "Nothing syncs until the licence is accepted, and the app asks within a minute");
- on the first start after an update, about three seconds in, "Update complete. Now running v<version>."

If the tray or menu-bar icon cannot be shown, the app still runs and syncs without it.

### A computer that is not fully set up names what is missing

The worst set-up problem is shown as one sentence saying what is missing and what to set. In the settings window, "WHAT IS NOT SET UP" lists up to three problems, worst first. While a problem stands, the sync status reads "NOT SYNCING: this computer isn't fully set up: <first problem, or 'see the log'>", and the menu carries a greyed line "⚠ NOT SET UP: nothing will sync (Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN)".

The app checks its settings at start and whenever they are saved, and says which problems stop all syncing and which only switch one feature off.

Problems that stop all syncing until fixed:

- the settings could not be read (see "A damaged settings file never runs the computer on the wrong settings");
- this computer's sync folder is not set, is blank, or does not exist ("nothing syncs until it names this computer's sync folder");
- no dashboard address is set (nobody can sign in, so nothing syncs);
- a timing or count setting that must be a positive number is not one.

Problems that only weaken one feature:

- the folder suggested for media the editor adds is blank (the suggestion becomes the top of the tree);
- making proxies on this computer is on but the computer cannot make them (see Proxies and file moves: Making proxies on editors' computers);
- an unknown computer role (treated as a remote editor's computer).

### A damaged settings file never runs the computer on the wrong settings

Every time the computer's settings read cleanly, the app keeps an exact copy of them as the last good settings. If they later cannot be read:

- with a last good copy, the app runs on that copy and says the settings could not be read, so the last good settings were loaded instead;
- with no good copy, every setting is its default and the app says that every setting is a default, not what was set.

Either way no syncing starts until a person puts the settings right. A setting with a nonsense value (a negative wait, a word where a number belongs) never crashes the app and never stops it starting: that one setting falls back to its default, and the app names it.

### A dashboard address that is plain http on the public internet is never used

A dashboard address that is plain http to an address on the public internet is never sent anything: the sign-in, reports and diagnostics would cross it unencrypted. Saving one in the app's settings is refused, and when one is found in use the editor is told once: "The dashboard address is plain http on the internet, so CC Sync will not send anything to it. Ask your admin for its https address." Plain http on the studio's own network or private network is accepted, with the note "This address is not https. It is fine on your studio network." A check that cannot decide whether an address is public never refuses. An address that does not begin with http or https is named as wrong.

### A failed transfer is explained in plain words

The raw error goes only to the log and the diagnostics. The editor sees:

| What went wrong | What the editor is told |
|---|---|
| the sync drive is mounted in the wrong place | "<Drive> is mounted at the wrong place, so syncing is paused. Nothing was deleted. See the CC Sync window for what to do." |
| the sync drive is gone | "<Drive> is disconnected, so syncing is paused. Plug it back in and it resumes on its own: nothing was deleted." |
| keeping the projects' shared files in step is not running on this computer | a sentence saying audio, graphics, subtitles and project files are not syncing, and to copy diagnostics for the admin |
| a project folder was deleted while still ticked | "A project folder was deleted on this computer while still ticked. Untick it on the dashboard, or use Tray > Settings > REMOVE '<project>' FROM THIS COMPUTER." |
| a transfer stopped moving | "This transfer stopped moving and was restarted. If it keeps happening, check the drive is connected." |
| the disk is full | "Your disk is full. Free up space and it will resume." |
| the server refused this computer's sign-in | "The server rejected this computer's login. <where to copy diagnostics>." |
| the server cannot be reached | "Can't reach the server.", with an instruction to check the computer's connection to the studio's network |
| anything else, or no error at all | "Something went wrong. <where to copy diagnostics>." |

Every status names its real cause in plain words. A deliberate safety pause reads as what it is, with when it will resume, never as an error, and a warning about a safety stop never suggests restarting (which would clear it): it names something the editor can do, such as copying diagnostics for the admin.

### The editor is told when the dashboard is not hearing from the computer, and when the clock is wrong

The computer remembers across restarts when a report last got through and how the last one ended, and the dashboard is told how many have failed in a row. A refused sign-in reads differently from "server unreachable" everywhere. After ten or more failed reports in a row, the settings window shows:

- the sign-in refused: the one warning with its SIGN IN AGAIN… button (see "A sign-in never expires on its own, and a refused one is said plainly");
- never accepted: "⚠ The dashboard has never accepted a report from this computer. Your work may not be visible to your admin. Copy diagnostics for them";
- otherwise: "⚠ The dashboard has not accepted a report for <duration>, so your admin cannot see whether this computer is syncing".

When this computer's clock is 60 seconds or more off the server's: "⚠ This computer's clock is <how far ahead or behind> the server's. Sync will not work correctly until it is fixed" (see Sync: Clocks and file age).

### The menu carries a line for each piece of work under way

Each line is present only while it applies:

- originals the editor asked for: for example "Bringing originals: 12 of 80, 140.0 GB to go";
- a YouTube download on this computer: "Downloading YouTube clips" (total unknown), "Downloading YouTube clip 3/12 (4.2 MB/s, 38%)" (speed and percentage only when known), or "Converting YouTube clip 3/12 to a format Resolve can decode" while a clip Resolve could not decode is converted; the clip number is done plus failed plus one, never above the total;
- "Waiting for you to finish signing in in the browser (240 s left)" during a YouTube sign-in (no countdown when it is unknown);
- "CC Sync is <transcribing|converting|running a job> for the studio while you work because <reason>", only when an admin has sent a piece of work to this computer whatever it is doing (see Work shared out across the computers: Choosing who runs what);
- a warning that this computer could not get what YouTube downloads need to process video;
- "N b-roll clips could not be indexed: <first file name> (<reason>), and M more" (or "... could not be indexed. See the log" when the reasons are unknown).

- When YouTube downloads are off: no YouTube line. When the b-roll archive is off: no b-roll line.

### The settings window ranks its warnings, merges repeats and shows at most six

Every problem the app finds on this computer is shown in its menu or settings window and counted in its report to the dashboard until it clears, even with nothing ticked or with the feature it belongs to off. The settings window gives every warning a rank:

- Blocking: any stop, a safety stop, a safety state that could not be saved, projects waiting for their filter list, failed reports, a wrong clock, a transfer that stopped moving, a full disk, the summary of what holds syncing.
- Warning: a name clash, files dated in the future, files edited on two computers, problems with included folders, a renamed project, saved crash reports, repeated recoveries, failed or reverted updates.
- For information: clips skipped for now, files that can be recovered, and the summary of what holds syncing when it is only that nothing is ticked.

Identical sentences are merged into one with " (xN)". At most 6 show, then "and N more" with "SHOW ALL", which becomes "SHOW FEWER"; the choice lasts until the app restarts. Among them:

- "⚠ N clips skipped for now and still not syncing - Settings > SCAN WHOLE PROJECT offers them again" (clips the editor put off for 30 minutes; see Resolve on the editor's computer: Fixing media: copying in, rehearsals and undo);
- "⚠ A background task failed on this computer (N reports saved). Copy diagnostics for your admin";
- after 8 failed attempts to install an update: "⚠ CC Sync could not install the update to vX N times, so it has stopped trying. <where to copy diagnostics>";
- "⚠ The vX update kept crashing, so CC Sync went back to the previous version. Your admin has been told".

When anything is wrong, the help and diagnostics are in reach at once, without scrolling (see "The settings window gathers everything about this computer and keeps itself current").

- When the help for the editing program is off: no line about clips or scanning a project.

### Every message points at the smallest action that clears it, and where it lives

Every message about a problem points at the smallest action that clears it and says where in the app that action is; an editor is never sent to their admin, or to run set-up again, for something one click fixes. Every sentence that says where to click names a control that exists, checked automatically whenever the product is built. Wherever the product asks for a computer's diagnostics, it names the one place they are copied: "Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN". Any menu or settings action that fails says: "'<action name>' didn't work. Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN." Every age, deadline and length of keeping shown to an editor is the true value under this site's settings.

### The editor sends the admin a full description of the computer with one button

"COPY DIAGNOSTICS FOR YOUR ADMIN" copies a plain-text description of the computer to the clipboard, sends it to the dashboard for the admin (named with the person, the computer and its permanent identity), and says "Diagnostics copied, and sent to your admin's dashboard." When the clipboard cannot be used: "Couldn't reach the clipboard. The diagnostics were written to the log and sent to your admin's dashboard." Nothing is sent when no dashboard address is set or nobody is signed in; a failed send is said.

The description covers, each part saying so in its own line when it cannot be read while the rest still appears:

- the time, the app's version, the system, and whether this is an installed copy;
- who is signed in (or "NOT SIGNED IN");
- whether syncing is on, paused, stopped or held, and why;
- the sync folder, and the sync drive's state (including whether macOS is refusing access to it);
- the server it syncs with;
- Resolve's open project and whether the app can reach Resolve ("not asked yet since CC Sync started", "connected", or "NOT CONNECTED: <reason>"), and the counts of clips outside the shared tree, on a wrong drive, missing, skipped for now and skipped for good, with the last scan time;
- the update history: attempts, failures, a version given up on because it kept crashing and was rolled back ("do not install it by hand") or failed N times, and a version refused, since when and why;
- every set-up problem and warning;
- which projects are being synced, and each kind of transfer's full state;
- whether the computer is taking shared work, the work it holds and how long it has been idle (where unknown means "not idle");
- the last report the dashboard accepted ("NEVER (nothing this computer has sent was accepted)"), failures in a row, and the clock difference with the server ("+Ns (this computer is AHEAD/BEHIND)" or "not measured yet");
- recent crashes and recent recoveries of the app's own work;
- the last 40 lines of the log.

The same description also reaches the dashboard by itself when a kind of syncing newly falls into an error, and when an admin asks the computer for it (see The dashboard: Reports from computers). An admin's request counts as answered only once it has succeeded, and is tried again until then.

- Who: the editor at the computer.
- Ways in: the help actions of the settings window; on its own when syncing falls into an error; on an admin's request from the dashboard.
- When the help for the editing program is off: the Resolve lines are left out.

### The help actions are in reach from the settings window

The help actions are:

- "COPY DIAGNOSTICS FOR YOUR ADMIN";
- "OPEN LOG";
- "HOW CC SYNC WORKS" and "WHAT DO THESE MEAN?", which open the dashboard's help page and its glossary, shown only when the dashboard's address is known (without it: "This computer does not know where your dashboard is, so it cannot open the help page."; with no browser: "Couldn't open a browser. The help page is at <address>");
- the offered version of the app, when there is one (see Releases and updates: Offering an update to a computer);
- "OPEN-SOURCE LICENCES", the licence texts carried with the app (or "This copy of CC Sync does not carry the open-source licence texts. Your admin can send them, or see Help, Legal on the dashboard.");
- "Support: <the support contact from the site's settings>";
- the app's version.

- Name and search words: Help. Search words: help, diagnostics, log, support, licences, version.

### Admins are told when the product's pages cannot reach the app on a computer

When the product's pages can send to Resolve on a computer but the app there cannot take the requests (another program on the computer is in the way), the app keeps trying, shows it in its menu and settings window, and reports it; the admin is warned "Send to Resolve cannot work on a computer", with the fix: quit whatever program is in the way, then restart CC Sync from its icon. It clears once the app can take requests again.

- When the help for the editing program is off: the warning is not raised (nothing sends to Resolve).

### Every install step is shown live and kept in a log the editor can copy

The install page has a scrolling log showing every step as it happens, and below it the path of a log file the wizard keeps for each run, never deleted. A copy-log button puts the whole log file (or the box's text when there is no file) on the clipboard and shows "[ COPIED ]" for about a second. If the file cannot be made, the page says so and tells the editor to use copy log before closing the window. Finish pages repeat the log's path and the copy-log button.

### An install that finished with something missing says NOT READY and lists what

Every required piece the install could not set up becomes a warning. The finish page is then headed "COMPLETED WITH N WARNING(S): NOT READY YET" ("INSTALLED WITH ..." on a wired computer) and says that the computer is NOT ready to sync, not to tell the admin they are set up until the problems are fixed, but to send them this list instead; up to 6 warnings are shown, then "... and N more. All of them are in the install log".

#### Lessons

- Met: APP-108, APP-109, APP-110, APP-111, APP-112, APP-113, APP-114, APP-115, APP-116, APP-117, APP-118, APP-119, APP-121, APP-122.

## Signing in, the computer's identity and the licence

### The editor types the dashboard address and it is checked before going on

At set-up the dashboard address is required ("ask your admin for it", with an example). A scheme the editor typed (http:// or https://) is always kept. When none was typed, https is tried first and http only if that fails; whatever was used is written back into the field and, on the next page, an amber note says the address had nothing in front and to go back and edit it if the one shown is wrong: a guess is never kept silently. The check says plainly whether the address is "not reachable" or reachable but "not a dashboard". An address that is plain http to the public internet is refused: "your password would cross it unencrypted. Nothing was sent. Ask your admin for the dashboard's https address." A check that cannot decide never refuses, and plain http on a local or private-network address is allowed with an amber note. A second press while the check runs is ignored, and editing the address during the check discards its answer. The same refusal is checked again at sign-in and at install.

### The editor signs in with the username and password their admin gave them

Nothing syncs and no report naming the person is sent until the editor signs in, at set-up or from the app. Signing in sends the username and password, with the app's version, the system, the processor kind and the computer's name (cut to 48 characters), and waits up to 15 seconds, never following a redirect. With no dashboard address set it is refused at once. The same limits on attempts apply as on the dashboard.

On success the computer is the editor's: the sign-in is kept on the computer, readable only by their account; syncing starts if nothing else holds it; any update the dashboard offers this computer, or the reason one is held back, comes with the answer (see Releases and updates: Offering an update to a computer); and, at set-up, the site's settings (tree name, drive letter, brand, which parts are on) are fetched and a copy kept, a copy no older than 30 days from the same dashboard being used where a value is needed and the fetch fails. Each computer has its own sign-in, labelled with the computer's name; signing in again on the same computer replaces that computer's, and a person may have at most 16 computers signed in, the least recently used one beyond that being signed out (see Accounts, privacy and the legal paperwork: How a computer proves who it belongs to).

On failure the editor sees the server's own sentence and what to do next, for every kind of refusal, and the password is cleared:

| Refusal | What the editor is told |
|---|---|
| wrong username or password | "invalid username or password" |
| the account is not one of this studio's | "'<name>' is not an account on this dashboard - ask an admin to create it" |
| the account is not allowed to sync | "'<name>' is not an editor on this dashboard - ask an admin to give the account the editor role" |
| the person is removed, suspended or disabled | the sentence for that case (see Accounts, privacy and the legal paperwork: Suspending, disabling and removing a person) |
| membership cannot be checked right now | "cannot confirm your account right now: try again shortly" |
| too many attempts | "too many sign-in attempts - try again shortly" |
| sign-in not available on the server right now | "sign-in is not available on this server right now - try again shortly" |
| the address is plain http on the internet | "Not sent: the dashboard address is plain http on the internet. Ask your admin for its https address." |
| a redirect | the dashboard answered with a redirect: ask your admin for its direct address |
| a reply that cannot be used (often a wrong clock) | "The server's sign-in reply couldn't be used. If this keeps happening, check this computer's clock is correct, then copy diagnostics for your admin (Tray > Settings > HELP)." |
| any other answer | "sign-in failed (HTTP N)" or the network error itself |

At set-up, step 3 says that the username and password are checked against the dashboard right now and the install will not go on if they do not match. A second press while checking shows "still verifying the last attempt...", and an answer arriving after the editor left the page is ignored.

- Who: an editor, on their own computer.
- Ways in: step 3 of set-up, the app's sign-in window.

### The sign-in window

The sign-in window is headed "► SIGN IN" and says: "Enter the username and password you use to sign in to CC Sync. This verifies that this computer is yours." and "Ask your admin if you do not have one yet." It has "username:" and "password:" (the password hidden), with the cursor starting in username, and CANCEL and SIGN IN; Enter signs in and closing the window cancels. Errors appear under the form: "username and password are both required", "sign-in failed: <reason>", or the server's own refusal (above). On success the window closes. It stays on top of other windows. If it cannot open: "Couldn't open the sign-in window. Restart CC Sync and try again."

- Name and search words: Sign in. Search words: sign in, log in, username, password, account.

### The menu says who is signed in and offers to sign in

The menu shows a greyed line "Signed in as <username>" or "NOT SIGNED IN". When nobody is signed in, it carries "► Sign in… (nothing syncs until you do)". The settings window shows the same identity line, with "SIGN OUT" while signed in and "SIGN IN…" otherwise. Signing out stops syncing and stops this computer reporting to the dashboard, and the status reads 'sign in required: use the menu's "Sign in..." to authenticate before syncing'. "Sign in again" runs the sign-in again while already signed in, for when the server has withdrawn a sign-in that still looks valid on the computer.

- Ways in: the menu's sign-in line, the settings window's sign-in and sign-out buttons.

### Nothing starts syncing on a computer nobody is signed in to

No path starts syncing on a computer nobody is signed in to: not resuming from a pause, not a restart, not an update, not the drive coming back. Resuming while nobody is signed in says "You're not signed in, so nothing will sync. Right-click the tray icon → Sign in…" and starts nothing.

### A sign-in never expires on its own, and a refused one is said plainly

A healthy computer never loses its sign-in by time alone. If the server ever refuses it (an admin withdrew it, the person was removed), syncing stops, the editor is told at once and reminded every hour until they sign in again, and the dashboard shows it. The reminder offers signing in again first:

- a notification: "Your CC Sync sign-in was refused by the dashboard - sign in again";
- in the menu, "► Sign in again (the server rejected this computer's sign-in)";
- in the settings window, beside the identity line, "⚠ The server rejected this computer's sign-in, so your admin cannot see whether you are syncing." with "SIGN IN AGAIN…".

Every one of these opens the sign-in window. When the refusal comes from this computer's clock being far off the server's, the editor is told instead: "This computer's clock is <N ahead of or behind> the server's, which is why your CC Sync sign-in was refused. Fix the clock (Windows: Date and time, Sync now) and syncing will start again." When the sign-in is accepted again, syncing starts by itself.

- Ways in: a notification, the menu, the settings window.

### Each computer has a permanent identity that survives renaming it

The app gives the computer a random identity the first time it needs one, and always reports it, so the server knows it is the same computer after its name changes. It is not a sign-in and is not taken from the hardware. An identity is made only when none exists: if the computer's identity exists but cannot be read, the app does not make a new one (that would look like a new computer), reports none, and tells the editor and the admin.

### When the identity cannot be read, the editor can give the computer a new one

The settings window then shows "⚠ CC Sync cannot read this computer's id file, so the server cannot recognise this computer again if you rename it. Syncing is not affected." with "GIVE THIS COMPUTER A NEW ID" and the note "the unreadable file is kept beside the new one". Pressing it asks: "CC Sync cannot read this computer's id file, so the server cannot recognise this computer again if you rename it. CC Sync will save a new id and keep the unreadable file beside it, so nothing in it is lost. Your syncing and your sign-in are not affected. If your admin is still looking at the old file, wait for them before doing this." with "GIVE IT A NEW ID". If the old identity has become readable meanwhile, it is kept. The answer is one of "This computer has a new id. It is reported from the next check in.", "CC Sync did not change this computer's id. <where to copy diagnostics>." or "CC Sync could not repair this computer's id file. <where to copy diagnostics>."; it never claims success when nothing changed. The new identity is reported at once, without a restart.

- Who: the editor at the computer.

### Nothing syncs until the licence is accepted, and the app asks within a minute

Nothing syncs on a computer until someone there has accepted the current licence (see Accounts, privacy and the legal paperwork: The licence a person accepts). The app offers it within a minute of starting, offers it again until it has been answered, counts closing it as unanswered, starts syncing as soon as it is accepted, and the dashboard names the licence as the reason the computer is not syncing. The menu carries "► Accept the licence agreement to start syncing…" while it holds syncing.

### Switching a computer between remote and wired is confirmed first

Switching a computer between remote and wired asks first and names the consequence plainly, and the direction that can move files out of the folder, to remote, needs the word REMOTE typed (see Sync: Wired or remote, "Switching a computer between remote and wired asks for confirmation").

#### Lessons

- Met: APP-123, APP-124, APP-125, APP-127, APP-128, APP-129, APP-130, APP-132.

## Settings, records and background work

### The settings window gathers everything about this computer and keeps itself current

"Settings…" in the menu opens the settings window: everything about this computer in one place, and every setting a person may change on this computer (none is reachable only by editing a file). It is resizable, and Escape or closing it closes it. Buttons along its top jump straight to each part of the window and stay visible while the rest scrolls. It updates itself within about two seconds of anything in it changing, and at least every 30 seconds, redrawing only what changed, keeping the editor's place and never flickering or dropping a click. A button that changes a setting or starts something does its work with the window left open, and the window shows the result. When anything in the window is a warning, the help actions (see "The help actions are in reach from the settings window") are brought to the front, so help and diagnostics are in reach without scrolling.

- Who: the editor at the computer.
- Ways in: "Settings…" in the menu; starting the app again when it has no icon.
- Name and search words: This computer's settings. Search words: settings, this computer, preferences, options, help.

### The settings window shows the dashboard address this computer uses, and warns when it is unsafe or wrong

The settings window shows "Dashboard address: <address>" when one is set, followed by the result of checking it: an error as "⚠ <sentence>", a lesser concern as a quiet note (for example plain http to a public address, see "A dashboard address that is plain http on the public internet is never used"). A check that needs the network may take a moment to appear, and a changed answer shows within about 5 minutes.

- Setting: Dashboard address. Does: the studio dashboard this computer signs in to, reports to and takes its projects, updates and site settings from. Default: none, set at install. Who: the editor on that computer, at set-up or in its settings. Applies to: a computer. Search words: dashboard address, server address, URL, https.

### The settings each computer holds

Each computer holds its own settings, set at install and changeable on the computer:

- the editor's name, used to suggest where media the editor adds should go;
- the computer's sync folder (required);
- the drive letter Resolve's clip paths use, from the site's settings (P: by default, also on a Mac), used to spot clips with the wrong drive;
- the folder inside the tree suggested for media the editor adds;
- where each library is on this computer (below).

The settings of the app's own working are below as setting lines. The other parts' settings on this computer are described with the part they belong to: wired or remote, keeping proxies, keeping the computer awake, the warning at shutdown, the recovery folder's size, the free space kept on the sync drive and the time for each project, each changed by the editor in this window for their own computer or by an admin from the dashboard, and the download safety limits, changed only by an admin (see Sync); pop-ups about clips outside the tree and how long a shown clip stays quiet, the warning when Resolve's scripting stops answering, attaching synced proxies, projects to leave alone, the shared LUT and stills links and grading from the server's originals (see Resolve on the editor's computer); analysing b-roll and music on this computer, the wait before work while the editor is away and whether it waits for Resolve to close, the free-space floor, where dropped files wait and how long finished drops are kept (see The b-roll archive, Music, and Work shared out across the computers); whether this computer takes shared work (see Work shared out across the computers: What a computer can honestly offer).

The b-roll archive is found on this computer at "Assets/B-roll Archive" inside the computer's tree, music at "Assets/Music" and projects at "Projects", unless a person sets another folder on this computer; with no tree set there is no b-roll default. On a Mac a library with no folder set is looked for as a mounted network volume of that name, or that name followed by -1 or -2 (macOS adds these when a volume of the same name is already mounted). A change takes effect without restarting the app. Setting the b-roll archive to a folder of one's own switches off fetching missing clips when sending to Resolve (see The b-roll archive: Sending a clip to Resolve).

- Setting: Where each library is on this computer. Does: points this computer at the b-roll archive and the projects in another folder than the studio's usual place. Default: the usual places inside the computer's tree. Who: the editor on that computer. Applies to: a computer. Search words: library location, b-roll folder, projects folder, archive path.
- Setting: How much the log records. Does: how much detail the app's log on this computer keeps. Default: normal. Who: the editor on that computer. Applies to: a computer. Search words: log, detail, debug, verbose.
- When the b-roll archive is off: no b-roll setting is shown. When music is off: no music setting is shown.

### A value set on the computer always wins

Each setting is its built-in default, then what the computer's role implies, then what the studio's site settings provide, then what is set on the computer. Anything set on the computer itself wins. A blank or zero value from the site never switches anything off on a computer.

### A setting changed anywhere changes only that setting, and an update never resets one

When a setting is changed, from the app's settings or by the dashboard, only that one setting changes; every other setting stays exactly as it was. If the change does not read back as written, the change is reported as failed. Every record the app keeps is replaced whole or left untouched, whatever the timing (a crash or a full disk in the middle of a save never leaves a half-written one), and an unreadable one gives the cautious answer or the last good copy, with a visible warning.

After any update or any re-install, every setting chosen on that computer is unchanged, including where Resolve is installed. An install writes only what it must: the signed-in editor, the dashboard address and whether this is a remote or a wired computer (always), the reporting choices (only when that page was shown), and, for a remote editor, the local folder and the studio's drive letter (from the site, else P:). Everything else, the editor's own changes included, is kept. Settings that cannot be read are set aside under a new name and replaced with defaults, with a warning.

### Site settings reach every running app within minutes

A change to the site's settings (a part switched on or off, the studio's name or logo, the help for the editing program) reaches every running app within minutes, with no restart, and an app that started without a connection picks the change up when it reconnects. A studio's logo is set once on the dashboard, reaches every computer, and survives updates.

### The product's pages reach Resolve on the editor's computer through the app, and only the studio's pages may

The b-roll, music and YouTube pages are served by the server, and Resolve can be driven only on the computer it runs on, so when an editor presses send to Resolve on one of those pages, their own browser hands the request to the app on their own computer. Only pages from the studio's own dashboard address may do this; an admin can add further exact web addresses that may. The dashboard address set in the site's settings must be exactly the address editors type in their browsers, and the site's settings say so; a refused request names both the address it came from and the addresses allowed. Nothing a page sends ever runs as a script on the computer, and repeated status checks from a page cause only a bounded amount of work.

If another program on the computer is in the way, sending to Resolve is simply absent: the rest of the app, syncing above all, carries on, and the problem is shown in the app and reported (see "Admins are told when the product's pages cannot reach the app on a computer"). Something unexpected inside a request is answered with "CC Sync failed to handle that request: see its log"; a request is never left unanswered.

- Setting: Send to Resolve from the product's pages. Does: lets the b-roll, music and YouTube pages send clips and tracks to Resolve on this computer. Default: on. Who: the editor on that computer. Applies to: a computer. Search words: send to Resolve, b-roll send, music send, browser.
- Setting: Other web addresses allowed to send to Resolve. Does: exact addresses, besides the dashboard's own, whose pages may send to Resolve on editors' computers. Default: none. Who: an admin. Applies to: the site. Search words: allowed addresses, origin, send to Resolve, refused.
- When the help for the editing program is off: none of this exists and the pages offer exports instead (see Resolve on the editor's computer).

### The app keeps a log and its other records within fixed limits

The app keeps a log on the computer of at most about 55 MB in total, older entries dropped first. A condition that keeps recurring is logged fully once when it starts, then as a count until it changes, so the log keeps days of history. If the place set for the log cannot be used, the app logs to its usual place, records which setting was wrong, and still starts; if even that fails, it starts without a log. Every other file the app keeps on the computer has a size or age limit and is removed when it passes it, half-written leftovers included, and every list a computer reports keeps the newest entries with a count of what was left out.

### The admin sees, read-only, the settings each computer last reported

The per-computer view of the dashboard shows, read-only and blank when not reported: how long the computer lends itself to shared work ("<n> min"; changed on the computer, in its settings); and, only while YouTube downloads are on, the YouTube terms ("accepted" or "not accepted", plus "downloads off on this computer") and the YouTube sign-in ("signed in", "signed in, needs a refresh", "expired: sign in again", "not signed in", "not used on this computer"), changed on the computer.

- Who: anyone signed in who may see that computer.
- When YouTube downloads are off: the YouTube lines are absent.

### Admins are told when a computer could not get what its parts need

When getting what the app needs for video and audio on a computer has failed 2 or more checks in a row, the admin is warned "a computer could not install its media tools", with the cause quoted. Everything a part needs is fetched whenever that part is on, whatever other parts are off.

#### Lessons

- Met: APP-133, APP-134, APP-136, APP-138, APP-139, APP-140, APP-141, APP-142, APP-143, APP-144, APP-145, RSV-150, RSV-151.

## Uninstalling

### CC Sync is listed among the installed apps with a working uninstall

On Windows the install lists CC Sync (with the studio's name in brackets when the site publishes one) in Settings, Apps, Installed apps, with its icon and version and an uninstall button that runs CC Sync's uninstaller; there is no modify or repair. A re-install replaces the same entry. If the entry cannot be made, the editor is told the manual way to uninstall. The uninstaller keeps a copy of itself on the computer so the entry keeps working.

- Windows and macOS: on macOS there is no such list; the uninstaller sits beside the app in the person's own programs folder, and set-up's closing text says how to run it (or to get it from the installer or from the admin).

### Uninstalling removes the app and every way into the studio's server, never the media

The uninstaller opens by saying which mode it is in and that synced media is never touched. It stops the app and everything it started, removes everything that started them at sign-in (including entries of versions with older names), and removes CC Sync's program folder and its entries in the command path. On Windows it removes the project drive only if CC Sync made it (one made by anything else is left alone), and closes the folder to the network only once the drive is confirmed gone; if the drive stays, the folder stays closed to other computers and the uninstaller prints the two commands to finish by hand. A protection is only ever removed after the thing it protects is confirmed gone, and a state that cannot be read counts as still there.

Every uninstall removes every credential that lets the computer reach the studio's server: the sign-in and anything else the computer held to reach it. The default uninstall keeps the settings and the computer's identity ("a reinstall is recognised as the same computer, no new approval needed") and says how to ask for a full uninstall. A full uninstall also removes the settings, the logs, the licence record and the computer's identity ("a reinstall is a NEW computer: your admin must approve it again"), but keeps the record of prompts already answered, so they stay answered after a reinstall. Windows and macOS treat the identity the same, and the uninstaller says once, truthfully, whether a reinstall will need the admin's approval.

Always left: the local folder and the synced media, the studio's private network app, and anything installed through the system's own package installers ("remove them from Apps & features if wanted", or the Mac's package manager). On a Mac, Resolve's drive mapping is removed when it points at this computer's folder and Resolve is closed; if Resolve is open the uninstaller says to quit it and run it again, or how to remove the mapping by hand (DaVinci Resolve, Preferences, Media Storage).

After every delete the uninstaller checks what is really gone. If files survive (a file in use), it names each with its path (up to 8) and how to retry: sign out and back in, then run the uninstaller again. On Windows the installed-apps entry stays until the program folder is really gone. It ends "CC Sync uninstall complete." only when every removal is confirmed, otherwise "CC Sync uninstall NOT complete" with the reason; a Mac run ends "YOUR SYNCED MEDIA WAS NOT TOUCHED". If the uninstaller itself is still on disk it says either to leave it there to retry, or that it may be deleted; it never suggests removing what a retry needs. A preview mode changes nothing.

- Who: the editor at the computer, or an admin.
- Ways in: the installed-apps entry on Windows, the uninstaller beside the app on a Mac.

#### Lessons

- Met: APP-148, APP-149, APP-150, APP-151, APP-152, APP-153.
