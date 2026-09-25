# Ledger, wave 2, group c-core

## bug-comp-core-4 - Sign-in's /verify carries no arch and drops upgrade_none_reason
- Status: PARTIAL (rest OWED to d-api and c-app). Severity low (verifier med-04 DOWNGRADE).
- Verified as: HEAD identity.verify_credentials payload has no `arch`; the returned dict drops `upgrade_none_reason`; app.sign_in (app.py ~6513) feeds `{"upgrade": last_upgrade_info}` to `note_report_response`, whose clear rule (upgrade.py ~1665) clears a refusal when neither key is present; api.VerifyIn declares no `arch` (pydantic default ignores extras, so sending it is harmless to any dashboard) and api_verify passes no `withheld`. Mechanism confirmed; the verifier's low severity stands.
- Fix: companion/src/ccsync_companion/identity.py - verify_credentials sends `arch` (upgrade_mod.arch_key()) and forwards `upgrade_none_reason`; IdentityManager keeps `last_upgrade_reply = {"upgrade", "upgrade_none_reason"}` (set only on a successful sign-in), the shape note_report_response reads.
- Regression test: companion/tests/test_bug_hunt_2026_09_24_w2_c-core.py::test_verify_sends_arch_like_the_report_does, ::test_verify_forwards_upgrade_none_reason, ::test_verify_reason_absent_from_an_older_dashboard_is_none, ::test_sign_in_keeps_the_whole_upgrade_reply_for_note_report_response, ::test_the_kept_reply_does_not_clear_a_standing_refusal (real UpgradeManager: the kept reply keeps the refusal, the bare HEAD-shaped reply clears it) - all fail on HEAD (no arch key, no reason key, no attribute); run against a `git archive HEAD` copy of companion/src.
- Tests run: companion .venv python -m pytest tests/test_bug_hunt_2026_09_24_w2_c-core.py tests/test_identity.py tests/test_reporter.py tests/test_report_token_precedence.py tests/test_role.py -q -> 179 passed; same new file against HEAD src -> 10 failed.
- Skew / deploy order: both new keys are additive and optional in both directions. A companion sending `arch` to 0.7.57 is ignored; a 0.9.77 companion never sends it and the dashboard keeps "no arch = offer everything". Dashboard half should deploy first (as comp-app-3 did) but neither order breaks anything.
- OWED:
  - d-api, dashboard/src/ccsync_dashboard/api.py: declare `arch: str | None = Field(default=None, max_length=32)` on `VerifyIn` (~2079); in `api_verify` (~2232) pass `withheld=withheld` to `_upgrade_info` and, when no offer and `withheld`, set `result["upgrade_none_reason"] = withheld[0]` exactly as the report route does (~9768-9780).
  - c-app, companion/src/ccsync_companion/app.py `sign_in` (~6513): call `self.upgrade.note_report_response(self.identity.last_upgrade_reply or {"upgrade": self.identity.last_upgrade_info})` instead of the bare `{"upgrade": ...}` dict, so a reason on the verify reply keeps a standing refusal.

## bug-comp-core-6 - A repaired machine id is not reported until the tray restarts
- Status: FIXED
- Verified as: HEAD reporter._machine_id caches "" for the process lifetime and nothing resets `_machine_id_cache`; settings_window.action_repair_machine_id calls machine.remint() and toasts "It is reported from the next check in". Real.
- Fix: companion/src/ccsync_companion/machine.py - a module-level remint generation, bumped whenever remint() answers an id (new mint, or the file became readable); `remint_generation()`. companion/src/ccsync_companion/reporter.py - `_machine_id` drops its cache (the "" included) when the generation moved; no extra file reads or log lines otherwise, so the "do not re-try a read-only home every report" intent survives. No change in settings_window.py (c-ui) needed.
- Regression test: test_bug_hunt_2026_09_24_w2_c-core.py::test_reporter_rereads_the_machine_id_after_a_remint, ::test_remint_of_a_readable_file_still_invalidates, ::test_failed_remint_does_not_bump_the_generation - fail on HEAD (the getter is never called again; `remint_generation` absent).
- Tests run: as above.
- Skew / deploy order: companion-only, no wire change.
- OWED: none

## bug-comp-core-7 - A sign-in whose reply token is unusable overwrites a working identity.json
- Status: FIXED
- Verified as: HEAD IdentityManager.sign_in calls save_identity, swaps in-memory identity and adopts the report token BEFORE `self.valid()`; on failure memory goes to None and the file keeps the broken token. Real.
- Fix: companion/src/ccsync_companion/identity.py sign_in - builds the candidate dict, checks `is_valid(candidate)` first; on failure returns the same error and changes nothing (file, in-memory identity, adopted report token, upgrade reply). Behaviour change: a signed-in editor whose re-sign-in reply is unusable stays signed in as before (previously dropped to signed out in memory); test_identity's malformed-token test (fresh machine) still passes unchanged.
- Regression test: test_bug_hunt_2026_09_24_w2_c-core.py::test_unusable_sign_in_reply_leaves_the_working_identity_on_disk, ::test_expired_sign_in_reply_does_not_write_the_file - fail on HEAD (file overwritten / written).
- Tests run: as above.
- Skew / deploy order: companion-only.
- OWED: none

## Owed round (builder c-core, 2026-09-25)

Four items routed from other groups. New tests appended to
`companion/tests/test_bug_hunt_2026_09_24_w2_c-core.py` (5 more, 15 in the
file). Against HEAD (`git archive HEAD companion/src` into the scratchpad, the
test file run with PYTHONPATH pointed there): every owed-round regression test
fails; the short-string pass-through guard passes on HEAD as it should, and
the caps-mirror guard skips there (no dashboard in the archive) and passes in
the tree.

### logic-resolve-3 (from c-resolve) - make `resolve_factory_luts_extra` discoverable
- Status: FIXED
- Verified as: `luts.LutLinkManager.find_strays` reads `cfg.get("resolve_factory_luts_extra", "")`; the key was in neither DEFAULTS, the generated template nor `config.example.toml`, so the knob existed only in c-resolve's ledger.
- Fix: `companion/src/ccsync_companion/config.py`: `"resolve_factory_luts_extra": ""` in DEFAULTS after `resolve_lut_dir` (comment cites the finding), and a commented line in `DEFAULT_TOML_TEXT` after `resolve_lut_dir`. `companion/config.example.toml` gets the same documented line: `test_config.py::test_config_example_documents_every_default_key` and `::test_config_example_toml_matches_default_keys` require every DEFAULTS key there (they failed until it was added; the example file is config.py's documentation, so c-core's by subject, and no other group had touched it). The owner decision c-resolve raised (whether to delete the factory copies already in `P:\Assets\Luts`) is not code and is left to the owner.
- Regression test: `::test_the_factory_luts_knob_is_a_known_default_and_in_the_template` - KeyError on HEAD.
- Skew / deploy order: companion only; the value is read with `.get`, so an old config.toml without it behaves exactly as before.
- OWED: none

### ui-copy-4 (from c-ytdl) - identity.py says "machine" to an editor
- Status: FIXED
- Verified as: the only editor-facing sentence in identity.py with the word is the unusable-sign-in reply ("check this machine's clock"), returned by `IdentityManager.sign_in` and shown in the sign-in window. The other hits are docstrings, comments and the plain-HTTP log warning (log lines exempt). Nothing matches the text (grepped src and tests).
- Fix: `identity.py` sign_in: "check this computer's clock is correct".
- Regression test: `::test_the_unusable_sign_in_reply_says_computer` - HEAD says "machine".
- Skew / deploy order: companion only.
- OWED: the shared vocabulary test (`companion/tests/test_sweep_2026_09_04_copy.py`, c-ui by subject) may now add `identity.py` to MODULES, as c-ytdl's ledger already notes; not re-routed.

### bug-wire-3 (from d-api) - the companion never caps lane strings, so an older dashboard 422s the whole report
- Status: FIXED
- Verified as: HEAD's `DashboardReporter._build_payload` sends `status.last_error`, `detail`, `current_project` and `list(status.transfers)` raw; HEAD's `api.LaneReportIn` / `TransferIn` declare raising `max_length` (2000 / 500 / 512; transfers 256; transfer name 512, project_slug 128, direction 16), so any dashboard at or below 0.7.58 rejects the whole report over one long rclone error.
- Fix: `reporter.py`: `LANE_*_MAX` / `TRANSFER_*_MAX` mirrors of those caps, `_cap_str` (a longer string is cut, anything else including None passes through) and `_capped_transfers` (list bounded to 256, each dict's name/project_slug/direction cut); applied to the lane dict and to the top-level `current_project` (api's report model caps that at 512 too). Transfers were included beyond the three fields asked for because a deep relative path over 512 chars 422s the same way; this is the same wire, same cause.
- Regression test: `::test_long_lane_strings_are_capped_to_what_an_older_dashboard_accepts` (HEAD sends 5000/900/900 chars and 300 transfers), `::test_short_and_absent_lane_strings_pass_through_unchanged` (guard: None stays None, "" detail still becomes None), `::test_the_lane_caps_mirror_the_dashboards_declared_caps` (reads the caps out of `dashboard/.../api.py` so the mirror cannot drift silently).
- Skew / deploy order: companion only, either order; a truncating dashboard receives already-bounded strings.
- OWED: none (c-sync's optional bounding of `syncthing_lane.py`'s errored-folder join is a nicety the reporter cap makes unnecessary for the wire).

### bug-wire-4 (from d-api) - send arch in the verify body and keep the verify reply's upgrade_none_reason
- Status: ALREADY_FIXED (by this group's own bug-comp-core-4 earlier in this wave, uncommitted)
- Verified as: `identity.verify_credentials` sends `"arch": upgrade_mod.arch_key()` and returns `upgrade_none_reason`; `IdentityManager.sign_in` keeps `last_upgrade_reply = {"upgrade", "upgrade_none_reason"}`. Covered by `::test_verify_sends_arch_like_the_report_does`, `::test_verify_forwards_upgrade_none_reason`, `::test_sign_in_keeps_the_whole_upgrade_reply_for_note_report_response`.
- Fix: none in this round.
- OWED: none from c-core (the c-app half, app.py `sign_in` passing `last_upgrade_reply`, was routed by bug-comp-core-4).

### Tests run (owed round)
- `companion\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_c-core.py tests/test_reporter.py tests/test_reporter_health.py tests/test_identity.py tests/test_config.py tests/test_luts.py tests/test_bug_hunt_2026_09_24_w2_c-resolve.py tests/test_sweep_2026_09_04_copy.py tests/test_report_token_precedence.py -q` -> 767 passed.
- New file against HEAD's companion/src -> 13 failed, 1 passed (the pass-through guard), 1 skipped (the caps-mirror guard).

## Review round (builder c-core, 2026-09-25)

### bug-wire-3 - Review round
- Reviewer: PROBLEM. `reporter._build_payload` still sent `payload["completed"]` raw. Each entry (`sync/rclone_lane.py` ~3898, `{"name": f"{prefix}{name}", ...}`) carries the same per-file name as the live transfer plus a project-subpath prefix, and HEAD's `api.CompletedIn` declares raising caps (name 512, direction 16, lane 64, at 64). So a >512-char path that was cut while live went out raw once it finished, and on a 0.7.58-or-older dashboard that report 422'd.
- Verdict: the reviewer is right. Checked HEAD's `CompletedIn` (`git show HEAD:dashboard/src/ccsync_dashboard/api.py`, line ~6888) and `ReportIn.completed` (`max_length=256`, above the companion's 200).
- Fix: `companion/src/ccsync_companion/reporter.py`: `COMPLETED_*_MAX` mirrors (512/16/64/64) and `COMPLETED_MAX = 200`. A shared `_cap_dict_fields(items, count, fields)` now does both jobs: `_capped_transfers` calls it, and the new `_capped_completions` too. `_build_payload` sends `_capped_completions(self._get_completions())`. Nothing else changes: the 200-entry bound stays the same, non-dict entries and unknown keys pass through, the source dicts are copied rather than mutated, and an empty list still leaves `completed` out.
- Regression test: `::test_a_long_completion_name_is_capped_like_its_transfer` (905-char name, 40/100/100-char direction/lane/at, 300 entries, which must come out as 512/16/64/64 and 200 entries with the prefix and extra keys kept and the source unmutated). With the one call site reverted to the old raw `list(...)[:200]`, it FAILS; with the fix it passes. `::test_short_completions_pass_through_unchanged` is the guard (short records are unchanged, and an empty drain sends no key). The drift guard `::test_the_lane_caps_mirror_the_dashboards_declared_caps` now also reads `CompletedIn`'s four caps and `ReportIn.completed`'s list cap (it must be >= `COMPLETED_MAX`).
- Tests run: `companion\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_c-core.py tests/test_reporter.py tests/test_reporter_health.py tests/test_identity.py tests/test_config.py tests/test_luts.py tests/test_bug_hunt_2026_09_24_w2_c-resolve.py tests/test_sweep_2026_09_04_copy.py tests/test_report_token_precedence.py tests/test_rclone_lane.py -q` -> 903 passed.
- Skew / deploy order: this is companion-only, and deploy order does not matter.
- OWED: none.

### logic-resolve-3, ui-copy-4, bug-wire-4 - Review round
- The reviewer raised nothing, so there is no change.
