# T4: test conversion after the classic look was retired (2026-09-25)

Builder: test converter T4, worktree branch `ui-replace`. Nothing committed,
no version bumped. Six dashboard test files that failed after C-collapse.
Every converted test keeps its bug id and asserts the same behaviour on the
terminal markup; no test was weakened to pass.

## Per file

### tests/test_cards_capability.py (converted, 1 test)
- `test_the_chip_renders_and_the_refusing_machine_gets_none`: `[ CARDS: E1 v5 ]`
  is now the fleet row's tag `<span class="w">cards: E1 v5</span>`; the
  refusing machine draws no `cards` tag.

### tests/test_cards_mount.py (converted, 1 test)
- `test_an_engine_that_will_not_build_is_a_failed_episode`: "FAILED" is the
  landing's `cl-badge-failed` tag, and the page carries the exception TYPE.

### tests/test_cards_picker.py (converted, 3 tests)
- recent window: `[ YOUR RECENT ]` -> `data-win="recent"` + `cl-recent`.
- em dash scan: `static/cards_landing.css` (deleted) -> `static/cc/cards_landing.css`.
- one bad mtime: rows are `class="ep cl-ep"`; counted by class token.

### tests/test_cc_a11y_copy.py (converted, 9 tests, one line)
- `CC_T` pointed at `templates/cc/`, which moved up to `templates/`.

### tests/test_bug_hunt_2026_09_24_w2_d-diag.py (converted, 6 tests; PRODUCT FIX)
- `_labels` now returns the quoted D8 label lower-cased and `_keys()` reads
  every terminal key's `<span class="t">` text; the halt alerts, the recovery
  step, "Undo this change", "Create & link", "Ask this computer why" and
  "Update now" are matched against real keys instead of `[ LABEL ]`.
- collector panel: the window is on Settings, Health (`#fleet-collector`,
  filled from `/partials/health-collector`); `/go/collector` is
  `ui_chrome.go_href("collector") == "/admin/health#fleet-collector"`.
- PRODUCT (copy): three fix strings sent the owner to "the Dashboard panel"
  on Packages; the terminal window there is titled "this dashboard". Now
  "the This dashboard panel" in `notices.py` (ignored_report_sections),
  `alerts.py` (yt-dlp age) and `release_feed.py` (an unoffered newer bundle).
  The test pins the notice copy and that Packages draws `data-win="this_dashboard"`.

### tests/test_bug_hunt_2026_09_24_w2_d-ui.py (converted, 45 tests + 5 vacuous; PRODUCT FIX)
- Browser harness: the inline keeper script is read from `shell.html`
  (identical to base.html's); every Chrome test runs it for real.
- ui-dash-main-1 (markup): the sidebar is gone; the same rule is pinned on
  the terminal tree: the tick swaps innerHTML into `closest .tree-body`, the
  partial draws no `.tree-body` or find box, every include sits in one.
- Banner markers: `note err error-banner` / `note ok result-banner`.
- Plan-changes row: `<td data-label="project" title=slug>label</td>`.
- Halt: `/partials/fleet-halt-banner` -> `/partials/halt-line`; keys by
  their terminal text; the expired line gone after the ack.
- Packages feed copy: `Press "Check now" there to fetch them`.
- Settings page: `static/cc/site_settings.js`; no `<main>` (body text); the
  refusal line has no glyph (tone `bad`); undo asks through `#site-ask`, so
  the scenario reads its question and presses its yes.
- Project tick: its URL names `mode=on` now; the capacity confirm still rides it.
- Fix-root chips: `.fix-root-machines` keys with `aria-current`; the
  "SYNC QUEUE: LESO" title is the queue hint `For leso on EDIT-PC`; phone
  wrap measured on the terminal sheets.
- Queue untick: `?view=home-queue&mode=off&queue_machine=`.
- Keyed sections, password keys, minted token box (terminal `.secret`),
  ago stamps (`set by <b>owen</b>`, lower-case data-labels), undo-last-change,
  the rollback key (`#dashupd-older-key`, one key for the picked bundle),
  `static/cc/dashboard_update.js`, offline "Try again", `static/cc/copy_value.js`
  labels ("copied", "Selected: press Ctrl+C"), sign in/out, recovery keys,
  restore form/result, `/partials/queue` -> `/partials/home-queue`, the
  capped transfer rows' tags. Five tests that were passing only because a
  `[ BRACKET ]` string was absent now assert the terminal tag/key instead
  (env password, counted capped row, getting ready, unheld row, stale-banner
  toast).
- Contrast: `--muted`, `--text-2` and `--red` on `--bg` / `--win-solid`
  (terminal.css) >= 4.5.
- AI pin: the scenario's change event now bubbles (the terminal script
  listens on the document, as a real pick does).
- PRODUCT (CSS): ui-dash-static-7 on terminal pages. The shell's `#cc-toast`
  sat 26 px up, over the stale banner's text. `terminal.css` adds
  `body[data-stale] .toast { bottom: calc(26px + var(--stale-h) + var(--cc-dock-h)); }`.

## Deleted tests
- `test_the_drawer_close_and_help_notes_are_not_border_red`: NOT deleted,
  rewritten. `.drawer-close` / `.help-file-note` were classic-only CSS; the
  test now pins that no terminal rule sets text in `--red-dim` / `--red-deep`
  except decorative `content:` glyphs (and the bench's unused `.br` class).
- None deleted outright.
