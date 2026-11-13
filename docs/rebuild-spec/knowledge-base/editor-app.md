# The app on each editor's computer: what real use taught

142 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Installing and setting up

### APP-001: Typing an admin's password at the Windows prompt installed everything for that admin.
- Why: When a standard user runs an installer elevated with another account's password, Windows runs it as that account, so per-user files, autostart and settings land in its profile.
- Must: Setup refuses, before changing anything, when the running account differs from the signed-in one (ignoring domain and case), and stays silent when the signed-in user is unknown.
- Kind: given

### APP-002: A program downloaded on a Mac silently never ran in the background.
- Why: macOS quarantines files a browser downloads (not command-line or in-app downloads); a quarantined program started in the background fails with no dialog and no log.
- Must: Every program setup places on a Mac is cleared of quarantine before it runs, and a helper that fails to start is reported to the editor.
- Kind: given

### APP-003: The Mac setup refused to run from Downloads, the Desktop or Applications.
- Why: On macOS 10.15 and later the user's folders sit on a separate data volume joined to the system volume, so /Users and /Applications look like mount points.
- Must: On a Mac, setup refuses only network shares and removable disks, runs from the home folder or Applications, and words its refusals for the Mac.
- Kind: given

### APP-004: On stock Windows 11 the first install ended "not ready", missing a helper tool.
- Why: Windows' package manager changes the search path only for new processes, and installs into a version-numbered folder its next upgrade removes; setup also ignored the install's result.
- Must: Setup installs exact, verified helper versions, checks each install's real result, finds them without a restart, and never records a version-numbered package-manager path.
- Kind: given

### APP-005: On a Mac without Resolve, setup said to launch Resolve once and quit it.
- Why: On macOS, missing Resolve preference files look the same whether Resolve was never launched or is not installed at all.
- Must: Before asking an editor to launch Resolve, setup checks Resolve is installed, and if not says Resolve Studio must be installed first.
- Kind: given

### APP-006: Rewriting the Windows user search path flattened its variables for good.
- Why: Reading the user's search path expands entries like %USERPROFILE%; writing it back stores the literal text permanently.
- Must: Install and uninstall change only their own search-path entries and keep every other entry in its unexpanded form.
- Kind: given

### APP-007: Editor computers supported: Windows 10 22H2 or 11 on x64, and Apple silicon Macs.
- Why: The owner accepted this list, unmanaged machines only; company-managed machines (pushed installers, application allow-lists) are unsupported and the terms say so.
- Must: Setup on an Intel Mac or an unsupported Windows stops, before changing anything, with a message naming what is supported.
- Kind: ruling

### APP-008: One installer does everything, and refuses without a valid account.
- Why: The owner wanted one installer that asks for account and password, clears old versions, sets up the drive, and ends showing what to send the admin.
- Must: The installer refuses without valid credentials, asks the computer's role, removes earlier installs, sets up the drive, and ends showing what the admin needs.
- Kind: ruling

### APP-009: Setup asks "I'm a remote editor" or "I'm physically connected to the server/NAS".
- Why: The owner rewrote the role question in plain words a non-technical editor can answer.
- Must: The first-run role question offers exactly these two plain options and saves the answer for this computer only.
- Kind: ruling

### APP-010: A Mac gets the same step-by-step setup as Windows, role question included.
- Why: The owner ruled the Mac setup "should ask the question of base/remote also", and the installer link on a Mac must serve the Mac setup.
- Must: The Mac setup has every step the Windows one has, including the role choice, and a Mac's installer link downloads it.
- Kind: ruling

### APP-011: There is one app on each editor's computer, not several.
- Why: The owner refused a separate b-roll helper beside the sync app: "I don't want to have to maintain multiple [apps on the editor's computer]".
- Must: Every editor-side feature (sync, Resolve help, sending b-roll or music to Resolve) lives in one app on the editor's computer.
- Kind: ruling

### APP-012: After installing, the app was not running, and a fresh laptop came up broken.
- Why: Installs finished with no tray icon; on a never-installed laptop the installer died where no old drive mapping existed and no machine awaited approval.
- Must: An install on a fresh or used computer ends with the app visibly running, syncing without hand edits, and the computer awaiting the admin's approval.
- Kind: situation

### APP-013: Setup showed a green DONE on computers that could not work.
- Why: Setup finished with no way to report to the server, with the project drive letter taken by something else, or with an aborted step hidden by a minor warning.
- Must: Setup says done only after the computer has reported in, its project drive answers and Resolve is reachable; otherwise it names the failed step.
- Kind: situation

### APP-014: A failed or closed install left the computer with no app and no drive.
- Why: Install removed the old drive mapping and autostart first, then failed on a missing file or was closed part-way, and every retry failed the same way.
- Must: Setup checks it can finish before removing anything, asks before closing mid-way, offers to finish an interrupted run, and says plainly if nothing will start at login.
- Kind: situation

### APP-015: Old copies of the app kept running beside the new one after an install.
- Why: Older login items and background copies were retired only when the new app installed, so a failed install, or a renamed app, left two copies or an old one holding its port.
- Must: Every install run, failed or not, retires all earlier copies and login items of the app, leaving exactly one.
- Kind: situation

### APP-016: The installer run from the project drive would remap the drive it runs from.
- Why: The installer unmaps and remaps the project drive letter, which breaks if it was launched from that drive or a network share.
- Must: The installer refuses to run from the project drive or a network share and says to copy it to the computer first.
- Kind: situation

### APP-017: Two setups run at once on one computer each wiped the other's work.
- Why: Nothing stopped a second setup starting while one ran, and each began from a clean slate.
- Must: Only one setup runs at a time on a computer; a second one is refused with the reason.
- Kind: situation

### APP-018: A silent ten-minute install looked hung, and its log died with the window.
- Why: Install output appeared only at the end, and the log vanished when the window closed.
- Must: Install progress shows live, the log is saved to a file, and the finish page offers to copy the log and names the file.
- Kind: situation

### APP-019: Installing onto a nearly full drive passed, and the disk filled days later.
- Why: Nothing checked free space, though one project's synced proxies are typically 50 to 300 GB.
- Must: Below 200 GB free at the chosen sync location setup warns with the figure, never refuses, and stays silent when space cannot be measured.
- Kind: situation

### APP-020: A whole drive could be chosen as the editor's local project folder.
- Why: A bare drive root such as "D:\" passed the check, and setup then shared the entire volume.
- Must: The editor's local project folder can never be a bare drive or volume root.
- Kind: situation

### APP-021: A new editor could not download the installer before joining the private network.
- Why: The installer was served only behind the private network it existed to join, and setup asked for the address it had just come from.
- Must: A new editor downloads the installer without being on the private network, and setup never asks for a value it already has.
- Kind: situation

### APP-022: A dashboard address typed without a scheme, or on an unusual port, never connected.
- Why: Editors type the bare name the admin gave them; setup rejected it silently, or guessed http or https from the port and saved the wrong guess.
- Must: A typed scheme is always kept; without one, secure is tried first, a guess is never saved silently, and the check says "not reachable" or "not a dashboard".
- Kind: situation

### APP-023: Two server installs on one NAS were treated as one, crossing their settings.
- Why: Comparing host names only made two installs on different ports one server, so one's drive letter and folder name went to the other's setup.
- Must: A server's identity includes any port given, and settings remembered for one install are never applied to another on the same host.
- Kind: situation

### APP-024: A computer set up for a second site kept talking to the first.
- Why: Setting a computer up for a new site kept the first site's credential, so it went on reporting to the wrong server.
- Must: After setup for a new site, the computer holds only that site's credential and reports only to that site's server.
- Kind: situation

### APP-025: Proxy making and b-roll drops waited for ever for a media converter.
- Why: The converter both features need was only installed when the optional YouTube feature was on, so other sites sat at "no converter found".
- Must: Every tool a feature needs is installed whenever that feature is on, whatever other optional features are off.
- Kind: situation

### APP-026: Every setup turned off incoming file sharing on the editor's PC without saying so.
- Why: The local share made to give a laptop its project drive was reachable from other machines, and the fix blocked all inbound file sharing, unannounced.
- Must: Any local share the product makes is closed to other computers, the PC's other file sharing keeps working, and no unrelated system setting changes unannounced.
- Kind: situation

### APP-027: The installer took a drive letter a disk used, and another program's sync.
- Why: The installer read a drive letter held by a real disk as free, and adopted any running copy of the sync tool as its own.
- Must: Setup never claims a drive letter a disk uses and never adopts a sync process it did not start.
- Kind: situation

## Security warnings, permissions and certificates

### APP-028: Unsigned installers meet a Windows warning whose default is Don't run, and macOS blocks them.
- Why: Windows shows SmartScreen or Smart App Control; macOS needs Open Anyway in System Settings (right-click Open stops working from macOS 15), possibly again after each update.
- Must: The download page walks through both, including re-allowing after an update and checking the checksum; each program names the vendor, never the customer, as publisher.
- Kind: given

### APP-029: A Mac app loses Full Disk Access after every update.
- Why: macOS ties privacy grants to the exact build of an app signed without a stable developer identity, so each update loses access to the sync drive.
- Must: Mac builds carry a stable developer identity; the app checks Full Disk Access at every start and tells the editor exactly how to grant it.
- Kind: given

### APP-030: One Windows computer failed every secure call with "certificate has expired".
- Why: Windows certificate stores can hold expired cached certificates (27 of 173 on one machine) that Windows ignores but other secure-connection code trusts and fails on.
- Must: The app connects over https whenever Windows itself would; expired certificates in the Windows stores never break a connection.
- Kind: given

### APP-031: After a Windows install the app could not read or save its own state.
- Why: Removing inherited permissions from a Windows folder without inheritable grants leaves the files already inside with no permissions: the licence re-asked, logging stopped, safety stops went unsaved.
- Must: After any install or update every file in the app's state folder is readable and writable, the app repairs this at start, and an unsavable safety stop is reported.
- Kind: given

## Drive letters and network drives

### APP-032: A mapped network drive does not exist for a remote or background session on Windows.
- Why: Windows drive mappings belong to one user's desktop session; services, elevated processes, remote shells and scheduled tasks do not see the editor's mapped letter.
- Must: Anything run outside the editor's desktop session reaches the tree by its real network path, and never reports files missing because a letter is unmapped there.
- Kind: given

### APP-033: A program started over a key-based remote shell on Windows could not read the NAS.
- Why: A key-based SSH logon on Windows carries no saved network credentials, so NAS shares cannot be read from it or from tasks registered through it.
- Must: The NAS shares are reached with the product's own credentials or the signed-in session, and unreachable shares are named plainly.
- Kind: given

### APP-034: A drive letter mapped by the installer as administrator was invisible to the editor.
- Why: On Windows a drive mapped under an elevated administrator token is not visible in the same user's normal session.
- Must: Drive letters an editor uses are mapped in the editor's own normal session, so Explorer and Resolve both see them.
- Kind: given

### APP-035: Windows can hide a mapped drive that is really there.
- Why: An elevated process cannot see the user's mappings, a disconnected persistent mapping (NAS asleep) tests as absent, and unmap exit codes are unreliable.
- Must: "Drive not found" from an elevated or early check means "cannot tell"; checks read the user's own mapping table, count disconnected mappings as present, and confirm every unmap.
- Kind: given

### APP-036: Mapping the server drive failed with "canceled by the user".
- Why: A Windows drive mapping that needs credentials tries to prompt on a console; a program without one fails with system error 1223.
- Must: A program without a console asks for network credentials in its own window and never relies on a console prompt.
- Kind: given

### APP-037: Windows 11 cannot give a display name to a substituted drive letter.
- Why: A drive letter made by substituting a folder always shows the host disk's label on Windows 11; a mapped network drive can be given its own per-user label.
- Must: The editor's project drive shows its own chosen name in Explorer on Windows 11, checked on a real machine after install.
- Kind: given

### APP-038: On a Mac with the NAS unmounted, downloads would fill the boot disk.
- Why: On macOS a share's path under /Volumes is just a folder on the boot disk when the share is not mounted.
- Must: Nothing is written under a mount path unless the share is confirmed mounted immediately before writing.
- Kind: given

### APP-040: The editor's project drive is named after the studio.
- Why: The owner wanted it named after the studio "to make it obvious to the editors that it's not their other drive and only to put project stuff in there".
- Must: The project drive on every editor's computer is labelled with the studio's name, taken from the studio's own settings.
- Kind: ruling

### APP-041: The app removed a drive mapping it did not create, breaking every Resolve path.
- Why: Install, update, uninstall and a grading feature removed the NAS mapping on the project letter, reading "cannot tell" as "ours", or acting on an unverified default role.
- Must: A drive mapping is removed or replaced only when provably the product's own; when unsure, or the chosen and verified roles disagree, it is left and the editor asked.
- Kind: situation

### APP-042: One failed fetch during setup set a studio's drive letter to the default.
- Why: With the server briefly unreachable, setup steps fell back to different sources (the built-in default, a cache of any age, another dashboard's cache) and disagreed.
- Must: One setup run uses one letter and tree name: the site's, else its saved copy from the same dashboard under 30 days old, else it stops and says so.
- Kind: situation

### APP-043: Changing the studio's drive letter after install silently split the fleet.
- Why: The drive letter could be edited centrally but was fixed at install on each computer, so a change reached nobody already installed.
- Must: A change of drive letter or tree name after computers are installed is either refused or carried to every computer, never silently ignored.
- Kind: situation

### APP-044: The NAS password was visible on the drive-mapping command line.
- Why: Mapping the drive passed the NAS password as a command argument, visible to other processes, and a credential prompt could hang the mapping.
- Must: No password ever appears on a command line, and drive mapping gives up within 30 seconds.
- Kind: situation

See also, filed under another capability:

- SRV-018 (The server: installing it and keeping it running): The owner: the drive letter editors see the tree on is set on the server.

## Starting, staying running and crashing

### APP-045: A program started at sign-in or login runs once, and nothing restarts it.
- Why: Windows "run at sign-in" and a macOS login item each start a program once and never again, so an app that dies stays dead until the next login.
- Must: Every long-running part on an editor's computer has something that restarts it, and nothing the app needs dies with an upgrade.
- Kind: given

### APP-046: A program started over a remote shell on Windows died with the session.
- Why: It lands outside the desktop with no tray icon and is killed when the shell closes, logged like a clean stop; a scheduled task gets a stripped environment.
- Must: Long-lived processes start fully detached, finding every helper without inherited environment, and after a remote install the app is started in the person's own desktop session.
- Kind: given

### APP-047: Mac background-launch rules can run the app twice or kill it during its own update.
- Why: launchd's KeepAlive restarts an app that exits on purpose; without AbandonProcessGroup it kills the relaunched child; only a parent process sees an exit status.
- Must: On a Mac the app restarts after a crash or Force Quit, never after Quit or self-update, never runs twice, and survives its own update.
- Kind: given

### APP-048: After a self-restart on Windows, the computer was left with no app running.
- Why: Windows reports a process as exited at the start of termination, while it still holds its handles, including the single-copy lock, for a second or more.
- Must: A replacing copy waits for the old process to be fully gone, plus up to 15 seconds, before deciding another copy holds the lock.
- Kind: given

### APP-049: After a reboot, a reused process number made the app think it was already running.
- Why: Process numbers are reused after a restart, and a loose match on number and command line refused to start the real app.
- Must: Checking for another running copy of the app never relies on a process number alone.
- Kind: given

### APP-050: Ordinary Windows shutdowns were counted as crashes of the app.
- Why: Windows sends an end-session notice at shutdown and may end the program at any moment afterwards; 4 of 9 reported crashes were plain shutdowns.
- Must: On the end-session notice (Windows or macOS) a clean exit is recorded at once; a cancelled shutdown records nothing, and a real power loss still counts as a crash.
- Kind: given

### APP-051: A computer's clock stepping backwards erased crash and relaunch history.
- Why: Time synchronisation, a virtual machine resuming or dual booting can move the clock backwards; records with "future" times were discarded, forgiving recent crashes and shortening waits.
- Must: Crash, restart and rate-limit counts and waits survive the clock stepping backwards or forwards and never reset because of it.
- Kind: given

### APP-052: On Windows, two clock readings a moment apart are often identical.
- Why: Windows' clock ticks every 15.6 ms, so identifiers taken from the time collided (6 distinct of 10), muting new warnings and double-counting relaunches.
- Must: Nothing uses a clock reading as a unique identifier; two events in the same instant stay distinct.
- Kind: given

### APP-053: A program started at Mac login cannot find tools that work in Terminal.
- Why: Programs launched by macOS's login service get a search path of /usr/bin:/bin:/usr/sbin:/sbin only, without Homebrew or per-user tool folders.
- Must: Everything the app runs on a Mac is referenced by a full path recorded at install.
- Kind: given

### APP-054: A Windows laptop on battery silently stopped a scheduled background task.
- Why: Windows scheduled tasks by default do not start on battery and stop when the laptop is unplugged, leaving no error.
- Must: Anything the app schedules keeps running on battery, and a stopped background job shows on the computer and the dashboard.
- Kind: given

### APP-055: A Mac app froze at start with its sync folder on an exFAT drive.
- Why: Starting a file-change watch on an exFAT external drive on macOS can block in the kernel indefinitely, freezing whatever waits on it.
- Must: A stuck file-change watch never freezes the app; the tray, Resolve checks and sync keep running.
- Kind: given

### APP-056: The app vanished silently and stayed dead for hours: it must restart itself.
- Why: Native aborts left nothing in the log; the app stayed down 47 minutes to 3 hours on Windows, 85 minutes on a Mac. Owner: "it should be able to auto start after a crash".
- Must: On Windows and macOS an unasked death is recorded, shown on next start, and relaunched within about 10 seconds, at most three times an hour, never after Quit, logout, update or uninstall.
- Kind: ruling

### APP-057: A Start menu entry reopens the app; no stray copy runs beside it.
- Why: An editor whose app had vanished restarted a months-old copy from a downloaded zip, which ran beside the real app and wrote into its log.
- Must: Every install leaves a Start menu entry, named after the product, that starts the installed app, and every build refuses to run beside another copy.
- Kind: ruling

### APP-058: The tray shows the running version, and confirms a finished update.
- Why: Nobody could tell which version a machine ran; the owner asked for the version at the top of the tray and a message when an update completes.
- Must: The tray shows the running version at the top, and the first start after an update says it is now running the new version.
- Kind: ruling

### APP-059: The relaunch limit stopped at two an hour, or never held at all.
- Why: Each relaunch was counted twice, so "three an hour" stopped at two; with the state folder unwritable (full disk, antivirus lock) every crash looked like the first.
- Must: A crashed app is relaunched exactly the advertised number of times per hour, even when it cannot save its records, and failed saves are reported to the dashboard.
- Kind: situation

### APP-060: Fourteen "crashes" on one computer were all deliberate stops.
- Why: Upgrades, test runs and manual restarts each filed a crash report, and a manual upgrade killed an instance that had just upgraded itself.
- Must: A deliberate stop (upgrade, quit, an operator's kill) is never counted as a crash, and two upgrade routes on one computer never kill each other's result.
- Kind: situation

### APP-061: A dead background part of the app was reported as running.
- Why: Watchdogs asked "was it started", not "is it alive"; the loop driving sync stopped with no restart, and back-off spacing meant the hourly restart limit never applied.
- Must: Every background part is judged alive by doing its work, restarted with growing waits, stops after six restarts an hour asking for a person, and each restart is reported.
- Kind: situation

### APP-062: Opening a second progress window crashed the whole app.
- Why: Running one long job after another, each with its own window, force-closed the app with no message.
- Must: Any number of windows can open and close, together or in a row, in any order, without the app ending.
- Kind: situation

### APP-063: A wrongly typed setting made the app vanish at startup without a word.
- Why: A setting hand-edited to a number instead of a folder path crashed the app before its tray icon appeared, leaving only a log line.
- Must: A malformed setting never stops the app starting; it starts, shows its icon and names the setting that is wrong.
- Kind: situation

### APP-064: Quit, cancel or an update left a transfer or encoder running after the app.
- Why: The app exited before its tear-down finished; transfers outlived it and raced the new build, and an orphaned local model held 4 to 12 GB of video memory.
- Must: Quit, cancel, restart and update stop every helper the app started (waiting up to 40 seconds), and at start any leftover helper is stopped first.
- Kind: situation

### APP-065: A restart, update or Quit cut off a multi-hour copy halfway.
- Why: Automatic restarts did not wait for a running copy-and-relink job, Quit stopped everything at once, and macOS quit events skipped the clean shutdown.
- Must: No automatic restart or update starts during a copy, relink or sharing job; Quit names what is in flight and asks, proceeding if that cannot be checked.
- Kind: situation

### APP-066: The quit-while-copying question read as broken English.
- Why: With a file number but no batch total, the question read "copying file 3 files in".
- Must: Every wording of a question is a correct sentence; with no known total it says a file is being copied, with no half count.
- Kind: situation

## The tray or menu-bar icon and its menu

### APP-070: At Windows sign-in the tray icon failed to appear and every notice was lost.
- Why: At login Windows' notification area is often not ready within 3 s and can take up to 105 s; adding the icon failed, and the app dropped every later notice, safety warnings included.
- Must: Placing the icon retries for minutes; notices raised meanwhile (at least the five newest) show once it is up; if it never appears, editor and admin are told.
- Kind: given

### APP-071: After Windows Explorer restarted, the tray icon vanished or came back frozen.
- Why: An Explorer restart (shell crash, graphics driver reset, update) drops every tray icon and broadcasts once; a failed re-add left no icon, menu or Quit, or a frozen icon.
- Must: The icon returns and keeps updating after any Explorer restart, retrying until it works, without the menu going unresponsive for more than about 2.5 seconds meanwhile.
- Kind: given

### APP-072: With an auto-hiding Windows taskbar, the tray menu opened behind the taskbar.
- Why: Windows leaves an auto-hide taskbar out of the screen area menus are kept inside, so a menu opened at the cursor is covered by the raised bar.
- Must: The tray menu opens fully clear of the taskbar, docked or auto-hidden, on whichever screen edge.
- Kind: given

### APP-073: A very long menu line stretched the right-click menu across the whole screen.
- Why: Windows and macOS menus never wrap or shorten an item, so a 440-character line makes the menu that wide.
- Must: Tray menu lines stay short, about 80 characters at most, with full explanations in a window.
- Kind: given

### APP-074: Tray hover text cut to 127 characters still failed on Windows.
- Why: Windows limits tray hover text to 128 units and counts emoji and rare Chinese characters as two units each.
- Must: Tray hover text always fits Windows' 128-unit limit, measured the way Windows counts, including emoji and rare Chinese characters.
- Kind: given

### APP-075: A tray menu rebuilt while open vanished under the editor's mouse.
- Why: Rebuilding an open menu destroys it under the cursor, so lines carrying live percentages make it unusable; on macOS rebuilding an open menu-bar menu is also unsafe.
- Must: An open tray or menu-bar menu is never rebuilt for a changing figure; changes to what it lists wait until it closes.
- Kind: given

### APP-076: On macOS, changing the menu-bar icon or a window from another thread risks a crash.
- Why: macOS menu-bar items, menus and windows may only be changed from the main thread; elsewhere it can crash without a trace or block for ever.
- Must: On macOS every menu-bar, menu and window change, animation included, is handed to the main thread without the caller waiting.
- Kind: given

### APP-077: On a MacBook with a notch, the app's menu-bar icon never appeared.
- Why: With a full menu bar, macOS places a new status icon behind the camera notch and draws nothing, while reporting it created.
- Must: The app detects when its menu-bar icon cannot be seen and tells the editor another way, within seconds of starting, how to reach it.
- Kind: given

### APP-078: The tray icon is the bare studio mark; colour and pulse show the state.
- Why: The owner chose no tile or border, and darker tints, because neon colours washed out on Windows' light grey taskbar.
- Must: Amber pulsing while transferring, red pulsing on error, steady amber when paused, signed out or drive missing, steady green only when fully caught up; legible on light and dark taskbars.
- Kind: ruling

### APP-079: The tray menu had grown to forty lines; the owner set a short one.
- Why: He approved: identity, one conditional prompt, "Sync:" with files and speed, "Resolve: connected", sync now, pause, "Open my sync drive", open dashboard, settings, quit.
- Must: The right-click menu holds only those everyday items, about ten; this computer's role and every other control live in a settings window the menu opens.
- Kind: ruling

### APP-080: A wired computer that syncs nothing must show green unless something is wrong.
- Why: The owner's computer works straight off the NAS with sync off by design, yet showed amber and "sync engine not running" as a blocking problem for two days.
- Must: A computer configured to sync nothing shows the healthy colour and never reports the missing sync as a problem; owner: "green unless there is an error".
- Kind: ruling

### APP-081: The tray's "Open dashboard" opened an address browsers could not use.
- Why: The owner wanted the link to work for remote editors too; after the dashboard went https-only for browsers, the tray still opened the plain address the app reports to.
- Must: "Open dashboard" opens the address the site publishes for people, reachable from wherever the computer is, falling back to the reporting address only when none is published.
- Kind: ruling

### APP-082: Right-clicking the tray icon opened the menu seconds late, or not at all.
- Why: Long background work, including Resolve scripting calls of 33 to 91 s, kept the tray from answering clicks, and rebuilds racing a click left a dead menu.
- Must: A right-click opens the tray menu within half a second, and highlighting follows the mouse instantly, every time, whatever Resolve or the sync is doing.
- Kind: situation

### APP-083: The tray lagged up to seven seconds per refresh while the dashboard was down.
- Why: Each two-second refresh made a fresh five-second attempt to reach the unreachable dashboard.
- Must: With the dashboard unreachable the tray is as responsive as online, and the dashboard is retried on a schedule, not on every refresh.
- Kind: situation

### APP-084: Tray actions that did nothing said nothing.
- Why: "Sync now" checked one of six reasons sync refuses and said "Sync requested" on a halted computer; "Open my sync drive" silently did nothing with no drive set.
- Must: Every tray action answers, accepted or "not now" with the same reason that stops sync; Quit says what stops and until when, with Restart beside it.
- Kind: situation

### APP-085: "Open dashboard" did nothing when clicked.
- Why: On a remote editor's computer the open-dashboard action silently failed to open a browser.
- Must: If opening the dashboard fails, the person is told and shown the address to open by hand.
- Kind: situation

### APP-086: An editor's app was not showing up on his Mac.
- Why: The owner reported the app missing for a Mac editor; the cause was not recorded.
- Must: While the app runs on a Mac its menu-bar presence is visible, and the dashboard shows whether that computer is reporting.
- Kind: situation

## Windows, dialogs and notifications

### APP-087: A blank black window appeared at install, and closing it killed the app.
- Why: A Windows program built as a console program, or a helper started without the no-window option, gets a console window, and closing it ends the program.
- Must: Nothing the app or its helpers start on Windows ever shows a console window, whether started by the installer, at login or after an update.
- Kind: given

### APP-088: Windows showed the program file's icon on the taskbar and an internal id on notifications.
- Why: Windows fixes a taskbar button's application identity when the first window appears; one declared later is ignored for the process's life.
- Must: Every process that shows windows declares the product's identity, name and mark before its first window, so taskbar and notifications show the product.
- Kind: given

### APP-089: Windows cut long notifications off at the end, where the action was.
- Why: Windows tray notification text is cut at about 250 characters, and the action an editor needs usually sits at the end.
- Must: Notification text too long for Windows is shortened in the middle, keeping its opening and its closing action.
- Kind: given

### APP-090: On macOS a quit confirmation froze every other window of the app.
- Why: On macOS tray menu actions and window work share one main thread, so a question left on screen stalled progress windows and dialogs for up to 120 seconds.
- Must: A confirmation left open never freezes the app's other windows, and if it times out, Quit still quits.
- Kind: given

### APP-091: A folder picker left open on a Mac blocked every other window and update.
- Why: macOS gives an app no way to close an open picker panel after a timeout, so it stayed up and held the app's one-window-at-a-time slot.
- Must: A picker left open never silently blocks fixes, settings or updates; the app says what is waiting on it.
- Kind: given

### APP-092: Windows "show in folder" opened Documents for a path with spaces.
- Why: Explorer's select switch must arrive as one unquoted "/select,<path>" token with only the path quoted; quoting the whole argument silently opens Documents.
- Must: "Show in folder" opens the containing folder with the file selected, for paths with spaces and Chinese characters.
- Kind: given

### APP-093: Every long job opens a progress window: "the lack of feedback is disturbing".
- Why: B-roll indexing, music indexing and proxy making showed only tray lines; the owner asked for windows that also close themselves when done.
- Must: Each long job shows download, per-item and overall progress and time left; closing its window never stops the job, and it closes itself within seconds of finishing.
- Kind: ruling

### APP-094: Any download the app starts announces itself.
- Why: Model downloads started silently; the owner asked for "x model is downloading. Right click ... to see progress."
- Must: Starting any download raises a notification naming it and where to see progress, and another when it is ready.
- Kind: ruling

### APP-096: A window that could not close blocked every later window, and shutdown.
- Why: A failed dialog, a retried batch or a progress window ending itself the wrong way kept the one-window slot, so later dialogs and "Update now" were refused and the app ignored shutdown.
- Must: Every dialog can always be closed, a second batch in one dialog finishes normally, later windows still open, and quitting always works.
- Kind: situation

### APP-097: One unanswered dialog silenced every other project's prompts and held back updates all day.
- Why: A missing-media dialog left open nine hours hid prompts for other projects, matched by file path alone, and pushed updates refused to install while it stayed open.
- Must: Prompts for different projects are never merged or suppressed by an open dialog, and an update waiting on an open dialog shows that on the dashboard.
- Kind: situation

### APP-098: A settings window that failed while opening stayed on screen, frozen.
- Why: A display change (a remote desktop session switching) during construction left an unresponsive, uncloseable window, and each new click added another.
- Must: A window that fails while opening is closed and the failure reported; the next click opens one working window.
- Kind: situation

### APP-099: The settings window flashed every button white every two seconds.
- Why: The window was torn down and rebuilt on each two-second refresh, so the scroll jumped and clicks landed on vanishing controls.
- Must: A periodically refreshed window redraws only what changed, keeps its scroll position, and never flickers or drops a click.
- Kind: situation

### APP-100: Pressing Enter on a focused Cancel button ran the window's main action.
- Why: The app's buttons took no keyboard focus, so Enter always triggered the window's default.
- Must: Every button can be reached by keyboard and shows focus, and Enter acts on the focused button.
- Kind: situation

### APP-101: One long clean-up repeated "files moved to trash" on every pass.
- Why: A clean-up of about 30 GB, spread over many passes by a safety cap, raised the same notification each pass.
- Must: The same notification repeats at most once every 30 minutes, and the first one is never suppressed.
- Kind: situation

### APP-102: The pulled-drive reminder kept nagging when only downloads were waiting.
- Why: Downloads can safely wait for the drive; only work owed up to the server is at risk while it is away.
- Must: A pulled sync drive gives one warning; half-hourly reminders continue only while uploads the server does not yet have are owed.
- Kind: situation

### APP-103: A Mac editor was shown a folder path with Windows backslashes.
- Why: A message joined a Mac path with a backslash, so the one line saying where the editor's stills went failed in Finder's Go to Folder.
- Must: A path shown to an editor uses their own system's separators, so it can be pasted into Finder or Explorer.
- Kind: situation

See also, filed under another capability:

- CE3-092 (Timeline Cards: the editor): The desktop editor is one whole window, like Resolve.

## Telling the editor what is wrong

### APP-108: The status icon stayed green while nothing had synced for days.
- Why: An unaccepted licence, a safety stop, a rejected sign-in or a replugged drive with sign-in missing left the icon green or showed a stale reason, shown only in settings.
- Must: Whenever anything blocks syncing the icon leaves green, and the at-a-glance status names the one current blocker, changing when it changes.
- Kind: situation

### APP-109: A dozen equally loud red warnings hid the one that mattered.
- Why: Every status line was drawn as a warning in source order, so a blocking problem sat at the bottom beside harmless information.
- Must: Status lines are ranked blocking, warning, information; duplicates collapse with a count; six show and the rest sit behind "show all".
- Kind: situation

### APP-110: Tray status lines hid the real cause behind jargon.
- Why: The tray showed "Something went wrong" for hours, "tidying old files in slices" and "paused at the 600s project budget", none of which an editor could understand.
- Must: Every status names its actual cause in plain words, and a deliberate safety pause reads as progress with when it resumes, not as an error.
- Kind: situation

### APP-111: The tray said "downloading" for ever with nothing to download from.
- Why: With no connection to the server, the downloader still reported syncing, so the icon pulsed amber and counted files that could not arrive.
- Must: "Downloading" shows only while files are actually arriving; with no connection the tray says it is waiting for the server.
- Kind: situation

### APP-112: Problems the app found on a computer reached nobody.
- Why: Background crashes, a shared library not working, a folder moved after a rename and failing tool installs went only to a log or crash file while the tray stayed green.
- Must: Every problem the app detects shows in its tray and settings window and is counted in its report, even with nothing ticked or the feature off, until cleared.
- Kind: situation

### APP-113: Crash reports overwrote each other and were kept where nobody read them.
- Why: A new crash file truncated an older one, reports could hold secrets, and no crash ever left the computer.
- Must: Every crash report is kept without overwriting another, has secrets removed, and is counted on the dashboard.
- Kind: situation

### APP-114: A tray glitch the app recovers from filled the crash reports.
- Why: Each temporary tray failure wrote a crash report and advised a restart; with only the newest 20 kept, they pushed out the real crashes.
- Must: A failure the app recovers from by itself writes no crash report and never advises a restart.
- Kind: situation

### APP-115: A safety warning told the editor to restart, which silently clears the safety stop.
- Why: A restart drops the sync safety stops the warning was protecting, yet the sentence offered a restart as the remedy.
- Must: A warning about a safety stop never suggests a restart; it names an action the editor can take, such as sending diagnostics to the admin.
- Kind: situation

### APP-116: An editor was sent to an admin, or to re-run setup, for a one-click fix.
- Why: A licence refusal said to re-run setup and an identity warning said to send the log to an admin, though the app itself held the fix.
- Must: A message about a problem always points at the smallest action that clears it, and says where in the app that action lives.
- Kind: situation

### APP-117: Help and diagnostics sat below two screens of warnings.
- Why: On a computer with problems, the help button that eight warnings point at sat below a status section taller than the window.
- Must: When anything is wrong, help and diagnostics are reachable without scrolling, with a fixed jump bar to each section.
- Kind: situation

### APP-118: Error messages sent editors to menu items that no longer existed.
- Why: About twenty sentences named tray menu rows removed when the menu was redesigned, and fixing them by hand repeated the drift.
- Must: Every sentence that says where to click names a control that exists, and an automatic check fails when one does not.
- Kind: situation

### APP-119: Ages and deadlines shown to editors were wrong.
- Why: A sync plan live a minute read "10 days ago", and the trash deadline ignored the site's retention setting.
- Must: Every age, deadline and retention figure shown to an editor reflects the true value and this site's settings.
- Kind: situation

### APP-121: A repeating warning rotated away the log history support needed.
- Why: A port held by another program logged six lines every two minutes, and a per-clip "missing" line filled the 5 MB log every 25 minutes.
- Must: A recurring condition is logged loudly once when it starts, then as a count per pass until it changes, so the log keeps days of history.
- Kind: situation

### APP-122: A computer's own plan was visible only as a stack of remove buttons.
- Why: The only list of projects ticked for the computer was its remove buttons, and "upload only" appeared only inside a delete button's label.
- Must: The app lists each project ticked for this computer with its mode and transfer state in words; an empty plan says to tick projects on the dashboard.
- Kind: situation

See also, filed under another capability:

- BRO-009 (The b-roll archive): The page said the local app was not running when Chrome had blocked it.
- RSV-135 (Resolve on the editor's computer): A rehearsal of fixing media reported files copied, failed or uploading.

## Signing in, the computer's identity and the licence

### APP-123: An editor app's sign-in must never expire on its own.
- Why: Sign-in lapsed after 30 days; sync and reporting stopped silently on unattended machines (an editor lost two days, a render machine a weekend), with one night-time balloon.
- Must: A healthy computer never loses its sign-in by time alone; if it is ever refused, the editor and dashboard are told and the editor reminded hourly.
- Kind: ruling

### APP-124: A refused sign-in showed "HTTP 403" instead of what to do.
- Why: The app read the wrong part of the server's refusal, so "ask an admin to add you to the editors group" and "server busy, retry" never reached the editor.
- Must: When sign-in is refused, the editor sees the server's own plain reason and what to do next, for every kind of refusal.
- Kind: situation

### APP-125: The server stopped accepting a computer's reports and nobody found out.
- Why: A revoked credential or wrong address left sync running and the tray green while the computer vanished from the dashboard; the only button offered was sign out.
- Must: A rejected credential tells the editor once, reads differently from "server unreachable" everywhere, offers signing in again first, and when a report was last accepted survives restarts.
- Kind: situation

### APP-127: Pause then resume started syncing on a computer nobody had signed in to.
- Why: Start and sign-in refused to sync while signed out, but resuming from pause did not check, even after a sign-in had lapsed.
- Must: No path, resume from pause included, starts syncing on a computer that is not signed in when sign-in is required.
- Kind: situation

### APP-128: An unreadable identity file turned a computer into a new one.
- Why: A truncated, locked or quarantined identity file was read as "no identity yet", so a new one was written over it and the server saw another computer.
- Must: A computer's identity is created only when none exists; one that cannot be read is reported to the editor and admin and never silently replaced.
- Kind: situation

### APP-129: An unreadable computer identity had a warning and no way out.
- Why: The app rightly refused to mint a new identity silently, but offered the editor nothing to do.
- Must: One confirmed button says it gives this computer a new identity (never "repair"), sets the old file aside, and never claims success when nothing changed.
- Kind: situation

### APP-130: An update parked sync behind a licence prompt nobody saw, for 18 hours, twice.
- Why: Only first-time setup could record acceptance, the prompt lost to a popup opening every start, closing it counted as declining, and the dashboard showed the computer idle.
- Must: A prompt that stops sync appears in the app within a minute, returns until answered, treats closing as unanswered, resumes sync on accept, and the dashboard names the reason.
- Kind: situation

### APP-132: The owner switched his server-side computer to remote by one click and feared deletions.
- Why: Remote mode may remove local files during download, so flipping the NAS-side machine endangered the live share; the reverse click silently stopped all syncing.
- Must: Switching a computer between wired and remote asks first, names the consequence plainly, and the direction that can delete needs the word REMOTE typed.
- Kind: situation

See also, filed under another capability:

- SYN-022 (Sync): Signing in as someone else ran the previous person's projects.
- SYN-023 (Sync): Wired or remote belongs to each computer, not to the person signed in.

## Settings, records and background work

### APP-144: A Mac laptop on battery with its lid closed sleeps despite keep-awake.
- Why: A remote editor's Mac on battery with the lid shut slept overnight though the app asked to stay awake, and the interrupted upload started again from zero.
- Must: When an upload is owed, the editor is warned that closing the lid on battery stops it, and the dashboard shows this as the reason.
- Kind: given

### APP-133: An update must never reset a computer's own settings.
- Why: An editor's Resolve is installed off the C: drive, and the owner required that updating the app never resets that setting.
- Must: After any update, every setting chosen on that computer, including where Resolve is installed, is unchanged.
- Kind: ruling

### APP-134: A save cut off by a crash or full disk reset the app's settings.
- Why: Settings, decisions and safety-stop records were rewritten in place, so a power cut or overlapping writer left a broken file read as "never asked", "not halted" or defaults.
- Must: Every record is replaced whole or left untouched, whatever the timing; an unreadable one gives the cautious answer or the last good copy, with a visible warning.
- Kind: situation

### APP-135: Half-written temporary files from killed processes piled up for ever.
- Why: A process killed between writing a temporary file and renaming it leaves it behind, and the cleanup only matched finished file names.
- Must: Every cleanup that ages out the app's records also removes temporary files left by a killed write, on the same retention.
- Kind: situation

### APP-136: Files the product keeps on an editor's computer grew without limit.
- Why: On-demand b-roll and music clips were never evicted (about 150 GB a year), save-point exports grew 10 to 50 GB a year, and each install left 130 MB.
- Must: Every file the product stores on an editor's computer has a size or age limit and is removed when it passes it.
- Kind: situation

### APP-137: Reports from editors' computers grew with the size of the media pool.
- Why: A list of refused relinks had no cap, so 200 or more clips went into every 30-second report.
- Must: Every list a computer reports is capped, keeping the newest, with a count of what was left out.
- Kind: situation

### APP-138: A feature switched on for the site never reached apps already running.
- Why: Site settings were read once at start, so a switch flipped later, or an app that started offline, waited for a restart.
- Must: Site settings changes reach every running app within minutes, with no restart, and an app that started offline picks them up when it reconnects.
- Kind: situation

### APP-139: A studio's own logo vanished from every computer on update.
- Why: The logo was set per computer, so an update that changed the default stripped it, and restoring it meant touching every editor.
- Must: A studio's logo is set once centrally, reaches every computer, and survives updates.
- Kind: situation

### APP-140: Setting the local helper's port to 0 silently killed Send to Resolve.
- Why: Port 0 means "any free port", so the helper came up where no web page could find it while the app reported it fine.
- Must: An invalid helper port is refused with a warning and the standard port used; switching the helper off is a separate, explicit setting.
- Kind: situation

### APP-141: Any web page could drive the editor's local helper.
- Why: Pages could post actions to the helper on the editor's computer, and status requests from any page each spawned a slow background process, unbounded.
- Must: Only the studio's own pages can trigger actions on an editor's computer, untrusted text never runs as script there, and repeated status checks spawn bounded work.
- Kind: situation

### APP-142: An admin's request for diagnostics was dropped or refused for good.
- Why: The request was marked answered before the upload, so a failure was never retried, and a stuck "in progress" mark refused every later request silently.
- Must: An admin's request is marked done only once it succeeds and is retried until then; every "in progress" mark expires after a generous limit.
- Kind: situation

### APP-143: Retries ran every few seconds for ever, overflowed after weeks, or waited a whole day.
- Why: A doubling wait overflowed after 21 days, some loops never slowed, every computer polled a down dashboard every 30 s, and a failed tool install waited a day.
- Must: Every automatic retry grows its wait to a 30-minute cap, has an hourly ceiling, never queues duplicates, recovers promptly when the other end answers, and survives months of uptime.
- Kind: situation

### APP-145: A lost NAS connection kept a PC awake and blocked every shutdown.
- Why: "Still syncing" counted files still needed, not data moving, so with the NAS off overnight the PC never slept and shutdowns were interrupted.
- Must: Keep-awake and shutdown warnings apply only while data is moving or recently moved, with a maximum hold time.
- Kind: situation

### APP-146: Helper jobs either hung for ever or were killed mid-encode by a fixed limit.
- Why: Some helper processes had no upper bound, while every long encode was cut off at 15 minutes regardless of size.
- Must: A helper job is stopped when it makes no progress for a set time, and a slow job that keeps progressing is never killed by a fixed clock.
- Kind: situation

### RSV-150: Send to Resolve failed when the dashboard address differed from the browser's.
- Why: The editor's app accepts browser requests only from the configured dashboard address, so another spelling of the same address refused every Send to Resolve.
- Must: Site settings warn that the dashboard address must be exactly what editors type, and a refusal names both addresses.
- Kind: situation

### RSV-151: Send to Resolve did nothing when another program held the app's local port.
- Why: The app tried its local listening port once at start; when another program held it, the app still believed it was serving and only the browser saw failures.
- Must: The local port's health is retried, shown on the computer and reported to the dashboard, which warns when the feature is on and the port is not ours.
- Kind: situation

## Uninstalling

### APP-148: On Windows one locked file can make a folder delete remove nothing at all.
- Why: With Windows' built-in shell a recursive delete removes nothing when one file is locked, and a just-stopped program, antivirus scan or the uninstaller itself can still hold locks.
- Must: The uninstaller re-reads what is really gone after every delete, and removes the installed-apps entry only once the files are gone.
- Kind: given

### APP-149: Uninstalls reported removals they had not checked.
- Why: A held log file kept the sign-in file alive, a Mac script printed "complete" over root-owned leftovers, dry runs claimed deletions, and leftovers advice said to delete the uninstaller too.
- Must: Uninstall says complete only when verified, names every leftover with its path and how to retry, never suggests removing the retry path, and a dry run changes nothing.
- Kind: situation

### APP-150: The Mac uninstaller always destroyed the computer's sync identity; Windows always kept it.
- Why: The platforms disagreed, so a Mac reinstall needed fresh approval while Windows promised none was needed, and the closing text contradicted itself.
- Must: Uninstall treats the sync identity the same on every platform and states once, truthfully, whether re-approval will be needed.
- Kind: situation

### APP-151: Uninstalling left the computer able to reach the studio's server.
- Why: Uninstalling the app left its server credentials on the computer.
- Must: After uninstall, no credential that lets the computer reach the studio's server remains on it.
- Kind: situation

### APP-152: The app appeared in no uninstall list, or with a blank icon.
- Why: The uninstaller came only with one install package, and the installed-apps entry was written before the program existed, so its icon was skipped.
- Must: On Windows the app is listed in installed apps with its icon and a working uninstall from the first install; on a Mac the uninstaller sits beside the app.
- Kind: situation

### APP-153: Uninstalling removed the firewall rule while the share it guarded was still published.
- Why: The uninstaller dropped the block rule when the drive unmapped, even when removing the share had failed or could not be checked.
- Must: A protection is removed only after the thing it protects is confirmed gone; an unreadable state counts as still there.
- Kind: situation
