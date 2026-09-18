# CR-298 - the dashboard collector/notices/app mediums - FIXED in repo 2026-09-18 (2026-09-18b mediums wave)

Five confirmed mediums in `collector.py`, `notices.py`, `alerts.py` and
`app.py`. All five fixed; nothing owed to this group.

### CR-298A (dash-collector-alerts-2) - the b-roll archive check could not fire on the outage it was written for - FIXED (notices.py, alerts.py)

Both copies of `_check_broll_archive` scandir'd the RECORDED ROOT and treated
success as healthy. `mount_status.record_root`'s own docstring says why that
cannot work: a bind mount that goes away leaves its mount point behind, so an
unmounted dataset lists fine (empty) and the check answered OK in exactly the
window where `insert_target_detail` starts answering `known: false` and every
Send to Resolve degrades to a 540p preview. The fix is one shared probe,
`notices._broll_archive_problem(root, witness)`: the WITNESS the mount
recorded (`root_of()[1]`, b-roll's proxies directory) must EXIST, falling back
to the root for a build that recorded no witness, and an empty root is
unreadable rather than healthy - the same canary `_record_inventory` and
`alerts._check_nas_tree` already read. Existence, not directory-ness, because
another mount's witness is allowed to be a file. `alerts.py` imports the probe
inside the function (`notices` imports `alerts`, so a module-level import
would be a cycle) so the mail half and the card half can never disagree. The
dead `except StopIteration` the hunter spotted is gone with the rewrite.

### CR-298B (dash-collector-alerts-3) - a file could pair as having arrived before it left - FIXED (collector.py)

`InventoryWalk.old` is `db.nas_media_rows`, which is EMPTY for a project this
collector has never walked, so every media file of a newly activated episode
is an "appeared" half and stays live pairing evidence for two days: an
unrelated deletion elsewhere in the fleet a day later then pairs with it and
becomes a `file_moves` row in state DONE that every holding machine applies to
its own disk, with no admin in the path. The first attempt at this dropped a
first walk's arrivals outright; the coordinator's correction (2026-09-18b) is
that the harm is ORDER, not first walks, because a folder moved INTO a
brand-new project is the common case and is exactly a vanish in one pass plus
a first walk in the next. So the halves are kept and `pair_across_cycles` now
pairs only when the vanish was seen BEFORE the arrival or in the same pass
(`_vanished_first` / `_seen_order`; a half from this pass carries `""`, which
means now and must sort AFTER every carried stamp, not first). A refused pair
consumes neither half: the vanish may still pair with a genuine later
arrival, and the stale arrival ages out on its own. The comeback cancel
(same slug and rel path) is applied before the order rule and still consumes
both halves whichever order they were seen in.

### CR-298C (res-fleet-2) - the carried halves were written without a bound and read with one - FIXED (collector.py)

`db.record_pending_move_halves` had no cap while `db.pending_move_halves`
reads the OLDEST 4000 rows inside the two-day window, so one 6,000-clip upload
filled the window with halves that by construction never pair and crowded out
every half written after it: cross-cycle move detection turned itself off,
silently, for two days. `_settle_halves` now drops a pass's whole `persist`
list when it exceeds `PENDING_MOVE_HALF_WRITE_LIMIT` (1000, deliberately well
under the read's 4000 so one pass can never fill the window), with a warning
naming the count. The halves of a move the `DETECTED_MOVE_LIMIT` cap dropped
are added after the check and are never discarded - they are the only record
of those old paths. Dropping costs only the convenience (a hand move in that
window goes undetected, which is what this product did before the feature).

### CR-298D (dash-core-1) - every failure under a mount recorded itself twice - FIXED (app.py)

wire-2 installed the parent's `unhandled_error` on every mounted sub-app, and
Starlette's `ServerErrorMiddleware` runs the handler, sends its response and
then RE-RAISES, so the parent's copy catches the same exception and runs the
same handler again: two tracebacks and two connect-write-close cycles against
the database whose contention the `db_busy` notice exists to report (the write
that is loudest exactly when the server can least afford it). The wrapper
`_install_busy_handler_on_mounts` installs now stamps `scope` with
`_ERROR_RECORDED` after the inner entry - Starlette mutates the one scope dict
when it enters a Mount, so the parent sees it - and the second entry returns a
response (Starlette requires one even though it discards it) without logging
or writing. A parent-route error is unchanged: one entry, one record.

### CR-298E (dash-core-2) - a mounted app's notice named a path that does not exist, and two mounts collided on one row - FIXED (app.py, notices.py)

Since wire-2 the handler runs INSIDE the sub-app, so `scope["route"]` is the
sub-app's own route and `route_path` was the INNER template (`/api/ingest`) -
a path that exists nowhere on this dashboard, and one that `/broll` and
`/music` share verbatim across twelve routes, so one notice row and one count
served two features. Per the verifier's correction the ROUTE template is
prefixed with the mount's `root_path`, never `request.url.path` (which already
carries the prefix on this Starlette and would double it); an unmatched
request still falls through to `redact_path`'s two-segment form, which is what
keeps a `/broll/share/<token>/` failure from writing a client's credential
into a row. `redact_path`'s docstring, which still claimed the route is absent
inside a mounted sub-app, is corrected in the same change.

### Verification

- CR-298A: `test_a_mount_point_left_behind_by_an_unmount_is_not_a_readable_archive` (new) - an existing root with a missing witness raises the card AND the alert finding, and only a witness plus a non-empty root clears both. The existing `test_an_archive_this_server_cannot_list_is_a_problem_it_found` pinned the wrong invariant (it asserted an EMPTY directory clears the card) and was corrected to put a folder in the archive before asserting the clear.
- CR-298B: `test_a_file_cannot_arrive_before_it_leaves` (a carried arrival plus a fresh vanish is no move and consumes nothing; the honest order still pairs, including into a project walked for the first time) and `test_a_first_walks_arrivals_are_still_kept_as_halves`. Both of the afternoon's pinned behaviours still pass - `test_a_move_between_two_projects_is_paired_across_two_passes` and `test_a_file_that_comes_back_to_its_old_path_is_not_a_move` in `test_bug_hunt_2026_09_18_dashboard_lows.py`, the second of which is what proves the cancel-on-return still deletes both halves. The ordering test was run against the source with `_vanished_first` disabled and FAILED there.
- CR-298C: `test_one_pass_cannot_fill_the_carried_halves_window` - at the limit the halves are written, one over it none are.
- CR-298D: `test_a_failure_under_a_mount_is_recorded_once_and_under_its_own_path` and `test_a_busy_database_under_a_mount_is_counted_once` - one row, count 1, for one request under a mount.
- CR-298E: `test_two_mounts_with_the_same_inner_route_are_two_notices` plus the subject assertion in the test above (`/broll/api/ingest (RuntimeError)`).
- All six new tests were run against the pre-fix source (the four files restored to their pre-fix shape in a scratch copy) and all six FAILED; with the fixes in place `test_bug_hunt_2026_09_18b_collector_core.py`, `test_bug_hunt_2026_09_18_dashboard_mediums.py`, `test_notices.py`, `test_alerts.py`, `test_hand_moves_detected.py` are 179 passed, and `test_bug_hunt_2026_09_11b_dash_collector_alerts.py`, `test_hardening.py`, `test_db_write_locks.py` are 83 passed.

### Not fixed

- Nothing from this group's list.

### OWED TO ANOTHER GROUP

- To dashboard-api-db (`db.py`), res-fleet-2's read half: `db.pending_move_halves` is `ORDER BY seen_at, rowid LIMIT PENDING_MOVE_HALF_LIMIT`, i.e. OLDEST first, so a saturated table hides the newest halves rather than the least useful ones. Change to `ORDER BY seen_at DESC, rowid DESC` and correct the "oldest first" docstring at the same site. My side is safe alone: the write cap means one pass can no longer saturate the window, so oldest-first only matters for a table filled over many passes. `test_hand_moves_detected.py` and `test_db_write_locks.py` must be re-read with that change.
- To whoever triages dash-db-5 (low): the write cap above drops a pass's halves with a log line only. dash-db-5 asks for a `file_move_halves_dropped` notice so it is not silent; that needs a new notice kind registered WITH its writer (`db.NOTICE_KINDS`, `alerts.ALERT_KINDS`, the checks meta), which is more than this box allowed. The drop is the safe direction either way (no move is recorded, the pre-feature behaviour).

### Deploy order

Dashboard only; no wire change, no companion change. A rollback is safe: every
change is inside one container's own notice/collector behaviour, and the
pending-halves rows a rolled-back build reads are the same shape.

### Owner decisions

- None needed.
