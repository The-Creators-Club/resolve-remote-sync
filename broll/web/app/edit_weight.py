"""Is a clip's own file already light enough to cut on? One rule, two copies.

The companion decides this at INGEST (make an editing proxy or not,
`ccsync_companion.ffmpeg_tools.is_edit_weight`) and this web app decides it
again at INSERT time (`routes_api._is_edit_weight`, the detail API's
`original_is_edit_weight`). The two answers describe the same file and must
not disagree: a clip the companion judged edit-weight has no `.mov` beside it,
so a page that called the same file heavy would send a remote editor looking
for a proxy that was deliberately never made (plan section 5 items 1-2,
2026-09-17).

A VERBATIM copy rather than a shared import: `broll/web` is deployed to the
NAS container as a tree on PYTHONPATH and knows nothing about
`ccsync_companion`, which is a frozen exe on an editor's machine. The
companion suite's test_broll_ingest_media.py loads THIS file by path and
compares the two answers case by case, which is what keeps the copies honest
-- the same arrangement `hash_partial` and the preview argv already live
under. Stdlib only, for the same reason: it is imported by path, with no
package around it.
"""
from __future__ import annotations

# Where "edit-weight" sits (plan section 5 item 1, owner question 4): at or
# below 1080 lines, at or below about 12 Mbps, in a codec Resolve decodes
# cheaply. A file like that IS its own editing proxy -- downloading it is
# correct and making a second one would waste the space twice.
EDIT_WEIGHT_MAX_HEIGHT = 1080
EDIT_WEIGHT_MAX_BITRATE = 12_000_000
EDIT_WEIGHT_CODECS = ("h264", "hevc")


def is_edit_weight(height, bitrate, codec) -> bool | None:
    """Is this file already an editing proxy? None = cannot tell.

    None is the answer when the bitrate is unknown: a row indexed before
    migration 012 added the column (2026-09-17), or a probe that could not
    read one. It must stay distinguishable from False -- a missing bitrate
    read as 0 would say "tiny, definitely edit-weight" and send a remote
    editor a multi-GB camera master.
    """
    if bitrate is None:
        return None
    name = str(codec or "").lower()
    # Any ProRes flavour counts. The archive holds Proxy and LT, which are
    # cheap; a 6K ProRes 422 master is excluded by the height and bitrate
    # tests below, not by its codec name.
    cheap_codec = name in EDIT_WEIGHT_CODECS or name.startswith("prores")
    if not cheap_codec or height is None:
        return False
    try:
        return int(height) <= EDIT_WEIGHT_MAX_HEIGHT and int(bitrate) <= EDIT_WEIGHT_MAX_BITRATE
    except (TypeError, ValueError):
        # A height or bitrate that is not a number is not a measurement, and
        # guessing here would be this rule inventing a verdict.
        return None
