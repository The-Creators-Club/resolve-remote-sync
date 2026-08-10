-- v1 -> v2: on-screen text capture + dual-tokenizer search.
--
-- Adds segments.onscreen_text / onscreen_text_en, rebuilds segments_fts to
-- include the English gloss, and adds a trigram-tokenized segments_cjk_fts so
-- Chinese is findable by substring. See docs/indexing-findings.md for the
-- measurements behind the two-tokenizer design.
--
-- Existing rows get empty on-screen text; re-run the `claude` stage to populate
-- them (proxies and contact sheets are unaffected, so that is cheap).
--
-- Bundled copy: this is the same file as migrations/002_onscreen_text.sql at the
-- repo root, kept in sync here so `broll-index migrate` still works when the
-- package is installed without the rest of the repo checked out. See
-- broll_index/migrate.py.

ALTER TABLE segments ADD COLUMN onscreen_text    TEXT NOT NULL DEFAULT '';
ALTER TABLE segments ADD COLUMN onscreen_text_en TEXT NOT NULL DEFAULT '';

DROP TRIGGER IF EXISTS segments_ai;
DROP TRIGGER IF EXISTS segments_ad;
DROP TRIGGER IF EXISTS segments_au;
DROP TABLE IF EXISTS segments_fts;
DROP TABLE IF EXISTS segments_cjk_fts;

CREATE VIRTUAL TABLE segments_fts USING fts5(
    description, objects, setting, onscreen_text_en,
    content='segments', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE VIRTUAL TABLE segments_cjk_fts USING fts5(
    onscreen_text, objects,
    content='segments', content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, description, objects, setting, onscreen_text_en)
    VALUES (new.id, new.description, new.objects, new.setting, new.onscreen_text_en);
    INSERT INTO segments_cjk_fts(rowid, onscreen_text, objects)
    VALUES (new.id, new.onscreen_text, new.objects);
END;
CREATE TRIGGER segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, description, objects, setting, onscreen_text_en)
    VALUES ('delete', old.id, old.description, old.objects, old.setting, old.onscreen_text_en);
    INSERT INTO segments_cjk_fts(segments_cjk_fts, rowid, onscreen_text, objects)
    VALUES ('delete', old.id, old.onscreen_text, old.objects);
END;
CREATE TRIGGER segments_au AFTER UPDATE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, description, objects, setting, onscreen_text_en)
    VALUES ('delete', old.id, old.description, old.objects, old.setting, old.onscreen_text_en);
    INSERT INTO segments_cjk_fts(segments_cjk_fts, rowid, onscreen_text, objects)
    VALUES ('delete', old.id, old.onscreen_text, old.objects);
    INSERT INTO segments_fts(rowid, description, objects, setting, onscreen_text_en)
    VALUES (new.id, new.description, new.objects, new.setting, new.onscreen_text_en);
    INSERT INTO segments_cjk_fts(rowid, onscreen_text, objects)
    VALUES (new.id, new.onscreen_text, new.objects);
END;

INSERT INTO segments_fts(segments_fts) VALUES ('rebuild');
INSERT INTO segments_cjk_fts(segments_cjk_fts) VALUES ('rebuild');

PRAGMA user_version = 2;
