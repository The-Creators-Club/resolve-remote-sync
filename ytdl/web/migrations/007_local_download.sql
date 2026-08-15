-- v7: requester-first downloads -- the claim/lease columns on a job, and the
-- record of WHICH machine actually fetched each clip
-- (docs/YTDL_LOCAL_DOWNLOAD.md §4).
--
-- Every column is additive and idle by default. A fleet with no 0.8.0
-- companion in it never writes any of them: every job stays
-- download_mode='server', which is byte-for-byte the behaviour that shipped
-- before this, and that is the whole rollback story for phase 1 (plan §10) --
-- there is no schema rollback because there is nothing to roll back.
--
-- WHY THE LEASE IS TWO COLUMNS AND NOT A FLAG: the holder can vanish without
-- telling anyone (laptop closed, tray upgraded mid-job, companion killed --
-- plan §11), so "who has it" has to expire on its own. `lease_expires_at` is
-- an ISO-8601 UTC string written by ytdlweb.db.now(), and it is COMPARED as a
-- string: every writer is that one function, so the offset is always '+00:00'
-- and lexicographic order is chronological order.
ALTER TABLE jobs ADD COLUMN download_mode TEXT NOT NULL DEFAULT 'server';
ALTER TABLE jobs ADD COLUMN claimed_by TEXT;
ALTER TABLE jobs ADD COLUMN lease_expires_at TEXT;

-- 'server' pins a job to the NAS worker: the editor pressed "download on the
-- server instead" (plan §9, hotel wifi / tethered), or the server RECLAIMED an
-- expired lease. Both mean the same thing to a claim -- 410, not claimable --
-- which is how "reclaim is one-way per job" (plan §3) is enforced with no
-- extra state and no ping-pong.
ALTER TABLE jobs ADD COLUMN mode_lock TEXT;

-- 'server' or the editor's dashboard username: whose IP fetched this clip.
-- The plan calls the table `clip_downloads`; there is no such table in this
-- app -- the per-clip dl_state rows are job_videos, and the column belongs
-- beside the state it describes.
ALTER TABLE job_videos ADD COLUMN download_host TEXT;
