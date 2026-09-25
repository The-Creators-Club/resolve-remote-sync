"""How a report reached the dashboard: `machine_state.report_via` (LG-4,
docs/LEGAL_GAP_FEATURES_PLAN.md 4.4, 2026-09-25, group G2a).

The rules defended here:

- netclass.classify IS the companion's transport.classify: the companion's
  module is loaded by path and the two are run on the same table and the same
  DNS answers. A drift here would make the dashboard call a machine "public"
  that its own companion would have sent to happily, or the reverse.
- The scheme is X-Forwarded-Proto only from a trusted proxy; from anybody
  else it is the socket's own.
- `report_via` is written by the report itself, and only when it changes.
- Nothing about it can cost a report: an unclassifiable Host writes nothing
  and the report lands.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod, netclass
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

TRANSPORT_PY = (Path(__file__).resolve().parents[2]
                / "companion" / "src" / "ccsync_companion" / "transport.py")

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"
EDITOR = "jsmith"
MACHINE = "EDIT-PC"


def _load_transport():
    if not TRANSPORT_PY.is_file():
        pytest.skip("companion/transport.py is not in this checkout")
    spec = importlib.util.spec_from_file_location("_companion_transport_for_parity",
                                                  TRANSPORT_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def transport():
    return _load_transport()


DNS = {
    "dash.studio.com": ["203.0.113.9", "8.8.4.4"],       # one doc-range: local
    "public.studio.com": ["8.8.8.8", "2001:4860:4860::8888"],
    "split.studio.com": ["192.168.0.10"],
    "tailnet.studio.com": ["100.101.102.103"],
    "mixed.studio.com": ["8.8.8.8", "10.0.0.1"],
    "empty.studio.com": [],
    "garbage.studio.com": ["not-an-ip"],
}


def _fake_resolve(host):
    if host not in DNS:
        raise OSError("no such host")
    return list(DNS[host])


@pytest.fixture
def same_dns(monkeypatch, transport):
    monkeypatch.setattr(transport, "resolve", _fake_resolve)
    monkeypatch.setattr(netclass, "resolve", _fake_resolve)
    transport.clear_cache()
    netclass.clear_cache()
    yield
    transport.clear_cache()
    netclass.clear_cache()


PARITY_TABLE = [
    "https://dash.studio.com", "https://8.8.8.8", "HTTPS://Dash.Studio.COM/",
    "http://127.0.0.1:8480", "http://localhost:8480", "http://[::1]:8480",
    "http://cards.localhost", "http://192.168.0.10:8480", "http://10.0.0.5",
    "http://172.16.4.4", "http://100.64.0.1:8480", "http://100.127.255.254",
    "http://169.254.1.1", "http://[fd7a:115c:a1e0::1]:8480", "http://truenas:8480",
    "http://nas.local", "http://nas.lan:8480", "http://nas.internal",
    "http://nas.home.arpa", "http://nas.tail1234.ts.net", "http://dash.example.com",
    "http://dash.example", "http://dash.test", "http://dash.invalid",
    "http://0.0.0.0", "http://192.0.2.1", "http://8.8.8.8",
    "http://8.8.8.8:8480/api/v1/report", "http://[2001:4860:4860::8888]",
    "http://[::ffff:8.8.8.8]", "", None, 5, "ftp://dash.studio.com",
    "dash.studio.com", "http://", "file:///etc/passwd",
    # the review round's dotless numeric hosts
    "http://134744072", "http://0x08080808", "http://01002004010",
    "http://3232235530", "http://0x7f000001", "http://0", "http://99999999999",
    "http://09",
    # names judged by their resolved addresses
    "http://dash.studio.com", "http://public.studio.com", "http://split.studio.com",
    "http://tailnet.studio.com", "http://mixed.studio.com", "http://empty.studio.com",
    "http://garbage.studio.com", "http://nowhere.studio.com",
]


@pytest.mark.parametrize("url", PARITY_TABLE)
def test_classify_matches_the_companion(url, transport, same_dns):
    assert netclass.classify(url) == transport.classify(url)


def test_host_is_local_matches_the_companion(transport):
    for host in ("truenas", "nas.lan", "8.8.8.8", "2001:4860::8888", "134744072",
                 "100.64.0.1", "dash.studio.com", "", "localhost", "0x7f000001"):
        assert netclass.host_is_local(host) == transport.host_is_local(host), host


def test_the_suffix_lists_match_the_companion(transport):
    assert netclass.LOCAL_SUFFIXES == transport.LOCAL_SUFFIXES
    assert netclass.RESERVED_SUFFIXES == transport.RESERVED_SUFFIXES
    assert netclass.RESERVED_DOMAINS == transport.RESERVED_DOMAINS
    assert netclass.CGNAT == transport.CGNAT


@pytest.mark.parametrize("scheme, host, expected", [
    ("https", "8.8.8.8", "https"),
    ("https", "", "https"),
    ("http", "192.168.0.10:8480", "http_local"),
    ("http", "127.0.0.1:8480", "http_local"),        # loopback records as local
    ("http", "nas.tail1234.ts.net", "http_local"),
    ("http", "8.8.8.8:8480", "http_public"),
    ("http", "[2001:4860:4860::8888]:8480", "http_public"),
    ("http", "public.studio.com", "http_public"),
    ("http", "nowhere.studio.com", "http_local"),    # doubt is never public
    ("http", "", None),
    ("http", "evil@8.8.8.8", None),
    ("ws", "8.8.8.8", None),
    ("", "8.8.8.8", None),
])
def test_report_via(scheme, host, expected, same_dns):
    assert netclass.report_via(scheme, host) == expected


def _request(scheme, peer, headers):
    return SimpleNamespace(url=SimpleNamespace(scheme=scheme),
                           client=SimpleNamespace(host=peer),
                           headers={k.lower(): v for k, v in headers.items()})


def test_forwarded_proto_counts_only_from_a_trusted_proxy():
    settings = Settings(trusted_proxies="127.0.0.1/32")
    trusted = _request("http", "127.0.0.1",
                       {"host": "8.8.8.8", "x-forwarded-proto": "https"})
    stranger = _request("http", "8.8.4.4",
                        {"host": "8.8.8.8", "x-forwarded-proto": "https"})
    assert netclass.request_report_via(settings, trusted) == "https"
    assert netclass.request_report_via(settings, stranger) == "http_public"


def test_a_broken_request_is_none_never_a_raise():
    assert netclass.request_report_via(Settings(), object()) is None


# ------------------------------------------------------------- the route


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "via.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def _report(client, **headers):
    body = {"editor_name": EDITOR, "machine": MACHINE, "companion_version": "0.9.80",
            "reported_at": "2026-09-25T10:00:00+00:00",
            "lanes": [{"name": "lane_a_video_up", "state": "idle"}]}
    hdr = {"X-CCSync-Token": TOKEN,
           "X-CCSync-Identity": auth.make_identity_token(SECRET, EDITOR), **headers}
    return client.post("/api/v1/report", json=body, headers=hdr)


def _via(conn):
    row = conn.execute("SELECT report_via FROM machine_state WHERE editor_username=?"
                       " AND machine=?", (EDITOR, MACHINE)).fetchone()
    return None if row is None else row["report_via"]


def test_the_report_records_how_it_arrived(env):
    client, conn = env
    assert _report(client, Host="192.168.0.10:8480").status_code == 200
    assert _via(conn) == "http_local"
    assert _report(client, Host="8.8.8.8:8480").status_code == 200
    assert _via(conn) == "http_public"


def test_it_is_written_only_when_it_changes(env, monkeypatch):
    client, conn = env
    calls = []
    real = dbmod.set_machine_report_via

    def spy(c, e, m, via):
        changed = real(c, e, m, via)
        calls.append(changed)
        return changed

    monkeypatch.setattr(dbmod, "set_machine_report_via", spy)
    for _ in range(3):
        assert _report(client, Host="nas.lan:8480").status_code == 200
    assert calls == [True, False, False]


def test_an_untrusted_forwarded_proto_is_ignored(env):
    client, conn = env
    # TestClient's peer is "testclient", which is no trusted proxy.
    assert _report(client, Host="8.8.8.8", **{"X-Forwarded-Proto": "https"}).status_code == 200
    assert _via(conn) == "http_public"


def test_an_unclassifiable_host_writes_nothing_and_the_report_lands(env):
    client, conn = env
    assert _report(client, Host="").status_code == 200
    assert _via(conn) is None
    assert conn.execute("SELECT COUNT(*) FROM lane_report_current WHERE editor_username=?",
                        (EDITOR,)).fetchone()[0] == 1


# --------------------------------------------------------------- review round
#
# G2a review round, point 3 (2026-09-25): a lookup is bounded in time and in
# number, and the cache is bounded in size.


def test_a_slow_lookup_is_doubt_not_a_stall(monkeypatch):
    import time as _time
    netclass.clear_cache()
    monkeypatch.setattr(netclass, "RESOLVE_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(netclass, "resolve", lambda host: _time.sleep(2) or ["203.0.113.9"])
    started = _time.monotonic()
    assert netclass.report_via("http", "slow.studio-name.net") == "http_local"
    assert _time.monotonic() - started < 1.5
    assert "slow.studio-name.net" not in netclass._cache     # asked again next time


def test_the_cache_is_capped(monkeypatch):
    netclass.clear_cache()
    monkeypatch.setattr(netclass, "RESOLVE_CACHE_MAX", 3)
    monkeypatch.setattr(netclass, "resolve", lambda host: ["93.184.216.34"])
    for i in range(10):
        assert netclass.report_via("http", f"h{i}.studio-name.net") == "http_public"
    assert len(netclass._cache) <= 3
    assert "h9.studio-name.net" in netclass._cache
    netclass.clear_cache()
