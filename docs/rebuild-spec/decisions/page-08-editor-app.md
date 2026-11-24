# Decision list, page 8: The app on each editor's computer

Stays behind: never shown to the session that rebuilds the product.

19 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 8.1 An editor can stop syncing on their computer in four ways that behave differently (pause, stop all syncing, setting the computer to sync nothing, signing out). Which should an editor have?

- **Today:** pause is forgotten when the app restarts and lets small project files keep sharing; "stop all syncing" is remembered and stops everything; a computer set to sync nothing (wired) does nothing at all; signing out stops syncing and reporting. Each says something different in the app.
- **Options:** A: keep all four. B: one pause for the editor that stops everything and is remembered until they resume (the stop folded into it), the wired role for a computer that works off the server, and signing out kept for what it is (giving the computer up), not as a way to stop syncing.
- **Recommended:** B, because one pause that means "nothing moves until I say" is what an editor reaches for, and a second, stronger stop beside it is a choice nobody can tell apart.
- **What you would notice:** with B the editor sees one pause and one resume; the admin's studio-wide stop is unchanged; with A nothing changes.
- (editor-app-Q1)

### 8.2 A field backup page opens from the app's menu on computers where it is switched on. Is it wanted, and is it on by default?

- **Today:** when field backup is on for a computer, "Field backup..." in the menu opens a local page; whether it is on by default is not clear.
- **Options:** A: keep it, shown only while the camera cards part is on and off by default per computer. B: cut it from the app's menu; field backup is reached from the Footage Sorter's own pages.
- **Recommended:** A, as long as field backup itself stays in the Footage Sorter; a menu line that appears only when switched on costs the everyday menu nothing.
- **What you would notice:** with A an editor who backs up in the field opens it from the menu; with B they open it from the dashboard's Footage Sorter pages.
- (editor-app-Q3)

### 8.3 Every button in the settings window closes the window before it acts, and some then reopen it. Should the window stay open and show the result instead?

- **Today:** pressing any button in the settings window closes it first, does the work, and for a setting change opens it again.
- **Options:** A: the window stays open and shows the result in place. B: keep closing and reopening.
- **Recommended:** A, because a window that vanishes and comes back loses the editor's place and looks like a crash.
- **What you would notice:** with A the editor stays where they were and sees what their click did.
- (editor-app-Q5)

### 8.4 A remote editor must install the private network's app and sign in to it with an invite before the wizard can go on. Should reaching the server from outside still be a separate step the editor does by hand?

- **Today:** step 2 of the wizard sends the remote editor to install the network's app (on Windows from a button, on a Mac from its download page), sign in with the admin's invite, and check the connection before going on.
- **Options:** A: keep it as a step of the wizard, as written. B: the wizard joins the computer to the studio's network itself from what the admin set up, with no separate app to sign in to.
- **Recommended:** A, because the studio's private network is the only way in by your earlier decision and it belongs to the studio, not the product; B would need the product to hold the keys to the studio's network.
- **What you would notice:** with B a remote editor has one sign-in instead of two.
- (editor-app-Q10)

### 8.5 Uninstalling on a Mac leaves Resolve's drive mapping that set-up added. Should uninstall remove it?

- **Today:** the Mac uninstaller always leaves the mapping and says to remove it in Resolve's preferences if wanted.
- **Options:** A: uninstall removes the mapping it added (only when Resolve is closed; otherwise it says how), keeping any other. B: leave it, as now.
- **Recommended:** A, because uninstall should take away what install added, and a mapping pointing at a folder the product no longer manages only confuses later.
- **What you would notice:** with A a Mac editor who uninstalls finds Resolve's mapping gone, and clips on the studio's drive show offline in Resolve.
- (editor-app-Q11)

### 8.6 Should a computer ever sync without anyone signed in?

- **Today:** requiring sign-in is a setting on the computer, on by default; with it off the computer reports under a name typed on the computer, and with no dashboard address at all it syncs the whole tree on its own.
- **Options:** A: every computer must have someone signed in before anything syncs, and a computer with no dashboard address syncs nothing and says so. B: keep the switch and the name.
- **Recommended:** A, because a computer nobody is signed in to is invisible to the admin and its reports name nobody, and one rule is simpler for editors and support.
- **What you would notice:** with A a studio running a computer without sign-in has to sign it in once.
- (editor-app-Q13)

### 8.7 Should the app show only one of its windows at a time, or let several be open together?

- **Today:** asking for a window while another is open is refused with "Another CCSync window is already open. Close it first."; the app's own prompts wait until the open window closes, or turn into a notification; restart and update are refused while any window is open.
- **Options:** A: several windows may be open at once, each kind once (asking again brings it forward); restart, update and quit still ask when they would cut off what a window is doing. B: one window at a time, as now, with prompts waiting their turn.
- **Recommended:** A, because a refusal to open a window is a dead end for the editor, and lessons from real use show one unanswered window silencing every other prompt and update for a day.
- **What you would notice:** with A an editor never sees "close it first" and a question about one project never waits behind a window about another.
- (editor-app-Q14)

### 8.8 The app shows two different one-line summaries of syncing: one in its menu ("Sync: ...") and one in its window ("syncing <project> (n/total)", "Waiting for the server ..."). Should there be one?

- **Today:** the menu's line says what is moving or what holds syncing; a second status line names the project being synced and whether the computer is using a saved plan.
- **Options:** A: one status sentence, used in the menu and the window alike, which also carries the project being synced and the "waiting for the server" states. B: keep both.
- **Recommended:** A, because two summaries of the same thing in different words will one day disagree.
- **What you would notice:** with A the editor reads the same words in the menu and the window.
- (editor-app-Q15)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 8.9 | Sending crash reports to an outside crash-collection service is present but can never work. Can it go? | a setting and an address exist for sending each crash to an outside service, but no address is built in and the sending part is not in the installed app. | A, because the dashboard already sees every computer's crash count and newest report, and an outside service is another place customer data goes. (editor-app-Q2) |
| 8.10 | A refused computer sign-in is announced in four places (a menu line, a warning line, a line beside the identity, a button) and the sign-in window is opened from four. Keep all, or one warning with one button plus the menu line? | after ten refused reports the settings window shows a warning in its list of warnings and a second red line beside the identity with a SIGN IN AGAIN button; the menu has "Sign in again"; the settings window also has SIGN IN and SIGN OUT buttons; the menu has "Sign in…". | B, because one warning with its button and one menu line is enough to be found, and two red lines saying the same thing read as two problems. (editor-app-Q4) |
| 8.11 | Two protections overlap when a new version of the app will not stay up: going back to the previous version after repeated failed starts, and giving up relaunching after three times an hour. Is one rule enough, and what should the editor and admin see? | a version that starts 3 times in 10 minutes without a clean shutdown is replaced by the one before; separately the app is relaunched at most 3 times an hour and then left down; and when the program is missing after a broken update the previous version is put back. | A, because one rule says one thing to the editor and admin, and it keeps the ruled three-an-hour relaunch for ordinary crashes. (editor-app-Q6) |
| 8.12 | The installer can be downloaded directly or picked from a page that shows the same builds. Keep both? | a direct download link picks the platform from the browser, and a separate page lists each platform with version, size and checksum and its own button. | A, because the page already marks "this computer"; the link an admin hands over is the only other way in a new editor needs, since they cannot sign in yet. (editor-app-Q7) |
| 8.13 | A computer can be set up through the wizard or a hand-run install, and a new version can arrive by the app's own update, a hand-run upgrade or by running the wizard again. Keep only the wizard (for setting up or repairing) and the app's own update (for new versions)? | the wizard is what editors are pointed at; a hand-run install does the same job for technical people, with a preview mode; a hand-run upgrade swaps the app in by hand; running the wizard again also installs the version it carries. | A, because two ways to set up a computer must be kept identical for ever, and the wizard already does everything the hand run does. (editor-app-Q8) |
| 8.14 | Uninstalling on a Mac removes the computer's identity (so the admin must approve it again) even in the default mode, while on Windows it is kept unless a full uninstall is asked for. Which should both follow? | Windows keeps the identity, sign-in and server connection by default; a Mac removes the identity and its server connection by default and keeps the sign-in. | A, because a repair-by-reinstall should not cost an admin's approval, and removing every credential already makes the computer unable to reach the server until someone signs in. (editor-app-Q9) |
| 8.15 | A hand-run Windows install can leave the editor's project folder reachable from other computers on the network. Keep this option? | an option of the hand-run install, with a warning, leaves the folder served to other computers; the wizard never offers it. | A, because it serves the whole project tree to any network the laptop joins, and nothing an editor does needs it. (editor-app-Q12) |
| 8.16 | When the project open in Resolve has no home on the server, the editor is asked once and can also set it up later from a menu line. Keep both? | a one-time question opens the dashboard's set-up page; afterwards a menu line does the same while the project still has no home. | A, because the question is asked once ever per project and the menu line is the way back to it; neither repeats. (editor-app-Q16) |
| 8.17 | A shared library or included folder that is not working is reported in four places: the one-line status, the app's project list, the settings window and the dashboard. Keep all? | the same problem sentence appears in each of the four. | A, because a sentence repeated in three places of one app reads as three problems. (editor-app-Q17) |
| 8.18 | The editor can restart the app from its menu and from its settings window. Keep both? | "Restart CCSync" in the menu and "RESTART CCSYNC NOW" in the settings window behave the same. | A, because restart is what support asks for first and the settings window is where an editor is looking when something is wrong; both are one control doing one thing. (editor-app-Q18) |
| 8.19 | Two things in these items are tools for the people building the product. Can they go from the specification? | a check that draws a second tray icon for about five seconds, and a setting that lets pages served from the computer itself send to Resolve. | A; neither is something an editor or admin meets. (editor-app-Q19) |

## Your answers

ANSWERED 2026-11-24. After answering pages 2 and 3 and most of page 4 one
by one, he said of everything still waiting: "accept all the
recommendations." So every question on this page is answered with its
recommendation.
