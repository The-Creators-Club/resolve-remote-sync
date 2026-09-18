# server-tools - server/*.py, tools/* (minus the four feed tools), bench/

Files read (with approximate coverage):
- `git diff 34a3c8f..HEAD -- server/ tools/ bench/` (full; only
  `server/install_dashboard_app.py` + `tools/license_allowlist.toml` are mine
  in it) and `git diff 18e69f3..34a3c8f -- server/ tools/ bench/` (full:
  `install_dashboard_app.py` +189, `check_deploy_drift.ps1`,
  `run_all_tests.ps1`, `ship_gates.ps1`).
- `server/publish_db.py` (100%), `server/broll_drain.py` (100%),
  `server/check_health.py` (~60%, the tailscale + dashboard halves),
  `server/common.py` (~35%: host-key pinning, `ssh_client`, `snapshot_before`,
  `cli`), `server/install_dashboard_app.py` (~20%: docs shipping, cards
  snapshot, snapshot volumes, `git_out`, `install_tree` header).
- `tools/run_all_tests.ps1` (100%), `tools/ship_gates.ps1` (100%),
  `tools/check_deploy_drift.ps1` (~40%, the cards block), `tools/jobs.py`
  (~80%), `tools/gen_notices.py` (~50%), `tools/check_licenses.py` (targets
  and allowlist plumbing only), `tools/build_dashboard_bundle.py` (~40%),
  `tools/publish_package.py` (~30%), `tools/release.ps1` / `tools/ship.ps1`
  (version-compare and parity blocks only).
- `bench/ccbench/runners/{base,_rclone_common}.py` (subprocess layer only).
- Cross-checked: `dashboard/src/ccsync_dashboard/published_docs.py`,
  `api.py` jobs routes, `db.request_job_cancel`, `broll/web/migrations/012_geometry.sql`,
  `docs/legal/THIRD_PARTY_NOTICES.md`, `.github/workflows/ci.yml`.

Tests run:
- `cd server; ../dashboard/.venv/Scripts/python.exe -m pytest tests -q` (from
  Git Bash, per CLAUDE.md) -> **706 passed, 2 skipped**.
- `cd tools; ../dashboard/.venv/Scripts/python.exe -m pytest tests -q` ->
  **328 passed**.

## Findings

### server-tools-1 - an LGPL dependency shipped to customers has no notice, and the generator that would catch it is in no gate
- Severity: medium
- Confidence: CONFIRMED
- Where: `tools/license_allowlist.toml:52-79` (the new `[allow.psycopg2-binary]`
  entry), `tools/gen_notices.py:49-70` (`COMPONENTS`), `docs/legal/THIRD_PARTY_NOTICES.md`
  (no psycopg2 row), `.github/workflows/ci.yml` (no `gen_notices` step)
- What: the allowlist entry added this week excuses psycopg2-binary (LGPL) for
  the `dashboard-container` target, and its own `reason` text asserts that the
  remaining obligations are "tracked in docs/legal/THIRD_PARTY_NOTICES.md: the
  notice, the licence text, and a written offer". They are not: that file has
  never been regenerated since the package landed, it carries no psycopg2 row
  in any of its five tables, and `tools/gen_notices.py --check` - which
  `KNOWN_BUGS.md:499` (CR-5) describes as "a CI gate" - is referenced by no
  workflow, no `ship.ps1`/`ship_gates.ps1` step and no test. So the ONE gate
  that does run (`check_licenses.py --strict`) passes precisely because a human
  wrote a promise into a TOML file, and nothing checks the promise.
- Failure scenario: a customer receives the dashboard image (which installs
  `dashboard/deploy/requirements.lock`, containing `psycopg2-binary==2.9.12`),
  asks for the third-party notices, and is handed a document that does not
  mention the LGPL component they were conveyed, with no licence text and no
  written offer for its source. Every future addition to
  `dashboard/deploy/requirements.lock` lands the same way, silently.
- Evidence:
  - `grep -n "psycopg2" dashboard/deploy/requirements.lock` -> `psycopg2-binary==2.9.12`;
    `dashboard/requirements.lock` -> `2.9.13`; `dashboard/.venv/Lib/site-packages/psycopg2_binary-2.9.13.dist-info` exists.
  - `grep -n "psycopg2" docs/legal/THIRD_PARTY_NOTICES.md` -> no match; its LGPL
    rows are still only `paramiko`, `pystray`, `bgutil-ytdlp-pot-provider`, `pyinstaller*`.
  - `git log -1 -- docs/legal/THIRD_PARTY_NOTICES.md` -> `18e69f3` (2026-09-11),
    i.e. it predates nothing relevant but has not been regenerated since
    psycopg2 entered the locks (2026-08-31).
  - `grep -rn "gen_notices" .github/workflows/ tools/ship.ps1 tools/ship_gates.ps1 tools/release.ps1`
    -> no match. `check_licenses` is in ci.yml four times; `gen_notices` zero.
  - Secondary: `gen_notices.py` inventories the five component **venvs**, never
    `dashboard/deploy/requirements.lock`, so even a regeneration would print the
    dev venv's 2.9.13 rather than the 2.9.12 actually conveyed - the file's own
    `TODO(legal)` header admits this ("the tables below are the venvs, not the
    shipped artefacts").
- Ledger: new (CR-5 says `--check` is a CI gate; it is not - so this is also
  "CR-5's ledger text does not match the tree")
- Suggested fix: add `python tools/gen_notices.py --check` to `ci.yml` beside
  the `check_licenses.py --strict` steps, regenerate the file, and either add
  `dashboard/deploy` as a `COMPONENTS` entry (scanned from the lock rather than
  a venv) or state in the header that the container lock is audited only by
  `check_licenses.py`.

### server-tools-2 - a b-roll publish whose drain merge fails still exits 0, and a test pins that
- Severity: medium
- Confidence: CONFIRMED
- Where: `server/publish_db.py:843-857` (the post-swap `apply_drain` branch),
  `server/tests/test_broll_drain.py:426-440` (`assert rc == 0`)
- What: the drain's second half runs AFTER the rename. When it fails
  (`database is locked`, the container restarting, the merge raising), the code
  prints a WARNING naming the bundle and the recovery command - and then falls
  through to `return 0`. The process exit status says the publish succeeded
  while the live index is missing every clip the fleet ingested since the
  source copy was pulled, plus every `ingest_batches`/`ingest_items` row (the
  file is the only place those exist - `broll_drain.py:13-17`).
- Failure scenario: `python publish_db.py --which broll --apply` is run from a
  script, a scheduled task, or any `&&` chain; the container is mid-restart so
  the merge answers rc 5. The command exits 0, the caller proceeds, and the
  b-roll search UI is live and short 12 fleet-ingested clips with two ingest
  batches showing no progress. Nobody learns unless a human happened to be
  reading stderr in that terminal.
- Evidence: `server/tests/test_broll_drain.py:426-440`
  (`test_a_merge_that_fails_after_the_swap_names_the_bundle_and_the_command`)
  feeds a `(5, '{"error": "OperationalError: database is locked"}', "")` exec
  result and asserts `rc == 0` alongside the stderr text - so the suite would
  not fail if the exit code were corrected, and it actively pins the lie.
  Contrast `do_apply_drain` (`publish_db.py:625-631`), which returns 1 for the
  very same failure when it is the whole command.
- Ledger: new (related to BROLL-1, 2026-09-04)
- Suggested fix: return a distinct non-zero code (the swap succeeded, so not 1 -
  e.g. a new `RC_DRAIN_UNMERGED`) from that branch, keep the WARNING text
  verbatim, and change the test to assert the new code.

### server-tools-3 - `tailscale status --json` is decoded with the console codec, so a non-ASCII peer name turns a health check into a false "skipped"
- Severity: low
- Confidence: CONFIRMED
- Where: `server/check_health.py:311`
- What: `subprocess.run([exe, "status", "--json"], capture_output=True, text=True)`
  has no `encoding=`, so on Windows Python decodes tailscale's UTF-8 JSON with
  `locale.getencoding()` (cp1252 here, cp950 on a Traditional-Chinese install).
  This is exactly the bug class `e050413` fixed one file over
  (`install_dashboard_app.git_out`, "a commit subject with a Chinese clip name
  took the deploy down", 2026-09-12) - and it was fixed in `git_out` only.
- Failure scenario: a tailnet peer (a machine name, a Mac's `DNSName`) contains
  a non-ASCII character. Either the decode raises `UnicodeDecodeError` inside
  `subprocess.run`, which the broad `except Exception` at line 312 reports as
  "skipped -- `tailscale status --json` failed", or it mis-decodes and the
  peer-hint match fails, giving "NAS peer not found in the local tailnet -- is
  this machine on the same tailnet?". Both are `info()` lines, not failures, so
  check 2b (DERP-vs-direct from this machine, the P14 half that matches what an
  editor experiences) silently stops being performed and the health run still
  exits 0.
- Evidence: read the call site; `text=True` with no `encoding` is
  locale-dependent by definition (CPython `subprocess` docs), and
  `tools/build_dashboard_bundle.py:171` and `install_dashboard_app.py:616` both
  carry `encoding="utf-8", errors="replace"` for the same reason while this one
  does not. `grep -rn "capture_output" server/*.py tools/*.py | grep -v encoding`
  leaves this line, `tools/gen_notices.py:93/98/103` and the bench runners.
- Ledger: new (same class as the `git_out` fix in e050413)
- Suggested fix: `encoding="utf-8", errors="replace"` on this call, and on
  `tools/gen_notices.py`'s three `pip-licenses` invocations.

### server-tools-4 - bench's rclone readback decodes with the console codec and its decode failure is not caught
- Severity: low
- Confidence: PLAUSIBLE (the code path is certain; whether a bench run is ever
  pointed at CJK-named media is not)
- Where: `bench/ccbench/runners/_rclone_common.py:211-219` (`remote_listing`),
  same shape at `bench/ccbench/runners/base.py:138-143` (`run_subprocess`),
  `bench/ccbench/runners/syncthing.py:143`, `iperf3.py:154`
- What: `rclone lsjson -R` emits UTF-8 JSON containing every remote file's
  path. `text=True` with no `encoding` decodes it with the Windows console
  codec. `remote_listing` catches only `TimeoutExpired` and `OSError`, so a
  `UnicodeDecodeError` (raised inside `subprocess.run`) escapes the function
  and the runner entirely, rather than returning the documented `None`.
- Failure scenario: a benchmark run against a tree holding a real project name
  (the fleet's own vault has `母母女子`, `Matej Šimalčík`) - the upload finishes,
  then `verify_upload`'s read-back either crashes the run with a traceback, or
  on a cp950 box mis-decodes the paths and reports every file as missing, i.e.
  a false verification failure about a transfer that worked.
- Evidence: read both functions; the `except (subprocess.TimeoutExpired, OSError)`
  on line 218 does not cover `UnicodeDecodeError` (a `ValueError` subclass),
  and the docstring promises `None` "if the listing failed".
- Ledger: new
- Suggested fix: `encoding="utf-8", errors="replace"` on all four call sites,
  and widen `remote_listing`'s except to include `ValueError`.

### server-tools-5 - one absent guide now suppresses the licence agreement as well
- Severity: low
- Confidence: CONFIRMED
- Where: `server/install_dashboard_app.py:4466-4473` (`ship_dashboard_docs`),
  with `SHIPPED_DOCS` at :307
- What: `SHIPPED_DOCS` gained `EDITOR_SETUP.md` in the 09-11b pass, and the
  refusal is all-or-nothing: if ANY member of `SHIPPED_DOCS`/`SHIPPED_DOC_TREES`
  is absent, the function returns False and ships NO documents at all - the
  `legal/` tree (the EULA the first-run wizard gates on) included. Before the
  change, a missing `EDITOR_SETUP.md` cost nothing; now it costs the licence
  agreement on a bind-mode deploy.
- Failure scenario: a customer checkout or a `make_product_repo.ps1`-produced
  tree that strips `docs/EDITOR_SETUP.md` deploys successfully; `/help` and
  `/setup` both report no licence agreement is included in this build, and the
  operator is told to look for a guide, not for the EULA.
- Evidence: line 4466 builds `missing` from `SHIPPED_DOCS` then returns False
  for any member; `_stage_docs_tree`'s per-file `_copy` would have skipped the
  absent one harmlessly. The NOTE text at 4469-4472 already describes both
  consequences, so the behaviour is intentional-looking but the widening was
  not the finding's subject (server-tools-b-5 was about an escaping exception).
- Ledger: related to the 09-11b `dash-core-6` / `server-tools-b-5` pair
- Suggested fix: ship what is present and NOTE what is not; refuse only when
  `SHIPPED_DOC_TREES` (the legal tree) is the thing missing.

## Coverage note

Not reached: `server/setup_tree.py`, `setup_editor_account.py`,
`setup_syncthing_folder.py`, `setup_snapshots.py`, `accept_device.py`,
`create_api_key.py`, `secure_syncthing_gui.py`, `write_marker.py`,
`install_syncthing_app.py`, and ~80% of `install_dashboard_app.py` (6,132
lines - the stage/verify/swap engine, the image-mode path, the env-file
rendering and the Synology backend were only skimmed). `tools/`: untouched are
`check_mobile_origin.py`, `gen_icons.py`, `library_walk_*.py`,
`mobile_sweep_seed.py`, `make_product_repo.ps1`, `load_secrets.ps1`,
`sign_windows_binary.ps1`, `release_macos.sh`, `build_onboard_macos.sh`,
`indexer-entrypoint.sh`, and most of `ship.ps1`/`release.ps1`. `bench/` was
read only at its subprocess layer.

What the suites do not cover: neither the server nor the tools suite exercises
a non-ASCII byte anywhere - no test feeds a CJK path, filename or git subject
through any of the `text=True` subprocess calls, which is why e050413 shipped
as a field fix rather than a test failure. Nothing anywhere runs
`gen_notices.py --check`, so the generated half of `THIRD_PARTY_NOTICES.md` is
unverified by construction. The tools suite drives `Get-CardsDeployVerdict`
and `Get-KindExtrasVerdict` as pure functions, so the PowerShell that gathers
their inputs in `check_deploy_drift.ps1` (the `git -C <cards repo> status`
call, the site-scalar probe) is still untested.

## OUT OF TERRITORY
- `dashboard/requirements.lock` vs `dashboard/deploy/requirements.lock`: they
  pin different psycopg2-binary versions (2.9.13 vs 2.9.12), so CI's
  `--only dashboard-container` scan of the dev venv is not scanning the version
  the container installs.
- `tools/jobs.py` is mine but its `cmd_list` indexes `job['kind']`,
  `job['state']`, `job['attempts']` directly; a dashboard older than the field
  that added one would raise KeyError instead of a sentence. Low, unverified
  against any 0.7.34-era response shape.
