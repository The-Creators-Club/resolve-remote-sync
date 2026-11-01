"""The Timeline Cards apps' own updates, served at /cards/app/ (2026-10-22).

Alex: "make the app installable inside the app, without needing to get pushed
over adb". The Windows and Android apps (the Timeline Cards repo's
docs/NATIVE-APPS.md) have a [ CHECK FOR UPDATE ] in their settings page; this
is what it reads:

    GET /cards/app/latest.json   the newest build per platform
    GET /cards/app/<file>        one of the files latest.json names

The builds live in the vault, `<DASH_CARDS_VAULT_ROOT>/Apps/Timeline Cards/`
(X:\\Apps\\Timeline Cards on the editing PCs), put there with latest.json by
the Timeline Cards repo's apps/publish.ps1. Nothing is uploaded through the
dashboard and nothing here writes.

Both routes are behind the login gate like the rest of /cards, which is
right: the app asks through its own local server, carrying the session the
editor signed in with. Only a file latest.json NAMES is served, by its bare
name, so the route is not a window onto the vault.
"""

from __future__ import annotations

import json
import os
import re

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()

SUBDIR = ("Apps", "Timeline Cards")
LATEST = "latest.json"
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,120}\.(apk|exe)$")


def apps_dir(request: Request) -> str:
    from . import cards

    vault = cards.vault_root(request.app.state.settings)
    return os.path.join(vault, *SUBDIR) if vault else ""


def _latest(folder: str) -> dict | None:
    try:
        with open(os.path.join(folder, LATEST), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _named(latest: dict) -> set[str]:
    out = set()
    for entry in latest.values():
        if isinstance(entry, dict) and isinstance(entry.get("file"), str):
            out.add(entry["file"])
    return out


@router.get("/cards/app/latest.json", include_in_schema=False)
def cards_app_latest(request: Request):
    folder = apps_dir(request)
    latest = _latest(folder) if folder else None
    if latest is None:
        return JSONResponse({"ok": False, "error": "no app builds have been published"},
                            status_code=404, headers={"cache-control": "no-store"})
    return JSONResponse(dict(latest, ok=True), headers={"cache-control": "no-store"})


@router.get("/cards/app/{name}", include_in_schema=False)
def cards_app_file(name: str, request: Request):
    folder = apps_dir(request)
    latest = _latest(folder) if folder else None
    if latest is None or not _SAFE.match(name) or name not in _named(latest):
        return JSONResponse({"ok": False, "error": "no such app build"}, status_code=404)
    path = os.path.join(folder, name)
    if not os.path.isfile(path):
        return JSONResponse({"ok": False, "error": "that build is listed but missing"},
                            status_code=404)
    kind = ("application/vnd.android.package-archive" if name.endswith(".apk")
            else "application/octet-stream")
    return FileResponse(path, media_type=kind, filename=name,
                        headers={"cache-control": "no-store"})
