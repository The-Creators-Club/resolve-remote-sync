# verdicts - dash-core-collector

Group: `dash-core` + `dash-collector-alerts`. Read-only pass over
`app.py`, `secrets_boot.py`, `oidc.py`, `sessions.py`, `collector.py`,
`notices.py`, `health.py`, `db.py` and the companion's `lane_guard.py`, plus
one scratchpad snippet against `collector.detect_moves` from the dashboard
venv. `grep -an` of KNOWN_BUGS.md found no open entry covering any of the
twelve.

## dash-core-1
- Verdict: DOWNGRADED to medium
- Duplicate of: none (same ROOT CAUSE as dash-core-6 - one non-atomic
  `_write_secret_file` - so one fix closes both)
- Reasoning: the mechanism is exactly as reported and I could not refute it.
  `check_persisted_secrets` (app.py:544-552) asks only
  `(directory / name.lower()).is_file()`, `_write_secret_file`
  (secrets_boot.py:91-100) is `os.open(O_WRONLY|O_CREAT|O_TRUNC)` + `fh.write`
  with no temp file, no `os.replace` and no `fsync`, and `ensure_secrets`
  swallows the `OSError` (secrets_boot.py:218-223) while keeping the in-memory
  value. `_read_secret_file` (secrets_boot.py:113-117) `.strip()`s, so a
  zero-byte or whitespace file reads as `""` and the next boot mints a
  different secret - the refusal's whole point defeated. I downgrade only on
  probability: the common DCORE-3 case (a `/data` this process does not own,
  a read-only dataset) fails at `open`/`mkdir` and leaves NO file, which the
  existing check does catch; reaching the zero-byte state needs a create that
  succeeds and a flush that does not (ENOSPC on an appliance whose `/data` is
  full, a kill or power loss between `write` and the page cache reaching
  disk - the missing `fsync` makes the crash case real even when `close`
  returned cleanly). The blast radius when it does happen is genuinely
  fleet-wide (every `cce1.` identity token and every browser session), which
  is why this is medium and not low.
- Evidence: code read above; `grep -an` of KNOWN_BUGS.md for "secret file"
  and DCORE-3 shows only the 2026-09-04 entry, which covers the absent-file
  half. `dashboard/tests/test_secrets_boot.py` asserts existence and mode
  only - no test pins non-empty content, so a fix breaks no test.
- Fix note: the suggested fix is right and is the cheap one (five secrets,
  once per boot). Do BOTH halves: atomic write (temp + `fsync` + `os.replace`,
  with the 0600 mode set on the temp fd before the rename so the secret is
  never briefly world-readable) AND a content comparison in
  `check_persisted_secrets`. Other files a fix must touch:
  `secrets_boot.write_secret_file`'s docstring already promises one
  implementation for `ai_providers.write_secret_file`, so that caller inherits
  it; `dashboard/tests/test_secrets_boot.py` and `tests/test_app_boot*`/
  `test_setup_engine.py` (which call `ensure_secrets` with tmp dirs) should be
  re-run because the temp file appears in `<data>/secrets` listings any test
  may assert on. Note the `.tmp` sibling must be created inside the same
  directory (same filesystem) or `os.replace` is not atomic.

## dash-core-2
- Verdict: UPGRADED to high
- Duplicate of: dash-api-2 (rated high, same handler) and dash-db-3; three
  hunters found this independently, so it should be filed once
- Reasoning: confirmed, and worse than the hunter argued. The
  `notices.is_db_busy` branch (app.py:1350-1365) opens `db.connect(...)` with
  the DEFAULT `busy_ms=BUSY_TIMEOUT_MS` (db.py:686, 5000) and then does a
  SELECT (`_seen_before`), an INSERT/UPDATE (`db.notice`) and a
  `conn.commit()` - a write against the database whose lock the request just
  failed to get. The additional fact the hunter missed: `unhandled_error` is
  an `async def` exception handler (app.py:1318), so that blocking sqlite
  call runs ON THE EVENT LOOP, not in a threadpool worker. Under contention
  every other in-flight request in the process stalls behind it for up to 5 s,
  which turns a per-request delay into a whole-dashboard stall on a
  `workers=1` container. That, plus dash-api-2's independent finding of the
  same defect, is what moves it to high.
- Evidence: `async def unhandled_error(request, exc)` at app.py:1318 with the
  synchronous `db.connect`/`record_db_busy`/`conn.close()` inline;
  `record_db_busy` ends in `conn.commit()` (notices.py:1150);
  `connect(path, *, busy_ms=BUSY_TIMEOUT_MS)` at db.py:690 and the handler
  passes none. `tests/test_db_busy_2026_09_17.py`'s handler test raises from a
  route with no lock held, so it cannot see either problem.
- Fix note: the suggested `busy_ms=200` is the right minimum, but it does not
  fix the event-loop block - do it in `run_in_threadpool` (or hand the record
  to the collector) as well. The SAME shape sits ten lines below in the
  `record_server_error` branch and in `api.py:9402-9408`'s slow-write write,
  so a fix should cover all three; `tests/test_db_busy_2026_09_17.py` pins the
  503 body and `Retry-After`, neither of which changes.

## dash-core-3
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: the missing shape check is real - `username_from_claims`
  (oidc.py:280-294) refuses only `@`, `/` and `\`, while `db._USERNAME_RE`
  (db.py:615) and `local_users._USERNAME_RE` (local_users.py:64) gate four
  write paths on `^[a-z][a-z0-9._-]{0,31}$`. But I can refute most of the
  reach: `require_fleet_member` (oidc.py:309-353) falls through to
  `username not in _known_usernames(settings)` and those names come from the
  database, which can only hold regex-clean ones, so a malformed claim is
  already 403'd on the DEFAULT OIDC deployment. The bug only bites when the
  admin configures `DASH_OIDC_ALLOWED_GROUPS` (or admin-by-claims, or a fleet
  with zero known editors), i.e. an optional deployment plus a
  `DASH_OIDC_USERNAME_CLAIM` pointed at a display-name claim. The outcome is
  then a confusing half-working session, not a privilege gain (a shape the
  regex rejects can never collide with a real editor's row). Config-dependent,
  no data loss, no security effect: low.
- Evidence: oidc.py:288 is the entire shape test; oidc.py:341-353 is the
  known-usernames gate; `_known_usernames` reads the DB. `tests/test_oidc.py`
  pins only the `@`/`/` refusals.
- Fix note: the suggested fix is right and cheap. Import the regex from one
  place rather than adding a third copy (db.py, local_users.py and
  `nas.base.USERNAME_RE` already say they mirror each other), raise
  `OidcError` so the existing callback error page renders it, and add a case
  to `tests/test_oidc.py`. Check nothing in the SMB path relies on a laxer
  shape before sharing the constant.

## dash-core-4
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `_open_path(path)` (app.py:144-147) tests the path alone and
  `login_gate` calls it before any method test, so the comment's "GET only"
  at app.py:137-139 is an assertion the code does not make. I tried to refute
  it on exploitability and agree with the hunter that it is not exploitable
  today: the dashboard's own routes at those names are GET-only (405), the
  Cards mount answers 404/405, and the CSRF gate still applies. It stays a
  finding because the invariant is documented and unenforced, which is how the
  next handler at one of those names inherits an unauthenticated door.
- Evidence: the signature `def _open_path(path: str) -> bool` and the
  `_OPEN_PATTERN` regex at app.py:139-142; contrast the method-explicit
  carve-outs in the same middleware (`... and request.method == "GET"`).
- Fix note: the suggested `_open_path(path, method)` is right, but note
  `_OPEN_EXACT` also carries `/login` and `/api/v1/login`, which are POST
  targets - do NOT blanket-require GET for the whole set, only for the static
  members and the pattern, exactly as the hunter says. `tests/test_auth.py`
  and any test hitting `/login` with POST are the ones that would catch a
  careless version.

## dash-core-5
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: verified by grep - `session_store.prune()` and `prune_attempts()`
  appear only at app.py:720-721, inside the lifespan, and `collector.py:2114`
  calls `db.prune` but nothing for `auth_sessions`. `validate()`
  (sessions.py:220-224) deletes only the row whose cookie is presented after
  expiry, so a device that never returns leaves its row for ever. The impact
  is modest on a fleet this size (a handful of editors times devices), which
  is why low is right: `list_all(limit=200)` is the only place it becomes
  user-visible, and that needs 200 dead rows.
- Evidence: `grep -rn "prune()\|prune_attempts" src/ccsync_dashboard/*.py`
  returns the two lifespan lines only.
- Fix note: right fix, and the cheapest place is the collector cycle that
  already calls `db.prune(conn, ...)` at collector.py:2114. Watch the
  connection: `SessionStore` has its own `_write_lock` and its own connection
  with `BUSY_TIMEOUT_BACKGROUND_MS`, so call `store.prune()` (the store's
  method) from the collector rather than issuing the DELETE on the collector's
  conn, or two writers fight over the same table.

## dash-core-6
- Verdict: CONFIRMED (low)
- Duplicate of: none (shares dash-core-1's root cause: one helper, one fix)
- Reasoning: `_write_sidecar_env_files` (secrets_boot.py:263-292) calls the
  same `O_TRUNC`-in-place `_write_secret_file` on every boot, so the window is
  hit once per restart rather than once per install. The missing `fsync` makes
  the host-power-loss case real even for a write that returned cleanly, and
  the reader (the sftp sidecar) reads `internal.env` only at its own startup.
  A truncated `CCSYNC_INTERNAL_TOKEN` reproduces the dash-admin-2 outage from
  a different direction, with only a `log.warning` anywhere.
  Low is right: the write is under 100 bytes and the whole path is best-effort
  by design.
- Evidence: the `try:` block at secrets_boot.py:280-292 writes
  `syncthing.env` and `internal.env` then `unlink`s `sftp.env`, all inside one
  `except OSError -> log.warning`, so a partial failure also leaves the
  cleanup half-done.
- Fix note: fix it in `_write_secret_file` (temp + `fsync` + `os.replace`) and
  both findings close at once; `write_secret_file`'s docstring already names
  this as the intent, so `ai_providers`'s AI keys come along. Nothing else on
  the wire: the sidecars only read the file. Re-run
  `tests/test_secrets_boot.py` and `tests/test_setup_engine.py`
  (`_run_secrets` writes these same files through the narrow mapping).

## dash-collector-alerts-1
- Verdict: DOWNGRADED to medium
- Duplicate of: none
- Reasoning: the mechanism is exactly right and I could not refute it.
  `_record_inventory` selects `min(window, n)` projects through a rotating
  cursor (collector.py:1663-1666, `inventory_projects_per_cycle = 8`), builds
  `diffs` only from the projects walked in THIS pass, and calls
  `db.replace_nas_media` (collector.py:1706-1713) - which destroys the only
  record of the old paths - before `_record_detected_moves` runs on that pass's
  walks alone. `_matched_pairs`'s own docstring says the cross-project case is
  why it looks at all the walks at once; nothing guarantees the two halves are
  in one pass once the fleet has more than 8 active projects. The collapse-brake
  `else` branch has the same permanent-loss shape. I downgrade because the
  failure mode is "a best-effort convenience does not fire", leaving the fleet
  in exactly the state it was in before this feature existed (CR-267a's
  behaviour) - it is a missed detection, not a new corruption. What keeps it
  at medium rather than low is the unconditional
  `db.mark_notice_checked(conn, "file_move_detected", now)` at
  collector.py:1746, which reports the check as having RUN for a pass that
  could not possibly have seen the move.
- Evidence: `selected = [active[(start + i) % n] for i in range(min(window, n))]`;
  note that with n <= 8 every project is in every window, so this studio's own
  fleet shape (well over 8 active projects) is the precondition. The suite's
  `test_a_move_between_two_projects_is_matched_across_the_pass` hands
  `detect_moves` both walks already in one list - the precondition the
  collector does not guarantee - and the end-to-end test uses a two-project
  fixture.
- Fix note: of the hunter's three options, the persisted-pending-halves table
  is the only one that scales (forcing a full-fleet walk before any
  replacement re-introduces the exact os.walk-inside-a-write-transaction
  problem the docstring at collector.py:1634-1638 exists to prevent, and a
  full walk of the tree per pass is what the rotating cursor was added to
  avoid). A fix touches `db.py` (a new table plus a schema version bump - the
  next free one after v53 - and a retention clause in `db.prune`),
  `collector.py`, and `tests/test_hand_moves_detected.py`, which currently
  pins the one-pass shape.

## dash-collector-alerts-2
- Verdict: CONFIRMED (medium)
- Duplicate of: none (compounded by dash-collector-alerts-3, which multiplies
  a single folder rename into hundreds of rows and so makes the cap reachable)
- Reasoning: confirmed by reading order. `moves = moves[:DETECTED_MOVE_LIMIT]`
  at collector.py:1755 runs after the `for pid, slug, rel, rows, sig, n_dirs in
  walked:` loop at collector.py:1706-1713 has already called
  `db.replace_nas_media` for every walked project, so the discarded remainder
  has no surviving `old` side on any later cycle: the log line "the rest are
  picked up on later cycles" is false. I verified the truncation is
  alphabetical - `detect_moves` ends in
  `sorted(moves, key=lambda m: (m.from_slug, m.from_rel))` (collector.py:2442) -
  so what survives is arbitrary with respect to importance. Nothing writes a
  notice for the remainder, so the only trace is a container log a recreate
  discards.
- Evidence: line ordering above; `DETECTED_MOVE_LIMIT = 500` at
  collector.py:2214.
- Fix note: the hunter's first option (do not replace the inventory for the
  projects whose moves were dropped) is the better one but is not a one-liner:
  the replacement has already happened by the time the cap is known, so it
  means either deferring `replace_nas_media` until after `detect_moves` (which
  reorders phase 2 and must keep every walk before the first write) or
  re-writing the previous rows back. The notice half is cheap and should ship
  either way - and it needs `db.NOTICE_KINDS` to gain a registered kind, per
  dash-collector-alerts-5's rule. `tests/test_hand_moves_detected.py` has no
  cap test to break.

## dash-collector-alerts-3
- Verdict: CONFIRMED (medium)
- Duplicate of: none
- Reasoning: reproduced. `_folder_move` (collector.py:2360-2378) derives the
  candidate folder from the shared SUFFIX only and then iterates
  `range(shared, 1, -1)`; for a leaf-folder rename the only shared component
  is the basename, so `shared == 1`, the range is empty and every file falls
  through to the per-file loop. The doc promise (HAND_MOVES_ON_THE_SERVER.md
  section 7 phase 1) is a folder row per folder. Medium is right because the
  moves are still detected and applied correctly - the damage is 300
  `file_moves` rows, 300 command entries per holding machine, a flooded MOVES
  history, and the interaction with the 500 cap in finding 2, which turns a
  600-file rename into silent data loss.
- Evidence: my own snippet from `dashboard/.venv` against
  `collector.detect_moves` (scratchpad, outside the repo):
  `B-roll/ -> Broll/` with two originals and one proxy gives
  `B-roll/A001.braw -> Broll/A001.braw is_dir=False` and
  `B-roll/A002.braw -> Broll/A002.braw is_dir=False`, whereas the same three
  files moved to `Archive/B-roll/` give one row
  `B-roll -> Archive/B-roll is_dir=True n_files=3`. So the hunter's claim
  holds exactly, and the existing test
  `test_a_whole_folder_is_one_row_not_one_per_file` only covers the second
  shape.
- Fix note: the suggested prefix-derived candidate is right and the safety bar
  stays in `_folder_members`, which already refuses if anything under the old
  folder did not move or anything stayed behind. Two things a fix must keep:
  the `Proxy` refusal at collector.py:2367-2372 (the button refuses a Proxy
  folder at either end) and the fact that a depth-1 suffix candidate would
  otherwise name the FILE, not a folder - hence prefix, not a widened range.
  Add the rename case to `tests/test_hand_moves_detected.py`.

## dash-collector-alerts-4
- Verdict: CONFIRMED (medium)
- Duplicate of: dash-db-1 ("a collector poll that held no write lock at all is
  recorded as the writer that held it, for ever"); `api.py:9402-9408` is the
  same question for `api_report` and is dash-api's
- Reasoning: `_timed` (collector.py:469-500) starts `clock_started` before
  `fn(conn)` and files `record_slow_write` when the whole poll exceeds
  `db.BUSY_TIMEOUT_MS / 1000.0`. `_record_inventory`'s own docstring
  (collector.py:1634-1638) states that every filesystem walk happens BEFORE the
  first write precisely so no lock is held during it, and the Syncthing poll
  spends its time in HTTP. sqlite3's default isolation opens no transaction on
  reads, so the pre-write portion holds nothing. The notice body
  (notices.py:1164-1169) asserts the poll "held the database's write lock for
  longer than a request waits" as fact, and its fix text sends the operator
  after the wrong thing - worse, `record_db_busy`'s fix text tells them to
  cross-reference "a slow write from the same minute", which will now point at
  an innocent walk. Nothing clears these notices automatically.
- Evidence: the two timing lines plus `SLOW_POLL_SECONDS = 1.0`
  (collector.py:117) and `BUSY_TIMEOUT_MS = 5000` (db.py:686);
  `tests/test_db_busy_2026_09_17.py` calls `record_slow_write` with a made-up
  duration and never asserts a lock was held.
- Fix note: the suggested fix (time the write burst, or give whole-poll timing
  its own wording) is right. The cheapest honest version is the wording change
  plus a separate timer around phase 2; a fix must touch `notices.py`'s body
  string, `collector.py:488-500`, `api.py:9402-9408` (the other caller, whose
  wall-clock includes the report parse) and
  `tests/test_db_busy_2026_09_17.py`, which pins the current sentence.

## dash-collector-alerts-5
- Verdict: CONFIRMED (low)
- Duplicate of: dash-db-2 (same two kinds, same registry)
- Reasoning: `grep -n '"db_busy"\|"slow_write"' db.py` returns nothing, so
  neither kind is in `NOTICE_KINDS` while both have writers in `notices.py`.
  The consequences are as described and I verified the rendering path:
  `ui.py:1848-1852` titles a row with `kind_what.get(kind, "") or kind`, so an
  unregistered kind renders its raw key, and `db.notice_href` has no entry, so
  no [ TAKE ME THERE ]. Their sibling `server_error` IS registered
  (db.py:3300), and `tests/test_sweep_2026_09_04_dashboard.py:161-171` pins
  exactly this convention for the kinds that wave added - note that test names
  its own two kinds explicitly, so it does not fail for these, which is how
  they were missed.
- Evidence: greps above; the test body read in full.
- Fix note: the suggested fix is right. Note the second half of it (stamp
  `mark_notice_checked` from the poll) is what stops the checks panel reading
  [ NOT CHECKED ] for ever on a healthy server - CLAUDE.md's "register a kind
  WITH its writer" rule cuts both ways. Touches `db.py` (NOTICE_KINDS,
  `notice_href`), `collector.py` or `notices.py` for the stamp, and whichever
  test asserts the registry's size if one does.

## dash-collector-alerts-6
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `_disk_floor_hit` (health.py:284-297) compares against the module
  constant `DISK_RED_FREE_BYTES = 20 GB` (health.py:259) while the companion's
  floor is `_cfg_int(cfg, "lane_b_min_free_bytes", DEFAULT_LANE_B_MIN_FREE_BYTES)`
  (lane_guard.py:954, default 20 GB, documented as a config key at
  companion `config.py:235`/`:945`). I tried to refute it as unreachable,
  since the comment at health.py:692-693 says the branch is only for builds
  too old to send `blocked_reason` and the whole fleet is on 0.9.74 - but
  `_second_cause` (health.py:774-785) also feeds `disk_red` into the live map
  unconditionally, so a current machine reporting `paused` can still pick up a
  false "disk_full" second cause. Low is right: it needs an editor to have
  overridden the key, which nobody in this fleet has.
- Evidence: `grep -rn "lane_b_min_free" companion/src/ccsync_companion/*.py`
  finds it only in `config.py` - the reporter sends no floor value, so the
  dashboard genuinely has nothing to read.
- Fix note: the suggested fix is right and it is a WIRE change: the companion
  must add the effective floor to its report payload (reporter + the
  dashboard's report schema and `machine_state`/why-block reader), with the
  20 GB constant kept as the fallback for builds that do not send it. Deploy
  the dashboard first, per the repo's standing rule. Given the cost of a wire
  change for a low, the cheaper honest alternative is to soften the sentence
  when the floor is unknown.

## Cross-cutting notes
- dash-core-1 and dash-core-6 are one fix in `secrets_boot._write_secret_file`.
- dash-core-2, dash-api-2 and dash-db-3 are one defect in `app.py`'s
  `unhandled_error`; dash-api-2 carries the event-loop detail and is the one
  to keep.
- dash-collector-alerts-4 and dash-db-1 are one defect; -5 and dash-db-2 are
  one defect.
- dash-collector-alerts-1, -2 and -3 all sit in `_record_inventory`/
  `detect_moves` and should be fixed as one change: -3 makes -2 reachable, and
  -2's better fix reorders the same phase -1's fix touches.
