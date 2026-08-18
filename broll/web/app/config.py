"""Runtime configuration, read from environment variables.

See SPEC.md "Data layout (DATA_ROOT)" and "Web API contract".
"""
from __future__ import annotations

import os
import re
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


# --- dashboard b-roll ingest (docs/BROLL_INGEST_PLAN.md, 2026-08-18) ---------

# Where the companion stages dropped bytes inside the editor's own archive
# mirror: `<local archive root>/.ingest/<staging_id>/`. Named here, not only in
# the companion, because it is a directory that appears in the SHARED archive
# tree's local mirror and anything that walks that tree has to know it is not
# footage.
ARCHIVE_INGEST_DIR = ".ingest"

# How long a claim is good for, and how often the companion must say it is
# still alive. Copied from the ytdl fleet routes' 300/30 because the failure
# they cover is identical: a machine that is switched off mid-batch has to
# release its lease without anyone pressing anything, and 10 missed heartbeats
# is a comfortable margin over a laptop lid closing for a minute.
LEASE_SECONDS = 300
HEARTBEAT_SECONDS = 30


def get_fleet_token() -> str | None:
    """DASH_REPORT_TOKEN, or None when it is unset.

    The shared secret every companion in the fleet already holds. FAIL-CLOSED,
    like the ytdl fleet routes and unlike nothing else here: None means every
    /api/fleet/ingest call is refused, because the alternative -- an
    unauthenticated route that mints `videos` rows and hands out archive paths
    -- is not a dev convenience, it is the whole write path.

    It is NOT an identity: every machine has the same one, so it proves "a
    fleet machine" and nothing about WHICH (H5, COMMERCIAL_READINESS.md item
    7). See fleet_auth.require_identity for the half that does.
    """
    token = os.environ.get("DASH_REPORT_TOKEN")
    return token if token else None


def get_session_secret() -> str | None:
    """DASH_SESSION_SECRET, or None when it is unset.

    The key the dashboard signs its identity tokens with. Read live rather than
    cached so a container restart with a rotated secret needs no code change,
    and shared with the dashboard by ENVIRONMENT rather than by import: this
    app is deployed as its own tree and cannot see ccsync_dashboard.
    """
    secret = os.environ.get("DASH_SESSION_SECRET")
    return secret if secret else None


def get_ingest_token() -> str | None:
    """BROLL_INGEST_TOKEN, or None when it is unset.

    None means the ingest routes REFUSE (503) -- it stopped meaning "dev mode,
    ingest is open" on 2026-08-17 (COMMERCIAL_READINESS.md item 15). See
    routes_ingest.verify_ingest_token.
    """
    token = os.environ.get("BROLL_INGEST_TOKEN")
    return token if token else None


# The two browse roots. Downloads is everything sourced from the web; the
# other one is footage this customer shot. The split is by SHARE because that
# is the only thing the web app can see: which side of a proxy/original pair a
# share archives lives in the indexer's config (ShareConfig.source), and this
# app does not read that file — it may not even be on the same machine.
#
# THE OWN-FOOTAGE SLUG IS SITE DATA (2026-08-17,
# docs/COMMERCIAL_READINESS.md item 4/10). It was the literal "creators_club":
# one customer's name in every search URL, every tree root and the folder
# label an editor reads. `owned` is the neutral default; a site that wants its
# own name in the UI sets BROLL_DEFAULT_COLLECTION (slug) and
# BROLL_DEFAULT_COLLECTION_LABEL.
#
# Nothing in the DATABASE moves: the collection is derived from
# BROLL_CREATORS_SHARES at query time, never stored on a row.
COLLECTION_DOWNLOADS = "downloads"
# The pre-2026-08-17 slug. Still accepted on the wire so a bookmarked
# ?collection=creators_club URL, and any client that predates the rename,
# keep working -- see normalise_collection.
LEGACY_COLLECTION_CREATORS = "creators_club"


def get_creators_collection() -> str:
    """The own-footage collection's slug. Lowercased and stripped of anything
    that is not URL-safe: it travels as a query parameter and as a JSON key
    into the frontend, so a slug with a space in it would break both."""
    raw = os.environ.get("BROLL_DEFAULT_COLLECTION", "").strip().lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-")
    return slug or "owned"


def get_creators_collection_label() -> str:
    """What the folder tree calls that root. Defaults to a description of what
    it holds rather than to a name, because the product does not know the
    customer's."""
    return os.environ.get("BROLL_DEFAULT_COLLECTION_LABEL", "").strip() or "Our Footage"


# Module-level for the many call sites that compare against it. Read at import
# like every other get_*() default in this file; the env is set by the compose
# file, which a deploy re-renders.
COLLECTION_CREATORS = get_creators_collection()
COLLECTION_LABELS = {COLLECTION_DOWNLOADS: "Downloads",
                     COLLECTION_CREATORS: get_creators_collection_label()}


def normalise_collection(value) -> str:
    """A ?collection= value as this deployment spells it, or "" for "no
    filter". The legacy `creators_club` maps onto whatever the own-footage
    collection is called here -- an editor's bookmark must not silently turn
    into "show me everything"."""
    value = str(value or "").strip().lower()
    if value == LEGACY_COLLECTION_CREATORS:
        return COLLECTION_CREATORS
    if value in (COLLECTION_DOWNLOADS, COLLECTION_CREATORS):
        return value
    return ""


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


def get_archive_creators_dir() -> str:
    """The top-level folder own-footage shoots live in, inside the archive
    tree: `<archive root>/Creators_Club/<share>/<shoot dirs>/`.

    It is a LITERAL in the indexer (`build_archive.CREATORS`) and every one of
    the ~7,000 files already published sits under it, so the default cannot
    change without moving them. But the name is one customer's, and
    COMMERCIAL_READINESS.md item 4/10 is explicit that a second customer must
    not have to fork code to be called something else -- so ingest, which is
    NEW writes only, takes it from the environment with the historical value as
    the default. Sanitised like any other path component: it is joined into an
    archive path that a companion then hands to rclone.
    """
    raw = os.environ.get("BROLL_ARCHIVE_CREATORS_DIR", "").strip()
    if not raw:
        return "Creators_Club"
    # Imported here, not at module scope: config is imported by everything and
    # archive_names imports nothing, but the cycle is not worth risking for a
    # value read once per claim.
    from app.archive_names import safe_name

    return safe_name(raw.replace("/", "_").replace("\\", "_"))


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


# --- client folders (docs/CLIENT_FOLDERS.md, 2026-08-18) -------------------------

def get_org_name() -> str:
    """Whose footage the public client page says it is showing.

    DASH_SITE_ORG_NAME is what the dashboard container already carries for its
    own brand strings (settings.site_org_name); read here by environment for
    the same reason DASH_SESSION_SECRET is -- this app is deployed as its own
    tree and cannot import ccsync_dashboard. Blank falls back to the product
    name, never to a customer's (COMMERCIAL_READINESS.md item 10).
    """
    return os.environ.get("DASH_SITE_ORG_NAME", "").strip() or "CC Sync"
