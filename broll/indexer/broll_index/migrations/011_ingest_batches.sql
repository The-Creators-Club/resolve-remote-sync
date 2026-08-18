-- Drag-and-drop b-roll ingest: the work orders the dashboard hands a
-- companion, and the per-clip ledger it reports back against
-- (docs/BROLL_INGEST_PLAN.md §2, 2026-08-18).
--
-- Three parties share these two tables and none of them can see the others'
-- memory: the browser only dispatches, the companion crunches locally under a
-- fleet token, and this database is the only place the truth about a batch
-- lives. So EVERY transition is a row here -- a batch that exists only in a
-- companion's process is a batch nobody can cancel, and a clip whose stage
-- lives only in RAM is a clip that restarts from zero after a reboot. Same
-- rule the sync lanes' latches follow (docs/SYNC_SAFETY.md).
--
-- `uid` rather than an autoincrement id, minted server-side as
-- lower(hex(randomblob(16))) (the music 003 precedent): these ids travel
-- through a browser and a loopback POST, and a guessable integer would let a
-- logged-in editor enumerate -- or drive -- another editor's batch.
CREATE TABLE ingest_batches (
    uid TEXT PRIMARY KEY,
    -- The VERIFIED dashboard identity that created it. The fleet routes prove
    -- a caller is "a fleet machine" (shared DASH_REPORT_TOKEN) and nothing
    -- about WHICH, so the editor name is re-derived from a signed
    -- X-CCSync-Identity on every fleet call and compared with this column
    -- (H5, COMMERCIAL_READINESS.md item 7).
    editor TEXT NOT NULL,
    -- Which of that editor's machines holds the lease. NULL until a claim.
    -- One editor may have three companions; only one of them may crunch a
    -- batch, or two would write the same proxy over each other.
    machine TEXT,
    companion_version TEXT,
    -- The shoot folder, already through archive_names.safe_name on the way in.
    share TEXT NOT NULL,
    collection TEXT NOT NULL DEFAULT 'owned',
    -- {tier, run_mode, upload_originals, keep_subfolders, transcribe:false}.
    -- JSON because the settings form grows per release and a column per knob
    -- would mean a migration per release; nothing SEARCHES on them.
    settings_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued'
      CHECK (state IN ('queued','claimed','running','done','done_with_errors','cancelled','failed')),
    n_items INTEGER NOT NULL DEFAULT 0,
    n_done INTEGER NOT NULL DEFAULT 0,
    n_failed INTEGER NOT NULL DEFAULT 0,
    n_live INTEGER NOT NULL DEFAULT 0,
    n_duplicate INTEGER NOT NULL DEFAULT 0,
    current_item_uid TEXT,
    -- The lease, exactly as the ytdl fleet routes hold one: a claim is only
    -- good for lease_seconds and dies of silence, so a machine that is
    -- switched off mid-batch releases it without anyone pressing anything.
    lease_expires_at TEXT,
    last_heartbeat_at TEXT,
    -- Cancel is a REQUEST, not a kill: the companion learns about it on its
    -- next heartbeat (410) or in the report reply, and only then does it stop
    -- and release. A row flipped straight to 'cancelled' would leave a
    -- companion crunching a batch the server has forgotten.
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    cancel_by TEXT,
    upload_paused INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT
);
CREATE INDEX idx_ingest_batches_editor ON ingest_batches(editor, created_at);
CREATE INDEX idx_ingest_batches_state  ON ingest_batches(state);

CREATE TABLE ingest_items (
    uid TEXT PRIMARY KEY,
    batch_uid TEXT NOT NULL REFERENCES ingest_batches(uid) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    orig_name TEXT NOT NULL,
    -- Sub-folder below the shoot root, forward slashes, '' for a flat drop.
    -- Blanked at create time when the batch's keep_subfolders is off, so the
    -- claim allocator never has to consult the settings blob.
    rel_dir TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER,
    -- xxh64(first 8MiB + last 8MiB + size) -- the SAME digest videos.hash
    -- carries (broll_index/hashing.py), or duplicate detection would compare
    -- two different functions and always disagree.
    hash TEXT,
    duration_s REAL, fps REAL, width INTEGER, height INTEGER, codec TEXT, shot_date TEXT,
    -- 'upload' = the browser streamed the bytes into staging (a drop; browsers
    -- expose no local paths); 'path' = the native picker gave a real path and
    -- the clip is indexed where it lies.
    source TEXT NOT NULL CHECK (source IN ('upload','path')),
    -- Minted AT CLAIM, not at create: the row must not exist until a machine
    -- has actually taken the work, or a batch nobody ever ran would leave
    -- permanent status='ingesting' ghosts in the library.
    video_id INTEGER REFERENCES videos(id) ON DELETE SET NULL,
    duplicate_of INTEGER REFERENCES videos(id) ON DELETE SET NULL,
    -- Allocated at claim against the names already published in that folder,
    -- never against what is on disk (build_archive.claim_name's lesson,
    -- BROLL-IDX-5): archive_path = archive_dir/Proxy/archive_stem.mp4.
    archive_dir TEXT,
    archive_stem TEXT,
    state TEXT NOT NULL DEFAULT 'pending'
      CHECK (state IN ('pending','duplicate','proxying','framing','describing','indexed','uploading','live','failed','cancelled','skipped')),
    stage_percent INTEGER,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    original_uploaded INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
CREATE INDEX idx_ingest_items_batch ON ingest_items(batch_uid, ord);
CREATE INDEX idx_ingest_items_video ON ingest_items(video_id);

-- Which browse root a share belongs to, said outright instead of derived.
--
-- search.creators_shares() reads own-footage membership from
-- BROLL_CREATORS_SHARES plus share_roots.source='proxies' -- and an ingested
-- shoot is neither: its share is new (so no env var names it) and it archives
-- ORIGINALS, so the source flag would file a customer's own camera footage
-- under Downloads. NULL keeps today's rule for every share the indexer has
-- ever pushed; only the ingest path writes a value.
ALTER TABLE share_roots ADD COLUMN collection TEXT;

PRAGMA user_version = 11;
