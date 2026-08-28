# Release, upgrade channel and trust (REL)

## Summary
The cryptographic half of this area is in unusually good shape: offline ed25519 over a
canonical record, verified on publish, on apply, at every dashboard boot and again in the
companion before a byte is downloaded; no-redirect openers, byte ceilings, free-space
checks, sha-then-chmod ordering, a rollback around the exe swap, a boot-attempt watchdog
for the dashboard's own code. What is missing is almost entirely on the *operational*
side: there is no staged rollout, no recall, no failure telemetry, and no bound on disk.
One `-MakeCurrent` (or one vendor `current` pointer under the `current` policy) hands a
build to every machine at once, and the only thing standing between a bad build and the
whole fleet is that the companion watches its replacement for **2 seconds**
(`upgrade.py:96`) and deletes the rollback copy 60 s later (`app.py:6782`). The biggest
single risk is that combination: a build that starts and dies at minute five leaves a
machine with no companion, no `.old`, and nothing that restarts it before the next logon.
The best cheap win is REL-6: the dashboard's crash-loop watchdog currently proves only
that the process did not exit within 45 s (`dashboard_update.py:320`) - making it prove a
served `/api/v1/health` instead is a dozen lines and closes the "boots but wedges" hole in
the one mechanism designed to self-heal without an admin.

## Findings

### REL-1: a build reaches every machine at once - there is no canary, though every part of one exists
- **Lens:** safeguard
- **Where:** `tools/ship.ps1:601` (`-Publish -MakeCurrent` in one call), `dashboard/src/ccsync_dashboard/release_feed.py:588` (`make_current=(policy == "current")`), `dashboard/src/ccsync_dashboard/api.py:3913` (`get_current_package` is what every report answer reads)
- **Scenario:** the owner ships a companion at 18:00. `-MakeCurrent` flips `is_current`, and within one report interval (30 s) every machine in the fleet is offered it; on a site with `auto_update` on, every machine also *takes* it, unattended.
- **Today:** verified - nothing in the publish path stages a build against a subset first, and there is no `canary`/`cohort`/`ring` concept anywhere in the tree (grepped). The pieces are all present but unused: `publish_package` can publish without `make_current`, `db.machine_update_request` can push a build to ONE machine (`api.py:5518`), and every machine reports its running version every 30 s.
- **Proposed:** make `ship`/`publish_latest` publish **staged** by default and add a `[ MAKE CURRENT ]` gate on the Packages page that refuses (with an explicit override) until at least one machine has reported the new version AND stayed reporting for N minutes. The guided flow is: publish staged -> push to the base rig / one volunteer via the existing per-machine `commands.upgrade` -> the page shows "1 machine on 0.9.55 for 22 min, 0 crashes" -> make current. State lives in `companion_packages` (a `staged_soak_started_at`) plus the machine reports already in `machine_state`.
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** MULTI_MACHINE_PLAN.md §9 (the push channel), release-pipeline-5 (the `current` pointer)

### REL-2: a companion that dies after 2 seconds has no way back, and nothing restarts it
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/upgrade.py:96` (`CHILD_TAKEOVER_GRACE_SECONDS = 2.0`), `:999-1011` (the poll window), `companion/src/ccsync_companion/app.py:6782` (`.old` deleted 60 s after start), `upgrade.py:1078` (the LaunchAgent is RunAtLoad-only, the Windows Run key is logon-only)
- **Scenario:** 0.9.55 starts fine, then crashes at minute six the first time a lane touches a path with a surrogate, or when the Resolve bridge loads. The editor is mid-edit and notices nothing; the tray icon is simply gone.
- **Today:** verified - `_apply_inner` only rolls back if the child exits inside 2 s; `cleanup_old_exe` is armed on a 60 s timer at every start, so from minute one there is no previous binary on disk. Nothing supervises the process (no KeepAlive, no service), so the machine has no companion - no lanes, no Resolve fixer - until the editor next logs in, and then it crashes again.
- **Proposed:** mirror the dashboard's own watchdog, which already solves this: a `~/.ccsync/state/boot_attempts.json` keyed on version, bumped at start and cleared only after N minutes of uptime AND one successful report; two failed runs of a version restore `<exe>.old` automatically and toast "v0.9.55 would not run - you are back on v0.9.54". Keep `.old` until that first healthy run (an hour, not 60 s) instead of on a fixed timer, and report the revert in the next report so the dashboard shows it.
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** AUDIT_2 CORE-H6/R11 (why the timer exists), `dashboard_update.MAX_BOOT_ATTEMPTS` (the pattern to copy)

### REL-3: there is no recall - a build already taken cannot be pulled back
- **Lens:** pitfall
- **Where:** `dashboard/src/ccsync_dashboard/release_feed.py:567` (`policy == "manual"` returns immediately), `:582-592` (only a `current` policy re-points), `companion/src/ccsync_companion/app.py:4610-4620` (auto-update refuses anything not `VERSION_NEWER`)
- **Scenario:** the vendor discovers 0.9.55 corrupts something. `publish_feed.py --retract` removes the record and moves `current` back to 0.9.54.
- **Today:** verified - a customer dashboard on the default `manual` policy never acts on the channel again: 0.9.55 stays published and `is_current`, and its fleet keeps being offered it. Even on the `current` policy, machines that already installed 0.9.55 get offered 0.9.54 as an "older build" that `auto_update` deliberately refuses (correctly - rolling backwards is an admin decision), so recovery is a per-machine `[ UPDATE NOW ]` click for every editor.
- **Proposed:** a signed `retracted: [{kind, platform, version, reason}]` block in the channel, honoured under EVERY policy: the dashboard un-currents that row, refuses to serve it, shows the reason on Packages and Fleet, and offers one `[ ROLL THE FLEET BACK TO x ]` button that writes a `machine_update_request` for every machine currently reporting the retracted version (that channel already exists and already bypasses the "newer only" rule).
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** release-pipeline-5 (`--retract` exists in the tool, nothing consumes it), CR-45's resume command (the same delivery shape)

### REL-4: "deploy the dashboard before the companions" is enforced nowhere in the machinery
- **Lens:** pitfall / user-error
- **Where:** no `min_dashboard`/`requires_dashboard` field exists (grepped repo-wide); `dashboard/src/ccsync_dashboard/release_trust.py:33-43` (`RECORD_FIELDS`), `release_feed.py:576` (dashboard bundles are deliberately excluded from auto-publish, companions are not)
- **Scenario:** a customer site runs the `current` feed policy. The vendor publishes companion 0.9.54 (upload-only ticks, per-machine plans). The customer's dashboard is three months old and its `selections` table has no `sync_mode` column. Every companion on the site takes 0.9.54 overnight; nobody clicked anything.
- **Today:** verified - the companion record carries `min_version` (its own downgrade floor) and nothing about the dashboard it needs. CLAUDE.md states the ordering rule four times; the code never checks it. This is the B16 unshare-the-fleet shape with the arrow reversed.
- **Proposed:** add a signed `min_dashboard` to companion records via the existing `KIND_EXTRA_FIELDS` mechanism (scoped to `kind`, so no v2 prefix and no overlap release), and make `_upgrade_info` refuse to advertise - and `publish_from_feed` refuse to auto-publish - a companion whose `min_dashboard` is above the running dashboard's VERSION, with the Packages page saying "update the dashboard first".
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** `release_trust.KIND_EXTRA_FIELDS` (the precedent), MULTI_MACHINE_PLAN.md, UPLOAD_ONLY_TICK.md

### REL-5: nothing on the release path ever prunes, and a full `/data` takes the dashboard down
- **Lens:** pitfall
- **Where:** `dashboard/src/ccsync_dashboard/release_feed.py:717` (`prune=False` on every feed publish), `dashboard/src/ccsync_dashboard/api.py:4045` (`?prune=1` is opt-in and `ship` does not pass it), `dashboard_update.py:766` (a new `/data/backups/<ts>-<label>/` per apply, never deleted), `:989` (old `/data/code/<version>` trees are never removed), no `shutil.disk_usage` on either publish path
- **Scenario:** a year of shipping. `/data/packages` holds 50 companion exes and 50 onboard exes; `/data/backups` holds a full copy of `broll.db` and `music.db` per dashboard update; `/data/code` holds every bundle ever applied. `/data` also holds `dashboard.db`.
- **Today:** verified - `db.prune_companion_packages` exists and keeps current + 2, but neither writer calls it by default. `dashboard_update.preflight` refuses an apply at 507 when space runs low (good), but the package PUT and the feed publish have no free-space check at all, so they are what fills the volume - and a full volume is a SQLite write failure, i.e. "the dashboard that tells everyone whether their footage is syncing" going down.
- **Proposed:** prune by default on both publish paths (keep current + 2, the existing helper); cap `/data/backups` at the newest N per label with a size budget, and `/data/code` at the running tree + `previous` + one; refuse a publish with 507 below a free-space floor the way the code update already does; put a `/data` free-space gauge in `/api/v1/health` and on the Packages page.
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** DOCKER.md:186, `dashboard_update.MIN_FREE_BYTES` (the pattern), setup_engine's backup-age check (the only reader of `list_backups`)

### REL-6: the dashboard's crash-loop watchdog calls a boot healthy without asking whether it can serve
- **Lens:** pitfall
- **Where:** `dashboard/src/ccsync_dashboard/dashboard_update.py:318-327` (`time.sleep(BOOT_HEALTHY_SECONDS)` then `clear_boot_attempts`), `deploy/select_code_root.py:273-281` (the counter that reverts)
- **Scenario:** an applied bundle imports cleanly (stage-verify passes - that is exactly what it tested), boots, and then every request 500s because a template it needs is missing from the tarball, or uvicorn binds but a lifespan thread deadlocks.
- **Today:** verified - the watchdog thread sleeps 45 s and unlinks `boot_attempts.json` regardless of whether the process ever answered a request. The tree is then permanently "healthy": `select_code_root` will keep booting it, the auto-revert never fires, and the admin cannot use the dashboard to roll it back because the dashboard is the thing that is broken. Compose has `restart: unless-stopped`, which restarts a *crashed* container, not a wedged one.
- **Proposed:** before clearing the counter, make one loopback `GET http://127.0.0.1:${DASH_PORT}/api/v1/health` and require a 200 whose `version` equals `VERSION`; retry for up to BOOT_HEALTHY_SECONDS and leave the counter standing if it never answers. Same file, same thread, no new state.
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** WPK-3 (the code path is untested against a real container)

### REL-7: a mis-rotated release key strands the fleet permanently, and the parity check cannot see it
- **Lens:** user-error
- **Where:** `tools/release_key.py:152-175` (`bake` replaces unless `--add`; it warns, it does not refuse), `tools/release.ps1:492-527` (the parity check compares the signing key to the keys baked into **the build being built**), `companion/src/ccsync_companion/release_pubkey.py` (the field only trusts keys inside the binary it is already running)
- **Scenario:** the release key file is lost or the owner rotates. `release_key.py new`, `release_key.py bake` (without `--add`), ship. Everything passes: the new build trusts the new key, the record verifies, the dashboard accepts the publish.
- **Today:** verified - every companion in the field refuses the offer ("release signature rejected"), logged once per version, tray silent. There is no recovery over the air at all: every machine needs a hands-on reinstall. The one guard that exists compares the key against the artefact it just built, which is the one place the two can never disagree.
- **Proposed:** record the baked pubkey ids in the release manifest (`release.ps1` step 4 already writes provenance) and in `companion_packages` when published; then `ship`/`publish_latest` refuse when the signing key's id is not in the baked list of the build that is currently CURRENT for that platform, unless `-AllowKeyRotation` is passed, and the refusal spells out "every machine on 0.9.54 will refuse this build". Cheap complement: have the companion report the pubkey ids it trusts, so the Packages page can say "12 of 12 machines trust key a1b2…".
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** COMMERCIAL_READINESS item 4, docs/RELEASE.md "key rotation"

### REL-8: a machine that cannot take a build retries forever, and nobody is told
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/app.py:4672-4693` (auto), `:4768-4791` (pushed), `app.py:185-186` (`PUSHED_UPDATE_FAILED_RETRY_SECONDS = 600`), `dashboard/src/ccsync_dashboard/api.py:5502-5519` (the request rides every report until the version changes; no expiry, no attempt count)
- **Scenario:** an editor's AV quarantines every `ccsync-companion.new.exe`, or a captive-portal proxy mangles the download so the sha never matches, or the exe dir is on a full disk.
- **Today:** verified - `_run_auto_update` / `_run_pushed_update` re-arm on a flat 600 s timer with no attempt cap and no persistence, so the machine downloads ~20 MB every ten minutes indefinitely (≈2.9 GB/day off the NAS, over a possibly relayed tailnet link) and rolls back each time. The report payload carries nothing about upgrade outcomes, so the dashboard cannot distinguish "hasn't seen the push yet" from "has failed 140 times"; the admin's push shows as pending forever.
- **Proposed:** exponential back-off with a cap (10 min -> 1 h -> 6 h) and an attempt counter persisted under `~/.ccsync/state/upgrade_attempts.json` so a restart does not reset it; after N failures stop trying and raise a tray line. Add an `upgrade` block to the report (`{version, attempts, last_error, last_attempt_at}`) and show it on the Fleet page and beside the pushed request; expire a `machine_update_request` after M days with the reason recorded.
- **Effort:** M   **Severity:** med   **Confidence:** high
- **Related:** CR-41 (the latch-once bug these constants came from), CR-52

### REL-9: the stale-update-flag heal keys on a pid, and container pids repeat
- **Lens:** pitfall
- **Where:** `dashboard/src/ccsync_dashboard/dashboard_update.py:363-378` (`if owner == os.getpid(): return state`), `deploy/run.sh:380-386` (uvicorn is a *child* of the pid-1 shell, so its pid is small and deterministic)
- **Scenario:** the NAS loses power while an apply is downloading. `update_state.json` keeps `in_progress: true, owner_pid: 7`. The container comes back; run.sh is pid 1 and starts uvicorn, which is pid 7 again.
- **Today:** verified by reading - the heal treats `owner_pid == os.getpid()` as "the worker is alive", so on a pid collision the dead latch survives and every apply AND every rollback answers 409 forever. On the appliance shape the admin has no shell to delete the file with - which is the exact failure dash-release-ai-2 was written to end.
- **Proposed:** stamp a per-process nonce as well as the pid - `uuid4()` generated at import, or the process start time from `/proc/self/stat` field 22 - and treat a state file whose nonce differs as interrupted. Two lines, and it makes the guard actually mean "this process".
- **Effort:** S   **Severity:** med   **Confidence:** med
- **Related:** dash-release-ai-2 / CR-52

### REL-10: rolling the dashboard's code back leaves the database migrated forward
- **Lens:** pitfall
- **Where:** `dashboard/src/ccsync_dashboard/dashboard_update.py:1003-1013` (`restore_db` is opt-in and separate, deliberately), `:963-976` (the apply migrates only COPIES; the live DBs are migrated by the new code on its first boot)
- **Scenario:** 0.7.20 applies, migrates `dashboard.db` to v30, misbehaves; the admin clicks Rollback with no `restore_db` (the safe-looking choice - it does not throw away today's reports).
- **Today:** verified - the code goes back to 0.7.19 against a v30 database. Forward-only additive migrations survive that; a rename or a NOT NULL column does not, and nothing checks. The rollback UI offers no statement about it.
- **Proposed:** record the live `user_version` of each database in `current.json` at apply time and the schema version each tree was built for in `manifest.json`; on rollback, if the live schema is above what the target tree knows, refuse without an explicit acknowledgement and name the exact backup directory to restore alongside it ("rolling back to 0.7.19 needs backup 20260828T…-before-0.7.20 - restore it too, or today's reports go back with it").
- **Effort:** M   **Severity:** med   **Confidence:** med
- **Related:** DOCKER.md:233, BACKUP_RESTORE.md

### REL-11: a feed that has been unreachable for weeks is visible on exactly one admin page
- **Lens:** safeguard
- **Where:** `dashboard/src/ccsync_dashboard/release_feed.py:517-527` (`last_error` into `feed_state`), `build_feed_view` is read only by the Packages partial; `health_code_block` (`dashboard_update.py:288`) carries no feed fields
- **Scenario:** a customer's outbound DNS is filtered, or the vendor renames the release tag. Daily checks fail silently for six weeks. Or: the vendor bumps the dependency lock, so every bundle's `runtime_id` diverges from the customer's image and every update lands in `runtime_updates` behind a NAS-UI click nobody makes.
- **Today:** verified - the poller logs a warning and records `last_error`, and that is the end of it. No banner, no health field, no age threshold, and the vendor has no way to see it at all. The site quietly stops receiving fixes, which is indistinguishable from "no fixes were published".
- **Proposed:** put `feed: {last_checked_at, age_days, last_error, records}` into `/api/v1/health`; show a persistent dashboard banner when `age_days > 7` ("no successful update check since 12 Aug - <reason>") and a distinct one when every offered build is a runtime mismatch, naming the exact NAS click `nas_update_hint()` already produces.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** release-pipeline-9 (the `:1` tag), WPK-2

### REL-12: `windows_upgrade.ps1` overwrites the installed exe with no copy of what it replaced
- **Lens:** pitfall
- **Where:** `installer/windows_upgrade.ps1:178` (`Copy-Item -Force` over the live exe), `:418` (the relaunch check warns and stops)
- **Scenario:** the base rig ships; step 3 copies the new exe over `%LOCALAPPDATA%\ccsync\bin`; the new build exits within `$RelaunchConfirmSeconds`. Or the copy itself is interrupted (power, AV kill) and leaves a truncated exe.
- **Today:** verified - the script prints a good, blunt warning ("this machine has NO companion running… nothing will retry before the next logon") and leaves the machine there. There is no `.old` on this path, unlike the self-upgrade path, so there is nothing to restore even by hand short of re-running the installer with an older package.
- **Proposed:** rename the existing exe to `<exe>.prev` instead of overwriting it (same volume, same trick the self-upgrade uses), and on the relaunch-failed branch restore it, relaunch it, and say "the new build would not start - this machine is back on v0.9.54". Keep `.prev` until the next successful upgrade.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** SHIP-2, `upgrade._rollback`

### REL-13: "+dirty" dies at the publish boundary - the fleet cannot tell a hotfix from a build
- **Lens:** user-error
- **Where:** `tools/release.ps1:544-545` (`$VersionStamp = "$Version+dirty"` goes to the MANIFEST), `installer/build_editor_package.ps1:780` (the publish sends `--version $version`, the clean number), `db.insert_companion_package` (no provenance column)
- **Scenario:** a deliberate hotfix: `ship.cmd -AllowDirty`. The build is published as 0.9.55 and made current.
- **Today:** verified - the dashboard, the Packages page, every report and every drift check see "0.9.55" with nothing to say it came from uncommitted code. Worse, the real committed 0.9.55 can then never be published (same version, different bytes -> 409), so the fleet's 0.9.55 corresponds to no commit in the repo, permanently.
- **Proposed:** carry `git_dirty` and the short git sha into `companion_packages` (advisory columns filled by the publish tool, no signature change needed) and render them on Packages and in the drift check as "0.9.55 (+dirty, no commit)"; and have `-AllowDirty` publish under a distinguishable version (`0.9.55-dirty1`) or refuse `-MakeCurrent` without a second explicit flag.
- **Effort:** M   **Severity:** med   **Confidence:** high
- **Related:** docs/RELEASE.md, OPS-1

### REL-14: `publish_latest` asks a possibly-stale local ref whether a commit is on main
- **Lens:** pitfall
- **Where:** `tools/publish_latest.py:173-182` (`git merge-base --is-ancestor <sha> origin/main`, no fetch), `:160-169` (`gh run list --branch main`)
- **Scenario:** a commit is pushed to main, CI goes green, then the commit is force-pushed away (a bad merge undone). The operator's rig has not fetched since.
- **Today:** verified - `commit_is_on_main` compares against whatever `origin/main` this working copy last saw, so the check passes and the rig signs a build the release branch no longer contains. The guard's own docstring says the branch label is "a claim a force-push can make untrue" - the local ref can be untrue the same way.
- **Proposed:** `git fetch origin main` (or `git ls-remote origin main` + a refusal when the local ref is behind) before the ancestry test, and print the remote head sha in the summary so the operator sees what was compared.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** release-pipeline-7

### REL-15: ship publishes the companion and the installer as two independent acts
- **Lens:** pitfall / user-error
- **Where:** `installer/build_editor_package.ps1:780` (companion PUT `make_current`) then `:904` (onboard PUT `make_current`), `tools/ship.ps1:600-610`
- **Scenario:** the network drops, or the operator hits Ctrl-C, between the two PUTs - or the second 409s on an unbumped installer version (the step-0 probe catches the common case, but not a race with another ship).
- **Today:** verified - the companion is already CURRENT for the whole fleet while the installer channel still serves an onboard.exe that bundles the previous companion, so every fresh install lands one version behind and immediately self-upgrades. Nothing records how far the ship got; the operator's only recovery is to read the script and re-run the right half.
- **Proposed:** a ship journal (`tools/.ship-state.json`: step, version, timestamp, what was made current) plus `-Resume`, and publish both artefacts STAGED first, then flip both to current in one final step - two writes that fail together rather than a half-shipped fleet.
- **Effort:** M   **Severity:** med   **Confidence:** med
- **Related:** SHIP-4, OPS-4, R13

### REL-16: the channel has no architecture discriminator - an Intel Mac gets an arm64 binary
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/upgrade.py:370-372` (`platform_key()` -> `macos`), `dashboard/src/ccsync_dashboard/api.py:3793` (`_PACKAGE_PLATFORMS = {"windows", "macos"}`), `tools/release_macos.sh:621-635` (arch is *measured* and put in the manifest, then dropped at publish)
- **Scenario:** a customer (or a future editor) has an Intel MacBook. It reports `platform: macos` and is offered the arm64 build that GitHub's `macos-latest` runner produced.
- **Today:** verified - the record's `platform` is the only discriminator, so the wrong-arch binary is downloaded, verified, renamed over the running companion, fails to exec, and the swap rolls back (the guard works). The machine keeps running but can never update, and with `auto_update` on it retries forever (REL-8). A FRESH Intel install gets a wizard-installed binary that simply does not run.
- **Proposed:** carry the manifest's `arch` into the signed record (via `KIND_EXTRA_FIELDS`, kind-scoped so no v2 prefix), have the companion send `arch` in its report, and make `_upgrade_info` offer nothing rather than a mismatched binary - with the Packages page saying "no macos/x86_64 build published". Cheapest interim: build and publish universal2.
- **Effort:** M   **Severity:** med   **Confidence:** high
- **Related:** X-5 (the same lesson for `platform`), macos-port notes

## Cross-cutting notes
- **Companion lifecycle (another agent):** nothing supervises the tray process on either OS - Windows Run key at logon, macOS LaunchAgent `RunAtLoad` with no `KeepAlive` (`upgrade.py:1078`). Every "the companion is gone" failure in this area, and several outside it, would be a non-event with a keepalive/watchdog. Worth one owner.
- **Dashboard/ops:** compose `restart: unless-stopped` restarts a crashed container but not a wedged one, and there is no healthcheck-driven restart (`compose.appliance.yaml:245` says as much for tailscale). REL-6's loopback probe would also give a real healthcheck something to read.
- **Fleet page:** the report payload has no upgrade-outcome field at all. Several findings here (REL-1's soak gate, REL-3's recall, REL-8's telemetry) want the same small addition - one `upgrade` block in the report - so whoever owns the report schema should land it once.
- **Known-open, not re-reported:** `release-pipeline-8` (every record still carries `min_version = 0.0.0`, so the floor mechanism protects nothing in practice), `release-pipeline-9` (the mutable `:1` image tag), `release-pipeline-2` (two publish paths, unreconciled), WPK-2/3/4/5.
