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

# UX-2 (resilience sweep 2026-08-28). There are three one-click ways for an
# editor to stop syncing for ever -- Settings -> WIRED TO THE SERVER (which
# writes sync_enabled=False), SIGN OUT (which stops the lanes AND the
# reporting, because editor_identity() then returns None) and Quit -- and an
# editor who was CAUGHT UP when they clicked has behind=False, so neither the
# offline branch nor the stale-completion branch below fires. The dot the
# owner scans stayed GREEN for a machine that had been dark for a week.
#
# So freshness is its own rule, independent of `behind`: a companion reports
# every 30 s, so 15 minutes of silence is already three times the staleness
# the lane chips redden at, and six hours is a machine nobody is going to
# notice any other way.
STALE_EDITOR_AMBER_SECONDS = 3 * STALE_REPORT_SECONDS
STALE_EDITOR_RED_SECONDS = 6 * 60 * 60


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


def report_freshness(last_report_at: str | None, now: str) -> tuple[str, str | None]:
    """(colour, reason) for how long ago this machine's companion last reported.

    `last_report_at` None means "this device has no companion row at all",
    which is NOT an amber machine -- it is an unmapped Syncthing device, and
    the grid says so with its own `unmapped` flag. Anything else is measured:
    a timestamp that will not parse comes back AMBER with the reason naming
    it, never green (UX-2, resilience sweep 2026-08-28).
    """
    if last_report_at is None:
        return GREEN, None
    try:
        age = age_seconds(last_report_at, now)
    except (ValueError, TypeError):
        return AMBER, "the last report time on record cannot be read"
    if age >= STALE_EDITOR_RED_SECONDS:
        return RED, f"no report since {last_report_at}"
    if age >= STALE_EDITOR_AMBER_SECONDS:
        return AMBER, f"no report since {last_report_at}"
    return GREEN, None


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
    last_report_at: str | None = None,
) -> str:
    """Status of one editor device within one project.

    `lanes` are this editor's lane_report_current rows (any project -- lane
    A/B state is per-editor, not per-project).

    `last_report_at` is when that companion last reported at all. It is read
    INDEPENDENTLY of `behind` (UX-2): an editor who was caught up when they
    signed out, quit, or set the machine to WIRED TO THE SERVER is behind
    nothing and connected to nothing, and every other branch here says green.
    """
    lane_states = [l["state"] for l in lanes]
    if "error" in lane_states:
        return RED

    freshness, _reason = report_freshness(last_report_at, now)
    if freshness == RED:
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

    if behind or "syncing" in lane_states or freshness == AMBER:
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
