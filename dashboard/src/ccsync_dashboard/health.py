"""Pure status-rollup logic. Precedence everywhere: red > amber > green.

An editor's dot answers "do I need to chase this person": red means broken or
stuck (lane error, offline while behind, or the data itself has gone stale),
amber means work in flight, green means fully synced and quiet.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .db import age_seconds

GREEN = "green"
AMBER = "amber"
RED = "red"

_ORDER = {GREEN: 0, AMBER: 1, RED: 2}

OFFLINE_RED_SECONDS = 15 * 60
STALE_COMPLETION_SECONDS = 5 * 60
STALE_REPORT_SECONDS = 5 * 60


def worst(statuses: Iterable[str]) -> str:
    result = GREEN
    for s in statuses:
        if _ORDER.get(s, 0) > _ORDER[result]:
            result = s
    return result


def presence_status(mode: str, nas: Mapping[str, int], have: Mapping[str, int]) -> str:
    """Role-aware media-presence color for one editor on one project.

    Remote editors are *meant* to have proxies but not originals, so
    proxy-only is green; missing proxies (with proxies existing on the NAS)
    is amber. The base rig is meant to hold the originals, so missing
    originals is red. `nas` and `have` are {n_originals, n_proxies} counts.
    """
    nas_orig = nas.get("n_originals", 0)
    nas_prox = nas.get("n_proxies", 0)
    have_orig = have.get("n_originals", 0)
    have_prox = have.get("n_proxies", 0)
    if mode == "base":
        if nas_orig and have_orig < nas_orig:
            return RED           # the authoritative copy is incomplete
        return GREEN
    # editor: proxies are what matters; originals optional (proxy-only is fine)
    if nas_prox == 0:
        return GREEN             # nothing to pull yet
    if have_prox >= nas_prox:
        return GREEN
    if have_prox == 0:
        return AMBER             # not started
    return AMBER                 # partial


def is_proxy_only(have: Mapping[str, int]) -> bool:
    return have.get("n_originals", 0) == 0 and have.get("n_proxies", 0) > 0


def editor_status(
    *,
    completion: float | None,
    need_items: int | None,
    connected: bool,
    last_connected_at: str | None,
    completion_updated_at: str | None,
    syncthing_reachable: bool,
    lanes: Iterable[Mapping[str, Any]] = (),
    now: str,
) -> str:
    """Status of one editor device within one project.

    `lanes` are this editor's lane_report_current rows (any project -- lane
    A/B state is per-editor, not per-project).
    """
    lane_states = [l["state"] for l in lanes]
    if "error" in lane_states:
        return RED

    behind = bool(need_items) or (completion is not None and completion < 100)
    if behind and not connected:
        if last_connected_at is None or age_seconds(last_connected_at, now) >= OFFLINE_RED_SECONDS:
            return RED
    if (
        syncthing_reachable
        and completion_updated_at is not None
        and age_seconds(completion_updated_at, now) >= STALE_COMPLETION_SECONDS
    ):
        return RED

    if behind or "syncing" in lane_states:
        return AMBER
    return GREEN


def project_status(editor_statuses: Iterable[str]) -> str:
    return worst(editor_statuses)


def fleet_status(project_statuses: Iterable[str]) -> str:
    return worst(project_statuses)


def lane_chip_status(lane: Mapping[str, Any], now: str) -> str:
    """Dot color for a single reported lane, factoring in report freshness."""
    if lane["state"] == "error":
        return RED
    if age_seconds(lane["received_at"], now) >= STALE_REPORT_SECONDS * 3:
        return RED  # companion silent for 15+ minutes
    if lane["state"] == "syncing":
        return AMBER
    return GREEN
