# bug-comp-resolve - companion Resolve bridge, journal/undo, prefs, script-server guard, fixer, proxy relink, watcher, LUTs, consolidate, project setup, Timeline Cards role/bridge, project library
Files read (approximate coverage): script_server.py (all), resolve_journal.py (all), resolve_undo.py (all), resolve_prefs.py (all), timeline_cards_bridge.py (all), luts.py (~85%), project_setup.py (~85%), watcher.py (~90%), fixer.py (~65%: copy/claim/verify/fix_clip), proxy_relink.py (~60%: plan_relinks, refusals, apply_relinks), consolidate.py (~60%), timeline_cards_role.py (~75%), library.py (~50%: ProjectLibrary), resolve_bridge.py (~50%: connect/probe, library walk, timeline + pool walks, uid map, save point, replace_clip, link/unlink proxy, undo, _attach_adjacent_proxy). Not read: perform_insert/_place_at_playhead, import_files_to_bin_path, library.py blob decoding/locate.
Tests/probes run: companion venv snippets only (no Resolve, no scriptapp): (1) every DISCONNECTION_MESSAGE through resolve_undo.apply_undo; (2) current_project_name across a faked project switch; (3) CardsBridge.sweep_items with the library walk unavailable, counting API walks.

## Findings

### bug-comp-resolve-1 - An admin's undo sent during Resolve's launch window is recorded FAILED and never retried
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/resolve_undo.py:228-235 (and resolve_bridge.py:507 STARTING_MESSAGE)
- What: apply_undo classifies the bridge's refusal by prose. STARTING_MESSAGE ("DaVinci Resolve is starting up", the CR-68 launch-window answer) contains no PARK_HINTS/RETRY_HINTS substring and no "not", so it falls through to "failed". The other three disconnection messages all map to "retrying"; this one, added for CR-68 after RES-4 wrote the hint lists, was never added.
- Failure scenario: admin presses [ UNDO THIS CHANGE ] for a machine; the command arrives on a report while the editor's Resolve is in its 90-470 s launch window (script server up, host not registered). undo_last_relink -> get_media_pool_items -> "DaVinci Resolve is starting up" -> apply_undo returns (False, ..., "failed"); the ledger records it and the dashboard retires the command. The wrong clip paths stay, and the admin is told it failed although nothing was wrong except timing.
- Evidence: snippet over resolve_bridge.DISCONNECTION_MESSAGES: not running -> retrying, no scripting -> retrying, open-but-no-server -> retrying, "DaVinci Resolve is starting up" -> failed.
- Ledger: new (related to RES-4 / CR-68)
- Suggested fix: test `resolve_bridge.is_disconnection_message(message)` first and answer retrying for all of them, rather than extending the substring lists again.

### bug-comp-resolve-2 - The 20 s project-name cache files a relink under the PREVIOUS project: wrong journal, wrong save point, wrong rate limiter, and the cross-project undo hazard comes back
- Severity: medium
- Confidence: CONFIRMED (mechanism); the timing window is realistic, not measured live
- Where: companion/src/ccsync_companion/resolve_bridge.py:2130-2153 (current_project_name), 2223-2245 (_before_mutation), 3050; callers app.py:3258, 4653
- What: current_project_name() caches the name for 20 s with no invalidation on project change. _before_mutation (every replace_clip/link_proxy_media), the automatic canon-relink and proxy-relink rate limiters, and _attach_adjacent_proxy's journal entry all read that cache. The tray undo-summary render and the 120 s proxy pass keep refreshing it. After a project switch inside the window, save_project(name) exports the OLD project by name (ExportProject(name, ...)), the journal entries go under the old project's slug, and allow_automatic spends the old project's allowance.
- Failure scenario: editor has project A open (cache = A, e.g. from the tray menu or the proxy pass), switches to B; within seconds the watcher offers B's non-canonical clips and the unprompted relink runs. The journal records B's rewrites as project A. In B, Undo says "CCSync has not changed any clip paths in B ... open A and undo there". In A, undo_last_relink's journal-vs-open-project check passes (A == A) and replays B's entries against A's pool by path. Shared Assets paths (music beds, archive b-roll) match, so A's clips are rewritten to B's old spellings, unjournalled. This is comp-resolve-2 (2026-08-21) reopened through the cache.
- Evidence: snippet: fake Resolve returning project A, then B -> current_project_name() returned "A" after the switch.
- Ledger: new (reintroduces the hazard fixed as comp-resolve-2 / CR-51)
- Suggested fix: in _before_mutation (and the two app.py limiter calls) read the name with max_age=0, or key the cache on the project object/uid and drop it when the watcher reports a project change; the pool/timeline walk already carries project_name and could be passed through.

### bug-comp-resolve-3 - Timeline Cards' sweep_items runs resolve_bridge's API walk under _API_LOCK on every machine without a library, then throws the answer away, and speeds up the watcher's full-walk valve
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/timeline_cards_bridge.py:239-260; resolve_bridge.py:1235-1239, 1300-1312
- What: sweep_items calls resolve_bridge.get_timeline_items(allow_cached=True). When the library walk returns None (walk off, no library found, 60 s backoff after a failure) get_timeline_items falls through to _get_timeline_items_locked, the API walk under _API_LOCK, and sweep_items then discards the result because its items are source "api". Its own docstring says taking that walk "would be slower than the engine's own", but the check runs after the walk. It also shares the watcher's poll cache: every cache hit bumps _polls_since_full_walk, so with a 1 s sweep plus a 3 s watcher the "full walk every 10th poll" valve fires about every 7-8 s instead of about 30 s. That per-clip walk (up to 11 s on a large timeline, under the lock) then runs roughly four times as often.
- Failure scenario: cards_agent on, on a machine whose library cannot be read (disk library with no reader, laptop off the NAS network, 60 s after any library error). Every engine sweep costs a lock-held track walk plus the engine's own API walk, and a full per-clip walk lands every ~8 s. The tray, watcher and card clicks queue behind it. That is the starvation §3.1 of the plan exists to prevent, and the bridge's stats() blame the engine's own take.
- Evidence: snippet with _library_timeline_items forced to None: sweep_items('T') returned None and one API walk ran (calls == [True]).
- Ledger: new
- Suggested fix: in sweep_items, return None before calling get_timeline_items when library_status()/_library_attempt_due() says no library answer is possible, or give resolve_bridge a library-only entry point that never falls back to the API walk.

### bug-comp-resolve-4 - Restarting the Cards role after ONE loop dies leaves the other loop running on the released engine
- Severity: medium
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/timeline_cards_role.py:782-800, 805-817, 866-938
- What: regression-8 made supervise_now restart the role as soon as any loop died (all() plus _loop_error). _clear_dead then drops the thread list, calls engine.stop() and starts a new engine and client. But the surviving loop of the old client (for example pull_loop, still long-polling) is a daemon thread that nothing can stop, and role.call serves any caller: it does not check that the calling client is the current one. The old pull loop keeps taking /cards/agent/pending commands and applying them through the stopped engine, which shares the same CardsBridge. Per CLAUDE.md, upstream stop() only sets a flag the engine's worker threads do not read.
- Failure scenario: the push loop dies of an exception from the other repo. Within 60 s the watchdog starts engine #2 with new push and pull loops. The machine now has two pull loops draining one queue: some staged edits are applied by engine #1 (stopped, stale state) and some by engine #2, possibly at the same moment. That is two Timeline Cards engines driving one Resolve with synthetic keystrokes, the breach the role's comments say it prevents.
- Evidence: code reading. No stop hook on the AgentClient loops; role.call has no generation check; _clear_dead joins nothing.
- Ledger: new (related to regression-8 / comp-resolve-4 2026-09-11)
- Suggested fix: give each client a generation token and have role.call raise CardsTunnelError for a client whose generation is not current. That makes the orphaned loop back off and die instead of fetching work. Or restart only when all loops are dead, and report the half-dead state without starting a second engine.

### bug-comp-resolve-5 - On macOS the CR-68 probe spawns lsof while holding _API_LOCK
- Severity: low
- Confidence: CONFIRMED (code path)
- Where: companion/src/ccsync_companion/resolve_bridge.py:351-361 -> script_server.py:306-318
- What: connect() calls script_server.state() inside `with _bridge_call("connect")`. On Darwin the probe is a `lsof` subprocess with a 5 s timeout, re-run every time the 250 ms cache expires. That breaks this module's own rule (lines 497-500: "a subprocess must never run with the bridge lock held"). Every public call connects first, so each one can pay a spawn under the lock.
- Failure scenario: on a Mac, a slow lsof (a large fd table or a busy system; the timeout allows 5 s) blocks the watcher, the pool refresh, the b-roll insert and the Cards sweep behind the lock for as long as the spawn takes, several times a second while Cards is on. The wedge warning then names "connect".
- Evidence: code reading.
- Ledger: new
- Suggested fix: ask script_server.state() before taking _API_LOCK (it is lock-free and cached), and only take the lock for the import/scriptapp half.

### bug-comp-resolve-6 - An SMB blip at the reservation re-check leaves the original 0-byte reservation behind for good
- Severity: low
- Confidence: CONFIRMED (code path; needs an OSError from stat)
- Where: companion/src/ccsync_companion/fixer.py:1026-1040, 1358-1361; sweep at 831-904
- What: when `dest_path.stat()` raises, reclaim_if_reservation_lost claims a fresh name and returns it. The original 0-byte O_EXCL reservation, which is ours and empty, is neither removed nor tracked. The copy is then os.replace'd into "name (2).ext", so no `.ccsync-tmp` is left beside the original, and sweep_orphan_reservations only finds reservations through such a tmp.
- Failure scenario: a stat blip at the end of a long FIX ALL copy leaves `clip.braw` as 0 bytes next to `clip (2).braw`. Lane A uploads the 0-byte file after --min-age, --ignore-existing makes it permanent, and lane C fans it out. That is the COMP-GUARD-1 outcome through a path its sweep cannot see.
- Evidence: code reading.
- Ledger: new (related to COMP-GUARD-1 / DEL-7)
- Suggested fix: after claiming the fresh name, try remove_reserved_name(old reservation). It already refuses anything that is not empty.

### bug-comp-resolve-7 - The uid-map cache keys on `project is <cached object>`, which a fresh GetCurrentProject() wrapper probably never satisfies
- Severity: low
- Confidence: PLAUSIBLE (cannot be checked without calling Resolve)
- Where: companion/src/ccsync_companion/resolve_bridge.py:2016-2019
- What: every call path runs connect() (a new scriptapp) and GetCurrentProject() again, and fusionscript hands back a new proxy object each time as far as is known. If so, the identity test fails on every call, the 60 s cache never hits, and every media_pool_item_by_uid and every 100-clip enrichment chunk walks the whole pool. The design ("a FIX ALL over 50 clips pays for one walk, not 50") assumes the opposite; the tests pass because their fakes return one object.
- Failure scenario: FIX ALL over 50 clips = 50 full pool walks under _API_LOCK. A 1,300-clip enrichment = 13 walks instead of 1.
- Evidence: code reading plus the module's own measurements (~0.15 s per walk). Identity semantics not verified live.
- Ledger: new
- Suggested fix: confirm on a live Resolve (`pm.GetCurrentProject() is pm.GetCurrentProject()`). If it is False, key the cache on something the API returns stably (project name plus GetUniqueId(), or the timeline uid), with the TTL as the backstop.

### bug-comp-resolve-8 - The library finds the project by NAME only, so a same-named project in another folder supplies the pool
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/library.py:629-639
- What: `SELECT SM_Project_id FROM SM_Project WHERE ProjectName = :name` takes rows[0]. Resolve allows the same project name in different project-manager folders. The comment says this is "no worse than the API, which cannot tell them apart", but the API always answers for the OPEN project. pool_items and changed() then read another project's media pool and fingerprint. timeline_items is unaffected because it is keyed by timeline uid.
- Failure scenario: two "Interviews" projects in different folders. The pool walk returns the other one's clips. Proxy relink and non-canonical classification plan ops on uids that are not in the open pool, so every op fails as "not in the media pool" and the clips that are really in the pool are never considered.
- Evidence: code reading.
- Ledger: new
- Suggested fix: when more than one row matches, refuse (LibraryUnavailable, so the API walk answers) unless it can be disambiguated, for example by checking that the open timeline's uid belongs to the candidate project.

### bug-comp-resolve-9 - LUT adoption leaves `<name>.ccsync-tmp` behind on a failed copy
- Severity: low
- Confidence: CONFIRMED (code path)
- Where: companion/src/ccsync_companion/luts.py:377-382
- What: copy_into_library writes to a fixed `dest.ccsync-tmp` and has no cleanup when shutil.copy2 or os.replace raises. The OSError is recorded and the tmp stays inside the Syncthing-shared LUT library. It is ignored by .stignore, but it is never removed.
- Failure scenario: disk full or a locked destination during Adopt leaves a partial `.cube.ccsync-tmp` in P:\Assets\Luts on that machine for good.
- Evidence: code reading.
- Ledger: new
- Suggested fix: unlink the tmp in the except branch, as resolve_journal._write does.

## Coverage note
Not reviewed: the b-roll insert path (perform_insert, _place_at_playhead, _overlay_track, import_files_to_bin_path, _canonicalize_imported), library.py's blob decoding and locate(), proxy_relink._geometry_disagrees and the fleet stand-in memory, the rest of fixer.py (match_project_dir, list_destination_dirs, IgnoreTracker), timeline_cards_role health()/report_block(), and consolidate.run_consolidation. None of the NFC/NFD concerns in replace_clip's "took" comparison (Resolve's File Path against the path we passed, on a Mac) could be settled without a live Mac Resolve, so they are not reported.

## OUT OF TERRITORY
- companion/src/ccsync_companion/app.py:3258 / 4653: the unprompted relink limiters take the project name from the cached current_project_name(), not from the poll result that triggered them (see bug-comp-resolve-2).
