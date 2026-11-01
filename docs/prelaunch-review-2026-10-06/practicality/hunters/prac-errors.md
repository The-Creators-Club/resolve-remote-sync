# Pre-launch practicality pass - lens `prac-errors`

Date 2026-10-06, HEAD 08b40eb plus the uncommitted working tree. Read-only review.

**Covered:** the companion's tray and Settings lines (`tray.py`: `classify_lane_error`,
the lane-line formatter, the reporter, clock and sync-conflict lines, the sign-in dialog,
the grade-swap flow), `ui_copy.py`, the strings `config.validate_config` writes, the
sign-in path in `identity.py`, the strings the 8899 loopback sends back to the b-roll page
(`broll_server.py`, `broll_fetch.py`, `broll_upload.py`, `loopback_guard.py`), the
b-roll page's error toasts (`broll/web/static/app.js`), the onboarding wizard's error
mapping and its finish page (`onboarding/steps.py`, `onboard.py`), the setup wizard's
task details (`dashboard/setup_engine.py`), the dashboard's `detail` strings, its
notices (`notices.py`), how htmx errors are handled (`static/htmx_errors.js`), the
Users page template and the ytdl page's error rendering.

**Probed:** `tray.classify_lane_error` with eight realistic rclone error tails (scratchpad
script, companion venv).

**Not covered in depth:** the alert email bodies, the music page's toasts, the Cards
SPA, every one of the roughly 300 `detail=` strings one at a time, and the macOS-only
copy paths.

Earlier passes (UX-10, APP-5, ui-copy-*, the 2026-09-03 usability sweep) have already
cleaned most visible copy. What is left is mainly in the places those passes did not
reach: raw tool output passed straight through, setup and environment wording, and
escalation paths that stop at "your admin" or "support" with nowhere after that.

---

### prac-errors-1 - Setup wizard and admin refusals tell an appliance admin to set environment variables and "redeploy", though the appliance tells them to edit nothing
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/setup_engine.py:599-605` (DASH_ADMIN_USERS ... then redeploy), `:731`, `:753` (DASH_PROJECTS_DIR is not mounted: add the volume and redeploy), `:883`, `:899` (SYNCTHING_GUI_URL not configured), `:1211` (set DASH_NAS_HOST and ..., then redeploy), `:1538-1541` (DASH_RELEASE_PUBKEYS ... "the public half of your release key" ... "(docs/RELEASE.md)"); `api.py:6077` (SYNCTHING_GUI_URL is not configured, on the device-approve button); `templates/partials/admin_users.html:292-295` (or set DASH_NAS_PW in the container); `dashboard/deploy/compose.appliance.yaml:35-42` ("NONE OF IT SHOULD BE EDITED ... The customer never sees one").
- **What:** The setup wizard is the first screen a new customer's admin sees. Its task details are written for an operator holding a compose file: environment variable names, "redeploy", and a path inside our repo (`docs/RELEASE.md`) that a customer does not have. The release-key step says "your release key", but a customer has no release key. The key they need is the VENDOR's public key. The appliance compose file sets neither `DASH_RELEASE_PUBKEYS` nor `SYNCTHING_GUI_URL`. It tells the admin to edit nothing, and says the customer will never see a credential.
- **Scenario:** A studio admin pastes `compose.appliance.yaml` and opens the wizard. "Signing key for updates" reads "no release signing key: this server refuses every build until DASH_RELEASE_PUBKEYS holds the public half of your release key ... Set it and redeploy (docs/RELEASE.md)". The Syncthing step reads "SYNCTHING_GUI_URL not configured". The admin has no release key, no docs/RELEASE.md, and has been told not to edit the file, so they stop and email the vendor.
- **Recommendation:** Treat each wizard detail as two parts: a plain sentence plus one action the admin can take in the browser, and keep the variable name for an "operator detail" fold-out. Ship the vendor's public key and the in-stack Syncthing URL (`http://syncthing:8384`) as appliance defaults, in the image or the compose file, so those two steps are green on first boot. Until then, the release-key text should say "This is the vendor's key. It comes with your install; if this step is red, contact <support>", never "your release key" or a repo path. Remove "redeploy" and "(docs/...)" from every string a wizard or admin page renders.
- **Known:** Not recorded. The missing appliance defaults may also be raised by the install lens; this finding covers the wording the admin is shown.

### prac-errors-2 - Every escalation ends at "your admin" or "support", and there is no support contact anywhere in the product
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/ui_copy.py:48` (DIAGNOSTICS route, used about 30 times in `tray.py`, `app.py`, `settings_window.py`, `loopback_guard.py`, `identity.py`, `fixer.py`, `resolve_journal.py`); 68 "your admin" sentences in companion modules; `dashboard/src/ccsync_dashboard/notices.py:1456`, `:1490`, `:1585` ("send it to support"); `docs/HOW_IT_WORKS.md:459`, `:858`, `:894`; no `support` field in `site_store.py` or `companion/site.py`.
- **What:** For an editor, the last step of every error is "COPY DIAGNOSTICS FOR YOUR ADMIN". For the admin, the last step of the dashboard's worst notices is "send it to support". Nothing in the product says who support is. There is no support email, URL or contact field in the site manifest, the /help page, the dashboard footer or the setup wizard. The diagnostics text is a dump of internal state (rclone available, token expiry, RELAYED Syncthing devices), and nothing tells the customer's admin how to read it or where to send it.
- **Scenario:** With ten customers live, an editor at customer 7 copies diagnostics and pastes them to their studio manager. The manager is non-technical, cannot read the dump, and has no address to forward it to. The same manager sees "Copy the text of this notice and send it to support" on the home page and has the same problem. Every incident becomes an informal hunt for the vendor's personal email.
- **Recommendation:** Add `support_contact` (email and/or URL) to the site manifest, defaulting to the vendor's address in the vendor build. Render it on /help, in the dashboard footer, in every notice whose fix says "support" (as a mailto link with the notice text prefilled), and in the companion's HELP section beside COPY DIAGNOSTICS. Add one paragraph to HOW_IT_WORKS for admins: "When an editor sends you diagnostics: ...". Longer term, let the admin request a computer's diagnostics from the dashboard (the report channel already exists) so that nobody has to paste anything.
- **Known:** Not recorded.

### prac-errors-3 - The "send your device ID to your admin" step leads to an approval list that the appliance's default setup hides, and the notice points to that missing list
- **Severity:** high
- **Confidence:** PLAUSIBLE
- **Where:** `onboarding/steps.py:2439-2456` (finish page: "DONE: SEND YOUR DEVICE ID TO YOUR ADMIN"); `onboarding/onboard.py:1815-1819` (the "open http://127.0.0.1:8384, Actions > Show ID" placeholder); `dashboard/templates/partials/admin_users.html:156-204` (the devices-awaiting-approval window is inside `{% if admin_users.truenas_configured %}`); `dashboard/src/ccsync_dashboard/api.py:4313-4323` (no NAS credential, which is "the appliance's default shape", sets `pending_devices: []`); `notices.py:552` (fix line "Approve it on Settings, Users, in the pending devices list"); `api.py:4465-4467` (the companion already reports its own device ID).
- **What:** The wizard's last screen asks the editor to copy a 56-character Syncthing device ID and send it to the admin. The dashboard already receives that ID from the companion's report and pre-fills the owner on the approval row, so the copy-and-paste adds nothing. The approval window is only drawn when a NAS credential is configured. On the appliance's stated default (local accounts, no NAS credential) the admin has nowhere to approve the device. The `pending_device_approval` notice still sends them to "Settings, Users, in the pending devices list".
- **Scenario:** A new editor finishes the wizard and emails the device ID. The admin opens Settings > Users, finds local users and no devices window, and the editor's folder sync never starts. The editor's computer "looks permanently behind" (the notice's own words) and neither person can find a way forward. I could not close this end to end: on today's appliance compose `SYNCTHING_GUI_URL` is unset as well, so the notice may never fire there. Either way, the editor's instruction leads nowhere.
- **Recommendation:** Draw the devices window whenever Syncthing is configured, independently of the NAS credential (approval is a Syncthing call, not a NAS call). Replace the finish page's "send this ID" with "Tell your admin that <user> on <computer> is waiting under Settings > Users > devices awaiting approval". Keep the ID in a fold-out for the rare case where it is needed. The notice's fix line should give a link to the window, and should only be written when that window will be shown.
- **Known:** Not recorded.

### prac-errors-4 - The tray's sign-in dialog shows raw Python/urllib errors; the wizard already has a classifier that the tray does not use
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/identity.py:321-323` (`return {"ok": False, "error": str(exc)}`), `:490` ("dashboard_url is not configured -- cannot sign in"), `:262-263` (the 403 fallback names the NAS 'editors' group); `tray.py:1253-1256` (`f"sign-in failed: {exc}"`); classifier that is not reused: `onboarding/steps.py:1330-1359` `_classify_reach_error`; dashboard side `api.py:2430` (`f"verify busy: {exc}; try again"`).
- **What:** The most common reason sign-in fails on a fresh machine is that Tailscale is off or the address is wrong. That case lands in the generic `except` branch, and the dialog shows something like `<urlopen error [WinError 10060] A connection attempt failed because the connected party did not properly respond...>` or `<urlopen error [Errno 11001] getaddrinfo failed>`. The onboarding wizard already maps these failures to three plain sentences (unknown host, timeout, refused), but the tray uses a separate code path.
- **Scenario:** An editor's Tailscale signed itself out overnight. They open Tray > Sign in, type their password and get a WinError line, which they screenshot to their admin.
- **Recommendation:** Move `_classify_reach_error` into a shared module, or copy it into `identity.py`, and use it in `verify_credentials`. The fallback text should be "Can't reach the dashboard at <url>. Check Tailscale is connected, then try again." Replace "dashboard_url is not configured" with "This computer doesn't know the dashboard address yet. Enter it under Tray > Settings, or re-run the installer." Make the dashboard's 503 generic ("the server is busy checking another sign-in, try again in a few seconds").
- **Known:** Not recorded.

### prac-errors-5 - Developer-facing config-validation text reaches editors' tray lines and the Settings window
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/config.py:2071-2216` (validate_config sentences); `app.py:6423-6427` (`"NOT SYNCING: this computer isn't fully set up -- " + config_problems[0]`, or "see companion.log"); `tray.py:716-731`, `:761-763` (shown on every lane line, up to 180 characters); `tray.py:1439-1440` ("Set ytdl_cookies_file in config.toml instead."); `broll_fetch.py:207-212`, `:248` ("remote= in ~/.ccsync/config.toml", shown in the web page's toast).
- **What:** APP-5 deliberately surfaced the config sentence so that an admin looking over the editor's shoulder can see which key is wrong. The sentences themselves were written for a developer, for example: "remote is blank -- set it to the rclone remote name from rclone.conf", "remote_root is not absolute: 'x' -- an SFTP session starts in your home directory on the NAS, so this resolves to ~/x", or "config.toml failed to load and every setting below is a DEFAULT ... -- <TOML parser exception>". A customer's editor cannot act on any of them, and neither can a customer's admin: no screen edits config.toml, and the dashboard never sees it.
- **Scenario:** A drive letter changes or a bad hand edit happens. Every lane line reads "Upload: NOT SYNCING: remote_root is blank -- rclone would target the remote's default directory, which for SFTP is your home directory on the NAS, not the project tr…". The editor reads this as "the software is broken", and the admin cannot fix it remotely.
- **Recommendation:** Give each validate_config problem two strings: an editor sentence plus an action ("This computer's sync settings are incomplete. Re-run the installer from the dashboard's Downloads, or send diagnostics to your admin") and the technical sentence. Show the editor sentence on tray, Settings and web toasts. Put the technical sentence in diagnostics and in the report, so the dashboard's fleet page can show the admin the actual key. Never point an editor at config.toml. Where a Settings control exists (dashboard address, cookies file picker), name that control.
- **Known:** Not recorded. APP-5 introduced the current behaviour on purpose; this finding concerns the wording, not the decision to show something.

### prac-errors-6 - When "Send to Resolve" is refused because of an origin mismatch, the editor is told the tray is not running or the browser blocked the request, and the suggested self-test confirms the wrong cause
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/broll_server.py:2066-2083` (origin refusal, logged only), `:2193-2201` (the preflight answers 403 with no Access-Control-Allow-Origin, so the page cannot read the body), `:2123-2132` + `loopback_guard.py:117-119` (REFUSED_MESSAGE, never readable by the page); `broll/web/static/app.js:1935-1949`, `:2076-2083` ("Couldn't reach the CC Sync tray ... Self-test: open http://127.0.0.1:8899/status - if that shows ok:true, it's the browser"); `ingest.js:107-110` (same hint); `loopback_guard.py:231-247` (the allow-list is the exact `dashboard_url` plus the manifest URL).
- **What:** If an editor reaches the dashboard by any address other than the exact `dashboard_url` (MagicDNS short name or full ts.net name, IP or name, http or https on another port), the companion refuses the preflight with no CORS headers. The browser then raises a plain network error. The page's only branch for that says the tray may not be running or the browser blocked local access, and tells the editor to open /status. /status is a top-level navigation with no Origin header, so it answers `ok:true`. The page's own rule then says "it's the browser", which sends the editor into browser permission settings. The true cause and its fix (one config line) are only in companion.log.
- **Scenario:** A customer's admin bookmarks `https://ccsync-studio.tailXXXX.ts.net` for the team, while the installer wrote `http://100.x.y.z:8480`, or the reverse. Every editor's Send to Resolve and Add-to-archive fails with the browser-permission advice, and a support call follows for each editor.
- **Recommendation:** Record the last refused origin (and when) in the companion and show it in two places. First, as a tray/Settings line: "The b-roll page at <origin> was refused: this computer only trusts <dashboard_url>. Ask your admin to make these match." Second, in the /status JSON, so the self-test the page recommends shows the cause. Change the page's text to say "if /status shows ok:true and lists this page's address under refused, the addresses don't match". Also consider having the dashboard publish its known alias origins in the site manifest, so that the ts.net name and the IP both count.
- **Known:** Not recorded. CLAUDE.md describes the behaviour ("the companion log names both"), but nothing shows it to the user.

### prac-errors-7 - The lane-error classifier tells editors the wrong thing for common local failures (probed)
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/tray.py:534-606` (`classify_lane_error`).
- **What:** I ran the classifier on realistic rclone tails:
  - `open /Volumes/T7/.../A001.mov: permission denied` (a local file the Mac cannot read, for example a missing Full Disk Access grant or a file owned by another user) gives "The server rejected this computer's login", because "permission denied" sits in the auth branch.
  - `The process cannot access the file because it is being used by another process` (a render still being written, a file Resolve has locked), `sftp: "Failure" (SSH_FX_FAILURE)` (often the NAS volume or quota is full), `Fatal error: config file not found` and `didn't find section in config file` (rclone.conf gone) all give the generic "Something went wrong. COPY DIAGNOSTICS".
  - `unexpected EOF` (a dropped connection or a NAS restart) gives "Check the Tailscale tray icon is connected", even when Tailscale is fine.
- **Scenario:** A Mac editor whose external SSD lost its permission grant is told their login was rejected. They re-sign-in repeatedly and their admin resets the password, with no effect.
- **Recommendation:** Classify on where the path is: local (starts with the local root or a drive letter) versus remote. Add branches for "file in use (it will retry when the file is closed)", "server out of space or refused the write (SSH_FX_FAILURE)", "this computer's upload settings are missing (re-run the installer)" and "local permission (macOS: System Settings > Privacy > Full Disk Access)". Keep "server rejected login" for `publickey` / `unable to authenticate` / `handshake failed` only. Pin the probed strings in a test.
- **Known:** Not recorded. The Syncthing branch was CR-17-era; these cases are new.

### prac-errors-8 - B-roll fetch and upload failures put raw rclone stderr in the web page's toast
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/broll_fetch.py:338` ("could not start rclone: {exc}"), `:381` (`errors[-1]` or "rclone exited with code N"), `:383` ("cancelled -- the companion shut down"); `broll_upload.py:550`, `:583` (the same pattern); `broll_server.py:1806`, `:1918` ("rclone is not installed on this computer ..."). The docstring at `broll_fetch.py:200` confirms "it lands in the web UI's toast verbatim".
- **What:** When Send to Resolve has to sync a clip down first, or an indexed clip is uploaded, a failure shows the last rclone log line, for example `2026/10/06 10:11:12 ERROR : Assets/B-roll Archive/...: Failed to copy: sftp: "Failure" (SSH_FX_FAILURE)`, or `rclone exited with code 3`. This is the same raw text that `classify_lane_error` was written to keep off the tray.
- **Scenario:** An editor on deadline presses Send to Resolve on an archive clip during a Tailscale blip and gets a red toast in rclone log format with no next step.
- **Recommendation:** Pass these through the same (improved) classifier as the lanes (prac-errors-7), and add the clip name: "Couldn't fetch <clip>: can't reach the server. Check Tailscale, then press Send again." Keep the raw tail for the log and diagnostics. Replace "rclone is not installed" with "This computer's sync tools are missing. Re-run the installer."
- **Known:** Not recorded.

### prac-errors-9 - A failed grade-swap restore leaves the drive unmapped and tells the editor to "remap it by hand"
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/drive_swap.py:571-582` ("local_root is not configured -- P: is currently UNMAPPED", "P: could not be restored (<subst stderr>) -- remap it by hand or re-run the installer"); `tray.py:2214` (shown as "Swap stopped: ..."); a repair button already exists at `ui_copy.repair_drive` ("Tray > Settings > REPAIR P: NOW").
- **What:** This is the worst outcome of the grade swap: P: is gone and every clip in Resolve is offline. The message gives the editor a task they do not know how to do (`subst` or `net use`) and a key name (`local_root`). The product already has a one-click repair, and the message does not mention it.
- **Scenario:** A colourist finishes grading and swaps back. `subst` fails, and the toast says "remap it by hand". They do not know what that means, and the session stops until someone remote-controls the machine.
- **Recommendation:** "P: is not connected to anything right now, so Resolve shows media offline. Press <ui_copy.repair_drive(letter)> to put it back. If that fails, <DIAGNOSTICS>." Remove `local_root` and `subst` from the sentence, and keep them in the log.
- **Known:** Not recorded.

### prac-errors-10 - Tray warnings that state a problem but give no action (clock skew, never-accepted report)
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/tray.py:3631-3632` ("This computer's clock is N behind the server's. Sync will not work correctly until it is fixed"), `:3609-3610` ("... Copy diagnostics for them", the only route here not written via `ui_copy.DIAGNOSTICS`).
- **What:** The clock line warns that sync is broken (and it really is: lane B's `--min-age` transfers nothing) but does not say how to fix the clock. The report line names an action without saying where the button is.
- **Scenario:** A laptop's clock is 20 minutes off after a BIOS battery fault. The editor sees "Sync will not work correctly until it is fixed" and does not know what "it" is or how to fix it.
- **Recommendation:** Windows: "Settings > Time & language > Date & time > Sync now". macOS: "System Settings > General > Date & Time > Set time automatically". Pick the text by platform. Use `ui_copy.DIAGNOSTICS` in the report line.
- **Known:** Not recorded.

### prac-errors-11 - Leftover developer phrasing in dashboard refusals and notices
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/notices.py:1580` ("{seen} time(s)", the parenthetical plural UX-10 retired elsewhere); `templates/partials/health_collector.html:64`, `:68` ("No enforce cycle has run yet", "What the enforce cycle would apply"); `ui.py:1210` ("resolve_project required"), `:1217` (`str(exc)`), `:1219` (Python repr `{root_rel!r}`), `:1005`, `:2596`, `:2989` ("malformed form body"), `:2952` ("device not in project: <id>"); `api.py:4185`-style `{slug!r}` reprs (`api.py:2092`, `:4158-4170`); `api.py:6080` ("must be a valid TrueNAS-style username" on a Synology or local-account install); `ytdl/web/static/app.js:1783` ("failed: see the server log", where the editor cannot see the log).
- **What:** `static/htmx_errors.js` now puts a refusal's `detail` beside the control that was pressed (ui-dash-static-2). That is the right behaviour, but it means these strings are now shown in the UI: Python quote-reprs, internal field names, "enforce cycle", "TrueNAS-style" on a non-TrueNAS site, and "see the server log" for someone who cannot open it.
- **Scenario:** An admin picks a folder that has just been renamed and reads: no such folder under Projects/: 'FF5/Old Name'. That is readable but rough. A Synology admin creating an account is told the username must be TrueNAS-style.
- **Recommendation:** Add the dashboard's `detail` strings to the existing no-em-dash scan as a second scan for `!r`-style quotes, `(s)` and a short banned-word list (enforce cycle, selection, lease, slug, TrueNAS on generic paths). Reword the handful above.
- **Known:** Not recorded.

### prac-errors-12 - The product's name is spelled three ways in the copy an editor reads
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** "CCSync" appears in about 258 user-visible string literals in the companion and onboarding (e.g. `ui_copy.QUIT` "Quit CCSync", "UNDO THE LAST CLIP-PATH CHANGE CCSYNC MADE"). "CC Sync" appears in about 21, in the b-roll and music pages, `loopback_guard.REFUSED_MESSAGE` and /help ("HOW CC SYNC WORKS"). "the companion" appears in 39 web-page strings.
- **What:** One editor sees "the CC Sync tray" in the browser, "Quit CCSync" in the menu, "the CC Sync companion" in a refusal and "the companion" in an ingest hint, all about the same icon. CLAUDE.md names the product `CC Sync`.
- **Scenario:** Support asks "is CC Sync running?" and the editor looks for an item by that name in the tray menu.
- **Recommendation:** Choose one product name (CLAUDE.md says "CC Sync") and one noun for the tray app, and add the name check to the existing copy scans. This is cosmetic, but it costs nothing to fix before the first customer's screenshots are taken.
- **Known:** Not recorded.
