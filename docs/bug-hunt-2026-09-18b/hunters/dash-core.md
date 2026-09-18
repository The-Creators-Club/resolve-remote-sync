# dash-core - dashboard app factory, auth/sessions/OIDC, secrets bootstrap, setup engine, site store, help/docs, internal sftp

Files read (with approximate coverage):
- `git diff -- dashboard/src/ccsync_dashboard/{app,oidc,secrets_boot,sessions}.py` (100%, every hunk read against the ledger sections it cites)
- `dashboard/src/ccsync_dashboard/app.py` (~90%: the open-path set, `login_gate`, the body-limit middleware, `check_persisted_secrets` / `_refuse_ephemeral_secrets`, the lifespan, `unhandled_error` / `_record_off_the_loop` / `_install_busy_handler_on_mounts`)
- `secrets_boot.py` (100%), `sessions.py` (~80%), `oidc.py` (`username_from_claims` and its callers)
- `setup_engine.py` (`_check_secrets`, `_run_secrets` only), `published_docs.py` / `help.py` / `internal_sftp.py` / `site_store.py` / `truenas_client.py` / `tailscale_local.py` (not re-read - unchanged by this fix pass, all six were read at 100%/70% by the morning hunt)
- Followed out of territory (read, not reported on): `notices.record_db_busy` / `redact_path`, `db.age_seconds` / `_USERNAME_RE` / `connect(busy_ms=)`, `collector.Collector.__init__` / `_run_prune`, `cards_exec.PinnedExecutor`, `jobs.can_pin`, `api.api_locate_files` / `LocateIn`, `companion/sync/server_locate.py`
- Ledger sections read: `docs/bug-hunt-2026-09-18/ledger/dashboard.md` CR-285H, CR-285O, CR-285X, CR-285Y, CR-285Z; `ledger/highs.md` CR-282F; `hunters/dash-core.md` (all six findings) and `hunters/wire.md` wire-2
- Tests read: `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_mediums.py` (the wire-2, security-4, dash-core-1 tests)

Tests run:
`cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_secrets_boot.py tests/test_sessions.py tests/test_oidc.py tests/test_hardening.py -q` -> **114 passed**.
Plus two scratch scripts outside the repo (below) against the dashboard venv.

## Findings

### dash-core-1 - wire-2's fix makes every unhandled error under a mount record itself TWICE, and write to the busy database twice
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/app.py:1630-1651` (`_install_busy_handler_on_mounts`), with `app.py:1428` (the parent's `unhandled_error`) and `app.py:1412-1425` (`_record_off_the_loop`)
- What: a handler registered for the bare `Exception` class is Starlette's `ServerErrorMiddleware.handler`, and that middleware calls the handler, sends the response, and then **re-raises** (`raise exc`). Installing the parent's handler on the mounted sub-apps therefore does not replace the parent's copy, it adds a second one in front of it: the sub-app's `ServerErrorMiddleware` runs the handler and answers 503/500, re-raises, and the parent's `ServerErrorMiddleware` catches the same exception and runs the SAME handler again (`response_started` is now true, so the second response is discarded). Every error under `/broll`, `/music` and `/ytdl` now logs its traceback twice and performs two `_record_off_the_loop` writes.
- Failure scenario: one `GET /broll/...` that hits a locked archive database produces a `db_busy` notice reading "**2 time(s)** a request to ... waited 5 s" - so the counter the operator is told to watch ("if this keeps climbing, send Diagnostics to support") runs at double the real rate for exactly the three mounts wire-2 added, and any alert threshold on it trips at half the intended traffic. Worse in the case the fix is for: under sustained contention each mounted failure now opens and commits to the dashboard DB twice instead of once, adding write pressure to the contention being reported - the objection CR-282F/dash-core-2 was raised for.
- Evidence: measured twice. (a) minimal repro, starlette 1.6.0: a parent FastAPI with `add_exception_handler(Exception, h)` plus a mounted sub-app with the same handler -> `handler calls: ['/sub/boom', '/sub/boom']` for ONE request, versus `['/pboom']` for a parent route. (b) against the real factory (`create_app(Settings(...))`, a sub-app mounted at `/sub` raising `sqlite3.OperationalError("database is locked")`, `_install_busy_handler_on_mounts` called exactly as app.py calls it): status 503 and a single row in `notices` whose body is `2 time(s) a request to /boom waited 5 s ...`. `tests/test_bug_hunt_2026_09_18_dashboard_mediums.py::test_a_mounted_sub_app_answers_a_busy_database_with_the_same_503` asserts only the status code, so it cannot see this.
- Ledger: CR-285O (wire-2) opens a neighbour
- Suggested fix: make the installed handler idempotent per request - e.g. wrap it so it sets and checks a flag in `request.scope` (`scope.setdefault("_ccsync_error_recorded", False)`) and skips the log+record on a second entry, still returning the same response. One line in the wrapper `_install_busy_handler_on_mounts` already builds.

### dash-core-2 - a notice written for a mounted app names a path that does not exist on this dashboard, and two mounts collide on one row
- Severity: medium
- Confidence: CONFIRMED (the lost prefix), PLAUSIBLE (the exact cross-mount collision)
- Where: `dashboard/src/ccsync_dashboard/app.py:1459-1470` (`request.url.path` inside `unhandled_error`), reached for mounts by `app.py:1630-1651`
- What: Starlette's `Mount` mutates the request scope in place (`scope.update(child_scope)`), so by the time the handler runs, `scope["path"]` is the path **inside** the sub-app and the mount prefix lives in `scope["root_path"]`. `request.url.path` returns the inner path only. Before wire-2 no notice was ever written for a mounted app, so this is new with the fix.
- Failure scenario: a busy database under the fleet ingest route records `subject = "/api/ingest (database busy)"` on the PROBLEMS panel. The operator greps the dashboard for `/api/ingest` and finds nothing (the real route is `/broll/api/ingest/...`), and because `notices.redact_path` keeps only the first two segments, the same failure under `/music/api/ingest` and `/ytdl/api/...` folds into the same row - one count for two features, and the "which app is busy" question the notice exists to answer is the one it cannot.
- Evidence: the (b) run above, whose notice subject is `/boom (database busy)` although the request was `GET /sub/boom`; `notices.record_db_busy` -> `redact_path(path, route)` with `route=""` (a Mount has no usable `.path`, as the dash-collector-alerts-6 comment already notes).
- Ledger: CR-285O (wire-2) opens a neighbour
- Suggested fix: build the recorded path as `request.scope.get("root_path", "") + request.url.path` in `unhandled_error` (it is already defensive about `route`), so `/broll/api/ingest` is what the operator reads.

### dash-core-3 - the Setup page still passes a ZERO-BYTE secret file, so the dash-core-1 hole is closed at boot and open in the wizard
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/setup_engine.py:806-820` (`_check_secrets`), against the fixed `app.py:598-615` (`check_persisted_secrets`)
- What: CR-285H replaced `is_file()` with a content comparison in `check_persisted_secrets`, but `_check_secrets` - the Setup page's "Secrets" task, which asks the same question about the same five files in the same directory - was left on `(secrets_dir / name.lower()).is_file()`. A truncated file therefore reports **"all five secrets present"** on the one screen an admin looks at when they suspect exactly this.
- Failure scenario: `/data` fills while the container is running and a later `ai_providers` / sidecar write leaves `dash_session_secret` at 0 bytes. The admin opens Setup, sees the Secrets task green, and does not press [ RUN ] - which is the one action that would heal it, since `_run_secrets` -> `ensure_secrets` DOES read the content and would regenerate and persist. The next restart mints a different session secret and 401s every browser session and every non-expiring `cce1.` identity token, which is the outage CR-285H is about.
- Evidence: `grep -n "is_file()" setup_engine.py` -> line 815, unchanged by `git diff`; `secrets_boot._read_secret_file` strips an empty file to `""`, which is why `ensure_secrets` and `check_persisted_secrets` both treat it as absent and this one does not.
- Ledger: CR-285H does not fix dash-core-1 on the Setup surface
- Suggested fix: have `_check_secrets` use `secrets_boot._read_secret_file(...)` (non-empty) instead of `is_file()`, or call `check_persisted_secrets` with a provenance of its own.

### dash-core-4 - the atomic secret write fsyncs the file but never its directory, so the power-loss case the finding names can still lose the rename
- Severity: low
- Confidence: CONFIRMED (the missing fsync), PLAUSIBLE (the loss on a given filesystem)
- Where: `dashboard/src/ccsync_dashboard/secrets_boot.py:118-134` (`_write_secret_file`)
- What: the new write is `open(tmp)` -> `write` -> `flush` -> `fsync(file)` -> `chmod` -> `os.replace`. `os.replace` makes the swap atomic with respect to a concurrent reader, but the DIRECTORY entry it creates is not durable until the parent directory is fsynced. dash-core-1's own failure list is "ENOSPC on a full `/data`, a read-only dataset, an OOM kill **or a host power loss**", and only the first three are closed by this shape.
- Failure scenario: the appliance loses power in the seconds after first boot generated `DASH_SESSION_SECRET`. On ext4 with `data=writeback` (or any filesystem without the rename-implies-data barrier) the directory can come back without the new entry: the file is absent, `ensure_secrets` mints a different secret, and every identity token issued in that first window is dead - the same outcome CR-285H exists to prevent, by the one road the temp+rename does not cover. ZFS on the shipped TrueNAS target is safe here; the Synology/appliance target is the exposure.
- Evidence: no `os.open(dir, O_RDONLY)` / `os.fsync(dirfd)` anywhere in the file (`grep -n fsync secrets_boot.py` -> one hit, the file fd). `check_persisted_secrets` reads back through the page cache, so it cannot see the difference either.
- Ledger: CR-285H is incomplete for the power-loss half of dash-core-1
- Suggested fix: after `os.replace`, `fd = os.open(str(path.parent), os.O_RDONLY); os.fsync(fd); os.close(fd)` inside a `try/except OSError` (the call is meaningless and raises on Windows, which is dev-only here).

### dash-core-5 - security-4's 512 KB locate cap can refuse a batch the route's own cap allows, and the companion reads that refusal as "these files were deleted"
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/app.py:285-297` (`MAX_LOCATE_BODY_BYTES`, `_BODY_LIMITS`), against `api.py:10994-11010` (`LocateFileIn.name` is `max_length=512`, `LocateIn.files` capped at 2000 in the handler) and `companion/src/ccsync_companion/sync/server_locate.py:169-173`
- What: the new declared-length ceiling is 512 KB, justified in the comment as "2000 entries of ~120 bytes of JSON, with room to spare". With `ensure_ascii` JSON (six bytes per escaped CJK character - and this fleet's vault holds `母母女子` and `Matej Šimalčík`), 2000 entries whose basenames are ~40 CJK characters is 561 KB and 80 characters is 1.04 MB, both over the cap and both inside the model's own `max_length=512`. The middleware answers before the route, so the reply is `{"detail": "request body too large (max 524288 bytes)"}` - NOT "the route's careful 413 sentence" the comment says it keeps.
- Failure scenario: a lane B pass on a project of Chinese-named clips asks about a full 2000-file batch, gets a 413 from the middleware, and `server_locate.locate` logs "the dashboard answered HTTP 413 - **treating these files as deletions**" and returns None. The hand-move probe then reaches the exact wrong conclusion the route's 413 exists to prevent, on the machine whose files were only moved. (Lane B's breaker and CR-268's move-not-trash bound the damage, which is why this is low and not high.)
- Evidence: `python -c` with `json.dumps` -> `2000 x 40 cjk 560901` bytes, `2000 x 80 cjk 1040901` bytes, `2000 x 60 ascii 200901`. `_too_large` at `app.py:918-922` is the body that is actually returned; `server_locate.py` treats every `status != 200` identically.
- Ledger: CR-285 (security-4) opens a neighbour
- Suggested fix: raise `MAX_LOCATE_BODY_BYTES` to ~2 MB (still a 50x cut from the 4 MB default and far below anything that matters on a single-worker container), or have `server_locate` halve the batch and retry once on a 413 rather than turning it into a deletion verdict.

## Coverage note
- `setup_engine.py` beyond the two secrets tasks, `site_store.py`, `help.py`'s markdown renderer and `published_docs.py` were NOT re-read: `git diff` shows no change to any of them in this fix pass, and the morning hunt covered them. If a builder's OWED line landed in one of those files without a diff entry I would not have seen it.
- I did not exercise the mounted-app double-handler against the REAL `/broll` mount (that needs a b-roll checkout on the path); the repro used a synthetic mount on the real `create_app`, which is the same middleware shape.
- Not attempted: a live contention test of `_record_off_the_loop`'s 250 ms timeout (rule 1), so "the 503 no longer waits on the database" is argued from `db.connect(busy_ms=...)` and the threadpool hop, not measured.
- The suite does not cover: how many times a mounted error records itself, which PATH a mounted error records, the Setup page's zero-byte secret, or a locate body between 512 KB and 4 MB.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/jobs.py:467` + `cards_exec.py:189`: `can_pin` is true only while an episode happens to be open, so a job can be PINNED at 10:00 and sit in a queue whose engine the pool has since released; nothing re-checks a pinned row. (dash-release-jobs / res-fleet)
- `dashboard/src/ccsync_dashboard/collector.py:2271-2286`: `_run_prune` commits mid-runner so `_timed`'s `elapsed` now spans two transactions; the slow-write attribution for `prune` is measured over both. (dash-collector-alerts)
- `dashboard/src/ccsync_dashboard/sessions.py:311-326`: `prune` still deletes only on the ABSOLUTE lifetime, never the 12 h idle one, so CR-285Z's "dead rows hide live ones" premise is only half closed - `list_all` orders by `last_seen DESC`, which is what actually saves it. (dash-db)
