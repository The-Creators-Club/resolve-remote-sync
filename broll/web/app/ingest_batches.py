"""The b-roll ingest ledger: everything that writes `ingest_batches`/`ingest_items`.

docs/BROLL_INGEST_PLAN.md §2 (data model) and §4.2/§4.3 (the two APIs over it),
2026-08-18. `routes_batches.py` is the browser's half and `routes_fleet.py` the
companion's; both are thin, and every rule that decides what a batch or an item
may become is here, once.

THREE THINGS THIS MODULE EXISTS TO GUARANTEE, none of which either caller can:

  1. **The name is allocated by the database, in one transaction.** Two editors
     dropping the same camera card into the same shoot on two machines would
     both pick `A001_C003`; the second upload would land on a file already
     recorded on another row and already cut into somebody's timeline. That is
     BROLL-IDX-5 with a second machine instead of a second run, and the fix is
     the same one build_archive learned: settle collisions against CLAIMED
     names, never against what is on disk.

  2. **A `videos` row is only as real as the media behind it.** Rows are minted
     at claim with `status='ingesting'`, which browse, tree and search all
     exclude, and they become visible only when `mark_uploaded` has `stat()`ed
     the files under `BROLL_DATA_ROOT` and found the sizes the companion
     declared. The server never takes "I uploaded it" for an answer -- the
     archive root IS a directory it can read, so it reads it.

  3. **Nothing is in-memory-only.** A stage that lives in a companion's process
     is a stage that restarts from zero after a reboot, and a batch that lives
     there is one nobody can cancel. Same rule as the sync lanes' latches
     (docs/SYNC_SAFETY.md).

Refusals are raised as HTTPException with the exact bodies §4.2/§4.3 promise --
the shape of a 409 is part of the contract the companion retries against, so it
belongs next to the rule that produces it, not in a route that re-invents it.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import HTTPException

from app import config, normalize
from app.archive_names import claim_key, claim_name, safe_name, split_stem
from app.db import bump_search_generation

log = logging.getLogger("broll.ingest_batches")

# --- state machines (plan §2) -------------------------------------------------

BATCH_STATES = ("queued", "claimed", "running", "done", "done_with_errors",
                "cancelled", "failed")
# A batch in one of these is over: no lease, no more work, and every fleet call
# against it answers 410 (see routes_fleet._leaseholder_or_410).
BATCH_TERMINAL = frozenset({"done", "done_with_errors", "cancelled", "failed"})

# The one legal route through a clip, in order. `stage_percent` re-posts of the
# SAME state are allowed (that is how progress is reported); going backwards is
# not, or a late-arriving retry of an earlier POST would un-index a clip that
# has already been described.
ITEM_PROGRESS = ("pending", "proxying", "framing", "describing", "indexed",
                 "uploading", "live")
_ITEM_ORDER = {name: i for i, name in enumerate(ITEM_PROGRESS)}
# Ends the item, whatever it was doing. `failed` is the ONE terminal state that
# can be left again (retry, plan §2), because a proxy that did not decode is
# worth a second attempt and a cancelled batch is not.
ITEM_ENDINGS = ("duplicate", "failed", "cancelled", "skipped")
ITEM_STATES = ITEM_PROGRESS + ITEM_ENDINGS
ITEM_TERMINAL = frozenset({"live", "duplicate", "cancelled", "skipped"})
# What "nothing left to do with this clip" means, for n_done.
ITEM_FINISHED = ITEM_TERMINAL | {"failed"}

# The status a `videos` row wears between its claim and its upload. Excluded
# from browse/tree/search exactly as 'skipped'/'excluded' are (app/search.py
# BROWSE_PREDICATE): the row exists so the name is reserved and the segments
# have somewhere to land, but there is no proxy, poster or sprite on the NAS
# yet, so browsing it would be a broken thumbnail.
VIDEO_STATUS_INGESTING = "ingesting"

# The `Proxy/` level every archived preview sits under, and the reason lane B
# syncs archive media to editors at all (build_archive's PROXY_DIR: lane B
# takes `**/Proxy/**` down, lane A excludes it going up).
PROXY_DIR = "Proxy"

MAX_ITEMS = 2000

# Settings the create route accepts. Kept here rather than in schemas.py
# because the fleet manifest hands the same blob straight to the companion, and
# a value this end has never heard of would be a work order nobody can execute.
TIERS = ("good", "best")
# Owner review, 2026-08-18: "start now" became a run MODE beside the tier.
# 'idle' is the proxy generator's behaviour (runs when the editor is away,
# pauses when they come back); 'foreground' ignores the idle and Resolve-open
# gates -- free space, drive and model gates still apply.
RUN_MODES = ("idle", "foreground")


class ItemFiles:
    """The three (or four) archive-relative paths one finished item occupies.

    Named rather than passed around as a tuple because `mark_uploaded` verifies
    them and `claim` advertises them, and the two must not drift.
    """

    def __init__(self, archive_dir: str, archive_stem: str, final_name: str,
                 video_id: int | None) -> None:
        self.proxy = f"{archive_dir}/{PROXY_DIR}/{archive_stem}.mp4"
        self.original = f"{archive_dir}/{final_name}"
        self.poster = f"posters/{video_id}.jpg" if video_id else None
        self.sprite = f"sprites/{video_id}.jpg" if video_id else None


# --- small helpers ------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def new_uid(conn: sqlite3.Connection) -> str:
    """A 32-hex-character id, minted by SQLite's own CSPRNG.

    `lower(hex(randomblob(16)))` (the music 003 precedent) rather than an
    autoincrement: these ids travel through a browser and a loopback POST, and
    a guessable integer would let any logged-in editor enumerate -- or drive --
    another editor's batch. 128 bits is also what the dashboard's login_gate
    carve-out regex pins, so the shape is load-bearing.
    """
    return conn.execute("SELECT lower(hex(randomblob(16)))").fetchone()[0]


def lease_live(batch: sqlite3.Row | dict, now: datetime | None = None) -> bool:
    expires = _parse_iso(batch["lease_expires_at"])
    if expires is None:
        return False
    return expires > (now or datetime.now(timezone.utc))


def load_settings(batch: sqlite3.Row | dict) -> dict:
    """The settings blob as a dict, never an exception.

    A batch whose JSON cannot be parsed is a batch the SPA can still list and
    cancel; refusing to render it would strand it. The fleet manifest is the
    one caller that would rather know, and validate_settings has already run on
    the way in, so this only fires on hand-edited rows.
    """
    try:
        parsed = json.loads(batch["settings_json"] or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def validate_settings(raw: Any) -> dict:
    """The settings the batch will actually run under, or 422.

    Validated here and not left to the companion: a tier nobody has heard of
    means a model nobody can download, and the machine would sit in
    `waiting-for-model` forever with the editor watching a progress bar that
    never starts.
    """
    if not isinstance(raw, dict):
        raise HTTPException(422, "settings must be an object")
    tier = str(raw.get("tier") or "good").strip().lower()
    if tier not in TIERS:
        raise HTTPException(422, f"tier must be one of {', '.join(TIERS)}")
    run_mode = str(raw.get("run_mode") or "idle").strip().lower()
    if run_mode not in RUN_MODES:
        raise HTTPException(422, f"run_mode must be one of {', '.join(RUN_MODES)}")
    if raw.get("transcribe"):
        # Phase 2 (whisper.cpp sidecar). Refused rather than silently ignored:
        # an editor who ticked it would otherwise wait for speech search that
        # is never coming and conclude the transcription is broken.
        raise HTTPException(422, "transcription is not available yet (phase 2)")
    return {
        "tier": tier,
        "run_mode": run_mode,
        "upload_originals": bool(raw.get("upload_originals", True)),
        "keep_subfolders": bool(raw.get("keep_subfolders", True)),
        "transcribe": False,
    }


def _clean_rel_dir(raw: Any) -> str:
    """A sub-folder path below the shoot root: forward slashes, sanitised, no
    way out of the tree.

    Every component goes through safe_name, and `.`/`..` are dropped outright.
    This value ends up in an archive path a companion hands to rclone, so a
    `../../` here would be an upload anywhere on the NAS.
    """
    text = str(raw or "").replace("\\", "/")
    parts = [safe_name(p) for p in text.split("/") if p and p not in (".", "..")]
    return "/".join(parts)


def archive_dir_for(share: str, rel_dir: str) -> str:
    """`Creators_Club/<shoot>/<sub folders>` -- where this clip's media lands.

    Mirrors indexer `build_archive.dest_dir` for an own-footage share exactly,
    because it IS the same tree: what an editor sees in the search UI has to be
    where the file actually is, and lane B's `**/Proxy/**` rule is what carries
    it to them. The top-level folder name is site data (config's
    get_archive_creators_dir), the rest is the shoot's own structure.
    """
    parts = [config.get_archive_creators_dir(), safe_name(share)]
    parts += [p for p in rel_dir.split("/") if p]
    return "/".join(parts)


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _taken_names(conn: sqlite3.Connection, share: str, rel_dir: str,
                 archive_dir: str) -> set[str]:
    """Every name already spoken for in that archive folder.

    TWO sources, and both are needed:

      - published `archive_path`s under `<archive_dir>/` (their own and their
        `Proxy/` preview's, folded to one claim key by claim_key, which is the
        BROLL-IDX-5 lesson);
      - `videos.rel_path` in the same (share, rel_dir), which catches a row
        that has been claimed but not yet uploaded -- it has no archive_path at
        all yet, and without this a second batch would allocate the same stem
        and then fail the UNIQUE(share, rel_path) constraint mid-claim.
    """
    taken: set[str] = set()

    pattern = _like_escape(archive_dir) + "/%"
    for row in conn.execute(
        "SELECT archive_path FROM videos WHERE archive_path LIKE ? ESCAPE '\\'",
        (pattern,),
    ):
        p = PurePosixPath(row["archive_path"])
        parent = p.parent
        if parent.name == PROXY_DIR:
            parent = parent.parent
        if str(parent) == archive_dir:
            taken.add(claim_key(archive_dir, p.stem))

    if rel_dir:
        esc = _like_escape(rel_dir)
        rows = conn.execute(
            "SELECT rel_path FROM videos WHERE share = ? AND rel_path LIKE ? ESCAPE '\\' "
            "AND rel_path NOT LIKE ? ESCAPE '\\'",
            (share, f"{esc}/%", f"{esc}/%/%"),
        )
    else:
        rows = conn.execute(
            "SELECT rel_path FROM videos WHERE share = ? AND rel_path NOT LIKE '%/%'",
            (share,),
        )
    for row in rows:
        taken.add(claim_key(archive_dir, PurePosixPath(row["rel_path"]).stem))
    return taken


def _allocate(conn: sqlite3.Connection, share: str, rel_dir: str, orig_name: str,
              cache: dict[str, set[str]]) -> tuple[str, str, str]:
    """-> (archive_dir, archive_stem, final_name), reserving the name in `cache`.

    `cache` is per-call and keyed by archive_dir, so the folder is read from
    `videos` once however many clips of one drop land in it, and each
    allocation is immediately visible to the next -- which is what stops two
    items of the SAME batch claiming one slot.
    """
    archive_dir = archive_dir_for(share, rel_dir)
    if archive_dir not in cache:
        cache[archive_dir] = _taken_names(conn, share, rel_dir, archive_dir)
    stem, ext = split_stem(orig_name)
    archive_stem = claim_name(archive_dir, safe_name(stem), cache[archive_dir])
    # safe_name("") is "untitled" by design (a clip must always get A name), so
    # an extensionless drop must not be run through it or `A001` would become
    # `A001untitled`.
    return archive_dir, archive_stem, archive_stem + (safe_name(ext, cap=32) if ext else "")


def rel_path_for(rel_dir: str, final_name: str) -> str:
    """The clip's ingest identity: `<rel_dir>/<final_name>`, forward slashes.

    NOT the archive path. `videos.rel_path` records where the footage came from
    inside its share -- the shoot's own day/camera structure -- and
    `archive_path` records where the preview was published. Conflating them is
    what sent the base rig's insert path at a `Z:\\` drive nobody else had
    (2026-08-12).
    """
    return f"{rel_dir}/{final_name}" if rel_dir else final_name


# --- reading ------------------------------------------------------------------

def get_batch(conn: sqlite3.Connection, uid: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM ingest_batches WHERE uid = ?", (uid,)).fetchone()


def get_item(conn: sqlite3.Connection, batch_uid: str, item_uid: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM ingest_items WHERE uid = ? AND batch_uid = ?",
        (item_uid, batch_uid),
    ).fetchone()


def list_items(conn: sqlite3.Connection, batch_uid: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM ingest_items WHERE batch_uid = ? ORDER BY ord, uid", (batch_uid,)
    ).fetchall()


def batch_public(batch: sqlite3.Row) -> dict:
    """One batch as both APIs report it. Scalars only: this is polled every few
    seconds by the SPA and rides the fleet grid, and a nested blob here becomes
    a payload the reporter has to shed."""
    out = {k: batch[k] for k in batch.keys() if k != "settings_json"}
    out["settings"] = load_settings(batch)
    out["cancel_requested"] = bool(batch["cancel_requested"])
    out["upload_paused"] = bool(batch["upload_paused"])
    return out


def item_public(item: sqlite3.Row) -> dict:
    out = {k: item[k] for k in item.keys()}
    out["original_uploaded"] = bool(item["original_uploaded"])
    return out


def list_batches(conn: sqlite3.Connection, editor: str | None = None,
                 limit: int = 200) -> list[dict]:
    """Newest first. `editor=None` is the admin's "all machines" view; every
    other caller passes a name, because a batch names the machine an editor is
    sitting at and that is nobody else's business."""
    sql = "SELECT * FROM ingest_batches"
    params: list[Any] = []
    if editor is not None:
        sql += " WHERE editor = ?"
        params.append(editor)
    sql += " ORDER BY created_at DESC, uid DESC LIMIT ?"
    params.append(limit)
    return [batch_public(r) for r in conn.execute(sql, params).fetchall()]


def taxonomy(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in
            conn.execute("SELECT slug, label, description FROM categories ORDER BY slug")]


# --- counters -----------------------------------------------------------------

def _recount(conn: sqlite3.Connection, batch_uid: str) -> dict[str, int]:
    """Counters recomputed from the items, never incremented.

    An increment is one lost/duplicated POST away from a batch that says 39 of
    40 forever, and the item table is at most 2000 rows -- the read costs less
    than the bug does.
    """
    rows = conn.execute(
        "SELECT state, COUNT(*) n FROM ingest_items WHERE batch_uid = ? GROUP BY state",
        (batch_uid,),
    ).fetchall()
    by_state = {r["state"]: r["n"] for r in rows}
    counts = {
        "n_items": sum(by_state.values()),
        "n_done": sum(n for s, n in by_state.items() if s in ITEM_FINISHED),
        "n_failed": by_state.get("failed", 0),
        "n_live": by_state.get("live", 0),
        "n_duplicate": by_state.get("duplicate", 0),
    }
    conn.execute(
        "UPDATE ingest_batches SET n_items = ?, n_done = ?, n_failed = ?, n_live = ?, "
        "n_duplicate = ?, updated_at = ? WHERE uid = ?",
        (counts["n_items"], counts["n_done"], counts["n_failed"], counts["n_live"],
         counts["n_duplicate"], now_iso(), batch_uid),
    )
    return counts


# --- create + precheck (the SPA's half) ---------------------------------------

def precheck(conn: sqlite3.Connection, *, share: str, keep_subfolders: bool,
             items: list[Any]) -> list[dict]:
    """Per item: is it already in the archive, and what will it be called?

    Read-only and allocates NOTHING permanent -- it runs while the editor is
    still ticking boxes, and a name reserved here would be a name leaked by
    every abandoned drop. The real allocation happens inside the claim
    transaction; this is a preview of it, and the SPA says so ("final name").
    """
    cache: dict[str, set[str]] = {}
    out: list[dict] = []
    for item in items:
        rel_dir = _clean_rel_dir(item.rel_dir if keep_subfolders else "")
        _dir, _stem, final_name = _allocate(conn, share, rel_dir, item.name, cache)
        duplicate_of = None
        duplicate_name = None
        if item.hash:
            # `videos.hash` is xxh64(first 8MiB + last 8MiB + size) -- a
            # CANDIDATE match, which is all a pre-check should claim
            # (migrations/005 is explicit that only full_hash confirms one).
            # The editor is shown it and decides; nothing is skipped for them.
            row = conn.execute(
                "SELECT id, rel_path, archive_path FROM videos "
                "WHERE hash = ? AND status != 'ingesting' ORDER BY id LIMIT 1",
                (item.hash,),
            ).fetchone()
            if row is not None:
                duplicate_of = row["id"]
                source = row["archive_path"] or row["rel_path"]
                duplicate_name = PurePosixPath(source).name
        out.append({
            "local_id": item.local_id,
            "duplicate_of": duplicate_of,
            "duplicate_name": duplicate_name,
            "final_name": final_name,
        })
    return out


def create_batch(conn: sqlite3.Connection, *, editor: str, share: str,
                 collection: str, settings: dict, items: list[Any]) -> str:
    """Mint a queued batch and its items. Returns the batch uid.

    No `videos` rows and no names are allocated here -- see claim. A batch that
    no machine ever picks up must leave nothing behind but a row the editor can
    see and delete, which is the difference between "queued" meaning "waiting"
    and it meaning "half in the library".
    """
    if not items:
        raise HTTPException(422, "a batch needs at least one item")
    if len(items) > MAX_ITEMS:
        raise HTTPException(422, f"a batch may hold at most {MAX_ITEMS} clips "
                                 f"({len(items)} were sent)")
    keep_subfolders = bool(settings.get("keep_subfolders", True))
    created = now_iso()
    uid = new_uid(conn)
    with conn:
        conn.execute(
            "INSERT INTO ingest_batches (uid, editor, share, collection, settings_json, "
            "state, n_items, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
            (uid, editor, share, collection, json.dumps(settings, sort_keys=True),
             len(items), created, created),
        )
        for ord_, item in enumerate(items):
            conn.execute(
                "INSERT INTO ingest_items (uid, batch_uid, ord, orig_name, rel_dir, "
                "size_bytes, hash, source, duplicate_of, state, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (new_uid(conn), uid, ord_, item.name,
                 # Blanked at CREATE when the editor unticked "keep
                 # sub-folders", so nothing downstream has to consult the
                 # settings blob to know where a clip belongs.
                 _clean_rel_dir(item.rel_dir if keep_subfolders else ""),
                 item.size, item.hash or None, item.source, item.duplicate_of, created),
            )
    log.info("b-roll ingest: %s queued batch %s (%d clips, share %r)",
             editor, uid, len(items), share)
    return uid


def cancel(conn: sqlite3.Connection, uid: str, by: str) -> None:
    """Ask for a stop, and take the lease away in the same breath.

    A REQUEST, not a kill (plan §2): the companion is mid-ffmpeg somewhere and
    learns about this on its next heartbeat (410) or from the report reply,
    then stops and releases. Flipping the row straight to `cancelled` here
    would leave a machine crunching a batch the server has forgotten -- and,
    worse, uploading into archive paths nothing has reserved any more.

    Expiring the lease at the same time is what makes the NEXT fleet call 410
    even if the heartbeat is the call that lands first; the two checks are
    belt and braces (YTDL-WEB-1's lesson, 2026-08-14).
    """
    with conn:
        conn.execute(
            "UPDATE ingest_batches SET cancel_requested = 1, cancel_by = ?, "
            "lease_expires_at = NULL, updated_at = ? WHERE uid = ?",
            (by, now_iso(), uid),
        )
    log.info("b-roll ingest: batch %s cancel requested by %s", uid, by)


def set_upload_paused(conn: sqlite3.Connection, uid: str, paused: bool) -> None:
    with conn:
        conn.execute(
            "UPDATE ingest_batches SET upload_paused = ?, updated_at = ? WHERE uid = ?",
            (1 if paused else 0, now_iso(), uid),
        )


def cancel_requested_for(conn: sqlite3.Connection, editor: str,
                         machine: str | None) -> list[str]:
    """Batch uids this editor+machine should stop, for the report reply.

    The dashboard's report handler calls this and puts the answer in
    `commands.broll_ingest` (PR-I), which is the SECOND way a companion learns
    about a cancel -- the first being a 410 on its next heartbeat. Two channels
    because the heartbeat can be up to 30 s away and the report tick is
    already happening; and because a companion whose NAS calls are failing
    still reports.

    Best-effort by contract: it must never fail a report. A pre-011 database
    has no such table and gets an empty list.
    """
    try:
        placeholders = ", ".join("?" for _ in BATCH_TERMINAL)
        params: list[Any] = [editor, *sorted(BATCH_TERMINAL)]
        sql = ("SELECT uid FROM ingest_batches WHERE cancel_requested = 1 "
               f"AND editor = ? AND state NOT IN ({placeholders})")
        if machine:
            sql += " AND (machine IS NULL OR machine = ?)"
            params.append(machine)
        return [r["uid"] for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []


# --- leases (the companion's half) --------------------------------------------

def expire_stale_leases(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """Hand back every batch whose machine stopped talking. Returns how many.

    Back to `queued`, not to a terminal state: the work is still wanted, and
    the same editor's companion (that machine on restart, or another of theirs)
    re-claims it and resumes from the items' own recorded stages. `machine` is
    deliberately LEFT in place so the SPA can still say "waiting for
    <machine>".

    Called opportunistically from list and claim rather than on a timer,
    because this app has no timer: the dashboard runs uvicorn with workers=1
    and a background thread here would be a thread the fleet status page waits
    behind.

    The comparison is a STRING one, which is only sound because every
    `lease_expires_at` in this table is written by this module as a UTC
    `datetime.isoformat()` -- same offset, same field widths, so lexical order
    is chronological order. Nothing else writes that column; if anything ever
    does, it writes it that way or this stops working silently.
    """
    cutoff = (now or datetime.now(timezone.utc)).isoformat()
    with conn:
        cur = conn.execute(
            "UPDATE ingest_batches SET state = 'queued', lease_expires_at = NULL, "
            "current_item_uid = NULL, updated_at = ? "
            "WHERE state IN ('claimed', 'running') AND lease_expires_at IS NOT NULL "
            "AND lease_expires_at < ?",
            (now_iso(), cutoff),
        )
    if cur.rowcount:
        log.info("b-roll ingest: %d batch lease(s) expired and went back to queued",
                 cur.rowcount)
    return cur.rowcount


def claim(conn: sqlite3.Connection, *, batch_uid: str, editor: str, machine: str,
          companion_version: str, tier: str, capabilities: Any) -> dict:
    """Take the batch, mint its `videos` rows, allocate its names. One txn.

    IDEMPOTENT for the machine that already holds it: a companion restarting
    mid-batch re-issues exactly this call, and it must get the same manifest
    back rather than a second set of rows and a second set of `_2` names. That
    is why an item with a `video_id` already on it is left completely alone.

    Refusals (§4.2): 403 the verified identity is not this batch's editor --
    the one thing here that is NOT 410, because it means "wrong credentials",
    not "your claim is over"; 409 another of this editor's machines holds a
    live lease; 410 the batch is cancelled or finished.
    """
    expire_stale_leases(conn)
    batch = get_batch(conn, batch_uid)
    if batch is None:
        raise HTTPException(404, "no such batch")
    if batch["editor"] != editor:
        raise HTTPException(403, {
            "detail": "this batch belongs to another editor",
            "reason": "identity"})
    if batch["cancel_requested"] and (batch["state"] not in BATCH_TERMINAL
                                      or batch["state"] == "cancelled"):
        raise HTTPException(410, {"detail": "this batch has been cancelled",
                                  "reason": "cancelled"})
    if batch["state"] in BATCH_TERMINAL:
        raise HTTPException(410, {"detail": f"this batch is {batch['state']}",
                                  "reason": "finished", "state": batch["state"]})
    if batch["machine"] and batch["machine"] != machine and lease_live(batch):
        raise HTTPException(409, {
            "detail": f"{batch['machine']} is already indexing this batch",
            "machine": batch["machine"],
            "lease_expires_at": batch["lease_expires_at"]})

    settings = load_settings(batch)
    now = now_iso()
    expires = (datetime.now(timezone.utc)
               + timedelta(seconds=config.LEASE_SECONDS)).isoformat()
    cache: dict[str, set[str]] = {}
    try:
        with conn:
            for item in list_items(conn, batch["uid"]):
                if item["video_id"] is not None or item["state"] in ITEM_TERMINAL:
                    continue
                archive_dir, archive_stem, final_name = _allocate(
                    conn, batch["share"], item["rel_dir"], item["orig_name"], cache)
                cur = conn.execute(
                    "INSERT INTO videos (share, rel_path, hash, size_bytes, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (batch["share"], rel_path_for(item["rel_dir"], final_name),
                     item["hash"], item["size_bytes"], VIDEO_STATUS_INGESTING),
                )
                conn.execute(
                    "UPDATE ingest_items SET video_id = ?, archive_dir = ?, "
                    "archive_stem = ?, updated_at = ? WHERE uid = ?",
                    (cur.lastrowid, archive_dir, archive_stem, now, item["uid"]),
                )
            # The share's own row. `source='originals'` because that is what an
            # ingested camera clip IS -- and precisely why `collection` had to
            # exist: creators_shares() derives own-footage membership from
            # source='proxies', so without this column a customer's own shoot
            # would file itself under Downloads (migrations/011).
            conn.execute(
                "INSERT INTO share_roots (share, root, source, description, indexed, "
                "collection, updated_at) VALUES (?, ?, 'originals', ?, 1, ?, ?) "
                "ON CONFLICT(share) DO UPDATE SET collection = excluded.collection, "
                "updated_at = excluded.updated_at",
                (batch["share"], f"ingest:{batch['uid']}",
                 f"dashboard ingest by {editor}", batch["collection"], now),
            )
            conn.execute(
                "UPDATE ingest_batches SET state = CASE WHEN state = 'running' "
                "THEN 'running' ELSE 'claimed' END, machine = ?, companion_version = ?, "
                "claimed_at = COALESCE(claimed_at, ?), lease_expires_at = ?, "
                "last_heartbeat_at = ?, error = NULL, updated_at = ? WHERE uid = ?",
                (machine, companion_version, now, expires, now, now, batch["uid"]),
            )
            _recount(conn, batch["uid"])
    except sqlite3.IntegrityError as exc:
        # Overwhelmingly UNIQUE(share, rel_path): another batch claimed a name
        # between _taken_names and the INSERT. The companion retries the whole
        # claim, which re-reads the folder and allocates around it.
        log.warning("b-roll ingest: claim of %s hit a constraint: %s", batch_uid, exc)
        raise HTTPException(409, {
            "detail": "another batch claimed one of these names first; retry",
            "reason": "name_race"}) from exc

    log.info("b-roll ingest: %s claimed batch %s on %s (companion %s, tier %s)",
             editor, batch_uid, machine, companion_version, tier)
    fresh = get_batch(conn, batch_uid)
    rows = list_items(conn, batch_uid)
    # One query, not one per clip: a 2000-clip drop would otherwise be 2000
    # round trips inside a request the fleet status page waits behind
    # (uvicorn workers=1).
    rel_paths = {
        r["id"]: r["rel_path"] for r in conn.execute(
            "SELECT v.id, v.rel_path FROM videos v JOIN ingest_items i "
            "ON i.video_id = v.id WHERE i.batch_uid = ?", (batch_uid,))
    }
    items = []
    for item in rows:
        rel_path = rel_paths.get(item["video_id"]) if item["video_id"] else None
        items.append({
            "uid": item["uid"], "ord": item["ord"], "orig_name": item["orig_name"],
            "rel_dir": item["rel_dir"], "size_bytes": item["size_bytes"],
            "hash": item["hash"], "video_id": item["video_id"],
            "share": fresh["share"], "rel_path": rel_path,
            "archive_dir": item["archive_dir"], "archive_stem": item["archive_stem"],
            "state": item["state"], "duplicate_of": item["duplicate_of"],
            "source": item["source"], "attempts": item["attempts"],
        })
    return {
        "batch": batch_public(fresh),
        "settings": settings,
        "lease_seconds": config.LEASE_SECONDS,
        "heartbeat_seconds": config.HEARTBEAT_SECONDS,
        # Where the archive is ON THE REMOTE, relative to the rclone remote's
        # root -- never a local path. Only the companion knows what that root
        # is mapped to on the machine it is running on, exactly as
        # /music/send's contract has it (never trust the page with paths, and
        # never tell the server about drive letters).
        "archive_remote_rel": "Assets/B-roll Archive",
        "taxonomy": taxonomy(conn),
        "items": items,
    }


def _video_rel_path(conn: sqlite3.Connection, video_id: int | None) -> str | None:
    if not video_id:
        return None
    row = conn.execute("SELECT rel_path FROM videos WHERE id = ?", (video_id,)).fetchone()
    return row["rel_path"] if row else None


def heartbeat(conn: sqlite3.Connection, batch: sqlite3.Row) -> dict:
    """Extend the lease. Answers with the two flags the companion acts on."""
    expires = (datetime.now(timezone.utc)
               + timedelta(seconds=config.LEASE_SECONDS)).isoformat()
    now = now_iso()
    with conn:
        conn.execute(
            "UPDATE ingest_batches SET lease_expires_at = ?, last_heartbeat_at = ?, "
            "updated_at = ? WHERE uid = ?",
            (expires, now, now, batch["uid"]),
        )
    fresh = get_batch(conn, batch["uid"])
    return {"ok": True, "cancel_requested": bool(fresh["cancel_requested"]),
            "upload_paused": bool(fresh["upload_paused"]),
            "lease_expires_at": fresh["lease_expires_at"],
            "lease_seconds": config.LEASE_SECONDS}


# --- per-item transitions ------------------------------------------------------

def _check_transition(old: str, new: str) -> None:
    """Monotonic, with exactly one way back: `failed` -> retry (plan §2).

    Enforced server-side because the companion is not the only writer of an
    item's stage -- a cancel writes it too -- and because a retried POST that
    arrives late must not un-index a clip that has since been described. 400,
    not 409: the companion sent something illegal, and telling it which two
    states is what makes that debuggable from a log line.
    """
    if new not in ITEM_STATES:
        raise HTTPException(400, f"unknown item state {new!r}")
    if old == new:
        return
    if new in ITEM_ENDINGS:
        if old in ITEM_TERMINAL:
            raise HTTPException(400, {
                "detail": f"item is already {old}; it cannot become {new}",
                "reason": "illegal_transition", "state": old})
        return
    if old == "failed":
        return  # retry
    if old in ITEM_TERMINAL:
        raise HTTPException(400, {
            "detail": f"item is already {old}; it cannot become {new}",
            "reason": "illegal_transition", "state": old})
    if _ITEM_ORDER[new] < _ITEM_ORDER[old]:
        raise HTTPException(400, {
            "detail": f"an item cannot go back from {old} to {new}",
            "reason": "illegal_transition", "state": old})


def set_item_state(conn: sqlite3.Connection, batch: sqlite3.Row, item: sqlite3.Row, *,
                   state: str, stage_percent: int | None = None,
                   error: str | None = None, attempts: int | None = None,
                   hash: str | None = None, probe: dict | None = None) -> dict:
    """Record where a clip has got to, and drag the batch along with it."""
    _check_transition(item["state"], state)
    now = now_iso()
    with conn:
        conn.execute(
            "UPDATE ingest_items SET state = ?, stage_percent = ?, "
            "error = COALESCE(?, error), attempts = COALESCE(?, attempts), "
            "hash = COALESCE(?, hash), updated_at = ? WHERE uid = ?",
            (state, stage_percent, error, attempts, hash, now, item["uid"]),
        )
        if probe:
            _apply_probe(conn, item["uid"], item["video_id"], probe)
        # `running` is entered by the FIRST item that starts, not by the claim:
        # a batch that was claimed and then blocked on the idle gate for three
        # hours is honestly `claimed`, and the fleet grid says so.
        if state != "pending" and batch["state"] == "claimed":
            conn.execute(
                "UPDATE ingest_batches SET state = 'running', "
                "started_at = COALESCE(started_at, ?), updated_at = ? WHERE uid = ?",
                (now, now, batch["uid"]),
            )
        conn.execute(
            "UPDATE ingest_batches SET current_item_uid = ?, updated_at = ? WHERE uid = ?",
            (None if state in ITEM_FINISHED else item["uid"], now, batch["uid"]),
        )
        counts = _recount(conn, batch["uid"])
    return {"ok": True, "state": state, **counts}


_PROBE_COLUMNS = ("duration_s", "fps", "width", "height", "codec", "shot_date")


def _apply_probe(conn: sqlite3.Connection, item_uid: str, video_id: int | None,
                 probe: dict) -> None:
    """ffprobe's answers, onto both the item and (if minted) its video row.

    On the item because the SPA shows them before anything is live, and on the
    video because that row is what search filters and the player sizes itself
    from. COALESCE-free on purpose: the probe is authoritative and re-probing a
    clip is how a wrong duration gets corrected.
    """
    values = [probe.get(c) for c in _PROBE_COLUMNS]
    conn.execute(
        "UPDATE ingest_items SET " + ", ".join(f"{c} = COALESCE(?, {c})" for c in _PROBE_COLUMNS)
        + " WHERE uid = ?", [*values, item_uid])
    if video_id:
        conn.execute(
            "UPDATE videos SET " + ", ".join(f"{c} = COALESCE(?, {c})" for c in _PROBE_COLUMNS)
            + " WHERE id = ?", [*values, video_id])


def segment_search_text(seg: dict[str, Any]) -> str:
    """The text `search_norm` is built from, per SPEC.md's indexing output
    contract.

    Statement-for-statement the indexer's `pipeline._segment_search_text`
    (`tests/test_normalize_parity.py` pins the two together), and it takes the
    same shape it does there -- the DB ROW, whose `objects` is the ", "-joined
    string, not the wire format's list. Normalising the list instead would put
    brackets and quotes in the blob and jieba would happily segment them.

    The field set matters more than it looks: a blob built from a different one
    does not match badly, it matches NOTHING, so the same clip indexed on the
    base rig and on an editor's machine has to produce the same bytes.
    """
    parts = [
        seg.get("description") or "",
        seg.get("objects") or "",
        seg.get("setting") or "",
        seg.get("onscreen_text") or "",
        seg.get("onscreen_text_en") or "",
    ]
    return " ".join(p for p in parts if p)


def segment_norm(seg: Any, objects: str) -> str:
    """`search_norm` for one segment off the wire (a SegmentIn) plus the
    ", "-joined `objects` string that is about to be stored beside it.

    The one place both write paths -- this module's fleet `result` and
    routes_ingest's `/api/ingest/index` -- turn a request body into the blob,
    so the two cannot drift into two tokenisations of one archive.
    """
    return normalize.searchable_blob(segment_search_text({
        "description": seg.description,
        "objects": objects,
        "setting": seg.setting,
        "onscreen_text": seg.onscreen_text,
        "onscreen_text_en": seg.onscreen_text_en,
    }))


def write_item_result(conn: sqlite3.Connection, batch: sqlite3.Row, item: sqlite3.Row,
                      body: Any) -> dict:
    """What the model saw, written the way `/api/ingest/index` writes it -- plus
    the `search_norm` that endpoint could never compute.

    The segment/theme/flag replace is the same atomic delete-then-insert, with
    the same embeddings sweep (BROLL-13: `embeddings.source_id` points at
    segment rows with no foreign key, so a re-index left vectors for dead
    segments behind and semantic search went on scoring them) and the same
    in-transaction `bump_search_generation` (KNOWN_BUGS R2).

    What it does NOT do is set `videos.status = 'indexed'`. The clip is
    described but its media is still on the editor's laptop; the row goes
    visible in `mark_uploaded`, after the server has stat'ed the files.
    """
    if item["video_id"] is None:
        raise HTTPException(409, {"detail": "this item has no video row yet; re-claim",
                                  "reason": "unclaimed"})
    _check_transition(item["state"], "indexed")
    video_id = item["video_id"]
    now = now_iso()
    try:
        with conn:
            conn.execute(
                "DELETE FROM embeddings WHERE source = 'segment' AND video_id = ?",
                (video_id,))
            conn.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
            conn.execute("DELETE FROM themes WHERE video_id = ?", (video_id,))
            conn.execute("DELETE FROM quality_flags WHERE video_id = ?", (video_id,))

            for seg in body.segments:
                objects = ", ".join(seg.objects)
                conn.execute(
                    "INSERT INTO segments (video_id, t_start, t_end, description, objects, "
                    "setting, motion, onscreen_text, onscreen_text_en, search_norm) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (video_id, seg.t_start, seg.t_end, seg.description, objects,
                     seg.setting, seg.motion, seg.onscreen_text, seg.onscreen_text_en,
                     segment_norm(seg, objects)),
                )
            for theme in body.themes:
                conn.execute("INSERT INTO themes (video_id, text) VALUES (?, ?)",
                             (video_id, theme))
            for flag in body.quality_flags:
                conn.execute("INSERT INTO quality_flags (video_id, flag) VALUES (?, ?)",
                             (video_id, flag))

            conn.execute(
                "UPDATE videos SET category_hint = COALESCE(?, category_hint), "
                "indexed_at = ?, model = ?, "
                "sprite_cell_w = COALESCE(?, sprite_cell_w), "
                "sprite_cell_h = COALESCE(?, sprite_cell_h), "
                "sprite_cols = COALESCE(?, sprite_cols), "
                "sprite_cells = COALESCE(?, sprite_cells), "
                "sprite_interval_s = COALESCE(?, sprite_interval_s) WHERE id = ?",
                (body.category_hint, now, body.model, body.sprite_cell_w,
                 body.sprite_cell_h, body.sprite_cols, body.sprite_cells,
                 body.sprite_interval_s, video_id),
            )
            _apply_probe(conn, item["uid"], video_id, {
                c: getattr(body, c, None) for c in _PROBE_COLUMNS})
            conn.execute(
                "UPDATE ingest_items SET state = 'indexed', stage_percent = 100, "
                "error = NULL, updated_at = ? WHERE uid = ?", (now, item["uid"]))
            if batch["state"] == "claimed":
                conn.execute(
                    "UPDATE ingest_batches SET state = 'running', "
                    "started_at = COALESCE(started_at, ?), updated_at = ? WHERE uid = ?",
                    (now, now, batch["uid"]))
            # Inside the same transaction as the replace, deliberately: it is
            # the only thing that can tell the semantic/fuzzy caches about a
            # re-index landing the same number of rows on the same rowids.
            bump_search_generation(conn)
            counts = _recount(conn, batch["uid"])
    except sqlite3.IntegrityError as exc:
        raise HTTPException(400, f"invalid index result: {exc}") from exc
    return {"ok": True, "state": "indexed", "video_id": video_id, **counts}


# --- upload verification -------------------------------------------------------

def _resolve_under_root(rel: str) -> Path | None:
    """`<BROLL_DATA_ROOT>/<rel>`, or None if `rel` tries to leave it.

    The archive root IS this container's data root, which is what makes
    verification possible at all -- but it also means a `rel` off the wire is a
    path this process will stat, and one with `..` in it is a probe of the
    NAS's filesystem. Refused on the string AND on the resolved path: the
    string check catches the obvious, the containment check catches a symlink.
    """
    text = str(rel or "").replace("\\", "/").strip()
    if not text:
        return None
    pure = PurePosixPath(text)
    if pure.is_absolute() or any(p == ".." for p in pure.parts) or ":" in text:
        return None
    root = config.get_data_root()
    candidate = (root / text).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def mark_uploaded(conn: sqlite3.Connection, batch: sqlite3.Row, item: sqlite3.Row, *,
                  files: list[Any], original_uploaded: bool) -> dict:
    """The clip goes live -- but only once the server has seen the bytes.

    `BROLL_DATA_ROOT` is the NAS archive, so "did the upload land" is a
    `stat()`, not a promise. Every declared file is checked for presence AND
    size, and the proxy the server itself allocated is required whether or not
    the companion declared it. A 409 lists exactly which files to send again,
    which is what lets an interrupted rclone resume instead of restarting the
    clip (plan §6, "Upload interrupted").

    Only here does `videos.status` leave `ingesting`: before this the row
    reserves a name and holds segments, and browse/tree/search all skip it.
    Which is why it also refuses a clip that holds NO segments (CR-54): going
    live is the one-way door, and an undescribed clip through it is invisible
    to search for ever.
    """
    if item["video_id"] is None or not item["archive_dir"] or not item["archive_stem"]:
        raise HTTPException(409, {"detail": "this item has no archive slot yet; re-claim",
                                  "reason": "unclaimed"})
    rel_path = _video_rel_path(conn, item["video_id"]) or ""
    final_name = PurePosixPath(rel_path).name
    slots = ItemFiles(item["archive_dir"], item["archive_stem"], final_name,
                      item["video_id"])

    declared: dict[str, int | None] = {}
    for entry in files:
        declared[str(entry.rel).replace("\\", "/").strip()] = entry.size
    required = [slots.proxy]
    if original_uploaded:
        required.append(slots.original)
    for rel in required:
        declared.setdefault(rel, None)

    missing: list[str] = []
    size_mismatch: list[dict] = []
    sizes: dict[str, int] = {}
    for rel, want in declared.items():
        path = _resolve_under_root(rel)
        if path is None:
            # Not a 409: a 409 invites a retry, and no retry can fix a path
            # that points outside the archive. It is a bug or an attack.
            raise HTTPException(400, {
                "detail": f"{rel!r} is not a path inside the archive root",
                "reason": "outside_root"})
        try:
            actual = path.stat().st_size
        except OSError:
            missing.append(rel)
            continue
        sizes[rel] = actual
        if want is not None and int(want) != actual:
            size_mismatch.append({"rel": rel, "declared": int(want), "actual": actual})

    if missing or size_mismatch:
        log.warning("b-roll ingest: item %s not live -- %d missing, %d size mismatch",
                    item["uid"], len(missing), len(size_mismatch))
        raise HTTPException(409, {
            "detail": "the archive does not hold these files yet",
            "reason": "not_uploaded",
            "missing": missing, "size_mismatch": size_mismatch})

    # DEFENCE IN DEPTH for comp-loopback-4 (CR-54, CR-67 item 10, 2026-08-21).
    # A `/result` this route refused used to be a log line on the companion and
    # nothing else: the clip was uploaded anyway and went LIVE with no
    # segments, no themes and no category -- unfindable by either search, and
    # never re-described. The companion now fails such an item instead of
    # uploading it, but this side is the one that owns `videos.status`, and it
    # is the only writer that can be sure. An empty description is not a clip
    # in the archive; it is a clip nobody will ever find again.
    #
    # Same 409 as the missing-files branch on purpose: a 409 here means "this
    # is not finished yet", which is exactly what it is, and the companion's
    # existing handling counts it against the item's attempts and fails it with
    # the server's own words rather than looping.
    if conn.execute("SELECT 1 FROM segments WHERE video_id = ? LIMIT 1",
                    (item["video_id"],)).fetchone() is None:
        log.warning("b-roll ingest: item %s cannot go live -- no segments were "
                    "ever recorded for video %s", item["uid"], item["video_id"])
        raise HTTPException(409, {
            "detail": "this clip has no description yet; post its result first",
            "reason": "no_result"})

    now = now_iso()
    with conn:
        conn.execute(
            "UPDATE videos SET archive_path = ?, status = 'indexed' WHERE id = ?",
            (slots.proxy, item["video_id"]))
        if original_uploaded:
            # ARCHIVE-RELATIVE, like archive_path beside it, though the column
            # was introduced for absolute per-share paths (migrations/008). The
            # only absolute path this process could write is the CONTAINER's
            # (/broll-app/... ), which no editor and no conform script can
            # resolve; the archive-relative form is the one every client
            # already knows how to join to its own mount.
            conn.execute(
                "UPDATE videos SET original_path = ?, original_size_bytes = ?, "
                "original_verified_at = ? WHERE id = ?",
                (slots.original, sizes.get(slots.original), now, item["video_id"]))
        conn.execute(
            "UPDATE ingest_items SET state = 'live', stage_percent = 100, error = NULL, "
            "original_uploaded = ?, updated_at = ? WHERE uid = ?",
            (1 if original_uploaded else 0, now, item["uid"]))
        conn.execute(
            "UPDATE ingest_batches SET current_item_uid = NULL, updated_at = ? "
            "WHERE uid = ?", (now, batch["uid"]))
        # The clip has just become reachable by search; the caches that key on
        # (count, MAX(rowid)) cannot see a status flip.
        bump_search_generation(conn)
        counts = _recount(conn, batch["uid"])
    log.info("b-roll ingest: item %s is live at %s", item["uid"], slots.proxy)
    return {"ok": True, "live": True, "archive_path": slots.proxy, **counts}


# --- finishing ----------------------------------------------------------------

def release(conn: sqlite3.Connection, batch: sqlite3.Row, *, state: str,
            summary: Any = None) -> dict:
    """End the batch and drop the lease.

    `done` becomes `done_with_errors` when anything failed -- the companion
    reports what it did, the server decides what to call it, so a clip that
    failed cannot be summarised away.

    On `cancelled` the half-made rows go: a `videos` row still marked
    `ingesting` has no media on the NAS and never will, so it is deleted rather
    than left as a permanent invisible ghost holding a name. Rows that already
    reached `live` STAY -- their media is uploaded and an editor may already
    have cut with it (plan §6, "Cancel").
    """
    if state not in ("done", "failed", "cancelled"):
        raise HTTPException(422, "release state must be done, failed or cancelled")
    now = now_iso()
    with conn:
        counts = _recount(conn, batch["uid"])
        final = state
        if state == "done" and counts["n_failed"]:
            final = "done_with_errors"
        if state == "cancelled":
            conn.execute(
                "UPDATE ingest_items SET state = 'cancelled', updated_at = ? "
                "WHERE batch_uid = ? AND state NOT IN "
                "('live', 'duplicate', 'skipped', 'cancelled')",
                (now, batch["uid"]))
            conn.execute(
                "DELETE FROM videos WHERE status = ? AND id IN "
                "(SELECT video_id FROM ingest_items WHERE batch_uid = ? "
                "AND video_id IS NOT NULL)",
                (VIDEO_STATUS_INGESTING, batch["uid"]))
        conn.execute(
            "UPDATE ingest_batches SET state = ?, error = ?, finished_at = ?, "
            "lease_expires_at = NULL, current_item_uid = NULL, updated_at = ? "
            "WHERE uid = ?",
            (final, _summary_text(summary), now, now, batch["uid"]))
        counts = _recount(conn, batch["uid"])
    log.info("b-roll ingest: batch %s released as %s (%d live, %d failed)",
             batch["uid"], final, counts["n_live"], counts["n_failed"])
    return {"ok": True, "state": final, **counts}


def _summary_text(summary: Any) -> str | None:
    """Whatever the companion said, as one short string for `error`.

    Capped because it is rendered in a tooltip on the fleet grid and a
    companion traceback pasted whole would push everything else off it.
    """
    if summary in (None, "", {}, []):
        return None
    text = summary if isinstance(summary, str) else json.dumps(summary, default=str)
    return text[:500]
