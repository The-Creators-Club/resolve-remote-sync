"""Client folders: curated sets of clips with an outward-facing preview link.

An editor picks clips out of the archive into a named folder, and the folder
gets a link -- `<public base>/broll/share/<token>/` -- that a prospective
licensee can open with no account and browse the way an editor browses the
archive: hover-scrub thumbnails, a 540p preview player, what is in each clip.
docs/CLIENT_FOLDERS.md is the operator's document; this module is the ledger.

**A SEPARATE DATABASE, `client_shares.db`, BESIDE broll.db -- NOT NEW TABLES
IN broll.db.** broll.db is the search INDEX: the base rig builds it and pushes
it over the live copy with server/publish_db.py (checkpoint, stage, verify,
rename), which is exactly the right thing to do to an index and exactly the
wrong thing to do to a customer's list of which clips they showed which client
last week. Rows here are written on the NAS by editors and only ever there;
they must survive every index publish, so they live in a file publish_db.py
never touches. It sits in the same data root (the same dataset, so
setup_snapshots.py's schedule covers it and docs/BACKUP_RESTORE.md restores it
with everything else). Clips are referenced by broll.db's `videos.id` AND by
their (share, rel_path) identity: an id is only as stable as the next index
build, and a folder whose clip has been re-indexed under a new id can be
re-resolved by name at read time (`resolve_items`) rather than silently losing
the clip.

**THE TOKEN IS THE CREDENTIAL, and it is stored in the clear.** 128 bits from
secrets.token_urlsafe, unguessable, never derived from anything. Stored as
typed rather than hashed because the one thing an editor does with a folder
after making it is copy its link again -- a hash would mean "the link is shown
once and never again", which is not how a small studio works with clients. The
database is on the NAS, behind the dashboard, behind the tailnet; a copy of it
IS a copy of every live link, which is also true of the browser history of
everyone who ever clicked one. Revoke (`revoked_at`) and expiry (`expires_at`)
are the answer to a link that got away, and both are honoured on every public
request, not only at page load.

Nothing here knows about HTTP. routes_client_folders.py is the editor's door
(session identity stamped by the dashboard gate), routes_share.py the public
one (token only, read only). Both call in here.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from app import config

SCHEMA_VERSION = 1

# secrets.token_urlsafe(16) -> 22 chars of [A-Za-z0-9_-]. The pattern is a
# little wider than what we mint so a future longer token still routes; it is
# still tight enough that `assets` (the static mount beside these routes) and
# any path-shaped junk never reach a database lookup.
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
TOKEN_BYTES = 16

# Bounds on what an editor may type. Generous, and refused (422) rather than
# truncated: a title cut short is a title the client reads wrong.
MAX_TITLE = 120
MAX_DESCRIPTION = 2000
MAX_CONTACT = 200
MAX_NOTE = 500
# Folders are curated by hand for one client; a thousand clips is not a
# showcase, it is the archive, and the public page would take a while to draw.
MAX_ITEMS = 500

# The one key/value setting this ledger holds: the public origin the links are
# minted against (docs/CLIENT_FOLDERS.md "The public base URL"). Blank means
# "not configured": links are still made against the dashboard's own origin,
# which only reaches inside the tailnet, and the panel says so.
SETTING_PUBLIC_BASE = "public_base_url"

_SCHEMA = """
CREATE TABLE client_folders (
    id          INTEGER PRIMARY KEY,
    token       TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    -- Free text the public page shows as "to licence, contact ..." An email
    -- address is rendered as a mailto link; anything else is shown as typed.
    contact     TEXT NOT NULL DEFAULT '',
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    -- ISO UTC. NULL = never expires. Compared as text against now_iso(),
    -- which is safe because both are datetime.isoformat() of aware UTC times
    -- (the same trick ingest_batches.expire_stale_leases relies on).
    expires_at  TEXT,
    -- Set = the link is dead until an editor reactivates it. Kept as a
    -- timestamp rather than a flag so the panel can say when.
    revoked_at  TEXT,
    view_count  INTEGER NOT NULL DEFAULT 0,
    last_viewed_at TEXT
);

CREATE TABLE client_folder_items (
    id          INTEGER PRIMARY KEY,
    folder_id   INTEGER NOT NULL REFERENCES client_folders(id) ON DELETE CASCADE,
    video_id    INTEGER NOT NULL,
    -- The clip's identity in broll.db, carried alongside the id so a
    -- re-indexed archive (new ids, same files) can be re-resolved by name.
    share       TEXT NOT NULL,
    rel_path    TEXT NOT NULL,
    ord         INTEGER NOT NULL,
    -- The curator's caption for this clip in this folder ("drone, golden
    -- hour, 4K master available"). Shown on the public page under the
    -- thumbnail; blank shows the file's own name.
    note        TEXT NOT NULL DEFAULT '',
    added_by    TEXT NOT NULL,
    added_at    TEXT NOT NULL,
    UNIQUE (folder_id, video_id)
);
CREATE INDEX idx_client_folder_items_folder ON client_folder_items(folder_id, ord);

CREATE TABLE client_share_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

PRAGMA user_version = 1;
"""


class ClientFolderError(ValueError):
    """A request that is well-formed but cannot be honoured (unknown clip,
    folder full, ...). The routes turn these into 4xx with the message."""


# --- schema / connections ------------------------------------------------------

def get_db_path() -> Path:
    return config.get_data_root() / "client_shares.db"


def ensure_schema(db_path: Path | None = None) -> None:
    """Create client_shares.db if it is missing. Idempotent.

    A DB newer than this code is refused, like broll.db's ensure_schema: a
    file migrated by a newer deployment must not be half-read by an older one.
    """
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            conn.executescript(_SCHEMA)
            version = SCHEMA_VERSION
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"FATAL: {path} has user_version={version}, newer than this app "
                f"supports (max {SCHEMA_VERSION}). Upgrade the web app before "
                "pointing it at this data root."
            )
    finally:
        conn.close()


def open_connection(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_shares_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: a per-request connection to client_shares.db.

    ensure_schema on the way in, cheaply (one PRAGMA when the file exists):
    unlike broll.db this file is created by this feature alone, and a
    deployment whose lifespan shim predates it must not 500 on first use.
    """
    ensure_schema()
    conn = open_connection()
    try:
        yield conn
    finally:
        conn.close()


# --- small helpers ---------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def valid_token(token: str | None) -> bool:
    return bool(token) and TOKEN_RE.match(token) is not None


def _clean_text(value: str | None, limit: int, field: str) -> str:
    text = (value or "").strip()
    if len(text) > limit:
        raise ClientFolderError(f"{field} is too long (max {limit} characters)")
    return text


def _clean_expires(value: str | None) -> str | None:
    """An ISO timestamp, normalised to aware UTC isoformat, or None."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise ClientFolderError("expires_at is not an ISO date/time") from e
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


# --- folders -----------------------------------------------------------------------

def create_folder(conn: sqlite3.Connection, *, title: str, created_by: str,
                  description: str = "", contact: str = "",
                  expires_at: str | None = None) -> sqlite3.Row:
    title = _clean_text(title, MAX_TITLE, "title")
    if not title:
        raise ClientFolderError("a folder needs a title")
    now = now_iso()
    # A UNIQUE collision on 128 random bits is not a case worth a retry loop,
    # but the loop costs one line and the alternative is a 500 once a century.
    for _ in range(3):
        token = new_token()
        try:
            cur = conn.execute(
                "INSERT INTO client_folders (token, title, description, contact, "
                "created_by, created_at, updated_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (token, title, _clean_text(description, MAX_DESCRIPTION, "description"),
                 _clean_text(contact, MAX_CONTACT, "contact"), created_by, now, now,
                 _clean_expires(expires_at)),
            )
            break
        except sqlite3.IntegrityError:
            continue
    else:  # pragma: no cover - three collisions of 128-bit tokens
        raise ClientFolderError("could not mint a link token; try again")
    conn.commit()
    return get_folder(conn, cur.lastrowid)


def get_folder(conn: sqlite3.Connection, folder_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM client_folders WHERE id = ?", (folder_id,)).fetchone()


def get_folder_by_token(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    if not valid_token(token):
        return None
    return conn.execute("SELECT * FROM client_folders WHERE token = ?", (token,)).fetchone()


def list_folders(conn: sqlite3.Connection) -> list[dict]:
    """Every folder, newest first, with its item count.

    Every editor sees every folder (2026-08-18 decision): a client folder is
    the studio's, not the editor's, and a colleague has to be able to find
    "the one we sent to X" without asking who made it. `created_by` is shown,
    not enforced.
    """
    rows = conn.execute(
        "SELECT f.*, (SELECT COUNT(*) FROM client_folder_items i WHERE i.folder_id = f.id) "
        "AS n_items FROM client_folders f ORDER BY f.created_at DESC, f.id DESC"
    ).fetchall()
    return [folder_dict(r) for r in rows]


def update_folder(conn: sqlite3.Connection, folder_id: int, *, title: str | None = None,
                  description: str | None = None, contact: str | None = None,
                  expires_at: str | None = None, clear_expiry: bool = False) -> sqlite3.Row:
    """Change what was sent (None = leave alone). `clear_expiry` exists because
    "expires_at: null" and "expires_at absent" are the same thing to a JSON
    body; the routes translate an explicit null into it."""
    folder = get_folder(conn, folder_id)
    if folder is None:
        raise ClientFolderError("no such folder")
    sets, args = [], []
    if title is not None:
        clean = _clean_text(title, MAX_TITLE, "title")
        if not clean:
            raise ClientFolderError("a folder needs a title")
        sets.append("title = ?"); args.append(clean)
    if description is not None:
        sets.append("description = ?"); args.append(_clean_text(description, MAX_DESCRIPTION, "description"))
    if contact is not None:
        sets.append("contact = ?"); args.append(_clean_text(contact, MAX_CONTACT, "contact"))
    if clear_expiry:
        sets.append("expires_at = NULL")
    elif expires_at is not None:
        sets.append("expires_at = ?"); args.append(_clean_expires(expires_at))
    sets.append("updated_at = ?"); args.append(now_iso())
    args.append(folder_id)
    conn.execute(f"UPDATE client_folders SET {', '.join(sets)} WHERE id = ?", args)
    conn.commit()
    return get_folder(conn, folder_id)


def set_revoked(conn: sqlite3.Connection, folder_id: int, revoked: bool) -> sqlite3.Row:
    if get_folder(conn, folder_id) is None:
        raise ClientFolderError("no such folder")
    now = now_iso()
    conn.execute(
        "UPDATE client_folders SET revoked_at = ?, updated_at = ? WHERE id = ?",
        (now if revoked else None, now, folder_id),
    )
    conn.commit()
    return get_folder(conn, folder_id)


def rotate_token(conn: sqlite3.Connection, folder_id: int) -> sqlite3.Row:
    """A NEW link for the same folder; the old one stops working at once.

    For the case revoke does not cover: the folder is still wanted, the old
    link is not (forwarded on, pasted somewhere public). Also clears a
    revocation, since the editor plainly wants a live link.
    """
    if get_folder(conn, folder_id) is None:
        raise ClientFolderError("no such folder")
    conn.execute(
        "UPDATE client_folders SET token = ?, revoked_at = NULL, updated_at = ? WHERE id = ?",
        (new_token(), now_iso(), folder_id),
    )
    conn.commit()
    return get_folder(conn, folder_id)


def delete_folder(conn: sqlite3.Connection, folder_id: int) -> None:
    conn.execute("DELETE FROM client_folders WHERE id = ?", (folder_id,))
    conn.commit()


def is_live(folder: sqlite3.Row | dict, now: str | None = None) -> bool:
    """Whether the public link answers: not revoked, not past its expiry."""
    if folder["revoked_at"]:
        return False
    expires = folder["expires_at"]
    return not expires or expires > (now or now_iso())


def status_of(folder: sqlite3.Row | dict) -> str:
    if folder["revoked_at"]:
        return "revoked"
    if folder["expires_at"] and folder["expires_at"] <= now_iso():
        return "expired"
    return "live"


def folder_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["status"] = status_of(row)
    return d


# --- items -----------------------------------------------------------------------

def _video_identity(index_conn: sqlite3.Connection, video_id: int) -> tuple[str, str]:
    row = index_conn.execute(
        "SELECT share, rel_path FROM videos WHERE id = ?", (video_id,)
    ).fetchone()
    if row is None:
        raise ClientFolderError(f"clip {video_id} is not in the archive index")
    return row["share"], row["rel_path"]


def add_items(conn: sqlite3.Connection, index_conn: sqlite3.Connection, folder_id: int,
              video_ids: list[int], added_by: str) -> dict:
    """Append clips (in the order given) that are not already in the folder.

    Returns {"added": [ids], "already": [ids]}. Idempotent by design -- the
    card's "+" is pressed twice more often than one would think, and the
    second press must not be an error toast.
    """
    if get_folder(conn, folder_id) is None:
        raise ClientFolderError("no such folder")
    # By id AND by (share, rel_path): after an index rebuild renumbers
    # videos.id the folder's row for this clip carries the OLD id, so an
    # id-only test says "not in the folder", UNIQUE (folder_id, video_id) does
    # not catch the second insert, and resolve_items then draws the clip twice
    # on the client's page (broll-4, 2026-08-21).
    present, present_names = set(), set()
    for r in conn.execute(
            "SELECT video_id, share, rel_path FROM client_folder_items "
            "WHERE folder_id = ?", (folder_id,)):
        present.add(r["video_id"])
        present_names.add((r["share"], r["rel_path"]))
    ord_row = conn.execute(
        "SELECT COALESCE(MAX(ord), -1) FROM client_folder_items WHERE folder_id = ?",
        (folder_id,)).fetchone()
    next_ord = int(ord_row[0]) + 1
    added, already = [], []
    now = now_iso()
    for vid in video_ids:
        vid = int(vid)
        if vid in present:
            already.append(vid)
            continue
        share, rel_path = _video_identity(index_conn, vid)
        if (share, rel_path) in present_names:
            already.append(vid)
            continue
        if len(present) >= MAX_ITEMS:
            raise ClientFolderError(f"a client folder holds at most {MAX_ITEMS} clips")
        conn.execute(
            "INSERT INTO client_folder_items (folder_id, video_id, share, rel_path, ord, "
            "added_by, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (folder_id, vid, share, rel_path, next_ord, added_by, now),
        )
        present.add(vid)
        present_names.add((share, rel_path))
        added.append(vid)
        next_ord += 1
    conn.execute("UPDATE client_folders SET updated_at = ? WHERE id = ?", (now, folder_id))
    conn.commit()
    return {"added": added, "already": already}


def _identity_of(index_conn: sqlite3.Connection | None, video_id: int) -> tuple[str, str]:
    """The (share, rel_path) the CURRENT index files `video_id` under, or a
    pair nothing matches.

    MEDIA-23 (resilience sweep 2026-08-28): the panel sends the id the index
    has NOW, which after a rebuild is not the id the item was stored under.
    An id-only match then answered "that clip is not in this folder" to an
    editor pulling a clip out of a live client link, while the client kept
    seeing it -- and the same for a note. The empty pair is deliberate: no
    row carries it, so a caller with no index connection (or a clip that has
    left the index) falls back to the id-only behaviour rather than matching
    everything (broll-1's family, sites four and five).
    """
    if index_conn is None:
        return "", ""
    row = index_conn.execute(
        "SELECT share, rel_path FROM videos WHERE id = ?", (video_id,)).fetchone()
    return (row["share"], row["rel_path"]) if row is not None else ("", "")


def remove_item(conn: sqlite3.Connection, folder_id: int, video_id: int,
                index_conn: sqlite3.Connection | None = None) -> bool:
    share, rel_path = _identity_of(index_conn, video_id)
    cur = conn.execute(
        "DELETE FROM client_folder_items WHERE folder_id = ? "
        "AND (video_id = ? OR (share = ? AND rel_path = ?))",
        (folder_id, video_id, share, rel_path),
    )
    conn.execute("UPDATE client_folders SET updated_at = ? WHERE id = ?",
                 (now_iso(), folder_id))
    conn.commit()
    return cur.rowcount > 0


def set_note(conn: sqlite3.Connection, folder_id: int, video_id: int, note: str,
             index_conn: sqlite3.Connection | None = None) -> bool:
    share, rel_path = _identity_of(index_conn, video_id)
    cur = conn.execute(
        "UPDATE client_folder_items SET note = ? WHERE folder_id = ? "
        "AND (video_id = ? OR (share = ? AND rel_path = ?))",
        (_clean_text(note, MAX_NOTE, "note"), folder_id, video_id, share, rel_path),
    )
    conn.commit()
    return cur.rowcount > 0


def reorder(conn: sqlite3.Connection, folder_id: int, video_ids: list[int]) -> None:
    """Set the display order to `video_ids`. Ids not listed keep their relative
    order after the listed ones; ids not in the folder are ignored -- so a
    stale panel that sends yesterday's list cannot delete anything."""
    current = [r["video_id"] for r in conn.execute(
        "SELECT video_id FROM client_folder_items WHERE folder_id = ? ORDER BY ord, id",
        (folder_id,))]
    listed = [int(v) for v in video_ids if int(v) in set(current)]
    seen = set(listed)
    final = listed + [v for v in current if v not in seen]
    for i, vid in enumerate(final):
        conn.execute(
            "UPDATE client_folder_items SET ord = ? WHERE folder_id = ? AND video_id = ?",
            (i, folder_id, vid))
    conn.execute("UPDATE client_folders SET updated_at = ? WHERE id = ?",
                 (now_iso(), folder_id))
    conn.commit()


def list_items(conn: sqlite3.Connection, folder_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM client_folder_items WHERE folder_id = ? ORDER BY ord, id",
        (folder_id,)).fetchall()


def member_video_id(conn: sqlite3.Connection, index_conn: sqlite3.Connection,
                    folder_id: int, video_id: int) -> bool:
    """True when the folder holds this id AND the index row still IS the clip
    that was curated under it.

    The (share, rel_path) re-check is not belt-and-braces. broll.db is
    REPLACED wholesale by an index build (server/publish_db.py), which
    renumbers videos.id, so a stored item id can come to name a completely
    different clip -- which is the whole reason items carry their name as well
    as their id and resolve_items re-resolves on it. This used to answer on
    the bare id, so the public media/detail routes served whatever clip had
    inherited the number to anyone holding the link, a clip nobody curated
    into that folder (broll-1, 2026-08-21).
    """
    item = conn.execute(
        "SELECT share, rel_path FROM client_folder_items "
        "WHERE folder_id = ? AND video_id = ?",
        (folder_id, video_id)).fetchone()
    if item is None:
        return False
    video = index_conn.execute(
        "SELECT share, rel_path FROM videos WHERE id = ?", (video_id,)).fetchone()
    return video is not None and \
        (video["share"], video["rel_path"]) == (item["share"], item["rel_path"])


# The columns of `videos` that leave the building. Deliberately a list, not
# `SELECT *`: `rel_path`, `archive_path`, `original_path` and `share` describe
# the NAS's directory layout and are nobody's business but ours; `hash`,
# `status`, `error`, `duplicate_of` are pipeline internals. What is left is
# what a client needs to judge a clip -- length, frame size, rate, when it was
# shot -- plus the sprite geometry the hover-scrub cannot work without.
PUBLIC_VIDEO_COLUMNS = (
    "id", "duration_s", "fps", "width", "height", "codec", "shot_date",
    "sprite_cell_w", "sprite_cell_h", "sprite_cols", "sprite_cells", "sprite_interval_s",
)


def resolve_items(conn: sqlite3.Connection, index_conn: sqlite3.Connection,
                  folder_id: int, public: bool) -> list[dict]:
    """The folder's clips joined with what broll.db knows about them, in order.

    `public=True` returns only PUBLIC_VIDEO_COLUMNS plus a display `name` (the
    file's basename, sans extension -- the one bit of the path a client may
    see, because it is what the editor named the shot); `public=False` adds
    rel_path/share/category for the curator's own list. Either way an item
    whose stored id no longer names the clip it was curated as -- gone from the
    index, or renumbered so the id belongs to something else -- is re-resolved
    by (share, rel_path), which is how an archive rebuilt with new ids keeps
    its folders; and one that cannot be found BY NAME is DROPPED rather than
    shown as a broken card or, worse, served as whatever inherited its number
    (the panel reports it as `missing`, the public page never sees it).
    """
    out = []
    # Two items can resolve to ONE clip: a folder written before 2026-08-21
    # could take a second row for a clip whose id a rebuild had changed
    # (broll-4), and the client's page then showed the card twice. add_items
    # cannot make one any more; this is what the folders that already have one
    # look like. The first item wins, so the curator's order and note are the
    # ones they set; removing it from the panel reveals the other.
    seen: set[int] = set()
    for item in list_items(conn, folder_id):
        video = index_conn.execute(
            "SELECT * FROM videos WHERE id = ?", (item["video_id"],)).fetchone()
        if video is None or (video["share"], video["rel_path"]) != (item["share"], item["rel_path"]):
            # MEDIA-1 (resilience sweep 2026-08-28): the by-id row is NOT a
            # fallback. When the identity disagrees the id names some other
            # clip -- a rebuild reuses low ids -- and keeping it here put that
            # clip in public_video_ids, which is what _member_id authorises
            # on, so the client's page drew and streamed footage nobody
            # curated (the fourth site of broll-1, which fixed the other
            # three). By name or not at all: None below drops the item, and
            # the curator's panel reports it `missing`.
            video = index_conn.execute(
                "SELECT * FROM videos WHERE share = ? AND rel_path = ?",
                (item["share"], item["rel_path"])).fetchone()
        if video is None:
            if not public:
                out.append({"video_id": item["video_id"], "share": item["share"],
                            "rel_path": item["rel_path"], "note": item["note"],
                            "missing": True})
            continue
        if video["id"] in seen:
            continue
        seen.add(video["id"])
        v = dict(video)
        entry = {k: v.get(k) for k in PUBLIC_VIDEO_COLUMNS}
        # The card's id and media URLs follow the CURRENT index row -- which
        # may differ from item.video_id after a rebuild -- because that is the
        # id /media/proxy answers to.
        entry["id"] = v["id"]
        entry["name"] = _display_name(v["rel_path"])
        entry["note"] = item["note"]
        if not public:
            entry["video_id"] = item["video_id"]
            entry["share"] = v["share"]
            entry["rel_path"] = v["rel_path"]
            entry["category"] = v.get("category") or v.get("category_hint")
            entry["missing"] = False
        out.append(entry)
    return out


def _display_name(rel_path: str) -> str:
    base = (rel_path or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return stem or base or "clip"


def public_video_ids(conn: sqlite3.Connection, index_conn: sqlite3.Connection,
                     folder_id: int) -> set[int]:
    """The CURRENT index ids the public media routes may serve for this
    folder. Same re-resolution as resolve_items, so a rebuilt archive's
    thumbnails and previews keep working from the same link."""
    return {e["id"] for e in resolve_items(conn, index_conn, folder_id, public=True)}


def record_view(conn: sqlite3.Connection, folder_id: int) -> None:
    conn.execute(
        "UPDATE client_folders SET view_count = view_count + 1, last_viewed_at = ? "
        "WHERE id = ?", (now_iso(), folder_id))
    conn.commit()


# --- settings ------------------------------------------------------------------------

def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM client_share_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO client_share_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()


def clean_public_base(value: str | None) -> str:
    """The public origin as it will be stored: scheme://host[:port], no path,
    no trailing slash. Blank clears it. Anything that is not an http(s) origin
    is refused -- the value is spliced into every link the studio sends out."""
    text = (value or "").strip().rstrip("/")
    if not text:
        return ""
    m = re.match(r"^(https?)://([A-Za-z0-9.-]+)(:\d{1,5})?$", text)
    if not m:
        raise ClientFolderError(
            "the public base must be an origin like https://nas.example.ts.net:8443 "
            "(scheme and host, an optional port, no path)")
    return text
