# comp-sync — companion sync lanes, guards, selection, file moves, drive/root guards

Files read (with approximate coverage):
- `companion/src/ccsync_companion/sync/lane_guard.py` (100%)
- `companion/src/ccsync_companion/sync/repath.py` (100%)
- `companion/src/ccsync_companion/sync/shared_folders.py` (100%)
- `companion/src/ccsync_companion/sync/borrowed_folders.py` (~60%)
- `companion/src/ccsync_companion/sync/base.py` (100%)
- `companion/src/ccsync_companion/canon.py` (100%)
- `companion/src/ccsync_companion/file_moves.py` (100%)
- `companion/src/ccsync_companion/drive_reminder.py` (100%)
- `companion/src/ccsync_companion/selection.py` (100%)
- `companion/src/ccsync_companion/sync/rclone_lane.py` (~45%: filter rules, all three
  argv builders, `_build_command`, `run_once`/`_run_once_locked`, express queue/
  partition/flush, relocation probe, `check_remote_root`, trash/backup dir)
- `companion/src/ccsync_companion/sync/sequencer.py` (~30%: sync-mode helpers,
  `_item_is_valid`, pass loop, `_process_project`, `_run_lanes_a_and_b`,
  `_update_known_selection`, startup ignores verification)
- `companion/src/ccsync_companion/drive_swap.py` (~40%), `root_guard.py` (~35%)
- `companion/src/ccsync_companion/sync/syncthing_admin.py` (accept_folder only)
- Docs: CLAUDE.md, docs/FILE_MOVES.md (via module docstrings), delete-protection
  doc, KNOWN_BUGS CR-90/CR-94/RES-1/RES-10/SYNC-3/SYNC-11/SYNC-13/SYNC-16/YT-3.

Tests run:
`companion/.venv/Scripts/python.exe -m pytest tests/test_borrowed_folders.py
tests/test_canon.py tests/test_drive_reminder.py tests/test_drive_swap.py
tests/test_file_moves.py tests/test_lane_b_resume_requests.py tests/test_lane_guard.py
tests/test_lane_watchdog.py tests/test_rclone_lane.py tests/test_rclone_lane_races.py
tests/test_repath.py tests/test_root_guard.py tests/test_selection.py
tests/test_sequencer.py tests/test_shared_folders.py tests/test_sync_halt.py
tests/test_sync_sequencer_policy.py tests/test_syncthing_admin.py
tests/test_syncthing_lane.py tests/test_syncthing_supervisor.py -q`
-> **859 passed** (44.95 s), i.e. everything below is a gap the suite does not cover.

## Findings

### comp-sync-1 — the express lane A door does not implement YT-3's ytdl work-file excludes (nor the file-moves excludes), so it uploads exactly the half-made files the periodic pass refuses
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/rclone_lane.py:1671-1695`
  (`path_matches_lane_a_filter`) vs `:566-599` (`build_filter_rules_up`, which
  emits `YTDL_WORK_EXCLUDE_RULES` and the `extra_excludes_fn` rules); the express
  gate is applied at `:4463` and `:4737`, and `_build_command`'s exclusion work at
  `:2680-2694` never reaches `build_express_command` (`:1759`, no filter flags by
  construction).
- What: `path_matches_lane_a_filter` is documented as the Python re-implementation of
  `build_filter_rules_up()` and "must stay equivalent to the rule list", but it only
  checks (a) video extension, (b) no `Proxy` component, (c) no `._` AppleDouble
  prefix. It implements neither `YTDL_WORK_EXCLUDE_RULES` (`- *.editready.*`,
  `- *.original.*`, `- *.temp.*`, `- *.f[0-9][0-9][0-9]*.*`, `- *.failed`) nor the
  `file_moves.recent_excludes` rules that `_build_command` injects for lane A. The
  express run cannot carry a filter file (rclone refuses `--filter-from` with
  `--files-from-raw`), so this predicate is the *only* gate — and express is
  `copy --ignore-existing`, i.e. whatever it lands on the NAS first is permanent.
- Failure scenario: an editor's ytdl download finishes and `_ensure_edit_ready`'s
  libx264 pass starts. `Interview.original.mp4` (the VP9/AV1 source) and
  `Interview.f137.mp4` (the yt-dlp per-format fragment) sit unchanged on disk for the
  minutes-to-hours the conversion takes, so they pass the express gate's two
  size-stable observations and the 120 s min-age. Express uploads both to the NAS,
  where lane A's `--ignore-existing` means nothing ever replaces or removes them.
  Second half: a file the dashboard has told this machine to keep out of lane A
  (a refused/blocked `file_moves` entry, whose local copy is still at the old path)
  is re-uploaded to the path the admin just cleared the moment anything touches it —
  the exact failure `docs/FILE_MOVES.md` exists to prevent, through the other door.
- Evidence: run from the companion venv:
  ```
  2026/X/clip.editready.mp4 True
  2026/X/clip.original.mov  True
  2026/X/vid.f137.mp4       True
  2026/X/a.temp.mp4         True
  build_filter_rules_up()[:8] == ['- ._*', '- **/Proxy/**', '- /Proxy/**',
    '- *.editready.*', '- *.original.*', '- *.temp.*',
    '- *.f[0-9][0-9][0-9]*.*', '- *.failed']
  ```
  `tests/test_rclone_filters.py:1908` and `:1926` prove the *periodic* pass excludes
  all five families (twice, once against the real binary), and
  `tests/test_rclone_express.py:506-513` exercises `path_matches_lane_a_filter` with
  only `.mov`/`.MOV`/`notes.txt`/`Proxy/` cases — so the suite pins the equivalence
  claim on one side and never tests the other. Note the 0-byte floor (COMP-GUARD-1)
  *was* correctly mirrored into `_express_partition` (`st.st_size <= 0`), which shows
  this mirroring is the established pattern and YT-3 simply missed it.
- Ledger: new (adjacent to YT-3 and SYNC-13, neither of which mentions the express
  predicate; `grep -n express KNOWN_BUGS.md` finds only SYNC-13).
- Suggested fix: add the five ytdl patterns to `path_matches_lane_a_filter` (a
  basename regex is enough) and give `RcloneLane` an express-side consult of
  `extra_excludes_fn(None)` before writing the `--files-from-raw` list; extend
  `test_rclone_express.py` with the YT-3 names so the equivalence is pinned on both
  sides.

### comp-sync-2 — `file_moves._cmp_key` folds case but not Unicode, so a Mac never recognises its own moved file when the name carries a diacritic
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/file_moves.py:110-124` (`_cmp_key`), used by
  `moved_to()` (`:296`), `_same_file` and `_is_inside`; consumer at
  `companion/src/ccsync_companion/watcher.py:339-347`.
- What: `_cmp_key` is `os.path.normcase(os.path.normpath(x))` plus a `.lower()` on
  darwin (the CR-94 fix). It performs no Unicode normalisation. `moved_to()` compares
  the ledger's `old_local` — built from the dashboard's **NFC** `from_rel` — against a
  path that came out of Resolve, which on macOS is **NFD** (`resolve_bridge._nfc`
  exists for precisely this reason, and `recent_excludes` in this same file emits both
  spellings for SYNC-11). CLAUDE.md's CR-90 rule says exactly this: "Compare through a
  normaliser ... normalise on the way IN for a value that is only ever compared".
- Failure scenario: an admin moves `Projects/2026/A/Matej Šimalčík.mov` on the server.
  A Mac editor's companion applies the move and records the ledger entry. Next time
  that project is open, the clip is MISSING in Resolve; the watcher asks
  `moved_to(<NFD path from Resolve>)`, gets `None`, and the RES-10 one-click relink is
  never offered — the clip looks like a mystery offline clip forever. CJK names never
  warn you (no decomposed form), so this reproduces only on accented Latin names.
- Evidence: snippet from the companion venv against the real `FileMoveLedger`:
  ```
  NFC lookup: True
  NFD lookup: False
  ```
  (record written with the NFC spelling, queried with the NFD one).
  `tests/test_file_moves.py` has no NFD case — CR-94's fix added case folding only.
- Ledger: new; same family as CR-90, and a gap left by CR-94's `_cmp_key` fix.
- Suggested fix: `folded = unicodedata.normalize("NFC", str(path))` before the
  normcase/normpath in `_cmp_key` (it is a comparison key only, so this is safe under
  CLAUDE.md's rule), and add an NFD lookup case to `tests/test_file_moves.py`.

### comp-sync-3 — a lane A run over a BORROWED subtree drops every file-moves exclusion
- Severity: low
- Confidence: CONFIRMED (by reading both sides)
- Where: `companion/src/ccsync_companion/sync/sequencer.py:1743` (`self._run_lanes_a_and_b(sub, budget)`
  with `sub = "Projects/<lender_rel>/<inc_subpath>"`) and
  `companion/src/ccsync_companion/file_moves.py:321-366` (`recent_excludes`).
- What: `recent_excludes(subpath)` strips a leading `Projects/` and then requires
  `from_project_rel.lower() == subpath.lower()`. For a borrowed include the subpath is
  `<lender_rel>/<sub_rel>`, which can never equal a project rel, so the function
  returns `[]` and the run carries no move exclusions. It also returns `[]` for
  `subpath=None` (a whole-tree lane A run) for the same reason — reachable only in
  unmanaged mode today, where there is no dashboard to issue moves.
- Failure scenario: the admin moves a file inside a lender's project that a borrower
  is syncing a subtree of. The borrower's lane A run for that include re-uploads its
  copy at the old path, undoing the move on the NAS. Low because lane A on a borrowed
  subtree is `copy --ignore-existing` of a subtree the borrower normally only reads.
- Evidence: `_run_lanes_a_and_b(sub, budget)` at sequencer.py:1743 passes no
  `upload_only` and the include subpath is two levels deep; `recent_excludes`'s only
  match key is `from_project_rel`.
- Ledger: new (RES-1 / SYNC-11 cover the per-project case only).
- Suggested fix: make `recent_excludes` match on a project-rel PREFIX of `subpath` and
  re-express `from_rel` relative to the run root, instead of demanding equality.

### comp-sync-4 — `borrowed_folders._repoint` leaves the folder paused for an extra pass because `_reconcile_one` decides the unpause from a stale config
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/borrowed_folders.py:221-243` (`_repoint`
  pauses and never unpauses) and `:190-219` (`_reconcile_one` tests
  `folder.get("paused")`, from the dict fetched *before* the repoint).
- What: `_repoint` calls `set_folder_paused(slug, True)`, moves the dir and
  `set_folder_path(...)`, and returns without unpausing. Back in `_reconcile_one` the
  unpause branches read the pre-repoint `folder` dict, so on a lender that was running
  they see `paused=False` and do nothing. The folder therefore stays paused until the
  next reconcile pass observes `paused=True`. `sync/repath.py:243-247` (the analogous
  project path) explicitly unpauses in the same function.
- Failure scenario: a lender project is moved on the NAS; the borrower's shared subtree
  stops syncing for one sequencer pass (up to `sequencer_idle_seconds` +
  a full rotation) with no line saying why, then silently resumes.
- Evidence: read both functions; `tests/test_borrowed_folders.py` passes because it
  never asserts the paused state immediately after a repoint.
- Ledger: new.
- Suggested fix: have `_repoint` return a flag (or unpause itself, gated on
  `halted()` and confirmed ignores) rather than leaving the decision to a stale dict.

## Coverage note
Not covered: `sync/syncthing_supervisor.py` (read only its outline),
`sync/syncthing_lane.py` beyond the API-key/status surface, most of
`sync/syncthing_admin.py`, the second half of `sync/borrowed_folders.py`
(`_drop_unborrowed`, `restricted_ignore_lines`), `root_guard.probe_root`'s darwin
misplaced-volume path, the whole `drive_swap` Win32 half, and roughly 55% of
`rclone_lane.py` (the JSON-log parser, orphan `.partial` scan, watchdog, trash
notification). The suite has no NFD test anywhere in this territory, and no test
that drives the express lane against the ytdl work-file names (comp-sync-1) — those
are the two blind spots I would close first.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/app.py:4304-4305, 4345, 4416`: the tray/report
  side computes `upload_only` as `sync_mode == "upload_only"`, so an UNKNOWN
  `sync_mode` reads there as **full** — the opposite of `sequencer._item_sync_mode`'s
  deliberate fail-closed (`None` -> the item is not synced at all). Two readers of
  the same field disagree on the unknown value.
- `companion/src/ccsync_companion/sync/syncthing_admin.py:493-552` /
  `shared_folders._accept`: the docstring claims the offering device is checked
  against devices this machine is paired with; no such check exists in either
  function (Syncthing's own pending-folder semantics probably make it moot).
