# lens-disk - cross-cutting: everything the product writes to disk, and what removes it

Files read (approximate coverage): every `*.json` / `*.md` report in this folder (collected all `disk-growth` items and the WAL / rewrite perf items); companion: app.py log setup, crash_report.py, resolve_journal.py (retention, sweep, session open), resolve_bridge.py save_project / _before_mutation, broll_fetch.py header + caps, broll_standins.py prune, broll_ingest.py staging retention, upgrade.py cleanup_old_exe, proxy_history.py, startguard.py, supervisor.py, ledger_outbox.py, syncthing_admin.py versioning + stignore, sync/lane_guard.py prune_trash, sync/rclone_lane.py orphan-.partial policy, build.spec (onefile, runtime_tmpdir); dashboard: db.py prune / prune_jobs / prune_companion_packages, triage.py prune, crash_report.py, cli_tools.py version prune, provision.py versioning, static/sw.js cache cleanup, browser-storage writers in dashboard/broll/music/ytdl static; server: setup_snapshots.py policy, install_dashboard_app.py LOG_ROTATION, setup_syncthing_folder.py; installer: windows_upgrade.ps1 stop, windows_bootstrap.ps1 Syncthing autostart; footage-sorter: files.py, engine.py save_manifest, ledger.py BACKUP_KEEP; MulticamPipeline / editor: only to place the filed items (cli argv, OPFS/cache store greps).
Probes run: PyInstaller `CArchiveReader` over the repo's own build output `companion/dist/ccsync-companion.exe` (read-only; companion venv, `-I`): 1,335 extracted files, 108,117,253 bytes per `_MEI` extraction (PyInstaller 6.21.0).

All growth figures below are at today's use (4 editor machines, ~100 projects, one NAS container) and are ESTIMATED unless the cited hunter measured them.

## Inventory 1 - an EDITOR machine

| Path | Writer | Trigger | Size per write | Growth / month (arithmetic) | Cap / retention | Severity if none |
|---|---|---|---|---|---|---|
| `~/.ccsync/logs/companion.log*` | companion app.py:157-192 | every log line | lines | flat once full | rotates 5 MB x 10 (app.py:108-109) = 55 MB | - |
| `~/.ccsync/crashes/*.json`, `native.log` | companion crash_report.py:174-181, :514 | crash / native fault | KB | flat | 20 files (crash_report.py:69), native log dropped past 512 KB | - |
| `~/.ccsync/crashes/supervisor.log`, `state/supervisor.json` | supervisor.py:136-137, :300 | each relaunch | lines | flat | 256 KB log, 20 history entries | - |
| `~/.ccsync/state/startguard.log` | startguard.py:211-219 | failed start | line | flat | unlinked past 64 KB | - |
| `~/.ccsync/state/*.json` (breaker, project dirs, halt, drive reminder, ...) | sync/lane_guard.py:662-664, :775-783 et al. | every lane pass | KB | flat (rewritten, not appended) | latch state persists by design; breaker scopes: comp-sync-6 (filed) | filed |
| `~/.ccsync/resolve_edits/<slug>/*.json` (undo journals) | resolve_journal.py:472-480 | first Resolve mutation of a burst | KB, rewritten per entry (comp-resolve-6) | small | 60 days (resolve_journal.py:100), swept ONLY for the slug being written (resolve_journal.py:481, :749-765) | see lens-disk-1 |
| `~/.ccsync/resolve_edits/<slug>/*.drp` (save-point exports) | resolve_bridge.py:2342-2406 via _before_mutation :2421-2427 | a Resolve mutation, at most once per project per 15 min (resolve_journal.py:69) | "tens of MB" (resolve_journal.py:732-737) | 2-6 per active project-day x 20-50 MB = 40-300 MB per active project-day; permanent for every project that stops being edited | same per-slug 60-day sweep; a dormant project is never swept | **lens-disk-1, medium** |
| `~/.ccsync/state/proxy_history.jsonl` | proxy_history.py:13-14, :62 | each proxy made | ~200 B | flat | 2 MB + one `.1` generation; 90 days of rollup | - |
| `~/.ccsync/field-local-copies.jsonl` | field_mode.py:513, :737-751 | field verdict | rewritten whole (comp-field-3, comp-ui-1 filed) | flat | 30 days | filed (perf) |
| `~/.ccsync/ledger-outbox.jsonl` / `.rejected.jsonl` | ledger_outbox.py:52-56, :185-194 | each field copy | ~0.3 KB/row | drains when online | 200,000 rows (ledger_outbox.py:56); rejected requeued on a new dashboard | filed (comp-field-6) |
| `~/.ccsync/ledger-mirror.sqlite` (+WAL) | ledger_mirror.py:49, :244-268 | ledger sync | rows per volume | flat | other volumes forgotten on change | - |
| TeraCopy job lists | teracopy.py:597, :619 | each card copy | KB | flat | 14 days (teracopy.py:619) | - |
| b-roll / music ingest staging (`<local_root>/Assets/B-roll Archive/.ingest`) | broll_ingest.py:885-929, music_ingest.py | each ingest batch | the source media | flat | 7 days default (broll_ingest.py:149, :3864; app.py:8099); walked every 2 s by sync_guard (comp-app-1 filed) | - |
| `<local_root>/Assets/B-roll Archive/<rel>` and `Assets/Music/<rel>` fetched on demand | broll_fetch.py:1-30, :94-97 | every Send to Resolve / + Resolve of a clip not yet local | the ORIGINAL clip, 50 MB - 2 GB | 10 clips/week/remote editor x ~300 MB = ~13 GB/month per remote editor, ceiling = the whole archive | **NONE** (no eviction anywhere; grep for the archive rel finds no unlink) | **lens-disk-2, medium** |
| `<local_root>/.ccsync-trash/` | sync/lane_guard.py:1260-1300 | lane B removals | moved files | flat | age, then 50 GB, then disk pressure; never while breaker tripped | - |
| b-roll stand-in ledger / stand-in files | broll_standins.py:98, :440 | stand-in made | proxy-size | flat | 30 days after the original arrives | - |
| `*.ccsync-tmp`, fixer reservations | fixer.py:813, :889; app.py:11827 | interrupted copy | up to a clip | flat | startup sweep (cost: comp-resolve-10 filed) | - |
| proxy `.partial` (local) | proxy_gen.py:429 | killed proxy encode | up to a proxy | flat | sweep_stale_partials | - |
| rclone `.partial` / `.h<n>.partial` ON THE NAS | rclone_lane.py:270-282, :1628-1680 | upload killed mid-file | up to a clip | rare | REPORTED, never deleted, by design (AUDIT_2 C-7; rclone_lane.py:3356) | by design |
| fleet-job `.partial` in the vault | jobs_media.py | killed media job | up to a proxy | rare | comp-jobs-4 (filed) | filed |
| Syncthing `.stversions` (editor) | syncthing_admin.py:164-167 | a pulled change replaces a file | file size | 30 days of staggered versions | Syncthing cleans hourly, maxAge 2,592,000 s | - |
| Syncthing index DB, Syncthing / rclone logs | Syncthing, rclone | - | - | proportional to file count; Syncthing is started from a hidden .vbs with no `--logfile` (windows_bootstrap.ps1:2070), rclone has no `--log-file` anywhere (grep) | n/a | - |
| `%LOCALAPPDATA%\ccsync\bin\*.exe.old` | upgrade.py:946-975 | self-upgrade | 48 MB | flat | at most one, deleted once the new build proves itself | - |
| `.stale-<epoch>` exe copies | onboarding/steps.py:3359-3365 | wizard clean slate on a locked exe | ~48 MB | rare | NONE | filed: ops-install-9 |
| `%TEMP%\_MEI*` (PyInstaller onefile extraction) | build.spec:333-352 (`runtime_tmpdir=None`) | every companion start AND every supervisor start; left behind when the process pair is force-killed | 108 MB measured per extraction | base rig: ~10 ships/month x 2 dirs x 108 MB = ~2.2 GB/month | **NONE** | **lens-disk-3, medium** |
| `%TEMP%` installer downloads (rclone / Syncthing zips) | installer/windows_bootstrap.ps1:783-816 | fresh install | ~130 MB | per install | NONE | filed: ops-install-4 |
| `local_vlm_server.log` / `broll_vlm_server.log` | broll_vlm/local_vlm.py:167-170; broll_vlm_sidecar.py:95 | VLM start / clip | KB | MBs per 1,000 clips | NONE | filed: comp-media-6 |
| local VLM model weights `<cache>/models/<tier>/` | broll_vlm/local_runtime.py:801-802 | first use of a tier | 3-9 GB | one-off | both tiers kept if switched (base rig only) | - (bounded ~9 GB) |
| yt-dlp / ffmpeg / deno sidecars | ytdlp_manager.py, sidecar_tools.py:420-450 | update | tens of MB | flat | tmp unlinked, one install each | - |

## Inventory 2 - the NAS / dashboard container

| Path | Writer | Trigger | Size per write | Growth / month (arithmetic) | Cap / retention | Severity if none |
|---|---|---|---|---|---|---|
| `<data>/dashboard.db` rows | dashboard db.py (many) | reports, collector | rows | flat | db.prune (db.py:10691-10839): history 7 d, audit/alerts/notices/diagnostics/media by age; jobs 30 d (db.py:13476); triage KEEP_DAYS incl. run dirs (triage.py:658-669); packages: current + 2 (db.py:5324) | `file_moves`, `triage`-less small tables: tiny |
| `<data>/dashboard.db-wal` | SQLite | every commit | 28 KB per light report (dash-api-5), 83 KB per 15 s collector cycle (dash-collector-1), 1.09 MB/min with backlogs (dash-collector-3), full manifest rewrite per 10 min (dash-db-1) | file size flat at 6-8 MB today; WRITES ~0.5-2 GB/day | no journal_size_limit (dash-db-2 filed) | filed |
| ZFS hourly + daily snapshots of the APP dataset | server/setup_snapshots.py:73-93, :144-147 | hourly / 03:10 | every block rewritten or deleted since the previous snapshot | the WAL churn above, CoW'd in 128K records, plus every file deleted from `<data>` held 30 days | 24 hourly + 30 daily | **lens-disk-4, medium** |
| `ccsync-pre-*` pre-op snapshots | server/common.py:2406 | each new project / deploy | delta | per op | NONE | filed: ops-server-1 |
| OTA DB backups | dashboard_update.py:1660-1670 | each OTA apply | ~520 MB x 2 | ~4.2 GB held | up to 8 copies | filed: dash-ops-2 |
| release/OTA download staging | release_feed.py:1449-1460; api.py:6901-6923 | interrupted download | 0.2-0.8 GB | rare | NONE | filed: dash-ops-3 |
| `<data>/packages/` + `.trash/` | package_store.py:535; api._trash_package_file | publish / delete | 48 MB-ish | flat | current + 2 per kind/platform; `.trash` 30 days on purpose | - |
| `<data>/tools/<tool>/` (CLI wizard) | cli_tools.py:1331-1421 | install / auto-update | 100-300 MB | flat | old versions pruned an hour after a newer one | - |
| `<data>/tools/claude/home/.claude/projects/*.jsonl` (CLI session transcripts) | the Claude Code CLI, launched by triage.py:236, triage_mail.py:366, cards_ai.py:733, gear_ai.py:266, MulticamPipeline library_engine.py:1931 | every CLI call | KB-MB per call | bounded | the CLI's own 30-day default cleanup (none set by us); Cards resumes sessions, so persistence is needed there | - |
| ytdl DB `job_videos` / `job_video_terms` | ytdl/web schema.sql:208-258 | each search | 356 KB / 400-candidate job | ~20 MB/month | NONE | filed: web-ytdl-7 |
| ytdl nightly yt-dlp builds | ytdl/web/ytdlweb/ytdlp_nightly.py:263-278 | nightly | tens of MB | flat | versions not kept + staging swept | - |
| music ingest ledger | music/web/musicweb/ingest_batches.py | each ingest | row | small | NONE | filed: web-music-10 |
| `/tmp` b-roll publish staging | server/publish_db.py:593-609 | publish | ~500 MB | per publish | removed after | filed: ops-server-7 |
| Cards `<data>/cards/<slug>/` + remote_audio caches | MulticamPipeline library_engine.py:4240, :3700 | proxy / audio window use | 0.5-0.7 GB per footage hour | per episode | NONE | filed: cards-library-11 |
| Cards Claude temp dirs (`/tmp`) | MulticamPipeline chat_edit.py:1427 et al. | each chat / search turn | KB-MB | until container recreate | NONE | filed: cards-server-4 |
| Footage Sorter thumbnails + filmstrips | footage-sorter thumbs.py:177-199 | each clip seen | 35-80 KB | ~2 GB today, ~9 GB at 500k files | NONE | filed: sorter-py-11 |
| Footage Sorter `logs/manifest-YYYYMMDD.json` | footage-sorter engine.py:440-442 | first manifest save of each day, then REWRITTEN on every save that day | ~2.9 MB (DASHBOARD-MODULE-PLAN.md:310) | ~25 edit days x 2.9 MB = ~73 MB/month | **NONE** | **lens-disk-5, low** |
| Footage Sorter `logs/manifest-ops.jsonl`, `logs/move-journal.jsonl` | engine.py:436; moves.py:153 | each manifest op / each move | a line | move journal is 11 MB / 39,264 lines today (sorter-py probe) | NONE | lens-disk-5 |
| Footage Sorter ledger snapshots | footage-sorter ledger.py:1699-1712 | backup | ledger size | flat | 7 (BACKUP_KEEP) | - |
| Footage Sorter catalog | catalog.py | each scan | 25 MB rewritten | flat | rewritten in place (sorter-py-9 filed) | filed (perf) |
| container stdout | docker json-file | every log line | lines | flat | 20 MB x 5 (install_dashboard_app.py:2740-2741; compose.appliance.yaml:188-193) | - |
| `<data>/logs/` dashboard log + crash JSONs | dashboard crash_report.py:60-61, :209-213 | log line / crash | lines | flat | 5 MB x 3; MAX_CRASH_FILES | - |
| NAS Syncthing `.stversions` (every project folder + Luts + Stills) | provision.py:285-288, :536-539; server/setup_syncthing_folder.py:459-463 | an editor's change replaces a non-video file on the NAS | file size | unmeasured (alerts.py:4961-4963: "no companion measures it") | staggered, maxAge 365 days (up to ~100 versions per file) | **lens-disk-6, low** |
| b-roll previews / sprites, music proxies / peaks | base-rig indexers | per indexed clip | proportional to the library | follows the library | removal of a de-indexed clip's artefacts not audited | - |

## Inventory 3 - Timeline Cards data (vault) and the rebuilt editor

| Path | Writer | Trigger | Size | Growth | Cap | Status |
|---|---|---|---|---|---|---|
| `timeline_plans.history.jsonl` | MulticamPipeline cards/stores.py:338-352 | every staged op | whole op list per rev, quadratic | 70 MB measured for one 400-op draft | NONE | filed: cards-library-5 |
| cut-list revision history | cards/cutlist.py:1023-1068 | every 10th revision kept | 198 KB per copy | 75-234 MB per long-edited list | NONE | filed: cards-resolve-9 |
| translation caches | cards/translate.py:144-356 | each distinct text | entry | 0.5-5 MB per episode | NONE | filed: cards-server-7 |
| Story Deck board | storydeck/model.py:643-732 | each event | 1.44 MB after 3 days | linear | NONE | filed: cards-storydeck-6 |
| whisper corpus scratch | transcripts/whisper_corpus.py:678 | failed run | MBs-tens of MB | per failure | NONE | filed: cards-server-6 |
| editor `.tcards` log segments, 3 snapshots, `.bak`, quarantine | editor server/sync/options.ts:49-50; store.ts:870-881 | edits | ~8-15 MB per list | 1-4 GB across lists | 100 segments + 3 snapshots; quarantine NONE | filed: editor-server-4 |
| editor shorten record cache (memory) | editor features/shorten/server.ts:154-196 | per list | - | - | - | filed: editor-features-b-8 (leak) |

## Inventory 4 - the browser

| Store | Writer | Cap | Status |
|---|---|---|---|
| dashboard service-worker Cache Storage | dashboard/static/sw.js:81, :94-96 | every `ccsync-*` cache not the current VERSION+LOOK deleted on activate | bounded per release (re-write cost: dash-web-3 filed) |
| localStorage (dashboard, b-roll, music, ytdl SPAs) | cc/cc.js:41, :690; cards_landing.js:50; ytdl app.js:689-2494; broll cc_spa.js:120 | fixed keys, small values | bounded |
| Cards offline IndexedDB + Cache Storage (downloaded media) | MulticamPipeline cards/page/15-offline.js | never evicted | filed: cards-page-b-4 |
| Cards search answer cache in localStorage | cards/page/14-search.js:150-183 | never pruned across roots | filed: cards-page-b-6 |
| rebuilt editor OPFS / cachefs (Keep) | editor client/device/opfs.ts, cachefs.ts | explicit `remove` / `removeTree` only; no LRU found | eviction policy not audited (Coverage note) |
| sessionStorage tab memory | dashboard/static/tab_memory.js | per tab | bounded |

Already-filed disk items this lens relies on (not re-filed): comp-media-6, comp-sync-6, comp-resolve-6, comp-field-3, comp-field-6, comp-ui-1, comp-media-2, comp-app-1, comp-jobs-4, dash-collector-1, dash-collector-3, dash-api-5, dash-db-1, dash-db-2, dash-ops-2, dash-ops-3, ops-server-1, ops-server-7, ops-install-4, ops-install-9, web-ytdl-7, web-music-10, sorter-py-9, sorter-py-11, sorter-node-6, cards-library-5, cards-library-11, cards-resolve-9, cards-server-4, cards-server-6, cards-server-7, cards-storydeck-6, cards-page-b-4, cards-page-b-6, editor-server-4.

## Findings

Ordered by estimated gigabytes per year.

### lens-disk-2 - Clips fetched on demand from the b-roll archive and the music library are never evicted from a remote editor's disk
- Category: disk-growth
- Severity: medium
- Confidence: PLAUSIBLE (mechanism CONFIRMED by code read; volume estimated)
- Where: companion/src/ccsync_companion/broll_fetch.py:1-30, :94-97 (destination `<local_root>/Assets/B-roll Archive/<rel_path>` and `Assets/Music/<rel_path>`); broll_server.py:245-247, :363; music_server.py (second caller)
- What: Send to Resolve on a remote editor pulls the ORIGINAL clip into the archive path inside the editor's tree, "into the same place a full sync would have put it". That folder is not a Syncthing folder and no lane, sweep or prune ever deletes from it; no module names the archive path with an unlink (grep of `ARCHIVE_REL`, `B-roll Archive`, `Assets/Music`). Over months each remote machine converges on the whole archive the module header says editors must not be made to sync ("hundreds of GB").
- Cost / failure scenario: estimated 10 inserts per remote editor per week x ~300 MB per archive original = ~13 GB/month, ~150 GB/year per remote editor (3 of today's 4 machines), on an editor's sync drive that also holds their ticked projects; ceiling = the archive (5,000 clips). Nothing reports it: the tray, the report and the weekly mail measure `.ccsync-trash`, not this.
- Evidence: broll_fetch.py header ("Syncing the whole archive down would cost every editor hundreds of GB ... instead the companion pulls exactly the clip"); no eviction path anywhere in companion/src for either root; broll_standins.py:440 prunes only stand-in LEDGER entries.
- Ledger: new
- Suggested change: record each completed fetch (path, size, fetched_at) in a small `state/fetched_assets.json`; a daily pass deletes fetched files older than 90 days that the media tree the companion already walks (`library.py` / `media_tree_clips` report) shows in NO project's media pool, and deletes nothing when that walk cannot answer (fail closed - a deleted clip in a timeline is Media Offline). Never touch a file that was not fetched (base rig, wired rigs whose local_root is the share). Report the total in Settings so an editor can see it.
- Effort / risk: M effort; medium risk (must keep "never delete what a timeline uses", and must never run where local_root is the NAS).

### lens-disk-1 - Save-point exports (.drp, tens of MB) of a project nobody edits any more are never swept
- Category: disk-growth
- Severity: medium
- Confidence: CONFIRMED (mechanism); volume estimated
- Where: companion/src/ccsync_companion/resolve_journal.py:481 (`_sweep(slug, now)` only for the slug being opened), :749-765 (`_sweep`), :100 (RETENTION_DAYS = 60), :69 (SAVE_POINT_INTERVAL_SECONDS = 900); resolve_bridge.py:2342-2406, :2421-2427
- What: the 60-day sweep of journals and exported rollback copies runs only on the write path, and only inside the directory of the project being journalled. When a project stops being edited (finished, delivered, unticked), its last 60 days of `.drp` exports stay in `~/.ccsync/resolve_edits/<slug>/` for ever; no startup or periodic pass walks the other slugs (the only other readers of `journal_root()` are the redaction helpers, app.py:10200, :10220). docs/RESOLVE_EDIT_SAFETY.md "Housekeeping" says "older than 60 days are swept on the next write", which is true only for a project that gets a next write.
- Cost / failure scenario: a save point is taken before a mutation, at most once per project per 15 min; an auto-relinking project (proxies arriving over days, file moves, Cards conforms) takes an estimated 2-6 a day at "tens of MB" each (resolve_journal.py:732-737). A project's final 60 days = 20-100 exports x 20-50 MB = 0.4-5 GB left behind per finished project per machine; at ~25 projects a year per editor, an estimated 10-50 GB/year in the editor's HOME (the system disk, the smallest disk on a laptop), invisible to every report.
- Evidence: code read of the three call sites; `summaries()` and `_redaction_names` only read.
- Ledger: related to comp-resolve-4 (FIXED 2026-08-21, which added `.drp` to the sweep but kept the per-slug trigger)
- Suggested change: run the existing `_sweep` over every subdirectory of `journal_root()` once at startup and once a day (same 60 days, same SWEPT_SUFFIXES), and remove a slug directory that ends empty. Optionally, past 14 days keep only the newest `.drp` per project per day. Undo replays the JSON journals, which keep their 60 days unchanged, so the undo guarantee and the documented retention both hold.
- Effort / risk: S effort; low risk.

### lens-disk-3 - Every force-kill of the companion leaves two 108 MB PyInstaller extraction folders in %TEMP%
- Category: disk-growth
- Severity: medium
- Confidence: PLAUSIBLE (extraction size MEASURED; the orphaning is PyInstaller's documented onefile behaviour when the bootloader parent is killed, not reproduced live by rule)
- Where: companion/build.spec:333-352 (onefile, `runtime_tmpdir=None`); installer/windows_upgrade.ps1:184 (`Stop-Process -Force` on every `ccsync-companion` image); supervisor.py (the same exe re-entered with `--supervise`, so a second extraction per start)
- What: a onefile build unpacks to `%TEMP%\_MEIxxxxxx` and only the bootloader PARENT deletes it when its child exits. `windows_upgrade.ps1`, the uninstaller and `Get-Process ccsync-companion | Stop-Process -Force` kill parent and child of BOTH the companion and its supervisor (KNOWN_BUGS: "the supervisor shares the image name and dies with it"), so each such stop strands two extraction folders. Nothing in the companion, installer or upgrade path ever looks for stale `_MEI*` folders (grep).
- Cost / failure scenario: 108,117,253 bytes per extraction (measured on `companion/dist`), x 2 per stop. The base rig runs `windows_upgrade.ps1` on every `ship.cmd` (0.9.71 -> 0.9.91 in about two months, ~10 ships/month) = ~2.2 GB/month, ~26 GB/year on the base rig's C:; every hand install or uninstall on an editor machine adds 216 MB. A crash under the supervisor is cleaned (the parent survives), so it is the scripted stops that leak.
- Evidence: CArchiveReader probe (1,335 files, 108 MB); build.spec runtime_tmpdir=None; windows_upgrade.ps1:184; KNOWN_BUGS supervisor entry (~3413).
- Ledger: related to COMMERCIAL_READINESS L-list "onefile `_MEI` temp" (security angle, not growth)
- Suggested change: at companion startup (after the single-instance slot is held), delete `%TEMP%\_MEI*` folders older than one hour that are not `sys._MEIPASS` and contain this build's marker (e.g. `ccsync_lib/` or `ccsync_companion` resources), skipping any that fails to delete (locked = in use). Do the same sweep at the end of `windows_upgrade.ps1` after the new build has started. Must not touch onboard.exe's or any other app's extraction.
- Effort / risk: S effort; low risk.

### lens-disk-4 - The APP dataset's 24 hourly + 30 daily snapshots pin the dashboard DB's rewrite churn and everything deleted from `<data>`, sized on a "kilobytes per hour" assumption that no longer holds
- Category: disk-growth
- Severity: medium
- Confidence: PLAUSIBLE (churn figures MEASURED by the cited hunters; the snapshot hold is estimated, no NAS access by rule)
- Where: server/setup_snapshots.py:20-27 (APP dataset "Hourly, same policy: it is kilobytes of change per hour"), :73-93, :144-147; dashboard/src/ccsync_dashboard/db.py:710-728 (4 KB SQLite pages, no checkpoint policy); server/backends/truenas.py:805 (recordsize deliberately not set, so the TrueNAS default 128K applies)
- What: copy-on-write snapshots keep one old version of every block changed between snapshots. The APP dataset holds dashboard.db, whose WAL and pages are rewritten all day (dash-api-5, dash-collector-1, dash-collector-3, dash-db-1), on 128K records, so each dirty 4 KB page pins a 128 KB record; and it holds `<data>`, where every OTA DB copy (dash-ops-2), deleted package, Cards cache and sorter thumbnail is held another 30 days after deletion. Nothing reports the dataset's `usedbysnapshots`; the dashboard's free-space check (alerts.py:2166) sees only the result.
- Cost / failure scenario: WAL writes today ~0.5-2 GB/day (83 KB per 15 s = 0.48 GB/day collector alone; light reports and backlogs on top). Each daily snapshot can hold up to a whole dashboard.db plus WAL; 30 dailies + 24 hourlies x an estimated 20-100 MB of dirty records = an estimated 1-5 GB held, plus dash-ops-2's ~1 GB per OTA held 30 days after its own pruning. At 20 machines the churn and so the hold scale roughly linearly.
- Evidence: the cited hunters' WAL measurements; setup_snapshots.py docstring; no recordsize, journal_size_limit or usedbysnapshots in the tree (grep).
- Ledger: related to dash-db-1, dash-db-2, dash-collector-1, dash-collector-3, dash-api-5, dash-ops-2, ops-server-1 (all filed, all this audit)
- Suggested change: put the SQLite files in a child dataset with `recordsize=16K` (set once by the installer on a NEW dataset, so it never rewrites the operator's choice for the existing one), which cuts the pinned bytes per dirty page 8x; read `usedbysnapshots` for the APP dataset in the collector's daily pass and show it on the health page; fix the docstring. Reducing the churn itself is the filed findings' job. Keep 24h/30d retention as is.
- Effort / risk: M effort; low risk (new dataset + move under the existing stage-verify-swap deploy).

### lens-disk-5 - Footage Sorter keeps a full manifest copy for every day it is used, and its two journals only grow
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED (no remover exists); size estimated from the module plan
- Where: footage-sorter footage_sorter/engine.py:424-443 (`save_manifest`: `logs/manifest-YYYYMMDD.json` written with the whole manifest on EVERY save, and `logs/manifest-ops.jsonl` appended); footage_sorter/moves.py:153 (`logs/move-journal.jsonl`); files.py:62-67 (append with fsync); no `remove` of anything under `logs/` (grep)
- What: the "one snapshot a day" is a full manifest rewrite on every save (the first write of the day creates it, every later save that day overwrites it: twice the manifest bytes per edit, each fsynced), and the daily files are never pruned. The ops log and the move journal are append-only for ever.
- Cost / failure scenario: manifest ~2.9 MB (docs/DASHBOARD-MODULE-PLAN.md:310) x ~25 edit days/month = ~73 MB/month, ~0.9 GB/year on the APP dataset (and in its snapshots, lens-disk-4); the move journal is 11 MB / 39,264 lines today and is read at start (0.089 s, sorter-py's probe). Grows with the pool: estimated 3-5x at 500k files.
- Evidence: code read; sorter-py probe figures.
- Ledger: new (sorter-py-11 covers thumbnails; sorter-node-6 covers the old Node state)
- Suggested change: write the daily copy once (only if today's file is absent), keep 30 daily + one per month for 12 months, pruned at that write; rotate `manifest-ops.jsonl` at 10 MB keeping 3; compact `move-journal.jsonl` by dropping start/done pairs older than 90 days that are both done (never an unfinished entry, which is what recovery reads).
- Effort / risk: S effort; low risk.

### lens-disk-6 - The NAS keeps a year of staggered Syncthing versions for every project folder, and nothing measures it
- Category: disk-growth
- Severity: low
- Confidence: PLAUSIBLE (retention CONFIRMED; volume unmeasured, which is the finding)
- Where: dashboard/src/ccsync_dashboard/provision.py:285-288, :536-539; server/setup_syncthing_folder.py:459-463 (`maxAge` 31,536,000 s); dashboard/src/ccsync_dashboard/alerts.py:4961-4963 (".stversions is NOT here: no companion measures it")
- What: lane C carries every non-video file; when an editor's change replaces one on the NAS, Syncthing keeps the old one under `.stversions` with staggered thinning (hourly for a day, daily for a month, weekly to a year: up to ~100 versions per file). Project files, audio re-exports, graphics and transcripts that are saved often accumulate a year of copies. The delete side is already covered by `ignoreDelete`, so these versions guard only against bad overwrites. The `versioning_agrees` invariant is deliberately NOT evaluated and the weekly report omits `.stversions`, so its size is never seen.
- Cost / failure scenario: estimated: a 50 MB project or graphics file saved daily for a month keeps ~55 versions = ~2.7 GB for that one file; across ~100 projects, tens of GB a year on the tree dataset, which ops-server-1's never-expiring pre-op snapshots then also pin.
- Evidence: config read; KNOWN_BUGS ~7783 ("`.stversions` retention is 365 d NAS-side").
- Ledger: related to KNOWN_BUGS `versioning_agrees` (registered, not evaluated, by design)
- Suggested change: have the collector total `<tree>/**/.stversions` (one bounded walk a day, like cards_catalog's size walker) and put it in the weekly report and the health page, with an alert over a site-set threshold; whether to lower `maxAge` to 90 days is an owner decision once the number is known. Do not change the editor-side 30 days.
- Effort / risk: S effort; low risk.

## What is already good
- The companion's own files are almost all bounded and deliberately so: rotated log (55 MB), 20 crash files, capped supervisor/startguard logs, proxy history (2 MB + one generation), 200k-row outbox, `.ccsync-trash` with age, size and disk-pressure triggers that stand down while the breaker is tripped. Leave them.
- dashboard.db has one hourly `prune` covering every high-volume table by age; jobs 30 d; triage runs and their directories together; packages current + 2 with a 30-day `.trash`; docker json-file rotated in both compose paths.
- The CLI-tool and yt-dlp nightly installers prune old versions and staging dirs themselves; the service worker drops every old cache on activate.

## Coverage note
Did not audit: whether de-indexed b-roll / music clips leave previews, sprites, proxies or peaks behind; the rebuilt editor's OPFS/Keep eviction policy beyond confirming it has explicit removes only; Cards `<data>/cards/<slug>/` contents beyond the filed remote_audio caches; macOS-specific paths (`~/Library/Logs`, launchd stdout). No live sizes were read (rule 2), so every monthly figure here is code-derived or an estimate.

## OUT OF TERRITORY
- footage-sorter footage_sorter/engine.py:441: the per-save fsynced rewrite of the daily manifest copy doubles the write cost of every manifest edit (perf, folded into lens-disk-5's fix).
