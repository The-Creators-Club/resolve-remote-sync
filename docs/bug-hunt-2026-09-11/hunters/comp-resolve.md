# comp-resolve - the companion's Resolve half: bridge, journal, script server, fixer, library, proxies, LUTs, BPG, Timeline Cards role

Files read (with approximate coverage):
- `companion/src/ccsync_companion/timeline_cards_role.py` (100%),
  `timeline_cards_bridge.py` (100%), `resolve_journal.py` (100%),
  `script_server.py` (diff + `classify`/`is_resolve_name`/`_darwin_tables`),
  `proxy_relink.py` (100%), `proxy_scan.py` (diff + `scan_project` /
  `scan_missing_proxies`), `luts.py` (diff + `copy_into_library` /
  `_is_under` / `LutLinkManager._report`), `bpg.py` (diff + escaping index),
  `project_setup.py` (diff), `fixer.py` (diff + `copy_with_progress`,
  `fix_clip`, `list_project_dirs`), `proxy_gen.py` (diff + `_publish` /
  `_discard` / `_brakes` / partial claim), `resolve_bridge.py` (~35%:
  `connect`, `_bridge_call`, `bridge_activity`, the library-walk half
  1238-1510, `replace_clip` / `link_proxy_media` diff), `library.py` (~40%:
  backends, `_connect` / `_reconnect` / `_retrying`).
- Cross-checked the wire: `dashboard/src/ccsync_dashboard/api.py`
  (`CardsAgentIn`, `_BoundedSectionIn`), `db.py` (`cap_cards_*`),
  `companion/src/ccsync_companion/consolidate.py` (`run_consolidation`),
  `app.py` (the consolidate + cards-role call sites).
- Full diff `097f5a3..HEAD` for every file in the territory.

Tests run:
- `cd companion; .venv\Scripts\python.exe -m pytest tests/test_fixer.py tests/test_proxy_relink.py tests/test_proxy_scan.py tests/test_resolve_journal.py tests/test_timeline_cards_role.py tests/test_timeline_cards_role_health.py tests/test_timeline_cards_bridge.py tests/test_script_server.py tests/test_luts.py -q` -> **388 passed**
- `... tests/test_resolve_bridge.py tests/test_resolve_bridge_launch_window.py tests/test_resolve_edit_safety.py tests/test_library.py tests/test_library_walk.py tests/test_proxy_gen.py tests/test_proxy_history.py tests/test_bpg.py tests/test_bpg_qt_escape.py tests/test_luts.py tests/test_project_setup.py tests/test_stills.py tests/test_resolve_prefs.py tests/test_resolve_undo_command.py tests/test_resolve_mapping_helper.py -q` -> **591 passed, 1 skipped**
- Three ad-hoc snippets from the companion venv (scratchpad), reproduced under Evidence below.

## Findings

### comp-resolve-1 - the copy read size ratchets down to 64 KB and never recovers
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/fixer.py:665-679` (`copy_with_progress`, the `read_size` shrink), ledger text at `KNOWN_BUGS.md:12558-12570`
- What: RES-14 made the read size adaptive - a read slower than
  `POLL_MAX_SECONDS` (0.5 s) halves the next one, floor `MIN_CHUNK_BYTES`
  (64 KB). There is no path back up. `read_size` is monotonically
  non-increasing for the whole file, so one slow read early in a copy
  permanently sets the rest of that file's transfer to a smaller read, and a
  handful of slow reads floor it at 64 KB. The realistic trigger is the case
  the change was written for: the FIRST read of a Google Drive / OneDrive
  placeholder blocks while the file hydrates, so almost every placeholder
  copy is ratcheted on read #1 and finishes the remaining gigabytes in 64 KB
  requests over SMB, long after the source has become fast.
- Failure scenario: FIX ALL / CONSOLIDATE copies a 40 GB camera original off
  a cloud-backed or thinking SMB source. The first few reads stall, the read
  size drops 1 MB -> 512 KB -> ... -> 64 KB, and the remaining 39 GB is
  copied in ~640,000 round trips instead of ~40,000, with a `report()`
  callback (and therefore a UI publish) per 64 KB. The copy that RES-14 was
  supposed to make cancellable becomes materially slower on exactly the links
  that were already slow.
- Evidence: snippet against the real function with an instrumented reader and
  a fake clock in which only the FIRST read looks slow:
  `first 6 read sizes: [1048576, 524288, 524288, 524288, 524288, 524288]`,
  `last 3: [524288, 524288, 524288]` - it never returns to 1 MB. Note also
  that the ledger entry claims "`chunk_size` stays the unit of PROGRESS
  reporting, so the bar and the ETA are unchanged", while the code comment at
  `fixer.py:671-676` says the opposite and correct thing ("ONE REPORT PER
  READ"); the ledger's description of this change is wrong on that point.
- Ledger: new (the shrink itself is RES-14, recorded as FIXED; the missing
  grow-back is not recorded anywhere)
- Suggested fix: grow the read back towards `POLL_CHUNK_BYTES` after N
  consecutive reads that finished inside the budget (e.g. double it when a
  read completes in under `POLL_MAX_SECONDS / 4`), capped at
  `min(POLL_CHUNK_BYTES, chunk_size)`.

### comp-resolve-2 - CONSOLIDATE counts a FIX ALL rehearsal as files copied in
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/consolidate.py:467-468` and `:493-499`; `companion/src/ccsync_companion/app.py:3561-3586`; the change that caused it is `companion/src/ccsync_companion/fixer.py:1269-1288`
- What: RES-15 flipped `fixer.fix_clip`'s dry run from `ok: False` to
  `ok: True, dry_run: True` and taught `popup.summarize_fix_results` /
  `_fix_done` to read `dry_run`. `consolidate.run_consolidation` is the OTHER
  caller of `fix_clip` (through `popup.call_fix_clip`) and was not taught:
  it counts `copied = sum(1 for r in results if r.get("ok"))`, credits
  `batch_done += size` for every rehearsal, and publishes `fixed=copied`.
  `app.py`'s toast then computes `len(results) - len(failures) - len(skipped)`
  from the same `ok` flag. This is the same twin-miss shape as UI-5
  (2026-08-11), where `perform_fix_all` was fixed and `run_consolidation` was
  not, and the comment about that miss sits four lines above the defect.
- Failure scenario: an admin sets `fixer_dry_run = true` to rehearse on a
  machine whose `local_root` is in doubt, then runs tray > COPY THIS
  PROJECT'S MEDIA IN. The progress bar fills at full speed (sizes are
  credited for copies that never happened), the ETA is nonsense, and the
  final toast reads "Copy & upload finished." having reported 69 files copied
  in. Nothing was copied. The rehearsal mode exists precisely so an admin can
  trust that screen.
- Evidence: `run_consolidation` has no reference to `dry_run` anywhere
  (`grep -n "dry_run" consolidate.py` returns only the rclone `--dry-run`
  helpers, lines 91-277); `popup.py:199-262` is where the `dry_run` handling
  lives, and `app.py:3561-3586` reads only `ok` / `aborted`.
- Ledger: new (regression introduced by RES-15, recorded as FIXED at `KNOWN_BUGS.md:13379`)
- Suggested fix: in `run_consolidation`, exclude `r.get("dry_run")` from
  `copied` and from `batch_done`, publish a `rehearsal` count beside
  `fixed`/`skipped`/`failed`, and have `app.py`'s consolidate toast say
  "Rehearsal: nothing was copied" the way `summarize_fix_results` does.

### comp-resolve-3 - the Timeline Cards refusal loses its actionable half at the dashboard's 255-char cap
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/timeline_cards_role.py:523-529` (the sentence) and `dashboard/src/ccsync_dashboard/api.py:7716` (`CardsAgentIn.detail`, `max_length=255`)
- What: the standalone-agent refusal sentence is 247 characters BEFORE
  `describe_process(found)` is appended. `_BoundedSectionIn` truncates rather
  than rejecting (good - no 422), so the dashboard stores the first 255
  characters: 8 characters of the process description. RES-7 added
  `describe_process` specifically because "the refusal used to name a command
  line and nothing else, so 'stop it' meant 'find it yourself'" - and on the
  fleet grid, which is where an admin looks, that addition is invisible. The
  same cap eats the tail of the other long refusals: `check_contract`'s
  no-bridge-contract message (~330 chars, the part naming
  `BRIDGE_CONTRACT_VERSION` and the doc section is cut) and `load_engine`'s
  import failure (the exception text is cut).
- Failure scenario: an editor leaves `reorder_web.py --agent` running on
  creator-1 and turns `cards_agent` on. The tray log has the pid and command
  line; the dashboard's fleet grid shows "... will pick the page up on its
  own within a minute. Found: python.e" and the admin cannot tell them what
  to close.
- Evidence:
  - base sentence length measured at 247 (`len(base)` from the companion venv);
  - parsed through the real model in the dashboard venv:
    `companion detail len: 303` -> `stored len: 255`,
    `tail: 'its own within a minute. Found: python.e'`.
- Ledger: new (related to RES-6 at `KNOWN_BUGS.md:13202`, which introduced the field, and to RES-7's `describe_process`)
- Suggested fix: shorten the refusal so the process description leads (e.g.
  "A Timeline Cards process is already driving Resolve here: <described>.
  Close it and ..."), or raise `CardsAgentIn.detail` to 512 and keep the
  companion's own truncation below it. Either way the companion should
  truncate deliberately rather than letting the wire cap choose the cut.

### comp-resolve-4 - the cards watchdog never restarts a role whose loops died, because `_threads` is never cleared
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/timeline_cards_role.py:676-683` (`supervise_now`), `:561-563` (`_start`), `:619-644` (`_loop` / `_note_loop_end`)
- What: `supervise_now()` short-circuits on `if self._threads: return True`.
  `_loop` records `_loop_error` when a loop raises or returns but does NOT
  remove the thread from `self._threads`, and nothing else does either. So a
  role whose push and pull loops have both died still holds a two-element
  list of dead `Thread` objects, the RES-7 watchdog answers "running" for
  ever, and only a companion restart brings the page back. This is the exact
  "a list that nothing ever cleared" shape the RES-6 comment at
  `timeline_cards_role.py:90-95` complains about; RES-6 fixed the *reporting*
  (`health()` correctly says `stopped`) and RES-7 added the watchdog, but the
  watchdog gates on the uncleared list rather than on liveness.
- Failure scenario: the tunnel raises something the engine's five-retry
  answer does not swallow (a `TypeError` out of a changed `AgentClient`, a
  `MemoryError`, an engine bug). Both loops exit. Every other refusal in this
  file self-heals within a minute; this one does not, and the editor's phone
  shows a dead page until somebody restarts the tray.
- Evidence: snippet with an engine whose `push_loop`/`pull_loop` raise
  immediately:
  ```
  start -> True
  health: ('stopped', 'the push loop stopped: RuntimeError: boom')
  supervise_now -> True  (True means it thinks it is running)
  threads alive: [False, False]
  ```
- Ledger: new (related to RES-6 and RES-7, both recorded as FIXED)
- Suggested fix: in `supervise_now`, treat "no live thread" as down -
  `if any(t.is_alive() for t in self._threads): return True` - and have the
  restart path clear `_threads`, `_client`, `_engine` and `_loop_error` first
  (and stop the old engine if it exposes a stop), so a restart is a clean
  `_start()` and not a second engine beside the first.

### comp-resolve-5 - a journal tmp file orphaned by a kill is never swept, contrary to its own comment
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/resolve_journal.py:353-380` (`_tmp_path` / `_write`) and `:612-638` (`SWEPT_SUFFIXES` / `_sweep`)
- What: `_tmp_path` writes `<name>.json.tmp.<pid>.<tid>` and its docstring
  says "Not swept: `SWEPT_SUFFIXES` matches `*.json`, and a tmp that is left
  behind is unlinked by the writer that made it." The second half is only
  true for an exception - a process that dies between `open()` and
  `os.replace()` unlinks nothing, and `_sweep`'s `*.json` / `*.drp` globs do
  not match the tmp name, so it stays in `~/.ccsync/resolve_edits/<slug>/`
  for ever. This is not a theoretical kill: CR-93's `Tcl_AsyncDelete` abort
  and the 0.9.62 supervisor make "the companion died without a shutdown" a
  routine event on this codebase.
- Failure scenario: a tray that aborts during a FIX ALL burst leaves one
  ~1 KB orphan per incident, accumulating silently in the editor's home; the
  retention promise in `docs/RESOLVE_EDIT_SAFETY.md` ("journals and exports
  older than 60 days are swept") is not kept for them.
- Evidence: `SWEPT_SUFFIXES = ("*.json", "*.drp")`; the tmp name ends in the
  thread id, so neither glob matches. No other code path unlinks it.
- Ledger: new (the tmp-name scheme is comp-resolve-1 of bug-hunt-2026-09-03, recorded as FIXED)
- Suggested fix: add `"*.json.tmp.*"` to `SWEPT_SUFFIXES` (or sweep tmps on a
  shorter cutoff, e.g. one day, since nothing ever needs an old one).

### comp-resolve-6 - `_note_starting(None)` logs "script server has its host now" when Resolve has actually gone away
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/resolve_bridge.py:367-373` and `:409-426`
- What: `connect()` calls `_note_starting(None)` for the `ABSENT` phase (no
  script server at all), which is the same call the READY path makes. If the
  bridge was in the STARTING window and Resolve is then quit or crashes
  mid-launch, the next poll goes STARTING -> ABSENT and the log reads
  "resolve: script server has its host now - connecting (held off for 12.3s)"
  immediately before the connection does not happen. The two states are
  logged as the same event.
- Failure scenario: diagnosing a "Resolve hung on launch" report from a
  bundle, the log says scripting recovered at 14:02:11 when in fact Resolve
  died at 14:02:11 and nothing has connected since. CR-68 diagnoses are read
  out of this exact log line.
- Evidence: `_note_starting(None)`'s only branch logs "has its host now"
  whenever `_starting_since` is set, and both `connect()`'s ABSENT arm
  (line 372) and its fall-through to `scriptapp` (line 374) call it with
  `None`.
- Ledger: new (related to CR-68)
- Suggested fix: give `_note_starting` a third outcome - clear
  `_starting_since` silently (or log "Resolve went away during its launch
  window") on ABSENT, and keep the "has its host now" line for the arm that
  is about to call `scriptapp`.

## Coverage note

Not covered: `stills.py` and `resolve_prefs.py` were only skimmed (no
changes since 097f5a3 and no cross-file contract of their own);
`resolve_bridge.py` is 3,423 lines and I read roughly a third - the media
pool enumerators (1,600-2,200), `replace_clip`'s full retry ladder and the
bin/folder helpers (2,800-3,400) were not read line by line; `library.py`'s
SQL half (`_sequence_for_timeline`, `_tracks`, `timeline_items`,
`_folder_tree`) was not read; `bpg.py`'s Qt escaping was taken on the
strength of `test_bpg_qt_escape.py` rather than re-derived; `proxy_gen.py`'s
encode/verify path (1,200-1,760) was read only around `_publish` / rule 2.

What the suite does not cover, that I noticed:
- Nothing exercises `copy_with_progress`'s read-size adaptation at all
  (no test references `POLL_MAX_SECONDS`, `MIN_CHUNK_BYTES` or the `clock`
  seam) - finding 1 would not be caught.
- `consolidate.run_consolidation` has no `fixer_dry_run` test; the RES-15
  tests all go through `popup`.
- Nothing in `companion/tests` parses a `report_block()` through the
  dashboard's `CardsAgentIn`, so field-cap truncation (finding 3) is invisible
  from either side's suite.
- `test_timeline_cards_role*.py` never asserts what `supervise_now` does after
  a loop has died; it only asserts `health()`'s word.

## OUT OF TERRITORY

- `companion/src/ccsync_companion/consolidate.py:467-499` - the defect in
  comp-resolve-2 lives here rather than in `fixer.py`; recorded under my
  territory because `fixer.fix_clip`'s contract change is what broke it.
- `dashboard/src/ccsync_dashboard/api.py:7716` - `CardsAgentIn.detail`'s
  255-char cap is the other half of comp-resolve-3.
- `companion/src/ccsync_companion/proxy_gen.py:1169-1174` - `report()` now
  splices `**self._brakes()`, which adds a nested `reasons` dict of three
  ~150-char sentences into the reporter payload, directly under a comment
  that says this block must stay scalars-only so the reporter's size guard is
  never forced to drop the per-project map. Worth a look from whoever owns
  the reporter/report-size territory.
- `KNOWN_BUGS.md:12568-12569` - the RES-14 entry says "`chunk_size` stays the
  unit of PROGRESS reporting"; the code reports once per READ and its own
  comment says so. Ledger text, not code.
