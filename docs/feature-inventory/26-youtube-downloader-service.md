# The YouTube downloader: pages, API, jobs, AI search and download strategies

Terms used throughout:

- **Job**: one request by an editor. Two kinds: a **search job** (the editor typed a topic) and a **paste job** (the editor pasted YouTube links). Every job has a **phase** (its state).
- **Candidate**: a video a search found and put on the job's list.
- **Manifest** (in the page): the review grid of a job's videos. **Manifest file**: the `manifest.json` written into the download folder.
- **Ledger**: the permanent, fleet-wide record of every video the fleet has downloaded, keyed on the 11-character YouTube video id. It never shrinks.
- **Worker**: the single background thread inside the dashboard process that runs every job, one at a time, for the whole site.
- **Companion**: the CC Sync tray app on an editor's computer. Its loopback server is at `http://127.0.0.1:8899`.
- **Requester-first / local download**: the editor's own companion downloads the clips instead of the server.
- **Lease**: a time-limited claim by one computer to download one job's clips.
- **Fleet token**: the shared secret `DASH_REPORT_TOKEN` every companion holds, or a per-editor `cce1.` token (resolved by the dashboard).
- **Projects root**: the folder holding every project (the container's `/projects`; `P:\Projects` on a Windows editor).

## Where it runs and the static page routes
(source: ytdlweb/main.py, ytdlweb/__init__.py, ytdlweb/vendor/__init__.py, static/index.html, static/favicon.svg, pyproject.toml, requirements.lock)

- The app is a web application mounted by the dashboard at `/ytdl`; it can also run standalone (`uvicorn ytdlweb.main:app`, default host `127.0.0.1`, port `8791`, overridable with `YTDL_HOST` / `YTDL_PORT`). Standalone start prints the URL and runs uvicorn at log level `warning`. DEV ONLY.
- Standalone start (and only standalone; the dashboard does the equivalent at mount time) creates the data root, creates or migrates the database, starts the worker and starts the canary.
- Page and asset routes (no sign-in check of their own; the dashboard's login gate covers them when mounted):
  - `GET /` serves the single page (`index.html`).
  - `GET /app.js` serves the page script (JavaScript).
  - `GET /cc_spa.js` serves the terminal-look helper script.
  - `GET /style.css` serves the stylesheet.
  - `GET /favicon.svg` serves the product mark (a red two-part "CC" logo).
- All URLs inside the page are relative to the page, so the same files work at `/` and at `/ytdl/`.
- Browser tab title: `CC SYNC // YOUTUBE`.
- Python package requirement: Python 3.12 or newer; depends on FastAPI, uvicorn and `yt-dlp>=2026.8.19`. The test extra adds pytest and httpx. A hash-pinned `requirements.lock` pins every dependency (yt-dlp pinned at `2026.8.19`).
- yt-dlp is never imported at startup; every use imports it lazily, so the app (and the dashboard) still loads with no yt-dlp installed, and a job then fails with a readable error.

## Who is calling: browser identity and machine identity
(source: ytdlweb/session.py, ytdlweb/identity.py, ytdlweb/routes_fleet.py, ytdlweb/config.py)

- Browser routes identify the editor only from the `x-ccsync-user` header, which the dashboard's gate adds after stripping any copy the browser sent.
- No header: HTTP 401, `not signed in: no dashboard session reached this app. If you got here directly, sign in to the dashboard first.` A standalone run therefore answers 401 to every API route.
- DEV ONLY: a test stand-in user can be set by an in-process function call (`set_test_user`); there is no environment variable for it (the old `YTDL_DEV_USER` is gone and unread).
- Machine (companion) routes need two things, both failing closed:
  - **The fleet credential.** Either the `X-CCSync-Token` header equal (constant-time compare) to `DASH_REPORT_TOKEN`, or, when the dashboard mount has switched on trust of its gate stamp, an `X-CCSync-Fleet-Auth` header the gate wrote: `shared` (the shared token was accepted) or `editor:<name>` (a per-editor token bound to that editor). Unset `DASH_REPORT_TOKEN`, missing or wrong token: 403 `missing or invalid X-CCSync-Token`. A non-ASCII junk token is a 403, never a 500. The stamp header is ignored entirely when the app runs standalone.
  - **A verified identity.** The `X-CCSync-Identity` header must be a dashboard identity token `v2.identity.<username base64url>.<expiry epoch>.<HMAC-SHA256 hex>` signed with `DASH_SESSION_SECRET`. Refused (403) when: the secret is unset (`this dashboard cannot verify who is calling`, reason `identity_unconfigured`, and a warning is logged); the token is missing, wrong shape, version 1, has purpose `session` (a browser cookie), a bad signature, is expired, or has an undecodable name (`a valid X-CCSync-Identity is required: sign in again from the CC Sync tray`, reason `identity`).
  - Retired secrets: tokens signed with any key in `DASH_SESSION_SECRET_PREVIOUS` (comma-separated, read live on every call) are also accepted, current key first.
  - When a per-editor token is bound to one editor and the identity names another: 403 `this report token belongs to a different editor`, reason `identity_mismatch`, and a warning is logged.
  - The `editor` field in a companion's request body is accepted but ignored; only the signed identity decides.

## The rights and terms-of-service notice (attestation)
(source: ytdlweb/attestation.py, ytdlweb/routes_api.py, ytdlweb/routes_fleet.py, ytdlweb/db.py, static/app.js, static/index.html)

- Every editor must accept a notice before any download can be caused. Current wording version: `2026-08-17.1`. Title: `Before you download: your responsibilities`.
- The notice text has four numbered statements: (1) you confirm you have the right to use the material (own it, licence or permission, public domain or openly licensed, or an exception such as fair dealing or fair use); (2) you are responsible for complying with YouTube's terms of service and copyright law; (3) CC Sync grants no rights in downloaded material and makes no representation that a download is lawful; (4) your username, the machine's name, the clip and the time are recorded and downloads are attributed to you. It ends: "If you cannot make these statements about the material you are about to fetch, do not download it."
- Two standing lines are shown at the bottom of the page whether or not the editor has accepted:
  - Copyright: "Material downloaded here belongs to whoever made it. Clearing the rights for anything you cut into a deliverable is your responsibility, and this tool grants you none of them."
  - Rate disclaimer: "Downloads are paced deliberately and are not guaranteed to succeed. YouTube rate-limits, blocks and changes its service without notice; bulk or automated retrieval may breach its terms and may stop working at any time. Do not build a workflow that depends on this feature being fast, available, or complete."
- Acceptance is stored per (username, wording version) with a SHA-256 digest of the exact wording and the time of the FIRST acceptance; pressing accept again does not change the time. A new wording version adds a new row and does not erase the old.
- If the acceptance table is missing or unreadable, everyone is treated as not having accepted (downloads refused), and a warning is logged.
- Enforced on: creating a search job, creating a paste job, starting or retrying a download (re-checked at that moment, since a review can sit for a week), and a companion's claim. Refusal: 403 with `you have not accepted the YouTube download terms. Open the YouTube downloader and read the notice at the top of the page, then press Accept.`, reason `attestation`, and the current version.
- Page panel "Before you download" sits above everything, shows the title and full text in a scrollable box (max 300 px tall in the terminal look), and an `I ACCEPT` button. Hidden once the current version is accepted.
- Pressing `I ACCEPT` posts the version the page displayed. Success toast: `Recorded. Thank you.` If the wording changed while the page was open the server answers 409 `the terms were updated while this page was open. Reload and read the new wording before accepting` (reason `stale_version`) and the page reloads itself.
- Until accepted, the SEARCH, GET LINKS and DOWNLOAD buttons are disabled and their tooltip reads `Accept the download terms at the top of this page first`; pressing Enter in the search box or Ctrl+Enter in the links box shows that sentence as a red toast instead.
- If the page cannot ask the server (an older server, a network blip), it leaves the buttons as they are and lets the server refuse.

## Browser API routes
(source: ytdlweb/routes_api.py, ytdlweb/db.py, ytdlweb/projects.py)

Every route below requires the signed-in editor (401 otherwise). Every job route loads the job only if the caller created it; another editor's job is answered 404 `no such job`, never 403.

- `GET /api/attestation`: the notice wording, the copyright line, the rate disclaimer, whether this editor accepted the current version, when, and which version they last accepted.
- `POST /api/attestation` body `{version}`: record acceptance; 409 `stale_version` when the version is not current.
- `GET /api/me`: `{user}`.
- `GET /api/health`: the health snapshot (see "Health, evidence and diagnostics").
- `GET /api/projects?machine=<hostname>&local=<bool>`: the projects this editor may download into, plus `projects_available` (whether the dashboard database could be read at all) and an error text. See "Which projects are offered".
- `POST /api/jobs`: create a search job. Body fields and validation:
  - `term` (required): blank gives 400 `a search topic is required`; over 400 characters gives 400 `a search topic must be 400 characters or fewer (that one is N)`.
  - `project_slug` (required): re-checked server-side; refused with 400 `that project is not one you are syncing. Tick it on the dashboard first: downloads go into the projects you sync.`
  - `quality`: one of `best`, `2160p`, `1440p`, `1080p`, `720p`, `480p` (default `1080p`); else 400 `unknown quality ...`.
  - `period`: one of `hour`, `today`, `week`, `month`, `year` (YouTube's own upload-date windows) or empty; else 400 `unknown period ...`.
  - `max_per_term`: default 15, silently clamped to 1..50. Not offered by the page.
  - `mode`: `visuals` or `news`; omitted means `visuals`; unknown is 400 `unknown search mode ... Known: visuals, news`.
  - `shot_types`: list of shot-type keys; omitted means the mode's preset; an empty list means "no bias". More than 9 entries: 400 `that is N shot types; there are only 9`. Unknown keys: 400 naming up to five of them and the known list. Order and duplicates are normalised.
  - `max_candidates`: one of 50, 100, 200, 400; omitted means 100; anything else is refused (never clamped) with 400 `... is not one of the candidate limits: 50, 100, 200, 400`.
  - `term_scope`: `both`, `en`, `zh`, `exact`; omitted means `both`; unknown is 400.
  - `date_from`, `date_to`: `YYYY-MM-DD` or `YYYYMMDD`, must be a real calendar date; else 400 `date_from must be a date like 2026-01-31 (that was ...)`. A reversed pair: 400 `the date range is reversed: "from" is after "to"`.
  - `auto_terms` (default false): skip the term review. The page never sends it; it exists for scripts.
  - `machine`, `local` (default true): the requesting computer's hostname and whether the download may run on it; they widen the destination check and are stored on the job.
  - The job is always created in the `queued` phase at the back of the editor's queue; the worker is woken. Answer: `job_id`, `phase`, `queue_position`, `queued_behind` (this editor's jobs ahead: the busy one, if any, plus queued ones in front), `fleet_ahead` (other editors' jobs the worker takes first) and `worker_alive`.
  - The folder name is derived from the topic (see "Folder and file naming").
- `POST /api/jobs/urls`: create a paste job. Body: `urls` (a string or a list), `project_slug`, `quality`, optional `folder`, `machine`, `local`. Fields such as mode or shot types are silently ignored.
  - Over 4000 characters of links: 400 `that is N characters of links; paste at most 4000`.
  - Links are split on whitespace and commas. Accepted: a bare 11-character id; `youtube.com/watch?v=`, `youtu.be/`, `/shorts/`, `/embed/`, `/live/`, `/v/` links on `youtube.com`, `music.youtube.com`, `youtube-nocookie.com`, `youtu.be` (with or without `www.` / `m.`), with or without `https://`, with any tracking parameters. Playlist, channel, results and feed links are refused. No network call is made to read a link.
  - Any unreadable entry: 400 `N of those are not YouTube video links: <first three>.... Paste watch/youtu.be/shorts links (or bare 11-character video ids), one per line.`
  - Nothing usable: 400 `paste at least one YouTube link`. More than 50 distinct videos: 400 `that is N links; 50 is the most one job may take. Split them into two.` Duplicates within one paste collapse to the first.
  - Project re-check and quality check as for search jobs.
  - Each video already in the ledger is written as skipped and deselected with "already in <project>/<folder>". If every video is already in the ledger: 409 `the fleet already has that video` / `... all of those videos`, with the list of duplicates, and no job is created.
  - Free-space check (when the server will do the download, which is always unless local downloads are on and `local` is true): see "Free space and missing-tree guards"; the refusal ends `Free some space and press GET LINKS again.`
  - Answer: the queue fields as above, plus `term_dir`, `folder` (`Youtube` or `Youtube/<name>`), `queued` (number of clips to fetch) and `skipped` (the duplicates).
- `GET /api/jobs?limit=N`: this editor's most recent jobs, newest first; limit default 20, clamped to 1..100.
- `GET /api/jobs/active`: `job` (the job the page should attach to: the editor's moving job first, else the newest job waiting at a review, else the head of their queue, else none), `queue` (their queued jobs in run order, numbered 1, 2, 3 by order, excluding the attached job) and `waiting` (their jobs waiting at a review, oldest first, excluding the attached job).
- `GET /api/downloads?limit=N&offset=M`: one page of the fleet-wide ledger, newest download first (ties by insertion order); limit default 24, clamped to 1..100; offset at least 0. Answer includes `total` and `has_more`. Every row carries title, channel, project, the typed term, the actual folder, `folder_path` (`Youtube` or `Youtube/<folder>`), `reveal_path` (path under the projects root, or none when no file path was recorded), job id, who downloaded it and when.
- `GET /api/jobs/{id}`: the poll answer: the job (all counters, the `terminal` flag, mode, shot types, candidate cap, scope, date range, `created_local`, and `dl_pending`, the number of clips still waiting), every term with its translation, enabled flag, source, raw hit count and the number of videos on the manifest it surfaced, the manifest header counts, the live per-clip download percentages from memory, and `worker_alive`. For a `queued` job it also carries `queued_behind` and `fleet_ahead`.
- `GET /api/jobs/{id}/manifest`: the job, every video (with its term ids and a `reveal_path` built from the job's folder and the file's name for finished clips), every term, and the counts. Counts: total, relevant (relevant, not duplicate, no metadata error), irrelevant (not relevant or metadata error), duplicates, selected (selected and not duplicate), selected seconds.
- `POST /api/jobs/{id}/terms` body `{enabled: [ids or query texts]}`: tick exactly these terms and untick the rest. Only while the job is at `terms_review`, else 409 `this job is <phase>, not waiting for you to pick its search terms`. An empty list is accepted (all unticked). Unknown entries are ignored. Answer: how many are ticked and the total.
- `POST /api/jobs/{id}/terms/continue`: leave the term review and start searching. 409 as above if not at review; 400 `tick at least one search term: a search with none of them would find nothing` if nothing is ticked. Sets the term total to the ticked count, moves the job to `searching`, wakes the worker.
- `POST /api/jobs/{id}/queue/move` body `{position}` (default 1): move a queued job to a 1-based position; out-of-range positions are clamped. The editor's whole queue is renumbered 1..n. 409 `this job is <phase>, not waiting in the queue` if it has started. Answer: the new queue.
- `POST /api/jobs/{id}/videos/{video_id}/select` body `{selected}`: tick or untick one video. 404 `no such video on this job`. A duplicate cannot be ticked: 409 `already downloaded, so it cannot be selected` with where it already is (also enforced in the database write). Answer: the new counts.
- `POST /api/jobs/{id}/select` body `{selected, scope}`: select all or none. Never touches duplicates or videos with a metadata error. Selecting with scope `relevant` (the default) only ticks relevant videos; scope `all` ticks filtered-out ones too. Deselecting always unticks everything regardless of scope.
- `POST /api/jobs/{id}/download`: start (or retry) the download. Order of checks:
  - Attestation (403).
  - Phase must be `ready_for_review`, `done` or `failed`; else 409 `this job is <phase>, not ready for review`.
  - A `failed` job with no failed or unfinished download rows: 409 `this job failed before any clips were queued, so there is nothing to retry. Start a new search.`
  - Reviving a `done` or `failed` job while this editor has another job actually running (generating terms, searching, fetching metadata, filtering or downloading): 409 `you already have a job in progress` with that job's id and phase. Jobs merely waiting at a review do not block it.
  - The destination is re-checked under the same widening the job was created with (never what this request says); refused with 409 `<project> is no longer a project you sync, so nothing can be downloaded into it. Tick it on the dashboard again, or start a new search.`
  - Free-space check over the clips about to be queued (skipped when local downloads are on and the job was created local); refusal ends `Free some space and press DOWNLOAD again.`
  - Then queues every selected, non-duplicate, metadata-ok video whose state is none, failed, skipped or pending; if none: 400 `nothing is selected that has not already been downloaded`.
  - Clears any unhonoured cancel request, clears the previous run's executor state (server pin, local mode, holder, machine, lease), resets the download counters and the job's error text, moves the job to `downloading`, wakes the worker. Answer `{ok, queued}`.
- `POST /api/jobs/{id}/mode-lock` body `{mode}`: "download on the server instead". Only `server` is accepted (400 `unknown mode ...: only 'server' can be locked`). Pins the job to the server and immediately expires any live local lease, so the companion is told to stop at its next call and the worker takes the rest. Answer: the pin, the current download mode, whether a lease is still active, and the phase.
- `POST /api/jobs/{id}/cancel`:
  - A finished job: `{ok, phase, note: 'already finished'}`.
  - A job at `queued`, `terms_review` or `ready_for_review` is cancelled outright.
  - Otherwise a cancel flag is set, any live local lease is expired (`stopped_local_download` says whether one was), and the worker is woken. The worker honours the flag between terms, between metadata chunks, between clips, and during a download (checked at most every 2 seconds from the download's progress).

## Which projects are offered as destinations
(source: ytdlweb/projects.py)

- The project list is read from the dashboard's own database (`YTDL_DASH_DB`), opened read-only so a write is impossible; 5-second busy timeout.
- Normally: the active projects this editor has ticked on any of their computers, each listed once, in the editor's own sync order then by label.
- Every active project (ordered by label) is offered instead when any of these is true:
  - `local=false`: the download will run on the server, so no computer's sync plan constrains it.
  - The named `machine` (hostname) is recorded as a wired ("base") machine of this editor.
  - Every known machine of this editor is wired. An editor with no known machines is not treated as wired.
- The same rule is re-applied on every write (job create, and download start using the values stored on the job), so the picker and the check cannot disagree. Consequence: with local downloads off (the shipped default) any signed-in editor may download into any active project.
- `YTDL_DASH_DB` unset (standalone): `projects_available: false`, error `YTDL_DASH_DB is not set: ...`, and the list comes from `YTDL_DEV_PROJECTS` (`slug=label,slug2=label2`). DEV ONLY.
- Database file missing: empty list, `available: false`, `the dashboard database at <path> does not exist.` An unreadable or too-old dashboard database: empty list, `available: false`, the error text (first 200 characters), logged as a warning.
- Machine names in messages: a machine id is turned into the hostname from the dashboard's `machines` registry (most recently seen), best effort; otherwise the raw id is shown.

## Companion (fleet) routes for requester-first downloads
(source: ytdlweb/routes_fleet.py, ytdlweb/db.py, ytdlweb/ytdl_common.py)

All except the first need the fleet credential and a verified identity (see "Who is calling").

- `GET /api/config/ytdl-client` (no authentication): `min_ytdlp_version` (the fleet floor), `download_pause_seconds` (3), `template_version` (1), `sidecar_version` (1), `lease_seconds` (180), `heartbeat_seconds` (30).
- `POST /api/jobs/{id}/claim`: take the download lease. Body: `machine_id`, `ytdlp_version`, `template_version`, `sidecar_version`, `scope_qualities` (the rungs that computer runs), `free_bytes`, and an ignored `editor`. Checks, in order:
  - 404 `no such job`.
  - 403 attestation (for the verified editor).
  - 410 `this job is <phase>, not downloading` (reason `phase`).
  - 410 `this job has been cancelled` (reason `cancelled`).
  - 410 `this job was created to download on the server` (reason `created_widened`) when the job was created with `local:false`.
  - 410 `this job is pinned to the server` (reason `mode_lock`) when the editor pinned it or the server already reclaimed it once.
  - 410 naming the template versions (reason `template_version`) when the companion's filename template version differs: "Downloading here would put two spellings of the same clip in the tree."
  - 410 naming the sidecar versions (reason `sidecar_version`) when the companion sends a non-zero sidecar version that differs.
  - 410 `this job is <quality>, which that computer does not run` (reason `out_of_scope`) when the companion declares rungs and the job's is not among them.
  - 403 `yt-dlp <version> is older than the fleet minimum <floor>` (reason `ytdlp_version`) when the companion's yt-dlp ranks below the floor or cannot be ranked (versions compared numerically part by part).
  - The claim itself is a single compare-and-set: succeeds only if the job is downloading, not pinned to the server, created local, not cancelled, and either not held, held by this same editor and computer (or a computer that did not say which), or held with an expired lease.
  - Lost to a live holder: 409 `<holder> is already downloading this job` or `... on <hostname or 'computer <id>'>`, with holder, machine and expiry. Lost otherwise: 410 `this job is no longer claimable` (reason `race`).
  - Success: logged, `free_bytes` is stored on the job (never used to refuse), answer `{ok, lease_seconds, heartbeat_seconds, download_pause_seconds}`.
- `POST /api/jobs/{id}/heartbeat` body `{machine_id}` (or `X-CCSync-Machine` header): extend a live lease by 180 s. Never revives an expired lease. Answer `{ok, lease_seconds, lease_expires_at}`.
- `GET /api/jobs/{id}/download-manifest?machine_id=`: the work order for the lease holder: project label, the destination path relative to the projects root (`<label>/Youtube[/<folder>]`), folder, quality, template and sidecar versions, the pause, and the clips (id, URL, title, thumbnail). Before answering it re-checks each pending clip against the ledger and the disk and marks any the fleet already has as skipped. If nothing is owed and nothing is in flight, it ends the lease so the server closes the job immediately.
- `POST /api/jobs/{id}/clips/{video_id}/status`: report one clip. Body: `state` (`downloading`, `done`, `failed`), `error`, `note` (quality downgrade), `title`, `thumbnail`, `channel`, `filepath_rel`, `machine_id`.
  - `downloading`: marks the clip in flight, records whose computer.
  - `done` with no file name: recorded as failed with `the downloader reported no output file`. A name of `.` or `..` after taking the last path segment: 400 `'<name>' is not a file name`. Otherwise the server builds the clip's path itself from the job's project and folder, records it done (the note goes in the error column of a done row), writes a ledger row and bumps the done counter.
  - `failed`: records the error (first 500 characters; default `the download failed`) and bumps the failed counter.
  - Any other state: 400 `unknown state ...: expected downloading, done or failed`.
  - A repeat report for a clip that is already finished is answered 200 with `duplicate: true` and counted once.
  - After the last clip finishes, the job is handed back to the server: every clip that failed on the editor's computer is put back to waiting (one retry by the server, never more), the lease ends, the job is pinned to the server and the worker is woken. Answer includes `remaining` and `retrying_on_the_server`.
- Every lease-holder route answers 410 (never 403) when the caller no longer holds the lease on that computer: `this job is no longer yours to download` (with the holder and mode), or `this job has been cancelled` (reason `cancelled`). A machine id may be given as a body field, query parameter or `X-CCSync-Machine` header; a companion that gives none is matched per editor.
- Leases: 180 s (`YTDL_LEASE_SECONDS`), heartbeat every 30 s (`YTDL_HEARTBEAT_SECONDS`), so a vanished holder is reclaimed within three minutes. Expiry times are compared as text.

## Job states and what moves a job between them
(source: ytdlweb/db.py, ytdlweb/worker.py, ytdlweb/routes_api.py)

- Phases: `queued`, `generating_terms`, `terms_review`, `searching`, `enriching` (fetching metadata), `filtering`, `ready_for_review`, `downloading`, `done`, `failed`, `cancelled`. The last three are terminal.
- Search job path: queued → generating_terms → terms_review → (editor presses SEARCH WITH THESE) → searching → enriching → filtering → ready_for_review → (editor presses DOWNLOAD) → downloading → done.
  - `exact` scope skips the review: generating_terms → searching directly, with no AI call.
  - `auto_terms` skips the review: generating_terms → searching.
- Paste job path: queued → downloading → done.
- `failed`: any phase's unexpected error (stored as `<ExceptionType>: <message>`, 500 characters), an AI failure while generating terms (stored with its prefix), a bot check that stops the phase, a missing footage tree, no room on the server, or the identical-failure breaker.
- `cancelled`: the cancel route, or a cancel flag honoured by the worker.
- A `done` job, or a `failed` job with download rows, can be sent back to `downloading` by the download route (retry).
- `done` is used even when some clips failed; those show per clip.
- Jobs waiting for a person (`terms_review`, `ready_for_review`) have no timer and no default; they wait until the editor acts or cancels.
- Every phase change and every counter change is saved immediately, so the page's poll always sees current numbers. Live download percentages are held in memory only.
- When a job that was cancelled by a personal-data delete reaches a terminal phase, its search terms are deleted at that moment.
- Boot recovery (once, when the worker starts): jobs caught in generating_terms, searching, enriching or filtering are put back to `queued` with their terms, videos and counters wiped (re-run from scratch); every clip caught "downloading" goes back to waiting (the download job itself continues and yt-dlp resumes partial files). Logged when anything was repaired; a failure of the sweep is logged and ignored.
- Per-clip download states: `none` (never asked for), `pending`, `downloading`, `done`, `failed`, `skipped` (the fleet already had it).

## The queue and the single worker
(source: ytdlweb/db.py, ytdlweb/worker.py, ytdlweb/routes_api.py)

- One worker thread serves the whole site, one job at a time. It wakes when nudged by a route, or every 5 seconds when idle. Disabled entirely by `YTDL_WORKER=0` (the tests set it), which also stops the canary and the yt-dlp nightly refresh.
- A worker tick that fails is logged and the database connection is re-opened on the next tick; one job's error never stops the worker.
- At start the worker runs one AI health probe.
- Which job runs next: jobs already in a working phase first; then queued jobs whose own editor has nothing working, in that editor's queue order, then by id. Jobs held by a live local lease are invisible to the worker, so a local download does not block the queue.
- Each editor may queue any number of jobs. A new job always goes to the back of its editor's queue.
- An editor's jobs waiting at a review do not block that editor's next queued job.
- "Fleet ahead" counts other editors' jobs the worker would take first; a job whose own editor is busy is counted as behind all other candidates.
- While idle, if the AI health is not "ok" and at least 300 seconds have passed since it was last checked, the worker re-probes the AI provider; a recovery is logged. Probes are never more often than every 60 seconds unless forced.

## The search pipeline
(source: ytdlweb/worker.py, ytdlweb/vendor/ytsearch.py, ytdlweb/claude_cli.py, ytdlweb/config.py)

### Search terms
- The editor's own topic is always added first as a term (source `user`), labelled Chinese if it contains any CJK ideograph, else English.
- Under `exact` scope that is the only term; no AI call; term total 1. An exact search therefore works with the AI provider down.
- Otherwise the AI is asked for queries (see "The AI prompts"). Terms are added until the job holds 24 terms (`YTDL_MAX_TERMS`); the rest are dropped with a log line. Duplicate query texts on one job are ignored.
- The editor's own term gets a bracketed translation if the AI returned the same text as one of its queries.
- Every term starts ticked.

### Searching YouTube
- One flat YouTube search per ticked, not-yet-searched term. A 2-second pause before every search after the first (`YTDL_SEARCH_PAUSE`); cancel is checked before and after each pause. The term total is reset to the number of ticked terms.
- Results per term: the job's `max_per_term` (15 by default). Under `exact` scope the single search may return up to the job's whole candidate cap.
- With a `period` set, the search goes to YouTube's results page with YouTube's own upload-date filter for that window (hour, today, week, month, year); otherwise yt-dlp's `ytsearchN:` search.
- Search and metadata options: JavaScript runtime deno or node, fetch of YouTube's challenge solver from GitHub allowed, the PO-token provider when configured, the yt-dlp cache directory when configured, 5 retries and 3 extractor retries, and the cookie file whenever `YTDL_COOKIES_FILE` is set (searches and metadata always use the jar when one is configured, unlike downloads).
- The candidate cap (50/100/200/400) is enforced as candidates accumulate: once the job holds that many distinct videos, new videos are neither added nor linked to terms, but remaining terms are still searched and existing videos still collect term links. A log line notes the cap was reached.
- For every new video the search page's own details are kept (title, channel, view count, widest thumbnail, duration unless live or upcoming; upload date only when it is an 8-digit date).
- A term whose search fails is logged and counted as searched with 0 hits; the job continues. A failure whose text contains "confirm you're not a bot" (straight or curly apostrophe) fails the job with the bot-check note.
- Each term records its raw hit count; the job counts terms done and candidates.

### Fetching metadata (`enriching`)
- Every video without a duration, metadata error or search-page marker gets a full metadata fetch: at most 2 in flight (`YTDL_ENRICH_WORKERS`) and 0.75 s between requests across all of them (`YTDL_ENRICH_PAUSE`, about 80 per minute; every request waits, including the first). Done in chunks of max(4, workers x 4) (8 by default) so progress is saved and cancel is honoured between chunks.
- A video that cannot be fetched (unavailable, private, geo-blocked) keeps its card, marked not relevant, deselected, note `unavailable`, error text kept (300 characters).
- A bot check during this phase stops all further requests for the job (requests already in flight finish). Every video not fetched is described from the search page, and the job carries the warning: "YouTube is limiting this server right now (it asked the server to prove it is not a bot), so the details on these results come from the search page instead of from each video: upload dates are missing and some durations may be too. Open a clip on YouTube before relying on its date." The job continues to filtering. Logged as a warning.
- If, after a bot check, no usable video on the job has any duration (fetched or from the search page), the job fails with the bot-check note.
- Fields the fetch returns empty are kept from the search page rather than blanked.

### Filtering (`filtering`)
- Mechanical drops first (card kept, deselected, marked not relevant, editor can re-tick):
  - No duration: note `live or no duration`.
  - Longer than 1800 s (`YTDL_MAX_DURATION`): note `over 30 minutes` (minutes = limit / 60).
  - A known upload date outside the editor's date range: note `uploaded YYYY-MM-DD, outside <range>` where range is `A to B`, `A onwards` or `up to B`. An unknown date never drops.
  - Under a date range, a video described from the search page (date unknown) stays relevant but arrives unticked with `upload date unknown, so not checked against <range>: unticked until you look`.
- Then the AI relevance judge over every still-relevant video, in batches of 40. Videos the judge drops are deselected with its reason (80 characters) or `not relevant to the topic`. Videos the judge did not mention stay relevant.
- If the AI fails, the job does NOT fail: the warning `<prefix> the relevance filter could not run, so every result below is shown unfiltered` (followed by any earlier search-page warning) is stored, the review goes ahead unfiltered, and the health cache records the failure.
- Then duplicate flags: a video is marked "already in <where>" and deselected if the ledger has it (any project) or a finished file whose name ends in `[<id>]` before its extension exists anywhere under this project's `Youtube` folder (in-progress, intermediate and disowned files do not count). A disk scan failure is logged and skipped.
- Finally `ready_for_review`.

## The AI prompts and what they are asked for
(source: ytdlweb/claude_cli.py)

- Two AI calls exist: (1) turn one topic into search queries; (2) judge candidate videos as keep or drop. Both send instructions in the system turn and every piece of untrusted text (the typed topic, YouTube titles and channels) in the user turn inside labelled blocks `<topic>...</topic>` and `<candidates>...</candidates>`; a closing tag inside the data is removed so it cannot end the block early. No tools are ever offered to the model.
- Replies must be a JSON object. A reply wrapped in a code fence or a sentence is unwrapped (outermost braces). An unparseable reply or a non-object is retried once; then the call fails with the `claude_output:` prefix.

### Search modes
- `visuals` (default, label `VISUALS`): b-roll to cut under something else. Term role: "You are helping a documentary editor find archive/b-roll footage on YouTube." Mission: queries that surface footage OF the topic (places, people, events, on-location footage, aerials, walk-throughs, ceremonies, press events, synonyms, names, related events). Judge: is each candidate "FOOTAGE OF the subject that can be cut into a timeline, not coverage ABOUT the subject". Preset boxes: the six footage types.
- `news` (label `NEWS MONTAGE`): a montage made of the reporting, where the clip's own audio is used. Term role asks for NEWS REPORTING; mission: queries that surface reporting whose audio tells the story, naming people, places, organisations, events, outlets and programmes. A header "PRIORITISE REPORTING" asks for news packages, bulletins, field reports, correspondent pieces, press conferences, briefings, statements and substantive interviews, carrying filing words in both languages (news, report, press conference, briefing, statement, interview, full speech; 新聞, 報導, 新聞報導, 專題報導, 記者會, 訪問, 專訪, 完整版, 談話). Judge header "SCORE THE AUDIO FIRST": on-topic speech counts, pictures second. Preset boxes: the three coverage types.

### Shot types (nine checkboxes)
- Footage group (default ticked): Aerial / drone; Establishing / exteriors; Walk-through / POV / street; Timelapse; Ceremonies / events / protests; Raw / uncut / no commentary.
- Coverage group (default unticked): Interviews / talking heads; News reports; Commentary / analysis / reaction.
- Each ticked type adds its search phrasings (in English and Taiwanese Chinese, for example "aerial, drone footage ... 空拍, 空拍機, 鳥瞰") to the term prompt and its keep guidance to the judge prompt.
- Each UNTICKED coverage type adds an "AVOID" phrasing list to the term prompt and a DROP line to the judge (interviews and talk/panel shows; studio segments, anchors, desk reads and pieces to camera, but keep a field report whose shots carry it; commentary, analysis, explainers, reaction videos, podcasts, vlogs). Unticked footage types add nothing.
- All nine ticked or none ticked both mean "no shot-type preference": the term prompt searches the topic broadly; the judge keeps anything on topic and drops only off-topic results, music, gaming, AI-generated or still-image slideshows (in news mode it also drops music-only, ambient, silent or narration-free b-roll and off-topic talking).
- With at least one footage type ticked in visuals mode, the term prompt opens "PRIORITISE VISUALS" and requires at least two thirds of queries (in each language) to carry one of the ticked phrasings; the judge also drops compilations under heavy overlays.
- Always on the judge's drop list (biased cases): unrelated results, music, gaming, AI-generated or still-image slideshows. In news mode also: silent/ambient/narration-free b-roll, talking about something else, round-ups that only mention the subject.
- Keep extras: in news mode, prefer clear speech over prettier pictures, and fuller statements over 30-second summaries, and accept either language but prefer a clip that stays in one language (dropped under a single-language scope). In visuals mode, "foreign-language material: narration the editor cannot use does not matter" (dropped under a single-language scope). With Raw ticked: prefer the longer, steadier, less-edited item.
- Every biased judge prompt ends: when unclear, KEEP it.

### Language scopes
- `both` (label `EN + ZH`): 8 to 12 English queries and 8 to 12 Traditional Chinese queries as used in Taiwan (not Simplified, not mainland terms); every Chinese query must carry a literal English gloss.
- `en` (`ENGLISH ONLY`): 16 to 24 English queries only; the judge drops a candidate whose title and channel show another language, and keeps one whose language cannot be told.
- `zh` (`CHINESE ONLY`): 16 to 24 Traditional Chinese queries only (proper nouns may stay English inside them), each with an English gloss; the judge drops plainly other-language candidates.
- `exact` (`MY TERM ONLY`): no term call at all; one search of the typed text with the whole candidate cap; the judge still runs.
- Queries in a language the scope excludes are silently discarded, whatever the model returned.
- All queries: 2 to 6 words, no quotes, no boolean operators. Reply shape: `{"terms": [{"q", "lang", "english_gloss"}]}`.

### Term reply handling
- Entries without text, with a language other than en/zh, or repeated (case-insensitive) are dropped.
- A Chinese query with no gloss: the whole reply is asked for a second time; if glosses are still missing, those queries are dropped and the rest kept (logged). No usable query at all: fails with `claude_output: the reply contained no usable queries`.
- The bracketed translation shown at the review is the gloss for Chinese queries and nothing for English ones.

### Relevance reply handling
- Each candidate line sent: `index. title (120 chars) | channel (60 chars) | m:ss duration` (or `?`).
- Reply shape: `{"keep": [indices], "drop": [{"i", "why" (10 words max)}]}`; every index must appear once. Out-of-range or non-numeric indices are ignored; a null keep or drop list reads as empty; an index in both lists counts as keep.

## Which AI provider answers
(source: ytdlweb/ai_backend.py, ytdlweb/claude_cli.py, ytdlweb/config.py)

- Mounted in the dashboard, the provider is asked for afresh on every call from a callback the dashboard installs (Settings → AI providers), so a key added or removed takes effect on the next call without a restart. Provider order known to this app: `claude_code`, `anthropic_api`, `codex`, `openai_api`, `deepseek_api`.
- Refusals from the provider lookup (all `claude_auth:`): the callback raised (`the dashboard could not resolve an AI provider (<type>). An admin can fix this on Settings -> AI providers.`); no provider named (the dashboard's detail text, or "this deployment has no working AI provider. An admin must add a key ... or set ANTHROPIC_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY in the container. Until then no job can generate search terms. See ytdl/web/DEPLOY.md."); an unknown provider name.
- Standalone (no dashboard callback): environment fallback in order: an absolute path in `YTDL_STANDALONE_CLAUDE_CODE` to an existing file (only when `YTDL_DASH_DB` is unset) runs Claude Code; else `ANTHROPIC_API_KEY`; else `OPENAI_API_KEY`; else `DEEPSEEK_API_KEY`; else Anthropic with no key (which then refuses). DEV ONLY for the standalone CLI path.
- A CLI provider (`claude_code`, `codex`) that arrives without its site feature flag enabled is refused: `<label> is not enabled for this site ([features] ai_cli_providers is off).`
- **Anthropic API**: the `anthropic` SDK, a fresh client per call; model `YTDL_CLAUDE_MODEL` (default `claude-sonnet-5`) unless the provider names one; `ANTHROPIC_BASE_URL` optional; max reply 8000 tokens (`YTDL_CLAUDE_MAX_TOKENS`); timeout 180 s (`YTDL_CLAUDE_TIMEOUT`); effort set to low. Failures: missing key or rejected key or permission denied → `claude_auth:` (naming the provider and where to fix it: Settings page or the provider's environment variable); timeout → `claude_timeout: Claude did not answer within Ns.`; connection error → `claude_missing: could not reach the Anthropic API from this container (...)`; SDK not installed → `claude_missing:`; other HTTP status → `claude_output: the Anthropic API answered <code>: ...`; a refusal stop → `claude_output: Claude declined this request (<category>).`; anything else → `claude_output:`.
- **OpenAI and DeepSeek APIs**: one POST to `<base>/chat/completions` with system and user messages, temperature 0, max tokens 8000, `Authorization: Bearer`. Defaults: OpenAI base `https://api.openai.com/v1`, model `gpt-4o-mini`; DeepSeek base `https://api.deepseek.com`, model `deepseek-chat` (overridable by `OPENAI_BASE_URL`, `YTDL_OPENAI_MODEL`, `DEEPSEEK_BASE_URL`, `YTDL_DEEPSEEK_MODEL`). Redirects are never followed. Classification: 401/403 → auth; 408/504 → timeout; 3xx → `claude_missing:` "answered a redirect ... Check the base URL."; other statuses → output with the body (300 characters); no answer in time → timeout; unreachable → missing. Content given as a list of parts is joined.
- **Claude Code and Codex CLIs** (the customer's own installed binary, path supplied by the dashboard): run with arguments from `YTDL_CLAUDE_CODE_ARGS` (default `-p --output-format text --disallowed-tools *`) or `YTDL_CODEX_ARGS` (default `exec --sandbox read-only -`), prompt on standard input as one document ("SYSTEM INSTRUCTIONS ... ----- DATA -----" then the data), UTF-8, timeout 300 s (`YTDL_AI_CLI_TIMEOUT`), working directory the app's data root. Environment is an allow-list (PATH, HOME, LANG, TZ, TERM, temp dirs, proxy variables, Windows system variables, and any `LC_`, `CLAUDE_`, `CODEX_` variable), with the four AI keys always removed, plus the dashboard's overlay (its own HOME for the CLI and an OAuth token). Failures: no path → missing; not installed → missing; timeout; non-zero exit whose output mentions login, authentication, API key, credentials, sign in, subscription and similar → `claude_auth: <label> is installed but not signed in on the dashboard host ...`; other non-zero exit → output with the stderr (300 characters).
- An empty reply from any provider: `claude_output: <label> returned an empty response`.
- Each call logs the provider, duration and character count, or the failure prefix. Keys are never logged or printed.
- The four error prefixes (`claude_auth:`, `claude_missing:`, `claude_timeout:`, `claude_output:`) are kept for every provider; the page maps them to instructions.

### The AI health cache
- States: `ok`, `unauthenticated`, `missing`, `timeout`, `error`, `unknown` (before any check), plus which provider and a detail line.
- Written by: the worker's start-up probe (a real tiny request, "Reply with the two characters: ok", timeout at most 60 s); every real AI call (success sets ok; failure sets the matching state); the idle re-probe while red. Never probed from a page request.

## The download phase
(source: ytdlweb/worker.py, ytdlweb/vendor/downloader.py, ytdlweb/ytdl_common.py, ytdlweb/ytdl_evidence.py)

### Before the first clip
- Destination: `<projects root>/<project label>/Youtube/<folder>` (no folder for a paste with no folder name). Every path segment is validated: no absolute parts, no `..`, no drive letters, nothing that resolves outside the root.
- If the footage tree is proven missing (see guards), nothing is created and the job fails with the missing-tree sentence.
- Otherwise the folder is created; every directory this creates gets mode 2775 (not on Windows); then day-old leftovers in that folder are deleted (in-progress `.part`, `.part-FragN`, `.ytdl`, `.temp` files and intermediate `.fNNN`, `.temp`, `.editready` files older than 24 hours).
- If the job is still marked as held by a local computer (its lease expired), the server takes it back (see "Requester-first downloads").
- Grace for the requester: when local downloads are on and the job was created local, the worker waits up to 4 seconds (`YTDL_LOCAL_CLAIM_GRACE_SECONDS`; 0 disables) polling every 0.1 s for the editor's computer to claim the job; if it does, the server stands down.
- Free-space guard on the server's disk (see guards); refusal fails the job, ending "Free some space and press RETRY FAILED."
- The download total is recounted if missing.

### Per clip (one at a time)
- Before each clip: stop if cancelled; stop (standing down) if a local lease has appeared.
- The clip is taken by a compare-and-set (waiting to downloading); if another executor already took it, skip it.
- Dedupe re-check immediately before downloading: the ledger, then a scan of the destination for a finished file carrying the id; a hit marks the clip skipped and deselected with where it is.
- The clip's host is recorded as `server`.
- Any `.original` copy left from an earlier conversion of this clip is retried for deletion; whatever is still locked is reported as "an earlier copy of this clip is still in use (N MB reclaimable)" on the clip row.
- Live progress (percent, speed, "merging", conversion status) is kept in memory for the poll.
- Cancel during a running download: checked at most every 2 seconds from yt-dlp's progress; the clip is stopped, its leftovers removed or disowned, the clip goes back to waiting, and the job ends cancelled.
- After a success: the file and sidecar get mode 664 (not on Windows), the clip is recorded done (title and thumbnail filled from the download, which is the first time a pasted clip's title is known), a ledger row is written with the job creator's name, and the next clip waits 3 seconds (`YTDL_DOWNLOAD_PAUSE`) unless it was the last.
- A download that reports no file: failed with `the downloader reported no output file`.
- A failure: any file this attempt newly produced is renamed with `.failed` appended (so the dedupe ignores it), this clip's in-progress leftovers are deleted, the clip is marked failed with the error (500 characters), counted, and the traceback is logged.
- After the last clip: the manifest file is written and the job ends `done`.

### Download strategy: anonymous first, cookies as the fallback
- Every clip is tried on the "preferred path". It starts as anonymous (no cookie jar) at every process start.
- The cookie jar counts as usable only if `YTDL_COOKIES_FILE` holds at least one Google sign-in cookie (SID, SAPISID, SSID, HSID, APISID, LOGIN_INFO, `__Secure-1PSID`, `__Secure-3PSID`, `__Secure-1PAPISID`, `__Secure-3PAPISID`). A jar of only header lines is "empty"; a jar of only anonymous cookies is "anonymous"; neither is ever used as a fallback.
- Anonymous attempt fails with a bot check ("confirm you're not a bot") and a usable jar exists: the clip's leftovers are cleared, status "retrying on the cookies path", one retry with the jar.
- Cookies attempt fails with "the page needs to be reloaded" (a flagged account): one retry anonymously.
- When the fallback works, it becomes the preferred path for every later clip until the process restarts; the change is logged once.
- Bot check with no usable jar: the phase stops with the bot-check note: "YouTube is asking this server to sign in to confirm it is not a bot, so nothing can be searched or downloaded from it right now. Downloads run anonymously by default and there is no signed-in session to fall back to: an admin has to export a cookies.txt from a signed-in browser and point YTDL_COOKIES_FILE at it (ytdl/web/DEPLOY.md, "cookies.txt escape hatch"). A jar holding only its header lines counts as none."
- Both paths refused: the phase stops with "Both YouTube download paths are blocked, so nothing more can be fetched right now. Anonymous requests are being bot-checked ... and the signed-in cookies.txt is being refused ... An admin has to export a FRESH cookies.txt from a different signed-in session, and test the same clip both with and without cookies before trusting it ...".
- Other failures (network, HTTP 403 on the media, no format, truncation) never switch paths.
- Every real attempt's outcome on each path (ok or error, time, video id) is recorded as evidence and shown on the health strip.
- A phase-stopping bot check (and the both-blocked case) fails the job, and the remaining clips stay waiting so RETRY re-queues them; the manifest file is not written in that case.

### Quality fallback on a truncated stream
- If yt-dlp gives up on a format with both "more expected" and "giving up after" in its error (one format arriving short repeatedly), the clip's partial file is deleted and the next rung down is tried once: 2160p→1440p, 1440p→1080p, 1080p→720p, 720p→480p, best→1080p; 480p has none.
- If the lower rung lands, the clip row says `<q> stream truncated by YouTube, fell back to <lower>` and the progress status says `<q> stream truncated; retrying at <lower>`. If it fails too: `<q> stream truncated by YouTube and the <lower> retry failed too: <error>`.
- Nothing else downgrades quality.

### The identical-failure breaker
- When 3 consecutive clips (`YTDL_MAX_IDENTICAL_FAILURES`; 0 disables; a non-number reads as 3) fail with the same normalised error (video ids, paths and digits removed, first 120 characters), the phase stops: the manifest file is written, the job is `failed` with a note, unreached clips stay waiting. A clip that lands resets the count.
- Notes: "N clips in a row came back with no usable format ... That is what a YouTube client change looks like (this server is on yt-dlp V), not a problem with these videos: check for a yt-dlp update on the server, then press RETRY to re-queue the failed clips."; if no JavaScript runtime is installed: "... this server has no JavaScript runtime (deno or node) installed, which is what makes YouTube refuse every format. An admin has to add one on the server ..."; for HTTP 403: "... refused when the media itself was fetched (HTTP Error 403) ... check the PO-token helper is reachable (YTDL_POT_BASE_URL) and the server yt-dlp is up to date. Then press RETRY ..."; otherwise "N clips in a row failed the same way: <error>. Fix the cause, then press RETRY to re-queue the failed clips."

### Limits on one clip
- Live or not-yet-started streams are refused (ended streams are allowed): the clip fails with "this is a live stream that has not finished, so it would record until it ends. Download it again once it is an ordinary video." It does not count toward the breaker.
- A download running longer than 2 hours is stopped: "the download took longer than 2 hours and was stopped".
- The editable-file conversion is stopped after 3 hours ("the conversion to an editable file took longer than 3 hours and was stopped"); a codec probe after 120 seconds.

### yt-dlp download options
- Format: for 1080p and below, H.264 video plus AAC audio first, then H.264 video with any audio, then the best video and audio at or below that height; for 1440p, 2160p and best, the best stream at or below that height (converted afterwards). Output container mp4.
- 10 retries, 10 fragment retries, 3 extractor retries, 5 file-access retries; 6 fragments in parallel (`YTDL_FRAGMENT_JOBS`, bounded 1 to 16; a non-number reads as 6).
- File modification time is the download time, not YouTube's date.
- Windows-safe file names; single video only (no playlists).
- JavaScript runtime deno or node, challenge solver fetched from GitHub; PO-token provider when `YTDL_POT_BASE_URL` is set (extractor args `youtubepot-bgutilhttp: base_url`); cache directory from `YTDL_CACHE_DIR`; ffmpeg from `YTDL_FFMPEG_DIR` (default `/opt/ffmpeg` if it exists, else PATH); yt-dlp's scratch directory is the destination folder.

### Conversion for editing (Resolve-safe files)
- After download the file's codecs are probed with ffprobe. If the video is not H.264, or the frame rate is variable (average and nominal rates differ by more than 1%, compared as numbers), or the audio is not AAC, it is converted: video libx264 preset medium CRF 18 High profile yuv420p constant frame rate with the source's colour tags; audio AAC 320 kbit/s; metadata kept; fast-start mp4. Streams already fine are copied.
- If ffprobe itself fails, the file is converted on suspicion; if that guessed conversion fails, the file is delivered as downloaded with the status "could not probe the codecs and the safety conversion failed; kept as downloaded".
- An audio-only result is left alone. No ffmpeg installed: the file is kept as downloaded.
- While converting, the original sits under `<name>.source.editready.<ext>` and the new file is written to `<name>.editready.mp4`; then the converted file replaces the original. Status shown: `converting to H.264 (was <codec>/<audio codec>)`.
- If the original is locked (open in Resolve), it is renamed `<name>.original.<ext>` and the note `original was in use, kept as <file>` is added to the clip row. If even that fails, the converted file is saved as `<title>.converted [<id>].mp4` with the note `converted, but <file> was in use: saved as <file>`.
- A conversion that fails for a known-needed reason fails the clip with `Edit-ready conversion failed: <ffmpeg's last 500 characters>`.
- A DNxHR HQ / PCM `.mov` conversion mode exists in the code. UNREACHABLE: the worker always asks for H.264.

### Folder and file naming
- Search job folder: the topic reduced to a safe folder name: Unicode NFC, the characters `<>:"/\|?*` and control characters replaced by spaces, whitespace collapsed, leading and trailing dots and spaces removed, cut to 80 bytes of UTF-8 on a character boundary, Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9, checked on the part before the first dot) get `_` appended to that part, and an empty result becomes `search`.
- Paste job folder: the optional folder box, through the same rule; blank means loose in `Youtube/` itself.
- Clip file name: `<uploader, 60 bytes> - <title, 140 bytes> [<video id>].<ext>`. Naming contract version 1.
- Credits sidecar beside every clip: `<name>.credits.json` with channel, channel URL, uploader, video URL, title, video id, upload date, duration (sidecar version 1). The media file also carries the channel as artist, the URL as comment, and custom tags `meta_channel`, `meta_video_url`, `meta_channel_url`, `meta_uploader`.
- Manifest file: `manifest.json` in a search's folder (replaced by a re-run of the same term), or `manifest.<job id>.json` in the Youtube root for a paste with no folder. Contents: query, kind, mode, creation time, creator, project, quality, every term (text, language, gloss, translation, enabled, source, hits) and every done or skipped video (id, URL, title, channel, duration, upload date, file path, state, which terms found it). Pretty-printed UTF-8, mode 664. A write failure is logged and does not fail the job.

## Requester-first downloads (the editor's own computer downloads)
(source: ytdlweb/config.py, ytdlweb/worker.py, ytdlweb/db.py, ytdlweb/routes_fleet.py, static/app.js)

- Feature flag `YTDL_LOCAL_DOWNLOAD=1`; off by default. With it off the page never contacts the companion about downloads, shows no switch and no badge, and every job runs on the server (the fleet routes still exist and still require credentials). DORMANT unless set.
- The page is the dispatcher: after the server accepts DOWNLOAD, RETRY or GET LINKS, the page asks the editor's companion to take the job by id only; the companion then claims it from the server, fetches the work order, downloads, reports each clip, and heartbeats.
- If the lease expires (laptop closed, companion killed), the next worker pass takes the job back for good (pinned to the server, holder cleared): every unfinished or failed clip whose finished file already exists in the destination is recorded done with a ledger row (credited to its holder); the rest go back to waiting. Logged as a warning.
- "Download on the server instead" ends a live lease and pins the job; the worker credits what landed and fetches the rest.
- Cancelling the job ends a live lease too.
- When the server's one retry after a hand-back is itself bot-checked, the clip in hand and every clip still waiting are marked failed without further requests, each with "YouTube is blocking the server right now (it asked the server to prove it is not a bot), so the server could not retry this clip. Press RETRY to fetch it from your own computer again.", and the job ends `done` with the warning "Your computer downloaded the clips it could. The server could not retry the ones that failed there, because YouTube is blocking the server right now ... Press RETRY to try them from your own computer again."
- The fleet yt-dlp floor `YTDL_MIN_YTDLP_VERSION` defaults to `2026.08.19`; a value that is not dotted numbers is rejected, logged at error, and the default used instead.

## Free space and missing-tree guards
(source: ytdlweb/routes_api.py, ytdlweb/worker.py)

- Size estimate per second of video: 480p 0.35 MB, 720p 0.625 MB, 1080p 1.0 MB, 1440p 2.0 MB, 2160p and best 4.4 MB (unknown quality reads as 1080p).
- With known durations: need = twice the estimate. With no durations (always for a paste): need = the larger of 2 GB and (clips x 180 s x rate).
- Free space is read for the nearest existing ancestor of the destination (up to 8 levels), cached 60 seconds per filesystem; the cache is dropped whenever a refusal is given so the next press re-measures. Anything unmeasurable lets the download go ahead.
- Refusal (409, reason `disk_full`, with free and estimated bytes): "there is only X GB free where these clips go (<project>/Youtube[/<folder>]), and these N clips need about Y GB (or "this download needs room to work in"), so nothing was started. Free some space and press DOWNLOAD again." (GET LINKS on the paste route.) Numbers under 10 GB show one decimal.
- Applied: at DOWNLOAD/RETRY (unless local downloads are on and the job was created local), at GET LINKS when the server will fetch, and by the worker before the first clip for pastes and for created-local jobs the server ends up doing.
- Missing footage tree: when the project's folder does not exist, the projects root itself does exist, and no folder under the root matches the project label after Unicode normalisation, the tree is declared gone. At a press this is checked only on the way to a disk-full refusal: 409 reason `tree_missing`: "the footage tree is not there: nothing at <root> looks like <project>, so nothing was started. This is the server having lost the share, not a full disk. Tell whoever runs the dashboard, and press DOWNLOAD again once it is back." The worker checks it unconditionally before the first clip and fails the job with the same sentence (ending "... Tell whoever runs the dashboard.").

## Health, evidence and diagnostics
(source: ytdlweb/routes_api.py, ytdlweb/ytdl_evidence.py, ytdlweb/ytdl_canary.py, ytdlweb/ytdlp_nightly.py)

- `GET /api/health` returns (also callable in-process by the dashboard, which then never triggers a fresh network probe):
  - `claude` (AI state), `claude_detail`, `ai_provider`.
  - `yt_dlp` (`ok` or `missing`), `yt_dlp_version`, `yt_dlp_age_days` (days since the version's date; none if not a date or in the future), `yt_dlp_stale` (older than 21 days, `YTDL_YTDLP_MAX_AGE_DAYS`; 0 or less switches the warning off; a non-number reads as 21 with a warning), and `yt_dlp_age_detail`: "the running yt-dlp is N days old (V)", plus ", past the 21 day limit. YouTube breaks yt-dlp deliberately, so update the copy on this server before downloads start failing." or, when a newer nightly is waiting, "A newer build, V, is installed and is used after the next dashboard restart."; or "no yt-dlp is installed on this server"; or "... whose version is not a date this can age ...".
  - `yt_dlp_nightly`: state `off`, `unknown`, `ok` or `failed`, installed and running versions, `pending_restart`, time, error, note.
  - `js_runtime`: `ok` if deno or node is on PATH, else `missing`.
  - `worker_alive`.
  - `cookies` (true when a cookie-file path is set) and `cookies_state` (`none`, `empty`, `anonymous`, `present`).
  - `local_download` (the feature flag).
  - `pot_provider`: `unconfigured` (no `YTDL_POT_BASE_URL`), `ok` or `unreachable` from a 1-second `GET <base>/ping` that does not follow redirects, cached 60 s; `unknown` for the in-process caller when nothing is cached.
  - `plugin_install`: the outcome the container start script wrote for the PO-token plugin install (`ok`, `failed`, `unknown` when no marker, `off` when `DASH_SITE_YOUTUBE_UNBLOCK` is not `1`), with error, time, attempts, version. Marker path `YTDL_PLUGIN_INSTALL_MARKER`, default `/data/unblock-site/plugin_install.json`.
  - `paths`: the last outcome per path (anonymous, cookies) with ok, error (300 characters), time, video id and source (download or canary); `last_download` (newest real download) and `canary` (`enabled`, `last`).
- Evidence is mirrored to `<data root>/ytdl_evidence.json` (written atomically) so it survives restarts; failures to save are ignored.
- Canary: OFF unless `YTDL_CANARY_INTERVAL_SECONDS` is set to a positive number (minimum 300 s enforced). It sleeps one interval first, then extracts (never downloads) `YTDL_CANARY_URL` (default the 19-second "Me at the zoo" video, `jNQXAC9IVRw`) at the 1080p ladder with the same options as a real download; anonymous first, and with the cookie jar only after a bot check and only when the jar holds a sign-in cookie. Results go to the evidence and warnings to the log. DORMANT by default.
- yt-dlp nightly channel: active only when the container start script set `YTDL_YTDLP_NIGHTLY_ROOT` (default root `/data/ytdlp-nightly`) and `YTDL_YTDLP_NIGHTLY` is not `0`.
  - Boot install (`python -m ytdlweb.ytdlp_nightly install [--root DIR]`): runs the refresh with retries after 5, 15 and 30 seconds; always exits 0; prints the installed version or a WARNING that the image's pinned yt-dlp is in use with pip's message.
  - Refresh: skipped if the active version was checked successfully less than 20 hours ago. Otherwise `pip install --pre --upgrade --no-deps --quiet --no-cache-dir --timeout 20 --retries 1 --target <staging> yt-dlp` (5-minute limit), then imports the staged copy in a child process and builds a downloader (2-minute limit). Refused (kept on the previous one) if it does not import, has no dated version, or is older than the image's own yt-dlp. A new build goes into `versions/<version>/`; the `current` file names it; old versions and staging folders are pruned except the one the running process uses. `install.json` records ok, time, checked time (only moved on success), version, previous, image version, error (4000 characters), note, source and attempts.
  - A daily thread wakes 15 minutes after start and then every 6 hours. A new nightly is used only after the next process start; the dashboard is never restarted to apply it.
- Logged events of note: worker disabled; boot recovery counts; AI provider recovered; path preference changes; bot checks; breaker trips; reclaim of an expired lease; claims; duplicates skipped at manifest time; hand-back retries; nightly install outcomes.

## The ledger, download history and personal data
(source: ytdlweb/db.py, ytdlweb/routes_api.py)

- Every downloaded clip writes or replaces one ledger row keyed on the video id: title, channel, project, the typed term, the actual folder, the path under the project (`Youtube/<folder>/<file>` or `Youtube/<file>`), job id, who is credited (the job's creator as stored at write time) and when. Re-downloading a video into another project moves its row. The ledger is never pruned and never deleted with jobs.
- The ledger is fleet-wide: every editor sees every row in the history and in "ALREADY IN" badges.
- "ALREADY IN" text is `<project label>/<folder>`, where an empty folder reads `Youtube`, and old rows without a folder fall back to the typed term.
- Personal-data support for the dashboard (called by the dashboard, not by any route here):
  - Export: every row in jobs (created or claimed by the person), their jobs' terms, clips fetched by their computer (excluding the server mark), ledger rows credited to them, and their attestations, matched case-insensitively. For another person's job that this person's computer fetched, only the fetch facts are exported (ids, phase, mode, holder, machine, free bytes, lease, pin, counters, times; and per clip id, URL, title, channel, duration, upload date, state, error, host).
  - Erase history: deletes the person's FINISHED jobs with their terms, videos and term links (in batches of 500), never the ledger, never attestations, never other people's jobs.
  - Delete (pseudonymise): in one transaction expires their live leases, cancels their unfinished jobs (outright if idle, else flagged so the terms are deleted when the job stops), deletes terms of their finished jobs, replaces their machine names on their jobs with a stand-in (or blanks them), and replaces their name with a pseudonym in jobs, clips, ledger and attestations (keeping one attestation row per version). A blank username or pseudonym is refused.

## Stored data and files
(source: ytdlweb/config.py, ytdlweb/db.py, schema.sql, migrations/*.sql, migrations/README.md)

- `<YTDL_DATA_ROOT>/ytdl.db` (default data root `ytdl/web/data`, container `/ytdl-data`): SQLite in WAL mode, 30-second busy timeout, foreign keys on. Tables: jobs, job terms, job videos, which-term-found-which-video, the ledger, attestations.
- Schema version 15. The schema file is re-applied on every open; migrations 002 to 015 are applied in order, each only when its own "already applied" test says the change is absent, each in its own transaction. A database newer than the app refuses to start ("FATAL: database ... has user_version=N, newer than this app supports ..."); a missing migration file or a migration whose effect is still absent afterwards also refuses to start.
- Migration 003 (historical) cancelled duplicate active jobs per editor with the error "cancelled while enforcing one active job per editor (YTDL-25): this job was orphaned by a duplicate submission" and added a one-active-job index; migration 012 removed that index again when the queue arrived.
- `<data root>/ytdl_evidence.json`: download-path evidence.
- The data root is created at start or mount, never at import.
- Files written into the footage tree: the clips, their `.credits.json` sidecars, `manifest.json` / `manifest.<id>.json`, and possibly `.failed`, `.original`, `.converted [id]` files as described above.

## Settings and environment variables
(source: ytdlweb/config.py, ytdlweb/vendor/downloader.py, ytdlweb/routes_api.py, ytdlweb/ytdlp_nightly.py, ytdlweb/worker.py, ytdlweb/ai_backend.py)

| Variable | Default | Effect |
|---|---|---|
| `YTDL_DATA_ROOT` | `ytdl/web/data` | holds `ytdl.db` and evidence |
| `YTDL_PROJECTS_ROOT` | `ytdl/web/data/projects` | where downloads land |
| `YTDL_DASH_DB` | unset | dashboard database for project lists; unset = standalone |
| `YTDL_COOKIES_FILE` | unset | cookie jar (fallback path for downloads; always used for search and metadata when set) |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` | unset | standalone Anthropic provider |
| `YTDL_CLAUDE_MODEL` | `claude-sonnet-5` | Anthropic model |
| `YTDL_CLAUDE_TIMEOUT` | 180 | API timeout, seconds |
| `YTDL_CLAUDE_MAX_TOKENS` | 8000 | reply ceiling |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `YTDL_OPENAI_MODEL` | unset, `https://api.openai.com/v1`, `gpt-4o-mini` | OpenAI provider |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `YTDL_DEEPSEEK_MODEL` | unset, `https://api.deepseek.com`, `deepseek-chat` | DeepSeek provider |
| `YTDL_CLAUDE_CODE_ARGS`, `YTDL_CODEX_ARGS` | see above | CLI arguments |
| `YTDL_AI_CLI_TIMEOUT` | 300 | CLI timeout |
| `YTDL_STANDALONE_CLAUDE_CODE` | unset | DEV ONLY absolute path to Claude Code when standalone |
| `YTDL_FFMPEG_DIR` | `/opt/ffmpeg` if present | ffmpeg and ffprobe location |
| `YTDL_DOWNLOAD_PAUSE` | 3 | seconds between clips (also sent to companions) |
| `YTDL_MAX_TERMS` | 24 | most terms per job |
| `YTDL_MAX_DURATION` | 1800 | longest kept video for a search, seconds |
| `YTDL_ENRICH_WORKERS` | 2 | metadata fetches in flight |
| `YTDL_ENRICH_PAUSE` | 0.75 | seconds between metadata requests |
| `YTDL_SEARCH_PAUSE` | 2 | seconds between term searches |
| `YTDL_DEV_PROJECTS` | unset | DEV ONLY project list |
| `YTDL_LOCAL_DOWNLOAD` | off | `1` turns on requester-first downloads |
| `YTDL_LOCAL_CLAIM_GRACE_SECONDS` | 4 | worker wait for a local claim |
| `YTDL_LEASE_SECONDS`, `YTDL_HEARTBEAT_SECONDS` | 180, 30 | lease timing |
| `YTDL_MIN_YTDLP_VERSION` | `2026.08.19` | fleet yt-dlp floor |
| `YTDL_YTDLP_MAX_AGE_DAYS` | 21 | staleness warning age |
| `YTDL_CANARY_INTERVAL_SECONDS`, `YTDL_CANARY_URL` | off, "Me at the zoo" | canary |
| `DASH_REPORT_TOKEN`, `DASH_SESSION_SECRET`, `DASH_SESSION_SECRET_PREVIOUS` | unset | fleet credential and identity verification (all fleet routes refuse without the first two) |
| `YTDL_HOST`, `YTDL_PORT` | `127.0.0.1`, 8791 | standalone server |
| `YTDL_WORKER` | unset | `0` disables worker, canary and nightly refresh |
| `YTDL_MAX_IDENTICAL_FAILURES` | 3 | breaker threshold, 0 off |
| `YTDL_POT_BASE_URL` | unset | PO-token sidecar address |
| `YTDL_CACHE_DIR` | unset | yt-dlp cache directory |
| `YTDL_FRAGMENT_JOBS` | 6 | parallel fragments, 1..16 |
| `YTDL_PLUGIN_INSTALL_MARKER` | `/data/unblock-site/plugin_install.json` | plugin-install marker read by health |
| `DASH_SITE_YOUTUBE_UNBLOCK` | `0` | whether the plugin-install state is reported (else `off`) |
| `YTDL_YTDLP_NIGHTLY_ROOT`, `YTDL_YTDLP_NIGHTLY` | unset, on | nightly yt-dlp channel |

Fixed numbers that are not settings: candidate caps 50/100/200/400 (default 100); topic 400 characters; 50 links and 4000 characters per paste; 9 shot types; relevance batches of 40; history page 24 (max 100); recent jobs 20 (max 100); clip timeout 2 h; conversion timeout 3 h; probe 120 s; leftover sweep age 24 h.

## The page
(source: static/index.html, static/app.js, static/cc_spa.js)

### Header and chrome
- When mounted, the dashboard's real top bar is fetched from `../partials/topbar?current=ytdl` and replaces the fallback header (`CC SYNC // YOUTUBE` and a `[ DASHBOARD ]` link to `/`). A failed fetch, a redirect (expired session) or an answer without the topbar marker keeps the fallback. The header space is held for up to 3 seconds while the fetch is in flight. A retired look cookie (`ccsync_ui_effective`) is cleared on load.
- The terminal look is always on: panels marked as windows get a title bar with a fold button whose state is remembered per page (`ccsync.spafold:<path>` in browser storage); bracketed button labels like `[ CANCEL ]` are shown as plain "Cancel"; tooltips show as terminal tips on hover and keyboard focus (and on tap for non-controls on touch screens), Escape or scrolling hides them; confirmations use a dialog with `Cancel` (focused) and `Go ahead`.

### Search controls (top rows)
- Mode toggle `[ VISUALS ]` `[ NEWS MONTAGE ]`, with hints. Choosing a mode the editor is not already in switches the ticked boxes to what they last left in that mode (the mode's preset the first time). Remembered (`ytdl.search_mode`).
- Shot-type checkboxes, grouped "shots of it:" (six footage types) and "also keep:" (three coverage types), remembered per mode (`ytdl.shot_types`, `ytdl.shot_types.news`). Caption: "SHOTS OF IT = footage of the subject; ALSO KEEP = people talking about it". With none or all ticked, a note says "nothing ticked: no bias, claude searches and filters on the topic alone" / "everything ticked: ...".
- "SEARCH IN" language toggle: `[ EN + ZH ]`, `[ ENGLISH ONLY ]`, `[ CHINESE ONLY ]`, `[ MY TERM ONLY ]` with a note under the chosen one; remembered (`ytdl.term_scope`).
- Upload date range: "uploaded from" and "to" date boxes; `[ CLEAR ]` appears when either is set. Not remembered between visits.
- Topic box (Enter submits), project picker (remembered as `ytdl.project` if still offered; otherwise the first), quality picker (1080p, 720p, 1440p, 2160p, best; 480p is not offered), "on this computer" switch (only when local downloads are on; default ticked; remembered as `ytdl.local`), YouTube date window (any date, today, this week, this month, this year; "hour" is not offered), candidate cap ("50 candidates" ... "400 candidates", remembered as `ytdl.max_candidates`), and `SEARCH`.
- Flipping the "on this computer" switch toasts "downloads will be offered to this computer first" or "downloads will run on the server. YouTube originals only sync upwards, so you can fetch one later from the download history." and reloads the project list.
- Paste row: links box (Ctrl or Cmd + Enter submits; Enter adds a line), optional "folder/bin" box (remembered as `ytdl.url_folder`), `GET LINKS`.
- With no projects: the picker says "you are not syncing any project" and a banner says "You have no projects ticked on the dashboard, so there is nowhere to put downloads. Tick one on the dashboard first."; SEARCH and GET LINKS are disabled. "no project list available" / "could not load projects" when the list cannot be read.
- `pick a project first` toast when none is selected. SEARCH and GET LINKS disable themselves while their request is in flight.

### Health strip
- Main pip `<provider> <state>` (provider shown as claude code, claude api, codex, openai, deepseek, or claude), with " · yt-dlp missing" when relevant; green when the AI is ok and yt-dlp present, grey when unknown, red otherwise. Re-read every 2 minutes.
- Extra pips, each shown only when the server sends its key: `yt-dlp V` (amber with "(Nd old)" when stale; red when yt-dlp missing); `no JS runtime` (only when missing); PO token (`PO token ok`, `PO token unreachable`, `PO token missing` when the plugin install failed, or a grey `PO token off`); last download (`last download: anonymous`, `... failed`, with a rough age such as "3 min ago", or `no downloads yet`), with the cookie-jar state in its tooltip; canary (`canary ok`, `canary failed`, `canary: no run yet`, hidden when off).
- Banner lines (each concern its own line, amber or red): no AI credential, AI unreachable, AI timeout, AI failed on the server (naming the provider and detail), yt-dlp not installed, no JavaScript runtime, worker not running ("the pipeline worker is not running: jobs will queue and never start."), no projects, the attached job's error (with the matching instruction appended), "N searches are waiting for your review", and session expired ("your dashboard session has expired. Sign in to the dashboard again and reload this page. The job itself keeps running on the server.", which also stops polling).

### Progress panel
- Phase label (queued, asking claude for search terms, pick the search terms, searching youtube, fetching metadata, filtering + checking for duplicates, ready for review, downloading, done, failed, cancelled), a bar with fixed spans per phase (searching and fetching move within their span by their counters), a ticker (mode, language scope, date range, "N terms (x en / y zh)", "searched i/n", candidates, "metadata i/n", the latest term and its hits, for a queued job "waiting to start: you are next" / "N jobs ahead of it (M from other editors)" / "the downloader on the server is not running", and the failure text), and `[ CANCEL ]` (hidden when finished). Cancel toasts "cancelling: it stops after the video in flight" while downloading, else "cancelled".
- Polling every 1.5 s, slowing to every 5 s after 2 minutes; a network blip retries; 404 detaches; 401 shows the session banner. The job id is kept in the address (`#job=<id>`).

### Term review panel
- Shown while the job is at `terms_review`: every term with a checkbox, its bracketed translation, and "what you typed" on the editor's own; `N of M terms`; `[ TICK ALL ]`, `[ UNTICK ALL ]`, `SEARCH WITH THESE` (disabled with nothing ticked). Ticks stay in the page until the button sends them, then the search starts.

### Review panel (collapsible, `[-] REVIEW` / `[+] REVIEW`, header keeps "N clips · M selected")
- "Terms searched" chips: `all terms (count)` plus one chip per term with its English gloss for Chinese terms and the count of videos currently shown; tooltip says what you typed or generated and how many are filtered out; clicking filters the grid to that term, clicking again clears it.
- A line naming the mode, scope, date range, shot types and cap the search actually ran with.
- Counts: "R relevant · D already downloaded · F filtered out"; `[ SHOW FILTERED OUT ]` / `[ HIDE FILTERED OUT ]` (only when something was filtered).
- `[ CANCEL SEARCH ]` (only at ready_for_review) asks "Discard this search? Nothing from it was downloaded, and its results will be thrown away." then cancels and clears the page ("search cancelled").
- `[ SELECT ALL ]`, `[ SELECT NONE ]` (scope follows whether filtered-out cards are shown).
- `DOWNLOAD N`: enabled at ready_for_review or done with at least one selected and the terms accepted.
- Grid cards: thumbnail (YouTube's own, or `i.ytimg.com/vi/<id>/mqdefault.jpg`, no referrer), a tick box, title linking to YouTube in a new tab (clicking the title does not toggle the card), channel, duration, upload date, and the filter note or "unavailable". Duplicates are dimmed with `ALREADY IN <where>` and cannot be ticked. Clicking a card toggles it; ticks are sent one at a time per card in order and roll back with a toast on failure.
- Empty grid: "all N filtered out: [ SHOW FILTERED OUT ] to see them" or "nothing found for this term".
- Footer: "N selected · Xh Ym of footage · roughly G GB · F GB free on the computer doing the download · into <project>/Youtube/<folder>".
- The review panel re-opens itself when a job newly arrives at ready_for_review; otherwise its fold state is remembered (`ytdl.collapsed`). Paste jobs never show the review panel.

### Downloads panel (collapsible list)
- Phase, "N/M downloaded", failed count, this computer's live progress when it is the downloader ("clip i/n · 38% at 4.2 MB/s · 2:10 left" or "converting to H.264 on your computer"), free space reported by the claiming computer, and when done "N clips landed in <path>. Click a row to open the folder".
- Badge "downloading on your computer" (green) or "downloading on the server", with "claimed by <name>" in the tooltip (local-download feature only).
- `[ DOWNLOAD ON THE SERVER INSTEAD ]` (only while this job is held locally): one click; toast "handing this job back to the server: it picks up whatever your computer has not finished".
- `[ STOP ]` (only while this computer's companion has reported on the job): asks the companion to stop its current clip; toasts for success, too-old companion, refusal, or not answering.
- `[ CANCEL ]`.
- A note and `[ RETRY N FAILED ]` (or `[ RETRY N CLIPS ]` when a failed job has waiting clips but no failed ones) on a done or failed job; toast "re-queued the clips that failed"; refusals as red toasts.
- One row per clip: thumbnail, title (or id), and state: percent and speed, merging or converting, "failed: <reason>", "already downloaded", "done: <note>", or the state word. A finished clip row opens its folder.

### Waiting for you and Queue panels
- "Waiting for you": the editor's jobs parked at a review (term review or manifest review) with `[ RESUME ]` (attach) and `[ CANCEL ]`. Hidden when empty.
- "Queue": waiting jobs numbered in run order, with `[ UP ]`, `[ DOWN ]` (disabled at the ends) and `[ CANCEL ]`. Hidden when empty. A paste shows as "pasted links".
- After a new job: if anything is ahead, a toast "queued behind N jobs, M of them from other editors: it starts when they finish".

### Recent searches (collapsible, header count)
- The editor's last 15 jobs: time, phase in words, "topic → project" or "links → project/Youtube", mode, scope, date range, shot types, "max N". Clicking a row attaches to that job.

### Download history (collapsible, header "N clips")
- 24 ledger rows at a time, newest first, `[ OLDER ]` for more, "showing N of M. Click a clip to open its folder". Each row: thumbnail, title, "<project>/<folder> · channel · who", time.
- Clicking a row (or a finished download row) asks the companion to open the folder (`POST http://127.0.0.1:8899/ytdl/reveal` with the path under the projects root). Outcomes: success toast; companion says the clip is not on this computer → a toast with `[ GET IT FROM THE NAS ]`, which calls the companion's fetch route and polls every 1.5 s showing "getting <file> from the NAS - N%" until done, then opens the folder; companion unreachable, too old (404) or failing → a toast naming the folder `Projects/<path>` "under your sync drive" with `[ COPY PATH ]` (clipboard; "path copied" or "copy it from the line above").

### Talking to the editor's companion (local-download feature only)
- On load (only when local downloads are on and the switch is ticked) the page asks the companion's capabilities route for this computer's hostname, 1-second limit, to widen the project list on a wired machine.
- After DOWNLOAD, RETRY or GET LINKS: if the job was created with the switch off, a toast says the server is fetching it. Otherwise it probes `/ytdl/capabilities` (1 s, then one retry of 5 s only after a timeout), checks the companion runs the job's quality, then posts `{job_id}` to `/ytdl/download`. Every way this fails ends in one toast per distinct reason beginning "Downloading on the server: ..." (tray too old, not answering with the self-test hint `http://127.0.0.1:8899/status`, declined with its reason, busy with another job, wrong quality, HTTP code), each adding that originals only sync upwards. A terms refusal from the companion gives "Please first accept the download terms in the CC Sync tray: <route>. This download runs on the server instead." (default route "Tray > Settings > Accept YouTube Terms").
- After a successful hand-off it watches `/ytdl/progress` every 3 s for up to 240 s and, if the companion gave the job back, toasts its reason once. While the job is local, it reads `/ytdl/progress` every 2 s for the live line; a 404 turns that off for the session.

### Opening the page
- Order: attestation, health, machine probe, projects, then recent searches, history and queue; then attach to the editor's active job if there is one (rewriting `#job=`), else to the job in the address, else nothing.
- Load failure shows "failed to load: <message>" in the Recent searches list.

### Look and layout
(source: static/style.css)
- Dark red-on-black monospace theme; under 600 px wide the search controls wrap to full-width rows and fields use 16 px text; touch screens get 44 px tap targets; tablet and phone layouts of the shared dashboard top bar (a "more" sheet at 601-900 px, a bottom dock at 600 px and below, the toast lifted above the dock); reduced-motion and forced-colours adjustments. Several blocks are byte-identical copies shared with the dashboard, b-roll and music pages.

## Deployment notes in the tree
(source: DEPLOY.md, vendor/PROVENANCE.md, .gitignore, requirements.lock)

- `DEPLOY.md` is the operator guide (feature flags `youtube_download` and `youtube_unblock` in the site file, environment table, AI providers, the nightly yt-dlp, the unblock components, the umask and chmod rule, the cookie-jar history and the two-way test). It is documentation, not behaviour; its mismatches with the code are listed below.
- `vendor/PROVENANCE.md` records that the vendored download and search code has no licence grant yet.
- `.gitignore` excludes caches, virtual environments, `*.db` files and `data/`.

## Looks redundant or overlapping

- The quality table and format selector exist twice (`ytdl_common` and `vendor/downloader`), as do the sidecar field writer (`credits_sidecar` and `_write_sidecar`) and the version-ranking rule (`config.version_rank` and `ytdlp_nightly.version_rank`); the size-per-second table exists in both the server and the page.
- Five ways to stop or discard a job on one page: progress `[ CANCEL ]`, downloads `[ CANCEL ]`, review `[ CANCEL SEARCH ]`, Waiting `[ CANCEL ]`, Queue `[ CANCEL ]`, plus `[ STOP ]` (companion clip) and `[ DOWNLOAD ON THE SERVER INSTEAD ]`.
- DOWNLOAD on a finished job's review and `[ RETRY N FAILED ]` call the same route.
- Two PO-token mechanisms are reported (the sidecar URL probe and the plugin-install marker) and folded into one pip.
- Two places show a job's search settings (progress ticker and review line) plus Recent searches rows.
- `cookies` (path set) and `cookies_state` both on health; only the second means anything.
- Unused code: `downloader.probe_info`, `QUALITY_FORMATS`, the `audio` quality and `cookies_browser` paths, the DNxHR conversion; `ytsearch.existing_ids`, `parse_duration`, `fmt_duration`.
- The page's 409 "a previous search is still open" handling and the "discard parked search and retry" confirm are UNREACHABLE: job creation never answers 409 with a job id any more (it queues).
- The fleet identity verifier and token comparison are copies of the dashboard's.

## Claims the code does not back

- `DEPLOY.md` says the fleet route compares `YTDL_MIN_YTDLP_VERSION` as a string; the code ranks it numerically (and rejects a non-numeric floor). The claim body comment "Compared as a string" is stale too.
- `routes_api.cancel` docstring and the page's toast say a cancel stops "after the video in flight" / "never mid-file"; the worker now stops a running clip within about 2 seconds.
- `DEPLOY.md` says pasted links always land in `Youtube/` with no subfolder; an optional folder box now exists.
- `schema.sql` says a paste job's `term` is the folder name; the code always stores an empty term. `db.create_url_job` docstring says `term_dir` is always empty; it is the folder name when given.
- `db.py` module docstring: "There are no migrations yet"; there are fourteen.
- `pyproject.toml` comment: Claude Code is a binary the deploy provisions and is reached by subprocess; the default is the Anthropic SDK and the CLI path is optional.
- `DEPLOY.md` "Where things live" calls `claude_cli.py` "`claude -p`" and says migrations are "at v6"; the code is SDK-based and at v15. `migrations/README.md` omits 013 and 014.
- `index.html` comments say an undownloaded manifest blocks every new search; the queue removed that. The health pip's tooltip says "server-side Claude Code + yt-dlp" though any of five providers may answer.
- `DEPLOY.md` says the companion-side attestation is part of the server's refusal; the server only checks the per-user record.
- `DEPLOY.md` table says `YTDL_LOCAL_DOWNLOAD` is set to 1 by the deploy script and `DEPLOY.md` says "cookies false means broken"; neither is decided in this code (the code's default is off and anonymous-first).
- `ytsearch.py` docstring implies cookies are an escape hatch; search and metadata calls use the jar unconditionally whenever a path is set.

## Could not determine

- How the dashboard mounts the app: the login gate, the `youtube_download` feature flag, the `x-ccsync-user` injection, the gate stamp, and the AI provider chain and pin logic all live in dashboard code outside this section.
- The companion's loopback routes (`/ytdl/capabilities`, `/ytdl/download`, `/ytdl/progress`, `/ytdl/cancel`, `/ytdl/reveal`, `/ytdl/fetch`) and its executor; only the page's side is here.
- Whether the Anthropic SDK accepts the `output_config={'effort': 'low'}` argument with the configured model.
- The container start script that writes the plugin-install marker, sets `YTDL_YTDLP_NIGHTLY_ROOT` and installs the nightly at boot.
- Which dashboard screens call the export, erase-history and delete functions, and when.
