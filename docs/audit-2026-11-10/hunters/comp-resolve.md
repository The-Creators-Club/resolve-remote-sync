# comp-resolve - the companion's Resolve side: bridge, watcher, pool walk, relinks, journal, CR-68 probe, Cards role, file moves, YouTube import
Files read (approximate coverage): resolve_bridge.py (lines 1-2770 of 3934: lock, connect, CR-68 gate, disconnection, library walk, timeline + pool walks, uid map, save point, replace_clip, link_proxy_media), watcher.py (all), script_server.py (all), timeline_cards_bridge.py (all), timeline_cards_role.py (~60%: gate, probe, watchdog, start), resolve_journal.py (~85%), file_moves.py (relink_moved + FileMoveLedger), youtube_import.py (all), library.py (change detection + timeline walk), proxy_relink.py (find_proxy_on_disk, refusals, plan_relinks), vp9_guard.py (observe/evaluate/cache), fixer.py (list_project_dirs, walk_ccsync_tmp_files), proxy_scan.py (scan_project/scan_missing_proxies), paths.py classify_path (the watcher's per-clip cost), app.py callers (_refresh_media_tree_once, _relink_proxies_once, _media_tree_loop, _relink_pending_moves, startup tmp sweep). Not read: consolidate.py, luts.py beyond the index walk, stills.py, project_setup.py, resolve_undo.py, resolve_prefs.py beyond resolve_is_running, resolve_menu_install.py, proxy_history.py, resolve_bridge.py 2770-3934 (undo replay, insert, import-to-bin).
Probes run (all under the scratchpad `comp-resolve\`, companion venv, `-I`; no Resolve call, no scriptapp, nothing under ~/.ccsync written):
- `probe.py`: script_server's Windows probe on this machine, 200 iterations: TCP table 0.27 ms (173 rows), Toolhelp process snapshot 8.41 ms (498 processes), whole probe 9.23 ms wall / 9.14 ms CPU; answer `absent`.
- tasklist `/FI IMAGENAME eq Resolve.exe`: ~209 ms wall, ~19 ms CPU of its own.
- `cim.py`: the Cards role's `Get-CimInstance Win32_Process` PowerShell probe: 441-504 ms wall, ~520 lines / 114 KB of stdout per run (PowerShell itself ~220 ms CPU).
- `journal_probe.py`: resolve_journal.record() with HOME redirected to the scratchpad: 500 entries 1.15 s (2.3 ms avg), 1,000 entries 3.74 s, 2,000 entries 13.94 s (7.0 ms avg, file 779 KB).
- `classify_probe.py`: os.path.exists + os.path.realpath over 2,000 files on local NTFS: 57 ms + 102 ms.
- `walk_probe.py`: fixer.walk_ccsync_tmp_files over a synthetic 50,000-file tree: 0.12-0.35 s locally.
- netstat on this rig: Resolve.exe is running with NO listener on 1144 (the ABSENT state), so the live TIME_WAIT trail could not be re-measured; the figure used below is the one LAG-INVESTIGATION recorded.

## Findings

### comp-resolve-1 - The 120 s media-tree refresh re-reads every pool clip's proxy state through Resolve, unchanged pool or not
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (mechanism, read); cost from the repo's own measurements, scaled (estimated)
- Where: companion/src/ccsync_companion/resolve_bridge.py:1909 (`_library_media_pool_items` -> `_enrich_proxy_keys`), :2006-2039 (chunk loop), :2188-2219 (uid map), :1881 (API fallback); caller app.py:4759/:5241 (`_refresh_media_tree_once` every `media_tree_refresh_interval` = 120 s)
- What: even when the project library answers the pool walk in milliseconds, `_enrich_proxy_keys` asks Resolve for `Proxy Media Path` and `Proxy` (plus `Frames` for archive clips) on EVERY clip of the pool on every 120 s pass, and nothing remembers last pass's answers. Each 100-clip chunk re-runs `_current_project_locked()` (a fresh `scriptapp()`, see comp-resolve-2), and the first chunk rebuilds the uid map (GetClipList per bin + GetUniqueId per clip) in ONE `_API_LOCK` hold because the map's TTL (60 s) is shorter than the refresh (120 s). On a machine with no readable library the API walk does 5 RPCs per clip inside a single lock hold for the whole pool.
- Cost / failure scenario: measured in-tree (comment at :1999) 5.5 s of property reads for 1,298 clips. Today (1-4k-clip pools): 5-17 s of Resolve API time every 120 s, i.e. 5-15 % of Resolve's scripting capacity at idle, plus 13-40 fresh connections per pass. At the brief's 20,000-clip project: ~85 s of reads + ~2.3 s single-hold uid walk + 200 connects (~13 s) per 120 s pass, i.e. Resolve's API busy ~80 % of the time with nobody editing; the API-fallback machine holds `_API_LOCK` for one ~145 s stretch per pass (9.4 s per 1,298 clips, GOTCHAS section 16, scaled), so the watcher, b-roll insert and Cards queue behind it and Resolve's UI stalls (GOTCHAS 16: other clients went 0.3 s -> 7 s under a 11-14 s walk).
- Evidence: resolve_bridge.py:1929-1935 (no change gate on the pool read, by design), :2006-2030 (per-chunk connect + per-clip reads), :2139 (`_MEDIA_POOL_UID_TTL_SECONDS = 60.0`) vs app.py:2102 (120 s); proxy_relink.plan_relinks only acts on clips whose proxy is NOT working (proxy_relink.py:835).
- Ledger: new (GOTCHAS 16 records the 5.5 s and the chunking; nothing records the per-pass repetition or the 20k cliff)
- Suggested change: keep a per-project `uid -> (proxy_path, proxy_state, frames)` memo from the last pass and re-read only clips that are new, whose last state was not a working proxy, or whose library row changed (`ProjectLibrary.changed()` already fires on DbSavedTime), plus a full re-read every Nth pass as the safety valve the watcher already uses; set the uid-map TTL above the refresh interval. Must not hand out a half-enriched list (the `return False` contract at :2018) and must keep enrichment off `_LIBRARY_LOCK`.
- Effort / risk: M effort; medium risk (a stale "working" answer would hide a proxy that went offline until the valve pass)

### comp-resolve-2 - Every bridge call opens a brand-new scriptapp() connection: once a second with the Cards role on, every 3 s from the watcher, once per enrichment chunk and once per relinked clip
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (mechanism); per-connect cost measured in the other repo (75 ms including the guard)
- Where: companion/src/ccsync_companion/resolve_bridge.py:391-461 (`connect()`, module docstring line 7-9 "lazy-connect on every call rather than caching"), callers :1309, :1516 (watcher + Cards sweep via `_timeline_head_locked`), :1650, :2009 (per enrichment chunk), :2331 (`current_project_name`, forced fresh per mutation at :2421)
- What: `connect()` calls `dvr_script.scriptapp("Resolve")` every time; there is no cached handle. Each call is a TCP connect to 1144, a HostApp create/destroy inside fuscript, a second connection to Resolve's port, and a TIME_WAIT socket afterwards. The Timeline Cards engine in the SAME process keeps one steady connection (MulticamPipeline cards/resolve_engine.py:265 `self._resolve`), yet its 1 s sweep goes through `library_timeline_items()` -> `_timeline_head_locked()` -> `connect()` and opens a new one every second.
- Cost / failure scenario: LAG-INVESTIGATION.md:138-148 measured one guarded connect at 75 ms (~65 ms of it scriptapp after the ~9 ms probe here) and 49 TIME_WAIT sockets on 1144 at any moment, with the companion at "~38 % of a core at idle" (:418-419, unexplained there). Watcher alone: 20 connects/min = ~1.3 s/min of `_API_LOCK` spent connecting; with the Cards role on: +60/min = ~5 s/min; a 1,300-op auto proxy relink adds 1,300 connects (~85 s) via `_before_mutation`; a 20k-clip enrichment pass adds 200. Every one of those is a moment the lock is held and Resolve's single scripting thread does session setup.
- Evidence: resolve_bridge.py:452 (scriptapp per call, no module-level handle anywhere); LAG-INVESTIGATION.md:54-55 ("Every poll opens a fresh scriptapp ... one every 3.04 s"), :145-146 (Cards holds one steady connection).
- Ledger: new (CR-68 is about WHEN to connect; nothing addresses how OFTEN)
- Suggested change: cache the scriptapp object in `connect()` keyed on the fuscript listener pid / Resolve pid that `script_server.classify` already sees; reuse it while every probe answers READY with the same pids, and drop it on any non-READY answer, a pid change, an exception from the first call on it, or `GetProjectManager()` returning None. That keeps CR-68 (no connect outside READY/UNKNOWN) and R12 (the stale-bridge restart still fires when Resolve exits, and a changed pid can never reuse the old handle). Optionally let `_enrich_proxy_keys` take the project once per pass instead of per chunk.
- Effort / risk: M effort; medium risk (fusionscript object lifetime across a Resolve restart is exactly the R12 hazard, hence the pid key)

### comp-resolve-3 - The watcher stats AND realpaths every timeline clip every 3 s, even when the Resolve answer came from the poll cache
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (code path); SMB multiplier estimated
- Where: companion/src/ccsync_companion/watcher.py:380-384 -> paths.py:306-348 (`classify_path`: `os.path.exists` at :307, `os.path.realpath` at :338)
- What: the poll cache (resolve_bridge.py:1477) saves the Resolve calls on 9 of 10 polls, but the watcher then classifies every item again, and for every clip stored under the canonical prefix that is not textually under local_root (every clip on a remote editor rig, where P: is the `\\localhost\CCSync_P` loopback share) that is one exists() plus, for present files, one realpath() - a CreateFile + GetFinalPathNameByHandle through the SMB redirector - per clip per poll. The per-file realpath is redundant whenever `_prefix_resolves_under_root` (cached, :346) says the prefix maps under local_root, which is the fallback the function reaches anyway.
- Cost / failure scenario: measured 2,000 files on local NTFS: 57 ms exists + 102 ms realpath = ~160 ms per poll, every 3 s = ~5 % of one core continuously on a 2,000-item timeline, on the thread the popup latency depends on; through loopback SMB each op costs several times more (estimated 3-10x, so 0.5-1.6 s per 3 s poll). At the 20k-item timelines the brief asks about it no longer fits in the 3 s interval.
- Evidence: probe `classify_probe.py`; paths.py:158-163 (`_delooped` exists because realpath of P: answers `\\localhost\CCSync_P\...`); watcher.py:169-171 already memoises the archive/proxy questions for exactly this reason (comp-resolve-7, 2026-09-18) but not the classification itself.
- Ledger: related to comp-resolve-7 (2026-09-18, the archive-exemption memo; FIXED, different question)
- Suggested change: in classify_path, test the cached prefix verdict BEFORE the per-file realpath (a file under a healthy prefix is OK without resolving it), and in the watcher memoise `(path) -> class` for OK/MISSING across polls with the same TTL/cap as `_exempt_memo`, dropped when the bridge's poll cache does its full walk. Must keep BAD_PREFIX detection (the prefix check still runs each poll) and must not memoise OUT_OF_TREE/FOREIGN offers.
- Effort / risk: S effort; low risk

### comp-resolve-4 - A project switch runs one full media-pool walk PER pending file move, synchronously on the watcher thread
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (read)
- Where: companion/src/ccsync_companion/app.py:2692-2700 (`_on_resolve_project_changed` -> `_relink_pending_moves`, called from watcher.py:336-338), app.py:9445-9450, file_moves.py:953 (`relink_moved` -> `resolve_bridge.get_media_pool_items()`)
- What: for each `pending_relinks()` entry (up to 30 days old, ledger capped at 200) whose destination exists, `_relink_pending_moves` calls `relink_moved`, which performs a complete `get_media_pool_items()` - library read plus the comp-resolve-1 proxy enrichment, or the whole API walk under one lock hold - and then scans it for that one move's old path. K pending moves = K full walks of the SAME pool, back to back, inside the watcher's `poll_once`. A move in a project the editor rarely opens stays pending (only a match retires it), so every switch between two OTHER projects pays it again.
- Cost / failure scenario: 10 pending moves on a 1,300-clip project: 10 x (5.5 s enrichment, or 9.4 s API walk) = 55-94 s in which the watcher does not poll (no out-of-tree popup, no project name to the dashboard, LaneWatchdog heartbeat stale) and Resolve's scripting is saturated; on a 20k-clip pool, tens of minutes per project switch.
- Evidence: app.py:9445-9456 (loop, one `_relink_moved_result` per entry), file_moves.py:953 (walk inside the per-move function), file_moves.py:1279-1297 (pending until matched, 30-day window).
- Ledger: new (RES-10 added the re-run; nobody costed it)
- Suggested change: walk the pool once per `_relink_pending_moves` call and match every pending entry against that one list (`relink_moved` taking an optional pre-walked `items`), and run it on a worker thread rather than inside the watcher callback. Must keep "only a walk that FOUND the old path retires the entry".
- Effort / risk: S effort; low risk

### comp-resolve-5 - Every relink builds Resolve's full 60-key property dict two to four times, plus a fresh connection, while the cheap one-arg reader sits unused
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (read; per-call costs are GOTCHAS 16's measurements)
- Where: companion/src/ccsync_companion/resolve_bridge.py:2489-2510 (`replace_clip`'s `_file_path_locked`/`_geometry_locked`), :2675 and :2685 (`link_proxy_media` via `_safe_clip_property`), :2722 (`clip_proxy_state`), :2727-2737 (`_safe_clip_property` = no-arg GetClipProperty), :2421 (`current_project_name(max_age=0.0)` per mutation)
- What: these readers call `GetClipProperty()` with no argument, citing "the one-arg form is not implemented by every API build" - but `_clip_property` (:949) already probes the one-arg overload once per process and falls back to the dict, and is used by both walks. replace_clip does 2 dict builds per attempt (4 with `force`), link_proxy_media 2, clip_proxy_state 1, each 12.5 ms under `_API_LOCK`; `_before_mutation` adds a forced fresh `connect()` + 3 RPCs per clip.
- Cost / failure scenario: GOTCHAS 16: 12.5 ms per dict vs 0.1 ms one-arg. FIX ALL / auto proxy relink of 1,300 clips (the size the 2026-08-26 review named): 1,300 x (25-50 ms dict + ~65 ms connect) = ~2-2.5 minutes of extra lock time, every one of those holds blocking the watcher, the b-roll insert and Cards; with the phase-3 stand-in refresh (`force`) the geometry reads double it.
- Evidence: resolve_bridge.py:942-986 (the probed reader), :2489-2510, :2727-2737; GOTCHAS.md:1056-1064.
- Ledger: new
- Suggested change: route `_file_path_locked`, `_geometry_locked`, `_safe_clip_property` and `clip_proxy_state` through `_clip_property` (two one-arg reads for geometry), and let `_before_mutation` reuse the cached handle from comp-resolve-2 (the max_age=0 project check stays; only the reconnect goes). Must keep "File Path changed" as the success test.
- Effort / risk: S effort; low risk

### comp-resolve-6 - The undo journal rewrites the whole JSON file for every entry (quadratic)
- Category: perf / disk-growth
- Severity: low
- Confidence: CONFIRMED (measured)
- Where: companion/src/ccsync_companion/resolve_journal.py:505-526 (`record`: `_read` + append + `_write` with `indent=1` per entry)
- What: each relink re-parses and re-writes the burst's entire journal through tmp + os.replace. Cost per entry grows with the file, so a burst is O(n^2) in CPU and in bytes written.
- Cost / failure scenario: measured 1,000 entries 3.7 s, 2,000 entries 13.9 s (last entries ~12 ms each), final file 779 KB, so ~780 MB written to the editor's SSD for one 2,000-clip pass; at the 5,000-entry cap, estimated ~85 s and ~2 GB. The time is spent on the FIX ALL / proxy-relink thread between Resolve calls (outside `_API_LOCK`, so it slows the pass rather than Resolve).
- Evidence: probe `journal_probe.py` (HOME redirected to scratch).
- Ledger: related to bug-hunt-2026-09-03 comp-resolve-1 (the lock around the RMW; FIXED, unchanged here)
- Suggested change: keep the open burst's dict in memory (`_sessions`) and write it from there without re-reading, without `indent`, and coalesced (write at most every N entries or 1 s, plus at burst end and before an undo reads it); or append JSON lines to a sidecar and compact at burst end. Must keep the file valid JSON for `read_session` after a crash, and keep the read-before-undo path seeing every acknowledged entry.
- Effort / risk: S effort; low risk

### comp-resolve-7 - The CR-68 probe snapshots every process on the machine even when nothing listens on 1144, and the disconnection text spawns tasklist every 30 s on top
- Category: idle
- Severity: low
- Confidence: CONFIRMED (measured)
- Where: companion/src/ccsync_companion/script_server.py:327-336 (`_probe_uncached` always calls `_windows_processes()`), :148-151 (ABSENT needs only the TCP rows); resolve_bridge.py:640-665 + resolve_prefs.py:158 (`tasklist` spawn, 30 s TTL)
- What: ABSENT (Resolve closed, or open with dead scripting as on this rig right now) is decided from the TCP table alone, yet every probe also walks a Toolhelp snapshot of all processes. Separately, every failed poll calls `describe_disconnection()`, whose `_resolve_process_present()` spawns `tasklist` whenever its 30 s cache lapses - a question the snapshot just answered in-process.
- Cost / failure scenario: measured 9.2 ms CPU per probe, 8.4 ms of it the snapshot; at least one probe per 3 s watcher poll (more with the Cards sweep and the 120 s refresh) = ~260 s CPU/day per machine; plus 2 tasklist spawns/min (~209 ms wall, ~19 ms own CPU each) = 2,880 process spawns a day on any machine where Resolve is closed or unscriptable - nights, weekends, the base rig.
- Evidence: probe `probe.py` (tcp 0.27 ms vs processes 8.41 ms); tasklist timing.
- Ledger: new
- Suggested change: in `_probe_uncached`, return ABSENT straight from the TCP rows when no row listens on 1144 and only then take the snapshot (or OpenProcess just the listener and client pids); have `_resolve_process_present` reuse a Toolhelp snapshot (`script_server._windows_processes`) instead of spawning tasklist, keeping its fail-closed bias. Must keep READY/STARTING classification byte-identical.
- Effort / risk: S effort; low risk

### comp-resolve-8 - The Cards role's refusal watchdog runs PowerShell + WMI every 60 s for as long as a standalone agent is running
- Category: idle
- Severity: low
- Confidence: CONFIRMED (measured)
- Where: companion/src/ccsync_companion/timeline_cards_role.py:325-365 (`running_command_lines`), :548-564 (60 s cache), :798-806 (`_supervise` re-asks every `PROBE_CACHE_SECONDS`)
- What: on a machine with `cards_agent` on whose role is refused because the standalone `reorder_web.py --agent` is running (the base rig's normal state while the standalone agent drives Resolve), the watchdog launches `powershell Get-CimInstance Win32_Process` every minute, indefinitely, to re-read every process's command line.
- Cost / failure scenario: measured 441-504 ms wall per run, ~114 KB of output, a PowerShell start (~220 ms CPU) plus WmiPrvSE work: 1,440 PowerShell launches a day, each a short CPU burst on the editing machine beside Resolve.
- Evidence: probe `cim.py`.
- Ledger: related to RES-7 (2026-09-04, re-ask by design; the cadence is not the finding, the probe weight is)
- Suggested change: take the Toolhelp snapshot (already in script_server.py) and only when a python/pythonw/node process exists ask CIM for THOSE pids' command lines (`-Filter "ProcessId=..."`), or read them with NtQueryInformationProcess via ctypes; keep "cannot tell" = refuse (fail closed).
- Effort / risk: S effort; low risk

### comp-resolve-9 - plan_relinks re-stats up to four proxy candidates for every clip without a working proxy on every 120 s pass, with no memory
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE (mechanism read; SMB cost estimated)
- Where: companion/src/ccsync_companion/proxy_relink.py:842-843 -> :187-216 (`find_proxy_on_disk`: 2 extensions x 2 spellings), called from app.py:5125 every media-tree refresh with `exists_fn=os.path.exists`
- What: the watcher memoises this exact question for 60 s (watcher.py:194/:668, comp-resolve-7 2026-09-18) but the relink planner asks it afresh for every clip whose proxy is not working, every pass; `app._media_presence` (ops-efficiency-8) caches the ORIGINALS' presence but not the proxies'.
- Cost / failure scenario: a wired rig (local_root on the SMB share) with a 5,000-clip pool that has no Proxy/ files: up to 20,000 failed SMB stats every 120 s (~1-2 ms each over LAN, estimated 20-40 s of the media-tree thread per pass); 80,000 at 20k clips, which exceeds the 120 s interval.
- Evidence: proxy_relink.py:203-215; app.py:5129.
- Ledger: related to ops-efficiency-8 / CR-66 (FIXED for originals only)
- Suggested change: list each distinct `Proxy/` directory once per pass (one listdir, set lookup) instead of 2-4 stats per clip, or share the watcher's TTL memo; absent answers may be cached for one pass at most so a lane B arrival is still seen next pass.
- Effort / risk: S effort; low risk

### comp-resolve-10 - Every companion start walks the whole of local_root for *.ccsync-tmp, which on the base rig and wired rigs is the NAS share
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE (mechanism read, local cost measured, SMB cost estimated)
- Where: companion/src/ccsync_companion/fixer.py:784-810 (`walk_ccsync_tmp_files`, os.walk of local_root), started at app.py:10584-10587
- What: to find the partials and 0-byte reservations an interrupted FIX ALL could leave, startup walks every directory under local_root. Where local_root is the SMB share (the base rig's P:, wired rigs), that is a full NAS tree enumeration on every start - and starts are frequent (supervisor relaunch after a crash, every OTA, every stale-bridge self-restart after Resolve quits).
- Cost / failure scenario: 50,000 files locally 0.12-0.35 s (measured); over SMB a directory listing is a round trip, so 100 projects x ~200 directories at 2-10 ms = estimated 40-200 s of NAS metadata load per start, at 500 projects proportionally more; harmless to correctness (background thread) but it is load on the one NAS every editor syncs through, multiplied by every wired machine restarting after each Resolve quit.
- Evidence: fixer.py:795; app.py:10581-10587; `_maybe_recover_stale_bridge` (app.py:4966) restarts the companion whenever its Resolve exits.
- Ledger: new
- Suggested change: have fix_clip append each tmp/reservation path it creates to a small state file and sweep only those (removing them on success), keeping the full walk only when that file is missing (first run of the new build) or local_root is a local disk.
- Effort / risk: S effort; low risk

## What is already good
- The CR-68 gate itself: one chokepoint, probe primed OUTSIDE `_API_LOCK` (bug-comp-resolve-5), 250 ms cache, fail-open only on UNKNOWN. Make it cheaper (comp-resolve-7), never looser.
- The library walk for the TIMELINE: DB reads never under `_API_LOCK`, retry back-off, 60 s staleness valve, Cards sweep reading the cache with `count_poll=False`; per-poll Resolve cost there is 6 RPCs plus the connect.
- Watcher memory is well bounded: every set/dict has a cap or is rebuilt per pass (`_missing_logged`, `_rearm_due` 2,000, refusals 200, memos 4,000); warn-once latches and the transition-only bridge log keep idle logging at zero.
- youtube_import idles cheaply: 15 s tick of pure arithmetic, a two-level listdir + stat once a minute only when a project is open and mapped, mapping memoised per scan interval.
- vp9_guard's work is off the watcher thread, signature-gated to once per 120 s, codec cache keyed by (path, size, mtime) and capped.

## Coverage note
Not read: resolve_bridge.py 2770-3934 (undo replay, perform_insert, import_files_to_bin_path), consolidate.py, luts.py (only library_index), stills.py, project_setup.py, resolve_undo.py, resolve_menu_install.py, proxy_history.py, most of resolve_prefs.py. proxy_scan.py was read but not costed: it stats 2-4 proxy candidates per original on every 15-min scan on top of the manifest's own walk (its docstring says so); a per-directory listdir would likely help the base rig, unmeasured. The API-walk timeline fingerprint (GetItemListInTrack per track every 3 s) could not be measured without Resolve scripting.

## OUT OF TERRITORY
- companion/src/ccsync_companion/paths.py:338: per-clip `os.path.realpath` on every classification (reported here as comp-resolve-3 because the watcher is its hot caller).
- companion/src/ccsync_companion/app.py:4759: `_refresh_media_tree_once` runs the stale-bridge recovery, the relink and the classify passes serially on one 120 s thread; any one slow pass (comp-resolve-1, -9) delays the others.
- E:\Projects\Editing\Resolve\MulticamPipeline\docs\LAG-INVESTIGATION.md:418: "~38 % of a core at idle" for the companion was recorded and never chased; comp-resolve-2/-3/-7 are candidate contributors.
