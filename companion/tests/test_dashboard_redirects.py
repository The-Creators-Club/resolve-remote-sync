"""The companion never follows a redirect on a call that carries credentials.

COMMERCIAL_READINESS.md item 15, "non-upgrade requests follow redirects"
(2026-08-17). The upgrade channel has refused redirects since AUDIT_3 H-1;
every OTHER dashboard call still used urllib.request.urlopen, which follows
3xx automatically and strips only the Authorization header -- custom ones ride
along. A dashboard answering "302 Location: http://attacker/" would therefore
have handed X-CCSync-Token and X-CCSync-Identity to another origin, and the
companion would have parsed the reply as its own.

These drive the REAL urllib chain through a stub HTTP handler, so what is
pinned is the opener the code actually builds -- not a mock of it.
"""

from __future__ import annotations

import http.client
import io
import urllib.error
import urllib.request

import pytest

from ccsync_companion import reporter as reporter_mod
from ccsync_companion import selection as selection_mod


class RedirectingHandler(urllib.request.BaseHandler):
    """Answers the first request with a 302 to `elsewhere`, and records every
    request it is handed -- so a followed redirect is visible as a SECOND
    entry with the credential headers still attached."""

    handler_order = 100          # before the default HTTPHandler

    def __init__(self, elsewhere="http://attacker.example/x"):
        self.elsewhere = elsewhere
        self.seen = []

    def http_open(self, req):
        self.seen.append(req)
        if len(self.seen) == 1:
            headers = http.client.HTTPMessage()
            headers["Location"] = self.elsewhere
            headers["Content-Length"] = "0"
            resp = urllib.response.addinfourl(io.BytesIO(b""), headers,
                                              req.get_full_url(), 302)
            resp.msg = "Found"
            return resp
        headers = http.client.HTTPMessage()
        headers["Content-Type"] = "application/json"
        body = b'{"stolen": true}'
        resp = urllib.response.addinfourl(io.BytesIO(body), headers,
                                          req.get_full_url(), 200)
        resp.msg = "OK"
        return resp

    https_open = http_open


@pytest.fixture
def redirector(monkeypatch):
    handler = RedirectingHandler()
    real_build = urllib.request.build_opener

    def build(*handlers):
        return real_build(handler, *handlers)

    monkeypatch.setattr(urllib.request, "build_opener", build)
    return handler


CREDENTIALS = {"X-CCSync-Token": "sekrit", "X-CCSync-Identity": "v2.identity.x"}


def test_the_reporter_refuses_a_redirect(redirector):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        reporter_mod.default_http_post("http://dash.example/api/v1/report",
                                       {"a": 1}, dict(CREDENTIALS), 5.0)
    assert excinfo.value.code == 302
    assert len(redirector.seen) == 1                 # never re-sent anywhere


def test_the_selection_read_refuses_a_redirect(redirector):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        selection_mod.default_http_get("http://dash.example/api/v1/selection/owen",
                                       dict(CREDENTIALS), 5.0)
    assert excinfo.value.code == 302
    assert len(redirector.seen) == 1


def test_the_credentials_never_reach_the_redirect_target(redirector):
    """The whole point, stated as the attacker would: nothing this fleet holds
    is ever sent to attacker.example."""
    for call in (
        lambda: reporter_mod.default_http_post("http://dash.example/api/v1/report",
                                               {}, dict(CREDENTIALS), 5.0),
        lambda: selection_mod.default_http_get("http://dash.example/api/v1/selection/a",
                                               dict(CREDENTIALS), 5.0),
    ):
        redirector.seen.clear()
        with pytest.raises(urllib.error.HTTPError):
            call()
        hosts = {req.host for req in redirector.seen}
        assert hosts == {"dash.example"}


def test_a_normal_response_still_works(monkeypatch):
    """The no-redirect opener must not change the happy path."""
    class OkHandler(urllib.request.BaseHandler):
        handler_order = 100

        def http_open(self, req):
            headers = http.client.HTTPMessage()
            headers["Content-Type"] = "application/json"
            resp = urllib.response.addinfourl(io.BytesIO(b'{"ok": true}'), headers,
                                              req.get_full_url(), 200)
            resp.msg = "OK"
            return resp

    real_build = urllib.request.build_opener
    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *h: real_build(OkHandler(), *h))
    assert reporter_mod.default_http_post("http://dash.example/api/v1/report",
                                          {}, {}, 5.0) == {"ok": True}
