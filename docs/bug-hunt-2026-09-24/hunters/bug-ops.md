# bug-ops - server scripts, installers, onboarding, release/ship tools, deploy, bench (Wave 1: bugs)
Files read (approximate coverage): server/publish_db.py (all), server/install_dashboard_app.py (build_db_swap_script, sidecar constants), server/common.py (ssh_client / host-key pinning, validate_slug), server/setup_editor_account.py (username validation), tools/publish_latest.py (all), tools/publish_feed.py (main, retract, fetch, upload, asset plan), tools/sign_release.py (version_tuple), tools/ship.ps1 (preflight, journal, step 2b), tools/jobs.py (client, cancel/watch), tools/check_licenses.py (head), dashboard/deploy/select_code_root.py (all), dashboard/deploy/run.sh (first 140 lines), onboarding/steps.py (config merge, dashboard URL helpers), installer/windows_upgrade.ps1 (EULA version compare), installer/build_editor_package.ps1 (min_version compare), installer/windows_uninstall.ps1 + macos_uninstall.sh (profile deletion), bench/ccbench/guard.py.
Tests/probes run: ad-hoc snippets from the dashboard venv - `publish_db.newest_prev` fed a realistic `find` listing that includes the moved `-wal`/`-shm` sidecars; `publish_feed.parse_args` fed the recall command publish_latest.py prints.

## Findings

### bug-ops-1 - `publish_db.py --rollback` picks the `.prev-<ts>-wal` sidecar and renames it over the live index
- Severity: high
- Confidence: CONFIRMED
- Where: server/publish_db.py:556 (list_prev_command) and server/publish_db.py:578 (newest_prev); consumer build_rollback_script at :501
- What: the publish moves the live file's `-wal`/`-shm` along with it, to `<target>.prev-<ts>-wal` / `-shm` (SERVER-7, build_db_swap_script). The listing is `find -name 'broll.db.prev-*'`, which matches those sidecars too. `newest_prev` sorts by name and takes the last one, and `...T101500` < `...T101500-shm` < `...T101500-wal`. So when the swapped-out index had a WAL beside it (the normal case, because the container holds it open in WAL mode), the "newest prev" is the `-wal` file.
- Failure scenario: after a bad publish the operator runs the documented first-line recovery, `python publish_db.py --which broll --rollback --apply` (docs/BACKUP_RESTORE.md 4d). The script moves the live broll.db aside and runs `mv broll.db.prev-<ts>-wal broll.db`, which installs a WAL journal as the database. It then prints "rolled back ... restored from ...-wal", and /broll (or /music) is serving a file that is not a database. The real `.prev-<ts>` is still sitting there unused.
- Evidence: probe with `ida.run_ssh` stubbed to return `/d/broll.db.prev-20260821T101500`, `...-shm` and `...-wal` returned `('/d/broll.db.prev-20260821T101500-wal', '')`. test_backup_restore.py:506 itself asserts that `broll.db.prev-20260817T120000-wal` exists after a publish. The only test of newest_prev (test_bug_hunt_2026_08_21.py:68) lists bare `.prev-<ts>` names and nothing else, so it would not catch this.
- Ledger: new (related to server-1 / SERVER-7, which introduced the listing and the sidecar move)
- Suggested fix: filter the listing to names that exactly match `<filename>.prev-<digits>T<digits>` (a regex in Python, or `! -name '*-wal' ! -name '*-shm'` in find) before sorting. Also make `--from-prev` refuse a path that ends in a sidecar suffix.

### bug-ops-2 - `ship.cmd -Resume` cannot resume anything past the publish, and tells the operator to bump the version
- Severity: medium
- Confidence: CONFIRMED
- Where: tools/ship.ps1:423-472 (the "already published" fail-fast); tools/ship.ps1:925 (the advice to re-run with -Resume)
- What: the step-0 check asks the dashboard whether companion v$CompanionVersion (and installer v$InstallerVersion) are already published, and it `exit 1`s if so. It runs whether or not `-Resume` is set, and before any `Test-StepDone` gate. After the journal has recorded `publish` or `current`, both versions are published by definition.
- Failure scenario: step 2b returns 3 (the dashboard refuses the make-current until the build has soaked), and ship.ps1 prints "re-run: tools\ship.cmd -Resume". Following that advice fails at step 0 with "companion vX is ALREADY published on the server. bump VERSION ...". The same happens after a failed local upgrade (journal step `current`). So REL-15's resume path never works for the states it was written for, and the refusal sends a non-technical owner to cut a new version of a build that is already published and staged.
- Evidence: read of ship.ps1. `$script:ResumeFrom` is set at :411, and nothing between :419 and :472 reads it. Step 2b is the only step that checks `Test-StepDone "current"`.
- Ledger: related to REL-15 (FIXED in repo 2026-08-28). The fix is incomplete, not regressed.
- Suggested fix: skip both published-version probes when `Test-StepDone "build"` is true for this version, or accept "published" as the expected answer when the journal says `publish`/`current`.

### bug-ops-3 - The recall command publish_latest.py prints at the moment of release does not parse
- Severity: medium
- Confidence: CONFIRMED
- Where: tools/publish_latest.py:495-497; argument definition at tools/publish_feed.py:1010 and parse at :1147
- What: the summary prints `python tools\publish_feed.py --retract --kind <kind> --platform <platform> --version <version> --reason "..." --github-upload`. But `--retract` takes a single `KIND/PLATFORM/VERSION` value, and the command also leaves out `--feed-dir` and `--github-repo`, which publish_feed requires before it will upload.
- Failure scenario: an operator who has just learned a build is bad copies the printed line (REL-9 put it there for exactly that moment). argparse exits with `argument --retract: expected one argument`. Even with the value shape fixed, the run stops on `--feed-dir is required` and then on `--github-upload needs --github-repo`. Meanwhile the bad build stays CURRENT on the vendor feed while the operator works out the right syntax.
- Evidence: `publish_feed.parse_args(['--retract','--kind','companion',...])` raised SystemExit 2 with "argument --retract: expected one argument".
- Ledger: new
- Suggested fix: print `python tools\publish_feed.py --retract <kind>/<platform>/<version> --reason "..." --feed-dir <FEED_DIR> --github-repo <FEED_REPO> --github-upload`, filled in with the kind, platform and version just published and the script's own FEED_DIR/FEED_REPO. Add a test that parses the printed line.

### bug-ops-4 - The macOS `--full` uninstall reports the sign-in as removed without checking
- Severity: low
- Confidence: CONFIRMED
- Where: installer/macos_uninstall.sh:273-287
- What: the loop increments `removed` whether or not `rm -rf "$item"` succeeded, then prints "removed your sign-in and settings ... including config.toml, identity.json". install-onboard-3 (2026-09-18b) fixed the same defect on Windows by re-listing the directory afterwards (windows_uninstall.ps1:742-760). The Mac half was not changed.
- Failure scenario: a root-owned config.toml (left by a sudo'd bootstrap run) or a file the volume refuses to delete survives. It holds the per-editor `cce1.` fleet credential and dashboard_token. The editor hands the Mac on believing the sign-in is gone, but it is still there and still works.
- Evidence: read of both uninstallers side by side. The Mac file even has the helper that does the check (`rm -rf ... || warn` at :195-197), but this loop does not use it.
- Ledger: related to install-onboard-3 (fixed on Windows only)
- Suggested fix: after the loop, re-list `$CCSYNC_PROFILE` excluding `state`, and report any survivors the way the Windows side and the `BIN_DIR` block at :231 do.

## Coverage note
Not reached: most of install_dashboard_app.py (6k lines: deploy swap, compose rendering, OTA staging), backends/truenas.py and synology.py, setup_syncthing_folder.py, setup_tree.py, check_health.py, accept_device.py, the bulk of windows_bootstrap.ps1 / macos_bootstrap.sh / onboard.py, release.ps1, release_macos.sh, build_onboard_macos.sh, sign_windows_binary.ps1, check_deploy_drift.ps1, and bench beyond guard.py. Two things were looked at and not reported:
- publish_feed.fetch_published_channel treats any "not found" in gh's output as a first publish. That covers a 404 from a token without repo access, but the later `release view`/`create` fails in that case, so nothing is clobbered.
- bench guard.is_scratch_path accepts any path with a `_bench` component even when it is followed by `..`. That needs a malformed bench.toml, so it is not a realistic defect.

## OUT OF TERRITORY
- none recorded
