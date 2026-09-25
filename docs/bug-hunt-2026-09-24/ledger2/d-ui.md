# d-ui ledger, wave 2 (chunk 1 of 4: builder d-ui)

Shared regression file: `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-ui.py`.
Its browser half runs the REAL htmx 1.9.12 (`static/htmx.min.js`), base.html's
real inline script and `static/htmx_errors.js` in headless Chrome against a
fake XMLHttpRequest (skipped where Chrome is absent). HEAD check: the test
file was run against `git archive HEAD dashboard` in a scratch copy with
`PYTHONPATH` pointed at that copy's `src`: 14 of 16 fail on HEAD. The 2 that
pass are controls (an untouched poll still refreshes, and undoing an untick
still asks nothing). All 16 pass on the fix.

Tests run (this chunk, dashboard venv, from `dashboard/`):
`pytest tests/test_bug_hunt_2026_09_24_w2_d-ui.py` -> 16 passed.
`pytest` over test_bug_hunt_2026_09_11_dash_mounts_ui, _11b_dash_mounts_ui,
test_hand_off_2026_09_11b_dash_mounts_ui, test_static_js_syntax,
test_no_em_dash, test_fleet_audit, test_fleet_halt,
test_sweep_2026_09_04_copy_plan, test_mobile_admin, test_mobile_css,
test_mobile_fleet, test_sweep_2026_09_04_dash_ui, test_tab_memory, test_pwa,
test_admin_tick_for_editor, test_selection_api, test_protection,
test_recovery, test_templates_wave3_2026_09_04, test_topbar_partial,
test_home_layout, test_alerts, test_upload_only -> 772 passed, 2 failed. Both
failures are in the Packages panel, which concurrent CR-334/CR-335 work was
editing at the time (`admin_packages.html` hx-indicator count 8 != 4, and an
async-route check on `partial_admin_feed_publish` that passed on a re-run a
minute later). This chunk touches neither that template nor that route.

Skew / deploy order for the whole chunk: dashboard only (templates, static,
ui.py). No wire key, no schema, no companion change. Phones with the PWA
installed keep the old `htmx_errors.js` until the service worker's cache
moves, which the central version bump does (CR-243 -5).

## logic-admin-2 - The halt's release time reads "releases itself 0s ago", on every page
- Status: FIXED (duplicate of ui-dash-admin-2, one fix)
- Verified as: verdicts.json CONFIRMED medium, duplicate_of ui-dash-admin-2. `ui.ago` clamps a negative delta to 0, and both halt templates piped the FUTURE `expires_at` through it.
- Fix: see ui-dash-admin-2.
- Regression test: see ui-dash-admin-2.
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-main-1 - Ticking a project in the sidebar folds the whole project tree back up, and on a phone closes the sheet
- Status: FIXED
- Verified as: verdicts.json CONFIRMED medium. Read htmx.min.js 1.9.12: afterSwap fires on each element of the settle list with the responseInfo whose `target` is the original, and the outerHTML swap removes that original. base.html's keeper restored into `evt.detail.target`. The sidebar checkbox swapped `closest .projects` outerHTML, and the answer is the whole partial (handle + nav). Reproduced in headless Chrome with the real htmx: on HEAD a hand-opened group reads closed after an outerHTML swap.
- Fix: `dashboard/templates/base.html` inline script: new `liveRoot(evt)` (detail.target while it is still connected, else the element the event fires on), used by the details keeper and by the DUI-7 fragment scroller. The keeper also records each OPEN `[popover][id]` (with its scrollTop) inside the swapped target on beforeSwap and reopens the replacement after the swap, consumed once per swap. `dashboard/templates/partials/sidebar.html`: the tick now targets `closest .sidebar` with `innerHTML`, the same swap the aside's 30 s poll makes, so the handle is no longer duplicated. ui.py's toggle already returns the sidebar partial for `?view=sidebar`, which the URL always carries; every template including the partial wraps it in `aside.sidebar` (pinned by the test).
- Regression test: `test_an_outerhtml_swap_keeps_the_groups_the_reader_opened` (real htmx; the group reads closed on HEAD), `test_a_swap_that_replaces_the_open_sheet_opens_the_new_one` (sheet closed on HEAD), `test_the_sidebar_tick_swaps_the_aside_not_the_nav` (HEAD markup is `closest .projects` outerHTML).
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-main-2 - The DUI-6 "refusal next to the button" mover does nothing on the outerHTML panels it was written for
- Status: FIXED (same root cause and fix as ui-dash-static-1, which is in chunk 2 of this group: that builder should find it fixed here)
- Verified as: verdicts.json CONFIRMED medium (duplicate_of ui-dash-static-1). Same htmx fact as main-1: the mover and the chip `focusable()` pass searched `detail.target`, the detached panel. Reproduced with real htmx in Chrome: on HEAD the banner stays at the top of a 3000 px panel.
- Fix: `dashboard/static/htmx_errors.js`: a `liveRoot(evt)` in the chip block (focusable) and in the DUI-6 block (mover). An innerHTML target is still connected and is used exactly as before, so the 2026-09-11 node harnesses (which build `detail.target` by hand, with no `isConnected`) keep their meaning and still pass. Also, when two forms post to one path, the mover picks the one whose hidden inputs match the sent parameters (`sentBy`), else the first as before.
- Regression test: `test_a_refusal_on_an_outerhtml_panel_lands_beside_its_button` (real htmx outerHTML swap; on HEAD the banner is not beside the form, not in view, and has no `form-error`).
- Tests run: see the chunk header (both 2026-09-11 harness files pass unchanged).
- Skew / deploy order: dashboard only.
- OWED: none. Note for chunk 2 (ui-dash-static-1): the node harness tests in test_bug_hunt_2026_09_11_dash_mounts_ui.py (HTMX_HARNESS) and _11b still fabricate `detail.target`. They were left untouched here; the real-htmx coverage is now in the w2 d-ui file.

## ui-dash-main-3 - The project page's 10 s poll wipes what an admin is typing into MOVE and SHARE A FOLDER
- Status: FIXED
- Verified as: verdicts.json CONFIRMED medium. `#project-detail` polls every 10 s innerHTML; the SHARE and MOVE forms are inside it with id-less inputs, and nothing paused the poll (grep of static/ and templates/ for hx-preserve, hx-sync or a focus guard: none).
- Fix: `dashboard/static/htmx_errors.js`, new block "A POLL NEVER WIPES WHAT SOMEBODY IS DOING INSIDE IT". On `htmx:beforeRequest` for a poll (a GET from an element whose hx-trigger has `every N`, which also covers pwa.js's visible-again refresh), the beat is cancelled (`preventDefault`) while the panel holds: focus in a text-like field or select; a field somebody edited that still differs from its server value (held at most 5 min after the last edit, so an abandoned half-filled form cannot freeze a panel all day); a write of its own in flight (tracked from `htmx:beforeSend` to `htmx:afterRequest`, capped at 5 min); or an open popover. Fields that post themselves (hx-* on the field) and checkboxes/radios do not count. A skipped beat is not an error and touches nothing; the next beat is normal.
- Regression test: `test_a_poll_does_not_wipe_a_field_being_typed_in` (HEAD: value emptied and focus lost; the fix also keeps it after blur and sends no poll), control `test_a_poll_resumes_once_nothing_is_being_done`.
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-main-7 - [ UNDO ] on a TICKED row takes a project off computers with no confirm, unlike every other untick
- Status: FIXED
- Verified as: verdicts.json CONFIRMED medium. `plan_changes.html` had no hx-confirm. `partial_plan_change_undo` removes every machine in `after` that is not in `before`, which is a person-wide untick for a person-level tick. The row and the notice named only the slug.
- Fix: `dashboard/src/ccsync_dashboard/ui.py` `_plan_changes_context` adds `label` (projects.label, or the slug when the row is gone; new helper `_project_label`) and `undo_removes` (exactly the machines the undo would remove, '' shown as "unassigned") to each row, and the undo notice names the label. `dashboard/templates/partials/plan_changes.html`: the PROJECT column shows the label (slug in `title`), and the [ UNDO ] form carries the DASH-8 confirm ("This removes <label> from <editor>'s N computers (A, B). Their copies stay on disk; ...") only when it removes something. hx-confirm is a string attribute, never compiled, so a folder name cannot break it.
- Regression test: `test_undoing_a_person_tick_asks_first_and_names_the_computers` and `test_the_undo_notice_and_the_row_name_the_folder_not_the_slug` (both fail on HEAD); control `test_undoing_an_untick_puts_back_without_a_question`.
- Tests run: see the chunk header (test_fleet_audit and test_sweep_2026_09_04_copy_plan unchanged and green).
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-main-8 - The sidebar's projects sheet shuts under a phone user every 30 s
- Status: FIXED
- Verified as: verdicts.json CONFIRMED medium. Every page's aside polls /partials/sidebar every 30 s innerHTML, and the replacement `<nav popover>` is a new closed element. Nothing in static/ or ui.py referenced `projects-sheet` or `popover`, and pwa.js slows only the 2 s and 5 s polls.
- Fix: the poll-pause block (ui-dash-main-3) skips the beat while a popover inside the polled element is open, so the sheet is neither closed nor scrolled back. base.html's keeper also reopens an open popover after any swap that replaced it, with its scroll position. That is the belt, and it is what the tick needs.
- Regression test: `test_a_poll_does_not_shut_an_open_sheet` (HEAD: the sheet is closed and the poll went out), `test_a_swap_that_replaces_the_open_sheet_opens_the_new_one`.
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-admin-2 - The fleet halt says it "releases itself 0s ago" for the whole 24 hours it is active
- Status: FIXED
- Verified as: verdicts.json CONFIRMED medium; `ui.ago(now+23h)` -> "0s ago" (read the clamp).
- Fix: `dashboard/src/ccsync_dashboard/ui.py` new `until()` filter ("in 23h 30m", "in 5m", "in 2d 1h"; "any moment now" once past; offset-less stamps read as UTC like `ago`; unparseable shown as is), registered as `until`. `partials/fleet_halt_banner.html` and `partials/fleet_halt.html` use it in the ACTIVE branch. The expired branch keeps `ago`, since the stamp is in the past there.
- Regression test: `test_until_says_how_far_away_a_future_stamp_is`, `test_an_active_halt_says_when_it_releases_itself` (renders both routes with a real halt; HEAD says "releases itself 0s ago").
- Tests run: see the chunk header (test_fleet_halt green).
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-admin-3 - The Users and Packages polls wipe what the admin is typing and orphan in-flight writes (undoing DUI-4's busy labels)
- Status: FIXED
- Verified as: verdicts.json CONFIRMED medium. admin_users.html (30 s and 60 s) and admin_packages.html (30 s) poll innerHTML around forms whose targets are `closest .admin-users-box` / `.admin-packages-box`. htmx 1.9.12's response path swaps into the target computed at request time, with no `bodyContains` check.
- Fix: the same poll-pause block (ui-dash-main-3). A panel with a write of its own in flight, focus in a field, or an edited field is not replaced, so the busy label stays and the answer lands in a box that is still on the page.
- Regression test: `test_a_poll_does_not_orphan_a_write_in_flight` (HEAD: the poll fires during the held POST and the busy form is replaced), `test_a_poll_does_not_wipe_a_field_being_typed_in`.
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-admin-5 - The result of SEND A TEST / SET PASSWORD / RUN NOW / RESTORE / REHEARSE / a date refusal renders a screen or more above the button
- Status: FIXED
- Verified as: verdicts.json CONFIRMED medium. The three partials render `error` as `class="banner"` (not `error-banner`) and `notice` as a plain muted div at the top of the panel, and they swap outerHTML. The FAILED rehearsal and several other outcomes arrive as `notice`. The mover itself also never worked on outerHTML panels (ui-dash-main-2).
- Fix: `partials/admin_alerts.html`, `recovery.html`, `protection.html`: the error is `banner error-banner` and the notice is `muted result-banner`. `static/htmx_errors.js`: the mover also moves `.result-banner` (with class `form-result`; a refusal wins when both are present). It picks the pressed form among same-path forms by its hidden inputs (Protection's two date acks). For a form taller than half the viewport (alert settings, one [ SAVE ] under twenty fields) it places the answer above the form's last submit button instead of above its first field. `static/style.css`: `.form-result` shares the `.banner.form-error` block rule.
- Regression test: `test_a_result_banner_lands_beside_the_form_that_was_pressed` (two same-path forms; HEAD leaves it at the top), `test_the_three_admin_panels_mark_their_banners_for_the_mover`, `test_an_answer_to_a_tall_form_lands_at_its_foot` (HEAD: not placed before the SAVE button), and the outerHTML refusal test above.
- Tests run: see the chunk header (test_protection, test_recovery and test_alerts green).
- Skew / deploy order: dashboard only.
- OWED: none


# d-ui ledger, wave 2 (chunk 2 of 4: builder d-ui)

Same shared regression file, `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-ui.py`
(15 tests appended under "Chunk 2"). HEAD check: the whole file was run
against `git archive HEAD dashboard` in a scratch copy with `PYTHONPATH` on
that copy's `src` (the import was confirmed to resolve there): all 13 of this
chunk's non-control tests fail on HEAD; the 2 controls (a 401 and a failing
poll still raise the stale banner; cancelling a HELD job still names the
computer) pass on both. Whole file on the fix: 31 passed.

Tests run (dashboard venv, from `dashboard/`):
`pytest tests/test_bug_hunt_2026_09_24_w2_d-ui.py tests/test_fleet_halt.py
tests/test_static_js_syntax.py tests/test_no_em_dash.py tests/test_jobs_cancel.py
tests/test_packages.py tests/test_health_page.py tests/test_upload_only.py`
-> 343 passed. Also test_ai_providers, both 2026-09-11 dash_mounts_ui files,
test_hand_off_2026_09_11b_dash_mounts_ui, test_cr335_packages_page,
test_mobile_admin, test_site_history, test_sweep_2026_09_04_dash_ui,
test_templates_wave3_2026_09_04, test_admin_assignments, test_health -> all
green except `test_templates_wave3_2026_09_04::test_the_four_long_controls_on_packages_show_that_they_are_working`
(hx-indicator count 8 != 4), the same concurrent CR-335 failure chunk 1
recorded; that count comes from CR-335's new MAKE CURRENT forms, not from this
chunk's text edits in the same template.

Rendered in headless Chrome at 1280 and 390 px (scratchpad): the Settings
save answer sits on the [ SAVE ] line on a phone; the expired-halt panel's
[ OK, IT CAN STAY OFF ] was first drawn inline beside the reason box (it read
as the button that sends the reason) and was moved onto its own line.

Skew / deploy order for the chunk: dashboard only. The one new wire item is
the undo POST's optional JSON body `{"expected_at": ...}`, which the current
route ignores (it declares no body) and whose absence an old page simply
does not send. No schema, no companion change.

## ui-dash-static-1 - the "refusal moves next to its button" handler never fires for the five panels that swap outerHTML
- Status: ALREADY_FIXED (by chunk 1 of this group, same wave, uncommitted: ui-dash-main-2)
- Verified as: verdicts.json CONFIRMED medium. `static/htmx_errors.js` now carries `liveRoot(evt)` in BOTH places the finding names: the DUI-6 mover block and the chip `focusable()` pass (line ~110 and ~246). Chunk 1's `test_a_refusal_on_an_outerhtml_panel_lands_beside_its_button` covers the mover with real htmx; nothing covered the chip half.
- Fix: none new. Added the missing coverage only.
- Regression test: `test_a_chip_swapped_in_by_an_outerhtml_panel_is_keyboard_reachable` (real htmx 1.9.12 outerHTML swap; HEAD leaves the new chip with no tabindex).
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: none. (The 2026-09-11 node harnesses still hand-build `detail.target`; they pass unchanged and are left as they are, as chunk 1 noted.)

## ui-dash-static-2 - every 4xx refusal is reported as "THIS PAGE HAS STOPPED UPDATING", the server's reason is thrown away, and a signed-in 403 is called an ended session
- Status: FIXED
- Verified as: verdicts.json CONFIRMED medium. Read `htmx_errors.js`: responseError never read `xhr.responseText`, mapped 401 and 403 to "session has ended" and every other status to the stale banner. Read `ui.partial_toggle`: `403 if user else 401`, and 404/409 with a `detail`; the CSRF gate answers 403 `{"detail": "... reload the page and try again"}` and its origin half `{"error": ...}`.
- Fix: `dashboard/static/htmx_errors.js` first block: `reasonOf(xhr)` (FastAPI `detail` string or validation list, or `error`), and a `refuse(elt, status, reason)` path taken for a 4xx (not 401) answer to a WRITE (verb not GET): a `div.banner.error-banner.form-error.htmx-refusal` with role=alert, "▲ Refused: <reason>" or "▲ Not allowed: <reason>" for 403, inserted before the pressed control's form/label (textContent only), a checkbox flipped back to what the server still holds, and the page NOT marked stale. A second press of the same control drops its old refusal. 401 keeps "Your session has ended"; a 4xx on a poll (GET) keeps the stale banner, with 403 now worded as a refusal to this account rather than an ended session; 5xx, sendError and timeout are unchanged.
- Regression test: `test_a_409_says_the_servers_reason_beside_the_box_and_unticks_it` (HEAD: stale banner "answered 409", no reason, box left ticked), `test_a_signed_in_403_is_not_called_an_ended_session` (HEAD: "session has ended"); control `test_a_401_and_a_failing_poll_still_say_the_page_is_stale`.
- Tests run: see the chunk header (test_sweep_2026_09_04_dash_ui's DUI-2 pins, including "no innerHTML =", still green).
- Skew / deploy order: dashboard only; PWA phones pick up the new htmx_errors.js when the central version bump moves the service worker cache.
- OWED: none

## ui-dash-admin-6 - Site Settings [ SAVE ] gives its answer at the top of the page, and a stale "saved" stays beside a later failure
- Status: FIXED
- Verified as: verdicts.json CONFIRMED medium. HEAD `site_settings.js` wrote "saved" into `#settings-saved` and never cleared it; `showError` touched only `#settings-error`; both sat above the first field, [ SAVE ] ~20 fields below, no scrollIntoView. Import and undo errors used the same top slot.
- Fix: `dashboard/templates/admin_settings.html`: the two top slots are gone; each of [ SAVE ], [ IMPORT ] and [ UNDO ] has its own `span.settings-result` (role=status, aria-live) on its button's line. `dashboard/static/site_settings.js`: `showError` replaced by `showResult(id, ok, message)`, which REPLACES the line (so "saved" can never stand beside "could not save"), marks it ok/bad and scrolls it into view; a save writes "saving..." then "saved at HH:MM:SS" or "▲ could not save: ...". `dashboard/static/style.css`: `.settings-result` (+ `.ok` green / `.bad` red-hot).
- Regression test: `test_a_save_answers_beside_its_button_and_a_refusal_replaces_saved` (real rendered /admin/settings + site_settings.js in Chrome with a fake fetch; HEAD has no line beside the button and keeps "saved"), `test_the_settings_page_has_no_answer_slot_above_the_fields`.
- Tests run: see the chunk header (test_ai_providers green; it renders the same page).
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-static-3 - Settings [ UNDO ] names yesterday's change after an in-page save, then undoes the save just made
- Status: PARTIAL (client side fixed; the server's check of what was confirmed is OWED to d-auth)
- Verified as: verdicts.json CONFIRMED medium. `loadSiteHistory` ran once at DOMContentLoaded and captured `latest` in the undo closure; the form save, the CLI-provider checkbox and the wizard's accept all PUT /api/v1/admin/site (a new history entry) and none reloaded it; `setup_routes.api_admin_site_undo_last_change` reverts `entries[0]`.
- Fix: `dashboard/static/site_settings.js`: `loadSiteHistory` returns its promise, disarms the undo button (disabled, no onclick) while a reload is out, and is called after a successful SAVE, the CLI flag change and the wizard's accept; the undo POST now sends `{"expected_at": <the entry the admin confirmed>}` and a failed undo reloads the history and answers on the undo's own line.
- Regression test: `test_undo_after_an_in_page_save_names_the_save_just_made` (HEAD: the confirm quotes the 2026-09-20 entry loaded at page load; the fix quotes the save just made and sends its `at` as `expected_at`).
- Tests run: see the chunk header (test_site_history green: the route still takes a body-less POST).
- Skew / deploy order: dashboard only, and the two halves are independent: today's route ignores the body, and a page older than the d-auth half simply omits it (so the route must treat a missing `expected_at` as "no check").
- OWED: d-auth, `dashboard/src/ccsync_dashboard/setup_routes.py` `api_admin_site_undo_last_change`: accept an OPTIONAL JSON body `{"expected_at": str}`; when present and not equal to `entries[0]["at"]`, answer 409 "the newest change is no longer the one you confirmed (someone saved since): reload the page" and change nothing. Absent or empty = today's behaviour (older page, JSON door, tests in test_site_history.py). This closes the second-admin / second-tab race the client-side reload cannot.

## ui-dash-admin-7 - HEALTH says "Every check this server runs answered" when a source raised
- Status: FIXED
- Verified as: verdicts.json CONFIRMED medium. `ui._health_rows`: four `except Exception: log.exception(...)` blocks that add no row; with all four raising, `health_rows` is empty and admin_health.html renders "Nothing is open. Every check this server runs answered".
- Fix: `dashboard/src/ccsync_dashboard/ui.py` `_health_rows`: a local `failed(...)` adds one `band="unknown"` row per source that raised ("Could not read the protection lines", subject `<ExcType>: <first 160 chars>` as `_triage_status` already does, diagnosis "That is not checked, not OK.", fix naming that source's own page), so the NOT CHECKED band counts it and the all-clear sentence cannot render. Rows a source produced before raising are kept.
- Regression test: `test_a_source_that_raises_is_not_checked_not_ok` (one source raising shows its row; all four raising gives exactly four unknown rows and no all-clear; HEAD shows nothing for either).
- Tests run: see the chunk header (test_health_page green).
- Skew / deploy order: dashboard only.
- OWED: none

## logic-plans-2 - the project page's person-level mode buttons tick the project onto computers that never had it, with no confirm and no capacity check
- Status: FIXED (at the severity the verifier left: low, the missing confirm; person-level scope is the documented design, UPLOAD_ONLY_TICK.md section 2, and is kept)
- Verified as: verdicts.json DOWNGRADE to low. Read project_detail.html: neither mode button had hx-confirm. Also found while tracing: `tick_warning` (UX-1) and `toggle_editor_machines` (DASH-8) were built only by `_sidebar_context`, i.e. the full page. `partial_project` (the 10 s poll of #project-detail), the tick's own `view=project` answer, the link edit and both move renders passed no `tick_warning` (three of them no machines either), so even [ TICK ]'s capacity confirm vanished ten seconds after the page loaded.
- Fix: `dashboard/src/ccsync_dashboard/ui.py`: new `_tick_confirms(conn, editor, slug)` -> `{toggle_editor_machines, tick_warning}` (tick_capacity_warning is two indexed reads), spliced into all five project_detail renders. `dashboard/templates/partials/project_detail.html`: [ SWITCH TO FULL SYNC ] always asks, naming the person's computers, saying it ticks any that lack it and that proxies come down on each, plus the UX-1 capacity sentence when there is one; [ SWITCH TO UPLOAD ONLY ] asks when it changes an existing tick (it flattens a mixed plan and stops downloads), not when it is a fresh upload-only tick.
- Regression test: `test_the_mode_buttons_ask_before_ticking_every_computer` (full page and poll partial; HEAD: no hx-confirm), `test_the_poll_keeps_the_ticks_capacity_confirm` (HEAD: the poll's [ TICK ] has no UX-1 sentence).
- Tests run: see the chunk header (test_upload_only, test_admin_assignments green).
- Skew / deploy order: dashboard only.
- OWED: none

## logic-admin-3 - An expired fleet stop leaves a banner on every page that nothing in the UI can clear
- Status: FIXED
- Verified as: verdicts.json DOWNGRADE to low (truthful, blocks nothing, cannot be dismissed). Read fleet_halt.html: the `{% else %}` branch with `halt.expired` offered only [ STOP ALL SYNCING ]; `db.set_fleet_halt(active=False)` is the only clear, posted from the ACTIVE branch only.
- Fix: `dashboard/templates/partials/fleet_halt.html`: in the expired branch, on its own line, [ OK, IT CAN STAY OFF ] posting `active=0`, `ack_expired=1` and a history reason "the expired stop was acknowledged". `dashboard/src/ccsync_dashboard/ui.py` `partial_admin_set_fleet_halt`: with `ack_expired=1` and a halt that is ACTIVE now (a new stop set since the panel was drawn), refuse with a banner and change nothing, so a stale tab can never release a live halt with this button. `partials/fleet_halt_banner.html`: the expired banner tells an admin where to take it down (the active branch already linked).
- Regression test: `test_an_expired_halt_can_be_taken_down_without_a_new_halt` (HEAD: no button; the fix clears `expired` and the banner), `test_the_ok_button_never_releases_a_live_halt`.
- Tests run: see the chunk header (test_fleet_halt green).
- Skew / deploy order: dashboard only. The history row reads RELEASE with the acknowledgement as its reason; no new history action was added (d-db's set_fleet_halt is unchanged).
- OWED: none

## logic-admin-6 - The Packages page tells a customer's admin to run tools\ship.cmd, a vendor-only script
- Status: PARTIAL (the page fixed; the refusal text in package_store.py is OWED to d-ops)
- Verified as: read (not verified by anyone before, LOW). admin_packages.html names `tools\ship.cmd` unconditionally in the empty state, the footer, the [ UNSIGNED ] chip title and the unsigned make-current confirm; `package_store.make_current_refusal` says the same. `release_feed.build_feed_view` reports `configured` from `release_feed_url`, and the page's own [ CHECK NOW ] is the action a feed site has. RELEASE_PATHWAYS: ship.cmd is pathway A, the studio's own dashboard. Real.
- Fix: `dashboard/templates/partials/admin_packages.html`: `via_feed` (feed configured); on a feed site the empty state names [ AVAILABLE FROM THE VENDOR ] and [ CHECK NOW ], the footer says builds come from the supplier's channel and keeps ship.cmd only as a parenthetical for a site that builds its own, and the UNSIGNED chip and confirm say to publish the signed build from the vendor list. A site with no feed keeps the ship.cmd text exactly. Implemented with `{% if %}` rather than Jinja string literals, so the backslash in `tools\ship.cmd` is never a Jinja escape. `dashboard/tests/test_packages.py::test_c4_unsigned_make_current_confirm_copy_is_pinned` updated (it pinned the raw template text of the confirm, which is now two branches).
- Regression test: `test_a_feed_site_is_pointed_at_the_feed_not_ship_cmd` (HEAD: a feed site is told "or from your wired computer with tools\ship.cmd"; control: a no-feed site keeps it).
- Tests run: see the chunk header (test_packages, test_cr335_packages_page green; the wave3 hx-indicator count failure is CR-335's, see the header).
- Skew / deploy order: dashboard only.
- OWED: d-ops, `dashboard/src/ccsync_dashboard/package_store.py` `make_current_refusal` (~line 220): the unsigned refusal says "Republish it through tools\ship.cmd instead" to every site; when the vendor feed is configured (`bool(settings.release_feed_url)`), say "Publish the signed build from AVAILABLE FROM THE VENDOR instead" and keep the ship.cmd sentence otherwise. test_packages.py:267 pins `tools\ship.cmd` in that detail for a no-feed site and stays true.

## logic-admin-7 - Cancelling a pinned job says "the computer running it" will stop it, but this server runs it
- Status: PARTIAL (the jobs page fixed; the same sentence in triage mail's executor is OWED to d-diag)
- Verified as: read (LOW, unverified before). `db.request_job_cancel` returns "requested" for CLAIMED, RUNNING and PINNED alike; `ui.partial_admin_cancel_job` always said "will stop on its next report - the computer running it is the only thing that can end it". CLAUDE.md and api.py's docstring: pinned = "this container's own worker ... should_stop()". Real.
- Fix: `dashboard/src/ccsync_dashboard/ui.py` `partial_admin_cancel_job`: re-reads the job after the request (the request sets only cancel_requested_*, never the state) and, for a PINNED job, answers "job #N will stop when this server's own worker next checks it: it is running here, not on any computer". Queued and held wording unchanged. No d-db change needed.
- Regression test: `test_cancelling_a_pinned_job_names_this_server` (HEAD: "the computer running it"); control `test_cancelling_a_held_job_still_names_the_computer`.
- Tests run: see the chunk header (test_jobs_cancel green).
- Skew / deploy order: dashboard only.
- OWED: d-diag, `dashboard/src/ccsync_dashboard/triage_actions.py` `_x_cancel_job` (~line 240): same wording bug in the reply-mail action; after `request_job_cancel` returns "requested", read `db.get_job(conn, id)` and for `state == db.JOB_PINNED` return "job #N will stop when this server's own worker next checks it; it is running here, not on any computer" (no em dash; this string reaches the owner's mail).


# Chunk 3 of 4 (builder d-ui)

Regression tests appended to `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-ui.py`
(section "Chunk 3"). HEAD check: the whole file was run against
`git archive HEAD dashboard` in a scratch copy with `PYTHONPATH` on that
copy's `src`. 17 of chunk 3's 21 tests fail on HEAD. The 4 that pass are
controls: your own computers carry no `as=`, an abandoned picker stops holding
the poll, a queue_machine that is not theirs is ignored, and the keeper
mechanism itself with a data-key. All 50 in the file pass on the fix. Layout
checked in headless Chrome in a 390 px iframe: the fix-root chips wrap onto a
second row, and a minted cce1 token wraps inside its green box (screenshots
in the scratchpad).

Tests run (dashboard venv, from `dashboard/`):
`pytest tests/test_bug_hunt_2026_09_24_w2_d-ui.py` -> 50 passed.
`pytest` over test_api, test_alerts, test_templates_wave3_2026_09_04,
test_no_em_dash, test_static_js_syntax, test_fleet_halt, test_packages,
test_mobile_css, test_mobile_admin, test_recovery, test_home_layout,
test_sweep_2026_09_04_copy, test_hand_off_2026_09_11b_dash_mounts_ui,
test_bug_hunt_2026_09_11b_dash_mounts_ui, test_selection_api,
test_admin_tick_for_editor, test_tab_memory, test_sweep_2026_09_04_dash_ui ->
967 passed, 1 skipped, 1 failed. The failure is the same CR-335 Packages one
chunk 1 recorded (`admin_packages.html` hx-indicator count 8 != 4), on a
template line this chunk did not touch. test_jobs_cancel,
test_cr311_queue_says_on_hold and test_bug_hunt_2026_09_11_dash_api_jobs are
green.

Existing tests edited because the wording they pinned changed:
- `tests/test_api.py` lines 359 and 376: "SHARE REMOVAL(S) REFUSED" is now "2 SHARE REMOVALS REFUSED".
- `tests/test_alerts.py:1688`: "2 finding(s)" is now "2 findings".
- `tests/test_templates_wave3_2026_09_04.py:168`: "4 file(s) still uploading" is now "4 files".
- Chunk 2's `test_undo_after_an_in_page_save_names_the_save_just_made`: the history list now says "0s ago" and the exact stamp is the row's title. The undo confirm still carries the exact stamp and still sends `expected_at`.

Skew / deploy order for the whole chunk: dashboard only (templates, static,
ui.py). There is one new query parameter, `queue_machine`, on the dashboard's
own htmx toggle route. It is optional and validated, and an older dashboard
ignores it. No wire key to a companion and no schema change. Phones with the
PWA installed keep the old `htmx_errors.js`, `site_settings.js` and
`style.css` until the central version bump moves the service worker's cache.

## ui-dash-main-4 - The fix-root computer picker drops `?as=`, so an admin checking an editor's second computer lands back on their own queue
- Status: FIXED
- Verified as: verifier med-14 DOWNGRADED this to low (the mechanism holds, but it is a read-only view hop). I re-read fix_root.html:18-21 (hrefs `/` and `/?machine=<m>`), `ui._queue_editor` (reads `as` only from the query) and `_queue_machine` (drops a name not in `machines_of(editor)`). The admin does land on their own queue.
- Fix: `dashboard/templates/partials/fix_root.html`: both links carry `as=<queue.editor>` when the queue's editor is not the session user. This is the same test as fleet.html's poll URL, case-folded like `_as_qs`. `[ LAST TO REPORT ]` becomes `/?as=leso` and a computer becomes `/?machine=EDIT-PC&as=leso`.
- Regression test: `test_the_fix_root_chips_keep_the_editor_the_admin_is_viewing`. On HEAD the hrefs have no `as=`. The test also follows the link and checks for `[ SYNC QUEUE: LESO ]` with the chip lit. Control: `test_the_fix_root_chips_of_your_own_computers_carry_no_as`.
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-main-5 - On a phone the fix-root computer chips run off the screen and cannot be reached
- Status: FIXED
- Verified as: read (LOW, not verified before), then measured. The row was a plain `div.mono-sm` (`white-space: nowrap`) of inline chips, inside `.main { overflow-x: auto }`. In headless Chrome with the real style.css at 390 px, on HEAD the MacBook chip's right edge is past the 390 px box.
- Fix: the `fix_root.html` row gets class `fix-root-machines`. `dashboard/static/style.css` has a new rule beside `.root-line`: `display:flex; flex-wrap:wrap; gap`, so each chip is a flex item that moves to the next row.
- Regression test: `test_the_fix_root_chips_wrap_on_a_phone` renders the real `/` inside a 390 px box. On HEAD the rightmost chip edge is past the box edge.
- Tests run: see the chunk header. The 390 px screenshot shows `[ Leso-MacBook-Pro-2024.local ]` on its own second row.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-main-6 - The project-roots 30 s poll closes an open [ BROWSE ] folder picker and resets a changed select
- Status: FIXED (chunk 1's poll pause already covered the select half; the picker half is fixed here)
- Verified as: read (LOW). fleet.html's `/partials/project-roots` wrapper polls innerHTML every 30 s, and the picker is swapped into `#roots-browse-mN` inside it. Chunk 1's "A POLL NEVER WIPES" block in htmx_errors.js already skips a beat while a changed `<select>` still differs from its default (the `change` listener records selects, and `isDirty` compares `defaultSelected`). So the reverting select is already fixed in this wave. Nothing held the poll for an open picker, because the picker has no field and no popover.
- Fix: `dashboard/static/htmx_errors.js` `busy()`: a `[data-poll-hold]` element inside the polled panel holds the beat for DIRTY_HOLD_MS (5 min) from the first beat that finds it. Each step of the walk draws a new element, which resets the timer, so an abandoned picker stops freezing the list. `templates/partials/project_roots_browse.html`: `data-poll-hold` on `.roots-browse`.
- Regression test: `test_the_roots_poll_leaves_an_open_folder_picker_alone` runs the real htmx; on HEAD the beat fires and empties the picker. `test_the_folder_picker_is_marked_to_hold_the_poll` fails on HEAD because the attribute is missing. Control: `test_a_picker_left_open_stops_holding_the_poll`.
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-main-9 - [ UNTICK ] in the sync queue re-renders the panel as the person's view and drops the "safe to close" line
- Status: FIXED
- Verified as: read (LOW). `partial_toggle`'s last return rendered `my_queue.html` with `build_queue_view(conn, editor, machine=target)`, where target is None for the queue's button, and passed no `safe_to_close`. So on `/?machine=X` the answer was the person's queue, and the DUI-19 sentence was gone until the next 10 s poll.
- Fix: `templates/partials/my_queue.html`: the untick posts `?queue_machine=<m>` when the panel is about one computer. This is a view key, deliberately not `machine=`. Using `machine=` would turn the person-level untick, whose confirm names every computer, into a one-machine untick. `dashboard/src/ccsync_dashboard/ui.py` `partial_toggle`: the queue render checks `queue_machine` against `machines_of(editor)`, and anything else gets the person's view, as in `_queue_machine`. It renders the queue for that computer and passes `queue_machine` and `safe_to_close`, built exactly as `partial_queue` builds it. The `?machine=` path (assignments) is unchanged.
- Regression test: `test_the_queue_untick_keeps_the_computer_and_the_safe_to_close_line`. On HEAD the page's button has no `queue_machine` and the answer has no sentence. The test also asserts the write stayed person-level (the project is off both computers). Control: `test_a_queue_machine_that_is_not_theirs_is_the_persons_view`.
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only. An older dashboard ignores the unknown query key.
- OWED: none

## ui-dash-main-10 - "(s)" plurals survive on the fleet and transfers pages, against UX-10's own rule
- Status: FIXED (every cited line, plus the fleet page's own "safe to close" sentence)
- Verified as: grep of the three templates. fleet_grid.html:78, 80, 239, 276, 280, transfers.html:47, 65 and bins.html:4 all print "(s)" or "(S)" beside a known count. `ui.safe_to_close`, rendered on the same fleet and transfers panels, said "N file(s) still uploading" and "N file(s) are still coming down".
- Fix: the templates use `{{ "s" if n != 1 }}` (and "is/are", "attempt has/attempts have"), as the neighbouring lines do. Changed places: `fleet_grid.html` (the enforce-refusal banner's count and folders, sync-engine restart attempts, the moved-folder title, the express-dropped title), `transfers.html` (two queue counts) and `bins.html` (originals, proxy files). In `ui.safe_to_close` both sentences now agree with their count.
- Regression test: `test_the_cited_panels_carry_no_brackets_s` fails on HEAD ("(S)" in fleet_grid and others). `test_safe_to_close_counts_in_words` fails on HEAD ("file(s)"). The existing pins were updated (see the header).
- Remaining, not fixed: `ui.CHIP_HELP` still has about a dozen `{n} x(s)` tooltip strings (peers, tasks, clips, conflict files and others). They are format strings that need verb agreement ("have crashed", "are not"), several are pinned by other suites, and the finding did not cite them. One pass could add an `{s}`/`{are}` pair that `chip_help` fills from `n`. The admin-page notices in ui.py ("copied N file(s)", "revoked N session(s)") are also outside the fleet and transfers pages this finding is about.
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-admin-4 - "OTHER VERSIONS HELD ON THIS SERVER" (the rollback list) snaps shut every 30 seconds
- Status: FIXED
- Verified as: verifier med-15 DOWNGRADED this to low. Confirmed at HEAD: `details.pkg-other` (admin_packages.html) and the halt history's `details.proj-group` (fleet_halt.html) have neither a `data-key` nor an `id`. base.html's keeper records only `details[data-key]`, and tab_memory.js's `detailsId` needs one of the two.
- Fix: `data-key="pkg-other"` on OTHER VERSIONS and `data-key="halt-history"` on PREVIOUS STOPS, each with a comment.
- Regression test: `test_the_rollback_list_and_the_halt_history_are_keyed` fails on HEAD (no data-key). `test_a_keyed_section_stays_open_across_a_poll` runs the real htmx and base.html's keeper: the keyed section stays open across a beat, and the same markup without the key comes back closed.
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-admin-9 - SMTP [ SET PASSWORD ] / [ CLEAR ] say "stored" / "cleared" when the environment password is the one in use
- Status: FIXED
- Verified as: read (LOW). `alerts.read_password` returns the environment value first. `admin_alerts.html` still offered both buttons when `password_source == "env"`, next to a sentence saying the password cannot be changed there. The route wrote or deleted the file and answered "password stored." or "password cleared.".
- Fix: `templates/partials/admin_alerts.html`: when the environment sets the password, the page no longer offers the password input or either button. The block shows the mask of the password in use and says to change it where the server is deployed. `ui.partial_admin_alerts_password`: a stale tab can still post, and the file write or removal happens as before, but the notice now adds that the deployment's environment password is still the one in use. The secret itself never reaches the page; only the existing mask does.
- Regression test: `test_the_env_password_offers_no_set_or_clear` fails on HEAD (both buttons shown). `test_a_stale_tab_setting_the_password_is_told_the_env_still_wins` fails on HEAD (a bare "password stored."). Its control: with the environment password removed, the form is offered again and "cleared" carries no caveat.
- Tests run: see the chunk header (test_alerts green).
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-admin-11 - A minted report token runs off a phone screen
- Status: FIXED
- Verified as: read (LOW), then measured. `.mono, .mono-sm { white-space: nowrap }` beat `.minted-value { word-break: break-all }`, and `#minted-secret` sits outside `.admin-users-box`, which is where mobile.css's unwrap rule is scoped. In headless Chrome at 390 px on HEAD, the value's scrollWidth is wider than its box.
- Fix: `dashboard/static/style.css` `.minted-value`: `white-space: normal`. It has the same specificity as `.mono-sm` and comes later in the file, so it wins. The class stays for the font size.
- Regression test: `test_a_minted_token_wraps_inside_its_box` uses the real style.css at 390 px. On HEAD the value overflows.
- Tests run: see the chunk header. The 390 px screenshot shows the cce1 token on two lines inside the green box.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-admin-12 - Raw ISO timestamps beside humanised ones on the same pages
- Status: PARTIAL (every template and the Settings history fixed; the db.py refusal text OWED to d-db)
- Verified as: read (LOW). Confirmed raw UTC ISO in: report tokens CREATED and LAST USED, the halt's "set by X at <iso>", alerts' "Replies last read <iso>", the alert log's WHEN column and digest header, recovery's rehearsal and restore rows, and site_settings.js's change history and undo confirm. The jobs head printed raw seconds. NOT a defect: `triage.running_since` and `triage.last_run.started_at`. The finding lists them, but `triage.local_time` already renders them in the site zone, for example "2026-09-24 11:16 Asia/Taipei", so they are not raw ISO.
- Fix: templates use `{{ x | ago }}` with the stored stamp in `title=`: `admin_report_tokens.html`, `fleet_halt.html`, `admin_alerts.html` (3 places) and `recovery.html` (2 places). `ago(None)` returns "never", which is what LAST USED already said. `admin_jobs.html` uses `| eta` (172800 s shows as "2d 0h"). `dashboard/static/site_settings.js` has a new `agoText()` with ui.ago's buckets, used for the history rows (the exact stamp is the row's title) and the undo confirm. The confirm keeps the exact stamp in brackets: two saves a minute apart both read "1m ago", and that stamp is the `expected_at` that gets sent. While there, the "(s)" plurals in the alert digest header and the recovery rows now agree with their counts.
- Regression test: `test_the_halt_says_ago_not_iso` and `test_report_tokens_say_ago_not_iso` fail on HEAD (ISO in the cells). `test_the_jobs_head_says_how_long_in_words` and `test_the_alert_log_recovery_and_history_humanise_their_stamps` fail on HEAD (raw stamps).
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: d-db, `dashboard/src/ccsync_dashboard/db.py` `set_fleet_halt` (~line 8413). The stale [ KEEP HALTED ] refusal says "Syncing already started again at {when}", where `when` is the raw ISO `expires_at` or `set_at`. Render it for a person, for example `db.parse_iso(when)` formatted as "%Y-%m-%d %H:%M UTC". Better still, use the site zone through `triage.local_time` / `alerts._zone_or_utc` if d-db is willing to import it lazily. No em dash. The route shows this ValueError text verbatim in the halt panel's error banner.


# Chunk 4 of 4 (builder d-ui)

Regression tests appended to `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-ui.py`
(section "Chunk 4"). HEAD check: the whole file was run against
`git archive HEAD dashboard` in a scratch copy with `PYTHONPATH` on that
copy's `src`: all 17 of chunk 4's tests fail on HEAD, each on the assertion
that names the defect (2 POSTs and no refusal line; 0 status polls; "Update
this dashboard to 0.7.55?"; the toast at 793 px under a banner at 747;
"[ COPIED ]" after the window; and so on). All 67 in the file pass on the fix.
Rendered /admin/settings and /login from a TestClient and looked at them in
headless Chrome at 1280 px and in a 390 px iframe: [ SIGN OUT ] fits the
desktop bar, the phone hides it into the drawer as before, and the brighter
--muted still reads as secondary beside --text.

Tests run (dashboard venv, from `dashboard/`): the file above plus
test_sessions, test_topbar_partial, test_pwa, test_no_em_dash,
test_static_js_syntax, test_sweep_2026_09_04_copy, test_sweep_2026_09_04_dash_ui,
test_hardening, test_fleet_halt, test_site_history, test_mobile_css,
test_mobile_admin, test_dashboard_update, test_ai_providers, test_auth,
test_oidc, test_bug_hunt_2026_09_11_dash_mounts_ui,
test_bug_hunt_2026_09_11b_dash_mounts_ui, test_bug_hunt_2026_09_18_dashboard_mediums,
test_cr335_packages_page, test_templates_wave3_2026_09_04,
test_bug_hunt_2026_08_21, test_bug_hunt_2026_09_11b_dash_core, test_health,
test_multi_machine -> 1297 passed, 1 skipped, 2 failed. One was mine
(test_mobile_admin's long-confirm allowlist pinned "They will need to log in",
edited below; the file then passed 82/82). The other is the same CR-335
Packages failure chunks 1 and 3 recorded (`admin_packages.html`
hx-indicator count 8 != 4), on a template this chunk did not touch.

Existing tests edited because the wording they pinned changed (ui-copy-7):
- `tests/test_sessions.py` (two places): "log in again" is now "sign in again".
- `tests/test_topbar_partial.py` (three places): [ LOGOUT ] / [ LOGOUT ALL ] are now [ SIGN OUT ] / [ SIGN OUT EVERYWHERE ].
- `tests/test_mobile_admin.py:67`: the ALLOWED_LONG_CONFIRMS entry for the other-row revoke confirm now matches "They will need to sign in".

Skew / deploy order for the whole chunk: dashboard only (templates, static,
ui.py copy). No wire key, no schema change, no companion change. One new
data attribute (`data-dashupd-older`), which is read only by this dashboard's
own dashboard_update.js. Phones with the PWA installed keep the old
`dashboard_update.js`, `copy_value.js`, `site_settings.js`,
`htmx_errors.js`, `style.css` and the precached /offline page until the
central version bump moves the service worker's cache name.

## ui-dash-admin-14 - Two buttons whose words say something other than what they do
- Status: FIXED
- Verified as: a low, unverified by anyone, so I checked it. `setup_routes.py` undo-last-change reverts site_history's entries[0], which is a save OR an import (the history list and the blurb above the button both say so), and the button read [ UNDO LAST IMPORT ]. The rollback-candidate buttons in `admin_dashboard_update.html` carry `data-dashupd-apply`, and dashboard_update.js's apply handler asked "Update this dashboard to X?" for both.
- Fix: `templates/admin_settings.html`: the button is [ UNDO LAST CHANGE ]. `static/site_settings.js` comment updated to match. `templates/partials/admin_dashboard_update.html`: the [ ROLL BACK TO X ] buttons carry `data-dashupd-older="1"`. `static/dashboard_update.js` onClick: with that marker the confirm is "Roll this dashboard back to X? ... The databases are backed up first and stay as they are: they are not taken back to an older copy." (the apply route backs up and never restores, so that is what it does). [ UPDATE NOW ] keeps its question.
- Regression test: `test_the_settings_undo_is_named_for_any_change` (HEAD renders UNDO LAST IMPORT), `test_the_older_bundle_buttons_are_marked_as_rollbacks` (HEAD has no marker), `test_an_older_bundle_asks_to_roll_back_not_to_update` (real dashboard_update.js in Chrome; HEAD asks "Update this dashboard to 0.7.55?").
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED:
  - d-ops, `docs/ANDROID.md:219`: names the button `[ UNDO LAST IMPORT ]`; it is `[ UNDO LAST CHANGE ]` now.
  - d-auth, `dashboard/src/ccsync_dashboard/setup_routes.py:403, :418, :441`: three comments and docstrings name `[ UNDO LAST IMPORT ]`. Rename them so a grep for the button finds the route. Comments only, no behaviour.

## ui-dash-static-4 - a refused dashboard update or rollback flashes its reason and then erases it
- Status: FIXED (low, downgraded by verifier med-16)
- Verified as: verifier med-16 DOWNGRADE to low. It confirmed the apply path and said the rollback route's catch never reloads, which is right for [ ROLLBACK TO ... ]. But the [ ROLL BACK TO X ] buttons for an older feed bundle go through the APPLY path, so their refusal was wiped too. The hunt's OUT OF TERRITORY note says those 409 on runtime_id every time. I also checked the verifier's claim that the repainted panel "resumes watching" when another admin's update is running: it does not. reloadPanel is a fetch() plus outerHTML, which fires no htmx:afterSwap, so the in-progress line froze. The regression test proves it (0 status polls on HEAD).
- Fix: `static/dashboard_update.js`: `runUpdate` separates a refused POST from a failed run. A refusal repaints the panel, then `showRefusal()` puts "not applied: <reason>" (after the triangle) in its own `#dashupd-refusal` banner above `#dashupd-progress`, so it survives the repaint and sits beside the panel's own "working: ..." line. If the repainted panel says an update is in progress, the watch is resumed there. A module-level `applying` flag plus disabling the clicked button make a double click post once. The accepted path moved unchanged into `runAccepted()`, and its catch now returns reloadPanel's promise so the button is re-enabled when it has settled.
- Regression test: `test_a_refused_update_keeps_its_reason_and_posts_once` (HEAD: 2 POSTs, no refusal line after the repaint), `test_a_refusal_while_another_update_runs_resumes_the_watch` (HEAD: 0 status polls).
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-static-5 - muted explanatory text is below AA contrast, and the phone drawer's close button is 1.8:1
- Status: FIXED
- Verified as: computed WCAG contrast from style.css's tokens: #6f6f7a is 3.98 / 3.82 / 3.63 on --bg / --panel / --field, and --red-dim #7c1322 is 1.86 on --bg. `.drawer-close` (both copies in topbar.html) and `.help-file-note` used --red-dim as the TEXT colour. Its other uses are borders, dividers and decorative markers, which I left alone.
- Fix: `static/style.css`: `--muted` is #8a8a96 (5.80 / 5.57 / 5.28), `.drawer-close` is `var(--red)` (5.01 on --panel), `.help-file-note` is `var(--muted)`.
- Regression test: `test_muted_text_meets_aa_on_every_surface` (HEAD 3.63 on --field), `test_the_drawer_close_and_help_notes_are_not_border_red`.
- Tests run: see the chunk header (test_mobile_css green).
- Skew / deploy order: dashboard only.
- OWED (parity, not this finding's scope):
  - broll, `broll/web/static/style.css:24` and `share_gone.html:18`: the same `#6f6f7a` muted text.
  - music-ytdl, `music/web/static/style.css:25`: the same `#6f6f7a` muted text.
  - Raise both to the dashboard's #8a8a96 if they want the same AA floor. Those SPAs inject the dashboard topbar, so the drawer's close is already fixed there.

## ui-dash-static-6 - the offline page's [ RETRY ] throws away the page the reader was trying to open
- Status: FIXED
- Verified as: sw.js answers a failed navigation with `caches.match(OFFLINE_URL)` in `respondWith`, so the document's URL is the one that failed. offline.html's retry was `href="/"`.
- Fix: `templates/offline.html`: the retry is `href=""` (the current document URL: the page that failed), still a plain link that works from the cache. An inline onclick sends a reader who is literally at /offline to "/", since reloading /offline would only paint this page again.
- Regression test: `test_the_offline_retry_reloads_the_page_that_failed` (HEAD href="/").
- Tests run: see the chunk header (test_pwa green).
- Skew / deploy order: dashboard only. The PRECACHED copy only changes when the version bump moves sw.js's cache name.
- OWED: none

## ui-dash-static-7 - the stale banner hides error toasts and the bottom of the page, and sits under the iPhone home indicator
- Status: FIXED
- Verified as: I read the stacking (banner z 60, toast host z 50, both bottom-fixed) and ran it in Chrome with the real htmx_errors.js. On HEAD the error toast's bottom was at 793 px under a banner starting at 747, and the page's last line was behind the banner. I also found that `.banner.alarm` (two classes) beat `.stale-banner`'s margin and padding (one class), so the banner floated 0.4rem off the edge, and any safe-area padding added to `.stale-banner` alone would have been overridden.
- Fix: `static/style.css`: the rule is `.banner.alarm.stale-banner`, which now outranks .banner.alarm, with `padding-bottom: calc(0.5rem + var(--safe-b, 0px))`. `body[data-stale]` gets `padding-bottom: var(--stale-h, 4rem)`, and `body[data-stale] .toast-host` sits `1rem + --stale-h` up at z 65. `static/htmx_errors.js`: `show()` writes the banner's measured height to `--stale-h` on body, because the reason wraps differently per screen, and `clear()` removes it.
- Regression test: `test_the_stale_banner_leaves_the_toasts_and_the_foot_readable` (Chrome; HEAD fails on both the toast and the last line), `test_the_stale_banner_clears_the_home_indicator` (safe-b present, and the selector outranks .banner.alarm).
- Tests run: see the chunk header (test_sweep_2026_09_04_dash_ui's `.stale-banner` pin green).
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-static-8 - [ COPY ] can stick on "[ COPIED ]" and gives no feedback when the clipboard API is absent
- Status: FIXED
- Verified as: read copy_value.js. `flash()` saved `btn.textContent`, so a second click inside 2 s saved "[ COPIED ]" as the idle label. The no-clipboard path only called `select(src)` and changed nothing on the button, and did nothing at all for a `data-copy-value` button, which has no src.
- Fix: `static/copy_value.js`: the idle label is stored once in `data-idle-label`, and any pending timer is cleared before a new flash. Without `navigator.clipboard`, or when writeText rejects, `document.execCommand("copy")` is tried on the selection (or on a scratch textarea for `data-copy-value`). If that works the button says [ COPIED ]. Otherwise it says "[ SELECTED - PRESS CTRL+C ]" with the value selected, or "[ COULD NOT COPY ]" when there is nothing to select.
- Regression test: `test_a_double_click_on_copy_goes_back_to_copy` (HEAD stays "[ COPIED ]"), `test_copy_without_a_clipboard_api_says_what_happened` (HEAD label unchanged).
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-static-9 - the AI provider pin and the CLI-provider checkbox keep showing a choice the server refused
- Status: FIXED
- Verified as: read site_settings.js. Both catches only printed the error, `renderAiProviders` (the only thing that resets the controls) ran only on success, and loadAiProviders' render clears the error line, so the finding's suggested fix alone would have erased the reason.
- Fix: `static/site_settings.js`: `renderAiProviders` records the server's pin in `pref.dataset.server`. On a refused PUT the select goes back to it and the checkbox is flipped back at once, then the new `aiRefused()` re-reads the providers and shows the refusal AFTER that redraw, so it is not wiped.
- Regression test: `test_a_refused_ai_pin_or_cli_flag_goes_back_to_what_is_in_force` (the real /admin/settings render plus site_settings.js in Chrome; HEAD keeps "openai_api" and the ticked box).
- Tests run: see the chunk header (test_ai_providers green).
- Skew / deploy order: dashboard only.
- OWED: none

## ui-copy-6 - The " -- " stand-in em dash is banned in templates but ships in dashboard Python copy
- Status: PARTIAL (rest OWED)
- Verified as: an AST scan of the package (docstrings, log calls and `execute()` SQL excluded) finds user-reachable " -- " literals. The seven in ui.py were confirmed by reading each: the login page's busy and https-only errors, the https-only HTTP detail, the Resolve-mapping refusal, the fleet-halt "say why" refusal, and the two /download 404 bodies. The companion's REASON_NO_IDENTITY cited by the hunter already reads "...token: sign in again from the tray" (`ytdl_executor.py:355`), so that part is ALREADY_FIXED.
- Fix: `dashboard/src/ccsync_dashboard/ui.py`: all seven now use a colon or two sentences. The first carries the finding id comment. Tests that pin a substring ("busy checking sign-ins", "say why") still match.
- Regression test: `test_ui_py_copy_has_no_typewriter_em_dash` (AST scan of ui.py; HEAD has 7), `test_the_busy_login_says_it_without_the_banned_dash`.
- Tests run: see the chunk header (test_hardening and test_fleet_halt green).
- Skew / deploy order: dashboard only.
- OWED (each group: read each hit, change the ones a browser, toast, alert mail or HTTP `detail` shows to a colon or two sentences, and leave SQL, internal and log strings alone; line numbers are from the scan on 2026-09-25):
  - d-api, `api.py`: 24 hits, at 781, 2051, 2171, 2176, 2205, 2425, 2488, 3462, 3571, 3695, 3711, 3718, 3739, 3763, 3801, 4262, 6508, 6516, 6524, 6541, 6607, 6769, 6899 and 10439.
  - d-ops:
    - `dashboard_update.py`: 711, 723, 764-772, 799-840, 930, 1411, 1563.
    - `release_feed.py`: 186, 250, 283, 327, 339, 385, 762, 1315, 1338, 1378.
    - `ai_providers.py`: 257, 262, 271, 641, 985, 990, 1011, 1059.
    - `nas/synology.py` (13 hits), `nas/truenas.py` (7), `nas/factory.py:69`, `package_store.py:443`, `runtime_id.py:101`.
  - d-auth:
    - `setup_engine.py`: 619, 738, 742, 751, 756, 864.
    - `app.py:1100`, `oidc.py` (252, 460, 464), `sessions.py:93`, `setup_routes.py:191`, `site_store.py:899`.
  - d-cards: `cards.py` (95, 99, 678, 687), `cards_ai.py:118`, `cards_tunnel.py:196`.
  - d-diag: `notices.py:1467`.
  - d-db: `db.py` (47, 131, 268, 472, 499, 517, 775, 817). Most of these are probably schema comments inside SQL strings; check them.
  - Once every group is done, whoever owns `tests/test_sweep_2026_09_04_copy.py` (d-ui, next round) can widen DUI-14's check from templates to the package, reusing this chunk's `_typewriter_dashes` helper.

## ui-copy-7 - "Sign in" everywhere except the topbar's [ LOGIN ] / [ LOGOUT ] / [ LOGOUT ALL ]
- Status: FIXED
- Verified as: grep. topbar.html's bar and drawer foot said [ LOGOUT ], [ LOGOUT ALL ] and [ LOGIN ], and the login form's submit said [ LOGIN ] under a [ SIGN IN ] heading. The own-row and other-row confirms in topbar.html and admin_sessions.html said "log in again" after "Sign yourself out". Every other surface says sign in / sign out. No SPA matches the topbar by those labels (grep of broll/music/ytdl static).
- Fix: `templates/partials/topbar.html`: [ SIGN OUT ], [ SIGN OUT EVERYWHERE ], [ SIGN IN ], and the confirm says "sign in again". `templates/partials/admin_sessions.html`: both confirms say "sign in again". `templates/login.html`: the submit is [ SIGN IN ] and the tab title is "...: SIGN IN".
- Regression test: `test_the_topbar_says_sign_in_and_sign_out` (topbar partial and the anonymous /login page; HEAD has LOGOUT / LOGIN), `test_the_sessions_confirms_say_sign_in_again`.
- Tests run: see the chunk header.
- Skew / deploy order: dashboard only. The b-roll, music and ytdl SPAs pick up the new labels from /partials/topbar with no change of their own.
- OWED: d-auth (or whoever owns `dashboard/README.md`), `dashboard/README.md:105-106`: the doc names `[ LOGOUT ]` and `[ LOGOUT ALL ]`; they are `[ SIGN OUT ]` and `[ SIGN OUT EVERYWHERE ]` now.


# Owed round (builder d-ui, 2026-09-25)

Items other groups left for d-ui's files. The new tests are appended to
`dashboard/tests/test_bug_hunt_2026_09_24_w2_d-ui.py`, under "OWED round".

**Baseline check.** I ran `git archive HEAD dashboard` into the scratchpad,
copied the test file in, and ran the owed tests there with the dashboard venv.
18 of the 20 fail on HEAD. The other two are controls: the view with no
`uncertain` key, and a [ SET ] with no sessions.

**Tests run.** Command: `dashboard\.venv\Scripts\python.exe -m pytest`. Files:
- the d-ui file and test_recovery
- test_admin_users (plus _local and _partial_parity)
- test_bug_hunt_2026_09_11(b)_dash_mounts_ui and test_hand_off_2026_09_11b_dash_mounts_ui
- test_cr312_transfer_names_wrap and test_fleet_grid_declutter_2026_09_11
- test_mobile_admin, test_mobile_css and test_mobile_fleet
- test_sweep_2026_09_04_copy and test_templates_wave3_2026_09_04
- the w2 d-diag, d-db and d-api files
- test_local_users, test_sessions, test_health and test_multi_machine

Result: 997 passed, 1 skipped, 3 failed.
- **Expected:** d-diag's
  `test_the_resolve_undo_step_claims_no_dashboard_button_that_does_not_exist`.
  - Its premise, "no template calls resolve-undo", stopped being true when the button landed.
  - d-diag's ledger names this as the test to change when the button lands. I edited only its premise block, which now pins where the button is.
  - After the edit that file ran 61/61.
- **Not mine:** `test_no_retired_word_in_python_copy[jobs.py]`. It fails on jobs.py:120 ("machine"), which is d-cards' file.
- **Not mine:** the CR-335 Packages hx-indicator count, already recorded above.

**Skew / deploy order for the whole round:** dashboard only.
- What changed: templates, copy in ui.py, one new partial route (`POST /partials/admin/recovery/resolve-undo`) and one call to d-api's revoke helper.
- No wire key and no schema change.
- The Resolve undo button reaches only companions that already carry `commands.resolve_undo` (v40, SYS-15b). Older companions never get the command. Their request row just says "waiting for that computer to report".

## logic-sync-truth-2 (from c-sync) - "Safe to close" over an originals-capped manifest; transfers.html:78 wording
- Status: FIXED (the d-ui half). It works end to end only once d-api changes one filter (OWED below).
- Verified as:
  - `safe_to_close` counted only up rows that list files. When the ORIGINALS list is capped, the listed diff is empty, no up row exists, and the page said "Safe to close".
  - This round, d-db added `_original_manifest_capped`. It now keeps such a row, flagged `uncertain`, even at `n_files` 0 (db.py ~9969-10022).
  - `api.build_transfers_view` still drops every queue with `n_files == 0` (api.py:681). So a zero-file `uncertain` row never reaches the UI.
- Fix, in `ui.py safe_to_close`:
  - An up queue flagged `uncertain` is never safe.
  - With no counted uploads it says: "Cannot tell yet: <machine> (<project>) holds more video originals than it can list to the dashboard, so some may not have uploaded. Leave it running and check its tray."
  - With counted uploads it adds: "There may be more: <machine> (<project>) ...".
  - The key is optional. A view without it reads as before.
- Fix, in `templates/partials/transfers.html` (the capped line is now worded by direction):
  - Up row flagged `uncertain`, or an older row with only `manifest_truncated`: "(this computer has more video originals than it can list to the dashboard, so the upload count may be low)".
  - Down row whose proxy list was capped (d-db's contract is `files == []`): "(this computer's proxy list was capped, so the count is worked out from its totals and no file names are shown)".
  - Down row that still lists names: only the originals side was capped, so the count is exact and there is no note.
  - Zero-file `uncertain` row: "none counted, but this computer could not list every original: some may still need to upload".
  - "... and N more" shows only when names were listed.
- Regression tests:
  - `test_an_originals_capped_machine_is_never_safe_to_close` (HEAD: safe True).
  - `test_a_counted_upload_on_a_capped_machine_says_there_may_be_more`.
  - `test_the_capped_manifest_line_is_worded_by_direction` (HEAD: one "totals may undercount" line for all three rows).
  - Control: `test_a_view_without_the_uncertain_key_reads_as_before`.
- Tests run: see the round header.
- Skew / deploy order: dashboard only.
- OWED: d-api, `dashboard/src/ccsync_dashboard/api.py:681` (`build_transfers_view`).
  - Change: keep `uncertain` rows through the zero-file filter: `if q["n_files"] > 0 or q.get("uncertain")`.
  - Why: until then the zero-file case, which is the one this finding is about, still reads "Safe to close" on the live page.
  - Side effects: `queued_files` and `queued_bytes` are unaffected, because the row carries 0.

## bug-dash-db-2 (from d-db) - transfers.html:78 worded per direction
- Status: FIXED. It is the same template change as logic-sync-truth-2 above.
- Verified as: the one line "manifest was capped; totals may undercount" was wrong for a capped proxy list. There the count is a rollup lower bound and no names are shown.
- Fix: `templates/partials/transfers.html`, as described above.
- Regression test: `test_the_capped_manifest_line_is_worded_by_direction`.
- Tests run: see the round header.
- Skew / deploy order: dashboard only.
- OWED: none

## logic-sync-truth-4 (from c-sync) - CHIP_HELP["disk"] said the trash cannot prune while proxy download is stopped
- Status: FIXED
- Verified as:
  - I read `lane_guard.DiskFloor`: `clear_free_bytes = min_free_bytes * DISK_FLOOR_CLEAR_MULTIPLE`, and the multiple is 2.0.
  - I read `RcloneLane._prune_free_target`: while the lane is parked, the prune works toward the clear threshold, and reaching it releases the park.
  - The lane B breaker is the one state that holds proxy download regardless of free space.
- Fix: `ui.py` CHIP_HELP["disk"] now reads: "... When the drive drops below its floor, proxy download stops and .ccsync-trash is emptied oldest first until the drive has twice the floor free, which starts proxy download again. The exception is a proxy download the safety breaker has stopped: that one waits for somebody to resume it, from that computer's tray or by an admin with [ RESUME ] on this row." No em dash. [ RESUME ] is on the fleet grid row (admin only, fleet_grid.html:448).
- Regression test: `test_the_disk_chip_no_longer_says_the_trash_cannot_prune` (HEAD has "cannot prune").
- Tests run: see the round header.
- Skew / deploy order: dashboard only. The copy describes companion 0.9.78+ (c-sync chunk 1). A 0.9.77 machine does not clear the park by itself, so for those machines the chip promises more than happens until the companion ships.
- OWED: none

## ui-copy-5 (from c-ui) - fleet_grid.html hand-wrote a third route to Copy diagnostics
- Status: FIXED
- Verified as: fleet_grid.html:477 said "Settings, then Help, then Copy diagnostics". `COMPANION_DIAGNOSTICS_PATH` is already a template global (ui.py:287). d-diag has set it to "Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN".
- Fix: `templates/partials/fleet_grid.html` empty-fleet line: "ask that editor to open {{ COMPANION_DIAGNOSTICS_PATH }} and send you what it copies." A comment cites the finding.
- Regression test: `test_the_empty_fleet_names_the_one_diagnostics_route` (real GET /; compares against the HTML-escaped path).
- Tests run: see the round header.
- Skew / deploy order: dashboard only.
- OWED: none

## bug-dash-api-4 (from d-api) - the Users page [ SET ] left the account's sessions signed in
- Status: FIXED
- Verified as: `partial_admin_set_password` committed the new hash (local mode) or called `nas.set_known_password` (smb mode). It did nothing to sessions. d-api's `revoke_sessions_after_password_reset` exists and never raises.
- Fix, in `ui.py`:
  - `admin = _require_admin_page(request)` is kept.
  - After a successful change, in both branches, it calls `api_revoke_sessions_after_password_reset(request, username, admin=admin)`.
  - When N > 0 the notice reads: "Password set for X, and signed out N session(s) of theirs. Tell them the new password: it is not shown here again." It says "session" when N is 1.
  - When N == 0 the notice is unchanged.
  - When admins reset their own password, the helper keeps their current tab signed in.
- Regression tests: `test_the_users_page_set_button_signs_the_account_out` (HEAD: the leaked-password session still validates). Control: `test_a_set_with_no_sessions_keeps_the_plain_notice`.
- Tests run: see the round header. test_admin_users, test_admin_users_local and test_admin_users_partial_parity are green.
- Skew / deploy order: dashboard only.
- OWED: none

## bug-dash-diag-3 (from d-diag) - recovery copy said the restore goes inside the project
- Status: FIXED
- Verified as: recovery.py now writes `<tree>/.restored-<ts>/<label>/`. Two template texts still said "inside that project":
  - `partials/recovery.html`
  - the page intro in `admin_recovery.html`, which the owed item did not list; I found it in the screenshot.
- Fix:
  - `partials/recovery.html`, the paragraph under [ PUT A PROJECT'S FILES BACK ]: "copied into a new folder called .restored-<date> at the top of the Projects folder on the server, under the project's own name. It is not sent to any editor's computer."
  - `admin_recovery.html` intro: "a new folder at the top of the Projects folder on the server".
  - The docstring of `ui.py partial_admin_recovery_restore` now names `<tree>/.restored-<ts>/<project>/`.
- Regression tests: `test_the_restore_paragraph_says_where_the_copy_goes` (covers both templates) and `test_the_restore_route_docstring_names_the_tree_not_the_project`.
- Tests run: see the round header.
- Skew / deploy order: dashboard only.
- OWED: d-api, `api.py` ~10681, docstring of `api_recovery_restore`: change `<project>/.restored-<ts>/` to `<tree>/.restored-<ts>/<project>/`. Comment only; d-diag's ledger already notes it.

## logic-admin-4 (from d-diag) - the restore result line did not say where the folder is
- Status: FIXED
- Verified as: the result line read only "Restored N file(s) into .restored-<ts>/<label>."
- Fix: the result block in `partials/recovery.html` now adds: "..., at the top of the Projects folder on the server. A name that starts with a dot may be hidden in Explorer or Finder until hidden items are shown."
- Regression test: `test_the_restore_result_says_where_and_that_a_dot_name_may_hide`.
- Tests run: see the round header.
- Skew / deploy order: dashboard only.
- OWED: none

## logic-admin-5 / ui-dash-admin-13 (from d-diag) - a changed-only restore defaulted to a refused request, and the confirm quoted missing_count alone
- Status: FIXED. One change covers both findings.
- Verified as: the form showed whenever `missing_count or changed_count` was non-zero, but the box was unticked and the confirm said "Copy {{ missing_count }} file(s)". So a preview with only changed files asked "Copy 0 file(s)?", and the server then refused the request.
- Fix, in `partials/recovery.html`:
  - When `missing_count == 0`, the `include_changed` box renders `checked`.
  - Changed files only: "Copy the N file(s) that are there but different into a new folder? Nothing there now changes."
  - Both counts: "Copy M missing file(s), and the N different one(s) if the box is ticked, into a new folder? ..."
  - Missing files only: "Copy M missing file(s) into a new folder? ..."
  - No em dash. test_mobile_admin's long-confirm check is still green.
- Regression tests: `test_a_changed_only_restore_starts_ticked_and_counts_what_it_copies` (HEAD: unticked box and "Copy 0 file(s)") and `test_a_mixed_restore_confirm_names_both_counts_and_stays_unticked`.
- Tests run: see the round header.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-copy-2 (from d-diag) - the collector anchor, and a dashboard control for the Resolve undo
- Status: FIXED. Switching the recovery step back to an action is OWED to d-diag.
- Verified as:
  - d-db's registry now links `/#fleet-collector` (db.py 3399-3563), but no element had that id.
  - For the undo, only the two API routes existed. Nothing in templates or static called them.
- Fix, the anchor: the [ COLLECTOR ] side-head in `partials/collector_health.html` now has `id="fleet-collector"`. It renders once on `/`.
- Fix, the Resolve undo panel: it is on the recovery page's Resolve answer (`/admin/recovery?problem=resolve`, anchor `#resolve-undo`, heading "[ UNDO A CLIP-PATH CHANGE ]").
  - `ui._resolve_undo_view` lists every machine that has reported journals (`machine_state.resolve_journals`) or has undo requests.
  - Each journal row shows when, the project, the clip count, and [ UNDO THIS CHANGE ]. The button's hx-confirm names the clip count, the project and the computer.
  - A journal with an unanswered request shows [ UNDO ASKED ] instead of the button.
  - The last 5 requests are listed with `api._undo_state_sentence`.
- Fix, the new route `POST /partials/admin/recovery/resolve-undo`:
  - It checks the admin gate, then calls the JSON route's own function, `api.api_machine_resolve_undo`, so the button is never a softer door than the API.
  - That function 404s an unknown journal or machine and audits the ask.
  - A refusal renders as the error banner.
- Why the recovery page and not a new per-machine page: the "CC Sync changed clip paths" answer already sends the owner there, and it needs no api.py change.
- Visual check: headless Chrome at 1280, and inside a 390 px iframe. On the phone the rows stack and nothing scrolls sideways (scratchpad rec1280.png, rec390ru.png).
- Regression tests (all fail on HEAD):
  - `test_the_collector_panel_is_the_anchor_the_notices_link_to`
  - `test_the_fleet_page_renders_the_collector_anchor_once`
  - `test_the_resolve_answer_lists_each_computers_changes_with_an_undo`
  - `test_undo_this_change_asks_that_computer_and_shows_it_asked`: the request row is written, `requested_by` is the admin, and the row flips to [ UNDO ASKED ].
  - `test_undoing_a_change_the_computer_never_reported_is_refused`
  - `test_an_editor_cannot_press_undo_this_change`
  - `test_with_no_journals_the_resolve_answer_points_at_the_tray`
- Tests run: see the round header. d-diag's premise test was edited as described there.
- Skew / deploy order: dashboard only. Companions from before SYS-15b (v40) never report journals, so they never appear in the list.
- OWED: d-diag, `dashboard/src/ccsync_dashboard/recovery.py` `_plan_resolve`.
  - The problem: its first step still says "The dashboard has no button for this yet". That is now false, and it shows on the same page right above the new panel (visible in the 1280 screenshot).
  - Change it to an `action` step, "Undo it from here", with href `#resolve-undo` (the panel is on the same page) or `/admin/recovery?problem=resolve#resolve-undo`.
  - The body should say: pick the computer and the change under [ UNDO A CLIP-PATH CHANGE ] and press [ UNDO THIS CHANGE ]. It runs when that computer next reports, while that project is open in its Resolve. [ UNDO LAST FIX ] in the tray's Settings (RESOLVE section) does the same at the computer.
  - Then update `test_the_resolve_undo_step_claims_no_dashboard_button_that_does_not_exist` in `tests/test_bug_hunt_2026_09_24_w2_d-diag.py`. Its template premise already pins the button.

## ui-copy-6 (from d-ui) - widen DUI-14's typewriter-dash check from templates to the Python package
- Status: DEFERRED
- Verified as:
  - I ran the `_typewriter_dashes` scan over `dashboard/src/ccsync_dashboard` during this round: 93 hits.
  - The groups that own them (d-api 24, d-ops about 50, d-auth, d-cards, d-diag) are running their owed rounds at the same time as this one. Widening now would add a test that is red by construction and fail the central gate on other groups' files.
  - Some hits are not copy and need an exemption: the SQL schema strings in db.py, sessions.py:93 and db.py:7781; the setup probe file body at setup_engine.py:758; the embedded script at dashboard_update.py:840.
- Fix: none this round.
- Regression test: n/a
- Tests run: the scan only (scratch script).
- Skew / deploy order: n/a
- OWED: d-ui, next round, after every group's ui-copy-6 row has landed. File: `dashboard/tests/test_sweep_2026_09_04_copy.py`.
  - Add a package-wide test that reuses `_typewriter_dashes` from `test_bug_hunt_2026_09_24_w2_d-ui.py`.
  - Exempt constants passed to `execute`/`executescript`.
  - Exempt strings that start with `\nCREATE`, `\nALTER` or `INSERT`.
  - Add a short named allowlist: the probe body in `setup_engine.py` and the embedded checker script in `dashboard_update.py`.
  - Rerun the scan first. Expect zero hits outside the exemptions.

## Review round (2026-09-25): the adversarial reviewer's four problems on the owed chunk

### logic-sync-truth-2: Review round
- Reviewer: right.
  - The d-ui half is correct. But `api.build_transfers_view` (api.py:681) still drops the zero-file `uncertain` row, so in scenario (b) the live page still says "Safe to close".
  - My three tests built the view by hand and never went through that filter.
- Checked end to end:
  - Seeded `editor_media_project` with `truncated=1`: 2,500 originals held, 2,000 listed, every listed one on the NAS, nothing owed.
  - `db.fetch_sync_backlog` returns the `uncertain` row, and `build_transfers_view` drops it.
  - GET `/partials/queue`, signed in as the editor, renders "Safe to close: nothing is transferring."
- Checked that the reviewer's one line is enough:
  - I made a scratch copy of `dashboard/` (src, templates and tests; the conftest pins `src` to its own tree).
  - With only `or q.get("uncertain")` added at api.py:681, both end-to-end tests pass. Nothing else in the path drops the row.
- The line is still not mine to add: api.py belongs to d-api, so it stays OWED.
- New tests in `test_bug_hunt_2026_09_24_w2_d-ui.py`:
  - `test_the_db_keeps_the_capped_row_the_page_needs`: the premise (d-db's half). Passes.
  - `test_an_originals_capped_machine_is_not_safe_to_close_through_the_real_view`: the real `build_transfers_view`, then `safe_to_close`.
  - `test_the_editors_queue_panel_does_not_say_safe_to_close_over_a_capped_list`: a real GET `/partials/queue` as the editor, plus `/partials/transfers` for the "none counted" line.
- The two end-to-end tests are `xfail(strict=True)`, with the OWED item as the reason.
  - Today they fail, for the reason the reviewer gave.
  - Once d-api's line lands they XPASS, and strict turns that into a failure. That failure is the signal to delete the marker, so they cannot rot as expected failures.
- OWED (unchanged, restated): d-api, `dashboard/src/ccsync_dashboard/api.py:681`.
  - Make it `queues = [q for q in queues if q["n_files"] > 0 or q.get("uncertain")]`.
  - Then remove the two `xfail` markers in `test_bug_hunt_2026_09_24_w2_d-ui.py`.

### logic-sync-truth-4: Review round
- Reviewer: right.
  - Pruning up to twice the floor (`_prune_free_target`) is bug-comp-rclone-3. It is new in this wave and ships in the release after 0.9.78.
  - Every companion in the field (0.9.77 and 0.9.78) stops the prune at 1x the floor.
- What those older companions actually do:
  - `DiskFloorLatch` still clears itself at 2x (lane_guard.py docstring; the same at HEAD).
  - So the park lifts once free space reaches twice the floor by some other means, or when somebody presses [ RESUME ].
- One correction to the reviewer: the row's [ RESUME ] does not appear for a free-space park.
  - fleet_grid.html:448 draws that button only for `breaker_tripped`.
  - `app.resume_lane_b` does clear both latches, but for a free-space park alone the button that works is the tray's.
- Fix: `ui.py` CHIP_HELP["disk"] is now worded by version.
  - Newer: "On CC Sync newer than 0.9.78 it is emptied until the drive has twice the floor free, which starts proxy download again."
  - Older: "On 0.9.78 or older it stops emptying at the floor, so proxy download starts again only once somebody frees space up to twice the floor, or presses [ RESUME ] in that computer's tray."
  - The breaker exception is unchanged.
- Why not read the machine's reported version: the next release number is not assigned until the ship. A test against a number that does not exist yet would be wrong in both directions.
- Regression test: `test_the_disk_chip_no_longer_says_the_trash_cannot_prune`.
  - Now also asserts both version sentences and the tray's [ RESUME ].
  - Asserts that the first cut's unconditional sentence is gone.
  - It fails on the first cut.
- OWED: none.
  - Optional: once the release carrying bug-comp-rclone-3 has its number, the chip can name it instead of "newer than 0.9.78". The current wording stays true either way.

### bug-dash-api-4: Review round
- Reviewer: right.
  - In SMB mode, [ CREATE NEW EDITOR ACCOUNT ] is create-or-update.
  - Given an existing username, a key and a password, `_create_or_update_editor_sync` calls `nas.set_known_password` and revokes no sessions. That is a password reset by another door.
  - Local mode is safe: `local_users.create_user` refuses a name that already exists.
- Fix, in `ui.py partial_admin_create_user` (SMB branch):
  - After a successful create, when a password was given, it calls `api_revoke_sessions_after_password_reset(request, username, admin=admin)`.
  - The call is unconditional in that case. A brand-new account has no sessions, so it answers 0.
  - Through the helper, it keeps the admin's own tab and never raises.
  - When N > 0 the panel shows "Password set for X, and signed out N session(s) of theirs." The route now passes `notice`.
- Regression tests:
  - `test_the_create_form_resetting_an_existing_password_signs_the_account_out`: fake NAS, real session store, real POST. Before the fix, the leaked session still validated.
  - Control: `test_the_create_form_without_a_password_signs_nobody_out`.
- OWED: d-api, `dashboard/src/ccsync_dashboard/api.py` ~4455-4458.
  - The JSON twin of the create route has the same gap.
  - After a successful create-or-update that set a password, call `revoke_sessions_after_password_reset(request, username, admin=admin)`, as the [ SET ] JSON route already does.

### ui-copy-2: Review round
- (1) The contradiction. Reviewer: right.
  - `recovery._plan_resolve` still says "The dashboard has no button for this yet". It is drawn right above the new panel.
  - recovery.py belongs to d-diag, so this stays OWED. It is not in the working tree as of this round.
- (2) The brief. Reviewer: right. Editing d-diag's test file in the owed round broke rule 2.
  - This round the premise block of `test_the_resolve_undo_step_claims_no_dashboard_button_that_does_not_exist` is back to d-diag's documented premise: no template or static file contains `resolve-undo`, `resolve-journals` or `UNDO THIS CHANGE`. That is the grep in d-diag's ledger, line 142.
  - I rebuilt it from that description because the original text was not preserved.
  - The test now FAILS on `partials/recovery.html` 'resolve-undo'. That is correct: its premise is false now the button exists, and it is the test d-diag's own ledger names as the one to change when the button lands.
- (3) `asked`. Reviewer: right.
  - It came from `resolve_undos_for_machine(limit=5)`. An open ask with five or more newer requests above it dropped out of the set, and its journal offered [ UNDO THIS CHANGE ] again.
  - Fix: `ui._resolve_undo_view` now builds `asked` from every row with `applied_at IS NULL` for that (editor, machine), the key the request is stored under.
  - Not `pending_resolve_undos`: that one caps at RESOLVE_UNDO_COMMAND_LIMIT and widens to former hostnames. Those are delivery concerns, not what the panel draws.
  - The five-row history is unchanged.
- Regression test: `test_an_old_unanswered_undo_stays_asked_under_five_newer_requests`.
  - Seeds one old open ask and six newer ones.
  - Asserts `asked` is True, and that the page shows [ UNDO ASKED ] and no [ UNDO THIS CHANGE ].
  - It fails on the first cut.
- OWED:
  - d-diag, `recovery.py _plan_resolve`: as recorded above.
  - d-diag, `tests/test_bug_hunt_2026_09_24_w2_d-diag.py::test_the_resolve_undo_step_claims_no_dashboard_button_that_does_not_exist`:
    - Change the premise to pin the button: `partials/recovery.html` carries `id="resolve-undo"` and "[ UNDO THIS CHANGE ]".
    - Assert the step is an `action` linking `#resolve-undo`.

### Tests run (review round)
- `dashboard\.venv\Scripts\python.exe -m pytest -p no:cacheprovider` over:
  - the w2 d-ui and d-diag files
  - test_admin_users, plus its _local and _partial_parity variants
  - test_recovery, test_fleet_grid_declutter_2026_09_11 and test_sweep_2026_09_04_copy
- Result: 551 passed, 1 skipped, 2 xfailed (the strict ones above), 2 failed.
  - Expected failure: d-diag's `test_the_resolve_undo_step_claims_no_dashboard_button_that_does_not_exist`, restored and OWED to d-diag.
  - Not mine: `test_no_retired_word_in_python_copy[jobs.py]` (d-cards' file).
- test_templates_wave3_2026_09_04 + test_mobile_admin: 99 passed, 1 failed. The failure is the CR-335 Packages hx-indicator count, already recorded as not mine.
- The xfail tests were also run in a scratch copy with d-api's line applied: both XPASS.
- Skew / deploy order: dashboard only. No wire key, no schema change.

# Owed round 2 (builder d-ui, 2026-09-25)

New tests are appended to `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-ui.py` under "Owed round 2".

**Baseline check.** I ran `git archive HEAD dashboard` into the scratchpad, copied the test file in, and ran the new tests there. Three of the five fail on HEAD: the zero-file row, the counted-row caveat, and the package scan. The other two are controls: a GETTING READY row, and the scan's self-test on a fake module.

**Tests run.** Command: `dashboard\.venv\Scripts\python.exe -m pytest -p no:cacheprovider`. Files: the w2 d-ui file, test_mobile_css, test_cr312_transfer_names_wrap, test_cr311_queue_says_on_hold, test_mobile_fleet, test_sweep_2026_09_04_copy, test_auth, test_home_layout, test_presence, test_settings_hub, test_templates_wave3_2026_09_04 and test_fleet_grid_declutter_2026_09_11.
- Result: every test passes except two failures that belong to other groups.
  - `test_no_retired_word_in_python_copy[jobs.py]` fails on d-cards' file.
  - The CR-335 Packages hx-indicator count, already recorded above.
- The d-ui file ran 96 passed, 2 xfailed.

**Skew / deploy order:** dashboard only. The change is in templates, one CSS rule and tests. There is no wire key and no schema change.

## bug-dash-db-2 / logic-sync-truth-2 (from d-db) - a zero-file `uncertain` up row read "0 files · 0 B upload"
- Status: FIXED
- Verified as:
  - The first owed round kept "0 files · 0 B" and the "upload" chip on the row, and only added a "none counted" note after them.
  - The [ QUEUED ] header also said "0 files · 0 B waiting" when that row was the only one in the queue.
- Fix, in `templates/partials/transfers.html`:
  - An up row with `uncertain` and `n_files` 0 now has its own branch: the ⇡ arrow, an amber `[ CANNOT TELL ]` chip, and the sentence "this computer's file list was capped: it holds more video originals than it can list to the dashboard, so the dashboard cannot tell whether it still owes uploads. Leave it running and check its tray."
  - The row shows no count and no "upload" chip.
  - When nothing is counted, the header says "nothing counted yet, but the rows below are not finished: see each one", not "0 files · 0 B waiting".
  - The "(... so the upload count may be low)" caveat now shows only on a capped row that did count files.
- Fix, in `static/style.css`: a new `.queue-note` rule lets the sentence wrap.
  - The row's summary is `.mono-sm`, which does not wrap. Without the rule the sentence pushed the 1280 px page sideways.
  - Checked in headless Chrome at 1280 px and in a 390 px iframe (scratchpad `tr1280.png`, `tr390.png`). Nothing scrolls sideways at either width.
- Regression tests:
  - `test_a_zero_file_capped_upload_row_is_a_sentence_not_zero_files`. It fails on HEAD, which rendered "0 files · 0 B" and the upload chip.
  - `test_a_capped_row_that_counted_files_still_shows_its_count`.
  - Control: `test_a_zero_file_row_that_is_not_capped_keeps_its_old_shape`.
- Changes to my own earlier tests, because the behaviour changed:
  - `test_the_capped_manifest_line_is_worded_by_direction` now uses a capped row that counted 3 files. The caveat is on that row now.
  - The strict-xfail end-to-end test now asserts the new sentence, not "none counted".
- Tests run: see the round header.
- Skew / deploy order: dashboard only.
- OWED: d-api, `api.py:681`. This is unchanged from the owed round.
  - As of this round the working tree still has `if q["n_files"] > 0`. So on the live page the zero-file row is still dropped before this template can draw it.
  - When d-api's line lands, the two `xfail(strict=True)` tests in the d-ui file XPASS. Strict turns that into a failure. Whoever gates next should delete the two markers.

## ui-copy-2 (from d-diag) - `id="fleet-collector"` on the [ COLLECTOR ] side-head
- Status: ALREADY_FIXED (d-ui's first owed round; not committed yet)
- Verified as:
  - The [ COLLECTOR ] side-head is not in `fleet_grid.html` itself. It is in `templates/partials/collector_health.html`, which `fleet_grid.html:528` includes.
  - That side-head already carries the anchor: `<div class="side-head" id="fleet-collector" ...>[ COLLECTOR ]` (collector_health.html:17). A grep of `fleet_grid.html` alone does not find it, which is probably why the item came back.
  - The existing tests cover it, and both pass this round:
    - `test_the_collector_panel_is_the_anchor_the_notices_link_to`
    - `test_the_fleet_page_renders_the_collector_anchor_once`: a real GET `/`, which finds the id exactly once.
- Fix: none needed.
- OWED: none.

## ui-copy-6 (from d-ui) - package-wide typewriter-dash scan
- Status: FIXED
- Verified as: I reran `_typewriter_dashes` over `dashboard/src/ccsync_dashboard` after the other groups' rows landed. 13 hits remain, down from 93, and none is visible copy:
  - Nine are SQL schema or INSERT strings (db.py ×9, sessions.py ×1).
  - The setup probe file body (setup_engine.py:758).
  - The stage-verify script source (dashboard_update.py:840).
  - `cards_ai.JSON_REPLY_NOTE` (cards_ai.py:118). This is an instruction to the model that no person sees. The earlier ledger did not name it.
- Fix: new tests in the d-ui file, not in `test_sweep_2026_09_04_copy.py` (brief rule 1).
  - `test_no_typewriter_em_dash_in_any_dashboard_python_copy` scans every module in the package with `_typewriter_dashes`.
  - It exempts every string constant inside an `execute`, `executescript` or `executemany` call.
  - It exempts strings whose first word is a SQL keyword (CREATE, ALTER, INSERT, UPDATE, DELETE, SELECT, WITH).
  - It keeps a named three-entry allowlist, keyed by module and how the string starts: the setup probe body, the stage-verify source, and the cards_ai model prompt.
- Regression tests:
  - `test_no_typewriter_em_dash_in_any_dashboard_python_copy`. It fails on HEAD (93 hits).
  - `test_the_package_scan_still_catches_a_dash_in_copy`: a fake module with a SQL comment, an `execute("... -- ...")` and an HTTP detail containing " -- ". Only the detail is reported.
- Tests run: see the round header.
- Skew / deploy order: n/a (tests only).
- OWED: none.

## Also this round: two of my Resolve undo tests re-aimed at the button
- Why: d-diag's `_plan_resolve` step now names "[ UNDO THIS CHANGE ]" in its prose, on the same page as the button.
- Two tests broke on that prose, not on the behaviour they check: `test_undo_this_change_asks_that_computer_and_shows_it_asked` and `test_an_old_unanswered_undo_stays_asked_under_five_newer_requests`.
- Both now assert `">[ UNDO THIS CHANGE ]</button>" not in html`, so they check for the button, not the words.


# Owed round 3 (builder d-ui, 2026-09-25)

## bug-dash-db-2 (round 3) - the capped zero-file upload row dropped its [ ON HOLD ] chip
- Status: FIXED
- Verified as: api.py sets `q["held"]` (CR-311, `health.queue_hold`) on every non-pending queue row that has a machine, including the `uncertain` zero-file row. The round-2 branch `{% elif q.direction == "up" and q.uncertain and not q.n_files %}` rendered only [ CANNOT TELL ] and "Leave it running and check its tray." A machine whose drive was unplugged (or that was halted, or signed out) lost its hold chip and got advice that was wrong for it.
- Fix: `dashboard/templates/partials/transfers.html`, in that branch: "Leave it running and check its tray." appears only when `not q.held`. The `{% if q.held %}` [ ON HOLD ] chip, its reason sentence and "(since ...)" render exactly as in the ordinary branch.
- Regression test: `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-ui.py::test_a_held_zero_file_capped_row_shows_the_hold_not_leave_it_running` fails on round 2's template, which has no [ ON HOLD ] and still gives the "leave it running" advice. Also `::test_an_unheld_zero_file_capped_row_still_says_check_its_tray`.
- Tests run: `dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_d-ui.py tests/test_cr311_queue_says_on_hold.py -q` -> pass. Rendered through the Jinja env in the tests. There is no layout change (it reuses the ordinary branch's chip markup), so no screenshot was taken.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-copy-6 (round 3) - the package-wide " -- " scan exempted English copy that starts like SQL
- Status: FIXED
- Verified as: `_package_typewriter_dashes` exempted any value whose `lstrip().upper()` started with CREATE/ALTER/INSERT/UPDATE/DELETE/SELECT/WITH, so "Update the dashboard -- now", "Delete ...", "With ..." and "selected ..." passed. `_sql_constant_values` also exempted every string constant anywhere inside an execute call (parameter tuples included) and, matching by value, any equal string anywhere in the module.
- Fix: test file only. `_SQL_HEAD_RE = re.compile(r"\s*(CREATE|ALTER|INSERT|UPDATE|DELETE|SELECT|WITH)\s")` is case-sensitive. `_sql_statement_constants` returns `(line, value)` only for constants inside the FIRST positional argument of execute/executescript/executemany, matched by line and value rather than value alone.
- Regression test: `::test_the_sql_exemption_does_not_swallow_english_copy` uses a fake module with `detail="Update the dashboard -- now"`, "Delete it -- first", "With care -- please", "select one -- here", "SELECTED -- nothing" and an execute parameter "note -- param". Every one must be reported and the two statements must not. It fails on the old scanner, which exempted the first four and the parameter.
- Tests run: the whole d-ui file, 101 passed. The tightened package scan (`test_no_typewriter_em_dash_in_any_dashboard_python_copy`) finds no real hit in dashboard copy, so no module needed a change.
- Skew / deploy order: none (test only).
- OWED: none
