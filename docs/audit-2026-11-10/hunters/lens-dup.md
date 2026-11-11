# lens-dup - cross-cutting duplication, dead code, weight and hot spots across all four trees

Files read (approximate coverage): HUNTER_BRIEF, ccsync CLAUDE.md, every `hunters/*.json` plus the `.md`-only reports (cards-library, cards-resolve, editor-client, editor-server, sorter-node, sorter-page, sorter-py) for already-filed streamline/deploy items; both copies of every twin named in the brief (by script, then by hand where the script showed drift); `docs/CARDS_EDITOR.md` (beside/flip), editor `PARITY.md` (native apps rows); `companion/build.spec`; `companion/tests/test_jobs_media.py`, `test_broll_vlm_vendored.py`, `server/tests/test_cross_component.py` (vendored pins); Cards `handler.py` (READONLY_BLOCK, do_POST) and `project_engine.py` (`_apply`, readonly guards); `dashboard/src/ccsync_dashboard/db.py` (editor_prefs), `truenas_client.py`; footage-sorter `.gitignore` + `data/`.

Probes run (all scripts and outputs under `scratchpad\lens-dup\`):
- `twins.py` / `funcdiff.py`: whitespace-normalised, comment-stripped line diff of each twin and per-function diff of the shared names.
- `imports.py`: `ast` import graph of 9 packages (companion, dashboard, broll_index, app, musicweb, ytdlweb, music indexer, multicam_pipeline, footage_sorter), then a string grep for each never-imported module.
- `deadfuncs2.py` / `deadfuncs5.py`: every top-level function / class / method >= 15 (and >= 5) lines with zero word-references anywhere in the three git trees plus the editor worktree outside its own file (decorated functions and the `_do_` / `_op_` getattr-dispatched families excluded).
- `deadjs.py`: every tracked `.js` / `.mjs` / `.css` outside tests that no other tracked file names.
- `deadkeys.py`: 167 companion `DEFAULTS` keys vs every quoted mention in companion / installer / onboarding / dashboard.
- `deadroutes.py`: 306 decorator-registered dashboard routes vs every client tree (companion, templates, static, broll / music / ytdl static, Cards, sorter, editor, tools, server, installer).
- `deps.py`: every `pyproject.toml` dependency (and extra) vs `import` / quoted module names in that component.
- `bigfuncs.py`: the 25 largest Python functions in the product by `ast` line span.
- `collect_all("onnxruntime")` run in the companion venv (PyInstaller 6.21.0) to measure what the spec actually collects.
- `git ls-files` size rollups per repo.

## Summary tables

### (1) Twins

| Twin | Normalised lines (A / B) | Shared | Pinned equal by a test? | Drifted? | Verdict |
|---|---|---|---|---|---|
| `ed25519.py` companion / dashboard | 145 / 145 | 100% (byte-identical) | yes, `companion/tests/test_upgrade.py` | no | deliberate (three deployment units, docstring); leave |
| `crash_report.py` companion / dashboard | 763 / 323 | 24% (130 lines) | no | n/a - two different modules sharing a name and a handful of helpers | not a twin; a shared module would save ~100 lines and add a cross-unit import the frozen exe cannot make; leave |
| `ffmpeg_tools.py` companion / broll indexer | 913 / 843 | 17% (145 lines) | preview flags pinned by importing the indexer (`test_ffmpeg_tools.py`, audit F8); `frames_match` / `_plausible_frames` / `parse_frame_count` / `count_frames_cmd` NOT cross-pinned | YES - see lens-dup-4 | rehomed copy by design (2026-08-10 docstring); extend the existing import-based pin |
| `broll_vlm/*` (5 modules + prompt) vs `broll_index/*` | e.g. local_runtime 894 / 869 | 94-99% (100% below the vendor marker) | yes, three times: `release.ps1` byte gate, `server/tests/test_cross_component.py`, `companion/tests/test_broll_vlm_vendored.py` | no | deliberate (keeps anthropic/xxhash/yaml/jieba out of the exe, ~50 MB); leave |
| `ingest_batches.py` broll / music | 1,239 / 1,163 | 18% | no | yes | already filed: web-music-9 |
| `ingest.js` broll / music | 1,837 / 1,435 | 22% | no | yes | same family as web-music-9 |
| `style.css` broll / music / ytdl | 2,425 / 1,818 / 1,863 | 58% b-m, 57% b-y, 68% m-y | no | yes | already filed: web-broll-8 |
| `webtheme.py` Launcher / MulticamPipeline | 37 / 37 | 100% | `deploy/install_nas.py` reports a stale copy | no | deliberate vendoring (the build context cannot reach Launcher); 37 lines, leave |
| `telemetry_policy.FIELDS` / `telemetry_fields.FIELDS` | 257 / 249 | 20% of the files (the FIELDS tables are pinned equal) | yes (CLAUDE.md, LG-1) | no | deliberate; leave |
| Windows / macOS installers | - | - | - | yes | already filed: ops-install-2 |
| sorter `lib/*.js` + `server.js` / `footage_sorter/*.py` | ~7,200 JS lines | parity oracle | 13 `test_parity_*.py` run the JS | yes (sorter-node-3) | already filed: sorter-node-1/-2/-3 |
| companion `teracopy.py` (875) / sorter `lib/teracopy.js` (738) / sorter `ingest/tray/TeraCopyStatus.py` (160) | - | port (docstring says so) | no | the JS + tray copies are the retired path | goes with sorter-node-1/-2 (1,000 lines with the tray script) |
| Cards `library_engine.py` ffmpeg recipes / companion `jobs_media.py` | 3 recipes | identical TODAY (checked by hand: aac copy, opus 64k, 480p x264) | pinned only against a LITERAL in the companion test | no | see lens-dup-6 |
| Old Cards page `cards/page/*.js` / rebuilt editor | 32,741 JS lines (24 files; the brief's ~27,000 is low) + 28,022 lines of JS page tests (44 files) / 91,016 TS lines + 53,239 TS test lines | parallel implementation, PARITY.md tracks it | n/a | by design during "beside" | see lens-dup-1 |

### (2) Dead code (survives a grep for the name as a string, all three trees + the editor)

| What | Where | Lines | Risk of removal |
|---|---|---|---|
| `editor_prefs.project_root_override` feature: `set_/get_project_root_override` (0 callers, 0 tests), `get_detected_project_root` (0 callers), table only ever touched by db.py | dashboard `db.py:8382-8427`, `:10666`; schema `:502`, `:884-896` | 52 code + table | low (keep the migration, drop the functions; table can stay empty) |
| `truenas_client.py` shim, "KEPT FOR ONE RELEASE" since 2026-08-17 (dozens of releases); no importer anywhere | dashboard `truenas_client.py` | 47 | low |
| `machine_by_machine_id` (0 refs) | dashboard `db.py:5544` | 19 | low |
| `media_paths` (0 refs; `jobs_runner._media_paths` is a different function) | Cards `library/library_reader.py:758` | 29 | low |
| `probe_info` (0 refs, vendored downloader) | ytdl `ytdlweb/vendor/downloader.py:684` | 15 | low (check the vendor marker first) |
| `all_prompts` | music `musicweb/vocab.py:156` | 12 | low |
| `fold_many` | Cards `transcripts/mono_fold.py:432` | 12 | low |
| `under_folders`, `_hash` | sorter `ledger_rules.py:146`, `moveplan.py:304` | 19 | low |
| 13 more 5-14 line functions with zero references (`live_counts`, `delete_key`, `read_backup_record`, `parse_duration`, `fmt_duration`, `clip_color_hex`, `sidecar_status`, `library_available`, `consolidate_in_flight`, `upgrade_in_flight`, `_nas_credential_key`, `get_detected_project_root`, `set_project_root_override`) | scratchpad `deadfuncs5.txt` | ~95 | low |
| Functions reached ONLY from tests (>= 15 lines): `apply_tailnet_only_options` 32, `spec_hidden_imports` 30 (a tool helper; fine), `action_open_skipped_folder` 21, `note_ytdl_login_progress` 17, `_section_models` 16 (test helper by design), `expected_frames` 16 | various | 132 | medium: two of these are test helpers by design; read each before removing |
| Tracked logs / backups: footage-sorter `data/` (8 manifest backups, 6 moveplans, dupes, 2 server logs) | footage-sorter `data/` | 23.6 MB | see lens-dup-2 |
| Never-imported Python modules | 0 in any package: every candidate the ast graph found is reached by name (Cards `pipeline.py` subcommands) or is a script with `__main__` | 0 | - |
| Unreferenced JS / CSS files | 0 | 0 | - |
| Companion config keys read nowhere | 0 of 167 (the six that look unread are reached through `IngestKind.cfg_key`) | 0 | - |
| Dashboard routes no client calls | 7 of 306, and all 7 are documented JSON twins of htmx partials (`/api/v1/me/*`, ACCOUNT_PAGE_FEATURES "every partial calls the SAME service function its JSON twin") or documented API (`POST /projects/link`, `/admin/devices/approve`, docs/API.md) | 0 dead | - |
| Test files for modules that no longer exist | 0 (suites are green and only third-party `importorskip`s exist) | 0 | - |

Total genuinely dead Python: about **320 lines** (52 + 47 + ~220 zero-reference functions), plus 132 test-only lines. The product's Python is unusually well pruned; the duplication cost is in the two parallel Cards pages and the retired sorter Node path, not in stray code.

### (3) Weight

| Repo | Tracked | Biggest items | Ships? |
|---|---|---|---|
| ccsync | 64.3 MB, 2,264 files | `docs/mobile/` 9.9 MB of PNG; `KNOWN_BUGS.md` 2.4 MB; bug-hunt JSON (`docs/bug-hunt-2026-09-24/wave2_results.json` 0.95 MB); `db.py` 0.69 MB, `api.py` 0.66 MB, `app.py` 0.66 MB | none of `docs/` ships (`.dockerignore` names the customer docs individually); clone cost only |
| footage-sorter | 231 files | `data/` 23.6 MB (lens-dup-2); `docs/ui/*.png` ~4 MB | `data/` does not ship; it IS on GitHub |
| MulticamPipeline | - | Story Deck screenshots 46 MB (cards-storydeck-8); 3.7 MB the mount never imports (cards-storydeck-7, deploy-nas-7) | already filed |
| editor | - | 11.6 MB dist nobody downloads, 1.29 MB eager bundle (editor-client-7) | already filed |
| companion exe | 48 MB onefile, 108 MB extracted (lens-disk-3) | onnxruntime: 306 `.py` files (3.87 MB) + 156 submodules of `transformers` / `quantization` / `tools` the code never imports (lens-dup-3) | yes, every editor machine, extracted twice per start |

Dependencies: every `pyproject.toml` dependency in the nine Python components is imported by its component or is a deliberate extra for a mounted tree (the dashboard's `broll` / `music` / `cards` / `ytdl_unblock` extras serve code that lives in the other trees; `soundfile` is librosa's backend; `PyYAML` is used by `server/tests`). The editor's `package.json` has 5 runtime deps, all used. Sorter `package.json` (express) is the retired Node server (sorter-node-2). Nothing to remove.

### (4) Hot spots - the ten largest Python functions

| # | Lines | Function | Where | Would a table / split remove a bug class? |
|---|---|---|---|---|
| 1 | 1,981 | `make_handler` (contains `do_POST` 1,003 lines / 69 path branches, `do_GET` 559) | Cards `cards/handler.py:128` | YES - lens-dup-5: the read-only guard is a second hand-kept list beside the branch chain and has already drifted (`/api/fade`). A `ROUTES = {path: (fn, writes_cut, needs_version)}` table makes "is this a write" a column of the route, not a separate set. Saving: the class of bug, and ~150 lines of `elif path ==` scaffolding. But this handler retires with the old page (lens-dup-1), so fix the one entry now and do not refactor it. |
| 2 | 1,482 | `main` | ccsync `server/install_dashboard_app.py:5936` | Partly: deploy-nas-10 (a Cards / Sorter deploy runs the whole site provisioning) is the real cost; splitting `main` into "provision" and "ship the mounted trees" phases is that fix. Cite, not re-file. |
| 3 | 1,207 | `create_app` | ccsync `dashboard/app.py:671` | No clear bug class: it is middleware + router registration whose ORDER is load-bearing (CARDS_EDITOR.md flip step 2). Splitting it would hide the order. Leave. |
| 4 | 1,000 | `api_report` | ccsync `dashboard/api.py:10861` | Partly: ~20 per-section blocks (lanes, file_moves_applied, resolve_undo_applied, local_manifest, media_tree, ...) each with its own "absent means untouched" rule, then ~10 reply-side `commands.*` blocks. A per-section handler table (`REPORT_SECTIONS = [(key, writer, telemetry_category)]`) would make the LG-1 strip ("strip BEFORE any write") structurally true instead of by ordering, and match `telemetry_fields.FIELDS`. Saving: one class (a new section written before the strip); estimated 150-200 lines. Medium effort, medium risk; not filed as a finding because no drift was found. |
| 5 | 921 | `App.__init__` | ccsync `companion/app.py:1669` | No: 18 branches, it is attribute initialisation. The cost is that every subsystem's state lives on one object (comp-app territory). Leave. |
| 6 | 605 | `compose_config` | `server/install_dashboard_app.py:3120` | 4 branches: a template in code, pinned by `test_compose_template.py` goldens. Leave. |
| 7 | 559 | `do_GET` | Cards `handler.py:388` | as #1 |
| 8 | 502 | `main` | `tools/publish_feed.py:1242` | deploy-release territory |
| 9 | 466 | `create_app` | sorter `footage_sorter/web.py:95` | route table already (Starlette `Route` list); leave |
| 10 | 412 | `_run_once_locked` | companion `sync/rclone_lane.py:4737` | comp-sync territory |

Also: `sync_guard()` 282 lines (comp-app-4, already filed as a table candidate).

## Findings

### lens-dup-1 - The old Cards page has no retirement step: ~61,000 lines and a second implementation of every Cards feature stay live after the flip
- Category: streamline
- Severity: medium
- Confidence: CONFIRMED
- Where: MulticamPipeline `multicam_pipeline/cards/page/*.js` (24 files, 32,741 lines), `tests/*.js` (44 files, 28,022 lines, all page tests bar `storydeck_cdp.js`); ccsync `docs/CARDS_EDITOR.md:161-180` ("The flip, later"); editor `PARITY.md:40, :291` ("the Windows and Android apps still load the old page")
- What: The plan is "beside first, then flip", and the flip moves the old page to `/cards/old` "for one release for rollback" but names no step that deletes it, its tests, its `handler.py` page routes, or the offline seam the native apps depend on. Until it goes, every Cards fix or feature has two homes (32.7k JS vs 91k TS), and PARITY.md is a hand-kept ledger of which one has it.
- Cost / failure scenario: every Cards change today, x2 implementations; the old page's JS test suite (28k lines) runs in the Cards gate on every iteration. At the flip the native apps (Windows, Android: 8,579 lines in `apps/`) still point at the old page, so the old page cannot be deleted then either: the apps are the hidden blocker.
- Evidence: `git ls-files multicam_pipeline/cards/page | xargs wc -l` = 32,741; `tests/*.js` = 44 files / 28,022 lines; editor non-test TS 91,016, TS tests 53,239; CARDS_EDITOR.md phase 5 text; PARITY.md rows 40 and 291.
- Ledger: new
- Suggested change: add a phase 6 to CARDS_EDITOR.md: (a) move the native apps to the new editor (NATIVE-APPS.md row 291 is "partial"), (b) one release after the flip, `git rm` `cards/page/`, the page tests, and the page-only handler routes (keep `/agent/*` and whatever `cards_tunnel` and the companion role use), (c) drop the rows from PARITY.md. Must not break the `/cards/agent/*` fleet routes or the companion's `jobs_mulcam_pipeline` import.
- Effort / risk: M effort; low risk once the apps are moved (rollback is the one setting the doc already names).

### lens-dup-2 - The footage sorter tracks 23.6 MB of manifest backups, move plans and logs, with real interviewee names, on GitHub, against its own .gitignore
- Category: security
- Severity: medium
- Confidence: CONFIRMED
- Where: footage-sorter `data/manifest.backup-*.json` (8 files), `data/moveplan*.json` (11), `data/dupes-20260819.json`, `data/server.err.log`, `data/server.out.log`, `data/episodes.json`, `data/settings.json`; `.gitignore` lines for `data/manifest.json`, `data/roster.json`
- What: `.gitignore` excludes `data/manifest.json` and `data/roster.json` with the comment "names of real people, and regenerable in one command, so it stays out of the repo", yet eight full timestamped copies of that manifest (1.6-2.6 MB each) and the executed move plans are tracked, committed in "checkpoint before the E:\Projects reorganisation", and the repo's remote is `github.com/The-Creators-Club/footage-sorter`. A sample contains `Interviewees/<full Chinese and English name>` paths.
- Cost / failure scenario: 23.6 MB per clone (the sorter's code is ~1 MB), and the interviewee list of a documentary in a repo that is going to be shared as part of a commercial product; any future collaborator or a public flip of the repo exposes it.
- Evidence: `git ls-files -z data | xargs -0 du -ck` = 23,576 KB; `git remote -v`; grep of one backup for `Interviewees/`; `.gitignore` text quoted above.
- Ledger: new
- Suggested change: `git rm --cached data/*.backup* data/moveplan* data/dupes-* data/server.*.log` and add `data/*.backup*`, `data/moveplan*`, `data/*.log` to `.gitignore`; the files stay on disk. Decide separately (owner) whether to purge them from history. Must not touch `data/episodes.json` / `settings.json` if a test or the deploy reads them (check `SORTER_DEPLOY.md`).
- Effort / risk: S effort; low risk (history rewrite is the only risky part, and optional).

### lens-dup-3 - The companion build collects all of onnxruntime: 306 .py files (3.87 MB) and 156 submodules of transformers / quantization / tools that the code never imports
- Category: deploy
- Severity: low
- Confidence: CONFIRMED (what is collected); PLAUSIBLE (exact bytes saved in the final exe)
- Where: ccsync `companion/build.spec:80-93` (`collect_all("onnxruntime")`); the only uses are `onnxruntime.InferenceSession`, `SessionOptions`, `get_available_providers` (`music_clap_sidecar`)
- What: `collect_all` defaults to `include_py_files=True`, so every `.py` under `onnxruntime/` is added as a DATA file (extracted raw to `_MEI` on every start) and every importable submodule is added as a hidden import. 156 of the 168 hidden imports are `onnxruntime.transformers.*`, `.quantization.*` and `.tools.*` (graph-optimisation and model-conversion tooling for exporters), which the companion never touches.
- Cost / failure scenario: about 4 MB of extraction and ~1.3k fewer files are not the point at today's 108 MB extraction (lens-disk-3 has that cost: every start and every supervisor start), but these are the cheapest 4 MB to remove, on every editor machine, every launch, twice.
- Evidence: in the companion venv with PyInstaller 6.21.0, `collect_all('onnxruntime')` returned 318 datas of which 306 are `.py` totalling 3.87 MB, 168 hidden imports of which 156 are under transformers / quantization / tools, and binaries `onnxruntime.dll` 18.1 MB + `providers_shared`; grep of `ccsync_companion` for `onnxruntime\.` finds only the three names above.
- Ledger: related to lens-disk-3
- Suggested change: replace `collect_all` with `collect_dynamic_libs("onnxruntime")` + `hiddenimports += ["onnxruntime", "onnxruntime.capi.onnxruntime_pybind11_state", "onnxruntime.capi._pybind_state"]` + the ThirdPartyNotices data line, then let `tools/scan_frozen.py` and a frozen smoke of the CLAP sidecar prove the session still loads. Must not drop the DLL or the providers file.
- Effort / risk: S effort; medium risk (a frozen build that imports fine and fails at first session is the failure shape the spec's comments warn about, so the smoke is required).

### lens-dup-4 - ffmpeg_tools twins: the indexer's copy has no timeout on any of its ten ffmpeg/ffprobe calls, and the "verbatim twin" helpers are not pinned across the two copies
- Category: resilience
- Severity: low
- Confidence: CONFIRMED
- Where: ccsync `broll/indexer/broll_index/ffmpeg_tools.py:45, :279, :432, :499, :586, :731, :764, :782, :853, :960` (every `subprocess.run`, none with `timeout=`) vs `companion/src/ccsync_companion/ffmpeg_tools.py:1016-1038` (`timeout=PROBE_TIMEOUT_SECONDS`); `_plausible_frames` companion `:990` vs indexer `:403`
- What: The two copies share 145 normalised lines. Of the shared helpers, `count_frames_cmd` / `parse_frame_count` / `_parse_fps` / `_tags` are equal, but `count_frames` gained a timeout and a `TimeoutExpired` catch only in the companion, and `_plausible_frames` (whose companion docstring says "a verbatim twin of the indexer's helper") coerces with `float()` only in the companion. `test_ffmpeg_tools.py` already imports the indexer module for the preview flags (audit F8) but does not compare `frames_match`, `_plausible_frames`, `parse_frame_count` or `count_frames_cmd`.
- Cost / failure scenario: the indexer reads originals over SMB on the base rig; an ffprobe stuck on a stalled share read (or a pathological file) blocks that worker forever with no error, and a batch of ~5,000 clips is the scale it runs at. The `_plausible_frames` difference is benign today (both callers pass floats) but contradicts its own "verbatim" claim, which is how the Reproductive Rights "three checks each thought another had looked" defect began.
- Evidence: `funcdiff.py` output (ratios 0.40 / 0.47 for `_plausible_frames` / `count_frames`, unified diff in scratchpad); grep for `timeout` in the indexer file finds none on a subprocess call.
- Ledger: new (idx did not file the timeouts)
- Suggested change: give the indexer's probes the companion's `PROBE_TIMEOUT_SECONDS` (encodes can take a generous per-duration timeout), and add four lines to `test_ffmpeg_tools.py` asserting the indexer's `frames_match`, `_plausible_frames`, `parse_frame_count` and `count_frames_cmd` agree on the same inputs. Must keep `frames_match` exact.
- Effort / risk: S effort; low risk.

### lens-dup-5 - Cards read-only guard is a second hand-kept list beside the route chain and has drifted: /api/fade writes a read-only project
- Category: bug
- Severity: low
- Confidence: CONFIRMED
- Where: MulticamPipeline `multicam_pipeline/cards/handler.py:47` (`READONLY_BLOCK`), `:1138` (the guard), `:1517-1540` (`/api/fade`); `project_engine.py:146` ("the handler's one guard reads this"), `:2928` (`_do_fade` -> `_save`)
- What: `READONLY_BLOCK` lists 53 paths that change the cut; `do_POST` has 64 `path == "/api/..."` branches. `/api/fade` (2026-09-15) changes the cut and is absent from the set; `/api/gain` (2026-10-09), its sibling, is present. `ProjectEngine` relies on the handler ("the handler's one guard"), and `_do_fade` -> `_save` -> `_write_project_text` has no readonly check of its own.
- Cost / failure scenario: a standalone `server.py --project X --readonly` session (the dashboard mount does not use readonly): dragging a fade handle writes the `.cut.md` that was opened read-only. Rare mode, real write.
- Evidence: set difference of the handler's POST paths minus READONLY_BLOCK (22 paths, of which `/api/fade` is the only one that writes the cut file; the rest are reads, AI calls, notes or blocked elsewhere); code paths quoted.
- Ledger: new
- Suggested change: add `/api/fade` to `READONLY_BLOCK`, and make `ProjectEngine._save` refuse when `self.readonly` (a second line of defence that does not depend on the list). The class goes away for good when the old page retires (lens-dup-1); do not refactor the handler into a table now.
- Effort / risk: S effort; low risk.

### lens-dup-6 - The Cards media-job recipes are pinned against a literal, the shape audit F8 already found fails nothing when the other side moves
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: ccsync `companion/tests/test_jobs_media.py:146-172` vs MulticamPipeline `multicam_pipeline/cards/library_engine.py:3993, :4033-4036, :4202-4209`
- What: CLAUDE.md says the three `jobs_media` recipes reproduce `library_engine.py`'s ffmpeg argv VERBATIM because a page in the other repo reads those files. The test compares `jobs_media` with a hand-copied list. They agree today (checked by hand), but if `library_engine.py` changes its crf, gop or bitrate, nothing fails. `test_ffmpeg_tools.py` fixed the same pattern for the indexer by importing the other module (audit F8, 2026-09-17).
- Cost / failure scenario: one edit to `_vid_make` in the Cards repo -> fleet-made proxies and engine-made proxies differ silently; a page reading both sees two encodings for one clip.
- Evidence: test text and the three `library_engine.py` argv blocks.
- Ledger: new
- Suggested change: when the Cards checkout is present (the role already locates it), parse the argv lists out of `library_engine.py` (or expose them as module constants there) and compare; skip with a reason when the checkout is absent, as `test_music_clap_sidecar.py` does.
- Effort / risk: S effort; low risk.

### lens-dup-7 - Dead dashboard feature and an expired shim: editor_prefs.project_root_override and truenas_client.py
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: ccsync `dashboard/src/ccsync_dashboard/db.py:8382-8427` (`set_project_root_override`, `get_project_root_override`), `:10666` (`get_detected_project_root`), `:5544` (`machine_by_machine_id`), schema `:502`, `:884-896`; `dashboard/src/ccsync_dashboard/truenas_client.py` (47 lines)
- What: the per-machine "sticky destination root" setter and getter have zero callers anywhere (no route, template, companion or test), and `editor_prefs` is touched only by db.py. `truenas_client.py` is an import shim marked "KEPT FOR ONE RELEASE ... delete this file once nothing does" on 2026-08-17; nothing imports it (two comments name its old line numbers).
- Cost / failure scenario: about 120 lines read by every engineer working in `db.py` (13k lines) and a table that looks live; small.
- Evidence: `deadfuncs5.py` zero-reference result, confirmed by grep for each name across all four trees.
- Ledger: new
- Suggested change: delete the four functions and the shim (update the two comments that cite `truenas_client.py:165`); leave the table and migrations in place (dropping a table is a schema bump for no gain).
- Effort / risk: S effort; low risk.

## What is already good
- The vendored copies (`broll_vlm`, `ytdl_common`, `music_clap`, `ed25519`) are byte-pinned in up to three places (release gate, cross-component test, own-suite test) with the marker refused if absent or ambiguous. Leave them.
- No Python module in nine packages is unimported, no JS / CSS file is unreferenced, no companion config key is unread, and no dependency is unused: the trees are well pruned. Total dead Python found is about 320 lines in ~250k.
- `.dockerignore` names the customer-facing docs one by one, so the 64 MB of repo (docs, PNG, ledgers) never reaches the image.
- The companion's `ffmpeg_tools` preview flags are pinned by importing the indexer (F8); that pattern is the model for lens-dup-4 and lens-dup-6.

## Coverage note
- Dead-function scan is Python only; TypeScript / JS exports in the editor and the old page were not scanned for unused exports (would need the TS compiler; no npm allowed).
- Route scan covers decorator-registered dashboard routes (306); routes added by `add_api_route` / Starlette `Route` lists (sorter, cards wsgi) were not cross-checked.
- Did not diff `crash_report.py` helper-by-helper beyond the 24% figure, nor the sorter's `lib/teracopy.js` vs the companion port (both on retirement paths).

## OUT OF TERRITORY
- dashboard `db.py` / `api.py` / companion `app.py` are each over 650 KB; size alone, no finding.
