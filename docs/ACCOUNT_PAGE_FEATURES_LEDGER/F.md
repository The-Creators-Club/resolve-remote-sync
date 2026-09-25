# Group F: the /account page + display names (account page 2026-09-25)

Built from `docs/ACCOUNT_PAGE_FEATURES.md` sections 3 (the partial halves),
3.7, 6.1, 6.2, 7 (group F) and the group F row of section 8. Owner decisions
D-1..D-15 taken at their recommended defaults. Nothing committed, no version
bumped, KNOWN_BUGS untouched.

## What was built

### The page and its partials (`account_ui.py`, NEW)

`router = APIRouter(default_response_class=HTMLResponse)`, registered by
group C's `app.py` edit before `ui.router`. Every partial calls C's service
function, never `account_password` or `db` writes directly:

| Route | Calls | Answers |
|---|---|---|
| `GET /account` | `account_api.build_account_view` | the page; `?as=` ignored (sidebar pinned to the session user too); `?changed=password&others=<n>` parsed as an int, clamped 0..999, anything else renders nothing |
| `GET /partials/account/computer?machine=` | `build_account_view` | one computer (polled 30 s and on `account-refresh`); a machine not in the signed-in person's list answers an empty 200 |
| `GET /partials/account/sync-keys` | `build_sync_keys_view` | plain `def` (may call the NAS), loaded `hx-trigger="load"` |
| `POST /partials/account/display-name` | `set_own_display_name` | the YOU panel with a result line; a refusal keeps what was typed |
| `POST /partials/admin/users/display-name` | `set_user_display_name` | the Users panel with notice/error (403 for a non-admin) |
| `POST /partials/account/password` | `change_password` (in the threadpool) | refusal: a result line into `#account-pw-result`; success: `HX-Redirect: /account?changed=password&others=<n>` with the rotated cookie on the response |
| `GET /partials/account/sessions` | `list_own_sessions` | the panel (polled 30 s) |
| `POST /partials/account/sessions/revoke` | `revoke_own_session` | the panel + result |
| `POST /partials/account/sessions/revoke-others` | `revoke_own_other_sessions` | the panel + result |
| `POST /partials/account/machines/settings` | `ask_machine_settings` | the computer's fleet-jobs fragment + result |
| `POST /partials/account/machines/settings/withdraw` | `withdraw_machine_settings` | the same fragment |

Expected refusals are 200 with the service's own sentence; 401/403 re-raise.
The fleet-jobs controls are two forms with one key each (a click asks only for
what it changed); the kinds form refuses the last untick with the 4.8 sentence
both in `account.js` and on the server (an empty list is never sent). Any
other field (e.g. `mode`) is passed through to the service, which refuses the
whole ask with its 422 sentence. Presentation helpers: `request_status` (the
4.5 lines), `decorate_computer`, `dom_id` (a digest, since machine names are
matched exactly and may hold spaces), `_readonly_rows` (F6, D-14 hides the
YouTube rows when the site has YouTube downloads off).

### Templates (NEW)

`account.html` (head, admin note, YOU, CHANGE YOUR PASSWORD, YOUR COMPUTERS,
YOUR WIRED COMPUTERS, YOUR SETTINGS table, SIGNED-IN BROWSERS),
`partials/account_you.html`, `account_password.html`, `account_computer.html`,
`account_jobs.html` (the fleet-jobs fragment an ask answers with),
`account_sessions.html`, `account_sync_keys.html`, `account_result.html`.
The password and YOU panels are never inside a polling element (tested).
Plan buttons post to the EXISTING `/partials/selection/{editor}/{slug}/toggle`
with `?machine=` (and `&mode=`), `hx-swap="none"`, then fire `account-refresh`
on the computer's panel; the untick carries the DASH-8 style confirm and
switching an upload-only row to full carries the UX-1 capacity sentence
(`api.tick_capacity_warning`). Admins get the existing `[ UPDATE NOW ]` and
`[ ASK THIS COMPUTER WHY ]` forms the same way.

### Display names (6.2)

- `ui.py`: the `shown_as` filter (`@pass_context`, falls back to the value),
  `_render` puts `display_names` (via `account_api.display_names_for`,
  imported at call time, `{}` on any failure) and `session_shown_as` in every
  signed-in render; nothing for an anonymous render.
- `topbar.html`: the three session labels are `session_shown_as` linked to
  `/account` with `title="signed in as <user>"`; the drawer foot gets
  `[ YOUR ACCOUNT ]`. `/partials/topbar` gets it through `_render`.
- `fleet_grid.html` (both EDITOR cells): name, sign-in name muted beneath when
  they differ, title "signed in as".
- `admin_audit.html`, `plan_changes.html` (WHO and EDITOR): `| shown_as`, the
  sign-in name in `title`.
- `admin_users.html`: a SHOWN AS column with the F1a form in both the local
  and NAS account tables.
- `cards_landing.py`: `opened_phrase`, `last_in_phrase` and the close prompt
  use display names; new `occupants_shown` and `opened_by`; the JSON keys
  (`occupants`, `last_in`) stay sign-in names. A display name spelt "you",
  "somebody", "someone" or "nobody" falls back to the sign-in name, so it
  cannot read as the phrase's own word. `cards_landing.html`: occupants by
  name, sign-in names in the `title` of the three phrases.

### D-15 (the ui twin)

`ui.partial_admin_set_password` writes `user.password_reset` through group
D's `api._audit_password_reset` (imported at call time) before the commit,
both branches (local, NAS). Nothing about the password is recorded.

### Static

`static/style.css` (an `account-*` block, existing vocabulary only; the design
bench's `account.css` is not copied), `static/mobile.css` (one column of
computers and one-column forms at phone width), `static/account.js` (NEW:
password counter/match/show, the two browser-side password refusals via
`htmx:confirm`, the last-kind guard, and the add-project row, which builds the
toggle URL and asks the UX-1 question before a full tick).

## Tests

`dashboard/tests/test_account_page.py` (NEW, 45 tests): page for editor and
admin (admin note and admin buttons only for the admin), `?as=` ignored, every
panel present, password and YOU panels not inside any `every ...` trigger,
oidc shows no form (issuer host only, emergency note only for admins),
`?changed=` values (valid, clamped, `abc`, a script, a missing count), empty
states, display-name partial saves/refuses (taken, RLO, 65 chars, clear) and
needs CSRF and a session, the admin F1a partial (403 for an editor, 404
sentence, audited as `user.display_name` by the admin), the name in the
topbar (+ `/partials/topbar`), fleet grid, audit, plan changes (WHO and
EDITOR), Users page, the `shown_as` filter fallbacks, Cards landing phrases
(including the "You" impersonation guard and the keys staying keys),
sessions panel (one THIS BROWSER, no SIGN OUT on it, 12-hex handles only,
revoke one / others, the refusals, CSRF), sync keys partial, password partial
(refusal is a result line with no redirect; success redirects with a new
cookie and signs the other browser out; nothing typed in the logs), D-15
audit row with no password, F5 ask from the page (pending line, WITHDRAW,
box shows what was asked), every-kind stored as `[]`, last kind refused with
nothing stored, `mode` refused, someone else's computer 403, an old companion
(cfg_* NULL) gets the 4.7 sentence and no controls, F6 rows and D-14, the
computer partial, every 4.5 line, `dom_id`, plan rows posting to the existing
toggle route (a machine name with a space), a wired computer with no plan
controls, and every F write refusing without CSRF and absent from every
exemption list.

Run: `tests/test_account_page.py` 45 passed. Also run, because they render
what F changed: test_admin_* (5 files), test_bug_hunt_2026_09_11(_b)_dash_mounts_ui,
test_bug_hunt_2026_09_24_w2_d-cards / d-ui, test_cards_capability / picker /
pool, test_fleet_audit, test_fleet_grid_declutter_2026_09_11, test_fleet_halt,
test_home_layout, test_mobile_admin / css / fleet, test_no_em_dash, test_pwa,
test_sessions, test_settings_hub, test_site_manifest_consumers,
test_sweep_2026_09_04_copy / copy_plan / dash_ui,
test_templates_wave3_2026_09_04, test_theme_css, test_topbar_partial,
test_ui_filters, test_tab_memory, test_help_page, test_account_api:
all green except ONE failure that is group A's (below).

## Owed / notes for other groups

- **Group A**: `test_sweep_2026_09_04_copy.py::test_no_retired_word_in_python_copy[db.py]`
  fails on `db.py:12124` `"no machine setting to request"` (CR-181 retired
  word "machine"; say "computer", or make it a log/docstring). Not F's file.
- **Group C**: the view has no sync-drive fact for a remote computer; the
  panel shows `pc.drive` if C ever adds it (wired computers show the site's
  drive letter). `why` is the grid's `why` dict and the page reads its
  `sentence` and `informational`.
- **Vocabulary**: the mock's "wired rig(s)" is a CR-179 retired word in
  rendered copy, so the page says "computers wired to the server" /
  `[ YOUR WIRED COMPUTERS ]`. The spec's 6.1 wording should follow.
- The Users panel polls every 30 s, so a SHOWN AS name half typed there can
  be wiped by a poll, exactly as the existing SET PASSWORD boxes beside it
  can. Left as the panel's existing behaviour.
- Orchestrator: the CLAUDE.md invariant paragraph (section 8 hand-off 6).

## Review round (2026-09-25)

The adversarial review's four points, all fixed. Files: `dashboard/src/ccsync_dashboard/account_ui.py`,
`dashboard/templates/account.html`, `dashboard/tests/test_account_page.py`.

1. **Password changed, no confirmation when the count is unknown.** `_changed_line`
   now returns `{"others": None, "others_unknown": True}` for a missing or unreadable
   `others`, and `account.html` prints "Password changed. Your other browsers may still be
   signed in: check SIGNED-IN BROWSERS below, or use SIGN OUT EVERYWHERE." The partial
   still redirects to `/account?changed=password` when B's
   `rotate_after_password_change` answers None (no store, or the sign-out failed); a
   bool is not taken as a count. The old test that pinned "no count prints nothing" is
   replaced: `test_changed_line_without_a_count_still_confirms` (4 queries, incl. a
   script payload) and `test_password_partial_success_without_a_count_still_confirms`
   (None / garbage / True from the service). Any other `changed=` word still prints nothing.
2. **"In effect." without checking the running value.** `request_status` now says
   "In effect." only when `_running_matches`: every asked key equals the running value
   (`jobs.enabled` / `jobs.kinds`; `[]` and "every kind" are one answer; NULL or an
   unknown key is never a match). Otherwise the applied row keeps the "saved it. It takes
   effect the next time CCSync starts there." line. "The row is quiet": the green line
   shows for `IN_EFFECT_SHOWS_FOR` (10 min) after `answered_at`, then the row returns
   None; a row still waiting on a restart never goes quiet. Tests:
   `test_in_effect_needs_the_running_value_to_match`, `test_in_effect_goes_quiet`.
3. **NAS call on the event loop.** `partial_admin_user_display_name` runs
   `build_admin_users_view` through `run_in_threadpool`. Test:
   `test_admin_display_name_partial_asks_the_nas_off_the_event_loop` (spies the call and
   asserts no running loop on its thread; fails against the old inline call).
   `ui.partial_admin_set_password` still calls it inline: not F's file, noted for its owner.
4. **Per-project queries on every refresh.** `_add_options` reads
   `db.project_proxy_bytes_map` once and `db.machine_free_bytes` once per computer, and
   builds the sentence with `health.capacity_warning` (the function
   `tick_capacity_warning` uses), so the words cannot drift. Test:
   `test_add_options_capacity_sentence_matches_the_tick_helper` (a tight project, a small
   one and an unwalked one each match the helper; unwalked stays silent).

Tests re-run: `test_account_page.py` 54 passed. With `test_no_em_dash.py`,
`test_sweep_2026_09_04_copy.py`, `test_topbar_partial.py`, `test_admin_users*.py`,
`test_fleet_audit.py`, `test_account_api.py`: 686 passed, 1 skipped, 1 failed, the failure
being group A's `db.py` retired word ("no machine setting to request"), unchanged and not F's.
