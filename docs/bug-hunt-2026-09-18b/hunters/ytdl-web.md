# ytdl-web - the YouTube downloader web app (`ytdl/web/ytdlweb/*`, `static/*`, `migrations/*`)
Files read (with approximate coverage): `git diff -- ytdl/` in full (app.js, tests/test_api.py, ytdlweb/db.py, routes_api.py, worker.py); `ytdl/web/ytdlweb/routes_api.py` lines 850-1100 and 1370-1800 (the url-job door, the free-space/tree guards, start_download) ~40%; `ytdl/web/ytdlweb/worker.py` `_phase_start`, `ensure_outdir`, `_sweep_stale`, `_no_room_note`, `_phase_download` ~30%; `ytdl/web/ytdlweb/db.py` `_column`, `create_url_job`, `mark_pending`, `selected_for_download`, `pending_videos`, `unfinished_downloads`, boot recovery ~25%; `ytdl/web/static/app.js` poll/attach/renderProgress/renderRetry/retryFailed/dispatchLocal ~25%; `tests/test_bug_hunt_2026_09_18_webapps_tools.py` in full; `migrations/` listing (unchanged by this pass); `docs/bug-hunt-2026-09-18/ledger/webapps-tools.md` CR-286K/L/M and its OWED section.
Tests run: `cd ytdl/web; ..\..\dashboard\.venv\Scripts\python.exe -m pytest tests -q` -> 968 passed (green, including the five new ytdl-web sections)

## Findings

### ytdl-web-1 - CR-286K does not fix ytdl-web-3: a failed job has no manifest, so the retry button is still hidden
- Severity: medium
- Confidence: CONFIRMED
- Where: `ytdl/web/static/app.js:1419` (the new `pending` count) against `ytdl/web/static/app.js:1247-1252` (`poll()`: `if (job.phase !== 'failed') { await loadManifest(id); }`)
- What: the fix decides the offer from `state.manifest.videos`, but `poll()` deliberately never loads the manifest for a job whose phase is `failed`, and the only other place it is filled is the per-tick fetch guarded by `job.phase === 'downloading'` (line 1236). In the very scenario the fix names - `_no_room_note` / the new tree guard firing before the first clip - the job goes `downloading` -> `failed` in the milliseconds after `worker.nudge()`, so no tick ever ran with phase `downloading`, `state.manifest` is `null`, `pending` is 0, `stalled` is false and the button is hidden exactly as before. The ledger entry itself names this half of the mechanism ("`poll()` does not reload the manifest for a failed job") and then fixes only the other half.
- Failure scenario: editor presses DOWNLOAD on a 41-clip manifest with 1 GB free; the worker fails the job with "there is only 1.0 GB free ... Free some space and press RETRY FAILED" before any clip. The page (or a reload onto `#job=<id>`, which is the case the ledger calls out) shows the red sentence, the review grid hidden, `#dlretry` hidden and `#dlnote` hidden - the editor's only route back is a whole new search, i.e. the YTDL-16 situation unchanged.
- Evidence: read `poll()` (app.js 1203-1275) - `loadManifest` is called at exactly one site, line 1255, inside `if (job.phase !== 'failed')`; `attach()` sets `state.manifest = null` (line 1182). The regression test `test_a_job_that_failed_before_any_clip_still_offers_the_retry` is a source grep over `renderRetry` (`"dl_state === 'pending'" in fn`), so it passes without the behaviour existing.
- Ledger: CR-286K does not fix ytdl-web-3
- Suggested fix: in `poll()`, fetch the manifest for a terminal `failed` job too, tolerating a 404 (a job that died in search has none) - `try { m = await api(...manifest) } catch {}` - or have `/api/jobs/{id}` carry `dl_pending` so `renderRetry` needs no manifest at all. The latter also survives the manifest endpoint being unavailable.

### ytdl-web-2 - the paste free-space guard can never size a paste, so it misses its own stated scenario
- Severity: medium
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/routes_api.py:1045-1052` (the new `_refuse_if_full` call in `create_url_job`) and `ytdl/web/ytdlweb/worker.py:1576-1581` (`_no_room_note`'s url-job branch); estimate at `routes_api.py:1407-1416`
- What: `estimated_bytes` sums `r['duration']`, and a pasted job's rows never have one - `parse_url_list` produces `{'video_id', 'url'}` only (routes_api.py:883), `db.create_url_job` writes those rows verbatim, and `_phase_start` sends a `KIND_URLS` job straight to `downloading` with no enrich phase (worker.py:403-413). So the estimate is always 0 and the test collapses to the flat `UNKNOWN_ESTIMATE_FLOOR` of 2 GB regardless of whether 1 or 40 links were pasted. The ledger's own scenario ("40 links into a project with 6 GB left") is still accepted, on both the press and the worker.
- Failure scenario: 40 x 1080p links (~30 GB) pasted into a project with 6 GB free -> 6 GB >= 2 GB -> no refusal at GET LINKS, no refusal in `_no_room_note`, and the editor gets exactly the N opaque per-clip ENOSPC failures plus a breaker note that CR-286L claims to have replaced with one sentence.
- Evidence: `parse_url_list` returns no duration; `create_url_job`'s docstring lists the accepted keys as `video_id/url/title?/duplicate_of?`; `_phase_start` has no enrich branch for `KIND_URLS`. Both new tests pass only because they monkeypatch `disk_usage` to 10**8 bytes (0.1 GB), i.e. below the flat floor - they would pass with `estimated_bytes` hard-coded to 0.
- Ledger: CR-286L does not fix ytdl-web-4 (partial: it covers a nearly-full disk, not a big paste)
- Suggested fix: size a paste by count - `len(rows) * BYTES_PER_SECOND[quality] * TYPICAL_CLIP_SECONDS` or a per-clip floor (`max(UNKNOWN_ESTIMATE_FLOOR, len(rows) * PER_CLIP_FLOOR)`) - and add a test with 40 rows and 6 GB free that expects the 409.

### ytdl-web-3 - the worker's no-room sentence names "RETRY FAILED", the button CR-286K just renamed to "RETRY N CLIPS"
- Severity: low
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/worker.py:1591-1593` (`... Free some space and press RETRY FAILED.`) against `ytdl/web/static/app.js:1425-1428` (`btn.textContent = failed > 0 ? '[ RETRY N FAILED ]' : '[ RETRY N CLIPS ]'`)
- What: `_no_room_note` fires before any clip is attempted, so `dl_failed` is 0 by construction in every state this sentence can be read in - which is precisely the state where CR-286K now labels the button `[ RETRY N CLIPS ]`. The instruction therefore names a control that does not exist under that name, which is the exact defect CR-286L introduced the `press=` parameter to avoid one screen over. The same sentence is now also emitted for a pasted job, whose page control is GET LINKS.
- Failure scenario: a paste into a full tree fails with "Free some space and press RETRY FAILED"; the page shows `[ RETRY 40 CLIPS ]` (if it shows anything at all - see ytdl-web-1), and the editor hunts for a button labelled RETRY FAILED.
- Evidence: the two strings, side by side in the diff of this same fix pass; `_no_room_note` is reached only from `_phase_download` before the per-clip loop, so `failed > 0` is unreachable there.
- Ledger: new (a collision between CR-286K and CR-286L/CR-286J)
- Suggested fix: make the note say "press the retry button on this job" or give `_no_room_note` the same `press=` treatment, deriving it from `db.KIND_URLS`.

### ytdl-web-4 - ytdl-web-5 turns "tree is gone" from a wording rule into an absolute refusal, reversing a documented decision
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `ytdl/web/ytdlweb/worker.py:1667-1685` (the new unconditional `tree_missing_note` gate) against `ytdl/web/ytdlweb/routes_api.py:1642-1648` (`_refuse_if_the_tree_is_gone`'s docstring: "Only ever consulted on the way to a disk_full refusal, and deliberately so ... a project folder this check cannot see is not a reason to invent a new way for one to be impossible")
- What: the guard's evidence is "no directory under `PROJECTS_ROOT` whose NFC-folded name equals `project_label`". That is now sufficient to fail the whole job, where before it only chose the wording of a refusal that had already been decided on free space. The predicate is exact on CASE and on separators, and it requires the project folder to exist already - `ensure_outdir` used to create it. Any legitimate absence (a project ticked on the dashboard whose folder has not been made on the NAS yet, a label whose case differs from the on-disk folder on a case-sensitive dataset, a label that reached the jobs row before a rename) now yields a hard failure whose sentence blames a lost share and tells the editor to go find an admin.
- Failure scenario: an admin adds a project, ticks it, and an editor pastes links before anything has been written into that project folder -> every download fails with "the footage tree is not there: nothing at /projects looks like <label>" and no retry can ever succeed, on a NAS that is perfectly healthy.
- Evidence: `tree_is_gone` returns False only for a traversal refusal, an unreadable root or an OSError; a readable root with no matching child returns True, and `_named_under_the_root` compares `unicodedata.normalize('NFC', e.name) == want` with no casefold. The new `test_a_vanished_share_stops_the_download_even_when_there_is_room` asserts exactly this state (root exists, project folder does not) is "gone" - it cannot tell the two causes apart.
- Ledger: CR-286M opens a neighbour of ytdl-web-5
- Suggested fix: require a second, positive signal before failing the job - e.g. that the root is readable AND contains at least one entry (a mount point left behind is empty), or a marker file the tree always has - and casefold the comparison in `_named_under_the_root`. Otherwise keep creating the folder and let the disk check decide, as the old docstring intends.

### ytdl-web-5 - the vanished-share guard runs after the container overlay has already been written
- Severity: low
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/worker.py:1614-1616` (`ensure_outdir(outdir)` / `_sweep_stale(outdir)`) vs the new gate at `worker.py:1668-1685`
- What: `_phase_download` makedirs `<root>/<label>/Youtube/<term_dir>` and chmods 2775 on everything it created, and sweeps that folder, before it asks whether the tree is there. The mechanism the fix is written against ("`ensure_outdir` makedirs the mount point's children") therefore still happens on every refused run; only the yt-dlp writes are prevented.
- Failure scenario: bind mount gone, twenty queued jobs -> twenty project/Youtube/<term> trees created on the container's own overlay under the mount point; when the mount returns they are shadowed, and `tree_is_gone` would answer False for any of those labels for as long as the container lives, silently disarming the guard for the next outage.
- Evidence: line order in `_phase_download`; `ensure_outdir` (worker.py:849) unconditionally `os.makedirs(..., exist_ok=True)`.
- Ledger: CR-286M is incomplete
- Suggested fix: move the `tree_missing_note` check above `ensure_outdir`, where it costs one `is_dir()`.

### ytdl-web-6 - the free-space regression tests pass for a reason unrelated to the fix
- Severity: low
- Confidence: CONFIRMED
- Where: `ytdl/web/tests/test_bug_hunt_2026_09_18_webapps_tools.py:82-118` (`test_a_pasted_job_is_measured_at_the_press`, `test_the_workers_backstop_covers_a_paste_with_the_flag_off`) and `:154-165` (`test_a_job_that_failed_before_any_clip_still_offers_the_retry`)
- What: the two disk tests set free space to 0.1 GB, below the unknown-estimate floor, so they never exercise the estimate at all (ytdl-web-2 above); the retry test is a regex over `app.js` source, so it pins the presence of the word `stalled` rather than the behaviour, and cannot see that the manifest it reads is null in that state (ytdl-web-1 above). `test_the_db_module_defines_column_once` is likewise a source grep, which is defensible for that finding but makes three of the seven new tests source assertions.
- Failure scenario: the fixes regress or, as here, never worked, and the suite stays green.
- Evidence: the test file, read in full; the suite is green with the defects in ytdl-web-1 and ytdl-web-2 present.
- Ledger: new
- Suggested fix: drive the paste test with 40 rows against 6 GB free, and test the retry offer through the DOM contract (or a server-side `dl_pending` field) rather than a source grep.

## Coverage note
I did not audit `ytdl_server.py`'s companion-facing fleet routes (they belong to comp-music-ytdl-jobs on the other side and were untouched by this pass), the attestation/cookies/browser-login paths, or the queue/lease logic beyond what the diff touches. `ytdl/web/migrations/` is unchanged by this fix pass (no new step), so no migration hazard exists here. The suite has no browser-level coverage at all: every app.js assertion in the tree is a text search over the source file, which is why ytdl-web-1 is invisible to it. I did not verify ytdl-web-4 against a real deployment's project table (whether a ticked project can exist before its folder does) - that is why it is PLAUSIBLE rather than CONFIRMED, and it is one query on the live dashboard to settle.

## OUT OF TERRITORY
- `ytdl/web/ytdlweb/db.py:1599-1616` vs `:1674-1679`: `start_download`'s "is there anything to retry" gate counts `dl_state='downloading'` rows (`unfinished_downloads`) but `mark_pending` does not re-queue them, so a job whose rows are stuck `downloading` passes the 409 and then 400s; boot recovery resets them, so it only bites within one container lifetime. Not reported as a finding (pre-existing, self-healing).
