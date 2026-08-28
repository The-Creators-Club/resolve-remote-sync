# DaVinci Resolve integration (RES)

## Summary
This is the most defensively-written area of the repo: every media-pool write goes
through `replace_clip`/`link_proxy_media` with a save point + undo journal, the copy
path has O_EXCL reservations, `.ccsync-tmp` + `os.replace`, a post-copy verify before
any relink, and CR-68's script-server probe is a genuinely novel guard. The residual
risk is not in the mutation primitives but in **what happens after they fail or are
never reached**: the unprompted-rewrite rate limiter is in-memory only (the one thing
CLAUDE.md says never to do with a safety latch), the undo journal has a duplicate-clip
bug that reports success while leaving a clip un-restored, a dashboard-driven file move
that Resolve blocked is refused *permanently* and then re-uploads itself after 24 h, and
the companion launches BPG (`Resolve.exe -pg`) without ever consulting the CR-68 guard
that the same companion carries. The biggest single risk is RES-1 (permanent file-move
refusal quietly undoing an admin's move). The best cheap win is RES-3: `bridge_activity()`
was built lock-free "for a status reader" and no status reader reads it - wiring it into
the tray line and the report makes a wedged Resolve visible fleet-wide for ~20 lines.

## Findings

### RES-1: a file move Resolve blocked is refused forever, then re-uploads itself
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/app.py:4929-4943`, `file_moves.py:119-141,190-210`
- **Scenario:** admin uses [ MOVE ON THE SERVER AND ON EVERY MACHINE ]. On the editor's
  machine the file (or its proxy) is open in Resolve; per `docs/GOTCHAS.md` Resolve holds
  media without share-delete, so `src.replace(dest)` raises `PermissionError`.
- **Today:** `apply_move` returns `(False, "could not move it on this machine: ...")`;
  `self.file_moves.record(move, ok=False, ...)` writes it to the ledger unconditionally
  (app.py:4943). Every later report finds `entry(move_id)` non-None (app.py:4929) and
  simply re-answers the old failure - the move is **never retried**, even after Resolve
  closes. `recent_excludes` keeps the old path out of lane A for 24 h; after that lane A
  re-uploads the file to the old path and the admin's server-side move is undone.
- **Proposed:** record failures as `retryable` with an attempt count and next-attempt
  stamp, and re-attempt on each report (cap ~20 attempts / 7 days) instead of latching.
  Extend the exclusion window while a move is still pending rather than expiring it into
  a re-upload. A move that exhausts its attempts should report a distinct
  `blocked` state the dashboard can show, not a silent success-shaped answer.
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** CR-87 (built, unshipped), `docs/FILE_MOVES.md`

### RES-2: the unprompted-rewrite rate limiter lives only in RAM
- **Lens:** pitfall
- **Where:** `resolve_journal.py:91-98,133-163`, `app.py:2041`, `app.py:3244`
- **Scenario:** a machine with a wrong `canonical_prefix`/`local_root` auto-relinks a
  project, then the tray restarts - an OTA/auto-update, an EULA park, a crash, the editor
  quitting and reopening the tray, a self-upgrade.
- **Today:** `_automatic_at` / `_save_points` / `_sessions` are module globals. A restart
  resets all three, so the 15-minute bar on the two **unprompted** project-database
  rewrites is gone: each launch may rewrite hundreds of clip paths again. CLAUDE.md's own
  rule is "Never make a safety latch in-memory-only" (lane B's breaker is on disk for
  exactly this reason).
- **Proposed:** persist `{project slug: {source: last_ts}}` to
  `~/.ccsync/state/resolve_auto.json` (wall clock, tolerate skew by treating a future
  stamp as "now"), loaded lazily in `allow_automatic`. Add a per-day cap as well as a
  per-15-minute one, so a machine that is wrong all day rewrites at most N times and logs
  "held N clips - this looks like a configuration problem, tray -> Copy diagnostics".
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** item 9 / `docs/RESOLVE_EDIT_SAFETY.md`; lane B breaker `sync/lane_guard.py`

### RES-3: nothing reads `bridge_activity()` - a wedged Resolve call is invisible
- **Lens:** safeguard
- **Where:** `resolve_bridge.py:152-166` (docstring: "cheap enough for a status reader"),
  only consumer is `tray_native.py:400-414` inside a slow-click WARNING
- **Scenario:** `ImportMedia` or a media-pool walk hits a P: mapping that has gone away.
  The native call never returns; it holds `_API_LOCK` and every other Resolve thread parks.
- **Today:** one WARNING every 5 minutes in a 5 MB-rotating log (`_note_wedge`). The tray
  status line, the popup, and the dashboard report show nothing; `resolve_project` in the
  report just goes stale. The editor sees features silently doing nothing.
- **Proposed:** (a) tray line: "Resolve is busy (ImportMedia, 4 min) - CCSync is waiting";
  (b) add `resolve_bridge: {call, seconds}` to the reporter payload beside
  `resolve_project` (`reporter.py:509-515`) so the fleet page can flag a wedged machine;
  (c) once past a threshold, have the tray offer "Resolve is not answering - quit and
  reopen Resolve" rather than leaving the editor to guess.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** COMP-MEDIA-9; CR-70 (open, tray menu late)

### RES-4: the companion launches `Resolve.exe -pg` without asking its own CR-68 guard
- **Lens:** pitfall
- **Where:** `bpg.py:720-790` (`maybe_launch`), `bpg.py:11-16` ("BPG IS RESOLVE"),
  `script_server.py:110-141`
- **Scenario:** editor is away, ffmpeg queue empty, BRAW clips need BPG. The companion
  spawns `Resolve.exe -pg`. Minutes later the editor sits down and starts real Resolve.
- **Today:** `maybe_launch` checks enabled/command/queue/idle/cooldown and never calls
  `script_server.state()`. Two consequences, both the exact CR-68 failure shape: (1) if
  BPG brings up its own script server on 1144, the real Resolve that starts afterwards
  cannot get the port and gives up scripting for the whole session; (2) `classify()`
  matches a client by `name in _RESOLVE_NAMES` (`resolve.exe`), and BPG *is* resolve.exe,
  so a BPG-only machine reads as READY and `scriptapp("Resolve")` attaches to the wrong
  host.
- **Proposed:** refuse the BPG launch unless `script_server.state()` is `ABSENT` (no
  Resolve scripting anywhere) and no Resolve window is up; and record the spawned child's
  pid so `classify()` can exclude it from both the server-parent and the `_RESOLVE_NAMES`
  match. Log the refusal ("not starting the proxy generator while Resolve's scripting
  server is live") rather than starting anyway.
- **Effort:** M   **Severity:** high   **Confidence:** med
- **Related:** CR-68, R14, `docs/GOTCHAS.md` §15

### RES-5: BPG idling makes the companion nag "Resolve's scripting is dead" with Resolve closed
- **Lens:** pitfall
- **Where:** `resolve_prefs.py:128-158` (`tasklist /FI "IMAGENAME eq Resolve.exe"`),
  `resolve_bridge.py:464-505`, `app.py:2989-3049`
- **Scenario:** the companion started BPG overnight and never stops it ("never stopped by
  us", bpg.py:781). Real Resolve is closed. `Resolve.exe` is nevertheless in the process
  list.
- **Today:** `_resolve_process_present()` is True, `describe_disconnection()` returns
  `NO_SCRIPTING_MESSAGE` after the grace, and `_maybe_warn_scripting_dead`'s
  "positive sighting only" check (`resolve_process_state() is not True`) passes - so a
  modal dialog opens every 5 minutes telling the editor Resolve is running but scripting
  is broken and to quit and reopen it. Resolve is not open. This is precisely the warning
  the design says must never be trained-away.
- **Proposed:** `resolve_process_state()` should distinguish BPG using the command line -
  `bpg._cim_command_lines()` / `is_bpg_running()` already does exactly this - and treat a
  `-pg`-only sighting as "Resolve is not running". Belt and braces: suppress the nag while
  `BpgLauncher._child_alive()`.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** item 19, 2026-08-12 incident; bpg.py fact 1

### RES-6: undo reports clips restored that it never restored (duplicate media-pool entries)
- **Lens:** pitfall
- **Where:** `resolve_bridge.py:2401-2423`
- **Scenario:** the same source file is in the media pool twice (two imports, or a clip
  and its duplicate). FIX ALL relinks both - `fix_clip` deliberately relinks every distinct
  item (fixer.py:1064-1080) - so the journal holds two entries with the same old/new.
- **Today:** `by_path.setdefault(...)` keeps only the FIRST item per path (2404), and the
  loop never deletes the `new` key after undoing (2421 only adds the `old` key). The
  second entry finds the same item, `replace_clip` returns "Already linked" -> `ok: True`,
  `undone += 1`. The message says "Put 2 clip path(s) back" while one clip is still at the
  new path, offline for everyone else if the copy is later removed.
- **Proposed:** key `by_path` to a *list* of items per path and pop one per entry; and
  treat "already linked to `old`" as a no-op that is counted separately from a real undo,
  so the count cannot exceed the work actually done.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** comp-resolve-2, item 9

### RES-7: FIX ALL / consolidate have no free-space preflight
- **Lens:** user-error
- **Where:** `fixer.py:895-1075` (no `disk_usage` anywhere in the module),
  `popup.py:438` (`batch_total = batch_total_bytes(rows)`), `consolidate.py:404`
- **Scenario:** an editor onboards a pre-existing project: 69 out-of-tree clips, 800 GB,
  onto a laptop with 200 GB free. They press FIX ALL.
- **Today:** the batch total is computed and shown, then every file is copied until the
  disk fills; each subsequent file fails one at a time with "Your disk is full. Free up
  space and try again." (`classify_copy_failure`) and the loop keeps going. The tree is
  left with a mix of copied and half-attempted files; the machine's C:/system drive can be
  driven to zero, which also breaks Resolve's cache and the companion's own log.
- **Proposed:** before the first copy, compare `batch_total_bytes(rows)` against
  `shutil.disk_usage(local_root).free` minus a reserve (say 20 GB) and show a spelled-out
  confirmation: "This copies 812 GB into P:\... You have 197 GB free. 12 of 69 files fit."
  with [ COPY WHAT FITS ] / [ CANCEL ]. Re-check per file and **stop the batch** on the
  first ENOSPC instead of failing 40 more times. `proxy_gen.free_space_shortfall`
  (proxy_gen.py:1848-1918) is the pattern to copy - the fixer is the only large writer
  without it.
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** proxy_gen's low-space surface; CORE-H5

### RES-8: `~/.ccsync/resolve_edits` is only swept for projects still being edited
- **Lens:** pitfall
- **Where:** `resolve_journal.py:245,372-387` (`_sweep(slug, ...)` called only from
  `open_session`), `resolve_bridge.py:2060-2078` (the `.drp` export)
- **Scenario:** an editor finishes a project. Its directory holds up to one exported
  project database per 15 minutes of editing (tens of MB each).
- **Today:** the retention sweep is per-slug and runs only when a NEW journal is opened
  **for that same project**. A project that is never edited again is never swept, so its
  `.drp` exports stay forever - while `docs/RESOLVE_EDIT_SAFETY.md` Housekeeping tells the
  admin "journals and exports older than 60 days are swept on the next write". There is
  also no size budget: only age.
- **Proposed:** sweep **every** slug (cheap `iterdir` over a handful of directories) on
  each `open_session`, plus a total-size budget (e.g. 2 GB) that drops oldest-first and
  logs it. Skip the export entirely when `disk_usage(journal_root).free` is under a floor,
  and say so in the journal's `message` - an export that fills the OS drive is worse than
  no export.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** comp-resolve-4 (fixed the `.drp` suffix but not the reach)

### RES-9: a project renamed in Resolve orphans its own undo
- **Lens:** user-error
- **Where:** `resolve_journal.py:108-118` (slug is the project NAME),
  `resolve_bridge.py:2371-2392` (refusal when journal project != open project)
- **Scenario:** editor runs FIX ALL on "FF4 rough", then does Save As / renames the
  project to "FF4 v2", then decides the relink was wrong and presses Undo.
- **Today:** the newest journal for "FF4 v2" does not exist; `latest_session()` finds the
  "FF4 rough" journal and the mismatch check refuses with *"open 'FF4 rough' and undo
  there"* - a project that no longer exists under that name. The editor's only route is
  reading the JSON by hand.
- **Proposed:** record the project's stable identifier as well as its name in the journal
  header (the library walk already resolves a project db / uid - `library.py:313-336`),
  match on that first and fall back to the name. Failing that, when the refusal names a
  project no library holds, offer the journal anyway behind an explicit "this journal was
  written under a different name - replay it here?" confirmation listing the clip count.
- **Effort:** M   **Severity:** med   **Confidence:** high
- **Related:** comp-resolve-2, CR-51

### RES-10: `_relink_moved` only fixes the project that happens to be open
- **Lens:** pitfall
- **Where:** `app.py:4975-5020`, `watcher.py:304-308`
- **Scenario:** the admin moves a file belonging to project B; the editor has project A
  open (or Resolve closed). The move applies on disk.
- **Today:** `_relink_moved` walks the CURRENT media pool only, returns "Resolve not
  relinked (not open)", the ledger marks the move done, and it is never revisited. When
  the editor later opens project B the clip is offline. Its path is still *in-tree*, so
  the watcher classifies it `MISSING` - a DEBUG line and nothing else. No popup, no toast,
  no dashboard signal.
- **Proposed:** keep applied moves in the ledger as *pending relinks* until a media-pool
  walk has actually matched (or 30 days pass), and re-run `_relink_moved` on every
  `on_project_changed`. Cheaply: teach the watcher that a MISSING path matching a recent
  `file_moves` entry is a **fixable** event - toast "this clip moved on the server, CCSync
  can repoint it" with a one-click relink, since the new path is known exactly.
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** CR-87, `docs/FILE_MOVES.md`

### RES-11: the library walk cannot see unsaved edits, and nothing detects that
- **Lens:** pitfall
- **Where:** `resolve_bridge.py:786-791,1257-1336`, `library.py:253-336`
- **Scenario:** an editor with Live Save off imports media from their Desktop and works
  for two hours before pressing Ctrl-S.
- **Today:** with `library_walk` on, the timeline walk reads the project DATABASE. The
  60 s `_LIBRARY_CACHE_MAX_SECONDS` valve re-reads it, but re-reading a database that does
  not yet contain the edit still returns nothing - so for those two hours the out-of-tree
  popup, the canonical relink and the proxy repoint are all blind, and the dashboard's
  media view disagrees with the editor's screen with no error anywhere.
- **Proposed:** every Nth poll (or when the library walk returns fewer items than the
  API's track lengths - `_timeline_tracks` already gathers them cheaply), do one API walk
  and compare. A disagreement means unsaved edits: log it once, fall back to the API walk
  for that project, and surface "Resolve has unsaved changes - CCSync is reading them the
  slow way" rather than being quietly wrong.
- **Effort:** M   **Severity:** med   **Confidence:** med
- **Related:** CR-81 (fixed in repo, unshipped)

### RES-12: an editor who says "no" for ever is never heard by anyone
- **Lens:** user-error
- **Where:** `fixer.py:39-55` (`IgnoreTracker`, in-memory by SPEC), `reporter.py:509-515`
- **Scenario:** an editor keeps a personal stock-footage folder outside the tree. Every
  tray restart, the popup offers the same 300 clips; they press IGNORE ALL every time.
- **Today:** the ignore set dies with the process, so the popup returns for ever, and the
  editor is trained to dismiss the one dialog that also catches a genuinely un-synced
  card dump. Nothing about out-of-tree/missing/foreign counts reaches the dashboard -
  `poll_once` computes exactly those numbers (`watcher.py:351-359`) and throws them away.
- **Proposed:** (a) a persisted third choice - "always leave clips in this FOLDER alone
  on this machine" - written to `~/.ccsync/state/fixer_ignores.json` with the folder and a
  reason, listed in the settings window so it can be undone; (b) add the four counts plus
  the open project to the report payload so the fleet page can show "3 clips outside the
  tree" per machine. The owner currently cannot see this at all.
- **Effort:** M   **Severity:** med   **Confidence:** high
- **Related:** SPEC (per-session by design), CR-45's tray/dashboard pattern

### RES-13: `save_point_due` burns the slot before it knows the export worked
- **Lens:** pitfall
- **Where:** `resolve_journal.py:295-312`, `resolve_bridge.py:2090-2117`
- **Scenario:** a collaboration project (or an API build with no `ExportProject`). The
  editor runs FIX ALL at 10:00 and again at 10:10.
- **Today:** `save_point_due` claims the 15-minute slot the moment it answers True, before
  `save_project()` runs. The export is refused, a WARNING is logged, and the *next* burst
  10 minutes later is told a save point is not due - so it gets neither an export nor even
  a fresh `SaveProject()`. The failure is sticky in the wrong direction.
- **Proposed:** claim the slot only on a save point that at least achieved `saved: True`;
  on a total failure, re-arm immediately (a short retry floor, ~60 s, stops a storm).
  Surface a persistent "no rollback copy is being made on this machine" state in the tray
  diagnostics - today it is one WARNING per burst in a rotating log.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** item 9, `docs/RESOLVE_EDIT_SAFETY.md`

### RES-14: edits past 5000 in one burst are made and silently not journalled
- **Lens:** pitfall
- **Where:** `resolve_journal.py:76,267-268`
- **Today:** `record()` returns the path without appending once `MAX_ENTRIES_PER_SESSION`
  is reached - no log line at any level. A 6,000-clip auto-relink on a machine with a bad
  prefix is 1,000 clip rewrites with no undo entry, and `undo_last_relink` reports success
  for the 5,000 it does know about.
- **Proposed:** roll over to a new session file at the cap (keeping the same burst's save
  point), or at minimum log one WARNING naming the count and telling the reader the rest
  of the pass is in the log only. Have `undo_last_relink`'s message say when the journal
  it replayed was truncated.
- **Effort:** S   **Severity:** med   **Confidence:** high

### RES-15: a zero-byte or in-flight proxy can be handed to `LinkProxyMedia`
- **Lens:** pitfall
- **Where:** `proxy_relink.py:148-170` (`find_proxy_on_disk` uses `os.path.exists` only),
  `resolve_bridge.py:2240-2288`
- **Scenario:** a proxy arrives truncated (an interrupted third-party copy, an editor
  dragging files in by hand, a share that dropped mid-write).
- **Today:** existence is the only test. Resolve validates timecode/frame count and often
  refuses - but a container whose metadata reads correctly can be accepted, and the editor
  then cuts against a proxy that ends early. `proxy_gen` full-decode verifies what IT
  makes (`proxy_gen.py:1664-1702`); nothing verifies what arrives.
- **Proposed:** in `find_proxy_on_disk`, skip a candidate whose size is 0 or whose mtime is
  under ~30 s old (still landing), and record it for the next pass instead of refusing
  permanently. Optionally reuse `ffmpeg_tools.probe_video` once per newly seen proxy to
  compare duration against the original before linking - the probe is already used by
  proxy_gen and is cheap next to a LinkProxyMedia.
- **Effort:** S   **Severity:** med   **Confidence:** med
- **Related:** R10, R17 (open)

### RES-16: the macOS half of the CR-68 guard rests on one field lsof may not give
- **Lens:** pitfall
- **Where:** `script_server.py:222-286` ("untested against a live Mac when written"),
  `classify` at 132-141
- **Scenario:** a Mac editor launches Resolve while the companion polls.
- **Today:** READY needs either the client pid to be the server's PARENT (the `R` field
  from `lsof -F pcRnT`) or its name to be in `_RESOLVE_NAMES`. lsof truncates COMMAND to
  9 characters by default, so Resolve reads as `davinci r` and the name test can never
  match - the guard hangs entirely on the PPID field. If `R` is absent or unparsed the
  answer is STARTING for ever and every Resolve call is withheld silently (`_note_starting`
  logs once), i.e. the Mac fleet loses the fixer, proxy attach and project reporting with
  a healthy-looking log.
- **Proposed:** pass `+c 0` to lsof and prefix-match `davinci` in `_RESOLVE_NAMES`; and add
  a self-test - if STARTING has persisted for more than ~3 minutes, log a WARNING and fall
  back to UNKNOWN (fail open) rather than withholding for ever. A guard that cannot expire
  is a new way to be dark.
- **Effort:** S   **Severity:** med   **Confidence:** med
- **Related:** CR-68, MAC-10

### RES-17: the automatic proxy repoint rewrites the project and tells no one
- **Lens:** safeguard
- **Where:** `app.py:3226-3253` (no `_notify_tray`), cf. `app.py:2137-2141` where the
  canonical relink does notify
- **Today:** `apply_relinks` can repoint hundreds of proxy attachments unprompted, logged
  only. An editor who then notices their proxies changed has no idea CCSync did it, and
  `docs/RESOLVE_EDIT_SAFETY.md` is the only place the behaviour is written down.
- **Proposed:** one toast per pass ("Repointed 42 proxies to the copies in your sync
  folder - tray -> Advanced -> Undo if that was wrong"), matching the canonical relink's
  wording so the undo action is discoverable at the moment it is needed. Include the
  `describe_latest()` summary in the tray's Advanced submenu label so "undo" names what it
  would undo before it is pressed.
- **Effort:** S   **Severity:** low   **Confidence:** high

### RES-18: `verify_copy` proves size, not bytes, and the relink follows immediately
- **Lens:** safeguard
- **Where:** `fixer.py:748-779`
- **Today:** the last gate before Resolve is told anything compares sizes and the source's
  (size, mtime). A copy that came back corrupt over a flaky SMB link with the right length
  passes, is relinked, and lane A then uploads it under a name it can never replace
  (`--ignore-existing`).
- **Proposed:** for files under a threshold (say 2 GB) hash both ends during the copy -
  `copy_with_progress` already streams the bytes, so the source digest is free and only the
  destination re-read costs I/O; for larger files, sample-verify (first/last/N random 8 MB
  windows). Record the digest beside the journal entry so a later dispute ("which copy is
  the good one?") is answerable.
- **Effort:** M   **Severity:** med   **Confidence:** med
- **Related:** item 9, AUDIT D-5

## Cross-cutting notes
- **Sync/lanes agent:** RES-1's 24-hour `EXCLUDE_WINDOW_SECONDS` is the mechanism by which
  a *failed* move turns into a lane A re-upload. Whoever owns lane A should know that the
  exclusion expiry is not tied to the move actually having been applied.
- **Dashboard agent:** the companion reports no Resolve health at all beyond the project
  name (`reporter.py:509-515`). Out-of-tree / missing / bad-prefix counts and a wedged
  bridge are computed on the machine and thrown away; a fleet column for them is a
  dashboard-side design question (RES-3, RES-12).
- **Ops/global:** per `~/.claude/CLAUDE.md`, every Resolve client on a machine must carry
  `ready_to_connect()`. This session's own environment exposes a `davinci-resolve` MCP
  server whose tool descriptions say they "automatically launch Resolve if it is not
  running" - that is the CR-68 trigger by design, on the base rig, and worth confirming
  the guard was actually landed there (KNOWN_BUGS CR-68 records the port as *uncommitted*).
