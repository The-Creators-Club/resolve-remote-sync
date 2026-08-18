"""Read `indexer.model_tier` off the dashboard's public site manifest, for a
site whose config.yaml does not say which local tier to use.

    GET {dashboard_url}/api/v1/site  ->  200, unauthenticated, NO SECRETS
    {"schema": 1, ..., "indexer": {"model_tier": "good" | "best"}}

Mirrors the shape and never-raise posture of
`companion/src/ccsync_companion/site.py`'s manifest fetch, but is its own tiny
implementation: the indexer does not depend on the companion package, and this
needs exactly one field out of the manifest. `"indexer"` is additive — a
dashboard that predates it (or one this agent's sibling hasn't shipped yet)
simply omits the key, which reads as "not set" per CLAUDE.md's task, not as an
error.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from .local_models import VALID_TIERS

logger = logging.getLogger(__name__)

SITE_PATH_SUFFIX = "/api/v1/site"
FETCH_TIMEOUT = 5.0

# The indexer's ingest client (storage/http_backend.py) points db.url at the
# dashboard's mounted ingest API, e.g. "https://dash.example.ts.net/broll/api"
# (dashboard/src/ccsync_dashboard/broll.py mounts b-roll at /broll). Stripping
# one of these known suffixes recovers the dashboard's own root without a
# second config key on sites that already have db.mode: api. A URL that
# doesn't end in one of these is left alone — better an explicit
# `indexer.dashboard_url` than a guess that 404s silently.
_INGEST_URL_SUFFIXES = ("/broll/api", "/api")


def dashboard_url_from_config(cfg: Any) -> str:
    """The dashboard base URL to ask for the site manifest, or "" when none is
    configured or derivable. `indexer.dashboard_url` always wins when set."""
    explicit = (getattr(cfg.indexer, "dashboard_url", "") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    if getattr(cfg.db, "mode", None) == "api" and cfg.db.url:
        url = cfg.db.url.strip().rstrip("/")
        for suffix in _INGEST_URL_SUFFIXES:
            if url.endswith(suffix):
                return url[: -len(suffix)]
    return ""


def fetch_model_tier(
    dashboard_url: str, *, opener: Callable[..., Any] = urlopen, timeout: float = FETCH_TIMEOUT
) -> str | None:
    """`indexer.model_tier` from the dashboard's site manifest, or None.

    None covers every reason this might not work: no dashboard configured, the
    dashboard is unreachable, it predates the `indexer` manifest key, or the
    value it sent is not a recognised tier. Never raises — a customer's
    indexing run must not fail because the dashboard was briefly unreachable.
    """
    base = (dashboard_url or "").strip()
    if not base:
        return None
    url = base.rstrip("/") + SITE_PATH_SUFFIX
    try:
        with opener(Request(url), timeout=timeout) as resp:
            body = resp.read()
    except (URLError, OSError, ValueError) as e:
        logger.info("dashboard_site: could not fetch %s: %s", url, e)
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.info("dashboard_site: %s did not return JSON: %s", url, e)
        return None
    if not isinstance(data, dict):
        return None
    indexer = data.get("indexer")
    if not isinstance(indexer, dict):
        return None
    tier = indexer.get("model_tier")
    if isinstance(tier, str) and tier.strip().lower() in VALID_TIERS:
        return tier.strip().lower()
    return None


def resolve_model_tier(
    cfg: Any,
    cli_tier: str | None = None,
    *,
    fetch: Callable[[str], "str | None"] = fetch_model_tier,
) -> str:
    """CLI `--tier` > config.yaml `indexer.model_tier` > dashboard manifest >
    default "good" — CLAUDE.md's task, precedence order verbatim.
    """
    if cli_tier:
        cli_tier = cli_tier.strip().lower()
        if cli_tier not in VALID_TIERS:
            raise ValueError(f"--tier must be one of {', '.join(VALID_TIERS)}, got {cli_tier!r}")
        return cli_tier
    if cfg.indexer.model_tier_explicit:
        return cfg.indexer.model_tier
    manifest_tier = fetch(dashboard_url_from_config(cfg))
    if manifest_tier:
        return manifest_tier
    return cfg.indexer.model_tier
