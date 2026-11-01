# Pre-launch resilience pass, lens res-storage (storage failure)

Date 2026-10-06, working tree on top of 08b40eb. Read-only review.

**Covered:** NAS pool / dashboard volume capacity (`alerts._check_data_disk`,
`notices._check_dashboard_space`, `protection.py`, `server/check_health.py`,
`server/setup_snapshots.py`); editor disk space (`lane_guard.disk_report`,
`DiskFloorLatch`, `prune_trash`, `_remove_tree`, `notices._check_machine_space`,
`alerts._check_disk_low/_check_disk_park`, fleet grid DISK chip); lane error
surfacing (`rclone_lane._run_once_locked` result handling, `sync/base.LaneStatus`
`state_since`, `alerts._check_lane_error/_check_red_unexplained`); sync-root
presence (`root_guard.probe_root`, `access_is_blocked`, tray sentences);
Resolve save point / journal on a full system drive (`resolve_bridge.save_project`,
`_before_mutation`, `resolve_journal.record/save_point_due`); atomic writes and
latch persistence; fixer / proxy_gen / jobs_media failure cleanup; filename byte
caps (ytdl, links); long-path handling; installer root validation.
Compared against `docs/RESILIENCE_SWEEP_2026-08-28.md` (theme D, K, OPS-2) and
the 2026-09-03 sweep, and KNOWN_BUGS (SYS-5, SYNC-7, SYNC-16, UX-1, UX-14, REL-5,
DASH-5, SYNC-2, SYNC-3, SYNC-11, MEDIA-21 are FIXED and not re-reported).

**Not covered:** live rclone behaviour against a real SFTP target (case-only
rename semantics are from rclone's documented march rules, not probed); Synology
btrfs quota behaviour; macOS exFAT normalisation; Syncthing's own disk-full
behaviour beyond its default `minDiskFree`.

### res-storage-1 - The NAS footage pool's free space is never measured, and the one server-side check reads ZFS percentages that understate a full pool

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/alerts.py:136-139` and `:2143-2163` (`_check_data_disk`), `dashboard/src/ccsync_dashboard/notices.py:58` and `:1065-1095` (`_check_dashboard_space`), `dashboard/src/ccsync_dashboard/protection.py:682-690`, `server/check_health.py` (no capacity check), `server/setup_snapshots.py:25` (24 hourly + 30 daily)
- **What:** Nothing measures the free space of `projects_dir`, the dataset lane A uploads camera originals into. The only server-side checks look at the dashboard's own `db_path` parent. `data_disk` works in percentages only. On ZFS, `statvfs` reports a dataset's size as its own used space plus pool free space, so a small apps dataset on a nearly full pool still looks mostly free. With about 60 GB referenced, the alert turns amber at roughly 6.7 GB of pool space left and red at roughly 3.2 GB. The notice floor is an absolute 2 GB. The protection panel tells the operator to check the pool's free space by hand, but it never measures it.
- **Scenario:** A customer's 40 TB pool sits behind 30 days of daily snapshots. Editors delete or replace 2 TB of originals, and the snapshots keep all of those blocks. Lane A keeps uploading hundreds of GB a day. The first message anyone gets arrives with single-digit GB left. Its fix sentence says "Delete old builds on Settings, Packages", which points at the wrong thing. Within minutes, lane A fails on every file on every machine, with raw rclone text. Snapshots stop. A ZFS pool at 100 % is hard to delete out of because the snapshots pin the blocks. The dashboard's SQLite, on the same pool, starts failing its writes. Footage that cannot upload stays only on editors' laptops.
- **Recommendation:** Add a `nas_pool` alert and notice that runs `shutil.disk_usage(projects_dir)` and judges the absolute free bytes, not a percentage. Where the TrueNAS API is reachable, also read pool `size/allocated/free` and the tree dataset's `usedbysnapshots`. Warn at 80 % pool use or 1 TB free, whichever comes first, and turn red at 90 %. Name the snapshot share in the sentence. Change `data_disk` from percent-only to an absolute floor as well. Put the figure on the protection panel and the home page. Add the matching `check_health` capacity line that OPS-2 proposed.
- **Known:** OPS-2 (docs/resilience-sweep-2026-08-28/OPS.md), still OPEN. The ZFS percentage problem in `data_disk` is new.

### res-storage-2 - The system drive's free space is measured and then never acted on, and a full system drive takes away Resolve's undo net

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/sync/lane_guard.py:890-947` (`system_drive_path`, `disk_report`), `dashboard/src/ccsync_dashboard/api.py:8208-8213`, `dashboard/templates/partials/fleet_grid.html:143` (the only reader), `dashboard/src/ccsync_dashboard/notices.py:615-691`, `alerts.py:1537-1580`, `companion/src/ccsync_companion/resolve_bridge.py:2236-2335`, `companion/src/ccsync_companion/resolve_journal.py:528-534, 543-560`
- **What:** `system_free_bytes` exists, according to its own docstring, because "a full BOOT disk breaks Resolve, Syncthing and the companion's own log before it breaks a lane". The dashboard stores it but shows it only inside the DISK chip's tooltip. That chip is drawn only when the sync drive is already amber or red. No notice, alert, `blocked` reason or tray line uses it. On a full system drive, Resolve's project database, Syncthing's index database, `~/.ccsync` latches and the companion log all live on that volume. `save_project` then fails at `ExportProject`, which is best effort by design, and the relink goes ahead. `resolve_journal.record` fails too, logs a warning and returns. So an unprompted relink pass (proxy repoint, fixer, file move relink) runs with no rollback copy and no journal. `save_point_due` has already claimed the 15-minute slot before the export failed.
- **Scenario:** A Mac editor's tree is on an external SSD with 900 GB free, while the internal disk is at 300 MB because of Resolve caches. The fleet grid shows no chip. Syncthing stops on a database write error, which looks like "engine down" with no reason given. The companion relinks 40 clips after a server-side file move, and nothing exists that could undo it.
- **Recommendation:** Judge `disk_system_free_bytes` with its own floor (for example 10 GB) in `health.disk_status`, `machine_disk_low` and a `system_disk_low` alert, and add a `system_disk_full` reason to `sync_guard.blocked`. On the companion, refuse unprompted Resolve mutations when the journal directory cannot be written (probe-write before the burst). Claim the save-point slot only after an export succeeded (the open RES-13 from the 2026-08-28 sweep).
- **Known:** RES-13 (2026-08-28 sweep, "save_point_due burns the slot"): there is no fix entry in KNOWN_BUGS, so it is treated as open. The system-drive half is new.

### res-storage-3 - Storage errors on lane A arrive as raw rclone text, and a lane that fails every pass never meets the one-hour alert clocks

- **Severity:** high
- **Confidence:** CONFIRMED (code path traced; not run live)
- **Where:** `companion/src/ccsync_companion/sync/rclone_lane.py:4312-4313` (every pass sets `STATE_SYNCING`), `:4517-4541` (raw `_most_informative_error`), `:4542-4550` (the next clean project sets `STATE_IDLE`), `companion/src/ccsync_companion/sync/base.py:81-84` (`state_since` re-stamped on every state change), `dashboard/src/ccsync_dashboard/alerts.py:1760-1780` (`_check_lane_error`, needs `state_since` at least 1 h old), `:3882-3914` (`_check_red_unexplained`)
- **What:** Lane A runs one project per turn. Every pass sets `syncing` at start. A pass that fails sets `error` with the raw rclone line. The next project's clean pass sets `idle`. `state_since` is re-stamped on each change, so an `error` that comes back every pass never ages past the idle interval, and `lane_error` (1 h) never fires. `red_unexplained` fires only if the evaluation happens to land on a red moment. Nothing classifies storage errors such as "permission denied" (a NAS ACL or chown change, a new project folder created as root over SMB), "no space left", a read-only file system or "file name too long" (a name over 255 bytes on the NAS that is legal on NTFS, such as about 90 CJK characters). There is also no alert for originals that have been owed to the NAS for N hours.
- **Scenario:** A customer's admin re-creates `2026/Ep7/Footage` from a NAS shell as root. From then on, every editor's lane A pass for Ep7 fails with `sftp: "permission denied"`, while their other projects upload fine. The grid flickers red and amber with a raw sftp string. No alert fires. The camera originals for Ep7 exist only on editor laptops for days, which is exactly the loss window the product exists to close.
- **Recommendation:** Keep a per-project failure streak in lane A, keyed by subpath and the classified error, and report it in `sync_guard` (for example `upload_blocked: {project, reason, since, files}`). The streak should survive passes of other projects. Classify ENOSPC, EACCES/EPERM, EROFS and ENAMETOOLONG into sentences that name the fix and who must act ("the server refuses this folder: ask your admin to run the permissions repair"). Base `lane_error` on a since-time that holds while the same error class keeps coming back. Add an "originals owed to the server for more than 24 h" alert from the existing `[ QUEUED ]` owed-upload data.
- **Known:** none.

### res-storage-4 - On Windows a sync drive that comes back under another letter reads as "disconnected" forever, and any drive that takes the old letter is accepted as the tree

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/root_guard.py:50-52, 426-432` (Windows is `isdir()` only, no volume record), `companion/src/ccsync_companion/tray.py:519-560` ("disconnected ... Plug it back in")
- **What:** The macOS half records a volume UUID and tells `misplaced` apart from `absent`. On Windows, `probe_root` is a plain `os.path.isdir(local_root)`, and no volume identity is recorded. Windows gives a newly connected volume the lowest free letter. If a card reader or another SSD took `E:` while the sync drive was out, the sync drive comes back as `F:`. The tray then keeps telling the editor to plug in a drive that is already plugged in, and nothing ever finds it. The reverse case is not checked either: a different drive at `E:` that has a `Creators_Club` folder is treated as the tree. That could be the editor's previous sync SSD or a clone made while upgrading drives. Lane A then uploads that drive's stale originals to the NAS, resurrecting footage that was deliberately deleted. Lane B rewrites the drive. Lane C pushes old project files, which only server-side staggered versioning catches.
- **Scenario:** An editor ingests a card through a reader while the T7 is unplugged, then plugs the T7 back in. Sync stays paused with "the drive is disconnected" until someone opens Disk Management. A non-technical editor at a customer site cannot do that unaided.
- **Recommendation:** Record the volume serial or GUID (`GetVolumeInformationW` / `GetVolumePathNameW`) in `volume.json` on Windows, as the Mac path already does. When the root is absent, look for the same volume under other letters and report `misplaced` with the new letter. When the root is present, refuse a different volume (`ROOT_MISPLACED` / "a different drive is at E:"). Better still, add a tree-identity marker file (`.ccsync-tree` holding the machine id and site id) at `local_root` and check it before any lane runs.
- **Known:** none.

### res-storage-5 - Windows long paths: the installer never enables them, and the Python-side walks silently skip or fail on deep trees

- **Severity:** medium
- **Confidence:** PLAUSIBLE (this rig has `LongPathsEnabled=1`, so it cannot reproduce; the absence was confirmed by grep)
- **Where:** `installer/windows_bootstrap.ps1` (no `LongPathsEnabled`), `companion/src/ccsync_companion/manifest.py:186-210` (`os.walk` without `onerror`, `size_fn` OSError leads to `continue`), `companion/src/ccsync_companion/sync/lane_guard.py:1155-1170` (trash sizing walk) and `:1353-1360` (`_remove_tree` uses `shutil.rmtree`), `rclone_lane._backup_dir` (trash path = `<root>/.ccsync-trash/<ts>/Projects/<rel>/<orig rel>`, about 40 characters longer than the tree path)
- **What:** rclone and Syncthing handle paths over 260 characters on their own. The companion's Python code needs the `LongPathsEnabled` registry value, which is 0 on a stock Windows 10 or 11, and nothing sets it or warns about it. `os.walk` swallows the error for an over-long directory, so its subtree drops out of the manifest without a word: the dashboard believes the files are not on that machine. Trash copies are about 40 characters deeper than the original, so a proxy that is legal in the tree can become unprunable and uncounted in the trash. The fixer copy, file moves and proxy_gen would raise on the same paths.
- **Scenario:** Deep episode trees plus long Chinese camera-day folder names push a few proxies past 260 characters. They download fine. Their trashed copies are never pruned and are not counted against `trash_max_bytes`. The manifest under-reports the project, and the project page shows a phantom download backlog.
- **Recommendation:** Have `windows_bootstrap.ps1` set `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled=1` (it already runs elevated), confirm that the frozen exe's manifest declares `longPathAware`, and have the companion report the registry value in diagnostics. In the meantime, pass an `onerror` to the manifest and trash walks so a skipped subtree is counted and reported, not dropped silently.
- **Known:** none.

### res-storage-6 - A read-only sync root reads as "present", and only the Mac installer checks the filesystem type

- **Severity:** medium
- **Confidence:** CONFIRMED (absence traced)
- **Where:** `companion/src/ccsync_companion/root_guard.py` (no writability probe; `access_is_blocked` covers macOS EACCES/EPERM reads only), `companion/src/ccsync_companion/app.py` `_BLOCKED_ORDER` (no read-only reason), `installer/windows_bootstrap.ps1:470-510` (free space only), `installer/macos_bootstrap.sh:2254-2257` (warns on non-APFS)
- **What:** Several real cases leave the drive mounted and readable but not writable: a Mac with an NTFS-formatted SSD (macOS mounts NTFS read-only), an exFAT drive that macOS remounts read-only after an unclean eject, a write-protected or BitLocker-locked-read-only drive on Windows, and a NAS-side read-only dataset for a wired machine. `probe_root` answers `present`. Lane B and lane C then fail per file with EROFS or "access denied" in raw text, and `sync_guard.blocked` has no reason to give. On Windows, nothing checks for FAT32, which cannot hold files over 4 GB, or for exFAT.
- **Scenario:** A Mac editor is handed an NTFS-formatted shuttle drive as their sync drive. The install completes, the tray says syncing, and every proxy download fails with "read-only file system" on every pass.
- **Recommendation:** Add a cheap write probe (create and delete `.ccsync-write-probe` once per root-guard cycle, or on each lane B pass start) that maps EROFS, EACCES and EPERM to a new `root_readonly` state and `blocked` reason, with its own sentence. Make both installers refuse or warn on FAT32 and read-only volumes. On macOS, refuse NTFS outright.
- **Known:** none.

### res-storage-7 - A case-only rename on an editor's machine uploads a second copy of the originals to the NAS

- **Severity:** low
- **Confidence:** PLAUSIBLE (based on rclone's documented march keying; not probed against SFTP)
- **Where:** `companion/src/ccsync_companion/sync/rclone_lane.py:2030-2042` (lane A `copy --ignore-case --ignore-existing`; `--ignore-case` is a filter flag, not `--ignore-case-sync`), `server/` (the tree dataset's `casesensitivity` is never read or recorded)
- **What:** rclone matches source and destination names case-insensitively only when the destination backend is case-insensitive or `--ignore-case-sync` is set. An SFTP destination on a case-sensitive ZFS dataset is neither. If an editor renames `day 1` to `Day 1` in Explorer, Windows treats it as the same folder, but lane A sees new names and uploads every original under the new casing. The NAS then holds both trees. Lane B on other Windows machines collapses the pair to one local folder and logs duplicates, and the dashboard inventory counts the footage twice. Whether this happens depends on the dataset's `casesensitivity`, which the TrueNAS SMB preset sets to insensitive. The setup never records that value.
- **Scenario:** One tidy-minded editor recapitalises a 600 GB shoot folder. Lane A re-uploads 600 GB over a remote link, and the pool loses 600 GB that nobody can see.
- **Recommendation:** Record the tree dataset's `casesensitivity` during setup. If it is sensitive, add `--ignore-case-sync` to lane A's `copy` (lane A never deletes, so ignoring case loses nothing) and have the dashboard inventory walk flag case-only duplicate siblings.
- **Known:** none.

### res-storage-8 - No antivirus guidance or exclusions for a tree of multi-GB media writes

- **Severity:** low
- **Confidence:** PLAUSIBLE
- **Where:** `installer/windows_bootstrap.ps1` (no `Add-MpPreference -ExclusionPath`, no Controlled Folder Access check), `docs/EDITOR_SETUP.md`, `companion/src/ccsync_companion/proxy_gen.py:1792-1799` and `jobs_media.py:419-424` (a failed `os.replace` on a sharing violation is reported and left as `.partial`, not retried after a short wait)
- **What:** Real-time scanning of every multi-GB `.mov` that rclone, Syncthing or ffmpeg writes costs CPU and briefly holds files open. `os.replace` then hits WinError 5 or 32. Proxy publication and media jobs treat that as a failure instead of retrying after a second. Customer sites often run a third-party endpoint product that quarantines unsigned binaries. The companion is unsigned (`-AllowUnsignedBinary`). Nothing in the setup docs tells the customer's IT team what to exclude.
- **Scenario:** A customer's endpoint product locks each new proxy for 1 to 3 seconds. A good share of proxy_gen publishes fail and leave `.partial` files that are only reported, and the base rig's proxy generation crawls.
- **Recommendation:** Add a short retry with backoff (3 tries, 0.5 to 2 s) around `os.replace` for the sharing-violation and access-denied errors in `proxy_gen._publish` and `jobs_media`. Document the exclusions to request (the sync root, `%LOCALAPPDATA%\ccsync`, the rclone and Syncthing binaries). Optionally have the installer offer the Defender exclusion for the sync root.
- **Known:** none.
