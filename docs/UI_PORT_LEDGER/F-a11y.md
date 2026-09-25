# F-a11y: accessibility and copy fixes (UI port review 2026-09-25)

Fix builder F-a11y, 2026-09-25. Scope: every `a11y-copy-*` finding in
`docs/UI_PORT_REVIEW_2026-09-25.md`, in the terminal-look files only (classic
templates are about to be deleted and were not touched). Not committed, no
version bumped.

Test file: `dashboard/tests/test_cc_a11y_copy.py` (46 tests). Against a
`git archive HEAD` export of the tree, 39 of them fail and the 7 that pass
are scan self-tests or sheets that never had a glyph. With the fixes, all
46 pass.

| Finding | Status | What changed | Tests |
|---|---|---|---|
| a11y-copy-1 | fixed | Every decorative `content:` glyph in `static/cc/*.css` and in the SPA sheets' terminal half (hud-common onward, all three apps, hud-common still byte-identical) is followed by its alt twin, `content: X; content: X / "";` (the first line is the fallback for a browser without alt text). `.vd .fix` keeps "what to do: " as its alt. Transfers direction arrows are drawn by a `dirmark` macro: arrow aria-hidden, the word "up"/"down" visually hidden. | `test_every_generated_glyph_has_an_empty_alternative[*]` (12), `test_the_alt_scan_would_catch_a_bare_glyph`, `test_what_to_do_keeps_its_words_for_a_screen_reader`, `test_the_transfer_direction_is_a_word_behind_an_arrow`, `test_the_decorative_checkbox_glyph_is_not_part_of_the_name` |
| a11y-copy-2 | fixed | `#cc-confirm` gets `aria-describedby="cc-confirm-q"` and the question paragraph that id; Site settings' `#site-ask` is described by `#site-ask-q`. `cc_spa.js` (all three copies): the dialog gets `aria-label` and `aria-describedby` at the question, which gets an id. | `test_the_confirm_dialog_is_described_by_its_question`, `test_the_site_settings_ask_is_described_by_its_question`, `test_the_spa_confirm_has_a_name_and_says_its_question[*]` (3) |
| a11y-copy-3 | fixed | `cc_spa.js` `showTip` sets `aria-description` from the title before removing it (and `restoreTitles` takes it back off). New `focusin`/`focusout` listeners show and hide the tip, so keyboard focus sees it, and so does a tap that focuses a control on a touch screen. | `test_spa_tips_keep_the_description_and_follow_focus[*]` (3) |
| a11y-copy-4 | fixed | `cc.js`: `TIP_SELECTOR` now covers `a/button/[role=tab]/label/select/input/textarea[title]`, so focus shows the floating tip (the existing 900 ms control delay). On a coarse pointer only, `adoptTips` puts a `.tip-btn` "?" after each explained control (not in the dock, a dialog or a fold; an input inside a label that explains itself defers to the label), named "What X does". `window.ccsyncOpenHint` is defined and opens `#chip-sheet` through its three hooks. A typed field with an adopted title keeps the text cursor (components.css). | `test_dashboard_tips_reach_keys_tabs_and_fields`, `test_a_touch_screen_gets_a_question_mark_that_opens_the_hint_sheet` |
| a11y-copy-5 | fixed | Every h1 `<span class="prompt">` is aria-hidden (17 pages). Every snake_case window title goes through `cc_title` (admin_settings bar and ask, cards_landing bar, Packages bar and this_dashboard, Health x3, Alerts x2, Protection x2, Recovery bar, ev_macros.win). `.doc h2/h3` "## "/"### " and the `//` section glyphs have empty alt text (a11y-copy-1). | `test_no_page_title_prompt_reaches_a_screen_reader`, `test_no_window_title_is_named_with_underscores`, `test_cc_title_draws_a_space_for_a_screen_reader`, `test_help_headings_lose_their_hashes_for_a_screen_reader` |
| a11y-copy-6 | fixed | The four bare folds (admin_settings, cards_landing, Packages partial, this_dashboard) now say "fold <title>". Users: export data, erase history, revoke, set password, save name, enable/disable, suspend/resume, delete (x3), approve (device and key), dismiss, add/update ssh key, remove computer each carry a visually hidden object. Home problems and Health notices: the link and dismiss carry ": <subject>"; Health rows' links carry ": <title>". | `test_every_fold_names_its_window`, `test_a_repeated_key_names_what_it_acts_on[*]` (4) |
| a11y-copy-7 | fixed | Each page sheet linked after phone.css (everyday, home, settings_fleet, settings_people) ends with its own 760 px floor for its sub-12 px selectors. New CSS-fact check: a rule under 12 px outside a media query must be floored later in its own sheet, or (for hud/terminal/components, which load before phone.css) in phone.css. The mobile_sweep.js computed check was not added. | `test_no_sheet_undercuts_the_12px_phone_floor` |
| a11y-copy-8 | fixed | "...and &quot;Resume&quot; puts it back." / "&quot;Disable&quot; only stops logins." Packages: `Press "Check now" there`, `Press "Check now" to publish them`, `the From the vendor window lists them, and "Check now" fetches`, and the feed policy option `manual: "Check now" and publish only`. New scan: an ALL-CAPS word in any cc `hx-confirm` that equals a key label on any cc page fails. | `test_a_confirm_names_a_key_in_sentence_case_not_capitals`, `test_packages_quotes_check_now_and_names_the_window_in_words` |
| a11y-copy-9 | fixed | sftp_host hint: "Usually the same server as this dashboard." The new scan (string literals in every cc `{% set %}` block, through the sweep's `_retired_words_in`) also caught `fleet_grid.html`'s "suppressed on this machine", now "this computer". | `test_no_retired_word_in_the_json_help_maps`, `test_the_help_map_scan_sees_a_set_block` |
| a11y-copy-10 | fixed | `alerts._for_words(stamp, now)`: None with no stamp, else "for N minute(s)/hour(s)/day(s)". Feed stale: "has never been able to check for new CC Sync builds. Nobody in the fleet will be offered a fix until it can." or "has not been able to check ... for 15 days". Weekly BUILDS line: "is on 0.9.53 (since when is not known)" or "has been on 0.9.49 for 3 days". Loopback-held: ", for N hours" or nothing. `_age_words` itself is unchanged (other phrasings and tests use it). | `test_for_words_never_says_since_never`, `test_the_feed_alert_on_a_fresh_site_says_never_checked`, `test_the_feed_alert_with_a_stamp_says_for_how_long`, `test_the_weekly_builds_line_never_says_since_never` |
| a11y-copy-11 | fixed | cc project_detail placeholder: `e.g. 2026/Show/Episode/Interviews/...`. | `test_no_studio_show_name_is_an_example_path` |

## Files touched

- `dashboard/static/cc/`: components.css, terminal.css, hud.css, home.css,
  everyday.css, health.css, settings_fleet.css, settings_people.css, cc.js
- `broll|music|ytdl/web/static/style.css` (hud-common + the html.cc tail),
  `broll|music|ytdl/web/static/cc_spa.js` (byte-identical)
- `dashboard/templates/cc/`: shell, the 17 page templates with an h1 prompt,
  admin_settings, admin_packages, admin_health, cards_landing, and partials
  transfers, admin_packages, admin_alerts, protection, recovery, admin_users,
  admin_suspend_button, home_problems, health_notices, ev_macros, fleet_grid,
  project_detail
- `dashboard/src/ccsync_dashboard/alerts.py` (`_for_words` + three callers)
- `dashboard/tests/test_cc_a11y_copy.py` (new)

## Checks run

- `dashboard`: test_cc_a11y_copy, test_cc_css_facts, test_ui_chrome,
  test_sweep_2026_09_04_copy, test_cc_settings_people,
  test_cc_settings_site_packages, test_cc_home, test_cc_everyday, test_alerts,
  test_cc_cards_landing, test_copy_sweep_phase7: 1076 passed, 23 skipped.
  test_admin_users*, test_cc_settings_review_fixes, test_cr312, test_cr335,
  test_fleet_grid_declutter, test_health_page, test_help_page, test_notices,
  test_protection, test_recovery, test_ui_health_group, test_ui_filters,
  test_account_page, test_bug_hunt_2026_09_24_w2_d-ui: 448 passed, 1 skipped.
- broll/music/ytdl `test_cc_body.py` + `test_mounted_prefix.py`: 28/28/27 passed.

## Notes for the integrator

- The JS behaviour (tips on focus, the "?" button, the SPA dialog names) is
  pinned by source facts, not a browser run. A CDP check at 390 with a coarse
  pointer (tipBtns > 0, the hint sheet opens) and an AX check of the confirm
  description are still owed.
- iOS Safari does not focus a button on tap, so the SPA tap path for
  controls (a11y-copy-3) works on Android and desktop keyboard, not iPhone.
  The dashboard's "?" button covers iPhone.
- `sed -i` under Git Bash turned some cc templates' working-copy CRLF into
  LF. Git's autocrlf hides it (diffs show only the real lines).
