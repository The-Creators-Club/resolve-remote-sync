# CR-291 - the companion-core mediums (2026-09-18b wave)

## CR-291 - companion core: the stranded editing-proxy resume, the folder move nothing followed, and one stall slot for two lanes - FIXED in repo 2026-09-18 (companion app.py, file_moves.py, sync/rclone_lane.py)

### CR-291A (comp-app-2) - the editing-proxy resume still sat behind a live Resolve - FIXED (companion/src/ccsync_companion/app.py)

CR-283D/comp-app-1 took the b-roll editing-proxy resume out of
`_relink_proxies_once` (and so out of `proxy_relink_enabled`), but left the
call at the TAIL of `_refresh_media_tree_once`, below its two early returns:
`get_media_pool_items()` answering not-ok, and an ignored project. So the
resume still needed Resolve open, scripting alive and a non-ignored project,
while its own docstring says the ledger is on disk precisely for "a Resolve
that was closed when the download landed". An editor who inserted an archive
clip, got a stand-in, restarted the companion and did not reopen Resolve kept
a 1080p H.264 preview under a 6K name for ever, with the attempt budget never
even spent. The call now runs in `_media_tree_loop`, on every tick, beside
`retry_loopback_bind()` - the shape the loop already had for work that needs
no Resolve - and the `_local_root_is_broken()` gate stays inside the function
where comp-app-1 put it. The old test stubbed `get_media_pool_items` to
`ok: True`, i.e. it mocked away the gate that was still there; it is replaced
by one that drives the real loop with Resolve answering not-ok.

### CR-291B (comp-sync-3) - a hand-moved FOLDER was the one shape res-companion-2 could not read - FIXED (companion/src/ccsync_companion/file_moves.py)

The collector describes a hand-moved folder as ONE `is_dir=True` command whose
`from_rel`/`to_rel` name the directory, while lane B relocates FILES and writes
one `(old_local, new_local)` row each. `relocation_to` is an exact `_cmp_key`
equality on both halves, so the directory pair matched nothing: `apply_move`
fell through to "nothing at the old path on this machine" with `paths=None`,
app.py skipped the relink, and every clip under the folder stayed Media
Offline while the MOVES history said this machine had followed. A new ledger
method, `relocated_folder`, answers the question lane B's rows can actually
support: every row under the source must land at the SAME relative path under
the destination (prefixes folded through `_cmp_key`, CR-90), and one row
pointing elsewhere means a partly carried folder, which must not be relinked
as if it were complete. It is consulted in both branches - the `not
src.exists()` resume branch, and the `dest.exists()` refusal, where an EMPTY
leftover source directory (lane B carries files, not the husk) otherwise
produced the flat "the destination already exists on this machine". Nothing
here deletes the husk.

### CR-291C (comp-sync-4) - lane B's recovery stamp erased lane A's live stall - FIXED (companion/src/ccsync_companion/sync/rclone_lane.py)

Lane A and lane B share one `state/lane_stall.json`, and only lane B's
`sync_guard_report()` reaches the wire. `_note_stall_recovered` read
`stall_record()`, which prefers the lane's OWN in-memory `_last_stall`,
checked the label against that stale copy, and then wrote it back over the
shared file - so a lane A kill that landed after a lane B kill was destroyed
by lane B's next good pass: `stall_report()` answered None, app.py's
`_lane_stall_record()` fallback skipped the `recovered_at` row, and the only
persisted evidence of the lane A kill was gone with lane A still uploading
nothing. `_note_stall_recovered` now reads the PERSISTED record and re-checks
the label against what the file actually holds; another lane's record is left
untouched (this lane only retires its own stale in-memory copy). The mirror of
the same shared-slot bug is closed too: `stall_record()` returns the NEWER of
the in-memory and persisted records (file first on a tie, undateable sorts
oldest), so lane B's report carries a fresh lane A stall instead of its own old
one. The existing `test_the_other_lanes_pass_does_not_end_this_lanes_stall`
could not see any of this because it builds a FRESH lane object; the new test
REUSES the lane B instance, which is the live shape.

### Verification
- comp-app-2: `tests/test_bug_hunt_2026_09_18_companion_core.py::test_the_editing_proxy_resume_runs_with_resolve_closed` - fails with the call back in `_refresh_media_tree_once` (asserted by reverting the move), passes now.
- comp-sync-3: `tests/test_bug_hunt_2026_09_18b_companion_core.py` - four tests (folder followed, partly followed refused, empty husk accepted, husk with files still refused); the two positive ones fail with `relocated_folder` short-circuited out.
- comp-sync-4: `tests/test_rclone_lane.py::test_a_lane_b_recovery_does_not_erase_a_later_lane_a_stall` - fails on the pre-fix `stall_record()` read, passes now.
- Suites re-run green: `test_bug_hunt_2026_09_18_companion_core.py`, `test_bug_hunt_2026_09_18b_companion_core.py`, `test_rclone_lane.py`, `test_file_moves.py` (206 passed) plus the neighbours that drive the same code, `test_app.py`, `test_broll_proxy_upgrade.py`, `test_bug_hunt_2026_09_18_companion_media.py`, `test_lane_watchdog.py` (465 passed).

### Not fixed
- Nothing from this group's list. All three assigned findings landed inside the box.

### OWED TO ANOTHER GROUP
- None. One foreign test was touched only because the fix made it a stub-attribute error: `tests/test_bug_hunt_2026_09_18_companion_core.py`'s `_Stub` in `test_a_retired_media_tree_thread_exits_instead_of_looping` gained a no-op `_resume_broll_proxy_upgrades` counter (same file group, same file).

### Deploy order
- Companion-only, no wire change. `relocated_folder` reads a ledger the same companion writes, and the stall record's shape on the wire is unchanged (the dashboard still sees a `stalled` block or nothing), so a dashboard one release older or newer, and a rollback, are all fine.

### Owner decisions
- None needed.
