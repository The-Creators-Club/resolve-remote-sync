# Pre-launch practicality review: new editor onboarding (prac-editor-onboard)

Date 2026-10-06, HEAD 08b40eb plus the uncommitted working tree. Read-only.

**Covered.** The new-editor journey on Windows and macOS as the editor and their admin
live it: `installer/START_HERE.md`, `docs/EDITOR_SETUP.md`, the onboarding wizard
(`onboarding/onboard.py`, all pages, and the `onboarding/steps.py` helpers behind them:
EULA, role, Tailscale, sign-in, privacy, install, finish), the end of `windows_bootstrap.ps1`
(elevation, the loopback share, the device-ID and remaining-steps banner) and the
macOS bootstrap's dependency and permission handling. Also the dashboard side the editor
touches: `/download` and `/installer`, `/api/v1/verify`, SSH key and device approval, the
Users page pending lists, and the tray wording for a machine that is not approved yet. I
probed `steps.ensure_config` and `fleet_token_needed` with a scratch script to check what
carries over when a machine is onboarded to a second dashboard (finding 8).

**Not covered.** No live installs (none allowed), the uninstall/upgrade scripts beyond their
docs, the macOS `.app` build itself, and the admin-side account creation flow except where
the editor waits on it.

Checked against KNOWN_BUGS.md, COMMERCIAL_READINESS.md and the 2026-09-24 hunt.
Code signing (COMMERCIAL_READINESS item 4) and the ad-hoc-signature TCC loss (old item 16)
are known and are cited, not re-reported.

---

### prac-editor-onboard-1 - The installer can only be downloaded from a place the installer is meant to get you into

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/ui.py:3922-3990` (`/download`, session-gated by `login_gate`); `installer/START_HERE.md:10-16` versus `:85-92`; `onboarding/onboard.py:782-822` (wizard STEP 2 "JOIN THE NETWORK")
- **What:** The only supported way to get `onboard.exe` / the Mac zip is `[ INSTALLER ]` on the dashboard, which needs a dashboard login. Since the 2026-08-17 decision the dashboard is reachable over the tailnet only. So the editor must already have joined Tailscale and signed in to the dashboard before they can download the wizard, and the wizard's second page is "install Tailscale and join the network". START_HERE.md tells the editor to "sign in and click `[ INSTALLER ]`" in its first paragraph. "1. Join the private network (Tailscale)" comes 80 lines further down.
- **Scenario:** A new freelance editor gets "here's your login" from a customer's admin. They open the dashboard URL and get no answer (not on the tailnet yet). They go back to the admin, who has to email or Slack an `.exe` (which SmartScreen and mail filters treat as suspect). Or the editor installs Tailscale by hand from START_HERE section 1, after which the wizard's Tailscale page is redundant. Every customer's first editor hits this.
- **Recommendation:** Give the admin a way to hand over the installer that works before the editor is on the tailnet. One option is a per-editor, expiring, unauthenticated download link minted on Settings > Users (it can be published through the same Funnel port the client-share links use). Another is the vendor's public release feed URL for the wizard itself. Then reorder START_HERE: 1. accept the Tailscale invite, 2. run the wizard. The wizard's Tailscale page stays as the check.
- **Known:** none

### prac-editor-onboard-2 - The wizard makes the editor type the dashboard address it was just downloaded from

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `onboarding/steps.py:156` (`DEFAULT_DASHBOARD_URL = os.environ.get("CCSYNC_DASHBOARD_URL", "")`); `onboarding/onboard.py:612-627, 729-740`; `ui.py` `/download/{platform}` (serves the file under a fixed server-chosen name, `api._package_filename`)
- **What:** Since WP0 (2026-08-17) no address is compiled in, so page 2 refuses NEXT until the editor types the dashboard URL. On a tailnet that URL looks like `https://nas.tail26290e.ts.net`. The dashboard knows its own address and serves the download, but it passes nothing to the wizard. The welcome page now says you need the address, and the error example is `http://<your-dashboard>:8480`, which is not the shape a Tailscale Serve site uses.
- **Scenario:** The editor types `nas.tail26290e.ts` or the Serve name with a typo. The Tailscale page then says "that address does not exist on this network: check the spelling with your admin", and that is one more round trip to the admin on day one.
- **Recommendation:** Let `/download/{platform}` name the file after the site, e.g. `ccsync-onboard-1.0.46@nas.tail26290e.ts.net.exe`. Have the wizard read its own `sys.executable` name, or the `.app`'s enclosing zip name on macOS, to prefill and lock the field, with an "edit" link for the rare case. The signature covers the bytes and not the name, so publishing stays signed. Change the example in the refusal to the site's real shape (`https://<name>.ts.net`).
- **Known:** none

### prac-editor-onboard-3 - There is no "invite an editor" flow: a new editor needs five to seven separate hand-offs from the admin

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `docs/EDITOR_SETUP.md:15-35` ("Before you start" list); `onboarding/steps.py:2459-2486` (welcome text: "two things"); `onboarding/onboard.py:1262-1280` (fleet token field); `installer/START_HERE.md:250-262` (Postgres password "sent separately"); no `invite` route anywhere in `dashboard/src/ccsync_dashboard/`
- **What:** Each item reaches the editor by a separate side channel:
  1. a Tailscale invite
  2. the dashboard URL
  3. username and password
  4. on a site that has retired the shared token (the boot log tells every operator to), a 64-character `cce1.` report token copied from Settings > Users > REPORT TOKENS
  5. the Resolve project-server host and Postgres password
  6. "External scripting = Local", which only EDITOR_SETUP mentions

  The editor then sends back the Syncthing device ID, and sometimes the SSH key. On the admin's side that is: create the account, invite to the tailnet, mint the token, approve the SSH key, approve the device (typing the username, CR-91) and send the Postgres password. The welcome page says "you'll need two things". The token field appears unannounced on the install page.
- **Scenario:** A customer onboarding six freelancers for a shoot spends the day relaying strings. Any one item that is missing gives a "NOT READY" or a silent no-sync state, and the editor can't tell which one.
- **Recommendation:** Add a Settings > Users > `[ INVITE EDITOR ]` that creates the account and produces ONE message (copyable, or emailed through the existing alerts SMTP): the download link (finding 1), the dashboard address (finding 2), the username and a one-time password, and the Tailscale invite link if the admin pastes one. Everything else should come from the signed-in session: the report token (finding 4), the Postgres settings via the site manifest (finding 6), and approval (finding 5). The goal is that an editor needs one email and their password.
- **Known:** none

### prac-editor-onboard-4 - A password-verified sign-in still cannot get a per-editor fleet token, so the secure configuration adds a copy-paste per computer

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/api.py:2405-2460` (`api_verify`: "CR-18 stands: /verify never mints a cce1 token"); `onboarding/steps.py:1034-1068`; `onboarding/onboard.py:1262-1280, 1539-1544`
- **What:** `/api/v1/verify` checks the editor's real password and fleet membership, then hands back a long-lived signed identity token, but it refuses to mint the per-editor `cce1.` report token. The CR-18 reasoning ("the unauthenticated bootstrap must never issue one") treats /verify as unauthenticated, but by the time it answers it has authenticated the person exactly as the dashboard login does. So once an operator retires the shared token, which is the documented hardening step, every new computer needs the admin to mint a token and send the 64-character string, and the editor to paste it. Leaving it blank gives a whole install with "NOT READY". In the default configuration, every editor's companion instead holds the one fleet-wide shared secret.
- **Scenario:** An editor's laptop is replaced mid-project. They run the wizard and sign in fine, and the finish page says "no fleet key ... ask your admin". The admin is on a shoot, so the laptop is invisible to the fleet and nothing syncs until they get back.
- **Recommendation:** On a successful /verify (same throttle, fleet-membership check and audit row), mint a `cce1.` token bound to that username and the reporting machine and return it. Admins can still revoke it per token on the Users page. Then make "shared token retired" the vendor default for new sites. Remove the token field from the install page.
- **Known:** CR-18 (design decision, FIXED); CR-55. This finding challenges CR-18's premise and does not report a bug in it.

### prac-editor-onboard-5 - "Send your device ID to your admin" is busywork the dashboard already does, and the editor is never told they are waiting on approval

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `onboarding/steps.py:2423-2456` (`finish_page_copy`: "DONE: SEND YOUR DEVICE ID TO YOUR ADMIN"); `installer/windows_bootstrap.ps1:2487-2493`; `dashboard/src/ccsync_dashboard/api.py:4462-4478` (`_pending_owner_hint`: "the dashboard already knows the answer it was making the admin guess"); `dashboard/templates/partials/admin_users.html:165, 301` (the only place pending items appear); `companion/src/ccsync_companion/tray.py:596-599`
- **What:** The companion reports its own Syncthing device ID, and the wizard already uploads the SSH key (`_offer_ssh_key`). The admin's Users page lists both as pending, with the owner suggested. Even so, the finish page's headline instruction is to copy a 56-character ID into a message, and the bootstrap banner says the same. Nothing tells the admin that someone is waiting: there is no alert kind, no digest line and no home-page notice for pending keys or devices. On the editor's side, if they tick a project before the key is approved, lane A/B fails SFTP auth and the tray says "The server rejected this computer's login", which reads like a broken install, not "waiting for your admin".
- **Scenario:** The editor finishes at 18:00, sends the ID, ticks the project and sees a red error. The admin approves the key from the pending list but misses the separate devices list. Lane C (audio, .drp, graphics) never arrives, and nobody gets an alert.
- **Recommendation:** Change the finish page to "Done. Your admin has been asked to approve this computer", and show the ID only as a fallback. Add an alert kind or notice "N computers waiting for approval" with one `[ APPROVE ]` that approves the key and the device together. Better still, auto-approve a device and key submitted under a freshly verified identity whose account the admin created (the trust is the same). Give the companion a reported state "waiting for approval", taken from the report reply, so the tray says that instead of "rejected this computer's login".
- **Known:** none (CR-91 covers the approve-dialog username, not this flow)

### prac-editor-onboard-6 - The wizard says DONE but never connects Resolve to the project server or enables scripting, and the manual steps it leaves are only in a scrolling log

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `onboarding/onboard.py:1781-1838` (`show_finish`: device ID, SSH key, hint; no Resolve step); `installer/windows_bootstrap.ps1:2503-2508` ("4. connect DaVinci Resolve to the Project Server / 5. Prefer Proxies / 6. ... see docs/EDITOR_SETUP.md", printed into the wizard's log box only); `installer/START_HERE.md:250-262` (Username `postgres`, password "sent separately"); `docs/EDITOR_SETUP.md:17-19` ("External scripting using = Local", mentioned nowhere else an editor reads); no installer, wizard or companion code sets or checks that preference (`grep "External scripting"` hits only `music_worker.py:72`)
- **What:** An editor can't open a single shared project until they have done three things by hand:
  1. added a PostgreSQL project library in Resolve with a host and credentials. START_HERE says the username is `postgres`, so every editor gets the database superuser password.
  2. set Preferences > System > General > External scripting = Local. Resolve's default is None, and with it the watcher, fixer, popup, Send to Resolve and proxy attach all do nothing.
  3. turned on Prefer Proxies.

  The wizard's last page mentions none of these. They appear only as lines 4-6 of the bootstrap banner inside the log box, and line 6 points at a repo document the editor does not have. The macOS bootstrap already writes Resolve's preference files for Mapped Mount, so writing Resolve's prefs from the installer is a pattern this codebase already uses.
- **Scenario:** The editor closes a DONE wizard, opens Resolve and sees only the local database. They wait for a sync that is in fact working, and phone the admin for "the Postgres password". Then the companion shows RESOLVE SCRIPTING IS DOWN (finding 7).
- **Recommendation:** Put a "Last: connect Resolve" section on both finish pages, with the host prefilled from the site manifest and the three settings as a checklist. Add an optional manifest block (`resolve_library: {host, port, name, user}`) and a non-superuser Postgres role per site so the password is not the superuser's. Where Resolve is closed, have the installer write the External scripting preference the same way the Mac Mapped Mount is written. Replace "see docs/EDITOR_SETUP.md" with the dashboard's own `/help` URL.
- **Known:** none (COMMERCIAL_READINESS.md:512 records "external scripting set by hand" as a fact, not a defect)

### prac-editor-onboard-7 - No check for Resolve Studio or the scripting preference; the tray's advice for that state is "quit and reopen Resolve", which never fixes it

- **Severity:** medium
- **Confidence:** PLAUSIBLE (the wording and the missing check are confirmed; that a scripting-off Resolve lands in NO_SCRIPTING rather than NO_SERVER was not probed, because no live Resolve was allowed)
- **Where:** `companion/src/ccsync_companion/resolve_bridge.py:565-579` (`NO_SCRIPTING_MESSAGE`, `NO_SERVER_MESSAGE`); `companion/src/ccsync_companion/tray.py:1772-1860` (RESOLVE SCRIPTING IS DOWN dialog); `onboarding/steps.py` (Windows has no Resolve presence or edition check; the Mac only checks presence, `:598`)
- **What:** The product requires Resolve Studio with external scripting set to Local, but neither installer checks for either. When Resolve is open and scripting answers nothing, the editor gets a modal saying "quit and reopen Resolve; if that does not help, also restart the companion". For a free-edition Resolve, or one with scripting set to None, that advice is useless however many times they follow it. The dialog's other button is STOP WARNING ME, which turns a setup error into a silenced, permanently dead companion.
- **Scenario:** A new editor on Resolve free (common for freelancers who use Studio only at the studio), or with the default None preference, restarts Resolve and the companion three times, then clicks STOP WARNING ME. Their out-of-tree media never uploads, and nothing says why.
- **Recommendation:** In the wizard, detect Resolve and its edition (the Windows install path and `Resolve.exe` version info, or the Mac bundle id and name) and warn on the install page if Resolve is not Studio. In the companion, when the no-scripting state has lasted past the grace period on a machine that has never had a scripting connection, change the message to "Resolve's External scripting is off, or this is not Resolve Studio: Preferences > System > General > External scripting using: Local, then restart Resolve". Keep "quit and reopen" for machines that have connected before.
- **Known:** none

### prac-editor-onboard-8 - Onboarding a computer to a second dashboard silently keeps the first site's NAS path and fleet token, then says DONE

- **Severity:** medium
- **Confidence:** CONFIRMED (probed)
- **Where:** `onboarding/steps.py:3640-3646` (`remote_root` is a `defaults` key, "SEEDED, not owned"); `:3612-3613` (a blank `report_token` never touches the key); `:1034-1044` (`fleet_token_needed` returns False when any per-editor token is already held); `:2074-2095` (`write_identity` carries the old `editor_report_token` forward); `installer/windows_bootstrap.ps1:2188-2194` (an existing config is skipped, with only "confirm these values match" printed into the log)
- **What:** I ran a probe: `ensure_config` for site A (`remote_root=/mnt/tankA/Creators`, a `cce1.` token), then for site B (`remote_root=/volume1/studioB/Tree`, no token). Result: `dashboard_url` became B, but `remote_root` stayed `/mnt/tankA/Creators` and `report_token` stayed A's token. `fleet_token_needed(...)` returned False, so B's wizard never shows the token field. Lane A then uploads to a path that does not exist on B's NAS, every report to B is refused with A's token, and the finish page says DONE. CR-265 (install-onboard-1) fixed the same A-to-B carry-over for the drive letter and tree name, but not for these keys. Separately, the product assumes one site per computer (one `dashboard_url`, one tree drive, one tailnet), so a freelancer working for two customers cannot have both installed. Running customer B's wizard converts the machine, with no "this computer is currently set up for <A>" warning. An editor signed in to their own or another customer's tailnet gets "that address does not exist on this network: check the spelling".
- **Scenario:** Once the product is sold to several studios, freelance editors move between customers. The second studio's install "succeeds", and the computer never appears on their fleet page.
- **Recommendation:** In `ensure_config`, when the existing `dashboard_url` host differs from the new one, treat the run as a site change: say so on the role page ("this computer is set up for <A>; continuing moves it to <B>"), force `remote_root` from the new manifest, drop `report_token` and identity `editor_report_token` (so the token step asks again), and archive the old config beside it. Decide and document whether one computer can serve two customers. If not, say so in START_HERE. Change the unknown-host message on the Tailscale page to name the likely cause: "is Tailscale signed in to <the customer>'s network? Open the Tailscale icon and switch".
- **Known:** CR-265 / install-onboard-1 (drive letter and tree name only, FIXED); this residual is not recorded

### prac-editor-onboard-9 - The Mac first-run advice ("right-click, Open") no longer works on current macOS, and the dashboard gives Mac editors no note at all

- **Severity:** medium
- **Confidence:** CONFIRMED (the repo's own build script gives the newer instruction)
- **Where:** `installer/START_HERE.md:72-75`; `tools/build_onboard_macos.sh:485-486` ("first open needs System Settings > Privacy & Security > 'Open Anyway'"); `dashboard/templates/installer.html` (a SmartScreen note for Windows only)
- **What:** Until a Developer ID and notarisation are bought (COMMERCIAL_READINESS item 4, blocked on purchase), the Mac wizard is ad-hoc signed. Since macOS 15 the control-click Open bypass no longer works for an unnotarised download: the user must try to open the app, then go to System Settings > Privacy & Security and click Open Anyway, and authenticate. START_HERE tells every Mac editor the old way. The installer page, which Mac editors are actually sent to, has the Windows "More info > Run anyway" note but nothing for macOS.
- **Scenario:** A Mac editor on macOS 15 or later follows START_HERE, gets "Apple could not verify ... is free of malware", finds no Open button, and concludes the download is broken or malicious.
- **Recommendation:** Update START_HERE with the macOS 15 path (System Settings > Privacy & Security > Open Anyway), and add the matching note under the macOS card on `/installer` (keep it until notarisation lands, like the Windows one). The real fix is item 4.
- **Known:** COMMERCIAL_READINESS item 4 (signing, open, blocked on purchase); the wrong doc text is not recorded

### prac-editor-onboard-10 - Mac: the install never asks for the Full Disk Access the sync tools need, and the first sign is a silent stall

- **Severity:** medium
- **Confidence:** PLAUSIBLE (that FDA is required on every Mac comes from `docs/macos-first-run-2026-08-05.md:165`, one Mac; that nothing asks for it is confirmed)
- **Where:** `docs/macos-first-run-2026-08-05.md:165, 215-219` ("Full Disk Access needed for the three binaries"); `installer/macos_bootstrap.sh`, `onboarding/onboard.py`, `installer/START_HERE.md`, `docs/EDITOR_SETUP.md` (no mention of Full Disk Access); `companion/src/ccsync_companion/app.py:3029-3062` (FDA is only mentioned after an upgrade)
- **What:** The one real Mac install needed Full Disk Access for the companion, rclone and Syncthing on an external SSD root. The wizard's Mac finish page and the docs don't mention it. The companion's only FDA message fires after a self-upgrade (`_check_macos_volume_access`), not on first run. Because the companion is ad-hoc signed, the grant is lost on every update (known, old item 16), and a Mac editor has to repeat a System Settings task nobody walked them through the first time.
- **Scenario:** A Mac editor puts their root on an external SSD as instructed and accepts or ignores whatever TCC prompts appear. Lane B then reports errors or zero progress, the tray says "Something went wrong", and the editor or admin goes through logs.
- **Recommendation:** On macOS, have the wizard's install page check access to the chosen root from each of the three binaries. If any is blocked, the finish page should list exactly which apps to add under Privacy & Security > Full Disk Access, with an `[ OPEN SETTINGS ]` button (`x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles`). Run the same check on every companion start, not only after an upgrade.
- **Known:** KNOWN_BUGS "macOS code-signing (was item 16)", open: covers the per-upgrade loss, not the first-run gap

### prac-editor-onboard-11 - Every editor is asked to accept the customer's B2B contract personally, including an indemnity and Taiwan jurisdiction, with links to repo paths they cannot open

- **Severity:** medium
- **Confidence:** CONFIRMED (text); the legal effect is for counsel
- **Where:** `onboarding/assets/EULA.md:16-19` ("between ... Licensor and the individual or organisation installing ... (the 'Customer', 'you')"), `:101-105` (indemnity), `:121-126` ("`docs/legal/TELEMETRY.md` ... Read it before deploying"), `:189-193` (governing law); `onboarding/onboard.py:459-535`; `dashboard/src/ccsync_dashboard/setup_engine.py:13, 58-98` (the organisation's admin already accepts the EULA in the dashboard setup wizard)
- **What:** The organisation accepts the EULA once during dashboard setup. The wizard then shows the full B2B agreement to every editor on every computer, and their ACCEPT makes "you", the editor, the Customer. They warrant the rights to the studio's music and stock, indemnify the Licensor, agree to New Taipei District Court, and are told to "read `docs/legal/TELEMETRY.md` before deploying", a repo path. What an editor actually needs is a short end-user notice: who runs this, what it reports about them (the controller is their studio), and where the studio's privacy notice is.
- **Scenario:** A freelance editor, or their agent, reads "you will indemnify the Licensor" and refuses to click, or a customer's legal team asks why their contractors are signing the vendor's contract personally. In either case the studio's onboarding stops.
- **Recommendation:** Put this to counsel: a separate end-user terms or notice for the wizard and the tray licence dialog, which names the customer from `org_name` as the party that deployed it. Keep the full EULA for the admin acceptance in the setup engine. Replace the repo paths with the dashboard's own served URLs for TELEMETRY and PRIVACY.
- **Known:** CR-5 (EULA drafting, done); the editor-versus-customer framing is not recorded

### prac-editor-onboard-12 - The editor-facing docs mix two install methods and carry stale and customer-specific instructions

- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `installer/START_HERE.md:85-262` (the hand-run package flow: "Run the setup script", "copy ccsync-companion.exe ... from this folder", "if you didn't pass -DashboardToken"); `:300-306` ("Update to a new build: your admin sends you a fresh package; run `.\windows_upgrade.ps1`", which contradicts `:59-61` "the companion updates itself"); `:200` and `docs/EDITOR_SETUP.md:138` ("`T:` is known to collide", one customer's server letters); `docs/EDITOR_SETUP.md:20, 161` ("TrueNAS username ... `server/setup_editor_account.py`", "they run `server/accept_device.py`"); `:28` ("your dashboard token"); `installer/windows_bootstrap.ps1:414, 2508`, `installer/macos_bootstrap.sh:1438, 1553, 1679, 2871` (output that points editors at `docs/EDITOR_SETUP.md`); `:303` vs `:315` (START_HERE says send "a screenshot of the tray menu", which contradicts its own "send the log, not a photo")
- **What:** START_HERE is the editor's one document. After its wizard section it carries about 200 lines of the older hand-run route, written as if the reader holds the package folder, which a wizard user does not. It also gives an update procedure the product no longer uses, a drive-letter warning that is only true for the first customer, TrueNAS- and script-specific admin steps, and a "dashboard token" that the wizard now hides. The bootstraps tell editors to read a repo file they never receive.
- **Scenario:** A new customer's editor follows the "Updating" section and asks the admin for a package. Or they avoid `T:` but map `S:`, which collides on their own studio's server. Or they look for `docs/EDITOR_SETUP.md` on their computer.
- **Recommendation:** Split START_HERE: a one-page "Editor: start here" for the wizard flow (finding 1's order, finding 6's Resolve steps, the Mac Gatekeeper path) and an "Admin: manual install" appendix. Derive the collision warning from site data (the server drive letters in the manifest) or word it generically. Serve the editor guide from the dashboard (`/help`) and point bootstrap output there. Remove the package-upgrade section.
- **Known:** none

---

Twelve findings: 3 high, 8 medium, 1 low.
