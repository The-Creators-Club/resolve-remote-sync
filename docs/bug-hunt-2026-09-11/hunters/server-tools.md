# server-tools - NAS-side scripts (server/) and the release tooling (tools/, bench/)

Files read (with approximate coverage):
- `git diff 097f5a3..HEAD -- server/ tools/ bench/` in full (36 files, ~3,700 added lines) - 100%
- `server/broll_drain.py` (both embedded programs, line by line) - 100%
- `server/publish_db.py` drain/swap/rollback path - ~80%; `server/install_dashboard_app.py`
  the new REL-5 / OPS-3 / OPS-9 / datasets code, `install_tree`, `iter_local_files`,
  `upload_tree`, `local_manifest`, `compose_config`/`compose_variables` wiring - ~35% of a
  5,500-line file
- `server/common.py` host-key pinning block (`ssh_client`, `_known_host_key`,
  `_record_host_key`, `_parse_host_key`) - 100%
- `server/backends/truenas.py` `resolve_dataset`/`ensure_snapshot_schedule`/`container_exec`,
  `server/backends/synology.py` `render_env_file`/`install_ssh_key`/`container_exec` - ~25%
- `tools/ship.ps1` (new step 0a gates, rollout tail), `tools/publish_latest.py`,
  `tools/sign_release.py`, `tools/release_key.py`, `tools/check_licenses.py`,
  `tools/run_all_tests.ps1`, `tools/load_secrets.ps1`, `tools/jobs.py`,
  `tools/check_deploy_drift.ps1`, `tools/build_dashboard_bundle.py` - 60-100% each
- cross-checked the other side of three wires: `dashboard/.../api.py::_rollout_block`,
  `db.rollout_status`, `help.py`/`ui.page_help`, `dashboard/deploy/Dockerfile`, `.dockerignore`

Tests run:
- `bash -c "cd server && ../dashboard/.venv/Scripts/python.exe -m pytest tests -q"`
  -> first run **2 failed, 668 passed, 2 skipped** (`test_music_deploy.py`, "internal
  manifest mismatch (297 vs 296)"); second run of the same command
  -> **670 passed, 2 skipped**. See server-tools-4.
- `cd tools; ..\dashboard\.venv\Scripts\python.exe -m pytest tests -q`
  -> **1 failed, 288 passed** (`test_docs_index.py::test_every_doc_is_listed`:
  `docs/STAGE_A_FOLDER.md` is untracked in the working tree and has no row in
  `docs/README.md`. Working-tree state, not a code defect - the gate is doing its job.)
- `cd bench; .venv\Scripts\python.exe -m pytest tests -q` -> **175 passed, 1 skipped**
- `powershell`: verified the `$null -eq @()` semantics behind server-tools-1.

## Findings

### server-tools-1 - `ship.ps1 -EmitKindExtras` fails OPEN when the dashboard reports an empty rollout
- Severity: high
- Confidence: CONFIRMED
- Where: `tools/ship.ps1:540-570` (step 0a), against
  `dashboard/src/ccsync_dashboard/api.py:1499` (`_rollout_block`) and
  `dashboard/src/ccsync_dashboard/db.py:4199` (`rollout_status`)
- What: the gate that is supposed to make `-EmitKindExtras` impossible until the whole
  fleet is on 0.9.55+ treats `"rollout": []` as a valid, empty, all-clear answer. It
  guards with `if ($null -eq $health -or $null -eq $health.rollout)`, and in PowerShell
  `$null -eq @()` is `$false`, so an empty JSON array walks straight past the refusal,
  the `foreach` body never runs, `$stragglers.Count` is 0, and the script prints
  "-EmitKindExtras: every reporting computer is on 0.9.55 or newer" having checked
  nothing. The script's own comment says an unparseable answer must be FALSE - "we could
  not tell is never fine on either of the two gates that read this" - and that is exactly
  the case it lets through.
  A second, narrower hole in the same block: the loop iterates CHANNELS, and
  `db.rollout_status` builds "one channel per (kind, platform) that has a CURRENT build".
  A platform with real machines but no current companion package (a fresh site, or a
  macOS channel nobody has pointed current) contributes no channel, so its machines are
  invisible to the gate even when the array is non-empty.
- Failure scenario: `_rollout_block` wraps `db.rollout_status` in
  `except Exception: log.exception(...); return []`. A dashboard whose `machine_state`
  read raises (locked DB, a column an older schema lacks, the collector mid-migration)
  answers `/api/v1/health` with `rollout: []` and HTTP 200. The operator runs
  `tools\ship.cmd -EmitKindExtras`, is told the fleet is clear, and publishes a record
  carrying the signed `requires_dashboard`/`arch` fields. Every companion below 0.9.55 -
  leso's Mac sat on 0.9.2 for weeks, per the ledger - fails the signature check on the
  whole record and refuses that build permanently. There is no over-the-air recovery;
  the fix is a reinstall at that desk, which is the precise outcome this gate exists to
  prevent.
- Evidence:
  ```
  PS> $h = '{"rollout": [], "version": "0.7.42"}' | ConvertFrom-Json
  isnull: False
  count: 0
  stragglers: 0
  ```
  (`$null -eq $h.rollout` is False for an empty array, True only for a missing property.)
  `api.py:1513-1516` returns `[]` on any exception; `db.py:4252-4256` selects only
  `companion_packages WHERE kind='companion' AND is_current=1`.
- Ledger: new (the gate itself is REL-4, usability sweep 2026-09-04)
- Suggested fix: refuse unless the answer is a non-empty array -
  `if ($null -eq $health -or @($health.rollout).Count -eq 0) { <the existing refusal> }` -
  and have `_rollout_block` distinguish "computed, nothing current" from "could not
  compute" (e.g. return `null` on the exception path) so the ship can tell the two apart.

### server-tools-2 - every customer's dashboard ships and serves this studio's entire internal docs tree
- Severity: high
- Confidence: CONFIRMED
- Where: `tools/build_dashboard_bundle.py:89-110` (`TREES` gains `("docs","docs")`,
  `ROOT_DOCS`), `server/install_dashboard_app.py:300-311` + `:3940-3975`
  (`SHIPPED_ROOT_DOCS`, `_stage_docs_tree`), `dashboard/deploy/Dockerfile:110,118`
  (`COPY docs /app/docs`, `COPY *.md /app/docs/_root/`); read back by
  `dashboard/src/ccsync_dashboard/help.py` via `ui.py:4144` (`page_help`), which is
  explicitly "Not admin-only" (`ui.py:189`).
- What: REL-5 needed two documents on the server (the EULA and HOW_IT_WORKS.md). All
  three shipping routes now carry **every `.md` under `docs/` plus the repo's top-level
  documents**, and `help.resolve_document` has no allowlist - its only checks are ".md,
  inside the root, no `..`, no symlink out". So any logged-in EDITOR at any site can
  browse the whole tree at `/help/<path>`.
- Failure scenario: a second customer's editor opens `/help`, and the index lists
  `KNOWN_BUGS.md` (16k lines of this fleet's incidents), `CLAUDE.md`, `SECRETS.md`,
  `TENANCY.md`, `COMMERCIAL_READINESS.md`, `PRODUCT_REPO.md`, every bug-hunt and sweep
  report, and the hunter reports under `docs/bug-hunt-2026-09-03/`. Those name this
  studio's editors, their machines, and infrastructure addresses.
- Evidence:
  ```
  $ find docs -name '*.md' | wc -l          -> 124   (4,136,063 bytes)
  $ grep -rln "ruskin|leso@|100.66.62.41|100.65.15.123|192.168.0.104" docs --include=*.md
    docs/bug-hunt-2026-08-14.md, docs/bug-hunt-2026-08-21.md,
    docs/bug-hunt-2026-09-03/hunters/dash-collector.md,
    docs/bug-hunt-2026-09-03/verifiers/dashboard-b.md, docs/COMMERCIAL_READINESS.md,
    docs/macos-first-run-2026-08-04.md, docs/MULTI_BASE_RIG_PLAN.md,
    docs/MULTI_MACHINE_PLAN.md, docs/PRODUCT_REPO.md, docs/RELEASE.md,
    docs/resilience-sweep-2026-08-28/APP.md, docs/resilience-sweep-2026-08-28/DASH.md,
    docs/spikes/..., docs/synology-spikes-2026-08-17.md,
    docs/TIMELINE-CARDS-INTO-CCSYNC.md, docs/usability-resilience-sweep-2026-09-03/REL.md
  ```
  No credential value is in there (I grepped for the known passphrase and found none), so
  this is disclosure of operational and customer-identifying detail, not of a secret.
  This is also the letter of CLAUDE.md's "No customer's name in code" broken by the
  shipping change rather than by the code.
  Secondary: the three routes disagree about WHICH root documents travel. Bundle and
  bind modes ship the four names in `ROOT_DOCS`/`SHIPPED_ROOT_DOCS`; the image uses
  `COPY *.md /app/docs/_root/`, so any future top-level `.md` is published to every
  customer automatically and silently.
- Ledger: new (the widening is "Alex, 2026-09-04" in the code comments - the owner asked
  to READ every document, which is a base-rig/dev need, not necessarily a customer-facing
  one)
- Suggested fix: ship a published SUBSET (a `docs/published/` tree, or a front-matter or
  manifest allowlist), and make everything outside it visible only on a dev checkout;
  replace the Dockerfile's `COPY *.md` glob with the four explicit names so the three
  routes cannot drift.

### server-tools-3 - the OPS-3 `.zfs/snapshot` bind mount will very likely show the container empty snapshots
- Severity: medium
- Confidence: PLAUSIBLE (cannot be verified from here - it needs the NAS)
- Where: `server/install_dashboard_app.py:715-760` (`snapshot_source`) and `:762-770`
  (`snapshot_volumes` -> `f"{host}:{SNAPSHOT_MOUNT}:ro"`)
- What: `<mountpoint>/.zfs/snapshot` is ZFS's control directory: listing it shows the
  snapshot names, but each name is an AUTOMOUNT that the kernel performs in the host
  mount namespace when the directory is first traversed, and that unmounts again after
  inactivity. A docker bind mount is `rprivate` by default, so mounts that appear under
  the source AFTER the container started do not propagate into it. `snapshot_volumes`
  passes only `:ro` - no `rshared`/`rslave` and no propagation setting anywhere in the
  compose body.
- Failure scenario: the RECOVERY page lists every snapshot (the ctldir listing itself is
  visible) and then shows each one as containing nothing, or restores zero files from it.
  That is a "green while dead" shape: the page stops saying "this deployment was never
  given a snapshot mount" - the honest state the code went to some trouble to produce -
  and starts offering a restore that silently has no content. It would also work
  intermittently, because a snapshot already automounted when the container started IS
  visible, which is the worst possible failure mode for an operator mid-incident.
- Evidence: read `snapshot_volumes` and the whole `volumes:` list in `compose_config` -
  no `bind` propagation option is emitted for any mount; `remote_dir_exists` only
  `test -d`s the ctldir itself, which succeeds whether or not any snapshot is mounted.
  `server/tests/test_snapshot_mount.py` asserts the string that is emitted, not what the
  container can read through it, so no test would catch this.
- Ledger: new (OPS-3, usability sweep 2026-09-03)
- Suggested fix: verify on the live NAS by `docker exec`ing an `ls /snapshots/<name>/` on
  a snapshot nobody has touched for an hour. If it is empty, either mount the automount
  root with `bind-propagation: rslave` (which compose supports only in the long-form
  volume syntax) or have the recovery page read snapshots over SSH instead of a mount.

### server-tools-4 - `install_tree` re-walks the source tree after the upload, so a file that moves under it aborts a finished transfer
- Severity: low
- Confidence: CONFIRMED (the mechanism); the trigger for the observed flake is not
  identified
- Where: `server/install_dashboard_app.py:4021-4022` and `:4053-4055`
- What: `expected = upload_tree(...)` walks `iter_local_files(source, excludes)` and
  SFTPs it; `expected_count, expected_bytes = local_manifest(source, excludes)` then
  walks the same tree AGAIN, afterwards, and `expected != expected_count` is a hard
  FAILED. The two walks are independent snapshots of a live directory, and the byte total
  used for the staged-tree verification comes from the SECOND one - i.e. the deploy
  verifies the uploaded copy against a manifest of a tree it did not upload.
- Failure scenario: anything that creates or removes a non-`.pyc` file under
  `dashboard/` (or `broll/web`, `music/web`, `ytdl/web`) while a deploy is uploading -
  an editor saving, a stray tool, a build - either aborts the deploy after the whole SFTP
  with "internal manifest mismatch", or shifts `expected_bytes` so the staged-tree check
  fails instead. Both refusals are in the safe direction (nothing is swapped), so this is
  a wasted transfer and a confusing message rather than damage.
- Evidence: first full run of `server/tests` at HEAD:
  `FAILED tests/test_music_deploy.py::test_a_deploy_ships_the_music_tree_and_prepares_every_host_dir`
  and `..._music_data_none_pushes_no_data_but_still_ships_the_code`, both with
  `FAILED: internal manifest mismatch (297 vs 296)` after
  `[dry-run] would SFTP 297 files from E:\...\dashboard`. Re-running
  `tests/test_music_deploy.py` alone: 65 passed. Re-running the whole suite: 670 passed.
  So the suite is flaky here, and the flake is exactly the production race.
- Ledger: new
- Suggested fix: have `upload_tree` return the `(count, bytes)` of the list it actually
  sent and use that one snapshot for both the internal check and the staged-tree compare;
  keep the mismatch test as an assertion on one list, not a comparison of two walks.

### server-tools-5 - `tools/jobs.py` and `tools/publish_package.py` turn an unreachable dashboard into a traceback
- Severity: low
- Confidence: CONFIRMED
- Where: `tools/jobs.py:110-121` (`Http.send`), same shape in
  `tools/publish_package.py`
- What: `send` catches `urllib.error.HTTPError` only. `URLError` (connection refused, DNS
  failure, TLS failure) and `socket.timeout` are not caught, and `main()`'s handler only
  catches `JobsError`, so they escape as an unhandled traceback.
- Failure scenario: the operator runs `python tools/jobs.py queue` while the NAS is
  rebooting, or `ship.cmd` runs `publish_package.py` against a dashboard that is
  restarting mid-deploy, and gets a urllib stack trace instead of "could not reach the
  dashboard at <url>". Every other failure in these two scripts is a sentence naming the
  next action; this one, the commonest, is not.
- Evidence: `grep -c URLError tools/*.py` -> only `check_mobile_origin.py` handles it;
  `jobs.py` and `publish_package.py` are 0.
- Ledger: new
- Suggested fix: catch `urllib.error.URLError` and `OSError` in `Http.send` (or around
  the call in `main`) and raise `JobsError(f"could not reach {url}: {exc.reason}",
  EXIT_CALL)`.

### server-tools-6 - `check_deploy_drift.ps1 -Watch` retries an expired session for ever
- Severity: low
- Confidence: CONFIRMED
- Where: `tools/check_deploy_drift.ps1:742-780`
- What: the watch loop catches every exception from the admin `packages` GET, prints
  "packages query failed", sleeps 60 s and continues, with no ceiling and no distinction
  between a dashboard restarting (the case it was written for) and a session cookie that
  has expired or been invalidated - which is guaranteed to happen on a long rollout,
  because the session was minted once before the report.
- Failure scenario: an operator leaves `-Watch` running over a slow rollout; the session
  expires; the tool prints the same failure line once a minute for ever and never says
  "your admin session expired, re-run", and never reaches the completion line it exists
  to print.
- Evidence: read the loop - the only `break`s are "no rollout numbers" and
  `Test-RolloutComplete`.
- Ledger: new (REL-6, usability sweep 2026-09-04)
- Suggested fix: count consecutive failures, and on (say) the fifth, or on an HTTP
  401/403 specifically, stop with "the admin session expired - re-run with -AdminUser".

## Coverage note

What I did not get to:
- `setup_editor_account.py` and `setup_syncthing_folder.py` idempotency (unchanged since
  097f5a3, so they were deprioritised under the brief's "new code is where the bugs are")
- the bulk of `install_dashboard_app.py` outside the diff: the stage-verify-swap script
  builders, `snapshot_before()` call sites, the env-file secret handling, the Synology
  backend's compose path. I read `render_env_file`'s new single-quoting (it looks right:
  compose-go treats single quotes as literal, and the `$` check is correctly retired
  because of it) but did not audit every value that reaches it.
- `publish_feed.py`, `publish_package.py` and the CR-52 `min_version` refusal beyond a
  skim; `release_macos.sh` / `build_onboard_macos.sh` diffs; `tools/gen_icons.py` and
  `make_icons.js`; `bench/` source (the suite passes and it is ad hoc tooling).

Things I checked and found SOUND, recorded so nobody re-treads them:
- `common.ssh_client` host-key pinning: a changed key is a `BadHostKeyException` refusal
  with both fingerprints and no re-trust; an unknown host with no pin and no TOFU flag is
  a refusal; a corrupt known_hosts is a refusal, not a crash; a server offering a key type
  we have not recorded hits `RejectPolicy`, which also refuses.
- `broll_drain.py`: the export's `ingest_schema` gate covers `share_roots.collection`
  too (both arrive in migration 011, so no half-migrated live DB can crash the export),
  `embeddings.source` really is only `'segment' | 'transcript'`, the apply is idempotent
  by construction, and `container_exec` propagates the container's exit code so
  `RC_NO_LIVE=3` is distinguishable from a real failure. `take_drain`'s three-way answer
  is correct.
- `check_licenses.py --strict`: an unknown or empty `License` string is `UNKNOWN`, which
  with no applicable allowlist entry is a FAIL; the copyleft path FAILs on a missing
  allowlist entry and on an entry with no `reason`. The `Target.names` accumulation bug
  from the last hunt is genuinely fixed (it is a local now).
- `run_all_tests.ps1`: the exit code is the count of rows whose outcome is not `PASS*`, so
  a SKIP counts as a failure; all seven installer scripts are collected; the server suite
  really does go through Git's own bash.
- `publish_latest.py`: `version_tuple` handles two-digit minors (0.10.0 > 0.9.70), the
  dashboard channel is looked up as `("dashboard","linux")` which is what
  `build_dashboard_bundle.py` prints, and `merge-base --is-ancestor` fails closed on an
  unknown sha.
- `load_secrets.ps1` no longer materialises the plaintext (the BSTR round trip is gone).
- No `.sh` in this territory is CRLF in the index; `help.render_markdown` normalises
  `\r\n`, so the CRLF markdown a Windows bind-mode deploy uploads renders correctly.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/api.py:1513` (`_rollout_block`): returns `[]` both for
  "nothing is current" and for "the computation raised". Two different facts with one
  wire representation, and `tools/ship.ps1` cannot tell them apart (see server-tools-1).
- `dashboard/src/ccsync_dashboard/help.py` / `ui.py:4144`: `/help/{doc_path}` is behind
  the login gate but is not admin-only, and there is no allowlist of which shipped
  documents may be served (see server-tools-2).
- `docs/STAGE_A_FOLDER.md` is untracked and has no row in `docs/README.md`, which fails
  `tools/tests/test_docs_index.py` on the current working tree.
