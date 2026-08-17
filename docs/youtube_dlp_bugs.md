# ytdl bug hunt — 2026-08-11

**RESOLVED same day: all 45 findings fixed in the 2026-08-11 fix pass** (three
Opus agents — worker/vendor, API/DB/claude seam, frontend SPA — plus the
orchestrator for the four fix sites shared with concurrently-edited dashboard
and ops files). Suite went 103 → 185+21 tests, all green. Notes: YTDL-6 is
closed by DASH-3's dashboard-wide 4 MB default body cap rather than a
ytdl-specific limit; YTDL-29's fix withholds the identity header for a
non-latin-1 name (loud 401, never a lossy collision); schema is now v3
(`term_dir` column, one-active-job unique index with duplicate retirement);
`test_static_app.py`'s 13 behavioural tests need node and skip without it
(KNOWN_BUGS R7). Still-open residuals live in KNOWN_BUGS.md.

**2026-08-17 — some of these code sites no longer exist.** The
commercial-readiness pass rewrote the seams several findings were written
against; the findings stay for their write-ups, but read them with this:

- **There is no `claude` CLI and no `-p` argv any more** (item 1). The two AI
  calls go through the `anthropic` SDK with the customer's `ANTHROPIC_API_KEY`,
  so `_invoke` builds a Messages request instead of a command line. **YTDL-7**
  (an un-capped topic hitting execve's per-arg limit, misclassified as "claude
  CLI not installed") cannot happen at all now — there is no argv; the topic is
  a fenced data block in the user turn. The claude-home volume, the one-time
  `/login` and the `/opt/claude` mount are all gone with it. The four
  `claude_*:` prefixes survive unchanged (the SPA's hint map depends on them);
  what `claude_auth:` and `claude_missing:` MEAN has changed — see
  `ytdl/web/DEPLOY.md`.
- **deno, the PO-token sidecar and the NAS-side signed-in `cookies.txt` are now
  opt-in per customer** (`site.toml` `[features] youtube_unblock`, item 3), so
  **YTDL-24**'s "a missing deno produces per-video failures" is the EXPECTED
  state on a site that has not enabled them, not a fault to report. `/api/health`
  still surfaces the JS-runtime answer; read it beside the flag.
- **`YTDL_DEV_USER` is gone** (item 15) — the identity stand-in is now an
  in-process `session.set_test_user()` call that no environment variable can
  reach.
- **The whole app is unmounted unless `[features] youtube_download` is set**
  (item 2), and every download path additionally refuses until the editor has
  accepted the rights/ToS attestation — see
  `docs/legal/YOUTUBE_FEATURE_NOTICE.md`.

Findings from a six-hunter sweep of `ytdl/` (worker + claude_cli, db + path
safety, API + dashboard mount, vendored downloader, frontend SPA, and
cross-component contracts + tests), orchestrated and cross-verified. The text
below is the original worklist, kept for the write-ups. `file:line` is as of commit `3b0fc19`
(the ytdl landing commit is `ded8dd4`); the suite currently passes 103/103
under the dashboard venv, so none of this is caught by tests today.

**Confidence markers:**
- `[verified]` — the orchestrator re-checked it against source, or a hunter
  reproduced it by running code (noted which).
- `[confirmed xN]` — N hunters found it independently.
- `[analysis]` — one hunter's reading; mechanics traced but not re-derived.

**45 findings: 2 critical, 12 major, 31 minor.** Recurring shapes worth
reading first: the `[id]`-in-filename dedupe trusts filenames it shouldn't
(YTDL-2, YTDL-3, YTDL-15, YTDL-27), terminal-state handling has one-way doors
(YTDL-1, YTDL-5, YTDL-12, YTDL-16), and the ledger's old theme — bugs masked
by tests that assert the wrong thing — is here too (YTDL-1, YTDL-14, YTDL-20,
YTDL-41, YTDL-44).

---

## Critical

### YTDL-1 — cancelling a job at `ready_for_review` is a silent no-op that permanently locks the editor out [verified — reproduced by running code; confirmed x4]
`routes_api.py:236-250` (cancel), `db.py:281-291` (`claim_next_job`),
`db.py:217-225` (`active_job`). The cancel route sets `cancel_requested=1` and
nudges the worker for any non-terminal phase — but the flag is honoured only
inside `run_job`, which the worker reaches only for phases `claim_next_job`
selects, and that list deliberately excludes `ready_for_review` ("waiting for
a human"). Nothing ever transitions a cancelled review-phase job to
`cancelled`, while `active_job` deliberately counts `ready_for_review` as
active. **Failure:** editor's search reaches review; they press CANCEL (the
button is visible — `app.js:279` hides it only for terminal phases — and the
route answers `{ok:true}` with a "cancelling…" toast). The job sits at
`ready_for_review` forever and every new `POST /api/jobs` 409s with "you
already have a job in progress". A container restart does not help
(`reset_stale_jobs` deliberately leaves `ready_for_review` alone). The one
in-band escape — press DOWNLOAD so the worker claims the job and insta-cancels
— is unavailable in the *common* trigger case: a re-search of an
already-downloaded topic marks every video `duplicate=1, selected=0`, so
DOWNLOAD 400s ("nothing is selected…") and the SPA disables it. The editor is
blocked until someone edits `ytdl.db` by hand. Side defect: `cancel_requested`
is never cleared, so after a no-op cancel a later legitimate DOWNLOAD press
instantly cancels the job. Masking test: `test_api.py:218` asserts cancel only
sets the flag, at phase `searching`; no test cancels a review-phase job.
**Fix:** in the cancel handler (or `db.request_cancel`), move
`ready_for_review` (and `queued`) straight to `cancelled` — no worker phase is
in flight; clear `cancel_requested` in `start_download`; add the missing test.

### YTDL-2 — an interrupted download's `.part` file satisfies the `[id]` dedupe, so the clip is marked duplicate and never resumed [verified]
`vendor/ytsearch.py:60,95-99` (`existing_id_locations` rglobs every file and
takes the first `[11-char]` match in `p.stem`), consumed at `worker.py:521`
(pre-download re-check) and `:409` (`mark_duplicates`). yt-dlp's in-flight
artifacts — `Title [id].f616.mp4.part`, `.ytdl` sidecars, an unmerged
`Title [id].f251.webm`, and `ensure_edit_ready`'s `Title [id].editready.mp4` —
all carry the `[id]` in their stem, so a *partial* file counts as "the fleet
already has it". **Failure:** container restart (redeploy, OOM, NAS reboot)
mid-download. Boot recovery correctly re-queues the video (`worker.py:114`),
`_sweep_stale` deliberately keeps the <24h-old `.part` for resume — then the
re-check finds the id in the `.part` stem and marks the video `skipped,
duplicate=1`. The download never resumes, the UI says the clip exists, and
what is on disk is a 0600 fragment that the sweep deletes 24 hours later,
leaving nothing. The worker's own comment ("its .part turned into a real
file") assumes only completed files match — false. **Fix:** ignore files whose
name carries `.part`/`.ytdl`/`.f<n>`/`.editready` markers, or require the
`[id]` to sit immediately before the final media extension (see also YTDL-27).

---

## Major — download pipeline

### YTDL-3 — a failed edit-ready conversion leaves a 0600, unledgered file that permanently blocks the clip via dedupe [confirmed x2]
`vendor/downloader.py:261-267` (`ensure_edit_ready` cleans up only its tmp and
raises), `worker.py:551-562` (except path marks the row `failed` and never
learns the filepath — so no chmod, no ledger row). The completed original
download (e.g. VP9-in-mp4) stays in the term folder under its
`… [id].mp4` name. **Failure:** editor picks 1440p/2160p (above 1080p YouTube
serves only VP9/AV1, so conversion always runs); ffmpeg errors or the disk
fills → row shows `failed`, job ends `done`. On retry (new search — the only
route, see YTDL-16), `existing_ids` finds the leftover's `[id]` and marks the
video `skipped, duplicate` — pointing at a Resolve-undecodable VP9 file with
permissions no editor can even read over SMB (umask 077 → 0600). Unrecoverable
through the UI. **Fix:** on the download-exception path delete or rename (drop
the `[id]`) any freshly-landed output for that video; only chmod+ledger on
success.

### YTDL-4 — `prefer_avc` silently caps 1440p/2160p/"best" at ~1080p; the documented VP9 fallthrough is dead code [verified]
`vendor/downloader.py:57-73` (`format_selector`), invoked with
`prefer_avc=True` from `worker.py:552` (`edit_codec='h264'`). For 2160p the
selector is `bestvideo[height<=2160][vcodec^=avc1]+…/…/generic`; yt-dlp takes
the first *satisfiable* alternative, and `[height<=2160][vcodec^=avc1]` is
satisfied by the 1080p AVC stream virtually every YouTube video has — so the
generic VP9/AV1 alternative never fires. The docstring's "anything above that
falls through to VP9/AV1 and gets converted afterwards" is false. **Failure:**
editor selects 2160p (reachable — `routes_api.py:106` whitelists
`best/2160p/1440p`) on a 4K source; the job downloads 1080p, reports success,
and the whole `ensure_edit_ready` conversion path for high-res sources is
unreachable. Silent quality loss, no error anywhere. **Fix:** only prepend the
AVC alternatives when `h <= 1080`; for `best/1440p/2160p` use the generic
selector and let the conversion do its job.

### YTDL-5 — the cached claude-health state can only degrade; one transient failure shows red fleet-wide until container restart [verified; confirmed x2]
`claude_cli.py:342-396`, `worker.py:123` (the only `refresh_health` call, at
worker-thread start). Every later update is `note_failure`
(`worker.py:185,376`), which writes only failure states; no success path ever
writes `ok` back and nothing re-probes — the comment at `claude_cli.py:346`
("the worker calls refresh() on every failure") describes code that does not
exist, and `_MIN_PROBE_INTERVAL` guards a path with no callers. **Failure:**
one `claude_timeout:` blip → `/ytdl/api/health` reports `timeout` to every
page load, forever. An admin follows DEPLOY.md, runs `/login`, verifies with
`claude -p "say ok"` — the banner stays; even a subsequently successful job
doesn't clear it. Only restarting the dashboard container (taking the fleet
status page down) resets it, so the documented ops procedure appears not to
work. Masking test: `test_claude_cli.py:220-234` exercises `refresh_health`
only with `force=True` and never asserts a failure→ok transition on the paths
the worker actually uses. **Fix:** call `refresh_health()` (interval-limited —
the machinery exists) after a claude failure, and/or write `ok` into the cache
on each successful `_invoke`.

### YTDL-6 — every `/ytdl` write path buffers an unbounded request body in the single-worker container (DASH-3 recurrence) [verified]
`dashboard/src/ccsync_dashboard/app.py:54-68` (`_BODY_LIMITS` /
`_BODY_LIMIT_PREFIXES` — entries for `/api/v1/report`, packages and
`/music/api/ingest`, nothing for `/ytdl`), reaching `routes_api.py:92,182,205`.
ytdlweb imposes no cap of its own; FastAPI reads the entire body into memory
before pydantic sees it. **Failure:** any logged-in editor (or stolen session
cookie) POSTs a multi-GB stream to `/ytdl/api/jobs` → the uid-3000
single-worker uvicorn buffers it resident → OOM kill takes down the fleet
sync-status dashboard — the one outcome the mount contract exists to prevent,
and a fresh instance of the exact class KNOWN_BUGS DASH-3 documents. **Fix:**
add a small `("/ytdl/api/", "POST", …64 KB…)` prefix limit (or enforce it in
`YtdlGate`, which already sees every request).

### YTDL-7 — an un-capped topic string hits execve's per-arg limit, is misclassified as "claude CLI not installed", and pins that false banner fleet-wide [analysis]
`routes_api.py:95-97` (`NewJob.term`: only `.strip()` + non-empty),
`claude_cli.py:113-133` (`_invoke` embeds the term in the `-p` argv element;
`except OSError → ClaudeError(ERR_MISSING)`). Linux `MAX_ARG_STRLEN` is
128 KiB per argument, so a term ≳127 KiB makes `subprocess.run` raise
`OSError(E2BIG)` → classified as `ERR_MISSING`. **Failure:** an editor pastes
a huge text blob as the topic (well under any sane body cap, so YTDL-6's fix
alone doesn't close this) → the job fails with the wrong ops hint ("the claude
CLI is not installed in the dashboard container") AND `note_failure` writes
`missing` into the shared health cache — so every editor sees the red
"not installed" banner until container restart (YTDL-5). **Fix:** cap `term`
in `create_job` (e.g. 400 chars) and 400 on excess.

## Major — frontend

### YTDL-8 — SEARCH while a job is active tears down the live job view before the server says no [verified]
`static/app.js:475-492` (`runSearch` calls `detach()` — stops polling, clears
`location.hash`, hides the progress/downloads/review panels — *before* the
`POST api/jobs` is validated). The server correctly 409s when a job is active,
and the 409 detail carries `job_id` — but `api()` (`app.js:72`) extracts only
the message string and drops it, so the UI cannot re-attach. **Failure:**
editor has a search running (or a forgotten `ready_for_review` manifest from
last week — `active_job` counts that too), types a second topic, presses
SEARCH: the progress panel vanishes, a toast says "you already have a job in
progress", and the page shows nothing running while the job continues
server-side. Recovery requires knowing to click the row in Recent searches.
**Fix:** `detach()` only after the POST succeeds; on 409 read `job_id` from
the detail object and `attach()` it.

### YTDL-9 — no ownership guard on poll responses: a stale terminal response kills the new job's polling loop [verified]
`static/app.js:201-232`. `poll()` never re-checks, after its awaits, that the
response still belongs to `state.jobId`; the `downloading` branch even fetches
the manifest in a second await. A stale response re-renders old job state over
the new job's UI, and — worst — a stale *terminal* response runs
`stopPolling()` unconditionally and returns without rescheduling, clearing the
timer the new job's loop just armed. **Failure:** job A's final
(slow, double-await) poll is in flight when it completes server-side; the
editor's next SEARCH is accepted, job C attaches and schedules its next tick;
A's late `done` response lands: it renders A's finished list over C's view,
kills C's timer, and loads C's empty queued manifest. C runs to completion on
the server while the page sits frozen until a manual refresh. **Fix:** capture
`const id = state.jobId` at poll entry and bail after every await if it no
longer matches (or a monotonic attach token / AbortController).

### YTDL-10 — session expiry mid-job: the poll retries 401 forever, silently, with the UI frozen at stale progress [verified]
`static/app.js:206-210`. The poll's catch handles only `404 → detach()`; every
other status — including the dashboard gate's JSON 401 — hits `schedulePoll()`
and retries every 5 s indefinitely, telling the editor nothing. **Failure:**
tab left open overnight mid-download; the session cookie expires; the page
shows "downloading 17/41, 44%" forever while polls 401 every 5 s. The editor
concludes the download hung; it actually finished hours ago. **Fix:** on
`e.status === 401`, stop polling and warn "session expired — sign in to the
dashboard and reload".

### YTDL-11 — health states `timeout`/`error` produce no pre-submit banner, and the fallthrough actively clears one [analysis]
`static/app.js:137-148` (`loadHealth`). The health contract emits
`ok|unauthenticated|missing|timeout|error|unknown` (`routes_api.py:57`,
`claude_cli.py:374-378`); `loadHealth` warns only for
`unauthenticated`/`missing` — `timeout`/`error` fall through to the all-clear
`warn(null)`, which also erases any banner already on screen. **Failure:**
claude is wedged (probe timed out at worker start); editor loads the page,
sees no warning (only the easy-to-miss pip text), submits, and gets a failure
minutes later — exactly the pre-submit warning the banner exists to give.
**Fix:** add `timeout`/`error` branches before the fallthrough (the HINTS
table already has the copy).

### YTDL-12 — a failed job's red error banner persists through the next, healthy job [analysis]
`static/app.js:251-253` (`renderProgress`: `if (job.error) warn(...)` with no
else; `warn()` is only ever cleared by `loadHealth`'s all-ok path, which runs
once at init). **Failure:** job fails with `claude_timeout:` → red banner;
editor retries; the new job succeeds end-to-end with the failure banner
sitting above it the whole way — through review and download — telling the
editor (and any admin they escalate to) the server is broken. Mirror case:
job N's amber "relevance filter unavailable" degraded banner persists into
job N+1's properly-filtered manifest. **Fix:** `else warn(null)` when the
rendered job has no error, or clear in `attach()`/`detach()`.

## Major — claude seam

### YTDL-13 — a relevance reply with `"keep": null` fails the whole job, defeating the degrade-don't-fail design [analysis]
`claude_cli.py:308` (`{int(i) for i in data.get('keep', [])}` — `.get`
returns the present-but-null None, TypeError), `worker.py:374-381`
(`_phase_filter` catches only `ClaudeError`, so the TypeError escapes to
`run_job`'s generic handler → phase `failed`). Line 311 defends `drop` against
exactly this shape (`data.get('drop', []) or []`); `keep` is unguarded — an
asymmetry suggesting the shape has been seen. **Failure:** a 20-minute search
completes; the model returns `{"keep": null, "drop": [...]}` when it kept
nothing; instead of the designed outcome (unfiltered manifest + degraded
banner, `worker.py:364-366`) the job dies at `filtering` with a raw
`TypeError` string no SPA hint maps, and the manifest is lost. **Fix:**
`data.get('keep') or []` plus a non-iterable guard, or widen `_phase_filter`'s
except to degrade on TypeError/ValueError too.

## Major — test wiring

### YTDL-14 — the ytdl suite is wired into nothing: absent from `run_all_tests.ps1`, and DEPLOY.md's venv does not exist [verified — hunter ran the suite]
`tools/run_all_tests.ps1:23-31` (`$Suites` has no ytdl entry — and no
`music/web` either, contradicting CLAUDE.md's "all 8 suites");
`ytdl/web/DEPLOY.md:163-165` documents `.venv\Scripts\python.exe -m pytest`,
but `ytdl/web/.venv` was never created — the documented command fails with no
interpreter. `ship.cmd` gates only `server/`. The 103-test suite exists and
passes (verified under the dashboard venv) but no aggregate command runs it.
**Failure:** the next ytdl regression ships silently — the sibling B1 shape:
infrastructure exists, nothing exercises it. **Fix:** add ytdl/web (and
music/web) to `$Suites`; create the venv or fix DEPLOY.md to name an
interpreter that works.

---

## Minor / low

**Download pipeline & worker:**
- **YTDL-15** [confirmed x2] `download()` can return success with
  `filepath=None` (bare `except Exception: pass` around `prepare_filename` +
  a 5-extension guess list, `vendor/downloader.py:346-359`); the worker then
  records `dl_state='done'` and `ledger_add`s with `rel_path=''`
  (`worker.py:564-580`) — a permanent, never-cascading ledger row that flags
  the video "already in the fleet" forever, pointing at nothing, fixable only
  by hand-editing ytdl.db. Fix: prefer
  `info['requested_downloads'][0]['filepath']`; treat `filepath=None` as a
  failed video; never ledger an empty rel.
- **YTDL-16** [confirmed x2] failed downloads are unretryable:
  `db.mark_pending`'s "second DOWNLOAD press re-queues failed rows" contract
  (`db.py:450-462`) is unreachable — `start_download` 409s unless the phase is
  `ready_for_review` (`routes_api.py:221-224`) and `_phase_download` always
  ends terminal `done` even with `dl_failed>0`. 3 of 41 clips fail on a
  throttle → the only recovery is a full new search job (claude + search +
  enrich re-spend; dedupe at least skips the 38 that landed). Fix: allow
  DOWNLOAD on a `done` job that still has failed/selected-undone rows, or
  return partial jobs to `ready_for_review`.
- **YTDL-17** [analysis] `_sweep_stale` matches `'.part' in p.name` /
  `'.editready' in p.name` as substrings (`worker.py:478-486`) — but
  `_swap_in`'s fallback deliberately keeps a converted clip as
  `<stem>.editready.mp4` and stores that exact path in the ledger
  (`vendor/downloader.py:289-299`). Such a file older than 24 h is deleted by
  the next download job into the same term dir; the ledger still lists it, so
  dedupe blocks re-fetching fleet-wide and any Resolve project referencing it
  goes Media Offline. Titles containing ".part" match too. Fix: suffix-match
  `.part`/`.part-Frag`, drop `.editready` from the sweep (or exclude ledgered
  filepaths).
- **YTDL-18** [analysis] `start_download` commits `mark_pending`, `set_job`,
  `set_phase` as three separate transactions (`routes_api.py:226-231`); a
  container death between the first and third leaves `ready_for_review` with
  rows already `pending` — which `mark_pending`'s
  `dl_state IN ('none','failed','skipped')` no longer matches, so every later
  DOWNLOAD press 400s, and (with YTDL-1) cancel can't clear it either. Fix:
  include `'pending'` in the IN-list (idempotent) or write phase+pending in
  one transaction.
- **YTDL-19** [analysis] the worker thread opens its DB connection *outside*
  the try that guards the loop (`worker.py:110`); a transient
  locked-at-boot/unwritable-data-root raise kills the thread permanently
  (`ensure_started` runs only at mount). Visible via `worker_alive:false` but
  only fixable by container restart. Fix: retry/lazy-acquire inside the loop.
- **YTDL-20** [analysis] one missing `english_gloss` fails the whole job:
  the gloss check (`claude_cli.py:246-250`) runs after `ask_json`'s retry loop
  (which retries only unparseable output), so the promised "a retry fixes
  this" in the docstring never happens; `test_claude_cli.py:152-159` enshrines
  the terminal raise. 19 good terms + 1 missing gloss → editor loses the whole
  search. Fix: retry `generate_terms` once on gloss failure, or drop the
  offending term.
- **YTDL-21** [analysis] no bot-check classification anywhere: yt-dlp's "Sign
  in to confirm you're not a bot" is treated as a dead video per row
  (`vendor/ytsearch.py:167-169`, `worker.py:259-261,557-560`) — a bot-checked
  NAS IP burns full retry budgets per video, ends `done` with 0 candidates or
  N opaque errors, and never surfaces the `YTDL_COOKIES_FILE` escape hatch
  DEPLOY.md documents. Fix: match the phrase and short-circuit the phase with
  a cookies-pointing job error.
- **YTDL-22** [analysis] `probe_streams` returns `{}` on *any* ffprobe failure
  (`vendor/downloader.py:170-179`), which `ensure_edit_ready` reads as
  "audio-only; nothing to fix" (`:215-219`) — if `/opt/ffmpeg` lacks ffprobe
  or it transiently fails, every VP9/Opus download is delivered unconverted
  with zero warning: the exact Media-Offline-in-Resolve outcome the module
  exists to prevent. Fix: distinguish probe-failed (warn, optionally convert
  anyway) from genuinely-no-video-stream.
- **YTDL-23** [analysis] VFR detection compares ffprobe's raw fraction
  *strings* (`avg_frame_rate != r_frame_rate`, `vendor/downloader.py:225`) —
  differently-reduced equal fractions or one-frame rounding on trimmed uploads
  read as VFR and trigger a needless full libx264 re-encode (generation loss +
  minutes of container CPU); the reverse miss is possible too. Fix: compare as
  `Fraction`s with tolerance.
- **YTDL-24** [confirmed x2] a missing deno produces per-video failures while
  health reports all-ok: `_yt_dlp_state` is import-only
  (`routes_api.py:65-71`), no surface checks for a JS runtime, and the
  resulting "Requested format is not available" rows read as YouTube
  flakiness — the exact misdiagnosis DEPLOY.md warns about, with no signal.
  Fix: `shutil.which('deno'/'node')` in `/api/health` next to `yt_dlp`.

**DB / paths / API:**
- **YTDL-25** [confirmed x3] `create_job`'s one-active-job check is
  read-then-insert with no transaction or unique constraint
  (`routes_api.py:113-122`), and the SPA never disables `#go` while the POST
  is in flight — a double-click creates two active jobs; the worker runs both;
  `active_job`'s `ORDER BY id LIMIT 1` means the *orphaned first* job is what
  blocks all future searches with a 409 naming a job_id the SPA isn't
  tracking. Fix: partial unique index on
  `jobs(created_by) WHERE phase NOT IN (terminal)` → turn IntegrityError into
  the 409; disable the button in flight.
- **YTDL-26** [analysis] "select NONE" can't deselect a hand-selected
  filtered-out video: `bulk_select(..., selected=0, scope='relevant')` appends
  `AND relevant=1` (`db.py:434-447`) and app.js sends `scope:'relevant'`
  whenever "show filtered" is off — the hidden card stays selected and
  `mark_pending` (no relevant predicate) silently downloads it into the
  project. Fix: when `selected=0`, drop the relevant predicate — deselect-all
  means all.
- **YTDL-27** [confirmed x2; hunter reproduced] the dedupe regex takes the
  *first* bracketed 11-char token in a stem, not the trailing `[id]` the
  outtmpl guarantees (`vendor/ytsearch.py:60,97`): a title like
  `Song [OFFICIAL_MV] [dQw4w9WgXcQ]` registers `OFFICIAL_MV` and the real id
  is never recorded, so hand-copied/pre-ledger clips with such names are
  invisible to the disk scan and get re-downloaded. Fix: use the last match or
  anchor to end-of-stem (dovetails with YTDL-2's fix).
- **YTDL-28** [verified — hunter reproduced] `safe_term_dirname` passes
  Windows reserved device names through (`config.py:158-180`; `'con'→'con'`,
  `'COM1'→'COM1'` verified): a term that is exactly CON/PRN/AUX/NUL/COM1-9/
  LPT1-9 creates `<project>/Youtube/con/` on the NAS (POSIX, succeeds), which
  then gives every Windows editor persistent per-item sync errors on that
  project until renamed on the NAS. Fix: suffix `_` when the pre-dot stem
  upper-cases into the reserved set — same treatment the trailing-dot rule
  gets.
- **YTDL-29** [analysis, latent] non-ASCII usernames arrive mojibake: the gate
  appends the identity header UTF-8-encoded
  (`dashboard/src/ccsync_dashboard/ytdl.py:116`) but Starlette decodes headers
  latin-1 (`session.py:31`) — `josé` becomes `josÃ©`, deterministically, so
  `ticked_projects` matches nothing and the app is unusable for that editor
  (self-consistent, no cross-user leakage). All current usernames are ASCII.
  Fix: ASCII-limit at the gate, or `encode('latin-1').decode('utf-8')` in
  session.py.
- **YTDL-30** [analysis] `start_download` never re-validates the destination
  project, contradicting the module's own "re-validated on every write"
  contract (`routes_api.py:14-17` vs `:215-233`): a project unticked/retired
  while the manifest sat at review still receives 40 clips into a tree nobody
  syncs or watches. Fix: re-run `resolve_project` in `start_download`, 409 on
  None.
- **YTDL-31** [analysis] the ledger stores the *raw* term while the folder on
  disk is `safe_term_dirname(term)` (`worker.py:577-580`, `db.py:495-498`) —
  for any term with `<>:"/\|?*` or >80 UTF-8 bytes the "ALREADY IN
  <label>/<term>" badge names a path that does not exist over SMB, and the
  disk-scan half reports the real folder, so the two halves of the same badge
  disagree. Fix: store `term_dir` (or both) and render the badge from it.
- **YTDL-32** [analysis] DASH-5's `hmac.compare_digest` TypeError has an
  unledgered third site: `auth._read_token`
  (`dashboard/src/ccsync_dashboard/auth.py:207`), reachable pre-auth with a
  non-ASCII byte in the session cookie (headers decode latin-1) → 500 +
  traceback where a 401 is owed, on every gated path including `/ytdl`. Fix:
  the same `except TypeError: return None` DASH-5 prescribes — one fix covers
  all three sites.

**Frontend:**
- **YTDL-33** [analysis] rapid select/deselect: toggle POSTs are unserialised
  and last-response-wins client-side while last-request-wins server-side
  (`app.js:451-460`); the card-body handler also reads stale `v.selected`, so
  a double-click sends `{selected:true}` twice. A quick check→uncheck can
  leave server yes / UI no — and DOWNLOAD fetches what the DB says. Fix:
  optimistic update + per-video sequence, or disable the control in flight.
- **YTDL-34** [analysis] the terminal-branch `await loadManifest()` is
  unguarded after polling has already stopped (`app.js:221-229`): one blip at
  the `ready_for_review` tick (container redeploy, 401) → full green bar, no
  review grid, no retry, until a manual refresh. Same missing handling in
  `bulk()`. Fix: try/catch + re-`schedulePoll()` around the terminal manifest
  load; toast in `bulk()`.
- **YTDL-35** [analysis, latent] `toast()` interpolates server `detail` text
  via innerHTML (`app.js:102-108`): every reachable detail today is
  server-constant or self-reflected (traced), but one future detail that
  embeds a video title turns it into XSS from a YouTube title — the exact
  sibling-SPA pattern. Fix: build toasts with `el()`/textContent.
- **YTDL-36** [analysis] cancelling (or failing) mid-download hides the
  per-video list: the `downloading` render predicate covers only
  `downloading` and `done`-with-`dl_total` (`app.js:246-249`), so a cancel at
  clip 17/41 replaces the which-clips-landed list with a red 100% bar. Fix:
  include `cancelled`/`failed` with `dl_total` in the predicate.
- **YTDL-37** [analysis] init ordering race: `loadProjects()`'s "you have no
  projects ticked" warning (with SEARCH disabled) is erased ~100 ms later by
  un-awaited `loadHealth()`'s all-clear `warn(null)` (`app.js:144-148,
  167-169, 567-568`), leaving a disabled button with no stated reason. Fix:
  separate banner slots per concern.
- **YTDL-38** [analysis] term-chip counts come from `term_hit_counts` (all
  linked videos) while the grid ANDs the term filter with
  `showFiltered=false` (`app.js:356-381`): a chip reading "(7)" can show an
  empty grid with no empty-state, reading as "the search lost my videos".
  Fix: count visible videos per chip, or render an "all N filtered out" empty
  state.
- **YTDL-39** [analysis] every poll response carries `worker_alive` and the UI
  never reads it, and health is never re-fetched after page load
  (`app.js:201-232`, `routes_api.py:155`): a dead worker leaves the bar at
  "queued" forever with the explanation present in every response; an admin
  fixing claude leaves open tabs red until manually reloaded. Fix: warn on
  `!worker_alive` with a non-terminal phase; refresh health on a slow
  interval.

**Tests & deploy:**
- **YTDL-40** [analysis] `YTDL_EXCLUDE_DIRS = BROLL_EXCLUDE_DIRS`
  (`server/install_dashboard_app.py:325`) is missing the `| {"data"}` music
  got (`:226`), and `ytdlweb.config` defaults DATA_ROOT/PROJECTS_ROOT to
  `ytdl/web/data` — one env-less dev run leaves a dev `ytdl.db` and downloaded
  videos in-tree, and the next routine ship SFTPs all of it into the NAS's
  read-only `ytdl-web` mount (potentially GB; dev job history readable in the
  container). Fix: add `"data"` to the exclude set.
- **YTDL-41** [analysis] `test_the_scan_never_leaves_the_projects_root`
  (`tests/test_dedupe.py:85-91`) is false-green: it adds no video rows, so
  `mark_duplicates` returns 0 whatever happens — delete the `safe_join` call
  and the suite stays green while the worker rglobs arbitrary host paths.
  Fix: assert `existing_id_locations` is never called with the evil path (or
  that `safe_join` raises for the label).
- **YTDL-42** [analysis] `test_mounted_prefix.py`'s `ROOT_RELATIVE` regex
  (`:30`) misses CSS `url(/…)` bodies, unlisted roots like `/partials/`, and
  bare `'/api'` without the trailing slash; the browser-walk test regexes only
  `src|href` in HTML. A root-relative CSS background or a `fetch('/partials/…')`
  ships green and 404s under the mount. Fix: deny-by-default pattern + scan
  served CSS.
- **YTDL-43** [analysis] the load-bearing bare `/ytdl` → `/ytdl/` redirect is
  pinned only under a plain `FastAPI().mount()` with neither `YtdlGate` nor
  `login_gate` (`tests/test_mounted_prefix.py:49-61`); the dashboard-side
  suite never GETs `/ytdl` without the slash — the same gap DASH-9 files for
  `/music`. Fix: one authenticated dashboard test asserting 30x → `/ytdl/`
  (do `/music` in the same pass).
- **YTDL-44** [analysis] `tests/conftest.py:59-80` hand-copies the dashboard's
  projects/selections DDL ("Copied rather than imported") with no drift guard
  on either side — verbatim-identical today (verified), but a dashboard column
  rename or semantic change keeps every ytdl test green while production
  degrades to "no project list" or, worse, wrong project lists. Fix: a
  dashboard-side test executing `ytdlweb.projects._SQL` against the real
  dashboard schema.
- **YTDL-45** [analysis] nothing anywhere asserts the umask-077 chmod
  contract (0o664 files / 0o2775 dirs): `_chmod` is a no-op on Windows and no
  test mocks `os.chmod` to assert the calls, so a regression makes every
  download invisible over SMB with all suites green. Fix: a test that records
  `os.chmod` calls on the success path.

---

## Verified sound (hunters checked deliberately — don't re-investigate)

- **Mount contract:** `mount_ytdl` import and storage-probe both fully guarded
  (ABSENT/DEGRADED, worker never started before schema); no path where a
  broken ytdl checkout stops dashboard boot. Docs routes 404 under both path
  conventions, pinned. `/ytdl/api/` is in `login_gate`'s JSON-401 prefix list.
- **Identity & isolation:** `YtdlGate` strip-then-append is correct and pinned
  by real spoofing tests; per-user ownership is in SQL on every job route;
  the dashboard DB is opened genuinely read-only (`mode=ro` URI).
- **Path safety:** `safe_join` holds against `..`, absolute, drive-prefix,
  UNC, backslash and symlink tricks (resolve+relative_to backstop);
  `safe_term_dirname`'s NFC collapse and byte-cap cut on a char boundary
  (empirically probed) — YTDL-28's reserved names are the one gap.
- **SQL:** every interpolated column name passes a frozenset whitelist; all
  values parameterised. `add_term` re-reads after `INSERT OR IGNORE` (the
  lastrowid trap is avoided). Threading: one connection per thread, WAL,
  30 s timeout; `_progress` uses atomic replace + copy.
- **Schema:** `schema.sql` idempotent; `ensure_schema` stamps after success,
  refuses newer DBs, runs predicate-gated migrations in their own
  BEGIN/COMMIT with rollback.
- **Deploy wiring:** config.py names/defaults match DEPLOY.md exactly;
  compose.yaml and `install_dashboard_app.compose_config()` agree on the 4
  YTDL env keys and 5 volumes, and `server/tests/test_safety.py`'s
  set-equality drift tests (post-B1) cover both automatically; claude and deno
  are provisioned with digest check + `--version` execution; run.sh puts
  `/ytdl-app` on PYTHONPATH and `/opt/claude:/opt/deno` on PATH.
- **Claude seam fidelity:** the fake subprocess pins the real argv, envelope,
  subprocess-only HOME/CLAUDE_CONFIG_DIR, cwd, all four error prefixes, retry
  counts — and the prefixes match app.js HINTS verbatim. No buffering
  deadlock; env mutation is subprocess-only.
- **Frontend:** every server-derived string except the toast (YTDL-35) is
  inserted via `el()`/textContent — no XSS found; every URL is
  document-relative (the two absolute exceptions are deliberate and pinned);
  `response.ok` is checked centrally; phase labels cover all ten phases;
  polling backs off and recovers from blips and restarts.
- **Vendor:** `cookies_browser` unreachable in the container; `-map 0:v:0
  -map 0:a:0?` handles multi-audio correctly; outtmpl byte-truncation leaves
  headroom under the 255-byte cap; `windowsfilenames: True` keeps NAS/dev
  names identical; yt-dlp socket timeout and bounded retries mean nothing
  blocks forever; `js_runtimes`/`remote_components` present on all three
  network paths that matter.
- **Dedupe core:** ledger∪disk union at filter time, ledger-then-disk re-check
  before each download, duplicate refusal in SQL, ledger upsert-moves — all
  correct apart from the filename-parsing gaps (YTDL-2/15/27/31).
- **Boot recovery:** `reset_stale_jobs`' wipe-and-requeue vs resume-in-place
  split is implemented as documented; the global `downloading→pending` sweep
  can only touch kept jobs.

---

## Suggested order of work

1. **Unblock the editor:** YTDL-1 (cancel dead-ends the account) + its test;
   YTDL-16 (failed downloads unretryable) rides the same phase-machine fix.
2. **Dedupe filename parsing (one cluster):** YTDL-2, YTDL-3, YTDL-15,
   YTDL-17, YTDL-27, YTDL-31 all stem from trusting `[id]`-bearing filenames
   and success-paths that don't require a file; fix together.
3. **Availability:** YTDL-6 (body cap — one middleware entry), YTDL-7 (term
   cap), YTDL-32 (pre-auth 500).
4. **Operator trust:** YTDL-5 + YTDL-11 + YTDL-12 (health/banner lifecycle),
   YTDL-24 (deno visibility), YTDL-21 (bot-check hint).
5. **Silent quality/data wrongness:** YTDL-4 (1080p cap), YTDL-22 (probe
   fallback), YTDL-26 (NONE doesn't deselect), YTDL-30 (stale project).
6. **Frontend lifecycle:** YTDL-8, YTDL-9, YTDL-10 (one polling refactor
   covers all three), then the minor renders.
7. **Test wiring:** YTDL-14 first (nothing else matters if the suite never
   runs), then the false-green fixes YTDL-41/42/43/44/45.
