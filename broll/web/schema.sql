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
    updated_at  TEXT
);

PRAGMA user_version = 9;
