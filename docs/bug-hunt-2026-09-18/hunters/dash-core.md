# dash-core - dashboard app factory, auth/sessions/OIDC, secrets bootstrap, setup engine, site store, help/docs, internal sftp

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/app.py` (100%, plus `git diff 34a3c8f..HEAD` and `18e69f3..34a3c8f`)
- `dashboard/src/ccsync_dashboard/auth.py` (100%)
- `dashboard/src/ccsync_dashboard/sessions.py` (100%)
- `dashboard/src/ccsync_dashboard/oidc.py` (100%)
- `dashboard/src/ccsync_dashboard/secrets_boot.py` (100%)
- `dashboard/src/ccsync_dashboard/internal_sftp.py` (100%)
- `dashboard/src/ccsync_dashboard/published_docs.py` (100%)
- `dashboard/src/ccsync_dashboard/help.py` (~70%: the index cache, `document_root`, `resolve_document`, `read_rel`; the markdown renderer only skimmed)
- `dashboard/src/ccsync_dashboard/setup_routes.py` (~60%: the two gates and the task routes)
- `dashboard/src/ccsync_dashboard/setup_engine.py` (~25%: the gate/warn carve-out, `_run_storage`, `_run_secrets` surroundings)
- `dashboard/src/ccsync_dashboard/tailscale_local.py` (100%), `truenas_client.py` (skim), `site_store.py` (skim)
- Followed calls out of territory (read, not reported on): `notices.is_db_busy` / `record_db_busy`, `db.connect` / `BUSY_TIMEOUT_*`, `api.api_locate_files` / `_require_fleet_caller`, `cards.py` (`CardsGate`, `CardsDispatch`), `cards_pool.slug_for` / `is_slug`, `local_users.ROLES`.
- Tests read: `dashboard/tests/test_db_busy_2026_09_17.py`, and the dash-core suites listed below.

Tests run:
`cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_auth.py tests/test_sessions.py tests/test_oidc.py tests/test_secrets_boot.py tests/test_internal_sftp.py tests/test_setup_routes.py tests/test_setup_engine.py tests/test_help_page.py -q`
-> **293 passed, 1 skipped** (55 s).

## Findings

### dash-core-1 - the DCORE-3 boot refusal passes on a zero-byte secret file, so a half-written `dash_session_secret` still signs the whole fleet out on the next boot
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/app.py:544-552` (`check_persisted_secrets`), with `dashboard/src/ccsync_dashboard/secrets_boot.py:91-100` (`_write_secret_file`) and `secrets_boot.py:196-201` (the `except OSError` that swallows the failed write)
- What: `_write_secret_file` opens the target with `O_CREAT|O_TRUNC` and writes in place - no temp file, no rename, no fsync, no read-back. `ensure_secrets` wraps that call in `except OSError` and carries on with the in-memory value. `check_persisted_secrets`, which is the whole DCORE-3 refusal, then asks only `(directory / name.lower()).is_file()`. A write that created the file and then failed (ENOSPC on `/data`, the container killed between `open` and `close`, a dataset that went read-only after the `creat`) leaves a **zero-byte** file, which satisfies `is_file()`, so `_refuse_ephemeral_secrets` finds nothing lost and the dashboard serves happily on a secret that exists only in memory - the exact state the refusal was written to make impossible.
- Failure scenario: first boot on an appliance whose `/data` is full or is snapshot-restored mid-write. `DASH_SESSION_SECRET` is generated, `dash_session_secret` lands as 0 bytes, boot succeeds, every editor signs in and every companion is issued an identity token over that in-memory key. On the next `docker restart`, `_read_secret_file` returns `""`, `ensure_secrets` generates a **different** secret, and every companion's non-expiring identity token (CR-86) and every browser session 401 at once - the fleet grid goes stale and the halt / pushed-update / lane-B-resume / file-move command channel dies with it. `DASH_SESSION_SECRET_PREVIOUS` cannot help, because nobody ever knew the lost value.
- Evidence: run from `dashboard/` with the dashboard venv:
  ```
  (d/'dash_session_secret').write_text('')
  empty file exists: True
  check_persisted_secrets says lost: []
  what the NEXT boot reads back: ''
  ```
  i.e. the refusal returns an empty "lost" list for a secret file that carries nothing.
- Ledger: new (CR-nn does not fix this - DCORE-3, 2026-09-04, only covers the "file absent" half)
- Suggested fix: write through a sibling `.tmp` + `os.replace` (with an `fsync` on the fd before the rename), and make `check_persisted_secrets` compare the file's CONTENT to the generated value rather than testing existence. Both are cheap: five secrets, once per boot.

### dash-core-2 - the database-busy 503 opens a second connection and WRITES, so a busy request waits the busy timeout twice and adds write pressure to the contention it is reporting
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/app.py:1350-1365` (the `notices.is_db_busy(exc)` branch in `unhandled_error`), with `db.py:686` (`BUSY_TIMEOUT_MS = 5000`) and `notices.py:1130-1150` (`record_db_busy` -> `db.notice` + `conn.commit()`)
- What: the branch fires precisely because a request already spent its full 5 s busy timeout and lost the write lock. It then calls `db.connect(settings.db_path)` (default `busy_ms=BUSY_TIMEOUT_MS`, 5000) and performs a *write* - `db.notice` plus `conn.commit()` - against the same still-locked database. So the request blocks for up to another 5 s before the 503 is sent, and if the second write also times out the only record is `log.exception("could not record a database-busy notice")` in a container log that the next recreate throws away - which is the failure mode `test_db_busy_2026_09_17.py`'s own docstring says this rework exists to end.
- Failure scenario: a report from a machine with tens of thousands of media rows holds the write lock for 12 s (the `slow write` notice's own example). Every other request that touches the DB in that window waits 5 s, fails, then waits up to 5 s more inside the handler: ~10 s of a threadpool worker each, on the `workers=1` container, and every one of them queues another INSERT behind the long writer. The one notice that would have told the operator what happened is the one most likely to be dropped, because the lock is held hardest exactly then.
- Evidence: `db.connect(path, *, busy_ms=BUSY_TIMEOUT_MS)` at `db.py:690` - the handler passes no `busy_ms`; `record_db_busy` ends in `conn.commit()` after `db.notice`, i.e. a write. `test_db_busy_2026_09_17.py::test_the_handler_answers_a_locked_database_503_with_retry_after` raises the error from a route with no lock held at all, so it cannot fail on this.
- Ledger: new (related to the 4aaca6a busy-database rework)
- Suggested fix: open that connection with a short busy timeout (e.g. `busy_ms=200`) so the 503 is not delayed by the very contention it describes, or hand the record to the collector's queue instead of writing it on the request path. A count that arrives one cycle late is worth more than a 503 that arrives five seconds late.

### dash-core-3 - OIDC mints a session for a username the rest of the dashboard will not accept, and says nothing
- Severity: medium
- Confidence: CONFIRMED (the missing check), PLAUSIBLE (the exact user-visible outcome per route)
- Where: `dashboard/src/ccsync_dashboard/oidc.py:279-294` (`username_from_claims`), against `dashboard/src/ccsync_dashboard/db.py:615` (`_USERNAME_RE = ^[a-z][a-z0-9._-]{0,31}$`) and `local_users.py:64` (the same regex)
- What: `username_from_claims` lower-cases the claim and refuses only `@`, `/` and `\`. Everything else becomes the session identity: a space, a colon, a plus, non-ASCII (`jürgen`), a 200-character string, a name starting with a digit. `auth.start_session` writes it into `auth_sessions` and every page renders it - but `db.record_known_editor`, `db.set_selection` and friends all gate on `_USERNAME_RE` and simply refuse, and `db.known_editor_usernames` can never contain such a name.
- Failure scenario: a customer sets `DASH_OIDC_ALLOWED_GROUPS` (which is the supported way to let the IdP decide membership) and `DASH_OIDC_USERNAME_CLAIM=name`, so the claim is `Jürgen Müller`. `require_fleet_member` returns on the group, a session is minted, the dashboard draws - and every tick, every Syncthing device join and every selection write for that person is refused deep inside `db.py` with no sentence anyone can read. The editor appears signed in to a dashboard that does nothing.
- Evidence: `oidc.py:288` is the entire shape check (`if "@" in username or "/" in username or "\\" in username`); `grep -n "_USERNAME_RE" db.py local_users.py` shows four gates on the strict regex and none on this path. `tests/test_oidc.py` pins only the `@`/`/` refusals.
- Ledger: new (related to trust-model-5, which added `require_fleet_member` but not a shape check)
- Suggested fix: apply `db._USERNAME_RE` in `username_from_claims` and raise the same `OidcError` shape, naming `DASH_OIDC_USERNAME_CLAIM` - a 403 an admin can read beats a session that half-works.

### dash-core-4 - the per-episode open paths are not restricted to GET, although the comment beside them says they are
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/app.py:128-148` (`_OPEN_PATTERN` / `_open_path`) and `app.py:1157` (the `login_gate` test), same shape for every entry in `_OPEN_EXACT`
- What: the comment states "GET only, no secret in any of the three, and the slug shape is pinned so this can never widen to anything else under `/cards/p/`", but `_open_path` looks at the path alone. A `POST`/`PUT`/`DELETE` to `/cards/p/<slug>/sw.js`, `/cards/sw.js`, `/manifest.webmanifest` or `/offline` skips the session gate entirely. Nothing behind those names writes today (the Cards sub-app answers 404/405 and the CSRF gate still applies its `/cards/` origin rule), so this is not exploitable now - but the invariant the comment asserts is not the one the code enforces, and the next handler registered at one of those names inherits an unauthenticated write door with nothing in its diff to say so.
- Failure scenario: someone adds `POST /offline` (a "dismiss" ping) or the Cards repo grows a `POST /sw.js` cache-purge route; it is reachable with no session from anything that can reach the dashboard.
- Evidence: `_open_path(path)` takes only `path`; `login_gate` calls it before any method test. Every other carve-out in the same function that is meant to be method-limited spells it out (`path == "/api/v1/fleet/halt" and request.method == "GET"`).
- Ledger: new
- Suggested fix: make `_open_path(path, method)` and require `method in ("GET", "HEAD")` for the pattern and for the static-asset members of `_OPEN_EXACT`; leave the credentialed POST routes (`/api/v1/report`, `/api/v1/login`, ...) as they are.

### dash-core-5 - expired browser sessions accumulate on a long-running container: the only sweep runs at boot
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/app.py:720-721` (`session_store.prune()` / `prune_attempts()` in the lifespan), `sessions.py:303-318` (`prune`)
- What: `sessions.py` says "expired sessions are deleted rather than left to accumulate", but the only unconditional sweep is the one at boot. `validate()` deletes a row only when that exact cookie is presented again after it expired, and nothing in `collector.py` (which is the module that prunes the other eight tables) touches `auth_sessions`. A session from a phone that is never opened again, or a laptop that was reimaged, stays until the next container restart. `login_attempts` is fine - `record_failure` sweeps it inline - so this is `auth_sessions` only.
- Failure scenario: a container that runs for months (the `record_failure` comment names exactly that case) between deploys holds every session row the fleet has ever minted, revoked or idled out; the admin Users page's session list and `live_counts()` scan them all, and `list_all(limit=200)` starts hiding live sessions behind dead ones once 200 accumulate.
- Evidence: `grep -rn "session_store.prune\|prune_attempts" dashboard/src/ccsync_dashboard/*.py` returns only the two lifespan lines.
- Ledger: new
- Suggested fix: call `store.prune()` from the collector cycle that already calls `db.prune`, on the same schedule.

### dash-core-6 - `internal.env` and `syncthing.env` are rewritten in place on every boot, so a boot cut off mid-write leaves the sidecars a truncated credential
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/secrets_boot.py:91-100` (`_write_secret_file`), called unconditionally from `_write_sidecar_env_files` (`secrets_boot.py:263-292`) on every `ensure_secrets()`
- What: same non-atomic write as dash-core-1, but on files that are rewritten *every* boot rather than once. `O_TRUNC` destroys the good copy before the new bytes are written, and the only handler is a `log.warning`. The sftp sidecar reads `internal.env` at its own startup and never again.
- Failure scenario: a host reboot or an OOM kill during the dashboard's boot leaves `internal.env` at 0 bytes. The sftp sidecar starts, gets no `CCSYNC_INTERNAL_TOKEN`, and `internal_sftp._require_internal_token` refuses every `AuthorizedKeysCommand` call with a 401 - which is precisely the dash-admin-2 outage ("no editor could authenticate to lanes A/B at all"), reached by a different road. Nothing in either log says the file is empty.
- Evidence: `_write_secret_file` is `os.open(..., O_WRONLY|O_CREAT|O_TRUNC)` then `fh.write(value)`; no temp file, no rename, no fsync. `sftp.env` is `unlink`ed in the same `try`, so a failure part-way also leaves the cleanup half-done.
- Ledger: new (related to dash-admin-2, 2026-08-21)
- Suggested fix: one atomic-write helper (temp + `os.replace` + `fsync`) used by `_write_secret_file`, which also fixes `ai_providers.write_secret_file`'s AI keys for free - the docstring already promises "one implementation, so a future fix to it reaches every secret this container writes".

## Coverage note
- `site_store.py` (946 lines) and `setup_engine.py` (1664 lines) were skimmed, not read line by line: `setup_engine`'s per-task `run` functions (`_run_syncthing`, `_run_tailnet`, `_run_software`, `_run_alerts`) and `site_store`'s history/manifest merge paths are the largest unread surface in this territory, and both write state.
- `help.py`'s markdown renderer (`render_markdown`, ~250 lines, escapes everything on the way in) was only skimmed for an HTML passthrough; I found none but did not fuzz it.
- `truenas_client.py` (47 lines) was read but has no exercised call path in this territory.
- Not attempted: a live multi-process contention test of the busy-database path (rule 1 - no live systems), so dash-core-2's second timeout is argued from `db.connect`'s default rather than measured.
- The suite does not cover: any of the six findings above. In particular there is no test that a persisted secret file is non-EMPTY (`tests/test_secrets_boot.py` only checks existence and mode), no test that `login_gate`'s open paths are method-limited, and `test_db_busy_2026_09_17.py`'s handler test raises from a route with no lock held, so it cannot see the second busy wait.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/notices.py:1105-1112`: `DB_BUSY_MARK = "database is locked"` misses SQLite's other contention error, `SQLITE_LOCKED` ("database **table** is locked"), which does not contain that substring - such a request still 500s with a `server_error` notice whose fix line says "send to support". (dash-collector-alerts)
- `dashboard/src/ccsync_dashboard/cards.py:353-368`: `CardsGate` performs no session check at all, so app.py's `login_gate` is the *only* thing standing in front of a whole episode's cut under `/cards/p/<slug>/`; worth pinning with a test on the mount side rather than resting on the middleware alone. (dash-cards)
(Nothing else. One in-territory nit not filed as a finding: `oidc.py:388-402` builds a fresh `PyJWKClient` per callback, so every OIDC sign-in re-fetches the IdP's JWKS with no cache and no timeout - cosmetic until an IdP rate-limits the dashboard.)
