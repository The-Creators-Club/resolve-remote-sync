# Verifier med-06 (2026-09-25)

Judged against HEAD (63d4290) with `git show`, and a `git archive HEAD dashboard`
extract in the session scratchpad for the one reproduction that needed the full
stack. Nothing in the repo was edited except this file.

## bug-dash-auth-2 - session touch blocks the event loop up to 20 s

- Verdict: CONFIRMED
- Severity: medium
- Reason: `SessionStore.validate` (sessions.py) does the once-a-minute
  `UPDATE auth_sessions SET last_seen` through `_connect()`, which opens with
  `db.BUSY_TIMEOUT_BACKGROUND_MS` (20 s) on purpose (its own comment: waiting
  beat the 500). It is called synchronously from `auth._resolve_session` ->
  `get_session_user`, and `login_gate` (app.py:1253) and `csrf_gate` (app.py:1071)
  are `async def` middlewares that call it inline, so on the single-worker
  container that wait happens on the event loop. Any write-lock holder therefore
  stalls every request for as long as it holds the lock, up to 20 s, and then
  the `OperationalError` propagates (the CR-282F handler turns it into a 503,
  not a 500, but a valid session is still refused). CR-282F fixed the same
  shape in the error handler only; this is a different door.
- Evidence: read sessions.py `_connect`/`validate`/`_write_lock`, app.py
  login_gate/csrf_gate, KNOWN_BUGS CR-282F. No earlier ledger entry for the
  touch.

## bug-dash-auth-3 - [ UNDO ] empties template_folders and shared_asset_folders

- Verdict: CONFIRMED
- Severity: medium
- Reason: `_settings_fallback` returns "" for both csv keys, `diff_against_current`
  records that "" as `from`, and the undo route replays the `before` values
  through `set_many`, which upserts an explicit "" row. `resolved_manifest`
  then sees the key present and resolves an empty list instead of provision's
  defaults. Applies to any site whose rows were never seeded (a fresh appliance
  with no DASH_SITE_* env; `seed_from_env_once` writes them only when env is
  set).
- Evidence: probe (dashboard venv, temp DB, `db.migrate`): before 8 template
  folders / `['Assets/Luts','Assets/Stills']`; diff `from: ''`; after restoring
  the diff's `from` values, `[] []`.

## bug-dash-auth-4 - all-non-ASCII shared asset folder 500s the manifest

- Verdict: CONFIRMED
- Severity: medium
- Reason: `validate_many` accepts `Assets/Luts,音效`, and every later
  `resolved_manifest` goes through `provision.shared_asset_folders_for` ->
  `slugify`, which raises ValueError. `api_site` calls `resolved_manifest` with
  no fallback, so the open manifest every installer, wizard and companion reads
  500s, and `site_store.template_folders` (project creation) with it. A studio
  that names folders in Chinese is exactly this fleet. Recoverable only by an
  admin rewriting the row, hence medium not high.
- Evidence: probe: `validate_many` returned the value unchanged; `set_many` +
  `resolved_manifest` raised `ValueError slugify('音效') produced an empty slug`.
  Read api.py `api_site` (HEAD:1699).

## bug-dash-cards-jobs-1 - `//api/root` walks past CardsGate

- Verdict: CONFIRMED
- Severity: medium
- Reason: `CardsDispatch._child` sets `path = "/" + tail`, so
  `/cards/p/<slug>//api/root` hands the gate `//api/root`, which neither
  `BLOCKED_PATHS.get(path.rstrip("/"))` nor any `sub_paths` candidate matches.
  a2wsgi keeps `//api/root` as PATH_INFO, and CPython 3.12's
  `BaseHTTPRequestHandler.parse_request` (gh-87389, present in the venv's
  3.12.10 and the image's 3.12.7) collapses the leading `//`, so the handler
  dispatches `/api/root`. Reproduced end to end on the HEAD code; `//api/restart`
  reaches the handler too. Needs a signed-in session and an Origin that passes
  CSRF, so medium is right.
- Evidence: scratch test built on HEAD's `test_cards_pool` fixtures (real
  create_app, CardsDispatch, CardsGate, cards_wsgi, fake handler):
  `/api/root 200 {"error": "this Timeline Cards has one engine per episode..."}`,
  `//api/root 200 {"ok": true, "path": "/api/root"}`, `//api/restart 200
  {"ok": true}`, engine.posts `[('/api/root', ...)]`, restarted True.

## bug-dash-cards-jobs-2 - agent routing follows the editor's last request

- Verdict: CONFIRMED
- Severity: medium
- Reason: `EnginePool.note_visit` overwrites the single `_where[editor]` slot
  on every dispatched request (`CardsDispatch._note`, media included), and
  `cards_tunnel._routed` -> `local_engine` -> `engine_for` resolves each of
  `/state`, `/pending`, `/result` independently. With one account on two
  episodes (the pool docstring's own "everyday pair"), a pending taken from
  engine A can have its result routed to engine B, which refuses the id, and A
  then reports the applied edit as lost. The routing flip is certain from the
  code; how often it bites depends on two pages being open with the agent
  running.
- Evidence: read cards_pool.py `note_visit`/`engine_for`, cards_tunnel.py
  `_routed`/`local_engine`, cards.py `_note`; the pool docstring's "one account
  on a laptop and a phone ... two different episodes".

## bug-dash-cards-jobs-3 - pinned jobs wait with no alert while no episode is open

- Verdict: DOWNGRADE
- Severity: low
- Reason: The mechanism holds: `PinnedExecutor.tick` returns at once while
  `pool.any_engine()` is None, and DDIAG-6's three branches are all silent for
  mounted + running + unclaimed rows. But the jobs are delayed, not lost: the
  pool has no automatic idle release, so engines disappear only by an explicit
  close or a restart, and the drain resumes the moment ANY episode is opened
  (any engine runs any pinned job). The outputs (proxy-480p, audio-extract,
  peaks) are consumed by Timeline Cards pages, which exist only while an
  episode is open, so the wait ends exactly when someone needs the file. "Wait
  for ever" and the transient `why` answer are therefore mostly true, and the
  cost is a jobs page that says "in hand" for a job that is idle.
- Evidence: read cards_exec.py `tick`, alerts.py `_check_jobs_pinned_no_executor`,
  db.py `release_pinned_jobs`, app.py boot start (res-fleet-1), cards_pool.py
  (no idle release; `drop` is the only close).

## bug-dash-cards-jobs-4 - b-roll/music gates ignore previous session secrets

- Verdict: CONFIRMED
- Severity: medium
- Reason: `BrollGate._identified_scope` and `MusicGate._identified_scope` call
  `auth.read_session_cookie(self._secret, cookie)` with no `previous=`, while
  `_resolve_session` (login_gate) accepts `previous_session_secrets` (DASH-2).
  Nothing re-mints the cookie on request (`make_session_cookie` is called only
  at sign-in), and sessions live up to 7 days, so for the whole drain window a
  pre-rotation browser passes the login gate and reaches /broll and /music with
  no identity header, and the header-gated routes 401. The ytdl gate has the
  same shape (hunter's out-of-territory note).
- Evidence: read broll.py and music.py `_identified_scope`, auth.py
  `read_session_cookie`/`_resolve_session`/`previous_session_secrets`, grep of
  `make_session_cookie`/`set_cookie` (sign-in only). sessions.py
  DEFAULT_ABSOLUTE_SECONDS = 7 days.

## Duplicates

None within this group. cards-jobs-4 and the ytdl variant in the hunter's
out-of-territory list are one defect in three gates.
