# Porting the CC Terminal redesign to the live dashboard

Written 2026-09-25 from the owner's ask the same day: "run a deep audit of
how this new UI will be ported to the live site, once the plan is complete
run multiple adversarial waves against it". This is the audit and the plan.
The adversarial waves are run against THIS document.

- The design: `dashboard/design/` (README.md, BUILDER_BRIEF.md with its round 2
  rules, `cc-terminal.css`, `cc-components.css`, `shell.js`,
  `issues-variants.js`, `css/*.css`, 28 pages). Committed as f9d5176.
- The product: `dashboard/templates/` + `partials/` (Jinja + htmx),
  `dashboard/static/`, `ui.py`, the topbar the three SPAs inject, the
  `/cards` landing page, the PWA, the share page, and every test that pins
  markup, copy or CSS.
- Measured against the tree at 823c9c9, plus the uncommitted account-page
  work in progress on 2026-09-25 (`docs/ACCOUNT_PAGE_FEATURES.md`: the new
  `account*.py`, `templates/account.html`, `partials/account_*.html`,
  `static/account.js`, and edits to `topbar.html`, `fleet_grid.html`,
  `admin_users.html`, `admin_audit.html`, `plan_changes.html`,
  `cards_landing.*`, `style.css`, `mobile.css`). `ui.py` line numbers move
  while that work lands, so this plan names routes by URL and functions by
  name.

What the owner approved and asked for (README.md, BUILDER_BRIEF.md round 2):
the terminal look; nothing shifts (scrollbar gutter always reserved, one
Settings width, controls keep their size); tags are a square plus a
lowercase word; every window folds; tooltips; pickers, dropdowns and short
wizards instead of long lists; no `[ bracket ]` controls; no hand-written
note; site-style scrollbars.

---

## 0. The verdict in ten lines

1. The port is mostly CSS and templates, but it is NOT a pure restyle.
   Several bench pages invent behaviour, which needs backend work (section 5).
   A few bench pages also move panels between pages (collector, notices and
   diagnostics go from home to Health; project roots go from home to the
   project page), and a lot of Python copy names moved or renamed controls.
2. **The class names collide.** `.rule`, `.stack`, `.main`, `.side`,
   `.toast`, `.lane`, `.form`, `.inline`, `.radio`, `.chip`, `.muted`,
   `.dim` and `.red` mean different things in `style.css` and in the bench.
   Layering the bench sheets over `style.css` does not work. A page is
   either classic or terminal, never both.
3. **The topbar is the hard part.** It is one partial served to five
   surfaces: every dashboard page, plus `/broll`, `/music` and `/ytdl`,
   which inject it with `innerHTML` (so no script runs in it) and paint it
   with their OWN stylesheets. It goes first, and it is script-free by
   construction.
4. **Tests forbid the new HUD.** `test_topbar_partial.py` and
   `test_theme_css.py` assert that the bar holds no module links (the
   owner's 2026-08-18 redesign). The bench puts them back in the bar. That
   is an owner decision (D3), and those tests change in the same commit.
5. There is **no light theme and no theme toggle** in the live product.
   `style.css` declares `color-scheme: dark`. The question does not arise
   unless the owner wants one (D1).
6. Fonts must be self-hosted (the dashboard runs on a tailnet and must work
   offline). None ship today. JetBrains Mono and Orbitron are both OFL.
   Drop Space Mono, which is only a TUNE option.
7. TUNE, the bench strips (`.bench`, "preview as", "mark what is new") and
   the issue-variant switcher never ship. TUNE's current values become fixed
   tokens, taken from the owner's "copy settings" output (D5).
8. The PWA serves `/static/*` stale-while-revalidate. Unless the terminal
   CSS has new, versioned URLs, the first load after a deploy paints new
   HTML with the old stylesheet.
9. 328 bracket literals across 61 dashboard test files, plus the four
   byte-identical `theme-common` blocks and their eight tests, pin the
   markup. Classic stays the default for every customer until phase 8, so
   **classic pins are kept, not rewritten**: each phase ADDS terminal
   assertions beside them, run through a per-test variant switch (7.1,
   phase 0), and classic pins are deleted only with the classic templates.
10. Recommended mechanism: a **template overlay** (`templates/cc/`) behind a
    per-page-group site setting and a three-way per-browser cookie. The
    owner can look at a ported page group on the live fleet before anybody
    else sees it, and taking the group off the setting is the rollback.
    Phases go chrome first, then home and project, then the rest, then a
    copy sweep, then deleting the classic templates (section 7).

---

## 1. Inventory: live file to bench page

"Bench" is `dashboard/design/<page>.html`. "BACKEND" means the difference
needs a new route or new view data. "UI" means it is presentation only.
The details behind every row are in section 5.

### 1.1 The shell (every page)

| Live | Bench | What differs |
|---|---|---|
| `templates/base.html` | `shell.js` `page()` + each page's `<head>` | Bench loads Google Fonts, `cc-terminal.css` and `cc-components.css`, and draws the HUD, dock, toast and TUNE from JS. Live is server-rendered. It has the CSRF `<meta>` and `hx-headers`, the manifest and PWA tags, five deferred scripts, the inline details/popover keeper, the deep-link scroller, the fleet-halt banner poll (60 s) and the chip sheet. **All of it stays.** The new shell is a new template (section 2.5), not an edit of this one. |
| `partials/topbar.html` (included by base and served at `/partials/topbar`) | `shell.js` `hud()` + `.dock` + `.snav` | Live: a `[ ≡ ]` menu button that opens a popover drawer holding every module link; the brand; the problems and alerts chips (absent at zero); the stamp (polled every 30 s); `[ ? ]`, the user, the gear and SIGN OUT. The account work adds `/account` links. Bench: brand plus the CC swoosh, `>word` links for sync, b-roll, music, youtube, cards, transfers and settings; problems and alerts counts (always shown); the user as a link to the account page; a Taipei clock; on phones a bottom dock (sync, b-roll, cards, transfers, more). **The bench has no sign out, no sign out everywhere, no installer, no help and no stamp.** Those must survive (section 3.4). |
| `partials/settings_nav.html` | `shell.js` `settingsStrip()` + `.snav` | Same three groups and the same keys, from `ui.SETTINGS_NAV_GROUPS`. Bench labels are lowercase with a `>` prefix and no brackets. Live becomes one row that scrolls sideways (`.scroll-x`) below 600 px. The bench wraps. |
| `partials/stamp.html` | `.head .sub` "updated 3 s ago" | Bench moves the stamp into each page's head line. Live polls it in the topbar. Keep the poll and move the slot (section 3.3). |
| `partials/fleet_halt_banner.html` | `.alertline` | Restyle. It keeps its own load plus 60 s poll. |
| `partials/chip_sheet.html` + `htmx_errors.js` block 2 | shell.js `tooltips()` | Two mechanisms for one job. Merged in section 3.2. |
| `partials/sidebar.html` + `editor_switcher.html` (every page) | home and project only: `ticking_for` + `projects` windows (`.tree`) | Bench: only home and project have the project tree; settings, transfers, installer and project-setup have none. Bench adds a computer picker next to the editor picker, a find box, and a size per project. Live rails the tree on every page and turns it into a bottom sheet (`#projects-sheet` popover) on phones. The classic sidebar (tick checkboxes, its 30 s poll, the TICKING FOR `?as=` form, the phone sheet) is included by 17 page templates (`fleet`, `project`, `account`, `transfers`, `project_setup`, `installer` and every `admin_*`). **Decision D17 (wave 4):** the terminal tree and TICKING FOR live on home and project only, as the bench draws them; every other cc page drops the sidebar, and phases 3, 4 and 5 each list census allow-list entries for the toggle POSTs, the `/partials/sidebar` poll and the `as` GET form as moves to `/` (R1's structured moves, checked on the destination), and the phone sweep confirms one tap from every page reaches the tree (the dock's sync link). |
| `static/style.css` (2093 lines) + `mobile.css` (393) | `cc-terminal.css` (532) + `cc-components.css` (237) + `css/*.css` (1725) | Section 2. |

### 1.2 Everyday pages

| Live template(s) and route | Bench | What differs |
|---|---|---|
| `fleet.html`, `GET /`. Partials: `sidebar`, `notices` (60 s), `fleet_grid` (15 s, includes `collector_health`), `plan_changes` (60 s), `transfers` (2 s), `queue_section`/`my_queue` (10 s), `project_roots` (30 s) + `project_roots_browse`, `#fleet-diagnostics`. | `home.html` | Largest change. Bench: head keys **Stop the fleet** (UI, the route exists on Users) and **Check now** (BACKEND). A stale alert line. Four **readouts** (online, moving, problems, in sync; UI, aggregated in the view builder). **problems.log** (notices restyled, plus **dismiss all**, BACKEND). **computers** as fixed-height rows: three lane meters **with a percent per lane** (BACKEND, lane chips carry no percent), issues listed inline worst first (UI, from the chips behind today's `[ DETAILS ]`), version with "N behind" (dropped in wave 6: the package store forgets deleted versions, 5.1), and collector age in the bar (UI). A transfers window of only what is moving, and plan_changes without the UNDO column. **Lost on the way:** each computer's `fleet_headline` line (the muted "Nothing ticked for this computer" sentence included; wave 6, 5.1), the project cards overview, about ten fleet banners (`fleet_grid.html` lines 37-130), everything behind `[ DETAILS ]`, `[ RESUME ]`, `[ ASK THIS COMPUTER WHY ]`, `[ READ THE ANSWER ]`, LOST COMPUTERS + `[ FORGET ]`, the queued and history halves of the transfers window, the SYNC QUEUE panel, PROJECT ROOTS (moved to project), plan-change `[ UNDO ]`. Each needs a home before home ports (section 5.1). |
| `project.html`, `GET /project/{slug}`. Partials: `project_detail` (10 s), `bins` (load + 5 s), `missing_files`, `sidebar`. | `project.html` | Mostly UI. Sections reordered; **project_roots** window added (UI, the partial and routes exist); "N computers share it"; the missing-files list opens inline; the confirms are dialogs, except the file-move form, which keeps its own computed `hx-on::confirm` and native `window.confirm` (3.2, wave 4). Sizes in the tree are BACKEND. Every hx-post in `project_detail.html` (tick, machine, mode, links, move, reissue, undo, missing) must keep its URL and `#project-detail` target. |
| `transfers.html`, `GET /transfers` + `/partials/transfers` (load + 2 s) | `transfers.html` | UI. Bench drops the sidebar and shows the machine under the editor (check that `t.machine` is in the row; if not, BACKEND). The editor-only safe-to-close line is kept but reserved in height on the admin view. |
| `project_setup.html` + `partials/project_setup_panel.html`, `GET /project-setup` | `project-setup.html` | UI. Narrow page with no sidebar. The "already set up" state links to `project.html#roots` instead of the home page's PROJECT ROOTS box, which follows from the roots move. |
| `installer.html`, `GET /installer` (and `/download` fallback) | `installer.html` | UI. Drop the bench's "/download explainer" window; it is documentation, not product. |
| `account.html` + `partials/account_*.html` + `static/account.js` (being built NOW in the classic look, `docs/ACCOUNT_PAGE_FEATURES.md` §6) | `account.html` | The spec says the page ships classic and the port restyles it later. The port restyles; it adds nothing. The bench's "preview as" and "mark what is new" strips never ship. |
| (none) | `user.html` | NEW admin page, one person. BACKEND end to end (section 5.2). |
| `login.html`, `GET/POST /login` | `login.html` | UI. Bench is bare (no HUD). Live extends base, so the topbar shows. The bench's "throttled" state is just another `error` string. |
| `offline.html`, `GET /offline` (precached by `sw.js`, rendered anonymous) | `offline.html` | UI. Bare page with a "no connection" LED. It must reference only precached, versioned assets (section 6, R9). |
| `help.html` + `help.py`, `GET /help`, `/help/{doc}` | `help.html` | UI. It has the strip only for admins, the same as live. |
| `setup.html` + `static/setup.js`, `GET /setup` | `setup.html` | UI plus JS. A step strip and folded windows with a status per step, prefilled "Your studio" (from `GET /api/v1/admin/site`, which exists), and the doubled "(optional)" fixed. `setup.js` builds its buttons and chips as `"[ " + label + " ]"` strings (section 3.5). |

### 1.3 Settings pages (all get `settings_nav`; the bench drops the sidebar)

| Live | Bench | What differs |
|---|---|---|
| `admin_settings.html` + `partials/android_settings.html` + `static/site_settings.js` (894 lines, builds AI PROVIDERS in JS) | `site.html` | Five tabs instead of one long scroll (UI; the tabs are display only. Only the "studio and tree" and "features" panels are inside `#settings-form`, as live: AI providers (the JS-built section with `#ai-providers`, `#ai-preference`, `#ai-cli-enabled`), export and history (`<form id="settings-import-form">`) and Android (`<form id="android-form">` with its `#android-settings` target) stay sibling panels with their own forms and ids, because a `<form>` nested in `#settings-form` is dropped by the parser and its fields would join the general save, which `site_store.validate` refuses for any key outside `KEYS`. Every field keeps its live `site_store.KEYS` name: the bench's indexer radios are `name="tier"`, live is `indexer_model_tier`; wave 3). **AI providers:** only the ones that are set up, a manage menu per row, and ADD NEW opening a picker then a short wizard per provider (mostly UI over the existing `ai_providers`/`cli_tools` routes; the "how to get a key" copy is new). **who_answers:** three consumers, where live shows one (UI if derived in JS; BACKEND if it should be one server rule). Import and undo use a dialog instead of `window.confirm`. `site_settings.js` builds 21 bracketed labels itself. |
| `admin_users.html` + `admin_users`, `admin_sessions`, `admin_report_tokens`, `minted_secret` (oob), `fleet_halt`, `admin_suspend_button` | `users.html` | Columns match. Names link to `user.html` (BACKEND). Head anchors (UI). Four polls: users 30 s, sessions load + 30 s, tokens load + 60 s, halt load + 60 s. Every form targets `closest .admin-users-box` or its own id, outerHTML, so the frame problem in section 3.1 applies. |
| `admin_assignments.html` + `static/assignments.js` (no htmx) | `sync-plans.html` | The computer select is shown before a person is chosen, filled client-side (UI, the page must emit the person-to-machines map it already builds in `_picker`). Free space and proxy size become visible text (UI, today they are `data-*` only). **Confirms stay native** (wave 5): ARCHIVE is a plain `method="post"` form with `onsubmit="return window.confirm(...)"` (`admin_assignments.html:171-173`) and `assignments.js:137,274,402` calls `window.confirm` inside checkbox handlers; `htmx:confirm` never fires for either, and an `hx-confirm` on a non-htmx form is ignored, so the port keeps these native confirms verbatim (3.2). |
| `admin_packages.html` + `partials/admin_packages.html` (30 s) + `partials/admin_dashboard_update.html` (load only) + `dashboard_update.js`, `confirms.js` | `packages.html` | **UPDATE ALL** panel (BACKEND, section 5.3). A **roll back to…** dropdown on each served row (UI over `POST packages/current`) is ADDED, but it does not replace the "OTHER VERSIONS HELD" list (wave 6): each held build is a `package_row` (`admin_packages.html:92-185`, inside `<details data-key="pkg-other">`, :514) carrying its canary/soak evidence line, PUSH TO ONE COMPUTER with its own computer select, MAKE CURRENT, the typed override (`force=1`, `confirm` typed as that version, and an `hx-confirm` about the missing signature ONLY when that version is unsigned), DELETE to the trash, and the CR-335 refusal keyed by `error_for`, none of which a select option can carry (`hx-confirm` is static). So the select lists only versions a plain MAKE CURRENT would accept (signed, not retracted, soaked or `ever_current`, file present), and every held build keeps a folded per-version row (`data-key` kept) with all six (5.3). Its "goes to the trash for 30 days" wording is true (both delete routes call `_trash_package_file`); the live confirm undersells it. The dashboard's own rollback becomes a select plus a key, and the apply-older and image-rollback lists stay two separate controls (a JS change with a test per path, section 5.3; `dashboard_update.js` reads `data-dashupd-*` from `evt.target` itself, section 3.3). |
| `admin_jobs.html` + `partials/admin_jobs.html` (self-poll 15 s, outerHTML, carries `?finished=1`) | `jobs.html` | UI. Person links (BACKEND via user page). Dialog confirm. |
| `admin_audit.html` + `partials/admin_audit.html` (not polled; `q` filter, 200 rows) | `history.html` | UI. The "pager" is a text line; real paging would be BACKEND (`fetch_audit` offset). Not needed. |
| `admin_health.html` (not polled) | `health.html` | Tabs: open findings, problems the server found (`/partials/notices` exists), collector (**BACKEND**: no standalone collector route; its context is built inside `fleet_grid`), what computers said (`/partials/admin/diagnostics` exists). Anchors `#server-notices`, `#fleet-diagnostics` and `#fleet-collector` are named by `db.py`, `notices.py`, the topbar chip and `collector_health.html`. Move them with the panels. |
| `admin_invariants.html` + `invariant_checks.html` | `invariants.html` | UI. Head counts derived from existing states. |
| `admin_protection.html` + `protection.html` | `protection.html` | UI. |
| `admin_alerts.html` + `partials/admin_alerts.html` | `alerts.html` | UI. Head keys; four windows, one save. **Four forms, not one** (wave 6): the bench opens `<form id="alerts-form">` (`design/alerts.html:58`) with the password body `#pw` (:113, its store and clear keys) and the server-check run key (:95) inside it and bare field ids (`tz`, `hb`, `host`); live has four sibling forms (save :61-150, `/partials/admin/alerts/triage/run` :173-176, `/partials/admin/alerts/password` with `name=password` and `name=clear` :182-201, test :204-207), and `ui.py:2525` keeps only `alerts.SETTING_KEYS`, so a password folded into the save form is dropped while the page says "saved.". The password, run and test forms stay siblings outside the save form; a window may visually hold another form's control through the `form=` attribute, never a nested `<form>`; every field keeps its `alerts_*` name from `SETTING_KEYS`. Phase 5 tests: no nested `<form>` on the cc Alerts page; SET PASSWORD posts to `/partials/admin/alerts/password` and RUN NOW to `/partials/admin/alerts/triage/run`; a save serialises only `SETTING_KEYS` names. Severity per kind is UI if `ALERT_KINDS` carries it (check). |
| `admin_recovery.html` + `partials/recovery.html` | `recovery.html` | UI. Two-pane problem picker (can stay a link with `?problem=`, or become an hx-get). The Resolve undo list nests inside its problem. `recovery.py`'s "the dashboard has no button for this yet" sentence sits next to the undo button, a product defect the bench found. |

### 1.4 Apps

| Live | Bench | What differs |
|---|---|---|
| `cards_landing.html` + `static/cards_landing.css/js`, `GET /cards/` (router `cards_landing.py`, mounted by `cards.mount_cards`) | `cards.html` | Close to live. Has its own `cl-*` vocabulary and no htmx, but it DOES carry 16 bracket labels (`[ OPEN ]`, `[ CLOSE ]`...): phase 6's `cc/cards_landing.html` rewrites them and gets terminal `has_key` twins in `test_cards_picker.py`, and `cards_pool.py`'s "Press [ OPEN ] to try again", shown on both variants, follows the variant-neutral D8 wording in phase 7. Confirm for close stays the native `onsubmit` confirm (`cards_landing.html:43-44` is a plain form, not htmx; wave 5, 3.2). The landing extends base, so it gets the HUD with the chrome. `cards_landing.css` reads classic tokens (`--amber`, `--green`, `--red-dim`, `--red-hot`, `--panel`, `--tap`) that the cc `:root` does not define, so the terminal landing gets its own `static/cc/cards_landing.css` (phase 6), and the classic file is not edited until phase 8. |
| `/cards/p/<slug>/`: the Timeline Cards page from `E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\cards\page\` | **no bench page** | Another repo, its own "console" look, its own Google Fonts loader (`10-look.js`), and it does NOT inject the dashboard topbar. **Out of this port** (D9). The HUD links to `/cards/`. |
| `broll/web/static/index.html`, `app.js`, `ingest.js`, `clientfolders.js`, `sprite.js`, `style.css` at `/broll/` | `broll.html` | Clip detail opens beside the grid instead of replacing it (UI, in app.js). Panels become drawers. **Bench and live ids differ** (`#q` vs `#q-input`, `#grid` vs `#results-grid`, and six more); the port keeps live ids. Bench omits ingest retry-failed; keep it. |
| `broll/web/static/share.html`, `share.css`, `share.js`, `share_gone.html` (public, via Funnel) | **no bench page** | Client-facing and public. It must not get the crosshair, the HUD or the dock. Out of this port (D10). **But it loads b-roll's main `style.css`** (`share.html` links `../assets/style.css` before `share.css`, and `SHARE_ASSETS` in `broll/web/app/main.py` lists `style.css`), so every change to that sheet reaches clients. R22 has the rule. |
| `music/web/static/index.html`, `app.js`, `ingest.js`, `style.css` at `/music/` | `music.html` | Near-faithful. Reconcile ids: the bench lacks `#durMin/#durMax`, `#applyRange`, `#addMusic`, `#drop`, and uses `#rhead` for `#resulthead`. |
| `ytdl/web/static/index.html`, `app.js` (17 bracketed labels in its own `text-btn` class), `style.css` at `/ytdl/` | `youtube.html` | Faithful. Health spans become one line. Bench renames about ten ids (`#df` vs `#datefrom` and so on); keep live ids. |

### 1.5 Live surfaces the bench does not cover, and what they get

| Surface | Gets |
|---|---|
| `/cards/p/<slug>/` (other repo) | Nothing in this port. A separate plan in MulticamPipeline if wanted (D9). |
| b-roll client share page | Nothing (D10). |
| `partials/minted_secret.html` + `copy_value.js` | Restyle; `copy_value.js` labels change (section 3.5). |
| The fleet-grid banners, `[ DETAILS ]` content, lost computers, sync queue | Keep them. They need homes in the new home page or the account and user pages (section 5.1). |
| `partials/fix_root.html`, `missing_files.html`, `bins.html`, `project_roots_browse.html` | Restyle within their parent pages' phases. |
| `partials/admin_diagnostics.html`, `collector_health.html`, `notice_checks.html` | Move to Health (phase 5), or stay on home if D7 says so. `#fleet-diagnostics` is also the target of the per-computer READ THE ANSWER button (`fleet_grid.html`) and of `admin_diagnostics.html` itself. So the terminal home keeps an empty `#fleet-diagnostics` window outside the grid body. **No listing ticket is needed** (wave 4 correction): `GET /partials/admin/diagnostics` with no `editor`/`machine` already returns `db.newest_diagnostics_per_machine`, one row per computer (`ui.py:4466-4480`). `/partials/computer-answer` and `/partials/health-diagnostics` accept no parameters for that listing (and `editor`+`machine` for one bundle), and their "every computer" link targets their OWN route and window, never the classic `hx-get="/partials/admin/diagnostics"` of `admin_diagnostics.html:37`, which would fetch classic markup into a terminal window. Both are in R15's fetch-map test. |
| `GET /admin/alerts/preview`, `/admin/alerts/triage/{id}` | Plain text. No change. |
| Email and webhook text (`alerts.py`, `protection.weekly_lines`, notices fixes, `invariants` fixes) | No styling. Bracket copy changes in the copy sweep (phase 7). |
| The companion's Tk UI (`theme.py:463` wraps every button as `[ X ]`) | Untouched. Companions are out of scope. Say so in the release notes, so the tray and the dashboard disagreeing on brackets is known and intended (D12). |

---

## 2. CSS strategy

### 2.1 Replace, do not layer

The collisions (section 0, point 2) and the two different box models of a
"window" (live `.panel`, `.side-head`, `.editors` tables against bench
`.win > .bar + .body`, `.tbl`) mean the terminal sheets cannot be layered
over `style.css`. So:

- **New files, new URLs:** `dashboard/static/cc/terminal.css` (tokens, base,
  window, key, tag, led, layout, the home pieces, from
  `cc-terminal.css`), `dashboard/static/cc/components.css` (from
  `cc-components.css` plus the deduplicated `design/css/*.css`, see below)
  and `dashboard/static/cc/phone.css` (all the phone rules in one place, the
  way `mobile.css` separated them).
- A terminal page loads ONLY the `cc/` sheets. A classic page loads ONLY
  `style.css` + `mobile.css`. The shell template decides (section 2.5).
- `style.css` and `mobile.css` are deleted in the last phase, except for the
  pieces the SPAs share. Those are the `theme-common` block and the drawer
  block, which live in all four stylesheets (section 4).
- **theme-common goes into `cc/terminal.css` byte for byte in phase 0**
  (what the block actually holds, `style.css` 1694-1864: its `:root` scroll
  tokens, `html`/`body`/`*` scrollbar paint, range inputs, `::selection`,
  `:focus-visible` and `color-scheme`; it does NOT hold the text-field,
  textarea and select paint, which is `style.css` 663-700, outside the
  block). So `components.css` carries the field, textarea, select and
  option rules with `color-scheme: dark` on them, and the cc `:root`
  defines every custom property theme-common reads (`--bg`, `--red`,
  `--red-hot`, `--red-dim`; the bench `:root` has no `--red-dim`, which the
  range-track borders read three times). The `cc/` CSS-fact file tests that
  every `var(--x)` inside theme-common is declared in `cc/terminal.css`'s
  `:root`, and carries terminal twins of
  `test_every_text_field_family_is_themed`,
  `test_textareas_and_selects_share_the_same_paint` and
  `test_focus_is_a_slim_red_ring_that_moves_nothing`. And
  `cc/terminal.css` becomes a fifth `FLEET_STYLESHEETS` entry in all four
  suites' `test_theme_css.py`. Otherwise a terminal page and `/music/` paint
  different scrollbars and focus rings, and D6's change would not reach
  terminal pages. The bench's own scrollbar, selection and focus-ring rules
  (`cc-components.css` `--red-deep` 6 px, `cc-terminal.css` `--hi`) are NOT
  carried: theme-common is the one definition for scrollbars and selection.
  **Focus is the one exception** (wave 5): theme-common's `:focus-visible
  { outline: 1px solid var(--red); outline-offset: 2px }` (`style.css:1860`)
  is invisible in a UI where every `.win`, `.bar` and field border is 1 px
  red (WCAG 2.4.7), so theme-common stays byte-identical and `cc/terminal.css`
  adds, after it, `html[data-ui="cc"] :focus-visible { outline: 2px solid
  var(--hi); outline-offset: 2px }`; hud-common adds the same for `.hud`,
  `.hud-dock` and `.hud-more` with `--cc-hi`, so the HUD matches on classic
  pages and in the SPAs. The terminal twin of the focus test asserts the
  2 px `--hi` ring and no layout shift (not the red ring), and a Chrome check
  asserts a focused fold button's ring colour differs from its bar's border. In phase 8 the `"dashboard"`
  reference entry in all four test files moves from `static/style.css` to
  `static/cc/terminal.css` in the same commit as the deletion.
- **Static JS is shared by both variants** (the overlay is templates only).
  A script whose OUTPUT changes for the terminal look (`site_settings.js`,
  `copy_value.js`, `setup.js`, `assignments.js`, `dashboard_update.js`, and
  `account.js` in phase 3, wave 5: it writes `field-hint amber|ok|muted` and
  `account-result red`, classic colours in `style.css:2118-2124` that the cc
  sheets do not define or define differently; `static/cc/account.js` emits
  cc tag or note classes)
  ships as a separate file under `static/cc/`, loaded only by `cc/`
  templates, and the classic file is frozen until phase 8. A `cc/` page
  never loads the classic copy of a forked script (two delegated click
  handlers would both run). `static/cc/copy_value.js` is forked in phase 0,
  so `cc/shell.html` loads the cc copy from its first day.
  **Tags lowercase the state word, never the data** (wave 5): the bench's
  `.tag { text-transform: lowercase }` (`cc-terminal.css:190`) would
  lowercase data that classic chips carry (Syncthing device-id prefixes
  `{{ d[:7] }}` in `collector_health.html:84-85`, which admins compare with
  Syncthing's own upper-case UI; hostnames in `admin_jobs.html:93`; SMTP
  error details in `admin_alerts.html:235`; versions and git shas in
  `admin_packages.html`). The fixed state words are written lowercase in
  the templates; the CSS rule is dropped (or limited to `.tag .w`), and
  any interpolated value sits in a `.v` span with `text-transform: none`.
  A `cc/` markup-fact test: no `.tag` interpolates a Jinja expression
  outside a `.v` span.
  A script shared on purpose (`htmx_errors.js`, `tab_memory.js`, `pwa.js`)
  branches on where it is acting and keeps its classic output byte for
  byte. `htmx_errors.js` and `tab_memory.js` branch on
  `<html data-ui="cc">`, which only `cc/shell.html` sets. `pwa.js` is not
  forked: from phase 1 the HUD's `#install-slot` sits inside `#hud-more` on
  CLASSIC pages too, where only the classic `pwa.js` runs. It branches on
  `slot.closest('.hud-more')`: there it builds `button.hud-key` with an
  unbracketed label, and in the classic slot it builds today's
  `button.btn.chip.tap.install-btn` `[ INSTALL ]` unchanged (a test per
  slot). Classic JS pins (`test_pwa.py` `[ INSTALL ]`, d-ui `[ COPIED ]`,
  the d-ui Chrome harness over classic `site_settings.js` fixtures) stay;
  the `cc/` copies and the HUD branch get terminal twins.
- **Classes a `cc/` template must not use.** `.stack` is a grid container
  in the bench (`cc-components.css:59`), not the classic table-stacking
  class, and `.rule` and `.editors` are classic vocabulary. No `cc/`
  template uses the bare classes `stack`, `rule` or `editors` (a test
  enforces it). Phone tables are `.tbl.stack-sm` with a `data-label` on
  every `td`, and `cc/phone.css` carries
  `.tbl.stack-sm td[data-label]::before { content: attr(data-label) }`.
- **No customer name or website in the shipped sheets** (wave 6).
  `design/cc-terminal.css:1-12` opens with the owner's quote naming
  `thecreatorsclub.co/productions`; CLAUDE.md: "No customer's name in
  code." The bench header comments are not carried into `static/cc/*.css`
  or hud-common (a one-line neutral header instead), and the `cc/` CSS-fact
  file fails on the domain `thecreatorsclub` (case-insensitive) in any
  `static/cc/*`, `templates/cc/**` or hud-common copy; visible brand text
  comes from `brand_org` (R20), and the CC mark itself is the product's
  logo (the 2026-08-18 ruling), not a string.
- **Generated slashes.** The bench's `content: "//"` (`cc-components.css:68`,
  `css/apps.css:309`, `css/account.css:94`, `css/fleet.css:312`) becomes
  `content: "\2f\2f"` in the dedup, as live already does, and the `cc/`
  CSS-fact file asserts no `content:` value starts with a slash other than
  a bare `"/"`.
- **Data-URI slashes** (wave 3). `content:` is not the only place a quote
  meets a slash: the bench's inline SVGs close elements with `'/%3E`
  (`cc-terminal.css:73` crosshair, `:91` grain tile, `:431` select chevron,
  `cc-components.css:89` `.sel` chevron), and ytdl's `_ABSOLUTE`
  (`["'`(](/[^"'`)\s>]*)`) matches every one. Rule for every `static/cc/*.css`
  and hud-common: a data-URI SVG percent-encodes every slash (`%2F%3E`,
  `%3C%2Fsvg`) or uses explicit closing tags with no `/` after a quote. The
  `cc/` CSS-fact file runs ytdl's exact `_ABSOLUTE` over every
  `static/cc/*.css` and the hud-common block (only a bare `"/"` allowed), and
  phase 6 lists ytdl's `test_mounted_prefix.py` in its verification for the
  body restyle. Only with both does every sheet pass ytdl's deny-by-default
  scan.
- **HUD, dock and settings-strip rules are not copied from the bench**
  (wave 3). The bench defines `.hud*` and `.dock` (`cc-terminal.css:223-255`,
  the phone versions at `:484-523`) and `.snav*` (`cc-components.css:23-40`,
  `:193`) with the SPA-colliding `var(--red)`/`var(--hi)`. `cc/hud.css` loads
  first (2.5), so unscoped bench copies in `terminal.css`, `components.css`
  or `phone.css` would override hud-common at equal specificity on cc pages
  only, and the byte-identity test would not see it. Every `.hud*`, `.dock*`
  and `.snav*` rule, media queries included, is left out of those three
  sheets: hud-common is their only home. The `cc/` CSS-fact file asserts no
  selector containing `.hud`, `#hud-`, `.dock` or `.snav` appears in any
  `static/cc/*.css` outside the hud-common BEGIN/END block.
- **Bar corners and tree branches are drawn by CSS**, not text. The bench
  writes `┌─╡ ... ═┐` and `├─ └─` as literal glyphs; `test_mobile_admin.py`
  bans `─` in admin partial renders and sources (MOBILE_PLAN 3.2). The `cc/`
  templates carry no box-drawing characters: borders and `::before`/`::after`
  generated content in `components.css` draw them, so the ban holds in the
  terminal variant too, and the `cc/` CSS-fact file pins it.

**Deduplicating the bench's per-builder sheets.** The builders worked in
parallel and defined some classes twice, for different components:
`.fold` (apps vs sync), `.crumbs` (apps vs sync), `.files` (safety vs sync),
`.bench` (fleet vs sync), `.chip` (apps.css defines a toggle chip that
collides with the live `.chip` name), `.err/.warn/.hi` setting `--sev`
globally (issues.css), plus refinements of `.tbl`, `.key`, `.note`, `.inp`,
`.sel`, `.dialog`, `.pick`, `.prob`, `.page` in four or more files. Phase 0
merges them into `components.css` with one definition each. The toggle chip
becomes `.toggle`, so `.chip` means nothing in the terminal sheets and a
leftover classic `.chip` in a ported template is visible (unstyled) in
review rather than half-styled. Bench-only classes are not carried: `.bench`,
`.acct-bench`, `.acct-new*`, `.fl-new*`, `.fl-benchsw`, `.tune*`, `.opts`,
`.swatch`, `.iv-switch`. Nor are the bench's phone rules that hide real
controls (wave 6): `.bar a.act { display: none }` (`css/sync.css:196`),
and `.pc .ver`, `.pc.head-row`, `.xf .meter/.eta` (`cc-terminal.css:496-497,
508`) only where the same fact is shown another way on the phone; every
bar action gets a phone home (the window body, or `#hud-more`), checked by
R1 (11).

### 2.2 Tokens

- Carry `:root` from `cc-terminal.css` as it stands, with TUNE's current
  choices baked in as literals (D5): `--hi-rgb`, `--fx-grain`,
  `--fx-scan`, `--fx-glow`, `--fx-dither`, `--fs`, `--d`. Keep them as
  custom properties (they are free, and a later tweak is one line), but
  nothing writes them at runtime.
- Keep the live mobile tokens: `--tap: 44px` and the four `--safe-*`.
  `viewport-fit=cover` stays in the head. The bench never used them, so the
  dock (`bottom: 0`, `env(safe-area-inset-bottom)`) and the toast need
  `--safe-b`, and the HUD needs `--safe-t` in standalone (installed PWA)
  mode, as live does.
- `color-scheme: dark` on `:root`. Keep `<meta name="theme-color">` in sync
  with `--bg` (live `#0a0a0d`; bench `#070403`).
- **Breakpoints differ.** The bench uses 760 / 1100 / 1320. Live uses 600
  (phone) / 900 (tablet), and `test_mobile_css.py` pins `--bp-phone: 600px`
  and a single `@media (max-width: 600px)` block in `style.css`. Recommended:
  adopt the bench's numbers in the `cc/` sheets (the layout was designed
  and screenshot at them), give the terminal sheets their own mobile test
  file, and leave the classic pins alone until classic is deleted. The
  sweep checks 390 / 768 / 1440 either way. **768 is 8 px above the bench's
  phone query**, so at 768 the HUD shows the full `>word` nav with no dock.
  That is the width most likely to overflow (seven nav words, brand,
  problems, alerts, user), so it must be screenshot, and the phone query may
  need to become 800.
- **The HUD's own breakpoint is separate from the bodies'.** hud-common is
  byte-identical in four sheets and, from phase 1, sits over classic bodies
  that switch to phone layout at 600. So hud-common swaps nav for dock at
  600 while classic bodies exist (one value, recorded in the `cc/` CSS-fact
  test), and between 601 and 900 the lower-priority nav words (music,
  youtube) collapse into the "more" popover so 768 fits. **The dock is
  hidden above 600, so the popover needs its own opener there** (wave 4):
  `.hud-nav` carries `<button type="button" class="hud-more-btn"
  popovertarget="hud-more">more</button>`, shown only from 601 to 900 and
  44 px on coarse pointers; without it music, youtube and `#install-slot`
  are unreachable on a 744/768 px tablet. The phase 1 sweep asserts at 768
  that every mounted module's href is one tap from the HUD.
- **One dock query** (wave 4). The dock's query is hud-common's 600, and it
  is THE query for everything that makes room for the dock: `--cc-dock-h`,
  every lift, the body padding, in `cc/hud.css`, `cc/phone.css` and the SPA
  sheets. The cc sheets' own phone layout stays at the bench's 760, but the
  bench's dock-sized rules under 760 are NOT carried: `.page { padding:
  18px 14px 100px }` becomes `calc(18px + var(--cc-dock-h))` at the bottom,
  and `.toast { bottom: 76px }` becomes `calc(18px + var(--cc-dock-h))`, so
  601-760 reserves nothing for a hidden dock and 600 and below does not pay
  it twice. The cc CSS-fact test asserts the query that declares
  `--cc-dock-h` equals hud-common's dock query.
- **hud-common is never put into classic `style.css`** (wave 2). The
  dashboard's copy lives in its own sheet, `static/cc/hud.css`, linked
  through `asset_url()` by `cc/shell.html` and, when the HUD is served, by
  classic `base.html` (one added line; `test_mobile_css.py` asserts its
  contract lines are PRESENT, not that no other line exists, so its pins
  hold). Reasons: classic `/static/style.css` is unversioned and served
  stale-while-revalidate by `sw.js` (and heuristically cached by browsers
  without the worker), so a phone whose first load after `chrome` is
  enabled pairs HUD markup with the pre-phase-1 sheet; and
  `test_mobile_css.py` builds `PHONE_BLOCK`, `TOUCH_BLOCK` and `APP_BLOCK`
  from the FIRST occurrence of each query (`css.index(opening)`), as does
  `test_theme_css.py`'s phone slice (l.134-136), so a hud-common phone
  query ahead of the phone layer would hijack a dozen classic tests. With
  its own file, classic `style.css` and its pins are untouched and no
  carve-out is needed. The same first-occurrence slicing exists in the SPA
  suites (`test_bug_hunt_2026_09_24_w2_broll.py:1000` slices from the first
  `@media (max-width: 700px)`); phase 1 places hud-common in each SPA sheet
  after every such block or strips the marked range before slicing, and
  lists every affected test in its verification.
- **`--cc-dock-h`** (58 px plus the bottom safe area on the phone query, 0
  elsewhere) is NOT a hud-common token: custom properties inherit only
  downward, and none of the elements it lifts sits inside `.hud` or
  `.hud-dock`. It is declared in a lift block outside hud-common on the
  ROOT, `html:has(.hud-dock)` (wave 4: declared on `body` it never reaches
  `html`, body's parent, so the `scroll-padding-bottom` below, which only
  the root element's value drives, always took its 0px fallback), inside
  the dock query, in `cc/hud.css` (for classic pages), `cc/phone.css`
  and each SPA sheet. Everything that reads it (body padding, the lifted
  classic banner, sheet and handle, the SPA toasts and panels) is a
  descendant of `html` and inherits it. A CSS-fact assert in the `cc/` file
  and in each SPA suite: `--cc-dock-h` is declared only on an
  `html:has(...)`/`:root` selector. Inside hud-common the dock uses
  `env(safe-area-inset-bottom, 0px)` directly, never `var(--safe-b)`: the
  SPA sheets define neither `--safe-b` nor `--tap`. hud-common's colour
  tokens are declared on `.hud, .hud-dock, .hud-more` inside the block (the
  three are siblings with no common HUD root). A CSS-fact test asserts that
  every `var(--x)` in hud-common is a `--cc-*` token declared inside the
  block or has a fallback. Everything else fixed to the bottom is lifted by
  `--cc-dock-h` on phones: classic `.banner.alarm.stale-banner` (the
  "server not answering" alarm, z 60), `.chip-sheet` (z 70),
  `.btn.sheet-handle` (z 40, the only way to open the project tree on a
  classic phone), `.toast-host`, and `body` padding (added to `--stale-h`).
  Those lifts name classic classes, so they sit in `cc/hud.css` after the
  hud-common END marker and in `cc/phone.css`, keyed on
  `body:has(.hud-dock)`, which the client share page never matches.
- **Contrast** (computed on `#070403`): `--muted` 5.45:1, `--text-2`
  11.25:1, `--red` 5.53:1, `--warn`, `--ok` and `--hi` all above 11:1. That
  clears the 4.5:1 pins the four `test_bug_hunt_2026_09_24_w2_*` suites
  apply to live tokens. **White on the primary key's red fill is 3.7:1,
  under AA for 12 px text.** Fix: darken the fill (for example `#d01818`,
  about 5:1), or black text on red. **The fix is key-local** (wave 6): the
  hover is worse (`.key.primary:hover { --k-bg: var(--red-hot) }`, white on
  `#ff5a3c` is about 3.1:1, `cc-terminal.css:169`), and darkening `--red`
  itself would drop red text on `--bg` below AA and change the scrollbar
  and range track theme-common reads. `.key.primary` gets its own `--k-bg`
  (`#d01818`, about 5.5:1 with white) and a hover fill that also clears
  4.5:1 (`#b81414`, about 6.7:1); `--red` and `--red-hot` stay as they are;
  the cc CSS-fact file pins both contrasts. `--red-deep` (scrollbar thumb, tree
  branches) is 2.1:1, under the 3:1 non-text guideline for the thumb (D6).
- **Font-size floor.** The bench uses 10 and 11 px for `.kbd`, `.snav-h`,
  table headers, `.hint`, `.pc` headers, dock labels and lane labels.
  `MOBILE_PLAN.md` sets a 12 px floor on phones, and `mobile_sweep.js` warns
  under 12. `phone.css` raises the BODY ones to 12 on the phone query. The
  HUD ones (dock labels, 11 px at `cc-terminal.css:502`; `.snav-h`, 10 px at
  `cc-components.css:34`) cannot be raised there, since `.dock*`/`.snav*`
  rules live only in hud-common (2.1) and the SPAs never load `phone.css`
  (wave 4): hud-common's own phone query sets `.hud-dock a`, `.snav-h` and
  any other HUD text to 12 px or more, and a hud-common CSS-fact assert
  finds no `font-size` under 12px inside that query.
- **Fields at 16 px on phones, 44 px hit boxes on touch** (wave 3). The bench
  `.inp, .sel, .area` are `font-size: 13px` (`cc-components.css:85`), so iOS
  zooms the page on every focused field; live pins 16 px (`style.css:1380`,
  `mobile.css:249`). `cc/phone.css` carries the 16 px rule on the phone query
  **written to win** (wave 6: a media query adds no specificity, and the
  bench's `.prompt-in input` (0,1,1, the tree find box), `.pick select`
  (0,1,1, the TICKING FOR pickers), `.inp.sm, .sel.sm` (0,2,0,
  `css/fleet.css:40`) and `.ctrl .inp.sm` (0,3,0, `css/apps.css:439`) all
  beat a bare `input, select` rule): `html[data-ui="cc"] :is(input:not([type=checkbox],
  [type=radio],[type=range]), select, textarea) { font-size: 16px }`, placed
  last in `cc/phone.css`, and the dedup drops every smaller field
  font-size inside the phone query. `tools/mobile_sweep.js` gains a
  computed check (FAIL, not WARN): at 390 every visible focusable text
  input, select and textarea has `getComputedStyle().fontSize` of 16px or
  more; the cc mobile test file keeps its CSS assert as a second guard. And a
  `(pointer: coarse)` block giving `.key`, `.tabs button` (bench padding
  6px 14px at 12 px, `cc-components.css:119-122`), `.fold`, `.tip-btn` (3.2)
  `min-height: var(--tap)`. hud-common declares its own `--cc-tap: 44px`
  (the SPA sheets have no `--tap`) and gives dock links, `.hud-nav a` and
  `.hud-key` `min-height: var(--cc-tap)` under `(pointer: coarse)`. Terminal
  twins of the live 16 px and 44 px tests go in the `cc/` mobile test file.
  **Ticks, radios, switches, tree rows and tappable tags too** (wave 5). The
  bench hides the real input (`.check input, .radio input, .switch input {
  position: absolute; opacity: 0; pointer-events: none }`,
  `cc-components.css:99-112`), leaving a 13 px label (11 px switch), and a
  tree row is about 23 px (`.tree { font-size: 13px; line-height: 1.75 }`),
  where classic makes every tick a 44 px input (`style.css:1575-1592`, the
  tick "starts a real sync on someone's computer") and every tappable chip
  44 px (`mobile.css:220-227`, DUI-3). So the same `(pointer: coarse)`
  block adds `.check, .radio, .switch, .tree .row, .tag[title],
  .led[title], [data-chip-detail], .pick select, .inp, .sel { min-height:
  var(--tap) }`, the label is the hit box, the painted glyph stays 1em, and
  a row that holds ticks grows with them. `tools/mobile_sweep.js` today
  measures only `button, a.chip, .btn, input, select` and `shown()`
  (l.228-233) skips `opacity: 0`, so it is extended to measure
  `label:has(> input)`, `.tree .row`, `.tag[title]` and `[data-tip]`, and
  to measure an opacity-0 input's label instead of skipping it. The `cc/`
  mobile test file gets a terminal twin of "every tick is 44 px on a coarse
  pointer".
- **Wrap rules on phones** (wave 5; the wave-1 "bench makes user strings
  and long keys nowrap" finding was never applied). The bench sets `.key`,
  `.xf` to `white-space: nowrap` and `.tree .row` to `white-space: pre`
  (`cc-terminal.css:142-159, 405, 453`). The phase-2 key "Move on the
  server and on every computer" is about 376 px at 12 px mono with 0.12em
  tracking, and a 390 px phone's window body offers about 328 px. Classic
  measured and fixed exactly this (`mobile.css:57-66`, the move key
  overflowed by 319 px at 768; `mobile.css:40-56` wraps names). `cc/phone.css`
  carries the same rules in terminal vocabulary on the phone query: `.body
  .key { white-space: normal; height: auto; text-align: left }`; the move
  form's fields `display: block; width: 100%`; tree names in a span with
  `white-space: normal; overflow-wrap: anywhere` (the branch and box
  columns stay fixed); file and name cells `overflow-wrap: anywhere`
  instead of ellipsis. Terminal twins of those `mobile.css` tests go in the
  `cc/` mobile test file, and phase 2's sweep loads `/project/{slug}` at
  390 with a long CJK project name and asserts zero page overflow.
- **The HUD brand shrinks** (wave 5). `.hud-brand { white-space: nowrap }`
  in a fixed 52-58 px flex row holds `brand_org`, which `site_store`
  does not cap (`_validate_str`), so a 25-30 character org name pushes the
  390 px HUD sideways on every page and in every SPA (classic's `.topbar`
  wraps). hud-common sets `.hud-brand { min-width: 0; flex: 0 1 auto }` and
  `.hud-name { overflow: hidden; text-overflow: ellipsis }` with the full
  name in `title`; on the phone query the brand shrinks before the counts
  and the stamp. Phase 1 sweep: a 40-character `org_short` and a CJK one at
  390 and 768, zero page overflow.
- **Sticky HUD and scroll-padding** (wave 3). The bench `.hud` is sticky
  (`top: 0`, 58 px; 52 px under 760), where the classic `.topbar` is not, and
  nothing sets `scroll-padding-top` today. So from phase 1 every deep link
  (`/#server-notices`, `/admin/users#admin-fleet-halt`, every `/go/<panel>`),
  the base.html scroller's and tab_memory's `scrollIntoView()`, and Tab focus
  scrolling put the target under the HUD (and, on phones, the last control
  under the 58 px dock; WCAG 2.4.11). Outside hud-common, in `cc/hud.css`
  (classic pages), `cc/terminal.css` and each SPA sheet:
  `html:has(.hud) { scroll-padding-top: calc(58px + 8px); scroll-padding-bottom: var(--cc-dock-h, 0px) }`,
  with the phone HUD height in the phone query. `scrollIntoView()` and focus
  scrolling honour it. The sweep loads each R13 anchor at 390 and 1440 and
  asserts the target's top is below the HUD's bottom; a Chrome-harness check
  asserts a Tab-focused element near either edge is not covered by the HUD or
  the dock.
- **The HUD must actually stick on classic pages and in the SPAs** (wave 4).
  A sticky element sticks only inside its containing block, and a
  `<header class="hud-host">` (or the SPAs' `#dash-topbar`) is exactly as
  tall as the HUD, so the HUD would scroll away on every classic page and
  SPA while sticking on cc pages, and the scroll-padding check above would
  pass for the wrong reason. So the host is transparent for layout:
  `header.hud-host { display: contents }` in `cc/hud.css`, and hud-common's
  `#dash-topbar:has(> .hud)` reset is `display: contents` (not `block`).
  The HUD is then sticky against `<body>` on classic pages and against
  `#app-header` in the SPAs. **In b-roll and music the body is one viewport
  tall** (wave 6): both sheets set `html, body { ...; height: 100% }`
  (`broll/web/static/style.css:52-61`, `music/web/static/style.css:42-51`;
  ytdl has `min-height: 100%`), so `<body>` is the sticky header's
  containing block and it ends after one screen (the wave 6 critic measured, in headless Chrome
  at 1440x900 with 5000 px of content scrolled to 1500, `#app-header`'s top
  is -793 (b-roll) and -791 (music), 0 in ytdl). `display: contents` does not
  change that. So the b-roll and music sheets add, OUTSIDE hud-common and
  scoped (b-roll's sheet is also the client share page's, R22),
  `html:has(#dash-topbar > .hud) body { height: auto; min-height: 100% }`,
  which joins R22's scoped allow-list and b-roll's unscoped-rule snapshot.
  It also makes the SPA's existing sticky `#app-header` stick as its own CSS
  intended. Phase 1 checks that b-roll's `.folder-tree`
  (`calc(100vh - var(--header-h))` heights, `style.css:1051-1061`) and
  music's `.filter-rail` still lay out with body height auto (screenshot at
  1440 and 390, scrolled). Making it stick exposes the classic sticky
  rail: `.project-tree { position: sticky; top: 1rem; max-height:
  calc(100vh - 9rem) }` (`style.css:402-407`) would slide its first ~42 px
  under the 58 px HUD. A lift in `cc/hud.css` after the END marker:
  `html:has(.hud) .project-tree { top: calc(58px + 1rem); max-height:
  calc(100vh - 9rem - 58px) }`, with the phone HUD height in the phone
  query. Phase 1 sweep: scroll 1000 px on a classic page with a sidebar, a
  cc page, `/broll/` and `/ytdl/` (and `/music/` above 900 px, where its
  header is sticky), assert the HUD's `getBoundingClientRect().top == 0` and
  the project tree's top is at or below the HUD's bottom.
- **The installed app pays the safe-area insets in hud-common** (wave 4).
  With `black-translucent` and `viewport-fit=cover` (`base.html:37`), live
  pays the top inset only through `.topbar { padding-top: calc(0.9rem +
  var(--safe-t)) }` in standalone (`style.css:1686-1687`), which no longer
  applies once the host is not `.topbar`, and hud-common cannot read
  `--safe-t`. hud-common carries `@media (display-mode: standalone) { .hud {
  height: calc(58px + env(safe-area-inset-top, 0px)); padding-top:
  env(safe-area-inset-top, 0px) } }` (the phone height in the phone query;
  a padding alone would crush a border-box 58 px bar), pads the HUD
  sides with `max(24px, env(safe-area-inset-left, 0px))` and the right-hand
  twin, and the DOCK with the real inset only (`padding-inline:
  env(safe-area-inset-left, 0px) env(safe-area-inset-right, 0px)`; wave 6:
  the dock is five equal columns, and with 24 px sides and the 12 px floor
  "transfers" at 12 px JetBrains Mono with 1 px tracking is about 73.8 px in
  a 68.4 px cell at 390 and a 62.4 px cell at 360, so it overflows into its
  neighbours; dock labels also get `letter-spacing: 0` in the phone query,
  and the sweep asserts at 360 and 390 that every `.hud-dock a` has
  `scrollWidth <= clientWidth`), and the `scroll-padding-top` calc includes the top inset. Phase 1:
  a hud-common CSS-fact assert for the standalone block, and a screenshot
  from the installed iPhone app.
- **Forced colours and reduced motion inside hud-common** (wave 3). hud-common
  carries its own `@media (forced-colors: active)` block (LEDs and the
  current nav entry keep a visible system-colour border, since their meaning
  is otherwise a colour) and its own `prefers-reduced-motion` kill for the
  HUD LED blink, because the SPA sheets do not carry the dashboard's.
  **Body LEDs need the same** (wave 5): `.led` is a background-only 8 px
  square (`cc-terminal.css:211-219`) that forced colours paint as Canvas,
  and on the home `.pc` row it is the only state indicator (classic draws a
  `●` glyph by `color`, which survives). `cc/terminal.css` carries a
  `@media (forced-colors: active)` block giving `.led` a system-colour
  border, and wherever an LED carries a state no neighbouring word says
  (the `.pc` row, collector, allclear, the offline page) the template adds
  a visually-hidden state word from the same text as its `title`. A CSS-fact
  assert for the block and a markup test that every `.pc` row has a state
  word.
  **Switches, ticks and radios** (wave 6). The bench `.switch input` is
  `opacity: 0` (`cc-components.css:110-114`) with no `:focus-visible` rule,
  so the 2 px ring of 2.1 lands on an invisible input; `.check`/`.radio`
  get only the bench's 1 px `input:focus-visible + .g` outline (:107), which
  2.1's override does not reach; `<label class="switch"><input
  id="triage"><span class="off">off</span><span class="on">on</span></label>`
  (`design/alerts.html:87`) names the checkbox "off on"; and forced colours
  replace the only state cue, a background, with Canvas. So `cc/terminal.css`
  gives `.switch:has(input:focus-visible)`, `.check:has(input:focus-visible)
  .g` and `.radio:has(input:focus-visible) .g` the same 2 px `--hi` ring;
  the `.switch` macro names the input after the setting (`aria-labelledby`
  pointing at the visible setting text, or `aria-label`) and marks the
  `.off`/`.on` spans `aria-hidden`; and the forced-colours block shows the
  selected half with a `Highlight` border (or `forced-color-adjust: none`
  with system colours). Tests: a terminal twin of the focus test on the
  three components (Chrome: Tab onto a switch, a non-zero outline on the
  label); a `cc/` markup test that no `.switch input` is named "off on"; a
  CSS-fact assert for the forced-colours switch rule.

### 2.3 Fonts: self-hosted, offline, licensed

- Ship woff2 in `dashboard/static/fonts/`: JetBrains Mono 400/500/700 and
  Orbitron 700/800 (500 only if the tokens use it). Both are SIL OFL 1.1.
  Drop Space Mono, which is only a TUNE option. Subset Latin, Latin-1 and
  Latin Extended-A (U+0100-017F: the fleet's own example name `Matej
  Šimalčík`, CR-90, needs it; wave 3), the box-drawing block (U+2500-257F), block elements (U+2580-259F; the
  meters are `█░`), geometric shapes (the `▸ ▾ ■ □ ● ○ ▲ ✕ ✓` glyphs) and
  arrows. Check each glyph the templates use renders from JetBrains Mono
  rather than a fallback, or the meters misalign. **The ranges are derived,
  not listed from memory** (wave 5): `✓` (U+2713) and `✕` (U+2715) are
  Dingbats, not geometric shapes, and a scan of `templates/`, `design/` and
  `static/` (literal characters plus CSS `\XXXX` escapes) also finds
  General Punctuation (`• … “ ”`, U+2000-206F), `ℹ` (U+2139), `≡`
  (U+2261), `⇅ ⇡ ⇣` (U+21C5-21E3) and `⛔` (U+26D4). So the subset list is
  Latin, Latin-1, Latin Extended-A, General Punctuation, Letterlike
  Symbols, Arrows (U+2190-21FF), Mathematical Operators used, the three
  blocks above, and the used Dingbats. A phase 0 test scans the same trees
  for every non-CJK codepoint above U+007F and asserts each lies inside the
  `unicode-range` of a shipped `@font-face` (or is on a short allow-list
  of emoji left to the system face, like `📁`).
- **CJK.** Project and clip names are Chinese on this fleet. JetBrains Mono
  has no CJK, so those fall back to the system face, which is fine for body
  text. **Orbitron must never carry a user string.** The bench's own rule
  ("only numbers and page titles") has to be enforced: the project page's
  `h1` is a project name, so it stays in the mono face. The same holds for
  the HUD brand: the bench `.hud-name` is Orbitron with 3 px letter-spacing
  (`cc-terminal.css:237`) and holds `brand_org` (`topbar.html:40`), which is
  customer site data, so `brand_org` renders in the mono face (R19).
- `@font-face` with `font-display: optional` (wave 3: `swap` re-lays every
  line when the font lands, against the owner's "nothing shifts"; the fonts
  are precached, so `optional` uses them on every load after the first).
  Paths are **relative to the sheet**
  (`url(../fonts/x.woff2)` from `/static/cc/terminal.css`). No Google Fonts
  anywhere at runtime: remove the `<link>`s the bench pages carry. Add the
  fonts to `sw.js` PRECACHE so the installed app and `/offline` have them,
  **at their plain URLs** (`/static/fonts/<name>.woff2`, no `?h=`): a
  static sheet's `url()` cannot carry the hash, and `caches.match(req)`
  matches the query string, so a hashed precache entry would never be hit.
  Font bytes never change in place; a font change is a new file name.
- `.woff2` has no MIME type in Python 3.12's table (`mimetypes.guess_type`
  returns `(None, None)` on the base rig, and `python:3.12-slim` has no
  `/etc/mime.types`), so `StaticFiles` would send `text/plain`. Phase 0
  registers `mimetypes.add_type('font/woff2', '.woff2')` at dashboard
  import and in each SPA's standalone app, and the font GET tests keep
  their content-type assert.
- `docs/legal/THIRD_PARTY_NOTICES.md`: add JetBrains Mono and Orbitron (OFL
  1.1, with the licence text) to the hand-maintained block **in
  `docs/legal/THIRD_PARTY_NOTICES.md` itself**, between `<!-- BEGIN/END
  HAND-MAINTAINED -->` (wave 5: `gen_notices.py` reads that block back
  verbatim, l.44-45, and its `DEFAULT_HAND_BLOCK`, l.404, is used only when
  the file or its sentinels are missing, so an edit to the script changes
  nothing and `--check` stays green). `tools/check_licenses.py` reads
  lockfiles only, so phase 0 adds a tools/ test that every file under
  `dashboard/static/fonts/` has its family named inside that block.
- The SPAs: see section 4.3.

### 2.4 Effects

The crosshair cursor, grain (an animated `body::after` with an SVG
turbulence tile at `inset: -50%`), scanlines and the DOS shadow ship at the
owner's TUNE values, or off (D5). Three product constraints the bench did
not face:

- The grain animates at 6 frames a second behind every page, forever. On a
  laptop left open on the fleet page for a day that is a constant repaint.
  **Nothing moves for more than 5 s for anyone** (wave 6, WCAG 2.2.2, which
  requires automatic blinking or moving content lasting over 5 s to be
  stoppable by every user, not only reduced-motion users): `.led.err` and
  `.hud-led.err` (`cc-terminal.css:217`, `animation: blink 1.2s steps(1)
  infinite`) get `animation-iteration-count: 4` (about 4.8 s), ending
  steady, and blink again only when the element is newly swapped in; the
  grain (`cc-terminal.css:92`, `grain 0.5s steps(3) infinite`) ships
  static, or capped the same way. CSS-fact asserts: no `infinite`
  animation in `static/cc/*.css` or hud-common except `.spin`, the busy
  indicator that ends with its request.
  Pause it when `document.hidden` (a class toggled by the shared script),
  and keep the existing `prefers-reduced-motion` kill. The same
  `prefers-reduced-motion` query also turns off the grain (wave 3), not only
  the animation (the HUD blur is gone for everyone, below, wave 6).
- **No `backdrop-filter`** (wave 6): the HUD's background is already 82-96%
  opaque (`cc-terminal.css:228-230`), yet the blur is recomputed every frame
  over the grain on cc pages and over b-roll's playing `<video>` and the
  scrolling grid in the SPAs, on laptops whose GPU runs Resolve. hud-common
  and `cc/terminal.css` drop it (the gradient alone reads the same), and a
  CSS-fact assert finds no `backdrop-filter` in any `static/cc/*.css` or
  hud-common rule. The containing-block rule below and R7's test stay as
  guards. Were it kept, `backdrop-filter: blur()` on `.hud` would make the
  HUD the containing block of any `position: fixed` descendant. The dock and the drawer must not be
  children of `.hud`. The drawer is a popover, which renders in the top
  layer and escapes this; the dock must be a sibling. In the SPAs the
  injected partial lands inside their sticky `#app-header`, which has the
  same stacking problem (live `topbar.html`'s popover comment).
- The crosshair cursor on text fields: keep `cursor: text` on inputs,
  textareas and `[contenteditable]`.

### 2.5 Shell templates

- New `templates/cc/shell.html` (the name must NOT be `base.html`, see
  section 7.0). It is base.html's head (CSRF meta, `hx-headers` with the
  `X-CC-UI` group set of R23, manifest and PWA tags, the inline keeper
  scripts) with this script order: `pwa.js` (shared, 2.1), `htmx.min.js`,
  `htmx_errors.js`, `cc/copy_value.js`, `tab_memory.js`, then `cc/cc.js`,
  each through `asset_url()`. It never loads `/static/copy_value.js`: the
  test asserts the script `src`s of a RENDERED cc page (the source holds only
  `asset_url()` calls, so a source grep proves nothing; wave 3), which
  include `/static/cc/copy_value.js?h=` and no `/static/copy_value.js`.
  `test_static_js_syntax.py`'s cc `ON_EVERY_PAGE` set names the cc copies by
  path relative to `static/` (`cc/copy_value.js`), and its subset check
  compares those relative paths, not `p.name`, which `rglob` would make
  ambiguous between `copy_value.js` and `cc/copy_value.js`. It loads `cc/hud.css`, `cc/terminal.css`,
  `cc/components.css` and `cc/phone.css` instead of
  `style.css`/`mobile.css`, and has blocks `title`, `head`, `layout`.
  `<html>` carries `data-ui="cc"` and `data-ui-groups="<the set>"`.
- Body: `.shell > .page` (or `.page.one`, `.page.narrow`), the HUD include,
  the halt line (`cc/partials/halt_line.html`, polled from its own route
  `/partials/halt-line`), the hint sheet (`cc/partials/hint_sheet.html`),
  the dock, a toast slot. The halt line and hint sheet have NEW names on
  purpose: they are shell furniture, not overlays of classic names, so a
  classic page never receives them (R15).
- Classic `base.html` changes in exactly three ways across phases 0-7: its
  `hx-headers` gains `X-CC-UI` (phase 0, R23), `<html>` gains
  `data-ui-groups` (phase 0), and when the HUD is served it renders the
  bare host and one added `<link rel="stylesheet" href="{{
  asset_url('cc/hud.css') }}">` (phase 1, 2.2). Its existing link and
  script lines are untouched.
- Every static URL in `cc/shell.html` goes through `asset_url(path)`, a new
  Jinja global returning `/static/<path>?h=<sha256[:10]>` of the file's bytes,
  computed at startup. A content hash, not `VERSION`, because same-version
  redeploys happen (a CSS hotfix, an OTA bundle, `--allow-replace`; `sw.js`
  says so), and a same `?v=` would pair new HTML with the cached old sheet.
  `sw.js` PRECACHE gets its `cc/` entries from the same map (the route
  already substitutes `__VERSION__`; it substitutes the hash map too).
  **Classic `base.html` is not touched**: `test_mobile_css.py` pins its
  link lines byte for byte, and its PRECACHE entries are unversioned, so a
  `?v=` there would make the classic `/offline` miss the precache
  (`caches.match` matches the query string) and paint bare offline. A test
  renders every page the precache serves offline (chrome off and chrome
  on) and asserts each SUBRESOURCE in it (`link[rel~=stylesheet|icon|
  apple-touch-icon|manifest]`, `script[src]`, `img[src]`; not navigation
  `<a href>`) appears verbatim in PRECACHE, then parses every linked
  stylesheet and resolves each relative or same-origin `url()` in it
  against PRECACHE too (a `data:` URL is exempt: classic `style.css:849-850`
  masks and the grain tile are data URIs). The
  classic page already references five assets PRECACHE lacks
  (`/static/favicon.svg`, `/static/favicon.png`, `/manifest.webmanifest`,
  `/static/copy_value.js`, `/static/tab_memory.js`); phase 0 allow-lists
  exactly those five in the test, with the reason (today's offline
  behaviour, unchanged), and anything new must be precached (section 6,
  R8).

### 2.6 Bracket copy that lives outside templates

Every count here is from the inventory (tokenised, docstrings and comments
excluded).

| Where | Count | Kind | Plan |
|---|---|---|---|
| `alerts.py` | 19-20 lines | copy naming a control (`[ RESUME ]`, `[ UPDATE NOW ]`, `[ SEND A TEST ]`, `[ START SYNCING AGAIN ]`...) | **Leaves the product** by SMTP and webhook. Rewrite in the copy sweep (phase 7). |
| `notices.py` | 11-13 | copy naming a control or panel (`[ COLLECTOR ]` panel "under the fleet grid", `[ DASHBOARD ]`, `[ DOWNLOAD CRASH REPORTS ]`) | Error-severity fixes are emailed too. Some **name a panel that moves** (collector goes to Health). Rewrite with the move. |
| `invariants.py` | 4 lines, 5 names | copy | Emailed through `alerts._check_invariants`. |
| `protection.py` | 4, plus the f-string `[ {label} ]` in `weekly_lines()` | copy, plus state words in the weekly email | Emailed. The f-string is a state word in plain text: keep brackets there, or use `PROTECTED:` (D8). |
| `recovery.py` | 4 | copy (`[ STOP ALL SYNCING ]`, `[ CREATE & LINK ]`, `[ UNDO THIS CHANGE ]`, `[ UNDO LAST FIX ]` which is the TRAY's button) | Rewrite. Also fix "the dashboard has no button for this yet". |
| `cards_pool.py` | 4 | copy (`Press [ OPEN ] to try again`) | Rewrite with the cards landing. |
| `api.py` | 3 | HTTP `detail` an editor reads | Rewrite. |
| `ui.py` | 3 copy (`CHIP_HELP` resume lines, "Use [ START SYNCING AGAIN ]") + 8 `detail_label` values in `_health_rows` (`[ NOTICES ]`, `[ ALERTS ]`...) | labels and copy | Labels move with the Health phase; copy in the sweep. |
| `db.py` | 2 (`href_label` `[ DOWNLOAD CRASH REPORTS ]`, default `[ TAKE ME THERE ]`) | control labels in the `NOTICE_KINDS` registry | **Not stored**: `db.notice_href` computes `(href, href_label)` from the registry at render time, so changing the registry is enough. What IS stored per row is `body` and `fix` (the upsert rewrites `fix` on every write, so an open notice picks up new text on its next write). In phase 7 the registry holds plain labels (`Take me there`), and each variant's template draws them: the terminal key uppercases by CSS, the classic template wraps them as `[ {{ label | upper }} ]` until phase 8. The `href` values are panel anchors: see R13. |
| `collector.py`, `release_feed.py`, `setup_engine.py` | 1 each, plus `setup_engine` run labels (`DO IT`, `GET A SIGN-IN LINK`, `CHECK NOW`, `SAVE A DESTINATION`) which `setup.js` wraps | copy / labels | Rewrite; `setup.js` stops wrapping. |
| `tools/publish_latest.py` | 2 (`Settings > Packages > [ CHECK NOW ] > [ PUBLISH ].`) | operator console text | Rewrite with the packages phase; `tools/tests/test_publish_latest.py` pins it. |
| docs | 355 occurrences in 50 files | docs | Only `docs/HOW_IT_WORKS.md` and `docs/EDITOR_SETUP.md` ship in the image (Dockerfile) and render at `/help`. Those two are rewritten in phase 7. The rest are history; leave them. |
| Companion | 4 literals, all about the tray's own Tk buttons | not the dashboard | Out of scope. |

**The convention for copy that names a control (D8):** the label as it
appears on the key, in sentence case, in double quotes: `press "Resume" on
that computer's row`. It works in an email, a webhook, a tooltip and a page
alike, and it survives a later relabel as a grep target. Templates store key
labels in sentence case, and CSS uppercases them (`.key { text-transform:
uppercase }`), so the quote and the key agree. One mismatch to settle while
rewriting: `alerts.py:3697` says `ASK THIS COMPUTER WHY` and some docstrings
say `ASK THIS MACHINE WHY`. The template is the truth.

---

## 3. JS strategy

### 3.1 The rule that makes folds survive htmx: the frame is static, the body polls

Live panels poll in two shapes. In the first, a wrapper polls and swaps its
own `innerHTML` (`fleet.html`: sidebar, notices, fleet grid, plan changes,
transfers, queue, roots; `admin_users.html` wrappers; `admin_packages.html`).
In the second, a partial replaces itself `outerHTML` (`#admin-jobs` self-poll,
every admin form targeting `closest .admin-users-box`, `#admin-fleet-halt`,
`#admin-sessions`, `#recovery`, `#protection`, `#admin-alerts`,
`#server-notices`, `#plan-changes`, `.queue-box`, `.roots-box`,
`#project-detail` via innerHTML, `.project-setup-box`).

A fold is state on the window element. So:

- **The `.win` and its `.bar` live in the PAGE template, outside the swap
  target.** The polled or form-swapped element is the `.body` (or a child of
  it). A 15 s poll can never touch the bar, the fold state, or the bar's
  button. This is the same rule `test_home_layout.py` already pins for the
  live transfers window ("the poll sits on an inner wrapper, never on the
  panel open tag"). It becomes the rule for every window.
- Where a partial today returns its own frame (every `outerHTML` panel), the
  port splits it: the frame moves into the page, and the partial returns the
  body. The route's response shape changes, so its tests change. Where that
  is too invasive (`admin_packages.html` is 639 lines of rows that also
  target `closest .admin-packages-box`), the fallback is the keeper: fold
  state is re-applied after every swap (below).
- **Every swap-target class or id goes on the `.body` (or a child), never on
  the `.win`.** Users, jobs and audit forms target `closest .admin-users-box`
  outerHTML; RESUME and ASK WHY target `closest .fleet-grid-wrap` innerHTML;
  the same holds for `admin-packages-box`, `roots-box`, `queue-box`,
  `project-setup-box`, `#admin-jobs`, `#recovery`, `#protection`,
  `#admin-alerts`, `#admin-fleet-halt`, `#admin-sessions`. On the `.win`, a
  POST response would replace the whole window, bar and fold button
  included. A test per ported page asserts that no element carrying one of
  these hooks also carries `win`, and that each sits inside a `.body`.
- **Dynamic text in a bar** (counts, "collector 12 s ago", "N issues") comes
  back with the body as an out-of-band swap
  (`<span id="meta-computers" hx-swap-oob="innerHTML">`). `minted_secret.html`
  already uses `hx-swap-oob="true"`, so the pattern is in the product.
  **The oob fragments are emitted only on htmx requests**: the body partial
  is also `{% include %}`d on first render (`fleet.html` includes
  `fleet_grid`, and so on), where `hx-swap-oob` is inert and the span would
  duplicate the bar's id. `_render` sets `oob` in the context when the
  `HX-Request` header is present, and the fragments sit inside
  `{% if oob %}`; the page renders the bar meta itself on first load. A test
  asserts each meta id appears exactly once in first-paint HTML. A partial
  fetched by hand-written JS rather than by htmx (`dashboard_update.js`
  fetches `/partials/admin/dashboard-update` with `HX-Request: true` and
  inserts it with `outerHTML`, with no htmx processing) carries no oob
  fragment at all; a test pins that for the dashboard-update partial.
- **Window ids never reuse a hook or anchor id.** A `.win` that needs an id
  (tab_memory's section fallback, a deep link to the window) gets
  `id="win-<data-win>"`. The panel's own id (`#admin-jobs`,
  `#admin-fleet-halt`, `#recovery`, `#project-detail`...) stays on the
  `.body` or its child: with the same id on the `.win`, `hx-target="#x"`
  resolves to the first match in document order, the window, and an
  outerHTML response replaces the bar. The per-page test asserts that every
  id in each rendered page (first paint plus one htmx response per target)
  is unique.
- **Fold state is keyed by a stable attribute, never the title text.** The
  bench keys on `.t` text, which a count would change. Use `data-win="computers"`,
  stored per path as `ccsync.fold:<path>` in localStorage with try/catch
  (tab_memory's storage pattern, including its blocked-storage no-op).
- **Re-application** uses `htmx.onLoad(elt => ...)`, which fires for every
  element htmx settles, outerHTML included, so it covers the fallback case
  too. It replaces the bench's `MutationObserver` over the whole body,
  which on the 2 s transfers poll would fire constantly.
- **A fold never hides an answer** (wave 3). `.win.collapsed > :not(.bar)` is
  `display: none !important` (`cc-components.css:207`), so an answer, a
  refusal or a deep-link target landing in a folded window is invisible, and
  a `display: none` live region is silent. `cc/cc.js` unfolds WITHOUT writing
  the store: (a) on `htmx:afterSwap` for a request the user started (the
  triggering event is not an `every` poll), the `.win` holding the swap
  target (READ THE ANSWER into `#fleet-diagnostics`); (b) on load and on
  `hashchange`, the `.win` holding `location.hash`, after tab activation and
  before the scroller (3.2); (c) any swap that adds `.error-banner`,
  `.result-banner` or `.htmx-refusal` to a folded body. A folded window with
  open problems shows the count in its bar (the oob meta above) and its fold
  button's `aria-label` says so. Chrome test: fold `#win-diagnostics`, press
  READ THE ANSWER, assert the answer is visible.
- **A one-time secret is never foldable** (wave 5). `minted_secret.html` is
  an out-of-band swap into `#minted-secret` (`admin_users.html:15`), a slot
  nothing polls; MINT's own swap target is `#admin-report-tokens` or
  `.admin-users-box`, so rule (a) would not unfold a folded minted window
  and the password or token, which can never be shown again, would be
  hidden. `#minted-secret` never sits inside a foldable `.win`: its frame
  has no fold button and no `data-win`, and (c) also unfolds for any oob
  swap into `#minted-secret` as a second guard. Chrome test: fold every
  window on Users, mint a token, assert `#minted-value` is visible.

### 3.2 `static/cc/cc.js`: what ships from `shell.js`, and what does not

| shell.js piece | Ships? | How |
|---|---|---|
| `hud()`, `settingsStrip()`, dock | No, as JS | Server-rendered in the partials. The HUD must work in the SPAs, where no script runs. |
| TUNE (`tunePanel`, `applySettings`, `KEY`, the `T` key, `#s=` hash, `storage` sync) | **Never** | Delete. Its values become tokens (D5). A test asserts `tune` appears in no template and no `static/` file. |
| `onData` busy/calm | No | Bench only. The calm states become real empty states in each template (`.empty`, `.allclear`). |
| `issues-variants.js` + the `iv-switch` | No | The chosen variant (D11) is rendered server-side into the fixed-height issues slot. It is a Jinja macro, not JS. |
| The Taipei clock | No (D4) | The zone is hard-coded (`Asia/Taipei`, `TPE`). That breaks "no customer's name in code" and site data, and the SPAs cannot tick it. If wanted, render the site zone's time server-side into the stamp. |
| Busy keys (`data-busy`, min-width lock) | Yes, rewritten | Live already has `.htmx-request .btn` + `.busy-label` + `hx-disabled-elt` (pinned by `test_templates_wave3`, `test_cr335`). Keep htmx's own classes: `.key` keeps its width because the busy label overlays the label (CSS, no JS), and htmx adds `htmx-request`. No toast on completion; the server's result banner is the answer. |
| `data-dismiss` | No | A dismissal is a POST (notices dismiss exists). No client-side-only removal of a server fact. |
| The bench's `are_you_sure` window (dialog confirm) | Yes, rewritten | Below ("Confirms"). |
| Tabs (Site, Health, Recovery's two panes) | Yes, rewritten | Below ("Tabs and deep links"). |
| `foldable()` | Yes, rewritten | Section 3.1. The bar's fold control is a real `<button type="button" class="fold" aria-expanded aria-controls>` as the bar's first child, not a click handler on a `div`. The `type="button"` is load-bearing (wave 4): the Site "studio and tree" and "features" windows sit inside `#settings-form`, whose submit handler PUTs the whole form (`site_settings.js:851`), so a typeless fold would save every setting, become the form's default button for Enter in a field, and also be where DUI-6 anchors banners (`htmx_errors.js:413` selects `button:not([type])`). The fold is rendered by one Jinja macro that writes the type; a `cc/` markup-fact test asserts every `button` under `templates/cc/**` that is not a submit control (`.fold`, `.tip-btn`, tab buttons, popover and dialog openers, `.hud-more-btn`) carries `type="button"`; phase 4 adds a Chrome check that folding a Settings window sends no PUT. The bench's bar is not keyboard-reachable and announces nothing. Click on the bar still toggles (a convenience), excluding a, button, input, select, label. **Names and headings** (wave 6): the fold's only content is the `.fold-g` glyph, which R10 makes `aria-hidden`, so it would announce "button, expanded" with no name, and the titles are snake_case (`shared_folders`, `move_a_file`, `media_presence`, `sync_plan`, `project_roots`, `design/project.html:41-128`) in a `<span class="t">`, not headings, inside an unnamed `<section class="win">`. The fold macro renders the title as `<h2 class="t" id="win-<data-win>-t">` with the underscores in `aria-hidden` spans (or an `aria-label` of the spaced words), the section is `<section class="win" aria-labelledby="win-<data-win>-t">`, and the fold button is always named (`aria-labelledby` pointing at the title, with the problem count appended when folded, 3.1). A `cc/` markup-fact test: every `.fold` button has a non-empty computed name, every `.win` has `aria-labelledby` resolving to a heading, and no heading's accessible name contains `_`. |
| `tooltips()` | Yes, merged with the chip sheet | Below. |
| `toast()` | Maybe | `assignments.js` has its own `#assign-toast`. One toast slot in the shell, used by `assignments.js` and `copy_value.js`. |
| Single-key shortcuts (`site.html:880-883` bare `s` submits `#settings-form` from any non-field focus, including a focused button or tab; `.kbd` keycaps such as `R` on Check now with no handler; 16 `.kbd` hints across the bench) | **Never** (wave 3) | No global single-character action shortcut ships (WCAG 2.1.4; speech input fires them, and this one saves fleet-wide settings). The `/` focus-find of the tree stays, because it only moves focus, and it is ignored when `e.isComposing`, when a control or `[contenteditable]` has focus, or with a modifier. Any action shortcut, if ever wanted, needs a modifier (Ctrl/Cmd+S with `preventDefault`) and is listed in `/help`. `.kbd` hints are dropped from keys, so accessible names stay the label ("Save", not "Save S"); a `cc/` template test asserts no `.kbd` inside a `.key`. |

**Tooltips and the chip sheet become one mechanism.** Today:
`htmx_errors.js` block 2 opens `#chip-sheet` on a TAP of `[data-chip-detail],
.chip[title], .dot[title]`. It reads `data-chip-detail || title`, makes them
`tabindex=0`, and ignores anything inside a control. That is the phone's
tooltip layer, and the only way a touch device reads a chip's explanation
(DUI-3). The bench's `tooltips()` MOVES `title` to `data-tip` on hover.
Shipped as-is, the chip sheet would find no `title` after the first hover
and go blank. So:

- One module (`htmx_errors.js` block 2 generalised, since it must also run
  on classic pages under the HUD) handles
  an EXPLICIT selector: `[data-tip], [data-chip-detail], .tag[title],
  .led[title], .chip[title], .dot[title]` (plus `.hud-led[title]`). The
  selector extension applies whatever `data-ui` says: classic pages carry
  no `data-ui` but carry the HUD from phase 1, and a `.hud-led` there must
  still open the sheet. Only the sheet it fills differs by shell (the
  classic `#chip-sheet` from `partials/chip_sheet.html`, or the same hooks
  in `cc/partials/hint_sheet.html`). Not a
  bare `[title]`: the click handler calls `preventDefault()` and exempts only
  `a, button, input, select, textarea, label`, so a bare `[title]` would
  stop `<summary title>` folds opening (`bins.html`, polled every 5 s;
  `fleet_grid.html`'s clip groups) and give some 150 `span/td/div[title]`
  cells a `tabindex`. `summary` joins the control exemption. On a fine
  pointer, hover and focus show the floating tip. On a coarse pointer, or a
  tap on a matching non-control, open the sheet. The sheet reads
  `data-tip || data-chip-detail || title`. A Chrome-harness test asserts a
  `<summary title>` still toggles its `<details>`.
- Keep `title` in the SERVER markup. It is the no-JS fallback (the HUD in
  the SPAs), it is what six tests pin, and it is an accessible description.
  When the script moves it to `data-tip`, it also sets
  `aria-description` so screen readers keep it.
- `focusable()` keeps adding `tabindex=0` to non-control elements that have
  a tip, so the sheet stays keyboard-reachable.
  `test_bug_hunt_2026_09_24_w2_d-ui.py` l.527 pins exactly this.
- The chip sheet's heading is `chip.textContent`. With tags as "square plus
  word", that is just the word, which is fine.
- **Explanations on controls on touch devices** (wave 3). The bench puts most
  of the owner's requested tooltips on controls (156 `class="key..." title=`,
  180 `<button title=`, 42 `<a title=` across `design/*.html`: Site tabs,
  Save, Check now). Touch browsers never show `title`, and the control
  exemption above keeps a tap on a control from opening the sheet, so on a
  phone those explanations are unreachable. The mechanism: a control whose
  `data-tip` explains an action gets an adjacent
  `<button type="button" class="tip-btn" aria-label="What does Save do?" data-tip-for="<id>">?</button>`,
  rendered by a Jinja macro, shown only under `(pointer: coarse)` and 44 px
  (2.2), which opens the sheet with that control's text. On a fine pointer,
  hover and focus show the floating tip for `.key[data-tip]`,
  `[role=tab][data-tip]` and `.hud-nav a[data-tip]` too, so the look is the
  same as for tags (the server writes `data-tip` plus `title` for the no-JS
  case; the script moves `title` and sets `aria-description`, as for tags).
  A sweep check at 390 on a coarse pointer: every element inside `.page`
  with a `title` or `data-tip` is either a matching non-control or has a
  `.tip-btn` naming it. The HUD in the SPAs (no script) keeps `title` only;
  its words are self-explanatory.
- **The floating tip meets WCAG 1.4.13** (wave 5; the bench's `shell.js:247-277`
  has no Escape, hides on `mousemove` off the anchor while drawing the tip
  12-14 px away from the pointer, opens on every `focusin`, and never clears
  `cur` when htmx replaces the anchor, so the 2 s, 10 s and 15 s polls
  leave a stale tip at the old position). `cc.js`: Escape hides the tip
  without moving focus; the tip is positioned against the anchor's rect,
  not the cursor, and stays open while the pointer is over the anchor or
  the tip (a short hover-intent delay); it hides on `htmx:beforeSwap` when
  the anchor is inside the swapped target, and on `hashchange`; on focus it
  opens only for non-control tip elements, or after a delay for controls,
  so tabbing along a row of keys does not drop a box over the next ones.
  d-ui Chrome tests: Escape dismisses; the pointer can move onto the tip;
  a tip whose anchor a poll removed is gone.

**Confirms.** Today almost every destructive control uses `hx-confirm`,
which calls `window.confirm` and blocks JS, so no poll runs while it is
open. **The exception is the file-move form** (wave 4): `project_detail.html:173-190`
builds its question in `hx-on::confirm` from `[name=path]`,
`[name=to_slug]`, `[name=to_path]` and `data-project-label`, lets an empty
path through to the server's own banner, and calls `window.confirm`. It
carries no `hx-confirm`, so the handler below returns for it (empty
`question`). Decision: `cc/partials/project_detail.html` keeps that handler and its
native confirm verbatim (a native confirm blocks the 10 s poll, so the
detach problem below does not arise), and those field names and the data
attribute are on the 3.3 and R2 hook lists. A later change may move it to
the dialog through a `cc.js` API (`ccConfirm(question, issueRequest)`),
but not in the port. **The same decision covers every confirm htmx does not
issue** (wave 5): ARCHIVE (`admin_assignments.html:171-173`) and the Cards
landing's CLOSE (`cards_landing.html:43-44`) are plain forms with
`onsubmit` confirms, and `assignments.js:137,274,402`,
`dashboard_update.js:235,259` and account.js's add-mode button call
`window.confirm` synchronously. `htmx:confirm` never fires for any of
them, and an `hx-confirm` on a non-htmx form is ignored, so a builder who
"converts" one would ship ARCHIVE or CLOSE with no question at all. They
keep their native confirms verbatim in the cc templates and the
`static/cc/` forks (1.3, 1.4 and 5.3 rows that said "dialog confirm" mean
the htmx confirms only). Test: a rendered cc Sync plans page and a cc
Cards landing still carry the `onsubmit` confirm on ARCHIVE and CLOSE, and
no element under `templates/cc/**` has `hx-confirm` unless it or an
ancestor carries `hx-post`, `hx-get`, `hx-put` or `hx-delete`. A
dialog is asynchronous, and htmx 1.9.12's `issueAjaxRequest` returns
quietly (`if(!se(n)){ie(o);return l}`) when the source element has left the
document. Most confirms sit in polled bodies (`project_detail.html` 10 s,
`admin_users.html` 30 s, `#admin-jobs` 15 s, fleet grid 15 s, plan changes
and notices 60 s), and `busy()` in `htmx_errors.js` holds a poll only for a
focused or typed field, a write in flight, `[data-poll-hold]` or an open
`[popover]` INSIDE the polled root. So a confirm read for longer than one
beat would send nothing. The mechanism:

- One `htmx:confirm` handler in `cc/cc.js`. htmx 1.9.12 fires
  `htmx:confirm` on EVERY request (`var d=ne(n,"hx-confirm");if(e===undefined){...question:d};if(ce(n,"htmx:confirm",U)===false)...`),
  so the handler **returns at once unless `evt.detail.question` is a
  non-empty string** (the 15 s grid poll, the 2 s transfers poll, `pwa.js`'s
  and `account.js`'s `htmx.ajax` calls carry none), and also returns at once
  when the element carries `__ccConfirmed` (below, after clearing the flag
  and calling `evt.detail.issueRequest(true)`). Otherwise it calls
  `preventDefault()`, opens ONE page-level dialog (`#cc-confirm`, a
  `<dialog>` in `cc/shell.html` opened with `showModal()`, never a popover;
  wave 6: a popover is not modal, so a keyboard user whose focus stayed on
  the destructive key could press Enter again, overwriting the stored
  event, or Tab to another destructive key behind it) and stores the
  event. Cancel carries `autofocus`. The `cancel` event and every
  close-without-OK path clear the stored event and remove the temporary
  submitter input (below; `htmx:afterRequest` never fires on a cancel).
  After OK, focus moves to the re-found element, or to its `.win`'s fold
  button when nothing was found (a `<dialog>` restores focus only to a
  still-connected element, so after a detached-source re-dispatch it would
  land on `<body>`). The bench's dialogs are no model: `.dialog-back` is a
  div toggled by `display` (`cc-components.css:170-171`) and
  `jobs.html:168`, `packages.html:464` put `aria-modal` on a non-modal div.
  Chrome keyboard tests: Enter on a destructive key opens the dialog with
  focus on Cancel; Escape sends nothing and leaves no hidden input in the
  form; after a forced re-render of the source, OK leaves
  `document.activeElement` inside the re-found window, not on `body`.
- While it is open, `busy()` holds EVERY poll: a document-level check
  (`document.querySelector('#cc-confirm[open]')`)
  runs before the root-scoped checks. This is a terminal branch of the
  shared script (its classic output is unchanged, since classic pages never
  have `#cc-confirm`).
- **The pressed button is recorded before the dialog opens** (wave 4). htmx
  1.9.12 collects a form's values only when the request is issued, after
  the confirm, and includes the submitter's `name=value` only from
  `lastButtonClicked`, which its `focusout` listener (`Ut`/`Xt` in
  `htmx.min.js`) clears as soon as the dialog takes focus; a re-dispatch by
  `form.requestSubmit()` passes no submitter either. So a two-button form
  (`admin_alerts.html:199`, `name="clear" value="1"` beside SET PASSWORD)
  would post CLEAR as SET PASSWORD. Before opening, the handler records the
  submitter (`document.activeElement` if it is a submit button of
  `evt.detail.elt`, else the form's `lastButtonClicked`); on OK it inserts a
  temporary hidden input with that name and value into the form (removed on
  `htmx:afterRequest`) before `issueRequest(true)` or the re-dispatch
  (`form.requestSubmit(submitter)` when the button is still attached). Chrome
  test: a confirmed two-button form sends the pressed button's value.
- On confirm with the source still in the document, call the stored
  `issueRequest(true)`. With the source detached, the stored
  `issueRequest` is useless: it closes over the ORIGINAL element, and
  `issueAjaxRequest` starts with `if(!se(n)){ie(o);return l}`, so it would
  return silently. Instead the element is re-found by its stable
  `data-confirm-key`, marked `el.__ccConfirmed = true`, and re-dispatched
  (`form.requestSubmit()` for a form, otherwise `htmx.trigger(el, <its
  trigger event>)`); the handler sees the flag and issues without a second
  dialog. If nothing is found, the dialog says so ("this changed while you
  were reading; nothing was sent") instead of doing nothing.
- Chrome-harness tests: (1) open the confirm on `/project/{slug}`, wait two
  10 s beats, confirm, assert the POST was sent; (2) a poll with no
  `hx-confirm` still fires on a cc page while no dialog is open; (3) with
  the dialog open, force a non-poll swap that re-renders the source (a POST
  response re-rendering the body), confirm, and assert exactly one POST is
  sent, from the re-found element.

**Tabs and deep links.** Site's five tabs, Health's four and Recovery's
two-pane picker hide panels that shared Python and templates link to by
hash: `db.py:3635` `/admin/settings#ai-providers`, `admin_settings.html`'s
`#ai-providers`, `recovery.py:955` `/admin/recovery#restore`,
`recovery.py:984` `/admin/packages#dashboard-update`, `recovery.py:939` and
the halt banner's `/admin/users#admin-fleet-halt`, and the Health anchors.
The base.html deep-link scroller and `tab_memory.js` only
`scrollIntoView`, which does nothing on a panel in an inactive tab. So
`cc/cc.js` activates the tab (or the recovery pane) that contains
`location.hash`, on load and on `hashchange`, BEFORE the scroller runs.
Activation alone does not scroll (wave 3): the base.html scroller acts only
on `htmx:afterSwap` for a target inside the swapped fragment, and the
browser's own fragment scroll ran at parse time while the target was in a
`hidden` panel and is never retried. So after activating, `cc/cc.js` calls
`scrollIntoView()` on the target if it already exists (a first-paint anchor
such as `#ai-providers`), and otherwise leaves it to the afterSwap scroller
(a load-triggered anchor such as `#admin-fleet-halt`). The R13 test runs in
the Chrome harness and asserts the target is in the viewport after load,
below the HUD (2.2 scroll-padding), for one first-paint anchor
(`/admin/settings#ai-providers`) and one load-triggered anchor
(`/admin/users#admin-fleet-halt`), besides checking every anchor in R13's
table lands in a panel its hash selects.

**Tab semantics** (wave 3). The bench tabs are `role="tablist"` /
`role="tab"` with `aria-selected` and nothing else (`site.html:44-49`,
`health.html:51-55`, `broll.html:347`, `music.html:289`): no
`aria-controls`, no `role="tabpanel"`, no roving `tabindex`, no arrow keys.
`cc/cc.js` implements the WAI-ARIA APG tabs pattern: each tab has an `id`
and `aria-controls`; each panel `role="tabpanel" aria-labelledby tabindex="0"`
and `hidden` when inactive (so its fields leave the accessibility tree);
roving `tabindex` (0 on the selected tab, -1 elsewhere); ArrowLeft,
ArrowRight, Home and End move and activate. A save refusal that names a
field on another tab activates that tab before scrolling (live
`site_settings.js` `showResult` only scrolls, `:43`). Tests: a markup test
pairs every `role=tab` with an existing tabpanel id; a Chrome keyboard test
(ArrowRight moves the selection and shows the next panel).

**Tabs and `tab_memory.js`** (wave 5). `nearestSection()` (`tab_memory.js:219-250`)
has no visibility check: a heading in a `hidden` panel has a zero rect, so
`top = 0 + y` wins over every visible heading, and the saved section is the
last hidden heading on the page; `attempt()` then scrolls to a Y recorded in
another tab or calls `scrollIntoView()` on a hidden element. So `cc.js`
stores the active tab per page key in its OWN namespace,
`ccsync.cctab:<path>` beside `ccsync.fold:` (wave 6: `ccsync.tab:` is
tab_memory's `PREFIX`, `tab_memory.js:50`, and its `pageKey()` is exactly
`ccsync.tab:/admin/settings` on a page with no view query; its `read()`
drops any value that is not `{t: number}`, so the two writers would erase
each other's state), with the fold store's try/catch pattern, and, when there is no hash (the hash still wins),
activates it on load before tab_memory's first `attempt()`; and
tab_memory's cc branch (`data-ui="cc"`) skips elements with
`getClientRects().length === 0` in `nearestSection()` (classic output
unchanged). Chrome test: on Site, open the AI tab, scroll, navigate away
and back; the AI tab is active and the scroll position restored; and after
both scripts have written on `/admin/settings`,
`localStorage['ccsync.tab:/admin/settings']` still parses as tab_memory's
`{t: number}` entry and `ccsync.cctab:/admin/settings` holds the tab id.

### 3.3 Every script that finds things by selector or by text

From the full inventory. The rule for the port: **behaviour hooks stay by
name** even when the look changes. Keep the class or id as a second class,
or rename it in the script in the same commit.

| Script | Hooks the port must keep (or rename in the same commit) |
|---|---|
| `htmx_errors.js` block 1 | `#htmx-stale-banner` (built in JS; restyle as `.alertline` via its classes `banner alarm stale-banner`), `body[data-stale]`, `--stale-h` (pads the page; the new shell must apply it), `.htmx-refusal` inserted before the host `form, label`. |
| `htmx_errors.js` block 2 (chip sheet) | `#chip-sheet`, `.chip-sheet-label` and `.chip-sheet-text` (it sets their `textContent`), and the `hidden` attribute it toggles. `cc/partials/hint_sheet.html` keeps all three hooks, or every chip tap on a cc page throws a TypeError. Its styling lives in `cc/components.css`/`cc/phone.css` (cc pages only; classic pages keep the classic sheet and its classic CSS). A test renders a cc page and asserts the three hooks. |
| `htmx_errors.js` block 3 (DUI-6) | `.error-banner` / `.result-banner` in every panel, `form-error` / `form-result` added, `[hx-post]`/`[hx-delete]`/`[hx-put]`, hidden inputs to pick the form, `button[type=submit]`. **Every ported panel keeps `.error-banner` and `.result-banner` on its banners** (as a second class next to `.note.err` and `.note.ok`). |
| `htmx_errors.js` block 4 (poll hold) | `hx-trigger` containing `every`; `[data-poll-hold]` (the roots BROWSE picker); `[popover]:popover-open`. A new dropdown or wizard opened INSIDE a polled body (the bench's AI provider wizard, the packages "roll back to" select, the home computer picker) **must carry `data-poll-hold`** or live inside a popover, or the next beat closes it. Select changes are already protected (typed/dirty tracking), but a custom picker built from buttons is not. |
| htmx `hx-preserve` (wave 3) | `project_detail.html:337` `<div id="missing-{{ loop.index }}" hx-preserve="true">`, the target of `[ MISSING FILES ]` (`:333`), survives the 10 s `#project-detail` poll only because htmx swaps the preserved element back by id. Every `hx-preserve` element keeps an id that is stable across polls; the terminal "opens inline" missing-files list keeps this element and is not wrapped in a new element without one. **The id is keyed by computer, not by loop index** (wave 5): `missing-{{ loop.index }}` shifts when `project.editors` gains or loses a report-only row (`api.py:494-500`) between beats, and htmx then swaps the preserved list back under another computer; the cc template uses `missing-{{ e.device_id }}` (already in the route URL) for both the `hx-target` and the preserved id, and **renders the preserved div only when `e.device_id` is set** (wave 6): report-only rows carry `"device_id": None` (`api.py:500-501`) while the classic preserved div is rendered for every row (`project_detail.html:337`) and the button only `{% if e.need_items and e.device_id %}` (:331), so two computers without Syncthing (wired rigs, upload-only laptops) would give duplicate `id="missing-None"`, and htmx's preserve pass would match the wrong element. The phase 2 state matrix gains a project with two report-only rows, and the id-uniqueness assert (3.1) runs over it. The phase 2 Chrome check also adds a row between beats and asserts the open list stays under the same computer. Phase 2 adds a Chrome check that an opened missing-files list survives two 10 s beats in the terminal variant. |
| base.html inline keeper | `details[data-key]` and `[popover][id]` across swaps; `liveRoot()`. Nested folds inside a window stay `<details data-key>` (the bench's `.fold` is `<details>`), so they are kept for free. |
| base.html deep-link scroller | `/#server-notices`, `/admin/users#admin-fleet-halt`, `/#fleet-collector`. If notices move to Health, the topbar's problems link and `db.py`/`notices.py` hrefs change with them. **Until phase 5 switches them to `/go/<panel>`, `db.NOTICE_KINDS` links six kinds to `/#fleet-collector` (`db.py:3448-3612`) while `home` is already on** (wave 4): so the terminal home keeps `id="fleet-collector"` on the collector body in `partials/home_collector.html`, and `id="server-notices"` on the problems body in `partials/home_problems.html` (the dismiss target needs it anyway), until the classic home is deleted. The phase 2 test resolves every `NOTICE_KINDS` href against a rendered cc home. |
| Inline `hx-on` hooks (wave 4) | The file-move form's `hx-on::confirm` reads `[name=path]`, `[name=to_slug]`, `[name=to_path]` and `data-project-label` (`project_detail.html:173-190`, 3.2); the account page's `hx-on:htmx:after-request` handlers (`account_computer.html:38,63,67,72,109`) find `.account-pc` by `closest()` and fire the `account-refresh` event its poll listens for. Both are kept by name in `cc/partials/project_detail.html` (phase 2) and `cc/partials/account_computer.html` (phase 3). |
| `account.js` (wave 5; forked to `static/cc/account.js` in phase 3, 2.1) | `#account-pw-*` (the length and match hints), `.account-add [data-add-mode]` (its native confirm, 3.2), `data-panel`, the `jobs_kinds` fields and `.account-last-kind` (the "keep one kind" refusal). The cc copy writes cc tag or note classes instead of `field-hint amber|ok|muted` and `account-result red`. |
| `tab_memory.js` | Open `<details>` with an id or `data-key`; sections `h1[id]..h4[id], section[id]`; scroll. The new window folds are not `<details>`, so tab_memory does not keep them, but the fold store (3.1) is per-path and persistent, so it covers them. Give every `.win` an `id="win-<data-win>"` (never a hook or anchor id, 3.1) so the section fallback still works. Not active on SPA prefixes. |
| `pwa.js` | `#install-slot` (in the HUD's `#hud-more` from phase 1, on classic pages too); it builds `button.btn.chip.tap.install-btn` with `[ INSTALL ]` in a classic slot and, by the 2.1 branch on `slot.closest('.hud-more')`, a `button.hud-key` with an unbracketed label in the HUD slot (hud-common paints `.hud-key`; a test per slot); it rewrites `hx-trigger` intervals on coarse pointers (2 s to 10 s, 5 s to 15 s): keep the poll intervals literal in templates so this still matches. |
| `copy_value.js` | `.copy-btn`, `data-copy-from`, `data-copied-label`, and it writes `[ COPIED ]`, `[ SELECTED - PRESS CTRL+C ]`, `[ COULD NOT COPY ]` into `textContent`, which **flattens a keycap's inner spans**. Change it to write into the key's `.t` span. |
| `dashboard_update.js` | `#dashboard-update[data-running]`, `#dashupd-progress` (it sets `className` to exactly `"banner"` or `"muted"`, wiping any terminal classes), `#dashupd-refusal`, `#dashupd-restore-db`, `#dashupd-schema`. It reads `data-dashupd-*` from `evt.target` itself, **so a click on a span inside a keycap does nothing.** Use `closest()`, and set classes with `classList`. It runs two flows: an older bundle through `runUpdate` (`data-dashupd-apply` + `data-dashupd-older=1`) and an image rollback through `ROLLBACK_URL` (`data-dashupd-rollback` + `dashupd-restore-db`). A `<select>` carries no per-option attribute on the clicked element, so the terminal control is a select plus a key whose `data-dashupd-*` value the script sets from the select on change, one pair per flow, never one merged list. It ships as `static/cc/dashboard_update.js` (2.1), with a test per path. Its hand-rolled `fetch(PARTIAL_URL, {headers: {"HX-Request": "true"}})` carries no body `hx-headers`, so the cc copy also sends `X-CC-UI` read from `<html data-ui-groups>` (R23); the partial carries no oob fragments (3.1). **The cc copy obeys `HX-Refresh`** (wave 6): `reloadPanel()` checks only `!resp.ok || HX-Redirect` (`dashboard_update.js:68`), so R23's "cannot serve" answer (200, `HX-Refresh: true`, empty body) would run `host.outerHTML = ""` and erase `#dashboard-update` with `#dashupd-progress` and `#dashupd-refusal` inside it, exactly after a failed update or a watchdog revert. The cc copy reloads the page on `HX-Refresh: true` before reading the body, and on a 409 carrying `X-CC-UI-Want` shows the line and keeps the panel. Test in the phase 4 d-ui harness: against a stub answering 200 + `HX-Refresh` with an empty body, `reloadPanel` calls reload and `#dashboard-update` stays in the DOM; against 409 + Want it shows the line and keeps the panel. |
| Any script that fetches a `/partials/` URL itself | **General rule:** it sends `X-CC-UI`, `X-CC-UI-Gen` and `X-CC-UI-Sig` read from `<html data-ui-groups>`, `data-ui-gen` and `data-ui-sig` (both shells emit all three attributes beside `hx-headers`, wave 4), or the response is classic (an htmx-shaped request with no `X-CC-UI`, R23 and 7.0, wave 6). It also treats `HX-Refresh: true` like `HX-Redirect` (`location.reload()` before reading the body) and a 409 with `X-CC-UI-Want` as an error line, never a swap (wave 6). The SPAs' topbar fetch is the one deliberate exception: it sends no `HX-Request` and has no dashboard page to follow, so it follows the cookie and setting. |
| `confirms.js` | `select[name="policy"]`, `data-previous`. Unaffected. |
| `assignments.js` | `#assign-grid`, `#assign-toast`, `#assign-filter`, `.matrix-check`, `.matrix-upmode`, `.assign-upmode(.on)`, `.assign-copy`, `[data-col-all]`, `[data-col-none]`, many `data-*`; writes `"[ n / total ... ]"` into the button. |
| `site_settings.js` | About 13 ids; builds the whole AI PROVIDERS UI (`.ai-provider`, `.ai-wizard`...) with 21 bracketed labels and inline styles (`1px dotted #2a2a31`). The bench's picker and wizard is a **rewrite** of this file's render half, not a restyle. |
| `setup.js` | 13 ids; builds rows with `chip` + status, `[ CREATE ]`, and wraps labels as `"[ " + label + " ]"`. |
| `cards_landing.js` | Its own `cl-*` vocabulary. Unaffected unless the port renames `cl-*`, and it should not. |
| `account.js` (new, in flight) | Whatever group F writes. Rule for them: hooks by id or `data-*`, never by `.btn`/`.chip` or by label text. |
| `tools/mobile_sweep.js` | Tap check `button, a.chip, .btn, input, select`: add `.key, a.tag, .fold`. Scroll exemption `.closest('.scroll-x')`: keep the class name (the bench has `.scroll-x` too). Project discovery `a[href^="/project/"]`: keep that href shape in the tree. |

### 3.4 What the HUD must keep from the live topbar

- `data-dash-topbar` on an element inside the partial. The SPAs refuse to
  inject without it. Keep it on the brand link, with `data-csrf`.
- **Every class and id in `cc/partials/topbar.html` is HUD-owned**: prefixed
  `hud-` (`.hud-led`, `.hud-hide-sm`, `.hud-user`, `.hud-key`, `.hud-dock`,
  `#hud-more`, `.hud-more*`) or scoped under `.hud`/`.hud-dock` inside
  hud-common. The bench's `.led`, `.hide-sm`, `.user` and `.key` exist in no
  SPA sheet (so the LEDs would be invisible and `hide-sm` items would show on
  phones in the SPAs), and a phase 6 SPA body restyle that brings `.key` or
  `.led` would then restyle the HUD. No HUD selector reuses a classic name
  (`.nav-drawer`, `.drawer-item`, `.menu-btn`, `.gear-link`, `#nav-drawer`),
  so hud-common and the classic drawer block never select each other's
  markup. A test extracts every class token from the RENDERED chrome
  (wave 4: the source of `cc/partials/topbar.html` misses the included
  stamp, whose classic form uses `.banner` and `.stamp-at`, and the
  settings strip): `/partials/topbar` as admin and as editor with nonzero
  counts, `/partials/stamp` with Syncthing reachable and unreachable, and a
  rendered cc `settings_nav`, and asserts each token is `hud-`/`snav-`
  prefixed or has a rule inside the hud-common block.
- **The host.** Classic `base.html` wraps the include in
  `<header class="topbar">` and the SPAs inject into
  `<div class="topbar" id="dash-topbar">`; every sheet has
  `.topbar { display: flex; flex-wrap: wrap; padding... }` and
  `.topbar > * { flex: 0 0 auto; white-space: nowrap }` (pinned by
  `test_every_topbar_child_is_an_unbreakable_unit`), plus classic phone rules
  (`.topbar .session { display: none }`, safe-area padding). Under those the
  HUD would shrink-wrap, never wrap, and get the safe-area inset twice. So:
  `base.html` renders `<header class="topbar">` and the `.rule` only when the
  classic topbar is served, and a bare `<header class="hud-host">` when the
  HUD is (`display: contents`, so the HUD sticks, 2.2); hud-common carries
  `#dash-topbar:has(> .hud)` resets (`display: contents`, padding 0, `> *`
  flex and white-space reset) for the SPAs, whose
  markup the dashboard does not control. A test in each SPA suite and in the
  dashboard suite asserts the reset exists. The unbreakable-unit test stays,
  for the classic markup only.
- **No `<script>`** in the partial (`test_topbar_partial.py` checks). Every
  interaction is a link, a plain form, or the popover API.
- The problems and alerts counts are **absent at zero** (the UX-10 and
  SYS-8 rule: a permanent "0 problems" stops being read). The bench always
  shows them. The product rule wins. **In the SPAs** (wave 3): `_render`
  computes `notice_counts`/`alert_counts` only for names not starting
  `partials/` (`ui.py:707`, `:717`), and `/partials/topbar` renders
  `partials/topbar.html`, so the injected HUD would never show them.
  `partial_topbar` computes the two counts itself (the same safe helpers,
  one cheap read per SPA load), and the terminal twin asserts counts appear
  when nonzero through `/partials/topbar`.
- Sign out and sign out everywhere (C-9 `window.confirm` in `onsubmit`, a
  plain form with the hidden `csrf` field), the installer link to
  `/download`, help, the settings entry for admins and transfers for editors,
  modules only when mounted (`broll_mounted`, `music_mounted`,
  `ytdl_mounted`, `cards_mounted`), and trailing slashes on `/broll/`,
  `/music/`, `/ytdl/`, `/cards/`. On desktop they live in a user menu
  (`#hud-user`, a popover). `popovertarget` does nothing on an `<a>`, so it
  is two controls: the user name stays `<a href="/account">`, and beside it
  a `<button popovertarget="hud-user">` opens the menu (sign out, sign out
  everywhere, installer, help). On phones they live in the "more" sheet.
  The phase 1 HUD test asserts that every `popovertarget` in the partial
  sits on a `<button>`. **No popover base rule declares `display`** (wave
  3): an author `display` beats the UA's
  `[popover]:not(:popover-open){display:none}`, which is why the classic
  drawer has `test_the_drawer_base_rule_declares_no_display` in each SPA
  suite. The phase 1 hud-common test pair in all four suites (and the `cc/`
  CSS-fact file) asserts the base rules for `.hud-more`, `#hud-more` and
  `#hud-user` declare no `display` (only their `:popover-open` rules do) and
  each has explicit positioning; otherwise the menu is permanently open, in
  flow, on every page and inside every SPA's `#app-header`, where the
  ResizeObserver inflates `--header-h`.
- **The user menu links to the look switch** (wave 3). `#hud-user` (desktop)
  and `#hud-more` (phones) carry plain `<a>` links to
  `/ui/preview?variant=cc`, `?variant=classic` and `?variant=site`, and the
  classic `/account` page carries the same three, because an installed iOS
  app (`manifest.webmanifest` `"display": "standalone"`) has its own cookie
  jar and no URL bar: a cookie set in Safari never reaches it, and a URL
  cannot be typed there. `/ui/preview` redirects back to a same-origin
  `next` or `Referer`. **The links carry an explicit `next`** (wave 5):
  `_safe_next` (`ui.py:893-900`) keeps only strings starting with `/`, and a
  browser's Referer is absolute (`https://host/broll/`), so it would always
  give `/`; inside a SPA the partial is fetched from
  `/partials/topbar?current=broll`, so a request-derived `next` would be
  that URL. The partial derives `next` from `nav_current` for the SPAs
  (`/broll/`, `/music/`, `/ytdl/`, `/cards/`) and from the request path for
  full pages. A Referer, when used, is parsed with `urlsplit`, its netloc
  must equal the request host, and only `path?query` goes to
  `_safe_next`. Test: `/ui/preview?variant=classic` with `Referer:
  https://testserver/broll/` and no `next` redirects to `/broll/`.
  **Nobody opts into unreviewed templates by default** (wave 4, tightened
  in wave 5; D14 and "the owner sees it before editors"): the
  dashboard-only site setting `ui_preview` is `off` (vendor build),
  `admins` or `everyone`. It replaces the earlier boolean
  `ui_preview_allowed`, under which every customer admin could switch into
  half-ported templates from phase 1 while the phases ride the vendor
  feed. `variant=cc` answers 403 unless the role is allowed by it; this
  studio sets `admins` through `tools/ui_variant.py`; customers get it only
  if D14 is decided the other way. The `classic` and `site` links are
  available to everyone. Tests: with `off`, an admin's `?variant=cc` is
  403, `/account` shows no cc link, and a stored admin `ccsync_ui=cc`
  cookie is read as absent; with `admins`, an editor's is 403 and
  `/account` shows the cc link only to admins.
- **Signed-out pages** (wave 5). Phase 3 ports `login` and phase 4 `setup`.
  If a signed-out request ignored the cookie, neither could be previewed;
  if it honoured an unsigned one, anybody could opt in, and a signed-out
  owner would be stranded on a broken cc login (`/ui/preview` needed a
  session; the installed app has no URL bar). So:
  `GET /ui/preview?variant=classic|site` works WITHOUT a session (it only
  removes a look); the cc login page carries a small "use the classic look"
  link to it; `variant=cc` writes a SIGNED cookie value (an HMAC with the
  session secret over `cc` and the admin username who set it); a
  signed-out request honours `ccsync_ui=cc` only when the signature
  verifies, that username is a current admin and `ui_preview` is not `off`;
  logout (`auth.end_session`) keeps the cookie. **`/ui/preview` is an open
  path** (wave 6): `login_gate` passes only `_open_path()` paths
  (`app.py:56-74`, `:166-170`), so without an entry the signed-out escape
  link is redirected to `/login?next=/ui/preview...`, which renders the same
  cc login: a loop. Phase 0 adds `/ui/preview` to `_OPEN_GET_ONLY` (GET and
  HEAD only), and the route itself refuses `variant=cc` without a session.
  `test_bug_hunt_2026_09_18_dashboard_mediums.py`'s open-path method test
  gains the entry, and a POST to it is still sent to login. Tests: a
  signed-out GET `/ui/preview?variant=classic` answers the redirect to
  `next` with the clearing `Set-Cookie`, not a 303 to `/login`; a signed-out
  `?variant=cc` is refused; a signed-out
  `?variant=classic` clears the cookie; an unsigned `ccsync_ui=cc` on
  `/login` renders classic; a signed admin cookie renders
  `cc/login.html`.
- The stamp and its 30 s poll. Keep it as `#topbar-stamp` in the HUD meta.
  Its poll inherits the page's `X-CC-UI` group set (R23), which includes
  `chrome` on every page that shows the HUD, classic bodies included, so
  it always gets `cc/partials/stamp.html`. A phase 1 test renders a
  classic page with only `chrome` on, takes its `hx-headers`, GETs
  `/partials/stamp` with them and asserts the cc stamp; its mirror (a cc
  page after `chrome` is switched off) still gets the cc stamp.
  The bench's "updated 3 s ago" in each page head is what the stamp says, so
  one of the two goes. Recommended: the HUD, because it is on every page,
  the SPAs included. **On phones** (wave 4): the stamp carries
  `▲ SYNCTHING UNREACHABLE: data may be stale`, and the bench hides
  `.hud-meta .hide-sm` at 760 in a fixed 52 px nowrap row. At 600 and
  below the HUD keeps a compact stamp: an LED plus the word `stale` when
  Syncthing is unreachable (the full sentence opens in the hint sheet on a
  tap), and nothing when all is well. The sentence is NOT repeated in
  `#hud-more` (wave 6): the 30 s poll replaces only `#topbar-stamp`'s
  innerHTML (`topbar.html:211-214`), so a copy elsewhere would be rendered
  once per page load and its "data may be stale" warning would itself go
  stale, which `_stamp_context`'s docstring (DUI-2) calls worse than no
  banner. The sheet reads the polled compact stamp's own `title`/`data-tip`. Phase
  1 adds a terminal twin rendering `cc/partials/stamp.html` with
  `stamp_syncthing_reachable=False`, and a sweep assert at 390 that the
  warning element has a nonzero box.
- The phone: the bench dock is five links with the last one "more"
  (`index.html` on the bench). In the product "more" is
  `popovertarget="hud-more"`: a NEW popover (`#hud-more`, `.hud-more*`),
  not the classic `#nav-drawer`, holding music, youtube, settings,
  installer, help, the user and sign out, the chips, and `#install-slot`.
  The dock is **inside the partial** so the SPAs get it, and a sibling of
  `.hud` (section 2.4). Everything fixed at the bottom is lifted by
  `--cc-dock-h` (2.2), and `tools/mobile_sweep.js` gains an occlusion
  check: at 390, scrolled to the bottom, `elementFromPoint` at the centre
  of every fixed bottom control and of the last focusable element on the
  page must be that element, not the dock.
- `nav_current` marks the entry; `?current=` from the SPAs. The bench's
  settings mapping (`transfers` lights transfers, every other settings key
  lights settings) matches `SETTINGS_PAGES`.

### 3.5 JS-built labels

`site_settings.js` (21), `ytdl/app.js` (17, SPA-internal), `copy_value.js`
(3), `setup.js` (1 plus two built by concatenation), `pwa.js` (1),
`assignments.js` (1 built). Each is rewritten in the phase of the page it
belongs to, to build `<button class="key"><span class="t">Label</span></button>`
and to write busy text into `.t` only. The rewrite is a `static/cc/` copy
(2.1); the classic file keeps its bracket output until phase 8.

---

## 4. The SPAs and Cards

### 4.1 The injected topbar contract

- `/broll/`, `/music/` and `/ytdl/` each `fetch('../partials/topbar?current=<app>')`
  (document-relative, pinned by their `test_mounted_prefix.py`). They bail
  unless `res.ok && !res.redirected` and the body contains
  `data-dash-topbar`, then set `#dash-topbar.innerHTML`. broll and music
  measure `#app-header` with a ResizeObserver and set `--header-h`, so a
  taller HUD (58 px against today's wrapping bar) is absorbed. ytdl must be
  checked (it has no observer in the inventory).
- The partial is painted by **each SPA's own stylesheet**. So the HUD's CSS
  must exist in four places, like the drawer block today ("IDENTICAL in all
  four stylesheets"). Plan: a new `/* ==== hud-common BEGIN ... END */`
  block, byte-identical in `dashboard/static/cc/hud.css` (the dashboard's
  one copy, loaded by both shells, 2.2),
  `broll/web/static/style.css`, `music/web/static/style.css` and
  `ytdl/web/static/style.css`, with a test pair in each of the four suites
  modelled on `theme-common`'s. Its selectors are all `.hud*` (the dock is
  `.hud-dock`, the more sheet `#hud-more`/`.hud-more*`) and `.snav*`, or
  scoped under `.hud`/`.hud-dock`; never a classic name (3.4). It carries no
  `body`, `html`, `:root` or font rule (the share page loads b-roll's
  `style.css`, R22), and its phone query follows 2.2. Its tokens are
  **namespaced** (`--cc-red`,
  `--cc-hi`, `--cc-bg`...), because each SPA already defines `--red`,
  `--panel`, `--field` with different values, and a HUD that read `var(--red)`
  would take the SPA's red. They are declared on `.hud, .hud-dock,
  .hud-more` inside the block; `--cc-dock-h` is not one of them (2.2).
- **Classic pages get the block through `cc/hud.css`**, which classic
  `base.html` links only when the HUD is served (2.2, 2.5). Classic
  `style.css` never carries it. So four copies throughout, and
  `cc/hud.css` is the dashboard's `FLEET_STYLESHEETS`-style reference for
  hud-common in all four suites' identity tests.
- The drawer block that exists today (menu button `::before "["`, `.nav-drawer`,
  `.drawer-item`, `.gear-link`) is pinned in all three SPA
  `test_theme_css.py` files. **hud-common is ADDED beside it, never in its
  place.** Whenever the chrome group is off (every vendor customer until
  phase 8, this studio after a rollback, a browser with the `classic`
  cookie), `/partials/topbar` still serves the classic menu and drawer, and
  all four sheets must still paint it. The classic drawer block and its pins
  are deleted in phase 8. A phase 1 test renders the classic topbar with the
  chrome group off and asserts each SPA sheet still carries the drawer
  block.
- **ytdl's root-relative scan is deny-by-default** across `style.css` and
  the served `/ytdl/` index, raw, comments included
  (`test_mounted_prefix.py:39`, `["'`(](/...)`): any `"/..."`, `'/...'`,
  `` `/...`` or `(/...` except bare `/` fails. The rule for hud-common (and
  so for the other three identical copies): no quote, backtick or `(`
  immediately before `/` ANYWHERE in the block, comments included; write
  URL-like examples in comments without that prefix. The live separator is
  `\2f\2f` for exactly this reason. The bench's `.hud-nav a .slash` is
  `&gt;` in markup (fine) and `.snav a::before { content: ">" }` (fine).
  The phase 6 first script in ytdl's `index.html` reads the cookie with
  `document.cookie.split('; ')`, never a regex literal such as
  `match(/(?:^|; )...` (its `(/` fails the served-index scan).
- **em dashes**: the broll and music scans read `static/**` raw, comments
  included. No em dash in any shared block, even in a comment.

### 4.2 Fonts in the SPAs

A `url()` in a stylesheet resolves against the STYLESHEET's URL, not the
document's. music and ytdl serve their sheet at `/music/style.css` and
`/ytdl/style.css`, so `url(../static/fonts/x.woff2)` lands on the
dashboard's `/static/fonts/`. b-roll links `static/style.css`, served at
`/broll/static/style.css` by its own `StaticFiles` mount, so b-roll needs
`url(../../static/fonts/x.woff2)` (the single `../` would hit
`/broll/static/fonts/`, a 404). Both pass the root-relative scans because
they start with `.`. Standalone dev (no dashboard) falls back to Consolas,
which is acceptable. The `@font-face` rules sit OUTSIDE hud-common, because
the path differs per sheet. In b-roll they are harmless on the share page
only because the HUD's font-family rule is scoped to `.hud*` (the share
page has none); the fonts are not in `SHARE_ASSETS` and must not be needed
there (R22). **The font checks run in the dashboard suite**, where the
fonts live (wave 4: no SPA suite imports `ccsync_dashboard`, the SPA
mounted tests mount under a bare `FastAPI()` with no `/static/fonts/`, and
the dashboard venv cannot import `musicweb`, `test_music_mount.py:8-10`).
For each SPA the test reads its `style.css` from disk, parses the
`@font-face` src urls, resolves them with `urljoin` against that sheet's
KNOWN served URL (`/broll/static/style.css`, `/music/style.css`,
`/ytdl/style.css`), asserts the result is under `/static/fonts/`, and GETs
it from the dashboard's `create_app()` (200, `font/woff2`; this needs the
`mimetypes.add_type` of 2.3, or `StaticFiles` sends `text/plain`). No SPA
import is needed. Each SPA suite may keep a disk-only resolution test.

### 4.3 What changes in which repo

| Repo / tree | Changes |
|---|---|
| ccsync `dashboard/` | Everything in sections 1-3. |
| ccsync `broll/web/static` | Phase 1: hud-common + fonts; both `index()` and the `/static` mount send `Cache-Control: no-cache`, with no markup change (R16, the option chosen in wave 3). Phase 6: body restyle in `style.css`/`app.js`/`ingest.js`/`clientfolders.js`, every new rule under `html.cc` (own tests: `test_theme_css.py`, `test_mounted_prefix.py`, `test_no_em_dashes.py`, the w2 contrast pins). `share.*` untouched (D10), but `share.html` loads `style.css`, so R22 applies to every change there. |
| ccsync `music/web/static` | Same shape. |
| ccsync `ytdl/web/static` | Same shape. Plus 17 JS labels and `test_static_app.py`'s 28 bracket literals. |
| MulticamPipeline (Cards page) | Nothing. It does not inject the topbar, and its tests pin nothing of the dashboard's. If the owner wants the Cards page in the terminal look, that is its own plan in that repo, deployed by its snapshot deploy (D9). |
| Companion | Nothing. |

The SPAs ship INSIDE the dashboard image (`Dockerfile`: `COPY broll/web
/broll-app` and so on) and inside the OTA bundle (`tools/build_dashboard_bundle.py`
maps `dashboard/static` and the sub-apps). One deploy carries all four.
`dashboard/design/` is not copied into the image (good; keep it that way).

---

## 5. Invented behaviour vs pure restyle

Tagged **BACKEND** (a new route, view data, or a behaviour change) or
**UI** (presentation over what exists). A BACKEND item is its own ticket.
It is not part of a port phase, and the port phase ships without it: the
key is hidden, or the older control stays, until the ticket lands.

### 5.1 Home

| Item | Tag | Note |
|---|---|---|
| Readouts (online x/y, moving GB, problems open, in sync x/y) | UI | Aggregate in the `/` and `/partials/fleet` view builders from data they already load. Poll with the grid (oob into the readouts). **Nothing ticked is never a warning** (wave 6; the owner's rule, restated 2026-09-18): the "online" readout leaves every computer whose `why.reason == 'no_selection'` out of its denominator and its foot, and never takes a warn tone because of one (the bench turns it `warn` with "TCHEN-RIG silent 2 h", `design/home.html:93`). **"Problems open" is the HUD's count** (wave 6): the live topbar counts error-severity notices only (`topbar.html:45-47`, `notice_counts.error`), while the bench readout counts every open notice (`home.html:95`: 4 open, 2 err plus 2 warn); the readout uses the same `notice_counts` helper, shows errors as the number, and warnings as a secondary "n warnings" foot. Phase 2 test: for a seed with error and warn notices, the HUD count and the readout number agree. |
| Stop the fleet key | BACKEND (small) | POST `/partials/admin/fleet-halt` exists (on Users), but it refuses `active=1` with a reason under 3 characters ("say why: every editor's tray will show this") and answers with `partials/fleet_halt.html`, the Users panel (`.admin-users-box#admin-fleet-halt`, START/KEEP/history). The home key opens a dialog with a reason input; the form posts with an hx-target on home and gets a compact response (a small new partial, or `HX-Trigger` that refreshes `/partials/fleet-halt-banner` at once instead of up to 60 s later). Until that lands, the key is a link to `/admin/users#admin-fleet-halt`. Admin only. |
| Check now (force a collector pass) | BACKEND | No route. It is also a load risk (the collector is not re-entrant-safe by design). Needs a debounce. |
| problems.log restyle of notices | UI | Keep per-notice dismiss (POST exists) and its confirm. **The dismiss answers with the classic `partials/notices.html`** (`ui.py:1845-1858`, error branch included), which would swap a classic `admin-users-box` into the terminal window (wave 4). The route picks its answer with `?view=home-problems` or `?view=health-notices` (the toggle's `view=` pattern): it renders `partials/home_problems.html` or `partials/health_notices.html`, and answers 404 when that group is not in the resolved set; no `view` keeps the classic answer. The cc templates post with the view. Test in both variants: a dismiss from each cc panel returns that panel's markup and never `admin-users-box`. |
| Dismiss all | BACKEND | Only per-notice dismiss exists. |
| Computers: fixed three-line rows, issues inline worst first | UI | **The row keeps `fleet_headline`** (wave 6): the classic row leads with `e.headline` from `health.fleet_headline` (`fleet_grid.html:187-203`), whose `muted` level covers a computer with nothing ticked, and `health.py` keeps a SILENT nothing-ticked computer muted, never amber (logic-sync-truth-1); the bench row has no headline field and draws a silent computer as LED `off` with lanes `warn` "not heard from" (`design/home.html:105-109`, `:154-157`). So the cc row keeps `e.headline.text` as one of its fixed lines, and the row LED and lane tones come from `e.headline.level`, never recomputed from lanes or silence. Phase 2 test: a computer with nothing ticked, silent 7 h, renders no `warn` or `err` class on its row or on the readouts, and the muted "Nothing ticked for this computer. Last report ..." sentence. Issues come from the chips behind today's `[ DETAILS ]`. Pick one variant (D11). A row scrolls inside its slot, per the owner's round 2 rule, **on a fine pointer only** (wave 5): the bench's `.pc .issues { overflow-y: auto; overscroll-behavior: contain }` still applies at 1100 and below (`cc-terminal.css:363-366, 494`), so on a phone a vertical swipe that starts on any computer with more than two issue lines scrolls a 48 px strip and never the page, and Safari cannot reach the hidden issues by keyboard. Under the phone query and `(pointer: coarse)` the issues column is not a scroller (the first N issues plus a nested fold); elsewhere the slot gets `tabindex="0"` and an `aria-label` naming the computer; `--lane-h` and the row height are in `em`/`lh`, not px, so text scaling does not overlap the lanes (WCAG 1.4.4). Sweep at 390: a vertical scroll that starts over `.pc .issues` moves the page. |
| Lane meter with a percent per lane | BACKEND | Lane chips carry state and a label, not a fraction. Check `lane_report_current` for bytes owed and total; if absent it needs the companion to report it (then it is a companion change too, and out of the "companions untouched" rule). **Recommended: ship the meter as state-only (full / empty / animated busy) until the data exists.** |
| Version "N behind" | dropped (wave 6) | The package store cannot count it: a delete removes the row (`db.py:4939`, `:4959`), so on any site that prunes old builds "28 behind" (`design/home.html:109`) would read far fewer, and the gap is per kind and platform. The row shows running and current version, which the headline already says ("Out of date: running X, current is Y"). A count, if ever wanted, is BACKEND over a history deletes do not touch (the vendor feed's release list or an append-only published-versions record). |
| "on since 08:02" per computer | dropped (wave 6) | No data source: the fleet view has no machine-uptime or session-start field (only `poll_runs.started_at` for the collector), and a local clock time in an unstated zone is not how the product states times. The row's second line is the existing last-report time through the `ago` filter. A real "on since" would be BACKEND plus a companion field, outside the "companions untouched" rule. |
| Collector age in the computers bar | UI | From `collector_health`. |
| Computer picker next to the editor picker (ticking_for) | BACKEND (small) | The toggle WRITE takes `machine=`, but the RESPONSE does not follow it: `partial_toggle` picks its answer by `?view=` (`sidebar` or an hx-target containing "sidebar" renders `partials/sidebar.html`, `project` renders `project_detail`, anything else falls through to `partials/my_queue.html`), and `_sidebar_context` calls `db.fetch_selections(conn, toggle_editor)` with no machine, so after a tick or a 30 s poll the tree would show the person's union (the dash-api-4 shape). Needed: a `view=tree` branch rendering the new tree partial, and `machine` carried in the tree context, the tick response and the poll URL. **And `as_qs`** (wave 4): the classic sidebar poll carries `?as=` (`fleet.html:4-7`, `_as_qs` at `ui.py:809`), because a refresh that dropped it re-rendered the checkboxes against the ADMIN'S OWN ticks, so the next click ticked the project onto the admin's machine. The tree context, the `/partials/projects-tree` poll URL and the `view=tree` tick response carry `as_qs` built with `_as_qs`, as well as `machine`. Tests in both variants: a tick from the tree returns tree markup with that machine's ticks; an admin with `?as=bob` polls the tree and gets bob's ticks, and a tick after the poll goes to bob. |
| Project tree find box, `/` key, "n of m ticked" | UI | Client-side filter. The tree is re-rendered every 30 s (poll), so the filter text must be re-applied after swap (keep it outside the swap target, the 3.1 rule). **IME-safe** (wave 6): the bench filters on every `input` event (`design/home.html:282-288`, `project.html:509`), so during Zhuyin or Pinyin composition the unconverted phonetic symbols hide every Chinese project row. The handler returns when `e.isComposing` and filters on `compositionend`; both sides are compared through `.normalize('NFC')` and `toLowerCase()` (CR-90's rule for a compare-only value). Chrome test: a dispatched composition sequence hides no rows until `compositionend`. The filter hides `details` groups and label rows, not bare divs (next row). |
| Tree rows are real controls | UI | **Wave 6** (wave 1's finding, never applied): the bench tree is script-built divs (`design/home.html:181`: `<div class="row proj" title="Click to tick..."><span class="br">..</span><span class="box">■/□</span>name</div>`, a click handler flipping the `.box` text, dir rows toggling a `hidden` class), with no tabindex, role or keyboard, and R10 makes `.box`, the only place the ticked state is shown, `aria-hidden`. Classic ticks are real `<input type="checkbox" class="proj-check" hx-post=".../toggle?view=sidebar...">` (`sidebar.html:13-21`) in `<details class="proj-group" data-key="grp:...">` groups (`sidebar.html:57`) that the base.html keeper holds across the poll. So each home `.tree .row.proj` is a `<label>` wrapping a visually hidden, focusable `<input type="checkbox" class="proj-check" hx-post="...toggle?view=tree&machine=...">`, the `.box` glyph (aria-hidden) is drawn from `input:checked + .box`, and the label text is the project name; on the project page, where the row is a link, the state is also given as visually hidden text ("ticked" / "not ticked") beside the `.box`; year and show groups are `<details class="proj-group" data-key="grp:<path>"><summary>`. Tests: a `cc/` markup-fact test that every home `.tree .row.proj` holds `input[type=checkbox][hx-post]` and every dir row is a `summary`; a Chrome keyboard test: Tab to a project, Space sends exactly one toggle POST, and the group stays open across two 30 s beats. The R1 census cannot see this (a `<div hx-post>` passes it). |
| Size per project in the tree | BACKEND (small) | Not in the sidebar view. |
| What the bench drops from home | UI (a decision) | Fleet banners, `[ DETAILS ]` content, RESUME / ASK WHY / READ THE ANSWER, lost computers + FORGET, the sync queue, transfers queued/history, plan-change UNDO, the project cards overview. **None may be lost.** Recommended homes: banners stay INSIDE the grid's polled body (wave 5, below); per-computer details and actions go in a row expander (a nested `<details data-key>` under the row, which the round 2 rules allow), and home keeps an empty `#fleet-diagnostics` window outside the grid body for READ THE ANSWER to fill (otherwise the button raises `htmx:targetError` and does nothing); lost computers stays inside the grid's polled body too; the sync queue goes into the account page (it is the person's queue) and stays on home for editors; plan-change UNDO stays in the plan_changes window. The project cards overview is dropped only if the owner says so (D7). **Why banners and LOST COMPUTERS stay in the grid body** (wave 5): both are rendered by `partials/fleet_grid.html` (banners l.37-130, LOST COMPUTERS l.494-514) and refresh with the 15 s `/partials/fleet` poll, and FORGET is `hx-post="/partials/admin/machines/forget-lost" hx-target="closest .fleet-grid-wrap" hx-swap="innerHTML"`, answered with the whole grid (`ui.py:4520-4542`). Moved into a window of their own or into the alert-line slot, FORGET has no `.fleet-grid-wrap` ancestor (htmx raises `htmx:targetError` and sends nothing) and both freeze at first paint. So they are nested `<details data-key>` sections inside the element carrying `fleet-grid-wrap`, styled as sub-windows; the alert-line slot holds only the halt line (2.5). R1's hx-target resolution check catches a move. |

### 5.2 New pages

| Page | Tag | Note |
|---|---|---|
| `/account` | Built now (classic) | Port = restyle only, in phase 3. The spec's "NEW" controls are group F's. |
| `user.html` (admin, one person) | BACKEND | New route (for example `GET /admin/users/{u}`), a view builder composing machines, selections, backlog (`db.fetch_sync_backlog`), `missing_files`, sessions, tokens and audit. Two bench columns have no data yet ("last file" per project; "on the server?" for unticked projects). The Users, Sync plans and Jobs name links wait for it. |

### 5.3 Settings

| Item | Tag | Note |
|---|---|---|
| Packages UPDATE ALL panel | BACKEND | The bench re-implements every server gate in JS (dashboard first, soak, signatures, crash-looped, fleet stop, `min_version` floor, arch withholding). Shipped client-side it would drift from the server's `make_current_refusal`. It needs a server-side plan builder (one view: what each row would do and what holds it back) and ideally one orchestrating endpoint that runs the rows in order and stops at the first refusal. Its own design review, because it is a fleet-wide action on one click. |
| Roll back to… dropdown per served row | UI | POST `packages/current` exists; previously-current builds skip the soak via `ever_current`. **A shortcut, not a replacement** (wave 6): the select lists only versions a plain MAKE CURRENT would accept (signed, not retracted, soaked or `ever_current`, file present). Every held build keeps its own folded row (the `pkg-other` `details`, `data-key` kept) with its canary line, PUSH TO ONE COMPUTER, MAKE CURRENT, the typed override with its conditional unsigned `hx-confirm`, DELETE and the `error_for` refusal. If the select ever lists an unsigned or soak-held version, `static/cc/dashboard_update.js` (or a small `static/cc/` helper) sets or clears `hx-confirm`, `force` and the `confirm` field on change. Phase 4: census entries for push-one, delete and the override per held build with NO allow-list, and a test that an unsigned version cannot be posted without the signature confirm. |
| Delete "goes to the trash for 30 days" | copy only | Verified 2026-09-25: both the partial route (`ui.py`, `POST /partials/admin/packages/delete`) and the API call `api._trash_package_file`, so a delete already goes to `<data>/packages/.trash/` for `PACKAGE_TRASH_DAYS`. The bench is right; it is the live confirm text ("These are the bytes a rollback to that version needs...") that undersells it. Fix the copy. |
| Dashboard rollback as a select | UI + JS | Two select-plus-key pairs (apply an older bundle; roll back the image), never one merged list, because the two run different flows (`runUpdate` with `data-dashupd-older=1` against `ROLLBACK_URL` with `dashupd-restore-db`). The script sets each key's `data-dashupd-*` from its select and matches with `closest()`. A `static/cc/dashboard_update.js` copy, with a test for each path (3.3). |
| AI providers: configured list, manage menu, ADD NEW picker, per-provider wizard | UI (mostly) | Every action has a route. It is a rewrite of `site_settings.js`'s render half. The "how to get a key" steps are new copy that names third-party consoles and key prefixes; keep them in `ai_providers.py`'s catalogue, not hard-coded in JS. |
| who_answers (three consumers) | UI or BACKEND | Derivable in JS from provider status. Recommended: BACKEND (small), with `resolved_cards` and `resolved_server_check` in the snapshot, so the rule has one home. |
| Site tabs | UI | Tabs are display only (1.3): `#settings-form` wraps only the studio-and-tree and features panels; AI, export/history and Android are sibling panels with their own forms and ids, and every field keeps its `site_store.KEYS` name (`indexer_model_tier`, not the bench's `tier`). Phase 4 tests: the cc Site page serialised exactly as `site_settings.js` does sends only names in `site_store.KEYS`; the rendered cc Site page has no nested `<form>`. The bench's "tabs keep their height" rule: a fixed min-height per tab. |
| Sync plans computer select before submit | UI | Emit the person-to-machines map as JSON in the template. |
| Health tabs carrying notices, collector, diagnostics | UI + BACKEND (small) | The collector panel needs a partial route of its own. The diagnostics tab needs no new query (wave 4 correction): `/partials/admin/diagnostics` with no parameters already lists the newest bundle per computer, and `/partials/health-diagnostics` does the same with no parameters (1.5). |
| Recovery two-pane picker | UI | |
| History pager | not needed | |
| Setup step strip and prefill | UI | |

### 5.4 Apps

| Item | Tag |
|---|---|
| b-roll detail beside the grid | UI (app.js) |
| Drawers for ingest / client folders / tray | UI |
| music and youtube restyles | UI |
| Cards landing restyle | UI |

---

## 6. Risks, and what prevents or catches each

| # | Risk | Prevention / detection |
|---|---|---|
| R1 | **A lost control.** The bench drops sign out, sign out everywhere, installer, help, the stamp, RESUME, ASK WHY, FORGET, UNDO, the fleet banners. | Before each page ports, a **control census**: a script (tests/ or tools/, run in CI) renders the page in the classic and the terminal variant against the seeded app, extracts every `form[action]`, `[hx-post]`, `[hx-get]`, `[hx-delete]`, `[hx-put]`, `a[href]`, and fails if a control reachable in classic is unreachable in terminal, unless it is on a written allow-list with the reason ("moved to Health"). A control is compared as **(method, path with ids stripped, sorted QUERY PARAMETER NAMES, sorted form/`hx-vals`/`hx-include` field names)**, and the VALUES of `view` and `mode` are compared too, with an allow-list for intended changes (`view=sidebar` to `view=tree`). The query string matters most (wave 3): the tick's `machine=` is a query parameter, not a hidden input (`project_detail.html:82` `.../toggle?view=project&machine=...`), as are the queue poll's `?as=&machine=`, jobs' `?finished=1`, `?view=` (which decides whether `partial_toggle` answers with the sidebar, `project_detail` or `my_queue`) and the sidebar poll's `?current=`; no template uses `hx-vals` or `hx-include` today. A self-test removes `machine=` from the classic `project_detail` tick and asserts the census fails. **Two halves, two gates** (wave 3): the STATIC half (rendered controls plus load-trigger following over the state matrix, TestClient only, input (1) and (3) below and the URL-constant diff of (2)) is an ordinary pytest test and gates in CI and `publish_latest`'s green-run gate. The CLICK half of (2) needs a signed-in server and a browser with network recording, which pytest here does not have (the d-ui harness loads `file://` pages with `--dump-dom`; `tools/mobile_sweep.js` is the only CDP driver, node 24, not run by `run_all_tests.ps1` or `ci.yml`), so it is `tools/census_click.js` built on `mobile_sweep.js`'s CDP code, run per phase on the base rig against the seeded server, its JSON report attached to the phase report (7.1). **Inputs:** (1) a state-matrix fixture, one render per conditional state: fleet halt active and expired, lane B breaker tripped (RESUME, RESUME ASKED), a lost computer (FORGET), a plan change with UNDO, open notices, diagnostics present, a retracted package, populated recovery and protection (via the `fake_truenas` the tests already use), NAS users (fake NAS). `tools/mobile_sweep_seed.py` says itself it cannot produce several of these, so the census does not use it. (2) JS-issued routes: a per-script list of the URLs it calls (`dashboard_update.js` `ROLLBACK_URL`, `site_settings.js` fetches, `assignments.js` PUT/DELETE, `setup.js`, `account.js`), extracted from URL constants and `data-*` attributes and diffed classic against the `cc/` copy, plus a headless pass that clicks every button on those pages and records fetch/XHR URLs. The click pass stubs `window.confirm = () => true` before load (headless Chrome answers an unhandled confirm with false, so a classic confirmed control records nothing), confirms `htmx:confirm` events, and presses the terminal dialog's OK by a fixed hook (`[data-dialog-ok]` in `#cc-confirm`, 3.2) before recording; a self-test asserts the classic sign-out and package delete record their POSTs. (3) **Load-triggered panels.** Much of what R1 protects is not in first paint: notices dismiss and plan-change UNDO (`fleet.html:22`, `:36`), sessions, report tokens and the fleet halt on Users (`admin_users.html:25/30/35`), every package row (`admin_packages.html:22`), bins, transfers, sync keys. The census follows every `hx-get` whose `hx-trigger` contains `load`, recursively to a bounded depth, sending `HX-Request: true` plus the page's own `hx-headers` (including `X-CC-UI`), and treats each response as part of the page before comparing. A self-test asserts it finds the plan-change UNDO and the notice dismiss on `/` in the classic variant. **Wave 4 widening:** (4) **Click-fetched fragments.** It also follows every `hx-get` whose trigger is click (explicit or default), GET only, bounded depth, with the same headers: `project_roots.html:30,55` BROWSE returns `project_roots_browse.html`'s `hx-post="/partials/project-roots"` forms, `project_setup_panel.html` browse returns the `/partials/project-setup/link` forms, and READ THE ANSWER, MISSING FILES and jobs `?finished=1` hold controls too. Self-test: removing the set-root form from `project_roots_browse.html` fails the census on classic `/` and, once roots move, on `/project/{slug}`. (5) **Roles.** Every census page renders as admin, as editor, and as admin with `?as=<editor>`; comparison is per role and fails in BOTH directions (lost in terminal, or present in terminal for a role that did not have it in classic), each direction with its own allow-list. Self-test: removing `{% if session_is_admin %}` around FORGET in a fixture copy fails the editor run. (6) **Structured allow-list.** A move is `(control key, from page, to page)`, checked: the key must be reachable on the destination page in the same variant and role (following loads and clicks), or on the destination's classic page while it is unported; free text is for true removals only. Self-test: a fake move to a page lacking the control fails. Explicit census pairs map a renamed poll to its classic source so the query-parameter comparison applies: `/partials/sidebar` to `/partials/projects-tree` (a self-test drops `as` and fails), `/partials/transfers` to `/partials/home-transfers`, `/partials/notices` to `/partials/home-problems`/`health-notices`, `/partials/queue` to `/partials/home-queue`/`person-queue`, `/partials/admin/diagnostics` to `/partials/computer-answer`/`health-diagnostics`. (7) **Every group set a phase can produce** (see 7.0's cross-group rule): classic, `{chrome}`, each cumulative prefix of enabled groups (`{chrome,home}`, `{chrome,home,everyday}`...) and `all`, not only classic against `all`. The role runs of (5) reach a terminal set through the SETTING (the `ui_variant` fixture's `site_groups` seam, phase 0, wave 6), never the cookie, which a non-admin session does not honour (wave 5: through the cookie the editor run was classic against classic and passed vacuously). **Wave 5 widening:** (8) **Hidden-value discriminators.** Field NAMES alone collapse distinct controls: ARCHIVE and UNARCHIVE are both `POST /partials/admin/projects/archive` with the same fields, told apart only by `archived=1`/`0` (`admin_assignments.html:171-176` vs `:262-266`), and the two protection acks both post `key`+`date` to `/partials/admin/protection/ack`, told apart by `key=release_key_backup`/`restore_drill` (`protection.html:81-83` vs `:94-96`). The key adds the value of every constant (non-Jinja) hidden input, and controls are compared as a MULTISET, not a set; archived projects and both acks join the state matrix. Self-test: deleting the `restore_drill` form from a fixture copy of `protection.html` fails the census. (9) **Every `hx-target` resolves.** In every rendered cc page (first paint plus every load- and click-fetched fragment), a `closest .x` target must match an ancestor of its element and a `#id` target must exist in the document; the census compares routes and field names, not whether a target resolves, so a FORGET moved out of `.fleet-grid-wrap` (5.1) would pass it. Self-test: moving FORGET out of `.fleet-grid-wrap` in a fixture fails the check. This is the single most important new test. **Wave 6 widening:** (10) **One key per (form, submitter).** A form with two named submit buttons is two controls: `admin_alerts.html:182-200` is ONE form posting to `/partials/admin/alerts/password` with `[ SET PASSWORD ]` and `<button type="submit" name="clear" value="1">[ CLEAR ]</button>` (the only way to remove a stored SMTP password from the page), and a cc form that kept the `password` input and dropped CLEAR produced the same key, since submitters are not `input/select/textarea[name]` fields. For every `button[type=submit]`/`input[type=submit]` with a `name`, the key adds `name=value`; a form with no named submitter keeps its single key. The SMTP password form with `password_source != env` joins the state matrix. Self-test: deleting the `name="clear"` button from a fixture copy of `admin_alerts.html` fails the census on `/admin/alerts` in every role where it renders. (11) **Present means visible, at both widths.** The static half proves a control is in the DOM; the bench hides real controls on phones (`design/css/sync.css:196` `.bar a.act { display: none }` under 760 px removes home's dismiss all, the transfers link to the full Transfers page where the queued and history halves now live, the plan-changes link to History, project's computers help link and Health's packages link; `cc-terminal.css:496-497,508` hide `.pc .ver`, `.pc.head-row` and `.xf .meter/.eta`), and `mobile_sweep.js`'s `shown()` skips hidden elements, so a control that exists only above 760 px passed every gate at 390. `tools/census_click.js` runs at 390 AND 1440 and asserts every control the static half found has a non-zero box (not `display:none`, not `visibility:hidden`, not inside a closed popover no visible opener targets) at each width, or has an allow-listed phone alternative (the dock, `#hud-more`). A `cc/` CSS-fact test: no `display: none` inside a phone or tablet query in `static/cc/*.css` or hud-common applies to a selector matching `a`, `button`, `.key`, `.act`, `form` or `[hx-post]` unless it is on an allow-list with the reason; `.bar a.act` is in 2.1's not-carried list and each hidden bar action gets a phone home. (12) **The SPAs are censused too** (phase 6). The static half renders dashboard pages only, and phase 6 changes SPA controls in `app.js` (clip detail beside the grid, panels to drawers, ingest retry-failed, reconciled ids), with `index.html` and `app.js` shared by both variants and branching on `html.cc`. Phase 6 runs `tools/census_click.js` on `/broll/`, `/music/` and `/ytdl/` with `html.cc` off and on, records the visible buttons, links and inputs by id and label and the fetch/XHR URLs from clicking each (confirm stubbed as in (2)), and diffs the two runs with a structured allow-list as in (6); a per-SPA static list of required live ids (1.4's reconciled ids plus ingest retry-failed) is asserted present in `index.html` or in the terminal branch's builders; `/cards/` joins the static census page list. |
| R2 | **A script no longer finds its element.** | Section 3.3 table as a checklist per phase. `test_static_js_syntax.py` collects with `STATIC.glob("*.js")`, which is not recursive: phase 0 changes it to `rglob` (vendored files excluded) so `static/cc/*.js` is parsed, and adds a second `ON_EVERY_PAGE` set checked against `cc/shell.html`. Add a test per script listing its required hooks and asserting that each ported template that loads the script contains them (`#assign-grid`, `.error-banner`, `#install-slot`, `data-dashupd-*`, `#fleet-diagnostics`...). htmx's own hooks are on the list too (wave 3): every `hx-preserve` element in a classic template exists in its `cc/` twin with the same, poll-stable id (3.3). |
| R3 | **A poll resets a fold, a picker or a find box.** | The 3.1 rule (frame static, body polls; oob for bar meta), `data-poll-hold` on anything opened inside a polled body, the fold store re-applied by `htmx.onLoad`. Headless test: fold a window, wait two poll beats, assert it is still folded. The d-ui Chrome harness today hard-codes `_inline_base_script()` from classic `base.html` and loads only `htmx.min.js` + `htmx_errors.js` on a bare `<html>`, so it cannot run the terminal branch of anything. Phase 0 parametrises `_run_page(variant)`: in `cc` it takes the inline scripts from `cc/shell.html`, loads `static/cc/cc.js` after `htmx_errors.js`, and sets `<html data-ui="cc" data-ui-groups=...>`. Every shared-script test with a terminal branch (block 2 tip and sheet, stale banner, refusal mover, the confirm hold of 3.2) runs in both variants. **Virtual time** (wave 4): `_run_page` passes a fixed `--virtual-time-budget=15000` (d-ui l.135, 692, 1280, 1624), and `--dump-dom` dumps when it runs out, so "wait two 10 s beats", "two grid beats" (30 s) and the confirm scenarios would never report. `_run_page(variant, budget_ms=...)` takes a budget above the scenario's longest wait (for example 45 000). In the cc variant the inline scripts come from a RENDERED `cc/shell.html` (TestClient GET), never its Jinja source; until phase 2 no page extends the shell, so phases 0 and 1 render the test-only `tests/templates/cc_probe.html` child (phase 1 row, wave 5). |
| R4 | **An htmx target id renamed or a swap shape changed.** 30-plus `hx-target` values (`#project-detail`, `#admin-jobs`, `#recovery`, `closest .admin-users-box`, `closest .sidebar`...). | Keep every target id and every `closest .x` class as-is, on the `.body` or a child, never on the `.win` (3.1). Where a partial's shape must change (frame split out), the route renders BOTH shapes from one handler (classic for a classic page, R23), and its test runs in both variants. The existing hx-attribute tests render classic only (through `ui.templates.env`, `TEMPLATES / ...` reads, or a TestClient with no cookie), so they cannot trip on a `cc/` template: they are parametrised over the `ui_variant` fixture (7.1, phase 0) for each ported page, and each phase's verification names the suites that gain the terminal parameter. |
| R5 | **Phone overflow**, especially 768 (section 2.2). | `tools/mobile_sweep.js` at 360 (wave 6: the narrowest common phone and the dock's worst case, 2.2), 390, 768, 1440, adding a 1440 METRICS entry (non-mobile), `/admin/health`, `/help`, `/cards/`, `/account`, `/offline`, `/setup` (first-run), and the SPAs (`/broll/`, `/music/`, `/ytdl/`) to PAGES. Update its tap selector for `.key` and `.tag`. Run against the seeded server in both variants; the terminal run must have zero FAIL. Screenshots go to the session scratchpad and are attached to the phase report. They do not go to `docs/mobile/` until the variant is the default. |
| R6 | **The dock covers content or another fixed bar.** In the SPAs (measured; there is no fixed music player bar, the player is inline, `music/style.css:710`, and no b-roll batch bar): b-roll `#toast-container` (bottom 18 px, z 100) and the full-height `#settings-panel`, `#ingest-panel`, `#cf-panel` (bottom 0, z 50); music `.toast` (bottom 18 px, z 70), `.mi-panel` (full height, z 65) and `.dropzone` (z 60); ytdl `.toast` (z 50). The injected dock sits inside `#app-header`, which is `position: sticky; z-index: 10` in b-roll and ytdl (a stacking context: whatever z-index the dock has, it is confined to 10 there, so b-roll's panels and toasts paint over it) and in music above 900 px only (static below, so on a phone the dock competes directly and can cover the bottom of `.mi-panel`). **The end of b-roll's page** (wave 6): `main#grid-view` holds `#pager` with `#pager-prev`/`#pager-next` (`index.html:86-93`) and has only `padding: 12px 12px 40px` at 700 px (`style.css:1795`), so the 58 px dock plus the safe area covers the pager on every phone; music's `#results` (`style.css:527`) and ytdl's `#main` (`style.css:651`) already end with 120 px and clear it. SPA bottom room is reserved on the SCROLLING CONTENT container, never on `body`: the body-padding mechanism of 2.2 is for classic and cc pages only, and in b-roll and music (`height: 100%` body) body padding is a no-op (the wave 6 critic measured: the last element's bottom did not move for 0, 58 or 300 px of body padding) unless 2.2's scoped height fix lands first. Decision recorded here: SPA overlays (panels, toasts) are allowed to cover the dock, and each SPA sheet lifts its toast by `--cc-dock-h` and gives each full-height panel `bottom: var(--cc-dock-h)` under `body:has(.hud-dock)`, so nothing the SPA owns is covered by the dock. The dashboard toast sits at `bottom: 76px` on phones. On classic pages from phase 1: the stale-data alarm banner (`bottom: 0`, z 60), the chip sheet (z 70), the projects-sheet handle (z 40, the only way into the tree on a phone), the toast host, and the last row of every page. | `--cc-dock-h` lifts all of them and pads `body` (2.2), in `cc/hud.css` (after the hud-common END marker) for classic pages and in `cc/phone.css` for cc pages; never in classic `style.css` (wave 3 correction). In the SPAs, the per-app list above is lifted in each SPA sheet, plus b-roll's end-of-page content (wave 6): `body:has(.hud-dock) #grid-view { padding-bottom: calc(40px + var(--cc-dock-h)) }` inside the dock query, and the same for the clip-detail view that replaces the grid. The sweep names `/broll/` at 390 scrolled to the bottom with the pager shown and asserts `#pager-next` is the hit-test element at its centre; music and ytdl are recorded as already clear (120 px). The sweep's occlusion check (3.4) runs at 390 on every page, with the stale banner forced on and the chip sheet open once, and on each SPA with a toast showing and each panel open. Screenshot a classic page with a sidebar at 390. |
| R7 | **`backdrop-filter` traps fixed descendants** (dock, sheets). | The dock is a sibling of `.hud`, and sheets are popovers (top layer). A test that the partial's dock is not inside `.hud`. |
| R8 | **Stale shell from the PWA.** `/static/*` is stale-while-revalidate: the first navigation after a deploy is still controlled by the old worker, which serves the cached old `style.css` under the new HTML. The worker installs a new cache only when `VERSION` changes. | New URLs (`/static/cc/...`) are never in the old cache, so they go to the network. `cc/shell.html` links through `asset_url()`, a content hash (2.5), so a same-version redeploy still changes the URL. `sw.js` PRECACHE lists the hashed `cc/` sheets (`cc/hud.css` from phase 0, since classic pages link it from phase 1) and `cc.js` from the same map, and the fonts at their plain URLs (2.3). Classic `base.html`'s existing lines and its unversioned PRECACHE entries stay as they are until phase 8 (a `?v=` there would break `test_mobile_css.py`'s contract lines and make the classic `/offline` miss the precache); the HUD's CSS reaches classic pages only through the hashed `cc/hud.css`, never through the unversioned `style.css` (2.2). The `/offline` test (2.5) checks subresources and every `url()` in the linked sheets, chrome off and on. **Every phase bumps the dashboard version** (it would anyway), so `/offline` is re-precached. **The shared classic JS is not covered by the hash** (wave 4): phases 0 and 1 change `htmx_errors.js` (block 2's selector, the Want line) and `pwa.js` (the HUD-slot branch), which classic `base.html` loads unversioned from a `/static` mount (`app.py:1661`, plain `StaticFiles`: validators, no `Cache-Control`, so browsers cache heuristically for hours), and `sw.js`'s revalidation `fetch(req)` (l.136) goes through that same HTTP cache. Phase 0 sends `Cache-Control: no-cache` from the dashboard's `/static` mount (a small `StaticFiles` subclass; a `?h=` URL gets `public, max-age=31536000, immutable` **only when `h` equals the current `asset_url` hash of that file**, and `Cache-Control: no-store` for any other `h` (wave 5: StaticFiles ignores the query, so `cc/hud.css?h=OLD` served during a deploy's restart window, a same-version hotfix or a rollback would stamp the NEW bytes immutable under the OLD hash for a year)) and makes the revalidation `fetch(req, {cache: 'no-cache'})`. Neither touches base.html's pinned lines. **Fonts are the exception to `no-cache`** (wave 6): 2.3 chooses `font-display: optional` (about 100 ms before the fallback is kept for the page's life) and plain, unhashed font URLs, so a 304 round trip on a slow tailnet link would paint Consolas on some loads and JetBrains Mono on others wherever the worker is not answering from its precache (first visit, no worker, before the worker controls the page), on cc pages, classic pages with the HUD and all three SPAs. `/static/fonts/*` gets `Cache-Control: public, max-age=31536000, immutable`, justified by 2.3's rule that a changed font gets a new file name, and that rule is tested: a checked-in manifest of name to sha256 under `static/fonts/` fails CI when a shipped `.woff2`'s bytes change under the same name. Tests: `/static/pwa.js` carries `no-cache`, a `?h=` URL with the current hash carries `immutable` and one with a wrong hash does not, a font GET carries `immutable` (wave 6), the font manifest test, and a `sw.js` source test for the cache mode. |
| R9 | **The offline page** is precached HTML referencing whatever it referenced at precache time. | Its BODY is rendered by the terminal shell only once the variant is the default (phase 8), with bare markup and only precached assets. But `offline.html` extends classic `base.html`, which includes `partials/topbar.html`, and the worker precaches `/offline` at install with the installing browser's cookies, so from phase 1 the precached offline page carries the HUD whenever `chrome` resolves on for that request. So the HUD's sheet (`cc/hud.css?h=`) and the fonts are precached from phase 1, not phase 8, and phase 1 adds chrome-on twins of `test_offline_says_nothing_about_this_fleet` and `test_offline_carries_no_identity_even_when_signed_in` (the HUD adds a user link and counts, which the anonymous offline render must not carry). |
| R10 | **Accessibility regressions.** The bench's bar-click fold is not a button; its tooltip removes `title`; the `.key` busy state hides the label; the primary key is 3.7:1; the crosshair. | A fold `<button aria-expanded>`; `aria-description` on tip move; the busy text and the result are announced: no result banner has a live region today (six `result-banner` templates, for example `partials/admin_alerts.html:20`, `protection.html:24`, `recovery.html:21`, carry no `aria-live` or `role`; wave 3 correction), so every ported `.result-banner` gets `role="status" aria-live="polite"` and every `.error-banner` `role="alert"`, pinned by a `cc/` markup-fact test, and a banner is never inside a folded body (3.1). **Roles alone are not enough** (wave 4): these banners arrive already filled inside a swapped fragment and are then moved by `htmx_errors.js` block 3, and a region inserted with its text (or moved) is not reliably announced. So `cc/shell.html` carries two PERSISTENT, empty regions from first paint (`#cc-announce` `role="status" aria-live="polite"` and `#cc-alert` `role="alert"`, visually hidden), and `cc/cc.js`, on `htmx:afterSettle` (after block 3 has moved the banner), copies the text of each new `.result-banner`/`.error-banner`/`.htmx-refusal` into the matching region (clear, then set on the next frame, so a repeated message is announced again). The banners keep their roles as a second path. Chrome test: after a refused POST, `#cc-alert` holds the refusal text; contrast fix (2.2); 16 px fields and 44 px touch targets, scroll-padding under the sticky HUD, forced colours (2.2); tips on controls reachable by touch (3.2); APG tabs (3.2); no single-key shortcuts (3.2); `cursor: text` on fields; `prefers-reduced-motion` keeps killing grain, blink (`.led.err` blinks forever) and the spinner. Contrast pins for the new tokens in each suite. **Glyphs stay out of accessible names** (wave 5; wave 1's finding was never applied): Chrome and Safari include CSS `content` in the name, so each HUD link would read "greater than sync" (`.slash`), and `.key.quiet::before "\25B8"`, `.none::before "\2713"`, `.cmd::before "> "`, the tree's `.nm::after "/"`, the dock `.g` glyphs and the `.box` squares in tree rows are read too. Decorative markup glyphs carry `aria-hidden="true"` (`.slash`, dock `.g`, tree `.br` and `.box`); decorative generated content uses the CSS alt-text form (`content: "\25B8" / ""`, with the plain declaration first as a fallback); text meters carry `role="img"` with a label, or `aria-hidden` plus a visually-hidden percent or state word. Tests: a `cc/` markup-fact test that every `.slash`, `.g`, `.br` and `.box` carries `aria-hidden`, and a CSS-fact test that every non-empty `content:` in `static/cc/*.css` and hud-common has an alt part. **Decorative against informational** (wave 6): the rule is "decorative generated content has an empty alt; informational generated content has an explicit alt". `.tbl.stack-sm td[data-label]::before` (2.1) is the only column header a reader gets once `display: block` strips table semantics, so it is `content: attr(data-label); content: attr(data-label) / attr(data-label)`, on a short allow-list the test checks; `@keyframes` bodies (the `.spin` steps, `cc-terminal.css:179`) are excluded by the parser. Wave 5 also added to this row: the focus ring (2.1), body LEDs under forced colours (2.2), the floating tip (3.2), touch targets for ticks and tags (2.2). |
| R11 | **Tests that pin the old markup** (328 bracket literals, 196 positive and 35 negative asserts in 55 files; the theme-common and drawer CSS pins in four suites; `test_mobile_css.py`'s 45 asserts on `style.css`; the 17-count `hx-trigger` test in `test_mobile_admin.py`). | **Classic pins on TEMPLATE markup stay unchanged until phase 8**, because classic stays the default for every customer (D14) and is what a rollback serves; rewriting them would delete coverage of the variant most people get. **Pins on Python-produced copy are the exception**: classic templates render that copy too, so they are REWRITTEN in the phase that changes the copy (phase 5 for panel names and anchors, phase 7 for control names), not kept. Known ones (not a complete list: phase 7's verification adds a grep step, wave 6): `test_notices_sweep_wave2.py:261-263` (`[ DOWNLOAD CRASH REPORTS ]` in `fix`, the `notice_href` tuple); d-diag `_labels()` (l.572, matches only `\[ [A-Z]... \]` and asserts non-empty, so D8's `press "Keep halted"` fails it) is rewritten to pull D8 quoted labels and check each against the panel in both variants (classic `[ LABEL ]` uppercased, terminal via `has_key`); d-diag l.640-662 (`'[ COLLECTOR ]' in fix`, and at least 4 "under the computers table on SYNC STATUS", a page-region phrase R13 bans) becomes a check that the copy names the Collector panel and that `/go/collector` resolves; d-diag l.1311-1317 (`'[ ASK THIS COMPUTER WHY ], then'`); `test_api.py:362/375` (`[ COLLECTOR ]`). The R13 switch to `/go/<panel>` rewrites four more in phase 5 (wave 3), each to assert the `/go/<panel>` href AND that it resolves in both variants: `test_bug_hunt_2026_09_24_w2_d-db.py:464` (`notice_href(kind)[0] == "/#fleet-collector"`, six kinds), `test_bug_hunt_2026_09_24_w2_d-diag.py:596` (`_stop_the_fleet_step().href == "/admin/users#admin-fleet-halt"`), `test_health_page.py:97` (`/#server-notices` on classic Health, since `admin_health.html` moves to `/go/notices`). `test_sweep_2026_09_04_copy.py:293` (`/#server-notices` in the CLASSIC `partials/topbar.html`) is NOT rewritten: the classic topbar keeps `/#server-notices`, because classic home still holds the notices; only `cc/partials/topbar.html` links `/go/notices`, and that gets a terminal twin. Under the overlay no classic pin breaks, so a pin can only catch a terminal regression if it is ALSO run against the terminal variant. Each phase therefore ADDS terminal assertions beside the classic ones, never "skip", never replace: the `ui_variant` fixture (phase 0) parametrises TestClient and `env` renders; hard-coded `templates/<x>.html` reads of hook and behaviour pins go through a resolver (the `cc/` file if it exists, else classic) with the pin asserted on both; the resolver is for SAME-NAMED templates only and never for CSS files (wave 3: `test_mobile_css.py`'s `--bp-phone: 600px` and single-600-query pins do not apply to cc sheets, which have their own file). **The shell is renamed, so the resolver cannot reach it** (`base.html` to `cc/shell.html`, `fleet_halt_banner` to `cc/partials/halt_line.html`, `chip_sheet` to `cc/partials/hint_sheet.html`), and `cc/shell.html` emits every URL through `asset_url()`, so literal-string pins cannot be re-pointed. Phase 1 adds an explicit shell twin list, asserted on the RENDERED HTML of a cc page under the `ui_variant` fixture: the manifest link, `theme-color` (the new value), `apple-touch-icon`, the viewport meta with `viewport-fit=cover`, `pwa.js` ordered before `htmx.min.js` (hash-tolerant), the halt line's `load, every 60s` trigger plus `VISIBILITY_FILTER`, `VISIBILITY_FILTER` on the cc stamp and tree polls, and the deep-link scroller with the 3.2 tab activation (the classic sources: `test_mobile_css.py` CONTRACT_LINES l.295-311, l.316, l.323, l.340-364; `test_sweep_2026_09_04_copy.py:287-293`). **`OWNED_TEMPLATES` stays classic** (wave 3): it feeds `test_every_poll_m3_owns_stops_while_the_page_is_hidden` (`seen == 17`, l.190), `test_every_editors_table_m3_owns_stacks` and the `scroll-x`-before-every-table test, which the first `cc/admin_*.html` would break. A separate `CC_OWNED_TEMPLATES` (`templates/cc/admin_*.html`, `cc/partials/admin_*.html` and the cc twins of `recovery`, `invariant_checks`, `protection`, `collector_health`) feeds only the box-drawing source test, the visibility-filter check with its own count constant, the em-dash test and the new `tbl`/`stack-sm`/`data-label` twins; R11's table-stacking and poll-count tests take `OWNED_TEMPLATES` only. d-ui's `TEMPLATES.glob("*.html")` includes `templates/cc/`. The pins a `cc/` template could drop silently today (the `VISIBILITY_FILTER` on a poll, `.error-banner`, `hx-disabled-elt`, `data-poll-hold`) are the first to gain the parameter. The table-stacking pins (`test_mobile_admin.py:236-287`, `editors stack`, `<table class="editors`, `scroll-x` before each table) are NOT parametrised: over terminal markup they pass on nothing or push a builder into the `.stack` grid collision (2.1). They get terminal twins in terminal vocabulary instead (every `<table class="tbl` in `templates/cc/` carries `stack-sm` and a `data-label` on every `td`), and the poll count is kept per variant (17 classic, its own number for `cc/`). **There is no second suite run.** `Settings` is a frozen dataclass that reads the environment only in `from_env()`, which 2 of 149 test files call, and `env` renders ignore Settings, so a `DASH_UI_VARIANT=cc` rerun would be classic again for most tests and red on kept bracket literals for the rest, and CI (`ci.yml`, one dashboard pytest run) would never run it. Terminal coverage comes only from explicit `ui_variant`-parametrised tests, and a phase 0 coverage check asserts every file in `ui_variant.TEMPLATE_GROUPS` is rendered by at least one terminal-parametrised test, so a new `cc/` template with no terminal test fails the normal CI run. It is NOT an ordinary test (wave 3: conftest collects no test items, and a test checking "rendered so far" depends on file order): it is a `pytest_sessionfinish` hook in `dashboard/tests/conftest.py` reading a registry that a recording wrapper on every per-set environment's loader fills, and it sets `session.exitstatus` non-zero only when the whole `tests/` directory was collected (every `test_*.py` under `tests/` among the collected modules); on a subset run (the owner's "builders run only the files they touch" rule) it prints a skip notice. A self-test asserts the recorder sees a cc render. **What counts as coverage** (wave 4): a loader wrapper records LOADS, and the phase 0 mechanism tests (the group-filter, alternating-render and `TEMPLATE_GROUPS` tests, naturally a loop over the table) plus every include and `extends` would fill it whatever the page tests do. So the recorder records only renders inside a test using the `ui_variant` fixture (a contextvar set by the fixture), and tests marked `@pytest.mark.ui_mechanism` (the overlay and filter tests carry it) record nothing. Self-test: a cc template loaded only by a `ui_mechanism` test is reported uncovered. **What it records is the FILE, not the name** (wave 5): names passed to `_render` are logical (`fleet.html`), the same for both variants, so a variant test whose render quietly resolved to CLASSIC still counted; and `partials/settings_nav.html` (only `{% include %}`d), `cc/shell.html` (only extended), `hint_sheet` and `home_collector` (only included) are never passed to `_render` at all and would be uncovered for good. So the recorder wraps each per-set environment's `get_template`/`_load_template`, which Jinja also calls for every `{% include %}` and `{% extends %}` at render time, and records `template.filename` only when it lies under `templates/cc/` and the contextvar is set. Self-tests: a `ui_variant` test whose render resolves to classic records nothing; an include-only cc partial rendered through its page counts as covered. **New-named partials** (wave 4): the resolver reaches same-named templates only, so `test_mobile_fleet.py`'s OWNED list (`partials/transfers.html`, `notices.html`, `queue_section.html`, `my_queue.html`...) and its `test_every_poll_waits_for_a_visible_page` would re-check classic files under the terminal parameter. Two additions: a glob-based `cc/` source test (every `hx-trigger` containing `every ` in any file under `templates/cc/**` carries `VISIBILITY_FILTER`, and no file there holds `─`), and a `NEW_NAME_TWINS` map (`partials/transfers.html` to `partials/home_transfers.html`; `notices` to `home_problems`/`health_notices`; `queue_section`/`my_queue` to `home_queue`/`person_queue`; `collector_health` to `home_collector`/`health_collector`; `admin_diagnostics` to `computer_answer`/`health_diagnostics`; `sidebar` to `projects_tree`; `fix_root` to `home_fix_root`/`person_fix_root`, wave 5) through which hard-coded name lists such as OWNED and WITH_TABLES assert their pins on every twin. Terminal label asserts go through `has_key(html, "Resume")`, which matches a `.key` whose `.t` text is the label (it is for the terminal variant; classic asserts keep their bracket literals). **Negative asserts get a terminal twin, never deleted**: `"[ UP ]" not in html` stays for classic and `'>Up<' not in html` is added for terminal. CSS-fact tests for classic `style.css` stay until the classic sheets are deleted; the terminal sheets get their own CSS-fact test file (tokens, gutter, `.win.collapsed`, tag shape, the phone query, the 12 px floor, contrast, no box-drawing glyphs in `cc/` templates). |
| R12 | **Copy rules.** No em dash (the dashboard scan covers templates, static JS and Python strings, but NOT CSS; broll and music scan CSS raw, comments included); no typewriter ` -- ` in rendered copy (`test_sweep_2026_09_04_copy.py`); the retired-phrase bans. | The `cc/` CSS carries no em dash even in comments (the SPA copies of hud-common would fail). **Nothing tested that** (wave 5: `test_no_em_dash.py` scans templates, static JS and Python, l.57-65, and no .css), so phase 0 adds `STATIC.rglob('cc/*.css')` to it, scanned raw with comments included, and names it in the cc CSS-fact list. Add a **bracket scan** over `templates/cc/`, `static/cc/` and Python UI strings (classic templates and classic JS are excluded by path, since they keep brackets until phase 8). **What it scans is defined by extraction, not raw text** (wave 3; a raw lowercase-bracket pattern would flag `VISIBILITY_FILTER = "[document.visibilityState === 'visible']"`, which every cc poll must carry, cc.js selector strings such as `'[data-tip], [data-chip-detail]'` and `'#cc-confirm[open]'`, Jinja subscripts and JSON arrays, so it could never reach zero). Templates: text nodes plus the visible attributes (`title`, `placeholder`, `aria-label`, `alt`, `hx-confirm`), taken with the `_visible_strings` extractor already in `test_sweep_2026_09_04_copy.py`; interpolated brackets (`\[ \{\{`, `\[ \{%`; 42 such in templates today, like `[ {{ label }} ]`) are checked on the raw source BEFORE Jinja expressions are blanked. JS: string literals written into `textContent` or `innerHTML`, never selector arguments. CSS: `content:` values only (generated brackets; the classic `.menu-btn::before { content: "[" }` is the model). The patterns are `\[ [A-Z]` and `\[ [a-z]`, both with the space the product's bracket style always has and selectors and filters never have. **Two more rules, because those patterns miss the generated and concatenated brackets** (wave 5): in CSS `content:` values ANY `[` or `]` character is flagged (a content value is never a selector; the model rule `.menu-btn::before { content: "[" }` has no space and no letter after it); in JS literals written into `textContent`/`innerHTML`, a literal matching `\[\s*$` or `^\s*\]` is flagged too (`setup.js:277` `"[ " + item.title.toUpperCase() + " ]"`, `setup.js:286`, `assignments.js:248`, which phase 4 forks into `static/cc/` as copies). Self-tests: a sheet with `content: "["` and a line `el.textContent = "[ " + label + " ]"` both fail; the visibility filter and a `querySelector('[data-tip]')` literal do not match. The Python allow-list starts as today's full list, **may not grow**, and its length constant is lowered in the commit that rewrites copy (phases 5 and 7), reaching zero in phase 7 (except the documented plain-text email state words, D8) (wave 6: "must shrink each phase" could not be met by phases 1-4 and 6, which change no Python copy, and would push a builder to rewrite copy before the variant-neutral D8 sweep). **The Python half walks every module under `src/ccsync_dashboard`** (wave 6) with the AST and docstring subtraction of `test_no_em_dash.py` (`_py_files`, `_docstring_nodes`), never `VOCABULARY_FILES` (`test_sweep_2026_09_04_copy.py:350-357`), which lacks `cards_pool.py` (4, e.g. l.389 "Press [ OPEN ] to try again"), `recovery.py` (l.936 "[ STOP ALL SYNCING ]") and `release_feed.py` (l.1177 "[ APPLY ]"), all rewritten per 2.6; a self-test asserts those three are scanned. Phase 7 adds `recovery.py`, `cards_pool.py`, `release_feed.py` and `account_ui.py` to `VOCABULARY_FILES`, since their D8 rewrites are new copy. **What makes it shrink** (wave 4): a stale-entry test fails on any `(file, fragment)` entry that no longer matches an extracted string, so an entry whose copy was rewritten must be deleted in the same commit and cannot keep allowing a reintroduction; a length constant, lowered only by a commit that rewrites copy (phases 5 and 7) and never raised, pins the count. **The vocabulary scan is already live on `cc/`** (wave 4): `test_sweep_2026_09_04_copy.py`'s `_rendered_files()` is `TEMPLATES.rglob("*.html") + STATIC.rglob("*.js")` (l.74), so `test_no_retired_word_in_rendered_copy` (l.588, `RETIRED_WORDS` l.359: lane(s), machine(s), rig(s), halt(ed), park(ed), breaker, selection(s), assignment(s)), `test_no_retired_phrase_in_rendered_copy` and `test_no_typewriter_em_dash_in_rendered_copy` scan `templates/cc/**` and `static/cc/**` from the first file. The bench fails it (`design/home.html:66` "sync lanes"; `design/account.html:61-62` and its JS strings "wired rig"; `design/youtube.html:53,79`), so phase 0's bench-to-product copy rules add: "sync lanes" becomes "sync" (or "upload / proxy download / folder sync"), "wired rig" becomes "wired computer", and every bench string runs through `RETIRED_WORDS` before it lands. `TEMPLATE_VOCABULARY_ALLOWED` entries are keyed by `path.name`, so a new-named partial loses its classic ancestor's entries: they are carried over by the new name in the same commit that adds the partial. Phases 2, 3 and 6 list the scan in their verification. "Zero over the whole tree" is a phase 8 check, after classic is deleted. **The retired-phrase bans get terminal twins in phase 0**, not phase 7: `RETIRED_IN_TEMPLATES` in `test_sweep_2026_09_04_copy.py` matches bracketed, uppercase forms case-sensitively (`[ ASK THIS MACHINE WHY ]`, `<th>MACHINE</th>`), which a terminal key `<span class="t">Ask this machine why</span>` or a lowercase `<th>machine</th>` never matches. An explicit terminal twin table, written entry by entry (wave 3; a mechanical unbracketed, case-insensitive twin of `("[ UP ]", ...)` is the substring `up`, which matches `update`, `upload`, `setup` and the bench home's own lane label), applies to `templates/cc/**` and `static/cc/**` from the first `cc/` template on: LABEL entries become whole-label matches on key text (`has_key(html, "Up")` is false, or `>\s*Up\s*<` inside a `.t` span, the form R11's `'>Up<'` twin uses); only PHRASE entries (`pick a machine`, `machine(s)`, `this machine's`) become case-insensitive substrings. A self-test asserts the twin table does not match `update` or `upload`. The classic entries stay as they are. **The vocabulary allow-lists need twins too**: `VOCABULARY_ALLOWED` allows `("alerts.py"|"notices.py", "[ MOVE ON THE SERVER AND ON EVERY MACHINE ]")` and `TEMPLATE_VOCABULARY_ALLOWED` allows `("", "MOVE ON THE SERVER AND ON EVERY MACHINE")`, case-sensitive substrings over a scan in which `machine` is a `RETIRED_WORDS` entry. A sentence-case `cc/partials/project_detail.html` key ("Move on the server and on every machine", phase 2) and the D8 rewrite of `notices.py:474/832` and `alerts.py:2362/2430` (phase 7) both stop matching and go red. Decision recorded here (settle before phase 2): the label becomes the vocabulary word, **"Move on the server and on every computer"**, in the cc template in phase 2 (the classic key keeps its bracketed text until phase 8) and in the D8 copy and `docs/FILE_MOVES.md` in phase 7; no allow-list entry is needed for the new form, and the old entries are deleted with the classic template. Every other `VOCABULARY_ALLOWED`/`TEMPLATE_VOCABULARY_ALLOWED` entry keyed on a bracketed or uppercase label is checked the same way before its page's phase, and the edits are listed in that phase's verification. |
| R13 | **Panel anchors in shared Python.** `db.NOTICE_KINDS` hard-codes `/#fleet-collector` for six kinds, `ui.py` uses `detail_page="/#server-notices"`, `admin_health.html` links `/#server-notices`, and notices' `fix` text names panels ("read the [ COLLECTOR ] panel", "open FLEET and press [ FORGET ]"). Both variants read these. Editing them in phase 5 sends classic viewers (the default) to Health anchors classic Health lacks; not editing them breaks terminal. (Labels are NOT stored: `db.notice_href` computes `href_label` per render; 2.6.) | Small redirect routes, `/go/<panel>`, send each viewer to that panel's location in the variant they would get (R23's rule). `NOTICE_KINDS`, `recovery.py`, `ui.py`, `admin_health.html`, `cc/partials/topbar.html`'s problems link and alert copy use `/go/...`, so no shared string names a page region. The CLASSIC `partials/topbar.html` keeps `/#server-notices` (classic home still holds the notices; its pin `test_sweep_2026_09_04_copy.py:293` stays). The four pins this changes are listed in R11. Emailed `fix` text names the panel, not the page ("the Collector panel"). Open notices pick up the new `fix` on their next upsert. **The panel table** covers every anchor href in `NOTICE_KINDS`, `recovery.py` and the templates, not only the three that move: `collector`, `notices`, `diagnostics` (moved to Health), `ai-providers` (`db.py:3635`, `admin_settings.html`; a Site tab), `restore` (`recovery.py:955`; a Recovery pane), `dashboard-update` (`recovery.py:984`), `admin-fleet-halt` (`recovery.py:939`, the halt banner, `account.html`). Each resolves to the page plus the hash, and the terminal page's tab activation (3.2) opens the tab or pane holding it. **The hash per variant** (wave 4): `collector` is `/#fleet-collector` on both homes (the terminal home keeps the id on `home_collector`'s body, 3.3) and `/admin/health#fleet-collector` on terminal Health; `notices` is `/#server-notices` on both homes and `/admin/health#server-notices` on terminal Health; `diagnostics` is `/#fleet-diagnostics` on both homes and `/admin/health#fleet-diagnostics` on terminal Health; the rest keep their live hash in both variants. Which one a viewer gets follows 7.0's cross-group rule (source group and destination group), not the destination alone. A test walks the table over every group set a phase can produce (R1 input 7), not only classic and `all`. |
| R14 | **The account-page builders are editing the same files right now** (`topbar.html`, `fleet_grid.html`, `admin_users.html`, `admin_audit.html`, `plan_changes.html`, `style.css`, `mobile.css`, `ui.py`). | Phase 0 starts only after the account work is committed. Every later phase starts from a clean tree. Any bug fix that touches a page mid-port is made in BOTH variants (the port's owner is responsible for the second copy) until that page's classic template is deleted. |
| R15 | **A partial shared by a ported and an unported page** gets the terminal markup on the classic page (section 7.0 overlay). | The `chrome` group's overlays are exactly three partials whose every class is HUD-owned and painted by hud-common in `cc/hud.css` (3.4): `topbar`, `settings_nav`, `stamp`. The fleet-halt banner and the chip sheet are NOT overlaid (wave 2): their cc forms are shell furniture under new names (`cc/partials/halt_line.html` on its own route `/partials/halt-line`, `cc/partials/hint_sheet.html`, 2.5), so a classic page keeps the classic banner, sheet and CSS, and a cc page never loads classic ones. Any other shared partial ports together with every page that includes it, or gets a new name. **The phase table was checked against the include map** (wave 2): `partials/transfers.html` is included by `fleet.html` (group `home`) AND `transfers.html` (group `everyday`), so phase 2 ports it as `cc/partials/home_transfers.html` (new name; the classic partial and `/partials/transfers` stay as they are for the Transfers page until phase 3); `partials/minted_secret.html` is included by `admin_users.html` and `admin_report_tokens.html` (group `settings-fleet`), so it ports in phase 4, not phase 3. A test lists `{% include %}`s per page (recursively) and fails if a `cc/partials/x.html` would be served to a page of another group, unless x is one of the three chrome overlays. **Includes are not the only way in** (wave 3): the test is a FETCH map too. For each page, every `hx-get`/`hx-post` URL (plus load-triggered descendants, as R1 follows them) is mapped to the template its route renders, and a `cc/` partial reached by pages of two groups fails unless it is a chrome overlay. The fetch map found four, and the choice for each is recorded here and in the phase rows: `/partials/notices` (`notices.html` + `notice_checks.html`; home in phase 2, a Health tab in phase 5) and `collector_health.html` (included by `fleet_grid`, a Health route in 5.3) get home-only new names in phase 2, `cc/partials/home_problems.html` on `/partials/home-problems` and `cc/partials/home_collector.html` included by the new grid body. `/partials/admin/diagnostics` (READ THE ANSWER on home, a Health tab) gets `cc/partials/computer_answer.html` on `/partials/computer-answer?editor=&machine=` for home in phase 2. `/partials/queue` (`queue_section`/`my_queue`; home, the account page of group `everyday` per 5.1, and `partial_toggle`'s fallthrough) gets `cc/partials/home_queue.html` on `/partials/home-queue` (with a `view=home-queue` branch in `partial_toggle`) in phase 2. The other side gets its own names too, and **the four classic names are never overlaid** (overlaying one under `settings-health` would hand terminal notices to a classic home whose page set holds `settings-health`): Health in phase 5 uses `cc/partials/health_notices.html`, `health_collector.html` and `health_diagnostics.html` on `/partials/health-notices`, `/partials/health-collector` and `/partials/health-diagnostics`; the account page in phase 3 uses `cc/partials/person_queue.html` on `/partials/person-queue`. Every one follows 7.0's naming rule for new-named partials. **The fetch map covers write responses too** (wave 4): for every `hx-post`/`hx-delete`/`hx-put` on a page, the template its route ANSWERS with is mapped the same way, since a POST route that always renders a classic name swaps classic markup into a terminal window. Known case: `POST /partials/notices/{id}/dismiss` always renders `partials/notices.html` (`ui.py:1845-1858`); it gains `?view=home-problems` or `?view=health-notices` (5.1). The tick (`view=tree`, `view=home-queue`) already follows this pattern. The phase 2 and 5 tests assert, per cc panel, that each write it can send answers with that panel's own markup. **Swap-none writes** (wave 5): the account page's `hx-swap="none"` posts are answered by partials of other groups (`account_computer.html:37` to `/partials/admin/machines/update`, which renders `partials/admin_packages.html`, `ui.py:4370-4406`, settings-fleet; `:108` to `/partials/admin/machines/ask-why`, which renders `partials/fleet_grid.html`, `ui.py:4438-4461`, home), and htmx 1.9.12 still applies out-of-band swaps on `swap none` (the oob pass runs before the `none` return), so the grid body's 3.1 oob bar meta and readouts would hit the account page (`htmx:oobErrorNoTarget`, or an id the page reuses) and the group rule would trip in phases 3 and 4 with no recorded decision. Decision: the account buttons send `?view=none`, and those routes (`machines/update`, `ask-why`, and `resume-lane-b` if the account page gains it) answer an EMPTY 200 for it, no template and no oob. A swap-none write is exempt from the group rule only when its answer is empty, and the test asserts that: an account-page ask-why or update POST returns no `hx-swap-oob` element in either variant. |
| R16 | **The SPA injects a topbar its stylesheet cannot paint** (hud-common not yet in that SPA's sheet, or a browser pairing the always-fresh `/partials/topbar` with a cached old SPA sheet; phase 6 has the same shape with a new `app.js` against an old `style.css`). | Same image, so the server side is consistent, and the hud-common byte-identity test fails the gate if one copy is missing. The browser side is not free: b-roll's index links unversioned `static/style.css`, served by plain `StaticFiles` with `Last-Modified` and no `Cache-Control`, so browsers cache it heuristically. Phase 1 sends `Cache-Control: no-cache` from b-roll's `/static` mount AND from `index()` (`broll/web/app/main.py:105-107`, a bare `FileResponse` today, so index.html itself is heuristically cached too, and phase 6 changes that file), with no markup change (wave 3). Hashed links were the rejected alternative: `broll/web/tests/test_mounted_prefix.py:100` pins `'src="static/ingest.js"' in body` on the served `/broll/`. A b-roll test pins the header on `/broll/` and on `/broll/static/style.css`. music and ytdl serve `style.css`/`app.js` as plain `Response(read_text)` with no validators, which browsers do not cache heuristically; a test per suite pins that (no `Last-Modified`/`ETag` on those routes, or a hashed link if that changes). |
| R17 | **Load.** Five windows each polling on home (2 s, 10 s, 15 s, 30 s, 60 s), plus the new oob meta and readouts. | No new polls: readouts and meta ride the existing 15 s grid response. Folded windows still poll (the cost is the same as today). A later optimisation could skip the beat when folded (`[!this.closest('.win.collapsed')]` in the trigger filter); do not add it in the port. |
| R18 | **Grain and the blink run forever on a wall display.** | Pause when hidden (section 2.4). |
| R19 | **Orbitron on a CJK string** paints tofu or mixed faces. | The display face only on `.big` numbers and fixed page titles. Lint (wave 3, widened from `h1` only): every selector in `static/cc/*.css` and hud-common that sets `font-family: var(--disp)` (or Orbitron) is listed, and a render test asserts no element matching one of them interpolates a user or site string. The HUD brand is the known case: `.hud-name` holds `brand_org`, site data, so it is in the mono face (2.3). |
| R20 | **Customer names or site specifics in code.** The bench says "CC SYNC / the creators club", `TPE`, `owen@admin`. | Brand from `brand_org` (site data), product name as the fallback; no clock (D4); user from the session. The bench sheets' header comment names the customer's website (`cc-terminal.css:1-12`); it is not carried, and the `cc/` CSS-fact file fails on the customer's domain in any `static/cc/*`, `templates/cc/**` or hud-common copy (2.1, wave 6). |
| R21 | **The fold state goes stale when a window is renamed or removed.** | Keys are `data-win` values; old keys are ignored. The store is capped at 100 entries per path. |
| R22 | **The client share page** picks up the terminal look via a shared sheet. It DOES share one: `share.html` loads `../assets/style.css` (b-roll's main sheet, listed in `SHARE_ASSETS`) before `share.css`, which only overrides on top (`test_bug_hunt_2026_09_24_w2_broll.py` pins `.share-header .topbar > .brand` against `style.css`'s `.topbar > *`). | Rule for phases 1, 6 and 8: every new rule in b-roll's `style.css` is scoped: `.hud*` selectors, under `html.cc` (7.0), or beginning `body:has(.hud-dock)`, `html:has(.hud-dock)` (where `--cc-dock-h` is declared, wave 4), `html:has(.hud)` (the lift and scroll-padding blocks of 2.2, which the share page cannot match), `html:has(#dash-topbar > .hud) body` (the body-height fix that lets the HUD stick in b-roll and music, 2.2, wave 6), `html.cc-chrome` (the first-paint header reservation, 7.0) or `#dash-topbar` (the `.rule` hide of phase 1; the share page has no `#dash-topbar`); `@font-face` rules are also allowed (they paint nothing on their own; the HUD's font-family rule is scoped to `.hud*`). No change to unscoped `:root`, `html`, `body`, `.topbar`, `.brand` or theme-common in that sheet; no body or font-family rule in hud-common; the share page never needs `static/fonts/` (not in `SHARE_ASSETS`, and 404 behind the Funnel prefix). A b-roll test snapshots the unscoped rule set of `style.css` (every rule not under the scopes just listed) and fails on any change without an explicit update, and records the `@font-face` and `:has()` rules explicitly in a second list (wave 3 rewording: phase 1's own lift and `@font-face` rules were neither `.hud*` nor `html.cc`); the share page at 390 and 1440 joins the sweep in phases 1, 6 and 8. Phase 8 does not "unscope" b-roll's sheet unless the share page first gets its own copy of the classic rules it uses (added to `SHARE_ASSETS`). **Allowed exception: D6.** D6 changes theme-common's scrollbar thumb, which is byte-identical in b-roll's sheet and so reaches the client share page. That is an intended, owner-approved change to the share page (a scrollbar thumb), made as an explicit update of the unscoped-rule snapshot in the same commit, with the share page screenshot at 390/1440 attached. If the owner does not want clients to see it, `share.html` first gets its own copy of the classic theme-common (in `SHARE_ASSETS`) before D6 lands. |
| R23 | **An open page gets partials in the other variant** when the setting or the cookie changes. Nothing reloads a dashboard page (no version check in `pwa.js` or `htmx_errors.js`; `sw.js` skips `/partials/`), so a wall display on classic `/` keeps polling `/partials/fleet` and `/partials/transfers`, and would swap terminal bodies into classic frames (or, on rollback, classic frames into `.win .body`, doubling them). Form POST responses too. | **A partial's variant follows the page that asked for it**, not the current setting. A one-word `cc|classic` header cannot describe the mixed pages phases 1-6 produce (a classic body under the HUD: with `classic` the HUD's 30 s stamp poll would swap classic stamp markup into the HUD), so **the header carries the GROUP SET the page was rendered with**: `X-CC-UI: chrome,home`, empty for fully classic, `all` for the `cc` cookie. Both `base.html` and `cc/shell.html` emit it into `hx-headers` from the same context value `_render` used for the full page, and put the same set on `<html data-ui-groups>`. On an htmx request `_render` resolves against that set (it selects the environment, 7.0), so a classic-body page with `chrome` gets cc chrome partials (the stamp) and classic body partials, whatever the setting now says. The setting and cookie decide only full pages and non-htmx fetches (the SPAs' topbar fetch, which sends no `HX-Request`; any other JS fetch of a `/partials/` URL must send the header, 3.3). **An htmx request with no `X-CC-UI` at all is classic** (wave 6; 7.0's order, step 2): pages loaded before phase 0 and the frozen classic `dashboard_update.js` send `HX-Request` alone, and following the setting would swap `cc/partials/stamp.html` into a classic `.stamp` span once `chrome` is on and the terminal grid body into a classic `.fleet-grid-wrap` once `home` is on; they get the classic fragment plus `HX-Refresh` (GET) or 409 plus Want (write) when a full load would now differ for `chrome` or their page's group. Every route whose partial is split renders both shapes from one handler, and its test runs in both variants. **Reload hint:** `X-CC-UI-Want` is computed from `HX-Current-URL` (htmx 1.9.12 sends it on every request): the route of the asking page maps to its template's group (a table in `ui_variant`, beside `TEMPLATE_GROUPS`), and the server compares, for `chrome` plus that group only, the header's set with the set a full load would now give. It sends `X-CC-UI-Want` only on a difference, and `htmx_errors.js` shows a quiet "the dashboard look changed, reload" line when the header is present (never an automatic reload mid-edit). So a poll that belongs to no page group (the stamp, the halt line) never raises the line for a group the page does not use. Tests: classic body with `chrome` on (no line); the page's group flipped on (line shown); an unrelated group flipped (no line); the stamp poll (no line unless `chrome` itself flipped). **The set is concrete, and a generation token rides with it** (wave 3). A group set alone does not say which `cc/` templates existed when the page rendered: a Transfers page loaded under the phase 2 image with the `cc` cookie is classic-bodied with header `all`, and after the phase 3 deploy its next 2 s poll would get the new terminal transfers partial with no Want (both sets are `all`); an image rollback past the phase that introduced an enabled group resolves `settings-fleet` to classic partials inside terminal frames; phase 8 would do the same to any still-classic page. So (a) `all` is expanded at render time to the concrete groups that had `cc/` templates in that build, and (b) both shells emit a generation token beside the set (`X-CC-UI-Gen`), and `_render` sends `X-CC-UI-Want` whenever the token differs from its own, not only when the set differs. **The token is a content digest** (wave 4: a list of names plus `VERSION` misses the same-version redeploys 2.5 exists for, where a hotfix changes a `cc/` template's markup and `cc/terminal.css` together and an open page keeps the old `?h=` sheet): a digest, computed at startup beside `asset_url`, of the `asset_url` hash map plus the sha256 of every `cc/` template's bytes. Test: same VERSION, one `cc/` template's bytes changed, and the poll carries Want. **A fully classic page is left alone before phase 8** (wave 4): when the page's set and the set a full load would now give are both empty, the token is not compared, so a customer on classic sees no reload line after a deploy and phase 0 really renders nothing differently (test: an empty-set page polling with an old token across a VERSION change gets no Want). The token check is permanent for terminal pages; phase 8 turns it into the generic "the dashboard was updated, reload" line for every page, a wording chosen then. **A missing `X-CC-UI-Gen`** (a page from before phase 0, or a hand-written fetch) means "send Want, serve by the header's set" when the header's set is non-empty, and nothing when it is empty; tested separately. **The header set is signed** (wave 4): the header is a client value, so an editor could send `X-CC-UI: all` and get unreviewed cc partials. Both shells emit `X-CC-UI-Sig`, an HMAC with the session secret over (set, generation, session id), and `_render` honours a header set only when its signature verifies; otherwise it falls back to the cookie and setting. Test: an editor sending a forged `X-CC-UI: all` gets the setting's variant. **When the server cannot serve the asking page's look, it makes the page reload itself** (wave 5). Want is a line nobody on a wall display presses, and three cases leave the server unable to serve the page's own look: phase 8b deletes the classic templates while every customer's open classic pages keep polling; a rollback to a build that predates an enabled group, which the product does unattended (the one-click roll-back in Settings > Packages, `dashboard_update.js` ROLLBACK_URL, and `dashboard_update`'s watchdog auto-revert, `dashboard_update.py:44-47`) and which never runs a runbook step; and a signature that no longer verifies (a re-sign-in changes the sid, as it does for the CSRF token, `account_ui.py:19-22`). So whenever `_render` cannot serve that look it answers an htmx GET with `HX-Refresh: true` and an empty body (htmx 1.9.12 obeys it) and a write with 409 plus the Want line, never a fragment in the other look. "Cannot serve" is (wave 6, redefined): the header set names a group with no `cc/` templates in THIS build, or a name it does not know (from phase 0 all six names are valid values, so "does not know" alone would never fire after a rollback from phase 4 to phase 3 with `settings-fleet` on: the phase 3 build knows the name, sends only Want, and swaps the classic `admin_users` partial into the cc frame); the page's set is empty (or its token predates 8b) on a build with no classic templates; the signature does not verify for a non-empty set. The unknown-group rule ships in PHASE 0, so every later build already applies it when an older build is rolled back to, and phase 8b keeps parsing `X-CC-UI` for this answer. Because every resolved set is intersected with this build's groups (7.0, wave 6), the reloaded page no longer names the missing group and polls cleanly: exactly one reload, never a loop. Tests: a page with set `{chrome,settings-fleet}` polling a build without `settings-fleet` templates gets exactly one HX-Refresh, and the reloaded page renders `data-ui-groups` without it and then polls with no HX-Refresh; a stored `{chrome,home,settings-fleet}` on a build without `settings-fleet` templates renders `data-ui-groups=chrome,home`; a classic page polling 8b gets HX-Refresh; a forged or stale signature gets HX-Refresh (GET) or 409 plus Want (write), never a fragment in the other look. **The token is scoped to the page** (wave 5): one global digest would raise the reload line on every open page after every phase deploy, since each phase changes `cc/` templates of groups that are off, and the owner would learn to ignore the line. `X-CC-UI-Gen` is a digest of the asset hashes of the sheets and scripts the page's shell loads plus the `cc/` templates of the groups in the page's own set (for `{chrome}`: the three chrome overlays, `halt_line`, `hint_sheet` and `cc/hud.css`), and `_render` recomputes the same scoped digest for the asking set. Test: a changed `cc/fleet.html` deployed while only `chrome` is enabled raises no Want on a classic-bodied page, and raises it on a page whose set holds `home`. `docs/RELEASE.md`'s rollback runbook: running `tools/ui_variant.py off` before an image rollback is still good practice, but open pages reload themselves (above) whether or not it ran, **provided the build they land on is at or above the header floor** (wave 6, below). Test: render a page under template list A, poll it with token A against a server holding list B, assert Want is sent and no cross-variant partial is served. **Any `HX-Refresh` answer on a write or a hand-written fetch** (wave 6): a script that fetches a `/partials/` URL itself (today only `static/cc/dashboard_update.js`'s `reloadPanel()`; `account.js` uses `htmx.ajax`, which obeys the header) treats `HX-Refresh: true` like `HX-Redirect` and calls `location.reload()` before reading the body, and treats a 409 carrying `X-CC-UI-Want` as an error line, never a swap (3.3). **The header floor** (wave 6): an image from before phase 0 reads no header at all, and the unattended paths (the Packages image rollback posting `ROLLBACK_URL` with an empty `to_version`, the watchdog revert "to the previous tree (or the image)", `deploy/select_code_root.py`'s "any single failure means boot the image") can land on such an image with no runbook step, because the port adds no dependencies, so every phase could arrive as an OTA bundle on a pre-phase-0 image with the same `runtime_id`. So phase 0 reaches this studio, and later the vendor feed, as a new IMAGE, not only as a bundle; `ui_variant.HEADER_FLOOR` names the first version that parses `X-CC-UI`; while `dashboard_update.image_version()` is below it in image mode, enabling any group and `/ui/preview?variant=cc` are refused (422 or 403 naming the image version and the NAS-UI image update, shown the same way by `ui_variant.py set` and the groups form); and phases 1-8 carry a signed `min_image_version` = `HEADER_FLOOR` in their feed records, which `dashboard_update`'s preflight enforces (the bundle is refused on an older image). Tests: the groups PUT with a stubbed `image_version` below the floor is 422; a bundle record with `min_image_version` above the image is refused by preflight. |
| R24 | **The rollback control is on a page that might be broken.** The only site-feature toggle today is the Settings form, which phase 4 ports. | The setting is flipped without rendering any terminal template: `tools/ui_variant.py off` (a `PUT /api/v1/admin/site` with the groups set to `none`, see below; that route already calls `site_store.invalidate`). **The tool signs in like `tools/jobs.py`** (wave 4: a minted session needs the session secret, SSH, a `docker exec` INSERT into `auth_sessions`, a CSRF HMAC and a matching `Origin`, which is a scratchpad recipe, not a tool, and `tools/` is not in the image): `jobs.py`'s `Client`/`Http` (`POST /api/v1/login`, password from the terminal or `--password-stdin`, CSRF from the login answer) are factored into a shared module, and `ui_variant.py` offers `off`, `site`, `set <groups>` and `show` with the same password hygiene. `tools/tests/test_ui_variant.py` with a stub sender: `off` sends exactly `{values: {ui_terminal_groups: "none"}}` with the `X-CSRF-Token`, and a set without `chrome` is refused locally. `docs/RELEASE.md`'s runbook names the command. The second path is a group control on the CLASSIC Settings page, reachable with the `classic` cookie. **That control is its OWN form**, `<form id="ui-groups-form">` OUTSIDE `#settings-form`, handled by a small new `static/ui_groups.js` that sends only `{values: {ui_terminal_groups: "chrome,home"}}` (a CSV value, `_validate_csv`). It is never a checkbox list inside `#settings-form`: `site_settings.js:852-869` walks every named element of that form and writes a checkbox as `values[el.name] = el.checked ? "1" : "0"`, so same-named boxes collapse to one `"1"`/`"0"`, `site_store.set_many` refuses the whole write on that one bad field, and no admin could save ANY site setting from phase 0 on. And the general save must never carry the key at all, or an admin saving an unrelated field from a Settings tab opened before `tools/ui_variant.py off` would silently re-enable the group just rolled back. Tests: the classic save (serialised exactly as `site_settings.js` does) and the phase 4 `cc/site_settings.js` save both PUT successfully and never contain `ui_terminal_groups`. **Look changes are kept OUT of `site_history`** (wave 4, replacing wave 3's "undo skips `ui` entries", which could not work: `site_settings.js:818-833` arms the undo on `entries[0]` and sends `expected_at: latest.at`, so a skipping server answers 409 "someone saved since" on every click; `SITE_HISTORY_KEEP = 10` (`db.py:4041`) would let a preview's flips push out the tree-key snapshots the undo exists to restore; and after `tools/ui_variant.py off` and an image rollback, the pre-phase-0 undo would run `validate_many` on an unknown key and 422 every click). Phase 0 records group changes under their own meta key, `ui_groups_history` (capped separately), from `api_admin_site_put`'s new `ui_terminal_groups` branch and from the tool; the classic `#ui-groups-form` shows that list, and the undo for a look is the tool or the groups form. `site_history` never contains a key an older build cannot validate. Tests: after `ui_variant.py off`, `GET /admin/site/history` entries[0] is still the last real save, and a classic undo sent exactly as `site_settings.js` sends it (with `expected_at`) returns 200; twenty group flips leave a tree-key snapshot in `site_history`; no `site_history` entry ever contains `ui_terminal_groups`. **The import path refuses the key** (wave 4): `site_store.import_toml` (`site_store.py:988-1003`) takes any `KEYS` member found in any known section, so a pasted `[site] ui_terminal_groups = "chrome,home"` would re-enable a rolled-back group and be recorded as an ordinary `import` entry. It refuses `ui_terminal_groups` with a message pointing to the groups form or the tool, `export_toml`'s `_SECTIONS` never lists it, and a test asserts an import carrying it is 422 and changes nothing. **Off is a value, not an empty row** (wave 3): `site_store._shape.pick()` returns any stored row, even `""`, over the default, so an empty row would permanently mask phase 8's "default on". Off is stored as `none`; a `site` value (the tool's `ui_variant.py site`, and the form's "follow the vendor default" choice) DELETES the row, through a new delete path on the site store; and `ui_terminal_groups` joins `template_folders` in `_settings_fallback`'s special case, so an undo that would write the fallback deletes the row instead of writing `""`. **`chrome` is refused, never added** (wave 3; `site_store.validate` never guesses a corrected value silently): `_validate` answers 422 for a set holding any group without `chrome` (test: `{values: {ui_terminal_groups: "home"}}` is 422), the groups form shows `chrome` ticked and disabled while any other group is on, with "the new header is part of every new page; turning it off turns them all off", and the tool offers only `off` for the HUD. Per browser, `/ui/preview?variant=classic` is the escape, reachable as a link from the HUD user menu and the classic `/account` page (3.4), so it works inside an installed iOS app too. All of this is written down in `docs/RELEASE.md`, naming the account-page link as the per-device escape. An environment variable is NOT a rollback path: a stored site row beats `DASH_SITE_*` (`site_store.feature_enabled`). |

---

## 7. The order

### 7.0 The mechanism: a template overlay behind a per-group setting

- **One Jinja environment per effective group set**, never one environment
  whose loader decides per request. Jinja caches compiled templates per
  environment under `(loader, name)` and only asks the loader again when
  `uptodate()` (an mtime check for file loaders) says the file changed, and
  `{% include "partials/topbar.html" %}` resolves through the same cache at
  render time. So a single terminal environment with a request-dependent
  loader would serve whichever variant of `partials/topbar.html`,
  `fleet.html` and so on it compiled first to every later request (the
  owner's `cc` cookie preview putting the HUD on every editor's page, a
  rollback doing nothing until a restart); an `uptodate` keyed on the
  request would instead recompile on every alternation, a real cost on the
  2 s transfers poll under `--workers 1`. So: the classic environment is
  `FileSystemLoader(templates/)`, as today (the empty set). Each other
  distinct set (a frozenset of the group names, `chrome` always in it, plus
  `all` for the `cc` cookie; at most 33) gets its own environment, built
  lazily under a lock and memoised in a dict:
  `ChoiceLoader([GroupFilteredLoader(templates/cc, groups), FileSystemLoader(templates)])`,
  whose group filter is FIXED when it is built, so its cache is correct by
  construction. `_render` resolves the set, picks the environment, and
  renders through a `Jinja2Templates` wrapper for it. **Each per-set
  environment is a CLONE of the classic one** (wave 3): today's environment
  comes from `Jinja2Templates(directory=...)` (`ui.py:64`), which Starlette
  builds as `jinja2.Environment(loader=..., autoescape=jinja2.select_autoescape())`;
  the `env=` path keeps whatever it is handed, and a bare
  `jinja2.Environment` defaults to `autoescape=False`, which would emit
  display names, project and folder names, notice bodies and error details
  raw on every terminal page (stored XSS on an admin surface). So each set's
  environment is `templates.env.overlay(loader=ChoiceLoader([...]))`, which
  copies autoescape, `undefined`, extensions and every other option, and it
  is wrapped with `Jinja2Templates(env=...)`. The classic environment's
  loader is ALSO restricted so it can never load `cc/*` (a filtered
  `FileSystemLoader` that refuses names under `cc/`); the second loader of
  each ChoiceLoader is that same filtered loader, so the group filter cannot
  be bypassed by asking for `cc/...` by name. All get the same globals and
  filters: today they are registered on `templates.env` at import time
  across `ui.py`; `sync_envs()` copies them into every environment it
  builds. The parity test, over every environment built so far, asserts
  equal `globals`/`filters` key sets, equal `undefined`, `extensions`,
  `trim_blocks`/`lstrip_blocks`, and identical escaping behaviour (render
  `{{ '<b>' }}` from a `.html` template and assert `&lt;b&gt;`); and
  `templates.env.get_template('cc/shell.html')` raises
  `TemplateNotFound`. A phase 0 test
  renders the same name alternately under two sets in one process (and
  from two threads), and renders `/` with the `cc` cookie, then with none,
  then flips the setting between two requests with no restart, asserting
  each render gets its own variant every time.
- **The gate is per page group, not one switch.** A single on/off flag
  cannot stage phases 2-6: once it is on for the chrome, every `cc/`
  template in the next image is live for everyone on deploy. So the site
  setting is a LIST of enabled groups, `ui_terminal_groups` (values
  `chrome`, `home`, `everyday`, `settings-fleet`, `settings-health`,
  `apps`; empty by default). Every `cc/` template is mapped to exactly one
  group in one table (`ui_variant.TEMPLATE_GROUPS`, a test asserts every
  file under `templates/cc/` is in it). The environment for a set serves
  `cc/<name>` only when that template's group is in the set, and falls back
  to classic otherwise. A test asserts, across repeated renders in one
  process, that a `cc/` template outside the set is never served.
- **A panel that moves between groups stays at its source until its
  destination is on** (wave 4). Phase 5 moves notices, collector and
  diagnostics from the terminal home (group `home`, enabled since phase 2)
  to Health (group `settings-health`, off at deploy). Deleting them from
  `cc/fleet.html` in phase 5 would change an enabled group's page on
  deploy, against "deploy never turns a group on", and a site with `home`
  on and `settings-health` off would have problems.log on neither page
  (classic Health only links to `/#server-notices`). Rule: a moved panel
  stays in its source template behind `{% if '<dest-group>' not in
  ui_groups %}` until phase 8, and `/go/<panel>` resolves on the pair
  (source group on?, destination group on?): destination if it is on,
  else the terminal source if that is on, else classic. The same holds for
  D17's tree (its source pages simply stop carrying it only when their own
  group is enabled) and for the queue's move to the account page. Every
  test that decides this (the R1 census, the R13 `/go` walk, the R15
  fetch map) runs over every set a phase can produce: classic, `{chrome}`,
  each cumulative prefix of enabled groups and `all`. The phase 5
  `{chrome,home}` case (notices, collector and diagnostics still on home,
  `/go/notices` to `/#server-notices`) is an explicit census input and
  test.
- **The per-browser cookie is three-way and beats the setting:**
  `ccsync_ui=cc` (every group, the owner's preview), `ccsync_ui=classic`
  (no group: the per-browser escape), or absent (follow the setting).
  `GET /ui/preview?variant=cc|classic|site` writes or clears it (signed-in
  users only, except that `classic` and `site` work signed out (3.4, wave 5);
  it changes only that browser; a GET is fine because it writes nothing
  server-side). `variant=cc` is allowed only by the dashboard-only site
  setting `ui_preview` (`off` in the vendor build, `admins`, `everyone`;
  never in `/api/v1/site`'s `features`), and a cookie `cc` presented by a
  role the setting does not allow is read as absent (waves 4 and 5, 3.4).
  The `cc` value is signed (an HMAC over `cc` and the admin who set it), so
  a signed-out request can honour it for the owner's login and setup
  previews and for nobody else (3.4). **The cookie's attributes** (wave 5;
  without an expiry it is a session cookie, which iOS standalone apps drop
  when the app closes, taking the owner's preview and the per-device
  classic escape with it): `Max-Age` 180 days, `Path=/`, `SameSite=Lax`,
  `Secure` under `cookie_secure()`, `HttpOnly`. Test on `/ui/preview`:
  Max-Age and Path for `cc` and `classic`, and `site` deletes the cookie
  with `Path=/`.
- `_render` decides the group set per request in this order (wave 6): (1)
  the `X-CC-UI` header on an htmx request (the set of the page that asked,
  R23); (2) otherwise, a request carrying `HX-Request: true` with NO
  `X-CC-UI` header resolves to the EMPTY set (classic), because the only
  askers of that shape are pages loaded before the phase 0 deploy (nothing
  reloads them, so a wall display on classic `/` keeps its 30 s stamp and
  15 s grid polls) and the frozen classic `static/dashboard_update.js`
  (`reloadPanel()` sends `HX-Request` alone, `dashboard_update.js:60`, and
  inserts the answer with `outerHTML`); the answer is the CLASSIC fragment,
  plus `HX-Refresh: true` on a GET (or 409 plus Want on a write) when a
  full load would now give a non-empty set for `chrome` or for the asking
  page's group (htmx 1.9.12 reloads on `HX-Refresh` before any swap, and
  the classic script, which ignores the header, still inserts classic
  markup into its classic page); (3) only non-htmx fetches (the SPAs'
  topbar fetch, which sends no `HX-Request`) follow the cookie, then the
  setting. A page and its partials therefore agree even across a change of
  setting. Tests (phase 0): an `HX-Request` GET of `/partials/stamp` with no
  `X-CC-UI` and `chrome` on gets classic stamp markup with `HX-Refresh`,
  never `cc/partials/stamp.html`; the classic `dashboard_update.js`
  request pattern (`HX-Request` only) on `/partials/admin/dashboard-update`
  with `settings-fleet` on never receives a cc partial.
  **Every resolved set is intersected with THIS build's groups** (wave 6):
  the setting, the cookie and the header are each intersected at resolve
  time with the groups that have at least one `cc/` template in the running
  build (from `TEMPLATE_GROUPS`) before the set is emitted in
  `data-ui-groups`, `X-CC-UI`, the Sig or the scoped digest. `all` already
  did this; an explicit stored list must too, or a stored
  `{chrome,home,settings-fleet}` on a rolled-back phase 3 build would put
  `settings-fleet` into every page's header and reload-loop (below). The
  intersection is also the reason a group enabled early does nothing
  until its build lands. `X-CC-UI: all` serves every `cc/` template
  that exists (the page was fully terminal when it loaded, so its partials
  must be too, even after a rollback); an empty value serves none. Every
  group other than `chrome` implies `chrome` (a `cc/` page extends
  `cc/shell.html`, which includes the HUD); validation REFUSES a set that
  breaks this, and never adds `chrome` silently (R24, wave 3). `all` is
  expanded at render time to the concrete groups this build has `cc/`
  templates for, and a generation token rides beside the set (R23).
- Every full-page response, the `/partials/topbar` response (which every
  SPA fetches on every load) and the login gate's pass-through for
  navigations to `/broll/`, `/music/`, `/ytdl/` (NOT under `/broll/share/`,
  the sessionless Funnel-published client viewer, and never api or media
  paths; a test asserts a GET of `/broll/share/<token>/` carries no
  `Set-Cookie`; wave 3) set a readable (not
  HttpOnly) cookie `ccsync_ui_effective` for the `chrome` and `apps` groups
  (wave 4: a list, so a SPA's first-paint script also knows whether the
  HUD is coming), with an explicit `Path=/` (set under `/admin/...` without
  one, the SPAs could not read it). **The list is dot-separated**
  (`chrome.apps`, `chrome` or empty; wave 5): a comma is not a legal
  cookie-octet, and Starlette's `set_cookie` (via `SimpleCookie`) sends
  `chrome,apps` as `"chrome\054apps"`, checked in the dashboard venv, so the
  first-paint parse would see neither word once both groups are on, and a
  TestClient cookie jar unquotes it back and hides the defect. The server
  `set_cookie` and the client rewrite use the same format. Tests: the RAW
  `Set-Cookie` header of a gate SPA navigation and of `/partials/topbar`
  with chrome and apps on is unquoted with no backslash; a per-SPA test
  runs the first-paint parse over that exact raw header string, not a
  cookie jar. **`/partials/topbar` sets the cookie itself** (wave 5): the
  `is_partial` rule below keeps full-page cookie logic off fragments, so
  `partial_topbar` calls the same helper explicitly after `_render`. Test:
  `GET /partials/topbar` with chrome on returns `Set-Cookie:
  ccsync_ui_effective=...; Path=/`, not HttpOnly, and another
  `/partials/*` route returns none. **The client-side rewrite uses the same path** (wave 4): a
  `document.cookie` write from `/broll/` without a path creates a second
  cookie scoped to `/broll/`, listed FIRST for pages under it, so the
  first-paint script would read the SPA's own stale value forever. The write
  is exactly `document.cookie = 'ccsync_ui_effective=' + v + '; path=/;
  samesite=lax'` plus `; secure` when `location.protocol === 'https:'`
  (matching the server's attributes); it passes ytdl's `_ABSOLUTE` because
  no quote precedes the slash. A per-SPA test asserts the write carries
  `path=/`. **The HUD's height is reserved before the topbar arrives**
  (wave 4): each SPA first paints its static fallback header and swaps in
  the fetched bar (`broll app.js:299`, `music :902`, `ytdl :3165`), so under
  `chrome` every b-roll, music and youtube load would jump from a bracketed
  row to the 58 px HUD, against "nothing shifts". So the first-paint head
  script is added in PHASE 1, not phase 6: when the cookie holds `chrome`
  it sets `html.cc-chrome`, and each SPA sheet carries
  `html.cc-chrome #dash-topbar:not(:has(> .hud)) { min-height: 58px }` and
  `html.cc-chrome #dash-topbar:not(:has(> .hud)) > * { visibility: hidden }`
  (the phone height in the phone query), plus `html.cc-chrome #dash-topbar +
  .rule { display: none }` (wave 5: the reservation otherwise leaves the
  SPA's box-drawing `.rule`, `broll style.css:392`, music `:385`, ytdl
  `:375`, in place until the HUD arrives, so everything below moves up one
  line on every load; `share.html` has no `#dash-topbar`, so it is
  share-safe, and it joins R22's allow-list and the phase 1 per-SPA
  CSS-fact test). The injected marker corrects a stale cookie as below.
  **The reservation never outlives a failed fetch** (wave 5): all three
  loaders return without injecting on `!res.ok || res.redirected`, a
  missing marker or a thrown fetch (`broll app.js:297-307`, `music
  :900-911`, `ytdl :3163-3174`), and the fallback header they leave holds
  the SPA's only way out, `[ DASHBOARD ]`; a 503 from `/partials/topbar`
  (more likely now that it computes the notice and alert counts, 3.4), an
  expired session or a network blip would otherwise leave a blank 58 px
  band, and a classic topbar injected under a stale `chrome` cookie has no
  `.hud`, so the hide rule would hide the injected bar itself. So each
  loader removes `html.cc-chrome` in a `finally` on every path, re-adds it
  only when the injected markup contains `.hud`, and rewrites the cookie's
  chrome part to match what arrived; as a CSS-only safety net the hide
  rules key on a separate `html.cc-chrome-pending` class, which the script
  clears when the fetch settles or after about 3 s. Tests per SPA: a 503 or
  redirected fetch leaves the fallback `[ DASHBOARD ]` link visible and the
  class removed; a classic topbar injected under a `chrome` cookie shows its
  children. The SPAs pick their body variant from it before first
  paint (phase 6). Because an editor may only ever open `/broll/` directly,
  the injected topbar's marker is AUTHORITATIVE in both directions once it
  arrives. **The marker is defined** (wave 3): `data-ui-apps="cc|classic"`
  on the `data-dash-topbar` element, in BOTH topbar partials, computed from
  whether `apps` is in the effective set `_render` resolved for that
  request, never from which topbar variant was served (`chrome` is on for
  this studio from phase 1 while `apps` stays off, so a constant `cc` in
  the HUD partial would restyle every SPA body on the first phase 6
  deploy). A missing or unknown marker means classic; a failed or
  redirected topbar fetch leaves the class as it is. After injection the
  SPA sets or clears the class from the marker and rewrites the cookie
  client-side, so a stale `cc` cookie after `apps` is rolled back lasts one
  early paint, not indefinitely. **The class is `html.cc`, not `body.cc`**:
  the first-paint script runs in `<head>`, where there is no
  `document.body`, so it sets the class on `document.documentElement`, and
  every SPA body rule is written under `html.cc`. Tests per SPA: with
  `chrome` on and `apps` off the marker is `classic` and the class is
  removed; with `chrome` off (classic topbar) the class is removed; with
  `apps` on it is set.
- **Plumbing** (phase 0): `ui_terminal_groups` is a site setting read by the
  dashboard only (a `KEYS` entry with validation against the group names,
  and (wave 6) `_validate` answers 422 for a group with no `cc/` templates
  in the running build, so `tools/ui_variant.py set chrome,apps` at phase 1
  cannot store `apps` and have the phase 6 deploy switch every SPA body on
  by itself; the groups form lists only groups this build has templates
  for and shows a stored one without templates as "waiting for its build";
  test: `PUT {ui_terminal_groups: 'chrome,apps'}` on a build without
  `apps` templates is 422; a
  `Settings.site_ui_terminal_groups` attribute plus its `DASH_SITE_*` env
  default, the defaults maps in `site_store`, and the resolved manifest
  `_render` reads). It is **not** a `[features]` entry and is never added
  to `GET /api/v1/site`'s `features`: that dict goes to every companion, and
  `test_site.py`'s `set(features) == {...}` pin stays unchanged as the
  guard. The rollback path that renders no terminal template is R24.
  Also in phase 0 (wave 3): the `none` value, the row-delete path, the
  `_settings_fallback` special case, the `chrome` refusal and the `ui`
  `ui_groups_history` branch in `api_admin_site_put` (kept out of `site_history`), the `import_toml` refusal (all R24);
  and `site_store.manifest_for_app` stops caching its fallback shape. Today
  a failed read (a transient `database is locked` on the first render after
  boot) caches `_shape({}, settings)` on `app.state` until the next site
  write, which before the port only mis-branded pages and after it would
  flip the whole studio to classic for the life of the process and raise
  the reload line on every open terminal page. The fallback is used for
  that render only and the next render retries (or the last good
  `ui_terminal_groups` is kept in memory). Test: the first manifest read
  raises, the second succeeds, and the second render is terminal.
- A ported page is `templates/cc/<name>.html` extending `cc/shell.html`. An
  unported page is found in `templates/` by fallback, extends classic
  `base.html`, and still includes `partials/topbar.html`, which the terminal
  loader resolves to `cc/partials/topbar.html` (the HUD) when `chrome` is
  enabled. That is why classic `base.html` links `cc/hud.css` then (2.2),
  why it swaps its `.topbar` wrapper for a bare host then (3.4), and
  why the new shell is NOT called `base.html` (the overlay would then wrap
  every classic page in the new shell).
- **New-named terminal partials** (wave 3). A terminal partial with no
  classic twin (`home_transfers`, `home_problems`, `home_collector`,
  `home_queue`, `home_fix_root`, `computer_answer`, `projects_tree`,
  `halt_line`, `hint_sheet`, `person_queue`, `person_fix_root`,
  `health_notices`, `health_collector`, `health_diagnostics`) lives only under `templates/cc/partials/` and is
  addressed WITHOUT the `cc/` prefix (`partials/home_transfers.html`), so it
  goes through the group filter like any overlay and is reachable only from
  an environment whose set holds its group. Each polled or fetched one is
  served by its OWN route (`/partials/home-transfers`,
  `/partials/projects-tree`, `/partials/halt-line`, `/partials/home-problems`,
  `/partials/home-queue`, `/partials/computer-answer`,
  `/partials/person-queue`, `/partials/health-notices`,
  `/partials/health-collector`, `/partials/health-diagnostics`) that answers
  404 when its group is not in the resolved set; the classic route it
  replaces on that page (`/partials/transfers` renders
  `partials/transfers.html`, so polling it would swap classic markup into
  the terminal window) is never polled by a cc page. `_render`'s
  full-page-versus-fragment test stops being `name.startswith("partials/")`
  (`ui.py:707`, `:717`) and becomes an explicit `is_partial` decided from
  the name's last directory (`name.split('/')[-2:-1] == ['partials']`), so a
  fragment never pays for `_stamp_context`, `_notice_counts_safe` and
  `_alert_counts_safe` or gets the full-page cookie logic. Phases 1, 2, 3
  and 5 list every new-named partial with its route.
- Rollback at any phase: take the group off the setting (R24), and every
  browser goes classic for that group on its next full load; an open page
  keeps its variant until reloaded, and is told to reload (R23). Per
  browser: `/ui/preview?variant=classic`. No image rollback is needed for a
  look problem. A behaviour bug in a shared route falls back to the
  dashboard's normal rollback, and an image rollback past the phase that
  introduced an enabled group is preferably preceded by
  `tools/ui_variant.py off`; open pages whose look the older build cannot
  serve reload themselves through `HX-Refresh` (R23, wave 5), on any build
  at or above `ui_variant.HEADER_FLOOR`, which the image floor of R23
  guarantees (wave 6).
- The overlay is temporary. Phase 8 deletes classic, moves `cc/` up, and
  removes the loader, the setting and the cookie route. It keeps PARSING
  the group-set header (wave 5), only to answer `HX-Refresh` to a page
  whose look it can no longer serve (R23). The generation token and its reload line stay for good (R23).

**Cheaper alternative, not recommended:** port page groups in place, with no
flag, and roll back with the dashboard's image or bundle rollback. It saves
the environment plumbing and the dual-maintenance window, but the owner
cannot see a ported page on the live fleet before editors do, and a bad look
costs a redeploy.

### 7.1 Phases

Every phase is one commit series on `main`, gated by
`tools\run_all_tests.ps1` (13 suites), the mobile sweep on the seeded
server at 390, 768 and 1440 in both variants, the em-dash and bracket scans,
and a control census (R1). **Which gate runs what** (wave 3): pytest (and so
CI and `publish_latest`'s green-run gate) runs the suites, the scans and
the census's static half. The census click half (`tools/census_click.js`)
and the sweep's `--variant` runs are node plus Chrome against the seeded,
signed-in server; `run_all_tests.ps1` and `ci.yml` run neither, so they run
per phase on the base rig and their JSON reports and screenshots are
attached to the phase report, which the owner's review reads before a group
is enabled. Then a dashboard version bump and a deploy
(dashboard first; the SPAs ride the image; Cards and companions are not
touched). **Tests:** classic pins are kept as they are (R11); the commit
that adds a `cc/` template adds the terminal assertions for it, through
explicit `ui_variant`-parametrised tests that run in the ordinary suite
(and so in CI and the vendor feed's green-run gate); the phase 0
coverage meta-test fails any `cc/` template no terminal test renders.
There is no second suite run and no `DASH_UI_VARIANT` (R11). Each phase's
partial list was checked against the include map (R15).
**Deploy never turns a group on.** Each
phase deploys with its group off; the owner previews it with the `cc`
cookie on the live fleet, in a desktop browser AND from the installed app
on the iPhone (set through the HUD user menu's link, 3.4, since the
installed app has its own cookie jar); then the group is added to `ui_terminal_groups`
(R24's tool) as a separate, reversible step.

| Phase | What | Shippable because | Verification | Deploy |
|---|---|---|---|---|
| **0. Foundations** | `static/cc/terminal.css` (with theme-common byte-identical and the cc `:root` defining every token it reads, 2.1), `components.css` (with the field, textarea and select paint, 2.1), `phone.css` (merged and deduplicated from the bench, tokens fixed from TUNE, contrast and 12 px floor fixed, no Google Fonts, no box-drawing glyphs needed in markup, `content: "\2f\2f"`), an empty-block `static/cc/hud.css` scaffold; `static/fonts/` + notices + the `.woff2` MIME registration (2.3); `static/cc/cc.js` (fold store, tips + sheet, `htmx.onLoad`, the confirm dialog handler and tab activation of 3.2; no TUNE); `static/cc/copy_value.js`; the per-set environments and `TEMPLATE_GROUPS` plus the route-to-group table, `sync_envs`, the `ui_terminal_groups` setting and its plumbing (7.0), the three-way cookie route, the `X-CC-UI` group-set header in both shells and `data-ui-groups` on classic `base.html` (R23), `/go/<panel>` redirects for the whole R13 table, `tools/ui_variant.py` and the separate `#ui-groups-form` with `static/ui_groups.js` on the CLASSIC Settings page (R24); `asset_url()` global; `sw.js` PRECACHE additions (hashed `cc/` entries, fonts at plain URLs); `mobile_sweep.js` (1440, new pages, `.key`/`.tag`, `--variant`, occlusion check); the control-census tool with its state-matrix fixture, load-trigger following and confirm stubs (R1); the bracket scan with a full allow-list; the retired-phrase terminal twins (R12); the new CSS-fact test file for `cc/`. **The test switch:** a `ui_variant` fixture. **For every non-classic parameter it makes the SETTING resolve to that parameter's concrete groups, through one seam** (wave 6: 129 test files build their own app with `create_app(`, each with its own tmp DB, bound at import time (`test_home_layout.py:32,43`, `test_packages.py:49-70` plus two inline apps), and `conftest.py` provides no shared app or client, so a fixture that wrote a row through `site_store` could not know which DB or which `app.state` to use): every reader of `ui_terminal_groups` goes through `ui_variant.site_groups(conn, settings)`, which the fixture monkeypatches, so any app a test builds resolves to the parameter's set with no DB write; the real `site_store` path has its own tests. The fixture also yields `ui_variant.htmx_headers(client)`, which builds `X-CC-UI`, `X-CC-UI-Gen` and a valid `X-CC-UI-Sig` from the client's own session cookie and `client.app`, and each parametrised file's local client fixture takes `ui_variant` as an argument, so no file learns the DB. Self-test: a file-local `create_app` client under the `all` parameter renders a non-empty `data-ui-groups` on `/` (`all` is every group name; wave 5: a `cc` cookie from a non-admin session is read as absent, `X-CC-UI` is honoured only on htmx requests, and no cookie value means `{chrome}` or `{chrome,home}`, so without the setting every editor-session page and every full page of a partial set rendered classic and the terminal parameters passed vacuously); the cookie is only an extra, admin-only path under test, and the headers are set only on `HX-Request` calls; on every full-page response it asserts `<html data-ui-groups>` equals the expected set, so a silently classic render fails (self-test: an editor-session GET of `/` under `all` carries a non-empty `data-ui-groups`). The headers it sends on htmx calls are those a real page sends: `X-CC-UI` with the EXPANDED concrete group list, `X-CC-UI-Gen` read from the app (`ui_variant.current_generation()`) and a valid `X-CC-UI-Sig`, R23, wave 4; or renders through the matching environment). It is parametrised over classic, `{chrome}`, the previous phase's cumulative set (for example `{chrome,home}` while phase 3 is built) and `all`, never only classic and `all` (7.0's cross-group rule), the template/CSS path resolver, the coverage meta-test over `TEMPLATE_GROUPS` (R11), `OWNED_TEMPLATES` and d-ui's template glob extended to `templates/cc/`, the d-ui Chrome harness parametrised by variant (R3). `test_static_js_syntax.py` collects with `rglob` (vendored excluded) plus a `cc/shell.html` `ON_EVERY_PAGE` set naming the cc copies. `cc/terminal.css` added to `FLEET_STYLESHEETS` in all four suites. Wave 3 additions: per-set environments cloned by `overlay()` and the classic loader refusing `cc/*` (7.0); the `is_partial` fragment test in `_render` (7.0); `CC_OWNED_TEMPLATES` (R11); the coverage check as a `pytest_sessionfinish` hook (R11); the census static half in pytest, `tools/census_click.js` for the click half (R1); the bracket-scan extractor and the per-entry retired-phrase twin table (R12); the `site_store` changes of R24 (`none`, row delete, `_settings_fallback`, `chrome` refusal, the `ui_groups_history` meta kept out of `site_history`, the `import_toml` refusal) and the `manifest_for_app` fallback fix (7.0); `tools/ui_variant.py` on a shared login client factored out of `tools/jobs.py` (R24, wave 4); `Cache-Control: no-cache` on the dashboard's `/static` mount and `fetch(req, {cache: 'no-cache'})` in `sw.js`'s revalidation (R8, wave 4); `/ui/preview?variant=cc` admin-only and the signed header set (3.4, R23, wave 4); the generation token in classic `base.html` (R23; `cc/shell.html` does not exist until phase 1, wave 5); the `/ui/preview` redirect to `next` and the three links on the classic `/account` page (3.4); wave 5: the new `hx-headers` keys are appended AFTER `X-CSRF-Token` in base.html's single-quoted attribute (`base.html:171`), the JSON built by `tojson` so a group list cannot break the quoting (`test_sessions.py:377` pins `'hx-headers=\'{"X-CSRF-Token": "'`, `test_pwa.py:215` parses every value); the `HX-Refresh` answer for a header set naming an unknown group (R23); `?h=` immutable only on the current hash (R8); the woff2 family-in-notices test and the `unicode-range` coverage scan (2.3); `cc/*.css` in `test_no_em_dash.py` (R12); `cc.js`'s confirm handler per 3.2 (question check, re-dispatch), tab ARIA and scroll, fold-unfold on answers (3.1). | Nothing renders differently: `templates/cc/` is empty and no group is enabled. The only classic-visible changes are an `X-CC-UI` header value and a `data-ui-groups` attribute, and the separate groups form on Settings. | Suites green; `test_static_js_syntax` parses `static/cc/*.js` (by the rglob change); env-parity test over every built environment; the alternating-render and setting-flip tests (7.0); every `cc/` file is in `TEMPLATE_GROUPS`; the cookie route sets all three states and needs a session; `ui_terminal_groups` absent from `/api/v1/site` (`test_site.py` unchanged); both Settings saves PUT successfully and never carry `ui_terminal_groups` (R24); a test that `tune` appears nowhere under `static/`; the `/offline` precache test with its five-entry classic allow-list (2.5); the census self-tests (R1, including removing `machine=` fails it); the env parity test with the autoescape render and the classic loader's `cc/` refusal made REAL (wave 5: with `templates/cc/` empty, `get_template('cc/shell.html')` raises whether or not the filter exists): the test writes a temporary `cc/probe.html` into a fixture templates dir and asserts the classic environment raises for it while a per-set environment holding its group loads it, with a second assert on `cc/shell.html` once it exists; every file under `templates/cc/` except `shell.html` and the new-named partials shadows an existing `templates/<same relative path>` (wave 5: a `cc/project_detail.html` is never served, the overlay name is `cc/partials/project_detail.html`); `test_sessions.py:377` and `test_pwa.py:215` green; the manifest-fallback retry test; `{ui_terminal_groups: "home"}` is 422; after `ui_variant.py off`, a classic undo sent as `site_settings.js` sends it returns 200 and `site_history` holds no `ui_terminal_groups`; an import carrying the key is 422; `tools/tests/test_ui_variant.py`; an empty-set page gets no Want across a VERSION change, and a missing `X-CC-UI-Gen` is tested (R23); the `/static` no-cache and `?h=` immutable header pins (R8); the coverage recorder self-test; the bracket-scan and twin-table self-tests. Wave 6: the htmx-without-`X-CC-UI` order (7.0 step 2) with its stamp and classic `dashboard_update.js` tests; every resolved set intersected with this build's groups, the redefined "cannot serve" and the one-reload test, and `_validate`'s 422 for a group with no templates (7.0, R23); `HEADER_FLOOR`, the image-version refusal and the signed `min_image_version` preflight (R23), with phase 0 shipped as an IMAGE (7.2); `/ui/preview` in `_OPEN_GET_ONLY` with the signed-out escape tests (3.4); fonts `immutable` plus the font manifest test (R8); the `ui_variant.site_groups` seam, `htmx_headers(client)` and the file-local `create_app` self-test (phase 0 fixture); the Python bracket half over every module with its three-file self-test and the no-grow length constant (R12); the cc `:has()` focus rings for `.switch`/`.check`/`.radio`, the forced-colours switch rule, the key-local primary fills and their contrast pins, the no-`infinite`-animation, no-`backdrop-filter` and no-customer-domain CSS-fact asserts, the decorative/informational `content:` rule (2.1, 2.2, 2.4, R10, R20); `cc.js`'s `ccsync.cctab:` store and the modal `<dialog>` confirm (3.2); the 16 px computed-size check, the 360 width and the dock `scrollWidth` assert in `mobile_sweep.js` (2.2, R5); the census submitter key and its CLEAR self-test, and the click half's visibility check at 390 and 1440 (R1 (10), (11)). | Dashboard only, as a new IMAGE (wave 6, 7.2). |
| **1. Chrome** (group `chrome`) | `cc/partials/topbar.html` (HUD: `>word` nav, counts absent at zero, the stamp, the user link plus a `<button popovertarget="hud-user">` menu with sign out / everywhere / installer / help, `.hud-dock` + `#hud-more` popover, `#install-slot`, `data-dash-topbar`, no script, every class HUD-owned, 3.4); `cc/partials/settings_nav.html`, `stamp.html` (the only three chrome overlays, R15); the shell furniture `cc/partials/halt_line.html` + `/partials/halt-line` and `cc/partials/hint_sheet.html` (keeping block 2's hooks, 3.3); `cc/shell.html`; `base.html` renders a bare host instead of `.topbar` + `.rule`, and links `cc/hud.css`, when the HUD is served; **hud-common** block ADDED (never replacing the classic drawer block) in four sheets (`cc/hud.css`, the three SPAs, each placed after any block a first-occurrence test slices, 2.2), with the `#dash-topbar:has(> .hud)` reset and byte-identity tests in four suites; classic `style.css` is not edited; the `--cc-dock-h` lift blocks outside hud-common (2.2) and each SPA's own lifts (R6); SPA `@font-face` (b-roll `../../static/fonts/`, 4.2) and `@font-face` in `cc/hud.css` (`url(../fonts/..)`); b-roll's hashed or no-cache assets (R16); `htmx_errors.js` block 2 generalised with the explicit selector regardless of `data-ui` (3.2); `pwa.js`'s HUD-slot branch (2.1). New-named partials and routes in this phase: `partials/halt_line.html` on `/partials/halt-line`, `partials/hint_sheet.html` (included, no route) (7.0). Wave 3: `data-ui-apps` on the `data-dash-topbar` element of both topbars (7.0); `partial_topbar` computes the problem and alert counts (3.4); the look-switch links in `#hud-user`/`#hud-more` (3.4); `--cc-tap`, forced-colours and reduced-motion blocks in hud-common and the `scroll-padding` blocks outside it (2.2); b-roll `Cache-Control: no-cache` on `index()` and `/static` (R16). Wave 4: `header.hud-host` and the SPA reset `display: contents` so the HUD sticks, with the classic `.project-tree` lift (2.2); the standalone safe-area block and side insets in hud-common (2.2); the 601-900 `.hud-more-btn` (2.2); `--cc-dock-h` on `html:has(.hud-dock)` and one dock query (2.2); the 12 px HUD floor in hud-common (2.2); the compact phone stamp (3.4); in each SPA sheet (outside hud-common) `#dash-topbar:has(> .hud) + .rule { display: none }`, because all three SPA headers carry a box-drawing `.rule` right after `#dash-topbar` (broll `index.html:31`, music and ytdl `:29`); the SPA first-paint head script and the `html.cc-chrome` header reservation (7.0); the `/partials/stamp` and settings strip classes in the rendered class-coverage test (3.4). | With `chrome` on, every page (classic bodies included, and the SPAs) gets the HUD; off, nothing changes, because the classic topbar, drawer block and base.html wrapper are untouched. | Classic pins untouched: `test_topbar_partial.py`, the drawer sections of all four `test_theme_css.py`, `test_every_topbar_child_is_an_unbreakable_unit`. Added: terminal-variant twins of `test_topbar_partial.py` (the bar holds exactly the mounted modules, no script, counts absent at zero), `test_settings_hub.py`, `test_sessions.py` topbar asserts, `test_music_mount.py`/`test_ytdl_mount.py` `?current=` marking, the d-ui phone chip test; the HUD class-coverage test (every `popovertarget` on a `<button>`); the classic-topbar-still-painted test; the host-reset tests; the per-SPA font GET test; the b-roll share-page rule snapshot (R22); `test_mobile_css.py` and `test_theme_css.py` unchanged (classic `style.css` untouched); every SPA test that slices from a first query occurrence listed and green; the stamp-poll-from-a-classic-page test (3.4); the `pwa.js` two-slot test; chrome-on twins of the two `/offline` identity tests (R9); `/offline` precache test with chrome on. Sweep all pages at 390/768/1440 **with the classic bodies** (this is where 768 overflow shows, now in the real JetBrains Mono on classic pages too, since `cc/hud.css` carries the `@font-face`), with the occlusion check; the share page at 390/1440; each SPA with a toast and each panel open. Screenshot `/broll/`, `/music/`, `/ytdl/`, and a classic page with a sidebar at 390, with the HUD. Wave 3: the shell twin list asserted on a rendered cc page (R11); the popover no-`display` base-rule test in four suites and the `cc/` CSS-fact file (3.4); the no-`.hud`/`.dock`/`.snav`-outside-hud-common and ytdl-`_ABSOLUTE` CSS-fact tests (2.1); counts through `/partials/topbar` when nonzero; the marker tests (`classic` with `chrome` on and `apps` off); the b-roll `no-cache` header pin and `test_mounted_prefix.py:100` unchanged; the sweep's R13 anchors below the HUD at 390/1440 and the focus-occlusion check (2.2). Wave 4: the sticky checks after a 1000 px scroll on a classic page with a sidebar, a cc page and the SPAs (2.2); at 768 every mounted module one tap from the HUD; the `--cc-dock-h` root and single-query CSS-fact asserts in the cc file and each SPA suite; the no-under-12px assert in hud-common's phone query; the standalone block assert plus an installed-app screenshot; the phone stamp twin and nonzero-box sweep assert; a per-SPA CSS-fact test for the `.rule` hide and the header reservation, both in R22's snapshot allow-list; the font GET checks in the dashboard suite (4.2); the rendered class-coverage test over topbar, stamp and settings strip. Wave 5: **no page extends `cc/shell.html` until phase 2**, so every "rendered cc page" check of phases 0 and 1 (R3's harness inline scripts, the shell twin list, the `ON_EVERY_PAGE` script srcs, the hint-sheet chip test, the generation token and signature in `hx-headers`) runs against a TEST-ONLY child template, `tests/templates/cc_probe.html` extending `cc/shell.html` with an empty layout block, loaded through a test-only extra loader on the per-set environment (never a production route); the coverage hook counts it as covering the shell and `hint_sheet`. The ytdl pin `test_bug_hunt_2026_09_24_w2_music-ytdl.py:365` reads the FIRST `@media (max-width: 600px)` block and asserts `.search-bar > #q` in it, and hud-common's dock query is also 600, so hud-common goes AFTER ytdl's phone block (`style.css:1065`), or that test takes the block containing `.search-bar`; listed by name with b-roll's 700 px slice. The HUD brand sweep with a 40-character and a CJK `org_short` (2.2); the cookie attribute, dot-format, raw `Set-Cookie`, topbar-sets-cookie and failed-fetch fallback tests (7.0); the `.rule` reservation fact (7.0); the `next` derivation and Referer tests (3.4); the `ui_preview` three-state and signed-out tests (3.4); the hud-common focus ring (2.1). Wave 6: the b-roll and music scoped body-height fix and the sticky assert passing on `/broll/` and `/music/`, with `.folder-tree` and `.filter-rail` screenshots (2.2, R22 allow-list and snapshot); b-roll's `#grid-view` dock lift and the `#pager-next` hit-test at 390 (R6); no `#hud-more` stamp copy (3.4); the dock's real-inset padding, `letter-spacing: 0` and the `.hud-dock a` overflow assert at 360 and 390 (2.2); the HUD LED blink capped at four iterations and no blur in hud-common (2.4). | Dashboard (SPAs ride), group off. Owner previews with the cookie, then `chrome` is added to the setting for this studio. |
| **2. Home and project** | `cc/fleet.html`, `cc/project.html`, the home partials (`fleet_grid` split into frame and body, `plan_changes`, and under NEW names with their own routes because the fetch map puts their classic names on pages of other groups (R15, 7.0): `partials/home_transfers.html` on `/partials/home-transfers` (the Transfers page keeps `partials/transfers.html`), `partials/home_problems.html` on `/partials/home-problems` (not `notices`), `partials/home_collector.html` included by the grid body (not `collector_health`), `partials/home_queue.html` on `/partials/home-queue` with a `view=home-queue` toggle branch (not `queue_section`/`my_queue`), `partials/computer_answer.html` on `/partials/computer-answer` for READ THE ANSWER (not `admin_diagnostics`)), `project_detail` (at `cc/partials/project_detail.html`), `bins`, `missing_files`, `project_roots(_browse)`; FIX DESTINATION ROOT under a NEW name, `partials/home_fix_root.html` (wave 5: `fix_root.html` is included by `queue_section.html:13`, which splits into `home_queue` and phase 3's `person_queue`, so a same-named overlay would be reached by two groups; on the account page it is `person_fix_root`, drawn per computer window from that machine's context rather than through `/?machine=` links, since `fix_root.html:27-31` links to home, where an admin's queue is no longer drawn), both in `NEW_NAME_TWINS` with an R1 structured move; the projects tree (the sidebar is included by EVERY classic page too, so the terminal tree is `partials/projects_tree.html` under `templates/cc/partials/`, served on `/partials/projects-tree`, and `partials/sidebar.html` stays classic; a `view=tree` branch in `partial_toggle` returns tree markup for a tick from the tree, 5.1, 7.0.) The issue variant (D11). Homes for everything the bench dropped (5.1), including the empty `#fleet-diagnostics` window. Readouts, collector age (UI items); the stop-the-fleet key as a link to Users until its BACKEND ticket lands (5.1). Oob bar meta only on htmx requests (3.1). Every split route renders both shapes (R23). | The heart of the product. Group `home`, off at deploy: the owner uses it with the cookie for a day on the live fleet, then `home` is added to the setting. | Control census on `/` and `/project/{slug}` over the state matrix (R1). Classic tests unchanged; terminal parameter added to `test_home_layout.py`, `test_fleet_grid_declutter_2026_09_11.py`, `test_mobile_fleet.py`, `test_file_moves.py`, `test_upload_only.py`, `test_admin_tick_for_editor.py`, `test_tab_memory.py` fleet parts, the relevant d-ui tests (hx-target, form fields, polls). New: tick-from-tree returns tree markup in both variants; meta ids once in first paint; no swap hook on a `.win`; the poll-survival Chrome test (R3); sweep. Wave 3: each new-named route answers 404 when `home` is off and never serves classic markup to a cc page; the R15 fetch-map test; an opened missing-files list (`hx-preserve`, 3.3) survives two 10 s beats; the confirm re-dispatch test (3.2); READ THE ANSWER into a folded window unfolds it (3.1); the file-move key is "Move on the server and on every computer" in `cc/partials/project_detail.html` and passes the vocabulary scan with no allow-list entry (R12). Wave 4: the tree carries `as_qs` and `machine` in its context, poll and `view=tree` response, and an admin acting `?as=bob` polls and ticks as bob (5.1); the census pair `/partials/sidebar` to `/partials/projects-tree` with its drop-`as` self-test (R1); a dismiss from `home_problems` posts `?view=home-problems` and gets `home_problems` markup, never `admin-users-box` (5.1, R15); `home_collector` keeps `id="fleet-collector"` and `home_problems` keeps `id="server-notices"`, and every `NOTICE_KINDS` href resolves against a rendered cc home (3.3); `computer_answer`'s "every computer" link targets its own route (1.5); the file-move form keeps its `hx-on::confirm` and hooks, and the account-style inline hooks list is checked (3.2, 3.3); the click-fetched BROWSE forms and the per-role census (R1); the retired-word, retired-phrase and typewriter scans over `templates/cc/**` and `static/cc/**` (R12); the `NEW_NAME_TWINS` poll pins and the glob visibility test (R11). Wave 5: banners and LOST COMPUTERS inside the grid body and the hx-target resolution check with its FORGET self-test (5.1, R1); `missing-{{ e.device_id }}` survives a row added between beats (3.3); the move key wraps at 390 with a long CJK project name (2.2); the `.pc .issues` swipe check (5.1); ticks and tree rows 44 px on a coarse pointer (2.2); the tip Escape, hover and poll tests (3.2). Wave 6: the preserved missing-files div only for rows with a `device_id`, a two-report-only-row project in the state matrix and the id-uniqueness assert over it (3.3); the cc computer row keeps `fleet_headline`'s text and level, and the silent-nothing-ticked computer renders no warn anywhere (5.1); the "online" readout excludes `no_selection` computers and the problems readout agrees with the HUD count (5.1); real checkbox tree rows in `<label>`s and `<details>` groups, with the markup test and the Tab/Space keyboard test (5.1); the IME-safe find box and its composition test (5.1); no "N behind" and no "on since" (5.1); window titles as named headings and named fold buttons (3.2); the phone census visibility run over `/` and `/project/{slug}`, every bar action with a phone home (R1 (11)). | Dashboard, group off. |
| **3. Everyday rest** (group `everyday`) | Transfers (its page and `cc/partials/transfers.html`), project-setup, installer, login, help, account (restyle of group F's classic templates; its sync queue is `partials/person_queue.html` (not `account_*`, the prefix group F's classic partials use, so no future classic file can collide) on `/partials/person-queue`, a new name, because home fetches the classic queue partials, R15). `minted_secret` is NOT here: both pages that include it are group `settings-fleet`, so it ports in phase 4 (R15). `static/cc/copy_value.js` already exists (phase 0), and `pwa.js` is shared, not forked (2.1). | Group off at deploy; previewed, then enabled. | Classic tests unchanged, including `test_pwa.py` `[ INSTALL ]` and d-ui `[ COPIED ]`. Terminal parameter added to `test_cr312`, `test_project_setup.py`, `test_help_page.py`, `test_sweep_2026_09_04_dash_ui.py` copy button, `test_account_page.py` (group F's); terminal twins for the install and copy labels. Wave 4 (D17): census structured moves for the sidebar's toggle POSTs, `/partials/sidebar` poll and `as` GET form from each phase 3 page to `/` (R1); the phone sweep reaches the tree in one tap from every page; the account page's inline `hx-on` hooks kept (3.3); the retired-word scan over the cc account copy ("wired computer", never "wired rig", R12); `person_queue` in the `NEW_NAME_TWINS` map. Wave 5: `static/cc/account.js` (2.1, 3.3); the account buttons post `?view=none` and ask-why and update answer an empty 200 with no `hx-swap-oob` (R15); `person_fix_root` per computer window (phase 2 row); the signed-out classic link on the cc login and the signed-cookie login preview (3.4). | Dashboard, group off. |
| **4. Settings: run the fleet** (group `settings-fleet`) | Site (tabs, AI providers picker and wizard: `static/cc/site_settings.js`, a rewrite of the render half; the classic file frozen), users (frames split out of `admin_users`, `admin_sessions`, `admin_report_tokens`, `fleet_halt`, each route rendering both shapes; swap hooks on `.body`; `minted_secret` ported here with its two includers; the routes are enumerated by the template they render, grepping every `_render(..., "partials/admin_users.html"` and the others across `src/`, which today includes `account_ui.py`'s `POST /partials/admin/users/display-name` as well as the `ui.py` handlers), sync plans (`static/cc/assignments.js`), packages (roll back to… select; `static/cc/dashboard_update.js` with two select-plus-key pairs, `closest()` and `classList`, 5.3; delete wording per 5.3), jobs, history, setup (`static/cc/setup.js`). R24's classic checkbox list for `ui_terminal_groups` lands on the CLASSIC Settings form in phase 0, not here. | Group off at deploy; previewed, then enabled. | Classic tests unchanged. Terminal parameter added to `test_packages.py` (20 literals, exact counts), `test_cr335_packages_page.py`, `test_templates_wave3` `hx-indicator` count, a separate `CC_OWNED_TEMPLATES` poll-count test with its own constant, and twins of `test_mobile_admin.py`'s mobile.css admin rules against `cc/phone.css` in the cc mobile test file (wave 4: `test_mobile_admin.py`'s 17-count and CSS tests themselves stay classic and unparametrised, R11), `test_jobs_retry.py`, `test_fleet_halt.py`, `test_hardening.py`, `test_admin_*`, `test_dashboard_update.py` (plus one test per rollback path), the d-auth `setup_routes` source count, chaos `COSMETIC_DISABLES` ids; the d-ui Chrome harness gets a `cc/site_settings.js` run over terminal fixture markup beside the classic one. Wave 3: the cc Site page serialised exactly as `site_settings.js` does sends only `site_store.KEYS` names (`indexer_model_tier`); the rendered cc Site page has no nested `<form>`, and `#settings-import-form`, `#android-form` and the AI section are siblings of `#settings-form` (1.3, 5.3); the APG tab keyboard test and the tab-activating save refusal (3.2); `.tip-btn` present for every explained key at 390 coarse (3.2). Wave 4: every non-submit `button` in `templates/cc/**` has `type="button"` and folding a Settings window sends no PUT (3.2); a confirmed two-button form sends the pressed button's value (3.2); D17's structured moves for the settings pages (R1). Wave 5: ARCHIVE and the Packages rollbacks keep their native confirms (3.2); the forked `setup.js`/`assignments.js` pass the fragment bracket rule (R12); the minted secret stays visible with every window folded (3.1); Site's active tab and scroll come back after navigating away (3.2); UNARCHIVE and both protection acks are distinct census keys (R1). Wave 6: the "roll back to" select lists only plainly-current-able versions and every held build keeps its folded row with canary line, PUSH TO ONE COMPUTER, the typed override, DELETE and the `error_for` refusal, census entries for push-one, delete and override per held build with no allow-list, and an unsigned version cannot post without the signature confirm (1.3, 5.3); the cc `dashboard_update.js` `HX-Refresh` and 409 tests (3.3); Site's tab store does not corrupt tab_memory's entry (3.2); the `.switch` name and focus tests on Site (2.2). | Dashboard, group off. |
| **5. Settings: is it healthy / when it breaks** (group `settings-health`) | Health (tabs; the collector partial route, BACKEND small, lands here or its tab waits; the diagnostics listing already exists, 1.5), invariants, protection, alerts, recovery. The notices, collector and diagnostics move from home to Health (D7) under 7.0's cross-group rule: they stay in `cc/fleet.html` behind `{% if 'settings-health' not in ui_groups %}` until phase 8, so deploying phase 5 changes nothing on the enabled home (wave 4). Links reach them through `/go/<panel>` (R13), so `db.py`, `notices.py`, `ui.py`, `admin_health.html` and the topbar problems link are variant-neutral and correct for classic viewers too. | Group off at deploy; previewed, then enabled. | Classic tests unchanged. Terminal parameter added to `test_health_page.py`, `test_invariants.py`, `test_protection.py`, `test_notices*.py`, `test_live_notices_2026_09_21.py`, recovery tests; d-diag's panel-name pins REWRITTEN with the copy (R11: l.640-662's `[ COLLECTOR ]` and "under the computers table on SYNC STATUS" become "names the Collector panel, `/go/collector` resolves"; `test_api.py:362/375`); `/go/<panel>` resolves per variant; each R13 anchor lands inside a tab panel its hash selects (3.2). Wave 3: the four `/go` pins REWRITTEN (R11: d-db l.464, d-diag l.596, `test_health_page.py:97`; `test_sweep_2026_09_04_copy.py:293` stays, classic topbar unchanged, with a terminal twin for `/go/notices`); Health's tabs use the new names `partials/health_notices.html`, `health_collector.html`, `health_diagnostics.html` on `/partials/health-notices`, `/partials/health-collector`, `/partials/health-diagnostics` (R15), never the classic `notices`/`collector_health`/`admin_diagnostics` names, which stay classic for classic home; the first-paint and load-triggered anchor scroll tests (3.2). Wave 4: the census and `/go` walk under `{chrome,home}` (home keeps the three panels, `/go/notices` stays `/#server-notices`) and under `{chrome,home,everyday,settings-fleet,settings-health}` (they are on Health and gone from home); a dismiss from `health_notices` returns `health_notices` markup; `health_diagnostics` with no parameters lists the newest bundle per computer (1.5); D17's structured moves for the Health-group pages. Wave 6: Alerts keeps four sibling forms (no nested `<form>`, SET PASSWORD and RUN NOW post to their own routes, a save serialises only `SETTING_KEYS`, 1.3), and the SMTP password form's CLEAR is its own census key (R1 (10)). | Dashboard, group off. |
| **6. Apps** (group `apps`) | `/cards/` landing (`cc/cards_landing.html` + a NEW `static/cc/cards_landing.css` on the cc tokens; the classic `cards_landing.css` and its `test_cards_picker.py` pins untouched until phase 8; `cl-*` hooks kept); b-roll, music, youtube bodies in their own stylesheets and JS (live ids kept; ytdl's 17 labels), every new rule under `html.cc`. The SPAs are static files, so they pick their variant **before first paint**: the first-paint script each `index.html` `<head>` has carried since phase 1 (7.0) also sets `html.cc` when the `ccsync_ui_effective` list holds `apps` on `document.documentElement` (there is no `document.body` in `<head>`); the injected topbar's `data-ui-apps` marker is then AUTHORITATIVE in both directions (7.0; computed from `apps` in the effective set, never constant): it sets or clears `html.cc` and rewrites the cookie, which covers a first visit and a stale cookie after a rollback (one late restyle, and `--header-h` is re-measured by the existing observers). ytdl's script reads the cookie with `split('; ')`, never a regex literal (4.1). **Folds, tips and confirms in the SPAs** (wave 6): the bench gets them from `shell.js` (`foldable()`, `tooltips()`, `shell.js:214-247`; the SPA bench pages draw 3, 5 and 10 `.win` windows), and `static/cc/cc.js` is dashboard-only while the injected HUD is script-free, so phase 6 adds a small SPA helper (fold with a per-path store, tip on tap, confirm dialog as in 3.2), byte-identical in each SPA's static dir with an identity test like hud-common's, no root-relative URLs (ytdl `_ABSOLUTE`) and no em dash. | The body variant follows the `apps` group through the cookie. | Each SPA's `test_theme_css.py`, `test_mounted_prefix.py`, em-dash scans, w2 contrast pins, ytdl `test_static_app.py` (28 literals, kept for classic, twins for terminal), music `test_ui_says_what_it_knows.py`; `test_cards_picker.py` unchanged plus a terminal twin, d-cards; the b-roll share-page rule snapshot (R22); a test per SPA that the first script sets `html.cc` from the cookie; the three marker tests of 7.0 (`chrome` on and `apps` off gives `classic` and removes the class; `chrome` off removes it; `apps` on sets it); ytdl's `test_mounted_prefix.py` over the restyled `style.css` and index (the data-URI slash rule, 2.1); the retired-word scan over the cc cards landing and any `static/cc/` JS (R12, wave 4). Sweep adds the three SPAs, `/cards/` and the share page. Wave 6: the SPA census (R1 (12)): `census_click.js` on `/broll/`, `/music/`, `/ytdl/` with `html.cc` off and on, diffed with a structured allow-list, the per-SPA required-id list (retry-failed included) and `/cards/` in the static census; the SPA helper's identity test across the three copies, every SPA `.win` bar folds and keeps its state across a reload, a tip opens on tap, and the helper passes each SPA's mounted-prefix and em-dash scans. | Dashboard (SPAs ride), group off. |
| **7. Copy sweep** | Every Python and JS string in 2.6 to the D8 convention; the `NOTICE_KINDS` labels as plain text drawn per variant (2.6); `HOW_IT_WORKS.md` and `EDITOR_SETUP.md` (shipped in the image, rendered at `/help` for BOTH populations from one file): brackets to D8, and the page-map rows (`HOW_IT_WORKS.md` l.476-481, 500, 565: "the front page ... The sidebar ticks are here", "Settings > Users ... the switch that stops syncing") rewritten to name destinations only ("Settings > Health", "the projects list"), never a region or a sidebar, and where a location truly differs between the variants the sentence names both; the full layout rewrite of both docs moves to phase 8, and both docs join the R13 page-region check (wave 3); the file-move label becomes "Move on the server and on every computer" in `notices.py`, `alerts.py` and `docs/FILE_MOVES.md` (R12); `tools/publish_latest.py`; the Python allow-list of the bracket scan reaches zero; retired-phrase bans updated. The new wording is **variant-neutral** (`press "Resume"` reads correctly next to a classic `[ RESUME ]` key too), because classic is still served to every flag-off customer; no sentence names a page region (R13). Also the product defects the bench builders found (recovery "no button for this yet", doubled "(optional)", fix texts naming bracketed buttons, em dashes in legal titles; the legal title change must NOT bump the EULA version marker unless the owner means to). | Pure copy. Email and webhook readers see the new wording next report. | The bracket scan (R12 scope) at zero for Python and `cc/`; the Python-copy pins REWRITTEN in this phase (R11): d-diag `_labels()` to D8 quoted labels checked against both variants, d-diag l.1311-1317, `test_notices_sweep_wave2.py:261-263`; `test_report_endpoint.py`; `tools/tests/test_publish_latest.py`; alerts tests; `test_cards_picker.py` for `cards_pool.py`'s copy. Wave 6: also `test_protection.py:547` (`"[ SEND A TEST ]" in line.fix`), `test_alerts.py:791` (`[ FORGET ]`) and `:900` (`[ TRY AGAIN ]`), `test_cards_pool.py` if its asserts follow `cards_pool.py`'s copy, and a grep step over `dashboard/tests` for `\[ [A-Z]` asserts against `.fix`, `.diagnosis`, `detail` or `_code(<module>)` of every module in 2.6; each hit becomes a D8-label assert (the quoted label is present and matches a key in both variants), as for d-diag `_labels()`. | Dashboard. |
| **8. Default and delete** | Two steps (wave 3). **8a**: all groups default on in the vendor build, plus a notice (or a one-time migration) naming every site whose stored `ui_terminal_groups` row overrides the default, since a stored row (`none`, or a set) beats the vendor default for good (R24); such a site returns to the default through the row-delete path. **The soak is enforced by 8a, not 8b** (wave 4: `dashboard_update.preflight` reads no site state, the refusal must live in the RUNNING code, and an image-mode update from the NAS app manager runs no preflight at all). 8a writes `meta.ui_terminal_default_since` the first time the resolved set is every group, and clears it when the set changes; 8a's `preflight` refuses a feed record carrying a signed `requires_ui_soak_days` field while that meta is missing or younger, naming the date the soak ends (`publish_feed`/`sign_release` gain the field; tests with and without the meta). Image mode cannot be refused, so **8b must boot safely on an unsoaked site**, including one with a stored `none` row: it logs a notice naming the forced switch rather than assuming a soak happened (test: 8b boots with a stored `none` row), and the vendor image for 8b is not published until the feed-mode soak data supports it. After the soak, 8b deletes classic templates, the classic copies of the forked scripts, `style.css`/`mobile.css` (theme-common's reference entry in all four `test_theme_css.py` moves to `static/cc/terminal.css` in the same commit; theme-common's scrollbar rules become the site-style bar, D6), the classic drawer block and its pins in all four sheets, the classic `cards_landing.css`; move `cc/` up; remove the loader, setting, header, `/go` indirection if unneeded, and cookie route; `/offline` on the terminal shell; `sw.js` PRECACHE drops classic assets; delete the classic CSS-fact tests and classic pins; `docs/mobile/` screenshots regenerated. `HOW_IT_WORKS.md`/`EDITOR_SETUP.md` layout rewrite (moved here from phase 7). The generation token and its reload line stay (R23). The SPAs: either the topbar partial keeps emitting `data-ui-apps` (from then on always `cc`, since classic is gone) and the `ccsync_ui_effective` cookie for good, or the SPA sheets and JS drop their classic halves in the same commit (b-roll only under R22's share-page rule). | Irreversible except by the dashboard rollback. | Full gate, full sweep; the bracket scan at zero over the whole tree; the theme-common identity tests green against the moved reference. | Dashboard. |

### 7.2 Deploy order and compatibility

- Only the dashboard image (or bundle) changes, in every phase. The SPAs are
  inside it. **Phase 0 ships as a new IMAGE** (wave 6, R23's header floor),
  to this studio and later to the vendor feed, so every automatic fallback
  (`select_code_root.py` booting the image, the watchdog, the Packages
  image rollback) lands on a build that parses `X-CC-UI`; phases 1-8 may
  ride bundles, each carrying `min_image_version` = `HEADER_FLOOR`. There is no wire change and no schema change in any port
  phase, so the "dashboard before companions" rule is not engaged.
- **The BACKEND tickets** in section 5 are separate changes with their own
  versions. Any that need companion data (per-lane percent) follow the usual
  order: dashboard first, then companions, and the UI shows the older
  state-only meter for a companion that does not send it.
- Cards (MulticamPipeline) is not deployed by any phase.
- The vendor feed (`publish_latest.py`) carries the `ui_terminal_groups`
  default: empty until phase 8 in the vendor build, so customer dashboards
  stay classic unless an admin opts in. D14 decides whether other customers
  get a preview.
- No deploy turns a group on. Enabling a group is a separate, reversible
  site-setting change made after the owner's cookie preview (7.1, R24).

---

## 8. Effort and the owner's decisions

### 8.1 Effort (builder-days, one Opus builder per day of focused work, tests included; the central gate and the owner's review are extra)

| Phase | Effort | Notes |
|---|---|---|
| 0 Foundations | 2-3 | CSS merge and dedup is most of it; the overlay loader is small but needs care (globals parity). |
| 1 Chrome | 3-4 | Four-sheet block (`cc/hud.css` + three SPAs), four suites of CSS tests, SPA screenshots, 768. |
| 2 Home and project | 5-7 | Frame/body split of `fleet_grid.html` (529 lines) and `project_detail.html` (343); homes for every dropped control; the census. |
| 3 Everyday rest | 2-3 | Includes the account page restyle. |
| 4 Run the fleet | 5-7 | `admin_packages.html` (639) and `site_settings.js` (894) dominate. |
| 5 Healthy / breaks | 3-4 | Panel moves between pages. |
| 6 Apps | 5-8 | Three SPAs + Cards landing; ytdl app.js is 3,000+ lines; the shared SPA fold/tip/confirm helper and the SPA census (wave 6). |
| 7 Copy sweep | 2-3 | Alerts copy is emailed: review sentence by sentence. |
| 8 Default and delete | 1-2 | Plus the soak. |
| **Total** | **28-41** | The BACKEND tickets (section 5) are not in these numbers: user page 3-5, UPDATE ALL 4-6 (with its own design review), check now 1, dismiss all 1, the small view fields 1-2 together, collector route 0.5, who_answers 0.5. |

### 8.2 Decisions for the owner (each with a recommended default)

| # | Decision | Recommended default |
|---|---|---|
| D1 | A light theme? There is no theme toggle today; the product is dark only (`color-scheme: dark`). | **No.** Dark only, as today and as the bench. |
| D2 | Self-host the fonts (adds about 150-250 KB of woff2 to the image and the offline cache) or keep the system mono? | **Self-host** JetBrains Mono + Orbitron, OFL, subset; drop Space Mono. |
| D3 | Module links back in the bar (the bench) against the 2026-08-18 "drawer only" rule the tests pin. | **The bench**: `>word` nav in the HUD on desktop, a dock plus a "more" drawer on phones. |
| D4 | The HUD clock. | **Drop it.** It needs script (dead in the SPAs) and hard-codes Taipei. |
| D5 | The shipped values of TUNE's knobs (live colour, grain, scanlines, glow, DOS shadow, text size, density) and the crosshair. | Paste the output of TUNE's **copy settings** on the bench into the phase 0 ticket. Without it: cyan, grain 0.05, scan 0.05, glow on, shadow on, 14 px, normal, crosshair on (the bench defaults), grain paused when hidden. |
| D6 | Scrollbars: the site's thin deep-red thumb with no track (the owner's ask), which fails the 3:1 non-text guideline (2.1:1) and changes the pinned `theme-common` values in four suites. | **The site's look, with the thumb one step brighter** (`--red` on hover as now, a resting thumb near 3:1). Change it in theme-common so every app moves at once; this reaches the b-roll client share page, so it is R22's one listed exception (an explicit snapshot update), or the share page first gets its own theme-common copy. |
| D7 | The information architecture moves: notices, collector and diagnostics from home to Health; project roots from home to the project page; the project cards overview dropped from home. | **Yes to all three moves**, with the home problems window still showing the open notices (it is the home page's first question). **Keep** a compact project overview on home unless the owner says drop it. |
| D8 | How copy names a control once brackets go, including emails. | `press "Resume"`: sentence-case label in double quotes, everywhere. The weekly protection email's state words become `PROTECTED:` style prefixes. |
| D9 | The Timeline Cards page (`/cards/p/<slug>/`, other repo) in the terminal look? | **Not in this port.** A separate plan in MulticamPipeline after phase 6. |
| D10 | The client share page (public, customer-facing). | **Leave it.** Clients are not in the terminal. |
| D11 | Which issue variant (log, tree, matrix, counts, bar, ticker, tags). | **log** (the bench default; one line per issue, reads at a glance, copies as text). |
| D12 | The companion tray keeps `[ BRACKETS ]` (Tk `theme.py`) while the dashboard drops them. | **Accept for now**; the release note says so. A tray restyle is a separate ask. |
| D13 | Soak before deleting classic (phase 8). | **Two weeks** with every group on for this studio. |
| D14 | Other customers' dashboards: classic until phase 8, or opt-in earlier? | **Classic until phase 8** (`ui_terminal_groups` empty in the vendor build). |
| D15 | BACKEND items: which to build, and when. | Build **user page** and **UPDATE ALL** (each with its own spec and review) after phases 2 and 4 respectively. **Check now** and **dismiss all** only if the owner wants them. Per-lane percent waits on companion data; ship the state-only meter. |
| D16 | Packages delete wording. | Both routes already trash for 30 days (verified). **Say so in the confirm**; no behaviour change. |
| D17 | Where the project tree and TICKING FOR live on terminal pages (wave 4). The classic sidebar is on 17 pages; the bench draws the tree only on home and project. | **Home and project only**, as the bench: other cc pages drop it, the census records the moves to `/` (R1), and the dock's sync link reaches it in one tap on phones. The alternative, the tree as shell furniture in group `chrome` with its own route so any cc page can carry it, costs a `chrome`-group tree partial and poll on every page; choose it only if the owner wants ticking from Settings pages. |

---

## Appendix A: the numbers behind this plan

- Bench: 28 pages, 12,087 lines including sheets; `cc-terminal.css` 532,
  `cc-components.css` 237, `css/*.css` 1,725, `shell.js` 280.
- Live: 22 page templates, 38 partials, 13 static scripts, `style.css` 2,093,
  `mobile.css` 393, `ui.py` about 4,900.
- Bracket strings: templates, the bulk; Python UI copy 66 literals + 1
  f-string (+ 102 docstrings and 153 comments, which do not change); JS 21 +
  3 + 3 + 1 + 1 in the dashboard, 17 in ytdl; tests 328 in dashboard, 29 in
  ytdl, 2 in music, 2 in tools; docs 355 in 50 files.
- Polls on home: 2 s, 10 s, 15 s, 30 s (sidebar, roots, stamp), 60 s
  (notices, plan changes, halt banner).
- Contrast on `#070403`: muted 5.45, text-2 11.25, red 5.53, red-deep 2.12,
  warn 11.19, ok 15.29, hi 13.28; white on red 3.70.

---

## Adversarial review log

Each wave's findings, verified against the code by the reviser before the
plan was changed. ACCEPTED means the plan was revised; REJECTED says why.

### Wave 1 (2026-09-25)

Four critic lenses (behaviour, embedded apps, tests and gate, rollout and
rollback). Several findings were raised by more than one lens; each is
listed once per lens as raised.

| # | Lens | Finding | Verdict | Why / where fixed |
|---|---|---|---|---|
| 1 | behaviour | One flag plus an OR cookie cannot gate phases 2-6 | ACCEPTED | 7.0 now gates per page group (`ui_terminal_groups`, `TEMPLATE_GROUPS`, custom loader) with a three-way cookie that beats the setting; 7.1 deploys every group off. |
| 2 | behaviour | Existing tests render only classic, so the tripwire never trips | ACCEPTED | Verified (`ui.templates.env`, `TEMPLATES / ...` reads, non-recursive globs, cookieless TestClient). R4, R11 and phase 0 add the `ui_variant` fixture, `DASH_UI_VARIANT`, a path resolver and `run_all_tests -Variant both`; classic pins stay until phase 8. |
| 3 | behaviour | Phase 1 removes the drawer CSS the classic topbar needs; `.nav-drawer` reused | ACCEPTED | 4.1: hud-common is added beside the drawer block, deleted only in phase 8; the HUD uses `#hud-more`/`.hud-*` names (3.4). |
| 4 | behaviour | The tick route returns the classic sidebar or queue into the new tree; no machine in `_sidebar_context` | ACCEPTED | Verified (`view=sidebar`, hx-target substring match, `my_queue` fallthrough, `fetch_selections` without machine). 5.1 retags the computer picker BACKEND (small) with a `view=tree` branch and `machine` carried; phase 2 adds the both-variants test. |
| 5 | behaviour | Chip sheet on any `[title]` blocks `<summary title>` and adds tabindex everywhere | ACCEPTED | Verified (`target()` exemption list, `preventDefault`, `bins.html:28`). 3.2 keeps an explicit selector, exempts `summary`, adds a Chrome test. |
| 6 | behaviour | Home Stop the fleet needs a reason and answers with the Users panel | ACCEPTED | Verified (3-char reason refusal, `fleet_halt.html` root). 5.1 retags it BACKEND (small): dialog with reason, compact response or `HX-Trigger`; a link to Users until then. |
| 7 | behaviour | READ THE ANSWER targets `#fleet-diagnostics`, which moves to Health | ACCEPTED | Verified. Home keeps an empty `#fleet-diagnostics` window (1.5, 5.1); Health needs a listing route (5.3); added to R2's hook list. |
| 8 | behaviour | Moved-panel anchors are shared Python; `href_label` is not stored | ACCEPTED | Verified (`NOTICE_KINDS` hrefs, `ui.py` detail_page, `notice_href` computes the label). R13 rewritten around `/go/<panel>`; 2.6 corrected; the display filter dropped. |
| 9 | behaviour | Swap-target classes on the `.win` conflict with the static frame | ACCEPTED | 3.1 rule: every swap hook on `.body` or a child; R4 rewritten; a test per page. |
| 10 | behaviour | Oob bar meta in an also-included partial duplicates the id | ACCEPTED | 3.1: oob fragments only when `HX-Request` is present; first-paint test for single ids. |
| 11 | behaviour | The dashboard rollback select cannot be fixed with `closest()` | ACCEPTED | Verified (two flows, attributes read from `evt.target`). 3.3 and 5.3: two select-plus-key pairs, a `cc/` script copy, a test per path. |
| 12 | behaviour | The phone dock collides with the stale banner and chip sheet | ACCEPTED | Verified (`bottom: 0`, z 60 / 70). 2.2 adds `--cc-dock-h` lifts outside hud-common; R6 widened; sweep occlusion check. |
| 13 | behaviour | `test_static_js_syntax` does not check `static/cc/cc.js` | ACCEPTED | Verified (`STATIC.glob("*.js")`). Phase 0 switches to `rglob`; R2 says so. |
| 14 | behaviour | The census cannot see conditional or JS-built controls | ACCEPTED | R1 now specifies a state-matrix fixture and a per-script URL list plus a click-through pass. |
| 15 | embedded-apps | R22 wrong: the share page loads b-roll's `style.css` | ACCEPTED | Verified (`share.html` links, `SHARE_ASSETS`). R22 rewritten with a scoping rule, an unscoped-rule snapshot test and the share page in the sweep; 1.4 and 4.3 note it. |
| 16 | embedded-apps | Phase 1 removes the drawer CSS; class-name collision | ACCEPTED | Same fix as 3. |
| 17 | embedded-apps | The HUD lands in a `.topbar` flex host (`.topbar > *` nowrap) | ACCEPTED | Verified (`base.html` header, SPA `#dash-topbar.topbar`, the pinned rule). 3.4: `base.html` uses a bare host when the HUD is served; hud-common resets `#dash-topbar:has(> .hud)`; tests in each suite. |
| 18 | embedded-apps | The b-roll `@font-face` path 404s | ACCEPTED | Verified (`static/style.css` under b-roll's own mount). 4.2: `../../static/fonts/` for b-roll, a GET test per SPA. |
| 19 | embedded-apps | R16 is not impossible: unversioned SPA assets | ACCEPTED (narrowed) | b-roll is exposed (`StaticFiles`, `Last-Modified`); music and ytdl serve `Response(read_text)` with no validators, so they are not heuristically cached. R16 rewritten; b-roll's index gets hashed links or no-cache in phase 1; music/ytdl get a pin. |
| 20 | embedded-apps | theme-common left out of the terminal sheets; phase 8 deletes the reference file | ACCEPTED | 2.1: theme-common byte-identical in `cc/terminal.css`, a fifth `FLEET_STYLESHEETS` entry; phase 8 moves the reference in the same commit. |
| 21 | embedded-apps | HUD markup uses classes outside hud-common | ACCEPTED | 3.4: every HUD class `hud-` prefixed or scoped; a class-coverage test. |
| 22 | embedded-apps | Phase 6 restyles `cards_landing.css` in place under the classic landing | ACCEPTED | Verified (classic tokens `--amber`, `--green`, `--red-dim`, `--panel`, `--tap` absent from the cc root). New `static/cc/cards_landing.css` (1.4, phase 6). |
| 23 | embedded-apps | The SPA `data-ui` marker flashes classic and has no phase 8 story | ACCEPTED | 7.0 sets a readable `ccsync_ui_effective` cookie; phase 6 picks `body.cc` before first paint with the marker as fallback; phase 8 states both endings. |
| 24 | embedded-apps | The phone dock covers classic pages and SPAs from phase 1 | ACCEPTED | Same fix as 12, plus the sweep's occlusion check. |
| 25 | tests-and-gate | No test renders the terminal variant, so phases 2-6 are ungated | ACCEPTED | Same fix as 2; also `OWNED_TEMPLATES` and d-ui's glob extended to `templates/cc/`. |
| 26 | tests-and-gate | Phase 1 rewrites SPA drawer CSS and classic topbar pins | ACCEPTED | Same fix as 3; `test_topbar_partial.py` keeps its classic asserts and gains a terminal twin. |
| 27 | tests-and-gate | Static JS is shared, so phase 3/4 rewrites change classic pages | ACCEPTED | 2.1 JS rule: forked output goes to `static/cc/`; shared scripts branch on `<html data-ui>`; classic JS pins kept. |
| 28 | tests-and-gate | `test_static_js_syntax` misses `cc/cc.js` | ACCEPTED | Same as 13. |
| 29 | tests-and-gate | Terminal pages lose theme-common; identity tests never see it | ACCEPTED | Same as 20. |
| 30 | tests-and-gate | hud-common in classic `style.css` breaks the exactly-once and after-theme-common query pins | ACCEPTED | Verified (`test_mobile_css.py` three-query count and theme-common tail check). 2.2: hud-common placed before the phone layer, the three pins amended to count outside hud-common, the HUD breakpoint agrees with 600 while classic bodies exist. |
| 31 | tests-and-gate | The dock lands on the classic projects-sheet handle | ACCEPTED | Verified (`.btn.sheet-handle` fixed at bottom, z 40). Lifted by `--cc-dock-h` (2.2, R6). |
| 32 | tests-and-gate | The census is blind to JS-built and conditional controls; route-only compare | ACCEPTED | Same as 14, plus (method, route, field names) comparison. |
| 33 | tests-and-gate | `?v=` breaks classic PWA contract pins and offline precache | ACCEPTED | 2.5 and R8: classic `base.html` untouched; `cc/` uses `asset_url()`; an `/offline`-in-PRECACHE test. |
| 34 | tests-and-gate | The box-drawing ban conflicts with the bench's text window bars | ACCEPTED | 2.1: bar corners and tree branches drawn by CSS; the `cc/` CSS-fact file pins the ban. |
| 35 | tests-and-gate | The bracket scan cannot reach zero in phase 7; regex misses interpolation and CSS | ACCEPTED | R12 scope and pattern rewritten; whole-tree zero moved to phase 8; phase 7 copy is variant-neutral. |
| 36 | tests-and-gate | The b-roll font URL resolves inside b-roll's static dir | ACCEPTED | Same as 18. |
| 37 | tests-and-gate | `ui_terminal` must not join the published features block | ACCEPTED | Verified (`test_site.py` pins the set). 7.0: `ui_terminal_groups` is a dashboard-only site setting, never in `/api/v1/site`. |
| 38 | rollout | One on/off flag cannot stage the rollout | ACCEPTED | Same as 1. |
| 39 | rollout | Removing the SPA drawer block breaks flag-off SPAs | ACCEPTED | Same as 3. |
| 40 | rollout | Open pages get partials in the other variant after a flip | ACCEPTED | New R23: `X-CC-UI` header from the page decides partials; split routes render both shapes; an `X-CC-UI-Want` mismatch shows a reload line. |
| 41 | rollout | No reliable way to switch off; plumbing missing | ACCEPTED | Verified (`FEATURE_SETTINGS_ATTRS` hand list, DB row beats env, the only toggle is the Settings form). 7.0 plumbing list; new R24 (tool, classic checkbox list, per-browser escape; env is not a rollback). |
| 42 | rollout | `?v=` on classic `base.html` breaks the precached offline page | ACCEPTED | Same as 33. |
| 43 | rollout | `?v={{ VERSION }}` fails on same-version redeploys; b-roll sheet uncached | ACCEPTED | 2.5: content hash via `asset_url()`; R16 for b-roll. |
| 44 | rollout | The b-roll `@font-face` path is wrong | ACCEPTED | Same as 18. |
| 45 | rollout | The HUD inside classic `.topbar`; dock collides with classic fixed-bottom UI | ACCEPTED | Same as 17 and 12 (`.toast-host` included). |
| 46 | rollout | Phase 5/7 notice links and copy break for the classic population | ACCEPTED | Same as 8: `/go/<panel>`, variant-neutral copy, R13 corrected (`fix`/`body` stored, label computed). The finding text was truncated in the hand-off; its visible part was verified and acted on. |

### Wave 2 (2026-09-25)

Four lenses again, against the wave 1 revision. Every finding below was
checked against the tree before the plan changed (`ui.py:64`, htmx
1.9.12's `issueAjaxRequest`, `htmx_errors.js` `busy()`, `site_settings.js`
852-869, `site_store.set_many`, the include map, `test_mobile_css.py`'s
`_block`, the theme-common block, `settings.py`'s frozen dataclass,
`ci.yml`, `sw.js` PRECACHE, the SPA sheets, `mimetypes` on the base rig).
No finding was rejected; duplicates across lenses are marked.

| # | Lens | Finding | Verdict | Why / where fixed |
|---|---|---|---|---|
| 47 | behaviour | A per-request loader breaks Jinja's template cache | ACCEPTED | Verified (one `Jinja2Templates`, cache keyed by loader and name). 7.0: one memoised environment per group set with a fixed filter; alternating-render, two-thread and setting-flip tests. |
| 48 | behaviour | A dialog confirm in a polled body drops the action when a poll replaces its source | ACCEPTED | Verified (`if(!se(n)){ie(o);return l}`; `busy()` checks only inside the root). 3.2 "Confirms": one page-level dialog, every poll held while open, re-find by `data-confirm-key` or refuse visibly, Chrome test. |
| 49 | behaviour | The HUD's stamp poll swaps classic stamp markup into the HUD | ACCEPTED | Verified (`topbar.html:211-214`). R23: the header carries the page's group set; 3.4 test. |
| 50 | behaviour | `chip_sheet` in chrome breaks block 2's hooks and has no CSS on classic pages | ACCEPTED | Verified (`.chip-sheet-label`/`.chip-sheet-text` set by `htmx_errors.js`). The sheet and the halt banner leave the chrome overlays and become new-named cc shell furniture (R15, 2.5); 3.3 block 2 row; the tip selector applies regardless of `data-ui` (3.2). |
| 51 | behaviour | `partials/transfers.html` and `minted_secret.html` cross phase groups | ACCEPTED | Verified (`fleet.html:60`, `transfers.html:19`; `admin_users.html:5`, `admin_report_tokens.html:13`). Phase 2 ports `cc/partials/home_transfers.html`; `minted_secret` moves to phase 4; R15 records the include-map check. |
| 52 | behaviour | R24's checkbox list makes every classic Settings save fail | ACCEPTED | Verified (checkbox serialised as "1"/"0", `set_many` validates first). R24: a separate `#ui-groups-form` with a CSV value; the general save never carries the key; save tests. |
| 53 | behaviour | Tabs break deep links emitted by shared Python | ACCEPTED | Verified (`db.py:3635`, `recovery.py:939/955/984`, `admin_settings.html:155`). 3.2 tab activation on load and hashchange; R13 table extended to every anchor; a test per anchor. |
| 54 | behaviour | `X-CC-UI-Want` has no correct answer per group | ACCEPTED | R23: Want computed from `HX-Current-URL`'s route group plus `chrome`, sent only on a difference; four case tests. |
| 55 | behaviour | Window ids collide with swap-target ids | ACCEPTED | 3.1 and 3.3: `id="win-<data-win>"`, never a hook or anchor id; unique-id test over first paint and one response per target. |
| 56 | behaviour | 2.5 loads classic `pwa.js` and `copy_value.js` while 2.1 forks them | ACCEPTED | 2.5 script list corrected: `cc/copy_value.js` (forked in phase 0), `pwa.js` shared with a slot branch (2.1); a test that `cc/shell.html` never loads `/static/copy_value.js`. |
| 57 | behaviour | `dashboard_update.js`'s own fetch bypasses `X-CC-UI` and would insert oob raw | ACCEPTED | Verified (`dashboard_update.js:60`, `:77`). 3.3 row plus a general rule for any JS partial fetch; 3.1: no oob fragments in that partial, pinned. |
| 58 | embedded-apps | hud-common rides the unversioned classic `style.css` | ACCEPTED | Verified (`base.html` unversioned link, `sw.js` stale-while-revalidate). 2.2: hud-common lives in `static/cc/hud.css`, linked by hash; classic `style.css` untouched, so the `test_mobile_css.py` carve-out is dropped. |
| 59 | embedded-apps | Hashed font precache entries never match; R9 wrong once chrome is on | ACCEPTED | Verified (`caches.match(req)` without `ignoreSearch`; `offline.html` extends `base.html`). 2.3: fonts at plain URLs; the 2.5 test resolves `url()`s; R9 rewritten (HUD sheet and fonts precached from phase 1). |
| 60 | embedded-apps | `--cc-dock-h` cannot reach what it lifts; `--safe-b` absent in SPA sheets | ACCEPTED | Verified (zero `--safe-b`/`--tap` in the three SPA sheets). 2.2: `--cc-dock-h` declared on `body:has(.hud-dock)` outside hud-common; `env()` inside it; token-declaration test. |
| 61 | embedded-apps | R6's SPA bars are wrong; the dock is trapped in `#app-header`'s z 10 | ACCEPTED | Verified (music's player is inline, `style.css:710`; `#app-header` sticky z 10 in b-roll and ytdl, static below 900 px in music). R6 lists the real elements and records the decision (SPA overlays may cover the dock; SPA toasts and panels are lifted); sweep with toasts and panels. |
| 62 | embedded-apps | A binary `X-CC-UI` cannot describe a classic body under the HUD | ACCEPTED | Duplicate of 49. |
| 63 | embedded-apps | `ccsync_ui_effective` goes stale for an SPA opened directly | ACCEPTED | 7.0: also set on `/partials/topbar` and the gate's SPA pass-through, with `Path=/`; the injected marker is authoritative both ways; a test per SPA. |
| 64 | embedded-apps | D6 contradicts R22 | ACCEPTED | R22 lists D6 as its one allowed exception (explicit snapshot update), or the share page gets its own copy first; the D6 row says so. |
| 65 | embedded-apps | No `.woff2` MIME type in Python 3.12 | ACCEPTED | Verified (`guess_type` returns `(None, None)` in the dashboard venv). 2.3 and 4.2: `mimetypes.add_type` in phase 0. |
| 66 | embedded-apps | `popovertarget` on a link does nothing | ACCEPTED | 3.4: user link plus a separate menu button; phase 1 test. |
| 67 | embedded-apps | The Cards landing has 16 brackets, not none | ACCEPTED | Verified (count 16). 1.4 corrected; phase 6 twins; `cards_pool.py` copy in phase 7. |
| 68 | embedded-apps | ytdl's scan also rejects comments and regex literals | ACCEPTED | Verified (`_ABSOLUTE` over raw text and the served index). 4.1 rule restated for the whole block, comments included; the SPA first script avoids regex literals. |
| 69 | tests-and-gate | `-Variant both` / `DASH_UI_VARIANT` is not a gate | ACCEPTED | Verified (frozen `Settings`, env read only in `from_env()`; one dashboard pytest run in `ci.yml`). Dropped; explicit parametrised tests plus a coverage meta-test (R11, 7.1, phase 0). |
| 70 | tests-and-gate | Per-request loader defeated by the template cache | ACCEPTED | Duplicate of 47. |
| 71 | tests-and-gate | Binary header flips chrome partials to classic | ACCEPTED | Duplicate of 49 (the halt banner is now shell furniture, per 50). |
| 72 | tests-and-gate | hud-common before the phone layer hijacks `PHONE_BLOCK` and friends | ACCEPTED | Verified (`_block` uses `css.index`, the first occurrence; `test_theme_css.py:134-136`). Resolved by 58 (classic `style.css` untouched); 2.2 carries the same rule for SPA tests that slice from a first occurrence (`test_bug_hunt_2026_09_24_w2_broll.py:1000`). |
| 73 | tests-and-gate | The census reads first paint; many controls arrive through `load` triggers | ACCEPTED | Verified (`fleet.html:22/36`, `admin_users.html:25/30/35`, `admin_packages.html:22`). R1 follows load triggers with the page's headers; self-test. |
| 74 | tests-and-gate | The click-through records nothing for confirm-guarded controls | ACCEPTED | R1: `window.confirm` stubbed, `htmx:confirm` confirmed, `[data-dialog-ok]` pressed; self-test on sign-out and package delete. |
| 75 | tests-and-gate | theme-common holds no field paint and reads `--red-dim`, which the cc root lacks | ACCEPTED | Verified (the block holds range, scrollbar, selection and focus only; `--red-dim` read 3 times, absent from `cc-terminal.css`). 2.1 corrected; field paint into `components.css`; token-declaration test and three terminal twins. |
| 76 | tests-and-gate | Phase 7 must rewrite classic pins on Python copy | ACCEPTED | Verified (`_labels()` at d-diag l.572 and the pins listed). R11 amended: Python-copy pins are rewritten in the phase that changes the copy; phases 5 and 7 list them. |
| 77 | tests-and-gate | Parametrising the table-stacking pins passes on nothing or causes the `.stack` collision | ACCEPTED | Verified (`test_mobile_admin.py:247`, `cc-components.css:59`). R11: terminal twins in terminal vocabulary; 2.1 bans bare `stack`/`rule`/`editors` in `cc/`; per-variant poll count. |
| 78 | tests-and-gate | Retired-phrase bans are case-sensitive and bracketed, and updated too late | ACCEPTED | Verified (`test_sweep_2026_09_04_copy.py:105/110`). R12: case-insensitive unbracketed twins for `cc/` in phase 0. |
| 79 | tests-and-gate | The `/offline` precache test fails on day one; chrome puts the HUD in `/offline` | ACCEPTED | Verified (five `base.html` assets absent from `sw.js` PRECACHE). 2.5: subresources only, five-entry allow-list; R9 and phase 1 add chrome-on twins. |
| 80 | tests-and-gate | Chrome partials other than the topbar are unstyled on classic pages | ACCEPTED | Same fix as 50: only topbar, settings_nav and stamp are overlays, all HUD-owned. |
| 81 | tests-and-gate | The d-ui Chrome harness cannot run the terminal variant | ACCEPTED | Verified (`_inline_base_script()` from classic `base.html`). R3 and phase 0: `_run_page(variant)`. |
| 82 | tests-and-gate | pwa.js/copy_value.js contradiction; a `[ INSTALL ]` chip lands in the HUD | ACCEPTED | Same fix as 56, plus the `pwa.js` HUD-slot branch (2.1, 3.3) with a test per slot. |
| 83 | tests-and-gate | A Users-panel route lives in `account_ui.py` | ACCEPTED | Verified (`account_ui.py:506`). Phase 4 enumerates split routes by the template they render, across `src/`. |
| 84 | tests-and-gate | Bench `content: "//"` fails ytdl's scan | ACCEPTED | Verified (also `css/fleet.css:312`). 2.1: `\2f\2f` in the dedup plus a CSS-fact assert. |
| 85 | rollout | Per-request loader and the template cache | ACCEPTED | Duplicate of 47. |
| 86 | rollout | A one-value header cannot describe a classic body under the HUD | ACCEPTED | Duplicate of 49. |
| 87 | rollout | The rollback checkbox list breaks Settings saves; a stale tab re-enables a rolled-back group | ACCEPTED | Same fix as 52, which also covers the stale-tab re-enable (the general save never carries the key) and records group changes in `site_history`. |
| 88 | rollout | hud-common rides stale-while-revalidate `style.css` | ACCEPTED | Duplicate of 58. |
| 89 | rollout | From phase 1 `pwa.js` puts a classic `[ INSTALL ]` chip into the HUD | ACCEPTED | Duplicate of 82. The finding text was truncated in the hand-off; its visible part was verified (`pwa.js:91-96`) and acted on. |

### Wave 3 (2026-09-25)

Five lenses: the four of waves 1 and 2 plus mobile, accessibility and i18n.
Every finding was checked against the tree before the plan changed
(Starlette `templating.py:95-97`, htmx 1.9.12's `htmx:confirm` dispatch,
`ui.py:707/717`, `project_detail.html:82/337`, `admin_settings.html`
78-244, `android_settings.html:27`, `design/site.html`, `site_store.py`
`validate`/`pick`/`manifest_for_app`, `setup_routes.py` PUT and undo,
base.html's scroller, `topbar.html:40`, the bench sheets run through ytdl's
`_ABSOLUTE`, the SPA `test_theme_css.py` popover pins,
`broll/web/tests/test_mounted_prefix.py:100`, `app.py:1290`, the four `/go`
pins, `test_sweep_2026_09_04_copy.py` allow-lists and `RETIRED_IN_TEMPLATES`,
`test_mobile_admin.py` `OWNED_TEMPLATES`, `ci.yml`, `test_static_js_syntax.py`,
`style.css:849`, `broll/web/app/main.py:105`, `HOW_IT_WORKS.md:476-481`,
`manifest.webmanifest`, the result banners, the bench tabs, keys and
`.win.collapsed`). None was rejected. The mobile/a11y/i18n lens noted that
the wave 1 log carries no rows for that lens and its defects were still in
the plan text; the reviser has no record of the wave 1 wording, so those
defects are logged here (rows 124-129) with their fixes rather than
back-filled into the wave 1 table. The last finding's text was truncated in
the hand-off; its visible part was verified (`site.html:880-883`) and acted
on.

| # | Lens | Finding | Verdict | Why / where fixed |
|---|---|---|---|---|
| 90 | behaviour | Per-set environments lose autoescape | ACCEPTED | Verified (`Jinja2Templates(directory=)` sets `select_autoescape()`, the `env=` path keeps what it gets). 7.0: environments are `templates.env.overlay(loader=...)`; parity test checks escaping, `undefined`, extensions, trim/lstrip. |
| 91 | behaviour | The async confirm catches every poll; the stored `issueRequest` cannot send for a detached source | ACCEPTED | Verified (`htmx:confirm` fired on every request with `question` null; `he()` starts `if(!se(n))`). 3.2: return unless `question` is non-empty; re-dispatch on the re-found element with a `__ccConfirmed` flag; two new Chrome tests. |
| 92 | behaviour | New-named cc partials have no routes and no naming rule | ACCEPTED | Verified (`_render`'s fragment test is `startswith("partials/")`). 7.0: named without `cc/`, own routes that 404 when the group is off, `is_partial` from the last directory, classic loader refuses `cc/*`; phases 1, 2, 3, 5 list names and routes. |
| 93 | behaviour | R15 misses partials fetched by URL | ACCEPTED | R15 gains a fetch map; notices, collector, diagnostics and queue get group-specific names on both sides (`home_*`, `health_*`, `person_queue`) and the classic names are never overlaid (a `settings-health` overlay would reach classic home). |
| 94 | behaviour | The census ignores query-string parameters (`machine=`) | ACCEPTED | Verified (`project_detail.html:82`; zero `hx-vals`/`hx-include`). R1 key adds query parameter names and `view`/`mode` values; self-test removing `machine=`. |
| 95 | behaviour | Nesting every Site tab in `#settings-form` breaks import, Android and every save | ACCEPTED | Verified (import and Android forms and the AI section outside the form; `validate` refuses unknown keys; bench `name="tier"`). 1.3 and 5.3: tabs display only, sibling forms kept, live `KEYS` names; phase 4 tests. |
| 96 | behaviour | R24's `ui` history needs a route change; classic undo would revert a rollback | ACCEPTED | Verified (PUT records only `TREE_KEYS`; undo reverts `entries[0]`). R24: `ui` branch in `api_admin_site_put`, undo skips `ui` entries, test. |
| 97 | behaviour | Opening a tab does not scroll to the target | ACCEPTED | Verified (scroller acts on `afterSwap` only). 3.2: `scrollIntoView()` after activation when the target exists; viewport tests for a first-paint and a load-triggered anchor. |
| 98 | behaviour | `hx-preserve` on the missing-files slot is on no hook list | ACCEPTED | Verified (`project_detail.html:337`). 3.3 row, R2 list, phase 2 Chrome check. |
| 99 | embedded-apps | The topbar's `data-ui` marker is never defined | ACCEPTED | Verified (classic topbar has no marker). 7.0: `data-ui-apps` computed from `apps` in the effective set, missing means classic; the class moves to `html.cc` (no body in `<head>`); phases 6 and 8 reworded; three marker tests. |
| 100 | embedded-apps | Bench `.hud`/`.dock`/`.snav` rules would override hud-common on cc pages | ACCEPTED | Verified (`cc-terminal.css:223-255`, `cc-components.css:23-40`). 2.1: excluded from the three cc sheets; CSS-fact test. |
| 101 | embedded-apps | Bench data-URI SVGs fail ytdl's scan | ACCEPTED | Verified (hits at `cc-terminal.css:73/91/431`, `cc-components.css:89`). 2.1: percent-encode slashes; `_ABSOLUTE` over every cc sheet and hud-common; phase 6 lists ytdl's test. |
| 102 | embedded-apps | No pin stops a HUD popover base rule declaring `display` | ACCEPTED | Verified (the drawer pin exists in each SPA suite). 3.4 and phase 1: no-`display` pin for `.hud-more`, `#hud-more`, `#hud-user` in four suites and the cc CSS-fact file. |
| 103 | embedded-apps | R6 still says the lifts go in classic `style.css` | ACCEPTED | R6 reworded: `cc/hud.css` after the END marker, and `cc/phone.css`. |
| 104 | embedded-apps | Hashing b-roll's links breaks `test_mounted_prefix.py:100` | ACCEPTED | Verified. R16 and 4.3 choose `Cache-Control: no-cache` (no markup change). |
| 105 | embedded-apps | `ccsync_ui_effective` would be set on the public share page | ACCEPTED | Verified (`/broll/share/` is a gate open prefix). 7.0 excludes it, api and media paths; no-`Set-Cookie` test. |
| 106 | embedded-apps | The SPA HUD never shows counts; R22 forbids phase 1's own lift and `@font-face` rules | ACCEPTED | Verified (`ui.py:707/717`, `partial_topbar`). 3.4: `partial_topbar` computes the counts; R22 allows `@font-face` and the `:has()` lift and scroll blocks, recorded in the snapshot. |
| 107 | tests-and-gate | `/go/<panel>` breaks four classic pins not listed | ACCEPTED | Verified (d-db:464, d-diag:596, `test_health_page.py:97`, copy:293). R11 and phase 5 rewrite three; the classic topbar keeps `/#server-notices`, so copy:293 stays; R13 names which topbar. |
| 108 | tests-and-gate | Vocabulary allow-lists match only the bracketed uppercase MOVE label | ACCEPTED | Verified (`VOCABULARY_ALLOWED` l.395/398, `TEMPLATE_VOCABULARY_ALLOWED` l.574; `machine` retired). R12 decides the label: "...on every computer" (phase 2 cc key, phase 7 copy and `FILE_MOVES.md`). |
| 109 | tests-and-gate | Mechanical case-insensitive twins fire on "update"/"upload" | ACCEPTED | Verified (`("[ UP ]", ...)` l.94). R12: per-entry twin table, label entries as whole-label key matches; self-test. |
| 110 | tests-and-gate | The lowercase bracket pattern matches required markup | ACCEPTED | R12 defines extraction (visible text and attributes, JS text writes, CSS `content:`) and `\[ [a-z]` with the space; self-test on `VISIBILITY_FILTER` and a selector. |
| 111 | tests-and-gate | `templates/cc/` in `OWNED_TEMPLATES` breaks the 17-count and table pins | ACCEPTED | Verified (`seen == 17` l.190, glob l.84-92). R11: `OWNED_TEMPLATES` stays classic; a new `CC_OWNED_TEMPLATES` and which test takes which. |
| 112 | tests-and-gate | The resolver cannot reach the renamed shell; "asserted on both" hits classic CSS pins | ACCEPTED | R11: resolver for same-named templates only, never CSS; an explicit rendered shell twin list in phase 1. |
| 113 | tests-and-gate | Neither the census click pass nor the sweep can run in the named gate | ACCEPTED | Verified (no node in `ci.yml` or `run_all_tests.ps1`; the d-ui harness is `file://`). R1 split into a pytest static half and `tools/census_click.js`; 7.1 says which gate runs what; reports attached per phase. |
| 114 | tests-and-gate | The coverage meta-test cannot be an ordinary collected test | ACCEPTED | R11: a `pytest_sessionfinish` hook that fails only on a full collection and prints a skip notice on a subset; recorder self-test. |
| 115 | tests-and-gate | `ON_EVERY_PAGE` and the copy_value check cannot see the cc forks | ACCEPTED | Verified (`p.name` compare, l.51). 2.5: relative paths; a rendered-page script-src assert. |
| 116 | tests-and-gate | The precache `url()` resolution fails on `data:` | ACCEPTED | Verified (`style.css:849-850`). 2.5: `data:` exempt. |
| 117 | rollout | The group-set header records no template generation | ACCEPTED | R23: `all` expanded to concrete groups; `X-CC-UI-Gen` token, Want on a token mismatch, kept after phase 8; runbook "off before an image rollback"; test. |
| 118 | rollout | A stored empty row masks phase 8's default | ACCEPTED | Verified (`pick()` returns any stored row). R24: `none` value, row delete for `site`, `_settings_fallback` special case; phase 8 split into 8a/8b with a notice and a soak refusal. |
| 119 | rollout | `/ui/preview` unreachable from an installed iPhone app | ACCEPTED | Verified (`"display": "standalone"`; nothing links the route). 3.4: links in the HUD menu and on classic `/account`, redirect to `next`; 7.1 previews from the installed app; RELEASE.md names the link. |
| 120 | rollout | Validation silently adds `chrome` | ACCEPTED | 7.0 and R24: refuse (422); the form shows `chrome` ticked and disabled with the sentence; test. |
| 121 | rollout | One failed manifest read flips the studio classic for the process | ACCEPTED | Verified (`manifest_for_app` caches `_shape({}, settings)`). 7.0 plumbing: the fallback is not cached; retry test. |
| 122 | rollout | b-roll's index.html stays heuristically cacheable | ACCEPTED | Verified (`FileResponse`, no Cache-Control). R16: `index()` sends `no-cache` too; header pin. |
| 123 | rollout | `/help` cannot be variant-neutral with a page map | ACCEPTED | Verified (`HOW_IT_WORKS.md:476-481`). Phase 7 rewrites page-map rows to destinations only; the full layout rewrite moves to phase 8; both docs join the R13 check. |
| 124 | mobile-a11y-i18n | Wave 1's a11y/mobile/i18n defects never applied or logged | ACCEPTED | Verified in the plan text and the tree (no banner has a live region; bench fields 13 px; `.hud-name` Orbitron on `brand_org`). R10 live regions, `font-display: optional`, Latin Extended-A, 16 px fields and 44 px targets with `--cc-tap` in hud-common, R19 lint widened to every display-face selector with `brand_org` in mono, forced colours and reduced motion inside hud-common, grain and blur off under reduced motion (2.2, 2.3, 2.4, R10, R19). |
| 125 | mobile-a11y-i18n | The sticky HUD hides deep-link targets and focus (no scroll-padding) | ACCEPTED | Verified (bench `.hud` sticky 58 px; no `scroll-padding` in the tree). 2.2: `html:has(.hud)` scroll-padding outside hud-common; sweep and focus checks. |
| 126 | mobile-a11y-i18n | Explanations on controls unreadable on touch | ACCEPTED | 3.2: a `.tip-btn` beside explained controls on coarse pointers; fine-pointer tips extended to keys, tabs and nav links; sweep check. |
| 127 | mobile-a11y-i18n | A persistent fold hides answers, refusals and deep-link targets | ACCEPTED | Verified (`.win.collapsed > :not(.bar) { display: none !important }`). 3.1: unfold on user-started swaps, hash targets and banners, without writing the store; aria-label count; Chrome test. |
| 128 | mobile-a11y-i18n | Tabs keep the bench's partial ARIA | ACCEPTED | Verified (`site.html:45-49` has `role=tab` only). 3.2: APG pattern, `hidden` panels, a save refusal activates its tab; markup and keyboard tests. |
| 129 | mobile-a11y-i18n | Single-letter shortcuts and `.kbd` hints; `s` saves from a focused button | ACCEPTED | Verified (`site.html:880-883`; 16 `.kbd` across the bench). 3.2 table: no single-key action shortcut ships; `/` focus-find guarded; no `.kbd` inside a key; test. The finding was truncated in the hand-off; its visible part was acted on. |

### Wave 4 (2026-09-25)

Five lenses again. Every finding was checked against the tree before the
plan changed (`ui.py:809/1621/1845-1858/4466-4480`, `notices.html:33-35`,
the 17 templates including `partials/sidebar.html`, `db.py:3448-3612`,
`collector_health.html:17`, `admin_diagnostics.html:37`,
`project_detail.html:173-190`, `account_computer.html:38-109`,
`htmx.min.js` `Ut`/`Xt`/`lastButtonClicked`, `admin_alerts.html:199`,
`htmx_errors.js:413`, `site_settings.js:818-852`, `setup_routes.py:455-478`,
`db.py:4041`, `site_store.py:988-1003`, `app.py:1661`, `sw.js:136`,
`tools/jobs.py:96-142`, `stamp.html`, `base.html:37`, `style.css:402-407`
and `1684-1690`, the bench `.hud`/`.dock`/`.snav-h` rules, the SPA
`.rule` divs and topbar fetches, `test_music_mount.py:8-10`,
`test_sweep_2026_09_04_copy.py:74/359/588`, the bench's retired words,
d-ui's `--virtual-time-budget=15000`, `test_mobile_admin.py:190`). None was
rejected; 135 is a correction that removes work. The two `--cc-dock-h`
findings and the two sticky-HUD findings from different lenses are one
defect each. The last finding's text was truncated in the hand-off ("Add
one"); its visible part was verified (no banner has a persistent live
region; block 3 moves banners) and acted on with a fix of the reviser's
choosing.

| # | Lens | Finding | Verdict | Why / where fixed |
|---|---|---|---|---|
| 130 | behaviour | The notice dismiss answers with classic `notices.html` | ACCEPTED | Verified (`ui.py:1845-1858`). 5.1 and R15: `?view=home-problems` or `health-notices`, 404 when the group is off; the fetch map covers write responses; tests in phases 2 and 5. |
| 131 | behaviour | The tree's poll and tick drop `?as=` | ACCEPTED | Verified (`_as_qs`, `fleet.html:4-7`). 5.1: `as_qs` in the tree context, poll and `view=tree` response; `?as=bob` test; R1 census pair `/partials/sidebar` to `/partials/projects-tree` with a self-test. |
| 132 | behaviour | The sidebar is on 17 pages, the terminal tree on two | ACCEPTED | Verified (17 includers). D17 recorded (home and project only), 1.1 row, R1 structured moves, phases 3-5 verification. |
| 133 | behaviour | A typeless fold button submits `#settings-form` | ACCEPTED | 3.2: `type="button"` from the macro; markup-fact test over `templates/cc/**`; phase 4 no-PUT Chrome check. |
| 134 | behaviour | `NOTICE_KINDS` links `/#fleet-collector` while `home` is on | ACCEPTED | Verified (`db.py`, six kinds). 3.3: ids `fleet-collector` and `server-notices` kept on the home bodies; R13 states the hash per variant; phase 2 test. |
| 135 | behaviour | The diagnostics listing already exists | ACCEPTED | Verified (`ui.py:4466-4480`, `newest_diagnostics_per_machine`). 1.5 and 5.3: the BACKEND ticket dropped; own-route "every computer" links; phase 5 wording. |
| 136 | behaviour | The file-move confirm is a computed `hx-on::confirm` | ACCEPTED | Verified. 3.2: it keeps its handler and native confirm (stated), 1.2 row corrected; move fields and the account `hx-on` hooks on the 3.3 list. |
| 137 | behaviour | An async confirm drops the pressed button's value | ACCEPTED | Verified (`Xt` clears `lastButtonClicked` on focusout; values are collected after the confirm). 3.2: submitter recorded before the dialog, hidden input on OK; Chrome test. |
| 138 | embedded-apps | The HUD does not stick on classic pages; fixing it covers the classic tree | ACCEPTED | Verified (bench `.hud` sticky; host as tall as the HUD; `style.css:402-407`). 2.2 and 3.4: host `display: contents`, `.project-tree` lift, phase 1 scroll checks. |
| 139 | embedded-apps | `--cc-dock-h` on body never reaches html's scroll-padding | ACCEPTED | 2.2: declared on `html:has(.hud-dock)`; R22 scope updated; CSS-fact assert. |
| 140 | embedded-apps | The per-SPA font GET test cannot run in the SPA suites | ACCEPTED | Verified (no SPA suite imports the dashboard; `test_music_mount.py:8-10`). 4.2: all three checks in the dashboard suite via `urljoin` on the known sheet URLs. |
| 141 | embedded-apps | A client cookie rewrite without `path=/` shadows the server's | ACCEPTED | 7.0: exact write string with `path=/` and `samesite`/`secure`; per-SPA test. |
| 142 | embedded-apps | The SPAs keep their box-drawing `.rule` under the HUD | ACCEPTED | Verified (three index files). Phase 1: `#dash-topbar:has(> .hud) + .rule { display: none }` per SPA sheet; R22 scope; CSS-fact test. |
| 143 | embedded-apps | Every SPA load jumps from the fallback header to the HUD | ACCEPTED | Verified (fetch then swap in all three). 7.0: `ccsync_ui_effective` carries `chrome`; the first-paint script moves to phase 1 with an `html.cc-chrome` height reservation; phase 6 reuses it. |
| 144 | tests-and-gate | Phase 5 edits the enabled home toward a disabled Health; mixed sets never tested | ACCEPTED | 7.0 cross-group rule (panels stay behind `{% if dest not in ui_groups %}` until phase 8; `/go` on the pair); fixture, census, `/go` walk and fetch map over every cumulative set; phase 5 explicit case. |
| 145 | tests-and-gate | The census follows only load-triggered fetches | ACCEPTED | Verified (`project_roots.html:30,55` BROWSE, `project_roots_browse.html` forms). R1 input 4: click-triggered GETs followed; self-test. |
| 146 | tests-and-gate | The census has no role dimension and checks only losses | ACCEPTED | R1 input 5: admin, editor, admin `?as=`; both directions with separate allow-lists; self-test. |
| 147 | tests-and-gate | "Moved to X" is never checked at X | ACCEPTED | R1 input 6: structured `(key, from, to)` moves checked on the destination; self-test. |
| 148 | tests-and-gate | The coverage hook counts loads, so mechanism tests satisfy it | ACCEPTED | R11: record only `_render`/`get_template` names inside `ui_variant` tests; `ui_mechanism` mark excluded; self-test. |
| 149 | tests-and-gate | New-named partials escape the per-file poll pins | ACCEPTED | Verified (`test_mobile_fleet.py` OWNED reads classic names). R11: glob `cc/` visibility and box-drawing test plus `NEW_NAME_TWINS`. |
| 150 | tests-and-gate | The CR-179 scan already covers `cc/`, and the bench fails it | ACCEPTED | Verified (`rglob`, l.74; "sync lanes" at `design/home.html:66`, "wired rig" in `design/account.html`). R12: stated; bench-to-product copy rules; allow-list entries carried to new names; phases 2, 3, 6. |
| 151 | tests-and-gate | The Chrome harness's 15 s budget is shorter than the scenarios | ACCEPTED | Verified (four call sites). R3: `budget_ms` parameter; inline scripts from a rendered cc shell. |
| 152 | tests-and-gate | Phase 4 says to parametrise tests R11 keeps classic | ACCEPTED | Phase 4 row reworded: a separate `CC_OWNED_TEMPLATES` count and `cc/phone.css` twins; the classic tests stay. |
| 153 | tests-and-gate | The fixture sends `X-CC-UI: all` and no generation | ACCEPTED | Phase 0: expanded groups, `current_generation()`, a valid signature; a missing `X-CC-UI-Gen` is defined in R23 and tested. |
| 154 | tests-and-gate | HUD class coverage reads only the topbar source | ACCEPTED | Verified (the stamp uses `.banner`, `.stamp-at`). 3.4: rendered topbar (both roles), stamp (both states) and settings strip. |
| 155 | tests-and-gate | Nothing makes the bracket allow-list shrink | ACCEPTED | R12: stale-entry test and a per-phase length constant. |
| 156 | rollout | `ui` entries in `site_history` break UNDO LAST CHANGE | ACCEPTED | Verified (`expected_at` 409 path; `SITE_HISTORY_KEEP = 10`; `validate_many` on an unknown key). R24: look changes in their own `ui_groups_history` meta, never in `site_history`; three tests; phase 0 row. |
| 157 | rollout | 8b's soak refusal has no mechanism and image mode cannot refuse | ACCEPTED | Verified (`preflight` reads no site state). Phase 8: `ui_terminal_default_since` and a signed `requires_ui_soak_days` refused by 8a; 8b boots safely on an unsoaked site; tests. |
| 158 | rollout | The generation token misses same-version redeploys | ACCEPTED | R23: a digest of the `asset_url` map and every `cc/` template's bytes; same-VERSION test. |
| 159 | rollout | Any editor can opt into unreviewed templates | ACCEPTED | 3.4 and 7.0: `variant=cc` admin-only unless `ui_preview_allowed`; the header set is HMAC-signed (R23); 3.3 scripts send the signature; tests. |
| 160 | rollout | The dashboard's `/static` has no Cache-Control | ACCEPTED | Verified (`app.py:1661`, `sw.js:136`). R8: `no-cache` on `/static`, `immutable` on `?h=`, `cache: 'no-cache'` revalidation; phase 0. |
| 161 | rollout | A minted-admin tool is not runnable in an incident | ACCEPTED | Verified (`tools/jobs.py` `Client`/`Http`, login). R24: `ui_variant.py` on a shared login client, `off`, `site`, `set`, `show`; stub-sender test; runbook. |
| 162 | rollout | The token raises the reload line on fully classic pages after every deploy | ACCEPTED | R23: no comparison when both sets are empty before phase 8; test; phase 8 chooses the generic wording then. |
| 163 | rollout | `import_toml` accepts `ui_terminal_groups` | ACCEPTED | Verified (`site_store.py:988-1003` keeps any `KEYS` member). R24: refused with a pointer, not exported; 422 test. |
| 164 | mobile-a11y-i18n | `--cc-dock-h` scroll-padding resolves to 0 | ACCEPTED | Duplicate of 139. |
| 165 | mobile-a11y-i18n | The classic HUD never sticks; sticking covers the tree | ACCEPTED | Duplicate of 138 (the reviser chose `display: contents` over a sticky host, which keeps the SPA path identical). |
| 166 | mobile-a11y-i18n | The installed iPhone app puts the HUD under the status bar | ACCEPTED | Verified (`base.html:37`, `style.css:1686-1687`, bench fixed 58 px). 2.2: standalone height and padding plus side insets in hud-common; CSS-fact assert and installed-app screenshot. |
| 167 | mobile-a11y-i18n | 601-900 moves music, youtube and install into a popover nothing opens | ACCEPTED | 2.2: `.hud-more-btn` shown 601-900; sweep assert at 768. |
| 168 | mobile-a11y-i18n | The dock query (600) and cc phone query (760) disagree | ACCEPTED | Verified (bench `.page` 100 px and `.toast` 76 px under 760). 2.2: one dock query for every lift; the bench's dock-sized rules rewritten on `--cc-dock-h`; CSS-fact assert. |
| 169 | mobile-a11y-i18n | The 12 px floor for dock labels and `.snav-h` contradicts hud-common ownership | ACCEPTED | Verified (11 px and 10 px in the bench). 2.2: the floor in hud-common's phone query; no-under-12px assert. |
| 170 | mobile-a11y-i18n | The stamp's Syncthing warning has no phone place | ACCEPTED | Verified (`stamp.html`; the bench hides `.hud-meta .hide-sm`). 3.4: compact LED plus `stale`, full sentence in the sheet and `#hud-more`; twin and sweep assert. |
| 171 | mobile-a11y-i18n | Live-region roles on swapped-in banners are not announced | ACCEPTED | R10: persistent `#cc-announce`/`#cc-alert` regions in the shell, filled by `cc.js` after block 3 moves the banner; Chrome test. The finding was truncated; its visible part was acted on. |

### Wave 5 (2026-09-25)

Five lenses. Every finding was checked against the tree before the plan
changed: `fleet_grid.html:452-514` (FORGET and ASK WHY target `closest
.fleet-grid-wrap`), `account_computer.html:37,108` (`hx-swap="none"`),
`admin_assignments.html:171-173` and `cards_landing.html:44` (plain-form
`onsubmit` confirms), `assignments.js:137,274,402`,
`dashboard_update.js:235,259`, `queue_section.html:12-13`,
`fix_root.html:28,31`, `project_detail.html:333,337`,
`minted_secret.html:19-26`, `account.js:25-85`, `ui.py:893-900`
(`_safe_next`), `test_sessions.py:377`, `test_pwa.py:215`, `base.html:171`,
`gen_notices.py:44-45,404`, `ytdl ...music-ytdl.py:365`,
`mobile_sweep.js:22,228-233`, `style.css:122,1860`, `setup.js:277,286`,
`cc-terminal.css:190,211-219,234-237,363-373,494`, `shell.js:274`,
`collector_health.html:84-85`; the cookie quoting was reproduced in the
dashboard venv (`set_cookie('ccsync_ui_effective','chrome,apps')` sends
`"chrome\054apps"`), and a codepoint scan of `templates/`, `design/` and
`static/` produced the glyph list in 2.3. None was rejected. The two
`html.cc-chrome` fallback findings (embedded-apps and rollout) are one
defect. The last finding's text was truncated in the hand-off ("The font
subset ranges leave out glyphs th"); its visible part was verified by the
codepoint scan (`✓`/`✕` are Dingbats, not geometric shapes; General
Punctuation, `ℹ`, `≡`, `⇅ ⇡ ⇣` and `⛔` are used and not listed) and acted on.

| # | Lens | Finding | Verdict | Why / where fixed |
|---|---|---|---|---|
| 172 | behaviour | LOST COMPUTERS and the banners moved out of the grid body break FORGET and stop refreshing | ACCEPTED | Verified (`fleet_grid.html:512-514`, `ui.py:4520-4542`). 5.1: both stay nested in the `.fleet-grid-wrap` body; R1 (9) hx-target resolution check with a FORGET self-test; phase 2. |
| 173 | behaviour | Account swap-none posts are answered by other groups' partials, and oob still runs | ACCEPTED | Verified (`account_computer.html:37,108`). R15: `?view=none` answers an empty 200, exemption only for empty answers; no-oob test; phase 3. |
| 174 | behaviour | "Dialog confirm" rows cover confirms `htmx:confirm` never sees | ACCEPTED | Verified (plain-form `onsubmit`, synchronous `window.confirm` in the JS). 3.2, 1.3, 1.4: native confirms kept verbatim; test for ARCHIVE and CLOSE and no bare `hx-confirm`; phase 4. |
| 175 | behaviour | In-page tabs break tab_memory's section and scroll restore | ACCEPTED | Verified by reading the plan's 3.2 (activation from hash only). 3.2: per-page tab store, tab_memory cc branch skips zero-rect elements; Chrome test; phase 4. |
| 176 | behaviour | `fix_root` is a same-named overlay inside the split queue fragment | ACCEPTED | Verified (`queue_section.html:13`, `fix_root.html:28,31`). Phase 2: `home_fix_root`/`person_fix_root`, `NEW_NAME_TWINS`, 7.0 list, R1 move; phase 3 per computer window. |
| 177 | behaviour | `cc/project_detail.html` is the wrong overlay path | ACCEPTED | Verified (`templates/partials/project_detail.html`). Four mentions replaced; phase 0 shadow assert. |
| 178 | behaviour | A minted secret can land in a folded window | ACCEPTED | Verified (oob into `#minted-secret`). 3.1: never foldable, oob unfold as second guard; Chrome test; phase 4. |
| 179 | behaviour | account.js is shared and writes classic colour classes | ACCEPTED | Verified (`account.js:25,30,61,85`). 2.1 fork list, 3.3 hooks row, phase 3. |
| 180 | behaviour | The preserved missing-files id is keyed by loop index | ACCEPTED | Verified (`project_detail.html:333,337`). 3.3: `missing-{{ e.device_id }}`; phase 2 Chrome check. |
| 181 | embedded-apps | `chrome,apps` is sent quoted and escaped | ACCEPTED | Reproduced in the dashboard venv. 7.0: dot-separated value on both writers; raw `Set-Cookie` and raw-parse tests; phase 1. |
| 182 | embedded-apps | The `cc-chrome` reservation hides the fallback header when the topbar is not injected | ACCEPTED | Verified (the three loaders bail and keep the fallback). 7.0: `finally` removal, re-add only on `.hud`, `cc-chrome-pending` safety net; per-SPA tests; phase 1. |
| 183 | embedded-apps | The reservation still jumps by the `.rule` height | ACCEPTED | 7.0: `html.cc-chrome #dash-topbar + .rule { display: none }`, R22 allow-list, CSS-fact test; phase 1. |
| 184 | embedded-apps | Look-switch links send SPA users to `/` | ACCEPTED | Verified (`_safe_next` keeps only `/...`). 3.4: explicit `next` from `nav_current`, Referer parsed and host-checked; test. |
| 185 | embedded-apps | `is_partial` switches off the topbar's cookie | ACCEPTED | 7.0: `partial_topbar` calls the cookie helper explicitly; header test both ways. |
| 186 | tests-and-gate | The coverage hook cannot see includes and cannot tell cc from classic | ACCEPTED | Verified (`settings_nav` has no route; logical names shared). R11: record `template.filename` under `templates/cc/` from per-set env loads within ui_variant tests; two self-tests. |
| 187 | tests-and-gate | The ui_variant fixture cannot make an editor or a partial set terminal | ACCEPTED | Phase 0: the fixture writes `ui_terminal_groups`, asserts `data-ui-groups`, headers only on htmx calls; editor self-test; R1 roles via the setting. |
| 188 | tests-and-gate | "Rendered cc page" checks in phases 0-1 before any cc page exists | ACCEPTED | Phase 1: test-only `cc_probe.html` child through a test loader; R3 updated; phase 0 "both shells" corrected to base.html only. |
| 189 | tests-and-gate | The census key collapses controls told apart by a hidden value | ACCEPTED | R1 (8): constant hidden values in the key, multiset comparison, archived projects and both acks in the matrix; `restore_drill` self-test. |
| 190 | tests-and-gate | The bracket patterns miss CSS-generated and concatenated brackets | ACCEPTED | Verified (`style.css:122`, `setup.js:277,286`). R12: any bracket in `content:`, fragment rule for JS; self-tests. |
| 191 | tests-and-gate | Nothing tests the no-em-dash rule for cc CSS | ACCEPTED | Verified (`test_no_em_dash.py` has no CSS). R12 and phase 0: `cc/*.css` scanned raw. |
| 192 | tests-and-gate | A ytdl test reads the first 600 px block | ACCEPTED | Verified (l.365). Phase 1: named; hud-common after ytdl's phone block or the test takes the `.search-bar` block. |
| 193 | tests-and-gate | hx-headers key order is pinned | ACCEPTED | Verified (`test_sessions.py:377`). Phase 0: keys appended after `X-CSRF-Token`, `tojson`, both pins listed. |
| 194 | tests-and-gate | The font licence entry is aimed at gen_notices.py | ACCEPTED | Verified (`gen_notices.py:44-45,404`). 2.3: edit the block in THIRD_PARTY_NOTICES.md; fonts-in-notices test. |
| 195 | tests-and-gate | The classic-env `cc/shell.html` check passes vacuously | ACCEPTED | Phase 0: temporary `cc/probe.html` in a fixture dir, both environments asserted. |
| 196 | rollout | After 8b or an unattended rollback, open pages get the wrong look with only a reload line | ACCEPTED | Verified (`dashboard_update` watchdog revert, Packages ROLLBACK_URL). R23: `HX-Refresh` (GET) or 409 plus Want (write) when the look cannot be served; unknown-group rule in phase 0; 8b keeps parsing `X-CC-UI`; runbook reworded; tests. |
| 197 | rollout | The reservation hides the fallback for good on a failed fetch | ACCEPTED | Duplicate of 182. |
| 198 | rollout | Every customer admin can preview half-ported templates from phase 1 | ACCEPTED | 3.4 and 7.0: `ui_preview` `off`/`admins`/`everyone`, off in the vendor build; this studio sets `admins`; tests. |
| 199 | rollout | Login and setup cannot be previewed; no escape from a broken cc login | ACCEPTED | 3.4 and 7.0: `classic`/`site` work signed out, signed `cc` cookie honoured signed-out for current admins, classic link on the login page, logout keeps the cookie; tests; phase 3. |
| 200 | rollout | The preview cookie has no lifetime | ACCEPTED | 7.0: Max-Age 180 days, Path, SameSite, Secure, HttpOnly; test. |
| 201 | rollout | `?h=` URLs are immutable whatever hash they carry | ACCEPTED | Verified (plain `StaticFiles` ignores the query). R8: immutable only on the current hash, `no-store` otherwise; test. |
| 202 | rollout | One global generation token raises the reload line after every deploy | ACCEPTED | R23: the token is scoped to the page's shell assets and its own groups' templates; test. |
| 203 | mobile-a11y-i18n | Ticks, radios, switches, tree rows and tags have no 44 px rule, and the sweep is blind to them | ACCEPTED | Verified (bench hidden inputs, `mobile_sweep.js:22,230`). 2.2: coarse-pointer block; sweep selectors and opacity-0 labels; twin test. |
| 204 | mobile-a11y-i18n | No phone wrap rules; the move key overflows 390 | ACCEPTED | 2.2: `mobile.css` wrap rules carried in cc vocabulary; twins; phase 2 CJK sweep. |
| 205 | mobile-a11y-i18n | The 1 px red focus ring vanishes among red frames | ACCEPTED | Verified (`style.css:1860`). 2.1: theme-common unchanged, a 2 px `--hi` override after it in `cc/terminal.css` and hud-common; twin and Chrome check. |
| 206 | mobile-a11y-i18n | The floating tip breaks WCAG 1.4.13 and outlives swaps | ACCEPTED | Verified (`shell.js:274` focusin, no Escape). 3.2: Escape, hoverable, anchor-positioned, hides on beforeSwap and hashchange; tests. |
| 207 | mobile-a11y-i18n | Glyphs reach screen readers | ACCEPTED | R10: `aria-hidden` on markup glyphs, CSS alt-text on generated content, meters labelled; tests. |
| 208 | mobile-a11y-i18n | The HUD brand is unbounded in a nowrap bar | ACCEPTED | Verified (`.hud-brand` nowrap). 2.2: hud-common shrink and ellipsis with `title`; phase 1 sweep. |
| 209 | mobile-a11y-i18n | Body LEDs vanish under forced colours | ACCEPTED | Verified (background-only `.led`). 2.2: forced-colours block in `cc/terminal.css`, visually-hidden state word; tests. |
| 210 | mobile-a11y-i18n | The issue slot is a scroll trap on phones | ACCEPTED | Verified (`cc-terminal.css:363-366,494`). 5.1: no scroller on coarse pointers, `tabindex` elsewhere, em-based heights; sweep. |
| 211 | mobile-a11y-i18n | `.tag` lowercase changes interpolated data | ACCEPTED | Verified (`collector_health.html:84-85`). 2.1: state words lowercased in templates, values in `.v`; markup test. |
| 212 | mobile-a11y-i18n | The font subset ranges leave out used glyphs (truncated) | ACCEPTED | Verified by codepoint scan. 2.3: ranges derived from the scan, `unicode-range` coverage test. |

### Wave 6 (2026-09-25)

Five lenses. Every finding was checked against the tree before the plan
changed: `static/dashboard_update.js:59-78` (`reloadPanel()` sends
`HX-Request` alone and checks only `!resp.ok || HX-Redirect`),
`topbar.html:209-214` (the stamp poll), `fleet.html:22-28`,
`tab_memory.js:50,127-170` (`PREFIX = "ccsync.tab:"`, `read()` wants
`{t: number}`), `api.py:500-501` (`"device_id": None`),
`project_detail.html:331-337`, `app.py:56-74,166-186` (`_OPEN_GET_ONLY`
has no `/ui/preview`), `admin_packages.html:92-185,514`,
`admin_alerts.html:173-207` and `ui.py:2525`, `design/alerts.html:58,87,
113,129`, the three SPA `style.css` `html, body` rules
(`height: 100%` in b-roll and music, `min-height` in ytdl),
`broll style.css:547,1795` and `index.html:89-92`, `music style.css:527`,
`ytdl style.css:651`, `dashboard/tests/conftest.py` (no shared app; 129
files call `create_app(`), `test_sweep_2026_09_04_copy.py:350-357`,
`cards_pool.py:389`, `recovery.py:936`, `release_feed.py:1177`,
`test_protection.py:547`, `test_alerts.py:791,900`,
`dashboard_update.py:265-278` (`image_version()` exists; only
`runtime_id` is checked), `select_code_root.py`'s "boot the image" rule,
`design/home.html:93,105-109,181,282-288`, `cc-terminal.css:1-12,88-94,
168-169,176-179,211-219,226-232,425-450,496-504`, `cc-components.css:
105-114`, `css/fleet.css:40`, `css/apps.css:439`, `css/sync.css:196`,
`fleet_grid.html:187-203`, `health.py:435-465` (`no_selection`),
`topbar.html:45-47`, `db.py:4939,4959`. The contrast figures were
recomputed (white on `#ff5a3c` 3.10:1, on `#d01818` 5.49:1, on `#b81414`
6.67:1). The headless-Chrome measurements (the SPA header scroll-away and
the b-roll body-padding no-op) and the dock-label arithmetic are the
critics'; the CSS they rest on was verified. None was rejected. The two
`dashboard_update.js` `HX-Refresh` findings (behaviour and rollout) are one
defect. The last finding's text was truncated in the hand-off ("R20
(l.1374) covers only the rendered br"); its visible part was verified
(`cc-terminal.css:1-12` names the customer's website) and acted on,
narrowed to the domain because the CC mark is the product's own logo.

| # | Lens | Finding | Verdict | Why / where fixed |
|---|---|---|---|---|
| 213 | behaviour | An htmx request with no `X-CC-UI` follows the setting, so pre-phase-0 pages and the classic `dashboard_update.js` get cc partials | ACCEPTED | Verified (`topbar.html:211-214`, `dashboard_update.js:60,77`). 7.0 order step 2: `HX-Request` without `X-CC-UI` is classic, plus `HX-Refresh`/409 when a full load would differ; R23; phase 0 tests. The classic body is still sent, so the classic script (which ignores the header) stays correct. |
| 214 | behaviour | The "roll back to" select drops held builds' per-version controls and evidence | ACCEPTED | Verified (`admin_packages.html:92-185,514`). 1.3 and 5.3: the select is a shortcut listing only plainly-current-able versions; every held build keeps its folded row; census entries with no allow-list; unsigned-confirm test; phase 4. |
| 215 | behaviour | cc.js's `ccsync.tab:<path>` is tab_memory's own key | ACCEPTED | Verified (`tab_memory.js:50,127-170`). 3.2: `ccsync.cctab:<path>`; coexistence Chrome check; phase 4. |
| 216 | behaviour | `missing-{{ e.device_id }}` renders `missing-None` for every report-only row | ACCEPTED | Verified (`api.py:500-501`, `project_detail.html:331,337`). 3.3: preserved div only when `device_id` is set; two-report-only-row seed and id-uniqueness assert; phase 2. |
| 217 | behaviour | `/ui/preview` is not an open path, so the signed-out escape loops to login | ACCEPTED | Verified (`app.py:166-186`). 3.4: `_OPEN_GET_ONLY` entry, `variant=cc` refused signed out, open-path method test gains it, POST still gated; phase 0. |
| 218 | behaviour | The `#hud-more` copy of the stale-data sentence is never polled | ACCEPTED | Verified (the poll swaps only `#topbar-stamp`). 3.4: the repetition is dropped; the hint sheet reads the polled compact stamp. |
| 219 | behaviour | The forked `dashboard_update.js` inserts an empty panel on `HX-Refresh` | ACCEPTED | Verified (`dashboard_update.js:68,77`). 3.3 row and general rule, R23: reload on `HX-Refresh`, 409 plus Want is an error line; d-ui harness test; phase 4. |
| 220 | embedded-apps | The HUD cannot stick in b-roll or music (`body { height: 100% }`) | ACCEPTED | Verified (`broll style.css:52-61`, `music style.css:42-51`, ytdl `min-height`). 2.2: scoped `html:has(#dash-topbar > .hud) body { height: auto; min-height: 100% }` outside hud-common; R22 allow-list and snapshot; layout screenshots; phase 1. |
| 221 | embedded-apps | Nothing reserves room for the dock at the end of b-roll's page | ACCEPTED | Verified (`#grid-view` 40 px bottom at 700 px, `index.html:89-92`; music and ytdl 120 px). R6: lift on `#grid-view` and the clip-detail view, bottom room on the scrolling container, not `body`; `#pager-next` hit-test; phase 1. |
| 222 | embedded-apps | Fonts served `no-cache` fight `font-display: optional` | ACCEPTED | R8: `/static/fonts/*` immutable, justified by 2.3's new-name rule, now tested by a name-to-sha256 manifest; phase 0. |
| 223 | tests-and-gate | The `ui_variant` fixture cannot reach apps that tests build themselves | ACCEPTED | Verified (conftest has no app fixture; 129 files call `create_app(`). Phase 0: the `ui_variant.site_groups` seam monkeypatched by the fixture, `htmx_headers(client)`, file-local client self-test. |
| 224 | tests-and-gate | The census key ignores the pressed button, so dropping CLEAR passes | ACCEPTED | Verified (`admin_alerts.html:199`). R1 (10): one key per (form, submitter) with `name=value`; state matrix; CLEAR self-test. |
| 225 | tests-and-gate | The census checks presence in the DOM, not visibility, and the bench hides bar actions on phones | ACCEPTED | Verified (`css/sync.css:196`, `cc-terminal.css:496-497`). R1 (11): click half at 390 and 1440 asserts a non-zero box or an allow-listed phone home; CSS-fact test on phone-query `display: none`; 2.1 not-carried list. |
| 226 | tests-and-gate | Phase 6 changes SPA controls with no census | ACCEPTED | R1 (12) and phase 6: `census_click.js` on the three SPAs with `html.cc` off and on, required-id lists, `/cards/` in the static census. |
| 227 | tests-and-gate | The Python bracket scan has no file set; "shrink each phase" cannot be met | ACCEPTED | Verified (`VOCABULARY_FILES` lacks `cards_pool.py`, `recovery.py`, `release_feed.py`). R12: every module via `_py_files`/`_docstring_nodes`, three-file self-test, "may not grow", constant lowered in phases 5 and 7; phase 7 widens `VOCABULARY_FILES`. |
| 228 | tests-and-gate | Phase 7's list of Python-copy pins misses at least three | ACCEPTED | Verified (`test_protection.py:547`, `test_alerts.py:791,900`). R11 says the list is not complete; phase 7 names them and adds a grep step turning each hit into a D8-label assert. |
| 229 | rollout | A stored group with no `cc/` templates in the running build serves classic partials into cc frames or reload-loops, and a group enabled early goes live on a later deploy | ACCEPTED | 7.0: every resolved set intersected with this build's groups; R23: "cannot serve" redefined, one-reload test; `_validate` 422 for a template-less group; groups form "waiting for its build"; phase 0. |
| 230 | rollout | The image fallback can predate phase 0, so unattended rollbacks land on a build that never sends `HX-Refresh` | ACCEPTED | Verified (`select_code_root.py` "boot the image", `dashboard_update.py` checks only `runtime_id`, `image_version()` exists). R23 header floor: phase 0 ships as an image (7.2), groups and `?variant=cc` refused below `HEADER_FLOOR`, signed `min_image_version` in later records enforced by preflight; R23's "whether or not it ran" qualified; tests. |
| 231 | rollout | `dashboard_update.js` repaints with plain `fetch()` and ignores `HX-Refresh` | ACCEPTED | Duplicate of 219. |
| 232 | mobile-a11y-i18n | The terminal tree has no real checkbox and no `<details>` groups; R10 hides the only tick state | ACCEPTED | Verified (`design/home.html:181`, `sidebar.html:13-21,57`). 5.1 new row: `<label>` plus a hidden focusable `input.proj-check[hx-post]`, `<details data-key>` groups, visually hidden state on the project page; markup and keyboard tests; phase 2. |
| 233 | mobile-a11y-i18n | The 16 px phone field rule loses on specificity | ACCEPTED | Verified (`.prompt-in input`, `.pick select`, `.inp.sm`, `.ctrl .inp.sm`). 2.2: `html[data-ui="cc"] :is(...)` placed last, smaller sizes dropped; computed check in `mobile_sweep.js` (FAIL). |
| 234 | mobile-a11y-i18n | `.switch` has no visible focus, is named "off on", loses state under forced colours; the `.check`/`.radio` ring is out of reach | ACCEPTED | Verified (`cc-components.css:105-114`, `design/alerts.html:87`). 2.2: `:has(input:focus-visible)` 2 px rings, a named input with `aria-hidden` halves, a forced-colours rule; tests. |
| 235 | mobile-a11y-i18n | The 12 px floor plus 24 px side padding overflows "transfers" in the dock | ACCEPTED | Arithmetic checked against `cc-terminal.css` (five `1fr` columns, 1 px tracking). 2.2: the dock pays only the real inset, `letter-spacing: 0`; `scrollWidth` assert at 360 and 390; R5 adds 360. |
| 236 | mobile-a11y-i18n | The page-level confirm has no focus handling or modality | ACCEPTED | 3.2: `<dialog>` with `showModal()`, Cancel autofocus, cancel clears the stored event and the temporary submitter input, focus after OK to the re-found element or its fold button; `busy()` checks `#cc-confirm[open]`; keyboard tests. |
| 237 | mobile-a11y-i18n | Fold buttons are unnamed; window titles are snake_case with no heading or region | ACCEPTED | Verified (`design/project.html:41-128`). 3.2 foldable row: `<h2 class="t">` with hidden underscores, `section aria-labelledby`, a named fold button; markup test. |
| 238 | mobile-a11y-i18n | Error LEDs blink and the grain moves forever (WCAG 2.2.2) | ACCEPTED | Verified (`cc-terminal.css:92,217`). 2.4: four blink iterations then steady, re-armed on swap; grain static or capped; no-`infinite` CSS-fact assert except `.spin`. |
| 239 | mobile-a11y-i18n | The HUD's `backdrop-filter` re-blurs animated content for almost nothing | ACCEPTED | Verified (`cc-terminal.css:228-230`). 2.4: dropped from hud-common and `cc/terminal.css`, CSS-fact assert; R7's test kept as a guard. |
| 240 | mobile-a11y-i18n | The primary key fails contrast on hover; "darken the fill" can be read as changing `--red` | ACCEPTED | Recomputed (3.10:1 on `#ff5a3c`). 2.2: key-local `--k-bg` `#d01818` and hover `#b81414`, `--red`/`--red-hot` unchanged, contrast pins. |
| 241 | mobile-a11y-i18n | "Every `content:` has an alt part" conflicts with the stacked-table labels | ACCEPTED | R10: decorative gets an empty alt, informational an explicit one; `td[data-label]::before` on an allow-list; `@keyframes` excluded by the parser. |
| 242 | mobile-a11y-i18n | The find box filters mid-IME composition | ACCEPTED | Verified (`design/home.html:282-288`). 5.1: skip while `isComposing`, filter on `compositionend`, NFC plus lower-case compare; composition test. |
| 243 | scope-and-truth | The terminal home breaks the nothing-ticked rule and drops `fleet_headline` | ACCEPTED | Verified (`design/home.html:93,105-109`, `fleet_grid.html:187-203`, `health.py` `no_selection`). 1.2 lost list, 5.1: the row keeps the headline's text and level; the online readout excludes `no_selection`; phase 2 test with a silent nothing-ticked computer. |
| 244 | scope-and-truth | Alerts gets the nested-form trap, and fails silently | ACCEPTED | Verified (`design/alerts.html:58,95,113,129`, `admin_alerts.html:173-207`, `ui.py:2525`). 1.3: four sibling forms, `form=` never nesting, `alerts_*` names; phase 5 tests. |
| 245 | scope-and-truth | Folds, tips and confirms cannot reach the SPAs as planned | ACCEPTED | Verified (the SPA bench pages load `shell.js`). Phase 6: a byte-identical SPA helper with an identity test; fold and tip checks; effort 5-8, total 28-41. |
| 246 | scope-and-truth | The HUD problems count and the home readout would disagree | ACCEPTED | Verified (`topbar.html:45-47` counts errors; the bench readout counts all). 5.1: the readout uses `notice_counts`, errors as the number, warnings as a foot; agreement test. |
| 247 | scope-and-truth | "N behind" cannot be counted from a store that forgets deletes | ACCEPTED | Verified (`db.py:4939,4959`). 5.1 and 1.2: dropped; running and current version shown; a count would be BACKEND over an append-only history. |
| 248 | scope-and-truth | "on since 08:02" has no data source | ACCEPTED | 5.1: dropped; the second line is the last-report time through `ago`; a real one would need a companion field. |
| 249 | scope-and-truth | The CSS derived from `cc-terminal.css` would ship the customer's website name (truncated) | ACCEPTED | Verified (`cc-terminal.css:1-12`). 2.1 and R20: bench header comments not carried; CSS-fact test on the domain in `static/cc/*`, `templates/cc/**` and hud-common. |
