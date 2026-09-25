# F-settings: the settings-* findings of the UI port review

Fix builder F-settings, 2026-09-25, on the owner's "fix all" for
`docs/UI_PORT_REVIEW_2026-09-25.md`. Worktree branch `ui-replace`. Not committed, no
version bump. Classic templates were not touched: they are being deleted.

Tests: `dashboard/tests/test_cc_settings_review_fixes.py`, 17 tests. The browser
tests run the shipped htmx 1.9.12, `cc/cc.js` and `cc/shell.html`'s inline keeper in
headless Chrome. Each test was run against the code without its fix and failed
there. That was done by stripping only this builder's hunks, never with `git stash`
in the shared tree.

| Finding | Status | What changed | Tests |
|---|---|---|---|
| settings-1 (high, live bug) | fixed | `ui._form(request, max_fields=...)`. The default cap stays at 16. `partial_admin_alerts_save` uses `ui.alerts_form_max_fields()`, which is `len(alerts.SETTING_KEYS) + 4`, so the next setting key cannot bring the 400 back. On the form side, the cc template's header comment ties `#alerts-form` to that cap: one field per key and nothing else. The classic twin is fixed too, because the fix is in the route. | `test_alerts_save_takes_every_setting_key_at_once`, `test_alerts_save_still_refuses_a_flood_of_fields`, `test_every_other_form_route_keeps_the_default_cap`, `test_the_rendered_alerts_form_saves_as_the_browser_sends_it` (posts every control the rendered `#alerts-form` owns, including `form=` owners) |
| settings-2 (low) | fixed | The rollback form carries `row_version` (the served row it sits on). `partial_admin_package_current` keys the refusal to that row. `_packages_and_feed` sends a refusal back to the top banner when `error_for` matches no row on the page. `cc.js` has a new `htmx:afterSettle` rule: for every `.row-refusal` / `.error-banner` / `.htmx-refusal` under the LIVE swapped element, it opens each closed `<details>` above it and unfolds the window. It runs after the settle's `applyFolds` and after the details keeper, so neither can shut them again. | `test_the_rollback_select_names_the_row_it_sits_on`, `test_a_refused_rollback_is_drawn_on_the_served_row`, `test_a_refusal_for_no_row_on_the_page_falls_back_to_the_banner`, `test_a_refusal_on_a_held_row_still_lands_on_that_row`, `test_a_row_refusal_inside_folded_held_builds_is_opened_up_to` (Chrome) |
| settings-3 (medium) | fixed | `.sp-stack`, `.sf-stack` and `.sf-tabs-wrap` get `grid-template-columns: minmax(0, 1fr)`. `phone.css`'s existing `.bar .meta` ellipsis then handles the long bar meta. Measured with no mobile emulation, in a 390 px iframe, because headless Chrome will not make a window narrower than 500 px. Before the fix: assignments 627, packages 432, setup 443 (the review's numbers). After: all within 390. The HUD dock's "...more" at 401 px, noted in the evidence, belongs to the HUD's own findings and was not changed here. | `test_settings_pages_do_not_scroll_sideways_on_a_phone[/admin/assignments, /admin/packages, /setup]` (Chrome) |
| settings-4 (low) | fixed | The `sent.log` table is wrapped in `.scroll-x` inside `.scroll-y` (the `admin_audit` pattern). | `test_alerts_sent_log_does_not_scroll_sideways_at_tablet_width` (Chrome, 768; before: `.scroll-y.hl-list` scrolled sideways by 532 px) |
| settings-5 (low) | fixed | In `cc.js`, a click on an in-page `a[href^="#"]` whose hash the address already carries calls `openHash()` (no hashchange fires for it). Other hashes are still left to hashchange. Clicks on tabs and clicks with a modifier key are not affected. This covers "AI providers" on Site and "notices" on Health. | `test_an_in_page_link_to_a_tab_works_every_time` (Chrome) |
| settings-6 (low) | fixed | A dismiss that removed a notice answers with `HX-Trigger: cc-health-changed` (`ui_health.HEALTH_CHANGED`). A refused dismiss (notice gone) triggers nothing. On `admin_health.html`, `#health-open-list` re-reads `/admin/health` on that event with `hx-select` itself and `hx-select-oob` for the tab count (`#htab-open-count`), the bar meta (`#health-open-meta`) and the head's totals (`#health-head-sub`, `#health-head-bands`). No new template, so `ui_variant.TEMPLATE_GROUPS` is untouched. | `test_a_dismiss_tells_the_page_to_reread_open_findings`, `test_a_dismiss_of_a_gone_notice_triggers_nothing`, `test_the_open_findings_tab_rereads_when_a_notice_is_dismissed` (Chrome, real htmx) |

## Files touched

- `dashboard/src/ccsync_dashboard/ui.py`: `_form` `max_fields`, `alerts_form_max_fields`, the alerts save, the `_packages_and_feed` fallback, `row_version` in the make-current route
- `dashboard/src/ccsync_dashboard/ui_health.py`: HX-Trigger on dismiss
- `dashboard/templates/cc/partials/admin_alerts.html`: header comment, `.scroll-x` around sent.log
- `dashboard/templates/cc/partials/admin_packages.html`: `row_version` hidden field
- `dashboard/templates/cc/admin_health.html`: ids and the re-read hooks
- `dashboard/static/cc/cc.js`: afterSettle refusal reveal, same-hash link
- `dashboard/static/cc/settings_people.css`, `dashboard/static/cc/settings_fleet.css`: `minmax(0, 1fr)` tracks
- `dashboard/tests/test_cc_settings_review_fixes.py`: new

## Gate run (this builder's area)

`test_cc_settings_review_fixes`, `test_ui_health_group`, `test_cc_settings_site_packages`,
`test_cc_settings_people`, `test_cr335_packages_page`, `test_alerts`, `test_packages`,
`test_cc_css_facts`, `test_templates_wave3_2026_09_04`, `test_triage`, every `test_cc_*`,
`test_bug_hunt_2026_09_24_w2_d-ui`, `test_ui_variant*`: all green (375 + 522 passed).

The new tests use `ui_variant` "all" to draw the terminal look. When the switch is
removed, they need only the parametrize marker dropped.

## Verifier pass (2026-09-25)

Re-ran each scenario against a real seeded dashboard (`tools/mobile_sweep_seed.py`,
every group on) in headless Chrome over CDP, plus the builder's tests.

| Finding | Verdict | Evidence |
|---|---|---|
| settings-1 | CLOSED | Real Save key on `/admin/alerts` at 1440: FormData 17 pairs, `POST /partials/admin/alerts/save` 200, "saved.", no "malformed". Cap is 21 (17 keys + 4). |
| settings-2 | CLOSED | Recalled-after-render probe (0.2.0 retracted, rollback posted from the 0.3.0 row): refusal drawn on 0.3.0 only, no banner. Deleted-row case falls back to the banner (builder test). Chrome harness: folded window and closed `pkg-other` both open over the refusal. |
| settings-3 | CLOSED | 390 px, no mobile emulation: assignments, packages, setup, users, jobs, settings, audit, health all scrollWidth 380 against innerWidth 390. |
| settings-4 | CLOSED | `/admin/alerts` with 25 sent rows: sent `.hl-list` 704/704 at 768, 350/350 at 390. |
| settings-5 | CLOSED | Site: link, features tab, link again opens AI providers both times; also after `/go/ai-providers`. Health "notices" link works twice. |
| settings-6 | CLOSED | Dismiss through the confirm dialog: tab 54 to 52, bar meta, head totals and bands re-read, row gone from open.log, ids stay unique, list keeps its trigger, a folded open.log stays folded. |

Verifier correction: `.sp-eula` (Setup's EULA box, a `.scroll-y`) scrolled sideways by
12-39 px at 390 on a long path; `overflow-wrap: anywhere` added in `settings_people.css`
(same class as settings-3/-4, not a review finding). Re-measured 316/316.
