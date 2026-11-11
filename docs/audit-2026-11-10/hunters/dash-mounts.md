# dash-mounts - the dashboard's in-process mounts: /cards (a2wsgi shim, engine pool, tunnel, landing, catalog, exec, AI seam), /cards/edit (Node supervisor + proxy), /sorter, /broll, /music, /ytdl gates, the fleet job scheduler, gear identify

Files read (approximate coverage): cards_edit.py (all), cards_wsgi.py (all), cards.py (all), cards_pool.py (all), cards_tunnel.py (all), cards_catalog.py (all), cards_app.py (all), sorter.py (all), gear_ai.py (all), cards_landing.py (state, scan, routes: ~55%), cards_ai.py (Runner, _sdk, _cli, session store: ~50%), cards_exec.py (executor loop: ~60%), jobs.py (policy, fleet_facts, ranking, offers: ~45%), broll.py (gate: ~40%), ytdl.py (gate: ~15%), music.py (gate lines only). Plus the libraries the mounts stand on: a2wsgi 1.10.10 `wsgi.py`, starlette 1.6.0 `middleware/base.py` and `responses.py`, uvicorn 0.52.3 `httptools_impl.py`; app.py's middleware stack and body gate; MulticamPipeline `cards/handler.py:_serve_range`, `library_engine.stop`, `config.TX_PARALLEL`; the new editor's `server/media` range tests (read only).
Probes run (all under scratchpad\dash-mounts\, dashboard venv, loopback port 0):
- `probe_disconnect.py`: the dashboard's real stack shape (five BaseHTTPMiddleware layers, as app.py has) around (a) `a2wsgi.WSGIMiddleware(cards_wsgi.handler_wsgi(H), workers=24)` with a handler that serves like `_serve_range`, and (b) `cards_edit.Passthrough` over a generator. The client asks `Range: bytes=0-` for a 200 MB body, reads 256 KiB and closes. Result: BOTH producers produced the full 200.0 MiB (WSGI path finished in 0.44 s, proxy path in 0.12 s).
- `probe_disconnect_fix.py`: same stack, with a 20-line ASGI wrapper that races `receive()` for `http.disconnect` on GET/HEAD and makes the writer raise `BrokenPipeError`. Result: the producer stopped at 0.4 MiB, through all five middleware layers.
- `probe_isadmin.py`: `auth.is_admin` for a non-listed user under `auth_method=local` on a migrated temp DB: 1.008 ms quiet, 68.671 ms beside one CPU-bound Python thread.
- `probe_rank.py`: `jobs.first_refusal` for 200 fresh queued jobs: 3.1 / 11.1 / 28.1 ms per report at 5 / 20 / 50 machines (not a finding, see "already good").

## Findings

### dash-mounts-1 - A video seek or an abandoned media request keeps streaming the rest of the file: /cards and /cards/edit never notice the browser has gone
- Category: perf
- Severity: high
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards_wsgi.py:129-146 (`_Writer.write` never raises), cards.py:803 (`WSGIMiddleware(wsgi, workers=24)`), cards_edit.py:701-726 (`Passthrough`, whose docstring says "a browser that goes away is noticed by the next `send` failing") and 796-805 (`stream()`); the mechanism is uvicorn `httptools_impl.py:467-468` (`if self.disconnected: return`, ASGI spec 2.3, so `send` never raises) plus starlette `middleware/base.py:204-241` (`_StreamingResponse` drains the inner app with no disconnect listener). Producers: MulticamPipeline `cards/handler.py:1068-1095` (`bytes=N-` serves to EOF in 64 KiB writes, relying on `ConnectionError` to stop) and the new editor's range parser (`bytes=90-` -> end of file, `editor/server/media/test/units.test.ts:34`).
- What: Behind uvicorn, a `send` after the client disconnects returns silently, so the Cards handler's `except (ConnectionError, OSError)` never fires and `Passthrough` never stops. Every response therefore runs to its last byte: the WSGI thread keeps reading the vault file and handing 64 KiB chunks through the event loop and five middleware memory streams into the void; on /cards/edit httpx keeps pulling the Node child, which keeps reading its file. With no client there is no back-pressure either (uvicorn skips `flow.drain()` once disconnected), so it runs at disk speed.
- Cost / failure scenario: A browser `<video>`/`<audio>` seek aborts the current request and opens `bytes=N-`; scrubbing a lane does this several times a second. Each abort costs the REST of the file: a 480p proxy of an hour-long interview is "hundreds of megabytes" (cards_wsgi.py's own docstring), so 300-700 MB of vault reads per seek, plus about 3,200 event-loop hops per 200 MB (measured 0.44 s of event-loop time per 200 MB on this workstation; the NAS CPU is slower, estimated 1-2 s per discarded 500 MB tail). Each orphaned stream also holds one of the engine's 24 a2wsgi workers until EOF: at an estimated 100-200 MB/s vault read under load, 3-7 s per seek, so a few seconds of scrubbing (roughly 5-8 seeks a second) fills all 24 and the page's own JSON polls queue behind them - the "stall with no error message" cards.py:799-802 sized the pool to avoid. The same bytes compete with the fleet's lane B downloads for the pool's disks. On /cards/edit the leak is identical, and an upstream response that never ends (httpx `read=None`, cards_edit.py:694) would hold a pool connection for ever.
- Evidence: probe_disconnect.py: client read 256 KiB of a 200 MB `bytes=0-` response and closed; the WSGI producer produced 200.0 MiB and finished after 0.44 s, the Passthrough producer 200.0 MiB after 0.12 s. Source of uvicorn 0.52.3 and starlette 1.6.0 as cited.
- Ledger: new (no disconnect entry in KNOWN_BUGS, bug-hunt-*, prelaunch-review; the Passthrough docstring states the opposite of what happens)
- Suggested change: Wrap the per-episode ASGI app (in `CardsDispatch`, before the gate) and `edit_proxy` with a disconnect listener for GET/HEAD only: a task that awaits `receive()` until `http.disconnect` and sets an event. For the shim, put the event in the environ and have `_Writer.write` raise `BrokenPipeError` once it is set (the handler already catches it and closes); for the proxy, stop iterating `aiter_raw()` and `aclose()` the upstream. Proven in probe_disconnect_fix.py (producer stopped at 0.4 MiB through five BaseHTTPMiddleware layers). Must not break: POST bodies (body_size_gate's replay answers `http.request` for ever, which is why the listener is GET/HEAD-only and must ignore non-disconnect messages), and Range/206 bytes must stay byte for byte.
- Effort / risk: S effort; low risk (the stop path it triggers is the one the standalone server has used for months)

### dash-mounts-2 - Every /broll, /music and /sorter request opens a fresh SQLite connection on the event loop to ask "is this person an admin" (local accounts), and beside any busy thread that costs ~69 ms
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/broll.py:287 (`BrollGate._identified_scope`), music.py:297 (`MusicGate`, same shape), sorter.py:107-109 (`SorterGate._identity`, called for EVERY request at :162); the cost is auth.py:1140-1150 (`is_admin` -> `_open_local_conn` -> `db.connect`: connect + 4 PRAGMAs + a SELECT + close).
- What: The three gates are async ASGI callables and call `auth.is_admin(settings, username)` synchronously for every request that carries a session, including thumbnails, media ranges and polls. On `DASH_AUTH_METHOD=local` (the appliance's mode, docs/ZERO_TOUCH_PLAN.md) any name not in `DASH_ADMIN_USERS` costs a brand-new SQLite connection on the event loop. Each sqlite3 call releases and re-takes the GIL, and with any CPU-bound thread in the process every re-take waits out the switch interval (the CR-351 effect, here on the one thread that serves the whole dashboard).
- Cost / failure scenario: Measured 1.0 ms per call quiet and 68.7 ms beside one CPU-bound Python thread. The dashboard process always has candidates for that thread: a Cards engine build (prac-perf-7, "seconds of pure Python"), the music index rebuild, ytdl/AI workers. A b-roll grid of 60 thumbnails is then 60 x 69 ms = about 4 s of event loop blocked for every user of the dashboard (the fleet's /report included); a music page playing audio adds one per range request. Today's studio runs smb auth (`is_admin` returns before the DB), so the cost lands on the first local-accounts customer, and on every non-admin editor there.
- Evidence: probe_isadmin.py on a `db.migrate`d temp DB, `auth_method=local`, user "ruskin" not in admin_users: "quiet: 1.008 ms", "beside one CPU-bound thread: 68.671 ms" per call.
- Ledger: new
- Suggested change: Resolve admin-ness once per request at most and cache it per username for a few seconds in process (a dict of `username -> (verdict, expires)` with a 5-10 s TTL, cleared by the users routes on any role/disable change), or let login_gate stash it on `request.state` beside the session it already resolved so the gates read it like they read `ccsync_session`. Must not break: a disabled or demoted admin must lose the header within the TTL (clear the cache on the write to make that immediate), and the gates must stay fail-closed.
- Effort / risk: S effort; low risk

### dash-mounts-3 - Gear identify keeps every earlier photo in the hot CLI's conversation, so input grows quadratically over the 40-photo session, and queued photos each hold a shared threadpool worker
- Category: perf
- Severity: medium
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/gear_ai.py:56-58 (`IDLE_SECONDS`, `MAX_TURNS = 40`), 168-206 (`HotClaude.ask`: each photo is a further user turn of one stream-json conversation), 296-298 (`run_in_threadpool(hot_for(settings).ask, ...)`, with the lock taken INSIDE the worker at :169)
- What: Every photo is appended as a new user turn with its base64 image, and the CLI sends the whole conversation on every turn (the system prompt even has to say "describe only that photo, never an earlier one"). Turn n therefore carries n images. Separately, each request takes an anyio worker before it waits on the one-photo-at-a-time lock, for up to TURN_TIMEOUT 120 s per photo ahead of it.
- Cost / failure scenario: A packing session of 40 photos carries 1+2+...+40 = 820 image inputs instead of 40 (20.5x). At an estimated ~1,600 tokens per phone photo after Claude's resize, that is ~1.3 M input tokens per session instead of ~64 k (estimated; prompt caching softens the bill but not the per-turn context, the latency growth or the subscription's usage limits, and this runs on the studio's Claude Code login). The warm start being bought is 3.9 s per photo (5.7 s cold vs 1.8 s warm, the module's own measurement), and by turn ~10 the growing context plausibly eats it. A burst of N photos from the website holds N of the dashboard's 40 shared threadpool workers while they queue on the lock (40 photos = every worker, so /report and every sync route stall until the queue drains).
- Evidence: Read gear_ai.py as cited; stream-json input mode keeps the conversation in the process (that is what makes the second turn warm). Token figures are estimated, not measured (no CLI was run).
- Ledger: new
- Suggested change: Recycle the hot process after a small number of turns (for example 5) rather than 40, which keeps the warm start for a burst and bounds the context; and take the lock before entering the threadpool (an `asyncio.Lock` around `run_in_threadpool`) or answer 429 when more than a few photos are already queued. Must not break: one conversation at a time (two photos interleaved would cross answers).
- Effort / risk: S effort; low risk

### dash-mounts-4 - Nothing caps how many Claude Code CLI processes Timeline Cards starts inside the dashboard container
- Category: leak
- Severity: medium
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/cards_ai.py:250-347 (`Runner.run`) and 559-566 (`subprocess.run` of the CLI, one process per call); callers in MulticamPipeline: `config.py:736 TX_PARALLEL = 3` (translation thread pool, `library_engine.py:1844`), `config.py:1054 CHAT_SHORTEN_PARALLEL = 4` (page-driven shorten turns), plus search, montage and chat_edit call sites (24 `run_claude` sites in `cards/*.py`).
- What: `Runner.run` is shared by every engine in the pool and has no semaphore; each CLI-path call spawns a fresh Node `claude` process for the life of the call (seconds to minutes). The engines decide their own parallelism and know nothing about each other or about the container they are in.
- Cost / failure scenario: Two open episodes (the pool's cap), one translating (3 in flight) and one person shortening a cut (4 in flight), plus a search: 8-14 concurrent `claude` processes in the one container that serves the fleet. At an estimated 150-300 MB RSS each, a 1.5-4 GB spike on top of two engines (~128 MB each, measured in CARDS_TWO_PROJECTS), with no ordering between them and the dashboard as a possible OOM victim. The gear identify CLI (gear_ai.py) is a further process outside any count.
- Evidence: Read as cited; no CLI was run here, so the per-process RSS is estimated.
- Ledger: new (com-licensing-billing and bug-dash-jobs-cards-5 cover cost and the session store, not concurrency)
- Suggested change: A module-level `threading.BoundedSemaphore` in `Runner.run` around the provider call (for example 3 for the CLI path, a higher one for the SDK path, which costs no process), with the time spent waiting counted against the call's `timeout` so a queued call still fails on time. Must not break: the CLI session ids (one `--resume` per session at a time is already the caller's rule).
- Effort / risk: S effort; low risk

### dash-mounts-5 - The SDK path builds a new Anthropic client (and connection pool) for every call and never closes it
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards_ai.py:445 (`_sdk`) and 501 (`model_ids`)
- What: `anthropic.Anthropic(api_key=key)` is constructed per call and dropped, so every Cards AI call on the API path opens a new TCP+TLS connection and leaves an httpx pool for the garbage collector to close.
- Cost / failure scenario: A translation run is one call per chunk (hundreds per episode, estimated) at TX_PARALLEL=3; each pays a fresh handshake (estimated 100-300 ms over the NAS's uplink) that a kept-alive client would not, and the sockets linger until GC. Small next to an LLM call, but free to remove.
- Evidence: Read as cited.
- Ledger: new
- Suggested change: Cache one client per key (module level, rebuilt when the key changes) and close it in the lifespan's shutdown. Must not break: a key rotated in Settings must take effect on the next call.
- Effort / risk: S effort; low risk

### dash-mounts-6 - A stop that lands between Popen and `self._proc = proc` leaves the new editor's child running and unflushed
- Category: resilience
- Severity: low
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/cards_edit.py:303-319 (`stop` reads `self._proc` once) and 354-397 (`_run`: Popen at 354, `self._proc = proc` at 368, then `if self._stop.is_set(): return  # stop() terminates the child`)
- What: `stop()` sets the flag and then reads `self._proc`. If the supervisor thread is between `Popen` returning and line 368 (a start or restart in progress at shutdown, for example inside a crash loop's restart), `stop()` sees no process, and `_run` then sees the flag and returns trusting `stop()` to terminate a child it never saw.
- Cost / failure scenario: The Node editor (`--write`, the live vault) keeps running after the dashboard has stopped, its SIGTERM flush of open cut lists never runs, and a dashboard restarted in the same container (dev reload, an in-process restart) starts a second child against the same vault. Narrow window, so rare; the cost when it hits is two writers on cut lists.
- Evidence: Read as cited.
- Ledger: new
- Suggested change: In `_run`, when the inner loop exits because `_stop` is set, terminate and wait for `proc` itself if it is still alive (idempotent with `stop()`), or publish `self._proc` under `_lock` before Popen returns control to anyone and have `stop()` read it under the same lock.
- Effort / risk: S effort; low risk

## What is already good
- The fleet job scheduler is cheap where it runs hottest: `offers_for_machine` reads the fleet lazily and once, `queued_jobs` is LIMIT 200 on `ix_jobs_state_kind`, and the ranking path measured 3 / 11 / 28 ms per report at 5 / 20 / 50 machines with 200 fresh jobs (probe_rank.py). Finished jobs are pruned (`db.prune_jobs`). Leave it.
- cards_catalog's size walker is one background thread, one episode at a time, capped at 400,000 entries, refreshed at most every 12 h, and keeps the last good number on failure; `note_opened` is throttled per (person, episode). The landing scan is cached 30 s and the page's poll pauses while hidden.
- cards_tunnel's no-engine hold and the engine pool's lazy expiry are lock-bounded dict reads with no per-call I/O; the pool's per-editor maps are bounded by the number of editors and cleared on drop/stop.
- The /cards/edit supervisor drains the child's stdout on its own thread (no 64 KB pipe stall), backs off exponentially to 60 s then 300 s in a crash loop, confirms its own child holds the port, and strips every client `X-TC-*` and the dashboard's cookies before proxying; the WebSocket relay cancels both directions on either side's close.
- The sorter gate waits for the engine on an asyncio event, not a threadpool worker, and the ledger chunk route bounds the gzip inflation as it decompresses.

## Coverage note
Not read in depth: music.py and ytdl.py beyond their gates, broll.py's mount and health half, cards_landing's PWA/service-worker half, cards_ai's session store and model-learning half (its unpruned sessions are bug-dash-jobs-cards-5), jobs.py `explain` (the `why` page) was not probed. Known and not re-reported: the 25 s Cards long poll holding a shared threadpool worker (bug-dash-jobs-cards-3, open), closing an episode leaking its engine threads (bug-dash-jobs-cards-4 / res-time-scale-7; `ProjectAgentEngine.stop` still does not reach `LibraryEngine.stop`), engine open running seconds of Python in-process (prac-perf-7), pinned-vs-abandoned depending on an open episode (bug-dash-jobs-cards-6).

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/app.py login_gate + auth._resolve_session: the session is validated with SQLite synchronously on the event loop for every request, the same GIL-wait amplification measured in dash-mounts-2 (1 ms quiet, tens of ms beside a busy thread), on every request the dashboard serves.
- broll/web and music/web (Starlette `FileResponse` behind the same middleware stack): media ranges also run to EOF after the browser goes (same mechanism as dash-mounts-1); files there are smaller (previews, tracks), so the cost is lower, and the dash-mounts-1 wrapper would cover them if applied at the mount.
