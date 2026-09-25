# Group A: schema v58 + db.py (account page 2026-09-25)

Built against `docs/ACCOUNT_PAGE_FEATURES.md` sections 2, 2.1 and 7 (group A).
Nothing committed, no version bumped, KNOWN_BUGS untouched.

## What was built

All in `dashboard/src/ccsync_dashboard/db.py`.

- **`SCHEMA_V58`**, appended to `_MIGRATION_STEPS` as `(58, SCHEMA_V58)`:
  `user_profiles`, `machine_setting_requests` (both `CREATE TABLE IF NOT
  EXISTS`) and the six `machine_state.cfg_*` columns, exactly as the spec's SQL.
  `SCHEMA_VERSION` is 58; the list stays gapless.
- **Display names (F1)**: `DISPLAY_NAME_MAX_CHARS`, `DisplayNameError`,
  `normalise_display_name`, `get_display_name`, `display_names`,
  `set_display_name`, `clear_display_name`, `display_name_taken`.
- **Machine setting requests (F5)**: `MACHINE_SETTING_KEYS`,
  `MACHINE_SETTING_REQUEST_MAX_AGE_DAYS` (= the pushed update's 14),
  `request_machine_settings`, `machine_settings_request`,
  `withdraw_machine_settings_request`, `mark_machine_settings_delivered`,
  `answer_machine_settings_request`, `expire_machine_settings_requests`.
- **Reported settings (F6)**: `store_machine_settings`, `machine_settings_map`.
- **Audit action names**: every `AUDIT_*` constant of 2.1.
- **Existing functions changed**: `_MACHINE_STATE_TABLES` gains
  `machine_setting_requests` (so `forget_machine`/`forget_editor` delete it);
  `forget_editor` deletes the `user_profiles` row and reports
  `deleted["user_profiles"]`; `adopt_renamed_machine` carries a PENDING ask
  (`UPDATE OR IGNORE ... AND state='pending'`); `prune()` calls
  `expire_machine_settings_requests` beside `expire_machine_update_requests`.

## Additions beyond the pinned signatures (all backwards compatible)

- **`class DisplayNameTaken(DisplayNameError)`**: raised by `set_display_name`
  for the D-4 clash, so a route answers 409 for it and 422 for every other
  `DisplayNameError`. `except DisplayNameError` still catches it.
- **`set_display_name(..., other_usernames: Iterable[str] | None = None)`**
  (keyword): the pinned signature gives the function no way to see
  `settings.admin_users`. The function always checks every sign-in name the
  database knows (`known_editor_usernames` | `users` | `user_profiles`) and
  ADDS what the caller passes. Group C already passes it (their ledger).
- **The sentences as constants**: `DISPLAY_NAME_EMPTY`, `DISPLAY_NAME_TOO_LONG`,
  `DISPLAY_NAME_BAD_CHARS`, `DISPLAY_NAME_TAKEN`, verbatim from spec 3.2;
  `str(exc)` is always one of them.
- **`AUDIT_MACHINE_SETTINGS_EXPIRED = "machine.settings_expired"`**: the
  expiry writes an audit row (actor `system`), the same way REL-8's
  `machine.update_push_expired` does. Not in the spec's list; group F may want
  a label for it on the audit timeline.

## Behaviour notes other groups can rely on

- Profile keys are the sign-in name `strip().lower()` on every read and write.
- `normalise_display_name`: NFC, then whitespace runs collapse to one space.
  Tab/LF/CR/VT/FF count as whitespace; every other Cc (including the
  0x1c..0x1f separators `str.isspace()` accepts) and every Cf/Cs/Co/Cn is
  refused. Checks run empty, then characters, then length (64 code points).
- `set_display_name`/`clear_display_name` do NOT audit and do NOT commit (the
  route audits before/after, then commits), as the spec's 3.2 says.
- `request_machine_settings` cleans its input to the whitelist with the right
  types (bool / list of str; duplicates dropped; every kind stored as `[]`),
  and raises `ValueError` when nothing survives (the route refuses that first).
  It audits and does not commit. A merge's audit detail names the id it
  replaced (`merged_into`).
- `answer_machine_settings_request` lowercases the state word and bounds
  `detail` to 255; a repeat of an answer already final returns False and
  writes nothing (the companion repeats its ledger's last answer each report).
- `store_machine_settings` does the section cleaning itself as well (accepts
  intersected with the whitelist; `pending_restart` limited to the four keys
  with their types; numbers clamped 0..100000; `youtube` rebuilt from its four
  named fields, so no cookie or reason text can be stored). With no
  `machine_state` row nothing is written. `accepts` absent stores NULL, which
  `machine_settings_map` reads as `[]`.
- `machine_settings_map` returns only computers with `cfg_at` set (absent =
  never reported); `youtube` is None when not reported or unparseable,
  `pending_restart` is `{}`.

## Tests

NEW `dashboard/tests/test_account_db.py`, 67 tests: v58 on fresh / v57 / v50
databases, twice, an interrupted replay, the older-image refusal, gapless list;
normalise (NFC, whitespace, 64/65, RLO, ZWJ, ZWSP, controls, private use, CJK
and accented names); taken (sign-in name any case, display name, own name
allowed, NFC compare, local account, caller-passed admin); requests (unknown
machine, merge, replace answered, every kind as `[]`, delivered once, stale id,
applied/refused final + audited by the editor + not twice, failed/unknown word
stays pending, withdraw, expiry via `prune()`, unparseable JSON); forget
machine/editor; rename carries pending only; reported settings (None leaves
alone, cleaning, wholesale replace, clamps, wrong types, unparseable JSON, no
state row).

Run: `dashboard\.venv\Scripts\python.exe -m pytest tests/test_account_db.py`
67 passed. Every existing test file that exercises what changed (migrations,
forget, rename, prune; 20 files) : 678 passed, 1 skipped. A first run of that
set showed 10 failures in `test_dashboard_update.py` that did not reproduce
alone (66 passed) or on the rerun of the whole set; other groups were editing
`api.py` at the time.

## Owed

Nothing owed by A. For F: a timeline label for `machine.settings_expired` if
the audit page maps action names to words.

## Review round (2026-09-25)

1. FIXED, medium: `adopt_renamed_machine` lost a pending settings ask when
   the new name already held an ANSWERED row (applied / refused / withdrawn /
   expired), because the table is one row per (editor, machine) and
   `UPDATE OR IGNORE` skipped the move. Now, when the old name has a pending
   ask, the new name's finished row is deleted first; OR IGNORE only fires
   when both names hold a pending ask (the new name's, the newer, stands).
   With nothing pending at the old name the new name's history is left alone.
   Tests: `test_a_rename_carries_a_pending_ask_over_an_answered_one_at_the_new_name`
   (x4 states), `test_a_rename_keeps_the_new_names_own_pending_ask`,
   `test_a_rename_with_nothing_pending_leaves_the_new_names_history`.
2. FIXED, low: `set_display_name`'s taken check and upsert are now one
   critical section: `BEGIN IMMEDIATE` before the reads when the connection
   is not already in a transaction (legacy isolation only opens one before
   DML, so an open one already holds the write lock). A refusal rolls back a
   lock it took itself; one the caller opened is left to the caller (the
   route in account_api already rolls back on DisplayNameError). Tests:
   `test_set_holds_the_write_lock_across_the_check_and_the_upsert` (two
   connections on one file: the second waits/fails while the first is
   uncommitted, then is refused as taken after the commit, and holds no
   lock afterwards), `test_set_inside_the_callers_transaction_leaves_it_to_the_caller`.
3. NOT CHANGED, note: look-alike names (full-width, Cyrillic) pass the D-4
   check, which is NFC + casefold as the spec pins. NFKC or a confusables
   check is an owner decision, raised here for the orchestrator.

Run: test_account_db.py + test_account_api.py + test_account_page.py +
test_db.py: 234 passed; every test matching rename/adopt/forget/prune/
display_name across the suite: 110 passed. One run showed
`test_account_page.py::test_plan_rows_drive_the_existing_toggle_route`
failing; it passed alone and in the rerun (other groups editing at the time).
