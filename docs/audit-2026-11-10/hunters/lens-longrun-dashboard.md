# lens-longrun-dashboard - census of the ONE uvicorn process: threads, pools, children, shared locks, memory, boot and shutdown, across the dashboard and its six in-process mounts

Files read (approximate coverage): app.py lifespan + mounts + CollectorWatchdog (400-1000, 1700-1935, full for those ranges); collector.py lifecycle and loop (200-380); cards.py (mount, build_engine, stop_engine, dispatch, 10-840); cards_exec.py executor loop (236-305); cards_edit.py stop (296-325); cards_tunnel.py long poll (80-120, 455-530); ytdl.py `_init_ytdl_storage` (740-860); ytdl/web worker.py (160-320), ytdlp_nightly.py loop (380-445), db.claim_next_job, vendor/downloader.py conversion (425-460); MulticamPipeline cards/models.py catalogue thread; deploy/run.sh restart loop (565-609); uvicorn 0.52.x `server.py` shutdown (272-320); docs/CARDS_TWO_PROJECTS.md §12 measurements. Every territory report present on 2026-11-11: dash-api, dash-collector, dash-mounts, dash-ops, dash-web, web-broll, web-music, web-ytdl (dash-db, cards-library, cards-server, sorter-py were not yet written). Thread/child census by grep over dashboard/src, ytdl/web, broll/web/app, music/web/musicweb and MulticamPipeline/multicam_pipeline (`threading.Thread(`, `Timer(`, `ThreadPoolExecutor`, `Popen(`, `create_task`, `to_thread`, `lifespan`, `wait(`/`sleep(`).
Probes run (scratchpad\lens-longrun-dashboard\, dashboard venv, `DASH_DEV_INSECURE=1`, `YTDL_WORKER=0`, temp data dir, no port bound, no create_app):
- `python -X importtime -c "import ccsync_dashboard.app"`: 0.536 s wall. Largest: fastapi 0.227 s, ai_providers -> cli_tools -> release_feed -> api 0.203 s (api.py self 91 ms), ui 63 ms, nas.synology -> requests 44 ms. Importing the module starts nothing (all thread starts are in create_app or the lifespan).
- Mount dependencies, cold import each: numpy 0.062 s, yt_dlp 0.201 s, onnxruntime 0.129 s, a2wsgi 0.063 s.
- Read uvicorn's `Server.shutdown` in the dashboard venv: in-flight connections are awaited with `timeout_graceful_shutdown` (default None = unbounded) BEFORE the lifespan shutdown is sent.

## Census

### (1) Threads, pools and children alive in the process

| Mount | Thing (module:line) | Started by | Cadence | One tick | Stopped at shutdown? |
|---|---|---|---|---|---|
| core | `dash-collector` collector.py:218 | lifespan app.py:903 | wakes every <=5 s; kinds on their own intervals (15 s cycle, prune hourly, alerts) | Syncthing polls, inventory window, invariants, alerts, prune; ~18 write tx per idle cycle (dash-collector-1) | yes, `join(10)` app.py:946 |
| core | `dash-watchdog` app.py:436 | lifespan app.py:916 | `DASH_COLLECTOR_WATCHDOG_SECONDS` | reads heartbeat; may restart collector or `os._exit(75)` | yes, `join(5)`, first |
| core | `ccsync-pinned` cards_exec.py:250 | lifespan app.py:890 (whenever /cards mounted) | 10 s | `available()`; with an engine, drains pinned jobs onto the engine's ffmpeg worker | yes, `join(5)`, keeps handle if mid-job |
| core | `release-feed-poller` release_feed.py:1679 | lifespan, only if `release_feed_url` | first at 10 s, then `release_feed_interval` (default 86,400 s) | one HTTPS feed fetch | yes, `join(5)`, after cards_edit |
| core | `lifespan-deadline` Timer dashboard_update.py:596 | top of lifespan | one shot, 600 s | exits a hung startup | cancelled once startup completes |
| core | `code-boot-watchdog` dashboard_update.py:697 | lifespan | one shot, sleeps 45 s | clears boot_attempts.json | ends itself |
| core | `dash-triage-replies` triage.py:883 | only when triage replies are enabled | 120 s | IMAP poll (30 s timeout) | NO (daemon; `_POLLER_STOP` is never set by the lifespan) |
| core | triage run thread triage.py:819 + `claude` CLI child | alerts_triage_hours schedule | daily-ish | Claude Code read-only run, up to 20 min (CLI_TIMEOUT_SECONDS) | NO |
| core | `cli-auto-update` cli_tools.py:1591; install worker :1034; sign-in worker :1992 + pty reader :2191 + Popen :2092 | admin clicks / boot floor then 24 h | 24 h | fetch + checksum a CLI; pty sign-in for 5 min | NO |
| core | `netclass-resolve` netclass.py:181 | a request needing a DNS class | per lookup, TTL 300 s, 1 s timeout | getaddrinfo | n/a (short) |
| core | gear identify hot `claude` child gear_ai.py:117 + stdout pump :127 + `gear-claude-idle` reaper :132 | first photo | reaper every 30 s; child lives up to 1 h idle (IDLE_SECONDS) | stream-json turn | NO (stdin closes at process exit, so the child ends) |
| core | `appliance_config` Timer :389 | wizard save | one shot | `request_restart` | n/a |
| core | anyio default limiter (40 tokens) | every sync `def` route, `run_in_threadpool`, `to_thread`, `FileResponse` chunk reads, every mount's sync routes | per request | - | uvicorn waits for in-flight requests (unbounded, see lens-1) |
| ytdl | `ytdl-worker` ytdl/web/ytdlweb/worker.py:190 | **create_app** (ytdl.py:813, mount time, not the lifespan) | idle: 5 s (`IDLE_WAIT`), one read-only `claim_next_job` on ytdl.db; spawns `claude` health probe at start | search/filter/enrich/download phases; in-process yt_dlp; `ffmpeg` children via `subprocess.run` (downloader.py:305, 456) | NO |
| ytdl | `ytdl-ytdlp-nightly` ytdlp_nightly.py:438 | create_app via ensure_started, only under run.sh ROOT_ENV | daily | pip-installs a yt-dlp nightly into a staging dir | NO |
| ytdl | `ytdl-canary` ytdl_canary.py:197 | create_app; no-op unless `YTDL_CANARY_INTERVAL_SECONDS` | off by default | test download | NO |
| ytdl | vendor ytsearch ThreadPoolExecutor ytsearch.py:310 | inside a search phase | per search | parallel searches | scoped `with` |
| cards | `cards-models-catalogue` MulticamPipeline cards/models.py:199 | on demand from `_row` when the listing is stale | at most once per CATALOGUE_TTL | Models API listing | n/a (short) |
| cards | engine builder thread cards_pool.py:592 | first entry to an episode | once per episode | builds ProjectAgentEngine (seconds of Python, prac-perf-7) | n/a |
| cards | per engine: ~5-6 standing threads (agent.py mirror writer :495, tokens :627, library :805, writer :1355, editor :1675, undo :1878; library_engine sweep/sources/lite/sem/translator :1785/:3125/:4309/:4409) | `engine.start()` | sweep periodic; others queue-driven | library sweep, ffmpeg proxy/peaks worker (Popen library_engine.py:3201), translation pool `TX_PARALLEL=3` | `pool.stop_all()`; measured: 5-6 per engine are NOT stopped by `stop()` (CARDS_TWO_PROJECTS §12, bug-dash-jobs-cards-4) |
| cards | a2wsgi `WSGIMiddleware(workers=24)` executor per engine cards.py:803 | engine build | per request | Cards page requests, its 25 s long poll, media ranges to EOF (dash-mounts-1) | `executor.shutdown(wait=False)` on evict only; not on app stop |
| cards | `claude` CLI children cards_ai.py:559 | any Cards AI call | per call, seconds to minutes; uncapped (dash-mounts-4) | translate/search/shorten/chat turn | NO |
| cards | `cards_catalog` size walker cards_catalog.py:183 | landing page | at most every 12 h per episode | os.walk of an episode (cap 400k) | NO (daemon) |
| cards/edit | `cards-editor` supervisor cards_edit.py:299 + stdout pump :372 + **Node child** :354 | lifespan app.py:895 (when `DASH_CARDS_EDITOR`) | restart backoff to 300 s | supervises `host.mjs` | yes, LAST: SIGTERM, `wait(15)`, kill, `join(5)` |
| cards/edit | WebSocket relay tasks cards_edit.py:894 (2 `create_task` per socket) | each `/sync` socket | per message | relay | cancelled on either side's close |
| sorter | `sorter-load` sorter.py:683 | **create_app** (mount time) | once | loads ~55 MB of clips + catalog | `stop_sorter` app.py:958 |
| broll, music | none of their own | - | - | everything runs in the shared limiter; music's ONNX session is loaded on first search and kept | n/a |

At idle with every feature mounted and nobody in Cards: about 8 Python threads (main loop, collector, watchdog, pinned executor, ytdl worker, nightly, sorter if loading, feed poller) plus up to 1 Node child; CARDS_TWO_PROJECTS measured 4 threads for the bare dashboard and 15-16 with two engines open (before the sorter and the new editor existed). Idle wakeups: collector <=5 s, ytdl worker 5 s, pinned executor 10 s, gear reaper 30 s (when a child exists), triage 120 s.

### (2) Shared resources

**The default threadpool (anyio, 40 tokens).** The Cards page itself does NOT draw from it (each engine has its own 24-thread a2wsgi executor), and the sorter gate waits on an asyncio event. Consumers that HOLD a token for seconds or minutes:
- `/cards/agent/pending` long poll, 25 s, one per machine with the Cards role, continuously, each also holding an open SQLite connection (`Depends(get_conn)`) for the whole hold (wire-5 / dash-cards-2, open, low).
- gear identify: one token per queued photo, up to 120 s each behind the one-photo lock (dash-mounts-3).
- AI provider resolution probing every CLI on the request path (dash-ops-1).
- b-roll index rebuild on a `search_generation` bump inside a search request: ~4 s at 50k clips (web-broll-3); music index rebuild 0.76 s at 5k / 8.2 s at 50k tracks (web-music-4); music model cold load 0.67 s on the first search (web-music-3).
- ytdl `/api/health` with `allow_probe` (1 s), music ingest name checks at scale (web-music-10).
- `FileResponse` chunk reads (b-roll previews, music audio) take a token per chunk, briefly; they keep doing so to EOF after the browser leaves (dash-mounts-1 out-of-territory note).
Arithmetic: today (4 machines, Cards role off in the vendor build) nothing standing; the pool starves only on a 40-photo gear burst (dash-mounts-3). At 20 machines with the Cards role on, 20 tokens are permanently asleep in the long poll, so 20 concurrent slow items (a gear burst of 20, or two index rebuilds plus a handful of probes during a batch) starve every sync route, `/api/v1/report` included. Not filed again here: see lens-4 for the one structural fix.

**The SQLite write lock (dashboard DB).** Holders, longest first: `/api/v1/report` across the CR-379 filesystem walk (dash-api-2), the collector's idle cycle at 18 write transactions per 15 s (dash-collector-1) and remoteneed's delete/re-insert every minute (dash-collector-3), each light report's ~28 KB of WAL (dash-api-5). Waiters: request routes at `busy_ms=5000`, the collector at the background timeout, and ~45 `async def` UI routes that wait ON THE EVENT LOOP (dash-web-1), which is the one place a lock wait stops every request in the process. Separate files with their own writers: ytdl.db (worker, per-row commits, web-ytdl-5), broll.db / client_shares.db, music.db, each Cards episode's state files. Nothing new found here beyond the territory reports; the composite is: any long report write x any admin click on an async route = a whole-process stall.

### (3) Memory budget

| Item | Today | Commercial (50k clips/tracks, 20 machines) | Source |
|---|---|---|---|
| dashboard process alone | 83 MB | ~100 MB (estimated) | CARDS_TWO_PROJECTS §12, measured |
| b-roll semantic index held | ~127 MB (15k clips / 83k embeddings) | 422 MB | web-broll-3, measured |
| b-roll rebuild transient | ~+250 MB (3x peak) | +530 MB (951 MB peak) | web-broll-3, measured |
| music ONNX text tower, after the first search, for life | +560 MB (peak 744 MB while loading) | same | web-music-3, measured |
| music index | ~11 MB | 1,342 MB held, 2,843 MB peak | web-music-4, measured |
| two Cards engines with cuts open | +128 MB | same (cap 2) | CARDS_TWO_PROJECTS §12, measured |
| sorter catalog | ~55 MB on disk, estimated 100-150 MB as Python objects | grows with clips | sorter.py comment; Python size estimated |
| ytdl job in process (yt_dlp) | estimated 50-100 MB | same, one at a time | estimated |
| ffmpeg conversion child (VP9/AV1 -> H.264) | estimated 200-500 MB | same | estimated |
| Node editor child | estimated 100-150 MB | same | estimated |
| `claude` CLI children | estimated 150-300 MB each: 1-3 today | 8-14 concurrent (dash-mounts-4) = 1.5-4 GB | estimated |
| gear hot `claude` child | estimated 200 MB, up to 1 h after the last photo | same | estimated |

Busy moment TODAY (music searched, b-roll index in memory and rebuilding, two engines open, a ytdl conversion, a translation with 3 CLI calls, the Node editor): 83 + 127 + 250 + 560 + 11 + 128 + 125 + 75 + 350 + 125 + 750 = about **2.6 GB**, of which ~1.4 GB is the uvicorn process itself. Commercial: 100 + 422 + 530 + 560 + 2,843 + 128 + 150 + 75 + 350 + 125 + 3,500 = about **8.8 GB**, of which ~4.7 GB is the uvicorn process. No container memory limit is set anywhere in the repo (no `mem_limit`/`limits` in compose, install scripts or deploy), so the kernel's OOM killer chooses on the host: its score is RSS-proportional, so the first victim is the single largest process, which is the uvicorn process holding the model and both indexes - the fleet dashboard, not the CLI children that caused the spike. See lens-3.

### (4) Boot

Measured: `import ccsync_dashboard.app` 0.54 s; the mounts' heavy dependencies add ~0.45 s (numpy 0.06, yt_dlp 0.20, onnxruntime 0.13 - imported only if the mount imports it at mount time, a2wsgi 0.06). The music model and both search indexes are lazy (first search), the Cards engines are lazy (first entry to an episode), the sorter loads in a thread, the release feed waits 10 s. At mount time create_app STARTS the ytdl worker (which immediately runs a `claude` health probe on its own thread) and the sorter load thread. Lifespan: `db.migrate` (a no-op when current), session prune, file-move reconcile, pinned-job release, then threads. Import + mount is about 1 s and is not where deploy downtime comes from; the measured-by-nobody cost is the SHUTDOWN drain in front of it (lens-1) and run.sh's pre-start steps (pip/nightly checks, dash-ops / ops-install territory). Nothing worth making lazier at boot.

### (5) Shutdown, in order

SIGTERM (docker stop -> run.sh trap in image mode -> uvicorn; or the app's own exit-75 request) ->
1. uvicorn stops accepting, then **waits for every in-flight connection with no timeout** (`timeout_graceful_shutdown` unset in run.sh:592/607): a Cards page long poll (25 s, inside an engine's a2wsgi pool), each `/cards/agent/pending` (25 s), every media stream that runs to EOF after its browser left (dash-mounts-1), a gear photo (up to 120 s each queued).
2. lifespan `finally`: watchdog `join(5)` -> collector `join(10)` -> pinned executor `join(5)` -> `cards.stop_engine` (pool.stop_all; 5-6 threads per engine are not stopped, known) -> `stop_sorter` -> **cards_edit: SIGTERM to Node, `wait(15)`, then kill** -> feed poller `join(5)` -> `finish_restart` (exit 75 if an OTA asked).
3. Never stopped: ytdl worker / nightly / canary threads, the triage poller and runs, cli_tools workers, Cards `claude` children, the gear child, a2wsgi executors. Daemon threads die with the interpreter, mid-write if they are writing; their CHILD processes do not (lens-2).
Docker's default stop timeout is 10 s and no `stop_grace_period` exists in the repo, so under `docker stop` everything after the first 10 s of step 1 is a SIGKILL. See lens-1.

## Findings

### lens-longrun-dashboard-1 - Shutdown is unbounded in front and serial behind, so `docker stop` SIGKILLs the lifespan - including the Node editor's cut-list flush - whenever a Cards page or agent is connected
- Category: resilience
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/deploy/run.sh:592-598 and :607 (uvicorn started with no `--timeout-graceful-shutdown`); uvicorn `server.py:272-302` (in-flight connections awaited, `timeout=None`, BEFORE `lifespan.shutdown()`); dashboard/src/ccsync_dashboard/app.py:942-972 (shutdown order); cards_edit.py:107 (`STOP_GRACE = 15.0`) and 303-322; no `stop_grace_period` anywhere in the repo (grep).
- What: The lifespan's shutdown runs only after uvicorn has drained every in-flight request, and the drain has no bound: an open Cards page always has a 25 s long poll in flight, each Cards-role machine has a 25 s `/cards/agent/pending`, and an abandoned media range runs to EOF (dash-mounts-1). Then the lifespan joins the watchdog (5 s), collector (10 s) and executor (5 s) BEFORE it sends the Node editor the SIGTERM whose handler flushes every open cut list (CLAUDE.md: "stopped gracefully by the lifespan because its SIGTERM flushes the cut lists"), and gives Node 15 s. In image mode docker's SIGTERM reaches only run.sh (PID 1) and uvicorn; Node gets nothing but the lifespan's signal.
- Cost / failure scenario: Every image deploy and app update is a `docker stop` with the default 10 s grace. With one Cards page open, step 1 alone is up to 25 s, so the SIGKILL lands before the lifespan starts: no engine stop, no pinned-executor handback, no Node flush, the collector killed mid-transaction (WAL makes that safe, the others are not). With nothing connected, the joins still sum to up to 20 s before Node is asked, plus Node's own 15 s. On the exit-75 OTA path there is no SIGKILL, but the same drain is downtime: up to 25 s + 20 s + 15 s + 5 s = 65 s before run.sh can re-exec, which matches the "health check FAILED is usually premature" note in CLAUDE.md's deploy recipe. Becomes high the day `/cards/edit` is released (cut lists in flight lost on every deploy).
- Evidence: uvicorn source as cited (`_wait_tasks_to_complete` loops while connections exist; `timeout_graceful_shutdown` default None); run.sh flags; repo-wide grep for `stop_grace|stop_timeout|timeout-graceful` returns nothing; app.py order read line by line.
- Ledger: new (dash-mounts-6 covers a different stop race in the same supervisor)
- Suggested change: (a) pass `--timeout-graceful-shutdown 5` in both run.sh lines (long polls already treat a dropped answer as "ask again"); (b) send Node its SIGTERM FIRST in the lifespan (start `editor.stop` on a thread at the top of `finally`, join it last) and signal the collector/executor/watchdog stops together then join, so the waits overlap instead of adding; (c) set `stop_grace_period: 40s` in the app's compose so the whole sequence fits. Must not break: the watchdog must still stop before the collector (or it reads the stop as a death), and the executor before the engine.
- Effort / risk: S effort; low risk

### lens-longrun-dashboard-2 - Mount-time workers are never stopped, and on an exit-75 restart their ffmpeg/CLI children outlive the process into the next one
- Category: resilience
- Severity: medium
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/ytdl.py:813-826 (ytdl worker and canary started in create_app, not the lifespan); ytdl/web/ytdlweb/worker.py:170-201 and 234-241 (`_boot_recovery` puts in-flight downloads back to pending); ytdl/web/ytdlweb/vendor/downloader.py:452-456 (`ffmpeg ... -loglevel error` via `subprocess.run(capture_output=True)`); dashboard/deploy/run.sh:576-604 (run.sh stays PID 1 and re-execs uvicorn on exit 75); app.py:942-972 (no ytdl, triage or cli_tools stop); cards_ai.py:559 (Cards CLI children).
- What: Exit 75 is the OTA restart and the collector watchdog's recovery, and it ends only uvicorn: run.sh lives on and adopts uvicorn's orphans. Daemon threads die, but a child started with `subprocess.run` keeps running. The ytdl conversion's ffmpeg runs at `-loglevel error`, so it writes nothing to its (now readerless) stderr pipe and never meets EPIPE: it keeps re-encoding while the new process's `_boot_recovery` restarts the same download and conversion. Cards `claude` children likewise run to their own end, billed, with nobody to read the answer.
- Cost / failure scenario: A dashboard OTA applied while a 1440p/2160p clip converts (tens of minutes of crf-18 re-encode, web-ytdl-2): two ffmpeg processes on the NAS CPU for the rest of the encode, the orphan writing a staging file the new run is also producing or has swept (`.editready` staging names are deterministic per clip). Frequency: OTAs are a few a week during active development x the chance a conversion is running; rare today, more likely at 20 editors. A watchdog exit-75 during a translation leaves up to 3-14 orphan CLIs (dash-mounts-4).
- Evidence: Read as cited. ffmpeg prints progress at info level, which `-loglevel error` suppresses (ffmpeg behaviour, not run here); run.sh's restart loop keeps the container and PID 1 alive across exit 75. Not reproduced (no container run).
- Ledger: new (web-ytdl-2 covers the missing timeout/cancel, not the restart)
- Suggested change: start the ytdl worker from the lifespan (or register a stop hook) and, on shutdown, kill any child the worker or `cards_ai.Runner` holds: keep the `Popen` handle (Popen + `communicate`, not `subprocess.run`) in a module-level registry that the lifespan terminates; or start such children in their own process group and `killpg` them in `finish_restart` before exiting 75. Must not break: ytdl's boot recovery, which must still treat the interrupted job as resumable.
- Effort / risk: M effort; low risk

### lens-longrun-dashboard-3 - No memory limit, and every resident cache lives in the one process the fleet depends on: the OOM victim is the dashboard
- Category: resilience
- Severity: medium
- Confidence: PLAUSIBLE
- Where: the app compose / install scripts (no `mem_limit`/`limits` anywhere in the repo); music/web/musicweb/text_encoder.py:266 (model kept for life); broll and music index holders (web-broll-3, web-music-4); cards_ai.py:559 (uncapped CLI children, dash-mounts-4).
- What: The music text tower (+560 MB after one search), both search indexes and their 2-3x rebuild peaks, two Cards engines and the sorter catalog all accumulate in the uvicorn process and are never released, while the spiky consumers (CLI children, ffmpeg) are separate processes in the same container. With no cgroup limit, an overrun is resolved by the host kernel's OOM killer, which picks by RSS: the uvicorn process, i.e. the fleet dashboard, the sync status, the report endpoint and the Cards cut in memory, not the child that caused the spike.
- Cost / failure scenario: Census section (3): about 2.6 GB at a busy moment today (1.4 GB in uvicorn), about 8.8 GB at commercial scale (4.7 GB in uvicorn). On today's 64 GB NAS this is headroom; on the 8-16 GB appliances the commercial plan targets, with ZFS ARC taking half, a 50k-track music rebuild during a translation is an OOM, and the victim restarts with the music model and indexes cold.
- Evidence: Hunters' measured figures as tabulated; grep for memory limits returns only two unrelated hits (ytdl routes_api.py, broll ingest_batches.py); RSS-based OOM victim selection is kernel behaviour, not reproduced.
- Ledger: related to web-music-3, web-music-4, web-broll-3, dash-mounts-4 (all new in this audit)
- Suggested change: set a container memory limit sized from this table (about 4 GB today) so an overrun is contained and visible, and add one process-wide idle eviction for the two lazily loaded giants (drop the ONNX session after N minutes without a music search; it reloads in 0.67 s); cap CLI children as dash-mounts-4 proposes. Must not break: the never-fatal mount contract (a reload failure must degrade search, not the mount).
- Effort / risk: S effort for the limit, M for eviction; low risk

### lens-longrun-dashboard-4 - One unpartitioned 40-token threadpool carries both 25 s parked long polls and every sync route, so the standing reservation grows with fleet size
- Category: concurrency
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards_tunnel.py:455-528 (blocking `def` long poll with `Depends(get_conn)`), gear_ai.py:296-298, and every sync route in the dashboard and the broll/music/ytdl mounts; no `CapacityLimiter` configured anywhere in dashboard/src (grep).
- What: Everything that blocks shares anyio's default 40 tokens. The Cards agent long poll parks one token AND one open SQLite connection per Cards-role machine for 25 s, back to back, forever; gear photos park one each while queued; index rebuilds and provider probes hold one for seconds.
- Cost / failure scenario: At 20 machines with the Cards role, 20 of 40 tokens are permanently asleep; 20 more slow holders at once (a 20-photo gear burst, or a music ingest batch triggering rebuilds while probes run) and `/api/v1/report`, the selection reads and every sync UI route queue with no error. Today (role off, 4 machines) it needs a 40-photo burst.
- Evidence: census section (2); wire-5 / dash-cards-2 verifier note confirms no limiter exists.
- Ledger: related to wire-5 (open, low) and dash-mounts-3
- Suggested change: give the long-hold routes their own `anyio.CapacityLimiter` (the long poll and gear identify each `await to_thread.run_sync(..., limiter=...)` from an `async def`), so they can only ever exhaust their own pool; and release the `get_conn` connection before the hold. Must not break: the no-engine hold's pacing (dash-cards-1), which needs the wait, not the thread.
- Effort / risk: S effort; low risk

## What is already good
- Boot is cheap: 0.54 s to import the app, ~1 s with mount dependencies; the music model, both indexes and every Cards engine are lazy, the sorter loads on a thread and the feed poller waits 10 s. Do not "optimise" boot.
- The background loops that do run at idle are event-driven or slow: the collector waits on an Event with nudges, the ytdl worker's idle tick is one indexed read on its own DB every 5 s, the pinned executor returns at once with no engine, the Cards catalog walker is 12-hourly and capped.
- The Cards page draws from its own per-engine a2wsgi executor and the sorter gate waits on an asyncio event, so neither competes with the 40-token pool; the collector and watchdog have explicit, ordered stops with timeouts and keep their handles when a join times out.

## Coverage note
Not reached: the sorter engine's own threads beyond `sorter-load`/`stop_sorter`; a live measurement of the busy-moment RSS (the table adds the hunters' measured figures and labels the rest estimated); whether run.sh's pre-start steps dominate deploy downtime (ops territory); the dash-db, cards-library, cards-server and sorter-py reports, which were not yet written when this census was made, so overlaps with them are unchecked.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/triage.py:812-883: `_POLLER_STOP` exists but nothing in the lifespan sets it; harmless as a daemon, but a test or reload that builds a second app keeps the first poller.
- dashboard/src/ccsync_dashboard/cards.py:629-642: a2wsgi executors are shut down only on evict, never in `stop_engine`; with daemon-less ThreadPoolExecutor workers, interpreter exit waits on any WSGI request still running (another unbounded tail behind lens-1).
