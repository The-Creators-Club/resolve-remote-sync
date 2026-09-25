"""What the dashboard holds about one person, gathered from every store, and
the client-folder half of deleting them (LG-2 and LG-3,
docs/LEGAL_GAP_FEATURES_PLAN.md sections 4.2 and 4.3, 2026-09-25).

The dashboard database half is G0's registry (`db.SUBJECT_TABLES`, read by
`db.fetch_subject_rows`). This module adds the stores that are not the
dashboard's own file:

* the sign-in sessions and throttle (`sessions.SessionStore.subject_rows`,
  G2a), which live in the same file but in a schema `db.migrate` does not own;
* the YouTube ledger (`ytdl.subject_rows`, G4), which is the mounted app's own
  database;
* `client_shares.db`, `broll.db` and `music.db`, which belong to the mounted
  b-roll and music apps and are opened READ-ONLY here, the way
  alerts._sqlite_ro opens them (BROLL-2): nothing in an export may write to a
  customer's index, and a store that is missing, locked or not mounted is
  "could not be read", which the file says in `not_included`, never an error
  that loses the rest of the export.

A helper another group owns may not exist in this build (wave 1 builds them
in parallel, and an older checkout of a mounted app has none), so each is
asked through getattr and its absence is written into `not_included` in
words. A silent gap is the one thing an access request cannot have.

Deleting a person pseudonymises `client_shares.db` in place (forget_shares):
the links are the studio's to its clients, so they keep working and only the
curator's name goes. broll.db and music.db `ingest_batches` are NOT edited:
publish_db.py replaces those files wholesale from the base rig, so an edit
here would be undone at the next publish (the cleared wording says so).
"""
from __future__ import annotations

import base64
import datetime as dt
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

from . import db

log = logging.getLogger(__name__)

# Columns never exported from another store, by name, for the same reason
# db.SUBJECT_TABLES excludes `token_hash`: a client folder's `token` IS the
# credential of a public link (docs/CLIENT_FOLDERS.md), so a copy of it in a
# file that gets mailed around is a copy of the link.
_EXCLUDED_OTHER_STORE_COLUMNS = frozenset({"token", "token_hash", "sid", "sid_hash",
                                           "password_hash", "secret"})

# In words, in the order PRIVACY section 8's replacement wording lists them
# (plan 8.2). Shown to the person in their own file, so plain sentences and
# no em dashes (the owner's rule for anything a person reads).
NOT_INCLUDED: tuple[str, ...] = (
    "Files on the person's own computers, including the CCSync folder there "
    "(~/.ccsync): the dashboard does not hold them.",
    "Files on the storage server, and Syncthing's own database: they are the "
    "footage and its sync state, not records the dashboard keeps.",
    "The text of server triage reports: they are mailed, not kept per person, "
    "and their runs are deleted after 60 days.",
    "Timeline Cards working records (turns and edit chat), which are kept per "
    "episode under the dashboard's data folder, not per person.",
    "Sign-in throttle records kept by network address rather than by name: "
    "nothing ties them to one person.",
    "Snapshots of the dashboard's storage, which expire on their own schedule.",
)

# The mounted apps' tables that name a person, and the columns that do.
# `db.OTHER_STORE_SUBJECT_TABLES` names the same tables for the coverage test.
_CLIENT_SHARE_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("client_folders", ("created_by",)),
    ("client_folder_items", ("added_by",)),
)
_INGEST_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ingest_batches", ("editor", "cancel_by", "cancelled_by")),
)


# ------------------------------------------------------------------ paths

def _store_paths() -> dict[str, Path | None]:
    """{'client_shares', 'broll', 'music'} -> the database file, or None.

    From the mounted apps' OWN config, found through sys.modules only (the
    same rule as alerts._broll_paths): importing the b-roll or music tree on a
    site that does not mount it is exactly what the mounts' tri-state exists
    to avoid. Tests replace this function."""
    out: dict[str, Path | None] = {"client_shares": None, "broll": None, "music": None}
    config = sys.modules.get("app.config")
    if config is not None:
        try:
            out["broll"] = Path(config.get_db_path())
            out["client_shares"] = Path(config.get_data_root()) / "client_shares.db"
        except Exception:                                           # noqa: BLE001
            log.debug("subject_data: b-roll config did not answer", exc_info=True)
    music_config = sys.modules.get("musicweb.config")
    if music_config is not None:
        try:
            out["music"] = Path(music_config.DB_PATH)
        except Exception:                                           # noqa: BLE001
            log.debug("subject_data: music config did not answer", exc_info=True)
    return out


def _open_ro(path: Path | None) -> sqlite3.Connection | None:
    try:
        if path is None or not Path(path).exists():
            return None
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True,
                               timeout=2.0)
        conn.row_factory = sqlite3.Row
        return conn
    except (sqlite3.Error, OSError, ValueError):
        log.debug("subject_data: could not open %s read-only", path, exc_info=True)
        return None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _rows_by_columns(conn: sqlite3.Connection, table: str, person_columns: tuple[str, ...],
                     username: str) -> list[dict[str, Any]] | None:
    """Rows of `table` whose person columns equal `username` (case-folded:
    every one of these columns holds a dashboard sign-in name, which is
    lower-case, and a mounted app that stored one as typed must still match).
    None = the table is not there (an older store)."""
    present = _columns(conn, table)
    if not present:
        return None
    cols = [c for c in person_columns if c in present]
    if not cols:
        return []
    where = " OR ".join(f"lower({c}) = :u" for c in cols)
    rows = conn.execute(f"SELECT * FROM {table} WHERE {where}", {"u": username}).fetchall()
    return [{k: r[k] for k in r.keys() if k not in _EXCLUDED_OTHER_STORE_COLUMNS}
            for r in rows]


def _read_store(name: str, path: Path | None, tables, username: str,
                out: dict[str, list[dict[str, Any]]], missing: list[str],
                what: str) -> None:
    conn = _open_ro(path)
    if conn is None:
        # Not mounted here is the common case (a site without b-roll or
        # music) and is still said: "nothing" and "could not look" must read
        # differently in a person's own file.
        missing.append(f"{what}: not available on this dashboard, so it could not be read.")
        return
    try:
        for table, person_columns in tables:
            try:
                rows = _rows_by_columns(conn, table, person_columns, username)
            except sqlite3.Error:
                log.warning("subject_data: could not read %s.%s", name, table, exc_info=True)
                missing.append(f"{what} ({table}): could not be read just now.")
                continue
            if rows is not None:
                out[f"{name}.{table}"] = rows
    finally:
        conn.close()


# ------------------------------------------------------- other groups' helpers

def _merge_helper(prefix: str, result: Any, out: dict[str, list[dict[str, Any]]]) -> None:
    """A helper answers table -> rows (the contract in the plan's 7.3). A bare
    list is accepted too and filed under the store's own name, so a helper
    that answers one table is not lost."""
    if isinstance(result, dict):
        for table, rows in result.items():
            out[f"{prefix}.{table}"] = [dict(r) for r in (rows or [])]
    elif isinstance(result, (list, tuple)):
        out[prefix] = [dict(r) for r in result]


def _is_envelope(result: Any) -> bool:
    # G4's ytdl helpers answer {"status", "detail", "tables"} (ytdl.py,
    # 2026-09-25), the session store a bare table -> rows. The first build
    # merged the envelope as if it were tables, so dict("ok") raised on EVERY
    # export and the YouTube half always read "could not be read" (G3 review
    # round, point 1). No store has a table called "status".
    return isinstance(result, dict) and isinstance(result.get("status"), str)


def _ask(helper: Callable[..., Any] | None, prefix: str, username: str,
         out: dict[str, list[dict[str, Any]]], missing: list[str], what: str) -> None:
    if helper is None:
        missing.append(f"{what}: this dashboard version cannot read them yet.")
        return
    try:
        result = helper(username)
        if _is_envelope(result):
            if result["status"] != "ok":
                # "absent" and "error" both leave this half out of the file,
                # and the helper's own sentence says which (no records here,
                # not installed, could not be opened).
                detail = str(result.get("detail") or "could not be read just now")
                missing.append(f"{what}: {detail.rstrip('.')}.")
                return
            result = result.get("tables") or {}
        _merge_helper(prefix, result, out)
    except Exception:                                               # noqa: BLE001
        log.warning("subject_data: %s helper failed", prefix, exc_info=True)
        missing.append(f"{what}: could not be read just now.")


def _session_helper(store: Any) -> Callable[..., Any] | None:
    return getattr(store, "subject_rows", None) if store is not None else None


def _ytdl_helper() -> Callable[..., Any] | None:
    try:
        from . import ytdl
    except Exception:                                               # noqa: BLE001
        return None
    return getattr(ytdl, "subject_rows", None)


# ------------------------------------------------------------------ collect

def collect(conn: sqlite3.Connection, username: str, *, session_store: Any = None,
            dashboard_version: str = "", now: str | None = None) -> dict[str, Any]:
    """Everything this dashboard holds about `username`, as one JSON-ready
    dict: {generated_at, dashboard_version, subject, tables, not_included}.

    `tables` is flat: the dashboard database's tables by their own names (G0's
    registry, secrets dropped by column), the other stores' as
    `<store>.<table>`. Read-only everywhere; the caller commits nothing."""
    user = str(username or "").strip().lower()
    tables: dict[str, list[dict[str, Any]]] = dict(db.fetch_subject_rows(conn, user))
    missing: list[str] = []

    _ask(_session_helper(session_store), "sessions", user, tables, missing,
         "Signed-in browser sessions and failed sign-ins under this name")
    _ask(_ytdl_helper(), "ytdl", user, tables, missing,
         "YouTube requests, downloads and rights confirmations")

    paths = _store_paths()
    _read_store("client_shares", paths.get("client_shares"), _CLIENT_SHARE_TABLES, user,
                tables, missing, "Client folders and the clips added to them")
    _read_store("broll", paths.get("broll"), _INGEST_TABLES, user, tables, missing,
                "B-roll indexing batches")
    _read_store("music", paths.get("music"), _INGEST_TABLES, user, tables, missing,
                "Music indexing batches")

    return {
        "generated_at": now or db.utcnow_iso(),
        "dashboard_version": str(dashboard_version or ""),
        "subject": user,
        "tables": tables,
        "not_included": list(NOT_INCLUDED) + missing,
    }


def counts(export: dict[str, Any]) -> dict[str, int]:
    """table -> row count, the only thing an audit row about an export may
    carry (plan 4.2: "counts only")."""
    return {t: len(rows or []) for t, rows in (export.get("tables") or {}).items()}


def _jsonable(value: Any) -> Any:
    # A BLOB column (a digest, a waveform) is data the person holds a right
    # to, not a reason to fail the export.
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"base64": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return str(value)


class ExportTooLarge(Exception):
    """The encoded export passed `max_bytes`; raised while encoding, so the
    whole oversized string is never built (G3 review round, point 8)."""


def to_json_bytes(export: dict[str, Any], max_bytes: int | None = None) -> bytes:
    """`export` as UTF-8 JSON. With `max_bytes`, encoding stops and
    ExportTooLarge is raised as soon as the output passes it: the first build
    made the whole indented string and then measured it, so an editor with a
    large editor_media briefly held several times the cap in the container.
    The rows themselves are still in memory (collect reads them whole); only
    the text copy is bounded."""
    import json

    encoder = json.JSONEncoder(indent=1, sort_keys=True, ensure_ascii=False,
                               default=_jsonable)
    parts: list[bytes] = []
    size = 0
    for chunk in encoder.iterencode(export):
        data = chunk.encode("utf-8")
        size += len(data)
        if max_bytes is not None and size > max_bytes:
            raise ExportTooLarge(size)
        parts.append(data)
    return b"".join(parts)


# ---------------------------------------------------------- forget (delete)

class ForgetSharesFailed(Exception):
    """The deleted person's name could NOT be removed from client_shares.db.

    Raised, not returned (G3 review round, point 3, 2026-09-25): the first
    build returned {"ok": False} and delete_user_everywhere, which ignores
    the return value, reported a finished delete while client folders still
    carried the real name. A raise lands in the caller's `except`, which
    writes a warning the admin reads."""


def forget_shares(username: str, stand_in: str | None = None, *,
                  conn: sqlite3.Connection | None = None,
                  path: Path | None = None) -> dict[str, Any]:
    """LG-3 delete: replace `username` in client_shares.db's `created_by` and
    `added_by` with the person's stand-in. The links keep working: the token,
    the clips and the folder are the studio's, not the curator's. Free-text
    columns (`contact`, `description`, item notes) are NOT rewritten; they
    are the studio's words to its client and may name anyone.

    The stand-in is `db.pseudonym(conn, username)`; pass it, or pass the
    dashboard connection it is minted from. The plan's contract names only
    `username`, but the stand-in is keyed on the dashboard's pseudonym salt,
    which lives in the dashboard database, so one of the two is needed.

    If the salt did not exist yet, db.pseudonym mints it on `conn`; this
    function commits that write itself when `conn` had no transaction open
    before the call (review point 9: an uncommitted salt is lost, and the
    next stand-in for the same person differs, so one deleted person reads
    as two). A caller already inside a transaction must commit it.

    -> {"ok": True, "client_folders": n, "client_folder_items": n}, or
    {"ok": False, "reason"} when there was nothing to do (no client folders
    on this dashboard). Raises ForgetSharesFailed when the name could not be
    removed: no stand-in to use, or the store could not be opened or
    written."""
    user = str(username or "").strip().lower()
    if not user:
        return {"ok": False, "reason": "no username"}
    target = path if path is not None else _store_paths().get("client_shares")
    if target is None or not Path(target).exists():
        return {"ok": False, "reason": "client folders are not on this dashboard"}
    if stand_in is None:
        if conn is None:
            log.warning("subject_data.forget_shares(%s): no stand-in and no connection; "
                        "client folders keep the name", user)
            raise ForgetSharesFailed("no stand-in name was given for the deleted person")
        was_in_txn = conn.in_transaction
        stand_in = db.pseudonym(conn, user)
        if not was_in_txn and conn.in_transaction:
            conn.commit()
    try:
        shares = sqlite3.connect(str(target), timeout=10.0)
    except sqlite3.Error as exc:
        log.warning("subject_data.forget_shares: could not open %s", target, exc_info=True)
        raise ForgetSharesFailed("could not open client_shares.db") from exc
    out: dict[str, Any] = {"ok": True}
    try:
        for table, person_columns in _CLIENT_SHARE_TABLES:
            present = _columns(shares, table)
            n = 0
            for col in person_columns:
                if col in present:
                    n += int(shares.execute(
                        f"UPDATE {table} SET {col} = ? WHERE lower({col}) = ?",
                        (stand_in, user)).rowcount or 0)
            out[table] = n
        shares.commit()
    except sqlite3.Error as exc:
        shares.rollback()
        log.warning("subject_data.forget_shares: update failed", exc_info=True)
        raise ForgetSharesFailed("client_shares.db could not be updated just now") from exc
    finally:
        shares.close()
    return out
