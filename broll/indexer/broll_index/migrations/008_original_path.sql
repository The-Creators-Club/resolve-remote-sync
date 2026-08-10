-- Where each clip's TRUE original lives, resolved to an absolute path.
--
-- Everything an editor touches is a proxy: the archive tree holds ~27 MB H.264
-- copies and the sources never leave the archive drives. At final export the
-- real file has to be found again, so its location has to be recorded while we
-- still know it.
--
-- It was derivable before, but only for half the library and only by a join
-- that differs per share:
--
--   source=originals  ->  share_roots.root + videos.rel_path
--   source=proxies    ->  rel_path is the PROXY; the camera original is a
--                         SEPARATE videos row (status='excluded') with no link
--                         back to it, findable only by guessing at filenames.
--
-- Resolving it once, here, means conform does a column read instead of
-- reimplementing that per-share logic — and it survives the source drives being
-- re-lettered or consolidated, because `original_verified_at` records when the
-- path was last known good rather than implying it still is.
ALTER TABLE videos ADD COLUMN original_path TEXT;
ALTER TABLE videos ADD COLUMN original_size_bytes INTEGER;
ALTER TABLE videos ADD COLUMN original_verified_at TEXT;

PRAGMA user_version = 8;
