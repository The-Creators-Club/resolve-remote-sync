# ytdl-web - the YouTube downloader service (ytdl/web)

Files read (with approximate coverage):
- `ytdl/web/ytdlweb/routes_api.py` (~80%: the whole `097f5a3..HEAD` diff, every
  route signature, the new free-space block, `health_snapshot`,
  `_plugin_install_state`, `_pot_provider_state`, `start_download`, `cancel`)
- `ytdl/web/ytdlweb/routes_fleet.py` (~90%: identity/token gates, `claim`,
  `heartbeat`, `clip_status`, `_record_done`, `_hand_back_to_the_server`)
- `ytdl/web/ytdlweb/db.py` (~60%: migrations table + predicates, `create_job`,
  `create_url_job`, `active_job`, `parked_jobs`, `fleet_ahead`,
  `claim_next_job`, the whole lease block, `mark_pending`,
  `selected_for_download`, `video_reveal_path`, `job_dict`, `queue_dict`)
- `ytdl/web/ytdlweb/projects.py` (~100% of `ticked_projects`/`resolve_project`)
- `ytdl/web/ytdlweb/ai_backend.py` (~70%: provider resolution, key handling,
  `_complete_openai_compatible`, `_http_error`, `_complete_cli`, `_cli_env`)
- `ytdl/web/ytdlweb/claude_cli.py` (the `_invoke` diff + the whole health cache)
- `ytdl/web/ytdlweb/worker.py` (~35%: `_run`, `recheck_health`, the cancel
  checks, `identical_failure_note`, `DEGRADED_NOTE`)
- `ytdl/web/ytdlweb/config.py` (skim), `ytdl_common.py` (compared against the
  companion's vendored copy), `migrations/013`, `migrations/014`, `schema.sql`
- `ytdl/web/static/app.js` (~45%: the whole diff - `queuedWait`,
  `renderWaiting`, `freeNote`, `sizeEstimate`, `probeLocalMachine`,
  `localWanted`, `initLocalSwitch`, `runSearch`, `runUrls`, `startDownload`,
  `api`/`post`), `static/index.html` (skim)
- `ytdl/web/tests/test_no_em_dash.py`, `tests/test_says_what_it_knows.py`
  (free-space half), spot reads of `tests/test_api.py`
- Cross-side: `companion/src/ccsync_companion/ytdl_executor.py` (claim body,
  error model, `_this_machine_id`), `companion/.../ytdl_common.py`

Tests run: `cd ytdl\web; ..\..\dashboard\.venv\Scripts\python.exe -m pytest tests -q`
-> **927 passed, 1 warning in 26.04s** (no reds at HEAD).

## Findings

### ytdl-web-1 - a lost Projects mount reads as "the disk is full", and refuses every download
- Severity: medium
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/routes_api.py:1395-1430` (`free_bytes_at`) and
  `:1433-1455` (`_refuse_if_full`), reached from `start_download`
  (`:1525-1540`)
- What: `free_bytes_at(outdir)` calls `shutil.disk_usage` on the first ancestor
  that EXISTS. In the container `YTDL_PROJECTS_ROOT` is a bind mount, and a
  mount that has gone away leaves the mount-point directory behind on the
  container's own overlay filesystem - so `disk_usage` succeeds on the first
  probe and reports the OVERLAY's free space, not the tree's. The walk-up loop
  has the same property one level higher. The function's only "I cannot tell"
  answer is an exception, which this case never raises, so the fail-open path
  designed for exactly this state (`free is None` -> return) is unreachable
  here.
- Failure scenario: the NAS share unmounts under the dashboard container (a
  TrueNAS restart, an SMB/NFS blip). A container whose writable layer has ~2 GB
  free then answers every `POST /api/jobs/{id}/download` with `409 disk_full`:
  "there is only 2.0 GB free where these clips go (2026/FF5 Energy
  Transition/Youtube/...), and these 40 clips need about 22 GB, so nothing was
  started. Free some space and press DOWNLOAD again." The editor is sent to
  delete footage; the actual fault (no tree at all) is named nowhere, and the
  same refusal comes back after they do.
- Evidence: read `free_bytes_at` - the `try: shutil.disk_usage(probe)` /
  `except (OSError, ValueError)` pair only steps up on a path that does not
  exist; nothing compares the answering path to the one asked about. The
  suite's own test (`tests/test_says_what_it_knows.py:203`
  `test_free_space_is_read_from_the_nearest_real_directory_and_cached`) pins
  the walk-up as intended behaviour and never covers "the ancestor is on a
  different filesystem". Every other test of this feature monkeypatches
  `free_bytes_at` away entirely (`:153,:173,:184,:194,:199`), so no test
  exercises the real function against the refusal.
- Ledger: new (the feature is YTWEB-9, 2026-09-03)
- Suggested fix: refuse only when the measured filesystem is the destination's.
  Record which path answered and compare `os.stat(...).st_dev` (or
  `Path.is_mount()`) against `PROJECTS_ROOT`; if they differ, return None (fail
  open) and let the existing "the tree does not look like the tree" machinery
  say what is actually wrong.

### ytdl-web-2 - "Free some space and press DOWNLOAD again" does not work for 60 seconds
- Severity: medium
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/routes_api.py:1395-1430` (`_FREE_TTL = 60`,
  `_free_cache`), message at `:1448-1454`
- What: the refusal's own instruction is the one action the 60 s cache
  invalidates. `free_bytes_at` serves the cached number for a minute, so an
  editor who deletes 200 GB and presses DOWNLOAD again gets a byte-identical
  409 quoting the pre-deletion figure. Nothing invalidates the entry on a
  refusal, and there is no way for the editor to force a re-stat.
- Failure scenario: 40-clip manifest, NAS at 8 GB free, estimate 11 GB. Editor
  reads the refusal, frees 300 GB, presses DOWNLOAD: same 409, same "only
  8.0 GB free". The reasonable next conclusion is that DOWNLOAD is broken.
- Evidence: `tests/test_says_what_it_knows.py:203-228` proves the cache is
  consulted for 60 s and only expires at `now + 61`. `_refuse_if_full` calls
  `free_bytes_at(outdir)` with no `now` override and never clears the key.
- Ledger: new
- Suggested fix: drop (or bypass) the cache entry for that path when the check
  refuses - the next press is precisely when a fresh stat is worth its cost -
  or cache only passes, never refusals.

### ytdl-web-3 - one editor's two computers can both download the same job after a lease expiry
- Severity: medium
- Confidence: CONFIRMED (from code; not reproduced against a live companion)
- Where: `ytdl/web/ytdlweb/db.py:1054-1071` (`is_leaseholder`, per-EDITOR) and
  `ytdl/web/ytdlweb/routes_fleet.py:190-216` (`_leaseholder_or_410`), `:525-545`
  (`heartbeat`), `:661-716` (`clip_status`); companion side
  `companion/src/ccsync_companion/ytdl_executor.py` (the heartbeat and status
  bodies carry no machine id)
- What: CR-66 narrowed the lease key to `(editor, machine_id)` at the CLAIM
  door only. `heartbeat`, `download-manifest` and `clip_status` all go through
  `is_leaseholder(job, editor)`, which passes `machine=None` and therefore
  answers True for ANY of that editor's computers. `is_leaseholder`'s docstring
  justifies this with "the machine that could not claim never gets a job id to
  post about" - which does not cover the machine that DID claim and then lost
  the lease by expiry.
- Failure scenario: laptop A claims job 88 and stalls longer than
  `LEASE_SECONDS` (sleep, a wifi drop, a paused yt-dlp). Desktop B claims it,
  legitimately - the CAS allows it once the lease is stale. A wakes up: its
  heartbeat is accepted (per-editor) and RE-EXTENDS the lease that now belongs
  to B, its manifest fetch is accepted, and its per-clip `done` posts are
  accepted and recorded with `download_host = claimed_by`. Both machines fetch
  all 40 clips into two trees and lane A carries both up - the
  two-spellings-in-two-trees outcome CR-66 was written to end. Neither
  companion is ever told 410, so neither stops.
- Evidence: `db.lease_held_by` (`db.py:1029-1051`) returns True when
  `machine is None`; `is_leaseholder` always calls it that way;
  `heartbeat_download` is keyed on `job['claimed_by']` alone
  (`routes_fleet.py:539`). `HeartbeatIn` has only `editor: str = ''` and
  `ClipStatusIn` has no machine field, so the server cannot currently tell the
  two apart even if it wanted to.
- Ledger: new; partial regression of the property CR-66 established
- Suggested fix: carry `machine_id` on the heartbeat and clip-status bodies
  (absent = today's per-editor answer, so an older companion is unchanged) and
  pass it into `is_leaseholder`; a heartbeat from a machine that is not the
  recorded holder must be 410 so the stale executor stops.

### ytdl-web-4 - the free-space gate measures the wrong computer for a requester-first download
- Severity: low
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/routes_api.py:1525-1540` (`start_download`)
- What: the check runs BEFORE any claim exists, so it always sizes
  `config.PROJECTS_ROOT` - the NAS mount inside the dashboard container. When
  `YTDL_LOCAL_DOWNLOAD=1` the clips are usually fetched onto the requesting
  editor's own disk first (the companion writes them, lane A carries them up
  later), and the companion does its own free-space decision at claim time. The
  server's refusal therefore blocks a download that was never going to touch
  the measured filesystem at that moment, and its sentence ("there is only X
  free where these clips go") names a path the editor cannot act on from the
  machine they are sitting at.
- Failure scenario: NAS at 9 GB free; an editor with 4 TB free locally presses
  DOWNLOAD on a 22 GB manifest and is refused outright, with no override.
- Evidence: `start_download` has no reference to `download_mode`,
  `config.LOCAL_DOWNLOAD` or the claim; `db.claim_download` (the only thing
  that sets `download_mode='local'`) runs later, from `routes_fleet.claim`.
- Ledger: new (YTWEB-9's blind spot)
- Suggested fix: when `config.LOCAL_DOWNLOAD` is on, downgrade the refusal to a
  warning the SPA shows (the number is already on the page via `sizeEstimate`)
  and let the companion's own check - which reads the disk that will actually
  be written - be the one that refuses.

### ytdl-web-5 - the server-side destination check is disabled by a flag the client sends
- Severity: medium
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/routes_api.py:14-19` (the module docstring's stated
  invariant), `:683-688` and `:971-976`
  (`resolve_project(..., local=req.local)`),
  `ytdl/web/ytdlweb/projects.py:196-201` (`if (not local) or _wired(...) or
  _base_only(...): rows = _ALL_SQL`), `static/app.js:2157`
  (`local: localWanted()`), `static/app.js:2396-2405` (`localWanted` returns
  false whenever `state.localDownload` is false)
- What: `NewJob.local` is a client-supplied boolean, and `local=false` widens
  `ticked_projects` to EVERY active project for ANY editor. The fleet ships
  with `YTDL_LOCAL_DOWNLOAD` off, so `localWanted()` is false and the SPA posts
  `local: false` on every search and every paste - meaning the check the module
  header describes ("without it an editor could post any slug and drop 40
  videos into a project they do not sync") currently permits exactly that, for
  every editor, by default. migration 013 / `schema.sql` then persist the
  widening onto the row and `start_download` re-validates under it, so the
  security property those comments claim ("read from the JOB and never from the
  request... a client-supplied local=0 there would be any editor writing into
  any active project") is true only of the second door; the first door takes
  the client's word.
- Failure scenario: any signed-in editor posts `{"project_slug": "<any active
  project>", "local": false, ...}` to `/ytdl/api/jobs` - which is byte-for-byte
  what their own page already sends - and 40 clips land in a project they do
  not sync and cannot see. No curl needed: unticking "on this machine" does it.
- Evidence: read `projects.ticked_projects`; `not local` alone selects
  `_ALL_SQL`. Confirmed the SPA's default by reading `localWanted()`:
  `if (!state.localDownload) return false;`.
- Ledger: related to CR-96 (half 1 is a deliberate widening, KNOWN_BUGS around
  line 2992). The DEFECT is that the widening is self-asserted by the client
  and that three separate comments still claim an invariant the code does not
  hold - an owner reading them would believe destinations are constrained when
  they are not.
- Suggested fix: decide, then say so. Either derive `local` server-side
  (`config.LOCAL_DOWNLOAD` plus what the machine actually is) instead of
  trusting the field, or accept the widening explicitly and correct the
  docstrings in `routes_api.py`, `schema.sql` and `migrations/013` so nobody
  later relies on a check that does not exist.

### ytdl-web-6 - `_free_cache` is never evicted
- Severity: low
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/routes_api.py:1391-1430`
- What: `_free_cache` gains one entry per distinct destination
  (`<project>/Youtube/<term_dir>`) and nothing ever removes one. Every search
  has its own `term_dir`, so the dict grows once per search for the life of the
  container.
- Failure scenario: a slow, bounded leak (a few hundred bytes per search) in
  the dashboard's single uvicorn process. Not user-visible; recorded because it
  is a module-level cache with no ceiling in a process meant to run for months.
- Evidence: the only writes are `_free_cache[key] = (now, free)`; the only read
  is the TTL check. `tests/test_says_what_it_knows.py:207` clears it by hand,
  which is the tell.
- Ledger: new
- Suggested fix: key the cache on the FILESYSTEM (the resolved mount or
  `st_dev`) rather than the destination path - one entry, and it is also the
  correct granularity for the number being cached.

### ytdl-web-7 - the " -- " cleanup was applied to one string; six other editor-facing ones still carry it
- Severity: low
- Confidence: CONFIRMED
- Where: `ytdl/web/ytdlweb/routes_api.py:687`, `:975`, `:97`;
  `ytdl/web/ytdlweb/ai_backend.py:306`, `:342`, `:758`;
  `ytdl/web/ytdlweb/attestation.py:46` (the legal notice the browser paints)
- What: YTWEB-7 reworded `worker.DEGRADED_NOTE` specifically because "the
  em-dash scan does not catch '--'", but the remaining editor-facing strings
  with the same spelling were not touched and no test was added - so the
  house-style gap the fix identified is still open and still unguarded.
- Failure scenario: cosmetic only. An editor sees "Tick it on the dashboard
  first -- downloads go into the projects you sync." in a toast.
- Evidence: an AST walk over `ytdlweb/**.py` skipping docstrings, searching for
  `' -- '`, run from the dashboard venv; the seven hits above are the ones on
  strings that reach a person (the rest are log lines and prompt text).
- Ledger: new (follow-on to YTWEB-7)
- Suggested fix: reword the seven, and extend `tests/test_no_em_dash.py`'s
  Python half to flag `' -- '` in the literals that reach an editor
  (HTTPException details and the attestation text).

## Coverage note
Not reached: `ytdlweb/vendor/` (the downloader itself) beyond its em-dash scan;
`ytsearch`/dedupe; `ytdl_canary.py`; server-side cookie handling (I confirmed
only that no cookie value is formatted into a response or log in the files I
read, not that the jar is never read into memory elsewhere); the Claude prompt
builders in `claude_cli.py` past their injection posture; most of `worker.py`'s
search/enrich/filter phases; and `tests/test_static_app.py` (4,826 lines),
which I only sampled.

Checked and found SOUND, for the record:
- migrations 013/014 are additive `ALTER TABLE`s with predicates in the same
  shape as 005/007/011; a v12 database (the last shipped build) migrates
  cleanly and re-running is a no-op - the predicates read `_columns`, never
  `user_version`.
- `ytdl_common.py` is identical (comments stripped) between
  `ytdl/web/ytdlweb/` and `companion/src/ccsync_companion/`, and
  TEMPLATE/SIDECAR versions agree at 1/1.
- `db.fleet_ahead`'s candidate set and ORDER BY are character-for-character
  `claim_next_job`'s, as its docstring claims.
- `db.selected_for_download`'s WHERE clause is identical to `mark_pending`'s.
- every `routes_api` write route resolves `current_user(request)` and then
  `_job_or_404(c, job_id, user)`; every `routes_fleet` route goes through
  `require_fleet_caller` (bound token AND signed identity, refusing a mismatch)
  and then `_leaseholder_or_410`.
- no API key is logged, repr'd or returned (`Provider.__repr__` prints
  `key=set|unset`; the CLI environment is allow-listed in `_cli_env`).
- `static/app.js` has no root-relative `/api|/static|/media` URL; the only two
  absolute URLs are the ytimg thumbnail and the deliberate
  `http://127.0.0.1:8899` loopback. `index.html`'s `href="/"` back-link is
  intentional.
- `_refuse_a_name_that_is_not_a_filename` does close the `'.'`/`'..'` hole
  (ytdl-web-3 of the last hunt); `os.path.basename` upstream already removes
  the separator cases.
- the boot order in `app.js` is right: `loadHealth` (which calls
  `initLocalSwitch`, so localStorage is honoured) is awaited before
  `probeLocalMachine`, which is awaited before `loadProjects`.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/ytdl.py:760-770`: the `health_snapshot`
  bridge probes for the keyword-less older signature with a retry; worth a
  glance from whoever owns the dashboard mount, since a partial call there
  would make the ytdl checks read `[ NOT CHECKED ]` rather than fail.
