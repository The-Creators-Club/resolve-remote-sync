# Wave 2 ledger - c-resolve

## Chunk 1 (builder c-resolve, 2026-09-25)

All eight are MEDIUMs the verifiers CONFIRMED (verdicts.json). New tests:
`companion/tests/test_bug_hunt_2026_09_24_w2_c-resolve.py` (26 tests). Against
HEAD: `git archive HEAD companion/src companion/tests companion/pyproject.toml`
into the scratchpad, the new test file copied in, same venv -> 25 failed,
1 passed (the passing one is `test_a_real_refusal_still_fails`, a guard that a
genuine refusal still answers `failed`). On this tree: 26 passed.

Tests run (companion venv, from `companion/`): the new file plus
test_bug_hunt_2026_09_11_comp_resolve, _11b_comp_resolve, _18_companion,
test_consolidate, test_fixer, test_library_walk, test_luts, test_popup,
test_resolve_bridge, test_resolve_edit_safety, test_resolve_journal,
test_resolve_undo_command, test_timeline_cards_bridge, test_timeline_cards_role,
test_timeline_cards_role_health, test_watcher, test_app, test_app_contract,
test_tray, _11b_comp_app, _11b_comp_ui, _18_companion_core, _18_companion_media,
_18b_companion_ui, test_broll_wiring -> all pass except
`test_app.py::test_the_dialog_shows_the_document_this_build_bundles` (EULA text;
not touched by this chunk, it moves with another group's concurrent edits).

Two existing test files changed because the behaviour changed:
- `tests/test_timeline_cards_bridge.py`: the sweep tests monkeypatch
  `resolve_bridge.library_timeline_items` instead of `get_timeline_items`
  (bug-comp-resolve-3 moved the sweep to the new entry point).
- `tests/test_fixer.py::test_fix_clip_tmp_name_is_unique_per_process_and_call`:
  writes different bytes per call, because an identical source is now relinked
  to the first copy rather than copied again (logic-resolve-1).

## bug-comp-resolve-1 - An admin's undo sent during Resolve's launch window is recorded FAILED and never retried
- Status: FIXED
- Verified as: `resolve_undo.apply_undo` classifies by substring; `STARTING_MESSAGE` ("DaVinci Resolve is starting up") matched no PARK/RETRY hint and has no "not", so it fell to `failed`. `undo_last_relink` passes `get_media_pool_items`' message through verbatim.
- Fix: `resolve_undo.py` apply_undo: `resolve_bridge.is_disconnection_message(message)` is asked first (lazy import, guarded) and every bridge disconnection sentence answers `retrying` with the message as detail.
- Regression test: `test_an_undo_in_resolves_launch_window_is_retried_not_failed` - HEAD answers `failed` for STARTING_MESSAGE.
- Tests run: see top.
- Skew / deploy order: none; `retrying` is one of the three states every deployed dashboard accepts.
- OWED: none

## bug-comp-resolve-2 - The 20 s project-name cache files a relink under the PREVIOUS project
- Status: PARTIAL (rest OWED)
- Verified as: `current_project_name()` caches 20 s with no invalidation; `_before_mutation` (journal slug, save_point_due, `save_project(name)` -> `ExportProject(name)`) and `_attach_adjacent_proxy`'s journal record read it with the default TTL. Reproduced in the test: cache warmed on A, project switched to B, relink journalled under A on HEAD.
- Fix: `resolve_bridge.py` `_before_mutation` and the adjacent-proxy `resolve_journal.record` read `current_project_name(max_age=0.0)`. One GetCurrentProject+GetName per mutation, beside a ReplaceClip that is far dearer. The fresh read also refreshes the cache for everyone after it.
- Regression test: `test_a_relink_just_after_a_project_switch_is_journalled_under_the_new_project` - HEAD writes the journal under A.
- Tests run: see top.
- Skew / deploy order: none (companion only, no wire change).
- OWED: c-app, `companion/src/ccsync_companion/app.py`: the two automatic-pass rate limiters read the cached name - `_handle_non_canonical` (`project = resolve_bridge.current_project_name()` before `allow_automatic(project, "canon-relink")`, ~line 3261 at HEAD) and the proxy relink pass (`project = resolve_bridge.current_project_name()` before `allow_automatic(project, "auto-proxy-relink")`, ~line 4656 at HEAD). Both should pass `max_age=0.0`, for the same reason and with a comment citing bug-comp-resolve-2; otherwise B's first unprompted burst after a switch still spends A's allowance (the journal and save point are already right).

## bug-comp-resolve-3 - Cards sweep_items runs the API walk under _API_LOCK when no library is available, throws the result away, and speeds up the watcher's full-walk valve
- Status: FIXED
- Verified as: `sweep_items` called `get_timeline_items(allow_cached=True)`, which on a None library answer ran `_get_timeline_items_locked` under `_bridge_call` before sweep_items could discard the `api` items; and every library cache hit incremented `_polls_since_full_walk`.
- Fix: `resolve_bridge.py`: new public `library_timeline_items()` (library answer or None, never the API walk, never raises), `_library_timeline_items(..., count_poll=True)` and `_cached_timeline_result(fingerprint, count_poll=True)`; with `count_poll=False` a read still honours a due valve but does not advance it. `timeline_cards_bridge.py` `sweep_items` calls `library_timeline_items()`; its uid and `source == "library"` checks stay.
- Regression test: `test_the_cards_sweep_never_takes_the_api_walk` (HEAD returns the API walk's answer), `test_a_library_read_for_cards_does_not_advance_the_watchers_valve`, `test_library_timeline_items_passes_the_non_counting_flag` (HEAD has neither parameter nor function).
- Tests run: see top.
- Skew / deploy order: none (in-process only).
- OWED: none

## bug-comp-resolve-4 - Restarting the Cards role after ONE loop dies leaves the other loop running on the released engine
- Status: PARTIAL (rest DEFERRED to the other repo)
- Verified as: `_clear_dead` drops the thread list and calls `_release_engine`, but the surviving daemon loop keeps calling `role.call`, which served any caller. The verifier also found `engine.stop()` absent in the MulticamPipeline checkout, so the old engine is never stopped either.
- Fix: `timeline_cards_role.py`: `_TunnelClient._req` passes `caller=self`; `TimelineCardsRole.call(..., caller=None)` refuses (CardsTunnelError) a caller that is not `self._client`, before the request and again after it (a long poll already in flight at the restart has its command dropped rather than applied by the released engine; logged at WARNING). The orphaned loop's own retry/back-off treats it as a dashboard error and it never receives work again. `caller=None` (a direct call) is unchanged.
- Regression test: `test_a_replaced_clients_loop_is_refused_before_it_fetches_work`, `test_a_long_poll_in_flight_at_the_restart_is_not_handed_to_the_old_client`, `test_the_tunnel_client_names_itself` - HEAD's `call` has no `caller` parameter (TypeError) and `_req` does not pass one.
- Tests run: see top.
- Skew / deploy order: none (no wire change).
- OWED: not a CC Sync group - the Timeline Cards repo (MulticamPipeline) needs a real `stop()` on SyncEngine/ResolveEngine/LibraryEngine that ends its worker threads; until then `_release_engine` stays a no-op and a restarted role leaves engine #1's own threads sweeping beside engine #2 (they no longer receive agent commands, which is what this fix closes).

## logic-resolve-1 - RETRY FAILED and 'run FIX ALL again' copy the whole file in a second time when only the relink failed
- Status: FIXED
- Verified as: `fix_clip` always went through `_claim_destination_path`; a relink failure or a relink stopped part way keeps `copied_to`, popup `_failed_rows` retries the whole row, and the next call claimed `name (2).ext` and copied again (reproduced in the test with a counting copier).
- Fix: `fixer.py`: `find_existing_copy(dest_dir, src)` looks only at the names fix_clip would have claimed (`name.ext`, `name (N).ext`), same size, and three 1 MB sampled windows (start, middle, end) equal to the source; `_fix_clip` relinks to such a copy instead of claiming and copying. Size alone is refused as identity (a CBR camera writes same-size clips under recycled names) - covered by `test_a_same_named_same_sized_different_clip_is_not_reused`. Results carry `reused_copy`, and the message says "already copied to". Works for RETRY FAILED and for a later popup on the same clip, with no popup change.
- Regression test: `test_retry_after_a_failed_relink_relinks_the_copy_instead_of_copying_again` - HEAD copies twice and leaves `A001 (2).braw`.
- Tests run: see top.
- Skew / deploy order: none.
- OWED: c-ui, `companion/src/ccsync_companion/popup.py` `fix_copied_bytes`: exclude results with `reused_copy` true from the "copied N GB" total (they copied nothing this run). Cosmetic.

## logic-resolve-2 - UNDO LAST FIX only undoes the last 2-minute burst of a FIX ALL, and a second press falsely says the clips left the media pool
- Status: FIXED
- Verified as: `SESSION_GAP_SECONDS = 120` between edits; FIX ALL relinks each clip after its own copy, so a copy over 2 minutes opens a new journal; `undo_last_relink` replayed `latest_session` and never retired it; on a replay the clips are at their old paths and were counted as "no longer in this project's media pool".
- Fix: `resolve_journal.py`: `hold_sessions()` context manager (a burst that was still open when the hold began stays open across it; the quiet gap restarts at the hold's end; a burst already quiet is not revived); `latest_undoable_session()`, `is_undone()`, `mark_undone()` (stamps `undone_at`/`undone_count`, drops it as the open burst); `describe_latest` describes the newest undoable journal. `fixer.py`: public `fix_clip` runs `_fix_clip` inside `hold_sessions()`. `resolve_bridge.py` `undo_last_relink`: the tray path takes the newest undoable journal and says "Every clip-path change CCSync made in X has already been put back" when none is left; a clip found at its OLD path counts as `already_back` (own sentence, never "left the media pool"); a replay that put back or found back anything stamps the journal. `docs/RESOLVE_EDIT_SAFETY.md` "Undoing" updated.
- Regression test: `test_a_fix_all_with_long_copies_is_one_journal` (HEAD: 3 journals), `test_a_second_undo_press_moves_on_instead_of_blaming_the_media_pool`, `test_replaying_a_journal_whose_clips_are_already_back_says_so`, plus `test_a_burst_that_went_quiet_before_the_hold_is_not_revived` as the guard.
- Tests run: see top.
- Skew / deploy order: `undone_at` is an extra top-level key in a local journal file; an older companion ignores it. The dashboard's admin undo is unchanged on the wire; an admin undo by id of an already-undone journal now answers `done` ("already back") instead of `failed`.
- OWED: none. (The finding's other half, the 120 s automatic proxy pass starting a newer journal after a FIX ALL, is not changed: that pass is a real, separately undoable change.)

## logic-resolve-3 - Share LUTs offers Resolve's factory LUTs, and a Resolve version mismatch turns that into a permanent offer that copies nothing
- Status: FIXED (plus an owner decision noted)
- Verified as: `search_dirs()` is Resolve's factory LUT folder and `stray_luts` had no factory exclusion; `copy_into_library` skips an existing dest while the next scan still reports a size-mismatched same-name file. Listing `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT` against `P:\Assets\Luts` on 2026-09-25: the library already holds the factory set (ACES, Arri, Astrodesign, Blackmagic Design, DCI, DJI, Film Looks, HDR *, Olympus, Panasonic, RED, Samsung, Sony, VFX IO, and the loose Canon/Cintel/Invert/Sony .ilut/.olut files).
- Fix: `luts.py`: `RESOLVE_FACTORY_LUT_NAMES` (top-level folders and loose files Resolve ships, measured on this rig plus camera-vendor folders other builds ship), `_is_factory`, `stray_luts(..., factory_names=None)` skips factory content and any stray whose destination path already exists in the library whatever its size; `LutLinkManager.find_strays` extends the list with config `resolve_factory_luts_extra` (comma-separated names, optional).
- Regression test: `test_resolves_factory_luts_are_never_offered`, `test_a_lut_already_in_the_library_at_its_destination_is_not_offered_again`, `test_the_factory_list_can_be_extended_from_config` - HEAD offers all three.
- Tests run: see top.
- Skew / deploy order: none.
- OWED: c-core, `companion/src/ccsync_companion/config.py`: optionally add `"resolve_factory_luts_extra": ""` to DEFAULTS and the commented template next to `resolve_lut_dir` so the knob is discoverable (the code reads it with `.get`, so nothing breaks without it). OWNER DECISION, not code: whether to remove the factory copies already in `P:\Assets\Luts` (every editor's LUT browser shows each factory LUT twice until they go). Nobody should delete them without the owner's say-so; it is a Syncthing-shared folder.

## logic-resolve-4 - With no matched project, FIX ALL's default destination is the tree root, which lane A never uploads, yet the dialog reports Fixed
- Status: PARTIAL (rest OWED)
- Verified as: `pick_project_prefix` falls back to `""`, `suggest_destination` then gives `B-roll/Editor Added/<editor>` at the tree root; `fix_clip` checks only containment in local_root; lane A walks `Projects/<rel>` only.
- Fix: `fixer.py`: `destination_stays_local(dest_rel)` (True when the first segment is not `Projects` or `Assets`); `_fix_clip`'s success and relink-failure results carry `stays_local` and, when true, the message adds "This folder is outside every project, so the copy stays on this computer and will not reach the server or other editors." No refusal: an editor may choose a local folder on purpose.
- Regression test: `test_a_fix_into_the_tree_root_says_it_will_not_sync`, `test_a_fix_into_a_project_says_nothing_extra`, `test_destination_stays_local[*]` - HEAD has neither the key nor the helper.
- Tests run: see top.
- Skew / deploy order: none.
- OWED: c-ui, `companion/src/ccsync_companion/popup.py`: the dialog is where this has to be said BEFORE the copy. (1) In the row builder / dialog, when a row's `effective_prefix` is `""` (or `fixer.destination_stays_local(selected dest)` is true), show a red line under the destination ("This folder is outside every project and will not sync") and ideally require a project choice from the dashboard-selected rels before FIX ALL is enabled. (2) In `fix_summary_text` / the per-row results, surface results with `stays_local` true (their message already carries the sentence) rather than folding them into "Fixed N of M".

## Chunk 2 (builder c-resolve, 2026-09-25)

All seven are LOWs nobody had verified; each was read against the code
first. New tests appended to
`companion/tests/test_bug_hunt_2026_09_24_w2_c-resolve.py` (16 more, 42 in
the file). Against HEAD (`git archive HEAD companion/src companion/tests
companion/pyproject.toml` into the scratchpad, this test file copied in, same
venv): every chunk-2 regression test fails; the guards that pass on HEAD are
`test_a_stat_blip_never_removes_an_arrival_with_content`,
`test_one_project_of_that_name_still_opens` and the three
`test_the_tunnels_no_engine_answer_is_still_not_attached` cases (they pin
behaviour that must not change). No existing test file was edited.

Tests run (companion venv, from `companion/`): the new file,
test_resolve_bridge_launch_window, test_script_server, _11_comp_resolve,
_11b_comp_resolve, test_resolve_bridge, test_library, test_library_walk,
test_luts, test_fixer, _18_companion_media, test_timeline_cards_role,
test_timeline_cards_role_health, test_timeline_cards_bridge,
test_resolve_edit_safety, test_resolve_journal -> 668 passed, 1 skipped; and
every test file that names `_bridge_call`, `_API_LOCK`, `api_call(`,
`copy_into_library`, `reclaim_if_reservation_lost` or `ProjectLibrary`
(test_broll_server, test_proxy_relink, test_tray, ...) -> 760 passed,
1 skipped.

## bug-comp-resolve-5 - On macOS the CR-68 probe spawns lsof while holding _API_LOCK
- Status: FIXED
- Verified as: `connect()` called `script_server.state()` inside `with _bridge_call("connect")`, and every public call already holds the lock when it calls connect(), so moving the probe to the top of connect() alone would not have helped. On Darwin `_probe_uncached` is `subprocess.run(["lsof", ...], timeout=5)` whenever the 250 ms cache has lapsed. Windows is ctypes (no spawn), so the cost is Mac-only, as reported.
- Fix: `resolve_bridge.py` `_bridge_call.__enter__`: an OUTERMOST take calls `_prime_script_server_probe()` before it queues for `_API_LOCK`, storing (time, answer) in a thread-local; the outermost `__exit__` clears it. `connect()` reads `_script_server_phase()`: this thread's primed answer if at most `_PRIMED_PROBE_MAX_AGE` (2.0 s) old, else a probe as before. The comment records why staleness is safe: the only answer that must never be acted on late is "connect" while the truth is STARTING, and READY/UNKNOWN cannot become STARTING inside 2 s (Resolve must quit, relaunch and reach its script server, 90 s at least); a lock wait past the bound (a wedge) falls back to probing under the lock.
- Regression test: `test_the_cr68_probe_never_runs_under_the_bridge_lock`, `test_a_connect_nested_in_a_public_call_uses_the_answer_taken_before_the_lock` (HEAD probes with the lock owned), `test_a_stale_primed_answer_is_not_acted_on`, `test_the_primed_answer_does_not_outlive_its_call` (HEAD has no primed answer).
- Tests run: see chunk 2 top.
- Skew / deploy order: none (in-process).
- OWED: none

## bug-comp-resolve-6 - An SMB blip at the reservation re-check leaves the original 0-byte reservation behind for good
- Status: FIXED
- Verified as: `reclaim_if_reservation_lost`'s `except OSError` branch claimed a fresh name and returned it; the original O_EXCL reservation was neither removed nor tracked, the tmp is os.replace'd into the fresh name, and `sweep_orphan_reservations` finds reservations only through a `.ccsync-tmp` beside them. Reproduced: HEAD returns `clip (2).braw` and leaves `clip.braw` at 0 bytes.
- Fix: `fixer.py` `reclaim_if_reservation_lost`: in the OSError branch, `remove_reserved_name(dest_path)` (removes only if still empty; loud warning if it cannot) BEFORE `_claim_destination_path`, so a passed blip lands the copy under its own name rather than `name (2).ext`. The content-or-gone branch is unchanged.
- Regression test: `test_a_stat_blip_at_the_recheck_leaves_no_empty_reservation` - HEAD leaves an empty `clip.braw`; guard `test_a_stat_blip_never_removes_an_arrival_with_content`.
- Tests run: see chunk 2 top.
- Skew / deploy order: none.
- OWED: none

## bug-comp-resolve-7 - The uid-map cache keys on `project is <cached object>`, which a fresh GetCurrentProject() wrapper probably never satisfies
- Status: DEFERRED
- Verified as: code path confirmed: `_media_pool_uid_map_locked` hits only when `project is _uid_cache_project_object`, and every caller gets `project` from a fresh `connect()` + `GetCurrentProject()`. Whether fusionscript hands back the same Python object for the same project is NOT knowable without a live Resolve, and rule 9 forbids calling `scriptapp()` here. Nothing in the repo, GOTCHAS or the Resolve_MCP tests records it.
- Fix: none. Why not key on something stable now: the `is` test exists to catch a CLOSED-AND-REOPENED project whose name matches while every cached MediaPoolItem is a dead fusionscript pointer (handing one to ReplaceClip is a 0xc0000005 crash). `Project.GetUniqueId()` (Resolve README.txt line 194) almost certainly survives a reopen, so swapping the key for it would trade a possible slowness for a possible crash. Today's worst case, if the hunter is right, is one pool walk per lookup: slow, correct.
- Decision/measurement needed (on a machine with Resolve open, from Resolve's console or a one-off script, not the companion): (1) `pm.GetCurrentProject() is pm.GetCurrentProject()`, and the same across two `scriptapp()` objects; (2) close and reopen the project, then call `GetName()` / `GetClipProperty()` on a MediaPoolItem fetched before the reopen: does it fail cleanly or fault? (3) does `project.GetUniqueId()` or `GetMediaPool().GetUniqueId()` change across a reopen? If (1) is False and a reopen changes the MediaPool uid, key the cache on (project name, MediaPool uid) with the TTL as the backstop.
- Regression test: none.
- Tests run: n/a.
- Skew / deploy order: n/a.
- OWED: none (a live measurement, above).

## bug-comp-resolve-8 - The library finds the project by NAME only, so a same-named project in another folder supplies the pool
- Status: FIXED
- Verified as: `_find_project_id` ran `SELECT "SM_Project_id" FROM "SM_Project" WHERE "ProjectName" = :name` and took `rows[0]`; its comment claimed the API "cannot tell them apart either", but the API answers for the OPEN project. The row has nothing that says which one is open.
- Fix: `library.py` `_find_project_id`: more than one distinct id for the name raises `LibraryUnavailable` naming the count, so the bridge falls back to the API walk (right by construction) with its usual retry backoff and rate-limited INFO line. One matching row is unchanged. Chosen over disambiguation because no column verified on the live schema ties a row to the open project; the cost is only the library speed-up for that one project.
- Regression test: `test_two_projects_with_one_name_are_refused_not_guessed` - HEAD opens it on rows[0]; guard `test_one_project_of_that_name_still_opens`.
- Tests run: see chunk 2 top (test_library, test_library_walk included).
- Skew / deploy order: none.
- OWED: none

## bug-comp-resolve-9 - LUT adoption leaves `<name>.ccsync-tmp` behind on a failed copy
- Status: FIXED
- Verified as: `copy_into_library` writes `dest.ccsync-tmp` and its `except OSError` only recorded the error; a copy2 that died part way or an os.replace that was refused left the tmp in the Syncthing-shared library, ignored by .stignore and so never cleaned anywhere.
- Fix: `luts.py` `copy_into_library`: `tmp` is tracked per entry and unlinked in the except branch (FileNotFoundError ignored, any other failure logged with "delete it by hand"). The name is written only by this function, so removing it cannot take anyone's data.
- Regression test: `test_a_failed_lut_copy_leaves_no_tmp_in_the_library` (copy2 dies after writing), `test_a_refused_rename_leaves_no_tmp_either` (os.replace refused) - HEAD leaves `Look.cube.ccsync-tmp` in both.
- Tests run: see chunk 2 top.
- Skew / deploy order: none.
- OWED: none

## logic-resolve-5 - A relink stopped part way is reported as "you skipped it, nothing was copied in or relinked", with no undo pointer
- Status: PARTIAL (rest OWED)
- Verified as: fixer.py's relink-loop stop returns `{"ok": False, "aborted": True, "partial_relink": True, "copied_to": ..., "relinked": n, "message": "Stopped by you. X was copied in and n of N clips were repointed ..."}`. popup.py counts every `aborted` as a skip (`summarize_fix_results`: "skipped by you"), prints "You skipped: X. Nothing was copied in or relinked for them, and the half-copied files were deleted", never shows the result's own message, and adds UNDO_POINTER only when some result is `ok`. The relinks ARE journalled (replace_clip), so an undo would work. Real, and entirely a display defect: fixer.py already reports the truth.
- Fix: none in c-resolve files; the result already carries everything the popup needs (`partial_relink`, `copied_to`, `relinked`, `message`).
- Regression test: none here (the change is in popup.py).
- Tests run: n/a.
- Skew / deploy order: none.
- OWED: c-ui, `companion/src/ccsync_companion/popup.py`: (1) `summarize_fix_results` (~line 226) and the batch-finished branch (~line 1480): treat a result with `partial_relink` true as its own outcome, not a skip (e.g. "1 stopped part way"), and keep it out of `aborted`; (2) in the blocks, show its `message` (it names the copy and how many clips were repointed) instead of folding it into "You skipped: ... Nothing was copied in or relinked ... the half-copied files were deleted"; (3) show UNDO_POINTER whenever any non-dry-run result has `copied_to` set or `relinked > 0`, not only when one is `ok`; (4) keep the row in `_failed_rows` so RETRY FAILED finishes it (with chunk 1's logic-resolve-1 fix the retry relinks the existing copy instead of copying again). Test: `summarize_fix_results([{"ok": False, "aborted": True, "partial_relink": True, "copied_to": "x", "relinked": 1, "file_path": "a"}], 1, False)` must not say "skipped by you".

## logic-cards-9 - The Cards role calls a routine stale-result refusal "the dashboard is discarding this computer's pushes"
- Status: PARTIAL (rest OWED)
- Verified as: `_note_answer` set `_not_attached` from ANY `error`/`note` in a 200 and logged the discarding WARNING; `health()` then shows it as the fleet grid detail. `cards_tunnel._local` wraps an engine exception as `{"error": str(exc)}` with a 200, and the engine's `agent_result` answers `{"ok": false, "error": "that request is no longer open"}` for an edit it already let go; both come from an ATTACHED engine.
- Fix: `timeline_cards_role.py`: module helper `_is_no_engine_answer(parsed)`: `attached is False` -> yes, `attached is True` -> no; otherwise (a dashboard that predates the key) the long poll's `{"note": ...}` (only ever the no-engine answer) or an `error` containing the tunnel's own sentence "is not in a Timeline Cards episode". `_note_answer` sets `_not_attached` (and the WARNING) only for that; any other refusal still returns True (the push is not recorded as traffic served), is logged at INFO once per change (`_last_refusal`), and CLEARS the not-attached state, since an engine answering proves the machine is attached.
- Regression test: `test_a_stale_result_refusal_is_not_called_discarding`, `test_an_engine_answer_clears_a_not_attached_state`, `test_attached_true_wins_over_the_sentence` - HEAD logs "discarding" and puts the sentence in health; guards `test_the_tunnels_no_engine_answer_is_still_not_attached[*]`. The 2026-09-18 wire-3 tests still pass unchanged.
- Tests run: see chunk 2 top.
- Skew / deploy order: either order. A 0.9.77/0.9.78 companion ignores an `attached` key; this companion against a dashboard without it uses the sentence fallback. Once the dashboard sends `attached`, a reworded sentence can no longer break it.
- OWED: d-cards, `dashboard/src/ccsync_dashboard/cards_tunnel.py`: add `"attached": False` to `_no_engine()`'s dict, and to the long poll's no-engine answer (`return {"note": answer.get("error", ""), "attached": False}` in the pending route). Do NOT add it to `_local`'s `{"error": str(exc)}` (that is an attached engine). Plus a dashboard test that `_no_engine("x")["attached"] is False`.

# Owed round

## ui-copy-4 (low, owed by c-ytdl) - Companion copy says "machine"/"parked"/"halted" to editors (c-resolve's half)
- Status: FIXED
- Verified as: ran the shared vocabulary scan (`test_sweep_2026_09_04_copy._sentences` + `_WORD_RE`) over both modules: it flagged `resolve_undo.PARKED_DETAIL` ("Parked: ..."), the Cards role's halt refusal ("the fleet is halted, so this machine ..."), `PROBE_UNREADABLE` and its twin literal in `_standalone`, and the cannot-tell refusal ("this machine's processes ..."). Both refusal sentences also carried "(CR-68)". Nothing parses any of them: grepped companion, dashboard (src, static, templates, tests); `PROBE_UNREADABLE` is only compared with itself inside the module, and the undo's wire state is `retrying`, not the text.
- Fix: `resolve_undo.py` PARKED_DETAIL "Parked:" -> "Waiting:". `timeline_cards_role.py`: halt refusal is now "syncing is stopped by your admin, so this computer is not taking work of any kind"; `PROBE_UNREADABLE` says "this computer's processes"; `_standalone`'s except branch returns the constant instead of a copy of its words (a copy reworded on one side only would have drawn a probe that raised as a sighting); "(CR-68)" dropped from the cannot-tell and the already-running refusals (the rule stays in the comments). The CardsRoleError at ~line 244 (checkout has no bridge contract) still cites CR-68; it is an admin-facing setup error about a checkout, not the refusal named in the finding, and was left alone.
- Regression test: `companion/tests/test_bug_hunt_2026_09_24_w2_c-resolve.py::test_no_retired_word_in_a_resolve_sentence[resolve_undo.py|timeline_cards_role.py]`, `::test_the_parked_undo_says_waiting`, `::test_the_halt_refusal_uses_the_owner_words`, `::test_no_bug_id_in_a_standalone_refusal[x3]` - all 7 FAIL against HEAD's two modules in a scratch copy (ran). `::test_a_probe_that_raised_is_still_cannot_tell_not_a_sighting` is a guard for the constant change (passes on both).
- Existing tests changed because the pinned wording changed: `test_resolve_undo_command.py` ("Parked" -> "Waiting"), `test_timeline_cards_role.py::test_a_standalone_agent_is_a_refusal_and_is_not_killed` and `test_timeline_cards_role_health.py` (the process-leads test) now assert "CR-68" is NOT in the detail.
- Tests run: `companion\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_c-resolve.py tests/test_resolve_undo_command.py tests/test_timeline_cards_role.py tests/test_timeline_cards_role_health.py tests/test_sweep_2026_09_04_copy.py -q` -> 469 passed.
- Skew / deploy order: companion only; text only, nothing reads it. An older companion keeps the old words until it upgrades.
- OWED: the owner of `companion/tests/test_sweep_2026_09_04_copy.py` (c-ui by subject; already listed in c-ytdl's ledger): add `resolve_undo.py` and `timeline_cards_role.py` to MODULES. Until then this group's own scan test covers them.


# Owed round 3 (2026-09-25)

## logic-resolve-5 (owed from c-ui) - the relink-failure result carried no `relinked` count
- Status: FIXED
- Verified as: fixer.py `fix_clip`'s `if failures:` return after the relink loop had `copied_to` but no `relinked`; the stopped-by-you return did have it. popup's `_changed_something` (c-ui, round 2) points at the undo only on `ok` or `relinked > 0`, so a relink that repointed 2 of 3 clips (journaled by replace_clip) showed no undo pointer. The message already says "relink failed for N of M", which reads as partial. The count was the renderer's only missing piece.
- Fix: fixer.py, the `if failures:` return: `"relinked": relinked`.
- Regression test: `companion/tests/test_bug_hunt_2026_09_24_w2_c-resolve.py::test_a_relink_that_repointed_some_clips_says_how_many` (KeyError on HEAD; asserts `_changed_something` is True), and `::test_a_relink_that_repointed_nothing_says_zero` (count 0, no pointer).
- Tests run: `companion\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_c-resolve.py tests/test_timeline_cards_role.py -q` -> 89 passed; `tests/test_fixer.py tests/test_bug_hunt_2026_09_24_w2_c-ui.py` -> 206 passed.
- Skew / deploy order: a companion-local key; nothing goes on the wire.
- OWED: none

## ui-copy (owed from c-ui) - the bridge-contract refusals cited CR-68 and §7c to an admin
- Status: FIXED
- Verified as: `check_contract`'s three `CardsRoleError`s become `health_detail`, which `agent_report` sends to the dashboard's machine row. They carried "(CR-68)", "(docs/TIMELINE-CARDS-INTO-CCSYNC.md §7c)" and "(§7c: SyncEngine(root, bridge=...))".
- Fix: timeline_cards_role.py `check_contract`. The three sentences now say what to do: "Update the checkout to one that defines BRIDGE_CONTRACT_VERSION = N.", "... so one of the two needs updating." (for a version mismatch, which could mean either side is behind), and "... Update the checkout." The bug id and doc section moved to a comment above the raises.
- Regression test: `test_bug_hunt_2026_09_24_w2_c-resolve.py::test_the_contract_refusals_carry_no_bug_id_or_doc_section[...]` has three cases and fails on HEAD. `tests/test_timeline_cards_role.py::test_an_engine_with_no_bridge_contract_is_refused` asserted `"7c" in detail`; it now asserts the opposite, because that is the behaviour this item changes.
- Tests run: as above.
- Skew / deploy order: none.
- OWED: none
