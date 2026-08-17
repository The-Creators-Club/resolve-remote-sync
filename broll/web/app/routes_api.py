"""GET /api/search, /api/videos/{id}, /api/categories, /api/shares."""
from __future__ import annotations

import os
import sqlite3
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Query

from app import config
from app.db import get_db
# Import the name, not the module: the route function below is itself called
# `search` and would shadow a module import.
from app.search import BROWSE_PREDICATE, UNCATEGORISED, creators_shares, search_videos

router = APIRouter(prefix="/api")

# The share slug the companions derive a mount for without any hand-written
# config: <local_root>/Assets/B-roll Archive. Everything the archive holds is
# addressable under it on every machine.
ARCHIVE_SHARE = "broll"


def _insert_target(video: dict) -> tuple[str, str]:
    """The (share, rel_path) "Send to Resolve" should reference for `video`.

    The DB keys every clip by its INGEST share (ff3, ff4, mofa-disaster...),
    and v1 sent that identity to the companion verbatim -- which only a
    machine with a hand-written mount for that share could translate, and
    translated it to the clip's PRE-archive location: the base rig resolved
    share ff3 to an out-of-tree drive and inserted from outside the tree, and
    every other machine got "no mount configured for share 'ff3'"
    (2026-08-12). An archived clip's canonical home is the archive, which is
    mountable everywhere as the "broll" share (derived from local_root; the
    companion can even fetch a missing clip from the NAS under it), so the
    insert references the archive TOP-SLOT file -- the best media, sibling of
    its Proxy/ preview (HANDOFF.md par.1: best media in the folder, preview in
    Proxy/). The sibling is found by stem at request time because the DB
    stores only the preview path; the 4 stem-diverged clips of archive task
    #23 (no unique sibling) fall back to inserting the preview itself --
    degraded but present on every machine, unlike the ingest-share path.
    Un-archived clips keep the ingest identity, exactly as before.
    """
    rel = str(video.get("archive_path") or "")
    if not rel:
        return video["share"], video["rel_path"]
    preview = PurePosixPath(rel)
    if preview.parent.name == "Proxy":
        top_dir = preview.parent.parent
        top_dir_fs = config.get_data_root() / str(top_dir)
        try:
            entries = os.listdir(top_dir_fs)
        except OSError:
            entries = []
        matches = [
            e for e in entries
            if os.path.splitext(e)[0] == preview.stem
            and (top_dir_fs / e).is_file()
        ]
        if len(matches) == 1:
            return ARCHIVE_SHARE, str(top_dir / matches[0])
    return ARCHIVE_SHARE, rel


@router.get("/search")
def search(
    q: str = "",
    category: str | None = None,
    flags: str | None = None,
    limit: int = Query(default=24, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    mode: str = Query(default="hybrid"),
    fuzzy: bool = Query(default=True),
    sources: str = Query(default="all"),
    collection: str | None = None,
    shoot: str | None = None,
    path: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    results, total = search_videos(
        conn,
        q=q,
        category=category,
        flags=flags,
        limit=limit,
        offset=offset,
        mode=mode,
        fuzzy=fuzzy,
        sources=sources,
        collection=collection,
        shoot=shoot,
        path=path,
    )
    return {"results": results, "total": total}


@router.get("/videos/{video_id}")
def get_video(video_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    video_row = conn.execute(
        "SELECT * FROM videos WHERE id = ?", (video_id,)
    ).fetchone()
    if video_row is None:
        raise HTTPException(status_code=404, detail="video not found")

    segments = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM segments WHERE video_id = ? ORDER BY t_start ASC",
            (video_id,),
        ).fetchall()
    ]
    # Transcript cues alongside segments (SPEC.md "Database": speech is
    # transcribed locally and is often the richest index a clip has -- see
    # docs/indexing-findings.md), so the detail view can show what's said as
    # well as what's seen.
    transcript = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM transcript_segments WHERE video_id = ? ORDER BY t_start ASC",
            (video_id,),
        ).fetchall()
    ]
    themes = [
        r["text"]
        for r in conn.execute(
            "SELECT text FROM themes WHERE video_id = ?", (video_id,)
        ).fetchall()
    ]
    flags = [
        r["flag"]
        for r in conn.execute(
            "SELECT flag FROM quality_flags WHERE video_id = ?", (video_id,)
        ).fetchall()
    ]

    video = dict(video_row)
    video["insert_share"], video["insert_rel_path"] = _insert_target(video)

    return {
        "video": video,
        "segments": segments,
        "transcript": transcript,
        "themes": themes,
        "quality_flags": flags,
    }


@router.get("/categories")
def get_categories(conn: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    rows = conn.execute("SELECT * FROM categories ORDER BY slug").fetchall()
    return [dict(r) for r in rows]


@router.get("/shares")
def get_shares() -> list[dict]:
    return config.parse_shares()


# How deep the Creators_Club tree mirrors a share's real folders. Three levels
# below the share is what the deepest meaningful structure actually is
# (`Whisky/Interviews/黃培峻 Huang Pei-jun`); anything past that is camera-roll
# noise that would split a folder across branches for no benefit.
SHOOT_TREE_DEPTH = 3


def _shoot_tree(conn: sqlite3.Connection, creators: list[str]) -> list[dict]:
    """Creators_Club, organised by shoot rather than subject.

    Group = share (the shoot); under it the share's OWN folder tree, mirrored
    as nested children (to SHOOT_TREE_DEPTH) so a clip lives in the sidebar
    where it lives on disk: `ff4/Whisky/Interviews/<person>/Proxy/x.mov` shows
    as ff4 > Whisky > Interviews > <person>. A `Proxy` path component is folded
    away: on a source="proxies" share every single clip sits in one, so it
    carries no information and would just add a level of noise to every branch.

    A node's slug is `share::A / B / C` — the exact shape build_shoot_clause
    parses, at any depth.
    """
    if not creators:
        return []
    placeholders = ", ".join("?" for _ in creators)
    rows = conn.execute(
        f"SELECT share, rel_path FROM videos WHERE share IN ({placeholders}) "
        "AND status != 'skipped' AND status != 'excluded' AND duplicate_of IS NULL",
        creators,
    ).fetchall()

    # share -> nested {name: {"count": n, "children": {...}}}
    shoots: dict[str, dict] = {}
    totals: dict[str, int] = {}
    for r in rows:
        parts = [p for p in r["rel_path"].split("/")[:-1] if p.lower() != "proxy"]
        parts = parts[:SHOOT_TREE_DEPTH]
        totals[r["share"]] = totals.get(r["share"], 0) + 1
        node = shoots.setdefault(r["share"], {})
        for name in parts:
            entry = node.setdefault(name, {"count": 0, "children": {}})
            entry["count"] += 1
            node = entry["children"]

    def to_children(share: str, node: dict, prefix: list[str]) -> list[dict]:
        out = []
        # Alphabetical, not by count: this side mirrors a folder tree, and
        # `Day 1, Day 2` in shooting order is how an editor scans it.
        for name in sorted(node):
            path = [*prefix, name]
            out.append({
                "slug": f"{share}::{' / '.join(path)}",
                "label": name,
                "count": node[name]["count"],
                "children": to_children(share, node[name]["children"], path),
            })
        return out

    out = []
    for share in sorted(shoots):
        out.append({
            "slug": share, "label": share, "count": totals[share],
            "children": to_children(share, shoots[share], []),
        })
    return sorted(out, key=lambda g: -g["count"])


def _downloads_total(conn: sqlite3.Connection, creators: list[str]) -> int:
    """How many clips clicking the Downloads root actually returns.

    Deliberately NOT the sum of the category counts below it: those come from a
    `status='indexed'` grouping (a clip has no category before the model pass),
    while a click goes through search's browse path, which drops only
    skipped/excluded/duplicates. The root advertised the smaller number and
    delivered the bigger one (BROLL-10, 2026-08-11). The per-category counts are
    left alone -- the extra rows have no category to be counted under, and
    inflating a subject folder would be the same lie in the other direction.
    """
    sql = f"SELECT COUNT(*) FROM videos v WHERE {BROWSE_PREDICATE}"
    params: list = []
    if creators:
        placeholders = ", ".join("?" for _ in creators)
        sql += f" AND v.share NOT IN ({placeholders})"
        params = list(creators)
    return conn.execute(sql, params).fetchone()[0]


@router.get("/tree")
def get_tree(conn: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    """The folder browser: two roots, each with its subject groups and leaves.

    Counts come from videos.category, and are what the sidebar shows next to
    each folder. They deliberately exclude the same rows browse does (editor
    proxy folders, byte-duplicates) so a folder's count matches what clicking
    it actually returns -- a tree that promises 218 and delivers 190 is worse
    than no count at all.

    Folders with no videos in a root are omitted from that root rather than
    shown as zero: an editor scanning for footage should not have to read past
    empty shelves.
    """
    # Derived, not just configured: env list plus every share the indexer has
    # pushed as source='proxies' — see search.creators_shares.
    creators = sorted(creators_shares(conn))
    labels = {r["slug"]: r["label"] for r in
              conn.execute("SELECT slug, label FROM categories").fetchall()}

    # The two roots are organised on DIFFERENT axes, on purpose.
    #
    # Downloads is footage we did not shoot, so the only way in is what it is
    # ABOUT -- the subject taxonomy, which costs a model call per clip to build.
    #
    # Creators_Club is our own shoots, which are deliberately not model-indexed
    # (ShareConfig.index: false). They do not need it: an editor looks for own
    # footage by the shoot, and the shoot's own folder tree -- event / day /
    # camera -- already records that. So this side is built from rel_path, which
    # is free, instant, and exactly matches how the material was captured.
    creators_tree = _shoot_tree(conn, creators) if creators else []

    # COALESCE rather than "category IS NOT NULL": clips with no subject at all
    # (only format/place/look themes) still need somewhere to be browsed to,
    # otherwise they are searchable but unreachable by clicking.
    rows = conn.execute(
        f"SELECT COALESCE(category, '{UNCATEGORISED}') category, share, COUNT(*) n "
        "FROM videos WHERE status != 'skipped' AND duplicate_of IS NULL "
        "AND status = 'indexed' GROUP BY 1, share"
    ).fetchall()

    roots: dict[str, dict[str, int]] = {
        config.COLLECTION_DOWNLOADS: {}, config.COLLECTION_CREATORS: {}}
    for r in rows:
        bucket = roots[config.COLLECTION_CREATORS if r["share"] in creators
                       else config.COLLECTION_DOWNLOADS]
        bucket[r["category"]] = bucket.get(r["category"], 0) + r["n"]

    out = []
    for key in (config.COLLECTION_DOWNLOADS, config.COLLECTION_CREATORS):
        counts = roots[key]
        groups: dict[str, dict] = {}
        for slug, n in counts.items():
            if slug == UNCATEGORISED:
                continue  # appended last, below — never sorted among real subjects
            top = slug.split("/")[0]
            g = groups.setdefault(top, {"slug": top, "label": top.replace("-", " ").title(),
                                        "count": 0, "children": []})
            g["count"] += n
            g["children"].append({"slug": slug, "label": labels.get(slug, slug), "count": n})
        for g in groups.values():
            g["children"].sort(key=lambda c: -c["count"])

        ordered = sorted(groups.values(), key=lambda g: -g["count"])
        # Always last, whatever its size: it is a leftover pile, not a subject,
        # and ranking it by count would float it above real folders.
        leftover = counts.get(UNCATEGORISED, 0)
        if leftover:
            ordered.append({
                "slug": UNCATEGORISED, "label": "Uncategorised",
                "count": leftover, "children": [],
            })
        if key == config.COLLECTION_CREATORS:
            # Shoot-shaped, not subject-shaped — see the note in get_tree().
            ordered = creators_tree
        out.append({
            "collection": key,
            "label": config.COLLECTION_LABELS[key],
            "total": (sum(g["count"] for g in creators_tree)
                      if key == config.COLLECTION_CREATORS
                      else _downloads_total(conn, creators)),
            "groups": ordered,
        })
    return out
