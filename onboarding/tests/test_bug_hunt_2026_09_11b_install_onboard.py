"""Bug hunt 2026-09-11b, install-onboard territory (CR-265).

The hunt was OF the 2026-09-11 fix pass, so every test here is about a fix
that landed half of itself:

- install-onboard-1: site_manifest_value fell back to the cache PER KEY and
  with no bound and no identity, so a manifest this run fetched successfully
  could still be completed from a cache written by a different deployment,
  and the mixed pair went on argv where it beat the bootstrap's own later
  fetch.
- install-onboard-5: the new "8443 means TLS" rule is a property of this
  studio's Tailscale Funnel, not of the port number.

Nothing here may depend on the developer's own ~/.ccsync: cached_site is
always substituted.
"""

from __future__ import annotations

import pytest

import steps
from ccsync_companion import site as site_mod


# -- install-onboard-1: the cache is a FALLBACK, not a filler ------------------

# What a previous onboarding to a different deployment left behind.
OLD_SITE = {
    "canonical_prefix": "Q:\\",
    "tree_name": "Pool",
    "dashboard_url": "https://old-nas.tailabc.ts.net",
}


def _cache(monkeypatch, payload, seen=None):
    def cached_site(*args, **kwargs):
        if seen is not None:
            seen.append(dict(kwargs))
        return dict(payload) if payload is not None else None
    monkeypatch.setattr(site_mod, "cached_site", cached_site)


def test_a_fetched_manifest_is_never_completed_from_the_cache(monkeypatch):
    """A dashboard that publishes no tree_name (site.normalise fills every
    absent string key with "") used to hand the bootstrap this run's
    canonical_prefix and SOME OTHER deployment's tree name."""
    _cache(monkeypatch, OLD_SITE)
    site = {"canonical_prefix": "R:\\", "tree_name": ""}
    # No dashboard_url on purpose: this must fail on the old code for the
    # MECHANISM (a per-key cache fallback), not because the parameter that
    # carries the other half of the fix does not exist yet (tests-5).
    assert steps.site_manifest_value(site, "canonical_prefix") == "R:\\"
    assert steps.site_manifest_value(site, "tree_name") == ""


def test_a_cache_from_another_dashboard_is_ignored(monkeypatch):
    _cache(monkeypatch, OLD_SITE)
    assert steps.site_manifest_value(
        None, "canonical_prefix",
        dashboard_url="https://new-nas.tailxyz.ts.net") == ""


def test_a_cache_from_the_same_dashboard_is_still_used(monkeypatch):
    _cache(monkeypatch, OLD_SITE)
    for typed in ("https://old-nas.tailabc.ts.net",
                  "old-nas.tailabc.ts.net",
                  "https://OLD-NAS.tailabc.ts.net/"):
        assert steps.site_manifest_value(
            None, "canonical_prefix", dashboard_url=typed) == "Q:\\", typed


def test_a_cache_that_names_no_dashboard_is_still_used(monkeypatch):
    """Only a PROVEN mismatch refuses: an older dashboard publishes no
    dashboard_url at all, and refusing there would undo install-onboard-2."""
    _cache(monkeypatch, {"canonical_prefix": "Q:\\", "tree_name": "Pool"})
    assert steps.site_manifest_value(
        None, "canonical_prefix", dashboard_url="https://new.tailxyz.ts.net") == "Q:\\"


def test_the_cache_read_is_bounded(monkeypatch):
    seen = []
    _cache(monkeypatch, OLD_SITE, seen=seen)
    steps.site_manifest_value(None, "canonical_prefix",
                              dashboard_url="https://old-nas.tailabc.ts.net")
    assert seen and seen[0].get("max_age_seconds"), (
        "cached_site is called with no age bound: an unbounded cache is "
        "install-onboard-1")
    assert seen[0]["max_age_seconds"] == steps.SITE_CACHE_MAX_AGE_SECONDS


def test_run_bootstrap_passes_the_url_it_signed_in_to(tmp_path, monkeypatch):
    """The end to end shape: a failed fetch on deployment B must not hand
    deployment A's letter to the bootstrap, which then skips its own fetch."""
    _cache(monkeypatch, OLD_SITE)
    calls = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def run(cmd, **kwargs):
        calls.append((list(cmd), dict(kwargs.get("env") or {})))
        return _Result()

    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# stand-in", encoding="utf-8")
    steps.run_bootstrap(
        editor_name="jane", dashboard_token="t", tailnet_host="new-nas",
        dashboard_url="https://new-nas.tailxyz.ts.net", site=None,
        platform="win32", script_path=str(script), run=run)
    assert "-CanonicalPrefix" not in calls[0][0]
    assert "-TreeName" not in calls[0][0]


def test_an_unreadable_cache_is_still_not_fatal(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("~/.ccsync is not readable")

    monkeypatch.setattr(site_mod, "cached_site", boom)
    assert steps.site_manifest_value(None, "tree_name",
                                     dashboard_url="https://nas.ts.net") == ""


# -- install-onboard-5: 8443 is THIS deployment's Funnel port ------------------

@pytest.mark.parametrize("typed,expected", [
    # A tailnet name is TLS on every port Serve/Funnel fronts.
    ("nas.tail26290e.ts.net:8443", "https://nas.tail26290e.ts.net:8443"),
    ("nas.tail26290e.ts.net:8480", "https://nas.tail26290e.ts.net:8480"),
    # 443 is https everywhere, and a bare name is https by convention.
    ("dash.studio.internal:443", "https://dash.studio.internal:443"),
    ("dash.studio.internal", "https://dash.studio.internal"),
    # install-onboard-5 (2026-09-11b): 8443 on somebody else's hostname is a
    # plain container port as often as it is a TLS one, and guessing https
    # there writes a URL that cannot connect into config.toml and into the
    # companion's loopback origin allow-list.
    ("dash.studio.internal:8443", "http://dash.studio.internal:8443"),
    ("dash.example.com:8480", "http://dash.example.com:8480"),
    ("192.168.0.104:8443", "http://192.168.0.104:8443"),
    ("localhost:8443", "http://localhost:8443"),
])
def test_8443_means_tls_only_where_this_fleet_publishes_it(typed, expected):
    assert steps.normalise_dashboard_url(typed) == expected
