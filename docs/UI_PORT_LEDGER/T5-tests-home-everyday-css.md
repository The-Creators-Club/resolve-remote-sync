# T5: test conversion after the collapse (home, everyday, cards landing, css facts)

Builder: test converter T5, 2026-09-25, worktree branch `ui-replace`. Six
dashboard test files that failed after C-collapse, converted to the terminal
look as the only look. No product code changed. Nothing committed.

Common conversion: the `ui_variant` fixture, `ui_variant_support.UIVariant`,
`uv.site_groups` monkeypatches and every `if not _on(v)` classic branch are
gone; htmx requests send `conftest.HX` (+ `HX-Current-URL`); template paths
read `templates/` instead of `templates/cc/`. Every terminal-branch assertion
was kept as written.

## Per file

- `test_cc_cards_landing.py` (6 pass): converted. The page test keeps every
  shared finder/fact assertion and every script hook, and now pins
  `data-ui="cc"` (cards_landing.js keys its nothing-shifts branch on it) and
  the absence of `[ TIMELINE CARDS ]` / `/static/cards_landing.css`.
  Deleted assertion: `recent.hidden = searching || any === 0;` (the classic
  hide-on-search branch of cards_landing.js); replaced by the terminal line
  `recent.hidden = any === 0;`.
- `test_cc_css_facts.py` (25 pass): `theme_common_is_byte_identical_to_the_classic_sheet`
  converted to a parametrised check against the three SPA sheets (broll,
  music, ytdl), which still carry the block; the dashboard's copy is
  terminal.css now. `TEMPLATES_CC` points at `templates/`: four scans
  (customer domain, box drawing, classic vocabulary, glyph ranges) had turned
  into silent no-ops when `templates/cc/` vanished; their `is_dir()` escape
  hatches are removed and they now scan every template (all pass).
- `test_cc_everyday.py` (36 pass): converted. Deleted: the `TEMPLATE_GROUPS`
  half of the group-table test (the table is gone; the file-exists half
  stays); "the classic account.js is untouched" became "the classic
  account.js is gone"; the sign-in page's "way back" (`/ui/preview?variant=classic`)
  became "no /ui/preview and no word classic on the page". The person-queue
  and person-queue-untick 404-without-the-group branches are deleted (no
  group).
- `test_cc_everyday_review_fixes.py` (29 pass): converted (the switch seam
  and its import fallback removed; `hx()` sends HX). No assertion changed.
- `test_cc_home.py` (43 pass): converted. `partials/home_collector.html`
  left HOME_FILES (deleted by the collapse); the exists test now pins that it
  is gone. The grid poll asserts `id="fleet-collector"` is NEVER on the home
  grid (was: only while settings-health was off). LG-17's "Retention last
  ran" assertion left this file: it only ran with settings-health off, and
  the same line is pinned on Health by `test_ui_health_group.py`. The
  "404 without home" branch of the new-named routes test is deleted. The
  project page test now also pins `data-ui="cc"` (was `check_page`).
- `test_cc_home_review_fixes.py` (19 pass): converted. The 6 failures were
  the stale-page gate answering HX-Refresh because the fallback headers had
  no `X-CC-UI`; `_hx` sends HX now. `CC_T` points at `templates/`, so
  home-project-1's "no `<tr class="drawer">`" scan, which had become a
  silent no-op, scans every template again (passes).

## Product findings (reported, not fixed: not my files)

- `static/cards_landing.js` lines ~249-256 still carry the classic
  `else { recent.hidden = searching || any === 0; }` branch behind
  `var terminal = ... === 'cc'`. Every page is `data-ui="cc"`, so it is dead
  code; harmless, but the collapse can drop the branch and the `terminal`
  flag.

## Final numbers

158 passed, 0 failed across the six files
(dashboard venv, from the worktree `dashboard/`).
