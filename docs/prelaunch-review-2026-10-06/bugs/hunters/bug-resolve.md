# Pre-launch bug hunt: companion Resolve stack (lens `bug-resolve`)

Date: 2026-10-06. Tree: HEAD 08b40eb plus the uncommitted working tree
(including the new import-then-MoveClips shape in `_import_files_to_bin_path_locked`).

**What this covers.** I read `resolve_bridge.py` end to end: connect and the
CR-68 guard, `_bridge_call` and the primed probe, the library walk and its
caches, the uid map, save points, `replace_clip`, `link_proxy_media`, undo,
insert and import. I also read `script_server.py`, `resolve_journal.py`,
`resolve_undo.py`, `fixer.py`, `watcher.py` (poll path), `resolve_prefs.py`,
`stills.py`, `project_setup.py`, `timeline_cards_bridge.py`,
`timeline_cards_role.py` (gate, start/stop, tunnel) and `consolidate.py`
(`run_consolidation`). I also covered the parts of `luts.py` that write
(`copy_into_library` and `repair_stale_index`) and `library.py`'s
connection, path cache and change detection. I followed every caller of
`replace_clip` and `link_proxy_media` in `app.py`, `file_moves.py`,
`proxy_relink.py` and `music_worker.py`. I checked the Cards engine in the
MulticamPipeline checkout read-only, to see whether it calls `sweep_items`
under the API lock. It does not.

**Probes.** I wrote throwaway scripts in the scratchpad that use the
companion venv and a redirected HOME. They never touch Resolve and never call
scriptapp. They confirmed bug-resolve-1, -2 and -3.

**Not covered in depth.** The body of `proxy_scan.py`, `library.py`'s
timeline and multicam expansion SQL (`timeline_items`, `_expand`,
`_folder_tree`), and `luts.py`'s stale-index log parsing.

**Already known and fixed, so not re-reported.** bug-comp-resolve-1..9 and
logic-resolve-1..5 (2026-09-24 hunt, all fixed except bug-comp-resolve-7,
which was deferred on purpose: the uid-map `is` test).

---

### bug-resolve-1 - UNDO LAST FIX right after a FIX ALL retires the journal and undoes nothing when the media pool comes from the project library

- **Severity:** high
- **Confidence:** CONFIRMED (code path traced and probed). The premise that
  the library trails a scripted relink comes from the module's own comments.
- **Where:** `companion/src/ccsync_companion/resolve_bridge.py:2723-2813`
  (`undo_last_relink`), `:1744-1847` (`get_media_pool_items` /
  `_library_pool_read`), `:911-919`, `library.py:42-43, 738-779`
- **What:** `undo_last_relink` builds its `by_path` map from
  `get_media_pool_items()`. That function answers from the PROJECT LIBRARY
  whenever one can be read, and the library is the project database on disk.
  The bridge's own comments say that database lags a scripted `ReplaceClip`:
  it does not move until the project is saved when Live Save is off ("the
  library trails the UI ... until the next manual save with Live Save off").
  On top of that, `ProjectLibrary.pool_paths()` caches uid to path until
  `changed()` sees `LastModTimeInSecs`/`DbSavedTime` move. `_before_mutation`
  saves the project BEFORE the first ReplaceClip, so the database holds the
  pre-fix paths. Right after a FIX ALL, every journal entry's `new` path is
  therefore missing from the library answer and its `old` path is present. The
  loop counts every entry as `already_back`. `ok` comes out True, and
  `mark_undone()` retires the journal.
- **Scenario:** An editor has Live Save off (a per-machine Resolve
  preference) and the library walk on (the default; Disk and PostgreSQL
  libraries are both read). They run FIX ALL over 50 clips, look at the
  result, and press UNDO LAST FIX within the same minute, as the popup
  invites them to. The probe output was `{'ok': True, 'undone': 0,
  'already_back': 3, 'message': 'Those clip paths were already back the way
  they were ... nothing to put back.'}` with zero ReplaceClip calls and
  `is_undone(journal) == True`. A second press then says "Every clip-path
  change CCSync made in FF4 has already been put back." The clips are still
  relinked, the tray no longer offers the undo, and an admin undo-by-id
  through `resolve_undo` reports `done` for the same reason. This is the
  rollback of last resort (COMMERCIAL_READINESS item 9), and here it states
  something false and then throws itself away.
- **Recommendation:** Never decide an undo from library data. Use
  `_get_media_pool_items_locked()` (the API walk) inside `undo_last_relink`.
  Or resolve each entry's clip by uid and re-read its LIVE `File Path` before
  classifying it as already back. Do not `mark_undone` when `undone == 0`
  unless the already-back verdict was checked against the live API.
- **Known:** not recorded. logic-resolve-2 (fixed) added the `already_back`
  arm; this is a new failure of that arm.

### bug-resolve-2 - The library's 60 s staleness ceiling never fires while the watcher is polling, so a pool-only edit can stay invisible for as long as the timeline is open

- **Severity:** medium
- **Confidence:** CONFIRMED (probed: 20 simulated minutes of 3 s polls caused
  zero path-cache drops)
- **Where:** `resolve_bridge.py:1164-1172` (`_library_answers_are_stale`,
  `_library_read_done`), `:1470-1507`, `:1823-1840`
- **What:** `_LIBRARY_CACHE_MAX_SECONDS = 60` is documented as "a CEILING on
  how stale a library answer may be, independent of changed()". Its only job
  is to drop `ProjectLibrary._paths` when `changed()` cannot see an edit. The
  test, however, is "60 s since the last walk that went to the database".
  `_library_read_done()` resets that stamp on EVERY non-cached walk, and the
  watcher's own safety valve forces such a walk every 10th poll (about 30 s).
  `_library_pool_read` resets it too. On any machine where the watcher runs,
  the stamp is never more than about 30 s old, so `stale` is never true and
  `_drop_library_path_cache` is never called. The uid-to-path cache then lives
  until `changed()` reports a fingerprint move.
- **Scenario:** The companion relinks clips in bins that are on no timeline:
  the auto-canonical pass, a file move, or a FIX ALL from SCAN WHOLE PROJECT.
  If that pool-only edit does not move `SM_Project.LastModTimeInSecs` or any
  sequence's `DbSavedTime` (unmeasured; the plan says the signal "is blind
  while Live Save is off"), every library reader keeps serving the old path
  indefinitely. That covers the watcher's classification and therefore the
  popup re-offering clips that are already fixed, `proxy_relink.plan_relinks`,
  `file_moves.relink_moved`, and the undo in bug-resolve-1. The backstop
  written for exactly this case is dead code in production.
- **Recommendation:** Track the cache-drop time separately from the
  last-read time. Stamp only when `_drop_library_path_cache` runs (or when
  `changed()` reloaded), and drop when that stamp is 60 s old. Also drop the
  library path cache (`_drop_library_path_cache`) after any successful
  `replace_clip` or `link_proxy_media`, since the bridge knows it just changed
  a path.
- **Known:** not recorded.

### bug-resolve-3 - UNDO LAST FIX can be permanently hidden behind an empty or un-replayable newer journal, and blames refusals on clips "no longer in the media pool"

- **Severity:** medium
- **Confidence:** CONFIRMED (two probes). That `LinkProxyMedia` refuses an
  unreachable proxy path is PLAUSIBLE; the shadowing does not depend on it.
- **Where:** `resolve_journal.py:451-487` (`open_session`), `:537-541`
  (`note_save_point`), `:601-613` (`latest_undoable_session`), `:713-727`
  (`describe_latest`); `resolve_bridge.py:2305-2338` (`_before_mutation`),
  `:2693-2721`, `:2777-2813`
- **What:** There are two ways the newest journal can become one that UNDO
  LAST FIX can never get past:
  1. **Empty journal.** `_before_mutation` takes a save point BEFORE the edit,
     whenever one is due (every 15 min per project), and `note_save_point`
     calls `open_session`, which creates a NEW journal file when no burst is
     open. If the ReplaceClip or LinkProxyMedia that follows does not take,
     nothing is recorded, and the newest journal has `entries: []`.
     `latest_undoable_session` skips only undone journals, not empty ones. So
     `undo_last_relink` answers "<file> records no changes", and
     `describe_latest` answers "" for this project AND globally. The tray hides
     the undo entirely.
  2. **Un-replayable journal.** A journal whose entries all fail to replay
     (`undone == 0`) is never marked undone. An example is an auto proxy
     repoint whose `old` proxy was the stale, unreachable one: by
     construction, op reason "stale" means attached but unreachable, and
     Resolve validates LinkProxyMedia. Every later press replays the same
     file.
  In both cases every older journal is unreachable from the tray. The
  rejection message is also wrong: `skipped` counts refusals as well as
  missing clips, and the editor is told "those clips are no longer in this
  project's media pool" about clips that are still in it.
- **Scenario:** At 10:00, FIX ALL relinks 50 clips (journal J1). At 10:20 the
  120 s proxy pass finds a clip and a save point is due. `note_save_point`
  creates J2, and Resolve refuses the proxy (the R10 timecode refusal is the
  common case). J2 is empty, so the tray's UNDO LAST FIX disappears and the
  50-clip FIX ALL can only be undone through the dashboard's undo-by-id.
  Variant: at 10:10 the pass repoints a stale proxy (J2, one entry). Probe:
  three presses each said "Put 0 clip path(s) back ... 1 could not be undone:
  those clips are no longer in this project's media pool", and the tray label
  stayed on J2 for ever.
- **Recommendation:** Do not create a journal file from `note_save_point`
  alone. Hold the save-point outcome in memory and write it with the first
  `record()`. Make `latest_undoable_session`/`describe_latest` skip journals
  with no entries. Retire a journal (or step past it) when a replay leaves
  nothing that could still succeed, and count `refused` separately from
  `not_in_pool` in the message.
- **Known:** not recorded. logic-resolve-2 (fixed) is the "already undone"
  half of the same selection rule.

### bug-resolve-4 - Every b-roll insert, music import and stand-in proxy upgrade runs a full SaveProject + ExportProject and opens a fresh journal, because the worker is a new process each time

- **Severity:** medium
- **Confidence:** CONFIRMED (traced; the rate-limit state is in-process
  globals)
- **Where:** `music_server.py:155-200` (one `subprocess.run` per call),
  `music_worker.py:483-536, 300` (`act_broll_insert`, `act_broll_link_proxy`,
  music import with `canonical_fn`), `resolve_bridge.py:3297-3303, 3558-3586`
  (`_canonicalize_imported` -> `replace_clip`, journaled),
  `:2305-2338` (`_before_mutation`), `resolve_journal.py:117-118, 543-560`
  (`_save_points`, `save_point_due`), `:451-482` (`_sessions`)
- **What:** `save_point_due` throttles the SaveProject+ExportProject save
  point to once per 15 min per project using `_save_points`, and the journal
  groups edits into one file per burst using `_sessions`. Both are module
  globals, which means per PROCESS. The b-roll "Send to Resolve", the
  stand-in proxy upgrade and the music import all run in a brand-new
  `--music-resolve-worker` child for every request. In each child the dicts
  are empty, so the first mutation always takes a full save point and always
  starts a new journal file. That first mutation is `_canonicalize_imported`'s
  ReplaceClip, which runs for any fresh import of an in-tree file on a machine
  whose `local_root` is not the canonical prefix (every remote editor;
  the archive is `<local_root>/Assets/B-roll Archive`). For the proxy upgrade
  it is `link_proxy_media` with `source="broll_proxy_upgrade"`.
- **Scenario:** A remote editor sends 40 archive clips to the timeline in an
  afternoon. That is 40 `ExportProject` calls of the whole project database.
  The comment at `resolve_journal.py:66-68` says "seconds of Resolve's main
  thread" each, on the request's 90 s budget. It also writes 40 `.drp` files,
  tens of MB each by the module's own comment (`resolve_journal.py:731-737`),
  into `~/.ccsync/resolve_edits`, swept only after 60 days, plus 40 separate
  one-entry journals. The newest of those journals becomes what UNDO LAST FIX
  targets. Pressed after a FIX ALL, it reverts the latest b-roll clip's
  canonical `P:\...` spelling back to the machine-private local path, which is
  offline on every other machine, instead of undoing the FIX ALL. The two
  processes can also mint the same per-second journal filename for one
  project, and then the later `_write` replaces the other's file.
- **Recommendation:** Persist `_save_points` (or `last save point at`) to
  disk like `resolve_auto.json`. Alternatively, run the save point decision
  in the parent and pass `journal`/`save_point` intent to the child. Give
  worker-originated journals a source the tray's UNDO LAST FIX can exclude,
  or keep them out of "last fix" altogether. Make `_session_path` unique per
  process (pid suffix).
- **Known:** not recorded.

### bug-resolve-5 - On macOS the Resolve process probe looks for a process named "DaVinci Resolve", which is probably not the executable's name

- **Severity:** medium
- **Confidence:** PLAUSIBLE (I believe the bundle executable is
  `DaVinci Resolve.app/Contents/MacOS/Resolve`, so `p_comm` is `Resolve`, but
  this needs a Mac to confirm)
- **Where:** `resolve_prefs.py:149-153` (`pgrep -x "DaVinci Resolve"`);
  consumers `resolve_prefs.py:352, 447, 504`, `resolve_bridge.py:592-633`,
  `app.py:4747, 4814, 11996`; compare `installer/macos_bootstrap.sh:725`
  (`pgrep -f "DaVinci Resolve"`, a full-command-line match) with `:1452`
  (`pgrep -x`)
- **What:** `pgrep -x` matches the exact process name (the executable,
  `p_comm`), not the bundle's display name. The installer's own Python
  helper uses `-f` (the full path, which contains "DaVinci Resolve"), so the
  two disagree. If the name is `Resolve`, `resolve_process_state()` answers
  False ("definitely absent") on every Mac while Resolve is open.
- **Scenario:** On a Mac editor with Resolve open:
  - The 900 s LUT/stills reconcile writes `config.dat` and `.config.data`
    under a running Resolve, which then overwrites them from memory on quit.
    The edit is lost while the log says it succeeded ("gallery moved to ..."),
    and a `.ccsync-bak-*` pair is left each time.
  - `describe_disconnection()` tells an editor looking at an open Resolve
    whose scripting is dead that "DaVinci Resolve is not running", which is
    the exact dead end the helper was written to end.
  - `_maybe_warn_scripting_dead` never warns.
  - `_maybe_recover_stale_bridge` restarts the companion while Resolve is
    still up.
- **Recommendation:** Match the way the installer's Python helper does
  (`pgrep -f "DaVinci Resolve.app/Contents/MacOS/Resolve"`), or accept either
  `-x Resolve` or `-x "DaVinci Resolve"`. Confirm on the studio Mac and fix
  `wait_for_resolve_quit` in `macos_bootstrap.sh` the same way.
- **Known:** not recorded.

### bug-resolve-6 - A Windows TCP-table read failure is reported as ABSENT (fail closed), not UNKNOWN as the CR-68 guard documents

- **Severity:** low
- **Confidence:** CONFIRMED (read)
- **Where:** `script_server.py:188-206` (`_windows_tcp_rows`), `:323-336`
- **What:** The module's rule is "fail open only when the table itself
  cannot be read". In `_windows_tcp_rows`, a second `GetExtendedTcpTable`
  call that returns non-zero just `continue`s. `ERROR_INSUFFICIENT_BUFFER`
  (122) is returned whenever the table grows between the sizing call and the
  read, which is common with rclone `--transfers` and Syncthing opening
  connections. A zero size also just `continue`s. Either way the probe goes
  on with no IPv4 rows, `classify` sees no listener, and it answers ABSENT
  instead of UNKNOWN. That is safe for CR-68, because it withholds a
  connection.
- **Scenario:** On a busy rig, now and then a poll reads "no script server".
  The bridge reports a disconnection for that poll: the tray flips to
  NO_SERVER_MESSAGE, the watcher logs a transition, and an admin undo that
  arrives in that poll is answered `retrying`. This is noise that makes CR-68
  diagnoses harder to read.
- **Recommendation:** Retry the sized read on 122 with the new size (two or
  three attempts). If a family still cannot be read, raise so that
  `_probe_uncached` returns UNKNOWN.
- **Known:** not recorded.

### bug-resolve-7 - The journal's project check compares slugs, so two projects whose names share their first 80 characters (or differ only in `/ : * ?`) can replay each other's undo

- **Severity:** low
- **Confidence:** CONFIRMED (read and probed: `project_slug("Ep 1/2") ==
  project_slug("Ep 1:2")`)
- **Where:** `resolve_journal.py:141-151` (`project_slug`, truncation at
  80), `resolve_bridge.py:2693, 2731-2739` (the comp-resolve-2 guard)
- **What:** The comp-resolve-2 guard against replaying project A's journal
  in project B compares `project_slug(journal_project)` with
  `project_slug(open_name)`, even though the journal stores the full
  `project` name. Names that slug the same pass the check, and they also
  share one journal directory, so `latest_undoable_session` hands B the
  journal A wrote.
- **Scenario:** An editor with long versioned project names that differ
  only after character 80 (e.g. "... Rough Cut v2" and "... v3") presses UNDO
  in v3. v2's last FIX ALL is replayed against v3's pool through the Assets
  paths the two share. This is the cross-project rewrite the guard exists to
  prevent.
- **Recommendation:** Compare the stored raw `project` name (whitespace
  stripped) with the open project's name. Keep the slug for the directory
  only, and add a short hash of the full name to the slug so different
  projects never share a directory.
- **Known:** not recorded.

### bug-resolve-8 - The stills "gallery moved" sentence prints a forward slash on Windows

- **Severity:** low
- **Confidence:** CONFIRMED (read)
- **Where:** `stills.py:161` with `app.py:10603, 12017` (constructed without
  `windows=`)
- **What:** `separator = "\\" if self._windows else "/"`. `_windows` is None
  in every production construction (`desired_entry` handles None correctly,
  this line does not), so Windows editors get "gallery moved to
  P:\Assets\Stills/.gallery". The comp-ui-6 fix for macOS inverted the
  Windows case.
- **Recommendation:** `windows = self._windows if self._windows is not None
  else os.name == "nt"`, and use that value.
- **Known:** not recorded (comp-ui-6 is the parent fix).
