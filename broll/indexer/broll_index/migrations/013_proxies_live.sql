-- `proxies_live`: an ingest item whose proxies are in the archive and whose
-- ORIGINAL is still going up (wire-1, 2026-09-18b, CR-290B).
--
-- The companion stages a clip live as soon as its preview, poster and sprite
-- have landed and posts `/uploaded` a second time when the original finishes
-- (CR-288D). The first post wrote `live`, which is TERMINAL: an original whose
-- upload then failed left an item nothing could retry, a batch that called
-- itself `done`, and a `videos` row advertising an original the archive does
-- not hold. The new word is deliberately not terminal, and the clip stays
-- visible throughout - visibility is `videos.status`, never this column, which
-- is the whole point of the two stages.
--
-- The state column carries a CHECK constraint, and SQLite cannot alter one, so
-- the table is rebuilt: every column, index and foreign key of migration 011
-- exactly, with one more word in the CHECK. Nothing else about it changes, and
-- the rows are copied whole. Safe inside the migration runner's single
-- transaction because NOTHING references `ingest_items` (ingest_batches
-- carries `current_item_uid` as a plain TEXT column on purpose).

CREATE TABLE ingest_items_new (
    uid TEXT PRIMARY KEY,
    batch_uid TEXT NOT NULL REFERENCES ingest_batches(uid) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    orig_name TEXT NOT NULL,
    rel_dir TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER,
    hash TEXT,
    duration_s REAL, fps REAL, width INTEGER, height INTEGER, codec TEXT, shot_date TEXT,
    source TEXT NOT NULL CHECK (source IN ('upload','path')),
    video_id INTEGER REFERENCES videos(id) ON DELETE SET NULL,
    duplicate_of INTEGER REFERENCES videos(id) ON DELETE SET NULL,
    archive_dir TEXT,
    archive_stem TEXT,
    state TEXT NOT NULL DEFAULT 'pending'
      CHECK (state IN ('pending','duplicate','proxying','framing','describing','indexed','uploading','proxies_live','live','failed','cancelled','skipped')),
    stage_percent INTEGER,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    original_uploaded INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);

INSERT INTO ingest_items_new
    (uid, batch_uid, ord, orig_name, rel_dir, size_bytes, hash, duration_s, fps,
     width, height, codec, shot_date, source, video_id, duplicate_of, archive_dir,
     archive_stem, state, stage_percent, error, attempts, original_uploaded, updated_at)
SELECT
     uid, batch_uid, ord, orig_name, rel_dir, size_bytes, hash, duration_s, fps,
     width, height, codec, shot_date, source, video_id, duplicate_of, archive_dir,
     archive_stem, state, stage_percent, error, attempts, original_uploaded, updated_at
FROM ingest_items;

DROP TABLE ingest_items;
ALTER TABLE ingest_items_new RENAME TO ingest_items;

CREATE INDEX idx_ingest_items_batch ON ingest_items(batch_uid, ord);
CREATE INDEX idx_ingest_items_video ON ingest_items(video_id);

PRAGMA user_version = 13;
