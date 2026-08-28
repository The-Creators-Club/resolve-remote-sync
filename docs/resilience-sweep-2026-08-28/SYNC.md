# Sync engine (SYNC)

## Summary
This is the most heavily defended area in the repo: the lane B breaker, `.ccsync-trash`,
atomic latch files, the ignores-unconfirmed latch, the express/periodic exclusion, the
Syncthing supervisor and the root guard are all real and mostly correct. The defences are
built against *deletion* and against *the NAS being wrong*; they are much weaker against
**"nothing is happening and everything looks green"**. The biggest risk found is that
every long-running child and every filesystem probe on the transfer path is unbounded:
`_run_popen`'s `proc.wait()` (rclone_lane.py:3310), the sequencer's `thread.join()`
(sequencer.py:1579), and `os.path.isdir` inside the root guard itself
(root_guard.py:369) — so a wedged mount hangs the lane, the sequencer, AND the one
detector that would have named the cause. That is CR-91's mechanism, and it is
mechanically the same shape as MAC-12, for which an out-of-process probe
(`probe_watch_root`, rclone_lane.py:682) already exists and is used in exactly one
place. Second theme: **CR-90's NFD/NFC lesson was applied in the dashboard's DB layer
only** — the breaker's relocation probe and the file-move exclusion both still compare a
macOS NFD path against an NFC one, so on a Mac the breaker trips on a benign
reorganisation and a moved file re-uploads itself. Best cheap wins: reuse
`probe_watch_root` in `RootGuard.probe_once`; NFC-normalise the two comparisons above;
and declare `syncthing_supervisor` on `SyncGuardIn` (api.py:4656) so an engine-down
incident reaches the grid.

## Findings

### SYNC-1: a hung rclone child freezes the whole sequencer, with no timer anywhere
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/sync/rclone_lane.py:3310` (`proc.wait()`), `:1303` (`_max_duration_flags`), `sync/sequencer.py:1579` (`thread.join()`), `:2597` (`_run_lock`)
- **Scenario:** leso's Mac, 2026-08-28. The external SSD stops answering opens; rclone's goroutine blocks in the kernel on a local read. Or on Windows: a `subst`ed SMB mapping over a dropped tailnet.
- **Today:** `--max-duration` is rclone's own timer and is set only when the sequencer passes a budget, with `--cutoff-mode SOFT` — it stops *starting* transfers, it does not abort a blocked one, and it is inert if rclone never reaches its scheduler. `proc.wait()` has no timeout; `_run_lock` is held; `_run_lanes_a_and_b` joins lane B with no timeout, so lane A finishing does not release the turn. The lane stays `state=syncing, transferring=1, last_error=NULL` forever and the sequencer never reaches lane B or the next project — verified against the reported symptom in KNOWN_BUGS CR-91.
- **Proposed:** a per-pass watchdog inside `_run_popen`: loop `proc.wait(timeout=30)`; track `bytes` from the `--stats` records `_handle_stderr_line` already parses. If **zero bytes moved** for `max(4 × max_duration_seconds, 900 s)`, log, `_terminate_child`, set `state=error` with `"rclone made no progress for Ns -- killed"`, and add a `sync_guard.stalled_lane` field (persist last-stall in `~/.ccsync/state/`, so a restart does not erase the evidence). Bound `thread.join()` in `_run_lanes_a_and_b` to the budget + grace and log a named warning if it times out. Bytes-not-wall-clock, exactly as CR-91 asks.
- **Effort:** M **Severity:** high **Confidence:** high
- **Related:** CR-91 (OPEN — this adds the verified mechanism and the exact two lines); MAC-12; docs/SYNC_SAFETY.md.

### SYNC-2: the root guard's own probe can block on the wedged mount it exists to detect
- **Lens:** pitfall
- **Where:** `root_guard.py:369` (`present = bool(isdir(root))`), `:750` (`_loop`), `rclone_lane.py:2566`, `sequencer.py:1716`, `manifest.py:242`; the fix already exists at `rclone_lane.py:682` (`probe_watch_root`)
- **Scenario:** the SSD's filesystem stops answering (MAC-12's FSEvents wedge, an SMB share whose server slept). `probe_once`'s own docstring names this: *"on Windows an isdir() against a dropped SMB mapping blocks on the network timeout"*.
- **Today:** every root check in the area is an in-process `isdir`. On a wedged mount they all block, so `RootGuard._loop` stops polling, `_on_root_absent` never fires, lanes are never paused, the tray keeps saying the drive is fine, and `state()` keeps returning the last good answer. The one machine-visible signal (`ROOT_ABSENT`) is exactly what cannot be produced.
- **Proposed:** give `RootGuard` a fourth answer, `ROOT_NOT_ANSWERING`, produced by running `probe_watch_root(local_root)` (already stdlib-only, out-of-process, 5 s cap, never raises) on the poll cadence *instead of* `isdir` when the previous `isdir` took longer than ~2 s, or unconditionally every Nth poll. Treat it like `absent` for lane pausing but with its own sentence ("the sync drive is not answering — reconnect it or restart"), and put it on the report so the grid shows it. It is the sentence MAC-12 already logs; it just never reaches anyone.
- **Effort:** M **Severity:** high **Confidence:** high
- **Related:** MAC-12, CR-91, `_watch_root_answers` (rclone_lane.py:3540).

### SYNC-3: on a Mac the relocation probe cannot match its own trashed files (CR-90 reaches the breaker)
- **Lens:** pitfall
- **Where:** `sync/rclone_lane.py:3086-3090` (`_count_relocations`), `:3008` (`_trashed_this_pass`, local `os.walk`), `:1039` (`list_remote_files`, SFTP)
- **Scenario:** a Mac editor holds `Interviewees/Matej Šimalčík/...`. An admin reorganises that folder on the NAS. Lane B trashes 60 proxies; the breaker runs the CR-44 relocation probe.
- **Today:** `_trashed_this_pass` reads paths off macOS's filesystem (NFD); `list_remote_files` reads them off the NAS (NFC). `rel in remote_paths` and `remote_files.get(name)` are exact string comparisons, so every path containing a diacritic scores as a deletion. The probe under-counts, the breaker trips, and the operator runbook's "a move should no longer reach you as an alarm" is false on every Mac. Same defect in the opposite direction: the CJK folders beside it match fine, which is what made CR-90 unreadable for a day.
- **Proposed:** normalise both sides with `unicodedata.normalize("NFC", ...)` at the comparison only (never for anything that opens/moves a file — the CR-90 rule). Three lines in `_count_relocations`, plus the same on the basename key. Add a companion test using the real NFC/NFD pair already committed in `dashboard/tests/test_unicode_paths.py`.
- **Effort:** S **Severity:** high **Confidence:** high
- **Related:** CR-90, CR-44, CR-47, `db.media_rel_key`.

### SYNC-4: an upload-only project can never be repathed, so lane A rebuilds the old NAS path forever
- **Lens:** pitfall
- **Where:** `sync/repath.py:194-196` (`folder = folders.get(slug); if folder is None: continue`), `sync/sequencer.py:1476`, `docs/UPLOAD_ONLY_TICK.md`
- **Scenario:** an editor is ticked upload-only for `2026/FF5/Animals` (CR-85). An admin renames or moves that project on the NAS.
- **Today:** `ProjectRepather` is deliberately stateless — the *local Syncthing folder* is its only record of where the project lives. An upload-only machine is never shared that folder ("no share", by design), so `folders.get(slug)` is always `None` and the project is silently skipped. The local directory stays at the old rel; the selection's new rel is what lane A runs, so lane A either uploads nothing (source dir missing → `"project dir not yet local"`, IDLE and green, rclone_lane.py:2655) or, if the old path is still selected under a different name, re-creates the abandoned path on the NAS. `copy` never deletes, so nothing ever cleans it up.
- **Proposed:** give the repather a second source of truth for upload-only slugs: the `.ccsync-project` marker already read by `read_project_slug` (rclone_lane.py:1782). Walk `Projects/` for markers, match slug → current rel, and repath on a mismatch through the same `_move_dir`. Failing that, at minimum report it: when an upload-only project's local dir is missing at the selection's rel but its slug's marker exists elsewhere, raise a named `sync_guard` alarm rather than reporting the lane idle.
- **Effort:** M **Severity:** high **Confidence:** med

### SYNC-5: a folder latched paused for missing ignores is invisible — lane C still reports green
- **Lens:** pitfall
- **Where:** `sync/syncthing_lane.py:652` (`elif len(paused_folders) == len(expected)`), `:664-668`, `sequencer.py:424` / `:1271` (`_ignores_unconfirmed`)
- **Scenario:** `set_ignores` times out on one folder (routine — `config_write_timeout` exists for exactly that). The sequencer latches the slug and every leak-recovery sweep skips it, correctly. The next turn's re-assert also fails, or the folder 404s in a way that keeps it latched.
- **Today:** that project's lane C carries nothing, indefinitely. `check_once` only reports `PAUSED` when **every** expected folder is paused; with 1 of 5 paused it falls through to the `else` and publishes `state=IDLE, queued=0, last_sync=now` — the exact "green while lane C does nothing" shape AUDIT_2 L-6 was written about. `_ignores_unconfirmed` is reported nowhere: grep confirms it never leaves sequencer.py, and the only trace is one DEBUG line ("stays paused -- its ignores never landed", sequencer.py:1277).
- **Proposed:** publish the latched set. `Sequencer` exposes `unconfirmed_slugs()`; `SyncthingLane` (or the reporter) turns a non-empty one into `state=error`/a `sync_guard.folders_unfiltered` field naming the projects, and the tray line says *"N project(s) are not sharing yet — waiting for their filter list"*. Cheap: both halves already exist, nothing new is computed.
- **Effort:** S **Severity:** high **Confidence:** high
- **Related:** AUDIT_2 L-3/L-6, B14, SYNC-8 (startup verification).

### SYNC-6: the shared/borrowed folder reconcile mkdirs into an absent local_root
- **Lens:** pitfall
- **Where:** `sync/shared_folders.py:269` (`Path(want_path).mkdir(parents=True)`), `sync/borrowed_folders.py:195` and `:260`, called from `sequencer.py:751` — **before** any root check
- **Scenario:** a Mac editor unplugs the SSD (or it is out at login). Within the root guard's 5 s poll, the sequencer's loop head runs `_reconcile_shared_folders()`.
- **Today:** `_clone_structure` checks `_local_root_is_present()` first (sequencer.py:1722) and both rclone lanes check it (rclone_lane.py:2617) — but the shared/borrowed reconcile does not. `mkdir(parents=True)` on `/Volumes/SAMDISK/Creators_Club/Assets/B-roll Archive` creates the whole chain on the **boot disk**, which is precisely the "ghost directory at /Volumes/<Name>" that `probe_root` (root_guard.py:392) exists to detect — and it then makes macOS mount the real drive as `/Volumes/SAMDISK 1`, i.e. `ROOT_MISPLACED`, permanently, until a human deletes the ghost. On first accept the folder is also *pointed* at that path.
- **Proposed:** both managers take the same `root_present_fn` the manifest cache takes (`manifest.py:200`) and return early from `reconcile()` when it is False; and `_accept`/`_repoint` refuse to `mkdir` a path whose local_root ancestor is not a directory. One guard, two files, no behaviour change when the drive is present.
- **Effort:** S **Severity:** high **Confidence:** high

### SYNC-7: no lane checks free disk space, though every other subsystem does
- **Lens:** safeguard
- **Where:** nothing in `sync/*`; compare `proxy_gen.py:1859`, `broll_vlm_sidecar.py:460`, `music_clap_sidecar.py:262`, `broll_server.py:819` (`_free_bytes_at`)
- **Scenario:** an editor ticks a big project; lane B pulls proxies onto a 1 TB laptop SSD that is at 40 GB free. `.ccsync-trash` (up to the 50 GB cap) is on the same volume.
- **Today:** rclone fails per file with an ENOSPC message; the lane goes red with a raw rclone string; `prune_trash` only runs *after a healthy lane B pass* (`_maybe_prune_trash`, rclone_lane.py:3170, reached only at the tail of `_run_once_locked`), so on a machine whose passes keep failing the 50 GB of recovery copies is never reclaimed. Nothing warns before the wall, and nothing tells the dashboard the machine is nearly full.
- **Proposed:** (a) one `shutil.disk_usage` per lane B pass, reported as `sync_guard.free_bytes`, with a grid chip under a floor; (b) below `lane_b_min_free_bytes` (default ~20 GB) lane B stands down in `paused` with `"not enough free space"` — the same shape as the breaker, so lanes A/C keep running and an editor can clear space; (c) `prune_trash` gains a `min_free_bytes` trigger so disk pressure prunes even when age/size have not.
- **Effort:** M **Severity:** high **Confidence:** high

### SYNC-8: the dashboard silently drops the Syncthing supervisor's incident section
- **Lens:** pitfall
- **Where:** `dashboard/src/ccsync_dashboard/api.py:4647-4660` (`SyncGuardIn` — no `syncthing_supervisor` field), `companion/.../sync/syncthing_supervisor.py:471` (`report()`), docs/SYNC_SAFETY.md §6
- **Today:** the companion sends `sync_guard.syncthing_supervisor` (`down_since`, `attempts`, `last_error`, `supervising`) and Pydantic's `extra="ignore"` throws it away. What turns the chip red is only lane C's own `state`, which SYNC-5 above shows can be green while the engine is fine but a folder is parked — and which is `error` for a genuinely down engine only via the unreachable path. The doc already flags this as unfixed.
- **Proposed:** add the model + a `machine_state` column, and surface "sync engine down for Nh, N restart attempts, last error X" on the fleet page. Dashboard-only change; every companion in the field already sends it.
- **Effort:** S **Severity:** med **Confidence:** high
- **Related:** SYNC-17.

### SYNC-9: a frozen manifest walk is indistinguishable from a machine that holds nothing new
- **Lens:** pitfall
- **Where:** `manifest.py:265` (`scan_local_manifest` — unbounded `os.walk`), `:269` (cache replaced only on success), `:220` (`start()` guards on `is not None`, not `is_alive()`)
- **Scenario:** CR-91's other half: `editor_media_project.reported_at` froze at 19:00:42 while light reports kept flowing.
- **Today:** `refresh_once` swallows every failure and simply keeps the old cache — correct for "the drive is out", wrong as a *permanent* silent state: there is no `scanned_at` stamp, nothing reports the cache's age, and a walk blocked in the kernel means the loop never reaches `_stop_event.wait`. The dashboard then diffs a snapshot that is hours or days old against a live NAS inventory and invents a backlog (the CR-90 shape, by a different cause). Separately, `start()`'s `is not None` guard is the anti-pattern `root_guard.start()` (root_guard.py:719) explicitly warns against — a stopped cache can never be restarted.
- **Proposed:** stamp `scanned_at` on every successful scan, report `manifest_age_seconds`, and have the dashboard mark presence data stale (and stop deriving a backlog from it) past ~3 refresh intervals. Add a watchdog: if `refresh_once` has not completed within 3 intervals, log a WARNING naming the project dir it was last walking. Change `start()` to `is_alive()`.
- **Effort:** M **Severity:** high **Confidence:** high
- **Related:** CR-91, CR-90.

### SYNC-10: a repath onto an existing target orphans a whole project directory, silently
- **Lens:** pitfall / user-error
- **Where:** `sync/repath.py:283-288` (`if dst.exists(): ... re-pointing the folder anyway`)
- **Scenario:** an admin moves a project on the NAS to a path the editor already has a stale copy at (a hand-made folder, a previous failed repath, an editor who reorganised in Explorer).
- **Today:** the old directory is left in place with a WARNING and the folder is re-pointed. That directory is now in no selection, so no lane ever touches it: lane B never syncs it, lane A never uploads it, the manifest counts its files as this machine's (inflating presence), and it consumes disk forever. Nothing ever reports a project directory that is not in the selection.
- **Proposed:** a "stray project dirs" scan on the orphan-scan cadence (`_maybe_scan_orphans` already runs every N passes and already exists as report-only, rclone_lane.py:2461): walk `Projects/` for `.ccsync-project` markers whose slug is not in the selection, report count + bytes + paths as `sync_guard.stray_projects`. Never delete — same posture as the `.partial` scan. Bonus: it is also the detector for SYNC-4 and for an editor who dragged a project folder in Explorer.
- **Effort:** M **Severity:** med **Confidence:** high

### SYNC-11: the file-move exclusion does not match a macOS path, so the moved file re-uploads
- **Lens:** pitfall
- **Where:** `file_moves.py:190-210` (`recent_excludes`), `sync/rclone_lane.py:2231-2246` + `:398` (`- /{escape_filter_pattern(rel)}`)
- **Scenario:** exactly `docs/FILE_MOVES.md`'s founding case — leso's card dump — but on the Mac it happened on.
- **Today:** the dashboard's `from_rel` is NFC; the editor's file on disk is NFD. The exclude rule is handed to rclone as a literal glob, and rclone matches the bytes it reads from the filesystem, so a path with any diacritic is not excluded. Lane A re-uploads it to the old NAS path — the exact failure the whole feature exists to stop — and nothing reports that the exclusion missed. `apply_move` itself survives (APFS lookups are normalisation-insensitive), which is what makes this look like it works.
- **Proposed:** emit both spellings from `recent_excludes` (`unicodedata.normalize("NFC"/"NFD", rel)`, deduped) — the exclude list is `-` rules, so an extra pattern that matches nothing is free. Same treatment for the `is_dir` case, and add a `/**` form: `- /Sub/Dir` alone is a directory-prune that is easy to get wrong.
- **Effort:** S **Severity:** med **Confidence:** med
- **Related:** CR-90, docs/FILE_MOVES.md.

### SYNC-12: "bounded" remote listings are not actually bounded
- **Lens:** pitfall
- **Where:** `sync/rclone_lane.py:762` (`_run_lsf`), `:989` (`_run_capture`) — both `subprocess.run(..., timeout=)`; contrast `:661` (`_end_probe`) which documents this trap verbatim
- **Today:** `subprocess.run`'s timeout kills the child and then sits in `communicate()` waiting for the pipes to close. On Windows an rclone that spawned anything inheriting the write handle — or a child stuck in an uninterruptible kernel wait — leaves that call blocked forever. `list_remote_files` runs inside `_run_lock` on the relocation path with a 600 s "cap" that can therefore be infinite, wedging the sequencer at the exact moment the breaker is deciding whether to stop lane B. `_end_probe` was written because the authors already know this; the knowledge did not reach these two helpers.
- **Proposed:** route both through the `Popen` + `wait(timeout)` + `kill` + `wait(timeout=1)` shape `_end_probe` uses, reading stdout on a daemon thread with the `abandoned` flag `_run_popen` already implements (rclone_lane.py:3280-3327).
- **Effort:** S **Severity:** med **Confidence:** med

### SYNC-13: the express lane has no duration bound and no abandoned-reader escape
- **Lens:** pitfall
- **Where:** `sync/rclone_lane.py:4125` (`proc.stderr.read()`), `:4133` (`proc.wait()`), `:1468` (`build_express_command` — no `--max-duration`)
- **Today:** `_express_spawn` reads stderr to EOF and then waits, both unbounded, with none of `_run_popen`'s bounded join / abandon logic. An express run that wedges holds `_express_run_lock` for the life of the process: every subsequent window loses the lock, requeues, and eventually gives up to the periodic pass (`EXPRESS_PENDING_MAX_SECONDS`) — so express dies permanently and silently, and the only symptom is that new clips take a full rotation to reach the NAS instead of ~10 s. `express_report()`'s counters simply stop advancing; nothing checks that they are stale.
- **Proposed:** give the express command a `--max-duration` (a generous multiple of the batch's byte total, or simply `project_rotation_seconds`) and reuse the bounded reader; report `express.last_run` age so a dead express lane is visible.
- **Effort:** S **Severity:** med **Confidence:** high

### SYNC-14: a renamed computer silently gets somebody else's plan (or none)
- **Lens:** user-error
- **Where:** `selection.py:31` (`_machine_name()` = `platform.node()`), `:214-217` (`?machine=`), `sequencer.py:754-762` (empty selection → `STATE_NO_SELECTION`)
- **Scenario:** an editor renames their PC (or macOS changes the `.local` name after a network change — leso's machine reports as `liaoshaoxuandeMacBook-Pro.local`).
- **Today:** the plan is keyed on the hostname; `machine_id` (`~/.ccsync/machine.json`) exists precisely because a rename must not lose identity, but the selection fetch does not send it. A renamed machine asks for a plan that does not exist, falls into the unassigned bucket or comes back empty, and the sequencer parks in `no selection (zero projects selected)` — sync stops completely, with a tray line that reads like the admin simply has not ticked anything. Nothing detects that this machine had a plan five minutes ago.
- **Proposed:** send `machine_id` alongside `?machine=`, and let the dashboard resolve by id first (the registry already stores it, per CLAUDE.md/v23). Until then, cheap companion-side guard: remember the last hostname that returned a non-empty selection in the selection cache, and when a fetch returns **empty** under a *different* hostname, keep the cached plan, log a WARNING, and raise a tray line — *"this computer's name changed; ask your admin to re-approve it"* — rather than treating it as an untick.
- **Effort:** M **Severity:** med **Confidence:** med
- **Related:** CR-91 (the machine-approval half), docs/MULTI_MACHINE_PLAN.md.

### SYNC-15: nothing aggregates the seven independent reasons this machine is not syncing
- **Lens:** safeguard
- **Where:** `sync/lane_guard.py:256` (breaker), `:674` (halt), `app.root_is_present`, `sequencer._state`, `sequencer._ignores_unconfirmed:424`, `syncthing_supervisor.lane_error:447`, `RcloneLane._stop_event:2627`
- **Today:** each latch has its own state, its own file and its own (or no) report field. `build_diagnostics()` (app.py:5266) is local, manual and clipboard-only. The fleet page has to infer "why is this machine doing nothing" from a lane state, which SYNC-1/5/9 all show can be wrong.
- **Proposed:** one derived, report-only field, `sync_guard.blocked` = the first non-empty of {fleet halt, local halt, root absent/not answering, licence park, no selection, breaker tripped, folders unfiltered, lane stalled}, with its reason string. Nothing new to compute — every value already exists in memory — and it becomes the single sentence the grid, the tray and the "why isn't it syncing" question all read. Rank the ordering so the *actionable* reason wins.
- **Effort:** M **Severity:** med **Confidence:** high

### SYNC-16: the trash prune can only run on the one code path that a sick machine never reaches
- **Lens:** pitfall
- **Where:** `sync/rclone_lane.py:2889` (`_maybe_prune_trash()` — last statement of a fully successful pass), `:2795` (stop mid-transfer returns first), `:2888` (a trip returns first), `lane_guard.py:603`
- **Today:** the retention policy is reachable only from the tail of a lane B pass that did not trip, was not stopped, and did not error. A machine that errors every pass (NAS unreachable, disk full, a filter file that will not validate) keeps up to 50 GB of recovery copies forever — and disk-full is precisely the state in which that matters. "Nothing is pruned while the breaker is tripped" is deliberate and right; "nothing is pruned while the lane is failing" is an accident of placement.
- **Proposed:** call `_maybe_prune_trash()` from the sequencer once per pass (fault-isolated, like `_check_remote_root`), keeping the breaker gate inside `prune_trash` where it belongs. Also: `prune_trash`'s size rule sorts by `mtime`, and `trash_entries` yields `0.0` when every `stat` fails (lane_guard.py:560-573) — such a batch sorts as the *oldest* and is deleted first, which for a batch created seconds ago is the wrong one. Fall back to parsing the `%Y%m%d-%H%M%S` directory name.
- **Effort:** S **Severity:** med **Confidence:** high

### SYNC-17: `--min-age` on lane B still round-trips a rewritten proxy through the trash
- **Lens:** pitfall
- **Where:** `sync/rclone_lane.py:1570-1577` (`--min-age`), `:3057-3067` (the CR-47 comment naming this as residue)
- **Today:** documented and accepted: a proxy rewritten on the NAS inside the min-age window is excluded from the source listing while the local twin is still on the destination side, so it is moved into `.ccsync-trash` and re-downloaded next pass. On a base-rig bulk re-render this is hundreds of files leaving the editor's project folder for a whole rotation — visible to the editor as clips going offline in Resolve mid-session, with the tray reporting a healthy pass.
- **Proposed:** not `--track-renames` (rightly deferred). Instead make it *visible and cheap to sit out*: when a pass trashes files whose exact rel path is still on the remote (a count `_count_relocations` already computes at line 3087), say so in the pass detail — *"12 proxies are being re-downloaded because the server rewrote them just now"* — and skip the `on_trash` toast for them. It removes the alarming half without touching the deletion behaviour.
- **Effort:** S **Severity:** low **Confidence:** high
- **Related:** CR-47 residue, sync-safety-7 (deferred, CR-66).

### SYNC-18: `_verify_startup_ignores` costs one blocking GET per project before the first byte
- **Lens:** pitfall
- **Where:** `sync/sequencer.py:938-995`, `syncthing_admin.py:288` (5 s read timeout)
- **Today:** at startup the sequencer serially GETs every selected folder's ignores before releasing anything. With a slow or busy Syncthing (config commit in flight — the documented reason `config_write_timeout` is 30 s), ten projects can be 50 s of blocked startup during which nothing syncs and the tray shows "starting up". It is correct to verify; it is serial and unbounded in aggregate.
- **Proposed:** cap the whole verification (e.g. 15 s wall clock); anything unverified when the budget expires goes through the existing `_latch_unverified` path (sequencer.py:997), which is already the correct fail-closed behaviour and is already used for the stop-event case. No new safety reasoning needed — just a second reason to take the same exit.
- **Effort:** S **Severity:** low **Confidence:** high

## Cross-cutting notes
- **Dashboard:** `SyncGuardIn` (api.py:4647) drops `syncthing_supervisor` (SYNC-8) and would need one column each for the new fields proposed in SYNC-1/5/7/9/10/15. Whoever owns the fleet page should know that `state=idle` and `state=syncing` are both currently reachable while a machine syncs nothing.
- **Dashboard / multi-machine:** SYNC-14 needs the selection endpoint to resolve a plan by `machine_id`, not hostname. That is the same registry CR-91's approval flow touches.
- **CR-90 follow-through:** the NFC normaliser was applied at the dashboard's two write chokepoints only. Two more comparison sites in the companion still compare raw bytes across the Mac/NAS boundary (SYNC-3, SYNC-11); it is worth a repo-wide sweep for `rel in`/`== rel_path` comparisons that cross that boundary.
- **Resolve/app area:** `app.py`'s root-guard callbacks (`_on_root_absent`, app.py:1540) are the only thing that pauses lanes for a missing drive; SYNC-2 means they can fail to fire at all. The `_unfinished_before_pause` docstring already knows about CR-91's fake `syncing`.
