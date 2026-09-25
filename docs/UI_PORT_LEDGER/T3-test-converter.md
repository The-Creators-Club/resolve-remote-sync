# T3: test converter (dashboard, six files)

Builder T3, 2026-09-25, worktree branch `ui-replace`, after C-collapse made the
terminal look the only one. Tests only; no product code changed, nothing
deleted. Every conversion keeps its test's behaviour and bug id and asserts
it against the terminal markup. Where a paired NEGATIVE assertion looked for
the retired classic string (and so passed without testing anything), it was
converted too.

| File | Test | Was | Now |
|---|---|---|---|
| test_broll_mount.py | test_a_signed_in_editor_renders_a_page_through_the_mount | `[ B-ROLL ]` in the nav | the HUD's `<a href="/broll/"` link and `>b-roll</a>` |
| test_broll_mount.py | test_a_data_root_it_cannot_prepare_is_mounted_but_never_advertised | `[ B-ROLL ]` absent (vacuous) | no `<a href="/broll/"` on the page |
| test_bug_hunt_2026_09_11_dash_mounts_ui.py | test_the_machine_panel_shows_what_resolve_last_said | `<dt>RESOLVE</dt>`, `project open: <span class="who">` | `<dt>resolve</dt>`, `project open: <b>FF5 EP12</b>`; every other fact unchanged |
| test_bug_hunt_2026_09_11_dash_mounts_ui.py | test_a_machine_that_has_not_sent_them_renders_nothing | `<dt>RESOLVE</dt>` absent (vacuous) | `<dt>resolve</dt>` absent |
| test_bug_hunt_2026_09_18_dashboard_mediums.py | test_the_grid_draws_an_unreported_lane_in_its_own_style (dash-api-4) | grep of the classic template for `lane.reported` / `unknown` | the grid calls `cc_lane_tone(lane`, and `ui_home.lane_tone` never gives an unreported lane the class a reported healthy lane gets (nor `ok`/`busy`) at any headline level |
| test_bug_hunt_2026_09_18b_dashboard_api_db.py | test_the_packages_page_names_a_push_that_cannot_be_sent (CR-306) | `[ CANNOT BE SENT ]` | an err tag reading `cannot be sent`, plus the unchanged "It still takes jobs." |
| test_bug_hunt_2026_09_24_crash_looped.py | test_the_grid_chip_reads_a_crash_loop_as_a_crash_loop | `[ UPDATE KEPT CRASHING ]` | the home tag `<span class="w">update kept crashing</span>` |
| test_bug_hunt_2026_09_24_crash_looped.py | test_the_packages_row_offers_no_update_now_for_the_fled_build | `[ UPDATE NOW ]` absent (vacuous) | no `>update now<` key and no update form post in the row |
| test_bug_hunt_2026_09_24_w2_d-cards.py | test_want_names_the_episode_that_is_not_open_and_offers_its_button (logic-cards-4) | `class="cl-want"`, `FRAMING FORMOSA IS NOT OPEN` | `note cl-want` banner, `<b>Framing Formosa is not open.</b>`, the slug button; no-want check on `cl-want"` |
| test_bug_hunt_2026_09_24_w2_d-cards.py | test_entering_an_episode_page_sets_the_carry_on_cookie | `CARRY ON WITH FRAMING FORMOSA` | `Carry on with Framing Formosa` and the key's `href="/cards/p/<slug>/"` |

Deleted tests: none. Product fixes: none (no product bug surfaced).

Final: the six files, 179 passed, 0 failed.
