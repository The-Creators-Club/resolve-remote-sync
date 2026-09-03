-- YouTube downloader schema v1. Every statement is CREATE ... IF NOT EXISTS, so
-- this file is applied to every database the app opens and additive changes (a
-- new table, a new index) need no migration -- the same arrangement music/web
-- uses. Anything NOT expressible that way (an ALTER) needs a file in
-- migrations/ and a bump of ytdlweb.db.CURRENT_SCHEMA_VERSION.
--
-- This file deliberately does NOT set `PRAGMA user_version`. Because it is
-- re-run against EXISTING databases, a stamp here marks an unmigrated database
-- as current and the migration it needs is then skipped forever -- that is not
-- hypothetical, it cost music/web a live index (see its schema.sql header).
-- ytdlweb.db.ensure_schema() owns the version.
PRAGMA journal_mode=WAL;

-- One row per "editor typed a topic and hit SEARCH", or pasted links and hit
-- GET LINKS. The phase column is the whole state machine and every transition
-- is a committed UPDATE, because the SPA polls this row 1500 ms apart and a
-- phase held in memory would lie to it across a container restart.
CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY,
    created_by       TEXT NOT NULL,          -- dashboard username; owns the job
    -- 'search' = the Claude-expanded topic pipeline; 'urls' = the editor
    -- pasted YouTube links and wants exactly those. A url job has no
    -- search/claude/filter half at all: the API writes its job_videos rows
    -- itself and _phase_start sends it straight to `downloading`. On an
    -- existing database this arrives via migrations/004.
    kind             TEXT NOT NULL DEFAULT 'search',
    -- For a search job: what the editor typed. For a url job: the name of the
    -- folder they are filing the links under -- same column because it is the
    -- same fact downstream (the ledger's "why this clip is here", the manifest
    -- header, and the folder under Youtube/).
    term             TEXT NOT NULL,
    term_dir         TEXT NOT NULL,          -- filesystem-safe form of `term`
    project_slug     TEXT NOT NULL,
    project_label    TEXT NOT NULL,          -- rel path, e.g. '2026/FF5/Energy Transition'
    quality          TEXT NOT NULL DEFAULT '1080p',
    period           TEXT,                   -- hour|today|week|month|year, NULL = any
    max_per_term     INTEGER NOT NULL DEFAULT 15,
    -- The ceiling on CANDIDATE VIDEOS this search may accumulate, and so on
    -- the metadata calls the enrich phase makes: 24 terms x 15 results is 336
    -- candidates, and 112 rapid metadata calls is where YouTube cut the NAS's
    -- IP off (2026-08-11). One of ytdlweb.config.CANDIDATE_CAPS, validated in
    -- routes_api and enforced in worker._phase_search where the candidates are
    -- accumulated -- not after the fact, because the point is the CALLS.
    -- Stored per job so a job resumed after a restart re-runs with the number
    -- it was submitted with. Meaningless for kind='urls': nothing is searched,
    -- so nothing accumulates. On an existing database this arrives via
    -- migrations/006, whose default is this one (test_db.py pins the pair).
    max_candidates   INTEGER NOT NULL DEFAULT 100,
    -- Which SHOT TYPES the editor ticked for this search: a comma-separated
    -- list of ytdlweb.claude_cli.SHOT_TYPES keys, composed into the {bias}
    -- block of BOTH Claude prompts. The default here is that module's own
    -- DEFAULT_SHOT_TYPES and the two are pinned together by a test -- an old
    -- row (and one written by migrations/005) reads as the defaults, which is
    -- the behaviour every job before the checkboxes actually ran with. An
    -- EMPTY string is different and deliberate: the editor ticked nothing,
    -- which means an unbiased search. Meaningless for kind='urls': nothing is
    -- searched for, so nothing is biased.
    shot_types       TEXT NOT NULL DEFAULT 'aerial,establishing,walkthrough,timelapse,event,raw',
    -- WHAT THE SEARCH IS FOR: 'visuals' (b-roll to cut UNDER something
    -- else, so the pictures are what gets used) or 'news' (a montage made OF
    -- the reporting, so the clip's own AUDIO is what gets used). It chooses
    -- the framing of BOTH AI calls -- the queries generated and the rubric
    -- the candidates are judged on -- and the rubrics, and why they differ,
    -- live in ytdlweb.claude_cli.MODES. The default here is that module's
    -- DEFAULT_MODE and test_db.py pins the pair; an old row (and one written
    -- by migrations/009) reads as 'visuals', which is the only search this
    -- app ran before 2026-08-18. Meaningless for kind='urls': nothing is
    -- searched for, so nothing is framed.
    -- NOT `download_mode` / `mode_lock` below, which are about which MACHINE
    -- fetches the clips.
    mode             TEXT NOT NULL DEFAULT 'visuals',
    -- WHICH LANGUAGES the search runs in: 'both' | 'en' | 'zh' | 'exact'
    -- (claude_cli.TERM_SCOPES, 2026-08-25). Orthogonal to `mode`: 'en'/'zh'
    -- narrow the queries the model writes (and add a language rule to the
    -- relevance pass), 'exact' skips the model and searches the editor's
    -- text alone. The default is claude_cli.DEFAULT_TERM_SCOPE and
    -- test_db.py pins the pair; an old row (and one written by
    -- migrations/011) reads as 'both', the only search before today.
    term_scope       TEXT NOT NULL DEFAULT 'both',
    -- An UPLOAD-DATE range, YYYYMMDD like job_videos.upload_date so the two
    -- compare as strings; NULL = no bound on that side. Enforced in the
    -- filter phase as a mechanical drop (YouTube's search has no range
    -- filter; `period` above is its fixed windows).
    date_from        TEXT,
    date_to          TEXT,
    -- queued > generating_terms > terms_review > searching > enriching >
    -- filtering > ready_for_review > downloading > done | failed | cancelled
    -- (kind='urls' skips the middle: queued > downloading > done)
    phase            TEXT NOT NULL DEFAULT 'queued',
    -- WHERE THIS JOB SITS IN ITS EDITOR'S QUEUE (2026-08-30). One job RUNS per
    -- editor; the rest wait at `queued` in this order, which is the order the
    -- SPA's QUEUE list shows and [ UP ]/[ DOWN ] rewrite. Per editor, 1-based,
    -- and only meaningful while the phase is `queued` -- a job that has started
    -- keeps whatever number it was given, and nothing reads it again. On an
    -- existing database this arrives via migrations/012; every row there is
    -- terminal or already running, so 0 (the default) is honest for all of them.
    queue_position   INTEGER NOT NULL DEFAULT 0,
    -- SKIP THE TERM REVIEW (2026-08-30). 0 is the SPA's job: the editor sees
    -- the generated queries at `terms_review`, unticks what they do not want,
    -- and presses SEARCH WITH THESE. 1 is the headless path a script takes --
    -- POST /api/jobs {auto_terms: true} -- which goes straight from
    -- generating_terms to searching with every term enabled. Stored per job for
    -- the reason shot_types and max_candidates are: a job that sat queued over
    -- a restart must resume as the caller submitted it, and there is nobody
    -- watching a script's job to press the button for it.
    auto_terms       INTEGER NOT NULL DEFAULT 0,
    -- THE TWO WIDENING SIGNALS THIS JOB WAS ACCEPTED UNDER (ytdl-web-2,
    -- bug-hunt-2026-09-03). `created_local` is the request's `local` (0 = the
    -- NAS worker fetches, which no machine's sync plan constrains) and
    -- `created_machine` the hostname the SPA learned from its companion (a
    -- mixed account's WIRED computer works off the whole tree). Both go into
    -- projects.resolve_project at create AND again in start_download, which
    -- re-validates the destination on every write (YTDL-30) and used to re-run
    -- it with the narrow defaults -- answering "no longer a project you sync"
    -- for a project that was never ticked and never had to be.
    -- Read from the JOB and never from the request that presses DOWNLOAD: a
    -- client-supplied local=0 there would be any editor writing into any
    -- active project. The defaults are resolve_project's own pre-widening
    -- values, so a row from migrations/013 re-validates as it always has.
    created_local    INTEGER NOT NULL DEFAULT 1,
    created_machine  TEXT,
    -- Carries a machine-readable prefix the SPA maps to ops hint text:
    -- claude_auth: / claude_missing: / claude_timeout: / claude_output: .
    error            TEXT,
    terms_total      INTEGER DEFAULT 0,
    terms_done       INTEGER DEFAULT 0,
    candidates       INTEGER DEFAULT 0,
    enrich_total     INTEGER DEFAULT 0,
    enrich_done      INTEGER DEFAULT 0,
    dl_total         INTEGER DEFAULT 0,
    dl_done          INTEGER DEFAULT 0,
    dl_failed        INTEGER DEFAULT 0,
    cancel_requested INTEGER DEFAULT 0,      -- honoured between terms/videos
    -- WHO DOWNLOADS THIS JOB'S CLIPS (docs/YTDL_LOCAL_DOWNLOAD.md). 'server' is
    -- the NAS worker, which is the default and the fallback executor; 'local'
    -- means the requester's own companion holds a lease and is fetching them
    -- from their residential IP (the 2026-08-13/14 incident: bulk anonymous
    -- downloads out of one datacentre IP is the bot-check profile). One holder
    -- at a time, compare-and-set in ytdlweb.db.claim_download.
    download_mode    TEXT NOT NULL DEFAULT 'server',
    claimed_by       TEXT,                   -- the leaseholder's username
    -- ...and WHICH OF THAT EDITOR'S COMPUTERS holds it (migrations/010,
    -- data-model-7 / CR-66, 2026-08-21): the companion-minted machine_id, the
    -- same one the fleet report and the dashboard's `machines` registry key
    -- on. A name is a person, and a person can own two editing machines; both
    -- used to pass the CAS as "the same holder refreshing". NULL is a holder
    -- that did not say which machine it is (any companion older than this),
    -- and reads as today's per-editor behaviour, never as "some other
    -- machine".
    claimed_machine  TEXT,
    -- ISO-8601 UTC (db.now()), compared as a STRING -- see migrations/007.
    -- Expiry is what makes a vanished laptop recoverable: the worker takes the
    -- job back and downloads only what is missing.
    lease_expires_at TEXT,
    -- 'server' pins the job to the NAS worker for good: the editor asked for it
    -- (plan §9), or the server reclaimed an expired lease -- which is one-way
    -- per job (plan §3), and this column is how.
    mode_lock        TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- The user's own term plus everything Claude expanded it into. `english_gloss`
-- is what makes the zh half of the manifest readable to an editor who does not
-- read Chinese (REQ 5); it is required for lang='zh' and NULL for lang='en'.
CREATE TABLE IF NOT EXISTS job_terms (
    id            INTEGER PRIMARY KEY,
    job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    term          TEXT NOT NULL,
    lang          TEXT NOT NULL,             -- 'en' | 'zh'
    english_gloss TEXT,                      -- literal translation; zh terms only
    -- What the term review shows in brackets (2026-08-30, the owner: "for
    -- chinese ones, it should show a translation in brackets"). It is
    -- english_gloss for a query Claude wrote, and NULL for a query that is
    -- already English -- a separate column because the two are asked different
    -- questions: english_gloss is the manifest's readability guarantee for a zh
    -- query (REQ 5), this is "what to print after this row's term, if
    -- anything", and the editor's OWN term can have one where no gloss was ever
    -- generated.
    translation   TEXT,
    -- Will this term actually be searched? Every term arrives ticked; the
    -- editor unticks the ones they do not want at `terms_review` and
    -- worker._phase_search only ever looks at the ones left (2026-08-30).
    -- DEFAULT 1 so every path that writes a term -- including migrations/012 on
    -- a database full of finished searches -- means "searched", which is what
    -- every term before this actually was.
    enabled       INTEGER NOT NULL DEFAULT 1,
    source        TEXT NOT NULL,             -- 'user' | 'claude'
    searched      INTEGER DEFAULT 0,
    hits          INTEGER DEFAULT 0,
    UNIQUE(job_id, term)
);

CREATE TABLE IF NOT EXISTS job_videos (
    id             INTEGER PRIMARY KEY,
    job_id         INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    video_id       TEXT NOT NULL,
    url            TEXT NOT NULL,
    title          TEXT,
    channel        TEXT,
    duration       REAL,
    upload_date    TEXT,
    view_count     INTEGER,
    -- yt-dlp's own thumbnail URL when enrichment got one; the client falls back
    -- to i.ytimg.com/vi/<id>/mqdefault.jpg, which needs no metadata at all.
    thumbnail      TEXT,
    meta_error     TEXT,                     -- unavailable/private/geo-blocked
    relevant       INTEGER DEFAULT 1,
    relevance_note TEXT,
    duplicate      INTEGER DEFAULT 0,
    duplicate_of   TEXT,                     -- '<project label>/<term>' it lives under
    selected       INTEGER DEFAULT 1,        -- auto-selected (REQ 4); forced 0 when duplicate
    dl_state       TEXT DEFAULT 'none',      -- none|pending|downloading|done|failed|skipped
    dl_error       TEXT,
    filepath       TEXT,
    -- 'server' or the editor whose machine fetched it: the history row's
    -- "whose IP got this clip", and the first thing to look at when one editor's
    -- downloads fail and everybody else's do not (YTDL_LOCAL_DOWNLOAD.md §4).
    download_host  TEXT,
    UNIQUE(job_id, video_id)
);

-- Which term(s) surfaced which video. A join table rather than a JSON column on
-- job_videos because the manifest's term chips filter the grid by it, and a row
-- is written for EVERY term that returned the video -- including the second and
-- third term to hit one already seen, which is precisely the attribution a
-- "first writer wins" column would throw away.
CREATE TABLE IF NOT EXISTS job_video_terms (
    job_id   INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL,
    term_id  INTEGER NOT NULL REFERENCES job_terms(id) ON DELETE CASCADE,
    PRIMARY KEY (job_id, video_id, term_id)
);

-- The permanent cross-project dedupe ledger (REQ 6). It outlives the job that
-- wrote it -- jobs are history, this is "the fleet already has this clip" --
-- so it is keyed on the video id alone and never cascades.
CREATE TABLE IF NOT EXISTS downloads (
    video_id      TEXT PRIMARY KEY,
    title         TEXT,
    channel       TEXT,
    project_slug  TEXT NOT NULL,
    project_label TEXT NOT NULL,
    term          TEXT NOT NULL,             -- what the editor typed, verbatim
    -- The FOLDER the clip is actually in, safe_term_dirname(term). Both are
    -- kept because the ALREADY IN badge has to name a path an editor can open
    -- over SMB, and `term` frequently is not one (YTDL-31, 2026-08-11).
    term_dir      TEXT,
    rel_path      TEXT NOT NULL,             -- 'Youtube/<term_dir>/<filename>' under the project
    job_id        INTEGER,
    downloaded_by TEXT,
    downloaded_at TEXT NOT NULL
);

-- The poll endpoint reads a job's terms and videos on every tick.
CREATE INDEX IF NOT EXISTS idx_jobs_user     ON jobs(created_by, id DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_phase    ON jobs(phase, id);
CREATE INDEX IF NOT EXISTS idx_terms_job     ON job_terms(job_id, id);
CREATE INDEX IF NOT EXISTS idx_videos_job    ON job_videos(job_id, id);
CREATE INDEX IF NOT EXISTS idx_videos_state  ON job_videos(job_id, dl_state);
CREATE INDEX IF NOT EXISTS idx_jvt_term      ON job_video_terms(job_id, term_id);

-- THE QUEUE (2026-08-30). There used to be a UNIQUE index here --
-- idx_jobs_one_active, one non-terminal job per editor (YTDL-25) -- and a
-- double-clicked SEARCH was the reason: create_job's check is read-then-insert
-- and the second click fits between the two. An editor may now have as many
-- jobs as they like, waiting at `queued` in queue_position order, so the
-- uniqueness is gone (migrations/012 drops it) and the double click it guarded
-- is no longer an error at all: the second job simply queues behind the first,
-- which is what the editor was trying to say.
--
-- What replaces it is an ORDINARY index, because db.claim_next_job now asks
-- "does this job's editor already have a busy one" on every tick.
CREATE INDEX IF NOT EXISTS idx_jobs_queue
    ON jobs(created_by, phase, queue_position, id);

-- The rights/ToS attestation record (attestation.py, 2026-08-17). One row per
-- (editor, wording version) -- a re-worded notice adds a row rather than
-- replacing the record of what was agreed to before. Downloads refuse until
-- the current TEXT_VERSION is present for the caller; see
-- docs/legal/YOUTUBE_FEATURE_NOTICE.md.
CREATE TABLE IF NOT EXISTS attestations (
    username     TEXT NOT NULL,
    version      TEXT NOT NULL,
    text_sha256  TEXT NOT NULL,
    accepted_at  TEXT NOT NULL,
    PRIMARY KEY (username, version)
);
