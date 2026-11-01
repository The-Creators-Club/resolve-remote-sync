# Pre-launch bug hunt 2026-10-06 - lens `bug-sync`

Territory: `companion/src/ccsync_companion/sync/` (sequencer, rclone lanes incl.
the CR-347 hand-off and express, repath, lane_guard breaker/trash/halt,
borrowed and shared folders, syncthing_admin), `file_moves.py`,
`selection.py`, `manifest.py`, `drive_swap.py`, `root_guard.py`. Delete
paths first: lane B `sync` + `--backup-dir`, trash prune, the "Remove from
this machine" gate (`app.removal_blockers` / `remove_project_from_machine`,
read because it is the consumer of `RcloneLane.pending_uploads`), file-move
section 4b, repath and borrowed/shared re-points.

Checked against KNOWN_BUGS.md (CR-44/47/66, CR-347, APP-13, the 09-24 hunt)
so known-and-fixed items are not repeated. Probe run: the bundled rclone
1.74.4 against a scratch tree, confirming that `--min-age` excludes a file
whose mtime is in the future (it is neither copied nor counted by the
`--dry-run` the removal gate uses).

Not covered in depth: `syncthing_lane.py`, `syncthing_supervisor.py`,
`drive_reminder.py`, `server_locate.py` (skimmed only); the express lane's
batching beyond `_express_partition`; the 7,000-line `rclone_lane.py` was
read along its delete/trash/hand-off/filter paths, not line by line.

### bug-sync-1 - "Remove from this machine" deletes originals lane A has not uploaded when their mtime is recent or in the future

- Severity: high
- Confidence: CONFIRMED (code path read; rclone behaviour probed)
- Where: `sync/rclone_lane.py:1792-1854` (`scan_pending_uploads`), `sync/rclone_lane.py:2005-2058` (`--min-age 120s` in `build_up_command`), `app.py:6203-6236`, `app.py:6340-6392`, `tray.py:1926-1931`, `sync/rclone_lane.py:6779-6782` (express twin)
- What: the removal gate's only lane A question is a `--dry-run` of the real lane A command, which carries `--min-age 120s`. rclone excludes every file younger than 120 s AND every file whose mtime is in the future, so those files are neither uploaded nor counted as pending. The gate then reports "nothing pending", the dialog says "CCSync has checked: everything on this computer has reached the server, so nothing will be lost", and `shutil.rmtree` deletes them. Probed with the bundled rclone 1.74.4: a `.mov` dated 2027 is skipped by both the real copy and the dry run.
- Scenario: a documentary crew's camera clock is set to local time abroad while the laptop is on home time (FAT timestamps carry no zone, so the copied clips are dated hours ahead), or a camera with a wrong year. The card dump sits on the laptop with lane A green and silently not uploading it; the editor clicks Remove to free disk; the gate passes and the only copy is deleted (rmtree, no trash). Same with a render exported in the last two minutes. Separately, a future-dated clip never uploads at all (express gives up after 30 min, the periodic pass excludes it) and nothing reports it.
- Recommendation: run the gate's dry run WITHOUT `--min-age` (and without `--min-size`): anything present that the NAS lacks must block. Detect future-dated video in lane A (a stat walk or `rclone lsf --max-age 0`-style check) and report it in the tray/dashboard; consider `--min-age` only for files whose mtime is in the past, or use the size-stability gate express already has.
- Known: not recorded (APP-13 covers a skewed machine clock, not future-dated files).

### bug-sync-2 - Removing an upload-only project deletes every non-video file, with a dialog that says nothing will be lost

- Severity: high
- Confidence: CONFIRMED
- Where: `app.py:6171` (`upload_only` skips the lane C half), `app.py:6236-6283`, `tray.py:1926-1931`, `docs/UPLOAD_ONLY_TICK.md` section 5
- What: an upload-only tick carries ONLY `VIDEO_EXTS` up (lane A); lane C is off, so separate-recorder audio (WAV), stills, documents and project files in that folder exist nowhere but this disk. `removal_blockers` asks the lane A question only for upload-only projects, so it never blocks on them, and the confirm dialog states "everything on this computer has reached the server, so nothing will be lost". `remove_project_from_machine` then rmtree's the folder. The doc lists "only video goes up" as a known limit but not that the removal gate deletes the rest.
- Scenario: an ingest laptop ticks a shoot upload-only (the feature's stated use), dumps cards with Zoom/Tascam WAVs beside the video, waits for the uploads to finish, then uses Remove to reclaim the disk. All the sound recordings are deleted permanently.
- Recommendation: for upload-only (and in general), block or loudly warn when the folder holds any file lane A would not carry and that is not provably on the server (e.g. `rclone check --one-way --size-only` of the whole folder, or a list of non-video files with a typed confirmation). Fix the dialog sentence so it only claims what was checked.
- Known: docs/UPLOAD_ONLY_TICK.md section 5 records the upload limit (open decision), not this deletion.

### bug-sync-3 - A borrowed folder whose lender was renamed is re-pointed at an empty skeleton and silently stops syncing

- Severity: medium
- Confidence: CONFIRMED (code path); end state per the repo's own marker-missing analysis (bug-comp-syncthing-7)
- Where: `sync/borrowed_folders.py:293-305` (`_repoint`), `sync/borrowed_folders.py:230-240`, `sync/sequencer.py:1350-1358` (borrowed reconcile only at pass head), `sync/sequencer.py:2187-2195` + `2318-2327` (mid-pass selection restart, then the include's structure clone and lane B at the NEW subpath)
- What: `_repoint` moves the old directory only when `want_path` does not exist, and when the move is skipped or fails it `mkdir`s `want_path` and re-points the Syncthing folder there anyway ("Syncthing will re-pull the subtree"). It will not: the new directory has no `.stfolder`, so Syncthing refuses to scan it, and unlike `SharedFolderManager` (bug-comp-syncthing-7) the borrowed manager has no marker check, so the reconcile reports `repaired`/`ok`. The common way to reach it: the sequencer re-reads the selection after every project turn, a lender rename is noticed mid-pass, the borrower's turn then structure-clones and lane-B-fills the include at the new path, and the next pass's reconcile finds `want_path` existing, skips the move and re-points at that skeleton. The same happens on Windows whenever Resolve holds a handle and the move fails.
- Scenario: admin renames a lender project on the NAS during a long pass. On every borrower machine the borrowed interview folder stops syncing both ways with no problem sentence; the editor's unsynced edits and any un-uploaded originals stay stranded in the old directory, which no lane walks any more (the include subpath now names the new path).
- Recommendation: mirror repath: never re-point after a failed or skipped move unless the target holds the marker; leave the folder paused and record a problem sentence; skip the include's clone/lane runs while the lender's move is pending; add the marker-missing check `SharedFolderManager` has.
- Known: not recorded (bug-comp-syncthing-7 fixed the shared-folder twin only).

### bug-sync-4 - File-move section 4b trashes a single file without checking the server holds that version

- Severity: medium
- Confidence: CONFIRMED
- Where: `file_moves.py:630-669` (single-file branch of the 4b path)
- What: logic-plans-3 taught the FOLDER branch to bin only files the server is known to hold at the destination (matching rel+size). The single-file branch still does `src.replace(trash)` unconditionally. Lane A is `copy --ignore-existing`, so a local file can legitimately differ from the server's copy of the same name (a re-exported clip the size-mismatch scan already warns about), and a lane C file can hold edits Syncthing has not pushed yet (its folder is paused outside its turn). That local version goes to `.ccsync-trash` with an ok/done answer and `prune_trash` deletes it after 14 days, or sooner under the free-space floor.
- Scenario: editor re-exports `Interview_A.mp4` (NAS still has the first export). Admin moves `Interview_A.mp4` into a project this machine does not sync. The re-export is trashed, the MOVES history says the machine followed, and two weeks later it is gone.
- Recommendation: run the same server-listing check for a single file (size match at the destination) and keep the file at the old path (answer as the folder branch does) when it does not match or the listing fails.
- Known: not recorded (logic-plans-3 fixed the folder branch only).

### bug-sync-5 - File-move section 4b trashes a whole folder of un-synced non-video files when the server listing fails

- Severity: medium
- Confidence: CONFIRMED
- Where: `file_moves.py:503-541` (`_split_folder_for_4b`, `inventory is None` branch)
- What: when `server_files` returns None (rclone `lsf` timed out, NAS hiccup, the 120 s reporter-thread timeout), a folder holding no lane A original is binned whole on the reasoning that "proxies and sidecars are what the server's own lanes hand out". Lane C files are not: WAVs, stills, `.drp`s and documents the editor added go UP through Syncthing, and the project's folder is paused except during its lane C turn, so new ones are routinely not on the server yet.
- Scenario: editor drops a folder of sound recordings into `Audio/Day3`; before its lane C turn the admin moves `Audio/Day3` to a project this machine does not sync, and the listing call times out. The whole folder goes to the trash, the move is recorded done, and the recordings are pruned 14 days later. They never reached the server.
- Recommendation: on a failed listing, answer `retrying` for ANY folder that holds files (not only lane A originals), as the original-bearing case already does.
- Known: not recorded.

### bug-sync-6 - Lane B sweeps proxies an editor generates locally (Resolve, BPG) into the trash, and a batch trips the breaker

- Severity: medium
- Confidence: CONFIRMED (code path); depends on editor workflow
- Where: `sync/rclone_lane.py:977-1026` (`build_filter_rules_down`), `sync/rclone_lane.py:2273-2345` (`sync` + `--backup-dir`), `sync/lane_guard.py:1293-1345` (prune)
- What: lane B is `rclone sync` over every `**/Proxy/**` path, so any proxy that exists locally and not on the NAS is moved to `.ccsync-trash` once it is 120 s old. SPEC.md acknowledges this for the companion's own generator (off where lane B is on) but nothing stops Resolve's "Generate Proxy" or the Blackmagic Proxy Generator, whose default output is exactly `<media dir>/Proxy/`, on an editor machine. Lane A never uploads Proxy dirs and lane C ignores them, so the NAS never gets them.
- Scenario: a remote editor imports a fresh card dump and lets Resolve generate proxies for it, as every Resolve tutorial says to. Two minutes later lane B moves them into the trash (proxies go offline in Resolve), and a dump of more than 50 clips trips the lane B breaker, stopping all proxy downloads on that machine until a human resumes. After 14 days the generated proxies are deleted.
- Recommendation: exclude local-only proxies younger than the NAS's own proxy for the same stem from deletion (or switch lane B to `copy` plus an explicit, NAS-confirmed delete list), or carry editor-made proxies up; at minimum detect "proxies created on this machine" and warn the editor and admin instead of tripping the breaker on them.
- Known: SPEC.md line 54 records the generator case only; not in KNOWN_BUGS.

### bug-sync-7 - A server-side folder move does not end a handed-off upload from that folder, so it lands at the cleared path

- Severity: medium
- Confidence: PLAUSIBLE
- Where: `app.py:8786-8806` (`apply_move` called with no `end_handoffs_under`), `file_moves.py:684-690`, `sync/rclone_lane.py:3597-3626`, `sync/sequencer.py:2864-2876`
- What: CR-347 made lane A hand a long upload to a background child that can run for hours, and taught the repath and borrowed moves to end children reading from a folder before moving it (`_guarded_move`), "anywhere they would keep writing to the server's OLD path". `file_moves.apply_move` (reporter thread) moves files and folders with no such step. On macOS the rename succeeds under the open file; the child keeps reading through its fd and finishes the upload to the old remote path, which `rclone` re-creates. On Windows the move fails with a sharing violation and is retried hourly for as long as the 22 GB upload runs.
- Scenario: leso's card dump shape: one 22 GB original still uploading (handed off) into `Footage/Card3`, admin moves `Card3` on the dashboard. The Mac follows the move, the upload completes into the now-recreated old `Card3` on the NAS, and lane A later uploads the same file again at the new path: two copies on the NAS, one at the path the admin cleared.
- Recommendation: call `lane_a.end_handoffs_under(src)` (and stop an in-flight express/periodic run over that subtree) before `apply_move` touches the disk, as `_guarded_move` does.
- Known: CR-347 (fixed) covers repath/borrowed only.

### bug-sync-8 - The removal gate rewrites lane A's shared filter file without its exclusions, racing a periodic run's startup

- Severity: low
- Confidence: CONFIRMED (race window is small)
- Where: `sync/rclone_lane.py:3877-3890` (`pending_uploads` calls `_ensure_filter_file()` with no excludes), `sync/rclone_lane.py:3384` + `3402`, `sync/rclone_lane.py:2985`
- What: `pending_uploads` (tray worker thread) rewrites the single `filter_up.txt` with no exclusions. The sequencer thread writes the same path with the express in-flight, handed-off and file-move exclusions and then spawns rclone, which reads it once at startup. If the tray's rewrite lands between those two steps, the periodic run starts without the exclusions.
- Scenario: editor opens "Remove..." on project X while the sequencer is starting lane A for project Y that has a recently moved-away path; the run uploads the moved file back to the path the admin cleared (the failure docs/FILE_MOVES.md exists to prevent), or double-uploads a handed-off file.
- Recommendation: give probes their own filter file (`filter_up_probe.<pid>.txt`) instead of the lane's live one.
- Known: not recorded.
