# Entries that may be one lesson filed twice: batch 2 of 2 (67 groups)

## Group 108

### DSH-077 [dashboard / Reports from computers]: A momentary empty listing made the server treat projects as deleted.
- What was going on: The NAS sync service restarted empty or a volume was not mounted yet, so projects were deactivated and their inventory wiped; the later refusal never reached the owner.
- What the product must do: A pass that would deactivate over a quarter of projects or drop over 90% of a project's files is refused, keeps the old data, and stays on the home page until resolved.
- Kind: 3

### APP-038 [editor-app / Drive letters and network drives]: On a Mac with the NAS unmounted, downloads would fill the boot disk.
- What was going on: On macOS a share's path under /Volumes is just a folder on the boot disk when the share is not mounted.
- What the product must do: Nothing is written under a mount path unless the share is confirmed mounted immediately before writing.
- Kind: 1a

### SRV-062 [server-install-and-running / Shares that go away, and checks that cannot run]: A NAS share that drops leaves an empty folder where it was mounted.
- What was going on: An unmounted share, or a volume mounted after the server starts, reads as an existing empty folder, and free space is then measured on the wrong disk.
- What the product must do: A share is judged present only by something that exists on the real share, never by its mount folder existing or listing.
- Kind: 1a

### YTD-075 [youtube / Choosing the destination and checking space]: Space was measured on the wrong disk, and freeing space changed nothing.
- What was going on: Downloads to an editor's disk were refused for lack of space on the NAS, and a refusal was kept a minute, so freeing 300 GB did nothing.
- What the product must do: Free space is measured on the disk that will be written, by the computer writing it, afresh each time download is pressed.
- Kind: 3

## Group 109

### DSH-079 [dashboard / Problems the server finds]: The server diagnoses itself as far as it can.
- What was going on: The owner: "make the server as self-diagnosing as possible. Any errors should be flagged, the diagnosis should be as clear as possible"; refusals had reached only a log.
- What the product must do: Every problem the server finds shows on the home page with a plain next step, and comes back if dismissed while still true.
- Kind: 2

### SRV-099 [server-install-and-running / Health checks and alerts]: The owner: the server finds and explains its own problems.
- What was going on: He asked to "include as many alerts as possible, make the server as self-diagnosing as possible. Any errors should be flagged, the diagnosis should be as clear as possible."
- What the product must do: Every problem the server can detect reaches a person on the home page and by message, with a plain diagnosis and the next action.
- Kind: 2

## Group 110

### DSH-082 [dashboard / Problems the server finds]: The footage-outside-the-tree warning must name the project.
- What was going on: The owner: "this warning should say which project. the project might be an editor's personal project which they don't want to sync."
- What the product must do: The warning names the project; a project tied to no synced project raises nothing; when the open project is unknown it says "could not check", never "fine".
- Kind: 2

### RSV-060 [resolve-on-the-editors-computer / Clip paths and media outside the shared tree]: Media used from outside the project folder raises a warning naming the project.
- What was going on: The owner wanted a popup to move such media "to where it is syncable", and: "this warning should say which project", since it may be an editor's personal project.
- What the product must do: The warning names the clip, the Resolve project and where to move it, and a project that is not one of the studio's synced projects raises nothing.
- Kind: 2

## Group 111

### DSH-086 [dashboard / Problems the server finds]: The owner was mailed "cleared" about problems nobody had fixed.
- What was going on: Anything absent from a scan counted as recovered: another project opened, a cap of 20 or 40 per kind, a recency window, a check with no verdict.
- What the product must do: A problem closes only when a complete check found it gone; capped, filtered, skipped or unchecked subjects stay open and mail nothing; a display limit never limits what is known.
- Kind: 3

### ALL-050 [whole-product / Could not check, refusals and nothing silent]: "Could not check" was shown as fine, zero or cleared.
- What was going on: A crashed scan read "fully covered", a closed Resolve showed zero problems, a failed check mailed "cleared", and a release gate passed an empty error list.
- What the product must do: Anything not checked shows "not checked" or "cannot tell", never OK, zero or passed; earlier problems stay open, and any gate meeting it refuses.
- Kind: 3

## Group 112

### DSH-090 [dashboard / Problems the server finds]: An optional feature that failed simply vanished from the menu.
- What was going on: B-roll or music search failing to start lost its link with no reason shown, and a feature whose NAS share dropped at night stayed advertised as working.
- What the product must do: A feature that is on but unavailable shows broken with its reason; one whose data disappears shows degraded within one check; unreadable status reads "not checked".
- Kind: 3

### MUS-039 [music / Keeping the library's data whole]: A library written by a newer version broke every request.
- What was going on: Publishing a music index from a newer build made every request fail while the menu still offered the page as working.
- What the product must do: Data written by a newer version is detected at start, the section is marked degraded with that reason, and its link is not offered as working.
- Kind: 3

## Group 113

### DSH-093 [dashboard / Problems the server finds]: A slowness warning blamed the wrong cause.
- What was going on: A slow but harmless NAS scan was reported as holding the data store, and slow-write timing counted queue waits and advised editors to untick.
- What the product must do: A slowness problem measures only how long the lock was held, names the real holder, never advises an editor to untick, and clears once a later check passes.
- Kind: 3

### SRV-116 [server-install-and-running / Health checks and alerts]: A busy server made reports wait seconds, and its warning blamed the editors' computers.
- What was going on: With the CPU busy, each report held the database write lock up to 17.6 seconds; the warning blamed the reporting computer and advised unticking projects.
- What the product must do: Reports finish in about a tenth of a second under load, and a slow-write warning measures the lock holder and never blames an editor's computer.
- Kind: 3

## Group 114

### DSH-094 [dashboard / Problems the server finds]: Alerts counted deliberate restarts as crashes.
- What was going on: Intentional restarts and a test abort counted as crashes, and an alert fired when the studio ran a newer server than the vendor offered.
- What the product must do: Alerts never count a deliberate restart as a crash, and never flag running a newer release than the vendor offers.
- Kind: 3
- State: still open

### APP-060 [editor-app / Starting, staying running and crashing]: Fourteen "crashes" on one computer were all deliberate stops.
- What was going on: Upgrades, test runs and manual restarts each filed a crash report, and a manual upgrade killed an instance that had just upgraded itself.
- What the product must do: A deliberate stop (upgrade, quit, an operator's kill) is never counted as a crash, and two upgrade routes on one computer never kill each other's result.
- Kind: 3
- State: still open

### REL-034 [releases-and-updates / Trying a build on one computer first]: A trial build was blamed for crashes written by older builds.
- What was going on: The crash count was a lifetime total, so weeks-old crashes held a new build back, and test kills and deliberate restarts were counted as its crashes.
- What the product must do: Only real crashes after the build started on that computer count; deliberate restarts never do, and when it cannot be told the build is not passed and says so.
- Kind: 3
- State: still open

## Group 115

### DSH-097 [dashboard / Alerts by mail]: Alert mail comes as one digest, not one mail per alert.
- What was going on: Turning mail alerts on sent eleven messages in one minute, and every unfixed error mailed again daily; the owner: "I'm getting spammed with emails now."
- What the product must do: One message per check: new problems worst first, unfixed ones one line each with days open, recoveries included; the first message says it is a catch-up.
- Kind: 2

### SRV-100 [server-install-and-running / Health checks and alerts]: The owner: setting up alert mail sent eleven separate e-mails at once.
- What was going on: The owner: "I'm getting spammed with emails now". Each open finding was mailed on its own.
- What the product must do: A person gets at most one alert e-mail per check cycle, a digest listing every new, cleared and still-open finding.
- Kind: 2

### SRV-104 [server-install-and-running / Health checks and alerts]: Problems open before alerts were set up were never sent.
- What was going on: Problems found while no destination existed were recorded as already raised, so configuring mail later sent nothing about them.
- What the product must do: When an alert destination is first set, everything currently open is sent at the next check, and the save says so.
- Kind: 3

## Group 116

### DSH-125 [dashboard / Pages that refresh and answer clicks]: The only button that closes an error was red text on a red banner.
- What was going on: Error banners are red and buttons were drawn red, so dismiss was clickable but unreadable on every error.
- What the product must do: Every button and link on any banner is legible against that banner's own colour.
- Kind: 3

### ALL-030 [whole-product / The look]: A banner's dismiss button was invisible, so stale errors were mailed daily.
- What was going on: The dismiss link was red text on a red banner, so nobody could close five stale error cards, mailed out daily as "still not fixed".
- What the product must do: Every button on a warning or error banner is clearly visible against it.
- Kind: 3

## Group 117

### DSH-130 [dashboard / Phones and the installed app]: A phone zooms the page when a text field under 16 px is tapped.
- What was going on: Phone browsers zoom in on focusing a small input and do not zoom back out, leaving the page sideways.
- What the product must do: Every input on a phone-sized screen has text of at least 16 px.
- Kind: 1a

### ALL-010 [whole-product / The look]: iOS zooms the whole page when a form field's text is under 16 px.
- What was going on: On an iPhone, focusing an input whose text is smaller than 16 px zooms the whole page.
- What the product must do: Every form field on a phone uses at least 16 px text.
- Kind: 1a

## Group 118

### DSH-143 [dashboard / Stopping and resuming the fleet]: An admin can resume a computer's stopped downloads from the dashboard.
- What was going on: The admin had checked the NAS and knew the trip was harmless, but only the editor at that computer could clear it; the owner asked for a remote resume.
- What the product must do: An admin can resume a stopped computer's downloads from the dashboard, and the resume applies only to the stop in force when pressed.
- Kind: 2

### PRX-079 [proxies-and-file-moves / Moves made by hand on the NAS]: Every hand move on the NAS tripped the download safety stop.
- What was going on: The owner: "this happening every time I move something on the server is a major issue"; to every holding computer, a hand move looked like mass deletion.
- What the product must do: A file found elsewhere on the NAS with the same name and size is followed as moved and never counts as a deletion toward the safety stop.
- Kind: 3

### SYN-045 [sync / Safety stops]: Only the editor at the keyboard could clear a tripped safety stop.
- What was going on: A remote computer stayed stopped until its owner returned; a first remote resume then stayed in force, re-releasing every new stop and binning 100 proxies a minute.
- What the product must do: An admin can clear one computer's safety stop from the dashboard; one click releases exactly one current stop, and any later stop waits for a person again.
- Kind: 3

### YTD-056 [youtube / Where a download runs, and saying so]: An editor's computer stopped downloading its own clips, and nobody knew why.
- What was going on: The owner asked twice why a remote editor's app was not downloading YouTube clips on his own computer; no cause was recorded.
- What the product must do: When a computer that should download a clip does not, the dashboard states that computer's reason.
- Kind: 3
- State: outcome not found

## Group 119

### APP-007 [editor-app / Installing and setting up]: Editor computers supported: Windows 10 22H2 or 11 on x64, and Apple silicon Macs.
- What was going on: The owner accepted this list, unmanaged machines only; company-managed machines (pushed installers, application allow-lists) are unsupported and the terms say so.
- What the product must do: Setup on an Intel Mac or an unsupported Windows stops, before changing anything, with a message naming what is supported.
- Kind: 2

### REL-042 [releases-and-updates / Offering an update to a computer]: An Intel Mac was offered an Apple silicon build it could never run.
- What was going on: Builds were matched by operating system only, from some offer paths, so the Mac downloaded, failed to start and rolled back for ever.
- What the product must do: Every offer, from every path, matches the computer's operating system and processor, and when no build exists for it the computer and dashboard say so.
- Kind: 3

### ALL-008 [whole-product / The rebuild itself]: The supported platforms are one fixed, published list.
- What was going on: Nothing said what the product runs on; the owner's list is Windows 10 22H2 or 11 x64, Apple silicon Macs, Resolve Studio 20, TrueNAS 25 or 26, Synology DSM 7.2.1.
- What the product must do: The supported-platform list is published, and every install check agrees with it exactly.
- Kind: 2

## Group 120

### APP-039 [editor-app / Drive letters and network drives]: The shared drive letter is a studio setting, not built in.
- What was going on: The owner plans to sell the product and wants each studio to set its drive letter once, carried to every editor install.
- What the product must do: A studio sets its project drive letter once, and every new editor install uses it with no change to the program.
- Kind: 2

### SRV-018 [server-install-and-running / Installing on a NAS]: The owner: the drive letter editors see the tree on is set on the server.
- What was going on: The tree's drive letter is site data, defaulting to P:, so a second studio never needs a different installer.
- What the product must do: The drive letter is set once on the server, defaults to P:, and every installer and editor app reads it from there.
- Kind: 2

## Group 121

### APP-061 [editor-app / Starting, staying running and crashing]: A dead background part of the app was reported as running.
- What was going on: Watchdogs asked "was it started", not "is it alive"; the loop driving sync stopped with no restart, and back-off spacing meant the hourly restart limit never applied.
- What the product must do: Every background part is judged alive by doing its work, restarted with growing waits, stops after six restarts an hour asking for a person, and each restart is reported.
- Kind: 3

### RSV-029 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: A dead background helper kept reporting itself as running.
- What was going on: The restart check counted helpers started rather than alive, so a dead one was never restarted and the editor's phone page stayed dead.
- What the product must do: A helper whose work has stopped is restarted within a minute, judged by whether it is actually alive.
- Kind: 3

## Group 122

### APP-064 [editor-app / Starting, staying running and crashing]: Quit, cancel or an update left a transfer or encoder running after the app.
- What was going on: The app exited before its tear-down finished; transfers outlived it and raced the new build, and an orphaned local model held 4 to 12 GB of video memory.
- What the product must do: Quit, cancel, restart and update stop every helper the app started (waiting up to 40 seconds), and at start any leftover helper is stopped first.
- Kind: 3
- State: fixed, never shipped

### JOB-018 [fleet-jobs / Stopping and cancelling]: A cancelled transcription kept the graphics card busy after "stopped".
- What was going on: Ending a process on Windows does not end the processes it started, so a helper kept writing, held graphics memory or kept a half-downloaded file locked.
- What the product must do: Cancel, stop and quit end every process a job started within seconds, and report done only once all have exited.
- Kind: 1a

## Group 123

### APP-067 [editor-app / Starting, staying running and crashing]: After an update the app was gone until someone restarted it by hand.
- What was going on: The new version started while the old one still held the run-once lock and quit, and "update complete" was reported without checking the new app stayed up.
- What the product must do: After an update exactly one copy runs; success is reported only if the new app is still running seconds later, and otherwise the old one keeps running.
- Kind: 3
- Move to: releases-and-updates

### REL-046 [releases-and-updates / Installing an update on an editor's computer]: An update failed but reported success, leaving the old build running for days.
- What was going on: The install step failed yet exited cleanly, relaunched the old build, and the release reported complete.
- What the product must do: An update is reported done only once the new version is confirmed running; otherwise it says it failed and names the version still running.
- Kind: 3

## Group 124

### APP-092 [editor-app / Windows, dialogs and notifications]: Windows "show in folder" opened Documents for a path with spaces.
- What was going on: Explorer's select switch must arrive as one unquoted "/select,<path>" token with only the path quoted; quoting the whole argument silently opens Documents.
- What the product must do: "Show in folder" opens the containing folder with the file selected, for paths with spaces and Chinese characters.
- Kind: 1a

### ALL-075 [whole-product / Windows, text and names]: Explorer ignores its select switch when the switch arrives inside quotes.
- What was going on: "Open in Explorer" opened Documents for every clip whose path had a space, because the quoted select switch was silently ignored.
- What the product must do: Reveal in Explorer opens the right folder with the clip selected for paths with spaces, brackets and non-Latin letters, checked against the window that opened.
- Kind: 1a

### YTD-091 [youtube / Reaching the editor and Resolve]: "Show in folder" opened Documents for every clip.
- What was going on: Windows Explorer's select-a-file option works only in one exact quoting form; quoting the whole option opens a default folder instead.
- What the product must do: "Show in folder" opens the containing folder with the file selected, for any path, verified by the folder that actually opened.
- Kind: 1a

## Group 125

### APP-104 [editor-app / Windows, dialogs and notifications]: Clips found while a dialog was open were lost behind an "already open" notice.
- What was going on: The owner ruled: "get rid of the popup already open message ... the editor can decide"; clips found meanwhile were silently dropped.
- What the product must do: Clips found while a dialog is open are shown, without duplicates, as soon as it closes, and no "already open" notice appears.
- Kind: 2
- Move to: resolve-on-the-editors-computer

### RSV-067 [resolve-on-the-editors-computer / Clip paths and media outside the shared tree]: Clips found while an editor read a popup were silently dropped.
- What was going on: A batch found while one popup was open was discarded behind an "already open" notice re-fired every 3 seconds.
- What the product must do: Later batches queue and show when the current popup closes, deduplicated so the same clips never produce repeated dialogs.
- Kind: 3

## Group 126

### APP-110 [editor-app / Telling the editor what is wrong]: Tray status lines hid the real cause behind jargon.
- What was going on: The tray showed "Something went wrong" for hours, "tidying old files in slices" and "paused at the 600s project budget", none of which an editor could understand.
- What the product must do: Every status names its actual cause in plain words, and a deliberate safety pause reads as progress with when it resumes, not as an error.
- Kind: 3

### SYN-104 [sync / Saying truthfully what the sync is doing]: The app said "Something went wrong" for hours without naming the cause.
- What was going on: Only a transfer's last line was kept, hiding the real cause, and the main status said "Something went wrong" while a line below gave the reason.
- What the product must do: An error names its real first cause in the same words in the editor's app, the dashboard and the log; a safety limit doing its job shows as paused, not an error.
- Kind: 3

## Group 127

### APP-119 [editor-app / Telling the editor what is wrong]: Ages and deadlines shown to editors were wrong.
- What was going on: A sync plan live a minute read "10 days ago", and the trash deadline ignored the site's retention setting.
- What the product must do: Every age, deadline and retention figure shown to an editor reflects the true value and this site's settings.
- Kind: 3

### ALL-040 [whole-product / Wording]: Parts of the product ignored the site's drive letter and folder names.
- What was going on: Installers, messages and sync steps assumed the default drive letter, projects folder, login port and account ids, so another studio's install mapped wrong drives and broke silently.
- What the product must do: Every part reads drive letter, tree, projects and proxy folder names, NAS login port and account ids from the same site settings, or refuses a value it cannot honour.
- Kind: 3

## Group 128

### APP-120 [editor-app / Telling the editor what is wrong]: A rehearsal read "Copying ... 0 B of 800 GB" for its whole run.
- What was going on: A dry run of a large copy reused the real copy's progress wording, so it looked stuck at zero.
- What the product must do: A rehearsal says it is a rehearsal and shows what it checked, never copy progress.
- Kind: 3

### RSV-135 [resolve-on-the-editors-computer / Fixing media: copying in, rehearsals and undo]: A rehearsal of fixing media reported files copied, failed or uploading.
- What was going on: In rehearsal mode nothing is copied, yet results said "69 copied" or 69 failed, the bar showed 800 GB in two seconds or froze at 0%, and an upload could start.
- What the product must do: The mode is visible before the click; a rehearsal says "Checking", moves by clips checked, says nothing was copied, starts nothing; a real run states how many it copied.
- Kind: 3

### ALL-059 [whole-product / Could not check, refusals and nothing silent]: A rehearsal told people things had changed.
- What was going on: A rehearsal uninstall said removal failed and to delete by hand, and rehearsals showed "Copying 0 B of 800 GB".
- What the product must do: A rehearsal says "checking" or "would", never claims or demands a change, and counts exactly what the real run would do.
- Kind: 3

## Group 129

### APP-121 [editor-app / Telling the editor what is wrong]: A repeating warning rotated away the log history support needed.
- What was going on: A port held by another program logged six lines every two minutes, and a per-clip "missing" line filled the 5 MB log every 25 minutes.
- What the product must do: A recurring condition is logged loudly once when it starts, then as a count per pass until it changes, so the log keeps days of history.
- Kind: 3

### ALL-086 [whole-product / Requests, logs and outside programs]: The same unchanged problem was logged every pass, burying everything else.
- What was going on: Repeating warnings ran to 1,350 lines a day in a 5 MB log, and an unreachable server would log once a second per clip.
- What the product must do: A repeating condition is logged when it starts or changes and quietly in between, so a day of it costs a handful of lines.
- Kind: 3

## Group 130

### APP-126 [editor-app / Signing in, the computer's identity and the licence]: A failed re-sign-in replaced a computer's working sign-in with an unusable one.
- What was going on: An unusable answer to a new sign-in attempt was saved over the good stored one, signing the computer out.
- What the product must do: A failed or unusable sign-in attempt never replaces a computer's working sign-in.
- Kind: 3

### SYN-022 [sync / A plan belongs to a computer]: Signing in as someone else ran the previous person's projects.
- What was going on: The saved sync plan was not tied to who signed in, and a sign-in with an unusable answer overwrote a working identity.
- What the product must do: After a sign-in the computer runs only the signed-in person's plan, and a failed sign-in leaves the previous working identity intact.
- Kind: 3

## Group 131

### APP-127 [editor-app / Signing in, the computer's identity and the licence]: Pause then resume started syncing on a computer nobody had signed in to.
- What was going on: Start and sign-in refused to sync while signed out, but resuming from pause did not check, even after a sign-in had lapsed.
- What the product must do: No path, resume from pause included, starts syncing on a computer that is not signed in when sign-in is required.
- Kind: 3

### SYN-056 [sync / Studio-wide stops and the editor's pause]: Signing in or restarting silently resumed syncing the editor had paused.
- What was going on: Sign-in restarted every transfer while Pause still showed ticked, releasing a studio-wide stop erased an editor's own stop, and accepting the licence started sync with nobody signed in.
- What the product must do: While Pause is on nothing starts, through sign-in, restart, update or another stop's release, and sync never starts with nobody signed in.
- Kind: 3
- State: outcome not found

## Group 132

### APP-131 [editor-app / Signing in, the computer's identity and the licence]: Wired to the NAS or remote belongs to the computer, never the person.
- What was going on: Setup set a computer's role from whether its person was an admin, so the owner's laptop counted as wired and an admin's remote laptop was dismantled.
- What the product must do: The wired-or-remote choice made in setup becomes that computer's own setting, and nothing derived from the person's account ever changes it.
- Kind: 2

### SYN-023 [sync / Wired or remote]: Wired or remote belongs to each computer, not to the person signed in.
- What was going on: One account owns an office desktop wired to the NAS and a remote laptop; the owner's laptop synced as wired because admins were treated as wired.
- What the product must do: Any number of computers can be wired; each is set on that computer, never derived from who signs in, and automatic detection may switch to wired but never back.
- Kind: 2

## Group 133

### APP-132 [editor-app / Signing in, the computer's identity and the licence]: The owner switched his server-side computer to remote by one click and feared deletions.
- What was going on: Remote mode may remove local files during download, so flipping the NAS-side machine endangered the live share; the reverse click silently stopped all syncing.
- What the product must do: Switching a computer between wired and remote asks first, names the consequence plainly, and the direction that can delete needs the word REMOTE typed.
- Kind: 3

### ALL-064 [whole-product / Safety in what the product does]: One click stopped syncing, signed people out or stopped the fleet.
- What was going on: Stopping the fleet, wiping a plan, revoking sign-ins, signing out every session including your own and switching a computer to wired all acted at once.
- What the product must do: Any action that stops syncing, deletes, revokes, signs out or affects every computer asks first stating the consequence, and looks unlike harmless controls.
- Kind: 3

## Group 134

### APP-137 [editor-app / Settings, records and background work]: Reports from editors' computers grew with the size of the media pool.
- What was going on: A list of refused relinks had no cap, so 200 or more clips went into every 30-second report.
- What the product must do: Every list a computer reports is capped, keeping the newest, with a count of what was left out.
- Kind: 3

### RSV-092 [resolve-on-the-editors-computer / Missing clips, relinking and refreshing]: Pending relinks hammered Resolve over and over.
- What was going on: Each pending relink walked Resolve's whole media pool several times per pass, and 158 refused clips were re-offered every 3 seconds without de-duplication.
- What the product must do: Pending relink work is de-duplicated, capped, and checked against Resolve at most once per pass, however many projects or clips wait.
- Kind: 3

## Group 135

### APP-144 [editor-app / Settings, records and background work]: A Mac laptop on battery with its lid closed sleeps despite keep-awake.
- What was going on: A remote editor's Mac on battery with the lid shut slept overnight though the app asked to stay awake, and the interrupted upload started again from zero.
- What the product must do: When an upload is owed, the editor is warned that closing the lid on battery stops it, and the dashboard shows this as the reason.
- Kind: 1a
- State: outcome not found

### SYN-097 [sync / Uploads that cannot resume, shutdown and sleep]: A Mac laptop on battery with its lid closed sleeps despite a keep-awake request.
- What was going on: macOS sleeps a closed-lid laptop on battery even with a keep-awake request, waking only briefly, so an overnight upload stalled from about 23:00 to 03:21.
- What the product must do: When a Mac is about to sleep with transfers owed, the person is told what is unfinished, and transfers resume by themselves on wake.
- Kind: 1a

## Group 136

### APP-S07 [editor-app / Sealed]: On Windows a timed-out wait on a helper process could still hang for ever.
- What was going on: After a timeout killed the child, collecting its output could block indefinitely on Windows, so the timeout bounded nothing.
- What the product must do: Every wait on a helper process has a true upper bound on Windows, including after the helper has been killed.
- Kind: 1b
- Tool: Python subprocess.run with timeout on Windows

### SYN-S35 [sync / Sealed]: A time-limited child-process wait could still hang forever on Windows.
- What was going on: After killing a child on timeout, the call waits for its output pipes to close, which never happens when a grandchild inherited them.
- What the product must do: Every wait on a child process has a hard limit, and a run cut off is reported as "could not tell", never as an empty result.
- Kind: 1b
- Tool: Python subprocess.run(timeout=) on Windows

## Group 137

### JOB-006 [fleet-jobs / When a computer counts as free and able]: A computer that could not take a pushed update silently dropped out of jobs.
- What was going on: An update asked for a build withheld from that computer (recalled, wrong processor, needs a newer server), and it was kept from every job for 14 days.
- What the product must do: A computer an update cannot reach stays eligible for every job it can run, and the admin is shown why it was not updated.
- Kind: 3

### REL-057 [releases-and-updates / Pushing updates and seeing who has what]: A push the computer could not take kept it out of fleet jobs.
- What was going on: A push of a build withheld from that computer (wrong processor, withdrawn) stayed "waiting" for 14 days and the computer was treated as mid-update.
- What the product must do: A push that cannot be delivered says so beside the computer with the reason, and the computer keeps taking jobs.
- Kind: 3

## Group 138

### JOB-025 [fleet-jobs / Outages and withdrawn access]: A three-second server restart killed a running job and blamed the computer.
- What was going on: One failed check-in ended the job, counted an attempt and cooled the computer down, while a real refusal of access mid-run was treated as a passing error.
- What the product must do: A running job survives brief server or network loss and stops only when the server says the job is gone or access is withdrawn.
- Kind: 3

### YTD-065 [youtube / One job, one computer]: A three-second dashboard restart ended a 22-clip download at clip 2.
- What was going on: The editor's computer treated one refused connection during a brief restart as the end of the job, and the server then fetched clips the editor could not get.
- What the product must do: A job survives the server being unreachable for up to 60 s, while a clear error answer such as "job over" still stops it.
- Kind: 3

## Group 139

### JOB-S01 [fleet-jobs / Sealed]: A machine lists the hardware encoder and then fails mid-encode.
- What was going on: A machine without a suitable graphics card still lists the hardware encoder; a 64x64 test frame fails even on a real RTX 3080.
- What the product must do: Hardware encoding is used only after a real one-frame encode of at least 320x240 succeeded on that machine.
- Kind: 1b
- Tool: ffmpeg h264_nvenc

### PRX-S04 [proxies-and-file-moves / Sealed]: A machine listed a GPU encoder it could not use.
- What was going on: The encoder lists NVIDIA's hardware encoder on a machine with no GPU, and a 64x64 test encode fails even on a real RTX 3080.
- What the product must do: Hardware encoding is used only after a real one-frame 320x240 test encode has succeeded on that machine.
- Kind: 1b
- Tool: ffmpeg with NVIDIA's hardware encoder (nvenc)

## Group 140

### SRT-026 [footage-sorter-and-camera-cards / What cameras and recorders write]: Camera RAW video has no picture to show until its proxy exists.
- What was going on: Common open decoders cannot read Blackmagic RAW or RED RAW, so such a clip gets a thumbnail or preview only from its proxy.
- What the product must do: A RAW clip previews from its proxy, says plainly when it has none yet, and picks up the picture soon after a proxy appears.
- Kind: 1a
- State: fixed, never shipped

### PRX-040 [proxies-and-file-moves / Making proxies on editors' computers]: The originals picker showed no picture and could not play a clip.
- What was going on: The owner: "there's no thumbnail or preview in the bring originals here dialogue".
- What the product must do: Each file in the originals picker has a thumbnail and plays its proxy; a Blackmagic RAW file without a proxy says "no proxy yet".
- Kind: 2
- State: fixed, never shipped

## Group 141

### SRT-092 [footage-sorter-and-camera-cards / The record of every copy]: Copy badges are outlined when healthy and filled only for a problem.
- What was going on: With 36,000 clips, a filled green badge on every healthy one would make the grid a wall of green.
- What the product must do: Copy-count badges are outlined when healthy, filled gold when not backed up, and red when only on a laptop, card or client drive.
- Kind: 2
- State: fixed, never shipped

### ALL-017 [whole-product / The look]: Green means backed up and nothing else; each colour has one job.
- What was going on: Assigned clips were green, colliding with "backed up"; the owner wanted the product's red, "red instead of orange", as the highlight.
- What the product must do: Green only for synced or backed up; cyan for selection, focus and go; gold for suggestions and warnings; red for brand, the one primary action and danger.
- Kind: 2

## Group 142

### SRT-128 [footage-sorter-and-camera-cards / Sorting into shoots, people and cameras]: The NAS is case-sensitive, so a differently cased folder became a second folder.
- What was going on: Windows treats "Ukraine trip" and "Ukraine Trip" as one folder; the NAS treats them as two, splitting footage between them.
- What the product must do: When a destination folder already exists in another letter case, copies and moves use the existing folder's spelling.
- Kind: 1a

### PRX-087 [proxies-and-file-moves / Names: letter case and Unicode]: A rename that only changed letter case ended as two files.
- What was going on: The case-sensitive NAS saw a rename that editors' disks saw as done already; the proxy kept the old case, and the old spelling was uploaded back.
- What the product must do: A case-only file rename is applied on every computer with its proxy renamed to match; a case-only folder rename is refused with a sentence.
- Kind: 1a

## Group 143

### SRT-162 [footage-sorter-and-camera-cards / The sorter page]: The footage page said "no clips match" while still loading.
- What was going on: The empty message appeared about 60 ms after page start and stayed until data arrived.
- What the product must do: Until clips arrive the page says it is loading, a failed load offers Try again, and "no clips match" appears only once data is there.
- Kind: 3

### ALL-052 [whole-product / Could not check, refusals and nothing silent]: The owner: "no clips match" appeared while the page was still loading.
- What was going on: The owner: "there is no 'loading' - it just says no clips match your current filter"; the empty message appeared before any data arrived.
- What the product must do: Until data arrives the page says it is loading; a failed load says so with a retry; "nothing found" appears only after a real answer.
- Kind: 2

## Group 144

### SRT-184 [footage-sorter-and-camera-cards / Filed here, belonging elsewhere]: A camera with a wrong clock dates clips in the future, and they never upload.
- What was going on: Clips dated ahead of now never passed an "old enough to upload" test, and nothing reported it.
- What the product must do: Footage dated in the future is uploaded like any other and reported to the editor, never skipped as too new.
- Kind: 1a
- State: still open
- Move to: sync

### REL-018 [releases-and-updates / Signing and trust]: An old or wrongly dated release list could lock computers out.
- What was going on: Nothing checked a release list was fresh, so an old one could be replayed; once checked, a list stamped hours ahead by a fast clock blocked every later one.
- What the product must do: Computers refuse a release list older than one already seen, and list dates never go backwards because a publisher's wrong clock is caught and named.
- Kind: 3
- State: fixed, never shipped

### SYN-124 [sync / Clocks and file age]: Footage dated in the future by a wrong camera clock never uploads.
- What was going on: Cameras with clocks set ahead write files dated in the future, and a rule to wait until files stop changing never sees them as settled.
- What the product must do: Future-dated files upload like any other, and the editor sees which file and date are wrong until they are fixed.
- Kind: 3
- State: still open

### ALL-081 [whole-product / Windows, text and names]: One file dated far in the future blanked every row after it.
- What was going on: A camera with no clock set writes absurd file dates, and one bad date broke the whole list from that row on.
- What the product must do: A file or folder with an impossible date shows a plain placeholder date and never hides or breaks any other row.
- Kind: 3

## Group 145

### SRT-S10 [footage-sorter-and-camera-cards / Sealed]: A hosted database's shared daily limits ran out and took other sites down.
- What was going on: 100,000 writes and 5 million reads a day per account; one change list read 26 million rows and a one-off repair 442 million, failing every site on the account.
- What the product must do: The copy record lives where no daily quota can stop it, and every job's reads scale with what it changes, are bounded, watched and stopped when far over.
- Kind: 1b
- Tool: Cloudflare D1 (free plan, limits shared per account)

### SRV-S22 [server-install-and-running / Sealed]: One bulk import used up a hosted database's daily allowance for every app.
- What was going on: The free tier shares 100,000 row writes and 5 million reads a day across all databases; one import or full-scan update used it until midnight UTC.
- What the product must do: Estimate rows written and read before any bulk job, send only changes, and test query plans on data of real size.
- Kind: 1b
- Tool: Cloudflare D1

## Group 146

### PRX-002 [proxies-and-file-moves / What Resolve accepts as a proxy]: A proxy one character off in its name never attached in Resolve.
- What was going on: Resolve pairs proxies by exact file name; a synced name that differed in one fullwidth punctuation mark (？ ：) left the clip without its proxy.
- What the product must do: Every file reaches the other side with a byte-identical name, Chinese and fullwidth punctuation included, in both directions.
- Kind: 1a

### PRX-005 [proxies-and-file-moves / What Resolve accepts as a proxy]: Resolve refused proxies only one or two frames short.
- What was going on: Resolve rejects a proxy whose frame count differs from the original's by even one frame, though it plays fine; a check with two frames of slack let them through.
- What the product must do: Every proxy, from any producer, has exactly the original's frame count for constant-frame-rate footage, or is refused and remade.
- Kind: 1a

### RSV-101 [resolve-on-the-editors-computer / Proxies in Resolve]: Resolve pairs a proxy with its clip only by exact file name.
- What was going on: A proxy whose name differs from the original's by even one character is not attached, so the clip plays the original or goes offline.
- What the product must do: A proxy always carries exactly the original's name, byte for byte, on every computer.
- Kind: 1a

### SYN-067 [sync / Names]: Names with full-width punctuation arrived changed and never relinked.
- What was going on: YouTube and Chinese titles use full-width ： ？ ｜ ⧸; names were rewritten on the editor's disk, worse each pass, so 29 of 68 proxies on one computer never relinked.
- What the product must do: A name containing full-width punctuation arrives byte-identical on the NAS and every computer, both ways, on every transfer path, recovery runs included.
- Kind: 3

### YTD-048 [youtube / File names and what a file carries]: Titles carry characters Windows forbids, and their full-width look-alikes.
- What was going on: Video titles contain characters Windows forbids and full-width look-alikes (？ ： ｜); a name changed by one character no longer matches its Resolve clip.
- What the product must do: A title becomes a name legal on Windows, macOS and the NAS once, at the source, and that name is carried byte for byte everywhere.
- Kind: 1a

## Group 147

### PRX-022 [proxies-and-file-moves / Raw camera formats and Blackmagic Proxy Generator]: Blackmagic Proxy Generator is Resolve started with a flag.
- What was going on: Its shortcut runs Resolve with "-pg", so only the command line tells it from the editor; it watches folders listed in its own settings.
- What the product must do: The generator is told from Resolve by its command line, the user's own watch folders are never removed, and it is never killed mid-run.
- Kind: 1a

### RSV-020 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: Blackmagic Proxy Generator runs as the Resolve program itself.
- What was going on: The proxy generator is the Resolve program started with a "-pg" switch, so a process check reads it as Resolve running.
- What the product must do: Detecting Resolve ignores a Resolve process started with the proxy generator switch.
- Kind: 1a
- State: still open

## Group 148

### PRX-051 [proxies-and-file-moves / Writing, copying and deleting files safely]: A copy inside the NAS share was slow, while a rename was instant.
- What was going on: Copying within the NAS share from Windows rewrites every byte on the NAS disks (190 to 450 MB/s), and a move across disks quietly becomes a copy.
- What the product must do: Moving within the NAS is a rename in place, never copy-then-delete; when a rename is impossible the move fails visibly.
- Kind: 1a

### SRV-127 [server-install-and-running / NAS speed, load and clock]: One copy inside the NAS made every share slow to list from that computer.
- What was going on: A NAS-to-NAS copy saturated the disks, and the NAS serves each PC's file sharing through one process, so all its listings queued behind it.
- What the product must do: Big copies between NAS folders are paced so a person's folder browsing on any share never waits more than a few seconds.
- Kind: 1a

## Group 149

### PRX-052 [proxies-and-file-moves / Writing, copying and deleting files safely]: A Synology's own SSH server cut every proxy over 514 MiB short.
- What was going on: A larger transfer-window setting made Synology's SSH server silently truncate large files while downloads reported success.
- What the product must do: Transfers to a Synology use settings it handles, larger ones are refused, and each transferred file's size is checked.
- Kind: 1a
- State: fixed, never shipped

### SYN-133 [sync / Facts about the NAS and the operating systems]: Synology's built-in secure file transfer silently cut proxies over 514 MiB short.
- What was going on: With large read sizes and many parallel requests, Synology DSM 7.2's secure file transfer stops at 539,000,832 bytes while the download appears successful.
- What the product must do: Transfer settings known to truncate on that NAS are refused, and a downloaded file shorter than the source is never marked done.
- Kind: 1a
- State: fixed, never shipped

## Group 150

### PRX-053 [proxies-and-file-moves / Writing, copying and deleting files safely]: An interrupted copy left an empty or partial clip that spread to every editor.
- What was going on: A crash, quit or hiccup mid-copy left a zero-byte or partial file under the real name; it uploaded, and other tools counted half-written files.
- What the product must do: A copy appears under its final name only when complete, and any leftover partial or placeholder is cleaned up at next start and never synced.
- Kind: 3

### SYN-060 [sync / Files that must never sync]: Half-finished and temporary files spread to every editor and could not be deleted.
- What was going on: An interrupted 40 GB upload left a 39 GB part-file, and the downloader's 1.6 GB of partial files were synced everywhere and then kept by delete protection.
- What the product must do: Partial, temporary and work files of every tool are excluded by every upload and download path, the same set everywhere, and interrupted transfers' leftovers are cleaned up.
- Kind: 3

## Group 151

### PRX-054 [proxies-and-file-moves / Writing, copying and deleting files safely]: During a multi-gigabyte copy the editor had no way to stop or skip.
- What was going on: The only control while copying media into a project was "stop after this file", so one huge file trapped the editor.
- What the product must do: During a copy the editor can skip the current file, cancel the batch, or stop after this file, and an aborted file leaves nothing behind.
- Kind: 3

### RSV-134 [resolve-on-the-editors-computer / Fixing media: copying in, rehearsals and undo]: A long media copy shows its progress and can be skipped, never hangs.
- What was going on: Fix-all hung then closed; another copy sat at "35/69" with no clue which file; the owner wanted file name, per-file and overall bars, skip, and cancel all.
- What the product must do: A copy shows the current file name, per-file and overall progress, and offers skip this file and cancel all; only a person's click stops it.
- Kind: 2

## Group 152

### PRX-055 [proxies-and-file-moves / Writing, copying and deleting files safely]: Files set aside on an editor's computer were deleted before the promised time.
- What was going on: Moved-out copies promised recoverable for a year were pruned after 14 days, or sooner under disk pressure.
- What the product must do: Anything set aside instead of deleted is kept at least as long as people are told, and never removed while the NAS lacks it.
- Kind: 3

### SYN-039 [sync / Deletions and removing a project]: An editor's undo window is 14 days while the NAS keeps versions a year.
- What was going on: Deleted files stay recoverable on an editor's computer for 14 days or 50 GB, while the server keeps versions 365 days; the two were never chosen together.
- What the product must do: The owner sets both recovery windows together, and each is stated where a person goes looking for a lost file.
- Kind: 3
- State: still open

## Group 153

### PRX-062 [proxies-and-file-moves / Moving footage through the product]: "Could not move this project's folder" stayed after the problem went away.
- What was going on: A blocked folder rename was cleared only by a later successful move, so undoing the rename or re-ticking left the warning forever.
- What the product must do: The message clears when the mismatch no longer exists, and the project is never shown as fine while its sync is still paused.
- Kind: 3

### SYN-130 [sync / Project folders on an editor's computer]: A project kept saying it could not move its folder after that was fixed.
- What was going on: The message cleared only on a successful move, so once the folder was right by another route the project stayed paused.
- What the product must do: Once a project's folder is where it belongs, the "could not move" message clears and the project syncs again.
- Kind: 3

## Group 154

### PRX-070 [proxies-and-file-moves / Following a move on an editor's computer]: A crash in the middle of a file move turned it into a permanent failure.
- What was going on: A kill between moving and recording left no record, so the redelivered move looked done or failed for good, or the missing-clip fixer copied the file back.
- What the product must do: A move interrupted at any point, by crash, reboot or update, finishes on the next attempt, is never reported done early, and nothing recreates the old path.
- Kind: 3

### REL-050 [releases-and-updates / Installing an update on an editor's computer]: An update killed midway left nothing to start at sign-in.
- What was going on: For a moment during a self-update no program exists at the expected path, and a kill then leaves nothing to start.
- What the product must do: An update interrupted at any point leaves a program that starts at sign-in, recovered without a person renaming files.
- Kind: 3
- State: outcome not found

## Group 155

### PRX-071 [proxies-and-file-moves / Following a move on an editor's computer]: Following a move binned camera originals that were never uploaded.
- What was going on: A local folder the computer did not sync was moved whole to the trash, including originals the NAS did not yet hold.
- What the product must do: No move or tidy removes a local file until the server is seen holding the same content at the same path and size.
- Kind: 3

### SYN-036 [sync / Deletions and removing a project]: A laptop's record of holding the only copy of some originals expired.
- What was going on: The record that a laptop held camera originals not yet on the server aged out after 14 days, so the product forgot they still had to go up.
- What the product must do: A computer stays marked as holding unique originals until each of those files is confirmed on the server, however long that takes.
- Kind: 3
- State: outcome not found

## Group 156

### PRX-078 [proxies-and-file-moves / Relinking Resolve after a move]: A file in the trash was offered as the place to relink Resolve.
- What was going on: After a move put the local copy in the trash, "repoint Resolve to where it is now" left clips offline once the trash emptied.
- What the product must do: Resolve is never offered, or relinked to, a file in the trash.
- Kind: 3

### RSV-097 [resolve-on-the-editors-computer / Missing clips, relinking and refreshing]: The editor was offered a one-click relink into the product's own trash.
- What was going on: After a moved folder was set aside, its trash location was recorded as the move's destination and offered as where Resolve should look.
- What the product must do: Resolve is never relinked, or offered a relink, to a place the product may delete.
- Kind: 3

## Group 157

### PRX-089 [proxies-and-file-moves / Relinking and gathering missing clips]: Fixing a project would duplicate 100 GB that was already in the tree.
- What was going on: 107 interview clips pointed at an editor's former drive while the same files sat in the project tree, and the fix could only copy.
- What the product must do: When a missing clip's file exists in the tree with the same name and size, the person is offered a relink to it, never a copy.
- Kind: 3
- State: still open

### RSV-095 [resolve-on-the-editors-computer / Missing clips, relinking and refreshing]: An offline clip whose file already sat in the tree was copied again.
- What was going on: 107 interview clips pointed at a temporary drive while identical copies sat in the project tree; the fix only knew how to copy.
- What the product must do: When an offline clip's same-named, same-size file already exists in the project tree, the fix relinks to that copy instead of duplicating it.
- Kind: 3
- State: outcome not found

## Group 158

### PRX-090 [proxies-and-file-moves / Relinking and gathering missing clips]: When several copies of a missing clip exist, the largest is the right one.
- What was going on: The owner ruled "1.mov should be the largest": same-named duplicates were full-resolution files beside proxies, and backups were byte-identical across drives.
- What the product must do: Among same-named candidates the largest file, the original, beats a proxy, and identical backups do not count as a conflict.
- Kind: 2

### RSV-096 [resolve-on-the-editors-computer / Missing clips, relinking and refreshing]: Relinking 1,559 offline clips found several same-named candidates for many.
- What was going on: Moved media often has byte-identical backups on several drives, and full-resolution and proxy copies share names.
- What the product must do: Candidates are ranked by longest matching path tail, then the root most other clips resolved to, then larger file, and ambiguous picks are shown first.
- Kind: 3

## Group 159

### PRX-096 [proxies-and-file-moves / Relinking and gathering missing clips]: Music files in AAC were filed as b-roll instead of music.
- What was going on: Stray clips were sorted by extension and the audio list lacked .aac and .opus, so 30 licensed music tracks landed in a b-roll folder.
- What the product must do: .aac, .opus and every other common audio type are filed as audio when stray clips are copied into the tree.
- Kind: 3

### RSV-072 [resolve-on-the-editors-computer / Clip paths and media outside the shared tree]: Music in .aac files was filed as b-roll footage.
- What was going on: The list of audio file types lacked .aac and .opus, so licensed music gathered from outside the tree went to the b-roll folder instead of the music folder.
- What the product must do: .aac and .opus files are treated as audio and filed with music, like .wav and .mp3.
- Kind: 3

## Group 160

### REL-028 [releases-and-updates / Making and publishing a release]: An interrupted publish listed a release whose files were missing.
- What was going on: The list went up before the files, a killed publish left a listing with no file, and re-applying the running version erased the rollback target.
- What the product must do: A release becomes visible only once all its files download, an interrupted publish leaves the old or complete new release, and re-applying keeps the rollback target.
- Kind: 3

### SRV-049 [server-install-and-running / Updates, restarts and rollbacks]: Re-applying the server version already running erased the rollback target.
- What was going on: After a restart that did not happen or a fallback boot, re-applying the same version blanked the previous one, so rollback went to much older code.
- What the product must do: Re-applying a version keeps the existing rollback target unchanged.
- Kind: 3

## Group 161

### REL-066 [releases-and-updates / The server updating itself]: A server update that could not serve pages was never undone.
- What was going on: Only a crash on start counted, an update that never started was skipped uncounted, and a refusal for a missing setting counted as a failed boot.
- What the product must do: An update that started but does not pass its health check within ten minutes is reverted with its real reason shown; a refusal names its cause instead.
- Kind: 3
- State: fixed, never shipped

### SRV-045 [server-install-and-running / Updates, restarts and rollbacks]: A server update that crashed on boot was reverted, then reapplied for ever.
- What was going on: The failed update was reverted and re-applied ten seconds later, endlessly.
- What the product must do: A failed server update is reverted and never reapplied automatically.
- Kind: 3
- State: fixed, never shipped

## Group 162

### REL-067 [releases-and-updates / The server updating itself]: An automatic revert could roll back to code that cannot open the database.
- What was going on: The failed version had already upgraded the database, so the older code refused to start on every boot.
- What the product must do: A revert never picks code older than the database; it keeps the new code and says why, and when it cannot tell, it still reverts.
- Kind: 3

### SRV-050 [server-install-and-running / Updates, restarts and rollbacks]: A rollback ran old code against data a newer version had changed.
- What was going on: A manual rollback kept today's newer-layout data, and an automatic revert counted refused boots as failures and could pick a build older than the data.
- What the product must do: No rollback reaches a build that cannot open the current data unless the admin restores the named backup or accepts the risk; only real failed boots count.
- Kind: 3

## Group 163

### REL-068 [releases-and-updates / The server updating itself]: A server killed mid-update refused every later update and rollback.
- What was going on: Power loss or a kill during the restart left "update in progress" recorded, and only a shell could clear it.
- What the product must do: An "in progress" left by a dead process becomes "failed, interrupted" on start, and update and rollback work again from the page.
- Kind: 3

### SRV-048 [server-install-and-running / Updates, restarts and rollbacks]: A power cut during an update blocked every later update and rollback.
- What was going on: The "update in progress" mark survived the power loss and still looked current after restart, so every later update was refused until files on the NAS were edited.
- What the product must do: An update interrupted by power loss or a restart shows as failed at its step on the next start, and can be retried or rolled back from the dashboard.
- Kind: 3

## Group 164

### REL-069 [releases-and-updates / The server updating itself]: On a full data disk an applied update never started and status failed.
- What was going on: Reading the update status also wrote a correction, and on a full or read-only disk that failure stopped the restart.
- What the product must do: With a full or read-only data disk, update status still answers and an applied update still restarts into the new code.
- Kind: 3

### SRV-047 [server-install-and-running / Updates, restarts and rollbacks]: A full or read-only data disk left an update swapped in but never restarted.
- What was going on: The update's status notes could not be written to the failed disk, and that failure skipped the restart while the records named the new version.
- What the product must do: An update or rollback on a full or read-only disk either restarts into the new code or stops before swapping, and says plainly which.
- Kind: 3

## Group 165

### RSV-039 [resolve-on-the-editors-computer / Setting Resolve up: edition, scripting switch, preferences]: Resolve collaboration failed for editors connecting from outside the studio.
- What was going on: Collaborators connect peer to peer at the address the project database saw; remote editors arriving through address translation registered an address nobody could reach.
- What the product must do: Every collaborator's Resolve registers an address all other collaborators can reach, whether on the studio network or remote.
- Kind: 1a

### SRV-012 [server-install-and-running / Installing on a NAS]: Resolve collaborators were shown an internal server address and could not connect.
- What was going on: Resolve collaboration takes each editor's address as the project server sees it; behind address translation every editor registered the server's internal gateway.
- What the product must do: The shared project server sees each editor's real, mutually reachable address, on the LAN and the private network alike.
- Kind: 1a

## Group 166

### RSV-115 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve cannot decode VP9 originals at full resolution, though proxies edit fine.
- What was going on: Resolve Studio 21 on Windows logs "Failed to decode the video frame" for VP9 originals and the final render fails; YouTube MP4s are often VP9; AV1 and HEVC render fine.
- What the product must do: The editor is warned as soon as a timeline uses VP9 originals, naming each clip and the fix, and is warned again for any newly added one.
- Kind: 1a
- State: fixed, never shipped

### YTD-037 [youtube / Files Resolve can decode]: Resolve shows YouTube's VP9, AV1 and Opus downloads as Media Offline.
- What was going on: Resolve fails to decode the VP9 ("Failed to decode the video frame"), AV1 and Opus files YouTube commonly serves, though the files are sound; about 1,495 studio files were affected.
- What the product must do: No downloaded clip reaches any editor's Resolve in VP9, AV1 or Opus.
- Kind: 1a

### YTD-039 [youtube / Files Resolve can decode]: Resolve 21 stops a render on some VP9 and AV1 YouTube clips.
- What was going on: Resolve 21 stops a render with "Error decoding full resolution media" on VP9 and some AV1 clips that other tools decode without trouble.
- What the product must do: Before a render, a timeline's sources are checked for such codecs and the editor is told which clips will fail.
- Kind: 1a

## Group 167

### RSV-116 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Repairing undecodable clips before a deadline render takes seconds, not hours.
- What was going on: A 48-minute re-encode blocked a render; the owner: "just copy the proxy out into the main folder instead of re-encoding each one individually".
- What the product must do: A pre-render repair swaps in an edit-ready copy with the same frame count in seconds per clip, re-encoding only when no matching copy exists.
- Kind: 2

### YTD-042 [youtube / Files Resolve can decode]: An undecodable download is fixed by copying its proxy, if frames match.
- What was going on: The owner: "just copy the proxy out into the main folder instead of re-encoding each one individually"; a 48-minute re-encode was too slow before a deadline.
- What the product must do: An undecodable original is replaced by its proxy only when the frame counts match, keeping the original aside; otherwise it is re-encoded.
- Kind: 2

## Group 168

### RSV-130 [resolve-on-the-editors-computer / Colour look-up tables (LUTs)]: One shared LUT library that every editor's Resolve reads directly.
- What was going on: Each editor's LUTs lived only on their own computer; the owner asked for one shared LUT folder on the NAS, kept in sync, with Resolve pointed straight at it.
- What the product must do: Every editor receives the shared LUT folder without ticking anything, and Resolve on every computer lists the LUTs from it.
- Kind: 2

### SYN-012 [sync / What syncs where]: Studio-wide libraries must reach every computer, even one with nothing ticked.
- What was going on: The shared LUT, b-roll and music libraries had to reach everyone; deciding sharing from project ticks alone would have unshared them from every computer.
- What the product must do: Studio-wide library folders sync to every editor's computer automatically, with no project ticked, and never appear as projects.
- Kind: 3

## Group 169

### RSV-152 [resolve-on-the-editors-computer / Other givens on the editor's computer]: A refusal's reason was cut off before the part naming what to close.
- What was going on: The sentence naming the other program holding Resolve was cut at 255 characters on the way to the dashboard, so the admin saw advice but not the program.
- What the product must do: A refusal shown to an admin leads with the actionable part, and any length limit shortens it deliberately in the middle, never silently mid-word.
- Kind: 3

### ALL-049 [whole-product / Wording]: A long message reached the dashboard cut off mid-word.
- What was going on: Messages over 255 characters were cut at the limit, losing the name of the conflicting program at the end.
- What the product must do: Messages put the useful fact first and are shortened on purpose, never by a limit that lands mid-word.
- Kind: 3

## Group 170

### SRV-032 [server-install-and-running / Installing on a NAS]: Setting only the user half of the file-owner pair misfiled files days later.
- What was going on: A user id set without its group id was honoured by one part and ignored by another, so files landed under different owners and an editor's sync failed.
- What the product must do: The server's file-owner user and group are set together or not at all, and a half-set pair is warned about at start.
- Kind: 3

### SYN-017 [sync / What syncs where]: Renaming the projects folder in setup made every computer sync nothing.
- What was going on: The projects-folder name was honoured by server setup only, so a customer who changed it got a server tree under one name and computers looking for another.
- What the product must do: Every setting offered is honoured by every part of the product, or the product refuses to start with it set and says why.
- Kind: 3

## Group 171

### SRV-S18 [server-install-and-running / Sealed]: The assistant's command-line tool took 50 seconds to start on a busy NAS.
- What was going on: A cold version check took 50 s against a 10 s limit, and an expired sign-in left a credential file without a refresh token that still looked present.
- What the product must do: Allow at least 90 s for a cold start, keep the last good answer on a timeout, and treat a credential with no refresh token as signed out.
- Kind: 1b
- Tool: Claude Code CLI

### YTD-S11 [youtube / Sealed]: A dead assistant sign-in leaves its credential file with zero expiry.
- What was going on: When its session cannot refresh, the command-line assistant rewrites its credential file with expiry 0 and no refresh token, and the file still exists.
- What the product must do: "No refresh token and already expired" counts as signed out, reading only those two facts and never any secret value.
- Kind: 1b
- Tool: Claude Code CLI

## Group 172

### SYN-009 [sync / What syncs where]: YouTube originals go up from the computer that downloaded them, never down to others.
- What was going on: A remote editor's computer started pulling 58 GB of colleagues' YouTube originals; the owner: that is a "waste of bandwith".
- What the product must do: A YouTube original goes up to the NAS only; other computers get its proxy, and a requester gets their own clip by downloading it themselves.
- Kind: 2

### YTD-086 [youtube / Reaching the editor and Resolve]: Downloaded originals go up from the computer that fetched them, never down to others.
- What was going on: Other editors' YouTube originals cost one editor 58 GB on his first sync.
- What the product must do: Downloaded originals upload from the downloading computer but never sync down to other computers; their small proxies still come down.
- Kind: 2

## Group 173

### SYN-061 [sync / Files that must never sync]: A YouTube download that keeps getting cut short is retried at a lower quality.
- What was going on: Partial and fragment files from repeatedly truncated YouTube downloads sat in a synced project folder.
- What the product must do: A download truncated repeatedly retries one quality step lower rather than leaving partial files.
- Kind: 3
- Move to: youtube

### YTD-026 [youtube / How YouTube throttles and refuses]: One quality of a clip can arrive truncated every time while another works.
- What was going on: One clip's 1080p stream died at about 10 MB on every attempt from two different networks, while 720p downloaded fine.
- What the product must do: A truncated download retries once a quality lower and records it; a transient refusal never lowers quality, and a final failure removes its partial files.
- Kind: 1a

## Group 174

### SYN-107 [sync / Saying truthfully what the sync is doing]: "Ask your admin" appeared when the computer's own sync was not answering.
- What was going on: One message covered three cases: not yet offered by the server, the local sync not answering, and a deliberate stop holding it.
- What the product must do: Each cause gets its own sentence, a deliberate stop is not shown as a problem, and only a truly missing approval sends the editor to the admin.
- Kind: 3

### ALL-043 [whole-product / Wording]: The admin was told "ask your admin", and counts had the wrong scope.
- What was going on: A notice put a computer-wide 1,046 missing proxies under a project holding 438; one sentence covered three situations; only the first failing folder was named.
- What the product must do: Counts state their scope, each distinct problem gets its own true sentence, several show a count, and nobody is told to ask themselves.
- Kind: 3

