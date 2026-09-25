# bug-dash-cards-jobs - the dashboard's Timeline Cards mount (pool, landing, dispatch, gate, WSGI shim, tunnel, AI runner, pinned executor), the job scheduler, and the /broll and /music mount gates

Files read (approximate coverage): dashboard/src/ccsync_dashboard/cards.py (all), cards_pool.py (all), cards_landing.py (all), cards_tunnel.py (all), cards_wsgi.py (all), cards_exec.py (all), cards_ai.py (all), jobs.py (all), broll.py (all), music.py (gate + mount + storage, ~85%). Callees followed: auth.py (`_resolve_session`, `read_session_cookie`, `is_admin`), app.py (CSRF origin gate, executor boot, mount order), alerts.py `_check_jobs_pinned_no_executor`, db.py pinned-job helpers and cooldown, api.py job routes; the other repo's `handler.py`, `agent.py` (`agent_pending` / `agent_result` / `check_token`), `server.restart_server`, `library_engine.montage_open` / `_run_claude_json`, a2wsgi `build_environ`, CPython 3.12 `BaseHTTPRequestHandler.parse_request`.

Tests/probes run (dashboard venv, scratch scripts in %TEMP%, nothing in the repo):
- a real `CardsDispatch` + `CardsGate` + `cards_wsgi` + a2wsgi stack in front of a stub `BaseHTTPRequestHandler`, driven by Starlette's TestClient (finding 1);
- `EnginePool` with two open episodes and one account's two devices polling (finding 2);
- `auth.read_session_cookie` vs the login gate's `_read_token_any` on a cookie signed with a retired secret (finding 4).

## Findings

### bug-dash-cards-jobs-1 - A double slash walks past CardsGate: `/cards/p/<slug>//api/root` reaches `engine.set_root()`
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards.py:425 (`CardsGate.__call__`, `BLOCKED_PATHS.get(path.rstrip("/"))`), with cards.py:575 (`_child` builds `"/" + tail`)
- What: the gate compares the child path to `/api/root` and `/api/restart` literally, but the handler behind it is a `BaseHTTPRequestHandler`, whose `parse_request` (CPython gh-87389, present in the shipped 3.12) collapses a leading `//` to `/` before `urlparse`. So `/cards/p/<slug>//api/root` gives the gate `//api/root` (not blocked) and the handler `/api/root` (dispatched). The trailing-slash variant was closed as dash-release-jobs-4; this is the leading-slash sibling of the same gap.
- Failure scenario: any signed-in session POSTs `{"root": "<episode B>"}` to `/cards/p/<slug-of-A>//api/root`. Engine A (data dir `<data>/cards/<slug-A>`) moves onto episode B, which may already have its own engine: the pool's key is now a lie (URL A serves B), two engines write one episode's files from two state directories, and the agent tunnel routes by the wrong slug. `//api/restart` also reaches `restart_server`: on the NAS it dies on the read-only `/cards-app` log open or on `creationflags` under Linux, but on a Windows dev run (CARDS_SRC) it Popen-s a copy of the dashboard's argv and calls `os._exit(0)`.
- Evidence: probe output, same stack as production (CardsDispatch -> CardsGate -> a2wsgi -> cards_wsgi -> handler): `'api/root' 200 {"error": "this Timeline Cards has one engine per episode..."}`, `'//api/root' 200 {"reached": "/api/root"}`, `'//api/restart' 200 {"reached": "/api/restart"}`.
- Ledger: new (a sibling of dash-release-jobs-4, bug-hunt-2026-09-03)
- Suggested fix: normalise before matching. Collapse runs of `/` (`re.sub(r"/{2,}", "/", path)`) in `CardsGate` and in the dispatcher's AGENT_PREFIX check, or have `_child` refuse or redirect any tail that begins with `/`. A test should also cover `//api/root` and `/./api/root`.

### bug-dash-cards-jobs-2 - An agent's traffic follows whichever of its editor's devices made the LAST request, so pending and result land on different engines
- Severity: medium
- Confidence: CONFIRMED (the routing flip); PLAUSIBLE (how often it bites in practice depends on two open pages)
- Where: dashboard/src/ccsync_dashboard/cards_pool.py:347 (`note_visit` overwrites `_where[editor]` on every served request) and :324 (`engine_for`), used by cards_tunnel.py:173 (`_routed`) on each of `/state`, `/pending`, `/result` independently
- What: `_where` is one slot per editor, overwritten by every request the dispatcher serves (`CardsDispatch._note`: page polls, media ranges, state fetches). The design's own headline case, one account with a laptop in episode A and a phone in episode B (cards_pool.py docstring, "the everyday pair"), makes that slot flip several times a second. Each of the agent's three calls is routed on its own, so a long poll can take an edit from engine A and the matching `/agent/result` can be routed to engine B.
- Failure scenario: laptop open on Repro Rights, phone open on Framing Formosa, both on alex's account, alex's companion running the Cards role. The agent's `/pending` goes to engine A and receives edit #12 (A: `_req`=#12, `busy`=True). Resolve applies it. `/result` is routed to engine B, which answers `{"ok": false, "error": "that request is no longer open"}`. On the agent's next poll to A, `agent_pending` sees `_req` still set and publishes "the Resolve agent went away with that edit - it was never confirmed" for an edit Resolve DID apply, and the editor presses it again (a double edit). State pushes also alternate between the two engines, each re-mirroring the other's timeline.
- Evidence: probe: two READY engines, `note_visit` alternating between A and B for "alex" as two polling pages would; `engine_for("alex")` answered A, B, A, B, A, B on consecutive calls. `agent.py:1144-1224`: `agent_pending` moves `_pending` into `_req`, and a poll that finds `_req` set declares it lost; `agent_result` refuses any id that is not its own `_req`.
- Ledger: new (docs/CARDS_TWO_PROJECTS.md "Not proved: two people / no agent was connected")
- Suggested fix: pin the agent to one engine. Record where an agent's `/pending` handed out an edit (by request id) and route `/result` there. Update `_where` from navigations and page-state polls only, never from media and asset requests. Better still, let the agent's own state push name the Resolve project it is sweeping, and route on that.

### bug-dash-cards-jobs-3 - Pinned jobs wait for ever, with no alert, whenever no episode happens to be open
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards_exec.py:283 (`tick` returns at once when `available()` is false); alerts.py:2755-2808 (`_check_jobs_pinned_no_executor`); jobs.py:411 (REASON_PINNED is TRANSIENT)
- What: after CR-282G the drain thread runs whenever Cards is mounted, but it can only work while `pool.any_engine()` returns an engine, which is only while somebody has an episode open. A job pinned while an episode was open (`can_pin` true), followed by that episode being closed or the container restarting (the pool starts empty, and `release_pinned_jobs` puts rows back in the queue), sits in `pinned` with no worker. DDIAG-6 covers three shapes: mount not mounted, executor thread not running, and a row in hand with a stale heartbeat. This is a fourth: mounted, thread running, `claimed_machine` empty, no engine. It fires none of them.
- Failure scenario: an editor has Framing Formosa open. A `proxy-480p` job spends its fleet budget and goes `pinned`. The editor closes the episode (or an image update restarts the container overnight). The job never runs. PROBLEMS THE SERVER FOUND stays empty. `GET /jobs/<id>/why` answers `reason_code: pinned, transient: true`, so Timeline Cards' client keeps waiting instead of making the file itself.
- Evidence: `PinnedExecutor.tick` -> `available()` -> `engine` -> `cards.engine_provider` -> `pool.any_engine()` is None with no READY entry. The alert's `elif cards == "mounted"` branch fires only on `not cards_exec.is_running()`, and its stale branch needs a non-empty `claimed_machine`.
- Ledger: related to CR-282G (fixed; this is the shape that fix left)
- Suggested fix: make `can_pin` require a READY engine, which it already does. Then either (a) have the executor mark pinned rows `abandoned`, with a sentence, after N minutes with no engine, or (b) add the fourth DDIAG-6 shape (pinned rows, mounted, thread running, `pool.any_engine()` None for more than X minutes, published through a module-level flag like `is_running`) and have `explain` answer non-transient while no engine exists.

### bug-dash-cards-jobs-4 - After a session-secret rotation the b-roll and music gates mint no identity, so ingest panels and client folders 401 for every signed-in editor
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/broll.py:232 and music.py:242 (`auth.read_session_cookie(self._secret, ...)`, CURRENT secret only), against auth.py:606 (`_resolve_session` accepts `previous_session_secrets`)
- What: DASH-2 made the login gate accept a browser session signed with any `DASH_SESSION_SECRET_PREVIOUS` key, so that "a rotation must not sign every admin out in the middle of the incident". The two mount gates re-decode the cookie themselves with the new secret alone. Every pre-rotation session therefore passes `login_gate` and reaches the sub-app with NO `X-CCSync-User` / `X-CCSync-Admin`.
- Failure scenario: an admin rotates the secret (the documented drain procedure). Every editor still signed in sees the dashboard, /broll search and /music search working, but the b-roll ingest panel (`/broll/api/ingest-batches`), client folders (`/broll/api/client-folders`) and the music ingest panel answer 401 "not signed in" while the page shows them signed in. Nothing tells them to sign out and back in, and the drain counter on the fleet page counts companions, not browsers.
- Evidence: probe: cookie minted with the old secret. `read_session_cookie(new, c)` -> None, and `_read_token_any(new, (old,), c, PURPOSE_SESSION)` -> 'ruskin'. `grep x-ccsync-user` finds the header read by broll/web/app/routes_batches.py, routes_client_folders.py and music/web/musicweb/routes_batches.py / main.py.
- Ledger: new (related to DASH-2, fixed)
- Suggested fix: read the identity `login_gate` already resolved, `scope["state"]["ccsync_session"][0]`, as `CardsDispatch._note` does. That also honours server-side revocation. At minimum, pass `previous=auth.previous_session_secrets(settings)`.

### bug-dash-cards-jobs-5 - The API-path session trim throws away corpus parts 2..n once a montage or search conversation passes 40 turns
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards_ai.py:1182 (`_trimmed` keeps `messages[:2]` + the last 78)
- What: the docstring says "the first turn is NEVER trimmed - it is the corpus". Since 2026-09-07, however, a corpus too big for one message is sent as one TURN PER PART (`library_engine.montage_open` / `montage.montage_open`: a `run_claude(..., session=...)` per chunk), so parts 2..n are messages 2..2n-1, and those are the first ones the trim drops. Every later turn also moves the kept window, so the prefix after message 1 changes on every call and the "last corpus part" breakpoint never hits again.
- Failure scenario: a four-part episode corpus (the 68k/89k/97k/67k-char case named in decision 7) on a site with an ANTHROPIC_API_KEY. After 36 transcript searches in one afternoon, turn 41 is sent without part 2, turn 42 without parts 2-3, and so on. Searches silently stop finding anything in the interviews those parts held, and every warm turn re-reads the kept history at full price. The CLI door keeps its own history and is not affected.
- Evidence: `_trimmed` slices whole pairs from index 2; `_is_corpus_message` / `_for_send` show that parts are separate stored user messages.
- Ledger: new
- Suggested fix: keep every leading corpus pair (`_is_corpus_message` up to the first non-corpus user turn) and trim only after them, or answer `session_lost` at the cap so the caller re-opens the corpus.

### bug-dash-cards-jobs-6 - `POST /cards/open` walks the vault four levels deep on the event loop
- Severity: low
- Confidence: CONFIRMED (the blocking call); PLAUSIBLE (a stall long enough to notice)
- Where: dashboard/src/ccsync_dashboard/cards_landing.py:199-214 (`async def cards_open` -> `_episodes` -> `cards_pool.episodes`)
- What: `cards_open` is `async def`, and when the 30 s scan cache has lapsed it calls `cards_pool.episodes()`, a recursive `os.scandir` over up to four levels of the vault share, directly on the event loop. `cards_pool`'s own docstring ("BUILDING IS NOT A REQUEST ... doing it inside the ASGI call would hold the event loop") is the rule it breaks. The GET routes are sync `def` and run in the threadpool. The POST is the one that is not.
- Failure scenario: an editor presses [ OPEN ] more than 30 s after the landing page was drawn, for example after reading the list. The whole single-worker dashboard (fleet reports, every page) waits on a scan of `/vault`. On a large or slow share that is seconds. If the vault export hangs, the dashboard hangs with it.
- Evidence: route signature and call chain as cited. `_scan` TTL is `SCAN_TTL_SECONDS = 30.0`.
- Ledger: new
- Suggested fix: make `cards_open` (and `cards_close`, which calls `engine.stop()` on the loop) a plain `def`, or run `_episodes` through `run_in_threadpool`. Parse the form with a sync-safe helper.

## Coverage note
Not traced: `cards_ai`'s concurrent turns on one session id (two searches in flight would each read-modify-write the stored conversation; I did not confirm the other repo lets that happen). The `explain` / `offers_for_machine` ranking with multi-machine fixtures (read, not executed). The landing template (Wave 3's). `cards_wsgi` with chunked request bodies. I read the jobs scheduler fully and found no new defect beyond what earlier hunts fixed.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/ytdl.py:171: same as finding 4. `YtdlGate` decodes the session cookie with the current secret only, so after a rotation the ytdl app gets no identity for pre-rotation sessions.
- E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\cards (library_engine.py:4125, transcript_search.py:1321, montage.py:276, chat_edit.py): every Claude call does `tempfile.mkdtemp()` for its `out` file and nothing removes it, so the container's /tmp grows by one directory per search, describe and chat turn.
- E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\cards\server.py:110 `restart_server` calls `os._exit(0)` on whatever process imported it. It is only reachable in the dashboard through finding 1, and on Linux it fails before the exit.
