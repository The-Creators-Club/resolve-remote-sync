# ytdl-web — the YouTube downloader web app (ytdl/web): fleet protocol, API, worker, AI backend, SPA

Files read (with approximate coverage):
- `ytdl/web/ytdlweb/routes_fleet.py` (100%), `routes_api.py` (100%), `projects.py` (100%),
  `identity.py` (100%), `session.py` (100%), `main.py` (100%), `ytdl_evidence.py` (~60%)
- `ytdl/web/ytdlweb/db.py` (~50%: migrations table, job/queue/lease/claim/heartbeat/end_lease/
  reclaim/lock_mode/cancel, video setters), `worker.py` (~65%: run_job, `_phase_download`,
  `_download_video`, `_record_failure`, breaker, `_reclaim_local_job`, `_await_local_claim`,
  manifest), `config.py` (`safe_join`, `version_rank`, floors, lease constants)
- `ytdl/web/ytdlweb/ai_backend.py` (~55%: provider resolution, `complete`, OpenAI-compatible
  path, `_http_error`, auth detail), `claude_cli.py` (`data_block`, `_strip_fences`)
- `ytdl/web/static/app.js` (~35%: payload construction, `probeLocalMachine`, `loadProjects`,
  topbar, innerHTML sites), `schema.sql` + `migrations/*.sql` (drift check, scripted)
- `ytdl/web/tests/`: `conftest.py`, `test_api.py` (CR-72/CR-96 cases), `test_no_em_dash.py`,
  grep across `test_static_app.py`
- Cross-side (read-only): `companion/src/ccsync_companion/ytdl_executor.py` (claim / heartbeat /
  manifest / clip_status wire format, `_this_machine_id`, version-floor warning)
- `KNOWN_BUGS.md` CR-29..CR-39, CR-73..CR-84, CR-96..CR-99

Tests run:
- `cd ytdl/web && ../../dashboard/.venv/Scripts/python.exe -m pytest tests -q` -> **840 passed**
- Three ad-hoc repro tests written to the scratchpad (never into the repo) and run with
  `-p tests.conftest` against the real app; outputs quoted below.

## Findings

### ytdl-web-1 — the SPA never sends `machine` on a job POST, so the picker offers projects that SEARCH and GET LINKS then refuse with a 400
- Severity: high
- Confidence: CONFIRMED
- Where: `ytdl/web/static/app.js:1913` (`runSearch` payload) and `ytdl/web/static/app.js:1972`
  (`runUrls` payload); consumed at `ytdl/web/ytdlweb/routes_api.py:456` / `:774`
  (`projects.resolve_project(user, req.project_slug, machine=req.machine, local=req.local)`)
- What: CR-96 half 2 widens the picker per MACHINE. `loadProjects()` correctly builds
  `api/projects?local=…&machine=<hostname>` (app.js:671-672), but both job-creation payloads
  carry only `local: localWanted()` and no `machine:` key at all — `grep -n "machine:" static/app.js`
  returns exactly one hit, and it is a comment. `NewJob.machine` / `NewUrlJob.machine` therefore
  default to `None`, `projects._wired(con, user, None)` answers False ("unknown is not wired"),
  and `resolve_project` falls back to the narrow ticked list.
- Failure scenario: the owner's own shape — a mixed account (wired base rig + remote laptop),
  standing at the wired rig with "on this machine" ticked. The picker lists every active project
  (that is the CR-96 fix). Choosing one the account does not tick and pressing SEARCH or GET LINKS
  returns `400 "that project is not one you are syncing. Tick it on the dashboard first…"`. The
  destination is visible, selectable, and unusable — which is a worse version of the empty picker
  CR-72/CR-96 set out to fix.
- Evidence (scratchpad repro, mixed account seeded exactly as `test_the_wired_machine_of_a_mixed_
  account_is_offered_every_project` seeds it):
  ```
  offered on ?local=true&machine=owen-rig  -> includes '2025-ff4-nuclear'
  POST /api/jobs {term, project_slug: '2025-ff4-nuclear', local: true}   # the real SPA payload
  CREATE -> 400 {"detail":"that project is not one you are syncing. …"}
  ```
  The CR-96 test note itself says "a picker offering what the POST then refuses is the worse bug",
  and `tests/test_static_app.py:2573-2587` pins only the GET URLs, never a POST body — so the
  suite cannot see this.
- Ledger: regression of CR-96 (half 2, client side) — the entry claims the SPA half is complete.
- Suggested fix: add `machine: localMachine || undefined` (or `null`) to both payloads next to
  `local: localWanted()`, and extend `test_the_picker_tells_the_server_which_computer_is_asking`
  to assert the POST body, not just the projects query string.

### ytdl-web-2 — `start_download` re-validates the destination with the NARROW rule, so a widened job can be created but never downloaded
- Severity: high
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/routes_api.py:517` — `if projects.resolve_project(user, job['project_slug']) is None:`
  (no `machine=`, no `local=`); the widening decision made at create time is at `routes_api.py:456`
  / `:774`, and it is **not persisted** anywhere (checked: no `local`/`machine` column in
  `schema.sql` or `migrations/*`).
- What: `resolve_project`'s two widening flags default to `machine=None, local=True`, i.e. the
  pre-CR-72-follow-up rule. `start_download` is the DOWNLOAD button at the end of a search's
  review, and the RETRY button on a finished/failed job. It therefore refuses every job whose
  project was only legitimate because of half 1 (`local=False`) or half 2 (`machine=<wired>`),
  and because the job row does not record which flags were used, no correct answer is even
  reachable from this function today.
- Failure scenario: an editor unticks "on this machine" (or the fleet's `YTDL_LOCAL_DOWNLOAD`
  flag is off, which is the shipped default — so this is the COMMON path). The SPA sends
  `local: false`, the picker and the create both widen, the search runs, the manifest is
  reviewed... and pressing DOWNLOAD answers
  `409 "<project> is no longer a project you sync, so nothing can be downloaded into it."` The
  job is unreachable and the message is false — the project was never ticked and never had to be.
- Evidence (scratchpad repro, no `machine_state` needed for the `local=false` half):
  ```
  POST /api/jobs/urls {urls, project_slug: '2025-ff4-nuclear', local: false}
  CREATE   -> 200 {"job_id":1,...}
  POST /api/jobs/1/download
  DOWNLOAD -> 409 {"detail":{"detail":"2025/FF4/Nuclear is no longer a project you sync, …"}}
  ```
  and the same 409 for the `machine='owen-rig'` (wired, mixed account) create.
- Ledger: regression of CR-96 (both halves; half 1 is described in the ledger as "complete").
- Suggested fix: persist the create-time `local` (and `machine`) on the job row in a new
  migration and pass them back into `resolve_project` here — or, since neither is a security
  boundary once the project was already accepted at create, re-run the check with the same
  widening the job was created under. A test that walks create -> `ready_for_review` -> DOWNLOAD
  for a widened project is what the suite is missing.

### ytdl-web-3 — a `done` status post with a directory-shaped `filepath_rel` 500s the fleet route instead of being refused
- Severity: low
- Confidence: CONFIRMED (by reading; not exercised against a live companion)
- Where: `ytdl/web/ytdlweb/routes_fleet.py:741` (`_record_done` -> `config.safe_join(...)`),
  raising `config.PathTraversalError` (`config.py:478`); no handler for it in
  `ytdlweb/main.py` and no `except` on the call path.
- What: `name = os.path.basename(filepath_rel.replace('\\','/').rstrip('/'))` yields `'..'` for
  `filepath_rel='../..'`, and `safe_join` raises `PathTraversalError`, which FastAPI turns into a
  500 with a traceback in the dashboard log. `'.'` is worse in the other direction: `safe_join`
  silently drops it, so the clip is recorded `done` with `filepath` pointing at the TERM
  DIRECTORY and a ledger row whose `rel_path` ends in `/.` — a permanent "the fleet already has
  this" pointing at a folder, which is exactly what YTDL-15's rule (quoted three lines above)
  exists to prevent.
- Failure scenario: a companion bug (or a machine holding a valid fleet token plus a valid
  identity token) posts `{"state":"done","filepath_rel":"."}` for a clip; the ledger gains a row
  that suppresses that video for the whole fleet forever, and the ledger never cascades.
- Evidence: `os.path.basename('.') == '.'`; `config.safe_join` skips segments in `('', '.')` at
  `config.py:476-477` and only rejects `'..'`. The route has no try/except and `main.py` installs
  no exception handler.
- Ledger: new.
- Suggested fix: validate `name` the way a filename should be validated (reject `'.'`, `'..'`,
  any separator, empty) and answer 400, rather than relying on `safe_join`'s traversal rule to
  double as filename validation.

## Coverage note
Not covered: `vendor/downloader.py` and `vendor/ytsearch.py` (explicitly outside the territory —
so the `player_client=web_safari` / `concurrent_fragment_downloads` / cookie-jar mechanics of
CR-39/CR-74/CR-80 were only read at their call sites in `worker.py`); `attestation.py`;
`ytdl_canary.py`; the bulk of `claude_cli.py`'s prompt tables and JSON parsing; roughly two
thirds of `app.js` (the review grid, history panel and dispatch state machine) and all of
`test_static_app.py`'s 4400 lines beyond targeted greps; `DEPLOY.md`.

What the suite does not cover, beyond the two findings above: no test drives the full
create -> review -> `start_download` path for a *widened* project (findings 1 and 2 both live in
that gap), and no test asserts the shape of a job-creation POST **body** from the SPA — only the
`GET /api/projects` query string. Prompt-injection posture (`claude_cli.data_block`) is
tested only for the closing tag; an injected *opening* tag is not stripped, which I did not
judge exploitable enough to file.

Two documented-but-real trade-offs I deliberately did not file as findings, because the code
argues for them explicitly: `db.lease_held_by` treats a NULL `claimed_machine` as "matches any
machine", so an editor whose first machine claimed with an empty `machine_id`
(`ytdl_executor._this_machine_id()` returns `""` when `~/.ccsync/machine.json` cannot be read)
can have a second machine take the live lease and download the same clips into two trees — the
CR-66 failure, behind a compatibility clause; and `db.heartbeat_download` / `db.is_leaseholder`
are keyed per-EDITOR with no machine, which is safe only as long as the losing machine never
learns the job id.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/ytdl_executor.py:1211` — `_warn_on_a_version_floor_we_rank_differently`'s
  docstring still says "the dashboard compares the raw strings"; the server has ranked
  numerically since COMP-BROLL-9 (`config.version_rank`). Stale comment only, no behaviour bug.
