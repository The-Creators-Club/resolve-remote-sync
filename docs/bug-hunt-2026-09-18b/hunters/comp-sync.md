# comp-sync - the companion's sync package, file moves, drive/manifest/root guards

Files read (with approximate coverage):
- `git diff` of the whole territory, hunk by hunk: `companion/src/ccsync_companion/file_moves.py`
  (+173, ~100%), `sync/rclone_lane.py` (+234, ~100% of the diff, plus the
  surrounding `_relocate_trashed` / `_move_out_of_trash` / stall-watchdog /
  `_backup_dir` / `_trashed_this_pass` bodies), `sync/server_locate.py` (100%),
  `sync/syncthing_lane.py` (100% of the diff plus `_heal_missing_paths` and `poll()`).
- Both ends of every wire the diff touches: `app.py` `_synced_project_rels`,
  `_project_rel_for_slug` / `_borrowed_rel_for_slug`, `_apply_file_moves`,
  `_on_moved_clip_missing` / `_show_moved_clip_dialog`, `_lane_stall_record`,
  lane construction (~2420-2520); `sync/sequencer.py` `rel_to_slug`,
  `rel_to_slug_with_borrowed`, `_update_known_selection`, `_build_borrowed`;
  `sync/lane_guard.py` `prune_trash`; dashboard `locate.py`, `db.pending_file_moves`,
  `db.record_file_move`, `api.py` move route, `collector.py` hand-move detection
  (the `is_dir=True` case).
- Tests: the whole new res-fleet-3 block and the comp-sync-1 / live-1 / comp-sync-4
  blocks in `tests/test_file_moves.py`, `tests/test_rclone_lane.py`,
  `tests/test_lane_watchdog.py`.
- Skimmed only (unchanged this pass): `selection.py`, `drive_reminder.py`,
  `drive_swap.py`, `manifest.py`, `root_guard.py`, `sync/repath.py`,
  `sync/borrowed_folders.py`, `sync/shared_folders.py`, `sync/syncthing_admin.py`,
  `sync/syncthing_supervisor.py`, `sync/base.py`.

Tests run:
`companion\.venv\Scripts\python.exe -m pytest tests/test_file_moves.py tests/test_rclone_lane.py tests/test_syncthing_lane.py tests/test_lane_guard.py tests/test_lane_watchdog.py -q` -> 331 passed.
Plus three ad-hoc scripts run from the companion venv (scratchpad, outside the repo); their output is quoted in the findings.

## Findings

### comp-sync-1 - a machine with an empty plan now trashes every file it is told to move, including a move WITHIN the project it is holding
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/file_moves.py:346-380` (`_dest_is_synced_here`) and `:464-490` (the section 4b branch in `apply_move`); the caller is `companion/src/ccsync_companion/app.py:1365-1384` (`_synced_project_rels`).
- What: res-fleet-3's new test asks only about the DESTINATION. `_synced_project_rels`
  returns `[]` (not `None`) for any managed companion whose sequencer has an empty
  selection, and `_dest_is_synced_here` answers False for every path against an empty
  list, so `apply_move` takes the 4b branch for EVERY move - including a move whose
  source and destination are the same project, the one this machine is holding the
  file in. The file is renamed into `.ccsync-trash`, `paths=None` means Resolve is
  never relinked, and `ok=True` means the dashboard records the machine as having
  followed. `lane_guard.prune_trash` then deletes the batch on its age rule, so this
  ends in permanent loss of a local original on a machine that may be its only holder.
- Failure scenario: an editor between projects, or one whose admin has just cleared
  the ticks (`editor_media` rows and therefore `file_move_targets` survive an untick,
  and `api.py:2849` targets every machine holding the file regardless of ticks). The
  admin files `B-roll/A001.braw` into `B-roll/Selects/` on the server. That machine
  puts its copy in `.ccsync-trash`, says "trashed locally, destination not synced
  here", never relinks, and the retention rule deletes the copy later.
- Evidence: run from the companion venv against the working tree, with an
  intra-project move and `project_rels=[]`:
  ```
  empty plan -> True 'trashed locally, destination not synced here' None
  at new path: False
  trashed: ['...\Creators_Club\.ccsync-trash\20260918-142229\Projects\2026\Base Drone\B-roll\A001.braw']
  proxy left behind: True
  ```
  (the Proxy/ sibling is also orphaned: the 4b branch does not call
  `move_proxy_siblings`, so lane B trashes the proxy separately next pass.)
  Every new test in `test_file_moves.py` passes `_plan(DRONE, ...)`, i.e. the SOURCE
  project is always in the plan; no test covers an empty plan or a same-project move.
- Ledger: new (res-fleet-3's companion half); it also collides with today's owner
  decision that "a computer with nothing ticked is fine and must never read as a fault
  anywhere".
- Suggested fix: apply 4b only when the SOURCE was synced here and the destination is
  not (a machine holding a file outside its plan proves the plan is not the whole truth
  on that disk), and never when `to_project_rel == from_project_rel`. Treat an empty
  plan like `None`. Carry the proxy siblings into the trash with the original.

### comp-sync-2 - the 4b trash path becomes the "RELINK IT" destination, so the editor is invited to point Resolve into `.ccsync-trash`
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/file_moves.py:477-479` (`record_intent(move, src, trash)`) with `:696-701` (`record()`'s path inheritance) and `:786-817` (`moved_to`); consumed at `companion/src/ccsync_companion/app.py:8390-8443` (`_on_moved_clip_missing` / `_show_moved_clip_dialog`).
- What: the 4b branch deliberately returns `paths=None` ("a relink to the trash would
  be worse than the offline clip"), but it first writes an INTENT row whose `new_local`
  IS the trash path, and `record()` with `paths=None` copies `old_local`/`new_local`
  forward from the previous row. The finished row therefore carries
  `new_local = <local_root>\.ccsync-trash\<stamp>\...`, and its state is
  `not_synced_here`, which `moved_to()` does not skip (it skips `applying` only). The
  watcher's RES-10 hook then offers the one-click relink at that path.
- Failure scenario: the editor opens the project, the clip is offline, the tray says
  "CCSync can repoint Resolve to where it is now", the dialog says "It is now at:
  ...\.ccsync-trash\20260918-142541\... Your copy has already been moved to match",
  and RELINK IT writes that path into the media pool through `replace_clip`.
  `prune_trash` deletes the batch on its age rule and every relinked clip is
  permanently offline, pointing at a directory that no longer exists.
- Evidence: run from the companion venv:
  ```
  state: not_synced_here | old_local: ...\Projects\2026\Base Drone\B-roll\A001.braw
                         | new_local: ...\.ccsync-trash\20260918-142541\Projects\2026\Base Drone\B-roll\A001.braw
  moved_to offers relink to: ...\.ccsync-trash\20260918-142541\Projects\2026\Base Drone\B-roll\A001.braw
  ```
  `_moved_destination_is_there` passes (the file really is at the trash path), so the
  comp-sync-b-2/2026-09-11b guard does not stop it either.
- Ledger: new (res-fleet-3); note the copy "Your copy has already been moved to match"
  is untrue in this branch.
- Suggested fix: either do not write an intent row for 4b, or clear the paths
  explicitly on the completion record (`paths=("", "")`), and make `moved_to()` and
  `_relink_pending_moves()` skip `STATE_NOT_SYNCED_HERE` the way they skip
  `STATE_APPLYING`.

### comp-sync-3 - res-companion-2 does not cover the folder move, which is the shape the feature exists for
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/file_moves.py:629-670` (`record_relocation` / `relocation_to`) against `sync/rclone_lane.py:4119-4137` (`_note_relocated`, one call per FILE) and `dashboard/src/ccsync_dashboard/collector.py:2801` (`is_dir=True`).
- What: lane B relocates individual FILES out of the trash and notes one
  `(old_local, new_local)` row per file. A detected hand move of a FOLDER is recorded
  by the collector as one `is_dir=True` command whose `from_rel`/`to_rel` are the
  directory. `relocation_to(<dir src>, <dir dest>)` compares whole paths and finds no
  row, so `apply_move` falls through to "nothing at the old path on this machine",
  `paths` is None, and `app.py` skips the relink - exactly the failure res-companion-2
  describes ("every clip under a hand-moved folder is Media Offline while the MOVES
  history says the machine followed"). If the emptied source directory still exists
  locally the command instead fails earlier with "the destination already exists on
  this machine", which is no better.
- Failure scenario: an editor drags `Interviewees/Creator_Interviews` into `B-roll/`
  on the NAS (the case the docstrings cite, twice). Lane B follows it file by file and
  writes N relocation rows; the dashboard's command names the folder; the companion
  answers "nothing at the old path"; no clip is relinked.
- Evidence: read of both ends; `relocation_to` is an exact `_cmp_key` equality on both
  halves and lane B never writes a directory-level row (`_note_relocated(origin, dest)`
  is called from the per-file loop in `_relocate_trashed`). No test in
  `test_file_moves.py` or `test_rclone_lane.py` exercises `is_dir=True` with a lane B
  relocation.
- Ledger: new - "res-companion-2's fix does not cover the `is_dir` move".
- Suggested fix: in the `not src.exists()` branch, when `move["is_dir"]`, accept the
  evidence of any relocation row whose `old` is under `src` and whose `new` is the
  matching path under `dest`; return the directory pair so the relink walks it.

### comp-sync-4 - lane B's recovery stamp overwrites lane A's live stall record and erases it from the wire and from disk
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/rclone_lane.py:4744-4763` (`_note_stall_recovered`) with `:4768-4778` (`stall_record`, which prefers the in-memory `_last_stall`) and `:4785-4800` (`stall_report`).
- What: `_note_stall_recovered` reads `stall_record()`, which returns this lane's STALE
  in-memory record in preference to the shared file, checks the label against that
  stale record, and then writes it back over the shared `state/lane_stall.json`. Lane A
  and lane B share that file, and only lane B's `sync_guard_report()` reaches the wire,
  so a lane A stall that lands after a lane B stall is destroyed by lane B's next
  successful pass: the file now holds a `recovered_at` lane B record, `stall_report()`
  answers None, and `app.py`'s `_lane_stall_record()` fallback also answers nothing (it
  skips `recovered_at`).
- Failure scenario: lane B is killed at 10:00; lane A wedges and is killed at 10:20;
  lane B's 10:30 pass completes. From 10:30 the machine reports no stall at all, the
  tray line clears, the alert clears, and the only persisted evidence of the lane A
  kill is gone - with lane A still uploading nothing.
- Evidence: run from the companion venv, driving the real functions over a fake lane:
  ```
  file before lane B recovers: A
  file after  lane B recovers: B recovered_at: True
  stall_report of a fresh reader: None
  ```
  `test_the_other_lanes_pass_does_not_end_this_lanes_stall` does not catch it: it
  builds a FRESH lane object with no `_last_stall`, so `stall_record()` reads the file
  and the label check works. (The in-memory shadowing itself predates live-1; what is
  new is that the file is now overwritten and the report goes silent.)
- Ledger: new (live-1).
- Suggested fix: read the persisted record (not `_last_stall`) inside
  `_note_stall_recovered`, and re-check the label after the read; better, give each
  lane its own key inside the one file so one lane can never write the other's slot.

### comp-sync-5 - the file-move ledger now has two writer threads, no lock, and one fixed `.tmp`
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/file_moves.py:591-680` (`FileMoveLedger._save`, `record`, `record_relocation`) wired at `companion/src/ccsync_companion/app.py:2427` (`extra_excludes_fn`, lane A thread), `:2475` (`on_relocated`, lane B thread) and `:8139-8190` (`apply_move`/`record`, the report/watcher thread).
- What: `FileMoveLedger` has no lock. Before today its only writer was the
  move-applying path; `on_relocated=self.file_moves.record_relocation` makes lane B's
  pass thread a second writer, and `_save()` serialises `self._entries` and
  `self._relocations` through one fixed `file_moves.json.tmp` followed by
  `tmp.replace()`. Two threads in `_save()` at once interleave their writes into that
  one temp file and then one of them promotes it; on Windows the concurrent
  `tmp.replace()` raises `PermissionError`, which `_save` swallows with a log line.
  `recent_excludes` (lane A thread) iterates `self._entries` while the same list is
  rebuilt by another thread.
- Failure scenario: a lane B pass that follows a 60-file move calls `record_relocation`
  60 times, each a full rewrite of the ledger, while the report thread records a move's
  `applying` intent row. The promoted file is truncated or holds a half-written record,
  `_load` drops it on the next start (`json.loads` raises, caught, entries empty), and
  with it goes every `applying` intent row (the res-companion-1 crash resume), every
  `relink_pending` row and every lane A exclusion.
- Evidence: read of `_save` (`tmp = self._path.with_suffix(".json.tmp")`, one fixed
  name), of the class (no `threading.Lock` anywhere in `file_moves.py`), and of the
  three call sites above, which are on three different threads. This is the shape
  CLAUDE.md flags for `project_pick.doc_save` ("a read-merge-write through a fixed
  `.tmp`").
- Ledger: new (res-companion-2's wiring).
- Suggested fix: one `threading.Lock` around `_load`/`_save`/every mutator, and a
  unique temp name (`.json.<pid>.<tid>.tmp`); batch a pass's relocations into one
  `_save()`.

### comp-sync-6 - a hard link that cannot be unlinked is reported as "kept" while the file is already at the destination
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/rclone_lane.py:4266-4290` (`_move_out_of_trash`).
- What: on POSIX the new path is `os.link(src, dest)` then `os.unlink(src)`. If the
  unlink fails (a read-only trash, an NFS/SMB lock, EPERM under a sticky bit) the
  `OSError` escapes to the outer handler, which logs "could not move %s to its new
  folder ... it stays in .ccsync-trash" and returns "kept" - but the link is already in
  place, so the file IS at the destination. The pass then counts it as a duplicate
  rather than a relocation, so the breaker's relocation discount loses one file and the
  log says the opposite of what happened.
- Failure scenario: a Mac editor whose `.ccsync-trash` sits on a volume that refuses
  the unlink; every relocated file is counted as trashed-as-duplicate and the breaker
  is one file closer to tripping per file successfully followed.
- Evidence: read of the control flow; the `else: os.unlink(...); return "moved"` block
  is inside the outer `try` whose `except OSError` returns "kept".
- Ledger: new (comp-sync-3, the 2026-09-18 morning finding).
- Suggested fix: wrap the `os.unlink` in its own try; on failure log it and return
  "moved" (the link is the move), leaving the trash copy for `prune_trash`.

### comp-sync-7 - a relocation row whose timestamp cannot be parsed is silently dropped
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/file_moves.py:672-681` (`_prune_relocations`).
- What: the pruner's `except (TypeError, ValueError): continue` DROPS the row rather
  than keeping it, which is the opposite of the convention stated by the same fix pass
  a few hundred lines away (`rclone_lane._stall_age_seconds`: "Unparseable is NOT old:
  a record we cannot date must keep whatever claim it already has"). A ledger written
  by a build that spells `at` differently, or a row whose float was mangled by a
  partial write, loses the evidence `apply_move` resumes from, and the clips go Media
  Offline with the move recorded as followed - the exact outcome res-companion-2 exists
  to prevent.
- Failure scenario: any partially written `relocations` array after a kill mid-`_save`
  (see comp-sync-5) that still survives `json.loads`.
- Evidence: read of both functions side by side.
- Ledger: new (res-companion-2).
- Suggested fix: treat an unparseable `at` as `now` (keep the row) and let the entry
  cap bound it, matching `_stall_age_seconds`.

## Coverage note
- I did not re-audit the unchanged parts of the territory in depth: `selection.py`,
  `drive_reminder.py`, `drive_swap.py`, `manifest.py`, `root_guard.py`,
  `sync/repath.py`, `sync/borrowed_folders.py`, `sync/shared_folders.py`,
  `sync/syncthing_admin.py`, `sync/syncthing_supervisor.py`, `sync/base.py` were read
  only far enough to follow the diff's call graph.
- The suite does not cover: `apply_move` with an EMPTY plan or a same-project move
  (comp-sync-1); `moved_to()` after a 4b outcome (comp-sync-2); any `is_dir=True` move
  combined with a lane B relocation (comp-sync-3); `_note_stall_recovered` on a lane
  object that holds its own in-memory stall while the other lane owns the file
  (comp-sync-4); any concurrent use of `FileMoveLedger` (comp-sync-5); the POSIX
  hard-link branch of `_move_out_of_trash` at all (it is `os.name != "nt"`, so it never
  executes on the Windows runner, and I found no macOS-only test for it - the macOS CI
  runner is the only place it is exercised).
- Checked and found sound: the `unreadable` key on the locate wire (both ends exist,
  optional on read, harmless when ignored); `_trashed_from`'s reconstruction of the
  pre-trash path against `_backup_dir` / `_trashed_this_pass`; `_local_destination`'s
  new two-argument `project_rel_fn` with its `TypeError` fallback (the app's
  `_project_rel_for_slug(slug, rel_path="")` matches, and the borrowed lookup's keys
  line up with `_dest_is_synced_here`'s); the syncthing_lane import-cycle fix and the
  move of `_heal_missing_paths` above the `if not expected` return.
- `syncthing_lane`'s `markerName` change (comp-sync-6 of the morning) is honest about
  covering the heal only; `rclone_lane`'s filters and `tray.py` still hardcode
  `.stfolder`, which the comment states, so I did not report it as a defect.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/app.py:8410-8427` (`_show_moved_clip_dialog`): the
  body text "Your copy has already been moved to match" is asserted unconditionally and
  is false for any outcome where the copy did not reach `to_rel` - see comp-sync-2.
- `dashboard/src/ccsync_dashboard/api.py:2849`: the move route's target set is the
  union of the SOURCE project's enforce ticks and every `editor_media` holder, and
  nothing in it asks whether the destination is ticked anywhere - the server-side half
  of comp-sync-1.
