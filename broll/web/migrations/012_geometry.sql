-- What a clip's own file IS, beyond its dimensions: frame count, start
-- timecode and bitrate (docs/BROLL_PROXY_TIERS_PLAN.md section 5, audit F3,
-- 2026-09-17).
--
-- `videos` carried duration_s, fps, width, height and codec and nothing else,
-- and three pieces of the proxy-tiers work need more:
--
--   * `bitrate` decides `original_is_edit_weight` on the detail route -- a top
--     slot at or below 1080 lines and about 12 Mbps in a cheap codec IS its
--     own editing proxy, and downloading it is correct. Without the column the
--     route would have to ffprobe a possibly multi-GB ProRes original on the
--     NAS, inside the dashboard container, on every detail view.
--   * `frames` and `start_tc` are what phase 3 writes into the interchange
--     file that creates an OFFLINE media-pool clip at the original's canonical
--     path. Resolve takes such a clip's metadata from the file, not from
--     media it cannot see, so a wrong or absent frame count is a clip of the
--     wrong length on every remote machine.
--
-- NULL means "probed before these columns existed", and it has to stay
-- distinguishable: `original_is_edit_weight` answers null for a row with no
-- bitrate rather than guessing, because a 0 would read as "tiny, definitely
-- edit-weight" and send a remote editor the whole camera master.
--
-- `start_tc` is the timecode AS THE FILE PRINTS IT, deliberately NOT
-- drop-frame normalised: the column describes the source, and the
-- normalisation is a property of a proxy written against it (audit F6 -- a
-- colon printed by a tmcd track is a real non-drop timecode).
ALTER TABLE videos ADD COLUMN frames INTEGER;
ALTER TABLE videos ADD COLUMN start_tc TEXT;
ALTER TABLE videos ADD COLUMN bitrate INTEGER;

PRAGMA user_version = 12;
