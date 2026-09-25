# logic-sync-truth - does what the tray and the dashboard SAY about sync match what the lanes DO
Files read (approximate coverage): companion sync/base.py (all), sync/syncthing_lane.py (check_once, connections, 90-140, 485-880), sync/rclone_lane.py (filters 40-140, 650-740, build_up_command, run_once stand-downs 3540-3575, 3840-3865, disk floor 3939-3985, trash prune 4517-4570), sync/lane_guard.py (DiskFloorLatch, prune_trash), sync/sequencer.py (_prune_trash), manifest.py (scan_local_manifest), reporter.py (_lane_liveness), tray.py (compute_overall_color, _sync_line), drive_reminder.py (1-200), shutdown_guard.py (busy_lanes, live_busy, _is_alive), app.py (_on_root_absent, _unfinished_before_pause, _lane_peer_states); dashboard health.py (40-260, 400-460, 787-1314), api.py (build_transfers_view 534-800, build_editors_view 960-1130), db.py (fetch_sync_backlog, replace_editor_media, media_rel_key), ui.py (CHIP_HELP, safe_to_close), templates/partials/transfers.html, fleet_grid.html (grep).
Tests/probes run: one ad-hoc snippet in the dashboard venv against `health.lane_chip` / `health.report_freshness` / `health.fleet_headline` (finding 1). No suites run.

## Findings

### logic-sync-truth-1 - A laptop that is merely asleep gets a red "Upload has stopped" headline after 15 minutes
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/health.py:230 (lane_chip), health.py:1096-1143 (_lane_fault / fleet_headline); api.py:993
- What: `lane_chip` paints EVERY lane RED with reason "this companion has been silent for 15 minutes or more" once the report is 15 min old, although `report_freshness` (UX-2) deliberately makes silence AMBER until 6 h. `fleet_headline` then takes the first red lane (always lane A) and writes "Upload has stopped: this companion has been silent...", level red. A whole-computer silence is blamed on one lane, and the 6 h amber window the freshness rule was written for never shows.
- Failure scenario: an editor shuts their laptop lid at 18:00. At 18:15 the fleet grid row turns red with the headline "Upload has stopped: this companion has been silent for 15 minutes or more", and stays that way all night. Every laptop in the fleet does this every evening, so red means nothing. The admin is also sent looking at the upload lane rather than at "this computer is off".
- Evidence: snippet in dashboard venv, three idle lanes received 20 min ago: `report_freshness` -> `('amber', 'no report since ...')`; `fleet_headline` -> `{'reason': 'lane_error', 'text': 'Upload has stopped: this companion has been silent for 15 minutes or more', 'level': 'red'}`.
- Ledger: new
- Suggested fix: take report silence out of `lane_chip`. Let `report_freshness` answer for the whole row (amber at 15 min, red at 6 h) and give it its own headline ("Not heard from since HH:MM"), ranked above `_lane_fault`.

### logic-sync-truth-2 - The per-kind manifest cap still causes phantom proxy downloads, the UI says the opposite ("may undercount"), and "Safe to close" can miss uploads
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/manifest.py:37,208-223 (MAX_PER_FILE_ENTRIES = 2000 per kind); dashboard/src/ccsync_dashboard/db.py:37,9287-9310 (EDITOR_MEDIA_CAP), db.py:9700-9765 (fetch_sync_backlog); templates/partials/transfers.html:78; ui.py:436-487 (safe_to_close)
- What: CR-314 made the cap per kind, but a project with more than 2,000 proxies (or originals) on one machine still reports only the first 2,000 in walk order. The down diff (`nas_media` proxies NOT IN `editor_media`) therefore counts every proxy past the cap as owed. That is an OVERcount that never clears, but the row says "(this computer's manifest was capped; totals may undercount)". The up diff UNDERcounts: an original past the cap that is not on the NAS is never counted, and `safe_to_close` counts only owed-upload rows, so it can say "Safe to close" (the dangerous direction). Note that `manifest_truncated` only shows on a row that already has files.
- Failure scenario: (a) ruskin's Energy Transition grows from 1,696 to 2,300 proxies. Every proxy is on his drive, but [ QUEUED ] shows "proxy download, 300 files" for as long as the project is ticked, which is the CR-314 phantom again at a higher number. (b) A 2,400-clip multicam project: the 2,001st to 2,400th originals in walk order include a new card that has not uploaded. No upload row exists, and the editor's page says "Safe to close: nothing of yours is waiting to go to the server."
- Evidence: read both sides. The companion appends to `proxies`/`originals` only while `len < 2000`, else sets `truncated`. `replace_editor_media` keeps 2,000 per kind. `down_totals_q` is `NOT EXISTS (editor_media ...)`, and `up_totals_q` only walks `editor_media`.
- Ledger: related to CR-314 (fixed; this is the part it did not cover)
- Suggested fix: when `emp.truncated` is set, suppress the down backlog for that pair, or report n_proxies/bytes as the rollup-only difference. Make `safe_to_close` refuse to say "safe" for an editor with any truncated manifest pair ("cannot tell"). Fix the copy to say the totals are inexact in both directions.

### logic-sync-truth-3 - Tray says "Sync: downloading N files" and pulses amber for ever when lane C has no connected peer
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/sync/syncthing_lane.py:776-851 (check_once verdict); reporter.py:245-272 (no token for lane C); tray.py:2489-2527 (_sync_line), tray.py:241-272 (compute_overall_color / should_pulse); dashboard health.py:183-212 (lane_stall)
- What: lane C reports `STATE_SYNCING, queued=needTotalItems` whenever Syncthing has a need, whether or not any peer is connected. It never sets `progress_token`, so the dashboard's SYS-1 stall rule can never fire for it. The companion does know the peer is gone: `_lane_peer_states()` (app.py:10413) reports lane C False, and `PendingTracker._is_alive` uses that to stop the power guards crying wolf. But the tray line, the icon colour and the pulse never read it.
- Failure scenario: the NAS Syncthing is down, or the tailnet path drops, while a ticked project has 40 items owed. The tray reads "Sync: up 40 · down 40 files" (see finding 5) with a breathing amber icon, meaning "work is happening", for hours. Nothing is moving, and no line says "cannot reach the server". The fleet grid's lane chip stays amber ("syncing") with no stall verdict.
- Evidence: read check_once. None of the `queued > 0` / `outgoing_items > 0` branches consult `_connection_summary`, and `_path_detail` only speaks about RELAYED peers. `_lane_liveness` omits the token because the lane never sets one. shutdown_guard.py:425-430 shows the peer signal exists and is trusted elsewhere.
- Ledger: new
- Suggested fix: in check_once, when the connected-device set is empty and need > 0, publish a distinct detail such as "waiting: not connected to the server (N files owed)". Either make that a non-syncing state (paused/blocked with a reason) or give lane C a progress token from Syncthing's in-sync bytes, so both the tray pulse and the dashboard stall rule work.

### logic-sync-truth-4 - The disk-floor park never clears on its own after the trash prune: the prune stops at 1x the floor, but the latch clears only at 2x
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/sync/lane_guard.py:1005-1050 (DiskFloorLatch.check, clear at DISK_FLOOR_CLEAR_MULTIPLE=2.0), lane_guard.py:1281-1296 (prune_trash pressure trigger stops at `free >= min_free_bytes`); rclone_lane.py:4531-4535 (min_free_bytes = disk_floor.min_free_bytes); dashboard ui.py:305-308 (CHIP_HELP["disk"])
- What: SYNC-16 wired the trash's disk-pressure prune to "the same number" as the floor (20 GB). The latch that parks lane B releases only at 40 GB. The prune therefore stops deleting recovery copies at 20 GB free. That is exactly the point where the latch still reads "parked", and the pressure trigger has nothing more to say, so neither mechanism can move the machine out of the state. The dashboard's disk chip text also still says ".ccsync-trash cannot prune while proxy download is stopped", which has not been true since SYNC-16 moved the prune into the sequencer (only a tripped BREAKER blocks it).
- Failure scenario: an editor's 1 TB SSD drops to 12 GB free, with 35 GB in `.ccsync-trash`. Lane B parks. The sequencer's prune deletes oldest batches until free is about 20.5 GB and stops. The latch needs 40 GB, so proxy download stays "NOT DOWNLOADING (disk)" indefinitely, while about 26 GB of the product's own garbage (which the editor was never told they can delete) sits on the drive. RESUME from the tray starts one pass, which fills the drive back under 20 GB and parks again. Meanwhile the admin reads a chip saying the trash cannot prune.
- Evidence: read the two thresholds side by side. `self.clear_free_bytes = int(self.min_free_bytes * DISK_FLOOR_CLEAR_MULTIPLE)`, versus `if free >= min_free_bytes: break` in the prune loop with `min_free_bytes=self.disk_floor.min_free_bytes`. sequencer.py:1312-1334 runs the prune regardless of the park.
- Ledger: related to SYNC-16 (fixed)
- Suggested fix: pass the latch's `clear_free_bytes` (not `min_free_bytes`) as the prune's pressure target while the latch is parked, so the prune can release the latch. Update CHIP_HELP["disk"] to say the trash IS pruned under disk pressure (except while the breaker is tripped).

### logic-sync-truth-5 - "Idle, nothing owed" is stated without looking at what is owed
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/health.py:1153-1158 (fleet_headline fallback); api.py:1121-1122
- What: the fleet row's all-clear headline is decided only from lane STATES (`any lane == "syncing"`). It never looks at the owed-upload/-download backlog that the same dashboard computes for the transfers page (`fetch_sync_backlog`). Lanes are idle between sequencer rotations and for every project that is not current, so "nothing owed" flips on and off while uploads are still owed.
- Failure scenario: a machine with 3 projects ticked and 60 originals owed in the second project, between passes: the fleet grid says "Idle, nothing owed" (muted), while the same editor's transfers page says "Not yet: 60 file(s) still uploading from DESKTOP-X". Two surfaces disagree on the one question the owner asks, and the one that says "nothing owed" is the one he looks at.
- Evidence: fleet_headline reads `row["why"]`, `companion_outdated` and `row["lanes"]` only. build_editors_view never attaches backlog counts to the row.
- Ledger: new
- Suggested fix: say "Idle" (no claim), or attach the per-machine owed-upload count from `fetch_sync_backlog` to the row and say "Idle, N uploads owed" / "Idle, nothing owed" from that.

### logic-sync-truth-6 - Tray sync line counts every lane C file twice ("up 40 · down 40") and the drive reminder nags about downloads the dashboard calls harmless
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/tray.py:2491-2502 (_sync_line); drive_reminder.py:77-81,128-165 (unfinished_work); dashboard ui.py:419-436 (safe_to_close rule)
- What: (a) `_sync_line` adds lane C's single count to BOTH `up` and `down`. When only lane C is busy, the tray reads "Sync: up 40 · down 40 files", which is 80 claimed transfers for 40 items that are in fact one direction (queued = our download need, or outgoing = upload need, never both). (b) The CR-92 reminder counts lane B proxy downloads and lane C items as "unfinished" (and a lane B pass in `syncing` with 0/0 counts as 1). The dashboard's own "safe to close" rule says uploads alone decide it, because a download resumes. An editor who unplugs mid proxy-download is reminded every 30 minutes that sync is "unfinished", for something the dashboard tells them is safe.
- Failure scenario: (a) a 40-file audio pull reads as "up 40 · down 40". (b) A laptop editor pulls the SSD on the train while lane B is fetching one proxy. The balloon "Your drive was disconnected before syncing finished: 1 proxy download still to go" repeats every half hour until they get home, while the dashboard says "Safe to close".
- Evidence: read `_sync_line` (`if not status.name.endswith("_down"): up += count; if not status.name.endswith("_up"): down += count`), and `unfinished_work`'s `_LANE_NOUNS` / `count = 1` branch.
- Ledger: related to CR-92
- Suggested fix: (a) have lane C say which direction its count is (queued vs outgoing) and count it once. (b) Start the half-hourly reminders only for lane A (uploads). Keep a one-off first warning for downloads.

## Coverage note
Did not get to: collector.py itself (completion/need ingestion, editors_behind rollup), the settings_window lane lines, `_format_lane_line_from`/`classify_lane_error`, lane_guard breaker trip/resume arithmetic (heavily covered by earlier hunts), the sequencer's rotation and pause rules for paused-folder need counts. One suspicion I could not verify offline: with `ignoreDelete` on the server folder, a local delete may leave `/rest/db/completion` for the server with a need that never drains. That would put lane C permanently in the "sending N file(s) to the server" branch. It needs a live Syncthing to confirm.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/api.py:676-699: the in-flight subtraction is keyed by editor only (not machine or direction), and its basename fallback removes a same-named file queued in ANOTHER project or on the editor's OTHER computer from the queue.
