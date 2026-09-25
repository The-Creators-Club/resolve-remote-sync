# P3: phase 3, everyday rest (group `everyday`)

Builder P3, 2026-09-25, worktree branch `ui-port`. Plan: `docs/UI_REDESIGN_PORT_PLAN.md`
1.2, 3.1, 5.1, 5.2, 7.1 row 3, R15. Nothing committed, no version bumped.
A first P3 pass had already built transfers, project setup, installer, sign
in and help. This pass finished the group: the account page, the person
queue, the missing stylesheet, the tests and this ledger.

## Built

- **Transfers** (first pass): `cc/transfers.html` + `cc/partials/transfers.html`.
  The frame is static. A hidden poll element asks `/partials/transfers` every
  2 s with `hx-swap="none"` and `hx-select-oob` over six inner ids
  (`#xf-safe`, `#xf-live-meta`, `#xf-live`, `#xf-q-meta`, `#xf-queued`,
  `#xf-history`). Every id is drawn in every state. `static/cc/everyday.js`
  keeps the open state of `details[data-key]` queue rows across the oob swap,
  because the shell's keeper only sees ordinary swaps. The machine is shown
  under the editor on the admin view (`t.machine` is in the row).
- **Project setup** (first pass): `cc/project_setup.html` +
  `cc/partials/project_setup_panel.html`. `.project-setup-box` sits on the
  window BODY, so every browse, link or create answer (outerHTML, `closest
  .project-setup-box`) leaves the bar and its fold alone.
- **Installer** (first pass): `cc/installer.html`. The bench's "/download
  explainer" window is left out, as the plan says.
- **Sign in** (first pass): `cc/login.html`. Bare, with no HUD. SSO first,
  then the break-glass password form. It always carries a "use the classic
  look" link (`/ui/preview?variant=classic`, which works without a session).
- **Help** (first pass): `cc/help.html`. The document list, the contents and
  the reader. The Settings strip shows for admins only.
- **Account restyle** (this pass): `cc/account.html` plus
  `cc/partials/account_{you,password,computer,jobs,sessions,sync_keys,result}.html`.
  It keeps the same routes, ids, fields, polls, `hx-on` hooks and sentences
  as group F's classic page. Each panel is a folding `.win`. The swap
  targets are the window bodies (`#account-you`, `#account-pw-result`,
  `#account-sessions-wrap`, `#<pc>-jobs`), so no answer replaces a frame.
  Each computer window keeps a static frame. A hidden poll element (30 s,
  plus `account-refresh from:closest .account-pc`) takes only
  `#<dom_id>-body` from the answer (`hx-select-oob`). The classic look links
  are drawn as keys in a "how this browser looks" window, because the
  classic partial has bracket labels. "Fleet stopped" links through
  `/go/admin-fleet-halt`.
- **`view=none`** (R15): the account page's swap-none writes (toggle, update
  now, ask why, and the add row in cc/account.js) post `?view=none`, and the
  routes answer an empty 200 with no oob. The first pass had already added
  update and ask-why. This pass adds the toggle branch through
  `ui_everyday.toggle_answer`.
- **Person queue** (R15, 5.1): `cc/partials/person_queue.html` on
  `GET /partials/person-queue` (new module `ui_everyday.py`). The page draws
  it as a "sync queue" window whose body polls every 10 s. It is always the
  signed-in person. An untick posts `?view=person-queue` and gets the same
  markup back. `cc/partials/person_fix_root.html` draws one FIX DESTINATION
  ROOT per remote computer from that computer's own `build_queue_view`. All
  of these share one fleet snapshot. The route returns 404 when the asking
  page's look has no `everyday`.
- `static/cc/everyday.css` (new; the first pass referenced it but never
  wrote it): only the ev-* glue, reserved result slots and account section
  headings. The bench styles were already in `components.css`.
- `static/cc/account.js` (new): a fork of `static/account.js` with the
  terminal classes and `view=none` on the add row. The classic file is
  untouched.
- `cc/partials/ev_macros.html` gained `result_line()` and `tag()`.
- Shared files (surgical): `ui.py` `partial_toggle` got 4 lines calling
  `ui_everyday.toggle_answer` for `person-queue`/`none`, placed after P2's
  hook. `app.py` got one `include_router(ui_everyday.router)`.

## Omitted controls / not built

- None of the classic account controls is lost. Two of the bench's rows
  have no data behind them and are left out: "Pause syncing" and "Stop all
  syncing on this computer". The bench's "preview as" and "mark what is new"
  strips are left out, as the plan says.
- There is no `cc/offline.html` (it is not on phase 3's list; `/offline`
  stays classic).
- The terminal parameter was NOT added to the existing files `test_cr312`,
  `test_project_setup.py`, `test_help_page.py`, the
  `test_sweep_2026_09_04_dash_ui.py` copy button or `test_account_page.py`.
  Their terminal twins live in the new `test_cc_everyday.py` instead
  (speed).
- Not run (they belong to the sweep or adversarial pass): the census
  structured moves (the sidebar toggle POSTs, the `/partials/sidebar` poll
  and the `as` GET form moving to `/`), the phone sweep, the Chrome checks,
  the retired-word scan over the cc account copy, and the `NEW_NAME_TWINS`
  map entry for `person_queue`.

## Departures

- The person queue is one window for the person. The FIX DESTINATION ROOT
  lines sit inside that window, one per computer, not inside each computer
  window. The computer windows poll every 30 s, and a per-computer queue
  build there would cost one snapshot per computer per beat.
- A computer that leaves the person's list keeps its last body until the
  next page load. Classic removed the whole panel. The frame is static now,
  and an empty answer matches nothing in `hx-select-oob`.
- The account copy says "wired computers", never "wired rigs" (R12).
- The ask-why key is in the computer window's foot, as the bench draws it.
  The classic page had it in the body.

## Tests (run once, dashboard venv)

- New: `dashboard/tests/test_cc_everyday.py`: 63 passed across `classic`,
  `chrome` and `all`. It covers the static no-em-dash and no-bracket scans
  over the 18 everyday templates and the three assets, every page in each
  look, the signed-out sign in, the transfers poll ids, the account hooks,
  account partials answering in the asking page's look, the person queue
  being terminal only (404 in classic), an untick from the person queue,
  and the three `view=none` writes answering empty. All 18 everyday
  `TEMPLATE_GROUPS` files were rendered under `ui_variant` (checked
  in-process: none missing).
- Touched: `test_account_page.py` + `test_ui_variant_mechanism.py`: 94
  passed, 1 skipped. `node --check static/cc/account.js`: ok.

## Hand-offs

- P0 / central: add `person_queue` and `person_fix_root` to
  `NEW_NAME_TWINS` (queue_section/my_queue and fix_root twins) when that map
  exists. Consider adding `cc/everyday.css` and `cc/account.js` to the
  `sw.js` PRECACHE, if hashed cc/ assets are enumerated rather than
  globbed.
- Central gate: the existing classic files listed above still need their
  terminal parameter if the owner wants the twins inside them.
