"""JSON API under /api/v1, plus the view-model builders shared with ui.py.

The report endpoint is the only write path exposed over HTTP; it requires an
X-CCSync-Token -- a per-editor token an admin minted, or the one fleet-wide
shared secret while DASH_SHARED_REPORT_TOKEN_ENABLED is on.
DASH_REPORT_TOKEN_OPTIONAL is NOT a way around that any more: since 2026-08-17
(COMMERCIAL_READINESS.md item 15) it is ignored, loudly, unless the machine
also sets the DASH_DEV_INSECURE lab flag.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import VERSION, auth, db, health, local_users, package_store, release_trust
from .nas import EDITORS_GROUP, NasBackend, NasError, is_valid_username, looks_like_ssh_pubkey
from .nas import factory as nas_factory
from .syncthing_client import SyncthingClient, SyncthingError

router = APIRouter(prefix="/api/v1")

log = logging.getLogger("ccsync.dashboard.api")

LANE_LABELS = {
    "lane_a_video_up": "A",
    "lane_b_proxy_down": "B",
    "lane_c_syncthing": "C",
}

# Scratch/utility Resolve project names (lowercased) that must never drive
# sticky-root auto-matching, the resolve_project_unmapped new-project prompt,
# machine_state, or media-tree presence. Mirrors the companion's
# ignored_resolve_projects config default -- kept server-side too so reports
# from OLD companion versions (or any unfiltered code path) stay harmless.
IGNORED_RESOLVE_PROJECTS = {"untitled project", "new doc"}

# Resolve numbers duplicates of its scratch projects -- "New Doc 1",
# "Untitled Project (3)" -- and the Blackmagic Proxy Generator's helper
# project counts up like that all day. Only a trailing number (optionally
# spaced/dashed/bracketed) may follow the ignored name: "New Documentary"
# and "New Doc Final" are real projects and never match. Mirrors the
# companion's config.is_ignored_project rule -- keep the two in lockstep.
_NUMBERED_DUPLICATE_RE = re.compile(r"^[\s_\-]*[\(\[]?\d+[\)\]]?$")


def is_ignored_resolve_project(name: str) -> bool:
    """Prefix match over IGNORED_RESOLVE_PROJECTS, whitespace-collapsed."""
    candidate = " ".join(str(name or "").split()).lower()
    if not candidate:
        return False
    for entry in IGNORED_RESOLVE_PROJECTS:
        if candidate == entry:
            return True
        if candidate.startswith(entry) and _NUMBERED_DUPLICATE_RE.match(
            candidate[len(entry):]
        ):
            return True
    return False


def token_ok(configured: str, presented: str) -> bool:
    """Constant-time shared-secret comparison.

    `==` on a secret leaks its length and its matching prefix through timing.
    The dashboard is LAN/tailnet-only, so this was never the day's biggest
    problem -- but every token check in this codebase goes through here now so
    the next one can't be written the naive way.

    Compared as BYTES: Starlette decodes header values latin-1, and
    hmac.compare_digest raises TypeError on a str containing any character
    above U+007F -- so a junk `X-CCSync-Token` with one non-ASCII byte turned
    an unauthenticated request into a 500 and a traceback instead of a 401
    (KNOWN_BUGS DASH-5, 2026-08-11)."""
    if not configured or not presented:
        return False
    try:
        return hmac.compare_digest(str(configured).encode("utf-8", "surrogateescape"),
                                   str(presented).encode("utf-8", "surrogateescape"))
    except (TypeError, ValueError, UnicodeError):
        return False


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db.connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


# ------------------------------------------------- companion credentials
# TWO credentials reach the companion-facing routes, and every one of them goes
# through resolve_companion_credential (COMMERCIAL_READINESS.md item 15,
# 2026-08-17):
#
#   editor  "cce1.<id>.<secret>", minted per editor on the Users page, stored
#           hashed, revocable one person at a time, and BOUND: it carries whose
#           machine it is, so a report or a selection read under it may not
#           claim another editor's identity.
#   shared  the one DASH_REPORT_TOKEN every deployed companion holds today.
#           Kept for migration and nothing else -- it proves only "somebody in
#           this fleet", which is why the identity header exists beside it --
#           and DASH_SHARED_REPORT_TOKEN_ENABLED=0 retires it.
#
# `conn` may be None for callers that have no database handle yet (app.py's
# pre-body gate opens its own; see _companion_credential there). A per-editor
# token can then only be recognised by SHAPE, never accepted -- so None never
# widens what is allowed.

AUTH_NONE = "none"
AUTH_SHARED = "shared"
AUTH_EDITOR = "editor"


def resolve_companion_credential(
    settings, conn: sqlite3.Connection | None, token: str
) -> tuple[str, str | None]:
    """-> (AUTH_*, editor username or None).

    AUTH_EDITOR always comes with the editor the token is bound to; AUTH_SHARED
    never does, because the shared token identifies nobody.
    """
    token = str(token or "")
    if db.looks_like_editor_report_token(token):
        # Shape-first: a per-editor token is NEVER compared against the shared
        # secret, so a deployment mid-migration cannot have one accidentally
        # accepted as the other.
        if conn is None:
            return AUTH_NONE, None
        editor = db.verify_editor_report_token(conn, token)
        if editor is None:
            return AUTH_NONE, None
        return AUTH_EDITOR, editor
    if (getattr(settings, "shared_report_token_enabled", True)
            and token_ok(settings.report_token, token)):
        return AUTH_SHARED, None
    return AUTH_NONE, None


def companion_token_ok(settings, conn: sqlite3.Connection | None, token: str) -> bool:
    """Either credential, without caring which. For the routes that pair it
    with a separate identity check of their own."""
    return resolve_companion_credential(settings, conn, token)[0] != AUTH_NONE


# ------------------------------------------------------------- view models

def _lanes_view(rows: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    return [
        {
            "lane": r["lane"],
            "label": LANE_LABELS.get(r["lane"], r["lane"]),
            "machine": r["machine"],
            "state": r["state"],
            "chip": health.lane_chip_status(r, now),
            "queued": r["queued"],
            "last_error": r["last_error"],
            "last_sync": r["last_sync"],
            "received_at": r["received_at"],
            "companion_version": r["companion_version"],
            "current_project": r["current_project"],
            "bytes_done": r["bytes_done"],
            "bytes_total": r["bytes_total"],
            "speed_bps": r["speed_bps"],
            "eta_seconds": r["eta_seconds"],
        }
        for r in rows
    ]


def _editor_view(
    e: dict[str, Any],
    lanes_by_editor: dict[str, list[dict[str, Any]]],
    reachable: bool,
    now: str,
) -> dict[str, Any]:
    username = e["editor_username"]
    lane_rows = lanes_by_editor.get(username, []) if username else []
    status = health.editor_status(
        completion=e["completion"],
        need_items=e["need_items"],
        connected=bool(e["connected"]),
        last_connected_at=e["last_connected_at"],
        completion_updated_at=e["updated_at"],
        syncthing_reachable=reachable,
        lanes=lane_rows,
        now=now,
    )
    have_items = None
    if e["global_items"] is not None:
        have_items = max(e["global_items"] - e["need_items"], 0)
    rate = e["rate_bytes_per_sec"]
    eta_seconds = None
    if rate and rate > 1 and e["need_bytes"]:
        eta_seconds = e["need_bytes"] / rate
    return {
        "device_id": e["device_id"],
        "device_row_id": e["device_row_id"],
        "name": e["name"],
        "editor_username": username,
        "display_name": username or e["name"],
        "unmapped": username is None,
        "connected": bool(e["connected"]),
        "address": e["address"],
        "last_connected_at": e["last_connected_at"],
        "completion": e["completion"],
        "need_items": e["need_items"],
        "need_bytes": e["need_bytes"],
        "need_deletes": e["need_deletes"],
        "global_items": e["global_items"],
        "global_bytes": e["global_bytes"],
        "have_items": have_items,
        "rate_bytes_per_sec": rate,
        "eta_seconds": eta_seconds,
        "updated_at": e["updated_at"],
        "status": status,
        "lanes": _lanes_view(lane_rows, now),
    }


def _lanes_by_editor(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in db.fetch_lane_reports(conn):
        grouped.setdefault(row["editor_username"], []).append(row)
    return grouped


def _project_tree(projects: list[dict[str, Any]]) -> dict[str, Any]:
    """Nested {groups: {name: node}, projects: [...], slugs: [...]} built
    from the slash-separated labels (2026/CCT/Website Highlights/...). The
    sidebar renders it recursively: group rows per path segment, and each
    project shown by its LAST segment only ("short"). `slugs` lists every
    project under a node so the template can default-open the chain that
    contains the page's current project."""
    root: dict[str, Any] = {"groups": {}, "projects": [], "slugs": []}
    for p in projects:
        parts = [seg for seg in str(p["label"]).split("/") if seg]
        node = root
        node["slugs"].append(p["slug"])
        for seg in parts[:-1]:
            node = node["groups"].setdefault(seg, {"groups": {}, "projects": [], "slugs": []})
            node["slugs"].append(p["slug"])
        node["projects"].append({**p, "short": parts[-1] if parts else p["label"]})
    return root


def build_projects_view(conn: sqlite3.Connection, now: str | None = None) -> dict[str, Any]:
    now = now or db.utcnow_iso()
    collector = db.fetch_collector_status(conn)
    reachable = collector["syncthing_reachable"]
    lanes_by_editor = _lanes_by_editor(conn)
    projects = []
    for p in db.fetch_projects(conn):
        editors = [_editor_view(e, lanes_by_editor, reachable, now) for e in p["editors"]]
        projects.append({
            "slug": p["slug"],
            "label": p["label"],
            "path": p["path"],
            # Syncthing's own folder health -- 'stopped' with "folder marker
            # missing" is the tell that a project dir was moved out from under
            # a folder, which the completion % alone hides.
            "folder_state": p.get("folder_state"),
            "folder_error": p.get("folder_error"),
            "status": health.project_status(e["status"] for e in editors),
            "editors": editors,
            "need_bytes_total": sum(e["need_bytes"] or 0 for e in editors),
            "editors_behind": sum(1 for e in editors if (e["completion"] or 0) < 100),
        })
    return {
        "generated_at": now,
        "syncthing_reachable": reachable,
        "fleet_status": health.fleet_status(p["status"] for p in projects),
        "projects": projects,
        "tree": _project_tree(projects),
    }


def build_project_view(conn: sqlite3.Connection, slug: str, now: str | None = None) -> dict[str, Any] | None:
    now = now or db.utcnow_iso()
    project = db.fetch_project(conn, slug)
    if project is None:
        return None
    collector = db.fetch_collector_status(conn)
    reachable = collector["syncthing_reachable"]
    lanes_by_editor = _lanes_by_editor(conn)
    editors = [_editor_view(e, lanes_by_editor, reachable, now) for e in project["editors"]]

    # "Who has what" must cover every machine that reports media on this
    # project -- not only Syncthing (lane C) device rows. The base rig has no
    # lane C device at all, so it was invisible in this table even while
    # holding the authoritative copy of every original.
    nas = db.fetch_nas_media_summary(conn, project["id"])
    media_by_editor: dict[str, dict[str, Any]] = {}
    for r in db.fetch_editor_media_for_project(conn, slug):
        m = media_by_editor.setdefault(r["editor_username"], {
            "machine": r["machine"], "mode": r["mode"],
            "n_originals": 0, "n_proxies": 0, "bytes_proxies": 0,
        })
        m["n_originals"] += r["n_originals"]
        m["n_proxies"] += r["n_proxies"]
        m["bytes_proxies"] += r["bytes_proxies"] or 0
        if r["mode"] == "base":
            m["mode"] = "base"
    for e in editors:
        e["media"] = media_by_editor.get(e["editor_username"])
        e["report_only"] = False
        # TOTAL sync progress for an editor: lane C content plus proxies,
        # by bytes, with camera originals excluded -- they only ever live
        # on the server. A single lane's percentage told the editor nothing
        # ("SYNC (LANE C) 0%" while 263 of 283 proxies were already local,
        # 2026-07-26). Falls back to the lane C completion when no manifest
        # has arrived yet.
        lane_c_global = e.get("global_bytes") or 0
        lane_c_need = e.get("need_bytes") or 0
        nas_proxy_bytes = nas.get("bytes_proxies") or 0
        media = e["media"]
        if media is not None and (lane_c_global or nas_proxy_bytes):
            have = max(lane_c_global - lane_c_need, 0)
            have += min(media.get("bytes_proxies") or 0, nas_proxy_bytes)
            denom = lane_c_global + nas_proxy_bytes
            e["synced_pct"] = round(100.0 * have / denom, 1) if denom else None
        else:
            e["synced_pct"] = e.get("completion")
    device_editors = {e["editor_username"] for e in editors if e["editor_username"]}
    for username, m in sorted(media_by_editor.items()):
        if username in device_editors:
            continue
        lane_rows = lanes_by_editor.get(username, [])
        last_report = max((r["received_at"] for r in lane_rows), default=None)
        have = {"n_originals": m["n_originals"], "n_proxies": m["n_proxies"]}
        editors.append({
            "device_id": None, "device_row_id": None, "name": m["machine"],
            "editor_username": username, "display_name": username,
            "unmapped": False, "connected": False, "address": None,
            "last_connected_at": None, "completion": None, "need_items": 0,
            "need_bytes": 0, "need_deletes": 0, "global_items": None,
            "global_bytes": None, "have_items": None, "rate_bytes_per_sec": None,
            "eta_seconds": None, "updated_at": last_report,
            "report_only": True, "media": m, "mode": m["mode"], "synced_pct": None,
            "status": health.presence_status(m["mode"], nas, have),
            "lanes": _lanes_view(lane_rows, now),
        })

    return {
        "generated_at": now,
        "syncthing_reachable": reachable,
        "slug": project["slug"],
        "label": project["label"],
        "path": project["path"],
        "active": bool(project["active"]),
        "folder_state": project.get("folder_state"),
        "folder_error": project.get("folder_error"),
        "folder_state_at": project.get("folder_state_at"),
        "status": health.project_status(e["status"] for e in editors),
        "editors": editors,
        "nas_media": nas,
        "project_row_id": project["id"],
    }


def build_transfers_view(
    conn: sqlite3.Connection, now: str | None = None, editor: str | None = None
) -> dict[str, Any]:
    """Fleet-wide (or scoped) live per-file transfers, plus lane-C project-
    level rows from the Syncthing EMA. `editor` limits to one editor."""
    now = now or db.utcnow_iso()
    rows = []
    for t in db.fetch_active_transfers(conn, now, editor=editor):
        rows.append({
            "editor": t["editor_username"], "machine": t["machine"], "lane": t["lane"],
            "name": t["name"], "direction": t["direction"],
            "bytes_done": t["bytes_done"], "bytes_total": t["bytes_total"],
            "percentage": t["percentage"], "speed_bps": t["speed_bps"],
            "eta_seconds": t["eta_seconds"], "granularity": "file",
        })
    # Lane C (Syncthing) has no per-file data -- surface project-level drain.
    lane_c_q = """SELECT c.need_bytes, c.rate_bytes_per_sec, p.label, d.editor_username
                  FROM completion_current c
                  JOIN projects p ON p.id = c.project_id
                  JOIN devices d ON d.id = c.device_id
                  WHERE d.is_server = 0 AND c.need_bytes > 0
                    AND c.rate_bytes_per_sec IS NOT NULL AND c.rate_bytes_per_sec > 1"""
    for r in conn.execute(lane_c_q):
        if editor is not None and (r["editor_username"] or "") != editor:
            continue
        rate = r["rate_bytes_per_sec"]
        rows.append({
            "editor": r["editor_username"], "machine": "", "lane": "lane_c_syncthing",
            "name": r["label"], "direction": "down",
            "bytes_done": None, "bytes_total": None, "percentage": None,
            "speed_bps": rate, "eta_seconds": (r["need_bytes"] / rate) if rate else None,
            "granularity": "project",
        })
    rows.sort(key=lambda x: (x["speed_bps"] or 0), reverse=True)

    # The queue: what is WAITING on the current sync job, per (editor,
    # machine, project) -- lanes A/B from the nas_media/editor_media
    # manifest diff, lane C from Syncthing's missing-files cache. Two
    # scoping rules, both from the 2026-07-26 phantom-queue report:
    # every source joins selections (only TICKED projects sync, so only
    # ticked projects can be queued), and files already in the live table
    # above are subtracted (queued means not yet syncing).
    queues = db.fetch_sync_backlog(conn, editor=editor)
    lane_c_q = """SELECT c.project_id, c.device_id AS device_row, c.need_items,
                         c.need_bytes, p.slug, p.label, d.editor_username
                  FROM completion_current c
                  JOIN projects p ON p.id = c.project_id
                  JOIN devices d ON d.id = c.device_id
                  JOIN selections s ON s.editor_username = d.editor_username
                                   AND s.project_slug = p.slug
                  WHERE d.is_server = 0 AND c.need_items > 0"""
    for r in conn.execute(lane_c_q):
        if editor is not None and (r["editor_username"] or "") != editor:
            continue
        missing = db.fetch_missing(conn, r["project_id"], r["device_row"])
        queues.append({
            "editor": r["editor_username"], "machine": "",
            "slug": r["slug"], "label": r["label"],
            "lane": "c", "direction": "down", "kind": "everything else",
            "n_files": r["need_items"], "bytes": r["need_bytes"],
            "files": missing["files"][:50],
            "truncated": r["need_items"] > min(len(missing["files"]), 50),
            "manifest_truncated": False,
        })

    # Subtract in-flight files: rclone transfer names are project-relative
    # like the manifest rel_paths, with a basename fallback for safety.
    active_by_editor: dict[str, set[str]] = {}
    for t in rows:
        if t.get("granularity") != "file":
            continue
        names = active_by_editor.setdefault(str(t["editor"] or ""), set())
        name = str(t["name"] or "")
        if name:
            names.add(name)
            names.add(name.rsplit("/", 1)[-1])
    for q in queues:
        active = active_by_editor.get(str(q["editor"] or ""), set())
        if not active:
            continue
        kept = []
        removed_bytes = 0
        for f in q["files"]:
            name = str(f.get("name") or "")
            if name in active or name.rsplit("/", 1)[-1] in active:
                removed_bytes += int(f.get("size") or 0)
                continue
            kept.append(f)
        removed = len(q["files"]) - len(kept)
        if removed:
            q["files"] = kept
            q["n_files"] = max(0, q["n_files"] - removed)
            q["bytes"] = max(0, (q["bytes"] or 0) - removed_bytes)
    queues = [q for q in queues if q["n_files"] > 0]

    # A JUST-ticked project has no completion row and no manifest yet, so
    # every source above is silent for its first minute or two while the
    # share + index exchange spin up -- and the page said "everything that
    # should be somewhere is there" mid-provisioning (2026-07-26). Show it
    # as preparing instead of absent.
    pending_q = """SELECT s.editor_username AS editor, s.project_slug AS slug, p.label
                   FROM selections s JOIN projects p ON p.slug = s.project_slug AND p.active = 1"""
    pending_params: list[Any] = []
    if editor is not None:
        pending_q += " WHERE s.editor_username = ?"
        pending_params.append(editor)
    queued_pairs = {(q["editor"], q["slug"]) for q in queues}
    for r in conn.execute(pending_q, pending_params):
        if (r["editor"], r["slug"]) in queued_pairs:
            continue
        has_completion = conn.execute(
            """SELECT 1 FROM completion_current c
               JOIN devices d ON d.id = c.device_id
               JOIN projects p ON p.id = c.project_id
               WHERE p.slug = ? AND d.editor_username = ?""",
            (r["slug"], r["editor"]),
        ).fetchone()
        if has_completion:
            continue  # known state: fully synced or already queued above
        queues.append({
            "editor": r["editor"], "machine": "", "slug": r["slug"],
            "label": r["label"], "lane": "c", "direction": "down",
            "kind": "preparing", "n_files": 0, "bytes": 0, "files": [],
            "truncated": False, "manifest_truncated": False, "pending": True,
        })
    queues.sort(key=lambda q: (q["editor"] or "", q["label"], q["lane"]))

    # Editors pushing lane C content TO the server (the NAS folder's own
    # need) -- a 400 MB mp3 uploading via Syncthing was invisible in every
    # view (2026-07-26). Attribution to a single editor isn't knowable from
    # the folder need alone, so the row names the project and direction.
    incoming_q = """SELECT label, slug, need_items, need_bytes FROM projects
                    WHERE active=1 AND need_bytes > 0"""
    for r in conn.execute(incoming_q):
        rows.append({
            "editor": "", "machine": "", "lane": "lane_c_syncthing",
            "name": f"{r['label']} -- {r['need_items']} file(s) arriving at the server",
            "direction": "up",
            "bytes_done": None, "bytes_total": r["need_bytes"], "percentage": None,
            "speed_bps": None, "eta_seconds": None, "granularity": "project",
        })

    history = [
        {
            "editor": h["editor_username"], "machine": h["machine"],
            "lane": h["lane"], "name": h["name"], "direction": h["direction"],
            "completed_at": h["completed_at"] or h["received_at"],
        }
        for h in db.fetch_transfer_history(conn, editor=editor, limit=50)
    ]

    return {"generated_at": now, "transfers": rows,
            "fleet_speed_bps": sum((x["speed_bps"] or 0) for x in rows),
            "queues": queues,
            "queued_files": sum(q["n_files"] for q in queues if not q.get("pending")),
            "queued_bytes": sum(q["bytes"] or 0 for q in queues),
            "history": history}


def build_presence_view(
    conn: sqlite3.Connection, slug: str, now: str | None = None, editor: str | None = None
) -> dict[str, Any] | None:
    """Per-editor media presence for a project: NAS denominators, each
    editor's disk rollup + role-aware status + proxy-only badge, and the
    Resolve bin tree with per-clip online/offline/uploading. `editor` scopes
    to one editor (non-admins)."""
    now = now or db.utcnow_iso()
    project = db.fetch_project(conn, slug)
    if project is None:
        return None
    nas = db.fetch_nas_media_summary(conn, project["id"])
    rollups = {(r["editor_username"], r["machine"]): r
               for r in db.fetch_editor_media_for_project(conn, slug, editor=editor)}
    # Surface any (editor, machine) that has a bin tree even without a disk
    # rollup yet (e.g. Resolve open but the manifest walk hasn't run).
    for key in db.fetch_media_tree_keys(conn, slug, editor=editor):
        rollups.setdefault(key, {
            "editor_username": key[0], "machine": key[1], "mode": "editor",
            "n_originals": 0, "bytes_originals": 0, "n_proxies": 0, "bytes_proxies": 0,
            "truncated": 0,
        })
    editors = []
    for r in sorted(rollups.values(), key=lambda x: (x["editor_username"], x["machine"])):
        have = {"n_originals": r["n_originals"], "n_proxies": r["n_proxies"]}
        tree = db.fetch_media_tree(conn, r["editor_username"], r["machine"], slug, now)
        editors.append({
            "editor": r["editor_username"], "machine": r["machine"], "mode": r["mode"],
            "have": have, "bytes_originals": r["bytes_originals"],
            "bytes_proxies": r["bytes_proxies"], "truncated": bool(r["truncated"]),
            "status": health.presence_status(r["mode"], nas, have),
            "proxy_only": health.is_proxy_only(have),
            "bins": tree["bins"],
            "offline": sum(1 for b in tree["bins"] for c in b["clips"] if not c["present"]),
        })
    return {"generated_at": now, "slug": slug, "label": project["label"],
            "nas": nas, "editors": editors}


def build_editors_view(conn: sqlite3.Connection, now: str | None = None) -> dict[str, Any]:
    now = now or db.utcnow_iso()
    # Per-platform current version (see X-5): a machine's "out of date" flag
    # must compare against the CURRENT PACKAGE FOR ITS OWN REPORTED PLATFORM,
    # never hardcoded to "windows" -- a macOS companion must never be
    # compared against the Windows release. Unreported platform (old
    # companions predating the platform field) falls back to "windows".
    current_pkg_cache: dict[str, sqlite3.Row | None] = {}

    def current_version_for(platform: str) -> str | None:
        if platform not in current_pkg_cache:
            current_pkg_cache[platform] = db.get_current_package(conn, platform)
        pkg = current_pkg_cache[platform]
        return pkg["version"] if pkg is not None else None

    platforms = db.fetch_platform_map(conn)
    # Per-machine reported build (schema v10). machine_state is one row per
    # (editor, machine) and outlives a lane_report_current prune, so it is the
    # authority for "which companion build is this box running"; the lane rows
    # are only a fallback for machines that reported before v10.
    machine_versions = db.fetch_companion_version_map(conn)
    machines: dict[tuple[str, str], dict[str, Any]] = {}
    for row in db.fetch_lane_reports(conn):
        key = (row["editor_username"], row["machine"])
        entry = machines.setdefault(key, {
            "editor_username": row["editor_username"],
            "machine": row["machine"],
            "companion_version": row["companion_version"],
            "received_at": row["received_at"],
            "lanes": [],
        })
        entry["lanes"].extend(_lanes_view([row], now))
        entry["received_at"] = max(entry["received_at"], row["received_at"])
    # A machine that has reported at all belongs in the fleet view even with
    # no live lane rows (pruned after 30 silent days, or a report whose lanes
    # were all filtered out) -- otherwise a stale build goes invisible exactly
    # when you most want to see it.
    for key, state in machine_versions.items():
        entry = machines.setdefault(key, {
            "editor_username": key[0],
            "machine": key[1],
            "companion_version": state["companion_version"],
            "received_at": state["reported_at"],
            "lanes": [],
        })
    verified = db.fetch_verified_map(conn)
    # B17: the companion has been sending transport_health every heavy tick
    # and ReportIn dropped it, so nothing could tell a RELAYED editor from a
    # merely slow one -- exactly the case the companion's own docstring names.
    transport = db.fetch_transport_map(conn)
    # The safety latches (item 9): a tripped breaker or a halted machine is
    # invisible in every other signal here -- lane B simply reads idle.
    guards = db.fetch_sync_guard_map(conn)
    # "Admins see which computers are indexing and their progress"
    # (BROLL_INGEST_PLAN.md §0) -- plus the missing-proxy count, which the
    # companion has always sent and this dashboard has never stored (v20).
    ingest = db.fetch_broll_ingest_map(conn)
    music_ingest = db.fetch_music_ingest_map(conn)
    proxies = db.fetch_proxy_coverage_map(conn)
    result = []
    for entry in machines.values():
        key = (entry["editor_username"], entry["machine"])
        entry["status"] = health.worst(l["chip"] for l in entry["lanes"])
        entry["verified"] = verified.get(key, False)
        entry["transport"] = transport.get(key) or {}
        entry["guard"] = guards.get(key) or {}
        entry["ingest"] = ingest.get(key) or {}
        entry["music_ingest"] = music_ingest.get(key) or {}
        entry["proxy"] = proxies.get(key) or {}
        entry["companion_version"] = (
            (machine_versions.get(key) or {}).get("companion_version")
            or entry["companion_version"]
        )
        platform = (platforms.get(key) or "windows").strip().lower()
        current_version = current_version_for(platform)
        entry["platform"] = platform
        entry["current_companion_version"] = current_version
        # "Out of date" = running version differs from the published current
        # (not "older than": an admin rollback must flag machines too), and
        # ALWAYS compared against the current package for THIS machine's own
        # platform -- see X-5.
        entry["companion_outdated"] = bool(
            current_version
            and entry["companion_version"]
            and entry["companion_version"] != current_version
        )
        # No version reported at all (pre-0.2 companion): flag it separately
        # so the fleet view can say "unknown build" instead of silently
        # showing "?" next to a green row.
        entry["companion_version_unknown"] = not entry["companion_version"]
        result.append(entry)
    result.sort(key=lambda e: (e["editor_username"], e["machine"]))
    # Fleet-level rollups for the banner (item 9). Computed here rather than
    # in the template so the numbers are testable and both the page and the
    # /partials/fleet poll get the same ones.
    tripped = [e for e in result if (e.get("guard") or {}).get("breaker_tripped")]
    halted = [e for e in result if (e.get("guard") or {}).get("halt_active")]
    return {"generated_at": now, "editors": result,
            "current_companion_version": current_version_for("windows"),
            "breaker_tripped": [
                {"editor": e["editor_username"], "machine": e["machine"],
                 "reason": (e.get("guard") or {}).get("breaker_reason")}
                for e in tripped
            ],
            "halted": [
                {"editor": e["editor_username"], "machine": e["machine"],
                 "scope": (e.get("guard") or {}).get("halt_scope")}
                for e in halted
            ],
            "fleet_halt": db.get_fleet_halt(conn)}


# ------------------------------------------------------- scoping fleet reads
#
# COMMERCIAL_READINESS.md §C L1, "unscoped fleet reads" (2026-08-17). Every
# read below used to answer the WHOLE fleet to any signed-in editor: other
# editors' machine names, their companion builds, their per-project completion
# and -- through /projects/{slug}/devices/{id}/missing -- the actual file paths
# missing from another person's laptop. Combined with the telemetry the
# companion already sends (Resolve project name, media manifest, bin tree,
# §3's GDPR note), that is one editor able to inventory another's work.
#
# The rule is the one auth.Scope already encodes for transfers and presence:
# an EDITOR sees their own machines plus fleet-level SUMMARY numbers; an ADMIN
# sees everything, and may focus one editor with ?as=. Redaction happens at the
# route boundary rather than inside the view builders because the builders are
# shared with ui.py's page renderers, which pass their own scope in -- one
# rule, two callers, and no builder that can be called "unscoped by accident".

def _scope_shows(scope: auth.Scope, editor: str) -> bool:
    """Whether a row belonging to `editor` survives redaction.

    NOT auth.Scope.allows: that answers True for any admin, ignoring ?as=,
    which is right for "may you act on this" and wrong for "should you be
    LOOKING at this" -- an admin who has focused one editor is asking to see
    one editor. `scope.editor` is the focused/own username, or None for an
    unfocused admin (everything). A viewer with neither is shown nothing.
    """
    if scope.admin and scope.editor is None:
        return True
    if scope.editor is None:
        return False
    return str(editor or "").lower() == scope.editor.lower()


def _scope_projects_view(view: dict[str, Any], scope: auth.Scope) -> dict[str, Any]:
    """Drop other editors' per-device rows; keep the project-level totals.

    The totals stay because they are the fleet summary an editor legitimately
    needs -- "is anyone behind on this project" -- and they name nobody.
    """
    if scope.admin and scope.editor is None:
        return view
    for project in view.get("projects", []):
        editors = project.get("editors", [])
        kept = [e for e in editors
                if not e.get("editor_username")
                or _scope_shows(scope, str(e["editor_username"]))]
        project["editors_hidden"] = len(editors) - len(kept)
        project["editors"] = kept
    return view


def _scope_project_view(view: dict[str, Any], scope: auth.Scope) -> dict[str, Any]:
    if scope.admin and scope.editor is None:
        return view
    editors = view.get("editors", [])
    kept = [e for e in editors
            if not e.get("editor_username")
            or _scope_shows(scope, str(e["editor_username"]))]
    view["editors_hidden"] = len(editors) - len(kept)
    view["editors"] = kept
    return view


def _scope_editors_view(view: dict[str, Any], scope: auth.Scope) -> dict[str, Any]:
    """Own machines in full; everybody else's collapsed into a count.

    `summary` is what keeps the fleet page useful for a non-admin: how many
    machines are reporting and how many are unhealthy, with no names in it.
    """
    machines = view.get("editors", [])
    summary = {
        "machines_total": len(machines),
        "machines_ok": sum(1 for m in machines if m.get("status") == "ok"),
        "machines_unhealthy": sum(1 for m in machines if m.get("status") not in ("ok", None)),
        "machines_outdated": sum(1 for m in machines if m.get("companion_outdated")),
    }
    view["summary"] = summary
    if scope.admin and scope.editor is None:
        return view
    kept = [m for m in machines
            if _scope_shows(scope, str(m.get("editor_username") or ""))]
    view["machines_hidden"] = len(machines) - len(kept)
    view["editors"] = kept
    # The safety-alarm rollups name editors and machines too, so they follow
    # the same rule as the rows they summarise (COMMERCIAL_READINESS.md item
    # 9, 2026-08-17 -- added with those fields, not a later fix). The FLEET
    # halt is deliberately NOT redacted: it is why this editor's own sync has
    # stopped, and they must be able to see it.
    for key in ("breaker_tripped", "halted"):
        view[key] = [m for m in view.get(key, [])
                     if _scope_shows(scope, str(m.get("editor") or ""))]
    return view


# ------------------------------------------------------------------ routes

@router.get("/health")
def api_health(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    """Liveness for anyone; detail only for authenticated callers.

    The full body carries project slugs, project labels and Syncthing's
    folder error strings, and this route is in app.py's _OPEN_EXACT so the
    Docker healthcheck can reach it from 127.0.0.1 without credentials --
    which made the client roster readable by anyone who could reach the port.
    Unauthenticated callers now get {"ok", "version"} and the same
    200/exception behaviour; a session or the companion's X-CCSync-Token
    unlocks the rest.

    The status code stays 200 even when `ok` is False, and that is load
    bearing: ship.ps1 polls this route after a deploy and the macOS
    onboarding wizard uses it as its connection test, so a 503 for "Syncthing
    is unreachable" would read as "the dashboard is down". The container
    healthcheck reads `ok` out of the body instead (DASH-2, 2026-08-14)."""
    settings = request.app.state.settings
    collector = db.fetch_collector_status(conn)
    if not (
        auth.get_session_user(request) is not None
        or companion_token_ok(settings, conn,
                              request.headers.get("x-ccsync-token", ""))
    ):
        # Enough for a probe to distinguish "process up" from "process up but
        # blind", and nothing an outsider can inventory the fleet from.
        return {
            "ok": bool(collector["syncthing_reachable"]) or not settings.syncthing_url,
            "version": VERSION,
        }
    return {
        "ok": bool(collector["syncthing_reachable"]) or not settings.syncthing_url,
        "version": VERSION,
        "syncthing_reachable": collector["syncthing_reachable"],
        # True = the last poll succeeded but finished too long ago, i.e. the
        # collector thread is dead/wedged. That state also clears
        # syncthing_reachable, hence `ok` above -- which is what Docker's
        # healthcheck (see deploy/compose.yaml) parses out of this body.
        "collector_stale": collector["collector_stale"],
        "folder_errors": collector["folder_errors"],
        "last_polls": {
            kind: {"finished_at": run["finished_at"], "ok": bool(run["ok"]), "error": run["error"]}
            for kind, run in collector["kinds"].items()
        },
    }


# How often a failed live-myID read is retried. The site route is open, so an
# unreachable Syncthing must not cost every caller a request timeout; a
# successful read is cached for the life of the process instead (a Syncthing
# instance's device ID is its public key -- it does not change without a
# restart of Syncthing, and a dashboard restart re-reads it anyway).
SITE_SYNCTHING_ID_RETRY_SECONDS = 60.0


def _nas_syncthing_id(request: Request, conn: sqlite3.Connection) -> str:
    """The NAS's Syncthing device ID, live value preferred.

    The site_settings row (if any) is the next fallback, then
    DASH_SITE_NAS_SYNCTHING_ID -- the dashboard already talks to that
    Syncthing, so asking it removes the one way this manifest could hand
    every new editor a device ID that no longer exists (a re-created
    Syncthing config regenerates it -- see the "stuck lane C = regenerated
    device ID" incident). Fails soft, and never blocks the route for longer
    than one short Syncthing timeout.

    Precedence unchanged by WP D (ZERO_TOUCH_PLAN.md, 2026-08-17): the live
    read still beats everything, including a value an admin or the
    `syncthing` setup task wrote into the DB -- see site_store.py's own
    "only fills a BLANK row" rule for how that value gets there.
    """
    settings = request.app.state.settings
    state = request.app.state
    cached = getattr(state, "site_nas_syncthing_id", "")
    if cached:
        return cached
    if settings.syncthing_url:
        last_try = getattr(state, "site_nas_syncthing_id_last_try", 0.0)
        now = time.monotonic()
        if now - last_try >= SITE_SYNCTHING_ID_RETRY_SECONDS:
            state.site_nas_syncthing_id_last_try = now
            try:
                client = SyncthingClient.from_settings(settings)
                client.timeout = min(client.timeout, 5.0)
                my_id = str(client.system_status().get("myID", "") or "")
            except SyncthingError as exc:
                log.warning("site manifest: could not read Syncthing's myID (%s)", exc)
                my_id = ""
            if my_id:
                state.site_nas_syncthing_id = my_id
                return my_id
    from . import site_store

    return site_store.get_all(conn).get("nas_syncthing_id") or settings.site_nas_syncthing_id


@router.get("/site")
def api_site(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    """This site's non-secret facts, for clients that need them BEFORE they
    have any credentials (SYNOLOGY_PORT_PLAN.md WP0 step 3).

    Open by design -- it is in app.py's _OPEN_EXACT beside /api/v1/health, and
    for the same reason: the installer, the onboarding wizard and the
    companion all read it before (or without) a login. Nothing in here is a
    secret. A Syncthing device ID is a public key, and every other value is an
    address an editor is about to be handed anyway; no user, project, path
    inventory or token may ever be added to this response.

    Every string defaults to "" rather than to this fleet's own values: a
    blank field means "this deployment has not been told", which a client can
    fall back on, while a wrong-tenant default is a support incident nobody
    can see (COMMERCIAL_READINESS.md item 10).

    `schema` is a monotonic integer, not the dashboard version: clients across
    three OSes upgrade at their own pace, so they check the shape they know.

    Since ZERO_TOUCH_PLAN.md WP D (2026-08-17): every field below except
    `nas_syncthing_id` (its own precedence, above) and `video_extensions`
    (never site data, see provision.py) is resolved through
    `site_store.resolved_manifest` -- a `site_settings` DB row wins over the
    `DASH_SITE_*` value, which is what lets the wizard's "Your studio" step
    and the Settings page publish an answer with no container `--recreate`.
    A deployment that has never touched Settings (every one running today)
    has an EMPTY table, so `resolved_manifest` falls through to exactly the
    `settings.site_*` value this route always served --
    `tests/test_site.py` pins that response byte-for-byte.
    """
    from . import provision, site_store

    settings = request.app.state.settings
    site = site_store.resolved_manifest(conn, settings)
    return {
        "schema": 1,
        "org_name": site["org_name"],
        # BRAND INDIRECTION (2026-08-17, COMMERCIAL_READINESS.md item 10).
        # `org_short` is the customer's name where only a few characters fit
        # (topbar, tray tooltip); `product_name` is the VENDOR's, which is why
        # it alone has a non-blank default. Every consumer falls back
        # org_short -> org_name -> product_name, so an unbranded install shows
        # the product rather than another tenant's studio.
        "org_short": site["org_short"] or site["org_name"],
        "product_name": site["product_name"] or "CC Sync",
        # The fleet's own tray/window mark (2026-08-18). Additive to schema 1
        # like `features`: a companion too old to read it wears the product
        # mark, which is the same thing a blank here means, so an old client
        # and a silent server agree. Blank is the VENDOR default on purpose --
        # a site that has never said must not inherit another tenant's logo.
        "brand_logo": site["brand_logo"],
        "tree_name": site["tree_name"],
        "canonical_prefix": site["canonical_prefix"],
        "remote_root": site["remote_root"],
        # The companion reads this into server_p_unc instead of deriving it
        # from remote_root -- derive_server_unc() only knows /mnt/<pool>/<rest>
        # (WP5 / drive_swap.py).
        "smb_unc": site["smb_unc"],
        "sftp_host": site["sftp_host"],
        "sftp_port": site["sftp_port"],
        # See settings.site_sftp_chunk_size: the NAS's sshd decides the safe
        # rclone chunk size, so the server states it (2026-08-17).
        "sftp_chunk_size": site["sftp_chunk_size"],
        "sftp_concurrency": site["sftp_concurrency"],
        "sftp_shell_type": site["sftp_shell_type"],
        "rclone_remote": site["rclone_remote"],
        "nas_syncthing_id": _nas_syncthing_id(request, conn),
        "dashboard_url": site["dashboard_url"],
        # Shipped from provision.py (env-derived) UNLESS a site_settings row
        # overrides it (site_store.resolved_manifest); either way the tree an
        # installer expects and the tree /project-setup creates cannot drift
        # apart. server/common.py holds the same two lists and
        # server/tests/test_cross_component.py pins them byte-identical for
        # the env-only shape.
        "template_folders": site["template_folders"],
        "shared_asset_folders": site["shared_asset_folders"],
        # READ-ONLY, and deliberately not configurable: which extensions are
        # "video" decides what travels by rclone (lanes A/B) instead of
        # Syncthing (lane C), so the three copies of this list must stay
        # byte-identical or a media type gets carried by both or by neither
        # (server/tests/test_cross_component.py). provision.py is the
        # canonical copy; publishing it lets a future client read it instead
        # of growing a fourth (2026-08-17, COMMERCIAL_READINESS.md item 11).
        "video_extensions": list(provision.VIDEO_EXTENSIONS),
        # Where this fleet's vendor artefacts live, as a DIRECTORY prefix: the
        # configured `DASH_RELEASE_FEED_URL` minus its `channel.json`
        # (docs/RELEASE_FEED.md). Published because the companion needs it to
        # fetch the CLAP audio model for music ingest, and because no vendor
        # host may be written down in this repo -- the same rule that keeps a
        # CUSTOMER's name out of it (docs/MUSIC_INGEST_PLAN.md step 3;
        # music_clap_sidecar.feed_base reads exactly this key).
        #
        # NOT A SECRET and not a credential: the feed is world-readable static
        # files whose every byte is signature- and sha256-verified after the
        # fact, and a client that fetched from the wrong host would simply
        # fail those checks. Empty when no feed is configured, which every
        # client reads as "this fleet cannot fetch models" -- a refusal with a
        # fix, not an error.
        "release_feed_base": _release_feed_base(settings),
        "nas_kind": site["nas_kind"],
        # Optional features this site has turned on. Additive to schema 1 on
        # purpose (companion/site.py reads unknown-to-it keys as absent), and
        # BOTH DEFAULT FALSE: a client that cannot read this key, or reaches a
        # dashboard too old to send it, must behave as if the feature is off
        # rather than as if it is on (COMMERCIAL_READINESS.md items 2 + 3).
        "features": {
            "youtube_download": site["features"]["youtube_download"],
            # Never true on its own -- the unblock components only exist to
            # serve the downloader, and a site that answered
            # {download: false, unblock: true} would be telling companions to
            # install a JS challenge solver for a feature they cannot use.
            "youtube_unblock": bool(site["features"]["youtube_download"]
                                    and site["features"]["youtube_unblock"]),
        },
        # Which LOCAL vision model the b-roll indexer should load: "good"
        # (Qwen3-VL 4B, needs 8 GB VRAM) or "best" (Qwen3-VL 8B, needs 12 GB),
        # chosen on Settings by how much VRAM the indexing machine has
        # (2026-08-18). A NEW top-level object rather than a third `features`
        # entry -- it is a choice between two shipped models, not an
        # on/off switch, and the indexer already has its own per-machine
        # override in config.toml if this ever disagrees with the box it is
        # actually running on. Additive to `schema: 1`, same as `features`
        # was: an indexer too old to read this key defaults to "good" itself
        # (see broll/indexer's local_models.TIERS).
        "indexer": {
            "model_tier": site["indexer"]["model_tier"],
        },
    }


def _release_feed_base(settings: Any) -> str:
    """`DASH_RELEASE_FEED_URL` minus the filename, or "".

    Derived rather than configured separately, so there is exactly one URL an
    operator sets and no way for the two to disagree about which feed this
    fleet trusts. Anything that is not an https URL ending in a filename comes
    back "" -- release_feed.py already refuses a non-https feed at boot, and a
    client with no base simply does not download.
    """
    raw = str(getattr(settings, "release_feed_url", "") or "").strip()
    if not raw.lower().startswith("https://"):
        return ""
    base = raw.rsplit("/", 1)[0] if "/" in raw.split("://", 1)[1] else ""
    return base.rstrip("/")


@router.get("/projects")
def api_projects(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    return _scope_projects_view(build_projects_view(conn), auth.scope_for(request))


@router.get("/projects/{slug}")
def api_project(
    slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    view = build_project_view(conn, slug)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    return _scope_project_view(view, auth.scope_for(request))


@router.get("/transfers")
def api_transfers(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    scope = auth.scope_for(request)
    return build_transfers_view(conn, editor=scope.editor)


@router.get("/projects/{slug}/presence")
def api_presence(
    slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    scope = auth.scope_for(request)
    view = build_presence_view(conn, slug, editor=scope.editor)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    return view


@router.get("/projects/{slug}/devices/{device_id}/missing")
def api_missing(
    slug: str, device_id: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    project = db.fetch_project(conn, slug)
    if project is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    device = next((e for e in project["editors"] if e["device_id"] == device_id), None)
    if device is None:
        raise HTTPException(status_code=404, detail=f"device not in project: {device_id}")
    # The one route in this group that answers actual FILE PATHS -- what is
    # missing from a named person's machine. 404, not 403: an editor has no
    # business learning that another editor's device id even exists here.
    scope = auth.scope_for(request)
    if not scope.allows(str(device.get("editor_username") or "")):
        raise HTTPException(status_code=404, detail=f"device not in project: {device_id}")
    result = db.fetch_missing(conn, project["id"], device["device_row_id"])
    result["need_items"] = device["need_items"]
    return result


@router.get("/editors")
def api_editors(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    return _scope_editors_view(build_editors_view(conn), auth.scope_for(request))


def build_queue_view(conn: sqlite3.Connection, editor: str, now: str | None = None,
                     projects_view: dict[str, Any] | None = None) -> dict[str, Any]:
    """The editor's ordered sync queue with per-project progress, for MY QUEUE.

    `projects_view` lets a caller that has already built the fleet snapshot
    hand it over. The fleet page renders the sidebar (build_projects_view) and
    this panel side by side, and used to build the whole snapshot -- collector
    status + lanes + the N+1 fetch_projects -- twice per render, from two
    independently-taken `now` values, so the sidebar's status dots and this
    panel's percentages came from two different reads of the same tables
    (DASH-6, 2026-08-14)."""
    if projects_view is not None:
        now = now or projects_view.get("generated_at") or db.utcnow_iso()
    else:
        now = now or db.utcnow_iso()
        projects_view = build_projects_view(conn, now)
    projects = {p["slug"]: p for p in projects_view["projects"]}
    lane_rows = _lanes_by_editor(conn).get(editor, [])
    # The companion reports current_project as a project SLUG.
    current = next((r["current_project"] for r in lane_rows if r["current_project"]), None)
    rclone_by_project = {
        r["current_project"]: r for r in lane_rows
        if r["current_project"] and r["speed_bps"] is not None
    }
    items = []
    for sel in db.fetch_selections(conn, editor):
        slug = sel["slug"]
        project = projects.get(slug)
        my_rows = [e for e in project["editors"] if e["editor_username"] == editor] if project else []
        best = my_rows[0] if my_rows else None
        rclone = rclone_by_project.get(slug)
        items.append({
            "slug": slug,
            "label": sel["label"] or slug,
            "position": sel["position"],
            "missing_project": project is None,
            "is_current": slug == current,
            "completion": best["completion"] if best else None,
            "need_items": best["need_items"] if best else None,
            "need_bytes": best["need_bytes"] if best else None,
            "rate_bytes_per_sec": (rclone["speed_bps"] if rclone else None)
                                   or (best["rate_bytes_per_sec"] if best else None),
            "eta_seconds": (rclone["eta_seconds"] if rclone else None)
                            or (best["eta_seconds"] if best else None),
            "status": best["status"] if best else "green",
        })
    ticked = {i["slug"] for i in items}
    available = [
        {"slug": s, "label": p["label"]}
        for s, p in sorted(projects.items(), key=lambda kv: kv[1]["label"])
        if s not in ticked
    ]
    def label_of(slug):
        return projects[slug]["label"] if slug in projects else slug

    machine = db.latest_machine_state(conn, editor)
    resolve_project = machine["resolve_project"] if machine else None
    root_slug = machine["detected_project_root"] if machine else None
    root_source = None
    if resolve_project:
        mapping = conn.execute(
            "SELECT source FROM project_roots WHERE resolve_project = ?", (resolve_project,)
        ).fetchone()
        root_source = mapping["source"] if mapping else None

    return {"editor": editor, "generated_at": now, "queue": items,
            "available": available, "current_project": current,
            "resolve_project": resolve_project,
            "root_slug": root_slug,
            "root_label": label_of(root_slug) if root_slug else None,
            "root_source": root_source}


# ------------------------------------------------------------------ auth

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
def api_login(payload: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.session_secret:
        raise HTTPException(status_code=503, detail="login not configured (DASH_SESSION_SECRET unset)")
    username = payload.username.strip().lower()
    # Per-username AND per-IP budget, in SQLite so it survives the restart
    # every deploy performs (auth.login_throttled, 2026-08-17).
    if auth.login_throttled(request, username):
        raise HTTPException(status_code=429, detail="too many failed attempts; wait and retry")
    verifier = getattr(request.app.state, "credential_verifier", auth.verify_credentials)
    try:
        verified = verifier(settings, username, payload.password)
    except auth.CredentialProbeBusy as exc:
        raise HTTPException(status_code=503, detail=f"login busy: {exc} -- try again") from exc
    if not verified:
        auth.record_login_failure(request, username)
        raise HTTPException(status_code=401, detail="bad username or password")
    auth.clear_login_failures(request, username)
    # Mints the cookie AND the revocable server-side session row (HttpOnly,
    # SameSite=Lax, Secure per auth.cookie_secure) -- see auth.start_session.
    auth.start_session(request, response, username)
    return {"ok": True, "user": username, "is_admin": auth.is_admin(settings, username)}


@router.post("/logout")
def api_logout(request: Request, response: Response) -> dict[str, Any]:
    # Revokes the server-side session, not just the browser's copy of the
    # cookie: a logout that leaves a stolen cookie working is not a logout.
    auth.end_session(request, response)
    return {"ok": True}


class VerifyIn(LoginIn):
    # Optional so pre-upgrade-channel companions keep verifying fine; when
    # present, the response may carry the same conditional "upgrade" key as
    # the report reply (see _upgrade_info).
    companion_version: str | None = None
    platform: str | None = None


def _require_fleet_member(settings, username: str) -> None:
    """Refuse to mint a companion identity (and hand out the shared report
    token) for an SMB account that isn't part of this fleet.

    The credential check is an SMB session setup, so ANY account the NAS's
    SMB service accepts -- a bookkeeper, a guest share user, truenas_admin --
    used to come back with a valid identity token AND report_token, i.e. the
    ability to write reports as themselves and read every editor's selection.
    Membership of the `editors` group (or DASH_ADMIN_USERS) is the same
    fleet definition create_or_update_editor already enforces.

    Degrades the way build_admin_users_view does: with no NAS credentials
    there is nothing to check against, so the check is skipped (and logged)
    rather than locking every companion out of a NAS-less deployment. A NAS
    that is configured but unreachable answers 503 -- retryable, never open.
    """
    if auth.is_admin(settings, username):
        return
    if not nas_factory.nas_configured(settings):
        log.warning(
            "minting an identity for %r without an editors-group check: DASH_NAS_PW is not "
            "configured on the dashboard", username)
        return
    try:
        client = nas_factory.make_nas_client(settings)
        allowed = client.is_editor(username)
    except NasError as exc:
        # /api/v1/verify is OPEN (app.py's _OPEN_EXACT) -- it is how a companion
        # bootstraps -- so a NasError's text, which names the NAS host and its
        # API path, would be readable by anyone who can reach the port. Logged
        # here, generic on the wire (COMMERCIAL_READINESS.md §C L "error detail
        # leaks", 2026-08-17).
        log.warning("fleet-membership check for %r failed: %s", username, exc)
        raise HTTPException(
            status_code=503,
            detail="cannot confirm fleet membership right now -- try again shortly",
        ) from exc
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=f"{username!r} is not in the '{EDITORS_GROUP}' group on the NAS -- "
                   "ask an admin to add the account in Admin > Users",
        )


@router.post("/verify")
def api_verify(
    payload: VerifyIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    """Companion machine-identity verification: same credential check as the
    browser login, but returns a long-lived signed identity token the
    companion stores to prove whose machine it is. Open (no session needed),
    but only for accounts that are actually in the fleet (see
    _require_fleet_member)."""
    settings = request.app.state.settings
    if not settings.session_secret:
        raise HTTPException(status_code=503, detail="identity not configured (DASH_SESSION_SECRET unset)")
    username = payload.username.strip().lower()
    if auth.login_throttled(request, username):
        raise HTTPException(status_code=429, detail="too many failed attempts; wait and retry")
    verifier = getattr(request.app.state, "credential_verifier", auth.verify_credentials)
    try:
        verified = verifier(settings, username, payload.password)
    except auth.CredentialProbeBusy as exc:
        raise HTTPException(status_code=503, detail=f"verify busy: {exc} -- try again") from exc
    if not verified:
        auth.record_login_failure(request, username)
        raise HTTPException(status_code=401, detail="bad username or password")
    auth.clear_login_failures(request, username)
    _require_fleet_member(settings, username)
    result = {
        "ok": True,
        "username": username,
        "token": auth.make_identity_token(settings.session_secret, username),
        # The report token is a shared secret every editor's companion uses;
        # hand it to a just-verified editor so onboarding needs no extra
        # copy-paste of secrets. Empty when the server has none configured.
        "report_token": settings.report_token,
        # "base" (direct-NAS-access machine, e.g. the admin's own rig) vs
        # "editor" (normal remote sync lanes) -- same DASH_ADMIN_USERS list
        # that gates dashboard admin actions, reused here by design (see
        # docs/SERVER.md's "Admin: Users section"). The companion uses this
        # to flip its sync behavior on sign-in instead of trusting a
        # hand-edited local config.toml `mode` value -- see
        # companion/src/ccsync_companion/identity.py.
        "role": "base" if auth.is_admin(settings, username) else "editor",
    }
    upgrade = _upgrade_info(conn, payload.platform, payload.companion_version)
    if upgrade is not None:
        result["upgrade"] = upgrade
    return result


@router.get("/me")
def api_me(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    return {"user": user, "is_admin": auth.is_admin(settings, user)}


# ------------------------------------------------------------------ selection

def _project_roots_view(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    labels = {r["slug"]: r["label"] for r in conn.execute("SELECT slug, label FROM projects")}
    return [
        {
            "resolve_project": r["resolve_project"],
            "slug": r["project_slug"],
            "rel_path": labels.get(r["project_slug"], r["project_slug"]),
            "source": r["source"],
            "updated_by": r["updated_by"],
            "updated_at": r["updated_at"],
        }
        for r in db.fetch_project_roots(conn)
    ]


def _selection_view(conn: sqlite3.Connection, editor: str) -> dict[str, Any]:
    rows = db.fetch_selections(conn, editor)
    return {
        "editor": editor,
        "generated_at": db.utcnow_iso(),
        # Sticky Resolve-project -> destination-root mappings (admin-managed).
        "project_roots": _project_roots_view(conn),
        "selection": [
            {
                "slug": r["slug"],
                "label": r["label"],
                "rel_path": r["label"],   # folder label IS the year/series/project rel path
                "position": r["position"],
                "active": bool(r["active"]) if r["active"] is not None else False,
            }
            for r in rows
        ],
    }


def _require_selection_read(request: Request, editor: str,
                            conn: sqlite3.Connection | None = None) -> None:
    """Session (self or admin), or the companion's token PLUS a matching
    identity header.

    The report token is a SHARED secret every editor's companion holds (it is
    handed out by /api/v1/verify), so on its own it proved nothing about WHOSE
    selection was being read -- any editor could enumerate the whole fleet's
    queues and sticky project-root mappings. This is the same identity rule
    /api/v1/report already applies, and the same carve-out: a server with no
    DASH_SESSION_SECRET cannot mint or verify identity tokens at all, so
    requiring one there would just break lab deployments."""
    settings = request.app.state.settings
    token = request.headers.get("x-ccsync-token", "")
    auth_kind, token_editor = resolve_companion_credential(settings, conn, token)
    if auth_kind == AUTH_EDITOR:
        # A per-editor token IS the identity, so it stands on its own -- and it
        # binds: it can only read the selection of the editor it was minted for
        # (COMMERCIAL_READINESS.md item 15, 2026-08-17).
        if token_editor == editor:
            return
        raise HTTPException(
            status_code=401,
            detail="this X-CCSync-Token belongs to a different editor",
        )
    if auth_kind == AUTH_SHARED:
        if not settings.session_secret:
            return  # cannot mint or check identities at all -- token is all there is
        identity = request.headers.get("x-ccsync-identity", "")
        id_user = auth.read_identity_token(settings.session_secret, identity)
        if id_user is not None and id_user == editor:
            return  # companion access, proven to be this editor's machine
        raise HTTPException(
            status_code=401,
            detail="X-CCSync-Identity required (and must match the editor) alongside "
                   "X-CCSync-Token -- sign in from the companion tray",
        )
    if auth.can_manage(settings, auth.get_session_user(request), editor):
        return
    raise HTTPException(status_code=401, detail="log in, or present X-CCSync-Token")


def _nudge_collector(request: Request) -> None:
    """Ask the in-process collector to reconcile sharing promptly -- a tick
    used to start syncing only after interval_enforce (up to 60s of dead
    air after the click, 2026-07-26). Never raises; absent in some tests."""
    collector = getattr(request.app.state, "collector", None)
    if collector is not None:
        try:
            collector.nudge()
        except Exception:
            pass


def _require_selection_write(request: Request, editor: str) -> str:
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if not auth.can_manage(settings, user, editor):
        raise HTTPException(
            status_code=403 if user else 401,
            detail="you can only change your own projects (admins excepted)",
        )
    return user


def _require_selection_untick(request: Request, editor: str,
                              conn: sqlite3.Connection | None = None) -> str:
    """_require_selection_write, plus the companion's token + a MATCHING
    identity header -- for UNTICK ONLY. The tray's "Remove this project from
    this machine" must untick before deleting (a delete while ticked just
    errors the Syncthing folder), so a machine may remove ITS OWN ticks.
    Ticking stays session-only on purpose: a compromised shared token plus
    one identity must not be able to start syncing projects TO machines."""
    settings = request.app.state.settings
    token = request.headers.get("x-ccsync-token", "")
    auth_kind, token_editor = resolve_companion_credential(settings, conn, token)
    if auth_kind == AUTH_EDITOR:
        if token_editor == editor:
            return f"companion:{editor}"
        raise HTTPException(
            status_code=401,
            detail="this X-CCSync-Token belongs to a different editor",
        )
    if auth_kind == AUTH_SHARED:
        if not settings.session_secret:
            return f"companion:{editor}"  # lab carve-out, same as reads
        identity = request.headers.get("x-ccsync-identity", "")
        id_user = auth.read_identity_token(settings.session_secret, identity)
        if id_user is not None and id_user == editor:
            return f"companion:{editor}"
        raise HTTPException(
            status_code=401,
            detail="X-CCSync-Identity required (and must match the editor) alongside "
                   "X-CCSync-Token -- sign in from the companion tray",
        )
    return _require_selection_write(request, editor)


@router.get("/selection/{editor}")
def api_get_selection(
    editor: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    editor = editor.strip().lower()
    _require_selection_read(request, editor, conn)
    return _selection_view(conn, editor)


@router.put("/selection/{editor}/{slug}")
def api_tick(
    editor: str, slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    editor = editor.strip().lower()
    user = _require_selection_write(request, editor)
    project = conn.execute(
        "SELECT slug FROM projects WHERE slug=? AND active=1", (slug,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail=f"unknown or inactive project {slug!r}")
    added = db.add_selection(conn, editor, slug, created_by=user, now=db.utcnow_iso())
    conn.commit()
    _nudge_collector(request)
    view = _selection_view(conn, editor)
    view["changed"] = added
    return view


@router.delete("/selection/{editor}/{slug}")
def api_untick(
    editor: str, slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    editor = editor.strip().lower()
    _require_selection_untick(request, editor, conn)
    removed = db.remove_selection(conn, editor, slug)
    conn.commit()
    _nudge_collector(request)
    view = _selection_view(conn, editor)
    view["changed"] = removed
    return view


class ProjectRootIn(BaseModel):
    resolve_project: str = Field(min_length=1, max_length=256)
    slug: str | None = None   # None = delete the mapping (re-detected on next report)


def _require_admin(request: Request) -> str:
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="log in first")
    if not auth.is_admin(settings, user):
        raise HTTPException(status_code=403, detail="admins only: destination roots are fixed once set")
    return user


@router.get("/project-roots")
def api_project_roots(conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    return {"project_roots": _project_roots_view(conn)}


@router.put("/project-roots")
def api_set_project_root(
    payload: ProjectRootIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    """Tiered: an editor may FIRST-SET an unmapped Resolve project that ONE OF
    THEIR OWN MACHINES HAS REPORTED (first-write-wins, so races resolve at the
    DB); deleting or CHANGING an existing mapping stays admin-only ("fixed
    once set"). Admins may first-set anything. See may_first_claim: the
    un-scoped version let any editor claim any name, including one only
    another editor's companion had ever opened."""
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="log in first")
    name = payload.resolve_project.strip()
    slug = (payload.slug or "").strip() or None
    existing = conn.execute(
        "SELECT project_slug FROM project_roots WHERE resolve_project=?", (name,)
    ).fetchone()

    if slug is None:
        _require_admin(request)
        db.delete_project_root(conn, name)
    else:
        exists = conn.execute(
            "SELECT 1 FROM projects WHERE slug=? AND active=1", (slug,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail=f"unknown or inactive project {slug!r}")
        if existing is not None:
            admin = _require_admin(request)
            db.admin_set_project_root(conn, name, slug, admin=admin, now=db.utcnow_iso())
        else:
            if not may_first_claim(settings, conn, user, name):
                raise HTTPException(
                    status_code=403,
                    detail=f"{name!r} is not a Resolve project any of your machines has "
                           "reported -- open it in Resolve first, or ask an admin",
                )
            inserted = db.sticky_project_root(
                conn, name, slug, db.utcnow_iso(), source="editor", updated_by=user
            )
            if not inserted:
                conn.commit()
                raise HTTPException(
                    status_code=409,
                    detail="already mapped -- ask an admin to change it",
                )
    conn.commit()
    return {"ok": True, "project_roots": _project_roots_view(conn)}


# --------------------------------------------------- project setup / creation

class ProjectSetupError(Exception):
    """User-fixable problem with a create-project request; the message is
    shown verbatim in the UI banner / API 422 detail."""


class FolderExistsError(ProjectSetupError):
    """create_tree_project's target directory already exists on the NAS and
    the caller did not ask to reuse it. Carries `rel` so the picker can offer
    a one-click "use that folder instead" -- without it the only remaining
    action was "type another name", which is how
    2026/CCT/Website Highlights/Website Highlights happened."""

    def __init__(self, message: str, rel: str):
        super().__init__(message)
        self.rel = rel


_YEAR_RE = re.compile(r"^\d{4}$")


def _validate_tree_part(value: str, what: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ProjectSetupError(f"{what} is required")
    if "/" in value or "\\" in value:
        raise ProjectSetupError(f"{what} must not contain slashes")
    if value.startswith(".") or ".." in value:
        raise ProjectSetupError(f"{what} must not start with '.' or contain '..'")
    if any(ord(ch) < 32 for ch in value):
        # NUL/control characters make Path.resolve() raise ValueError (not
        # OSError), which would otherwise escape the ProjectSetupError -> 422
        # handling and surface as a 500 traceback.
        raise ProjectSetupError(f"{what} must not contain control characters")
    return value


def _projects_dir_or_error(settings) -> Path:
    projects_dir = str(getattr(settings, "projects_dir", "") or "")
    if not projects_dir or not Path(projects_dir).is_dir():
        raise ProjectSetupError(
            "the NAS Projects tree is not mounted on the dashboard "
            "(DASH_PROJECTS_DIR) -- create the folder with server/setup_tree.py instead"
        )
    return Path(projects_dir)


def _safe_rel(settings, rel: str) -> tuple[Path, str]:
    """Validate a user-supplied posix rel path and resolve it under
    projects_dir. Returns (absolute_path, normalized_rel). '' means the
    Projects root itself. Raises ProjectSetupError on traversal attempts."""
    projects_dir = _projects_dir_or_error(settings)
    rel = str(rel or "").strip().strip("/")
    if not rel:
        return projects_dir, ""
    parts = [_validate_tree_part(p, "path segment") for p in rel.split("/")]
    normalized = "/".join(parts)
    target = (projects_dir / Path(*parts)).resolve()
    # is_relative_to, not a string prefix: the old check would have accepted a
    # sibling '<projects_dir>-old' (not currently reachable, but one segment
    # validator change away from being so).
    if not target.is_relative_to(projects_dir.resolve()):
        raise ProjectSetupError("path escapes the Projects tree")
    return target, normalized


def _marked_ancestor(projects_dir: Path, rel: str) -> str | None:
    """The rel of the closest ancestor (or rel itself) carrying a project
    marker, or None. Projects cannot nest -- both create and link refuse
    inside an existing project. Shared with the collector's provision cycle,
    which enforces the same rule before creating a Syncthing folder."""
    from . import provision

    return provision.marked_ancestor(projects_dir, rel, include_self=True)


def _raise_if_container_of_projects(target: Path, rel: str) -> None:
    """Refuse a folder that CONTAINS projects -- a container is not a project.

    DASH-1, 2026-08-14: both create and link used to look for descendants with
    provision.scan_project_dirs(projects_dir), which prunes its os.walk at
    every marker it finds. A marker is a plain JSON file on a share every
    editor can write, so the case that actually needs catching -- someone
    dropped one on Projects/2026/CCT/, which holds three real projects -- is
    precisely the case that scan blinds itself to: it yields the container and
    stops, the descendant loop sees nothing, and the adopt/create succeeds.
    The projects row that gets written is then one the collector refuses to
    provision every cycle (collector._creatable, which has used
    marked_descendants all along), i.e. a project that silently never syncs.
    """
    from . import provision

    below = provision.marked_descendants(target)
    if not below:
        return
    first = f"{rel}/{below[0]}"
    more = f" (+{len(below) - 1} more)" if len(below) > 1 else ""
    raise ProjectSetupError(
        f"that folder already contains a project ({first}{more}) -- pick that instead"
    )


def may_first_claim(
    settings, conn: sqlite3.Connection, user: str | None, resolve_project: str
) -> bool:
    """May `user` create the FIRST sticky mapping for this Resolve project?

    Admins: always. Everyone else: only for a name one of their OWN machines
    has actually reported (machine_state). Without this scoping any signed-in
    editor could first-claim any unmapped Resolve project name -- including
    one only somebody else's companion has ever opened -- and permanently fix
    where that editor's media lands, with no way back but an admin edit."""
    if user is None:
        return False
    if auth.is_admin(settings, user):
        return True
    return db.editor_reported_resolve_project(conn, user, resolve_project)


def _register_project(
    settings, conn: sqlite3.Connection, rel: str, slug: str,
    resolve_project: str, user: str,
) -> dict[str, Any]:
    """Shared tail of create/adopt: eager projects row (active immediately;
    the provision cycle adds the Syncthing folder within ~5 min and the
    deactivation grace covers the gap) + sticky Resolve mapping."""
    now = db.utcnow_iso()
    resolve_project = (resolve_project or "").strip()
    if resolve_project and not may_first_claim(settings, conn, user, resolve_project):
        # Refuse BEFORE the projects row is written: half-claiming (folder
        # made, mapping silently skipped) is how an editor ends up believing
        # a project is set up when their companion still prompts for it.
        raise ProjectSetupError(
            f"{resolve_project!r} is not a Resolve project any of your machines has "
            "reported -- open it in Resolve first, or ask an admin to set the mapping"
        )
    st_path = f"{settings.syncthing_data_prefix.rstrip('/')}/{rel}"
    db.upsert_project(conn, slug, rel, st_path, now)
    mapped = False
    if resolve_project:
        mapped = db.sticky_project_root(
            conn, resolve_project, slug, now, source="editor", updated_by=user
        )
    return {"slug": slug, "rel": rel, "mapped": mapped}


def create_tree_project(
    settings,
    conn: sqlite3.Connection,
    parent_rel: str,
    name: str,
    resolve_project: str,
    user: str,
    use_existing: bool = False,
) -> dict[str, Any]:
    """Create Projects/<parent_rel>/<name> (any depth) with the standard
    template subfolders and a project marker, register + map it. Idempotent
    for the same rel. Caller commits.

    An already-existing target raises FolderExistsError unless it already
    carries this project's marker (partial-create convergence) or the caller
    passes use_existing=True -- the picker's [ USE THIS FOLDER ] (adopt_folder)
    is the normal way to point a project at a folder that is already there,
    and it does not touch the folder's contents. use_existing=True means
    "adopt it AND add the standard template subfolders"; every mkdir is
    exist_ok so a pre-populated folder is left alone."""
    from . import provision

    parent_path, parent_norm = _safe_rel(settings, parent_rel)
    if not parent_path.is_dir():
        raise ProjectSetupError(f"parent folder does not exist: {parent_norm or '(root)'}")
    name = _validate_tree_part(name, "project name")
    rel = f"{parent_norm}/{name}" if parent_norm else name

    projects_dir = _projects_dir_or_error(settings)
    inside = _marked_ancestor(projects_dir, rel.rsplit("/", 1)[0]) if "/" in rel else None
    if inside:
        raise ProjectSetupError(
            f"cannot create a project inside another project ({inside})"
        )
    # ...and no marked DESCENDANTS either (adopt_folder already checks this).
    # mkdir(exist_ok=True) happily reuses an existing directory, so "create
    # 2026/CCT" over a container that already holds three real projects would
    # otherwise drop a marker on the container: scan_project_dirs prunes at
    # it, all three vanish from discovery, and the collector then refuses to
    # provision the container forever (collector._creatable) -- a project that
    # silently never syncs.
    #
    # DASH-1, 2026-08-14: this used to ask scan_project_dirs for the WHOLE
    # tree, which prunes its walk at every marker -- so on the one path that
    # matters (the container already carries a hand-dropped marker, the
    # partial-create convergence branch below) the scan stopped AT the
    # container and the projects underneath were invisible to their own guard.
    # marked_descendants is the scoped look-below written for exactly this
    # (provision.py), and it walks the candidate directory instead of the
    # whole depth-8 Projects tree on every create POST.
    _raise_if_container_of_projects(parent_path / name, rel)

    try:
        slug = provision.slugify(rel)
    except ValueError:
        raise ProjectSetupError("that name produces an empty identifier -- use letters/numbers")

    target = parent_path / name
    exists = target.is_dir()
    existing_marker = provision.read_marker(target) if exists else None
    if existing_marker is not None and existing_marker != slug:
        raise ProjectSetupError(
            f"that folder is already a project with a different identity ({existing_marker})"
        )
    if exists and existing_marker is None and not use_existing:
        # Don't silently absorb (and template-ify) a folder someone already
        # made on the NAS -- offer it instead, so the answer to "my folder is
        # already there" stops being "type another name" (the double-nesting
        # bug).
        raise FolderExistsError(
            f"Projects/{rel} already exists -- use [ USE THIS FOLDER ] to point the project "
            "at it instead of creating another folder inside it",
            rel,
        )
    row = conn.execute("SELECT label FROM projects WHERE slug=?", (slug,)).fetchone()
    if row is not None and row["label"] != rel:
        raise ProjectSetupError(
            f"a different project already uses this identifier: {row['label']} -- pick another name"
        )

    try:
        target.mkdir(parents=True, exist_ok=True)
        for sub in provision.TEMPLATE_FOLDERS:
            (target / sub).mkdir(parents=True, exist_ok=True)
        provision.write_marker(target, slug, created_by=user)
    except OSError as exc:
        # The OSError text carries the NAS's ABSOLUTE path
        # (/mnt/<pool>/<tenant>/Projects/...), and this route is reachable by
        # any signed-in editor -- logged, not answered (COMMERCIAL_READINESS.md
        # §C L "error detail leaks", 2026-08-17).
        log.warning("could not create project folders for %r: %s", rel, exc)
        raise ProjectSetupError(
            "could not create the folders on the NAS -- ask an admin to check the "
            "dashboard log")

    return _register_project(settings, conn, rel, slug, resolve_project, user)


def adopt_folder(
    settings,
    conn: sqlite3.Connection,
    rel: str,
    resolve_project: str,
    user: str,
) -> dict[str, Any]:
    """Claim an EXISTING folder (any depth) as a project: write its marker
    (or adopt the one it already carries), register + map it. This is the
    picker's [ USE THIS FOLDER ] flow -- for a browsed child row AND for the
    folder the browser is currently standing in. Contents are never touched
    (no template subfolders), so a folder already full of media adopts
    cleanly. Caller commits."""
    from . import provision

    projects_dir = _projects_dir_or_error(settings)
    target, rel = _safe_rel(settings, rel)
    if not rel:
        raise ProjectSetupError("pick a folder -- the Projects root itself cannot be a project")
    if not target.is_dir():
        raise ProjectSetupError(f"folder does not exist: {rel}")

    marked = _marked_ancestor(projects_dir, rel)
    if marked is not None and marked != rel:
        raise ProjectSetupError(f"this folder is inside an existing project ({marked})")
    # No marked descendants either -- a container of projects isn't a project.
    # Scoped look-below, not a whole-tree scan: see _raise_if_container_of_
    # projects (DASH-1, 2026-08-14) for why the whole-tree scan could not see
    # them once the container itself carried a marker.
    _raise_if_container_of_projects(target, rel)

    slug = provision.read_marker(target)
    if slug is None:
        try:
            slug = provision.slugify(rel)
        except ValueError:
            raise ProjectSetupError("that folder name produces an empty identifier")
        row = conn.execute("SELECT label FROM projects WHERE slug=?", (slug,)).fetchone()
        if row is not None and row["label"] != rel:
            raise ProjectSetupError(
                f"a different project already uses this identifier: {row['label']}"
            )
        try:
            provision.write_marker(target, slug, created_by=user)
        except OSError as exc:
            raise ProjectSetupError(f"could not write the project marker: {exc}")
    else:
        # Folder already carries an identity (e.g. a moved project) -- adopt
        # it, but refuse if that identity's registered dir ALSO still exists
        # elsewhere (a copy, not a move).
        row = conn.execute("SELECT label FROM projects WHERE slug=?", (slug,)).fetchone()
        if row is not None and row["label"] != rel:
            other = projects_dir / Path(*row["label"].split("/"))
            if other.is_dir():
                raise ProjectSetupError(
                    f"this folder claims the identity of {row['label']}, which still exists -- "
                    "resolve the duplicate on the NAS first"
                )

    return _register_project(settings, conn, rel, slug, resolve_project, user)


class CreateProjectIn(BaseModel):
    parent_rel: str = Field(default="", max_length=512)
    name: str = Field(min_length=1, max_length=128)
    resolve_project: str = Field(default="", max_length=256)
    # opt-in "the folder is already there, use it" -- see create_tree_project
    use_existing: bool = False


class LinkFolderIn(BaseModel):
    rel: str = Field(min_length=1, max_length=512)
    resolve_project: str = Field(default="", max_length=256)


@router.post("/projects")
def api_create_project(
    payload: CreateProjectIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    user = auth.get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="log in first")
    try:
        result = create_tree_project(
            request.app.state.settings, conn,
            payload.parent_rel, payload.name, payload.resolve_project, user,
            use_existing=payload.use_existing,
        )
    except ProjectSetupError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    conn.commit()
    return {"ok": True, **result, "project_roots": _project_roots_view(conn)}


@router.post("/projects/link")
def api_link_folder(
    payload: LinkFolderIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    user = auth.get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="log in first")
    try:
        result = adopt_folder(
            request.app.state.settings, conn, payload.rel, payload.resolve_project, user,
        )
    except ProjectSetupError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    conn.commit()
    return {"ok": True, **result, "project_roots": _project_roots_view(conn)}


# ------------------------------------------------------------- admin users

def build_admin_users_view(settings, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Everything the admin 'Users' section needs: local accounts (WP C,
    docs/ZERO_TOUCH_PLAN.md §3.3, 2026-08-17) when this site is
    DASH_AUTH_METHOD=local, existing NAS editor accounts, plus devices that
    still need approving/naming (Syncthing devices that are either truly
    pending, or already configured but with a name that doesn't resolve to a
    username -- see db.resolve_editor_username).

    Returns {"error": <str>} instead of raising when a backend is
    unreachable, mirroring the rest of the dashboard's "stale banner, don't
    crash the page" convention.

    The two backends fail INDEPENDENTLY (DASH-7, 2026-08-14). A NAS blip
    used to return early with pending_devices=[] as well, so the panel's
    Syncthing half -- the device-approval table, which is the whole reason an
    admin has this page open while somebody's machine is being onboarded --
    vanished behind a banner about an unrelated backend. `truenas_error` and
    `syncthing_error` say WHICH half is missing so the template can avoid
    reporting an unreachable backend as "none pending".

    The `truenas_*` key names outlive the TrueNAS-only era on purpose: the
    admin_users template, the JSON API and this suite all read them, and
    renaming a published response shape is not what WP1 is for.

    `conn` is optional: most callers already hold one (Depends(get_conn));
    when absent, a short-lived one is opened here -- local accounts exist
    independently of any NAS credential, so this half must never wait on one.
    """
    method = str(getattr(settings, "auth_method", "") or "smb").strip().lower()
    result: dict[str, Any] = {"auth_method": method, "local_users": None}
    if method == "local":
        owned = conn is None
        c = conn if conn is not None else db.connect(settings.db_path)
        try:
            result["local_users"] = local_users.list_users(c)
        finally:
            if owned:
                c.close()

    if not nas_factory.nas_configured(settings):
        # No NAS credential: the appliance's default shape (ZERO_TOUCH_PLAN.md
        # §5, "the customer's NAS admin credential is optional"). This is no
        # longer a reason to 503 or hide the whole page -- local_users above
        # already answered the identity question; the NAS section (editor
        # accounts, device approval) simply has nothing to show.
        result.update({"truenas_configured": False, "editors": [], "pending_devices": [],
                       "error": None, "truenas_error": None, "syncthing_error": None})
        return result

    truenas_error: str | None = None
    editors: list[dict[str, Any]] = []
    try:
        editors = nas_factory.make_nas_client(settings).list_editors()
    except NasError as exc:
        truenas_error = f"{settings.nas_kind}: {exc}"

    # The stack's own service account is plumbing, not a person: it must never
    # appear on the Users page (it did on the first Synology bring-up, as an
    # "editor" with a MISSING ssh key -- 2026-08-17). Filtered here, once, for
    # every backend, on top of the install-time rule that it is not in the group.
    service_user = (getattr(settings, "nas_service_user", "") or "").strip().lower()
    if service_user:
        editors = [u for u in editors if str(u.get("username", "")).lower() != service_user]

    editor_rows = [{
        "username": u["username"],
        "uid": u.get("uid"),
        "full_name": u.get("full_name") or u["username"],
        "smb": bool(u.get("smb")),
        "has_ssh_key": bool(u.get("sshpubkey")),
        "home": u.get("home"),
        "locked": bool(u.get("locked")),
    } for u in sorted(editors, key=lambda u: u["username"])]

    syncthing_error: str | None = None
    pending: list[dict[str, Any]] = []
    if settings.syncthing_url:
        syncthing = SyncthingClient.from_settings(settings)
        try:
            cfg = syncthing.config()
            my_id = syncthing.system_status().get("myID", "")
            configured_ids = {d["deviceID"] for d in cfg.get("devices", [])}
            for d in cfg.get("devices", []):
                if d["deviceID"] == my_id:
                    continue
                if db.resolve_editor_username(d.get("name") or "") is None:
                    pending.append({
                        "device_id": d["deviceID"],
                        "current_name": d.get("name") or "",
                        "status": "unmapped",
                    })
            for device_id, info in (syncthing.pending_devices() or {}).items():
                if device_id in configured_ids:
                    continue
                pending.append({
                    "device_id": device_id,
                    "current_name": (info or {}).get("name") or "",
                    "status": "pending",
                })
        except SyncthingError as exc:
            syncthing_error = f"syncthing: {exc}"
            pending = []

    result.update({
        "truenas_configured": True,
        "editors": editor_rows,
        "pending_devices": pending,
        # kept as one string for existing callers/tests; the per-backend keys
        # are what the template renders each half's empty state from
        "error": "; ".join(e for e in (truenas_error, syncthing_error) if e) or None,
        "truenas_error": truenas_error,
        "syncthing_error": syncthing_error,
    })
    return result


def _nas_client_or_503(request: Request) -> NasBackend:
    """The admin section's client, or a 503 saying it isn't configured.

    503 rather than 500: "this deployment has no NAS credentials" is a
    configuration state the rest of the dashboard runs happily in, and a
    caller should be told to try later/elsewhere, not that we crashed.
    """
    settings = request.app.state.settings
    if not nas_factory.nas_configured(settings):
        raise HTTPException(status_code=503, detail="DASH_NAS_PW is not configured on the dashboard")
    try:
        return nas_factory.make_nas_client(settings)
    except NasError as exc:
        # An unknown DASH_NAS_KIND: a misconfiguration, not a request error.
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# WP1 transition alias (2026-08-17): the name six months of this file used.
_truenas_client_or_503 = _nas_client_or_503


class CreateEditorIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    # Required for a NAS account, optional for a local one (WP C): a local
    # account's dashboard/SFTP login is the password below, and an SSH key --
    # if given here -- is added the same way local.add_ssh_key would. The
    # looks_like_ssh_pubkey check runs inside whichever branch uses it.
    ssh_pubkey: str | None = None
    full_name: str | None = None
    # Optional: absent still means "randomise it, no dashboard login". Present
    # means it must clear the same floor as SetPasswordIn.
    password: str | None = Field(default=None, min_length=auth.MIN_PASSWORD_CHARS)
    # Local accounts only: "admin" or "editor" (local_users.ROLES), default
    # editor. Ignored by the NAS branch -- role there is "in the editors
    # group", which create_or_update_editor always grants.
    role: str | None = None


class SetPasswordIn(BaseModel):
    # min_length is auth.MIN_PASSWORD_CHARS, not 1 (2026-08-17,
    # COMMERCIAL_READINESS.md item 15's "admin password min length 1"). Floor
    # on what this dashboard SETS only: existing short NAS passwords keep
    # working, because locking a fleet out mid-shoot is not a security
    # improvement. The htmx twin (ui.partial_admin_set_password) checks the
    # same floor with a readable message instead of a 422.
    password: str = Field(min_length=auth.MIN_PASSWORD_CHARS)


class ApproveDeviceIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=32)


# Intentional copy of server/accept_device.py's DEVICE_ID_RE: 8 dash-separated
# groups of 7 base32 characters (RFC 4648 minus 0/1/8/9). Deliberately lenient
# -- it does not verify the interleaved Luhn check characters, only the shape,
# so a typo'd-but-well-formed ID still reaches Syncthing (which does check
# them) rather than being rejected here for the wrong reason.
#
# The shape was checked on the SERVER SCRIPT side only, so a truncated paste
# into the dashboard's approve dialog went straight through to Syncthing and
# came back as a generic 502 with no hint at what was wrong.
_DEVICE_ID_RE = re.compile(r"^[A-Z2-7]{7}(-[A-Z2-7]{7}){7}$")


def normalize_device_id(device_id: str) -> str:
    """Uppercase + shape-check a Syncthing device ID, or raise ValueError.
    Mirrors server/accept_device.normalize_device_id."""
    cleaned = str(device_id or "").strip().upper()
    if not _DEVICE_ID_RE.match(cleaned):
        raise ValueError(
            f"{device_id!r} is not a Syncthing device ID. Expected 8 groups of 7 "
            f"characters (A-Z, 2-7) separated by dashes, e.g. P56IOI7-MZJNU2Y-"
            f"IQGDREY-DM2MGTI-MGL3BXN-PQ6W5BM-TBBZ4TJ-XZWICQ2 -- copy it whole, it "
            f"is 63 characters. Adding a malformed ID creates a device entry that "
            f"can never connect."
        )
    return cleaned


def _local_mode(settings) -> bool:
    return str(getattr(settings, "auth_method", "") or "smb").strip().lower() == "local"


@router.get("/admin/users")
def api_admin_users(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    _require_admin(request)
    return build_admin_users_view(request.app.state.settings, conn)


@router.post("/admin/users")
def api_admin_create_user(
    payload: CreateEditorIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    admin = _require_admin(request)
    settings = request.app.state.settings
    username = payload.username.strip().lower()

    if _local_mode(settings):
        # No NAS account of any kind (WP C, docs/ZERO_TOUCH_PLAN.md §3.3,
        # 2026-08-17): create a row in the local `users` table instead. A
        # blank password generates a one-time one, returned ONCE in this
        # response and never stored anywhere the dashboard could show again.
        role = (payload.role or "editor").strip().lower()
        generated_password: str | None = None
        password = payload.password
        if not password:
            generated_password = secrets.token_urlsafe(15)
            password = generated_password
        try:
            result = local_users.create_user(conn, username, password, role, created_by=admin)
            if payload.ssh_pubkey:
                local_users.add_ssh_key(conn, username, payload.ssh_pubkey.strip())
        except local_users.LocalUserError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        db.record_known_editor(conn, username, "admin")
        conn.commit()
        response = {"ok": True, "result": result, "view": build_admin_users_view(settings, conn)}
        if generated_password:
            response["generated_password"] = generated_password
        return response

    nas = _nas_client_or_503(request)
    if not is_valid_username(username):
        raise HTTPException(
            status_code=422,
            detail="username must start with a letter and contain only lowercase letters, "
                   "digits, '.', '_', '-'",
        )
    ssh_pubkey = (payload.ssh_pubkey or "").strip()
    if not looks_like_ssh_pubkey(ssh_pubkey):
        raise HTTPException(status_code=422, detail="does not look like an OpenSSH public key")
    try:
        result = nas.create_or_update_editor(username, ssh_pubkey, payload.full_name)
        if payload.password:
            nas.set_known_password(username, payload.password)
            result["password_set"] = True
    except NasError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # The account provably exists now -- record it so a device named after it
    # is treated as an editor rather than as an unmapped machine (B16).
    db.record_known_editor(conn, username, "admin")
    conn.commit()
    return {"ok": True, "result": result, "view": build_admin_users_view(settings, conn)}


@router.post("/admin/users/{username}/password")
def api_admin_set_password(
    username: str, payload: SetPasswordIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Set a known password for an EDITOR account.

    The charset check is here as well as inside set_known_password: an
    admin's typo (or a URL-encoded 'root') must be a 422 from the dashboard,
    not a NAS round-trip that changes a system account's password. The
    refusals that actually matter -- uid < 1000, not in the editors group --
    live in each backend's set_known_password so every caller gets them."""
    _require_admin(request)
    username = username.strip().lower()
    settings = request.app.state.settings

    if _local_mode(settings):
        try:
            local_users.set_password(conn, username, payload.password)
        except local_users.LocalUserError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        conn.commit()
        return {"ok": True}

    if not is_valid_username(username):
        raise HTTPException(
            status_code=422,
            detail="username must start with a letter and contain only lowercase letters, "
                   "digits, '.', '_', '-'",
        )
    nas = _nas_client_or_503(request)
    try:
        nas.set_known_password(username, payload.password)
    except NasError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True}


def _require_local_mode(request: Request) -> None:
    if not _local_mode(request.app.state.settings):
        raise HTTPException(
            status_code=400,
            detail="this action is only available with DASH_AUTH_METHOD=local",
        )


class SetDisabledIn(BaseModel):
    disabled: bool = True


@router.post("/admin/users/{username}/disable")
def api_admin_disable_user(
    username: str, payload: SetDisabledIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Disable (or re-enable) a LOCAL account -- there is no NAS twin of this
    action in scope here (docs/ZERO_TOUCH_PLAN.md §5's TrueNAS/DSM `locked`
    field has no toggle on the NasBackend Protocol)."""
    _require_admin(request)
    _require_local_mode(request)
    settings = request.app.state.settings
    username = username.strip().lower()
    try:
        local_users.disable_user(conn, username, payload.disabled)
    except local_users.LocalUserError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    conn.commit()
    return {"ok": True, "view": build_admin_users_view(settings, conn)}


class AddSshKeyIn(BaseModel):
    key_text: str = Field(min_length=1)
    label: str = ""


@router.post("/admin/users/{username}/keys")
def api_admin_add_ssh_key(
    username: str, payload: AddSshKeyIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Add a key to a LOCAL account -- what the sftp sidecar's
    AuthorizedKeysCommand will serve for them (internal_sftp.py)."""
    _require_admin(request)
    _require_local_mode(request)
    settings = request.app.state.settings
    username = username.strip().lower()
    try:
        key = local_users.add_ssh_key(conn, username, payload.key_text, label=payload.label)
    except local_users.LocalUserError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conn.commit()
    return {"ok": True, "key": key, "view": build_admin_users_view(settings, conn)}


@router.delete("/admin/users/{username}/keys/{fingerprint}")
def api_admin_remove_ssh_key(
    username: str, fingerprint: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    _require_admin(request)
    _require_local_mode(request)
    settings = request.app.state.settings
    username = username.strip().lower()
    removed = local_users.remove_ssh_key(conn, username, fingerprint)
    conn.commit()
    return {"ok": True, "removed": removed, "view": build_admin_users_view(settings, conn)}


# The JSON twin of the Users page's SIGNED-IN BROWSERS panel
# (ui.partial_admin_sessions), so "sign that laptop out" is scriptable and not
# only clickable -- COMMERCIAL_READINESS.md item 6 / H1, 2026-08-17. Deliberately
# NOT a NAS call: revocation must keep working while the NAS is unreachable,
# which is precisely when an admin reaches for it.

@router.get("/admin/sessions")
def api_admin_sessions(request: Request) -> dict[str, Any]:
    _require_admin(request)
    store = auth.session_store(request)
    rows = store.list_all() if store is not None else []
    # The sid is a keyed digest of the cookie and cannot be replayed, but there
    # is no reason to publish it whole either.
    for row in rows:
        row["sid"] = row["sid"][:12]
    return {"sessions": rows}


@router.post("/admin/users/{username}/sessions/revoke")
def api_admin_revoke_sessions(username: str, request: Request) -> dict[str, Any]:
    admin = _require_admin(request)
    username = username.strip().lower()
    if not is_valid_username(username):
        raise HTTPException(status_code=422, detail="not a valid username")
    store = auth.session_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="sessions are not being recorded")
    revoked = store.revoke_user(username, by=f"admin:{admin}")
    log.warning("admin %r revoked %d session(s) for %r", admin, revoked, username)
    return {"ok": True, "revoked": revoked}


# ------------------------------------------------- per-editor report tokens
#
# The admin half of COMMERCIAL_READINESS.md item 15 (2026-08-17). Minting is a
# POST because it CREATES a credential, and the secret comes back in that one
# response and is never retrievable again -- there is nothing stored that could
# answer it a second time (db.create_editor_report_token stores a hash).
#
# How an admin actually hands one over is deliberately NOT automated here: see
# docs/GOTCHAS.md "per-editor report tokens". The pairing flow that exists
# (tray Sign in -> POST /api/v1/verify -> identity.json) is the right seam to
# deliver it through later; today the admin mints and passes the value on the
# same channel they already use for the editor's NAS password.

class CreateReportTokenIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    label: str = Field(default="", max_length=64)


@router.get("/admin/report-tokens")
def api_admin_report_tokens(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    _require_admin(request)
    return build_report_tokens_view(conn)


@router.post("/admin/report-tokens")
def api_admin_create_report_token(
    payload: CreateReportTokenIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    admin = _require_admin(request)
    username = payload.username.strip().lower()
    if not is_valid_username(username):
        raise HTTPException(
            status_code=422,
            detail="username must start with a letter and contain only lowercase letters, "
                   "digits, '.', '_', '-'",
        )
    token, row = db.create_editor_report_token(
        conn, username, created_by=admin, label=payload.label)
    conn.commit()
    log.info("minted a per-editor report token for %s (id %s, by %s)",
             username, row["token_id"], admin)
    # `token` appears here and nowhere else, ever.
    return {"ok": True, "token": token, "token_row": row,
            "view": build_report_tokens_view(conn)}


@router.delete("/admin/report-tokens/{token_id}")
def api_admin_revoke_report_token(
    token_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    admin = _require_admin(request)
    revoked = db.revoke_editor_report_token(conn, token_id, revoked_by=admin)
    conn.commit()
    if not revoked:
        raise HTTPException(status_code=404, detail="no such live token")
    log.info("revoked per-editor report token %s (by %s)", token_id, admin)
    return {"ok": True, "view": build_report_tokens_view(conn)}


def build_report_tokens_view(conn: sqlite3.Connection) -> dict[str, Any]:
    """The Users page's token panel: live tokens plus the migration counter.

    `shared_machines` is what tells an operator whether it is safe to set
    DASH_SHARED_REPORT_TOKEN_ENABLED=0 yet -- the machines whose LAST report
    still authenticated with the one shared fleet token."""
    usage = db.count_shared_token_machines(conn)
    return {
        "tokens": db.fetch_editor_report_tokens(conn),
        "shared_machines": usage["machines"],
        "shared_count": usage["shared"],
        "editor_count": usage["editor"],
    }


# ---------------------------------------------------- fleet halt (item 9)

class FleetHaltIn(BaseModel):
    """Body of POST /fleet/halt. `reason` is shown in EVERY editor's tray, so
    it is the one field an admin must actually fill in when halting."""
    active: bool
    reason: str = Field(default="", max_length=500)


@router.get("/fleet/halt")
def api_fleet_halt(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    """Read the fleet halt. Any signed-in user (or a companion holding the
    report token) may READ it -- an editor whose tray says "your admin
    stopped syncing" must be able to confirm that from the dashboard --
    while setting it is admin-only below."""
    settings = request.app.state.settings
    if not (
        auth.get_session_user(request) is not None
        or token_ok(settings.report_token, request.headers.get("x-ccsync-token", ""))
    ):
        raise HTTPException(status_code=401, detail="log in first")
    return {"halt": db.get_fleet_halt(conn)}


@router.post("/fleet/halt")
def api_set_fleet_halt(
    payload: FleetHaltIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """The fleet-wide stop (COMMERCIAL_READINESS.md item 9, 2026-08-17).

    Persisted in `meta` and handed to every companion on its next report
    reply, which is what makes it survive a dashboard restart AND reach a
    machine that was offline when it was set. Reversible by construction:
    the same route with active=false releases it, and the companion's
    HaltState refuses a LOCAL release of a fleet halt so one editor cannot
    opt out of it.

    Deliberately NOT a per-machine control. The case this exists for is
    "something is destroying files and I do not yet know which machine" --
    one switch, one reason, everybody stops."""
    admin = _require_admin(request)
    state = db.set_fleet_halt(conn, payload.active, payload.reason, admin)
    conn.commit()
    log.warning(
        "FLEET HALT %s by %s: %s",
        "ENGAGED" if state["active"] else "released", admin, state["reason"] or "(no reason)",
    )
    return {"ok": True, "halt": state}


@router.post("/admin/devices/approve")
def api_admin_approve_device(
    payload: ApproveDeviceIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    _require_admin(request)
    settings = request.app.state.settings
    if not settings.syncthing_url:
        raise HTTPException(status_code=503, detail="SYNCTHING_GUI_URL is not configured")
    username = payload.username.strip().lower()
    if not is_valid_username(username):
        raise HTTPException(status_code=422, detail="username must be a valid TrueNAS-style username")
    try:
        device_id = normalize_device_id(payload.device_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    syncthing = SyncthingClient.from_settings(settings)
    try:
        syncthing.approve_device(device_id, username)
    except SyncthingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # An admin naming the device is the dashboard's strongest evidence that
    # this username is a real editor account -- record it, so the enforce
    # cycle is allowed to manage the device's shares (B16).
    db.record_known_editor(conn, username, "admin")
    conn.commit()
    return {"ok": True, "view": build_admin_users_view(settings, conn)}


# ------------------------------------------- companion packages (upgrade channel)

_PACKAGE_PLATFORMS = {"windows", "macos"}
# 'companion' rows feed the fleet's self-upgrade channel (_upgrade_info);
# 'onboard' rows are the full clean-install package served by the UI's
# [ INSTALLER ] download: onboard.exe on Windows, and on macOS the zipped
# onboarding wizard (CCSync Onboarding.app, since installer 1.0.17) -- with
# the Terminal bootstrap script as the historical/hand-publish alternative.
_PACKAGE_KINDS = {"companion", "onboard"}
_PACKAGE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_PACKAGE_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _package_filename(kind: str, platform: str, version: str, head: bytes = b"") -> str:
    """Server-chosen filename -- never taken from the upload, so the packages
    dir can only ever contain these shapes.

    The macos onboard slot is the one place the extension follows the
    payload (`head` = the upload's first bytes): since installer 1.0.17 the
    package is the ZIPPED WIZARD .app (tools/build_onboard_macos.sh), but
    the Terminal bootstrap script remains a legitimate hand-publish, and a
    zip served as .sh -- or a script served as .zip -- breaks a Mac editor's
    very first contact with the system. Zip magic is unambiguous (PK);
    everything else is treated as the script, which matches every pre-1.0.17
    row. Callers without the body yet (the .part staging name) just get the
    .sh shape -- only the final rename/DB row needs the real answer."""
    if kind == "onboard":
        if platform == "windows":
            return f"ccsync-onboard-{version}.exe"
        ext = ".zip" if head[:2] == b"PK" else ".sh"
        return f"ccsync-onboard-{version}{ext}"
    return f"ccsync-companion-{version}" + (".exe" if platform == "windows" else "")


def _package_file(settings, row: sqlite3.Row | dict[str, Any]) -> Path:
    return settings.packages_path() / row["platform"] / row["filename"]


def _unlink_package_file(settings, row: sqlite3.Row | dict[str, Any]) -> None:
    try:
        _package_file(settings, row).unlink(missing_ok=True)
    except OSError:
        pass  # a stray file is harmless; the DB row is the source of truth


# Old enough that no publish still in flight can own it: the request would
# have to have been streaming for six hours (DASH-3, 2026-08-14).
STALE_PART_SECONDS = 6 * 3600


def _sweep_stale_parts(dest_dir: Path, now: float | None = None) -> list[str]:
    """Delete abandoned *.part staging files. Best-effort by construction --
    an orphan wastes disk, a raise here would refuse a publish."""
    import time

    now = time.time() if now is None else now
    swept: list[str] = []
    try:
        parts = list(dest_dir.glob("*.part"))
    except OSError:
        return swept
    for path in parts:
        try:
            if now - path.stat().st_mtime < STALE_PART_SECONDS:
                continue
            path.unlink()
        except OSError:
            continue
        swept.append(path.name)
    if swept:
        log.warning("removed %d abandoned package staging file(s): %s",
                    len(swept), ", ".join(sorted(swept)))
    return swept


def _upgrade_info(
    conn: sqlite3.Connection, platform: str | None, running: str | None
) -> dict[str, Any] | None:
    """The conditional `upgrade` key for report/verify responses.

    Present only when a current package exists for the platform AND the
    companion reported a running version that DIFFERS from it. "Different",
    not "newer": that makes an admin rollback get offered to the fleet like
    any other update, with zero extra machinery. Absent key = up to date
    (old companions that never send their version just never see it).

    An absent or unknown `platform` offers NOTHING (see X-5): coercing it to
    "windows" is how a macOS companion got handed a Windows .exe.
    """
    plat = (platform or "").strip().lower()
    if plat not in _PACKAGE_PLATFORMS:
        return None
    # kind='companion' explicitly: the fleet must never be offered the
    # onboarding installer as a self-upgrade -- upgrade.py would rename it
    # over the running companion exe.
    current = db.get_current_package(conn, plat, kind="companion")
    if current is None or not running or running == current["version"]:
        return None
    # MIGRATION SHAPE (item 4, 2026-08-17): version/url/sha256/size_bytes are
    # exactly what they were, in the same places, because 0.7.11 companions
    # are in the field right now and parse_upgrade reads those four keys and
    # ignores the rest. Everything below is ADDED, never substituted -- the
    # first signed build reaches an unverifying companion through the same
    # response shape it already understands, and verifies every build after
    # that. A row published before this migration serves signature="" and
    # is refused by any companion new enough to look.
    return {
        "version": current["version"],
        "url": f"/api/v1/companion/package/{plat}/{current['version']}",
        "sha256": current["sha256"],
        "size_bytes": current["size_bytes"],
        "kind": "companion",
        "platform": plat,
        "filename": current["filename"],
        "published_at": current["published_at"],
        "min_version": _row_str(current, "min_version"),
        "signed_binary": bool(_row_value(current, "signed_binary") or 0),
        "signature": _row_str(current, "signature"),
        "pubkey_id": _row_str(current, "pubkey_id"),
    }


def _row_value(row: sqlite3.Row | dict[str, Any], key: str) -> Any:
    """A column that may not exist yet.

    The v14 columns are read by code that also runs against a DB opened by a
    concurrently-starting older process during a redeploy, and sqlite3.Row
    raises IndexError -- not KeyError -- for an unknown key."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _row_str(row: sqlite3.Row | dict[str, Any], key: str) -> str:
    value = _row_value(row, key)
    return "" if value is None else str(value)


def build_packages_view(conn: sqlite3.Connection, settings, now: str | None = None) -> dict[str, Any]:
    now = now or db.utcnow_iso()
    packages = []
    current: dict[str, str] = {}
    for row in db.fetch_companion_packages(conn):
        entry = {
            "kind": row["kind"],
            "version": row["version"],
            "platform": row["platform"],
            "filename": row["filename"],
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
            "published_at": row["published_at"],
            "published_by": row["published_by"],
            "is_current": bool(row["is_current"]),
            "file_exists": _package_file(settings, row).is_file(),
            # Item 4: the admin page and check_deploy_drift.ps1 must be able
            # to see, at a glance, whether the build the fleet is offered is
            # one an editor's companion will actually accept. `signed` is
            # false for every row published before v14.
            "signature": _row_str(row, "signature"),
            "pubkey_id": _row_str(row, "pubkey_id"),
            "min_version": _row_str(row, "min_version"),
            "signed_binary": bool(_row_value(row, "signed_binary") or 0),
            "signed": bool(_row_str(row, "signature")),
        }
        # `current` keeps its pre-kind shape (platform -> version) and keeps
        # meaning "the companion the fleet is offered" -- the onboard current
        # is visible per-row via is_current.
        if entry["is_current"] and entry["kind"] == "companion":
            current[entry["platform"]] = entry["version"]
        packages.append(entry)
    editors = build_editors_view(conn, now)
    outdated = [
        {
            "editor_username": e["editor_username"],
            "machine": e["machine"],
            "companion_version": e["companion_version"],
            "received_at": e["received_at"],
        }
        for e in editors["editors"]
        if e["companion_outdated"]
    ]
    return {"generated_at": now, "packages": packages, "current": current,
            "outdated_machines": outdated}


@router.get("/admin/packages")
def api_admin_packages(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    _require_admin(request)
    return build_packages_view(conn, request.app.state.settings)


@router.put("/admin/packages/{platform}/{version}")
async def api_publish_package(
    platform: str,
    version: str,
    request: Request,
    sha256: str = "",
    make_current: int = 0,
    prune: int = 0,
    kind: str = "companion",
    signature: str = "",
    pubkey_id: str = "",
    min_version: str = "",
    published_at: str = "",
    signed_binary: int = 0,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Publish a companion build: raw exe bytes as the request body (no
    multipart -- python-multipart isn't a dependency and doesn't need to be),
    expected sha256 as a query param, verified server-side before anything
    becomes visible. A per-request `.part` staging file + os.replace means the
    served file is always complete, and that two publishes in flight at once
    cannot write into (or delete) each other's staging file.

    `?prune=1` opts IN to deleting all but the current build and the two
    newest non-current ones. It is off by default: publishing must not
    silently destroy older build artifacts (rollback material) as a side
    effect, given the standing no-deletion rule.

    SIGNATURE REQUIRED (COMMERCIAL_READINESS.md item 4, 2026-08-17). The
    upload must carry `signature`/`pubkey_id`/`min_version`/`published_at`/
    `signed_binary` from tools/sign_release.py, and the signature must verify
    against DASH_RELEASE_PUBKEYS over the record the server itself assembles
    -- including the filename the SERVER chose, so a signed artifact cannot be
    re-labelled into another kind or platform on the way in. There is no
    unsigned path and no "warn and continue": publish tooling that predates
    signing fails here, loudly, which is the only place the failure is cheap.
    A companion that downloads an unsigned build is renaming an unverified
    binary over itself.

    Two shapes here are deliberate (see the unbounded-packages-upload
    finding): the body is capped at MAX_PACKAGE_BODY_BYTES both by
    Content-Length (app.py's body_size_gate) and by a running total here --
    the header is advisory for a chunked request -- and every file write goes
    through the threadpool, because this is an `async def` and a 60 MB
    blocking write to a ZFS dataset otherwise stalls the whole event loop
    (every companion report, every htmx poll) for its duration."""
    from .app import MAX_PACKAGE_BODY_BYTES

    user = _require_admin(request)
    settings = request.app.state.settings
    platform = platform.strip().lower()
    kind = kind.strip().lower()
    if platform not in _PACKAGE_PLATFORMS:
        raise HTTPException(status_code=422, detail=f"platform must be one of {sorted(_PACKAGE_PLATFORMS)}")
    if kind not in _PACKAGE_KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {sorted(_PACKAGE_KINDS)}")
    if not _PACKAGE_VERSION_RE.match(version):
        raise HTTPException(status_code=422, detail="version must look like 1.2.3")
    sha = sha256.strip().lower()
    if not _PACKAGE_SHA256_RE.match(sha):
        raise HTTPException(status_code=422, detail="sha256 query param must be 64 hex chars")

    # Refuse BEFORE the body is streamed: a 40 MB upload over Tailscale that
    # is going to be rejected on a query param it never had is a five-minute
    # wait for a one-line answer.
    signature = signature.strip()
    pubkey_id = pubkey_id.strip()
    min_version = min_version.strip()
    published_at = published_at.strip()
    if not settings.release_pubkeys:
        raise HTTPException(
            status_code=503,
            detail="this dashboard has no release public key configured, so it cannot "
                   "verify a build and will not publish one. Set DASH_RELEASE_PUBKEYS "
                   "to the vendor's key (tools/release_key.py pubkey) and redeploy -- "
                   "see docs/RELEASE.md.",
        )
    if not signature:
        raise HTTPException(
            status_code=422,
            detail="unsigned publish REFUSED: no signature. Builds are signed offline "
                   "by tools/sign_release.py and published with its &signature=... "
                   "query suffix. Publish tooling older than 2026-08-17 cannot "
                   "publish to this dashboard -- update it (docs/RELEASE.md).",
        )
    if not release_trust.valid_min_version(min_version):
        raise HTTPException(
            status_code=422,
            detail="min_version must be dotted-numeric (e.g. 0.7.11) -- it is the "
                   "downgrade floor every companion will remember",
        )
    if not published_at:
        raise HTTPException(
            status_code=422,
            detail="published_at is part of the signed record and must be sent with it",
        )
    if db.get_package(conn, platform, version, kind) is not None:
        bump = (
            "bump INSTALLER_VERSION in installer/windows_bootstrap.ps1, "
            "installer/macos_bootstrap.sh and onboarding/steps.py"
            if kind == "onboard"
            else "bump VERSION in companion/src/ccsync_companion/config.py"
        )
        raise HTTPException(
            status_code=409,
            detail=f"{kind} version {version} is already published for {platform} -- "
                   f"{bump} and rebuild",
        )

    dest_dir = settings.packages_path() / platform
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = _package_filename(kind, platform, version)
    # Per-REQUEST staging name. It used to be `filename + ".part"`, derived
    # only from (kind, platform, version) and therefore identical for every
    # attempt at the same version, while the except below unlinks that exact
    # path on ANY exception -- including the ClientDisconnect that
    # request.stream() raises when an upload is abandoned. Ctrl-C a stalled
    # 40 MB publish over Tailscale, re-run it while uvicorn is still draining
    # the first request, and the dying request deletes the live one's staging
    # file (os.replace -> FileNotFoundError -> 500, nothing published, and
    # ship's "already published" gate to work around). Worse when both
    # complete: every threadpool write is an await point, so the two streams
    # interleave into one file while each hashes only its own bytes -- the
    # sha256 gate passes for a file that matches neither, and make_current=1
    # then hands the fleet a build that fails its own verification
    # (DASH-3, 2026-08-14).
    part = dest_dir / f"{filename}.{uuid.uuid4().hex}.part"
    # A unique staging name means an upload the process never got to clean up
    # (SIGKILL, container restart) can no longer be overwritten by the retry,
    # so sweep the abandoned ones. Best-effort and generously old: the point is
    # that ~40 MB orphans must not accumulate on the dataset the SQLite DB
    # lives on, not to be prompt (DASH-3, 2026-08-14).
    _sweep_stale_parts(dest_dir)
    digest = hashlib.sha256()
    size = 0
    too_big = False
    head = b""
    try:
        with part.open("wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_PACKAGE_BODY_BYTES:
                    too_big = True
                    break
                await run_in_threadpool(fh.write, chunk)
                digest.update(chunk)
                if not head:
                    head = bytes(chunk[:4])
    except Exception:
        part.unlink(missing_ok=True)
        raise
    if too_big:
        part.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail=f"package body too large (max {MAX_PACKAGE_BODY_BYTES} bytes)",
        )
    if size == 0 or digest.hexdigest() != sha:
        part.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="sha256 mismatch (or empty body) -- upload corrupted, nothing was published",
        )
    # The staging name above was chosen before any bytes arrived; the real
    # extension (macos onboard: wizard zip vs bootstrap script) needs the
    # payload's head -- see _package_filename.
    filename = _package_filename(kind, platform, version, head=head)

    # Verify the release signature over the record the SERVER assembled --
    # server-chosen filename, server-counted size, server-computed digest --
    # not over anything the uploader asserted, then place the file and write
    # the row. This tail is SHARED with the vendor release feed's unattended
    # publisher (ZERO_TOUCH_PLAN.md WP E, 2026-08-17): package_store is the
    # only writer of a `companion_packages` row, so a PUT here and a feed
    # auto-publish can never disagree about what "published" means. See
    # package_store.store_verified_package's docstring for what it does and
    # why it raises PackageStoreError rather than HTTPException directly.
    try:
        await run_in_threadpool(
            package_store.store_verified_package,
            conn, settings,
            kind=kind, platform=platform, version=version, filename=filename,
            sha256=sha, size_bytes=size, min_version=min_version,
            published_at=published_at, signed_binary=bool(signed_binary),
            signature=signature, pubkey_id=pubkey_id, published_by=user,
            make_current=bool(make_current), prune=bool(prune), part_path=part,
        )
    except package_store.PackageStoreError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return {"ok": True, "view": build_packages_view(conn, settings)}


@router.post("/admin/packages/{platform}/{version}/current")
def api_set_current_package(
    platform: str, version: str, request: Request,
    kind: str = "companion",
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Set (or roll back) which version the fleet is offered (kind=companion)
    or which installer the download serves (kind=onboard)."""
    _require_admin(request)
    platform = platform.strip().lower()
    kind = kind.strip().lower()
    if not db.set_current_package(conn, platform, version, kind):
        raise HTTPException(status_code=404, detail=f"no published {platform} {kind} package {version}")
    conn.commit()
    return {"ok": True, "view": build_packages_view(conn, request.app.state.settings)}


@router.delete("/admin/packages/{platform}/{version}")
def api_delete_package(
    platform: str, version: str, request: Request,
    kind: str = "companion",
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    _require_admin(request)
    settings = request.app.state.settings
    platform = platform.strip().lower()
    kind = kind.strip().lower()
    row = db.get_package(conn, platform, version, kind)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no published {platform} {kind} package {version}")
    if row["is_current"]:
        raise HTTPException(
            status_code=409,
            detail="cannot delete the current version -- make another version current first",
        )
    db.delete_companion_package(conn, platform, version, kind)
    conn.commit()
    _unlink_package_file(settings, row)
    return {"ok": True, "view": build_packages_view(conn, settings)}


def _require_package_read(request: Request,
                          conn: sqlite3.Connection | None = None) -> None:
    """Same dual auth as _require_selection_read, minus the editor scoping:
    any signed-in user, or any companion holding EITHER fleet credential (the
    shared report token or its own per-editor one), may download a published
    package -- it is the same exe everyone runs."""
    settings = request.app.state.settings
    if companion_token_ok(settings, conn, request.headers.get("x-ccsync-token", "")):
        return
    if auth.get_session_user(request) is not None:
        return
    raise HTTPException(status_code=401, detail="log in, or present X-CCSync-Token")


@router.get("/companion/package/{platform}/{version}")
def api_download_package(
    platform: str, version: str, request: Request,
    kind: str = "companion",
    conn: sqlite3.Connection = Depends(get_conn),
) -> FileResponse:
    """Download a published package by exact version, or the magic version
    "current" to get whatever is current for that (kind, platform).

    "current" is handled INSIDE this route on purpose -- a second route like
    /companion/package/{platform}/current would depend on decorator ordering
    to not be shadowed by this one. A fresh macOS bootstrap has no version to
    ask for, so it fetches .../package/macos/current?kind=onboard and verifies
    the bytes against the X-CCSync-SHA256 header below.
    """
    _require_package_read(request, conn)
    settings = request.app.state.settings
    plat, kind = platform.strip().lower(), kind.strip().lower()
    if version.strip().lower() == "current":
        row = db.get_current_package(conn, plat, kind=kind)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"no current {platform} {kind} package is published",
            )
    else:
        row = db.get_package(conn, plat, version, kind)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no published {platform} {kind} package {version}")
    path = _package_file(settings, row)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="package file missing on server")
    # X-CCSync-Signature is for the ONE client that cannot verify ed25519:
    # installer/macos_bootstrap.sh, a POSIX shell script doing a first
    # install. It cannot check the signature, but it CAN refuse a channel
    # that has none -- which is the difference between "trusting the
    # dashboard" and "trusting anything that answered". Every other consumer
    # (upgrade.py) verifies the signed record from the report response and
    # never reads these headers (item 4, 2026-08-17).
    headers = {"X-CCSync-SHA256": row["sha256"], "X-CCSync-Version": row["version"]}
    signature = _row_str(row, "signature")
    if signature:
        headers["X-CCSync-Signature"] = signature
        headers["X-CCSync-Pubkey-Id"] = _row_str(row, "pubkey_id")
        headers["X-CCSync-Min-Version"] = _row_str(row, "min_version")
        headers["X-CCSync-Signed-Binary"] = "1" if _row_value(row, "signed_binary") else "0"
    return FileResponse(
        str(path),
        media_type="application/octet-stream",
        filename=row["filename"],
        headers=headers,
    )


# ------------------------------------------------------------------ report

# Field ceilings for the report body (see the unbounded-report finding). Every
# string that reaches a DB column is capped, every list is capped, and the two
# free-form dicts have a key-count cap -- so the whole payload has a bounded
# worst case even before the request-size middleware in app.py.
#
# THESE CEILINGS TRUNCATE, THEY DO NOT REJECT (KNOWN_BUGS B6). They used to be
# pydantic `max_length`/raising validators, which fire BEFORE the route body
# runs -- so a machine with a 65th project 422'd its entire HEAVY report and
# lost lane status, transfers, machine_state, presence AND the upgrade
# advertisement with it. An idle companion only ever sends heavy ticks, so it
# vanished from the fleet grid completely, with one WARNING and then DEBUG
# forever. Worst placed of all is the base rig, whose local_root is the whole
# NAS tree: it hits the cap first and holds the authoritative copy of
# everything. Media presence for the 65th project is a real loss; the whole
# machine going dark is a much bigger one.
#
# Truncation keeps the FIRST N entries in the order the companion sent them:
# the companion prioritises (selected projects first, then most recently
# touched -- see companion manifest.scan_local_manifest), so its order is the
# best available signal about what matters. Every truncation is logged here
# and echoed in the reply under "truncated" so it can never be silent.
MAX_REPORT_PROJECTS = 64          # keys in local_manifest / media_tree / queue
MAX_MANIFEST_FILES = 4000         # per project, per kind (db caps rows again)
MAX_MEDIA_CLIPS = 4000            # per Resolve project


def _truncate_report_sections(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Slice the oversized sections of a raw report body down to the ceilings
    above, returning (new_body, {section: entries_dropped}).

    Runs as a `mode="before"` validator, i.e. on the RAW dict, so pydantic
    only ever builds models for the entries that survive -- truncating after
    validation would have meant parsing the whole oversized payload first,
    which is the cost this is here to bound.
    """
    dropped: dict[str, int] = {}
    out = dict(data)

    for key in ("local_manifest", "media_tree"):
        value = out.get(key)
        if isinstance(value, dict) and len(value) > MAX_REPORT_PROJECTS:
            dropped[key] = len(value) - MAX_REPORT_PROJECTS
            out[key] = dict(list(value.items())[:MAX_REPORT_PROJECTS])

    queue = out.get("queue")
    if isinstance(queue, list) and len(queue) > MAX_REPORT_PROJECTS:
        dropped["queue"] = len(queue) - MAX_REPORT_PROJECTS
        out["queue"] = queue[:MAX_REPORT_PROJECTS]

    manifest = out.get("local_manifest")
    if isinstance(manifest, dict):
        files_dropped = 0
        trimmed: dict[str, Any] = {}
        for rel, project in manifest.items():
            if isinstance(project, dict):
                for kind in ("originals", "proxies"):
                    entries = project.get(kind)
                    if isinstance(entries, list) and len(entries) > MAX_MANIFEST_FILES:
                        files_dropped += len(entries) - MAX_MANIFEST_FILES
                        project = {**project, kind: entries[:MAX_MANIFEST_FILES],
                                   "truncated": True}
            trimmed[rel] = project
        if files_dropped:
            dropped["manifest_files"] = files_dropped
            out["local_manifest"] = trimmed

    tree = out.get("media_tree")
    if isinstance(tree, dict):
        clips_dropped = 0
        trimmed_tree: dict[str, Any] = {}
        for name, clips in tree.items():
            if isinstance(clips, list) and len(clips) > MAX_MEDIA_CLIPS:
                clips_dropped += len(clips) - MAX_MEDIA_CLIPS
                clips = clips[:MAX_MEDIA_CLIPS]
            trimmed_tree[name] = clips
        if clips_dropped:
            dropped["media_clips"] = clips_dropped
            out["media_tree"] = trimmed_tree

    return out, dropped


class CompletedIn(BaseModel):
    """One finished per-file transfer, from rclone's Copied/Moved records
    (the dashboard's HISTORY section)."""
    name: str = Field(max_length=512)
    direction: str = Field(default="", max_length=16)
    lane: str = Field(default="", max_length=64)
    at: str = Field(default="", max_length=64)


class TransferIn(BaseModel):
    name: str = Field(max_length=512)
    direction: str = Field(default="", max_length=16)
    bytes_done: int | None = None
    bytes_total: int | None = None
    percentage: float | None = None
    speed_bps: float | None = None
    eta_seconds: float | None = None
    project_slug: str | None = Field(default=None, max_length=128)


class LaneReportIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    state: Literal["idle", "syncing", "error", "paused"]
    queued: int | None = None
    transferring: int | None = None
    last_error: str | None = Field(default=None, max_length=2000)
    last_sync: str | None = Field(default=None, max_length=64)
    detail: str | None = Field(default=None, max_length=500)
    # Progress fields (companions >= 0.2); optional for rollout compatibility.
    current_project: str | None = Field(default=None, max_length=512)
    bytes_done: int | None = None
    bytes_total: int | None = None
    speed_bps: float | None = None
    eta_seconds: float | None = None
    # Generous but bounded (see SEC-4): current companions send a handful of
    # live transfers per lane, never anywhere near this many.
    transfers: list[TransferIn] = Field(default_factory=list, max_length=256)


class ManifestProjectIn(BaseModel):
    n_originals: int = Field(default=0, ge=0, le=10_000_000)
    bytes_originals: int = Field(default=0, ge=0, le=2**60)
    n_proxies: int = Field(default=0, ge=0, le=10_000_000)
    bytes_proxies: int = Field(default=0, ge=0, le=2**60)
    truncated: bool = False
    # No max_length: _truncate_report_sections has already sliced these to
    # MAX_MANIFEST_FILES on the raw body (a raising cap here 422'd the whole
    # report -- see B6).
    originals: list[tuple[str, int | None]] | None = None
    proxies: list[tuple[str, int | None]] | None = None


class MediaClipIn(BaseModel):
    bin_path: str = Field(default="", max_length=512)
    clip_name: str = Field(max_length=512)
    file_path: str | None = Field(default=None, max_length=1024)
    kind: str | None = Field(default=None, max_length=32)
    present: bool = False


class SyncthingTransportIn(BaseModel):
    """companion sync/syncthing_lane.summarize_connections() -- CONNECTED
    devices only, so "offline" and "relayed" stay different problems."""
    devices: dict[str, str] | None = None
    relayed: list[str] | None = Field(default=None, max_length=256)
    direct: list[str] | None = Field(default=None, max_length=256)


class OrphanReportIn(BaseModel):
    """companion sync/rclone_lane.orphan_report() -- the `.partial` files lane
    A leaves on the NAS when it is killed mid-transfer, and the local
    .ccsync-trash. Reported only; nothing ever deletes them."""
    count: int | None = Field(default=None, ge=0)
    bytes: int | None = Field(default=None, ge=0)


class LaneOrphansIn(BaseModel):
    partials: OrphanReportIn | None = None
    trash: OrphanReportIn | None = None


class ExpressReportIn(BaseModel):
    """companion sync/rclone_lane.express_report(). An express failure is
    deliberately a warning + counter rather than STATE_ERROR, so without
    these the server has no way to see one at all."""
    enabled: bool | None = None
    runs: int | None = Field(default=None, ge=0)
    files_uploaded: int | None = Field(default=None, ge=0)
    dropped_over_cap: int | None = Field(default=None, ge=0)
    last_error: str | None = Field(default=None, max_length=2000)
    last_run: str | None = Field(default=None, max_length=64)
    last_files: int | None = Field(default=None, ge=0)


class TransportHealthIn(BaseModel):
    """The companion's `transport_health` payload (B17).

    Every field is optional and every sub-model tolerates extra keys, because
    this is a diagnostic channel: a companion that grows a new counter must
    never 422 its whole report against an older dashboard.
    """
    syncthing: SyncthingTransportIn | None = None
    orphans: dict[str, LaneOrphansIn] | None = None
    express: ExpressReportIn | None = None


def flatten_transport_health(
    health: "TransportHealthIn | None", now: str
) -> dict[str, Any] | None:
    """TransportHealthIn -> the flat columns machine_state stores (B17).

    Returns None when the companion sent nothing (a LIGHT tick), which
    upsert_machine_state treats as "leave the stored values alone" rather
    than "clear them". The orphan counters are summed across lanes: which
    rclone lane left a `.partial` on the NAS is a companion-log question, the
    grid only needs "this machine is leaving junk behind"."""
    if health is None:
        return None
    flat: dict[str, Any] = {"at": now}
    if health.syncthing is not None:
        flat["relayed"] = len(health.syncthing.relayed or [])
        flat["direct"] = len(health.syncthing.direct or [])
    if health.orphans:
        partials = 0
        partial_bytes = 0
        for lane in health.orphans.values():
            if lane.partials is not None:
                partials += lane.partials.count or 0
                partial_bytes += lane.partials.bytes or 0
        flat["orphan_partials"] = partials
        flat["orphan_partial_bytes"] = partial_bytes
    if health.express is not None:
        flat["express_dropped"] = health.express.dropped_over_cap
        flat["express_last_error"] = health.express.last_error
    return flat


class BreakerIn(BaseModel):
    """companion sync/lane_guard.LaneBBreaker.report() -- lane B's circuit
    breaker (COMMERCIAL_READINESS.md item 9, 2026-08-17). `tripped` means
    that machine has STOPPED downloading proxies and needs a human."""
    tripped: bool = False
    reason: str | None = Field(default=None, max_length=1000)
    tripped_at: str | None = Field(default=None, max_length=64)
    deletes: int | None = Field(default=None, ge=0)
    bytes: int | None = Field(default=None, ge=0)
    last_pass_deletes: int | None = Field(default=None, ge=0)
    resumed_at: str | None = Field(default=None, max_length=64)


class TrashIn(BaseModel):
    """`.ccsync-trash` -- what lane B removed and can still be recovered."""
    count: int | None = Field(default=None, ge=0)
    bytes: int | None = Field(default=None, ge=0)
    removed: int | None = Field(default=None, ge=0)
    removed_bytes: int | None = Field(default=None, ge=0)


class HaltIn(BaseModel):
    """companion sync/lane_guard.HaltState.report() -- "stop all sync"."""
    active: bool = False
    scope: str | None = Field(default=None, max_length=16)   # 'local' | 'fleet'
    reason: str | None = Field(default=None, max_length=500)
    at: str | None = Field(default=None, max_length=64)


class SkippedExistsIn(BaseModel):
    """Lane A files the NAS already holds AT A DIFFERENT SIZE --
    `copy --ignore-existing` will never replace them (item 9)."""
    count: int | None = Field(default=None, ge=0)
    samples: list[str] | None = Field(default=None, max_length=64)
    checked_at: str | None = Field(default=None, max_length=64)


class RemovalOverrideIn(BaseModel):
    """An editor who deleted a project's local copy anyway, past the
    caught-up gate. Reported so the deletion is not only in one machine's
    log file."""
    slug: str | None = Field(default=None, max_length=128)
    rel: str | None = Field(default=None, max_length=512)
    at: str | None = Field(default=None, max_length=64)
    pending_uploads: int | None = Field(default=None, ge=0)
    reasons: list[str] | None = Field(default=None, max_length=8)


class SyncGuardIn(BaseModel):
    """The companion's `sync_guard` section (item 9, 2026-08-17).

    Every field optional, sub-models tolerant of extras, exactly like
    TransportHealthIn: a companion that grows a counter must never 422 its
    whole report against an older dashboard. And the converse matters more
    here -- an OLDER companion sends none of this, which reads as "no alarm",
    which is right: it has no breaker to trip.
    """
    lane_b_breaker: BreakerIn | None = None
    trash: TrashIn | None = None
    halt: HaltIn | None = None
    skipped_exists: SkippedExistsIn | None = None
    removal_overrides: list[RemovalOverrideIn] | None = Field(default=None, max_length=8)


def flatten_sync_guard(guard: "SyncGuardIn | None", now: str) -> dict[str, Any] | None:
    """SyncGuardIn -> the flat machine_state columns (schema v16).

    None when the companion sent nothing -- upsert_machine_state then leaves
    every stored value alone, so a pre-item-9 companion reporting into an
    upgraded dashboard cannot clear another machine's alarm. `at` doubles as
    the "this report carried a guard section" marker the upsert keys its
    latch writes on."""
    if guard is None:
        return None
    breaker = guard.lane_b_breaker
    halt = guard.halt
    return {
        "at": now,
        "breaker_tripped": int(bool(breaker.tripped)) if breaker is not None else 0,
        "breaker_reason": breaker.reason if breaker is not None else None,
        "breaker_at": breaker.tripped_at if breaker is not None else None,
        "trash_bytes": guard.trash.bytes if guard.trash is not None else None,
        "trash_count": guard.trash.count if guard.trash is not None else None,
        "halt_active": int(bool(halt.active)) if halt is not None else 0,
        "halt_scope": (halt.scope if halt is not None and halt.active else None),
        "halt_reason": (halt.reason if halt is not None and halt.active else None),
        "skipped_exists": (
            guard.skipped_exists.count if guard.skipped_exists is not None else None
        ),
    }


# --------------------------------------------------- tolerant report sections
#
# The companion's diagnostic sections (proxy_coverage, youtube_import,
# broll_ingest) are CACHED ZERO-I/O GETTERS on the tray side: they grow fields
# whenever a feature does, they are never the point of a report, and they must
# never be the reason one does not land. So every one of them is bounded here
# the way B6 bounded the presence sections -- oversize values are cut down to
# the ceiling instead of raising -- and, one level up, a section that cannot be
# parsed at all is DROPPED rather than allowed to 422 the report (see
# ReportIn._a_bad_section_never_422s).
#
# The alternative is what shipped for a year: `ReportIn` did not declare
# proxy_coverage or youtube_import at all, so pydantic's extra='ignore' threw
# both away on every tick, and the dashboard could not say how much of an
# editor's footage still had no proxy -- the number that decides whether
# anyone else on the fleet can see that footage at all.


class _ReportSectionIn(BaseModel):
    """Base for those sections: extras ignored, everything else BOUNDED.

    `max_length` on a plain Field RAISES, and a raising validator fires
    before the route body -- one 300-character VRAM refusal would have taken
    the whole machine off the fleet grid (B6's lesson). Here the caps are
    applied to the raw dict instead: strings truncated, sequences sliced,
    numbers clamped to their ge/le.
    """

    # protected_namespaces: `model_download_percent` is a field name from the
    # companion's payload, not a pydantic attribute; without this, importing
    # this module warns about every `model_*` field.
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    @model_validator(mode="before")
    @classmethod
    def _bound_rather_than_reject(cls, data):
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for name, field in cls.model_fields.items():
            if name not in out:
                continue
            value = out[name]
            for meta in field.metadata:
                cap = getattr(meta, "max_length", None)
                if cap is not None:
                    if isinstance(value, (str, list)):
                        value = value[:cap]
                    elif isinstance(value, dict) and len(value) > cap:
                        value = dict(list(value.items())[:cap])
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    low, high = getattr(meta, "ge", None), getattr(meta, "le", None)
                    if low is not None and value < low:
                        value = low
                    if high is not None and value > high:
                        value = high
            out[name] = value
        return out


class ProxyCoverageProjectIn(_ReportSectionIn):
    """One project's row of proxy_gen.coverage()["projects"]."""
    missing: int | None = None
    braw: int | None = None
    needs_resolve: int | None = None
    own: int | None = None
    preview: int | None = None


class ProxyCoverageIn(_ReportSectionIn):
    """companion proxy_gen.ProxyGenerator.coverage().

    Only the scalars the grid can act on are persisted (see
    flatten_proxy_coverage); the rest are declared so that parsing the
    section does not depend on the companion and the dashboard agreeing on
    its exact shape.
    """
    state: str = Field(default="", max_length=32)
    enabled: bool | None = None
    # gap()'s flag rather than coverage()'s: the two getters share a
    # vocabulary, and a reporter that later sends the tray's block should be
    # parsed, not refused.
    encoding: bool | None = None
    missing: int | None = None
    braw: int | None = None
    needs_resolve: int | None = None
    own: int | None = None
    preview: int | None = None
    left: int | None = None
    generated: int | None = None
    failed: int | None = None
    ffmpeg: bool | None = None
    nvenc: bool | None = None
    scanned_at: str | None = Field(default=None, max_length=64)
    low_space: str | None = Field(default=None, max_length=500)
    truncated: bool | None = None
    # Sliced, never refused: the companion caps this at MAX_COVERAGE_PROJECTS
    # and sheds it entirely when the payload gets big.
    projects: dict[str, ProxyCoverageProjectIn] | None = Field(default=None, max_length=128)
    history: dict[str, Any] | None = None


class YoutubeImportIn(_ReportSectionIn):
    """companion youtube_import.YoutubeImporter.status() -- whether the clips
    the dashboard downloaded have actually reached the editor's Resolve."""
    state: str = Field(default="", max_length=32)
    pending: int | None = None
    imported_session: int | None = None
    failed_session: int | None = None
    last_import_at: str | None = Field(default=None, max_length=64)
    last_bin: str | None = Field(default=None, max_length=512)
    last_error: str | None = Field(default=None, max_length=2000)


class BrollIngestIn(_ReportSectionIn):
    """The companion's `broll_ingest` section (BROLL_INGEST_PLAN.md §1 step 8,
    2026-08-18) -- one local b-roll indexing batch, as the tray sees it.

    Scalars only, every one optional: an older companion sends nothing (which
    reads as "not indexing", correctly), and a newer one that grows a counter
    must never 422 its whole report against this dashboard.

    `warning` is the insufficient-VRAM refusal ("Best needs 12 GB VRAM, this
    GPU has 8 GB -- choose Good"). It is deliberately shown on the grid even
    when nothing is running: the batch the editor asked for is NOT happening,
    and the only other place that says so is their own tray.
    """
    active: bool = False
    batch_uid: str = Field(default="", max_length=32)
    state: str = Field(default="", max_length=32)
    gate: str = Field(default="", max_length=32)
    done: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    clip: str = Field(default="", max_length=255)
    percent: int = Field(default=0, ge=0, le=100)
    tier: str = Field(default="", max_length=16)
    run_mode: str = Field(default="", max_length=16)
    uploading: bool = False
    upload_paused: bool = False
    model_download_percent: int | None = Field(default=None, ge=0, le=100)
    warning: str = Field(default="", max_length=255)
    at: str = Field(default="", max_length=64)


class MusicIngestIn(BrollIngestIn):
    """The companion's `music_ingest` section (MUSIC_INGEST_PLAN.md step 3,
    2026-08-18) -- one local music indexing batch, as the tray sees it.

    b-roll's fields exactly, plus `kind`, and a SEPARATE section rather than a
    reuse of the b-roll one because the two run AT THE SAME TIME: music needs
    no GPU, so a machine can be embedding an album while it indexes a camera
    card, and one section could only ever describe one of them.

    `tier` is inherited and is always "" here -- music has one model and
    nothing to choose -- so the grid's chip has nothing to say about it.
    """
    kind: str = Field(default="music", max_length=16)


def flatten_broll_ingest(ingest: "BrollIngestIn | None", now: str) -> dict[str, Any] | None:
    """BrollIngestIn -> the flat machine_state columns (schema v20).

    None when the companion sent no section at all, which upsert_machine_state
    reads as "leave every stored ingest value alone EXCEPT ingest_active,
    which goes to 0" -- the reporter omits an empty section, so silence is how
    a finished batch is spelled.

    `at` is the RECEIPT time, not the companion's clock: the grid renders it
    as an age, and a machine with a skewed clock would otherwise show a batch
    that started in the future (same rule as flatten_sync_guard)."""
    if ingest is None:
        return None
    return {
        "at": now,
        "active": int(bool(ingest.active)),
        "batch": ingest.batch_uid or None,
        "state": ingest.state or None,
        "gate": ingest.gate or None,
        "done": ingest.done,
        "total": ingest.total,
        "failed": ingest.failed,
        "clip": ingest.clip or None,
        "percent": ingest.percent,
        "tier": ingest.tier or None,
        "warning": ingest.warning or None,
    }


def flatten_music_ingest(ingest: "MusicIngestIn | None", now: str) -> dict[str, Any] | None:
    """MusicIngestIn -> the flat machine_state columns (schema v21).

    flatten_broll_ingest's dict, into its own set of columns. None when the
    companion sent no section at all, which upsert_machine_state reads as
    "leave every stored music value alone EXCEPT music_ingest_active, which
    goes to 0" -- the reporter omits an empty section, so silence is how a
    finished batch is spelled.

    `tier` is not carried: music has one model, so the column would be empty
    on every row that ever existed.
    """
    if ingest is None:
        return None
    return {
        "at": now,
        "active": int(bool(ingest.active)),
        "batch": ingest.batch_uid or None,
        "state": ingest.state or None,
        "gate": ingest.gate or None,
        "done": ingest.done,
        "total": ingest.total,
        "failed": ingest.failed,
        "track": ingest.clip or None,
        "percent": ingest.percent,
        "warning": ingest.warning or None,
    }


def flatten_proxy_coverage(
    coverage: "ProxyCoverageIn | None", now: str
) -> dict[str, Any] | None:
    """ProxyCoverageIn -> the columns the grid reads (schema v20).

    The per-project map, the history block and the capability flags stay out
    of the database: they are a diagnostic the tray already renders, while
    "this machine owes the fleet N proxies" is a fleet-level number. `now` is
    accepted for symmetry with the other flatteners; coverage carries its own
    `scanned_at` and needs no receipt stamp of its own."""
    if coverage is None:
        return None
    return {
        "missing": coverage.missing,
        "state": coverage.state or None,
        "left": coverage.left,
        # No column of its own (v20 stays as narrow as the plan drew it):
        # `state` already spells an encode in flight. Carried in the dict so
        # a caller that wants it does not have to re-parse the section.
        "encoding": bool(coverage.encoding) if coverage.encoding is not None else None,
    }


# Which model parses each of the tolerant sections. Explicit rather than
# derived from the annotations: this table is what
# ReportIn._a_bad_section_never_422s consults, and it must not silently grow.
_TOLERANT_SECTIONS: dict[str, type[BaseModel]] = {
    "proxy_coverage": ProxyCoverageIn,
    "youtube_import": YoutubeImportIn,
    "broll_ingest": BrollIngestIn,
    "music_ingest": MusicIngestIn,
}


# At most this many batch uids ride one report reply. A companion runs one
# batch at a time, so anything past a handful is a stuck queue, not an
# instruction -- and the reply is on the hot path of every tick of every
# machine in the fleet.
MAX_INGEST_CANCELS = 16


def broll_cancel_requested(settings: Any, editor: str, machine: str) -> list[str]:
    """Batch uids an admin/owner has asked this machine to stop indexing.

    BEST-EFFORT IN EVERY DIRECTION (BROLL_INGEST_PLAN.md §4.2). The report
    reply is the fleet's status channel; it must not acquire a dependency on
    the b-roll checkout being present, importable, migrated or even readable.
    Every failure here answers "nothing to cancel" and the companion learns
    about the cancel from its next heartbeat's 410 instead -- which is the
    authoritative path anyway. This one only makes it prompt.

    The sub-app is reached exactly as broll.py reaches it (imported as the
    top-level `app` package the container puts on PYTHONPATH), and its
    database is opened read-only for the length of the query: the mounted
    app holds that file open read-write in WAL mode, and this runs inside a
    request that already has the dashboard's own connection.
    """
    if not getattr(settings, "broll_enabled", False):
        return []
    try:
        from app.config import get_db_path  # type: ignore[import-not-found]
        from app.ingest_batches import cancel_requested_for  # type: ignore[import-not-found]
    except ImportError:
        # No b-roll checkout, or one predating the ingest work. Not an error:
        # the feature is optional and the dashboard is not.
        return []
    except Exception as e:  # noqa: BLE001
        log.debug("b-roll cancel lookup skipped (%s: %s)", type(e).__name__, e)
        return []
    conn = None
    try:
        path = Path(str(get_db_path()))
        if not path.is_file():
            return []
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        uids = cancel_requested_for(conn, editor, machine) or []
        return [str(u) for u in uids][:MAX_INGEST_CANCELS]
    except Exception as e:  # noqa: BLE001 - see the docstring
        log.warning("b-roll cancel lookup failed for %s/%s (%s: %s); the report was "
                    "answered without it", editor, machine, type(e).__name__, e)
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def music_cancel_requested(settings: Any, editor: str, machine: str) -> list[str]:
    """Batch uids an admin/owner has asked this machine to stop indexing.

    `broll_cancel_requested`'s twin, and BEST-EFFORT IN EVERY DIRECTION for
    the same reason: the report reply is the fleet's status channel and must
    not acquire a dependency on the music checkout being present, importable,
    migrated or even readable. Every failure here answers "nothing to cancel"
    and the companion learns about the cancel from its next heartbeat's 410
    instead -- which is the authoritative path anyway.

    The sub-app is reached exactly as music.py reaches it (`musicweb`, on the
    PYTHONPATH the container sets), and its database is opened READ-ONLY: the
    mounted app holds that file open read-write in WAL mode.

    There is NO settings flag to check first, unlike b-roll's: the music mount
    has never had one (`mount_music` is attempted on every boot and reports
    MOUNTED/ABSENT/DEGRADED), so the import below is the only honest test of
    whether this deployment has music at all. `settings` is accepted anyway,
    so the two functions are called identically and a future flag has
    somewhere to go.
    """
    try:
        from musicweb.config import DB_PATH  # type: ignore[import-not-found]
        from musicweb.ingest_batches import (  # type: ignore[import-not-found]
            cancel_requested_for,
        )
    except ImportError:
        # No music checkout, or one predating the ingest work. Not an error:
        # the feature is optional and the dashboard is not.
        return []
    except Exception as e:  # noqa: BLE001
        log.debug("music cancel lookup skipped (%s: %s)", type(e).__name__, e)
        return []
    conn = None
    try:
        path = Path(str(DB_PATH))
        if not path.is_file():
            return []
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        uids = cancel_requested_for(conn, editor, machine) or []
        return [str(u) for u in uids][:MAX_INGEST_CANCELS]
    except Exception as e:  # noqa: BLE001 - see the docstring
        log.warning("music cancel lookup failed for %s/%s (%s: %s); the report was "
                    "answered without it", editor, machine, type(e).__name__, e)
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


class ReportIn(BaseModel):
    editor_name: str = Field(min_length=1, max_length=64)
    machine: str = Field(min_length=1, max_length=128)
    companion_version: str | None = Field(default=None, max_length=64)
    platform: str | None = Field(default=None, max_length=32)  # 'windows' | 'macos'
    reported_at: str = Field(max_length=64)
    # Generous but bounded (see SEC-4): current companions send exactly the
    # three lanes in LANE_LABELS.
    lanes: list[LaneReportIn] = Field(max_length=32)
    # Completed-file feed for the HISTORY section (companions >= 0.4.11).
    completed: list[CompletedIn] | None = Field(default=None, max_length=256)
    # Truncated, not rejected: an editor ticking a 65th project must not take
    # their whole machine off the fleet grid (B6).
    queue: list[str] | None = None
    current_project: str | None = Field(default=None, max_length=512)
    resolve_project: str | None = Field(default=None, max_length=512)
    # Media-presence (companions >= 0.3); all optional -> absent leaves tables
    # untouched, so a LIGHT report never wipes manifest/tree data.
    mode: str | None = Field(default=None, max_length=32)   # 'base' | 'editor'
    local_manifest: dict[str, ManifestProjectIn] | None = None   # keyed by project rel
    media_tree: dict[str, list[MediaClipIn]] | None = None       # keyed by RESOLVE PROJECT NAME
    # Connection-path + orphan diagnostics the companion has been computing
    # and sending every heavy tick since 0.4.x, which this model used to drop
    # on the floor (pydantic extra='ignore') -- so a RELAYED editor and a
    # merely slow one stayed indistinguishable on the fleet grid, and the
    # orphaned-.partial / express-failure counters that exist ONLY to give
    # the server visibility reached nobody (KNOWN_BUGS B17).
    transport_health: TransportHealthIn | None = None
    # The safety latches (COMMERCIAL_READINESS.md item 9, 2026-08-17): a
    # tripped lane B breaker, a halted machine, the trash size and lane A's
    # "skipped, exists" counter. The first two are ALARMS -- a machine in
    # either state looks perfectly healthy on every other field in this
    # model.
    sync_guard: SyncGuardIn | None = None
    # The three sections this model used to DROP UNDECLARED. proxy_coverage
    # and youtube_import have ridden every heavy tick since their features
    # shipped and reached nobody; broll_ingest is new (BROLL_INGEST_PLAN.md
    # §3.2) and is what lets an admin see which computers are indexing
    # b-roll and how far along they are.
    proxy_coverage: ProxyCoverageIn | None = None
    youtube_import: YoutubeImportIn | None = None
    broll_ingest: BrollIngestIn | None = None
    # The music half of the same feature (MUSIC_INGEST_PLAN.md step 3). Its
    # own field for the reason MusicIngestIn gives: both can be true at once.
    music_ingest: MusicIngestIn | None = None
    # Set by _truncate_report_sections, never by the client: {section:
    # entries dropped}. Echoed in the reply and logged, so a truncated report
    # is loud rather than silent (B6).
    truncated: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _truncate_rather_than_reject(cls, data):
        """Slice oversized sections down to the ceilings instead of 422-ing.

        See MAX_REPORT_PROJECTS: a raising cap fires before the route body,
        so ONE project over the line cost the machine its lane status,
        transfers, presence and upgrade advertisement too -- it disappeared
        from the fleet grid entirely (B6)."""
        if not isinstance(data, dict):
            return data
        out, dropped = _truncate_report_sections(data)
        out["truncated"] = dropped        # client-supplied value is discarded
        return out

    @field_validator("machine")
    @classmethod
    def _clean_machine(cls, v: str) -> str:
        # `machine` is half of the primary key in four tables: " PC" and "PC"
        # must never become two machines.
        v = v.strip()
        if not v:
            raise ValueError("machine must not be blank")
        return v

    @field_validator("lanes")
    @classmethod
    def _drop_unknown_lanes(cls, lanes: list[LaneReportIn]) -> list[LaneReportIn]:
        """Unknown lane names are FILTERED OUT, not rejected.

        Rejecting the model made one unknown lane 422 the whole report, so a
        companion shipping a future 4th lane would go completely dark against
        an un-upgraded dashboard. Dropping the unknown entries keeps the three
        real lanes flowing while still never creating a permanent
        lane_report_current row for a bogus name (SEC-4)."""
        return [lane for lane in lanes if lane.name in LANE_LABELS]

    @field_validator("proxy_coverage", "youtube_import", "broll_ingest",
                     "music_ingest", mode="before")
    @classmethod
    def _a_bad_section_never_422s(cls, value, info):
        """A diagnostic section that will not parse is DROPPED, not fatal.

        The bounding in _ReportSectionIn covers oversize values; this covers
        the rest -- a wrong type, a null where a number was expected, a
        companion mid-refactor. None of that is worth taking a machine off
        the fleet grid for, which is precisely what a 422 here does: the
        route body never runs, so the lanes, transfers, presence and upgrade
        advertisement in the same report are lost too (B6).
        """
        if value is None or isinstance(value, BaseModel):
            return value
        model = _TOLERANT_SECTIONS[info.field_name]
        try:
            return model.model_validate(value)
        except Exception as e:  # noqa: BLE001 - deliberately catch-all, see above
            log.warning("report section %s dropped (%s: %s); the rest of the report "
                        "was accepted", info.field_name, type(e).__name__, e)
            return None

    # NOTE: the project-key / clip-count / manifest-file ceilings are applied
    # by _truncate_rather_than_reject above, on the raw body. They were
    # raising validators here until B6 -- see MAX_REPORT_PROJECTS for why a
    # raise was the wrong shape.


@router.post("/report")
def api_report(
    payload: ReportIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    settings = request.app.state.settings
    token = request.headers.get("x-ccsync-token", "")
    auth_kind, token_editor = resolve_companion_credential(settings, conn, token)
    if auth_kind == AUTH_NONE:
        if not settings.report_token and not db.looks_like_editor_report_token(token):
            # No shared token configured and none presented: the deployment
            # never set DASH_REPORT_TOKEN and has not minted per-editor tokens
            # either. Same message this route has always given.
            if not settings.report_token_optional:
                raise HTTPException(
                    status_code=401,
                    detail="report token not configured on server (set DASH_REPORT_TOKEN)",
                )
        else:
            raise HTTPException(status_code=401, detail="bad or missing X-CCSync-Token")
    received_at = db.utcnow_iso()
    editor = payload.editor_name.strip().lower()
    machine = payload.machine.strip()

    # A per-editor token IS an identity claim, so it is checked against the one
    # the body makes before anything is written. The shared token makes no such
    # claim -- that is exactly its weakness, and why the identity header below
    # exists (COMMERCIAL_READINESS.md item 15, 2026-08-17).
    if auth_kind == AUTH_EDITOR and token_editor != editor:
        log.warning("report refused: a per-editor token belonging to %r reported as %r",
                    token_editor, editor)
        raise HTTPException(
            status_code=401,
            detail="this X-CCSync-Token belongs to a different editor than editor_name",
        )

    # Machine-identity verification: a valid X-CCSync-Identity token whose
    # username matches the reported editor_name proves this companion actually
    # authenticated as that editor (not just a config-set editor_name). The
    # header is REQUIRED whenever the server can verify one (i.e. whenever
    # DASH_SESSION_SECRET is configured): the report token is a SHARED secret
    # handed to every editor by /api/v1/verify, so without this any token
    # holder could write reports -- and overwrite presence rows,
    # machine_state and live transfers -- as any other editor (see SEC-5).
    #
    # BEHAVIOUR CHANGE: pre-upgrade companions that don't send the header are
    # rejected with 401. Sign in on the companion tray to mint one.
    identity = request.headers.get("x-ccsync-identity", "")
    id_user = auth.read_identity_token(settings.session_secret, identity) if identity else None
    if settings.session_secret:
        if not identity:
            raise HTTPException(
                status_code=401,
                detail="X-CCSync-Identity required -- sign in from the companion tray "
                       "(Sign in…) to get a machine identity token",
            )
        if id_user is None:
            raise HTTPException(
                status_code=401,
                detail="X-CCSync-Identity is invalid or expired -- sign in again from the "
                       "companion tray",
            )
        if id_user != editor:
            raise HTTPException(
                status_code=401,
                detail="X-CCSync-Identity does not match editor_name",
            )
    elif identity and id_user is not None and id_user != editor:
        raise HTTPException(
            status_code=401,
            detail="X-CCSync-Identity does not match editor_name",
        )
    verified = id_user is not None and id_user == editor
    if verified:
        # A signed identity token is the dashboard's OWN evidence that this
        # is a real editor account -- the one thing that distinguishes an
        # editor from a username-shaped machine name later, when the enforce
        # cycle decides whether a device may be unshared (B16).
        db.record_known_editor(conn, editor, "report", received_at)

    # Which credential this machine used, so an operator can see how far the
    # fleet has moved off the shared token before switching it off (see
    # settings.shared_report_token_enabled and app.py's boot log).
    if auth_kind != AUTH_NONE:
        db.record_report_auth(conn, editor, machine, auth_kind, received_at)
    if auth_kind == AUTH_EDITOR:
        db.touch_editor_report_token(conn, token, received_at)

    # B6: a truncated section is never silent. The report was ACCEPTED (the
    # alternative -- 422 -- took the whole machine off the fleet grid), but
    # somebody has to be able to see that presence data was dropped.
    if payload.truncated:
        log.warning(
            "report from %s/%s was truncated to fit the ceilings: %s -- the report was "
            "accepted, but these entries are not in the dashboard's picture",
            editor, machine,
            ", ".join(f"{k}: {v} dropped" for k, v in sorted(payload.truncated.items())),
        )

    for lane in payload.lanes:
        db.upsert_lane_report(
            conn,
            editor_username=editor,
            machine=machine,
            lane=lane.name,
            state=lane.state,
            queued=lane.queued,
            transferring=lane.transferring,
            last_error=lane.last_error,
            last_sync=lane.last_sync,
            detail=lane.detail,
            companion_version=payload.companion_version,
            reported_at=payload.reported_at,
            received_at=received_at,
            current_project=lane.current_project,
            bytes_done=lane.bytes_done,
            bytes_total=lane.bytes_total,
            speed_bps=lane.speed_bps,
            eta_seconds=lane.eta_seconds,
        )
    # Sticky fix-destination mapping: the FIRST HIGH-CONFIDENCE auto-match of
    # a Resolve project name to a tree project is stored and never changes
    # automatically -- admins edit it on the dashboard thereafter.
    #
    # "High confidence" (db.match_project_label_confident) means >=2 shared
    # non-trivial tokens, or the name IS the project's final path segment.
    # One shared word is a coincidence: "Nuclear Family Reunion" mapped
    # itself permanently into "2025/FF4/Nuclear" on the token "nuclear"
    # (verified 2026-07-25). Anything weaker is left unmapped so the report
    # reply prompts a human to pick the folder.
    #
    # Scratch/utility Resolve projects are dropped HERE, server-side, as
    # well as in the companion's watcher (config ignored_resolve_projects):
    # this is the belt-and-braces that also covers old companion versions
    # and any companion code path that reports the bridge's project name
    # unfiltered. Without it, one report of "New Doc" (the Blackmagic Proxy
    # Generator's helper project) gets echoed back as
    # resolve_project_unmapped and pops a bogus NEW PROJECT dialog.
    detected_slug = None
    resolve_project = (payload.resolve_project or "").strip()
    if is_ignored_resolve_project(resolve_project):
        resolve_project = ""
    if resolve_project:
        existing = conn.execute(
            "SELECT project_slug FROM project_roots WHERE resolve_project = ?",
            (resolve_project,),
        ).fetchone()
        if existing is not None:
            detected_slug = existing["project_slug"]
        else:
            labels = {
                r["label"]: r["slug"]
                for r in conn.execute("SELECT slug, label FROM projects WHERE active=1")
            }
            match = db.match_project_label_confident(resolve_project, labels.keys())
            if match is not None:
                detected_slug = labels[match]
                db.sticky_project_root(conn, resolve_project, detected_slug, received_at)
    db.upsert_machine_state(
        conn, editor, machine, detected_slug, received_at,
        resolve_project=resolve_project or None, verified=verified,
        platform=(payload.platform or "").strip().lower() or None,
        companion_version=(payload.companion_version or "").strip() or None,
        transport=flatten_transport_health(payload.transport_health, received_at),
        guard=flatten_sync_guard(payload.sync_guard, received_at),
        ingest=flatten_broll_ingest(payload.broll_ingest, received_at),
        music=flatten_music_ingest(payload.music_ingest, received_at),
        proxy=flatten_proxy_coverage(payload.proxy_coverage, received_at),
    )
    # An overridden "Remove from this machine" destroyed a local copy the
    # gate said was not caught up. There is nowhere on the grid for a
    # one-off event, so it goes in the dashboard's log -- which is the only
    # record that outlives the machine it happened on (item 9).
    for override in (payload.sync_guard.removal_overrides or []) if payload.sync_guard else []:
        log.warning(
            "%s/%s DELETED the local copy of %s past the caught-up gate (%s pending "
            "upload(s)): %s",
            editor, machine, override.rel or override.slug,
            override.pending_uploads, "; ".join(override.reasons or []),
        )

    # -- media presence (all optional; absent field ⇒ table untouched) --
    mode = (payload.mode or "editor").strip().lower()

    # Live transfers: replace the whole set for this (editor, machine) so an
    # empty/absent list clears finished transfers.
    transfer_rows = []
    for lane in payload.lanes:
        for t in lane.transfers:
            transfer_rows.append({
                "lane": lane.name, "name": t.name, "direction": t.direction,
                "bytes_done": t.bytes_done, "bytes_total": t.bytes_total,
                "percentage": t.percentage, "speed_bps": t.speed_bps,
                "eta_seconds": t.eta_seconds, "project_slug": t.project_slug,
            })
    db.replace_active_transfers(conn, editor, machine, transfer_rows, received_at)
    if payload.completed:
        db.add_transfer_history(
            conn, editor, machine,
            [{"lane": c.lane, "name": c.name, "direction": c.direction, "at": c.at}
             for c in payload.completed],
            received_at,
        )

    if payload.local_manifest is not None:
        for rel, m in payload.local_manifest.items():
            slug = _slug_for_rel(conn, rel)
            db.upsert_editor_media_project(
                conn, editor=editor, machine=machine, slug=slug, mode=mode,
                n_originals=m.n_originals, bytes_originals=m.bytes_originals,
                n_proxies=m.n_proxies, bytes_proxies=m.bytes_proxies,
                truncated=m.truncated, now=received_at,
            )
            if m.originals is not None or m.proxies is not None:
                files = [(rel_p, "original", size) for rel_p, size in (m.originals or [])]
                files += [(rel_p, "proxy", size) for rel_p, size in (m.proxies or [])]
                db.replace_editor_media(conn, editor, machine, slug, files, received_at)

    if payload.media_tree is not None:
        # media_tree is keyed by the RESOLVE PROJECT NAME; map it to a slug via
        # the sticky project_roots table (same source as the fix-dest mapping).
        for resolve_name, clips in payload.media_tree.items():
            if is_ignored_resolve_project(resolve_name):
                continue
            slug = _slug_for_resolve_name(conn, resolve_name)
            if slug is None:
                continue
            rows = [(c.bin_path, c.clip_name, c.file_path, c.kind, c.present) for c in clips]
            db.replace_media_tree(conn, editor, machine, slug, rows, received_at)

    conn.commit()
    result: dict[str, Any] = {
        "ok": True, "lanes": len(payload.lanes), "received_at": received_at}
    # B6: tell the companion what was dropped so the truncation is visible on
    # BOTH sides -- the companion logs this and can shed the section itself
    # next tick rather than resending something the server will trim again.
    if payload.truncated:
        result["truncated"] = payload.truncated
    # Upgrade channel: piggyback on the report reply so an out-of-date
    # companion learns about the current build with no extra request. Key
    # absent = up to date (or nothing published, or version unreported).
    upgrade = _upgrade_info(conn, payload.platform, payload.companion_version)
    if upgrade is not None:
        result["upgrade"] = upgrade
    # New-project onboarding: the auto-match above already ran, so this is
    # authoritative -- the reported Resolve project has no root mapping and
    # nothing matched. Echo the NAME (not a bool) so the companion's prompt
    # can't race a project switch. Key absent = mapped (or no project open).
    if resolve_project and detected_slug is None:
        result["resolve_project_unmapped"] = resolve_project
    # FLEET HALT (COMMERCIAL_READINESS.md item 9, 2026-08-17). The reply is
    # the dashboard's only channel back to a companion -- it already carries
    # the upgrade advertisement and the unmapped-project prompt -- so an
    # admin's "stop everything" reaches every tray within one report
    # interval with no new request and no push infrastructure.
    #
    # ALWAYS present, both states. The companion treats an ABSENT key as
    # "this dashboard is too old to have an opinion" and holds whatever halt
    # it has; sending `active: false` is what releases one, so the key must
    # not be omitted when the flag is clear.
    halt_state = db.get_fleet_halt(conn)
    result["commands"] = {"halt": {
        "active": bool(halt_state["active"]),
        "reason": halt_state["reason"],
        "at": halt_state["set_at"],
    }}
    # B-roll ingest cancels (BROLL_INGEST_PLAN.md §4.2). Present ONLY when
    # there is something to cancel -- unlike `halt`, an empty list is not an
    # instruction and this rides every tick of every machine. The companion's
    # heartbeat 410 remains the authoritative stop; this just makes it
    # arrive within one report interval instead of one heartbeat.
    cancels = broll_cancel_requested(settings, editor, machine)
    if cancels:
        result["commands"]["broll_ingest"] = {"cancel": cancels}
    # ...and the same for music, on the same terms and with the same
    # best-effort rules (MUSIC_INGEST_PLAN.md step 3). Present only when there
    # is something to cancel: an empty list is not an instruction and this
    # rides every tick of every machine.
    music_cancels = music_cancel_requested(settings, editor, machine)
    if music_cancels:
        result["commands"]["music_ingest"] = {"cancel": music_cancels}
    return result


def _slug_for_rel(conn: sqlite3.Connection, rel: str) -> str:
    """rel -> project slug. The project's LABEL (kept in lockstep with its
    current rel by the collector's provision/retarget cycle) is the
    authoritative lookup key, because a moved/adopted project's real slug --
    the marker's immutable slug -- need not equal slugify(its current rel)
    (see X-3). Only falls back to slugify() when no project is registered at
    that label at all (e.g. a report about a brand-new/unregistered dir).

    `label` has no uniqueness constraint, so the lookup is constrained to
    ACTIVE projects, ordered deterministically, and prefers a row whose
    stored path actually ends in this rel -- otherwise two projects sharing a
    label (or a deactivated one) yielded an arbitrary slug."""
    rows = conn.execute(
        "SELECT slug, path FROM projects WHERE label = ? AND active = 1 ORDER BY id",
        (rel,),
    ).fetchall()
    if rows:
        want = rel.strip("/")
        for row in rows:
            path = str(row["path"] or "").replace("\\", "/").rstrip("/")
            if path == want or path.endswith("/" + want):
                return row["slug"]
        return rows[0]["slug"]
    from . import provision
    try:
        return provision.slugify(rel)
    except Exception:
        return rel.strip().lower()


def _slug_for_resolve_name(conn: sqlite3.Connection, resolve_name: str) -> str | None:
    """Resolve project NAME -> tree slug, via the sticky project_roots
    mapping ONLY.

    There is deliberately no best-effort label match here. This lookup routes
    a media_tree report, and replace_media_tree WIPES AND REPLACES that
    project's whole bin tree for the reporting machine: a loose token match
    ("Nuclear Family Reunion" -> "2025/FF4/Nuclear" on the word "nuclear")
    therefore blew away an unrelated project's presence data. No explicit
    mapping = no write; the report reply already asks the editor to set one."""
    name = (resolve_name or "").strip()
    if not name:
        return None
    row = conn.execute(
        "SELECT project_slug FROM project_roots WHERE resolve_project = ?", (name,)
    ).fetchone()
    return row["project_slug"] if row is not None else None
