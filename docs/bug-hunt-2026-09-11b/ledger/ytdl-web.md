## The YouTube downloader's disk gate, its claim door and its page copy (CR-263, 2026-09-11)

The morning's CR-244 pass rebuilt this territory's free-space refusal, its
claim compare-and-set and its house-style scan. Every finding below is the
neighbour one of those fixes opened, plus the two coverage holes the same pass
left behind.

### CR-263a (ytdl-web-b-1) - ytdl-web-1's own guard left the stale number behind, so the press after the share came back said "free some space" - FIXED (`ytdl/web/ytdlweb/routes_api.py`)

`_refuse_if_full` called the two new helpers in the wrong order:
`_refuse_if_the_tree_is_gone(job)` RAISES, so on the `tree_missing` path
`_forget_free_at(outdir)` never ran and the container-overlay figure measured
while the bind mount was gone stayed in `_free_cache` for the rest of its 60 s
TTL, keyed on `PROJECTS_ROOT` and therefore on every project. The admin
remounts ten seconds later, the tree guard now passes, and the next press falls
through to the ordinary `disk_full` 409 quoting the overlay's 2 GB on a share
with 900 GB free: the exact sentence ytdl-web-1 exists to stop an editor from
acting on, emitted by ytdl-web-1's own fix. Only the third press succeeded. The
fix drops the cached number BEFORE the tree guard: a refusal of either shape is
the one moment a fresh stat is worth its cost.

### CR-263b (ytdl-web-b-2) - ytdl-web-4 removed the only free-space gate from exactly the jobs the NAS worker is the fallback executor for - FIXED (`ytdl/web/ytdlweb/worker.py`)

ytdl-web-4 skips `_refuse_if_full` for a job created local while requester-first
downloads are on, and that is right at the DOWNLOAD press: the editor's own disk
is the one that will be written and the companion decides for itself at claim
time. But a created-local job is only OFFERED. The tray is not running, the
claim is refused on a template or sidecar skew or an out-of-scope quality, the
machine is asleep, a lease expires and `_reclaim_local_job` takes the rest back
- and this worker becomes the executor, into the NAS tree, with no free-space
check anywhere in `worker.py`. For that whole class of job YTWEB-9 was undone: a
full NAS back to N opaque per-clip ENOSPC failures with no sentence before a
byte is fetched. `_no_room_note` now measures the tree once the grace has
expired and it is settled that the server is the executor, and ends the job
`failed` with the same one-sentence error the 409 carries. It fails OPEN on
anything it cannot measure, the rows keep their `pending` state so RETRY FAILED
re-queues exactly them, and it only runs for the jobs whose press skipped the
check. The helpers are imported inside the function because `routes_api`
imports `worker`.

### CR-263c (regression-26) - the new claim refusal reached the page as "this computer declined the job (HTTP 503)" - FIXED (`ytdl/web/static/app.js`, `ytdl/web/ytdlweb/db.py`)

`created_local` is fixed when the job is CREATED; the SPA re-reads its own
"download on this computer" switch at dispatch time. An editor who ticks the box
after the search was submitted therefore holds a job with `created_local = 0`
and hands it to their companion anyway: since ytdl-web-5 the claim CAS refuses
it, the fleet route answers 410 `created_widened`, the companion answers 503 and
the page painted a bare HTTP code, which reads as a broken tray on a download
that is going fine. `db.job_dict` now publishes `created_local` as a bool
through the same tolerant reader the claim gate uses, and `dispatchLocal` takes
it as a third argument: a job created on the server is never probed for, and the
editor gets a sentence saying which switch decided it and when to tick it. An
older server sends no field, which dispatches exactly as before.

### CR-263d (ytdl-web-b-4) - the worker held the claim door open for 4 s per job `claim_download` can no longer grant - FIXED (`ytdl/web/ytdlweb/worker.py`)

ytdl-web-5 made `created_local=0` a hard refusal at the CAS, but
`_await_local_claim` still gated on `config.LOCAL_DOWNLOAD` alone. Every job
created on the server cost `LOCAL_CLAIM_GRACE_SECONDS` of polled dead time on a
single-threaded worker that also serves the queue, and logged that the requester
had been given first refusal, which was no longer true of anybody. It now
returns False immediately for a job no machine can claim.

### CR-263e (ytdl-web-b-5) - `free_bytes_at` stopped caching its negative answer, so a hung mount was re-stat'd on every press - FIXED (`ytdl/web/ytdlweb/routes_api.py`)

The pre-ytdl-web-6 version stored `(now, None)` when no ancestor answered; the
refactor into `_answering_path` returned before the cache write. The docstring
still said the cache exists because "a stat per request against a NAS mount that
has gone away is a request that hangs, not one that answers" - precisely the
case that had become uncached, at up to eight `disk_usage` calls per press. The
miss is cached again.

### CR-263f (ytdl-web-b-6) - `_refuse_if_the_tree_is_gone` compared a database label against on-disk bytes with no normaliser - FIXED (`ytdl/web/ytdlweb/routes_api.py`)

The guard decided "the share is gone" from an exact-bytes stat of
`PROJECTS_ROOT/<project_label>`. CR-90's rule applies here as everywhere: a
label that reached this database from a Mac is NFD, the NAS writes NFC, and
`is_dir()` answers False for a folder that is there - so a project with a
decomposable accent in its name earned "the footage tree is not there, tell
whoever runs the dashboard" when the real fault was a full disk, and the admin
found nothing wrong. `_named_under_the_root` now walks the label segment by
segment against the root's entries with both sides NFC-normalised, and only a
miss there is a refusal. Safe in this one place because the path is compared,
never opened, renamed or deleted, and it is reached only on the way to a refusal
that has already been decided.

### CR-263g (ytdl-web-b-3) - the ' -- ' scan added for ytdl-web-7 did not cover the SPA, where most editor-facing copy is written - FIXED (`ytdl/web/tests/test_no_em_dash.py`)

The em-dash scan has three arms (HTML, JS, Python literals); the double-hyphen
scan had one, the Python arm over six modules. `static/app.js` writes every
toast, banner, status cell and hint on the page and was not scanned at all, nor
was `static/index.html`, so the owner's 2026-08-18 rule was enforced for HTTP
`detail` strings only and ytdl-web-7's own rationale ("nothing to stop a
seventh") still held for the biggest surface. Both arms now exist, stripping
comments the way the em-dash arms already do. Both files are clean today, so
this is coverage, not a live violation.

### Verification
- `ytdl/web/tests/test_bug_hunt_2026_09_11b_ytdl_web.py::test_the_press_after_the_share_comes_back_is_measured_fresh` -> fails at f1eeb42 (409 disk_full on the second press), passes now
- `...::test_the_server_will_not_execute_a_local_job_onto_a_full_tree` -> fails at f1eeb42 (the job ends `done` having fetched the clips onto a full tree), passes now
- `...::test_a_server_job_with_room_still_downloads` -> the fail-open half
- `...::test_the_double_hyphen_scan_covers_the_page_copy` -> fails at f1eeb42 (nothing in `test_no_em_dash.py` catches a doctored app.js or index.html), passes now
- `...::test_a_job_created_on_the_server_costs_no_grace_period` -> fails at f1eeb42 (it waits out the grace), passes now
- `...::test_a_job_created_local_still_gets_its_grace` -> the CR-34 half that must not regress
- `...::test_an_unreadable_tree_is_stat_ed_once_a_minute_not_once_a_press` -> fails at f1eeb42 (16 stats for two presses), passes now
- `...::test_a_decomposed_project_label_is_not_a_missing_tree` -> fails at f1eeb42 (`tree_missing` for a folder that is there), passes now; skipped on a filesystem that folds the two spellings
- `...::test_the_job_says_whether_it_was_created_local` and `...::test_the_spa_skips_the_hand_off_for_a_job_created_on_the_server` -> fail at f1eeb42 (raw int / no guard in the source), pass now
- `ytdl/web/tests/test_static_app.py::test_a_job_created_on_the_server_is_never_handed_to_this_computer` -> fails with the guard removed from app.js (the page probes 127.0.0.1 and toasts the HTTP code), passes now; the behavioural half of regression-26, run in the node harness
- Neighbours re-run green as a check on the worker/db changes: `test_local_download.py`, `test_worker.py`, `test_bug_hunt_2026_09_11_ytdl_web.py`, `test_static_app.py`, `test_no_em_dash.py` (382 + 32 passed)

### OWED TO ANOTHER TERRITORY
- comp-ytdl-jobs: `companion/src/ccsync_companion/ytdl_executor.py`: `heartbeat()`: send the `X-CCSync-Machine` header that `routes_fleet._machine_of` accepts as its shape-independent fallback (the header arm has no caller anywhere today, so it is untested surface rather than a working fallback). Optional on both sides; either may deploy first.
- dash-api / dash-mounts-ui (security-1): the ytdl mount's `_fleet_stamp` in `dashboard/src/ccsync_dashboard/ytdl.py` must ask the suspended-account predicate before `ytdlweb`'s fleet routes see the credential. `ytdlweb` has no notion of an account and should not grow one: the gate belongs in the dashboard half. Dashboard deploys first; no companion change.

### Owner decisions
- CR-263b ends a job that cannot fit as `failed` with a sentence, rather than pausing it or letting it fail clip by clip. That matches the circuit breaker's shape (rows stay pending, RETRY FAILED re-queues them) but it does mean a server-executed local job now has one more way to end without fetching anything.
- CR-263c's skip is a toast rather than silence: an editor who ticked the box mid-session is told the server has it and why. The alternative, silently dispatching and letting the 410 happen, is what the finding is about.
- CR-263f trusts a normalised match as evidence the share is present. It can only ever turn a `tree_missing` refusal back into the `disk_full` one it was masking, never the other way round.
