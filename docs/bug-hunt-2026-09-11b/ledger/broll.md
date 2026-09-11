## The b-roll web app, 2026-09-11 (CR-261)

Seven findings, all of them against fixes that landed earlier the same day:
the retry button that finally dispatched to the right route but with the one
field that makes the claim useless, the two ways its failures reached the
editor as fiction, and the ledger migration whose hardening stopped one branch
short of the branch that creates the file.

### CR-261a (comp-broll-music-1) - RETRY FAILED claimed the batch with no staging id, so every clip in it failed at once - FIXED (`broll/web/static/ingest.js`)

This afternoon's broll-1 fix re-pointed [ try the N failed again ] at the
loopback's `/broll/ingest/run` with `{batch_uid, staging_id: null}`. The
companion populates an item's `local_path` in exactly one place -
`_item_from_manifest` matches the server's manifest rows against the items of
`self._staging[staging_id]` - and `run()` only looks a staging entry up when
`staging_id` is truthy. With `null`, every item of the re-claimed batch was
built with `local_path: ""`, `_crunch_item` failed it immediately ("the source
file is not on this computer any more"), twice each up to MAX_ITEM_ATTEMPTS,
and `_maybe_finish` released the batch failed - while the page toasted "3
clips queued again." in success green. Pressing the button again repeated it
exactly, so a drop whose bytes were still sitting in staging was
unrecoverable without re-dropping the files. The music half of the same fix
pass got this right on the same day: `music/web/static/ingest.js` sends
`{batch_uid, staging_id: mi.stagingId}` guarded by `uid === mi.batchUid &&
mi.stagingId`. The b-roll page now sends the same thing under the same guard:
this page's own staging id when it is still the batch this page staged, and
`null` otherwise, which is the take-over case and is what that call has always
meant.

### CR-261b (broll-1) - the 409 branch printed the one sentence that is almost always false, and then set the panel running on a dispatch that failed - FIXED (`broll/web/static/ingest.js`)

The same fix added `if (e.status === 409)` -> "Another of your computers is
still working on this batch, so it picks them up." By construction that is the
one 409 that cannot arrive: `run()` answers "this computer is already indexing
another batch" FIRST, ahead of the enabled check, the identity checks and any
claim, and the server's `retry-failed` route (broll-5, same commit) refuses
the call outright while another machine holds a live lease. So the editor
indexing batch B who pressed retry on batch A was told to wait for a machine
that was never told anything - nothing polls for queued batches, the discovery
route went in the same commit - while A sat in `queued` holding its
archive-name reservations, which is the BROLL-8 state the whole feature exists
to prevent. The companion's own sentence was in `e.message` and was thrown
away. It is shown now, and the dispatch failing no longer sets
`ing.running`/starts the live poller: a panel polling a run that does not
exist is the same lie in a second place. The toast on that path is a warning,
not success green.

### CR-261c (broll-2) - the held-batch refusal reached the editor as "[object Object]" - FIXED (`broll/web/static/app.js`)

`retry_failed` raises `HTTPException(409, {...})` with a DICT detail, so the
body is `{"detail": {"detail": "EDIT-01 is still working on this batch. Stop
it first, ...", "reason": "held", ...}}`. `fetchJson` did `new Error(body.detail
|| body.message)`, and `Error.message` of an object is the string "[object
Object]" - which is what the red toast said, in place of the one sentence that
tells the editor which computer to go and stop. `fetchJson` now unwraps an
object detail once, centrally (the same file's batch-create handler had been
working around this by hand since 2026-08-18), and keeps the whole object on
`err.body` for the callers that read `reason`. The new test asserted `"EDIT-01"
in r.text`, which passes on the raw JSON and proves nothing about what is
rendered; the one here runs the page's own `fetchJson` over that exact body.

### CR-261d (broll-3, regression-14) - the ledger's CREATE half was still the crash-unsafe shape broll-2 fixed the ALTER half of - FIXED (`broll/web/app/client_folders.py`)

broll-2 hardened the v1 -> v2 step this morning (IMMEDIATE lock, column probe,
idempotent backfill) and left the `version == 0` branch above it exactly as it
was: `conn.executescript(_SCHEMA)`, which commits any open transaction and
then runs in autocommit, so each CREATE was durable the instant it ran while
`PRAGMA user_version = 2` was the last statement of the script. The identical
"durable DDL, un-stamped version" shape. A container killed or OOM-ed inside
the first request that creates `client_shares.db` - a bind-mounted file on a
spinning pool - left tables at version 0, and every later entry re-ran the
script and raised `table client_folders already exists`, for ever, on every
client-folder route and every public `/broll/share/<token>/` link. And the new
`except sqlite3.Error` in `get_shares_db` then SWALLOWED that, so the cure
(hand-deleting a file on the NAS) was documented nowhere and the symptom was a
500 with one container log line. The create now runs inside the same `BEGIN
IMMEDIATE` with the version stamped inside it (a `user_version` write goes
through the pager and rolls back with the DDL), statement by statement because
`executescript` cannot be in a transaction, and every CREATE is IF NOT EXISTS
so a file the old code already left on a customer's NAS finishes rather than
raising. regression-14, same function: that swallow caught `sqlite3.Error`
only, while `ensure_schema` opens with a `mkdir` and a `sqlite3.connect` that
raise OSError - which is exactly what an unmounted or read-only dataset
raises, the failure most likely to reach a handler whose whole job is keeping
the public share door open. It catches OSError too now. The deliberately fatal
"newer user_version" RuntimeError still is not caught.

### CR-261e (broll-5) - a ledger problem at BOOT degraded the whole /broll mount, which the same fix said must not happen - FIXED (`broll/web/app/main.py`, `broll/web/app/client_folders.py`)

broll-2 guarded `ensure_schema` on the request path only ("a sqlite failure
HERE is not allowed to take the public share door out"). Both boot paths still
called it bare. Under the dashboard the exception was caught a level up and
the whole /broll mount was marked DEGRADED - nav link hidden, home page saying
"every /broll request will fail until the data root is writable" - which after
that same fix is FALSE: every request works. Standalone, `uvicorn app.main:app`
did not boot at all. A ledger locked for longer than the busy timeout exactly
as the container starts is a real possibility now that the migration takes
`BEGIN IMMEDIATE`. There is one way to call it from anything but a test now,
`ensure_schema_best_effort()`, which logs and answers whether it worked, and
`main.py`'s lifespan uses it. Client folders are one feature of this app and
do not get to take the archive's search page down with them. The dashboard's
`_init_broll_storage` is the other boot path and is owed below.

### CR-261f (broll-6) - a failed backfill still stamped the schema version, so those items lost the hash identity for ever - FIXED (`broll/web/app/client_folders.py`)

`_backfill_hashes` returns on any `sqlite3.Error` - an unreadable `broll.db`
is the realistic one, and `publish_db.py` renames a new index over the live
file - and `ensure_schema` then wrote `PRAGMA user_version = 2` regardless. The
step was never retried and those items kept `hash = ''`: the third identity,
the one that survives an `/api/ingest/moved` rename, permanently and silently
absent for every clip curated before v2. The next index publish that renames
one of them drops it out of the client's folder page. The backfill now reports
whether it ran to the end (OSError counted as a failure too, and logged rather
than swallowed) and the version is stamped only when it did. A missing
`broll.db` is not a failure - there is nothing to read hashes out of, and
holding a deployment at version 1 waiting for one would be worse.

### CR-261g (broll-4) - the deleted discovery route left its login-gate carve-out behind, and the test asserted the opposite - FIXED (`broll/web/app/routes_fleet.py`, `broll/web/tests/test_bug_hunt_2026_09_11_broll.py`)

broll-3 deleted `GET /api/fleet/ingest/batches` this morning and left
`_broll_fleet_list_re` in the dashboard's `login_gate`, so
`/broll/api/fleet/ingest/batches` is still admitted with no session - onto a
404 today, and onto whatever collection GET lands there next, session-gated in
its author's head and not in fact. The regression test written beside it
pinned the claim that the gate "was widened in the same commit", a wrong fact
about a security gate held in place by a green test, which is the very thing
its own docstring says gets a correct gate "fixed". The test now says what
happened and asserts that `routes_fleet.py` - the file that owns the path
shape - records why the carve-out is gone. Deleting the carve-out itself is
one line in `app.py` and is owed below; nothing on this side depends on it,
and this side has no GET at that path for it to expose.

### Verification
Run from `broll\web` with `.venv\Scripts\python.exe -m pytest <file> -q`.

- `tests/test_bug_hunt_2026_09_11b_broll.py::test_retry_failed_hands_the_companion_this_pages_staging_id` -> fails at f1eeb42, passes now
- `tests/test_bug_hunt_2026_09_11b_broll.py::test_retry_failed_sends_no_staging_id_for_someone_elses_batch` -> the guard; passes either way by design (it pins the case that must STAY null)
- `tests/test_bug_hunt_2026_09_11b_broll.py::test_a_busy_companion_is_quoted_and_the_panel_does_not_start_polling` -> fails at f1eeb42, passes now
- `tests/test_bug_hunt_2026_09_11b_broll.py::test_a_held_batch_reaches_the_editor_as_a_sentence` -> fails at f1eeb42 ("[object Object]"), passes now
- `tests/test_bug_hunt_2026_09_11b_broll.py::test_a_kill_inside_the_create_leaves_nothing_behind` -> fails at f1eeb42, passes now
- `tests/test_bug_hunt_2026_09_11b_broll.py::test_a_ledger_created_by_the_old_code_still_finishes` -> fails at f1eeb42 ("table client_folders already exists"), passes now
- `tests/test_bug_hunt_2026_09_11b_broll.py::test_a_backfill_that_failed_is_not_retired_by_the_version_stamp` -> fails at f1eeb42, passes now
- `tests/test_bug_hunt_2026_09_11b_broll.py::test_the_share_door_survives_a_data_root_that_went_read_only` -> fails at f1eeb42 (PermissionError out of the dependency), passes now
- `tests/test_bug_hunt_2026_09_11b_broll.py::test_a_ledger_problem_at_boot_does_not_degrade_the_whole_mount` -> fails at f1eeb42, passes now
- `tests/test_bug_hunt_2026_09_11b_broll.py::test_the_standalone_boot_uses_the_best_effort_call` -> fails at f1eeb42 (the lifespan raises), passes now
- `tests/test_bug_hunt_2026_09_11_broll.py::test_the_fleet_docstrings_do_not_claim_the_gate_needs_widening` -> fails at f1eeb42 on the corrected assertion, passes now

The three page tests RUN the page: `app.js` + `ingest.js` load in a bare V8
(ingest.js touches the DOM only inside functions, which
`test_ingest_ui.py`'s sanitiser-parity test already relies on) and
`ingestRetryFailedBatch` is called for real with `fetch` and the loopback
stubbed, so what is asserted is the body that goes to 8899 and the string the
editor is shown - not a source scan.

Also run, because they read the two files I edited and the module I changed:
`tests/test_client_folders.py`, `tests/test_ingest_retry_and_takeover.py`,
`tests/test_ingest_ui.py`, `tests/test_no_em_dashes.py`,
`tests/test_mounted_prefix.py`, `tests/test_one_vocabulary.py` - 153 passed.
`py_compile` on the three .py files, `node --check` on both .js files.

### OWED TO ANOTHER TERRITORY
- dash-core: `dashboard/src/ccsync_dashboard/app.py`: `login_gate`: delete `_broll_fleet_list_re` (line ~1075) and the `request.method == "GET" and _broll_fleet_list_re.match(path)` clause (~1176-1178) with its comment - the route it carved out for was deleted this morning (broll-3), so the gate opens an unauthenticated collection path onto nothing. No deploy order: both halves are the dashboard image, and the b-roll side has no GET at that path either way.
- dash-mounts-ui: `dashboard/src/ccsync_dashboard/broll.py`: `_init_broll_storage` (last statement, ~line 568): call `client_folders.ensure_schema_best_effort()` instead of `client_folders.ensure_schema()`, so a ledger that cannot be opened at BOOT degrades client folders and not the whole /broll mount (broll-5). Guard it for a `broll/web` checkout older than this change (`getattr(client_folders, "ensure_schema_best_effort", client_folders.ensure_schema)`): `BROLL_WEB_SRC` can point at a tree the image did not ship. b-roll web deploys with the dashboard, so no cross-release order.
- comp-broll-music: `companion/src/ccsync_companion/broll_ingest.py`: `run()`: belt and braces for CR-261a - refuse (409, with a sentence) a claim whose manifest yields zero `local_path`s while this machine DOES hold a staging entry for that batch, rather than claiming it and failing every item. The page half is fixed and shipped independently; this only protects a stale page (a browser tab cached before this build) from spending a batch's attempts. Companion side alone, no order.
- dash-collector-alerts: OPTIONAL, low: a `notices` row when `client_shares.db` cannot be opened (`kind = "client_shares_unreadable"`), so a swallowed ledger failure says so on the home page rather than in one container log line. Both swallow points (`get_shares_db`, `ensure_schema_best_effort`) log with `log.exception` today. Needs a notice kind WITH its writer, which is dash-collector-alerts' rule.

### Owner decisions
- The 409 branch that said "another of your computers picks them up" is gone rather than re-aimed. The case it describes cannot reach it (the server route refuses a held batch before the loopback is called), so the honest thing was to quote the companion. If that sentence is wanted for the server's held-batch 409, it belongs on the `toast` in the first catch block, which now shows the route's own wording ("EDIT-01 is still working on this batch. Stop it first, then try the failed clips again.") - which says the same thing and names the machine.
- The retry dispatch still uses `/broll/ingest/run`, not `/broll/ingest/retry` (which the music page uses and which `broll_server.py` already accepts for both kinds). `run` works on every companion in the field; the `batch_uid` branch of `/retry` only exists in builds carrying this morning's music-2 fix, and an older one would answer 200 with nothing claimed - the exact failure broll-1 was written to kill.
- `CREATE TABLE IF NOT EXISTS` means a ledger left half-created by the OLD code is completed rather than raising, but a table that got created with a wrong shape (only possible from a hand-edited file) would be kept as it is. Permanent 500s on every client link is the worse of the two.

### Hand-off wave

#### CR-261h (broll-4's third wrong fact) - the corrected note described the gate as still open - FIXED (`broll/web/app/routes_fleet.py`, `broll/web/tests/test_bug_hunt_2026_09_11_broll.py`)

broll-4 was about a wrong fact in this file's own comment: a security gate
described as needing to be WIDENED when it did not. The correction written
this morning carried a third one, in its tense. It says the carve-out "still
admitted an unauthenticated GET ... onto a 404 today" - written while
dash-core was deleting `_broll_fleet_list_re` from `login_gate` in the same
pass (security-2, CR-257h). The paragraph now reads as history and names the
change that closed it, and says what IS true today: only `_broll_fleet_re`
(the POST carve-out these routes need) remains, so a GET route added here
would be behind the session gate like everything else. Same reason as
broll-4 itself: a file that describes a gate as open when it is shut is how
the next reader re-opens it to match the comment.

### Verification (hand-off wave)

From `broll/web` with `.venv\Scripts\python.exe -m pytest`:

- tests/test_bug_hunt_2026_09_11_broll.py::test_the_fleet_docstrings_do_not_claim_the_gate_needs_widening -> fails on the wave-1 source (neither "security-2" present nor "onto a 404 today" absent), passes now
- The two earlier assertions (the broll-4 wording) are unchanged and still green.

### OWED TO ANOTHER TERRITORY (hand-off wave)

- none. dash-core's half is already done (security-2, wave 1); this is the
  b-roll side catching up with it.

### Owner decisions (hand-off wave)

- none.
