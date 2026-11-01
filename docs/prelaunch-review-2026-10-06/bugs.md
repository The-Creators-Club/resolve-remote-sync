# Pre-launch bug hunt 2026-10-06 (whole repo, by territory)

Part of the pre-commercial-launch review the owner asked for ("every single
thing that should be looked at or changed before going live commercially").
Scope: the whole CC Sync repo at HEAD `08b40eb` plus the UNCOMMITTED working
tree as it stood (alert-kind selection, companion fixes, the CR-356 folder-ignore
retirement, `docs/ZERO_DOWNTIME_DEPLOY.md`). Twenty-two Opus hunters ran on
disjoint territories: companion (`bug-app-a`, `bug-app-b`, `bug-sync`,
`bug-resolve`, `bug-comp-ui`, `bug-comp-trust`, `bug-comp-media`,
`bug-comp-ytdl`), dashboard (`bug-dash-api`, `bug-dash-db`, `bug-dash-auth`,
`bug-dash-ops`, `bug-dash-jobs-cards`, `bug-dash-ui`, `bug-dash-release`),
the web sub-apps (`bug-broll`, `bug-music`, `bug-ytdl-web`), `bug-server`,
`bug-installer`, `bug-tools-ci`, and the cross-component `bug-wire` lens. Every
critical and high was then put to one adversarial Opus verifier told to refute
it. Read-only throughout: no code, tests, KNOWN_BUGS.md or live systems were
touched; probes ran in scratchpads against repo code. Raw reports are in
`docs/prelaunch-review-2026-10-06/bugs/hunters/`, the merged machine-readable
list in `bugs/results.json`.

Each hunter checked KNOWN_BUGS.md and the 2026-09-24 hunt first; items already
FIXED there are not repeated. Items still OPEN that matter for launch are
included with their id under "Known".
## Tally

**175 raw findings (2 critical, 27 high, 81 medium, 65 low; 149 CONFIRMED by the hunter, 26 PLAUSIBLE).**
Merging duplicates across hunters (13 merges, sources cited per item) leaves
**162 distinct items**. After verification:

| Severity | Raw | After merge and verification |
|---|---|---|
| Critical (stop-ship) | 2 | 1 |
| High (before the first paying customer) | 27 | 11 |
| Medium (soon after launch) | 81 | 90 |
| Low (polish) | 65 | 60 |
| **Total** | **175** | **162** |

## Verifier outcome

29 items went to a verifier (2 critical, 27 high):

- **Critical: 1 CONFIRMED** (`bug-server-1`), **1 DOWNGRADED to high** (`bug-installer-1`: real, reproduced, but recoverable).
- **High: 10 CONFIRMED, 17 DOWNGRADED to medium, 0 refuted.**
- The downgrades are mostly "real mechanism, narrower blast radius than claimed": tailnet-only reach (`bug-dash-auth-3`), a documented design trade (`bug-dash-api-1`/`bug-dash-auth-5`, trust-model-1), needs repo write access first (`bug-dash-release-2`/`bug-tools-ci-1`), or needs an uncommon pair of events (`bug-app-a-1`, `bug-resolve-1`).
- Mediums and lows were not verified. Past passes refuted about 3% of theirs.

Nothing was refuted, so the "Refuted" section below is empty.

## 1. Stop-ship

Verified critical: the documented zero-touch appliance cannot be installed by a new customer.

### bug-server-1 - The appliance stack boots with no way for anyone to sign in
- Sources: `bug-server-1`. Hunter: critical/CONFIRMED. Verifier: CONFIRMED.
- Where: `dashboard/deploy/compose.appliance.yaml:153-173; settings.py:807; setup_routes.py:60-90; auth.py:158-165`
- What: compose.appliance.yaml sets no DASH_AUTH_METHOD (defaults to smb), no DASH_SMB_HOST and no DASH_ADMIN_USERS. Under smb the anonymous first-run window stays shut, every /api/v1/setup route needs an admin session, and the SMB probe runs against an empty host. check_boot_secrets does not object.
- Scenario: A new customer follows APPLIANCE_INSTALL.md (paste the compose, set CCSYNC_TREE/CCSYNC_DATA, up). /setup redirects to /login and no credential can pass: no admin, no wizard, no recovery without editing the compose. Probe: Settings.from_env() gives auth_method=smb, smb_host='', admins empty, boot raises nothing.
- Fix: Set DASH_AUTH_METHOD: "local" in compose.appliance.yaml and pin it in tools/tests/test_compose_appliance.py. Have check_boot_secrets refuse smb with an empty smb_host.
- Verifier note: Traced: no Dockerfile ENV, run.sh line or secrets-init sets the method; first_run_open is False under smb and is_admin needs DASH_ADMIN_USERS. APPLIANCE_INSTALL.md is DRAFT and no customer has run it, but it is the documented zero-touch path, so 'cannot install for a new customer' holds.

## 2. Before the first paying customer

Verified highs, including one critical the verifier downgraded to high. Grouped loosely: data loss on the editor's machine, then trust and access, then release and install.

### bug-sync-1 - Remove from this machine deletes originals lane A has not uploaded when their mtime is recent or in the future
- Sources: `bug-sync-1`. Hunter: high/CONFIRMED. Verifier: CONFIRMED.
- Where: `companion sync/rclone_lane.py:1792-1854, 2005-2058, 6779-6782; app.py:6203-6236, 6340-6392; tray.py:1926-1931`
- What: The removal gate's only originals check is a --dry-run of lane A's command, which carries --min-age 120s. rclone excludes files younger than 120 s and files with a future mtime (probed, rclone 1.74.4), so they count as nothing pending. The dialog says everything reached the server and rmtree deletes them. A future-dated clip never uploads at all and nothing reports it.
- Scenario: A camera clock set to local time abroad (FAT/exFAT times are zone-less) or a wrong camera year dates a card dump hours or years ahead. Lane A stays green while skipping it; the editor clicks Remove to free space and the only copy is deleted. Same for a render exported in the last 2 minutes.
- Fix: Run the gate's dry run without --min-age (and --min-size) so anything the NAS lacks blocks. Detect and report future-dated video in lane A; apply the age gate only to past mtimes or use express's size-stability test.
- Known: not recorded (APP-13 covers machine clock skew, not file mtimes)
- Verifier note: Traced removal_blockers -> scan_pending_uploads -> build_up_command(--min-age, --min-size) -> rmtree with no further check. Irreversible footage loss on an editor-initiated action; kept at high.

### bug-sync-2 - Removing an upload-only project deletes every non-video file while the dialog says nothing will be lost
- Sources: `bug-sync-2`. Hunter: high/CONFIRMED. Verifier: CONFIRMED.
- Where: `companion app.py:6171, 6236-6283; tray.py:1926-1931; docs/UPLOAD_ONLY_TICK.md section 5`
- What: Upload-only carries only VIDEO_EXTS up and lane C is off, so WAVs, stills, documents and project files exist only on this disk. removal_blockers asks only the lane A question for upload-only, the confirm says 'everything on this computer has reached the server', and remove_project_from_machine rmtree's the folder.
- Scenario: An ingest laptop ticks a shoot upload-only, dumps cards with separate-recorder WAVs, waits for uploads and clicks Remove: every sound recording is permanently deleted.
- Fix: Block, or require the typed confirmation, when the folder holds files lane A does not carry and that are not provably on the server (e.g. rclone check --one-way --size-only). Make the dialog claim only what was checked.
- Known: UPLOAD_ONLY_TICK.md records the upload limit as open, not the deletion
- Verifier note: Traced the filter (`- **` after video exts), the skipped lane C block, the unblocked dialog copy and the rmtree. Opt-in mode and editor-initiated, so high not critical.

### bug-installer-1 - The Windows bootstrap strips ACL inheritance from ~/.ccsync: every file and folder already inside becomes unreadable (install log, EULA record, state\ safety latches)
- Sources: `bug-installer-1`. Hunter: critical/CONFIRMED. Verifier: DOWNGRADED (critical -> high).
- Where: `installer/windows_bootstrap.ps1:551-575, 2179-2186; onboarding/onboard.py:526; onboarding/steps.py:2320-2341, 2500-2518; companion eula.py:146-160; sync/lane_guard.py:172-181`
- What: Protect-CCSyncPath runs icacls <dir> /inheritance:r /grant:r me:(F) SYSTEM:(F) Admins:(F) with no (OI)(CI). Children whose ACEs were all inherited end up with an empty DACL; nothing can be created in existing subfolders. Only config.toml and identity.json are re-granted. Reproduced in the scratchpad.
- Scenario: Every Windows wizard install: eula_accepted.json, logs/onboard-*.log and state/<breadcrumb> already exist when section 8 runs. The rest of the install log cannot be written, the EULA reads as not accepted (dialog shows again), and ~/.ccsync/state is permanently unusable, so lane_b_breaker.json, sync_halt.json, drive_unfinished.json cannot persist. A re-run on an existing machine makes a tripped breaker unreadable and lane B resumes.
- Fix: Grant with (OI)(CI) on directories, or harden files only (as secretfile.py does). Ship a repair (re-grant with (OI)(CI) /T) from the next bootstrap, windows_upgrade.ps1 and the companion at start. Add an installer test with a pre-existing child.
- Known: not recorded; CR-17 / COMMERCIAL_READINESS item 15 record this icacls as the fix
- Verifier note: Reproduced with the exact command. Downgraded because it is recoverable: install completes, sync runs, re-accepting the EULA works, the latches fall back to in-memory and say they cannot write. Still must fix before the first customer: every new Windows machine loses persisted safety state.

### bug-comp-ui-1 - shutdown() re-entry returns at once, so the process exits while Quit/Restart/self-upgrade teardown is still running on a daemon thread
- Sources: `bug-comp-ui-1`. Hunter: high/CONFIRMED. Verifier: CONFIRMED.
- Where: `companion app.py:11453-11469, 11939-11956, 6821-6855; tray.py:2433-2446, 5190; upgrade.py:2142-2147`
- What: Quit, Restart, stale-bridge recovery and self-upgrade call shutdown() off the main thread. shutdown() sets _stop_event before teardown; the main loop wakes, run()'s finally calls shutdown() again, which returns immediately ('already ran'), and the interpreter exits, killing the daemon teardown thread mid-way.
- Scenario: A self-upgrade or Restart while lane B runs rclone sync: the old process exits in milliseconds, lane_b.stop() (the only path that kills rclone) never runs, and on Windows the rclone child outlives it. The new build starts its own lane B on the same destination: the delete-authorised two-rclone race SYNC-1 / AUDIT_2 L-12/C-7 closed. note_clean_shutdown is never written, so three Quit/Restart cycles in 10 minutes read as a crash loop. Probe: repeat call returned in 0.016 s with lanes not stopped.
- Fix: Make the repeat call wait on a _shutdown_done Event (bounded ~30-40 s), or have Quit/restart/upgrade only set _stop_event and let the main thread do the single teardown (the revert path already does this). Add a regression test driving shutdown from a worker thread.
- Verifier note: Traced every caller and the daemon flag; no Job Object kills children on Windows. Fires on every self-upgrade fleet-wide. Not critical: lane B's destination is local proxies, originals are not at risk.

### bug-comp-ytdl-1 - A suspended, disabled or deleted editor keeps fleet-write access to YouTube jobs (and the b-roll/music fleet routes) through the shared token, indefinitely
- Sources: `bug-comp-ytdl-1`, `bug-ytdl-web-3`. Hunter: high/CONFIRMED. Verifier: CONFIRMED.
- Where: `dashboard ytdl.py:246-281 (YtdlGate/_fleet_stamp); ytdl/web/ytdlweb/routes_fleet.py:134-180, 242-283; ytdlweb/identity.py:64-95; api.py:2449-2455; same shape broll.py:338, music.py:208`
- What: CR-259g's account-bar check runs only for per-editor cce1 tokens. The shared report token (handed out by /verify by default) is stamped 'shared' with no account check, and the sub-app trusts the signed identity token (non-expiring since CR-86). Suspension, disable and deletion are never consulted on claim, heartbeat, manifest or clip-status; attestation survives suspension.
- Scenario: An admin suspends a departed freelancer. Their laptop can still claim any downloading job by sequential id, read manifests (URLs, project paths), land clips in the shared tree via lane A, post 'done' with made-up filenames (poisoning dedupe) or 'failed' for a colleague's clips. Default configuration.
- Fix: On AUTH_SHARED, verify the identity header in YtdlGate (and the b-roll and music gates) and refuse when api.account_bar_reason names that editor, or refuse barred identities once in login_gate's fleet bypass. Add server-side identity revocation (a deny-list by user and issued-at).
- Known: CR-259g / security-1 (marked FIXED; the shared-token path was never covered)
- Verifier note: Confirmed; the time limit is worse than the hunter said (identity tokens never expire since CR-86). A customer hits it the first time they offboard someone.

### bug-dash-auth-1 - /api/v1/login accepts NAS passwords for everyone on an OIDC site
- Sources: `bug-dash-auth-1`. Hunter: high/CONFIRMED. Verifier: CONFIRMED.
- Where: `dashboard api.py:2255-2293; auth.py:151-166; ui.py:1028-1034`
- What: With DASH_AUTH_METHOD=oidc the password form is break-glass for DASH_ADMIN_USERS only, and ui.py's /login enforces that. The JSON twin /api/v1/login does not, and verify_credentials runs the SMB probe for oidc. Any NAS SMB account gets a full session plus CSRF token, skipping the IdP, MFA, allowed groups and fleet membership. It also skips refuse_plaintext_login.
- Scenario: A leaver disabled in the IdP but with a NAS SMB account POSTs /api/v1/login: 200 and a session. Probed: a non-admin got 200 and /api/v1/me named them while POST /login refused the same user.
- Fix: Move the page_login_submit rules (oidc admin-only, plaintext refusal) into one helper both routes call; refuse with the same generic message and record a failure.
- Verifier note: Confirmed. Only OIDC sites, and needs a valid NAS password, so not critical; but it bypasses the control a customer chose SSO for.

### bug-comp-trust-1 - The one release signing key every customer trusts sits in plaintext on the everyday workstation
- Sources: `bug-comp-trust-1`. Hunter: high/CONFIRMED. Verifier: CONFIRMED.
- Where: `companion release_pubkey.py:56-58; %USERPROFILE%\.ccsync-release\release.key; tools/release_key.py:229; docs/COMMERCIAL_READINESS.md:144`
- What: RELEASE_PUBKEYS holds one key, generated by an agent session on the base rig. Its private half is an unencrypted file readable by any process running as alex on a machine that browses, runs yt-dlp and runs Claude Code. The docs call it 'offline'. The same key signs dashboard OTA bundles.
- Scenario: Malware, a poisoned dependency or an agent acting on injected content reads release.key and signs a companion (or dashboard bundle) every customer installs. It can also sign version == min_version 99.0.0, raising every machine's monotonic floor so every genuine build is refused; recovery is deleting upgrade_floor.json by hand on every machine. No revocation path.
- Fix: Before the first customer: generate the production key offline (hardware token or isolated VM), bake it, run the overlap release. At minimum DPAPI-wrap it like android.keystore.pw next to it. Keep .ccsync-release out of agent scope. Bake an emergency key and write a compromise runbook.
- Known: COMMERCIAL_READINESS item 4 ('decide keep/rotate before the first customer ship'): OPEN
- Verifier note: Confirmed on disk and in code. The key alone also needs a delivery channel, but the vendor feed is published from the same rig. Operational, not code; must be resolved before the first paying customer.

### bug-dash-release-1 - Dashboard auto-update re-applies a bundle that just crash-looped and was reverted, forever
- Sources: `bug-dash-release-1`. Hunter: high/CONFIRMED. Verifier: CONFIRMED.
- Where: `dashboard release_feed.py:1144-1153, 1189-1197; dashboard_update.py:1338-1374; deploy/select_code_root.py:427-441`
- What: The only guard against re-applying under policy=current is update_state step=='failed'. A bundle that passes stage-verify but fails to boot ends its apply with step 'done'; select_code_root's revert rewrites only current.json (reverted_from) and boot_attempts, which _dashboard_auto_apply_reason never reads.
- Scenario: Vendor ships dashboard X with a lifespan crash. Every policy=current site applies it, fails 2 boots, reverts, boots the good tree, polls 10 s later, sees step 'done' and soak passed, and applies X again: download, DB backup, ZFS snapshot, swap, restart, revert, indefinitely. Dashboard mostly down, a snapshot per loop.
- Fix: Treat current.json reverted_from==version as tried-and-failed; have revert write a durable do-not-auto-apply marker cleared only by a newer version or an explicit admin APPLY. Add an apply -> revert -> poll test.
- Verifier note: Traced end to end; preflight has no reverted-version check. Needs a vendor bundle that boot-crashes only on some sites, but then every default-policy customer loops.

### bug-server-3 - Syncthing GUI is an unauthenticated admin surface on both install paths
- Sources: `bug-server-3`. Hunter: high/PLAUSIBLE. Verifier: CONFIRMED.
- Where: `dashboard/deploy/compose.appliance.yaml:264-279; server/backends/truenas.py:304-323, 387-393; server/secure_syncthing_gui.py`
- What: Appliance: STGUIADDRESS 0.0.0.0:8384 inside tailscale's userspace-networking netns, which forwards inbound tailnet TCP to local listeners (the file relies on this for :22/:22000); no GUI user/password is ever set. TrueNAS: install_syncthing_app publishes the GUI on every interface with no password unless gui_bind is set and secure_syncthing_gui.py is run by hand; it only warns.
- Scenario: Any editor laptop on the tailnet (or anyone on the LAN on TrueNAS) opens :8384 and has full Syncthing admin over the whole tree: share any project folder to its own device (bypassing selections and tenancy), re-point folders, change delete behaviour.
- Fix: Bind the GUI to 127.0.0.1 and reach it via a shared netns, or have the dashboard set a GUI user and random password at boot with the API key. Make install_syncthing_app run the secure step itself.
- Known: COMMERCIAL_READINESS item 7 H4 (TrueNAS half, not run on either NAS); appliance half unrecorded
- Verifier note: Confirmed by reading; the appliance half rests on the userspace-netstack behaviour the compose file itself depends on (not probed on a live tailnet).

### bug-server-2 - Appliance dashboard is never wired to its own Syncthing, its release keys or the tailnet
- Sources: `bug-server-2`. Hunter: high/CONFIRMED. Verifier: CONFIRMED.
- Where: `dashboard/deploy/compose.appliance.yaml:153-203; settings.py:797, 840, 910; setup_engine.py:881-899; docs/APPLIANCE_INSTALL.md`
- What: Nothing sets SYNCTHING_GUI_URL (env-only; reachable at http://tailscale:8384). DASH_RELEASE_PUBKEYS is unset and the compose comment wrongly says it is generated at first boot (it must be the vendor key). Serve is never configured, so the dashboard stays on loopback. Unset DASH_NAS_KIND becomes 'truenas', contradicting the compose comment.
- Scenario: The Sync engine wizard step stays 'todo: SYNCTHING_GUI_URL not configured' forever, the collector provisions and shares nothing (lane C never works), feed/publish/OTA refuse without pubkeys, and companions cannot reach a loopback-only dashboard. The appliance syncs nothing.
- Fix: Add SYNCTHING_GUI_URL=http://tailscale:8384 (or share the netns) with a test; bake the vendor pubkey as non-secret data; finish WP B Serve before calling the appliance installable; fix the DASH_NAS_KIND default or comment.
- Known: APPLIANCE_INSTALL.md admits Serve/publishing NOT YET TRUE; Syncthing URL and pubkey gaps unrecorded
- Verifier note: Confirmed each part. The TrueNAS install path is unaffected, so high not critical.

### bug-installer-2 - On a machine with winget, rclone and Syncthing installed by winget are invisible to the same run: the first install ends NOT READY with no Syncthing set up, and bypasses the pinned verified binaries
- Sources: `bug-installer-2`. Hunter: high/CONFIRMED. Verifier: CONFIRMED.
- Where: `installer/windows_bootstrap.ps1:1089-1100, 1239-1248, 1281-1301, 1338-1343, 1951-1957, 2486-2488; onboarding/steps.py:1870`
- What: winget is tried before the pinned download. Rclone.Rclone and Syncthing.Syncthing are portable winget packages: PATH changes go to the registry and this process's $env:Path is never refreshed. rclone's re-probe fails (capability miss); for Syncthing $installed=$true skips the pinned fallback, Get-SyncthingExePath returns null, section 6 never runs (no generate, Run shim, daemon or device seeding). When winget succeeds the machine also gets winget's build, not the sha256-pinned one.
- Scenario: A new customer's editor runs onboard.exe on stock Windows 11. The bootstrap exits 3, the wizard shows NOT READY with three misses, the companion inherits the stale PATH ('rclone not found'), and lane C never starts. A re-run from the same wizard repeats it.
- Fix: Prefer the pinned verified download into $BinDir and drop winget or use it only as a fallback. If kept, refresh $env:Path from the registry after each winget call and probe WinGet\Links; never set $installed without a located exe; write the absolute rclone path into config.toml.
- Known: not recorded (ui-onboarding-4 is the same stale-PATH shape for Tailscale, fixed in the wizard only)
- Verifier note: Traced; no code mentions WinGet\Links. Most stock Windows 11 machines have winget.

## 3. Soon after launch

Mediums, grouped by theme. Items marked "Verifier: DOWNGRADED" were filed as high (or critical) and verified real at medium.

### Theme: Companion: sync lifecycle, removal and halts

#### bug-app-a-1 - Resume after a pause can leave a managed machine with no sequencer at all (sync silently dead until restart)
- Sources: `bug-app-a-1`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `companion app.py:10075-10127, 6697-6721, 6896-6908, 8150-8162, 9147-9178; sync/sequencer.py:695-705, 754-784`
- What: Managed Resume only calls sequencer.resume(), which never starts a thread. Every restart path (sign-in, halt release, fleet release, licence accept) goes through _start_lanes(), which refuses while paused and leaves _lanes_started False. A stopped sequencer reads thread_died()=False, so the watchdog never restarts it.
- Scenario: Editor pauses; admin fleet-halts and releases; editor resumes. Lanes A/B/C stay down while the tray says resumed and Sync now says 'Checking the server for changes now.' Same via token expiry plus sign-in while paused.
- Fix: On managed resume call _start_lanes() when not _lanes_started, else sequencer.resume(); make sync_now_result refuse when lanes were never started.
- Verifier note: Mechanism confirmed; downgraded because it needs two events in order, is fail-stopped and clears on restart.

#### bug-app-a-2 - Accepting the licence, or clearing a local halt, starts the lanes with nobody signed in
- Sources: `bug-app-a-2`, `bug-app-b-3`. Hunter: medium/CONFIRMED.
- Where: `companion app.py:6638-6646, 6666-6695, 8150-8162, 10155-10168, 11862-11879; tray.py:2139; settings_window.py:1676`
- What: The require_login gate is not in _lanes_refusal(); only start(), on_signed_in, _root_resume_lanes and toggle_pause apply it. The licence-accept path and release_halt call _start_lanes() directly.
- Scenario: An EULA re-consent reaches a machine whose token expired; the editor accepts and the lanes start on the cached selection while the reporter skips every cycle: syncing while invisible on the grid (the SYNC-3 shape).
- Fix: Add the login gate to _lanes_refusal() with _mark_lanes_pending_login as its action so every caller inherits it.

#### bug-app-a-3 - A fleet halt release also erases the editor's own local halt
- Sources: `bug-app-a-3`. Hunter: medium/CONFIRMED.
- Where: `companion sync/lane_guard.py:1421-1490; app.py:9147-9178`
- What: HaltState is one slot; a fleet engage over a local halt overwrites it and the fleet release clears it, unpausing lane C and calling _start_lanes().
- Scenario: Editor presses STOP ALL SYNC over a bad folder; an unrelated fleet halt is engaged and released; the editor's machine resumes syncing although they never released their stop.
- Fix: Track the local halt separately and fall back to it on fleet release.

#### bug-app-a-4 - Consolidate pulls proxies (lane B) for a project ticked upload-only on this machine
- Sources: `bug-app-a-4`. Hunter: medium/PLAUSIBLE.
- Where: `companion app.py:4407-4418; consolidate.py`
- What: _consolidate_upload_phase runs lane B for the open project without consulting the tick's sync_mode.
- Scenario: A laptop ticks a large project upload-only and runs COPY THIS PROJECT'S MEDIA IN; lane B then downloads every proxy and trashes local-only files.
- Fix: Skip the lane B pull (and say so) when the open project's tick is upload_only.

#### bug-app-b-1 - The reporter thread calls into Resolve in-process, so a wedged or modal Resolve stops that machine's reports, halt and pushed updates
- Sources: `bug-app-b-1`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `companion app.py:2566-2571, 8813, 9005; resolve_bridge.py:144, 2685, 2723; file_moves.py:953; reporter.py:1416`
- What: on_report_response runs inline on the reporter thread; _apply_resolve_undo and _apply_file_moves make live fusionscript calls behind _API_LOCK with no overall deadline.
- Scenario: Resolve sits on a modal dialog; an admin undoes or moves a file on that machine; the reporter thread never returns, and halts, updates, diagnostics and lane B resume stop reaching it until Resolve unwedges.
- Fix: Move undo replay and move relink to the watcher thread or a worker and answer 'retrying' until done; at least skip while bridge_activity() shows a call in flight.
- Verifier note: Downgraded: needs a rare admin action on a wedged Resolve, one machine only, self-clearing, no data loss.

#### bug-app-b-2 - The update stand-down test runs before a minutes-long download and is never repeated before the swap
- Sources: `bug-app-b-2`. Hunter: medium/CONFIRMED.
- Where: `companion app.py:6984-7002, 11591-11599; upgrade.py:1920-1986`
- What: _standing_down_would_kill_work() is checked once; download, verify, swap and shutdown() follow without asking again.
- Scenario: The out-of-tree popup reappears during the download, the editor clicks FIX ALL, and the process exits mid-copy leaving a partial .ccsync-tmp and a half-relinked project (CORE-H8/H5).
- Fix: Re-check the predicate in UpgradeManager.apply just before the swap and hold a standing-down latch that FIX ALL / consolidate / new popups refuse under; same for restart_self.

#### bug-comp-ui-2 - Quit is only confirmed for a FIX ALL copy; a CONSOLIDATE copy in flight is killed with no question
- Sources: `bug-comp-ui-2`. Hunter: medium/CONFIRMED.
- Where: `companion tray.py:2362-2411; popup.py:910-925; consolidate.py:405-503; app.py:6948-6966`
- What: _confirm_quit_while_copying reads only popup.copy_in_progress(); consolidate sets _consolidate_active, which restart/upgrade check but Quit does not.
- Scenario: Quit an hour into a Consolidate: a multi-GB .ccsync-tmp in the tree and possibly a copied clip Resolve was never repointed at.
- Fix: Have Quit consult _standing_down_would_kill_work() and show the same confirm.
- Known: RES-8 covered FIX ALL only

#### bug-comp-ui-3 - macOS: a quit Apple event (logout, restart, Activity Monitor Quit) exits through Tk's default handler, bypassing shutdown()
- Sources: `bug-comp-ui-3`. Hunter: medium/PLAUSIBLE.
- Where: `companion app.py:11812-11829; shutdown_guard.py:1145-1191; crash_report.py:586-605; supervisor.py:159-203`
- What: No ::tk::mac::Quit command is defined, so kAEQuitApplication makes Tk call C exit(): no atexit, no shutdown(), lanes not stopped.
- Scenario: Every Mac logout files a phantom UncleanExit; an Activity Monitor Quit is relaunched by the supervisor 10 s later; an rclone child is orphaned.
- Fix: Register root.createcommand('::tk::mac::Quit', ...) routing into app.shutdown() off the UI thread; verify on a Mac.
- Known: CR-316 fixed only the Windows WM_ENDSESSION half

#### bug-sync-3 - Borrowed folder of a renamed lender is re-pointed at an empty skeleton and silently stops syncing
- Sources: `bug-sync-3`. Hunter: medium/CONFIRMED.
- Where: `companion sync/borrowed_folders.py:230-240, 293-305; sync/sequencer.py:1350-1358, 2187-2195, 2318-2327`
- What: _repoint mkdirs want_path and re-points the Syncthing folder even when the move was skipped or failed; no .stfolder marker check, so reconcile reports ok.
- Scenario: Admin renames a lender project mid-pass; on every borrower the subtree stops syncing with no problem sentence, stranding unsynced edits and un-uploaded originals in the old directory.
- Fix: Mirror repath: never re-point after a failed/skipped move unless the target holds the marker; leave paused with a problem sentence; add the marker-missing check.
- Known: bug-comp-syncthing-7 fixed only the shared-folder twin

#### bug-sync-4 - File-move section 4b trashes a single file without checking the server holds that version
- Sources: `bug-sync-4`. Hunter: medium/CONFIRMED.
- Where: `companion file_moves.py:630-669`
- What: The folder branch checks rel+size at the destination; the single-file branch does src.replace(trash) unconditionally.
- Scenario: An editor's re-export (NAS has the first export, --ignore-existing) is moved into a project this machine does not sync; the re-export goes to .ccsync-trash and is pruned in 14 days.
- Fix: Apply the destination listing check to single files and keep the file (retrying) on mismatch or listing failure.
- Known: logic-plans-3 fixed the folder branch only

#### bug-sync-5 - File-move 4b bins a whole folder of un-synced non-video files when the server listing fails
- Sources: `bug-sync-5`. Hunter: medium/CONFIRMED.
- Where: `companion file_moves.py:503-541`
- What: On a failed listing a folder with no lane A original is trashed whole, assuming server-distributed proxies; lane C files often have not reached the server yet.
- Scenario: Fresh sound recordings in Audio/Day3 are moved by the admin before their lane C turn while the listing times out; the folder is trashed and pruned after 14 days, never having reached the server.
- Fix: On a failed listing answer 'retrying' for any folder holding files.

#### bug-sync-6 - Lane B sweeps proxies an editor generates locally (Resolve/BPG) into the trash, and a batch trips the breaker
- Sources: `bug-sync-6`. Hunter: medium/CONFIRMED.
- Where: `companion sync/rclone_lane.py:977-1026, 2273-2345; sync/lane_guard.py:1293-1345`
- What: Lane B is rclone sync over **/Proxy/**; any local proxy absent on the NAS is trashed after 120 s. Resolve's Generate Proxy and BPG default to <media>/Proxy/ and nothing carries them up.
- Scenario: A remote editor lets Resolve generate proxies for a card; two minutes later they are trashed, 50+ trip the lane B breaker (all proxy downloads stop until a human resumes) and are deleted after 14 days.
- Fix: Do not delete local-only proxies the NAS never had (explicit NAS-confirmed delete list), or carry editor proxies up; at least detect and warn instead of tripping.
- Known: SPEC.md line 54 records the companion-generator case only

#### bug-sync-7 - Server-side folder move does not end a handed-off upload from that folder, so it lands at the cleared path
- Sources: `bug-sync-7`. Hunter: medium/PLAUSIBLE.
- Where: `companion app.py:8786-8806; file_moves.py:684-690; sync/rclone_lane.py:3597-3626; sync/sequencer.py:2864-2876`
- What: CR-347 hand-off children can run for hours; repath/borrowed moves end children under the moved folder, file_moves.apply_move does not.
- Scenario: A 22 GB original still uploading into Card3; admin moves Card3; on a Mac the upload completes into a recreated old Card3 and lane A later uploads it again at the new path (Windows retries hourly instead).
- Fix: Call lane_a.end_handoffs_under(src) and stop in-flight runs over that subtree before apply_move touches disk.
- Known: CR-347 covers repath/borrowed only

#### bug-comp-media-1 - Quitting the tray during a whisper job often leaves the whisper worker running on the GPU
- Sources: `bug-comp-media-1`. Hunter: medium/CONFIRMED.
- Where: `companion jobs_runner.py:962-967, 1314-1347; app.py:11518-11522`
- What: JobRunner.stop() joins for 5 s; the child loop notices _stop only after 5 s waits and a heartbeat of up to 20 s; the whisper child is in its own process group and survives.
- Scenario: Quit or self-upgrade mid-transcription: the orphan keeps VRAM and writes sidecars; the restarted companion claims another whisper job (OOM), and the expired lease hands the first job to another machine (two writers).
- Fix: Keep the live Popen on the runner and have stop() kill_tree it; check _stop before the heartbeat; join for the kill budget.

### Theme: Companion: Resolve

#### bug-resolve-1 - UNDO LAST FIX right after a FIX ALL retires the journal and undoes nothing when the pool comes from the project library
- Sources: `bug-resolve-1`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `companion resolve_bridge.py:911-919, 1744-1847, 2723-2813; library.py:42-43, 738-779`
- What: undo_last_relink decides from get_media_pool_items(), which (library walk on) reads the project database; with Live Save off it still holds the pre-fix paths, so every entry is 'already_back' and mark_undone() retires the journal.
- Scenario: Live Save off, FIX ALL over 50 clips, UNDO within a minute: probe returned undone 0 / already_back 3, zero ReplaceClip calls, journal retired, tray stops offering undo.
- Fix: Decide undo from the live API walk or re-read each clip's live path; never mark_undone when undone == 0 unless verified against the API.
- Verifier note: Downgraded: needs Live Save off and no save in between; the .drp save point remains as rollback.

#### bug-resolve-2 - The library's 60 s staleness ceiling never fires while the watcher polls, so pool-only edits stay invisible to library readers
- Sources: `bug-resolve-2`. Hunter: medium/CONFIRMED.
- Where: `companion resolve_bridge.py:1164-1172, 1470-1507, 1823-1840`
- What: The stamp is reset on every non-cached walk and the watcher forces one every ~30 s, so _drop_library_path_cache never runs in production.
- Scenario: Probe: 20 simulated minutes of polls, 0 drops. A relink that does not move the fingerprint leaves the watcher, popup, plan_relinks, relink_moved and undo serving old paths all session.
- Fix: Stamp the cache-drop time separately; invalidate the path cache after every successful replace_clip / link_proxy_media.

#### bug-resolve-3 - UNDO LAST FIX is hidden behind an empty or un-replayable newer journal, and refusals are reported as clips that left the pool
- Sources: `bug-resolve-3`. Hunter: medium/CONFIRMED.
- Where: `companion resolve_journal.py:451-487, 537-541, 601-613, 713-727; resolve_bridge.py:2305-2338, 2693-2721, 2777-2813`
- What: note_save_point creates a journal before the edit; if the edit is refused that newest journal stays empty and hides older ones. A journal whose replays all fail is never retired. Refusals are counted as 'no longer in this project's media pool'.
- Scenario: FIX ALL at 10:00 (J1); a 10:20 proxy pass takes a save point (J2) and Resolve refuses the proxy; the tray's undo disappears and J1 is unreachable.
- Fix: Write the save-point outcome with the first record(); skip empty journals; step past or retire un-replayable ones; count refused separately.

#### bug-resolve-4 - Every b-roll insert, music import and stand-in upgrade takes a full SaveProject+ExportProject and opens its own journal (worker is a new process per request)
- Sources: `bug-resolve-4`. Hunter: medium/CONFIRMED.
- Where: `companion music_server.py:155-200; music_worker.py:300, 483-536; resolve_bridge.py:2305-2338, 3297-3303, 3558-3586; resolve_journal.py:117-118, 451-482, 543-560`
- What: save_point_due and burst grouping are in-process globals; each --music-resolve-worker child takes a save point and starts a journal on its first journaled ReplaceClip (every remote editor).
- Scenario: 40 archive clips sent in an afternoon: 40 whole-project exports on Resolve's main thread, 40 tens-of-MB .drp kept 60 days, and UNDO LAST FIX after a FIX ALL reverts the last b-roll clip to a machine-private path instead. Per-second journal names can collide.
- Fix: Persist the save-point time (like resolve_auto.json) or decide it in the parent; tag worker journals so UNDO LAST FIX skips them; add the pid to _session_path.

#### bug-resolve-5 - The macOS Resolve process probe uses pgrep -x "DaVinci Resolve", which probably never matches (the executable is Resolve)
- Sources: `bug-resolve-5`. Hunter: medium/PLAUSIBLE.
- Where: `companion resolve_prefs.py:149-153, 352, 447, 504; resolve_bridge.py:592-633; app.py:4747, 4814, 11996; installer/macos_bootstrap.sh:725 vs 1452`
- What: pgrep -x matches p_comm; the bundle executable is believed to be Contents/MacOS/Resolve; the installer's helper uses -f instead.
- Scenario: On a Mac with Resolve open, the LUT/stills reconcile writes config.dat under the running Resolve (overwritten on quit), 'Resolve is not running' is shown, and stale-bridge recovery restarts the companion.
- Fix: Use pgrep -f on the bundle path or accept both names; verify on the studio Mac; fix wait_for_resolve_quit too.

### Theme: Companion: trust, identity and updates

#### bug-comp-trust-2 - Downgrade floor is 0.0.0 on every signed record, so any older signed build can be pushed back onto a fleet
- Sources: `bug-comp-trust-2`, `bug-dash-release-3`. Hunter: medium/CONFIRMED.
- Where: `installer/build_editor_package.ps1:1043-1044; tools/sign_release.py:281, 460; tools/publish_feed.py:1042; tools/publish_latest.py:381, 419; tools/release_macos.sh:838; companion upgrade.py:726-776, 1502-1565`
- What: The floor only rises when a record carries min_version, and every publisher defaults to 0.0.0. 'Different, not newer' lets a dashboard offer any build ever signed, and commands.upgrade installs it unattended.
- Scenario: A compromised customer dashboard (or a replayed channel, bug-dash-release-4) makes an old signed companion with a since-fixed hole current; every editor installs it.
- Fix: Track a MIN_VERSION read by all signers, raise it at launch and at every security release; make sign_release refuse 0.0.0 for companion records without --allow-no-floor; print the stamped floor.
- Known: release-pipeline-8 (deferred 2026-08-21, open)

#### bug-comp-trust-3 - A second person signing in on a computer provisioned with someone else's per-editor token is locked out of the fleet
- Sources: `bug-comp-trust-3`. Hunter: medium/CONFIRMED.
- Where: `companion identity.py:146-176, 279-288, 498-506; onboarding/steps.py:3622; dashboard api.py:2649-2658, 2718-2724, 10172-10177, 11729-11734`
- What: preferred_report_token always prefers the cce1 token; tray sign-in swaps only the identity, and the dashboard refuses a cce1 token bound to another editor.
- Scenario: B signs in on A's provisioned laptop or a shared bay: sign-in succeeds, then every report/selection/job call 401/403s; the machine drops off the grid while the tray shows B.
- Fix: Have /verify say who owns the current token and drop or replace it on mismatch (or refuse the sign-in clearly); show 'this computer's key belongs to another editor'.

#### bug-comp-trust-4 - The loopback token adds nothing against local processes: any non-browser caller can send an allowed Origin
- Sources: `bug-comp-trust-4`. Hunter: medium/CONFIRMED.
- Where: `companion broll_server.py:2048-2104; loopback_guard.py:13-28`
- What: _post_authorised accepts an allowed Origin OR the token; Origin is only unforgeable for browsers.
- Scenario: Another OS account on a shared bay, or low-privilege malware, POSTs to 127.0.0.1:8899 with the dashboard Origin: claims ytdl jobs as the editor, inserts into their open timeline, starts ingest batches.
- Fix: Require the token unless browser-only evidence is present (Sec-Fetch-Site/Mode), or use a short-lived capability from the dashboard; fix the docstring.

#### bug-comp-trust-5 - On plain-http LAN, the unauthenticated site manifest is persisted and widens the loopback allow-list and the SMB target
- Sources: `bug-comp-trust-5`. Hunter: medium/PLAUSIBLE.
- Where: `companion site.py:142-198; loopback_guard.py:244; config.py:1912; reporter.py:1323-1420`
- What: /api/v1/site is cached to site.json and trusted; its dashboard_url joins the Origin allow-list and its smb_unc becomes the grade-swap SMB target.
- Scenario: A LAN attacker spoofs one response: their web page gains permanent loopback POST rights and the next grade swap sends the editor's NTLM credentials to their SMB server. Not over Tailscale.
- Fix: Make https/Tailscale the supported commercial transport; do not let the manifest widen the allow-list or set a foreign smb_unc.
- Known: 'require https site-wide' deferred (LEGAL_GAP plan section 6); manifest effects unrecorded

#### bug-wire-3 - A Mac's first install takes the channel's current package with no architecture check, so an Intel Mac is handed an arm64 companion
- Sources: `bug-wire-3`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `installer/macos_bootstrap.sh:106, 2398-2410; dashboard api.py:7375-7419; tools/release_macos.sh:683-699`
- What: REL-16's arch discriminator protects only the upgrade offer; the bootstrap downloads macos/current, checks sha and signature presence, and installs. Builds are arm64 only.
- Scenario: An editor on an Intel iMac installs; the companion cannot run (Bad CPU type) and the installer reports success.
- Fix: Pass ?arch=$(uname -m) and refuse mismatches server-side; check with file/lipo; ship universal2 or state Apple silicon is required and refuse x86_64 up front.
- Known: REL-16 fixed the upgrade offer only
- Verifier note: Downgraded: one declining hardware class, failed install not data loss; the urgent part is a clear refusal or a stated requirement.

#### bug-wire-4 - A Windows-on-ARM laptop reports arm64 while running the x64 companion, so once records carry arch it is never offered an update
- Sources: `bug-wire-4`. Hunter: medium/CONFIRMED.
- Where: `companion upgrade.py:157-176; dashboard api.py:6304-6323, 6528-6531; tools/release.ps1:600-606; build_editor_package.ps1:140-142; publish_latest.py:177-183`
- What: platform.machine() reports the native CPU; _arch_matches('x86_64','arm64') is False once arch signing (-EmitKindExtras) is on.
- Scenario: A Snapdragon X editor never receives another release, security fixes and EULA updates included.
- Fix: Treat an x86_64 Windows record as installable on arm64, or report process architecture; add a test.
- Known: REL-16 (discriminator); this mismatch unrecorded

### Theme: Companion: media, ingest and YouTube

#### bug-comp-media-2 - A 409 from /uploaded is re-posted before the re-upload starts, so the retry budget is gone in seconds while files still upload
- Sources: `bug-comp-media-2`. Hunter: medium/CONFIRMED.
- Where: `companion broll_ingest.py:3083-3084, 3134-3135, 3150-3167; broll_upload.py:294-309, 409-413`
- What: UploadQueue dedupes only against active/queued jobs and uploaded() still returns the old DONE entries, so the next pump sees nothing missing and re-posts immediately.
- Scenario: Server cannot stat an original; the pump spends MAX_UPLOAD_ATTEMPTS in seconds and fails the clip while rclone is still pushing 40 GB, leaving an orphan on the NAS. Music shares the pump.
- Fix: Forget done-ledger entries for re-declared rels (or track an upload generation) and re-post only once they land; re-send only detail.missing.

#### bug-comp-media-3 - Music: two picked .ogg files with the same name transcode to one out/<stem>.mp3, so a track can be uploaded with the other's audio
- Sources: `bug-comp-media-3`. Hunter: medium/CONFIRMED.
- Where: `companion music_clap_sidecar.py:777; broll_ingest.py:1597-1607, 2455-2463; music_ingest.py:342-366, 610-670`
- What: transcode_to_mp3 writes dest_dir/<stem>.mp3 into one per-batch out/; picked tracks keep their real names and the upload is asynchronous.
- Scenario: Disc 1/Theme.ogg and Disc 2/Theme.ogg: track 1's library row goes live with track 2's audio while its embedding and hash are track 1's. Size checks pass.
- Fix: Name transcode output per item (out/<item uid>.mp3) or use a per-item subdirectory.

#### bug-comp-ytdl-2 - The tray's YouTube terms are a materially shorter text recorded under the same TEXT_VERSION as the web notice
- Sources: `bug-comp-ytdl-2`. Hunter: medium/CONFIRMED.
- Where: `companion ytdl_attestation.py:49-84; ytdl/web/ytdlweb/attestation.py:46-80`
- What: The tray omits the ToS-restriction, 'no representation of lawfulness' and 'what is recorded' sentences, yet records version 2026-08-17.1. No test compares the texts though comments claim 'word for word'.
- Scenario: In a dispute the record claims agreement to wording the editor never saw.
- Fix: Use one source text verbatim with a CI equality test; bump TEXT_VERSION both sides; store a hash of the shown text; counsel to review.

#### bug-comp-ytdl-3 - The signed-in YouTube session (cookies.txt and the Chromium login profile) survives sign-out, so the next person downloads as the previous person's Google account
- Sources: `bug-comp-ytdl-3`. Hunter: medium/CONFIRMED.
- Where: `companion ytdl_cookies.py:80-104; ytdl_browser_login.py:32, 211-213; app.py:6910-6924; identity.py:554-560; ytdl_executor.py:2999-3020`
- What: The jar and profile belong to the OS user, not the CC Sync editor; sign-out deletes only identity.
- Scenario: On a shared suite PC, B's bot-checked clips are retried with A's cookies; A's live Google login stays in the kept profile.
- Fix: Record which editor installed the jar and ignore it for others; delete jar, status and profile on sign-out / forget-this-computer.

#### bug-comp-ytdl-4 - Free space is checked once, at the claim, so one local YouTube job can fill the editor's disk to zero
- Sources: `bug-comp-ytdl-4`. Hunter: medium/CONFIRMED.
- Where: `companion ytdl_executor.py:2265-2278, 2422-2453, 2689-2700`
- What: Only a 200 MB + 5 GiB check before the claim; nothing re-measures per clip or per conversion (which needs two copies).
- Scenario: 6 GB free, a 40-clip job or a 2-hour conversion fills the drive; Syncthing, lane B, Resolve and the tray's state writes fail before the breaker trips.
- Fix: Re-measure before each clip and conversion and hand back with an editor sentence below margin plus estimate.
- Known: server-side twins CR-263b / CR-286L fixed

#### bug-comp-ytdl-5 - Every editor machine takes the newest yt-dlp nightly daily, with no remote way to pin, hold or roll back a bad build
- Sources: `bug-comp-ytdl-5`. Hunter: medium/CONFIRMED.
- Where: `companion ytdlp_manager.py:80-83, 125, 934-1022; ytdl/web/ytdlweb/routes_fleet.py:294-301`
- What: CR-361 runs --update-to nightly every day; the client config only has a min version; the only off switch is a hand edit per machine.
- Scenario: A regressed nightly reaches every customer's machines within 24 h; the vendor cannot hold or downgrade.
- Fix: Add ytdlp_channel (nightly/stable/pin:<v>) and max version to client config and site manifest, honoured via --update-to <channel>@<tag>; optionally an N-hour delay.
- Known: CR-361 (BUILT, unshipped)

### Theme: Dashboard: authentication, accounts and request safety

#### bug-dash-api-1 - Deleting an editor on an smb/oidc site does not stop their companion: it re-registers them as a known editor and erases a prior suspension
- Sources: `bug-dash-api-1`, `bug-dash-auth-5`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `dashboard api.py:228-271 (_account_refusal), 5114-5143, 5178-5300 (delete_user_everywhere), 10144-10270 (api_report); db.py:2803 (suspended_editors), forget_editor; auth.py:74, 375-391; settings.py:135`
- What: Outside local mode _account_refusal knows only suspension, stored on the known_editors row forget_editor deletes. The shared token (on by default) and the never-expiring identity token still pass, and the report calls record_known_editor.
- Scenario: Probe: suspend -> 401; delete -> report 200, locate 200, claim 200; the person is a known editor again with suspended_at None and back on the grid.
- Fix: Write a durable removal tombstone checked on every auth method; keep suspension off the deletable row; add per-identity revocation (trust-model-1); ship new sites with the shared token off.
- Known: trust-model-1 / CR-86 trade (OPEN); the deletion-erases-suspension half is new
- Verifier note: Both verifiers downgraded: the same delete removes the NAS account, Syncthing devices and selections, so no footage flows; re-suspend or disabling the shared token is a workaround.

#### bug-dash-auth-2 - Browser sign-in on smb sites checks the password only: no fleet membership, and suspension does not stop sign-in or NAS writes through the dashboard
- Sources: `bug-dash-auth-2`, `bug-dash-api-7`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `dashboard ui.py:984-1081; api.py:2255-2293, 2435 (only api_verify calls _require_fleet_member), 3699, 4107, 4177, 4863-4885`
- What: /login and /api/v1/login mint a session for any account the NAS SMB service accepts; suspension is never checked at sign-in and revokes no session. A suspended person can still create project folders and markers, adopt folders and claim roots.
- Scenario: A bookkeeper or guest SMB account browses the libraries, creates client-folder links (public Funnel URLs) and queues AI/ytdl work; a suspended freelancer creates 2026/<anything> folders visible to every editor.
- Fix: Call _require_fleet_member (and _account_refusal) in both sign-in routes; gate session-only write routes on _account_refusal; optionally revoke sessions on suspend.
- Known: contradicts KNOWN_BUGS trust-model-5 / CR-56 wording; DCORE-4 keeps suspension and sign-in independent on purpose
- Verifier note: Downgraded: needs a valid NAS password on the customer's own NAS, inside the tailnet; the suspension half is a documented design choice.

#### bug-dash-auth-3 - The login throttle can be bypassed with concurrent requests (unbounded on local accounts, plus a scrypt memory DoS)
- Sources: `bug-dash-auth-3`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `dashboard ui.py:1019, 1042; api.py:2268, 2422; sessions.py:580-671; auth.py:159`
- What: Check-then-act throttle: blocked_until is written only after a failure is recorded. Local verifies are 32 MiB scrypt each with no concurrency cap.
- Scenario: Probe: 100 concurrent /login attempts ran the verifier 100 times against a limit of 5; ~40 concurrent scrypts hold ~1.3 GB and starve the threadpool.
- Fix: Reserve each attempt atomically under _write_lock before verifying; semaphore local scrypt and answer busy.
- Verifier note: Downgraded: /login is reachable only from the tailnet (Funnel exposes only /broll/share).

#### bug-dash-auth-4 - OIDC identity is the mutable preferred_username claim, matched straight against DASH_ADMIN_USERS
- Sources: `bug-dash-auth-4`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `dashboard oidc.py:280-312, 347-348, 359-365, 498`
- What: Nothing binds the name to (iss, sub); the admin-name shortcut runs before the allowed-groups gate; an empty fleet skips membership.
- Scenario: In an IdP that lets users edit their username, a user renames to the admin's name and gets a full admin session.
- Fix: Bind (iss, sub) at first sign-in; apply the group gate before the admin shortcut; document that the claim must not be user-editable.
- Verifier note: Downgraded: default configs of the named IdPs keep the claim admin-managed; OIDC is optional.

#### bug-dash-api-2 - The package routes 'make current' and 'roll the fleet back' are CSRF-exempt session routes
- Sources: `bug-dash-api-2`. Hunter: medium/CONFIRMED.
- Where: `dashboard app.py:234, 1083; api.py:7091 (api_set_current_package), 7281 (api_roll_fleet_back)`
- What: /api/v1/admin/packages/ skips both the CSRF token and the Origin check, though these routes authenticate by session cookie with simple query-string POSTs.
- Scenario: Probe: POST with Origin http://evil.example reached the handler while a control route got 403. A same-site page (another tailnet host or NAS port) can make an old build current past the soak gate.
- Fix: Remove the prefix from the exemption (publish tools already get a csrf token at login), or keep the Origin check for POSTs.

#### bug-dash-api-3 - Any fleet member can take another editor's Syncthing device by reporting its id; cloned PCs flip-flop, and invariant 3 reads OK
- Sources: `bug-dash-api-3`, `bug-dash-db-4`. Hunter: medium/CONFIRMED.
- Where: `dashboard api.py:7876-7906 (_register_machine); db.py:5201-5238 (release_device_id_elsewhere); collector.py:1484-1495, 1556-1580; invariants.py:375-433`
- What: The self-reported device id is moved off every other row, across editors, with no check against Syncthing's label. Exactly one row ever holds it, so the 'claimed twice' invariant cannot fire.
- Scenario: Probe: bob reports B then alice reports B; the enforce cycle shares alice's projects with bob's computer and unshares bob's. PCs imaged from one master flip every 30 s; an insider redirects a colleague's device.
- Fix: Scope the release to the reporting editor's rows; on a cross-editor collision refuse and raise a notice naming both; persist contention so invariant 3 can see it; validate against the device's mapped editor.

#### bug-dash-ui-2 - No browser security headers on any dashboard response
- Sources: `bug-dash-ui-2`. Hunter: medium/CONFIRMED.
- Where: `dashboard app.py (no middleware sets nosniff, X-Frame-Options/frame-ancestors, Referrer-Policy or CSP)`
- What: HTML, PlainText, /help and static responses carry none of them.
- Scenario: A same-site origin can frame admin pages (fleet halt, user delete, package publish are one click each); any customer security review flags this on day one.
- Fix: One middleware: nosniff, frame-ancestors 'self' + X-Frame-Options SAMEORIGIN, Referrer-Policy same-origin; plan a script CSP later.
- Known: docs/MOBILE_PLAN.md:47 notes 'Security headers: none'

### Theme: Dashboard: data model, collector and alerts

#### bug-dash-api-4 - NEW PROJECT, USE THIS FOLDER and file moves accept names Windows cannot create, so Windows editors cannot sync the project
- Sources: `bug-dash-api-4`. Hunter: medium/CONFIRMED.
- Where: `dashboard api.py:3772-3787 (_validate_tree_part) and its callers`
- What: The validator allows : * ? " < > |, trailing dots/spaces and reserved names like CON.
- Scenario: Probe: 'Shoot: Day 1', 'Q&A?', 'CON', 'Final.' accepted; mkdir fails on Windows, 'Final.' becomes 'Final', rclone maps ':' to fullwidth.
- Fix: Refuse those characters, trailing '.'/space and reserved stems in _validate_tree_part; report existing invalid folders as a notice.

#### bug-dash-db-1 - The unassigned plan bucket never empties, so every new computer a person registers starts syncing it
- Sources: `bug-dash-db-1`. Hunter: medium/CONFIRMED.
- Where: `dashboard db.py:7061-7108, 7147-7176, 7715-7739, 7831-7921; collector.py:1376-1382`
- What: Ticking before a person's first computer writes machine=''; nothing ever moves it, so it applies to every later machine, contradicting MULTI_MACHINE_PLAN 3.2 ('a new machine starts empty').
- Scenario: Probe: eve's new LAPTOP months later inherits projects a and b; the enforce cycle shares them and lane B downloads every proxy.
- Fix: Move bucket rows onto the first registered computer in _register_machine's transaction; add a DESK/LAPTOP regression test.

#### bug-dash-db-2 - Archiving a project or suspending an editor raises false error alerts that every tick is 'not shared'
- Sources: `bug-dash-db-2`. Hunter: medium/CONFIRMED.
- Where: `dashboard notices.py:557-608; invariants.py:286-330; collector.py:1474-1520`
- What: _check_plan_without_share and invariant 1 do not filter archived slugs or suspended editors.
- Scenario: Archive a project ticked on 8 computers: 8 error notices, invariant 1 BROKEN, alert mails until unarchived, advice to 'untick and re-tick'.
- Fix: Apply archived_project_slugs and suspended_editors once inside fetch_machine_selections(for_enforce=True) and use it in both readers.

#### bug-dash-db-3 - After a computer is renamed, its old name stays on the grid for 30 days, raises daily 'gone quiet' error alerts, and FORGET answers 404
- Sources: `bug-dash-db-3`. Hunter: medium/CONFIRMED.
- Where: `dashboard db.py:6944-7058 (adopt_renamed_machine), 8886-8900; api.py:1058-1105, 5391-5409; alerts.py:1580-1605`
- What: The rename moves the plan and deletes the registry row but leaves machine_state, lane_report_current, transfers, media, report_auth and stand-in rows; forget needs a registry row.
- Scenario: Owner gets 'OLD has not been in touch' mails for two weeks and cannot remove the ghost row.
- Fix: Re-key or delete the old name's rows in every per-machine table; let FORGET sweep by (editor, machine) without a registry row.

#### bug-dash-ops-1 - Weekly report and daily heartbeat are sent over SMTP/webhook while the collector holds the SQLite write lock
- Sources: `bug-dash-ops-1`. Hunter: medium/CONFIRMED.
- Where: `dashboard alerts.py:5284, 5310, 5325, 5374-5404`
- What: _record_delivery_budget always writes, then the sends use send() not _send_committed(); probe showed in_transaction=True during transmit.
- Scenario: A slow relay at the heartbeat slot or Monday 08:00 holds the lock for up to tens of seconds; every report in that window returns 500 'database is locked'.
- Fix: Send through _send_committed or commit first; add both paths to test_db_write_locks.

#### bug-dash-ops-2 - Completion pass calls Syncthing /rest/events after it has started writing, every cycle
- Sources: `bug-dash-ops-2`. Hunter: medium/CONFIRMED.
- Where: `dashboard collector.py:2181-2257`
- What: _ingest_item_finished makes up to two 10 s events() calls inside the open write transaction (probed).
- Scenario: A slow NAS Syncthing holds the write lock up to 20 s every minute; editors' reports fail.
- Fix: Commit before _ingest_item_finished or fetch events with the other HTTP reads.

#### bug-dash-ops-3 - Provision pass holds the write lock across every project's Syncthing calls and tree walks once any notice is filed
- Sources: `bug-dash-ops-3`. Hunter: medium/CONFIRMED.
- Where: `dashboard collector.py:672-692, 743-755, 779, 805, 947, 986-1003, 1112, 1133`
- What: db.notice inside the loops opens the transaction; ignores, folder puts, os.walk and marker reads then run under it.
- Scenario: A copied project folder (duplicate_slug_dirs) makes every 5-minute cycle hold the lock across N Syncthing round trips; reports fail for that span.
- Fix: Buffer notices until after the HTTP/filesystem phase (as _run_inventory does), or commit after each.

#### bug-dash-ops-4 - Triage agent's read-only scope is not enforced: Read/Grep/Glob reach the whole container, and the report is mailed unscrubbed
- Sources: `bug-dash-ops-4`. Hunter: medium/PLAUSIBLE.
- Where: `dashboard triage.py:207-214, 415-560, 657-690`
- What: Nothing confines the tools to the run and package dirs; scrub_text is applied to evidence, never to the model's output; evidence includes editor-controlled strings.
- Scenario: An editor plants instructions in a reported error; the run quotes /proc/1/environ or /data/secrets/dash_session_secret into a webhook channel or mailbox.
- Fix: Deny Read outside the run/package dirs via a permissions file; scrub the composed subject/body with live secret values; mark evidence as data; consider a separate uid.

#### bug-dash-ops-5 - Synology SSH without a pinned host key trusts every connection (not TOFU) and sends the DSM admin password on it
- Sources: `bug-dash-ops-5`. Hunter: medium/CONFIRMED.
- Where: `dashboard nas/synology.py:1054-1063, 1079-1128; server/install_dashboard_app.py:2663-2670`
- What: A fresh SSHClient with AutoAddPolicy and no stored keys on every connection; the deploy carries only site.toml ssh_hostkey, not the base rig's recorded key.
- Scenario: Anything answering on the NAS SSH address from the container's network gets the DSM admin password on the next Users page render.
- Fix: Persist known_hosts under <data>/secrets with RejectPolicy after first add, or refuse without a pin; carry the base rig's key into DASH_NAS_SSH_HOSTKEY.
- Known: COMMERCIAL_READINESS H2 / CR-9 cover the base-rig side only

#### bug-dash-ops-6 - SMTP port 465 (implicit TLS) can never work, though the Alerts page recommends it
- Sources: `bug-dash-ops-6`. Hunter: medium/CONFIRMED.
- Where: `dashboard alerts.py:742-746, 758-799; templates/partials/admin_alerts.html:134`
- What: Always smtplib.SMTP with STARTTLS; on 465 both sides wait for the other until a 20 s timeout.
- Scenario: A customer whose relay offers only 465 gets no alerts, reports, heartbeat or triage mail, with a network-looking error.
- Fix: Use SMTP_SSL on 465 (or a TLS-mode setting); otherwise refuse 465 at save and fix the tooltip.

#### bug-wire-1 - Retrying file moves and parked undos hold the head of the offer queue, so newer commands are never delivered and lane A puts the files back
- Sources: `bug-wire-1`. Hunter: medium/CONFIRMED.
- Where: `dashboard db.py:6377-6410, 6532-6540, 6751-6777; companion file_moves.py:65-67; sync/rclone_lane.py:3368-3383`
- What: pending_file_moves offers the oldest 20 undelivered-or-retrying targets; 20 retrying moves fill every reply for ~20 hours. Same with LIMIT 4 for parked undos.
- Scenario: 25 clips moved while open in Resolve: 1-20 retry; 21-25 are never sent, and lane A re-uploads them to the old paths (duplicates).
- Fix: Offer never-delivered targets first (ORDER BY delivered_at IS NOT NULL, id) or always include every undelivered target; same for undos, parked last.

#### bug-wire-2 - File-move answers are unbounded on the companion, capped by a raising 64 on the dashboard, and lost for good when a report fails
- Sources: `bug-wire-2`. Hunter: medium/CONFIRMED.
- Where: `dashboard api.py:9944; companion app.py:8930-8934, 9042-9065; reporter.py:1026-1033, 1383-1388`
- What: file_moves_applied max_length=64 raises (probed); the companion sends its whole queue, drains it at build and never restores it on failure; relink_pending is cleared before queuing.
- Scenario: 80 'relinked after all' answers on project open: the report 422s, lanes and alarms are lost, and the project page says 'Resolve not repointed yet' for all 80 for good.
- Fix: Make these sections truncate instead of reject; cap at 64 and carry the rest; requeue on POST failure or keep relink_pending until accepted.
- Known: related to fixed bug-wire-1/-6 (2026-09-25); this loss path unrecorded

### Theme: Timeline Cards and the fleet job system

#### bug-dash-jobs-cards-1 - A percent-encoded ? or # walks past CardsGate: /cards/p/<slug>/api/root%3F reaches engine.set_root()
- Sources: `bug-dash-jobs-cards-1`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `dashboard cards.py:421-464 (CardsGate, _gate_readings); cards_wsgi.py:200-219 (request_head)`
- What: uvicorn decodes %3F into the path; _gate_readings does not cut at '?'/'#'; request_head builds 'POST /api/root? HTTP/1.0' and the handler's urlparse sees /api/root. Decoded CRLF can inject header lines.
- Scenario: A signed-in editor moves engine A onto episode B (two engines read-merge-writing B's cut list) or onto any container dir.
- Fix: Cut gate readings at '?'/'#', refuse CR/LF/NUL, or re-quote PATH_INFO in request_head; add tests for %3F, %23, %0D%0A.
- Known: sibling of fixed bug-dash-cards-jobs-1
- Verifier note: Downgraded: needs a signed-in user hand-crafting a URL; the /api/restart half is stopped by the mount's server.shutdown() refusal.

#### bug-dash-jobs-cards-3 - Each Cards agent long-poll holds one of the 40 shared threadpool workers; about 40 agents stall /report
- Sources: `bug-dash-jobs-cards-3`. Hunter: medium/PLAUSIBLE.
- Where: `dashboard cards_tunnel.py:200-230, 430-500; deploy/run.sh:593, 608`
- What: /cards/agent/pending is a blocking sync route holding a worker up to 25 s back to back in a single-process server.
- Scenario: A 40+ machine customer turns the Cards role on; /api/v1/report queues behind the polls and the grid goes stale.
- Fix: Make the long poll async (asyncio.Event) or use a capped executor; raise the anyio limiter; jitter the no-engine hold.

#### bug-dash-jobs-cards-4 - Closing a Cards episode frees the seat but leaks the engine (threads and ~128 MB); open/close cycles grow the dashboard until OOM
- Sources: `bug-dash-jobs-cards-4`. Hunter: medium/CONFIRMED.
- Where: `dashboard cards_pool.py:707-730, 753-766; MulticamPipeline cards/project_agent.py:686`
- What: engine.stop() only sets a flag the library, tokens and translator threads ignore; the cap counts entries, so each close lets a new engine be built.
- Scenario: A week of episode switching without a restart fills NAS RAM and the dashboard (fleet status, client links) is OOM-killed.
- Fix: Land the real stop() upstream before selling Cards; meanwhile count leaked engines in health, refuse opens past a ceiling, add an alert.
- Known: CARDS_TWO_PROJECTS.md section 6.1 (open)

#### bug-dash-jobs-cards-5 - Montage sessions in <data>/cards_sessions are never pruned: unbounded disk and indefinite retention of interview transcripts
- Sources: `bug-dash-jobs-cards-5`. Hunter: medium/CONFIRMED.
- Where: `dashboard cards_ai.py:648-668, 1209-1222`
- What: Each conversation is stored whole with corpus parts; nothing deletes or reports them; not covered by account deletion or retention docs.
- Scenario: Months of searches fill /data below the 2 GB critical floor; transcripts kept outside the vault indefinitely.
- Fix: Prune in the collector (age + file cap), report count/bytes in health, document in privacy/retention docs.
- Known: DDIAG-19 (open)

### Theme: Release, supply chain and CI

#### bug-dash-release-2 - Container image path bypasses the offline release key: :1 moves on any v* tag push with no CI/main/version gate, actions are tag-pinned, and the documented cosign verify accepts any identity
- Sources: `bug-dash-release-2`, `bug-tools-ci-1`, `bug-tools-ci-2`, `bug-tools-ci-7`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `.github/workflows/image.yml (triggers, tag computation, build-push, tag-pinned actions with packages:write/id-token:write); dashboard/deploy/compose.appliance.yaml:88, 147, 291; docs/DOCKER.md:548-565; server/install_dashboard_app.py:1419-1627 (:edge advice)`
- What: Any v* tag pushes :<VERSION> and :1 with no needs: on tests, no ancestor-of-main check, no tag==VERSION or newer-than-:1 check, and no refusal to overwrite an existing :<VERSION>. workflow_dispatch from any branch moves :edge, which the installer recommends. Docs verify with --certificate-identity-regexp '.*'. Nothing in the product verifies the image.
- Scenario: A red or branch commit tagged v0.7.74, or an old commit re-tagged as a hotfix (0.7.50 code against a v58 schema), becomes every appliance's next pull; a compromised tag-pinned action can push :1; a lookalike image signed from any repo passes the published verify.
- Fix: Gate :1/:VERSION on main ancestry plus a green ci.yml run behind a protected environment; require tag == v$VERSION and newer; never overwrite :<VERSION>; restrict :edge to main; pin actions by SHA; publish an exact-identity cosign verify; consider carrying the image digest in the signed channel and checking it.
- Known: release-pipeline-9 (mutable :1 tag, deferred)
- Verifier note: Both verifiers downgraded: every path needs repo write access or a prior supply-chain compromise; it is release hardening, not a defect a customer triggers.

#### bug-dash-release-4 - No channel freshness check: the feed host can replay an old signed channel to roll back policy=current fleets and hide later recalls
- Sources: `bug-dash-release-4`. Hunter: medium/CONFIRMED.
- Where: `dashboard release_feed.py:395-433, 870-875, 1010-1023; package_store.py:251-261; docs/RELEASE_FEED.md:231-235, 503-505`
- What: A channel is accepted whenever its signature verifies; last_channel_generated_at is stored but never compared; backwards pointers are honoured and bootstrap_ok skips soak.
- Scenario: After a security fix ships, whoever controls the release assets serves the older channel; every policy=current dashboard makes the vulnerable build current.
- Fix: Persist the highest accepted generated_at and refuse lower ones with a notice; optionally a max age; correct the threat model doc.

#### bug-dash-release-5 - publish_feed merge lets a stale local feed/ dir overwrite the live channel's current pointer and records
- Sources: `bug-dash-release-5`. Hunter: medium/CONFIRMED.
- Where: `tools/publish_feed.py:275-314, 1186-1198, 1567-1578`
- What: Every local pointer and record overrides the published channel; the shrink guard only detects removals. Probe: published 0.9.82 + local 0.9.83 -> merged 0.9.83.
- Scenario: A withdrawn 0.9.83 (set back from a laptop) is re-made current by the base rig's next unrelated publish.
- Fix: Overlay only what this run changed, or refuse when a local pointer/record differs from the published one unasked.

#### bug-dash-release-6 - ship.cmd -PublishFeed makes a dirty or untested onboard installer current on the vendor feed, past every gate
- Sources: `bug-dash-release-6`. Hunter: medium/CONFIRMED.
- Where: `tools/ship.ps1:375-390, 1019-1046; tools/publish_feed.py:962-973`
- What: The onboard feed mirror passes no manifest, so the dirty and tests_run gates never run and --make-current is always passed.
- Scenario: ship.cmd -AllowDirty -PublishFeed: the companion publish is refused but onboard.exe bundling the dirty companion goes current for every new customer editor.
- Fix: Give the onboard publish its provenance so gates apply; never --make-current when the ship refused current; skip the onboard when the companion publish failed.

#### bug-server-6 - select_code_root boots OTA code whose files are never re-verified
- Sources: `bug-server-6`, `bug-dash-release-8`. Hunter: medium/CONFIRMED.
- Where: `dashboard/deploy/select_code_root.py:219-279 (check_tree); dashboard_update.py:846-867`
- What: At boot only record.json's signature and manifest fields are checked; the extracted tree is never hashed against files_sha256 (and the on-disk manifest is unsigned).
- Scenario: A code-execution bug in any in-process app (e.g. the ytdl worker on an unpinned nightly) edits /data/code/<v>/src, and the tampered tree boots on every restart as 'signed and verified'.
- Fix: Re-hash the tree against a signed files_sha256 or tree digest at boot and refuse (counting toward revert), or store trees where the app uid cannot write.

#### bug-tools-ci-3 - publish_latest signs and ships a release build without checking that ci.yml was green for that commit
- Sources: `bug-tools-ci-3`. Hunter: medium/CONFIRMED.
- Where: `tools/publish_latest.py:236-246; .github/workflows/release-windows.yml, release-macos.yml; docs/RELEASE_PATHWAYS.md`
- What: 'Green' means the release workflow succeeded, which skips the installer suites, CRLF gate, licence and notices checks and four component suites.
- Scenario: A bootstrap change turns ci.yml red; release-windows passes on the same commit and onboard.exe with the broken bootstrap goes to new customers.
- Fix: After commit_is_on_main, require a successful ci.yml run for that sha (--allow-red-ci override); fix the docs.

#### bug-tools-ci-4 - The licence gate is a GPL-family denylist: non-commercial, source-available, proprietary, EUPL and OSL licences pass silently
- Sources: `bug-tools-ci-4`. Hunter: medium/CONFIRMED.
- Where: `tools/check_licenses.py:78-108; tools/scan_frozen.py:77`
- What: verdict() flags only AGPL/SSPL/LGPL/GPL/UNKNOWN; probe returned clean for CC-BY-NC, BUSL, Elastic, Commons Clause, Proprietary, EUPL, OSL, CDDL.
- Scenario: A transitive dependency with CC-BY-NC or BUSL metadata passes CI and ships in a sold binary.
- Fix: Switch to an allowlist of permissive licences with reasoned exceptions; at minimum deny the listed families.

#### bug-tools-ci-5 - CI tests the installer's PowerShell under pwsh 7; editors run it under Windows PowerShell 5.1
- Sources: `bug-tools-ci-5`. Hunter: medium/CONFIRMED.
- Where: `.github/workflows/ci.yml installer step (shell: pwsh); installer/windows_*.ps1:1 (#requires 5.1); onboarding/steps.py:1831, 2681, 3079, 3170`
- What: pwsh 7 accepts &&, ternary, ??, -AsHashtable and different encodings that 5.1 rejects; green CI says nothing about the real host. No current break found.
- Scenario: A helper using -AsHashtable passes CI and kills windows_bootstrap.ps1 on a customer PC.
- Fix: Run the step with shell: powershell / powershell -File (5.1 ships on windows-latest); optionally both editions.

#### bug-ytdl-web-4 - The server pulls and imports an unpinned yt-dlp nightly from PyPI into the dashboard process that holds every fleet secret
- Sources: `bug-ytdl-web-4`, `bug-server-14`. Hunter: medium/CONFIRMED.
- Where: `ytdl/web/ytdlweb/ytdlp_nightly.py:80-90, 300-350, 440-470; dashboard/deploy/run.sh:353-425, 587-589`
- What: pip install --pre --upgrade yt-dlp with no pin or hash, verify child inherits the full environment, result prepended to PYTHONPATH, code dir writable by the app uid.
- Scenario: A compromised pre-release, or any file-write bug under /data/ytdlp-nightly, becomes code inside every youtube_download customer's dashboard within a day, with the session secret and NAS key in reach. Contradicts trust-model-7.
- Fix: Run the downloader in a sidecar without dashboard secrets, or pin vetted nightlies by digest via the signed feed; allow-list the verify child's env; keep the code dir read-only to the app uid.
- Known: CR-361 (BUILT, unshipped; owner decision 2026-10-05)

### Theme: B-roll

#### bug-broll-1 - The archive-name allocator compares folders by exact bytes: shoots differing only in case (or NFC vs NFD) get the same file name and can overwrite each other's original
- Sources: `bug-broll-1`. Hunter: high/PLAUSIBLE. Verifier: DOWNGRADED (high -> medium).
- Where: `broll/web/app/ingest_batches.py:257-337; routes_batches.py:66-86; companion broll_upload.py:159-195`
- What: _taken_names filters by exact str(parent) and share = ?; claim_key casefolds only afterwards; nothing normalises Unicode or compares shoot names by case.
- Scenario: Probe: 'Taiwan Shoot' and 'taiwan shoot' both get .../Day1/C0001.MP4. On a case-insensitive dataset the second copyto replaces the first clip's preview and original, silently.
- Fix: Casefold+NFC the folder key in both sources; normalise share/rel_dir on the way in; refuse a shoot name matching an existing one except by case; never overwrite an original the upload did not create.
- Verifier note: Downgraded: the overwrite needs a case-insensitive archive dataset (unverified) and an unusual retyped name.

#### bug-broll-2 - A partial /api/ingest/video upsert wipes hash, size, duration, dimensions, codec, shot_date and in_inbox
- Sources: `bug-broll-2`. Hunter: medium/CONFIRMED.
- Where: `broll/web/app/routes_ingest.py:68-108; broll/indexer/broll_index/storage/http_backend.py:129-140; pipeline.py:109, 176, 208`
- What: ON CONFLICT sets those columns from the incoming row without COALESCE; HttpBackend sends only changed fields.
- Scenario: Probe: a status-only update NULLs the probe metadata; every clip indexed by a db.mode:api indexer loses filters, dedupe-by-hash and inbox state.
- Fix: COALESCE every column; make in_inbox Optional; add a partial-after-full test.

#### bug-broll-3 - Publishing the b-roll index while a dashboard ingest batch runs silently loses that batch's writes and re-numbers its clips under the live companion
- Sources: `bug-broll-3`. Hunter: medium/CONFIRMED.
- Where: `server/publish_db.py:898-981; server/broll_drain.py; broll/web/app/ingest_batches.py:1069-1345; docs/INDEXERS.md:315-319`
- What: The drain is a snapshot; writes between export and rename go to the renamed-away file, fleet calls 404 in the gap, and the apply re-mints drained ids. open_batches is only printed.
- Scenario: A morning publish over an overnight batch: an /uploaded in the window is restored as 'uploading' and the clip is invisible for ever; every clip gets a new id while stills sit under the old ones.
- Fix: Refuse while open_batches > 0 without --allow-running-ingest; better, a site-wide ingest hold during drain+apply.
- Known: operator caution in INDEXERS.md; the loss and re-mint unrecorded

#### bug-broll-4 - release('done') with unfinished items ends the batch 'done', leaves invisible 'ingesting' rows holding names, and nothing can retry them
- Sources: `bug-broll-4`. Hunter: medium/CONFIRMED.
- Where: `broll/web/app/ingest_batches.py:584-651, 1350-1398`
- What: final is downgraded only for failed and proxies_live; pending/describing/indexed/uploading are ignored and retry_failed does not reach them.
- Scenario: Probe: a 2-item batch released done shows 'done' with n_done 0; footage never appears.
- Fix: In release(done) mark every unfinished item failed with a reason; log the mismatch.

#### bug-broll-5 - A client link built against a public base with no explicit port keeps the dashboard's own port, so the link is dead for the client
- Sources: `bug-broll-5`. Hunter: medium/CONFIRMED.
- Where: `broll/web/static/clientfolders.js:54-62 (cfShareUrl)`
- What: The WHATWG host setter keeps the existing port when the new host carries none.
- Scenario: Probe: http://truenas:8090 + base https://nas.tail1234.ts.net gives https://nas.tail1234.ts.net:8090/broll/share/abc/; the client cannot connect and the editor never notices.
- Fix: Use new URL(local.pathname, cf.publicBase) or set port explicitly; add a test.

#### bug-broll-6 - Preview stills are keyed by videos.id in one shared folder while the base rig, fleet ingest and the drain mint ids independently (still open)
- Sources: `bug-broll-6`. Hunter: medium/CONFIRMED.
- Where: `broll/web/app/ingest_batches.py:149-161, 822-831; routes_media.py:50-59; routes_share.py; broll/indexer/build_archive.py:116-129, 590-606; server/broll_drain.py`
- What: No FLEET_ID_BASE exists; build_archive replaces fleet stills and the drain renumbers without moving stills.
- Scenario: After an index + publish, ingested clips show another clip's thumbnail and scrub sprite, including on public client links.
- Fix: Implement the owner's pending option (A): a disjoint fleet id range kept by the drain plus a one-off rename.
- Known: bug-broll-3 (2026-09-24), DEFERRED for the owner, OPEN

#### bug-broll-7 - The public media gate re-resolves the whole folder on every thumbnail after any renumber and never heals
- Sources: `bug-broll-7`. Hunter: medium/CONFIRMED.
- Where: `broll/web/app/routes_share.py:93-109; client_folders.py:795-818, 855-868, 972-977`
- What: member_video_id matches only the stored id; after a renumber every request falls back to a full resolve_items, and nothing rewrites the id.
- Scenario: Probe: 500-item folder costs ~4.2 s CPU per page view on the single dashboard process behind an unauthenticated Funnel URL; a scraper stalls fleet status.
- Fix: Rewrite the stored video_id when resolution finds a new id, or cache per (folder, search_generation); consider a per-token budget.

### Theme: Music

#### bug-music-1 - Publishing music.db deletes every fleet-ingested track and the whole batch ledger
- Sources: `bug-music-1`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `server/publish_db.py:88-135, 404-418; music/web/DEPLOY.md:237, 246-252, 321-355`
- What: SPECS music has drain False; since fleet ingest the live file is the only home of companion-ingested tracks and the ingest_batches/items ledger; the shrink guard ignores the ledger and allows a 10% drop.
- Scenario: 200 fleet tracks in a 3,000-track library: a base-rig re-index plus publish --apply passes the guard and they vanish; in-flight batches 404.
- Fix: Drain and merge fleet rows and the ledger like b-roll, or refuse while the live file holds ingest_items the source lacks; correct SPECS and DEPLOY.md.
- Known: CR-152 fixed the b-roll half only
- Verifier note: Downgraded: needs a deliberate whole-file publish the docs discourage; .prev-<ts> rollback exists; audio files remain to re-index.

#### bug-music-5 - A new customer with no GPU base rig gets a music page whose search 500s and whose fleet-ingested tracks are never tagged
- Sources: `bug-music-5`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `music/web/musicweb/text_encoder.py:293-365; rescore.py:110-118, 389-391; dashboard music.py:480-517; deploy/compose.image.yaml:323; server/install_dashboard_app.py:5849-5862`
- What: Text search and tagging need the ~482 MB CLAP text tower, which is not in the image or the feed; it arrives only from a GPU base rig push. mount_music still reports MOUNTED.
- Scenario: Customer #2 without an RTX box: every /music search shows 'search is broken' and companion drops land untagged.
- Fix: Ship the text tower as a sha-pinned feed artefact fetched by the container or wizard; until then report DEGRADED and hide search instead of 500ing.
- Known: only an operator NOTE in install_dashboard_app.py
- Verifier note: Downgraded: secondary mount, no data lost, scores_stale lets a later rescore repair tags once installed.

#### bug-music-2 - A dropped connection or timeout on the music result POST fails the track for good (and can strand a track row)
- Sources: `bug-music-2`. Hunter: medium/CONFIRMED.
- Where: `companion music_ingest.py:424-431, 540, 636-642; broll_ingest.py:114, 249-271, 2306-2313, 2340-2349`
- What: Transport exceptions are not retryable; embedded=True is set before the POST, so the retry skips the POST and fails 'library did not name this track'.
- Scenario: A dashboard deploy mid-drop fails a track twice within a second; after a timeout a searchable row with 404 audio remains.
- Fix: Treat transport errors as retryable with backoff; set embedded only after 200; re-POST when dest_name is empty; pre-warm the encoder at mount.
- Known: music-2 covers only 503 and name_race

#### bug-music-3 - A track that fails after its result keeps a library row with no audio, which also blocks re-dropping it
- Sources: `bug-music-3`. Hunter: medium/CONFIRMED.
- Where: `music/web/musicweb/ingest_batches.py:1237-1324; db.py:647-671; companion broll_ingest.py:3091-3110, 3150-3161`
- What: Rows of failed items are dropped only on 'cancelled'; done_with_errors/failed keep them.
- Scenario: Track 7's upload fails 3 times; a week later staging is pruned; it stays in search, plays nothing, and a browser re-drop is refused as a duplicate.
- Fix: Drop unlanded rows of failed items on every terminal release and in lease expiry, or ignore failed-item rows in duplicate checks.
- Known: bug-music-ytdl-4 fixed the cancelled path only

#### bug-music-4 - One malformed window vector takes text search and 'similar' down for the whole fleet, and it survives restarts
- Sources: `bug-music-4`. Hunter: medium/CONFIRMED.
- Where: `music/web/musicweb/ingest_batches.py:1088-1119; db.py:349-358; search.py:24-26, 230-262`
- What: _write_windows never checks width against dim; np.stack fails on every Index build.
- Scenario: Probe: one 1-float window posted via a fleet result; search.refresh() and a fresh index() both raise; only SQL surgery fixes it.
- Fix: 422 or drop wrong-width windows; have the loaders skip and log bad rows.

#### bug-music-6 - Any write to music.db (heartbeat, checkpoint, waveform cache) makes the next search rebuild the whole index
- Sources: `bug-music-6`. Hunter: medium/CONFIRMED.
- Where: `music/web/musicweb/db.py:208-236; search.py:207-245; ingest_batches.py:779-792; routes_media.py:221-223`
- What: Staleness keys on file identity, size and mtime including -wal.
- Scenario: Probe: 10k tracks, one heartbeat -> next search 0.67 s and ~245 MB; during any batch every search stalls on the single worker.
- Fix: Key staleness on a revision counter bumped by writers of tracks/windows/debias; keep the inode check for swaps.

#### bug-music-7 - Preview proxies from the base rig can play another track's audio after a drain, because ids diverge
- Sources: `bug-music-7`. Hunter: medium/PLAUSIBLE.
- Where: `music/web/musicweb/drain.py apply_bundle; music/indexer/make_proxies.py:20-40; music/web/DEPLOY.md:270-320; config.py:132-172`
- What: Proxies are named by tracks.id and served on existence; drain apply re-mints ids while the base rig's copy keeps its own.
- Scenario: After a drain and proxy push, clicking a fresh cue plays another track (the music-4 symptom by a new door).
- Fix: Key proxies by a stable value (content hash or rel_path digest) or verify (id, rel_path) on push.
- Known: related to music-4 (fixed in-process path)

### Theme: YouTube downloader (server)

#### bug-ytdl-web-1 - Turning the YouTube downloader OFF does not stop the server downloading, and hands in-flight local downloads to the server IP
- Sources: `bug-ytdl-web-1`, `bug-dash-jobs-cards-2`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `dashboard ytdl.py:468-578, 806-819 (YtdlFeatureGate); ytdl/web/ytdlweb/worker.py:170-201, 244-320; ytdlp_nightly.py:440-470; companion ytdl_executor.py:388`
- What: The switch is enforced only by HTTP 404s; the worker, canary and nightly refresher never check it. A companion's heartbeat 404s, its lease expires after 180 s, and _phase_download reclaims the job server-side.
- Scenario: Counsel says stop and the admin unticks the feature: queued and downloading jobs carry on from the NAS IP and nightlies keep installing until a restart. Contradicts YOUTUBE_FEATURE_NOTICE's 'off runs no pipeline thread'.
- Fix: Give the worker, canary and refresher the cached feature predicate and idle while off; do not reclaim leases while off; show paused jobs; test a mid-job flip.
- Verifier note: Downgraded: only jobs already in flight, nothing lost, a restart stops it; cheap fix.

#### bug-ytdl-web-2 - A deleted person's username stays in manifest.json files in the footage tree
- Sources: `bug-ytdl-web-2`. Hunter: medium/CONFIRMED.
- Where: `ytdl/web/ytdlweb/db.py:2085-2130, 2323; worker.py write_manifest`
- What: Every finished download writes created_by beside the clips; the LG-3 delete pseudonymises ytdl.db only.
- Scenario: A deleted freelancer is still named in every Youtube/<term>/manifest.json synced to every editor.
- Fix: Stop writing the username (stand-in or nothing) or rewrite manifests in forget_requester; mention in export and PRIVACY.md.

### Theme: Server, appliance and installers

#### bug-server-4 - TrueNAS setup_editor_account.py takes over any existing account, admin and root included
- Sources: `bug-server-4`. Hunter: high/CONFIRMED. Verifier: DOWNGRADED (high -> medium).
- Where: `server/setup_editor_account.py:165, 493-581; server/backends/truenas.py:443-529 (contrast backends/synology.py:607-701, dashboard nas/truenas.py:65-67)`
- What: USERNAME_RE accepts any name; update_editor replaces sshpubkey, adds to editors, setperm 700 the home and disables password login, with no builtin/uid/editors-membership guard.
- Scenario: An operator onboards an editor whose name equals the admin's: a freelancer's key logs in as admin, the admin is forced into the sftp Match block and server/ scripts stop working.
- Fix: Port _refuse_non_editor into TrueNASBackend create/update (builtin, uid<1000, not already in editors, the [nas] admin_user); add tests.
- Verifier note: Downgraded: operator-only CLI with the admin's own credentials, and it prints 'updating in place' first.

#### bug-server-5 - run.sh image mode: docker stop kills PID 1 before uvicorn finishes shutting down
- Sources: `bug-server-5`. Hunter: medium/CONFIRMED.
- Where: `dashboard/deploy/run.sh:592-602`
- What: With a TERM trap, wait returns 143 at once; rc is not 75 so the shell exits, SIGKILLing the container mid graceful shutdown (probed).
- Scenario: Every docker stop, image update, --recreate or reboot in image mode skips lifespan shutdown: Cards engines, collector and ytdl workers killed mid-write.
- Fix: Loop `while kill -0 $app_pid; do wait $app_pid || rc=$?; done` before choosing the exit code, or exec a supervisor.
- Known: WPK-3 (open, generic)

#### bug-server-7 - Image-mode deploys fail their own health gate whenever the image is not the checkout's VERSION
- Sources: `bug-server-7`. Hunter: medium/CONFIRMED.
- Where: `server/install_dashboard_app.py:1762-1778, 1889-1930, 5990, 6139; server/tests/conftest.py:83`
- What: verify_dashboard_after_restart requires the health version to equal the checkout's VERSION in both modes; the conftest stubs the probe.
- Scenario: An image-mode --recreate one version ahead of :1 (or with a newer OTA tree) probes 150 s, prints a bind-mode rollback line and exits 1; ship.cmd stops.
- Fix: In image mode compare against the image/current.json version or accept any healthy answer; drop the bind rollback line there.

#### bug-server-8 - Optional Postgres profile publishes a superuser with Resolve's default password on all interfaces
- Sources: `bug-server-8`. Hunter: medium/CONFIRMED.
- Where: `dashboard/deploy/compose.yaml:763-783; compose.image.yaml:~415-425`
- What: POSTGRES_PASSWORD defaults to 'DaVinci' and the port binds 0.0.0.0.
- Scenario: A customer enables --profile project-server: anyone on the LAN gets postgres superuser and a container shell via COPY FROM PROGRAM.
- Fix: Bind to DASH_BIND_* and require ${PG_PASSWORD:?}; refuse 'DaVinci'.

#### bug-server-9 - The 'scoped' TrueNAS API key is still root-equivalent
- Sources: `bug-server-9`. Hunter: medium/PLAUSIBLE.
- Where: `server/create_api_key.py:1-60, 76-82, 160-175`
- What: ACCOUNT_WRITE (any account's password and keys) plus FILESYSTEM_ATTRS_WRITE (setperm anywhere); without --username it is minted as the admin.
- Scenario: Code execution in the container resets truenas_admin's keys via PUT /user and SSHes in with sudo.
- Fix: Require a dedicated --username; document residual root equivalence; seek a narrower privilege or move account writes out of the container.
- Known: COMMERCIAL_READINESS item 6 / H3 (treated as mitigated)

#### bug-server-10 - Live b-roll databases sit in the editor-writable SMB share
- Sources: `bug-server-10`. Hunter: medium/PLAUSIBLE.
- Where: `server/install_dashboard_app.py:5659-5713; server/publish_db.py:198; broll/web/app/client_folders.py:143`
- What: /broll-data is the editors' P:\Assets\B-roll Archive (2770 editors); broll.db, client_shares.db, drain bundles and .prev-* copies are deletable or replaceable by any editor.
- Scenario: Ransomware on one editor PC takes out the search index, every client link and the rollback copies at once; an editor can plant a crafted broll.db.
- Fix: Move the databases to a private app data dir (as music.db is) and share only media; at minimum 0600 service-owned in a non-editor-writable subdir.

#### bug-installer-3 - A Syncthing installed by winget gets its versioned package folder baked into the logon shim, so winget upgrade silently kills lane C
- Sources: `bug-installer-3`. Hunter: medium/PLAUSIBLE.
- Where: `installer/windows_bootstrap.ps1:1259, 1967, 2007; companion sync/syncthing_supervisor.py:167-223`
- What: Get-Command resolves to WinGet\Packages\...\v2.1.x\syncthing.exe, which is written into CCSyncSyncthing.cmd.
- Scenario: IT runs winget upgrade --all; next logon Syncthing does not start and supervisor restarts fail.
- Fix: Always run our pinned copy from $BinDir, or resolve to the stable WinGet\Links path.

#### bug-installer-4 - Re-running the wizard silently downgrades the companion to whatever build that onboard.exe bundled, skipping the floor
- Sources: `bug-installer-4`. Hunter: medium/CONFIRMED.
- Where: `onboarding/steps.py:2980, 3011-3019, 3207-3229; installer/windows_bootstrap.ps1:2276-2300; onboarding/onboard.py:1733; installer/windows_upgrade.ps1`
- What: Clean-slate deletes the self-upgraded exe and copies in the bundled build; nothing compares versions or reads upgrade_floor.json.
- Scenario: An editor on 0.9.82 re-runs a months-old onboard.exe to fix a drive and silently gets 0.9.6x without later safety and privacy fixes.
- Fix: Read the installed version first and keep a newer build (or warn); same guard in windows_upgrade.ps1.

#### bug-installer-5 - A tree-drive letter held by a real volume is read as free: install says DONE with no tree drive and a logon task that fails at every logon
- Sources: `bug-installer-5`. Hunter: medium/CONFIRMED.
- Where: `installer/drive_mapping.ps1:131-202; installer/windows_bootstrap.ps1:1476-1494, 1691-1736; onboarding/steps.py:2156-2226`
- What: Get-DriveMapping reads only subst and net use; net use and subst failures are warnings, not capability misses.
- Scenario: A card reader or second partition on P:: green DONE, every Resolve path offline, lane B has nowhere to land; if the volume goes away the subst later takes the letter.
- Fix: Check whether the letter is in use at all before mapping and treat a foreign one as a capability miss; verify after mapping; refuse in the wizard.
- Known: CR-153/OPS-1 covers the mapped-foreign case only

#### bug-installer-6 - Any Syncthing the editor already runs is taken to be ours (lane C wired to the wrong instance, DONE shown), and the Windows uninstaller kills it
- Sources: `bug-installer-6`. Hunter: medium/CONFIRMED.
- Where: `installer/windows_bootstrap.ps1:1895-1901, 2010-2013, 2027-2030; windows_uninstall.ps1:321-331; windows_upgrade.ps1:572-579`
- What: The bootstrap, uninstaller and upgrade match Syncthing by process name; a personal instance on 8384 makes ours skip start; seeding 401/403 is only a warning.
- Scenario: A freelancer with personal Syncthing gets DONE, lane C never reaches the NAS, and uninstalling CC Sync later kills their Syncthing mid-transfer.
- Fix: Use the wizard's managed-directory filter in all three scripts; give ours its own ports or record a named capability miss.
- Known: INST-20 fixed in the wizard and macos_uninstall.sh only

#### bug-installer-7 - Every wizard install blocks ALL inbound SMB (139/445) on every network profile, with no opt-out and no notice
- Sources: `bug-installer-7`. Hunter: medium/CONFIRMED.
- Where: `installer/windows_bootstrap.ps1:1413-1434, 1649-1659; onboarding/steps.py:1829-1856`
- What: Inbound Block TCP 139,445, any remote, any profile; -KeepRemoteSmbOpen is never passed by the wizard.
- Scenario: A workstation sharing D:\Exports to the colourist breaks after onboarding with nothing naming CC Sync; may conflict with domain GPO.
- Fix: Avoid or scope the change; detect existing shares and ask or report; document for customer IT.
- Known: COMMERCIAL_READINESS item 15 introduced the rule; side effect unrecorded

## 4. Polish

Lows, one line each: id (sources) - title. Where. Fix.

**Companion**

- `bug-app-a-5` [PLAUSIBLE] - Dashboard file moves are applied on disk during a halt. `companion app.py:2541-2566, 8680-8895; dashboard api.py:10990-11010`. Fix: Answer pending moves 'retrying' while halted.
- `bug-app-a-6` - A watchdog restart of a dead sequencer silently undoes Pause and the drive-out pause. `companion app.py:1206-1255; sync/sequencer.py:652-655`. Fix: Re-apply pause after a watchdog restart when _paused or _root_absent.
- `bug-app-a-7` - Lane completion events are drained before the POST and lost when it fails. `companion app.py:5099-5112; reporter.py:941-947, 1384-1389`. Fix: Hold drained completions and resend until a post succeeds.
- `bug-app-a-8` - Pushed update and auto-update on one reply race; the loser records a false 'Update failed'. `companion app.py:2547, 2575, 8382-8571; upgrade.py:1901-1918`. Fix: Return a distinct 'already applying' outcome and treat it as a stand-down.
- `bug-app-a-9` - Bin-only non-canonical clips are latched once per process even when the relink fails. `companion app.py:3445-3449, 3626-3644, 4888-4891`. Fix: Discard the key on a refused relink and for unreachable items. Known: RES-19 fixed the watcher half only.
- `bug-app-b-4` - A Windows shutdown/log-off is never stamped clean for the crash-loop counter, so reboots after an update can revert a good build. `companion app.py:11212-11215, 11634-11637; shutdown_guard.py:590-614; upgrade.py:289-305`. Fix: Call upgrade.note_clean_shutdown in the session-end callback.
- `bug-app-b-5` [PLAUSIBLE] - Restarting the watcher thread clears the process-wide stop event, which can undo a racing shutdown. `companion app.py:1094-1229, 10331, 11459-11478, 11946`. Fix: Give the watcher its own stop event; never clear _stop_event.
- `bug-app-b-6` - 'Copy diagnostics' says the bundle was sent to the admin when it was not. `companion app.py:9291-9293, 9918-9960`. Fix: Toast 'copied', then report the upload's real outcome.
- `bug-sync-8` - Removal gate rewrites lane A's shared filter file without exclusions, racing a run's startup. `companion sync/rclone_lane.py:2985, 3384, 3402, 3877-3890`. Fix: Give probes their own filter file.
- `bug-resolve-6` - A Windows TCP-table read failure yields ABSENT instead of UNKNOWN (spurious disconnections). `companion script_server.py:188-206, 323-336`. Fix: Retry on error 122 with the new size; raise so the probe answers UNKNOWN.
- `bug-resolve-7` - Undo's cross-project guard compares 80-char slugs, so similar project names replay each other's journals. `companion resolve_journal.py:141-151; resolve_bridge.py:2693, 2731-2739`. Fix: Compare raw stored names; hash the full name into the slug.
- `bug-resolve-8` - The stills 'gallery moved' message prints a forward slash on Windows. `companion stills.py:161; app.py:10603, 12017`. Fix: Resolve None to os.name == 'nt' before choosing the separator.
- `bug-comp-ui-4` - Settings [ GIVE THIS COMPUTER A NEW ID ] opens a Tk dialog without taking _popup_active_lock. `companion settings_window.py:548-595`. Fix: Take the lock non-blocking with the standard toast.
- `bug-comp-trust-6` - A dashboard_url with an explicit default port (:443/:80) makes every Send to Resolve 403. `companion loopback_guard.py:208-231`. Fix: Normalise default ports before building origins.
- `bug-comp-trust-7` - A jobs_kinds typo turns a restriction into 'take every kind'. `companion capabilities.py:101-135`. Fix: Take no work when a non-empty setting yields no known kind; warn in Settings.
- `bug-comp-media-4` - The peaks recipe buffers the whole decode in the tray process (~1-2 GB for long files). `companion jobs_media.py:335-351, 636-718`. Fix: Bin while streaming, O(bins) memory.
- `bug-comp-ytdl-6` - A yt-dlp self-update whose new binary cannot be read is published as ok under the old version. `companion ytdlp_manager.py:979-992`. Fix: Treat updated-but-unreadable as its own failed outcome with the short retry.
- `bug-comp-ytdl-7` - The executor's 'old yt-dlp' poke is swallowed by CR-361's 20 h update throttle. `companion ytdl_executor.py:2887-2915; ytdlp_manager.py:914-976`. Fix: Pass a force flag from the poke (keep one per job, 1 h floor).
- `bug-comp-ytdl-8` [PLAUSIBLE] - A stop just after yt-dlp finishes leaves the clip under its deliverable name, never probed. `companion ytdl_executor.py:2555-2561, 3253-3261`. Fix: Move a landed file onto the staging name so the sweep removes it. Known: related to CR-327 (fixed).
- `bug-comp-ytdl-9` - /ytdl/fetch will pull any file under Projects/ from the NAS, not only YouTube originals. `companion ytdl_server.py:328-387; broll_fetch.py:106, 220-261`. Fix: Require <label>/Youtube/ and a video extension (optionally a synced label).
- `bug-wire-5` [PLAUSIBLE] - A Resolve project name over 256 chars gets every heavy report refused while its journal is among the newest 20. `companion resolve_journal.py:682-711; dashboard api.py:9641-9655`. Fix: Cap 'project' in the companion and add a truncating validator.

**Dashboard**

- `bug-dash-api-5` - A shared-token holder can stamp 'being turned away' on any editor's computer and trigger report_refused alerts. `dashboard api.py:10196-10220; db.py:5668`. Fix: Stamp only when the credential proves that editor.
- `bug-dash-api-6` - Job claim trusts the machine name in its body, so a hostname target can be claimed by any editor (and cooldowns evaded). `dashboard api.py:12104-12150; jobs.py:478-483`. Fix: Refuse a claim whose machine is not in machines_of(editor); match targets as editor/machine.
- `bug-dash-api-8` [PLAUSIBLE] - A file move can overwrite a file that appears at the destination after the exists() check. `dashboard api.py:3151, 3207-3226`. Fix: Use a no-replace rename or re-check immediately before. Known: related to CR-333 (OPEN).
- `bug-dash-api-9` - Per-machine storage bounds (diagnostics, pending SSH keys) are keyed on a caller-chosen machine name. `dashboard db.py:2413, 5983-6008; api.py:10144, 11183`. Fix: Per-editor caps; refuse diagnostics for unregistered machines.
- `bug-dash-api-10` (bug-dash-api-10, bug-dash-release-9) - Publish-time prune deletes recalled rows and builds a machine has a pending push for. `dashboard db.py:4639-4690, 5021-5035; package_store.py:535; api.py:6326-6354`. Fix: Exclude retracted rows and versions named by pending pushes (or keep the row, drop only the file).
- `bug-dash-auth-6` - The first local admin is whoever reaches /api/v1/setup/admin first. `dashboard setup_api.py:63-105; app.py:90; setup_routes.py:47-84`. Fix: Require a one-time setup code generated at first boot. Known: related to 09-24 bug-dash-auth-1 (window scope, fixed).
- `bug-dash-auth-7` - The SMB guest/null-session rejection is dead code (session_flags never exists). `dashboard auth.py:115-126`. Fix: Check session.session_key is None after connect or pin require_signing=True; add a test.
- `bug-dash-auth-8` - Non-ASCII header/query values 500 two pre-auth comparisons (internal sftp bearer, OIDC state). `dashboard internal_sftp.py:89; oidc.py:462`. Fix: Route through api.token_ok or catch TypeError.
- `bug-dash-auth-9` [PLAUSIBLE] - /broll, /music, /ytdl writes skip CSRF and Origin checks and rely on SameSite=Lax alone. `dashboard app.py:234-235, 1083-1085; musicweb/routes_ingest.py:432; ytdlweb/routes_api.py`. Fix: Apply _origin_mismatch to these prefixes as for /cards/. Known: deliberate interim exemption.
- `bug-dash-ops-7` - File-move reconciliation can delete the row of a move still in progress, so the fleet is never told. `dashboard api.py:3217-3227, 3249, 3448-3468; collector.py:390-397`. Fix: Reconcile only rows older than a grace period or share a lock; check complete_file_move's rowcount.
- `bug-dash-ops-8` [PLAUSIBLE] - Snapshot restore follows symlinks, copying container files (e.g. secrets) into the Projects tree. `dashboard recovery.py:270-292, 510-520`. Fix: Walk and copy with follow_symlinks=False; skip and name symlinks.
- `bug-dash-jobs-cards-6` - Whether a spent media job is pinned or abandoned depends on whether a Cards episode happens to be open. `dashboard jobs.py:120-133; cards_exec.py:153-172; cards.py:385-402`. Fix: Make available() true when the checkout exposes fleet_execute; let tick wait for an engine.
- `bug-dash-jobs-cards-7` - Re-running Codex SET UP for the installed version deletes the live install before unpacking. `dashboard cli_tools.py:1196-1205`. Fix: Unpack into <version>.new and swap atomically, or skip an identical version.
- `bug-dash-ui-1` - A long project name with no spaces makes the project page scroll sideways. `dashboard templates/project.html:28; static/cc/terminal.css:219; phone.css:7`. Fix: overflow-wrap:anywhere and min-width:0 on .head h1/.sub; add a test.
- `bug-dash-ui-3` - The /help markdown renderer escapes link targets twice, so & in a URL breaks. `dashboard help.py:473, 494`. Fix: Unescape before escaping, or match links before escaping; add a test.
- `bug-dash-ui-4` - The new alert-kinds form blanks its All / Problems only / None buttons while saving. `dashboard templates/partials/admin_alerts.html (uncommitted); static/cc/health.css:76-81`. Fix: Give the preset keys a .busy-t or scope the rule to [data-busy]. Known: new uncommitted code.
- `bug-dash-ui-5` - The installer 404 shown to an editor tells admins to run a vendor-only release tool. `dashboard ui.py:4008-4021`. Fix: Point admins at Settings > Packages instead. Known: CR-59 left this sentence.
- `bug-dash-ui-6` [PLAUSIBLE] - An installed Cards app's sign-in page is outside the app's scope (possible iOS sign-in loop). `dashboard cards_landing.py (APP_SCOPE); app.py login_gate`. Fix: Test on iOS/Android; add a /cards/login alias or widen scope.

**Release, CI and tooling**

- `bug-dash-release-7` - Concurrent publishes of one version escape as IntegrityError, orphaning a .part and failing check_now. `dashboard package_store.py:470-494; release_feed.py:886, 1043-1074`. Fix: Catch IntegrityError, roll back, unlink the part, re-run the comparison; or lock.
- `bug-tools-ci-6` - Licence tools pip-install unpinned pip-licenses into the venv they judge; PyInstaller is pinned but not hashed. `tools/gen_notices.py:177-211; tools/release.ps1; release workflows`. Fix: Hashed tools lock, throwaway venv with --python; hash-pin PyInstaller and hooks.
- `bug-tools-ci-8` [PLAUSIBLE] - check_deploy_drift.ps1 POSTs the admin password through redirect-following calls with no cleartext guard. `tools/check_deploy_drift.ps1:507-611, 854`. Fix: -MaximumRedirection 0 on every call; refuse http:// to public hosts.
- `bug-tools-ci-9` - The selector's scoped tier never runs licence/notices checks, so allowlist or notices-input changes pass locally. `tools/select_suites.py:312-314; tools/test_map.toml; run_all_tests.ps1:296-310`. Fix: Give those files a tier-full row or let an area require full checks.
- `bug-tools-ci-10` - check_licenses judges the container's packages from other venvs, at other versions. `tools/check_licenses.py:140-155, 216-231`. Fix: Scan a venv built from the container lock, or match on (name, version).
- `bug-tools-ci-11` - The opt-in YouTube-unblock dependency set (GPLv3) is in no gate. `tools/check_licenses.py:157-178; .github/workflows/ci.yml`. Fix: Add a named CI step for dashboard-container-unblock. Known: by design, unenforced.
- `bug-tools-ci-12` - The bench scratch-path guard accepts '..' traversal and any component containing '_bench'. `bench/ccbench/guard.py:126-135`. Fix: Refuse '..'; require a component equal to '_bench'.
- `bug-comp-ytdl-10` - THIRD_PARTY_NOTICES still says the NAS runs the lock-pinned yt-dlp; since CR-361 it runs an unpinned PyPI nightly. `docs/legal/THIRD_PARTY_NOTICES.md:364, 431`. Fix: Update the row; extend gen_notices and the LG-16 drift check to the nightly path. Known: follows CR-361.

**B-roll, music and YouTube web apps**

- `bug-broll-8` - A shoot name equal to an indexer share re-files its collection and makes every later drain treat base-rig rows as dashboard-only. `broll/web/app/ingest_batches.py:838-845; routes_batches.py:66-86, 107-109; server/broll_drain.py`. Fix: Refuse such names; validate collection; drain by ingest_items.video_id.
- `bug-broll-9` - The expired/revoked share page shows the curator's login username to anyone with the old link. `broll/web/app/client_folders.py:549-570; routes_share.py:111-138`. Fix: Show only the contact or a display name.
- `bug-broll-10` - record_view on the public folder route is unguarded against a locked ledger, so a client can get a 500. `broll/web/app/routes_share.py:162-164; client_folders.py:980-984`. Fix: Wrap in try/except sqlite3.Error.
- `bug-music-8` - Music fleet routes accept unvalidated shapes: 'live' via /status skips the upload check; nested probe values 500. `music/web/musicweb/ingest_batches.py:79-80, 797-838, 1004-1006; schemas.py:112-123, 161`. Fix: Refuse 'live' in set_item_state; type the probe model and bound ints.
- `bug-music-9` - Inline base-rig music ingest leaves the uploaded file in the library with no row when analysis raises. `music/indexer/music_index/ingest.py:145-171`. Fix: Unlink or restore dest on any exception after the move.
- `bug-ytdl-web-5` - A job whose last owed clip is server-held waits a full lease (~180 s) before finishing. `ytdl/web/ytdlweb/routes_fleet.py _after_terminal; worker.py _phase_download`. Fix: Re-check unfinished_downloads after a clip under a live lease and close out.
- `bug-ytdl-web-6` - Worker waits out the local-claim grace on jobs pinned to the server. `ytdl/web/ytdlweb/worker.py _await_local_claim`. Fix: Return False when mode_lock is 'server'.
- `bug-ytdl-web-7` - No cap on how many searches one editor can queue. `ytdl/web/ytdlweb/routes_api.py create_job / create_url_job`. Fix: Per-editor queue limit with a 409 naming it.

**Server and installers**

- `bug-server-11` - Two rename sequences (db swap sidecars, rollback one-liner) can leave the live thing missing or nested on partial failure. `server/install_dashboard_app.py:1846-1860, 3359-3364`. Fix: Guard the sidecar moves; use && and shell_quote in the rollback.
- `bug-server-12` [PLAUSIBLE] - Pinned ffmpeg URL points at a directory the upstream prunes (and is amd64-only). `server/install_dashboard_app.py:424-430`. Fix: Self-host the pinned tarball with the GPL source offer; surface a missing ffmpeg.
- `bug-server-13` [PLAUSIBLE] - TrueNAS custom_app body carries secrets unescaped through compose interpolation ($ in a password). `server/install_dashboard_app.py:2627-2662; server/backends/truenas.py:168-195`. Fix: Escape $ as $$ or refuse, as render_env_file does; add a test.
- `bug-installer-8` - The wizard's schtasks 'not found' check fails on non-English Windows. `onboarding/steps.py:3184-3203`. Fix: Check existence with schtasks /Query exit code or Get-ScheduledTask.
- `bug-installer-9` - macOS default uninstall deletes the Syncthing device identity; Windows default keeps it. `installer/macos_uninstall.sh:242-256; windows_uninstall.ps1:798-806`. Fix: Keep syncthing-config unless --full.

## 5. Refuted

None. All 29 verified items held up as real; 18 were downgraded (one critical to high, seventeen highs to medium), none disproved.

## Duplicates merged

| Kept as | Also from | Subject |
|---|---|---|
| `bug-app-a-2` | `bug-app-b-3` | licence accept / halt release start lanes with nobody signed in |
| `bug-comp-ytdl-1` | `bug-ytdl-web-3` | suspended/deleted editor keeps ytdl fleet access on the shared token |
| `bug-dash-api-1` | `bug-dash-auth-5` | deleted editor's companion re-registers them |
| `bug-dash-auth-2` | `bug-dash-api-7` | smb sign-in ignores membership and suspension |
| `bug-dash-api-3` | `bug-dash-db-4` | cross-editor Syncthing device id takeover |
| `bug-comp-trust-2` | `bug-dash-release-3` | downgrade floor is 0.0.0 |
| `bug-dash-release-2` | `bug-tools-ci-1`, `bug-tools-ci-2`, `bug-tools-ci-7` | container image `:1` tag, action pins, cosign identity |
| `bug-ytdl-web-1` | `bug-dash-jobs-cards-2` | YouTube feature switch does not stop the worker |
| `bug-ytdl-web-4` | `bug-server-14` | unpinned yt-dlp nightly inside the dashboard process |
| `bug-server-6` | `bug-dash-release-8` | OTA tree never re-verified at boot |
| `bug-dash-api-10` | `bug-dash-release-9` | prune deletes recalled / pushed builds |

Related but kept separate on purpose: `bug-comp-ytdl-5` (companion nightly, no
remote pin) versus `bug-ytdl-web-4` (server nightly inside the secrets
process); `bug-comp-ui-1` (shutdown re-entry) versus `bug-app-b-4` (Windows
session end not stamped clean); `bug-app-b-2` (upgrade stand-down) versus
`bug-comp-ui-2` (Quit during consolidate). Several items share the
trust-model-1 root (a shared token plus never-expiring identity tokens with no
server-side revocation): `bug-comp-ytdl-1`, `bug-dash-api-1`, `bug-dash-auth-2`,
`bug-dash-api-5`. One fix (per-identity revocation plus the shared token off on
new sites) closes most of them.

## Coverage gaps

What the hunters said they did not reach:

- **Companion**: app.py `shutdown()`/`run()` internals were covered by bug-app-b and bug-comp-ui, but `removal_blockers` was read only by bug-sync; syncthing_lane.py, syncthing_supervisor.py, drive_reminder.py, server_locate.py and express batching beyond partitioning; proxy_scan.py body and library.py's timeline/multicam SQL; luts.py stale-index parsing; ui_copy.py, theme.py and most tray line producers and dialog builders; broll_standins ledger internals, bpg.py UI automation, broll_vlm_sidecar server lifecycle, proxy_history, the rest of proxy_gen; build_insert_response, broll_ingest beyond prepare's path rule; config.py DEFAULTS. Nothing was verified on a real Mac (bug-comp-ui-3 and bug-resolve-5 need one), and a real Chromium sign-in and a real yt-dlp nightly self-update on Windows were not exercised.
- **Dashboard**: api.py view builders (330-1575), build_queue_view, the SyncGuardIn / flatten_* models and forget_machine_everywhere; the full upsert_machine_state body; cards/ytdl/triage tables, session-store DDL, invariants 8 and 10+; the 64 individual alert checks (sampled), health.py why-not-syncing, nas/truenas.py API shapes, setup_engine's tailnet login drive; cards_ai SDK/cache internals and the cli_tools pty sign-in; protection.py internals and the sub-apps' own auth; load testing of the threadpool claim (bug-dash-jobs-cards-3 stays PLAUSIBLE); a real phone-width (360-390 px) pass and line-by-line reads of cards_landing.js, assignments.js, setup.js, account.js and most of site_settings.js.
- **Web apps**: b-roll search.py and most of the indexer (local_vlm, runtime, parallel, run_queue, sorter, taxonomy); music's CLAP sidecar download/verify path, ingest.js beyond HTML sinks, eval/ and exporters; ytdl's claude_cli prompts/parsers and vendored downloader internals.
- **Server and install**: check_health.py, install_syncthing_app beyond its GUI binding, Synology DSM calls beyond the takeover guards, tools/Dockerfile.indexer-gpu; whether TrueNAS middleware escapes `$` (no live system); build_editor_package.ps1, most of macos_bootstrap.sh, macOS signing and notarisation; the wizard's EULA/privacy/Tailscale pages (covered on 09-24); windows_bootstrap first-install trust and release_macos.sh in depth.
- **Release and tools**: the bodies of ship.ps1, ship_gates.ps1, publish_feed.py (beyond merge), publish_package.py, sign_release.py, build_dashboard_bundle.py; tools/android and android.yml.
- **Cross-component**: the Timeline Cards engine side of the agent protocol (other repo), the Android app, and the macOS wizard internals.
- No live system was touched, so nothing was checked against the deployed dashboard, the NAS or a tailnet; the appliance findings (bug-server-1..3) were traced in the compose and code, not run.
