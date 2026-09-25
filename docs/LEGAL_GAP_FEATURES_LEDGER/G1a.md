# G1a ledger: companion telemetry switches, address rule, EULA section, About

2026-09-25. Plan: `docs/LEGAL_GAP_FEATURES_PLAN.md` revision 2, Tier 1 + Tier 2a,
recommended defaults. Built on wave 0 (G0 `db.py`, G1b `transport.py`) in the
working tree. No version bumped, nothing committed.

## What was built

### `telemetry_policy.py` (NEW, leaf module: no package imports)

- `CATEGORIES`, `CONFIG_KEYS` (`report_resolve_project`, `report_local_manifest`,
  `report_media_tree`, `report_input_idle`), `OPTOUTS_KEY = "report_optouts"`.
- `FIELDS`: the plan's 4.1 table as dotted paths (`a.b`, `a[].b`). Every path
  is REMOVED from the payload (all are optional on the dashboard's models),
  except `MASKED = {"resolve_journals[].id": "opaque_journal_id"}` (see note J
  below).
- `local_switches(cfg)`, `site_switches(site)`, `site_withheld(site)`,
  `effective(cfg, site)` (local AND site; `resolve_project` off forces
  `media_tree` off; the only copy of the rule), `withheld(eff)` (sorted).
- `strip(payload, eff)`: copy-on-write (never edits a getter's cached dict),
  never raises, leaves odd shapes alone.
- `opaque_journal_id(id)`, `redact_text(text, names, roots)` (paths under a
  root become `<root>/<file>`, whole-word names become `<project>`, names
  under 3 characters skipped, a root never matches inside `http:`).

### `config.py`

- `DEFAULTS`: the four `report_*` keys, all `True`, with the "never
  remote-controlled" comment (safety L2). `DEFAULT_TOML_TEXT` and
  `config.example.toml` document them.
- `dashboard_url_problem(url) -> (level, sentence)` on `transport.classify`;
  constants `DASHBOARD_URL_PUBLIC_HTTP`, `DASHBOARD_URL_LOCAL_HTTP` (the plan's
  words, no em dash).
- `validate_config(cfg, for_save=False)`: `http_public` is an **error only
  when `for_save=True`**, a warning otherwise; `http_local` is a warning; a
  wrong-typed `report_*` key is a warning.

### `site.py`

- `TELEMETRY_KEYS` whitelist; `normalise()` now carries `telemetry` (only a
  real JSON `false` is off; absent or garbage is on). Round trip fetch ->
  normalise -> `save_site` -> `cached_site` tested.

### `reporter.py`

- New optional ctor args `get_eula`, `get_site` (default `site.cached_site`).
- `_build_payload` ends with `_withhold()`: `telemetry_policy.strip` LAST,
  then `report_optouts` (sorted, **always**, empty included).
  `telemetry_effective()` is public; the app reads it.
- `eula` section on heavy ticks only.
- `_note_failure`: a `transport.CleartextRefused` sets
  `last_status = CLEARTEXT_REFUSED_STATUS` and toasts
  `CLEARTEXT_REFUSED_LINE` once per run (pinned equal to
  `identity.CLEARTEXT_REFUSED_MESSAGE`).

### `capabilities.py`

- `build(..., withheld=())`: collects exactly as before (cache keeps the
  real values), then `_withhold` blanks `resolve.project` to `""` and sets
  `idle_seconds = None` for `input_idle`, and also whenever `jobs_enabled`
  is false (D4).

### `app.py`

- `telemetry_withheld()` (reporter's answer, else config + cached site).
- `job_capabilities` passes `withheld`.
- `_refresh_media_tree_once`: runs in full (stale-bridge recovery, relink,
  classify); with `media_tree` withheld only the reporter's cache stays `{}`.
- Module-level `real_journal_id()`: maps `withheld:project/<file>` back to
  the one local journal with that file name (refuses if 0 or 2+); called in
  `_apply_resolve_undo` before `apply_undo`.
- `build_diagnostics` -> `_redact_diagnostics`: with any of
  `resolve_project`/`local_manifest`/`media_tree` withheld, the whole bundle
  runs through `redact_text` (open project name; `local_root`, `remote_root`,
  `canonical_prefix`, `jobs_vault_root`, `jobs_media_root`,
  `cards_vault_root`, resolved local root) and ends with a note saying so.
  Fails to a one-line placeholder, never the unredacted text.
- Reporter wired with `get_eula=eula_mod.report_block`.

### `eula.py`

- `REPORT_KEYS`, `report_block(path=None)`: `{version, accepted_at,
  eula_sha256}` from the record (capped 32/64/64), or None. No path, no text.

### `settings_window.py`

- THIS COMPUTER gets `Dashboard address: <url>` with the LG-4 verdict (muted
  note for `http_local`, warning line for `http_public`; verdict cached 5 min
  per address because the model rebuilds twice a second on the Tk thread and
  classify can do DNS), then the PRIVACY block: four `[x]`/`[ ]` Buttons via
  `action_set_report_switch(app, name, on)`. A site-off category is a muted
  Line "... (Turned off for everyone by your administrator)"; bins while the
  project name is off read "(Off while the project name is off)". Each block
  in its own try.
- HELP gets `OPEN-SOURCE LICENCES` -> `action_open_licences` ->
  `licences_path()` (`_MEIPASS/ccsync_companion/assets/THIRD_PARTY_LICENSES.txt`,
  then the package `assets/`), through `tray._open_path_or_say_why` with a
  "this copy does not carry the texts" sentence when absent.
- The right-click menu is untouched (CR-88 ten items).

## Note J (answered here, read from the code)

The undo route keys on the journal **id** (`api_machine_resolve_undo` matches
`journal` against the stored ids; `resolve_undo.parse_command` and
`resolve_journal.session_by_id` use only the id). But the id is
`<project slug>/<UTC stamp>.json`, so it **carries the project name**.
Sending `project: ""` alone would not withhold the name. So `FIELDS` also
masks `resolve_journals[].id` to `withheld:project/<stamp>.json`, which the
companion maps back. Undo from the dashboard keeps working for a current
build, so **the "cannot be undone" cost sentence (plan 8.1) is NOT needed**.
An older companion handed a masked id answers "not found" (`:` is never in a
slug), which is harmless.

## Departures from the plan, and why

1. **`for_save`.** Plan: `validate_config` returns an error for
   `http_public`, "start is never blocked". An error from `validate_config`
   stops the lanes at start (DEL-3), so the error is raised only with
   `for_save=True`; at start it is a warning. The guard refuses the sends
   either way.
2. **No save in the settings window.** The window has no text entry and
   nothing in the companion writes `dashboard_url`, so there is no save to
   block there. The window shows the address and its verdict; `for_save` and
   `dashboard_url_problem` are the API for the wizard (G8) and any future
   editor.
3. **Journal ids are masked** (note J above), beyond the plan's `project: ""`.
4. **D4 is in `capabilities` only.** `idle_seconds` is null while
   `jobs_enabled` is false, but `input_idle` is NOT added to
   `report_optouts` for it: that list is the switches, and adding it would
   make G0 clear and G2b chip "NOT REPORTED" on every jobs-off machine for a
   switch nobody turned.
5. **"About" is the HELP section** (it already holds the version line; there
   is no About section).
6. **The refusal tray line** is a balloon once per run plus the Settings
   warning line. The persistent tray status line lives in `tray.py`
   (`_reporter_line`), which is not G1a's file: hand-off below.
7. **A privacy switch takes effect at once** (the running config dict is the
   reporter's own, so the action writes config.toml and the live dict),
   unlike the jobs settings which wait for a restart.
8. **Wrong-typed `report_*`** is read as off (withholding) plus a warning.
9. **Redaction covers the whole bundle**, clipboard copy included, not only
   log lines; `input_idle` alone does not trigger it (matches G0's rule that
   a newly withheld `input_idle` alone keeps stored bundles).
10. **`report_*` lines are live assignments in `DEFAULT_TOML_TEXT`** (a
    first-run config.toml gets `report_resolve_project = true` etc.):
    `test_default_toml_text_documents_every_default_key` requires it.
11. **Files outside the owned list:** `companion/config.example.toml` (four
    documented keys; `test_config_example_*` requires every DEFAULTS key) and
    `companion/tests/test_config.py` (`_good_cfg` now uses
    `https://dash.example:8480`; with `http://` a fully configured install now
    carries the LG-4 note, which broke five "no warnings" assertions).
12. `identity._warn_if_plaintext` deletion: already done by G1b; nothing to do.
13. `validate_config` at startup now classifies the address, which can do a
    DNS lookup for a name `transport` does not recognise (cached 30 s by
    `transport`). IP literals, `.ts.net`/`.local`/`.lan` and reserved names
    make no lookup.

## Tests run (only the files touched or created)

- NEW `companion/tests/test_telemetry_policy.py`: **303 passed** (256 of them
  the local x site combination grid; every FIELDS row; masking and
  `real_journal_id` both ways; reporter always sends `report_optouts`;
  collect-then-withhold in the reporter and in `_refresh_media_tree_once`
  (call counts on `_maybe_recover_stale_bridge`, `_relink_proxies_once`,
  `_classify_pool_once`); conflict count kept; diagnostics redacted;
  capabilities blanking + cache + D4; site round trip; `report_*` in neither
  `machine_settings.ACCEPTS` nor `db.MACHINE_SETTING_KEYS`; LG-4 config and
  window; refusal toast once; PRIVACY rows, site-greyed rows, the action;
  licences action; em-dash scan; `redact_text`).
- NEW `companion/tests/test_telemetry_disclosure.py` (LG-16 payload pin):
  **4 passed**.
- NEW `companion/tests/test_eula_report.py`: **7 passed**.
- Mutation check: disabling the reporter strip fails 2 tests; disabling the
  media-tree withhold fails 1.
- Existing suites of the touched modules and every suite that drives them
  (test_site, test_config, test_capabilities, test_reporter,
  test_reporter_health, test_settings_window, test_eula, test_app,
  test_resolve_undo_command, test_diagnostics_upload, test_machine_settings,
  test_jobs_phase4, test_broll_wiring, test_file_moves, test_lane_watchdog,
  test_role, test_root_guard, test_sequencer_perf, test_ytdl_feature_gate,
  test_ytdlp_manager, test_cr319_skip_ahead, the five bug-hunt files that
  drive these modules, test_transport, test_identity) together with the three
  new files: **2022 passed**. `test_tray.py`: **201 passed**.

## Hand-offs owed

- **G2a (`telemetry_fields.py` + the strip in `api_report`):** copy
  `FIELDS` AND `MASKED` exactly; the mask for `resolve_journals[].id` is
  `"withheld:project/" + last path segment` (`opaque_journal_id`), applied
  instead of removal. A current companion now always sends
  `report_optouts` (possibly `[]`) and may omit top-level `resolve_project`
  (withheld), which must read as "not reported", not as "Resolve closed".
  `eula` rides heavy reports only. Parity test may load
  `companion/src/ccsync_companion/telemetry_policy.py` by path (leaf module).
- **G0 (via the overseer; G0's wave is closed):** `apply_report_optouts`
  blanks `project` in stored `resolve_journals` but keeps the ids, which carry
  the project slug. They should be masked with the same rule when
  `resolve_project` is newly withheld (the next report from a current build
  replaces them anyway; an older build's do not).
- **G8 (wizard):** the four key names are `telemetry_policy.CONFIG_KEYS`
  (`report_resolve_project`, `report_local_manifest`, `report_media_tree`,
  `report_input_idle`), bools. For the address: `config.dashboard_url_problem`
  or `config.validate_config(cfg, for_save=True)`; the sentences are
  `config.DASHBOARD_URL_PUBLIC_HTTP` / `DASHBOARD_URL_LOCAL_HTTP`.
- **G6:** the About button opens `assets/THIRD_PARTY_LICENSES.txt` inside the
  `ccsync_companion` package (`_MEIPASS/ccsync_companion/assets/` when
  frozen), the same datas layout as `EULA.md`. Until it is bundled the button
  says the build does not carry the texts.
- **tray.py owner (unassigned; overseer):** optional. `_reporter_line` could
  name the refusal when `last_status == reporter.CLEARTEXT_REFUSED_STATUS`
  with `reporter.CLEARTEXT_REFUSED_LINE`; today it shows the generic "has not
  accepted a report" line after the streak, beside the balloon and the
  Settings warning.
- **G9 (docs):** note J needs no extra cost sentence (undo still works). The
  PRIVACY block path is "Settings, THIS COMPUTER, PRIVACY", as 8.1 says.
  `docs/CONFIG.md`: the four `report_*` keys (take effect at once from the
  window, at next start from a hand edit), and `validate_config`'s
  `for_save`. CLAUDE.md invariant: the journal id mask is part of "collect,
  then withhold".

## Review round 1 (2026-09-25, adversarial reviewer's six points)

Every point was verified before it was fixed; all six were real.

1. **FIXED: switched off, then on within 10 minutes, the manifest stayed
   away.** `reporter._build_payload` ran `_drop_unchanged_sections` BEFORE
   `_withhold`, so a withheld, unchanged manifest was booked as "omitted as
   unchanged" and kept its stamp. The dashboard had already deleted the rows
   (`db.apply_report_optouts`), so the machine had no inventory and no
   file-move targeting for up to `SECTION_RESEND_SECONDS`. The withhold now
   runs first. A withheld section is therefore "not sent", and
   `_note_sections_sent` drops its stamp. Test:
   `test_a_section_switched_off_then_on_within_the_resend_window_is_sent_again`.
   It fails on the old order.
2. **FIXED: `resolve_undo_applied[].detail` named projects.** The bridge's
   retry and refusal sentences quote the journal's project and the open one.
   - `app._resolve_undo_results` runs each answer through
     `_withheld_undo_detail` at REPORT time, so the switch as it is now
     decides. That helper replaces every known name (item 3), then applies
     `telemetry_policy.redact_undo_detail`.
   - `redact_undo_detail` is name-agnostic: every “…” quoted span becomes
     “<project>”, and a `record <slug>/<stamp>.json` becomes
     `withheld:project/<stamp>.json`.
   - New FIELDS row `resolve_undo_applied[].detail` under `resolve_project`,
     MASKED with `"undo_detail"`, so G2a's copy can apply it to an older
     build's answer. `state`/`ok`/`id` stay.
   - `resolve_undo_applied` has left `NOT_PERSONAL_TOP_LEVEL`.
   - `_resolve_undo_results` reads `telemetry_withheld` through getattr,
     because `test_resolve_undo_command`'s fake app borrows the method.
3. **FIXED: diagnostics redaction knew only the open project.** New
   `app._known_project_names()` collects:
   - the watcher's `last_resolve_project` and `_last_seen_project` (not
     cleared when Resolve closes);
   - the watcher's ignored projects and config `ignored_resolve_projects`;
   - every journal's project and its `project_slug`, from `summaries(500)`;
   - every folder name under `resolve_journal.journal_root()`.

   New `app._redaction_roots()` adds the journal root to the roots. Test:
   `test_diagnostics_redact_every_project_this_machine_knows` covers Resolve
   closed, an earlier project, and a `/` name logged under its slug path. It
   fails on the old code.
4. **ACCEPTED, fixed in the wording and the hand-off.** An older companion
   given a masked journal id answers "failed: no longer has the record", and
   the dashboard retires the request. So dashboard undo is lost for older
   builds while the SITE withholds `resolve_project`. The tray undo still
   works. The `MASKED` comment in `telemetry_policy.py` now states the cost,
   and my note J above ("harmless", "cost sentence NOT needed") is WRONG for
   older builds. I kept masking rather than "mask only when `report_optouts`
   is present", because not masking sends the project name, which the site
   switch promises not to store. The docs group needs a cost sentence (see
   hand-offs).
5. **FIXED: the pin now reaches inside `sync_guard`.**
   `test_telemetry_disclosure.py` pins the key sets from the source:
   - `app.sync_guard`'s `guard["x"] =`, lane B's `sync_guard_report`
     `out["x"] =`, and `app.resolve_health`'s returned keys;
   - every key must be classified exactly once: in a FIELDS row, not
     personal, or STILL SENT;
   - STILL SENT, inside `sync_guard`: `blocked`, `folders_unfiltered`,
     `removal_overrides`, `repath_events`, `shared_folder_problems`,
     `stalled`, `standins_placed`, `trash`;
   - STILL SENT, inside `resolve_health`: `stills` (its `path`).

   New FIELDS row: `sync_guard.skipped_exists.samples` under
   `local_manifest`. These are file names from this computer's tree; the
   counts stay.
6. **FIXED: the address check could block on DNS.**
   - `config.dashboard_url_problem(url, lookup=True)`: with `lookup=False`,
     a name only DNS could judge (`_needs_dns`) is answered as the
     studio-network note with no lookup.
   - `validate_config` passes `lookup=for_save`, so startup never asks DNS
     and a save still does.
   - The settings window shows the shape-only verdict at once and runs the
     lookup on a daemon thread (`_address_lookup`, one per address). The
     thread replaces the cached verdict when it is done.
   - Tests: `test_startup_never_asks_dns_about_the_dashboard_address` and
     `test_the_window_never_waits_on_dns_for_the_address` (a 5 s blocking
     resolver; the window answers in under 1 s). Both fail on the old code.

   This supersedes departure 13.

Mutation check: reverting items 2, 3 and 6 fails exactly the 4 new
app/config/window tests. Reverting item 1's order fails its test.

### Tests (review round)

- `test_telemetry_policy.py`: 311 passed. `test_telemetry_disclosure.py`: 9
  passed.
- With them: `test_eula_report`, `test_reporter`, `test_reporter_health`,
  `test_config`, `test_settings_window`, `test_resolve_undo_command`,
  `test_diagnostics_upload`, `test_app`, `test_capabilities`, `test_site`,
  `test_transport`. **1288 passed.**
- Dashboard `test_report_optouts.py`:
  `test_the_fields_copy_equals_the_companions` and
  `test_the_masks_equal_the_companions` now FAIL, as they should. G2a's copy
  must take the two new rows and the new mask (below). The other 67 in the
  three LG-1 dashboard files pass.

### Hand-offs owed (review round)

- **G2a (`telemetry_fields.py`), required: the parity tests fail until this
  is done.**
  - Add `"resolve_undo_applied[].detail"` to `resolve_project`.
  - Add `"sync_guard.skipped_exists.samples"` to `local_manifest`.
  - Add `MASKED["resolve_undo_applied[].detail"] = "undo_detail"`, with
    `redact_undo_detail` copied verbatim from `telemetry_policy.py`, together
    with `_QUOTED_NAME`, `_JOURNAL_IN_TEXT` and `UNDO_DETAIL_WITHHELD`.
  - The mask must work on a Pydantic model's `detail` as well as a dict's.
  - Consider also running `redact_undo_detail` over the stored
    `resolve_undo_requests.detail` when `resolve_project` is newly withheld
    (G0's `apply_report_optouts`).
- **Docs group (wave 2):**
  - The cost sentence for the site switch: "While the project name is
    withheld for everyone, undoing a clip-path change from the dashboard
    needs companion <COMP> or newer on that computer; an older one can still
    undo from its own tray."
  - TELEMETRY.md's payload table: `sync_guard.skipped_exists.samples` moves
    under the file-list switch, and `resolve_undo_applied[].detail` moves
    under the project-name switch (names replaced, not removed).
  - The "still sent" list gains the `sync_guard` keys above: `blocked`,
    `folders_unfiltered`, `removal_overrides`, `repath_events`,
    `shared_folder_problems`, `stalled`, `standins_placed`, `trash`, and
    `resolve_health.stills`.
  - The plan's 4.1 table gains the same two rows.
- **Orchestrator:** substitute the companion version for `<COMP>` when
  versions are bumped.
