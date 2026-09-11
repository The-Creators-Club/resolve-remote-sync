# regression - did the 2026-09-11 fix pass (18e69f3) actually close the 131 findings it claims?

Files read (with approximate coverage): `docs/bug-hunt-2026-09-11.md` (the ten
highs in full; every territory section), `docs/bug-hunt-2026-09-11/tally.txt` and
`verdicts.txt` (all 131 ids and all 72 verdicts), `docs/bug-hunt-2026-09-11/ledger/*.md`
(18 builder reports), `KNOWN_BUGS.md` CR-233..CR-248, and the fix site of every id
via `grep -rn <id>`. Depth-read for the eleven final-severity highs and the 41
verified mediums; the 80 lows sampled at about 53 of 80. Code read in depth:
`dashboard/src/ccsync_dashboard/{published_docs,help,ui,alerts,api,db,mount_status,links,release_feed,jobs}.py`,
`nas/synology.py`, `static/sw.js`; `tools/{ship.ps1,ship_gates.ps1}`;
`.github/workflows/ci.yml`; `server/install_dashboard_app.py`;
`broll/web/app/client_folders.py`; `music/web/musicweb/{ingest_batches,config}.py`;
`ytdl/web/ytdlweb/{db,routes_fleet}.py`, `ytdl/web/static/app.js`;
`companion/src/ccsync_companion/{app,file_moves,tray,tray_native,supervisor,broll_ingest,music_ingest,timeline_cards_role,sidecar_tools}.py`,
`sync/{sequencer,rclone_lane,lane_guard}.py`; `onboarding/steps.py`; plus the
`test_bug_hunt_2026_09_11_*.py` files beside each. A mechanical sweep ran every
one of the 131 ids against every non-doc file in the tree, to find ids claimed
fixed that no code cites.

Tests run:
`cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_help_page.py -q` -> 38 passed, 1 skipped;
`cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_dash_api_jobs.py tests/test_bug_hunt_2026_09_11_dash_collector_alerts.py -q` -> 40 passed;
`cd companion; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_comp_resolve.py -q` -> 16 passed;
all eight `installer/tests/*.ps1` under `powershell -NoProfile` -> pass;
ad-hoc venv snippets for `db.fail_job` after a cancel, `music/web`'s
`share_root_ready`, and `file_moves.cmp_key` vs `os.path.normcase` on NFC/NFD.

## Findings

### regression-1 - res-fleet-2: the per-cycle mount probe cannot see the failure it was written for
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/mount_status.py:102-121` (`recheck`,
  `probe = is_dir or os.path.isdir`), with the recorded roots at
  `dashboard/src/ccsync_dashboard/broll.py:538` and `music.py:450`
- What: the whole verdict turns on `os.path.isdir(root)`, and the recorded roots
  ARE the bind-mount targets (`BROLL_DATA_ROOT=/broll-data`,
  `MUSIC_DATA_ROOT=/music-data`). A bind mount that has gone away leaves its
  mount-point directory behind inside the container, so `isdir` answers True and
  `recheck` never downgrades - and `_init_broll_storage` / `_init_music_storage`
  `mkdir(parents=True, exist_ok=True)` that same root at boot, so after any boot
  the directory provably exists on the container's own layer whatever the host
  does.
- Failure scenario: the NAS export behind `<tree>/Assets/B-roll Archive` flaps at
  03:00 - the finding's own scenario. `/broll-data` is still a directory,
  `recheck` returns `{}`, `mount_status` keeps `("mounted", "serving /broll")`,
  `/api/v1/health` reports all four mounted, the topbar still offers B-ROLL,
  every request under it serves an empty library, and PROBLEMS THE SERVER FOUND
  says nothing. Identical outcome to 40f931a.
- Evidence: read `recheck` and all four `record_root` call sites;
  `broll/web/app/config.py:12-18` shows `get_data_root()` is the env var
  verbatim. The same fix pass states the mechanism twice elsewhere -
  `ytdl/web/ytdlweb/routes_api.py:1440-1447` ("a mount that has gone away leaves
  its mount POINT behind on the container's own filesystem") and
  `alerts.py:1801-1805` ("A share that failed to mount presents as an EMPTY
  directory, not as an error"), which is why `_check_nas_tree` probes
  `path.iterdir()`. The regression test
  `test_a_mount_whose_root_goes_away_stops_reading_as_mounted` injects
  `lambda _p: False`, so it passes without ever exercising the real shape.
- Ledger: CR-241 does not fix res-fleet-2
- Suggested fix: probe what the mount actually needs and keep it cheap -
  `any(os.scandir(root))` (the `_check_nas_tree` test) or an `os.path.exists` on
  the one artefact the mount serves (`broll.db`, `music.db`, the cards checkout
  marker) - with the OSError path still "cannot tell".

### regression-2 - dash-collector-alerts-1: the new quiet path names the machine, which silences the catch-all "not syncing and we cannot say why" alert
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/alerts.py:1941` (`_check_out_of_tree`,
  `if ctx.name(who) not in ctx.open_alert_subjects("out_of_tree"): continue`),
  against `alerts.py:1122` (`Ctx.name`) and `alerts.py:2909`
  (`_check_red_unexplained`)
- What: the fix spells "say nothing about a subject nothing was ever said about"
  with `ctx.name(who)`, which is not a predicate - it MUTATES, adding the machine
  to `ctx.named`. At 40f931a the `continue` sat one line ABOVE `who = ctx.name(who)`,
  so a skipped machine was never named. `_check_red_unexplained` is the last kind
  in `ALERT_KINDS` (`out_of_tree` at :2993, `red_unexplained` at :3067) and exists
  only for machines no other check named.
- Failure scenario: a machine reports `resolve_health.out_of_tree = 40` with a
  personal (non-tree) project open - the exact CR-232 case - and its lanes have
  been RED for over `RED_UNEXPLAINED_SECONDS`. `out_of_tree` correctly emits
  nothing but has already named the machine, so `_check_red_unexplained` skips
  it. The fleet's one "green while dead" backstop stays silent: the editor is not
  syncing and nobody is told, by either kind.
- Evidence: `git show 40f931a:.../alerts.py` lines 1779-1781 have `continue`
  before `who = ctx.name(who)`; HEAD calls `ctx.name(who)` inside the membership
  test. `Ctx.name` is `self.named.add(subject); return subject`.
  `_check_red_unexplained` filters on `who in ctx.named`. The regression test
  (`tests/test_bug_hunt_2026_09_11_dash_collector_alerts.py:138`) never puts the
  machine in `health.RED`, so it cannot see this.
- Ledger: CR-241 (dash-collector-alerts-1 / res-fleet-3) opens a neighbour
- Suggested fix: ask the question without naming - test the raw `_who(e)` against
  `ctx.open_alert_subjects("out_of_tree")` before any `ctx.name()`, and name only
  on the paths that emit a finding (the quiet branch should still name, since it
  holds an open row).

### regression-3 - dash-api-2: a cancelled job the holder fails as retryable becomes an immortal invisible `queued` row
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:9089` (`queued_jobs`, new
  `AND cancel_requested_at IS NULL`) and `:9306` (`claim_job`, same), against
  `fail_job` at `:9444-9475`
- What: the fix closed `expire_leases` (a cancelled lease now goes `failed`) and
  added two belts that HIDE any `queued` row carrying `cancel_requested_at`. But
  `fail_job` still re-queues a cancelled row when the holder posts
  `retryable=True`, and nothing reaps it: `expire_leases` skips it (no lease),
  `queued_jobs` and `claim_job` refuse it, `prune_jobs` only drops finished rows.
- Failure scenario: an admin clicks CANCEL on a running proxy job; within the
  same report interval (up to 30 s, before `commands.jobs.cancel` is delivered)
  the companion posts an ordinary retryable failure - a transient ffmpeg error,
  the "a path this machine cannot place is retryable ELSEWHERE" branch
  (`jobs_runner.py:895,944,1022`), or a fleet halt handing the job back. The row
  becomes `state=queued, cancel_requested_at=<set>` and is permanent: never
  offered, never claimable, never terminal. `queue_depth.queued >= 1` for ever,
  so every job-capable companion stays at the base poll cadence instead of
  backing off, `oldest_age_s` grows without bound, and
  `GET /api/v1/jobs/{id}/why` answers `schedulable: true` with a ranked best
  machine for a job the offer path can never see - the exact "a scheduler that
  quietly assigns nothing" shape `why` exists to tell apart. A second CANCEL
  click is the only cure and nothing suggests one.
- Evidence: run against the dashboard venv with the real `db` module -
  `claim True / cancel -> requested / fail -> queued / state queued
  cancel_requested_at set / queued_jobs [] / claim_next None / expire [] /
  depth {'queued': 1, 'oldest_age_s': 0.0}`. `git show 40f931a:...db.py` confirms
  both guards are new; before them the row was re-offered rather than wedged.
  The new test only exercises the `expire_leases` path.
- Ledger: CR-239 does not fully fix dash-api-2
- Suggested fix: give `fail_job` the rule `expire_leases` was given - a row with
  `cancel_requested_at` set goes to `JOB_FAILED` (`JOB_CANCELLED_ERROR`)
  regardless of `retryable` - or add a sweep that fails any `queued` row carrying
  the column.

### regression-4 - comp-sync-7: the new stale-subpath gate is on the shared lane object, so CONSOLIDATE's proxy pull is silently dropped
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/rclone_lane.py:3384` (the gate in
  `_run_once_locked`, i.e. every `run_once` caller), wired at
  `companion/src/ccsync_companion/sync/sequencer.py:439`, tripped from
  `companion/src/ccsync_companion/app.py:3814`
- What: the gate is a property of the LANE, not of the sequencer's own passes,
  and it sits inside `_run_once_locked`, below `run_once`'s `_run_lock`.
  `app._consolidate_upload_phase` calls `self._lane_b.run_once(subpath)` on the
  same object the sequencer holds (`app.py:2235` and `app.py:1587` prove one
  object). Worse, `_lane_b_subpath` is STICKY: `sequencer.py:2011` sets it once
  per turn and nothing clears it when the turn ends, so between turns it still
  names the last project the rotation visited.
- Failure scenario: an editor runs FIX ALL / consolidate on project X while the
  last rotation turn was on project Y (the ordinary case, not a race).
  `_subpath_is_current("X")` is False, and the consolidate's lane B pass returns
  `_stand_down_status("skipped a queued pass: the rotation had moved on")`. The
  progress UI has already published "Downloading proxies from the server...", so
  the editor's consolidated project ends with no proxies, and the only trace is a
  `log.warning` about a rotation that moved on.
- Evidence: read `run_once`/`_run_once_locked` (rclone_lane.py:3331-3396) - the
  gate is after the lock and applies to every caller; `_subpath_is_current`
  (sequencer.py:2104-2117) is `current is None or str(current) == str(subpath)`;
  `grep -n "_lane_b_subpath = " sequencer.py` -> one site, line 2011.
  `app.py:8570`'s `lane.run_once()` passes no subpath and is unaffected. Neither
  new test drives lane B from outside the sequencer.
- Ledger: CR-234 does not fix comp-sync-7 (it fixes the thread leak and opens
  this neighbour)
- Suggested fix: scope the check to the sequencer's own passes - a per-run token
  (`run_once(..., expect_subpath_current=True)`) set only by
  `Sequencer._run_lane` - or clear `_lane_b_subpath` when the turn ends.

### regression-5 - comp-sync-11: the twin the fix's own comment names, `CompanionApp._relink_moved`, was never converted to `cmp_key`
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:7846`, `:7851`, `:7857`; the fix
  is `companion/src/ccsync_companion/file_moves.py:143-150`
- What: CR-234 routed `file_moves.relink_moved` through a new PUBLIC `cmp_key`
  (NFC + case fold) and its comment says "CompanionApp._relink_moved (its twin)
  ... Anything outside this module that compares two paths must come through
  here". `app._relink_moved` still compares with a bare
  `os.path.normcase(os.path.normpath(...))` and still takes the folder tail with
  `os.path.relpath` on the raw strings. `file_moves.relink_moved` has exactly one
  caller (`sequencer._relink_moved_project`, the SYNC-102 project-directory
  path); the FILE MOVE feature - `_apply_file_moves`, `_relink_pending_moves` and
  the "RELINK IT" dialog - all go through the unfixed twin.
  `grep -rn cmp_key companion/src` outside `file_moves.py` returns nothing.
- Failure scenario: the hunter's exact scenario. An admin moves a clip whose name
  carries a diacritic through the project page; the Mac moves its copy,
  `_relink_moved` walks the media pool, Resolve answers NFD, `old_local` is the
  dashboard's NFC, no clip matches, `matched=False`, the ledger keeps
  `relink_pending` for the whole 30-day window, the clip stays Media Offline, and
  RELINK IT answers "Nothing in this project pointed at the old location."
- Evidence: read both functions; `grep -n normcase app.py` -> only 7846/7851.
  From the companion venv:
  `os.path.normcase(os.path.normpath(nfc)) == ...(nfd)` -> False,
  `cmp_key(nfc) == cmp_key(nfd)` -> True. Both new regression tests call
  `file_moves.relink_moved` only.
- Ledger: CR-234 does not fix comp-sync-11
- Suggested fix: replace both comparisons in `app._relink_moved` with
  `file_moves.cmp_key` and take the folder tail the way the module twin now does,
  or delete `_relink_moved` and delegate to `file_moves.relink_moved`.

### regression-6 - comp-sync-12: the new case-only rename skips the proxy siblings every other move takes with it
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/file_moves.py:305-312` against `:324`
- What: the ordinary move arm calls `move_proxy_siblings(src, dest)` after
  `src.replace(dest)` and reports "N proxy file(s) with it"; the crash-resume arm
  calls it too. The new case-only arm calls `_rename_case_only(src, dest)` and
  returns without ever touching `<parent>/Proxy/`.
- Failure scenario: an admin fixes `clip.mov` -> `Clip.mov` through the project
  page. The dashboard renames the original AND its proxy on the NAS
  (`docs/FILE_MOVES.md`: "the dashboard renames it (proxies with it)"). The
  editor now has `Clip.mov` beside `Proxy/clip.mov`: lane B's sync sees
  `Proxy/Clip.mov` as absent locally and `Proxy/clip.mov` as extraneous, so it
  re-downloads the proxy and moves the old-spelled one into `.ccsync-trash` -
  which is also charged to the lane B breaker's deletion account. Before the fix
  nothing was renamed at all, so the pair was at least consistent.
- Evidence: read `apply_move` 296-331 - `move_proxy_siblings` at :289 (resume)
  and :325 (ordinary) and nowhere between 305 and 312.
  `test_a_case_only_rename_is_actually_applied` asserts only on the original.
- Ledger: CR-234 does not fix comp-sync-12 (the rename lands; its proxy does not
  follow)
- Suggested fix: call `move_proxy_siblings` in the case-only arm too, through the
  same staging two-step (the sibling stems fold together as well), and fold the
  count into the detail.

### regression-7 - comp-ui-1: a recoverable Explorer-restart re-add failure now kills the tray refresh and pulse loops for the life of the process
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray.py:1020`
  (`icon._ccsync_stop = True` in `_report_windows_icon_failure`), reached from
  `companion/src/ccsync_companion/tray_native.py:1157-1166`
- What: `_announce_failure` has two callers - the first-registration failure in
  `run()` (where the pump is dead and stopping the loops is right) and the
  Explorer-restart re-add failure (where the pump thread is alive and a later
  `TaskbarCreated` can still succeed). Both set `_ccsync_stop`, and
  `_refresh_loop` / `_pulse_loop` are `while not getattr(icon, "_ccsync_stop", False)`
  (tray.py:4869, :4922) with nothing to restart them.
- Failure scenario: Explorer crashes and restarts; the re-add fails against an
  Explorer that has only just come back. Both loops exit. The next
  `TaskbarCreated` re-adds the icon successfully - it is visible, clickable,
  toasts flow - but nothing ever assigns `icon.menu`, `icon.title` or `icon.icon`
  again (tray.py:4898-4901). The editor has a permanently frozen tray: last
  hour's tooltip, last hour's menu, no colour change when the breaker trips.
  Before CR-235 that sequence recovered completely.
- Evidence: read `_report_windows_icon_failure` (tray.py:993-1038), both
  `_announce_failure` call sites (tray_native.py:864, :1165) and both loops;
  `_ccsync_stop` is assigned in two places and never cleared.
- Ledger: CR-235 does not fix comp-ui-1 (it closes the first-registration case
  and opens this one)
- Suggested fix: pass a `recoverable` flag - set `_ccsync_stop` only on `run()`'s
  arm - or clear it and restart the loops when a later `_add_icon()` succeeds.

### regression-8 - comp-resolve-4: the cards watchdog still never recovers a role that lost ONE of its two loops
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/timeline_cards_role.py:756-763`
  (`supervise_now`) against `:952-955` (`health`) and `:718-722`
  (`_note_loop_end`)
- What: `supervise_now` now tests `any(t.is_alive() for t in self._threads)`,
  which recovers the both-dead case. `health()` returns `HEALTH_STOPPED` as soon
  as `_loop_error` is set, and `_note_loop_end` sets it on the FIRST loop death -
  so with the push loop dead and the pull loop alive, health says stopped for
  ever while `supervise_now` answers True and never calls
  `_clear_dead`/`_start_guarded`. The "the REPORT is honest and the RECOVERY is
  not" asymmetry the finding is about is narrowed, not removed.
- Failure scenario: `client.push_loop` raises on a Resolve state the other repo's
  client cannot encode while `pull_loop` keeps long-polling. The fleet grid shows
  the machine STOPPED with that sentence, the 60 s watchdog answers "running"
  every minute, and only a companion restart brings the phone page back.
- Evidence: read the three functions;
  `companion/tests/test_bug_hunt_2026_09_11_comp_resolve.py` (16 passed) only
  exercises both threads dead.
- Ledger: CR-236 does not fully fix comp-resolve-4
- Suggested fix: make the liveness test `all(t.is_alive() ...) and not self._loop_error`,
  so a single dead loop takes the role down through `_clear_dead()` and restarts
  it under the same ceiling.

### regression-9 - comp-broll-music-2: a staged-but-never-run drop is now immortal - no sweep, no button, unbounded staging disk
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:3134-3145`
  (`prune_staging`'s new `if not ended: continue`)
- What: the `ended_at` -> `at` fallback was replaced by an unconditional skip at
  every retention value, which correctly saves the mid-PUT drop. But `ended_at`
  is only ever written by `_note_staging_ended`, called from `_maybe_finish` and
  `_lease_lost` - i.e. only for a drop that was RUN. `prepare()` mints a fresh
  `uuid4().hex[:16]` staging directory per drop, so an abandoned drop has no path
  to deletion at all: the 7-day retention skips it, the tray's CLEAR FINISHED
  STAGING skips it, and its bytes go on being counted in `staging_report`.
- Failure scenario: an editor drags a 200 GB shoot into the ingest panel, the
  uploads finish, they close the tab without pressing Run. The staging folder
  under the tree stays for ever; a week later they do it again. Nothing in the
  product can free it except deleting the directory by hand, and
  `sync_guard.ingest_staging.bytes` grows monotonically.
- Evidence: read `prune_staging`, `_note_staging_ended` (`:3041`, called only
  from `:1258`, `:2789`, `:2808`) and `prepare`. No other caller unlinks a
  staging directory.
- Ledger: CR-238 does not fully fix comp-broll-music-2
- Suggested fix: keep the skip only while the drop is live (any item
  `waiting`/`uploading`, or `at` within a short grace) and sweep an unrun drop
  whose last item activity is older than the retention; or give the panel an
  explicit "discard this drop" that stamps `ended_at`.

### regression-10 - music-5: `ORDER BY id DESC` now samples the rows least likely to be on disk, so a live drop refuses itself from item ~51
- Severity: medium
- Confidence: CONFIRMED
- Where: `music/web/musicweb/config.py:505-515` (`share_root_ready`), reached
  from `ingest_batches.allocate_name:251`
- What: the probe was flipped from the oldest 50 `tracks` rows to the newest 50.
  But a fleet `result` writes the `tracks` row BEFORE the companion uploads the
  audio (`write_item_result`'s own docstring: "The audio itself is still on the
  editor's machine at this point"), and `tracks` has no status column to exclude
  unlanded rows. Once a drop has written 50 rows whose files have not landed, the
  newest-50 sample is entirely files that do not exist - and the positive cache
  is only 5 s (`_READY_CACHE_SECONDS`), so it does not paper over it.
- Failure scenario: an editor drops a 120-track library import (`MAX_BATCH_ITEMS`
  is 500). Items 1-50 get names and rows; uploads trail behind on a slow uplink.
  `allocate_name` for item 51 stats the 50 newest rel_paths - this batch's, none
  on disk yet - and raises `HTTPException(503, 'the music library at
  /music-share is there but empty ...')`. With music-2's new retry that burns the
  6-try / 20-minute budget per track and then fails it permanently, while the
  message points the operator at a mount that is fine.
- Evidence: a scratchpad script in the `music/web` venv built a `tracks` table
  with 300 rows whose files exist plus 50 newer rows whose files do not ->
  `share_root_ready` returned `(False, 'the music library at ... is there but
  empty: none of the indexed tracks are visible ...')`.
  `test_a_share_with_none_of_the_newest_tracks_is_still_refused` pins exactly
  this input as correct behaviour.
- Ledger: CR-246 does not fix music-5 (it moves the false refusal from an old
  library to a live drop)
- Suggested fix: sample from both ends (25 newest + 25 oldest), or exclude rows
  whose `rel_path` is an unlanded `ingest_items` row.

### regression-11 - comp-ytdl-jobs-3: the dashboard half was never built, so the finding's central symptom stands
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:7397-7445` (the only dashboard
  site); nothing in `alerts.py`, `ui.py`, `collector.py` or `jobs.py`
- What: the companion half landed (cause carried into `message`,
  `consecutive_failures`, a WARNING repeat, a tray/Settings line, the new
  `sync_guard.ytdlp.sidecar` block). On the dashboard only the pydantic model
  `YtdlpSidecarIn` was added; the value is swallowed whole into the `ytdlp:` meta
  JSON by `_store_ytdlp_state` and NO READER EXISTS - no `ALERT_KINDS` row, no
  grid or Settings render, no change to `GET /api/v1/jobs/{id}/why`. The hunt's
  fix list asked in as many words for "the dashboard model, column and
  `ALERT_KINDS` row (registered WITH its writer, per CLAUDE.md)".
- Failure scenario: a Mac editor's sidecar ffmpeg install fails on the SSL CA
  problem. `capabilities.ffmpeg=false`; the admin queues a `proxy-480p` job,
  `why` answers `no_capable_machine`, and the fleet grid and Settings -> JOBS
  still say nothing about why - exactly the "reads as *this machine was never set
  up*" the finding names. The only place the cause appears is that editor's own
  tray, which is the audience the finding said it already had.
- Evidence: `grep -rn comp-ytdl-jobs-3 dashboard/` -> two comment lines in
  `api.py` and nothing else; `grep -rn sidecar alerts.py ui.py` -> only the
  unrelated PO-token and Tailscale sidecars. The builder's own ledger says "a
  dashboard that does not read it is unchanged".
- Ledger: CR-237 does not fix comp-ytdl-jobs-3 (companion half only)
- Suggested fix: add an `ALERT_KINDS` row with its writer, reading
  `ytdlp.sidecar.ok/cause/consecutive_failures` off the stored meta blob, and
  render the cause beside `cap_ffmpeg` on the jobs machine list and in `why`'s
  `no_capable_machine` explanation.

### regression-12 - res-companion-3 is claimed fixed and there is no fix anywhere in the tree
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/supervisor.py:136-143` (the unchanged
  stand-down), window at `companion/src/ccsync_companion/upgrade.py:1753-1768`;
  claim at `KNOWN_BUGS.md:16368-16376`
- What: the finding asked `supervisor.main` to repair the one state only an
  outside process can repair - marker names our supervised pid,
  `ccsync-companion.exe` missing, `<exe>.old` present - by renaming back and
  relaunching. `decide()` still returns "the companion exe is no longer on disk:
  nothing to relaunch" and `supervisor.py` never mentions `.old`.
- Failure scenario: a self-upgrade is interrupted between the two `os.replace`
  calls. There is no `ccsync-companion.exe`; the supervisor, the one awake
  process outside it, logs "nothing to relaunch" and exits; the Run key points at
  a missing name and every in-companion recovery lives inside a companion that
  cannot start. The machine syncs nothing until a human renames the file.
- Evidence: the whole-tree sweep of all 131 ids found res-companion-3 to be the
  ONLY id with zero citations in any non-doc file; it is also absent from all 18
  ledger files and from KNOWN_BUGS.md, while `KNOWN_BUGS.md:16372` says "131
  distinct findings ... 0 refuted", "each fix citing its finding id at the code
  site" and "every finding with a regression test that fails at 40f931a".
- Ledger: no CR entry fixes res-companion-3
- Suggested fix: implement the guarded restore in `supervisor.main` (tightly
  guarded and loudly logged - `installer/windows_upgrade.ps1` swaps the same
  paths), or record it in KNOWN_BUGS.md as accepted-and-not-fixed so the "all 131
  fixed" claim stays truthful.

### regression-13 - CR-242b/CR-242c cite the wrong finding ids, and dash-release-jobs-5 is unledgered while dash-release-jobs-3's real fix is uncredited
- Severity: low
- Confidence: CONFIRMED
- Where: `KNOWN_BUGS.md:18710` (CR-242b, labelled `dash-release-jobs-3`),
  `KNOWN_BUGS.md:18723` (CR-242c, labelled `dash-release-jobs-4`),
  `dashboard/src/ccsync_dashboard/release_feed.py:342` and `:1264` (the same wrong
  ids in the code comments), `docs/bug-hunt-2026-09-11/ledger/dash-release-jobs.md:33,44,105-108`
- What: per `tally.txt`, -3 is the per-kind fleet cap race, -4 the `.sig` URL
  concatenation, -5 the `FeedPoller.start()/stop()` idempotence. CR-242b
  describes -4's defect under -3's id and CR-242c describes -5's under -4's, so
  the ledger is shifted by one across two entries: -5 appears nowhere, and -3's
  real fix (`db.claim_job`'s correlated `COUNT(*)`, `db.py:9293-9313`, correctly
  cited there and wired from `api.py:10327`) has no CR entry. The ledger's "Owner
  decisions" line still says dash-release-jobs-3 "is not fixed here - the
  per-kind fleet cap is advisory", which was true when written and is not now.
- Failure scenario: anyone auditing by id - this hunt, the next one, the shipping
  note - reads CR-242b as "the fleet cap race is fixed", cannot find -5 at all,
  and believes the cap race is open. All three fixes exist, so this costs nothing
  today and costs a re-hunt the first time one of them regresses.
- Evidence: `grep -an "^### CR-242" KNOWN_BUGS.md` against
  `docs/bug-hunt-2026-09-11/tally.txt` and `docs/bug-hunt-2026-09-11.md:1524-1556`;
  `grep -rn "dash-release-jobs-" --include=*.py .` has no `-5` hit and two `-3`
  hits for two different defects.
- Ledger: CR-242b / CR-242c mislabel their findings
- Suggested fix: re-label the two CR entries and the two code comments to -4 and
  -5, add the missing one-line CR for dash-release-jobs-3's `claim_job` change,
  and correct the "Owner decisions" line.

### regression-14 - broll-2: the `try/except` that protects the public share door catches `sqlite3.Error` only
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/app/client_folders.py:275-277` (`get_shares_db`), against
  `:154` (`ensure_schema`'s `path.parent.mkdir(parents=True, exist_ok=True)`)
- What: the docstring says "a sqlite failure HERE is not allowed to take the
  public share door out", and the handler catches `sqlite3.Error`.
  `ensure_schema`'s first act is a `mkdir` on the data root, which raises
  `OSError` (`PermissionError`, `FileNotFoundError`, "Read-only file system"),
  and so does `sqlite3.connect` on a path whose parent cannot be traversed.
- Failure scenario: the dataset holding `BROLL_DATA_ROOT` is unmounted or
  remounted read-only. Every `/broll/share/<token>/...` request - the client link
  an editor has already sent a customer - 500s with a traceback instead of the
  routes answering on their own merits, which is exactly what the handler was
  added to prevent. (The migration half of broll-2 is sound: `BEGIN IMMEDIATE`,
  `PRAGMA table_info` instead of `user_version`, and an idempotent backfill.)
- Evidence: read `get_shares_db` and `ensure_schema` at HEAD; `mkdir` and
  `sqlite3.connect` are outside any handler and `OSError` is not a subclass of
  `sqlite3.Error`.
- Ledger: CR-245 does not fully fix broll-2
- Suggested fix: `except (sqlite3.Error, OSError)` - the deliberately fatal
  "newer user_version" `RuntimeError` stays uncaught either way.

### regression-15 - comp-sync-7: the abandoned-lane-B latch is set outside the lock that its only clearer takes
- Severity: low
- Confidence: CONFIRMED (mechanism; the window is narrow)
- Where: `companion/src/ccsync_companion/sync/sequencer.py:2087-2094`
- What: `if thread.is_alive():` then `with self._lock: self._lane_b_abandoned = subpath`.
  The only clearer is `_clear_lane_b_abandoned()` in the lane B thread's own
  `finally`. If that thread completes between the `is_alive()` read and the lock
  acquisition, it clears a latch not yet set, and the main thread then sets it
  with no thread left to run the `finally`.
- Failure scenario: the wedge clears in exactly that window. Every later project
  turn takes the `run_b = False` arm, lane B never runs again for the life of the
  process, and the tray reads "stalled on <subpath>: waiting for an earlier pass
  to end" about a pass that ended. Only a restart recovers - and lane B is the
  proxy download, which editors notice last.
- Evidence: read `_run_lanes_a_and_b` (2065-2100) and `_clear_lane_b_abandoned`
  (2119-2124); no re-check of liveness under the lock and no other clearer.
- Ledger: CR-234 does not fully fix comp-sync-7 (residual)
- Suggested fix: re-check liveness under the lock
  (`with self._lock: if thread.is_alive(): ...`), or clear the latch defensively
  at the top of a turn when the recorded thread is no longer alive.

### regression-16 - comp-ui-1: the Explorer-restart re-add inherited the new backoff and blocks the pump for ~15.5 s, against its own comment
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray_native.py:1039`
  (`attempts = _NIM_ADD_RETRIES if attempts is None ...`, then
  `delays = _nim_add_delays(attempts)`), called with no argument at `:1157`
- What: the comment at `:318-324` states "The Explorer-restart re-add keeps the
  short schedule; it runs on the pump thread, where a two-minute sleep would
  freeze the tray." Only the ATTEMPT COUNT stayed short - the delays are now
  `_nim_add_delays(6)` = `[0.5, 1, 2, 4, 8, 15]`, so the re-add sleeps
  0.5+1+2+4+8 = 15.5 s inside the `TaskbarCreated` WndProc, against 3.0 s before.
- Failure scenario: Explorer restarts and the first attempts fail. The message
  pump is blocked inside the window procedure for ~15 s: queued clicks,
  `WM_CCSYNC_TRAY` callbacks and any broadcast sit unprocessed, and Windows can
  mark the window as not responding. The documented invariant is violated by a
  fifth of the amount it names, silently.
- Evidence: read `_nim_add_delays` (326-336), `_add_icon`'s default binding
  (:1039) and the re-add call (:1157); the last entry is consumed by `break`.
- Ledger: CR-235 does not fully fix comp-ui-1 (residual; the code contradicts its
  own comment)
- Suggested fix: give `_add_icon` a `delays` parameter and have the re-add path
  use the flat `_NIM_ADD_RETRY_DELAY` schedule the comment describes.

### regression-17 - res-companion-1: the new `applying` intent row is `relink_pending=True` before the file has moved
- Severity: low
- Confidence: CONFIRMED (mechanism; the window is narrow)
- Where: `companion/src/ccsync_companion/file_moves.py:320-321` (`record_intent`
  -> `record(..., relink_pending=True)`), `:519-527` (`pending_relinks`),
  `:333-408` (`relink_moved`), consumed at `companion/src/ccsync_companion/app.py:7769`
- What: the intent row is written before the first filesystem call and carries
  `relink_pending=True` plus both paths. `pending_relinks()` selects on
  `relink_pending and old_local` with no state filter, and `relink_moved`
  repoints every media-pool clip found at `old_local` to `new_local` without ever
  checking that anything exists there. Separately `recent_excludes:603` treats
  `STATE_APPLYING` as unresolved with no cap, so such a row holds its lane-A
  exclusion open indefinitely (unlike `retryable`, which ages out to `blocked`).
- Failure scenario: the companion is killed (the CR-93 shape, or a
  `Stop-Process`) between the intent write and `src.replace(dest)`. On restart
  the editor opens the project, `_rerun_pending_relinks` matches the clips still
  at the old path and `replace_clip`s them to `new_local`, where nothing is: the
  clips go offline, and the old path is also excluded from lane A for as long as
  the row survives.
- Evidence: `pending_relinks` has no `state` test; `relink_moved` has no
  `os.path.exists(new_local)` test; `recent_excludes` includes `STATE_APPLYING`
  in `unresolved` and only a later `record()` for the same move id clears it.
- Ledger: CR-234 does not fully fix res-companion-1
- Suggested fix: exclude `STATE_APPLYING` rows from `pending_relinks()` (the
  resume arm in `apply_move` is the right recovery route for them), and have
  `relink_moved` refuse when `new_local` does not exist.

### regression-18 - comp-sync-20: the new "retrying" answer does not stop the 7-day expiry it was written to stop
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:7545` against
  `dashboard/src/ccsync_dashboard/db.py:5480-5502` (`expire_delivered_file_moves`)
- What: the builder took the hunter's first option (answer `state="retrying"`)
  and changed nothing on the dashboard. `expire_delivered_file_moves` selects
  purely on `applied_at IS NULL AND expired_at IS NULL AND delivered_at < cutoff`;
  `mark_file_move_applied`'s retrying branch writes `state`/`attempts`/`detail`
  and touches neither timestamp, and `record_file_move_delivery` uses
  `COALESCE(delivered_at, ?)` so it never refreshes. "Retrying" is invisible to
  the expiry.
- Failure scenario: an editor takes the external SSD on a two-week shoot. The
  companion now answers "waiting for the sync drive" on every report instead of
  being silent, and on day 7 the target is expired exactly as before - the
  machine still holds the file at the old path, and lane A puts it back at the
  path the admin cleared.
- Evidence: read the fix at app.py:7510-7560, then `db.py:5450-5502` and
  `mark_file_move_applied`; `grep -rn comp-sync-20` shows app.py as the only code
  site.
- Ledger: CR-234 (comp-sync-20) does not fix comp-sync-20
- Suggested fix: take the hunter's second option too - exclude targets whose last
  answer was `retrying` from `expire_delivered_file_moves`, or refresh
  `delivered_at` when a retrying answer arrives.

### regression-19 - comp-ui-4: the "(s)" ban was extended to two files and app.py still ships four editor-visible plurals
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:3072, :3418, :3739, :4218,
  :9628, :9641`; the scan is `companion/tests/test_sweep_2026_09_04_copy.py:358-363`
- What: tray.py and settings_window.py were converted to `ui_copy.count` and
  given a blanket "no new `(s)` in a visible string" assertion - but that blanket
  loop names only `("tray.py", "settings_window.py")`, while app.py is still
  checked against a nine-phrase `retired` tuple alone. The `(s)` strings in
  app.py are arguments to `_notify_tray` and `popup.confirm_dialog`, not to
  `log.*`.
- Failure scenario: a canonical relink fixes 3 clips and the toast reads
  "Re-addressed 3 clip(s) to P: so they stay online for every editor"; likewise
  "Rehearsal finished: 5 file(s) were checked", "(2 folder(s) are set to be left
  alone ...)", "and 3 other clip(s)", and the LUT dialog's "7 LUT(s) on this
  computer". The test asserting UX-10's plurals were retired passes.
- Evidence: read tray.py:2248/3315/3483/3885/3908/4100 and
  settings_window.py:833 (all correctly converted), then scanned app.py for `(s)`
  within 8 lines of a UI call and read each hit.
- Ledger: CR-234 (comp-ui-4) does not fully fix comp-ui-4
- Suggested fix: add `app.py` and `popup.py` to the blanket `(s)` loop and
  convert those toasts to `ui_copy.count`.

### regression-20 - comp-sync-15: the second trash-summary producer still hands out the DEFAULT retention
- Severity: low
- Confidence: CONFIRMED (latent: no in-tree consumer today)
- Where: `companion/src/ccsync_companion/app.py:4851-4884` (`trash_summary`),
  calling `sync/lane_guard.py:1121`
- What: the fix added `path`/`max_age_days` to `RcloneLane._maybe_prune_trash`,
  closing the tray line. The other producer the hunter named,
  `app.trash_summary()` -> `lane_guard.trash_summary(root)`, is still called with
  one argument, so `retention_days` is `DEFAULT_TRASH_MAX_AGE_DAYS` whatever the
  site's `trash_max_age_days` says, and the fallback branch hardcodes the same
  default.
- Failure scenario: a site sets `trash_max_age_days = 3`; the next consumer of
  `app.trash_summary()` (it is in the pinned app contract,
  `tests/test_app_contract.py:60`) renders "copies are kept 14 days" about a
  folder pruned at 3 - the wrong-deadline defect SYNC-112 and comp-sync-15 both
  exist to stop, re-introduced by the next caller.
- Evidence: read app.py:4851-4884 and `lane_guard.trash_summary`'s signature;
  `grep -rn trash_summary companion/src` shows `self._trash_max_age_days` is
  never passed there.
- Ledger: CR-234 (comp-sync-15) does not fully fix comp-sync-15
- Suggested fix: pass the configured value through `app.trash_summary()` (and
  into the fallback's `retention_days`), or delete the dead method.

### regression-21 - comp-ui-2: the "second source that does not need a filesystem" is itself a file, written with a silent swallow
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/supervisor.py:226-231`
  (`write_relaunch_note`), consumed at `crash_report.py:645-655`
- What: the relaunch count reaches the next SUPERVISOR on argv but reaches the
  relaunched COMPANION only through `<crash>/relaunched.json`. `merge_history`'s
  docstring claims a source "that does not need a filesystem at all".
  `write_history` now returns a bool and logs a WARNING on failure;
  `write_relaunch_note` still returns None, swallows every failure with a bare
  `pass`, and uses a plain `write_text` rather than the tmp+replace used
  everywhere else in the package.
- Failure scenario: `<crash>/relaunched.json` is unwritable (an AV lock, or it
  exists as a directory) while `running.marker` in the same directory is fine and
  `<state>/supervisor.json` is also unwritable. `_relaunch_history` is empty on
  every relaunched companion, `--prior` is omitted, `decide` sees an empty
  history for ever, and a build that cannot stay up is relaunched every 10 s with
  nothing in any log saying the ceiling was lost.
- Evidence: read `supervisor.main`'s history merge, both writers,
  `supervisor_argv`/`spawn_for`, and `crash_report.install_native` ->
  `note_relaunch_history` -> `start_supervisor(prior=...)`.
- Ledger: CR-234 (comp-ui-2 / res-companion-4) does not fully fix comp-ui-2
- Suggested fix: have `write_relaunch_note` return whether it wrote, use
  tmp+replace, and log the same loud line `write_history`'s failure gets.

### regression-22 - dash-db-3: the cap bounds the rows but not the work the same marker buys
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/links.py:196-214` (the dedupe loops,
  before the `MAX_INCLUDES` break at :218-230)
- What: the `break` at entry 33 bounds `project_links` as promised, but it comes
  after two O(n^2) passes over the FULL list (`if declared in ordered`, then a
  `next((o for o in ordered ...))` per kept entry). `parse_includes` /
  `read_marker_data` cap nothing, so all entries are parsed, NFC-normalised per
  segment and compared before anything is capped. The cap's own comment at :40-43
  still claims "a tampered marker must not be able to make either unbounded".
- Failure scenario: an editor writes a `.ccsync-project` marker with 10,000
  includes on a share every editor can write. `_run_links` spends ~10^8 string
  comparisons inside every collector cycle before writing its 33 rows; the
  collector (whose own freshness is an alert kind) stalls, and
  `GET /api/.../includes` at `api.py:3131` stalls a request thread with it.
- Evidence: read links.py:187-231, `parse_includes` (:94-115) and
  `read_marker_data` (`provision.py:298-309`, a bare `read_text` with no size
  bound).
- Ledger: CR-240j does not fix dash-db-3
- Suggested fix: truncate `paths` to a small multiple of `MAX_INCLUDES` right
  after `parse_includes`, and bound the marker read, so the dedupe never sees an
  attacker-chosen n.

### regression-23 - dash-mounts-ui-5: the stale-while-revalidate write is not held alive, so the stale asset can survive anyway
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/static/sw.js:129-148`
- What: the `/static/` branch resolves `respondWith` with the cached hit and
  leaves the background `fetch(...).then(cache.put)` outside any
  `event.waitUntil(...)`. Once the respondWith promise settles the worker has no
  extend-lifetime promise pending, so the browser may terminate it before the
  network response arrives and before `cache.put` runs.
- Failure scenario: a same-version redeploy changes `style.css`; a phone opens
  the PWA, the worker serves the cached copy and is killed on idle or memory
  pressure before the revalidation resolves. Nothing is written to `CACHE` and
  the next load is stale again - the defect the fix is for.
- Evidence: read sw.js:95-155 and
  `dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py:324-339`; the node
  harness awaits all promises, so it cannot see this.
- Ledger: CR-243e does not fully fix dash-mounts-ui-5
- Suggested fix: add `event.waitUntil(network.catch(function(){}))` beside the
  `respondWith`.

### regression-24 - dash-release-jobs-5: a `stop()` whose join times out, plus `start()`, leaves two pollers and the orphan is uncancellable
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:1264-1284`
- What: `stop()` sets the event, drops `_thread` to None and joins with a 5 s
  ceiling. A cycle inside `check_now` can exceed that (`FEED_FETCH_TIMEOUT` 10 s
  per fetch, `ARTIFACT_FETCH_TIMEOUT` 600 s), so `stop()` returns while the old
  thread lives. `start()` then calls `self._stop.clear()` - the very flag the
  orphan is about to test - and spawns a second thread.
- Failure scenario: pause during a long fetch, then resume (exactly the reuse
  case this fix exists for). The orphan's `self._stop.wait(interval)` returns
  False because the new `start()` cleared the event, and two poller threads run
  `check_now` against the same database concurrently for the life of the process,
  one of them unreferenced.
- Evidence: read `FeedPoller.start/stop/_run` and the timeout constants at
  release_feed.py:96,99; `cards_exec.PinnedExecutor.stop` has the same shape, so
  copying it carried the flaw in.
- Ledger: CR-242c does not fully fix dash-release-jobs-5
- Suggested fix: keep the joined thread referenced and refuse to `start()` while
  `thread.is_alive()`, or give each run its own stop Event.

### regression-25 - res-fleet-4: the per-slot attempt ceiling loses the weekly report for an outage longer than about twenty minutes
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/alerts.py:708-786`
- What: `ok_only=True` is the right half, but `MAX_SEND_ATTEMPTS_PER_SLOT = 3`
  counts per SLOT, not per recovery, and the alerts cycle runs on
  `interval_alerts = 600.0` (`settings.py:566`). Three attempts cover about 20
  minutes from Monday 08:00; after that `weekly_due` is False until the next slot
  even once the sink comes back.
- Failure scenario: the SMTP relay is down 07:55-08:40 on Monday with the
  container up. Attempts at 08:00, 08:10 and 08:20 all fail, the budget is spent,
  and the week's report is gone rather than late - the outcome the finding was
  raised about. `weekly_due`'s docstring still promises "a container down for the
  whole of Monday still sends it on Tuesday" without saying a sink down for half
  an hour loses the week.
- Evidence: read `_attempts_since`, `weekly_due`, `heartbeat_due`, `run_cycle`'s
  weekly branch and `interval_alerts`'s default.
- Ledger: CR-241 (res-fleet-4) narrows but does not close the lost-slot case
- Suggested fix: count attempts since the last FAILED send and back off (10 min,
  1 h, 6 h) rather than capping per slot.

### regression-26 - ytdl-web-5: the new claim refusal reaches the page as "this computer declined the job (HTTP 503)"
- Severity: low
- Confidence: PLAUSIBLE
- Where: `ytdl/web/ytdlweb/db.py:1151` and `routes_fleet.py:469-471` against
  `ytdl/web/static/app.js:2286`, `:1436`, `:2546-2548`
- What: `created_local` is fixed when the job is CREATED, but `dispatchLocal`
  re-reads `localWanted()` at the review-panel start and at `retryFailed`. With
  `YTDL_LOCAL_DOWNLOAD` on, an editor who ticks "this computer" AFTER the search
  was submitted has a job with `created_local = 0` and a dispatch that goes
  ahead; the claim is refused 410 `created_widened`, the companion answers 503,
  and the SPA paints a bare HTTP code.
- Failure scenario: flag on, editor searches with the switch unticked, ticks it
  while reviewing candidates, presses start. The job downloads on the server
  (correct) but the page reports "this computer declined the job (HTTP 503)",
  which reads as a broken companion. The ledger asserts "nothing an editor sees
  changes".
- Evidence: read `claim_download`'s `COALESCE(created_local,1)=1`,
  `routes_fleet.claim`'s `created_widened` branch, `localWanted()` and the three
  `dispatchLocal` call sites.
- Ledger: CR-244 (ytdl-web-5) opens a neighbour in the SPA's decline note
- Suggested fix: have `dispatchLocal` skip the hand-off when the job it holds was
  not created local, or map `created_widened` to a sentence rather than an HTTP
  code.

## Coverage note

Judged SOUND and not restated above (the fix closes the hunter's whole scenario,
on the platforms it named): server-tools-2 / dash-mounts-ui-1 (the /help
disclosure - one `published_docs.py` list, the audience gate in
`help.resolve_document` defaulting to non-admin, and `install_tree`'s swap
removing stale staged docs), dash-core-1 and dash-core-2, server-tools-1 (both
halves: `Get-KindExtrasVerdict` and `_rollout_block` returning null),
dash-collector-alerts-2, broll-2's migration half, music-1, comp-broll-music-1
(both the b-roll and the music side), dash-api-3 (v52 `update_requested_from`,
`_update_push_done`'s direction rule, the channel moving with the fleet, and the
14-day expiry that stops an un-clearable downward push riding for ever),
install-onboard-1; and dash-api-1, dash-collector-alerts-3/-4/-5/-6,
dash-mounts-ui-4, server-tools-3, ytdl-web-1, ytdl-web-3, install-onboard-2,
install-onboard-3, res-fleet-1, comp-sync-1/-2/-3/-5/-6/-8/-9/-13, comp-app-1,
comp-app-2, comp-resolve-2, comp-resolve-3, comp-ytdl-jobs-1, comp-ytdl-jobs-2,
res-companion-2, comp-broll-music-3, broll-1, music-2, music-3,
dash-release-jobs-3. Lows sampled and sound: comp-app-4/-5/-6/-7,
comp-sync-14/-16/-17/-18/-21/-22, comp-resolve-1/-5/-6, comp-broll-music-4/-5,
comp-ytdl-jobs-4/-5, res-companion-4, dash-api-5, dash-collector-alerts-7,
dash-core-3/-4/-5/-6/-7, dash-db-1/-4, dash-mounts-ui-2/-7/-8,
dash-release-jobs-2/-4, res-fleet-5/-6, ytdl-web-2/-7, music-4/-6,
install-onboard-5/-6, server-tools-5, broll-3/-4.

Not reached: about 28 of the 80 lows, chiefly `comp-sync-19`, `dash-api-4/-6`,
`dash-collector-alerts-8`, `dash-mounts-ui-6`, `dash-release-jobs-6/-7`,
`music-7`, `ytdl-web-4/-6`, `server-tools-4/-6`, `install-onboard-4`,
`broll-5/-6`, `res-companion-5`. install-onboard-1 remains unexecuted on a Mac -
the one-line `os.path.ismount('/Users')` test the verifier set is still the only
thing that settles it, and this session had no Mac either. Nothing here was run
against a live dashboard, the NAS or a real Resolve. A residual exposure worth an
owner decision rather than a finding: an image built BEFORE 18e69f3 still carries
the whole docs tree on a customer's server, and the new audience gate lets that
customer's own ADMIN read KNOWN_BUGS.md and CLAUDE.md from it until the image is
replaced.

What the suites do not cover, seen repeatedly while auditing: several of this
afternoon's regression tests pin the new behaviour through the seam the fix
added rather than through the shape that broke - `mount_status`'s test injects
`lambda _p: False` where production's probe answers True (regression-1),
`test_a_personal_project_does_not_clear_an_open_out_of_tree_alert` never makes
the machine RED (regression-2), the dash-api-2 test only drives `expire_leases`
(regression-3), and the two comp-sync-11 tests call the module function, never
the app twin the fix's own comment names (regression-5). A test that cannot see
the production probe is the common thread.

## OUT OF TERRITORY
- `ytdl/web/ytdlweb/attestation.py:40`: `TEXT_VERSION` was deliberately not
  bumped after the notice text was edited, so stored `text_sha256` rows no longer
  match the live wording for the same version string. Reasoned and documented,
  but worth an owner decision.
