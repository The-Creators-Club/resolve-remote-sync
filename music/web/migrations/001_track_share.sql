-- (share, rel_path): the b-roll path model, applied to the music library.
--
-- b-roll's load-bearing rule is that the database never stores absolute paths.
-- Every asset is a logical share name plus a forward-slash relative path, and
-- the pair is translated to a real path at the edge -- which is what lets the
-- library move, or be mounted at a different letter per host:
--
--     base rig (indexer)   W:\Creators_Club\Assets\Music
--     editor machines      P:\Assets\Music
--
-- rel_path was already relative (to a single implied MUSIC_ROOT), so this only
-- makes the other half explicit. There is exactly one share today and the
-- constant is 'music'; the column exists so the database stops *implying* a
-- single root, not because a second share is planned.
--
-- Additive, and the only reason this needs a migration file at all: an
-- ALTER TABLE is not expressible in schema.sql's re-runnable
-- CREATE ... IF NOT EXISTS form. NOT NULL with a non-null DEFAULT is legal in
-- SQLite's ADD COLUMN, so the 376 existing rows are backfilled in place by the
-- ALTER itself -- no table rebuild, no data movement, no lost rowids.
ALTER TABLE tracks ADD COLUMN share TEXT NOT NULL DEFAULT 'music';

-- Belt and braces for a database that grew the column some other way (a hand
-- ALTER without the default, an interrupted run): every track lives in the one
-- share, and a blank one would resolve against nothing.
UPDATE tracks SET share = 'music' WHERE share IS NULL OR share = '';

PRAGMA user_version = 1;
