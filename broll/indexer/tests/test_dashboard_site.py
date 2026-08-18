"""dashboard_site.py: deriving the dashboard URL from db.url, fetching
`indexer.model_tier` from `/api/v1/site` (never raising), and the CLI >
config.yaml > dashboard manifest > default precedence."""
from __future__ import annotations

import json

import pytest

from broll_index import dashboard_site
from broll_index.config import Config, DbConfig, IndexerConfig, SamplingConfig


def _cfg(*, backend="local", model_tier="good", model_tier_explicit=False,
        dashboard_url="", db_mode="sqlite", db_url=None) -> Config:
    return Config(
        shares={}, data_root="/data", db=DbConfig(mode=db_mode, path="/x.db", url=db_url),
        sampling=SamplingConfig(),
        indexer=IndexerConfig(backend=backend, model_tier=model_tier,
                              model_tier_explicit=model_tier_explicit, dashboard_url=dashboard_url),
    )


# ---------------------------------------------------------------------------
# dashboard_url_from_config
# ---------------------------------------------------------------------------

def test_explicit_dashboard_url_wins():
    cfg = _cfg(dashboard_url="https://explicit.example.ts.net/", db_mode="api",
              db_url="https://dash.example.ts.net/broll/api")
    assert dashboard_site.dashboard_url_from_config(cfg) == "https://explicit.example.ts.net"


def test_derives_from_broll_api_ingest_url():
    cfg = _cfg(db_mode="api", db_url="https://dash.example.ts.net/broll/api")
    assert dashboard_site.dashboard_url_from_config(cfg) == "https://dash.example.ts.net"


def test_derives_from_bare_api_ingest_url():
    cfg = _cfg(db_mode="api", db_url="https://dash.example.ts.net/api")
    assert dashboard_site.dashboard_url_from_config(cfg) == "https://dash.example.ts.net"


def test_no_url_when_sqlite_mode_and_no_explicit_url():
    cfg = _cfg(db_mode="sqlite")
    assert dashboard_site.dashboard_url_from_config(cfg) == ""


def test_no_url_when_api_url_does_not_match_a_known_suffix():
    cfg = _cfg(db_mode="api", db_url="https://dash.example.ts.net/something-else")
    assert dashboard_site.dashboard_url_from_config(cfg) == ""


# ---------------------------------------------------------------------------
# fetch_model_tier
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_model_tier_reads_the_indexer_key():
    def opener(req, timeout=None):
        assert req.full_url == "https://dash.example.ts.net/api/v1/site"
        return _FakeResp(json.dumps({"schema": 1, "indexer": {"model_tier": "best"}}).encode())

    assert dashboard_site.fetch_model_tier("https://dash.example.ts.net", opener=opener) == "best"


def test_fetch_model_tier_no_dashboard_url_returns_none():
    assert dashboard_site.fetch_model_tier("", opener=lambda *a, **k: 1 / 0) is None


def test_fetch_model_tier_older_dashboard_with_no_indexer_key_returns_none():
    def opener(req, timeout=None):
        return _FakeResp(json.dumps({"schema": 1}).encode())

    assert dashboard_site.fetch_model_tier("https://dash.example.ts.net", opener=opener) is None


def test_fetch_model_tier_invalid_tier_value_returns_none():
    def opener(req, timeout=None):
        return _FakeResp(json.dumps({"indexer": {"model_tier": "ultra"}}).encode())

    assert dashboard_site.fetch_model_tier("https://dash.example.ts.net", opener=opener) is None


def test_fetch_model_tier_network_error_returns_none_never_raises():
    from urllib.error import URLError

    def opener(req, timeout=None):
        raise URLError("unreachable")

    assert dashboard_site.fetch_model_tier("https://dash.example.ts.net", opener=opener) is None


def test_fetch_model_tier_non_json_body_returns_none():
    def opener(req, timeout=None):
        return _FakeResp(b"<html>not json</html>")

    assert dashboard_site.fetch_model_tier("https://dash.example.ts.net", opener=opener) is None


# ---------------------------------------------------------------------------
# resolve_model_tier precedence: CLI > config.yaml > manifest > default
# ---------------------------------------------------------------------------

def test_resolve_prefers_cli_tier_over_everything():
    cfg = _cfg(model_tier="good", model_tier_explicit=True)
    tier = dashboard_site.resolve_model_tier(cfg, "best", fetch=lambda url: "good")
    assert tier == "best"


def test_resolve_prefers_explicit_config_over_manifest():
    cfg = _cfg(model_tier="best", model_tier_explicit=True)
    tier = dashboard_site.resolve_model_tier(cfg, None, fetch=lambda url: "good")
    assert tier == "best"


def test_resolve_falls_back_to_manifest_when_config_did_not_say():
    cfg = _cfg(model_tier="good", model_tier_explicit=False)
    tier = dashboard_site.resolve_model_tier(cfg, None, fetch=lambda url: "best")
    assert tier == "best"


def test_resolve_falls_back_to_default_when_manifest_has_nothing_either():
    cfg = _cfg(model_tier="good", model_tier_explicit=False)
    tier = dashboard_site.resolve_model_tier(cfg, None, fetch=lambda url: None)
    assert tier == "good"


def test_resolve_invalid_cli_tier_raises():
    cfg = _cfg()
    with pytest.raises(ValueError, match="--tier"):
        dashboard_site.resolve_model_tier(cfg, "ultra", fetch=lambda url: None)
