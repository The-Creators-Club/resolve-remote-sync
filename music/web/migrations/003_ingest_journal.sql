-- Make the ingest queue a JOURNAL: an identity that survives being copied.
--
-- 2026-08-17, COMMERCIAL_READINESS.md item 14. Draining the queue was a "pull,
-- drain, push": copy the NAS's music.db to the base rig, analyse the pending
-- rows there, copy the whole file back. There is no merge in a file copy, so
-- everything an editor queued while the operator held the copy was overwritten
-- on the push -- a lost-write window minutes to hours wide, documented in
-- web/DEPLOY.md as a hazard to work around rather than fixed. It is not
-- detectable afterwards either: the row, the queue count and the upload's place
-- in the UI all vanish together, and the only surviving copy is the
-- music.db.old.<ts> the installer keeps.
--
-- The fix does not push a file back at all (musicweb/drain.py): the base rig
-- exports the ANALYSED RESULTS of the rows it drained, and those are applied to
-- the live index in place, `INSERT ... ON CONFLICT`, touching only the rows it
-- names. Anything queued during the drain is simply not named and stays
-- pending. That needs a key that means the same thing in both copies of the
-- database, and `id` does not: it is a per-database rowid, and two hosts
-- inserting into their own copies both get the next integer. `rel_path` is
-- unique but is REUSED -- queue_add upserts on it, so a failed row dropped
-- again is the same rel_path describing a different upload.
--
-- Hence `uid`: minted once per accepted upload, minted AGAIN whenever a row is
-- reset to pending by that upsert (a second drop of a name is a second upload
-- and must not be closed by a bundle drained from the first). Random rather
-- than derived from the content, because two rows may legitimately hold the
-- same bytes at different paths, and a hash key would then close both.
--
-- NULL is allowed on purpose: rows that predate this migration are backfilled
-- below, but a row written by an older container against a migrated database
-- would have none, and a UNIQUE index tolerates many NULLs. apply_bundle skips
-- what it cannot identify rather than guessing.
ALTER TABLE ingest_queue ADD COLUMN uid TEXT;

-- randomblob(16) is SQLite's own CSPRNG; 128 bits is uuid4's collision budget
-- and this needs no more. Done in SQL rather than in Python so the migration
-- stays a file the runner can apply in one transaction.
UPDATE ingest_queue SET uid = lower(hex(randomblob(16))) WHERE uid IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_uid ON ingest_queue(uid);

PRAGMA user_version = 3;
