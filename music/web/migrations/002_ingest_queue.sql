-- The drag-and-drop ingest queue (port step 7).
--
-- Ingest today decodes, CLAP-embeds and tags inside the request. That works on
-- the base rig and is impossible in the NAS container: no GPU, no torch, and
-- no indexer on the tree at all. So the web half is split in two -- accept,
-- validate, de-duplicate, transcode, land the file, record it -- and a base rig
-- `index_music.py --queue` run does the analysis afterwards. This table is the
-- handoff between the two, and it is written on one host and read on another,
-- which is why it carries (share, rel_path) and not a path.
--
-- Strictly speaking this is an ADDITIVE change and `CREATE TABLE IF NOT EXISTS`
-- in schema.sql would land it on an existing database unaided -- that is how
-- `peaks` and `debias` arrived. It gets a migration file anyway because the
-- table is a contract between two hosts running two different checkouts: a
-- numbered file plus a bump of musicweb.db.CURRENT_SCHEMA_VERSION is what makes
-- "this database predates the queue" a *diagnosable* state (`PRAGMA
-- user_version` says 1) instead of an invisible one, and what stops a base rig
-- still on the old code from quietly draining nothing.
--
-- Its already-applied predicate in musicweb.db._MIGRATIONS is the table's
-- existence. As with 001, the predicate -- not the recorded version -- decides
-- whether this runs, because this database predates `user_version` and one
-- stray application of schema.sql has already stamped the live index once
-- without its migration having run.
CREATE TABLE IF NOT EXISTS ingest_queue (
    id           INTEGER PRIMARY KEY,
    share        TEXT NOT NULL DEFAULT 'music',
    rel_path     TEXT UNIQUE NOT NULL,
    orig_name    TEXT NOT NULL,
    bytes        INTEGER,
    duration     REAL,
    content_hash TEXT,
    transcoded   INTEGER NOT NULL DEFAULT 0,
    state        TEXT NOT NULL DEFAULT 'pending'
                 CHECK (state IN ('pending', 'done', 'failed')),
    error        TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0,
    track_id     INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    queued_at    TEXT NOT NULL,
    updated_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_queue_state ON ingest_queue(state, id);
CREATE INDEX IF NOT EXISTS idx_queue_hash  ON ingest_queue(content_hash);

-- Not part of the queue, but the reason the queued path can afford its
-- content-hash duplicate check at all. The base rig hashes every file under the
-- share root on each upload (`music_index.ingest.library_hashes`); the
-- container cannot -- that is a 9.5 GB read over the mount, per drop. Identical
-- content implies an identical byte count, so the queued path hashes only the
-- library files whose `bytes` already match, and this index is what makes that
-- lookup one seek instead of a 376-row scan.
CREATE INDEX IF NOT EXISTS idx_tracks_bytes ON tracks(bytes);

PRAGMA user_version = 2;
