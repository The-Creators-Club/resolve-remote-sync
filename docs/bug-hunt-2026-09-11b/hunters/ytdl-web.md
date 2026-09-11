# ytdl-web - the YouTube downloader web app mounted at /ytdl (ytdlweb package, SPA, migrations)

Files read (with approximate coverage):
- `git diff 40f931a..HEAD -- ytdl/web/` in full (12 files, 582 insertions): the
  whole of this afternoon's CR-244 fix pass for ytdl-web-1..-7.
- `ytdl/web/ytdlweb/routes_api.py` (free-space block, `start_download`,
  `create_job`/`create_url_job` models, attestation route) ~40%
- `ytdl/web/ytdlweb/routes_fleet.py` (claim / heartbeat / manifest /
  clip_status, `_machine_of`, `_leaseholder_or_410`, `ClaimIn`) ~70%
- `ytdl/web/ytdlweb/db.py` (`claim_download`, `heartbeat_download`,
  `lease_held_by`, `is_leaseholder`, `created_widening_of`, migration
  registry) ~35%
- `ytdl/web/ytdlweb/worker.py` (`_phase_download`, `_await_local_claim`,
  `_reclaim_local_job`) ~25%
- `ytdl/web/ytdlweb/config.py` (LOCAL_DOWNLOAD block) ~20%
- `ytdl/web/ytdlweb/attestation.py`, `ai_backend.py` (diff hunks only)
- `ytdl/web/static/app.js` (`localWanted`, `initLocalSwitch`, health/flag
  wiring, plus a full non-comment scan for ' -- ') ~15%
- `ytdl/web/tests/test_bug_hunt_2026_09_11_ytdl_web.py`,
  `tests/test_no_em_dash.py` in full
- cross-checked the other side of the ytdl-web-3 wire in
  `companion/src/ccsync_companion/ytdl_executor.py` (`_this_machine_id`,
  `_with_machine`, `_machine_query`) - read only, not hunted.

Tests run:
`cd ytdl/web; ..\..\dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_ytdl_web.py tests/test_no_em_dash.py tests/test_local_download.py tests/test_api.py -q`
-> **236 passed**, 1 warning.
Plus one scratch test (written to the scratchpad, copied in, run, deleted) that
reproduces ytdl-web-b-1 below.

## Findings

### ytdl-web-b-1 - ytdl-web-1's own guard leaves the stale number behind, so the press after the share comes back says "free some space"
- Severity: medium
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/routes_api.py:1500` (`_refuse_if_the_tree_is_gone(job)` is called BEFORE `_forget_free_at(outdir)` and RAISES), with `ytdl/web/ytdlweb/routes_api.py:1463` (`_forget_free_at`)
- What: `_refuse_if_full` orders the two new helpers wrong. On the
  `tree_missing` path the guard raises out of the function, so
  `_forget_free_at(outdir)` never runs and the container-overlay figure
  measured while the bind mount was gone stays in `_free_cache` for the rest
  of its 60 s TTL, keyed on `PROJECTS_ROOT` (i.e. for every project). When the
  share comes back inside that window the tree guard now passes, so the next
  press falls through to the ordinary `disk_full` 409 quoting the overlay's 2
  GB - the exact sentence ytdl-web-1 was written to stop an editor from
  acting on, now emitted by ytdl-web-1's own fix.
- Failure scenario: the NAS bind mount drops; the editor presses DOWNLOAD and
  is correctly told `tree_missing`; the admin remounts ten seconds later; the
  editor presses DOWNLOAD again and is told "there is only 2.0 GB free where
  these clips go ... Free some space and press DOWNLOAD again" on a share with
  900 GB free. Only the third press succeeds.
- Evidence: scratch pytest against the real app (tmp root, `disk_usage`
  stubbed 2 GB, then the project folder created and `disk_usage` stubbed 900
  GB):
  `SECOND PRESS: 409 {'reason': 'disk_full', 'detail': 'there is only 2.0 GB free where these clips go (2026/FF5/Energy Transition/Youtube/reef) ... Free some space and press DOWNLOAD again.', 'free_bytes': 2000000000}` then
  `THIRD PRESS: 200 {'ok': True, 'queued': 1}`.
  `tests/test_bug_hunt_2026_09_11_ytdl_web.py` pins the first press
  (`tree_missing`) and separately pins the second press after freeing space on
  a healthy tree, but never the two together, which is why it is green.
- Ledger: CR-244 does not fix ytdl-web-1 (second half); new
- Suggested fix: call `_forget_free_at(outdir)` before
  `_refuse_if_the_tree_is_gone(job)` - a refusal of either shape is the one
  moment a fresh stat is worth its cost - and add the "mount returns inside
  the TTL" case to the regression test.

### ytdl-web-b-2 - ytdl-web-4 removed the only free-space gate from exactly the jobs the NAS worker is the fallback executor for
- Severity: medium
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/routes_api.py:1640` (`if config.LOCAL_DOWNLOAD and job_local: selection = []`), with `ytdl/web/ytdlweb/worker.py:1518` (`_phase_download`)
- What: the fix skips `_refuse_if_full` for every job created local while
  requester-first downloads are on, on the reasoning that "the companion runs
  its own free-space decision at claim time, on the disk that is actually
  written". But a created-local job is only *offered* to the companion: the
  worker waits `LOCAL_CLAIM_GRACE_SECONDS` (4 s) and then downloads it into
  the NAS tree itself whenever the tray is not running, the claim is refused
  (template/sidecar skew, out-of-scope quality, yt-dlp floor), the machine is
  asleep, or a lease expires and `_reclaim_local_job` takes the rest back.
  `worker.py` contains no free-space check at all (`grep -n
  "free\|disk_usage\|estimated_bytes" ytdlweb/worker.py` -> no output), so for
  that whole class of job YTWEB-9 is undone: a full NAS goes back to N opaque
  per-clip yt-dlp failures with no sentence before a byte is fetched.
- Failure scenario: `YTDL_LOCAL_DOWNLOAD=1`, editor ticks the local box,
  presses DOWNLOAD with their tray not running. Server skips the disk check
  (job_local true), grace expires, the worker downloads 40 clips into a tree
  with 2 GB free and the job ends `failed` with per-clip ffmpeg/ENOSPC noise.
- Evidence: read `_phase_download` and `_await_local_claim` end to end; the
  grace path returns only when `db.lease_active` becomes true, and every other
  exit falls through to the download loop. `estimated_bytes`/`free_bytes_at`
  have exactly one caller, `_refuse_if_full`, which this branch skips.
  `test_a_local_download_is_not_refused_by_the_servers_own_disk` asserts 200
  and stops there, so the neighbour is untested.
- Ledger: new (opens the neighbour of ytdl-web-4 / CR-244); regression of the
  YTWEB-9 guarantee for local jobs
- Suggested fix: keep the skip at the DOWNLOAD press (it is right - that
  filesystem may never be touched) but make the worker check before it becomes
  the executor: one `free_bytes_at(outdir)` / `estimated_bytes` comparison at
  the top of `_phase_download` after `_await_local_claim` returns False, ending
  the job with the same one-sentence `error` the 409 carries.

### ytdl-web-b-3 - the ' -- ' scan added for ytdl-web-7 does not cover the SPA, where most editor-facing copy is written
- Severity: low
- Confidence: CONFIRMED
- Where: `ytdl/web/tests/test_no_em_dash.py:128` (`DOUBLE_HYPHEN_MODULES`), and `_editor_facing_py()` at :133
- What: the em-dash scan has three arms (HTML, JS, Python literals); the new
  double-hyphen scan added for ytdl-web-7 has one, and it is the Python arm
  restricted to six modules. `static/app.js` writes every toast, banner,
  status cell and hint on the page and is not scanned for ' -- ' at all, nor
  is `static/index.html`. The finding's own rationale ("nothing to stop a
  seventh") therefore still holds for the surface that carries the most copy.
- Failure scenario: any future edit to an app.js toast or an index.html label
  reintroduces ' -- ' and the suite stays green; the owner's 2026-08-18 rule is
  enforced for HTTP `detail` strings only.
- Evidence: ran the same comment-stripping regexes the test uses over
  `static/app.js` and `static/index.html`: both are clean of ' -- ' today
  (so the gap is coverage, not a live violation), while
  `test_the_double_hyphen_scan_covers_the_modules_it_names` asserts only that
  the six Python names resolve.
- Ledger: CR-244 does not fully fix ytdl-web-7
- Suggested fix: add a `' -- '` parametrisation of the existing
  `_html_files()` / `_js_files()` arms (they already strip comments), and
  extend `test_the_scan_would_catch_a_regression` with the spelling.

### ytdl-web-b-4 - the worker still holds the claim door open for 4 s per job that claim_download can no longer grant
- Severity: low
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/worker.py:1507` (`_await_local_claim`), with `ytdl/web/ytdlweb/db.py:1151` (`AND COALESCE(created_local,1)=1`)
- What: ytdl-web-5 made `created_local=0` a hard refusal at the claim CAS, but
  `_await_local_claim` still gates only on `config.LOCAL_DOWNLOAD`. A job that
  no machine can ever claim still costs `LOCAL_CLAIM_GRACE_SECONDS` of polled
  dead time before the worker starts, once per job, on a single-threaded
  worker that also serves the queue.
- Failure scenario: `YTDL_LOCAL_DOWNLOAD=1` and an editor who has unticked the
  local box (or any job created before the flag was flipped on): every one of
  their downloads is 4 s slower to start and the log line says the requester
  was given first refusal, which is now untrue.
- Evidence: read both; `_await_local_claim` has no `created_local` /
  `created_widening_of` term, and `claim_download`'s WHERE now cannot match.
- Ledger: new (neighbour of ytdl-web-5 / CR-244)
- Suggested fix: `if not db.created_widening_of(job)[1]: return False` at the
  top of `_await_local_claim` (it already has the job row in
  `_phase_download`).

### ytdl-web-b-5 - `free_bytes_at` no longer caches its negative answer, so a hung mount is re-stat'd on every press
- Severity: low
- Confidence: PLAUSIBLE
- Where: `ytdl/web/ytdlweb/routes_api.py:1457` (`if probe is None: return None`)
- What: the pre-fix version stored `(now, None)` when no ancestor answered;
  the refactor into `_answering_path` returns before the cache write. The
  docstring still says the cache exists because "a stat per request against a
  NAS mount that has gone away is a request that hangs, not one that answers"
  - which is precisely the case that is now uncached.
- Failure scenario: a mount whose `statvfs` errors rather than hangs on every
  ancestor (an unreachable NFS/SMB share with `PROJECTS_ROOT` at `/`-less
  depth): each DOWNLOAD press pays up to eight `disk_usage` calls instead of
  one per minute.
- Evidence: read; not reproduced, because on Linux `/` always answers so
  `probe is None` needs every one of the eight probes to raise - which is why
  this is PLAUSIBLE, not CONFIRMED.
- Ledger: new (introduced by ytdl-web-6 / CR-244's refactor)
- Suggested fix: cache the miss too - `_free_cache[key] = (now, None)` before
  returning - which is also the pre-fix behaviour.

### ytdl-web-b-6 - `_refuse_if_the_tree_is_gone` compares a database label against on-disk bytes with no normaliser
- Severity: low
- Confidence: PLAUSIBLE
- Where: `ytdl/web/ytdlweb/routes_api.py:1527` (`project_dir.is_dir()`)
- What: the new guard decides "the share is gone" from an exact-bytes stat of
  `PROJECTS_ROOT/<project_label>`. CLAUDE.md's CR-90 rule is that a path one
  platform reported is not `==` a path another reported: a project label that
  reached the dashboard database from a Mac is NFD, the NAS is NFC, and
  `is_dir()` answers False for a folder that is there.
- Failure scenario: a project whose name carries a decomposable accent
  (`Matej Simalcik`-shaped) and a genuinely low-but-not-empty disk: the editor
  is told "the footage tree is not there ... tell whoever runs the dashboard"
  when the real fault is a full disk, and the admin finds nothing wrong.
- Evidence: read only. Narrow: it fires only on the way to a disk_full
  refusal, and only for a decomposable label (CJK never decomposes), which is
  why it is low and PLAUSIBLE.
- Ledger: related to CR-90
- Suggested fix: fall back to a normalised comparison of `PROJECTS_ROOT`'s
  entries (NFC both sides) before concluding the tree is gone; this path only
  stats, it never opens, so normalising is safe here.

## Coverage note

What I did not get to: `claude_cli.py`, `ytdl_evidence.py`, `ytdl_canary.py`,
`projects.py`, `session.py`/`identity.py`, `vendor/downloader.py` and
`vendor/ytsearch.py`; the terms-review/queue routes and `migrations/001..012`;
most of `static/app.js` (I read only the local-download wiring and ran a text
scan over the rest) and all of `static/style.css` / `index.html`. I ran four
test files, not the whole ytdl suite (owner rule: the gate runs once,
centrally).

What the suite does not cover, beyond the three gaps named in findings b-1,
b-2 and b-3: nothing in `tests/` exercises the NAS worker as the fallback
executor for a *created-local* job, so the whole of b-2's path is untested;
`_await_local_claim` is only tested through `test_local_download.py`'s claim
happy path; and no test pins `free_bytes_at`'s cache-miss behaviour (b-5).
The ytdl-web-3 wire is the one thing in this diff that landed on BOTH sides
cleanly - `ytdl_executor._with_machine` / `_machine_query` send exactly what
`_machine_of` reads, the field is optional in both directions, and
`test_a_heartbeat_with_no_machine_id_is_the_older_companion` plus
`test_a_holder_that_did_not_say_which_machine_is_not_evicted` pin the
0.9.65..0.9.70 skew properly. The residual per-editor hole (a holder whose
`machine.json` is unreadable claims with `claimed_machine` NULL and is then
heartbeat-able by any of that editor's computers) is deliberate and
documented in `db.lease_held_by`; I did not count it as a finding.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/ytdl_executor.py:1159`: `heartbeat()` never sends the `X-CCSync-Machine` header that `routes_fleet._machine_of` accepts as its "shape-independent fallback" - the header arm of that helper has no caller anywhere, so it is untested surface rather than a working fallback.
