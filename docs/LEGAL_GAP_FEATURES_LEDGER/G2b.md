# G2b ledger: dashboard settings and views (legal-gap features, wave 1)

2026-09-25. Plan: `docs/LEGAL_GAP_FEATURES_PLAN.md` revision 2, Tier 1 +
Tier 2a, recommended defaults for every decision. Built on G0's `db.py`
(v59) as it stands in the tree. No version bumped, nothing committed.

## What was built

### LG-1: the site telemetry policy

- **`settings.py`.** Four fields, `site_telemetry_{resolve_project,
  local_manifest, media_tree, input_idle}`, all `True` by default. From the
  environment `DASH_SITE_TELEMETRY_<NAME>`: `"0"` and nothing else is OFF
  (the mirror of the features' `"1"` rule, because on is the safe default
  here).
- **`site_store.py`.**
  - `KEYS` gains `telemetry.resolve_project`, `telemetry.local_manifest`,
    `telemetry.media_tree` and `telemetry.input_idle` (bool, `"1"`/`"0"`).
    `TELEMETRY_KEYS` and `TELEMETRY_SETTINGS_ATTRS` name them.
  - `validate` refuses a blank or a word for these four. The generic bool
    rule reads `""` as `"0"`, which here would delete data fleet-wide.
  - `resolved_manifest()["telemetry"]` = four bools, as set.
  - `telemetry_policy(conn, settings=None) -> set[str]`, the contract G2a
    calls. Precedence is DB row, then settings, then the product default
    (reported). `resolve_project` off implies `media_tree` (through
    `db.clean_report_categories`). It never raises. On an unreadable table
    it returns settings UNION the last applied set
    (`db.META_SITE_REPORT_OPTOUTS`).
  - **The hook.** `set_many(..., settings=None)` calls
    `db.apply_site_optouts(conn, telemetry_policy(conn, settings))` whenever
    the write carries a telemetry key. It runs in the caller's
    transaction, and the full set is passed every time. Settings save,
    import and undo all end here.
  - **Boot** (G0 hand-off 7). `seed_from_env_once` now always finishes with
    `enforce_telemetry_policy(conn, settings)`, which applies the full
    policy and commits. It never raises. The seed also copies the four
    keys.
  - `site.toml [telemetry]` export and import (`resolve_project = false`,
    and so on). `_settings_fallback` answers `"1"` for an absent key, so a
    diff or an undo never writes a blank.
- **`setup_routes.py`.**
  - `PUT /admin/site`, import and undo pass `settings=` to `set_many`.
  - A save that changes a telemetry key is snapshotted in `site_history`,
    like the three tree keys, so [ UNDO LAST CHANGE ] can switch it back on.
- **Settings page** (`admin_settings.html`, `site_settings.js`).
  - A [ TELEMETRY ] block with four ticks inside the settings form. Each
    has a hint that states what it covers and its cost, in the plan's §8.1
    terms.
  - Saving with a tick going from on to off asks first. The dialog names
    the items and says the held data is deleted for every computer and
    cannot be brought back.
- **Views.**
  - **Fleet grid.** A `REPORTING` row under [ DETAILS ] shows one grey chip
    per withheld category: `[ NOT REPORTED BY THIS COMPUTER: FILE LIST ]`.
    It is never a fault colour, never counted in `notes`, and never an
    alert.
  - **`health.py`.** `WITHHELD_LABELS`, `withheld_sections(names)`, and
    `annotate_legal(conn, entries, bundled_version=None)`, which does two
    fleet-wide reads and puts `report_withheld` and `eula` on each entry.
  - **`style.css`.** Adds `.chip.grey` (muted, dashed).
- **`alerts.py`.**
  - `Ctx.withheld` (from `db.withheld_map`) and `Ctx.report_via`.
  - `_withheld_quiet` handles a computer that withholds `local_manifest`:
    - `stray_projects` and `moved_project_dir` say nothing about it if the
      finding was never raised;
    - an already-open finding is held QUIET, so switching reporting off
      never mails "this has cleared".

### LG-4: plain http

- `GET /api/v1/admin/site` gains `report_via_counts` (`{"https",
  "http_local", "http_public"}` -> count, from `db.report_via_map`). It is
  admin-only and never on the open manifest.
- The Settings page draws one informational line from those counts (JS):
  "N computers reach this dashboard over plain http on your network or
  tailnet. Serving it over https (Tailscale Serve does this) is
  recommended." There is no notice and no alert for `http_local`.
- **Alert kind `dashboard_reached_over_public_http`** (SEV_ERROR) is
  registered with its evaluator `_check_public_http`. It fires only for
  `report_via = 'http_public'`, and an unreadable column is nothing.

### LG-5: licence line

- `health.eula_status(block, bundled_version)` judges the version only.
  The sha is carried for display and never compared.
  - green "Licence <v> accepted" when the version equals the bundled
    `EULA-VERSION`;
  - amber "Older licence accepted" when it differs;
  - grey "Not reported" when nothing was sent;
  - uncoloured when this dashboard carries no licence.
  - It never says "not accepted".
- `health.bundled_eula_version()` reads the same file `/setup` serves
  (`setup_engine.eula_path`).
- The fleet grid's VERSION cell and `partials/account_computer.html` (a
  `licence` row, plus a `not reported` row of grey chips) render `e.eula` /
  `pc.eula`. Absent draws nothing.

### LG-12: licence texts in /help

- **`published_docs.py`.** `TEXT_TREE = "legal/licenses"`,
  `TEXT_SUFFIX = ".txt"` and `is_licence_text(rel)`. `is_published` accepts
  a `.txt` only under that subtree. `..` escapes are refused.
- **`help.py`.**
  - The index walk adds the `.txt` files under `legal/licenses/`.
  - `resolve_document` serves them. Any other `.txt` is refused, for an
    admin too.
  - `help_href` follows a `.txt` link only into that subtree.
  - `page_context` renders a licence verbatim, as escaped `<pre
    class="licence-text">` with no markdown, titled by file name.

### LG-17: retention visibility

- **`partials/collector_health.html`.**
  - A "Retention last ran <ago>" line, read from
    `collector_health()["retention_last_ran"]`. When it has never run, the
    line says "never on this database".
  - An ok-but-late kind shows `[ OVERDUE ]` instead of
    `[ INCOMPLETE ] overdue`.
- **Alert kind `collector_kind_overdue`** (SEV_WARN) is registered with
  `_check_collector_overdue`.
  - It fires on `kinds[i]["overdue"]`, which G0 keeps false while the
    collector is stale.
  - It is debounced by one alerts interval (G0 hand-off 10): the kind must
    be past `db.collector_kind_overdue_after(...) + interval_alerts`,
    measured from its last finish.
  - `prune` gets its own retention wording.
  - A failed kind stays `collector_kind_failed`'s.

## Departures from the plan, and why

1. **Boot enforcement lives in `site_store.seed_from_env_once`, not in
   `app.py`.** `app.py` is G3's (the `include_router` line only), and this is
   the site-manifest hook the lifespan already calls, inside its own
   try/except. An environment policy can only change on a restart.
2. **The manifest publishes the four values as set.** It does not fold
   `resolve_project` off into `media_tree`. The implication lives once on
   each side: `telemetry_policy` here, and `telemetry_policy.effective` in
   the companion. Folding it into the manifest would untick the admin's own
   `media_tree` choice.
3. **A blank telemetry value is a 422.** It is not read as `"0"`, because
   `"0"` deletes data fleet-wide.
4. **Telemetry changes are snapshotted in `site_history` on save.** This
   goes beyond the tree keys, so they can be undone. Undo switches
   reporting back on; it cannot restore deleted data, and the confirm
   dialog says so.
5. **`telemetry_policy`'s failure fallback includes the last applied set**
   (`META_SITE_REPORT_OPTOUTS`). G2a's `_site_withheld` falls back to that
   same meta row, but only when this function raises, and it never does. So
   the two stand-ins are unioned here to keep the "a broken read never lets
   withheld data back in" property.
6. **Chip placement.** The plan asks for a chip "on each withheld section",
   but the grid has no per-section block for three of the four categories.
   Instead, the chips are one `REPORTING` row under [ DETAILS ], one chip
   per category.
7. **The LG-4 Settings line is drawn by `site_settings.js`** from
   `GET /admin/site`. The page context is built in `ui.py`, which no group
   owns.
8. **`style.css`** also gained `.eula-line .green/.amber` (two text
   colours), beyond "chips only".
9. **`setup.js` is untouched.** The wizard's site step posts an explicit
   field list, and nothing in G2b's scope changes it.
10. **`red_unexplained` and the stand-in readers are unchanged, on purpose.**
    `red_unexplained` reads the row's status, which comes from lanes and
    freshness, never holdings, and alerts.py has no stand-in reader. The
    readers that do go stale under a withheld file list are `stray_projects`
    and `moved_project_dir`, and those now go quiet.

## Tests

| File | Result |
|---|---|
| `dashboard/tests/test_site_telemetry.py` (new) | **28 passed** |
| `dashboard/tests/test_legal_alerts.py` (new) | **11 passed** |
| `dashboard/tests/test_published_licenses.py` (new) | **20 passed** |
| `dashboard/tests/test_site.py` (edited) | **22 passed, 4 failed** |

- **The 4 failures in `test_site.py` are expected until hand-off 1 lands.**
  Each pins the new `telemetry` object on `GET /api/v1/site`, which
  `api.api_site` (G2a's file) does not publish yet:
  - `test_site_is_readable_without_logging_in` and
    `test_site_carries_no_credential_and_no_fleet_inventory` (the
    `EXPECTED_KEYS` pin);
  - `test_the_manifest_publishes_every_telemetry_switch_on_by_default`;
  - `test_a_site_switch_from_the_environment_is_published`.
- **Read-only regression check** of the existing files closest to the edited
  modules: `test_site_store`, `test_site_history`, `test_help_page`,
  `test_alerts`, the three `dash_mounts_ui` published-docs pins,
  `test_site_manifest_consumers` and `test_account_page`. Result: **303
  passed, 1 skipped**. This ran with other groups' work in progress in the
  tree.

## Hand-offs owed

1. **G2a, `api.api_site`** (the open manifest): add
   `"telemetry": dict(site["telemetry"])` beside `features`. `site` is
   already `site_store.resolved_manifest(...)`. This turns the 4 failing
   `test_site.py` tests green. The companion's `site.normalise` (G1a)
   reads exactly these four bools.
2. **G2a, `api.build_editors_view`:** call
   `health.annotate_legal(conn, <every entry in "editors" and
   "lost_machines">)` before returning. Without it, the grid's grey chips
   and licence line draw nothing, which is safe. The call is two
   fleet-wide reads, and `bundled_version` defaults to the `/setup`
   licence.
3. **Overseer: `account_api._computer_view`.** The plan says nobody edits
   this file, but `account_computer.html` (G2b) can only draw what `pc`
   carries. Add `"eula": entry.get("eula")` and
   `"report_withheld": entry.get("report_withheld") or []`. Without it the
   /account licence row is simply absent.
4. **Overseer or G6: ship the `.txt` licence texts.** All three shipping
   routes are markdown-only today, so `docs/legal/licenses/**/*.txt`
   reaches no deployed dashboard until they change:
   - `.dockerignore`: add `!docs/legal/licenses/**/*.txt` next to
     `!docs/legal/*.md`. `COPY docs/legal` in the Dockerfile already takes
     the directory.
   - `tools/build_dashboard_bundle.py`: the `md_only` filter.
   - `server/install_dashboard_app.py`: `SHIPPED_DOC_SUFFIX`.

   Each should accept `.txt` only under `docs/legal/licenses/`
   (`published_docs.is_licence_text` is the rule).
5. **Overseer, `ui.safe_to_close` wording** (G0 hand-off 8, `ui.py` is
   unowned). When `q.get("not_reported")`, say "does not report its file
   list, so the dashboard cannot tell whether everything uploaded".
6. **G9 docs.**
   - `docs/CONFIG.md`: `DASH_SITE_TELEMETRY_RESOLVE_PROJECT`,
     `_LOCAL_MANIFEST`, `_MEDIA_TREE` and `_INPUT_IDLE` (`"0"` = off, a
     site_settings row wins), and `site.toml [telemetry]` with the four
     bool keys.
   - `docs/SELF_DIAGNOSIS.md` / `docs/API.md`: the two new alert kinds, and
     `report_via_counts` on `GET /api/v1/admin/site`.
7. **G2a (information).** `site_store.telemetry_policy(conn, settings)`
   has the agreed signature and never raises.

## Review round (2026-09-25)

The adversarial reviewer raised five points. All five were real and all
five are fixed. Each fix has a test that fails on the code before it
(checked by putting the old code back and running the tests).

1. **Critical, fixed: the Settings script did not parse.** The telemetry
   confirm in `site_settings.js` had a raw line break inside a string
   literal, so none of the file ran. It is now `"?\n\n"`. The wording lives
   in one function, `telemetryOffQuestion`, which point 2 reuses.
   - New `test_site_telemetry.py::test_the_settings_script_parses` runs
     node's `vm.Script` over the file.
   - The three `test_bug_hunt_2026_09_24_w2_d-ui.py` tests the reviewer
     named pass again. That file is now part of the G2b gate.
2. **Medium, fixed: import and undo deleted data without the warning.**
   - `site_store.telemetry_switching_off(changes)` returns the categories a
     diff turns from on to off.
   - `POST /admin/site/import?dry_run=1` returns them as `telemetry_off`.
   - `GET /admin/site/history` puts `telemetry_off` on `entries[0]`, the
     only entry an undo can replay, from the same diff the undo route
     makes. The key is left out when the list is empty, so
     `test_site_history`'s exact key-set pin still holds. The key carries
     category names only, never values.
   - Both confirms end with Save's "deleted for every computer now, and
     cannot be brought back" question, naming the page's own tick labels.
   - **Departure:** I first gave the undo route a `dry_run` of its own, but
     the existing undo harness answers every undo call with a 409, and a
     second round-trip is not needed. The history is reloaded after every
     in-page save (ui-dash-static-3), and `expected_at` already refuses a
     confirm made against an older entry, so the history route carries the
     preview instead.
   - Tests: `test_the_import_preview_names_a_category_it_switches_off`,
     `test_the_history_names_what_an_undo_would_switch_off`, and
     `test_import_and_undo_confirms_say_what_is_deleted` (headless Chrome,
     the real `/admin/settings` render).
3. **Low, fixed: a privacy choice held an alert open forever.** The quiet
   hold is replaced by a new `withdrawn` volume on `_f`:
   - `deliver` closes an open row by writing a `<kind>.ok` row with
     `sent_to=""` and detail "closed without a message: ...".
   - Nothing is transmitted, and it is not counted as recovered or still
     open.
   - A row that was never raised gets nothing.
   - The finding appears on the scan surfaces for at most one alerts
     cycle, until `deliver` closes it. After that the check says nothing.
   - Test: `test_switching_reporting_off_closes_an_open_finding_without_a_message`,
     which replaces the old quiet-hold test.
4. **Low, fixed: a late-job alert could mail "cleared" when things got
   worse.** `_check_collector_overdue` now gives a `quiet=True` finding for
   a subject that is in `open_alert_subjects("collector_kind_overdue")`
   when the collector is stale or that kind's last run failed. A kind that
   ran again on time still recovers.
   - Tests: `test_an_open_overdue_job_is_held_quiet_when_its_last_run_failed`,
     `..._while_the_collector_is_stopped`, and
     `test_a_job_that_ran_again_on_time_still_recovers`.
5. **Low, fixed: the public-http alert never aged out.**
   - The diagnosis now says when the computer last reported ("(40 days
     ago)"), and the fix names [ FORGET ].
   - Past `SILENT_SECONDS`, the bound `machine_silent` uses, the finding is
     `repeat=False`: it is said once, not daily.
   - It is never dropped for age. Dropping it would be a recovery mail,
     and nothing about the exposure was fixed.
   - Test: `test_public_http_says_when_and_stops_repeating_for_a_quiet_computer`.

**Housekeeping:** a Python rewrite earlier in this round turned
`setup_routes.py`, `site_store.py` and `alerts.py` into CRLF files. All three
are LF again (the byte count of `\r` is 0), matching HEAD.

### Tests this round

| File | Result |
|---|---|
| `test_site_telemetry.py` | **32 passed** (28 + 4 new) |
| `test_legal_alerts.py` | **15 passed** (old quiet-hold test replaced, 5 new) |
| `test_published_licenses.py` | **20 passed** |
| `test_bug_hunt_2026_09_24_w2_d-ui.py` (now in the gate) | **101 passed** |
| `test_site.py` | **22 passed, 4 failed** (the same four pins, still waiting on hand-off 1) |
| Regression check: `test_site_history`, `test_site_store`, `test_alerts` | **159 passed** |

No new hand-offs.
