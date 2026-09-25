# Wave 2 ledger - c-sync (chunk 1 of 2)

New tests: `companion/tests/test_bug_hunt_2026_09_24_w2_c-sync.py` (19 tests).
All 14 fix tests were run against HEAD's copies of the eight changed modules
(`git show HEAD:` into a scratch `src/`, PYTHONPATH first). All 14 fail there.
The 3 controls pass there and here.

Tests run for the whole chunk:
`companion\.venv\Scripts\python.exe -m pytest` on test_borrowed_folders,
test_bug_hunt_2026_09_11_comp_sync, test_bug_hunt_2026_09_11b_comp_sync,
test_cr319_skip_ahead, test_file_moves, test_halt_holds_lane_c,
test_lane_guard, test_manifest, test_rclone_lane, test_rclone_lane_races,
test_sequencer, test_sequencer_perf, test_shared_folders, test_sync_halt,
test_sync_sequencer_policy, test_syncthing_admin and the new file: 724 passed.
test_bug_hunt_2026_09_11_comp_ui + test_bug_hunt_2026_09_18_companion_core:
62 passed. test_app.py: 384 passed, 7 failed. The 7 are consolidate and EULA
tests (KeyError 'report' / 'during_copy', the EULA text). They exercise
app.py/eula code that other groups are editing in this wave. None of them
touches a file changed here.

Skew / deploy order for the whole chunk: companion-only. No wire key, no
schema. `known_relocated` and `release_ok` are in-process keyword arguments.
Each has a default, and the callers probe the signature (`_accepts_kw` /
`syncthing_admin.release_guard`), so test doubles and older admins keep
working. The OWED dashboard change for syncthing-3 is independent of this
one: the companion now treats a `covered` include whose lender is ticked
upload-only as uncovered, so it works against dashboard 0.7.57/0.7.58 as they
are.

## bug-comp-rclone-2 - moves the lane followed on a sub-eager pass stay on the breaker's cumulative counter for ever
- Status: FIXED
- Verified as: verifier med-01 CONFIRMED (medium). I re-read `note_pass`
  (lane_guard.py): `_deletes += deleted` happens before the relocation
  check. The probe only runs when `would_trip or eager` (eager = 25 at the
  default cap), and the discount is clamped to the current pass.
  `_relocate_trashed` already computes the server's placements for free.
- Fix: `LaneBBreaker.note_pass` takes `known_relocated`, clamped to the pass.
  It is discounted on EVERY pass before the trip test. When the lazy probe
  still runs, only `probe - known` is taken off, so nothing is discounted
  twice (lane_guard.py note_pass, ~731-830). `RcloneLane._relocate_trashed`
  records `_server_relocated_count`: this pass's trashed files the server
  placed elsewhere, whether they were moved out of the trash, ambiguous or
  not synced here. `_account_pass` passes it in (rclone_lane.py ~2507,
  ~4178, ~4495). comp-sync-1's own-path rule is unchanged: a place equal to
  the trashed-from path is still not counted.
- Regression test: `test_sub_eager_followed_moves_do_not_fill_the_slow_leak_counter`
  (on HEAD: TypeError, no such kwarg. The mechanism is the hunter's p1.py:
  12 x 20 leaves 200 on the counter, then 2 more trip LEAK).
  `test_the_known_figure_is_clamped_and_never_double_counted` checks that
  45, not 35, stays on the counter. `test_the_lane_hands_the_servers_placements_to_the_breaker`
  gets 0 == 7 on HEAD.
- Tests run: see top -> green.
- Skew / deploy order: companion only.
- OWED: none
- Review round (2026-09-25): the reviewer was right. `note_pass` took
  `known` off `deleted` before `eager` was computed, so a pass whose raw
  count crossed the eager threshold could drop below it and skip the probe.
  Their case: 30 trashed, 10 located by the server, 20 same-path re-renders
  only the probe sees. That left 20 on the counter for good, where HEAD left
  0. Fix: `raw_deleted` is captured before the known discount and `eager`
  reads it (lane_guard.py ~794 and ~812). `would_trip` still reads the
  discounted count on purpose: the located moves are not deletions, and a
  raw count over a fraction-narrowed `limit` but under 25 needs no probe once
  they are off. New tests:
  `test_a_mixed_known_and_probe_pass_over_the_eager_threshold_still_probes`
  (30/10/probe 30: one probe call and 0 on the counter; it fails with the
  pre-review `eager = deleted >=` line restored) and the control
  `test_a_pass_under_the_eager_threshold_still_skips_the_probe` (24 raw, no
  probe call, 20 on the counter). Ran test_bug_hunt_2026_09_24_w2_c-sync,
  test_lane_guard, test_rclone_lane, test_rclone_lane_races: 266 passed.

## bug-comp-rclone-3 - the free-space park keeps its first sentence and never clears after the trash prune frees space
- Status: FIXED
- Verified as: verifier med-01 CONFIRMED. `DiskFloorLatch.check` kept
  `_reason` from park time. `_maybe_prune_trash` passed the 1x floor, but
  the park clears at 2x (`DISK_FLOOR_CLEAR_MULTIPLE`), so the prune could
  never produce the release. The sequencer prunes every pass, even while
  parked.
- Fix: while parked, `check()` rebuilds `_reason` from the current
  measurement. The `at` time is kept. Above the floor but below the clear
  threshold, the sentence says "starts again on its own at 40 GB" rather
  than "needs 20 GB" beside "has 22 GB" (lane_guard.py `_sentence` / `check`,
  ~1010-1060). The new `RcloneLane._prune_free_target()` returns the floor
  while running and `clear_free_bytes` while parked. `_maybe_prune_trash`
  uses it, so the disk-pressure prune now works up to the release point.
  Oldest batch first, and never the last batch, as before.
- Regression test: `test_a_parked_floor_says_the_current_free_space` (on
  HEAD the reason still says 10 GB), `test_the_disk_pressure_prune_works_towards_the_clear_threshold_while_parked`
  and `test_a_prune_to_the_clear_threshold_releases_the_park` (on HEAD:
  AttributeError, no target helper. End to end, three 15 GB batches, 10 GB
  free: it now reaches 40 GB and the park clears).
- Tests run: see top -> green. test_app's disk_floor tests pass.
- Skew / deploy order: companion only. The reason stays a free-text string
  on the existing `disk_floor.reason` wire field, with no em dash.
- OWED: none

## bug-comp-syncthing-1 - a proxy that cannot follow turns a completed move into a "failed" one, and the retry then drops the relink
- Status: FIXED
- Verified as: verifier med-01 CONFIRMED. `src.replace(dest)` and
  `move_proxy_siblings` shared one `except OSError`. The resume arm trusted
  only `applying` rows. app.py records `record_attempt_failed` ->
  `retryable`.
- Fix: `move_proxy_siblings(src, dest, failed=None)` makes each proxy its
  own attempt. A proxy that will not move is logged, named in `failed` and
  left where it is (file_moves.py ~256-300). The main branch now keeps the
  original's rename alone in the fatal try. After that the move is ok with
  its paths, and the detail says "N proxy file(s) were in use and stayed at
  the old path" (~800-815). The resume arm also accepts
  `_attempt_moved_it()`: a `retryable`/`blocked` row whose intent paths are
  exactly src/dest, with src gone and dest present. This recovers the rows
  0.9.77 already left in the field. A 4b intent has an empty `new_local` and
  can never match.
- Regression test: `test_a_locked_proxy_does_not_turn_a_moved_original_into_a_failed_move`
  (HEAD: ok False) and `test_a_redelivery_after_an_old_builds_failed_attempt_still_relinks`
  (HEAD: paths None). Control: `test_a_failed_row_for_other_paths_is_not_evidence`.
- Tests run: see top -> green. Changed an existing test, because the
  signature it monkeypatches changed:
  `test_bug_hunt_2026_09_11_comp_sync.py::test_a_move_interrupted_before_the_ledger_row_is_finished_on_redelivery`.
  Its stand-in `die(src, dest)` became `die(src, dest, *failed)`. The crash
  it simulates (RuntimeError, not OSError, out of the proxy step) still
  propagates, and the test still passes.
- Skew / deploy order: companion only. `detail` is the existing free-text
  field (<=512).
- OWED: none

## bug-comp-syncthing-2 - an UPLOAD-ONLY borrower still builds a borrowed lender, so the tray tells the editor to chase an admin who can never fix it
- Status: FIXED
- Verified as: verifier med-01 CONFIRMED. `_build_borrowed` never checked
  `_item_upload_only`. The collector shares a lender only for FULL borrower
  ticks (collector.py ~1416). The upload-only turn already skips the borrowed
  runs (sequencer ~2249), so the only effect was the `not-offered` problem
  sentence and the wrong rel attribution.
- Fix: `_build_borrowed` skips upload-only borrower items (sequencer.py
  ~1740-1800).
- Regression test: `test_an_upload_only_borrower_borrows_nothing` (HEAD: the
  lender is in `borrowed_lenders()`).
- Tests run: see top -> green.
- Skew / deploy order: companion only. The dashboard still sends the
  includes, and they are harmless.
- OWED: d-api, `dashboard/src/ccsync_dashboard/api.py` `_expand_includes`.
  Optional mirror for older companions: omit (or never expand) includes for
  a row whose `sync_mode` is upload_only. Not needed for correctness with
  this companion.

## bug-comp-syncthing-3 - a FULL borrower whose lender is ticked upload-only never gets the borrowed subtree
- Status: PARTIAL (companion half fixed; dashboard half OWED)
- Verified as: verifier med-01 CONFIRMED. Both `selected_rels` and the
  `lender in slug_to_item` test used every mode, and the dashboard's
  `covered` is computed from `fetch_selections` rows of any mode.
- Fix: in `_build_borrowed`, only FULL items cover. `selected_rels` and the
  lender test use `full_slugs`. A `covered` include whose lender is
  upload-only on this machine (`_covered_by_upload_only`) is run like any
  other include, so this works against today's dashboard. The upload-only
  lender stays in `borrowed_lenders()`, so the BorrowedFolderManager holds
  its folder restricted to the borrowed subtree. That is consistent with
  every other sequencer path, which already treats an upload-only slug as
  "not a folder of this machine" (`expected_folder_slugs`, `_unpause_all`,
  the startup verify). The collector already shares the lender with the
  borrower's device, because the borrower's FULL tick is in `borrowers_of`.
- Regression test: `test_a_full_borrower_of_an_upload_only_lender_gets_the_subtree`
  (HEAD: no includes). Control: `test_a_full_lender_still_covers_its_borrower`.
- Tests run: see top -> green.
- Skew / deploy order: either order. The companion fix works with an
  unchanged dashboard.
- OWED: d-api, `dashboard/src/ccsync_dashboard/api.py` `_expand_includes`
  (~2273). Build `selected` from FULL rows only (`r["sync_mode"]` in
  (None, '', 'full')), so an upload-only lender yields `covered: false` and
  enters `claimed` for the server-side longest-prefix dedupe. That lets an
  older companion (<= 0.9.78) receive the subtree too. The removal gate's
  "removing the lender strands a borrower" warning should still see the
  relationship for an upload-only lender. It already does, because the entry
  is still sent, only with covered false.

## bug-comp-syncthing-4 - a sequencer thread that outlives stop() can unpause a folder AFTER the halt paused it
- Status: FIXED
- Verified as: verifier med-01 CONFIRMED (timing race). `halt.engage` runs
  before `_stop_lanes()`. After stop()'s 15 s, `_verify_current_folder_unpaused`
  and the turn's own unpause have no halt check, and `accept_folder` ends in
  an unconditional unpause after writes that can take 30 s.
- Fix: `Sequencer._set_paused(slug, False)` refuses while `_is_halted()`.
  "Cannot tell" counts as halted. This is the one door for every sequencer
  unpause: verify, the turn, `_release_paused_folders`, `_unpause_all`
  (sequencer.py ~2032). `SyncthingAdmin.accept_folder(..., release_ok=None)`
  asks the predicate after `set_ignores`, before the final unpause, and
  leaves the folder paused if it says no. Its ignores are confirmed and the
  next turn after the halt releases it (syncthing_admin.py ~517-600). The
  new `release_guard()` passes it from the sequencer's `_maybe_auto_accept`
  and from the Shared/BorrowedFolderManager accepts, which already checked
  the halt before starting but not after the slow writes. `app.release_halt`
  clears the latch before it releases anything, so lifting a halt is
  unaffected (test_halt_holds_lane_c green).
- Regression test: `test_a_late_verify_does_not_release_a_folder_the_halt_paused`
  (HEAD: unpaused), `test_accept_folder_leaves_the_folder_paused_when_a_halt_arrived_meanwhile`
  (HEAD: TypeError) and `test_the_sequencer_hands_accept_folder_its_halt_predicate`.
- Tests run: see top -> green.
- Skew / deploy order: companion only.
- OWED: none

## bug-comp-core-5 - a manifest scan that overlaps a drive unplug reports zero files
- Status: FIXED
- Verified as: verifier med-04 CONFIRMED. `refresh_once` samples presence
  only before `scan_local_manifest`. `os.walk` has no `onerror`, and the
  result replaces the cache.
- Fix: `refresh_once` re-checks `_root_is_present()` after the scan and
  discards the result if the root went away, keeping the last good scan and
  conflicts (manifest.py ~343). An unanswerable probe is still "present", as
  before.
- Regression test: `test_a_scan_the_drive_vanished_under_is_discarded`
  (HEAD: the cache holds the zeros). Control:
  `test_a_scan_with_the_drive_still_there_replaces_the_cache`.
- Tests run: see top -> green, and test_manifest green.
- Skew / deploy order: companion only.
- OWED: none

## logic-sync-truth-2 - the per-kind manifest cap still causes phantom proxy downloads, the copy says "may undercount", and "Safe to close" can miss uploads
- Status: PARTIAL (nothing to change in c-sync's files; the rest OWED)
- Verified as: verifier med-09 CONFIRMED. The companion's side is correct as
  it stands: `manifest.py` caps each per-file list at 2000, sets
  `truncated`, and keeps the rollups (`n_originals`/`n_proxies`) EXACT. Those
  exact rollups are what lets the dashboard tell which list was capped
  (listed rows < rollup). No new wire key is needed. `ManifestProjectIn` is a
  plain BaseModel that would silently drop one anyway. The DOWN half is
  already fixed in this wave, uncommitted, by d-db's bug-dash-db-2
  (`db._proxy_manifest_capped`: a rollup-based count, no names). What
  remains: (b) the UP direction and "Safe to close", and (c) the copy.
- Fix: none in c-sync files.
- Regression test: n/a
- Tests run: n/a
- Skew / deploy order: dashboard-only when the OWED items land.
- OWED:
  - d-db, `dashboard/src/ccsync_dashboard/db.py` `fetch_sync_backlog`: add
    `_original_manifest_capped(conn, pair)`, the twin of
    `_proxy_manifest_capped` (held `n_originals` > listed `kind='original'`
    rows). For such a pair, emit an "up" signal even when the listed diff is
    empty, because today `if not n_files: continue` drops it. Examples: an
    `uncertain: true` up row with `n_files` 0, or a separate
    `capped_pairs` list.
  - d-ui, `dashboard/src/ccsync_dashboard/ui.py` `safe_to_close`: when any
    of the editor's pairs has an originals-capped manifest, never say "Safe
    to close". Say that it cannot tell, and name the machine and project.
    Also `dashboard/templates/partials/transfers.html:78`: word
    `manifest_truncated` per direction. For up, the uploads may be
    UNDERcounted. For down, the count is an estimate from the totals (per
    bug-dash-db-2). No em dash.

# Wave 2 ledger - c-sync (chunk 2 of 2)

New tests: 26 more in `companion/tests/test_bug_hunt_2026_09_24_w2_c-sync.py`
(45 in the file after the review round, which replaced logic-plans-5's
three tests with six; see that entry for their baseline). I built a baseline of the tree as chunk 1 left it (my
chunk-2 hunks reversed into a scratch `src/`; selection.py and
syncthing_lane.py from HEAD, which chunk 1 did not touch). I preloaded it
ahead of pytest's `pythonpath` and ran the file: all 17 chunk-2 fix tests fail
there. The 6 controls and all 19 chunk-1 tests pass there and here.

Tests run for the chunk (`companion\.venv\Scripts\python.exe -m pytest`):
- The new file plus test_rclone_lane, test_rclone_lane_races,
  test_rclone_express, test_lane_guard, test_syncthing_admin,
  test_syncthing_lane, test_borrowed_folders, test_shared_folders,
  test_selection, test_sequencer, test_sync_sequencer_policy,
  test_halt_holds_lane_c, test_sync_halt, test_repath_blocked_turn,
  test_bug_hunt_2026_09_11_comp_sync, test_bug_hunt_2026_09_11b_comp_sync,
  test_cr319_skip_ahead and test_sequencer_perf: 846 passed.
- test_app_contract, test_bug_hunt_2026_09_18_companion_core,
  test_reporter, test_settings_window, test_tray,
  test_bug_hunt_2026_09_11_comp_ui, test_bug_hunt_2026_09_11b_comp_ui and
  test_app: 898 passed.

Existing tests changed because behaviour I fixed changed:
- test_rclone_lane.py: three tally asserts pinned "a deletion is also a
  transfer" (bug-comp-rclone-5).
- test_borrowed_folders.py::test_restricted_ignore_lines_escapes_glob_specials:
  the posix form is now pinned with `windows=False` (bug-comp-syncthing-5).
- test_shared_folders.py: a healthy running folder now needs its marker, so
  three fixtures create `.stfolder`. The re-point test now expects
  `marker-missing` when there is nothing to carry (bug-comp-syncthing-7).

## logic-sync-truth-4 - the disk-floor park never clears on its own after the trash prune
- Status: PARTIAL (companion half already fixed in this wave; copy OWED)
- Verified as: verifier med-09 CONFIRMED (medium). This is the same
  mechanism as bug-comp-rclone-3, which chunk 1 of this group fixed in this
  wave (uncommitted). `RcloneLane._prune_free_target()` returns
  `clear_free_bytes` while the latch is parked. `_maybe_prune_trash` passes
  it as the pressure target, and the sequencer's `_prune_trash` reaches the
  lane only through `_maybe_prune_trash`. I re-read both and they hold. What
  is left is the dashboard chip copy, which is d-ui's file.
- Fix: none in this chunk (chunk 1: rclone_lane.py `_prune_free_target`,
  lane_guard.py `check`).
- Regression test: chunk 1's
  `test_a_prune_to_the_clear_threshold_releases_the_park` and
  `test_the_disk_pressure_prune_works_towards_the_clear_threshold_while_parked`.
- Tests run: see top -> green.
- Skew / deploy order: companion-only for the fix. The OWED copy is
  dashboard-only and independent of it.
- OWED: d-ui, `dashboard/src/ccsync_dashboard/ui.py` CHIP_HELP["disk"]
  (~357-360). ".ccsync-trash cannot prune while proxy download is stopped"
  is false, and has been since SYNC-16. Say instead that the trash is pruned
  under disk pressure, oldest first, until the drive has twice the floor
  free, which also restarts proxy download. The one exception is while the
  lane B breaker is tripped. No em dash.

## logic-sync-truth-3 - tray says "downloading N files" and pulses amber for ever when lane C has no connected peer
- Status: PARTIAL (lane C and the dashboard verdict fixed; tray half OWED)
- Verified as: verifier med-09 DOWNGRADE to low. The mechanism is real:
  `check_once` reports `syncing, queued=need` without reading the
  connection summary, and it never set a `progress_token`, so health.py's
  `lane_stall` always returned None for lane C. The narrow case the verifier
  left is also real: Syncthing's path alone fails while SFTP works, and the
  fleet chip stays amber.
- Fix: sync/syncthing_lane.py. `_refresh_connection_summary` now also keeps
  Syncthing's running byte total (`connection_bytes_total`: the `total`
  block, or the per-connection sum). Every syncing branch with files owed
  carries `progress_token = "c:<bytes>"`. Any transfer, and even a connected
  peer's keep-alives, moves the token. A lane with nobody to talk to holds
  still, so the dashboard's existing stall rule reds it after
  max(30 min, 3 rotations). When the connection list is readable and names
  no connected device, the detail reads "waiting: not connected to the
  server (N file(s) owed)" (`NO_PEER_DETAIL`). The state stays `syncing` on
  purpose, because the files are owed and the sequencer's turn logic reads
  that state. An unreadable connection list claims nothing: no token and no
  sentence.
- Regression test: `test_owed_files_with_no_peer_say_so_and_carry_a_still_token`
  (baseline: empty detail, token None) and
  `test_a_connected_lane_moves_its_token_and_claims_nothing_odd` (baseline:
  None != None fails). Control: `test_an_unreadable_connection_list_claims_nothing`.
- Tests run: see top -> green.
- Skew / deploy order: either order. `progress_token` is an existing
  optional report field (<=256 chars; "c:<int>" is short), and dashboard
  0.7.57 already stores it and runs the stall rule on it for any lane. A
  dashboard that ignored it would lose nothing.
- OWED: c-ui, `companion/src/ccsync_companion/tray.py` `_sync_line` /
  `compute_overall_color` / `should_pulse`. When lane C is the only lane
  claiming work and its status detail starts with
  `sync.syncthing_lane.NO_PEER_DETAIL` (or app's `_lane_peer_states()` says
  lane C False), stop pulsing and show "Sync: waiting, not connected to the
  server (N owed)" rather than "downloading N files". No em dash.

## bug-comp-rclone-4 - stray-project scan and express attribution compare paths without NFC folding
- Status: FIXED
- Verified as: read both sites. `_project_rel_for_path` lower-cases
  watchdog path parts against the dashboard's rels. `_refresh_stray_projects`
  normcases `scan_project_markers` directories (read off the disk) against
  paths built from the rels. Neither folds Unicode, while every other
  comparison in the file uses `nfc_key` (CR-90, GOTCHAS §17). A Mac's NFD
  directory name is therefore a mismatch.
- Fix: sync/rclone_lane.py. Both sides of both comparisons go through
  `nfc_key` before the case fold (`_project_rel_for_path` ~2385/2391,
  `_refresh_stray_projects` ~3437/3446). Comparison only: the returned rel
  is the dashboard's spelling, and the reported stray path is the disk's.
- Regression test: `test_express_attributes_a_macs_nfd_path_to_its_nfc_project`
  (baseline: None) and `test_a_ticked_project_spelled_nfd_on_disk_is_not_a_stray`
  (baseline: count 1). Control: `test_a_genuinely_unticked_project_is_still_a_stray`.
- Tests run: see top -> green (incl. test_rclone_express).
- Skew / deploy order: companion only.
- OWED: none

## bug-comp-rclone-5 - a trashed file is counted as "transferred" as well as deleted
- Status: FIXED
- Verified as: read `RcloneRunTally.feed_record`. `transferred += 1` ran
  before the deletion test, so every "Moved into backup dir" / "Deleted"
  record was both. `_last_run_moved = transferred + deleted` (whose comment
  says trashed files count once) double-counted, and the lane detail
  "transferred N file(s)" reached the tray and the fleet grid. The existing
  test comment calling it "rclone's per-file line count" does not match
  rclone, whose own "Transferred:" figure excludes deletions.
- Fix: sync/rclone_lane.py `feed_record` (~2143-2163). A deletion counts only
  as `deleted`, and `transferred` counts arrivals only. `_last_run_moved`
  still sees a trash-only pass as work (deleted > 0), so the idle backoff is
  unchanged.
- Regression test: `test_a_trash_only_pass_transfers_nothing` (baseline: 12,
  12) and `test_a_mixed_pass_counts_each_file_once` (baseline: 3, 2).
- Tests run: see top -> green. Three asserts in test_rclone_lane.py updated
  (listed at the top).
- Skew / deploy order: companion only. `transferred` in the lane detail is
  free text.
- OWED: none

## bug-comp-syncthing-5 - borrowed-folder negations are escaped with backslashes, which Syncthing on Windows reads as path separators
- Status: FIXED
- Verified as: `escape_ignore_glob` put `\` before `[ ] { } * ?` on every
  platform. Syncthing's ignore docs say `\` escaping is not supported on
  Windows, because it is the path separator there. `[ ] { }` are legal in
  Windows names, so `Interviews [raw]` produced a negation that matched
  nothing, and the trailing `**` kept the subtree out while the list read
  back "confirmed". NOT reproduced against a real Syncthing (brief rule 9:
  no live process). The fix does not depend on how Windows treats `\`,
  because it emits no `\` there.
- Fix: sync/syncthing_admin.py. `escape_ignore_glob(rel, windows=None)` and
  `restricted_ignore_lines(subs, windows=None)`: on Windows (`os.name ==
  "nt"`, the platform of the Syncthing that reads this device-local file),
  `[`, `{` and `}` become the one-character classes `[[]`, `[{]` and `[}]`.
  `]` outside a class is text, and `* ? \` cannot occur in a Windows name.
  The posix form is unchanged. A lender already written in the old form
  self-heals: `_ensure_ignores` finds the new negation missing and rewrites
  the list.
- Regression test: `test_windows_negations_escape_with_classes_not_backslashes`
  (it also proves the class form matches the literal name under glob rules,
  via fnmatch) and `test_the_default_follows_this_machines_platform`
  (baseline: TypeError / backslashes on nt). Control:
  `test_a_plain_name_is_unchanged_on_both_platforms`.
- Tests run: see top -> green.
- Skew / deploy order: companion only. A Windows machine rewrites each
  bracketed lender's .stignore once (one config write), then it is steady.
  Still worth a 5-minute spike on a scratch Syncthing on Windows, since
  gobwas's class parsing is read from its lexer, not measured.
- OWED: none

## bug-comp-syncthing-6 - the cached plan is not keyed by editor
- Status: FIXED
- Verified as: `selection.json` held `{fetched_at, response}` only.
  `get()` falls back to `load_cached()` on every failed or identity-less
  fetch, and `_startup_unpause` adopts and unpauses from it. Only the
  in-memory TTL was editor-keyed, and nothing deletes the file on sign-out.
- Fix: selection.py. `_write_cache(response, editor)` writes `"editor"`, and
  write-on-change now compares (response, editor), so an identical plan for
  a new person still re-stamps the owner. `load_cached(any_editor=False)` /
  `_load_cached_response` refuse a cache whose editor is known and differs
  from the signed-in one. They log once per pair. Both names are needed, so
  a pre-key cache and the no-identity-yet moment (SYNC-110's restart case)
  read as before. This covers `get()`, `_startup_unpause`, the halt release
  and `project_roots_result`'s cache arm. sync/sequencer.py:
  `halt_folder_ids_to_repause` passes `any_editor=True` (falling back on
  TypeError for doubles), because it only PAUSES, and the previous person's
  folders are still configured here.
- Regression test: `test_the_next_person_never_runs_the_previous_persons_cached_plan`
  (baseline: KeyError 'editor' / A's plan served),
  `test_an_identical_plan_for_a_new_person_still_rewrites_the_owner` and
  `test_the_halt_repause_still_pauses_the_previous_persons_folders`
  (baseline: []). Controls: `test_the_same_person_still_falls_back_to_the_cache`
  and `test_a_cache_from_before_the_key_is_still_read`.
- Tests run: see top -> green (incl. test_selection).
- Skew / deploy order: companion only. The key is local and additive. A
  downgraded companion ignores it.
- OWED: none

## bug-comp-syncthing-7 - re-pointing a shared asset folder neither moves its contents nor creates the path/marker, and reports "repaired"
- Status: FIXED
- Verified as: `_reconcile_one` PATCHed the new path with no pause, no
  SYNC-6 guard, no mkdir and no move, then decided the unpause from the
  pre-PATCH dict. The next pass saw matching paths and answered "ok", which
  cleared any problem. Syncthing's own rule is to move the folder, including
  .stfolder, before changing the path. Its marker exists so that an empty
  directory is never read as "everything was deleted".
- Fix: sync/shared_folders.py. A new `_repoint` (the twin of the borrowed
  manager's) checks `_mkdir_allowed`, pauses, moves the old directory with
  its marker when it exists and the new one does not (`move_dir`, which the
  sequencer now passes as `_default_move`), mkdirs, then PATCHes. The unpause
  is decided from `paused_now`. A running (or just re-pointed) folder whose
  `markerName` (default `.stfolder`) is absent reports the new
  `marker-missing` problem outcome on every pass, with its own tray
  sentence, until the marker exists. The marker is never created here, for
  the reason above. A refused re-point returns "error" and changes nothing.
- Regression test: `test_a_repointed_library_carries_its_files_and_marker`
  (baseline: TypeError move_dir),
  `test_a_repoint_with_nothing_to_carry_is_a_problem_until_the_marker_exists`
  (baseline: "repaired", then "ok"),
  `test_a_repoint_onto_an_absent_root_changes_nothing` (baseline: PATCHed)
  and `test_the_sequencer_hands_the_shared_manager_a_mover`.
- Tests run: see top -> green. Three fixtures and one expectation changed in
  test_shared_folders.py (listed at the top).
- Skew / deploy order: companion only. A machine whose LUT folder is ALREADY
  running without a marker (i.e. broken today) will now show the problem
  sentence. That is truthful, not a regression.
- OWED: none

## logic-plans-5 - the companion's "the dashboard does not know this machine" untick fallback can never fire
- Status: FIXED (companion); the earlier dashboard OWED is WITHDRAWN and
  replaced by an optional one (below)
- Verified as: `api_untick` (api.py ~2675) never checks `?machine=`
  (api_tick 404s at ~2628). A machine-scoped DELETE that matches no row
  answers 200 with `changed: false` and that machine's resolved view. The
  companion's fallback keyed on 404 only, so it said "unticked" and the tray
  deleted the local copy while the tick stood under the old name.
- Fix (as revised in the review round): selection.py `untick`. The
  `_machine_unknown_to` widening is gone. After the machine-scoped DELETE
  (and the existing 404 / unassigned-bucket fallbacks, which are unchanged),
  an answer whose `changed` is exactly False and whose `selection` does not
  list the slug (`_removed_nothing`) means the tick this computer synced by
  is under a key its hostname cannot reach. The companion then reads the
  person's union (`_person_holds`, GET with no `?machine=`, cache untouched).
  Ticked nowhere: "unticked", and the local delete goes on (the tray's plan
  was stale, and nothing can bring the project back). Ticked for another
  computer: refused with a sentence naming this computer's name and the
  rename case. Cannot tell: refused. Nothing is widened, and nothing is
  deleted on a refusal. `app.remove_project_from_machine` already stops
  before any delete when untick returns False. An answer with no `changed`
  (older dashboard) or an unreadable body keeps the old "unticked" answer
  and asks nothing more.
- Regression test (all in `test_bug_hunt_2026_09_24_w2_c-sync.py`, built
  from the dashboard's real answer in the SYS-18a window: `machines` names
  BOTH computers, `changed: false`, the tick visible only in the union):
  `test_a_renamed_pc_whose_tick_stands_under_its_old_name_is_refused`,
  `test_a_forgotten_hostname_is_not_widened_to_the_person`,
  `test_cannot_tell_whether_another_computer_holds_it_is_refused`.
  Controls: `test_a_tick_already_gone_everywhere_is_still_unticked`,
  `test_an_answer_without_changed_is_not_evidence`,
  `test_a_machine_scoped_removal_that_worked_asks_nothing_more`. Against
  HEAD's selection.py (a scratch copy of the package with the test file run
  from it, because pytest's `pythonpath = ["src"]` otherwise wins): the three
  fix tests fail (HEAD answers "unticked"), `already_gone` fails only on its
  "asked the union once" assert, and the other two controls pass.
- Tests run: test_bug_hunt_2026_09_24_w2_c-sync.py + test_selection.py: 102
  passed. test_app.py -k "remove or untick": 5 passed.
- Skew / deploy order: either order. It reads `changed` and `selection`,
  which dashboard 0.7.57 already sends, and the person-wide GET the
  companion has always been allowed.
- OWED (optional, d-api): do NOT add the 404 this entry first asked for. A
  renamed PC's new name is registered, so it would not fire, and for a
  forgotten computer it would make companions <= 0.9.78 widen the untick to
  the whole person. If d-api wants to protect companions <= 0.9.78: in
  `api_untick`, when the actor is `companion:<editor>`, a `?machine=` was
  given, nothing was removed and the slug is not in that machine's view,
  answer 409 with a plain sentence (old companions then say "could not
  untick ... nothing was deleted"). Keep the signed-in UI's untick
  idempotent (200).
- Review round (2026-09-25): the reviewer was right on both counts. (1)
  `_register_machine` upserts the new hostname even when it refuses the
  adoption, so `db.machines_of` names it and `_machine_unknown_to` never
  fired in the finding's own scenario. The old regression test built a view
  the dashboard does not send (hostname missing from `machines`), so it only
  covered the seconds before a first report. (2) Widening to the person
  would also untick every other computer for a just-forgotten machine
  (CR-76). The widening was removed. The hunter's second suggestion ("no
  change and the slug absent is nothing to untick here, not success") is
  implemented, with one refinement: before refusing, the person's union is
  asked. If nothing holds the tick, the stale-plan case still frees the disk.
  The tests were rewritten on the real answer shape.

# Owed round (2026-09-25) - c-sync

This round covers items other groups left for c-sync's files. The new tests
are appended to `companion/tests/test_bug_hunt_2026_09_24_w2_c-sync.py` under
"OWED round" (17 tests).

HEAD check: I took `git show HEAD:` copies of drive_reminder.py,
file_moves.py, selection.py, sync/base.py and sync/syncthing_lane.py into a
scratch `src/`, put today's tests dir beside it, pointed `PYTHONPATH` at it,
and picked the owed tests with `-k`. 11 fail there. The 4 controls pass
there and here:
- the legacy-record reminder
- the wedged reminder
- plain-move-never-overwrites
- the pure bucket still widening

A 12th test, `test_an_owed_upload_still_recurs`, is also a control. It fails
on HEAD only because HEAD has no `lanes=` keyword.

Existing tests edited because the behaviour they pin changed:
- `test_drive_reminder.py::test_begin_after_clear_is_a_fresh_episode` now
  begins with "3 uploads". A "3 other files" episode no longer starts the
  recurring thread.
- The expected detail is now "nothing at the old path on this computer" in
  `test_bug_hunt_2026_09_11_comp_sync.py`,
  `test_bug_hunt_2026_09_18_companion.py` and this group's own w2 file
  (`test_a_failed_row_for_other_paths_is_not_evidence`).
- `test_bug_hunt_2026_09_18_companion.py::test_the_move_command_after_lane_b_followed_it_still_relinks_resolve`
  now asserts "proxy download" where it asserted "lane B".

Tests run (companion venv, from `companion/`):
- 1553 passed across these files: the w2 c-sync file, test_drive_reminder,
  test_file_moves, test_selection, test_syncthing_lane,
  test_sweep_2026_09_04_copy, test_bug_hunt_2026_09_11_comp_sync,
  test_bug_hunt_2026_09_18_companion,
  test_bug_hunt_2026_09_18b_companion_core,
  test_bug_hunt_2026_09_11_comp_app, test_bug_hunt_2026_09_11b_comp_app,
  test_settings_window, test_tray, test_bug_hunt_2026_09_24_w2_c-ui,
  test_shared_folders, test_sequencer, test_no_em_dash,
  chaos/test_fault_injection_wave2, test_halt_holds_lane_c, test_sync_halt,
  test_syncthing_supervisor and test_rclone_lane.
- The one warning comes from test_sequencer's own deliberate "startup
  unpause exploded" thread. It is not from these changes.
- `test_app.py test_app_contract.py test_config.py -k "drive or untick or
  remove or move or reminder or lane_c or direction"`: 39 passed.

## logic-sync-truth-6 (owed from c-ui) - the drive reminder repeats for downloads; lane C's direction is only in its words
- Status: FIXED (both the required part (b) and the optional direction field)
- Verified as: `drive_unfinished.json` did NOT keep the lanes, so there was
  nothing to gate on as it stood.
  - `begin()` took only the summary string.
  - `_write_record` stored summary/sentence/kind/since.
  - `Unfinished.lanes` existed but never left `app._unfinished_before_pause`,
    which hands `begin()` only `work.summary()`.
  The rest of c-ui's reading is right: `_loop` recurred for any unfinished
  episode, lanes B and C included.
- Fix (b), `drive_reminder.py`:
  - `UPLOAD_LANE` (~95) and `owes_an_upload(lanes, summary)` (~109) decide
    whether an episode recurs. Known lanes decide. With no lanes, the summary
    is read back through `_LANE_NOUNS`, the module's own producer of that
    sentence:
    - "N upload(s)" recurs.
    - A summary that names only proxy downloads or other files does not.
    - "N file(s)" from a lane this module cannot name still recurs. That is
      the CR-92 behaviour and the safe direction.
    - The "(2.3 GB left)" clause is not mistaken for a lane.
  - `begin(summary, announce=True, lanes=None)` (~328) records `_lanes` and
    `_recurs`. The record now carries `"lanes"` (~568), and
    `resume_remembered` passes them back. A 0.9.77 record has no lanes and
    is read by its summary.
  - `_start_thread` (~515) starts no cadence for a non-recurring episode, and
    `mute_episode` starts no snooze thread for one.
  - `reminders_muted` is True for a non-recurring episode. Settings then
    shows its existing line ("Reminders about this drive are off until it is
    plugged back in.") instead of two buttons for a reminder that is not
    coming.
  - The FIRST warning is unchanged.
  - The one reminder at startup after a restart is kept for a download-only
    episode. It stands in for the "Sync paused" balloon: app.py suppresses
    that balloon when `resume_remembered` returns True.
  - The wedged-drive state episode (SYNC-120) always recurs.
  - The caller needed no change: app.py's bare summary is enough.
- Fix (optional):
  - `sync/base.py` ~60 adds `LaneStatus.direction`: "up", "down", or ""
    (the default).
  - `syncthing_lane.py` ~903 sets it in the syncing branch: "" with no peer,
    "down" when our need is non-zero, "up" when only the server's need of us
    is.
  - It is in-process only: reporter.py builds the wire dict field by field.
    `LaneStatus(**vars())` copies keep it.
- Regression tests:
  - Fail on HEAD:
    - `test_a_download_only_episode_warns_once_and_does_not_recur`
    - `test_the_bare_summary_app_py_passes_is_enough_to_tell`
    - `test_the_lanes_survive_a_restart_and_keep_the_decision` (reads
      `lanes` from the JSON record)
    - `test_a_lane_this_module_cannot_name_keeps_reminding`
    - `test_a_snooze_on_a_download_only_episode_starts_no_cadence`
    - `test_lane_c_names_its_direction`
  - Controls:
    - `test_an_owed_upload_still_recurs`
    - `test_a_record_from_before_lanes_were_kept_is_read_by_its_summary`
    - `test_the_wedged_drive_reminder_is_unchanged`
- Skew / deploy order: companion only, no wire change. A 0.9.77 record is
  read by its summary, and an older build ignores the new `lanes` key.
- OWED (optional, reported only):
  - c-ui, `tray.py` `_lane_direction`: read `status.direction` for lane C.
    Keep the sentence match as the fallback when the field is empty. Then a
    reword in syncthing_lane no longer changes the tray's counts.
  - c-app, `app.py` `_unfinished_before_pause`: optionally pass
    `lanes=work.lanes` to `begin()` rather than relying on the summary
    read-back.

## ui-copy-4 (owed from c-ytdl) - file-move answers said "lane B" and "this machine"
- Status: FIXED
- Verified as: these strings are the `detail` of `file_moves_applied`, shown
  in the project page's MOVES history. Nothing parses them:
  - Semantics ride on `state`.
  - The only string compared is `DETAIL_NOT_SYNCED_HERE` (app.py ~8644),
    which is unchanged.
  - The dashboard's test_file_moves.py:506 uses "applying it on this
    machine" only as input data.
  On HEAD, the shared vocabulary scan (`test_sweep_2026_09_04_copy._sentences`
  / `_WORD_RE`) flagged 11 sentences in file_moves.py, not only the three
  named.
- Fix:
  - Every visible file_moves.py sentence now says "this computer".
  - The three "lane B had already moved ..." answers now say "proxy download
    had already moved ... on this computer" (c-ytdl's suggested wording).
  - The scan now finds nothing in file_moves.py.
- Regression test: `test_the_file_move_answers_say_computer_not_machine_or_lane`
  applies the shared scan to file_moves.py and checks the live answer. It
  fails on HEAD.
- Skew / deploy order: companion only. Rows written by older builds keep
  their wording.
- OWED (reported only): c-ui, the owner of the shared
  `companion/tests/test_sweep_2026_09_04_copy.py`: add "file_moves.py" to
  `MODULES`. It passes the scan now.

## bug-dash-api-2 (owed from d-api) - the companion kept a moved proxy's OLD stem
- Status: FIXED
- Verified as: `move_proxy_siblings` targeted
  `dest.parent/Proxy/<candidate.name>`. Two failures followed:
  - A cross-folder rename kept `Proxy/<old stem>` locally. With d-api's fix
    the NAS now has `Proxy/<new stem>`, so lane B downloads the new one and
    trashes the old one.
  - A same-folder rename targeted the proxy itself. `exists()` was true, so
    nothing moved.
- Fix, `file_moves.py` ~287:
  - The target is `dest.stem + candidate.suffix`.
  - Exception: when the two stems differ only in Unicode form (a Mac's NFD
    proxy against the dashboard's NFC `to_rel`), the proxy keeps its own
    bytes. CR-90 says never re-spell what is on disk. This keeps
    comp-sync-18's `test_a_decomposed_proxy_follows_its_original` green.
  - A target that is the candidate's own path is skipped.
  - A target that exists AND is the same disk file goes through
    `_rename_case_only`. This is a case-only stem change on a case-folding
    disk. The new helper `_is_the_same_disk_file` uses `os.path.samefile`
    and never raises.
  - Any other existing target is still never overwritten. The check asks the
    disk, not the folded names, so a case-sensitive disk holding two real
    files is safe.
  - The 4b trash call site is unchanged. Its `dest` is named like `src`.
    Only a case or spelling difference between the original's stem and the
    proxy's could re-spell a proxy inside the trash, which is harmless.
- Regression tests:
  - Fail on HEAD: `test_a_renaming_move_renames_the_proxy`,
    `test_a_same_folder_rename_moves_the_proxy_too`.
  - New: `test_a_case_change_through_a_move_renames_the_proxy_spelling`.
  - Control: `test_a_plain_move_keeps_the_proxy_name_and_never_overwrites`.
- Skew / deploy order: either order.
  - With d-api's dashboard fix, both sides now agree on `Proxy/<new stem>`.
  - Against an older dashboard, the NAS keeps the old stem for a renaming
    move, so lane B downloads that one and trashes ours. That is the same
    one-download cost d-api described, in the other direction.
- OWED: none.

## logic-plans-1 (owed from d-db) - the untick widening skew belt
- Status: FIXED
- Verified as: `selection.untick` widened to the person-wide DELETE on any
  `ok` machine-scoped answer that still listed the slug.
  - A dashboard without d-db's fix answers that way, with `changed: true`,
    when this computer's last project came from the bucket. It materialised
    the bucket, removed this computer's copy and fell back to the bucket.
  - Widening then deleted every other computer's row for the project
    (comp-lane-c-2).
- Fix, `selection.py`:
  - A new branch comes first (~553). If `changed` is truthy and the slug is
    still listed, `untick` refuses and returns `(False, "the dashboard still
    lists it in this computer's sync plan after the untick. Untick it on the
    dashboard's sync plans page")`.
  - On that refusal nothing is widened and nothing is deleted
    (app.remove_project_from_machine stops on False). The plan TTL is zeroed
    so the tray refetches.
  - The existing widening branch (~573) now fires only when `changed` is
    false or absent: the pure bucket case, or a dashboard too old to send
    `changed`.
- Regression tests:
  - `test_a_changed_answer_that_still_lists_the_project_is_not_widened`
    fails on HEAD, which issues the second, person-wide DELETE.
  - Control: `test_the_pure_bucket_answer_still_widens` (`changed: false`,
    and `changed` absent).
  - test_selection.py's existing widening test sends no `changed` and still
    passes.
- Skew / deploy order: either order.
  - With d-db's dashboard fix, the refusal branch should not be reached,
    because the bucket drains.
  - Against 0.7.57/0.7.58, an untick that would have widened to the whole
    person is now refused with "untick it on the dashboard". That is the
    safe direction for a removal.
- OWED: none.

## logic-plans-4 (owed from d-db) - per-file manifest lists for borrowed subtrees
- Status: DEFERRED (not done; the reason and the decision needed are below)
- Verified as: `scan_local_manifest` builds per-file lists only for
  `_selected_project_rels()`, which is the keys of `sequencer.rel_to_slug`
  (manifest.py ~173, app.py ~4389). The owed item asks for the keys of
  `rel_to_slug_with_borrowed` too. Doing that here has two problems.
  1. It does not serve the scenario it was owed for, "a borrower that has
     since unticked the borrowing project".
     - Once P is unticked, `_build_borrowed` drops P's borrowed rels.
       `rel_to_slug_with_borrowed` then no longer holds the lender subtree,
       so no per-file list would be built for it either. That is the same
       14-day decay the hunter describes for ordinary projects.
     - A borrower that still ticks P is already reached through its plan by
       d-db's `file_move_target_machines` fix, and that covers the hunter's
       failure scenario.
  2. The manifest is keyed by PROJECT rel. The dashboard reads each key as
     "this machine's whole copy of that project": editor_media_project and
     editor_media, and the up/down totals and uploads-owed queries at db.py
     ~9921-9965. A borrowed rel is a SUBFOLDER of the lender.
     - Sent as its own key, it is a non-project key the dashboard would
       slugify or drop.
     - Folded under the lender's rel, it makes a borrower look like a
       partial holder of the whole lender project, on the lender's page and
       in the uploads-owed counts.
     Either way it is a d-db/d-ui design change, not a companion-side fix.
- Fix: none.
- Decision needed (d-db + owner): whether a borrower's files should be
  reported at all. If yes, one option is a separate optional wire section,
  for example `borrowed_media: {lender_rel: {sub_rel, originals}}`. The
  dashboard would write it as editor_media rows for the lender slug WITHOUT
  an editor_media_project row. That feeds the editor_media arm of
  `file_move_target_machines` and nothing that computes totals. The
  companion half is small once that contract exists.
- OWED (reported only): d-db, the decision above.

### Review round (2026-09-25) - logic-sync-truth-6
- Reviewer: the fix treated every lane C episode as a download, and lane C
  is two-way. It carries every non-video file UP (SPEC.md: its stignore
  drops only video and Proxy), so a recorder WAV or project file whose only
  copy is on the pulled drive got one warning and no reminders. The
  reviewer is RIGHT. Two parts of it:
  - `unfinished_work` never read `LaneStatus.direction`; every lane C item
    was "other files" under the lane name `lane_c_syncthing`, and
    `owes_an_upload` counted only lane A as an upload.
  - A second gap the reviewer did not name: `syncthing_lane` set
    direction "down" whenever our own need was non-zero, so an upload owed
    at the same moment as a download was hidden.
- Fix:
  - `sync/syncthing_lane.py` (the syncing branch): direction is "both"
    when our need and the server's need of us are both non-zero. No peer
    stays "". `sync/base.py`'s field comment names "both".
  - `drive_reminder.py`: lane C's key in `Unfinished.lanes` carries its
    direction (`lane_c_syncthing:up` / `:down`; plain `lane_c_syncthing`
    for "" or "both"), and each has its own noun: "other file upload(s)",
    "other file download(s)", and the old "other file(s)" for an unknown
    direction.
  - The rule is inverted to the safe side: an episode recurs UNLESS every
    lane is a known download (`DOWNLOAD_LANES` = lane B + lane C down). A
    lane C upload, a lane C with no known direction, and a lane added
    later all recur.
  - The summary read-back (app.py still passes only `work.summary()`)
    follows the same rule: it recurs unless every item is a download noun,
    so the noun alone carries the direction. A 0.9.77 record saying
    "N other files" now RECURS (it may be an upload), where the first
    round read it as a download.
- Regression tests (appended to the w2 c-sync file):
  - `test_a_lane_c_upload_keeps_reminding` - the reviewer's case
    (syncing, direction "up", queued 0), with lanes and with the bare
    summary. Failed on the first-round code (summary "1 other file",
    lanes `["lane_c_syncthing"]`, no cadence).
  - `test_a_lane_c_episode_with_no_known_direction_keeps_reminding`
    ("" and "both", plus a legacy "other files" summary).
  - `test_a_lane_c_download_alone_still_does_not_recur` (the control).
  - `test_the_lane_c_direction_survives_a_restart`.
  - `test_lane_c_names_its_direction` gains the "both" case.
  - Edited honestly: the two first-round tests that meant a lane C
    DOWNLOAD now say `direction="down"` (they had relied on "" being read
    as a download), and `test_a_lane_this_module_cannot_name_keeps_reminding`
    now expects "other files" to recur and uses the download noun for the
    non-recurring case.
- Tests run: w2 c-sync, test_drive_reminder, test_syncthing_lane, test_tray,
  test_settings_window, test_sequencer, test_halt_holds_lane_c,
  test_sync_halt, test_no_em_dash, test_bug_hunt_2026_09_11_comp_sync,
  test_bug_hunt_2026_09_18_companion, test_bug_hunt_2026_09_24_w2_c-ui,
  test_file_moves, test_selection: 939 passed. test_app,
  test_bug_hunt_2026_09_18b_companion_core, the two 09-11 comp_app files,
  chaos/test_fault_injection_wave2: 481 passed.
- Skew: companion only. `direction` is still in-process only. A record
  written by the first-round code with `lanes: ["lane_c_syncthing"]` is
  now read as unknown direction and recurs (safe side).
- OWED (optional, reported only, unchanged): c-ui's `tray.py`
  `_lane_direction` may read `status.direction`; it must treat "both" as
  both. c-app may pass `lanes=work.lanes` to `begin()`.

### Review round (2026-09-25) - ui-copy-4, bug-dash-api-2, logic-plans-1, logic-plans-4
- No reviewer problem was raised. Unchanged from the owed round above.
