# Trace of editor-app

## Coverage

- 01-003 | An install cut short is offered to be finished, and nothing syncs until it is
- 09-007 | The settings each computer holds
- 10-040 | The app runs on supported Windows computers and Apple silicon Macs
- 13-021 | An editor gets the installer for a new computer, or to repair one
- 22-002 | The installer refuses to run from the project drive, a network location or a removable disk
- 22-003 | One set-up wizard takes a computer from nothing to signed in and working, and is safe to run again
- 22-005 | One set-up wizard takes a computer from nothing to signed in and working, and is safe to run again
- 22-006 | Closing the wizard in the middle of an install asks first
- 22-007 | An install cut short is offered to be finished, and nothing syncs until it is
- 22-009 | On Windows set-up under a different account from the one signed in is refused
- 22-012 | A remote editor joins the studio's private network inside the wizard
- 22-021 | The install shows every step live, can be retried, and gives up after 30 minutes
- 22-022 | Every install leaves exactly one copy of the app and keeps the sign-in, settings and identity ; A drive letter already in use is never taken
- 22-037 | The finish page says whether the computer is ready, and what happens next
- 22-041 | left out: cut by the owner (2026-11-24, editor-app-Q8)
- 22-049 | One set-up wizard takes a computer from nothing to signed in and working, and is safe to run again
- 01-029 | On macOS the app checks at every start that it may read the sync drive, and says how to allow it
- 03-033 | On macOS the app checks at every start that it may read the sync drive, and says how to allow it
- 09-038 | On Windows an expired certificate left in the computer's store never stops the app reaching the server
- 13-022 | The download page walks the editor past the operating system's warnings
- 22-001 | The download page walks the editor past the operating system's warnings ; An editor gets the installer for a new computer, or to repair one
- 22-026 | Everything set-up fetches is checked before it is used ; Everything set-up fetches is reused or downloaded at a known version
- 22-028 | The computer only ever talks to its own studio's server
- 22-029 | The computer's sign-in and settings are readable only by the editor
- 01-050 | Windows warns when the drive letter does not lead to the synced folder, and repairs it in one click
- 04-074 | Windows warns when the drive letter does not lead to the synced folder, and repairs it in one click
- 22-023 | On Windows a remote editor's copy of the projects appears at the studio's drive letter
- 22-024 | A drive letter already in use is never taken
- 22-025 | Installing from an administrator window is warned against
- 01-001 | Only one copy of the app ever runs on a computer
- 01-004 | An app that dies on its own is started again within about ten seconds, and says so
- 01-005 | The app keeps its own work going when part of it stops
- 01-013 | The editor can restart the app
- 01-081 | Quitting stops everything cleanly and asks first if media is being copied in
- 01-083 | Every crash is written down on the computer and counted for the admin
- 03-023 | The app keeps its own work going when part of it stops
- 04-004 | On Windows the icon comes back by itself, and a computer without it keeps working
- 04-005 | On macOS the app says when the menu bar has no room for its icon
- 04-024 | The editor can restart the app
- 04-025 | Quitting stops everything cleanly and asks first if media is being copied in
- 07-025 | A computer doing heavy work stays awake and warns before shutting down
- 09-047 | The editor can restart the app
- 09-075 | Every crash is written down on the computer and counted for the admin
- 09-076 | left out: cut by the owner (2026-11-24, editor-app-Q2)
- 09-077 | An app that dies on its own is started again within about ten seconds, and says so
- 09-078 | An app that dies on its own is started again within about ten seconds, and says so
- 10-038 | The computer's sign-in and settings are readable only by the editor
- 10-041 | An app that dies on its own is started again within about ten seconds, and says so ; A version that cannot stay up is replaced by the version before
- 12-042 | Every crash is written down on the computer and counted for the admin
- 15-035 | Every crash is written down on the computer and counted for the admin ; The app keeps its own work going when part of it stops
- 22-034 | The app starts whenever the editor signs in to the computer, and set-up confirms it is running
- 01-002 | On macOS the app lives only in the menu bar
- 01-084 | Field backup opens from the menu
- 02-023 | The menu holds about ten everyday lines
- 03-002 | The app's status line says where syncing has got to
- 04-001 | The icon shows at a glance whether all is well, needs attention, or has a problem
- 04-002 | The icon shows at a glance whether all is well, needs attention, or has a problem
- 04-003 | Clicking the icon opens the menu at once, and it never shifts or freezes while open
- 04-006 | Clicking the icon opens the menu at once, and it never shifts or freezes while open ; Notifications are the operating system's own, headed with the studio's name and mark
- 04-007 | Hovering over the icon shows one short line saying what this computer's syncing is doing
- 04-008 | Hovering over the icon shows one short line saying what this computer's syncing is doing
- 04-011 | The menu holds about ten everyday lines
- 04-021 | The editor opens their sync drive from the menu
- 04-022 | The editor opens the dashboard from the menu
- 05-003 | Clicking the icon opens the menu at once, and it never shifts or freezes while open
- 10-044 | left out: for the builders only
- 01-009 | Notifications are the operating system's own, headed with the studio's name and mark ; The app's windows never block one another
- 02-038 | Nothing the app runs ever flashes a console window on Windows
- 03-011 | The editor sees each ticked project with what it is doing and why
- 04-028 | The app's windows never block one another
- 04-085 | Long background work has a progress window the editor can close and reopen
- 04-086 | Confirmations default to the safe answer and every window works from the keyboard
- 04-091 | When the project open in Resolve has no home on the server, the editor is asked once
- 07-038 | Long background work has a progress window the editor can close and reopen
- 22-004 | Confirmations default to the safe answer and every window works from the keyboard
- 01-007 | At start the app says at once if this computer will not sync, and confirms a finished update
- 01-008 | A computer that is not fully set up names what is missing
- 01-014 | The editor sends the admin a full description of the computer with one button
- 04-010 | A computer that is not fully set up names what is missing
- 04-015 | The menu carries a line for each piece of work under way
- 04-026 | Every message points at the smallest action that clears it, and where it lives
- 04-043 | A failed transfer is explained in plain words
- 04-050 | The editor is told when the dashboard is not hearing from the computer, and when the clock is wrong
- 04-051 | The settings window ranks its warnings, merges repeats and shows at most six ; The app keeps its own work going when part of it stops ; A version that cannot stay up is replaced by the version before
- 04-057 | The settings window ranks its warnings, merges repeats and shows at most six
- 04-075 | The help actions are in reach from the settings window
- 09-002 | A damaged settings file never runs the computer on the wrong settings
- 09-003 | A computer that is not fully set up names what is missing ; A dashboard address that is plain http on the public internet is never used
- 09-034 | A sign-in never expires on its own, and a refused one is said plainly ; A dashboard address that is plain http on the public internet is never used ; The editor is told when the dashboard is not hearing from the computer, and when the clock is wrong
- 09-036 | The editor sends the admin a full description of the computer with one button
- 15-037 | Admins are told when the product's pages cannot reach the app on a computer
- 15-112 | Every message points at the smallest action that clears it, and where it lives
- 22-020 | Every install step is shown live and kept in a log the editor can copy
- 22-038 | An install that finished with something missing says NOT READY and lists what
- 01-010 | The editor signs in with the username and password their admin gave them ; The menu says who is signed in and offers to sign in ; Nothing starts syncing on a computer nobody is signed in to
- 01-011 | A sign-in never expires on its own, and a refused one is said plainly
- 04-009 | The menu says who is signed in and offers to sign in ; A sign-in never expires on its own, and a refused one is said plainly
- 04-029 | The sign-in window
- 04-030 | The menu says who is signed in and offers to sign in
- 04-059 | When the identity cannot be read, the editor can give the computer a new one
- 04-060 | A sign-in never expires on its own, and a refused one is said plainly
- 09-012 | The editor signs in with the username and password their admin gave them
- 09-069 | Each computer has a permanent identity that survives renaming it ; When the identity cannot be read, the editor can give the computer a new one
- 09-071 | The editor signs in with the username and password their admin gave them
- 11-023 | The editor signs in with the username and password their admin gave them
- 22-011 | The editor types the dashboard address and it is checked before going on
- 22-013 | The editor signs in with the username and password their admin gave them
- 01-006 | The app keeps a log and its other records within fixed limits ; The settings each computer holds
- 01-086 | The settings each computer holds
- 04-056 | The settings window gathers everything about this computer and keeps itself current
- 04-061 | The settings window shows the dashboard address this computer uses, and warns when it is unsafe or wrong
- 07-012 | The product's pages reach Resolve on the editor's computer through the app, and only the studio's pages may
- 07-013 | The settings each computer holds
- 07-043 | The settings each computer holds
- 09-001 | A setting changed anywhere changes only that setting, and an update never resets one ; The settings each computer holds
- 09-004 | A value set on the computer always wins
- 09-025 | The product's pages reach Resolve on the editor's computer through the app, and only the studio's pages may
- 14-050 | The admin sees, read-only, the settings each computer last reported
- 15-072 | Admins are told when a computer could not get what its parts need
- 22-036 | A setting changed anywhere changes only that setting, and an update never resets one
- 22-042 | CC Sync is listed among the installed apps with a working uninstall
- 22-043 | Uninstalling removes the app and every way into the studio's server, never the media
- 22-044 | Uninstalling removes the app and every way into the studio's server, never the media

## Questions for the owner

### editor-app-Q1: An editor can stop syncing on their computer in four ways that behave differently (pause, stop all syncing, setting the computer to sync nothing, signing out). Which should an editor have?
- Kind: either-or
- Today: pause is forgotten when the app restarts and lets small project files keep sharing; "stop all syncing" is remembered and stops everything; a computer set to sync nothing (wired) does nothing at all; signing out stops syncing and reporting. Each says something different in the app.
- Options: A: keep all four. B: one pause for the editor that stops everything and is remembered until they resume (the stop folded into it), the wired role for a computer that works off the server, and signing out kept for what it is (giving the computer up), not as a way to stop syncing.
- Recommend: B, because one pause that means "nothing moves until I say" is what an editor reaches for, and a second, stronger stop beside it is a choice nobody can tell apart.
- Changes for a person: with B the editor sees one pause and one resume; the admin's studio-wide stop is unchanged; with A nothing changes.
- Text assumes: this piece only names the pause and the stop as lines of the menu and points to Sync, where the pause and stop are written; the choice is made there.
- Items: 01-010
- Covers: 01-Q1
- Answered by the owner 2026-11-24: B, one pause for the editor that stops everything and holds across restarts, sign-in and updates; the separate stop and its clearing line are gone

### editor-app-Q2: Sending crash reports to an outside crash-collection service is present but can never work. Can it go?
- Kind: dormant
- Today: a setting and an address exist for sending each crash to an outside service, but no address is built in and the sending part is not in the installed app.
- Options: A: cut it; crash reports stay on the computer and are counted on the dashboard. B: keep it as a site setting the vendor can turn on.
- Recommend: A, because the dashboard already sees every computer's crash count and newest report, and an outside service is another place customer data goes.
- Changes for a person: with A nothing changes for anyone; with B an admin gains one setting and the vendor gains crash reports from customers' computers.
- Text assumes: A; the passage is written in its place and marked pending, to be deleted
- Items: 01-083, 09-076
- Covers: 01-Q9, 09-Q6
- Answered by the owner 2026-11-24: A, cut; crash reports stay on the computer and are counted on the dashboard

### editor-app-Q3: A field backup page opens from the app's menu on computers where it is switched on. Is it wanted, and is it on by default?
- Kind: other
- Today: when field backup is on for a computer, "Field backup..." in the menu opens a local page; whether it is on by default is not clear.
- Options: A: keep it, shown only while the camera cards part is on and off by default per computer. B: cut it from the app's menu; field backup is reached from the Footage Sorter's own pages.
- Recommend: A, as long as field backup itself stays in the Footage Sorter; a menu line that appears only when switched on costs the everyday menu nothing.
- Changes for a person: with A an editor who backs up in the field opens it from the menu; with B they open it from the dashboard's Footage Sorter pages.
- Text assumes: A
- Items: 01-084
- Covers: 01-Q11
- Answered by the owner 2026-11-24: A, kept, shown only while the camera cards part is on

### editor-app-Q4: A refused computer sign-in is announced in four places (a menu line, a warning line, a line beside the identity, a button) and the sign-in window is opened from four. Keep all, or one warning with one button plus the menu line?
- Kind: several ways in
- Today: after ten refused reports the settings window shows a warning in its list of warnings and a second red line beside the identity with a SIGN IN AGAIN button; the menu has "Sign in again"; the settings window also has SIGN IN and SIGN OUT buttons; the menu has "Sign in…".
- Options: A: keep all. B: one notification when it happens (repeated hourly), one menu line, and one warning in the settings window with its button.
- Recommend: B, because one warning with its button and one menu line is enough to be found, and two red lines saying the same thing read as two problems.
- Changes for a person: with B the editor sees the refusal once in the settings window instead of twice.
- Text assumes: B
- Items: 04-009, 04-050, 04-060
- Covers: 04-Q7
- Answered by the owner 2026-11-24: B, one notification (hourly), one menu line, one warning with its button

### editor-app-Q5: Every button in the settings window closes the window before it acts, and some then reopen it. Should the window stay open and show the result instead?
- Kind: other
- Today: pressing any button in the settings window closes it first, does the work, and for a setting change opens it again.
- Options: A: the window stays open and shows the result in place. B: keep closing and reopening.
- Recommend: A, because a window that vanishes and comes back loses the editor's place and looks like a crash.
- Changes for a person: with A the editor stays where they were and sees what their click did.
- Text assumes: A
- Items: 04-056
- Covers: 04-Q8
- Answered by the owner 2026-11-24: A, the window stays open and shows the result

### editor-app-Q6: Two protections overlap when a new version of the app will not stay up: going back to the previous version after repeated failed starts, and giving up relaunching after three times an hour. Is one rule enough, and what should the editor and admin see?
- Kind: built twice
- Today: a version that starts 3 times in 10 minutes without a clean shutdown is replaced by the one before; separately the app is relaunched at most 3 times an hour and then left down; and when the program is missing after a broken update the previous version is put back.
- Options: A: one rule: a version that cannot stay up after an update is replaced by the one before, the editor and admin are told, and the relaunch limit applies only to a version that has run well before. B: keep both rules as they are.
- Recommend: A, because one rule says one thing to the editor and admin, and it keeps the ruled three-an-hour relaunch for ordinary crashes.
- Changes for a person: with A, after a bad update the editor sees one sentence ("the update kept crashing, so CC Sync went back to the previous version") and the admin one alert.
- Text assumes: A
- Items: 10-041, 09-078, 04-051
- Covers: 09-Q1
- Answered by the owner 2026-11-24: A, one rule: a version that cannot stay up is replaced by the one before

### editor-app-Q7: The installer can be downloaded directly or picked from a page that shows the same builds. Keep both?
- Kind: several ways in
- Today: a direct download link picks the platform from the browser, and a separate page lists each platform with version, size and checksum and its own button.
- Options: A: one installer page, whose main button downloads the one for this computer, plus a plain link an admin can hand to a new editor. B: keep both as they are.
- Recommend: A, because the page already marks "this computer"; the link an admin hands over is the only other way in a new editor needs, since they cannot sign in yet.
- Changes for a person: with A an editor always lands on the page and sees the version and checksum before downloading.
- Text assumes: A
- Items: 13-021, 22-001
- Covers: 13-Q10
- Answered by the owner 2026-11-24: A, one installer page plus a file or link an admin hands over

### editor-app-Q8: A computer can be set up through the wizard or a hand-run install, and a new version can arrive by the app's own update, a hand-run upgrade or by running the wizard again. Keep only the wizard (for setting up or repairing) and the app's own update (for new versions)?
- Kind: several ways in
- Today: the wizard is what editors are pointed at; a hand-run install does the same job for technical people, with a preview mode; a hand-run upgrade swaps the app in by hand; running the wizard again also installs the version it carries.
- Options: A: keep the wizard and the app's own update only; the wizard keeps its safe re-run for repair. B: keep the hand-run install as well, for admins.
- Recommend: A, because two ways to set up a computer must be kept identical for ever, and the wizard already does everything the hand run does.
- Changes for a person: with A an admin who set computers up from a terminal uses the wizard instead; editors notice nothing.
- Text assumes: A; the hand-run install is written in its place and marked pending, to be deleted
- Items: 22-041, 22-003, 22-036
- Covers: 22-Q1
- Answered by the owner 2026-11-24: A, the wizard and the app's own update only; the hand-run install is cut

### editor-app-Q9: Uninstalling on a Mac removes the computer's identity (so the admin must approve it again) even in the default mode, while on Windows it is kept unless a full uninstall is asked for. Which should both follow?
- Kind: built twice
- Today: Windows keeps the identity, sign-in and server connection by default; a Mac removes the identity and its server connection by default and keeps the sign-in.
- Options: A: on both, the default uninstall keeps the settings and the computer's identity (a reinstall needs no new approval), a full uninstall removes them; every uninstall removes every credential that lets the computer reach the server. B: on both, every uninstall removes the identity, so a reinstall is always a new computer.
- Recommend: A, because a repair-by-reinstall should not cost an admin's approval, and removing every credential already makes the computer unable to reach the server until someone signs in.
- Changes for a person: with A a Mac editor who reinstalls signs in again but needs no new approval; with B every reinstall on either system needs the admin.
- Text assumes: A
- Items: 22-043, 22-044
- Covers: 22-Q2
- Answered by the owner 2026-11-24: A, the same on both systems: the default keeps settings and identity, every credential removed

### editor-app-Q10: A remote editor must install the private network's app and sign in to it with an invite before the wizard can go on. Should reaching the server from outside still be a separate step the editor does by hand?
- Kind: other
- Today: step 2 of the wizard sends the remote editor to install the network's app (on Windows from a button, on a Mac from its download page), sign in with the admin's invite, and check the connection before going on.
- Options: A: keep it as a step of the wizard, as written. B: the wizard joins the computer to the studio's network itself from what the admin set up, with no separate app to sign in to.
- Recommend: A, because the studio's private network is the only way in by your earlier decision and it belongs to the studio, not the product; B would need the product to hold the keys to the studio's network.
- Changes for a person: with B a remote editor has one sign-in instead of two.
- Text assumes: A
- Items: 22-012
- Covers: 22-Q4
- Answered by the owner 2026-11-24: A, joining the private network stays a step of the wizard

### editor-app-Q11: Uninstalling on a Mac leaves Resolve's drive mapping that set-up added. Should uninstall remove it?
- Kind: other
- Today: the Mac uninstaller always leaves the mapping and says to remove it in Resolve's preferences if wanted.
- Options: A: uninstall removes the mapping it added (only when Resolve is closed; otherwise it says how), keeping any other. B: leave it, as now.
- Recommend: A, because uninstall should take away what install added, and a mapping pointing at a folder the product no longer manages only confuses later.
- Changes for a person: with A a Mac editor who uninstalls finds Resolve's mapping gone, and clips on the studio's drive show offline in Resolve.
- Text assumes: A
- Items: 22-044
- Covers: 22-Q5
- Answered by the owner 2026-11-24: A, uninstall removes the Resolve mapping it added

### editor-app-Q12: A hand-run Windows install can leave the editor's project folder reachable from other computers on the network. Keep this option?
- Kind: dormant
- Today: an option of the hand-run install, with a warning, leaves the folder served to other computers; the wizard never offers it.
- Options: A: cut it; the folder is never reachable from other computers. B: keep it for the hand-run install.
- Recommend: A, because it serves the whole project tree to any network the laptop joins, and nothing an editor does needs it.
- Changes for a person: none for editors; an admin loses an option nobody is known to use.
- Text assumes: A; the passage is written in its place and marked pending, to be deleted
- Items: 22-023
- Covers: 22-Q7
- Answered by the owner 2026-11-24: A, cut; the folder is never reachable from other computers

### editor-app-Q13: Should a computer ever sync without anyone signed in?
- Kind: other
- Today: requiring sign-in is a setting on the computer, on by default; with it off the computer reports under a name typed on the computer, and with no dashboard address at all it syncs the whole tree on its own.
- Options: A: every computer must have someone signed in before anything syncs, and a computer with no dashboard address syncs nothing and says so. B: keep the switch and the name.
- Recommend: A, because a computer nobody is signed in to is invisible to the admin and its reports name nobody, and one rule is simpler for editors and support.
- Changes for a person: with A a studio running a computer without sign-in has to sign it in once.
- Text assumes: A; the switch is written in its place and marked pending, to be deleted
- Items: 01-010, 01-086, 09-007
- Covers:
- Answered by the owner 2026-11-24: A, cut; a computer always belongs to a studio, someone is always signed in, and it syncs only what is ticked for it

### editor-app-Q14: Should the app show only one of its windows at a time, or let several be open together?
- Kind: other
- Today: asking for a window while another is open is refused with "Another CCSync window is already open. Close it first."; the app's own prompts wait until the open window closes, or turn into a notification; restart and update are refused while any window is open.
- Options: A: several windows may be open at once, each kind once (asking again brings it forward); restart, update and quit still ask when they would cut off what a window is doing. B: one window at a time, as now, with prompts waiting their turn.
- Recommend: A, because a refusal to open a window is a dead end for the editor, and lessons from real use show one unanswered window silencing every other prompt and update for a day.
- Changes for a person: with A an editor never sees "close it first" and a question about one project never waits behind a window about another.
- Text assumes: A
- Items: 01-009, 04-028
- Covers:
- Answered by the owner 2026-11-24: A, several windows may be open at once, each kind once

### editor-app-Q15: The app shows two different one-line summaries of syncing: one in its menu ("Sync: ...") and one in its window ("syncing <project> (n/total)", "Waiting for the server ..."). Should there be one?
- Kind: other
- Today: the menu's line says what is moving or what holds syncing; a second status line names the project being synced and whether the computer is using a saved plan.
- Options: A: one status sentence, used in the menu and the window alike, which also carries the project being synced and the "waiting for the server" states. B: keep both.
- Recommend: A, because two summaries of the same thing in different words will one day disagree.
- Changes for a person: with A the editor reads the same words in the menu and the window.
- Text assumes: A
- Items: 03-002
- Covers:
- Answered by the owner 2026-11-24: A, one status sentence in the menu and the window

### editor-app-Q16: When the project open in Resolve has no home on the server, the editor is asked once and can also set it up later from a menu line. Keep both?
- Kind: several ways in
- Today: a one-time question opens the dashboard's set-up page; afterwards a menu line does the same while the project still has no home.
- Options: A: keep both. B: only the menu line (no question).
- Recommend: A, because the question is asked once ever per project and the menu line is the way back to it; neither repeats.
- Changes for a person: with B an editor opening a new project is never interrupted, and must notice the menu line.
- Text assumes: A
- Items: 04-091
- Covers:
- Answered by the owner 2026-11-24: A, keep the one-time question and the menu line

### editor-app-Q17: A shared library or included folder that is not working is reported in four places: the one-line status, the app's project list, the settings window and the dashboard. Keep all?
- Kind: several ways in
- Today: the same problem sentence appears in each of the four.
- Options: A: in the app's project list (one sentence per folder) and on the dashboard, with the one-line status naming it only when it is what holds syncing. B: keep all four.
- Recommend: A, because a sentence repeated in three places of one app reads as three problems.
- Changes for a person: with A the editor sees the problem once in the app, where the project is listed.
- Text assumes: A
- Items: 03-011
- Covers:
- Answered by the owner 2026-11-24: A, the app's project list and the dashboard only

### editor-app-Q18: The editor can restart the app from its menu and from its settings window. Keep both?
- Kind: several ways in
- Today: "Restart CCSync" in the menu and "RESTART CCSYNC NOW" in the settings window behave the same.
- Options: A: keep both. B: the menu line only.
- Recommend: A, because restart is what support asks for first and the settings window is where an editor is looking when something is wrong; both are one control doing one thing.
- Changes for a person: with B an editor in the settings window goes to the menu to restart.
- Text assumes: A
- Items: 01-013, 04-024
- Covers:
- Answered by the owner 2026-11-24: A, restart from the menu and the settings window

### editor-app-Q19: Two things in these items are tools for the people building the product. Can they go from the specification?
- Kind: dev only
- Today: a check that draws a second tray icon for about five seconds, and a setting that lets pages served from the computer itself send to Resolve.
- Options: A: leave them out; the builders make their own tools. B: keep them in the product.
- Recommend: A; neither is something an editor or admin meets.
- Changes for a person: none.
- Text assumes: left out
- Items: 10-044, 09-025
- Covers:
- Answered by the owner 2026-11-24: A, left out

## Readers' questions and unsettled points

- 01-Q1 | editor-app-Q1
- 01-Q7 | with dashboard-1
- 01-Q9 | editor-app-Q2
- 01-Q11 | editor-app-Q3
- 04-Q5 | answered: APP-081 (the site's published address for people, falling back to the reporting address); the same rule is written for the help pages and the project set-up page
- 04-Q7 | editor-app-Q4
- 04-Q8 | editor-app-Q5
- 04-Q11 | answered: APP-084 (every tray action answers), APP-070 (an icon that never appears is told to the editor and admin) and APP-112 (every problem the app finds is shown and reported); the FIX ALL part is written by Resolve on the editor's computer under the same lessons
- 07-Q6 | with broll
- 09-Q1 | editor-app-Q6
- 09-Q6 | editor-app-Q2
- 09-Q10 | not a question: the app already shows a clock 60 seconds or more out and ten failed reports in its settings window, and the admin is alerted at five minutes (written in Sync, part 2); the text keeps both
- 11-Q2 | with accounts-privacy-legal
- 13-Q10 | editor-app-Q7
- 22-Q1 | editor-app-Q8
- 22-Q2 | editor-app-Q9
- 22-Q3 | with accounts-privacy-legal
- 22-Q4 | editor-app-Q10
- 22-Q5 | editor-app-Q11
- 22-Q7 | editor-app-Q12
- 22-Q8 | with accounts-privacy-legal
- U-01-3 | settled: the relaunch limit is three an hour by ruling APP-056; the other numbers (readdressing, update waits, rollback window, reminders, project checks) belong to the pieces that own those behaviours
- U-01-9 | settled: the text gives a starting order for the menu, from the items and ruling APP-079
- U-03-7 | settled: APP-029 requires the Full Disk Access check at every start, with the editor told how to grant it
- U-03-8 | behind the glass
- U-04-1 | not a question: outside the Timeline Cards editor wording is written in plain words by the piece that owns each message
- U-04-5 | not a question: which video files the b-roll chooser accepts belongs to the b-roll archive's piece
- U-04-6 | behind the glass
- U-05-3 | settled: every reference names the one place diagnostics are copied, as written in "Every message points at the smallest action that clears it, and where it lives"
- U-05-6 | settled: the app's link to Resolve is renewed on its own when Resolve is started again; whether that takes a restart of the app is behind the glass
- U-05-8 | behind the glass
- U-07-2 | settled: APP-025, everything a part needs is fetched whenever that part is on
- U-09-7 | settled: every setting a person may change on a computer is in the app's settings window
- U-10-4 | settled: only the studio's dashboard address and exact addresses an admin adds may send to the app
- U-10-7 | behind the glass
- U-10-8 | settled: owner's requirements section 2, a part that is off is seen by nobody, so the line is absent
- U-13-4 | not a question: which dashboard pages open without signing in belongs to the dashboard and accounts pieces
- U-14-2 | not a question: the installed web app belongs to the dashboard's piece
- U-22-3 | settled: the support contact comes from the site's settings
- U-22-5 | behind the glass
- U-22-6 | behind the glass

## Still unsettled

## Conflicts between an item and a lesson

- APP-040 | 22-023 | the item labels the drive with the tree's name; the ruling labels it with the studio's name from the site's settings. Wrote the ruling.
- APP-029 | 10-040 | the item carries a developer identity only when the vendor has one; the lesson requires a stable developer identity on every Mac build. Wrote the lesson.
- APP-022 | 22-011 | the item adds http for an IP address or local name and https otherwise, by rule; the lesson keeps a typed scheme, tries https first, and never keeps a guess silently. Wrote the lesson.
- APP-123 | 01-011, 09-071, 09-034 | the items let a sign-in expire and tell a refusal once per run; the ruling says a sign-in never expires by time alone and a refusal is reminded hourly. Wrote the ruling.
- APP-129 | 09-069 | the item calls the button Repair; the lesson says it gives the computer a new identity, never "repair". Wrote the lesson (the button from 04-059).
- APP-151 | 22-043, 22-044 | the items keep the sign-in, the computer's key and the server connection after an uninstall; the lesson says no credential that reaches the server remains. Wrote the lesson.
- APP-150 | 22-043, 22-044 | the two systems treat the identity differently; the lesson says the same on every platform. Wrote one rule (editor-app-Q9).
- APP-070 | 04-004 | the item tells nobody on the computer when the icon cannot be shown; the lesson says editor and admin are told. Wrote the lesson.
- APP-084 | 04-024 | the item tells nobody when a restart fails; the lesson says every tray action answers. Wrote the lesson.
- APP-045 | 22-034 | the item has Windows background syncing start only at sign-in; the lesson says every long-running part has something that restarts it. Wrote the lesson.
- APP-090 | 04-025 | on Windows the quit question has no time limit; the lesson says a timed-out confirmation still quits. Wrote one behaviour on both systems: Keep copying is the default, and the quit goes ahead after 2 minutes unanswered.
- APP-138 | 07-013 | the item needs a restart for a library location change; the lesson asks for changes to reach a running app without one. Wrote no restart.
- APP-021 | 13-021 | the item lets only signed-in people download; the lesson says a new editor downloads without the private network. Wrote both: the page for people signed in, and a file or link an admin hands over.
- APP-100 | 04-086 | none in this bundle: an update confirmation elsewhere lets Enter confirm; this text has Enter press only the focused button everywhere (noted for Releases and updates).

## New in this text

- Only one set-up runs at a time on a computer | APP-017 asks for it; no item shows it.
- Set-up checks that it can finish before it changes anything | the checks before removing anything, the bare-drive refusal and the Resolve-installed check come from APP-014, APP-020 and APP-005.
- The finish page says whether the computer is ready, and what happens next | the editor no longer copies a sync code and a key to send to the admin: the computer appears on the dashboard waiting for approval by itself; done is said only after the computer has reported in and its drive answers (APP-013); Resolve missing is a note on the finish page (joins 2026-11-24, editor-app F21).
- An editor gets the installer for a new computer, or to repair one | a file or a link an admin hands over that works without signing in or the private network (APP-021).
- The studio's drive letter and tree name cannot change under installed computers | APP-043; the text chooses refusing over carrying the change.
- On Windows the icon comes back by itself, and a computer without it keeps working | the editor is told when the icon never appears, and starting the app again opens its settings (APP-070).
- Only one copy of the app ever runs on a computer | starting the app again when it has no icon opens its settings window.
- The settings window gathers everything about this computer and keeps itself current | every setting a person may change is in the window, none only in a file.
- The settings each computer holds | a library location change takes effect without a restart.
- Quitting stops everything cleanly and asks first if media is being copied in | "Restart CC Sync" beside Quit (APP-084); the same question and 2-minute limit on both systems.
- A sign-in never expires on its own, and a refused one is said plainly | an hourly reminder (APP-123).
- The editor can restart the app | a failed restart is told (APP-084).
- Uninstalling removes the app and every way into the studio's server, never the media | every credential removed (APP-151), one rule for the identity on both systems, and Resolve's mapping removed on a Mac (editor-app-Q11).
- The app keeps its own work going when part of it stops | work that keeps progressing is never cut off by a fixed clock (APP-146).
- The editor opens Timeline Cards in a window of its own from the app | added by the joins (2026-11-24, editor-app F9), from the owner's answer on page 28.1.

## Parts of items left out

- 09-007 | where the tree lives on the server, and the editor's name as the identity reports are sent under: arrangements of how the computer reaches the server.
- 10-040 | each program built on its own system, and the program's own description string: arrangements.
- 22-022 | the background sync program CC Sync installs, its server connection entry and the computer's key as separate things kept by an install: arrangements (the promise of keeping the sign-in, settings and identity is written).
- 22-026 | the sync tools themselves and their sources: arrangements (the promise of verified, complete installs is written).
- 22-028 | the server connection entry and its backup file: arrangements (the promise of talking only to the studio's server is written).
- 22-037 | the sync identity code and key shown in fields with copy buttons, and their headings: arrangements of how the present product approves a computer.
- 22-041 | the server's tree location and the key given by hand, the closing steps of making a key and sending its public half: arrangements.
- 22-049 | background syncing kept alive by the system on a Mac, a hand upgrade with fall-back, a hand Mac install downloading the app: arrangements and the hand-run upgrade (editor-app-Q8).
- 22-034 | the app copied into the person's own program folder, a hand-run Mac install downloading the app, and background syncing handled by the system: arrangements.
- 01-001 | Linux showing nothing: Linux is not supported (APP-007).
- 01-005 | the named inner parts (the watcher, the media pool reader, the project loop): inside names; the promise is written per piece of work.
- 01-083 | the hard crash record being made by the system's fault handler: an inside.
- 09-047 | the app relaunching its own build to give Resolve a clean connection, its 30-second hand-over, and the copy run by developers: arrangements (the promise is under "The editor can restart the app").
- 09-077 | the process number in the crash sentence: an inside.
- 09-078 | Linux and developer copies; the closing of a console window; an app killed before its watcher started: arrangements.
- 10-038 | looking at up to 400 entries: a size of the present build's check.
- 10-041 | every start recorded first: an arrangement.
- 04-006 | other operating systems: not supported (APP-007).
- 04-008 | "fetching the <b-roll|music> model": reworded to what analysis needs.
- 07-038 | "Waiting for the computer that is wired to the server: N tracks still on this computer", and items left for the wired computer: an arrangement of which computer does the work (see Work shared out across the computers).
- 07-025 | "the <kind> indexing model": reworded.
- 03-023 | the wait schedule (30 seconds, 1, 2, 4, 8 minutes, then every 10) and the 20-second success test: arrangements; the editor's and dashboard's sentences are kept or pointed to Sync, part 2.
- 01-014 | "Another window is open, so the diagnostics went to the log": no longer happens (editor-app-Q14); whether project-file sharing answers and whether peers are on a direct path: insides of the present sync.
- 09-036 | the 262,144-character limit: a size of the present build's pipe.
- 09-003 | the server address and server location for the tree, and the half set-up separate download path: arrangements; the computer without credential: covered by not signed in.
- 04-015 | "the helper the downloader needs": reworded to what YouTube downloads need.
- 15-037 | "an old b-roll helper, a leftover process": the rebuild has no such helper; written as "another program in the way".
- 07-012 | the retired standalone b-roll helper as the usual cause: the rebuild has none.
- 07-013 | a plain-words explanation written beside the settings the first time; a damaged settings file falling back: covered by the settings behaviours.
- 09-001 | the settings file with comments, its invisible marker, a second copy of a setting or a section heading as the usual cause of a failed save: arrangements of a file; the promise (only that setting changes, a failed save is told) is written.
- 01-086 | how often the timeline, media pool, LUT link and sign-in are read; rehearsing copy-ins: tuning of the present build or dormant (rehearsals belong to Resolve on the editor's computer).
- 01-011 | checking the sign-in about once a minute: an arrangement once sign-ins no longer expire.
- 11-023 | the studio-wide key; a site on NAS accounts or single sign-on with no way to ask the NAS, where membership goes unchecked: with accounts-privacy-legal (11-Q2).
- 22-036 | the per-computer key pasted at install and the shared reporting key: arrangements (with accounts-privacy-legal, 22-Q8).
- 22-043 | the computer's key and server connection entry always left: replaced by APP-151.
- 22-044 | the server connection entry removed with no backup: an arrangement.
- 09-025 | accepting pages served from the computer itself: for the builders only (editor-app-Q19).
- APP-004 | never recording a version-numbered package-manager path: an arrangement.
- APP-044 | no password on a command line: kept as "never shown on screen or in a command".
- APP-048 | the 15-second wait for the lock: an arrangement; the promise of never leaving the computer without the app is written.

- owner's answer 2026-11-24 | 01-010, 09-007 | the items let a computer sync and report without anyone signed in, and sync the whole tree with no dashboard; the owner confirmed a computer always belongs to a studio and syncs only what is ticked for it. Wrote that.
- owner's answer 2026-11-24 (sync piece) | 04-011 | the items carry a separate "stop all syncing" and a line to clear it; the owner gave the editor one pause. Wrote one pause; downloads after a safety stop or a low-disk pause are started again from one line in the app.

## Joins with other capabilities

- Sync / Wired or remote | One set-up wizard takes a computer from nothing to signed in and working, and is safe to run again | the role step of set-up and the wired finish page.
- Sync / Wired or remote | Switching a computer between remote and wired is confirmed first | the confirmation itself.
- Sync / Computers joining and changing | The finish page says whether the computer is ready, and what happens next | an admin approves a new computer.
- Sync / Studio-wide stops and the editor's pause | The menu holds about ten everyday lines | Sync now and the one pause.
- Sync / Disk space | The menu holds about ten everyday lines | resuming downloads after a low-disk pause.
- Sync / Safety stops | The computer's sign-in and settings are readable only by the editor | an unsavable safety stop; the resume proxy download prompt.
- Sync / Saying truthfully what the sync is doing | The menu holds about ten everyday lines | the menu's one-phrase sync line.
- Sync / Saying truthfully what the sync is doing | The app keeps its own work going when part of it stops | syncing brought back and its sentences.
- Sync / What syncs where | The editor sees each ticked project with what it is doing and why | the list of ticked projects.
- Sync / Uploads that cannot resume, shutdown and sleep | A computer doing heavy work stays awake and warns before shutting down | keeping awake and shutdown warnings for syncing.
- Sync / The sync drive | Notifications are the operating system's own, headed with the studio's name and mark | the pulled-drive warning and reminders.
- Sync / Clocks and file age | The editor is told when the dashboard is not hearing from the computer, and when the clock is wrong | measuring the clock.
- Accounts, privacy and the legal paperwork / The licence a person accepts | Nothing syncs until the licence is accepted, and the app asks within a minute | the licence window.
- Accounts, privacy and the legal paperwork / What the product records about a person | One set-up wizard takes a computer from nothing to signed in and working, and is safe to run again | the reporting choices page.
- Accounts, privacy and the legal paperwork / How a computer proves who it belongs to | The editor signs in with the username and password their admin gave them | each computer's own sign-in.
- Accounts, privacy and the legal paperwork / Passwords, sessions and failed sign-ins | The editor signs in with the username and password their admin gave them | the refusal sentences, the same as the dashboard's sign-in.
- Accounts, privacy and the legal paperwork / What the product records about a person | The editor sends the admin a full description of the computer with one button | what diagnostics hide when a kind is withheld.
- Accounts, privacy and the legal paperwork / The licence a person accepts | Nothing syncs until the licence is accepted, and the app asks within a minute | a newer licence version asked for while syncing goes on.
- Releases and updates / Offering an update to a computer | The menu holds about ten everyday lines | the offered version in the menu and settings.
- Releases and updates / Rolling back and withdrawing a build | A version that cannot stay up is replaced by the version before | going back to the earlier version.
- Releases and updates / Customer sites and the vendor's release feed | An editor gets the installer for a new computer, or to repair one | an admin taking the installer from the vendor.
- Resolve on the editor's computer / Setting Resolve up: edition, scripting switch, preferences | On Windows a remote editor's copy of the projects appears at the studio's drive letter | Resolve's drive mapping on a Mac.
- Resolve on the editor's computer / Grading from the server's originals | Windows warns when the drive letter does not lead to the synced folder, and repairs it in one click | the drive pointed at the server for grading.
- Resolve on the editor's computer / Connecting to Resolve's scripting: launch, stalls and death | The editor can restart the app | the link to Resolve renewed on its own.
- Resolve on the editor's computer / Colour look-up tables (LUTs) | The menu holds about ten everyday lines | the share-LUTs prompt.
- Resolve on the editor's computer / Fixing media: copying in, rehearsals and undo | The settings window ranks its warnings, merges repeats and shows at most six | clips skipped for now; the copy-in Quit asks about.
- Proxies and file moves / Making proxies on editors' computers | A computer that is not fully set up names what is missing | proxy making that cannot work here.
- Proxies and file moves / Following a move on an editor's computer | The editor sees each ticked project with what it is doing and why | the last moves shown.
- Work shared out across the computers / Stopping and cancelling | Quitting stops everything cleanly and asks first if media is being copied in | shared work handed back on quit.
- Work shared out across the computers / Choosing who runs what | The menu carries a line for each piece of work under way | work an admin sent to this computer.
- Work shared out across the computers / What a computer can honestly offer | The settings each computer holds | whether this computer takes shared work.
- The b-roll archive / Bringing new footage in | Long background work has a progress window the editor can close and reopen | the browser page's progress.
- The b-roll archive / Sending a clip to Resolve | The settings each computer holds | fetching missing clips switched off by a folder of one's own.
- Music / Adding tracks to the library | Long background work has a progress window the editor can close and reopen | the browser page's progress.
- The Footage Sorter and camera cards / Copying a card | Field backup opens from the menu | the field backup page (part 1).
- The Footage Sorter and camera cards / The sorter page | Field backup opens from the menu | the field backup page keeping itself up to date (part 3).
- Timeline Cards: the editor / Opening episodes and keeping the editor running | The editor opens Timeline Cards in a window of its own from the app | the editor window itself.
- The b-roll archive / Describing and indexing clips | The menu carries a line for each piece of work under way | what a drop waits for and what each button answers.
- Music / Imports across computers | The menu carries a line for each piece of work under way | what each music button answers.
- Sync / What is owed | The editor sees each ticked project with what it is doing and why | the safe-to-close line.
- Resolve on the editor's computer / Setting Resolve up: edition, scripting switch, preferences | The finish page says whether the computer is ready, and what happens next | the note when Resolve is missing.
- Proxies and file moves / Making proxies on editors' computers | A computer doing heavy work stays awake and warns before shutting down | proxy making kept awake.
- The dashboard / Projects | When the project open in Resolve has no home on the server, the editor is asked once | the page for setting up a project.
- The dashboard / Reports from computers | The editor sends the admin a full description of the computer with one button | diagnostics sent on error and on request.

## Joins settled

- accounts-privacy-legal F1 | changed: The editor signs in with the username and password their admin gave them | "disabled" dropped; suspended or removed now share the one refusal sentence.
- accounts-privacy-legal F6 | changed: The editor signs in with the username and password their admin gave them | the 16-computer limit and signing out the least recently used one dropped; a new computer takes nothing from the others.
- accounts-privacy-legal F7 | changed: The editor signs in with the username and password their admin gave them | refusals use accounts-privacy-legal's sentences (one sentence for unknown name and wrong password, wait in minutes, "login not configured on the server"), pointing there.
- broll F3 | changed: The settings each computer holds | "where dropped files wait and how long finished drops are kept" dropped from the list.
- dashboard-1 F7 | changed: The editor sends the admin a full description of the computer with one button | withheld kinds hidden as in accounts-privacy-legal "Diagnostics hide what a computer withholds", with a pointer.
- editor-app F3 | changed: A failed transfer is explained in plain words | refused sign-in row uses the refused-sign-in warning with SIGN IN AGAIN…, not diagnostics.
- editor-app F4 | changed: A value set on the computer always wins | the exception named: a site-only limit, above all a kind of reporting the studio switched off, is never overridden from the computer (settled by ACC-047).
- editor-app F5 | no change here: accounts-privacy-legal changes; this piece already counts closing as unanswered.
- editor-app F6 | changed: Nothing syncs until the licence is accepted, and the app asks within a minute ; At start the app says at once if this computer will not sync, and confirms a finished update | "nothing syncs" limited to a computer that never accepted a licence; a newer version is asked for while syncing goes on.
- editor-app F7 | no change here: already agrees (home here; broll and music point to it).
- editor-app F8 | changed: The menu carries a line for each piece of work under way | b-roll and music analysis lines (music failure line included) added to the menu, their buttons placed in the settings window, each absent while its part is off. The b-roll upload lines were not carried: they describe analysis done here and then uploaded, an arrangement.
- editor-app F9 | changed: The editor opens Timeline Cards in a window of its own from the app (new) | a menu line while Timeline Cards is on; the window is part of the one app and its updates.
- editor-app F10 | no change here: this piece already shows the shared-work time read-only and changed on the computer, and mentions no sync-drive reminder setting.
- editor-app F11 | changed: The settings each computer holds | wired or remote is set only on the computer, taken out of the settings an admin changes from the dashboard.
- editor-app F12 | changed: The app starts whenever the editor signs in to the computer, and set-up confirms it is running | installing or updating switches the start at sign-in back on after Task Manager turned it off (settled by SRT-008).
- editor-app F13 | changed: Field backup opens from the menu | field backup off by default on every computer.
- editor-app F14 | no change here: already agrees (this piece's sentences win; music points here).
- editor-app F15 | changed: The product's pages reach Resolve on the editor's computer through the app, and only the studio's pages may | the app's local status address a browser can open.
- editor-app F16 | changed: A computer doing heavy work stays awake and warns before shutting down | proxy making named, with the same 8-hour cap and its shutdown sentence quoted; pointer to proxies-and-file-moves.
- editor-app F21 | changed: The finish page says whether the computer is ready, and what happens next ; Set-up checks that it can finish before it changes anything | "Resolve can be reached" dropped; Resolve missing is a finish-page note, absent with the help for the editing program off.
- editor-app F22 | no change here: sync-1 changes its pointer.
- editor-app F23 | changed: Set-up checks that it can finish before it changes anything | the bare-drive refusal limited to a remote editor's computer; a computer straight off the server uses the site's drive letter as its root; pointer to sync-2's folder checks.
- editor-app F24 | changed: A computer that is not fully set up names what is missing ; At start the app says at once if this computer will not sync, and confirms a finished update | status sentence is sync-2's "Sync: not set up yet", the longer explanation kept in WHAT IS NOT SET UP.
- editor-app F25 | no change here: sync-2 changes.
- editor-app F26 | no change here: sync-2 changes.
- editor-app F27 | no change here: already agrees (an admin, for the site).
- fleet-jobs F14 | no change here: already agrees (this piece's menu line is the one sentence).
- fleet-jobs F17 | no change here: accounts-privacy-legal and fleet-jobs change.
- footage-sorter-and-camera-cards-3 F3 | changed: Field backup opens from the menu | pointer moved to part 1 "An editor can copy a card with no network at all" and part 3 "The field backup page on an editor's computer keeps itself up to date".
- music F5 | no change here: already agrees (home here; music points to it).
- releases-and-updates F8 | changed: A version that cannot stay up is replaced by the version before ; The settings window ranks its warnings, merges repeats and shows at most six | the rollback sentence now pointed to in releases-and-updates instead of quoted.
- releases-and-updates F9 | changed: A version that cannot stay up is replaced by the version before | with nothing to go back to, relaunched at most three times an hour, then left down, admin told.
- releases-and-updates F10 | no change here: releases-and-updates changes.
- releases-and-updates F11 | no change here beyond F12: this piece keeps the installer sentences.
- releases-and-updates F12 | changed: An editor gets the installer for a new computer, or to repair one | admins told to take the installer from the vendor, pointing to "An admin brings one version from the vendor onto the site by hand"; "re-publish it" dropped.
- resolve-on-the-editors-computer F4 | no change here: this piece's sentence stands.
- resolve-on-the-editors-computer F5 | changed: The editor can restart the app | "never has to restart" limited to the ordinary case, pointing to "What the editor is told when Resolve cannot be reached".
- sync-1 F8 | changed: The editor sees each ticked project with what it is doing and why | one closed list of states; "the others show waiting or paused" dropped.
- sync-1 F9 | changed: Notifications are the operating system's own, headed with the studio's name and mark | reminders also when what is owed cannot be told, and for a drive that stays not answering.
- sync-2 F4 | no change here: sync-2 changes its pointer to the menu's resume line.
- sync-2 F5 | changed: The app keeps its own work going when part of it stops | the setting to switch automatic recovery off and its status sentence dropped.
- sync-2 F6 | changed: The editor is told when the dashboard is not hearing from the computer, and when the clock is wrong | sync-2's sentence and threshold (more than 60 seconds, "Turn on setting the time automatically.").
- sync-2 F9 | changed: The editor sees each ticked project with what it is doing and why | the safe-to-close line placed in the app's window.
