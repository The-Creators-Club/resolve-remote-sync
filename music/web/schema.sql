-- Music library schema v1. Every statement is CREATE ... IF NOT EXISTS, so this
-- file is applied to every database the app opens and additive changes (a new
-- table, a new index) need no migration -- that is how `peaks` and `debias`
-- landed on a live index. Anything NOT expressible that way (an ALTER) needs a
-- file in migrations/ and a bump of musicweb.db.CURRENT_SCHEMA_VERSION.
--
-- This file deliberately does NOT set `PRAGMA user_version`. Because it is
-- re-run against EXISTING databases, a stamp here marks an unmigrated database
-- as current and the migration it needs is then skipped forever. That is not
-- hypothetical: on 2026-08-10 a stamp in this file took the live 376-track
-- index from user_version=0 to 1 without adding tracks.share, and the next
-- startup happily agreed it was up to date. musicweb.db.ensure_schema() owns
-- the version.
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS tracks (
    id          INTEGER PRIMARY KEY,
    share       TEXT NOT NULL DEFAULT 'music',  -- logical share; root is per host
    rel_path    TEXT UNIQUE NOT NULL,   -- relative to the share root, forward slashes
    filename    TEXT NOT NULL,
    ext         TEXT,
    bytes       INTEGER,
    duration    REAL,
    samplerate  INTEGER,
    channels    INTEGER,
    codec       TEXT,
    bpm         REAL,
    music_key   TEXT,
    key_conf    REAL,
    lufs        REAL,                   -- integrated loudness
    peak_db     REAL,
    embedding   BLOB,                   -- float32, L2-normalised track vector
    dim         INTEGER,
    file_hash   TEXT,                   -- size+mtime fingerprint; drives re-analysis
    model       TEXT,
    analyzed_at TEXT
);

CREATE TABLE IF NOT EXISTS windows (
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    t0          REAL,
    t1          REAL,
    embedding   BLOB,
    PRIMARY KEY (track_id, idx)
);

CREATE TABLE IF NOT EXISTS tags (
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    category    TEXT NOT NULL,
    label       TEXT NOT NULL,
    score       REAL,                   -- softmax within category
    pct         REAL,                   -- percentile rank within library
    rank        INTEGER,                -- 1 = strongest label for this category
    PRIMARY KEY (track_id, category, label)
);

CREATE TABLE IF NOT EXISTS axes (
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    axis        TEXT NOT NULL,
    raw         REAL,
    pct         REAL,
    PRIMARY KEY (track_id, axis)
);

-- Waveform overview for the inline player: N uint8 peak values, 0-255.
-- A separate table rather than a tracks column so it can be added to an
-- existing database by schema.sql alone (CREATE TABLE IF NOT EXISTS).
CREATE TABLE IF NOT EXISTS peaks (
    track_id    INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    n           INTEGER,
    data        BLOB
);

-- Source-bias axes projected out of every embedding before similarity/search.
-- Recomputed on every retag, since they depend on the library's composition.
CREATE TABLE IF NOT EXISTS debias (
    idx         INTEGER PRIMARY KEY,
    vec         BLOB
);

-- Drag-and-drop uploads that have landed in the share but have not been
-- analysed yet (port step 7). The NAS container has no GPU and no CLAP audio
-- tower, so /api/ingest there can only validate, de-duplicate, transcode and
-- park the file; a base-rig `index_music.py --queue` run drains this table and
-- fills in the embeddings/tags/waveform.
--
-- One row per accepted upload, keyed on where the file was actually put, which
-- is also the key the indexer needs to find it again: (share, rel_path), never
-- an absolute path -- the row is written on the NAS and read on the base rig.
CREATE TABLE IF NOT EXISTS ingest_queue (
    id           INTEGER PRIMARY KEY,
    -- Identity that survives the database being copied to another host, so a
    -- drain can name exactly the rows it analysed (migrations/003, and
    -- musicweb/drain.py for what it is for). `id` cannot: it is a per-database
    -- rowid. Re-minted whenever queue_add resets a row to pending.
    uid          TEXT,
    share        TEXT NOT NULL DEFAULT 'music',
    rel_path     TEXT UNIQUE NOT NULL,   -- where it landed, under the share root
    orig_name    TEXT NOT NULL,          -- what the browser called it
    bytes        INTEGER,
    duration     REAL,                   -- from ffprobe, for the re-encode check
    content_hash TEXT,                   -- blake2b of the landed bytes
    transcoded   INTEGER NOT NULL DEFAULT 0,
    -- pending -> done | failed. A failed row is NEVER picked up again on its
    -- own: an upload that cannot be analysed would otherwise be retried by
    -- every indexer run forever, and the failure would never be looked at.
    state        TEXT NOT NULL DEFAULT 'pending'
                 CHECK (state IN ('pending', 'done', 'failed')),
    error        TEXT,                   -- why, for the failed ones
    attempts     INTEGER NOT NULL DEFAULT 0,
    track_id     INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    queued_at    TEXT NOT NULL,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT
);

CREATE INDEX IF NOT EXISTS idx_tags_label ON tags(category, label, pct DESC);
CREATE INDEX IF NOT EXISTS idx_tags_track ON tags(track_id, rank);
CREATE INDEX IF NOT EXISTS idx_axes_axis  ON axes(axis, pct);
CREATE INDEX IF NOT EXISTS idx_tracks_bpm ON tracks(bpm);
CREATE INDEX IF NOT EXISTS idx_queue_state ON ingest_queue(state, id);
-- the content-hash duplicate check reads this on every upload
CREATE INDEX IF NOT EXISTS idx_queue_hash  ON ingest_queue(content_hash);
-- apply_bundle looks every drained row up by uid; UNIQUE also stops two rows
-- claiming one identity, which would close the wrong upload. Many NULLs are
-- allowed by a SQLite unique index, which is what rows written by an older
-- container need.
CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_uid ON ingest_queue(uid);
-- and it only hashes library files whose byte count already matches
CREATE INDEX IF NOT EXISTS idx_tracks_bytes ON tracks(bytes);

-- Dashboard music ingest: batches and their per-track items
-- (migrations/004_ingest_batches.sql, 2026-08-18, docs/MUSIC_INGEST_PLAN.md).
-- The definitions live in BOTH files for the reason at the top of this one: a
-- brand-new database gets schema.sql in full and never runs a migration, while
-- an existing one is migrated and then re-run through here. Migration 004's
-- header carries the reasoning -- what each column is for and where it differs
-- from b-roll's 011 -- and this copy stays a copy of it.
CREATE TABLE IF NOT EXISTS ingest_batches (
    uid               TEXT PRIMARY KEY,
    editor            TEXT NOT NULL,      -- the VERIFIED dashboard identity
    machine           TEXT,               -- which of their machines holds the lease
    companion_version TEXT,
    share             TEXT NOT NULL DEFAULT 'music',
    settings_json     TEXT NOT NULL,      -- {run_mode}
    state             TEXT NOT NULL DEFAULT 'queued'
                      CHECK (state IN ('queued','claimed','running','done',
                                       'done_with_errors','cancelled','failed')),
    n_items           INTEGER NOT NULL DEFAULT 0,
    n_done            INTEGER NOT NULL DEFAULT 0,
    n_failed          INTEGER NOT NULL DEFAULT 0,
    n_live            INTEGER NOT NULL DEFAULT 0,
    n_duplicate       INTEGER NOT NULL DEFAULT 0,
    current_item_uid  TEXT,
    lease_expires_at  TEXT,               -- a claim dies of silence
    last_heartbeat_at TEXT,
    cancel_requested  INTEGER NOT NULL DEFAULT 0,   -- a request, never a kill
    cancel_by         TEXT,
    upload_paused     INTEGER NOT NULL DEFAULT 0,
    error             TEXT,
    created_at        TEXT NOT NULL,
    claimed_at        TEXT,
    started_at        TEXT,
    finished_at       TEXT,
    updated_at        TEXT
);

CREATE TABLE IF NOT EXISTS ingest_items (
    uid          TEXT PRIMARY KEY,
    batch_uid    TEXT NOT NULL REFERENCES ingest_batches(uid) ON DELETE CASCADE,
    ord          INTEGER NOT NULL,
    orig_name    TEXT NOT NULL,
    size_bytes   INTEGER,
    content_hash TEXT,                    -- blake2b-16 of the whole file
    duration_s   REAL,
    samplerate   INTEGER,
    channels     INTEGER,
    codec        TEXT,
    transcoded   INTEGER NOT NULL DEFAULT 0,
    source       TEXT NOT NULL DEFAULT 'upload' CHECK (source IN ('upload','path')),
    -- NULL until `result`: `tracks` has no status column and every facet,
    -- percentile and debias axis reads every row, so a placeholder would skew
    -- the library rather than hide from it.
    track_id     INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    duplicate_of INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    dest_name    TEXT,                    -- the flat name allocated under the share root
    state        TEXT NOT NULL DEFAULT 'pending'
                 CHECK (state IN ('pending','duplicate','transcoding','embedding',
                                  'indexed','uploading','live','failed','cancelled',
                                  'skipped','queued_for_base_rig')),
    stage_percent INTEGER,
    error         TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingest_batches_editor ON ingest_batches(editor, created_at);
CREATE INDEX IF NOT EXISTS idx_ingest_batches_state  ON ingest_batches(state);
CREATE INDEX IF NOT EXISTS idx_ingest_items_batch    ON ingest_items(batch_uid, ord);
CREATE INDEX IF NOT EXISTS idx_ingest_items_track    ON ingest_items(track_id);
CREATE INDEX IF NOT EXISTS idx_ingest_items_hash     ON ingest_items(content_hash);
