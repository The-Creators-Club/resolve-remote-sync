"""JSON API under /api/v1, plus the view-model builders shared with ui.py.

The report endpoint is the only write path exposed over HTTP; it requires the
X-CCSync-Token shared secret unless DASH_REPORT_TOKEN_OPTIONAL=1.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from . import VERSION, auth, db, health
from .syncthing_client import SyncthingClient, SyncthingError
from .truenas_client import (
    EDITORS_GROUP, TrueNASClient, TrueNASError, is_valid_username, looks_like_ssh_pubkey,
)

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
    the next one can't be written the naive way."""
    if not configured or not presented:
        return False
    return hmac.compare_digest(str(configured), str(presented))


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db.connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


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
    return {"generated_at": now, "transfers": rows,
            "fleet_speed_bps": sum((x["speed_bps"] or 0) for x in rows)}


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
    result = []
    for entry in machines.values():
        key = (entry["editor_username"], entry["machine"])
        entry["status"] = health.worst(l["chip"] for l in entry["lanes"])
        entry["verified"] = verified.get(key, False)
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
    return {"generated_at": now, "editors": result,
            "current_companion_version": current_version_for("windows")}


# ------------------------------------------------------------------ routes

@router.get("/health")
def api_health(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    """Liveness for anyone; detail only for authenticated callers.

    The full body carries project slugs, project labels and Syncthing's
    folder error strings, and this route is in app.py's _OPEN_EXACT so the
    Docker healthcheck (which only reads the status code, from 127.0.0.1) can
    reach it without credentials -- which made the client roster readable by
    anyone who could reach the port. Unauthenticated callers now get
    {"ok", "version"} and the same 200/exception behaviour; a session or the
    companion's X-CCSync-Token unlocks the rest."""
    settings = request.app.state.settings
    collector = db.fetch_collector_status(conn)
    if not (
        auth.get_session_user(request) is not None
        or token_ok(settings.report_token, request.headers.get("x-ccsync-token", ""))
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
        # collector thread is dead/wedged. Docker's healthcheck (see
        # deploy/compose.yaml) uses syncthing_reachable, which this clears.
        "collector_stale": collector["collector_stale"],
        "folder_errors": collector["folder_errors"],
        "last_polls": {
            kind: {"finished_at": run["finished_at"], "ok": bool(run["ok"]), "error": run["error"]}
            for kind, run in collector["kinds"].items()
        },
    }


@router.get("/projects")
def api_projects(conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    return build_projects_view(conn)


@router.get("/projects/{slug}")
def api_project(slug: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    view = build_project_view(conn, slug)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    return view


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
    slug: str, device_id: str, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    project = db.fetch_project(conn, slug)
    if project is None:
        raise HTTPException(status_code=404, detail=f"unknown project {slug!r}")
    device = next((e for e in project["editors"] if e["device_id"] == device_id), None)
    if device is None:
        raise HTTPException(status_code=404, detail=f"device not in project: {device_id}")
    result = db.fetch_missing(conn, project["id"], device["device_row_id"])
    result["need_items"] = device["need_items"]
    return result


@router.get("/editors")
def api_editors(conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    return build_editors_view(conn)


def build_queue_view(conn: sqlite3.Connection, editor: str, now: str | None = None) -> dict[str, Any]:
    """The editor's ordered sync queue with per-project progress, for MY QUEUE."""
    now = now or db.utcnow_iso()
    projects = {p["slug"]: p for p in build_projects_view(conn, now)["projects"]}
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
    if auth.login_throttled(username):
        raise HTTPException(status_code=429, detail="too many failed attempts; wait a minute")
    verifier = getattr(request.app.state, "credential_verifier", auth.verify_credentials)
    try:
        verified = verifier(settings, username, payload.password)
    except auth.CredentialProbeBusy as exc:
        raise HTTPException(status_code=503, detail=f"login busy: {exc} -- try again") from exc
    if not verified:
        auth.record_login_failure(username)
        raise HTTPException(status_code=401, detail="bad username or password")
    auth.clear_login_failures(username)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.make_session_cookie(settings.session_secret, username),
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        # see auth.cookie_secure: on for https, off for today's http LAN
        secure=auth.cookie_secure(settings, request),
        path="/",
    )
    return {"ok": True, "user": username, "is_admin": auth.is_admin(settings, username)}


@router.post("/logout")
def api_logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(auth.COOKIE_NAME, path="/")
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

    Degrades the way build_admin_users_view does: with no TRUENAS_PW there is
    nothing to check against, so the check is skipped (and logged) rather than
    locking every companion out of a TrueNAS-less deployment. A TrueNAS that
    is configured but unreachable answers 503 -- retryable, never open.
    """
    if auth.is_admin(settings, username):
        return
    if not settings.truenas_pw:
        log.warning(
            "minting an identity for %r without an editors-group check: TRUENAS_PW is not "
            "configured on the dashboard", username)
        return
    client = TrueNASClient(settings.truenas_host, settings.truenas_user, settings.truenas_pw,
                           base_url=settings.truenas_base_url or None,
                           verify_ssl=settings.truenas_verify_ssl)
    try:
        allowed = client.is_editor(username)
    except TrueNASError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"cannot confirm fleet membership right now ({exc}) -- try again",
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
    if auth.login_throttled(username):
        raise HTTPException(status_code=429, detail="too many failed attempts; wait a minute")
    verifier = getattr(request.app.state, "credential_verifier", auth.verify_credentials)
    try:
        verified = verifier(settings, username, payload.password)
    except auth.CredentialProbeBusy as exc:
        raise HTTPException(status_code=503, detail=f"verify busy: {exc} -- try again") from exc
    if not verified:
        auth.record_login_failure(username)
        raise HTTPException(status_code=401, detail="bad username or password")
    auth.clear_login_failures(username)
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


def _require_selection_read(request: Request, editor: str) -> None:
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
    if token_ok(settings.report_token, token):
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


def _require_selection_write(request: Request, editor: str) -> str:
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if not auth.can_manage(settings, user, editor):
        raise HTTPException(
            status_code=403 if user else 401,
            detail="you can only change your own projects (admins excepted)",
        )
    return user


@router.get("/selection/{editor}")
def api_get_selection(
    editor: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    editor = editor.strip().lower()
    _require_selection_read(request, editor)
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
    view = _selection_view(conn, editor)
    view["changed"] = added
    return view


@router.delete("/selection/{editor}/{slug}")
def api_untick(
    editor: str, slug: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    editor = editor.strip().lower()
    _require_selection_write(request, editor)
    removed = db.remove_selection(conn, editor, slug)
    conn.commit()
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
    # it, all three vanish from discovery, and a Syncthing folder is
    # provisioned whose path CONTAINS three other folders' paths.
    for child_rel, _child_slug in provision.scan_project_dirs(projects_dir):
        if child_rel.startswith(rel + "/"):
            raise ProjectSetupError(
                f"that folder already contains a project ({child_rel}) -- pick that instead"
            )

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
        raise ProjectSetupError(f"could not create folders on the NAS: {exc}")

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
    for child_rel, child_slug in provision.scan_project_dirs(projects_dir):
        if child_rel != rel and child_rel.startswith(rel + "/"):
            raise ProjectSetupError(
                f"this folder contains an existing project ({child_rel}) -- pick that instead"
            )

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

def build_admin_users_view(settings) -> dict[str, Any]:
    """Everything the admin 'Users' section needs: existing editor accounts
    (from TrueNAS) plus devices that still need approving/naming (Syncthing
    devices that are either truly pending, or already configured but with a
    name that doesn't resolve to a username -- see db.resolve_editor_username).

    Returns {"error": <str>} instead of raising when a backend is
    unreachable, mirroring the rest of the dashboard's "stale banner, don't
    crash the page" convention.
    """
    if not settings.truenas_pw:
        return {"truenas_configured": False, "editors": [], "pending_devices": [], "error": None}

    truenas = TrueNASClient(settings.truenas_host, settings.truenas_user, settings.truenas_pw,
                              base_url=settings.truenas_base_url or None,
                              verify_ssl=settings.truenas_verify_ssl)
    try:
        editors = truenas.list_editors()
    except TrueNASError as exc:
        return {"truenas_configured": True, "editors": [], "pending_devices": [],
                "error": f"truenas: {exc}"}

    editor_rows = [{
        "username": u["username"],
        "uid": u.get("uid"),
        "full_name": u.get("full_name") or u["username"],
        "smb": bool(u.get("smb")),
        "has_ssh_key": bool(u.get("sshpubkey")),
        "home": u.get("home"),
        "locked": bool(u.get("locked")),
    } for u in sorted(editors, key=lambda u: u["username"])]

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
            return {"truenas_configured": True, "editors": editor_rows, "pending_devices": [],
                    "error": f"syncthing: {exc}"}

    return {"truenas_configured": True, "editors": editor_rows, "pending_devices": pending, "error": None}


def _truenas_client_or_503(request: Request) -> TrueNASClient:
    settings = request.app.state.settings
    if not settings.truenas_pw:
        raise HTTPException(status_code=503, detail="TRUENAS_PW is not configured on the dashboard")
    return TrueNASClient(settings.truenas_host, settings.truenas_user, settings.truenas_pw,
                              base_url=settings.truenas_base_url or None,
                              verify_ssl=settings.truenas_verify_ssl)


class CreateEditorIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    ssh_pubkey: str = Field(min_length=1)
    full_name: str | None = None
    password: str | None = None


class SetPasswordIn(BaseModel):
    password: str = Field(min_length=1)


class ApproveDeviceIn(BaseModel):
    device_id: str = Field(min_length=1)
    username: str = Field(min_length=1, max_length=32)


@router.get("/admin/users")
def api_admin_users(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return build_admin_users_view(request.app.state.settings)


@router.post("/admin/users")
def api_admin_create_user(payload: CreateEditorIn, request: Request) -> dict[str, Any]:
    _require_admin(request)
    truenas = _truenas_client_or_503(request)
    username = payload.username.strip().lower()
    if not is_valid_username(username):
        raise HTTPException(
            status_code=422,
            detail="username must start with a letter and contain only lowercase letters, "
                   "digits, '.', '_', '-'",
        )
    ssh_pubkey = payload.ssh_pubkey.strip()
    if not looks_like_ssh_pubkey(ssh_pubkey):
        raise HTTPException(status_code=422, detail="does not look like an OpenSSH public key")
    try:
        result = truenas.create_or_update_editor(username, ssh_pubkey, payload.full_name)
        if payload.password:
            truenas.set_known_password(username, payload.password)
            result["password_set"] = True
    except TrueNASError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "result": result, "view": build_admin_users_view(request.app.state.settings)}


@router.post("/admin/users/{username}/password")
def api_admin_set_password(username: str, payload: SetPasswordIn, request: Request) -> dict[str, Any]:
    """Set a known password for an EDITOR account.

    The charset check is here as well as inside set_known_password: an
    admin's typo (or a URL-encoded 'root') must be a 422 from the dashboard,
    not a TrueNAS round-trip that changes a system account's password. The
    refusals that actually matter -- uid < 1000, not in the editors group --
    live in truenas_client.set_known_password so every caller gets them."""
    _require_admin(request)
    username = username.strip().lower()
    if not is_valid_username(username):
        raise HTTPException(
            status_code=422,
            detail="username must start with a letter and contain only lowercase letters, "
                   "digits, '.', '_', '-'",
        )
    truenas = _truenas_client_or_503(request)
    try:
        truenas.set_known_password(username, payload.password)
    except TrueNASError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/admin/devices/approve")
def api_admin_approve_device(payload: ApproveDeviceIn, request: Request) -> dict[str, Any]:
    _require_admin(request)
    settings = request.app.state.settings
    if not settings.syncthing_url:
        raise HTTPException(status_code=503, detail="SYNCTHING_GUI_URL is not configured")
    username = payload.username.strip().lower()
    if not is_valid_username(username):
        raise HTTPException(status_code=422, detail="username must be a valid TrueNAS-style username")
    syncthing = SyncthingClient.from_settings(settings)
    try:
        syncthing.approve_device(payload.device_id.strip(), username)
    except SyncthingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "view": build_admin_users_view(settings)}


# ------------------------------------------- companion packages (upgrade channel)

_PACKAGE_PLATFORMS = {"windows", "macos"}
_PACKAGE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_PACKAGE_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _package_file(settings, row: sqlite3.Row | dict[str, Any]) -> Path:
    return settings.packages_path() / row["platform"] / row["filename"]


def _unlink_package_file(settings, row: sqlite3.Row | dict[str, Any]) -> None:
    try:
        _package_file(settings, row).unlink(missing_ok=True)
    except OSError:
        pass  # a stray file is harmless; the DB row is the source of truth


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
    current = db.get_current_package(conn, plat)
    if current is None or not running or running == current["version"]:
        return None
    return {
        "version": current["version"],
        "url": f"/api/v1/companion/package/{plat}/{current['version']}",
        "sha256": current["sha256"],
        "size_bytes": current["size_bytes"],
    }


def build_packages_view(conn: sqlite3.Connection, settings, now: str | None = None) -> dict[str, Any]:
    now = now or db.utcnow_iso()
    packages = []
    current: dict[str, str] = {}
    for row in db.fetch_companion_packages(conn):
        entry = {
            "version": row["version"],
            "platform": row["platform"],
            "filename": row["filename"],
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
            "published_at": row["published_at"],
            "published_by": row["published_by"],
            "is_current": bool(row["is_current"]),
            "file_exists": _package_file(settings, row).is_file(),
        }
        if entry["is_current"]:
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
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Publish a companion build: raw exe bytes as the request body (no
    multipart -- python-multipart isn't a dependency and doesn't need to be),
    expected sha256 as a query param, verified server-side before anything
    becomes visible. A `.part` staging file + os.replace means the served
    file is always complete.

    `?prune=1` opts IN to deleting all but the current build and the two
    newest non-current ones. It is off by default: publishing must not
    silently destroy older build artifacts (rollback material) as a side
    effect, given the standing no-deletion rule.

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
    if platform not in _PACKAGE_PLATFORMS:
        raise HTTPException(status_code=422, detail=f"platform must be one of {sorted(_PACKAGE_PLATFORMS)}")
    if not _PACKAGE_VERSION_RE.match(version):
        raise HTTPException(status_code=422, detail="version must look like 1.2.3")
    sha = sha256.strip().lower()
    if not _PACKAGE_SHA256_RE.match(sha):
        raise HTTPException(status_code=422, detail="sha256 query param must be 64 hex chars")
    if db.get_package(conn, platform, version) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"version {version} is already published for {platform} -- "
                   "bump VERSION in companion/src/ccsync_companion/config.py and rebuild",
        )

    dest_dir = settings.packages_path() / platform
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"ccsync-companion-{version}" + (".exe" if platform == "windows" else "")
    part = dest_dir / (filename + ".part")
    digest = hashlib.sha256()
    size = 0
    too_big = False
    try:
        with part.open("wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_PACKAGE_BODY_BYTES:
                    too_big = True
                    break
                await run_in_threadpool(fh.write, chunk)
                digest.update(chunk)
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
    await run_in_threadpool(os.replace, part, dest_dir / filename)

    db.insert_companion_package(
        conn, version=version, platform=platform, filename=filename,
        sha256=sha, size_bytes=size, published_by=user, now=db.utcnow_iso(),
    )
    if make_current:
        db.set_current_package(conn, platform, version)
    pruned = db.prune_companion_packages(conn, platform) if prune else []
    # Commit BEFORE unlinking: the old order deleted the exe first, so a
    # failed commit left the file gone while the row survived ([ FILE
    # MISSING ] in the UI, 404 for any companion pointed at it).
    conn.commit()
    for row in pruned:
        _unlink_package_file(settings, row)
    return {"ok": True, "view": build_packages_view(conn, settings)}


@router.post("/admin/packages/{platform}/{version}/current")
def api_set_current_package(
    platform: str, version: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Set (or roll back) which version the fleet is offered."""
    _require_admin(request)
    platform = platform.strip().lower()
    if not db.set_current_package(conn, platform, version):
        raise HTTPException(status_code=404, detail=f"no published {platform} package {version}")
    conn.commit()
    return {"ok": True, "view": build_packages_view(conn, request.app.state.settings)}


@router.delete("/admin/packages/{platform}/{version}")
def api_delete_package(
    platform: str, version: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    _require_admin(request)
    settings = request.app.state.settings
    platform = platform.strip().lower()
    row = db.get_package(conn, platform, version)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no published {platform} package {version}")
    if row["is_current"]:
        raise HTTPException(
            status_code=409,
            detail="cannot delete the current version -- make another version current first",
        )
    db.delete_companion_package(conn, platform, version)
    conn.commit()
    _unlink_package_file(settings, row)
    return {"ok": True, "view": build_packages_view(conn, settings)}


def _require_package_read(request: Request) -> None:
    """Same dual auth as _require_selection_read, minus the editor scoping:
    any signed-in user or any companion holding the shared report token may
    download a published package (it's the same exe everyone runs)."""
    settings = request.app.state.settings
    if token_ok(settings.report_token, request.headers.get("x-ccsync-token", "")):
        return
    if auth.get_session_user(request) is not None:
        return
    raise HTTPException(status_code=401, detail="log in, or present X-CCSync-Token")


@router.get("/companion/package/{platform}/{version}")
def api_download_package(
    platform: str, version: str, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> FileResponse:
    _require_package_read(request)
    settings = request.app.state.settings
    row = db.get_package(conn, platform.strip().lower(), version)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no published {platform} package {version}")
    path = _package_file(settings, row)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="package file missing on server")
    return FileResponse(
        str(path),
        media_type="application/octet-stream",
        filename=row["filename"],
        headers={"X-CCSync-SHA256": row["sha256"], "X-CCSync-Version": row["version"]},
    )


# ------------------------------------------------------------------ report

# Field ceilings for the report body (see the unbounded-report finding). Every
# string that reaches a DB column is capped, every list is capped, and the two
# free-form dicts have a key-count cap -- so the whole payload has a bounded
# worst case even before the request-size middleware in app.py.
MAX_REPORT_PROJECTS = 64          # keys in local_manifest / media_tree
MAX_MANIFEST_FILES = 4000         # per project, per kind (db caps rows again)
MAX_MEDIA_CLIPS = 4000            # per Resolve project


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
    originals: list[tuple[str, int | None]] | None = Field(
        default=None, max_length=MAX_MANIFEST_FILES)
    proxies: list[tuple[str, int | None]] | None = Field(
        default=None, max_length=MAX_MANIFEST_FILES)


class MediaClipIn(BaseModel):
    bin_path: str = Field(default="", max_length=512)
    clip_name: str = Field(max_length=512)
    file_path: str | None = Field(default=None, max_length=1024)
    kind: str | None = Field(default=None, max_length=32)
    present: bool = False


class ReportIn(BaseModel):
    editor_name: str = Field(min_length=1, max_length=64)
    machine: str = Field(min_length=1, max_length=128)
    companion_version: str | None = Field(default=None, max_length=64)
    platform: str | None = Field(default=None, max_length=32)  # 'windows' | 'macos'
    reported_at: str = Field(max_length=64)
    # Generous but bounded (see SEC-4): current companions send exactly the
    # three lanes in LANE_LABELS.
    lanes: list[LaneReportIn] = Field(max_length=32)
    queue: list[str] | None = Field(default=None, max_length=MAX_REPORT_PROJECTS)
    current_project: str | None = Field(default=None, max_length=512)
    resolve_project: str | None = Field(default=None, max_length=512)
    # Media-presence (companions >= 0.3); all optional -> absent leaves tables
    # untouched, so a LIGHT report never wipes manifest/tree data.
    mode: str | None = Field(default=None, max_length=32)   # 'base' | 'editor'
    local_manifest: dict[str, ManifestProjectIn] | None = None   # keyed by project rel
    media_tree: dict[str, list[MediaClipIn]] | None = None       # keyed by RESOLVE PROJECT NAME

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

    @field_validator("local_manifest", "media_tree")
    @classmethod
    def _cap_project_keys(cls, value):
        if value is not None and len(value) > MAX_REPORT_PROJECTS:
            raise ValueError(f"too many projects (max {MAX_REPORT_PROJECTS})")
        return value

    @field_validator("media_tree")
    @classmethod
    def _cap_clips(cls, value):
        if value is not None:
            for name, clips in value.items():
                if len(clips) > MAX_MEDIA_CLIPS:
                    raise ValueError(f"too many clips for {name!r} (max {MAX_MEDIA_CLIPS})")
        return value


@router.post("/report")
def api_report(
    payload: ReportIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    settings = request.app.state.settings
    token = request.headers.get("x-ccsync-token", "")
    if settings.report_token:
        if not token_ok(settings.report_token, token):
            raise HTTPException(status_code=401, detail="bad or missing X-CCSync-Token")
    elif not settings.report_token_optional:
        raise HTTPException(
            status_code=401,
            detail="report token not configured on server (set DASH_REPORT_TOKEN)",
        )
    received_at = db.utcnow_iso()
    editor = payload.editor_name.strip().lower()
    machine = payload.machine.strip()

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
    result = {"ok": True, "lanes": len(payload.lanes), "received_at": received_at}
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
