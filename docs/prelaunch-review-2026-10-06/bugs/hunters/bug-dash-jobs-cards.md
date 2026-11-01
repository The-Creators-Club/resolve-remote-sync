# bug-dash-jobs-cards - pre-launch bug hunt, 2026-10-06

Lens: dashboard jobs.py (scheduler), cards*.py (cards, cards_pool, cards_wsgi,
cards_tunnel, cards_exec, cards_landing, cards_catalog, cards_ai),
assignments.py, locate.py, links.py, the broll.py / music.py / ytdl.py mount
gates, ai_providers.py, cli_tools.py. Working tree as of HEAD 08b40eb plus the
uncommitted changes. Read-only; one throwaway probe in the scratchpad drove
`cards._gate_readings`, `CardsDispatch._child`, a2wsgi's `build_environ`,
`cards_wsgi.request_head` and a stock `BaseHTTPRequestHandler` with
percent-encoded paths (no live system touched).

Checked against KNOWN_BUGS.md and docs/bug-hunt-2026-09-24/hunters
(bug-dash-cards-jobs, logic-cards, logic-ytdl-jobs, bug-music-ytdl,
logic-broll-music, bug-broll) so fixed items are not re-reported.

Read in full: jobs.py, cards.py, cards_wsgi.py, cards_tunnel.py, cards_pool.py,
cards_exec.py, cards_catalog.py, locate.py, links.py, assignments.py, the
gates in broll.py / music.py / ytdl.py, the job routes in api.py and the job
CAS functions in db.py. Read in part: cards_landing.py (routes, state, PWA),
cards_ai.py (Runner, session store), ai_providers.py (keys, cli_path, routes),
cli_tools.py (download, install, auto-update, routes). Not read: cards_ai's
SDK message-building internals, cli_tools' pty sign-in worker in detail, the
ytdlweb / broll-web / musicweb sub-apps beyond what the gates touch.

### bug-dash-jobs-cards-1 - A percent-encoded `?` or `#` walks past CardsGate: `/cards/p/<slug>/api/root%3F` reaches `engine.set_root()`
- Severity: high
- Confidence: CONFIRMED (probed)
- Where: dashboard/src/ccsync_dashboard/cards.py:421-464 (CardsGate, _gate_readings); cards_wsgi.py:200-219 (request_head)
- What: uvicorn percent-decodes `scope["path"]`, so `%3F` becomes a literal `?` in the path the gate matches. `_gate_readings` collapses slashes and resolves dot segments but does not cut at `?`/`#`, so `/api/root?` is not in BLOCKED_PATHS. `request_head` then writes `PATH_INFO + "?" + QUERY_STRING` into the synthetic request line, and the handler's `urlparse(self.path).path` is `/api/root`. Probe output: `'/cards/p/abc/api/root%3F' gate blocked: [] head: b'POST /api/root? HTTP/1.0' -> handler sees /api/root`. `%23` (`#`) does the same through urlparse's fragment split. Decoded `%0D%0A` also injects header lines into the synthetic head (harmless today because the mount mints no trusted header, but it is a request-smuggling shape).
- Scenario: any signed-in editor (not only an admin) POSTs `{"root": "/vault/.../Other Episode"}` (or any directory in the container, such as `/data`) to `/cards/p/<slugA>/api/root%3F`. Engine A moves onto episode B, which may already have its own engine, so two engines now read-merge-write B's cut list and pick files. That is the exact failure bug-dash-cards-jobs-1 fixed for `//`. `/api/restart%3F` also reaches `restart_server`: on the Linux container it only gets as far as `Popen(creationflags=...)` raising, so it fails by luck, not by design (on a Windows dev run it would `os._exit(0)` the dashboard).
- Recommendation: in `_gate_readings`, also add each reading cut at the first `?` and `#` (and refuse any path containing CR, LF or NUL with a 400). Better: have `request_head` percent-encode PATH_INFO again (`urllib.parse.quote(path, safe="/:@!$&'()*+,;=-._~")`) so that the handler can never see a decoded `?`, `#` or CRLF. Add a test that sends `%3F`, `%23` and `%0D%0A` variants of both blocked routes.
- Known: new. It is a sibling of bug-dash-cards-jobs-1 (fixed).

### bug-dash-jobs-cards-2 - Turning the YouTube downloader off on a running dashboard leaves its worker downloading
- Severity: medium
- Confidence: CONFIRMED (read end to end)
- Where: dashboard/src/ccsync_dashboard/ytdl.py:468-578 (YtdlFeatureGate); ytdl/web/ytdlweb/worker.py:170-200, 255-320
- What: `YtdlFeatureGate` re-reads `[features] youtube_download` every 5 s, and when it goes false it only answers 404 to HTTP. The worker thread started by `ensure_started()` (and the yt-dlp nightly refresher started with it) is a `while True` loop that never consults the flag. `_tick` claims and runs every queued and `downloading` job exactly as before.
- Scenario: a customer enables the downloader, editors queue jobs, and the customer's counsel then says stop. The admin unticks the feature. The page reports the feature as off and the nav hides it, but the container keeps fetching YouTube media into the shared tree (and keeps pulling yt-dlp nightlies from GitHub) until the container restarts. The module docstring promises that an off site "runs no pipeline thread", and docs/legal/YOUTUBE_FEATURE_NOTICE.md puts the lawfulness decision on that switch.
- Recommendation: have `worker._tick` (and the nightly refresher) check a "feature enabled" callable that the mount installs, the same way `_install_ai_provider_lookup` installs the provider lookup. When it is off, claim nothing and park the in-flight job. Alternatively have `YtdlFeatureGate._record(DISABLED)` call a `worker.stop()`. Either way, show "N jobs paused by the site switch" on the admin page.
- Known: new.

### bug-dash-jobs-cards-3 - Each Cards agent long-poll holds one of the 40 shared threadpool workers, so a fleet of about 40 agents stalls /report and every sync route
- Severity: medium
- Confidence: PLAUSIBLE (mechanism read and confirmed; not load-tested)
- Where: dashboard/src/ccsync_dashboard/cards_tunnel.py:430-500 (cards_agent_pending, a blocking `def`); cards_tunnel.py:200-230 (_wait_for_an_engine); deploy/run.sh:593,608 (`--workers 1`)
- What: `/cards/agent/pending` is a sync route by design, so FastAPI runs it on anyio's default thread limiter, which allows 40 threads per process. The route holds its worker for up to 25 s on every call, back to back. That happens both when the editor is in an episode (`engine.agent_pending`) and when they are not (the dash-cards-1 hold in `_wait_for_an_engine`). Every machine with `cards_agent` on therefore pins one worker permanently. `api_report`, `get_conn` and most of api.py are sync routes too, and the dashboard runs as one process. Nothing raises the limiter (no `total_tokens` anywhere).
- Scenario: a customer with 40 or more editing machines turns the Cards role on fleet-wide. All 40 tokens sit in long polls, so `/api/v1/report` and every page's sync dependencies queue behind 25 s holds. The fleet grid goes stale and companions time out their reports. This is the "dashboard is what tells everyone whether their footage is syncing" outage, caused by an optional feature. At 20 to 30 agents, the latency of every sync route already degrades whenever other slow sync routes are running at the same moment.
- Recommendation: make the long poll async: await an asyncio.Event per engine and editor, or run the engine call through a dedicated small executor with its own cap. Also, or alternatively, raise `anyio.to_thread.current_default_thread_limiter().total_tokens` at startup, sized to the fleet plus headroom. Shorten the no-engine hold to a few seconds with jitter.
- Known: new. dash-cards-1 introduced the hold deliberately; its thread cost was not counted against the limiter.

### bug-dash-jobs-cards-4 - Closing a Cards episode frees the seat but leaks the engine (its threads and about 128 MB), so open/close cycles grow the dashboard until it OOMs
- Severity: medium
- Confidence: CONFIRMED (code); growth rate PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/cards_pool.py:707-730 (drop), 753-766 (_stop); MulticamPipeline cards/project_agent.py:686 (`stop()` only sets `_stop`); library_engine.py / translate.py worker loops
- What: `drop()` (now reachable by any editor for an idle episode, security-2) calls `engine.stop()`, which only sets a flag that the library worker, tokens worker and translator ignore. Those threads keep running and keep the whole engine reachable. The cap counts entries, so a seat frees and the next open builds another engine. The pool's own docstring and CARDS_TWO_PROJECTS.md section 6.1 say so, but there is no bound, alert or restart policy.
- Scenario: a studio with a dozen episodes moves between them all day: open B, close A, open C. Each switch leaves a dead engine with its sweep still walking the vault share, plus about 128 MB and about 15 threads (the 2026-09-14 measurement). Over a week without a container restart, NAS RAM fills and the dashboard (fleet status, reports, client links) is OOM-killed or swaps. The orphaned sweeps also keep hitting the share.
- Recommendation: land the real `stop()` upstream (plan section 6.1) before selling Cards. Until then, count leaked engines in `cards.health_block`, refuse a new open once `leaked + live` passes a ceiling (with a sentence telling the admin to restart), and raise an alert kind for it.
- Known: docs/CARDS_TWO_PROJECTS.md section 6.1 ("A real stop()", open). No KNOWN_BUGS id.

### bug-dash-jobs-cards-5 - Montage sessions in `<data>/cards_sessions` are never pruned: unbounded disk use and indefinite retention of interview transcripts
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards_ai.py:1209-1222 (_session_path/_sessions_dir), 648-668 (_open_convo/_save_convo)
- What: every montage or search conversation is written whole, including the corpus parts (measured 68k to 89k characters per part, several parts each), as `<data>/cards_sessions/<uuid>.json`. Nothing deletes these files, and no page or health line shows the directory's size.
- Scenario: a commercial customer runs searches daily for months. The /data dataset, which `_check_dashboard_space` treats as critical below 2 GB, fills with transcript copies. The dashboard's own database then fails to write. Separately, interview transcripts persist on the server indefinitely outside the vault, which docs/legal (retention and erasure) does not account for, and the account-deletion flow does not touch them.
- Recommendation: prune in the collector's prune cycle (for example, untouched for 30 days, plus a file-count cap). Report the count and bytes in the cards health block. Mention the store in the privacy and retention documentation.
- Known: DDIAG-19 (docs/usability-resilience-sweep-2026-09-03/DDIAG.md), still open.

### bug-dash-jobs-cards-6 - Whether a spent media job is pinned or abandoned depends on whether somebody happens to have a Cards episode open at that moment
- Severity: low
- Confidence: CONFIRMED (code path)
- Where: dashboard/src/ccsync_dashboard/jobs.py:120-133 (can_pin); cards_exec.py:153-172 (engine/available); cards.py:385-402 (engine_provider)
- What: `can_pin()` asks `PinnedExecutor.available()`, which resolves the provider to `pool.any_engine()`. With no READY episode that is None, so the answer is False, and `fail_job` / `expire_leases` mark the media job ABANDONED rather than PINNED. engine_provider's docstring calls this exact outcome ("every media job that spent its fleet retry budget would go abandoned") a silent regression. The fix only holds while an episode is open. The later "pinned and waiting for an engine" path (bug-dash-cards-jobs-3) can therefore only ever hold jobs that were pinned while an engine happened to exist.
- Scenario: the fleet spends a proxy job's retry budget overnight with no one in Cards. The job is abandoned and not pinned, so the next morning's episode open does not make it. The why page says "given up". Whether the same job is pinned or abandoned is decided by an unrelated person's browser.
- Recommendation: have `available()` answer True when the provider exists and the mounted checkout exposes `fleet_execute` (checkable at mount time), independent of whether an engine is live, and let the tick's existing `_NO_ENGINE` wait handle the rest. Alternatively, say clearly in the explanation and docs that pinning requires an open episode.
- Known: new. Related to bug-dash-cards-jobs-3 (fixed: the pinned jobs wait with no alert).

### bug-dash-jobs-cards-7 - Re-running the Codex SET UP for the installed version deletes the live install before unpacking the new one
- Severity: low
- Confidence: CONFIRMED (code path)
- Where: dashboard/src/ccsync_dashboard/cli_tools.py:1196-1205 (_install_codex)
- What: `target_dir = tool_root / version`, and when that directory exists it is `shutil.rmtree`'d before `_extract_codex_package`. When the publisher's latest equals the installed version (an admin pressing the button again to repair it), that directory is the one `current` points at. If extraction fails (disk full on the NAS dataset, a refused archive), the pointer is left naming a binary that no longer exists, and a running ytdl Codex call loses its files mid-run. The module promises that "a failed or killed install leaves the previously installed version exactly as it was" (the Claude path keeps that promise with an `os.replace`).
- Scenario: an admin presses SET UP again on Codex to fix a broken sign-in, and the unpack fails on a full dataset. Codex is now "not installed", with no previous version to fall back to, and every ytdl job pinned to Codex fails.
- Recommendation: unpack into `<version>.new` and swap with `os.replace` and a rename-aside, or skip reinstalling an identical version whose sha matches the record.
- Known: new.
