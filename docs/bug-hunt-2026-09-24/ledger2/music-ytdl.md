# Ledger, wave 2, group music-ytdl

## bug-music-ytdl-2 - A browser upload can take a filename a fleet batch already promised, and the companion's upload then overwrites it
- Status: FIXED (server half; companion defence in depth OWED). Severity medium (was high, per the report's table).
- Verified as: HEAD routes_ingest.queue_one used `db.unique_dest`, which checks only `exists()` on disk; a fleet `result` promises `dest_name` (ledger + `tracks` row) before the companion's `rclone copyto` lands it; `find_reencode`/content hash miss a different recording. HEAD's fleet side has the mirror gap too: between `allocate_name` and the commit of the `tracks` row the name is invisible to a browser check. The base-rig inline path (music/indexer/music_index/ingest.py) used `unique_dest` as well.
- Fix: music/web/musicweb/db.py:548-627 - `NAME_LOCK`, `_name_promised` (tracks rel_path in both spellings + unlanded `ingest_items.dest_name`, same exclusion list as `reserved_names`; tolerates a pre-004 db), `claim_dest` (disk + tracks + ledger, then an O_EXCL empty placeholder under the lock so the fleet's own disk check sees the name at once), `release_dest`. music/web/musicweb/routes_ingest.py:376-389 - queue_one creates the root first, claims, moves over the placeholder, and removes the placeholder if the move fails. music/indexer/music_index/ingest.py:140-151 - the same claim on the inline path. music/web/musicweb/ingest_batches.py:948-954 - write_item_result holds `db.NAME_LOCK` from allocate_name through the commit (held for a stat loop and one small transaction, never across a copy; the app runs one uvicorn worker). docs/MUSIC_INGEST_PLAN.md:23 names claim_dest.
- Regression test: music/web/tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_a_browser_drop_steps_around_a_name_a_fleet_item_holds, ::test_a_fleet_result_steps_around_a_browser_claim, ::test_a_fleet_result_takes_the_name_lock (fail on HEAD: the drop lands at the promised name; claim_dest / NAME_LOCK absent). Guards: ::test_a_released_promise_does_not_hold_the_name, ::test_a_move_that_fails_leaves_no_empty_file_in_the_library.
- Tests run: music/web .venv `python -m pytest tests -q` -> 640 passed, 2 skipped (the full music web suite, run because this file's rescoring interacts with test_db's order; see the note under bug-music-ytdl-4). music/indexer, system python, `python -m pytest tests -q` -> 50 passed, 1 skipped. The new file against a `git archive HEAD` copy -> 12 failed, 6 passed (the 6 are guards).
- Skew / deploy order: server-only (the music web app ships inside the dashboard image). No wire or schema change; any companion version is unaffected.
- OWED:
  - c-broll-music, companion/src/ccsync_companion/broll_upload.py (~180, `build_upload_command`): defence in depth only, not needed for this fix. Consider `--ignore-existing` for MUSIC library uploads (not b-roll, whose retry semantics differ) so a server-assigned name that some other path filled is refused rather than overwritten; `mark_uploaded`'s size check then answers 409. Needs that group's judgement on how an interrupted-then-retried upload behaves with the flag.

## bug-music-ytdl-3 - The first fleet drop into a new library refuses itself from item 2 onward
- Status: FIXED. Severity low (verifier med-07 DOWNGRADE).
- Verified as: HEAD config.share_root_ready samples both ends of `tracks`; a library whose only rows are the in-flight drop's (item 1 indexed, upload queued or paused) answers "is there but empty ... not mounted", i.e. 503 share_not_ready for item 2 onward; with the root absent, `library_has_tracks` is true and gives the same refusal. Reproduced by the new test against HEAD.
- Fix: music/web/musicweb/config.py:531-547 and 571-600 - the readiness sample and `library_has_tracks` leave out `tracks` rows whose ledger item is `indexed`/`uploading` (not evidence either way); a database without `ingest_items` falls back to the old query. `routes_ingest._create_share_root_on_first_run` inherits the same answer through `library_has_tracks`.
- Regression test: test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_a_library_made_only_of_unlanded_rows_is_not_unmounted, ::test_first_run_root_creation_ignores_unlanded_rows (fail on HEAD). Guards: ::test_a_landed_row_that_is_missing_still_says_not_mounted, ::test_a_pre_004_database_keeps_the_old_answer.
- Tests run: as above (tests/test_share_gate.py is in the full run).
- Skew / deploy order: server-only, no schema change.
- OWED: none
- Review round (2026-09-25): the reviewer was right on both counts. (1) A `failed` item keeps its track_id and tracks row (retry_failed keeps them so a retry reuses the slot), and one that failed after its result is an upload that never landed, so a first drop whose item 1 upload failed still refused every later result and the next batch. `_UNLANDED` is now built from `_UNLANDED_STATES` = pending, transcoding, embedding, indexed, uploading, failed (the three progress states because a retried item walks back through them with the same row); `live` and `cancelled` still count (the cancel path keeps a cancelled row only when its file is there). A failed item whose file did land (size mismatch) only loses its vote. music/web/musicweb/config.py `_UNLANDED_STATES`/`_UNLANDED`. (2) The mkdir widening: `library_has_tracks(con, count_unlanded=True)` is strict again by default (HEAD's "any row at all"), and only `share_root_ready`'s missing-root branch passes `count_unlanded=False`, so a missing root with only unlanded rows lets a NAME be allocated but never lets `_create_share_root_on_first_run` mkdir it. That function now raises a plain-words error in exactly that case ("the music library folder is not there yet on the server...") instead of letting the move fail with a bare ENOENT; the landed-rows case stays quiet because the gate 503s before it. music/web/musicweb/routes_ingest.py `_create_share_root_on_first_run`.
  - Regression tests: ::test_a_failed_or_retried_upload_is_not_evidence_either[failed|pending|embedding] (fail on HEAD and on round 1), ::test_a_browser_drop_does_not_mkdir_a_root_only_unlanded_rows_vouch_for (fails on HEAD: no error; would have mkdir'ed on round 1), ::test_first_run_root_creation_ignores_unlanded_rows now pins both answers of library_has_tracks. Guards: ::test_a_failed_row_beside_a_missing_landed_row_still_says_not_mounted, ::test_a_truly_empty_index_still_creates_the_root; tests/test_share_gate.py::test_the_mkdir_does_not_run_for_a_library_that_has_tracks unchanged and green. Against a `git archive HEAD` copy: 6 of the bug-3 tests fail, the 4 guards pass.
  - Tests run: music/web .venv `python -m pytest tests -q` -> 648 passed, 2 skipped; music/indexer `python -m pytest tests -q` -> 50 passed, 1 skipped.
  - Not changed, noted: `release(state='cancelled')` still leaves a `failed` item's tracks row in place (only indexed/uploading are dropped). That row is now out of the readiness sample, so it no longer blocks ingest; whether a cancelled batch should also drop its failed-and-unlanded rows is the same question as bug-music-ytdl-4 one state over, and nobody raised it.

## bug-music-ytdl-4 - Cancelling a batch strands every indexed-but-not-uploaded track as a permanent row with no audio
- Status: FIXED. Severity medium (verifier med-07 CONFIRMED). The same defect as logic-broll-music-3.
- Verified as: HEAD `release(state='cancelled')` moves `indexed`/`uploading` items to terminal `cancelled` while their `tracks` row (embedding, windows, peaks) stays; `retry_failed` moves only `failed`; the only `DELETE FROM tracks` is `prune_missing` (manual `--prune`); `load_matrix` loads every embedded row. The docstring promised the opposite. Reached from the fleet release route, `expire_stale_leases` and the browser cancel route alike.
- Fix: music/web/musicweb/ingest_batches.py:1236-1330 - on a cancelled release, `_drop_unlanded_tracks` (inside release's transaction) deletes the `tracks` row of each `indexed`/`uploading` item whose file is on disk under NO spelling (windows/tags/axes/peaks cascade; the item's `track_id` is nulled), marks `scores_stale` so the release route's `_settle_scores` re-scores, and after the commit calls `config.drop_proxy` for each freed id (music-4's reused-id rule). Conservative: a share `share_root_ready` does not trust, a stat that raises, or a file that is present (the upload landed, `uploaded` never came) keeps the row. Docstring rewritten to say what happens. Deletion was chosen over "leave them failed for retry": the companion stops its upload queue on cancel and the editor asked to stop, so a retry would re-run work nobody wants, and the name is freed for the next drop.
- Regression test: test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_cancelling_drops_the_rows_whose_audio_never_landed (fails on HEAD: the row survives and the name is held). Guards: ::test_a_cancelled_row_whose_file_did_land_is_kept, ::test_a_share_this_host_cannot_see_keeps_every_row. The file carries an autouse fixture restoring `debias`/`tags`/`axes`/`meta`, because a fleet result re-scores the shared session library and tests/test_db.py::test_load_matrix_shapes pins the seeded debias. That order dependence already exists on HEAD (`pytest tests/test_fleet_ingest.py tests/test_db.py` fails there too); this file only had to avoid triggering it in the default order.
- Tests run: as above.
- Skew / deploy order: server-only. The search index drops the row on its own staleness check (`search._looks_stale`), and the release route refreshes after the rescore.
- OWED: none

## logic-broll-music-3 - Cancelling a music batch mid-upload leaves tracks that stay searchable but have no audio and cannot be retried
- Status: FIXED (the same defect and the same fix as bug-music-ytdl-4 above).
- Verified as: see bug-music-ytdl-4 (verifier CONFIRMED medium).
- Fix: see bug-music-ytdl-4 (ingest_batches.release / _drop_unlanded_tracks).
- Regression test: test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_cancelling_drops_the_rows_whose_audio_never_landed.
- Tests run: as above.
- Skew / deploy order: server-only.
- OWED: none

## ui-music-ytdl-web-4 - The music player pane is a fixed 150 px box that cuts off its own buttons and messages
- Status: FIXED. Severity medium (CONFIRMED).
- Verified as: rendered HEAD's style.css in headless Chrome with a fleet track's no-waveform caption and the "could not reach the tray" error line: content 161 px at 1264 px wide and 237 px at 390 px, pane 150 px, overflow clipped (the phone view loses the second row of buttons and the whole message).
- Fix: music/web/static/style.css:703-738 - the pane animates a grid row 0fr -> 1fr instead of a fixed height (the row is the content's own height and it still animates); `.paneinner` gets `min-height: 0; overflow: hidden`, and a closed pane zeroes its vertical padding and bottom border (a 0fr row still shows the item's padding and border: without this a closed pane measured 21 px). Measured after: closed 0 px, open 162 px on a desktop and 237.5 px on a phone, i.e. equal to the content.
- Regression test: test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_the_open_pane_is_as_tall_as_what_it_holds (fails on HEAD: `height: 150px`).
- Tests run: the full music web suite (tests/test_theme_css.py included) -> 640 passed; headless Chrome renders at 1280 and 390 px, before and after (scratchpad).
- Skew / deploy order: static file, ships with the dashboard image.
- OWED: none

## ui-music-ytdl-web-5 - Changing any rail filter, the sort, or pressing "[ include them ]" silently throws away the typed search
- Status: FIXED. Severity medium (CONFIRMED).
- Verified as: HEAD app.js axis onchange, `#sort`, `#includeUnknown`, `#applyRange` and the `[ include them ]` button that `noteUnknownHidden` draws (runSearch calls it itself) all call `loadTracks()` (browse) and never read `#q`.
- Fix: music/web/static/app.js:591-602 `refreshResults()` - runSearch(q) when the box holds a query, loadTracks() otherwise; the five handlers (lines 636, 712, 919, 925, 943) call it. A facet click and [ clear ] still empty the box and browse, as before. Deliberately unchanged: a sort change under a search re-runs the search (ranked results keep their ranking, nothing is lost), and `refreshLibrary(newest)` after a fleet batch still switches to the newest-first browse list on purpose.
- Regression test: test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_include_them_under_a_search_re_runs_the_search (node; fails on HEAD: the button browses) and ::test_no_rail_control_goes_straight_to_the_browse_route[4 handlers] (fail on HEAD).
- Tests run: as above.
- Skew / deploy order: static file.
- OWED: none
- Review round (2026-09-25): the reviewer was right. The sort is honoured by /api/tracks only (filterParams); /api/search and /api/similar rank by match, so round 1's "a sort change re-runs the search" paid for a CLAP embed and returned the same order. Now `sortApplies(on)` (music/web/static/app.js, after refreshResults) disables `#sort`, retitles it, and shows a new `#sortnote` "search results are in order of match" (music/web/static/index.html, in `.sortrow`; a title does not show on a phone) whenever runSearch (with a query) or showSimilar starts, and loadTracks turns it back on. `sort.onchange` goes back to `loadTracks()`: it can only fire while the browse list is showing, and there a typed-but-unsearched query must not be sent by a sort change. The ledger line above ("Deliberately unchanged: a sort change under a search re-runs the search") is superseded. The five rail handlers are otherwise as round 1 left them.
  - Regression tests: ::test_the_sort_is_switched_off_while_a_ranked_answer_shows (node; fails on HEAD: no sortApplies, the control stays live under a search and a similar list), ::test_the_page_says_why_the_sort_is_off (fails on HEAD: no #sortnote). Guard: ::test_the_sort_handler_reorders_the_browse_list (passes on HEAD too; it fails on round 1, which sent a typed query from the sort). The parametrised ::test_no_rail_control_goes_straight_to_the_browse_route drops its sort case (3 handlers now).
  - Rendered: the sort row with the note in headless Chrome at 1280 px and in a 390 px iframe: one line, no wrap (scratchpad sort1280.png / sort390.png).
  - Tests run: as for bug-music-ytdl-3's review round.

## ui-music-ytdl-web-2 - Clicking a clip's title to watch it on YouTube also ticks or unticks it for download
- Status: FIXED. Severity medium (CONFIRMED).
- Verified as: HEAD ytdl app.js `card()`: the checkbox stops propagation, the title `<a target=_blank>` has no handler, and the card's onclick calls `toggle(v, !v.selected)`, which is optimistic and persisted server-side. The thumbnail is an `<img>`, not a link, so it is not affected.
- Fix: ytdl/web/static/app.js:2011-2016 - `a.onclick = e => e.stopPropagation()`.
- Regression test: ytdl/web/tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_clicking_a_clip_title_does_not_change_its_selection (node, bubbling simulated; fails on HEAD; also pins that a click on the card body still toggles).
- Tests run: ytdl/web with the dashboard venv: tests/test_static_app.py tests/test_local_download.py tests/test_no_em_dash.py tests/test_says_what_it_knows.py -> 313 passed; the new file -> 4 passed; the new file against HEAD -> 4 failed.
- Skew / deploy order: static file.
- OWED: none

## logic-ytdl-jobs-3 - The page never shows why the editor's own computer gave a download back
- Status: PARTIAL (page half FIXED; the claim-refusal half OWED to c-ytdl). Severity medium (CONFIRMED, with the verifier's qualification that silent claim refusals are documented design).
- Verified as: HEAD `grep handed_back ytdl/web/static/app.js` is empty; `ensureLocalProgress` polls only while `download_mode === 'local'`, so the pre-lease hand-backs (capabilities, free space) and any hand-back before the job flips to local are never fetched. Companion side (read, not edited): `hand_back()` records the sentence, `progress_row` exposes `phase: handed_back` + `handed_back_reason`, and the row survives the job in `_LAST`.
- Fix: ytdl/web/static/app.js:2599-2607 - a 202 from /ytdl/download starts `watchHandBack(jobId)`. Lines 2740-2791: `announceHandBack` (once per job; only `phase === 'handed_back'` with a reason, never the editor's own `cancelled` STOP; the companion's sentence plus the "originals only sync upwards" tail and the clip title) and `watchHandBack` (polls /ytdl/progress every 3 s for 240 s, past the 180 s lease; 1 s budget per call; a 404 or a finished/cancelled row ends it). Lines 2719-2721: pollLocalProgress also announces a hand-back in the middle of a local run.
- Regression test: ytdl/web/tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_a_hand_back_after_the_202_is_said_once_in_the_companions_words, ::test_another_jobs_row_and_the_editors_own_stop_are_not_announced, ::test_the_202_starts_the_watch_and_a_local_poll_reads_the_reason_too (all fail on HEAD: the functions do not exist).
- Tests run: as for ui-music-ytdl-web-2 (the whole-page harness in test_static_app.py still passes with the watcher).
- Skew / deploy order: page-only and tolerant both ways: a companion without /ytdl/progress (404) ends the watch, and one without `handed_back_reason` never matches. The fields read are documented in LOOPBACK_API.md since CR-171.
- OWED:
  - c-ytdl, companion/src/ccsync_companion/ytdl_executor.py `_run` (after the claim, where `lease is None` returns) and `FleetClient.claim` (~1127-1186): when the dashboard REFUSES the claim (403 yt-dlp below the fleet floor, 409 already downloading on your other computer, 410 skew / out of scope / created on the server, 403 attestation), call `self.hand_back(<the server's editor-readable detail> + " The server is downloading these clips.")` so the page's new watcher can say it. Today those refusals exist only in the companion log. Needs that group's call against FleetClient.claim's documented "none of them is an error the editor should see" (the owner's 2026-08-19 ask for feedback argues for it); a lease that another machine legitimately won is the one case that should stay quiet.


# Chunk 2 of 2 (2026-09-25)

## logic-ytdl-jobs-4 - The download-terms toast sends the editor to a right-click menu item that has not existed since CR-88
- Status: FIXED. Severity low (nobody verified it before this; verified here).
- Verified as: HEAD ytdl/web/static/app.js `explainCompanionRefusal` ignored its `reason` and said "right-click the tray icon, then 'Accept YouTube Terms'". The companion's reason (ytdl_executor.REASON_NOT_ATTESTED) ends with `ui_copy.YOUTUBE_TERMS` = "Tray > Settings > Accept YouTube Terms". CYT-4's comment beside it records that the item left the right-click menu on 2026-08-27 (CR-88). A node run of HEAD's function reproduces the wrong route.
- Fix: ytdl/web/static/app.js `TERMS_ROUTE_FALLBACK` / `termsRoute()` / `explainCompanionRefusal` (~2426-2450). The toast repeats the route after the last colon of the companion's reason when that route names "Accept YouTube Terms". An older build's own route was right for its own menu, so it is repeated too. Any other reason gets the current route. The existing pin in test_static_app.py (`'accept the download terms in the CC Sync tray'` + `'Accept YouTube Terms'`) still holds unchanged.
- Regression test: ytdl/web/tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_the_terms_toast_names_the_route_the_companion_gave and ::test_a_reason_without_a_route_gets_the_current_one (node; both fail on HEAD, which says "right-click"). ::test_the_fallback_route_is_the_companions_constant pins the copy against companion ui_copy.YOUTUBE_TERMS (fails on HEAD: no constant).
- Tests run: see the ytdl line under ui-music-ytdl-web-3.
- Skew / deploy order: page only. It reads a field every companion already sends. None.
- OWED: none

## ui-music-ytdl-web-1 - The YouTube page has no phone layout: its search row is 365 px wider than the screen
- Status: FIXED. Severity low (verifier med-17 DOWNGRADE).
- Verified as: in HEAD ytdl/web/static/style.css, `.search-bar` is a flex row with no wrap, and the file has no @media rule. Rendered in headless Chrome (index.html with the real stylesheet, app.js left out, the switch unhidden and the pickers filled): HEAD's scrollWidth is 912 at a 500 px window, and 912 against 784 at an 800 px window.
- Fix: ytdl/web/static/style.css `.search-bar { flex-wrap: wrap }` (~395-406), plus a `@media (max-width: 600px)` block before the theme-common block (~1055-1068). In it, the search-bar takes a full line and #q/#urls take a full line inside it. The pickers and the switch share the rest, #urlfolder flexes, and the date row may wrap.
- Regression test: test_bug_hunt_2026_09_24_w2_music-ytdl.py (ytdl)::test_the_search_row_wraps_and_a_phone_gets_a_layout (fails on HEAD: no wrap, no media block).
- Rendered: after the fix, scrollWidth equals the viewport at 500 and 800 px. At 1280 and 1000 px the layout is the same as HEAD's. The 390 px iframe view shows every control on screen (scratchpad `ytdl/new_390.png`, `new_1280.png`, `head_*.png`).
- Tests run: as below (tests/test_theme_css.py included; the theme-common block is untouched).
- Skew / deploy order: static file, ships with the dashboard image.
- OWED: none

## ui-music-ytdl-web-3 - The rights-attestation lock on SEARCH / GET LINKS is undone by the project loader and by every submit
- Status: FIXED. Severity low (verifier med-17 DOWNGRADE).
- Verified as: five defects in HEAD, each reproduced in node:
  - `init` awaits loadAttestation, which disables #go/#golinks. Then loadProjects sets both to `disabled = false` whenever a project exists.
  - `setAttested(true)` enabled them over loadProjects' no-projects lock.
  - runSearch/runUrls' `finally` enabled them unconditionally.
  - renderGrid set #download's `disabled` from the selection alone, on every poll.
  - setAttested(true) restored `el.dataset.title`, which nothing ever set, so the lock's tooltip stayed after accepting.
- Fix: ytdl/web/static/app.js. `syncSubmitButtons()` (~3215-3245) is now the one place that locks or unlocks the buttons:
  - #go is disabled when attested===false, hasProjects===false or state.searching is set. #golinks uses the same rule with state.linking.
  - #download is locked while attested===false and otherwise left to renderGrid.
  - Each button's own title is captured once (OWN_TITLES) and restored on accept.

  Around it:
  - loadProjects sets `state.hasProjects`.
  - runSearch/runUrls set `state.searching`/`state.linking` and call syncSubmitButtons instead of writing `disabled`. The button is still the in-flight guard they test.
  - An Enter in the box past a terms-locked button now shows a toast with the reason instead of doing nothing.
  - renderGrid's #download line also requires `state.attested !== false`.
  - setAttested calls syncSubmitButtons, and re-runs renderGrid when a review is on screen.

  Every test is `=== false`: an old server with no api/attestation leaves the value undefined, and the server stays the gate, as loadAttestation's comment says.
- Regression test: test_bug_hunt_2026_09_24_w2_music-ytdl.py (ytdl), all four fail on HEAD:
  - ::test_the_project_loader_does_not_undo_the_terms_lock runs loadProjects after a lock and also checks that the tooltip is restored.
  - ::test_accepting_does_not_unlock_over_no_projects
  - ::test_a_finished_submit_does_not_unlock_either
  - ::test_download_stays_locked_until_the_terms_are_accepted
- Existing tests changed, because the behaviour they relied on changed:
  - ytdl/web/tests/test_static_app.py `baseline()` now answers api/attestation as accepted. The whole-page harness never answered it, so every scenario ran past a lock that loadProjects silently removed. With the lock holding, 23 scenarios could not submit.
  - test_the_search_button_is_guarded_in_source and test_the_links_button_is_guarded_in_source now check the flag (`state.searching`/`state.linking`) and the `if (go.disabled)` / `if (btn.disabled)` guard, in place of `go.disabled = true/false`.
- Tests run: ytdl/web with the dashboard venv, `python -m pytest tests -q` -> 995 passed. That is the whole ytdl suite, because the harness change touches every scenario. The new file against a `git archive HEAD` copy -> 13 failed (chunk 1's 4 + chunk 2's 9).
- Skew / deploy order: static file.
- OWED: none

## ui-music-ytdl-web-6 - A length filter that matches nothing says "The library is empty"
- Status: FIXED. Severity low (verified here).
- Verified as: HEAD music/web/static/app.js loadTracks builds `bits` from facet, axis and BPM only, and chooses the empty sentence from `bits.length`. A node run of HEAD with `state.dur.min = 900` renders "All tracks" / "The library is empty...".
- Fix: music/web/static/app.js loadTracks (~551-555) adds a `<min>–<max> s` bit for `state.dur`, as it does for BPM. include-unknown is deliberately left out of the headline: it only ever widens the results.
- Regression test: music/web/tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_a_length_filter_is_named_in_the_headline (fails on HEAD).
- Tests run: music/web .venv `python -m pytest tests -q` -> 656 passed, 2 skipped. The chunk-2 tests against a `git archive HEAD` copy -> 7 failed, 1 passed (the guard below).
- Skew / deploy order: static file.
- OWED: none

## ui-music-ytdl-web-7 - One failed stats or facets call at load kills the whole music page, with a raw status line
- Status: FIXED. Severity low (verified here).
- Verified as: HEAD `init` awaited api/stats and api/facets before wiring anything, and its catch wrote `Failed to load: api/stats -> 401`. A node run of HEAD's init with a 401 rejects before a single handler exists.
- Fix: music/web/static/app.js `loadLibraryMeta()` (~934-951) loads stats and facets best-effort:
  - A failed stats call leaves "library totals did not load", with failureText's sentence in the tooltip.
  - A failed facets call leaves an empty rail.

  init now wires everything first, then calls loadLibraryMeta, then loadTracks. loadTracks' own catch already uses failureText's words (for a 401: "reload the page to sign in again"). The last-resort `init().catch` also goes through `failureText('Loading the page', e)`. refreshLibrary is unchanged.
- Regression test:
  - ::test_a_failed_stats_call_leaves_a_working_page runs the whole init in node with every fetch answering 401. It fails on HEAD: init rejects, #go and #clear stay unwired, and the list never loads.
  - ::test_a_page_that_still_fails_to_start_says_so_in_words also fails on HEAD.
- Rendered: in headless Chrome with no server, so every fetch fails, the page is wired, the stats line says "library totals did not load", and the list says "Loading the library failed: Failed to fetch. Try again..." (scratchpad `music-ytdl-w2c2-render/m1280.png`, `m390.png`).
- Tests run: as for ui-music-ytdl-web-6.
- Skew / deploy order: static file.
- OWED: none

## ui-music-ytdl-web-8 - Music's sticky header is taller than the `--header-h` the filter rail parks under, and on a phone it takes a third of the screen
- Status: FIXED. Severity low (verified here).
- Verified as: HEAD style.css has `--header-h: 134px` as a constant, and `#app-header` is sticky at every width. Rendered, the header is 150 px tall at 1280 px, so the rail's top 16 px park under it. At 500 px it is 263 px tall and still sticky.
- Fix, two parts:
  - music/web/static/app.js `trackHeaderHeight()` (~918-930), called first thing in init, writes the header's measured height into `--header-h`. A ResizeObserver keeps it current, because the injected dashboard topbar changes the height after load. 134 px stays in style.css as the fallback, with its comment updated.
  - music/web/static/style.css: the 900 px media block adds `#app-header { position: static; }`. The rail is already static at that width.
- Regression test: ::test_the_rail_offset_is_the_headers_measured_height (node; fails on HEAD, which has no such function and does not call one from init) and ::test_a_narrow_screen_does_not_pin_the_header (fails on HEAD).
- Rendered: after the fix, `--header-h` is 150px at 1280 and the header stays sticky. At 500 px the header is `position: static` (263 px) and scrolls away. Screenshots as above.
- Tests run: as for ui-music-ytdl-web-6 (tests/test_theme_css.py included; the theme-common block is untouched).
- Skew / deploy order: static files.
- OWED: none

## ui-music-ytdl-web-9 - After a music batch finishes, the panel still says "Running" and offers Run again on the same staged tracks
- Status: FIXED. Severity low (verified here).
- Verified as, in HEAD music/web/static/ingest.js:
  - miRun never empties `mi.items`.
  - On a terminal state, miPollServer only sets `mi.running` to false, so miRenderSummary re-enables Run over the same ticked, staged items.
  - The `#mi-live` `<h3>` is a static "Running", and `mi.batchUid` is never cleared, so the heading stays above "all done".
  - The only path that empties the list is the clear button.
- Fix: music/web/static/ingest.js.
  - `miForgetRunDrop()` is called from miPollServer when the batch THIS page was running turns terminal. It removes the batch's tracks from the staged list and resets `staged`/`precheckKey` (scoped to the recorded batch and ids in the review round below).
  - `stagingId` is kept, because miTakeOver/miRetryFailed still pass it for that batch, and a new drop re-stages under a new id anyway.
  - A batch the list poll re-attached after a reload does not clear a drop.
  - miRenderLive (~1088-1093) titles the section "Last batch" once the batch is over and "Running" otherwise. It finds the heading by tag, so a cached index.html gets the right word too.
- Regression test: ::test_the_run_drop_is_cleared_when_its_batch_ends and ::test_the_live_section_stops_saying_running fail on HEAD. The guard ::test_a_reattached_batch_does_not_clear_a_new_drop passes on both.
- Tests run: as for ui-music-ytdl-web-6.
- Skew / deploy order: static file. No server or companion change. A cancelled or failed batch is retried from its batch card (miRetryFailed dispatches from the batch, not from this list).
- OWED: none

- Review round (2026-09-25): the reviewer was right on both counts. (1) `mi.running` is not this page's run: the list poll's re-attach after a reload and miTakeOver both set it, and round 1's guard test drove `running=false`, a state the re-attach never produces. (2) Drops are accepted during a run (miHandleDrop, the picker and miAddItems have no running guard; only prepare/precheck wait), so round 1 emptied tracks dropped mid-run, unstaged and unannounced, when any batch ended. Now miRun records `mi.ranBatchUid = created.uid` and `mi.ranIds` (the chosen items' local_ids) beside `running = true`, i.e. only once the companion took the batch (the 503 path keeps the drop as HEAD did). `miForgetRunDrop(uid)` (music/web/static/ingest.js ~355-384) removes only those ids and only when `uid` is that batch, clears the record, and re-schedules prepare for whatever is left (prepare held off during the run). A re-attached or taken-over batch has no record and removes nothing; a record for another batch (this page ran b0, then took over b1) does not let b1's end touch b0's items. miPollServer passes `mi.batch.uid || mi.batchUid`. The "Last batch" heading is unchanged. Tests: ::test_the_run_drop_is_cleared_when_its_batch_ends now drives the recorded state; ::test_a_reattached_batch_does_not_clear_a_new_drop now drives the real re-attach state (running=true, an item added, no record); new ::test_a_drop_made_during_the_run_survives_its_end, ::test_a_taken_over_batch_does_not_clear_this_pages_older_run, ::test_mirun_records_the_batch_and_its_items. With round 1's whole-list forget substituted back in, the four node tests fail. music/web: the file 37 passed; whole music/web suite 659 passed, 2 skipped.

## ui-music-ytdl-web-10 - YouTube's Recent searches list prints the raw phase enum that the progress strip translates
- Status: FIXED. Severity low (verified here).
- Verified as: HEAD ytdl/web/static/app.js loadRecent prints `el('span', 'ph', j.phase)`, while the progress strip and the download line use `PHASE_LABEL`.
- Fix: ytdl/web/static/app.js loadRecent (~2892-2898) prints `PHASE_LABEL[j.phase] || j.phase` and keeps the raw enum in the span's title for support. An unknown (newer) phase still shows as itself.
- Regression test: test_bug_hunt_2026_09_24_w2_music-ytdl.py (ytdl)::test_recent_searches_use_the_progress_strips_words (node; fails on HEAD).
- Tests run: as under ui-music-ytdl-web-3.
- Skew / deploy order: static file.
- OWED: none

# Owed round (2026-09-25)

## bug-wire-2 (owed from broll) - a session-secret rotation drain cut un-re-signed machines out of music ingest and ytdl
- Status: FIXED
- Verified as: read broll's ledger and its require_identity diff; music/web/musicweb/fleet_auth.require_identity and ytdl/web/ytdlweb/routes_fleet.require_identity verified against DASH_SESSION_SECRET only, while the dashboard (settings.py `session_secrets_previous`, auth._read_token_any) accepts DASH_SESSION_SECRET_PREVIOUS. Both apps run in the dashboard process when mounted, so that variable is in their environment.
- Fix: music/web/musicweb/config.py `previous_session_secrets()` and ytdl/web/ytdlweb/config.py `session_secrets_previous()` (read live; comma split, strip, blanks dropped, as the dashboard parses it); music fleet_auth.require_identity and ytdl routes_fleet.require_identity try each after the current key, skipping one equal to it, accept-only. An unset current secret still refuses (`identity_unconfigured`): the retired keys never open an unconfigured server.
- Regression test: music/web/tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_an_identity_signed_with_a_retired_key_is_accepted (ran against HEAD's fleet_auth.py in a scratch copy: fails, 403) and ytdl/web/tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_an_identity_signed_with_a_retired_key_is_accepted (HEAD's require_identity has no fallback: 403, by reading); guards ::test_a_key_that_was_never_ours_is_still_refused, ::test_a_retired_key_does_not_stand_in_for_an_unset_current_one, ::test_previous_secrets_parse_like_the_dashboards in both.
- Tests run: music/web `.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py tests/test_fleet_ingest.py tests/test_no_em_dashes.py -q` -> 116 passed; ytdl/web `..\..\dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py tests/test_fleet_credentials.py tests/test_local_download.py -q` -> 113 passed.
- Skew / deploy order: server-only, no wire change; ships with the dashboard image.
- OWED: none

## bug-wire-7 (owed from c-broll-music) - a CJK-named machine's music ingest calls get the machine check back
- Status: FIXED (music); ytdl half NOT_A_DEFECT today
- Verified as: companion broll_ingest.FleetClient._headers (shared by b-roll and music ingest) now sends `X-CCSync-Machine-Pct` when the name is not Latin-1; music/web/musicweb/routes_fleet.py read only `X-CCSync-Machine`, so such a machine got no machine check (a second computer of the same editor could heartbeat or post results into a batch the first one holds). ytdl: companion ytdl_executor.py:1092 still sends only `X-CCSync-Machine`, through `_header_safe`, and never the Pct twin; the ytdl server's `_machine_of` prefers the body `machine_id` / query `machine_id` anyway, so there is nothing for the ytdl server to read yet.
- Fix: music/web/musicweb/routes_fleet.py `_declared_machine` dependency (plain header wins; else `urllib.parse.unquote` of the Pct header; a malformed escape decodes with U+FFFD and names no holder, so a 410, never a 500 or a skipped check), used by heartbeat, item_status, item_result, item_uploaded and release in place of the bare header. Same rule as broll/web's `_declared_machine`. The claim is unchanged (the machine rides in its JSON body).
- Regression test: music/web/tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_another_machine_is_refused_through_the_pct_header (HEAD: heartbeat from another CJK machine got 200; ran in scratch), ::test_the_plain_header_wins_and_a_bad_escape_names_nobody (HEAD: no such function); ::test_the_pct_header_names_the_holder is a guard.
- Tests run: as bug-wire-2 (music).
- Skew / deploy order: optional header both ways; an older companion sends the plain header (unchanged behaviour), a Latin-1 name too; either side may ship first.
- OWED: none from this group. If c-ytdl ever sends `X-CCSync-Machine-Pct` from ytdl_executor, ytdl/web/ytdlweb/routes_fleet.py `_machine_of` should unquote it as its last fallback; not built now because nothing sends it and the body/query carry the id.

## ui-copy-5 (owed from c-ui) - the music page named a fourth route to Copy diagnostics
- Status: FIXED
- Verified as: music/web/static/app.js:378 said "Settings > Help > Copy diagnostics in the tray"; companion ui_copy.DIAGNOSTICS is now "Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN" and settings_window.py's button is "COPY DIAGNOSTICS FOR YOUR ADMIN" in the HELP section.
- Fix: music/web/static/app.js ~378: "Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN has the reason." No em dash.
- Regression test: music/web/tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_the_refused_send_names_the_trays_real_route (HEAD: the old wording is present).
- Tests run: as bug-wire-2 (music), including test_no_em_dashes.py.
- Skew / deploy order: static copy, ships with the dashboard image.
- OWED: none

## ui-dash-static-5 (owed from d-ui, parity) - music and ytdl muted text below AA
- Status: FIXED
- Verified as: both music/web/static/style.css and ytdl/web/static/style.css had `--muted: #6f6f7a` over the same --bg/--panel/--field tokens as the dashboard (3.98 / 3.82 / 3.63:1, below 4.5). The owed item named music only; ytdl is the same token in a file this group owns, so it got the same one-line change.
- Fix: `--muted: #8a8a96` in both (5.80 / 5.57 / 5.28:1), the dashboard's value.
- Regression test: music and ytdl test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_muted_text_meets_aa_on_every_surface (HEAD: 3.63 on --field; ran against HEAD's music style.css in scratch).
- Tests run: as above.
- Skew / deploy order: static, dashboard image.
- OWED: none

# Owed round 2

## drawer-close contrast (owed from broll / d-ui parity) - the drawer's close control in --red-dim
- Status: FIXED (music as owed; ytdl too, same rule in a file this group owns)
- Verified as: music/web/static/style.css:337 and ytdl/web/static/style.css:327 set `.drawer-close { color: var(--red-dim) }` (#7c1322) on the `.nav-drawer`'s `var(--panel)` (#101014): 1.78:1, below AA's 4.5. broll/web/static/style.css:347 already uses var(--red).
- Fix: `.drawer-close { color: var(--red); }` in both (#ff2140 on #101014 = 5.01:1); :hover stays var(--red-hot).
- Regression test: music and ytdl test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_the_drawer_close_control_meets_aa_on_the_drawer_panel (HEAD: both files carry `var(--red-dim)`, confirmed with `git show HEAD:<file>`, which the test measures at 1.78 < 4.5).
- Tests run: music/web `.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py tests/test_no_em_dashes.py -q` -> 72 passed; ytdl/web `..\..\dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py -q` -> 19 passed.
- Skew / deploy order: static CSS, ships with the dashboard image.
- OWED: none

## Fable round (2026-09-25)

## bug-broll-4, music twin (fable-review-wave2-webapps-ops problem 1) - a cancelled release from a stale machine deleted the holder's track rows
- Status: FIXED
- Verified as: `music/web/musicweb/routes_fleet.py` release(): the cancelled branch checked only `batch['editor'] != editor`, the shape bug-broll-4 fixed in broll. Music's claim lets another of the editor's machines take an expired lease, and since bug-music-ytdl-4 `ingest_batches.release(state='cancelled')` runs `_drop_unlanded_tracks`. Reproduced Fable's probe as a test: EDIT-01 claims, lease expires, EDIT-02 claims and posts a result, EDIT-01 posts cancelled -> 200, batch cancelled, EDIT-02's `tracks` row deleted.
- Fix: `music/web/musicweb/routes_fleet.py` release(), cancelled branch: answer 410 `{reason: other_machine, machine}` when the caller declares a machine, the batch has a machine, they differ, and `ingest_batches.lease_live(batch)`. Same guard and wording as broll's. A caller naming no machine keeps the old behaviour; an expired lease nobody took still cancels.
- Regression test: `music/web/tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py::test_a_stale_machine_cannot_cancel_a_batch_another_machine_took_over` - fails without the guard (ran with the hunk removed: `assert 200 == 410`); asserts the batch is not terminal and EDIT-02's tracks row and `ingest_items.track_id` survive. Guard: `::test_the_holder_and_an_expired_lease_can_still_cancel` (passes both ways).
- Tests run: `cd music/web; .venv/Scripts/python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py tests/test_fleet_ingest.py -q` -> 94 passed.
- Skew / deploy order: server only. The companion's `release` already treats a 410 as "the server had already taken it back" (`broll_ingest.py`), in every shipped build.
- OWED: none
