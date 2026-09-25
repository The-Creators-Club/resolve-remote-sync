# F-everyday: the everyday-apps findings of the UI port review

Fix builder F-everyday, 2026-09-25. Source: `docs/UI_PORT_REVIEW_2026-09-25.md`,
findings everyday-apps-1 to -6. Owner authorisation: "Fix all, also we don't
need to maintain the switch to the old UI." Nothing committed, no version bumped.

## everyday-apps-1: queue Untick did not refresh the computer windows, and their stale Untick ticked the project again (FIXED)

- `ui.py partial_toggle`: `?mode=off` is an explicit REMOVE. If the project is
  not ticked it does nothing: no write and no audit row. It is never a tick.
  (The home builder then added the `?mode=on` twin in the same place for
  home-project-2; both live side by side.)
- `cc/partials/account_computer.html`: Untick posts `...&mode=off`. The
  hidden poll also listens for `account-refresh-all from:body`.
- `cc/partials/person_queue.html`: Untick posts `?view=person-queue&mode=off`.
- `ui_everyday.toggle_answer`: the person-queue answer carries
  `HX-Trigger: account-refresh-all`, so every computer window on the page
  reloads its body at once instead of up to 30 s later.
- Not changed: the computer window's stale "Upload only" / "Sync fully" keys
  are still a set. They now go away on the same refresh.

## everyday-apps-2: HUD overflowed sideways while Syncthing was unreachable (FIXED)

hud-common (`dashboard/static/cc/hud.css`, copied byte for byte into the
broll, music and ytdl `style.css`):
- `.hud-meta` is now `flex: 0 1 auto; min-width: 0; justify-content: flex-end;
  overflow: hidden`, with 4 px padding and a -4 px margin so focus rings are
  not clipped. Its children are `flex: none` except `.hud-stamp`, and
  "updated N ago" (`.hud-stamp-at`) is the part that shrinks, with an
  ellipsis. If the row ever clips, it clips on the start side, so the menu
  key is the last thing to go.
- `.hud-brand` is `flex: 0 0.2 auto; min-width: 36px`, so the name no longer
  collapses to 0 px.
- The long sentence ": syncthing unreachable, data may be stale" is now
  `.hud-stale-long` and only shows at 1600 px and wider. Narrower screens keep
  the LED, the word "stale" and the tip.
- In the 601 to 900 px band, `.hud .hud-lowpri` also hides the alert count,
  the account link and "updated N ago" (`topbar.html`, `stamp.html`). The
  "more" sheet already carries the count and the account link.
- Cosmetic fix: "stale" and its sentence are now one flex item, so the gap no
  longer draws "stale : syncthing".
- Measured in headless Chrome on the seeded server (admin, Syncthing
  unreachable, a problem and alerts open), /account, /transfers and /help.
  Before: scrollWidth 1390 at 1024 and 1281 at 768, `.hud-name` 0 px at 1440
  and 1100. After: no overflow at 1920, 1600, 1440, 1280, 1100, 1024, 901,
  900, 768, 601 or 390. `.hud-meta` clip (scrollWidth minus clientWidth) is 0
  at every width. `.hud-name` is 55 to 69 px everywhere.
- This also covers home-project-9 (the same overflow at 768 on home and
  project).
- Note: the block I copied also carried another builder's a11y-copy edit
  (`content: " :" / ""` on `.snav-h::after` and `.snav a::before`). All four
  sheets are identical; the three SPA `test_hud_common` suites pass.

## everyday-apps-3: hud-hide-sm and hud-more-btn lost the cascade (FIXED)

- Phone block: `.hud-nav, .hud .hud-hide-sm { display: none }`. At (0,2,0)
  it now beats `.hud-meta a` at (0,1,1).
- Base: `.hud-nav .hud-more-btn { display: none }`. At (0,2,0) it beats
  `.hud-key { display: inline-flex }`. The 601 to 900 block re-shows it with
  the same selector.
- Measured: at 390 the alert count, the account link and the menu key all
  compute `none`, and scrollWidth equals 390 (it was 401). "more" computes
  `none` at 1920, 1440 and 1100, and `flex` at 768.
- The test computes `display` through a small cascade over the hud-common
  block (specificity, source order and width media queries), as the review
  asked. It does not just grep the rule text.

## everyday-apps-4: SPAs turned ccsync_ui_effective into a session cookie (FIXED: SPA half; the /ui/preview half goes with the switch)

- `syncDashboardLook` in `broll/web/static/app.js`, `music/web/static/app.js`
  and `ytdl/web/static/app.js` now writes the cookie with
  `max-age=15552000`, the dashboard's own 180 days.
- Not touched: `ui_variant.ui_preview` and `set_effective_cookie`. Those are
  the look switch, which is being removed (mechanism-*, another builder).
  With one look there is no switch to go stale. Once the switch is gone, the
  SPA's first-paint cookie read and this write can go too. The new tests only
  check writes that still exist, so they will not block that removal.

## everyday-apps-5: help code blocks widened the page on phones (FIXED)

- `components.css`: `.doc pre { max-width: 100%; overflow-x: auto }`,
  `.doc pre code` without the inline-code chip, and
  `.doc table { display: block; max-width: 100%; overflow-x: auto }`.
- Measured at 390 with mobile emulation. Before, innerWidth was 531 on
  /help. After, it is 390 on /help, /help/EDITOR_SETUP.md, /help/API.md and
  /help/GOTCHAS.md, and 768 at 768.

## everyday-apps-6: tap rule keyed on [title], which cc.js removes (FIXED)

- `phone.css` pointer:coarse: `.tag:is([title], [data-tip])` and
  `.led:is([title], [data-tip])`. The 44 px rule now holds before and after
  adoptTips, so a polled row keeps one height.
- Measured on /transfers at 390: adopted tags (no title, with data-tip) are
  44 px. They were 19 px.

## Tests

Each test fails on the code the review measured. For every static test this
was checked by pointing it at `git archive HEAD` copies of `static/cc` and
`templates/cc`. The route tests fail on HEAD with a 400 (unknown sync mode)
and with no HX-Trigger.

- `dashboard/tests/test_cc_everyday_review_fixes.py`: 28 tests.
  - apps-1: 4 tests.
  - apps-2: 12 tests, counting parametrised cases.
  - apps-3: 11 tests, plus 1 check of the cascade helper itself.
  - apps-5: 1 test.
  - apps-6: 1 test.
- `broll/web/tests/test_look_cookie_lifetime.py`,
  `music/web/tests/test_look_cookie_lifetime.py` and
  `ytdl/web/tests/test_look_cookie_lifetime.py`: 1 test each, for apps-4.

Runs:
- The dashboard files touching these areas: 670 passed, 11 skipped.
  - 2 failures in `test_cc_home.py::test_a_tick_from_the_tree_answers_with_the_tree_for_that_computer`.
    They belong to the home builder, whose tree now posts `mode=off` / `mode=on`
    and whose test still expects the old URL.
- SPA suites: broll 725 passed, music 689 passed, ytdl 1059 passed.

## Files

Changed:
- `dashboard/src/ccsync_dashboard/ui.py`
- `dashboard/src/ccsync_dashboard/ui_everyday.py`
- `dashboard/templates/cc/partials/account_computer.html`
- `dashboard/templates/cc/partials/person_queue.html`
- `dashboard/templates/cc/partials/stamp.html`
- `dashboard/templates/cc/partials/topbar.html`
- `dashboard/static/cc/hud.css`
- `dashboard/static/cc/components.css`
- `dashboard/static/cc/phone.css`
- `broll/web/static/style.css`, `music/web/static/style.css`, `ytdl/web/static/style.css`
- `broll/web/static/app.js`, `music/web/static/app.js`, `ytdl/web/static/app.js`

New:
- `dashboard/tests/test_cc_everyday_review_fixes.py`
- `broll/web/tests/test_look_cookie_lifetime.py`
- `music/web/tests/test_look_cookie_lifetime.py`
- `ytdl/web/tests/test_look_cookie_lifetime.py`
