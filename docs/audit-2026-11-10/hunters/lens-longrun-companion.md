# lens-longrun-companion - census of everything the companion does on a timer, for weeks, beside Resolve
Files read (approximate coverage): every `threading.Thread(` / `Timer(` / `ThreadPoolExecutor(` site in `companion/src/ccsync_companion/` (110 sites, 40 modules) and the loop body each one runs; every `.wait(` / `sleep(` / `while True` (111 sites); every module-level mutable container (40) and each one's writers and evictors; every external command the package spawns (tasklist, pgrep, net use, subst, net share, powershell/CIM, ioreg, diskutil, lsof, ps, nvidia-smi, osascript). Loop bodies read in full: LaneWatchdog, site refresh, identity watch, LUT loop, canon relink, watcher.run/poll_once, jobs_runner tick/_gate/runnable_kinds, capabilities.build, proxy_gen tick/_gate, broll_ingest tick/_gate/prune_staging, youtube_import loop, UploadQueue._loop, OriginalsInbox, root_guard, keep-awake, sorter_cards, sorter_volumes, unopened_scan, resolve_prefs.resolve_process_state and all its callers, script_server's Toolhelp helper. The nine territory reports (comp-app, comp-core, comp-sync, comp-resolve, comp-ui, comp-media, comp-jobs, comp-field) were read first and are cited, not repeated.
Probes run (all under my scratch folder, HOME/USERPROFILE/LOCALAPPDATA redirected there; nothing written to it by the import):
- `python -X importtime -c "import ccsync_companion.app"` with the companion venv: 0.166 s total, 306 modules (table 5).
- `tasklist /FI "IMAGENAME eq Resolve.exe" /NH` x10: median **202 ms** wall on this rig (499 processes); `script_server._windows_processes()` Toolhelp snapshot + name match x50: median **8.5 ms**, no process spawned.

## 1. Long-lived threads, timers and periodic loops

Cadence is at idle (nothing ticked to transfer, Resolve closed unless stated). "Stops" = what ends it.

| module:line | thread name | cadence at idle | one tick does | stops |
|---|---|---|---|---|
| tray.py:5313 (`_pulse_loop`) | (unnamed) | 0.375 s | reads a tuple; usually nothing to pulse (comp-ui-5) | `icon._ccsync_stop` |
| tray.py:5311 (`_refresh_loop`) | (unnamed) | 2 s | full `sync_guard()` rebuild incl. ingest staging walk (comp-app-1), 3 site.json parses (comp-ui-5), menu fingerprint | `icon._ccsync_stop` |
| broll_upload.py:421 (x2: b-roll + music queues) | ccsync-broll-upload | **1 s, forever once the first upload ran** | lock + two attribute reads, then `wait(1.0)` | `_stopped` (stop()) |
| originals_requests.py:345 | ccsync-originals-inbox | 2 s | `iterdir()` of the local request inbox | `_stop` |
| watcher.py:849 (app.py:10744) | ccsync-watcher | 3 s | CR-68 probe (TCP table + Toolhelp, comp-resolve-7) -> maybe scriptapp (comp-resolve-2) -> stat/realpath per timeline clip (comp-resolve-3); on disconnect `describe_disconnection` (tasklist, 30 s TTL) | `_stop_event` |
| root_guard.py:888 | ccsync-root-guard | 5 s | one stat of the root (macOS: cached diskutil) | `_stop_event` |
| sorter_cards.py:540 | ccsync-sorter-cards | 10 s | `list_volumes("local")`: Windows ctypes GetLogicalDrives/GetVolumeInformationW/disk_usage; **macOS one `diskutil info -plist` spawn per /Volumes entry** (lens-2) | `_stop` |
| sorter_volumes.py:204 | ccsync-sorter-volumes | 10 s | `list_volumes("all")`: the same enumeration again (lens-2); POST only on change (debounced) | `_stop` |
| syncthing_lane.py:971 | ccsync-syncthing-poll | 15 s | 3 + 2N REST calls to local Syncthing (comp-sync-5) | `stop_event` |
| proxy_gen.py:1275 | ccsync-proxy-gen | 15 s (scan every `proxy_scan_interval` 900 s) | gate (idle probe = GetLastInputInfo), maybe a tree scan; no Resolve probe by default (`proxy_gen_skip_while_resolve_running=False`) | `_stop_event` |
| broll_ingest.py:2029 (x2: b-roll, music) | ccsync-broll-ingest | 15 s | gate stops at NOTHING_TO_DO before the Resolve probe; `prune_staging` over in-memory entries | `_stop_event` |
| youtube_import.py:490 | ccsync-youtube-import | 15 s | project-name compare, scan every `youtube_import_scan_interval` 60 s | `_stop_event` |
| jobs_runner.py:989 | ccsync-jobs | 20 s (80 s with an empty queue reported) | `_gate` -> `runnable_kinds` -> `capabilities.build` (tasklist even on cache hit) + gate's own Resolve probe (comp-jobs-2) | `_stop` |
| shutdown_guard.py:1367 / :1599 | ccsync-keep-awake | 30 s | SetThreadExecutionState (macOS: caffeinate child) | `_stop` |
| upgrade.py:1028 (app.py:12516) | ccsync-old-exe | 30 s, until the new build is healthy | stat/delete of the previous exe | `stop_event` / done |
| reporter.py:1500 | ccsync-dashboard-reporter | 60 s (5 s while a lane syncs) | builds the report incl. `capabilities.build` (tasklist, macOS ioreg comp-core-6), POST to dashboard; heavy manifest resent every 600 s (comp-core-2) | `_stop_event` |
| app.py:1091 (LaneWatchdog) | ccsync-thread-watchdog | 60 s | compares heartbeats in memory | `_stop` |
| app.py:10592 | ccsync-identity | 60 s | `identity.valid()` in memory | `_identity_stop_event` |
| sync/sequencer.py:706 | ccsync-sequencer | 60 s idle wait (`sequencer_idle_seconds`) | a lane pass: rclone lane A/B per project (comp-sync-1/2), lane C turn (comp-sync-4) | `_stop_event` |
| unopened_scan.py:506 (app.py:10855) | ccsync-unopened-scan | 60 s after a 120 s delay | CR-383 sweep tick | `stop_event` |
| ledger_outbox.py:434 | ccsync-ledger-outbox | 60 s | flush pending rows (comp-field-6) | `_stop` |
| app.py:3266.. (licence re-arm) | ccsync-licence-watch | 60 s, only while the EULA gate is open | re-offers the dialog | `_licence_asked`, gate clear |
| app.py:5197 | ccsync-media-tree | 120 s | pool classification (net use/subst x2, comp-app-2), proxy-state re-read via Resolve (comp-resolve-1), plan_relinks stats (comp-resolve-9), stale-bridge check (tasklist when disconnected) | `_media_tree_stop_event` / generation |
| sync/originals_lane.py:515 | ccsync-originals-down | 120 s | originals pull cycle | `stop_event` |
| manifest.py:283 | ccsync-manifest-cache | 300 s | full tree walk of ticked projects (comp-core-1) | `_stop_event` |
| sync/rclone_lane.py:3888 (per lane) | ccsync-<lane>-periodic | 300 s (`scan_interval`) | orphan/size/future-dated scans (comp-sync-3) | `stop_event` |
| drive_reminder.py:558 | ccsync-drive-reminder | `drive_reminder_minutes` (30 min) only during an episode | balloon | `_stop_event` |
| app.py:11142 | ccsync-luts | 900 s | LUT link check (Resolve probe via `luts` running_fn), stills check, stray-LUT walk of Resolve's LUT folder | `_stop_event` |
| app.py:10608 | ccsync-site-refresh | 900 s (120 s on failure) | GET /api/v1/site, write site.json | `_stop_event` |
| ytdlp_manager.py:1349 | ccsync-ytdlp | 30 s delay, then its own schedule (hours) | yt-dlp version check | `_stop_event` |
| timeline_cards_role.py:746/748/793 | ccsync-cards-push / -pull / -watch | 1 s push/pull while the role runs; watch 60 s (PowerShell CIM while refused, comp-resolve-8) | OFF by default (`cards_agent`) | `_stop_ev` |
| broll_server.py:3122, field_server.py:323 | ccsync-broll, ccsync-field | blocking `serve_forever` | nothing until a request | server.shutdown |
| tray_native.py:994 | ccsync-tray | message loop | nothing until a message | `_stopped` |
| shutdown_guard.py:655 | ccsync-shutdown-guard | message pump | nothing until WM_QUERYENDSESSION | `_ready`/stop |
| supervisor.py:520 | (separate process) | `poll_seconds` | is the child alive | the child's clean exit |

Per-job / per-event threads (start and end with their work, joined or daemon and bounded by it): rclone stdout/stderr readers and hand-off (rclone_lane 1479, 6527, 6610, 7640), sequencer lane-B thread (2730), jobs heartbeat/progress/scan (jobs_runner 1208-1656), media drains (jobs_media 566-664), proxy_gen workers and readers (1663-2386), field copy lanes (field_copy 374/415), ytdl job + heartbeat (ytdl_executor 2302/3532), broll fetch (443), popups and dialogs (app 3266, 3433, 4939, 6877, 9474; popup 1487-3065; tray 2503), auto/pushed upgrades (app 8812/8927), diagnostics upload (9706), tmp sweep (10585), resolve-menu install (10837), canon relink drain (3704, single-flight). Threading.Timer one-shots: app 12240/12473/12486/12497 (3 s / grace), rclone_lane 7031/7063/7231 (retry and debounce, each replaced not stacked), tray 1111.

None of the long-lived loops above lacks a stop path; the only one that never goes back to sleep properly is the UploadQueue worker (lens-4).

## 2. Subprocesses spawned on a schedule (Windows unless marked)

Measured here: tasklist **202 ms** wall (comp-jobs-2 measured 164 ms on another run); comp-app-2 measured `net use` 13.4 ms and `subst` 12.6 ms; comp-resolve-8 measured PowerShell+CIM 441-504 ms.

| command | call site(s) | cadence | per hour, idle Resolve closed | per hour, Resolve open | per hour, sync running | cost each |
|---|---|---|---|---|---|---|
| `tasklist /FI IMAGENAME eq Resolve.exe` | `resolve_prefs.resolve_process_state` (resolve_prefs.py:159), reached from the 9 callers in lens-1 | see lens-1 | **~230-545** | **~110-245** | **~800-1,100** | 160-235 ms wall, one process create + Defender scan |
| `tasklist ... TeraCopy.exe` | teracopy.py:372 | 5 s per lane during a TeraCopy copy (comp-field-11) | 0 | 0 | 720/lane during a card copy | same |
| `net use P:` (+ `subst`) | app.py `_classify_pool_once` + `_refresh_p_mapping_mode` | 120 s media-tree tick, twice (comp-app-2) | 0 | 60-120 | 60-120 | 13 ms each |
| `powershell Get-CimInstance Win32_Process` | timeline_cards_role.py:342 | 60 s while the Cards role is refused (comp-resolve-8) | 0 (role off by default) | 60 when refused | same | 441-504 ms |
| `powershell Get-CimInstance ... Resolve.exe` | bpg.py:226 | only when BRAW/R3D clips need BPG and the user is away; TTL-cached | ~0 | ~0 | ~0 | ~450 ms |
| `rclone` (copy/lsjson/sync) | sequencer lane passes, lane B listing (comp-sync-1), b-roll uploads (comp-media-4) | per pass / per item | per ticked project per 60 s pass | same | dominant | process + SSH handshake |
| `ffprobe`/`ffmpeg` | proxy_gen, jobs_media, ingest | only with work | 0 | 0 | per item | - |
| `nvidia-smi` | broll_vlm/local_runtime.py:932 via capabilities (cached) | once, cached | ~0 | ~0 | ~0 | - |
| macOS `ioreg -c IOHIDSystem` | idle.py:213, every capabilities build (comp-core-6) | per report + per jobs tick | ~60-240 | same | ~720+ | 10-30 ms est. |
| macOS `pgrep -x "DaVinci Resolve"` | resolve_prefs.py:166 (the Mac branch of lens-1's probe) | as tasklist | ~230-545 | ~110-245 | ~800-1,100 | ~10 ms est. |
| macOS `diskutil info -plist <vol>` | sorter_cards.py:224, called by BOTH sorter loops | 10 s x 2 loops x V volumes | **1,440-2,880** (V = 2-4) | same | same | 50-150 ms est. (diskarbitrationd round trip) |
| macOS `lsof -iTCP:1144` | script_server.py:313 (CR-68 probe) | every watcher poll (3 s), short cache | ~1,200 | ~1,200 | ~1,200 | 30-80 ms est. |

**Total scheduled spawns per hour, one Windows editor at idle with Resolve closed: ~230-545** (all of them tasklist), **~170-365 with Resolve open** (tasklist + net use/subst), **~900-1,250 while a sync runs** (before rclone). A Mac editor adds ~2,700-4,300 an hour of ioreg + diskutil + lsof on top of the pgrep equivalent.

## 3. Module-level and long-lived containers written at runtime

| container | key | evicted? | bound |
|---|---|---|---|
| proxy_relink.py:379 `_GEOMETRY_VERDICTS` | proxy path (+stored size) | **only `reset_geometry_verdicts()`, "tests only"** | distinct proxies probed in the process lifetime (lens-3) |
| proxy_relink.py:643 `_REFUSALS` | (clip, proxy path) | only `reset_refusals()`, "tests only"; restart is "the only way" | refusals seen; small in practice |
| proxy_relink.py:445 `_FLEET_STANDINS` | path | cleared on each fleet refresh | one fleet list |
| resolve_bridge.py:2146 `_uid_cache` | clip uid | reassigned whole per walk | one pool |
| resolve_journal.py:112-126 `_sessions`, `_save_points`, `_automatic_at`, `_automatic_daily` | project slug (x source) | `_sessions` popped on close; the other three never | projects opened in the process lifetime (~100; bytes) |
| paths.py:102 `_prefix_cache` | (root, prefix) | TTL on read, never deleted | handful |
| paths.py:119 `_share_cache` | SMB share name | TTL on read | handful |
| transport.py:81 `_cache`, :284 `_refusal_logged` | host | TTL / never | dashboard hosts (1-3) |
| sync/rclone_lane.py:737, 741, 1183 | (route, url) / host / rclone path | clear on reconfigure | handful |
| sync/lane_guard.py:1189 `_trash_summary_cache` | local_root | popped on change | 1 |
| ffmpeg_tools.py:197, 256 | ffmpeg path | TTL / never | 1-2 |
| machine_settings.py:89 `_mem_answers`; :405 `_kinds_cache` | ask key; kinds key | one pending ask; cleared above 32 | bounded |
| music_server.py:234 `_probe_slots` | probe key | stale pruned above 16 | 16 |
| teracopy.py:395 `_CLAIMED` | history db name | cleared above `_CLAIMED_MAX` | bounded |
| upgrade.py:1353 `_OFFER_NOTES` | version | cleared above 8 | 8 |
| broll_fetch.py:173 `_JOBS`; broll_server.py:1390 `_UPGRADES_IN_FLIGHT`; jobs_media.py:359 `_partials` | job / clip / partial path | popped/discarded at the end of the work | in-flight only |
| sorter_cards.py:107 `_busy`; :108 `_known_drives` | volume serial | `_busy` popped; `_known_drives` never | volumes ever plugged in (dozens; bytes) |
| sorter_cards `_seen` / `_first_seen` (instance) | serial | popped when the volume leaves | volumes present |
| originals_requests `_answered` (instance) | request file name | popped on delete | in-flight requests |
| settings_window.py:1264 `_address_verdicts` | URL typed in Settings | never | URLs typed (tiny) |
| crash_report.py:731 `_relaunch_history` | timestamp | (supervisor, 3/hour cap) | small |
| site.py:364 `_BRAND_CACHE`; theme.py:190; tray.py:341, 399 | 1 entry / icon size | overwritten | constant |
| ui_dispatch.py:722 `_registry` | Tcl interpreter id | freed on the building thread (CR-93); a raising dialog leaks one (comp-ui-3) | dialogs |
| sidecar_tools.py:167 `_failure_causes` | tool name | popped on success | 2-3 |
| broll_vlm/local_vlm.py:211 `_servers` | model key | cleared on stop | 1 |

No `lru_cache` / `functools.cache` anywhere in the package. The only container whose bound is "everything ever looked at" with no field eviction is `_GEOMETRY_VERDICTS` (lens-3); the rest are keyed by things that do not keep arriving (projects, hosts, volumes) or are explicitly capped.

## 4. Totals (one Windows editor; estimated from the cadences above unless marked)

| | idle, Resolve closed | idle, Resolve open | sync running |
|---|---|---|---|
| thread wakeups / minute | **~360** (pulse 160, two upload queues 120 once used, tray 30, originals inbox 30, watcher 20, root guard 12, sorter 12, the 15 s loops 20, the rest < 15) | ~360 | ~380 (report every 5 s, rclone readers) |
| subprocess spawns / hour | ~230-545 | ~170-365 | ~900-1,250 + rclone |
| dashboard HTTP calls / minute | ~1.1 (report 60 s, jobs claim only when offered, site 900 s, sorter posts on change) | ~1.1 | ~12 (report every 5 s) |
| local Syncthing REST calls / minute | 12 + 8N (comp-sync-5; N = 27 -> 228) | same | same |
| bytes to the dashboard / day | ~510 MB with 10 ticked 5k-file projects (comp-core-2's heavy resend dominates; light report ~few KB x 1,440 = single-digit MB) | same | higher: the heavy section changes and is resent each 300 s rescan |

At 20 machines the fleet does ~5,000-11,000 tasklist spawns an hour at idle and ~20,000 while syncing - the same probe asked through nine doors.

## 5. Import cost

`__main__.py` runs `_startguard.begin()` at import, so I imported `ccsync_companion.app` (no top-level statements beyond definitions and the ui_dispatch Tk wrapper) with HOME/USERPROFILE/LOCALAPPDATA redirected to scratch; nothing was written there. **0.166 s total, 306 modules.** Top cumulative: app 166 ms, broll_ingest 85 ms, broll_server 52 ms, config 28 ms, broll_fetch 17 ms, urllib.request 16 ms, ytdl_executor 15 ms, logging(+handlers) 24 ms, broll_vlm_sidecar 11 ms, popup 10 ms, rclone_lane 10 ms, tkinter 9 ms. The b-roll/ytdl chain (~110 ms) could be lazy, but this is paid once per tray start and once per onefile worker re-entry, where comp-media-3 shows the extraction, not the import, is the cost. **Not a finding**: under 0.2 s on a process that lives for weeks.

## Findings

### lens-longrun-companion-1 - One cached "is Resolve running" probe instead of a tasklist spawn behind nine doors
- Category: idle
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/resolve_prefs.py:143-171 (`resolve_process_state`, the only spawn); callers capabilities.py:495-520 (`_resolve_block`, uncached even on a cache hit, from reporter.py and jobs_runner.py:682/736/817), jobs_runner.py:614/758, broll_ingest.py:1004/1114 (+ music ingest), proxy_gen.py:705-723/925 (own 60 s TTL), resolve_bridge.py:640-662 (own 30 s TTL), app.py:4926/4993/12587, luts.py:474, resolve_prefs.py:367/462/519/572
- What: every Windows "is Resolve up" question spawns `tasklist` (macOS `pgrep`). Three modules each grew their own TTL cache around it (proxy_gen 60 s, resolve_bridge 30 s, capabilities caches everything EXCEPT this field), the rest call it raw, and two hot paths call it per tick or per frame. The process table is already read in-process by script_server's Toolhelp snapshot on every 3 s watcher poll.
- Cost / failure scenario: per Windows editor, ~230-545 tasklist spawns/hour idle with Resolve closed (reporter 60, bridge disconnection text 120, jobs runner 45-360, LUTs 4), ~110-245 with Resolve open, ~800-1,100 while syncing (report every 5 s); during an ingest batch +~29 per clip (comp-media-1, ~8,000-40,000 per batch). At 202 ms wall each (measured) that is 45-110 s of spawn wall time per idle hour per machine beside Resolve; 5,000-11,000 spawns/hour across 20 machines.
- Evidence: grep of all callers (one spawn site, nine call paths); probe: tasklist median 202 ms vs `script_server._windows_processes()` + `is_resolve_name` median 8.5 ms (499 processes), and a cache hit is a lock + monotonic read.
- Ledger: consolidates comp-jobs-2, comp-media-1, comp-resolve-7 (each filed one door); the reporter/capabilities door (60/h idle, 720/h syncing) is filed by none of them.
- Suggested change: replace the Windows branch of `resolve_process_state()` with a Toolhelp32 snapshot (reuse `script_server._windows_processes`, match `Resolve.exe` by image name exactly as tasklist did, so BPG still counts) behind ONE module-level 5 s TTL cache that stores the three-valued answer; keep `resolve_is_running()`'s fail-closed collapse (None -> True) and `_maybe_warn_scripting_dead`'s positive-sighting-only use; on macOS cache `pgrep` the same way. Then delete proxy_gen's `_resolve_probe` TTL and resolve_bridge's `_probe_cache` (or leave them; they become free). Must not break: CR-68 (this reads the process table, never connects), the fail-closed bias for prefs writes (resolve_prefs 367-572 may bypass the cache with `fresh=True` since a write under a running Resolve loses the edit), and the jobs gate's "fresh answer per tick" (5 s is far inside the 20 s tick).
- Effort / risk: S effort; low risk

### lens-longrun-companion-2 - On a Mac, both sorter loops spawn `diskutil` for every mounted volume every 10 seconds
- Category: idle
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/sorter_cards.py:194-244 (`_mac_volumes`: `diskutil info -plist` per /Volumes entry, before any freshness check), called from sorter_cards.py:563 (`current_cards`, scope "local") and sorter_volumes.py:225 (`current_volumes`, scope "all"); both loops 10 s (SCAN_SECONDS), both default ON (`sorter_cards_enabled`, `sorter_ledger_enabled`)
- What: the two Footage Sorter loops each enumerate the same volumes independently, and on macOS each enumeration spawns one `diskutil` per mounted volume (the startup disk included under "local"/"all") whether or not anything changed. sorter_cards' 120 s `RELIST_SECONDS` freshness cache sits AFTER `list_volumes`, so it saves the card listing but not the spawns.
- Cost / failure scenario: 2 loops x 360 ticks/hour x V volumes (2-4 on a typical editor Mac: Macintosh HD + an external sync drive + a card) = 1,440-2,880 `diskutil` spawns an hour, ~35,000-70,000 a day, on every Mac for weeks, each a fork/exec plus a diskarbitrationd round trip (estimated 50-150 ms; ~1-7 min of spawn wall time an hour) on laptops often on battery, regardless of whether the studio uses the sorter at all. Windows is unaffected (ctypes, comp-field's "already good").
- Evidence: code read of both loops and `_mac_volumes`; comp-field read the Windows path only and comp-app noted the default-on scan as an OUT OF TERRITORY line without the Mac spawn.
- Ledger: new (related to comp-app OUT OF TERRITORY note on sorter defaults; comp-field-9 is the Windows relist)
- Suggested change: one shared volume enumerator in sorter_cards with a ~10 s cache that both loops read; on macOS cache each volume's diskutil answer keyed on (mount path, `os.stat(root).st_dev`) and re-run `diskutil` only for a mount that is new or whose st_dev changed (capacity/free come from `shutil.disk_usage`, which needs no spawn). Must not break: the startup-disk Data-volume serial rule, the "busy volume is reused, not touched" rule, and a re-mounted card being re-described.
- Effort / risk: S effort; low risk

### lens-longrun-companion-3 - The proxy geometry-verdict cache keeps every proxy path it ever saw, with no field eviction
- Category: leak
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/proxy_relink.py:379, :408-416 (`note_geometry_verdict` writes), :419-422 (the only clear, "Tests only"); same shape at :643/:686/:714-718 (`_REFUSALS`, "a restart is the intended (and only) way to clear this")
- What: each geometry probe stores (fingerprint, verdict) keyed by proxy path. Entries are validated by fingerprint on read, so a stale one is harmless, but nothing removes it; the dict grows with every distinct proxy the 120 s relink planning and the refresh look at for the life of the process.
- Cost / failure scenario: ~250-400 bytes per entry (path string + tuple + dict slot, estimated). Today an editor touching ~10-20k proxies over weeks holds a few MB; a base rig or commercial site cycling through 500 projects x 5k files could reach 500k entries, ~100-200 MB in a tray process that runs for weeks beside Resolve.
- Evidence: code read: one writer, one clear reachable only from tests; no size check.
- Ledger: new
- Suggested change: make both an `OrderedDict` LRU capped at ~20,000 entries (move_to_end on read, popitem(last=False) on overflow). A miss only re-probes, so the cap cannot change a verdict. Must not break: `_REFUSALS`' "never relink to a proxy we refused this session" for proxies still in play, so cap it generously (it is small) or key its eviction on the project closing.
- Effort / risk: S effort; low risk

### lens-longrun-companion-4 - Two upload-queue threads poll every second forever, and the originals inbox lists its folder every 2 s, though all three have a wake event
- Category: idle
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/broll_upload.py:448-460 (`UploadQueue._loop`: `self._wake.wait(timeout=1.0)` when idle; instances at broll_ingest.py:2888 and music_ingest.py:607); originals_requests.py:351-358 (`POLL_SECONDS = 2.0`, `iterdir()` each tick)
- What: the upload worker is started lazily on the first upload but never exits or sleeps long afterwards: every second it takes the lock, sees an empty queue and waits again, although every enqueue/resume/stop already sets `_wake`. The originals inbox polls a local folder every 2 s for a request file the Resolve menu script drops a few times a week.
- Cost / failure scenario: 120 wakeups/minute (both queues) for the rest of the process's life after one ingest, plus 1,800 directory listings an hour of the inbox - about a third of the ~360 idle wakeups/minute in the census (comp-ui-5 filed the pulse thread, the other big one). CPU cost is tiny; the cost is a laptop never reaching deep idle and Defender seeing a steady trickle of file opens.
- Evidence: code read; every state change in broll_upload (`enqueue`, `pause/resume`, `_finish`, `stop`) calls `self._wake.set()`.
- Ledger: new (comp-ui-5 covers the pulse thread)
- Suggested change: in the idle branch wait without a timeout (or 60 s as a belt), since `_wake` is set on every change; poll the originals inbox every 10-15 s (a menu click answered in 10 s instead of 2 s is still immediate to a person) or have the menu script's request trigger a wake through the 8899 loopback it can already reach. Must not break: the NAS-unreachable retry (keeps its explicit 5 s wait) and `stop()` waking the thread.
- Effort / risk: S effort; low risk

## What is already good
- Every long-lived loop waits on an Event, not `time.sleep`, and has a stop path; the LaneWatchdog heartbeats the ones that can wedge inside Resolve or rclone. Leave the watchdog alone.
- Nearly every module-level cache is keyed by something that does not keep arriving (host, project, volume) or is explicitly capped (`_probe_slots` 16, `_kinds_cache` 32, `_OFFER_NOTES` 8, `_CLAIMED`); there is no `lru_cache` on a method anywhere.
- The idle gates of proxy_gen and both ingestors stop at NOTHING_TO_DO before they reach the Resolve probe, and the jobs runner backs off to 80 s on an empty queue: the idle cost of the GPU features is small.
- Windows idle detection is `GetLastInputInfo` and volume detection is ctypes - no spawns. Copy that pattern for the Resolve probe (lens-1).
- Import of the whole app is 0.17 s; nothing at import touches `~/.ccsync`.

## Coverage note
- Spawn costs on macOS (diskutil, ioreg, lsof, pgrep) are estimated, not measured - there is no Mac here. Wakeup and HTTP totals are computed from the cadences read, not from a trace of the running tray (the live companion was not touched).
- I did not trace instance-level containers in every long-lived object (sequencer, rclone_lane, reporter digests, watcher's offered-path set); I checked the module-level ones exhaustively and the sorter/originals/upload instances.
- Bytes per day reuse comp-core-2's measured heavy payload; I did not measure the light report's size.

## OUT OF TERRITORY
- none (this lens is the companion process as a whole).
