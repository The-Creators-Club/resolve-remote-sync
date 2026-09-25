# Verifier med-01 (2026-09-24 hunt, mediums)

Judged against HEAD (`git show HEAD:<path>`), read-only. Findings:
bug-comp-app-2, bug-comp-app-3, bug-comp-rclone-2, bug-comp-rclone-3,
bug-comp-syncthing-1, bug-comp-syncthing-2, bug-comp-syncthing-3,
bug-comp-syncthing-4.

Tally: 8 CONFIRMED (medium), 0 refuted. None is a duplicate of another in this
group. syncthing-2 and syncthing-3 are both in `_build_borrowed` ignoring the
tick mode, but they are opposite directions with separate fixes (and -3 also
needs the dashboard's `_expand_includes`). syncthing-4 belongs with high
comp-app-1 (a halt's pauses undone), but it is not the same mechanism.

## bug-comp-app-2 - CONFIRMED (medium)

`consolidate_project` (app.py:3781-3841 at HEAD) checks four things before it
starts: `_sync_enabled`, `_paused`, `config_problems`, and root
absent/broken. It never calls `_lanes_refusal()` (6302), the predicate that
`sync_now_result` and `_start_lanes` share, and that predicate is the only
place the halt and the EULA are checked. `_consolidate_upload_phase` then
calls `self._lane_a.run_once(subpath)` and `self._lane_b.run_once(subpath)`
directly. `rclone_lane._run_once_locked` (3481+) has no halt check at all: its
early returns are the root, the stop event, the rotation-only stale gate, the
breaker and the disk floor. The halt is `self.halt` (lane_guard's halt latch),
not the lane breaker, so nothing in the lane sees it. The
`_runnable_lanes` docstring (9171-9181) confirms that the stop event is never
set on a lane that was never started. The button is always offered in the
Settings window's ADVANCED section (settings_window.py:1533), and no halt
check guards it. `consolidate.lane_b_allowed` still blocks a lane B pull whose
dry run showed deletions, so this is not a data-loss path. That keeps it at
medium: an admin's stop is bypassed by one click.
Evidence: read of app.py:3781-3841 and 4080-4130, `_lanes_refusal`, rclone_lane.py:3466-3580, and grep for "halt" in rclone_lane.py (a comment only).

## bug-comp-app-3 - CONFIRMED (medium)

`_apply_diagnostics_request` (app.py:8703-8733) writes
`state["applied_request"] = request_id` to disk and then calls
`_upload_diagnostics_async`, a fire-and-forget thread whose `_upload_diagnostics`
return value (False on a signed-out identity, on a poster failure or on an
exception) is thrown away. The dashboard clears the request only when the
bundle arrives (`db.clear_diagnostics_request` is called only at api.py:10171),
so it resends the command on every reply, and the stored stamp refuses every
resend. A failed upload is therefore never retried until an admin clicks
again, and the fleet page shows "diagnostics requested" for good. The
reporter's own docstring (reporter.py:1253-1257) says app.py's triggers treat
a failure as "try again later", and this one does not. It stays medium
because the lost bundle is the one from the flaky machine the button exists
for. There is no data impact, and clicking again is a workaround.
Evidence: read of app.py:8605-8640 and 8703-8733, reporter.py:1229-1290, and the dashboard's db.py/api.py `diagnostics_request` call sites.

## bug-comp-rclone-2 - CONFIRMED (medium)

In `LaneBBreaker.note_pass` (lane_guard.py:731-817) `self._deletes` grows by
the pass's full `deleted` before any relocation is considered. The relocation
probe runs only if `would_trip or eager`, where
`eager = deleted >= max(2, max_deletes_per_pass // 2)`, which is 25 with the
default cap of 50. `_discount_relocations` is clamped to the current pass
(`min(relocated, deleted)`), so moves counted on an earlier sub-eager pass are
never taken back off the total. `_deletes` is reset only by `resume()`
(line 600). The lane already knows which files it moved for free
(`_moved_out_of_trash` and `_server_relocated_keys`, set in
`_relocate_trashed`, rclone_lane.py:4115-4175), but that count reaches the
breaker only through the lazy probe (`_account_pass`, 4490). So passes of 1-24
followed moves each add to the total, which is capped at 200, and later
trip BREAKER_CAUSE_LEAK. That is the exact shape comp-lanes-ab-5 set out to
stop. It is medium because the park needs a human RESUME and nothing is lost.
Evidence: read of lane_guard.py:431-470, 585-606 and 731-860, and rclone_lane.py:4084-4175, 4340-4410 and 4480-4495. No KNOWN_BUGS entry mentions the eager threshold.

## bug-comp-rclone-3 - CONFIRMED (medium)

`DiskFloorLatch.check` (lane_guard.py:1009-1046) updates `_free_bytes` while
parked, but it keeps `_reason` from the time it parked, so the editor and
fleet sentence keeps naming the old free-space figure. The park clears only at
`clear_free_bytes = min_free_bytes * DISK_FLOOR_CLEAR_MULTIPLE` (2.0, so 40 GB
at the default floor). The disk-pressure branch of `prune_trash`
(1281-1298) stops deleting once `free >= min_free_bytes` (1x, 20 GB), because
`_maybe_prune_trash` passes the disk floor's `min_free_bytes`
(rclone_lane.py:4536). The sequencer's `_prune_trash` runs this prune every
pass even while the lane is parked (seq 1217 and 1312). So the automatic fix
can never reach the automatic release: the lane stays parked until a manual
RESUME or until the editor frees another 20 GB, and the sentence it shows is
wrong the whole time. The hysteresis is deliberate (the comment at line 97),
but the prune target not matching it is not. It is medium because lane B stays
stopped with no data loss.
Evidence: read of lane_guard.py:95-102, 929-1046 and 1220-1300, rclone_lane.py:4517-4540, and sequencer.py:1205-1330.

## bug-comp-syncthing-1 - CONFIRMED (medium)

In `apply_move` (file_moves.py, the main branch near the end) `src.replace(dest)`
and `move_proxy_siblings(src, dest)` share one `try: ... except OSError`.
`move_proxy_siblings` (240-259) calls `candidate.replace(target)` with no
guard, so if a proxy is locked (Windows WinError 32) the function returns
`(False, "could not move it on this machine: ...", None)` after the original
has already moved. The app (app.py:8147-8200) then calls
`record_attempt_failed`, which sets the state to `retryable`, not `applying`.
On the redelivery `src` no longer exists. The resume arm accepts only
`entry.state == STATE_APPLYING`, a lane B relocation row, or a folder
relocation, so it falls through to `(True, "nothing at the old path on this
machine", None)`. With `paths=None` the app does no relink and sets
`relink_pending=False`. The clip stays offline and the proxy is left behind.
The 4b branch in the same function already wraps its proxy move in its own
try, which shows the intended pattern.
Evidence: read of file_moves.py:240-260, 429-583 and 891-916, and app.py:8140-8200.

## bug-comp-syncthing-2 - CONFIRMED (medium)

`_build_borrowed` (sequencer.py:1613-1665) skips only invalid items and never
checks `_item_upload_only(item)`, so an upload-only borrower's includes are
added to `_borrowed_lenders`. The dashboard's enforce cycle shares a lender
only for FULL borrower ticks: `selections`/`editor_selections` come from
`fetch_machine_selections(..., sync_modes=(SYNC_MODE_FULL,))`, and
`borrowers_of` is expanded over those (collector.py:1413-1515). The offer
therefore never comes, `BorrowedFolderManager._accept` returns `not-offered`
(borrowed_folders.py:356-360), and `problem_sentence` tells the editor
permanently to "Ask your admin to approve it" (shared_folders.py:167-169).
One part of the hunter's case is weaker than stated: an existing local lender
folder "still pulling down" needs the server to still share it, and enforce
would remove that share. The wrong permanent problem sentence and the wrong
subtree attribution are still real.
Evidence: read of sequencer.py:1564-1665 and 230-232, api.py:2273-2317, collector.py:1395-1515, borrowed_folders.py:344-380, and shared_folders.py:155-175.

## bug-comp-syncthing-3 - CONFIRMED (medium)

Both halves decide whether an include is "covered" without looking at the
tick mode. On the dashboard, `_expand_includes` builds
`selected = {r["slug"] for r in rows}` from `fetch_selections`, which has no
mode filter, so an upload-only lender marks the include `covered: true`. On
the companion, `_update_known_selection` puts upload-only rels into
`rel_to_slug` (sequencer.py:1567-1578). `_build_borrowed` then drops the entry
on `covered`, on `sub` falling under any selected rel, and on
`lender in slug_to_item`. The upload-only lender's own turn is lane A alone,
so no lane brings the borrowed subtree down, and nothing reports a problem.
This breaks the CLAUDE.md rule that every reader deciding what comes DOWN must
filter to `sync_modes=(FULL,)`. It is related to syncthing-2 but not a
duplicate: this is the opposite direction and needs the dashboard change too.
Evidence: read of api.py:2273-2317 (`_expand_includes`), db.py:7350-7372, and sequencer.py:1564-1665.

## bug-comp-syncthing-4 - CONFIRMED (medium; a timing race, needs a slow Syncthing)

`halt_all_sync` (app.py:7631-7664) runs `_stop_lanes()` first, which calls
`sequencer.stop()`: a 5 s wait for `_lane_c_idle`, then `join(timeout=10)`.
Only after that does it call `_pause_lane_c_folders(True)`, once, and nothing
re-asserts that pause later. Two sequencer paths can still unpause after that
point. (a) In `_lane_c_turn`, `_maybe_auto_accept` calls
`admin.accept_folder`, which does a folder POST, then `set_ignores` on the 30 s
config-write timeout, then an unconditional `set_folder_paused(id, False)`
(syncthing_admin.py:577-579). That is more than the 15 s stop() allows. The
borrowed-folder manager guards this exact call with `self.halted()` and a
comment ("accept_folder ends in an unpause; during a halt that would put a new
folder online mid-stop"), and the sequencer does not. (b)
`_wait_for_folder_sync` returns on stop, and `_verify_current_folder_unpaused`
runs next with no stop check. It calls `_set_paused(slug, False)`, which has
no halt check, if it sees the folder paused. The code path holds in both
cases, and the window needs Syncthing HTTP calls slow enough to outlast the
join. The hunter labelled it plausible, but I read the mechanism as real. It
is related to high comp-app-1 (a halt's pauses undone) but not the same bug.
Evidence: read of sequencer.py:734-777, 1854-1880, 2705-2815, 2945-3045 and 3071-3102, syncthing_admin.py:285-425 and 560-580, and app.py:6452-6490 and 7631-7715.
