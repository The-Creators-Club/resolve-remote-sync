"""GET /api/search, /api/videos/{id}, /api/categories, /api/shares."""
from __future__ import annotations

import logging
import os
import sqlite3
import unicodedata
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Query

from app import config
from app import edit_weight
from app import ingest_batches
from app.db import get_db
# Import the name, not the module: the route function below is itself called
# `search` and would shadow a module import.
from app.search import (BROWSE_PREDICATE, UNCATEGORISED, count_in_scope,
                        creators_shares, search_videos)
from app.semantic import mode_availability

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)

# The share slug the companions derive a mount for without any hand-written
# config: <local_root>/Assets/B-roll Archive. Everything the archive holds is
# addressable under it on every machine.
ARCHIVE_SHARE = "broll"


def _pending_original(conn: sqlite3.Connection | None, video: dict) -> str | None:
    """The archive path an original that is STILL UPLOADING will land at.

    overseer-1 (2026-09-18b). A clip whose proxies are on the NAS and whose
    original is not is published on purpose (wire-1's `proxies_live`), and for
    the hours that window lasts `insert_target_detail` finds no sibling beside
    the preview and answers `original_rel: null`. The companion reads that as
    "this clip has no original", imports the PREVIEW at the original's own
    path, permanently, and nothing upgrades when the real file lands - which
    is the common case for every heavy clip and defeats the plan's "usable
    from the moment its editing proxy lands".

    So the path is answered before the bytes exist, and flagged. It is
    `ingest_batches.ItemFiles(...).original`, i.e. the SAME expression
    `mark_uploaded` will store on the second post, never a reconstruction of
    it. None whenever nothing is genuinely coming: no ingest item (everything
    the indexer archived), an item that already sent its original, or a batch
    ingested with `upload_originals` off, whose item is `live` with the flag
    at 0 and has nothing owed at all.
    """
    if conn is None or not video.get("id"):
        return None
    try:
        row = conn.execute(
            "SELECT i.state, i.original_uploaded, i.archive_dir, i.archive_stem, "
            "b.settings_json FROM ingest_items i "
            "JOIN ingest_batches b ON b.uid = i.batch_uid "
            "WHERE i.video_id = ? ORDER BY i.updated_at DESC LIMIT 1",
            (video["id"],)).fetchone()
    except sqlite3.Error:
        # The insert object degrades; it never fails the detail page.
        return None
    if row is None or not row["archive_dir"]:
        return None
    if not bool(ingest_batches.load_settings(row).get("upload_originals", True)):
        return None
    owed = (row["state"] == "proxies_live"
            # A `live` row with the flag at 0 is a wire-1 victim written
            # before that fix deployed: published, original never sent, and no
            # longer reachable by any retry. It is owed just the same.
            or (row["state"] == "live" and not row["original_uploaded"]))
    if not owed:
        return None
    final_name = PurePosixPath(str(video.get("rel_path") or "")).name
    if not final_name:
        return None
    return ingest_batches.ItemFiles(
        row["archive_dir"], row["archive_stem"] or "", final_name,
        video.get("id")).original


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
    target = insert_target_detail(video)
    return target["share"], target["rel_path"]


# The editing proxy's extension. `proxy_relink.PROXY_EXTENSIONS` prefers
# `.mov` and `proxy_gen` writes `.mov`, so the editing proxy and the `.mp4`
# preview can share one `Proxy/` folder and every existing reader picks the
# editing proxy when both are there (plan section 2).
EDIT_PROXY_EXT = ".mov"

# Where the edit-weight line sits and how it is read: `app/edit_weight.py`,
# which the companion carries a verbatim copy of because it makes the same
# decision at ingest (plan section 5 items 1-2, 2026-09-17).
EDIT_WEIGHT_MAX_HEIGHT = edit_weight.EDIT_WEIGHT_MAX_HEIGHT
EDIT_WEIGHT_MAX_BITRATE = edit_weight.EDIT_WEIGHT_MAX_BITRATE
EDIT_WEIGHT_CODECS = edit_weight.EDIT_WEIGHT_CODECS


def _is_edit_weight(video: dict) -> bool | None:
    """Is this clip's own file already an editing proxy? None = cannot tell.

    A row read, not a rule: the rule is `edit_weight.is_edit_weight`, shared
    with the companion's ingest so the file that got no `.mov` made beside it
    is exactly the file this route calls edit-weight.
    """
    return edit_weight.is_edit_weight(
        video.get("height"), video.get("bitrate"), video.get("codec"))


def insert_target_detail(video: dict,
                         conn: sqlite3.Connection | None = None) -> dict:
    """Everything "Send to Resolve" may need about this clip, as rel paths.

    `share` and `rel_path` are _insert_target's answer unchanged -- the page
    keeps POSTing them and an old companion keeps acting on them alone. The
    rest is the proxy-tiers `insert` object (plan section 5): which file is
    the ORIGINAL, which is the browser preview, whether an editing proxy
    exists beside them, and whether the original is already light enough to be
    its own. The companion cannot fetch the detail API (audit F2), so the page
    forwards this object in the POST body and a companion that does not
    understand it falls back to the stem convention.

    `original_rel` is None when there was no unique sibling and the preview
    itself is what gets inserted -- the archive task #23 clips. A caller must
    not read "no original" as "use the preview and pretend": that is what the
    flag is for.

    `known` is proxy-tiers-3 (2026-09-18, the server half of CR-284G). This
    function discovers the original and the editing proxy by LISTING the
    archive folder inside the container, and an OSError - the dataset
    unmounted, an SMB hiccup, `BROLL_DATA_ROOT` wrong after an image update -
    was swallowed into "no entries", which is byte for byte the answer for
    "this clip has no original". Ten minutes of that turned every Send to
    Resolve in the window into a preview-only insert with a stand-in ledger
    row, and the damage outlived the outage for ever on projects nobody
    re-checks. `known: false` says "the server judged nothing", and the
    companion falls back to the pre-phase-3 route: fetch the file the editor
    asked for, never a stand-in. The keys are still PRESENT and null on that
    path on purpose - an ABSENT `preview_rel`/`edit_proxy_rel` means "use the
    stem convention", which re-creates exactly the wrong answer.
    """
    rel = str(video.get("archive_path") or "")
    if not rel:
        # Un-archived: the INGEST identity, which only a machine with a
        # hand-written mount for that share can translate. Unchanged since
        # 2026-08-12, and there is no archive geometry to describe.
        return {"share": video["share"], "rel_path": video["rel_path"],
                "original_rel": video["rel_path"], "preview_rel": None,
                "edit_proxy_rel": None, "known": True}

    preview = PurePosixPath(rel)
    if preview.parent.name != "Proxy":
        return {"share": ARCHIVE_SHARE, "rel_path": rel,
                "original_rel": None, "preview_rel": rel,
                "edit_proxy_rel": None, "known": True}

    top_dir = preview.parent.parent
    top_dir_fs = config.get_data_root() / str(top_dir)
    # An EMPTY listing is an answer; a listing that RAISED is not. Only the
    # second makes this object unknown (proxy-tiers-3).
    known = True
    try:
        entries = os.listdir(top_dir_fs)
    except OSError as exc:
        entries = []
        known = False
        log.warning("proxy-tiers-3: could not read the archive folder %s (%s); "
                    "answering known=false rather than 'this clip has no "
                    "original'", top_dir, exc)
    # broll-3 (2026-09-18): CR-90. The left side is listdir bytes off the NAS
    # (a Mac's rclone upload spells an accented name NFD), the right side is a
    # string the DB holds in NFC, and this comparison is only ever compared --
    # never opened. A miss answers `original_rel: None`, i.e. it silently
    # degrades a clip that HAS an original to a preview-only insert. The join
    # below keeps the entry's own bytes, which is where the truth is.
    want = unicodedata.normalize("NFC", preview.stem)
    matches = [
        e for e in entries
        if unicodedata.normalize("NFC", os.path.splitext(e)[0]) == want
        and (top_dir_fs / e).is_file()
    ]
    if len(matches) > 1:
        # Two files whose names differ only by normalisation is a real archive
        # shape; the clip degrades exactly as before, but not in silence.
        log.warning("broll-3: %s has %d top-slot candidates for stem %r; "
                    "answering original_rel=None", top_dir, len(matches),
                    preview.stem)
    original_rel = str(top_dir / matches[0]) if len(matches) == 1 else None

    # Found by stem beside the preview, the same way the top slot is: nothing
    # records it, and an editing proxy that arrives later must show up without
    # a re-index.
    # broll-1 (2026-09-18b mediums): "the same way" has to include CR-90.
    # broll-3 fixed the top slot's compare and left this one building
    # `preview.stem + ".mov"` from the DB's NFC string and stat'ing it, so a
    # Mac's NFD upload made the editing proxy invisible while the original
    # beside it was found. That asymmetry is worse than missing both:
    # `broll_server.derive_insert_paths` reads a null `edit_proxy_rel` as
    # either "the original is light enough to edit with" (a multi-GB camera
    # master over the internet) or a stand-in with no `upgrade_rel`, i.e. one
    # nothing ever upgrades. So list the Proxy folder once and compare
    # normalised, keeping the entry's own bytes in the answer - never NFC a
    # path something opens.
    proxy_dir_fs = config.get_data_root() / str(preview.parent)
    edit_proxy_rel = None
    try:
        proxy_entries = os.listdir(proxy_dir_fs)
    except OSError as exc:
        # Same rule as the listing above: a listing that could not be taken is
        # not "there is no editing proxy" (proxy-tiers-3). This is a second
        # call and can raise on its own.
        proxy_entries = []
        known = False
        log.warning("proxy-tiers-3: could not read the proxy folder %s (%s); "
                    "answering known=false", preview.parent, exc)
    # broll-4 (2026-09-18): a preview whose own suffix is already the
    # editing-proxy one IS this file, and advertising a file as its own
    # editing proxy costs the companion a background upgrade thread and a
    # stand-in ledger row for a tier that does not exist.
    # `build_archive.preview_source` produces exactly that shape when it
    # falls back to the top slot (the audio-only `skipped` arm, BROLL-14).
    # The guard survives the listing rewrite by comparing normalised too: the
    # preview's own name off disk may be spelled differently from the row's.
    preview_name = unicodedata.normalize("NFC", preview.name)
    edit_matches = [
        e for e in proxy_entries
        if unicodedata.normalize("NFC", os.path.splitext(e)[0]) == want
        and os.path.splitext(e)[1].lower() == EDIT_PROXY_EXT
        and unicodedata.normalize("NFC", e) != preview_name
        and (proxy_dir_fs / e).is_file()
    ]
    if len(edit_matches) > 1:
        # Two editing proxies differing only by normalisation: degrade rather
        # than guess, and say so, exactly as the top slot does.
        log.warning("broll-1: %s has %d editing-proxy candidates for stem %r; "
                    "answering edit_proxy_rel=None", preview.parent,
                    len(edit_matches), preview.stem)
    elif len(edit_matches) == 1:
        edit_proxy_rel = str(preview.parent / edit_matches[0])

    return {
        "share": ARCHIVE_SHARE,
        "rel_path": original_rel or rel,
        "original_rel": original_rel,
        "preview_rel": rel,
        "edit_proxy_rel": edit_proxy_rel,
        "known": known,
    }


def _insert_object(video: dict, conn: sqlite3.Connection | None = None) -> dict:
    """The detail response's `insert` object. Older pages ignore it."""
    target = insert_target_detail(video, conn)
    obj = {
        "share": target["share"],
        "original_rel": target["original_rel"],
        "preview_rel": target["preview_rel"],
        "edit_proxy_rel": target["edit_proxy_rel"],
        # proxy-tiers-3: "did the server manage to look?", not "is there
        # one?". Optional on the wire - a companion that has never heard of
        # it behaves exactly as before (CR-284G).
        "known": target.get("known", True),
        # proxy-tiers-3 (2026-09-18b mediums, owed to CR-302 by the
        # companion-broll group): FORCED on the known=false path, and the one
        # field in this object that is not the truth. `known` is read by
        # companion 0.9.75 and later only; every build in the field today
        # reads `original_is_edit_weight` alone, and a `false` there during an
        # outage is what makes it plan a stand-in and write a ledger row that
        # outlives the outage for ever. `true` forces PLAN_FETCH_ORIGINAL on
        # 0.9.65..0.9.74 - fetch the file the editor asked for, which is the
        # route 0.9.75 takes from `known` anyway, so nothing changes for a new
        # build (it returns before the weight is consulted). The dashboard
        # deploys first, so this is what protects the fleet in between. It
        # stays scoped to this path: a `true` on the healthy path would
        # suppress every stand-in.
        "original_is_edit_weight": (
            True if target.get("known") is False
            else _is_edit_weight(video)),
        # `fps` is the stored float, not a rational: it is what the row holds,
        # and inventing "30000/1001" from 29.97 here would be this route
        # guessing at the camera's intent.
        "geometry": {
            "width": video.get("width"),
            "height": video.get("height"),
            "fps": video.get("fps"),
            "frames": video.get("frames"),
            "start_tc": video.get("start_tc"),
        },
    }
    # overseer-1 (2026-09-18b): only while an original is genuinely on its way,
    # and only when the server could LOOK (a `known: false` object judged
    # nothing, and naming a path there would contradict it). ADDED, never
    # substituted: `original_rel` is null in this window today, so a companion
    # that ignores the flag simply gets the path it would have got once the
    # upload finished, which is its ordinary stand-in path. The key is absent
    # rather than false when nothing is pending, so nothing has to be taught
    # to read it.
    if obj["original_rel"] is None and obj["known"]:
        pending = _pending_original(conn, video)
        if pending:
            obj["original_rel"] = pending
            obj["original_pending"] = True
    return obj


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
    # Two things the page cannot work out for itself, both about an EMPTY grid
    # (BROLL-9 / BROLL-10, 2026-09-04). `mode_available` says which of the
    # three modes can answer at all and why not, so the buttons stop offering
    # a mode that returns nothing on every query for ever; `scope_total` says
    # how many clips the filters left to search, so "nothing matched" can name
    # what it searched. scope_total is computed only when there is a query and
    # it found nothing -- every other search pays for neither.
    out: dict = {"results": results, "total": total,
                 "mode_available": mode_availability(conn)}
    if q.strip() and not results:
        out["scope_total"] = count_in_scope(
            conn, category=category, flags=flags, collection=collection,
            shoot=shoot, path=path)
    return out


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
    # Additive, and older pages ignore it: a new dashboard in front of an old
    # page, or an old companion behind a new one, both behave exactly as they
    # did (plan section 7's deploy note).
    video["insert"] = _insert_object(video, conn)

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
    # BROWSE_PREDICATE, not a hand-copied twin of it: this query produces the
    # COUNT beside each shoot folder, and a click on that folder goes through
    # search's browse path. The two drifted once already (BROLL-10), and the
    # 'ingesting' rows dashboard ingest mints hours before their media lands
    # would have drifted them again -- a shoot advertising 40 while 12 are
    # playable is worse than no count at all.
    rows = conn.execute(
        f"SELECT v.share, v.rel_path FROM videos v WHERE v.share IN ({placeholders}) "
        f"AND {BROWSE_PREDICATE}",
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
