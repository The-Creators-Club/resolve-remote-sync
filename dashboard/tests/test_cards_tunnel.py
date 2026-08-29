"""The Timeline Cards agent tunnel: the credential, the carve-outs, the poll.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 2 (2026-08-30). The upstream cards
server is a fake opener here, so nothing in this suite needs a container, a
vault or a Resolve.

The properties defended, each of them a way this goes wrong live:

  * A FLEET CREDENTIAL IS REQUIRED, AND A NAKED TOKEN IS NOT ONE. Same rule
    as every other fleet route: the token proves "a machine in this fleet"
    and nothing about which, so a signed identity rides beside it.
  * THE CARVE-OUT IS PER SUFFIX. `/cards/` is the PAGE in phase 3; a leaked
    fleet token must reach the three agent routes and nothing else.
  * THE UPSTREAM TOKEN NEVER GOES DOWNSTREAM. It is on the outbound header
    only, and the caller's own `token` field is dropped rather than
    forwarded.
  * THE VERIFIED IDENTITY IS THE NAME. `AgentClient` self-asserts a hostname;
    the cards server is told who really called.
  * THE LONG POLL SURVIVES THE TRIP. `wait` is passed through and clamped,
    and the read timeout is that plus the agent's own margin.
  * UPSTREAM DOWN IS A SENTENCE. 502 with what was tried, never a traceback
    and never a 500.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, cards_tunnel
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"
CARDS_TOKEN = "cards-token-not-a-real-one"
CARDS_URL = "http://cards.invalid:8800"


class FakeUpstream:
    """The cards server's three routes, and a record of every outbound call."""

    def __init__(self, answer=None, raises=None):
        self.answer = answer if answer is not None else {"ok": True}
        self.raises = raises
        self.calls: list[dict] = []

    def open(self, request, timeout=None):
        body = None
        if request.data:
            body = json.loads(request.data.decode("utf-8"))
        self.calls.append({
            "url": request.full_url,
            "method": request.get_method(),
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "body": body,
            "timeout": timeout,
        })
        if self.raises is not None:
            raise self.raises
        return _Resp(self.answer)


class _Resp:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def env(tmp_path, monkeypatch):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(
        db_path=str(tmp_path / "dash.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), projects_dir=str(projects),
        report_token=TOKEN, cards_server_url=CARDS_URL, cards_token=CARDS_TOKEN,
    )
    upstream = FakeUpstream()
    monkeypatch.setattr(cards_tunnel, "_opener", lambda: upstream)
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, upstream, settings


def fleet_headers(editor="jsmith"):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


# ------------------------------------------------------------ the credential

def test_no_credential_is_refused(env):
    client, upstream, _ = env
    assert client.post("/cards/agent/state", json={}).status_code in (401, 403)
    assert client.get("/cards/agent/pending").status_code in (401, 403)
    assert client.post("/cards/agent/result", json={}).status_code in (401, 403)
    assert upstream.calls == []


def test_a_token_without_an_identity_is_refused(env):
    """The token proves a machine in the fleet and nothing about WHICH."""
    client, upstream, _ = env
    resp = client.post("/cards/agent/state", json={"state": None},
                       headers={"X-CCSync-Token": TOKEN})
    assert resp.status_code == 403
    assert "identity" in resp.json()["detail"].lower()
    assert upstream.calls == []


def test_an_identity_without_a_token_is_refused(env):
    client, upstream, _ = env
    resp = client.post(
        "/cards/agent/state", json={"state": None},
        headers={"X-CCSync-Identity": auth.make_identity_token(SECRET, "jsmith")})
    assert resp.status_code in (401, 403)
    assert upstream.calls == []


def test_a_session_alone_does_not_reach_the_agent_routes(env):
    """These are machine routes. An admin's browser has no business here, and
    more to the point a leaked SESSION must not be able to drive Resolve."""
    client, upstream, _ = env
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    resp = client.post("/cards/agent/state", json={"state": None})
    assert resp.status_code in (401, 403)
    assert upstream.calls == []
    client.cookies.clear()


# ------------------------------------------------------------ the carve-out

def test_the_carve_out_is_per_suffix_not_per_prefix(env):
    """`/cards/` is the PAGE in phase 3. A fleet token gets the three agent
    routes and nothing else under that prefix."""
    client, upstream, _ = env
    resp = client.get("/cards/api/state", headers=fleet_headers(),
                      follow_redirects=False)
    # 303 to /login is the un-carved-out answer: the fleet token bought
    # nothing here, which is the whole point.
    assert resp.status_code in (303, 401, 403, 404)
    assert upstream.calls == []


def test_the_three_routes_are_reachable_with_a_fleet_credential(env):
    client, upstream, _ = env
    assert client.post("/cards/agent/state", json={"state": None},
                       headers=fleet_headers()).status_code == 200
    assert client.get("/cards/agent/pending?wait=0",
                      headers=fleet_headers()).status_code == 200
    assert client.post("/cards/agent/result", json={"id": 1, "ok": True},
                       headers=fleet_headers()).status_code == 200
    assert len(upstream.calls) == 3


# ------------------------------------------------------------ the token

def test_the_upstream_token_rides_the_header_and_never_comes_back(env):
    client, upstream, _ = env
    resp = client.post("/cards/agent/state",
                       json={"state": None, "token": "a token of my choosing"},
                       headers=fleet_headers())
    assert resp.status_code == 200
    call = upstream.calls[0]
    assert call["headers"]["x-cards-token"] == CARDS_TOKEN
    # The caller's own token field is DROPPED, never forwarded: a companion
    # must not be able to present a secret of its choosing upstream.
    assert "token" not in call["body"]
    assert CARDS_TOKEN not in resp.text
    assert CARDS_TOKEN not in json.dumps(dict(resp.headers))


def test_a_token_echoed_by_the_upstream_is_stripped(env):
    client, upstream, _ = env
    upstream.answer = {"ok": True, "token": CARDS_TOKEN, "version": 5}
    resp = client.post("/cards/agent/state", json={"state": None},
                       headers=fleet_headers())
    assert resp.json() == {"ok": True, "version": 5}


def test_the_token_is_not_in_the_query_string(env):
    """handler._agent_ok accepts ?token=; the header is the one of the three
    that never reaches a log line or a proxy's access record."""
    client, upstream, _ = env
    client.get("/cards/agent/pending?wait=5", headers=fleet_headers())
    assert "token" not in upstream.calls[0]["url"]


# ------------------------------------------------------------ the identity

def test_the_verified_identity_becomes_the_agent_name(env):
    client, upstream, _ = env
    client.post("/cards/agent/state",
                json={"state": None, "name": "SOMEBODY-ELSES-PC"},
                headers=fleet_headers("jsmith"))
    assert upstream.calls[0]["body"]["name"] == "jsmith/SOMEBODY-ELSES-PC"


def test_the_name_is_the_editor_alone_when_no_machine_is_declared(env):
    client, upstream, _ = env
    client.post("/cards/agent/state", json={"state": None},
                headers=fleet_headers("jsmith"))
    assert upstream.calls[0]["body"]["name"] == "jsmith"


def test_the_name_is_sanitised_and_bounded():
    assert cards_tunnel.agent_name("jsmith", "a/../b") == "jsmith/a..b"
    assert len(cards_tunnel.agent_name("jsmith", "M" * 500)) <= cards_tunnel.MAX_NAME_CHARS


def test_the_state_body_is_otherwise_passed_through_verbatim(env):
    client, upstream, _ = env
    state = {"cards": [{"uid": "a"}], "fps": 30.0}
    client.post("/cards/agent/state",
                json={"state": state, "tl_id": "TL1", "tl_fps": 30.0,
                      "clips": {"u": {"name": "A"}}, "keys": {"cut": "^x"},
                      "db": {"info": {"kind": "PostgreSQL"}, "project": "FF5"},
                      "playhead": 42, "ph_uid": "a", "ph_src": None},
                headers=fleet_headers())
    body = upstream.calls[0]["body"]
    assert body["state"] == state
    assert body["tl_id"] == "TL1" and body["playhead"] == 42
    assert body["db"]["project"] == "FF5"


# ------------------------------------------------------------ the long poll

def test_the_wait_is_passed_through_and_the_timeout_allows_for_it(env):
    client, upstream, _ = env
    client.get("/cards/agent/pending?wait=25", headers=fleet_headers())
    call = upstream.calls[0]
    assert call["url"].endswith("/agent/pending?wait=25")
    assert call["method"] == "GET"
    assert call["timeout"] == 25 + cards_tunnel.POLL_MARGIN_SECONDS


def test_a_greedy_wait_is_clamped(env):
    """A client asking for a ten minute poll would hold a threadpool worker
    for ten minutes."""
    client, upstream, _ = env
    client.get("/cards/agent/pending?wait=600", headers=fleet_headers())
    assert upstream.calls[0]["url"].endswith("?wait=25")


def test_the_pending_answer_comes_back_verbatim(env):
    client, upstream, _ = env
    upstream.answer = {"id": 7, "kind": "move", "uid": "abc", "to": 3}
    resp = client.get("/cards/agent/pending?wait=0", headers=fleet_headers())
    assert resp.json() == {"id": 7, "kind": "move", "uid": "abc", "to": 3}


# ------------------------------------------------------------ the failures

def test_an_unreachable_upstream_is_a_502_with_a_sentence(env, monkeypatch):
    client, _upstream, _ = env
    monkeypatch.setattr(cards_tunnel, "_opener",
                        lambda: FakeUpstream(raises=TimeoutError("timed out")))
    resp = client.post("/cards/agent/state", json={"state": None},
                       headers=fleet_headers())
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "Timeline Cards server" in detail and CARDS_URL in detail


def test_an_upstream_403_names_the_dashboards_own_token(env, monkeypatch):
    """A 403 upstream is THIS dashboard's secret being wrong, not the
    caller's. Saying which is the difference between rotating the right
    secret and rotating the fleet's."""
    import urllib.error

    client, _upstream, _ = env
    error = urllib.error.HTTPError(CARDS_URL, 403, "Forbidden", {}, None)
    monkeypatch.setattr(cards_tunnel, "_opener", lambda: FakeUpstream(raises=error))
    resp = client.post("/cards/agent/state", json={"state": None},
                       headers=fleet_headers())
    assert resp.status_code == 502
    assert "DASH_CARDS_TOKEN" in resp.json()["detail"]


def test_non_json_from_the_upstream_is_a_502(env, monkeypatch):
    class Garbage(FakeUpstream):
        def open(self, request, timeout=None):
            self.calls.append({"url": request.full_url})

            class R:
                def read(self):
                    return b"<html>a proxy error page</html>"

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False
            return R()

    client, _upstream, _ = env
    monkeypatch.setattr(cards_tunnel, "_opener", lambda: Garbage())
    resp = client.post("/cards/agent/result", json={"id": 1},
                       headers=fleet_headers())
    assert resp.status_code == 502
    assert "JSON" in resp.json()["detail"]


def test_no_server_configured_is_a_503_naming_the_variable(tmp_path):
    """A fleet that does not use Timeline Cards has no server, and that is a
    normal state. 404 would read as an old dashboard."""
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "dash.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}),
                        projects_dir=str(projects), report_token=TOKEN)
    with TestClient(create_app(settings)) as client:
        resp = client.post("/cards/agent/state", json={"state": None},
                           headers=fleet_headers())
        assert resp.status_code == 503
        assert "DASH_CARDS_SERVER_URL" in resp.json()["detail"]


def test_a_configured_url_with_no_token_is_a_503_too(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "dash.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}),
                        projects_dir=str(projects), report_token=TOKEN,
                        cards_server_url=CARDS_URL)
    with TestClient(create_app(settings)) as client:
        resp = client.get("/cards/agent/pending?wait=0", headers=fleet_headers())
        assert resp.status_code == 503
        assert "DASH_CARDS_TOKEN" in resp.json()["detail"]


def test_the_tunnel_follows_no_redirect():
    """GOTCHAS §12: no dashboard call follows a redirect, and this one carries
    the cards server's token."""
    opener = cards_tunnel._opener()
    assert any(isinstance(h, cards_tunnel._NoRedirect) for h in opener.handlers)
