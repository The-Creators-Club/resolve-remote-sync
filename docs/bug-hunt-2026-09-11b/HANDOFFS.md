# Hand-off wave, fix pass 2026-09-11b

The OWED lines from wave 1's ledgers (`ledger/*.md`, "OWED TO ANOTHER
TERRITORY"), routed to the territory that owns the file. Same rules as
`BUILDER_BRIEF.md` (read it again): your territory's files only, a regression
test per behavioural change, py_compile, no version bumps, no KNOWN_BUGS.md
edits, no git state changes. Append what you did to your territory's existing
ledger file under a `### Hand-off wave` heading (with its own Verification
lines), or create the ledger file if your territory had none. Lines marked
OPTIONAL are yours to decline in one sentence.

## dash-api (api.py)
- comp-ytdl-jobs: `UpgradeIn`: declare `state_write_failures: int | None = Field(default=None, ge=0)`; without it `undeclared_report_sections` names `sync_guard.upgrade.state_write_failures` daily. Dashboard first.
- comp-ytdl-jobs: `_require_fleet_caller`: answer 410 (not 403) on `/jobs/{id}/heartbeat` and `/jobs/{id}/result` when the refusal is an account bar, so companions 0.9.65..0.9.71 (which stop only on 410) stop too. You already moved heartbeat to 410 in wave 1 - confirm result is covered and that claim stays 403.
- dash-db: `_build_admin_users_view` (~3829-3833): wrap `suspended_editors`, `editor_suspension`, `fetch_pending_ssh_keys` in `try/except sqlite3.OperationalError` and render the Users page with a "could not read this right now" strip.
- server-tools: `_rollout_platforms_block`: bucket a NULL/blank `machine_state.platform` as `db.rollout_status` does (`COALESCE(platform,'windows')`, lower-cased), never `unknown`.
- comp-app: log the retrying file-move answer only on a CHANGE of state/detail (today once per move per report while a drive is out).
- dash-db (OPTIONAL): a first-class `applying` state for `file_move_targets` if the project page should show the word; today it is stored as `retrying`, which gives the behaviour.

## dash-mounts-ui (ui.py, broll.py, music.py, ytdl.py, templates, deploy)
- dash-api: `partial_admin_roll_fleet_back`: pass `settings=request.app.state.settings` into `api.roll_fleet_back` (default None reads the DEFAULT soak minutes, not this site's). Also render `current_refused` from the answer on the Packages page.
- dash-api: the home page (`ui.py:649`) and `/partials/queue` (`ui.py:925`) call `api.build_queue_view(conn, editor)` with no machine, so dash-api-4's per-machine fix is unreachable from the only templates that render it: pass the machine (each machine's row, or the machine the section is about) and read the machine-scoped fields in the template.
- dash-api (security-1): the three `_fleet_stamp` helpers in `dashboard/src/ccsync_dashboard/{broll,music,ytdl}.py` must ask dash-api's now-public suspended-account predicate (`api.account_bar_reason`) before the mounted app sees the credential, so a suspended editor's laptop cannot claim batches or downloads. Test each of the three through the mounted app with a suspended editor.
- dash-collector-alerts: `templates/partials/recovery.html` (~141): when `recovery_preview.counts_unavailable`, print `recovery_preview.note` instead of the counts line.
- dash-db: `templates/admin_assignments.html`: render an "the archived list could not be read right now" strip when `archived_unreadable` is true.
- broll: `broll.py::_init_broll_storage` (last statement, ~568): call `client_folders.ensure_schema_best_effort()` instead of `ensure_schema()`, `getattr`-guarded for an older `BROLL_WEB_SRC` checkout.
- dash-api / regression-11: render the `ytdlp.sidecar` cause beside `cap_ffmpeg` on the jobs machine list (Settings -> JOBS).

## dash-collector-alerts (alerts.py, collector.py, mount_status.py, notices.py)
- comp-ytdl-jobs / dash-api / regression-11: an `ALERT_KINDS` row WITH its writer reading the stored `ytdlp.sidecar` block (`action == failed and consecutive_failures >= 2`), naming the machine and the cause. Register the notice kind with its writer.
- comp-ytdl-jobs: `_check_upgrade_refused`: a staleness bound so the row also clears for machines on 0.9.65..0.9.71 where the refusal is sticky for the life of the process.
- dash-db: `collector._run_enforce` (~1317): pass `for_enforce=True` to `db.fetch_machine_selections(...)`, keeping CR-110's `base_pairs`/`base_editors` belt (dash-db-4).
- dash-db: `alerts._collector_started_recently`: compare against `db.collector_stale_bound(...)` instead of the flat `COLLECTOR_STALE_SECONDS` (the other way the false positive fires).
- dash-mounts-ui: `mount_status.recheck()`: probe existence (`os.path.exists` or `any(os.scandir(root))`) rather than `os.path.isdir`, and give `record_root(name, root, witness="")` a witness argument so music/ytdl can record their db file; then update the two callers' comments.
- dash-mounts-ui (res-fleet-3's other half): a notice/alert kind for "this container is booting the image while `current.json` names a version" (`running_source` / `reverted_reason` / the new `revert_refused_reason` from `dashboard_update.status()` once dash-release-jobs exposes it).
- dash-release-jobs (OPTIONAL): a `feed_record_rejected` kind instead of reusing `feed_state.last_error`.
- broll (OPTIONAL, low): a `client_shares_unreadable` notice when `client_shares.db` cannot be opened.

## dash-core (app.py, settings.py)
- broll: `login_gate`: delete `_broll_fleet_list_re` (~1075) and its `GET` clause (~1176-1178) with the comment; the route it carved out for was deleted. (dash-core's wave-1 ledger says this was done as security-2: confirm, and add the test if none.)
- dash-release-jobs: `settings.py`: `release_feed_sig_url: str = ""` (env `DASH_RELEASE_FEED_SIG_URL`), and tell dash-release-jobs's `fetch_and_verify_channel` reads it when set (that read is in release_feed.py: record it as OWED back if you cannot make the two meet without touching that file - the settings half alone is harmless).

## dash-release-jobs (release_feed.py, dashboard_update.py, jobs.py, cards_*.py)
- dash-mounts-ui: `dashboard_update.status()`: add `revert_refused_reason` and `revert_refused_from` to the `current` dict (fixed key set).
- dash-core: `release_feed.fetch_and_verify_channel`: read `settings.release_feed_sig_url` when set instead of `_signature_url(url)` (getattr-guarded so a settings object without the field still works).
- dash-api / regression-11: `GET /api/v1/jobs/{id}/why`'s `no_capable_machine` explanation names the `ytdlp.sidecar` cause when that is why a machine is not capable.

## server-tools (server/, tools/, ci.yml)
- dash-core: `server/install_dashboard_app.py`: add `"EDITOR_SETUP.md"` to `SHIPPED_DOCS`.
- install-onboard: `.github/workflows/ci.yml`: the `macos` job also runs the onboarding suite (`cd onboarding && python -m pytest tests -q`).
- dash-release-jobs: `tools/publish_feed.py:810`: `--from-manifest` assigns `args.platform` after argparse, bypassing `choices`; fold to lower case and re-validate before signing.

## comp-ytdl-jobs (ytdl_executor.py, jobs_runner.py)
- ytdl-web: `ytdl_executor.heartbeat()`: send the `X-CCSync-Machine` header `routes_fleet._machine_of` accepts (optional both ways).
- dash-api: confirm `jobs_runner._heartbeat` treats 401/403 as terminal for the current job (stop the child, record cancelled, do not retry) and surfaces the refusal on the tray; wave 1's CR-254f says so - add the tray-surfacing half if it is missing.

## small items (one builder: comp-ui, install-onboard tests, broll comment, comp-sync copy)
- comp-app -> comp-ui: a Settings window / tray item that calls the new `machine.remint()` behind the new unreadable-machine-id advisory (comp-app-5), `settings_window.py` / `tray.py`, with a test.
- comp-app -> comp-sync: `file_moves.py`: the `"N Resolve clip(s) relinked"` plural now reaches the editor; count it properly (owner rule: no "(s)" in editor-visible copy).
- comp-ui (tests-5): a test through the PUBLIC entry point for `tray._persist_failed_line` so a bypassed helper is visible.
- install-onboard (tests-5): `installer/tests/Test-BinDirLeftovers.ps1`: one case driving the uninstaller's public path asserting the leftover report is REPORTED, not merely computed.
- broll: `broll/web/app/routes_fleet.py:65-67` comment and `test_the_fleet_docstrings_do_not_claim_the_gate_needs_widening` still describe `_broll_fleet_list_re` as present in the dashboard; it is deleted.

## orchestrator (not a builder)
- KNOWN_BUGS.md: relabel CR-242b (dash-release-jobs-3 -> -4) and CR-242c (-4 -> -5); add the missing one-line entry for the real dash-release-jobs-3 (per-kind fleet cap moved into `db.claim_job`'s compare-and-set, `db.py:9334`, wired from `api.py:10321`); correct that entry's Owner decisions line. Same three errors in `docs/bug-hunt-2026-09-11/ledger/dash-release-jobs.md` lines 33, 44, 105-108.
- CLAUDE.md "Running tests": the installer row now enumerates `installer\tests\Test-*.ps1`; replace the seven-name comment.
- music / broll / ytdl-web: nothing, once dash-mounts-ui's three `_fleet_stamp` helpers ask the predicate.
