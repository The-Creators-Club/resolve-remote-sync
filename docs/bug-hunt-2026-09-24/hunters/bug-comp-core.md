# bug-comp-core - companion core: self-upgrade, supervisor, crash-loop revert, identity/site/machine, reporter, guards
Files read (approximate coverage): upgrade.py (all), supervisor.py (all), release_pubkey.py (all), ed25519.py (all), idle.py (all), machine.py (all), secretfile.py (all), identity.py (all), eula.py (all), site.py (all), reporter.py (all), drive_reminder.py (all), canon.py (all), capabilities.py (most), manifest.py (most), drive_swap.py (connect/swap/unc half), root_guard.py (probe, record, access, sentences), shutdown_guard.py (PendingTracker), config.py (set_value, load_config, backup, site manifest merge). Not read in depth: config.py validate_config/DEFAULTS, paths.py, shutdown_guard.py Windows/Darwin guards, root_guard.RootGuard loop. Followed calls into app.py (upgrade/auto-update/push/revert wiring, sign_in, site refresh, removable-root demotion), settings_window.py (remint), and dashboard api.py (_upgrade_info, api_verify, VerifyIn).
Tests/probes run: companion venv snippet: `keep_old_exe_until_healthy(ev, lambda: True, cleanup=...)` returns at once with "the dashboard accepted a report from it" and calls cleanup (finding 2); `DashboardReporter._machine_id()` with a getter that answers "" then "newid" returns None twice and calls the getter once (finding 5).

## Findings

### bug-comp-core-1 - A crash-loop revert does not stop the machine re-installing the build it just fled
- Severity: high
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/upgrade.py:1012-1019 (revert writes only `reverted_from`); companion/src/ccsync_companion/app.py:6671-6686 (`_upgrade_attempt_blocked`), app.py:7780-7795 and 7907-7939 (auto-update and pushed-update paths)
- What: `revert_to_previous_build` records the bad version only as `reverted_from` in the attempts ledger. It never records it as a failed attempt, and no check tests for it. `_upgrade_attempt_blocked` looks only at `attempts`/`last_attempt_at` for the wanted version. `_on_upgrade_available`/`_maybe_auto_update` and `_apply_pushed_update` never look at `_upgrade_reverted_from`. The dashboard keeps offering the reverted build: `_upgrade_info` does not read `upgrade_reverted_from`, and a push rides every report until the machine reports that version.
- Failure scenario: a site with `auto_update` on, or an admin's [ UPDATE NOW ] push for vX. vX crash-loops, and APP-5 restores vX-1. On the restored build's first report reply, the offer and the push for vX arrive again, and the machine downloads and installs vX again at once. In the second round the supervisor has already spent 2 of its 3 relaunches for the hour. It relaunches vX once more and then refuses ("already relaunched 3 times"). vX has only 2 starts, so `crash_loop` never trips, and the machine is left with NO companion until the next logon. Then the cycle repeats.
- Evidence: read of the revert, the ledger helpers and the two apply paths. Grep shows no reader of `reverted_from` in any gate (it appears only in the report payload, the toast and app.py:11022).
- Ledger: new (related to APP-5 / REL-2 / REL-8, all FIXED)
- Suggested fix: have the revert also record the bad version with `note_upgrade_attempt(..., error="crash-loop")` at MAX_UPGRADE_ATTEMPTS, or make `_upgrade_attempt_blocked` refuse `wanted == reverted_from` until a DIFFERENT version is offered. Consider having `_upgrade_info` skip a push/offer equal to the machine's `upgrade_reverted_from`.

### bug-comp-core-2 - The APP-5 rollback copy is deleted seconds after start, so the crash-loop revert cannot fire on an online machine (APP-5's own scenario is not covered)
- Severity: high
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/upgrade.py:907-950 (`keep_old_exe_until_healthy`); app.py:11074-11075 (health = `self._report_accepted.is_set`); reporter.py:101 (`INITIAL_DELAY_SECONDS = 2.0`)
- What: the health signal that makes `<exe>.old` expendable is "one dashboard report accepted". The first report goes out 2 s after start, and the keeper checks `healthy()` before its first 30 s wait. So on any machine that can reach its dashboard, the rollback copy is deleted within about 2-32 s of the new build starting. That is shorter than the flat 60 s timer APP-5 replaced. `revert_to_previous_build` then returns "there is no rollback copy".
- Failure scenario: APP-5's documented scenario (docs/resilience-sweep-2026-08-28/APP.md:58): a published build starts, puts its tray up, reports once, and hits a fault three minutes later (Tk fault in the first dialog, an exception on one editor's config path). It gets relaunched and dies 3 times in 10 minutes, and `crash_loop` is true. But `.old` was deleted at about the 30 s mark, so the log says "did NOT roll back: there is no rollback copy". The fleet-wide bad-build case the guard exists for can only be reverted on a machine whose dashboard is DOWN.
- Evidence: probe: `keep_old_exe_until_healthy(ev, lambda: True, cleanup=...)` returns immediately with reason "the dashboard accepted a report from it" and calls cleanup once. Read of app.py:2278 (report response -> `_note_report_accepted` sets the event).
- Ledger: regression of APP-5 (FIXED 2026-08-28; the implemented health signal defeats its stated window)
- Suggested fix: require BOTH signals before deleting: an accepted report AND a minimum uptime of at least CRASH_LOOP_WINDOW_SECONDS (10 min). Also require a clean-shutdown-free window. The keeper then only shortens the 60-minute fallback and never undercuts the crash-loop window.

### bug-comp-core-3 - The site manifest (feature flags, smb_unc, sftp tuning) is refreshed once per process start, so an admin's change does not reach a running companion
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/app.py:9342-9356 (the only `refresh_site` call); site.py:278-298 (`feature_enabled` reads the cache only); config.py:1829-1866 (`_apply_site_manifest`, cache at load)
- What: nothing refreshes `~/.ccsync/state/site.json` after the one background fetch at start. If that fetch fails, nothing refreshes it at all for the life of the process. That covers the common case of a laptop whose companion starts at logon before Tailscale is up. `feature_enabled` fails closed on the cache, so the only way a site change lands is a tray restart. Companions run for days or weeks.
- Failure scenario: (a) The owner turns `youtube_download` OFF in site.toml (the legal off switch, docs/legal/YOUTUBE_FEATURE_NOTICE.md). Every running companion keeps serving the ytdl stack until each editor restarts their tray. (b) The owner turns `auto_update` ON. No machine takes unattended builds until restarted, so the feature looks broken, the same symptom as the 0.9.41 "shipped inert" bug. (c) An editor whose machine started offline keeps a stale `smb_unc`, and the grade swap maps the old UNC.
- Evidence: grep: `refresh_site` is called once (app.py:9352). `save_site` is called only from `refresh_site`. No report-reply field carries the manifest.
- Ledger: new
- Suggested fix: re-run `refresh_site` on a slow cadence (for example every heavy report tick or every 15 min) on the reporter thread, or piggyback a manifest etag on the report reply and refetch when it changes.

### bug-comp-core-4 - Sign-in's /verify path carries no `arch` and no `upgrade_none_reason`, so it can offer a wrong-CPU build and it clears a standing refusal
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/identity.py:320-328 (verify payload: no `arch`), identity.py:343-360 (only `upgrade` is kept); app.py:6505 (`note_report_response({"upgrade": ...})`); dashboard/src/ccsync_dashboard/api.py:2079-2084 (VerifyIn has no `arch`), api.py:2232-2233 (no `withheld` sink)
- What: REL-16 made `arch` the channel's discriminator, and comp-app-3 made `upgrade_none_reason` the signal that stops the companion clearing a refusal. The report path carries both. The sign-in path carries neither. `_upgrade_info` treats "no arch" as "offer everything", and `upgrade._check_offer` deliberately does not check arch. `note_report_response` is then handed `{"upgrade": X}` or `{"upgrade": None}`, with no `upgrade_none_reason`.
- Failure scenario: (a) An Intel Mac signs in while current is the arm64 build. The verify reply offers it, and the tray shows "Update available". With `auto_update` on, `_on_upgrade_available` applies it at once: download, swap, then exec fails ("Bad CPU type"). A rollback follows and REL-8 counts an attempt, which is REL-16's exact symptom. (b) A machine with a standing refusal of a retracted build, or one that needs a newer dashboard, signs in. The verify reply has no `upgrade` key and no reason, so the refusal is cleared. The next report reply withholds with `upgrade_none_reason` and does not restore it, so `[ REFUSING x ]` and the `upgrade_refused` alert vanish for good (the comp-app-3 hole, reopened through sign-in).
- Evidence: read of both sides of /api/v1/verify and of `note_report_response`'s clearing rule (upgrade.py:1561-1592).
- Ledger: related to REL-16 and comp-app-3 (both FIXED on the report path only)
- Suggested fix: send `arch` in `verify_credentials` and declare it on VerifyIn. Pass `withheld` in api_verify and return `upgrade_none_reason`. Have `verify_credentials` forward that key, and have app.sign_in pass the whole reply shape to `note_report_response`.

### bug-comp-core-5 - A manifest scan that overlaps a drive unplug reports zero files for the remaining projects, the "indistinguishable from deleted" case the guard exists for
- Severity: medium
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/manifest.py:316-347 (`refresh_once` checks presence only BEFORE the scan), manifest.py:186 (`os.walk(project_dir)` with no `onerror`)
- What: `refresh_once` skips the scan while the root is absent, so an unplugged drive is never reported as an empty tree. But presence is sampled once, before a walk that can take minutes on a large tree. `os.walk` silently swallows `scandir` errors, and `size_fn` OSErrors are `continue`d. So a drive that disappears mid-walk yields rollups of 0 files / 0 bytes for every project not yet walked, and that result replaces the cache.
- Failure scenario: a Mac editor ejects their SSD while the 300 s manifest refresh is walking it. The cache now holds 0 originals/proxies for most projects, and the next heavy report sends it (a changed digest, so it is not suppressed). The dashboard's presence view shows the editor holding nothing for up to 10 minutes, or until the drive returns and a later scan runs. The reporter keeps sending it, because the root guard does not pause the reporter.
- Evidence: read. Python's documented `os.walk` behaviour ignores errors when `onerror` is None. No post-scan presence check exists.
- Ledger: new
- Suggested fix: re-check `self._root_is_present()` after `scan_local_manifest` returns and discard the result if the root went away. Alternatively, pass an `onerror` that aborts the scan.

### bug-comp-core-6 - Repairing an unreadable machine id does not reach the dashboard until the tray restarts, although the toast says "from the next check in"
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/reporter.py:704-717 (`_machine_id` caches "" for the process lifetime); settings_window.py:497-506 (remint + toast)
- What: the reporter caches the empty answer on purpose ("so a read-only home directory is not re-tried"). But comp-app-8 added `machine.remint()`, a repair a human presses in Settings, and nothing invalidates `_machine_id_cache`. The new id is written to disk, and every report in this process keeps sending `machine_id: null`.
- Failure scenario: an editor sees the unreadable-id advisory, presses GIVE IT A NEW ID, and is told "It is reported from the next check in". The dashboard keeps seeing no id until the companion is restarted. If the computer is renamed before that, the rename affordance the repair was meant to restore is still missing.
- Evidence: probe: a getter answering "" then "newid" -> `_machine_id()` returns None twice and the getter is called once.
- Ledger: related to comp-app-8 (FIXED)
- Suggested fix: cache only a non-empty id (re-read "" at most every few minutes), or have `action_repair_machine_id` reset `app.reporter._machine_id_cache = None` after a successful remint.

### bug-comp-core-7 - A sign-in whose reply token is unusable still overwrites a working identity.json on disk
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/identity.py:514-541
- What: `sign_in` calls `save_identity(...)` with the new token BEFORE it checks `self.valid()`. When the check fails (unparseable token, or a pre-CR-86 expiry against a skewed clock), the in-memory identity is set to None and an error is returned. But the file on disk already holds the unusable token, replacing whatever identity was there.
- Failure scenario: an editor who is signed in re-enters credentials (for example to switch accounts). The dashboard answers 200 with a token this build cannot parse (a dashboard/companion token-shape skew). The tray says the reply could not be used, which suggests nothing changed. On the next start `load_identity` reads the broken token, `is_valid` is False, and the machine is signed out. With `require_login` on it stops reporting.
- Evidence: read; the order is save, then validate.
- Ledger: new
- Suggested fix: build the candidate identity dict, run `is_valid` on it first, and only then call `save_identity` and publish it.

## Coverage note
Not reviewed in depth: config.py `validate_config` and DEFAULTS/DEFAULT_TOML_TEXT, paths.py `classify_path`, shutdown_guard.py's Win32 window-class/pump and Darwin guards, root_guard.RootGuard's loop and filesystem-answer probe, capabilities/job gate interplay beyond the section builder. Also considered but not filed as a finding: `root_guard.local_root_is_removable` is only ever true on macOS (the volume record is written on darwin only), so a Windows editor whose local_root is on a USB SSD that is unplugged at logon keeps a permanent config error until restart. That may be out of the supported deployment; worth a line from the owner.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/api.py:2232: api_verify's `_upgrade_info` call ignores `targeted_staged_package`, `arch` and `withheld` (the dashboard half of finding 4).
- dashboard/src/ccsync_dashboard/api.py:5772: `_upgrade_info` never consults `machine_state.upgrade_reverted_from`, so it re-offers and re-pushes the build a machine just crash-loop-reverted from (the dashboard half of finding 1).
