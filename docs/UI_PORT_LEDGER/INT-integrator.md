# INT: integration of phases 0-7

Integrator, 2026-09-25, worktree branch `ui-port`. Nothing committed, no
version bumped. The inputs were the ten builder ledgers in this directory.

## Suites (worktree code, main venvs)

| Suite | Result |
|---|---|
| dashboard (all 191 files, 8 parallel shards) | **5983 passed, 35 skipped, 0 failed** |
| broll/web | 724 passed |
| music/web | 688 passed, 13 skipped |
| ytdl/web (dashboard venv) | 1033 passed |
| tools (dashboard venv) | 411 passed |

The first dashboard pass had 6 failures. All of them are fixed; the fixes
are listed below. The coverage hook needs a whole-suite run in a single
process, so it was checked another way: every test file that uses
`ui_variant` was run in one process and `RENDERED_CC_FILES` was read after
it. Nothing is missing now. Before the fix one file was missing:
`cc/partials/admin_suspend_button.html`.

## Seams checked

- **Includes:** every `{% include/extends/import %}` and every `cc/…`
  template name in Python resolves, either directly or through the overlay's
  `cc/` prefix. Nothing is missing.
- **Registry:** every `cc/` template is in `TEMPLATE_GROUPS`, and every
  registry row has a file. The built groups are chrome, home, everyday,
  settings-fleet, settings-health and apps.
- **Assets:** every `asset_url()` target and every `/static/cc/…` target
  exists.
- **Routes:** the new modules declare no duplicate routes. The only
  duplicate path strings are old ones on different prefixes (`/api/v1`
  compared with the pages).
- **Dev boot:** `tools/mobile_sweep_seed.py` was run with `DASH_DEV_INSECURE`
  and every page was loaded in classic and with the cc preview on (all six
  groups):
  - pages: 27 pages, the 7 `/go/<panel>` links and 36 partials, the partials
    requested with the page's signed `X-CC-UI` headers
  - **no 5xx in either look**, and all 36 partials answer 200 in the cc look
  - 20 full pages render `data-ui="cc"`
  - `/cards`, `/broll/` and `/ytdl/` return 404 only because the seed mounts
    no checkout for them
  - the new-name partials return 404 to a plain htmx request with no
    `X-CC-UI` header. The design says to do this.
  - the rendered cc pages have no bracket control, no duplicate id and no
    Jinja residue
  - the only em dash is on `/help`, in a doc's own title
    (APPLIANCE_INSTALL.md). Classic shows the same text, and docs are exempt
    from the rule.

## Fixed

1. `cc/partials/fleet_grid.html`: the computers header said "sync lanes", a
   retired word. It now says "sync" (P7's hand-off to P2).
2. P7's `TERMINAL_GAPS` list is now empty:
   - `cc/partials/admin_jobs.html` writes the literal "show finished" /
     "hide finished" labels
   - `cc/partials/project_setup_panel.html` says "Create &amp; link" (the D8
     label)
   - the two protection labels were already present
3. `test_cc_css_facts` found three problems, all fixed:
   - The bare classic class `stack` was on the cc pages and partials for
     admin_users, admin_assignments, admin_jobs, setup and project_detail.
     It is removed. `.sp-stack > div:empty` and `.project-notes > div:empty`
     keep the one rule `.stack` used to give them.
   - `everyday.css` had a `.snav` selector outside hud-common. It now
     selects `nav[aria-label="settings"]`.
   - The saving pulse in `settings_people.css` was `infinite`. It is now 6
     beats (owner rule: nothing moves forever).
4. R11 pins on Python copy that P7 rewrote are now rewritten too:
   - `test_bug_hunt_2026_09_24_w2_d-api.py` (two places) now looks for
     `"Unarchive"`
   - `test_bug_hunt_2026_09_18_dashboard_mediums.py` now looks for
     `"Move on the server and on every computer"`
5. Coverage: the new test
   `test_cc_settings_people.py::test_suspend_and_resume_answer_in_the_asking_look`
   (3 parameters) renders the suspend button in all three looks.
6. The home problems readout and the HUD count read the notices at two
   different moments. After a collector write they could show 5 beside 6.
   This made `test_cc_home.py::…agrees_with_the_hud_count[all]` flaky,
   depending on test order. `home_readouts()` now takes the page's own
   `notice_counts`, and `cc/fleet.html` passes it.

## Left as is (noted)

- **Home still shows problems.log and what_computers_said when
  settings-health is on.** D7's default keeps the home problems window. The
  diagnostics window stays because it is where the grid's "Read the answer"
  key puts its answer. The collector is gated as the plan says. The plan's
  7.1 row 5 says all three leave home, so this is a departure for the owner
  to rule on.
- `cc_spa.js` byte-identity and the hud-common byte-identity were checked
  by the SPA suites, which are green.

## Combined omitted controls (from every ledger)

Backend tickets, not built:
- **Home (P2):** "Check now" on the collector, "Dismiss all" on
  problems.log, the percent on the lane meter (the meter shows state only),
  size per project in the tree, and "Stop the fleet" as a dialog on home
  (it is a link to Users for now).
- **Packages (P4a):** the UPDATE ALL panel, and who_answers's "one server
  rule" as a server field (the JS works it out instead).
- **Users / Jobs / History (P4b):** a per-person page (`user.html`) that
  names on Users and Jobs would link to, and real paging on History.
- **Account (P3):** the bench's "Pause syncing" and "Stop all syncing on
  this computer" rows (nothing behind them), and its "preview as" and "mark
  what is new" strips.

Dropped by the plan (wave 6 / D4):
- "N behind", "on since", the version count on Packages, the bench's Taipei
  clock, and the installer's "/download explainer" window.

Kept in a different shape:
- ytdl health: the six `.rstatus` spans stay separate.
- Sync plans / Users / Jobs / History / Setup: the sidebar is dropped (D17).

No control removed: P1 (chrome), P5 (health), P6a (cards landing, b-roll),
P6b (music, youtube).

## Not run (speed rules, for the sweep / adversarial pass)

- the Chrome harness, the census (static and click), the phone sweep at
  360/390/768/1440, and screenshots
- the terminal parameters on the classic suites that each ledger lists
- the `NEW_NAME_TWINS` map, `CC_OWNED_TEMPLATES`, and P0's list:
  `HEADER_FLOOR` refusal, the `/offline` precache test, and the login gate's
  SPA pass-through cookie
