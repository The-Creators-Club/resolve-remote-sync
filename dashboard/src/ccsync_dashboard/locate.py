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
    contributed: str | None = None
    unreadable = _unreadable_slugs(conn)
    if walked and wanted:
        sizes = sorted({size for _name, size in wanted})
        for start in range(0, len(sizes), _SIZE_CHUNK):
            chunk = sizes[start:start + _SIZE_CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            # dash-api-1 (2026-09-18): a project whose last walk FAILED or was
            # refused keeps its previous nas_media rows for ever (DASH-5's
            # collapse refusal does not advance tree_sig, so every later cycle
            # refuses again), and answering a locate off them says "found - at
            # the path that just stopped existing". The companion then renames
            # a file out of .ccsync-trash back onto the path lane B trashed it
            # from, every pass, and counts it as a relocation the breaker
            # discounts. An inventory the server itself has flagged is not a
            # destination: it is "cannot tell", and the excluded slugs go back
            # in the answer so the asking machine can say so in its log.
            rows = conn.execute(
                f"""SELECT p.slug AS slug, n.rel_path AS rel_path, n.size AS size,
                           n.refreshed_at AS refreshed_at
                      FROM nas_media n JOIN projects p ON p.id = n.project_id
                      LEFT JOIN nas_inventory_state s ON s.project_id = n.project_id
                     WHERE p.active=1 AND COALESCE(s.last_error, '') = ''
                       AND n.size IN ({placeholders})""",
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
                    # dash-api-3 (2026-09-18): the OLDEST contributing walk.
                    # See _as_of.
                    stamp = str(row["refreshed_at"] or "")
                    if stamp and (contributed is None or stamp < contributed):
                        contributed = stamp

    return {
        "walked": walked,
        "as_of": contributed or _as_of(conn),
        # Additive on the wire (dash-api-1): a companion that does not know
        # the key ignores it, and this dashboard in front of an older
        # companion is still strictly safer than it was, because the places
        # it would have moved a file to are the ones no longer in `files`.
        "unreadable": unreadable,
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


def _unreadable_slugs(conn: sqlite3.Connection) -> list[str]:
    """Active projects whose inventory the server knows it could not read.

    dash-api-1 (2026-09-18). `last_error` is written by the same
    `replace_nas_media` call that REFUSES to replace a collapsed walk, so a
    non-empty value means "the rows below this slug are the last good picture,
    of a directory that is currently unmounted, renamed or unreadable". Only
    `last_error` is tested, never the age of `walked_at`: a project whose
    `tree_sig` has not changed is legitimately not re-walked, so an age test
    would exclude healthy projects and turn every hand move back into a
    deletion.
    """
    try:
        rows = conn.execute(
            """SELECT p.slug AS slug
                 FROM nas_inventory_state s JOIN projects p ON p.id = s.project_id
                WHERE p.active=1 AND COALESCE(s.last_error, '') <> ''
                ORDER BY p.slug"""
        ).fetchall()
    except sqlite3.Error:                                     # pragma: no cover
        log.exception("locate: nas_inventory_state could not be read")
        return []
    return [str(row["slug"] or "") for row in rows if row["slug"]]


def _as_of(conn: sqlite3.Connection) -> str:
    """The tree-wide freshest walk: the answer's stamp when NOTHING matched.

    dash-api-3 (2026-09-18). This used to be the answer's stamp always, and
    `refreshed_at` is written per project only when that project's walk
    actually replaced its rows - so a project refused since a NAS reboot three
    days ago kept its old stamp while one healthy project walked every cycle
    made every answer look a minute old. The docstring offers this number for
    judging staleness, and the companion logs it beside a rename it made from
    three-day-old data. So an answer that found something is stamped with the
    OLDEST walk that contributed to it, which BOUNDS the answer instead of
    flattering it; only an answer with no matches falls back here, where there
    is nothing to bound and "how old is the picture at all" is the question.
    Same string on the wire either way, so no companion release is needed.
    """
    try:
        row = conn.execute("SELECT MAX(refreshed_at) AS at FROM nas_media").fetchone()
    except sqlite3.Error:                                     # pragma: no cover
        return ""
    return str((row["at"] if row else "") or "")
