# The app on the editor's computer

## Installing and setting up

### APP-001: Typing an admin's password at the Windows prompt installed everything for that admin.
- What was going on: When a standard user runs an installer elevated with another account's password, Windows runs it as that account, so per-user files, autostart and settings land in its profile.
- What the product must do: Setup refuses, before changing anything, when the running account differs from the signed-in one (ignoring domain and case), and stays silent when the signed-in user is unknown.
- Kind: 1a
- From: L03-017

### APP-002: A program downloaded on a Mac silently never ran in the background.
- What was going on: macOS quarantines files a browser downloads (not command-line or in-app downloads); a quarantined program started in the background fails with no dialog and no log.
- What the product must do: Every program setup places on a Mac is cleared of quarantine before it runs, and a helper that fails to start is reported to the editor.
- Kind: 1a
- From: G01-017, L05-006

### APP-003: The Mac setup refused to run from Downloads, the Desktop or Applications.
- What was going on: On macOS 10.15 and later the user's folders sit on a separate data volume joined to the system volume, so /Users and /Applications look like mount points.
- What the product must do: On a Mac, setup refuses only network shares and removable disks, runs from the home folder or Applications, and words its refusals for the Mac.
- Kind: 1a
- From: L08-009, H05-014, L06-077

### APP-004: On stock Windows 11 the first install ended "not ready", missing a helper tool.
- What was going on: Windows' package manager changes the search path only for new processes, and installs into a version-numbered folder its next upgrade removes; setup also ignored the install's result.
- What the product must do: Setup installs exact, verified helper versions, checks each install's real result, finds them without a restart, and never records a version-numbered package-manager path.
- Kind: 1a
- State: fixed, never shipped
- From: H06-119, L11-043, H07-128

### APP-005: On a Mac without Resolve, setup said to launch Resolve once and quit it.
- What was going on: On macOS, missing Resolve preference files look the same whether Resolve was never launched or is not installed at all.
- What the product must do: Before asking an editor to launch Resolve, setup checks Resolve is installed, and if not says Resolve Studio must be installed first.
- Kind: 1a
- From: L05-004

### APP-006: Rewriting the Windows user search path flattened its variables for good.
- What was going on: Reading the user's search path expands entries like %USERPROFILE%; writing it back stores the literal text permanently.
- What the product must do: Install and uninstall change only their own search-path entries and keep every other entry in its unexpanded form.
- Kind: 1a
- State: outcome not found
- From: H04-062

### APP-007: Editor computers supported: Windows 10 22H2 or 11 on x64, and Apple silicon Macs.
- What was going on: The owner accepted this list, unmanaged machines only; company-managed machines (pushed installers, application allow-lists) are unsupported and the terms say so.
- What the product must do: Setup on an Intel Mac or an unsupported Windows stops, before changing anything, with a message naming what is supported.
- Kind: 2
- From: M02-089, H08-006

### APP-008: One installer does everything, and refuses without a valid account.
- What was going on: The owner wanted one installer that asks for account and password, clears old versions, sets up the drive, and ends showing what to send the admin.
- What the product must do: The installer refuses without valid credentials, asks the computer's role, removes earlier installs, sets up the drive, and ends showing what the admin needs.
- Kind: 2
- From: P02-050

### APP-009: Setup asks "I'm a remote editor" or "I'm physically connected to the server/NAS".
- What was going on: The owner rewrote the role question in plain words a non-technical editor can answer.
- What the product must do: The first-run role question offers exactly these two plain options and saves the answer for this computer only.
- Kind: 2
- From: P07-009

### APP-010: A Mac gets the same step-by-step setup as Windows, role question included.
- What was going on: The owner ruled the Mac setup "should ask the question of base/remote also", and the installer link on a Mac must serve the Mac setup.
- What the product must do: The Mac setup has every step the Windows one has, including the role choice, and a Mac's installer link downloads it.
- Kind: 2
- From: P03-046

### APP-011: There is one app on each editor's computer, not several.
- What was going on: The owner refused a separate b-roll helper beside the sync app: "I don't want to have to maintain multiple companions".
- What the product must do: Every editor-side feature (sync, Resolve help, sending b-roll or music to Resolve) lives in one app on the editor's computer.
- Kind: 2
- From: P04-024

### APP-012: After installing, the app was not running, and a fresh laptop came up broken.
- What was going on: Installs finished with no tray icon; on a never-installed laptop the installer died where no old drive mapping existed and no machine awaited approval.
- What the product must do: An install on a fresh or used computer ends with the app visibly running, syncing without hand edits, and the computer awaiting the admin's approval.
- Kind: 3
- From: P02-046, P02-051

### APP-013: Setup showed a green DONE on computers that could not work.
- What was going on: Setup finished with no way to report to the server, with the project drive letter taken by something else, or with an aborted step hidden by a minor warning.
- What the product must do: Setup says done only after the computer has reported in, its project drive answers and Resolve is reachable; otherwise it names the failed step.
- Kind: 3
- From: L04-070, H04-034, H07-078, H06-120

### APP-014: A failed or closed install left the computer with no app and no drive.
- What was going on: Install removed the old drive mapping and autostart first, then failed on a missing file or was closed part-way, and every retry failed the same way.
- What the product must do: Setup checks it can finish before removing anything, asks before closing mid-way, offers to finish an interrupted run, and says plainly if nothing will start at login.
- Kind: 3
- From: L03-015, H04-033, L08-014

### APP-015: Old copies of the app kept running beside the new one after an install.
- What was going on: Older login items and background copies were retired only when the new app installed, so a failed install, or a renamed app, left two copies or an old one holding its port.
- What the product must do: Every install run, failed or not, retires all earlier copies and login items of the app, leaving exactly one.
- Kind: 3
- From: L06-082, H05-093, L01-045

### APP-016: The installer run from the project drive would remap the drive it runs from.
- What was going on: The installer unmaps and remaps the project drive letter, which breaks if it was launched from that drive or a network share.
- What the product must do: The installer refuses to run from the project drive or a network share and says to copy it to the computer first.
- Kind: 3
- From: C01-110

### APP-017: Two setups run at once on one computer each wiped the other's work.
- What was going on: Nothing stopped a second setup starting while one ran, and each began from a clean slate.
- What the product must do: Only one setup runs at a time on a computer; a second one is refused with the reason.
- Kind: 3
- From: H07-145

### APP-018: A silent ten-minute install looked hung, and its log died with the window.
- What was going on: Install output appeared only at the end, and the log vanished when the window closed.
- What the product must do: Install progress shows live, the log is saved to a file, and the finish page offers to copy the log and names the file.
- Kind: 3
- From: L04-071

### APP-019: Installing onto a nearly full drive passed, and the disk filled days later.
- What was going on: Nothing checked free space, though one project's synced proxies are typically 50 to 300 GB.
- What the product must do: Below 200 GB free at the chosen sync location setup warns with the figure, never refuses, and stays silent when space cannot be measured.
- Kind: 3
- From: L03-016

### APP-020: A whole drive could be chosen as the editor's local project folder.
- What was going on: A bare drive root such as "D:\" passed the check, and setup then shared the entire volume.
- What the product must do: The editor's local project folder can never be a bare drive or volume root.
- Kind: 3
- State: outcome not found
- From: H04-063

### APP-021: A new editor could not download the installer before joining the private network.
- What was going on: The installer was served only behind the private network it existed to join, and setup asked for the address it had just come from.
- What the product must do: A new editor downloads the installer without being on the private network, and setup never asks for a value it already has.
- Kind: 3
- State: outcome not found
- From: H08-034

### APP-022: A dashboard address typed without a scheme, or on port 8443, never connected.
- What was going on: Editors type the bare name the admin gave them; setup rejected it silently, or guessed http or https from the port and saved the wrong guess.
- What the product must do: A typed scheme is always kept; without one, secure is tried first, a guess is never saved silently, and the check says "not reachable" or "not a dashboard".
- Kind: 3
- From: L08-011, H05-092, L04-072

### APP-023: Two server installs on one NAS were treated as one, crossing their settings.
- What was going on: Comparing host names only made two installs on different ports one server, so one's drive letter and folder name went to the other's setup.
- What the product must do: A server's identity includes any port given, and settings remembered for one install are never applied to another on the same host.
- Kind: 3
- From: L09-050

### APP-024: A computer set up for a second site kept talking to the first.
- What was going on: Setting a computer up for a new site kept the first site's credential, so it went on reporting to the wrong server.
- What the product must do: After setup for a new site, the computer holds only that site's credential and reports only to that site's server.
- Kind: 3
- State: outcome not found
- From: H08-035

### APP-025: Proxy making and b-roll drops waited for ever for a media converter.
- What was going on: The converter both features need was only installed when the optional YouTube feature was on, so other sites sat at "no converter found".
- What the product must do: Every tool a feature needs is installed whenever that feature is on, whatever other optional features are off.
- Kind: 3
- From: H03-016

### APP-026: Every setup turned off incoming file sharing on the editor's PC without saying so.
- What was going on: The local share made to give a laptop its project drive was reachable from other machines, and the fix blocked all inbound file sharing, unannounced.
- What the product must do: Any local share the product makes is closed to other computers, the PC's other file sharing keeps working, and no unrelated system setting changes unannounced.
- Kind: 3
- State: still open
- From: L01-048, H07-134

### APP-027: The installer took a drive letter a disk used, and another program's sync.
- What was going on: The installer read a drive letter held by a real disk as free, and adopted any running copy of the sync tool as its own.
- What the product must do: Setup never claims a drive letter a disk uses and never adopts a sync process it did not start.
- Kind: 3
- State: outcome not found
- From: H08-043

## Security warnings, permissions and certificates

### APP-028: Unsigned installers meet a Windows warning whose default is Don't run, and macOS blocks them.
- What was going on: Windows shows SmartScreen or Smart App Control; macOS needs Open Anyway in System Settings (right-click Open stops working from macOS 15), possibly again after each update.
- What the product must do: The download page walks through both, including re-allowing after an update and checking the checksum; each program names the vendor, never the customer, as publisher.
- Kind: 1a
- State: fixed, never shipped
- From: H08-007, L11-049, L05-008

### APP-029: A Mac app loses Full Disk Access after every update.
- What was going on: macOS ties privacy grants to the exact build of an app signed without a stable developer identity, so each update loses access to the sync drive.
- What the product must do: Mac builds carry a stable developer identity; the app checks Full Disk Access at every start and tells the editor exactly how to grant it.
- Kind: 1a
- State: outcome not found
- From: H01-040, L10-084, H08-019

### APP-030: One Windows computer failed every secure call with "certificate has expired".
- What was going on: Windows certificate stores can hold expired cached certificates (27 of 173 on one machine) that Windows ignores but other secure-connection code trusts and fails on.
- What the product must do: The app connects over https whenever Windows itself would; expired certificates in the Windows stores never break a connection.
- Kind: 1a
- From: M02-103, L10-069

### APP-031: After a Windows install the app could not read or save its own state.
- What was going on: Removing inherited permissions from a Windows folder without inheritable grants leaves the files already inside with no permissions: the licence re-asked, logging stopped, safety stops went unsaved.
- What the product must do: After any install or update every file in the app's state folder is readable and writable, the app repairs this at start, and an unsavable safety stop is reported.
- Kind: 1a
- State: fixed, never shipped
- From: H07-127, L11-042

## Drive letters and network drives

### APP-032: A mapped network drive does not exist for a remote or background session on Windows.
- What was going on: Windows drive mappings belong to one user's desktop session; services, elevated processes, remote shells and scheduled tasks do not see the editor's mapped letter.
- What the product must do: Anything run outside the editor's desktop session reaches the tree by its real network path, and never reports files missing because a letter is unmapped there.
- Kind: 1a
- From: M02-005, M05-033

### APP-033: A program started over a key-based remote shell on Windows could not read the NAS.
- What was going on: A key-based SSH logon on Windows carries no saved network credentials, so NAS shares cannot be read from it or from tasks registered through it.
- What the product must do: The NAS shares are reached with the product's own credentials or the signed-in session, and unreachable shares are named plainly.
- Kind: 1a
- From: M04-099

### APP-034: A drive letter mapped by the installer as administrator was invisible to the editor.
- What was going on: On Windows a drive mapped under an elevated administrator token is not visible in the same user's normal session.
- What the product must do: Drive letters an editor uses are mapped in the editor's own normal session, so Explorer and Resolve both see them.
- Kind: 1a
- From: C01-010

### APP-035: Windows can hide a mapped drive that is really there.
- What was going on: An elevated process cannot see the user's mappings, a disconnected persistent mapping (NAS asleep) tests as absent, and unmap exit codes are unreliable.
- What the product must do: "Drive not found" from an elevated or early check means "cannot tell"; checks read the user's own mapping table, count disconnected mappings as present, and confirm every unmap.
- Kind: 1a
- From: H04-032, L02-040

### APP-036: Mapping the server drive failed with "canceled by the user".
- What was going on: A Windows drive mapping that needs credentials tries to prompt on a console; a program without one fails with system error 1223.
- What the product must do: A program without a console asks for network credentials in its own window and never relies on a console prompt.
- Kind: 1a
- From: C01-037

### APP-037: Windows 11 cannot give a display name to a substituted drive letter.
- What was going on: A drive letter made by substituting a folder always shows the host disk's label on Windows 11; a mapped network drive can be given its own per-user label.
- What the product must do: The editor's project drive shows its own chosen name in Explorer on Windows 11, checked on a real machine after install.
- Kind: 1a
- From: P02-026, C01-009

### APP-038: On a Mac with the NAS unmounted, downloads would fill the boot disk.
- What was going on: On macOS a share's path under /Volumes is just a folder on the boot disk when the share is not mounted.
- What the product must do: Nothing is written under a mount path unless the share is confirmed mounted immediately before writing.
- Kind: 1a
- From: L01-069

### APP-039: The shared drive letter is a studio setting, not built in.
- What was going on: The owner plans to sell the product and wants each studio to set its drive letter once, carried to every editor install.
- What the product must do: A studio sets its project drive letter once, and every new editor install uses it with no change to the program.
- Kind: 2
- From: P02-029

### APP-040: The editor's project drive is named after the studio.
- What was going on: The owner wanted it named after the studio "to make it obvious to the editors that it's not their other drive and only to put project stuff in there".
- What the product must do: The project drive on every editor's computer is labelled with the studio's name, taken from the studio's own settings.
- Kind: 2
- From: P02-027

### APP-041: The app removed a drive mapping it did not create, breaking every Resolve path.
- What was going on: Install, update, uninstall and a grading feature removed the NAS mapping on the project letter, reading "cannot tell" as "ours", or acting on an unverified default role.
- What the product must do: A drive mapping is removed or replaced only when provably the product's own; when unsure, or the chosen and verified roles disagree, it is left and the editor asked.
- Kind: 3
- From: L02-039, L01-044, C01-016, H07-049, H04-031

### APP-042: One failed fetch during setup set a studio's drive letter to the default.
- What was going on: With the server briefly unreachable, setup steps fell back to different sources (the built-in default, a cache of any age, another dashboard's cache) and disagreed.
- What the product must do: One setup run uses one letter and tree name: the site's, else its saved copy from the same dashboard under 30 days old, else it stops and says so.
- Kind: 3
- From: L06-078, H05-089, L04-008, L08-010

### APP-043: Changing the studio's drive letter after install silently split the fleet.
- What was going on: The drive letter could be edited centrally but was fixed at install on each computer, so a change reached nobody already installed.
- What the product must do: A change of drive letter or tree name after computers are installed is either refused or carried to every computer, never silently ignored.
- Kind: 3
- State: still open
- From: H04-038, L01-046

### APP-044: The NAS password was visible on the drive-mapping command line.
- What was going on: Mapping the drive passed the NAS password as a command argument, visible to other processes, and a credential prompt could hang the mapping.
- What the product must do: No password ever appears on a command line, and drive mapping gives up within 30 seconds.
- Kind: 3
- From: L03-062

## Starting, staying running and crashing

### APP-045: A program started at sign-in or login runs once, and nothing restarts it.
- What was going on: Windows "run at sign-in" and a macOS login item each start a program once and never again, so an app that dies stays dead until the next login.
- What the product must do: Every long-running part on an editor's computer has something that restarts it, and nothing the app needs dies with an upgrade.
- Kind: 1a
- From: L01-002

### APP-046: A program started over a remote shell on Windows died with the session.
- What was going on: It lands outside the desktop with no tray icon and is killed when the shell closes, logged like a clean stop; a scheduled task gets a stripped environment.
- What the product must do: Long-lived processes start fully detached, finding every helper without inherited environment, and after a remote install the app is started in the person's own desktop session.
- Kind: 1a
- From: G01-033, M02-006

### APP-047: Mac background-launch rules can run the app twice or kill it during its own update.
- What was going on: launchd's KeepAlive restarts an app that exits on purpose; without AbandonProcessGroup it kills the relaunched child; only a parent process sees an exit status.
- What the product must do: On a Mac the app restarts after a crash or Force Quit, never after Quit or self-update, never runs twice, and survives its own update.
- Kind: 1a
- From: G01-020

### APP-048: After a self-restart on Windows, the computer was left with no app running.
- What was going on: Windows reports a process as exited at the start of termination, while it still holds its handles, including the single-copy lock, for a second or more.
- What the product must do: A replacing copy waits for the old process to be fully gone, plus up to 15 seconds, before deciding another copy holds the lock.
- Kind: 1a
- From: L04-010, M01-057, G01-034

### APP-049: After a reboot, a reused process number made the app think it was already running.
- What was going on: Process numbers are reused after a restart, and a loose match on number and command line refused to start the real app.
- What the product must do: Checking for another running copy of the app never relies on a process number alone.
- Kind: 1a
- From: H07-082

### APP-050: Ordinary Windows shutdowns were counted as crashes of the app.
- What was going on: Windows sends an end-session notice at shutdown and may end the program at any moment afterwards; 4 of 9 reported crashes were plain shutdowns.
- What the product must do: On the end-session notice (Windows or macOS) a clean exit is recorded at once; a cancelled shutdown records nothing, and a real power loss still counts as a crash.
- Kind: 1a
- From: C04-019, P12-014, L10-035

### APP-051: A computer's clock stepping backwards erased crash and relaunch history.
- What was going on: Time synchronisation, a virtual machine resuming or dual booting can move the clock backwards; records with "future" times were discarded, forgiving recent crashes and shortening waits.
- What the product must do: Crash, restart and rate-limit counts and waits survive the clock stepping backwards or forwards and never reset because of it.
- Kind: 1a
- From: H05-023

### APP-052: On Windows, two clock readings a moment apart are often identical.
- What was going on: Windows' clock ticks every 15.6 ms, so identifiers taken from the time collided (6 distinct of 10), muting new warnings and double-counting relaunches.
- What the product must do: Nothing uses a clock reading as a unique identifier; two events in the same instant stay distinct.
- Kind: 1a
- From: H05-022

### APP-053: A program started at Mac login cannot find tools that work in Terminal.
- What was going on: Programs launched by macOS's login service get a search path of /usr/bin:/bin:/usr/sbin:/sbin only, without Homebrew or per-user tool folders.
- What the product must do: Everything the app runs on a Mac is referenced by a full path recorded at install.
- Kind: 1a
- From: C01-111, G01-019

### APP-054: A Windows laptop on battery silently stopped a scheduled background task.
- What was going on: Windows scheduled tasks by default do not start on battery and stop when the laptop is unplugged, leaving no error.
- What the product must do: Anything the app schedules keeps running on battery, and a stopped background job shows on the computer and the dashboard.
- Kind: 1a
- From: M05-082

### APP-055: A Mac app froze at start with its sync folder on an exFAT drive.
- What was going on: Starting a file-change watch on an exFAT external drive on macOS can block in the kernel indefinitely, freezing whatever waits on it.
- What the product must do: A stuck file-change watch never freezes the app; the tray, Resolve checks and sync keep running.
- Kind: 1a
- State: still open
- From: C01-057

### APP-056: The app vanished silently and stayed dead for hours: it must restart itself.
- What was going on: Native aborts left nothing in the log; the app stayed down 47 minutes to 3 hours on Windows, 85 minutes on a Mac. Owner: "it should be able to auto start after a crash".
- What the product must do: On Windows and macOS an unasked death is recorded, shown on next start, and relaunched within about 10 seconds, at most three times an hour, never after Quit, logout, update or uninstall.
- Kind: 2
- From: M03-061, P09-016, C03-016, P12-051, L10-066, H04-074, L03-085, L02-001, G01-035, L01-091, C04-018, M02-008, P08-009

### APP-057: A Start menu entry reopens the app; no stray copy runs beside it.
- What was going on: An editor whose app had vanished restarted a months-old copy from a downloaded zip, which ran beside the real app and wrote into its log.
- What the product must do: Every install leaves a Start menu entry, named after the product, that starts the installed app, and every build refuses to run beside another copy.
- Kind: 2
- From: P05-032, L03-067

### APP-058: The tray shows the running version, and confirms a finished update.
- What was going on: Nobody could tell which version a machine ran; the owner asked for the version at the top of the tray and a message when an update completes.
- What the product must do: The tray shows the running version at the top, and the first start after an update says it is now running the new version.
- Kind: 2
- From: P02-048

### APP-059: The relaunch limit stopped at two an hour, or never held at all.
- What was going on: Each relaunch was counted twice, so "three an hour" stopped at two; with the state folder unwritable (full disk, antivirus lock) every crash looked like the first.
- What the product must do: A crashed app is relaunched exactly the advertised number of times per hour, even when it cannot save its records, and failed saves are reported to the dashboard.
- Kind: 3
- From: L07-001, L05-091, L07-002

### APP-060: Fourteen "crashes" on one computer were all deliberate stops.
- What was going on: Upgrades, test runs and manual restarts each filed a crash report, and a manual upgrade killed an instance that had just upgraded itself.
- What the product must do: A deliberate stop (upgrade, quit, an operator's kill) is never counted as a crash, and two upgrade routes on one computer never kill each other's result.
- Kind: 3
- State: still open
- From: L04-033

### APP-061: A dead background part of the app was reported as running.
- What was going on: Watchdogs asked "was it started", not "is it alive"; the loop driving sync stopped with no restart, and back-off spacing meant the hourly restart limit never applied.
- What the product must do: Every background part is judged alive by doing its work, restarted with growing waits, stops after six restarts an hour asking for a person, and each restart is reported.
- Kind: 3
- From: H05-046, H07-006, L06-093

### APP-062: Opening a second progress window crashed the whole app.
- What was going on: Running one long job after another, each with its own window, force-closed the app with no message.
- What the product must do: Any number of windows can open and close, together or in a row, in any order, without the app ending.
- Kind: 3
- From: P06-021, C02-050

### APP-063: A wrongly typed setting made the app vanish at startup without a word.
- What was going on: A setting hand-edited to a number instead of a folder path crashed the app before its tray icon appeared, leaving only a log line.
- What the product must do: A malformed setting never stops the app starting; it starts, shows its icon and names the setting that is wrong.
- Kind: 3
- From: H01-045

### APP-064: Quit, cancel or an update left a transfer or encoder running after the app.
- What was going on: The app exited before its tear-down finished; transfers outlived it and raced the new build, and an orphaned local model held 4 to 12 GB of video memory.
- What the product must do: Quit, cancel, restart and update stop every helper the app started (waiting up to 40 seconds), and at start any leftover helper is stopped first.
- Kind: 3
- State: fixed, never shipped
- From: H07-007, H04-058, L11-035, H07-129

### APP-065: A restart, update or Quit cut off a multi-hour copy halfway.
- What was going on: Automatic restarts did not wait for a running copy-and-relink job, Quit stopped everything at once, and macOS quit events skipped the clean shutdown.
- What the product must do: No automatic restart or update starts during a copy, relink or sharing job; Quit names what is in flight and asks, proceeding if that cannot be checked.
- Kind: 3
- State: outcome not found
- From: H01-002, H08-022, L04-050

### APP-066: The quit-while-copying question read as broken English.
- What was going on: With a file number but no batch total, the question read "copying file 3 files in".
- What the product must do: Every wording of a question is a correct sentence; with no known total it says a file is being copied, with no half count.
- Kind: 3
- From: L07-004

### APP-067: After an update the app was gone until someone restarted it by hand.
- What was going on: The new version started while the old one still held the run-once lock and quit, and "update complete" was reported without checking the new app stayed up.
- What the product must do: After an update exactly one copy runs; success is reported only if the new app is still running seconds later, and otherwise the old one keeps running.
- Kind: 3
- From: P05-031, H02-024
- Move to: releases-and-updates

### APP-068: A new build that died on start was never rolled back.
- What was going on: Deaths before the app finished starting were not counted as failed starts, so sync stopped until someone restored the old build by hand on each machine.
- What the product must do: After two failed starts of a new build, the app restores the previous build by itself and syncing resumes with no one touching the machine.
- Kind: 3
- State: fixed, never shipped
- From: L11-032
- Move to: releases-and-updates

### APP-069: An update interrupted mid-swap left the computer with no app at all.
- What was going on: A power cut, reboot or antivirus quarantine between moving the old program aside and placing the new one left nothing to start.
- What the product must do: An interrupted self-update restores a runnable app without a person, and recovery never overwrites an app that is present.
- Kind: 3
- From: L07-006
- Move to: releases-and-updates

## The tray or menu-bar icon and its menu

### APP-070: At Windows sign-in the tray icon failed to appear and every notice was lost.
- What was going on: At login Windows' notification area is often not ready within 3 s and can take up to 105 s; adding the icon failed, and the app dropped every later notice, safety warnings included.
- What the product must do: Placing the icon retries for minutes; notices raised meanwhile (at least the five newest) show once it is up; if it never appears, editor and admin are told.
- Kind: 1a
- From: L08-079, H05-039, L05-076

### APP-071: After Windows Explorer restarted, the tray icon vanished or came back frozen.
- What was going on: An Explorer restart (shell crash, graphics driver reset, update) drops every tray icon and broadcasts once; a failed re-add left no icon, menu or Quit, or a frozen icon.
- What the product must do: The icon returns and keeps updating after any Explorer restart, retrying until it works, without the menu going unresponsive for more than about 2.5 seconds meanwhile.
- Kind: 1a
- From: H06-066, L08-077, L06-098, L06-099

### APP-072: With an auto-hiding Windows taskbar, the tray menu opened behind the taskbar.
- What was going on: Windows leaves an auto-hide taskbar out of the screen area menus are kept inside, so a menu opened at the cursor is covered by the raised bar.
- What the product must do: The tray menu opens fully clear of the taskbar, docked or auto-hidden, on whichever screen edge.
- Kind: 1a
- From: P04-026, C01-065

### APP-073: A very long menu line stretched the right-click menu across the whole screen.
- What was going on: Windows and macOS menus never wrap or shorten an item, so a 440-character line makes the menu that wide.
- What the product must do: Tray menu lines stay short, about 80 characters at most, with full explanations in a window.
- Kind: 1a
- State: still open
- From: L11-048

### APP-074: Tray hover text cut to 127 characters still failed on Windows.
- What was going on: Windows limits tray hover text to 128 units and counts emoji and rare Chinese characters as two units each.
- What the product must do: Tray hover text always fits Windows' 128-unit limit, measured the way Windows counts, including emoji and rare Chinese characters.
- Kind: 1a
- State: still open
- From: P14-021

### APP-075: A tray menu rebuilt while open vanished under the editor's mouse.
- What was going on: Rebuilding an open menu destroys it under the cursor, so lines carrying live percentages make it unusable; on macOS rebuilding an open menu-bar menu is also unsafe.
- What the product must do: An open tray or menu-bar menu is never rebuilt for a changing figure; changes to what it lists wait until it closes.
- Kind: 1a
- From: H07-061, L04-099

### APP-076: On macOS, changing the menu-bar icon or a window from another thread risks a crash.
- What was going on: macOS menu-bar items, menus and windows may only be changed from the main thread; elsewhere it can crash without a trace or block for ever.
- What the product must do: On macOS every menu-bar, menu and window change, animation included, is handed to the main thread without the caller waiting.
- Kind: 1a
- From: H03-009, L01-041

### APP-077: On a MacBook with a notch, the app's menu-bar icon never appeared.
- What was going on: With a full menu bar, macOS places a new status icon behind the camera notch and draws nothing, while reporting it created.
- What the product must do: The app detects when its menu-bar icon cannot be seen and tells the editor another way, within seconds of starting, how to reach it.
- Kind: 1a
- From: C01-053, P04-004

### APP-078: The tray icon is the bare studio mark; colour and pulse show the state.
- What was going on: The owner chose no tile or border, and darker tints, because neon colours washed out on Windows' light grey taskbar.
- What the product must do: Amber pulsing while transferring, red pulsing on error, steady amber when paused, signed out or drive missing, steady green only when fully caught up; legible on light and dark taskbars.
- Kind: 2
- From: M01-004, P04-027, C01-068

### APP-079: The tray menu had grown to forty lines; the owner set a short one.
- What was going on: He approved: identity, one conditional prompt, "Sync:" with files and speed, "Resolve: connected", sync now, pause, "Open my sync drive", open dashboard, settings, quit.
- What the product must do: The right-click menu holds only those everyday items, about ten; this computer's role and every other control live in a settings window the menu opens.
- Kind: 2
- From: C03-004, L03-030, P07-016

### APP-080: A wired computer that syncs nothing must show green unless something is wrong.
- What was going on: The owner's computer works straight off the NAS with sync off by design, yet showed amber and "sync engine not running" as a blocking problem for two days.
- What the product must do: A computer configured to sync nothing shows the healthy colour and never reports the missing sync as a problem; owner: "green unless there is an error".
- Kind: 2
- From: P07-007, C03-046, P09-015

### APP-081: The tray's "Open dashboard" opened an address browsers could not use.
- What was going on: The owner wanted the link to work for remote editors too; after the dashboard went https-only for browsers, the tray still opened the plain address the app reports to.
- What the product must do: "Open dashboard" opens the address the site publishes for people, reachable from wherever the computer is, falling back to the reporting address only when none is published.
- Kind: 2
- From: C03-056, P09-014, P02-053

### APP-082: Right-clicking the tray icon opened the menu seconds late, or not at all.
- What was going on: Long background work, including Resolve scripting calls of 33 to 91 s, kept the tray from answering clicks, and rebuilds racing a click left a dead menu.
- What the product must do: A right-click opens the tray menu within half a second, and highlighting follows the mouse instantly, every time, whatever Resolve or the sync is doing.
- Kind: 3
- State: still open
- From: P04-025, P07-006, C01-024, P02-039, P03-018

### APP-083: The tray lagged up to seven seconds per refresh while the dashboard was down.
- What was going on: Each two-second refresh made a fresh five-second attempt to reach the unreachable dashboard.
- What the product must do: With the dashboard unreachable the tray is as responsive as online, and the dashboard is retried on a schedule, not on every refresh.
- Kind: 3
- From: H01-044

### APP-084: Tray actions that did nothing said nothing.
- What was going on: "Sync now" checked one of six reasons sync refuses and said "Sync requested" on a halted computer; "Open my sync drive" silently did nothing with no drive set.
- What the product must do: Every tray action answers, accepted or "not now" with the same reason that stops sync; Quit says what stops and until when, with Restart beside it.
- Kind: 3
- From: H05-031, L05-072, L04-102

### APP-085: "Open dashboard" did nothing when clicked.
- What was going on: On a remote editor's computer the open-dashboard action silently failed to open a browser.
- What the product must do: If opening the dashboard fails, the person is told and shown the address to open by hand.
- Kind: 3
- State: outcome not found
- From: P05-065

### APP-086: An editor's app was not showing up on his Mac.
- What was going on: The owner reported the app missing for a Mac editor; the cause was not recorded.
- What the product must do: While the app runs on a Mac its menu-bar presence is visible, and the dashboard shows whether that computer is reporting.
- Kind: 3
- State: outcome not found
- From: P11-044

## Windows, dialogs and notifications

### APP-087: A blank black window appeared at install, and closing it killed the app.
- What was going on: A Windows program built as a console program, or a helper started without the no-window option, gets a console window, and closing it ends the program.
- What the product must do: Nothing the app or its helpers start on Windows ever shows a console window, whether started by the installer, at login or after an update.
- Kind: 1a
- From: C01-003, C02-013

### APP-088: Windows showed the program file's icon on the taskbar and an internal id on notifications.
- What was going on: Windows fixes a taskbar button's application identity when the first window appears; one declared later is ignored for the process's life.
- What the product must do: Every process that shows windows declares the product's identity, name and mark before its first window, so taskbar and notifications show the product.
- Kind: 1a
- From: C02-025, M02-085, P06-030, L01-051, G01-031

### APP-089: Windows cut long notifications off at the end, where the action was.
- What was going on: Windows tray notification text is cut at about 250 characters, and the action an editor needs usually sits at the end.
- What the product must do: Notification text too long for Windows is shortened in the middle, keeping its opening and its closing action.
- Kind: 1a
- From: L04-038

### APP-090: On macOS a quit confirmation froze every other window of the app.
- What was going on: On macOS tray menu actions and window work share one main thread, so a question left on screen stalled progress windows and dialogs for up to 120 seconds.
- What the product must do: A confirmation left open never freezes the app's other windows, and if it times out, Quit still quits.
- Kind: 1a
- From: L05-092, H05-041

### APP-091: A folder picker left open on a Mac blocked every other window and update.
- What was going on: macOS gives an app no way to close an open picker panel after a timeout, so it stayed up and held the app's one-window-at-a-time slot.
- What the product must do: A picker left open never silently blocks fixes, settings or updates; the app says what is waiting on it.
- Kind: 1a
- State: still open
- From: H07-060

### APP-092: Windows "show in folder" opened Documents for a path with spaces.
- What was going on: Explorer's select switch must arrive as one unquoted "/select,<path>" token with only the path quoted; quoting the whole argument silently opens Documents.
- What the product must do: "Show in folder" opens the containing folder with the file selected, for paths with spaces and Chinese characters.
- Kind: 1a
- From: L03-053, M03-018

### APP-093: Every long job opens a progress window: "the lack of feedback is disturbing".
- What was going on: B-roll indexing, music indexing and proxy making showed only tray lines; the owner asked for windows that also close themselves when done.
- What the product must do: Each long job shows download, per-item and overall progress and time left; closing its window never stops the job, and it closes itself within seconds of finishing.
- Kind: 2
- From: P06-019, C02-012

### APP-094: Any download the app starts announces itself.
- What was going on: Model downloads started silently; the owner asked for "x model is downloading. Right click ... to see progress."
- What the product must do: Starting any download raises a notification naming it and where to see progress, and another when it is ready.
- Kind: 2
- From: P06-020

### APP-095: The desktop app is one dark window with no white title bar, like Resolve.
- What was going on: Owner: "make the windows header bar for the exe fit with the overall style, like it's one whole window, somewhat like resolve, without the white bar at the top".
- What the product must do: The desktop app's title bar is drawn in the product's own look, with no plain system bar above it.
- Kind: 2
- State: fixed, never shipped
- From: P15-024

### APP-096: A window that could not close blocked every later window, and shutdown.
- What was going on: A failed dialog, a retried batch or a progress window ending itself the wrong way kept the one-window slot, so later dialogs and "Update now" were refused and the app ignored shutdown.
- What the product must do: Every dialog can always be closed, a second batch in one dialog finishes normally, later windows still open, and quitting always works.
- Kind: 3
- From: H01-006, C01-052

### APP-097: One unanswered dialog silenced every other project's prompts and held back updates all day.
- What was going on: A missing-media dialog left open nine hours hid prompts for other projects, matched by file path alone, and pushed updates refused to install while it stayed open.
- What the product must do: Prompts for different projects are never merged or suppressed by an open dialog, and an update waiting on an open dialog shows that on the dashboard.
- Kind: 3
- State: outcome not found
- From: M02-025

### APP-098: A settings window that failed while opening stayed on screen, frozen.
- What was going on: A display change (a remote desktop session switching) during construction left an unresponsive, uncloseable window, and each new click added another.
- What the product must do: A window that fails while opening is closed and the failure reported; the next click opens one working window.
- Kind: 3
- From: H05-042, L05-093

### APP-099: The settings window flashed every button white every two seconds.
- What was going on: The window was torn down and rebuilt on each two-second refresh, so the scroll jumped and clicks landed on vanishing controls.
- What the product must do: A periodically refreshed window redraws only what changed, keeps its scroll position, and never flickers or drops a click.
- Kind: 3
- From: P09-018, C03-058, M03-064

### APP-100: Pressing Enter on a focused Cancel button ran the window's main action.
- What was going on: The app's buttons took no keyboard focus, so Enter always triggered the window's default.
- What the product must do: Every button can be reached by keyboard and shows focus, and Enter acts on the focused button.
- Kind: 3
- From: H07-062

### APP-101: One long clean-up repeated "files moved to trash" on every pass.
- What was going on: A clean-up of about 30 GB, spread over many passes by a safety cap, raised the same notification each pass.
- What the product must do: The same notification repeats at most once every 30 minutes, and the first one is never suppressed.
- Kind: 3
- From: C01-031

### APP-102: The pulled-drive reminder kept nagging when only downloads were waiting.
- What was going on: Downloads can safely wait for the drive; only work owed up to the server is at risk while it is away.
- What the product must do: A pulled sync drive gives one warning; half-hourly reminders continue only while uploads the server does not yet have are owed.
- Kind: 3
- From: L10-049, C04-011

### APP-103: A Mac editor was shown a folder path with Windows backslashes.
- What was going on: A message joined a Mac path with a backslash, so the one line saying where the editor's stills went failed in Finder's Go to Folder.
- What the product must do: A path shown to an editor uses their own system's separators, so it can be pasted into Finder or Explorer.
- Kind: 3
- From: L08-086

### APP-104: Clips found while a dialog was open were lost behind an "already open" notice.
- What was going on: The owner ruled: "get rid of the popup already open message ... the editor can decide"; clips found meanwhile were silently dropped.
- What the product must do: Clips found while a dialog is open are shown, without duplicates, as soon as it closes, and no "already open" notice appears.
- Kind: 2
- From: P03-019
- Move to: resolve-on-the-editors-computer

### APP-105: A clip from the b-roll archive must not set off the editor's popup.
- What was going on: The archive lives outside any project folder, and the owner warned such a clip should not "flip the trigger for a popup" asking where to file it.
- What the product must do: A timeline clip whose file is in the shared b-roll archive is treated as correctly placed and never prompts the editor.
- Kind: 2
- From: P03-038
- Move to: resolve-on-the-editors-computer

### APP-106: Installing on a Mac sets Resolve's path mapping automatically.
- What was going on: The owner asked that a Mac install "auto set resolve path mapping", so projects made on Windows find their media.
- What the product must do: After install on a Mac, Resolve maps the shared drive's Windows paths to the Mac's mount without the editor doing it by hand.
- Kind: 2
- From: P03-045
- Move to: resolve-on-the-editors-computer

## Telling the editor what is wrong

### APP-107: The browser said the app was not running when it was.
- What was going on: Chrome's local network permission can stop an http web page reaching an app on the same computer, which looks identical to the app being closed.
- What the product must do: When a page cannot reach the local app it says it could not reach it and offers a self-test, never asserting the app is not running.
- Kind: 1a
- From: P05-033

### APP-108: The status icon stayed green while nothing had synced for days.
- What was going on: An unaccepted licence, a safety stop, a rejected sign-in or a replugged drive with sign-in missing left the icon green or showed a stale reason, shown only in settings.
- What the product must do: Whenever anything blocks syncing the icon leaves green, and the at-a-glance status names the one current blocker, changing when it changes.
- Kind: 3
- From: H07-010, L04-049, H01-046

### APP-109: A dozen equally loud red warnings hid the one that mattered.
- What was going on: Every status line was drawn as a warning in source order, so a blocking problem sat at the bottom beside harmless information.
- What the product must do: Status lines are ranked blocking, warning, information; duplicates collapse with a count; six show and the rest sit behind "show all".
- Kind: 3
- From: L04-104

### APP-110: Tray status lines hid the real cause behind jargon.
- What was going on: The tray showed "Something went wrong" for hours, "tidying old files in slices" and "paused at the 600s project budget", none of which an editor could understand.
- What the product must do: Every status names its actual cause in plain words, and a deliberate safety pause reads as progress with when it resumes, not as an error.
- Kind: 3
- From: P02-033

### APP-111: The tray said "downloading" for ever with nothing to download from.
- What was going on: With no connection to the server, the downloader still reported syncing, so the icon pulsed amber and counted files that could not arrive.
- What the product must do: "Downloading" shows only while files are actually arriving; with no connection the tray says it is waiting for the server.
- Kind: 3
- From: H06-108

### APP-112: Problems the app found on a computer reached nobody.
- What was going on: Background crashes, a shared library not working, a folder moved after a rename and failing tool installs went only to a log or crash file while the tray stayed green.
- What the product must do: Every problem the app detects shows in its tray and settings window and is counted in its report, even with nothing ticked or the feature off, until cleared.
- Kind: 3
- From: L02-018, L05-077

### APP-113: Crash reports overwrote each other and were kept where nobody read them.
- What was going on: A new crash file truncated an older one, reports could hold secrets, and no crash ever left the computer.
- What the product must do: Every crash report is kept without overwriting another, has secrets removed, and is counted on the dashboard.
- Kind: 3
- From: H07-063

### APP-114: A tray glitch the app recovers from filled the crash reports.
- What was going on: Each temporary tray failure wrote a crash report and advised a restart; with only the newest 20 kept, they pushed out the real crashes.
- What the product must do: A failure the app recovers from by itself writes no crash report and never advises a restart.
- Kind: 3
- From: L08-078

### APP-115: A safety warning told the editor to restart, which silently clears the safety stop.
- What was going on: A restart drops the sync safety stops the warning was protecting, yet the sentence offered a restart as the remedy.
- What the product must do: A warning about a safety stop never suggests a restart; it names an action the editor can take, such as sending diagnostics to the admin.
- Kind: 3
- From: L07-003

### APP-116: An editor was sent to an admin, or to re-run setup, for a one-click fix.
- What was going on: A licence refusal said to re-run setup and an identity warning said to send the log to an admin, though the app itself held the fix.
- What the product must do: A message about a problem always points at the smallest action that clears it, and says where in the app that action lives.
- Kind: 3
- From: L04-106, L08-084

### APP-117: Help and diagnostics sat below two screens of warnings.
- What was going on: On a computer with problems, the help button that eight warnings point at sat below a status section taller than the window.
- What the product must do: When anything is wrong, help and diagnostics are reachable without scrolling, with a fixed jump bar to each section.
- Kind: 3
- From: L04-155

### APP-118: Error messages sent editors to menu items that no longer existed.
- What was going on: About twenty sentences named tray menu rows removed when the menu was redesigned, and fixing them by hand repeated the drift.
- What the product must do: Every sentence that says where to click names a control that exists, and an automatic check fails when one does not.
- Kind: 3
- From: L03-083, L04-036

### APP-119: Ages and deadlines shown to editors were wrong.
- What was going on: A sync plan live a minute read "10 days ago", and the trash deadline ignored the site's retention setting.
- What the product must do: Every age, deadline and retention figure shown to an editor reflects the true value and this site's settings.
- Kind: 3
- From: H05-102

### APP-120: A rehearsal read "Copying ... 0 B of 800 GB" for its whole run.
- What was going on: A dry run of a large copy reused the real copy's progress wording, so it looked stuck at zero.
- What the product must do: A rehearsal says it is a rehearsal and shows what it checked, never copy progress.
- Kind: 3
- From: H06-098

### APP-121: A repeating warning rotated away the log history support needed.
- What was going on: A port held by another program logged six lines every two minutes, and a per-clip "missing" line filled the 5 MB log every 25 minutes.
- What the product must do: A recurring condition is logged loudly once when it starts, then as a count per pass until it changes, so the log keeps days of history.
- Kind: 3
- From: H05-038, L03-071

### APP-122: A computer's own plan was visible only as a stack of remove buttons.
- What was going on: The only list of projects ticked for the computer was its remove buttons, and "upload only" appeared only inside a delete button's label.
- What the product must do: The app lists each project ticked for this computer with its mode and transfer state in words; an empty plan says to tick projects on the dashboard.
- Kind: 3
- From: L04-103

## Signing in, the computer's identity and the licence

### APP-123: An editor app's sign-in must never expire on its own.
- What was going on: Sign-in lapsed after 30 days; sync and reporting stopped silently on unattended machines (an editor lost two days, a render machine a weekend), with one night-time balloon.
- What the product must do: A healthy computer never loses its sign-in by time alone; if it is ever refused, the editor and dashboard are told and the editor reminded hourly.
- Kind: 2
- From: P08-001, H04-011

### APP-124: A refused sign-in showed "HTTP 403" instead of what to do.
- What was going on: The app read the wrong part of the server's refusal, so "ask an admin to add you to the editors group" and "server busy, retry" never reached the editor.
- What the product must do: When sign-in is refused, the editor sees the server's own plain reason and what to do next, for every kind of refusal.
- Kind: 3
- From: H04-059

### APP-125: The server stopped accepting a computer's reports and nobody found out.
- What was going on: A revoked credential or wrong address left sync running and the tray green while the computer vanished from the dashboard; the only button offered was sign out.
- What the product must do: A rejected credential tells the editor once, reads differently from "server unreachable" everywhere, offers signing in again first, and when a report was last accepted survives restarts.
- Kind: 3
- From: L02-017, L04-100

### APP-126: A failed re-sign-in replaced a computer's working sign-in with an unusable one.
- What was going on: An unusable answer to a new sign-in attempt was saved over the good stored one, signing the computer out.
- What the product must do: A failed or unusable sign-in attempt never replaces a computer's working sign-in.
- Kind: 3
- From: H07-044

### APP-127: Pause then resume started syncing on a computer nobody had signed in to.
- What was going on: Start and sign-in refused to sync while signed out, but resuming from pause did not check, even after a sign-in had lapsed.
- What the product must do: No path, resume from pause included, starts syncing on a computer that is not signed in when sign-in is required.
- Kind: 3
- From: H04-055

### APP-128: An unreadable identity file turned a computer into a new one.
- What was going on: A truncated, locked or quarantined identity file was read as "no identity yet", so a new one was written over it and the server saw another computer.
- What the product must do: A computer's identity is created only when none exists; one that cannot be read is reported to the editor and admin and never silently replaced.
- Kind: 3
- From: L05-073, H05-037, L06-096

### APP-129: An unreadable computer identity had a warning and no way out.
- What was going on: The app rightly refused to mint a new identity silently, but offered the editor nothing to do.
- What the product must do: One confirmed button says it gives this computer a new identity (never "repair"), sets the old file aside, and never claims success when nothing changed.
- Kind: 3
- From: L07-007

### APP-130: An update parked sync behind a licence prompt nobody saw, for 18 hours, twice.
- What was going on: Only first-time setup could record acceptance, the prompt lost to a popup opening every start, closing it counted as declining, and the dashboard showed the computer idle.
- What the product must do: A prompt that stops sync appears in the app within a minute, returns until answered, treats closing as unanswered, resumes sync on accept, and the dashboard names the reason.
- Kind: 3
- From: L01-019, P06-041, M01-075, M02-024, C02-020, P06-031

### APP-131: Wired to the NAS or remote belongs to the computer, never the person.
- What was going on: Setup set a computer's role from whether its person was an admin, so the owner's laptop counted as wired and an admin's remote laptop was dismantled.
- What the product must do: The wired-or-remote choice made in setup becomes that computer's own setting, and nothing derived from the person's account ever changes it.
- Kind: 2
- From: H07-080, H06-090, L10-053, L03-029

### APP-132: The owner switched his server-side computer to remote by one click and feared deletions.
- What was going on: Remote mode may remove local files during download, so flipping the NAS-side machine endangered the live share; the reverse click silently stopped all syncing.
- What the product must do: Switching a computer between wired and remote asks first, names the consequence plainly, and the direction that can delete needs the word REMOTE typed.
- Kind: 3
- From: P08-004

## Settings, records and background work

### APP-133: An update must never reset a computer's own settings.
- What was going on: An editor's Resolve is installed off the C: drive, and the owner required that updating the app never resets that setting.
- What the product must do: After any update, every setting chosen on that computer, including where Resolve is installed, is unchanged.
- Kind: 2
- State: outcome not found
- From: P05-020

### APP-134: A save cut off by a crash or full disk reset the app's settings.
- What was going on: Settings, decisions and safety-stop records were rewritten in place, so a power cut or overlapping writer left a broken file read as "never asked", "not halted" or defaults.
- What the product must do: Every record is replaced whole or left untouched, whatever the timing; an unreadable one gives the cautious answer or the last good copy, with a visible warning.
- Kind: 3
- From: L08-081, L01-038, L02-012, H06-065

### APP-135: Half-written temporary files from killed processes piled up for ever.
- What was going on: A process killed between writing a temporary file and renaming it leaves it behind, and the cleanup only matched finished file names.
- What the product must do: Every cleanup that ages out the app's records also removes temporary files left by a killed write, on the same retention.
- Kind: 3
- From: L06-004

### APP-136: Files the product keeps on an editor's computer grew without limit.
- What was going on: On-demand b-roll and music clips were never evicted (about 150 GB a year), save-point exports grew 10 to 50 GB a year, and each install left 130 MB.
- What the product must do: Every file the product stores on an editor's computer has a size or age limit and is removed when it passes it.
- Kind: 3
- State: still open
- From: H08-077

### APP-137: Reports from editors' computers grew with the size of the media pool.
- What was going on: A list of refused relinks had no cap, so 200 or more clips went into every 30-second report.
- What the product must do: Every list a computer reports is capped, keeping the newest, with a count of what was left out.
- Kind: 3
- From: H05-036

### APP-138: A feature switched on for the site never reached apps already running.
- What was going on: Site settings were read once at start, so a switch flipped later, or an app that started offline, waited for a restart.
- What the product must do: Site settings changes reach every running app within minutes, with no restart, and an app that started offline picks them up when it reconnects.
- Kind: 3
- From: H06-099, H03-017

### APP-139: A studio's own logo vanished from every computer on update.
- What was going on: The logo was set per computer, so an update that changed the default stripped it, and restoring it meant touching every editor.
- What the product must do: A studio's logo is set once centrally, reaches every computer, and survives updates.
- Kind: 3
- From: C02-023

### APP-140: Setting the local helper's port to 0 silently killed Send to Resolve.
- What was going on: Port 0 means "any free port", so the helper came up where no web page could find it while the app reported it fine.
- What the product must do: An invalid helper port is refused with a warning and the standard port used; switching the helper off is a separate, explicit setting.
- Kind: 3
- From: H05-052

### APP-141: Any web page could drive the editor's local helper.
- What was going on: Pages could post actions to the helper on the editor's computer, and status requests from any page each spawned a slow background process, unbounded.
- What the product must do: Only the studio's own pages can trigger actions on an editor's computer, untrusted text never runs as script there, and repeated status checks spawn bounded work.
- Kind: 3
- State: still open
- From: H04-017

### APP-142: An admin's request for diagnostics was dropped or refused for good.
- What was going on: The request was marked answered before the upload, so a failure was never retried, and a stuck "in progress" mark refused every later request silently.
- What the product must do: An admin's request is marked done only once it succeeds and is retried until then; every "in progress" mark expires after a generous limit.
- Kind: 3
- State: outcome not found
- From: H06-100, H07-081

### APP-143: Retries ran every few seconds for ever, overflowed after weeks, or waited a whole day.
- What was going on: A doubling wait overflowed after 21 days, some loops never slowed, every computer polled a down dashboard every 30 s, and a failed tool install waited a day.
- What the product must do: Every automatic retry grows its wait to a 30-minute cap, has an hourly ceiling, never queues duplicates, recovers promptly when the other end answers, and survives months of uptime.
- Kind: 3
- From: H05-016, L05-074, H07-077, H05-099

### APP-144: A Mac laptop on battery with its lid closed sleeps despite keep-awake.
- What was going on: A remote editor's Mac on battery with the lid shut slept overnight though the app asked to stay awake, and the interrupted upload started again from zero.
- What the product must do: When an upload is owed, the editor is warned that closing the lid on battery stops it, and the dashboard shows this as the reason.
- Kind: 1a
- State: outcome not found
- From: P12-048

### APP-145: A lost NAS connection kept a PC awake and blocked every shutdown.
- What was going on: "Still syncing" counted files still needed, not data moving, so with the NAS off overnight the PC never slept and shutdowns were interrupted.
- What the product must do: Keep-awake and shutdown warnings apply only while data is moving or recently moved, with a maximum hold time.
- Kind: 3
- From: H04-054

### APP-146: Helper jobs either hung for ever or were killed mid-encode by a fixed limit.
- What was going on: Some helper processes had no upper bound, while every long encode was cut off at 15 minutes regardless of size.
- What the product must do: A helper job is stopped when it makes no progress for a set time, and a slow job that keeps progressing is never killed by a fixed clock.
- Kind: 3
- From: H07-004

### APP-147: Background encoding at normal priority slowed Resolve's own render.
- What was going on: Three normal-priority encoders took the processor; dropping them to below normal raised Resolve's output from about 100 to 144 MB/s.
- What the product must do: The product's encoding on an editor's computer runs below normal priority so Resolve keeps its speed.
- Kind: 3
- From: M05-046
- Move to: proxies-and-file-moves

## Uninstalling

### APP-148: On Windows one locked file can make a folder delete remove nothing at all.
- What was going on: With Windows' built-in shell a recursive delete removes nothing when one file is locked, and a just-stopped program, antivirus scan or the uninstaller itself can still hold locks.
- What the product must do: The uninstaller re-reads what is really gone after every delete, and removes the installed-apps entry only once the files are gone.
- Kind: 1a
- From: L08-012, H05-090, L06-079

### APP-149: Uninstalls reported removals they had not checked.
- What was going on: A held log file kept the sign-in file alive, a Mac script printed "complete" over root-owned leftovers, dry runs claimed deletions, and leftovers advice said to delete the uninstaller too.
- What the product must do: Uninstall says complete only when verified, names every leftover with its path and how to retry, never suggests removing the retry path, and a dry run changes nothing.
- Kind: 3
- From: L09-039, L10-017, L08-013, H06-067

### APP-150: The Mac uninstaller always destroyed the computer's sync identity; Windows always kept it.
- What was going on: The platforms disagreed, so a Mac reinstall needed fresh approval while Windows promised none was needed, and the closing text contradicted itself.
- What the product must do: Uninstall treats the sync identity the same on every platform and states once, truthfully, whether re-approval will be needed.
- Kind: 3
- From: H06-068

### APP-151: Uninstalling left the computer able to reach the studio's server.
- What was going on: Uninstalling the app left its server credentials on the computer.
- What the product must do: After uninstall, no credential that lets the computer reach the studio's server remains on it.
- Kind: 3
- State: outcome not found
- From: H08-036

### APP-152: The app appeared in no uninstall list, or with a blank icon.
- What was going on: The uninstaller came only with one install package, and the installed-apps entry was written before the program existed, so its icon was skipped.
- What the product must do: On Windows the app is listed in installed apps with its icon and a working uninstall from the first install; on a Mac the uninstaller sits beside the app.
- Kind: 3
- From: L05-007, H05-091, L06-080

### APP-153: Uninstalling removed the firewall rule while the share it guarded was still published.
- What was going on: The uninstaller dropped the block rule when the drive unmapped, even when removing the share had failed or could not be checked.
- What the product must do: A protection is removed only after the thing it protects is confirmed gone; an unreadable state counts as still there.
- Kind: 3
- From: H04-085, L04-009

## Sealed

### APP-S01: The app vanished with no error, no log line and no trace, seven times.
- What was going on: The window toolkit aborts the process when a window interpreter is freed on any thread but its creator, which garbage collection of a reference cycle on another thread does.
- What the product must do: Every window interpreter is created, used and freed on one thread, proven by a test in a child process whose exit code is the assertion.
- Kind: 1b
- Tool: Tcl/Tk through Python's tkinter (Tcl_AsyncDelete abort)
- From: C03-015, L01-092, L02-002, G01-036, M02-009, P08-008, M03-062, P09-017

### APP-S02: On a Mac, freeing the window toolkit's first interpreter crashed the process later.
- What was going on: macOS's menu system keeps calling into the first toolkit interpreter a process created; once it is freed, the process segfaults at random.
- What the product must do: On macOS the first window toolkit interpreter lives for the whole process.
- Kind: 1b
- Tool: Tk (tkinter) on macOS
- From: C04-025, L10-073

### APP-S03: On a Mac, installer and app windows froze, never updated, or hung for ever.
- What was going on: The toolkit silently drops updates scheduled from other threads, a window built off the main thread blocks with no error, and an early app-policy call aborts startup.
- What the product must do: On macOS every window is created and updated from the main thread, and no window request can hang the app.
- Kind: 1b
- Tool: Tk on macOS (Aqua Tk 9 alongside PyObjC)
- From: C03-017, C01-050

### APP-S04: The Mac sign-in form said both fields were empty after filling them.
- What was going on: With a hidden main window, a text variable created without an owner binds to that window, and nested event loops stopped dialogs returning.
- What the product must do: Every dialog reads exactly what was typed and returns when closed, so it can be opened again in the same session.
- Kind: 1b
- Tool: tkinter StringVar and nested mainloop
- From: C01-051

### APP-S05: A secure server address on port 8443 was turned into plain http.
- What was going on: The private-network service used to publish the dashboard serves secure connections on 8443 and on every port of its own names.
- What the product must do: Without a typed scheme, that service's names and port 8443 are tried as secure.
- Kind: 1b
- Tool: Tailscale Serve and Funnel
- From: L06-081

### APP-S06: Multi-line safety notifications never appeared on a Mac.
- What was going on: The Mac notification was built as a script string, which cannot hold a newline, so every multi-line notice silently failed; the Windows balloon also cut long text.
- What the product must do: Notification text is collapsed to one line before the Mac call, and every notification is tested on each system at its real length and characters.
- Kind: 1b
- Tool: AppleScript "display notification" (macOS) and the Windows tray balloon
- From: H07-147, L04-037

### APP-S07: On Windows a timed-out wait on a helper process could still hang for ever.
- What was going on: After a timeout killed the child, collecting its output could block indefinitely on Windows, so the timeout bounded nothing.
- What the product must do: Every wait on a helper process has a true upper bound on Windows, including after the helper has been killed.
- Kind: 1b
- Tool: Python subprocess.run with timeout on Windows
- From: H07-005

### APP-S08: After a self-update the app lost its codecs and dialogs, then crashed.
- What was going on: A one-file packaged app started by another copy of itself reuses the parent's unpacked folder, which the exiting parent deletes moments later.
- What the product must do: An app restarted by its own update runs as a fully independent instance and starts cleanly every time.
- Kind: 1b
- Tool: PyInstaller one-file mode (version 6 and later); Python's lazily imported idna codec
- From: C01-004

### APP-S09: A handed-over new build was judged dead because the wrong process was watched.
- What was going on: The spawned process of a one-file packaged app is an unpacker that starts the real app as a child, often taking over two seconds.
- What the product must do: When handing over to a new build, either the spawned process or its child counts as the new app, waiting up to thirty seconds.
- Kind: 1b
- Tool: PyInstaller one-file executables
- State: fixed, never shipped
- From: L11-034

### APP-S10: Every secure download from the packaged Mac app failed certificate checks.
- What was going on: The packaged Mac app carried no list of trusted certificate authorities, so every https download failed with "unable to get local issuer certificate".
- What the product must do: The Mac app verifies secure downloads against a trust store it can always find, proven on a real Mac build.
- Kind: 1b
- Tool: Python frozen with PyInstaller on macOS
- State: outcome not found
- From: L08-048, M02-104

### APP-S11: The app trusted expired Windows store certificates that Windows itself ignores.
- What was going on: The default secure context loads every certificate from the Windows stores, expired or not, and a connection object made before a fix keeps the old trust.
- What the product must do: Expired store certificates are filtered out before any secure connection object is created.
- Kind: 1b
- Tool: Python ssl loading the Windows certificate stores
- State: fixed, never shipped
- From: L10-070, C04-023, P12-056

### APP-S12: Code writing to standard output crashed inside the packaged windowed app.
- What was going on: In the packaged windowed build standard output does not exist, so imported code that wrapped it failed at import.
- What the product must do: Code loaded inside the packaged app never assumes a console exists.
- Kind: 1b
- Tool: PyInstaller windowed builds
- From: M03-063

### APP-S13: A single-file self-extracting app writes hundreds of megabytes per start.
- What was going on: Each start unpacked 108 to 232 MB to the temp folder, each forced kill left two 108 MB folders, and security software reads the pattern as malware.
- What the product must do: Starting the app writes no large temporary files, leaves nothing behind after a forced kill, and is not flagged by common security software.
- Kind: 1b
- Tool: PyInstaller one-file packaging
- State: outcome not found
- From: H08-039

### APP-S14: A model download crawled at 2 MB/s and looked broken.
- What was going on: One long connection to the model host's delivery network stalled near 2 MB/s while fresh parallel connections reached 37 to 45 MB/s.
- What the product must do: A multi-gigabyte download recovers from a stalled connection by itself, resumes after interruption, and shows its rate and time left.
- Kind: 1b
- Tool: Hugging Face CDN downloads
- From: C02-047

### APP-S15: The desktop app's own window ran the editor at 20 fps; the browser ran 144.
- What was going on: The same page ran 144 fps in Chrome but about 20 in the app shell's window, each frame stalling about 49 ms on hand-off to Windows; driver settings did not cure it.
- What the product must do: The desktop app shows the editor at the same frame rate as the plain browser on the same computer.
- Kind: 1b
- Tool: Electron
- From: P15-022

### APP-S16: Re-running the Mac installer erased the whole remote-access configuration.
- What was going on: macOS's built-in text-processing tool rejects a multi-line variable, produced empty output, and the script wrote that over the config, destroying unrelated entries.
- What the product must do: An installer re-run replaces a config only when the new one is complete and keeps every other section; otherwise it leaves it untouched.
- Kind: 1b
- Tool: awk on macOS (BWK awk)
- From: C01-055

## Removed
