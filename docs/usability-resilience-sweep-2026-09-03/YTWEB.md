# YouTube download service: web UI, API, worker, fleet routes, AI backend, dashboard ytdl mount

## Summary

This is the best-written UI in the repo: nearly every control carries the
incident that produced it, every dead end ends at a sentence, and the two
worst usability defects of the 08-19/08-24 era (CR-30's one-job block, CR-35's
dead DOWNLOAD button) are properly closed - the queue landed 2026-08-30 and
`db.BUSY` correctly excludes the two phases that wait for a person. What is
left is a consistent shape: the server MEASURES more than the page SHOWS, and
the page shows more than the OWNER ever sees. `js_runtime` is computed and
rendered nowhere; the degraded-filter note is composed and then thrown away by
`hintFor`; the companion's free-space report is a log line; the whole ytdl
stack has zero entries in `alerts.ALERT_KINDS`, so the one machine that tells
the owner things is blind to the feature most likely to break on a Tuesday.
The biggest risk is that the CR-80 recovery ("export a fresh cookies.txt and
point `YTDL_COOKIES_FILE` at it") is an env-var-plus-container-restart
procedure written into an editor-facing error message, in a product whose
owner is non-technical. The best cheap wins: three health keys the SPA already
has the plumbing for (`js_runtime`, an unblock-plugin pip, `queued_behind`
counting the fleet), and one `_note_fail` in `claude_cli`.

## Findings

### YTWEB-1: a job at `queued` says only "queued", and the wait that actually happens is the one the page cannot count
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl/web/static/app.js:21`, `:33`, `:1268`, `:1840-1845`; `ytdl/web/ytdlweb/routes_api.py:612-627`; `ytdl/web/ytdlweb/db.py:811-848`
- **Today:** `claim_next_job` is fleet-serial - one job at a time for every
  editor on the site ("Serial by design: one job at a time, oldest first").
  But `_queued_answer` counts `queued_behind` as *this editor's* busy job plus
  *this editor's* queued jobs, and `announceQueued` is silent when that is 0
  (`if (!n) return;`). So editor B, submitting behind editor A's 20-minute
  enrich phase, gets no toast at all, a bar parked in `PHASE_SPAN.queued` =
  `[0, 3]`, the label `'queued'`, and an EMPTY ticker (`renderProgress`'s
  `bits` are all gated on `terms_total`/`enrich_total`, which a queued job has
  none of). Nothing anywhere says what it is waiting for or roughly how long.
  The one banner slot that could speak (`WORKER_DEAD`) only fires when the
  worker thread is gone.
- **Proposed:** make `_queued_answer` return a second number,
  `fleet_ahead` - the count of rows `claim_next_job` would take first - and
  have the ticker read, for a `queued` job: `waiting for the server: 2 other
  searches are running first` (or `you are next` at 0). Toast on submit
  whenever either count is non-zero, not only your own. Nothing here needs a
  new table: it is the same `WHERE phase IN (BUSY)` count.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** CR-30, YTDL-25; the queue itself (2026-08-30) is built and correct.

### YTWEB-2: the ytdl stack has no entry in the self-diagnosis registry, so the owner is never told the downloader is broken
- **Lens:** both
- **Who:** owner / admin
- **Where:** `dashboard/src/ccsync_dashboard/alerts.py:1424-1513` (grep for `ytdl` returns nothing); `ytdl/web/ytdlweb/routes_api.py:130-183`
- **Today:** wave 4 built forty checks evaluated every collector cycle,
  written into `notices` with an exact next action and shown as PROBLEMS THE
  SERVER FOUND. Not one of them is about /ytdl. Every signal the check would
  need already exists and is already computed on the health route:
  `yt_dlp_stale` + `yt_dlp_age_days`, `pot_provider == 'unreachable'`,
  `cookies_state == 'anonymous'`, `last_download.ok == false`, `canary.last`,
  `claude != 'ok'`, `worker_alive == false`. Today all of them are visible
  only to an editor who happens to open /ytdl and read a pip's tooltip. CR-80
  and CR-83 both ran for days on exactly that: the detector was an editor.
- **Proposed:** four registry rows, each a `_check_*` reading the mounted
  sub-app's health dict (the mount already holds the app object):
  `ytdl_ytdlp_stale` (WARN, "the YouTube downloader's yt-dlp is N days old"),
  `ytdl_download_failing` (ERROR, "the last N YouTube downloads failed the
  same way"), `ytdl_pot_down` (ERROR, "the PO-token helper is not answering"),
  `ytdl_ai_down` (ERROR, "searches cannot run: no working AI provider"). Each
  next action is a sentence the owner can act on, and `NOTICE_CHECKS_META`
  gets its evidence line. A kind must be registered WITH its writer (the first
  build's own bug), so land all four together.
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** `docs/SELF_DIAGNOSIS.md`, CR-73/CR-80/CR-83; 08-28 YT-23 (canary off by default) is the same blindness one layer down.

### YTWEB-3: `js_runtime` is measured, shipped in the health payload, and rendered nowhere
- **Lens:** both
- **Who:** admin / editor
- **Where:** `ytdl/web/ytdlweb/routes_api.py:143`, `:352-366`; `ytdl/web/static/app.js:596-621` (`loadHealth` reads `claude`, `yt_dlp`, evidence keys - never `js_runtime`)
- **Today:** `_js_runtime_state()` exists precisely because YTDL-24 cost a
  week: without deno or node on PATH every clip fails "Requested format is not
  available", which reads as YouTube flakiness per video. Its own docstring
  says "One `which` is the difference between an ops instruction and a week of
  misdiagnosis." The value is returned on `GET api/health` and no line of
  `app.js` mentions it. The only place a missing JS runtime surfaces is
  `identical_failure_note`'s "no usable format" branch, three clips into a
  failed download, and that note names yt-dlp updates and never deno.
- **Proposed:** one line in `loadHealth`, in the existing banner vocabulary:
  `else if (h.js_runtime === 'missing') setBanner('health', 'this server has
  no JavaScript runtime (deno or node), so YouTube will refuse every format.
  Downloads will fail until an admin adds one. See ytdl/web/DEPLOY.md.',
  true)`. Read with an `== null` guard like every other WP5 key. Add
  `js_runtime` to `identical_failure_note`'s no-usable-format branch too, so
  the note names the actual cause when it is this one.
- **Effort:** S   **Value:** high   **Confidence:** high

### YTWEB-4: the CR-80 recovery is an env var and a container restart, written into an error message an editor reads
- **Lens:** usability
- **Who:** editor (sees it) / owner (must act)
- **Where:** `ytdl/web/ytdlweb/worker.py:116-123` (`BOT_CHECK_NOTE`), `:133-141` (`BOTH_PATHS_NOTE`); `ytdl/web/ytdlweb/config.py:46`; no cookies control exists anywhere under `dashboard/src/ccsync_dashboard/`
- **Today:** an editor whose 41-clip job dies gets, verbatim: *"an admin has
  to export a cookies.txt from a signed-in browser and point
  `YTDL_COOKIES_FILE` at it (ytdl/web/DEPLOY.md, "cookies.txt escape hatch").
  A jar holding only its header lines counts as none."* That is a repo path,
  an env var and a compose edit, addressed to a non-technical owner, delivered
  through a video editor. There is no upload control, no "test this jar"
  button, and no route by which the editor can even tell the admin other than
  a message. `YTDL_COOKIES_FILE` is a compose variable, so changing it is a
  container restart - and CR-84 showed the customer-facing path for that is
  `docker compose up` in an SSH session.
- **Proposed:** Settings -> YouTube downloader: a file picker that writes the
  jar to `<data>/secrets/ytdl/cookies.txt` (0600, atomic tmp+rename), a
  `cookies_state` chip beside it reading the same
  `ytdl_evidence.cookie_jar_state` the pip uses, and a [ TEST IT ] button that
  runs the canary clip on the cookies path and reports which of ok / anonymous
  / flagged came back. `config.COOKIES_FILE` becomes "the env var, else that
  file" so nothing existing changes. Then reword both notes to the editor's
  half only: *"YouTube is refusing this server's downloads. An admin needs to
  refresh the YouTube sign-in on Settings > YouTube downloader. Nothing else
  on this page is affected."*
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** CR-80, CR-84, `docs/COMMERCIAL_READINESS.md` (a second customer cannot be handed a compose edit).

### YTWEB-5: the unblock plugin's boot install can fail forever and no health key can see it
- **Lens:** resilience
- **Who:** admin / owner
- **Where:** `dashboard/deploy/run.sh:206-233` (four stderr WARNING lines); `ytdl/web/ytdlweb/routes_api.py:317-340` (`_pot_provider_state` probes an HTTP sidecar URL only); `dashboard/deploy/compose.image.yaml:151` ("`YTDL_POT_BASE_URL` ... DELIBERATELY ABSENT")
- **Today:** on the shipped compose there is no `YTDL_POT_BASE_URL`, so
  `pot_provider` is `'unconfigured'` and the SPA paints it neutral with the
  tooltip *"no PO-token sidecar is configured on this server. That is normal
  unless YouTube starts bot-checking it."* The PO-token path that deployment
  actually uses is the pip-installed `bgutil-ytdlp-pot-provider` plugin on
  `PYTHONPATH` - and when its install fails (CR-73: DNS not up in the first
  seconds; CR-84: `[Errno 13]` into a read-only `/venv`) the entire evidence
  is four `run.sh: WARNING:` lines in a container log. CR-73's symptom was
  1.8 MiB/s downloads and "the file is empty" for days. The retry loop and the
  pip-stderr echo were both added; the *reporting* was not.
- **Proposed:** a fifth health key, `pot_plugin`: `'off'` when
  `DASH_SITE_YOUTUBE_UNBLOCK` is not 1, `'ok'` when
  `importlib.util.find_spec('yt_dlp_plugins.extractor.getpot_bgutil_script')`
  resolves, `'missing'` otherwise (a `find_spec`, no import, no subprocess).
  Render it in `renderEvidence` beside the PO-token pip: *"unblock plugin
  missing"*, off-red, tooltip *"this site has the YouTube unblock feature on
  but the plugin did not install. Downloads will be slow or empty until the
  container boots with PyPI reachable. See the container log for what pip
  said."* Pair with a `ytdl_pot_down` notice (YTWEB-2). Have `run.sh` also
  write `<data>/.unblock-install-error` on the final failure so the check has
  a durable artefact rather than a log scrollback.
- **Effort:** S   **Value:** high   **Confidence:** med-high

### YTWEB-6: the AI health cache can only go green, so a revoked key leaves a green pip over failing searches
- **Lens:** resilience
- **Who:** admin / editor
- **Where:** `ytdl/web/ytdlweb/claude_cli.py:161-169` (`_invoke` calls `_note_ok` on success and records nothing on failure), `:1101-1105`, `:1055-1058`; `ytdl/web/ytdlweb/worker.py:268-300` (`recheck_health` returns early unless the cache is already red)
- **Today:** `_note_ok` is the only writer besides `refresh_health`, and
  `refresh_health` is called at thread start and then only from
  `recheck_health`, which begins `if cached.get('claude') == 'ok': return
  False`. So once anything has succeeded, a key that is later revoked, rate-
  limited past its cap or paying against an exhausted balance leaves
  `claude: 'ok'` in the cache permanently: `loadHealth` paints the pip green,
  `setBanner('health', null)` clears the pre-submit warning, and every
  subsequent search fails with `claude_auth:` in `job.error`. YTDL-5's fix
  (one transient timeout must not pin the pip red) was correct; its mirror was
  never written.
- **Proposed:** a `_note_fail(prefix, detail, provider)` beside `_note_ok`,
  called from `_invoke`'s exception path, writing the same
  `unauthenticated|missing|timeout|error` mapping `refresh_health` already
  uses. `recheck_health`'s "only while red" rule then does the self-healing it
  was built for, and the pre-submit banner tells the editor before they spend
  twenty minutes. Pin with a test: a failing `complete()` must leave
  `health()['claude'] != 'ok'`.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** YTDL-5, ytdl-web-4; 08-28 YT-10 is the *write* path, this is the *read* path.

### YTWEB-7: the degraded-filter note is composed and then discarded by `hintFor`
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl/web/ytdlweb/worker.py:668-673`, `:729-733`; `ytdl/web/static/app.js:416-420`, `:1249-1251`
- **Today:** when the relevance pass fails, the worker writes
  `error = f'{exc.prefix} {DEGRADED_NOTE}'`, i.e. `claude_auth: relevance
  filter unavailable -- showing all results unfiltered`, on a job whose phase
  is NOT failed - the comment says "that is exactly how the SPA tells a
  warning from a failure". The SPA then calls `hintFor(job.error)`, which
  matches on the prefix and **returns the generic hint instead of the string**
  (`for (const [prefix, hint] of HINTS) if (err.startsWith(prefix)) return
  hint;`). The editor is shown *"This deployment has no working AI provider
  credential. An admin must add one on the dashboard..."* and is never told
  the manifest below them is UNFILTERED - which is the one fact that changes
  what they do next (every one of 300 candidates is ticked as relevant).
  The note also uses `--` in user-visible text, against the house rule.
- **Proposed:** `hintFor` returns `hint` plus the remainder of the error when
  the error is longer than the prefix: `` `${rest}. ${hint}` ``. And reword
  `DEGRADED_NOTE` to `'the relevance filter could not run, so every result
  below is shown unfiltered'` (no double hyphen). One line each side.
- **Effort:** S   **Value:** high   **Confidence:** high

### YTWEB-8: after a reload the page attaches to the OLDEST job, so a parked review hides the search that is actually running
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl/web/ytdlweb/db.py:687-714` (`active_job`: oldest non-terminal, `phase != 'queued'`); `ytdl/web/ytdlweb/routes_api.py:908-937`; `ytdl/web/static/app.js:1456-1489` (`renderQueue` lists `queued` rows only)
- **Today:** the queue (2026-08-30) deliberately lets a second search START
  while an older one sits at `ready_for_review`. `active_job` was not revisited:
  it still returns the editor's oldest non-terminal row. During the session
  `runSearch` attaches to the new job explicitly, so this is invisible - but
  on a reload, a second tab, or the next morning, the page attaches to the
  week-old parked review, shows a full green bar and a review grid, and the
  job that is actually downloading appears nowhere on the page. The queue
  panel cannot show it either (it lists `phase='queued'` only). The editor's
  only route to it is a Recent-searches row.
- **Proposed:** prefer BUSY over parked in `active_job`
  (`ORDER BY (CASE WHEN phase IN (BUSY) THEN 0 ELSE 1 END), id`) - what is
  moving is what the page is about - and add the parked jobs to the
  `/api/jobs/active` payload as `waiting: [...]`, rendered as a third,
  one-line list above the queue: `1 search waiting for your review (job #42)
  [ OPEN ]`. Nothing is lost: a parked job is exactly the thing that needs a
  named affordance rather than an implicit attachment.
- **Effort:** M   **Value:** high   **Confidence:** high

### YTWEB-9: nobody anywhere checks free space, and the one number that is collected is only logged
- **Lens:** both
- **Who:** editor / admin
- **Where:** `ytdl/web/ytdlweb/routes_fleet.py:323` (`free_bytes` on the claim body), `:500-502` (`log.info(... '%s free')` and nothing else); `ytdl/web/static/app.js:1704-1707` (`gridfoot`: count + duration only); `grep 'disk_usage|statvfs' ytdlweb/` finds nothing
- **Today:** the editor's only disk-space proxy before pressing DOWNLOAD is
  `` `${sel.length} selected · ${fmtTotal(secs)} of footage · into ...` `` -
  a duration. 40 clips of 12 minutes at 1080p is 15-40 GB and the page never
  says so. Server-side there is no free-space test at any point in the
  download phase; the companion sends `free_bytes` at claim time and the
  server writes it into a log line. On a full NAS the failure arrives as N
  opaque per-clip errors and `identical_failure_note`'s fallback branch, whose
  advice is *"Fix the cause, then press RETRY"*.
- **Proposed:** (a) an estimate in `gridfoot`, from duration x a per-rung
  bitrate table: `40 selected · 8h 10m of footage · roughly 22 GB · into
  Foo\Youtube\bar`; (b) `shutil.disk_usage(outdir).free` at the top of
  `_phase_download` and every ~10 clips, parking the phase with a note that
  names the number (*"the server has 4 GB free and this job needs about 22 GB.
  Nothing was deleted; free space and press RETRY."*); (c) refuse a claim
  whose `free_bytes` is under the estimate, with the reason in the 409 so
  `noteLocalSkipped` prints it; (d) an ENOSPC branch in
  `identical_failure_note` so a full disk never tells the editor to press
  RETRY.
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** 08-28 YT-5 (the cap half); `alerts._check_disk_low` exists for editors' sync drives and has no ytdl sibling.

### YTWEB-10: the fallback path copy hardcodes `P:` and Windows backslashes
- **Lens:** usability
- **Who:** editor (Mac), owner (second customer)
- **Where:** `ytdl/web/static/app.js:2593-2601` (`noCompanion`), `:341-344` (`winPath`/`winParent`), `:2447`
- **Today:** every no-companion dead end ends at *"The clip is in
  Projects\Foo\Youtube\bar on your sync drive (P: on Windows)"*, and the
  history row's subtitle is built with `winPath` unconditionally. `CLAUDE.md`
  is explicit that the drive letter is site data (`canonical_prefix`, default
  `P:\`) and that no customer-specific value belongs in code; the same page's
  own comment two lines up says it "genuinely does not know one (P: on
  Windows, /Volumes/<SSD> on a Mac)" and then prints P: anyway. A Mac editor
  reads a backslash path and a drive letter that does not exist on their
  machine.
- **Proposed:** the loopback probe already answers `/ytdl/capabilities`; add
  the companion's own `canonical_prefix` and path separator to that body and
  have `noCompanion` print the real prefix when it has one. With no companion
  answering (the common case here) drop the parenthetical entirely and print
  the relative path with forward slashes: *"The clip is in
  Projects/Foo/Youtube/bar under your sync drive."* Never invent a letter.
- **Effort:** S   **Value:** med-high   **Confidence:** high

### YTWEB-11: a finished clip in the DOWNLOADS list cannot be opened; only the history panel can reveal
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl/web/static/app.js:1570-1605` (`renderDownloads` rows: thumb, name, status - no click handler), `:2430-2461` (`historyRow` has `row.onclick = () => reveal(d)`)
- **Today:** the editor watches 41 rows go green in DOWNLOADS, then has to
  scroll past the queue and Recent searches to DOWNLOAD HISTORY - a fleet-wide
  ledger, newest first, mixing every editor's clips - and find their own rows
  there to click one open. The reveal machinery (`reveal`, `offerFetch`,
  `noCompanion`) is all written and works from one panel only. This is the
  last step of the flow the whole page exists for: "find the file in my
  project".
- **Proposed:** make a `dl_state === 'done'` row clickable with the same
  `reveal(d)` - the manifest row carries `video_id` and the job carries
  `project_label` + `term_dir`, which is exactly `db.reveal_path`'s shape, so
  add `reveal_path` to the manifest video dict. Plus one line in the
  DOWNLOADS header when the job reaches `done`: *"12 clips landed in
  Foo\Youtube\bar. Click a row to open the folder."*
- **Effort:** S   **Value:** med-high   **Confidence:** high

### YTWEB-12: a cancel toast promises a slower stop than actually happens, on the one path where speed matters
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl/web/static/app.js:2072-2075`; `ytdl/web/ytdlweb/routes_fleet.py:199-210` (`_leaseholder_or_410` 410s a cancelled job at the next heartbeat); `ytdl/web/ytdlweb/config.py:241` (`HEARTBEAT_SECONDS = 30`)
- **Today:** cancelling a downloading job toasts *"cancelling: it stops after
  the video in flight"*. For a SERVER download that is true. For a LOCAL one
  the cancel expires the lease and the next heartbeat gets a 410, which kills
  the child mid-file - sooner than promised, but the editor watching their own
  machine sees the row stop at 43% and the toast says it should have
  finished. Meanwhile a local job takes up to 30 s to notice at all, and
  nothing on screen says "asking your machine to stop".
- **Proposed:** branch on `job.download_mode`: server -> keep the current
  line; local -> *"cancelling: your machine stops the clip it is on, within
  half a minute"*. Set a `cancel_requested` flag on the poll payload so
  `#dlphase` can read `cancelling...` until the executor confirms, instead of
  the row sitting at `downloading` looking ignored.
- **Effort:** S   **Value:** med   **Confidence:** high

### YTWEB-13: an editor's own parked reviews are invisible until they collide with one
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl/web/ytdlweb/db.py:507-517`; `ytdl/web/static/app.js:1465-1489`, `:2352-2390`
- **Today:** now that a parked `ready_for_review` no longer blocks anything,
  nothing ever nags about one - which is the right trade, but it means an
  editor can accumulate five manifests they curated and never downloaded, each
  holding nothing but their own effort, discoverable only by reading `phase`
  in the Recent searches list. There is no age-out, no count, and the ledger
  of what they meant to fetch quietly stops mattering.
- **Proposed:** one line in the header's `#warn` container (a slot, so it
  cannot erase the others): *"3 searches are waiting for your review"* with
  the count linking to the oldest. Pairs exactly with YTWEB-8's `waiting: []`
  payload, so it is one server change for both.
- **Effort:** S   **Value:** med   **Confidence:** high

### YTWEB-14: the review grid's date and length drops are per-card notes with no summary line
- **Lens:** usability
- **Who:** editor
- **Where:** `ytdl/web/ytdlweb/worker.py:684-702`; `ytdl/web/static/app.js:1680-1684` (`#counts`)
- **Today:** `#counts` reads `` `${c.relevant} relevant · ${c.duplicates}
  already downloaded · ${c.irrelevant} filtered out` ``. Everything the
  mechanical pass dropped - `live or no duration`, `over 30 minutes`,
  `uploaded 2019-04-02, outside ...` - is folded into that one `irrelevant`
  bucket alongside Claude's judgements, and the reason is visible only after
  pressing [ SHOW FILTERED OUT ] and reading each card. An editor who set a
  date range too tight, or whose topic is mostly hour-long streams, sees "61
  filtered out" and concludes the AI judge is wrong.
- **Proposed:** count the mechanical notes server-side into
  `counts.dropped_by_rule = {length: n, dates: n, live: n}` and render a
  second line under `#counts`: *"of those, 22 were longer than 30 minutes and
  9 were outside your date range."* The rule the editor set is the one they
  can change in ten seconds.
- **Effort:** S   **Value:** med   **Confidence:** high

### YTWEB-15: the ytdl feature gate still flips a live feature off on an unreadable database, silently
- **Lens:** resilience
- **Who:** editor / developer
- **Where:** `dashboard/src/ccsync_dashboard/ytdl.py:365-368`
- **Today:** unchanged since 08-28: `except Exception: return fallback` with
  no log line at all, while the sibling `except` four lines down does warn.
  On a vendor build the fallback is `False`, so a transient `database is
  locked` or a NAS remount 404s every path under `/ytdl` - editors mid-job and
  every companion fleet call - for the TTL, and nothing anywhere records why.
- **Proposed:** as 08-28: log once per TTL naming the exception, and on an
  unreadable DB keep `self._enabled` rather than defaulting off. Adding it
  here only because it is one line and it is still there.
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** 08-28 YT-21 (not built).

## Still open from 08-28

- YT-1 yt-dlp never self-updates on an editor's machine: **partly built** - the
  server half landed (`YTDLP_MAX_AGE_DAYS`, `yt_dlp_stale`/`yt_dlp_age_days`
  and the amber pip, `routes_api.py:196-241`); the companion's `ensure()`
  max-age rule is not in `ytdlp_manager.py`, and nothing raises a notice.
- YT-4 nothing measures liveness (no `timeout=` on the two `subprocess.run`,
  `is_alive()` is thread liveness): **not built**.
- YT-5 nothing bounds what one clip may write; the duration cap and the
  live-stream drop do not apply to pasted-URL jobs at all
  (`worker.py:404-406`, `_ID_PATHS` still includes `'live'`): **not built**.
  Usability half worth adding: `#urls`'s placeholder and the [ GET LINKS ]
  tooltip say nothing about the cap not applying, so a pasted 4-hour stream
  looks like the same operation as a searched one.
- YT-14 a cancelled download job can never be resumed - `start_download`
  accepts `('ready_for_review', 'done', 'failed')` only
  (`routes_api.py:1187`): **not built**.
- YT-17 429/529 map to `ERR_OUTPUT` ("the model returned something
  unparseable") with no backoff (`ai_backend.py:469-474`): **not built**.
- YT-21 the ytdl gate's silent fallback: **not built** (YTWEB-15 above).
- YT-23 the canary is off by default and no `evidence: 'stale'` state exists:
  **not built** - `canary.enabled` is reported and the SPA hides the pip
  entirely, which is the honest-unknown-as-blank case YT-23 described.
- YT-13 no way to cancel a running LOCAL download from the machine:
  **partly built** - a server-side [ CANCEL ] now reaches the executor within
  one heartbeat via `_leaseholder_or_410`'s 410; there is still no tray item
  and `stop_all` is still called only from `broll_server.py:2125` at shutdown.

## Cross-cutting notes

- **For the dashboard/settings agent:** `Settings -> AI providers` is the only
  admin surface any of this has. The YouTube downloader has no settings page
  at all: the cookie jar, the PO-token URL, `YTDL_MAX_DURATION`,
  `YTDL_LOCAL_DOWNLOAD` and the candidate caps are compose variables. If a
  "YouTube downloader" settings panel is being considered anywhere else, this
  area wants it (YTWEB-4).
- **For the alerts/self-diagnosis agent:** `alerts.ALERT_KINDS` has zero ytdl
  rows and the health route already computes every input four checks would
  need (YTWEB-2). The mount object is reachable from the dashboard process, so
  no HTTP call is required.
- **For the companion agent:** `explainCompanionRefusal` (app.js:2122) tells
  the editor to right-click the tray and choose 'Accept YouTube Terms', which
  matches `tray.py:3212` and `settings_window.py:519` today. If the ten-item
  menu layout (CR-88) is reshuffled, that string breaks silently - there is no
  test tying the SPA copy to the tray label.
- **For whoever owns copy rules:** `worker.py:673`'s `DEGRADED_NOTE` uses a
  double hyphen in user-visible text; the em-dash scan test does not catch it.
