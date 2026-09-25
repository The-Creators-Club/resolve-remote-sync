# P6b: phase 6, second half (music and youtube bodies, group `apps`)

Builders P6b (two sessions), 2026-09-25, worktree branch `ui-port`. Nothing
committed, no version bumped. Plan: `docs/UI_REDESIGN_PORT_PLAN.md` 7.1 row 6,
4.1, 4.3, 5.4, 7.0. Bench: `dashboard/design/music.html`, `youtube.html`.

## Built

- **First paint** (`music/web/static/index.html`, `ytdl/web/static/index.html`):
  the phase 1 head script also sets `html.cc` on `documentElement` when the
  `ccsync_ui_effective` list holds `apps` (read with `split('; ')`, no regex
  literal). The loader's `syncDashboardLook()` (phase 1) is then
  authoritative from the topbar's `data-ui-apps` in both directions.
- **The SPA helper `cc_spa.js`**, byte-identical in `music/web/static/`,
  `ytdl/web/static/` and `broll/web/static/` (P6a ships the b-roll copy):
  windows from `[data-cc-win]` (a real fold button, per-path store
  `ccsync.spafold:<path>`, `[data-cc-own-fold]` keeps the app's own toggle),
  unbracketed labels (whole `[ X ]` and `[-]/[+] X` controls read as the
  sentence-case label; inline `[ X ]` in running text reads as a quoted
  label; originals restored when the look goes off, so classic code and the
  28 `test_static_app.py` literals are untouched), tips on hover and on tap,
  `ccSpa.confirm()` through a `<dialog>`. Every behaviour gated on `html.cc`.
  Served by a sibling route `GET /cc_spa.js` in `musicweb/main.py` and
  `ytdlweb/main.py`; loaded before `app.js`.
- **Windows**: music `feel`, `tempo_and_length`, `tracks` (`#results`), one
  per facet (set in `paintFacets`); ytdl `before_you_download` (`#attest`),
  `progress`, `search_terms` (`#terms`), `waiting_for_you` (`#waiting`),
  `queue`; ytdl's review, downloads, recent searches and history keep their
  own fold (`data-cc-own-fold`), header drawn as the bar.
- **CSS**: `cc-spa-common` block, byte-identical in the music and ytdl sheets
  (tokens re-pointed at the terminal palette under `html.cc`, windows, bars,
  fold, tip, dialog, keys, fields, chips, status, toast, coarse-pointer 44 px,
  phone 12 px floor and 16 px fields, reduced motion), then each app's own
  block. Every rule under `html.cc` / `html:not(.cc)` / `.cc-spa-*`; nothing
  in the classic rules above changed; placed after hud-common.
- **Confirms**: music ingest (model download consent, cancel batch) and ytdl
  (discard parked review, discard search) use `ccSpa.confirm` when the look
  is on, the browser confirm otherwise (callers awaited).
- Fix this session: ytdl `loadDashboardTopbar`'s `finally` guarded against
  a missing `documentElement` (the phase 1 loader broke all 95 node-harness
  tests in `test_static_app.py`).

## Omitted controls / not built

- No control removed. No backend ticket needed for music or youtube.
- ytdl health: the six `.rstatus` spans stay separate spans in the header
  row (restyled compact), not merged into one element as the bench draws it
  (markup and `app.js` fill them by id).
- Not run (speed rules): the SPA census (`census_click.js`), the sweep at
  390/768/1440, screenshots, the per-SPA required-id list, fold-survives-
  reload and tip-on-tap Chrome checks.

## Departures

- Terminal labels come from a runtime text transform in `cc_spa.js`, not
  from edited JS strings, so classic output (and its pins) is byte-for-byte
  what it was; the node label test is the terminal twin.
- `test_hud_common.py` (P1's, music and ytdl): the "phase one rules are
  scoped" scan now stops at `cc-spa-common BEGIN`; phase 6's rules are
  pinned by `test_cc_body.py` instead. b-roll's copy of that test is P6a's.

## Tests (once, at the end)

- `music/web` (own venv): `test_cc_body.py` (new) + `test_hud_common.py`,
  `test_theme_css.py`, `test_mounted_prefix.py`, `test_no_em_dashes.py`,
  w2 music-ytdl, `test_ui_says_what_it_knows.py`, `test_ingest_ui.py`,
  `test_one_vocabulary.py`, `test_plain_words.py`: 223 passed.
- `ytdl/web` (dashboard venv): `test_cc_body.py` (new) + `test_hud_common.py`,
  `test_theme_css.py`, `test_mounted_prefix.py`, `test_no_em_dash.py`,
  w2 music-ytdl, `test_says_what_it_knows.py`, `test_static_app.py`,
  `test_one_vocabulary.py`: 322 passed.
- `node --check` on music `app.js`/`ingest.js`, ytdl `app.js`, `cc_spa.js`: ok.

## Hand-offs

- P6a: `cc_spa.js` must stay byte-identical across the three apps
  (`test_cc_body.py` compares every copy that exists); b-roll's
  `test_hud_common.py` scope scan will need the same stop marker if its
  phase 6 rules sit after hud-common. The test harness stubs
  `window.addEventListener` (the helper now listens for scroll).
- Central gate: the census, sweep and screenshots listed above.
