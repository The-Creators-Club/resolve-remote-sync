# dash-api - the dashboard's HTTP surface: api.py, package_store.py, settings.py, local_users.py, provision.py, android.py, locate.py

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/locate.py` (100%) and `dashboard/tests/test_locate.py` (100%)
- `dashboard/src/ccsync_dashboard/api.py`: the whole `git diff 34a3c8f..HEAD` and `git diff 18e69f3..34a3c8f` hunks, plus `get_conn`, `resolve_companion_credential`, `_require_fleet_caller`, `_require_jobs_reader`, `api_publish_package`, `api_report`'s slow-write branch, `build_editors_view`, `build_editors_view`'s OperationalError guards (~20% of 10,762 lines)
- `dashboard/src/ccsync_dashboard/package_store.py` (~80%: the gate, the soak, `store_verified_package`, `what_is_running`'s head)
- `dashboard/src/ccsync_dashboard/android.py` (100%), `settings.py` (the `cards_engines` hunk + `from_env` helpers), `local_users.py` / `provision.py` (skimmed only - see coverage note)
- Read as the other side of the wires: `companion/src/ccsync_companion/sync/server_locate.py`, `rclone_lane._relocate_trashed` / `_count_relocations`, `dashboard/src/ccsync_dashboard/notices.py` (`is_db_busy`, `record_db_busy`, `record_slow_write`), `db.py` (`replace_nas_media`, `media_rel_key`, `insert_companion_package`, `record_ignored_report_sections`, `connect`), `app.py`'s gate tables and the `unhandled_error` handler, `health.lane_strip`, `templates/partials/fleet_grid.html`, `tools/sign_release.py`, `installer/build_editor_package.ps1`.

Tests run:
- `dashboard\.venv\Scripts\python.exe -m pytest tests/test_locate.py tests/test_db_busy_2026_09_17.py -q` -> 16 passed
- three ad-hoc snippets from the dashboard venv (scratchpad, outside the repo): the collapse-refusal + locate reproduction, the busy-notice blocking measurement, and a `companion_packages` uniqueness check. Output quoted in the findings.

## Findings

### dash-api-1 - locate answers from an inventory the dashboard itself has flagged as unreadable, and that resurrects deleted files while disarming the lane B breaker
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/locate.py:60-95` (the query joins `projects` on `active=1` only and never looks at `nas_inventory_state.last_error` / `walked_at`); the consuming half is `companion/src/ccsync_companion/sync/rclone_lane.py:3974-4045` and `:4160-4193`
- What: `db.replace_nas_media` deliberately REFUSES to replace an inventory when a walk collapses (DASH-5: an unmounted dataset, or a project directory renamed by hand mid-cycle), keeps the previous rows, writes `nas_inventory_state.last_error` and does NOT update `tree_sig`, so the next cycle walks, collapses and refuses again - permanently, for as long as the directory stays renamed or unmounted. `locate()` reads `nas_media` with no reference to that health state, so in exactly the scenario the hand-move feature was built for it answers "found - at the path that just stopped existing".
- Failure scenario: somebody renames `Projects/CCT S1` on the NAS (or a pool import lands late after a NAS reboot). Lane B on an editor's machine sees the scope empty, rclone walks the local copies into `.ccsync-trash`, `_relocate_trashed` asks locate, and locate returns every file at its ORIGINAL `project_slug` + `rel_path`. `_local_destination` maps that back to the file's original local path, `_move_out_of_trash` restores it, and every restored file is added to `_server_relocated_keys`, which `_count_relocations` subtracts from the deletion count the CR-45 breaker trips on. Result: an unbounded trash-and-restore churn on the editor's disk every pass, and the one safety latch that exists for "the NAS stopped looking like the tree" never parks the lane and never tells anybody. The same mechanism silently reverses a genuine hand DELETE for as long as the stale rows survive.
- Evidence: reproduced from the dashboard venv (scratchpad script):
  ```
  seed True
  refused? False
  walk returned 0 of 1 files - not replacing. The project directory looks unmounted or was renamed on the NAS.
  {'walked': True, 'as_of': '2026-09-01T00:00:00Z', 'files': [{'name': 'gold.mov', 'size': 1234,
    'found': [{'project_slug': 'cct-s1', 'rel_path': 'Interviews/gold.mov'}]}]}
  ```
  `walked: True` and a found row, from a project whose `last_error` on the very same connection says the inventory could not be replaced. `test_locate.py` has no case for a refused or errored inventory.
- Ledger: new (related to CR-268a/b and to the DASH-5 collapse refusal)
- Suggested fix: exclude projects whose `nas_inventory_state.last_error` is non-empty (and, better, whose `walked_at` is older than a few collector intervals) from the locate join, and carry the excluded slugs in the answer so the companion's log line can say "the server could not tell for N project(s)". A path from an inventory the server knows is stale must read as "cannot tell", never as a destination.

### dash-api-2 - the database-busy handler does a blocking 5 s write on the event loop, under exactly the contention it is reporting, and usually records nothing
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/app.py:1317-1365` (the `async def unhandled_error` handler's new `is_db_busy` branch, commit 4aaca6a) calling `dashboard/src/ccsync_dashboard/notices.py:1130-1150`; the same shape one branch down for `record_server_error`
- What: the handler is `async`, so it runs ON the event loop of a `--workers 1` container, and the busy branch synchronously opens a second connection (`db.connect`, busy timeout 5 s) and does an INSERT plus `conn.commit()`. The condition that gets you here is "somebody is holding the write lock for longer than 5 s", so this write blocks the whole loop for a further busy timeout and then raises `database is locked` itself - which is swallowed, so the `db_busy` notice the rework exists to surface is precisely the one that does not get written while contention lasts. Every concurrent request (companion reports, the 15 s htmx polls, the fleet grid) is stalled behind it.
- Failure scenario: one heavy report holds the write lock for 20 s (the exact case the commit message describes). Four companions and two open dashboard tabs hit `database is locked`; each 503 then spends another 5 s of the single event loop trying to write its notice and fails. The dashboard is unresponsive for the duration, the home page gains no `db_busy` notice, and the operator sees a dashboard that "went down" with nothing on the PROBLEMS panel.
- Evidence: measured from the dashboard venv with another connection holding `BEGIN IMMEDIATE`:
  ```
  raised OperationalError database is locked
  blocked for 5.4 s
  ```
  `db.connect` sets `timeout=5.0` and `PRAGMA busy_timeout=5000` (`db.py:690-708`); `unhandled_error` is declared `async def` and calls `notices.record_db_busy` directly, not through `run_in_threadpool`.
- Ledger: new (the 4aaca6a rework; related to CR-240i)
- Suggested fix: do the recording off the loop (`await run_in_threadpool(...)`) and open the notice connection with a short busy timeout (e.g. `db.connect(path, busy_ms=250)`) so a failed record costs milliseconds; better still, coalesce busy events in memory and let the collector flush them, since the 503 answer itself needs no database.

### dash-api-3 - `as_of` is a tree-wide MAX, so one freshly walked project makes every locate answer look current
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/locate.py:118-126` (`_as_of` = `SELECT MAX(refreshed_at) FROM nas_media`)
- What: `refreshed_at` is written per project, only when that project's walk actually replaces its rows (`db.replace_nas_media:8443-8449`); a project whose `tree_sig` is unchanged, whose walk was refused, or which has not been walked for weeks keeps its old stamp. The single global maximum therefore reports the freshest project in the tree as if it were the freshness of THIS answer, which is the one number the docstring offers the caller for judging staleness ("how old the server's picture is").
- Failure scenario: project A is walked every cycle, project B's inventory has been refused since a NAS reboot 3 days ago. A locate answered entirely from B's rows comes back with `as_of` = a minute ago. The companion logs "inventory as of <now>" beside a rename it made from 3-day-old data, so even the post-mortem points the wrong way.
- Evidence: read; the reproduction in dash-api-1 shows the stamp frozen at the seed time while the refused walk wrote a newer `walked_at` into `nas_inventory_state`.
- Ledger: new
- Suggested fix: compute `as_of` as the MINIMUM `refreshed_at` over the projects that actually contributed a match (or return it per found entry), so the number bounds the answer rather than flattering it.

### dash-api-4 - a lane a machine never reported draws as a quiet GREEN chip
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/health.py:877-883` (via `api.build_editors_view:1101-1107`, added since 34a3c8f), rendered at `dashboard/templates/partials/fleet_grid.html:205-207`
- What: `lane_strip` fills a missing lane with `{"state": "not reported", "chip": GREEN, "reported": False}`, and the template colours by `chip` alone (`"quiet" if lane.chip == "green"`), so the `reported` flag it is given is never read. A lane whose thread died, or a companion old enough not to send it, is drawn in the same muted style as a healthy one.
- Failure scenario: lane C's supervisor thread dies on an editor's machine and the section stops arriving. The fleet grid shows three muted chips, the third reading "Syncthing: not reported", and the row's headline is unaffected - the "green while dead" shape.
- Evidence: read both sides; `test_fleet_grid_declutter_2026_09_11.py` asserts the strip's order and the green-is-quiet rule, not the not-reported case.
- Ledger: new
- Suggested fix: give a not-reported lane its own chip class (amber, or a distinct "unknown" style) or have the template read `lane.reported`; the data is already there.

### dash-api-5 - `skipped_exists` is now a per-subpath figure rendered as a tree-wide fact, and a stale one never clears
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/api.py:7230-7240` (the declared-but-unread `subpath`), `api.py:7838-7840`, `db.py:7185-7186` (`skipped_exists=COALESCE(excluded.skipped_exists, machine_state.skipped_exists)`), copy at `ui.py:324-327`
- What: CR-267a declared `subpath` so the nested-key audit stops flagging 0.9.7x companions, and nothing reads it. The companion's scan is scoped to one project prefix, but the stored count is a single per-machine number and the sentence an admin reads ("{n} file(s) exist on the NAS under the same name at a different size") states it of the whole computer. Because the upsert COALESCEs, a count from one project's scan persists until some later scan reports a number, so it can outlive the condition and name the wrong scope while it does.
- Failure scenario: a scoped scan reports 4 for project X; project X is later untied from the machine. The chip keeps saying 4 files on this computer will never go up, with no way for the admin to find them.
- Evidence: read; no consumer of `subpath` exists anywhere in `dashboard/src`.
- Ledger: related to CR-267a (declared only)
- Suggested fix: store and render the subpath beside the count (or clear the count when a report carries a scoped scan for a different subpath), so the sentence names the scope it measured.

### dash-api-6 - a publish places the file before the row is inserted, so a failed insert leaves a replaced live artefact under an existing record
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/package_store.py:457-466` (`os.replace(part_path, dest_dir / filename)` then `db.insert_companion_package`, commit later)
- What: the file is moved into its final, served name BEFORE the row exists and before the transaction commits. The docstring's guarantee covers "a file with no row", which is harmless - but the ordering also means that when the insert or the commit fails after the replace (a busy database, an IntegrityError from two publishes of the same version racing past the route's `get_package` 409 check), the bytes at the served filename have already been swapped while the surviving record's `sha256` describes the old bytes.
- Failure scenario: two `-Publish` runs of the same version with different bytes overlap (ship interrupted and re-run while uvicorn drains the first). The loser's `os.replace` lands, its insert raises, and every companion that downloads that build fails its sha check and cannot upgrade, with the Packages page showing a normal record.
- Evidence: read; `UNIQUE (kind, platform, version)` confirmed against a migrated database, so a same-kind race does raise at the insert. The window is narrow and the route's 409 covers the sequential case.
- Ledger: new
- Suggested fix: move the file to its final name only after the insert has succeeded (still before `conn.commit()`), or write to a temporary name and `os.replace` after the commit that the DASH-3 ordering note already reasons about.

## Coverage note
`local_users.py` and `provision.py` were skimmed for shape only - neither has changed since before 34a3c8f and the time box went on the locate route and the busy-database rework. Of `api.py` I read the week's diff thoroughly and the credential/publish/report paths around it; the selection, project, share and fleet-command routes (the other ~8,000 lines) were not re-read this hunt. I did not exercise the locate route against a database shaped like a v47 (0.7.34) build; `nas_media` predates v47, so the route should degrade to `walked: false` there, but that is unverified. No suite covers a locate answered from a refused or stale inventory (dash-api-1), nor the exception handler's behaviour while the database really is locked (dash-api-2 - `test_db_busy_2026_09_17.py` injects the OperationalError rather than holding a lock, so the 5 s blocking write it then performs is never measured).

## OUT OF TERRITORY
- `companion/src/ccsync_companion/sync/server_locate.py:~160`: `rel = str(place.get("rel_path") or "").strip()` - stripping whitespace off a path that will drive a local rename contradicts the module's own "the bytes on disk are the truth" rule for a server filename with a trailing space (comp-sync).
- `dashboard/src/ccsync_dashboard/app.py:1370-1375`: `record_server_error` has the same on-the-loop blocking-write shape as dash-api-2, pre-dating it (dash-core).
