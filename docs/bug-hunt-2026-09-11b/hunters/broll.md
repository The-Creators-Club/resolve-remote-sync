# broll - the b-roll web app (`broll/web/app`, `broll/web/static`) and `broll/indexer`

Files read (with approximate coverage):
- `git diff 40f931a..HEAD` over the whole territory, every hunk (100%).
- `broll/web/app/client_folders.py` (schema/migration/backfill/token halves, ~60%),
  `routes_batches.py` (100%), `routes_fleet.py` (100%), `routes_share.py` (100%),
  `ingest_batches.py` (lease/retry/release/cancel paths, ~40%), `main.py` (100%).
- `broll/web/static/ingest.js` (loopback + batch-card + retry/take-over paths, ~25%),
  `static/app.js` `fetchJson` (100%).
- `broll/web/tests/test_bug_hunt_2026_09_11_broll.py` (100%),
  `test_ingest_retry_and_takeover.py` diff (100%).
- `broll/indexer/watchdog.ps1` (100%), indexer path scan for the repo move.
- Both sides of two wires, read outside the territory only to judge a contract:
  `companion/src/ccsync_companion/broll_ingest.py` `run()`,
  `broll_server.py` `/broll/ingest/{run,retry}`,
  `dashboard/src/ccsync_dashboard/app.py` login-gate carve-outs,
  `dashboard/src/ccsync_dashboard/broll.py` `_init_broll_storage`.

Tests run:
`cd broll\web; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_broll.py tests/test_ingest_retry_and_takeover.py tests/test_client_folders.py tests/test_fleet_ingest.py -q`
-> 122 passed. (Every finding below is invisible to the suite as it stands.)

## Findings

### broll-1 - the retry button's new 409 branch prints the one sentence that is almost always false
- Severity: medium
- Confidence: CONFIRMED
- Where: `broll/web/static/ingest.js:1718-1727` (second location:
  `companion/src/ccsync_companion/broll_ingest.py:1660-1664`)
- What: today's broll-1 fix re-pointed the retry dispatch at the loopback's
  `/broll/ingest/run` and added `if (e.status === 409)` -> "Another of your
  computers is still working on this batch, so it picks them up." But the
  companion's `run()` returns 409 FIRST for "this computer is already indexing
  another batch", long before any claim is attempted, and the server route
  that was just called (`retry-failed`, same commit) now REFUSES the call
  outright while another machine holds a live lease. So by construction the
  remote-leaseholder 409 can no longer reach this branch, and the 409 that does
  reach it is the local-busy one. The real message the companion sent is in
  `e.message` (`ingestLoopback` puts `parsed.message` there) and is thrown
  away; before the fix that message was shown.
- Failure scenario: an editor is indexing batch B on this machine, opens the
  finished batch A and clicks [ try the 12 failed again ]. The server moves A to
  `queued`; the loopback 409s "this computer is already indexing another
  batch"; the page says another of their computers will pick it up. Nothing
  will: no companion polls for queued batches (the discovery route was deleted
  in the same commit, broll-3) and the other machines were never told. A sits
  in `queued` for ever holding its archive-name reservations - the exact
  BROLL-8 state this feature exists to prevent. The page then sets
  `ing.batchUid = uid; ing.running = true; ingestStartPolling()` and toasts
  "12 clips queued again" in success green, so the live panel shows a run that
  does not exist.
- Evidence: `broll_ingest.py:1660` `if current and current != batch_uid: return
  409, {"ok": False, "message": "this computer is already indexing another
  batch"}` - the first 409 in `run()`, ahead of `enabled`, the identity checks
  and the claim. `routes_batches.py:220` 409s a live lease, so the remote case
  cannot get past the durable half. `ingestLoopback` (ingest.js:579) already
  carries the companion's own wording in `err.message`.
- Ledger: new (CR-245 / broll-1 fixes the dispatch but mis-labels its failure)
- Suggested fix: show `e.message` for every loopback failure here (the notice's
  `else` branch already does), and reserve the "another of your computers"
  wording for the 409 the *server* route returns. Do not set `ing.running` /
  start polling when the dispatch failed.

### broll-2 - the new retry-failed 409 reaches the editor as "[object Object]"
- Severity: medium
- Confidence: CONFIRMED
- Where: `broll/web/app/routes_batches.py:220-225`, `broll/web/static/ingest.js:1706-1709`
  (via `broll/web/static/app.js:180`)
- What: the broll-5 fix raises `HTTPException(409, {...})` with a DICT detail,
  so the body is `{"detail": {"detail": "...", "reason": "held", ...}}`.
  `fetchJson` does `const detail = body && (body.detail || body.message)` and
  then `new Error(detail)` - given an object, `Error.message` is the string
  "[object Object]". `ingestRetryFailedBatch` shows exactly that with
  `toast(e.message, "error")`.
- Failure scenario: an editor clicks [ try the failed ones again ] on a batch
  another of their machines still holds. The carefully written sentence
  ("EDIT-01 is still working on this batch. Stop it first, ...") never appears;
  a red toast reading "[object Object]" does, and the editor has no idea what
  to do. The new test only asserts `"EDIT-01" in r.text`, which passes on the
  raw JSON and proves nothing about what is rendered.
- Evidence: `app.js:180-182` (the only `fetchJson` the ingest panel uses);
  `ingest.js:1319-1320` is the same file's existing workaround for exactly this
  (`typeof detail === "object" ? detail.detail : e.message`) - the precedent the
  new branch did not follow.
- Ledger: new (CR-245 / broll-5)
- Suggested fix: either unwrap an object detail once inside `fetchJson`, or use
  the `detail.detail` pattern at ingest.js:1706 as the same file already does
  for the batch-create 409.

### broll-3 - `client_shares.db` creation is still the crash-unsafe half of the migration broll-2 fixed, and the new try/except now hides it
- Severity: medium
- Confidence: CONFIRMED (mechanism proved; the kill itself not staged)
- Where: `broll/web/app/client_folders.py:155-158` (the `version == 0` branch) and
  `broll/web/app/client_folders.py:266-276` (`get_shares_db`'s new `except sqlite3.Error`)
- What: broll-2's fix hardened the v1 -> v2 step (IMMEDIATE lock, column probe,
  idempotent backfill) but left the branch above it untouched.
  `conn.executescript(_SCHEMA)` runs in autocommit with no BEGIN, so each
  CREATE is durable the instant it runs while `PRAGMA user_version = 2` is the
  LAST statement of the script - the identical "durable DDL, un-stamped
  version" shape the fix was written for. A container killed inside the first
  create leaves some tables at `user_version = 0`; every later entry re-runs
  the script and raises `table client_folders already exists`, for ever. And
  the new `except sqlite3.Error: log.exception(...)` then SWALLOWS that and
  yields the connection anyway, so instead of a loud failure the editor's panel
  and every public `/broll/share/<token>/` link 500 on the missing tables with
  nothing but one container log line to say why.
- Failure scenario: the container is restarted (or OOM-killed) during the very
  first request that creates the ledger - which on the NAS is a bind-mounted
  file on a spinning pool. Client links are dead permanently; the cure is
  hand-deleting a file on the NAS, and nothing in the dashboard's notices says
  so.
- Evidence: from the broll/web venv,
  `executescript('CREATE TABLE a(x); CREATE TABLE b(y); SELECT bad_syntax from;')`
  -> `err: near ";": syntax error`, then on a fresh connection
  `tables: [('a',), ('b',)]  user_version: (0,)`. Partial schema, version 0,
  durable.
- Ledger: CR-245 / broll-2 does not fix the v0 case
- Suggested fix: wrap the create in the same `BEGIN IMMEDIATE` ... `commit()`
  (drop the trailing PRAGMA from `_SCHEMA` and stamp it inside the
  transaction), use `CREATE TABLE IF NOT EXISTS`, and raise a `notices` entry
  rather than only `log.exception` when `ensure_schema` is swallowed.

### broll-4 - the deleted discovery route left its login-gate carve-out behind, and today's test asserts the opposite
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/app/routes_fleet.py:60-71` (route removed) /
  `dashboard/src/ccsync_dashboard/app.py:1063-1075` (`_broll_fleet_list_re` kept)
- What: broll-3 deleted `GET /api/fleet/ingest/batches`; the dashboard's
  login_gate still carries an exact carve-out for that path, so
  `/broll/api/fleet/ingest/batches` (and `.../batches/`) is still admitted with
  no session - onto a path that no longer has a route. Harmless today (a 404),
  but it is an open hole aimed at a collection path: any GET route that later
  lands there is unauthenticated by inheritance. Worse, the regression test
  `test_the_fleet_docstrings_do_not_claim_the_gate_needs_widening` pins the
  claim that the gate "was widened in the same commit", which is now a wrong
  fact about a security gate held in place by a green test - the very thing its
  own docstring says gets a correct gate "fixed".
- Failure scenario: a future b-roll fleet GET at the collection path ships
  believing it is session-gated; it is not.
- Evidence: `grep -rn "fleet/ingest/batches"` - the only remaining producer of
  that exact path is `app.py:1075`; `routes_fleet.router` now has no GET
  (asserted by the new test itself).
- Ledger: new (CR-245 / broll-3 landed one side)
- Suggested fix: delete `_broll_fleet_list_re` and its use in the same change as
  the route, and correct the test's docstring.

### broll-5 - a ledger `ensure_schema` failure at BOOT degrades the whole /broll mount, which the same fix says must not happen
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/app/main.py:40` and
  `dashboard/src/ccsync_dashboard/broll.py:555-556` vs
  `broll/web/app/client_folders.py:266-276`
- What: the broll-2 fix guards `ensure_schema` only on the REQUEST path
  ("a sqlite failure HERE is not allowed to take the public share door out").
  Both boot paths still call it bare. Under the dashboard the exception is
  caught one level up and the mount is marked DEGRADED with "every /broll
  request will fail until the data root is writable" and the nav link hidden -
  a statement that is now false, because after the same fix every request
  works. Standalone (`main.py`'s lifespan) the app does not boot at all.
- Failure scenario: `client_shares.db` is locked for longer than the busy
  timeout by a concurrent write (the new `BEGIN IMMEDIATE` makes that a real
  possibility) exactly as the container boots. /broll is marked DEGRADED for
  the life of the container, the nav link disappears for every editor, and the
  home page reports a cause that is not the cause - while the app is in fact
  healthy.
- Evidence: `broll.py:523-556` (`client_folders.ensure_schema()` is the last,
  unguarded statement of `_init_broll_storage`) and `broll.py:472-494` (the
  DEGRADED text).
- Ledger: new (CR-245 / broll-2 landed one side)
- Suggested fix: wrap the boot call in the same `try/except sqlite3.Error:
  log.exception` as `get_shares_db`, so a ledger problem degrades the client
  folders feature and nothing else.

### broll-6 - a failed backfill still stamps the schema version, so those items lose the hash identity for ever
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/app/client_folders.py:228-245` with `client_folders.py:174-181`
- What: `_backfill_hashes` wraps both the index read and the ledger UPDATEs in
  one `try: ... except sqlite3.Error: return`. A failure part-way (an unreadable
  `broll.db`, a full disk on the ledger write) returns silently, and the caller
  then writes `PRAGMA user_version = 2` regardless - so the step is never
  retried and the affected items keep `hash = ''`. That is the third identity
  (the one that survives a `/api/ingest/moved` rename) permanently absent,
  silently, for folders curated before v2.
- Failure scenario: `broll.db` is mid-`publish_db.py` rename when the first
  request after an upgrade enters the migration; the connect raises, the version
  is stamped, and every pre-v2 curated clip silently loses the move-survival
  identity. The next index publish that renames one of those clips drops it out
  of the client's folder page.
- Evidence: `except sqlite3.Error: return` at `client_folders.py:245` returns
  into `ensure_schema`, which unconditionally executes the PRAGMA next.
- Ledger: new (adjacent to CR-245 / broll-6)
- Suggested fix: only stamp `user_version` when the backfill reports that it
  completed, or (cheaper) keep the stamp but make the blank-hash fill a
  best-effort step run on every open rather than once at migration time.

## Coverage note
Not reached: `search.py` (1386 lines) and `semantic.py`, `routes_api.py`,
`routes_ingest.py`, `fuzzy.py`, `archive_names.py`, most of `ingest_batches.py`
(the claim/upload/item-status half) and the whole of `broll/indexer/*.py`
(`run_queue.py`, `parallel_claude.py`, `build_archive.py`) - none of which
changed in this commit. The static SPA outside the ingest panel (`app.js`,
`share.js`, `sprite.js`) was read only where `fetchJson` mattered.

What the suite does not cover: nothing in it renders a `detail` dict the way
`fetchJson` does (broll-2 is invisible to the new 409 test); no test exercises
the loopback dispatch against a companion that is already busy (broll-1); no
test creates `client_shares.db` from a partially written file (broll-3); and
the mount's DEGRADED wording is asserted nowhere against the app's actual
behaviour (broll-5).

## OUT OF TERRITORY
- `companion/src/ccsync_companion/broll_server.py:1820-1831`: the
  `/broll/ingest/retry` handler dispatches `ingestor.run()` when the body
  carries `batch_uid`, so the 0.9.71 companion now handles both spellings;
  harmless, but it means broll-1's page-side change is untested against the
  build it was written for.
- `dashboard/src/ccsync_dashboard/broll.py:478-494`: the DEGRADED log/notice
  text asserts "every /broll request will fail", which is no longer true for
  the client-shares failure mode (see broll-5).
