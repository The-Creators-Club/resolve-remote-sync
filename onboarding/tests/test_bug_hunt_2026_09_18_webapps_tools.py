"""Bug hunt 2026-09-18, the onboarding half of webapps-tools (CR-286).

install-onboard-4: `_same_dashboard` reduced both URLs to a hostname, so a
host fronting two deployments - a customer's staging and production container
on one NAS, or a move from the container port to a Funnel port - counted as
one dashboard and the OTHER one's cached `canonical_prefix` / `tree_name` went
onto the bootstrap's argv, where they beat its own fetch.

Nothing here may depend on the developer's own ~/.ccsync: cached_site is
always substituted.
"""

from __future__ import annotations

import steps
from ccsync_companion import site as site_mod

OLD_SITE = {
    "canonical_prefix": "Q:\\",
    "tree_name": "Pool",
    "dashboard_url": "https://nas.tailabc.ts.net:8480",
}


def _cache(monkeypatch, payload):
    monkeypatch.setattr(site_mod, "cached_site",
                        lambda *a, **k: dict(payload))


def test_two_dashboards_on_one_host_are_not_the_same_deployment(monkeypatch):
    _cache(monkeypatch, OLD_SITE)
    assert steps.site_manifest_value(
        None, "canonical_prefix",
        dashboard_url="https://nas.tailabc.ts.net:8481") == ""
    assert steps.site_manifest_value(
        None, "tree_name",
        dashboard_url="https://nas.tailabc.ts.net:8481") == ""


def test_the_same_dashboard_on_the_same_port_is_still_the_same(monkeypatch):
    _cache(monkeypatch, OLD_SITE)
    for typed in ("https://nas.tailabc.ts.net:8480",
                  "nas.tailabc.ts.net:8480",
                  "https://NAS.tailabc.ts.net:8480/"):
        assert steps.site_manifest_value(
            None, "canonical_prefix", dashboard_url=typed) == "Q:\\", typed


def test_a_port_nobody_named_means_cannot_tell_which_means_allow(monkeypatch):
    """The blank rule, extended to the port: only two explicitly different
    ports are a refusal, or this regresses the cache path the guard exists to
    keep working (install-onboard-2)."""
    _cache(monkeypatch, {"canonical_prefix": "Q:\\", "tree_name": "Pool",
                         "dashboard_url": "nas.tailabc.ts.net"})
    assert steps.site_manifest_value(
        None, "canonical_prefix",
        dashboard_url="https://nas.tailabc.ts.net:8480") == "Q:\\"


def test_a_different_host_is_still_a_different_deployment(monkeypatch):
    _cache(monkeypatch, OLD_SITE)
    assert steps.site_manifest_value(
        None, "canonical_prefix",
        dashboard_url="https://other.tailabc.ts.net:8480") == ""
