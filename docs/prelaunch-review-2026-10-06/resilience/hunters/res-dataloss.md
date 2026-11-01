# Pre-launch resilience review, lens `res-dataloss` (2026-10-06)

**Territory.** Every path that can delete, overwrite, trash or unshare footage
or project files, the latch that stops it going wide, and the undo for each.
Reviewed against the working tree on top of `08b40eb`.

**Read end to end:** lane B `rclone sync` argv, filters, `--backup-dir`, delete
caps (`sync/rclone_lane.py`); the breaker, trash retention and disk-floor prune
(`sync/lane_guard.py`); relocation follow-out-of-trash; the "Remove from this
machine" gate and rmtree (`app.removal_blockers`,
`app.remove_project_from_machine`, `tray._confirm_remove_project`); repath,
including the cross-volume copy-then-swap (`sync/repath.py`); consolidate's
dry-run consent (`consolidate.py`); Syncthing folder config, ignores,
versioning and `ignoreDelete` on both sides (`sync/syncthing_admin.py`,
`dashboard/provision.py`, `collector._retarget_ok`); dashboard server-side file
moves (`api.move_project_files`) and the companion half
(`file_moves.apply_move`, section 4b); proxy_gen publish; b-roll staging
prune; ytdl sweepers; package trash and package prune; `server/publish_db.py`
(both indexes); fixer reservations; the protection panel; editor SMB
permissions (`server/setup_tree.py`, `server/backends/synology.py`
`EDITORS_ACE`) and the grade swap (`drive_swap.swap_to_server`).

**Probed:** the bundled-version rclone 1.74.4 (`copy --ignore-existing
--min-age 120s --dry-run`) against files with a future mtime, a fresh mtime and
an old mtime, in the scratchpad. Only the old file is listed: a future-dated
clip is invisible to lane A and to the removal gate.

**Not covered:** live Syncthing behaviour for `/rest/db/completion` on a paused
folder (finding 4 is PLAUSIBLE for that reason); Resolve database / `.drp`
loss paths beyond the media-pool journal; the Cards engine's own data dir.

**Already strong and not re-reported:** the lane B breaker (all three
triggers, marker probe on the down route, in-flight crediting, relocation
discount), `.ccsync-trash` with the "never while tripped / never the newest"
rules, the filter-file validator, consolidate's fail-closed dry run, repath's
pause-before-move and staging copy, `ignoreDelete` + staggered versioning on
every lane C folder, the retarget sanity gate, the broll publish drain, the
O_EXCL fixer reservations, the package trash.

---

### res-dataloss-1 - "Remove from this machine" deletes an upload-only project's non-video files that never left the computer, under a dialog that says nothing will be lost

- **Severity:** high
- **Confidence:** CONFIRMED (code read end to end)
- **Where:** `companion/src/ccsync_companion/app.py:6158-6162` (`upload_only` skips the lane C half), `app.py:6234` (lane C block guarded by `not upload_only`), `app.py:6380-6390` (`shutil.rmtree(target)`), `companion/src/ccsync_companion/tray.py:1925-1932` (confirm copy), `sync/rclone_lane.py:940-975` (lane A carries `VIDEO_EXTS` only), `docs/UPLOAD_ONLY_TICK.md:124-136`
- **What:** an upload-only tick runs lane A alone, and lane A carries only the 16 video extensions. Everything else in the project directory on that computer (separate-recorder WAVs from the same card dump, stills, graphics, subtitle files, AE projects, documents) is carried by nobody: lane C is off and the server never shares the folder. The removal gate for an upload-only project asks only the lane A question, so it answers "not blocked" whenever the videos are up, and the dialog then tells the editor "CCSync has checked: everything on this computer has reached the server, so nothing will be lost". The rmtree that follows is permanent: it is not a move to `.ccsync-trash`.
- **Scenario:** a shooter on a laptop ticks the shoot UPLOAD ONLY, dumps a card (A-cam `.mov` + Zoom `.wav` + `.jpg` stills) into the project, waits for lane A to finish, formats the card, and uses tray -> Remove from this machine to free space. Gate: 0 pending video uploads, no lane C question asked. Dialog: "nothing will be lost". Result: every WAV and still is gone from the only place it existed. The documented "known limit" (non-video is not uploaded) becomes silent loss at the one moment the product claims to have checked.
- **Recommendation:** for an upload-only project, the gate must enumerate the files under the project dir that no lane carries (everything outside `Proxy/` that does not match lane A's filter and is not product litter) and block, naming them, unless the editor types the override. The dialog copy must never say "everything has reached the server" for an upload-only project; say what was checked ("video originals"). Longer term: decide the owner's open question in UPLOAD_ONLY_TICK.md section 5 (widen lane A's filter for upload-only runs) before launch, because a customer's sound recordist is exactly the case.
- **Known:** not in KNOWN_BUGS; the non-upload is a documented limit (UPLOAD_ONLY_TICK.md section 5) but the removal consequence is not, and `companion/tests/test_sync_halt.py:394` pins the gap as intended behaviour.

### res-dataloss-2 - the removal gate does not see the WON'T UPLOAD set: a name collision or re-export passes the gate and the only copy is deleted

- **Severity:** high
- **Confidence:** CONFIRMED (code read)
- **Where:** `companion/src/ccsync_companion/sync/rclone_lane.py:1795-1850` (`scan_pending_uploads` = lane A dry run with `--ignore-existing`), `rclone_lane.py:1853-1890` (`scan_size_mismatches`, computed on the orphan cadence and reported only), `app.py:6131-6260` (`removal_blockers` never consults it), `tray.py:1925-1932`
- **What:** lane A is `copy --ignore-existing`, so a local file whose NAME already exists on the NAS is never uploaded, whatever its bytes. The product already knows this set (`scan_size_mismatches`, the `[ WON'T UPLOAD ]` chip, SYNC_SAFETY.md section 5 calls it "the one shape of data loss on lane A"). The removal gate is built on the same `--ignore-existing` dry run, so every one of those files counts as "already uploaded" and the removal proceeds without the typed override.
- **Scenario:** two shooters on two machines dump Sony cards into the same `Footage/Day1/` folder. Both cameras name clips `C0001.MP4`, `C0002.MP4` ... The first machine's clips win on the NAS; the second machine's 40 clips show `[ WON'T UPLOAD: 40 ]` on the grid. A week later the second shooter removes the project to free space: gate says 0 pending, dialog says "nothing will be lost", rmtree deletes 40 clips that exist nowhere else. The same happens to every "fix the audio and render again" export under an unchanged name.
- **Recommendation:** make the gate ask `scan_size_mismatches` for the project subpath (and each borrowed subpath) as well, and block on any non-zero count with the names, behind the same typed override. A check that cannot run blocks, like the rest of the gate. Consider making lane A refuse to treat a same-name/different-size file as uploaded anywhere else that asks "has this reached the server" (manifest/behind counts too).
- **Known:** the skipped-exists condition is known and reported (COMMERCIAL_READINESS item 9, SYNC_SAFETY.md section 5); its interaction with the removal gate is not recorded.

### res-dataloss-3 - a clip with a future mtime is never uploaded and is invisible to the removal gate; a clip written in the last two minutes is invisible too

- **Severity:** high
- **Confidence:** CONFIRMED (rclone probe + code read)
- **Where:** `sync/rclone_lane.py:470-479` (`LANE_A_MIN_AGE_SECONDS = 120`), `rclone_lane.py:2038-2049` (`--min-age` in `build_up_command`), `rclone_lane.py:1820-1824` (the removal gate reuses that argv), express path's Python age check (same rule)
- **What:** rclone's `--min-age 120s` excludes any file whose mtime is less than 120 s in the past, and a mtime in the FUTURE is never "older than 120 s" until the wall clock passes it. Probed against rclone 1.74.4: of `old.mov`, `now.mov` and `future.mov` (mtime +13 h), only `old.mov` is listed by `copy --ignore-existing --min-age 120s --dry-run`. Card copies preserve the camera's mtime (the comment at `rclone_lane.py:472` says so), and FAT/exFAT cards store local time with no zone, so a camera on home time while travelling west, or with a wrong year, produces future-dated files. Those clips: (a) are never uploaded until the date passes, with nothing on the editor's side saying why; (b) count as "nothing pending" for the removal gate, which then deletes them. Separately, the gate also treats anything written in the last 120 s (a render that just finished into `Render in Place/`, a card dump still landing) as not pending.
- **Scenario:** a crew shoots in Los Angeles with cameras still on Taipei time (+15 h). The editor dumps cards that evening; lane A uploads nothing from the dump for 15 hours, the tray is green. If the camera year was set to 2027 by a battery reset, the footage never uploads for a year. Removing the project from that computer at any point in that window: gate 0 pending, "nothing will be lost", rmtree.
- **Recommendation:** in the gate, run the dry run WITHOUT `--min-age` (the gate asks "is anything not yet on the server", not "would this pass upload it now"), keeping `--min-size 1B` and the filters. In lane A, detect files with mtime more than a few minutes ahead of the clock in the manifest walk and report them (`sync_guard` field, tray line naming the clip and the date) or upload them via the express path's own age test with future mtimes treated as old; never let a future date mean "wait silently".
- **Known:** not recorded. DUI-17 and the `[ CLOCK n AHEAD ]` chip are about the machine clock, not file mtimes.

### res-dataloss-4 - the removal gate's lane C half trusts Syncthing's index without a scan: unscanned edits, a paused (halted) folder, or a stopped watcher read as 100% synced

- **Severity:** medium
- **Confidence:** PLAUSIBLE (code read; Syncthing's completion answer for a paused folder not probed live)
- **Where:** `app.py:6234-6268` (`folder_completion` + `needTotalItems`, no scan, no state check), `sync/syncthing_admin.py:757-769`, `syncthing_admin.py:593-600` (editor folders: `fsWatcherEnabled`, no `rescanIntervalS`, so Syncthing's 3600 s default), `sync/lane_guard.py` `HaltState` (a halt pauses every lane C folder)
- **What:** `/rest/db/completion` measures remote devices against the LOCAL INDEX. A file Syncthing has not scanned yet is not in the index, so it cannot lower completion. That window is ~10 s with a working watcher, up to an hour when the watcher is not delivering (network or some external volumes), and unbounded while the folder is paused, which is exactly the state a local or fleet halt leaves every lane C folder in (paused folders do not scan). The gate does not check `state` (it records it but never blocks on it) and never asks for `/rest/db/scan` before reading.
- **Scenario:** a fleet halt is on for two days while an admin investigates. An editor keeps cutting music and VO into `Audio/` (lane C content), then removes the project to free disk. The folder is paused, nothing new is indexed, completion reads 100, `needTotalItems` 0: no block, "nothing will be lost", rmtree deletes two days of audio that never left the laptop.
- **Recommendation:** block (fail closed, with a reason) when the folder is paused or its state is not `idle`; otherwise POST `/rest/db/scan?folder=<id>`, wait for `idle` with a bound, then read completion. Treat "could not scan" as blocked, like every other unknown in this gate.
- **Known:** not recorded.

### res-dataloss-5 - every editor's SMB login can delete camera originals on the NAS, and the product puts editors on the NAS; originals have no versioning, recycle bin or self-service restore

- **Severity:** high
- **Confidence:** CONFIRMED (code read of the permission model; not exercised on a live NAS)
- **Where:** `server/setup_tree.py:21-27,183` (tree is `<owner>:editors` mode `2770`, group rwx), `server/backends/synology.py:90-92` (`EDITORS_ACE = "rwxpdDaARWc--:fd--"`, delete and delete-child included), `server/backends/synology.py:1091` (`enable_recycle_bin: False`), `companion/src/ccsync_companion/drive_swap.py:445-470` (grade swap maps `P:` to the server with the editor's own login), wired-mode computers whose `P:` IS the NAS tree, `docs/SYNC_SAFETY.md` section 7 (originals: "no version at all")
- **What:** the editors group has full delete over the whole canonical tree. Nothing restricts that to admins, there is no SMB recycle bin (Synology one is explicitly off, nothing configures `vfs_recycle` on TrueNAS) and no "Previous Versions" shadow copies on the share. Two product features put ordinary editors' Explorer and Resolve directly on that tree: wired computers, and the remote grade swap. SYNC_SAFETY.md section 7 accepts "a human on the NAS" as a deliberate unguarded path on the assumption that the human is an admin; the permission model makes it every editor. The only recovery is a ZFS/Btrfs snapshot restore, which (resilience sweep SYS-14/SYS restore finding) is a root SSH procedure a non-technical owner cannot run.
- **Scenario:** a remote colourist swaps to the server to grade at full resolution and, out of local-mode habit (where deleting is harmless because lane A never deletes), deletes a "duplicate" folder of clips in Explorer, or runs Resolve's "Delete Selected Clips and Media". The originals are gone from the NAS for the whole fleet immediately; lane B then trashes every editor's proxies of them. A customer whose snapshot task was never set up (the protection panel can show it, but cannot make it exist) has no recovery at all.
- **Recommendation:** before launch, (1) give editors create/write but not delete on `Projects/**` video originals (NFSv4 ACL without `d`/`D` for the editors group on TrueNAS; the DSM ACE without `dD`), with deletes done through the dashboard's MOVE/trash path or by an admin account; or at minimum (2) turn on the SMB recycle bin (`vfs_recycle` aux params on TrueNAS, `enable_recycle_bin` on DSM, admin-only access) and SMB shadow copies on the tree share so "Previous Versions" works from Explorer, and (3) make the grade swap mount read-only or warn in its own dialog that deletes there are permanent for everyone. Add the recycle-bin/shadow-copy state to the protection panel.
- **Known:** not recorded. SYNC_SAFETY.md section 7 covers admin deletes only.

### res-dataloss-6 - `publish_db.py --which music` still overwrites every fleet-ingested track and every pending queue row in the live index

- **Severity:** medium
- **Confidence:** CONFIRMED (code read)
- **Where:** `server/publish_db.py:93-106,121-134` (`"drain": False` for music; the comment says its NAS-only rows "go the other way"), `publish_db.py:375-416` (`read_live_counts` and `shrink_refusals` look at `tracks/windows/tags` only, 10% floor), `music/web/musicweb/ingest_batches.py:983-1000` (the fleet's inline ingest `INSERT INTO tracks` directly into the live file)
- **What:** the live `music.db` holds rows that exist nowhere else: tracks the companions ingested inline (embedding computed on the editor's machine, tagged in the container) and `ingest_queue` journal rows. The publish swap renames the base rig's copy over it with no drain and no check for either, as long as fewer than 10% of `tracks` disappear. The comment justifying `drain: False` predates the inline fleet ingest and is now wrong. Recovery is `--rollback`, which throws away the publish, or a hand merge from `music.db.prev-<ts>`.
- **Scenario:** the owner re-indexes on the base rig and runs `publish_db.py --which music --apply`, as DEPLOY.md recommends ("Prefer publish_db.py"). Twenty tracks the editors dropped in over the past month (5% of the library) vanish from search; pending queue rows vanish; nothing says so.
- **Recommendation:** what MEDIA-4 and MUSIC-6 proposed: read `count(*) FROM ingest_queue WHERE state='pending'` and the live `tracks` rows absent from the candidate (by `rel_path`) in the container before the swap, and refuse with names unless `--allow-clobber-queue`; better, give music the same drain-and-merge broll has (`broll_drain.py` pattern).
- **Known:** MEDIA-4 (resilience sweep 2026-08-28) and MUSIC-6 (usability sweep 2026-09-03), both still OPEN in code.

### res-dataloss-7 - a single-file server move trashes this machine's copy without checking the server holds the same bytes; the trash then expires

- **Severity:** low
- **Confidence:** CONFIRMED (code read)
- **Where:** `companion/src/ccsync_companion/file_moves.py:766-826` (single-file section 4b branch: `src.replace(trash)`, no server check), contrast `file_moves.py:567-615` (`_split_folder_for_4b` checks `(rel, size)` against the server listing for folders), `sync/lane_guard.py:1260-1350` (prune: 14 days, size cap, disk-floor rule)
- **What:** when a moved file's destination project is not synced on this machine, a FOLDER is binned file by file only where the server listing shows the same relative path and size; a single FILE is moved to `.ccsync-trash` unconditionally. The local copy can differ from the server's (same name, different bytes, the WON'T UPLOAD case of res-dataloss-2), and the trash is pruned after 14 days, or sooner under disk pressure.
- **Scenario:** machine B holds its own `C0001.MP4` that never uploaded (name collision). The admin moves the server's `C0001.MP4` to a project B does not sync. B's only copy goes to `.ccsync-trash` and is pruned two weeks later.
- **Recommendation:** run the single-file branch through the same server check the folder branch uses (`server_files(dest_dir)` then match `(name, size)`); keep the file in place (answer `retrying`/kept-local) when it does not match or the listing fails.
- **Known:** not recorded (logic-plans-3 hardened only the folder branch).

### res-dataloss-8 - file moves keep renaming and trashing local files while a local or fleet halt is engaged

- **Severity:** low
- **Confidence:** CONFIRMED (code read)
- **Where:** `companion/src/ccsync_companion/app.py:8680-8800` (`_apply_file_moves`: gated on drive presence and the ledger, never on `HaltState`), `docs/SYNC_SAFETY.md` section 4
- **What:** the halt stops lanes A and B and pauses lane C, and is what an admin presses when something on the server is spreading. Server file moves are not a lane, so every companion keeps applying `commands.file_moves` through a halt: renames, and section 4b moves into `.ccsync-trash`.
- **Scenario:** an admin drags the wrong folder between projects with MOVE ON THE SERVER, notices, presses FLEET SYNC HALT to stop it spreading while they work out the undo. Every machine still follows the move on its next report (and bins copies on machines that do not sync the destination), so the undo now has to be followed by the whole fleet too, and anything binned is on a 14-day clock.
- **Recommendation:** hold `commands.file_moves` while `HaltState.active` (answer `retrying` with "sync is halted on this computer", attempts not spent), and say in the halt panel that moves are held too.
- **Known:** not recorded.

### res-dataloss-9 - SYNC_SAFETY.md still says nothing reports a missing snapshot schedule

- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `docs/SYNC_SAFETY.md` section 7 ("Nothing in the product says when it is missing ... it is a runbook item, not a system property"), versus `dashboard/src/ccsync_dashboard/protection.py` (the SYS-14 panel and the weekly report's standing "what is protected" block)
- **What:** the operator-facing safety doc tells a customer's admin the opposite of what the product now does, and it is the document they will read after a deletion. It also still lists recovery from `.ccsync-trash` without mentioning that `file_moves` section 4b shares that folder and its 14-day expiry.
- **Recommendation:** update section 7 to point at the protection panel and the alert, and add the 4b trash to the recovery list.
- **Known:** not recorded.
