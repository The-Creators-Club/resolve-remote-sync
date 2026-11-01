# Pre-launch resilience review - lens res-upgrade (upgrades and rollbacks under adversity)

Date 2026-10-06, HEAD 08b40eb plus the uncommitted working tree. Read-only.

**Covered (read end to end):** `companion/upgrade.py` (offer check, floor,
apply/swap/rollback, takeover grace, crash-loop start record, revert, `.old`
retention, attempt ledger), `companion/app.py` (`run()`, `CompanionApp.run`
start-up order, `_revert_crashing_build`, `apply_upgrade`, stand-down
predicate, auto/pushed update loops, EULA gate and licence watch),
`companion/supervisor.py` (relaunch policy, deliberate exit codes,
interrupted-upgrade restore), `companion/eula.py`, `companion/config.py`
(`REQUIRES_DASHBOARD`), `dashboard/deploy/select_code_root.py` (whole file),
`dashboard/deploy/run.sh` (restart loop), `dashboard/dashboard_update.py`
(watchdog, probe, apply, backups, rollback schema check),
`dashboard/db.py` `migrate()`, `dashboard/app.py` lifespan start, compose
files (image, appliance), `tools/sign_release.py` / `tools/publish_latest.py`
(kind-extras gate, min-version), `tools/release.ps1` and
`.github/workflows/release-windows.yml` (looking for a launch smoke test),
`installer/windows_upgrade.ps1` (`.prev` handling), `package_store.py` soak
gate. Cross-checked against KNOWN_BUGS (REL-6, REL-8, res-fleet-2, CR-270,
bug-comp-core-1/2, comp-app-core-3), `docs/resilience-sweep-2026-08-28/REL.md`
and `docs/ZERO_DOWNTIME_DEPLOY.md`.

**Not covered:** live behaviour on a real container or a real frozen exe (no
probe can launch either here without touching live systems); the macOS
LaunchAgent relaunch path beyond reading; Cards engine state across a
dashboard restart; b-roll/music database migrations at boot (best-effort
mounts, covered by other lenses).

---

### res-upgrade-1 - A bad companion build that fails at start-up is never rolled back, and nothing tests that a build starts before it is published

- **Severity:** high
- **Confidence:** CONFIRMED (code read end to end)
- **Where:** `companion/src/ccsync_companion/app.py:12036-12139` (`run()`: imports, config, single-instance, `CompanionApp(cfg)` all before the start record), `app.py:11758-11771` (`note_version_start` is the first line of `CompanionApp.run`), `companion/src/ccsync_companion/supervisor.py:132-137,184` (exit code 1 is DELIBERATE, never relaunched; 3 relaunches an hour), `upgrade.py:97` (`CHILD_TAKEOVER_GRACE_SECONDS = 2.0`), `upgrade.py:253-329` (crash-loop window 3 starts / 10 min), `upgrade.py:981-1040` (`.old` deleted after 10 min + one accepted report), `tools/release.ps1`, `.github/workflows/release-windows.yml`, `tools/release_macos.sh` (no step launches the built exe)
- **What:** The automatic rollback (APP-5/REL-2) only counts a start once `CompanionApp.run()` reaches `note_version_start`. Three shapes of bad build escape it entirely:
  1. Dies before that line: a module missing from the PyInstaller freeze, a broken import, an exception in the 3,000-line `CompanionApp.__init__`. No start is ever recorded, so `crash_loop` is never true.
  2. Dies with a Python-level exception anywhere (exit code 1; on macOS the atexit "exiting" stamp). The supervisor treats that as deliberate and does not relaunch. Only the logon Run key or a human starts it again, so the "3 starts in 10 minutes" condition is never met unattended.
  3. Dies natively but later than about 5 minutes after start. Supervisor relaunches are 10 s apart plus run time, so three starts drift outside the 10-minute window and the counter resets. After 10 minutes plus one accepted report, the `.old` rollback copy is deleted anyway.
  The upgrade's own 2-second takeover check does not help: a 54 MB onefile exe usually takes longer than 2 s to extract and import before it can fail. Nothing in `release.ps1`, `release-windows.yml` or `release_macos.sh` runs the frozen binary even once (for example with a `--self-test` flag), so a build that cannot start is signed, published and offered.
- **Scenario:** The vendor publishes 0.9.86, whose freeze is missing a lazily imported module, or whose `__init__` reads a config key that some customer machines have hand-edited to a string. Every customer with `auto_update` on, or whose admin presses UPDATE NOW for the fleet, swaps in 0.9.86. It exits 1 a few seconds after the predecessor has stood down. No relaunch, no crash-loop revert. The `.old` is on disk but nothing uses it. Every affected machine stops syncing and reporting until somebody at each machine renames the file by hand. That is a fleet-wide outage at sites we cannot reach.
- **Recommendation:** (a) Add a release-gate smoke test: run the frozen exe with a `--self-test` flag that imports every module, builds `CompanionApp` against a temporary config and exits 0. Do this in `release.ps1`, `release-windows.yml` and `release_macos.sh`, and refuse to write a manifest if it fails. (b) Move the start record to the very top of `run()`, before `CompanionApp(cfg)`, in a stdlib-only helper. Also count an unclean exit (the run marker still present at the next start) as a failed start, whatever the exit code. (c) After a self-upgrade, have the supervisor relaunch exit-code-1 deaths of a just-upgraded version (the version state says `upgraded`), so the crash-loop counter can actually reach three. (d) Raise the takeover grace, or have the new build write a "started" marker that `apply()` waits for, up to 30 s, before it stands down.
- **Known:** not recorded. APP-5/REL-2 and bug-comp-core-1/2 are FIXED for crashes after `run()` starts. This gap is in front of them.

### res-upgrade-2 - When a dashboard update has migrated the database, a failing boot can never get back without a shell

- **Severity:** high
- **Confidence:** CONFIRMED (code read; the decision table in `select_code_root.main` traced for each case)
- **Where:** `dashboard/deploy/select_code_root.py` `main()` (revert refused at the `MAX_BOOT_ATTEMPTS` branch, then `check_tree` boots the same tree again; refusal branch boots the image with no schema check), `revert_refusal()`, `dashboard/src/ccsync_dashboard/db.py:2291-2335` (each step commits on its own, raises "database schema is newer than this build"), `dashboard/app.py:736-738` (`db.migrate` at the top of lifespan, uncaught), `dashboard_update.py:1263-1290` (`restore_backup` is reachable only through the dashboard's own routes)
- **What:** res-fleet-2 stops the watchdog from reverting into a tree that cannot open the database. Nothing replaces the revert, though, so these cases loop for ever:
  1. **Partial multi-step migration.** The OTA tree carries migrations v60..v63. v60-v61 commit and v62 fails on live data that the stage-verify copy did not have. That happens most easily on a customer who skipped many releases, so one bundle carries many steps. Each boot raises out of `migrate`, `boot_attempts` reaches 2, and the revert target knows v59 while the database is on v61. The revert is refused, the same failing tree boots again, and the loop never ends.
  2. **The tree is refused after it migrated.** `check_tree` rejects the tree, for example because `record.json` is damaged, `DASH_RELEASE_PUBKEYS` is missing after a container recreate, or `/venv/.runtime-id` is missing. The script then prints the IMAGE path with no `revert_refusal` check. The image's `migrate` raises "schema is newer", the container exits non-zero, and `restart: unless-stopped` restarts it for ever. On the tree-shaped refusals the counter reaches 2, the revert is refused, and it still boots the image.
  The refusal sentence tells the admin to "restore the backup taken before this update and roll back from the dashboard". The dashboard is the thing that is down, and no out-of-band restore tool exists in `tools/`, `server/` or `deploy/`.
- **Scenario:** A customer's appliance with `policy = current` applies a three-migration bundle overnight, and the third step trips on a duplicate row that arrived after staging. The dashboard is down permanently: no fleet page, no alerts (they come from the same process), and companions lose commands, halts and pushes. Recovery needs `docker exec`, `sqlite3` and a hand copy of `/data/backups/...`, which an appliance customer has no means to do.
- **Recommendation:** When a revert is refused on schema AND `current.json` names the backup this apply took, have `select_code_root.py` (image code, stdlib `sqlite3.backup`) restore that backup over the live database, move the failed live copy aside, and THEN revert, recording all of it in `current.json`. The data lost is only what arrived since the apply. Apply the same `revert_refusal` question before every "boot the image instead" exit in `main()`, and use the same restore when it says no. Consider also running all of a bundle's steps in ONE transaction (SQLite DDL is transactional), so a partial migration cannot exist.
- **Known:** res-fleet-2 / regression-3 (FIXED) created the refusal. The no-escape consequence is not recorded.

### res-upgrade-3 - A dashboard update that boots but cannot serve is never reverted: the watchdog only "leaves the counter standing" and nothing restarts the process

- **Severity:** high
- **Confidence:** CONFIRMED (code read; compose healthcheck has no restart action)
- **Where:** `dashboard/src/ccsync_dashboard/dashboard_update.py:488-514` (`start_boot_watchdog`: on a failed probe it logs and `return`s), `dashboard/deploy/select_code_root.py` (the revert happens only "at the next start", after `MAX_BOOT_ATTEMPTS = 2` counted boots), `dashboard/deploy/compose.image.yaml:345-356` (`restart: unless-stopped` plus a healthcheck that only marks the container unhealthy; plain Docker never restarts an unhealthy container)
- **What:** REL-6 was written for "uvicorn binds but a lifespan thread deadlocks / every request 500s". The fix makes the watchdog refuse to clear `boot_attempts.json`, but the wedged process keeps running, so there is no "next start". The revert needs TWO container restarts that nobody at the site knows to perform: one to count attempt 2, one to act on it. In the deadlocked-lifespan case uvicorn never binds at all (lifespan runs before bind), so every page is down, as is the Packages page's rollback button.
- **Scenario:** An OTA bundle that has a lifespan-time deadlock, or a missing template that 500s the health route, is applied unattended. The container stays "Up (unhealthy)" indefinitely, companions get nothing back from their reports, and the customer sees a dead dashboard. The KNOWN_BUGS REL-6 symptom is exactly this, and its "fixed" state still yields it.
- **Recommendation:** When the boot probe fails and the running code is a volume tree, exit the process with a non-75, non-zero code (or `os._exit`). The container restarts, `select_code_root` counts the next boot, and the second failure reverts on its own within about 3 minutes. Keep the current behaviour (log only) when running the image's own code, where there is nothing to revert to. Optionally also probe one HTML route and `/api/v1/report`'s 401 path, as ZERO_DOWNTIME_DEPLOY.md 3.2 suggests.
- **Known:** REL-6 (marked FIXED). This is the part of its own symptom that the fix does not cover.

### res-upgrade-4 - The appliance stack has no release key and no feed, so a zero-touch customer can never be updated or publish a companion

- **Severity:** high
- **Confidence:** CONFIRMED that the files carry neither setting. Whether the appliance stack is the launch install path is the owner's call.
- **Where:** `dashboard/deploy/compose.appliance.yaml:36-41,153-159` (says `DASH_RELEASE_PUBKEYS` is "generated into secrets on first boot"), `dashboard/src/ccsync_dashboard/secrets_boot.py:52-58` (`SECRET_ENV_VARS` does not include it, and it is a vendor public key that cannot be "generated"), `dashboard/src/ccsync_dashboard/settings.py:910-915` (read from env only, no baked default), `dashboard/deploy/select_code_root.py` (`ENV_REFUSALS[0]`)
- **What:** The appliance compose sets neither `DASH_RELEASE_PUBKEYS` nor `DASH_RELEASE_FEED_URL`. Its comment claims the key is generated at first boot, but `secrets_boot` does not handle it, and a release PUBLIC key is vendor identity that has to be baked into the image, not minted per site. With no key:
  - every companion publish is refused (503);
  - the feed poller cannot verify anything (and has no URL anyway);
  - `select_code_root` never boots an OTA tree.
  The only way such a customer moves forward is re-pulling the `:1` image by hand, and editors' machines can never be offered a companion build by their own dashboard.
- **Scenario:** A second organisation installs through the appliance stack (the ZERO_TOUCH direction). Install works. Their editors are installed from a package and then stay on that build for ever. A security fix cannot reach them, and the vendor recall/soak machinery has nothing to act on.
- **Recommendation:** Bake the vendor release public key(s) into the image (for example `/app/deploy/release_pubkeys`, read by both `Settings` and `select_code_root.py` when the env var is empty; env still wins). Set `DASH_RELEASE_FEED_URL` to the vendor feed in `compose.appliance.yaml`, with `policy=manual` as default. Correct the misleading compose comment. Add an appliance boot check that refuses, or raises a notice, when no key is configured.
- **Known:** COMMERCIAL_READINESS item 4 notes "set DASH_RELEASE_PUBKEYS on both live dashboards". The appliance gap is not recorded.

### res-upgrade-5 - "Deploy the dashboard before the companions" is still enforced by nobody at a customer site: requires_dashboard is not signed, and its value is stale

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `tools/sign_release.py:360-389` (kind extras opt-in via `CCSYNC_EMIT_KIND_EXTRAS=1`, otherwise `requires_dashboard` is dropped), `tools/publish_latest.py:500-525` (says so and proceeds), `companion/src/ccsync_companion/config.py:158-174` (`REQUIRES_DASHBOARD = "0.7.23"` while KNOWN_BUGS lists later dashboard-first changes: CR-282A/CR-283W/X/CR-284H/CR-285AX at 0.7.50, the LG-1 telemetry and account page at 0.7.60-0.7.61), `dashboard/release_feed.py:930-980` (the gate exists but is fed an empty field)
- **What:** The SYS-2/REL-4 ordering gate, which stages a companion that needs a newer dashboard, only works when the record is signed with `requires_dashboard`. The vendor feed does not sign it, by an opt-in that was only needed while pre-0.9.55 machines existed. Every machine in the known fleet is now 0.9.75 or newer, and new customers start on current builds. The constant itself has not been raised since 0.7.23.
- **Scenario:** A customer's dashboard cannot take the latest bundle because it needs a runtime/image update (a NAS-UI click nobody makes), or because its OTA was reverted. The feed's `current` policy still makes the newest companion current, and `auto_update` installs it. The companions now send words and sections the dashboard predates. The documented failure classes are a 422 on every report (machine invisible, no halt/push/commands delivery), IGNORED banners, and per-machine enforce mismatches (the B16 shape CLAUDE.md warns of).
- **Recommendation:** Turn kind extras on in the vendor publish (`CCSYNC_EMIT_KIND_EXTRAS=1` in CI/publish_latest by default, with an explicit opt-out). Raise `REQUIRES_DASHBOARD` to the newest dashboard version a companion feature actually depends on, and add a release-checklist line ("did this build start reading a new reply key or sending a non-tolerant word?"). Consider a test that fails when a companion change touches report/reply keys without bumping it.
- **Known:** REL-4/SYS-13/SYS-7 (gate built), logic-release-5 (noted the field is dropped). Still open in effect.

### res-upgrade-6 - Image and runtime updates migrate the live database with no backup and no way back

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/app.py:736-738` (`db.migrate` unconditionally at lifespan start), `dashboard_update.py:1016-1037` (`backup_databases` is called only from the OTA `apply` and `snapshot_before`), `db.py:2306-2313` (an older image refuses a newer schema)
- **What:** The OTA path backs up every database before migrating. The other update path, a new image pulled from the NAS app manager (which the code itself prescribes for every runtime/dependency change, and the only path on bind-mount or appliance sites), migrates the live `dashboard.db` at first boot with no copy taken. If the new image is bad, going back to the previous image tag is refused by `migrate` ("schema is newer than this build"). Unless the NAS has a snapshot schedule (studio TrueNAS: yes; a customer's Synology: unknown), there is nothing to go back to.
- **Scenario:** A customer clicks "Update" in Container Manager. The new image boots, migrates v59 to v62, then fails on something unrelated (or works badly). Support tells them to pin the previous tag, and that container refuses to start. Recovery requires the vendor's hands on their NAS.
- **Recommendation:** In the lifespan, before `db.migrate`, when `PRAGMA user_version < SCHEMA_VERSION`, take the same `backup_database` copy into `/data/backups/<ts>-pre-migrate-v<n>/`, pruned by the existing retention. Record it where `select_code_root` / the Packages page can name it, and pair it with res-upgrade-2's automatic restore.
- **Known:** not recorded.

### res-upgrade-7 - A licence-version bump parks syncing (uploads included) on every machine that auto-updates, with no warning at publish time and no re-prompt after a decline

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/eula.py:220-250` (`acceptance_problem`: older accepted version blocks), `app.py:6697-6790` (`_start_lanes` EULA gate stops lanes A, B and C), `app.py:6497-6530` (`_licence_watch` stops after one showing, even a decline), `tools/publish_latest.py` / `tools/sign_release.py` / dashboard Packages (no awareness of the EULA version a build carries)
- **What:** Bumping `<!-- EULA-VERSION -->` is, by design, a re-consent. Through the upgrade channel, that means every machine that takes the build stops syncing at once, including lane A uploads of originals, until a person at that machine clicks ACCEPT. Unattended machines (render rigs, overnight auto-updates, editors on leave) stay parked. If the dialog was shown once and closed, it is never offered again on its own (`_licence_asked`). The only trace is a `licence_pending` chip on the dashboard. Nothing at publish or make-current time says "this build will stop syncing on N machines until each accepts", and the release record does not carry the EULA version, so neither the dashboard nor `auto_update` can hold the build back.
- **Scenario:** Counsel revises the EULA after launch (1.1 to 1.2). The vendor ships 0.9.90. Every customer site on `auto_update` loses all sync overnight. Footage shot that day is not uploaded until each editor finds and accepts the dialog. One editor closed it without reading, and their uploads stay parked for days.
- **Recommendation:** Sign the bundled EULA version into the companion record (kind extra), show it on the Packages page and in `publish_latest`, and require an explicit confirmation to make current a build that raises it. Do not install such a build unattended (`auto_update` should leave it for a click). For a re-consent (an older version WAS accepted), keep syncing for a grace period while nagging, rather than parking at once. Re-offer the dialog daily after a decline. Counsel should confirm whether continuing under the previously accepted version during a grace period is acceptable.
- **Known:** memory "EULA gate parks self-upgraded editors" and "EULA 1.1 re-consent parks 0.9.82 machines" (ship 2026-09-25). No KNOWN_BUGS entry. Open.

### res-upgrade-8 - Unattended and pushed updates restart the companion in the middle of a transfer

- **Severity:** medium
- **Confidence:** CONFIRMED (stand-down predicate read). PLAUSIBLE on the exact cost per backend.
- **Where:** `companion/src/ccsync_companion/app.py:6948-6966` (`_standing_down_would_kill_work` checks only an open popup and consolidate), `app.py:8426-8470` (`_run_auto_update`), the pushed path at `app.py:8541+`
- **What:** The only things that defer a self-upgrade are an open CCSync window and an in-progress consolidate. An active lane A upload, a lane B download, a fleet job's ffmpeg/whisper child, a file-move application and a ytdl download all get stood down mid-flight. rclone over SFTP does not resume a partial upload, so the file restarts from zero.
- **Scenario:** A remote editor on a ~0.45 MB/s uplink (the leso case: one 22 GB original takes about 14 hours) has `auto_update` on. Each published build restarts the companion part-way through that file, and the upload starts over. With a weekly release cadence plus pushes, a large original may never finish.
- **Recommendation:** For unattended and pushed updates, also defer while any lane reports an active transfer or a fleet job is held, with a cap (for example 6 hours) after which the update proceeds. A person's own click from the tray can still go immediately, with a warning that names the transfer.
- **Known:** not recorded.

### res-upgrade-9 - A min_version floor equal to the release disables that release's automatic rollback everywhere

- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/upgrade.py:1546-1560` (floor raised on RECEIPT of an offer), `upgrade.py:1083-1086` (crash-loop revert refused below the floor), `tools/publish_latest.py:381` / `installer/build_editor_package.ps1:1039-1052` (`--min-version` / `CCSYNC_MIN_VERSION` free-form, only "not above version" is checked)
- **What:** The floor is raised as soon as an offer is seen. A release published with `min_version == version` (the natural spelling of "everyone must be on at least this") makes every machine's previous build sit below its own floor, so APP-5's automatic rollback refuses with "the crash loop needs a human". The vendor-side rollback (republish the old version as current) is refused too. The safety net disappears exactly for the release that raised the floor.
- **Scenario:** A security release 0.9.90 is published with `--min-version 0.9.90` and happens to crash on some customer machines. None of them can revert, and the old build cannot be offered either.
- **Recommendation:** Refuse (or require `--allow-floor-at-self`) a `min_version` above the newest build already CURRENT for that platform, so the floor always trails the release by one. Document "floor = previous release" as the rule in RELEASE.md.
- **Known:** CR-52 / comp-app-core-3 cover a floor ABOVE the version. This case is not recorded.

### res-upgrade-10 - After a manual (package) install, a stale `.old` from an earlier self-upgrade is restored under the wrong version name

- **Severity:** low
- **Confidence:** PLAUSIBLE (both code paths read; the interleaving not reproduced)
- **Where:** `installer/windows_upgrade.ps1:204-263` (keeps the replaced build as `.prev` and never touches `.old`), `companion/src/ccsync_companion/upgrade.py:1043-1100` (`revert_to_previous_build` restores `<exe>.old` and labels it `previous_version` from the start record)
- **What:** A self-upgrade leaves `.old` until the new build has proven itself (10 minutes plus a report). If the package installer runs inside that window (for example the editor re-runs it, or ship's local upgrade), the machine has exe=new, `.prev`=intermediate, `.old`=the one before that. If the new build then crash-loops, the revert restores the OLDEST binary, writes the intermediate version into the start record, and floor-checks the wrong version.
- **Scenario:** 0.9.84 to 0.9.85 by OTA, then 0.9.86 by installer 3 minutes later. 0.9.86 crash-loops, so 0.9.84 is restored but recorded as 0.9.85. A floor of 0.9.85 would have refused it. The UI and the report say 0.9.85 restored, but 0.9.84 is what runs, until its first report reveals the version.
- **Recommendation:** Have `windows_upgrade.ps1` delete (or fold into `.prev`) any `.old`, or have the revert read the version from the `.old` binary itself (its embedded version resource or a sidecar `.old.version` written at swap time) rather than from the start record.
- **Known:** not recorded.
