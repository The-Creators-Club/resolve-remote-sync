# dash-cards - the Timeline Cards mount, the engine pool, the landing page, the agent tunnel

Files read (with approximate coverage): `dashboard/src/ccsync_dashboard/cards.py` (100%),
`cards_pool.py` (100%), `cards_landing.py` (100%), `cards_tunnel.py` (100%),
`cards_exec.py` (~70%, the engine-provider half in full), `cards_ai.py` (~25%, the
model/provider seam only), `cards_wsgi.py` (skim), `dashboard/templates/cards_landing.html`
(100%), `dashboard/static/sw.js` (the PASS_THROUGH/scope half),
`dashboard/src/ccsync_dashboard/app.py` (`_open_path`, `_OPEN_PATTERN`, `_cards_json_re`,
`login_gate`, the CSRF gate), `auth.py` (the session tuple), `api.py:_require_fleet_caller`,
`docs/CARDS_TWO_PROJECTS.md` (100%), `dashboard/tests/test_cards_pool.py` +
`test_cards_mount.py` + `test_cards_tunnel.py` (read), and, for the other end of the wire
only, `companion/src/ccsync_companion/timeline_cards_role.py` and
`MulticamPipeline/multicam_pipeline/cards/agent.py` (`AgentClient.push_loop` / `pull_loop`).

Tests run: `dashboard\.venv\Scripts\python.exe -m pytest tests/test_cards_pool.py tests/test_cards_mount.py tests/test_cards_tunnel.py -q` -> 91 passed.
Plus one scratch snippet against `cards_pool.EnginePool` from the dashboard venv (below).

## Findings

### dash-cards-1 - an agent whose editor is in no episode long-polls in a hot loop
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_tunnel.py:358-367` (`cards_agent_pending`),
  against `MulticamPipeline/multicam_pipeline/cards/agent.py:2092-2113`
  (`AgentClient.pull_loop`), reached through
  `companion/src/ccsync_companion/timeline_cards_role.py:388` (`_TunnelClient._req`).
- What: phase 1a made `/cards/agent/pending` answer `{"note": ...}` IMMEDIATELY when
  `_routed` finds no engine for that editor, instead of holding the poll for `seconds`.
  `pull_loop` has no sleep of its own on the "nothing for you" path - `if got.get("id") is
  None: continue` goes straight back round - because its entire pacing has always been the
  server's 25 s long poll. An instant empty answer therefore turns the pull loop into a
  request-per-RTT spin.
- Failure scenario: `cards_agent` is on, an editor's companion has the role running (the
  normal state since CR-226), and nobody has opened an episode on `/cards/` yet - which is
  every container restart, and every night. That machine now issues
  `GET /cards/agent/pending?wait=25` continuously, each one a full fleet-credential check
  (`_require_fleet_caller`: a `cce1.` token lookup, an identity-token verify and a
  barred-account query) on the single-worker dashboard, plus an event-loop trip and a
  companion thread spinning. Four machines doing it is a self-inflicted DoS on the thing
  that tells everyone whether their footage is syncing. Before the pool this path raised
  (`_forward` -> 502) and the loop's exponential backoff caught it; the pool turned that
  exception into a 200.
- Evidence: `cards_agent_pending` computes `seconds` and then returns `{"note": ...}`
  before it is ever used; `pull_loop`'s only `time.sleep` calls are in its `except` branch
  and in `_apply_one`. `role.call()` returns the parsed dict and calls
  `_note_call(200, "")`, so nothing on the companion side slows it either.
- Ledger: new (the engine pool, dashboard 0.7.47/0.7.48).
- Suggested fix: honour the poll on the refusal path - wait `seconds` before answering
  `{"note": ...}` - so an agent with no episode is paced exactly as one with an idle
  episode. One side, no companion release needed.

### dash-cards-2 - an episode that failed to build can never be opened again
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_pool.py:329-335` (`EnginePool.open`),
  `dashboard/templates/cards_landing.html:57-89`.
- What: `open()` is idempotent on the SLUG, not on the state: an entry left in `FAILED` by
  the builder thread is returned as-is with an empty refusal, so the build is never
  retried. The landing page renders `[ FAILED ]` and offers the `[ OPEN ]` form (the `else`
  branch), which posts, gets the same failed entry back and redirects to `?want=<slug>`
  with nothing changed; the `[ CLOSE ]` button is inside `{% if ep.state == 'ready' %}`, so
  not even an admin can `drop()` the entry from the UI.
- Failure scenario: the vault share is not yet up (or Postgres is refusing) at the moment
  someone clicks OPEN. That episode is `failed` for the life of the container. Everyone who
  clicks OPEN gets a page that changes nothing and says nothing new. The only cure is
  redeploying the dashboard.
- Evidence: scratch snippet from the dashboard venv, with a build that raises once and
  then succeeds: `after first: failed 'OSError: ...'` / `retry: failed same entry? True
  build calls: 1`. The suite's `test_an_episode_that_will_not_build_holds_no_seat` only
  checks that a DIFFERENT root can still open, never that the failed one can be retried.
- Ledger: new.
- Suggested fix: in `open()`, treat a `FAILED` entry as absent (replace it and start a new
  builder thread); and render `[ CLOSE ]` for `failed` as well as `ready`, so an admin has
  a manual door.

### dash-cards-3 - the cap refusal names a page that does not exist, and an act that frees nothing
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_pool.py:344-349` (`_full_sentence`).
- What: the refusal reads "Ask one of them to leave it, or an admin can close an idle one
  on Settings > Timeline Cards." There is no Settings > Timeline Cards page - a grep over
  `dashboard/templates/*.html` finds `/cards/close` in `cards_landing.html` only - and
  "leaving" an episode releases nothing: a seat is held by the ENTRY, and only `drop()` (or
  a restart) removes one. `occupants()` lapsing after 15 minutes changes the sentence, not
  the cap.
- Failure scenario: a third editor is refused, closes their tab as asked, waits, is refused
  again in the same words, and then goes looking for a Settings page that is not there.
  Exactly the "misleading UI that causes a wrong action" case.
- Evidence: the grep above; `open()` counts `state != FAILED` entries and nothing
  decrements on idleness; `cards_landing.html:74` is the only close control, and it is
  admin-only and `ready`-only (see dash-cards-2).
- Ledger: new.
- Suggested fix: name the real place ("an admin can close one on the Timeline Cards page")
  and drop "ask one of them to leave it", or implement an idle release the sentence can
  honestly promise.

### dash-cards-4 - the /cards/sw.js kill switch deletes every cache on the origin, not just its own
- Severity: medium
- Confidence: CONFIRMED (by the CacheStorage contract; not run in a browser)
- Where: `dashboard/src/ccsync_dashboard/cards_landing.py:210-214` (`KILL_SW`), against
  `dashboard/static/sw.js:19-40` (the dashboard's own `CACHE` / `PRECACHE`).
- What: `for (const k of await caches.keys()) await caches.delete(k)` enumerates the
  ORIGIN's CacheStorage, which every worker on that origin shares. The kill switch
  therefore deletes the dashboard's own `ccsync-<version>` precache (the offline page, the
  stylesheets, `htmx.min.js`, `htmx_errors.js`, the icons) and any cache the NEW
  per-episode worker has already built under `/cards/p/<slug>/`, not only the flat cards
  caches it means to take.
- Failure scenario: a phone with both the dashboard PWA and the old flat cards app
  installed does its periodic worker update. The cards worker unregisters and, on the way
  out, empties the dashboard's precache. The dashboard's own worker is still registered and
  will not re-run `install` until its `__VERSION__` bytes change, so until the next
  dashboard release that phone has no offline page and re-fetches every static asset -
  including `htmx_errors.js`, the one script DUI-2 precached precisely for a bad
  connection.
- Evidence: `caches.keys()` is defined on the origin's CacheStorage; the dashboard worker's
  cache name shares no prefix the kill switch filters on. The suite only asserts
  `unregister()` is present and that there is no fetch handler
  (`test_the_flat_service_worker_is_a_kill_switch`).
- Ledger: new.
- Suggested fix: delete only the caches this worker owns - filter `caches.keys()` on the
  cards page's own cache-name prefix (the other repo's `15-offline.js` names them), or at
  minimum skip any key starting `ccsync-`.

### dash-cards-5 - closing an episode leaks its 24-thread WSGI executor
- Severity: medium
- Confidence: CONFIRMED (by reading a2wsgi in the dashboard venv)
- Where: `dashboard/src/ccsync_dashboard/cards.py:470-478` (`CardsDispatch._gates`) and
  `cards.py:620` (`WSGIMiddleware(wsgi, workers=24)`), with `cards_pool.py:_stop`, which
  clears `entry.asgi` but never touches the middleware.
- What: each engine build wraps the handler in `a2wsgi.WSGIMiddleware(..., workers=24)`,
  which constructs a `ThreadPoolExecutor(max_workers=24)` in its `__init__`
  (`.venv/Lib/site-packages/a2wsgi/wsgi.py:153-159`). `drop()` / `stop_all()` drop the
  pool's reference, but `CardsDispatch._gates[slug] = (asgi, gate)` is never pruned, so the
  middleware and its executor stay reachable for the life of the container, with whatever
  WSGI threads it has already spun up still alive.
- Failure scenario: an admin closes an episode to free a seat and opens another; repeated
  over a week of a long-lived container, the dashboard accumulates one dead 24-worker
  executor per close. This sits directly against §12's own accounting - "the thread count
  is the real price", 5-6 threads per engine - and makes the deliberate close worse than
  the doc says it is.
- Evidence: the a2wsgi source above; `_gates` has no deletion path anywhere in `cards.py`;
  `_stop()` sets `entry.asgi = None` only.
- Ledger: new (the same "started and then dropped" shape as bug-hunt-2026-09-03
  dash-release-jobs-1, one layer up).
- Suggested fix: have `EnginePool.drop` / `stop_all` call back into the dispatcher to evict
  `_gates[slug]`, and `executor.shutdown(wait=False)` on the middleware being discarded.

### dash-cards-6 - the per-slug data dir abandons every engine's existing state, with no migration
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards.py:215-233` (`data_dir_for`).
- What: the engine's `data_dir` moved from `<data>/cards` to `<data>/cards/<slug>` and
  nothing moves the files that are already there. A grep for
  `data_dir_for|cards_mirror|migrate` across `cards*.py` finds no migration step and no
  test.
- Failure scenario: upgrading to dashboard 0.7.47/0.7.48 silently resets, for every
  episode, `cards_mirror.json`, `cards_pick.json`, `cards_lane_keys.json`, `cards_ui.json`,
  the EN-index / translation caches and `library_backups` - the last of which is the safety
  net for the cut list itself, and the translation cache re-earns its cost in API calls.
  Nothing tells the operator; the files simply sit unread one directory up.
- Evidence: the grep; `data_dir_for`'s own docstring lists exactly those files as what
  `<data>/cards` holds. `docs/CARDS_TWO_PROJECTS.md` §11 lists the change and says nothing
  about the existing contents.
- Ledger: new.
- Suggested fix: a one-shot move at first build - if `<data>/cards/<slug>` is empty and
  `<data>/cards` holds the flat files, adopt them for the FIRST episode opened after the
  upgrade; or, safer, leave them and log one line naming both paths, so nobody spends an
  evening looking for the backups.

### dash-cards-7 - the raw build exception is rendered into the landing page
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_pool.py:373-376`
  (`entry.detail = f"{type(exc).__name__}: {exc}"`), rendered at
  `dashboard/templates/cards_landing.html:62`.
- What: whatever `ProjectAgentEngine.__init__` / `start()` raises is shown verbatim to any
  signed-in user. A Postgres failure there carries the DSN (host, database, user); an
  OSError carries container paths.
- Failure scenario: a non-admin editor opens an episode whose Resolve project DB is
  unreachable and reads `OperationalError: connection to server at "192.168.0.102", port
  5432, user "..." failed` off the page. Behind the login, hence low - but this is the one
  place in the dashboard that prints another repo's exception to a browser, while
  `app.py`'s `unhandled_error` deliberately prints nothing derived from an exception.
- Ledger: new.
- Suggested fix: keep the full text in the log and show a short reason plus "the log has
  the detail" on the page, or show it only when `session_is_admin`.

### dash-cards-8 - a discarded agent push reads as a healthy cards role
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_tunnel.py:334-340` (the state route) against
  `companion/src/ccsync_companion/timeline_cards_role.py:912-935` (`call` -> `_note_call`).
- What: `_no_engine` is answered as HTTP 200 (deliberately, on `handler.py`'s contract),
  and the companion's transport treats any 200 as success: `_note_call(200, "")` moves
  `_last_poll_at` and `_note_traffic` records the timeline, so `health()` says the machine
  is serving the page. Upstream, `push_loop` also sets `sent = version` on that answer, so
  the pushed version is not re-sent until the `AGENT_PING_S` heartbeat earns a `resend`.
- Failure scenario: an editor's tray and the fleet grid both show `[ CARDS: E1 v5 ]` while
  every sweep is dropped on the floor because nobody has opened an episode. It self-heals
  on the next ping, so the cost is a misleading health line rather than lost state.
- Ledger: new; the honest-signal half of dash-cards-1.
- Suggested fix: have the companion's `call()` notice an `error` / `note` key in a 200 body
  and surface it as the role's detail ("your dashboard has no episode open for you").

### dash-cards-9 - the failed-episode test cannot fail for the bug it sits next to
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/tests/test_cards_pool.py:186-194`.
- What: `test_an_episode_that_will_not_build_holds_no_seat` proves only that a DIFFERENT
  root can still be opened after one fails. Nothing in the suite re-opens the failed root,
  which is why dash-cards-2 ships green, and nothing asserts the landing page offers an
  admin a way out of `failed`.
- Ledger: new.
- Suggested fix: add "a failed episode can be opened again" and "an admin can close a
  failed episode" to that file.

## Coverage note
`cards_wsgi.py` had a skim only, and its streaming/Range half deserves its own read - it is
the byte-for-byte contract the whole mount rests on. `cards_ai.py` was read only at the
provider/model seam; its prompt building and the three Claude features are not covered
here. I did not exercise a real `multicam_pipeline` checkout: every test above runs against
the fake one in `dashboard/tests`, which is the same gap `docs/CARDS_TWO_PROJECTS.md` §11
calls "what has not been proved". Nothing in the suite covers two DIFFERENT identities
through `cards_tunnel._routed` (§12 says the same), the a2wsgi thread accounting, or a
service worker in a real browser. §5's memory measurement is now in §12, so no finding is
owed there.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/app.py:144-148`: `_open_path` / `_OPEN_PATTERN` carve the
  three PWA surfaces out of `login_gate` with no METHOD check, though every comment beside
  them says "GET only" - `POST /cards/p/<slug>/sw.js` reaches the mounted engine with no
  session. (dash-core / dash-api.)
- `dashboard/static/sw.js:46-56`: `PASS_THROUGH` holds `/cards/` but not the bare `/cards`,
  so the landing redirect is the one cards URL the dashboard worker may answer out of its
  offline cache. (dash-mounts-ui.)
- `companion/src/ccsync_companion/timeline_cards_role.py:912`: the transport treats a 200
  carrying `{"error": ...}` as a clean call (see dash-cards-8). (comp-resolve.)
