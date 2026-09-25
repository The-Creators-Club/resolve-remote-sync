# G2a ledger: dashboard wire (legal-gap features, wave 1)

2026-09-25. Plan: `docs/LEGAL_GAP_FEATURES_PLAN.md` revision 2, Tier 1 + Tier 2a,
recommended defaults. Built on wave 0 (G0 `db.py`, G1b `transport.py`), neither
edited. No version bumped, nothing committed.

## What was built

### `dashboard/src/ccsync_dashboard/telemetry_fields.py` (NEW): the FIELDS copy (LG-1)

- `FIELDS`, `MASKED`, `OPAQUE_JOURNAL_PREFIX`, `opaque_journal_id` and
  `CATEGORIES` match G1a's `companion/.../telemetry_policy.py` byte for byte.
  G1a's module landed while this group was building, so its table is the
  contract and this copy was brought into line with it. Tests on this side
  pin FIELDS, MASKED, the prefix, the mask function and the categories equal
  to the companion's, loaded by path.
- `clean(names)`: the known names only, with `resolve_project` implying
  `media_tree`. It works without the database.
- `strip(payload, withheld)`: removes or masks fields in place, on a dict or on
  a parsed `ReportIn`. A removed model field goes back to its default (None or
  ""). It never raises, and it returns the paths that held something.

### `dashboard/src/ccsync_dashboard/netclass.py` (NEW): `report_via` (LG-4)

- A port of `transport.classify` and `host_is_local`, including the
  review-round rules: an IP literal is judged first, a dotless numeric label
  is read as IPv4, reserved names are local, and a name counts as public only
  when every resolved address is global.
- `report_via(scheme, host)` returns `https`, `http_local` or `http_public`.
  It returns None when the result cannot be told, and None is never written.
  Loopback is recorded as `http_local`.
- `request_report_via(settings, request)` trusts X-Forwarded-Proto only from
  `auth.trusted_proxy`. Otherwise it uses the socket's own scheme, and it
  classifies the Host header.

### `api.py`

- **Wire (plan 3.2).**
  - `EulaIn`, a tolerant section bounded like the others.
  - `ReportOptoutsIn`, a `RootModel[list[str]]`. Unknown names and
    non-strings are dropped one entry at a time, and a non-list drops the
    whole section.
  - Both are registered in `_TOLERANT_SECTIONS` and in
    `_a_bad_section_never_422s`, and declared on `ReportIn` as
    `report_optouts` and `eula`.
- **`api_report` strips before any write (LG-1, correctness H3).**
  - `_report_withheld` returns `site ∪ own`.
  - `site` comes from `site_store.telemetry_policy(conn, settings)` (G2b).
    It falls back to `meta['site_report_optouts']` (the set last applied)
    when that function is missing or raises. A broken policy read never lets
    withheld data back in.
  - `own` is the list the report sent. When the key is absent, `own` is the
    **stored own list** (`report_optouts_local`, G0 hand-off 9), not the
    stored union, so a site switch turned back on does not stay on.
  - `telemetry_fields.strip(payload, …)` runs before the first section write.
- **`_record_legal_sections`** runs after the section writes and before the
  report's first commit. It calls `db.apply_report_optouts`, then
  `db.set_machine_report_via` (which writes only on a change), then
  `db.set_machine_eula`. Each call is best effort on its own and cannot cost
  the report.
- **Upload-only preparing rule (correctness H4).**
  - A machine that withholds `local_manifest` no longer gets a "getting ready"
    row for an upload-only tick.
  - It gets the `not_reported` / `uncertain` zero-file upload row instead,
    which G0 builds for full ticks only (see departure 3).
  - A probe with the rule disabled showed the permanent preparing row
    returning.
- **The first claim, NEW PROJECT and sticky auto-map are not worked around.**
  Once `resolve_project` is stripped, these three stop on their own, as the
  plan's "costs" wording says. A test asserts that no `project_roots` row is
  created and that no `resolve_project_unmapped` is returned.
- **`delete_user_everywhere` (LG-3, G0 hand-off 2).**
  - `was_admin` is computed before step 1, from `auth.is_admin` or the local
    account's role, and passed to `db.forget_editor`.
  - The `user.delete` audit row's subject is now the pseudonym, and its
    `machines` detail is a count.
  - The new `_forget_elsewhere` runs after `_purge_user_credentials`:
    - `db.delete_revoked_report_tokens`, then a commit;
    - `SessionStore.purge_user(username)`;
    - `ytdl.forget_requester(username)` (G4);
    - `subject_data.forget_shares(username)` (G3).

    The two cross-group calls are looked up at run time and skipped when
    absent. Every failure becomes a line in `warnings`, never a 500.
  - The route's `deleted` block gains `sessions_deleted` and
    `report_tokens_deleted`. Both are additive keys.

### `sessions.py`

- `SessionStore.subject_rows(username)` returns the person's `auth_sessions`
  without the sid, and their username-keyed `login_attempts`. IP-keyed rows
  are never included.
- `SessionStore.purge_user(username, revoked_only=False, now=None)` has two
  modes:
  - `revoked_only=True` is erase. It deletes revoked, idle-expired and
    absolute-expired sessions, and past failures **except** a row whose
    `blocked_until` is still in the future (safety L1). A live session
    survives.
  - The default is delete. It removes every session and every username
    throttle row.

  Both modes return counts, and both run through the store's own connection,
  after the caller's commit.

## Note J: the answer for G1a

The dashboard's undo keys on the **journal id** (`api_machine_resolve_undo`
matches `journal`, and the companion resolves it through `session_by_id`).
**The id itself carries the project name, though:** it is
`<resolve_journal.project_slug(name)>/<file>`, so sending `project: ""` would
not withhold the name.

G1a reached the same conclusion independently. It removes `project` and masks
`id` to `withheld:project/<file>`, which the companion maps back, so undo
keeps working for a companion that has the switches. This copy does the same.
For an older build under a site switch, the dashboard masks too. That build
answers "not found", so undo from the dashboard stops working for that
computer and its project name is not stored.

**For G9:** the undo cost applies only to computers whose companion predates
the switches. Plan 8.1's parenthetical ("cannot be undone from the dashboard")
is not needed for current builds.

## Departures from the plan, and why

1. **FIELDS follows G1a's table, not the plan's §4.1 wording.**
   - `sync_guard.stray_projects` and `sync_guard.moved_project_dirs` are
     withheld whole. The plan had them at top level, and they are really under
     `sync_guard`.
   - `resolve_journals[].id` is masked. There is no count-preserving
     variant: the stray-folder count and the moved-folder count read as
     "not reported", never zero.
   - `sync_conflicts.count` stays.
2. **The strip is a generic dotted-path walker over the parsed pydantic
   model**, so the one table drives both sides. A test checks that every FIELDS
   path resolves to a declared model field. Without that check, a typo would
   strip nothing while the wording claims it is withheld.
3. **The upload-only "not reported" row is built in `api.py`.** G0's
   `_backlog_not_reported` reads full ticks only
   (`fetch_machine_selections(for_enforce=True)`), and the plan says the row
   shows "not reported".
4. **`netclass` caches a DNS verdict for 300 s, not 30.** It only labels a
   record here, and the lookup is on the report path. This is documented in
   the module.
5. **LG-5 tests (stored, absent keeps it, malformed dropped) are in
   `test_report_optouts.py`.** The plan names no G2a test file for LG-5.
   The delete-path tests are in `test_sessions_purge.py`.

## Tests run (only the files this group created)

`dashboard/.venv` pytest, all four together: **112 passed** (5.6 s).

| File | Passed | What it covers |
|---|---|---|
| `test_report_optouts.py` | 24 | control; old build stripped under a site switch; clear on a later report; conflict count kept; policy failure falls back to the applied set; own switch; `resolve_project` implies `media_tree` and masks journals; absent key keeps the own list; `[]` switches back on; unknown names dropped; 3 malformed shapes land; empty list is not an old build; upload-only row; strip on a dict; paths resolve on the model; categories equal db's; FIELDS and masks equal the companion's; em-dash scan; LG-5 stored and absent-keeps, plus 3 malformed shapes |
| `test_report_via.py` | 74 | 58-row parity with the companion's `classify`; `host_is_local` and the constants; 13 `report_via` rows; trusted and untrusted X-Forwarded-Proto; broken request; route writes, change-only writes (a spy sees `[True, False, False]`), untrusted proto ignored, unclassifiable Host writes nothing and the report lands |
| `test_report_model_pin.py` | 4 | ReportIn, CapabilitiesIn and SyncGuardIn field sets pinned; every field in FIELDS or `NOT_PERSONAL`, with no stale or overlapping entry |
| `test_sessions_purge.py` | 10 | erase keeps the live session; lockout kept and lapsed one dropped; IP rows untouched; delete scope; pre-schema no-op; export has no sid; the delete route (sessions and revoked tokens deleted, pseudonym audit subject, admin actor kept and editor actor pseudonymised, ytdl and shares called, and a failure is a warning with no em dash) |

Not run, per the owner's 2026-09-03 rule (the overseer runs them centrally):
the suites that exercise the changed routes: `test_admin_delete.py`,
`test_admin_users_local.py`, `test_machine_settings_wire.py` and the other
report and transfers-view tests.

**Watch in the central run:** the `user.delete` audit detail's `machines` is
now a count, and its subject is the pseudonym. No test file greps for it,
except G0's.

## Hand-offs owed

1. **G0 (`db.py`).** `_clear_categories` blanks `project` in stored journals
   but keeps their real ids, and an id carries the project name. It should
   also rewrite each stored id with the same mask
   (`telemetry_fields.opaque_journal_id`, or its own copy). The report path
   already replaces a reporting machine's list with masked ids. Only
   `apply_site_optouts` against **offline** machines leaves the names in
   place.
2. **G0 (`db.py`), optional.** `_backlog_not_reported` could include
   upload-only ticks. The row is emitted in `api.py` for now (departure 3).
   If G0 adds them, the `(e, slug) in queued_pairs` check keeps the result
   free of duplicates.
3. **G2b.**
   - `site_store.telemetry_policy(conn, settings) -> set[str]` is called by
     name. Until it lands, the report path uses the last applied set in
     `meta['site_report_optouts']`.
   - G2b also needs G0 hand-off 7 (apply at boot), so that a `site.toml`-only
     policy is enforced on arrival and on disk.
4. **G3 and G4.** `delete_user_everywhere` calls
   `subject_data.forget_shares(username)` and `ytdl.forget_requester(username)`
   with **one argument**, after the commit. The return value is not used by
   the route. Raising is safe, because it becomes a warning.
5. **G1a.** The dashboard's pin of FIELDS, MASKED and `opaque_journal_id`
   against yours is `dashboard/tests/test_report_optouts.py`. Change both
   together.
6. **G9 (docs).**
   - Note J as above: the undo cost is limited to pre-switch companions.
   - `report_via` records Tailscale Serve traffic as `http_local`, not
     `https`, when Serve reaches the container from an address that is not
     in `DASH_TRUSTED_PROXIES` (the bridge gateway). The Settings count can
     then overstate plain-http computers on such a deployment. This is
     informational only, and no alert fires on `http_local`.
7. **Overseer.** Run the central gate. The files most likely to notice these
   changes are `test_admin_delete.py`, `test_admin_users_local.py`, the
   report-path suites and the transfers-view tests.

## Review round (2026-09-25)

Six points from the adversarial reviewer. Each was checked against the code before any change.

1. **Fixed (HIGH): a delete now reaches client folders and the YouTube ledger.**
   - The reviewer was right: `_forget_elsewhere` called `forget_shares(username)`, and G3's real function raises `ForgetSharesFailed` with neither `stand_in` nor `conn`. Every delete on a dashboard with client folders kept the real name and showed a false warning.
   - `ytdl.forget_requester(username)` only worked through `DASH_DB_PATH`.
   - Both now get the dashboard connection and the stand-in from `forget_editor` (`result["fleet"]["pseudonym"]`, falling back to `db.pseudonym`). The call is `forget_requester(username, conn=conn, pseudonym=...)` and `forget_shares(username, stand_in=..., conn=conn)`.
   - Any transaction left open on `conn` is committed after each call, or rolled back on a failure.
   - My hand-off 4 ("one argument each") is withdrawn.
   - Test: `test_the_real_forget_shares_takes_the_name_out_of_client_folders` uses G3's real `forget_shares` against a temp `client_shares.db`. It checks both columns, a colleague's row left alone, no warning, and that ytdl got `conn` and the same stand-in.
2. **Fixed (MEDIUM): an old build's diagnostics bundle is not stored under a site switch.**
   - The new `_diagnostics_withheld_unredacted` takes the site's content categories (`resolve_project`, `local_manifest`, `media_tree`) and applies them when the machine has no own list on record. That means `report_optouts_local IS NULL`, or no state row yet, which is how a companion that predates the switches looks. Such a companion never redacts.
   - `api_diagnostics` then stores a stub that names the withheld categories and says to update the companion, and answers `stored: false` (an additive key). The audit detail carries `withheld`.
   - A stub rather than a refusal, so an admin's "ask why" is still answered (the request clears) and does not read as a lost reply.
   - A build with the switches, even one with `[]`, is stored as sent, because it redacts its own bundle (`app._redact_diagnostics`). `input_idle` alone never touches a bundle.
   - Tests: `test_point2_*` (3).
3. **Fixed (MEDIUM): the Host lookup is out of the transaction, bounded in time, bounded in count, and cached in a capped map.**
   - Out of the transaction: `api_report` computes `report_via` after the credential checks (so a stranger's Host buys no lookup) and before `clear_report_refused`, the first write. `_record_legal_sections` now takes `via` and no longer takes `request` or `settings`.
   - Bounded in time: in `netclass`, a lookup runs on a daemon thread with `RESOLVE_TIMEOUT_SECONDS` = 1.0.
   - Bounded in count: at most `RESOLVE_MAX_INFLIGHT` = 4 lookups run at once, through a non-blocking semaphore.
   - A timeout, or no free slot, is doubt, which gives `http_local`, and that answer is not cached.
   - Capped cache: `RESOLVE_CACHE_MAX` = 256. Expired entries are evicted first, then the soonest to expire.
   - Tests:
     - `test_point3_the_host_lookup_runs_before_the_reports_first_write` checks the order of calls. A lock probe was tried first and was flaky, because the collector thread takes the write lock by itself.
     - `test_report_via.py`: `test_a_slow_lookup_is_doubt_not_a_stall` and `test_the_cache_is_capped`.
4. **Rejected as described, rule tightened anyway (LOW).**
   - The reviewer's case cannot occur. `build_transfers_view` reads `db.fetch_machine_selections`, which already resolves the unassigned bucket to each of the person's registered computers that has no plan of its own. The upload-only tick in that case is `(editor, DESK)`, which DESK's manifest clears. `machine == ''` survives only for a person with no registered computer.
   - `test_point4_the_unassigned_bucket_follows_the_machines_it_stands_for` pins this, and passes on the old code and the new.
   - For that remaining case, "ANY of the person's computers withholds" was still the wrong rule. `_upload_only_tick_withheld` now requires EVERY computer the bucket stands for to withhold. Those are the computers with reported state, no plan of their own, and not wired.
   - Test: `test_point4_a_bucket_only_withholding_machines_stand_for_is_not_reported`.
5. **Fixed (LOW): `strip` fails closed.**
   - A path that raises is logged at ERROR and its whole top-level section is dropped. On a model, the drop writes the field's default (or its `default_factory` value) through `__dict__`, which bypasses a `validate_assignment` or frozen `__setattr__`.
   - If even that fails, `telemetry_fields.StripFailed` propagates. The report is then refused with a 500 rather than stored with withheld data in it. The companion retries; nothing raises today.
   - Tests: `test_point5_*` (3): a model, a dict, the raise, and the route storing no `missing_clips`.
6. **Fixed (LOW):** `deleted.sessions_deleted` is now an int (`auth_sessions`), and `deleted.login_attempts_deleted` is added beside it. The existing route test was updated.

### Tests (this round, only the files this group owns)

`dashboard/.venv` pytest:
- The four G2a files together: **122 passed, 2 failed**. The two failures are `test_the_fields_copy_equals_the_companions` and `test_the_masks_equal_the_companions`. See hand-off 8.
- The existing suites that exercise the changed routes were run once to check the signature change: `test_auth`, `test_diagnostics`, `test_upload_only`, `test_cr311_queue_says_on_hold`, `test_multi_machine`, `test_presence`, `test_legal_db`, `test_hardening`, `test_unicode_paths`, the three bug-hunt files, `test_admin_delete`, `test_admin_users_local` and `test_report_endpoint`. All passed: 433 passed with the G2a files included (the same 2 failures), and 147 passed in the admin/report set.

### Hand-offs added this round

8. **G1a / overseer.**
   - While this round ran, the companion's `telemetry_policy.py` gained `MASKED["resolve_undo_applied[].detail"] = "undo_detail"` (`redact_undo_detail`). For a moment it was also syntactically broken (line 131), so it was being edited while I worked.
   - The dashboard's copy (`telemetry_fields.py`) does not have that mask yet, so this group's pin tests fail as designed.
   - Once G1a's table settles, port `redact_undo_detail` into `telemetry_fields._MASKS` as `undo_detail` and add the path. A test already checks that every FIELDS path resolves on `ReportIn`, so it confirms `resolve_undo_applied` is declared there. I did not chase a table that was changing under me.
9. **G9 (docs/API.md).**
   - `DELETE /admin/users/{username}` `deleted` gains `sessions_deleted` (int), `login_attempts_deleted` (int) and `report_tokens_deleted` (int).
   - `POST /api/v1/diagnostics` may answer `stored: false`, meaning a stub was stored because the site withholds content categories and the companion predates the switches.
   - The PRIVACY / TELEMETRY wording can say that a pre-switch companion's diagnostics bundles are not kept under a site switch.
