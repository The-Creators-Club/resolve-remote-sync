-- v15: job_videos.flat_duration + job_videos.meta_source -- WHAT THE SEARCH
-- PAGE SAID, kept for when YouTube refuses the per-video fetch (CR-360,
-- 2026-10-05).
--
-- Measured live: with the studio's IP bot-checked, the flat search succeeds in
-- two seconds and every per-video metadata call is answered "Sign in to
-- confirm you're not a bot". The metadata phase failed the whole job at the
-- first such row, so an editor whose own companion would have downloaded every
-- clip fine never even reached the review grid (jobs 117, 119, 120). The flat
-- search entries already carry a title, channel, view count, thumbnails and a
-- duration; this is where the duration waits, and `meta_source` is what marks
-- a row whose details came from there instead of from the fetch.
--
-- Two columns in one table, so db._MIGRATIONS' predicate asks about both.
-- ADDITIVE AND INERT: NULL in both is every row written before this, which is
-- exactly "enriched (or not yet)", and nothing reads flat_duration until the
-- metadata phase is bot-checked.
ALTER TABLE job_videos ADD COLUMN flat_duration REAL;
ALTER TABLE job_videos ADD COLUMN meta_source TEXT;
