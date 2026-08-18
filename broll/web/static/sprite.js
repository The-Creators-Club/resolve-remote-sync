"use strict";

/* ==========================================================================
   Sprite-sheet geometry, shared by the b-roll SPA (app.js) and the client
   folder viewer (share.js). A CLASSIC script loaded before either: they read
   these as globals, and there is no build step here.

   Extracted from app.js on 2026-08-18 rather than copied into share.js,
   because this arithmetic has been wrong twice in ways only the live archive
   revealed (BROLL-1, BROLL-2 -- see the comments below) and a second copy is
   a second place for the next such bug to hide. tests/test_sprite_geometry.py
   pins these constants against the generator's.
   ========================================================================== */

const SPRITE_COLUMNS = 10;
const SPRITE_SECONDS_PER_FRAME = 2;
const SPRITE_CELL_WIDTH = 240;
// Mirrors broll_index/ffmpeg_tools.py's SPRITE_MAX_CELLS. The generator caps a
// sheet at this many cells and STRETCHES the interval to fit, because a 2 s
// interval on a long clip wants an image too big to encode -- so the interval
// is only 2 s for clips under SPRITE_MAX_CELLS * 2 s (8 minutes). Reading it as
// a constant 2 s put every longer clip's frame off the bottom of its own sheet.
// broll/web/tests/test_sprite_geometry.py keeps the two files in step.
const SPRITE_MAX_CELLS = 240;

/** Seconds per sheet cell for `duration`, mirroring build_sprite exactly: 2 s
 * until that would need more than SPRITE_MAX_CELLS cells, then duration/240.
 *
 * This is the whole bug behind "the thumbnail is not the frame that matched".
 * A 50:41 documentary gets a 12.67 s interval, so the 46:20 hit lives in cell
 * 219 -- but read at a flat 2 s it was called cell 1390, i.e. row 139 of a
 * sheet 24 rows tall. The overlay landed far below the image, painted nothing,
 * and the POSTER showed through instead: build_poster takes that at 10% in,
 * which for this file is 5:04 -- the interview at the bookshelf. Everything
 * over 8 minutes was showing its 10% frame and looking, plausibly, like a
 * thumbnail that had simply picked a dull moment. */
function spriteInterval(duration) {
  if (duration && duration / SPRITE_SECONDS_PER_FRAME > SPRITE_MAX_CELLS) {
    return duration / SPRITE_MAX_CELLS;
  }
  return SPRITE_SECONDS_PER_FRAME;
}

/** The sheet's grid: what the generator RECORDED for this clip, or the old
 * guesswork for a sheet built before it recorded anything.
 *
 * The guesswork was wrong twice over, both measured on the live archive
 * (2026-08-11):
 *
 *   * cell height was re-derived from videos.width/height -- the SOURCE. The
 *     sheet is tiled from the 540p proxy through `scale=240:-2`, and both scale
 *     steps round to an even number, so 6,783 of 7,117 sheets were a pixel
 *     taller than this arithmetic said. With no CSS background-size to absorb
 *     it, a 24-row sheet lands ~17% off and shows a splice of two rows
 *     (BROLL-1);
 *   * the SPRITE_MAX_CELLS cap was applied unconditionally, including to the 95
 *     sheets built at a flat 2 s before the cap existed -- so a hit at 30:00 in
 *     a 58:47 clip painted the frame at 4:04 (BROLL-2).
 *
 * Neither is recoverable from the sheet, so build_sprite now measures its own
 * output into videos.sprite_*. A row without it keeps the old behaviour exactly
 * -- nothing gets worse for an unregenerated sheet -- and becomes exact the
 * moment an operator re-runs build_sprite for that clip. */
function spriteGeometry(video) {
  const duration = video.duration_s || 0;
  if (video.sprite_cell_w && video.sprite_cell_h && video.sprite_cells) {
    return {
      cellWidth: video.sprite_cell_w,
      cellHeight: video.sprite_cell_h,
      columns: video.sprite_cols || SPRITE_COLUMNS,
      cells: video.sprite_cells,
      interval: video.sprite_interval_s || spriteInterval(duration),
    };
  }
  const interval = spriteInterval(duration);
  return {
    cellWidth: SPRITE_CELL_WIDTH,
    cellHeight: video.width && video.height
      ? Math.round(SPRITE_CELL_WIDTH * (video.height / video.width))
      : 135,
    columns: SPRITE_COLUMNS,
    // Same count the generator tiles: floor(duration/interval) + 1, capped.
    cells: Math.min(SPRITE_MAX_CELLS, Math.max(1, Math.floor(duration / interval) + 1)),
    interval,
  };
}

/** Park the sprite overlay on the sheet cell holding `seconds`, using that
 * sheet's own grid (see spriteGeometry). */
function positionSprite(overlay, video, seconds) {
  const geo = spriteGeometry(video);
  const frame = Math.min(
    geo.cells - 1,
    Math.max(0, Math.floor(seconds / geo.interval))
  );
  const col = frame % geo.columns;
  const row = Math.floor(frame / geo.columns);
  overlay.style.backgroundPosition = `-${col * geo.cellWidth}px -${row * geo.cellHeight}px`;
}

function wireSpriteScrub(thumb, overlay, video) {
  thumb.addEventListener("mousemove", (e) => {
    const rect = thumb.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    positionSprite(overlay, video, frac * (video.duration_s || 0));
  });
}
