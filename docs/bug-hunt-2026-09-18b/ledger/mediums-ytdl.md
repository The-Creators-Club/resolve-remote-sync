# CR-305 - the ytdl web app's retry offer and its paste free-space guard - FIXED in repo 2026-09-18 (mediums wave, group `ytdl`)

Two confirmed mediums from `hunters/ytdl-web.md`, both of them the unfinished
half of a fix the 2026-09-18 pass landed (CR-286K and CR-286L).

### CR-305A (ytdl-web-1) - a job that failed before its first clip still had no retry button - FIXED (ytdl/web/ytdlweb/routes_api.py, db.py, static/app.js)

CR-286K decided the retry offer from `state.manifest.videos`, but `poll()`
deliberately never loads a manifest for a job whose phase is `failed`, and a
page reloading onto `#job=<id>` has none at all. In the one scenario the fix
names - `_no_room_note` or the tree guard failing the job ahead of the per-clip
loop, so `dl_failed` is 0 and every row is `pending` - `state.manifest` was
null, `pending` was 0, `stalled` was false and the button stayed hidden, which
is exactly what the failure's own last sentence tells the editor to press. The
fix carries the count on the poll instead: `db.pending_download_count` is one
`COUNT(*)`, `get_job` puts it on the JOB dict (`renderRetry(job)` is handed
nothing else), and `renderRetry` prefers `job.dl_pending` and keeps the
manifest count as the fallback for a page served by an older build. Tests drive
the real route for a failed job with three pending rows and for a done job with
none, plus a source assertion that `renderRetry` reads the poll.

### CR-305B (ytdl-web-2) - the paste free-space guard could never size a paste - FIXED (ytdl/web/ytdlweb/routes_api.py, worker.py)

`estimated_bytes` sums `r['duration']` and a pasted row has only
`video_id`/`url`: `parse_url_list` fetches no metadata and a `KIND_URLS` job
has no enrich phase, so the estimate was always 0 and both the press guard and
the worker's backstop collapsed to the flat 2 GB `UNKNOWN_ESTIMATE_FLOOR`
whether 1 or 40 links were pasted. CR-286L's own advertised scenario ("40 links
into a project with 6 GB left") was still accepted on both. `space_needed(rows,
quality)` is now the ONE place both callers get `(estimate, need)` from: a
measurable estimate keeps the `FREE_SPACE_FACTOR` headroom rule unchanged, and
an unmeasurable one becomes `max(UNKNOWN_ESTIMATE_FLOOR, len(rows) * rate *
TYPICAL_CLIP_SECONDS)` - three minutes at the job's own rung, no factor on top,
because doubling a guess is how a check that should refuse 40 links starts
refusing 3 that would have fit. A single pasted link therefore still meets the
old flat floor and still passes on 6 GB, which is pinned by its own test.

### Verification
- CR-305A: `tests/test_bug_hunt_2026_09_18b_ytdl.py` -
  `test_a_failed_jobs_poll_carries_the_count_the_retry_offer_needs`,
  `test_a_job_with_nothing_owed_is_offered_no_retry`,
  `test_render_retry_reads_the_poll_not_only_the_manifest` - all three fail on
  the pre-fix source (measured by reverting the three hunks in place).
- CR-305B: same file - `test_forty_pasted_links_are_refused_with_six_gb_free`
  and `test_the_workers_backstop_uses_the_same_floor` fail before, pass after;
  `test_one_pasted_link_still_passes_the_same_six_gb` and
  `test_space_needed_is_the_flat_floor_when_a_paste_is_small` are the
  no-over-refusal controls.
- Re-run green: `tests/test_bug_hunt_2026_09_18b_ytdl.py`,
  `tests/test_bug_hunt_2026_09_18_webapps_tools.py`, `tests/test_api.py`,
  `tests/test_bug_hunt_2026_09_11b_ytdl_web.py`, `tests/test_db.py`,
  `tests/test_says_what_it_knows.py` - 229 passed. `py_compile` on
  `routes_api.py`, `db.py`, `worker.py`.

### Not fixed
- ytdl-web-3, ytdl-web-4, ytdl-web-5, ytdl-web-6 are not in this group's
  assignment (low / downgraded); untouched.

### OWED TO ANOTHER GROUP
- None. Both fixes are inside `ytdl/web/*`.

### Deploy order
- One artefact: `ytdl/web` ships inside the dashboard image, page and API
  together, so there is no skew between the two halves of CR-305A. The page
  still tolerates an older API (no `dl_pending` -> the manifest fallback) and an
  older page tolerates the new API (it ignores the extra field), so a dashboard
  rollback is safe in both directions.

### Owner decisions
- None needed. `TYPICAL_CLIP_SECONDS = 180` is the one number a reader may want
  to argue with: it only ever raises the need for a paste whose rows carry no
  duration, and it is quoted in no editor-visible sentence (an unmeasurable
  refusal still says "this download needs room to work in").
