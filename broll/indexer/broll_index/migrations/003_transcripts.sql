-- v2 -> v3: local speech transcription as a first-class index.
--
-- Transcription runs on owned hardware (faster-whisper, ~12.6x realtime on an
-- RTX 3080) and costs no model quota, so it runs over everything. It is often
-- the richest index a clip has — names, operation names, dates and locations are
-- spoken rather than shown. See docs/indexing-findings.md.
--
-- Dual tokenizer again, same measured reason as segments: unicode61 makes an
-- unbroken CJK run one token, trigram gives substring matching but needs >=3
-- chars and drops English stemming.
--
-- Bundled copy: this is the same file as migrations/003_transcripts.sql at the
-- repo root, kept in sync here so `broll-index migrate` still works when the
-- package is installed without the rest of the repo checked out. See
-- broll_index/migrate.py.

ALTER TABLE videos ADD COLUMN transcribed_at  TEXT;
ALTER TABLE videos ADD COLUMN transcript_lang TEXT;

CREATE TABLE transcript_segments (
    id          INTEGER PRIMARY KEY,
    video_id    INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    t_start     REAL NOT NULL,
    t_end       REAL NOT NULL,
    text        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_transcript_video ON transcript_segments(video_id);

CREATE VIRTUAL TABLE transcript_fts USING fts5(
    text, content='transcript_segments', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE VIRTUAL TABLE transcript_cjk_fts USING fts5(
    text, content='transcript_segments', content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER transcript_ai AFTER INSERT ON transcript_segments BEGIN
    INSERT INTO transcript_fts(rowid, text) VALUES (new.id, new.text);
    INSERT INTO transcript_cjk_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER transcript_ad AFTER DELETE ON transcript_segments BEGIN
    INSERT INTO transcript_fts(transcript_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO transcript_cjk_fts(transcript_cjk_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER transcript_au AFTER UPDATE ON transcript_segments BEGIN
    INSERT INTO transcript_fts(transcript_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO transcript_cjk_fts(transcript_cjk_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO transcript_fts(rowid, text) VALUES (new.id, new.text);
    INSERT INTO transcript_cjk_fts(rowid, text) VALUES (new.id, new.text);
END;

PRAGMA user_version = 3;
