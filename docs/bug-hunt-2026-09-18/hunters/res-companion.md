# res-companion - what an editor's machine does when things go wrong (whole failure paths, across files)

Files read (with approximate coverage):
`companion/src/ccsync_companion/broll_standins.py` (100%),
`broll_fetch.py` (100%), `broll_server.py` (the insert/plan/upgrade half,
lines 800-1300, ~25%), `proxy_relink.py` (~80%: `stored_frames`,
`frame_counter`, `_geometry_disagrees`, `plan_relinks`, `apply_relinks`),
`ffmpeg_tools.py` (`count_frames*`, `PROBE_TIMEOUT_SECONDS`),
`resolve_bridge.py` (proxy/frames enrichment, `save_project`,
`_before_mutation`, ~10%), `app.py` (`LaneWatchdog` 930-1200,
`_refresh_media_tree_once` / `_relink_proxies_once` / `_media_tree_loop`
4090-4500, the file-move command handler 7800-7880, `_start_media_tree_thread`
9150-9170, the stand-in `configure` at 1628; ~15%),
`file_moves.py` (`apply_move`, `relink_moved`, ledger API),
`sync/server_locate.py` (100%), `sync/rclone_lane.py`
(`_relocate_trashed`, `_local_destination`, `_move_out_of_trash`,
`_count_relocations`, ~8%), `watcher.py` (`_archive_exempt`),
`docs/HAND_MOVES_ON_THE_SERVER.md`, `docs/BROLL_PROXY_TIERS_PLAN.md`
(section 6 as quoted in the code), `KNOWN_BUGS.md` (greps).

Tests run: none (read-only tracing; every claim below is verified by reading
both ends of the path).

## Findings

### res-companion-1 - a stand-in download that nobody polls to completion leaves an UNLEDGERED lie at the original's path, for ever
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_server.py:1071-1086` (the only
  `broll_standins.record` call in the tree) and
  `companion/src/ccsync_companion/broll_fetch.py:361-376` / `_run_job`
- What: the stand-in route downloads the PREVIEW's bytes to the ORIGINAL's
  own local path with `rclone copyto` on a daemon thread, and the ledger row
  that remembers the lie is written only by the HTTP request thread, on the
  poll that observes `state == "done"`. Nothing else in the companion ever
  writes a row (`grep broll_standins.` finds exactly one `record` call). If
  no further poll arrives after rclone renames `<name>.partial` onto the
  destination - the editor closed the tab, the browser navigated away, the
  companion was quit or self-upgraded (`stop_all()` kills rclone, but a
  rename that already happened stands) - the preview's bytes sit at the
  original's path with no ledger entry at all.
- Failure scenario: a remote editor clicks Send to Resolve on a 6K
  `A001_0123.mov`, the toast shows "syncing 40%", they switch tabs or the
  tray restarts for an upgrade; rclone finishes and renames. From then on
  `local_path.is_file()` is True and `broll_standins.is_standin()` is False,
  so `plan_insert` returns `PLAN_IMPORT_ORIGINAL` with
  `upgrade_rel = None` (broll_server.py:872-885): the next click imports a
  1080p H.264 file under the 6K original's name, never fetches the editing
  proxy, and the clip is not exempted by `watcher._archive_exempt` nor
  protected by `proxy_relink`'s `.mp4` rule (both ask the same ledger). The
  module docstring names this exact outcome as "the one failure this module
  exists to prevent" ("a render on this machine would render 1080p H.264
  under a 6K name") and the `record()` docstring's promise "called BEFORE the
  import, always" is true only of the import, not of the file landing.
- Evidence: `broll_fetch._run_job` sets `STATE_DONE` on its own thread and
  the file is already at `job.dest` at that instant (line 361); `poll_fetch`
  only reports and pops that state when a caller polls; `broll_server`
  records only inside the `if not insert_path.is_file():` branch after a
  `STATE_DONE` answer. No startup or watcher sweep reconciles the archive
  against the ledger (`grep -rn "broll_standins\."` shows readers only:
  `is_standin`, `is_under_archive`, `get`, `set_upgrade`,
  `pending_upgrades`).
- Ledger: new (proxy tiers phase 3 / CR-281)
- Suggested fix: write the ledger row BEFORE the download starts (a
  `placed_at` row with `size: None`, which `_entry_is_stale` already treats
  as "still a stand-in", i.e. the safe direction), and update `size` when the
  poll sees `done`; or have `broll_fetch` accept an on-success callback that
  the stand-in caller uses so the recording happens on the download thread,
  not on the polling one.

### res-companion-2 - lane B's hand-move follow leaves Resolve pointing at the old path, and the later file_moves command answers "nothing at the old path" instead of relinking
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/rclone_lane.py:4026-4033`
  (`_relocate_trashed` -> `_move_out_of_trash`) and
  `companion/src/ccsync_companion/file_moves.py:341-359` (`apply_move`'s
  `if not src.exists():` branch) with `app.py:7840-7860`
- What: CR-268's lane B now RENAMES the local copy into the server's new
  relative path itself, with no `file_moves` ledger intent row and no Resolve
  relink. Minutes later the dashboard's detection (v53) delivers the same
  move as a `file_moves` command with `source='detected'`. `apply_move` finds
  `src` gone; the resume branch requires an intent row in state
  `STATE_APPLYING`, which lane B never wrote, so it returns
  `(True, "nothing at the old path on this machine", None)`. With `paths is
  None`, `app.py` skips `_relink_moved_result` entirely, sets
  `relink_pending = False`, and answers the dashboard `ok` - the move is
  recorded as done on both sides.
- Failure scenario: someone drags `Interviewees/Creator_Interviews` into
  another project on the NAS. Ruskin's lane B pass runs inside the 15-minute
  inventory window (the exact race §4a was written for), moves his proxies to
  the new path, and does not trip the breaker - as designed. The detection
  command then arrives and does nothing. Every clip under that folder is
  MEDIA OFFLINE in his Resolve project for ever, the dashboard's MOVES
  history says his machine followed, and nobody is told. Worse, this is
  precisely the state res-companion-1 of the 09-11b pass describes as making
  "the fixer's answer to an in-tree missing clip ... copy it back to the path
  the admin just cleared".
- Evidence: `docs/HAND_MOVES_ON_THE_SERVER.md` §3 promises "Resolve keeps its
  links through `resolve_bridge.replace_clip`, with the same save point and
  undo journal the button gets" and §4a specifies only the rename for lane B;
  `grep -n "file_moves\|record_intent" sync/rclone_lane.py` shows lane B
  never touches the move ledger (only `recent_excludes` is read, at 2369);
  `apply_move`'s resume is gated on `ledger.entry(move["id"])` having
  `state == STATE_APPLYING`.
- Ledger: new (CR-268a/b); CR-266-era `res-companion-1` fix does not cover
  this second way of arriving at "src gone, dest present"
- Suggested fix: have `_relocate_trashed` relink Resolve for each file it
  carries (or record an intent row keyed by the destination so `apply_move`'s
  resume branch fires), and/or make `apply_move` treat "src absent, dest
  present, dest size matches" as a resumable move regardless of the intent
  row, returning the pair so the relink and `relink_pending` bookkeeping run.

### res-companion-3 - the phase 3 geometry check runs a whole-file ffprobe per archive clip per 120 s pass, on the media-tree thread, before any rate limit
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/proxy_relink.py:544-550`
  (`refresh = ... _geometry_disagrees(...)`), `proxy_relink.py:285-309`
  (`frame_counter`, cache is per PASS), `ffmpeg_tools.py:905-962`
  (`-count_packets`, `PROBE_TIMEOUT_SECONDS = 60`), driven from
  `app.py:4431-4444` inside `_refresh_media_tree_once`
- What: for every in-tree media-pool clip under the b-roll archive whose
  original is on disk and is not a ledgered stand-in, `plan_relinks` now runs
  `ffprobe -count_packets` - which demuxes the ENTIRE file - with a 60 s
  timeout, serially, on the media-tree thread, every `media_tree_refresh_
  interval` (120 s). The per-pass cache deliberately does not persist, so the
  cost repeats every pass for ever, and it is paid BEFORE
  `resolve_journal.allow_automatic` is consulted (app.py checks the rate
  limit only after `if not ops: return`), so the rate limiter does not bound
  it.
- Failure scenario: the base rig (wired, `local_root` = the NAS share) with
  120 archive clips in a documentary's pool reads all 120 files end to end
  off SMB every two minutes, competing with lanes A/B and Resolve for the
  same link; a remote editor on a slow drive pays it against her own disk. If
  the aggregate exceeds 30 minutes the media-tree heartbeat
  (`app.py:4481`, stamped only at the top of the loop) goes stale and the
  `LaneWatchdog` "restarts" the thread (see res-companion-4). The
  `ops-efficiency-8` rule the same file cites ("a stat per clip per 120 s is
  the thousand round trips a minute that the media-presence cache exists to
  stop") is broken by several orders of magnitude.
- Evidence: `count_frames_cmd` uses `-count_packets` (no `-read_intervals`,
  no duration bound); `frame_counter`'s docstring states the cache is per
  pass on purpose; `resolve_bridge.py:1846-1853` attaches `frames` for every
  archive clip, so `stored_frames` is non-None for all of them and
  `_geometry_disagrees` proceeds to the probe.
- Ledger: new (proxy tiers phase 3 / CR-281)
- Suggested fix: cache the (path, size, mtime) -> frame count answer across
  passes on disk or in the process (a file whose count changed also changes
  size/mtime, which is the falsifier the stand-in ledger already uses), and
  ask only about clips the ledger has an entry for - the only clips whose
  geometry can be a stand-in's.

### res-companion-4 - a wedged media-tree (or watcher) thread is "restarted" without being stopped, so the watchdog stacks duplicate threads that both mutate Resolve
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:1159-1169` (`LaneWatchdog.
  _restart`), `app.py:9152-9162` (`_start_media_tree_thread`),
  `app.py:1135-1148` (`_media_tree_target`, `bound = 30 min`)
- What: the watchdog restarts a thread not only when it `died` but when its
  heartbeat is older than 30 minutes. `_restart` simply calls
  `_start_media_tree_thread()`, which CLEARS the shared
  `_media_tree_stop_event` and starts a new thread, overwriting the
  reference. The old thread is neither signalled nor joined - and since the
  stop event is cleared, it will keep looping when it unblocks. The new
  thread's heartbeat immediately satisfies the watchdog, so the wedge is
  reported as healed while two (and, up to the 5-per-hour ceiling, more)
  media-tree threads run.
- Failure scenario: res-companion-3's ffprobe storm (or an SMB share that
  stops answering - the exact "read wedged in the kernel" case SYNC-2
  describes) makes one pass exceed 30 minutes. The watchdog spawns a second
  media-tree thread; both walk the media pool and both reach
  `_relink_proxies_once` -> `apply_relinks` -> `resolve_bridge.replace_clip`
  / `link_proxy_media`, i.e. two unprompted writers into the same Resolve
  project, each taking save points and writing undo journals, plus two
  `retry_loopback_bind()` callers. `sync_guard.restarts` shows "restarted",
  which reads as recovery.
- Evidence: `_restart` has no stop/join and no liveness precondition;
  `_start_media_tree_thread` calls `self._media_tree_stop_event.clear()`
  before spawning; `_media_tree_loop` tests that same shared event, so the
  orphan does not exit; `_media_tree_target` reports `died = not
  thread.is_alive()` of the NEW reference only.
- Ledger: related to SYS-2 (the watchdog, 2026-08-28, FIXED) - the wedged
  branch was never given a stop path
- Suggested fix: for the silent-but-alive branch, set the stop event (and, for
  the media tree, use a per-thread event) and only start a replacement once
  the old thread has exited or has been marked abandoned; at minimum have
  the loop check an owner token and exit when it is no longer the current
  thread.

### res-companion-5 - a stand-in-born clip whose stored geometry never converges re-runs replace_clip every pass, with nothing remembering the refusal
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/proxy_relink.py:551-566` (the
  `refresh` op is appended and `continue`s before any `is_refused` /
  `note_refusal` logic) and `proxy_relink.py:703-720` (`apply_relinks`
  refresh branch)
- What: `refresh` is planned whenever Resolve's stored `Frames` differs from
  ffprobe's packet count, and unlike a proxy link it is never remembered.
  Resolve's `Frames` and a demuxed packet count can legitimately disagree for
  reasons a `ReplaceClip` will not fix (an mp4 with an edit list, VFR media,
  a clip whose attributes override the frame rate), and `ReplaceClip` on the
  same path does not necessarily change the stored number.
- Failure scenario: one archive clip that disagrees for a non-stand-in reason
  is re-replaced on every pass that wins the `allow_automatic` bar, each
  carrying a `SaveProject` + `ExportProject` save point (`resolve_bridge.
  save_project`) and an undo-journal entry, for the life of the project -
  `~/.ccsync/resolve_edits` grows without bound and the project is saved
  under the editor.
- Evidence: the `refresh` op appends and `continue`s before the refusal
  machinery; `apply_relinks` increments `refreshed` and logs INFO but calls
  no `note_refusal`; `allow_automatic` bounds the rate (min interval + daily
  cap) but never the repetition.
- Ledger: new (proxy tiers phase 3 / CR-281)
- Suggested fix: remember a refresh that has already been performed for a
  given (path, size, mtime) - the same shape `note_refusal` uses - so a
  disagreement that a ReplaceClip does not resolve is attempted once, not for
  ever.

## Coverage note
Not reached: the drive-pull / `drive_reminder` path against the new
background fetch lane, `syncthing_lane`'s CR-278 path-missing heal,
`jobs_media` interruption, the ingest half of proxy tiers (`broll_ingest*`,
upload order on a killed process), `supervisor.py` vs a wedged (not dead)
companion, and the upgrade-mid-anything path. The suite does not cover any
of the five findings above: there is no test for a stand-in download whose
poll never returns (`test_broll_standins.py` and `test_broll_insert_tiers.py`
always poll to `done`), none for lane B's relocation followed by the
`file_moves` command (the two live in different test files and are never
composed), none for the ffprobe cost or cadence (`test_proxy_relink_standins.py`
injects `count_frames_fn`, which mocks away exactly the expensive thing), and
none for the watchdog's alive-but-silent restart producing two threads.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/broll_standins.py:299-324`: `is_stale()`
  is documented as "the relink pass's signal" but has no caller anywhere in
  the tree - the relink pass uses `_geometry_disagrees` instead (comp-resolve
  / proxy-tiers).
- `companion/src/ccsync_companion/broll_standins.py`: no entry is ever
  `forget()`ten, so the ledger grows for the life of the machine
  (comp-broll-tiers).
- `companion/src/ccsync_companion/broll_fetch.py:268-293`: the comment claims
  rclone's `.partial` staging unconditionally; that is a local-backend
  default and is worth pinning rather than assuming (comp-broll-tiers).
