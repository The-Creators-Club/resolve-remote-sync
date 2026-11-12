# Companion: the tray icon, menus, windows, dialogs and notifications

Terms used throughout:

- **Tray icon**: the small status icon the companion puts in the Windows notification area (bottom right) or the macOS menu bar (top right).
- **Balloon / toast / notification**: a short pop-up message raised by the operating system on the companion's behalf. Its title is the site's notification title (the site name, or "CCSync" when the site has none; the exact title helper lives outside this part).
- **Lane A / B / C**: the companion's sync channels. Lane A uploads this computer's video originals to the server; lane B downloads proxies (small editing copies) from the server; lane C keeps everything else (audio, graphics, subtitles, project files) in step both ways using Syncthing. A fourth channel, "originals on request", downloads full-resolution originals an editor asked for.
- **Base rig**: the office computer whose working tree is the server share itself, so it syncs nothing by design.
- **Sync guard**: the companion's own summary of every safety stop and every reason sync is blocked; the tray reads it, never computes it.
- **Popup lock**: only one companion window can be open at a time; most dialogs refuse with a balloon if another is already open.
- **Route**: the menu path a sentence tells the editor to follow, always written `Tray > Settings > ...` (source: ui_copy.py, the one place routes are spelled). The ones used in user-visible text: "Tray > Quit CCSync", "Tray > Sign in", "Tray > Settings", "Tray > Accept the licence agreement", "Tray > Settings > READ AND ACCEPT THE LICENCE", "Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN" (written below as "<diagnostics route>"), "Tray > Settings > OPEN LOG", "Tray > Settings > SIGN IN", "Tray > Settings > SCAN WHOLE PROJECT", "Tray > Settings > BRING AN EXISTING PROJECT'S MEDIA INTO THE SYNCED FOLDER", "Tray > Settings > UNDO THE LAST CLIP-PATH CHANGE CCSYNC MADE", "Tray > Settings > STOP ALL SYNCING ON THIS COMPUTER", "Tray > Settings > CLEAR THE SYNC STOP ON THIS COMPUTER", "Tray > Settings > Accept YouTube Terms", "Tray > Settings > Sign in to YouTube", "Tray > Settings > Use an exported cookies.txt", "Tray > Settings > REMOVE '<project>' FROM THIS COMPUTER", "Tray > Settings > FINISH GRADING: P: BACK TO LOCAL PROXIES", "Tray > Settings > REPAIR P: NOW", "Tray > Settings > HELP". The help page is `<dashboard_url>/help` (absent when no dashboard address is configured).
- **Counts** in user-visible text use real plurals ("1 file", "3 files"), never "file(s)". Channel words shared with the dashboard: upload (lane A), proxy download (lane B), originals download, folder sync (lane C), express upload.

## The tray icon: shape, colour and pulse
(source: tray.py, theme.py, assets)

- The icon is the product mark alone, drawn 64x64 on transparency, with no tile or border. Its silhouette never changes; only its colour and brightness carry status.
  - The mark is read from the window-icon asset (`cc_mark_white.png`, white on transparent) and tinted by painting a solid colour through its alpha channel.
  - A site can replace the mark with its own logo through the environment variable `CCSYNC_BRAND_LOGO` (see the theme section); the tray and the window title bars change together.
  - If the mark file is missing or unreadable, the icon falls back to a drawn glyph: an upward chevron over a downward chevron with a soft glow.
- Three colours. Green and amber are deliberately darker than the window palette so they read on a light-grey Windows taskbar: green RGB (24, 190, 98), amber RGB (216, 140, 18), red RGB (255, 33, 64).
- Colour rules, evaluated in this order (first match wins):
  1. **Red** if any lane is in the error state.
  2. **Red** if the configuration has problems (the computer is not set up).
  3. **Amber** if the sync drive is absent (unplugged, not answering, or mounted at the wrong place).
  4. **Amber** if nobody is signed in and sign-in is required.
  5. **Amber** if sync is paused.
  6. **Amber** if sync is disabled on this computer, except on the base rig, where disabled sync is the normal state and the icon stays green.
  7. If the sync guard reports a blocking reason:
     - "nothing ticked" (`no_selection`) is informational only and never changes the colour;
     - on the base rig, `no_selection` and `folders_unfiltered` are ignored;
     - `clock_skew`, `lane_stalled` and `syncthing_down` make it **red**;
     - any other blocking reason makes it **amber**.
  8. **Amber** if a call into DaVinci Resolve's scripting interface has been in flight for more than 20 seconds ("Resolve is wedged").
  9. **Amber** if any lane is transferring.
  10. Otherwise **green**. Green therefore means signed in, unpaused, configured, caught up and not blocked.
  - If reading any of the app state throws, the icon shows amber.
- **Pulse (breathing)**: the icon dims and brightens in a cosine curve, one breath every 3 seconds in 8 frames, never dimmer than 45 % brightness.
  - It pulses only when the colour is red, or when the colour is amber AND at least one lane is actually moving bytes.
  - A lane C that reports "syncing" while no server peer is connected counts as not moving, so it does not pulse.
  - Green never pulses. Steady amber states (paused, signed out, drive gone, sync disabled) never pulse.
  - When the pulse stops, the full-brightness frame is restored.
- **Refresh**: every 2 seconds the companion re-reads its state and updates the icon colour and the hover tooltip. The right-click menu is rebuilt only when something it shows changes (see "Menu rebuild rules").
- **Nothing changes while the menu is open**: while the right-click menu is open, the icon, tooltip and menu are not touched; updates resume within about a quarter second of it closing. While the menu is open, the companion also holds off its calls into Resolve (for at most 8 seconds per wait) so the menu highlight does not freeze.

## The tray icon: start-up and "is the icon actually visible?"
(source: tray.py, tray_native.py)

- The icon's name/title is the site notification title.
- **Windows**: the icon runs on its own background thread. If Windows never accepts the icon:
  - A terminal failure: the log gets an error line saying the icon, its menu, Settings and Quit are unreachable and every notification (including "sync has stopped itself") is being discarded, and to sign out and back in or restart CCSync; a crash report of type `TrayIconUnavailable` is written (which reaches the dashboard through the normal crash channel); the icon's refresh loops stop.
  - A non-terminal failure (a failed re-add after Explorer restarted): only a warning line in the log saying the icon will be re-added automatically; no crash report; refresh keeps running.
  - Sync itself is unaffected in both cases.
- **macOS**: the icon is created on the main thread. 3 seconds after start, the companion checks where macOS placed it:
  - If the icon sits below the menu bar row (not placed at all) or to the left of the camera notch on a notched display, it is invisible.
  - It then logs "TRAY ICON IS NOT VISIBLE ... The menu bar is full. Free a slot (System Settings > Control Center ...) then restart CCSync" and raises the notification: "CCSync is running, but the menu bar is full so its icon can't be shown. Free a menu bar slot and restart CCSync."
- If the tray libraries (Pillow) are not installed, the companion runs with no tray at all (status only in the console log). This fallback lives outside this part.
- **DEV ONLY**: the environment variable `CCSYNC_TRAY_BACKEND=pystray` swaps the tray to the third-party pystray library, only in an unfrozen (source) run where pystray has been installed by hand. In the shipped build it is ignored with a log warning; if pystray is missing, it falls back with a warning.

## The hover tooltip
(source: tray.py)

- Updated every 2 seconds; always safe to update even with the menu open (but it is still held while the menu is open).
- Limited to 127 characters (Windows truncates there); optional suffixes are added only if the whole line stays at or under 120 characters.
- Chosen in this order (first match wins):
  1. Configuration problems: "CCSync: NOT SET UP (nothing syncs)".
  2. Sync drive absent: "CCSync: PAUSED (<phrase>)" or, when something is still owed, "CCSync: PAUSED (<phrase>, <owed summary> still to go)" (cut to 120 characters). The phrase is "drive disconnected", "the drive is mounted at the wrong place" or "the drive is not answering".
  3. Not signed in (when sign-in is required): "CCSync: not signed in (nothing syncs)".
  4. Paused: "CCSync: PAUSED".
  5. A lane in error: "CCSync: PROBLEM with <lane name>" (the lane's name without its parenthesis: "Uploads", "Proxies", "Everything else, both ways", "Originals you asked for").
  6. A lane actually moving bytes: "CCSync: syncing · <last 40 characters of the project> · <speed>/s · <~N min> left", then the proxy suffix and the indexing suffix.
  7. The sync guard's blocking sentence: "CCSync: <detail>", shortened in the middle (not the end) so its closing instruction survives.
  8. Files owed while no server is connected: "CCSync: waiting, not connected to the server (N files owed)".
  9. Files lane A will never upload because the server holds a same-name file of a different size: "CCSync: will not upload <up to three names with sizes>", for example "A001.mov (yours 4.2 GB, the server's 3.1 GB)".
  10. A YouTube download in progress: "CCSync: downloading YouTube clip 3/12 (...)" (the download line with a lower-case first letter).
  11. Otherwise "CCSync: up to date", plus the proxy suffix, the indexing suffix and the Resolve suffix.
- **Proxy suffix** (only on states 6 and 11): while proxies are being made, " · making N proxy files" (or " · making proxies"), plus ", next at P%" where P is the highest per-clip percentage in flight; otherwise " · N need proxies" / " · 1 needs a proxy" when clips lack proxies.
- **Indexing suffix**: one only, b-roll first then music: " · fetching the <b-roll|music> model P%" while the indexing model downloads, or " · indexing <b-roll|music> D/T" while indexing runs.
- **Resolve suffix**: Resolve counts beyond the two shown on the menu line: " · Resolve: <phrases>".
- Byte and time formats used here and on lane lines: bytes as "512 B", "1.5 KB" ... "TB" (1024-based); durations as "<1 min", "45s", "~12 min", "~2h 5m".

## The right-click menu
(source: tray.py)

The menu is built from the 2-second snapshot. Items marked "line" are greyed-out, unclickable text. The menu has five groups separated by dividers, in this order.

### Group 1: who is signed in
- Line: "Signed in as <username>" or "NOT SIGNED IN".
- When not signed in: item "► Sign in… (nothing syncs until you do)" (or plain "Sign in…" when the site does not require sign-in). Opens the Sign-in dialog.
- When signed in but the dashboard has refused this computer's credential (10 or more report attempts in a row failed with HTTP 401 or 403): item "► Sign in again (the server rejected this computer's sign-in)". Opens the Sign-in dialog.
- There is no Sign out item in the menu; it is in Settings.

### Group 2: blockers and prompts (each present only while its condition holds; the group may be empty)
- Line "⚠ NOT SET UP: nothing will sync (Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN)" while the configuration has problems.
- Item "► Accept the licence agreement to start syncing…" while the licence (EULA) gate is blocking sync. Opens the licence dialog even if it was already declined this run.
- Item "Set up '<project name>' on the server…" while the project open in Resolve has no home on the server. Opens the dashboard's project-setup page (see "Project setup prompt").
- Item "► N LUT(s) only on this computer: share with the team" while Resolve's own LUT folder holds LUTs the shared LUT library does not. Copies them to the shared library (the copying itself is outside this part).
- Item "► Resume proxy download…" while lane B's safety breaker has tripped, or while proxy download is parked because the disk is nearly full. Opens the matching confirmation dialog.
- Item "► Clear the sync stop on this computer (set today at 14:32)" while a stop set on this computer is active (not a fleet-wide stop from the admin, which offers no local release). The "(set ...)" part reads "today at HH:MM" or "on 2 Sep at HH:MM" in local time and is dropped if the time cannot be read. Clicking it releases the stop at once (no confirmation) and shows the result as a balloon.
- Item "► Stop the YouTube download" while a local YouTube download runs.
- Item for an available companion build, while the dashboard offers one: "Update available → v<version> (install)" for a newer build, "Roll back to v<version> (older build, install)" for an older one, "Switch to v<version> (install)" for the same-ranked but different one; followed by " - <first line of release notes>" when the offer carries notes. Opens the Update dialog.

### Group 3: state lines (each present only when it has something to say)
- The **Sync: line** (always present). First match wins:
  1. A stop is active: "Sync: stopped by your admin" (fleet stop) or "Sync: stopped on this computer" (local stop), with " (and paused)" appended if a pause is also set.
  2. Lane B breaker tripped: "Sync: proxy download stopped (see Settings)".
  3. Not set up, or licence not accepted: "Sync: not set up yet".
  4. Drive absent: "Sync: paused (<phrase>)" or "Sync: paused (<phrase>, <owed> still to go)".
  5. Paused: "Sync: paused".
  6. The sync guard's blocking sentence: "Sync: <detail>".
  7. Transfers moving: "Sync: up U · down D files · 4.2 MB/s", "Sync: uploading N files · rate" or "Sync: downloading N files · rate". Rate is decimal megabytes per second, one decimal. Lane C's count goes to one direction only: up when its status says it is sending to the server, else down.
  8. Files waiting: if all waiting work is on a lane with no server connected, "Sync: waiting, not connected to the server (N files owed)"; otherwise "Sync: N files waiting" with " (not connected to the server)" if any lane lacks a peer.
  9. Otherwise "Sync: up to date".
- "⚠ Two things are stopping sync on this computer: your admin's stop and a pause." (fleet stop plus pause) or "⚠ Two things are stopping sync on this computer: a stop and a pause. Clear both to sync again." (local stop plus pause).
- The **Resolve line** (absent until the companion has tried to talk to Resolve, or if the state is unrecognised):
  - "Resolve: not answering for N s (<call name>)" when a Resolve call has been in flight over 20 seconds.
  - "Resolve: connected" or "Resolve: connected - <up to two count phrases>". Count phrases (zero counts are omitted): "N clips outside the tree", "N missing", "N on the wrong drive", "N other projects with clips only here", "N proxies not attached", "N clips still on a preview copy". Further phrases go to the tooltip.
  - "Resolve: not connected right now (<reason>)" if this computer has ever connected to Resolve.
  - "Resolve: NOT CONNECTED this session (<reason>)" if it never has; when the reason is "no scripting", it is replaced with advice about the scripting preference (wording outside this part).
- The **originals line**: the originals lane's own sentence, for example "Bringing originals: 12 of 80, 140.0 GB to go", while that lane runs.
- The **YouTube download line** while a local download runs: "Downloading YouTube clips" (total unknown), "Downloading YouTube clip 3/12 (4.2 MB/s, 38%)" (rate and percentage each only when known), or "Converting YouTube clip 3/12 to H.264" while re-encoding a clip Resolve could not decode. The clip number is done + failed + 1, capped at the total.
- The **YouTube sign-in waiting line**: "Waiting for you to finish signing in in the browser (240 s left)" (without the countdown when it is unknown), while a browser sign-in is in progress.
- The **forced fleet job line**: "CCSync is <transcribing|transcoding|running a job> for the fleet while you work because <reason>", shown only when an admin forced a job onto this computer.
- The **ffmpeg sidecar line**: a warning that this computer could not install its ffmpeg helper (wording lives in the downloader manager, outside this part).
- The **b-roll indexing failure line**: "N b-roll clips could not be indexed: <first file name> (<reason>), and M more", or "... could not be indexed. See the log" when reasons are unknown.

### Group 4: everyday actions
- "Sync now": asks for an immediate sync pass. Balloon afterwards: "Sync requested: <lanes>" or "Sync requested. Checking the server for changes now." when accepted; "Not now: <reason>" or "Not now: nothing on this computer needs syncing." when refused. Silent if the app gives no answer.
- "⚡ Take fleet jobs now (N min)" / "⚡ Taking fleet jobs until HH:MM (click to stop)" / "⚡ Taking fleet jobs now (click to stop)" (when the deadline cannot be read). Shown with a check mark while active. Present only when this computer has a job runner with fleet jobs enabled; N is the runner's volunteer duration, default 30 minutes. Clicking turns it on ("Taking fleet jobs for the next N minutes, even while you work.") or off ("Back to taking fleet jobs only while you are away.").
- "⏸ Pause syncing" / "▶ Resume syncing (paused by you)", with a check mark while paused. Toggles pause.
- "Open my sync drive": opens the sync folder in Explorer/Finder. With no sync folder configured: balloon "This computer has no sync drive set up yet: open Settings, THIS COMPUTER." If the folder does not exist: "CCSync cannot open <path> right now: it is not there. If it is on a drive you unplug, plug it back in." If opening fails: "CCSync could not open <path>."
- "Open dashboard": present only when a dashboard address is known. Opens the site manifest's published browser address if there is one, otherwise the configured `dashboard_url`. If no browser can be launched: "Couldn't open a browser. The dashboard is at <url>".
- "Field backup…": present only when this computer has the field backup service. Opens its local page in the browser; if the page is not running: "The field backup page is not running on this computer (it is switched off in the config, or its port is taken). The log says which." (The field page itself belongs to another section.)
- "Settings…": opens the Settings window.

### Group 5: lifecycle
- "Restart CCSync": restarts the companion through the Settings window's restart action (see Settings > HELP). Fallback if that is unavailable: the companion relaunches itself; on failure "CCSync could not restart itself. Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN."
- "Quit CCSync (nothing syncs until you start it again, or log in to this computer again)": quits.
  - If a FIX ALL copy (copying media into the synced folder) is running, it first asks. Windows: a native warning box titled "CCSync" with Yes/No: "CCSync is copying file I of N files into your synced folder. Quitting now abandons the file it is on. The rest of the batch is not copied and Resolve is not repointed at it. Quit anyway? [ Yes ] quits. [ No ] keeps copying." macOS: an alert "CCSync is still copying" with buttons "Quit anyway" and "Keep copying" (default), timing out after 120 seconds. Variants without an index or total: "CCSync is copying N files into ...", "CCSync is copying a file into ...", "CCSync is copying files into ...".
  - If the copy state cannot be read or the question cannot be shown, Quit goes ahead.
  - On macOS the whole quit runs off the main thread so an open alert does not freeze other windows.

### Every menu action
- Every action runs on its own background thread. If an action throws, the balloon "'<action name>' didn't work. Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN." is shown.

### Menu rebuild rules
- The menu is rebuilt only when one of these changes: each lane's name, state, detail, error, current project, whether it has queued files, and its progress in tenths (or in 5 GB steps when the total is unknown); the identity line; signed-in; paused; configuration problems; drive absent and what is owed; the Resolve line; the project-setup name; the offered version; the dashboard address; the icon colour; the stray LUT count; the safety latches (breaker tripped and its reason, stop active/scope/reason, trash size in whole gigabytes, the "same name, different size" count, the stall time, the disk park, the blocking reason); the ffmpeg sidecar line; whether the licence is blocking; the volunteer minutes and deadline; the YouTube download line up to the first parenthesis (which clip, not the speed); whether a YouTube sign-in is waiting; the forced fleet job line; whether the credential is rejected; the b-roll failure count.
- On Windows the menu itself is created at the moment of the right-click and destroyed when closed, so a rebuild can never disturb an open menu.

## Balloon notifications raised by the tray part
(source: tray.py)

- YouTube session warnings: raised ONCE each time the YouTube sign-in health moves into "stale" or "expired" (remembered in memory only; a restart may warn again). Text is the YouTube warning line plus " (Tray > Settings > Sign in to YouTube again)". Warning line variants:
  - expired: "⚠ YouTube sign-in has expired: age-restricted clips will fall back to the server";
  - account flagged by YouTube: "⚠ YouTube is refusing your signed-in session: downloads are continuing without it";
  - aged (not used for a long time): "YouTube sign-in has not been used since <date>. Sign in again if you need it";
  - otherwise: "⚠ YouTube sign-in no longer works (Google rotated the session). Sign in again".
- "Another CCSync window is already open. Close it first." whenever a dialog is requested while another companion window is open.
- Every other balloon is listed with the feature that raises it.

## Sign-in dialog
(source: tray.py)

- Opened from the menu's sign-in items and from Settings. Refused with "Another CCSync window is already open. Close it first." if another window is open. If the window cannot be created: "Couldn't open the sign-in window. Restart CCSync and try again."
- Window title: the site notification title with "sign in"; always on top; dark theme.
- Heading "► SIGN IN" and a red rule line.
- Text: "Enter the username and password you use to sign in to <product name>. This verifies that this computer is yours." and "Ask your admin if you do not have one yet."
- Fields "username:" and "password:" (password shown as asterisks). Focus starts on username.
- Buttons CANCEL and SIGN IN (primary). Enter submits; closing the window cancels.
- Errors shown in red under the form: "username and password are both required"; "sign-in failed: <exception>"; the server's error text or "sign-in failed". On a failed sign-in the password field is cleared.
- On success the window closes.

## Sign out
(source: tray.py)

- Signs the computer out (the action itself is outside this part). Reached from Settings.

## YouTube sign-in (browser), cookies file and terms
(source: tray.py)

- **Sign in to YouTube**: finds an installed Edge or Chrome.
  - None found: balloon "No Edge/Chrome found for the one-click sign-in: choose an exported cookies.txt instead", then the cookies file picker opens.
  - Found: balloon "<browser> is opening. Sign in to YouTube in that window; it closes by itself when you're done. Close the window to cancel." A private browser window opens on Google's sign-in; the tray shows the waiting line with a countdown.
  - Crash: "The sign-in window failed unexpectedly. Try Tray > Settings > Use an exported cookies.txt instead."
  - Success: the flow's own message (cookies written).
  - Timed out: "The sign-in did not finish in time. Nothing was saved: try again from Tray > Settings > Sign in to YouTube."
  - Other failures: the flow's own message.
- **Use an exported cookies.txt**: a native file chooser titled "Choose your exported YouTube cookies.txt", filter "cookies.txt (*.txt)" and "All files". Cancel does nothing. The chosen file is validated and installed for the local downloader; the result message is shown as a balloon. If the chooser cannot open: "Couldn't open the file chooser. Set ytdl_cookies_file in config.toml instead." Refused if another window is open.
- **Accept YouTube Terms**: requires a signed-in editor ("Sign in first: the record has to say who accepted these terms."). If already accepted on this computer: "You already accepted the YouTube terms (<text version>) on this computer." Otherwise a native OK/Cancel warning box with the terms title and text (from the attestation module, outside this part) plus "Accepting as: <username>", default button Cancel. OK records acceptance on this computer for this user and shows the result balloon. If the box cannot be shown, nothing is recorded: "Couldn't show the YouTube terms. Open the downloader in the dashboard and accept them there."
- **Stop the YouTube download**: stops local downloads. Balloon "Stopped. The server will download the clips this computer did not finish." On failure: "CCSync could not stop the download. Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN."
- Gates: the YouTube features are offered only when local downloads are enabled for this machine and site (`ytdl_local_downloads` and the site's `youtube_download` feature); signing in additionally needs the site's `youtube_unblock` feature. The YouTube session health is only read when sign-in is offered.

## Update / roll back dialog
(source: tray.py, upgrade.py for the wording)

- Opened from the menu's offer item or Settings. If no offer exists, nothing happens. Refused while another window is open: "Can't update while a CCSync window is open. Close it and try again."
- Title and text depend on the offer: newer: title "... update", text "Update to v<version>? The companion will restart itself.", button UPDATE; older: title "... roll back", text "Roll back to v<version>? That is OLDER than the v<current> on this machine. You would LOSE whatever v<current> fixed. The companion will restart itself.", button ROLL BACK; same rank: title "... switch build", "Switch to v<version>? You are running v<current>. The companion will restart itself.", button SWITCH. The release notes follow in full under "What is new in v<version>:".
- Heading "► UPDATE COMPANION" or "► ROLL BACK COMPANION".
- If any lane is syncing, appended: "A sync is currently running. It will resume automatically after the restart."
- Buttons CANCEL and the action (primary). Enter confirms; closing cancels.
- If the window cannot be created, nothing is installed: "Couldn't open the update window, so nothing was changed. Restart CCSync and try again."
- After confirming, the update is applied (outside this part). If that throws: "Update failed. You're still on v<version>, nothing is broken. Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN."

## "Resolve scripting is down" dialog (unrequested)
(source: tray.py)

- Raised on a timer by the app (not by a click) while Resolve is open but refuses scripting connections; it repeats on the app's own interval.
- If another companion window is open, or the window cannot be built, a balloon with the scripting advice is shown instead.
- Title: notification title with "Resolve scripting is down". Heading "► RESOLVE SCRIPTING IS DOWN".
- Body: the scripting advice (from the Resolve bridge, outside this part: different for a computer that has never connected), then "Until then CCSync can't see your timeline, so it can't warn you about media outside your project folder, attach proxies, or send b-roll, music and YouTube clips to Resolve. Your files and your sync are not affected." then "Save your work first -- nothing here is urgent enough to lose a take over."
- Buttons: "STOP WARNING ME" (secondary; tells the app to stop warning) and "OK" (primary; dismiss). Enter and closing the window both dismiss.

## Remove a project from this computer
(source: tray.py)

- Started from Settings (a REMOVE row per removable project).
- First a balloon: "Checking whether this project's files have reached the server…". The app checks what is still unsynced; if that check throws, the project is treated as blocked with the reason "CCSync could not check whether your work has been uploaded".
- **Blocked**: a type-to-confirm window. Title "... project not ready to remove", heading "► <title>". Body: "'<project>' is NOT ready to be removed." then each reason as a bullet, then "Deleting it now would destroy work that exists nowhere else. Leave CCSync running until this finishes, then try again. If you have to delete it anyway (a dead server, a full disk), type the project's folder name exactly to confirm:" and the folder name. A text field; buttons CANCEL and "DELETE ANYWAY". A wrong entry shows "type exactly: <name>". Confirming removes with the override set.
- **Ready**: a confirmation dialog titled "... remove project": "Remove '<project>' from THIS computer? This unticks the project on the dashboard, stops syncing it here, and deletes the local copy to free disk space." followed by what was checked:
  - upload-only projects: "CCSync has checked every file in this project's folder, apart from its Proxy folders (the server makes those again): each one is on the server at the same size and has not been changed since it went up, and none was left that CCSync does not upload."
  - normal projects: "CCSync has checked this project's video files and its shared project files: all of them have reached the server. Proxy folders are not counted, because the server makes those again."
  - then "Tick the project again any time to sync it back." Button "REMOVE FROM THIS COMPUTER".
- The app re-checks at the moment of deletion. Result balloon: its message, "Remove stopped: <message>", or "Remove failed. Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN."

## Resume proxy download (safety breaker and disk park)
(source: tray.py)

- One action for two different stops.
- If only the disk park is active: dialog "... resume proxy download": "CCSync stopped downloading proxies because: <reason, default 'this drive is nearly full'>. Your uploads never stopped. Proxy download starts again on its own as soon as there is enough room, so you only need this if you have just made space and do not want to wait." Button "RESUME PROXY DOWNLOAD".
- If the breaker tripped: dialog with the editor-facing breaker reason: "CCSync stopped downloading proxies because: <reason>. Only resume once your admin has confirmed the server is healthy. If it is not, resuming will move more of your local proxies into .ccsync-trash (they stay recoverable, but you will not see them in Resolve)." Button "RESUME PROXY DOWNLOAD".
- Result balloon: the app's message, or "Nothing to resume: <message>".

## Stop all syncing / clear the stop
(source: tray.py)

- Started from Settings. Dialog "... stop all syncing": "Stop ALL syncing on this computer? This is stronger than Pause: uploads, proxy downloads AND the shared project files (Syncthing) all stop, and they STAY stopped after a restart until you clear the stop from the tray menu (Clear the sync stop on this computer). Nothing is deleted. Use this when something looks wrong and you want the files to stop moving." Button "STOP ALL SYNCING".
- Confirmed: the stop is recorded with the reason "stopped from the tray on this computer". Balloon: the app's message or "Could not stop syncing: <message>".
- Clearing a local stop: from the menu item or Settings, no confirmation; balloon with the app's message. A fleet stop from the admin cannot be cleared here.

## Grade from the server (drive swap) and back
(source: tray.py)

- Started from Settings. The drive letter is the site's sync drive letter, default "P:".
- To server: dialog "... grade from server": "Point P: at the SERVER's tree so Resolve streams full-resolution originals while you grade? Pause playback first. Frames come over the network, so scrubbing is only as fast as your connection. In Resolve, set Playback > Proxy Handling > Prefer Camera Originals to actually use them. Syncing is not affected. Swap back when you are done: Tray > Settings > FINISH GRADING: P: BACK TO LOCAL PROXIES." Button "SWAP P: TO SERVER".
- Back: dialog "... back to proxies": "Point P: back at this computer's local copy (proxies)? Set Resolve's Playback > Proxy Handling back to Prefer Proxies." Button "SWAP P: BACK".
- If swapping to the server fails because Windows has no stored server login, the Server login dialog opens; cancelling stops there; submitting retries the swap with those credentials (the app stores them so this happens once per computer).
- Result balloon: the message, "Swap stopped: <message>", or "The P: swap failed. Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN."
- **Server login dialog**: title "... server login", heading "► SERVER LOGIN", text "Windows needs your login for <server name or 'the server'> to stream originals. Use the same username and password you sign in to <product> with. It is saved on this computer, so you will only be asked once." Username prefilled with the signed-in editor; focus on password when prefilled. Buttons CANCEL and CONNECT. Error "username and password are both required". If it cannot open: "Couldn't open the login window. Restart CCSync and try again."

## Other actions the tray part provides (used by Settings)
(source: tray.py)

- Scan whole project; Bring an existing project's media in (consolidate); Undo the last clip-path change; Share LUTs; Make proxies now; Stop making proxies; Show proxy progress (opens a window, outside this part); Index b-roll now / Pause / Resume / Cancel (cancel asks for confirmation inside the app) / Show indexing progress; the same five for music; Proxy history (opens a report file the app renders in the default viewer); Open log (opens the log file); Copy diagnostics for your admin; Set up project; each runs in the background with the generic failure balloon.
- **Open the recovery folder**: opens `<sync folder>/.ccsync-trash`. With no sync folder: "CCSync does not know where your sync folder is yet, so there is no recovery folder to open. Open Settings, THIS COMPUTER."
- **Open the folder it is in**: opens the folder of the newest file lane A refuses to upload. "Nothing is being skipped on this computer right now." if none; "CCSync does not know where your sync folder is, so it cannot open the folder holding <name>." if no sync folder.
- File opening uses the system's default opener (Windows shell, `open` on macOS, `xdg-open` elsewhere), with Python environment variables stripped for child processes.

## Advisory sentences the tray part writes (shown in the Settings window)
(source: tray.py)

These are produced here and rendered by Settings (see the Settings section for placement).

- **Lane lines**, one per lane, labelled "Uploads (your footage → server)", "Proxies (server → you)", "Everything else, both ways (audio, graphics, subs)", "Originals you asked for (server → you)". First match wins:
  - drive absent: "<label>: PAUSED (<drive phrase>)";
  - configuration problem: "<label>: NOT SYNCING: <the sentence naming the broken setting, cut to 180 characters>" or "<label>: NOT SYNCING (this computer isn't set up yet)";
  - paused: "<label>: PAUSED";
  - error: "<label>: PROBLEM. <classified error>";
  - "sign in required": "<label>: NOT SYNCING (sign in first)";
  - sync disabled / direct server access: "<label>: not used on this computer (it works straight off the server)";
  - syncing: "<label>: syncing (X of Y · speed/s · ~N min left)" or "<label>: syncing…";
  - lane paused: "<label>: PAUSED";
  - queued: "<label>: N items to go";
  - otherwise "<label>: up to date (<detail>)".
  - When the sync plan is 24 hours or more old: " (sync plan from N days ago: the dashboard has not answered since)" is appended to syncing, queued and up-to-date lines.
- **Classified lane errors** (the raw error stays in the log and diagnostics):
  - drive mounted at wrong place: "<Drive phrase> is mounted at the wrong place, so syncing is paused. Nothing was deleted. See the CCSync window for what to do.";
  - drive gone: "<Drive phrase> is disconnected, so syncing is paused. Plug it back in and it resumes on its own -- nothing was deleted.";
  - empty error: "Something went wrong. <diagnostics route>.";
  - "sync engine" in the text: passed through verbatim;
  - "syncthing not running": "The sync engine (Syncthing) is not running on this computer, so audio, graphics, subtitles and project files are not syncing. Restart this computer, or <diagnostics route>.";
  - "marker missing": "A project folder was deleted on this computer while still ticked. Untick it on the dashboard, or use Tray > Settings > REMOVE '<project>' FROM THIS COMPUTER.";
  - stall watchdog: "This transfer stopped moving and was restarted. If it keeps happening, check the drive is connected.";
  - disk full: "Your disk is full. Free up space and it will resume.";
  - authentication: "The server rejected this computer's login. <diagnostics route>.";
  - network: "Can't reach the server. Check the Tailscale tray icon is connected.";
  - anything else: "Something went wrong. <diagnostics route>."
- "Sync queue: <detail>" (the sequencer's own state, for example which project out of how many) and "Now syncing: <project>".
- **Safety and fault advisories**:
  - breaker: "⛔ PROXY DOWNLOAD STOPPED (safety): <reason>";
  - safety state cannot be saved: "⚠ CCSync cannot save its safety state on this computer (<errors>), so restarting CCSync would silently resume what it stopped. Press COPY DIAGNOSTICS FOR YOUR ADMIN below and send that to your admin before you restart.";
  - disk park: "⚠ Not downloading proxies: <reason>. Uploads are still running; free up space and it starts again on its own";
  - blocked: "⚠ <detail>" (or the detail alone for "nothing ticked"), suppressed when the reason already has its own line (fleet stop, local stop, breaker, disk full, unfiltered folders, clock skew);
  - stop: "⛔ Your administrator stopped syncing for everyone: <reason>" or "⛔ Syncing is STOPPED on this computer: <reason>";
  - trash, only at 1 GB or more: "Recoverable files in <path>: <size> (N files). Copies older than D days are removed automatically" (D default 14);
  - same name, different size: "⚠ N files on the server have the same name but a different size, so your newer version will NOT upload (e.g. <name with both sizes>). Rename yours, or ask your admin to remove the server's copy";
  - future-dated files: "⚠ N files are dated in the future, so they will NOT upload (first: <name>, dated YYYY-MM-DD). A camera clock is set wrong. One a few hours ahead uploads by itself once that time passes. One dated further ahead needs its modified date reset to now (a copy or re-import keeps the date); ask whoever looks after your computers. Fixing the camera clock only helps future recordings";
  - stall in the last 24 hours: "⚠ <Uploading | Proxy download | The fast upload of new clips | Syncing> stopped moving for N min and was restarted. If it keeps happening, check the drive is connected";
  - unfiltered projects: "⚠ N projects are not sharing yet - waiting for their filter list: <up to 3 names>, +M more";
  - shared folder problem: "⚠ <first problem> (and N other shared folders)";
  - project renamed on the server and moved here (not yet relinked): "⚠ A project was renamed on the server and this computer moved its folder to match: '<old>' is now '<new>'. Clips in Resolve may still point at the old path - Tray > Settings > SCAN WHOLE PROJECT relinks them", plus " (N more projects were renamed too)";
  - Syncthing conflict copies: "⚠ N files were edited on two computers at once, so Syncthing kept both copies (e.g. <name>). Nothing was lost: ask your admin which one to keep";
  - reporting failing for 10 or more cycles in a row: credential rejected (401/403): "⚠ The server rejected this computer's sign-in, so your admin cannot see whether you are syncing. Sign in again: Tray > Settings > SIGN IN"; never succeeded: "⚠ The dashboard has never accepted a report from this computer. Your work may not be visible to your admin. Copy diagnostics for them"; otherwise "⚠ The dashboard has not accepted a report for <duration>, so your admin cannot see whether this computer is syncing";
  - clock off by 60 seconds or more: "⚠ This computer's clock is <a phrase from the reporter module, for example how far ahead or behind> the server's. Sync will not work correctly until it is fixed";
  - clips skipped (for 30 minutes) in the Resolve check: "⚠ N clips skipped for now and still not syncing - Settings > SCAN WHOLE PROJECT offers them again";
  - crash reports saved: "⚠ A background task failed on this computer (N reports saved). Copy diagnostics for your admin";
  - update failed 8 times: "⚠ CCSync could not install the update to vX N times, so it has stopped trying. <diagnostics route>";
  - rolled back after crashes: "⚠ The vX update kept crashing, so CCSync went back to the previous version. Your admin has been told";
  - a background thread restarted 3 or more times in an hour: "⚠ CCSync keeps restarting its sync engine (N times in the last hour), so syncing is stopping and starting. Copy diagnostics for your admin".
- **Proxy lines**: "Proxies waiting: <reason>" when not encoding for a known reason; "Making proxies… N left (stops when you're back)" and "About <duration> to go at this rate" while encoding; otherwise "N clips have no proxy: other editors can't see them"; "N BRAW clips need the Blackmagic Proxy Generator"; "Made N proxies today · <source size> → <proxy size> · M failed".
- **Indexing lines** (b-roll with unit "clip", music with unit "track"): the batch's warning first (for example a graphics memory refusal); "Downloading the <label> indexing model… P %"; "Indexing <label>… D of T (stops when you're back)" (the tail omitted in foreground mode); "<Label> indexing waits until you're away: N <unit>s queued" (while the user is active or Resolve is open); "<Label> indexing paused: N <unit>s left"; "Uploading indexed <label> is paused: N left" or "Uploading indexed <label>… N <unit>s left"; the failure line.
- **YouTube downloader warnings**: "⚠ YouTube downloads on this computer may start failing: the downloader is N days old and could not update itself" (or "is out of date"); "⚠ YouTube downloads on this computer are running on the server: the downloader could not be installed here".

## The Settings window: frame and behaviour
(source: settings_window.py)

- Opened from the tray's "Settings…" item (also reopened by some of its own buttons). Refused with "Another CCSync window is already open. Close it first." if another companion window is open.
- Title: the site notification title with "SETTINGS". Default size 720 x 640 pixels, minimum 560 x 420, resizable, not forced on top. Dark theme. Escape or the window's close button closes it.
- Layout: a strip of **jump buttons** across the top, one per section, which stays put while the body scrolls; the strip wraps onto extra rows when the window is too narrow. Clicking a jump button scrolls that section's header to the top (it is the only button that does not close the window).
- The body is a scrollable list of sections. Each section has a header "[ TITLE ]" and a rule line, then rows. Rows are either text lines (normal, muted grey, or red "warning") or buttons. Text wraps to the window width (660 pixels at the default size, never under 240). The mouse wheel scrolls.
- **Refresh**: every 2 seconds the window re-reads the same snapshot the tray uses and redraws only if something visible changed, but at least every 30 seconds regardless; the scroll position is kept across redraws.
- **Every button closes the window first**, then runs its action in the background. Buttons that change a setting reopen the window afterwards.
- **HELP moves to the top**: whenever any row in the window is a red warning line, the HELP section is drawn first instead of last.
- If building the window fails part-way, it is torn down rather than left frozen on screen.

## Settings > THIS COMPUTER
(source: settings_window.py)

- Line "Computer name: <host name>".
- Line "Current role: REMOTE EDITOR" or "Current role: WIRED TO THE SERVER" (the role this running process started with).
- Button "REMOTE EDITOR" (with "  (current)" when it is the current role), with the muted note "syncs projects to this computer's own drive".
  - Opens a type-to-confirm window titled "... switch to REMOTE EDITOR": "Switch this computer to REMOTE EDITOR? A REMOTE EDITOR computer syncs projects DOWN to its own drive. If this computer's synced folder is actually the live server share, switching will start DELETING files from it the moment a proxy download runs, because proxy download syncs the server DOWN onto whatever this computer calls its own copy. If you are not sure this computer has its own separate copy of the project tree, do not do this. Type "REMOTE" to confirm:". The word REMOTE must be typed exactly; the confirm button is the shared typed-confirmation window's "DELETE ANYWAY"; CANCEL cancels.
  - Shown even when it is already the current role, and the confirmation is asked again in that case.
- Button "WIRED TO THE SERVER" (with "  (current)"), with the note "works directly off the server share, so nothing is synced to it".
  - Opens a yes/no dialog titled "... switch to WIRED TO THE SERVER": "Set this computer to WIRED TO THE SERVER? A wired computer works straight off the server share, so CCSync will sync NOTHING to it: no upload, no proxy download, no folder sync. Your admin will not be able to tick projects for it either. If this laptop keeps its own copy of the projects, this is not the setting you want." Button "WIRED TO THE SERVER".
- Either confirmed choice writes `mode` (`editor` or `base`) into config.toml. Balloon "This computer is now set to <ROLE>. Takes effect the next time CCSync starts -- open Settings to restart now." or, if the write cannot be read back, "Couldn't save that -- see the log." The running process does not change until restarted.
- Red line "The role above was changed and takes effect when CCSync next starts." while the file's `mode` differs from the running one.
- Line: the identity line ("Signed in as <user>" / "NOT SIGNED IN").
- When this computer's id file (`machine.json`) exists but cannot be read: red line "⚠ CCSync cannot read this computer's id file, so the server cannot recognise this computer again if you rename it. Syncing is not affected.", button "GIVE THIS COMPUTER A NEW ID" and note "  the unreadable file is kept beside the new one".
  - The button asks: title "... this computer's id", "CCSync cannot read this computer's id file, so the server cannot recognise this computer again if you rename it. CCSync will save a new id and keep the unreadable file beside it, so nothing in it is lost. Your syncing and your sign-in are not affected. If your admin is still looking at the old file, wait for them before doing this." Button "GIVE IT A NEW ID".
  - Results: "This computer has a new id. It is reported from the next check in." / "CCSync did not change this computer's id. <diagnostics route>." / "CCSync could not repair this computer's id file. <diagnostics route>."
- When the dashboard is rejecting this computer's credential (10 or more failed reports in a row, last answer HTTP 401 or 403): red line "⚠ The server rejected this computer's sign-in, so your admin cannot see whether you are syncing." and button "SIGN IN AGAIN…" (uses the app's re-sign-in if it has one, else the Sign-in dialog).
- Button "SIGN OUT" when signed in, otherwise "SIGN IN…".
- Button "RESTART CCSYNC NOW" (always present). Restarts the companion by relaunching itself. Refused with "Can't restart while a CCSync window is open or media is being copied in. Try again once it's done." when the app says stopping now would kill work. A failed relaunch is only logged.
- Line "Dashboard address: <configured dashboard_url>" (only when set), followed by the address check result: a red "⚠ <sentence>" for an error, or a muted note for a warning (the sentences come from the configuration module, outside this part; for example plain http to a public address). Addresses that need a DNS lookup are checked in the background and the result is cached for 5 minutes.
- **PRIVACY** rows: muted line "PRIVACY: what this computer tells the dashboard. Sync is not affected." then four check rows:
  - "[x] The name of the open Resolve project"
  - "[x] The list of media files on this computer"
  - "[x] The Resolve bin structure"
  - "[x] How long since the keyboard or mouse was used"
  - Each is a button showing `[x]` (on) or `[ ]` (off); clicking flips it, writes the matching `report_*` key in config.toml and applies it to the running process immediately (the next report already obeys it). Balloon "This computer will report <item> again from its next report." or "This computer will stop reporting <item>. The dashboard forgets what it held on the next report. Sync is not affected." Failure: "Couldn't save that - see the log."
  - A category the site has switched off for everyone shows as a muted line "  [ ] <label>  (Turned off for everyone by your administrator)" and cannot be changed here.
  - "The Resolve bin structure" shows as a muted "  [ ] ...  (Off while the project name is off)" when the project-name switch is off locally or by the site.

## Settings > SYNCING
(source: settings_window.py, tray.py)

- One lane line per lane (see "Lane lines" above).
- "Sync queue: ..." and "Now syncing: <project>" lines when present.
- When the licence (EULA) is what blocks sync: red line "⚠ <the refusal sentence without its route>. Nothing syncs until it is accepted." and button "READ AND ACCEPT THE LICENCE" (opens the licence dialog).
- **Advisories**, ranked and collapsed:
  - Every advisory sentence from the tray part is gathered and given a rank. BLOCKING (drawn red): stop, breaker, safety state cannot be saved, unfiltered projects, report failures, clock skew, stall, disk park, blocked summary. WARNING (normal colour): same-name different-size, future-dated files, Syncthing conflicts, shared folder problems, renamed project, crash reports, repeated restarts, failed update, reverted update. INFO (muted): clips skipped for now, recoverable trash. The blocked summary is demoted to INFO when the reason is "nothing ticked".
  - Identical sentences are merged into one with " (xN)".
  - At most 6 are shown; the rest are summarised as "and N more" with a "SHOW ALL" button; after SHOW ALL, a "SHOW FEWER" button. The choice is remembered for the life of the process.
- When the sync drive went away with work still owed (red): "<Drive> is not answering with <owed> still to go - reconnect it or restart this computer to finish syncing" / "<Drive> is mounted at the wrong place with <owed> still to go - eject it, delete the leftover empty folder, then plug it back in" / "<Drive> was disconnected with <owed> still to go - plug it back in to finish syncing".
- While a drive reminder episode is open: buttons "REMIND ME LATER" (mutes the reminder balloons for 120 minutes: "CCSync will remind you about this drive again in 120 minutes.") and "STOP REMINDING ME ABOUT THIS DRIVE" (mutes them until the drive returns: "CCSync will stop reminding you about this drive. Your unfinished syncing is still waiting for it, and Settings still says so."). Once muted, a muted line "Reminders about this drive are off until it is plugged back in." replaces the buttons. If nothing is left to mute: "There is nothing to remind you about now." Failure: "CCSync could not do that. <diagnostics route>." The warning line and the owed record are not affected.
- The YouTube download line, when a download runs.
- Button "RESUME PROXY DOWNLOAD" while the breaker has tripped or the disk park is active (same dialogs as the tray item).
- For up to 5 project folders that are missing from where CCSync expects them: red line "'<name>' is not where CCSync expects it - nothing in it is reaching the server"; if the folder was found elsewhere on this computer, a muted "  found at <path>" and a button "PUT '<name>' BACK WHERE CCSYNC EXPECTS IT" (moves it back; refuses if the target exists; deletes nothing; result balloon from the app, or "CCSync could not move that folder back. See the log.").
- Red line when project folders on this computer are in no sync plan: "N project folders on this computer are in no sync plan (X.X GB). Nothing syncs them and CCSync will not delete them". No button.
- When finished indexing staging holds disk: red line "Finished indexing staging is holding X.X GB on this computer" and button "CLEAR FINISHED STAGING" (deletes only finished batches' staging; result balloon from the app, or "CCSync could not clear the staging folders. See the log.").
- Button "CLEAR THE SYNC STOP ON THIS COMPUTER" while a local stop is active (not for a fleet stop).
- Proxy lines (see "Proxy lines"), then:
  - while making proxies: buttons "STOP MAKING PROXIES" and "SHOW PROXY PROGRESS";
  - otherwise, when clips lack proxies and this computer can make them: "MAKE PROXIES NOW (don't wait until I'm away)";
  - when this computer can make proxies or has made any: "PROXIES THIS COMPUTER HAS MADE…" (opens the history report).
- B-roll indexing lines, then while a batch exists: "RESUME B-ROLL INDEXING" (when paused) or, when not paused, "INDEX B-ROLL NOW (don't wait until I'm away)" (only while it is waiting for the user to be away or Resolve to close) and "PAUSE B-ROLL INDEXING"; then "SHOW B-ROLL INDEXING PROGRESS" and "CANCEL THE B-ROLL BATCH…".
- The same five for music: "RESUME MUSIC INDEXING", "INDEX MUSIC NOW (don't wait until I'm away)", "PAUSE MUSIC INDEXING", "SHOW MUSIC INDEXING PROGRESS", "CANCEL THE MUSIC BATCH…".

## Settings > YOUTUBE
(source: settings_window.py, tray.py)

- Present only when local YouTube downloads are enabled or YouTube sign-in is offered (see the gates above).
- First, red warnings when they apply: the downloader-age/install line and the ffmpeg sidecar line.
- When local downloads are enabled: button "Accept YouTube Terms ✓" (already accepted) or "Accept YouTube Terms…".
- When sign-in is offered:
  - a red YouTube warning line when the session is stale or expired;
  - button "Sign in to YouTube again (session expired)…" (stale/expired), "YouTube: signed in ✓ (sign in again…)" (working), or "Sign in to YouTube (for downloads)…" (never);
  - button "Use an exported cookies.txt…".

## Settings > PROJECTS ON THIS COMPUTER
(source: settings_window.py)

- Present only when the sync engine can list this computer's projects.
- With none: "No projects are ticked for this computer yet: tick them on the dashboard".
- Per project: "<slug> - <full sync | upload only (no proxy download)>: <state>", then a muted line naming each channel's state ("upload ..., proxy download ..., folder sync ..."), then a muted detail line when there is one.
- State words: idle = "up to date", syncing = "syncing now", queued = "waiting its turn", paused = "paused", error = "there is a problem", off/skipped = "not synced to this computer"; anything else is shown as is, or "not known".

## Settings > RESOLVE
(source: settings_window.py)

- Present only when the companion holds Resolve health data.
- "Connected to Resolve", or red "Not connected to Resolve right now".
- Red "Resolve has not answered <call> for Ns. Nothing is wrong with your sync; Resolve itself is busy" when a call has been in flight over 20 seconds.
- "Project open: <name>" or "No project is open in Resolve".
- Counts, each shown only when non-zero AND a scan time is known, all red:
  - "N clips are stored outside your synced folder, so nothing is backing them up";
  - "N clips in this project are offline";
  - "N clips point at a drive letter this computer does not have";
  - "N clips were left alone: their path is not one CCSync may rewrite".
  - After the first of them, one button "SCAN WHOLE PROJECT".
- For up to 3 other Resolve projects (not open) whose clips exist only on this computer: red "N clips in '<project>' are only on this computer. Open that project in Resolve and press FIX ALL"; beyond 3: "...and N more projects".
- "Proxies attached to clips: N" plus ", N clips re-read after the file changed" and ", N could not be attached: <why>" (red when any failed).
- Red "N clips still on the preview copy: the editing proxy did not arrive (<why>). Send them to Resolve again to ask for it."
- Red "N proxies skipped: this disk is low on space" / "...: this computer's proxy limit was reached" / "...: the list was too long to finish".
- The stills instruction line from the Resolve health data (red unless it says all is well).
- Muted "Checked <just now | N min ago | N h ago | N days ago>" (under 90 s, under 90 min, under 48 h, otherwise days).
- Button "UNDO LAST FIX" when the last FIX ALL can be undone.

## Settings > FLEET JOBS
(source: settings_window.py)

- Status half (present only when the job runner reports status):
  - "Taking fleet work" or "Not taking work: <reason>".
  - While a job runs: "Running a fleet job for the team: <kind> on <file> (started <age>)", a muted line with the forced reason if an admin forced it, and button "STOP THIS JOB". Stopping returns the job to the queue: "Stopping the fleet job. It goes back to the queue for another computer." / "There is no fleet job running now." / "This build cannot stop a fleet job." / "CCSync could not stop that job. <diagnostics route>."
  - Up to 10 recent jobs, muted: "  <kind> on <file>: <outcome, default finished>, <age> (<error>)".
- Settings half (always present; read from config.toml on disk):
  - Button "[x] Let the fleet use this computer" / "[ ] ...", writes `jobs_enabled` (default on). Balloons: "This computer will take work for the fleet again. Takes effect the next time CCSync starts." / "This computer will stop taking work for the fleet. Takes effect the next time CCSync starts." Muted note: "  Fleet work runs only while you are away from this computer."
  - One check row per known job kind, writing `jobs_kinds`: "Transcribe audio (uses the graphics card)" (whisper), "Make small preview copies of video" (proxy-480p), "Pull the audio out of video" (audio-extract), "Draw audio waveforms" (peaks); an unknown kind shows its raw name. An empty list means every kind; when all are ticked the value written is empty. Unticking the last ticked kind is refused: "That is the last kind of work this computer takes. Untick 'Let the fleet use this computer' instead." Balloon "This computer will <no longer do this | now do this> for the fleet: <kind label>. Takes effect the next time CCSync starts."
  - Button "LEND THIS COMPUTER FOR N minutes AT A TIME (click for M)", cycling 15, 30, 60, 120 minutes (an unknown value goes to 15), writing `jobs_volunteer_minutes` (default 30). Balloon "One click of 'Take fleet jobs now' will lend this computer for M minutes. Takes effect the next time CCSync starts."
  - Red line "The settings above were changed and take effect when CCSync next starts." while any of the three differ from the running values.
  - The Timeline Cards agent switch is deliberately not offered here.

## Settings > ADVANCED
(source: settings_window.py)

- "SCAN WHOLE PROJECT".
- "BRING AN EXISTING PROJECT'S MEDIA INTO THE SYNCED FOLDER…".
- "UNDO THE LAST CLIP-PATH CHANGE CCSYNC MADE…".
- When FIX ALL is in rehearsal mode (`fixer_dry_run` on): the popup's rehearsal warning line (red; text in the popup section) and button "TURN REHEARSAL OFF", which writes `fixer_dry_run = false`, takes effect at once, and says "FIX ALL will copy files in again." (or "Couldn't save that - see the log.").
- When the media drive can be repaired and either the drive is mapped somewhere else or not at all, or Resolve reports clips on a drive letter this computer lacks: red line "Resolve is looking for your media on P: but P: is not pointing at your synced folder, so clips will show offline. Your uploads and downloads are still running." and button "REPAIR P: NOW" (a mapping owned by someone else is refused by the app with what it points at; result balloon from the app, or "CCSync could not repair the drive mapping. <diagnostics route>.").
- When grading from the server is available on this computer: "GRADE FROM SERVER ORIGINALS (SWAP P:)…" or, while swapped, "FINISH GRADING: P: BACK TO LOCAL PROXIES".
- "STOP ALL SYNCING ON THIS COMPUTER…" unless a stop is already active.
- One "REMOVE '<folder>' FROM THIS COMPUTER…" button per removable project, with " (upload only)" before "FROM" for upload-only ticks.

## Settings > HELP
(source: settings_window.py)

- "COPY DIAGNOSTICS FOR YOUR ADMIN" (the diagnostics bundle is built outside this part).
- "OPEN LOG".
- When a dashboard address is configured: "HOW CC SYNC WORKS" (opens `<dashboard_url>/help` in the browser) and "WHAT DO THESE MEAN?" (opens `<dashboard_url>/help#glossary`). With no address: "This computer does not know where your dashboard is, so it cannot open the help page." No browser: "Couldn't open a browser. The help page is at <url>".
- The update/roll back offer button (same label and dialog as the tray item) when an offer exists.
- "OPEN-SOURCE LICENCES": opens the bundled `THIRD_PARTY_LICENSES.txt`; if this build has none: "This copy of CCSync does not carry the open-source licence texts. Your admin can send them, or see Help, Legal on the dashboard."
- Muted "Support: <site support contact>".
- Muted "ccsync-companion v<version>".

## "Media outside project tree" window (the FIX ALL popup)
(source: popup.py)

This window appears when the companion finds clips in the open Resolve timeline/project whose files live outside the synced folder (the decision to show it, and its timing, are outside this part). One window per batch.

- **Rows**: one row per unique source file. Several timeline uses of the same file (compared case-insensitively on a normalised path) become one row, and fixing it relinks every use.
- **Suggested destination per row**, first that applies:
  1. the destination the dashboard has remembered for that Resolve project (matched case-insensitively by project name);
  2. a project folder in the tree whose name matches the open Resolve project;
  3. the configured `active_project` prefix;
  4. the tree root.
  The exact suggested sub-folder comes from the fixer (outside this part); with no matched project it lands at the tree root, under the editor's own folder.
- Window: title is the site notification title; always on top; app icon; dark theme.
- Header "► MEDIA OUTSIDE PROJECT TREE", rule line, then: "N timeline clips live outside <sync folder> and will NOT sync. Pick a destination. FIX ALL copies them in and relinks Resolve. Your original file is left exactly where it is. Nothing is moved or deleted."
- When FIX ALL is in rehearsal mode (`fixer_dry_run`): red bold "FIX ALL is in rehearsal mode on this computer and will copy nothing."
- Buttons at the top (so they stay reachable with many rows):
  - "SKIP FOR 30 MINUTES": every row is skipped for 30 minutes (the skip ledger is outside this part) and the window closes. Ignored while a copy runs.
  - "FIX ALL" (primary): starts the copy.
  - "RETRY FAILED" (primary): hidden until a run leaves failed, skipped or part-way rows; re-runs only those rows with the same destinations.
- **Space line** (above the progress area): "N clips, X GB in total. This computer has Y GB free." In red, with " That is not much room. Everything copied in is also uploaded to the server." when the batch exceeds 90 % of the free space. Shown only when sizes can be measured; never blocks.
- **Cloud placeholder warning** (amber): "N of M files are online-only in your cloud drive and have to download before they can be copied. That happens automatically, but it can be slow, so the bar will sit at 0% for those while they download." (Google Drive online-only, OneDrive Files On-Demand and similar; detection is in the fixer.)
- **Row list** (scrolls; mouse wheel on Windows/macOS, buttons 4/5 on Linux): per row the clip name in bold ("▌ <name>"), the full source path in grey, "  dest:" and an editable drop-down of destination folders (built from that row's project prefix and the editor's name; free text allowed), and a red line under it when the chosen destination is outside every project: "This folder is outside every project and will not sync. Pick one under Projects to share the copy." The red line updates as the editor picks or types. It warns only; it does not block.
  - The drop-down is as wide as its longest option, between 52 and 100 characters, scrolled to show the end of the path.
  - Names and paths wrap at 620 pixels.
- Window sizing: at most 80 % of screen height and 90 % of screen width; only the row list shrinks (never below 120 pixels high).
- **FIX ALL run**:
  - The two top buttons are disabled; the status line reads "Copying N files in. Your originals stay exactly where they are. Nothing is moved or deleted." (plus the cloud warning if relevant).
  - Before each file, the open Resolve project is checked: a row that was seen in a different project than the one now open is refused with "Not copied. This clip belongs to the Resolve project "<A>", but "<B>" is open now. Open "<A>" and press FIX ALL again." Unknown names never refuse.
  - Progress area: a per-file line and bar, and a batch line and bar, updated 4 times a second.
    - File line: `Copying "<name>": 4.1 GB of 12.7 GB · 33 MB/s · ~4 min left`; while a cloud placeholder downloads: `Waiting for your cloud drive to download "<name>" (<size>). This can take a while`; in rehearsal: `Checking "<name>"`.
    - Speed is measured over the last 6 seconds. Time left: "almost done", "~N sec left", "~N min left", "~Nh Mm left".
    - Batch line: "File I of N: X GB of Y GB done" (or just "File I of N"). In rehearsal the batch bar counts clips instead of bytes.
  - Controls during a run:
    - "STOP AFTER THIS FILE": finishes the current file, then stops. Status: "Stopping after the current file finishes. Please wait."
    - "SKIP THIS FILE": abandons the current file (its partial copy is deleted, nothing relinked) and carries on. Status: "Skipping the file being copied now. The half-copied file is deleted and the rest of the list carries on."
    - "CANCEL ALL": abandons the current file and the rest. Status: "Cancelling. The file being copied now is abandoned and its half-copied file deleted. Everything already copied in stays." All three buttons are disabled.
    - The window's close button during a run acts as CANCEL ALL and does not close the window; it closes once the copy has really stopped.
  - The companion records that a copy is in flight (file index, total, name) for Quit's warning.
- **When the run ends**:
  - All succeeded (no failures, skips, part-way relinks, stop or rehearsal): the window closes and a notice window opens titled "... media copied in" with: "Fixed N of M, copied X.X GB" (decimal gigabytes), a line "Will not sync: <names>. Its/Their copy/copies are outside every project, so it/they stay on this computer and never reach(es) the server or other editors." for copies at the tree root, and "To undo: Settings, RESOLVE, [ UNDO LAST FIX ]" when anything was relinked. Copies that reused an earlier run's copy are not counted in the size.
  - Otherwise the window stays open, FIX ALL and SKIP are re-enabled, RETRY FAILED appears if anything is retryable, and the status area shows a headline and blocks:
    - headline: "N of M copied in, P stopped part way, S skipped by you, F failed", prefixed "Stopped: " and suffixed ", K left alone" when stopped early; in rehearsal: "REHEARSAL: nothing was copied. N files would be copied into <folder>." (plus " Stopped: K left alone.");
    - rehearsal: up to 12 lines "<name> would be copied to <path>", then "… and N more (see Tray > Settings > OPEN LOG)", then "FIX ALL is in rehearsal mode on this computer and will copy nothing. Turn it off in Settings, ADVANCED, [ TURN REHEARSAL OFF ].";
    - part-way relinks: up to 12 lines "■ <name>: <message>", then "Press RETRY FAILED to finish repointing them. The copy is not made again.";
    - skipped: "You skipped: <up to 6 names>. Nothing was copied in or relinked for them, and the half-copied files were deleted. Press RETRY FAILED to try them again." and, if a partial copy could not be deleted, "⚠ CCSync could NOT delete the N half-copied files: <paths>. Please delete them by hand.";
    - failures: up to 12 lines "✗ <name>: <reason>", "… and N more (see Tray > Settings > OPEN LOG)", and for cloud placeholders "These are online-only cloud files. Make them available offline in your cloud drive, then press RETRY FAILED.";
    - when nothing failed or was skipped (only stopped): "Nothing was moved or deleted.";
    - the "Will not sync" line and the undo pointer as above.
  - Skipping a single file never adds it to the 30-minute skip list.
- **No display**: if the window cannot be created, every row is logged, all rows are skipped for 30 minutes with the reason recorded as "headless", and nothing else happens.

## Copy progress window (consolidate)
(source: popup.py)

A two-bar window shown while the companion copies a whole project's media into the synced folder ("Bring an existing project's media in"); the caller that opens it and its title/subtitle are outside this part.

- Always on top; heading "► <title>", optional subtitle.
- Same file line, batch line and bars as FIX ALL; a phase with its own headline (for example an upload phase) shows the headline instead of the file line. If the worker publishes its own speed or time left, those are used.
- In rehearsal mode the file bar stays at 0 and the batch bar counts clips.
- Buttons "STOP AFTER THIS FILE" ("Stopping after the current file finishes…"), "SKIP THIS FILE" ("Skipping the file being copied now. Carrying on with the rest…"), "CANCEL ALL" ("Cancelling. The half-copied file is deleted; everything already copied in stays…"). The close button acts as CANCEL ALL.
- Refreshes 4 times a second; closes itself when the work finishes.
- Without a display the work still runs, and progress is written to the log every 5 seconds.

## Background work progress window (proxies, b-roll indexing, music indexing)
(source: popup.py)

A window that watches a long background job without owning it; opened from the "SHOW ... PROGRESS" buttons. The job's own title, subtitle and wording come from outside this part.

- Not forced on top. Heading "► <title>", optional subtitle.
- Three labelled bars, top to bottom: what is being fetched (for example an indexing model download), the current item ("<label> - P%"), and overall ("D of T clips · F failed · ~12 min left", or "estimating…" until at least 2 items are done; the overall count uses "track" for music).
  - The time left is a smoothed average of seconds per item (weighting 0.4 on the newest).
  - A headline that already contains a percentage is not given a second one.
- A note line (the job's note, or its phase), and in red up to 5 named failures "✗ <name>: <reason>" plus "and N more".
- Buttons PAUSE, RESUME, START NOW, CANCEL (CANCEL primary). Each is enabled only when the job says that action is possible; clicking runs it in the background.
- Polls the job 2.5 times a second (every 400 ms).
- The close button only closes the window; the job carries on and the window can be reopened.
- When the job reports finished, the window closes itself 4 seconds later.
- Only one copy of a given progress window opens at a time; with no display, it silently does not open.

## Generic confirm and notice dialogs
(source: popup.py)

- **Confirm dialog** (used by remove project, resume proxy download, stop all syncing, grade swap, role change, new id, and others): title, heading "► <title>", body text wrapped at 520 pixels, buttons CANCEL (or a caller-chosen label) and the action button. Always on top. Escape cancels; focus starts on CANCEL; Return is deliberately not bound. Closing the window cancels. If it cannot be shown, the answer is "cancel".
- **Notice dialog**: title, heading, body, one OK button. Return and Escape both close it. Always on top. Failure to show is only logged.

## Licence (EULA) dialog
(source: popup.py, eula.py, assets/EULA.md)

- Title and introduction are supplied by the caller (outside this part). Heading "► <title>", the introduction, then the full licence text in a scrolling, read-only text box (84 characters wide, 24 lines high).
- Buttons DECLINE and ACCEPT (or a caller-chosen label). ACCEPT is not focused by default and there is no Return shortcut. Closing the window declines. If the dialog cannot be shown, the answer is "decline".
- The text shown is the bundled `assets/EULA.md` verbatim (see the licence section).

## "Choose from this computer…" picker (b-roll ingest)
(source: popup.py)

- Opened on request from the companion's local web server (the b-roll ingest page; outside this part).
- Two kinds: a folder chooser titled "Choose a folder of clips to index" (folder must exist), or a multi-file chooser titled "Choose clips to index". Always on top.
- A folder is walked recursively in sorted order; only video files with the ingest extensions are kept (extension list outside this part), each with its size and sub-folder path. At most 2,000 files are offered; beyond that only the first 2,000.
- Only one picker can be open at a time; a second request joins the first and gets its answer (a "files" request that joins an open folder picker gets the folder's clips).
- If another companion window is open, the picker refuses with "Another CCSync window is open on this computer. Close it, then choose again."
- The requester waits up to 300 seconds. On timeout, on Windows the picker is closed (as if cancelled) and given 5 seconds to go; on macOS it cannot be closed from outside and stays up. A choice made after the requester stopped waiting is discarded (logged).

## Tray icon platform behaviour (Windows, macOS, Linux)
(source: tray_native.py)

- **Windows**:
  - The icon lives in the notification area. **Right-click, left-click and left double-click all open the same menu**; there is no separate left-click action.
  - The menu opens at the mouse pointer, aligned bottom-right. If the click lands on the taskbar itself (for example an auto-hide taskbar), the menu is moved so it clears the taskbar on whichever edge the taskbar sits (bottom, top, left, right).
  - Menu labels: an ampersand is shown literally and a tab becomes a space. Greyed rows are disabled; rows with a check state show a check mark.
  - Leading, trailing and doubled separators are removed, so an empty group never leaves a stray divider.
  - The menu is created at the moment it opens and destroyed when it closes.
  - Tooltip: up to 127 characters.
  - Balloons: the text is shortened to 250 characters by cutting the middle and keeping the last sentence (up to half the space), joined by " ... "; when shortened, the full text is written to the log. The title is cut to 60 characters (default title is the icon's name). Balloons use no icon type.
  - Balloons raised before the icon is registered are held (up to the 5 most recent; older ones are dropped with a log line) and shown as soon as the icon appears. Every dropped or held one is logged.
  - First registration at start-up: up to 12 attempts with waits of 0.5, 1, 2, 4, 8, then 15 seconds (about 1 minute 46 seconds in total), each failure logged. Giving up is the terminal failure described in "The tray icon: start-up".
  - When Explorer restarts (the "TaskbarCreated" broadcast), the icon is re-added with up to 6 attempts 0.5 seconds apart; if that fails it retries once a minute, forever, until it succeeds ("the CCSync tray icon is back" in the log).
  - Diagnostics: a click that waited 150 ms or more before the menu appeared, or a menu that took 150 ms or more to build, is logged with any Resolve call in flight and garbage-collector counts. A menu that fails to open (as opposed to being dismissed) is logged as a warning. A broken internal structure size is logged as an error ("the icon will probably not appear").
  - Quit: removes the icon and ends the tray within 5 seconds.
- **macOS**:
  - The icon is a menu bar item; clicking it opens the menu (standard macOS behaviour).
  - The image is drawn at 20 x 20 points.
  - All icon, tooltip and menu changes are applied on the main thread. If the menu is open when a rebuild arrives, the rebuild waits until the menu closes.
  - Notifications are shown through `osascript` "display notification" with the title (default the icon's name); line breaks and tabs are collapsed to single spaces first; a 10-second time limit; failures only logged. Because the companion is not a signed app bundle, it does not use the system notification framework.
  - Quit removes the menu bar item.
- **Linux and anything else**: no tray at all. A warning is logged once ("the companion will run with no tray icon"); notifications are only written to the log. Sync continues.

## Window dispatch: where windows are built and when they can be refused
(source: ui_dispatch.py)

- **Windows (and Linux)**: every window is built and run on the thread that asked for it.
- **macOS**: every window is built on the main thread. The main thread runs a hidden, never-shown window and checks for window requests every 50 ms; the requester waits until the window closes and gets its answer.
- **Only one companion window at a time**: nearly every dialog, Settings and the picker first try to take a single "window open" lock and refuse with a balloon if it is taken (exact refusal wording is listed with each window). The lock is the callers' rule; this module only carries the request.
- **Shutdown**: on macOS, any window still open when the companion shuts down is closed from the shutdown path (logged as an error naming the window); requests that arrive after shutdown starts are refused at once and the caller takes its safe default (a confirm answers "cancel", the FIX ALL popup falls back to its no-display behaviour). If the main thread will not accept the close within 5 seconds, that is logged.
- **Window memory housekeeping**: every window's underlying interpreter is kept alive until the thread that built it can free it. A window whose resources cannot be freed stays in memory (about 1.8 MB each); when 8 or more are held with their windows gone, an error naming them is logged.
- **DEV ONLY / diagnostic**: environment variable `CCSYNC_TK_AUDIT` (any non-empty value) logs, after every window closes, a full list of open window interpreters, which thread built each, and what still references them.

## Look and feel shared by every window
(source: theme.py)

- Dark "terminal" style: background #0a0a0d, panels #101014, input fields #16161c, accent red #ff2140 (hover #ff5c73, dim red #7c1322 for rules), green #2bff88, amber #ffb02e, text #e8e8ea, secondary text #8a8a96, input outlines #6f6f7a. The tray's red is RGB (255, 33, 64).
- Font: Consolas on Windows, Menlo on macOS, DejaVu Sans Mono elsewhere.
- Every heading starts with "►"; every section has a 72-character "─" rule line under its heading.
- **Buttons** are flat text drawn as "[ LABEL ]": primary buttons in bold red, secondary in grey; both turn bright red under the mouse; a hand cursor. Keyboard: Tab reaches each button and shows a thin focus outline; Enter (including the numeric keypad Enter) and Space press the focused button; a disabled button ignores them. Pressing Enter on a focused button does not also trigger the window's own Enter shortcut.
- Drop-downs and progress bars use the same dark colours (progress bars 10 pixels thick, red on dark).
- **Window icon**: every window's title bar (and the Windows taskbar button) shows the product mark tinted brand red at 128 x 128. Fallback: the pre-coloured `icon.png`; failing that, no icon. Never fatal.
- **Brand mark selection** (shared by the tray icon and every window icon), first that resolves to a real file:
  1. environment variable `CCSYNC_BRAND_LOGO`: a bare file name is looked up in the companion's assets folder (for example `ccsync_mark.png`); anything with a slash or backslash is a path to any white-on-transparent PNG. A name that does not exist is ignored. This per-machine override beats the site.
  2. the site manifest's `brand_logo` value (same rules), so a whole fleet can rebrand without reinstalling.
  3. the default `cc_mark_white.png` (the Creators Club mark).
  - The logo must be white on transparent; a coloured logo comes out as a solid tinted shape.
- **Windows app identity** (Windows only, at start-up and before the first window): the process declares the app id `com.ccsync.companion`, so the taskbar shows the window's own icon instead of the executable's. It also writes, per user, `HKEY_CURRENT_USER\Software\Classes\AppUserModelId\com.ccsync.companion` with `DisplayName` = the site's product name (default "CC Sync") and `IconUri` = `~/.ccsync/app_icon.png`, a 128-pixel red-tinted copy of the mark that it writes (and rewrites only if it changed). This is what Windows shows as the header and icon of every balloon. Failures are silent.

## Licence agreement (EULA) acceptance gate
(source: eula.py, popup.py, assets/EULA.md; the scheduling lives in app.py, outside this part, and is summarised only to say where and when the text is shown)

- **What is shown**: `assets/EULA.md`, the CC Sync End User Licence Agreement, currently marked version 1.1 by the `<!-- EULA-VERSION: 1.1 -->` line inside it. Its legal text is not summarised here.
- **Where and when it is shown to the user**:
  - in the companion's Licence dialog (scrolling read-only text box, ACCEPT / DECLINE, described above) titled "... licence agreement", with the introduction "This computer is NOT SYNCING until someone here accepts the <product> licence agreement (version 1.1). Read it below. Accepting records your agreement on this computer only, and syncing starts straight away.";
  - automatically, 3 seconds after start-up whenever this computer has not accepted the current version, retried every 60 seconds while another companion window is in the way, until the dialog has been shown once (whatever the answer);
  - on demand from the tray item "► Accept the licence agreement to start syncing…" and the Settings button "READ AND ACCEPT THE LICENCE", as many times as asked;
  - the document text is lightly cleaned for display by the app (authoring comments, the version marker and Markdown markup removed, long dashes turned into spaced hyphens); the version and fingerprint are taken from the untouched file;
  - the same document is also shown by the setup wizard (onboarding, outside this part), which is normally where it is first accepted.
- **Acceptance record**: `~/.ccsync/eula_accepted.json`, holding the accepted version, the time (UTC) and a fingerprint (SHA-256 of the document with line endings normalised). Written atomically. The same file the setup wizard writes. A file with a byte-order mark is still read.
- **Gate rule**: sync lanes may run only when the record's version is at least the bundled version, compared number by number ("1.10" is newer than "1.9"; "1.0" equals "1.0.0"). The fingerprint is never checked.
- **Refusal sentences** (shown in the tray/Settings via the sync guard): "The CC Sync licence agreement has not been accepted on this computer. Open Tray > Settings > READ AND ACCEPT THE LICENCE." / "The licence acceptance record on this computer is unreadable. Open ..." / "The CC Sync licence agreement has been updated (version 1.1; this computer accepted 1.0). Open ...".
- **Fails open**: if the build carries no `EULA.md`, or the file has no version marker, the gate is skipped with a log warning and sync is allowed. (If the gate is live but the text cannot be read, the app shows "NOT SYNCING: this build is missing its licence document. <diagnostics route>.")
- After the dialog (app behaviour): DECLINE or closing gives "NOT SYNCING: the licence agreement was not accepted. Tray > Accept the licence agreement."; a failed save gives "Couldn't save your acceptance. Check disk space and try again."
- **Reported to the dashboard**: only the accepted version (max 32 characters), time (max 64) and fingerprint (max 64); nothing when there is no usable record ("not reported", not "not accepted").
- Bumping the version marker in the document is the whole of a re-consent: every computer is parked until it accepts the new version.

## New Resolve project setup prompt
(source: project_setup.py)

- **Trigger**: the dashboard's reply to a report names an open Resolve project that has no home on the server (`resolve_project_unmapped`). Each reply that lacks the name clears the flag; switching to a different Resolve project clears a flag for the previous one.
- **Automatic prompt, once ever per project** (project names compared case-insensitively; remembered across restarts in `project_prompts.json` in the companion's state folder, written atomically):
  - skipped silently (and retried on the next report) if another companion window is open, or if the project flagged is not the one currently open (including when no promptable project is open);
  - otherwise recorded as "asked" first, then a confirm dialog titled "NEW PROJECT": "Project '<name>' isn't set up on the server. No media will sync for it until it has a home. Set it up now? (Opens the dashboard in your browser.)" with the button "SET UP NOW";
  - accepting opens `<dashboard_url>/project-setup?resolve_project=<name, fully URL-encoded>` in the browser (the configured `dashboard_url`, not the site manifest's address);
  - declining, closing or having no display counts as asked; the balloon then says "You can set up '<name>' later: right-click the CCSync tray icon and choose Set up '<name>' on the server."
- **Manual**: while a project is flagged, the tray shows "Set up '<name>' on the server…", which opens the same link directly with no dialog.

## The assets folder
(source: assets/, theme.py, tray.py, eula.py, settings_window.py)

- `cc_mark_white.png`: the default product mark (Creators Club), white on transparent. Tinted for the tray icon (green/amber/red) and, in red, for every window's title-bar/taskbar icon and the Windows balloon icon.
- `ccsync_mark.png`: a neutral white-on-transparent mark shipped for white-label fleets; used only when selected through `CCSYNC_BRAND_LOGO` or the site manifest's `brand_logo`.
- `icon.png`: an older, pre-coloured logo. Used only as the window-icon fallback when the tintable mark cannot be loaded.
- `icon.ico`: the Windows executable's own icon (set at build time, outside this part). Not read by any code in this part.
- `EULA.md`: the licence agreement text (see the licence section).
- `field/`: belongs to another section (the field backup page).
- Not in the folder in source, but looked for in the shipped build: `THIRD_PARTY_LICENSES.txt` (opened by Settings > HELP > OPEN-SOURCE LICENCES; generated at build time).

## Looks redundant or overlapping

- Restart exists twice: the tray's "Restart CCSync" and Settings' "RESTART CCSYNC NOW". Both end in the same Settings restart function (the Settings button first looks for a tray action named `action_restart` that does not exist). The tray's own fallback restart, with its failure balloon "CCSync could not restart itself. ...", is only reached if the Settings module cannot be loaded; in practice a failed restart is only logged.
- Sign-in has three entry points that open the same dialog: the tray's "► Sign in…", the tray's "► Sign in again (...)", and Settings' "SIGN IN…" / "SIGN IN AGAIN…".
- The "proxy download stopped" state has two resume buttons (tray item and Settings) and one action that clears two unrelated stops (the safety breaker and the low-disk park), with two different dialogs behind it.
- The local sync stop can be cleared from the tray item and from Settings; set only from Settings.
- The update offer appears in the tray menu and again in Settings > HELP.
- Credential rejection is computed twice (`tray.credential_rejected` and `settings_window._credential_refused`, identical logic) and announced three ways in Settings (an advisory line, a THIS COMPUTER warning line, and the button).
- Resolve state is shown three ways: the tray's Resolve line (two counts), the tooltip suffix (the remaining counts), and Settings > RESOLVE (fuller sentences for the same counts, with different wording, for example "N missing" vs "N clips in this project are offline").
- The "Sync:" line, the tooltip and the Settings "blocked" advisory all restate the same sync-guard sentence.
- Three progress windows with near-identical layouts: the FIX ALL popup's progress area, the copy progress window (consolidate) and the background work window; the first two share the same three controls.
- Two separate sign-in style dialogs (companion Sign-in and Windows Server login) with the same form; and two separate typed-confirmation uses (remove project and switch to REMOTE EDITOR) share one window whose confirm button always reads "DELETE ANYWAY", even for the role switch.
- Scan whole project appears in Settings > ADVANCED and again in Settings > RESOLVE whenever counts are shown.
- UNDO LAST FIX (Settings > RESOLVE) and UNDO THE LAST CLIP-PATH CHANGE CCSYNC MADE (Settings > ADVANCED) both undo CCSync's last clip-path change; the first uses the app's own undo when it has one and otherwise runs the second.
- The tray tooltip, the Sync: line and the Settings window each compute their own "waiting, not connected to the server" sentence.
- `human_bytes` is defined twice (tray.py and popup.py) with identical behaviour, and two different duration formatters exist ("~12 min" in tray, "~12 min left" in popup).
- The help page and project-setup links use the configured `dashboard_url`, while "Open dashboard" prefers the site manifest's published address: two different addresses for the same dashboard.
- The ffmpeg sidecar warning is shown both in the tray menu and in Settings > YOUTUBE.

## Claims the code does not back

- Settings window module docstring: "every button closes the window first". The jump-strip buttons do not (the code itself notes this exception).
- `settings_window.action_restart` docstring: "The tray's own restart action when it exists, so the menu and this window are the same code path." The tray module has no `action_restart` (it is `action_restart_app`), so the Settings button always uses its own fallback (which happens to be the same function the tray item calls).
- `popup.licence_dialog` docstring: "THE DOCUMENT IS SHOWN, NOT SUMMARISED ... the widget holds the verbatim assets/EULA.md". The app passes a display-cleaned version (comments, marker and markup removed, dashes replaced), not the verbatim file.
- `show_popup` docstring: "falling back to a console listing". There is no console listing; the fallback logs and auto-skips the clips for 30 minutes.
- `PopupDialog` class docstring calls it a "tkinter Toplevel wrapper"; it builds its own root window, not a Toplevel.
- `tray._MenuOpenGuard.install()` is documented as kept "only because start_tray() and its tests call it"; it does nothing.
- `tray._tray_snapshot` comment says the "Sign in to YouTube (for downloads)…" item is "offered" in the menu; the YouTube items exist only in the Settings window.
- `tray._build_menu` and `ui_copy` describe the menu as "the ten-item layout"; the menu can show many more rows (up to 8 conditional prompts and up to 9 state lines besides the fixed items).
- `tray_native.Menu.rendered` docstring refers to `*proxy_items` and sections that "carry their own trailing separator"; the current menu has neither.
- `tray._menu_fingerprint` docstring says it rebuilds "~40 menu items"; the reduced menu has far fewer.
- `ui_state.py` docstring describes pystray's window procedure; the tray no longer uses pystray.
- The project-setup decline balloon tells the editor to "right-click the CCSync tray icon"; on macOS the menu bar item is clicked, and on Windows any click opens the menu.

## Could not determine

- The exact wording of: the site notification title (site.py), the scripting advice for Resolve (resolve_bridge.py), the ffmpeg sidecar warning (ytdlp_manager.py), the YouTube terms title and text (ytdl_attestation.py), the breaker's editor-facing reasons (lane_guard.py), the dashboard address warnings (config.py), the clock-skew phrase (reporter.py), and the sync guard's "blocked" sentences. All are produced outside this part.
- What "Copy diagnostics for your admin", "Scan whole project", consolidate, undo, share LUTs, make/stop proxies, the ingest actions, pause/resume, sign out and apply-update actually do beyond being started from here (app.py and others).
- The exact suggested destination path rule and the destination list in the FIX ALL popup (fixer.py).
- When and how often the "Resolve scripting is down" dialog and the FIX ALL popup are raised (app.py).
- The ingest picker's accepted video file extensions (broll_server.py).
- Whether the macOS menu-bar placement check and Windows dark/light taskbar colours behave as described on real hardware; nothing here could be run.
