# Pre-launch resilience pass 2026-10-06
Resilience pass of the pre-commercial-launch review at HEAD `08b40eb` plus the
uncommitted working tree as it stood on 2026-10-06 (alert-kind selection,
companion fixes, `docs/ZERO_DOWNTIME_DEPLOY.md`). The owner asked for "every
single thing that should be looked at or changed before going live
commercially"; this pass assumed things go wrong at a customer site we cannot
reach and traced, per failure mode, whether every component recovers by
itself, degrades safely, tells the right person, and never loses or corrupts
footage or project data.

How it ran: twelve Opus hunters on disjoint failure lenses - `res-network`,
`res-storage`, `res-crash` (power loss and torn writes), `res-dataloss`,
`res-upgrade`, `res-concurrency`, `res-resolve`, `res-deps` (third-party
dependencies), `res-time-scale` (clocks, retention, scale), `res-recovery`
(backup, restore, identity loss), `res-observability` and
`res-security-adversity`. Each checked KNOWN_BUGS.md, the 2026-08-28 and
2026-09-03 resilience sweeps and the 2026-09-24 hunt so only open or new items
are reported. Every critical and high was then put to one adversarial Opus
verifier told to refute it. This file merges duplicates across hunters.
Read-only throughout except the report files; probes ran in the scratchpad
against repo code only (no NAS, dashboard, Tailscale, Resolve or SMTP). Raw
reports: `docs/prelaunch-review-2026-10-06/resilience/hunters/`;
machine-readable merge: `resilience/results.json`.

**Tally: 116 raw findings (0 critical, 31 high, 59 medium, 26 low). After verification and merging duplicates: 111 distinct items (0 critical, 5 high, 80 medium, 26 low).**

| Hunter | Raw H | Raw M | Raw L |
|---|---|---|---|
| res-network | 0 | 4 | 3 |
| res-storage | 2 | 4 | 2 |
| res-crash | 1 | 5 | 2 |
| res-dataloss | 4 | 2 | 3 |
| res-upgrade | 4 | 4 | 2 |
| res-concurrency | 0 | 6 | 4 |
| res-resolve | 3 | 8 | 2 |
| res-deps | 3 | 5 | 3 |
| res-time-scale | 1 | 6 | 3 |
| res-recovery | 6 | 4 | 1 |
| res-observability | 1 | 6 | 1 |
| res-security-adversity | 6 | 5 | 0 |
| **Total** | **31** | **59** | **26** |

**Verifier pass on the 31 highs: 5 CONFIRMED as high, 25 real but DOWNGRADED to medium, 1 DOWNGRADED to low, 0 refuted.** The common reasons for a downgrade were: the failure is loud rather than silent, no footage is lost (originals stay on editors' machines), a documented or shell-level recovery exists, the trigger needs a second compromise or a rare event, or the gap is already recorded as unbuilt (the appliance release key). Mediums and lows were not verified; earlier passes refuted about 3% of theirs.

Duplicates merged (5): res-network-1 + res-concurrency-1 (job leases across an outage); res-network-4 + res-deps-4 (server off the tailnet); res-network-7 + res-deps-2 (Syncthing self-upgrade); res-dataloss-3 + res-time-scale-3 (future-dated mtimes); res-recovery-6 + res-security-adversity-6 (the release key). Merged items keep the higher severity and cite every source.

## 1. Stop-ship

None. No hunter rated anything critical, and no high was raised on verification. The nearest are the two removal-gate data-loss items below (PL-RES-01, PL-RES-02): they need an editor to remove a project, but the dialog promises nothing will be lost before a permanent delete.

## 2. Before the first paying customer

Five verified highs. Two lose footage permanently behind a false promise, two leave a fleet or a dashboard dead after a bad release with nobody on site to fix it, and one takes the whole fleet offline on a predictable date.

### PL-RES-01 - Remove from this machine deletes an upload-only project's non-video files (WAVs, stills, docs) under a dialog promising nothing will be lost
- Sources: res-dataloss-1. Verdict: CONFIRMED by verifier.
- Where: `companion app.py:6131-6274 (removal_blockers), app.py:6380-6390 (rmtree); tray.py:1925-1932; sync/rclone_lane.py:941-974`
- What: Upload-only runs lane A alone, and lane A carries only video extensions. removal_blockers checks only lane A for an upload-only project and skips lane C, so non-video files are counted by nobody. The dialog says everything reached the server, then shutil.rmtree deletes permanently (not to trash).
- Scenario: A shooter ticks a shoot UPLOAD ONLY, dumps a card (.mov + recorder .wav + .jpg), waits for lane A, formats the card, removes the project to free space. All WAVs and stills are gone.
- Recommendation: For upload-only projects, enumerate files no lane carries and block naming them behind the typed override; never claim everything reached the server when only video was checked. Decide UPLOAD_ONLY_TICK.md section 5 (widen lane A for upload-only) before launch.
- Known: Not in KNOWN_BUGS; the sync limit is documented, the removal consequence is not.

### PL-RES-02 - Removal gate ignores the WON'T UPLOAD set: a name collision or same-name re-export passes and the only copy is deleted
- Sources: res-dataloss-2. Verdict: CONFIRMED by verifier.
- Where: `companion sync/rclone_lane.py:1792-1854 (scan_pending_uploads keeps --ignore-existing), :1857 (scan_size_mismatches, report-only); app.py:6131-6274; tray.py:1925-1938`
- What: Lane A is copy --ignore-existing, so a local file whose name already exists on the NAS never uploads. scan_size_mismatches already finds these (the [ WON'T UPLOAD ] chip) but the removal gate never calls it; its dry run counts them as uploaded.
- Scenario: An editor fixes audio and re-renders under the same name, or two cameras write C0001.MP4 into one folder. Removal: 0 pending, 'nothing will be lost', rmtree deletes the only copies.
- Recommendation: Run scan_size_mismatches for the project and each borrowed subpath inside removal_blockers; block on any non-zero count with names behind the typed override; fail closed if it cannot run.
- Known: Skipped-exists known (COMMERCIAL_READINESS item 9, SYNC_SAFETY section 5); its interaction with removal is not recorded.

### PL-RES-03 - A companion build that fails at start-up is never rolled back, and no release step ever launches the frozen exe
- Sources: res-upgrade-1. Verdict: CONFIRMED by verifier.
- Where: `companion app.py:12036-12139 (run() before the start record), app.py:11758 (note_version_start); supervisor.py:132-137,184 (exit 1 not relaunched); upgrade.py:97 (2 s takeover grace), :253-329, :981-1040; tools/release.ps1; .github/workflows/release-windows.yml; tools/release_macos.sh`
- What: The APP-5/REL-2 auto-rollback only counts a start once CompanionApp.run() is reached. An import error, a missing frozen module or an exception in __init__ is never counted; Python-level deaths exit 1, which the supervisor treats as deliberate and never relaunches; the 2 s hand-off grace is shorter than onefile extraction, so the old build stands down. No pipeline runs the built binary even once.
- Scenario: A build missing a lazily imported module is published; every auto/pushed machine swaps it in, it exits 1 after the predecessor stands down, nothing relaunches or reverts while .old sits unused. Sync and reporting stop until a human renames the file on each machine.
- Recommendation: Gate release.ps1, release-windows.yml and release_macos.sh on a --self-test launch of the frozen exe. Record the start at the very top of run() in a stdlib helper and count any unclean exit as a failed start. Have the supervisor relaunch exit-1 deaths of a just-upgraded build. Replace the 2 s grace with a 'started' marker waited for up to ~30 s.

### PL-RES-04 - A dashboard update that boots but cannot serve is never reverted, because nothing restarts the wedged process
- Sources: res-upgrade-3. Verdict: CONFIRMED by verifier.
- Where: `dashboard dashboard_update.py:488-514 (start_boot_watchdog logs and returns); deploy/select_code_root.py (revert only at the next start); deploy/compose.image.yaml:345-356 (healthcheck only marks unhealthy)`
- What: REL-6 leaves boot_attempts standing when the health probe fails, but the process keeps running, so there is never a next start and the revert never happens. A lifespan deadlock before the watchdog is armed is not caught at all; every page, including rollback, is dead.
- Scenario: An unattended OTA delivers a bundle with a lifespan deadlock or a 500ing health route. The container sits 'Up (unhealthy)' indefinitely; companions get no replies; the customer sees a dead dashboard with no vendor access.
- Recommendation: In volume-tree mode, exit the process (os._exit, even 75) when the boot probe fails so run.sh/Docker re-runs select_code_root and the counter advances to a revert. Add a lifespan deadline so a hang before arming is caught. Keep log-only for image code.
- Known: REL-6 (marked FIXED); this residual is its own symptom.

### PL-RES-05 - Nothing watches the server's own tailnet: the appliance node joins interactively and expires on Tailscale's schedule, taking the whole fleet with it; a fleet-wide disconnect surfaces only as per-machine machine_silent after 24 h
- Sources: res-deps-4, res-network-4. Verdict: CONFIRMED by verifier (res-deps-4); res-network-4 not verified (hunter: CONFIRMED).
- Where: `dashboard/deploy/compose.appliance.yaml:357-421; dashboard tailscale_local.py:105-122 (summarise drops Self.KeyExpiry); setup_engine.py:1029-1126; alerts.py ALERT_KINDS (no tailnet kind, no correlated-silence rule)`
- What: The tailnet is the only path between editors and server (dashboard via Serve, SFTP, Syncthing, Funnel client links). The appliance node logs in as a user device with no tagged auth key, so key expiry (180 days default) applies. No alert reads BackendState, KeyExpiry or Serve config, no doc says to disable expiry, and there is no 'most machines went silent at once' rule. The dead-man heartbeat is opt-in.
- Scenario: Day 180, or a TrueNAS update stops the Tailscale app: every companion stops reporting, lanes A/B/C stop fleet-wide, client links die. The dashboard mails one 'a computer has gone quiet' per machine after 24 h, never naming the cause, and the admin cannot open the tailnet-only dashboard.
- Recommendation: Read Self.KeyExpiry/BackendState/Serve in the collector and alert 14 days ahead with the fix ('disable key expiry for this node'). Have the wizard tell the admin to disable expiry or use a tagged key. Add one correlated fleet-silence alert (e.g. >=50 % of machines active in the last day silent for 30 min) naming the server's network. Have companions report their own KeyExpiry. See also PL-RES-52 (heartbeat off by default).

## 3. Soon after launch

Eighty mediums, grouped by theme. Items marked "DOWNGRADED from high" were real but judged not to block the first customer; they are the first to schedule.

### Footage and project data safety (13)

#### PL-RES-06 - Future-dated clips (camera clock ahead or on home timezone) silently never upload or get proxies, and they and files under 120 s old are invisible to the removal gate
- Sources: res-dataloss-3, res-time-scale-3. Verdict: DOWNGRADED from high by verifier (res-dataloss-3); res-time-scale-3 not verified (hunter: CONFIRMED).
- Where: `companion sync/rclone_lane.py:470-479, :2038-2049 (--min-age 120s), :1820-1824 (gate reuses argv), :6792 (express age gate); proxy_scan.py:446; proxy_gen.py:1836`
- What: Every age gate computes now - mtime; a future mtime is never old enough (probed with rclone 1.74.4). Card copies keep camera mtimes and FAT stores zone-less local time. The lane shows green with nothing transferred; the removal gate counts the files as nothing pending.
- Scenario: A crew in Los Angeles with cameras on Taipei time: nothing uploads or proxies for 15 h with a green tray. A camera reset to a future year: footage stays on one laptop for a year. A removal in that window deletes it.
- Recommendation: Drop --min-age from the removal gate's dry run. Detect mtime > now + tolerance in the manifest walk, report the files by name (sync_guard field, tray line, grid chip), and upload them via the express path using size stability alone.
- Known: Not recorded (DUI-17 / CLOCK AHEAD cover the machine clock). bug-sync-1 in the bug pass reported the same.

#### PL-RES-07 - Removal gate's lane C half trusts Syncthing's index without a scan: unscanned edits and paused (halted) folders read as 100 %
- Sources: res-dataloss-4. Verdict: not verified (hunter: PLAUSIBLE).
- Where: `companion app.py:6234-6268; sync/syncthing_admin.py:757-769, 593-600; sync/lane_guard.py HaltState`
- What: /rest/db/completion measures against the local index; unscanned files cannot lower it. A fleet or local halt pauses every lane C folder, so nothing is indexed. The gate never blocks on a paused folder and never requests a scan.
- Scenario: A halt stays on for two days while an editor adds VO under Audio/, then removes the project: completion 100, rmtree deletes two days of audio.
- Recommendation: Fail closed when the folder is paused or not idle; otherwise POST /rest/db/scan, wait bounded for idle, then read completion.

#### PL-RES-08 - Every editor's SMB login can delete camera originals on the NAS; no recycle bin, no shadow copies, and the grade swap puts editors straight on the tree
- Sources: res-dataloss-5. Verdict: DOWNGRADED from high by verifier.
- Where: `server/setup_tree.py:21-27,183 (2770 editors); server/backends/synology.py:90-92 (EDITORS_ACE has d/D), :1091 (recycle bin off); companion drive_swap.py:445-470; docs/SYNC_SAFETY.md section 7`
- What: Group delete is normal NAS editing, but nothing softens it: no SMB recycle bin, no Previous Versions, no warning in the grade swap that deletes there are fleet-wide. SYNC_SAFETY section 7 assumes only an admin deletes on the NAS. Snapshot coverage is already surfaced (invariant 9, protection panel), and lane B trash bounds proxy fallout.
- Scenario: A remote colourist swaps to the server and deletes a 'duplicate' clip folder in Explorer; originals vanish for the whole fleet and recovery needs an admin snapshot restore.
- Recommendation: Enable an admin-only SMB recycle bin and shadow copies on the tree share and show their state on the protection panel; warn in the grade swap that deletes there are permanent for everyone; correct SYNC_SAFETY section 7. Consider deny-delete on Projects/** only as a later option.
- Known: Not recorded.

#### PL-RES-09 - publish_db.py --which music still overwrites every fleet-ingested track and pending queue row in the live index
- Sources: res-dataloss-6. Verdict: not verified (hunter: CONFIRMED).
- Where: `server/publish_db.py:93-134 (drain False for music), :375-416; music/web/musicweb/ingest_batches.py:983-1000`
- What: The live music.db holds companion inline-ingested tracks and ingest_queue rows that exist nowhere else; the publish renames the base rig's copy over it with no drain and no check while under 10 % of tracks are lost.
- Scenario: Owner re-indexes and publishes as DEPLOY.md says; 20 editor-ingested tracks and all pending queue rows vanish silently.
- Recommendation: Refuse with names when pending queue rows or live tracks missing from the candidate exist (unless --allow-clobber-queue); better, a music drain-and-merge like broll_drain.py.
- Known: MEDIA-4 (2026-08-28) and MUSIC-6 (2026-09-03), both still OPEN.

#### PL-RES-10 - Lane A storage errors arrive as raw rclone text, and an error that recurs every pass never meets the one-hour alert clocks
- Sources: res-storage-3. Verdict: DOWNGRADED from high by verifier.
- Where: `companion sync/rclone_lane.py:4312-4313, :4517-4550; sync/base.py:81-84; dashboard alerts.py:1760-1780, :3882-3914`
- What: Each project pass resets the lane state, so state_since is re-stamped and lane_error (1 h) never fires for a per-project error that keeps recurring while other projects succeed. EACCES/ENOSPC/EROFS/ENAMETOOLONG are not classified; no alert exists for originals owed to the NAS for N hours. red_unexplained and the red-lane diagnostics upload cover the single-project case.
- Scenario: An admin re-creates a project's Footage folder as root; every editor's lane A fails for that project with 'permission denied' while other projects upload. The grid flickers, no alert fires, originals sit on laptops for days.
- Recommendation: Per-project failure streak keyed by subpath and error class, reported in sync_guard (upload_blocked with since); classify the storage errno family into sentences naming who must act; base lane_error on a since-time that holds across passes; add an 'originals owed to the server > 24 h' alert.

#### PL-RES-11 - On Windows a sync drive back under another letter reads 'disconnected' forever, and any drive that takes the old letter is accepted as the tree
- Sources: res-storage-4. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion root_guard.py:50-52, :426-432; tray.py:519-560`
- What: macOS records a volume UUID; Windows checks only os.path.isdir(local_root). A drive that returns as F: is 'plug it back in' forever; a different drive at E: holding an old Creators_Club folder is accepted, so lane A uploads stale originals and lane C pushes old project files.
- Scenario: A card reader takes E: while the T7 is out; sync stays paused until someone fixes the letter in Disk Management. Or an old clone SSD is plugged in at E:.
- Recommendation: Record volume serial/GUID in volume.json on Windows; when absent, search other letters and report 'misplaced'; refuse a different volume. Better: a .ccsync-tree identity marker checked before any lane runs.

#### PL-RES-12 - Windows long paths: the installer never enables them, and Python-side walks silently skip or fail on deep trees
- Sources: res-storage-5. Verdict: not verified (hunter: PLAUSIBLE).
- Where: `installer/windows_bootstrap.ps1; companion manifest.py:186-210; sync/lane_guard.py:1155-1170, :1353-1360`
- What: rclone and Syncthing cope; the companion's Python needs LongPathsEnabled=1, which is off by default. os.walk swallows the error so subtrees drop out of the manifest; trash paths are ~40 chars deeper so proxies become unprunable; fixer, file moves and proxy_gen would raise.
- Scenario: Deep episode trees with long CJK folder names: phantom backlog on the dashboard and trash that is never pruned or counted.
- Recommendation: Set LongPathsEnabled=1 in the (elevated) bootstrap, confirm the exe is longPathAware, report the value in diagnostics; pass onerror to the walks so skipped subtrees are counted.

#### PL-RES-13 - A read-only sync root reads as present, and only the Mac installer checks the filesystem type
- Sources: res-storage-6. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion root_guard.py; app.py _BLOCKED_ORDER; installer/windows_bootstrap.ps1:470-510; installer/macos_bootstrap.sh:2254-2257`
- What: No writability probe: NTFS on a Mac, exFAT remounted read-only after an unclean eject, or a locked drive all report present; lanes B and C fail per file with raw EROFS text; no blocked reason. Windows installer never checks FAT32/exFAT.
- Scenario: A Mac editor is handed an NTFS shuttle drive; install completes, every proxy download fails with 'read-only file system' every pass.
- Recommendation: Cheap write probe per root-guard cycle mapping EROFS/EACCES/EPERM to a root_readonly state and blocked reason; both installers refuse or warn on FAT32 and read-only volumes, and macOS refuses NTFS.

#### PL-RES-14 - Companion safety state is not fsynced; a torn latch after power loss reads as 'no state' and fails open
- Sources: res-crash-3. Verdict: not verified (hunter: PLAUSIBLE).
- Where: `companion sync/lane_guard.py:171-215; file_moves.py:1042-1088; resolve_journal.py:351-388; upgrade.py:713-760; sync/rclone_lane.py:359-367; selection.py:388`
- What: tmp + os.replace without fsync can come back NUL-filled or empty after power loss. Every reader treats that as absent: the lane B breaker and shrink baseline are lost, file-move intents vanish, the Resolve undo journal empties and is then overwritten.
- Scenario: The breaker trips during a power event that makes the NAS look empty; the PC loses power; on restart the latch is off and the first lane B pass has no shrink baseline.
- Recommendation: One atomic_write_json helper (write, flush, fsync, replace, dir fsync on POSIX) for every latch, ledger and journal; readers distinguish absent from unreadable, an unreadable latch stays TRIPPED, unreadable ledgers are renamed aside before rewrite.
- Known: comp-sync-1 / sync-safety-8 fixed atomicity; the power-loss fail-open half is new.

#### PL-RES-15 - Footage and proxies written without fsync can survive a power loss full-size but zeroed, and size-only comparisons then spread the damage fleet-wide permanently
- Sources: res-crash-4. Verdict: not verified (hunter: PLAUSIBLE).
- Where: `companion fixer.py:566-686, :1438-1442; ytdl_executor.py:1787-1822; jobs_media.py:401-425; proxy_gen.py:1794; broll_ingest.py:2611; sync/rclone_lane.py:2016-2055, :1877-1896, :2312-2345`
- What: Media writers rename a complete file but never fsync; the rename can reach disk before the data. FIX ALL keeps the source's old mtime so --min-age does not hold it; lane A uploads once, --ignore-existing never replaces it, the size audit cannot see it, lane B never re-fetches.
- Scenario: FIX ALL lands a 40 GB card dump, Resolve is relinked, power drops before the cache flushes: corrupted frames reach the NAS within minutes and every editor on the project.
- Recommendation: fsync the destination before every tmp/.partial -> final rename of media; sampled-hash (or --checksum) on lane A's first upload of files this machine wrote; re-verify recent fixer copies after an unclean shutdown.

#### PL-RES-16 - A case-only rename interrupted between its two renames strands the file as .ccsync-move-<pid>-<name>, and the redelivered command reports success
- Sources: res-crash-6. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion file_moves.py:340-370 (_rename_case_only), :686-724 (missing-src branch); sync/rclone_lane.py:115-123, :2133`
- What: On a case-insensitive disk, if the process dies (or both the second rename and the restore fail) neither src nor dest exists; the resume answers 'nothing at the old path', no relink, no sweep restores the staging file, and lane A and the fixer ignore dot-names.
- Scenario: An admin fixes a clip's spelling while a laptop hibernates mid-rename or Resolve holds the file: footage invisible, clip Media Offline, MOVES history says this computer followed.
- Recommendation: Before answering 'nothing at the old path', look for .ccsync-move-*-<name> beside src and finish or restore the rename; add the check to the startup tmp sweep and the tray.
- Known: CR-249f (FIXED for the upload half only).

#### PL-RES-17 - The server-side file move checks the destination then renames, and a Linux rename silently replaces anything that arrived in between
- Sources: res-concurrency-5. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard api.py:3159-3265 (move_project_files)`
- What: dest.exists() check, DB row commit, then Path.rename (rename(2) replaces atomically). Threadpool route, nothing serialises moves.
- Scenario: Two producers both move a C0001.MP4 into Interviews/; the second rename deletes the first clip on the NAS and both moves are recorded as done.
- Recommendation: os.link + os.unlink (EEXIST is atomic) or renameat2 RENAME_NOREPLACE for files; a module lock around check-record-rename; same for directories.

#### PL-RES-18 - The 14-day media age-out deletes the only record that a silent laptop holds originals the NAS never got
- Sources: res-time-scale-6. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard db.py:39, :10273-10275, :5157-5190, :11262; api.py:1340-1347`
- What: After 14 days of silence prune deletes editor_media and editor_media_project, so the machine drops out of every backlog as if it owed nothing; the LOST row shows only ticked projects.
- Scenario: A laptop holding three days of un-uploaded interviews dies on a shoot; three weeks later the project page says no machine owes anything, just before archiving.
- Recommendation: Snapshot the last owed-upload summary onto the machines row before pruning; show it on the LOST row and in the weekly report; alert on a lost machine with owed originals.

### Dashboard backups, restore and recovery (14)

#### PL-RES-19 - The NAS footage pool's free space is never measured, and data_disk's ZFS percentages understate a full pool
- Sources: res-storage-1. Verdict: DOWNGRADED from high by verifier.
- Where: `dashboard alerts.py:136-139, :2143-2163; notices.py:58, :1065-1095; protection.py:682-690; server/check_health.py`
- What: Only db_path's parent is checked, by percentage; on ZFS a small apps dataset on a nearly full pool looks mostly free (amber at ~6.7 GB of pool left). Nothing measures projects_dir. TrueNAS/DSM's own capacity alerts are the only safety net.
- Scenario: A pool behind 30 days of snapshots fills; lane A fails fleet-wide with raw rclone text, snapshots stop, dashboard SQLite on the same pool starts failing. No footage lost (originals stay on laptops), but an outage the product never predicted.
- Recommendation: Add a nas_pool alert/notice measuring projects_dir in absolute bytes plus pool and usedbysnapshots via the API; warn at 80 % or 1 TB free, red at 90 %, name the snapshot share; give data_disk an absolute floor; add the check_health capacity line.
- Known: OPS-2 (2026-08-28) still OPEN; the ZFS percentage problem is new.

#### PL-RES-20 - The system drive's free space is measured and never acted on, and a full system drive silently removes Resolve's undo net
- Sources: res-storage-2. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion sync/lane_guard.py:890-947; resolve_bridge.py:2236-2335; resolve_journal.py:528-534, :543-560; dashboard api.py:8208-8213; fleet_grid.html:143; notices.py:615-691; alerts.py:1537-1580`
- What: system_free_bytes is only a tooltip on an already-amber DISK chip. A full system drive breaks Resolve's DB, Syncthing's index, latches and the log; ExportProject and journal.record both fail best-effort, so unprompted relinks run with no rollback; save_point_due has already burned its slot.
- Scenario: Mac with a roomy external SSD and an internal disk at 300 MB: grid shows nothing, Syncthing stops with no reason, a 40-clip file-move relink runs with no undo.
- Recommendation: Own floor for system free bytes (health, machine_disk_low, system_disk_low alert, system_disk_full blocked reason); refuse unprompted Resolve mutations when the journal cannot be written; claim the save-point slot only after a successful export.
- Known: RES-13 (2026-08-28) open; the system-drive half is new.

#### PL-RES-21 - A damaged dashboard.db has no integrity check, no automatic recovery and no message outside the container log
- Sources: res-crash-5. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard app.py:736-738; db.py:716-726; dashboard_update.py:997-1040, :1263-1288; notices.py:270-273`
- What: Header/schema damage makes migrate raise and the container crash-loop (code rollback cannot help); later-page damage boots with 'malformed' routes, and the notice that would report it writes into the damaged DB. Backups exist only from before code updates; no quick_check anywhere.
- Scenario: After an unclean NAS shutdown the dashboard is down, reports fail, alerts cannot be sent (same process), the customer sees a browser error and nobody is told.
- Recommendation: PRAGMA quick_check before migrate; on failure quarantine with -wal/-shm, try .recover or the newest backup, serve a minimal DEGRADED page and alert from it; daily backup_database into /data/backups.
- Known: CR-10 (operator snapshots) open; detection and recovery new.

#### PL-RES-22 - When a dashboard update has migrated the database, a failing boot can never get back without a shell
- Sources: res-upgrade-2. Verdict: DOWNGRADED from high by verifier.
- Where: `dashboard/deploy/select_code_root.py main() (MAX_BOOT_ATTEMPTS branch, check_tree refusal path), revert_refusal(); db.py:2291-2335; app.py:736-738; dashboard_update.py:1263-1290`
- What: res-fleet-2 refuses a revert into an older schema but nothing replaces it: a partially committed multi-step migration boots the same failing tree for ever; a check_tree refusal (e.g. pubkeys missing after a recreate) boots the image, which raises 'schema is newer' and loops. The refusal text points at a dashboard that is down. Staging rehearses migrations on a copy, so triggers are narrow.
- Scenario: A three-migration bundle trips on a row that arrived after staging; dashboard permanently down; recovery needs docker exec and sqlite3, or a NAS snapshot rollback.
- Recommendation: When a revert is refused on schema and current.json names this apply's backup, have select_code_root restore it (stdlib sqlite3 backup), set the failed copy aside, then revert; ask revert_refusal on every 'boot the image' exit; consider one transaction per bundle.
- Known: res-fleet-2 / regression-3 (FIXED) created the refusal; the dead end is not recorded.

#### PL-RES-23 - Image and runtime updates migrate the live database with no backup and no way back
- Sources: res-upgrade-6. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard app.py:736-738; dashboard_update.py:1016-1037; db.py:2306-2313`
- What: Only the OTA path backs up before migrating. A new image pulled via the NAS app manager (the path for every runtime change, the only one on bind-mount/appliance sites) migrates at first boot with no copy, and pinning the previous tag is then refused.
- Scenario: Customer clicks Update in Container Manager, v59 -> v62, the new image misbehaves, the previous tag will not start.
- Recommendation: Before db.migrate, when user_version < SCHEMA_VERSION, take backup_database into /data/backups/<ts>-pre-migrate-v<n>/ and record it for select_code_root and the Packages page; pair with PL-RES-22's automatic restore.

#### PL-RES-24 - A local-auth (appliance) site whose only admin forgets the password has no supported way back in
- Sources: res-recovery-1. Verdict: DOWNGRADED from high by verifier.
- Where: `dashboard auth.py:150-180, :936-960; setup_api.py:64-104; account_password.py:165-172; local_users.py:223; docs/APPLIANCE_INSTALL.md`
- What: Local auth checks only local_users; first-admin bootstrap closes once any account exists; DASH_ADMIN_USERS grants role, not a password. No reset CLI, no self-service reset, no doc. A docker exec one-liner around local_users.set_password works but is undocumented. smb/oidc sites recover via the NAS or IdP.
- Scenario: An appliance studio's only admin forgets the password; sync continues but nobody can approve computers, tick projects, publish or restore.
- Recommendation: Ship a documented, audited reset CLI (one-time password, sessions revoked) or a reset file in /data/secrets consumed at boot; link it from sign-in; nudge for a second admin in the wizard.

#### PL-RES-25 - A missing or empty dashboard.db is silently recreated: the anonymous first-admin window reopens and accounts, SFTP keys and ticks are gone with no alarm
- Sources: res-recovery-2. Verdict: DOWNGRADED from high by verifier.
- Where: `dashboard app.py:736-738; db.py:710-730; setup_routes.py:91-119; internal_sftp.py; secrets_boot.py`
- What: Nothing records which volume/instance a DB belongs to (probe: missing DB beside existing backups/ and secrets/ is created fresh). Missing secrets are regenerated. Loud in practice (every companion 401s, admin sees a setup wizard) and the window is tailnet-only, but there is no 'wrong database' guard.
- Scenario: After a NAS reboot the dataset is not mounted under its parent; the dashboard boots green into first-run, SFTP refuses everyone, lanes A/B stop fleet-wide.
- Recommendation: Record an instance id in the DB and /data/secrets; refuse to initialise a fresh DB when backups/, secrets/ or code/ exist; show a 'this is not this site's database' page with restore choices; keep the anonymous window closed without an explicit first-run flag.

#### PL-RES-26 - When the NAS Syncthing gets a new identity, lane C stops on every editor computer and only a per-machine reinstall fixes it
- Sources: res-recovery-3. Verdict: DOWNGRADED from high by verifier.
- Where: `installer/windows_bootstrap.ps1:1849-1932; installer/macos_bootstrap.sh; companion site.py:14,75; sync/syncthing_admin.py; dashboard collector.py:1244-1265; server/install_syncthing_app.py:54-60; docs/BACKUP_RESTORE.md s1, s8`
- What: The NAS cert (device id) lives in an ix_volume no snapshot covers; editors learn the NAS id only at bootstrap; the companion never re-seeds it from the manifest; the collector adopts a changed myID with no notice; runbook section 8 covers only the NAS side.
- Scenario: Apps pool fails or the Syncthing app is reinstalled; admin re-approves devices as section 8 says; every editor's Syncthing still rejects the new NAS; lane C dead fleet-wide (no data loss, lanes A/B continue).
- Recommendation: Companion adds a missing manifest nas_syncthing_id on each refresh (keep the old one until the new connects); collector records myID and raises a notice on change; back up the cert/key into apps secrets at install; extend section 8.
- Known: OPS-22 (NAS side documented; editor side not tracked).

#### PL-RES-27 - The Resolve Project Server database (every timeline) is outside the backup story, and the bundled profile defaults to Resolve's well-known password
- Sources: res-recovery-4. Verdict: DOWNGRADED from high by verifier.
- Where: `docs/BACKUP_RESTORE.md s1; dashboard protection.py, recovery.py; dashboard/deploy/compose.yaml:752-772 (PG_PASSWORD:-DaVinci); docs/SERVER.md:460,547; docs/HOW_IT_WORKS.md:58-60`
- What: CC Sync disclaims the project DB (Resolve's own), but the install docs say the NAS hosts it and the protection panel goes green without mentioning it. No pg_dump, no NOT COVERED row. Bundled profile's volume is under the snapshotted apps root where that is a real dataset.
- Scenario: An Apps pool or app reinstall loses the project server volume; footage intact, protection green, every edit gone.
- Recommendation: NOT COVERED row in the backup table; a protection/RECOVERY line when [stack] project_server is on (optionally a scheduled pg_dumpall into the snapshotted dataset); randomise the Postgres password at install.

#### PL-RES-28 - Dashboard DB restore exists only as a code rollback: image mode only, the before-last-update copy only, and it rolls b-roll and music back too
- Sources: res-recovery-5. Verdict: DOWNGRADED from high by verifier.
- Where: `dashboard dashboard_update.py:1263-1287, :1589-1660, :1885-1928; templates/partials/admin_dashboard_update.html:105-112; static/cc/dashboard_update.js:255-275; recovery.py:976-1003; docs/BACKUP_RESTORE.md s4c`
- What: restore_backup is called only from rollback(), which refuses in bind-mount mode and on image code; it offers one backup, always reverts code, overwrites broll.db and music.db, takes no pre-restore copy. Backups are never periodic. RECOVERY claims the dashboard 'can put one back by itself'. NAS snapshots remain the real path.
- Scenario: An admin deletes the wrong user; on a fresh image install there is nothing to click; elsewhere the only option reverts code and three DBs to weeks ago, losing cce1 tokens and b-roll publishes.
- Recommendation: Standalone restore: list every backup, restore dashboard.db alone by default (indexes opt-in), always take a before-restore copy; daily backup_databases; make RECOVERY's copy match what the deployment can do.

#### PL-RES-29 - ytdl.db is migrated by an update but never backed up, and rollback checks only the dashboard's schema
- Sources: res-recovery-7. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard dashboard_update.py:659-686, :1016-1039, :1570-1587; ytdl/web/ytdlweb/db.py:448-481; docs/BACKUP_RESTORE.md s3`
- What: _db_paths covers dashboard, broll and music only (runbook says ytdl.db is backed up). ytdlweb refuses a newer user_version; schema_rollback_check compares only dashboard.db.
- Scenario: An update carries ytdl migration 016 and is rolled back: /ytdl fails 'database newer than this app supports' with no copy to restore.
- Recommendation: Add ytdl.db and client_shares.db to _db_paths; record and check every sub-app user_version in the manifest and schema_rollback_check; fix runbook section 3.

#### PL-RES-30 - Every customer dashboard shows a permanent BROKEN 'release key not backed up' line it cannot truthfully fix
- Sources: res-recovery-8. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard protection.py:483-505; docs/RELEASE.md:830-845; dashboard/deploy/compose.appliance.yaml:36`
- What: _check_key_backup is skipped only when no key is configured; customers pin the vendor's key, so the line is red for ever about a key they do not hold, and it feeds notices and alerts.
- Scenario: A new customer's protection panel and weekly report carry a red line about our key; they learn to ignore red or ack falsely.
- Recommendation: Show the line only on sites that sign their own builds; otherwise render 'vendor-held'; track the vendor key backup vendor-side.

#### PL-RES-31 - A dead NAS takes every original not on an editor's disk, and nothing in the product says offsite is missing
- Sources: res-recovery-9. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard protection.py; docs/BACKUP_RESTORE.md:122-125, :596-599; docs/HOW_IT_WORKS.md:826-827`
- What: Snapshots share the pool; the NAS is the only copy of wired-ingested originals, the b-roll archive and every DB. The protection panel goes all green without any replication or cloudsync task.
- Scenario: Fire, theft, ransomware or a RAIDZ1 double failure; the customer thought green meant backed up.
- Recommendation: Protection line 'a copy exists off this NAS' from replication/cloudsync tasks with recent success (DSM: admin-acknowledged date); name the gap in the install checklist and contract.
- Known: COMMERCIAL_READINESS item 8 (offsite deliberately out of scope; visibility not tracked).

#### PL-RES-32 - A deploy-mode site's site.toml exists only on the operator's PC and is in no backup list
- Sources: res-recovery-10. Verdict: not verified (hunter: CONFIRMED).
- Where: `.gitignore:15; server/install_dashboard_app.py:2154-2175, :2254; docs/BACKUP_RESTORE.md s1`
- What: site.toml holds host-key pins, datasets, feature flags, shares and telemetry switches, and every redeploy rebuilds the env from it; it is gitignored and never copied to the NAS.
- Scenario: The operator's machine is reimaged; a redeploy from a reconstructed file silently flips features, changes datasets, or re-trusts the NAS host key.
- Recommendation: Upload the resolved site.toml (no secrets) to <apps>/data/site.toml.deployed at each deploy, offer a download, warn on drift, list it in section 1.

### Upgrades and the release chain (10)

#### PL-RES-33 - A zero-byte config.toml silently loads all defaults and overwrites the good backup with an empty one
- Sources: res-crash-1. Verdict: DOWNGRADED from high by verifier.
- Where: `companion config.py:1803-1862 (load_config), :1766-1787 (_refresh_backup); installer/windows_upgrade.ps1:440 (WriteAllText)`
- What: APP-4's fallback fires only on TOMLDecodeError; an empty file is valid TOML, so every key defaults, no load error is set, and _refresh_backup replaces config.toml.bak with ''. Probed against repo code.
- Scenario: Disk-full or power loss during an installer write leaves 0 bytes; the machine loses URL and tokens, drops off the grid, and needs a reinstall.
- Recommendation: Treat empty/whitespace config as a load failure (load backup, set _config_load_error); never refresh the backup from a parse with no keys or replace one holding dashboard_url/local_root with one lacking them; add a 0-byte test.
- Known: Extends APP-4 (fixed for invalid TOML only).

#### PL-RES-34 - A power cut during a self-upgrade can leave a machine with no runnable companion, and nothing restarts it
- Sources: res-crash-2. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion upgrade.py:1810-1830 (no fsync), :1920-1960 (two renames); supervisor.py:346-388, :700-708; installer/windows_bootstrap.ps1:645-680; installer/macos_bootstrap.sh:2580-2597`
- What: Power loss between exe -> .old and new -> exe leaves no exe; autostart entries launch the exe path directly with no .old fallback. An unfsynced download can survive full-size but zeroed; it 'exists', so the supervisor will not restore .old, and the APP-5 revert lives inside the broken binary.
- Scenario: A laptop battery dies during an unattended update; next logon no tray, machine silent; someone must rename .old by hand on a machine we cannot reach.
- Recommendation: fsync the download before the swap; move recovery outside the binary (Run-key shim / task / LaunchAgent wrapper restores .old when the exe is missing or fails a recorded size/sha check).
- Known: CR-251i (FIXED only when the supervisor survives).

#### PL-RES-35 - The appliance stack has no release key and no feed URL, so a zero-touch customer can never be updated, and its compose comment says the key is generated at boot
- Sources: res-upgrade-4. Verdict: DOWNGRADED from high by verifier.
- Where: `dashboard/deploy/compose.appliance.yaml:36-41, :153-173; secrets_boot.py:52-58; settings.py:910-919; deploy/select_code_root.py ENV_REFUSALS`
- What: Neither DASH_RELEASE_PUBKEYS nor DASH_RELEASE_FEED_URL is set; the comment's 'generated on first boot' is false (a vendor public key cannot be minted per site). Every publish 503s, the feed cannot verify, no OTA tree boots. Documented as not yet true in APPLIANCE_INSTALL.md (DRAFT), and setup_engine/protection flag the missing key.
- Scenario: A second organisation installs via the appliance; editors stay on the install build for ever.
- Recommendation: Fix the false comment; bake the vendor public key(s) into the image (env still wins); set DASH_RELEASE_FEED_URL with policy=manual; state plainly in APPLIANCE_INSTALL.md that updates do not work until then.
- Known: Recorded as not built (APPLIANCE_INSTALL.md 'NOT YET TRUE', DOCKER.md, ZERO_TOUCH_PLAN WP E/F/G).

#### PL-RES-36 - 'Deploy the dashboard before the companions' is not enforced at customer sites: requires_dashboard is opt-in and its value is stale
- Sources: res-upgrade-5. Verdict: not verified (hunter: CONFIRMED).
- Where: `tools/sign_release.py:360-389; tools/publish_latest.py:500-525; companion config.py:158-174 (REQUIRES_DASHBOARD 0.7.23); dashboard release_feed.py:930-980`
- What: The SYS-2/REL-4 gate only works when records carry requires_dashboard, emitted only with CCSYNC_EMIT_KIND_EXTRAS=1; the constant was never raised past 0.7.23 despite dashboard-first changes up to 0.7.61.
- Scenario: A customer dashboard stuck behind a runtime update or a reverted OTA; the feed makes the newest companion current; reports 422, machines go invisible.
- Recommendation: Emit kind extras by default in the vendor publish; raise REQUIRES_DASHBOARD to the real dependency; add a check that fails when report/reply keys change without a bump.
- Known: REL-4/SYS-13/SYS-7 built; logic-release-5 noted the field is dropped.

#### PL-RES-37 - A licence-version bump parks all syncing on every auto-updating machine, with no warning at publish and no re-prompt after a decline
- Sources: res-upgrade-7. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion eula.py:220-250; app.py:6697-6790 (_start_lanes EULA gate), :~6503-6540 (_licence_watch); tools/publish_latest.py; tools/sign_release.py`
- What: An EULA-VERSION bump stops lanes A, B and C until someone at the machine accepts; a closed dialog is never re-offered; records do not carry the EULA version so nothing can warn or hold back.
- Scenario: Counsel revises the EULA; every auto_update site stops uploading overnight; an editor who closed the dialog stays parked for days.
- Recommendation: Sign the EULA version into records, show it on Packages and in publish_latest, require confirmation to make such a build current and never install it unattended; grace period with nagging (counsel to confirm); re-offer daily.
- Known: Memory notes (EULA 1.1 re-consent parked 0.9.82 machines); no KNOWN_BUGS entry.

#### PL-RES-38 - Unattended and pushed updates restart the companion in the middle of transfers and jobs
- Sources: res-upgrade-8. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion app.py:6948-6966 (_standing_down_would_kill_work), :8426-8470, :8541+`
- What: Only an open window or a consolidate defers a self-upgrade; active lane A/B transfers, held jobs, file moves and ytdl downloads are stood down; rclone over SFTP does not resume uploads.
- Scenario: A 22 GB original on a ~0.45 MB/s uplink takes ~14 h; each weekly build restarts it from zero, so it may never finish.
- Recommendation: For unattended/pushed updates also defer while a lane transfers or a job is held, capped (e.g. 6 h); tray clicks proceed with a warning naming the transfer.

#### PL-RES-39 - Transient network failures spend REL-8's permanent per-version upgrade budget, and an admin's UPDATE NOW cannot override it
- Sources: res-network-2. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion upgrade.py:125-141, :371-463, :1704-1859; app.py:7077-7108, :7167-7184, :8382-8425, :8500-8540`
- What: Any streamed-download exception counts as ERROR_DOWNLOAD toward MAX_UPGRADE_ATTEMPTS=8 (same budget as AV quarantine); no Range resume; once capped, auto and pushed paths silently return 'given up' even for a fresh push.
- Scenario: A remote editor on hotel Wi-Fi has eight downloads drop over ~37 h; the machine never takes the security fix and UPDATE NOW does nothing.
- Recommendation: Keep transport failures out of the permanent cap (own back-off, or reset on a successful report); let a pushed update with a new requested_at clear 'given up' once; add Range resume for .partial.
- Known: REL-8 (FIXED for AV/sha); the network side effect is new.

#### PL-RES-40 - Every signed build ever published can be pushed back onto the fleet: the downgrade floor is 0.0.0 everywhere
- Sources: res-security-adversity-5. Verdict: DOWNGRADED from high by verifier.
- Where: `installer/build_editor_package.ps1:1043-1044; tools/publish_feed.py:1042; dashboard package_store.py:373-456; companion app.py:8361-8371 + _apply_pushed_update; upgrade.py:726-776`
- What: Signatures prove 'signed once'. The dashboard publishes any signed record, and an admin push may roll machines back; the floor is 0.0.0 unless the signer types one. Needs a compromised admin session; admin rollback itself is intended.
- Scenario: A phished admin session publishes an early signed 0.9.x and presses UPDATE NOW; security fixes since (account bars, LG-4) vanish fleet-wide.
- Recommendation: Tracked MIN_VERSION constant read by every signer, raised with each security fix and set to the launch build; dashboard refuses records below the highest floor seen. Mind PL-RES-96 (a floor equal to the release disables rollback).
- Known: release-pipeline-8 (deferred under CR-66), OPEN.

#### PL-RES-41 - One plaintext release key on the owner's daily workstation signs companions and dashboard code for every customer, with no revocation path or compromise runbook
- Sources: res-recovery-6, res-security-adversity-6. Verdict: DOWNGRADED from high by verifier (both).
- Where: `tools/release_key.py:1-27, :88-108; companion release_pubkey.py:169-182; dashboard release_feed.py:499-525, :1138-1260; docs/RELEASE.md:700-835; docs/RELEASE_FEED.md:526-540; docs/COMMERCIAL_READINESS.md:144`
- What: The unencrypted Ed25519 seed (deliberate, REL-14) on the base rig signs companion builds, installers and dashboard bundles. Builds trust only baked keys; rotation assumes the old key is trustworthy; no cold revocation key, no compromise runbook; no Authenticode/Developer ID. Exploitation also needs feed/GitHub or dashboard write access; auto_update is off in the vendor build.
- Scenario: Base rig compromised: attacker with the key and the owner's GitHub credentials publishes a signed dashboard bundle and companion to every customer; recovery means visiting every site.
- Recommendation: Write a compromise runbook now; design a cold revocation key baked into builds that can sign a distrust list; move signing offline or to a hardware token; consider a separate dashboard-bundle key; allow a trusted signed record to update DASH_RELEASE_PUBKEYS; buy code-signing certs.
- Known: COMMERCIAL_READINESS item 4 (keep/rotate decision and certificates open); logic-release-1 fixed rotation docs only.

#### PL-RES-42 - The rclone and Syncthing pins are a last resort; each site runs whatever version PATH, winget, scoop or brew supplies
- Sources: res-deps-1. Verdict: DOWNGRADED from high by verifier.
- Where: `installer/windows_bootstrap.ps1:1075-1112, :1257-1300; installer/macos_bootstrap.sh:1740-1760; companion config.py:353, :1108; sync/rclone_lane.py:1108-1145, :2423-2476`
- What: Installers accept any PATH binary, then winget/scoop/brew latest with no checksum, and use the pinned sha256-verified download only if all fail. The companion resolves bare 'rclone' with no version check; lane B's tally parses rclone's English log text. --max-delete caps still bound each pass, and an old rclone fails loudly.
- Scenario: Each customer site ends up on an untested sync-engine version; a reworded log line blinds the cumulative breaker and trash notice.
- Recommendation: Make the verified pin the default, installed into the ccsync bin dir with absolute paths in config; report the rclone version in capabilities and park lane B outside a tested range; add OPS-15's cross-file pin test.
- Known: OPS-15 (2026-09-03) open; COMMERCIAL_READINESS rclone/Syncthing row partly closed.

### Network, fleet jobs and the report channel (7)

#### PL-RES-43 - A dashboard outage longer than the job lease kills every running fleet job and local YouTube download, and a result posted during the outage is never retried
- Sources: res-network-1, res-concurrency-1. Verdict: not verified (hunter: CONFIRMED) (both).
- Where: `companion jobs_runner.py:815-923, :1269-1366; dashboard db.py:11607, :12153-12330, :10300; api.py:12126-12181; ytdl/web/ytdlweb/db.py:1175-1202, config.py:240`
- What: heartbeat_job refuses an already-expired lease even when nobody else holds the row; the first heartbeat after >300 s gets 410 and the child is killed; expire_leases counts an attempt and cools the machine down; _post_result tries once. Same shape for ytdl's 180 s lease.
- Scenario: A NAS reboot or slow image update throws away every whisper pass in the fleet and cools down every machine; repeated outages abandon whisper jobs (never pinned); a result finishing during a 10 s restart reruns.
- Recommendation: Let heartbeat_job re-extend an expired lease still held by the same (editor, machine) and not re-queued; do not count a restart-spanning expiry as an attempt or cooldown (or extend held leases by measured downtime at boot); persist and retry result POSTs; same for ytdl heartbeat_download.
- Known: comp-ytdl-jobs-1/CR-31 fixed only the transport-blip half.

#### PL-RES-44 - An idle machine on a slow uplink can never deliver its heavy report: the 30 s timeout bounds the whole upload
- Sources: res-network-3. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion reporter.py:107-120, :417-443, :535-541, :1523-1571; manifest.py:36`
- What: urllib's timeout bounds the total body send (probed). Heavy reports are uncompressed, 30 s timeout, 7 MiB budget (needs ~1.9 Mbit/s sustained); _fit_payload trims by size, never after a timeout. The reply carries every command, so it is lost too. Lane A has no --bwlimit.
- Scenario: An editor with several projects on 1 Mbit/s upload: every idle report times out, the grid goes red, the admin cannot push a fix.
- Recommendation: gzip report bodies (dashboard accepts Content-Encoding: gzip); scale the heavy timeout with body size or fall back to a light tick after a heavy timeout; optional lane A bandwidth cap.
- Known: B6 fixed size, not time.

#### PL-RES-45 - Editor-side Syncthing runs on upstream defaults: self-upgrade every 12 h (defeating the pin) and crash reporting on
- Sources: res-deps-2, res-network-7. Verdict: not verified (hunter: CONFIRMED) (res-deps-2); res-network-7 PLAUSIBLE.
- Where: `installer/windows_bootstrap.ps1:333, :1945-2028; installer/macos_bootstrap.sh:1848-1877, :~2012; nothing sets autoUpgradeIntervalH / STNOUPGRADE / crashReportingEnabled; this rig's config.xml reads autoUpgradeIntervalH=12`
- What: Official binaries self-upgrade and restart; the sha256-checked binary is replaced on upstream's schedule; the server stays on compose-pinned 1.30.0. Crash reports leave sites although PRIVACY.md lists only discovery and relays.
- Scenario: An upstream point release with a regression or long DB migration reaches every editor at every customer within 12 h; engine_down fleet-wide; rollback needs a new installer.
- Recommendation: Set autoUpgradeIntervalH=0 and crash reporting off after generate and enforce from the companion on every start (PATCH /rest/config/options); ship Syncthing upgrades through the vendor channel; report the running version; update PRIVACY.md for anything left on.
- Known: PRIVACY.md covers discovery/relays only.

#### PL-RES-46 - Two of one editor's computers with the same hostname merge into one registry row, and the enforce cycle follows whichever reported last
- Sources: res-concurrency-6. Verdict: not verified (hunter: PLAUSIBLE).
- Where: `dashboard db.py:5108-5133; api.py:7777-7890; companion reporter.py:900, selection.py:38, jobs_runner.py:768; installer/macos_bootstrap.sh`
- What: The clone check covers one machine_id under two hostnames, not two ids under one; upsert_machine overwrites machine_id and device id every report. macOS platform.node() can change with the network and is read in three places, so a mid-job change turns the holder's heartbeat into 410.
- Scenario: Two MacBook Pros named Annas-MacBook-Pro on different networks: lane C gains and loses folders every interval; grid shows one computer whose platform flips.
- Recommendation: Raise a duplicate_hostname notice and refuse to overwrite id/device when a recent row has a different machine_id; read the hostname once per process; pin the macOS name from scutil.

#### PL-RES-47 - Deleting a user in local mode holds the SQLite write lock across every Syncthing call, so the fleet's writes fail with 'database is locked'
- Sources: res-concurrency-2. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard api.py:5146-5258; local_users.py:339-340; syncthing_client.py:194-228; db.py:697-722`
- What: delete_user_everywhere deletes rows uncommitted, then makes ~100 Syncthing calls (10 s timeout each) before commit; reports, job heartbeats and file-move answers time out at 5 s.
- Scenario: Deleting a departed editor with two computers and 25 projects: 10-30 s (minutes on a slow NAS) of failed reports and bounced sign-ins fleet-wide.
- Recommendation: Guard checks read-only, Syncthing removals with no transaction open, then one short transaction; test that conn.in_transaction is False at every external call from a route.

#### PL-RES-48 - Nothing stops two dashboard processes from running on one /data
- Sources: res-concurrency-3. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard/deploy/run.sh:592-608; dashboard app.py:810-840; docs/ZERO_DOWNTIME_DEPLOY.md section 3.3`
- What: Only --workers 1 enforces one process; no flock. A second container on the same /data runs a second collector, enforce cycle, alert sender, feed poller, pinned executor, triage scheduler and Cards pool.
- Scenario: A customer installs the app twice: release_pinned_jobs frees jobs the other is encoding, enforce cycles race Syncthing PUTs, every alert goes out twice, both apply the same OTA.
- Recommendation: Exclusive fcntl.flock on <data>/dashboard.lock for the process lifetime; a second process refuses (or runs read-only with a banner). Ship before launch, separate from zero-downtime work.
- Known: Design only in ZERO_DOWNTIME_DEPLOY.md (ZD-2).

#### PL-RES-49 - One editor with the Cards agent on two computers: edits reported lost, the page flips between timelines, edits go to whichever computer polls first
- Sources: res-concurrency-4. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard cards_pool.py:417-488; cards_tunnel.py:456-529; MulticamPipeline cards/agent.py:1167-1200, :340-360`
- What: The tunnel keys agents by editor only and the engine assumes one agent; a second poll while the first applies an edit publishes 'agent went away with that edit'.
- Scenario: Role on a studio desktop and a home laptop: a staged cut lands on whichever Resolve polled, the page says lost, the retry lands on the other.
- Recommendation: Route by (editor, machine); hand edits to one machine only and name both on the page; at minimum refuse the role on a second machine while one holds it.
- Known: Feature is off everywhere today.

### Telling the right person (observability) (8)

#### PL-RES-50 - An alert that fails to send during a channel outage is not retried: warns until they clear and recur, errors for 24 h, 'cleared' messages never
- Sources: res-observability-1. Verdict: DOWNGRADED from high by verifier.
- Where: `dashboard alerts.py:448-496, :4894-4922, :5084-5091; db.py:7477-7497`
- What: Every attempt writes an alert_log row and _is_open/dedup read failed rows too; _requeue_undelivered fires only when the sink goes from none to configured. Probed: after one failing cycle, 0 sends in later cycles. Weekly report, dashboard panels and channel-failure findings still carry the findings, days late.
- Scenario: A ten-minute relay blip or an expired app password: fleet_halt, crashes or upgrade_reverted are only seen in Monday's report.
- Recommendation: Count a failed row as not yet said, with a bounded retry (_retry_due); re-file failed rows when channel settings or SMTP password are saved and after the first success that follows a failure; retry recoveries the same way.
- Known: res-fleet-4 fixed weekly/heartbeat only; DDIAG-4 covers none -> configured.

#### PL-RES-51 - The dashboard restarting itself leaves no durable trace, so a crash-looping server looks healthy
- Sources: res-observability-2. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard app.py:432-511; notices.py:1010-1062; collector.py:2409-2430; alerts.py:4248-4261`
- What: Watchdog os._exit writes nothing; the replacement starts with watchdog_restarts=0; _check_server_crashes counts only crash files since this boot; the alerts pass is stuck on the wedged thread during each wedge.
- Scenario: A hung SMB/NFS mount wedges every cycle; container restarts every 16 min, UI green 15 of 16; no alert; evidence only in docker RestartCount.
- Recommendation: Write a durable meta row/file before exiting; at boot count exits in the last 24 h and raise an error notice/alert; make _check_server_crashes look back 24 h.

#### PL-RES-52 - 'The server itself is down' reaches nobody by default: the dead-man heartbeat is off and setup never offers it
- Sources: res-observability-3. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard alerts.py:280-297, :880-918; setup_engine.py:1567-1614; api.py:1579-1620`
- What: Every alert is sent by the thing being watched; alerts_heartbeat defaults to 0; setup asks only for a destination; no outbound check-in URL; no documented external monitor on /api/v1/health.
- Scenario: After a power cut the NAS app does not come back; no mail, which reads as all quiet for weeks.
- Recommendation: Heartbeat on by default once a sink is set (or a setup step saying 'if these stop, the server is down'); optional outbound check-in URL per successful pass; document an uptime monitor on /api/v1/health.
- Known: DDIAG-17 (deliberate default-off), open for commercial sites.

#### PL-RES-53 - A notice check that starts failing keeps showing [ OK ] for ever
- Sources: res-observability-4. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard db.py:3775-3809; ui.py:1835-1855; templates/partials/health_notices.html:48, home_problems.html:38; notices.py:198-207`
- What: WHAT THE SERVER CHECKS shows OK for any kind ever stamped, with no age test; run_checks swallows a raising check and keeps its last stamp; the notices collector still reports success.
- Scenario: _check_tree starts raising after a permission change; its kinds show OK for months.
- Recommendation: Compare stamp age and render NOT CHECKED since <date> after ~3 cycles; file a notice_check_failed error notice from run_checks' except branch.

#### PL-RES-54 - Warn-severity notices are never pushed to anyone, not even in the weekly report
- Sources: res-observability-5. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard alerts.py:2197-2222, :4512-4700; db.py:3495-3615`
- What: _check_notices mails only error notices and compose_weekly has no notices section; pending_device_approval, feature_not_mounted, project_links_failed and others reach only someone who opens the home page.
- Scenario: A new editor's device sits pending a week (lane C empty), or an update breaks the cards mount; the owner, who reads only mail, hears nothing.
- Recommendation: Weekly 'open on the dashboard' block listing warn notices with age and fix; promote editor-blocking ones to a warn alert after a day.

#### PL-RES-55 - A report the dashboard rejects as malformed (422/413) leaves no trace; the admin is told the computer is switched off
- Sources: res-observability-6. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard api.py:10144-10147, :10202-10208; app.py:936-941; alerts.py:1580-1606; companion tray.py:3581-3626`
- What: report_refused_at is stamped only for identity refusals; pydantic 422 and 413 are answered before the handler; machine_silent says check the tray and power; the tray says only 'not accepted'.
- Scenario: A companion build one field-type off (the 0.9.71 shape): every editor on it goes dark and the admin chases power desk by desk.
- Recommendation: RequestValidationError and 413 handlers for /api/v1/report that stamp report_refused_at/reason when credentials verify and file a version-mismatch notice; companion words non-auth 4xx as a version mismatch.
- Known: DASH-2 covers the identity half only.

#### PL-RES-56 - The alerts page suggests SMTP port 465, which the sender cannot speak
- Sources: res-observability-7. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard templates/partials/admin_alerts.html:134; alerts.py:4761-4821`
- What: The hint offers 465 but _send_smtp always uses smtplib.SMTP (+STARTTLS), never SMTP_SSL; 465 times out after 20 s with no port hint and eats the pass budget.
- Scenario: A customer whose host documents 465 follows the hint; setup shows green (fields filled), invariant 15 shows a timeout, alerting never works.
- Recommendation: SMTP_SSL with a verified context on 465 (or an explicit implicit-TLS option); until then drop 465 from the hint and make a 465 timeout say 'use 587 with STARTTLS'.

#### PL-RES-57 - A wrong NAS clock turns the whole fleet red with 'this computer's clock is out' and sends every editor to fix a correct clock
- Sources: res-time-scale-5. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion reporter.py:794-822; tray.py:159, :3620-3636; app.py:7808-7815; dashboard health.py:709-715; alerts.py:1628-1648`
- What: Skew is editor clock minus the dashboard's received_at; the server's own clock is never checked. A drifting NAS gives every machine the blocked-RED clock_skew reason and a per-computer alert.
- Scenario: A NAS loses NTP behind a firewall and drifts 10 minutes; every tray goes red; editors who set clocks by hand break real timestamps.
- Recommendation: When >=3 machines report skew of the same sign and size, raise one 'server clock looks wrong' notice and suppress per-machine reasons; check the server clock against an HTTPS Date header; word the remedy for both cases.
- Known: SYS-4/APP-13 (fixed) added measurement only.

### Resolve integration (11)

#### PL-RES-58 - A seat with Resolve Free or 'External scripting = None' is never detected and is told every 5 minutes to restart Resolve
- Sources: res-resolve-1. Verdict: DOWNGRADED from high by verifier.
- Where: `companion resolve_bridge.py:362-432, :536-633; app.py:4704-4785; tray.py:1806-1824; installer/windows_bootstrap.ps1; onboarding/steps.py; docs/EDITOR_SETUP.md:7-18`
- What: Every Resolve feature needs Studio plus External scripting = Local, a manual documented step nothing checks. With the server READY but scriptapp() None, the explainer says 'quit and reopen Resolve', which never helps. The Windows bootstrap does not check Resolve is installed. The fleet grid shows only 'not connected'. Sync is unaffected and the nag can be silenced.
- Scenario: A new customer's Free and default-preference seats get a nag that never helps, while the out-of-tree guard, proxy attach and Send to Resolve are silently off.
- Recommendation: A 'never connected while server READY' state with Studio/Local guidance; check Resolve and the preference in the wizard/bootstrap (set it via resolve_prefs if that works live); report ever_connected and reason to the dashboard with an alert kind.

#### PL-RES-59 - Library walk validated on one Resolve build with no sanity check; a blob format difference silently blinds the out-of-tree guard
- Sources: res-resolve-2. Verdict: DOWNGRADED from high by verifier.
- Where: `companion library.py:144-216, :691-725; resolve_bridge.py:1427-1508, :1810-1847; config.py:803`
- What: A schema rename raises and falls back to the API, but an unrecognised Clip blob encoding makes every path '' and the walk returns ok with items=[]; no version gate, no cross-check. library_walk=false and tools/library_walk_check.py exist.
- Scenario: A customer on Resolve 19/20 or a future 21.x/22: every walk returns zero clips; Desktop media is never flagged; another editor opens the project to Media Offline.
- Recommendation: Raise LibraryUnavailable when rows exist but none decode to a path; periodically cross-check one API walk and disable the walk on disagreement; record GetVersionString and gate to measured builds.
- Known: Related to 09-03 RES-12, distinct.

#### PL-RES-60 - Companion launches Resolve -pg (BPG) without the CR-68 guard, and a BPG-only machine reads as Resolve running
- Sources: res-resolve-6. Verdict: DOWNGRADED from high by verifier.
- Where: `companion bpg.py:763-835; script_server.py:94-110; resolve_prefs.py:128-162; app.py:4787-4815`
- What: maybe_launch never consults script_server.state(); BPG is never stopped; process probes match by image name, so BPG counts as Resolve, the scripting nag fires with Resolve closed and the R12 stale-bridge self-restart never runs while BPG lives. Whether -pg opens 1144 (and steals scripting) is unmeasured. Exposure: base rig with BPG installed.
- Scenario: BPG starts overnight; in the morning the editor is nagged with Resolve closed, and stale fusionscript state survives into the next launch (or scripting is dead for the day, if -pg opens 1144).
- Recommendation: Measure whether -pg opens 1144 once; exclude -pg processes from resolve_process_state via bpg._cim_command_lines; refuse a BPG launch unless script_server.state() is ABSENT. Raise to high if -pg proves to open 1144.
- Known: 08-28 RES-4 and RES-5 OPEN; CR-68 'not done (c)'.

#### PL-RES-61 - Relinks overwrite whatever the clip points at now, with no check it still points at the judged path
- Sources: res-resolve-3. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion resolve_bridge.py:2341-2467; app.py:3559-3615; fixer.py:1531-1561`
- What: replace_clip short-circuits only when the live path equals the new one; callers act on library walks that trail unsaved edits or popup rows hours old.
- Scenario: A clip hand-relinked to a different take and not yet saved is relinked back by the 120 s pool pass, or by FIX ALL from a stale popup.
- Recommendation: Add expected_old to replace_clip, refuse with 'changed_since' on mismatch, pass it from every automatic caller and fix_clip.
- Known: 08-28 RES-11 (input side) OPEN; the compare-and-set gap is new.

#### PL-RES-62 - Undo marks a journal done after a partial replay and blames 'no longer in the media pool' for transient refusals
- Sources: res-resolve-4. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion resolve_bridge.py:2662-2815; resolve_undo.py:200-212`
- What: Replay uses tries=1 although big projects return busy for seconds; any failure counts as skipped; if anything was undone the journal is marked undone and the admin command answers 'done'.
- Scenario: Undoing a 158-clip bad relink on a busy machine: 38 transient refusals stay on wrong paths with no retry route.
- Recommendation: Normal retry budget; count refusals separately from missing clips; mark undone only when nothing was refused; answer 'retrying' while any are refused.

#### PL-RES-63 - Undo over-counts and leaves clips unrestored when one file is in the pool twice
- Sources: res-resolve-5. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion resolve_bridge.py:2745-2770`
- What: by_path.setdefault keeps one item per path; the second entry finds the already-restored clip, gets 'Already linked' and counts it as undone.
- Scenario: A file in two bins, both relinked by FIX ALL: undo says 'Put 2 back' while one clip still points at the copy.
- Recommendation: Map each path to a list of items and pop one per entry; do not count 'Already linked' as undone.
- Known: 08-28 RES-6 OPEN.

#### PL-RES-64 - Bridge import/environment failures are DEBUG-only and misreported as 'restart Resolve'; older DaVinciResolveScript likely fails under Python 3.12
- Sources: res-resolve-7. Verdict: not verified (hunter: CONFIRMED) (Resolve-18 part PLAUSIBLE).
- Where: `companion resolve_bridge.py:408-432, :505-513, :586-604`
- What: A wrong RESOLVE_SCRIPT_LIB, Resolve outside PROGRAMFILES, or an older DaVinciResolveScript.py importing `imp` all surface as 'isn't accepting scripting connections'.
- Scenario: A seat on Resolve 18.6, or installed on D:: never connects, nag says restart, diagnostics cannot show the import failed.
- Recommendation: Log import/env failures at WARNING once with path and exception and give them their own message; load fusionscript via ExtensionFileLoader; find the install dir from the registry; publish a minimum Resolve version.

#### PL-RES-65 - Disk-library locator falls back to Local Database and takes the first same-named project
- Sources: res-resolve-8. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion library.py:315-338 (contrast :631-651)`
- What: _find_disk_db also searches the Local Database root and takes the alphabetically first Projects/<name>/Project.db; external/NAS libraries match a same-named project elsewhere; projects in folders are never found.
- Scenario: 'Ep 3' migrated to an SSD library with an old local copy: the pool pass reads the old copy, FIX ALL copies multi-GB files into the tree and lane A uploads them, then every relink fails.
- Recommendation: Search only the named library, return '' outside Support, refuse on multiple candidates, verify the open timeline's uid exists in that DB.

#### PL-RES-66 - No supported Resolve version is stated, recorded or reported
- Sources: res-resolve-9. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion (no GetVersionString/GetProductName); docs/INSTALL.md; docs/EDITOR_SETUP.md; library.py`
- What: The integration depends on version-specific API answers, log wording, DB schema and blob format, but no machine reports its Resolve version or edition and customers get no supported range.
- Scenario: 'The companion does nothing in Resolve': support cannot see the seat runs 18.6 or a 22 beta.
- Recommendation: Read version/product once per connection into resolve_health, diagnostics and the fleet grid; publish and test a supported range; warn outside it.

#### PL-RES-67 - A third-party scripting client on a customer seat can kill Resolve scripting at launch, and nothing names it
- Sources: res-resolve-10. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion script_server.py:126-158; app.py:9545-9547; docs/GOTCHAS.md section 15`
- What: classify() sees every ESTABLISHED pid on 1144 but discards them; diagnostics carry neither the probe phase nor other clients; advice is 'restart', which the other tool undoes next launch.
- Scenario: A studio automation tool polls Resolve at login; scripting is dead every morning with no evidence pointing at it.
- Recommendation: Record non-companion, non-Resolve clients on 1144 and the launch phase timeline into diagnostics; name the program when a session never connected after another client was seen during STARTING.
- Known: CR-68 fixed for our own clients.

#### PL-RES-68 - The macOS CR-68 probe has still never run against a live Mac
- Sources: res-resolve-11. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion script_server.py:247-302; KNOWN_BUGS CR-68 'Not done (a)'`
- What: The lsof parse is untested on a real Mac and every parse failure fails open, which on a Mac means connecting during the launch window: the exact CR-68 kill.
- Scenario: Mac editors at a customer site get the restart dance CR-68 fixed on Windows.
- Recommendation: Run the CR-68 harness once on a Mac before selling to Mac seats; count UNKNOWN probe answers in resolve_health.
- Known: CR-68 (a) OPEN.

### External dependencies (5)

#### PL-RES-69 - Every NAS operation uses TrueNAS's REST /api/v2.0, which iXsystems has deprecated for removal; no version probe and no supported-version statement
- Sources: res-deps-3. Verdict: DOWNGRADED from high by verifier.
- Where: `dashboard nas/truenas.py:111-140; server/common.py:1339, :1992-2044; server/install_dashboard_app.py:143-155; server/install_syncthing_app.py; server/setup_editor_account.py; server/create_api_key.py`
- What: Provisioning, password reset, user delete, snapshot-task listing, deploy, Syncthing app install and snapshot_before all use REST; no JSON-RPC client; all notes pinned to 25.10. Sync data paths are unaffected; snapshot_before's best-effort mode is deliberate and warns. Removal date unverified.
- Scenario: A customer updates TrueNAS to a release without REST: adding an editor, password reset, protection checks and redeploys fail with a 404 on /user and nothing names the NAS upgrade.
- Recommendation: Document supported TrueNAS versions now; detect 404/405 on known routes and name the likely NAS upgrade; plan a JSON-RPC (WebSocket /api/current) backend chosen from system.version before iX's removal release.

#### PL-RES-70 - An AI provider that stops working (revoked key, exhausted credit, outage) stays selected, fails every job, and nobody who can fix it is told
- Sources: res-deps-5. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard ai_providers.py:866-880, :953-972, :1113-1137; ytdl/web/ytdlweb/ai_backend.py:477-497; worker.py:380-387; claude_cli.py:1130-1146; dashboard ytdl.py:825-871`
- What: A provider is 'available' whenever a key exists; no runtime failover; 402/429/529/404 after SDK retries fails the job outright; no alert kind reads the ytdl snapshot's 'claude' health.
- Scenario: Anthropic spend cap hit on the 20th with a DeepSeek backup configured: every YouTube search fails until the 1st; DeepSeek never tried.
- Recommendation: Record each provider's last real-call outcome and treat auth/billing failures as unavailable for ~1 h so the chain falls through; live check on key save; re-queue on 429/529/5xx with backoff; ai_provider_failing alert kind.
- Known: YT-10 (2026-08-28) OPEN.

#### PL-RES-71 - Model ids are compiled in, so an upstream model retirement becomes a dated outage that only a new build fixes
- Sources: res-deps-6. Verdict: not verified (hunter: CONFIRMED).
- Where: `ytdl/web/ytdlweb/config.py:65,82,85; broll/indexer/broll_index/claude_client.py:51-66; dashboard triage.py:77; ytdl/web/ytdlweb/ai_backend.py:466-497`
- What: YouTube terms/filtering, triage and the b-roll indexer name fixed models; only a container env var overrides; a model 404 is generic ERR_OUTPUT. Only Cards follows model families.
- Scenario: On a retirement date every YouTube search on every site not on the newest build fails with 'answered 404'; triage stops.
- Recommendation: Resolve models like cards_ai (family alias, newest via Models API, cached, pin as fallback); classify a model 404 as 'model retired'; per-provider model field in Settings; track deprecation dates in the release checklist.

#### PL-RES-72 - The server's yt-dlp nightly (CR-361) has no way back from a bad build, can shadow a newer image copy, and waits for a restart nobody is prompted to do
- Sources: res-deps-7. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard/deploy/run.sh:382-424; ytdl/web/ytdlweb/ytdlp_nightly.py:285-385, :446-471; dashboard alerts.py:3575-3604`
- What: A nightly that imports but cannot download becomes current and is never reverted on canary failure; the not-older-than-image test runs only at staging; pending_restart is visible only in /ytdl/api/health; ytdl_downloads_failing advises 'update the dashboard', which does nothing while the nightly shadows the image.
- Scenario: The fix nightly is staged but the dashboard runs on for weeks; or a broken nightly survives a dashboard update.
- Recommendation: At boot skip a nightly older than the image's; revert to previous/image copy on canary failure; alert on pending_restart while downloads fail with a restart action; fix the alert text; put the switch in Settings.
- Known: CR-361 (BUILT, unshipped); these gaps not recorded.

#### PL-RES-73 - The appliance's Syncthing, Tailscale and SFTP images are pinned in compose with no update path
- Sources: res-deps-8. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard/deploy/compose.appliance.yaml:237, :291, :363; compose.yaml:711; compose.image.yaml:387`
- What: OTA and image updates cover only the dashboard; sidecars change only on an installer re-run and nothing reports how far behind they are (Syncthing 1.30.0, Tailscale v1.102.2 digest).
- Scenario: A Tailscale or Syncthing security advisory arrives; appliances keep launch-day sidecars with no vendor path to move them.
- Recommendation: Carry sidecar digests in the signed release manifest with a dashboard-offered stack update (snapshot, stage, verify, swap); report sidecar versions on /admin/health; move server Syncthing to 2.x.

### Scale and long-running sites (4)

#### PL-RES-74 - The fleet-wide owed-files diff costs ~6 s per call at 50 editors; the admin home page polls it every 2 s and its cache never hits
- Sources: res-time-scale-1. Verdict: DOWNGRADED from high by verifier.
- Where: `dashboard db.py:11098 (fetch_sync_backlog); api.py:975-1060; ui_home.py:423; templates/fleet.html:99-100; alerts.py:1142`
- What: Admin-scope home-transfers runs the NOT EXISTS diff uncached every 2 s; the owed-count cache fingerprints rows including reported_at so any report invalidates it; no single-flight. Verifier re-measured 6.0-6.3 s at the real 2000-row cap. Only while an admin tab is visible; scales with NAS proxies.
- Scenario: A 50-editor customer with large projects: an admin's home tab keeps a worker and a core busy, grid/account/alerts add ~6 s each, the report endpoint slows for everyone.
- Recommendation: Maintain per-pair owed counts in the writers; key the cache on a writer-bumped generation; single-flight; in admin scope show live transfers only with hx-sync drop and move queued totals to a slower poll.

#### PL-RES-75 - The b-roll semantic index is rebuilt whole, in the dashboard process and under a lock, after every ingest write (7 s and 1.7 GB peak at 500k embeddings)
- Sources: res-time-scale-2. Verdict: not verified (hunter: CONFIRMED).
- Where: `broll/web/app/semantic.py:207-250, :318; routes_ingest.py:289; ingest_batches.py:1141, :1336`
- What: Every ingest write bumps search_generation; the next search fetchall()s every blob and builds a float32 matrix under self._lock in-process. A 100k-clip archive extrapolates to ~14 s and ~3.5 GB peak.
- Scenario: During continuous indexing nearly every search pays a rebuild; on a small NAS the dashboard is OOM-killed and sync monitoring goes with it.
- Recommendation: Append incrementally above the high-water mark, rebuild only on deletes; stream rows, consider float16/memmap; rebuild off the request path with an atomic swap; publish a memory ceiling per 100k clips; check the music CLAP index too.
- Known: BROLL-17/R2 cover key correctness only.

#### PL-RES-76 - Past 2000 files per project, per-file sync truth is permanently 'uncertain', which at commercial project sizes is every project
- Sources: res-time-scale-4. Verdict: not verified (hunter: CONFIRMED).
- Where: `companion manifest.py:36, :206-247; dashboard db.py:37, :11055-11095, :11160-11260`
- What: The companion lists the first 2000 originals and 2000 proxies per project in os.walk order; above that uploads are 'uncertain' and owed counts cover only the listed 2000. A 10 TB project is ~20k files.
- Scenario: 'Safe to close' and the per-file queue never give a definite answer on a large project; editors learn to ignore them.
- Recommendation: List originals newest first and send per-directory digests (count, bytes, max mtime) for the rest; or send only files not confirmed on the NAS.
- Known: Cap mechanics CR-314, bug-dash-db-2, logic-sync-truth-2; the scale consequence not recorded.

#### PL-RES-77 - Every Cards episode switch leaks the engine's threads and memory for the container's life
- Sources: res-time-scale-7. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard cards_pool.py:28-34, :615-627, :707-731; docs/CARDS_TWO_PROJECTS.md section 6.1`
- What: drop() frees the seat but the library, tokens and translator threads keep running (+128 MB and 15 threads per engine); non-admins can close episodes so switching is routine.
- Scenario: A studio cycles 20-30 episodes in a quarter; the dashboard grows to GBs and hundreds of threads until OOM-killed. Medium only if Cards is sold.
- Recommendation: Land a real upstream stop() before selling Cards; meanwhile count leaked engines and raise a 'restart to reclaim N MB' notice or recycle at a quiet hour.
- Known: Documented design limitation, not a KNOWN_BUGS launch item.

### Security under adversity (8)

#### PL-RES-78 - A stolen editor laptop cannot be cut off per computer, and there is no lost-or-stolen runbook
- Sources: res-security-adversity-1. Verdict: DOWNGRADED from high by verifier.
- Where: `onboarding/steps.py:1432, :1474 (passphraseless key); installer/windows_bootstrap.ps1:2064-2068; docs/TENANCY.md:49-58; dashboard auth.py:375-392; api.py:5392-5435, :4864-4916, :2437-2451`
- What: The laptop holds a passphraseless NAS SSH key, a non-expiring identity token, the shared report token (default on) or a per-person cce1 token, and a browser session. No per-computer credential or revoke; SUSPEND leaves the NAS account live. Mitigations exist but are undocumented: setup_editor_account.py --revoke-key --lock, and removing the tailnet node.
- Scenario: A freelancer's laptop is stolen; the owner presses SUSPEND; the thief still reads and deletes the tree over SFTP under project_acl=shared.
- Recommendation: Write a 'lost or stolen computer' runbook (remove tailnet node, --revoke-key --lock, revoke sessions); later one admin action per machine (remove its SSH key, Syncthing device, blocklist machine_id); say in the SUSPEND confirm that the NAS account stays live; default the shared report token off for new sites.
- Known: trust-model-1 / trust-model-6 open; CR-86 design trade.

#### PL-RES-79 - Suspended or deleted editors on the SHARED fleet token still pass the b-roll, music and ytdl fleet doors, and a deleted smb editor's machine re-registers
- Sources: res-security-adversity-2. Verdict: DOWNGRADED from high by verifier.
- Where: `dashboard broll.py:338-339; music.py:208-209; ytdl.py:265-266; broll/web/app/fleet_auth.py; api.py:233-242, :10229-10240; db.py:9032`
- What: security-1 withheld the stamp only on the cce1 path; on AUTH_SHARED (default for the field) the gate stamps 'shared' before any account bar. After DELETE on smb/oidc no tombstone exists, so the next report re-creates known_editors. Suspend is a pause, not a security boundary (NAS access stays).
- Scenario: A suspended freelancer's companion keeps claiming b-roll ingest and YouTube downloads; after DELETE the laptop reappears on the grid.
- Recommendation: Apply account_bar_reason on the AUTH_SHARED branch using the verified identity, refusing when missing; write a deleted tombstone in forget_editor and refuse it on every auth method; per-mount tests.
- Known: Extends security-1 (FIXED for cce1 only).

#### PL-RES-80 - Any signed-in editor can mint a public, non-expiring link to any archive clip and read every other folder's link
- Sources: res-security-adversity-4. Verdict: not verified (hunter: CONFIRMED).
- Where: `broll/web/app/routes_client_folders.py:62-121; client_folders.py:90-93, :525-526; routes_share.py`
- What: Every editor (or stolen session) can publish any proxy publicly and list every live token; links never expire by default; no alert on creation; no rate cap.
- Scenario: A stolen laptop's 7-day session copies every client token and creates a folder holding the whole archive.
- Recommendation: Default expiry (e.g. 30 days); hide others' tokens from non-admins; alert on creation and bulk adds; per-token rate cap; record first-seen IP/UA.

#### PL-RES-81 - No Content-Security-Policy anywhere, so any stored XSS in a dashboard-hosted SPA could drive the 8899 loopback on every editor's machine
- Sources: res-security-adversity-7. Verdict: DOWNGRADED from high by verifier.
- Where: `dashboard/src, broll/web/app, music/web, ytdl/web (no CSP / frame-ancestors / nosniff); companion loopback_guard.py origins_for_url`
- What: The dashboard origin (and its http twin) is fully trusted by every loopback; the SPAs render third-party text through many innerHTML sinks. No XSS was demonstrated; loopback actions are bounded (journalled inserts, allow-listed paths).
- Scenario: A crafted YouTube title reaches a renderer that misses escapeHtml; every editor opening it fires a POST to their own 127.0.0.1:8899.
- Recommendation: Strict CSP from dashboard middleware (default-src 'self', hashed inline scripts, object-src 'none', frame-ancestors 'none') plus nosniff; drop the http twin on https-only sites.
- Known: trust-model-9 / CR-54 (deferred) OPEN.

#### PL-RES-82 - The admin-editable site dashboard_url becomes a trusted loopback origin and the tray's 'Open dashboard' target on every editor machine
- Sources: res-security-adversity-8. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard site_store.py:779; companion loopback_guard.py:244; tray.py:858-881; site.py:150-190`
- What: One Settings field, served to the fleet and barely validated, decides which origin may drive each companion and where editors type their NAS password; changes are not alerted and never compared with the reporting host.
- Scenario: A phished admin sets a look-alike host; after one manifest refresh every tray opens it (harvesting passwords) and its pages may POST to every editor's 8899.
- Recommendation: Companion accepts a manifest dashboard_url only if its host matches the reporting host (or an install-time list) and alerts on change; dashboard adds a confirm step and an alert kind for the key.

#### PL-RES-83 - The triage agent reads fleet-supplied text with no untrusted-data fence and mails the owner a paste-ready Claude Code prompt
- Sources: res-security-adversity-9. Verdict: not verified (hunter: PLAUSIBLE).
- Where: `dashboard triage.py:380-405, :432, :519-521; triage_actions.py:326-370`
- What: evidence.json carries companion-written strings; the prompt does not mark them as data; output becomes reply-executable actions (including resume_breaker and clear_fleet_halt) and a free-text prompt the owner is told to paste on the base rig, which holds the release key.
- Scenario: A stolen laptop reports last_error text steering the reviewer to suggest resume_breaker everywhere and a crafted code_fix_prompt; the owner replies '1' or pastes it.
- Recommendation: Fence evidence as untrusted; cap/strip companion strings in scrub; never mail an execution-ready free-text prompt (link to the finding); remove the two latches from the reply catalogue or require a dashboard click.

#### PL-RES-84 - Adding an address to alerts_smtp_to grants a mail control channel that survives session revocation
- Sources: res-security-adversity-10. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard triage_mail.py:14-22, :120-122; ui.py:2542-2561`
- What: One field means both 'receives alerts' and 'may command the fleet by email'; an attacker who once held an admin session keeps receiving references and can reply with DKIM-signed mail.
- Scenario: After a phishing incident the owner revokes sessions and changes passwords; the attacker still gets alerts and can reply to clear a fleet halt.
- Recommendation: Separate the reply-authorised list from alert recipients (owner-only, changes confirmed to the previous owner address); notify all recipients when the list changes.

#### PL-RES-85 - No second factor and no step-up re-auth for admin actions on local or smb sites
- Sources: res-security-adversity-11. Verdict: not verified (hunter: CONFIRMED).
- Where: `dashboard auth.py:61 (7-day sessions); sessions.py:48; admin routes guarded only by _require_admin`
- What: Every admin-side escalation starts from one session that is one NAS password away; no TOTP/WebAuthn outside OIDC; no fresh-password prompt for fleet-wide actions.
- Scenario: A reused password leaks; the attacker pushes a rollback, retargets dashboard_url and adds themselves to alerts.
- Recommendation: TOTP or WebAuthn for admins on local and smb; step-up password for fleet-wide or credential-changing actions.

## 4. Polish

One line each: id (sources) - title. Where / fix.

- **PL-RES-86** (res-security-adversity-3) [DOWNGRADED from high to low by verifier] - Suspension does not stop browser sign-in, so a suspended smb editor keeps the archive, the downloader and client links (deliberate per DCORE-4; UI labels say 'cannot sync'). `dashboard api.py:2256 api_login, :4863-4910`. Fix: Offer an smb toggle that pauses sync and blocks sign-in together, or make the 'suspend = sync only' scope louder; Set password + session revoke already locks someone out. Known: DCORE-4 design decision.
- **PL-RES-87** (res-network-5) - remote_down (second lane B route, e.g. a Cloudflare tunnel) has no failover to the primary route. `companion sync/rclone_lane.py:839-881; broll_fetch.py:268-297`. Fix: After N transport failures on remote_down, run the pass on the primary route and report the fallback, or mark remote_down unsupported for customers. Known: cf-lane-b trial.
- **PL-RES-88** (res-network-6) - A laptop with an http LAN-address dashboard sends its fleet credential in cleartext on whatever network it joins. `companion transport.py:1-30, :204-260; docs/EDITOR_SETUP.md:234-235`. Fix: Default new sites to https (Serve has certificates) and require it; until then hold credentials when a 100.64/10 target has no Tailscale interface or the address class changed. Known: LG-4 / CR-339 'require https' deferred.
- **PL-RES-89** (res-storage-7) [not verified (hunter: PLAUSIBLE)] - A case-only folder rename on Windows re-uploads every original under the new casing to a case-sensitive NAS dataset. `companion sync/rclone_lane.py:2030-2042; server/ (casesensitivity never recorded)`. Fix: Record dataset casesensitivity at setup; add --ignore-case-sync to lane A's copy when sensitive; flag case-only duplicate siblings in the inventory.
- **PL-RES-90** (res-storage-8) [not verified (hunter: PLAUSIBLE)] - No antivirus exclusion guidance, and sharing-violation renames in proxy_gen/jobs_media are not retried. `companion proxy_gen.py:1792-1799; jobs_media.py:419-424; installer/windows_bootstrap.ps1; docs/EDITOR_SETUP.md`. Fix: Retry os.replace with backoff on WinError 5/32; document exclusions (sync root, %LOCALAPPDATA%\ccsync, rclone/Syncthing); optionally offer the Defender exclusion.
- **PL-RES-91** (res-crash-7) - A package row committed without its file cannot be healed by publishing again (the same-sha branch deletes the new .part). `dashboard package_store.py:477-489, :536-552; api.py:7403-7406`. Fix: In the same-sha branch move the verified .part into place when the served file is missing; add a collector check that every package row has its file.
- **PL-RES-92** (res-crash-8) - Three hard power losses within ten minutes in the hour after an update count as a crash loop and revert a healthy build. `companion upgrade.py:116-117, :253-330; app.py:11760-11771, :7083-7100`. Fix: Do not count a start whose predecessor predates the OS boot time (GetTickCount64 / kern.boottime).
- **PL-RES-93** (res-dataloss-7) - Single-file server move trashes this machine's copy without checking the server holds the same bytes; the trash then expires. `companion file_moves.py:766-826 vs :567-615; sync/lane_guard.py:1260-1350`. Fix: Route the single-file branch through the same server (name, size) check; keep the file and answer retrying/kept-local on mismatch.
- **PL-RES-94** (res-dataloss-8) - File moves keep renaming and trashing local files while a local or fleet halt is engaged. `companion app.py:8680-8800 (_apply_file_moves); docs/SYNC_SAFETY.md section 4`. Fix: Hold commands.file_moves while HaltState.active (answer retrying without spending attempts) and say so on the halt panel.
- **PL-RES-95** (res-dataloss-9) - SYNC_SAFETY.md section 7 still says nothing reports a missing snapshot schedule, understates who can delete, and omits the 4b trash. `docs/SYNC_SAFETY.md section 7; dashboard protection.py`. Fix: Point section 7 at the protection panel/alert, state that editors can delete, add the file-move 4b trash and its 14-day expiry to the recovery list.
- **PL-RES-96** (res-upgrade-9) - A min_version floor equal to the release disables that release's automatic rollback everywhere. `companion upgrade.py:~1546-1560, :1083-1086; tools/publish_latest.py:381; installer/build_editor_package.ps1:1039-1052`. Fix: Refuse (or flag) a min_version above the build currently CURRENT for that platform so the floor trails by one release; document in RELEASE.md. Coordinate with PL-RES-40. Known: CR-52 / comp-app-core-3 cover a floor above the version only.
- **PL-RES-97** (res-upgrade-10) [not verified (hunter: PLAUSIBLE)] - After a package install, a stale .old from an earlier self-upgrade is restored under the wrong version name. `installer/windows_upgrade.ps1:204-263; companion upgrade.py:1043-1100`. Fix: Have windows_upgrade.ps1 remove or fold .old into .prev, or record the .old's real version in a sidecar and use it in the revert.
- **PL-RES-98** (res-concurrency-7) [not verified (hunter: PLAUSIBLE)] - macOS single-instance guard is check-then-write, and the Windows mutex is per logon session (second session's loopback serves the other user's browser). `companion app.py:599-638, :307; broll_server.py:2888-2897`. Fix: Hold fcntl.flock on posix for the process lifetime; choose Global\ deliberately on Windows or require the per-user token header on the loopback.
- **PL-RES-99** (res-concurrency-8) [not verified (hunter: PLAUSIBLE)] - Closing and reopening the same Cards episode runs two engines' unstoppable workers against one episode. `dashboard cards_pool.py:371-392, :557-595, :707-730; cards.py:239-260`. Fix: Refuse to reopen a slug while the previous engine's workers live, or per-engine tmp names and per-path doc_save serialisation. Known: thread leak in CARDS_TWO_PROJECTS.md 6.1; same-slug writer not recorded.
- **PL-RES-100** (res-concurrency-9) - The new (uncommitted) alert-kind switches mute kinds the page never showed: a tab drawn before an update, or a second admin's save. `dashboard ui.py partial_admin_alerts_kinds; templates/partials/admin_alerts.html; app.py:1125-1130`. Fix: Post the kinds the page rendered and mute only shown-minus-send, or refuse a save from a different build with a reload prompt. Known: new, uncommitted feature.
- **PL-RES-101** (res-concurrency-10) [not verified (hunter: PLAUSIBLE)] - A lane A pass before a server-side move command arrives re-uploads the file at the old path, and the duplicate is dropped without a word. `docs/FILE_MOVES.md:76-83; dashboard collector.py:2800-2822`. Fix: Raise a notice naming the move and machine when a comeback hits a recently moved path; offer remove-old-copy (to .trash) once every holder answered applied. Known: acknowledged in a collector comment.
- **PL-RES-102** (res-resolve-12) - FIX ALL keeps copying for hours after Resolve has gone away; an empty open-project name passes the mismatch guard. `companion popup.py:737-830; fixer.py:1531-1561`. Fix: Stop the batch after the first disconnection relink failure and treat an empty project answer as 'stop'.
- **PL-RES-103** (res-resolve-13) - Undo journal rewrites the whole file per entry and silently stops journalling at 5000. `companion resolve_journal.py:490-534`. Fix: Append-only JSON lines; WARNING at the cap; stop the burst at the cap rather than make edits nobody can undo. Known: 08-28 RES-14 OPEN (cap half).
- **PL-RES-104** (res-deps-9) - Any ffmpeg on PATH wins over the pinned sidecar with no version floor, and the pinned sidecar comes from one individual's GitHub repo. `companion ffmpeg_tools.py:101-142; sidecar_tools.py:95, :607`. Fix: Report ffmpeg version/flags in capabilities and gate media kinds on a floor or the managed copy; mirror pinned assets to the vendor feed.
- **PL-RES-105** (res-deps-10) - The Claude Code CLI auto-updater flips without a working-call check and prunes the previous version an hour later. `dashboard cli_tools.py:1366-1405, :1430-1663`. Fix: Run a one-token probe call before flipping, keep the previous version until N successful calls, add a go-back button. Known: CR-309 built the updater.
- **PL-RES-106** (res-deps-11) [not verified (hunter: PLAUSIBLE)] - The dashboard address is fixed into every machine at install, so a tailnet rename or NAS move strands the fleet with no channel to repoint it. `companion config.py:374, :1128; settings_window.py:1248-1284; installer rclone.conf host, Syncthing NAS address`. Fix: Site manifest publishes an ordered address list the companion caches and tries; derive rclone and Syncthing hosts from it; document a planned-rename procedure.
- **PL-RES-107** (res-time-scale-8) [not verified (hunter: PLAUSIBLE)] - The base rig re-walks its whole NAS tree over SMB every 300/900 s with an extra stat round trip per video file. `companion manifest.py:117, :206-253, :393-400; proxy_scan.py:400-440`. Fix: os.scandir with entry.stat(); skip per-file lists in base mode; skip projects whose directory mtimes are unchanged.
- **PL-RES-108** (res-time-scale-9) - The site timezone is never asked for, so weekly reports, triage and the heartbeat run on UTC for every customer. `dashboard alerts.py:719-746; triage.py:130-136; admin_alerts.html:68`. Fix: Timezone step in the setup wizard pre-filled from the browser's Intl timeZone.
- **PL-RES-109** (res-time-scale-10) [not verified (hunter: PLAUSIBLE)] - The snapshot policy assumes the apps dataset changes by kilobytes per hour; at fleet scale dashboard.db churn is pinned in 54 snapshots. `server/setup_snapshots.py:19-27, :73-93; dashboard db.py:10676`. Fix: Measure on the reference NAS; move rebuildable volatile tables to a separate SQLite on a short-retention dataset; add usedbysnapshots to the capacity check.
- **PL-RES-110** (res-recovery-11) - The Android signing keystore's password exists only as a DPAPI blob on one Windows profile, with no backup record. `docs/ANDROID.md:128-133; %USERPROFILE%/.ccsync-release/android.keystore.pw.dpapi; tools/release_key.py`. Fix: Extend release_key.py backup (or an Android twin) to export the keystore and print its password for the password manager, write a backup record, list it in the vendor checklist.
- **PL-RES-111** (res-observability-8) [not verified (hunter: PLAUSIBLE)] - Unreadable inputs to the alerts scan read as 'nothing wrong', so open alerts are mailed as cleared and then raised again. `dashboard alerts.py:1166-1171, :1236-1255, :1308-1320, :5132-5170`. Fix: Narrow _rows to 'no such table' so other errors become check_failed; make swallowed Ctx reads mark dependent checks as failed.

## 5. Refuted

None. No verified item was refuted. One high (res-security-adversity-3, suspension does not block browser sign-in) was cut to low because it is the documented DCORE-4 design and the UI labels already say "cannot sync".

## Coverage gaps

What the hunters said they did not get to, and what therefore still needs a look before launch:

- **Live behaviour, never measured.** No live network, NAS, Resolve, real frozen exe or real container was touched. Payload sizes and timeouts on real lossy links (res-network-3), the NTFS/APFS power-loss outcome (res-crash-3/-4), rclone against a real SFTP target and ZFS case sensitivity (res-storage-7), Syncthing completion on a paused folder (res-dataloss-4), Resolve Free / scripting None / 18.x / BPG on port 1144 (res-resolve-1/-6/-7), and snapshot churn on ZFS (res-time-scale-10) are all inferred from code.
- **Platforms.** macOS SMB hard mounts, macOS exFAT normalisation, the macOS LaunchAgent relaunch path, APFS specifics, Synology btrfs quotas and DSM restore paths (skimmed only), Synology DSM API in depth. Long paths could not be reproduced on this rig (LongPathsEnabled=1).
- **Components not covered.** Timeline Cards agent tunnel, engine state across restarts and per-episode data restore (feature off); the server-side ytdl stack (dormant in the vendor build); b-roll and music indexer concurrency and their own SQLite writers; music CLAP index at scale (same shape as res-time-scale-2, unmeasured); whisper/MulticamPipeline output atomicity; Syncthing's own crash and disk-full internals, and its memory/CPU at 500k files x 50 devices; b-roll/music migrations at boot; session store internals; the triage reply path in depth; Android; OIDC provider outage; PyPI/GHCR availability during a fresh appliance install; music indexer model downloads; offsite replication mechanics.
- **Audits started but not finished.** "Every process wait has a time limit" beyond rclone and jobs; the dashboard's SQLite contention under slow reports and the report handler's write-lock time at 50 machines; WAL checkpoint starvation (argued, not probed); the Resolve media-pool walk at 10k+ clips; a full innerHTML XSS audit of the four SPAs (spot-checked only); Cards edit-chat prompt injection; dashboard-to-TrueNAS TLS (known trust-model-8); companion lane-by-lane error classification beyond storage errors; SPA error surfaces for b-roll, music and ytdl; SYS-18a rename/clone logic (assumed adequate from reading).
