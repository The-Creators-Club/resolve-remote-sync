"""GET /api/search, /api/videos/{id}, /api/categories, /api/shares."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from app import config
from app.db import get_db
# Import the name, not the module: the route function below is itself called
# `search` and would shadow a module import.
from app.search import UNCATEGORISED, search_videos

router = APIRouter(prefix="/api")


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

    return {
        "video": dict(video_row),
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


def _shoot_tree(conn: sqlite3.Connection, creators: list[str]) -> list[dict]:
    """Creators_Club, organised by shoot rather than subject.

    Group = share (the shoot), leaf = the first meaningful directory under it.
    A `Proxy` path component is folded away: on a source="proxies" share every
    single clip sits in one, so it carries no information and would just add a
    level of noise to every branch. `Day 1/Fx3/Proxy/x.mov` -> `Day 1 / Fx3`.
    """
    if not creators:
        return []
    placeholders = ", ".join("?" for _ in creators)
    rows = conn.execute(
        f"SELECT share, rel_path FROM videos WHERE share IN ({placeholders}) "
        "AND status != 'skipped' AND status != 'excluded' AND duplicate_of IS NULL",
        creators,
    ).fetchall()

    shoots: dict[str, dict[str, int]] = {}
    for r in rows:
        parts = [p for p in r["rel_path"].split("/")[:-1] if p.lower() != "proxy"]
        # Two levels is what a shoot actually has (day, then camera). Deeper
        # nesting would split a camera roll across branches for no benefit.
        leaf = " / ".join(parts[:2]) if parts else "(root)"
        shoots.setdefault(r["share"], {})
        shoots[r["share"]][leaf] = shoots[r["share"]].get(leaf, 0) + 1

    out = []
    for share in sorted(shoots):
        children = [{"slug": f"{share}::{leaf}", "label": leaf, "count": n}
                    for leaf, n in sorted(shoots[share].items())]
        out.append({
            "slug": share, "label": share, "count": sum(shoots[share].values()),
            "children": children,
        })
    return sorted(out, key=lambda g: -g["count"])


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
    creators = sorted(config.get_creators_shares())
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
                      if key == config.COLLECTION_CREATORS else sum(counts.values())),
            "groups": ordered,
        })
    return out
