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
-- and it only hashes library files whose byte count already matches
CREATE INDEX IF NOT EXISTS idx_tracks_bytes ON tracks(bytes);
