"""LG-4, `refuse-cleartext-dashboard-url` (docs/LEGAL_GAP_FEATURES_PLAN.md 4.4).

What is pinned:
- the classification table the settings window, the wizard and the
  dashboard's `netclass.py` parity copy all read;
- the refusal fires only on POSITIVE evidence of a public address, never on
  doubt (split-horizon DNS, a failed lookup: safety H3);
- the guard in the shared opener refuses public http and lets every address
  the live fleet uses through, driven through the REAL urllib chain;
- no module talks HTTP outside that opener except the named, non-dashboard
  exceptions below (the no-stray-opener scan);
- the updater's `_host_is_local` alias and its stricter shape-only rule.
"""

from __future__ import annotations

import ast
import pathlib
import urllib.error
import urllib.request

import pytest

from ccsync_companion import transport
from ccsync_companion import upgrade as upgrade_mod

PACKAGE = pathlib.Path(transport.__file__).resolve().parent


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """No test here may reach a real resolver: a lookup that is not stubbed
    fails the test instead of depending on the network."""
    transport.clear_cache()

    def _unexpected(host):
        raise AssertionError(f"unexpected DNS lookup for {host!r}")

    monkeypatch.setattr(transport, "resolve", _unexpected)
    yield
    transport.clear_cache()


def _resolver(monkeypatch, answers):
    calls = []

    def fake(host):
        calls.append(host)
        answer = answers[host]
        if isinstance(answer, Exception):
            raise answer
        return list(answer)

    monkeypatch.setattr(transport, "resolve", fake)
    return calls


# -- the table -----------------------------------------------------------


@pytest.mark.parametrize("url, expected", [
    # https to anything, including a public name, is https
    ("https://dash.studio.com", "https"),
    ("https://nas.tail1234.ts.net", "https"),
    ("https://8.8.8.8", "https"),
    ("HTTPS://Dash.Studio.COM/", "https"),
    # plain http to this machine
    ("http://127.0.0.1:8480", "loopback"),
    ("http://localhost:8480", "loopback"),
    ("http://[::1]:8480", "loopback"),
    ("http://cards.localhost", "loopback"),
    # the live fleet's addresses and every intranet shape
    ("http://192.168.0.10:8480", "http_local"),
    ("http://10.0.0.5", "http_local"),
    ("http://172.16.4.4", "http_local"),
    ("http://100.64.0.1:8480", "http_local"),       # tailnet CGNAT
    ("http://100.127.255.254", "http_local"),
    ("http://169.254.1.1", "http_local"),
    ("http://[fd7a:115c:a1e0::1]:8480", "http_local"),  # tailnet IPv6 (ULA)
    ("http://truenas:8480", "http_local"),           # single label
    ("http://nas.local", "http_local"),
    ("http://nas.lan:8480", "http_local"),
    ("http://nas.internal", "http_local"),
    ("http://nas.home.arpa", "http_local"),
    ("http://nas.tail1234.ts.net", "http_local"),
    # reserved names: never somebody's public dashboard, never looked up
    ("http://dash.example.com", "http_local"),
    ("http://dash.example", "http_local"),
    ("http://dash.test", "http_local"),
    ("http://dash.invalid", "http_local"),
    # not globally routable IP literals are not evidence of "public"
    ("http://0.0.0.0", "http_local"),
    ("http://192.0.2.1", "http_local"),              # documentation range
    # public IP literals
    ("http://8.8.8.8", "http_public"),
    ("http://8.8.8.8:8480/api/v1/report", "http_public"),
    ("http://[2001:4860:4860::8888]", "http_public"),
    ("http://[::ffff:8.8.8.8]", "http_public"),     # IPv4-mapped
    # nothing to send to
    ("", "invalid"),
    (None, "invalid"),
    (5, "invalid"),
    ("ftp://dash.studio.com", "invalid"),
    ("dash.studio.com", "invalid"),                  # no scheme
    ("http://", "invalid"),
    ("file:///etc/passwd", "invalid"),
])
def test_classify_table(url, expected):
    assert transport.classify(url) == expected


def test_every_answer_is_one_of_the_published_classes():
    for url in ("https://a.b", "http://127.0.0.1", "http://10.0.0.1",
                "http://8.8.8.8", "gopher://x"):
        assert transport.classify(url) in transport.CLASSES


# -- names the shape rule does not know: DNS, positive evidence only -------


def test_a_name_whose_every_address_is_public_is_public(monkeypatch):
    calls = _resolver(monkeypatch, {"dash.studio.com": ["203.0.113.9", "8.8.4.4"]})
    # 203.0.113.9 is TEST-NET-3 (not global), so one of the two is not public
    assert transport.classify("http://dash.studio.com") == "http_local"
    transport.clear_cache()
    calls = _resolver(monkeypatch, {"dash.studio.com": ["8.8.8.8", "2001:4860:4860::8888"]})
    assert transport.classify("http://dash.studio.com:8480/x") == "http_public"
    assert calls == ["dash.studio.com"]


def test_split_horizon_name_resolving_privately_is_local(monkeypatch):
    """A studio's own DNS answering `dashboard.studio.com` with its LAN
    address: the name looks public, the path is not."""
    _resolver(monkeypatch, {"dashboard.studio.com": ["192.168.0.10"]})
    assert transport.classify("http://dashboard.studio.com:8480") == "http_local"


def test_a_name_resolving_to_the_tailnet_is_local(monkeypatch):
    _resolver(monkeypatch, {"nas.studio.com": ["100.101.102.103"]})
    assert transport.classify("http://nas.studio.com") == "http_local"


def test_mixed_public_and_private_answers_are_local(monkeypatch):
    _resolver(monkeypatch, {"dash.studio.com": ["8.8.8.8", "10.1.1.1"]})
    assert transport.classify("http://dash.studio.com") == "http_local"


@pytest.mark.parametrize("answer", [OSError("no such host"), [], ["not-an-ip"]])
def test_a_failed_or_empty_lookup_is_local_never_refused(monkeypatch, answer):
    _resolver(monkeypatch, {"dash.studio.com": answer})
    assert transport.classify("http://dash.studio.com") == "http_local"
    assert transport.is_refused("http://dash.studio.com") is False


def test_lookups_are_cached(monkeypatch):
    calls = _resolver(monkeypatch, {"dash.studio.com": ["8.8.8.8"]})
    for _ in range(5):
        assert transport.classify("http://dash.studio.com") == "http_public"
    assert calls == ["dash.studio.com"]


def test_the_cache_expires(monkeypatch):
    calls = _resolver(monkeypatch, {"dash.studio.com": ["8.8.8.8"]})
    clock = [1000.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: clock[0])
    transport.classify("http://dash.studio.com")
    clock[0] += transport.RESOLVE_TTL_SECONDS - 1
    transport.classify("http://dash.studio.com")
    assert len(calls) == 1
    clock[0] += 2
    transport.classify("http://dash.studio.com")
    assert len(calls) == 2


def test_a_failed_lookup_is_retried_sooner(monkeypatch):
    calls = _resolver(monkeypatch, {"dash.studio.com": OSError("down")})
    clock = [1000.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: clock[0])
    transport.classify("http://dash.studio.com")
    clock[0] += transport.RESOLVE_FAIL_TTL_SECONDS + 1
    transport.classify("http://dash.studio.com")
    assert len(calls) == 2


def test_https_never_looks_anything_up():
    # the autouse fixture fails on any lookup
    assert transport.classify("https://dash.studio.com") == "https"


# -- the guard, through the real urllib chain -----------------------------


class _Recorder(urllib.request.BaseHandler):
    """Stands in for the network: records what would have been sent.
    Ordered before the default HTTP(S)Handler, which would otherwise win the
    tie and really connect."""

    handler_order = 100

    def __init__(self):
        self.sent = []

    def _answer(self, req):
        import http.client
        import io
        import urllib.response
        self.sent.append(req.get_full_url())
        headers = http.client.HTTPMessage()
        resp = urllib.response.addinfourl(io.BytesIO(b"{}"), headers,
                                          req.get_full_url(), 200)
        resp.msg = "OK"
        return resp

    http_open = _answer
    https_open = _answer


@pytest.mark.parametrize("url", [
    "http://8.8.8.8:8480/api/v1/report",
    "http://[2001:4860:4860::8888]/api/v1/verify",
])
def test_the_shared_opener_refuses_public_http_before_sending(url):
    recorder = _Recorder()
    opener = upgrade_mod.build_no_redirect_opener(recorder)
    req = urllib.request.Request(url, data=b"{}", headers={"X-CCSync-Token": "t"},
                                 method="POST")
    with pytest.raises(transport.CleartextRefused) as excinfo:
        opener.open(req, timeout=5)
    assert recorder.sent == []
    # A URLError, so every caller's "could not reach the dashboard" path
    # (and its never-raise contract) handles it unchanged.
    assert isinstance(excinfo.value, urllib.error.URLError)
    assert excinfo.value.url == url


def test_a_public_name_is_refused_on_dns_evidence(monkeypatch):
    _resolver(monkeypatch, {"dash.studio.com": ["8.8.8.8"]})
    recorder = _Recorder()
    opener = upgrade_mod.build_no_redirect_opener(recorder)
    with pytest.raises(transport.CleartextRefused):
        opener.open("http://dash.studio.com/api/v1/report", timeout=5)
    assert recorder.sent == []


@pytest.mark.parametrize("url", [
    "https://8.8.8.8/api/v1/report",
    "https://dash.studio.com/api/v1/report",
    "http://127.0.0.1:8480/api/v1/report",
    "http://192.168.0.10:8480/api/v1/report",
    "http://100.64.0.1:8480/api/v1/report",
    "http://truenas:8480/api/v1/report",
    "http://nas.tail1234.ts.net/api/v1/report",
    "http://dash.example.com/api/v1/report",
])
def test_the_shared_opener_passes_every_fleet_shaped_address(url):
    recorder = _Recorder()
    opener = upgrade_mod.build_no_redirect_opener(recorder)
    with opener.open(url, timeout=5) as resp:
        assert resp.status == 200
    assert recorder.sent == [url]


def test_a_split_horizon_or_unresolvable_name_is_sent(monkeypatch):
    _resolver(monkeypatch, {"dashboard.studio.com": ["192.168.0.10"],
                            "gone.studio.com": OSError("nxdomain")})
    recorder = _Recorder()
    opener = upgrade_mod.build_no_redirect_opener(recorder)
    opener.open("http://dashboard.studio.com:8480/x", timeout=5).close()
    opener.open("http://gone.studio.com:8480/x", timeout=5).close()
    assert len(recorder.sent) == 2


def test_the_guard_still_refuses_redirects():
    """The guard joined the chain; it did not replace NoRedirectHandler."""
    names = [type(h).__name__ for h in upgrade_mod.build_no_redirect_opener().handlers]
    assert "NoRedirectHandler" in names
    assert "CleartextGuard" in names


@pytest.fixture
def _network(monkeypatch):
    """Every opener the package builds gets the recorder in front of the real
    HTTP handlers, so the production call functions run end to end."""
    recorder = _Recorder()
    real_build = urllib.request.build_opener
    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *h: real_build(recorder, *h))
    return recorder


def test_every_fleet_call_function_is_guarded(_network):
    """The production transports of every module that sends the fleet
    credential: reporter (and identity, which posts through it), selection,
    site, broll_ingest.default_request (jobs_runner, server_locate and the
    Timeline Cards tunnel all default to it), ytdl_executor, ytdlp_manager
    and the updater itself."""
    from ccsync_companion import broll_ingest, reporter, selection, site, ytdlp_manager

    public = "http://8.8.8.8:8480"
    calls = [
        lambda: reporter.default_http_post(f"{public}/api/v1/report", {}, {}, 5),
        lambda: selection.default_http_get(f"{public}/api/v1/selections", {}, 5),
        lambda: site.default_http_open(f"{public}/api/v1/site", 5),
        lambda: broll_ingest.default_request("POST", f"{public}/api/v1/jobs/claim",
                                             {}, {}, 5),
        lambda: ytdlp_manager.default_dashboard_open(f"{public}/api/v1/ytdl", {}, 5),
        lambda: upgrade_mod.default_http_open(f"{public}/pkg", {}, 5),
    ]
    for call in calls:
        with pytest.raises(transport.CleartextRefused):
            call()
    assert _network.sent == []

    # ...and the same functions reach a LAN dashboard untouched.
    lan = "http://192.168.0.10:8480"
    reporter.default_http_post(f"{lan}/api/v1/report", {}, {}, 5)
    broll_ingest.default_request("POST", f"{lan}/api/v1/jobs/claim", {}, {}, 5)
    assert len(_network.sent) == 2


def test_the_jobs_locate_and_cards_clients_default_to_the_guarded_request():
    """jobs_runner, sync/server_locate and timeline_cards_role send the
    fleet credential through `broll_ingest.default_request` when no request
    function is injected: pinned by source, because each imports it lazily."""
    for rel in ("jobs_runner.py", "sync/server_locate.py", "timeline_cards_role.py"):
        text = (PACKAGE / rel).read_text(encoding="utf-8")
        assert "broll_ingest import default_request" in text, rel


# -- no stray opener -------------------------------------------------------

_HTTP_NAMES = {"urlopen", "build_opener", "OpenerDirector",
               "HTTPConnection", "HTTPSConnection"}

# (module, enclosing function) -> why it may open its own connection. None of
# these carries the fleet credential or talks to `dashboard_url`; a new entry
# needs the same justification.
_ALLOWED = {
    ("upgrade.py", "build_no_redirect_opener"): "THE shared opener",
    ("ytdlp_manager.py", "default_github_open"):
        "https-only GitHub release download, redirects pinned to GitHub",
    ("ytdl_browser_login.py", "_http_json"):
        "the local browser's DevTools port on 127.0.0.1",
    ("broll_vlm/local_runtime.py", "<import>"): "local model runtime",
    ("broll_vlm/local_runtime.py", "download_verified"):
        "model weight download, sha256-verified, no credential",
    ("broll_vlm/local_vlm.py", "<import>"): "local VLM server on loopback",
    ("broll_vlm/local_vlm.py", "_health"): "local VLM server on loopback",
    ("broll_vlm/local_vlm.py", "_chat"): "local VLM server on loopback",
    ("broll_vlm/local_vlm.py", "run_window"): "local VLM server on loopback",
    ("broll_vlm/local_vlm.py", "call_local_with_retry"): "local VLM server on loopback",
}


def _http_references():
    found = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))

        def visit(node, fn):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = f"{fn}.{node.name}" if fn else node.name
            if isinstance(node, ast.ImportFrom):
                if any(a.name in _HTTP_NAMES for a in node.names):
                    found.add((rel, "<import>"))
            elif isinstance(node, ast.Attribute) and node.attr in _HTTP_NAMES:
                found.add((rel, fn or "<module>"))
            elif isinstance(node, ast.Name) and node.id in _HTTP_NAMES:
                found.add((rel, fn or "<module>"))
            for child in ast.iter_child_nodes(node):
                visit(child, fn)

        visit(tree, "")
    return found


def test_no_module_opens_http_outside_the_shared_opener():
    stray = sorted(_http_references() - set(_ALLOWED))
    assert not stray, (
        "these open an HTTP connection without upgrade.build_no_redirect_opener "
        "(and so without the LG-4 cleartext guard or the no-redirect rule): "
        f"{stray}")


def test_the_allowlisted_modules_do_not_send_to_the_dashboard():
    for rel in {m for m, _ in _ALLOWED} - {"upgrade.py", "ytdlp_manager.py"}:
        text = (PACKAGE / rel).read_text(encoding="utf-8")
        assert "dashboard_url" not in text, rel
        assert "X-CCSync-Token" not in text, rel


def test_the_allowlist_has_no_dead_entries():
    """An entry whose code is gone would silently excuse a future one."""
    assert set(_ALLOWED) <= _http_references()


# -- the updater -----------------------------------------------------------


def test_the_updater_alias_is_the_moved_function():
    assert upgrade_mod._host_is_local is transport.host_is_local


@pytest.mark.parametrize("host, local", [
    ("localhost", True), ("truenas", True), ("nas.local", True),
    ("nas.lan", True), ("nas.internal", True), ("nas.home.arpa", True),
    ("x.ts.net", True), ("100.64.0.1", True), ("192.168.0.10", True),
    ("[::1]", True), ("fe80::1%eth0", True),
    ("8.8.8.8", False), ("dash.studio.com", False), ("", False), (None, False),
])
def test_host_is_local_shape_rule(host, local):
    assert transport.host_is_local(host) is local


def test_the_updater_stays_stricter_than_the_guard(monkeypatch):
    """transport_ok refuses a cleartext PUBLIC-LOOKING name by shape, with no
    lookup, even one the guard would let through on split-horizon DNS: the
    updater pulls a binary, and it vouches only for names it can see are
    local."""
    ok, _ = upgrade_mod.transport_ok("http://dash.studio.com")
    assert ok is False


def test_transport_is_a_leaf_module():
    """The wizard and the dashboard's parity test load it standalone (plan
    7.1): it must import nothing from this package."""
    tree = ast.parse((PACKAGE / "transport.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in transport.py"
            assert not (node.module or "").startswith("ccsync_companion")
        elif isinstance(node, ast.Import):
            assert not any(a.name.startswith("ccsync_companion") for a in node.names)


# -- review round 2026-09-25 -------------------------------------------------


def test_a_network_change_is_noticed_within_thirty_seconds(monkeypatch):
    """Split-horizon DNS in the studio answers the LAN address; the same
    name on cafe Wi-Fi answers the studio's public port forward. A verdict
    cached for plan 4.4's 600 s let cleartext go out for ten minutes after
    the laptop moved."""
    answers = {"dashboard.studio.com": ["192.168.0.10"]}
    _resolver(monkeypatch, answers)
    clock = [1000.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: clock[0])
    recorder = _Recorder()
    opener = upgrade_mod.build_no_redirect_opener(recorder)
    url = "http://dashboard.studio.com:8480/api/v1/report"
    assert transport.classify(url) == "http_local"
    answers["dashboard.studio.com"] = ["8.8.8.8"]
    clock[0] += 31
    with pytest.raises(transport.CleartextRefused):
        opener.open(urllib.request.Request(url, data=b"{}", method="POST"), timeout=5)
    assert recorder.sent == []
    assert transport.RESOLVE_TTL_SECONDS <= 30
    assert transport.RESOLVE_FAIL_TTL_SECONDS <= 30


@pytest.mark.parametrize("url, expected", [
    ("http://134744072:8480", "http_public"),     # 8.8.8.8, decimal
    ("http://0x08080808", "http_public"),         # 8.8.8.8, hex
    ("http://01002004010", "http_public"),        # 8.8.8.8, octal
    ("http://3232235530:8480", "http_local"),     # 192.168.0.10
    ("http://0x7f000001", "http_local"),          # 127.0.0.1
    ("http://0", "http_local"),                   # 0.0.0.0
    ("http://99999999999", "http_local"),         # > 2**32: a name, not an address
    ("http://09", "http_local"),                  # not octal: a name
])
def test_dotless_numeric_hosts_are_judged_as_addresses(url, expected):
    # the autouse fixture fails on any lookup: none of these may resolve
    assert transport.classify(url) == expected


@pytest.mark.parametrize("url", ["http://134744072:8480", "http://0x08080808"])
def test_the_updater_refuses_dotless_public_literals(url):
    ok, _ = upgrade_mod.transport_ok(url)
    assert ok is False
    assert transport.host_is_local(url.split("//")[1].split(":")[0]) is False


def test_the_refusal_reason_carries_no_ticket_id_and_the_log_does(caplog):
    recorder = _Recorder()
    opener = upgrade_mod.build_no_redirect_opener(recorder)
    with caplog.at_level("WARNING", logger=transport.__name__):
        with pytest.raises(transport.CleartextRefused) as excinfo:
            opener.open("http://8.8.8.8:8480/api/v1/report", timeout=5)
    assert "LG-4" not in str(excinfo.value)
    assert "LG-4" not in str(excinfo.value.reason)
    assert "8.8.8.8" in str(excinfo.value.reason)
    assert any("LG-4" in r.getMessage() for r in caplog.records)
