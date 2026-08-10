-- v4 -> v5: duplicate detection.
--
-- A scattered archive holds the same clip in several places. Two consequences:
--   1. Indexing a duplicate spends model calls describing footage already described.
--   2. Copying duplicates to the NAS wastes space and re-creates the mess.
--
-- WHY TWO HASHES: `hash` is a fast partial fingerprint (first + last 8 MiB + size)
-- — cheap enough to run over an entire archive, but it can in principle collide
-- for two distinct files that share head, tail and size. That is normally a
-- harmless false positive; here it is NOT, because a file wrongly marked
-- duplicate gets SKIPPED during the NAS copy and is effectively lost. So a
-- partial-hash match is only a CANDIDATE: `full_hash` (whole-file digest,
-- computed only for candidates) is what actually confirms it. Cached because
-- hashing a 40 GB master twice is not free.
--
-- `duplicate_of` points at the canonical video that was kept. Duplicates keep
-- their row (so the DB still knows every copy's location) but are excluded from
-- indexing, from search results, and from the copy manifest.

ALTER TABLE videos ADD COLUMN full_hash    TEXT;
ALTER TABLE videos ADD COLUMN duplicate_of INTEGER REFERENCES videos(id);

CREATE INDEX idx_videos_hash         ON videos(hash);
CREATE INDEX idx_videos_full_hash    ON videos(full_hash);
CREATE INDEX idx_videos_duplicate_of ON videos(duplicate_of);

PRAGMA user_version = 5;
