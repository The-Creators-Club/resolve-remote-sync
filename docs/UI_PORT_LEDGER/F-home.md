# F-home: the home and project findings of the UI port review

Fix builder F-home, 2026-09-25. Scope: every `home-project-*` finding in
`docs/UI_PORT_REVIEW_2026-09-25.md`, in the terminal-look files and the server
code they needed. No classic template touched, nothing committed, no version
bumped.

Tests: `dashboard/tests/test_cc_home_review_fixes.py` (19 tests). They run the
terminal look only, through `ui_variant.site_groups` while the switch exists
and a plain app once it is removed. All 19 fail against HEAD (`d920ff7`, run
from a `git archive` copy) and pass on the worktree. `test_cc_home.py` still
passes (113 passed, 10 skipped with this file).

Browser check: `tools/mobile_sweep_seed.py` with every group on, headless
Chrome at 390, 768 and 1440 (probe script in the session scratchpad, not in
the tree).

| Finding | Fix | Tests | Browser |
|---|---|---|---|
| home-project-1 (high): `tr.drawer` collided with the off-canvas `.drawer` | Row drawers are `tr.row-drawer` in `cc/partials/project_roots.html` and `project_detail.html`, and in the four rules that style them (`components.css`, `phone.css`, `home.css`). The off-canvas `.drawer` is unchanged. | `test_hp1_no_table_row_carries_the_off_canvas_drawer_class`, `test_hp1_the_project_page_draws_row_drawers` | 1440: Browse answer 986 x 124 (was 0 x 0). 390: rows `grid/static`, the h1 is hit-tested (was a fixed black box) |
| home-project-2 (high): a stale tree row turned "This removes X" into a tick | (a) The controls send the state they mean: `?mode=off` (everyday-apps-1's remove-only, already in `partial_toggle`) and a new `?mode=on`, add-only, which never changes the mode of an existing tick. Tree checkbox, home queue Untick, project page tick key and per-computer keys all carry one. A stale request is a no-op with no audit row, answered with the true state. (b) Every tree / home-queue / project answer sends `HX-Trigger: cc-plan-changed`; the tree body, the queue body and `#project-detail` listen `from:body`, and `cc.js` treats that re-read as a poll, so it never unfolds a folded window. | `test_hp2_the_tree_and_the_queue_send_the_state_they_mean`, `..._a_stale_untick_after_a_queue_untick_is_a_no_op_never_a_tick`, `..._a_stale_tick_on_a_ticked_project_keeps_its_mode`, `..._every_plan_answer_tells_the_sibling_windows_to_re_read`, `..._the_project_page_keys_send_the_state_they_mean` | - |
| home-project-3: Cancel left the checkbox flipped | `cc.js`: the dialog's close handler (Cancel or Escape only: OK clears `pending` first) puts a checkbox source back. | `test_hp3_cancelling_a_confirm_puts_a_checkbox_back` | ticked box, Cancel: still ticked |
| home-project-4: "online" counted nothing-ticked computers, missed silent faulted ones | `ui_home._owes`: counted from the row's `plan.count` (a wired computer never counts); `_is_silent`: `health._silence(row)`, the headline's own freshness test, with the old headline check as the fallback. | `test_hp4_nothing_ticked_is_left_out_even_behind_another_why`, `test_hp4_a_silent_computer_with_a_fault_headline_is_not_online` | - |
| home-project-5: "moving" / "in sync" read Syncthing completion only | `ui_home.plan_facts(conn, editor)`: owed bytes from `build_transfers_view` (live lane files plus the non-pending queue, uploads and downloads), ticks from the selections table (every mode), catching-up from the queue, the project view and "getting ready" rows. `home_readouts` reads it through the request (viewer's scope) or takes `facts=`. | `test_hp5_ticks_count_from_the_selections_not_folder_completion`, `test_hp5_moving_counts_the_lane_transfers` | readouts: "2 projects catching up", "2 still catching up" |
| home-project-6: the tree about 10,000 px down on phones | `home.css`: below 1100 px `.home-page > .side` is order 0 and `.main` order 1 (the groups are folded details, so the tree is a few rows). The queue's empty state links to `#win-projects`. | `test_hp6_the_tree_comes_first_on_a_narrow_screen`, `test_hp6_the_empty_queue_links_to_the_tree` | home 390: tree at 602 (was 10016); 768: 486 (was 6650); project 390: tree 456, detail 824 |
| home-project-7: headline clipped, tooltip was the reason code | `fleet_grid.html`: the `.hl` title is the sentence. `home.css`: `.hl` wraps, clamped to three lines on a fine pointer, unclamped on touch or phone. | `test_hp7_the_headline_is_the_sentence_and_wraps` | 390: 110/110 px (all shown); 1440: 58/93 clamped with the title |
| home-project-8: `?as=` dropped by the grid and transfers polls | `fleet.html` threads the request's own `as` (the key `auth.scope_for` reads) onto `/partials/fleet` and `/partials/home-transfers`. | `test_hp8_the_grid_and_transfers_polls_keep_the_pages_as` | `/?as=jsmith`: 2 rows before and 16.5 s after |
| home-project-9: home 1282 px wide at 768 | Fixed by everyday-apps-2's `hud.css` change (the meta row shrinks and clips, the stamp gives way, the long stale sentence only at 1600+). Nothing further needed on home; pinned here. | `test_hp9_the_hud_meta_row_can_shrink` | home 768: scrollWidth 768 |
| home-project-10: phone tap targets under 44 px | `home.css` under `(pointer: coarse), (max-width: 760px)`: tree tick (min 44 x 44), project link, group summary, row "details" summary, fold button (44 x 44), every key 44 px tall. Scoped to `.home-page`. | `test_hp10_home_touch_targets_are_44px` | 390 and 768: no home control under 44 px |
| home-project-11: "Read the answer" landed off screen | `#fleet-diagnostics` carries `data-reveal`; `cc.js` scrolls a non-poll answer into such a target into view and focuses it (tabindex -1). | `test_hp11_read_the_answer_is_brought_on_screen` | not measured: the seed has no diagnostics bundle |

## Shared files touched (surgical edits)

- `dashboard/src/ccsync_dashboard/ui.py` `partial_toggle`: `add_only` beside
  everyday-apps-1's `remove_only`; the `view=project` answer goes through
  `ui_home.plan_changed`.
- `dashboard/static/cc/cc.js`: the confirm close handler, `POLL_EVENTS`,
  `reveal()`.
- `dashboard/static/cc/components.css`, `phone.css`: `tr.drawer` to
  `tr.row-drawer` only.

## Notes for the integrator

- `mode=on` / `mode=off` are now the only values a terminal plan control
  sends without a mode; the plain toggle remains for any caller that sends
  neither.
- `home_readouts` opens its own connection for `plan_facts` (one
  `build_transfers_view` per first paint and per 15 s grid poll). If that
  shows up in a profile, pass `facts=` from the page context.
- Below 1100 px the side column is first on the PROJECT page too, so the
  project's own windows start after the (folded) tree.

## Verifier pass (2026-09-25)

Re-ran every scenario against a fresh `mobile_sweep_seed.py` server (every
group on) in headless Chrome, plus the related suites (1714 passed, 23
skipped across every dashboard test file that touches toggles, readouts,
drawers or the home layout). All eleven CLOSED.

- hp1: rows `table-row/static` at 1440 and `grid/static` at 390; Browse
  answers 986x124 (1440) and 296x225 (390); the h1 is hit-tested at 390.
- hp2: jsmith on JSMITH-STUDIO: queue Untick sends `mode=off`, the tree
  re-read at once (unchecked). The pre-untick tree body put back by hand and
  its "This removes ..." confirmed: nothing re-ticked, server queue empty.
- hp3: Cancel and Escape both leave the box ticked.
- hp4: live DB with JSMITH-MBP (breaker headline) aged 8 h and tchen's ticks
  deleted: "online 2 / 3, JSMITH-MBP not heard from"; `?as=tchen`: 0 / 0,
  "no computer has a project ticked".
- hp5: "moving 522.3 GB, 2 projects catching up", "in sync 0 / 2".
- hp6: tree at 602 (390), 486 (768); project page tree 456, detail 824.
- hp7: titles are the sentence; 390 fully shown, 1440 clamped at 3 lines.
- hp8: `/?as=jsmith` 2 rows / "2 computers" before and 17 s after.
- hp9: home and project at 768: scrollWidth 768.
- hp10: the named controls pass. Correction made by the verifier in
  `home.css`'s touch block: four more home targets still measured 15-27 px
  at 390 (a window's `a.act` link, `details.sub-win > summary`, the
  computers overview's project links, the tree's find field). After it, no
  home control under 44 px at 390; at 768 only an in-sentence link (43 px).
- hp11: a Read the answer key (synthetic, same attributes; the seed has no
  bundle) at 390: scrollY 9122 -> 10906, window top 122, focus on
  `#fleet-diagnostics`.

Minor, not a regression: the key that fires `cc-plan-changed` is also inside
a body that listens for it (tree, `#project-detail`), so that body is read
twice (its own answer, then one GET). Harmless; drop the listener's
self-trigger only if it shows in a profile.
