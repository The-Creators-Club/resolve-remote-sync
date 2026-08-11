-- An app-level counter the search caches can trust, because the data cannot
-- tell them the truth on its own.
--
-- app/semantic.py's embedding matrix and app/fuzzy.py's typo-correction
-- vocabulary are process-wide caches keyed on cheap facts about the rows they
-- were built from: (row count, MAX(rowid)). That catches every re-index shape
-- seen in the field bar one (BROLL-17's residual, KNOWN_BUGS R2): a replacement
-- whose rows were already the table's highest ids AND arrives in exactly the
-- same number gets the SAME rowids back from SQLite, so both components of the
-- key are unchanged while every vector behind them is different. The caches
-- then serve the previous clip's vectors, and the clip's real content is
-- unreachable until some unrelated write happens to move the count.
--
-- `PRAGMA data_version` is the SQLite-native answer and is unusable here: it
-- only reports writes made by OTHER connections, and the web app opens a fresh
-- connection per request (app/db.py get_db), so it reads 1 forever.
--
-- So the write paths say so themselves: every path that inserts, replaces or
-- deletes `embeddings` rows, or the segments/transcript_segments rows the
-- vocabulary is built from, bumps this counter IN THE SAME TRANSACTION as the
-- write. Both twins do it -- web/app/routes_ingest.py and the indexer's
-- broll_index/storage/sqlite_backend.py -- and a test on each side pins it,
-- because the counter is only as good as the write paths' discipline. The
-- count/high-water components stay in the cache keys as belt and braces for a
-- write path that forgets.
--
-- `meta` is a generic key/value table on purpose: `search_generation` is the
-- first key, not the only one it may ever hold.
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO meta (key, value) VALUES ('search_generation', '0');

PRAGMA user_version = 10;
