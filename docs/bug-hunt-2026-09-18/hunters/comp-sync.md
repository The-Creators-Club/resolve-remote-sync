# comp-sync - the companion's sync lanes, selection, file moves, drive/root guards

Files read (with approximate coverage):
- `companion/src/ccsync_companion/sync/rclone_lane.py` (the 09-17 hunks in full:
  `_relocate_trashed`, `_local_destination`, `_move_out_of_trash`,
  `_count_relocations`, `_wait_with_watchdog`/`_wait_loop`/
  `seconds_since_child_progress`, the `_run` call site; ~40% of the rest)
- `companion/src/ccsync_companion/sync/server_locate.py` (100%)
- `companion/src/ccsync_companion/sync/syncthing_lane.py` (`_heal_missing_paths`,
  `_call`/`_get`/`_post`, `reconcile` down to the folder verdict; ~50%)
- `companion/src/ccsync_companion/sync/sequencer.py` (`seconds_since_heartbeat`,
  `_update_known_selection`, `rel_to_slug`, the upload-only plumbing; ~30%)
- `companion/src/ccsync_companion/sync/lane_guard.py` (`LaneBBreaker.note_pass`,
  `_count_relocations`, `_discount_relocations`, `note_in_flight`; ~35%)
- `companion/src/ccsync_companion/file_moves.py` (the whole 09-11b hunk plus
  `_cmp_key`/`_stem_key`/`rename_proxy_siblings_case_only`/ledger readers)
- `companion/src/ccsync_companion/sync/shared_folders.py`,
  `sync/syncthing_admin.py` (the 09-11b hunks only)
- `companion/src/ccsync_companion/app.py` `_project_rel_for_slug` + the lane
  wiring (read as the other end, reported under OUT OF TERRITORY where the fix
  belongs there)
- `dashboard/src/ccsync_dashboard/locate.py`, `api.api_locate_files`,
  `db.media_rel_key` (read as the other side of the wire, not reported on)
- `docs/HAND_MOVES_ON_THE_SERVER.md` §4a/§4b/§6, `KNOWN_BUGS.md` CR-268/278/279
- tests: `test_rclone_lane.py` (the whole relocation block), `test_sequencer.py`,
  `test_syncthing_lane.py`, `test_bug_hunt_2026_09_11b_comp_sync.py`

Tests run:
`companion\.venv\Scripts\python.exe -m pytest tests/test_rclone_lane.py
tests/test_sequencer.py tests/test_syncthing_lane.py tests/test_file_moves.py
tests/test_lane_guard.py tests/test_bug_hunt_2026_09_11b_comp_sync.py -q`
-> 413 passed, 1 warning (the warning is `test_sequencer.py`'s deliberate
"startup unpause exploded" thread exception).
Plus one ad-hoc script in the scratchpad against the real lane object (evidence
for comp-sync-1).

## Findings

### comp-sync-1 - lane B puts a file back at the exact path it just trashed it from, forever, while the server's inventory is stale
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/rclone_lane.py:3996-4045`
  (`_relocate_trashed`) and `:4055-4100` (`_local_destination`); the other side
  is `dashboard/src/ccsync_dashboard/locate.py:60-110`, which returns EVERY
  place including the one the file was deleted from.
- What: `_relocate_trashed` treats "the server's inventory holds exactly one
  place for this (basename, size)" as "it was moved there". It never checks
  whether that one place is the path this pass just trashed the file FROM.
  `nas_media` is the last completed inventory walk (up to `interval_inventory`
  old, and arbitrarily old if the walk is failing), so for the whole staleness
  window a file genuinely deleted on the NAS - or moved before the walk caught
  up - still appears at its OLD path. The companion then computes
  `dest = local_root / <project rel> / <server rel_path>`, which for the source
  project is bit for bit the path rclone just emptied, and `os.rename`s the
  file back out of `.ccsync-trash` into it. `docs/HAND_MOVES_ON_THE_SERVER.md`
  §4a states the intended contract precisely - "the answer is 'found elsewhere'
  for a move older than the last walk, and 'not found' otherwise" - and
  "elsewhere" is the word the code does not implement.
- Failure scenario: an editor (or the owner) deletes `Proxy/gold.mp4` on the
  NAS in project CCT/Season 1. Lane B's next pass sees it gone, moves the local
  copy into `.ccsync-trash`, then asks locate; the 14-minute-old inventory
  still lists it at `cct` / `Proxy/gold.mp4`; the companion renames it back into
  the project folder. The next pass trashes it again, asks again, restores it
  again. The deletion never lands, the log says "moved 1" every pass, and
  because every such file is counted as a relocation (`_moved_out_of_trash`
  feeds `_count_relocations`, which `LaneBBreaker._discount_relocations`
  subtracts) the breaker is blind to the whole event: a NAS folder wiped by
  accident is discounted to zero deletions for as long as the inventory has not
  refreshed. If the inventory walk is broken or the project's walk keeps
  failing, the loop never ends.
- Evidence: ad-hoc script in the scratchpad, using the suite's own
  `_lane_with_trash` / `_locator` helpers with a single place naming the SOURCE
  project and the source rel_path, run under `companion\.venv`:
  ```
  restored to the path rclone just trashed it from: True
  still in trash: False
  moved_out_of_trash: 1
  relocations counted: 1
  ```
  The relocation block of `companion/tests/test_rclone_lane.py:2113-2265` has a
  case for another project, for two places, for none, for an unsynced
  destination and for a path escaping the tree - and no case at all where the
  server's only answer is where the file already was, so nothing fails today.
- Ledger: new (CR-268b is BUILT; this is "CR-268b does not implement §4a's
  'found elsewhere'").
- Suggested fix: in `_relocate_trashed`, drop any `place` whose
  `(project_slug, rel_path)` resolves to the path the file was trashed from -
  i.e. compare `self._local_destination(place)` against
  `Path(self.local_root)/<this pass's project rel>/<rel>` (NFC-folded,
  `os.path.normcase`) and treat a place that equals it as "not found". A file
  whose only place is its own old path is exactly today's 0.9.72 deletion, and
  it must not count as a relocation for the breaker either.

### comp-sync-2 - CR-278's path-missing heal never runs on the machine shape its own docstring describes
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/syncthing_lane.py:671-684` (the
  `if not expected:` early return) vs `:711` (the `_heal_missing_paths(folders)`
  call) and `:373-411` (the docstring).
- What: `_heal_missing_paths` is documented as covering "Every configured
  folder, not just the selection: the shared asset libraries (assets-luts on
  leso's Mac) sit in the same error and no selection names them" - but it is
  invoked several branches below the `if not expected: return` short-circuit,
  where `expected` is `sequencer.expected_folder_slugs()`, i.e. ticked
  full-mode PROJECT slugs only (`sequencer.py:823` filters out upload-only, and
  shared/borrowed asset folders were never in that list). A machine whose
  selection currently names no full-mode project therefore takes the
  "no project folders to check yet" return and the heal is unreachable, which
  is precisely the machine whose only path-missing folder is an asset library.
- Failure scenario: an editor between projects (nothing ticked, or every tick
  upload-only) pulls the external SSD holding `assets-luts`, plugs it back in.
  Syncthing keeps the folder in `error: folder path missing` until its next
  hourly rescan or longer - the 07:24-to-12:50 symptom CR-278 was written for -
  and the heal that would clear it is never called. The same early return also
  fires whenever `expected_folder_ids_fn` transiently returns `[]` (a selection
  fetch that has not landed yet after a restart).
- Evidence: read of the three call sites above; `_heal_missing_paths` has no
  other caller (`grep -n "_heal_missing_paths" companion/src` -> definition and
  the single line 711). The CR-278 block in `tests/test_syncthing_lane.py`
  calls `_heal_missing_paths` directly, so it cannot see the gate.
- Ledger: "CR-278 does not fix the asset-library case it names".
- Suggested fix: move `config = self._get("/rest/config")` +
  `self._heal_missing_paths(folders)` above the `if not expected:` return (it
  needs no selection), or call the heal from the unreachable branch too.

### comp-sync-3 - `_move_out_of_trash` claims it can never overwrite; on macOS and Linux `os.rename` silently does
- Severity: medium
- Confidence: CONFIRMED (by the documented semantics of `os.rename`; not
  reproducible on this Windows rig)
- Where: `companion/src/ccsync_companion/sync/rclone_lane.py:4102-4119`.
- What: the docstring is explicit - "NOTHING here overwrites and nothing here
  deletes -- os.rename, never os.replace, so a destination that appeared
  between the check and the rename is a refusal rather than a file lost". That
  is true only on Windows. On POSIX (every Mac in the fleet, and the Linux
  container if this code is ever reused there) `os.rename` replaces an existing
  destination file silently and atomically; `FileExistsError` is a Windows-only
  behaviour. The `dest.exists()` guard above it is therefore a TOCTOU check, not
  the guarantee the comment sells, and the whole function is reached only on the
  path that is moving an editor's media around.
- Failure scenario: leso's Mac. Lane B pass for project A trashes
  `Proxy/gold.mp4`; locate says it is in project B; `dest.exists()` is False;
  before the rename, the lane B pass/express run for project B (or Syncthing,
  or the editor) writes `gold.mp4` at that path. `os.rename` destroys the
  freshly downloaded copy with the trashed one. Both are the "same" clip today,
  so the loss is silent - but the function's own contract says this case is
  impossible, so nothing anywhere re-checks it.
- Evidence: CPython docs for `os.rename`: "On Unix, if dst exists and is a
  file, it will be replaced silently if the user has permission." The code path
  runs on macOS (`sys.platform` is never consulted here).
- Ledger: new.
- Suggested fix: use `os.link(src, dest)` + `os.unlink(src)`, or open the
  destination with `O_CREAT|O_EXCL` first, or at minimum drop the claim from the
  docstring and accept the race in writing. `os.replace` is NOT the answer here.

### comp-sync-4 - a file moved into a BORROWED project has a home on this disk and is trashed anyway
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:4010-4027`
  (`_project_rel_for_slug`, iterates `sequencer.rel_to_slug`) against
  `companion/src/ccsync_companion/sync/sequencer.py:749-751` and `:800-803`
  (`rel_to_slug` deliberately excludes borrowed folders; `rel_to_slug_with_borrowed`
  is the one that includes them); consumed by `rclone_lane._local_destination:4065`.
- What: `_project_rel_for_slug` is lane B's answer to "do I sync the project the
  server says this file moved into?". It reads `rel_to_slug`, which by design
  holds only the machine's own selected projects - a borrowed folder lives in
  `_borrowed_rel_to_slug` and is reachable only through
  `rel_to_slug_with_borrowed()`. So a hand move into a project this machine
  borrows resolves to None and the file is left in `.ccsync-trash` as §4b's
  "no home on this disk", although the folder is right there and lane C will
  download the file again.
- Failure scenario: the owner drags a Proxy folder from an editor's own project
  into a project that editor borrows. The editor's copies go to the trash (14
  days) and are re-downloaded over the link instead of being renamed locally -
  the exact cost CR-268b was built to avoid, on a destination the machine does
  hold.
- Evidence: read of the three sites; `rel_to_slug`'s own comment at
  `sequencer.py:800-803` states the exclusion is deliberate for
  `_selected_project_rels`, which is why a new caller must use the other
  accessor.
- Ledger: new (related to CR-268b).
- Suggested fix: have `_project_rel_for_slug` consult
  `sequencer.rel_to_slug_with_borrowed()`, or fall back to it when the plain map
  misses.

### comp-sync-5 - the 09-11b fix pass wrote mojibake into two `file_moves.py` comments
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/file_moves.py:134` and `:206`.
- What: commit 34a3c8f re-encoded `Matej Šimalčík.mov` as
  `Matej Å imalÄÃ­k.mov` in the two comments that exist specifically to
  document CR-90's NFC/NFD rule - the text was decoded as latin-1 and re-encoded
  as UTF-8 by whatever wrote the file. Harmless at runtime (comments only, and
  no other file in the companion tree carries the sequence), but it destroys the
  worked example in the one place a future reader will look for it, and it is
  evidence that an editing tool in that pass was not UTF-8 clean.
- Failure scenario: none at runtime. A maintainer reading the CR-90 rationale
  reads a corrupted example.
- Evidence: `git diff 18e69f3..34a3c8f -- companion/src/ccsync_companion/file_moves.py`
  shows the two lines changed with nothing else on them;
  `grep -rn "ÄÃ­k" companion/src --include=*.py` matches only those two lines.
- Ledger: new.
- Suggested fix: restore the two comment lines to their pre-34a3c8f bytes.

### comp-sync-6 - the path-missing heal hardcodes `.stfolder` instead of the folder's own `markerName`
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/sync/syncthing_lane.py:402`.
- What: the "is the drive really back?" test is
  `os.path.isdir(os.path.join(path, ".stfolder"))`. Syncthing's marker name is a
  per-folder config field (`markerName`, present in the very `folder` dict this
  loop already holds) and the marker was a plain FILE in Syncthing before v1.0,
  so a folder configured with a custom marker, or created by an old Syncthing
  and never recreated, never heals. The `path` value is also used verbatim, and
  Syncthing stores a `~`-prefixed path unexpanded in its config, which
  `os.path.isdir` would never resolve.
- Failure scenario: a customer site whose Syncthing folders were created outside
  our installer sits in `folder path missing` after a drive return exactly as
  before CR-278, with no log line saying why (the heal simply `continue`s).
- Evidence: read of the loop; `grep -rn "markerName" companion/src server/*.py`
  -> no hits anywhere, so nothing in the product sets or reads it.
- Ledger: new (related to CR-278).
- Suggested fix: `marker = str(folder.get("markerName") or ".stfolder")` and
  accept a file as well as a directory; run `path` through
  `os.path.expanduser`.

## Coverage note

Not reached in the time box: `sync/repath.py`, `sync/borrowed_folders.py`,
`sync/syncthing_supervisor.py`, `drive_swap.py`, `drive_reminder.py`,
`root_guard.py`, `manifest.py` and `selection.py` beyond a targeted grep - none
of them changed in either of the two diffs the brief names, but none has been
read this hunt. Of `rclone_lane.py` I read the 09-17 hunks and their neighbours
closely and sampled the filter-building half; the filter rules are pinned by
`test_rclone_filters.py` and I did not re-derive them.

What the suite does not cover, beyond comp-sync-1's missing case: nothing
exercises `_relocate_trashed` against a real `.ccsync-trash` on a case-
insensitive or NFD filesystem (every relocation test runs on this Windows rig);
nothing exercises `_heal_missing_paths` through `reconcile()` (only directly),
which is why comp-sync-2's gate is invisible; and there is no test in which the
locate call is slow, so the 10 s per-pass cost of asking on EVERY pass that
trashed even one file - the module docstring's "at most once per lane B pass",
which is once per pass per PROJECT scope - is unmeasured.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/locate.py:88`: the size prefilter selects every
  `nas_media` row with a matching size across every active project before the
  Python basename match, so a lane B pass that trashes 100 one-byte or
  identically-sized sidecars makes the container walk a large slice of the
  inventory table; KNOWN_BUGS CR-268b already owes "a basename column or index
  on `nas_media`". dash-api / dash-db.
- `companion/src/ccsync_companion/app.py:4010`: see comp-sync-4 - the fix for a
  lane B contract lives in comp-app's file.
