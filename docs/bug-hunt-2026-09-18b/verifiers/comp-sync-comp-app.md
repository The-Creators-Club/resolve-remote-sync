# verdicts - comp-sync-comp-app

Scope: the six MEDIUMs assigned (comp-app-2/3/4, comp-sync-3/4/5). Read against the
working tree as of this verification (uncommitted fix pass over 214869b); no file
outside this one was touched.

## comp-app-2
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: the claim is exactly what the code shows. `_resume_broll_proxy_upgrades()`
  is called from one place only (`app.py:4338`, verified by grep across the whole
  companion package: the only other hits are the definition at 5151 and the tests), and
  that call site is the tail of `_refresh_media_tree_once`, below the `if not
  result.get("ok"): return` at 4288 and the `is_ignored_project` return at 4303. So the
  resume runs only when Resolve is open, scripting is alive AND the open project is not
  ignored. The morning ledger's own justification for the move
  (`ledger/companion-core.md` CR-283D: "needs no Resolve connection at all, so nothing
  is lost by moving it out") is therefore only half delivered - the
  `proxy_relink_enabled` gate is gone, the Resolve gate is not. The harm is real but
  self-healing the moment the editor opens a non-ignored project, which is why medium
  is the right rating, not high.
- Evidence: `grep -rn "_resume_broll_proxy_upgrades\|resume_pending_upgrades"` over
  `companion/src` -> one production call site; read of `_refresh_media_tree_once`
  (app.py:4277-4340) and of `_media_tree_loop` (4683-4719), where
  `retry_loopback_bind()` already demonstrates the "runs every tick regardless of
  Resolve" shape the hunter proposes.
- Fix note: the suggested fix is right and cheap - move the call into
  `_media_tree_loop` beside `retry_loopback_bind()`, keeping the
  `_local_root_is_broken()` guard inside the function where it already lives. Nothing
  else is wired to it, so the only other file a fix touches is
  `companion/tests/test_bug_hunt_2026_09_18_companion_core.py:512-560`, whose current
  test drives `_refresh_media_tree_once` with `get_media_pool_items` stubbed to
  `{"ok": True}` and would keep passing while proving nothing; it needs the `ok: False`
  case added (and the assertion re-pointed at the loop if the call moves).

## comp-app-3
- Verdict: DOWNGRADED to low
- Duplicate of: res-companion-4 (low) for the heartbeat half
- Reasoning: the mechanism is real - `_abandon_media_tree_thread` only bumps
  `_media_tree_generation`, the loop tests it at 4689 and 4713 and nowhere inside the
  pass, and `on_probe=self._stamp_media_tree_heartbeat` (app.py:4643) writes the single
  shared `self._media_tree_heartbeat` that `LaneWatchdog._media_tree_target` reads. But
  res-companion-4 already reports exactly this, at the same lines, rated low, so this is
  the same defect under a second id. The extra harm this hunter adds - two concurrent
  `apply_relinks` callers - is weaker than it reads: every Resolve call goes through
  `resolve_bridge`'s `_API_LOCK`, `resolve_journal.allow_automatic` rate-limits the
  batch per project, and the relink writes are idempotent repoints, so the outcome is
  duplicated work and log noise, not a corrupted pool. Also note the two scenarios are
  mutually exclusive in practice: a thread truly blocked in an ffprobe stamps nothing
  (so it masks nothing), and a thread that is merely slow is not yet the harm the
  watchdog exists for.
- Evidence: read of `_media_tree_loop`, `_stamp_media_tree_heartbeat`,
  `_abandon_media_tree_thread` (9498-9509), `_media_tree_target` (1177-1188) and
  `_relink_proxies_once` (4599-4672); `res-companion.md:160-185` is the same finding.
- Fix note: res-companion-4's suggested fix (bind the stamp to the generation the loop
  was born with, including the per-pass stamp at 4693) is the smaller and correct one
  and subsumes this report's heartbeat half. This hunter's extra proposal - a generation
  check before each `apply_relinks` batch - is worth folding in, but `on_probe` must
  RETURN rather than raise: it is called from inside `proxy_relink.plan_relinks`, whose
  caller wraps everything in a broad `except Exception` that would log the exit as
  "proxy relink pass failed". Fix a test alongside:
  `tests/test_bug_hunt_2026_09_18_companion_core.py` drives the loop with no pass in
  flight and cannot see either half.

## comp-app-4
- Verdict: DOWNGRADED to low
- Duplicate of: none (regression-6 is about the vocabulary on the same key, not this)
- Reasoning: the central mechanism the hunter asserts does not exist. `_upgrade_info`
  reaches its `retracted_at` branch only if `db.get_current_package` hands it a
  retracted row, and it cannot for the fleet path: `get_current_package` selects
  `is_current=1` (db.py:4161-4167), `retract_package` sets `is_current=0` in the same
  statement that stamps `retracted_at` (db.py:4255-4258), and `set_current_package`
  refuses a retracted row outright (db.py:4204). Retract the current build and either
  another build is current (an offer arrives, `_accept_offer` clears the refusal) or
  none is (`current is None` -> `_upgrade_info` returns None with NO
  `upgrade_none_reason`, so the comp-ytdl-jobs-1 clear still fires). The one reachable
  path is a targeted push: `targeted_staged_package` calls `db.get_package` by version
  and does not filter retractions, and res-fleet-2 deliberately leaves the request
  standing, so a machine with a pending push for a build later retracted does get
  `upgrade_none_reason` on every reply and does keep its stale refusal - bounded by
  `expire_machine_update_requests` (14 days) or by the next current build. Narrow,
  self-limiting, and cosmetic (a chip naming a recalled build), hence low.
- Evidence: db.py:4161-4167 (`get_current_package`), 4204 (`set_current_package`
  refusal), 4235-4262 (`retract_package` un-currents), api.py:5688-5716
  (`targeted_staged_package`, no retraction filter), api.py:5794-5808 (order of the
  checks), api.py:9711-9734 (the push case that also emits `upgrade_none_reason` and
  leaves the request standing), db.py:5308 (14-day expiry).
- Fix note: the hunter's "clear it on the retracted reason" would undo part of what
  today's dashboard-side comp-app-3 fix deliberately bought, and the arch-mismatch and
  `requires_dashboard` reasons are the genuinely long-lived ones, not retraction. If
  anything is done, do the hunter's second form: send the withheld VERSION beside the
  reason and clear the refusal only when the standing refusal names a different version.
  That touches both sides - `dashboard/src/ccsync_dashboard/api.py` (`_upgrade_info` and
  the report reply assembly) and `companion/src/ccsync_companion/upgrade.py` - plus
  `tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py`, which pins the current clear
  behaviour.

## comp-sync-3
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: both ends check out. The collector emits a folder hand-move as ONE
  `is_dir=True` row whose `from_rel`/`to_rel` are the directory
  (`collector.detect_moves`, the `_folder_move` batch at the top of the loop), while
  lane B writes relocation rows only per FILE (`rclone_lane._relocate_trashed` ->
  `_note_relocated(origin, dest)` inside the per-file loop at 4120).
  `relocation_to` is an exact `_cmp_key` equality on BOTH halves
  (file_moves.py:657-670), so a directory pair matches nothing, `apply_move` falls
  through to "nothing at the old path on this machine" with `paths=None`, and app.py
  skips the relink. The alternative branch the hunter names is real too and worse: if
  the emptied source directory still exists locally, `dest.exists()` returns the flat
  refusal "the destination already exists on this machine" (file_moves.py:461). A
  folder drag is the case the docstrings of both `record_relocation` and
  `res-companion-2` cite, so the fix misses its own headline shape.
- Evidence: read of `apply_move` (file_moves.py:400-500), `record_relocation` /
  `relocation_to` (629-670), `_relocate_trashed` / `_note_relocated`
  (rclone_lane.py:4095-4160), `detect_moves` (collector.py:2780-2812). No test in
  `test_file_moves.py` or `test_rclone_lane.py` combines `is_dir=True` with a lane B
  relocation.
- Fix note: the suggested fix (in the `not src.exists()` branch, when `move["is_dir"]`,
  accept any relocation row whose `old` is under `src` and whose `new` is the matching
  path under `dest`, and return the directory pair) is sound, but it must normalise
  with `_cmp_key` on the PREFIX too (the NFC/NFD rule, CR-90) and must not relink a
  partially-followed folder as if it were complete - one matching row under a
  50-file folder is not evidence the folder moved, so require that no relocation row
  under `src` points outside `dest`. The relink consumer is
  `app.py:_apply_file_moves` (it walks the returned directory pair), and
  `file_moves.relink_moved_clips`'s `is_dir=True` arm already handles a directory, so
  no third file is needed beyond tests.

## comp-sync-4
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: the two halves the hunter needs are both there.
  `_note_stall_recovered` reads `self.stall_record()`, which returns the lane's OWN
  in-memory `_last_stall` in preference to the shared file (rclone_lane.py:4768-4778),
  checks the label against that stale copy, and then `write_stall_record`s it back over
  the file both lanes share (`self._stall_file = self._state_dir /
  LANE_STALL_FILENAME`, one state dir for lane A and lane B - the function's own
  docstring says so). Only lane B's `sync_guard_report()` reaches the wire
  (`app.py:6856` is the sole caller), so after lane B's recovery stamp the report
  carries no `stalled` (stall_report drops anything with `recovered_at`) and app.py's
  file fallback `_lane_stall_record()` is skipped for the same key (app.py:7423-7428).
  A lane A kill that landed after a lane B kill is then gone from the wire, the tray,
  the alert AND the disk evidence the record was persisted for.
- Evidence: rclone_lane.py:4713-4800 read in full; `grep -rn "sync_guard_report()"`
  over companion/src -> `app.py:6856` only; `_stall_file` construction at 2677.
- Fix note: the hunter's fix is right and the stronger form is the one to take - read
  the PERSISTED record inside `_note_stall_recovered` (not `_last_stall`) and re-check
  the label after reading. The per-lane key inside one file is better still but changes
  the file's shape, so `app.py:_lane_stall_record()` and
  `rclone_lane.read_stall_record` would both have to learn the new shape and tolerate
  the old, and `test_the_other_lanes_pass_does_not_end_this_lanes_stall` in
  `tests/test_rclone_lane.py` pins the current one-record layout (it also builds a
  FRESH lane object, which is precisely why it does not see this bug - any regression
  test must reuse one lane instance that has `_last_stall` set).

## comp-sync-5
- Verdict: CONFIRMED
- Duplicate of: res-companion-2 (rated HIGH, already assigned to a builder)
- Reasoning: the mechanism is exactly as described and I could not refute it -
  `file_moves.py` contains no `threading` import and no lock anywhere (verified by
  grep), `_save()` writes one fixed `self._path.with_suffix(".json.tmp")` with a
  truncating `write_text` and then `replace`s it, and the three call sites are on three
  different threads: `extra_excludes_fn=self.file_moves.recent_excludes` (app.py:2427,
  lane A), `on_relocated=self.file_moves.record_relocation` (app.py:2475, lane B's pass
  thread, new today) and `record_intent`/`record` from `_apply_file_moves`
  (app.py:8139-8185, the report thread). Two `_save()`s interleaved promote a truncated
  or doubly written tmp, `_load` runs once at `__init__`, so the loss is only seen at
  the next start - which is the one moment res-companion-1's intent rows exist for. The
  reader half is less alarming than the hunter states: `recent_excludes`, `record` and
  `record_attempt_failed` all REBIND the lists rather than mutating in place, so an
  iterator holds a consistent snapshot; the corruption risk is the shared tmp file
  alone. This is the same defect res-companion-2 reports at high, so it should be
  tracked there rather than fixed twice.
- Evidence: `grep -n "Lock\|threading" companion/src/ccsync_companion/file_moves.py` ->
  no output; read of `_save` (591-614), `record` (681-706), `record_relocation`
  (629-654); `res-companion.md:80-110`.
- Fix note: one `threading.Lock` (RLock, since `record_attempt_failed` calls `record`
  which calls `_save`) around every mutator plus a unique tmp name is correct; batching
  a pass's relocations into one `_save()` is worth it too, since a 100-file lane B pass
  currently rewrites the whole ledger 100 times. Whoever fixes res-companion-2 should
  take this one with it; no other file needs to change, and
  `companion/tests/test_file_moves.py` has no test pinning single-threaded save
  behaviour that a lock would break.
