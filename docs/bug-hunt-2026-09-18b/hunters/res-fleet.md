# res-fleet - what the FLEET does when the server side goes wrong

Files read (with approximate coverage): `git diff` of
`dashboard/src/ccsync_dashboard/db.py` (whole diff, plus the v54 step, the
migration runner, the file-move/undo command tables and `prune`),
`api.py` (whole diff: report handler, `_upgrade_info` / `_machine_can_be_offered`,
the new report sections, the reply keys), `app.py` (lifespan, the busy/error
handler, mount handlers, `check_persisted_secrets`, `_open_path`),
`collector.py` (whole diff: `_timed`/slow-poll, hand-move detection, the
cross-cycle halves, the session sweep), `alerts.py` + `notices.py` +
`health.py` (the new kinds, `_check_file_moves`, `_check_jobs_pinned_no_executor`,
`_check_broll_archive`, the disk floor), `cards_pool.py`, `cards_exec.py`,
`dashboard_update.py` (`_set_state` / `apply_update` / `request_restart`),
`locate.py` + `companion/src/ccsync_companion/sync/server_locate.py` + the
relevant part of `sync/lane_guard.py`, `companion/src/ccsync_companion/broll_standins.py`
(`placed_report`) and `app.py`'s guard assembly. Skimmed:
`dashboard/tests/test_bug_hunt_2026_09_18_dashboard_lows.py`,
`docs/bug-hunt-2026-09-18/ledger/*` for the entries these touch.

Tests run: none from the repo suites (lens, no territory). One ad-hoc snippet
against the dashboard venv (`dashboard/.venv/Scripts/python.exe`, scratchpad
script, in-memory tmp DB) to prove finding res-fleet-1; output quoted below.

## Findings

### res-fleet-1 - a command offered under a machine's FORMER hostname can never be answered
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:5923` (`mark_file_move_applied`)
  and `dashboard/src/ccsync_dashboard/db.py:6168` (`mark_resolve_undo_applied`);
  the other end is `dashboard/src/ccsync_dashboard/api.py:9475` and
  `api.py:9492` (both pass the REPORTING hostname).
- What: the morning's res-fleet-4 fix taught the OFFER side to look under the
  former hostnames of the same `machine_id` (`db.command_machine_names`,
  `pending_file_moves`, `pending_resolve_undos`) and taught the DELIVERY stamp
  to write against the row's own key (`api._by_target_machine`). The ANSWER
  side was not changed: `mark_file_move_applied` and `mark_resolve_undo_applied`
  still match `WHERE ... AND machine=?` with the hostname the report came in
  under, so every answer to a command filed under the old name updates zero
  rows and is silently dropped (both functions return False, and the caller's
  logging is inside that `if`, so not even a log line).
- Failure scenario: an editor renames their PC. SYS-18a deliberately defers the
  adoption by a report or two (and refuses it entirely while both names look
  live). Inside that window the dashboard now offers move #17 (filed under
  `OLD-PC`) to the machine reporting as `NEW-PC`; the companion moves the file,
  relinks Resolve and answers `file_moves_applied: [{id: 17, ok: true,
  state: "done"}]`. `mark_file_move_applied(..., machine="NEW-PC")` matches
  nothing, `applied_at` stays NULL, so the SAME move is re-offered on the next
  report and on every report after it - the companion re-applies (or answers
  its not-found arm) once every thirty seconds - until `expire_file_move_targets`
  stamps `expired_at` and fires `file_move_expired`, which is verbatim the
  outcome res-fleet-4 was written to end. The identical path exists for
  `commands.resolve_undo`: an admin's undo is executed on the editor's Resolve
  and the dashboard keeps asking for it.
- Evidence: scratchpad snippet against the working tree, dashboard venv:
  ```
  offered: [(1, 'OLD-PC')]
  answer recorded: False
  still pending: [1]
  undo offered: [(1, 'OLD-PC')]
  undo answer recorded: False
  ```
  (`upsert_machine` OLD-PC/NEW-PC on `machine_id="mid-1"`, `record_file_move`
  targeting OLD-PC, `pending_file_moves(..., "NEW-PC", machine_id="mid-1")`,
  then `mark_file_move_applied(..., "NEW-PC", ...)`.)
  `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_lows.py:231`
  (`test_a_command_under_a_former_hostname_is_still_offered`) asserts the offer
  and the `target_machine` key and stops there; no test asserts that the answer
  retires the row, which is why the half-landed fix passed the gate.
- Ledger: CR-285/`ledger/dashboard.md` res-fleet-4 does not fix res-fleet-4's
  own scenario (new).
- Suggested fix: carry the row's key through the answer as well - either have
  the companion echo `target_machine` (it already receives nothing of the kind,
  so simpler: ) let `mark_file_move_applied` / `mark_resolve_undo_applied` take
  the `machine_id` and match `machine IN command_machine_names(...)`, exactly as
  the offer does; add a test that offers under OLD-PC, answers as NEW-PC and
  asserts `applied_at IS NOT NULL` and that the next offer is empty.

### res-fleet-2 - the carried move halves are written without a bound and read with one
- Severity: medium
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (how often a fleet reaches it)
- Where: `dashboard/src/ccsync_dashboard/collector.py:2650` (`unpaired_halves`)
  and `collector.py:_settle_halves`; `dashboard/src/ccsync_dashboard/db.py:8760`
  (`record_pending_move_halves`, no cap) vs `db.py:8790` (`pending_move_halves`,
  `ORDER BY seen_at, rowid LIMIT PENDING_MOVE_HALF_LIMIT=4000`).
- What: every unpaired vanish AND every unpaired appearance of every walked
  project is persisted, with no ceiling on the write, while the pairing read
  takes only the OLDEST 4000 rows inside the 2-day window. A vanish is rare; an
  APPEARANCE is not - every new clip an editor uploads, every file of a newly
  activated project's first walk, every project restored from a snapshot is an
  unpaired "appeared" half. Once the live window holds more than 4000 of them,
  the read is saturated by the oldest (by construction the least likely to ever
  pair, since a half only survives that long because nothing matched it), and
  fresh halves are never offered to `pair_across_cycles` at all: the cross-cycle
  detection this whole table exists for stops working, silently, exactly on the
  big fleets it was built for (>8 active projects).
- Failure scenario: a shoot of 6,000 clips is uploaded into `2026/FF5/Animals`.
  The next inventory pass writes ~6,000 `appeared` halves (one executemany
  inside the inventory pass's write transaction, on the connection whose lock
  hold is what `test_db_write_locks.py` guards). For the next two days
  `pending_move_halves` returns those 6,000-capped-to-4,000 oldest rows, and a
  genuine hand move out of project A into project B in that window is never
  paired - the operator gets the pre-fix behaviour (lane A puts the file back,
  lane B's breaker parks) with no notice saying so.
- Evidence: read of both functions; `record_pending_move_halves` takes the whole
  `halves` sequence, `_settle_halves` passes `plan.persist` whole, and
  `unpaired_halves` filters only ambiguity and `Proxy/` - not "is this project's
  whole content new". `pending_move_halves`' own docstring acknowledges "a
  restore or a remount can leave tens of thousands of them" and bounds only the
  READ.
- Ledger: CR-285 dash-collector-alerts-1 opens a neighbour (new).
- Suggested fix: bound the write too (drop a pass's halves entirely when it
  produced more than, say, `DETECTED_MOVE_LIMIT` of them - a pass that size is
  the restore the notice already covers), and read newest-first (or by
  `seen_at DESC`) so a saturated table degrades to "recent moves still pair"
  rather than "no move ever pairs again".

### res-fleet-3 - the OTA's last two state writes are still not best-effort, so a full /data swaps the tree and never restarts
- Severity: medium
- Confidence: CONFIRMED (code path), PLAUSIBLE (needs a full or read-only /data)
- Where: `dashboard/src/ccsync_dashboard/dashboard_update.py:1471` (the
  `step="restarting"` write at the end of `apply_update`, immediately before
  `request_restart`) and `dashboard_update.py:1558` (the write inside
  `request_restart` itself). Contrast `dashboard_update.py:590`, `:1288`,
  `:1303`, which this pass DID convert to `best_effort=True`.
- What: dash-release-jobs-1's premise is "the process has to be able to exit 75
  when it cannot write a byte". The two writes that stand between a completed
  swap and the exit were left as hard writes. `_write_json` raising OSError
  there propagates out of `apply_update` after `staging.rename(final)` and after
  `current.json` has been rewritten to name the new tree.
- Failure scenario: `/data` fills (the backup this same function just took is
  the likeliest cause). The code tree is swapped, `current.json` names the new
  version, `boot_attempts` is cleared - and then `_set_state` raises,
  `request_restart` never runs, the caller's `except` calls `_fail_state` which
  records `step="failed"`. The admin's page says the update FAILED; the
  container goes on serving the old code; the next unrelated restart (a
  redeploy, a host reboot) silently boots the new tree. "Failed" and "applied"
  are the two states that must not be confusable, and this produces both at
  once.
- Evidence: `grep -n "_set_state(" dashboard/src/ccsync_dashboard/dashboard_update.py`
  - lines 590/1288/1303 carry `best_effort=True`, 1353..1471 and 1558 do not;
  read of `apply_update`'s tail (no try/except around the final `_set_state`
  other than the `finally` that only unlinks the archive).
- Ledger: CR-285/`ledger/dashboard.md` dash-release-jobs-1 is half-applied (new).
- Suggested fix: `best_effort=True` on the `step="restarting"` write at the end
  of `apply_update` and on `request_restart`'s own write; the restart request
  and the exit must not be able to fail on a byte.

### res-fleet-4 - `standins_known`: the contract the comment states is not the one the code sends
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9862` (`if known: result[...]`)
  vs the comment three lines above and `db.standins_known`'s docstring.
- What: both write-ups say "an empty list is sent for the same reason, so the
  two shapes cannot be confused" - absent meaning "this dashboard does not know"
  and `{"rels": []}` meaning "there are none". The code only ever sets the key
  when the list is non-empty, so the two ARE confused: a fleet with no stand-ins
  and a dashboard too old to answer look identical on the wire. The behaviour is
  in the safe direction today (the companion is told to demux as before), but
  the next reader implements against the comment, and the reply then carries no
  way to say "none", which is what the wired-rig optimisation needs to be worth
  anything.
- Failure scenario: a later companion build reads absent as "demux as before"
  and `{"rels": []}` as "skip the demux entirely". Because the dashboard never
  sends the empty form, the optimisation never engages and the wired rig keeps
  ffprobing the whole archive - the exact cost proxy-tiers-4 was written to
  remove, still being paid, with nothing failing.
- Evidence: read of `api_report`'s stand-in block and `db.standins_known`; the
  test (`test_a_stand_in_this_machine_placed_is_known_to_the_whole_fleet`) only
  asserts the non-empty case.
- Ledger: related to CR-285 proxy-tiers-4 (new).
- Suggested fix: send `result["standins_known"] = {"rels": known}`
  unconditionally inside the `try` (it is already best-effort), or correct both
  comments to say absent and empty mean the same thing.

### res-fleet-5 - `cards_exec.is_running()` is a flag, not a fact: it lies in both directions
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_exec.py:129` (`_RUNNING`),
  `:212` (`start()`), `:239` (`stop()`); read by
  `dashboard/src/ccsync_dashboard/alerts.py:2649` (`_check_jobs_pinned_no_executor`).
- What: the flag is set at the end of `start()` and cleared at the top of
  `stop()`. `start()` has an early `return` for "the previous thread is still
  alive" that does NOT set it, and `stop()` clears it before the join that may
  time out and leave the thread running. The alert built on it is the one whose
  whole job is to notice a missing drain thread, and it is phrased as a fact
  ("the worker that drains them is not running in this container", fix:
  "Restart the dashboard").
- Failure scenario: (a) a stop whose join times out inside a long ffmpeg - the
  worker IS draining, `is_running()` is False, and the next alerts cycle mails
  an ERROR telling the operator to restart a container that is mid-encode;
  (b) the thread dies on a BaseException (MemoryError in ffmpeg glue) - the flag
  stays set and the check that exists for exactly this stays silent, which is
  the "green while dead" shape.
- Evidence: read of `start`/`stop`/`_loop`; `_note_running(True)` is only on the
  success path of `start`, `_note_running(False)` is before `thread.join`.
- Ledger: related to CR-285 res-fleet-1 (new).
- Suggested fix: make `is_running()` ask the thread (`self._thread is not None
  and self._thread.is_alive()`) through a module-level weak reference to the
  live executor, rather than an Event that only records intent.

### res-fleet-6 - the new locate body cap is not derived from the route's own file cap
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/app.py:285` (`MAX_LOCATE_BODY_BYTES =
  512 * 1024`) vs `dashboard/src/ccsync_dashboard/locate.py:50`
  (`MAX_LOCATE_FILES = 2000`) and
  `companion/src/ccsync_companion/sync/server_locate.py:170` (any non-200 is
  "cannot tell").
- What: the comment justifies 512 KB as "2000 entries of ~120 bytes of JSON,
  with room to spare", but the entry size is the BASENAME, and this product's
  basenames are long and often non-ASCII (`Matej Šimalčík`, CJK project
  folders), which `json.dumps` escapes to 6 bytes per character by default. A
  legitimate maximum-size request from a companion is rejected by the
  middleware, before the route's carefully worded 413 ever runs - and the
  companion collapses every non-200 into "treating these files as deletions".
- Failure scenario: a lane B pass trashes a batch of proxies whose originals
  were moved on the NAS; the relocation probe asks locate about 2000 long-named
  files; the middleware 413s on the body; the probe cannot discount the moves,
  so lane B's breaker trips and proxy download parks on that machine until a
  human clears it - the CR-44 failure, re-armed by a size limit.
- Evidence: read of `_BODY_LIMITS`, `locate.MAX_LOCATE_FILES`,
  `ServerLocate.locate` (`if status != 200 ... return None`) and
  `lane_guard.account_pass`'s use of the probe.
- Ledger: related to CR-285 security-4 (new).
- Suggested fix: derive the cap from the file cap with an honest per-entry
  figure (`MAX_LOCATE_FILES * 512` bytes, ~1 MB), or have the companion chunk
  its locate calls so the body cannot approach it.

### res-fleet-7 - every report from a stand-in-bearing machine rewrites the whole `broll_standins` set
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:8815` (`record_standins_placed`)
  called from `api.py:9412`; producer
  `companion/src/ccsync_companion/broll_standins.py:163` (`placed_report`,
  "the section is therefore always sent").
- What: the companion sends `standins_placed` on EVERY report (30 s), empty list
  included, and the dashboard answers with an unconditional
  `DELETE FROM broll_standins WHERE editor_username=? AND machine=?` plus an
  `executemany` of up to 200 inserts, inside the report's write transaction -
  with no "has anything changed" latch, unlike the neighbouring sections that
  were given one. This pass is otherwise entirely about write-lock contention on
  this database.
- Failure scenario: four machines each holding 200 stand-ins produce 4 x (1
  delete + 200 inserts) every 30 s of unchanged data, lengthening exactly the
  transaction whose duration `notices.record_db_busy` and `record_slow_write`
  exist to complain about.
- Evidence: read of both sides; `record_standins_placed` has no early return for
  "the stored set already equals `keys`".
- Ledger: related to CR-285 proxy-tiers-4 (new).
- Suggested fix: compare the stored set first and return without writing when it
  is unchanged (one SELECT against a two-column index), the way the report's
  other replace-wholesale sections are guarded.

## Coverage note
Not reached: the Syncthing-down paths (`syncthing_client.py`, the enforce
cycle) beyond what `_timed`'s new slow-poll accounting touches; `jobs.py`'s
scheduler under a half-applied migration; `recovery.py` / `protection.py`;
the alert SINK delivery path (smtp/webhook failures) except
`_check_alerts_sink`'s notice; the Cards tunnel's `_routed` push under a
refused third engine (read `cards_pool` only). I did not run any suite: every
suite that would exercise these belongs to a territory hunter, and the owner
rule is that the gate runs once, centrally. Nothing in the tree tests the
ANSWER side of a command offered under a former hostname (res-fleet-1) or the
saturation of `nas_media_pending_moves` (res-fleet-2); both would need a new
test, not a changed one.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/alerts.py:2028`: `_check_broll_archive` has an
  `except StopIteration` arm that cannot be reached (`next(iter(it), None)` takes
  a default), and it scandirs a possibly hung NAS mount on the collector thread.
- `dashboard/src/ccsync_dashboard/api.py:9411`: `standins_placed = getattr(...)
  if ... else None` is written on one line with a run of spaces where a line
  break was meant; valid Python, but it reads as a merge artefact.
- `dashboard/src/ccsync_dashboard/cards_pool.py:488`: `drop()` calls `_evict`,
  but the FAILED entry that `open()` pops after the retry floor does not - if a
  gate was ever built for that slug it is not evicted.
