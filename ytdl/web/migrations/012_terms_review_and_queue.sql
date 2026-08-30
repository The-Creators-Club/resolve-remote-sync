-- v12: the term review and the queue -- the two things the owner asked for on
-- 2026-08-30: "youtube downloader should show a list of the search terms it is
-- going to use (for chinese ones, it should show a translation in brackets).
-- They begin all ticked and then you can untick individual ones or untick all,
-- or tick all. there should also be a queue so you can queue up multiple
-- searches."
--
-- job_terms.translation: what the review prints in brackets after a term. For
-- a query Claude wrote it is the english_gloss that call already produces (no
-- extra AI turn is spent on it); NULL is "there is nothing to print", which is
-- every English query and every pre-existing row. A separate column from
-- english_gloss because the two answer different questions -- english_gloss is
-- the manifest's readability guarantee for a Chinese query (REQ 5) and is
-- required for one, translation is "print this after the term if it is there"
-- and can be filled for the EDITOR'S OWN term, which never had a gloss.
--
-- job_terms.enabled: will this term be searched. DEFAULT 1 on purpose and with
-- no backfill: every term this database already holds WAS searched, so 1 is
-- not a guess about them, it is what happened. The review unticks; the search
-- phase reads nothing else.
--
-- jobs.queue_position: where a waiting job sits in its editor's queue, 1-based
-- and per editor. Every row this migration can see is either terminal or
-- already running, so 0 (the default) is honest for all of them -- the number
-- is only ever read while the phase is `queued`.
--
-- jobs.auto_terms: the headless bypass. 0 is the SPA's job (stop at
-- `terms_review` and wait for a person); 1 is a script that posted
-- {auto_terms: true} and wants the search to run unattended. Stored per job
-- rather than passed in memory for the reason shot_types and max_candidates
-- are: a job that sat queued over a container restart must resume as the
-- caller submitted it, and there is nobody watching a script's job to press
-- the button for it. Every pre-existing row is 0, which is only reachable now
-- that a stop exists -- so nothing that has already run is changed by it.
ALTER TABLE job_terms ADD COLUMN translation TEXT;
ALTER TABLE job_terms ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1;
ALTER TABLE jobs ADD COLUMN queue_position INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN auto_terms INTEGER NOT NULL DEFAULT 0;

-- ...and the one-active-job rule this feature replaces (YTDL-25,
-- migrations/003). It was a UNIQUE index over every editor's non-terminal
-- jobs, and it is exactly what made a second search a 409 rather than a queue
-- entry. Dropped rather than left in place: a queued job IS a non-terminal job,
-- so with the index still there the second INSERT would raise and the queue
-- could never hold more than one thing.
--
-- The double-clicked SEARCH the index was created for is no longer an error:
-- the loser of that race queues behind the winner, which is a job the editor
-- can see and cancel, instead of an orphan that blocked them.
DROP INDEX IF EXISTS idx_jobs_one_active;

-- What claim_next_job asks on every tick now: "does this job's editor already
-- have a busy one, and if not, which of their queued jobs is next". Ordinary,
-- not unique -- see the header of schema.sql's copy.
CREATE INDEX IF NOT EXISTS idx_jobs_queue
    ON jobs(created_by, phase, queue_position, id);
