# Audit 2026-11-10 - hunter roster

41 read-only Opus hunters, one territory each. Every hunter gets the same
opening paragraph (below), then its territory and its questions. A hunter is
DONE when both `hunters/<id>.md` and `hunters/<id>.json` exist.

The session runs at most 20 subagents at once, so the roster goes out in two
waves. Usage rule from the owner (2026-11-10): run the first 5-hour window
freely; if the limit is hit, resume when it resets
(`E:\Projects\Utilities\claude-usage\usage.mjs wait-reset`); in the SECOND
window, pause at 80% (`wait-high --at 80`): launch nothing new, ask running
hunters to write up what they have.

## Opening paragraph (every hunter)

> You are hunter `<id>` in a read-only whole-product audit of CC Sync (a
> multi-machine video-editing sync fleet), Timeline Cards and the Footage
> Sorter. FIRST read the brief completely:
> E:\Projects\Editing\ccsync\docs\audit-2026-11-10\HUNTER_BRIEF.md - it
> defines what to look for (performance, wasted work, leaks, idle cost, bugs,
> streamlining), the rules (read-only; a live companion runs on this machine),
> the evidence standard, and the exact two report files you must write. Then
> read the CLAUDE.md of your tree. [territory + questions] Write your two
> report files as the brief specifies and end with the short final message the
> brief asks for.

Trees: CC = `E:\Projects\Editing\ccsync`; CARDS =
`E:\Projects\Editing\Resolve\MulticamPipeline`; EDITOR =
`C:\Users\alex\AppData\Local\Temp\claude\tc-standalone\Resolve\MulticamPipeline\editor`
(another session's live worktree, read only); SORTER =
`E:\Projects\Editing\footage-sorter`.

## Wave 1 (launched 2026-11-10 23:45 local)

| id | Territory |
|---|---|
| comp-app | CC `companion/.../app.py`, `__main__.py`, `startguard.py` |
| comp-core | CC companion: config, upgrade, reporter, supervisor, crash_report, shutdown_guard, selection, transport, site, identity, machine, machine_settings, telemetry_policy, manifest, paths, eula, state_acl, secretfile, release_pubkey, ed25519, win_trust, canon, capabilities, idle |
| comp-sync | CC companion `sync/` + originals_requests, drive_swap, root_guard, drive_reminder, unopened_scan |
| comp-resolve | CC companion: resolve_bridge, watcher, fixer, library, proxy_relink/scan/history, resolve_journal/undo/prefs/menu_install, script_server, file_moves, consolidate, luts, youtube_import, project_setup, stills, vp9_guard, timeline_cards_role/bridge |
| comp-ui | CC companion: tray, tray_native, popup, settings_window, ui_dispatch, theme, ui_copy, ui_state, field_mode windows |
| comp-media | CC companion: broll_* , broll_vlm/, proxy_gen, ffmpeg_tools, music_*, bpg, sidecar_tools, loopback_guard, ingest_kinds, lgpl_libs |
| comp-jobs | CC companion: ytdl_*, ytdlp_manager, jobs_runner, jobs_media, job_paths, proc_tree |
| comp-field | CC companion: card_copy, field_*, ledger_*, sorter_cards, sorter_volumes, teracopy, wav_header (+ both other sides of the wire) |
| dash-db | CC dashboard: db.py, site_store, sessions, subject_data |
| dash-api | CC dashboard: api.py, assignments, links, locate, project_groups, netclass, android, published_docs |
| dash-collector | CC dashboard: collector, alerts, notices, health, invariants, protection, recovery, triage*, mount_status, syncthing/truenas/tailscale clients |
| dash-web | CC dashboard: app.py, ui*.py, auth, oidc, local_users, account_*, settings, help, secrets_boot, templates/, static/ |
| dash-mounts | CC dashboard: cards*.py, sorter.py, broll.py, music.py, ytdl.py, jobs.py, gear_ai.py |
| dash-ops | CC dashboard: cli_tools, dashboard_update, release_feed/trust, package_store, setup_*, ai_providers, provision, tailnet_serve, appliance_config, crash_report, sftp |
| web-broll | CC `broll/web/` |
| idx | CC `broll/indexer/` + `music/indexer/` |
| web-music | CC `music/web/` |
| web-ytdl | CC `ytdl/` |
| ops-server | CC `server/` (not install_dashboard_app.py) + `bench/` |
| ops-install | CC `installer/` + `onboarding/` |

## Wave 2 (pending: launch as wave 1 slots free up)

| id | Territory | Questions |
|---|---|---|
| deploy-release | CC `tools/`, `.github/workflows/`, PyInstaller specs, release docs | Timeline of pathway A (`ship.cmd`) and B (CI + `publish_latest.py`) with real wall-clock from `gh run view`; CI caching; artefacts built twice; manual copies; the 14-minute feed pull vs 1 s direct PUT; version bumped in two files; a one-command release that keeps every refusal |
| deploy-nas | CC `server/install_dashboard_app.py`, Dockerfile + entry scripts, image workflow, `dashboard_update.py` (OTA), CARDS_DEPLOY / SORTER_DEPLOY / DOCKER docs | Timeline of each deploy (image, OTA, Cards-only, Sorter-only, restart-for-vault-data): manual steps, SSH round trips, downtime; the stale-digest trap; premature health check; snapshots per run; re-shipping unchanged files; restart vs reload; image size and layers; cold boot; a one-command digest-safe deploy. NEVER run the script, even `--dry-run` |
| tests-ci | every CC `tests/`, `tools/run_all_tests.ps1`, `select_suites.py`, conftests; CARDS `tests/` + `run_all.py` | Slowest tests/fixtures with seconds (CI logs); sleeps; fixture scope; the ~110 hunt-named test files and their duplication; tests that cannot fail; path-based suite selection; xdist balance; what makes the Cards gate 25 min. No whole-suite runs |
| cards-library | CARDS `multicam_pipeline/cards/library_engine.py`, `multicam_pipeline/library/`, `cards/stores.py`, `config.py`, `media.py`, `make_lite_audio.py`, `fleet_jobs.py`, `roots.py` | The library sweep: cadence, cost on a vault, what is cached; the single ffmpeg worker queue; proxy / audio / peaks caches and their caps; stores' read-merge-write and file churn; threads `stop()` does not stop; per-engine memory |
| cards-resolve | CARDS `cards/resolve_engine.py`, `project_engine.py`, `project_conform.py`, `project_diff.py`, `project_agent.py`, `project_edit.py`, `project_pick.py`, `cutlist.py`, `agent.py`, `keys.py`, `timecode.py`, `refresh_cuts.py`, `recolour_sections.py`, `multicam_pipeline/resolve/` | Resolve API calls per sweep / per conform and lock hold times (never call scriptapp); cut list parse/serialise cost per edit (whole file rewritten per keystroke?); revision history growth; diff cost on hundreds of cards; agent polling cadence; the DB-writer path that damaged Repro Rights V7 (memory) - is it still reachable |
| cards-server | CARDS `cards/handler.py`, `server.py`, `page.py`, `offline.py`, `chat_edit.py`, `shorten.py`, `transcript_search.py`, `corpus.py`, `translate.py`, `claude.py`, `claude_session.py`, `models.py`, `text.py`, `gap_notes.py`, `montage.py`, `__init__.py`, `multicam_pipeline/transcripts/`, `multicam_pipeline/canvas/`, root `reorder_web.py`, `pipeline_web.py` | Per-request cost of the ~70 routes (page assembled per request? state JSON size; ETag); media Range serving; corpus load and caches per engine; Claude session/prompt cache use and prompt sizes; long-poll / SSE handlers that pin threads; translation/search caches growth; whisper |
| cards-page-a | CARDS `cards/page/01-state.js`, `02-markers.js`, `03-lane.js`, `04-lane-keys.js`, `05-keys.js`, `06-trim.js`, `08-places.js`, `09-edit.js`, `10-look.js`, `cards.html`, `cards.css` | Lane render cost per frame and per edit at 500 cards (whole-lane rebuilds, layout thrash, waveform canvases, DOM node count); state polling and whole-state diffs; listeners stacked per render; rAF loops that never stop; undo/history arrays; memory after an hour of editing |
| cards-page-b | CARDS `cards/page/07-conform.js`, `11-montage.js`, `12-cats.js`, `13-paste.js`, `14-search.js`, `15-offline.js`, `16-chat.js`, `17-windows.js`, `18-shorten.js`, `19-pad.js`, `20-seqs.js`, `21-clip.js`, `sw.js` | Offline store (IndexedDB / Cache) growth and eviction, snapshot-per-minute (CR-274); service worker cache versions; gamepad polling when no pad is used; audio elements / AudioContext / decoded buffers; chat and search result retention; pop-out windows |
| cards-storydeck | CARDS `multicam_pipeline/storydeck/`, `apps/`, `tools/`, `deploy/`, root scripts (`pipeline.py`, `storydeck_web.py`, `build_canvas.py`, ...) | Is storydeck live or dead weight; agents/stages cost; the native app shells (Android/Windows) - webview lifecycle, updates; deploy script duplication with ccsync's; root-level one-off scripts that are dead |
| editor-client | EDITOR `client/` + `audio/` | Render model (what re-renders on one op), lane.ts at 500 cards, virtualisation, listeners, rAF, pad polling, audio engine buffers and node graph lifetime, state store subscriptions that leak, bundle size and load time. Read `PERF.md` first; do not re-report what it already measures as fixed |
| editor-features-a | EDITOR `features/`: transcripts, shelf, lane, markers, video, aids, align, looks, keep, gapnotes, montage | Same client questions per feature; video element pool; transcript indexing cost and memory on a 3-hour interview; align algorithms' complexity |
| editor-features-b | EDITOR `features/`: shorten, search, chat, translate, resolve, projects + every `features/*/server.ts` | Server-side handlers: blocking work on the Node event loop, unbounded caches/maps, AI call sizes and caching, child processes, file handle lifetimes; client halves as above |
| editor-server | EDITOR `server/`, `core/`, `cutmd/`, `adapters/`, `scripts/`; other side: CC `dashboard/.../cards_edit.py` | Sync store: op log growth, compaction, snapshot cost, fan-out per op, reconnect handling, per-socket state leaks; SIGTERM flush; media serving (Range, streams closed on abort); reducer cost per op; cut-list parse/serialise per save; pybridge child lifetime; header trust (`X-TC-*`) when reached without the proxy |
| sorter-py | SORTER `footage_sorter/*.py`; other side: CC `dashboard/.../sorter.py` | Scan cost on Temp Transfer (walks, stats, hashes, ffprobe per file), caches and invalidation; thumbnail / filmstrip generation concurrency and cache size; ledger and catalog stores (JSON rewritten whole? SQLite?) and growth; move safety (EXDEV, no-replace, crash between copy and delete); `_collation.py` 3,562 lines and `jscompat.py` / `jsvalue.py` - what they exist for and whether they can go; threads and lifecycle under the dashboard mount |
| sorter-page | SORTER `public/` (app.js 4,621, ingest.js, ledger.js, grid.js, audio.js, calendar.js, cards.js, util.js, style.css, index.html, dev-mock.js) | Grid of thousands of clips: virtualisation, thumbnails/filmstrips loaded eagerly, hover strips, listeners per tile, polling cadence, whole-state re-render, audio preview elements; is dev-mock.js shipped to production |
| sorter-node | SORTER `server.js`, `lib/`, `ingest/` (tray PowerShell backup scripts), `mover.ps1`, `cloud/ledger` worker, `tools/` | What of this still RUNS anywhere now that the Python package ships (dead weight to retire to legacy, with line counts); JS and Python implementations of the same logic that have drifted; the tray backup scripts: copy/verify correctness, polling cadence, handle leaks in long-lived PowerShell; the Cloudflare worker: auth, cost per request, storage growth |
| lens-longrun-companion | CC `companion/` whole package (census, not a re-read) | A table of EVERY thread, timer, periodic loop, child process and module/instance-level cache in the companion: owner module, cadence, idle cost, bound, what stops it. Then the totals: wakeups per minute at idle, subprocess spawns per hour, RSS after import, and the unbounded ones as findings. Probes: grep census + `tracemalloc` on import + `-X importtime` |
| lens-longrun-dashboard | CC `dashboard/` + everything it mounts in one process (broll, music, ytdl, cards engines, sorter) | The same census for the one uvicorn process: threads, tasks, children, caches, per-mount idle memory; boot time itemised (`-X importtime`, mounts); what happens to all of it on shutdown; container memory budget at idle and under a search + a Cards engine + a ytdl job at once |
| lens-sql | every SQLite DB except the dashboard's own (dash-db has that): broll.db, client_shares.db, music.db, ytdl db, sorter ledger/catalog, Cards stores, companion-side DBs | PRAGMAs, WAL/checkpoint, connection lifetime, EXPLAIN QUERY PLAN for each hot query on a synthetic DB at 10x today's size, missing indexes, commit-per-row, tables never pruned, VACUUM / file growth |
| lens-disk | all four trees | A table of EVERYTHING that writes to disk and never deletes, per machine role (editor machine `~/.ccsync`, `%LOCALAPPDATA%\ccsync`; NAS `<data>/`; Cards data; sorter-data): logs and rotation, state, journals, trash, tmp, `.partial`, caches, thumbnails, packages, crash reports, snapshots; growth per month at today's use; what prunes it; the uncapped ones as findings |
| lens-dup | all four trees | Cross-tree duplication and dead code with line counts: `ed25519.py` x2, `crash_report.py` x2, `ffmpeg_tools.py` x2, `local_runtime.py` x2, `ingest_batches.py` + `ingest.js` broll vs music, three `style.css`, `webtheme.py` copies, sorter JS vs Python, Cards `library_engine` ffmpeg argv vs companion `jobs_media` (a deliberate VERBATIM copy: is it pinned by a test?), old Cards page vs rebuilt editor; modules nothing imports (script it); feature flags nothing reads; dependencies nothing imports; PyInstaller bundle and Docker image size contributors. For each: have the copies drifted, and what a shared module or a deletion saves |
