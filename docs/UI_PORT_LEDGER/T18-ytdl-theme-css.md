# T18 - ytdl/web tests/test_theme_css.py (2026-09-25)

## What broke

The four-sheet theme-common contract (`FLEET_STYLESHEETS`) read
`dashboard/static/style.css`, which the collapse (C-collapse.md) deleted with the
classic look.

## Converted

- `FLEET_STYLESHEETS["dashboard"]` now points at `dashboard/static/cc/terminal.css`,
  the dashboard's only stylesheet and the one carrying the theme-common block
  (lines 423-593). The failure message names the new path. Same intent: the
  block must exist exactly once, be terminated and non-empty in all four sheets,
  and be byte-identical (newline-normalised) across them. Nothing loosened.
- By the time T18 started, this exact edit was already in the worktree (the same
  hunk is in broll/web and music/web's copies, from a parallel converter). T18
  verified it rather than re-editing: `dashboard/static/style.css` is gone,
  `terminal.css` carries one BEGIN/END pair, and the four blocks match.

## Deleted tests

None.

## Product fixes

None needed.

## Result

`ytdl/web`: `tests/test_theme_css.py` 36 passed (dashboard venv).
