# INT2: integration after the fixes, the collapse and the test conversion

Integrator, 2026-09-25, worktree branch `ui-replace`. Nothing committed, no
version bumped. Inputs: the review-fix ledgers (F-*, V-*), C-collapse and the
18 test converters (T1..T18).

## Suites (worktree code, main venvs), final run

| Suite | Result |
|---|---|
| dashboard (211 files, 12 parallel shards) | **5923 passed, 9 skipped, 0 failed** |
| broll/web | 723 passed |
| music/web | 688 passed, 13 skipped |
| ytdl/web (dashboard venv) | 1058 passed |
| tools (dashboard venv) | 459 passed |
| companion | 8054 passed, 4 skipped, **2 failed, not this branch's** (below) |
| server (Git Bash) | 726 passed, 2 skipped, **1 failed, environmental** (below) |
| onboarding | 556 passed, 2 skipped |
| bench | 175 passed, 1 skipped |
| broll/indexer | 831 passed |
| music/indexer | 50 passed, 1 skipped |

The first dashboard pass had 3 failures. All are fixed (below).

### Failures that are not this branch's

- **companion, 2 in `test_sweep_2026_09_04_copy.py`** (`app.py` " lane B
  via=", `sync/rclone_lane.py` "lane B parked"). The worktree was cut from
  `d920ff7`; `main`'s `77916b8` ("gate fixes (vocabulary in two companion
  messages ...)") already fixes exactly these two strings. This branch does not
  touch `companion/`, so they go away when it is rebased onto or merged with
  `main`.
- **server, `test_music_deploy.py::test_the_dry_run_says_how_big_the_push_is`**.
  It passes in the main checkout. The worktree's `music/web/data/` has no
  `text_encoder/` or `audio_encoder/` (they are gitignored model folders), so
  the dry run has nothing to measure in MB/GB. This is about the checkout, not
  the code.

## Fixed

1. `tests/chaos/test_fault_injection_wave2.py` `COSMETIC_DISABLES`: the two
   `cc/...` twin keys (`site-undo-btn`, `dashupd-older-key`) now name the
   moved files (`admin_settings.html#...`,
   `partials/admin_dashboard_update.html#...`). The two dead `cc/` twins of
   the other entries were removed. The setup entry now names
   `static/cc/setup.js`, because the classic `setup.js` was deleted.
2. `tests/test_every_template_renders.py`: the "classic look" phrase check
   failed on `/help`. For an admin on a dev checkout, `/help` lists the docs
   tree by title, and the `docs/UI_PORT_LEDGER/` titles say "after the classic
   look was retired". The check now cuts the doc-index links out of `/help`
   before it looks. A doc title is data, not product copy. The `/ui/preview`
   check still reads the whole page.
3. `static/cc/components.css` `.filenav a`: added `overflow-wrap: anywhere`.
   At 1440, the `/help` documents list scrolled sideways by 293 px. Long
   unbroken doc titles (such as "comp-app - the companion app core (app.py,
   config/site/identity...)") pushed past the side column. It is clean at
   1440, 768 and 390 now.
4. Comments only: `htmx_errors.js`, `pwa.js` and `tab_memory.js` said
   "base.html" where the loader is now `shell.html`. `shell.html` still loads
   pwa.js deferred and before htmx, so the contract in `pwa.js` still holds.

## Leftover-reference grep

A grep over non-test, non-docs code for `ui_variant`, `ui_terminal_groups`,
`ui_preview`, `X-CC-UI-Want`, `cc/*.html` template names, `base.html`,
`static/style.css`, `mobile.css` and `ui_groups.js` finds only these:

- the deliberate `RETIRED_KEYS` handling (`site_store.py`, `app.py`)
- `ui_assets.py`'s history docstring
- `shell.html`'s header comment
- the SPAs' deliberate clearing of the `ccsync_ui_effective` cookie
- b-roll's own `static/style.css`, which is the SPA's own sheet

## Live boot (seeded dev server, headless Chrome)

`tools/mobile_sweep_seed.py`'s seed, with `DASH_DEV_INSECURE=1`, known
passwords for the admin (`owen`) and an editor (`jsmith`). Every mount was on:

- `/broll`, with `BROLL_*` pointing at a temp data root
- `/music`
- `/ytdl`, with `site_feature_youtube_download`
- `/cards`, the MulticamPipeline checkout on an empty vault

A client folder was minted with `client_folders.create_folder` so that
`/broll/share/<token>/` could be loaded.

Scope of the sweep:

- **Pages**, loaded at 1440, 768 and 390, as admin, as editor, and signed out
  where the page allows it. The pages were `/`, both projects, `/transfers`,
  `/project-setup`, `/installer`, `/help`, `/account`, `/admin/settings`,
  `/admin/users`, `/admin/assignments`, `/admin/packages`, `/admin/jobs`,
  `/admin/audit`, `/admin/health`, `/admin/invariants`, `/admin/protection`,
  `/admin/alerts`, `/admin/alerts/preview`, `/admin/recovery`, `/offline`,
  `/download`, `/setup`, all 7 `/go/<panel>` links, `/cards`, `/broll/`,
  `/music/`, `/ytdl/`, `/login`, `/broll/share/<token>/` and a gone share
  token.
- **Partials**: 37 partial URLs, including the parameterised ones, fetched
  over HTTP with the page headers, as admin and as editor.

Checks on every load:

- no 5xx in any document or any subrequest (htmx loads included)
- console errors and exceptions
- page-level and element-level sideways scroll, outside `.scroll-x`
- bracket labels in visible text and in title, placeholder and aria-label
- em dashes

Results:

- **No 5xx anywhere.** All 37 partials answer 200 for the admin. For the
  editor, the admin-only partials answer 403 and the rest answer 200.
- `/partials/fleet` without `X-CC-UI` answers 200, empty, `HX-Refresh: true`
  for both roles. This is the stale-page gate.
- **No console errors or exceptions on any dashboard page.** Only the
  expected ones remain:
  - the editor's 403 on `/admin/*`
  - a 404 from `/download/windows`, because no package is published in the
    seed
  - a 404 from the gone share token, which draws the designed "gone" page
  - `/music/` logs one CORS refusal from `127.0.0.1:8899/music/status`. That
    is the base rig's real companion refusing an origin it was not configured
    for (the loopback guard doing its job), not the page.
- **No sideways scroll** on any page at any width, after fix 3.
- **No bracket controls.** The only bracket text is not a control:
  - the alert-mail preview's plain-text `<pre>`, which shows
    `[breaker_tripped]`-style kind tags in the email body
  - `/admin/recovery` quoting the site.toml section `[tree]` in its
    no-snapshot sentence
- **No em dashes in product copy.** The only ones are doc titles in `/help`'s
  documents list for the admin: repo docs such as APPLIANCE_INSTALL.md and
  the bug-hunt ledgers. Docs are exempt, and an editor's customer-facing set
  shows none.
- Screenshots of home, settings, music and cards at 1440 and 390 look right:
  the terminal chrome, the HUD, and the phone tab bar on the SPA.

## Left

- The companion and server items above need no change on this branch. They
  should be re-run after it is rebased onto `main`.
- The installer PowerShell and macOS shell tests were not run. This branch
  touches nothing under `installer/`.
