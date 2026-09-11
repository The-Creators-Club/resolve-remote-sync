# server-tools - the NAS-side deploy (`server/*.py`) and the release tooling (`tools/*`, `bench/`)

Files read (with approximate coverage): `git diff 40f931a..HEAD -- server tools bench`
in full (30 files, ~1700 added lines); `server/install_dashboard_app.py` -
every hunk plus `mount_target`, `compose_config`'s volume list, `install_tree`,
`upload_tree`, `ship_dashboard_docs`, `_stage_docs_tree`, the new cards
snapshot block (~600 lines read closely, the rest of the 5900-line script
skimmed for callers); `tools/ship.ps1` (step 0a), all of `tools/ship_gates.ps1`,
`tools/check_deploy_drift.ps1` (the new TIMELINE CARDS section + the watch
loop + the Write-Ok/Drift/Unknown helpers and the VERDICT block),
`tools/build_dashboard_bundle.py` (TREES/FILES/collect_files),
`tools/jobs.py` + `tools/publish_package.py` (`Http.send`),
`tools/make_product_repo.ps1` (diff only). Both sides of two wires:
`dashboard/src/ccsync_dashboard/published_docs.py` and
`api._rollout_block` / `api._rollout_platforms_block` / `db.rollout_status`.
Tests: all five changed/new server test files and all three changed/new tools
test files read in full. `bench/` unchanged since 40f931a and not read.

Tests run:
`cd server && ../dashboard/.venv/Scripts/python.exe -m pytest tests/test_bug_hunt_2026_09_11_server_tools.py tests/test_cards_snapshot.py tests/test_image_mode.py tests/test_deploy_resilience.py tests/test_snapshot_mount.py -q` (Git Bash) -> **121 passed**
`cd tools && ../dashboard/.venv/Scripts/python.exe -m pytest tests/test_bug_hunt_2026_09_11_server_tools.py tests/test_build_dashboard_bundle.py tests/test_release_scripts.py -q` -> **103 passed**
Em-dash scan of the six changed source files -> clean.
No NAS, no dashboard, no live process touched.

## Findings

### server-tools-b-1 - the cards snapshot deploy ships a commit and never says the checkout is dirty
- Severity: medium
- Confidence: CONFIRMED
- Where: `server/install_dashboard_app.py:307-351` (`resolve_cards_tree`, `export_cards_snapshot`), `server/install_dashboard_app.py:285-304` (`cards_head_moved_on`), `tools/check_deploy_drift.ps1:718-767`
- What: until today `[timeline_cards] src` shipped the operator's WORKING COPY; since the snapshot change the default ships `main`'s tracked tree instead, and nothing anywhere compares the two. `git status --porcelain` is never run (`grep -n "porcelain\|diff --quiet\|dirty" server/install_dashboard_app.py` finds only comments), and `cards_head_moved_on` compares the shipped commit against the ref's HEAD - which are equal precisely when the work is uncommitted. So the one state the change was written to prevent (half-finished edits shipping) is now inverted into a state nothing detects: finished edits NOT shipping.
- Failure scenario: the owner edits `Resolve/MulticamPipeline`, tests the page against the local agent, does not commit (the 2026-09-10/11 Cards waves are both recorded as UNCOMMITTED in this session's own memory), then runs `install_dashboard_app.py`. The deploy prints `Timeline Cards snapshot: <sha> (main) ... ` with no qualifier, swaps `cards-web`, restarts the container, `check_deploy_drift.ps1` then prints `OK /cards was shipped from main at <sha>, which is still its head`, and `/cards` serves the code from before the wave. Every channel says success; the page did not change. The previous recipe at least failed in the direction the operator could SEE.
- Evidence: read `resolve_cards_tree` -> `export_cards_snapshot` -> `git archive <sha>:<prefix>`; no status call on the path. `cards_head_moved_on` returns `""` when `head == commit`. `server/tests/test_cards_snapshot.py` deliberately leaves `handler.py` dirty in `make_repo` and asserts only that the COMMITTED bytes ship (line 89) - no test asserts anything is said about the edit that did not.
- Ledger: related to CR-247 / the 2026-09-11 cards snapshot deploy (new defect introduced by it; not in KNOWN_BUGS)
- Suggested fix: in `export_cards_snapshot`, after resolving the sha, run `git status --porcelain -- <prefix>` in the repo and, when it is non-empty and `ref` resolves to the checked-out branch, print a loud NOTE naming the count of modified/untracked files and the sentence "these are NOT in this deploy - commit them first". Put the same fact in the marker (`dirty_at_export=<n>`) and have `check_deploy_drift.ps1` downgrade its OK line when the working tree still differs from the shipped commit.

### server-tools-b-2 - `rollout_platforms` and `rollout_status` bucket a NULL platform differently, so the -EmitKindExtras gate refuses on a phantom platform
- Severity: medium
- Confidence: CONFIRMED
- Where: `tools/ship_gates.ps1:110-121` (the `$covered` loop), and the other side at `dashboard/src/ccsync_dashboard/api.py:1546-1552` (`_rollout_platforms_block`) vs `dashboard/src/ccsync_dashboard/db.py:4293` (`rollout_status`)
- What: `machine_state.platform` is NULLABLE - it was added by `SCHEMA_V8` as a bare `ALTER TABLE machine_state ADD COLUMN platform TEXT` (`db.py:175`, no default), and `db.record_report`'s upsert keeps a NULL with `COALESCE(excluded.platform, machine_state.platform)`. `db.rollout_status` maps that machine to **`windows`** (`str(... or "windows")`); the new `_rollout_platforms_block` maps the same machine to **`unknown`** (`str(row["platform"] or "").strip().lower() or "unknown"`). `Get-KindExtrasVerdict` then finds a platform with a positive machine count that no channel covers, and emits a straggler.
- Failure scenario: one `machine_state` row with a NULL or empty `platform` (a database carried forward from before v8, a row written by a path that does not set it). `-EmitKindExtras` is refused for ever with `1 unknown computer(s) have no current build on this dashboard, so their versions were never checked against 0.9.55` - a platform that does not exist, about a machine that WAS checked (as windows, inside the windows channel), and with no command anywhere that clears it. The operator cannot distinguish this from a real straggler.
- Evidence: `db.py:175` (`SCHEMA_V8`), `db.py:6943` (`COALESCE(excluded.platform, ...)`), `db.py:4293` vs `api.py:1549`. `tools/tests/test_bug_hunt_2026_09_11_server_tools.py` only ever feeds platform keys that also appear as channels, so the suite cannot see it.
- Ledger: CR-247 does not fully fix server-tools-1 (the fix's own new block introduces the divergence)
- Suggested fix: make `_rollout_platforms_block` use the same normaliser as `rollout_status` - `COALESCE(platform,'windows')`, lower-cased - so the two blocks in one health body cannot name different platforms for the same row. (Or have `Get-KindExtrasVerdict` treat `unknown` as covered by any channel; the dashboard-side fix is the honest one.)

### server-tools-b-3 - an explicit `--cards-src-dir` / `CARDS_SRC` deploy leaves a stale record, and the drift doctor reports it as OK
- Severity: medium
- Confidence: CONFIRMED
- Where: `server/install_dashboard_app.py:5733-5740` (`if cards_info and not args.dry_run: write_cards_deploy_record(...)`), read back at `tools/check_deploy_drift.ps1:725-767`
- What: the record `~/.ccsync/state/cards_deployed.json` is written ONLY when a commit snapshot was shipped. The documented escape hatch (`--cards-src-dir`, `CARDS_SRC`) ships a working directory and sets `cards_info = None`, so the previous deploy's record survives untouched and is never invalidated. The doctor has no NAS shell and reads nothing else.
- Failure scenario: an operator ships a working copy to debug something (`--cards-src-dir E:\...\MulticamPipeline`), then runs `check_deploy_drift.ps1`. It prints `deployed commit <old sha> (main)` and `OK /cards was shipped from main at <old sha>, which is still its head` about a tree that is nobody's commit. That is exactly the wave-4 rule the same section's own comment cites ("an unverified check is NOT CHECKED, never OK") broken by the new code.
- Evidence: `resolve_cards_tree` returns `(Path(explicit), None, "")` for the override (line 328-331); `write_cards_deploy_record` is behind `if cards_info`. `server/tests/test_cards_snapshot.py::test_an_explicit_directory_still_ships_as_it_stands` asserts `info is None` and stops there - it never checks what happens to the record.
- Ledger: new (introduced by the 2026-09-11 cards snapshot deploy)
- Suggested fix: on the override path write a record too, with `commit=""` and `override=<path>`; make the doctor print `?  /cards was last shipped as the DIRECTORY <path>, not a commit - NOT CHECKED` for it. An absent commit must not be readable as an old commit.

### server-tools-b-4 - the drift doctor's new TIMELINE CARDS section runs on sites that have no Timeline Cards
- Severity: low
- Confidence: CONFIRMED
- Where: `tools/check_deploy_drift.ps1:718-733`
- What: the section is unconditional. It never asks whether this site has `[timeline_cards] src` / `enabled`, so any machine that does not deploy Cards - every customer who did not buy it, and any base rig that has never run the deploy - gets a permanent `? no cards deploy record at ...\state\cards_deployed.json -- this machine has not shipped /cards since 2026-09-11 (docs\CARDS_DEPLOY.md). NOT CHECKED, not OK.`
- Failure scenario: a customer's operator runs the read-only doctor, sees a "NOT CHECKED, not OK" line pointing at an internal runbook for a feature they do not have, and either chases it or learns to ignore the doctor's `?` lines - which is the expensive outcome, because `?` is how three other real checks report.
- Evidence: no `[timeline_cards]`, `SITE_CARDS`, `cards_src` or site-manifest read anywhere in the section; the printers are pure (`Write-Unknown` at line 95 only writes to the host), so the VERDICT block is unaffected - it is noise, not a false verdict.
- Ledger: new
- Suggested fix: skip the whole section, or print one `skipped - this site has no Timeline Cards` line, when neither `CCSYNC_CARDS_RECORD`, a record file, nor a `[timeline_cards]` key in the site manifest is present.

### server-tools-b-5 - `_stage_docs_tree` can still raise out of a function documented never to
- Severity: low
- Confidence: CONFIRMED
- Where: `server/install_dashboard_app.py:4357-4362` (the two `published.PUBLISHED_*` reads) against the contract at `server/install_dashboard_app.py:4319-4321`
- What: `published_docs_module()` is carefully written to swallow every load failure and return `None`, and its docstring says None means ship the required set. But the attribute reads that follow are outside that guard: a module that imports cleanly and does not define `PUBLISHED_DOCS`/`PUBLISHED_TREES` (a checkout where the constants are renamed, a half-written file, a future dashboard that moves the list) raises `AttributeError` from `_stage_docs_tree`. `ship_dashboard_docs`'s `try/finally` only removes the temp dir - it does not catch - so the exception escapes to `main()`, and it does so at step 2a, AFTER the code swap at step 2 has already happened.
- Failure scenario: a deploy that has already swapped `/app` dies with a traceback instead of the documented `NOTE: the licence agreement and the help guide were NOT installed`, and skips the container restart that the swap requires (`install_tree`'s own docstring: the running container serves the old inode until restarted).
- Evidence: `ship_dashboard_docs` docstring line 4319: "every failure is a printed NOTE and False, never an exception". No `except` around `_stage_docs_tree(...)`.
- Ledger: new (introduced by the server-tools-2 fix)
- Suggested fix: read the two names with `getattr(published, "PUBLISHED_DOCS", ())`, and wrap the `_stage_docs_tree` call in `ship_dashboard_docs` in a `try/except Exception` that prints the documented NOTE and returns False.

### server-tools-b-6 - `cards_repo_for`'s prefix fallback silently turns a subtree export into a whole-repo export
- Severity: low
- Confidence: PLAUSIBLE
- Where: `server/install_dashboard_app.py:118-137` (`cards_repo_for`), consumed at `server/install_dashboard_app.py:165-171`
- What: when `src.resolve().relative_to(root.resolve())` raises (`ValueError`/`OSError`), the function swallows it and returns `prefix = ""`. `export_cards_snapshot` then builds `spec = sha` instead of `sha:Resolve/MulticamPipeline`, skips the `cat-file -t` subtree check (it is guarded by `if prefix:`), and exports the ENTIRE repository. The one case `relative_to` is there for - `src` is the repo root - is indistinguishable from the failure case.
- Failure scenario: `[timeline_cards] src` reached through a `subst` drive, a junction, or a UNC path whose `git rev-parse --show-toplevel` spelling does not resolve to the same object. The deploy exports the whole `Editing` repo (hundreds of MB), `ship_cards` is False because `multicam_pipeline/cards/handler.py` is not at its root, and the operator is told `This tree is the snapshot of commit <sha>, so the package is missing AT THAT COMMIT, not on disk` - which sends them to look at the wrong repository state. `/cards` is left on the previous tree.
- Evidence: read both functions; `test_cards_snapshot.py` only exercises the happy subtree case and the mocked not-a-repo case, never a failing `relative_to`.
- Ledger: new
- Suggested fix: distinguish the two - return an explicit error when `relative_to` raises (naming both paths), and only allow `prefix = ""` when `src.resolve() == root.resolve()`.

### server-tools-b-7 - `ro,rslave` reaches TrueNAS's middleware, and nothing offline can say it is accepted
- Severity: low
- Confidence: PLAUSIBLE
- Where: `server/install_dashboard_app.py:1090` (`snapshot_volumes`), delivered at `server/install_dashboard_app.py:2638` -> `compose_config` -> the `custom_compose_config` POST described at `server/install_dashboard_app.py:145` / `:2880`
- What: the server-tools-3 fix changes a compose short-syntax bind from `host:/snapshots:ro` to `host:/snapshots:ro,rslave`. Unlike a `docker run -v`, this dict is POSTed to the TrueNAS middleware, which validates it before creating or updating the app. Whether that validator accepts a propagation flag in the third field is not verifiable from this repo and was not verified live (the prior hunt recorded server-tools-3 as "CONFIRMED on the mechanism; NOT verified live"). The suite only asserts the string this code produces (`test_the_compose_body_carries_the_propagation_option`), which cannot fail on a rejection at the other end.
- Failure scenario: the middleware rejects the volume spec; the app update fails on the deploy happening tonight, on the one step where the snapshot mount is the only thing that changed - and the error will name a volume string, not this change.
- Evidence: read `snapshot_volumes`, `compose_config`'s volume list and `mount_target`; read both tests. `mount_target` itself is fine (positional split, index 1).
- Ledger: related to CR-247 / server-tools-3
- Suggested fix: before the ship, run the deploy with `--dry-run` against the real backend if that exercises the validation, or push the change on its own so a rejection is unambiguous; and keep a fallback that drops `rslave` and prints the propagation note if the app update is refused on the volume spec.

## Coverage note
Not reached: `bench/` (unchanged since 40f931a), `server/publish_db.py`,
`server/setup_snapshots.py`, `server/create_api_key.py` and the other untouched
`server/*.py` scripts, `tools/publish_latest.py`, `tools/release.ps1`,
`tools/check_licenses.py`, `tools/gen_notices.py`, `tools/release_key.py` -
none of them changed in this diff. I ran only the eight test files that
exercise the changed code, not the whole `server/` or `tools/` suite (owner
rule: the full gate runs once, centrally).

What the suites cannot cover, and I could not either: anything that needs the
NAS (server-tools-b-7's middleware validation, the `rslave` propagation end to
end, and whether `.zfs/snapshot` automounts now reach the container at all),
and the real Timeline Cards repository (every cards test builds a throwaway
repo, so nothing exercises the actual `E:\Projects\Editing` toplevel/subtree
spelling that server-tools-b-6 is about).

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/api.py:1546`: `_rollout_platforms_block` disagrees with `db.rollout_status` on a NULL platform - the dashboard half of server-tools-b-2, above.
- `dashboard/src/ccsync_dashboard/help.py`: the whole of server-tools-2's disclosure fix now rests on the read-side allow-list (`published_docs.is_published`) for anything already on a customer's disk from an older deploy; worth a dash-mounts-ui/security check that the browse list and the raw-file route both go through it.
