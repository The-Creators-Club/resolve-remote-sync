-- v3 -> v4: hybrid search — normalized CJK keyword matching + semantic vectors.
--
-- Two independent problems, two mechanisms, both measured (docs/indexing-findings.md):
--
-- 1. KEYWORD (exact, precise — names, IDs, specific terms).
--    `search_norm` holds raw text + both script variants, each word-segmented
--    (jieba) into space-separated tokens. Segmentation makes a 2-character term
--    like 堵車 a standalone token that unicode61 matches exactly, reaching below
--    trigram's 3-character floor; OpenCC conversion makes it script-agnostic.
--
-- 2. SEMANTIC (fuzzy, cross-lingual — meaning rather than characters).
--    Multilingual embeddings, so English "bulletproof vest" retrieves 防彈衣 and
--    Taiwanese 塞車 retrieves mainland 堵車 footage. Measured 9/9 top-1 on a
--    corpus sample with paraphrase-multilingual-MiniLM-L12-v2 (384-dim).
--
-- Neither replaces the other: keyword is exact but literal, semantic is flexible
-- but approximate. /api/search fuses both.
--
-- Bundled copy: this is the same file as migrations/004_hybrid_search.sql at the
-- repo root, kept in sync here so `broll-index migrate` still works when the
-- package is installed without the rest of the repo checked out. See
-- broll_index/migrate.py.

ALTER TABLE segments            ADD COLUMN search_norm TEXT NOT NULL DEFAULT '';
ALTER TABLE transcript_segments ADD COLUMN search_norm TEXT NOT NULL DEFAULT '';

-- Rebuild the keyword indexes to include the normalized blob.
DROP TRIGGER IF EXISTS segments_ai;
DROP TRIGGER IF EXISTS segments_ad;
DROP TRIGGER IF EXISTS segments_au;
DROP TABLE IF EXISTS segments_fts;
DROP TABLE IF EXISTS segments_cjk_fts;

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

DROP TRIGGER IF EXISTS transcript_ai;
DROP TRIGGER IF EXISTS transcript_ad;
DROP TRIGGER IF EXISTS transcript_au;
DROP TABLE IF EXISTS transcript_fts;
DROP TABLE IF EXISTS transcript_cjk_fts;

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

-- Semantic vectors. Stored as raw float32 little-endian BLOBs and brute-force
-- scanned in numpy: at archive scale (~1e5-1e6 segments) a full cosine pass is
-- milliseconds and needs no sqlite extension, which keeps deployment simple.
-- `model` is recorded per row so a model change can be detected and re-embedded
-- rather than silently comparing incompatible vector spaces.
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

INSERT INTO segments_fts(segments_fts) VALUES ('rebuild');
INSERT INTO segments_cjk_fts(segments_cjk_fts) VALUES ('rebuild');
INSERT INTO transcript_fts(transcript_fts) VALUES ('rebuild');
INSERT INTO transcript_cjk_fts(transcript_cjk_fts) VALUES ('rebuild');

PRAGMA user_version = 4;
