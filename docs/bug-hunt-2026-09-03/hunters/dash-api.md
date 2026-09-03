# dash-api — dashboard/src/ccsync_dashboard/api.py: auth gates, report reply, selections/ticks, file moves, packages, jobs

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/api.py` — ~90% (every route decorator + gate,
  the whole report handler and its reply, selections/tick/untick, file moves +
  undo/reissue/reconcile, packages publish/current/delete/download, fleet halt,
  machine admin routes, jobs block, diagnostics).
- `dashboard/src/ccsync_dashboard/auth.py` (identity/session token readers),
  `app.py` (login_gate, csrf_gate, body_size_gate, `_OPEN_EXACT`),
  `db.py` (selections, fleet halt, file moves, queue_depth, media_rel_key,
  base_machines/base_only_editors, mark_file_move_applied), `jobs.py`
  (offers_for_machine, target_refusal), `ui.py` (the htmx twins of the halt and
  the tick).
- Companion side, read-only: `companion/src/ccsync_companion/reporter.py`,
  `app.py` (the `commands.*` readers), `jobs_runner.py`
  (`note_report_reply`, `wait_seconds`).
- Docs: CLAUDE.md, docs/API.md §6c, MULTI_MACHINE_PLAN.md, UPLOAD_ONLY_TICK.md,
  FILE_MOVES.md, SECRETS.md ("Rotating DASH_SESSION_SECRET"), KNOWN_BUGS
  (DASH-1/2/3, UX-8, UX-9, UX-11, REL-1..16, CR-28/45/49/55/76/85/86/90).

Tests run:
`dashboard\.venv\Scripts\python.exe -m pytest tests/test_api.py tests/test_file_moves.py tests/test_fleet_halt.py tests/test_jobs.py tests/test_jobs_contract.py tests/test_jobs_backpressure.py tests/test_auth.py -q`
-> **174 passed, 1 skipped** (baseline green; none of the findings below is
caught by the suite). Plus four ad-hoc `TestClient` scripts run from the
dashboard venv (in the scratchpad, not the repo) that reproduce findings 1, 2
and 4.

## Findings

### dash-api-1 — DASH_SESSION_SECRET rotation only works for `/report`: the selection, untick, diagnostics and fleet-job gates all reject a retired-key identity
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:2049` (`_require_selection_read`),
  `:2107` (`_require_selection_untick`), `:7880` (`api_diagnostics`),
  `:8241` (`_require_fleet_caller`) — all call
  `auth.read_identity_token(settings.session_secret, identity)` with the
  default `previous=()`; contrast `api.py:7236`, which uses
  `auth.read_identity_token_ex(settings, identity)` and therefore *does*
  consult `settings.session_secrets_previous`.
- What: DASH-2 added `DASH_SESSION_SECRET_PREVIOUS` as an accept-only key so a
  secret rotation does not 401 the whole fleet, and `docs/SECRETS.md` documents
  a drain window in which every companion keeps working on its old identity
  until its editor next signs in. Only `/api/v1/report` was wired to it. Every
  other companion-facing route that verifies an identity header still verifies
  against the current secret alone.
- Failure scenario: operator follows the SECRETS.md runbook (new
  `DASH_SESSION_SECRET`, old value in `DASH_SESSION_SECRET_PREVIOUS`) on a
  fleet still on the shared `DASH_REPORT_TOKEN` (the documented migration
  reality). Every companion keeps reporting 200 and the grid keeps moving —
  and simultaneously: `GET /api/v1/selection/{editor}` 401s, so no machine can
  learn a new or changed sync plan; the tray's untick-before-delete 401s;
  `POST /api/v1/diagnostics` 401s, i.e. the one artefact SYS-7 exists to
  deliver is dead exactly during the incident; and `POST /api/v1/jobs/claim`,
  `/heartbeat`, `/result` all 403, so a job already held by a machine cannot be
  heartbeated or completed — its lease expires and it is re-queued forever.
  None of this shows on the fleet grid, because reports are being accepted.
- Evidence: ad-hoc run against `create_app(Settings(session_secret=NEW,
  session_secrets_previous=(OLD,), report_token=T))` with an identity minted on
  `OLD`:
  ```
  report      : 200      (logged "reported with an identity signed by a RETIRED session key")
  selection   : 401 {"detail":"X-CCSync-Identity required (and must match the editor)…"}
  untick      : 401
  diagnostics : 401 {"detail":"X-CCSync-Identity required -- sign in from the companion tray"}
  jobs/claim  : 403 {"detail":"X-CCSync-Identity required - sign in from the companion tray"}
  ```
  Also `grep -n "read_identity_token("` in `api.py` returns exactly those four
  call sites and no `previous=` argument on any of them. Note the refusal
  messages are misleading too: the editor HAS signed in, and the token is
  valid — it is just signed with a key three of the four gates do not consult.
- Ledger: incomplete fix of **DASH-2** (KNOWN_BUGS ~line 5595, "consulted by
  `auth._read_token_any` for both purposes, so companion identities and browser
  sessions both survive a rotation" — that is true of the helper, not of these
  four callers). New as a finding.
- Suggested fix: give the four sites `auth.read_identity_token_ex(settings,
  identity)[0]` (or pass `previous=auth.previous_session_secrets(settings)`),
  and add a test that a retired-key identity can read a selection and post
  diagnostics, so the next gate added does not miss it either.

### dash-api-2 — [ UNDO THIS MOVE ] does not restore the original filename when the move also renamed the file
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:2608-2612` (`undo_file_move`:
  `to_dir = move["from_rel"].rsplit("/", 1)[0] …; body = FileMoveIn(path=move["to_rel"], to_slug=move["from_slug"], to_path=to_dir)`),
  consumed by `move_project_files` at `api.py:2470-2477` (`if dest.is_dir():
  dest = dest / src.name`).
- What: the inverse move is built from the *parent folder* of `from_rel` only,
  never from `from_rel` itself, so `move_project_files` falls into its
  "destination is a folder, so drop the file into it under its own name"
  branch — and "its own name" is `basename(to_rel)`, the name the forward move
  gave it. `FileMoveIn.to_path` is documented as "folder **or full path inside
  it**", i.e. a move may rename, and UX-11's promise ("you can put it back") is
  then not kept.
- Failure scenario: admin moves `B-roll/A001.braw` to `Selects/RENAMED.braw`
  (one action, move + rename), realises the mistake, clicks UNDO. The server
  ends up with `B-roll/RENAMED.braw`: right folder, wrong name, and the
  original name is gone from the tree. The per-machine `commands.file_moves`
  that fans out carries the same wrong destination, so every editor's local
  copy is renamed to match and Resolve is relinked to a path that never
  existed before. The original `A001.braw` is unrecoverable from the dashboard
  (the `file_moves` row records it, but nothing reads it back).
- Evidence: ad-hoc run (scratchpad `t_undo.py`) against a temp Projects tree:
  ```
  move: 200 … 'to': '2026/Base Drone/Selects/RENAMED.braw'
  tree after move:  ['2026/Base Drone/Selects/RENAMED.braw']
  undo: 200 … 'to': '2026/Base Drone/B-roll/RENAMED.braw', 'undo_of': 1
  tree after undo:  ['2026/Base Drone/B-roll/RENAMED.braw']   <- expected A001.braw
  ```
  `tests/test_file_moves.py::test_a_move_can_be_put_back` only exercises a
  move that does not rename, so the suite is green.
- Ledger: new (the UX-11 entry, KNOWN_BUGS ~6946, states the design as
  "`to_path=` the original's parent folder" — the rename case was not
  considered).
- Suggested fix: pass the full original path,
  `FileMoveIn(path=move["to_rel"], to_slug=move["from_slug"], to_path=move["from_rel"])`.
  The destination cannot exist (it was moved away), so `move_project_files`
  takes its exact-path branch and restores both folder and name; a directory
  undo behaves identically.

### dash-api-3 — the jobs queue-depth backpressure never engages: the dashboard omits `queue` exactly when the companion would back off
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:7818-7820`
  (`if depth["queued"] or depth["running"] or depth["pinned"]: block["queue"] = depth`)
  vs `companion/src/ccsync_companion/jobs_runner.py:315-322` (`wait_seconds`:
  `if offered or not depth: return base`).
- What: the two sides disagree about what an absent `commands.jobs.queue` key
  means. The dashboard sends the depth block *only when the queue is
  non-empty*; the companion treats a missing/empty depth as "cannot tell" and
  polls at the base interval. So the only state that can ever reach the
  backoff branch is "pinned > 0 while queued == 0 and running == 0" — a
  transient. CLAUDE.md states the invariant as "a queue depth on the report
  reply the companion backs off on — STOP ASKING, never stop working", and
  `jobs_runner.wait_seconds`'s own docstring names the case it is supposed to
  cover ("a fleet of eight machines waking up every 20 s to discover that is
  eight pointless wakeups a minute on eight editors' laptops"). That is the
  behaviour in the field today.
- Failure scenario: fleet with an empty job queue. Every companion's jobs
  thread wakes on `poll_seconds` for ever instead of stretching to
  `IDLE_BACKOFF_MAX_SECONDS`; the whole `IDLE_BACKOFF` path is dead code. (The
  cost is wakeups on editors' laptops, not correctness — hence medium, not
  high.)
- Evidence: read both sides. `db.queue_depth` (db.py:8033) always returns all
  four keys, so `depth` is never falsy on the dashboard side; the gate above it
  is what drops it. No test crosses the seam: `test_jobs_backpressure.py:190`
  and `:201` assert on `dbmod.queue_depth(conn)` directly, and nothing asserts
  what a report reply carries into `JobsRunner.note_report_reply` /
  `wait_seconds`.
- Ledger: new.
- Suggested fix: send `block["queue"] = depth` unconditionally whenever the
  `jobs` block is emitted (or emit the block whenever `depth` is meaningful),
  and add a seam test that a report reply on an empty fleet makes
  `wait_seconds()` return the backed-off value.

### dash-api-4 — [ KEEP HALTED ] is unreachable through the JSON API: `extend=true` with no reason is a 422
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:4303-4310` (`if payload.active
  and len(payload.reason.strip()) < 3: raise 422`) vs
  `dashboard/src/ccsync_dashboard/ui.py:2354-2355` (`extend = form.get("extend",
  "") == "1"; if active and not extend and len(reason) < 3:`).
- What: `extend` means "keep the CURRENT halt going, with its existing reason"
  — `db.set_fleet_halt` carries `reason`, `set_by` and `set_at` forward and
  only moves the expiry. The htmx door exempts `extend` from the reason floor;
  the JSON door does not, so the API can never express the operation. This is
  the "second door" asymmetry the repo calls out elsewhere ("a ledger the
  second door can walk past is worse than no ledger").
- Failure scenario: an operator scripting the halt against the API (or
  Timeline Cards / tools) sends `{"active": true, "extend": true}` to hold a
  fleet halt through an incident and gets a 422 telling them to "say why" about
  a halt that already has a reason. The natural workaround — resend with a
  reason — is silently *not* an extend: `set_fleet_halt` treats a real reason
  alongside `extend` as a fresh halt, so `set_at` resets and the banner then
  says how long since the last click, not how long the fleet has been stopped.
- Evidence: ad-hoc run (scratchpad `t_extend.py`):
  ```
  halt:   200 {'active': True, 'reason': 'restoring the pool', 'expires_at': '2026-09-04T02:47:51+00:00', 'extended': 0}
  extend: 422 {'detail': "say why: the reason is shown in every editor's tray (at least 3 characters)"}
  ```
  `grep -n extend dashboard/tests/*.py` shows every extend test goes through
  `/partials/admin/fleet-halt`; the JSON route's extend path has no test at all.
- Ledger: incomplete fix of **UX-8** (the reason floor was added to the JSON
  twin, the extend carve-out was not).
- Suggested fix: `if payload.active and not payload.extend and
  len(payload.reason.strip()) < 3:` — the same condition ui.py already uses;
  `db.set_fleet_halt` already refuses a blank extend on an *expired* halt.

### dash-api-5 — `_require_admin`'s 403 message talks about destination roots on ~45 unrelated admin routes
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:2923`
  (`detail="admins only: destination roots are fixed once set"`).
- What: the helper started life beside `PUT /project-roots` and is now the
  admin gate for every admin route in the file — package publish/delete/
  make-current/roll-back, user create/delete/disable, report-token mint/revoke,
  fleet halt, per-machine update/forget/resume, recovery restore/drill, Resolve
  undo, and all six `/jobs` admin routes. A non-admin editor who opens any of
  them is told about a feature that has nothing to do with what they asked for.
- Failure scenario: a non-admin editor clicks a fleet action; the toast reads
  "admins only: destination roots are fixed once set", which reads as a
  configuration problem rather than a permission one, and is exactly the kind
  of message that generates a support round-trip.
- Evidence: the route census (script over `@router.*` decorators) shows 45
  routes reaching `_require_admin`; only one of them is `/project-roots`.
- Ledger: new (hygiene, but it is user-visible HTTP `detail` copy).
- Suggested fix: make the message generic ("admins only") and let
  `api_set_project_root` raise its own specific refusal if that sentence is
  still wanted there.

### dash-api-6 — a file move does not normalise its path before matching `editor_media`, so an NFD-spelled path finds no machines to tell
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/api.py:2489-2493` (the
  `SELECT DISTINCT editor_username, machine FROM editor_media WHERE
  project_slug=? AND (rel_path=? OR rel_path LIKE ?)` using the raw
  `from_rel`), against `db.replace_editor_media` (db.py:6943) which stores
  `media_rel_key(rel)`, i.e. NFC.
- What: `_clean_project_rel` / `_validate_tree_part` do no Unicode
  normalisation, so the admin-supplied path is compared as exact bytes against
  a column that is normalised on the way in. CLAUDE.md's CR-90 rule is explicit
  that a comparison of this shape must go through a normaliser
  (`db.media_rel_key`).
- Failure scenario: an admin on a Mac copies `Matej Šimalčík/clip.braw` out of
  Finder (NFD) into the MOVE box. The `fetch_machine_selections` half still
  finds the machines that sync the project, but the second half — the machines
  whose manifest says they hold the file even though their plan no longer does
  — matches nothing, so those machines are never told. Lane A never deletes,
  so each of them re-uploads the file to the old path the next day: precisely
  the failure FILE_MOVES.md exists to end. CJK names never warn you, per CR-90.
- Evidence: read only — `grep -n "media_rel_key" api.py db.py` shows it used in
  `build_transfers_view` (api.py:538/549) and on both media writes, and nowhere
  on this query. I did not build an NFD repro, hence PLAUSIBLE rather than
  CONFIRMED; the raw `src.exists()` check earlier in the same function would
  also have to be satisfied, which on a Linux/ZFS NAS holding NFC bytes means
  an NFD input 404s first *for a file*, but the `LIKE from_rel + '/%'` branch
  and directory moves are not equally protected.
- Suggested fix: match with `db.media_rel_key(from_rel)` in that query (the
  column is already stored that way), and leave the filesystem path — `src`,
  `dest` — as the un-normalised bytes it must stay.

## Coverage note
Not covered: the ~1200 lines of view builders (`build_editors_view`,
`build_transfers_view`, `build_packages_view`, `build_queue_view`) beyond the
places they touch auth or the report; `make_current_refusal`'s soak/REL-1 gate
in detail; the admin user create/delete/SSH-key routes' NAS interaction
(`delete_user_everywhere`, `_remove_editor_devices`); `api_create_project` /
`adopt_folder` / `may_first_claim`; the recovery and alerts routes; and
`package_store.store_verified_package` (signature verification itself, which is
another territory's file).

What the suite does not cover, specifically: no test crosses the report-reply →
companion-reader seam for `commands.jobs.queue` (finding 3); no test exercises
the JSON fleet-halt `extend` path (finding 4); no test rotates
`DASH_SESSION_SECRET` and then calls anything other than `/report` (finding 1);
`test_file_moves.py`'s undo test never renames (finding 2). Several tests assert
against `db.*` helpers directly where the defect lives in the route that calls
them — that is the shape to watch for here.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/jobs_runner.py:315` — `wait_seconds`'s
  `not depth -> base` reading is the companion half of finding 3; whichever
  side is changed, the two must be changed together.
- `dashboard/src/ccsync_dashboard/ui.py:2354` — the htmx fleet-halt handler is
  the door that behaves correctly in finding 4; no defect there, cited only as
  the reference behaviour.
