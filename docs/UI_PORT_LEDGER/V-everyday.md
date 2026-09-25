# V-everyday: verification of F-everyday (everyday-apps-1 to -6)

Verifier, 2026-09-25. Seeded server (`tools/mobile_sweep_seed.py` on the
worktree, every group on, the editors given a known password so the account
page could be driven as jsmith), headless Chrome via Playwright.

## everyday-apps-1: CLOSED

- Code: `ui.py partial_toggle` `mode=off` means remove only. A project that
  is not ticked is a no-op: no write, no audit row, never a tick. The queue
  answer (`ui_everyday.toggle_answer`) sends `HX-Trigger: account-refresh-all`.
  Each `.account-pc` poll listens `from:body`.
- Browser, jsmith at 1440 on /account: queue Untick on Animals, then OK in
  the cc confirm dialog. Straight after the POST, the page sent
  `GET /partials/account/computer` for both JSMITH-MBP and JSMITH-STUDIO.
  The JSMITH-MBP window went from [Sync fully, Untick] for Animals to empty
  (before, it stayed for up to 30 s). A stale computer-window Untick
  (`...&machine=JSMITH-MBP&mode=off`) then answered 200. A fresh
  /account still showed Animals unticked on both.
- Residual: a stale "Sync fully" / "Upload only" key is still a set, as the
  ledger says. The refresh now clears it in milliseconds, not 30 s.
- `test_cc_home.py` passes now (122 passed with the everyday file), so the
  home builder has caught the 2 failures F-everyday reported.

## everyday-apps-2: CLOSED

- The hud-common block is byte-identical in all four sheets (same md5).
- Measured as owen (admin, Syncthing unreachable, problems and alerts open)
  on /transfers, /account, /help, /, /installer and /project/2026-ff5-animals
  at 1920, 1600, 1440, 1280, 1100, 1024, 901, 900, 768, 601 and 390:
  - scrollWidth is never above innerWidth.
  - `.hud-meta` clip is 0.
  - The menu key is inside the viewport.
  - `.hud-name` is 55 to 69 px.
  - The long stale sentence shows only at 1600 and wider, and reads
    "stale: syncthing ..." (no " : ").
- Worst case, with the b-roll, music, youtube and cards nav links injected
  (the seed mounts no apps): no overflow at any width. "updated N ago"
  shrinks to 0 from 1280 down. The brand name falls to 49 px at 901 and
  29 px at 601. That is narrower but never 0 and never overflows, so it is
  not a finding.

## everyday-apps-3: CLOSED

- At 390, the alert count, the account link and the menu key compute to
  `none`, and the page is 390 wide on all six pages.
- "more" computes to `none` at 1920 through 901, and to `flex` at 900, 768
  and 601.

## everyday-apps-4: CLOSED (cookie half); first-paint half goes with the switch removal

- All three `syncDashboardLook` writes carry `max-age=15552000`, which equals
  `ui_variant.PREVIEW_MAX_AGE` (180 d). The three `test_look_cookie_lifetime`
  tests pass.
- Not re-run live: the seed mounts no SPA. This is a code trace only.
- Owed to the switch-removal builder: `/ui/preview` still exists, and each
  SPA's `index.html` still chooses its first-paint classes from the cookie.
  A browser with no cookie still paints classic and then flips (the review's
  0.69 CLS). With one look, those classes should be unconditional.

## everyday-apps-5: CLOSED after a verifier correction

- The builder's `.doc pre` / `.doc table` fix holds: /help went from 531 to
  390.
- A sweep of every document /help links (496 at 390) found 147 pages still
  wider than the phone, up to 533 px. The cause was not pre blocks but three
  other things:
  - contents entries whose heading is one long path (`.help-toc a`);
  - the reader window's title naming a deep document (`.win > .bar h2.t`,
    nowrap bar);
  - the page head's path line (`.head .sub`).
- Correction (mine), in `dashboard/static/cc/everyday.css` beside
  `.ev-help .help-doc`:
  - `.ev-help .help-toc { overflow-wrap: anywhere }`;
  - `.ev-help .win > .bar h2.t { min-width: 0; overflow: hidden; text-overflow: ellipsis }`.
    The bar keeps its one line; the document list names the file in full;
  - `.ev-help .head > div { min-width: 0 }` and
    `.ev-help .head .sub { overflow-wrap: anywhere }`.
- After: 0 of 496 over at 390 (the last two, the THIRD_PARTY_LICENSES
  pages, re-measured one by one after the head fix) and 0 of 496 at 768.
  Before the correction, 768 also had several (up to 862).
- Test added: `test_everyday_apps_5_help_contents_and_title_wrap` in
  `dashboard/tests/test_cc_everyday_review_fixes.py`.

## everyday-apps-6: CLOSED

- /transfers at 390 with mobile emulation, polling every 2 s. Summary-row
  height was sampled every 5 ms for 12 s: it held at one value (108 px), and
  layout shift was 0. The adopted tags (data-tip, no title) are 44 px.

## Runs

- `test_cc_everyday_review_fixes.py`: 29 passed.
- Dashboard `-k "cc_ or help or ui_"`: 619 passed, 27 skipped.
- `test_cc_everyday.py` + `test_help_page.py`: 104 passed, 1 skipped.
- The b-roll, music and youtube `test_look_cookie_lifetime.py`: 1 passed each.
- ytdl `test_hud_common.py`: passed.

Scripts: `scratchpad/vfe_*.py` (session scratchpad, not the tree).
