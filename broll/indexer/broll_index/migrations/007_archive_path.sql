-- Where a clip lives in the shared archive tree (P:\Assets\B-roll Archive),
-- relative to its root: e.g. "Downloads/energy/nuclear/Proxy/<name>.mp4".
--
-- The web app previously served every preview from a flat DATA_ROOT/proxies/
-- {video_id}.mp4. The archive is the same media laid out browsably, so without
-- this the two would have to hold 54.7 GB each. Recording the path lets one
-- tree serve both the search UI and the editors' timelines.
--
-- Also the canonical reference an inserted clip gets in Resolve, which is why
-- it is stored rather than recomputed: the on-disk name is the result of
-- filename sanitising, length capping and collision de-duplication, and a
-- second implementation of those rules would drift.
ALTER TABLE videos ADD COLUMN archive_path TEXT;

PRAGMA user_version = 7;
