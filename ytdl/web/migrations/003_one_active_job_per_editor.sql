-- v3: one non-terminal job per editor, enforced by the database.
--
-- YTDL-25 (2026-08-11): create_job's check was read-then-insert, so a
-- double-clicked SEARCH created two active jobs; active_job then returned the
-- ORPHANED first one and 409'd every later search with a job_id the SPA was
-- not tracking. The partial unique index makes the second insert an
-- IntegrityError, which routes_api turns into the same 409 the read check
-- gives -- the check stays, this is what closes the window between it and the
-- INSERT.
--
-- The UPDATE first: a live database may already hold the pairs this index
-- forbids, and a CREATE UNIQUE INDEX that raises would take every /ytdl
-- request down with it. The newest of an editor's active jobs is the one their
-- page is attached to, so the older ones -- which are precisely the orphans
-- that were blocking them -- are retired, with the reason recorded in `error`.
UPDATE jobs
   SET phase = 'cancelled',
       error = 'cancelled while enforcing one active job per editor (YTDL-25): this job was orphaned by a duplicate submission',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
 WHERE phase NOT IN ('done', 'failed', 'cancelled')
   AND id NOT IN (SELECT MAX(id) FROM jobs
                   WHERE phase NOT IN ('done', 'failed', 'cancelled')
                   GROUP BY created_by);

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_active
    ON jobs(created_by)
 WHERE phase NOT IN ('done', 'failed', 'cancelled');
