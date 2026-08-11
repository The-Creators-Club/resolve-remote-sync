-- What build_sprite ACTUALLY produced for this clip's hover-scrub sheet.
--
-- The browser used to re-derive the grid instead, from videos.width/height (the
-- SOURCE) plus a model of the generator's rules. Both halves were wrong in the
-- field (measured on the live archive, 2026-08-11):
--
--   * the sheet is tiled from the 540p PROXY through `scale=240:-2`, and each
--     scale step rounds to an even number, so the real cell height is routinely
--     a pixel taller than the source aspect ratio predicts (1920x1080 -> 135
--     computed, 136 actual). 6,783 of 7,117 sheets were off, which on a 24-row
--     sheet lands ~17% down the image and paints a splice of two rows (BROLL-1);
--   * SPRITE_MAX_CELLS was added to build_sprite AFTER part of the archive had
--     already been sprited at a flat 2 s interval, and nothing marked which was
--     which — so the browser applied the cap to 95 legacy uncapped sheets and
--     every clip over 8 minutes showed a frame from its first 8 minutes
--     (BROLL-2).
--
-- Neither is recoverable after the fact, so the generator records it here.
-- NULL means "sprited before these columns existed": the browser keeps the old
-- heuristics for those rows (no worse than before) and they become exact the
-- moment build_sprite is re-run for the clip.
ALTER TABLE videos ADD COLUMN sprite_cell_w INTEGER;
ALTER TABLE videos ADD COLUMN sprite_cell_h INTEGER;
ALTER TABLE videos ADD COLUMN sprite_cols INTEGER;
ALTER TABLE videos ADD COLUMN sprite_cells INTEGER;
ALTER TABLE videos ADD COLUMN sprite_interval_s REAL;

PRAGMA user_version = 9;
