# ytdl-web - the YouTube downloader web app (`ytdl/web/ytdlweb/*`, `static/*`, `migrations/*`)

Files read (with approximate coverage):
- `ytdl/web/ytdlweb/routes_api.py` (~60%: the whole free-space/tree-guard block 1370-1620, `start_download`, `create_url_job`, `create_job` signature, the health/yt-dlp-age block 245-300, manifest/poll)
- `ytdl/web/ytdlweb/worker.py` (~25%: `_await_local_claim`, `_no_room_note`, `_phase_download`, `ensure_outdir`)
- `ytdl/web/ytdlweb/routes_fleet.py` (~90%: gates, claim, heartbeat, manifest, clip_status, `_record_done`, `_hand_back_to_the_server`)
- `ytdl/web/ytdlweb/db.py` (~30%: `_column` x2, `created_widening_of`, `claim_download`, `heartbeat_download`, `mark_pending`, `pending_videos`, `job_dict`, `ensure_schema`/`_apply_migration`)
- `ytdl/web/static/app.js` (~25%: `dispatchLocal`, `localWanted`, `renderRetry`, `retryFailed`, `startDownload`, `runUrls`, the search payload)
- `ytdl/web/migrations/013`, `014`, `ytdl/web/tests/test_api.py` (health block), `.github/workflows/ci.yml` (ytdl steps)
- Diffs: `git diff 34a3c8f..HEAD -- ytdl/web/` (EMPTY - nothing this week touched this territory) and `git diff 18e69f3..34a3c8f -- ytdl/web/` read hunk by hunk.

Tests run: `cd ytdl/web; ../../dashboard/.venv/Scripts/python.exe -m pytest tests -q` -> **1 failed, 958 passed** (see ytdl-web-1).

## Findings

### ytdl-web-1 - the ytdl/web suite has been RED since 2026-09-17 on a hard-coded date, and CI red blocks the vendor feed
- Severity: high
- Confidence: CONFIRMED
- Where: `ytdl/web/tests/test_api.py:470` (with `ytdl/web/ytdlweb/config.py:282` `DEFAULT_YTDLP_MAX_AGE_DAYS = 21`, `routes_api.py:265` `_yt_dlp_is_stale`, `.github/workflows/ci.yml:343`)
- What: `test_health_reports_how_old_the_running_yt_dlp_is` monkeypatches the running yt-dlp to the literal `'2026.08.27'` and then asserts `h['yt_dlp_stale'] is False`. Staleness is `age > YTDLP_MAX_AGE_DAYS` with the age computed against `date.today()` and the limit defaulting to 21 days. The assertion therefore held only until 2026-09-17 and is false from that date onwards, for ever.
- Failure scenario: any run of the ytdl/web suite on or after 2026-09-17 - `tools\run_all_tests.ps1`, the CI job, a hunter - fails with `assert True is False`. The `ytdl/web -- pytest` step in `.github/workflows/ci.yml` has no `continue-on-error`, so every CI run on `main` is now red; `tools/publish_latest.py` takes "the newest GREEN CI run on main", so the vendor feed cannot be published from a commit made after that date until this is fixed.
- Evidence: the run above (`FAILED tests/test_api.py::test_health_reports_how_old_the_running_yt_dlp_is`, 1 failed / 958 passed) on an unmodified tree at HEAD 214869b. `(date(2026,9,18) - date(2026,8,27)).days == 22 > 21`.
- Ledger: new (no KNOWN_BUGS entry; the suite was green when the 09-11b pass landed).
- Suggested fix: derive the fresh version from the clock, e.g. `(date.today() - timedelta(days=1)).strftime('%Y.%m.%d')` for the not-stale case and `days=config.YTDLP_MAX_AGE_DAYS + 1` for the stale case, so the test pins the RULE and not a calendar date. A grep for other literal dates in the suite found none that compare against `today()`.

### ytdl-web-2 - the worker's new "no room" refusal reintroduces the wrong sentence a vanished share earns (ytdl-web-1's whole point), on the server side
- Severity: medium
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/worker.py:1528` (`_no_room_note`) and its caller `worker.py:1641`; compare `ytdl/web/ytdlweb/routes_api.py:1494-1530` (`_refuse_if_full`, which calls `_refuse_if_the_tree_is_gone`)
- What: `_no_room_note` duplicates `_refuse_if_full`'s two numbers and its sentence but NOT its tree guard. `YTDL_PROJECTS_ROOT` is a bind mount and a mount that has gone away leaves its mount point behind on the container overlay, so `shutil.disk_usage` answers with the overlay's couple of spare gigabytes. The worker then fails the job with "there is only 2.0 GB free on the server where these clips go ... Free some space", about a share with 900 GB on it - the exact sentence CR-263a/ytdl-web-1 exist to stop an editor acting on, now emitted from the executor path instead of the press path.
- Failure scenario: `YTDL_LOCAL_DOWNLOAD=1`, a job created local, the editor's tray is off so nobody claims it, and the NAS bind mount has dropped. The worker measures the overlay, sets `phase='failed'` with the disk-full sentence, and nothing anywhere names the lost share. The admin deletes footage.
- Evidence: read both functions side by side. `_refuse_if_full` calls `_refuse_if_the_tree_is_gone(job)`; `_no_room_note` has no equivalent and no caller adds one (`worker.py:1638-1650` just logs and sets the phase). `KNOWN_BUGS.md:19029` (ytdl-web-1) and `:23166` (CR-263a) state the rule for the press path only.
- Ledger: CR-263a / ytdl-web-1 do not cover the worker path opened by ytdl-web-b-2 (09-11b).
- Suggested fix: have `_no_room_note` ask `routes_api._named_under_the_root(job['project_label'])` / the same `project_dir.is_dir()` test first and, when the tree is gone, emit the `tree_missing` sentence instead ("the server has lost the share, tell whoever runs the dashboard").

### ytdl-web-3 - the "no room" failure tells the editor to press RETRY FAILED, and the page hides that button in exactly that state
- Severity: medium
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/worker.py:1556` (the note's last sentence) vs `ytdl/web/static/app.js:1401-1422` (`renderRetry`)
- What: `renderRetry` offers `[ RETRY N FAILED ]` only when `failed > 0`, where `failed = job.dl_failed || (manifest videos with dl_state === 'failed').length`. `_no_room_note` fires BEFORE any clip is attempted: `start_download` has just written `dl_failed=0` and `mark_pending` has reset every previously failed row to `pending`, so `dl_failed` is 0 and no row is `failed`. `offer` is false, so the button is hidden - and so is `#dlnote`, whose text is gated on `offer` too.
- Failure scenario: a created-local job the tray never claims, on a full server disk. The job goes `failed` with "Free some space and press RETRY FAILED."; the editor frees 500 GB and there is no RETRY FAILED button on the page. Their only route back is a whole new search (another Claude spend and another twenty minutes of yt-dlp) - which is the YTDL-16 situation the retry button was added to end. The server-side route would accept the retry (`unfinished_downloads` counts the pending rows), so the block is purely the page's.
- Evidence: `db.mark_pending` (`db.py:1612`) sets `dl_state='pending'` for `('none','failed','skipped','pending')`; `routes_api.py:1725` sets `dl_failed=0`; `_phase_download` returns at `worker.py:1650` before the loop. `renderRetry`'s `offer` expression read directly.
- Ledger: new (introduced with ytdl-web-b-2 in the 09-11b pass).
- Suggested fix: make `renderRetry` also offer the button when `job.phase === 'failed'` and the manifest has `pending` rows (or when `job.error` carries a `disk_full`-shaped reason), rather than only when a row is `failed`; alternatively have `_no_room_note` mark the pending rows `failed` with the same note so the existing predicate sees them.

### ytdl-web-4 - a pasted-links job never gets a free-space check at all, on either executor
- Severity: medium
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/routes_api.py:954-1045` (`create_url_job`, which never calls `_refuse_if_full`) and `ytdl/web/ytdlweb/worker.py:1543` (`_no_room_note`'s first line)
- What: the YTWEB-9 guard lives in `start_download` only, and a url job goes straight to `downloading` from `create_url_job` without passing through it. The worker's new backstop refuses to look unless `config.LOCAL_DOWNLOAD and created_local` is true. With the fleet's shipped default (`YTDL_LOCAL_DOWNLOAD` off) `localWanted()` returns false, so the SPA posts `local: false` for every job and `created_local` is 0 - so neither half of the guard ever runs for a paste.
- Failure scenario: an editor pastes 40 links into a project on a NAS with 6 GB left. Nothing measures anything; yt-dlp produces N opaque per-clip ENOSPC failures and the job ends `failed` with a breaker note about identical failures - precisely the symptom YTWEB-9 replaced with one sentence, still live for the paste door.
- Evidence: `grep -n "_refuse_if_full" ytdl/web/ytdlweb/routes_api.py` returns only the definition (1494) and the single call inside `start_download` (1705). `worker._no_room_note` line 1543: `if not (config.LOCAL_DOWNLOAD and db.created_widening_of(job)[1]): return None`.
- Ledger: new; ytdl-web-b-2 (09-11b) closed this for created-local jobs only, and its own docstring ("the press already measured this tree") is untrue of the paste path.
- Suggested fix: either call `_refuse_if_full` in `create_url_job` after the destination is resolved, or relax `_no_room_note` to "the press did not measure this tree" (created-local OR a url job) rather than created-local alone.

### ytdl-web-5 - when the share vanishes but the container has room, the download SUCCEEDS into the container overlay and the ledger permanently claims the clips
- Severity: medium
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/routes_api.py:1494-1512` (`_refuse_if_the_tree_is_gone` is reached only on the way to a disk_full refusal) with `ytdl/web/ytdlweb/worker.py:849` (`ensure_outdir` makedirs unconditionally)
- What: the tree guard is deliberately consulted only when `free < need`. A dashboard host with, say, 200 GB free on its own disk therefore passes the free-space check while the bind mount is gone, `ensure_outdir` creates `<mountpoint>/<project>/Youtube/<term>` on the overlay, and yt-dlp writes there. `db.ledger_add` then records each clip as held by the fleet at a NAS-relative path that has no file behind it, and the ledger never cascades.
- Failure scenario: the NAS share drops (the case ytdl-web-1 was written for) during a 40-clip job on a roomy host. The clips download to nowhere anybody syncs, are lost on the next container recreate or image update, and every future search or paste of those video ids is skipped as "the fleet already has that video" pointing at a path that does not exist. No notice, no refusal, `phase='done'`.
- Evidence: `_refuse_if_full` returns None at `routes_api.py:1500` whenever `free >= need`, before the tree guard is ever reached; the comment at 1508-1512 states the design ("a download that fits is a download that fits"). `ensure_outdir` (worker.py:849) has no existence precondition. `_record_done`/`worker`'s `db.ledger_add` writes the rel path regardless of which filesystem answered.
- Ledger: related to ytdl-web-1/CR-263a (both are about the REFUSAL sentence; neither covers the success path).
- Suggested fix: check the tree unconditionally at the top of `_phase_download` (and `_refuse_if_full`) - a project folder that is not there means the destination is not the tree, whatever the free-space number says. Refusing with `tree_missing` is strictly better than writing into the overlay.

### ytdl-web-6 - any fleet-credentialled editor can claim, and be handed the work order for, another editor's job
- Severity: low
- Confidence: PLAUSIBLE
- Where: `ytdl/web/ytdlweb/routes_fleet.py:180` (`_job_or_404`, no owner argument) and `:398-545` (`claim`, which never compares `editor` with `job['created_by']`)
- What: the browser routes use `db.get_job_for(user)`; the fleet claim route deliberately does not, and authorises on "token plus lease" - but the lease is the thing being handed out here, so on the first claim there is nothing but a valid `cce1.` token and a signed identity. Editor B can POST `/api/jobs/<A's id>/claim` and then GET the manifest, which carries A's `project_label`, term dir and the full clip list, and downloads them into a project B may not sync - the outcome ytdl-web-5's `created_widened` gate was added to exclude for the server-widened case, still open for the ordinary created-local case.
- Failure scenario: job ids are small sequential integers. A companion (or a curious editor with the token on their own machine) claims job 412 a second after another editor presses DOWNLOAD; the first editor's clips land in the wrong tree, `download_host` records the wrong person, and A's own machine is refused with 409 "B is already downloading this job".
- Evidence: read `claim` end to end; the only identity use is `db.claim_download(c, job_id, editor, ...)`, which writes `claimed_by` rather than testing it. `_job_or_404`'s docstring states the omission is intentional.
- Ledger: related to H5 / CR-55 (which bound the identity but not the row).
- Suggested fix: add `if job['created_by'] != editor: raise HTTPException(410, ...)` in `claim` - a companion only ever acts for its own editor's job, and the 410 keeps the "stop quietly" contract.

### ytdl-web-7 - `db.py` defines `_column` twice; the first definition is dead
- Severity: low
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/db.py:206` and `ytdl/web/ytdlweb/db.py:976`
- What: two module-level `def _column(row, key)` in one file. The second shadows the first for every caller in the module, including the fourteen readers above line 976 that were written against the first. They happen to behave identically today (the first's `except TypeError` covers `row is None`), so nothing is broken - but a future edit to either is a silent no-op or a silent behaviour change for half the module, and the two docstrings already disagree about what the function is for.
- Failure scenario: someone tightens the reader at line 206 (say, to stop swallowing `TypeError`) and nothing changes; the bug they were chasing stays.
- Evidence: `grep -n "^def _column" ytdl/web/ytdlweb/db.py` -> two hits, 206 and 976.
- Ledger: new.
- Suggested fix: delete one, keep the line-976 docstring.

### ytdl-web-8 - the new "download on this computer was unticked" sentence says "this search" on a pasted-links job
- Severity: low
- Confidence: CONFIRMED
- Where: `ytdl/web/static/app.js:2533-2536` (the `noteLocalSkipped` text in `dispatchLocal`), reached from `runUrls` at `app.js:2241`
- What: the regression-26 sentence is "this search was submitted with ... unticked, so the server is fetching it. Tick the box before the next search to have clips land here". `runUrls` (paste a list of links) calls the same `dispatchLocal`, and a paste is not a search; the editor is told to change a setting on a screen they did not use.
- Failure scenario: an editor pastes eight links with the box unticked, reads "this search", looks for a search they did not run.
- Evidence: the single `noteLocalSkipped` call site for `createdLocal === false` serves all three callers (`runUrls`, `startDownload`, `retryFailed`). No em dash in the string, so `test_no_em_dash` is satisfied.
- Ledger: new (introduced by the 09-11b regression-26 fix).
- Suggested fix: "this job was submitted with ... unticked" plus "tick the box before the next one".

## Coverage note

Not reached: `claude_cli.py` (1146 lines) and `ai_backend.py` (849) beyond their call shape, `ytdl_canary.py`, `ytdl_evidence.py`, `ytdl_cookies`/`attestation` in depth, ~75% of `app.js` (the review grid, terms review, history panel, queue rendering), `style.css`/`index.html`, and migrations 002-012. The diff `34a3c8f..HEAD` is EMPTY for this territory, so nothing this week changed it; all eight findings are against the 09-11b fix pass or older code.

What the suite does not cover: there is no test anywhere for the worker-side `_no_room_note` meeting a VANISHED tree (ytdl-web-2) - `test_bug_hunt_2026_09_11b_ytdl_web.py` exercises it only against a full-but-present tree; no test drives `create_url_job` past a full disk (ytdl-web-4); no test asserts the RETRY FAILED button is offered after a `no_room` failure (ytdl-web-3, and the static-app tests do drive `renderRetry`, so one could); and no test claims one editor's job as another (ytdl-web-6).

## OUT OF TERRITORY
- `.github/workflows/ci.yml:343`: the `ytdl/web -- pytest` step is red at HEAD because of ytdl-web-1, which by `tools/publish_latest.py`'s "newest GREEN run on main" rule blocks the vendor feed for every component, not just this one.
