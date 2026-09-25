# P7: phase 7, the copy sweep (UI_REDESIGN_PORT_PLAN.md 2.6, D8, R12, 7.1 row 7)

Builder P7, 2026-09-25, worktree branch `ui-port`. Not committed, no version
bump. Two sittings: an earlier P7 run did the rewrites and the new test file
and was cut off before it wrote this ledger or ran the pins; the second run
checked that work, fixed the four pins it broke, and wrote this.

## Built

**Python copy to D8** (a control is named by its key label in sentence case,
in double quotes: `press "Resume"`). Variant-neutral: it reads the same
beside a classic `[ RESUME ]` key and a terminal key.
- `alerts.py`: every fix line (breaker, fleet halt and its expiry, silent
  computer, feed stale, moved project dirs, file moves, versions behind,
  retracted build, weekly send, jobs abandoned/pinned, upgrade refused,
  rollout stalled, ytdl stale, red unexplained, delivery budget). Page names
  are sentence case ("Sync status", "Settings, Packages").
- `notices.py`: collector fixes name "the Collector panel" (no "under the
  computers table", the panel moves in the terminal look), the Dashboard
  panel's "Update now", "Resume", the file-move key.
- `invariants.py`, `protection.py` (plus `weekly_lines()`: `LABEL: title`,
  never `[ LABEL ]`), `recovery.py` (Stop all syncing, Create & link, Undo
  this change, the tray's Undo last fix), `cards_pool.py` (Open, Close),
  `api.py` (Unarchive, Use this folder, Forget), `ui.py` (CHIP_HELP Resume
  lines, the halt refusal; `_health_rows` `detail_label` values are plain
  `Notices`/`Alerts`/`Invariants`/`Protection`), `collector.py`,
  `release_feed.py` ("[ APPLY ]", which no page had, is now "Update now" in
  the Dashboard panel), `setup_engine.py` (the vendor section; the doubled
  "(optional)" on the NAS task title removed).
- File-move label is "Move on the server and on every computer" in
  `alerts.py`, `notices.py` and `docs/FILE_MOVES.md` (R12).
- `NOTICE_KINDS`: `href_label` plain (`Download crash reports`, default
  `Take me there`); classic `partials/notices.html` and `admin_health.html`
  wrap as `[ {{ label | upper }} ]`, so classic renders exactly as before;
  the cc templates (P5's `cc/admin_health.html`, `cc/partials/health_notices.html`)
  use `cc_unbracket`.
- `tools/publish_latest.py`: `"Check now" > "Publish"`.
- `docs/HOW_IT_WORKS.md`, `docs/EDITOR_SETUP.md`: zero bracket controls;
  page-map rows name destinations ("the projects list", "Stop all syncing"
  on Settings > Users); no "sidebar", "three bars", "top left", "above the
  grid"; the problems panel sentence names both variants.
- `test_sweep_2026_09_04_copy.py`: `VOCABULARY_FILES` gains recovery,
  cards_pool, release_feed, account_ui; the two `[ MOVE ON ... EVERY MACHINE ]`
  `VOCABULARY_ALLOWED` entries deleted; the setup-task page-name pin reads
  sentence case.
- Legal titles: checked, none carries an em dash (already fixed upstream).
  The EULA version marker is untouched.
- The recovery "the dashboard has no button for this yet" sentence is gone
  from the source (grep finds nothing).

## Tests (dashboard venv, run once at the end)

- NEW `dashboard/tests/test_copy_sweep_phase7.py`: the Python bracket scan
  over every module under `src/ccsync_dashboard` (AST, docstrings excluded,
  f-strings joined, SQL skipped) with an EMPTY allow-list pinned at 0, its
  self-test, a check that cards_pool/recovery/release_feed are scanned; each
  D8 label present in its module AND a `[ LABEL ]` key on its classic
  template (34 rows; the terminal half checked when the cc twin exists);
  file-move vocabulary; NOTICE_KINDS plain labels and the classic wrapping;
  the two shipped docs free of brackets and moved-region words.
- Pins rewritten this run: `test_project_setup.py:454`, `test_health_page.py:112`,
  `test_cards_pool.py:547`, `test_setup_engine.py:881`. Earlier run:
  `test_alerts.py`, d-diag, `test_notices_sweep_wave2.py`, `test_protection.py`,
  `test_sweep_2026_09_04_copy.py`, `tools/tests/test_publish_latest.py`.
- Run: copy_sweep_phase7, d-ops, project_setup, health_page, packages,
  sweep_2026_09_04_copy, alerts, d-diag, notices_sweep_wave2, protection,
  cards_picker, cards_pool, report_endpoint, invariants, notices, api,
  setup_engine, setup_routes, help_page, no_em_dash: 1504 passed, 4 skipped,
  5 failed; the four pins fixed and their files rerun: 198 passed. The fifth
  failure is not phase 7 (below). `tools/tests/test_publish_latest.py` 21 passed.

## Hand-offs

- **P2**: `templates/cc/partials/fleet_grid.html:102` says "sync lanes";
  `test_sweep_2026_09_04_copy.py::test_no_retired_word_in_rendered_copy[fleet_grid.html0]`
  fails on it. Say "sync" or "upload / proxy download / folder sync".
- `TERMINAL_GAPS` in the new test (skips, delete each when the key lands):
  `cc/partials/admin_jobs.html` has no "Show finished" key (P4);
  `cc/partials/protection.html` builds "I have backed it up" / "Record a
  restore" from a tuple (P5); `cc/partials/project_setup_panel.html` says
  "Create and link", not "Create & link" (P3).
- P2's `home_problems` (and any other cc template drawing `href_label` or
  `detail_label`) should use `cc_unbracket` or the plain value; the label is
  plain now.

## Omitted / departures

- Classic JS labels (`site_settings.js`, `copy_value.js`, `pwa.js`,
  `setup.js`) keep brackets: plan 3.5 forks them into `static/cc/` in their
  pages' phases and classic keeps its output until phase 8.
- `setup_engine` run labels (`DO IT`, `CHECK NOW`...) unchanged: `setup.js`
  wrapping stops in the cc fork (P4), and `test_setup_engine.py:902` /
  `test_setup_routes.py:73` pin the values.
- Operator console text outside 2.6 left bracketed: `tools/publish_package.py:370`
  (`[ MAKE CURRENT ]`) and `tools/release_key.py:281` (`[ I HAVE BACKED IT UP ]`,
  pinned by `tools/tests/test_release_key.py:102`). Candidates for phase 8.
- Page names inside a few alerts fixes stay uppercase where they were
  (`SETTINGS, PACKAGES` in two versions-behind lines): not brackets, not in D8's scope.
