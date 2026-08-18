-- B-Roll Platform schema v1. Applied via PRAGMA user_version migration (v0 -> v1).
PRAGMA journal_mode = WAL;

CREATE TABLE videos (
    id          INTEGER PRIMARY KEY,
    share       TEXT NOT NULL,
    rel_path    TEXT NOT NULL,              -- forward slashes, relative to share root
    hash        TEXT,                       -- xxh64(first 8MiB + last 8MiB + size)
    size_bytes  INTEGER,
    duration_s  REAL,
    fps         REAL,
    width       INTEGER,
    height      INTEGER,
    codec       TEXT,
    shot_date   TEXT,                       -- ISO date from metadata, nullable
    category    TEXT,                       -- approved taxonomy slug, NULL until assigned
    category_hint TEXT,                     -- raw model suggestion pre-approval
    in_inbox    INTEGER NOT NULL DEFAULT 0, -- 1 = under the designated inbox root
    status      TEXT NOT NULL DEFAULT 'discovered',
                -- discovered | probed | proxied | indexed | sorted | error
    error       TEXT,
    indexed_at  TEXT,                       -- ISO timestamp when claude pass completed
    model       TEXT,                       -- model used for the index pass
    transcribed_at TEXT,                    -- ISO timestamp of the local whisper pass
    transcript_lang TEXT,                   -- detected/forced language of the audio
    full_hash   TEXT,                       -- whole-file xxh64, computed only to confirm
                                             -- a partial-hash `hash` match (see migrations/005_duplicates.sql)
    duplicate_of INTEGER REFERENCES videos(id), -- points at the canonical copy; NULL if this
                                             -- row IS canonical (or has no known duplicate)
    archive_path TEXT,                      -- path in the shared archive tree,
                                             -- relative to its root (see migrations/007)
    original_path TEXT,                     -- absolute path of the TRUE original,
                                             -- resolved per share (see migrations/008)
    original_size_bytes INTEGER,
    original_verified_at TEXT,              -- when that path was last seen to exist
    -- The hover-scrub sheet's REAL geometry, as build_sprite measured it off the
    -- sheet it had just written (see migrations/009). NULL = sprited before these
    -- columns existed, and the browser falls back to its old source-derived
    -- heuristics for that row. Recorded, never re-derived: the sheet is tiled
    -- from the PROXY through an even-rounding scale, and the interval depends on
    -- whether SPRITE_MAX_CELLS existed when it was built.
    sprite_cell_w INTEGER,
    sprite_cell_h INTEGER,
    sprite_cols INTEGER,
    sprite_cells INTEGER,
    sprite_interval_s REAL,
    UNIQUE (share, rel_path)
);

-- See migrations/005_duplicates.sql for the two-hash reasoning: `hash` is a fast partial
-- fingerprint that only yields CANDIDATE duplicates; `full_hash` (whole-file) confirms
-- them before anything is ever marked `duplicate_of`.
CREATE INDEX idx_videos_hash         ON videos(hash);
CREATE INDEX idx_videos_full_hash    ON videos(full_hash);
CREATE INDEX idx_videos_duplicate_of ON videos(duplicate_of);

CREATE TABLE segments (
    id          INTEGER PRIMARY KEY,
    video_id    INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    t_start     REAL NOT NULL,
    t_end       REAL NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    objects     TEXT NOT NULL DEFAULT '',   -- ", "-joined object list incl. synonyms
    setting     TEXT NOT NULL DEFAULT '',
    motion      TEXT NOT NULL DEFAULT '',
    onscreen_text    TEXT NOT NULL DEFAULT '',  -- verbatim, original script
    onscreen_text_en TEXT NOT NULL DEFAULT '',  -- English rendering of the above
    -- Raw text + both Chinese script variants, word-segmented into space-separated
    -- tokens. Segmentation is what makes a 2-character term like 堵車 or 檢調
    -- matchable: trigram cannot help (a query needs 3 chars to form a trigram) and
    -- unbroken prose gives unicode61 no token boundary. Script conversion makes a
    -- Traditional query find Simplified source text and vice versa.
    search_norm TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_segments_video ON segments(video_id);

-- Two tokenizers on purpose; see docs/indexing-findings.md.
-- unicode61 makes an unbroken CJK run a single token (Chinese has no spaces), so
-- Chinese is only findable by typing the whole run. trigram gives substring match
-- but needs >=3 chars and drops English stemming. Neither alone is enough.
CREATE VIRTUAL TABLE segments_fts USING fts5(
    description, objects, setting, onscreen_text_en, search_norm,
    content='segments', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE VIRTUAL TABLE segments_cjk_fts USING fts5(
    onscreen_text, objects, search_norm,
    content='segments', content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, description, objects, setting, onscreen_text_en, search_norm)
    VALUES (new.id, new.description, new.objects, new.setting, new.onscreen_text_en, new.search_norm);
    INSERT INTO segments_cjk_fts(rowid, onscreen_text, objects, search_norm)
    VALUES (new.id, new.onscreen_text, new.objects, new.search_norm);
END;
CREATE TRIGGER segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, description, objects, setting, onscreen_text_en, search_norm)
    VALUES ('delete', old.id, old.description, old.objects, old.setting, old.onscreen_text_en, old.search_norm);
    INSERT INTO segments_cjk_fts(segments_cjk_fts, rowid, onscreen_text, objects, search_norm)
    VALUES ('delete', old.id, old.onscreen_text, old.objects, old.search_norm);
END;
CREATE TRIGGER segments_au AFTER UPDATE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, description, objects, setting, onscreen_text_en, search_norm)
    VALUES ('delete', old.id, old.description, old.objects, old.setting, old.onscreen_text_en, old.search_norm);
    INSERT INTO segments_cjk_fts(segments_cjk_fts, rowid, onscreen_text, objects, search_norm)
    VALUES ('delete', old.id, old.onscreen_text, old.objects, old.search_norm);
    INSERT INTO segments_fts(rowid, description, objects, setting, onscreen_text_en, search_norm)
    VALUES (new.id, new.description, new.objects, new.setting, new.onscreen_text_en, new.search_norm);
    INSERT INTO segments_cjk_fts(rowid, onscreen_text, objects, search_norm)
    VALUES (new.id, new.onscreen_text, new.objects, new.search_norm);
END;

-- Speech, transcribed locally (faster-whisper). Free on owned hardware and often
-- the richest index a clip has: names, operation names, dates and places are
-- spoken, not shown. See docs/indexing-findings.md.
CREATE TABLE transcript_segments (
    id          INTEGER PRIMARY KEY,
    video_id    INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    t_start     REAL NOT NULL,
    t_end       REAL NOT NULL,
    text        TEXT NOT NULL DEFAULT '',
    search_norm TEXT NOT NULL DEFAULT ''   -- see segments.search_norm
);
CREATE INDEX idx_transcript_video ON transcript_segments(video_id);

-- Same dual-tokenizer split as segments, for the same measured reason.
CREATE VIRTUAL TABLE transcript_fts USING fts5(
    text, search_norm,
    content='transcript_segments', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE VIRTUAL TABLE transcript_cjk_fts USING fts5(
    text, search_norm,
    content='transcript_segments', content_rowid='id',
    tokenize='trigram'
);
CREATE TRIGGER transcript_ai AFTER INSERT ON transcript_segments BEGIN
    INSERT INTO transcript_fts(rowid, text, search_norm) VALUES (new.id, new.text, new.search_norm);
    INSERT INTO transcript_cjk_fts(rowid, text, search_norm) VALUES (new.id, new.text, new.search_norm);
END;
CREATE TRIGGER transcript_ad AFTER DELETE ON transcript_segments BEGIN
    INSERT INTO transcript_fts(transcript_fts, rowid, text, search_norm)
    VALUES ('delete', old.id, old.text, old.search_norm);
    INSERT INTO transcript_cjk_fts(transcript_cjk_fts, rowid, text, search_norm)
    VALUES ('delete', old.id, old.text, old.search_norm);
END;
CREATE TRIGGER transcript_au AFTER UPDATE ON transcript_segments BEGIN
    INSERT INTO transcript_fts(transcript_fts, rowid, text, search_norm)
    VALUES ('delete', old.id, old.text, old.search_norm);
    INSERT INTO transcript_cjk_fts(transcript_cjk_fts, rowid, text, search_norm)
    VALUES ('delete', old.id, old.text, old.search_norm);
    INSERT INTO transcript_fts(rowid, text, search_norm) VALUES (new.id, new.text, new.search_norm);
    INSERT INTO transcript_cjk_fts(rowid, text, search_norm) VALUES (new.id, new.text, new.search_norm);
END;

-- Semantic vectors: float32 little-endian, L2-normalized, brute-force scanned in
-- numpy (milliseconds at archive scale, and no sqlite extension to deploy).
-- `model` is per-row so a model change is detected and re-embedded rather than
-- silently comparing incompatible vector spaces.
CREATE TABLE embeddings (
    source     TEXT NOT NULL,        -- 'segment' | 'transcript'
    source_id  INTEGER NOT NULL,
    video_id   INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    model      TEXT NOT NULL,
    dim        INTEGER NOT NULL,
    vec        BLOB NOT NULL,
    PRIMARY KEY (source, source_id)
);
CREATE INDEX idx_embeddings_video ON embeddings(video_id);
CREATE INDEX idx_embeddings_model ON embeddings(model);

CREATE TABLE themes (
    video_id    INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    text        TEXT NOT NULL
);
CREATE INDEX idx_themes_video ON themes(video_id);

CREATE TABLE quality_flags (
    video_id    INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    flag        TEXT NOT NULL
                CHECK (flag IN ('shaky','soft_focus','overexposed','underexposed','noisy','rolling_shutter'))
);
CREATE INDEX idx_flags_video ON quality_flags(video_id);

CREATE TABLE categories (
    slug        TEXT PRIMARY KEY,           -- e.g. 'military/naval'
    label       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

-- Where each share's footage actually lives, pushed from the indexer (the web
-- app does not read config.queue.yaml -- see app/config.py). Needed for the
-- final-export relink: a remote editor cuts against a proxy, and at conform the
-- true original must be found, most likely on a backup external drive.
CREATE TABLE share_roots (
    share       TEXT PRIMARY KEY,
    root        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'originals'
                CHECK (source IN ('originals', 'proxies')),
    description TEXT NOT NULL DEFAULT '',
    indexed     INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT,
    -- Which browse root this share belongs to, said outright rather than
    -- derived from `source` (see migrations/011). NULL = today's rule, which
    -- is every share the indexer has ever pushed; only dashboard ingest
    -- writes a value, because an ingested shoot archives ORIGINALS and would
    -- otherwise file the customer's own camera footage under Downloads.
    collection  TEXT
);

-- Generic key/value scratch; `search_generation` is its first key (see
-- migrations/010). Every write path that touches `embeddings`, or the
-- segments/transcript_segments rows the typo-correction vocabulary is built
-- from, increments it in the same transaction as the write. app/semantic.py
-- and app/fuzzy.py fold it into their cache keys: it is the only thing that
-- can see a re-index landing the same NUMBER of rows on the same rowids
-- (BROLL-17's residual, KNOWN_BUGS R2) -- the row count and high-water mark
-- that key alongside it are both blind to that shape.
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO meta (key, value) VALUES ('search_generation', '0');

-- Drag-and-drop b-roll ingest (docs/BROLL_INGEST_PLAN.md §2, 2026-08-18). The
-- work orders the dashboard hands a companion, and the per-clip ledger it
-- reports back against. See migrations/011_ingest_batches.sql for why each
-- column exists; this file is the fresh-install twin of it and the two are
-- compared column-for-column by web/tests/test_migration.py.
CREATE TABLE ingest_batches (
    uid TEXT PRIMARY KEY,                    -- lower(hex(randomblob(16))), server-minted
    editor TEXT NOT NULL,                    -- the VERIFIED dashboard identity
    machine TEXT,                            -- which of that editor's machines holds the lease
    companion_version TEXT,
    share TEXT NOT NULL,                     -- the shoot folder, through archive_names.safe_name
    collection TEXT NOT NULL DEFAULT 'owned',
    settings_json TEXT NOT NULL,             -- {tier, run_mode, upload_originals, keep_subfolders, transcribe}
    state TEXT NOT NULL DEFAULT 'queued'
      CHECK (state IN ('queued','claimed','running','done','done_with_errors','cancelled','failed')),
    n_items INTEGER NOT NULL DEFAULT 0,
    n_done INTEGER NOT NULL DEFAULT 0,
    n_failed INTEGER NOT NULL DEFAULT 0,
    n_live INTEGER NOT NULL DEFAULT 0,
    n_duplicate INTEGER NOT NULL DEFAULT 0,
    current_item_uid TEXT,
    lease_expires_at TEXT,                   -- a claim dies of silence; see the migration
    last_heartbeat_at TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,  -- a REQUEST; the companion releases
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
    rel_dir TEXT NOT NULL DEFAULT '',        -- forward slashes; '' for a flat drop
    size_bytes INTEGER,
    hash TEXT,                               -- the SAME digest videos.hash carries
    duration_s REAL, fps REAL, width INTEGER, height INTEGER, codec TEXT, shot_date TEXT,
    source TEXT NOT NULL CHECK (source IN ('upload','path')),
    video_id INTEGER REFERENCES videos(id) ON DELETE SET NULL,   -- minted AT CLAIM
    duplicate_of INTEGER REFERENCES videos(id) ON DELETE SET NULL,
    archive_dir TEXT,                        -- archive_path = archive_dir/Proxy/archive_stem.mp4
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

PRAGMA user_version = 11;
