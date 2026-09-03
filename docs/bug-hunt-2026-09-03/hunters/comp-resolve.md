# comp-resolve — the companion's Resolve bridge, journal/undo, proxy generation and relink, Timeline Cards role

Files read (approximate coverage): `companion/src/ccsync_companion/script_server.py` (100%),
`resolve_journal.py` (100%), `resolve_undo.py` (100%), `proxy_relink.py` (100%),
`timeline_cards_bridge.py` (100%), `timeline_cards_role.py` (100%),
`resolve_bridge.py` (~70% — header/locking, connect + CR-68 gate, library session,
timeline/pool walks, uid cache, save point, replace_clip / link_proxy_media /
unlink_proxy_media / undo_last_relink, bin + import path; skimmed perform_insert
and the playhead/track helpers), `proxy_gen.py` (~40% — encode_once, _encode_clip,
_build_cmd, _publish/_discard/_claim_partial, `-f` container plumbing),
`proxy_scan.py` (~40% — naming/convention half), `fixer.py` (~35% — the copy /
reserve / sweep half), `library.py` (~30% — blob + clip_path parsing, locate),
`bpg.py` (~20% — probe + detached spawn), plus `ffmpeg_tools.own_proxy_cmd`,
`canon.norm`, `app.py`'s proxy-relink call site. Tests read: `test_proxy_relink.py`,
`test_resolve_journal.py`, `test_resolve_edit_safety.py`, `test_timeline_cards_role.py`.

Tests run:
`companion/.venv/Scripts/python.exe -m pytest tests/test_resolve_bridge.py tests/test_resolve_bridge_launch_window.py tests/test_resolve_edit_safety.py tests/test_resolve_journal.py tests/test_resolve_undo_command.py tests/test_script_server.py tests/test_proxy_relink.py tests/test_proxy_gen.py tests/test_proxy_scan.py tests/test_library.py tests/test_library_walk.py tests/test_fixer.py tests/test_bpg.py tests/test_timeline_cards_role.py tests/test_timeline_cards_bridge.py -q`
-> **744 passed, 1 skipped**.

CR-68 audit result (asked for explicitly): `grep -rn "scriptapp(" companion/src` finds
exactly **one** call site, `resolve_bridge.connect()` at `resolve_bridge.py:369`, and it is
gated on `script_server.state()` with STARTING and ABSENT both refusing and UNKNOWN
failing open, exactly as `script_server.ready_to_connect()` documents. Every other hit
(`app.py`, `broll_server.py`, `capabilities.py`, `music_worker.py`,
`timeline_cards_bridge.py`) is a comment. `timeline_cards_bridge.CardsBridge.resolve()`
routes the cards engine through `connect()`, and `api_call(name)` is the only public way
to hold `_API_LOCK` from outside the module. **No CR-68 violation found.**

## Findings

### comp-resolve-1 — two concurrent media-pool edits silently lose undo-journal entries
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/resolve_journal.py:401-433` (`record`), with
  `_write` at `:351-359`; writers reach it from `resolve_bridge.replace_clip`
  (`resolve_bridge.py:2214-2219`) and `link_proxy_media` (`:2309-2315`).
- What: `record()` takes `_lock` only inside `open_session()`, then does an **unlocked
  read-modify-write** of the whole journal file: `_read(path)` -> append one entry ->
  `_write(path, data)`. Two threads recording into the same burst both read the same
  `entries` list and the second `os.replace` wins, so the first thread's entry is gone.
  The tmp file is also a fixed name (`<file>.json.tmp`) shared by every writer, so on
  Windows the loser can additionally hit `PermissionError` inside `os.replace` — which
  `record()` swallows at `log.debug` (`:431-433`), i.e. with nothing in the log at INFO.
- Failure scenario: an editor presses FIX ALL (tray worker thread) while the 120 s
  proxy-relink pass (`app._relink_proxies_once`, media-tree thread) is running, or while
  the watcher's automatic canonical relink fires, or while a b-roll `/insert`
  canonicalises freshly imported clips on the HTTP thread. All four write the same
  `~/.ccsync/resolve_edits/<project>/<stamp>.json`. Some of the `ReplaceClip`s that
  really happened are never journalled. Later, tray -> UNDO (or the dashboard's
  `[ UNDO THIS CHANGE ]` via `resolve_undo.apply_undo`) reports
  `"Put N clip path(s) back the way they were"` and returns `ok`, while the clips whose
  entries were lost keep the rewritten path — with no "skipped" count, because the undo
  never knew about them. This is the rollback of last resort for two *unprompted*
  rewrite paths.
- Evidence: with the companion venv, HOME redirected to a temp dir, 8 threads x 20
  `record()` calls into one project: **`recorded 5 of 160`**. With a 50 ms sleep inserted
  into `_read` to widen the existing window and only 5 concurrent writers:
  `entries recorded: 2 expected 6`, entries `['seed', 'c4']`. Neither
  `tests/test_resolve_journal.py` nor `tests/test_resolve_edit_safety.py` contains a
  thread — the suite only ever records serially, so the bug cannot be caught there.
- Ledger: new. (`KNOWN_BUGS.md` has the journal at 662-667 and CR-era entries at 1764,
  3779, 8215; none is about concurrent `record()`.)
- Suggested fix: hold `_lock` across the read-append-write in `record()` (the file is
  small and the lock is already the module's serialiser), and give `_write` a
  process/thread-unique tmp name (`.tmp.<pid>.<ident>`). Consider raising the swallowed
  write failure to a WARNING: an entry that could not be journalled is an edit that
  cannot be undone, which `open_session()` already says out loud.

### comp-resolve-2 — a Resolve that goes away mid-pass is remembered as a permanent proxy refusal
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/proxy_relink.py:384-407` (`apply_relinks`) against
  `companion/src/ccsync_companion/resolve_bridge.py:2295-2305` (`link_proxy_media`'s
  `except`), call site `companion/src/ccsync_companion/app.py:3919-3923`.
- What: `apply_relinks` distinguishes "Resolve refused this pairing" (remember it, never
  offer again until the proxy file's `(mtime, size)` change) from "the call blew up"
  (do **not** remember) by catching an exception around `link_fn`. But `link_fn` is
  `resolve_bridge.link_proxy_media`, which by contract *never raises*: it catches the
  `LinkProxyMedia` exception itself and returns
  `{"ok": False, "message": _SCRIPTING_ERROR_MESSAGE}`. So the `except Exception` branch
  at `:386-392` — the one whose comment says "NOT a refusal: fusionscript going away says
  nothing about this pairing" — is unreachable, and every scripting error lands in the
  `else` at `:399-407`, which calls `note_refusal(op, stat)`.
- Failure scenario: the editor quits Resolve (or opens a modal dialog, or the project is
  locked in a collaboration) while the 120 s pass is halfway through 200 ops. Every
  remaining op gets `_SCRIPTING_ERROR_MESSAGE` and is recorded in `_REFUSALS` keyed on
  `(clip, proxy)` with the proxy's current `(mtime, size)`. Those clips are then skipped
  by `plan_relinks` (`:323-328`) for the rest of the companion's life, because the proxy
  file on disk never changes — it was fine all along. Result: clips that would have
  relinked show Media Offline / no proxy until the tray is restarted, and the log says
  "refused by Resolve ... a timecode that does not match the original is the usual cause",
  pointing the operator at KNOWN_BUGS R10/R17 for a fault that is not there.
- Evidence: read both sides. `tests/test_proxy_relink.py` drives `apply_relinks` with a
  hand-written `link_fn` returning `{"ok": False}` and never exercises a
  `_SCRIPTING_ERROR_MESSAGE` result, so the whole suite passes with the bug present.
- Ledger: new (related to COMP-MEDIA-5, the mechanism this brake was added by, and to
  R17, which is open and whose diagnosis this can contaminate).
- Suggested fix: in `apply_relinks`, only `note_refusal` when the failure is Resolve
  actually declining the pairing — e.g. skip it when
  `result.get("message") == resolve_bridge._SCRIPTING_ERROR_MESSAGE` (or have
  `link_proxy_media` return a machine-readable `"reason": "scripting_error" | "refused"`
  and branch on that).

### comp-resolve-3 — a cards checkout that exports only `ResolveEngine` crashes instead of refusing
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/timeline_cards_role.py:161-162` (`check_contract`
  accepts `SyncEngine` **or** `ResolveEngine`) vs `:435` (`_start` does
  `getattr(engine_mod, "SyncEngine")`, no default).
- What: `check_contract` deliberately tolerates either class name and validates the
  `bridge` parameter on whichever it finds; `_start` then hard-requires `SyncEngine`.
- Failure scenario: the MulticamPipeline checkout lands §7c on the class it already has
  (`ResolveEngine`, the name used throughout `docs/TIMELINE-CARDS-INTO-CCSYNC.md` and
  in this module's own docstring). `check_contract` passes, `_start` raises
  `AttributeError`, `start()`'s catch-all sets
  `STATE_NO_ENGINE, "the role could not start (see the log)"` — the exact "discovered as
  an AttributeError" outcome the module's docstring says the version constant exists to
  prevent, and the diagnostics bundle carries a sentence that names nothing.
- Evidence: read both lines; `tests/test_timeline_cards_role.py` never mentions
  `ResolveEngine`, so only the `SyncEngine` spelling is exercised.
- Ledger: new.
- Suggested fix: have `check_contract` return the class it validated (or reuse the same
  `getattr(...) or getattr(...)` expression in `_start`).

### comp-resolve-4 — the "cards is starving the watcher" warning fires once and then never again
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/timeline_cards_bridge.py:271-283` (`_note_take`).
- What: `self._slow_logged_at` is stamped on **every** slow take, not only on the takes
  that actually log. The repeat guard then compares against the previous *slow take*
  rather than the previous *log line*, so once slow takes arrive more often than
  `SLOW_TAKE_REPEAT_SECONDS` (60 s) apart, the condition is never satisfied again.
- Failure scenario: the cards engine's 1 s sweep starts holding `_API_LOCK` for >0.5 s on
  a big project. One WARNING is written; the sustained condition — which is the whole
  stated risk of phase 2, "one scheduler starving the other" — then produces silence for
  as long as it lasts. Contrast `resolve_bridge._note_wedge`, which repeats every 300 s.
- Evidence: read; `_slow_logged_at` starts at 0.0 so the first slow take always logs, and
  every subsequent one refreshes the window it is measured against.
- Ledger: new.
- Suggested fix: move the stamp so it is written only when the WARNING is emitted (compute
  the decision inside the lock and set `_slow_logged_at` there only if it will log).

### comp-resolve-5 — on macOS the script-server probe's Resolve-name check can never match (lsof truncates the command)
- Severity: low
- Confidence: PLAUSIBLE (no Mac available here; the module's own header records that the
  darwin branch was never run against live hardware)
- Where: `companion/src/ccsync_companion/script_server.py:94` (`_RESOLVE_NAMES` includes
  `"davinci resolve"`), `:231-276` (`parse_lsof`, `c<command>`), `:279-286`
  (`lsof -nP -iTCP:1144 -F pcRnT`).
- What: `lsof`'s COMMAND field is truncated to 9 characters by default (`+c w`, default 9),
  including in `-F` output. `DaVinci Resolve` therefore arrives as `davinci r`, which is
  in neither `_RESOLVE_NAMES` nor anything else. READY on a Mac then depends **entirely**
  on the `pid in parents` arm (fuscript's parent pid being Resolve's) — the name check,
  which is the documented fallback for when the parent relationship is not what we expect,
  is dead code there. `fuscript` (8 chars) is unaffected.
- Failure scenario: a Mac where `fuscript` is re-parented (launchd adoption after the
  spawning thread exits, a helper process in between) reports STARTING forever instead of
  READY, and the companion's Resolve features go permanently quiet on that machine with
  "Resolve is starting up" in the tray. Fail-safe direction, but unrecoverable without a
  restart of Resolve.
- Evidence: read; `tests/test_script_server.py` feeds `parse_lsof` hand-written fixtures,
  so whatever they spell is what is asserted.
- Ledger: new.
- Suggested fix: pass `+c 0` to lsof (`lsof -nP +c 0 -iTCP:1144 -F pcRnT`), and/or match
  `_RESOLVE_NAMES` by prefix.

### comp-resolve-6 — the standalone-agent probe can clear on a partial process listing
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/timeline_cards_role.py:216-218`.
- What: `running_command_lines()` returns `None` (which `standalone_agent()` treats as
  "cannot tell" = refuse) only when the probe exits non-zero **and** produced no output.
  A PowerShell/`Get-CimInstance` run that emits some lines and then fails (CIM query
  interrupted, WMI repository hiccup, an access error part way through the enumeration)
  returns a truncated list, which `standalone_agent()` reads as an authoritative "nothing
  found".
- Failure scenario: the truncated listing happens not to include the running
  `reorder_web.py --agent`; the role starts, and the machine has two Resolve clients —
  the exact CR-68 outcome this gate exists to prevent, and the one the module says costs
  "the scripting API for the whole Resolve session".
- Evidence: read. The docstring one function above says "None is NOT 'there is nothing
  running'", but the non-zero-exit-with-output path silently converts one into the other.
- Ledger: new.
- Suggested fix: return `None` whenever `returncode != 0`, regardless of partial stdout.

## Coverage note

Not covered: `resolve_bridge.perform_insert` / `_place_at_playhead` / track-overlay
maths (~600 lines), `_enrich_proxy_keys` and the pool-walk half of the library path,
`fixer.py`'s `fix_clip` main body and the popup wiring, `library.py`'s SQL
(`_sequence_for_timeline`, `_tracks`, `_items`, the multicam expansion) and the
Postgres/SQLite backends, `proxy_gen`'s scheduler/idle-gate/queue half, `proxy_history`,
and most of `bpg.py` (`ensure_watch_folders`, the Qt-escape path).

Things the suite structurally cannot catch, beyond the two named above: the journal has
no concurrency test at all; `apply_relinks`' refusal memory is only exercised with
hand-written `link_fn` doubles, never with the real `link_proxy_media` result shapes;
and `parse_lsof`/`classify` are tested only against fixtures written by the same person
who wrote the parser, so a wrong assumption about real `lsof` output is invisible.

One item I looked at and did **not** find a defect in, since the brief asked: `_nfc`
(`resolve_bridge.py:3057`) is applied only to media-pool **bin names**, for comparison,
and `AddSubFolder` is handed the un-normalised name — correct per CR-90. `canon.norm`
(the path normaliser `_norm_path` delegates to) does **not** apply NFC, but every path
comparison in this territory compares strings that came from the same source (Resolve's
own property, or a path derived from it), so I could not construct a real NFD/NFC
mismatch inside the territory; worth a second look from whoever owns `canon.py` /
`links.py`. `proxy_gen`'s rule 2 is intact: `-f <container>` is passed on both
builders (`ffmpeg_tools.py:671`, `:759`) with `container = proxy_scan.GENERATED_EXT`
stripped of its dot (`proxy_gen.py:1929`), so the KNOWN_BUGS 24 muxer-EINVAL class
cannot recur through this path; `_publish` re-checks `expected_proxies` after the encode
and `os.replace`s, first writer wins.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/proxy_gen.py:1705-1732` (`_publish`): the
  "first writer wins" existence check and the `os.replace` are not atomic together — a
  BPG/lane-B proxy that lands in that window is overwritten. In-territory file, but a
  narrow TOCTOU I could not make concrete; noted rather than filed.
- `companion/src/ccsync_companion/canon.py:84-97` (`norm`): no NFC folding, despite
  CLAUDE.md's CR-90 rule naming per-domain normalisers. Whoever owns `canon.py` should
  confirm no cross-platform comparison reaches it with one NFD and one NFC spelling.
