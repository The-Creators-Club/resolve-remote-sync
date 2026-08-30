"""`tools/check_mobile_origin.py` against a fake origin, one test per verdict.

MOBILE_PLAN.md M6, 2026-08-30. The checker is what an admin runs after
putting the dashboard behind TLS and before touching a phone, so its
VERDICTS are the product: "OK" on a good origin is worth nothing if it also
says OK on a manifest that 303s to the login page, which is the actual
failure this exists to catch.

No sockets, no server, no certificate. The checker takes its `fetch` as an
argument (module docstring, "ONE FETCH FUNCTION, injected"), so the fake
below answers from a real `TestClient` over the real app for the routes that
exist today, and from a canned table for the three that M4 and M5 are still
building (`/manifest.webmanifest`, `/sw.js`,
`/.well-known/assetlinks.json` -- as planned; see MOBILE_PLAN.md sections 4
M4 and 4 M5). When those land, the canned entries can go and these tests
still describe the same verdicts.

`tools/` is not a package and not on the path, so the checker is loaded by
file path -- the same shape `tools/tests/` uses for the scripts it covers.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32
ORIGIN = "https://nas.tail26290e.ts.net:9443"


def _load_checker():
    path = Path(__file__).resolve().parents[2] / "tools" / "check_mobile_origin.py"
    spec = importlib.util.spec_from_file_location("check_mobile_origin", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


# The three routes M4 and M5 own, answered here the way their plans say they
# will answer. A test that wants the failing shape overrides one of them.
GOOD_MANIFEST = json.dumps({
    "name": "CC Sync", "start_url": "/", "scope": "/", "display": "standalone",
    "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"}],
}).encode()


def canned() -> dict[str, "checker.Response"]:
    R = checker.Response
    return {
        "/manifest.webmanifest": R(200, {"content-type": "application/manifest+json"},
                                   GOOD_MANIFEST),
        "/sw.js": R(200, {"content-type": "application/javascript",
                          "service-worker-allowed": "/"}, b"// sw\n"),
        "/.well-known/assetlinks.json": R(200, {"content-type": "application/json"}, b"[]"),
    }


class Fake:
    """`fetch(url)` over a TestClient, with a canned table in front of it.

    Follows redirects, exactly as `urllib.request.urlopen` does in the real
    `http_fetch` -- which is the whole reason a login-gated manifest reads as
    "not JSON" here rather than as a 303: a browser sees the same thing.
    """

    def __init__(self, client: TestClient, table: dict | None = None,
                 raises: Exception | None = None):
        self.client = client
        self.table = canned() if table is None else table
        self.raises = raises
        self.asked: list[str] = []

    def __call__(self, url: str) -> "checker.Response":
        assert url.startswith(ORIGIN), f"the checker left its origin: {url}"
        path = url[len(ORIGIN):] or "/"
        self.asked.append(path)
        if self.raises is not None:
            raise self.raises
        if path in self.table:
            return self.table[path]
        reply = self.client.get(path, follow_redirects=True)
        return checker.Response(
            status=reply.status_code,
            headers={k.lower(): v for k, v in reply.headers.items()},
            body=reply.content,
            set_cookies=tuple(reply.headers.get_list("set-cookie")),
        )


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET))
    with TestClient(app) as c:
        yield c


def verdicts(results) -> dict[str, str]:
    return {r.name: r.verdict for r in results}


def detail(results, name: str) -> str:
    return next(r.detail for r in results if r.name == name)


# --------------------------------------------------------------- the good run

def test_a_good_origin_passes_every_check(client):
    results = checker.run_checks(ORIGIN, Fake(client))
    assert all(r.ok for r in results), [r.line() for r in results]
    assert [r.name for r in results] == [
        "https", "certificate", "manifest", "service worker", "asset links",
        "health", "cookie secure",
    ]
    # The dashboard's real version, off the real /api/v1/health -- this is
    # the check that proves the origin points at THIS app.
    from ccsync_dashboard import VERSION
    assert VERSION in detail(results, "health")


def test_the_json_output_carries_every_verdict(client, capsys, monkeypatch):
    monkeypatch.setattr(checker, "http_fetch", Fake(client))
    code = checker.main([ORIGIN, "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert code == 0 and doc["ok"] is True
    assert doc["origin"] == ORIGIN
    assert [c["name"] for c in doc["checks"]][0] == "https"


def test_a_trailing_path_is_trimmed_to_the_origin(client):
    # An admin pastes the URL out of the browser, path and all.
    assert checker.normalise(ORIGIN + "/fleet?x=1") == ORIGIN
    assert checker.normalise("nas.tail26290e.ts.net:9443/") == "https://nas.tail26290e.ts.net:9443"


# ------------------------------------------------------------ one FAIL each

def test_plain_http_fails_first_and_stops(client):
    fake = Fake(client)
    results = checker.run_checks("http://nas.local:8480", fake)
    assert [r.name for r in results] == ["https"]
    assert not results[0].ok
    assert fake.asked == [], "nothing should be fetched once the scheme is wrong"


def test_a_bad_certificate_stops_at_the_certificate(client):
    fake = Fake(client, raises=checker.CertificateProblem("self signed certificate"))
    results = checker.run_checks(ORIGIN, fake)
    assert verdicts(results) == {"https": "OK", "certificate": "FAIL"}
    assert "self signed" in detail(results, "certificate")


def test_a_login_gated_manifest_fails(client):
    # THE failure this script exists for, and the state of the tree today:
    # /manifest.webmanifest is not in _OPEN_EXACT yet (M4), so an anonymous
    # fetch follows the 303 and lands on the login page's HTML. Chrome does
    # exactly this and then silently never offers to install.
    table = canned()
    del table["/manifest.webmanifest"]
    results = checker.run_checks(ORIGIN, Fake(client, table))
    assert verdicts(results)["manifest"] == "FAIL"
    assert "not JSON" in detail(results, "manifest")


def test_a_manifest_without_start_url_or_icons_fails(client):
    table = canned()
    table["/manifest.webmanifest"] = checker.Response(200, {}, b'{"name": "CC Sync"}')
    results = checker.run_checks(ORIGIN, Fake(client, table))
    assert verdicts(results)["manifest"] == "FAIL"
    assert "start_url" in detail(results, "manifest") and "icons" in detail(results, "manifest")


def test_a_service_worker_without_the_header_fails(client):
    table = canned()
    table["/sw.js"] = checker.Response(200, {"content-type": "application/javascript"}, b"// sw")
    results = checker.run_checks(ORIGIN, Fake(client, table))
    assert verdicts(results)["service worker"] == "FAIL"
    assert "Service-Worker-Allowed" in detail(results, "service worker")


def test_missing_asset_links_fail_and_an_empty_list_does_not(client):
    table = canned()
    table["/.well-known/assetlinks.json"] = checker.Response(404, {}, b"")
    results = checker.run_checks(ORIGIN, Fake(client, table))
    assert verdicts(results)["asset links"] == "FAIL"
    assert "URL bar" in detail(results, "asset links")
    # The default -- no Android package configured -- is not a fault.
    ok = checker.run_checks(ORIGIN, Fake(client))
    assert verdicts(ok)["asset links"] == "OK"
    assert "no Android package" in detail(ok, "asset links")


def test_something_else_on_the_port_fails_at_health(client):
    table = canned()
    table["/api/v1/health"] = checker.Response(200, {}, b"<html>TrueNAS</html>")
    results = checker.run_checks(ORIGIN, Fake(client, table))
    assert verdicts(results)["health"] == "FAIL"
    assert "not JSON" in detail(results, "health")


def test_health_without_a_version_fails(client):
    table = canned()
    table["/api/v1/health"] = checker.Response(200, {}, b'{"ok": true}')
    results = checker.run_checks(ORIGIN, Fake(client, table))
    assert verdicts(results)["health"] == "FAIL"
    assert "not the dashboard" in detail(results, "health")


# --------------------------------------------------------- the cookie check

def test_a_session_cookie_without_secure_fails(client):
    # The trusted-proxy trap: DASH_COOKIE_SECURE=auto behind a terminator
    # whose address is not in DASH_TRUSTED_PROXIES leaves the flag off, and
    # nothing else anywhere notices.
    table = canned()
    table["/login"] = checker.Response(
        200, {}, b"<html></html>",
        set_cookies=("ccsync_session=abc; HttpOnly; Path=/; SameSite=lax",))
    results = checker.run_checks(ORIGIN, Fake(client, table))
    assert verdicts(results)["cookie secure"] == "FAIL"
    assert "DASH_TRUSTED_PROXIES" in detail(results, "cookie secure")


def test_a_secure_session_cookie_passes(client):
    table = canned()
    table["/login"] = checker.Response(
        200, {}, b"<html></html>",
        set_cookies=("ccsync_session=abc; HttpOnly; Secure; Path=/; SameSite=lax",))
    results = checker.run_checks(ORIGIN, Fake(client, table))
    assert verdicts(results)["cookie secure"] == "OK"


def test_no_cookie_on_the_login_page_is_a_skip_not_a_pass(client):
    # What the app does TODAY: GET /login sets nothing, so there is no flag
    # to read. That must not read as "verified" in the output.
    results = checker.run_checks(ORIGIN, Fake(client))
    cookie = next(r for r in results if r.name == "cookie secure")
    assert cookie.verdict == "SKIP" and cookie.ok
    assert "devtools" in cookie.detail


# ------------------------------------------------------------- the exit code

def test_main_exits_non_zero_on_a_fail_and_names_the_check(client, capsys, monkeypatch):
    table = canned()
    del table["/sw.js"]
    monkeypatch.setattr(checker, "http_fetch", Fake(client, table))
    assert checker.main([ORIGIN]) == 1
    out = capsys.readouterr().out
    assert "STOPPED at service worker" in out
    # One line per check, and nothing after the one that failed.
    assert "asset links" not in out


def test_every_line_is_one_line(client, capsys, monkeypatch):
    monkeypatch.setattr(checker, "http_fetch", Fake(client))
    assert checker.main([ORIGIN]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 7
    assert all(ln.startswith(("OK", "SKIP", "FAIL")) for ln in lines)
