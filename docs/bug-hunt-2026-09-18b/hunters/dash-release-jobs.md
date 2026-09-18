# dash-release-jobs - the release feed, the OTA code-update path, the jobs scheduler and the four feed tools

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/dashboard_update.py` - the whole diff hunk by hunk, plus `_set_state` / `read_state` / `_heal_orphaned_progress` / `request_restart` / `consume_restart_request` / `finish_restart` / `apply` / `rollback` / `status` / `tree_schema_version` / `schema_rollback_check` in full (~60%)
- `dashboard/src/ccsync_dashboard/release_feed.py` - the diff, plus `channel_retractions`, `apply_retractions`, `_valid_records`, `repair_provenance`, `_feed_flag`, `_apply_policy` (~35%)
- `tools/publish_feed.py` - the diff, `published_assets`, `_asset_is_held`, `github_upload` (~25%)
- `dashboard/deploy/select_code_root.py` - `tree_schema_version`, `revert_refusal`, `_retire`, `revert`, `record_revert_refusal` (read as the other end of the manifest / current.json contract)
- `companion/src/ccsync_companion/release_pubkey.py` - `RECORD_FIELDS` / `KIND_EXTRA_FIELDS` / `OPTIONAL_KIND_EXTRA_FIELDS` (which fields the signature covers)
- `dashboard/templates/partials/admin_dashboard_update.html` (the retired_from / retired_reason render - present and correct)
- Tests: `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_mediums.py` (the five cases for this territory), `dashboard/tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py` (the regression-6 hunk), `tools/tests/test_publish_feed.py` (the five new cases)
- Ledger: `docs/bug-hunt-2026-09-18/ledger/dashboard.md` CR-285S / AA / AB / AC / AD / AE / AK and `webapps-tools.md` CR-286AJ
- Not changed by the pass and only skimmed: `jobs.py`, `ai_providers.py`, `cli_tools.py`, `release_trust.py`, `ed25519.py`, `tools/publish_latest.py`, `tools/sign_release.py`, `tools/release_key.py`

Tests run:
- `cd tools; ..\dashboard\.venv\Scripts\python.exe -m pytest tests/test_publish_feed.py -q` -> 77 passed
- ad-hoc script from the dashboard venv driving `request_restart` + `finish_restart` with `_write_json` raising `OSError(30)` (scratchpad, outside the repo) -> `finish_restart` returned False, `_exit_process` never called

## Findings

### dash-release-jobs-1 - CR-285S does not fix its own `request_restart` half: the restart intent lives only in the file that could not be written
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/dashboard_update.py:1286-1306` (`request_restart` / `consume_restart_request`), with the two callers at `:1471` and `:1558`
- What: `request_restart` now writes `restart_requested: True` best effort and then signals SIGTERM - but the ONLY channel between `request_restart` and `finish_restart` is the state FILE: `consume_restart_request` calls `read_state(settings)`, which re-reads `update_state.json` from disk. When the best-effort write is swallowed the flag is nowhere, `consume_restart_request` returns False, uvicorn exits 0 and `run.sh` does not re-exec. The fix makes the write survivable and loses the decision at the same moment. Separately, both callers run an UNGUARDED `_set_state(step="restarting", ...)` on the line immediately before `request_restart` (`:1471` in `apply`, `:1558` in `rollback`), so on the very disk this fix is about the OSError still escapes one line EARLIER than the guarded call and `request_restart` is never reached at all.
- Failure scenario: the `/data` dataset goes read-only (pool fault) or fills after the code swap. `apply` has already renamed staging onto `code/<version>` and written `current.json` naming the new version. `_set_state(step="restarting")` raises -> `apply` unwinds -> `_fail_state` (now best effort, so it does not raise) -> no restart is ever requested. If instead the disk goes bad one line later, `request_restart` swallows the write, SIGTERMs, and `finish_restart` answers False -> exit 0 -> the container keeps serving the OLD code while `current.json` names the new tree, with the panel's last state "restarting", until a human restarts the container.
- Evidence: scratchpad script, dashboard venv: pre-seed `update_state.json`, monkeypatch `_write_json` to raise `OSError(30)`, stub `_signal_restart` and `_exit_process`, then `request_restart(s); finish_restart(s)` -> printed `SIGNALLED`, `finish_restart -> False`, `exits: []` (expected `[75]`), and the on-disk state was still `{'in_progress': False, 'step': 'idle'}`. The suite's own case `test_a_restart_is_signalled_even_when_the_note_about_it_cannot_land` asserts only that `_signal_restart` fired; the sibling case only passes because it PRE-WRITES `restart_requested: True` to a healthy disk before breaking the writer. Neither exercises the sequence the ledger entry describes.
- Ledger: CR-285S (dash-release-jobs-1) does not fix its own second paragraph
- Suggested fix: carry the intent in memory as well as on disk - a module-level flag set by `request_restart` and OR'd into `consume_restart_request`'s disk read (the process identity is already nonce-checked, so a stale in-memory flag cannot leak across a re-exec) - and pass `best_effort=True` on the two `_set_state(step="restarting", ...)` calls at `:1471` and `:1558` so the guarded call is reachable at all.

### dash-release-jobs-2 - CR-285AA closes the direction nobody attacks and leaves the one its own comment describes
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:785-791` (`repair_provenance`)
- What: the finding was "an untrusted feed host could rewrite the provenance of a package this dashboard published itself", and the code comment spells the harm out: "a build published here by `ship.cmd -AllowDirty` and correctly stamped `+dirty` could therefore have that chip cleared ... by whoever serves the feed's static files". The new guard is `if dirty or not bool(existing["git_dirty"]): continue` - it refuses to make a clean row look dirty and refuses to rewrite `git_sha`, but clearing a TRUE `git_dirty` to False is the surviving path, and that is the attack. `git_dirty` is outside the Ed25519 record signature (`release_pubkey.RECORD_FIELDS` + `KIND_EXTRA_FIELDS` + `OPTIONAL_KIND_EXTRA_FIELDS` do not contain it), so editing it needs no key: only the ability to serve the feed's static JSON.
- Failure scenario: the vendor publishes 0.9.76 from a dirty tree, correctly stamped. Whoever serves (or MITMs, or compromises the host of) the feed's static files edits `git_dirty` to `"0"` on that record; the signature still verifies and the sha256 is untouched. Every customer dashboard's next feed poll runs `repair_provenance`, matches the sha, and silently clears the `+dirty` chip on the Packages page - on the one day the chip exists for. The `fixed` list is only logged.
- Evidence: read `repair_provenance` end to end. `sha_conflict` only protects against DIFFERENT bytes, and `_valid_records`' signature check does not cover the two advisory fields (confirmed in `release_pubkey.py:66-113`). The new test `test_the_feed_may_clear_a_dirty_chip_and_may_not_write_a_commit` asserts the clearing direction as DESIRED behaviour, so the suite now pins it.
- Ledger: CR-285AA (dash-release-jobs-2) does not fix the scenario it names
- Suggested fix: restrict the repair to rows this dashboard did not publish itself - `existing["published_by"] == release_feed.FEED_PUBLISHER` (the constant added in this same diff and currently used exactly once) - or, sufficient for the `bool("0")` bug it exists for, one-shot the repair behind a `meta` marker. A permanent write path driven by an unsigned field is the problem, not its direction.

### dash-release-jobs-3 - the regression test for CR-285AC re-implements the expression instead of calling `apply`, and passes unchanged on the unfixed tree
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_mediums.py:485-500` (`test_reapplying_the_running_version_keeps_the_rollback_target`)
- What: the test writes a `current.json`, reads it back, and then evaluates a COPY of the arithmetic inline (`carried = previous if previous and previous != version else str(held.get("previous") or "")`). It never calls `dashboard_update.apply`, and every function it does call (`_write_json`, `_read_json`, `current_json_path`) is byte-identical at HEAD - so it passes on `git show HEAD:dashboard/src/ccsync_dashboard/dashboard_update.py` and cannot fail for the bug it is named after. It also does not cover the branch the fix actually added (`if carried == version: carried = ""`), the guard against writing a `previous` that points at the tree being applied.
- Failure scenario: someone folds the `carried` block back into a one-liner, or breaks the `carried == version` guard; the suite stays green and the next admin who presses ROLLBACK after a re-apply is handed the image against a v53 database - the outcome CR-285AC exists to prevent.
- Evidence: the test body contains no reference to `dashboard_update.apply` and duplicates the source expression as a literal. The sibling case for regression-4 in the same file at least asserts on `inspect.getsource(apply)`, which does fail at HEAD.
- Ledger: CR-285AC (dash-release-jobs-5) - the fix is right, its regression test does not guard it
- Suggested fix: drive the real `apply`, or extract the three lines into a `_carry_previous(held, version)` helper in `dashboard_update.py` and assert on that helper, including the `carried == version` case.

### dash-release-jobs-4 - regression-6's replacement still does not test the absent attribute, and its comment points at a test about something else
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py:324-339`
- What: the tautological `assert not hasattr(...) or True` was replaced by a comment claiming "the rest of this test proves it for the present case; the absent case is the one below". The settings object in use is a real `Settings`, and `settings.py:426` declares `release_feed_sig_url: str = ""`, so the attribute is ALWAYS present and the absent case has no test anywhere: the next test in the file (`test_why_names_the_sidecar_cause_when_that_is_why_ffmpeg_is_missing`, under a `regression-11` banner) is about the jobs scheduler and ffmpeg. The `getattr(settings, "release_feed_sig_url", "")` at `release_feed.py:809` - the thing the docstring is about - remains unguarded by any test.
- Failure scenario: a rollback to a tree whose `Settings` predates the field, or a `SimpleNamespace` double; if the `getattr` default is ever dropped the suite stays green and the feed poller raises `AttributeError` on every cycle.
- Evidence: `grep -n release_feed_sig_url dashboard/src/ccsync_dashboard/settings.py` -> `426: release_feed_sig_url: str = ""`; the test's `_settings` builds a plain `Settings`.
- Ledger: CR-285AK (regression-6, dashboard half) removes the tautology without restoring the claim
- Suggested fix: add one line that derives the URL from an object that genuinely lacks the field and assert the result, or rename the test to what it does test.

### dash-release-jobs-5 - regression-4 fixed the manifest's `schema_version` and left the identical collapse in `current.json`
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/dashboard_update.py:1452` (vs the fixed writer at `:1411-1415`)
- What: the same `int(checks.get("schema_version") or 0)` that regression-4 removed from the staged manifest is still the writer of `current.json`'s `schema_version`, so a tree whose stage-verify probe could not answer is recorded there as claiming schema v0. Nothing reads that key today (`tree_schema_version` in both `dashboard_update.py` and `deploy/select_code_root.py` reads `manifest.json`; no template or route touches it), so it is inert now - but it is a field on the appliance's most load-bearing state file that says something the tree never claimed.
- Failure scenario: any future reader of `current.json["schema_version"]` (a notice, an alert, a support dump) repeats CR-285AD exactly: "cannot tell" read as v0, and v0 is below every live schema, so the escape hatch is refused.
- Evidence: `grep -rn schema_version dashboard/` outside `db.py` / `dashboard_update.py` / `select_code_root.py` / tests returns nothing but vendored third-party code; the two writers differ only in that one was fixed.
- Ledger: CR-285AD (regression-4) fixed one of the two writers
- Suggested fix: write the key from the same `probed` local, omitting it when the probe did not answer, so both files carry the three-way answer.

## Coverage note
- Checked and found SOUND, so not reported: CR-285AB (`channel_retractions` folding `kind`) - I first suspected it desynchronised `_valid_records`' `recalled` set, which still builds `key` from the RAW kind, but the `odd` check a few lines below drops any record whose kind is not already lower-case, so the mismatch is unreachable and the fold strictly improves the match. CR-285AE (`retired_from` / `retired_reason`) - the template half does exist at `dashboard/templates/partials/admin_dashboard_update.html:43-46`; the key names match `select_code_root._retire` exactly. CR-286AJ (`_asset_is_held`) - correct in the safe direction.
- `jobs.py`, `ai_providers.py`, `cli_tools.py`, `release_trust.py`, `ed25519.py`, `tools/publish_latest.py`, `tools/sign_release.py` and `tools/release_key.py` are untouched by this fix pass and no ledger entry claims a fix in them; I checked them for call-site fallout from the diff (none - `FEED_PUBLISHER` and `_asset_is_held` have no other callers, verified by grep) but did NOT hunt them cold. CR-280 (macOS certificate verification, OPEN) was not investigated: it needs the Mac.
- One fidelity gap the `publish_feed` suite hides: the `omit_state` fake returns a TWO-field line, which real `gh` never produces - jq prints the literal string `null` for a field the JSON lacks, so an older `gh` yields `state == "null"`, not a missing element. The outcome is the same (re-upload everything), so it is not a defect, but the `len(parts) > 2` branch is dead in production and the real old-gh path is untested. I could not verify that `.digest` is a field the installed `gh` serves (no network by rule); if it is not, the skip simply never fires and every release pushes everything.
- Not covered by any suite in this territory: `apply` with a disk that fails PART WAY (every existing case breaks `_write_json` globally or not at all), and `rollback`'s interaction with dash-release-jobs-1.

## OUT OF TERRITORY
- `tools/release_macos.sh:530-537` with `.github/workflows/release-macos.yml:141`: the workflow sets `CCSYNC_REQUIRE_FFMPEG: "1"` on the build step and says that turns "installed it and it still is not there" into a failed release, but `release_macos.sh` unconditionally OVERWRITES the variable with its own `have_cmd ffmpeg` verdict, so on a macOS runner where `brew install ffmpeg` did not put it on PATH the media-job tests skip silently and the build is published anyway - the hole tests-1 was written to close. (server-tools / dash-mounts-ui)
