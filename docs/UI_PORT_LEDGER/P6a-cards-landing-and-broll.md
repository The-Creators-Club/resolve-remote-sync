# P6a: phase 6, first half (the /cards landing and b-roll), group `apps`

Builder P6a, 2026-09-25 (resumed from an interrupted first run). Plan:
`docs/UI_REDESIGN_PORT_PLAN.md` 1.4, 4.1, 5.4, 7.0, 7.1 row 6, review
rows 22, 23, 67, 142, 143, 220, 221, 226, 245. Nothing committed, no
version bumped.

## Built

### /cards landing
- `dashboard/templates/cc/cards_landing.html`: the landing on `cc/shell.html`.
  Three windows (`find`, `recent`, `episodes`), each with a real fold
  button; keys and toggle chips instead of the 16 bracket labels; every
  `cl-*` hook `static/cards_landing.js` reads kept beside the terminal
  class; plain forms (works with no script); close keeps the native
  `onsubmit` confirm (plan 1.4, wave 5); refusal and `?want=` notes; empty
  vault state; "Carry on with" key.
- `dashboard/static/cc/cards_landing.css`: new sheet on the cc tokens only
  (the classic `cards_landing.css` is untouched until phase 8). Nothing
  shifts: the clear key keeps its box while hidden, the fold-all keys keep
  their room in list view, the recent window dims during a search instead
  of leaving.
- `dashboard/static/cards_landing.js` (shared, one small branch): in the
  terminal look the recent window stays and gets `.cl-dim` while a search
  runs; the classic line `recent.hidden = searching || any === 0;` is kept.

### b-roll (`broll/web`)
- `static/index.html`: the phase 6 half of the head script (`html.cc` from
  the `apps` entry of `ccsync_ui_effective`, `split('; ')`, no regex
  literal); `data-cc-win` on the search line, folder tree, results and clip
  detail; `static/cc_spa.js` loaded before `app.js`.
- `static/cc_spa.js`: the shared SPA helper (windows with a fold button and
  a per-path fold store, bracket-free labels with the original kept for
  classic, tips on hover and on tap, `ccSpa.confirm` dialog), byte-identical
  with music's and youtube's copies. Inert unless `html.cc`.
- `static/app.js`: `syncDashboardLook` sets or clears `html.cc` from the
  topbar's `data-ui-apps` marker (authoritative both ways) and rewrites the
  cookie; `relayoutDetail()` opens the clip BESIDE the grid in the terminal
  look (detail moved into `#browse-layout`, `.cc-with-detail`, grid keeps
  its scroll), classic still replaces the grid. Re-run when the look
  changes under an open clip.
- `static/ingest.js`, `static/clientfolders.js`: all six confirms (large
  drop, model download, cancel batch, revoke link, new link, delete
  folder) go through `ccSpa.confirm` in the terminal look and the browser
  confirm otherwise (the same inline ternary music uses).
- `static/style.css`: the `cc-spa-common` block, byte-identical with the
  music and youtube sheets (P6b's), then b-roll's own block ("B-roll in
  the terminal look"): keys for the pager and icon buttons, cyan toggle
  squares, the search window, folder tree / results / clip as windows side
  by side (sticky tree and detail on wide screens; detail drops under the
  grid at 1100 px; one column at 760 px), grid and detail bottom padding
  that includes `--cc-dock-h`, the three panels as terminal drawers,
  toasts, 44 px coarse-pointer targets. Every rule under `html.cc`, so the
  classic app and the public share page (R22) are unchanged.

## Omitted controls / not built

- No backend tickets were needed for these two pages; no control omitted.
  Ingest retry-failed is kept (the bench omits it).
- `cards_pool.py`'s "Press [ OPEN ] to try again" is phase 7 (D8 wording).
- Not run (speed rules): the SPA census click pass with `html.cc` on and
  off, the sweep at 390/768/1440, the fold-survives-reload and tip-on-tap
  Chrome checks, screenshots.

## Departures

- b-roll adopts P6b's `cc-spa-common` block rather than its own copy of
  the same rules; the block's header still says "in the music and youtube
  sheets" (changing it would break byte-identity; P6b may reword it for all
  three at once).
- The b-roll terminal body test is a new file (`tests/test_cc_body.py`),
  shaped like P6b's but not identical to it.
- `broll/web/tests/test_hud_common.py` (P1's): the phase 1 scope test now
  stops at `cc-spa-common BEGIN`, exactly as P6b did for music.

## Tests (run once, at the end)

- `broll/web` (own venv): whole suite 724 passed (includes the new
  `test_cc_body.py`, 17 tests, and the touched `test_hud_common.py`,
  `test_ingest_ui.py`, `test_client_folders.py`, `test_mounted_prefix.py`,
  `test_theme_css.py`, `test_no_em_dashes.py`, w2 b-roll pins).
- `dashboard`: `test_cc_cards_landing.py` + `test_cards_picker.py`: 25
  passed, 4 skipped (terminal-only tests skip on the classic parameter).
- `node --check` on `app.js`, `ingest.js`, `clientfolders.js`: ok.

## Hand-offs

- P6b: add b-roll's sheet to `SHEETS_WITH_COMMON` in music/ytdl
  `test_cc_body.py` if you want all three compared there (b-roll's own test
  already compares its block with music's); reword the block header for
  three sheets in all three copies at once if you like.
- Sweep / census owner: `/broll/` with `html.cc` on and off, `/cards/`
  in the static census.
