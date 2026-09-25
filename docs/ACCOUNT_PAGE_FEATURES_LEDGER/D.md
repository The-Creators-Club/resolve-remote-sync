# Group D: the wire, dashboard side (account page 2026-09-25)

Spec: `docs/ACCOUNT_PAGE_FEATURES.md` §4.1, §4.2, §8 row D, hand-off 4 and 5.

## What was built

### `dashboard/src/ccsync_dashboard/api.py`

- **The report section** (§4.1): `MachineSettingsAppliedIn`, `MachineYoutubeIn`,
  `MachineSettingsIn` (all `_ReportSectionIn`, so numbers clamp and strings cut
  through `_bound_to_field_caps`; every state word a plain bounded `str`).
  - `accepts` is filtered in a `mode="before"` validator: only `str` entries in
    `db.MACHINE_SETTING_KEYS`, deduplicated. A non-string entry costs that entry,
    not the section; a non-list is left to fail the type check, which drops the
    section. `mode` can never be advertised into the whitelist (CR-88).
  - `pending_restart` keeps only `MACHINE_SETTINGS_RESTART_KEYS`
    (`jobs_enabled` bool, `jobs_kinds` list of str (<= 16 entries, <= 32 chars),
    `jobs_volunteer_minutes` int, `drive_reminder_minutes` number; `bool` is
    refused for the two numbers).
  - Registered in `_TOLERANT_SECTIONS` and in `ReportIn._a_bad_section_never_422s`'s
    field list; `ReportIn.machine_settings: MachineSettingsIn | None = None`.
- **The report handler** (§4.1): right after `db.store_machine_capabilities`,
  `db.store_machine_settings(conn, editor, machine, _declared_dump(section) | None, received_at)`
  and, when `applied.id` is set, `db.answer_machine_settings_request(...)`.
  `_declared_dump` rather than `model_dump()` so nothing but validated fields is
  re-serialised (the spec's "never raw client text"). Both land in the report's
  own commit, before the commands block.
- **The reply** (§4.2): `commands.machine_settings = {id, set, requested_by, requested_at}`
  after `diagnostics`, before `broll_ingest`; present only while the row is
  `pending`; `mark_machine_settings_delivered` + commit only when `delivered_at`
  is empty. `set` is filtered to `db.MACHINE_SETTING_KEYS` again on the way out
  (defence in depth: a row written by another door cannot carry `mode`).
- **D-15** (owner default: yes): `AUDIT_USER_PASSWORD_RESET = "user.password_reset"`
  and `_audit_password_reset(conn, admin, username, method, via=)`, called in
  `api_admin_set_password` (local and smb branches; the smb branch now commits
  for the audit row) and in `api_admin_create_user`'s NAS branch when a password
  was given (`via="create"`). Detail is `{"method", "via"}` only: no password, no
  length. Written before the commit, so a refused reset leaves no row.

### `docs/API.md`

- §2 `GET /api/v1/me`: open by exact match only; `/api/v1/me/...` needs a session.
- §2 `POST /api/v1/report`: the `machine_settings` row in the field table, a
  paragraph with a strict-JSON example and every field's rule, and the
  `commands.machine_settings` reply bullet + example key.
- NEW **§4a "Account"** (every route of spec §3: account view, display name,
  own password, own sessions, own sync keys, machine settings request/withdraw),
  with every `detail` sentence verbatim from the spec.
- §5 Users table: the D-15 audit note on `POST /admin/users/{u}/password` and the
  admin `PUT /admin/users/{username}/display-name` row.
- **Deviation:** the spec says "a new §5 Account". §5 is Admin and is cited as
  "API.md §5" from `docs/CONFIG.md`, `docs/RELEASE_FEED.md` and
  `docs/ZERO_TOUCH_PLAN.md`, so renumbering would break those references. The
  section is **§4a** instead (the existing 5a/6a pattern), placed before Admin.

### `dashboard/tests/test_machine_settings_wire.py` (NEW, 32 tests)

No section -> nothing reported; section stored; absent section leaves columns
alone; wholesale replace; clamping and cutting; unknown keys and `mode` ignored
in `accepts` and `pending_restart`; six wrong-type shapes dropped with the
report landing (lanes written, machine registered, last good section kept);
not on `undeclared_report_sections`; registered as tolerant. Command absent
when nothing asked; standing and delivered once; `applied` and `refused` stop
it on the same reply; a stale id does not; `failed` stays pending with detail;
`mode` stripped from a row written elsewhere; withdrawn not sent. Skew: a future
answer word accepted (200) and left pending; a companion with no section gets
409 from group C's route and never the command; a rolled-back companion still
gets the standing command. D-15: local reset audited without the password or
its length; refused reset and non-admin leave no row; smb reset + create-with-
password both audited. `docs/API.md`: §4a JSON blocks parse, the report example
parses as `MachineSettingsIn`, no em dash in §4a's table rows.

## Tests run

- `tests/test_machine_settings_wire.py`: 32 passed.
- Adjacent suites exercising what changed: `test_report_endpoint.py`,
  `test_capabilities_report.py`, `test_admin_users.py`,
  `test_admin_users_local.py`, `test_bug_hunt_2026_09_24_w2_d-api.py`,
  `test_no_em_dash.py`, `test_broll_ingest_report.py`,
  `test_music_ingest_report.py`, `test_report_ingest_health.py`: 339 passed;
  `test_bug_hunt_2026_09_11_dash_api_jobs.py`: 20 passed.

## Owed / notes for others

- **Version bump NOT done** (the builder brief said not to): `dashboard/pyproject.toml`
  is group D's per spec §0.3 and is left for the orchestrator.
- **Group F**: D-15's ui twin (`ui.partial_admin_set_password`,
  `POST /partials/admin/users/password`) should call the same audit. It can
  import `api._audit_password_reset(conn, admin, username, method, via="reset")`
  (or write `db.audit(conn, admin, "user.password_reset", username, {"method", "via"})`
  before its commit). The page create twin likewise with `via="create"`.
- The companion must send `accepts` entries exactly as `db.MACHINE_SETTING_KEYS`
  spells them; anything else is dropped silently by design.
- The orchestrator's CLAUDE.md paragraph (hand-off 6) can cite `docs/API.md` §4a.

## Review round (2026-09-25)

1. **`set` not checked against stored `accepts`**: FIXED, in a slightly
   different way from the one the reviewer suggested. `api.py` report reply:
   the command goes out only while EVERY key in it is in the machine's last
   reported `accepts` (`db.machine_settings_map`). If a rollback shrank
   `accepts`, the command is WITHHELD rather than trimmed. A trimmed set would
   let the companion answer `applied` to part of the ask while the page shows
   all of it as done. A withheld request stays pending (no `delivered_at`) and
   goes out again when `accepts` grows back, or it expires. A machine with no
   stored section keeps the whitelist-only behaviour, which is the old
   §4.6 row 3 case, and a `set` that filters down to nothing is not sent.
   Tests: `test_a_key_the_machine_no_longer_accepts_withholds_the_command`,
   `test_a_key_still_accepted_rides_a_shrunk_accepts`,
   `test_a_machine_that_accepts_nothing_now_gets_no_command`.
2. **Caps sliced before the whitelist**: FIXED. `MachineSettingsIn.accepts` and
   `.pending_restart` have no `max_length` now. The whitelist field validators
   bound the output (2 and 4 keys at most), and the report body limit bounds
   the input. Test: `test_known_keys_listed_late_in_a_long_list_are_kept`
   (40 unknown keys placed ahead of the known ones).
3. **`test_no_section_leaves_nothing_reported` was vacuous**: FIXED. The test
   now asserts that the report landed (a lane row), that `stored()` is None,
   and that all six `cfg_*` columns on the registered `machine_state` row are
   NULL.
4. **Oversized `applied` was never asserted**: FIXED. The old test now checks
   that the report landed and what `accepts` holds. The new test
   `test_an_oversized_answer_is_cut_and_an_oversized_id_matches_nothing`
   covers two cases. A 500-character id finalises nothing. A 500-character
   state is cut into an unknown word, so the request stays pending and its
   detail is cut to 255.
5. **API.md did not say to deploy the dashboard first**: FIXED. A paragraph
   after the section's storage note says to deploy the dashboard before the
   companions (spec §4.6 row 2, the SYS-3 banner). The `commands.machine_settings`
   paragraph now also documents the withhold rule from item 1.

Owed items are unchanged: the version bump goes to the orchestrator, and the
D-15 ui twin goes to group F.

Tests after this round: `test_machine_settings_wire.py` 37 passed.
`test_report_endpoint`, `test_capabilities_report`, `test_no_em_dash` and the
wire suite together: 218 passed. `test_account_api`, `test_account_db` and
`test_account_page`: 154 passed.
