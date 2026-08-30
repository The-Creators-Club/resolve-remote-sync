"""`tools/check_mobile_origin.py` against a fake origin, one test per verdict.

MOBILE_PLAN.md M6, 2026-08-30. The checker is what an admin runs after
putting the dashboard behind TLS and before touching a phone, so its
VERDICTS are the product: "OK" on a good origin is worth nothing if it also
says OK on a manifest that 303s to the login page, which is the actual
failure this exists to catch.

No sockets, no server, no certificate. The checker takes its `fetch` as an
argument (module docstring, "ONE FETCH FUNCTION, injected"), so the fake
below answers from a real `TestClient` over the real app -- every route the
checker asks for, `/manifest.webmanifest` and `/sw.js` and
`/.well-known/assetlinks.json` included now that M4 and M5 have landed. The
good run is a real run with nothing canned in it. The override table exists
only to force ONE failure at a time, which is the half a working app cannot
demonstrate.

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


class Fake:
    """`fetch(url)` over a TestClient, with an override table in front of it.

    Follows redirects, exactly as `urllib.request.urlopen` does in the real
    `http_fetch`. That is not a detail: it is why a route that has fallen
    behind the login wall reads here as "not JSON" rather than as a 303, and
    a phone browser sees exactly the same thing.
    """

    def __init__(self, client: TestClient, overrides: dict | None = None,
                 raises: Exception | None = None):
        self.client = client
        self.overrides = overrides or {}
        self.raises = raises
        self.asked: list[str] = []

    def get(self, path: str) -> "checker.Response":
        reply = self.client.get(path, follow_redirects=True)
        return checker.Response(
            status=reply.status_code,
            headers={k.lower(): v for k, v in reply.headers.items()},
            body=reply.content,
            set_cookies=tuple(reply.headers.get_list("set-cookie")),
        )

    def __call__(self, url: str) -> "checker.Response":
        assert url.startswith(ORIGIN), f"the checker left its origin: {url}"
        path = url[len(ORIGIN):] or "/"
        self.asked.append(path)
        if self.raises is not None:
            raise self.raises
        if path in self.overrides:
            return self.overrides[path]
        return self.get(path)


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
    # THE failure this script exists for. /manifest.webmanifest is in
    # app._OPEN_EXACT today, so the app cannot show this shape by itself --
    # it is forced by answering that path with what a session-gated route
    # answers: a 303 followed to the login page's HTML. Chrome does exactly
    # this and then silently never offers to install. If somebody drops the
    # route out of _OPEN_EXACT, the checker still says so.
    fake = Fake(client)
    fake.overrides["/manifest.webmanifest"] = fake.get("/login")
    results = checker.run_checks(ORIGIN, fake)
    assert verdicts(results)["manifest"] == "FAIL"
    assert "not JSON" in detail(results, "manifest")


def test_a_manifest_without_start_url_or_icons_fails(client):
    overrides = {"/manifest.webmanifest": checker.Response(200, {}, b'{"name": "CC Sync"}')}
    results = checker.run_checks(ORIGIN, Fake(client, overrides))
    assert verdicts(results)["manifest"] == "FAIL"
    assert "start_url" in detail(results, "manifest") and "icons" in detail(results, "manifest")


def test_a_service_worker_without_the_header_fails(client):
    overrides = {"/sw.js": checker.Response(
        200, {"content-type": "application/javascript"}, b"// sw")}
    results = checker.run_checks(ORIGIN, Fake(client, overrides))
    assert verdicts(results)["service worker"] == "FAIL"
    assert "Service-Worker-Allowed" in detail(results, "service worker")


def test_missing_asset_links_fail_and_an_empty_list_does_not(client):
    overrides = {"/.well-known/assetlinks.json": checker.Response(404, {}, b"")}
    results = checker.run_checks(ORIGIN, Fake(client, overrides))
    assert verdicts(results)["asset links"] == "FAIL"
    assert "URL bar" in detail(results, "asset links")
    # The default -- no Android package configured -- is not a fault.
    ok = checker.run_checks(ORIGIN, Fake(client))
    assert verdicts(ok)["asset links"] == "OK"
    assert "no Android package" in detail(ok, "asset links")


def test_something_else_on_the_port_fails_at_health(client):
    overrides = {"/api/v1/health": checker.Response(200, {}, b"<html>TrueNAS</html>")}
    results = checker.run_checks(ORIGIN, Fake(client, overrides))
    assert verdicts(results)["health"] == "FAIL"
    assert "not JSON" in detail(results, "health")


def test_health_without_a_version_fails(client):
    overrides = {"/api/v1/health": checker.Response(200, {}, b'{"ok": true}')}
    results = checker.run_checks(ORIGIN, Fake(client, overrides))
    assert verdicts(results)["health"] == "FAIL"
    assert "not the dashboard" in detail(results, "health")


# --------------------------------------------------------- the cookie check

def test_a_session_cookie_without_secure_fails(client):
    # The trusted-proxy trap: DASH_COOKIE_SECURE=auto behind a terminator
    # whose address is not in DASH_TRUSTED_PROXIES leaves the flag off, and
    # nothing else anywhere notices.
    overrides = {"/login": checker.Response(
        200, {}, b"<html></html>",
        set_cookies=("ccsync_session=abc; HttpOnly; Path=/; SameSite=lax",))}
    results = checker.run_checks(ORIGIN, Fake(client, overrides))
    assert verdicts(results)["cookie secure"] == "FAIL"
    assert "DASH_TRUSTED_PROXIES" in detail(results, "cookie secure")


def test_a_secure_session_cookie_passes(client):
    overrides = {"/login": checker.Response(
        200, {}, b"<html></html>",
        set_cookies=("ccsync_session=abc; HttpOnly; Secure; Path=/; SameSite=lax",))}
    results = checker.run_checks(ORIGIN, Fake(client, overrides))
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
    # A service worker served WITHOUT Service-Worker-Allowed: real route,
    # real 200, and still a fail -- the header is the whole check.
    overrides = {"/sw.js": checker.Response(200, {}, b"// sw")}
    monkeypatch.setattr(checker, "http_fetch", Fake(client, overrides))
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
