# Companion: what syncs when, the Syncthing lane, and the safety latches

Terms used throughout this section:

- **Lane A**: the upload lane. It copies video originals from the editor's computer up to the NAS with rclone. It never deletes.
- **Lane B**: the proxy download lane. It copies proxy files (files under a `Proxy` folder) down from the NAS with rclone.
- **Lane C**: the Syncthing lane. Syncthing (a separate peer-to-peer sync program running on the same computer) syncs everything else in a project (project files, documents, small assets) in both directions.
- **Selection** or **plan**: the list of projects the dashboard says this computer should sync, each with a position (order), a slug (short id, also used as the Syncthing folder id), a `rel_path` (path under `Projects/` on the NAS), a label, and a mode.
- **Tick mode**: each selected project is either `full` (all three lanes) or `upload_only` (lane A alone).
- **Turn**: the time the sequencer spends on one project before moving to the next.
- **Pass**: one trip through every selected project in order.
- **Local root**: the folder on the editor's computer that holds the project tree (for example `P:\`).
- **Halt**: an operator- or fleet-wide "stop all sync" switch that persists across restarts.
- **`.stignore`**: Syncthing's per-folder ignore file. The companion writes a fixed list into it so Syncthing never carries video originals or proxies (those belong to lanes A and B).

## The sequencer: one project at a time, in the dashboard's order
(source: sync/sequencer.py)

### When it runs at all
- Runs only when the dashboard integration is enabled (managed mode). If the selection client reports itself disabled, starting the sequencer does nothing.
- A second start while the first loop is still alive is ignored with a log warning (never two sequencers at once).
- On start it re-arms lanes A and B (clears their "stopped" latch) so a sign-out followed by sign-in brings proxy downloads back.

### Sequencer states (what the tray line shows)
- `startup`: tray line "starting up".
- `no_selection`: tray line is one of three whole sentences:
  - "Waiting for the server: this computer has no plan saved yet" (dashboard unreachable, no cached plan on disk).
  - "Waiting for the server: using the plan saved on this computer" (dashboard unreachable, cached plan exists).
  - "Nothing to sync yet: no projects are ticked for this computer" (dashboard answered with an empty plan).
  - Fallback text "Nothing to sync yet".
- `running`: tray line "syncing <label> (<position>/<total>)", or "uploading <label> (<position>/<total>)" when the current project is ticked upload-only. Label falls back to the rel path, then slug, then "?".
- `between_passes`: "idle between passes".
- `paused`: "paused".
- `stopped`: "stopped".
- Moving between states: start goes to `startup`; empty plan goes to `no_selection`; a project turn starting goes to `running`; end of pass goes to `between_passes`; tray Pause goes to `paused` and back to `startup` on resume; stop, or the loop ending for any reason, goes to `stopped`.

### The main loop (background task, continuous)
- At startup (and after every resume from pause), before anything else:
  - Sets Syncthing's global "max folder concurrency" to `lane_c_max_folder_concurrency` (default 2) when the pause scheme is `none` and the value is above 0. Failure (older Syncthing) is ignored.
  - Reads the cached plan from disk, adopts it as the known plan, verifies each folder's `.stignore` (one read per folder), and then un-pauses every folder in the cached plan whose ignore list is confirmed ("leak recovery" for folders a crashed earlier run left paused).
  - Startup ignore verification: a folder whose `.stignore` cannot be read, is missing any required line, or still carries a borrowed-folder restriction while now ticked, is latched "unconfirmed" and stays paused. A folder Syncthing does not know (404) is skipped. If the companion is told to stop part-way through verification, every not-yet-verified folder is latched unconfirmed too.
- Each loop iteration:
  1. If paused, parks until resumed or stopped (no work, no heartbeat complaint).
  2. Reconciles the shared asset libraries (see Shared folders below), even with nothing ticked.
  3. Fetches the plan from the dashboard. Empty or unreachable: sets `no_selection`, waits `selection_poll_interval` (default 60 s, or until woken), and loops.
  4. Adopts the plan, reconciles borrowed folders, then asks the repather to move any project the server renamed (before any lane touches it).
  5. Asks lane B to probe that the NAS remote root really is the project tree, once per process (skipped when lane B is off).
  6. Runs one pass over the projects.
  7. Asks lane B to run its `.ccsync-trash` retention (every pass, even if the pass failed; the retention has its own interval gate; skipped when lane B is off).
  8. Sets `between_passes`, un-pauses folders (leak recovery), updates the idle backoff, and waits the idle time (or until woken).
- One failing pass never kills the loop: the error is logged at ERROR with its traceback, counted ("N failed pass(es) since launch"), written as a local crash report, and the loop waits the normal idle time and continues.
- If the loop thread ever does end on an exception, the reason is recorded for the watchdog and the state is forced to `stopped`.

### Liveness reporting (read by the companion's lane watchdog)
- Heartbeat is stamped at the top of every loop iteration and at the start of every project turn.
- "Seconds since heartbeat" is reported as 0 when not running, stopped, dead, or paused by the editor (a deliberate pause is never an outage).
- While lane A or lane B has a child process still moving bytes, its latest progress counts as a heartbeat (so a 70-minute upload of one big file is not read as a wedge).
- "Thread died" is true only if the sequencer was started, never stopped, and its thread is gone.
- Exposes the last exception that ended the thread or that a pass survived, and the count of failed passes.

### Waking up early
- Any of these cut the current wait short and reset the idle backoff to 1x: a watcher event in a ticked project, tray "sync now", resume, a plan change (tick, untick, mode change, borrowed-folder change), lane A finishing a background upload hand-off.
- "Sync now" and resume also forget every lane A "clean check" so lane A looks at every project again on its next turn.

### Idle backoff between passes
- Base wait is `sequencer_idle_seconds` (default 60 s).
- After each pass that moved no files, the multiplier steps through 1x, 2x, 5x (so 60 s, 120 s, 300 s at defaults) and stays at 5x.
- Any pass that moved at least one file resets it to 1x, as does any wake-up event above.

### Order and promotion
- Projects run in ascending `position` order from the plan.
- A file change the watcher sees in a ticked project (or in a borrowed folder, which promotes its borrower) moves that project to the front of the remaining queue, right after the current one. It never interrupts the project currently running.
- A change in a project already done this pass does not re-queue it; it only shortens the wait before the next pass.
- After each project the plan is fetched again. If the order of slugs changed, the pass restarts with the new plan, skipping projects already done this pass whose entry is unchanged.

### What makes a plan entry usable (refusals)
- An entry is skipped (never synced, never used to build a path or folder id) when any of: `rel_path` missing, blank, not a string, or unsafe (contains `..`, a backslash segment, a drive letter, and so on); `slug` missing, blank, or not a string; `active` explicitly false; `sync_mode` not one this build knows.
- `sync_mode` missing or blank means `full`. An unknown mode means "do not sync this project at all" (fails closed).
- A skipped entry produces a log warning when its turn comes up.

### One project's turn, in order
1. Clears the project's previous turn record and its "changed since last turn" mark.
2. Repath: if the server renamed the project, moves the local folder first. If an earlier rename could not be applied (the repather holds a "blocked" event for this project), the whole turn is skipped so nothing gets created at the new path before the move happens.
3. Directory skeleton clone (full ticks only, never upload-only): lists the project's folder tree on the NAS and creates any missing folders locally, including empty ones. Runs on the first turn after startup, immediately after a repath, and then every `structure_clone_every_n_passes` turns (default 10; 1 = every turn; 0 = never except right after a repath). Refuses (log warning "drive disconnected?") when the local root is not a directory. Logs "created N missing project folder(s)".
4. Releases any Syncthing folders this sequencer paused earlier.
5. Runs lanes A and B for the project (see below), with a per-project time budget of `project_rotation_seconds` (default 600 s; 0 or less means no budget).
6. Upload-only tick: stops here (after an orphan scan). No borrowed folders, no lane C.
7. Full tick: for each borrowed subfolder this project borrows, runs the skeleton clone (on its own schedule), lanes A and B with its own full budget, and an orphan scan.
8. Orphan scan of the project, then the lane C turn.
9. Records what the turn found (only if the turn completed; a stop or pause mid-turn leaves no record).

### Lanes A and B within a turn
- By default (`concurrent_lanes = true`) lane B runs on a second thread at the same time as lane A. With `concurrent_lanes = false`, lane A runs first, then lane B.
- Lane B runs only when `lane_b_enabled` is true (default true; base rigs that read proxies straight off the share turn it off) and the project is not upload-only.
- Lane A is told it "may hand off": if it runs past the budget with files still uploading, it lets them finish in the background and the rotation moves on.
- Bounded wait for lane B: the turn waits up to lane B's hard ceiling (computed by the rclone lane from the budget) plus 120 s. If lane B is still running after that, its rclone child is killed ("lane B did not finish within Ns on <subpath> -- ending its rclone so the rotation can continue") and the turn waits up to 30 s more. If it is still alive, the turn walks away and latches "lane B abandoned".
- While "lane B abandoned" is latched, no new lane B run is started on any project; lane B is marked stalled with the text "stalled on <subpath>: waiting for an earlier pass to end". The latch clears only when that abandoned run finally ends (log: "proxy download is back in the rotation"), or if its thread is found dead.
- A lane B run that waited behind an abandoned one drops itself if the rotation has since moved to another project (only for rotation runs; consolidate and FIX ALL runs are never dropped).
- Offline detection: if both lane A and lane B end in error on the same project, the NAS is treated as unreachable and the rest of the pass is abandoned (log: "lanes A and B both failed on <slug> -- treating the server as unreachable and ending this pass early; the next one runs in Ns"). Only applies when lane B ran.

### Lane A clean-project skip (saves NAS logins)
- Setting `lane_a_verify_seconds` (default 7200 s = 2 h; 0 disables the skip and lane A runs every turn).
- A lane A run counts as a "clean check" only if it found nothing, deferred nothing to a background or express upload, and the file watcher was the same uninterrupted watcher from start to end.
- On a later turn, lane A is:
  - **skipped** if a clean check exists, the watcher has not restarted since, no watcher event in the project arrived later than 30 s plus lane A's minimum file age before that check started, no lane B run failed this pass, and the check is younger than `lane_a_verify_seconds`. A skipped run counts as "found nothing".
  - **run in verify mode** (narrow connection pool) under the same conditions when the check is older than the limit, or when a lane B run failed this pass.
  - **run in full** in every other case, including any doubt.
- All clean checks are forgotten on: tray "sync now", resume, and any change to the plan (tick, untick, mode flip, borrowed-folder change).
- Clean checks live only in memory: after a restart lane A runs everywhere on the first round.

### Skip-ahead for a project with a big proxy backlog
- Setting `lane_b_idle_recheck_seconds` (default 600 s; 0 turns it off).
- After a project's turn ends with lane B stopped at its budget with files left, that project gets another turn straight away (instead of rotating) only if ALL of these hold:
  - the setting is above 0, lane B is enabled, and the pause scheme is `none`;
  - not stopping, not paused, not halted (or halt state unknown), not an offline pass, local root present, the project is a usable full tick, no lane B run is abandoned;
  - there is at least one other usable project, and every other project had a complete turn that started no more than the window before this turn started, in which every lane run (A, and for full ticks B and each borrowed subpath) found nothing, with the same tick mode as now;
  - the watcher has seen no change in any other project since its turn started;
  - no other full-tick project has an unconfirmed `.stignore` or is waiting as a pending (offered but not accepted) Syncthing folder; and that pending list could be read.
- Log line: "<label> still has files to fetch and the other N project(s) found nothing in the last M min -- giving it another turn".
- A plan change always wins over a skip-ahead. Turn records live only in memory, so the first round after a restart is the plain rotation.

### Orphan `.partial` report
- Every `orphan_scan_every_n_passes` turns per project (default 20; 0 disables), lists the project on the NAS and counts `*.partial` files left by killed lane A runs, for reporting. Never deletes anything.

### Lane C turn (Syncthing) for one full-tick project
1. If Syncthing is offering this project's folder (it is in the pending list), accepts it at `<local root>/Projects/<rel_path>`, labelled with the rel path, from the offering device. The accept may only release the folder if the machine is not halted.
   - If the pending list cannot be read (other than "no such endpoint"), or the accept fails, the folder is latched unconfirmed and left paused (log: "could not be accepted cleanly -- leaving it paused rather than syncing without ignores").
2. Re-asserts the folder's policy:
   - Reads the `.stignore`. If complete, nothing is written. If any required line is missing, the read failed, or it still carries a borrowed-folder restriction, writes the full required list. If that write fails, the folder is latched unconfirmed and left paused (log: "could not confirm ignores for folder ... leaving it paused rather than syncing without them").
   - Ensures file versioning and "ignore deletes" are set on the folder (failures logged but do not block).
   - A folder Syncthing does not know (404) is treated as fine and skipped.
3. Pause scheme (setting `lane_c_pause_scheme`):
   - `none` (default): nothing else is paused. Syncthing paces itself via max folder concurrency.
   - `rotate` (DORMANT: only when set by hand): every other full-tick folder in the plan is paused for this project's turn.
   - Any other value: log warning and `none` is used.
4. Un-pauses this project's folder (in both schemes).
5. Waits for Syncthing to settle: polls the folder status every 5 s until there is nothing left to download AND every other device has everything this machine holds for the folder, or until the wait budget runs out, or the plan's order changes (checked at most once per `selection_poll_interval`), or the folder status cannot be read.
   - Wait budget: under `rotate`, `project_rotation_seconds`. Under `none`, `lane_c_settle_seconds` (default 30 s) capped at `project_rotation_seconds`; `lane_c_settle_seconds = 0` restores the full rotation wait.
6. Re-reads the Syncthing config; if the folder is still paused, retries the unpause (log: "still paused after its lane C turn -- retrying the unpause").

### Un-pause sweeps and the "unconfirmed" latch
- Un-pause sweeps run at startup, after each pass, on tray Pause, on stop, and on resume.
- A sweep never releases: anything while the machine is halted (or halt state unknown; log "syncing is halted -- leaving every lane C folder paused"); an unusable plan entry; an upload-only project; a folder whose ignores are unconfirmed (by this sequencer or by the Syncthing admin's half-accepted-folder record).
- It reads the folder list once and only writes to folders that are actually paused. If the list cannot be read, it un-pauses every eligible folder anyway.
- Any single un-pause is refused while halted (log "not unpausing <slug> -- syncing is halted").
- The unconfirmed latch clears only when a `.stignore` write actually succeeds, or a read shows the full list. It is dropped for a project only when the project leaves the plan entirely (not when it merely becomes invalid, for example archived).

### Pause, resume, stop
- Pause (tray): stops after the current step, waits up to 5 s for any in-progress lane C pause sweep, then un-pauses folders (pause stops lanes A and B but leaves lane C running).
- Resume: forgets lane A clean checks, wakes the loop.
- Stop: waits up to 5 s for any lane C sweep, waits up to 10 s for the loop thread, then un-pauses folders (unless halted) and sets `stopped`.

### Halt support (the sequencer's side)
- Lists every Syncthing folder a halt must pause: the plan's full-tick projects, plus the shared asset libraries, plus lender folders this machine borrows from.
- Re-pause list after a restart onto a halted machine: the above plus every project and lender in the cached plan on disk (whichever editor's plan it is), filtered to folders currently running. If the folder list cannot be read, returns every id.
- Release after a halt is lifted: un-pauses through the same sweep (respecting the unconfirmed latch). If the sequencer has never run in this process, it reads the cached plan, verifies its ignore files first, releases, then reconciles the asset libraries and borrowed lender folders (lending the cached lender list for that one reconcile).

### Per-project status rows (feeds a tray window)
- One row per project in the plan: label, mode, state, per-lane state (A, B, C), and a sentence.
- States and sentences:
  - `blocked` with the repather's sentence, when a server rename could not be applied locally.
  - `blocked`, "Waiting for its filter list from the server. It starts by itself once that arrives." when the `.stignore` is unconfirmed.
  - `paused`, "Sync is paused on this computer." when the sequencer is paused or stopped.
  - `syncing`, "Syncing now (N of M)." for the current project.
  - `waiting`, "Waiting its turn." for projects still queued this pass; `waiting` with no sentence otherwise.
  - Upload-only rows that are syncing or waiting get "Uploads only. Proxies do not come down for this project." appended.
- Per-lane state: only the current project shows live lane states (lane A's and lane B's own state words, lane C "syncing"); others show "waiting" (or "paused"). Lane B shows "off" for upload-only or when lane B is disabled; lane C shows "off" for upload-only.
- Also exposed: the list of projects waiting for their filter list; one sentence per shared or borrowed folder that is not working; the last few server-side renames and what happened to each (slug, old, new, time, relinked, note).

### Project renames by the server
- Before each pass, and again right before each project's lanes, the repather moves the local folder of any project the server moved. Before moving, any background lane A upload reading from that folder is ended ("its folder is being moved to where the server now keeps it"). The moved project is relinked in Resolve via the file-move relink.
- A rename forces a skeleton clone on that project's next turn.

### Upload-only questions answered for other parts
- "Is this path inside an upload-only project?" Compared after Unicode NFC normalisation, case folding and slash normalisation; anything unplaceable answers no. Lane A uses this to decide whether to carry every file instead of only video.

### Settings read by the sequencer (all from the companion config)
- `selection_poll_interval`: default 60 s. Wait when nothing is ticked; also the throttle on mid-turn plan re-reads.
- `project_rotation_seconds`: default 600 s. Per-turn budget for lanes A and B (each borrowed subpath gets its own); also the lane C wait cap.
- `sequencer_idle_seconds`: default 60 s. Base wait between passes.
- `lane_b_enabled`: default true.
- `concurrent_lanes`: default true.
- `structure_clone_every_n_passes`: default 10 (0 = never, 1 = every turn).
- `lane_c_pause_scheme`: default `none`; also `rotate`.
- `lane_c_max_folder_concurrency`: default 2 (0 = do not set).
- `lane_c_settle_seconds`: default 30 (0 = wait the full rotation time).
- `orphan_scan_every_n_passes`: default 20 (0 = off).
- `lane_b_idle_recheck_seconds`: default 600 (0 = off).
- `lane_a_verify_seconds`: default 7200 (0 = off).
- A bad (non-numeric) value never crashes startup; it falls back to the default.
- Fixed numbers: folder status poll 5 s; lane B join grace 120 s; lane B abort join 30 s; idle backoff steps 1x/2x/5x; startup and pause lane C sweep wait 5 s; stop join 10 s.

## Lane B circuit breaker (stops proxy download when the server looks wrong)
(source: sync/lane_guard.py)

- What it does: when tripped, lane B (proxy download) stops on this machine and stays stopped until a person resumes it. Lane A (uploads) and lane C keep running.
- State file: `lane_b_breaker.json`, written atomically (temporary file named with the process id, then replaced). Survives restarts. The caller passes the location; a copy found at the older location (`<log dir>/state/`) is moved (not copied) to the new one once, with a log warning ("moved the sync latch ... state/ is the directory support sessions are told to delete").
- Remembers: tripped or not, the technical reason, the cause code, when it tripped, cumulative deletions and bytes since last cleared, the last pass's deletions, when it was last resumed, the dashboard resume request already honoured, and the last seen size of each NAS listing scope (up to 512 scopes stored).

### Trigger 1: the NAS listing looks wrong (checked before a pass)
- A listing that failed is NOT a trip (logged at info; the run fails on its own).
- Whole-tree scope only: if none of the marker folders (default `Projects`) is present at the remote root, trips with cause `root_unrecognised` and the technical text "the NAS root does not look like the tree: none of Projects is under remote_root (saw N entries). Check remote_root in config.toml."
- If the listing is empty but held more than 0 entries last time, trips with cause `remote_empty` ("the NAS listed <scope> as EMPTY, and it held N entries last time. Syncing from it would move every local proxy here into the trash.").
- If the scope previously held at least 4 entries (`lane_b_min_remote_sample`) and now holds fewer than half (`lane_b_remote_shrink_fraction` 0.5) of that, trips with cause `remote_shrank` ("the NAS listing for <scope> shrank from N to M entries since the last pass ...").
- Otherwise remembers the new count as the baseline.

### Triggers 2 and 3: what a pass deleted (checked after a pass)
- Deletions here mean files lane B moved into `.ccsync-trash` because they vanished from the NAS.
- Per-pass limit: 50 (`lane_b_max_deletes_per_pass`). If the scope held at least 20 local proxies (`lane_b_min_local_sample`) before the pass, the limit becomes the smaller of 50 and 25% (`lane_b_max_delete_fraction`) of that count (minimum 1). Exceeding it trips with cause `pass_deletes`.
- Cumulative limit: 4 times the per-pass limit, so 200 by default (`lane_b_max_deletes_cumulative`), counted since the breaker was last resumed. Exceeding it trips with cause `cumulative_deletes` ("a slow leak").
- Local proxy count: number of files under any folder named `Proxy` (any case) in the scope, never counting `.ccsync-trash`, capped at 200,000.
- Moves are not deletions: files the server reports as relocated elsewhere in the tree are subtracted on every pass. When a pass would trip, or when it trashed at least half the per-pass cap (25 by default, minimum 2), a relocation probe also runs (one recursive listing) and files found on the NAS under a different path are subtracted from both counters (log: "N of this pass's trashed file(s) are still on the NAS under a different path ... not counting them against the breaker"). Any probe failure counts every file as a deletion. Relocation counts are capped at the pass's deletions.
- In-flight counting: while a pass runs, its running deletion total is added to the cumulative count and saved to disk at most every 20 s, so a crash mid-pass does not erase the count. A new pass starts its in-flight count at zero.

### What the editor is told when it trips
- Log line at ERROR: "lane B CIRCUIT BREAKER TRIPPED: <reason> -- proxy download is stopped on this machine until someone resumes it from the tray. Uploads (lane A) and the assets lane (C) keep running ..."
- A callback fires exactly once per trip (used elsewhere for a toast).
- The editor-facing sentence is chosen by cause, each ending "Nothing was deleted and your uploads are still running. Ask your admin to check the server.":
  - root_unrecognised: "The server does not look like your project tree right now, so CCSync stopped downloading proxies before anything could be removed."
  - remote_empty: "The server suddenly listed nothing where your proxies were last time, so CCSync stopped downloading proxies before anything could be removed."
  - remote_shrank: "Far fewer files are on the server than there were last time, so CCSync stopped downloading proxies before anything could be removed."
  - pass_deletes: "One proxy download pass would have cleared out far more files than normal, so CCSync stopped it."
  - cumulative_deletes: "Proxy download has been clearing out files steadily for a while, so CCSync stopped it."
  - A trip saved by an older build (no cause) is mapped from words in its technical reason; if nothing matches, the technical reason is shown; if that is empty, "Proxy download stopped itself as a safety measure." plus the tail.
- Report block (`sync_guard.lane_b_breaker`): tripped, reason, cause, editor_reason (only while tripped), tripped_at, deletes, bytes, last_pass_deletes, resumed_at.

### Resuming
- Resume (from the tray, or from the dashboard's resume request delivered on the report reply) clears the latch AND every counter, including the remembered NAS listing sizes, so the next listing becomes the new baseline. Logged "lane B breaker RESUMED by <who>".
- A dashboard resume request carries an id; the same id is applied only once (it is saved before the latch clears), because the request repeats on every report reply until an admin clears it.

### Settings
- `lane_b_max_deletes_per_pass` (50), `lane_b_max_delete_fraction` (0.25), `lane_b_min_local_sample` (20), `lane_b_remote_shrink_fraction` (0.5), `lane_b_min_remote_sample` (4), `lane_b_remote_marker_dirs` (`Projects`; a single string or a list), `lane_b_max_deletes_cumulative` (4 x per-pass). A non-numeric value logs a warning and uses the default.

## Lane B free-space floor
(source: sync/lane_guard.py)

- When the sync drive's free space falls below the floor, lane B parks (state `paused`, not an error). Lanes A and C keep running.
- Setting `lane_b_min_free_bytes`: default 20 GiB. 0 turns the feature off.
- Clears itself when free space reaches twice the floor (40 GiB by default). Between the floor and twice the floor it stays parked.
- A measurement that failed changes nothing in either direction.
- State file `lane_b_disk_floor.json` (parked, reason, when, last free bytes); survives restarts.
- Sentences (GB is binary, rounded to whole numbers):
  - below the floor: "this drive has N GB free, and proxy download needs F GB"
  - above the floor but below the clear point: "this drive has N GB free, and proxy download starts again on its own at C GB"
  - The sentence is rebuilt from each new measurement while parked.
- Log at ERROR when parking: "lane B is NOT downloading proxies: <reason>. Uploads (lane A) and the assets lane (C) keep running. It starts again on its own once C GB is free, or when someone resumes it from the tray." A callback fires (used elsewhere for a notification).
- Resume (tray or admin): clears the park immediately so the next pass can try; if still under the floor it parks again.
- Report block: parked, reason, at, free_bytes, floor_bytes.

## Disk report
(source: sync/lane_guard.py)

- Report block `sync_guard.disk`: free and total bytes of the sync drive, free bytes of the system drive, and a timestamp. Any value that cannot be measured is null (never 0).
- System drive: Windows uses the `SystemDrive` environment variable (default `C:`) plus a backslash; macOS and Linux use `/`.

## `.ccsync-trash` recovery folder and its retention
(source: sync/lane_guard.py)

- Lane B moves files it would delete into `<local root>/.ccsync-trash/<YYYYMMDD-HHMMSS>/` (one folder per run, called a batch). This file decides how long those copies are kept.
- Retention rules, applied in order:
  1. Any batch older than 14 days (default) is removed. Age is the newest file time in the batch; if nothing could be read, the time in the batch folder's name.
  2. If the rest is still over 50 GiB (default), oldest batches are removed until under the cap. The newest batch is never removed by this rule.
  3. If a free-space floor is passed in and free space is below it, oldest batches are removed until free space reaches the floor. The newest batch is never removed by this rule either. Log warning: "only N GB free under <root> (the floor is F GB) -- dropping recovery copies the age and size rules would have kept".
- Nothing is pruned while the lane B breaker is tripped (log: "trash prune skipped: the lane B breaker is tripped, keeping every copy").
- Every removal is logged with its size and reason ("older than 14 days", "trash over the N GB cap", "under the F GB free-space floor").
- How often: the default interval constant is 6 hours; the sequencer asks once per pass and the interval gate lives in the rclone lane.
- Trash summary (for a tray window with an "open the recovery folder" button and a retention line): path, file count, bytes, oldest batch time, retention days. The walk is capped at 50,000 files (then marked truncated) and cached for 60 s per root; the cache is dropped after any prune.

## The sync halt ("stop all sync")
(source: sync/lane_guard.py)

- Different from Pause: Pause stops lanes A and B and leaves Syncthing running. A halt stops lanes A and B and pauses every Syncthing folder, and is saved to disk.
- State file `sync_halt.json`: active, scope, reason, time. Saved atomically.
- Two scopes:
  - `local`: the editor set it; the editor can clear it.
  - `fleet`: an admin set it on the dashboard; adopted from the report reply. The tray cannot clear it. Refusal text: "your admin stopped syncing for the whole fleet: <reason>. Only they can start it again."
- Engage: logged "SYNC HALTED (<scope>): <reason>". Counts as a change (so the caller stops lanes) when newly active, when a local halt becomes fleet, or when the reason changes.
- Release: refused with "syncing is not stopped" when not active. On success returns "syncing will start again" and logs "sync halt RELEASED by <who>".
- Fleet flag from the dashboard reply: absent means "no information" and never releases. Active adopts a fleet halt with the dashboard's reason or, if none, "your administrator stopped syncing across the fleet". Inactive releases only a fleet halt (a local halt is untouched).
- Report block: active, scope (only while active), reason, at.

## Safety state that cannot be saved
(source: sync/lane_guard.py)

- Applies to the breaker, the free-space floor and the halt. If writing the state file fails, the latch is held in memory, an ERROR is logged once ("SAFETY STATE NOT SAVED: <file> could not be written. Whatever is latched here is remembered in memory only, so restarting CC Sync would clear it. It is retried every 60s."), and each later report read retries the write at most every 60 s.
- While failing, the report block adds `persist_failed: true`, `persist_error`, `persist_failed_at`. These keys are absent when all is well.
- On recovery logs "written again after ... -- the latch is on disk".


## Lane C: watching the local Syncthing
(source: sync/syncthing_lane.py)

- Lane C does not sync anything itself and does not install Syncthing. It reads the status of a Syncthing that the installer set up and reports a lane state (idle, syncing, paused, error) with a queue count and a detail sentence. It also drives the Syncthing supervisor (restart of a dead Syncthing, see below).

### Where it finds Syncthing
- REST API address: default `http://127.0.0.1:8384` (overridable by the caller's config).
- Request timeout: 5 s.
- API key: a configured key wins and is the only one tried. Otherwise the key is read from Syncthing's `config.xml` (the `<gui><apikey>` element), trying in order:
  - the CC Sync managed Syncthing home: Windows `%LOCALAPPDATA%\ccsync\syncthing-config\config.xml`; macOS and Linux `~/.local/ccsync/syncthing-config/config.xml`;
  - the stock Syncthing home: Windows `%LOCALAPPDATA%\Syncthing\config.xml`; macOS `~/Library/Application Support/Syncthing/config.xml`; Linux `$XDG_CONFIG_HOME/syncthing/config.xml` (default `~/.config`).
  - The key the running Syncthing last accepted is tried first. A 401 or 403 means "wrong home", so the next key is tried. With no key anywhere, one unauthenticated attempt is made.
- REST calls never follow redirects (so the API key is never sent elsewhere).

### Poll loop (background task)
- Every 15 s (`poll_interval`), runs a full check, unless the quiet rule below applies.
- Quiet polling: after 4 full checks in a row that ended idle, a poll becomes just a ping plus one connections read. The full check runs again as soon as the set of connected devices changes, the byte counter goes backwards (Syncthing restarted), more than 64 KiB crossed the wire since the last full check, the ping fails, or 120 s have passed since the last full check.
- One failing poll is logged and the loop continues. Start is idempotent; stop waits up to 5 s.

### Full check, in order, and the lane state it produces
1. No API key anywhere: state `error`, "no Syncthing API key (checked <path>)". The supervisor is told Syncthing is unreachable (so it can restart it, which regenerates the home).
2. Ping:
   - 401/403: state `error`, "Syncthing is running but rejected every known API key (checked <paths>)". The supervisor is told it is alive (no restart).
   - any other failure: state `error` with the supervisor's sentence, or "Syncthing not running" when there is no supervisor.
3. Reads connections. Records which connected devices are relayed (connection type starting `relay`) or direct. If any are relayed, the detail gains "relayed, slow path (N device(s) via relay)". Records total bytes in and out (used as a progress token `c:<bytes>` so the dashboard can tell a stalled lane from a slow one).
4. Reads the Syncthing config once and runs the "folder path missing" heal (below) over every configured folder.
5. Works out which folders it should be judging: the sequencer's full-tick project slugs (upload-only projects excluded), else a static list from config.
   - None: state `idle`, detail "no project folders to check yet", and the previous "last synced" time is kept (never set to now).
6. For each expected folder: if not in the config, "<id> (not configured)"; if shared with no other device, "<id> (not shared with any device)"; notes paused ones.
   - Config unreadable: state `error`, "failed to read Syncthing config: <error>".
   - Some folders missing, but every missing one is currently offered by the server (pending): state `syncing`, detail "setting up N newly ticked project(s)".
   - Otherwise: state `error`, "folder(s) not configured/shared: <list>".
7. Per folder: adds up items this machine still needs to download; collects folders in error state or with errors, with Syncthing's own error text (for example "folder marker missing").
8. Per folder, per other device: adds up items and bytes those devices still need from this machine (outgoing).
9. Verdict:
   - Any folder in error, or any project waiting for its filter list: state `error`, joining "folder(s) in error: <list>" and "N project(s) are not sharing yet - waiting for their filter list: <up to 5 slugs>[, +K more]".
   - Anything owed in either direction: state `syncing`, queue = download count if any, else upload count. Direction field: `down`, `up`, `both`, or blank when no peer is connected. Detail: with no peer connected "waiting: not connected to the server (N file(s) owed)"; uploading only "sending N file(s) (<size>) to the server"; otherwise the relay detail.
   - Every expected folder paused: state `paused`, "N folder(s) paused", previous "last synced" kept.
   - Otherwise: state `idle`, "last synced" set to now.
- Problems with shared or borrowed folders are added to the detail in every branch (never change the state): the first problem sentence, plus "(+N more)" if there are several.
- Its own device id is re-read every 300 s; a change logs "this machine's Syncthing device id changed (old -> new) -- its config was regenerated".

### Healing "folder path missing"
- At most once every 60 s, for every configured folder that is not paused: if Syncthing reports the folder in error with "folder path missing" but the folder's marker (default `.stfolder`, or the folder's configured marker name; `~` is expanded) now exists, asks Syncthing to rescan that folder. Each folder is asked at most once every 300 s. Log: "folder <id> said 'folder path missing' but <path> is there -- asked Syncthing to rescan it".
- Purpose: an external drive that comes back is picked up within a minute instead of at Syncthing's next hourly scan. A rescan only reads.

### Other read-outs
- "Is the API reachable at all": a ping; 401/403 counts as reachable.
- The connection summary (devices and their connection types, relayed list, direct list) is exposed for the report sent to the dashboard.


## Borrowed folders (a ticked project that uses a folder from another, unticked project)
(source: sync/sequencer.py, sync/borrowed_folders.py, sync/syncthing_admin.py)

Terms: the **borrower** is the ticked project; the **lender** is the other project whose subfolder it uses; the borrowed **subpath** is that subfolder.

### Which borrowed folders count (decided by the sequencer from the plan)
- Each plan entry may carry `includes`. An include is used only if: the borrower is a usable full tick (an upload-only borrower builds nothing); the include is not marked `covered` (the lender is ticked here) unless that lender is ticked upload-only here, in which case it is run anyway; the subpath is safe, at least two segments deep, contains no `Proxy` segment, the lender slug is a non-blank string, and the sub-relative path is the tail of the subpath.
- An invalid include is dropped with a log warning ("dropping an invalid includes entry on <slug> ... refusing to build a path from it"); dropping syncs nothing extra.
- An include equal to or under a full-tick project's own folder is skipped (that project's own runs cover it). An include under one already granted this pass is skipped (first one by plan order wins).
- Lenders that are not themselves full ticks here form the borrowed-lender list (lender, its rel path, the borrowed subpaths, the borrowers).

### Lanes A and B for borrowed folders
- Inside the borrower's turn, each borrowed subpath gets its own lanes A and B run with its own full time budget, its own skeleton clone schedule and its own orphan scan.
- A file written in a borrowed subfolder promotes the borrower in the queue, and lane A uploads it under the lender's NAS path.

### Lane C for borrowed folders (the lender's Syncthing folder, restricted)
- Background task: reconciled once per sequencer pass (after the plan is adopted) and after a halt is released.
- Skipped entirely when the local root is not present, or the lender list cannot be read.
- Per lender:
  - Missing rel path or no subpaths: outcome `invalid`, problem sentence "<rel> could not be set up on this computer: the server's description of it is incomplete. It keeps trying."
  - Not configured in Syncthing: same accept flow as the asset libraries (outcomes `ask-failed`, `not-offered`, `halted`, `error`, `accepted`), but the folder is created at `<local root>/Projects/<lender rel>` with the restricted ignore list, so only the borrowed subfolders sync. Log "accepting borrowed folder <slug> (<rel>) from <device> at <path>, restricted to N subtree(s)".
  - Configured but at a different path (the lender moved on the NAS): pauses, moves the old local directory if the new one does not exist (failure: "could not move ...; re-pointing anyway (Syncthing will re-pull the subtree)"), creates the new directory, re-points the folder and relabels it. Refused if the local root is missing (folder left where it was). Log: "borrowed folder <slug> is at '<old>', re-pointing it at '<new>' (the lender moved on the NAS)". Before the move, any background lane A upload reading from that folder is ended.
  - Adds versioning and ignore-deletes if missing.
  - Ignore list must contain every wanted line AND be in the restricted shape; otherwise rewrites it (log "borrowed folder <slug>: .stignore is missing N line(s) ... / not restricted -- re-asserting the restricted list").
  - Paused: stays paused while halted; released once the restricted list is confirmed; otherwise stays paused with outcome `unfiltered` ("its restricted .stignore could not be confirmed, and the lender's whole folder must not go online here").
- Problems, sentences and retry backoff are the same as for the asset libraries. A lender nobody borrows any more has its problem cleared.

### Dropping a lender nobody borrows any more
- After each reconcile: every local Syncthing folder that is not a current lender, not a currently ticked full project, and whose ignore list is in the restricted shape, has its Syncthing config removed. Files on disk stay. Log: "borrowed folder <slug> is no longer borrowed by any selected project -- removing its local Syncthing config (files stay on disk)".
- Never runs when the ticked list is empty or unknown (a dashboard blip must not remove every borrowed folder).

### When the editor ticks a lender they were borrowing from
- The folder leaves the borrowed set and becomes a normal project folder. The sequencer sees its restricted ignore list, keeps it paused (startup) or rewrites the full project list on its turn (log "carries a restricted (borrowed-folder) .stignore but is selected here -- rewriting the full ignore list") before releasing it.

### Halts
- Lender folders are included in the set of folders a halt pauses.


## Syncthing supervisor: restarting a dead Syncthing
(source: sync/syncthing_supervisor.py)

- Background behaviour, driven by each lane C poll (every 15 s): if the local Syncthing REST API stops answering, the companion restarts Syncthing using the launcher the installer registered. It never installs Syncthing and never edits its config.
- Kill switch: config key `supervise_syncthing` (top level, or inside a `[sync]` table). Default on. Only the strings "false", "0", "no", "off" (or a false value) turn it off; anything unreadable leaves it on.

### How it restarts, per platform
- Windows: runs `wscript.exe //B //Nologo %LOCALAPPDATA%\ccsync\bin\CCSyncSyncthing.vbs` (the same script the logon Run entry uses), fully detached from the companion (no console window, own process group, no inherited handles), so Syncthing survives the tray quitting or self-upgrading. Success means only "the script ran".
- macOS: runs `launchctl kickstart -k gui/<uid>/com.ccsync.syncthing` and waits up to 20 s for it; a non-zero exit fails with the last line of launchctl's error output (up to 200 characters). Requires `~/Library/LaunchAgents/com.ccsync.syncthing.plist` to exist. The old `com.creatorsclub.*` label is not supported.
- Linux and anything else: no launcher; every attempt fails with "there is no registered sync engine launcher for <platform>".
- If the launcher file is missing: "the sync engine launcher is missing (<path>). Ask your admin to re-run the CC Sync installer on this machine."

### Timing and limits
- Grace: the API must be unreachable for 30 s before the first restart attempt.
- Backoff between attempts, measured from when the previous attempt finished: 30 s, 1 min, 2 min, 4 min, 8 min, then 10 min forever.
- After launching, waits up to 20 s (checking every 2 s) for the API to answer. If it does not: failure "it was started but 127.0.0.1:8384 did not answer within 20 s". If no API probe is wired in, the next poll decides, and a launch that has not been confirmed within 20 s is counted as failed ("it was started but 127.0.0.1:8384 still does not answer").
- Only one launch at a time, even if two callers notice the outage together.
- If the wall clock jumps backwards, the outage is re-timed from now (one extra grace period).
- Attempt counter capped at 100,000.

### When it deliberately does nothing
- Supervision switched off: logs once "the sync engine is down and supervise_syncthing is false on this machine -- NOT restarting it ...".
- The machine is halted or paused (the reason comes from the caller): logs once per reason "the sync engine is down but <reason> -- leaving it stopped ...". If that check itself fails, it stands off with the reason "the halt/pause check could not be read".

### What a person sees
- Lane C error text while the API is unreachable (also shown on the tray line and the dashboard chip):
  - "the sync engine (Syncthing) is not running on this machine -- restarting it" (normal case);
  - "the sync engine (Syncthing) could not be started: <error>" (after 3 or more failed attempts);
  - "the sync engine (Syncthing) is not running on this machine, and it is not being restarted: automatic restarts are switched off on this machine (supervise_syncthing = false)";
  - "the sync engine (Syncthing) is not running on this machine, and it is not being restarted: <halt or pause reason>".
- Tray balloons (title from the site's notification title):
  - "Sync engine was not running: restarted it" when the API answers again after at least one restart attempt.
  - "Sync engine will not start: <last line of the error>" once, on the third failed attempt.
- Log lines: attempts 1 and 2 at info, the third at warning ("the sync engine has failed to start N times: <error>. Lane C (audio, graphics, subtitles, project files) is carrying NOTHING on this machine until it runs."), later ones at info.
- Report section `sync_guard.syncthing_supervisor`: absent when healthy; while down: down_since, attempts, last_error, last_attempt, supervising (true when enabled and not standing off).

### State that survives restarts
- State file `syncthing_supervisor.json` (location passed in by the caller): when the outage began, attempts, last error, last attempt time, whether the warning was given, and whether an attempt is awaiting confirmation. Deleted when the API answers again.


## Syncthing folder policy written by the companion
(source: sync/syncthing_admin.py)

- The companion changes the local Syncthing only through its REST API. Same API-key discovery and 401/403 fallback as lane C (see above); requests never follow redirects. Reads time out after 5 s; config writes after 30 s (Syncthing restarts a folder on each config write).
- Folder ids are percent-encoded when put in a URL, so an id containing `/`, `?` or `#` cannot address a different endpoint.

### The project folder ignore list (`.stignore`)
- Every project folder on an editor machine carries these lines so Syncthing never carries what lanes A and B own:
  - one case-insensitive line per video extension: `.braw`, `.mov`, `.mp4`, `.mxf`, `.avi`, `.mts`, `.m2ts`, `.mkv`, `.r3d`, `.crm`, `.mpg`, `.mpeg`, `.wmv`, `.webm`, `.insv`, `.360`;
  - rclone's in-progress files: `*.partial` (anywhere);
  - yt-dlp's in-progress files: `*.part`, `*.part-Frag*`, `*.ytdl` (anywhere);
  - the companion's own half-copied files: `*.ccsync-tmp` (anywhere);
  - any folder named `Proxy` at any depth, and everything under it.
- A folder's ignore list counts as complete when every one of those lines is present (extra lines are allowed). A folder with no `.stignore` at all, or an answer of an unexpected shape, counts as missing every line.

### Shared asset folders (fleet-wide libraries every editor gets without ticking)
- Two are defined:
  - `assets-luts`, path `Assets/Luts`, label "Assets/Luts (LUT library)".
  - `assets-stills`, path `Assets/Stills`, label "Assets/Stills (Resolve gallery)".
- Their ignore list: the same video extensions, `*.partial`, and OS junk: `.DS_Store`, `Thumbs.db`, `desktop.ini`, `*.tmp`, `*.ccsync-tmp` (anywhere). No `Proxy` lines and no yt-dlp lines.

### Borrowed-folder restricted ignore list
- For a lender's folder that this machine only borrows parts of, the `.stignore` is: the full project list, then for each borrowed subfolder `!/<sub>` and `!/<sub>/**` (case-exact), then `**` (ignore everything else). Videos, proxies and partial files stay excluded even inside the borrowed subfolder.
- Special characters in the subfolder name are made literal: on Windows `[`, `{` and `}` are wrapped as one-character classes; on macOS and Linux `\ * ? [ ] { }` are backslash-escaped.
- A list is recognised as restricted when its last non-blank line is `**` and at least one `!` line comes before it.

### Writes the companion makes
- Pause or un-pause a folder.
- Re-point a folder to a new local path (and optionally new label) after the server moved a project.
- Add versioning to a folder that has none: staggered, cleaned every 3600 s, versions kept up to 30 days (2,592,000 s). Logged "folder <id> had no versioning -- adding staggered".
- Turn on "ignore deletes" for a folder that lacks it: this machine never applies a delete made on another device. Logged "folder <id> had no ignoreDelete -- adding it".
- Set the global max folder concurrency (only when it differs; logged "maxFolderConcurrency <old> -> <new> (pacing lane C without pausing folders)").
- Accept an offered folder: creates it as send-and-receive, paused, file watcher on, permissions not ignored, staggered versioning, ignore deletes on, shared with the offering device; then writes the ignore list (project list by default, or the list passed in); then un-pauses it, unless the caller's "may release" check says the machine is halted, in which case it stays paused (log "accepted folder <id> but left it paused: syncing is stopped on this machine"). Until the ignore write returns, the folder is marked "ignores unconfirmed" in memory, and sweeps will not un-pause it.
- Remove a folder from Syncthing's config (files on disk are left alone). Used before "remove this project from this machine".
- Write a folder's ignore list. A write that returns clears the folder's unconfirmed mark; so does a read that shows the list complete.

### Reads the companion makes
- Full config, one folder's config, all folders' configs, pending folder offers, a folder's ignore list, a folder's status, system status (own device id), connections, options, what one remote device still needs from this machine for a folder, and the folder's overall completion across all devices (used by the remove-from-this-machine gate to check nothing local is still unsent).


## Shared asset libraries (LUTs and Resolve stills) on every editor machine
(source: sync/shared_folders.py)

- Two fleet-wide Syncthing folders every editor gets without ticking anything: the LUT library at `<local root>/Assets/Luts` (folder id `assets-luts`) and the Resolve gallery stills at `<local root>/Assets/Stills` (folder id `assets-stills`). They are not part of the project rotation.
- Background task: reconciled at the start of every sequencer loop iteration (so roughly every pass, and every `selection_poll_interval` when nothing is ticked), and also after a halt is released. Steady state costs reads only and no config writes.

### What a reconcile does, per library
- Skipped entirely (nothing created, nothing changed) when the local root is not present. A check that cannot answer counts as absent.
- If Syncthing does not have the folder:
  - Reads the pending offers. If that read fails: outcome `ask-failed`.
  - No offer from the server: outcome `not-offered`.
  - Offer present but the machine is halted: leaves the offer pending (outcome `halted`, not recorded as a problem); it is accepted on the first reconcile after the halt.
  - Otherwise creates the local directory (refused if the local root is not a directory at that moment: log "refusing to create ... (that mkdir would build a ghost tree on the boot disk)"), then accepts the offer from the first offering device with the asset ignore list, paused until the ignore list is written, released only if not halted. Outcome `accepted`.
  - A folder that answers with an empty body is treated as absent.
- If Syncthing has the folder:
  - If its path differs from the expected path: pauses it, moves the old directory to the new path if the old one exists and the new one does not, creates the new directory, and re-points the folder. Outcome `repaired`. Refused (outcome `error`) if the local root is missing. Log: "shared folder <id> is at '<old>', re-pointing it at '<new>' (local_root moved, or it was accepted by hand)".
  - Adds versioning and ignore-deletes if missing (outcome `repaired`; failures ignored).
  - Reads the ignore list; rewrites it if any asset line is missing (outcome `repaired`). A read or write failure is "unconfirmed".
  - If paused: stays paused while halted ("stays paused: syncing is stopped on this machine"); is released when the ignore list is confirmed ("was paused -- releasing it", outcome `repaired`); stays paused if unconfirmed (outcome `unfiltered`).
  - If running (or just re-pointed) and its marker (default `.stfolder`) is not in the folder: outcome `marker-missing`, log "has no .stfolder marker: the sync engine will not scan it". The marker is never created by the companion.
- Any exception: outcome `error` (logged as a warning once per run per folder, debug after).

### Problems shown to the editor
- Outcomes `not-offered`, `ask-failed`, `unfiltered`, `marker-missing` and `error` are kept as problems until a later reconcile of that folder succeeds. Each produces one sentence (shown on the tray, the Settings window, the lane C detail and the report):
  - not-offered: "<name> has not been shared with this computer yet. Ask your admin to approve it."
  - ask-failed: "<name> is not set up yet: CC Sync could not ask the sync engine about it. It keeps trying."
  - unfiltered: "<name> is not syncing yet: CC Sync could not confirm its filter list, and a folder without one must not go online. It keeps trying."
  - marker-missing: "<name> is not syncing on this computer: its folder moved and the sync engine will not start it at the new place on its own. Ask your admin to remove it from this computer's sync engine so it is offered again."
  - other: "<name> could not be set up on this computer[: <reason up to 200 chars>]. It keeps trying."
  - <name> is the folder label, for example "Assets/Luts (LUT library)".
- A folder with a problem is retried on a backoff: 60 s, doubling, capped at 30 min. Between retries its last outcome stands.
- The third consecutive failed attempt is logged as a warning with the same sentence.
- Problems are kept in memory only; a restart re-learns them on the first pass.
- The library folder ids are included in the set of folders a halt pauses.


## The sync plan: fetching this computer's ticked projects from the dashboard
(source: selection.py)

- Managed mode is on only when `dashboard_url` is set. With it blank, every call below returns "nothing" and the sequencer does not run.

### Fetching the plan
- Request: `GET <dashboard_url>/api/v1/selection/<editor>?machine=<this computer's hostname>`. The editor name is lower-cased and URL-encoded; it comes from the signed-in identity (evaluated on every fetch), falling back to `editor_name` in config.
- Headers: `X-CCSync-Token` (the shared fleet token, re-read from config on every request so a token refreshed at sign-in takes effect at once; falls back to the value at startup) and `X-CCSync-Identity` (the signed identity token, only when signed in; never sent empty).
- Never follows redirects (a redirect counts as a failure). Timeout 5 s.
- No editor name yet (not signed in): no request is made; treated as a failure without logging.
- A response that is not an object with a `selection` list is a failure.
- Throttles:
  - `selection_fetch_ttl` (default 30 s): a successful answer is reused from memory for this long (keyed on the editor, so signing in as someone else fetches at once).
  - After a failure, no new request for the same editor for the same 30 s.
  - A forced fetch bypasses both.
- Failure logging: a warning on the first failure of a streak ("selection fetch failed: <error>"), debug after that.
- Answer sources reported to the sequencer: `live`, `cache` (dashboard failed, using the plan saved on disk), or `none`.

### The plan saved on disk
- File `selection.json` in the companion state directory: the full last response, the editor it belongs to, and when it was written. Written atomically (temporary file then replace), and only when the plan or editor actually changed (the dashboard's `generated_at` stamp is ignored when comparing).
- File `selection_fetched.json`: when the dashboard last answered at all. Written at most once an hour.
- A saved plan that names a different editor than the one signed in is not used (log once per pair: "the cached plan is <a>'s, not <b>'s -- not using it"). A plan with no editor name, or a moment with no signed-in editor, is used. The halt re-pause reads the saved plan whoever it belongs to.
- Older cache format (just a selection list) is still read.
- "How old is the plan": the newer of the cache's write time and the last-answered stamp; null when unknown (never shown as fresh).

### Removing a project from this computer (the tray's "remove from this machine" first step)
- Refused with "dashboard_url is not configured" or "no editor identity yet -- sign in first".
- Sends `DELETE <dashboard_url>/api/v1/selection/<editor>/<slug>?machine=<hostname>` with the same headers and no redirects. Errors: "dashboard refused the untick (HTTP <code>)", "dashboard unreachable: <error>".
- Then, depending on the dashboard's answer (its view of the plan after the delete):
  - 404 for the machine-scoped delete (dashboard does not know this hostname): retries without `?machine=` (removes the tick for every computer of this person). Log "the dashboard does not know this machine -- removing the tick for every machine".
  - Delete succeeded, the answer says something changed, but the project is still in this computer's plan: refused, nothing deleted: "the dashboard still lists it in this computer's sync plan after the untick. Untick it on the dashboard's sync plans page".
  - Delete succeeded, nothing changed (or the dashboard is too old to say), and the project is still listed: the tick comes from the unassigned bucket, so it retries person-wide.
  - Delete succeeded but provably removed nothing and the project is not listed: asks whether the project is ticked on any of the person's computers (`GET /api/v1/selection/<editor>` without machine). If it is: refused with "the dashboard has no tick for it under this computer's name (<host>), but it is still ticked for another of your computers. If this computer was renamed, wait until the dashboard shows the new name, or untick it on the dashboard". If that cannot be answered: refused with "the dashboard has no tick for it under this computer's name (<host>), and could not be asked whether another of your computers holds it. Try again in a minute". If it is ticked nowhere: allowed.
  - Success returns "unticked" and makes the next plan read go to the network.

### Recording "originals on request" picks for this computer
- `PUT <dashboard_url>/api/v1/selection/<editor>/<slug>/originals?machine=<hostname>` with JSON `{"add": [{"rel", "is_dir"}], "remove": [rel], "via": "resolve" by default}`. Same headers, no redirects.
- Returns the HTTP status (0 when unreachable), the parsed body (a 409's body is returned so its `detail` sentence can be shown verbatim), and an error text. Same two refusals as above when not configured or not signed in. A success makes the next plan read go to the network.

### Project roots (which NAS folder a Resolve project's media belongs in)
- The plan response may carry `project_roots`: Resolve project name to `rel_path`. Built into a map of lower-cased Resolve project name to `Projects/<rel>`. An entry whose path is unsafe (escapes the tree) is dropped with a warning ("dropping project_roots entry for ... is not a contained relative path").
- Answer comes with a source: `live`, `cache`, or `unreachable`. Callers must refuse to pick a destination on `unreachable`.
- Refreshed if older than `project_roots_ttl` (default 300 s). A failed refresh returns the in-memory map labelled `cache`, else the disk copy as `cache`, else empty and `unreachable`.

### Settings
- `dashboard_url` (blank = managed mode off), `dashboard_token`, `editor_name`, `selection_fetch_ttl` (30), `project_roots_ttl` (300). Non-numeric TTLs fall back to defaults.


## Local media manifest (what video this computer holds, reported to the dashboard)
(source: manifest.py)

- Background task: rescans every `manifest_refresh_interval` seconds (default 300; non-numeric falls back), starting immediately at launch. Readers always get the last finished scan; reading never walks the disk.
- What it scans: every project folder under `<local root>/Projects/<year>/<series>/<project>` (found by the same project discovery the fixer uses), plus every ticked project even if its marker has not arrived yet.
- Per project it reports: number and total bytes of video originals; number and total bytes of proxies (video files anywhere under a folder named `Proxy`, any case); whether the file lists were cut short; and, for ticked projects only, the file lists (relative path and size) of originals and of proxies. Other projects get counts only.
- Only files whose extension is in the sync lanes' video extension list count; audio, stills and project files are ignored.
- Limits:
  - At most 2,000 entries per file list per project (counts and bytes stay exact; `truncated` is set).
  - At most 64 projects. When there are more, ticked projects come first, then the most recently modified, then alphabetical. Logged once per change: "media manifest reports N of M project(s): the dashboard accepts at most 64 per report (B6). Ticked projects and the most recently touched are kept; K older project(s) are not in this machine's presence data." and "media manifest is no longer truncated" when it recovers.
  - Ticked-project matching uses Unicode NFC normalisation, so a Mac's decomposed accented names still match.
- When the local root is missing (drive unplugged), the scan is skipped and the last good scan is kept. If the drive disappears during a scan, that scan is discarded.
- A scan that fails is logged and the last good scan is kept.

### Syncthing conflict copies
- During the same walk it counts every file whose name contains `.sync-conflict-` (any extension), anywhere in any reported project, and keeps up to 20 example paths (`<project>/<path>`).
- Exposed as `{count, paths}`; absent (empty) when there are none. Replaced only by a successful scan.
- While any exist, every scan logs a warning: "N Syncthing conflict cop(y/ies) on this machine (e.g. ...). Nothing here deletes or merges them."
- The companion never deletes or merges conflict copies.


## Root guard: is the sync drive actually here?
(source: root_guard.py)

- Background task: every 5 s (minimum; a non-positive value logs an error and uses 5 s), checks whether the local root is usable and calls back only when the answer changes (the first real answer always calls back, so a companion that starts with the drive unplugged is told at once). What the callbacks do (pause or resume lanes) lives elsewhere.

### The five states
- `present`: the tree is there. On macOS, for a root under `/Volumes/<Name>`, it must also be on a real mount point.
- `absent`: the drive is unplugged, or (macOS) the folder at `/Volumes/<Name>` is an empty leftover on the boot disk and not a mount point (a "ghost").
- `misplaced` (macOS only): the recorded volume is mounted somewhere else (for example `/Volumes/T7 1` because a leftover folder occupies `/Volumes/T7`). Only detectable when a volume UUID was recorded; otherwise reported as `absent`.
- `not_answering`: the drive is present but its filesystem has stopped answering file opens (checked from a separate short-lived process, because an in-process check would itself hang).
- `unknown`: the check itself failed, or no local root is configured. Treated as "no new information": the previous state stands and nothing is paused or resumed.
- `absent`, `misplaced` and `not_answering` all mean "do not touch the tree".
- Before the first real answer, the tree is assumed present (a slow first check must not switch anything off).

### Per platform
- Windows and Linux: a plain "is it a directory" check; present or absent only. No volume record is written.
- macOS, root not under `/Volumes`: same as Windows.
- macOS, root under `/Volumes/<Name>`: also checks the mount point; if not mounted, looks for the recorded volume UUID among the other mounted volumes using `/usr/sbin/diskutil info -plist <mount>` (10 s timeout, answer cached for 30 s per mount point, including "no UUID").

### The "not answering" probe
- Runs on the first poll, then every 12th poll, and on any poll right after an in-process check that took 2 s or more.
- Only a "blocked" result counts (state `not_answering`). A probe that cannot be run, or answers promptly, gives no opinion and the normal check runs.
- Logged once per episode: "<root> did not answer an open() from a separate process (<detail>). The drive is not out -- its filesystem has stopped responding, so every lane is paused until it does. Reconnect it or restart."

### Sentences shown to the editor (tray line, balloon, lane detail, dashboard)
- not_answering: "the sync drive is not answering - reconnect it or restart"
- misplaced: "the sync drive is mounted at the wrong place - eject it, delete the leftover empty folder, then plug it back in"
- absent (and anything else): "the sync drive is disconnected"

### Volume record (macOS)
- File `volume.json` in the companion's config directory (`~/.ccsync/`), seeded by the macOS installer: volume UUID, mount point, local root. Written atomically with permissions 600, only when something changed. If diskutil returns no UUID but one is already recorded, the old UUID is kept. Logged "recorded the sync volume <mount> (uuid=...)". Never written on Windows or for a root not under `/Volumes`.
- A local root is treated as "legitimately comes and goes" (so its absence at startup is a runtime state, not a config error) when the host is macOS and the root is under `/Volumes`, or the volume record names this exact root.

### macOS blocking access (Full Disk Access lost)
- A check (run elsewhere, on a timer after a self-upgrade) answers "is macOS refusing us the sync root while the volume is mounted?": true only on macOS when listing the root (or the volume it sits on) fails with permission denied (EACCES or EPERM) and the volume is still mounted (or the root is on the internal disk). Any other failure answers false. Never touches the disk on Windows.

### Shutdown behaviour
- A check that completes while the guard is stopping is not acted on and not recorded, so the lanes are never started during teardown and a later restart still sees the change.
- Stop waits up to max(2 s, half the poll interval); if the check is still running it keeps the old thread rather than starting a second one.


## Drive reminder: the sync drive went out with work still owed
(source: drive_reminder.py)

- When the sync drive disappears while lanes are genuinely moving files (which lanes count as "alive" is decided by the power guards' pending-work tracker, not here), the editor gets a warning naming what was still to go, then reminders until the drive comes back.

### What is counted as owed
- For each live lane: its count of files transferring, else its queue count, else 1 if it is in `syncing` state with no counters. Bytes left are added up where the lane reports totals (lane C reports none).
- Nouns per lane: lane A "upload(s)"; lane B "proxy download(s)"; originals lane "original download(s)"; lane C uploading "other file upload(s)"; lane C downloading "other file download(s)"; lane C with no or two directions "other file(s)"; anything else "file(s)".
- Summary format: items joined with commas and "and", plus " (<size> left)" when bytes are known, for example "2 uploads and 14 other files (2.3 GB left)". Size units B, KB, MB, GB, TB (binary).
- Nothing live means nothing is shown (the separate calm "Sync paused" balloon belongs to the caller).

### Balloons (title from the site's notification title for "sync unfinished")
- First warning, when the drive goes: "<Your ... drive> was disconnected before syncing finished: <summary> still to go. Plug it back in to finish syncing."
- Reminder: "<Your ... drive> is still disconnected and syncing is unfinished: <summary> still to go. Plug it back in to finish syncing."
- Reminder for a drive that is plugged in but not answering, when nothing was owed: "<Your ... drive> is still not answering, so nothing is syncing. Reconnect it or restart this computer." (No first warning from here; the caller has just shown one.)
- Every balloon is also logged as a warning.
- The drive phrase comes from the site configuration (for example "Your Creators Club drive").

### When reminders repeat
- Interval: `drive_reminder_minutes`, default 30. 0 keeps the first warning only. Negative or non-numeric logs an error and uses 30.
- Reminders repeat only if something owed is an upload (lane A, lane C uploading, lane C with unknown direction, or an unknown lane). If everything owed is a download (proxies, originals, lane C downloading), only the first warning is shown (log: "nothing owed is an upload, so the first warning stands alone ...").
- A "not answering" episode always repeats.
- Only one episode at a time. A work-owed episode always wins over a "not answering" one; a "not answering" episode ends when the drive's state changes, a work-owed one does not.
- The drive coming back clears everything (log "drive reminder: cleared (...)").

### Muting (buttons offered elsewhere, for example a Settings window)
- "Remind me later" (snooze N minutes): silence now, one reminder after N minutes, then the normal interval.
- "Stop reminding me about this drive": silence for the rest of this episode.
- Muting does not remove the standing warning line in the tray or Settings, is not saved (a restart with the drive still out reminds again), and ends with the episode.
- When nothing owed is an upload, the episode reports itself as already muted (no reminder is coming).

### Surviving a restart
- File `drive_unfinished.json` (location passed in by the caller): summary, sentence, kind, lanes, start time. Written best-effort (temporary file then replace), deleted when the drive comes back. Not a safety latch: losing it costs a reminder.
- At startup with the drive still out: a remembered work-owed episode resumes without a new first warning but with one immediate reminder, then the usual cadence (log "the drive was out with work owed when the companion last ran (...) -- reminders carry on"). A remembered "not answering" episode resumes only if the drive is in that same state now; otherwise it is dropped.
- Quitting stops the reminder timer but keeps the file.


## Grade swap: pointing the sync drive letter at the server's originals (Windows only)
(source: drive_swap.py)

- Purpose: for remote colour grading, temporarily remap the sync drive letter (default `P:`) from the editor's local copy (proxies) to the NAS's SMB share (camera originals), then back. Resolve paths do not change; only what the letter points at. The sync lanes are unaffected (they work on the physical local root, not the drive letter). The menu item and the decision to call it live elsewhere; this file does the mapping.
- Drive letter: taken from the site's `canonical_prefix`; anything that is not a single letter (a UNC path, a POSIX path, a typo) falls back to `P:`. The loopback share name follows the letter: `CCSync_P`, `CCSync_Q`, and so on.
- Every shell command and the network connect share a 30 s ceiling. Shell commands run with no console window and no stdin (so `net use` cannot sit waiting for a typed password).

### Where the letter points now
- Reads `net use <letter>` (takes the UNC path to the end of the line, so share names with spaces work), then `subst`.
- Classified as: `local` (the loopback share `\\localhost\CCSync_<L>`, or a legacy `subst` mapping to the local root), `server` (the server UNC), `other` (something else), or `none` (nothing mapped, or the mapping could not be read).

### Swap to the server
- Refusals:
  - No server path configured: "server_p_unc is not configured".
  - Letter mapped to something CC Sync did not create: "<L> is currently mapped to <target>, which CCSync did not create. Swapping would replace it and CCSync cannot put it back."
  - Mapping could not be read or nothing is mapped: "CCSync could not tell what <L> is mapped to, so it is being left exactly as it is. Nothing was changed. If <L> is not mapped at all, restart the CCSync app or re-run the installer to put your local mapping back, then try the swap again."
- Already on the server: "<L> already shows the SERVER originals".
- Otherwise: removes the current mapping (`net use <L> /delete /y`, then `subst <L> /D`; `/y` answers the open-files prompt because Resolve holds files open), then connects the letter to the server share with the Windows network API (temporary, not persistent), passing the editor's server username and password when given (they are never put on a command line), else the credentials Windows already has stored. Never prompts.
- Success: "<L> now shows the SERVER originals". The caller must restore the local mapping on failure (this function does not roll back).
- Failure messages:
  - timeout: "the server did not answer within 30s -- the drive was not remapped" (a late connect may still land afterwards);
  - exception: "mapping <L> failed: <ExceptionType>" (the exception text is never shown, because it could contain the password);
  - Windows error codes, each with its own sentence: 5 "access is denied -- the server refused this logon"; 53 "the network path was not found -- is the server up and reachable from here?"; 55 "the share is no longer available on the server"; 66 "the server offered the wrong resource type for a drive"; 67 "the network name was not found -- check the share path"; 85 "<L> is already in use by another mapping"; 86 "that password is not correct for this server"; 1219 "Windows already holds a connection to this server as a different account -- disconnect it (or sign out) and try again"; 1223 "the connection was cancelled -- the server wants credentials for this share"; 1200 "<L> is not a valid device name"; 1203 "no network provider accepted the path"; 1326 "the user name or password is incorrect"; 1327 "this account cannot log on with a blank password"; any other "System error N mapping <L>". Each is prefixed "System error N: ".
- "Needs credentials" detection (the tray then asks for the server login and retries): any failure message containing denied, logon, credential, password, 1326, user name, 1223, canceled, cancelled, or username. Errors 53, 67 and 1219 deliberately do not match.

### Saving the server login
- After a successful credentialed swap, the login can be stored in Windows Credential Manager (a domain-password entry for the server host, persisted for the local machine), so later swaps and Explorer authenticate silently. Best effort; failure is logged at debug only, never with the password.

### Swap back to local
- Removes the current mapping, then maps the letter to `\\localhost\CCSync_<L>` persistently ("<L> is back to your local copy (proxies)").
- If that fails, falls back to `subst <L> <local root>` ("<L> is back to your local copy (proxies, via subst)").
- Failures: no local root: "local_root is not configured -- <L> is currently UNMAPPED"; subst failed: "<L> could not be restored (<last 200 chars of error>) -- remap it by hand or re-run the installer".

### Working out the server share path (last-resort fallback)
- From the dashboard URL's host and the NAS `remote_root`: TrueNAS `/mnt/<pool>/<rest>` becomes `\\<host>\<rest>`; Synology `/volume<N>/<rest>` becomes `\\<host>\<rest>`. Anything else gives nothing. A configured `server_p_unc` or the site's `smb_unc` take precedence (decided by the caller).

### Logging
- Every command line that is logged has any `/pass:` argument and the password itself replaced by `***`.


## Power guards: warn before shutdown and keep the machine awake while syncing
(source: shutdown_guard.py)

### Which lanes count as "really moving" (shared by both guards and the drive reminder)
- A lane is busy if it is in `syncing` state or has queued items. `paused` and `error` lanes never count.
- A busy lane only counts while it is alive:
  - its status (state, queue, transferring count, bytes done, bytes total, last sync time) changed within the last 180 s (a lane that has just become busy always counts at first);
  - and nothing says it has no peer to send to (lane C with no connected Syncthing device does not count; "unknown" never vetoes). Logged once: "<lane> reports work outstanding but has no connected peer -- not counting it as a reason to stay on".
  - A lane reporting the same backlog for 180 s with nothing moving is treated as stalled. Logged once: "<lane> has reported the same backlog for N minutes with nothing moving -- treating it as stalled, not as a sync worth staying on for".
- Hold ceiling, per lane: after 8 hours of continuous busy, that lane stops counting until it settles. Logged once: "<lane> has been busy for N hours without settling -- standing down for it: no more shutdown warnings or keep-awake on its account until it does".
- Both limits are passed in by the caller (a non-positive value logs an error and uses the default); the comments name the config keys `keep_awake_stale_seconds` and `keep_awake_max_hold_seconds`.
- Any failure inside this check means "not busy" (never traps anyone).

### The sentence shown
- "CCSync is still syncing[ -- <size> left[, about N min | about Nh Mm]]. Any file part-way uploaded has to start again from the beginning next time you switch on."
- Bytes left are summed over lanes that report totals; the time estimate is the slowest lane's estimate, shown only if 60 s or more. Cut to 255 characters.

### Windows: shutdown, restart and log-off
- A hidden top-level window (class `CCSyncShutdownGuard`, title `CCSync`) answers Windows' "may the session end?" question.
- If something is really moving: blocks, and Windows shows its "This app is preventing you from shutting down" screen with the sentence above. The person can still press "Shut down anyway". Logged "shutdown requested while syncing -- blocking: <reason>".
- If nothing is moving, or the sentence cannot be put on that screen, or anything fails: allows the shutdown.
- When the session really ends, records a deliberate exit (the caller's callback) so the next start does not report a crash. This window is built even when the shutdown warning is switched off, with a reason that never blocks.
- Start waits up to 5 s for the window ("window did not come up within 5s"); stop waits up to 2 s for a window still coming up and 3 s for the thread, and never starts a second one.
- Sleep is not covered by this guard (see keep-awake).

### macOS: logout, quit
- SIGTERM (logout, `launchctl bootout`): turned into the companion's normal graceful shutdown, then passed on to any previous SIGTERM handler. Installed only when a shutdown callback exists. Logged "SIGTERM received (logout or launchctl bootout) -- shutting down".
- Quit: if nothing else owns the application delegate and pyobjc is available, the first Quit while something is really moving is cancelled once and a macOS notification titled "CCSync" shows the sentence (via `osascript`). Any Quit within 120 s of that cancel goes straight through; a later attempt starts a new episode. Any failure allows the quit. Logged "quit requested while syncing -- asking once" / "already warned, allowing".
- There is no way to block a macOS logout; this is a warning, not a block.
- Linux: no shutdown guard.

### Keep-awake (stops idle sleep mid-transfer)
- Background task: every 30 s, asks whether anything is really moving.
- Windows: holds "system required" (never "display required": the screen still turns off) while busy, released within 30 s of the sync finishing, and released when the companion stops. Logged "keep-awake: holding off / released the system idle timer while syncing".
- macOS: runs `/usr/bin/caffeinate -i -w <companion pid>` while busy (idle system sleep only; it dies with the companion even if the companion is killed). If caffeinate exits on its own while still busy, a new one is started ("caffeinate exited on its own (rc=N) while a lane was still busy -- starting another"). On release it is terminated, then killed after 5 s if needed. A failure to start is logged once ("this Mac may sleep mid-upload").
- Linux: nothing.
- Neither can stop a deliberate sleep (Start, Sleep, or closing a laptop lid).
- Any failure lets the machine sleep.
- Both guards can be switched off by the caller (`enabled`); the setting names are not in this file.


## Start guard: rolling back a build that cannot start, and the self-test
(source: startguard.py)

### Counting failed starts (runs before the app itself is loaded)
- Every launch of the companion records a start attempt in `start_attempt.json` (in the state folder beside the log, `<log dir>/state/`): version, process id, time, whether it reached the single-instance lock, whether it finished booting, whether it was a self-upgrade hand-off child (and its spawner), the failed-start count, and whether this is a fresh build.
- Launches with any of these flags are not counted as starts: `--supervise`, `--setup-resolve-prefs`, `--self-test`, `--music-resolve-worker`.
- On the next launch of the same version, the previous attempt counts as a failed start if all of: it never reached the lock, or it reached the lock but never finished booting and was not a duplicate; its process is dead; it is not this process; and it was not a hand-off child whose spawner is still alive (that spawner handles its own rollback).
- A launch whose environment variable `CCSYNC_REPLACES_PID` names a live process (the self-upgrade hand-off) never counts, never records a version start and never reverts.
- "Fresh build": the first start of a version different from the last recorded version.
- After the first counted failure, the start is recorded in the upgrade version record. After 2 counted failures of the same version (one is allowed, for example an antivirus holding the files), the previous build is restored and launched, and this launch exits without starting the app. If the restore is refused, one line is written: "v<version> failed to start N times and was NOT rolled back: <reason> (record ...)".
- Reaching the single-instance lock marks the attempt (a launch that lost the lock is marked as a duplicate, never a failure). Finishing startup marks it booted and resets the failure count to 0.
- `startguard.log` in the same folder holds these lines (the normal log is not set up yet). Deleted and restarted when it exceeds 64,000 bytes.
- Every step here fails safe: any error means "no extra protection", never "no companion".

### Started marker for self-upgrade
- `handoff_started.json` (pid, parent pid, version, time) is written when the new build has loaded everything and is about to wait for the single-instance slot. The self-upgrade waits for this file instead of a fixed delay.

### `--self-test` command-line flag
- The exe imports its app module and every top-level module of its package and prints one line: "SELF-TEST OK v<version> (N modules)" or "SELF-TEST FAILED v<version>: <failures>". Exit code 0 or 2.
- Modules for the other operating system are allowed to fail: on Windows any module whose name contains mac, darwin, objc or appkit; on macOS any containing win32, windows or tray_native_win.
- `--self-test-out <path>` also writes the line to that file.
- Takes no lock, writes no marker, starts no thread; safe to run beside a live companion. Used by release steps to launch what they built.


## Looks redundant or overlapping

- Two lane C pacing schemes are both kept: `none` (default) and `rotate` (DORMANT unless `lane_c_pause_scheme = "rotate"`). Much of the sequencer's pause, release, verify and turn-wait machinery exists only for `rotate`; the skip-ahead is switched off under it.
- Under the default scheme the per-turn lane C wait (up to 30 s per project, `lane_c_settle_seconds`) gates nothing; its stated purpose is only to make the dashboard's "current project" read sensibly.
- Folders are released by six separate paths: startup leak recovery, the between-passes sweep, Pause, Stop, the pre-lane release of folders "this sequencer paused", and the post-turn "still paused?" retry. Every one re-checks the same halt and ignore-confirmation conditions.
- Two "ignores unconfirmed" latches for the same fact: one in the sequencer, one in the Syncthing admin (half-accepted folders), consulted together.
- The shared asset library manager and the borrowed folder manager are near copies (accept, re-point, versioning, ignore-deletes, ignore check, halt hold, marker, problem backoff and sentences). The "is this a 404" helper is written three times.
- Syncthing API-key discovery and the 401/403 fallback are written twice (lane C reader and admin writer).
- Byte formatting ("1.2 GB") is written three times (Syncthing lane, drive reminder, power guards).
- Several stacked "do less work when idle" mechanisms, each with its own setting or constant: idle backoff (1x/2x/5x), lane A clean-check skip and verify mode, lane B skip-ahead, the structure clone every N passes, the orphan scan every N passes, the lane C quiet poll, the selection fetch throttle (both in the selection client, 30 s, and again in the sequencer's mid-turn reads).
- Free-space protection appears twice for the same drive: the lane B free-space park (20 GiB) and the trash prune's free-space rule.
- The "drive not answering" sentence exists in the root guard ("the sync drive is not answering - reconnect it or restart") and again as a drive-reminder sentence with different wording.
- Start-failure rollback (`startguard.py`, 2 failed starts) overlaps with a "three starts in ten minutes" rollback the code comments refer to elsewhere.
- The shared folder and borrowed folder problem sentences reach the editor through four surfaces (lane C detail, tray, Settings, report).
- The halt check is repeated at nearly every write point (sequencer sweep, single un-pause, accept's final release, both folder managers), each with its own "cannot tell counts as halted" handling.

## Claims the code does not back

- `sync/sequencer.py` module docstring: lane C gets "a turn with every other selected folder paused". By default (`lane_c_pause_scheme = "none"`) nothing is paused.
- `sync/syncthing_lane.py` (paused branch comment): "the sequencer pauses all but the current project by design". Only true under the non-default `rotate` scheme.
- `sync/shared_folders.py` `_accept` docstring: it checks "that the offer came from a device this machine is actually paired with". The code accepts from the first offering device listed and makes no pairing check.
- `sync/shared_folders.py` `folder_ids` docstring and `sync/sequencer.py` `halt_folder_ids` docstring: the halt now also pauses "the B-roll archive, the music library and the LUTs" / "B-roll, music and LUT folders". The code only defines two shared folders: LUTs and Stills.
- `sync/shared_folders.py` module docstring describes only the LUT library; the code also manages `assets-stills`.
- `root_guard.py` module docstring: the volume record is "refreshed here on every present sighting". The guard's poll loop never calls the refresh; the function exists but nothing in this file invokes it.
- `startguard.py` `self_test` docstring: it "load[s] the config (read-only)". The code reads only the version constant; it never loads the config.
- `drive_reminder.py` `reminders_muted` docstring: "Compared against the episode's own start time". It compares an episode counter.
- `shutdown_guard.py` macOS docstrings describe pystray owning the NSApplication. The project's tray is its own module; whether the Quit delegate slot is free under it cannot be confirmed from this file.
- `sync/syncthing_supervisor.py` module docstring: the state "survives a restart" like `lane_guard.py`'s. Its file write is a plain in-place write, not the atomic write the lane guard uses; a torn write reads back as "no incident".
- `sync/__init__.py` docstring: the three latches "persist to <state_dir>". `lane_guard.adopt_legacy_latch` says they were moved out of the state folder into the config folder; the final location is chosen by the caller.
- `sync/lane_guard.py` `HaltState` docstring: the halt "is re-applied on the next start". Nothing in this file re-applies it; that is the caller's job (the sequencer only supplies the folder list).
- `drive_swap.py` module docstring: "All functions take an injectable run_fn and never raise". `persist_credentials` ignores its run_fn, and the timed connect re-raises (caught by its only caller here).

## Could not determine

- The exact on-disk locations of `lane_b_breaker.json`, `sync_halt.json`, `lane_b_disk_floor.json`, `syncthing_supervisor.json` and `drive_unfinished.json`: each path is passed in by the caller (not in this part).
- What the companion does on root-guard transitions, on a halt engage or release, and on breaker or free-space trips beyond the callbacks fired here (pausing lanes, tray lines, balloons): wired in `app.py`, not in this part.
- The setting names that enable or disable the shutdown guard and keep-awake guard, and whether `keep_awake_stale_seconds` / `keep_awake_max_hold_seconds` are the real keys (named only in a comment).
- The config keys for `.ccsync-trash` retention (age, size, interval) and where the 6-hour interval gate is enforced: in `sync/rclone_lane.py`, outside this part.
- Lane B's hard ceiling formula, the meaning of lane A/B run outcomes, and lane A's minimum file age: imported from `sync/rclone_lane.py`, outside this part.
- What the repather does when a project is renamed on the server (`sync/repath.py`, outside this part); only the sequencer's use of it is described here.
- Whether `refresh_volume_record` and `access_is_blocked` (root guard) are called anywhere.
- Whether the companion's own macOS tray installs an application delegate, which would silently disable the macOS Quit warning.
- The full set of lane state words (`sync/base.py`, outside this part).
