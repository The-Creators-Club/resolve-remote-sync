"""Where else on the NAS is a file with this name and this size?

`docs/HAND_MOVES_ON_THE_SERVER.md` phase 2 (2026-09-11). A hand move on the
NAS presents to an editor's lane B as a deletion: the files vanished from the
path that machine syncs, so `rclone sync` walks the local copies into
`.ccsync-trash` and, past 50 in one pass, the breaker parks the lane (CR-45).
CR-44 already asks "were they MOVED?" before tripping, but it asks by
re-listing the SCOPE, so a move to another project -- the shape that actually
happened, twice -- is outside the question it can ask.

This module is the tree-wide version of that question, answered from
`nas_media` (the inventory walk, at most `interval_inventory` stale) instead
of from the NAS itself. No filesystem call happens here at all: the cost of a
locate is one read of a table the collector already maintains, which is what
makes it safe to hang off a lane B pass.

Three properties the caller depends on:

  * **Basenames are compared NFC** (`db.media_rel_key`, CR-90). The names come
    off an editor's disk, and a Mac spells `Matej Simalcik` decomposed while
    the NAS inventory holds it composed. Comparison only -- the `rel_path`
    handed back is the bytes the server holds, because that is what the
    companion will rename to.
  * **`walked` is tri-state information, not a boolean convenience.** A
    dashboard whose inventory has never run answers `walked: false`, and the
    companion must then read "not found" as "not known" and change nothing.
    Silence and absence are different answers (the `idle_seconds` rule).
  * **`as_of`** is the newest `refreshed_at` in the table, so the caller can
    see how stale the server's picture is rather than assuming it is current.

Ambiguity is deliberately NOT resolved here: a name+size found at three paths
comes back with all three, and the mover on the far end declines to guess
(design section 6). This module reports; it never decides.
"""
from __future__ import annotations

import logging
import posixpath
import sqlite3
from typing import Any, Iterable

from . import db

log = logging.getLogger("ccsync.dashboard.locate")

# The most files one locate may ask about. A lane B pass is bounded by
# rclone's --max-delete (100), so this is roughly twenty passes' worth and no
# honest caller reaches it; it exists so a malformed body cannot turn one
# request into an unbounded scan.
MAX_LOCATE_FILES = 2000

# SQLite's oldest compiled-in parameter ceiling is 999. The size prefilter is
# chunked under it rather than built as one enormous IN list, because the
# limit is a property of the interpreter the container happens to ship.
_SIZE_CHUNK = 900


def locate(conn: sqlite3.Connection,
           entries: Iterable[tuple[str, int]]) -> dict[str, Any]:
    """(basename, size) pairs -> where each one sits on the NAS.

    The query is a SIZE prefilter plus a basename match in Python, and not a
    `WHERE basename = ?` join, because `nas_media` is keyed and indexed on
    `(project_id, rel_path)` and has no basename column: a LIKE '%/name'
    would scan the table once per file asked about. One scan per request,
    bounded by the caller's own cap, beats two thousand index-less lookups,
    and adding an index here would be a schema change in a module that must
    not own one (phase 1 owns `db.py`).
    """
    wanted: dict[tuple[str, int], list[dict[str, str]]] = {}
    order: list[tuple[str, int]] = []
    for name, size in entries:
        key = (db.media_rel_key(posixpath.basename(str(name or "").replace("\\", "/"))),
               int(size))
        if key not in wanted:
            wanted[key] = []
            order.append(key)

    walked = _has_been_walked(conn)
    as_of = _as_of(conn)
    if walked and wanted:
        sizes = sorted({size for _name, size in wanted})
        for start in range(0, len(sizes), _SIZE_CHUNK):
            chunk = sizes[start:start + _SIZE_CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""SELECT p.slug AS slug, n.rel_path AS rel_path, n.size AS size
                      FROM nas_media n JOIN projects p ON p.id = n.project_id
                     WHERE p.active=1 AND n.size IN ({placeholders})""",
                chunk,
            ).fetchall()
            for row in rows:
                rel = str(row["rel_path"] or "")
                # Stored NFC already (replace_nas_media normalises on the way
                # in), but folded again here: an inventory written by an older
                # build predates that rule and would otherwise never match a
                # Mac's trashed name.
                key = (db.media_rel_key(posixpath.basename(rel)), int(row["size"] or 0))
                bucket = wanted.get(key)
                if bucket is not None:
                    bucket.append({"project_slug": str(row["slug"] or ""),
                                   "rel_path": rel})

    return {
        "walked": walked,
        "as_of": as_of,
        "files": [{"name": name, "size": size, "found": wanted[(name, size)]}
                  for name, size in order],
    }


def _has_been_walked(conn: sqlite3.Connection) -> bool:
    """Has the inventory ever produced anything to answer from?

    A row in `nas_media` is the evidence, not a row in `nas_inventory_state`:
    a walk that refused a collapse (DASH-5) or failed writes the state row and
    no media, and answering "found nothing" off that is the mistake this flag
    exists to stop.
    """
    try:
        return conn.execute("SELECT 1 FROM nas_media LIMIT 1").fetchone() is not None
    except sqlite3.Error:                                     # pragma: no cover
        log.exception("locate: nas_media could not be read")
        return False


def _as_of(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("SELECT MAX(refreshed_at) AS at FROM nas_media").fetchone()
    except sqlite3.Error:                                     # pragma: no cover
        return ""
    return str((row["at"] if row else "") or "")
