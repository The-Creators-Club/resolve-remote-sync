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
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import VERSION, auth, db, health, links, local_users, package_store, release_trust
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

def _lanes_view(
    rows: list[dict[str, Any]], now: str, rotation_seconds: float | None = None
) -> list[dict[str, Any]]:
    """`rotation_seconds` is that machine's project_rotation_seconds (SYS-1):
    the stall budget is 3 rotations, and without it health.lane_stall falls
    back to a 30 min floor. Absent here on the project page, where the lanes
    are shown per project and the fleet grid is where a stall is chased."""
    chips = [health.lane_chip(r, now, rotation_seconds) for r in rows]
    return [
        {
            "lane": r["lane"],
            "label": LANE_LABELS.get(r["lane"], r["lane"]),
            "machine": r["machine"],
            "state": r["state"],
            "chip": chip[0],
            # Why the chip is not green, in words, when the reason is not on
            # the row itself: a red dot with no sentence is what CR-91b's two
            # silent hours looked like on this page (SYS-1).
            "chip_reason": chip[1],
            "progress_token": r.get("progress_token"),
            "progress_token_since": r.get("progress_token_since"),
            "state_since": r.get("state_since"),
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
        for r, chip in zip(rows, chips)
    ]


def _editor_view(
    e: dict[str, Any],
    lanes_by_editor: dict[str, list[dict[str, Any]]],
    reachable: bool,
    now: str,
) -> dict[str, Any]:
    username = e["editor_username"]
    lane_rows = lanes_by_editor.get(username, []) if username else []
    # UX-2 (resilience sweep 2026-08-28): when this editor's companion last
    # reported ANYTHING. None for a Syncthing device with no companion row at
    # all -- that is the `unmapped` case, not a stale one.
    last_report_at = max(
        (r["received_at"] for r in lane_rows if r["received_at"]), default=None)
    status = health.editor_status(
        completion=e["completion"],
        need_items=e["need_items"],
        connected=bool(e["connected"]),
        last_connected_at=e["last_connected_at"],
        completion_updated_at=e["updated_at"],
        syncthing_reachable=reachable,
        lanes=lane_rows,
        now=now,
        last_report_at=last_report_at,
    )
    _freshness, stale_reason = health.report_freshness(last_report_at, now)
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
        "last_report_at": last_report_at,
        # Why the dot is not green, when the reason is silence rather than a
        # number on the row. Rendered as the dot's tooltip.
        "status_reason": stale_reason,
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
    links_by_borrower = db.fetch_links_for_borrowers(conn)
    projects = []
    for p in db.fetch_projects(conn):
        editors = [_editor_view(e, lanes_by_editor, reachable, now) for e in p["editors"]]
        my_links = links_by_borrower.get(p["slug"], [])
        projects.append({
            "slug": p["slug"],
            "label": p["label"],
            # Cross-project folder links (SHARED_FOLDERS_PLAN.md §4.3): the
            # sidebar chips. ok counts what syncs; bad counts what an admin
            # needs to look at (invalid / missing / lender-inactive).
            "links_ok": sum(1 for l in my_links if l["status"] == "ok"),
            "links_bad": sum(1 for l in my_links if l["status"] != "ok"),
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
        # Cross-project folder links, both directions (SHARED_FOLDERS_PLAN.md
        # §4.3): what this project borrows (all statuses, so a broken link is
        # visible where it was declared) and who borrows from it (ok only).
        "links": db.fetch_links_for_borrowers(conn, [slug]).get(slug, []),
        "borrowers": db.fetch_borrowers_of(conn, slug),
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
    # ...and a THIRD scoping rule since CR-28 (2026-08-18): a machine that
    # does not sync cannot have a backlog. fetch_sync_backlog has excluded
    # base-mode machines since it was written (`WHERE emp.mode != 'base'`);
    # the two sources below never did, so the base rig sat in [ QUEUED ]
    # under a [ GETTING READY ] chip that could never clear -- it works
    # directly off the NAS tree, so it never gets a completion row, so
    # "ticked and nothing known yet" stayed true for as long as the tick did.
    # ...and PER MACHINE since 2026-08-21 (dash-admin-8): base_only_editors
    # is true only when EVERY one of a person's machines is wired, so an
    # account with a wired desktop and a remote laptop showed the desktop's
    # rows again -- the same permanent chip, one machine over. The person-level
    # set stays for the rows whose machine cannot be resolved.
    base_editors = db.base_only_editors(conn)
    base_pairs = db.base_machines(conn)
    queues = db.fetch_sync_backlog(conn, editor=editor)
    # WHOSE COMPUTER is this Syncthing device? (WP2/WP4.) The share is made
    # with a device, and only the machine registry can say which of an
    # editor's computers that device is -- without it, one person's laptop
    # showed the desktop's backlog and vice versa.
    # FULL ticks only (docs/UPLOAD_ONLY_TICK.md): an upload-only tick has no
    # Syncthing share, so a lane C backlog against it is impossible, and a
    # "getting ready" row for it would wait on a completion row that never
    # comes. Its own preparing row is built further down from the manifest.
    machine_plans = db.fetch_machine_selections(conn, sync_modes=(db.SYNC_MODE_FULL,))
    upload_only_plans = db.fetch_machine_selections(
        conn, sync_modes=(db.SYNC_MODE_UPLOAD_ONLY,))
    # WHOSE device it is comes from the REGISTRY first and the device's label
    # second (data-model-4, 2026-08-21). Two authorities bound a device to an
    # editor: `devices.editor_username`, resolved from the label an admin
    # typed at approve time, and `machines.syncthing_device_id`, reported by
    # an authenticated companion. A device approved straight in the Syncthing
    # GUI carries a HOSTNAME as its label, which resolves to no editor, so
    # this join dropped that machine's whole lane C backlog even though the
    # registry knew exactly whose computer it was.
    lane_c_q = """SELECT c.project_id, c.device_id AS device_row, c.need_items,
                         c.need_bytes, p.slug, p.label,
                         COALESCE(m.editor_username, d.editor_username) AS editor_username,
                         m.machine
                  FROM completion_current c
                  JOIN projects p ON p.id = c.project_id
                  JOIN devices d ON d.id = c.device_id
                  LEFT JOIN machines m ON m.syncthing_device_id = d.device_id
                  WHERE d.is_server = 0 AND c.need_items > 0"""
    for r in conn.execute(lane_c_q):
        who = r["editor_username"] or ""
        if editor is not None and who != editor:
            continue
        if who in base_editors:
            continue
        machine = r["machine"] or ""
        if machine and (who, machine) in base_pairs:
            continue
        planned = machine_plans.get(r["slug"], [])
        if machine:
            if (who, machine) not in planned:
                continue
        elif not any(e == who for e, _m in planned):
            # A device we cannot resolve to a computer (it has never reported
            # a machine_id, or its Syncthing identity changed): fall back to
            # the person-level question, which is what this query asked
            # before the registry existed.
            continue
        missing = db.fetch_missing(conn, r["project_id"], r["device_row"])
        queues.append({
            "editor": who, "machine": machine,
            "slug": r["slug"], "label": r["label"],
            "lane": "c", "direction": "down", "kind": "everything else",
            "n_files": r["need_items"], "bytes": r["need_bytes"],
            "files": missing["files"][:50],
            "truncated": r["need_items"] > min(len(missing["files"]), 50),
            "manifest_truncated": False,
        })

    # Subtract in-flight files: rclone transfer names are project-relative
    # like the manifest rel_paths, with a basename fallback for safety.
    # Both sides go through db.media_rel_key first: a Mac's rclone names a
    # file the way its filesystem spells it (NFD) and the manifest rows are
    # stored NFC, so an accented clip mid-download counted as transferring
    # AND as queued (the CR-90 shape, one layer up).
    active_by_editor: dict[str, set[str]] = {}
    for t in rows:
        if t.get("granularity") != "file":
            continue
        names = active_by_editor.setdefault(str(t["editor"] or ""), set())
        name = db.media_rel_key(str(t["name"] or ""))
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
            name = db.media_rel_key(str(f.get("name") or ""))
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
    # One row per (COMPUTER, project) since WP2: the plan belongs to a
    # machine, so "getting ready" does too -- a person with a desktop and a
    # laptop is preparing on one of them, not in the abstract.
    labels = {
        r["slug"]: r["label"] for r in conn.execute(
            "SELECT slug, label FROM projects WHERE active = 1")
    }
    pending_rows = [
        {"editor": e, "machine": m, "slug": slug, "label": labels[slug]}
        for slug, pairs in machine_plans.items() if slug in labels
        for e, m in pairs
        if editor is None or e == editor
    ]
    queued_pairs = {(q["editor"], q["slug"]) for q in queues}
    for r in pending_rows:
        if (r["editor"], r["slug"]) in queued_pairs:
            continue
        if (r["editor"] or "") in base_editors:
            # "Getting ready" is a promise that syncing starts in a minute or
            # two. For a base rig it never does (CR-28).
            continue
        if (r["editor"] or "", r["machine"] or "") in base_pairs:
            continue        # ...and the same for ONE wired machine of a mixed account
        # Completion for THIS computer where the device is resolvable, and
        # for any of the person's devices where it is not (a device that has
        # never reported a machine_id is all we had before WP1).
        has_completion = conn.execute(
            """SELECT 1 FROM completion_current c
               JOIN devices d ON d.id = c.device_id
               JOIN projects p ON p.id = c.project_id
               LEFT JOIN machines m ON m.syncthing_device_id = d.device_id
               WHERE p.slug = ? AND COALESCE(m.editor_username, d.editor_username) = ?
                 AND (m.machine IS NULL OR m.machine = ?)""",
            (r["slug"], r["editor"], r["machine"]),
        ).fetchone()
        if has_completion:
            continue  # known state: fully synced or already queued above
        queues.append({
            "editor": r["editor"], "machine": r["machine"], "slug": r["slug"],
            "label": r["label"], "lane": "c", "direction": "down",
            "kind": "preparing", "n_files": 0, "bytes": 0, "files": [],
            "truncated": False, "manifest_truncated": False, "pending": True,
        })
    # An UPLOAD-ONLY tick prepares too, but what ends its preparing is the
    # machine's first media manifest for the project (an editor_media_project
    # row) -- from then on the lane A backlog above says exactly what is left
    # to send, and "nothing left" is a finished upload, not a missing share.
    for slug, pairs in upload_only_plans.items():
        if slug not in labels:
            continue
        for e, m in pairs:
            if editor is not None and e != editor:
                continue
            if (e, slug) in queued_pairs:
                continue
            if (e or "") in base_editors or (e or "", m or "") in base_pairs:
                continue
            reported = conn.execute(
                """SELECT 1 FROM editor_media_project
                    WHERE editor_username=? AND project_slug=?
                      AND (? = '' OR machine=?)""",
                (e, slug, m or "", m or ""),
            ).fetchone()
            if reported:
                continue
            queues.append({
                "editor": e, "machine": m, "slug": slug,
                "label": labels[slug], "lane": "a", "direction": "up",
                "kind": "preparing", "n_files": 0, "bytes": 0, "files": [],
                "truncated": False, "manifest_truncated": False, "pending": True,
                "upload_only": True,
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

    # Which published builds the vendor has recalled (REL-3, 2026-08-28), read
    # once for the whole grid: (platform, version) -> reason.
    retracted_versions = db.retracted_packages(conn, kind="companion")
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
    # Which machines have an admin's "resume proxy download" still in flight
    # (v26, CR-45), so the button can say "asked" rather than inviting a
    # second click at a machine that has simply not reported yet.
    pending_resumes = {
        (r["editor_username"], r["machine"])
        for r in conn.execute(
            "SELECT editor_username, machine FROM machines "
            "WHERE lane_b_resume_requested_at IS NOT NULL"
        ).fetchall()
    }
    # SYS-7 (resilience sweep 2026-08-28): everything the WHY sentence needs
    # that is not already on the row. All four are ONE query for the whole
    # fleet, because this builder runs every 15 s for every open fleet page.
    # DASH-2 (resilience sweep 2026-08-28): computers that ARE reporting and
    # are being turned away, which used to look exactly like computers that
    # had been switched off.
    refusals = db.report_refusal_map(conn)
    pending_asks = db.pending_diagnostics_requests(conn)
    diag_stamps = db.diagnostics_stamp_map(conn)
    machine_role = db.machine_modes(conn)
    plans = db.plan_summary_map(conn, machines.keys())
    # A halted fleet is why THIS machine is not syncing, and it is the one
    # alarm _scope_editors_view deliberately does not redact.
    fleet_halted = bool(db.get_fleet_halt(conn)["active"])
    result = []
    for entry in machines.values():
        key = (entry["editor_username"], entry["machine"])
        # UX-2 (resilience sweep 2026-08-28): freshness is its own input, not
        # a property of the lanes. A machine whose editor signed out, quit, or
        # set it to WIRED TO THE SERVER stops reporting with its last lane
        # states frozen mid-green, and `worst()` over those chips is green for
        # ever. A machine with no lane rows at all (state row only) has no
        # chips to be worst of, which is the same hole from the other side.
        freshness, stale_reason = health.report_freshness(entry.get("received_at"), now)
        entry["status"] = health.worst(
            [l["chip"] for l in entry["lanes"]] + [freshness])
        entry["status_reason"] = stale_reason
        entry["verified"] = verified.get(key, False)
        entry["transport"] = transport.get(key) or {}
        entry["guard"] = dict(guards.get(key) or {})
        entry["guard"]["resume_requested"] = key in pending_resumes
        # SYS-1 (resilience sweep 2026-08-28): re-chip the lanes now that this
        # machine's OWN rotation budget is in hand (it arrives with the guard
        # section, which is read after the lane rows), and fold the stall into
        # the row's dot exactly as wave 1 folded report freshness. A lane in
        # `syncing` used to be amber for ever -- 2 h 20 m of it on leso's
        # MacBook with nothing moving and lane B never getting a turn.
        rotation = entry["guard"].get("rotation_seconds")
        for lane in entry["lanes"]:
            lane["chip"], lane["chip_reason"] = health.lane_chip(lane, now, rotation)
        entry["status"] = health.worst(
            [l["chip"] for l in entry["lanes"]] + [freshness])
        if not entry["status_reason"]:
            entry["status_reason"] = next(
                (l["chip_reason"] for l in entry["lanes"] if l.get("chip_reason")), None)
        # SYS-5: the DISK chip's colour, worked out here rather than in the
        # template so the two thresholds are one testable rule. A machine that
        # has never reported a disk section gets no chip at all -- not a green
        # one, which would be "could not check" rendered as "fine".
        disk_colour, disk_percent = health.disk_status(
            entry["guard"].get("disk_root_free_bytes"),
            entry["guard"].get("disk_root_total_bytes"))
        entry["guard"]["disk_status"] = disk_colour
        entry["guard"]["disk_percent"] = disk_percent
        if disk_percent is not None and disk_colour != health.GREEN:
            entry["status"] = health.worst([entry["status"], disk_colour])
        # SYS-4 / APP-13: the chip's own words, worked out here rather than in
        # the template so the threshold is one testable number. Under a minute
        # is NTP jitter and a laptop coming out of sleep; a minute is already
        # twice the `--min-age 60s` lane B passes, and a slow clock makes that
        # pass exclude every file on the NAS and exit 0 having done nothing.
        skew = entry["guard"].get("clock_skew_seconds")
        if skew is not None and abs(skew) >= db.CLOCK_SKEW_WARN_SECONDS:
            entry["guard"]["clock_skew_abs"] = abs(skew)
            entry["guard"]["clock_skew_dir"] = "AHEAD" if skew > 0 else "SLOW"
        # SYS-7: ONE SENTENCE for "why is this machine not syncing", composed
        # from states every one of which was already computed somewhere and
        # never composed. It is the first line of the machine's row, so the
        # answer is on the page the owner opens rather than in a message to
        # the editor whose machine is the broken one.
        entry["guard"]["diagnostics_requested"] = key in pending_asks
        refusal = refusals.get(key)
        if refusal:
            entry["guard"]["report_refused_at"] = refusal.get("at")
            entry["guard"]["report_refused_reason"] = refusal.get("reason")
        entry["diagnostics"] = diag_stamps.get(key) or {}
        entry["mode"] = machine_role.get(key) or "editor"
        entry["plan"] = plans.get(key) or {}
        entry["fleet_halt_active"] = fleet_halted
        why = health.why_not_syncing(entry, now)
        if why is None:
            entry["why"] = None
        else:
            entry["why"] = {
                "reason": why[0],
                "sentence": why[1],
                # An upload-only machine is doing exactly what it was ticked
                # for (CR-85): the sentence is an EXPLANATION, and colouring
                # it red is what would send an admin chasing it.
                "informational": why[0] in health.WHY_INFORMATIONAL,
            }
        # v38 (wave 4's ingest contract): clips the open project references
        # from outside the tree are appended to the sentence rather than being
        # a reason of their own. They are INFORMATIONAL: that machine may be
        # syncing perfectly, and the footage still is not going anywhere.
        # Composed here and not in health.why_not_syncing so that function
        # stays the answer to one question ("why is nothing moving").
        out_of_tree = entry["guard"].get("resolve_out_of_tree")
        if out_of_tree:
            note = (f"{out_of_tree} clip(s) in the open project are outside "
                    f"the tree and will never upload")
            if entry["why"] is None:
                entry["why"] = {"reason": "out_of_tree", "sentence": note.capitalize(),
                                "informational": True}
            else:
                entry["why"]["sentence"] = f"{entry['why']['sentence']}. Also: {note}"
            entry["why"]["out_of_tree"] = out_of_tree
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
        # REL-3 (resilience sweep 2026-08-28): this machine is RUNNING a build
        # the vendor has recalled. Un-currenting a recalled build stops it
        # reaching anyone new and says nothing at all about the machines that
        # already took it, which are the ones a recall is about.
        entry["companion_retracted_reason"] = retracted_versions.get(
            (platform, entry["companion_version"] or ""))
        result.append(entry)
    result.sort(key=lambda e: (e["editor_username"], e["machine"]))
    # Fleet-level rollups for the banner (item 9). Computed here rather than
    # in the template so the numbers are testable and both the page and the
    # /partials/fleet poll get the same ones.
    tripped = [e for e in result if (e.get("guard") or {}).get("breaker_tripped")]
    halted = [e for e in result if (e.get("guard") or {}).get("halt_active")]
    refused_rows = [
        {"editor": e["editor_username"], "machine": e["machine"],
         "reason": (e.get("guard") or {}).get("report_refused_reason") or ""}
        for e in result if (e.get("guard") or {}).get("report_refused_at")
    ]
    # DASH-16: a computer must never leave this page just because a status
    # table aged out. The `machines` registry row survives every prune, and it
    # still carries the sync plan that is still being enforced for a machine
    # nobody is watching -- so a machine past LOST_MACHINE_DAYS with no live
    # row of its own gets a LOST row of its own instead of vanishing.
    live = {(e["editor_username"], e["machine"]) for e in result}
    lost = [
        m for m in db.lost_machines(conn, now)
        if (m["editor_username"], m["machine"]) not in live
    ]
    return {"generated_at": now, "editors": result,
            "lost_machines": lost,
            # SYS-3: report sections this dashboard accepted and does not read.
            "ignored_report_sections": db.ignored_report_sections(conn),
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
            "fleet_halt": db.get_fleet_halt(conn),
            # DASH-2 / REL-11 (resilience sweep 2026-08-28). Three states that
            # are silent everywhere else: computers being refused, the
            # rotation drain that explains them, and a vendor feed nobody has
            # been able to reach. Built here rather than in the template so
            # both the page and its 15 s poll get the same numbers, and so
            # each is one testable rule.
            "report_refused": refused_rows,
            "identity_key_drain": _identity_drain_block(conn),
            "feed_alarm": _feed_alarm_block(conn, now),
            # THE COLLECTOR'S OWN BRAKES + per-kind notes (DASH-3 / DASH-4 /
            # DASH-14, resilience sweep 2026-08-28). Here rather than in a
            # second builder because both the fleet page and its every-15s
            # /partials/fleet poll render the same partial from this one dict,
            # and a frozen share set is a fleet alarm in exactly the sense
            # item 9's banners are: nothing else on any page can show it.
            # Redacted for non-admins in _scope_editors_view (device ids).
            "collector": db.collector_health(conn)}


def _identity_drain_block(conn: sqlite3.Connection) -> dict[str, Any]:
    """How many computers were last accepted on a RETIRED session key
    (DASH-2). Zero is the state an operator is waiting for: it is what says
    the rotation has drained and DASH_SESSION_SECRET_PREVIOUS can go."""
    try:
        entries = db.retired_key_identities(conn)
    except Exception:  # noqa: BLE001
        log.exception("could not read the retired-key identity ledger")
        return {"count": 0, "machines": []}
    return {"count": len(entries),
            "machines": sorted(entries.keys())[:20]}


def _feed_alarm_block(conn: sqlite3.Connection, now: str) -> dict[str, Any]:
    """REL-11: "this site has not been able to check for updates since <date>"
    and "every build on offer needs a new container image", as data.

    Read from the database rather than the in-memory feed cache: this builder
    runs for every fleet page and has a connection, and the durable half is
    exactly the half that survives the restart that cleared the cache."""
    from . import dashboard_update

    try:
        state = db.get_feed_state(conn)
        mismatch = db.get_feed_runtime_mismatch(conn)
    except Exception:  # noqa: BLE001
        log.exception("could not read the release feed state")
        return {}
    checked = str(state.get("last_checked_at") or "")
    age = None
    if checked:
        try:
            age = max(0.0, db.age_seconds(checked, now) / 86400.0)
        except (ValueError, TypeError):
            age = None
    return {
        "last_checked_at": checked,
        "age_days": None if age is None else round(age, 1),
        "last_error": str(state.get("last_error") or ""),
        # A feed that HAS been read and has gone quiet. Never-checked is left
        # off this banner deliberately (unlike /api/v1/health's `stale`, which
        # is a machine-readable field and says so): this builder cannot see
        # whether a feed is configured at all, and a site that was never
        # pointed at a channel must not be told its updates are broken.
        "stale": bool(checked) and age is not None
        and age > dashboard_update.FEED_STALE_DAYS,
        "runtime_mismatch": mismatch or None,
    }


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
    # The collector health block names Syncthing DEVICE IDS (the pending
    # enforce diff) and is an admin diagnostic, so it goes entirely
    # (DASH-3, resilience sweep 2026-08-28). Not merely trimmed: there is no
    # per-editor half of it that an editor needs.
    view.pop("collector", None)
    # The LOST rows (DASH-16) name editors, machines and the plan each one
    # still holds, so they follow the same rule as the live rows beside them.
    view["lost_machines"] = [
        m for m in view.get("lost_machines") or []
        if _scope_shows(scope, str(m.get("editor_username") or ""))
    ]
    # SYS-3's ignored-section record names machines and is an admin
    # diagnostic about this dashboard's own schema, not about anyone's
    # footage: it goes entirely rather than being trimmed.
    if not scope.admin:
        view.pop("ignored_report_sections", None)
        # DASH-2 / REL-11: the rotation drain names machines, and "this site
        # cannot reach the vendor's feed" is an operator's problem, not an
        # editor's. The per-machine refusal survives on the editor's OWN rows
        # (guard.report_refused_*), which is where it is actionable: sign in
        # on that computer's tray.
        view.pop("identity_key_drain", None)
        view.pop("feed_alarm", None)
    view["report_refused"] = [
        m for m in view.get("report_refused") or []
        if _scope_shows(scope, str(m.get("editor") or ""))
    ]
    return view


# ------------------------------------------------------------------ routes

def _code_block(settings) -> dict[str, Any]:
    """/api/v1/health's `code` object. Best-effort: a dashboard that cannot
    work out where its own code came from still has to answer the
    healthcheck, so every failure here is an empty block, never a 500."""
    try:
        from . import dashboard_update

        return dashboard_update.health_code_block(settings)
    except Exception:  # noqa: BLE001
        log.exception("could not describe the running code root")
        return {"running": VERSION, "image": "", "source": "", "runtime_id": ""}


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
    # A DEAD collector thread is not a healthy dashboard, whatever the last
    # poll said (ops-efficiency-6, 2026-08-21). db.fetch_collector_status only
    # sees poll_runs, so a thread that died between two cycles reads as
    # reachable until COLLECTOR_STALE_SECONDS has passed -- and one that died
    # before it ever ran a Syncthing-backed cycle (a Syncthing-less
    # deployment) never reads as anything else at all. Absent state (a test
    # that built the app without entering the lifespan) is not evidence of a
    # fault, and a collector that was STOPPED on purpose is not either: see
    # Collector.thread_died.
    runner = getattr(request.app.state, "collector", None)
    try:
        collector_down = bool(runner is not None and runner.thread_died())
    except Exception:  # noqa: BLE001
        collector_down = False
    ok = (bool(collector["syncthing_reachable"]) or not settings.syncthing_url) \
        and not collector_down
    if not (
        auth.get_session_user(request) is not None
        or companion_token_ok(settings, conn,
                              request.headers.get("x-ccsync-token", ""))
    ):
        # Enough for a probe to distinguish "process up" from "process up but
        # blind", and nothing an outsider can inventory the fleet from.
        return {
            "ok": ok,
            "version": VERSION,
        }
    return {
        "ok": ok,
        "version": VERSION,
        # WHICH CODE IS LIVE (ZERO_TOUCH_PLAN.md WP K, 2026-08-18). `ok` and
        # `version` above are untouched -- ship.ps1, the onboarding wizard and
        # the container healthcheck read those two and nothing else. This
        # block says whether `version` came from the container image or from a
        # code bundle applied over the air, which is the first question after
        # "is it up?" once a dashboard can update itself. Authenticated
        # callers only, like every other field here; imported lazily because
        # dashboard_update imports this module for _require_admin.
        "code": _code_block(settings),
        "syncthing_reachable": collector["syncthing_reachable"],
        # True = the last poll succeeded but finished too long ago, i.e. the
        # collector thread is dead/wedged. That state also clears
        # syncthing_reachable, hence `ok` above -- which is what Docker's
        # healthcheck (see deploy/compose.yaml) parses out of this body.
        "collector_stale": collector["collector_stale"],
        # ...and the direct answer, which does not wait for a poll to go
        # stale: the loop thread is gone and app.CollectorWatchdog has not
        # (yet) put one back (ops-efficiency-6, 2026-08-21).
        "collector_alive": not collector_down,
        "folder_errors": collector["folder_errors"],
        "last_polls": {
            kind: {"finished_at": run["finished_at"], "ok": bool(run["ok"]), "error": run["error"]}
            for kind, run in collector["kinds"].items()
        },
        # THE BRAKES THAT HAVE FIRED (DASH-3 / DASH-4, resilience sweep
        # 2026-08-28). A refused enforce pass and a refused deactivation pass
        # are both states in which every cycle above still reports ok while
        # nothing is being applied, so they belong in the one route an
        # operator (and the container healthcheck's reader) already looks at.
        # Best-effort: a health route that cannot answer is worse than one
        # that answers without this block.
        "collector_alarms": _collector_alarms_block(conn),
        # REL-11 / REL-5 (resilience sweep 2026-08-28). A feed that has been
        # unreachable for six weeks was visible on exactly one admin page, and
        # nothing anywhere measured the volume the SQLite database lives on --
        # which fills silently and turns every write, the fleet's own reports
        # included, into a disk I/O error. Both are best-effort blocks: a
        # health route that cannot answer them still has to answer.
        **_feed_and_space_block(request, conn),
        # SYS-8: how many things this server currently believes are wrong,
        # counted live from alerts.scan rather than from what was DELIVERED,
        # so the number is the same on a site whose sink is "none".
        "open_alerts": _open_alerts_block(request, conn),
        # UX-10 (2026-08-28): how many diagnoses this server has written and
        # nobody has acted on. Beside open_alerts on purpose -- one is what we
        # would send, the other is what we found.
        "notices": _open_notices_block(conn),
    }


def _open_notices_block(conn: sqlite3.Connection) -> dict[str, int]:
    """{"error": n, "warn": n}, best-effort.

    A count that cannot be read is reported as one `error`, on the same rule
    as open_alerts: "we could not check" must never render as "nothing
    wrong"."""
    try:
        counts = db.notice_counts(conn)
    except Exception:  # noqa: BLE001
        log.exception("could not count open notices for /health")
        return {"error": 1, "warn": 0}
    return {"error": int(counts.get("error", 0)), "warn": int(counts.get("warn", 0))}


def _open_alerts_block(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    """{"error": n, "warn": n}, best-effort.

    A scan that cannot run is reported as one `error` rather than as zero:
    "we could not check" must never render as "nothing wrong" (SYS-8).
    """
    from . import alerts

    try:
        findings = alerts.scan(conn, request.app.state.settings, db.utcnow_iso())
        return alerts.open_counts(findings)
    except Exception:  # noqa: BLE001
        log.exception("could not scan for open alerts")
        return {"error": 1, "warn": 0, "scan_failed": True}


def _feed_and_space_block(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    from . import dashboard_update

    settings = request.app.state.settings
    out: dict[str, Any] = {}
    try:
        out["feed"] = dashboard_update.feed_health(conn, settings, request.app.state)
    except Exception:  # noqa: BLE001
        log.exception("could not read the release feed state")
    try:
        out["data"] = dashboard_update.data_space(settings)
    except Exception:  # noqa: BLE001
        log.exception("could not measure free space on the data volume")
    return out


def _collector_alarms_block(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        return db.collector_alarms(conn)
    except Exception:  # noqa: BLE001
        log.exception("could not read the collector alarm state")
        return {}


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
        # A site_settings row when there is one, else provision.py's
        # env-derived copy (site_store.resolved_manifest). The claim that the
        # tree an installer expects and the tree /project-setup creates cannot
        # drift apart was FALSE for the DB-override case until 2026-08-21
        # (dash-admin-3): this route served the row while create_tree_project,
        # the /project-setup preview and the collector's shared-folder
        # provisioning all read the import-time env value. All three go
        # through site_store now, so the claim holds again. server/common.py
        # holds the same two lists and server/tests/test_cross_component.py
        # pins them byte-identical for the env-only shape.
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
            # Unattended updates (2026-08-18). Published because the
            # COMPANION is the client that acts on it -- and read fail-closed
            # there, so a dashboard too old to send it, or a companion that
            # cannot reach one, keeps waiting for a human click.
            "auto_update": site["features"]["auto_update"],
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
                     projects_view: dict[str, Any] | None = None,
                     machine: str | None = None) -> dict[str, Any]:
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
    links_by_borrower = db.fetch_links_for_borrowers(conn)
    items = []
    for sel in db.fetch_selections(conn, editor, machine=machine):
        slug = sel["slug"]
        project = projects.get(slug)
        my_rows = [e for e in project["editors"] if e["editor_username"] == editor] if project else []
        best = my_rows[0] if my_rows else None
        rclone = rclone_by_project.get(slug)
        items.append({
            "slug": slug,
            "label": sel["label"] or slug,
            "position": sel["position"],
            "sync_mode": sel.get("sync_mode") or db.SYNC_MODE_FULL,
            "upload_only": (sel.get("sync_mode") or db.SYNC_MODE_FULL)
                           == db.SYNC_MODE_UPLOAD_ONLY,
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
            # Borrowed folders this queued project pulls in (ok links only)
            # -- shown as muted sub-lines under the queue row (§4.3).
            "includes": [
                {"sub_rel": l["sub_rel"],
                 "lender_label": l["lender_label"] or l["lender_slug"]}
                for l in links_by_borrower.get(slug, []) if l["status"] == "ok"
            ],
        })
    ticked = {i["slug"] for i in items}
    # NOT rendered anywhere since 2026-08-18: the queue panel's [ ADD TO QUEUE ]
    # row was the only reader, and ticking moved to the sidebar tree, which
    # builds its own checkboxes from the projects view. Kept because the view
    # dict is a shape callers read (and it is one pass over an already-loaded
    # dict, no query) -- delete it with its last consumer, not before.
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
            # The computers a person-level untick from this panel would take
            # the project off, named in the confirm (DASH-8, 2026-08-28).
            "machines": db.machines_of(conn, editor),
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
        # copy-paste of secrets. Empty when the server has none configured
        # -- and empty once the operator has RETIRED it with
        # DASH_SHARED_REPORT_TOKEN_ENABLED=0 (dash-core-2, 2026-08-21).
        # Handing out a token every route now refuses made a freshly signed-in
        # companion adopt a credential its very next report would 401 on, with
        # nothing on the dashboard pointing at why: the machine never gets far
        # enough to write a report_auth row.
        "report_token": (settings.report_token
                         if settings.shared_report_token_enabled else ""),
        # Which credential this fleet expects, so the tray can say "ask your
        # admin for a per-editor token" rather than "report failed". CR-18
        # stands: /verify never mints a cce1 token.
        "report_token_kind": ("shared" if (settings.report_token
                                           and settings.shared_report_token_enabled)
                              else "editor"),
        # "base" (direct-NAS-access machine, e.g. the admin's own rig) vs
        # "editor" (normal remote sync lanes) -- same DASH_ADMIN_USERS list
        # that gates dashboard admin actions, reused here by design (see
        # docs/SERVER.md's "Admin: Users section"). The companion uses this
        # to flip its sync behavior on sign-in instead of trusting a
        # hand-edited local config.toml `mode` value -- see
        # companion/src/ccsync_companion/identity.py.
        "role": "base" if auth.is_admin(settings, username) else "editor",
    }
    # REL-16 (resilience sweep 2026-08-28): getattr, because `arch` is an
    # optional report field a companion older than this wave never sends and
    # a ReportIn/VerifyIn that has not declared it yet does not carry -- and
    # "no arch reported" is offered everything, exactly as before.
    upgrade = _upgrade_info(conn, payload.platform, payload.companion_version,
                            getattr(payload, "arch", None))
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


def _machine_arg(machine: str | None) -> str | None:
    """The `?machine=` query parameter, normalised.

    Absent or blank means "not saying", which every caller reads as the
    person-level answer -- NOT as db.ANY_MACHINE, which is a real machine
    value (the unassigned bucket) and must never be reachable from a URL."""
    value = (machine or "").strip()
    return value or None


def _expand_includes(
    conn: sqlite3.Connection, rows: list,
) -> dict[str, list[dict[str, Any]]]:
    """slug -> borrowed-folder entries for ONE machine's selection rows
    (SHARED_FOLDERS_PLAN.md §4.2). Server-side policy, so the companion
    stays dumb (D5): `ok` links only; an include equal to or inside another
    granted include is omitted (longest prefix wins) so no subtree is ever
    handed out twice.

    A link whose lender is itself in this machine's selection is NOT
    omitted (a deliberate deviation from the plan's first draft): it is
    marked `covered: true`. The companion never runs a covered include (its
    own dedupe drops anything under a selected rel -- the double-dedupe the
    plan requires anyway), but the tray's removal gate needs the
    relationship to warn that removing the LENDER strands a selected
    borrower's shared folder."""
    selected = {r["slug"] for r in rows}
    links_by_borrower = db.fetch_links_for_borrowers(conn, selected)
    out: dict[str, list[dict[str, Any]]] = {}
    claimed: list[str] = []
    for r in rows:                                   # position order
        entries = []
        for link in links_by_borrower.get(r["slug"], []):
            if link["status"] != "ok" or not link["lender_slug"] or not link["sub_rel"]:
                continue
            lender_label = link["lender_label"]
            if not lender_label:
                # No projects row for the lender: no current rel to build a
                # subpath from. _run_links will have downgraded the status
                # next cycle anyway.
                continue
            covered = link["lender_slug"] in selected
            subpath = f"{lender_label}/{link['sub_rel']}"
            if not covered:
                if any(subpath == c or subpath.startswith(c + "/") for c in claimed):
                    continue
                claimed.append(subpath)
            entries.append({
                "subpath": subpath,
                "lender_slug": link["lender_slug"],
                "lender_label": lender_label,
                "sub_rel": link["sub_rel"],
                "covered": covered,
            })
        if entries:
            out[r["slug"]] = entries
    return out


def _selection_view(conn: sqlite3.Connection, editor: str,
                    machine: str | None = None) -> dict[str, Any]:
    rows = db.fetch_selections(conn, editor, machine=machine)
    includes_by_slug = _expand_includes(conn, rows)
    return {
        "editor": editor,
        "machine": machine or "",
        # Every computer this person has, so a companion (and the wizard) can
        # offer "copy the plan from ..." without a second round trip.
        "machines": db.machines_of(conn, editor),
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
                # The tick's mode (docs/UPLOAD_ONLY_TICK.md): `full` or
                # `upload_only`. Additive: a companion older than 0.9.54
                # ignores it and runs lanes A and B for the project -- lane C
                # cannot follow, because the enforce cycle never shares the
                # folder with an upload-only machine.
                "sync_mode": r["sync_mode"] or db.SYNC_MODE_FULL,
                # Borrowed folders (SHARED_FOLDERS_PLAN.md §4.2): additive
                # key, ignored by old companions; `subpath` is spelled like
                # rel_path so the companion prefixes PROJECTS_PREFIX exactly
                # as it does for the project's own runs.
                "includes": includes_by_slug.get(r["slug"], []),
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
    editor: str, request: Request, machine: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    """This computer's plan, or -- with no `machine` -- the union of the
    person's computers (WP2).

    The union is what a companion too old to name itself gets, and for every
    single-machine editor it IS that machine's plan. Deliberately not the
    intersection: an old build that over-syncs fills a drive, an old build
    that under-syncs is an editor who quietly cannot open a project."""
    editor = editor.strip().lower()
    _require_selection_read(request, editor, conn)
    return _selection_view(conn, editor, machine=_machine_arg(machine))


def audit_plan_change(
    conn: sqlite3.Connection, actor: str, action: str, editor: str, slug: str,
    target: str | None, before: list[dict[str, str]], after: list[dict[str, str]],
) -> int:
    """Record one tick or untick in the fleet audit ledger (SYS-11 / DASH-8,
    resilience sweep 2026-08-28), and answer 0 for a change that changed
    nothing.

    BOTH placements are stored, not the intent: the person-level untick
    removes rows from every computer that person owns, each possibly in a
    different mode, and "put it back" is only answerable from what was there.
    That makes [ UNDO ] a restore of `before`, and it makes the same row
    readable as history a year later.

    Shared by the JSON API and the htmx toggle deliberately: a ledger the
    second door can walk past is worse than no ledger, because it reads as
    "nobody did that".
    """
    if before == after:
        return 0
    return db.audit(conn, actor, action, slug, {
        "editor": editor, "slug": slug, "machine": target or "",
        "scope": "machine" if target else "person",
        "before": before, "after": after,
    })


def _sync_mode_arg(mode: str | None) -> str:
    """The `?mode=` query parameter of a tick. Absent means `full` -- what
    every tick meant before 2026-08-27, and what an old client or a
    bookmarked URL still means. Anything but the two known modes is a 400:
    a typo must not quietly become a full sync of a project someone wanted
    upload-only."""
    value = (mode or "").strip().lower() or db.SYNC_MODE_FULL
    if value not in db.SYNC_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown sync mode {value!r}: use 'full' or 'upload_only'",
        )
    return value


def tick_capacity_warning(
    conn: sqlite3.Connection, editor: str, slug: str, machine: str | None = None
) -> str | None:
    """UX-1 (resilience sweep 2026-08-28): what this tick costs, in one line.

    "2026/FF5/Animals is 620 GB of proxies. LESO-MBP has 180 GB free."

    REFUSES NOTHING, by design (the owner may know something the dashboard
    does not), and stays silent when either figure is unknown -- an un-walked
    project read as 0 GB would be worse than no preflight at all. With no
    machine named the tick is the PERSON, so every computer they own is
    checked and each one that would be tight gets its own sentence: that is
    what [ ALL ] onto a 500 GB MacBook looked like from the owner's side, and
    it said nothing.
    """
    proxy_bytes = db.project_proxy_bytes(conn, slug)
    if not proxy_bytes:
        return None
    row = conn.execute(
        "SELECT label FROM projects WHERE slug=?", (slug,)
    ).fetchone()
    label = (row["label"] if row is not None else slug) or slug
    targets = [machine] if machine else db.machines_of(conn, editor)
    sentences = []
    for target in targets:
        if not target:
            continue
        free, _at = db.machine_free_bytes(conn, editor, target)
        sentence = health.capacity_warning(label, proxy_bytes, target, free)
        if sentence:
            sentences.append(sentence)
    if not sentences:
        return None
    # Three is enough to make the point; a person with six laptops does not
    # need a wall of text in a confirm dialog.
    return " ".join(sentences[:3])


@router.put("/selection/{editor}/{slug}")
def api_tick(
    editor: str, slug: str, request: Request, machine: str | None = None,
    mode: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    """Tick, in a MODE (`?mode=full|upload_only`, docs/UPLOAD_ONLY_TICK.md).
    A PUT on a project already ticked in the other mode SWITCHES it and
    answers changed=true; the same mode again is the no-op it always was."""
    editor = editor.strip().lower()
    user = _require_selection_write(request, editor)
    sync_mode = _sync_mode_arg(mode)
    project = conn.execute(
        "SELECT slug FROM projects WHERE slug=? AND active=1", (slug,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail=f"unknown or inactive project {slug!r}")
    if editor in db.base_only_editors(conn):
        # CR-28: this account's machines all work directly off the NAS tree.
        # A tick would sync nothing, show nothing and clear never -- which is
        # exactly what the base rig's stray tick did to the fleet page.
        # UNTICKING stays allowed (below), so an existing one can be removed.
        raise HTTPException(
            status_code=409,
            detail="this is a base rig account: it works directly off the NAS "
                   "and syncs nothing, so projects cannot be ticked for it",
        )
    target = _machine_arg(machine)
    known = db.machines_of(conn, editor)
    if target is not None and target not in known:
        # A hostname this account has never reported: a stale page after a
        # rename, or a typed URL. Refusing beats writing a plan for a
        # computer that does not exist, which nothing would ever read and
        # nobody would see was there.
        raise HTTPException(
            status_code=404,
            detail=f"{editor!r} has no computer named {target!r}",
        )
    if target is not None and (editor, target) in db.base_machines(conn):
        # CR-28 per MACHINE (dash-admin-8, 2026-08-21). The refusal above is
        # per person and so cannot see a mixed account: one wired desktop and
        # one remote laptop under one name is a shape a site can have (commit
        # f27c181), and a tick on the wired half is the same stuck
        # [ GETTING READY ] chip CR-28 was raised for.
        raise HTTPException(
            status_code=409,
            detail=f"{target!r} is a wired machine: it works directly off the NAS "
                   "and syncs nothing, so projects cannot be ticked for it",
        )
    now = db.utcnow_iso()
    before = db.selection_placements(conn, editor, slug, machine=target)
    if target is None:
        # No machine named: every computer this person has, which is what the
        # person-level control in the grid means and what an old client (or a
        # bookmarked URL) can express. An editor with no machine on record
        # yet gets the unassigned bucket, which their first report inherits.
        added = db.add_selection_for_person(conn, editor, slug, user, now,
                                            sync_mode=sync_mode)
    else:
        added = db.add_selection(conn, editor, slug, created_by=user, now=now,
                                 machine=target, sync_mode=sync_mode)
    audit_plan_change(conn, user, db.AUDIT_TICK, editor, slug, target, before,
                      db.selection_placements(conn, editor, slug, machine=target))
    conn.commit()
    _nudge_collector(request)
    view = _selection_view(conn, editor, machine=target)
    view["changed"] = added
    # UX-1: the consequence, after the fact for an API caller and BEFORE the
    # PUT for the two UIs, which read the same figures out of the page and
    # confirm first (assignments.js, project_detail.html). Never a refusal.
    view["warning"] = tick_capacity_warning(conn, editor, slug, target)
    return view


@router.delete("/selection/{editor}/{slug}")
def api_untick(
    editor: str, slug: str, request: Request, machine: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    editor = editor.strip().lower()
    # The actor the audit ledger needs, and the helper already knows it:
    # a session admin, the editor themself, or "companion:<editor>" for the
    # tray's own untick-before-delete (SYS-11, 2026-08-28).
    actor = _require_selection_untick(request, editor, conn)
    target = _machine_arg(machine)
    # No machine named removes it EVERYWHERE, including the unassigned
    # bucket: under-sharing is the safe direction for a removal, and an old
    # client asking for "stop syncing this" must not leave it running on one
    # of the person's computers.
    before = db.selection_placements(conn, editor, slug, machine=target)
    removed = db.remove_selection(conn, editor, slug, machine=target)
    audit_plan_change(conn, actor, db.AUDIT_UNTICK, editor,
                      slug, target, before,
                      db.selection_placements(conn, editor, slug, machine=target))
    conn.commit()
    _nudge_collector(request)
    view = _selection_view(conn, editor, machine=target)
    view["changed"] = removed
    return view


class ProjectRootIn(BaseModel):
    resolve_project: str = Field(min_length=1, max_length=256)
    slug: str | None = None   # None = delete the mapping (re-detected on next report)


# ---------------------------------------------- cross-project folder links
# (SHARED_FOLDERS_PLAN.md WP5). The MARKER is the truth: these endpoints
# edit the borrower's .ccsync-project `includes` (preserving every other
# key) and refresh the project_links mirror inline so the UI answers
# immediately rather than one provision cycle later.


class ProjectLinkIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


def _require_link_write(request: Request, conn: sqlite3.Connection, slug: str) -> str:
    """Admin, or an editor with this project ticked (the plan's rule: the
    people a project syncs to are the ones who may reshape what it pulls)."""
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="log in first")
    if auth.is_admin(settings, user):
        return user
    if user in db.fetch_all_selections(conn).get(slug, []):
        return user
    raise HTTPException(
        status_code=403,
        detail="only an admin or an editor syncing this project can change its shared folders",
    )


# ---------------------------------------------- dashboard-driven file moves
# (docs/FILE_MOVES.md, 2026-08-27). A file uploaded into the wrong project
# folder cannot be fixed by moving it on the NAS alone: lane A on every
# machine still holding it at the old path is a one-way copy that never
# deletes, so the next pass puts it straight back. The move is made HERE, on
# the mounted Projects tree, and every computer that syncs the source project
# (or has reported holding the file) is told to move its own copy and relink
# Resolve, through the same report-reply command channel the halt uses.

class FileMoveIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)        # inside the source project
    to_slug: str | None = Field(default=None, max_length=128)  # default: the same project
    to_path: str = Field(default="", max_length=1024)        # folder or full path inside it


def _require_move_write(request: Request) -> str:
    """Admins only. A move rewrites the server tree and reaches into every
    machine that holds the file, so it is an operator action even when the
    editor who mis-filed the card is the one asking."""
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="log in first")
    if not auth.is_admin(settings, user):
        raise HTTPException(status_code=403, detail="only an admin can move files on the server")
    return user


def _clean_project_rel(raw: str, what: str, *, allow_empty: bool) -> str:
    """A project-relative posix path from user input: each segment through
    the tree validator, no `Proxy` segment (a proxy travels with its
    original, it is never moved on its own), and never the marker."""
    value = str(raw or "").strip().replace("\\", "/").strip("/")
    if not value:
        if allow_empty:
            return ""
        raise ProjectSetupError(f"{what} is required")
    parts = [_validate_tree_part(p, f"{what} segment") for p in value.split("/") if p]
    if any(p.lower() == "proxy" for p in parts):
        raise ProjectSetupError(
            f"{what} must not name a Proxy folder: proxies move with their originals")
    from . import provision

    if parts[-1] == provision.MARKER_FILENAME:
        raise ProjectSetupError(f"{what} must not be the project marker")
    return "/".join(parts)


def _active_project_label(conn: sqlite3.Connection, slug: str) -> str:
    row = conn.execute(
        "SELECT label FROM projects WHERE slug=? AND active=1", (slug,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown or inactive project {slug!r}")
    return str(row["label"])


def _move_proxy_siblings(src: Path, dest: Path) -> tuple[int, list[str]]:
    """A file's proxies live beside it in `Proxy/<stem>.*` (the BPG/Resolve
    convention every lane is built on). They go where the original goes, or
    Resolve's auto-link on every other machine breaks the moment lane B
    delivers the proxy to the OLD folder.

    Returns (moved, names that could not move). It never raises: DASH-1
    (2026-08-28) -- this used to run inside the caller's fatal try, so one
    proxy held open by a Resolve on a wired rig turned a completed move into
    a 503 reading "the server could not move it", with the original already
    gone and no record written at all."""
    proxy_dir = src.parent / "Proxy"
    try:
        if not proxy_dir.is_dir():
            return 0, []
        candidates = sorted(proxy_dir.iterdir())
    except OSError as exc:
        log.warning("file move: could not read %s (%s)", proxy_dir, exc)
        return 0, [f"{proxy_dir.name} (could not be read: {exc})"]
    moved = 0
    failed: list[str] = []
    for candidate in candidates:
        try:
            if not candidate.is_file() or candidate.stem.lower() != src.stem.lower():
                continue
            target_dir = dest.parent / "Proxy"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / candidate.name
            if target.exists():
                failed.append(f"{candidate.name} (something is already at the destination)")
                continue
            candidate.rename(target)
            moved += 1
        except OSError as exc:
            log.warning("file move: proxy %s did not follow (%s)", candidate, exc)
            failed.append(f"{candidate.name} ({exc})")
    return moved, failed


def move_project_files(settings, conn: sqlite3.Connection, from_slug: str,
                       body: FileMoveIn, user: str,
                       undo_of: int | None = None) -> dict[str, Any]:
    """Move a file or folder inside the Projects tree, on the server, and
    record the command for every machine that has to follow. Refuses rather
    than guesses: a destination that already exists, a move into itself, a
    path that escapes the tree, a `Proxy` folder as either end."""
    try:
        projects_dir = _projects_dir_or_error(settings)
        from_label = _active_project_label(conn, from_slug)
        to_slug = (body.to_slug or from_slug).strip()
        to_label = _active_project_label(conn, to_slug)
        from_rel = _clean_project_rel(body.path, "the path to move", allow_empty=False)
        to_rel = _clean_project_rel(body.to_path, "the destination", allow_empty=True)
        src, _ = _safe_rel(settings, f"{from_label}/{from_rel}")
        dest, _ = _safe_rel(settings, f"{to_label}/{to_rel}" if to_rel else to_label)
    except ProjectSetupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not src.exists():
        raise HTTPException(
            status_code=404, detail=f"nothing at {from_label}/{from_rel} on the server")
    if dest.is_dir():
        # A folder as the destination means "into it", the way Explorer and
        # Finder read a drop -- and the way an admin types it.
        dest = dest / src.name
        to_rel = f"{to_rel}/{src.name}" if to_rel else src.name
    if dest.exists():
        raise HTTPException(
            status_code=409, detail=f"{to_label}/{to_rel} already exists: nothing was moved")
    if src.is_dir() and dest.resolve().is_relative_to(src.resolve()):
        raise HTTPException(status_code=400, detail="a folder cannot be moved into itself")
    if src == dest:
        raise HTTPException(status_code=400, detail="that is where it already is")
    is_dir = src.is_dir()
    # Who has to follow: every computer syncing the source project (either
    # mode: an upload-only machine is exactly the one holding a card dump at
    # the old path), plus any computer whose manifest says it holds the file
    # even though its plan no longer does.
    targets: set[tuple[str, str]] = set()
    for editor, machine in db.fetch_machine_selections(conn).get(from_slug, []):
        if machine:
            targets.add((editor, machine))
    for row in conn.execute(
        """SELECT DISTINCT editor_username, machine FROM editor_media
            WHERE project_slug=? AND (rel_path=? OR rel_path LIKE ?)""",
        (from_slug, from_rel, from_rel + "/%"),
    ):
        targets.add((row["editor_username"], row["machine"]))
    now = db.utcnow_iso()
    # DASH-1 (resilience sweep 2026-08-28): the record FIRST, committed, and
    # only then the rename. It used to be the other way round, so a rename
    # that succeeded and then met anything at all -- a proxy sibling held open
    # by a Resolve, a container restart, a full /data -- moved the original
    # with no row anywhere saying so. No row means no command to any machine,
    # which means every machine still holding it re-uploads the old path
    # (lane A never deletes) while the editors' Resolve projects point at a
    # file that is no longer there. A `pending` row is offered to nobody
    # (db.pending_file_moves) and is reconciled by stat-ing both ends.
    move_id = db.record_file_move(
        conn, from_slug=from_slug, from_project_rel=from_label, from_rel=from_rel,
        to_slug=to_slug, to_project_rel=to_label, to_rel=to_rel, is_dir=is_dir,
        proxies_moved=0, requested_by=user, now=now, targets=sorted(targets),
        state=db.FILE_MOVE_PENDING, undo_of=undo_of,
    )
    conn.commit()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
    except OSError as exc:
        # A rename across two mounts, a permission the container lacks, a
        # file Resolve holds open on the share: all of them leave the file
        # where it was, which is the safe outcome, and all of them are the
        # admin's to read. The reservation goes with it -- nothing moved, so
        # there is nothing for any machine to follow.
        conn.execute("DELETE FROM file_move_targets WHERE move_id=?", (move_id,))
        conn.execute("DELETE FROM file_moves WHERE id=?", (move_id,))
        db.audit(conn, user, "file.move.refused", from_slug,
                 {"move_id": move_id, "from": f"{from_label}/{from_rel}",
                  "to": f"{to_label}/{to_rel}", "error": str(exc)[:300]}, now=now)
        conn.commit()
        raise HTTPException(status_code=503, detail=f"the server could not move it: {exc}")
    # OUTSIDE the fatal try, because by here the original HAS moved: a proxy
    # that could not follow is a partial result to be named, never a 503 that
    # claims nothing happened (DASH-1).
    proxies_moved = 0
    proxies_failed: list[str] = []
    if not is_dir:
        proxies_moved, proxies_failed = _move_proxy_siblings(src, dest)
    state = db.FILE_MOVE_PARTIAL if proxies_failed else db.FILE_MOVE_DONE
    detail = ("these proxies did not move: " + ", ".join(proxies_failed)) if proxies_failed else ""
    db.complete_file_move(conn, move_id, state=state, proxies_moved=proxies_moved,
                          detail=detail)
    conn.commit()
    log.info("%s moved %s/%s -> %s/%s on the server (%d proxies with it, %d could not); "
             "%d machine(s) to follow", user, from_label, from_rel, to_label, to_rel,
             proxies_moved, len(proxies_failed), len(targets))
    return {
        "ok": True, "move_id": move_id, "state": state,
        "from": f"{from_label}/{from_rel}", "to": f"{to_label}/{to_rel}",
        "is_dir": is_dir, "proxies_moved": proxies_moved,
        "proxies_failed": proxies_failed,
        "machines": [{"editor": e, "machine": m} for e, m in sorted(targets)],
    }


@router.post("/projects/{slug}/move")
def api_move_project_files(
    slug: str, body: FileMoveIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    user = _require_move_write(request)
    settings = request.app.state.settings
    result = move_project_files(settings, conn, slug, body, user)
    if result.get("proxies_failed"):
        # 207: the original moved and the machines have been told, but this
        # answer must never read as "everything moved" (DASH-1).
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=207, content=result)
    return result


@router.get("/projects/{slug}/moves")
def api_project_moves(
    slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    _require_move_write(request)
    return {"slug": slug, "moves": db.file_moves_for_project(conn, slug),
            "awaiting": db.file_moves_awaiting_machines(conn, db.utcnow_iso())}


def undo_file_move(settings, conn: sqlite3.Connection, slug: str, move_id: int,
                   user: str) -> dict[str, Any]:
    """Put a move back (UX-11), through the same machinery that made it.

    The inverse is a file_moves row like any other -- the same server rename,
    the same per-machine commands, the same journal -- because a second
    mechanism for putting a file back is a second mechanism that can be wrong
    about which machines hold it. Refused while any computer FAILED or is
    BLOCKED: that machine still has its copy at the old path, and moving the
    server copy back under it leaves the fleet in a third state nobody asked
    for."""
    move = db.file_move(conn, move_id)
    if move is None or slug not in (move["from_slug"], move["to_slug"]):
        raise HTTPException(status_code=404, detail=f"no move {move_id} on this project")
    if move["state"] == db.FILE_MOVE_UNDONE:
        raise HTTPException(status_code=409, detail="that move has already been put back")
    if not move["undoable"]:
        raise HTTPException(
            status_code=409,
            detail="one of the computers could not apply this move, so its copy is still "
                   "at the old path. Sort that computer out first, then put it back.")
    if move["is_dir"]:
        # The repo's rule for anything privileged and recursive (CLAUDE.md,
        # server/common.snapshot_before). Best-effort: a NAS that cannot take
        # a snapshot is not a NAS where an admin loses the undo button.
        try:
            from . import dashboard_update

            snap = dashboard_update.snapshot_before(settings, f"file-move-undo-{move_id}")
            if not snap.get("ok"):
                log.warning("undo of move %s: no snapshot (%s)", move_id,
                            snap.get("reason") or snap.get("detail") or "")
        except Exception:  # noqa: BLE001 - never block the undo over a snapshot
            log.exception("undo of move %s: snapshot attempt failed", move_id)
    to_dir = move["from_rel"].rsplit("/", 1)[0] if "/" in move["from_rel"] else ""
    body = FileMoveIn(path=move["to_rel"], to_slug=move["from_slug"], to_path=to_dir)
    result = move_project_files(settings, conn, move["to_slug"], body, user,
                                undo_of=move_id)
    # Every computer the ORIGINAL reached, whether or not it syncs the project
    # the file is currently in: those are the machines with a copy to put
    # back. Without this an undo out of a project only one editor syncs moves
    # the server copy and leaves the fleet's copies where they were.
    added = db.add_file_move_targets(
        conn, int(result["move_id"]),
        [(t["editor_username"], t["machine"]) for t in move["targets"]])
    if added:
        result["machines"] = sorted(
            result["machines"] + [{"editor": t["editor_username"], "machine": t["machine"]}
                                  for t in move["targets"]],
            key=lambda m: (m["editor"], m["machine"]))
        seen: set[tuple[str, str]] = set()
        result["machines"] = [m for m in result["machines"]
                              if not ((m["editor"], m["machine"]) in seen
                                      or seen.add((m["editor"], m["machine"])))]
    db.mark_file_move_undone(conn, move_id, int(result["move_id"]))
    db.audit(conn, user, "file.move.undo", move["from_slug"],
             {"move_id": move_id, "undo_move_id": result["move_id"],
              "from": f"{move['to_project_rel']}/{move['to_rel']}",
              "to": f"{move['from_project_rel']}/{move['from_rel']}"})
    conn.commit()
    result["undo_of"] = move_id
    return result


@router.post("/projects/{slug}/moves/{move_id}/undo")
def api_undo_project_move(
    slug: str, move_id: int, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    user = _require_move_write(request)
    return undo_file_move(request.app.state.settings, conn, slug, move_id, user)


@router.post("/projects/{slug}/moves/{move_id}/reissue")
def api_reissue_project_move(
    slug: str, move_id: int, request: Request, editor: str, machine: str,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Offer an expired move to that computer again (DASH-9). The alternative
    used to be silence: the command simply stopped being offered and the
    machine went on holding the file at the old path."""
    user = _require_move_write(request)
    move = db.file_move(conn, move_id)
    if move is None or slug not in (move["from_slug"], move["to_slug"]):
        raise HTTPException(status_code=404, detail=f"no move {move_id} on this project")
    ok = db.reissue_file_move(conn, move_id, editor.strip().lower(), machine.strip(),
                              db.utcnow_iso(), actor=user)
    conn.commit()
    if not ok:
        raise HTTPException(status_code=409,
                            detail="that computer has already answered this move")
    return {"ok": True, "move_id": move_id, "editor": editor, "machine": machine}


def reconcile_file_moves(settings, conn: sqlite3.Connection) -> dict[str, int]:
    """Finish (or quarantine) every move whose row is still `pending`.

    DASH-1: the row is committed before the rename, so a container that died
    between the two leaves a `pending` row and a tree that is in one of three
    states. Only the destination exists: the rename DID happen, so the record
    is completed and the commands go out. Only the source: it did not, so the
    reservation is dropped. Both, or neither: something else is going on and
    guessing would be the expensive kind of wrong -- the row stays pending
    (offered to nobody) and an alarm goes on the project page.

    Run at boot and once per collector cycle. Never raises."""
    counts = {"completed": 0, "dropped": 0, "quarantined": 0}
    try:
        rows = db.unfinished_file_moves(conn)
    except sqlite3.Error:
        log.exception("could not read unfinished file moves")
        return counts
    quarantined: list[dict[str, Any]] = []
    for move in rows:
        try:
            src, _ = _safe_rel(settings, f"{move['from_project_rel']}/{move['from_rel']}")
            dest, _ = _safe_rel(settings, f"{move['to_project_rel']}/{move['to_rel']}")
        except (ProjectSetupError, HTTPException):
            log.warning("file move %s: cannot resolve its paths to reconcile it", move["id"])
            continue
        src_here, dest_here = src.exists(), dest.exists()
        if dest_here and not src_here:
            db.complete_file_move(conn, move["id"], state=db.FILE_MOVE_DONE,
                                  proxies_moved=int(move["proxies_moved"] or 0),
                                  detail="completed after an interrupted move")
            counts["completed"] += 1
            log.warning("file move %s was interrupted after the rename; completed it and "
                        "the machines are being told", move["id"])
        elif src_here and not dest_here:
            conn.execute("DELETE FROM file_move_targets WHERE move_id=?", (move["id"],))
            conn.execute("DELETE FROM file_moves WHERE id=?", (move["id"],))
            counts["dropped"] += 1
            log.warning("file move %s never happened (the file is still at the old path); "
                        "dropped the record", move["id"])
        else:
            counts["quarantined"] += 1
            quarantined.append({
                "id": move["id"],
                "from": f"{move['from_project_rel']}/{move['from_rel']}",
                "to": f"{move['to_project_rel']}/{move['to_rel']}",
                "both": bool(src_here and dest_here),
                "slugs": [move["from_slug"], move["to_slug"]],
            })
            log.error(
                "file move %s is in an ambiguous state on the server (source present: %s, "
                "destination present: %s); no computer will be told until an admin sorts "
                "it out", move["id"], src_here, dest_here)
    try:
        if quarantined:
            db.meta_set_json(conn, FILE_MOVE_ALARM_KEY, quarantined)
        else:
            db.meta_delete(conn, FILE_MOVE_ALARM_KEY)
        # UX-5 / DASH-9, in the same pass: a command that was DELIVERED and
        # never answered ages out and says so on the project page. An
        # UNDELIVERED one never expires -- that machine has not had its
        # chance yet, and it is the one still holding the file at the old
        # path for lane A to re-upload.
        for row in db.expire_delivered_file_moves(conn, db.utcnow_iso()):
            counts["expired"] = counts.get("expired", 0) + 1
            log.warning(
                "file move %s was told to %s/%s and never answered; that computer may "
                "re-upload the old path until it is re-issued",
                row["move_id"], row["editor_username"], row["machine"])
        conn.commit()
    except sqlite3.Error:
        log.exception("could not write the file-move reconciliation result")
    return counts


# The `meta` key the ambiguous-move alarm lives under. `meta` rather than the
# notices table because that table is another work package of the same sweep
# (v37) and this alarm must not wait on it; the project page reads it.
FILE_MOVE_ALARM_KEY = "file_move_quarantine"


def file_move_alarms(conn: sqlite3.Connection, slug: str = "") -> list[dict[str, Any]]:
    """The quarantined moves, optionally only the ones touching one project."""
    try:
        rows = db.meta_get_json(conn, FILE_MOVE_ALARM_KEY) or []
    except sqlite3.Error:
        return []
    if not isinstance(rows, list):
        return []
    if not slug:
        return [r for r in rows if isinstance(r, dict)]
    return [r for r in rows if isinstance(r, dict) and slug in (r.get("slugs") or [])]


def _link_marker_dir(settings, conn: sqlite3.Connection, slug: str) -> tuple[Path, str, Path]:
    """(projects_dir, borrower_rel, marker_dir) for a link edit, or an
    HTTPException. The marker must carry THIS slug: editing a marker whose
    identity disagrees with the projects row would write the declaration
    into somebody else's project."""
    from . import provision

    try:
        projects_dir = _projects_dir_or_error(settings)
    except ProjectSetupError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    row = conn.execute(
        "SELECT label FROM projects WHERE slug=? AND active=1", (slug,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown or inactive project {slug!r}")
    borrower_rel = str(row["label"])
    directory = projects_dir / Path(*[p for p in borrower_rel.split("/") if p])
    if provision.read_marker(directory) != slug:
        raise HTTPException(
            status_code=409,
            detail="this project's folder marker does not carry its identity; "
                   "repair the marker before editing its shared folders",
        )
    return projects_dir, borrower_rel, directory


def _sync_link_rows(conn: sqlite3.Connection, projects_dir: Path, borrower_rel: str,
                    slug: str) -> None:
    """Refresh the project_links mirror for one borrower from its marker.
    The same resolve + lender-active downgrade the collector's _run_links
    applies (minus the stale-path retarget, which needs prior rows and a
    moved lender -- the next provision cycle covers that case)."""
    from . import provision

    data = provision.read_marker_data(projects_dir / Path(*borrower_rel.split("/"))) or {}
    results = links.resolve_marker_includes(projects_dir, borrower_rel, data.get("includes"))
    proj_rows = {
        r["slug"]: r["active"]
        for r in conn.execute("SELECT slug, active FROM projects")
    }
    rows = []
    for res in results:
        status, detail = res.status, res.detail
        if status in (links.STATUS_OK, links.STATUS_MISSING):
            if not proj_rows.get(res.lender_slug or ""):
                status = links.STATUS_LENDER_INACTIVE
                detail = "the lending project is not active on the dashboard"
        keep = status in (links.STATUS_OK, links.STATUS_MISSING)
        rows.append({
            "declared_path": res.declared,
            "lender_slug": res.lender_slug if keep else None,
            "sub_rel": res.sub_rel if keep else None,
            "status": status,
            "detail": detail or None,
        })
    db.replace_project_links(conn, slug, rows, db.utcnow_iso())
    conn.commit()


def _link_path_with_prefix(raw: str) -> str:
    """The UI lets people paste the label spelling ('2026/FF5/...'); the
    declaration always carries the projects dir name."""
    text = links.normalise_declared(raw)
    if text and not text.startswith(links.PROJECTS_SEGMENT + "/") \
            and text != links.PROJECTS_SEGMENT and not text.startswith("/"):
        return f"{links.PROJECTS_SEGMENT}/{text}"
    return text


def add_project_link(settings, conn: sqlite3.Connection, slug: str, path: str,
                     user: str) -> dict[str, Any]:
    """Shared by the JSON endpoint and the UI partial. Raises HTTPException
    on every refusal, with the validator's own reason in the detail."""
    from . import provision

    projects_dir, borrower_rel, directory = _link_marker_dir(settings, conn, slug)
    res = links.resolve_include(projects_dir, borrower_rel, _link_path_with_prefix(path))
    if res.status != links.STATUS_OK:
        raise HTTPException(status_code=422,
                            detail=f"cannot share that folder: {res.detail or res.status}")
    data = provision.read_marker_data(directory) or {}
    includes = data.get("includes")
    includes = list(includes) if isinstance(includes, list) else []
    existing, _bad = links.parse_includes(includes)
    changed = all(links.normalise_declared(p) != res.declared for p in existing)
    if changed:
        if len(includes) >= links.MAX_INCLUDES:
            raise HTTPException(
                status_code=422,
                detail=f"this project already shares {links.MAX_INCLUDES} folders; "
                       f"remove one first")
        includes.append({"path": res.declared, "added_by": user,
                         "added_at": db.utcnow_iso()})
        data["includes"] = includes
        provision.write_marker_data(directory, data)
    _sync_link_rows(conn, projects_dir, borrower_rel, slug)
    return {"changed": changed, "declared_path": res.declared}


def remove_project_link(settings, conn: sqlite3.Connection, slug: str, path: str,
                        user: str) -> dict[str, Any]:
    from . import provision

    projects_dir, borrower_rel, directory = _link_marker_dir(settings, conn, slug)
    want = links.normalise_declared(_link_path_with_prefix(path))
    data = provision.read_marker_data(directory) or {}
    includes = data.get("includes")
    includes = list(includes) if isinstance(includes, list) else []

    def declared_of(entry: Any) -> str:
        if isinstance(entry, str):
            return links.normalise_declared(entry)
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            return links.normalise_declared(entry["path"])
        return ""

    kept = [e for e in includes if declared_of(e) != want]
    changed = len(kept) != len(includes)
    if changed:
        if kept:
            data["includes"] = kept
        else:
            data.pop("includes", None)
        provision.write_marker_data(directory, data)
    _sync_link_rows(conn, projects_dir, borrower_rel, slug)
    return {"changed": changed, "declared_path": want}


@router.post("/projects/{slug}/links")
def api_add_project_link(
    slug: str, payload: ProjectLinkIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    user = _require_link_write(request, conn, slug)
    settings = request.app.state.settings
    out = add_project_link(settings, conn, slug, payload.path, user)
    out["links"] = db.fetch_links_for_borrowers(conn, [slug]).get(slug, [])
    return out


@router.delete("/projects/{slug}/links")
def api_remove_project_link(
    slug: str, path: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    user = _require_link_write(request, conn, slug)
    settings = request.app.state.settings
    out = remove_project_link(settings, conn, slug, path, user)
    out["links"] = db.fetch_links_for_borrowers(conn, [slug]).get(slug, [])
    return out


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
    from . import provision, site_store

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
        # The site's OWN template, DB-first (dash-admin-3 / CR-58,
        # 2026-08-21). This used to iterate provision.TEMPLATE_FOLDERS -- the
        # value the container booted with -- so on an appliance, where compose
        # sets no DASH_SITE_*, an admin whose wizard answer said
        # "Footage, Audio, Graphics" was PREVIEWED that list by /project-setup
        # and then given the documentary defaults by this create.
        for sub in site_store.template_folders(conn, settings):
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
    owned = conn is None
    c = conn if conn is not None else db.connect(settings.db_path)
    try:
        return _build_admin_users_view(settings, c)
    finally:
        if owned:
            c.close()


def build_computers_view(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every computer the registry knows (v23), one row each, for the Users
    page's [ COMPUTERS ] table and the JSON view (CR-76, 2026-08-24). The
    registry is the authority on which computers exist; machine_state only
    decorates the row with what its last report said."""
    versions = db.fetch_companion_version_map(conn)
    modes = db.machine_modes(conn)
    plan_counts = {
        (r["editor_username"], r["machine"]): r["n"]
        for r in conn.execute(
            "SELECT editor_username, machine, COUNT(*) AS n FROM selections "
            "WHERE machine != '' GROUP BY editor_username, machine")
    }
    rows = []
    for m in db.fetch_machines(conn):
        key = (m["editor_username"], m["machine"])
        state = versions.get(key) or {}
        rows.append({
            "editor_username": m["editor_username"],
            "machine": m["machine"],
            "platform": (m.get("platform") or state.get("platform") or "").strip().lower() or None,
            "syncthing_device_id": m.get("syncthing_device_id"),
            "companion_version": state.get("companion_version"),
            "last_seen": m.get("last_seen"),
            "mode": modes.get(key, "editor"),
            "plan_count": plan_counts.get(key, 0),
        })
    return rows


def _build_admin_users_view(settings, conn: sqlite3.Connection) -> dict[str, Any]:
    method = str(getattr(settings, "auth_method", "") or "smb").strip().lower()
    result: dict[str, Any] = {"auth_method": method, "local_users": None}
    if method == "local":
        result["local_users"] = local_users.list_users(conn)

    # The fleet's own records, which exist whatever the identity backend
    # (CR-76): every computer, and every editor the fleet knows who has no
    # account in the section above -- a device approved under a name nobody
    # provisioned, or an account already removed at the NAS by hand. Those
    # are the ones only [ DELETE ] on this page can clean up.
    result["computers"] = build_computers_view(conn)
    known = db.known_editor_usernames(conn)
    account_names: set[str] = {
        str(u.get("username") or "").lower() for u in (result["local_users"] or [])
    }

    if not nas_factory.nas_configured(settings):
        # No NAS credential: the appliance's default shape (ZERO_TOUCH_PLAN.md
        # §5, "the customer's NAS admin credential is optional"). This is no
        # longer a reason to 503 or hide the whole page -- local_users above
        # already answered the identity question; the NAS section (editor
        # accounts, device approval) simply has nothing to show.
        result.update({"truenas_configured": False, "editors": [], "pending_devices": [],
                       "error": None, "truenas_error": None, "syncthing_error": None,
                       "known_editors": sorted(approvable_editor_usernames(conn)),
                       "fleet_only_editors": sorted(known - account_names)})
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
                        **_pending_owner_hint(conn, d["deviceID"]),
                    })
            for device_id, info in (syncthing.pending_devices() or {}).items():
                if device_id in configured_ids:
                    continue
                pending.append({
                    "device_id": device_id,
                    "current_name": (info or {}).get("name") or "",
                    "status": "pending",
                    **_pending_owner_hint(conn, device_id),
                })
        except SyncthingError as exc:
            syncthing_error = f"syncthing: {exc}"
            pending = []

    if method != "local":
        account_names |= {str(e["username"]).lower() for e in editor_rows}
    result.update({
        "truenas_configured": True,
        "editors": editor_rows,
        "pending_devices": pending,
        # The valid answers to "who owns this computer", offered as a datalist
        # on each pending row so the OWNER is one click and the machine name is
        # not the path of least resistance (CR-91). Union, not just the NAS
        # accounts: an editor whose account was removed at the NAS by hand still
        # owns their computers, and a local-auth site has no NAS list at all.
        "known_editors": sorted(approvable_editor_usernames(conn)),
        # kept as one string for existing callers/tests; the per-backend keys
        # are what the template renders each half's empty state from
        "error": "; ".join(e for e in (truenas_error, syncthing_error) if e) or None,
        "truenas_error": truenas_error,
        "syncthing_error": syncthing_error,
        # An unreachable NAS lists no accounts, which must not read as "every
        # editor has no account" and put a [ DELETE ] beside each of them.
        "fleet_only_editors": (
            [] if (truenas_error and method != "local") else sorted(known - account_names)),
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
    # Off by default so an existing integration cannot mint an editor by
    # accident; see approve_username_error (CR-91).
    create_new: bool = False


def _pending_owner_hint(conn: sqlite3.Connection, device_id: str) -> dict[str, str]:
    """Who the REGISTRY already says owns this device, for the approve row.

    A companion self-reports `machines.syncthing_device_id` as soon as it has a
    local Syncthing, which is normally BEFORE an admin gets to this page (see
    collector.py's unapproved-device warning). So in the ordinary case the
    dashboard already knows the answer it was making the admin guess, and
    guessing is what produced CR-91. When the registry has no row - a device
    that has never reported, or one added by hand in the Syncthing GUI - both
    keys are empty and the admin picks from the datalist as before.
    """
    known = db.machine_by_device_id(conn, device_id)
    if not known:
        return {"suggested_owner": "", "suggested_machine": ""}
    return {
        "suggested_owner": str(known.get("editor_username") or ""),
        "suggested_machine": str(known.get("machine") or ""),
    }


def approvable_editor_usernames(conn: sqlite3.Connection) -> set[str]:
    """The usernames a device may be approved under without CREATE NEW EDITOR.

    ONE definition, two callers -- the picker on the page and the guard on the
    POST -- so the page can never offer a name the POST then refuses (CR-91).

    Deliberately LOCAL-only: no NAS call. The guard runs on every approve, and
    making it depend on a reachable NAS would turn a backend blip into "this
    editor does not exist". A NAS account the fleet has no record of is a real
    "new to this dashboard" case, and ticking the box is what records it.
    """
    names = set(db.known_editor_usernames(conn))
    try:
        names |= {str(u.get("username") or "").lower() for u in local_users.list_users(conn)}
    except sqlite3.Error:
        # Local accounts are one source among several, not a precondition.
        pass
    return {n for n in names if n}


# Approving a device RECORDS its label as a known editor (record_known_editor,
# below), and being KNOWN is exactly what promotes a device from UNMAPPED to
# mapped in db.resolve_editor_username. So typing the COMPUTER's name here --
# which the row openly invites, printing CURRENT NAME "Razer" beside a box
# labelled ASSIGN USERNAME -- mints an editor who owns no selections rows, and
# the next enforce cycle computes `desired` without that device and unshares it
# from every folder it is on. That is the B16 failure shape, reached through the
# supported admin UI rather than through a hand-edited Syncthing config
# (CR-91, 2026-08-28).
#
# resolve_editor_username already refuses to map a label that is not a known
# editor; this stops the approve dialog from manufacturing the knowledge that
# defeats it. A genuinely new editor is still approvable -- the admin just has
# to say that is what they mean.
def approve_username_error(
    conn: sqlite3.Connection, username: str, create_new: bool
) -> str | None:
    """None if `username` may be approved, else the reason it may not."""
    if create_new or username in approvable_editor_usernames(conn):
        return None
    return (
        f"'{username}' is not an editor this dashboard knows. Pick the OWNER of "
        "this computer: one editor can own several computers, so a second "
        "machine takes the same username as the first. Tick CREATE NEW EDITOR "
        "if this really is a new person."
    )


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
    field has no toggle on the NasBackend Protocol).

    Disabling REVOKES, it does not just flag (dash-core-3 / trust-model-2,
    2026-08-21). `users.disabled` is read at login and by is_local_admin, and
    by nothing else: a session cookie is a bearer token whose server-side row
    decides (sessions.py) and a cce1 report token authenticates a MACHINE, so
    the contractor whose account an admin disabled kept their open tab for up
    to 7 days and their companion kept reporting and pulling selections for
    ever. DELETE has purged both since it was written; DISABLE is the
    non-destructive button an admin actually reaches for, so it must mean the
    same thing. Re-enabling gives the account back its password, not its old
    sessions or its old machine token: a new token is one click on the Users
    page.

    The two refusals are delete's (dash-admin-5, 2026-08-21), for the same
    reason and with the same 409: is_local_admin returns False for a disabled
    row and auth.is_admin consults it on every request, so disabling yourself
    or the last enabled admin takes admin away from the very session that did
    it, and only DASH_ADMIN_USERS (a redeploy on the appliance shape) or
    sqlite surgery gets it back."""
    admin = _require_admin(request)
    _require_local_mode(request)
    settings = request.app.state.settings
    username = username.strip().lower()
    user = local_users.get_user(conn, username)
    if user is None:
        raise HTTPException(status_code=404, detail=f"{username!r} is not a local account")
    if payload.disabled:
        if username == admin.strip().lower():
            raise HTTPException(
                status_code=409,
                detail="you cannot disable the account you are signed in as - sign in as "
                       "another admin to disable this one",
            )
        if (user["role"] == "admin" and not user["disabled"]
                and local_users.count_enabled_admins(conn) <= 1):
            raise HTTPException(
                status_code=409,
                detail="this is the last enabled admin account - create another admin "
                       "before disabling it",
            )
    try:
        local_users.disable_user(conn, username, payload.disabled)
    except local_users.LocalUserError as exc:
        # 409 for a guard refusal, 404 only for "no such account": the request
        # is well-formed and would be fine against a different one, which is
        # the same split api_admin_delete_user documents.
        status = 404 if "not a local account" in str(exc) else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    conn.commit()
    purged = {"sessions_revoked": 0, "report_tokens_revoked": 0}
    if payload.disabled:
        # AFTER the commit: _purge_user_credentials revokes sessions through
        # the store's own connection to the same SQLite file, and calling it
        # with a write transaction open on `conn` deadlocks the two.
        purged = _purge_user_credentials(request, conn, username, by=admin,
                                         why="account disabled")
        log.warning("admin %r disabled local account %r (%d session(s), %d report "
                    "token(s) revoked)", admin, username,
                    purged["sessions_revoked"], purged["report_tokens_revoked"])
    return {"ok": True, "purged": purged, "view": build_admin_users_view(settings, conn)}


def _purge_user_credentials(request: Request, conn: sqlite3.Connection, username: str, *,
                            by: str, why: str = "account deleted") -> dict[str, int]:
    """Everything that can still ACT as `username` once the account row is
    gone. Deleting the row alone is not enough: a session cookie is a bearer
    token whose server-side record decides (sessions.py), and a per-editor
    report token authenticates a MACHINE, not a login -- either would keep
    working against an account nobody can sign into any more.

    Token revocation is a soft delete on this connection (the caller commits);
    session revocation is NOT, because the session store opens its own
    short-lived connection to the same SQLite file -- call this while an
    uncommitted write transaction is open on `conn` and the two deadlock.
    Hence the ordering contract: commit the delete, then call this.

    `why` is what the revocation records say happened -- "account deleted" or
    "account disabled" (dash-core-3, 2026-08-21): both take every credential
    away, and an admin reading a revoked token's reason should see which one
    it was."""
    revoked_tokens = 0
    for row in db.fetch_editor_report_tokens(conn, editor=username):
        if db.revoke_editor_report_token(conn, row["token_id"],
                                         revoked_by=f"admin:{by} ({why})"):
            revoked_tokens += 1
    conn.commit()
    store = auth.session_store(request)
    revoked_sessions = (
        store.revoke_user(username, by=f"admin:{by} ({why})")
        if store is not None else 0
    )
    return {"sessions_revoked": revoked_sessions, "report_tokens_revoked": revoked_tokens}


def _remove_editor_devices(settings, device_ids: list[str], *,
                           named: str | None = None) -> list[dict[str, Any]]:
    """Take every one of these devices out of Syncthing (CR-76). `named`
    adds any configured device whose label IS that username -- a device an
    admin approved for them before a companion ever reported an id, which
    the registry and the collector's mirror may both still be missing.

    Raises SyncthingError when Syncthing cannot be asked; the callers turn
    that into "nothing was deleted" and roll back, because a device left in
    Syncthing after its rows are gone is unmapped, which the enforce cycle
    leaves alone (B16) -- it would keep receiving every project it was ever
    shared. No Syncthing configured at all means nothing to remove."""
    if not settings.syncthing_url:
        return []
    client = SyncthingClient.from_settings(settings)
    ids = [d for d in device_ids if d]
    if named:
        wanted = named.strip().lower()
        my_id = str(client.system_status().get("myID", "") or "")
        for dev in client.config().get("devices", []):
            device_id = dev.get("deviceID")
            if (device_id and device_id != my_id and device_id not in ids
                    and str(dev.get("name") or "").strip().lower() == wanted):
                ids.append(device_id)
    removed = []
    for device_id in ids:
        outcome = client.remove_device(device_id)
        if outcome["removed"]:
            removed.append({"device_id": device_id, "unshared": outcome["unshared"]})
    return removed


def delete_user_everywhere(request: Request, conn: sqlite3.Connection, username: str, *,
                           admin: str) -> dict[str, Any]:
    """Delete a person from the whole product (CR-76, 2026-08-24): their
    account (local row, or the NAS account through the backend's
    delete_editor), every one of their computers' records, their Syncthing
    devices and shares, and every credential that could still act as them.
    The one implementation behind DELETE /admin/users/{username} and the
    Users page button, so the button is never a softer door than the route.

    The ORDER is the point, because half of this cannot be rolled back:

      1. the local account row goes first, uncommitted -- its guards (the
         account you are signed in as, the last enabled admin) raise before
         anything irreversible has happened;
      2. Syncthing devices next. If Syncthing cannot be asked, everything
         so far is rolled back and the caller gets a 502 saying nothing was
         deleted: the alternative leaves a stranger's machine receiving
         projects forever (B16 -- the enforce cycle will not touch it);
      3. the NAS account, which no rollback can restore, once the shares are
         provably gone. A refusal or a NAS error here rolls the local rows
         back; the devices stay removed, which is the safe direction and a
         no-op on the retry;
      4. the fleet rows (db.forget_editor), then the commit;
      5. sessions and report tokens, AFTER the commit -- the session store
         writes through its own connection to the same file, and calling it
         with a write transaction open on `conn` deadlocks the two.

    A username the fleet knows but no backend has an account for (a device
    approved under a name nobody provisioned; an account already removed at
    the NAS by hand) is deletable too: that is the only way its records and
    its device can be cleaned up. Unknown everywhere is a 404."""
    settings = request.app.state.settings
    username = username.strip().lower()
    if not is_valid_username(username):
        raise HTTPException(status_code=422, detail="not a valid username")
    if username == admin.strip().lower():
        raise HTTPException(
            status_code=409,
            detail="you cannot delete the account you are signed in as - sign in as "
                   "another admin to remove this one",
        )
    local = _local_mode(settings)
    known = username in db.known_editor_usernames(conn)
    nas: NasBackend | None = None
    account: dict[str, Any] | None = None
    if local:
        account = local_users.get_user(conn, username)
    elif nas_factory.nas_configured(settings):
        nas = _nas_client_or_503(request)
        try:
            account = nas.find_user(username)
        except NasError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"{settings.nas_kind}: {exc} - nothing was deleted") from exc
    if account is None and not known:
        raise HTTPException(
            status_code=404,
            detail=f"{username!r} is not an account or an editor this dashboard knows")

    result: dict[str, Any] = {"username": username, "account": None, "warnings": []}
    if local and account is not None:
        try:
            result["account"] = local_users.delete_user(conn, username, requested_by=admin)
        except local_users.LocalUserError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        result["devices_removed"] = _remove_editor_devices(
            settings, db.editor_device_ids(conn, username), named=username)
    except SyncthingError as exc:
        conn.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"syncthing could not be reached ({exc}), so nothing was deleted - "
                   "try again once it is up",
        ) from exc

    if nas is not None and account is not None:
        try:
            result["account"] = nas.delete_editor(username)
        except NasError as exc:
            conn.rollback()
            raise HTTPException(
                status_code=502,
                detail=f"{settings.nas_kind}: {exc} - the account and the fleet records "
                       "were left in place",
            ) from exc
        result["warnings"].extend(result["account"].get("warnings") or [])

    result["fleet"] = db.forget_editor(conn, username)
    db.audit(conn, admin, "user.delete", username,
             {"machines": result["fleet"]["machines"],
              "devices_removed": len(result["devices_removed"])})
    conn.commit()
    purged = _purge_user_credentials(request, conn, username, by=admin)
    result.update(purged)
    log.warning(
        "admin %r deleted user %r: account=%s, %d machine(s) forgotten (%s), %d syncthing "
        "device(s) removed, %d session(s), %d report token(s) revoked",
        admin, username,
        "none" if result["account"] is None else
        ("local" if local else (settings.nas_kind or "nas")),
        len(result["fleet"]["machines"]), ", ".join(result["fleet"]["machines"]) or "-",
        len(result["devices_removed"]), purged["sessions_revoked"],
        purged["report_tokens_revoked"])
    return result


def forget_machine_everywhere(request: Request, conn: sqlite3.Connection, editor: str,
                              machine: str, *, admin: str) -> dict[str, Any]:
    """Remove one computer from the fleet (CR-76): its Syncthing device and
    shares first (abort with nothing removed if Syncthing cannot be asked --
    see delete_user_everywhere for why), then its records.

    Not a revocation. The person keeps their account and their report
    tokens, which authenticate the PERSON, so a companion still running on
    that computer registers it again on its next report; the response says
    so, and so does the button's confirm. Deleting the user is the
    revocation; this is for the laptop that was wiped, renamed, or
    replaced."""
    settings = request.app.state.settings
    editor, machine = editor.strip().lower(), machine.strip()
    row = conn.execute(
        "SELECT syncthing_device_id FROM machines WHERE editor_username=? AND machine=?",
        (editor, machine),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no machine {machine!r} for {editor!r}")
    try:
        removed = _remove_editor_devices(
            settings, [row["syncthing_device_id"]] if row["syncthing_device_id"] else [])
    except SyncthingError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"syncthing could not be reached ({exc}), so the computer was not "
                   "removed - try again once it is up",
        ) from exc
    for entry in removed:
        db.forget_device(conn, entry["device_id"])
    forgotten = db.forget_machine(conn, editor, machine)
    db.audit(conn, admin, "machine.forget", machine,
             {"editor": editor, "machine": machine,
              "deleted": (forgotten or {}).get("deleted", {})})
    conn.commit()
    log.warning("admin %r removed computer %s/%s (%d syncthing device(s) removed, plan rows %d)",
                admin, editor, machine, len(removed),
                (forgotten or {}).get("deleted", {}).get("selections", 0))
    return {"ok": True, "editor": editor, "machine": machine, "devices_removed": removed,
            "deleted": (forgotten or {}).get("deleted", {}),
            "note": "a companion still running and signed in on this computer will "
                    "register it again on its next report"}


@router.delete("/admin/users/{username}")
def api_admin_delete_user(
    username: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Delete a user everywhere (CR-76): see delete_user_everywhere for what
    goes, in what order, and why. Until 2026-08-24 this was local mode only
    and left the fleet's records standing; DISABLE remains the
    non-destructive button for "stop this person signing in".

    409, not 422, for the guard refusals (deleting yourself, the last enabled
    admin): the request is well-formed and would be fine against a different
    account -- it conflicts with the state of this one. 502 when a backend
    could not be asked, and the detail says what was and was not done."""
    admin = _require_admin(request)
    settings = request.app.state.settings
    result = delete_user_everywhere(request, conn, username, admin=admin)
    account = result["account"] or {}
    return {"ok": True,
            "deleted": {**account,
                        "machines": result["fleet"]["machines"],
                        "devices_removed": result["devices_removed"],
                        "sessions_revoked": result["sessions_revoked"],
                        "report_tokens_revoked": result["report_tokens_revoked"]},
            "warnings": result["warnings"],
            "view": build_admin_users_view(settings, conn)}


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
    it is the one field an admin must actually fill in when halting.

    UX-8 (resilience sweep 2026-08-28): the Users page has always required a
    reason and this model did not, so the JSON twin could stop the whole fleet
    with a blank one -- and then nobody's tray said why. min_length applies to
    a HALT only, which is why the check is in the route rather than on the
    field: releasing a halt needs no reason. `hours` is how long the halt
    stands before it expires by itself; `extend` is [ KEEP HALTED ]."""
    active: bool
    reason: str = Field(default="", max_length=500)
    hours: float | None = Field(default=None, gt=0, le=24 * 30)
    extend: bool = False


@router.get("/fleet/halt")
def api_fleet_halt(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    """Read the fleet halt. Any signed-in user (or a companion holding the
    report token) may READ it -- an editor whose tray says "your admin
    stopped syncing" must be able to confirm that from the dashboard --
    while setting it is admin-only below."""
    settings = request.app.state.settings
    # Both companion credentials, through the one resolver every other
    # companion-facing route has used since 2026-08-17 (dash-core-5,
    # 2026-08-21): this route was missed, so it still honoured a shared token
    # that DASH_SHARED_REPORT_TOKEN_ENABLED=0 had retired and still 401'd a
    # companion holding only its per-editor cce1 token.
    if not (
        auth.get_session_user(request) is not None
        or companion_token_ok(settings, conn, request.headers.get("x-ccsync-token", ""))
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
    if payload.active and len(payload.reason.strip()) < 3:
        # UX-8: the same rule the Users page has always applied, on the door
        # that did not apply it. Every editor's tray shows this sentence.
        raise HTTPException(
            status_code=422,
            detail="say why: the reason is shown in every editor's tray "
                   "(at least 3 characters)",
        )
    try:
        state = db.set_fleet_halt(conn, payload.active, payload.reason, admin,
                                  hours=payload.hours, extend=payload.extend)
    except ValueError as exc:
        # UX-8 (resilience sweep 2026-08-28): extend=true on a halt that has
        # already ended (see db.set_fleet_halt) must not silently start a
        # fresh, blank-reason halt.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conn.commit()
    log.warning(
        "FLEET HALT %s by %s: %s",
        "ENGAGED" if state["active"] else "released", admin, state["reason"] or "(no reason)",
    )
    return {"ok": True, "halt": state}


class PushUpdateIn(BaseModel):
    # Absent = "whatever is current for that machine's platform", which is
    # what the button on the packages page means. An explicit version is
    # still allowed so a rollback can be pushed the same way.
    version: str | None = Field(default=None, max_length=32)


@router.post("/admin/machines/{editor}/{machine}/update")
def api_push_machine_update(
    editor: str, machine: str, request: Request,
    payload: PushUpdateIn | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Ask ONE machine to apply a published build on its next report.

    The editor still does not have to click anything, and nothing here
    bypasses a check: the companion applies it only if the signed offer it is
    already holding is that exact version (release_trust + the downgrade
    floor), and only when swapping the exe would not kill work in progress.
    So this is "click Update now on their behalf", not a remote installer.
    """
    admin = _require_admin(request)
    editor, machine = editor.strip().lower(), machine.strip()
    row = conn.execute(
        "SELECT platform FROM machines WHERE editor_username=? AND machine=?",
        (editor, machine),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no machine {machine!r} for {editor!r}")
    version = ((payload.version if payload else None) or "").strip()
    if not version:
        current = db.get_current_package(
            conn, (row["platform"] or "").strip().lower(), kind="companion")
        if current is None:
            raise HTTPException(
                status_code=409,
                detail="no current companion package is published for that machine's platform",
            )
        version = current["version"]
    if not db.request_machine_update(conn, editor, machine, version, admin, db.utcnow_iso()):
        raise HTTPException(status_code=404, detail=f"no machine {machine!r} for {editor!r}")
    conn.commit()
    log.info("%s asked %s/%s to update to v%s", admin, editor, machine, version)
    return {"ok": True, "editor": editor, "machine": machine, "version": version}


@router.delete("/admin/machines/{editor}/{machine}/update")
def api_cancel_machine_update(
    editor: str, machine: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    _require_admin(request)
    editor, machine = editor.strip().lower(), machine.strip()
    db.clear_machine_update_request(conn, editor, machine)
    conn.commit()
    return {"ok": True}


@router.delete("/admin/machines/{editor}/{machine}")
def api_forget_machine(
    editor: str, machine: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Remove one computer from the fleet (CR-76): its Syncthing device and
    shares, its sync plan, its status rows. See forget_machine_everywhere
    for the order and for why this is not a revocation. 404 when the
    registry has no such computer; 502, with nothing removed, when Syncthing
    cannot be asked."""
    admin = _require_admin(request)
    return forget_machine_everywhere(request, conn, editor, machine, admin=admin)


@router.post("/admin/machines/{editor}/{machine}/resume-lane-b")
def api_resume_machine_lane_b(
    editor: str, machine: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Clear ONE machine's lane B circuit breaker on its next report (v26).

    This is "click Resume proxy download on their behalf", not an override:
    the companion does exactly what the tray button does, and it does it
    only while its breaker is actually tripped. What changes is who can
    reach the decision -- the admin who just checked the NAS, rather than
    only the editor sitting in front of the machine.

    Refused for a machine whose last report does NOT show a trip
    (comp-lanes-ab-2, 2026-08-21). It used to be allowed, to "get in front of
    one" -- but a request armed before the trip is a decision taken about a
    trip nobody has seen: the machine's first report after it delivers an
    automatic resume of whatever tripped, which for an offline machine can be
    days later and a completely different cause. There is nothing to get in
    front of anyway, because the request is delivered on the machine's next
    report either way. A companion too old to send a guard section (< 0.9.43)
    reports nothing here and is refused for the same reason: it has no
    breaker to clear.
    """
    admin = _require_admin(request)
    editor, machine = editor.strip().lower(), machine.strip()
    if machine not in db.machines_of(conn, editor):
        raise HTTPException(status_code=404, detail=f"no machine {machine!r} for {editor!r}")
    if not db.machine_breaker_tripped(conn, editor, machine):
        raise HTTPException(
            status_code=409,
            detail="that computer's last report does not show proxy download parked, "
                   "so there is nothing to resume. Wait for its next report and try again.",
        )
    if not db.request_lane_b_resume(conn, editor, machine, admin, db.utcnow_iso()):
        raise HTTPException(status_code=404, detail=f"no machine {machine!r} for {editor!r}")
    conn.commit()
    log.info("%s asked %s/%s to resume proxy download", admin, editor, machine)
    return {"ok": True, "editor": editor, "machine": machine}


@router.delete("/admin/machines/{editor}/{machine}/resume-lane-b")
def api_cancel_machine_lane_b_resume(
    editor: str, machine: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    _require_admin(request)
    editor, machine = editor.strip().lower(), machine.strip()
    db.clear_lane_b_resume_request(conn, editor, machine)
    conn.commit()
    return {"ok": True}


@router.post("/admin/machines/{editor}/{machine}/copy-plan")
def api_copy_machine_plan(
    editor: str, machine: str, request: Request, source: str = "",
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Copy one of this person's computers' plans onto another of them.

    A new machine starts empty (no inheritance -- see MULTI_MACHINE_PLAN.md
    §3.2), and this is what makes that a one-click state rather than a
    re-tick of everything."""
    admin = _require_admin(request)
    editor, machine, source = editor.strip().lower(), machine.strip(), source.strip()
    known = set(db.machines_of(conn, editor))
    if machine not in known:
        raise HTTPException(status_code=404, detail=f"no machine {machine!r} for {editor!r}")
    if source not in known:
        raise HTTPException(status_code=404, detail=f"no machine {source!r} for {editor!r}")
    if source == machine:
        raise HTTPException(status_code=422, detail="source and target are the same computer")
    if editor in db.base_only_editors(conn):
        raise HTTPException(
            status_code=409,
            detail="this is a base rig account: it works directly off the NAS "
                   "and syncs nothing, so projects cannot be ticked for it",
        )
    if (editor, machine) in db.base_machines(conn):
        # Per MACHINE (dash-admin-8, 2026-08-21): copying a plan onto a wired
        # computer is a tick on it by another route.
        raise HTTPException(
            status_code=409,
            detail=f"{machine!r} is a wired machine: it works directly off the NAS "
                   "and syncs nothing, so a plan cannot be copied onto it",
        )
    count = db.copy_machine_plan(conn, editor, source, machine, admin, db.utcnow_iso())
    conn.commit()
    _nudge_collector(request)
    log.info("%s copied %s's plan from %s to %s (%d project(s))",
             admin, editor, source, machine, count)
    return {"ok": True, "editor": editor, "machine": machine,
            "source": source, "projects": count}


@router.post("/admin/devices/approve")
def api_admin_approve_device(
    payload: ApproveDeviceIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    admin = _require_admin(request)
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
    # After the device-id shape check, so the two paths report the same reason
    # first for the same bad input (CR-91).
    unknown = approve_username_error(conn, username, payload.create_new)
    if unknown:
        raise HTTPException(status_code=422, detail=unknown)
    syncthing = SyncthingClient.from_settings(settings)
    try:
        syncthing.approve_device(device_id, username)
    except SyncthingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # An admin naming the device is the dashboard's strongest evidence that
    # this username is a real editor account -- record it, so the enforce
    # cycle is allowed to manage the device's shares (B16).
    db.record_known_editor(conn, username, "admin")
    db.audit(conn, admin, "device.approve", username,
             {"editor": username, "device_id": device_id})
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


# UX-9 (resilience sweep 2026-08-28). A deleted package used to be unlinked
# on the spot inside a bare `except OSError: pass`; those are the bytes a
# rollback to that version needs, and the swallow meant "deleted" could mean
# "still there". The file now goes to <data>/packages/.trash/<platform>/ for
# PACKAGE_TRASH_DAYS, and a move that fails is an ANSWER, not a pass: the row
# stays so the bytes can still be found. Shared by the JSON DELETE route here
# and the htmx partial in ui.py - one mechanism, not two.
PACKAGE_TRASH_DAYS = 30


def _trash_package_file(settings, row) -> tuple[str, str | None]:
    """Move one package's file into <data>/packages/.trash/<platform>/.

    Returns (where it went, error). A file that is ALREADY gone is not an
    error -- the row is what is being deleted -- but a file that could not be
    moved is, and the caller keeps the row so the bytes can still be found."""
    packages = settings.packages_path()
    source = packages / str(row["platform"]) / str(row["filename"])
    trash = packages / ".trash" / str(row["platform"])
    try:
        if not source.exists():
            _prune_package_trash(packages)
            return "", None
        trash.mkdir(parents=True, exist_ok=True)
        target = trash / f"{db.utcnow_iso().replace(':', '')}-{source.name}"
        source.replace(target)
        _prune_package_trash(packages)
        return str(target), None
    except OSError as exc:
        return "", (
            f"could not move {source.name} to the trash folder ({exc}). Nothing was "
            f"deleted: the package row is still here and so are its bytes."
        )


def _prune_package_trash(packages: Path) -> None:
    """Drop trashed packages older than PACKAGE_TRASH_DAYS. Best effort: a
    prune that cannot read the directory must never fail the delete that
    triggered it."""
    import datetime as _dt
    cutoff = _dt.datetime.now(_dt.timezone.utc).timestamp() - PACKAGE_TRASH_DAYS * 86400
    try:
        for path in (packages / ".trash").rglob("*"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue
    except OSError:
        return


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


def _version_tuple(text: str) -> tuple[int, ...]:
    """Dotted-numeric to a comparable tuple; () for anything a companion
    might report that is not one (a "+dirty" dev build, an empty string),
    which compares lower than every real version. Numeric per part on
    purpose: after 0.9.9 comes 0.10.0, never 1.0 (owner's rule 2026-08-18),
    and a string compare puts 0.10.0 BELOW 0.9.9."""
    raw = str(text or "").strip()
    if not raw or any(ch not in "0123456789." for ch in raw):
        return ()
    try:
        return tuple(int(p) for p in raw.split(".") if p != "")
    except ValueError:
        return ()


def _version_at_least(running: str, wanted: str) -> bool:
    """Is `running` the version that was asked for, or a later one?

    Falls back to an exact string match when either side is not
    dotted-numeric: an unparsable version must never read as "past it" and
    silently retire a request the machine has not honoured (dash-core-6)."""
    if running == wanted:
        return True
    a, b = _version_tuple(running), _version_tuple(wanted)
    return bool(a and b and a >= b)


def _arch_matches(record_arch: str, machine_arch: str) -> bool:
    """May a machine on `machine_arch` be handed a binary built for
    `record_arch`? (REL-16, resilience sweep 2026-08-28.)

    A record with no arch is every record published before this wave, and the
    answer for those is YES -- the channel worked on one arch per platform and
    silently changing that to "offer nothing" would stop every fleet in the
    field from upgrading. `universal2` is a Mac bundle carrying both slices.

    A machine that reports no arch is likewise offered everything: it is an
    older companion, and the pre-existing behaviour is the safe one for it.
    An arch that is stated on BOTH sides and disagrees is the case this
    exists for: an Intel Mac downloads, verifies and renames an arm64 binary
    over its running companion, which then cannot exec.
    """
    rec = str(record_arch or "").strip().lower()
    mach = str(machine_arch or "").strip().lower()
    if not rec or not mach or rec == "universal2":
        return True
    return rec == mach


def _upgrade_info(
    conn: sqlite3.Connection, platform: str | None, running: str | None,
    arch: str | None = None,
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
    # Three reasons to offer NOTHING rather than this build (resilience sweep
    # 2026-08-28). Each is silent to the companion on purpose -- there is no
    # "refused offer" shape in the protocol and inventing one would reach
    # every build in the field -- and loud on the Packages page, which is
    # where somebody can act on it.
    if _row_str(current, "retracted_at"):
        # REL-3: the vendor recalled this build. Machines already running it
        # are rolled back by [ ROLL THE FLEET BACK TO x ], not by silence.
        return None
    if package_store.blocks_on_dashboard_version(
            "companion", _row_str(current, "requires_dashboard")):
        # REL-4 / SYS-13: this build needs a newer dashboard than the one
        # answering. Offering it is the ordering violation that CR-22, CR-27a,
        # CR-49, CR-55, CR-83, CR-85 and CR-87 all are.
        return None
    if not _arch_matches(_row_str(current, "arch"), arch or ""):
        return None
    # MIGRATION SHAPE (item 4, 2026-08-17): version/url/sha256/size_bytes are
    # exactly what they were, in the same places, because 0.7.11 companions
    # are in the field right now and parse_upgrade reads those four keys and
    # ignores the rest. Everything below is ADDED, never substituted -- the
    # first signed build reaches an unverifying companion through the same
    # response shape it already understands, and verifies every build after
    # that. A row published before this migration serves signature="" and
    # is refused by any companion new enough to look.
    offer = {
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
    # The optional SIGNED extras, present in the offer only when the record
    # carries them (REL-4, REL-16, 2026-08-28). They are inside the signature,
    # so omitting one from a record that has it serves a build every verifying
    # companion would refuse; adding an empty one to a record that has not is
    # the same failure from the other side. Absent stays absent.
    for field in ("arch", "requires_dashboard"):
        value = _row_str(current, field)
        if value:
            offer[field] = value
    return offer


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


def soak_minutes_for(conn: sqlite3.Connection, settings) -> int:
    """How long a staged build must have run somewhere before it may be made
    current (REL-1, resilience sweep 2026-08-28).

    A `meta` row wins over the environment so a site can change it without a
    redeploy, and the floor is ZERO minutes on purpose: an operator who wants
    the old behaviour back sets it to 0 rather than learning a force flag.
    """
    raw = db.meta_get(conn, "release_soak_minutes")
    if raw is None:
        raw = getattr(settings, "release_soak_minutes", db.DEFAULT_SOAK_MINUTES)
    try:
        return max(0, int(float(str(raw).strip())))
    except (TypeError, ValueError):
        return db.DEFAULT_SOAK_MINUTES


def build_packages_view(conn: sqlite3.Connection, settings, now: str | None = None) -> dict[str, Any]:
    now = now or db.utcnow_iso()
    packages = []
    current: dict[str, str] = {}
    soak_minutes = soak_minutes_for(conn, settings)
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
            # The release channel's rollout state (REL-1/REL-3/REL-4/REL-13/
            # REL-16, resilience sweep 2026-08-28). `rollout` is what this
            # build IS to the fleet; the rest is what an admin needs in front
            # of them at the moment they click MAKE CURRENT.
            "rollout": _row_str(row, "rollout") or (
                "current" if bool(row["is_current"]) else "staged"),
            "staged_at": _row_str(row, "staged_at"),
            "requires_dashboard": _row_str(row, "requires_dashboard"),
            "arch": _row_str(row, "arch"),
            "git_sha": _row_str(row, "git_sha"),
            "git_dirty": bool(_row_value(row, "git_dirty") or 0),
            "retracted_at": _row_str(row, "retracted_at"),
            "retracted_reason": _row_str(row, "retracted_reason"),
        }
        entry["retracted"] = bool(entry["retracted_at"])
        entry["ordering_blocked"] = package_store.blocks_on_dashboard_version(
            entry["kind"], entry["requires_dashboard"])
        # The canary line, for a companion build that is not what the fleet is
        # already being offered: "canary: 1 machine on 0.9.55 for 22 min,
        # 0 crashes". Computed for the CURRENT build too, because after a
        # rollback the admin's next question is about the build they came from.
        if entry["kind"] == "companion":
            entry["soak"] = db.soak_state(
                conn, entry["platform"], entry["version"], soak_minutes, now)
        else:
            entry["soak"] = None
        # `current` keeps its pre-kind shape (platform -> version) and keeps
        # meaning "the companion the fleet is offered" -- the onboard current
        # is visible per-row via is_current.
        if entry["is_current"] and entry["kind"] == "companion":
            current[entry["platform"]] = entry["version"]
        packages.append(entry)
    editors = build_editors_view(conn, now)
    # Which of these already has a pushed update outstanding (v25), so the
    # page can say "asked, waiting for its next report" instead of offering
    # the same button again.
    pending_updates = {
        (r["editor_username"], r["machine"]): r["update_requested_version"]
        for r in db.fetch_machines(conn)
        if r.get("update_requested_version")
    }
    outdated = [
        {
            "editor_username": e["editor_username"],
            "machine": e["machine"],
            "companion_version": e["companion_version"],
            "received_at": e["received_at"],
            "update_requested": pending_updates.get(
                (e["editor_username"], e["machine"])),
            # REL-8 (resilience sweep 2026-08-28): what happened when this
            # machine last TRIED. Beside the request, because "asked, waiting
            # for its next report" and "has failed this build 8 times" looked
            # identical here, for ever.
            "upgrade": {
                k: (e.get("guard") or {}).get(k) for k in (
                    "upgrade_version", "upgrade_attempts", "upgrade_last_error",
                    "upgrade_last_attempt_at", "upgrade_reverted_from")
            },
        }
        for e in editors["editors"]
        if e["companion_outdated"]
    ]
    # Who [ PUSH TO ONE MACHINE ] can name (REL-1): every machine that has
    # reported, grouped by the platform whose build it could take. A staged
    # build is installable by NAME through the per-machine push channel that
    # already exists (db.machine_update_request) -- that is what makes a
    # canary a click instead of a trip to somebody's desk.
    machines_by_platform: dict[str, list[dict[str, Any]]] = {}
    for e in editors["editors"]:
        plat = (e.get("platform") or "windows").strip().lower()
        machines_by_platform.setdefault(plat, []).append({
            "editor_username": e["editor_username"],
            "machine": e["machine"],
            "companion_version": e["companion_version"],
            "update_requested": pending_updates.get(
                (e["editor_username"], e["machine"])),
        })
    # REL-16: (platform, arch) pairs machines are reporting that the current
    # build does not cover. `arch` on machine_state is v35's column, so this
    # is empty until that lands rather than wrong before it -- an empty list
    # says "nothing known", which is why the page words it as a gap it FOUND
    # and stays silent otherwise.
    arch_gaps: list[dict[str, Any]] = []
    seen_arch: dict[tuple[str, str], int] = {}
    for e in editors["editors"]:
        plat = (e.get("platform") or "windows").strip().lower()
        mach_arch = str((e.get("guard") or {}).get("arch") or e.get("arch") or "").strip().lower()
        if not mach_arch:
            continue
        seen_arch[(plat, mach_arch)] = seen_arch.get((plat, mach_arch), 0) + 1
    for (plat, mach_arch), count in sorted(seen_arch.items()):
        row = db.get_current_package(conn, plat, kind="companion")
        if row is not None and _arch_matches(_row_str(row, "arch"), mach_arch):
            continue
        arch_gaps.append({"platform": plat, "arch": mach_arch, "machines": count})
    retracted = [p for p in packages if p.get("retracted")]
    # For [ ROLL THE FLEET BACK TO x ]: how many machines are still running a
    # recalled build, per (platform, version). The recall's whole point is the
    # machines that already took it.
    for entry in retracted:
        entry["machines_running"] = len(
            db.machines_running_version(conn, entry["platform"], entry["version"]))
    return {"generated_at": now, "packages": packages, "current": current,
            "outdated_machines": outdated,
            "soak_minutes": soak_minutes,
            "machines_by_platform": machines_by_platform,
            "arch_gaps": arch_gaps,
            "retracted": retracted,
            # REL-5: the volume every one of these packages is written to.
            "data": _data_space_block(settings),
            "dashboard_version": VERSION}


def _data_space_block(settings) -> dict[str, Any]:
    from . import dashboard_update

    try:
        return dashboard_update.data_space(settings)
    except Exception:  # noqa: BLE001
        log.exception("could not measure free space on the data volume")
        return {"free_bytes": -1, "total_bytes": -1, "error": "could not measure"}


@router.get("/admin/packages")
def api_admin_packages(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    _require_admin(request)
    return build_packages_view(conn, request.app.state.settings)


def _refuse_publish_without_space(settings, request: Request) -> None:
    from . import dashboard_update

    space = _data_space_block(settings)
    free = int(space.get("free_bytes") or -1)
    if free < 0:
        return                    # could not measure: do not guess, do not block
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    needed = declared * 3 + dashboard_update.PUBLISH_MIN_FREE_BYTES
    if free < needed:
        raise HTTPException(
            status_code=507,
            detail=(f"not enough free space on the data volume: "
                    f"{free // (1024 * 1024)} MiB free, this publish needs about "
                    f"{needed // (1024 * 1024)} MiB. Old builds are pruned on publish "
                    "(current plus the two newest are kept); free some space and "
                    "try again."),
        )


@router.put("/admin/packages/{platform}/{version}")
async def api_publish_package(
    platform: str,
    version: str,
    request: Request,
    sha256: str = "",
    make_current: int = 0,
    prune: int = 1,
    kind: str = "companion",
    signature: str = "",
    pubkey_id: str = "",
    min_version: str = "",
    published_at: str = "",
    signed_binary: int = 0,
    # SIGNED, optional, companion-only (REL-4/SYS-13, REL-16, 2026-08-28):
    # the dashboard version this build needs and the CPU it was built for.
    requires_dashboard: str = "",
    arch: str = "",
    # ADVISORY and unsigned (REL-13): which commit this build came from.
    # Unsigned on purpose -- it changes nothing about what may be installed,
    # and signing it would cost the overlap release the two above already do.
    git_sha: str = "",
    git_dirty: int = 0,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Publish a companion build: raw exe bytes as the request body (no
    multipart -- python-multipart isn't a dependency and doesn't need to be),
    expected sha256 as a query param, verified server-side before anything
    becomes visible. A per-request `.part` staging file + os.replace means the
    served file is always complete, and that two publishes in flight at once
    cannot write into (or delete) each other's staging file.

    `prune` deletes all but the current build and the two newest non-current
    ones, and since REL-5 (resilience sweep 2026-08-28) it is ON by default:
    `?prune=0` opts out. It used to be opt-in, on the standing no-deletion
    rule, and neither writer passed it -- so a year of shipping left 50
    companion exes and 50 onboard exes on the dataset the SQLite database
    lives on, and a full /data takes the whole dashboard down. Current plus
    two is the rollback material anybody actually reaches for; the older
    artefacts are re-publishable from the vendor feed.

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

    # REL-5 (resilience sweep 2026-08-28): refuse BEFORE the body is streamed
    # when the volume cannot take it. dashboard_update.preflight has refused an
    # apply at 507 since WP K, and this route -- which is what actually fills
    # /data, 40 MB at a time -- had no free-space check at all. A full /data is
    # a SQLite write failure, i.e. the dashboard that tells everyone whether
    # their footage is syncing going down. Content-Length is advisory (a
    # chunked upload has none), so this is a floor plus 3x the declared body,
    # not a guarantee -- the running total below is still the real ceiling.
    _refuse_publish_without_space(settings, request)

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
            requires_dashboard=requires_dashboard.strip(), arch=arch.strip(),
            git_sha=git_sha.strip(), git_dirty=bool(git_dirty),
        )
    except package_store.PackageStoreError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    db.audit(conn, user, "package.publish", version,
             {"kind": kind, "platform": platform, "version": version,
              "make_current": bool(make_current), "signed_binary": bool(signed_binary),
              "min_version": min_version,
              "requires_dashboard": requires_dashboard.strip(),
              "arch": arch.strip(), "git_sha": git_sha.strip(),
              "git_dirty": bool(git_dirty)})
    conn.commit()
    return {"ok": True, "view": build_packages_view(conn, settings)}


def make_current_refusal(
    conn: sqlite3.Connection, settings, *, kind: str, platform: str, version: str,
    force: bool = False, confirm: str = "", now: str | None = None,
) -> tuple[int, str] | None:
    """(status, detail) when this build may NOT be handed to the fleet, else
    None. THE gate (REL-1/SYS-6, REL-3, REL-4/SYS-13, 2026-08-28).

    One function because there are three doors into "make current" -- the JSON
    route, the Packages page's htmx twin, and the roll-back button -- and a
    gate that only two of them pass through is not a gate. Order matters: a
    recall and an ordering violation are facts about the BUILD and no
    confirmation overrides them, while the soak is a judgement about
    EVIDENCE, which an admin is allowed to overrule in front of a typed
    confirmation.
    """
    row = db.get_package(conn, platform, version, kind)
    if row is None:
        return 404, f"no published {platform} {kind} package {version}"
    reason = _row_str(row, "retracted_reason")
    if _row_str(row, "retracted_at"):
        return 409, (
            f"{kind} {version} was RECALLED by the vendor"
            + (f": {reason}" if reason else "")
            + ". It cannot be made current. Roll the fleet back to a build "
              "that was not recalled."
        )
    requires = _row_str(row, "requires_dashboard")
    if package_store.blocks_on_dashboard_version(kind, requires):
        return 409, (
            f"{kind} {version} needs dashboard {requires} and this dashboard is "
            f"{VERSION}. Update the dashboard first, then make this build current."
        )
    if not _row_str(row, "signature") and not (
        force and str(confirm or "").strip() == str(version).strip()
    ):
        # UX-9 (resilience sweep 2026-08-28). An UNSIGNED build made current
        # stops every companion upgrading, silently: they verify the record
        # signature and refuse the offer, and the only signal anywhere was a
        # chip on this page. A judgement about evidence rather than a fact
        # about the build, so it goes through the SAME typed override the soak
        # gate uses -- one mechanism, not two.
        return 409, (
            f"{kind} {version} has no release signature. Companions verify "
            f"signatures, so making it current stops EVERY machine in the fleet "
            f"from updating, silently. Republish it through tools\\ship.cmd "
            f"instead. To make it current anyway, type the version number "
            f"({version}) into the confirmation box."
        )
    if _row_value(row, "ever_current"):
        # A ROLLBACK, not a rollout: this build has been what the fleet was
        # offered before, so the evidence the soak gate asks for already
        # exists. Gating it would put the gate in the way of the recovery it
        # exists to make possible (REL-1, 2026-08-28).
        return None
    if kind != "companion" or force:
        if force and str(confirm or "").strip() != str(version).strip():
            return 409, (
                f"to override the soak gate, type the version number "
                f"({version}) into the confirmation box. Nothing changed."
            )
        return None
    soak = db.soak_state(conn, platform, version,
                         soak_minutes_for(conn, settings), now)
    if soak["ok"]:
        return None
    if not soak["machines"]:
        detail = (
            f"no machine has reported {version} yet, so nothing has run it. "
            f"Push it to one machine first, leave it for "
            f"{soak['soak_minutes']} min, then make it current."
        )
    elif soak["reverted"]:
        detail = (
            f"{soak['reverted']} of the {soak['machines']} machine(s) on {version} "
            f"had to be rolled back off it by the crash-loop guard."
        )
    elif soak["crashes"]:
        detail = (
            f"{soak['machines']} machine(s) on {version} have reported "
            f"{soak['crashes']} crash(es)."
        )
    elif not any(d["crash_count"] == 0 for d in soak["detail"]):
        # "We could not tell" is not "fine" (resilience sweep 2026-08-28): a
        # companion that never sent a crash section has told us nothing about
        # whether this build stays up, and a soak is a claim that something
        # was observed.
        detail = (
            f"no machine on {version} has reported its crash counter, so "
            f"nothing here says the build stays up."
        )
    else:
        detail = (
            f"{soak['machines']} machine(s) have been on {version} for "
            f"{soak['minutes']} min; the soak is {soak['soak_minutes']} min."
        )
    return 409, (
        f"{version} has not soaked yet: {detail} Make it current anyway by "
        f"confirming the override."
    )


@router.post("/admin/packages/{platform}/{version}/current")
def api_set_current_package(
    platform: str, version: str, request: Request,
    kind: str = "companion",
    force: int = 0,
    confirm: str = "",
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Set (or roll back) which version the fleet is offered (kind=companion)
    or which installer the download serves (kind=onboard).

    Gated since 2026-08-28 (REL-1): a companion build reaches the whole fleet
    only after one machine has actually run it for the soak window, or after
    an admin overrides that in front of a typed confirmation. `force=1`
    without `confirm=<version>` is refused, so a script cannot pass the gate
    by accident."""
    admin = _require_admin(request)
    settings = request.app.state.settings
    platform = platform.strip().lower()
    kind = kind.strip().lower()
    refusal = make_current_refusal(
        conn, settings, kind=kind, platform=platform, version=version,
        force=bool(force), confirm=confirm)
    if refusal is not None:
        raise HTTPException(status_code=refusal[0], detail=refusal[1])
    if not db.set_current_package(conn, platform, version, kind):
        raise HTTPException(status_code=404, detail=f"no published {platform} {kind} package {version}")
    db.audit(conn, admin, "package.make_current", version,
             {"kind": kind, "platform": platform, "version": version,
              "forced": bool(force)})
    conn.commit()
    return {"ok": True, "view": build_packages_view(conn, request.app.state.settings)}


def roll_fleet_back(
    conn: sqlite3.Connection, *, platform: str, from_version: str,
    to_version: str, admin: str, now: str | None = None,
) -> dict[str, Any]:
    """Ask every machine running `from_version` to take `to_version` on its
    next report (REL-3, resilience sweep 2026-08-28).

    The recall's other half. Un-currenting a recalled build stops it reaching
    anyone NEW; the machines that already took it are the ones the recall is
    about, and this is the only channel that reaches them without an editor
    clicking anything. Nothing here installs: each companion applies the
    signed offer it is already holding, and the per-machine push channel
    already bypasses "newer only", which is what makes a rollback possible at
    all.

    Raises HTTPException on a target this dashboard cannot serve -- a rollback
    to a build that is not published here, or to one that has itself been
    recalled, is how a recall turns into a fleet with no working companion.
    """
    now = now or db.utcnow_iso()
    target = db.get_package(conn, platform, to_version, "companion")
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"no published {platform} companion package {to_version} to roll back to")
    if _row_str(target, "retracted_at"):
        raise HTTPException(
            status_code=409,
            detail=f"{to_version} was recalled too -- pick a build that was not")
    machines = db.machines_running_version(conn, platform, from_version)
    asked: list[str] = []
    for m in machines:
        if db.request_machine_update(conn, m["editor_username"], m["machine"],
                                     to_version, admin, now):
            asked.append(f"{m['editor_username']}/{m['machine']}")
    db.audit(conn, admin, "package.roll_fleet_back", to_version,
             {"platform": platform, "from_version": from_version,
              "to_version": to_version, "machines": asked}, now=now)
    conn.commit()
    log.warning("%s rolled %d machine(s) back from %s to %s on %s",
                admin, len(asked), from_version, to_version, platform)
    return {"ok": True, "platform": platform, "from_version": from_version,
            "to_version": to_version, "machines": asked}


@router.post("/admin/packages/{platform}/{version}/roll-fleet-back")
def api_roll_fleet_back(
    platform: str, version: str, request: Request,
    to: str = "",
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """`version` is the build to get OFF, `?to=` the one to land on (default:
    whatever is current for that platform)."""
    admin = _require_admin(request)
    platform = platform.strip().lower()
    target = to.strip()
    if not target:
        current = db.get_current_package(conn, platform, kind="companion")
        if current is None:
            raise HTTPException(
                status_code=409,
                detail="no current companion package is published for that platform, "
                       "so there is nothing to roll back to")
        target = current["version"]
    return roll_fleet_back(conn, platform=platform, from_version=version,
                           to_version=target, admin=admin)


@router.delete("/admin/packages/{platform}/{version}")
def api_delete_package(
    platform: str, version: str, request: Request,
    kind: str = "companion",
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    admin = _require_admin(request)
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
    # UX-9: bytes first, row second. A move that fails keeps the row, and says
    # so, rather than leaving a record-less file nobody can find again.
    trashed_to, error = _trash_package_file(settings, row)
    if error:
        raise HTTPException(status_code=500, detail=error)
    db.delete_companion_package(conn, platform, version, kind)
    db.audit(conn, admin, "package.delete", version,
             {"kind": kind, "platform": platform, "version": version,
              "trashed_to": trashed_to})
    conn.commit()
    return {"ok": True, "trashed_to": trashed_to, "view": build_packages_view(conn, settings)}


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
    # SYS-1 (resilience sweep 2026-08-28): the liveness contract. A state may
    # not be green or amber without a monotonic progress token and the time it
    # last changed. `progress_token` changes whenever REAL WORK happened
    # (bytes/files/current project), so a genuinely slow 40 GB file over a
    # thin uplink is not mistaken for a hang; absent when the lane is idle, or
    # when the build is too old to say (which reads as "no verdict", never as
    # "fine"). The time this dashboard judges a stall on is NOT sent by the
    # companion -- see db.upsert_lane_report's progress_token_since.
    progress_token: str | None = Field(default=None, max_length=256)
    state_since: str | None = Field(default=None, max_length=64)
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


# SYS-18a (wave 5 of the resilience sweep, 2026-08-29). How recently the OLD
# row must have reported for "this machine_id at a new hostname" to be two
# live computers off one disk image rather than one computer that was
# renamed. Not a new constant: it is the dashboard's own line for "a report
# this old is no longer current" (health.STALE_REPORT_SECONDS, ten report
# cycles at the companion's 30 s cadence).
#
# Deliberately generous in the CLONE direction, because the two mistakes do
# not cost the same: a refused adoption is reversible on the next report,
# while a wrong one DELETES the other computer's plan, every 30 s, for ever.
# That is affordable only because the verdict is REVISITED. A renamed
# Windows box reboots and is back inside one to three minutes, i.e. inside
# any window wide enough to catch a clone, so this window does not have to
# separate those two on its own: it only decides whether to act YET. The
# rename is confirmed later, by the old hostname staying quiet for this
# long, which a clone reporting every 30 s can never do.
CLONE_ADOPTION_WINDOW_SECONDS = health.STALE_REPORT_SECONDS


def _previous_row_is_live(previous: dict[str, Any], now: str) -> bool:
    """Did the row this machine_id used to live on report inside the window.

    Measured on `last_seen`, which upsert_machine fills from the SERVER's
    `received_at` and never from the companion's own clock (SYS-4): a machine
    whose clock is set to 2098 must not be able to declare itself fresh and
    make every rename look like a clone, nor set itself to 1999 and have a
    live clone read as quiet. An unreadable timestamp is NOT live -- "cannot
    tell" is not evidence of two running computers, and the adoption path is
    the one that keeps a renamed machine syncing."""
    try:
        age = db.age_seconds(str(previous.get("last_seen") or ""), now)
    except (TypeError, ValueError):
        return False
    return 0 <= age <= CLONE_ADOPTION_WINDOW_SECONDS


def _note_identity_clone(
    conn: sqlite3.Connection, editor: str, machine: str, other: dict[str, Any],
    machine_id: str, now: str,
) -> None:
    """Hand a person the clone (SYS-18a). Raised HERE, at the moment the
    adoption is refused, rather than left to the next collector cycle: this
    is the one place that knows both computers were live at the same instant.

    A rename too recent to tell from a clone raises it too, and the body says
    so, because the alternative is staying silent for five minutes about a
    real clone. The deferred adoption clears it a report or two later, so a
    renamed computer leaves no finding behind.

    Kind `duplicate_machine_id` on purpose, not a kind of its own. That check
    already exists, already has a writer that reopens and clears it every
    cycle (notices._check_identity_collisions), and now that the refusal
    leaves BOTH rows in `machines` it fires on this shape by itself -- which
    is exactly what its own fix text was written for. A second kind would
    have meant a second row on the checks panel that nothing but this branch
    ever evaluates."""
    other_name = str(other.get("machine") or "?")
    try:
        age = db.age_seconds(str(other.get("last_seen") or ""), now)
    except (TypeError, ValueError):
        age = 0.0
    heard = ("less than a minute ago" if age < 60
             else f"{int(age // 60)} minute(s) ago")
    # Never able to fail the report. A notice is the diagnosis of a problem;
    # taking /api/v1/report down to deliver it would be a worse one, and the
    # collector's own pass writes this same kind on the next cycle anyway.
    try:
        db.notice(
            conn, "duplicate_machine_id", "error", machine_id,
            body=(f"Two computers are reporting the same identity: "
                  f"{editor}/{machine} and {editor}/{other_name}. {other_name} "
                  f"was last heard from {heard}, so both are switched on and "
                  f"running. This happens when one computer's disk was copied "
                  f"onto another one. Until it is sorted out, neither computer's "
                  f"list of projects to sync is safe: the server cannot tell "
                  f"which of the two a plan, an update or a halt belongs to. If "
                  f"one of these two names is simply the new name of the other, "
                  f"because that computer was renamed, this clears itself a few "
                  f"minutes after the old name stops reporting and the projects "
                  f"move across on their own."),
            fix=("On the NEWER computer, quit CC Sync, delete the file "
                 ".ccsync/machine.json in that user's home folder, and start CC "
                 "Sync again. It mints a fresh identity on the next start and can "
                 "then be given its own projects. Nothing to do if this was a "
                 "rename rather than a copy: wait five minutes and it sorts "
                 "itself out. If it is still here after that and one of the two "
                 "computers no longer exists, remove that one with [ FORGET ] on "
                 "the FLEET page."),
            now=now)
    except sqlite3.Error:
        log.warning("could not record the duplicate_machine_id notice for %s",
                    machine_id, exc_info=True)


def _register_machine(
    conn: sqlite3.Connection, editor: str, machine: str, payload: "ReportIn", now: str
) -> None:
    """Keep the machine registry (v23) current from this report, adopting a
    renamed computer rather than treating it as a new one (WP1).

    The rename branch is the whole reason `machine_id` exists: a hostname is
    a label an editor can change, and the plan is keyed on it. It only fires
    when the minted id matches a machine of the SAME editor -- an id from
    somebody else's report names nothing here, so it can move nothing.

    FRESHNESS DECIDES (SYS-18a, 2026-08-29). A rename is one computer with
    two names over TIME; a cloned disk is two computers with one identity at
    the SAME time. Until this date the first reading was the only one, so an
    imaged PC and its original ping-ponged a single registry row between
    their hostnames every 30 s, each swap deleting the other's `selections`
    and carrying the survivor's plan onto whichever reported last -- and
    because there was only ever one row, neither `duplicate_machine_id` nor
    invariant 3 could see it. Now: if the old row reported inside
    CLONE_ADOPTION_WINDOW_SECONDS, both are live, so we UNDER-act. Nothing
    is deleted, nothing moves, both rows survive so the collision is visible
    to the two checks written for it, and a person is told.

    THE VERDICT IS REVISITED, NOT MADE ONCE. No window separates "rebooting
    after a rename" from "the twin was briefly quiet": a renamed Windows box
    is back one to three minutes later, inside any window wide enough to
    catch a clone. So the FIRST report after a rename is refused by design,
    and the rename is confirmed by what happens NEXT -- a clone's twin keeps
    reporting every 30 s, while a renamed computer's old hostname is never
    heard from again. Once that row has been quiet for the window, a later
    report from the new name adopts (db.adopt_renamed_machine,
    same_computer=True) and clears the notice, and nobody has had to do
    anything. That is why this looks at EVERY row carrying the id rather
    than only the most recent: after a refusal the most recent holder is the
    reporting machine itself, and a rule that only ever looked there could
    never change its mind. The one case that stays refused is a new name
    that has acquired a PLAN of its own in the meantime, which is an admin
    decision and not ours to overwrite."""
    machine_id = (payload.machine_id or "").strip() or None
    device_id = (payload.syncthing_device_id or "").strip() or None
    if machine_id:
        # Every OTHER hostname holding this id, freshest first. A first-sight
        # rename leaves one quiet row here; a clone one live row; a rename
        # whose first report was refused leaves one row that has since gone
        # quiet, which is the deferred case (SYS-18a).
        others = [r for r in db.machines_by_machine_id(conn, editor, machine_id)
                  if r["machine"] != machine]
        live = [r for r in others if _previous_row_is_live(r, now)]
        if live:
            # A CLONE, or a rename too recent to tell apart from one. Refusing
            # is the whole fix: this report is still recorded under its own
            # name below, so both rows exist from here on, and the next report
            # asks again.
            previous = live[0]
            log.warning(
                "%s: machine %r reports the machine_id of %r, which reported "
                "within the last %d minute(s) -- two live computers on one "
                "identity (a copied disk), NOT a rename. Refusing the "
                "adoption: no plan is moved and no row is deleted (SYS-18a).",
                editor, machine, previous["machine"],
                int(CLONE_ADOPTION_WINDOW_SECONDS // 60),
            )
            _note_identity_clone(conn, editor, machine, previous, machine_id, now)
        elif others:
            previous = others[0]
            if db.adopt_renamed_machine(conn, editor, previous["machine"], machine,
                                        same_computer=True):
                log.info(
                    "%s: machine %r is the computer previously known as %r (same "
                    "machine_id, and that name has now been quiet for over %d "
                    "minute(s)) -- moving its sync plan across rather than "
                    "starting it empty",
                    editor, machine, previous["machine"],
                    int(CLONE_ADOPTION_WINDOW_SECONDS // 60),
                )
                # The rename is settled, so the clone finding that a refused
                # first report may have raised is no longer true. Cleared here
                # rather than left to the collector, so a rename never leaves a
                # permanent problem on the home page (SYS-18a).
                try:
                    db.clear_notice(conn, "duplicate_machine_id", machine_id, now=now)
                except sqlite3.Error:
                    log.warning("could not clear the duplicate_machine_id notice "
                                "for %s", machine_id, exc_info=True)
            else:
                # The name is TAKEN by another of this editor's computers, or
                # has been given a plan of its own since the refusal. Nothing
                # moves and nothing is deleted: both plans stay where they are,
                # this report is recorded under the name it used, and the stale
                # row keeps its plan until an admin copies or clears it
                # (ultrareview 2026-08-19, db.adopt_renamed_machine).
                log.warning(
                    "%s: machine %r reports the machine_id of %r, but %r already "
                    "has a sync plan of its own -- NOT moving the plan (a hostname "
                    "collision is an admin decision, not a silent overwrite). "
                    "Both plans are untouched.",
                    editor, machine, previous["machine"], machine,
                )
    db.upsert_machine(
        conn, editor, machine, now,
        machine_id=machine_id,
        platform=(payload.platform or "").strip().lower() or None,
        syncthing_device_id=device_id,
    )
    if device_id:
        # ONE device is ONE computer (data-model-5, 2026-08-21). A refused
        # rename adoption leaves the old row holding this device id along
        # with its plan, and then the enforce cycle hands the live machine
        # the UNION of both rows' plans while GET /selection returns only its
        # own -- Syncthing offers folders the companion never configures.
        # This report is the fresher evidence, so the id moves here.
        for lost in db.release_device_id_elsewhere(conn, editor, machine, device_id):
            log.warning(
                "%s/%s reports Syncthing device %s, which was still recorded on %s "
                "-- taking it off that row (one device is one computer). Its sync "
                "plan is untouched.", editor, machine, device_id, lost)


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


def _bound_to_field_caps(cls, data):
    """Apply a model's own max_length/ge/le to the RAW dict, truncating.

    `max_length` on a plain Field RAISES, and a raising validator fires
    before the route body -- one 300-character VRAM refusal would have taken
    the whole machine off the fleet grid (B6's lesson). So the caps are
    applied here instead: strings truncated, sequences sliced, numbers
    clamped. Shared by _BoundedSectionIn and _ReportSectionIn (they differ
    only in model_config).
    """
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


class _BoundedSectionIn(BaseModel):
    """A report sub-section that TRUNCATES rather than rejects.

    `sync_guard` is not one of ReportIn's tolerant sections (a bad one there
    still 422s the whole report), and it is where the alarms live -- so a
    supervisor `last_error` carrying a 4 KB traceback must not be able to
    take the machine off the fleet grid it is trying to raise an alarm on
    (SYS-3, resilience sweep 2026-08-28).
    """
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _bound_rather_than_reject(cls, data):
        return _bound_to_field_caps(cls, data)


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


# ---- the sync_guard sections this dashboard used to drop ----------------
#
# SYS-3 / SYNC-8 (resilience sweep 2026-08-28). Every model below describes
# something the companion has been computing and sending for weeks that
# `extra="ignore"` threw away at the model boundary with no log line. The
# companion's own source said so out loud about the first one: "THE DASHBOARD
# DOES NOT READ THIS YET ... extra='ignore' drops it (BROLL-ING-1 is what
# that costs when nobody says so out loud)."


class SyncthingSupervisorIn(_BoundedSectionIn):
    """companion sync/syncthing_supervisor.SyncthingSupervisor.report().

    EMPTY WHILE HEALTHY by that method's design: an absent section is how
    "the sync engine is up" is spelled, and a zeroed one would need a second
    field to say the same thing. What this carries that lane C's own state
    cannot is DURATION and ATTEMPTS -- the difference between "he rebooted"
    and "that machine has needed a human since Tuesday" (SYNC-8)."""
    down_since: str | None = Field(default=None, max_length=64)
    attempts: int | None = Field(default=None, ge=0)
    last_error: str | None = Field(default=None, max_length=1000)
    last_attempt: str | None = Field(default=None, max_length=64)
    # Tri-state. False means the engine is down AND automatic restarts are off
    # or suppressed on that machine, i.e. nothing is trying; None means this
    # companion is too old to say, which is not the same answer.
    supervising: bool | None = None


class ReporterHealthIn(_BoundedSectionIn):
    """The companion's own view of whether its reports are landing (APP-1).

    Only ever seen on a report that DID land, so it is a RECOVERY record: a
    streak that has just ended, and the last status the streak had. A machine
    still inside a streak is simply absent from the grid, which is the half
    of APP-1 that only silence can tell you about."""
    last_success_at: str | None = Field(default=None, max_length=64)
    # An HTTP code or an exception class name -- "401" (a credential a human
    # must replace) reads nothing like "TimeoutError" (a NAS rebooting).
    last_status: str | None = Field(default=None, max_length=64)
    consecutive_failures: int | None = Field(default=None, ge=0)


class CrashesIn(_BoundedSectionIn):
    """~/.ccsync/crashes -- the tracebacks threading.excepthook wrote (APP-6).

    A count, not the files: the point is that an admin can see a machine
    where a background task died, on a grid, without asking for a
    diagnostics bundle. Non-zero here with three green lanes is the exact
    shape crash_report.py's own docstring names as the failure to fix."""
    count: int | None = Field(default=None, ge=0)
    newest: str | None = Field(default=None, max_length=256)


class UpgradeIn(_BoundedSectionIn):
    """`sync_guard.upgrade` -- what happened the last time this machine tried
    to take a build (REL-8 / APP-5, resilience sweep 2026-08-28).

    The report payload carried nothing at all about upgrade outcomes, so a
    machine whose AV quarantines every downloaded exe (or whose captive-portal
    proxy mangles it, so the sha never matches) was indistinguishable from one
    that had simply not seen the push yet: the admin's [ UPDATE NOW ] showed
    "pending" for ever while the machine downloaded 20 MB every ten minutes.

    `reverted_from` is the crash-loop guard's answer: the build that would not
    run and was rolled back to `<exe>.old`. The companion clears it after ONE
    accepted report, so this dashboard keeps it (db.store_upgrade_state) --
    the grid drops the chip by itself once the machine is running a build at
    or above the one it fell back from."""
    version: str | None = Field(default=None, max_length=64)
    attempts: int | None = Field(default=None, ge=0)
    last_error: str | None = Field(default=None, max_length=500)
    last_attempt_at: str | None = Field(default=None, max_length=64)
    reverted_from: str | None = Field(default=None, max_length=64)
    starts_this_version: int | None = Field(default=None, ge=0)


class SyncConflictsIn(_BoundedSectionIn):
    """Syncthing's `.sync-conflict-*` files in this machine's tree.

    Two editors saving one project file is a normal Syncthing outcome and a
    silent one: the loser's work is renamed, not lost, and nothing tells
    anybody. `paths` is a sample for the tooltip, never the whole set."""
    count: int | None = Field(default=None, ge=0)
    paths: list[str] | None = Field(default=None, max_length=32)


class DiskIn(_BoundedSectionIn):
    """One shutil.disk_usage per heavy tick (SYS-5 / UX-1, resilience sweep
    2026-08-28).

    Free space was invisible to the sync path AND absent from the report, so
    an editor's full drive showed up as red dots with no cause on any page,
    and a tick of 4 TB of proxies onto a 500 GB MacBook succeeded silently.
    `system_free_bytes` is the OS drive when it is a different volume, which
    is what stops a full boot disk (Resolve caches, the crash directory) from
    being invisible on a machine whose sync drive is fine."""
    root_free_bytes: int | None = Field(default=None, ge=0)
    root_total_bytes: int | None = Field(default=None, ge=0)
    system_free_bytes: int | None = Field(default=None, ge=0)
    at: str | None = Field(default=None, max_length=64)


class StalledIn(_BoundedSectionIn):
    """The last stall the COMPANION detected and killed (SYNC-1 / SYS-17).

    The server-side detector (health.lane_stall) and this are two halves of
    one finding on purpose: the dashboard is the healthy independent observer,
    and this is the machine that has the evidence -- `killed` is the
    difference between "rclone made no progress and we shot it" and "it is
    still sitting there". Absent when no stall has ever been recorded."""
    lane: str | None = Field(default=None, max_length=32)
    seconds: int | None = Field(default=None, ge=0)
    killed: bool | None = None
    at: str | None = Field(default=None, max_length=64)


class RestartRecordIn(_BoundedSectionIn):
    """One supervised thread's restart record (SYS-2)."""
    count_24h: int | None = Field(default=None, ge=0)
    last_at: str | None = Field(default=None, max_length=64)
    last_error: str | None = Field(default=None, max_length=1000)


class RestartsIn(_BoundedSectionIn):
    """The LaneWatchdog's record: a machine that needs restarting three times
    an hour is visible rather than merely self-healing (SYS-2).

    DECLARED HERE, STORED ELSEWHERE: the columns and the chip belong to the
    v33 why-not-syncing step of this same sweep. Declaring it now is what
    keeps it out of the ignored-sections banner and off the third repeat of
    SYS-3, which is the whole point of declaring a field early."""
    sequencer: RestartRecordIn | None = None
    watcher: RestartRecordIn | None = None
    media_tree: RestartRecordIn | None = None


class BlockedIn(_BoundedSectionIn):
    """The companion's OWN ranked answer to "why is nothing moving" (SYNC-15).

    Each latch had its own state, its own file and its own (or no) report
    field, so the fleet page had to INFER "why is this machine doing nothing"
    from a lane state -- which SYNC-1/5/9 all show can be wrong. This is the
    aggregate, ranked so the ACTIONABLE reason wins, and
    health.why_not_syncing prefers it over anything this server derives: the
    root guard's fourth answer, the licence park and the machine's own
    transport reach no column here.

    Absent when nothing blocks. `reason` is deliberately NOT an enum: a newer
    companion knowing a reason this build does not must not 422 its report,
    and why_not_syncing names an unknown code rather than swallowing it."""
    reason: str | None = Field(default=None, max_length=64)
    detail: str | None = Field(default=None, max_length=1000)
    since: str | None = Field(default=None, max_length=64)


class DiskFloorIn(_BoundedSectionIn):
    """lane_guard.DiskFloorLatch.report() -- WHY lane B stood down (SYNC-7).

    The latch, not the measurement: the figures ride `sync_guard.disk`. A
    parked lane B reads as a quiet, green, idle one on every other signal the
    grid has, which is the same hole the breaker's own chip was cut for.

    Declared here so it is not counted as an ignored section; the columns and
    the "why is this machine not syncing" sentence belong to the v33 step of
    this sweep."""
    parked: bool | None = None
    reason: str | None = Field(default=None, max_length=500)
    at: str | None = Field(default=None, max_length=64)
    free_bytes: int | None = Field(default=None, ge=0)
    floor_bytes: int | None = Field(default=None, ge=0)


class ResolveHealthIn(_BoundedSectionIn):
    """The companion's Resolve media scan (wave 4's ingest contract, 2026-08-28).

    Clips the OPEN project references from outside the sync tree are footage
    lane A will never upload and no other editor will ever see: the timeline
    opens with red media everywhere else and the machine reports a perfectly
    green sync, because as far as every lane is concerned there is nothing to
    move. Declared here BEFORE the companion half ships, which is SYS-3's
    lesson: the loss is invisible in the direction where the sender is newer
    than the reader.
    """
    out_of_tree: int | None = Field(default=None, ge=0)
    bad_prefix: int | None = Field(default=None, ge=0)
    missing: int | None = Field(default=None, ge=0)
    ignored_this_session: int | None = Field(default=None, ge=0)
    ignored_folders: int | None = Field(default=None, ge=0)
    last_scan_at: str | None = Field(default=None, max_length=64)
    open_project: str | None = Field(default=None, max_length=400)


class StrayProjectsIn(_BoundedSectionIn):
    """Project directories on the editor's disk that are not in the tree.

    A COUNT plus a size plus a bounded sample: what the grid needs is "this
    machine has 3 project folders nobody else can see", not the list in a
    column.
    """
    count: int | None = Field(default=None, ge=0)
    bytes: int | None = Field(default=None, ge=0)
    paths: list[str] | None = Field(default=None, max_length=20)


class MovedProjectDirIn(_BoundedSectionIn):
    """One project directory that is not where the tree says it should be."""
    slug: str | None = Field(default=None, max_length=200)
    expected: str | None = Field(default=None, max_length=1000)
    found: str | None = Field(default=None, max_length=1000)


class IngestStagingIn(_BoundedSectionIn):
    """Footage dropped but not yet filed into a project. It is on ONE
    computer, so it is one disk failure from gone."""
    bytes: int | None = Field(default=None, ge=0)
    batches: int | None = Field(default=None, ge=0)
    oldest_at: str | None = Field(default=None, max_length=64)


class SyncGuardIn(BaseModel):
    """The companion's `sync_guard` section (item 9, 2026-08-17).

    Every field optional, sub-models tolerant of extras, exactly like
    TransportHealthIn: a companion that grows a counter must never 422 its
    whole report against an older dashboard. And the converse matters more
    here -- an OLDER companion sends none of this, which reads as "no alarm",
    which is right: it has no breaker to trip.
    """
    # extra='allow', not 'ignore' (SYS-3): an undeclared sub-key here is what
    # lost syncthing_supervisor for weeks. Accepting it is what lets
    # api_report NAME it in a log line and on the fleet page instead of a
    # human finding it in a code read months later.
    model_config = ConfigDict(extra="allow")

    lane_b_breaker: BreakerIn | None = None
    trash: TrashIn | None = None
    halt: HaltIn | None = None
    skipped_exists: SkippedExistsIn | None = None
    removal_overrides: list[RemovalOverrideIn] | None = Field(default=None, max_length=8)
    # Sent since companion 0.9.x and dropped until v30 (SYNC-8).
    syncthing_supervisor: SyncthingSupervisorIn | None = None
    reporter: ReporterHealthIn | None = None
    crashes: CrashesIn | None = None
    # The companion's OWN measurement of its clock against the server's
    # (APP-13). Declared so it is not reported as an ignored section; the
    # value the grid chips is the one THIS server computes from `reported_at`
    # against its own clock (db.clamp_reported_at), because that one needs no
    # companion release and cannot be wrong about which clock it trusts.
    clock_skew_seconds: float | None = None
    # Syncthing folders on that machine with no .stignore filter written yet:
    # every one of them is a folder that will carry video both ways.
    folders_unfiltered: list[str] | None = Field(default=None, max_length=64)
    sync_conflicts: SyncConflictsIn | None = None
    # v32 (SYS-5 / SYS-1 / SYNC-1, resilience sweep 2026-08-28).
    disk: DiskIn | None = None
    stalled: StalledIn | None = None
    # Stored by the v33 step, declared here (see RestartsIn).
    restarts: RestartsIn | None = None
    # v33 (SYS-7 / SYNC-15): the one sentence's preferred input.
    blocked: BlockedIn | None = None
    # This machine's project_rotation_seconds. Sent because the stall budget
    # is 3 ROTATIONS: a rig on a 1 h rotation is not stalled at 35 minutes,
    # and a server that guessed would either cry wolf or wait all afternoon.
    # Absent leaves health.lane_stall on its 30 min floor.
    rotation_seconds: float | None = Field(default=None, ge=0)
    disk_floor: DiskFloorIn | None = None
    # v35 (REL-8 / APP-5): the outcome of the last update attempt.
    upgrade: UpgradeIn | None = None
    # RootGuard's answer as a plain string, including its SYNC-2 fourth one:
    # `present` / `absent` / `misplaced` / `not_answering` / `unknown`.
    # `unknown` is "we could not tell" and must never be rendered as
    # `present`. Stored by the v33 step, declared here.
    root_state: str | None = Field(default=None, max_length=32)
    # v38 (wave 4's ingest contract, resilience sweep 2026-08-28): the four
    # sections that answer "is this editor's footage anywhere but their own
    # disk", none of which any lane state can see.
    resolve_health: ResolveHealthIn | None = None
    stray_projects: StrayProjectsIn | None = None
    moved_project_dirs: list[MovedProjectDirIn] | None = Field(
        default=None, max_length=20)
    ingest_staging: IngestStagingIn | None = None

    @model_validator(mode="before")
    @classmethod
    def _bound_rather_than_reject(cls, data):
        """The caps on THIS model truncate too (SYS-3).

        sync_guard is not one of ReportIn's tolerant sections, so a 65th
        unfiltered folder or a 9th removal override would have 422'd the whole
        report -- taking the lanes, the transfers and the presence data with
        it, and silencing the very alarms this section exists to carry (B6's
        lesson, applied to the alarm channel)."""
        return _bound_to_field_caps(cls, data)


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
    sup = guard.syncthing_supervisor
    crashes = guard.crashes
    conflicts = guard.sync_conflicts
    folders = guard.folders_unfiltered
    disk = guard.disk
    stalled = guard.stalled
    blocked = guard.blocked
    restarts = guard.restarts
    upgrade = guard.upgrade
    rh = guard.resolve_health
    stray = guard.stray_projects
    staging = guard.ingest_staging
    restart_records = [] if restarts is None else [
        r for r in (restarts.sequencer, restarts.watcher, restarts.media_tree)
        if r is not None
    ]
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
        # v30 (SYS-3 / SYNC-8 / APP-6, resilience sweep 2026-08-28). Every one
        # of these is None when the section was absent, and the upsert writes
        # them from any guard-bearing report -- an absent supervisor section
        # is how the companion spells "the sync engine is up", so None has to
        # be able to CLEAR yesterday's incident rather than preserve it.
        "supervisor_down_since": sup.down_since if sup is not None else None,
        "supervisor_attempts": sup.attempts if sup is not None else None,
        "supervisor_last_error": sup.last_error if sup is not None else None,
        "supervisor_supervising": (
            None if sup is None or sup.supervising is None
            else int(bool(sup.supervising))
        ),
        "crash_count": crashes.count if crashes is not None else None,
        "crash_newest": crashes.newest if crashes is not None else None,
        # A COUNT plus a sample of names: the grid needs "this machine has
        # unfiltered folders" and a tooltip, not the list in a column.
        "folders_unfiltered": None if folders is None else len(folders),
        "folders_unfiltered_names": (
            ", ".join(folders[:10]) if folders else None
        ),
        "sync_conflicts": conflicts.count if conflicts is not None else None,
        # v32 (SYS-5 / UX-1). `disk_at` is this section's own marker in the
        # upsert, not guard_at: the measurement rides HEAVY ticks only, and a
        # light report in between must not blank the last known free space.
        "disk_root_free_bytes": disk.root_free_bytes if disk is not None else None,
        "disk_root_total_bytes": disk.root_total_bytes if disk is not None else None,
        "disk_system_free_bytes": (
            disk.system_free_bytes if disk is not None else None),
        "disk_at": (disk.at or now) if disk is not None else None,
        "rotation_seconds": guard.rotation_seconds,
        # v32 (SYNC-1 / SYS-17): the companion's own kill record, which
        # follows the LATCH rule so a recovered machine clears its chip.
        "stalled_lane": stalled.lane if stalled is not None else None,
        "stalled_seconds": stalled.seconds if stalled is not None else None,
        "stalled_killed": (
            None if stalled is None or stalled.killed is None
            else int(bool(stalled.killed))
        ),
        "stalled_at": stalled.at if stalled is not None else None,
        # v33 (SYS-7 / SYNC-15 / SYS-2). db.store_blocked_state writes these,
        # not the upsert's INSERT, and it writes them from ANY guard-bearing
        # report: an absent `blocked` is how the companion spells "nothing is
        # blocking me now", so None has to be able to clear this morning's
        # sentence rather than preserve it for ever.
        #
        # The restart record is FLATTENED ACROSS THE THREE THREADS on purpose:
        # what an admin needs on the grid is "this machine's background work
        # has been restarted N times in a day", and which of the three it was
        # is in the diagnostics bundle beside it.
        "blocked_reason": blocked.reason if blocked is not None else None,
        "blocked_detail": blocked.detail if blocked is not None else None,
        "blocked_since": blocked.since if blocked is not None else None,
        "restarts_count_24h": (
            None if not restart_records else
            sum(int(r.count_24h or 0) for r in restart_records)
        ),
        "restarts_last_at": (
            max((r.last_at for r in restart_records if r.last_at), default=None)
        ),
        "restarts_last_error": next(
            (r.last_error for r in restart_records if r.last_error), None),
        # v35 (REL-8). db.store_upgrade_state writes these, not the upsert's
        # INSERT -- same reasoning as blocked_*, and this group has a rule of
        # its own for `reverted_from` (sent once, kept here).
        "upgrade_version": upgrade.version if upgrade is not None else None,
        "upgrade_attempts": upgrade.attempts if upgrade is not None else None,
        "upgrade_last_error": upgrade.last_error if upgrade is not None else None,
        "upgrade_last_attempt_at": (
            upgrade.last_attempt_at if upgrade is not None else None),
        "upgrade_reverted_from": (
            upgrade.reverted_from if upgrade is not None else None),
        # v38 (wave 4's ingest contract). db.store_resolve_health writes these,
        # not the upsert's INSERT -- same shape and the same reasoning as
        # blocked_* and upgrade_*, and the same LATCH rule: an absent
        # sub-section is how the companion spells "there is nothing outside
        # the tree any more", which a COALESCE could never express.
        "resolve_out_of_tree": rh.out_of_tree if rh is not None else None,
        "resolve_bad_prefix": rh.bad_prefix if rh is not None else None,
        "resolve_missing": rh.missing if rh is not None else None,
        # The two "ignored" counters are SUMMED into one column: what the grid
        # needs is "this editor has dismissed N of these", and which half was
        # a folder is in the diagnostics bundle beside it.
        "resolve_ignored": (
            None if rh is None
            or (rh.ignored_this_session is None and rh.ignored_folders is None)
            else int(rh.ignored_this_session or 0) + int(rh.ignored_folders or 0)),
        "resolve_last_scan_at": rh.last_scan_at if rh is not None else None,
        "stray_projects_count": stray.count if stray is not None else None,
        "stray_projects_bytes": stray.bytes if stray is not None else None,
        # A LIST is flattened to its length: an absent list is "nothing moved",
        # an empty one is the same answer, and both must be able to clear
        # yesterday's chip.
        "moved_project_dirs_count": (
            None if guard.moved_project_dirs is None
            else len(guard.moved_project_dirs)),
        "ingest_staging_bytes": staging.bytes if staging is not None else None,
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


class _ReportSectionIn(_BoundedSectionIn):
    """Base for those sections: extras ignored, everything else BOUNDED by
    _bound_to_field_caps (inherited).
    """

    # protected_namespaces: `model_download_percent` is a field name from the
    # companion's payload, not a pydantic attribute; without this, importing
    # this module warns about every `model_*` field.
    model_config = ConfigDict(extra="ignore", protected_namespaces=())


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


class ResolveJournalIn(BaseModel):
    """One undo journal a machine holds (v40, SYS-15b).

    A companion cannot be ASKED what it holds -- there is no inbound
    connection to an editor's PC -- so it says so on the report channel and
    the dashboard remembers, which is what lets an admin name one. It is a
    LIST OF NAMES, never the journal itself: the entries name that editor's
    local paths, and nothing here needs them.
    """
    model_config = ConfigDict(extra="ignore")
    # "<project slug>/<file name>", the companion's own addressing.
    id: str = Field(max_length=256)
    project: str = Field(default="", max_length=256)
    started: str = Field(default="", max_length=64)
    entries: int = Field(default=0, ge=0, le=1_000_000)
    sources: str = Field(default="", max_length=128)


class ResolveUndoResultIn(BaseModel):
    """A machine's answer to `commands.resolve_undo` (v40, SYS-15b). The same
    contract FileMoveResultIn uses, including `retrying`: an undo refused
    because the wrong project is open in Resolve is going to be tried again,
    and retiring the command on it would leave the wrong paths in place with
    the admin believing they were put back."""
    model_config = ConfigDict(extra="ignore")
    id: int
    ok: bool
    detail: str | None = Field(default=None, max_length=512)
    state: Literal["done", "failed", "retrying"] | None = None
    attempts: int | None = Field(default=None, ge=0, le=1000)


class FileMoveResultIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    ok: bool
    detail: str | None = Field(default=None, max_length=512)
    # RES-1 (resilience sweep 2026-08-28). Absent from every companion below
    # 0.9.55, where a failure meant "answered, stop asking" -- so absent keeps
    # exactly that meaning. "retrying" records the attempt WITHOUT retiring
    # the command (the file is open in Resolve; it will be tried again),
    # "blocked" is the companion having run out of attempts and is a distinct
    # thing on the project page from a one-off failure.
    state: Literal["done", "failed", "retrying", "blocked"] | None = None
    attempts: int | None = Field(default=None, ge=0, le=1000)
    # RES-10: moved on disk, but no media pool has been walked yet that
    # references it, so Resolve is not repointed.
    relink_pending: bool = False


# SYS-3 (resilience sweep 2026-08-28): one WARNING per (machine, section) per
# UTC day. A 30 s report cadence means a single undeclared section would
# otherwise write 2,880 identical lines a day per machine and roll the log
# that carries everything else away. The durable record is the `meta` row
# (db.record_ignored_report_sections) -- this dict is only rate limiting, so
# losing it on a restart costs one extra log line, and it is bounded because
# `machine` is a client-chosen string on an unthrottled endpoint.
_IGNORED_SECTION_LOGGED: dict[tuple[str, str], str] = {}
_IGNORED_SECTION_LOG_CAP = 500


def _ignored_sections_to_log(machine: str, keys: list[str], day: str) -> list[str]:
    """Which of `keys` has not been logged for `machine` on `day` yet."""
    if len(_IGNORED_SECTION_LOGGED) > _IGNORED_SECTION_LOG_CAP:
        _IGNORED_SECTION_LOGGED.clear()
    fresh = []
    for key in keys:
        if _IGNORED_SECTION_LOGGED.get((machine, key)) != day:
            _IGNORED_SECTION_LOGGED[(machine, key)] = day
            fresh.append(key)
    return fresh


def undeclared_report_sections(payload: "ReportIn") -> list[str]:
    """Top-level and sync_guard keys this dashboard accepted but does not read.

    sync_guard sub-keys are prefixed so the two namespaces cannot collide in
    the record or the banner. `truncated` is excluded: the validator writes it
    onto the raw dict itself, so a client that also sent it is not telling us
    anything (and B6 already reports truncation loudly on its own).
    """
    keys = [k for k in sorted(payload.model_extra or {}) if k != "truncated"]
    guard = payload.sync_guard
    if guard is not None:
        keys += [f"sync_guard.{k}" for k in sorted(guard.model_extra or {})]
    return keys


class ReportIn(BaseModel):
    # extra='allow' (SYS-3, resilience sweep 2026-08-28). The default,
    # 'ignore', has now silently thrown away companion telemetry three times:
    # transport_health for months (B17), proxy_coverage and youtube_import
    # for a year each ("have ridden every heavy tick since their features
    # shipped and reached nobody"), and sync_guard.syncthing_supervisor
    # (SYNC-8). Each was found by a human reading the code; none by a signal.
    # Accepting the extras is what lets api_report name them in a log line
    # and on the fleet page, so the FOURTH one announces itself.
    #
    # Nothing reads model_extra except that reporting: an undeclared key is
    # still not stored, still not rendered as data, and still cannot reach a
    # table. It is bounded by the request-size limit like the rest of the body.
    model_config = ConfigDict(extra="allow")

    editor_name: str = Field(min_length=1, max_length=64)
    machine: str = Field(min_length=1, max_length=128)
    # WP1 (MULTI_MACHINE_PLAN.md): the computer's own identity, minted once
    # into ~/.ccsync/machine.json and reported thereafter. It is an
    # IDENTIFIER, not a credential -- nothing is authorised by it, exactly as
    # nothing is authorised by `machine` -- and it rides inside the same
    # authenticated report. What it buys: a hostname change stops looking
    # like a new computer with an empty plan, and a regenerated Syncthing key
    # stops looking like a stranger (the 2026-07-27 incident).
    machine_id: str | None = Field(default=None, max_length=64)
    # This machine's own Syncthing device ID (GET /rest/system/status myID).
    # The enforce cycle shares a folder with a DEVICE; without this it can
    # only resolve devices by their OWNER'S name, so both of one person's
    # computers get every project either of them is ticked for.
    syncthing_device_id: str | None = Field(default=None, max_length=128)
    companion_version: str | None = Field(default=None, max_length=64)
    platform: str | None = Field(default=None, max_length=32)  # 'windows' | 'macos'
    # REL-16 (resilience sweep 2026-08-28): an Intel Mac and an Apple-silicon
    # one both report platform `macos`, so the channel had no way to avoid
    # handing one the other's binary -- it downloads, verifies, is renamed over
    # the running companion, fails to exec, and rolls back for ever. Absent
    # from every build before this wave, which reads as "unknown": those
    # machines keep being offered what they were offered before.
    arch: str | None = Field(default=None, max_length=32)
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
    # Answers to `commands.file_moves` (docs/FILE_MOVES.md): one per move
    # this machine has now applied, or tried to. Absent from every companion
    # older than 0.9.54, which is fine -- those never receive the command's
    # effects either way (see the reply builder).
    file_moves_applied: list[FileMoveResultIn] | None = Field(default=None, max_length=64)
    # The clip-path changes this machine has recorded, so an admin can name
    # one to undo (v40, SYS-15b), and its answers to the undos already asked
    # for. Absent from every companion below this wave: absent is NOT an empty
    # list (see db.store_resolve_journals), because overwriting the stored
    # list with [] would tell an admin that a machine which has been relinking
    # for weeks has nothing to put back.
    resolve_journals: list[ResolveJournalIn] | None = Field(
        default=None, max_length=db.RESOLVE_JOURNALS_MAX)
    resolve_undo_applied: list[ResolveUndoResultIn] | None = Field(
        default=None, max_length=16)
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
    #
    # DASH-2 (resilience sweep 2026-08-28): a refusal HERE, and only here, also
    # stamps machines.report_refused_at/reason. Rotating DASH_SESSION_SECRET
    # 401s the whole fleet at once -- the identity token is an HMAC over it and
    # never expires (CR-86) -- and the fleet grid's answer used to be a page
    # that quietly stopped moving, which is exactly what a switched-off machine
    # looks like. The stamp writes those two columns on an EXISTING row and
    # nothing else: this report is unverified, so nothing from its body may
    # create or alter fleet data.
    identity = request.headers.get("x-ccsync-identity", "")
    id_user, id_retired_key = (
        auth.read_identity_token_ex(settings, identity) if identity else (None, False))

    def _refuse_identity(detail: str, reason: str) -> HTTPException:
        try:
            if db.stamp_report_refused(conn, editor, machine, reason, received_at):
                conn.commit()
        except sqlite3.Error:                                          # noqa: BLE001
            log.warning("could not stamp the refused report from %s/%s", editor, machine)
        return HTTPException(status_code=401, detail=detail)

    if settings.session_secret:
        if not identity:
            raise _refuse_identity(
                "X-CCSync-Identity required -- sign in from the companion tray "
                "(Sign in…) to get a machine identity token",
                "no machine identity token was sent")
        if id_user is None:
            raise _refuse_identity(
                "X-CCSync-Identity is invalid or expired -- sign in again from the "
                "companion tray",
                "its machine identity token cannot be verified (the dashboard's "
                "session secret has changed)")
        if id_user != editor:
            raise _refuse_identity(
                "X-CCSync-Identity does not match editor_name",
                "its machine identity token belongs to a different editor")
    elif identity and id_user is not None and id_user != editor:
        raise _refuse_identity(
            "X-CCSync-Identity does not match editor_name",
            "its machine identity token belongs to a different editor")
    verified = id_user is not None and id_user == editor
    # This machine IS reporting and IS being accepted: clear yesterday's
    # refusal, and count (or stop counting) it against the rotation drain.
    db.clear_report_refused(conn, editor, machine)
    if verified:
        db.record_retired_key_identity(conn, editor, machine, received_at,
                                       retired=bool(id_retired_key))
        if id_retired_key:
            log.warning(
                "%s/%s reported with an identity signed by a RETIRED session key "
                "(DASH_SESSION_SECRET_PREVIOUS). It is accepted; that editor has to "
                "sign in once at their tray before the old key can be removed.",
                editor, machine)
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

    # SYS-3: a section this dashboard does not read is now LOUD. The report is
    # accepted either way -- an undeclared key must never be a reason a
    # machine drops off the fleet grid -- but "the companion computed this and
    # we threw it away" has to be visible somewhere, because three times now
    # it has only been visible in the source.
    ignored_sections = undeclared_report_sections(payload)
    if ignored_sections:
        for key in _ignored_sections_to_log(
                f"{editor}/{machine}", ignored_sections, received_at[:10]):
            log.warning(
                "report from %s/%s carries section %r that this dashboard does not "
                "read -- the report was accepted and that section was discarded. "
                "Declare it on ReportIn/SyncGuardIn (SYS-3).",
                editor, machine, key,
            )
        try:
            db.record_ignored_report_sections(
                conn, received_at, f"{editor}/{machine}", ignored_sections)
        except Exception as e:  # noqa: BLE001 - a banner must never 500 a report
            log.warning("could not record the ignored report sections (%s: %s)",
                        type(e).__name__, e)

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
            progress_token=lane.progress_token,
            state_since=lane.state_since,
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
    # The machine's ROLE. Read here rather than where the media manifest is
    # stored (its old home, below) because it belongs to the MACHINE, not to
    # a project: a base rig that has never sent a manifest still has to be
    # knowable as one, or it lands in [ QUEUED ] forever (CR-28).
    # Two shapes on purpose (ultrareview 2026-08-19). `reported_mode` is
    # None when the report carried no `mode`, and THAT is what reaches
    # machine_state: its COALESCE keeps the stored role for a report from a
    # build too old to send one, which is CR-28's defence -- it was a no-op
    # while the default was applied here first, with the comment in db.py
    # describing a guard the code did not have. `mode` keeps the default for
    # editor_media_project, whose column is NOT NULL.
    reported_mode = (payload.mode or "").strip().lower() or None
    mode = reported_mode or "editor"
    # The machine registry (WP1). Before machine_state, because the rename
    # adoption below has to run before anything keyed on the new name is
    # written -- otherwise a renamed PC gets a fresh, empty everything.
    _register_machine(conn, editor, machine, payload, received_at)
    db.upsert_machine_state(
        conn, editor, machine, detected_slug, received_at,
        resolve_project=resolve_project or None, verified=verified,
        platform=(payload.platform or "").strip().lower() or None,
        companion_version=(payload.companion_version or "").strip() or None,
        mode=reported_mode,
        transport=flatten_transport_health(payload.transport_health, received_at),
        guard=flatten_sync_guard(payload.sync_guard, received_at),
        ingest=flatten_broll_ingest(payload.broll_ingest, received_at),
        music=flatten_music_ingest(payload.music_ingest, received_at),
        proxy=flatten_proxy_coverage(payload.proxy_coverage, received_at),
        # SYS-4: the companion's OWN wall clock, kept apart from ours and
        # clamped before it is stored. Nothing anywhere measured skew, and a
        # slow clock switches lane B off completely and silently.
        client_reported_at=payload.reported_at,
    )
    # v33 (SYS-7 / SYNC-15 / SYS-2): the companion's own "why is nothing
    # moving" answer and its watchdog's restart count, onto the row the upsert
    # above has just guaranteed exists. Its own statement rather than six more
    # columns in that INSERT, which every work package touching the report
    # edits, and because this pair has a latch rule of its own (see
    # db.store_blocked_state).
    db.store_blocked_state(
        conn, editor, machine, flatten_sync_guard(payload.sync_guard, received_at))
    # v35 (REL-8 / REL-16): what happened the last time this computer tried to
    # take a build, and which CPU it is. Same shape and the same reasoning as
    # store_blocked_state above.
    db.store_upgrade_state(
        conn, editor, machine, flatten_sync_guard(payload.sync_guard, received_at),
        (payload.arch or "").strip().lower() or None,
        running_version=(payload.companion_version or "").strip() or None)
    # v38 (wave 4's ingest contract): is this editor's footage anywhere but
    # their own disk. Same shape and the same reasoning as the two above.
    db.store_resolve_health(
        conn, editor, machine, flatten_sync_guard(payload.sync_guard, received_at))
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
    # The machine's answers to earlier file-move commands (docs/FILE_MOVES.md).
    # Recorded before the reply is built below, so a move answered in THIS
    # report is not re-sent in its own reply.
    for outcome in payload.file_moves_applied or []:
        if db.mark_file_move_applied(conn, outcome.id, editor, machine,
                                     outcome.ok, outcome.detail, received_at,
                                     state=outcome.state, attempts=outcome.attempts,
                                     relink_pending=outcome.relink_pending):
            (log.info if outcome.ok else log.warning)(
                "%s/%s file move #%s: %s%s", editor, machine, outcome.id,
                "done" if outcome.ok else (outcome.state or "failed").upper(),
                f" ({outcome.detail})" if outcome.detail else "")
    # ...and to the admin-side Resolve undos (v40, SYS-15b), on exactly the
    # same contract and in the same place, for the same reason: an undo
    # answered in THIS report must not be re-sent in its own reply.
    for undo in payload.resolve_undo_applied or []:
        if db.mark_resolve_undo_applied(
                conn, undo.id, editor, machine, undo.ok, undo.detail or "",
                received_at, state=undo.state, attempts=undo.attempts):
            (log.info if undo.ok else log.warning)(
                "%s/%s resolve undo #%s: %s%s", editor, machine, undo.id,
                "done" if undo.ok else (undo.state or "failed").upper(),
                f" ({undo.detail})" if undo.detail else "")
    # What this machine holds to undo. A section, so absent keeps whatever was
    # last reported rather than emptying the list an admin is looking at.
    db.store_resolve_journals(
        conn, editor, machine,
        None if payload.resolve_journals is None
        else [j.model_dump() for j in payload.resolve_journals])

    # -- media presence (all optional; absent field ⇒ table untouched) --
    # (`mode` is read above, with the machine_state write that now stores it.)

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
    upgrade = _upgrade_info(conn, payload.platform, payload.companion_version,
                            getattr(payload, "arch", None))
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
    # A PUSHED UPDATE (v25): an admin asked this machine to take a build
    # rather than waiting for its owner to click "Update now". Rides the same
    # reply as the halt, for the same reason -- it reaches every tray within
    # one report interval with no push infrastructure and no inbound
    # connection to an editor's PC.
    #
    # Present only while there is one outstanding, and CLEARED here the
    # moment the machine reports the version that was asked for: a standing
    # request would re-apply the same build after every restart. It names a
    # version and nothing else; the bytes still come from the signed offer
    # the companion already holds.
    update_request = db.machine_update_request(conn, editor, machine)
    if update_request:
        running = (payload.companion_version or "").strip()
        # AT OR PAST the version asked for, not just exactly it (dash-core-6,
        # 2026-08-21). A machine that was off when the push was made and then
        # took a NEWER build -- its editor clicked Update, or auto_update did
        # -- never reports the requested string again, so the request rode
        # every 30 s report for ever, the companion logged "IGNORED" once,
        # and the packages page showed a push that could never complete.
        if running and _version_at_least(running, update_request["version"]):
            db.clear_machine_update_request(conn, editor, machine)
            # Committed HERE: the report's own commit is above us, and an
            # uncommitted clear would re-offer the same update on the next
            # report forever (and re-apply it after every restart).
            conn.commit()
            log.info("%s/%s is on v%s (asked for v%s) -- the pushed update is done",
                     editor, machine, running, update_request["version"])
        else:
            result["commands"]["upgrade"] = {
                "apply": True,
                "version": update_request["version"],
                "requested_by": update_request["by_user"],
                "requested_at": update_request["at"],
            }
    # RESUME PROXY DOWNLOAD (v26, KNOWN_BUGS CR-45): an admin cleared this
    # machine's lane B breaker from the fleet page, because until now only
    # the editor's own tray could and a remote machine therefore stayed
    # parked until its owner was next at the keyboard.
    #
    # ONE SHOT: cleared as soon as the reply that carries it goes out, not
    # when the machine later reports itself clear (comp-lanes-ab-2,
    # 2026-08-21). A standing request re-armed the breaker on EVERY report:
    # a pass that re-trips inside the report interval (seconds -- a deleting
    # pass is bounded only by rclone's --max-delete 100) reported tripped,
    # the request was still there, the next reply resumed it again, and one
    # admin click became 100 more proxies into .ccsync-trash per cycle for
    # ever. That unbounded sequence is precisely what the breaker exists to
    # stop (lane_guard.py's module docstring); a second trip is a second
    # decision, so it needs a second click.
    #
    # `requested_at` rides the command so the companion can refuse to apply
    # the same stamp twice: a lost reply costs one more click, which is the
    # safe direction, but a REDELIVERED one must not resume a later trip.
    resume_request = db.lane_b_resume_request(conn, editor, machine)
    if resume_request:
        guard = payload.sync_guard
        breaker = guard.lane_b_breaker if guard is not None else None
        # A report that CARRIED a guard section saying "not tripped" retires
        # the request without sending it: there is nothing to resume, and the
        # machine has answered the question. A companion too old to send one
        # is not "not tripped" -- it gets the command (once), or the admin's
        # click would never reach it at all.
        if breaker is not None and not breaker.tripped:
            log.info("%s/%s is not parked after all -- dropping the resume request",
                     editor, machine)
        else:
            result["commands"]["resume_lane_b"] = {
                "apply": True,
                "requested_by": resume_request["by_user"],
                "requested_at": resume_request["at"],
            }
            log.info("%s/%s: delivering %s's resume-proxy-download request (%s)",
                     editor, machine, resume_request["by_user"], resume_request["at"])
        db.clear_lane_b_resume_request(conn, editor, machine)
        # Committed HERE for the same reason the pushed update's clear is:
        # the report's own commit is above us.
        conn.commit()
    # [ ASK THIS MACHINE WHY ] (v33, SYS-7): an admin wants this computer's
    # own diagnostics bundle. Rides the reply for the reason every command
    # here does -- it reaches the tray within one report interval with no
    # inbound connection to an editor's PC, which is the whole reason the
    # clipboard was the only route before.
    #
    # NOT cleared when the reply goes out, unlike resume_lane_b: it clears
    # when the BUNDLE ARRIVES (api_diagnostics). The two are opposite risks. A
    # standing resume re-armed the breaker every cycle, so it had to be
    # one-shot; a standing ask costs one upload of a text file, and the
    # failure that matters here is an admin clicking, nothing arriving, and no
    # way to tell a lost reply from a machine with nothing to say.
    #
    # `requested_at` rides it so the companion applies each ask once (the same
    # stamp comparison resume_lane_b uses); without it, every reply until the
    # bundle lands would build and upload another one.
    diag_request = db.diagnostics_request(conn, editor, machine)
    if diag_request:
        result["commands"]["diagnostics"] = {
            "requested_by": diag_request["by_user"],
            "requested_at": diag_request["at"],
        }
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
    # FILE MOVES an admin made on the server that this machine has to follow
    # (docs/FILE_MOVES.md, 2026-08-27). Present only while there is one
    # outstanding, and it keeps riding every report until the machine
    # answers through `file_moves_applied` -- a lost reply must not leave a
    # local copy at the old path re-uploading itself for ever, which is the
    # whole problem this exists to end. Bounded by db.pending_file_moves.
    pending_moves = db.pending_file_moves(conn, editor, machine, received_at)
    if pending_moves:
        result["commands"]["file_moves"] = [
            {
                "id": m["id"],
                "from_slug": m["from_slug"], "from_project_rel": m["from_project_rel"],
                "from_rel": m["from_rel"],
                "to_slug": m["to_slug"], "to_project_rel": m["to_project_rel"],
                "to_rel": m["to_rel"],
                "is_dir": bool(m["is_dir"]),
                "requested_by": m["requested_by"], "requested_at": m["requested_at"],
            }
            for m in pending_moves
        ]
        db.mark_file_moves_delivered(
            conn, [m["id"] for m in pending_moves], editor, machine, received_at)
        conn.commit()
    # AN ADMIN'S RESOLVE UNDO (v40, SYS-15b, 2026-08-29). Present only while
    # one is outstanding, and it keeps riding every report until the machine
    # answers -- the file_moves rule, not the resume_lane_b rule. The two
    # risks are opposite: a standing RESUME re-armed the breaker every cycle,
    # while a standing UNDO is idempotent (the companion refuses to replay a
    # journal it has already replayed) and the failure that matters here is an
    # admin clicking, Resolve being closed, and nothing ever happening.
    pending_undos = db.pending_resolve_undos(conn, editor, machine)
    if pending_undos:
        result["commands"]["resolve_undo"] = [
            {"id": u["id"], "journal": u["journal_id"], "project": u["project_name"],
             "requested_by": u["requested_by"], "requested_at": u["requested_at"]}
            for u in pending_undos
        ]
        db.mark_resolve_undos_delivered(
            conn, [u["id"] for u in pending_undos], received_at)
        conn.commit()
    return result


# ------------------------------------------------ the diagnostics channel
#
# SYS-7 (resilience sweep 2026-08-28). `build_diagnostics()` on the companion
# is genuinely good -- identity, token expiry, root state, config problems,
# sequencer state, rclone availability, the Resolve bridge, every section
# fault-isolated -- and it went to the CLIPBOARD, with the instruction "paste
# them to your admin in a message". If any CCSync window was open it silently
# went to the log instead. So the one artefact that answers "why is my footage
# not syncing" existed only if a non-technical editor performed a manual step
# at the right moment, on the machine that was broken.
#
# This is the same bundle on the same authenticated channel the report already
# uses. Deliberately a SEPARATE route and not a report section: a bundle is up
# to 256 KB of text on three occasional triggers, and putting it in the
# 30-second report would either bloat every tick or need a suppression rule
# (which is how sections start getting dropped -- SYS-3).

DIAGNOSTICS_TRIGGERS = ("button", "lane_error", "admin_request")


class DiagnosticsIn(BaseModel):
    """One diagnostics bundle from one computer.

    `text` is capped here as well as at the body gate (app._BODY_LIMITS):
    truncated, never rejected, on B6's rule -- an oversized bundle from the
    machine that is broken is the one bundle you must not throw away.
    """
    model_config = ConfigDict(extra="allow")

    editor_name: str = Field(min_length=1, max_length=64)
    machine: str = Field(min_length=1, max_length=128)
    machine_id: str | None = Field(default=None, max_length=64)
    at: str | None = Field(default=None, max_length=64)
    trigger: str | None = Field(default=None, max_length=32)
    text: str = Field(default="")

    @model_validator(mode="before")
    @classmethod
    def _truncate_rather_than_reject(cls, data):
        if not isinstance(data, dict):
            return data
        out = dict(data)
        text = out.get("text")
        if isinstance(text, str) and len(text) > db.DIAGNOSTICS_MAX_CHARS:
            out["text"] = text[:db.DIAGNOSTICS_MAX_CHARS]
        # `editor_name` is what the report channel calls this field and what
        # the companion sends; `editor` is accepted as the same thing because
        # the wire contract spelled it that way, and a bundle refused over the
        # name of a key would be the one bundle nobody could get.
        if not out.get("editor_name") and out.get("editor"):
            out["editor_name"] = out["editor"]
        return out


@router.post("/diagnostics")
def api_diagnostics(
    payload: DiagnosticsIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Store one diagnostics bundle (v33, SYS-7).

    THE SAME AUTH AS /report, check for check, because it carries the same
    kind of claim: a per-editor token that names somebody else is a refusal,
    a verifiable X-CCSync-Identity is REQUIRED whenever this server can verify
    one, and it must match `editor_name`. A bundle names paths, a Resolve
    project and an editor's own tree, so an unauthenticated one may not be
    stored under anybody's name (SEC-5).
    """
    settings = request.app.state.settings
    token = request.headers.get("x-ccsync-token", "")
    auth_kind, token_editor = resolve_companion_credential(settings, conn, token)
    if auth_kind == AUTH_NONE:
        if not settings.report_token and not db.looks_like_editor_report_token(token):
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
    if auth_kind == AUTH_EDITOR and token_editor != editor:
        log.warning("diagnostics refused: a per-editor token belonging to %r posted "
                    "as %r", token_editor, editor)
        raise HTTPException(
            status_code=401,
            detail="this X-CCSync-Token belongs to a different editor than editor_name",
        )
    identity = request.headers.get("x-ccsync-identity", "")
    id_user = auth.read_identity_token(settings.session_secret, identity) if identity else None
    if settings.session_secret:
        if not identity or id_user is None:
            raise HTTPException(
                status_code=401,
                detail="X-CCSync-Identity required -- sign in from the companion tray",
            )
        if id_user != editor:
            raise HTTPException(
                status_code=401,
                detail="X-CCSync-Identity does not match editor_name",
            )
    elif identity and id_user is not None and id_user != editor:
        raise HTTPException(
            status_code=401, detail="X-CCSync-Identity does not match editor_name")

    trigger = (payload.trigger or "").strip().lower()
    if trigger not in DIAGNOSTICS_TRIGGERS:
        # Recorded as `other`, never refused: a trigger this build does not
        # know is a NEWER companion, and losing the bundle over the label on
        # it would be the third repeat of SYS-3 in a new place.
        log.info("diagnostics from %s/%s carried an unknown trigger %r",
                 editor, machine, trigger)
        trigger = trigger or "other"
    bundle_id = db.record_diagnostics(
        conn, editor=editor, machine=machine,
        machine_id=(payload.machine_id or "").strip(), trigger=trigger,
        at=(payload.at or "").strip(), received_at=received_at, text=payload.text,
    )
    # THE ADMIN'S REQUEST IS ANSWERED BY THE ARRIVAL, not by the reply that
    # carried it (see the report reply's `commands.diagnostics`): this is the
    # ack, and it is the only thing that can distinguish a lost reply from a
    # machine that never answered.
    if trigger == "admin_request":
        db.clear_diagnostics_request(conn, editor, machine)
    db.audit(conn, editor, "diagnostics.received", machine,
             {"editor": editor, "machine": machine, "trigger": trigger,
              "chars": len(payload.text or ""), "id": bundle_id}, now=received_at)
    conn.commit()
    log.info("diagnostics bundle #%s from %s/%s (%s, %d chars)",
             bundle_id, editor, machine, trigger, len(payload.text or ""))
    return {"ok": True, "id": bundle_id}


@router.post("/admin/machines/{editor}/{machine}/ask-why")
def api_admin_ask_why(
    editor: str, machine: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """[ ASK THIS MACHINE WHY ]'s JSON twin (v33, SYS-7).

    404 rather than a silent success when the machine is unknown, on
    request_lane_b_resume's reasoning: a request that names nothing must read
    as a failure to the admin."""
    admin = _require_admin(request)
    if not db.request_diagnostics(conn, editor.strip().lower(), machine.strip(),
                                 admin, db.utcnow_iso()):
        raise HTTPException(status_code=404,
                            detail=f"no machine {machine!r} for {editor!r}")
    conn.commit()
    return {"ok": True}


@router.get("/admin/diagnostics")
def api_admin_diagnostics(
    request: Request, editor: str = "", machine: str = "",
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """The stored bundles. Admin only: a bundle names an editor's paths, their
    Resolve project and their tree, which is exactly what
    COMMERCIAL_READINESS.md §C L1 says one editor may not read about another.
    """
    _require_admin(request)
    if editor or machine:
        return {"bundles": db.fetch_diagnostics(
            conn, editor=editor.strip().lower() or None,
            machine=machine.strip() or None)}
    return {"bundles": db.newest_diagnostics_per_machine(conn)}


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


# ------------------------------------------------------------------- alerts
# SYS-8 (resilience sweep 2026-08-28). The JSON twins of the Settings, Alerts
# page's three buttons, so "send a test" and "what would this week's report
# say" behave IDENTICALLY from a script and from the page: both call
# alerts.py, neither carries its own copy of the logic.
#
# NO SECRET IS EVER IN A RESPONSE HERE. `alerts.settings_view` returns whether
# a password is set and where it came from, never the value, and the sink's
# refusals are composed by alerts.py for exactly that reason.


@router.get("/admin/alerts")
def api_alerts(request: Request, conn: sqlite3.Connection = Depends(get_conn)
               ) -> dict[str, Any]:
    _require_admin(request)
    from . import alerts

    now = db.utcnow_iso()
    findings = alerts.scan(conn, request.app.state.settings, now)
    return {
        "settings": alerts.settings_view(conn, request.app.state.settings),
        "open": findings,
        "counts": alerts.open_counts(findings),
        "kinds": [{"kind": k.kind, "severity": k.severity, "title": k.title,
                   "what": k.what} for k in alerts.ALERT_KINDS],
        "log": db.fetch_alerts(conn, limit=200),
    }


@router.post("/admin/alerts/test")
def api_alerts_test(request: Request, conn: sqlite3.Connection = Depends(get_conn)
                    ) -> dict[str, Any]:
    """Send one message through the configured sink, now.

    dedup OFF: an admin pressing the button twice is asking twice, and a
    silent "already sent today" is exactly the answer that makes somebody
    believe a broken sink works.
    """
    _require_admin(request)
    from . import alerts

    subject, text = alerts.compose_alert(
        alerts.KIND_TEST, "test",
        "This is a test of the CC Sync alert channel. Nothing is wrong.")
    result = alerts.send(conn, request.app.state.settings, subject, text,
                         kind=alerts.KIND_TEST, dedup=False)
    conn.commit()
    return result


@router.get("/admin/alerts/preview", response_class=PlainTextResponse)
def api_alerts_preview(request: Request, conn: sqlite3.Connection = Depends(get_conn)
                       ) -> str:
    """This week's report as it would be sent. Text, not JSON: the thing being
    previewed IS the text."""
    _require_admin(request)
    from . import alerts

    subject, text = alerts.compose_weekly(conn, db.utcnow_iso(),
                                          request.app.state.settings)
    return f"Subject: {subject}\n\n{text}"


# ---------------------------------------------------------------- recovery
# SYS-15 (resilience sweep 2026-08-28, built 2026-08-29 as wave 5). Getting
# something back without a root shell. `recovery.py` holds the reasoning; these
# are the routes, and every one of them is admin-only: a restore, a rehearsal
# and a runbook that names this NAS's datasets are all operator surface.


@router.get("/admin/recovery")
def api_recovery(request: Request, problem: str = "",
                 conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    """What is protected right now, what can have gone wrong, and the plan.

    Never 500s on a NAS that is down: page_view gathers what it can and says
    what it could not. The page an owner opens after losing something is the
    last page in this product that may fail to render."""
    _require_admin(request)
    from . import recovery

    return recovery.page_view(request.app.state.settings, conn, problem)


@router.get("/admin/recovery/preview")
def api_recovery_preview(request: Request, slug: str, snapshot: str,
                         conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    _require_admin(request)
    from . import recovery

    try:
        return recovery.preview_restore(request.app.state.settings, conn, slug, snapshot)
    except recovery.RecoveryError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/admin/recovery/restore")
def api_recovery_restore(request: Request, slug: str, snapshot: str,
                         include_changed: bool = False,
                         conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    """Restore into `<project>/.restored-<ts>/`, never over the live path.

    There is no "and overwrite" flag on this route and there is not going to
    be one: quarantine-instead-of-overwrite is what makes the snapshot choice
    safe to get wrong, which is the whole of SYS-15(a)."""
    admin = _require_admin(request)
    from . import recovery

    try:
        return recovery.restore_into_quarantine(
            request.app.state.settings, conn, slug, snapshot, admin,
            include_changed=include_changed)
    except recovery.RecoveryError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/admin/recovery/drill")
def api_recovery_drill(request: Request, snapshot: str = "",
                       conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    """Rehearse a restore against a scratch path (SYS-15d).

    A backup nobody has restored from is a hypothesis. A drill that WORKS
    records the date on the protection panel; one that fails records nothing
    there, so that line stays MISSING rather than green."""
    admin = _require_admin(request)
    from . import recovery

    try:
        return recovery.run_drill(request.app.state.settings, conn, admin,
                                  snapshot=snapshot)
    except recovery.RecoveryError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/admin/machines/{editor}/{machine}/resolve-journals")
def api_machine_resolve_journals(
    editor: str, machine: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """The clip-path changes this computer has recorded, and what has been
    asked of it. The list comes from the machine's own reports: there is no
    inbound connection to an editor's PC, so it tells us and we remember."""
    _require_admin(request)
    editor, machine = editor.strip().lower(), machine.strip()
    return {"journals": db.machine_resolve_journals(conn, editor, machine),
            "requests": db.resolve_undos_for_machine(conn, editor, machine)}


@router.post("/admin/machines/{editor}/{machine}/resolve-undo")
def api_machine_resolve_undo(
    editor: str, machine: str, request: Request, journal: str = "",
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """[ UNDO THIS CHANGE ] on somebody else's computer (SYS-15b).

    The same shape as CR-45's [ RESUME ]: this is "press the tray's undo on
    their behalf", not an override. The companion replays the journal the tray
    would have replayed, refuses it for the same reasons the tray refuses it
    (the wrong project is open), and answers on the report channel.

    404 rather than a silent success for a machine or a journal we do not
    know, on request_lane_b_resume's reasoning: a request that names nothing
    must read as a failure to the admin."""
    admin = _require_admin(request)
    editor, machine, journal = editor.strip().lower(), machine.strip(), journal.strip()
    known = db.machine_resolve_journals(conn, editor, machine)
    match = next((j for j in known if str(j.get("id") or "") == journal), None)
    if match is None:
        raise HTTPException(
            status_code=404,
            detail=f"that computer has not reported a change called {journal!r}. Its "
                   "list is refreshed every time it reports: reload and try again.")
    request_id = db.request_resolve_undo(
        conn, editor, machine, journal, str(match.get("project") or ""),
        admin, db.utcnow_iso())
    if not request_id:
        raise HTTPException(status_code=404, detail=f"no machine {machine!r} for {editor!r}")
    conn.commit()
    log.info("%s asked %s/%s to undo the clip-path changes in %s",
             admin, editor, machine, journal)
    return {"ok": True, "id": request_id}
