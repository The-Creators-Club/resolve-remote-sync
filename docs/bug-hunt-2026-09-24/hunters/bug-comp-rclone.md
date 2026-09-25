# bug-comp-rclone - lane A/B rclone runner, lane B breaker/disk floor/trash, server-side repath, locate client
Files read (approximate coverage): sync/lane_guard.py (all), sync/repath.py (all), sync/base.py (all), sync/server_locate.py (all), sync/rclone_lane.py (~60%: filters, command builders, tally, bounded runners, clone/orphan/trash scans, run_once, breaker accounting, relocation follow, stall watchdog, popen runner, start/stop, watchdog handler, express path). Callers followed into sync/sequencer.py (_process_project, _prune_trash) and app.py (_project_rel_for_slug, resume_lane_b).
Tests/probes run: three ad-hoc snippets under companion\.venv in the scratchpad (repath two-pass scenario with a fake SyncthingAdmin; LaneBBreaker cumulative account with sub-eager relocated passes; DiskFloorLatch park/re-measure; RcloneRunTally on a backup-dir record pair). No repo suite run.

## Findings

### bug-comp-rclone-1 - a blocked repath is "completed" on the next pass by re-pointing Syncthing at the directory lane B / the structure clone created at the new path
- Severity: high
- Confidence: CONFIRMED (mechanism, by probe); Syncthing's reaction to the re-point is PLAUSIBLE
- Where: companion/src/ccsync_companion/sync/repath.py:567 (`_move_dir`: `if dst.exists(): ... return True`); companion/src/ccsync_companion/sync/sequencer.py:2045-2067 (a blocked project's lanes still run at the NEW rel)
- What: when the move of the project directory fails (the routine case: Resolve/Explorer holds a handle), the folder is left paused and a blocked event is recorded, but `_process_project` then carries on for the same project at its NEW rel_path: `_maybe_clone_structure` mkdirs `local_root/Projects/<new rel>` (clone_directory_tree creates `base` when absent) and lane B's `rclone sync` creates it and fills its Proxy dirs. On the next pass `_move_dir` sees a live source and an existing destination, treats that as the "conflict" case, returns True, and reconcile re-points the Syncthing folder at the new directory, unpauses it, and records a moved=True event saying "CC Sync moved your copy to match".
- Failure scenario: admin renames `2026/Old` to `2026/New` while an editor has the project open in Resolve. Pass 1: move fails, blocked. Same pass: lane B pulls proxies into `.../2026/New/.../Proxy`. Pass 2: folder re-pointed at `.../2026/New` (holds proxies and an empty skeleton, no `.stfolder`, none of the lane-C assets), unpaused; the whole real project stays at `.../2026/Old` in no lane's scope (lane A no longer uploads originals from it), the blocked sentence is replaced by a false "moved your copy" note, and a Resolve relink from Old to New is attempted against files that are not there. The comment on the blocked branch (repath.py:440-447) names exactly this outcome as the thing leaving it paused was meant to prevent. The same path is reached if `shutil.move`'s cross-volume copy half fails part-way (a partial destination exists next pass).
- Evidence: scratchpad p2.py: pass 1 `[] [('pause', True)] moved=False`; after creating `New/Proxy/a.mov`, pass 2 returns `['slug1']`, calls `set_folder_path(...\2026\New)` and `set_folder_paused(False)`, `New/.stfolder` absent, `Old` still holds `.stfolder` and `Assets.wav`, event note "CC Sync moved your copy to match (2026/New)".
- Ledger: new (related to AUDIT_2 DEL-5/L-8, whose guard this bypasses)
- Suggested fix: only take the "target already exists, re-point anyway" branch when the target carries the project's own `.ccsync-project` marker / `.stfolder` (i.e. holds the content); otherwise treat it as still blocked. Independently, skip lanes A/B and the structure clone for a project whose repath is blocked (`ledger.blocked(slug)`).

### bug-comp-rclone-2 - moves the lane itself followed on a sub-eager pass stay on the breaker's cumulative counter for ever, so benign hand moves trip "slow leak"
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/sync/lane_guard.py:786-793 (`note_pass`: the relocation probe runs only when `would_trip or eager`); companion/src/ccsync_companion/sync/rclone_lane.py:4490-4493, 4377
- What: `_relocate_trashed` already knows, for free, how many of this pass's trashed files the server said were moved (`_moved_out_of_trash`, `_server_relocated_keys`), but that knowledge only reaches the breaker through `relocation_probe`, which `note_pass` calls only when the pass is about to trip or trashed at least half the per-pass cap (25). A pass that trashed 1-24 files, all of them followed to their new folder, adds them all to `_deletes` permanently; the later discount is clamped to the CURRENT pass's deletions, so earlier passes' relocations are never taken back.
- Failure scenario: an owner drags ten folders of ~20 proxies each between projects over a week. Each lane B pass follows the move (files renamed out of the trash into the new project), yet `deletes` climbs 20, 40, ... 200. The next pass that trashes two genuinely deleted proxies trips "proxy download has moved 202 file(s) ... slow leak" and parks lane B until a human resumes it, for 200 files that were all still on the NAS and on this disk.
- Evidence: scratchpad p1.py: 12 calls of `note_pass(scope, 20, 0, 100, relocation_probe=lambda: 20)` leave `deletes` at 200 (probe never consulted until the counter is over the limit), then `note_pass(scope, 2, ...)` trips BREAKER_CAUSE_LEAK with 202.
- Ledger: new (related to comp-lanes-ab-5 / CR-44, whose "discount them as they happen" this does not reach below the eager threshold)
- Suggested fix: pass the already-known server relocations (`_moved_out_of_trash` plus trashed files in `_server_relocated_keys`) to `note_pass` as a separate, always-applied discount, keeping the expensive scope listing lazy.

### bug-comp-rclone-3 - the free-space park keeps its first sentence and never clears after the trash prune frees space
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/sync/lane_guard.py:1019-1031 (`DiskFloorLatch.check` while parked); lane_guard.py:1286-1298 (`prune_trash` disk-pressure loop stops at `min_free_bytes`)
- What: two numbers disagree. The park clears itself only at `DISK_FLOOR_CLEAR_MULTIPLE` x the floor (40 GB by default), but the disk-pressure prune stops deleting recovery copies as soon as free space reaches 1 x the floor (20 GB), so the automatic remedy can never produce the automatic release. Meanwhile, while parked, `check()` updates `_free_bytes` but returns the reason string built at park time, so the editor keeps reading the old free-space figure.
- Failure scenario: a laptop parks at 10 GB free with 30 GB of `.ccsync-trash`. The next prune drops batches until ~22 GB free and stops. Lane B stays parked indefinitely (22 < 40), and the tray, balloon and fleet chip still say "this drive has 10 GB free, and proxy download needs 20 GB" while the drive has 22 GB and more than the stated need; only a manual RESUME gets proxies moving.
- Evidence: scratchpad p1.py: `check(10 GB)` parks; `check(25 GB)` returns "this drive has 10 GB free, and proxy download needs 20 GB" and `report()["free_bytes"]` is 25 GB.
- Ledger: new
- Suggested fix: rebuild `_reason` from the current measurement on every parked `check()`, and have the disk-pressure prune target `clear_free_bytes` (or clear the park at the floor once a prune has run), so the two thresholds agree.

### bug-comp-rclone-4 - stray-project scan and express attribution compare paths without NFC folding
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/sync/rclone_lane.py:3402-3410 (`_refresh_stray_projects`); rclone_lane.py:2390-2395 (`_project_rel_for_path`)
- What: both compare directory names read off the local disk (os.walk / watchdog paths) against the dashboard's rels with normcase/lower only. CLAUDE.md (CR-90, GOTCHAS 17) says a Mac's listdir is NFD and the dashboard's rels are NFC, and every other comparison in this file goes through `nfc_key`.
- Failure scenario: a Mac editor ticks `2026/FF5/Matej Šimalčík`. The stray scan counts that selected, syncing project as "in no sync plan" (its bytes on the stray chip and in Settings), and express never attributes its new clips (they wait for the rotation). CJK names are unaffected.
- Evidence: read only; no Mac available. The mismatch requires the on-disk spelling to be NFD, which CR-90 records as observed.
- Ledger: related to CR-90 (fixed elsewhere; these two sites were not covered)
- Suggested fix: fold both sides through `nfc_key` before normcase/lower in both functions.

### bug-comp-rclone-5 - a trashed file is counted as "transferred" as well as deleted
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/sync/rclone_lane.py:2138-2146 (`RcloneRunTally.feed_record`)
- What: the `"Moved into backup dir"` record matches the `"Moved" in msg` branch, which increments `transferred` before the inner check increments `deleted`. So every file lane B moves to the trash also counts as a transfer.
- Failure scenario: a lane B pass that only trashes 12 superseded proxies reports "transferred 12 file(s)" on the tray and the fleet grid. `_last_run_moved` counts each file twice, and the watchdog's progress marker sees double.
- Evidence: scratchpad: feeding the measured record pair (`Moved (server-side)`, `Moved into backup dir`) gives `transferred=1 deleted=1`.
- Ledger: new (the comp-lanes-ab-4 fix removed the twin record's count, not this one)
- Suggested fix: test for the backup-dir/deleted shapes first and only count a transfer for Copied/Moved records that are not deletions.

## Coverage note
Not read in depth: rclone_available/probe_watch_root, scan_pending_uploads/scan_size_mismatches, the stall-record file helpers (lines 248-510), refresh_orphan_report, the express partition's interaction with pause_express/resume_express, and RcloneTuning. HaltState and the breaker resume one-shot were read and look right. The relocation follow was checked for its own-path guard (comp-sync-1 from 09-18) and it holds.

## OUT OF TERRITORY
- companion/src/ccsync_companion/app.py:7549-7551: `resume_lane_b` clears the disk-floor park with no request-id one-shot, so a standing dashboard RESUME can re-clear, re-pass and re-park (re-firing the on_park toast) on every report reply while the breaker half is already applied.
