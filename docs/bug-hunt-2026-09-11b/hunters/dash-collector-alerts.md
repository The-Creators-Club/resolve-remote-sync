# dash-collector-alerts - the collector cycle, the forty alert kinds, the notice writers, the invariants, the mount registry, recovery and the Syncthing client

Files read (with approximate coverage): `dashboard/src/ccsync_dashboard/alerts.py`
(the whole 18e69f3 diff plus `scan`/`deliver`/`run_cycle`/`sink_deliverable`/
`weekly_due`/`heartbeat_due`/`_open_subjects`/`_check_out_of_tree`/
`_check_red_unexplained`/`_check_collector_stale`/`_check_nas_engine`/
`_check_weekly_send`/`_check_notices`, ~70%), `collector.py` (the diff hunks,
`_run_cycle`'s mount re-probe, `_run_enforce`'s share plan, `_run_alerts`,
~45%), `notices.py` (`_check_feature_mounts`, `_check_plan_without_share`,
`redact_path`/`record_server_error`, `_check_alerts_sink`, ~50%),
`invariants.py` (`Outcome`/`broken`/`evaluate`/`run_cycle`, the two
`for_enforce` hunks, ~45%), `mount_status.py` (100%), `recovery.py`
(`_walk`/`preview_restore`/`restore_into_quarantine`, ~30%),
`syncthing_client.py` (`_call`, 100% of the diff), `health.py` and
`protection.py` (skimmed, no diff), plus `db.py`'s
`fetch_collector_status`/`record_invariant_result`/`broken_invariants`/
`record_poll_run`/`record_alert`/`last_alert_at` and `settings.py`'s collector
cadences as callees, and `app.py`'s 500 handler for the `route` half of
`record_server_error`.

Tests run:
`dashboard> .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_dash_collector_alerts.py tests/test_alerts.py tests/test_notices.py tests/test_collector.py tests/test_invariants.py tests/test_recovery.py -q`
-> 248 passed. Two ad-hoc scripts run from the dashboard venv (scratchpad, not
in the repo) to prove findings 1 and 2.

## Findings

### dash-collector-alerts-1 - a Syncthing-less deployment now reports its own healthy collector as STOPPED, for ever
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:8788` (the new `MAX(started_at)`
  `collector_stale`) and `dashboard/src/ccsync_dashboard/alerts.py:1646`
  (`_check_collector_stale`, and `_collector_started_recently` above it)
- What: dash-collector-alerts-3 moved `collector_stale` out of the
  `if reachable and finished_at` branch so it is now the age of the newest
  `poll_runs.started_at` of ANY kind against `COLLECTOR_STALE_SECONDS` (180 s).
  On a deployment with no `syncthing_url`, `collector.py:390` runs only
  `SYNCTHING_FREE_KINDS` - `prune` (3600 s), `invariants` (900 s), `alerts`
  (600 s) - so the newest start is always at least 600 s old and the flag is
  permanently True. `_check_collector_stale` is an `error` kind, so it is
  raised on every pass, shown on PROBLEMS THE SERVER FOUND, counted in the
  topbar's red chip and re-mailed daily. The twin gate that
  `_check_nas_engine` received in the same commit
  (`if not getattr(ctx.settings, "syncthing_url", "")`) was not added here.
- Failure scenario: a vendor/zero-touch dashboard before Syncthing is
  configured (or any dev/bare deployment) boots, the collector turns
  perfectly, and within ten minutes the home page says "The server's
  background collector has not completed a cycle" and the owner is mailed it
  every day. At 40f931a `reachable` was False on such a site so `stale` was
  never computed and the finding never fired: this is a new false positive,
  not a pre-existing one.
- Evidence: scratch script against a fresh migrated DB holding only
  `prune`/`invariants`/`alerts` rows aged 30/15/10 minutes, with
  `Settings(syncthing_url="")`:
  `collector_stale: True reachable: False` /
  `collector_stale findings: [('error', 'the server')]`.
  Cadence defaults read at `settings.py:542-573`; the kind gate at
  `collector.py:390`; `SYNCTHING_FREE_KINDS = ("prune", "invariants", "alerts")`
  at `db.py:591`.
- Ledger: CR-241 / dash-collector-alerts-3 opens this; "regression introduced
  by the 18e69f3 fix pass"
- Suggested fix: the liveness threshold must be derived from the cadences that
  actually run, not a fixed 180 s - e.g. compare against
  `max(COLLECTOR_STALE_SECONDS, 2 * min(interval of the kinds this deployment
  runs))`, or keep 180 s only when `syncthing_url` is set and fall back to the
  slowest enabled interval otherwise.

### dash-collector-alerts-2 - the out-of-tree silence now also silences the catch-all "red and we cannot say why"
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/alerts.py:1939` (the new
  `if ctx.name(who) not in ctx.open_alert_subjects("out_of_tree")`), against
  `alerts.py:2909` (`_check_red_unexplained`)
- What: `Ctx.name()` is not a getter - it ADDS the subject to `ctx.named`
  (`alerts.py:1122`), which is the one thing `_check_red_unexplained` consults
  to decide it has nothing to add. The dash-collector-alerts-1 fix calls
  `ctx.name(who)` inside the branch that then `continue`s, i.e. on exactly the
  machines `_check_out_of_tree` decided to say NOTHING about. At 40f931a the
  `continue` came before `who = ctx.name(who)`, so those machines stayed
  un-named.
- Failure scenario: an editor opens a personal (non-tree) project, their
  machine has out-of-tree clips and has also been RED for three hours.
  `out_of_tree` deliberately says nothing; `red_unexplained` - the catch-all
  whose whole purpose is to turn "green while dead" into a message - now also
  says nothing, because the machine was marked named by a check that produced
  no finding. Nobody is told the machine is not syncing.
- Evidence: scratch script with a stub Ctx (RED machine, 3 h old lane state,
  `resolve_out_of_tree=40`, an unknown open project, no open alert row):
  `out_of_tree findings: []` / `ctx.named after out_of_tree: {'jsmith/EDIT-PC'}`
  / `red_unexplained findings: []`; with `ctx.named` cleared (the 40f931a
  behaviour) `red_unexplained` yields `['jsmith/EDIT-PC']`.
- Ledger: CR-241 / dash-collector-alerts-1 (2026-09-11 hunt) introduces it -
  "new"
- Suggested fix: read the open-subject set without naming, i.e.
  `if who not in ctx.open_alert_subjects("out_of_tree"): continue` (the
  subject key is the raw `who`; `ctx.name` is only reached on the line below
  for findings that are actually emitted).

### dash-collector-alerts-3 - the truncated-invariant keep-list only survives one pass
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/invariants.py:1213` (the new
  `if result.get("truncated")` keep-list) against
  `dashboard/src/ccsync_dashboard/db.py:3575-3581`
  (`record_invariant_result`'s delete)
- What: the fix keeps the previously-stored broken subjects in
  `broken_subjects` so `clear_notices_of_kind` does not close the notices the
  20-subject cap dropped. But `record_invariant_result` runs a few lines
  ABOVE, on the same BROKEN verdict, and deletes every `invariant_results`
  subject row not in the kept 20. `stored_broken` is built from
  `db.broken_invariants`, which reads that table - so from the very next pass
  it contains only the 20 currently visible, and the other 25 are no longer in
  the keep-list.
- Failure scenario: an invariant breaks on 45 subjects (a fleet-wide
  mis-share). Pass 1 writes 20 notices and keeps the old set. Pass 2 keeps
  only the 20 still visible; if the SQL ordering shifts (subjects 1-20 vs
  21-40), the notices for whichever 20 have just left are cleared and the
  owner is told "this has cleared" about a subject that is still broken -
  precisely the mistake the hunk's own comment is written against.
- Evidence: `db.record_invariant_result` docstring says it "DELETE[s] the
  subject rows this pass did not name" and runs the delete for
  `verdict in (INVARIANT_OK, INVARIANT_BROKEN)`; `db.broken_invariants` reads
  `invariant_results WHERE state=? AND subject<>''`. `invariants.MAX_SUBJECTS`
  == `db.INVARIANT_MAX_SUBJECTS` == 20, so the caps agree - only the
  persistence does not.
- Ledger: "CR-241 does not fix dash-collector-alerts-4 (the invariants half)"
- Suggested fix: pass the truncation down to `db.record_invariant_result`
  (a `truncated=True` that suppresses the delete, exactly as a non-verdict
  already does), or record all subjects and cap only at render time.

### dash-collector-alerts-4 - mount_status restores a stale boot verdict over a newer one the ytdl gate wrote
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/mount_status.py:115-119` (the
  `elif present and name in _RUNTIME_DEGRADED` restore), against
  `dashboard/src/ccsync_dashboard/ytdl.py:456` (`_record` -> `mount_status.record`)
- What: `recheck()` stashes the pre-degrade verdict in `_RUNTIME_DEGRADED` and
  replays it when the root comes back, unconditionally. `_STATE` is not owned
  by `recheck` alone: the ytdl feature gate rewrites its entry from a request
  thread whenever `[features] youtube_download` flips (that is what
  `snapshot()`'s own docstring says). A verdict written between the degrade
  and the restore is silently overwritten with the boot one.
- Failure scenario: the ytdl data root goes away, `recheck` records
  `("ytdl", degraded)` and stashes `("mounted", "...")`. The admin then turns
  `youtube_download` off; the gate records `("ytdl", "disabled")`. The bind
  mount comes back; the next `recheck` restores `("ytdl", "mounted")`.
  `_check_feature_mounts` sees "mounted", clears the notice, and
  `/api/v1/health` and the nav report a page that answers 404 to every
  request.
- Evidence: read only - the interleaving needs a feature flip inside the
  degraded window, which I did not reproduce. `ytdl._record` short-circuits on
  `status == self.status`, so the gate will not re-assert its verdict on its
  own once the restore has diverged from what the gate believes.
- Ledger: new (res-fleet-2, 2026-09-11)
- Suggested fix: only restore when the entry is still the degraded verdict
  this function wrote - compare `_STATE.get(name)` against the value `recheck`
  installed before replacing it, and drop the stash otherwise.

### dash-collector-alerts-5 - `recheck()` holds the mount registry lock across a filesystem probe
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/mount_status.py:104-119`
- What: the `probe(root)` (`os.path.isdir` by default) is called with `_LOCK`
  held, once per recorded mount. `snapshot()` and `get()` take the same lock
  from request threads (`api.py:1456`, the health route; `ui`'s nav) and from
  `alerts.Ctx` on the collector thread. A stat on a root whose backing export
  is gone but whose mount is still present (a hard NFS/CIFS mount, the exact
  scenario res-fleet-2 was written for) blocks in the kernel, and every reader
  blocks behind it.
- Failure scenario: the NAS export behind `/vault` hangs rather than
  disappearing; the collector thread parks inside `recheck` holding `_LOCK`,
  and `/api/v1/health` - the page an admin opens to find out why - hangs too.
- Evidence: read only; a hanging mount was not simulated. The docstring's
  "cheap by contract: one `is_dir` per mount" is true of a local bind mount
  and not of a stale network one.
- Ledger: new (res-fleet-2, 2026-09-11)
- Suggested fix: snapshot `_ROOTS` and `_STATE` under the lock, probe outside
  it, then re-take the lock to apply the changes.

### dash-collector-alerts-6 - the vendor default (no sink) now writes three failed heartbeat rows a day instead of one
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/alerts.py:798-812` (`heartbeat_due`,
  `ok_only=True` + `MAX_SEND_ATTEMPTS_PER_SLOT`) against
  `alerts.py:3673` (`_transmit` returns `ok=False` for `SINK_NONE`) and
  `alerts.py:4088` (`run_cycle` sends the heartbeat through `send`, unlike the
  weekly report which is recorded `ok=1` directly for this case)
- What: `weekly_due`'s no-sink carve-out (`run_cycle` writes an `ok=1`
  "generated, not sent" row) has no heartbeat equivalent. With
  `ok_only=True`, `last_alert_at(KIND_HEARTBEAT, ok_only=True)` is empty for
  ever on a site with no sink, so `heartbeat_due` is True on every cycle until
  the new per-day attempt ceiling stops it at three.
- Failure scenario: every vendor-default deployment writes three
  `ok=0 "no alert channel is configured"` heartbeat rows a day (was one), and
  the Alerts page's WHAT WAS SENT list shows three failures a day about a
  setting rather than a fault.
- Evidence: `_transmit` line 3673 returns `ok: False` for `SINK_NONE`;
  `_send_committed` records the attempt unconditionally; `run_cycle`'s
  `sink == SINK_NONE` branch exists only for `KIND_WEEKLY`.
- Ledger: introduced by res-fleet-4 (2026-09-11) - new
- Suggested fix: give the heartbeat the same `sink == SINK_NONE` carve-out
  `run_cycle` already gives the weekly report, or skip `heartbeat_due`
  entirely when the sink is `none`.

### dash-collector-alerts-7 - the restore refuses on a truncated walk but the preview it is chosen from still shows the wrong list
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/recovery.py:300-327`
  (`preview_restore`) against `recovery.py:369-387` (the new 409)
- What: the fix refuses `restore_into_quarantine` when either walk hit
  `MAX_SCAN_FILES`, on the grounds that a truncated LIVE walk classifies every
  file it never reached as missing. `preview_restore` has the identical
  defect and was not changed: it still returns `missing`/`missing_count`/
  `missing_bytes` computed from the same partial `live_files`, with
  `truncated: True` as the only signal.
- Failure scenario: a project over 50,000 files - the owner opens BROWSE A
  SNAPSHOT, reads "18,402 files missing, 4.1 TB" (almost all of which are
  present), presses restore and gets a 409. The number that drove the decision
  was invented by the cap.
- Evidence: `preview_restore` at `recovery.py:302` (`live_files, live_cut =
  ... _walk(live)`) and the `missing` loop below it; `MAX_SCAN_FILES = 50_000`
  at `recovery.py:101`.
- Ledger: "CR-241 partially fixes dash-collector-alerts-5" (the restore half
  only)
- Suggested fix: make the preview say "this folder is larger than this server
  compares; these counts are not the whole picture" instead of returning
  counts, i.e. suppress `missing_count`/`missing_bytes` when `truncated`.

### dash-collector-alerts-8 - `_collector_started_recently` is dead code: both sides of the same wire were fixed
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/alerts.py:1625-1645` against
  `dashboard/src/ccsync_dashboard/db.py:8788`
- What: two builders fixed dash-collector-alerts-3 in two places with the same
  query. `db.fetch_collector_status` now derives `collector_stale` from
  `SELECT MAX(started_at) FROM poll_runs`, and `_collector_started_recently`
  re-runs that query against the same constant. The branch it guards
  (`if not ctx.collector.get("collector_stale")`) is therefore only reached
  when the helper must answer True or None, so it can never change the
  verdict - one extra full-table aggregate per alerts pass for nothing. It
  also silently diverges if a caller ever passes a non-default
  `stale_after_seconds` to `fetch_collector_status`.
- Failure scenario: none at runtime beyond the wasted query; the hazard is a
  future change to one threshold and not the other.
- Evidence: the two queries are textually the same; both compare against
  `db.COLLECTOR_STALE_SECONDS = 180.0` (`db.py:576`).
- Ledger: new (housekeeping on CR-241)
- Suggested fix: delete `_collector_started_recently` and trust
  `ctx.collector["collector_stale"]`, now that `db` computes it from the start
  of the newest run.

## Coverage note
`health.py`, `protection.py` and `crash_report.py` carry no diff since
40f931a and I only skimmed them; `collector.py` outside the four changed
hunks (the completion/inventory/remoteneed passes, the budget carry-over) and
`notices.py`'s other twenty-odd writers had a single read each, not a trace.
I did not exercise the new `res-fleet-6` "unplanned devices" path in
`_run_enforce` against a live Syncthing config, only read it (it looks right:
`unplanned` is disjoint from `actual`, so `removed` is unchanged and `added`
correctly subtracts it). I did not attempt a v47-database migration check
(dash-db's territory). The suite does not cover: a Syncthing-less deployment
end to end (finding 1 is invisible to every existing test because they all
set a `syncthing_url` or write a fresh `poll_runs` row), a second invariants
pass after a truncated BROKEN verdict (finding 3 needs two passes; the new
regression test asserts only the first), or any interleaving of
`mount_status.recheck` with `ytdl`'s request-thread `record` (findings 4/5).

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/app.py:1301`: `request.scope.get("route")`
  works only for FastAPI `APIRoute`s (which set `child_scope["route"]`);
  Starlette 1.6.0's `Route`/`Mount` do not, so the route-template dedup in
  `notices.redact_path` never engages for a Mount. Safe (the two-segment
  fallback covers `/broll/share/<token>`), but the comment claims Mounts have
  no usable `.path` when in fact Starlette's `Mount.path` exists - worth a
  line if dash-core touches it.
