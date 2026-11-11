# cards-resolve - Timeline Cards' Resolve side: the sweep/agent loop, conform, cut list, project diff/pick, the library DB writer guard, timecode, keystroke edits
Tree: `E:\Projects\Editing\Resolve\MulticamPipeline` (HEAD 78f0bb0) unless stated.

Files read (approximate coverage): `multicam_pipeline/cards/resolve_engine.py` (~55%: module budget, bridge, connect, sweep, scan_bin/scan_pool, place_span, conform, _apply/_apply_edit, the main loop), `agent.py` (~45%: AgentLink state/push handling, writer/editor gates, library worker, writer handshake, AgentClient push/pull loops), `library_engine.py` publish / _publish_key / _sections / bind_db / tokens_for (call sites only), `cutlist.py` (save/history/write_text, header), `project_engine.py` (_edit_worker, _run_apply, _save), `project_diff.py` (match_spans, _in_place), `project_pick.py` (doc_save/remember), `keys.py`, `timecode.py`, `ripple_keys.ahk`, `resolve/multicam_ui.py` (header + function map), `library/library_writer.py` (gates, saved_counter, conform), `library/library_reader.py` (connection plumbing), `transcripts/multicam_transcripts.py` (ProjectDatabase connect), docs `REPRO-RIGHTS-V7-DAMAGE.md`, `LAG-INVESTIGATION.md` (sections 1-5 and the 2026-08-31 "what the agent does every second" note), `CLAUDE.md`, GOTCHAS headings.

Probes run (all from my scratch folder, no Resolve, no network):
- `probe_publish.py`: the per-tick publish work on a real 487-card / 23-marker state (`scratch/state8802.json`, 678 KB): `_sections` 0.50 ms, `_publish_key` dump 1.54 ms, full `json.dumps` 1.66 ms = **37 ms CPU per second at 10 Hz**; the agent's `json.loads` of the same state 1.81 ms.
- gzip of that state: 678,008 -> 131,369 bytes (5.2x) in 7.9 ms.
- `probe_diff.py`: `project_diff.match_spans` 500 cuts / 15 clips 2.0 ms; 500 cuts / 1 clip 26.9 ms; 1,000 / 1 clip 108 ms (quadratic only inside one clip; not a finding today).
- `probe_cut.py`: a real 433-cut `.cut.md` (198 KB): `loads` 2.6 ms, `dumps` 1.1 ms, gzip 54 KB; history-retention model below.
- timecode round trip: `frame_to_tc`/`tc_to_frame` for every frame of 3 h at 24/25/30/30DF/60/60DF: 0 mismatches; `03:00:00;00` = 323,676 = 3 h x 30000/1001 rounded. No drift.
- `lane_keys()` on this machine's real 92 KB `keyboard.preset.xml`: 0.7 ms (not a finding).

## Findings

### cards-resolve-1 - LibraryReader holds one open transaction on Resolve's live project library for the life of the process
- Category: resilience
- Severity: medium
- Confidence: CONFIRMED (mechanism, by reading); the effect on Resolve PLAUSIBLE
- Where: `multicam_pipeline/library/library_reader.py:411-436` (`_connect`/`_query`), kept alive by `multicam_pipeline/cards/agent.py:686-696` (`reader()`) and polled by `agent.py:1020-1029` (`_lib_worker`, every `LIB_POLL_S` = 2 s)
- What: psycopg2 opens a transaction on the first `execute` and keeps it until `commit()`/`rollback()`. `_query` never does either and never sets `autocommit`, and the connection is cached per database for the process's life. So every reader connection sits "idle in transaction" on FF5/FF3/FF5lab forever, holding an `AccessShareLock` on every table it has ever read (Sm2Sequence, Sm2Timeline, Sm2TiItem, ...) until the transaction ends.
- Cost / failure scenario: The NAS-side engine (one per open episode, up to 2) and any `--agent`/`--project` server keep the transaction open for days, and the 2 s fingerprint poll keeps it busy. The same repo already hit this exact bug in `ProjectDatabase` and fixed it on 2026-09-03 (`multicam_transcripts.py:184-191`: "an idle reader pinned the server's xmin for hours", and one refused statement poisoned the transaction). Today the effects are: (a) xmin can be held back, which bloats the tables Resolve itself reads and writes on every save; (b) any `ACCESS EXCLUSIVE` request on those tables (a Resolve version upgrading the library schema, "optimize"/VACUUM FULL, our own restore DDL) blocks behind the idle transaction, and every Resolve query queued after it blocks too: every editor in that library freezes until the dashboard restarts.
- Evidence: `library_reader.py:417-436` has no commit/rollback/autocommit (grep finds none in the file); the sibling reader's comment at `multicam_transcripts.py:184-190` records the same mechanism already observed live.
- Ledger: new (same defect as the 2026-09-03 ProjectDatabase fix, not carried over to LibraryReader)
- Suggested change: set `conn.autocommit = True` in `LibraryReader._connect` (it only SELECTs), or `conn.rollback()` after each fetch. Must not touch `LibraryWriter`, which relies on one explicit transaction and its own commit/rollback.
- Effort / risk: S effort; low risk

### cards-resolve-2 - The 10 Hz loop serialises the whole state twice every tick, whether or not anything changed or anyone is watching
- Category: idle
- Severity: medium
- Confidence: CONFIRMED
- Where: `multicam_pipeline/cards/resolve_engine.py:3502-3528` (every `POLL_FAST` tick calls `_publish(dict(state), ...)`) -> `library_engine.py:4942-4999` (`_publish_locked`: `_summary_state` -> `_sections`, `_publish_key` `json.dumps` of cards+markers, then a full `json.dumps(state)`)
- What: The cards change at most once per `POLL_FULL` sweep (1 s), but every 0.1 s tick rebuilds the section texts and hashes (O(markers x cards)), serialises the cards to compare them, and serialises the whole 680 KB state again to change only `playhead`/`ph_uid`/`ph_src`. This runs on the editor's machine beside Resolve, all day, with the page closed, in the companion's Timeline Cards role and in the standalone agent alike.
- Cost / failure scenario: measured 3.7 ms per tick on a 487-card state = **37 ms CPU per second (3.7 % of a core) and about 13 MB/s of short-lived strings**, continuously, forever, at today's size; linear in cards (1,000 cards: about 75 ms/s). LAG-INVESTIGATION (2026-08-31) measured the whole agent at ~23 % of a core with Resolve idle; this is the part that needs no Resolve call at all to fix.
- Evidence: probe_publish.py above; the loop code at 3502-3528 publishes unconditionally.
- Ledger: related to LAG-INVESTIGATION.md "The other half: what the agent does to Resolve every second" (documented, not fixed, no ledger entry)
- Suggested change: pass the sweep's "cards may have changed" flag into publish; on a playhead-only tick, skip `_summary_state`/`_publish_key` and splice the three playhead fields into the cached body (or serve the playhead as its own small field, as the agent's ping already does). Must keep the version bump rules (a playhead move must not bump `version`).
- Effort / risk: M effort; medium risk (the page's version/delta contract is sensitive)

### cards-resolve-3 - The full sweep keeps running at 1 Hz (about 1,350 RPCs under the shared API lock) when no page is open and while Resolve is playing
- Category: idle
- Severity: medium
- Confidence: CONFIRMED (code); cost from the repo's own measurement
- Where: `multicam_pipeline/cards/resolve_engine.py:3469-3501` and `_sweep` 453-510; `agent.py:2054-2118` (`push_loop`)
- What: `_sweep` reads uid + start + duration of every V1 item every second (3 RPCs per item plus about 6), plus `GetMarkers`, and each second also calls `bridge.sweep_items` (a companion fingerprint + library read). Nothing slows it when no browser has the page open (the server knows: the page polls `api/state`, and the agent could be told on its `/agent/state` reply), and nothing pauses it while the playhead is moving (the 10 Hz read already knows).
- Cost / failure scenario: LAG-INVESTIGATION measured 135-141 ms of Resolve's single scripting thread per sweep at 451 items, i.e. ~14 % of Resolve's scripting capacity every second, under `bridge.lock`, which the companion's tray and watcher share. At 500 cards today and longer cuts at commercial scale it grows linearly. Most of the working day nobody has `/cards` open.
- Evidence: loop code; LAG-INVESTIGATION.md section 4 table and the 2026-08-31 note.
- Ledger: related to LAG-INVESTIGATION.md (suggested there, not done)
- Suggested change: have the server answer `viewers: <n>` (pages polled in the last ~30 s) on `/agent/state`, and in the companion role read the same from the tunnel; drop the full sweep to every 10 s and the playhead read to 1 s when there are none, and skip the full sweep while the playhead advanced since the last tick. An edit or a jump must still force an immediate sweep (it already sets `last_full = 0`).
- Effort / risk: M effort; low risk

### cards-resolve-4 - `bridge.sweep_items()` is asked every second even when every item's detail is already cached
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: `multicam_pipeline/cards/resolve_engine.py:482` (`rows = self._sweep_rows(tl_id)`), used only on a cache miss at 489-493
- What: the rows only feed `_detail_from_row`, which returns the cached detail at once when `uid` is known and `dur` is unchanged, yet the library read is made before that is checked. In the companion role each call is `resolve_bridge.library_timeline_items()`: `ui_state.wait_while_menu_open()`, four head RPCs under `_API_LOCK` for the fingerprint, and (on a fingerprint change) a Postgres read.
- Cost / failure scenario: 1 call per second per machine all day (86,400 per day), each 4+ RPCs plus a possible library query, for an answer used only after a trim, an edit or a timeline switch.
- Evidence: code at 482-494; companion `resolve_bridge.py:1394-1417` docstring ("holds _API_LOCK only for the four head calls").
- Ledger: new
- Suggested change: compute the misses from `geom` against `self.lib._detail` first and call `_sweep_rows` only when there is at least one. Must keep the uid check in the bridge (positional mapping onto the fingerprinted timeline).
- Effort / risk: S effort; low risk

### cards-resolve-5 - A library conform passes `allow_open=True` after it has proved the project closed, so the writer's own lock gate is switched off for exactly the race it exists for
- Category: concurrency
- Severity: medium
- Confidence: CONFIRMED (code path); exploitation needs a second editor to open the project inside the window
- Where: `multicam_pipeline/cards/agent.py:1399-1401` (`writer.conform(..., allow_open=state["released"])`), same at `agent.py:1747` (library_edits apply) and `project_conform.py:1042`; gate at `library/library_writer.py:943-952`
- What: `_release_for_write` asks the agent to close the project and then re-reads `LockId` and refuses if anyone still holds it. Having proved the lock gone, the worker then passes `allow_open=True`, which makes `_gate_lock` accept a lock. Between that check and the conform's own read (the `editor.pin` library read, seconds) another editor or a Resolve auto-reopen can open the project, and the write goes ahead into a project Resolve holds open - the condition REPRO-RIGHTS-V7-DAMAGE.md names as the likely origin of the 63 half-links ("the video side was emptied later, while Resolve had V7 open").
- Cost / failure scenario: one conform or in-place apply into an allowlisted library while a collaborator opens the same project. Today only FF5lab is allowlisted (`deploy/site.toml`, ccsync `[timeline_cards] db_write_allow`), so the damage would be in the sandbox; the guard is still defeated by its own flag.
- Evidence: agent.py:1447-1475 sets `released` before the lock read and the lock read already refuses a holder; library_writer.py:943-952.
- Ledger: related to REPRO-RIGHTS-V7-DAMAGE.md (fixed items there do not cover this)
- Suggested change: pass `allow_open=False` once `_release_for_write` returned (the lock is gone by proof), so a lock that reappears is refused before any row is written; keep `released` only for the reload-after.
- Effort / risk: S effort; low risk

### cards-resolve-6 - The DB writer's "real library" protection is a hard-coded denylist of five names
- Category: security
- Severity: low
- Confidence: CONFIRMED
- Where: `multicam_pipeline/library/library_writer.py:215` (`REAL_LIBRARIES = ("FF5", "FF3", "FF1", "Base Drone", "The Creators Club")`), `_gate_db` 920-932
- What: The writer that damaged V7 is still reachable from the live page (library route, `agent.py:698-754`, `writer_ready`) and from `project_conform` whenever the deployment's allowlist names a library. Conform and in-place edit are refused only for the five listed names; a new season's library ("FF6") or any customer's library is unprotected the moment an admin puts it in `db_write_allow` (whose only description is "a list of library names").
- Cost / failure scenario: an admin allowlists "FF6" to try the fades on a real episode -> conform/edit rows land in a live library, the 2026-09-29 failure class again.
- Evidence: code; `deploy/site.example.toml:113-114`.
- Ledger: related to REPRO-RIGHTS-V7-DAMAGE.md
- Suggested change: invert it: allow conform/edit only into libraries named as sandboxes (e.g. a `sandbox` marker in site.toml, or a name suffix such as `lab`), keeping restore/delete_timeline as they are.
- Effort / risk: S effort; low risk

### cards-resolve-7 - The agent never re-binds its project database after the editor switches library
- Category: bug
- Severity: medium
- Confidence: PLAUSIBLE (code certain; needs a live Resolve library switch to see)
- Where: `multicam_pipeline/cards/resolve_engine.py:278-287` (`if self.lib._db is None:` bind once)
- What: The engine binds `lib._db`, `db_info` and `db_project` the first time it connects and never again: a reconnect after `_fail` skips the bind because `_db` is already set, and nothing compares `GetCurrentDatabase()` per sweep. After the editor moves Resolve to a project in another library (FF5 -> FF3, or FF5lab), every transcript lookup goes to the old database, misses, and is retried against it every 60 s (`TOKENS_RETRY_S`) per clip; the agent also keeps pushing the old `db` to the server (`agent.py:2089`), so the NAS page reads tokens from the wrong library too.
- Cost / failure scenario: companion role runs for weeks; a library switch leaves every card "no transcript" until the tray restarts, plus one failing Postgres query per clip per minute.
- Evidence: code; `bind_db` (library_engine.py:4839) is the only re-binder and is never called on the agent machine.
- Ledger: new
- Suggested change: in `_connect`, compare `current_database_info(manager, name)` (and the project name, for Disk libraries) with `lib.db_info/db_project` and re-bind through `lib.bind_db` when they differ.
- Effort / risk: S effort; low risk

### cards-resolve-8 - The agent uploads the whole 680 KB state uncompressed on every version change
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: `multicam_pipeline/cards/agent.py:2019-2026` (`_req`), 2075-2092 (full push)
- What: each version change (every edit, translation landing, marker) is a fresh HTTP connection carrying `json.dumps` of the decoded state plus every clip name/path ever met (`clips()`), with no `Content-Encoding`. The server already gzips what it serves (`handler.py:148-161`), not what it receives.
- Cost / failure scenario: 678 KB -> 131 KB gzipped (5.2x, 8 ms). For a remote editor's agent on a ~20 Mbit/s uplink that is ~270 ms vs ~60 ms on the path every edit confirmation waits on; at 200 edits an hour, ~136 MB vs ~26 MB uploaded.
- Evidence: gzip probe on `scratch/state8802.json`.
- Ledger: new
- Suggested change: gzip the full push and accept `Content-Encoding: gzip` on `/agent/state` (both the standalone handler and the dashboard's tunnel); deploy the server side first.
- Effort / risk: S effort; low risk (wire change: server before agents)

### cards-resolve-9 - Cut-list history grows without bound (every tenth revision kept forever) as full copies in the vault
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED
- Where: `multicam_pipeline/cards/cutlist.py:1023-1068` (`history_save`, `HISTORY_KEEP=200`, `HISTORY_THIN=10`)
- What: every edit writes the full previous file to `Cuts\.history\` and lists the whole shared `.history` folder (all cut lists of the episode) to thin it. Beyond the newest 200, one in ten is kept for ever, uncompressed. The writer itself is cheap (433 cuts: `loads` 2.6 ms, `dumps` 1.1 ms), so this is about disk and the per-edit SMB listing.
- Cost / failure scenario: one 433-cut list is 198 KB: 2,000 revisions -> 380 files / 75 MB, 10,000 -> 1,180 files / 234 MB, per cut list, in the NAS vault (and in its snapshots); the per-edit `listdir` of a folder of thousands of names runs over SMB on the base rig.
- Evidence: probe_cut.py and the retention arithmetic.
- Ledger: new
- Suggested change: thin by age beyond the newest 200 (e.g. one per hour for a week, one per day after) and gzip revisions older than the newest 200 (198 KB -> 54 KB); keep the oldest revision, which the docstring says is the one people want back.
- Effort / risk: S effort; low risk

### cards-resolve-10 - project_pick.doc_save is an unlocked read-merge-write through one fixed `.tmp` name
- Category: concurrency
- Severity: low
- Confidence: PLAUSIBLE
- Where: `multicam_pipeline/cards/project_pick.py:436-450`, callers `agent.py:858-864` (`_save_pick`, from `/agent/state` and `set_pick` threads), `project_pick.py:489-495` (`remember`, from project open)
- What: two HTTP threads of one engine (an agent push that moved timeline + a project open) can both read the doc, both write `cards_pick.json.tmp`, and one `os.replace` either loses the other's key or fails with FileNotFoundError (caught and only printed). The engine pool fixed the cross-engine case by separate data dirs; the in-engine case is unguarded.
- Cost / failure scenario: rare; the outcome is a lost "last project for this root" or a lost pick, i.e. the page reopening on the wrong cut list after a restart.
- Evidence: code.
- Ledger: related to ccsync CLAUDE.md engine-pool note (`project_pick.doc_save` race)
- Suggested change: a module-level lock around load-merge-write and a unique temp name (`tempfile.mkstemp` in the same dir).
- Effort / risk: S effort; low risk

### cards-resolve-11 - ripple_keys.ahk checks the foreground window once per batch, by process, not per key
- Category: resilience
- Severity: low
- Confidence: PLAUSIBLE
- Where: `ripple_keys.ahk:29-52`
- What: the batch checks `WinActive("ahk_exe Resolve.exe")` once and then sends each key 100 ms apart. Any Resolve.exe window passes (a floating Inspector/Fusion window, a second-screen viewer, a modal message box); a window that comes up mid-batch receives the rest. `BlockInput "SendAndMouse"` is best effort and, as far as I know, does nothing unless AutoHotkey runs elevated. Keystroke edits (unlike the conform, `resolve_engine.py:2398-2406`) do not check `GetCurrentPage()` for a modal before sending; `_park`'s read-back usually catches a dialog first, and the edit's own verification catches a wrong result, but keys like Delete/Enter into a Resolve message box are not undone by a rollback.
- Cost / failure scenario: rare; a Resolve popup during a move gets the remaining keys of the batch.
- Evidence: script; resolve_engine.py `_keys`/`_park`.
- Ledger: new
- Suggested change: re-check `WinActive` against the main window's class/title before each key and abort the batch (reply `err 3`) if it changed; call the same `GetCurrentPage()` dialog check `_apply_conform` uses at the top of `_apply_edit`.
- Effort / risk: S effort; low risk

## What is already good
- `timecode.py`: exact drop-frame maths, round trips every frame of 3 h at every base (probe); no float drift.
- `cutlist` parse/serialise is cheap (3.7 ms for 433 cuts) and atomic via temp + replace; the engine writes history from bytes in hand (no re-read).
- `project_diff.match_spans` buckets by clip (2 ms at 500 cuts) and the LIS move detection is O(n log n); the diff is already deferred until after publish.
- Per-item detail caching in `_detail_for`/`_detail_from_row`, and the whole-pool walk at names only every 120 s; one API take per phase, no nested takes; `stop()` ends the loop between ticks.
- The DB writer's 2026-09-29 fixes (saved-counter outlier walk, real-library refusal) are in place and the live allowlist is FF5lab only.

## Coverage note
Not reached in the time box: `project_conform.py` and `project_agent.py` beyond their writer call sites; `project_edit.py`, `refresh_cuts.py`, `recolour_sections.py`; `resolve_engine.py` move/trim/split/extend/insert bodies (roughly lines 1159-2150 and 3033-3235) and their RPC counts per edit; `resolve/interview_angles.py` and the rest of `resolve/` beyond `multicam_ui.py`'s header (multicam_ui posts messages to explicit hwnds and does not take the foreground, so its wrong-window risk is low by design). Not measured: real RPC counts per conform (needs Resolve), the `_scan_pool` lock hold on a 5,000-clip pool (estimated ~1 s per 120 s at ~0.1 ms per RPC), Postgres lock/xmin state for finding 1 (would need the live library).

## OUT OF TERRITORY
- `ccsync companion/src/ccsync_companion/resolve_bridge.py:1394`: `library_timeline_items` takes 4 head RPCs under `_API_LOCK` per call; with finding 4 unfixed that is every second per machine.
- `multicam_pipeline/cards/library_engine.py:4942`: `_publish_locked` is where finding 2's fix lands (library-engine hunter's file).
