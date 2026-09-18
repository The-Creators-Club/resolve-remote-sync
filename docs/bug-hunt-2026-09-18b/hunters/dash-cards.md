# dash-cards - the Timeline Cards mount, the engine pool, the tunnel and the kill switch

Files read (with approximate coverage):
- `git diff` over every file in the territory, hunk by hunk, against the ledger
  comments each hunk cites (dash-cards-1..-9, security-2/-3, res-fleet-1, wire-3).
- `dashboard/src/ccsync_dashboard/cards.py` (100% of the diff; `data_dir_for`,
  `CardsDispatch`, `mount_cards`, `_relative_path`, `build_engine`/`WSGIMiddleware` wrap)
- `dashboard/src/ccsync_dashboard/cards_pool.py` (100%: slug/root_key, `Entry`,
  `open`, `may_close`, `_full_sentence`, `_run_build`, `drop`, `stop_all`, `_evict`)
- `dashboard/src/ccsync_dashboard/cards_landing.py` (100%: `_state`, `cards_open`,
  `cards_close`, `remember`, `KILL_SW`)
- `dashboard/src/ccsync_dashboard/cards_tunnel.py` (`_routed`, `_no_engine`,
  `_wait_for_an_engine`, all three `/agent/*` routes, `_forward`, `_clean`)
- `dashboard/src/ccsync_dashboard/cards_exec.py` (`_RUNNING`/`is_running`,
  `engine` property, `available`, `why_not`, `start`/`stop`/`_loop`/`tick`)
- `dashboard/templates/cards_landing.html`, `dashboard/src/ccsync_dashboard/cards_wsgi.py` (read, unchanged)
- `companion/src/ccsync_companion/timeline_cards_role.py` - the tunnel's other
  end only (`call`, `_note_answer`, `_note_call`, `_note_traffic`, `health`)
- cross-repo, read to check what the mount assumes:
  `E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\cards\page\sw.js`,
  `page.py` (`render_sw`, `page_version`), `agent.py`
  (`agent_state`, `agent_pending`, `agent_result`, `agent_job`, `pull_loop`)
- `dashboard/src/ccsync_dashboard/app.py` (csrf_gate, `_origin_mismatch`, the
  CSRF exempt tables, the pinned-executor boot gate), `auth.py`
  (`cookie_secure`, `CSRF_FIELD`, `is_admin`), `alerts.py` `_check_pinned_*`
- tests: `dashboard/tests/test_cards_pool.py`, `test_cards_mount.py`,
  `test_cards_tunnel.py`, `test_bug_hunt_2026_09_18_dashboard.py` (the
  dash-cards-1 half), `companion/tests/test_bug_hunt_2026_09_18_companion_media.py`
  (the wire-3 half)

Tests run: `dashboard/.venv/Scripts/python.exe -m pytest tests/test_cards_pool.py
tests/test_cards_mount.py tests/test_cards_tunnel.py -q` -> 99 passed.

## Findings

### dash-cards-1 - the kill switch deletes the NEW per-episode page's shell cache too
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_landing.py:239` (KILL_SW, the
  `activate` handler), against
  `E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\cards\page\sw.js:37`
- What: dash-cards-4 narrowed the sweep from every cache to
  `k.indexOf('cards-shell-') === 0`. But the real worker's shell cache is named
  `'cards-shell-' + VER` where `VER` is the page bundle's own hash
  (`page.render_sw()` substitutes `%VER%` from `page_version()`), and
  CacheStorage is per ORIGIN, not per worker scope - the exact fact the fix's
  own comment cites. So the flat page and every `/cards/p/<slug>/` page share
  ONE cache name, and the kill switch deletes the cache the live project
  worker is using, not just the dead flat one. The project worker's `install`
  (which is what fills it) only re-runs when its own bytes change, so nothing
  refills it.
- Failure scenario: a phone has `/cards/p/civil-defence-ab12cd34/` installed;
  its worker has cached `./`, the manifest and the icon under
  `cards-shell-<VER>`. The editor opens `/cards/` (the landing page, in the
  older registration's scope); the browser soft-updates that registration from
  `/cards/sw.js`, the kill switch installs with `skipWaiting`, activates,
  deletes `cards-shell-<VER>` and unregisters. The project registration is
  untouched and never re-installs. The editor goes to set with no signal, taps
  the installed app, and the navigation has nothing to serve - the one thing
  `sw.js`'s own header says the worker exists for ("opening the installed app
  with no network at all"). The neighbouring `15-offline.js` IndexedDB state
  survives, so it reads as "the app is broken" rather than "the download is
  gone".
- Evidence: `sw.js:37` `const SHELL = 'cards-shell-' + VER;` and `sw.js:77`
  `names.filter((n) => n.indexOf('cards-shell-') === 0 && n !== SHELL)` - the
  real worker prunes with an `n !== SHELL` guard precisely because the names
  collide across pages; the kill switch has no such guard. `page.py:164-171`
  `render_sw()` bakes one `page_version()` per checkout, so every engine in the
  container serves the same `VER`. `test_the_kill_switch_leaves_the_dashboards_own_caches_alone`
  asserts only that `cards-shell-` appears and that the unfiltered sweep is
  gone; it cannot see this, because it never names the CURRENT shell.
- Ledger: `CR-285` (dashboard ledger) does not fully fix dash-cards-4 - it
  fixes the dashboard-PWA and `cards-media` halves and opens this one.
- Suggested fix: the kill switch should delete NO caches at all.
  `registration.unregister()` plus the client reload is the whole act, and the
  per-project worker's own `activate` already prunes stale `cards-shell-*`. If
  a delete is wanted, it must exclude the current version, which this worker
  cannot know - which is the argument for deleting none.

### dash-cards-2 - the no-engine hold parks one threadpool worker (and one DB connection) per idle agent, uncapped
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/cards_tunnel.py:178-207`
  (`_wait_for_an_engine`) and `:417-421` (its call in `cards_agent_pending`)
- What: the fix is right about the disease (the companion's `pull_loop` has no
  sleep on a 200 - confirmed at `multicam_pipeline/cards/agent.py:2092-2105` -
  so an immediate answer is a request-rate loop) but the cure has no ceiling.
  `cards_agent_pending` is a blocking `def` route, so the 25 s `time.sleep`
  poll occupies one anyio worker thread for its whole duration, plus the
  `Depends(get_conn)` connection it is holding. Nothing bounds how many agents
  may be in that state at once: it is EVERY machine with `cards_agent` on,
  permanently, from container boot until somebody opens an episode. anyio's
  default thread limiter is 40 and nothing in the tree raises it (no
  `CapacityLimiter` / `total_tokens` anywhere under `dashboard/`), and
  `deploy/run.sh:513,528` runs uvicorn `--workers 1`.
- Failure scenario: a customer fleet of 40+ editors with the cards role on and
  nobody in an episode (the ordinary state after every container restart). All
  40 threadpool tokens are held by sleeping `_wait_for_an_engine` calls; every
  other blocking `def` route on the dashboard - the fleet page, `/api/v1/report`
  - queues behind them. The dashboard that "tells everyone whether their
  footage is syncing" goes unresponsive, and nothing in the logs says why:
  the agents look healthy on both sides.
- Evidence: read `_wait_for_an_engine` (a `_sleep` loop, no shared waiter, no
  counter); `grep -rn "total_tokens|CapacityLimiter" dashboard/` -> nothing;
  `dashboard/deploy/run.sh:513` `--workers 1`. Today's fleet is four machines
  and `cards_agent` is off in the vendor build, which is why this is a ceiling
  rather than an outage - marked PLAUSIBLE because I did not measure a
  saturated limiter.
- Ledger: `CR-285` does not fully fix dash-cards-1 - it closes the hot loop and
  opens a thread-occupancy ceiling.
- Suggested fix: wake on an event instead of sleeping, and cap the waiters. A
  single `threading.Condition` on the pool, notified by `EnginePool.note_visit`
  / `_run_build`'s READY transition, lets all waiters share one wakeup; a
  module-level counter that falls back to the old immediate answer past N
  concurrent holds keeps the threadpool from ever being the thing that fails.

### dash-cards-3 - an ordinary `agent_result` race is reported to the editor as "the dashboard is discarding this computer's pushes"
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/timeline_cards_role.py:939-968`
  (`_note_answer`), read against
  `E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\cards\agent.py:1206-1212`
- What: `_note_answer` treats ANY 200 carrying a non-empty `error` or `note`
  string as "this push was discarded". Two attached, healthy answers match it.
  `AgentLink.agent_result` answers `{"ok": False, "error": "that request is no
  longer open"}` when the edit id has already been timed out by `tick()` - a
  routine race with an engine that is very much attached. And
  `handler.py`/`_local`'s contract (cited in `cards_tunnel._local`'s own
  docstring) wraps an upstream exception as `{"error": str(exc)}` with a 200,
  so any engine-side failure reads as "not attached" too. The consequence is
  not just a log line: `health()` (`:1037-1045`) returns that sentence as the
  role's DETAIL, which is what the tray line and the fleet grid show, and the
  call skips `_note_traffic`.
- Failure scenario: an editor's edit is applied a moment after the server timed
  the request out. The tray and the fleet grid change from "serving timeline
  E1" to "that request is no longer open" and stay there until the next clean
  call, telling the editor their agent is detached when it is attached and
  working. The reverse of the bug wire-3 was written to fix.
- Evidence: `agent.py:1206-1212` is the only non-`ok` answer on the agent
  routes and it is a race, not a refusal; `agent_state` never returns
  `error`/`note` (checked every `return` in `agent_state`/`_agent_publish`),
  and no `agent_job` request dict carries either key, so `pending` is clean.
  `test_a_push_the_dashboard_threw_away_is_not_reported_as_serving` only
  exercises the intended sentence, so it cannot see this.
- Ledger: `CR-284L` does not fully fix wire-3 (= dash-cards-8).
- Suggested fix: key on a field the TUNNEL owns rather than on any `error`.
  Have `cards_tunnel._no_engine()` add `"attached": False` (optional on read,
  ignored by an older companion, harmless to an older dashboard because the
  companion falls back to today's behaviour when the key is absent), and let
  `_note_answer` fire on that key alone.

### dash-cards-4 - `cards_exec.is_running()` answers from a module flag, not from the thread
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_exec.py:118-139`, read by
  `dashboard/src/ccsync_dashboard/alerts.py:2657-2668`
- What: res-fleet-1 added a `notices` check for "pinned rows and no drain
  thread", and made its evidence a module-level `threading.Event` set in
  `start()` and cleared in `stop()`. It is never reconciled with
  `self._thread.is_alive()`. It is also process-global while `PinnedExecutor`
  is an instance, so a second executor in one process (the suite builds
  several) makes the flag mean whichever one moved last, and `stop()` clears
  it even on the path where the join timed out and the thread is deliberately
  kept alive.
- Failure scenario: `_loop` exits abnormally (a `MemoryError`, or a `stop()`
  whose 5 s join timed out and whose thread then really ends). `_RUNNING` stays
  as it was, `is_running()` answers True, and the alert that exists precisely
  to catch "pinned into a queue nothing drains" stays silent. That is the
  "green while dead" shape the check was added against.
- Evidence: `_note_running` is called only from `start()` (after
  `thread.start()`) and `stop()` (before the join); `_loop`'s `finally` does
  not clear it; `is_running()` is `_RUNNING.is_set()` with no thread check.
- Ledger: `CR-285` does not fully fix res-fleet-1.
- Suggested fix: keep the module-level handle to the EXECUTOR (not a bool) and
  let `is_running()` answer `exc._thread is not None and exc._thread.is_alive()`;
  clear the handle in `_loop`'s `finally`.

### dash-cards-5 - the landing page's forms name the CSRF field `csrf_token`; `auth.CSRF_FIELD` is `csrf`
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/templates/cards_landing.html:85,92` vs
  `dashboard/src/ccsync_dashboard/auth.py:695` and
  `dashboard/src/ccsync_dashboard/app.py:1038-1053` (`_csrf_from_form`)
- What: every other template in the tree posts `name="csrf"` (topbar,
  admin_assignments, android_settings). These two post `name="csrf_token"`, so
  `_csrf_from_form` would find nothing. It is inert only because
  `_CSRF_ORIGIN_ONLY_PREFIXES = ("/cards/",)` (app.py:250) downgrades
  everything under `/cards/` to an Origin check. security-2 widened
  `/cards/close` from admin-only to every session in this pass, which puts one
  more state-changing route on that carve-out, and app.py:248 states the
  carve-out is meant to be deleted ("when the page starts sending
  X-CSRF-Token this constant is deleted and `/cards/` becomes an ordinary
  session route") - at which moment both [ OPEN ] and [ CLOSE ] 403 with
  "missing or bad CSRF token".
- Failure scenario: a later change removes the `/cards/` origin-only
  carve-out; the landing page's two buttons stop working for everybody, with a
  403 whose text sends the editor to reload the page, which does not help.
- Evidence: `grep -rn 'name="csrf' dashboard/templates/` - `cards_landing.html`
  is the only file using `csrf_token`. `_csrf_from_form` reads
  `parsed.get(auth.CSRF_FIELD)` and `CSRF_FIELD = "csrf"`.
- Ledger: new (pre-existing in the template, but security-2 added a second
  session-writable route behind it this pass).
- Suggested fix: rename both hidden inputs to `name="csrf"`. One-line, and it
  makes the carve-out removable.

### dash-cards-6 - a mid-build episode is closable by anyone the moment its opener's 15 minutes lapse
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/cards_pool.py:405-425` (`may_close`)
- What: `may_close` decides on `occupants()` only, and never on `state`. A
  LOADING entry whose build is slow (the case `RETRY_FLOOR_SECONDS` exists for:
  "a share that hangs before it refuses") has occupants only for
  `ACTIVE_SECONDS` after the `note_visit` in `cards_open`. Past 15 minutes of
  building, `occupants()` is empty and `may_close` returns "" for every signed-in
  session, so a bystander's [ CLOSE ] drops an episode somebody is waiting on.
  `_run_build` then finds it orphaned and stops the half-built engine.
- Failure scenario: an editor presses [ OPEN ] on an episode whose NAS share is
  slow; it builds for 20 minutes; a second editor, wanting a seat, sees
  "opening / nobody in the last 15 min" and closes it. The first editor's page
  is still polling `state.json` and simply loses the episode with no sentence.
- Evidence: `cards_open` is the only `note_visit` for a LOADING entry (the
  dispatcher's `_note` only fires once the entry is READY, since
  `ready_asgi` gates it); `Entry.occupants` filters on `ACTIVE_SECONDS`.
- Ledger: new (opened by security-2).
- Suggested fix: in `may_close`, treat `state == LOADING` as occupied by
  whoever opened it - record the opener on the `Entry` at `open()` time and let
  only them or an admin close it while it is still building.

## Coverage note
- I did not exercise the kill switch or the per-project worker in a browser;
  finding dash-cards-1 is read from the two workers' source and the shared
  `page_version()`, not observed. Nothing in either repo's suite tests a
  service worker.
- dash-cards-2 is unmeasured: I did not saturate anyio's limiter. The suite has
  no test for concurrent `/cards/agent/pending` holds at all, and
  `test_bug_hunt_2026_09_18_dashboard.py` stubs `cards_tunnel._sleep`, which is
  exactly what a thread-occupancy test cannot do.
- The companion-side fixture in
  `companion/tests/test_bug_hunt_2026_09_18_companion_media.py:382`
  builds the role with `__new__` and hand-sets `_not_attached`, so it would
  pass even if `TimelineCardsRole.__init__` did not initialise the field
  (it does). Flagged for the `tests` lens, not counted as a finding.
- I did not review `cards_ai.py` or `cards_wsgi.py` in depth (neither is in
  the diff), nor `static/sw.js`'s serving half (dash-mounts-ui owns it); I read
  only its kill-switch semantics.
- I did not attempt the full engine-pool lifecycle under real concurrency
  (`drop()` racing an in-flight `/cards/p/<slug>/` request through the evicted
  executor); the `wait=False` shutdown looked correct on paper.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/app.py:250`: `_CSRF_ORIGIN_ONLY_PREFIXES =
  ("/cards/",)` now also covers `/cards/close`, which security-2 turned from an
  admin route into a route every session can drive. Origin-only is still the
  documented contract, but the set of things behind it grew this pass.
- `companion/src/ccsync_companion/timeline_cards_role.py:964`: the new
  `log.warning` embeds the dashboard's `_no_engine()` sentence, which contains a
  double hyphen; it reaches `health()`'s detail and so the tray and the fleet
  grid. Not an em dash, so not the owner's rule, but it is server-composed copy
  arriving in tray text with no scan test over it (comp-resolve / comp-ui).
