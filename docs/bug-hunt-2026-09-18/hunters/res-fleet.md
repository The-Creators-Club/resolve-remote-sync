# res-fleet - what the FLEET does when the server side goes wrong (whole paths, across files)

Files read (with approximate coverage): `dashboard/src/ccsync_dashboard/app.py`
(boot sequence, the 500/503 handler, `CollectorWatchdog`, ~40%),
`collector.py` (loop, `run_cycle`, enforce, inventory + hand-move detection,
completion, alerts, ~70%), `db.py` (migrate/connect, fleet halt, file moves,
resolve undos, jobs + pinning, `forget_machine`, machine update requests,
~25%), `api.py` (`api_report` and the whole `commands` block, `_upgrade_info`,
forget/push routes, ingest-cancel lookups, ~20%), `notices.py` (db-busy /
slow-write), `alerts.py` (`run_cycle`, `_check_file_moves`,
`_check_jobs_pinned_no_executor`), `jobs.py` (`machine_facts`, bulk facts,
`policy`, `can_pin`), `cards.py` (`engine_provider`, `mount_cards`),
`cards_exec.py`, `cards_pool.py` (`any_engine`), companion
`file_moves.py` (all), `app.py` (`_apply_pushed_update`,
`_apply_file_moves`, `_build_lanes`), `manifest.py`, `fixer.list_project_dirs`,
plus `docs/HAND_MOVES_ON_THE_SERVER.md`, `docs/FILE_MOVES.md` (skim),
`docs/CARDS_TWO_PROJECTS.md` (skim) and the 24 hunter reports.

Tests run: none (read-only tracing; every finding below is verified by reading
both ends of the path, and two by `git log -L` on the hunk that moved).

## Findings

### res-fleet-1 - the engine pool killed the pinned-job executor: it is never STARTED, and jobs still get pinned into a queue nothing drains
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/app.py:735-752` (the boot gate), with
  `cards.py:314`/`cards.py:568` + `cards_pool.any_engine`
  (`cards_pool.py:268`) as the other end, and `cards_exec.start()`
  (`cards_exec.py:182-205`) as the half that WAS fixed.
- What: `PinnedExecutor.start()` was deliberately un-gated for the lazy pool
  ("with a lazily built pool the answer at boot is no, and it becomes yes the
  moment somebody opens an episode"), but its CALLER still is: app.py does
  `if executor.available(): ... release_pinned_jobs(); executor.start()`. With
  the pool, `available()` at boot asks `engine_provider` -> `pool.any_engine()`
  (no engines are built until somebody opens an episode) -> `app.state.cards_engine`,
  which `mount_cards` sets to `None` unconditionally (`cards.py:568`). So on
  EVERY boot of the current image the branch is false: the executor thread is
  never created, and `db.release_pinned_jobs()` never runs. `jobs.can_pin(app)`
  asks the same executor object LATER, when a job's retry budget is spent - by
  which time an editor has opened an episode and `available()` is true - so
  jobs are still moved to `pinned` by a dashboard with no worker.
- Failure scenario: dashboard 0.7.47+ boots (log line: "fleet jobs are never
  pinned here: Timeline Cards is not mounted in this dashboard", which is also
  untrue - it is mounted). An editor opens `/cards/p/<slug>/`, so an engine
  exists. A `proxy-480p` job then exhausts its fleet retry budget; `can_pin`
  answers True; the row goes to `pinned` with `claimed_machine` NULL. Nothing
  ever takes it: the only consumer is the thread that was never started. It is
  not `abandoned` (so nobody is told the work was given up on) and
  `_check_jobs_pinned_no_executor` cannot see it either - its first shape needs
  `cards mount != "mounted"` and its second needs a non-empty `claimed_machine`.
  The jobs page says the dashboard is running it, for ever. Additionally, rows
  a previous container left in hand are never released at boot.
- Evidence: `git log -L735,752:dashboard/src/ccsync_dashboard/app.py` shows the
  `if executor.available():` gate landing in 0612dcf (phase 4, one engine built
  at boot) and untouched by the pool commits (8a41f35, 5491f44), which changed
  `cards_exec.start()`'s own guard and added `cards.engine_provider` instead.
  `mount_cards` sets `app.state.cards_engine = None` at `cards.py:568` and never
  assigns an engine to it again in the pool world (`cards.py:296-314` says it is
  kept only as "an engine, if there is one"); `EnginePool` builds on first entry.
  `grep -n pinned_executor` finds exactly one starter (app.py:751) and two
  readers (api.py:10396, ui.py:3267).
- Ledger: new (regression of the phase-4 rule 5 contract in CLAUDE.md: "a job
  pinned into a queue nothing drains is worse than one that says so"; not in
  KNOWN_BUGS through CR-281, and none of dash-cards, dash-core or
  dash-release-jobs reported it).
- Suggested fix: start the executor unconditionally when Timeline Cards is
  configured (`executor.start()` already refuses to run without a source) and
  move the `release_pinned_jobs()` boot release out from behind `available()`;
  fix `why_not()` so a mounted-but-empty pool does not claim Cards is unmounted.

### res-fleet-2 - a pushed update the machine can never take removes that computer from the jobs fleet for ever, and nothing anywhere says why
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9464-9501` (the push command) and
  `api.py:5751-5769` (`_upgrade_info`'s three silent refusals),
  `jobs.py:503`/`jobs.py:622-627` (`upgrading`) and `jobs.py:805`
  (`policy` -> `REFUSE_UPGRADING`), companion
  `companion/src/ccsync_companion/app.py:7612-7625` (the IGNORED branch).
- What: the push and the OFFER are computed independently. `machine_update_request`
  emits `commands.upgrade` with a version whenever a request exists, while
  `_upgrade_info` returns None - silently, by design - when the build is
  retracted, needs a newer dashboard, or does not match the machine's arch. The
  companion then refuses ("this machine is not being offered that build"), logs
  it once locally, and reports NOTHING back (`sync_guard.upgrade.refused_*` is
  only written for an offer that was received and refused). The request has no
  expiry and no writer clears it except the machine reporting the asked-for
  version or an admin pressing cancel; meanwhile `jobs.machine_facts` turns
  "has an update waiting" into a blanket refusal of every job kind.
- Failure scenario: an admin pushes companion 0.9.74 to leso's Mac; the vendor
  then retracts that build (or the record's `arch` does not match what the Mac
  reports). From that moment the reply carries `commands.upgrade` with no
  `upgrade` offer for ever; the Mac never takes it and never says why; the
  Packages page shows a bare `asked for 0.9.74` chip with no age and no reason;
  and that machine is refused every whisper/proxy/peaks job in the fleet
  indefinitely with `reason_code=upgrading`. Nothing expires, no alert kind
  covers it, and `DELETE /admin/machines/.../update` is the only cure - which
  nobody knows to press.
- Evidence: `grep -n "DELETE FROM file_move_targets|clear_machine_update_request"`
  and a read of `package_store`/the retract and delete routes: no path clears a
  pending request when the build it names stops being offerable; `db.py:4774-4823`
  has no expiry column read anywhere; `alerts.py` has no `update_request` check
  (`grep -n "update_request" alerts.py` -> nothing).
- Ledger: new (related to REL-8, which covers the machine that DOWNLOADS and
  fails, not the machine that is never offered the bytes).
- Suggested fix: when `_upgrade_info` returns None while a request is
  outstanding, do not emit `commands.upgrade`; record the reason on the machine
  row and raise it as a notice/alert kind, and let the scheduler stop treating a
  push older than N hours as `upgrading`.

### res-fleet-3 - a detected hand move between two projects makes every holding machine file its copy into a directory that is not a project on that machine, and reports it as done
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:5469-5502`
  (`file_move_target_machines` - the source project's ticks, the destination's
  are never consulted), companion
  `companion/src/ccsync_companion/file_moves.py:324-395` (`apply_move`:
  `dest.parent.mkdir(parents=True, exist_ok=True)` unconditionally), against
  `docs/HAND_MOVES_ON_THE_SERVER.md` §4b.
- What: §4b of the hand-moves design says a target machine that does not sync
  the DESTINATION project must trash its copy locally and record `trashed
  locally, destination not synced here`. That rule was implemented only on lane
  B's relocation path (`project_rel_fn` in companion `app.py:2337-2343`, "None
  for anything not synced here, which is §4b's case"); the primary path - the
  `commands.file_moves` command, which is faster and is what the detection
  actually drives - has no such check. It creates the destination project's
  directory tree and moves the file there, then answers ok/`done`.
- Failure scenario: an admin moves a card dump in Explorer from
  `Creator Profiles` to `FF5 Talent Gap`. Ruskin syncs the first and not the
  second. His companion creates `P:\Projects\2026\FF5 Talent Gap\...` and moves
  the file in. That directory has no `.ccsync-project` marker (nothing creates
  one), so `fixer.list_project_dirs` never sees it, the media manifest never
  reports it, lane A/B never touch it and the fixer never meets it: the file is
  a permanent invisible orphan on his disk, unreachable by every tool the
  product has, while the dashboard's MOVES history says his computer followed
  the move. The disk it fills is the one lane B's 20 GB floor parks on.
- Evidence: read of both paths; `apply_move` has no plan/selection argument at
  all (its whole signature is `(move, local_root, ledger)`), and
  `fixer.list_project_dirs` (`companion/src/ccsync_companion/fixer.py:381-416`)
  keys projects on `MARKER_FILENAME`.
- Ledger: new (`docs/HAND_MOVES_ON_THE_SERVER.md` §4b is listed as work the
  companion still owes; this reports that the command path silently does
  something WORSE than the old behaviour rather than nothing).
- Suggested fix: pass the machine's own project map into `apply_move` (the
  sequencer already computes it for lane B's locator) and take §4b's branch -
  trash locally, answer `trashed locally, destination not synced here` - when
  the destination project is not in this machine's plan.

### res-fleet-4 - forgetting or renaming a computer strands its outstanding file moves and Resolve undos, and leaves an alert nobody can clear
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:7884-7925` (`_MACHINE_STATE_TABLES`
  / `forget_machine`), `db.py:5617-5648` (`pending_file_moves`, keyed
  `(editor_username, machine)`), `db.py:5651-5692`
  (`expire_delivered_file_moves`), `alerts.py:2157-2176` (`file_move_expired`),
  `db.py:5937-5953` (`pending_resolve_undos`).
- What: `forget_machine` deletes ten tables' rows for that computer and neither
  `file_move_targets` nor `resolve_undo_requests` is among them - nothing in
  `db.py` ever deletes from either (`grep -n "DELETE FROM file_move_targets"` ->
  nothing). Both are keyed by the HOSTNAME, so the same stranding happens when a
  machine is renamed (the registry survives a rename through `machine_id`; these
  two command tables do not). The stranded target keeps `applied_at IS NULL`, is
  never offered again, ages into `expired_at`, and then raises a warn alert whose
  fix line ("use [ MOVE ON THE SERVER AND ON EVERY MACHINE ] again once that
  computer is back online") names a computer the dashboard no longer has.
- Failure scenario: an admin moves a shoot on the server, then renames leso's Mac
  (or presses "forget this computer", CR-76, which is explicitly NOT a
  revocation - the companion keeps reporting under the new name). The move
  command is never delivered under the new key, so that machine still holds the
  file at the old path, and lane A - which never deletes - puts it back on the
  NAS at the path the admin just cleared: the exact failure the whole feature
  exists to prevent. The only trace is a `file_move_expired` warning for a
  machine name that no longer exists, which cannot be answered, re-issued
  usefully, or cleared.
- Evidence: reads above; `pending_file_moves` filters on
  `t.editor_username=? AND t.machine=?` with no `machine_id` fallback;
  `reissue_file_move` only clears `expired_at`, so a re-issued row for a gone
  hostname expires again on the next pass.
- Ledger: new (related to CR-76 and to UX-5/DASH-9, which bounded these commands
  by delivery on the assumption the machine key is stable).
- Suggested fix: re-key (or fan out) pending `file_move_targets` and
  `resolve_undo_requests` onto the machine's `machine_id` when a rename is
  detected, delete them in `forget_machine`, and make `_check_file_moves` skip a
  target whose machine is no longer in the registry (saying so once instead).

## Coverage note
Not reached: the Syncthing-down and half-ran-migration paths (both read and
found well guarded - `migrate()` is per-statement with `_already_applied`, the
enforce cycle refuses on an empty myID, an unseeded snapshot and a
blast-radius removal cap); the OTA `dashboard_update` half-apply (dash-release-jobs-1
owns the disk-full half); the alerts delivery path (read, correctly budgeted and
never marks an undelivered finding as sent); the Cards tunnel and the third
episode (dash-cards-1..9 cover what I would have said). I did not exercise any
suite, so all four findings rest on reading both ends plus `git log -L` for
res-fleet-1. The suites do not cover the boot-time wiring of the pinned
executor at all (`test_cards_pool.py` builds pools, never `create_app`'s
lifespan), which is why res-fleet-1 survived a green gate.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/cards_exec.py`: `why_not()` answers "Timeline
  Cards is not mounted in this dashboard" for a pool that is mounted but empty,
  so the boot log and the Settings -> JOBS line both misdescribe the state.
- `dashboard/src/ccsync_dashboard/collector.py:1621`: `_run_inventory` cannot see
  a file that CAME BACK at a path a detected move cleared (lane A re-uploading
  in the window before the command lands); it is an appear with no vanish, so no
  pair matches and no notice is raised about the duplicate left on the NAS.
