# Wave 2 ledger: group broll

## Chunk 1 of 3 (builder "broll", 2026-09-25)

## bug-broll-1 - client-folder item matching ORs a STALE stored id with the current name
- Status: FIXED (same defect as logic-broll-music-1, one fix)
- Verified as: verifier med-07 CONFIRMED, reproduced again by the new tests against a `git archive HEAD` copy: A stored 5, B stored 9, rebuild gives A=7, B=5, C=9. On HEAD, DELETE items/5 removed both A and B, add C answered `already`, the popover ticked C, and B's public detail showed A's note.
- Fix: broll/web/app/client_folders.py: new `_resolve_item` (the one id, then name, then unique-hash re-resolution, now shared by resolve_items), `items_holding` (items whose re-resolution lands on a given CURRENT index id), `_item_rows`, `_rekey_stale_item`. `add_items` decides "already" by resolved ids and moves a stale item off a number a new clip now holds (to its resolved id when free, else to `-row id`) so UNIQUE (folder_id, video_id) cannot refuse the insert. `remove_item` / `set_note` take an optional `item_id` (the ledger row, exact) and otherwise read `video_id` as a CURRENT id. `resolve_items` returns `item_id` on the curator's rows. routes_client_folders.py: `contains` tick via items_holding; DELETE and note routes take optional `?item_id=`. routes_share.py: the detail note via items_holding. static/clientfolders.js: `cfItemQuery(item)` on the panel's remove and note calls.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_removing_one_clip_in_the_panel_removes_that_clip_only, ::test_a_bare_current_id_removes_the_clip_that_id_names_now, ::test_a_note_lands_on_one_clip_and_the_public_caption_is_that_clips, ::test_a_new_clip_whose_id_an_old_item_carries_is_added, ::test_an_old_panel_sending_no_item_id_still_reaches_a_missing_clip, ::test_an_item_id_from_another_folder_matches_nothing, ::test_the_panel_names_its_rows_by_item_id. All fail on HEAD (run against a `git archive HEAD` copy with the new test file).
- Tests run: `broll/web/.venv/Scripts/python.exe -m pytest tests/test_client_folders.py tests/test_bug_hunt_2026_09_24_w2_broll.py` -> 64 passed (the MEDIA-23, broll-4 and MEDIA-1 tests in test_client_folders.py still pass unchanged).
- Skew / deploy order: broll/web ships inside the dashboard image, page and API together. `item_id` is an optional query key; a panel page loaded before the deploy sends none and its stored id is then read as a CURRENT id (right for every item whose id did not change, and never more than one clip). No schema change: a re-keyed item's `video_id` may be negative, which every reader already treats as "no index row".
- OWED: none

## bug-broll-2 - HttpBackend posts the LOCAL shadow id to /api/ingest/index and /moved
- Status: FIXED
- Verified as: verifier med-07 CONFIRMED; read http_backend.py (payload built from the local id), routes_ingest.py (looked the id up directly). Reproduced by the new indexer tests: a shadow numbering its first clip 1 against an archive whose new clip is 15001 posted 1.
- Fix: broll/indexer/broll_index/storage/http_backend.py: table `http_remote_ids(local_id, remote_id)` in the shadow file, filled from the `{id}` that `/ingest/video` answers on upsert_video and update_video; `write_index_result` and `record_moved` send that canonical id plus the clip's (share, rel_path) (for /moved, taken BEFORE the local rename). No mapping -> id 0, which an old server 404s on rather than writing onto the clip that shares the local number. broll/web/app/routes_ingest.py: `_target_video_id` resolves by (share, rel_path) when the body names one (a disagreeing id is logged and ignored), else by id exactly as before; schemas.py: optional `share`/`rel_path` on IndexIn and MovedIn. broll/SPEC.md documents the optional keys.
- Regression test: broll/indexer/tests/test_bug_hunt_2026_09_24_w2_broll.py (5 tests, all fail on HEAD); broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_ingest_index_resolves_by_path_when_the_body_names_one, ::test_ingest_index_with_an_unknown_path_is_a_404 (fail on HEAD), ::test_an_id_only_body_is_answered_as_before (compat guard). Existing broll/indexer/tests/test_http_backend.py: two assertions changed because the payload now carries the canonical id and the identity (behaviour this fix changed).
- Tests run: `python -m pytest tests/test_bug_hunt_2026_09_24_w2_broll.py tests/test_http_backend.py tests/test_indexer_backend_config.py` (broll/indexer, system python) -> 24 passed.
- Skew / deploy order: either order is safe. New indexer vs old web app: extra keys ignored (pydantic default), the mapped canonical id is correct, an unmapped one 404s. Old indexer vs new web app: id-only body answered as before. Dormant on the base rig (sqlite mode).
- OWED: none

## bug-broll-3 - posters/sprites keyed by videos.id while base rig and live dashboard mint ids independently
- Status: DEFERRED
- Verified as: verifier med-07 CONFIRMED by reading all four sites; re-read at HEAD: ingest_batches.claim mints AUTOINCREMENT ids on the live DB, ItemFiles names stills `posters|sprites/{id}.jpg`, build_archive copies base-rig stills by id, server/broll_drain.py re-inserts drained videos under new ids and renames nothing.
- Fix: none. The honest fix is a change of the stills' key, and it spans four owners: claim's id minting (broll), build_archive's copy (broll), the companion's upload of the stills it names (c-broll-music), and the drain (release-tools, server/broll_drain.py). Two designs, and the owner has to pick one: (a) key stills by something both databases agree on (content hash, or a digest of share+rel_path), with a one-off rename of the existing archive; or (b) mint fleet-ingest ids in a range the base rig never uses (e.g. from 1,000,000,000) AND have the drain rename `posters|sprites/<old>.jpg` to the re-minted id. A half of (b) alone is not safe: without the drain rename, the next fleet claim after a publish reuses the high id whose stale stills still sit on disk, so a new clip would show the drained clip's poster.
- Regression test: none (deferred)
- Tests run: none
- Skew / deploy order: n/a
- OWED: none until the owner decides (if (b): release-tools, server/broll_drain.py, rename `posters/<old>.jpg` and `sprites/<old>.jpg` to the new id for every re-minted video, inside the drain's transaction window)

## bug-wire-2 - a session-secret rotation drain cuts un-re-signed machines out of b-roll ingest, music ingest and ytdl
- Status: PARTIAL (b-roll fixed; music and ytdl OWED)
- Verified as: verifier med-08 CONFIRMED; broll/web/app/fleet_auth.require_identity verified against DASH_SESSION_SECRET only, while dashboard auth.read_identity_token_ex also accepts DASH_SESSION_SECRET_PREVIOUS. The new test's retired-key token is 403 on HEAD.
- Fix: broll/web/app/config.py `get_previous_session_secrets()` (DASH_SESSION_SECRET_PREVIOUS parsed exactly as dashboard settings.py does: comma split, strip, drop blanks); broll/web/app/fleet_auth.py `require_identity` tries each after the current key, accept-only. The mounted app runs in the dashboard process, whose environment holds that variable.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_an_identity_signed_with_a_retired_key_is_accepted, ::test_previous_secrets_parse_like_the_dashboards (fail on HEAD); ::test_a_key_that_was_never_ours_is_still_refused (guard).
- Tests run: test_fleet_ingest.py, test_fleet_credentials.py, test_ingest_retry_and_takeover.py + the new file -> all pass.
- Skew / deploy order: server-only, no wire change.
- OWED: music-ytdl, music/web/musicweb/fleet_auth.py (~:169) and ytdl/web/ytdlweb/routes_fleet.py (~:267): after `read_identity_token(<current secret>, token)` returns None, try each secret in `os.environ["DASH_SESSION_SECRET_PREVIOUS"]` (comma-separated, stripped, blanks dropped, skip one equal to the current secret), accept-only, exactly as broll/web/app/fleet_auth.require_identity now does.

## logic-broll-music-1 - after an index rebuild, removing one clip from a client folder can delete a second clip
- Status: FIXED (same defect and same fix as bug-broll-1; see that entry)
- Verified as: verifier med-11 CONFIRMED; the finding's exact probe (add C -> `already: [9]`, remove A deletes A and B) is test_a_new_clip_whose_id_an_old_item_carries_is_added and test_removing_one_clip_in_the_panel_removes_that_clip_only.
- Fix: see bug-broll-1.
- Regression test: see bug-broll-1.
- Tests run: see bug-broll-1.
- Skew / deploy order: see bug-broll-1.
- OWED: none

## ui-broll-web-3 - detail-view hotkeys hijack Enter/Space on focused buttons and in drawers
- Status: FIXED
- Verified as: verifier med-16 CONFIRMED; app.js onKeydown exempted only INPUT/SELECT/TEXTAREA and called preventDefault + sendToResolve on every Enter while a detail was open.
- Fix: broll/web/static/app.js: `hotkeysYieldToOverlay(target)` (any of #cf-panel, #ingest-panel, #settings-panel, #cf-popover open, or the target inside one -> the handler does nothing) and `isActivatable(target)` (plain Enter on a button, link, summary or role=button/menuitem in the detail view is left to the browser). Deliberately NOT extended to Space or Shift+Enter: focus sits on whichever detail button the editor last clicked (send, set in), and Space re-pressing it would be a second timeline append where they meant "play"; Shift+Enter stays insert-at-playhead.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_detail_hotkeys_leave_drawers_and_focused_buttons_alone (extracts the three functions and drives them under node; fails on HEAD, where the helpers do not exist and Enter on a drawer button sent to Resolve).
- Tests run: new file + test_detail_view_state.py + test_ingest_ui.py -> pass; `node --check static/app.js` ok.
- Skew / deploy order: static file, ships with the dashboard image.
- OWED: none

## bug-broll-4 - a CANCELLED release is accepted from any of the editor's machines
- Status: FIXED
- Verified as: read routes_fleet.release (cancelled branch checked only `batch.editor`), ingest_batches.release (cancels non-kept items, deletes `ingesting` video rows) and claim (another machine of the same editor may claim once the lease is not live). The new test reproduces it on HEAD: EDIT-01 claims, lease expires, EDIT-02 claims, EDIT-01's cancelled release returned 200 and cancelled EDIT-02's batch.
- Fix: broll/web/app/routes_fleet.py release: in the cancelled branch, a caller that names a machine other than the batch's while the lease is live gets 410 `other_machine`. No machine header, the holder itself, or an expired lease: unchanged. The companion's BatchClient.release already treats a 410 as "the server had already taken batch back" and cancel() goes on clearing local state.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_a_stale_machine_cannot_cancel_a_batch_another_machine_took_over (fails on HEAD); ::test_the_holder_and_an_expired_lease_can_still_cancel (guard).
- Tests run: test_fleet_ingest.py, test_ingest_retry_and_takeover.py, new file -> pass.
- Skew / deploy order: server-only; every companion version sends X-CCSync-Machine and handles 410 on release.
- OWED: none

## logic-broll-music-4 - the editor's own "open" check of a client link counts as the client opening it
- Status: FIXED
- Verified as: routes_share.share_folder called record_view on every api/folder fetch; the panel's "open" link loads that page; nothing told the two apart. Dashboard broll.py BrollGate strips inbound X-CCSync-User on EVERY request and appends it from a valid session cookie, share paths included, so the signal exists.
- Fix: broll/web/app/routes_share.py share_folder skips record_view when X-CCSync-User is present or `?preview=1` is sent. static/clientfolders.js: the "open" link is `<link>?preview=1` (the field and the copied link stay clean); static/share.js forwards `?preview=1` from the page URL to api/folder. docs/CLIENT_FOLDERS.md says so.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_the_curators_own_look_is_not_a_client_view, ::test_the_open_link_and_the_viewer_carry_preview (fail on HEAD). test_client_folders.py::test_opening_the_folder_counts_a_view_that_the_editor_can_see still passes (an anonymous client is still counted).
- Tests run: test_client_folders.py + new file -> 64 passed.
- Skew / deploy order: server and static ship together. A forged X-CCSync-User on a standalone (unmounted) app can only hide a view.
- OWED: none

## ui-broll-web-1 - share page detail view overflows a phone horizontally with a long camera filename
- Status: FIXED (low, downgraded by med-16)
- Verified as: verifier med-16 (mechanism holds). Rendered HEAD's share.css in headless Chrome inside a 390 px iframe with a DJI-style filename: document scrollWidth 435.
- Fix: broll/web/static/share.css: `grid-template-columns: minmax(0, 1fr)` in the 860 px rule, and `overflow-wrap: anywhere` on `.share-layout .video-meta .title` and `.share-caption .share-caption-name`.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_the_phone_detail_column_can_shrink_below_a_long_filename (fails on HEAD). Rendered: 390 px iframe scrollWidth 435 (HEAD) -> 390 (fix), title wraps; 1280 px layout unchanged apart from the title wrapping inside its column (screenshots in the session scratchpad, uiw/shot_new.png, shot_new_1280.png).
- Tests run: new file -> pass.
- Skew / deploy order: static file.
- OWED: none

## Chunk 2 of 3 (builder "broll", 2026-09-25)

## ui-broll-web-2 - share page brand line overflows a phone with a long org name
- Status: FIXED (low)
- Verified as: Unverified low, verified: style.css `.topbar > *` is `flex: 0 0 auto; white-space: nowrap`, and the brand holds `data.org` (site data, unbounded). Rendered HEAD's share page in headless Chrome in a 390 px iframe with org "The Creators Club Documentary Studio": document scrollWidth 505, brand right edge 505.
- Fix: broll/web/static/share.css:19-25: `.share-header .topbar > .brand { flex: 0 1 auto; min-width: 0; white-space: normal; }` and `#share-org { flex: 0 1 auto; min-width: 0; overflow-wrap: anywhere; }`. The org wraps inside the brand; the mark and `// PREVIEW` stay on the line. Rendered: 390 px scrollWidth 505 (HEAD) -> 390; the 1280 px header is identical to HEAD (flex-grow deliberately 0 so the desktop layout does not move).
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_the_share_brand_may_shrink_and_wrap_a_long_org_name - fails on HEAD (the 10 chunk-2 tests run against a `git archive HEAD` copy of broll/web with the new test file: 10 failed).
- Tests run: `broll/web/.venv/Scripts/python.exe -m pytest` on the new file + test_bug_hunt_2026_09_11b_broll, test_client_folders, test_detail_view_state, test_filter_state, test_ingest_ui, test_insert_target, test_mounted_prefix, test_no_em_dashes, test_one_vocabulary, test_search_says_what_it_did, test_send_busy_is_a_queue, test_sprite_geometry, test_theme_css -> 278 passed; `node --check` on app.js, clientfolders.js, share.js ok.
- Skew / deploy order: Static files, ship with the dashboard image, page and API together; no wire or schema change.
- OWED: none

## ui-broll-web-4 - folder rail parks under the sticky header (constant --header-h: 88px)
- Status: FIXED (low)
- Verified as: Verifier med-16 DOWNGRADE to low (nothing writes --header-h). Re-read: style.css:42 constant, read by .folder-tree top/max-height/min-height; no writer in any static JS. Rendered HEAD at 1366: header 132 px, rail top 88 px.
- Fix: broll/web/static/app.js:232-257 `trackHeaderHeight()` (first call in init): measures #app-header, sets --header-h on :root, and a ResizeObserver re-measures on every change (topbar injection, control rows re-wrapping); window resize is the fallback where ResizeObserver is absent. style.css:41-43 comment: 88px is the first-paint fallback. Rendered at 1366: --header-h 132px == header height (HEAD 88px). Headless Chrome delivers ResizeObserver callbacks only on the few frames it renders, so a 600 px render caught one stale value; the observer path is pinned by the node test.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_the_rail_offset_follows_the_real_header - fails on HEAD (the 10 chunk-2 tests run against a `git archive HEAD` copy of broll/web with the new test file: 10 failed) (no trackHeaderHeight).
- Tests run: `broll/web/.venv/Scripts/python.exe -m pytest` on the new file + test_bug_hunt_2026_09_11b_broll, test_client_folders, test_detail_view_state, test_filter_state, test_ingest_ui, test_insert_target, test_mounted_prefix, test_no_em_dashes, test_one_vocabulary, test_search_says_what_it_did, test_send_busy_is_a_queue, test_sprite_geometry, test_theme_css -> 278 passed; `node --check` on app.js, clientfolders.js, share.js ok.
- Skew / deploy order: Static files, ship with the dashboard image, page and API together; no wire or schema change.
- OWED: none

## ui-broll-web-5 - "+ new folder" in the popover shows success when the add fails
- Status: FIXED (low)
- Verified as: Verifier med-16 DOWNGRADE to low (mechanism holds, trigger narrow). Re-read clientfolders.js: cfCreateFlow toasts Created then returns afterCreate(folder) with no catch; the newBtn listener awaits it with no catch; cfRenderPopover ran only on success. Under node on HEAD: one success toast, an unhandled rejection, popover not redrawn.
- Fix: broll/web/static/clientfolders.js:603-627: the afterCreate callback catches the items POST and toasts `Folder "X" was created, but the clip was not added: <reason>` (error), then reloads the list and redraws the popover whether or not the add worked, unless the popover has since closed or moved to another clip. cfCreateFlow itself is unchanged (its other caller, the panel's New button, passes no callback).
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_the_popover_counts_reports_and_stays_on_screen (toasts, unhandled, redrawn titles) - fails on HEAD (the 10 chunk-2 tests run against a `git archive HEAD` copy of broll/web with the new test file: 10 failed).
- Tests run: `broll/web/.venv/Scripts/python.exe -m pytest` on the new file + test_bug_hunt_2026_09_11b_broll, test_client_folders, test_detail_view_state, test_filter_state, test_ingest_ui, test_insert_target, test_mounted_prefix, test_no_em_dashes, test_one_vocabulary, test_search_says_what_it_did, test_send_busy_is_a_queue, test_sprite_geometry, test_theme_css -> 278 passed; `node --check` on app.js, clientfolders.js, share.js ok.
- Skew / deploy order: Static files, ship with the dashboard image, page and API together; no wire or schema change.
- OWED: none

## ui-broll-web-6 - a send to Resolve keeps painting SYNCING onto the next clip
- Status: FIXED (low)
- Verified as: Unverified low, verified by reading app.js sendToResolve/openDetail/closeDetail: btn/otherBtn captured once, labels written every poll, only the loop's finally restored them; open/close never touched them; the result toast named no clip; Enter on clip B while A was in flight returned silently (sendInFlight).
- Fix: broll/web/static/app.js:1719-1775 (`sendClip`, `sendShowingInFlightClip`, `sendClipMessage`, `renderSendButtons`) and sendToResolve: the loop still runs to the end (one send per companion; the companion joins the download), but SYNCING/WAITING is drawn only while the in-flight clip is on screen. On another clip the buttons show their own labels, stay disabled, and carry the title `Still sending "A001.mov" to Resolve...`; pressing send there toasts that instead of doing nothing. Every toast from the loop is prefixed with the clip's filename once the editor has moved off it. openDetail and closeDetail call renderSendButtons.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_a_send_in_flight_is_not_painted_onto_the_next_clip - fails on HEAD (the 10 chunk-2 tests run against a `git archive HEAD` copy of broll/web with the new test file: 10 failed) (none of the helpers exist). test_send_busy_is_a_queue.py passes unchanged.
- Tests run: `broll/web/.venv/Scripts/python.exe -m pytest` on the new file + test_bug_hunt_2026_09_11b_broll, test_client_folders, test_detail_view_state, test_filter_state, test_ingest_ui, test_insert_target, test_mounted_prefix, test_no_em_dashes, test_one_vocabulary, test_search_says_what_it_did, test_send_busy_is_a_queue, test_sprite_geometry, test_theme_css -> 278 passed; `node --check` on app.js, clientfolders.js, share.js ok.
- Skew / deploy order: Static files, ship with the dashboard image, page and API together; no wire or schema change.
- OWED: none

## ui-broll-web-7 - share page tells a phone to hover; keyboard help shown on a phone
- Status: FIXED (low)
- Verified as: Unverified low, verified: share.html's intro was hover-first, sprite.js scrub is mousemove-only, the keyhelp names space/arrows/Esc. A tap opens the clip (card click), so a phone can never scrub.
- Fix: broll/web/static/share.html:35-42: the intro reads `Tap or click a clip to play the preview... On a computer, hover over a thumbnail to scrub through it.` (id share-howto). share.css:26-30: `@media (hover: none) { .share-body .keyhelp { display: none; } }`. Touch scrubbing NOT added on purpose: a touch pointermove on a grid thumbnail competes with scrolling the grid, and the tap already opens a player with its own scrubber.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_the_share_page_does_not_tell_a_phone_to_hover - fails on HEAD (the 10 chunk-2 tests run against a `git archive HEAD` copy of broll/web with the new test file: 10 failed).
- Tests run: `broll/web/.venv/Scripts/python.exe -m pytest` on the new file + test_bug_hunt_2026_09_11b_broll, test_client_folders, test_detail_view_state, test_filter_state, test_ingest_ui, test_insert_target, test_mounted_prefix, test_no_em_dashes, test_one_vocabulary, test_search_says_what_it_did, test_send_busy_is_a_queue, test_sprite_geometry, test_theme_css -> 278 passed; `node --check` on app.js, clientfolders.js, share.js ok.
- Skew / deploy order: Static files, ship with the dashboard image, page and API together; no wire or schema change.
- OWED: none

## ui-broll-web-8 - share grid captions clip filenames and slice a third line
- Status: FIXED (low)
- Verified as: Unverified low, verified by render: HEAD's caption (border-box, 12 px padding, max-height 3.9em) showed two lines and a sliced third. The mid-word cut of the filename was already fixed by chunk 1's ui-broll-web-1 (`overflow-wrap: anywhere` on .share-caption-name).
- Fix: broll/web/static/share.css:50-70: `-webkit-line-clamp: 3` (+ `line-clamp`), `max-height: calc(4.2em + 6px)` as the cap for an engine without clamp, and the bottom gap moved from padding to margin, because overflow clips at the padding box and bottom padding showed a sliver of line four (seen in the first render). Rendered at 390 and 1280: three whole lines ending in an ellipsis.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_the_share_caption_shows_three_whole_lines - fails on HEAD (the 10 chunk-2 tests run against a `git archive HEAD` copy of broll/web with the new test file: 10 failed).
- Tests run: `broll/web/.venv/Scripts/python.exe -m pytest` on the new file + test_bug_hunt_2026_09_11b_broll, test_client_folders, test_detail_view_state, test_filter_state, test_ingest_ui, test_insert_target, test_mounted_prefix, test_no_em_dashes, test_one_vocabulary, test_search_says_what_it_did, test_send_busy_is_a_queue, test_sprite_geometry, test_theme_css -> 278 passed; `node --check` on app.js, clientfolders.js, share.js ok.
- Skew / deploy order: Static files, ship with the dashboard image, page and API together; no wire or schema change.
- OWED: none

## ui-broll-web-9 - share page prev/next look enabled at the ends
- Status: FIXED (low)
- Verified as: Unverified low, verified: share.js sets `disabled` at the ends; style.css had a `:disabled` look only under `.cf-item-ctl`.
- Fix: broll/web/static/style.css:515-519: global `.text-btn:disabled, .text-btn:disabled:hover { color: var(--muted); cursor: default; text-shadow: none; }`, after :hover so it wins the tie. `.cf-danger .text-btn` and `.cf-item-ctl .text-btn:disabled` come later and keep their own looks. Rendered: prev at 1 / 3 is grey.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_a_disabled_text_button_looks_disabled - fails on HEAD (the 10 chunk-2 tests run against a `git archive HEAD` copy of broll/web with the new test file: 10 failed).
- Tests run: `broll/web/.venv/Scripts/python.exe -m pytest` on the new file + test_bug_hunt_2026_09_11b_broll, test_client_folders, test_detail_view_state, test_filter_state, test_ingest_ui, test_insert_target, test_mounted_prefix, test_no_em_dashes, test_one_vocabulary, test_search_says_what_it_did, test_send_busy_is_a_queue, test_sprite_geometry, test_theme_css -> 278 passed; `node --check` on app.js, clientfolders.js, share.js ok.
- Skew / deploy order: Static files, ship with the dashboard image, page and API together; no wire or schema change.
- OWED: none

## ui-broll-web-10 - share page heads a transient error "This link is not available"
- Status: FIXED (low)
- Verified as: Unverified low, verified: share.js set that headline for every api/folder failure with the raw `HTTP 502` / `Failed to fetch`; routes_share answers 404 for every revoked, expired or unknown token (routes_share.py:78), so 404 is the only "gone".
- Fix: broll/web/static/share.js:165-185: 404 keeps the dead-link headline and text; anything else is headed `The preview could not load just now`, reads `This is usually brief. Please try again in a moment.`, and gets a `Try again` button (location.reload); no raw status. The tap/hover intro is hidden on both failures. share.css `.share-retry` spacing. Rendered against a stub answering 502.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_a_transient_share_failure_offers_a_retry_not_a_dead_link - fails on HEAD (the 10 chunk-2 tests run against a `git archive HEAD` copy of broll/web with the new test file: 10 failed).
- Tests run: `broll/web/.venv/Scripts/python.exe -m pytest` on the new file + test_bug_hunt_2026_09_11b_broll, test_client_folders, test_detail_view_state, test_filter_state, test_ingest_ui, test_insert_target, test_mounted_prefix, test_no_em_dashes, test_one_vocabulary, test_search_says_what_it_did, test_send_busy_is_a_queue, test_sprite_geometry, test_theme_css -> 278 passed; `node --check` on app.js, clientfolders.js, share.js ok.
- Skew / deploy order: Static files, ship with the dashboard image, page and API together; no wire or schema change.
- OWED: none

## ui-broll-web-11 - client-folder popover: stale counts, off-screen placement, invisible "+"
- Status: FIXED (low)
- Verified as: Unverified low, verified all three: (a) the change handler updated folder.n_items but not the rendered span; (b) cfPlacePopover set top = anchor.bottom + 4 with no clamp, and .cf-popover (position: fixed) had no max-height or scrolling; (c) .cf-card-add is opacity 0 except under .card:hover, so no focus ring and no touch target.
- Fix: (a) clientfolders.js:566-569, 590: the count span is kept and redrawn after a toggle. (b) clientfolders.js:636-667: cfPlacePopover measures the list, goes below the anchor when it fits or when below has at least as much room, else above, and caps max-height to that side's room; cfRenderPopover re-places it once the real list replaces the loading line. style.css:1718-1727: `max-height: 60vh; overflow-y: auto` before JS runs; children flex-shrink 0 so they scroll rather than squash. (c) style.css:1584-1590: `.cf-card-add:focus-visible { opacity: 1 }` and `@media (hover: none) { .cf-card-add { opacity: 1 } }`.
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_the_popover_counts_reports_and_stays_on_screen (count, three placements), ::test_the_card_plus_is_reachable_by_keyboard_and_touch - fails on HEAD (the 10 chunk-2 tests run against a `git archive HEAD` copy of broll/web with the new test file: 10 failed).
- Tests run: `broll/web/.venv/Scripts/python.exe -m pytest` on the new file + test_bug_hunt_2026_09_11b_broll, test_client_folders, test_detail_view_state, test_filter_state, test_ingest_ui, test_insert_target, test_mounted_prefix, test_no_em_dashes, test_one_vocabulary, test_search_says_what_it_did, test_send_busy_is_a_queue, test_sprite_geometry, test_theme_css -> 278 passed; `node --check` on app.js, clientfolders.js, share.js ok.
- Skew / deploy order: Static files, ship with the dashboard image, page and API together; no wire or schema change.
- OWED: none

## Chunk 3 of 3 (builder "broll", 2026-09-25)

Common to all seven: static files under broll/web/static, which ship with the dashboard image (page and API together); no wire key, no schema change, no deploy order. Tests run for the chunk: `broll/web/.venv/Scripts/python.exe -m pytest -q` on test_bug_hunt_2026_09_24_w2_broll, test_client_folders, test_ingest_ui, test_no_em_dashes, test_mounted_prefix, test_theme_css, test_one_vocabulary, test_search_says_what_it_did, test_bug_hunt_2026_09_18b_webapps_broll, test_detail_view_state, test_send_busy_is_a_queue, test_bug_hunt_2026_09_11b_broll, test_filter_state, test_insert_target, test_batch_state_words -> 304 passed; `node --check` on app.js, ingest.js, clientfolders.js ok. HEAD check: the six new chunk-3 tests run against a `git archive HEAD` copy of broll/web with the new test file: 6 failed (the caption, Running-box and toast tests fail at extraction because HEAD has no cfNoteFields / ING_START_NOW_GATES / TOAST_MAX_STICKY; their behavioural asserts were reasoned against HEAD's code line by line, see each entry).

## ui-broll-web-12 - caption edits appear reverted on a reorder straight after typing; no save feedback
- Status: FIXED (low)
- Verified as: Unverified low, verified by reading clientfolders.js: the change handler assigned `item.note` only after the PUT resolved; cfMove swaps and calls cfRenderFolder synchronously, which rebuilds every row from `item.note`. blur (mousedown) -> change -> click puts the redraw inside the PUT's await, so the redrawn field showed the old caption. Success showed nothing.
- Fix: broll/web/static/clientfolders.js cfItemRow: `item.note` is set before the PUT is awaited; on failure it goes back to the previous caption unless a later edit already replaced it (the field keeps the typed words; the error toast is unchanged). A `saved` mark (span.cf-note-saved in the name line, so showing it never moves the row) flashes for 1.8 s on success, on whichever row shows the item NOW (`cfNoteFields` WeakMap item -> {field, mark}, refreshed by every redraw; `cfFlashSaved`). style.css `.cf-note-saved` (green).
- Regression test: broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_a_caption_typed_before_a_reorder_is_not_redrawn_away - type into B, fire change, cfMove before the PUT resolves: the redrawn field reads the new caption (HEAD: ""), the PUT carries it and the item_id, "saved" appears after it resolves, and a failed save reverts the model and toasts. Fails on HEAD.
- Tests run: see the chunk header.
- Skew / deploy order: static only.
- OWED: none

- Review round (2026-09-25): PROBLEM accepted. The reviewer was right that the mark could be clipped: it sat inside `.cf-item-name`, which was `overflow: hidden; text-overflow: ellipsis` as a whole line, so the name, the duration and "saved" shared one clipped box. Measured in headless Chrome with the real style.css at the 460 px panel: a 60-character clip name put the mark at right 1429 against a line right edge of 1208 (invisible); `DJI_20260917123456_0001_D.MP4` (29 chars) still just fitted (mark right 1198), so the threshold is a little above the reviewer's ~30. Fix: clientfolders.js cfItemRow puts the name in its own `span.cf-item-name-text` and tags the duration `cf-item-dur`; style.css makes `.cf-item-name` a nowrap flex row with no overflow of its own, `.cf-item-name-text` the only shrinking part (`flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis`), and `.cf-item-dur` / `.cf-note-saved` `flex: none`. Re-rendered: all three rows (short, 29-char, 60-char) show "saved" inside the line (60-char row: mark right 1208 = line right, name ellipsized; screenshot scratchpad w3r/new.png). The missing-clip text goes in the same span, so it ellipsizes as before. The regression test now also asserts the name line's children are `[cf-item-name-text, cf-note-saved]` (fails on the round-one code: the mark was the only child element) and pins the four CSS rules as text, because the fake DOM has no layout; the rendered measurement is the layout evidence. Tests: `broll/web/.venv/Scripts/python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_broll.py tests/test_client_folders.py tests/test_no_em_dashes.py` -> 114 passed; `node --check static/clientfolders.js` ok.

## ui-broll-web-13 - two hamburgers and two gears in the b-roll header
- Status: FIXED (low)
- Verified as: Unverified low, verified: index.html `#cf-btn` is U+2630 and `#settings-btn` U+2699; dashboard/templates/partials/topbar.html (injected by app.js loadDashboardTopbar) carries `.menu-btn` (nav drawer) and, for admins, `.gear-link` to dashboard Settings. The b-roll panel is shares + the tray status, not Settings.
- Fix: broll/web/static/index.html: `#cf-btn` reads `client folders`, `#settings-btn` reads `tray + shares` (title "Shares and the CC Sync tray on this computer"), the panel's heading `Tray and shares`. Ids and handlers unchanged. style.css `.icon-btn.label-btn` (11 px, nowrap) keeps them in the icon buttons' frame. The ingest `+` is left as is (it duplicates nothing in the topbar). Rendered at 1280 and 390 (scratchpad w3/r8941-*.png): both sit on the flag row at 1280 and wrap onto their own row at 390.
- Regression test: ::test_the_header_has_no_second_hamburger_or_gear - fails on HEAD.
- Tests run: see the chunk header (test_client_folders' id pin on `cf-btn` still passes).
- Skew / deploy order: static only.
- OWED: none

## ui-broll-web-14 - the ingest Running list prints raw state tokens (proxies_live)
- Status: FIXED (low)
- Verified as: Unverified low, verified: ingest.js ingestRenderLive printed `item.state.padEnd(10)`, while the batch card uses `ingestItemStateText` (wire-1, 2026-09-18b).
- Fix: broll/web/static/ingest.js ingestRenderLive: `ingestItemStateText(item.state).padEnd(10, " ")`. The row's `state-<token>` class is unchanged (styling hook).
- Regression test: ::test_the_running_box_speaks_words_and_offers_only_what_applies (the `rows` asserts: "original still owed Taipei/A001.mov", no "proxies_live") - fails on HEAD.
- Tests run: see the chunk header.
- Skew / deploy order: static only.
- OWED: none

## ui-broll-web-15 - Pause, Resume and Start now all offered at once, whatever the state
- Status: FIXED (low)
- Verified as: Unverified low, verified: index.html has all three always visible; ingestRenderLive only disabled them when the batch was over; ingestControl toasted `CC Sync tray: <raw gate>`. The companion's own progress window (broll_ingest.progress_model) offers resume XOR pause by its `paused` flag and start_now only at the user-active / resolve-open gates; the loopback `/broll/ingest/progress` answer has carried `batch.paused` since fe54705 (2026-08-18), so every field build sends it.
- Fix: broll/web/static/ingest.js ingestRenderLive: Pause shown unless paused, Resume only when paused (`lb.paused`, falling back to `gate === "paused"` for a companion that sends no flag), Start now only when not paused and the gate is in `ING_START_NOW_GATES` (user-active, resolve-open, mirroring progress_model). With no loopback answer, Pause stays visible but disabled (all three are loopback calls). ingestControl's toast goes through ingGateLabel ("CC Sync tray: indexing."). "Pause uploads" already toggled and is unchanged.
- Regression test: ::test_the_running_box_speaks_words_and_offers_only_what_applies (running / paused / user-active / no-flag / no-tray states and the toast) - fails on HEAD (all three buttons visible in every state; toast "CC Sync tray: running.").
- Tests run: see the chunk header.
- Skew / deploy order: static only; reads only keys every field companion sends.
- OWED: none

## ui-broll-web-16 - mode fallback toast says "keyword" while the page switches to Hybrid
- Status: FIXED (low)
- Verified as: Unverified low, verified: applyModeAvailability sets `state.mode = "hybrid"` and lights Hybrid but toasted "Searching by keyword instead." Only semantic is ever unavailable (semantic.mode_availability), and then hybrid carries NOTE_HYBRID_DEGRADED ("Keyword only right now..."), so keyword-only described the results but not the mode.
- Fix: broll/web/static/app.js applyModeAvailability: `<reason> Switched to Hybrid, which is searching by keyword only for now.` when hybrid reports a reason, else `<reason> Switched to Hybrid.`
- Regression test: ::test_the_mode_fallback_toast_names_hybrid - fails on HEAD (toast contains "by keyword instead").
- Tests run: see the chunk header.
- Skew / deploy order: static only.
- OWED: none

## ui-broll-web-17 - long error toasts vanish after 5 s, including the tray self-test instructions
- Status: FIXED (low)
- Verified as: Unverified low, verified: app.js toast removed every toast at 5000 ms, no dismiss control; the tray-unreachable error (sendToResolve) is ~330 characters with a URL to type.
- Fix: broll/web/static/app.js toast: an `error` toast stays until its close button (x, aria-label "dismiss") is pressed; other kinds live 60 ms per character, 5 to 15 s (`toastLifetimeMs`). A repeat of the same kind+text replaces its earlier copy, and at most `TOAST_MAX_STICKY` (4) error toasts are kept (oldest dropped), so a burst of per-file upload failures cannot fill the screen. style.css: `.toast` is a flex row with `.toast-text` + `.toast-close`, `max-width: min(640px, 100vw - 32px)`, `user-select: text` so the URL can be copied. share.js has its own toast and is untouched (the share page shows no long errors). Rendered at 1280 (scratchpad w3/toast.png): after 12 s of virtual time the error is still up with its close button and the success toast has gone.
- Regression test: ::test_an_error_toast_stays_until_dismissed - fails on HEAD (both toasts timed at 5000 ms).
- Tests run: see the chunk header.
- Skew / deploy order: static only.
- OWED: none

## ui-broll-web-18 - the b-roll SPA has no narrow layout (718 px wide at 390)
- Status: FIXED (low)
- Verified as: Unverified low, verified by render: the real broll/web app (uvicorn, a seeded temp DB) at HEAD in a 390 px iframe: docW 718, overflow flag-toggles:718 and the first card at 464.
- Fix: broll/web/static/style.css: `@media (max-width: 700px)` block at the end: header rows wrap (search bar full width, flag toggles wrap), the rail becomes a static 32vh scrolling shelf above the grid (browse-layout column), the grid centres its columns, the pager wraps, the detail layout is one column, the settings panel is capped at 100vw. The cards deliberately stay 240 px, unlike the hunter's suggested `minmax(160px, 1fr)` with fluid thumbs: sprite.js positions the scrub sheet with pixel offsets of a 240 px cell (SPRITE_CELL_WIDTH, no background-size), so a fluid card would show the wrong frame or a splice of two; one 240 px column fits 390 with room to spare. Rendered: grid and detail at 390 -> docW 380 (the iframe's scrollbar), no overflow; 1280 unchanged apart from the ui-broll-web-13 labels (scratchpad w3/r8941-390.png, det390.png, r8941-1280.png).
- Regression test: ::test_the_spa_has_a_narrow_layout - fails on HEAD (no such block).
- Tests run: see the chunk header.
- Skew / deploy order: static only.
- OWED: none

# Owed round

## bug-wire-7 (owed from c-broll-music) - the server half: read X-CCSync-Machine-Pct
- Status: FIXED
- Verified as: c-broll-music's `broll_ingest.FleetClient._headers` now sends a non-Latin-1 machine name only as `X-CCSync-Machine-Pct` (percent-encoded, `safe=""`). `broll/web/app/routes_fleet.py` read only `x_ccsync_machine` in heartbeat, item status/result/uploaded and release (both the `_leaseholder_or_410` path and bug-broll-4's cancelled-release check), so such a machine had no machine check. Nothing in `dashboard/src` filters or rewrites the header on the /broll mount (grep).
- Fix: `broll/web/app/routes_fleet.py`: new dependency `_declared_machine` reads both headers, the plain one winning when present, else `urllib.parse.unquote` of the twin (a malformed escape decodes to U+FFFD, names no holder, and so is a 410, never a 500 or a skipped check). The five handlers take `x_ccsync_machine = Depends(_declared_machine)` in place of `Header(default=None)`; their bodies are unchanged. The claim route is unaffected (its machine is in the JSON body).
- Regression test: `broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py::test_a_pct_declared_machine_that_does_not_hold_the_batch_gets_410`, `::test_a_stale_cjk_machine_cannot_cancel_a_batch_another_took_over`, `::test_the_plain_header_wins_and_a_malformed_pct_is_a_410_not_a_500` - all three fail with the handlers put back to `Header(default=None)` (ran: 200 instead of 410); `::test_the_cjk_holder_passes_the_machine_check_via_the_pct_header` is a guard (passes both ways).
- Tests run: `broll\web .venv python -m pytest tests/test_bug_hunt_2026_09_24_w2_broll.py tests/test_fleet_ingest.py -q` -> 101 passed.
- Skew / deploy order: either side first. An old companion sends the plain header (unchanged path) or, for a CJK name, raised before this wave; a 0.9.79 companion against an old server degrades to "no machine check", as c-broll-music noted. A server reading the twin changes nothing for a caller that does not send it.
- OWED: none (music/web and the ytdl twin were routed by c-broll-music to music-ytdl and c-ytdl).
- Review round (2026-09-25): no problem raised against this finding; unchanged. Re-ran `tests/test_bug_hunt_2026_09_24_w2_broll.py tests/test_fleet_ingest.py` -> 102 passed.

## ui-dash-static-5 (owed from d-ui, parity) - b-roll muted text below AA
- Status: FIXED
- Verified as: `broll/web/static/style.css` `--muted: #6f6f7a` is 3.98 / 3.82 / 3.63 on --bg / --panel / --field; `share_gone.html` paints its only sentence in #6f6f7a on #0a0a0d (3.98), which a client reads.
- Fix: `style.css` `--muted: #8a8a96` (the dashboard's value, 5.3-5.8:1); `share_gone.html` `p { color: #8a8a96 }`. `broll/eval/local_vlm/judge/*` also uses #6f6f7a but is an internal eval page, left alone.
- Regression test: `::test_muted_text_meets_aa_on_every_surface_and_the_gone_page` - fails with #6f6f7a restored (ran).
- Tests run: as above.
- Skew / deploy order: static only, ships with the dashboard image.
- OWED: none (music/web/static/style.css was routed by d-ui to music-ytdl).
- Review round (2026-09-25): the reviewer was right - the finding's second half (`.drawer-close` at #7c1322, 1.86:1 on --bg) was not carried over. /broll injects the dashboard topbar (app.js fetches ../partials/topbar) and styles it only with `broll/web/static/style.css`, and this wave moved the dashboard's own rule to `var(--red)` (dashboard/static/style.css:192), so /broll's drawer close was both below AA and out of parity. Fixed: `broll/web/static/style.css:347` `.drawer-close { color: var(--red) }` (#ff2140 on #0a0a0d, above 4.5:1; hover stays --red-hot). New regression test `::test_the_injected_drawer_close_meets_aa_on_bg` reads the rule's token and checks its contrast on --bg; it fails with `var(--red-dim)` restored (ran: 1 failed) and passes with the fix. Tests: `tests/test_bug_hunt_2026_09_24_w2_broll.py tests/test_fleet_ingest.py` -> 102 passed. The same gap in `music/web/static/style.css:337` belongs to the music chunk (music-ytdl), not touched here.
