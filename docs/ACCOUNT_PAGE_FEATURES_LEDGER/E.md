# Group E: the companion (account page 2026-09-25)

Spec: `docs/ACCOUNT_PAGE_FEATURES.md` section 5 (and the wire in section 4).
Started from `f9d5176`. Not committed, no version bump (the orchestrator told
builders not to bump; the spec's companion bump in `config.py` `VERSION` and
`companion/pyproject.toml` is still owed at release).

## Built

- **NEW `companion/src/ccsync_companion/machine_settings.py`**
  - `ACCEPTS`, `REPORTED_RESTART_KEYS`, `LEDGER_NAME`, `FAILED_RETRY_SECONDS`
    as pinned in 5.1.
  - `apply_request(command, *, config_path, ledger_path, now)` per 5.2:
    malformed command -> `{}` (logged, nothing recorded); an id already
    `applied`/`refused` in the ledger is answered from it with no write; a
    `failed` one is re-tried only after 300 s; any key outside `ACCEPTS`
    (including `mode`) refuses the WHOLE request; `jobs_enabled` must be a
    bool; `jobs_kinds` must be a list of str, filtered to
    `capabilities.KNOWN_KINDS`, a non-empty all-unknown list refused, every
    kind (or `[]`) written as `""`, otherwise `", ".join` in known-kinds order;
    writes through `config_mod.set_value`, `False`/exception -> `failed`,
    `could not save config.toml`. Ledger written tmp + `os.replace`; it keeps
    the last answer plus the last 16 answers by id.
  - `report_section(app)` per 5.5, cached config.toml read by mtime+size,
    `{}` on any failure.
  - `change_sentence(applied_settings, by)`, the balloon, using
    `settings_window._kind_label` (deferred import).
  - Extra public helpers (used by `app.py`): `last_answer(ledger_path)`,
    `answer_for(ledger_path, request_id)`, `ledger_path_of(app)`,
    `STATE_APPLIED/REFUSED/FAILED`.
- **`reporter.py`**: `DashboardReporter.__init__` gains
  `get_machine_settings`; `_build_payload` adds `payload["machine_settings"]`
  on every tick (light included) when the getter returns a non-empty dict; a
  raising getter is logged and the section omitted.
- **`app.py`**: `CompanionApp._apply_machine_settings_request(resp)` (never
  raises, reporter thread), called from `_on_report_response_locked` right
  after `_apply_diagnostics_request`; the `DashboardReporter(...)` call passes
  `get_machine_settings=lambda: machine_settings_mod.report_section(self)`.
  Balloon (title `notify_title("fleet work settings changed")`) and a
  `log.warning` only for an id whose state was not already recorded before
  this call, so the standing command balloons once. A refusal or failure is
  logged, not ballooned.

## Deviations / interpretations (for the orchestrator and group D)

1. **YouTube gate.** 5.5 says include `youtube` "only when
   `ytdlp_manager.youtube_enabled(app.config)`", but that function also folds
   in this machine's own opt-out, which would make `downloads` always true.
   4.3 says "omitted when the site's youtube_download is off", so the gate is
   `site.feature_enabled("youtube_download")` and `downloads` =
   `ytdlp_manager.youtube_enabled(cfg)` (the opt-out, with the site already
   on). `signin_enabled` and `signin` are exactly as 5.5 says.
2. **Empty `set` `{}`** is refused (`the request named nothing to change`)
   rather than recorded as applied. The dashboard never sends it (3.6 rule 3).
3. **`jobs_kinds` as a non-list** is refused with
   `jobs_kinds must be a list of kinds of work` (5.2 gives no sentence).
4. `pending_restart` values are the NORMALISED on-disk values (bool, list of
   kind names, int minutes, float minutes), which match the types group D's
   filter keeps.
5. The refusal/`detail` sentences are machine-side words the page shows after
   `{machine} refused: `; they are lowercase-first to read in that slot.

## Tests

NEW `companion/tests/test_machine_settings.py` (64 tests): apply (applied,
one line changed and the rest byte for byte, read back; kinds encoding;
every kind -> `""`; `[]` -> `""`; all-unknown refused; `mode` / other keys /
bad types refused whole; malformed commands answered with nothing;
idempotent redelivery of applied and refused; new id applies; failed write
retried only after the floor; raising write; corrupt ledger; bounded
ledger), report_section (shape, lend-length and reminder coercions,
`pending_restart` only differing keys with disk values, kinds compared as
lists, mtime cache, YouTube omitted when the site has it off, status words
only with no cookie / reason / path, opted-out machine, ledger answer,
never raises), balloon copy (no em dash), reporter (light and heavy ticks,
raising getter omitted and the report posts, empty omitted, no getter), app
(garbage replies never raise nor balloon, one balloon per new id, refusal
not ballooned, reporter wired).

Run (companion venv): `test_machine_settings.py test_reporter.py
test_no_em_dash.py test_app_contract.py test_lane_b_resume_requests.py
test_diagnostics_upload.py` 319 passed; `test_app.py test_reporter_health.py
test_file_moves.py` 470 passed.

## Owed

- Companion version bump (`config.py` `VERSION` + `companion/pyproject.toml`)
  at release, withheld on the orchestrator's instruction.
- Group D: `docs/API.md` should describe the section as sent here (fields in
  4.3; `youtube` omitted when the site's `youtube_download` is off).
- Deploy order unchanged: dashboard first.

## Review round (2026-09-25)

1. MEDIUM, broken config.toml read as a pending change: FIXED.
   `_config_on_disk` returns None when `load_config` reports
   `_config_load_error` without `_config_from_backup` (all defaults, not
   the file), and is not cached then; `report_section` leaves
   `pending_restart` OUT in that case and when the read raises (it used to
   send `{}`, a positive "nothing waiting"). A copy rescued from
   config.toml.bak is still compared (it is what the next start runs on).
   Tests: `test_a_broken_config_with_no_backup_leaves_pending_restart_out`
   (the reviewer's jobs_enabled=false / peaks case),
   `test_a_broken_config_is_asked_again_every_tick`,
   `test_a_broken_config_rescued_from_the_backup_is_still_compared`,
   `test_a_raising_config_read_leaves_pending_restart_out`.
   **Owed to group D:** `db.store_machine_settings_section` stores
   `_clean_pending_restart(None)` = `{}` when the key is absent, so the page
   still shows "In effect." for this case. It should store NULL for an
   absent `pending_restart` and the page should say it cannot tell what is
   saved on that computer, rather than "In effect.".
2. LOW, unwritable ledger -> balloon per report, command never stops:
   FIXED. `_record` puts every answer in an in-process copy
   (`_mem_answers`, bounded like the file) before writing the file;
   `answer_for` / `last_answer` consult it first, so a redelivery is
   answered, nothing is rewritten, the report carries `applied` and the
   dashboard stops sending. A failed ledger write is logged. After a restart
   with the file still unwritable the ask is applied once more (same values)
   and ballooned once more; accepted. Tests:
   `test_an_unwritable_ledger_still_answers_redeliveries_from_memory`,
   `test_memory_and_file_agree_after_a_restart`,
   `test_app_unwritable_ledger_balloons_once`.
3. LOW, call site never exercised: FIXED.
   `test_the_report_reply_fan_out_applies_the_request` drives
   `app._on_report_response(reply)`. Checked by mutation: replacing the
   `app.py` call line with `pass` fails it.
4. LOW, mtime cache never really tested: FIXED. The `_forget_disk_cache()`
   call is gone from `test_config_is_reread_only_when_it_changes`; it now
   asserts exactly one re-read after the file changes and none after.
   Checked by mutation: a cache that never invalidates fails it.
5. LOW, kinds compared in order: FIXED. `_same_value` compares `jobs_kinds`
   as sets; the on-disk list is still what is reported. Test:
   `test_kinds_in_a_different_order_are_not_a_pending_change`.
6. LOW, two unlocked writers of config.toml: NOT FIXED HERE, outside group
   E's files. **Owed (orchestrator / whoever owns `config.py`):** a
   module-level lock around `config.set_value` (read, edit, write through
   the fixed `config.toml.tmp`, `os.replace`), which serialises the tray's
   `_spawn` writes and this module's reporter-thread write. Until then a
   simultaneous tray click and dashboard apply can lose one write or answer
   `failed` (retried after 300 s, so the dashboard's ask is not lost).

Run (companion venv): `test_machine_settings.py test_reporter.py
test_config.py` 305 passed (73 in `test_machine_settings.py`).
