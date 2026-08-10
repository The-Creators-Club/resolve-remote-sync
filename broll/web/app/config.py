"""Runtime configuration, read from environment variables.

See SPEC.md "Data layout (DATA_ROOT)" and "Web API contract".
"""
from __future__ import annotations

import os
from pathlib import Path


def get_data_root() -> Path:
    """DATA_ROOT from env BROLL_DATA_ROOT, default ./data.

    Read live (not cached at import time) so tests can point it at a temp
    directory by setting the env var before constructing paths.
    """
    return Path(os.environ.get("BROLL_DATA_ROOT", "./data")).resolve()


def get_db_path() -> Path:
    return get_data_root() / "broll.db"


def get_proxies_dir() -> Path:
    return get_data_root() / "proxies"


def get_sprites_dir() -> Path:
    return get_data_root() / "sprites"


def get_posters_dir() -> Path:
    return get_data_root() / "posters"


def get_sheets_dir() -> Path:
    return get_data_root() / "sheets"


def get_ingest_token() -> str | None:
    """BROLL_INGEST_TOKEN. If unset, ingest is allowed without a token (dev mode)."""
    token = os.environ.get("BROLL_INGEST_TOKEN")
    return token if token else None


# The two browse roots. Downloads is everything sourced from the web;
# Creators_Club is footage we shot. The split is by SHARE because that is the
# only thing the web app can see: which side of a proxy/original pair a share
# archives lives in the indexer's config (ShareConfig.source), and this app does
# not read that file — it may not even be on the same machine.
COLLECTION_DOWNLOADS = "downloads"
COLLECTION_CREATORS = "creators_club"
COLLECTION_LABELS = {COLLECTION_DOWNLOADS: "Downloads", COLLECTION_CREATORS: "Creators_Club"}


def get_creators_shares() -> set[str]:
    """BROLL_CREATORS_SHARES: comma-separated share names that are our own
    footage. Everything not listed is a download.

    Defaults to empty, so an unconfigured deployment shows the whole archive
    under Downloads rather than inventing an empty Creators_Club or, worse,
    quietly filing bought/downloaded footage as ours.
    """
    raw = os.environ.get("BROLL_CREATORS_SHARES", "")
    return {s.strip() for s in raw.split(",") if s.strip()}


def collection_of(share: str) -> str:
    return COLLECTION_CREATORS if share in get_creators_shares() else COLLECTION_DOWNLOADS


# Directory this module lives in: web/app/
APP_DIR = Path(__file__).resolve().parent
# web/
WEB_DIR = APP_DIR.parent
STATIC_DIR = WEB_DIR / "static"


def parse_shares() -> list[dict[str, str]]:
    """Parse BROLL_SHARES env var.

    Format: "broll:Main b-roll archive;other:desc" -> semicolon-separated
    entries of "share:description".
    """
    raw = os.environ.get("BROLL_SHARES", "")
    shares: list[dict[str, str]] = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            share, desc = part.split(":", 1)
        else:
            share, desc = part, ""
        share = share.strip()
        if not share:
            continue
        shares.append({"share": share, "description": desc.strip()})
    return shares
