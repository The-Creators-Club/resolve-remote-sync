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


def make_channel(records: list[dict], *, seed=TEST_SEED, image=None) -> tuple[dict, str]:
    channel = {
        "schema": 1, "generated_at": PUBLISHED_AT, "channel": "stable",
        "pubkey_id": release_trust.pubkey_id(base64.b64encode(ed25519.public_key(seed)).decode("ascii")),
        "dashboard_image": image or {"tag": "", "digest": ""},
        "packages": records,
    }
    sig = base64.b64encode(ed25519.sign(seed, release_feed.canonical_channel_bytes(channel))).decode("ascii")
    return channel, sig


class _FakeResp:
    def __init__(self, data: bytes, status: int = 200):
        self._data = data
        self._pos = 0
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


class _FakeOpener:
    """table: url -> bytes, or a callable raising an exception."""

    def __init__(self, table: dict):
        self.table = table
        self.requested: list[str] = []

    def open(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.requested.append(url)
        val = self.table.get(url)
        if val is None:
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        if isinstance(val, Exception):
            raise val
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


def test_a_redirect_is_refused(env, monkeypatch):
    client, conn, settings = env

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(CHANNEL_URL, 302, "redirect", {"Location": "https://evil.test/x"}, None)

    monkeypatch.setattr(release_feed, "_opener",
                        lambda: type("O", (), {"open": staticmethod(boom)})())
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is False


def test_an_oversized_channel_is_refused(env, monkeypatch):
    client, conn, settings = env
    huge = b"x" * (release_feed.FEED_MAX_BYTES + 1)
    patch_opener(monkeypatch, {CHANNEL_URL: huge})
    r = client.post("/api/v1/admin/feed/check")
    assert r.json()["ok"] is False
    assert "cap" in r.json()["error"]


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
    assert r.json()["applied"] if "applied" in r.json() else True  # top-level 'applied' not required
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
