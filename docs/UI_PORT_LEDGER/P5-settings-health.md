# P5: phase 5, settings health / when it breaks (group `settings-health`)

Builder P5, 2026-09-25 (two sittings: the first was stopped mid-work at
15:49; the second finished it). Plan: `docs/UI_REDESIGN_PORT_PLAN.md` 1.3,
1.5, 5.3, 7.1 row 5, R13, R15. Nothing committed, no version bumped.

## Built

- `src/ccsync_dashboard/ui_health.py` (new; one `include_router` line in
  `app.py`): `GET /partials/health-notices`, `POST
  /partials/health-notices/{id}/dismiss` (group checked BEFORE the write, so
  a dismiss is never committed behind a 404), `GET /partials/health-collector`
  (the plan's "BACKEND, small": `db.collector_health` + `enforce_notes` on
  its own route), `GET /partials/health-diagnostics` (no params = newest
  bundle per computer; `editor`/`machine` = that computer's last five). All
  admin only, all 404 when the group is not in the asking page's set. Jinja
  filter `cc_unbracket` for Python-built `[ LABEL ]` strings until phase 7.
- Templates under `templates/cc/`: `admin_health.html` (WHAT IS RUNNING +
  four APG tabs: open findings, problems the server found, collector, what
  computers said; static frames carrying `#server-notices`,
  `#fleet-collector`, `#fleet-diagnostics`, bodies fetched on load),
  `admin_invariants.html`, `admin_protection.html`, `admin_alerts.html`,
  `admin_recovery.html`; partials `health_notices.html`,
  `health_collector.html`, `health_diagnostics.html`,
  `invariant_checks.html`, `protection.html`, `admin_alerts.html`,
  `recovery.html`. No sidebar on any of them (D17).
- Alerts: four sibling forms (save, `#alerts-pw-form`, `#alerts-run-form`,
  `#alerts-test-form` in the head); password/clear and run-now reach their
  forms through `form=`, never a nested `<form>`; every field keeps its
  `alerts_*` name.
- Recovery: bench two-pane picker (problem links `?problem=<key>#wizard`,
  chosen one `aria-current`, plan pane fixed height so nothing shifts), the
  Resolve undo inside the plan pane for the Resolve answer only, restore
  window `#restore` (the `/go/restore` target), rehearsal, history. Same
  forms, fields, confirms and `#recovery` outerHTML target as classic.
- `static/cc/health.css` (new): the bench's inline styles as `hl-*`/`rc-*`
  classes, the `aria-current` choice paint, and a busy state for the
  recovery/alerts keys keyed on htmx's `htmx-request` on the form.

## Omitted controls

None of the live pages' controls is dropped. Classic behaviour is unchanged
(no classic template or route edited).

## Departures

- Recovery's picker is links (the plan allows it), so the chosen problem is
  `aria-current`, not a radio.
- The terminal pages' confirms use `data-confirm-key` + `hx-confirm` (cc.js
  dialog).
- `data-busy` on keys is inert (cc.js has no generic handler); the busy text
  shows through `form.htmx-request` in `health.css` instead. Password and
  run-now keys live outside their (empty) forms, so they show no busy state.

## Tests (run once, dashboard venv)

- `dashboard/tests/test_ui_health_group.py` (new): **56 passed**. Covers
  every page in classic and terminal, no bracket control / em dash, every
  window folds with a named fold button, tab frames carry the `/go`
  anchors with fetched bodies, the three partials serve terminal markup and
  refuse when the group is off, dismiss returns health markup and writes
  nothing when off, `/go/{notices,collector,diagnostics,restore}` per
  variant landing on a rendered anchor, invariants/protection ack swap,
  alerts four forms / no nesting / save only `SETTING_KEYS`, recovery ids,
  forms and posts. All 12 `settings-health` templates are rendered under the
  `ui_variant` fixture (coverage hook satisfied).

## Hand-offs

- **P2 (`cc/fleet.html`)**: plan 7.1 row 5 wants home's problems, collector
  and diagnostics windows behind `{% if 'settings-health' not in ui_groups %}`
  until phase 8. Not edited here (P2's file).
- Not done (speed rules): terminal parameters on the classic suites
  (`test_health_page.py`, `test_invariants.py`, `test_protection.py`,
  `test_notices*.py`, `test_live_notices_2026_09_21.py`, recovery tests),
  the d-diag / d-db / `test_api.py` `/go` pin rewrites (R11), the census walk
  under the two group sets, the first-paint / load-triggered anchor scroll
  Chrome tests, and a screenshot pass.
- Phase 7: `recovery.py`, `notices`, `db.notice_href` still carry bracket
  copy; `cc_unbracket` strips it on labels only, not inside sentences.
