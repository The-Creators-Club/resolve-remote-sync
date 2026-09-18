# res-companion - what an editor's MACHINE does when things go wrong, traced across files

Files read (with approximate coverage): `git diff` over
`companion/src/ccsync_companion/` in full for the resilience-bearing modules -
`file_moves.py` (100%), `sync/rclone_lane.py` (the relocation/stall/trash
hunks, ~100% of the diff), `broll_standins.py` (100%), `broll_server.py`
(the upgrade half, ~80%), `proxy_relink.py` (the geometry/fleet hunks, ~90%),
`app.py` (the file-move block, the media-tree generation/watchdog block, the
report fan-out, ~60% of the diff), `supervisor.py`, `upgrade.py`,
`sync/server_locate.py` (100% of their diffs), plus the unchanged callees the
paths cross: `file_moves.moved_to/record/record_intent/recent_excludes`,
`app._on_moved_clip_missing` / `_show_moved_clip_dialog`,
`watcher.poll_once`'s moved-clip arm, `sync/lane_guard.prune_trash`. Both
sides of `dashboard_version`, `standins_known`, `standins_owed` and the
`unreadable` locate key were read in `dashboard/src/ccsync_dashboard/api.py`
and `db.py` only far enough to judge the companion's reading of them.
Ledger sections read: `highs.md` / `companion-core.md` / `companion-media.md`
entries CR-282B, CR-283W/X/Y, CR-284 (stand-in half), CR-285AX.

Tests run: `companion\.venv\Scripts\python.exe <scratchpad>\t_res.py` (an
ad-hoc driver of `file_moves.apply_move` + `FileMoveLedger.record` +
`moved_to`, run from `companion/` with `src` on `sys.path`; output quoted in
res-companion-1). No suite was run.

## Findings

### res-companion-1 - a move into a project this machine does not sync offers the editor a one-click relink of Resolve INTO the lane B trash
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/file_moves.py:464-489` (the section 4b
  branch writes `record_intent(move, src, trash)`), `file_moves.py:616-620`
  (`record()`'s `elif previous.get("old_local")` carry-over),
  `companion/src/ccsync_companion/app.py:8174-8181` (`record(..., paths=paths)`
  with `paths is None`), consumed at `file_moves.py:moved_to` and
  `app.py:8390-8430` (`_on_moved_clip_missing` / `_show_moved_clip_dialog`).
- What: the 4b branch writes an INTENT row whose `new_local` is the
  `.ccsync-trash` path before it moves the file, then returns `paths=None`
  precisely so nothing relinks Resolve there. But `FileMoveLedger.record()`
  falls back to the previous row's `old_local`/`new_local` when `paths` is
  falsy, so the completion row inherits the trash path, with
  `state="not_synced_here"` (which `moved_to` does not filter) and a fresh
  `at`. The comment in `apply_move` ("paths=None on purpose ... a relink to
  the trash would be worse than the offline clip") and CR-283Y's own
  verification text ("with no paths, so nothing relinks Resolve to a file in
  the trash") are both defeated by the carry-over.
- Failure scenario: an admin moves `2026/A/Media/clip.mov` to project `2026/B`,
  which this editor does not sync. The companion trashes its local copy and
  answers "trashed locally, destination not synced here". The editor opens
  project A in Resolve; `watcher.poll_once` sees the clip missing, asks
  `moved_to(old path)`, gets the row, and `_on_moved_clip_missing` fires a
  tray notification plus the dialog "CCSync can repoint Resolve to where it is
  now". `_moved_destination_is_there` passes (the trash file exists), so the
  editor clicks and every clip under that path is written, through
  `replace_clip` with an undo journal, to
  `<local_root>/.ccsync-trash/<stamp>/...`. `lane_guard.prune_trash` deletes
  that batch after `DEFAULT_TRASH_MAX_AGE_DAYS = 14`, while
  `RELINK_WINDOW_SECONDS` keeps the offer alive for 30 - so the clips become
  permanently Media Offline, pointing at a path that no longer exists, and
  lane B will never fetch a file there.
- Evidence: run from `companion/` with the component venv:
  ```
  apply: True trashed locally, destination not synced here None
  entry new_local: ...\tree\.ccsync-trash\20260918-142454\Projects\2026\A\Media\clip.mov
  moved_to(src) -> ...\tree\.ccsync-trash\20260918-142454\Projects\2026\A\Media\clip.mov
  ```
  (`project_rels=["2026/A"]`, destination `2026/B`; the third line is exactly
  what the watcher hands `_on_moved_clip_missing`.) `moved_to` skips only
  `STATE_APPLYING` rows, and `_moved_destination_is_there` returns True for any
  path that exists.
- Ledger: CR-283Y does not fix res-fleet-3 (it opens this neighbour); the
  carry-over itself is older, but nothing before 4b ever passed `paths=None`
  after writing an intent row.
- Suggested fix: in the 4b branch either do not write an intent row at all
  (nothing about it is resumable - the trash path is not a destination
  anything retries) or clear the paths on completion: have `app._apply_file_moves`
  pass an explicit sentinel, or make `record()` drop `old_local`/`new_local`
  when the state is `STATE_NOT_SYNCED_HERE`. Belt and braces: make `moved_to`
  skip `STATE_NOT_SYNCED_HERE` rows the way it skips `STATE_APPLYING`.

### res-companion-2 - the file-move ledger became multi-threaded today and has no lock; two `_save()`s share one tmp path
- Severity: high
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (frequency)
- Where: `companion/src/ccsync_companion/file_moves.py:592-627` (`FileMoveLedger`:
  no `threading.Lock` anywhere in the class; `_save` writes a single fixed
  `file_moves.json.tmp`), wired at `companion/src/ccsync_companion/app.py:2475`
  (`on_relocated=self.file_moves.record_relocation`) against
  `app.py:8032` (`_apply_file_moves`, "reporter thread") and `app.py:2427`
  (`extra_excludes_fn=self.file_moves.recent_excludes`, lane A's thread).
- What: res-companion-2's fix hands the LANE thread a writer into a ledger
  that until today was written only by the reporter thread.
  `RcloneLane._relocate_trashed` -> `_note_relocated` -> `record_relocation`
  mutates `self._relocations` and calls `_save()` on the sequencer/lane thread,
  while `_apply_file_moves` -> `record_intent` / `record` mutates
  `self._entries` and calls `_save()` on the reporter thread. Both `_save()`
  calls `write_text` on the same `file_moves.json.tmp` and then `replace` it;
  interleaved they produce a truncated or doubly-written tmp that is then
  promoted to the live ledger, and the loser's `replace` raises
  `FileNotFoundError` (caught, logged, lost).
- Failure scenario: lane B follows a hand move (one `record_relocation` per
  relocated file, up to rclone's 100 per pass) at the same moment the reporter
  applies a `file_moves` command. The ledger on disk becomes invalid JSON.
  Nothing notices while the process runs (`_load` is called once, in
  `__init__`), so the next restart - which after a crash is the ONE case the
  whole `applying`/intent design exists for - reads `[]`: every `applying`
  intent row is gone, so `apply_move`'s resume arm can never fire
  (res-companion-1's 2026-09-11 fix is void), `moved_to` offers nothing, and,
  worst, `recent_excludes` returns no paths - so lane A, which never deletes,
  re-uploads the file to the old path on the NAS, which is the single failure
  `docs/FILE_MOVES.md` exists to prevent.
- Evidence: `grep -n "Lock\|threading" companion/src/ccsync_companion/file_moves.py`
  returns nothing. `_save` (file_moves.py:613) uses
  `self._path.with_suffix(".json.tmp")` - one path, no pid, no uniqueness.
  `app.py:2475` is a new line in today's diff; at `git show HEAD:...app.py` the
  only callers of the ledger were `_apply_file_moves` (reporter) and the
  read-only `recent_excludes` / `moved_to`.
- Ledger: CR-282B opens this neighbour (new).
- Suggested fix: give `FileMoveLedger` an `threading.RLock` taken by
  `record`, `record_intent`, `record_relocation`, `relocation_to`, `moved_to`
  and `recent_excludes` (the reads iterate the same lists), and make `_save`'s
  tmp name unique per call (`.{os.getpid()}.{id}.tmp`) so a lost race cannot
  publish a half file. A validating `_load` that renames an unparseable ledger
  aside and logs it would also stop the silent `[]`.

### res-companion-3 - a stand-in whose drive or share is momentarily unreachable is FORGOTTEN, not deferred
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_standins.py:314-340`
  (`StandinLedger._prune_locked`, new today) with `_size_of`
  (broll_standins.py, `except OSError: return None`).
- What: the prune retires an entry when it is older than
  `PRUNE_AFTER_SECONDS` (30 days) AND `_size_of(local_path) is None`. But
  `_size_of` answers None for every `OSError`, which includes "the external
  sync drive is unplugged" (CR-92's routine case), "the SMB share stopped
  answering" (the wired rig's `P:`), and "access denied". The docstring's
  justification - "a path with no file has been deleted, moved or re-synced by
  some other route" - is a statement about ABSENCE, and the code cannot tell
  absence from unreachability. `_prune_locked` runs inside `_load_locked`, i.e.
  on every ledger operation, and the next write persists the loss.
- Failure scenario: an editor's b-roll archive lives on the external sync drive
  CR-92 is about. They unplug it, and a `set_upgrade`/`record` happens while it
  is out (the 120 s relink cycle calls `resume_pending_upgrades`, an insert, the
  report's `placed_report()` -> `all()`). Every stand-in entry placed more than
  30 days ago is dropped. When the drive comes back, the clips in Resolve are
  still the 1080p preview under a 6K name, but `is_stale` no longer knows them,
  `given_up_upgrades` no longer warns, and `placed_report` no longer tells the
  fleet - so the wired rig's proxy-tiers-4 shortcut loses exactly those rels
  and the "cutting on a preview" fact is gone from every surface.
- Evidence: `_size_of` catches `OSError` and bare `Exception` and returns None
  in both; `_prune_locked` treats that as "the file is gone". `_entry_is_stale`
  (unchanged) deliberately returns False for an unreadable file, which is the
  opposite reading of the same call in the same module.
- Ledger: CR-284 / comp-broll-tiers-5 does not fully fix its own scenario (new
  neighbour).
- Suggested fix: distinguish the two. Prune only when the file's PARENT
  directory is readable and the file is absent (`os.path.isdir(parent) and not
  os.path.exists(path)`), or when `local_root` is present at all - the same
  `_local_root_is_broken()` / `root_guard` test the rest of the companion uses
  before it concludes anything from a missing path.

### res-companion-4 - a retired media-tree thread keeps stamping the heartbeat its replacement is judged by
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:4674-4681`
  (`_stamp_media_tree_heartbeat`), `app.py:4625-4640` (`on_probe=` wiring),
  `app.py:9498-9509` (`_abandon_media_tree_thread`).
- What: `abandon()` only bumps the generation; the wedged thread keeps running
  until its current pass returns, and the generation is checked only at the top
  of the loop and after the pass. Anywhere inside that pass the OLD thread can
  still call `on_probe` -> `_stamp_media_tree_heartbeat`, which writes the one
  `self._media_tree_heartbeat` the watchdog reads.
- Failure scenario: the share unwedges after 40 minutes; the retired thread
  resumes its ffprobe loop and stamps the heartbeat every clip while the NEW
  media-tree thread is itself stuck. `LaneWatchdog` reads a fresh heartbeat and
  concludes the media tree is healthy, so the wedge that res-companion-4 was
  built to catch is masked for the length of that pass.
- Evidence: `_media_tree_loop` checks `generation != self._media_tree_generation`
  at the loop top and after `_refresh_media_tree_once()` only;
  `_stamp_media_tree_heartbeat` takes no generation argument and writes the
  shared attribute unconditionally.
- Ledger: related to CR-279 / res-companion-4 (today's fix; this is the residue).
- Suggested fix: bind the stamp to the generation - pass the loop's generation
  into the `on_probe` closure and have it write only while
  `generation == self._media_tree_generation`. The same guard belongs in
  `_media_tree_loop`'s own `self._media_tree_heartbeat = time.monotonic()`.

### res-companion-5 - `standins_known`: the code never sends the empty list its two comments promise
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9864-9873` (`if known:`),
  `dashboard/src/ccsync_dashboard/db.py:8869-8880` (docstring),
  read by `companion/src/ccsync_companion/proxy_relink.py:441-478`.
- What: both comments state that an empty list IS sent, "so the two shapes
  cannot be confused"; `if known:` means it is not, and the key is simply
  absent. The companion's three-state reading collapses correctly to "ask the
  probe" either way, so nothing is broken today - but the next reader who
  trusts the comment and gives the empty list a distinct meaning (for example
  "the fleet has cleared every stand-in, drop the cached set") will be writing
  against a shape that never arrives. The cached `_FLEET_STANDINS` is
  consequently never cleared for the life of the companion process.
- Failure scenario: none observable today; a stale True costs one `ReplaceClip`
  that changes nothing, as CR-284R notes.
- Evidence: `result["standins_known"] = {"rels": known}` is inside `if known:`.
- Ledger: new (documentation vs code).
- Suggested fix: either send `{"rels": []}` unconditionally, as both comments
  say, or correct both comments to say the key is absent when the set is empty.

## Coverage note
Not reached: the ytdl/jobs failure paths (`ytdl_executor.py`,
`jobs_runner.py`), `drive_reminder.py` / `drive_swap.py` under a pulled drive
(comp-sync owns the files and the diff there was small), the Tk/`ui_dispatch`
crash paths (comp-ui), and `timeline_cards_role.py`'s restart handshake. I did
not exercise a real kill-mid-write: res-companion-2's corruption window is
argued from the code, not reproduced. The companion suite has no test that runs
two threads against one `FileMoveLedger`, and none that asserts
`moved_to()` refuses a `not_synced_here` row - `test_file_moves.py`'s new 4b
tests all assert on `apply_move`'s return value, never on the ledger row that
`app._apply_file_moves` then writes, which is exactly why res-companion-1
survived the fix wave.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/file_moves.py:632-655`: `record_relocation`
  calls `_save()` per relocated file, rewriting up to 700 JSON rows per file
  for a pass that can carry 100 - batch it at the end of `_relocate_trashed`
  (comp-sync).
- `companion/src/ccsync_companion/broll_server.py:1395-1408`: a single
  `STATE_FAILED` from `broll_fetch` (NAS down for one poll) marks the
  editing-proxy upgrade `failed` for ever; only a re-insert re-arms it, and
  `pending_upgrades()` excludes it (comp-broll-tiers).
- `companion/src/ccsync_companion/sync/rclone_lane.py:326-338`:
  `_stall_age_seconds` is wall-clock, so a clock that jumps forward more than
  24 h silently clears a current stall claim (comp-sync).
