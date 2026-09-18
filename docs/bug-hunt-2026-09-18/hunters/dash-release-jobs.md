# dash-release-jobs - the vendor feed, the dashboard's own code updates, the job scheduler, and the AI provider/CLI wizard

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/release_feed.py` (100%, and `git diff 34a3c8f..HEAD` + `18e69f3..34a3c8f` on it first)
- `dashboard/src/ccsync_dashboard/release_trust.py` (100%)
- `dashboard/src/ccsync_dashboard/dashboard_update.py` (~60%: the state-file layer, heal/restart/exit path, `apply`, `start_apply`, `schema_rollback_check`, `status`; not the backup/prune/restore half in detail)
- `dashboard/src/ccsync_dashboard/jobs.py` (100%)
- `dashboard/src/ccsync_dashboard/cli_tools.py` (~35%: the download/checksum/install path, the CR-266a hunks, the routes)
- `dashboard/src/ccsync_dashboard/ai_providers.py` (~30%: key storage, masking, validation, route logging)
- `tools/publish_feed.py` (~45%: signing, `github_asset_plan`, `github_upload`, `published_assets`, `set_current`, `retract_record`)
- `tools/publish_latest.py` (~80%), `tools/sign_release.py` (~30%, the record shape), `tools/release_key.py` (skimmed)
- Supporting reads: `db.update_package_provenance` / `get_package` / `retract_package`, `api.YTDLP_META_PREFIX`, `docs/bug-hunt-2026-09-11b/ledger/dash-release-jobs.md`, `KNOWN_BUGS.md` CR-280/CR-281.

Tests run:
- `dashboard\.venv\Scripts\python.exe -m pytest tests/test_release_feed.py tests/test_dashboard_update.py tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py tests/test_bug_hunt_2026_09_11b_cr266a_cli_tools.py -q` -> 157 passed
- one ad-hoc repro script from the dashboard venv (scratchpad, outside the repo) - output quoted in finding 1.

## Findings

### dash-release-jobs-1 - the restart path still dies on a full or read-only /data: CR-260g fixed the reader, not the writer its own failure scenario names
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/dashboard_update.py:1268` (`consume_restart_request` -> `_set_state`), `:551` (`_set_state` -> raw `_write_json`), `:1290` (`finish_restart`); the partial fix is `:228` `_write_json_best_effort` and `:532`/`:547`.
- What: the 09-11b fix for dash-release-jobs-7 (ledger CR-260g) routed the HEALER's two writes through `_write_json_best_effort`, and explicitly left "every other `_write_json` caller unchanged". But the failure path the ledger describes is `finish_restart -> consume_restart_request -> read_state`, and `consume_restart_request` does not stop at `read_state`: having seen the flag it immediately calls `_set_state(restart_requested=False, ...)`, which writes through the UNGUARDED `_write_json`. So on a data dataset that is full or read-only the OSError still escapes the lifespan shutdown, `_exit_process(RESTART_EXIT_CODE)` still never runs, uvicorn still exits 0 and `deploy/run.sh` still does not re-exec. The fix moved the raise one line later.
- Failure scenario: an admin applies a dashboard bundle; the swap succeeds and `current.json` names the new version; `/data` then fills (or the pool faults read-only) before the SIGTERM shutdown completes. The container exits 0, run.sh treats it as a clean stop, the applied code never starts, and `update_state.json` still says `restarting` with nothing recording why. Identical outcome to the defect CR-260g claims to close. The same unguarded `_set_state` is also the first statement of `request_restart` (`:1264`), so on the same disk the apply worker raises BEFORE `_signal_restart()` ever fires, `_fail_state` then raises again inside its own `except`, and the thread dies with `in_progress: true` on disk and no restart requested at all.
- Evidence: ad-hoc repro from `dashboard/.venv` with `_write_json` monkeypatched to `OSError(28)` and a state file whose `owner_pid`/`owner_nonce` are the LIVE process (the real shutdown case, which is why the healer does not clear it):
  `RAISED out of finish_restart: OSError [Errno 28] No space left on device   exits []`
  i.e. `_exit_process` was never called. The two regression tests added for CR-260g (`tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py:231` and `:248`) only call `read_state`, and both seed a DEAD `owner_pid` so the healer short-circuits - neither exercises `finish_restart`, which is the function the ledger entry is about.
- Ledger: CR-260g (dash-release-jobs-7) does not fix dash-release-jobs-7.
- Suggested fix: make `consume_restart_request` decide the exit code from the in-memory state and persist best-effort (`_write_json_best_effort`), and wrap `request_restart`'s `_set_state` and `_fail_state`'s write the same way - the process must be able to exit 75 even when it cannot write a byte. Add a test that calls `finish_restart` with a LIVE owner nonce and an unwritable state file and asserts `_exit_process(RESTART_EXIT_CODE)` was called.

### dash-release-jobs-2 - `repair_provenance` lets an untrusted feed host rewrite the provenance of a package this dashboard published itself
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:745-768` (`repair_provenance`), with `release_trust.RECORD_FIELDS:34-44` and `tools/sign_release.py:452-453` as the other side.
- What: `git_sha` and `git_dirty` are NOT in `RECORD_FIELDS` and not in `KIND_EXTRA_FIELDS`/`OPTIONAL_KIND_EXTRA_FIELDS`, so they are outside the Ed25519 record signature (REL-13 says so deliberately - they are advisory). `repair_provenance` reads exactly those two unsigned fields off the feed and UPDATEs them onto any already-published row whose sha256 matches. Its docstring argues the sha check means "a vendor copy that differs from ours cannot rewrite our row's story", but a matching sha only proves the bytes are the same; it says nothing about the two fields being rewritten, which the feed host can edit freely without breaking any signature. This contradicts the module docstring's own threat model ("the feed HOST is untrusted ... Nothing here trusts it").
- Failure scenario: a build is published to this dashboard locally by `ship.cmd -AllowDirty` and correctly stamped `+dirty` in `companion_packages`. The same version and the same bytes are carried by the vendor feed. A feed host (or anyone who can serve its static files) edits that record's `git_dirty` to `"0"` and `git_sha` to any string; the signature still verifies, the sha still matches, and the next daily check silently clears the `+dirty` chip and rewrites the commit shown on the Packages page. The chip exists precisely so "the day a real dirty build is published" somebody notices - and that is the day it is switchable off by an untrusted party.
- Evidence: `grep -n "git_sha\|git_dirty" dashboard/src/ccsync_dashboard/release_trust.py` returns nothing (the fields are not canonicalised); `tools/sign_release.py:452` adds them to the record dict AFTER `canonical_record` has been signed. `db.update_package_provenance` writes them unconditionally.
- Ledger: new (opened by the 2026-09-11 fix for CR-267c).
- Suggested fix: restrict the repair to rows this dashboard actually published FROM the feed (`published_by = 'release-feed'`, which `publish_from_feed` already sets) and leave a locally PUT row alone; or restrict the repair to clearing the specific `git_dirty` value the `bool("0")` bug produced (feed record dirty is the string `"0"` and the row says 1) and never write `git_sha` at all.

### dash-release-jobs-3 - the new "only upload what changed" skip trusts a GitHub asset's name and size, and cannot see a half-uploaded asset
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `tools/publish_feed.py:746-758` (`published_assets`) and `:818-826` (the skip in `github_upload`).
- What: the 2026-09-11 speed-up asks `gh release view --json assets` for `{name, size}` and skips re-uploading any planned file whose name and size match. It does not read the asset's `state`. A GitHub release asset whose upload was interrupted sits in state `starter` (not `uploaded`) while already carrying the declared name and size, and a `starter` asset serves nothing usable. Before this change every run re-pushed everything with `--clobber`, so an interrupted upload healed itself on the next release; now it is skipped for ever, because nothing in the pipeline ever compares the published bytes against the record's sha again.
- Failure scenario: a 200 MB companion upload is cut off (the studio's line drops, `gh` is killed). The next release's `publish_feed` sees the asset at the same name and size, skips it, and prints "already on the release at the same name and size". Every customer dashboard then fetches that URL and gets a `FeedHashMismatch` - which is correctly refused, but is permanent and self-inflicted, and the only trace is a `last_error` on each customer's feed page. `fresh_key` does not help: it protects only the one package this run signed, not the other three artefacts or the older records in the mirror.
- Evidence: read of `published_assets`'s `--jq` (`.assets[] | "\(.name)\t\(.size)"` - no `.state`) and of the skip predicate `held.get(p.name) == p.stat().st_size`. Not reproduced against GitHub (the brief forbids touching the feed or GitHub), hence PLAUSIBLE.
- Ledger: new.
- Suggested fix: add `.state` to the jq and only treat an asset as held when `state == "uploaded"`; consider skipping on the record's own sha where the release API can give a digest, rather than on size.

### dash-release-jobs-4 - a channel `retracted` entry whose `kind` is not lower-case recalls nothing, silently, on both halves of the recall
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:474` (`channel_retractions`, `kind` is `.strip()` only while `platform` is `.strip().lower()`), used at `:519-524` (`_valid_records`'s `recalled` set) and `:497` (`apply_retractions` -> `db.retract_package`, which matches `kind` exactly: `db.py:4117` -> `get_package`).
- What: every other consumer of a channel record normalises kind through `_record_key` (`.strip().lower()`, dash-release-jobs-7's 2026-09-11 fix), and `companion_packages` stores kind folded. The retraction path folds `platform` but not `kind`. So a recall entry spelled `"kind": "Companion"` matches no stored row (nothing is un-currented) AND matches no feed record (the build stays on offer and stays auto-publishable), and neither half says anything: `retract_package` returns False for "we never published that", which is indistinguishable from "you spelled it wrong".
- Failure scenario: the vendor recalls a bad companion build with a capitalised kind in the channel's `retracted` list. Every customer dashboard verifies the channel, logs nothing, keeps the build current and keeps offering it to the fleet. The module's own comment says a recall "is the one channel message whose SUPPRESSION is the attack" - this is suppression by a typo.
- Evidence: read of the three call sites; `db.retract_package` -> `db.get_package` uses `WHERE kind=? AND platform=? AND version=?` with no folding. `_valid_records` compares `recalled` against `str(rec.get("kind",""))`, which for any record that survived the `-7` spelling gate is already lower-case.
- Ledger: new (a gap left by the CR-260 fix for dash-release-jobs-7, which folded `_record_key` but not `channel_retractions`).
- Suggested fix: fold `kind` in `channel_retractions` exactly as `platform` is folded, and log a warning when a well-formed retraction matches neither a stored package nor a feed record, so a mis-spelled recall is visible rather than a no-op.

### dash-release-jobs-5 - re-applying the version already running erases the rollback target
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/dashboard_update.py:1384` (`"previous": previous if previous and previous != version else ""`).
- What: `""` in `current.json`'s `previous` means "the image" to `deploy/select_code_root.py`. When an admin re-applies the version already current (the documented way to recover a tree whose files were damaged, and what `--allow-replace` republishes produce), `previous == version` and the real previous tree's name is discarded - not because there is no previous tree, but because the arithmetic cannot express "unchanged".
- Failure scenario: running 0.7.48, apply 0.7.49, apply 0.7.49 again (a retry after a failed swap, or a re-published bundle). `previous` is now `""`. The admin then hits ROLLBACK expecting 0.7.48 and gets the IMAGE's much older code with the live database at schema v53 - `schema_rollback_check` will call it `unknown`, which does not refuse.
- Evidence: read of `apply`; `rollback` and `select_code_root` both read `previous` as the fallback target, and `""` is documented in the same line as meaning the image.
- Ledger: new.
- Suggested fix: when `previous == version`, carry the existing `current.json`'s `previous` forward unchanged instead of blanking it.

### dash-release-jobs-6 - the install worker's crash handler can itself crash and leave the wizard spinning
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cli_tools.py:1024-1042` (`_install_worker`'s `except`).
- What: CR-266a's new error message calls `spec(name).label` INSIDE the handler whose whole job is to guarantee that "every failure has to become a status". `spec()` raises for a name it does not know; `_unexpected` and `install_supported` both guard the same lookup with `TOOLS[name].label if name in TOOLS else ...` but this one does not. If it raises, `_set_status(... state="error" ...)` never runs and the page polls a status that stays `installing` for ever - exactly the state the handler exists to prevent.
- Failure scenario: needs a name that passed `_tool(name)` at the route and is absent from `TOOLS` by the time the thread's handler runs (a partial deploy swapping the module under a running thread, which is precisely what a dashboard code update does). Narrow, but the cost is the unbounded spinner CR-266a was written to remove.
- Evidence: read of the three sites; `_unexpected` at `:1963` and `install_supported` at `:625` both use the guarded form.
- Ledger: related to CR-266a.
- Suggested fix: use `TOOLS[name].label if name in TOOLS else name` here too, and wrap the whole handler body so the `_set_status(state="error")` is the last thing that can be skipped.

## Coverage note

Not reached: the backup/prune/restore half of `dashboard_update.py` (`backup_databases`, `prune_backups`, `prune_code_trees`, `restore_backup`, `snapshot_before`) and its `stage_verify` subprocess protocol; most of `cli_tools.py`'s pty sign-in flow and `cli_env`; most of `ai_providers.py`'s probe cache and `test_provider`/`_live_api_check`; `tools/release_key.py`'s bake/rotate paths; `ed25519.py` (read only far enough to confirm it is the pinned copy). The dashboard suite has no test at all for `finish_restart` under an unwritable data directory (finding 1), none for `github_upload`'s new skip against an asset in a non-`uploaded` state (finding 3), and none for a `retracted` entry with a non-folded `kind` (finding 4) - the existing recall tests all use canonical spellings.

CR-280 (macOS certificate verification, OPEN) was checked against this territory: nothing here runs on a Mac. `release_feed._open_following_https_redirects` and `cli_tools._fetch_bytes`/`_download` execute only in the dashboard container (Linux, system CA bundle), and `tools/publish_*.py` shell out to `gh` rather than using urllib, so none of them is a second instance of the frozen-Python-no-CA-bundle fault. The Mac-side callers (`companion/upgrade.py`, the sidecar manager) belong to comp-app and comp-music-ytdl-jobs.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/api.py`: the human PUT publish route is the other writer of `git_dirty`; worth checking it coerces the same way `release_feed._feed_flag` now does, or the two doors disagree about the same string.
