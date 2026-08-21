"""The vendor release feed client (ZERO_TOUCH_PLAN.md WP E, 2026-08-17):
fetch + verify, the diff/publish routes, and the three policy modes.

No network: `release_feed._opener` is monkeypatched to a table-driven fake
that answers exactly the urls the code under test asks for and 404s on
anything else -- so a request to a URL nobody registered fails loudly rather
than hanging or hitting the real internet."""
from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import ed25519, release_feed, release_trust
from ccsync_dashboard.api import build_packages_view
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
TEST_SEED = bytes(range(32))
TEST_PUBKEY = base64.b64encode(ed25519.public_key(TEST_SEED)).decode("ascii")
OTHER_SEED = bytes(range(32, 64))
OTHER_PUBKEY = base64.b64encode(ed25519.public_key(OTHER_SEED)).decode("ascii")

FEED_BASE = "https://releases.example.test/v1"
CHANNEL_URL = f"{FEED_BASE}/channel.json"
SIG_URL = f"{FEED_BASE}/channel.json.sig"

PUBLISHED_AT = "2026-08-17T12:00:00Z"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def sign_record(seed: bytes, record: dict) -> dict:
    sig = base64.b64encode(ed25519.sign(seed, release_trust.canonical_record(record))).decode("ascii")
    pub = base64.b64encode(ed25519.public_key(seed)).decode("ascii")
    out = dict(record)
    out["signature"] = sig
    out["pubkey_id"] = release_trust.pubkey_id(pub)
    return out


def make_record(*, kind="companion", platform="windows", version="0.9.0",
                body=b"feed-exe-bytes", min_version="0.0.0", signed_binary=False,
                seed=TEST_SEED, filename=None):
    filename = filename or f"ccsync-companion-{version}.exe"
    record = {
        "kind": kind, "platform": platform, "version": version, "filename": filename,
        "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body),
        "min_version": min_version, "published_at": PUBLISHED_AT, "signed_binary": signed_binary,
    }
    signed = sign_record(seed, record)
    signed["url"] = f"{FEED_BASE}/{platform}/{filename}"
    signed["notes"] = "test build"
    return signed, body


def make_channel(records: list[dict], *, seed=TEST_SEED, image=None,
                 current=None) -> tuple[dict, str]:
    channel = {
        "schema": 1, "generated_at": PUBLISHED_AT, "channel": "stable",
        "pubkey_id": release_trust.pubkey_id(base64.b64encode(ed25519.public_key(seed)).decode("ascii")),
        "dashboard_image": image or {"tag": "", "digest": ""},
        "packages": records,
    }
    # The channel's own "current" pointer (release-pipeline-5, 2026-08-21):
    # {"<kind>/<platform>": "<version>"}. Part of the signed document, which is
    # what stops the feed HOST from steering it.
    if current is not None:
        channel["current"] = current
    sig = base64.b64encode(ed25519.sign(seed, release_feed.canonical_channel_bytes(channel))).decode("ascii")
    return channel, sig


class _FakeResp:
    def __init__(self, data: bytes, status: int = 200, headers: dict | None = None):
        self._data = data
        self._pos = 0
        self.status = status
        self.headers = headers or {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        self.closed = True

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


class _Redirect:
    """A table entry answering a 3xx, the way a real fetch sees one: the
    module's opener refuses to follow, so urllib raises HTTPError and the
    redirect's own headers hang off it. `as_response=True` covers the other
    shape release_feed guards against defensively -- a handler stack that
    hands back a 3xx as an ordinary response instead of raising."""

    def __init__(self, location: str | None, code: int = 302, as_response: bool = False):
        self.location = location
        self.code = code
        self.as_response = as_response

    def headers(self) -> dict:
        return {} if self.location is None else {"Location": self.location}


class _FakeOpener:
    """table: url -> bytes, a _Redirect, or an exception instance to raise."""

    def __init__(self, table: dict):
        self.table = table
        self.requested: list[str] = []
        self.requests: list = []

    def open(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.requested.append(url)
        self.requests.append(req)
        val = self.table.get(url)
        if val is None:
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        if isinstance(val, Exception):
            raise val
        if isinstance(val, _Redirect):
            if val.as_response:
                return _FakeResp(b"", status=val.code, headers=val.headers())
            raise urllib.error.HTTPError(url, val.code, "redirect", val.headers(), None)
        return _FakeResp(val)


def patch_opener(monkeypatch, table: dict) -> _FakeOpener:
    opener = _FakeOpener(table)
    monkeypatch.setattr(release_feed, "_opener", lambda: opener)
    return opener


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "feed.db"
    settings = Settings(
        db_path=str(db_path),
        session_secret=SECRET,
        admin_users=frozenset({"owen"}),
        packages_dir=str(tmp_path / "pkgs"),
        release_pubkeys=(TEST_PUBKEY,),
        release_feed_url=CHANNEL_URL,
    )
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "pw"
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        as_user(client, "owen")
        yield client, conn, settings
        conn.close()


# --------------------------------------------------------------- migration v19


def test_feed_state_default_and_partial_upsert(tmp_path):
    conn = dbmod.connect(tmp_path / "v19.db")
    dbmod.migrate(conn)
    state = dbmod.get_feed_state(conn)
    assert state == {"last_checked_at": None, "last_error": None,
                     "last_channel_generated_at": None, "etag": None, "policy_override": None}

    dbmod.set_feed_state(conn, last_checked_at="2026-08-17T18:00:00Z", last_error="")
    conn.commit()
    state = dbmod.get_feed_state(conn)
    assert state["last_checked_at"] == "2026-08-17T18:00:00Z"
    assert state["last_error"] == ""
    assert state["policy_override"] is None   # untouched field keeps its value

    dbmod.set_feed_state(conn, policy_override="current")
    conn.commit()
    state = dbmod.get_feed_state(conn)
    assert state["policy_override"] == "current"
    assert state["last_checked_at"] == "2026-08-17T18:00:00Z"   # still there
    conn.close()


# --------------------------------------------------------------- configuration


def test_unconfigured_feed_never_touches_the_network(tmp_path, monkeypatch):
    settings = Settings(
        db_path=str(tmp_path / "t.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), packages_dir=str(tmp_path / "pkgs"),
        release_pubkeys=(TEST_PUBKEY,),  # feed_url left blank
    )
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "pw"
    called = []
    monkeypatch.setattr(release_feed, "_opener", lambda: called.append(1) or _FakeOpener({}))
    with TestClient(app) as client:
        as_user(client, "owen")
        r = client.get("/api/v1/admin/feed")
        assert r.status_code == 200
        body = r.json()
        assert body["configured"] is False
        assert body["available"] == []
        assert r.json()["last_checked_at"] is None
        assert client.post("/api/v1/admin/feed/check").status_code == 503
        assert client.post("/api/v1/admin/feed/publish",
                           json={"platform": "windows", "version": "0.9.0"}).status_code == 503
    assert called == []


# --------------------------------------------------------------- check_now


def test_check_now_populates_available_and_persists_state(env, monkeypatch):
    client, conn, settings = env
    record, body = make_record()
    channel, sig = make_channel([record])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), record["url"]: body,
    })

    r = client.post("/api/v1/admin/feed/check")
    assert r.status_code == 200
    body_json = r.json()
    assert body_json["ok"] is True
    assert body_json["error"] is None
    view = body_json["view"]
    assert view["configured"] is True
    assert len(view["available"]) == 1
    assert view["available"][0]["version"] == "0.9.0"
    assert view["last_error"] == ""
    assert view["last_checked_at"]
    assert view["last_channel_generated_at"] == PUBLISHED_AT

    state = dbmod.get_feed_state(conn)
    assert state["last_error"] == ""
    assert state["last_checked_at"] == view["last_checked_at"]


def test_an_unverifiable_channel_is_refused_and_never_surfaced(env, monkeypatch):
    client, conn, settings = env
    record, body = make_record(seed=OTHER_SEED)   # signed by a key this dashboard does NOT trust
    channel, sig = make_channel([record], seed=OTHER_SEED)
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), record["url"]: body,
    })

    r = client.post("/api/v1/admin/feed/check")
    assert r.status_code == 200
    payload = r.json()
    assert payload["ok"] is False
    assert "signature invalid" in payload["error"]
    assert payload["view"]["available"] == []

    state = dbmod.get_feed_state(conn)
    assert state["last_error"]
    assert "signature invalid" in state["last_error"]


def test_a_record_with_a_bad_signature_inside_a_valid_channel_is_dropped(env, monkeypatch):
    """Belt and braces: even a channel wrapper this dashboard trusts must not
    smuggle in a record whose OWN signature does not verify."""
    client, conn, settings = env
    good, good_body = make_record(version="0.9.0")
    bad, bad_body = make_record(version="0.9.1", seed=OTHER_SEED)
    channel, sig = make_channel([good, bad])   # channel itself signed by the trusted key
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(),
        good["url"]: good_body, bad["url"]: bad_body,
    })
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is True
    available = r.json()["view"]["available"]
    assert [rec["version"] for rec in available] == ["0.9.0"]


def test_https_is_required(env, monkeypatch):
    client, conn, settings = env
    object.__setattr__(settings, "release_feed_url", "http://releases.example.test/v1/channel.json")
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is False
    assert "https" in r.json()["error"]


def test_an_oversized_channel_is_refused(env, monkeypatch):
    client, conn, settings = env
    huge = b"x" * (release_feed.FEED_MAX_BYTES + 1)
    patch_opener(monkeypatch, {CHANNEL_URL: huge})
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is False
    assert "cap" in r.json()["error"]


# ----------------------------------------------------------------- redirects
# Added 2026-08-18: GitHub Releases 302s every asset URL to a signed
# release-assets.githubusercontent.com URL, so the original absolute
# no-redirect rule made a GitHub-hosted feed fail on its first fetch. What
# these pin is the shape of the carve-out -- bounded, https-only, and buying
# the redirect target no trust whatsoever.

ASSET_HOST = "https://release-assets.example.test"


def redirect_chain(start: str, hops: int, body: bytes) -> dict:
    """A table of `hops` https redirects from `start`, ending in `body`."""
    table: dict = {}
    url = start
    for i in range(hops):
        nxt = f"{ASSET_HOST}/hop{i + 1}/channel.json"
        table[url] = _Redirect(nxt)
        url = nxt
    table[url] = body
    return table


def test_a_single_https_redirect_is_followed(env, monkeypatch):
    client, conn, settings = env
    record, body = make_record()
    channel, sig = make_channel([record])
    signed_url = f"{ASSET_HOST}/signed/channel.json"
    opener = patch_opener(monkeypatch, {
        CHANNEL_URL: _Redirect(signed_url),
        signed_url: json.dumps(channel).encode(),
        SIG_URL: sig.encode(),
    })
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is True, r.json()["error"]
    assert len(r.json()["view"]["available"]) == 1
    assert signed_url in opener.requested


def test_a_redirect_answered_as_a_response_is_also_followed(env, monkeypatch):
    """The defensive half: a 3xx that arrives as an ordinary response rather
    than an HTTPError must be followed as a redirect, never read as a body."""
    client, conn, settings = env
    channel, sig = make_channel([])
    signed_url = f"{ASSET_HOST}/signed/channel.json"
    patch_opener(monkeypatch, {
        CHANNEL_URL: _Redirect(signed_url, as_response=True),
        signed_url: json.dumps(channel).encode(),
        SIG_URL: sig.encode(),
    })
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is True, r.json()["error"]


def test_a_chain_at_the_hop_cap_is_followed(env, monkeypatch):
    client, conn, settings = env
    channel, sig = make_channel([])
    table = redirect_chain(CHANNEL_URL, release_feed._MAX_REDIRECTS, json.dumps(channel).encode())
    table[SIG_URL] = sig.encode()
    patch_opener(monkeypatch, table)
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is True, r.json()["error"]


def test_one_hop_over_the_cap_is_refused(env, monkeypatch):
    client, conn, settings = env
    channel, sig = make_channel([])
    table = redirect_chain(CHANNEL_URL, release_feed._MAX_REDIRECTS + 1, json.dumps(channel).encode())
    table[SIG_URL] = sig.encode()
    patch_opener(monkeypatch, table)
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is False
    assert "redirected more than" in r.json()["error"]


def test_an_endless_redirect_loop_is_refused(env, monkeypatch):
    client, conn, settings = env
    patch_opener(monkeypatch, {CHANNEL_URL: _Redirect(CHANNEL_URL)})
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is False
    assert "redirected more than" in r.json()["error"]


def test_a_redirect_to_http_is_refused_as_a_downgrade(env, monkeypatch):
    client, conn, settings = env
    opener = patch_opener(monkeypatch, {
        CHANNEL_URL: _Redirect("http://releases.example.test/v1/channel.json"),
    })
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is False
    assert "non-https redirect" in r.json()["error"]
    # Refused, not fetched-then-discarded: the http URL was never opened.
    assert not any(u.startswith("http://") for u in opener.requested)


def test_a_redirect_without_a_location_is_refused(env, monkeypatch):
    client, conn, settings = env
    patch_opener(monkeypatch, {CHANNEL_URL: _Redirect(None)})
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is False
    assert "no Location" in r.json()["error"]


def test_a_redirect_buys_the_new_host_no_trust(env, monkeypatch):
    """The redirect target is as untrusted as the feed host itself: a channel
    signed by a key this dashboard does not hold is still discarded whole."""
    client, conn, settings = env
    record, body = make_record(seed=OTHER_SEED)
    channel, sig = make_channel([record], seed=OTHER_SEED)
    evil = "https://evil.example.test/channel.json"
    patch_opener(monkeypatch, {
        CHANNEL_URL: _Redirect(evil),
        evil: json.dumps(channel).encode(),
        SIG_URL: sig.encode(),
    })
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is False
    assert "signature invalid" in r.json()["error"]
    assert r.json()["view"]["available"] == []


def test_the_byte_cap_still_applies_after_a_redirect(env, monkeypatch):
    client, conn, settings = env
    signed_url = f"{ASSET_HOST}/signed/channel.json"
    patch_opener(monkeypatch, {
        CHANNEL_URL: _Redirect(signed_url),
        signed_url: b"x" * (release_feed.FEED_MAX_BYTES + 1),
    })
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is False
    assert "cap" in r.json()["error"]


def test_no_credential_rides_along_on_any_hop(env, monkeypatch):
    """The property that makes following a redirect safe here at all
    (GOTCHAS §12): these fetches carry no credential, so a redirect cannot
    leak one. If this fails, the carve-out is no longer justified."""
    client, conn, settings = env
    channel, sig = make_channel([])
    signed_url = f"{ASSET_HOST}/signed/channel.json"
    opener = patch_opener(monkeypatch, {
        CHANNEL_URL: _Redirect(signed_url),
        signed_url: json.dumps(channel).encode(),
        SIG_URL: sig.encode(),
    })
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    assert len(opener.requests) >= 3
    for req in opener.requests:
        assert req.header_items() == []
        assert req.get_header("Authorization") is None
        assert req.get_header("Cookie") is None


# --------------------------------------------------------------- publish (manual)


def test_publish_inserts_the_same_shape_a_put_would(env, monkeypatch):
    client, conn, settings = env
    record, body = make_record(min_version="0.7.12", signed_binary=True)
    channel, sig = make_channel([record])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), record["url"]: body,
    })
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True

    r = client.post("/api/v1/admin/feed/publish",
                    json={"kind": "companion", "platform": "windows", "version": "0.9.0",
                          "make_current": True})
    assert r.status_code == 200
    view = r.json()["view"]
    assert view["current"]["windows"] == "0.9.0"

    row = dbmod.get_package(conn, "windows", "0.9.0")
    assert row is not None
    assert row["sha256"] == hashlib.sha256(body).hexdigest()
    assert row["signature"] == record["signature"]
    assert row["min_version"] == "0.7.12"
    assert bool(row["signed_binary"]) is True
    path = settings.packages_path() / "windows" / record["filename"]
    assert path.read_bytes() == body

    # After publishing it must no longer show as "available".
    view2 = client.get("/api/v1/admin/feed").json()
    assert view2["available"] == []


def test_publish_without_check_first_is_404(env):
    client, conn, settings = env
    r = client.post("/api/v1/admin/feed/publish",
                    json={"platform": "windows", "version": "0.9.0"})
    assert r.status_code == 404


def test_publish_refuses_a_sha_mismatch(env, monkeypatch):
    client, conn, settings = env
    record, body = make_record()
    channel, sig = make_channel([record])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(),
        record["url"]: b"NOT the bytes that were signed",
    })
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    r = client.post("/api/v1/admin/feed/publish", json={"platform": "windows", "version": "0.9.0"})
    assert r.status_code == 400
    assert dbmod.get_package(conn, "windows", "0.9.0") is None


def test_publish_refuses_a_non_https_artifact_url(env, monkeypatch):
    client, conn, settings = env
    record, body = make_record()
    record["url"] = "http://releases.example.test/v1/windows/x.exe"
    channel, sig = make_channel([record])
    patch_opener(monkeypatch, {CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode()})
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    r = client.post("/api/v1/admin/feed/publish", json={"platform": "windows", "version": "0.9.0"})
    assert r.status_code == 400


def test_publish_follows_a_redirect_on_the_artifact_url(env, monkeypatch):
    """The download half of the 2026-08-18 carve-out: a GitHub asset URL 302s
    to a short-lived signed URL on another host, and publishing must work."""
    client, conn, settings = env
    record, body = make_record()
    channel, sig = make_channel([record])
    signed_url = f"{ASSET_HOST}/blob/abc123?exp=1"
    opener = patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(),
        record["url"]: _Redirect(signed_url), signed_url: body,
    })
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    r = client.post("/api/v1/admin/feed/publish", json={"platform": "windows", "version": "0.9.0"})
    assert r.status_code == 200
    assert signed_url in opener.requested
    assert (settings.packages_path() / "windows" / record["filename"]).read_bytes() == body


def test_publish_refuses_an_http_redirect_on_the_artifact_url(env, monkeypatch):
    client, conn, settings = env
    record, body = make_record()
    channel, sig = make_channel([record])
    opener = patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(),
        record["url"]: _Redirect("http://releases.example.test/v1/windows/x.exe"),
    })
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    r = client.post("/api/v1/admin/feed/publish", json={"platform": "windows", "version": "0.9.0"})
    assert r.status_code == 502
    assert "non-https redirect" in r.json()["detail"]
    assert not any(u.startswith("http://") for u in opener.requested)
    assert dbmod.get_package(conn, "windows", "0.9.0") is None


def test_publish_refuses_an_artifact_redirect_chain_over_the_cap(env, monkeypatch):
    client, conn, settings = env
    record, body = make_record()
    channel, sig = make_channel([record])
    table = {CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode()}
    url = record["url"]
    for i in range(release_feed._MAX_REDIRECTS + 1):
        nxt = f"{ASSET_HOST}/hop{i + 1}/x.exe"
        table[url] = _Redirect(nxt)
        url = nxt
    table[url] = body
    patch_opener(monkeypatch, table)
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    r = client.post("/api/v1/admin/feed/publish", json={"platform": "windows", "version": "0.9.0"})
    assert r.status_code == 502
    assert "redirected more than" in r.json()["detail"]
    assert dbmod.get_package(conn, "windows", "0.9.0") is None


def test_a_redirected_artifact_still_has_to_hash_right(env, monkeypatch):
    """Same rule as the channel: the host a redirect names is trusted for
    nothing -- the sha256 pinned in the signed record still decides."""
    client, conn, settings = env
    record, body = make_record()
    channel, sig = make_channel([record])
    signed_url = f"{ASSET_HOST}/blob/abc123"
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(),
        record["url"]: _Redirect(signed_url), signed_url: b"substituted by the redirect target",
    })
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    r = client.post("/api/v1/admin/feed/publish", json={"platform": "windows", "version": "0.9.0"})
    assert r.status_code == 400
    assert dbmod.get_package(conn, "windows", "0.9.0") is None
    assert not list((settings.packages_path() / "windows").glob("*"))


def test_publish_already_published_is_409(env, monkeypatch):
    client, conn, settings = env
    record, body = make_record()
    channel, sig = make_channel([record])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), record["url"]: body,
    })
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    assert client.post("/api/v1/admin/feed/publish",
                       json={"platform": "windows", "version": "0.9.0"}).status_code == 200
    r = client.post("/api/v1/admin/feed/publish", json={"platform": "windows", "version": "0.9.0"})
    assert r.status_code == 409


# --------------------------------------------------------------- policy


def test_policy_defaults_to_manual_and_is_editable(env):
    client, conn, settings = env
    assert client.get("/api/v1/admin/feed").json()["policy"] == "manual"
    r = client.post("/api/v1/admin/feed/policy", json={"policy": "stage"})
    assert r.status_code == 200
    assert r.json()["policy"] == "stage"
    assert client.get("/api/v1/admin/feed").json()["policy"] == "stage"


def test_policy_rejects_an_unknown_value(env):
    client, conn, settings = env
    r = client.post("/api/v1/admin/feed/policy", json={"policy": "sometimes"})
    assert r.status_code == 422


def test_manual_policy_never_auto_publishes(env, monkeypatch):
    client, conn, settings = env
    record, body = make_record()
    channel, sig = make_channel([record])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), record["url"]: body,
    })
    r = client.post("/api/v1/admin/feed/check")
    # `applied` is part of the response since 2026-08-21 and is empty under
    # manual: nothing is published without an admin pressing PUBLISH.
    assert r.json()["applied"] == []
    assert dbmod.get_package(conn, "windows", "0.9.0") is None


def test_stage_policy_auto_publishes_but_not_current(env, monkeypatch):
    client, conn, settings = env
    assert client.post("/api/v1/admin/feed/policy", json={"policy": "stage"}).status_code == 200
    record, body = make_record()
    channel, sig = make_channel([record])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), record["url"]: body,
    })
    r = client.post("/api/v1/admin/feed/check")
    assert r.status_code == 200
    row = dbmod.get_package(conn, "windows", "0.9.0")
    assert row is not None
    assert not row["is_current"]


def test_current_policy_auto_publishes_and_makes_current(env, monkeypatch):
    client, conn, settings = env
    assert client.post("/api/v1/admin/feed/policy", json={"policy": "current"}).status_code == 200
    record, body = make_record()
    channel, sig = make_channel([record])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), record["url"]: body,
    })
    r = client.post("/api/v1/admin/feed/check")
    assert r.status_code == 200
    row = dbmod.get_package(conn, "windows", "0.9.0")
    assert row is not None
    assert row["is_current"]


def test_current_policy_never_republishes_an_already_published_version(env, monkeypatch):
    client, conn, settings = env
    record, body = make_record()
    channel, sig = make_channel([record])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), record["url"]: body,
    })
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    assert client.post("/api/v1/admin/feed/publish",
                       json={"platform": "windows", "version": "0.9.0"}).status_code == 200
    assert client.post("/api/v1/admin/feed/policy", json={"policy": "current"}).status_code == 200
    # A second check must not blow up on the version it already has.
    r = client.post("/api/v1/admin/feed/check")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# --------------------------------------------------------------- image line


def test_image_line_reports_tag_digest_and_running_version(env, monkeypatch):
    client, conn, settings = env
    channel, sig = make_channel([], image={"tag": "1.4.0", "digest": "sha256:" + "b" * 64})
    patch_opener(monkeypatch, {CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode()})
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    view = client.get("/api/v1/admin/feed").json()
    assert view["image"]["tag"] == "1.4.0"
    assert view["image"]["digest"] == "sha256:" + "b" * 64
    assert view["image"]["current_running_version"]


# --------------------------------------------------------------- admin gating


def test_anonymous_and_non_admin_are_refused(env):
    client, conn, settings = env
    client.cookies.delete(auth.COOKIE_NAME)
    assert client.get("/api/v1/admin/feed").status_code == 401
    as_user(client, "jsmith")
    assert client.get("/api/v1/admin/feed").status_code == 403


# --------------------------------------------------------------- today's PUT path


def test_the_put_path_is_unaffected_by_the_refactor(tmp_path):
    """package_store.store_verified_package now backs BOTH the PUT route and
    the feed -- this is a canary that the PUT route still round-trips a
    build end to end after that extraction."""
    settings = Settings(
        db_path=str(tmp_path / "put.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), packages_dir=str(tmp_path / "pkgs"),
        release_pubkeys=(TEST_PUBKEY,),
    )
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "pw"
    with TestClient(app) as client:
        as_user(client, "owen")
        body = b"a normal little exe"
        record = {
            "kind": "companion", "platform": "windows", "version": "0.2.0",
            "filename": "ccsync-companion-0.2.0.exe", "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body), "min_version": "0.0.0", "published_at": PUBLISHED_AT,
            "signed_binary": False,
        }
        signed = sign_record(TEST_SEED, record)
        suffix = (f"&signature={quote(signed['signature'], safe='')}"
                 f"&pubkey_id={quote(signed['pubkey_id'], safe='')}"
                 f"&min_version=0.0.0&published_at={quote(PUBLISHED_AT, safe='')}&signed_binary=0")
        r = client.put(f"/api/v1/admin/packages/windows/0.2.0?sha256={record['sha256']}{suffix}",
                       content=body, headers={"Content-Type": "application/octet-stream"})
        assert r.status_code == 200
        assert dbmod.get_package(dbmod.connect(settings.db_path), "windows", "0.2.0") is not None


# ------------------------------------------- the channel's `current` pointer
# release-pipeline-5 / release-pipeline-6 / dash-release-ai-3 (2026-08-21).


def test_current_policy_publishes_only_the_named_record(env, monkeypatch):
    """A fresh dashboard on `current` must not replay the whole history: it
    takes the ONE build the channel says is current, per (kind, platform)."""
    client, conn, settings = env
    assert client.post("/api/v1/admin/feed/policy", json={"policy": "current"}).status_code == 200
    old_rec, old_body = make_record(version="0.9.0", body=b"old-bytes")
    new_rec, new_body = make_record(version="0.9.41", body=b"new-bytes")
    channel, sig = make_channel([old_rec, new_rec],
                                current={"companion/windows": "0.9.41"})
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(),
        old_rec["url"]: old_body, new_rec["url"]: new_body,
    })
    r = client.post("/api/v1/admin/feed/check")
    assert r.status_code == 200
    assert r.json()["applied"] == ["companion/windows 0.9.41"]
    assert dbmod.get_package(conn, "windows", "0.9.0") is None
    row = dbmod.get_package(conn, "windows", "0.9.41")
    assert row is not None and row["is_current"]


def test_with_no_pointer_the_highest_version_wins_not_the_last_in_the_list(env, monkeypatch):
    """Append order is not version order: a --force republish of an older
    build lands AFTER a newer one in the file and used to become current."""
    client, conn, settings = env
    assert client.post("/api/v1/admin/feed/policy", json={"policy": "current"}).status_code == 200
    newer, newer_body = make_record(version="0.10.0", body=b"newer-bytes")
    older, older_body = make_record(version="0.9.41", body=b"older-bytes")
    channel, sig = make_channel([newer, older])          # older appended last
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(),
        newer["url"]: newer_body, older["url"]: older_body,
    })
    assert client.post("/api/v1/admin/feed/check").status_code == 200
    row = dbmod.get_package(conn, "windows", "0.10.0")
    assert row is not None and row["is_current"]
    assert dbmod.get_package(conn, "windows", "0.9.41") is None


def test_the_pointer_can_withdraw_a_build_by_naming_an_older_one(env, monkeypatch):
    """The retraction path: a bad build is withdrawn by moving `current` back
    to a version this dashboard already holds."""
    client, conn, settings = env
    assert client.post("/api/v1/admin/feed/policy", json={"policy": "current"}).status_code == 200
    good, good_body = make_record(version="0.9.41", body=b"good-bytes")
    bad, bad_body = make_record(version="0.9.42", body=b"bad-bytes")
    table = {good["url"]: good_body, bad["url"]: bad_body}

    channel, sig = make_channel([good, bad], current={"companion/windows": "0.9.42"})
    patch_opener(monkeypatch, dict(table, **{
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode()}))
    assert client.post("/api/v1/admin/feed/check").status_code == 200
    # 0.9.41 is not published at all yet -- publish it so the withdrawal has
    # something to fall back to, the way a fleet already running it would.
    assert client.post("/api/v1/admin/feed/publish",
                       json={"platform": "windows", "version": "0.9.41"}).status_code == 200
    assert dbmod.get_package(conn, "windows", "0.9.42")["is_current"]

    channel, sig = make_channel([good, bad], current={"companion/windows": "0.9.41"})
    patch_opener(monkeypatch, dict(table, **{
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode()}))
    assert client.post("/api/v1/admin/feed/check").status_code == 200
    assert dbmod.get_package(conn, "windows", "0.9.41")["is_current"]
    assert not dbmod.get_package(conn, "windows", "0.9.42")["is_current"]


def test_a_pointer_naming_a_version_the_feed_lacks_publishes_nothing(env, monkeypatch):
    client, conn, settings = env
    assert client.post("/api/v1/admin/feed/policy", json={"policy": "current"}).status_code == 200
    record, body = make_record(version="0.9.41")
    channel, sig = make_channel([record], current={"companion/windows": "0.9.99"})
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), record["url"]: body,
    })
    assert client.post("/api/v1/admin/feed/check").json()["applied"] == []
    assert dbmod.get_package(conn, "windows", "0.9.41") is None


def test_same_version_different_bytes_is_reported_not_silently_409ed(env, monkeypatch):
    client, conn, settings = env
    first, first_body = make_record(version="0.9.41", body=b"ci-run-one")
    channel, sig = make_channel([first])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), first["url"]: first_body,
    })
    assert client.post("/api/v1/admin/feed/check").status_code == 200
    assert client.post("/api/v1/admin/feed/publish",
                       json={"platform": "windows", "version": "0.9.41"}).status_code == 200

    # The vendor re-ran CI and replaced the record in place (publish_feed's
    # upsert / publish_latest --force): same version, different bytes.
    second, second_body = make_record(version="0.9.41", body=b"ci-run-two")
    channel, sig = make_channel([second])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), second["url"]: second_body,
    })
    assert client.post("/api/v1/admin/feed/check").status_code == 200
    view = client.get("/api/v1/admin/feed").json()
    assert view["sha_conflicts"], "the split must be visible to an admin"
    conflict = view["sha_conflicts"][0]
    assert conflict["version"] == "0.9.41"
    assert conflict["published_sha256"] != conflict["feed_sha256"]

    r = client.post("/api/v1/admin/feed/publish",
                    json={"platform": "windows", "version": "0.9.41"})
    assert r.status_code == 409
    assert "DIFFERENT bytes" in r.json()["detail"]


def test_a_record_whose_min_version_exceeds_its_version_is_never_offered(env, monkeypatch):
    """One typo on the release rig (`--min-version 0.9.54` for a 0.9.44
    build) would raise every companion's permanent downgrade floor above the
    build being offered (dash-release-ai-3)."""
    client, conn, settings = env
    bad, bad_body = make_record(version="0.9.44", min_version="0.9.54")
    channel, sig = make_channel([bad])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), bad["url"]: bad_body,
    })
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    assert client.get("/api/v1/admin/feed").json()["available"] == []
    r = client.post("/api/v1/admin/feed/publish",
                    json={"platform": "windows", "version": "0.9.44"})
    assert r.status_code == 404          # not a verified record any more
    assert dbmod.get_package(conn, "windows", "0.9.44") is None


def test_min_version_equal_to_the_version_is_fine(env, monkeypatch):
    client, conn, settings = env
    ok_rec, body = make_record(version="0.9.44", min_version="0.9.44")
    channel, sig = make_channel([ok_rec])
    patch_opener(monkeypatch, {
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(), ok_rec["url"]: body,
    })
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True
    r = client.post("/api/v1/admin/feed/publish",
                    json={"platform": "windows", "version": "0.9.44"})
    assert r.status_code == 200
    assert dbmod.get_package(conn, "windows", "0.9.44") is not None
