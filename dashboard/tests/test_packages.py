"""Upgrade-channel tests: publish auth + integrity, current/rollback/delete,
prune, the token-or-session download route, and the conditional `upgrade`
advertisement on the report/verify responses."""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.api import build_editors_view
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def clear_user(client):
    client.cookies.delete(auth.COOKIE_NAME)
    return client


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "pkg.db"
    settings = Settings(
        db_path=str(db_path),
        report_token="sekrit",
        session_secret=SECRET,
        admin_users=frozenset({"alex"}),
        packages_dir=str(tmp_path / "pkgs"),
    )
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "pw"
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        yield client, conn, settings
        conn.close()


def publish(client, version, body=b"exe-bytes", sha=None, make_current=0):
    sha = sha or hashlib.sha256(body).hexdigest()
    return client.put(
        f"/api/v1/admin/packages/windows/{version}?sha256={sha}&make_current={make_current}",
        content=body,
        headers={"Content-Type": "application/octet-stream"},
    )


def report_payload(version="0.1.0"):
    return {
        "editor_name": "jsmith",
        "machine": "EDIT-PC",
        "companion_version": version,
        "platform": "windows",
        "reported_at": "2026-07-25T10:00:00+00:00",
        "lanes": [{"name": "lane_a_video_up", "state": "idle"}],
    }


# -- publish -----------------------------------------------------------


def test_publish_auth_matrix(env):
    client, conn, settings = env
    assert publish(clear_user(client), "0.2.0").status_code == 401
    assert publish(as_user(client, "jsmith"), "0.2.0").status_code == 403
    resp = publish(as_user(client, "alex"), "0.2.0", body=b"v2-bytes")
    assert resp.status_code == 200
    row = dbmod.get_package(conn, "windows", "0.2.0")
    assert row is not None
    assert row["published_by"] == "alex"
    assert row["size_bytes"] == len(b"v2-bytes")
    stored = settings.packages_path() / "windows" / "ccsync-companion-0.2.0.exe"
    assert stored.read_bytes() == b"v2-bytes"


def test_publish_validation(env):
    client, conn, _settings = env
    as_user(client, "alex")
    assert publish(client, "not-a-version").status_code == 422
    assert client.put(
        "/api/v1/admin/packages/windows/0.2.0?sha256=zzz", content=b"x"
    ).status_code == 422
    assert client.put(
        "/api/v1/admin/packages/amiga/0.2.0?sha256=" + "0" * 64, content=b"x"
    ).status_code == 422


def test_publish_sha_mismatch_leaves_nothing(env):
    client, conn, settings = env
    as_user(client, "alex")
    resp = publish(client, "0.2.0", body=b"real-bytes", sha="0" * 64)
    assert resp.status_code == 400
    assert dbmod.get_package(conn, "windows", "0.2.0") is None
    pkg_dir = settings.packages_path() / "windows"
    assert not any(pkg_dir.glob("*")) if pkg_dir.is_dir() else True


def test_publish_duplicate_version_409(env):
    client, _conn, _settings = env
    as_user(client, "alex")
    assert publish(client, "0.2.0").status_code == 200
    assert publish(client, "0.2.0").status_code == 409


def test_make_current_and_rollback(env):
    client, conn, _settings = env
    as_user(client, "alex")
    publish(client, "0.2.0", body=b"v2", make_current=1)
    publish(client, "0.3.0", body=b"v3", make_current=1)
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.3.0"
    # rollback
    resp = client.post("/api/v1/admin/packages/windows/0.2.0/current")
    assert resp.status_code == 200
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.2.0"
    # exactly one current row
    n = conn.execute(
        "SELECT COUNT(*) FROM companion_packages WHERE platform='windows' AND is_current=1"
    ).fetchone()[0]
    assert n == 1
    # unknown version
    assert client.post("/api/v1/admin/packages/windows/9.9.9/current").status_code == 404


def test_delete_rules(env):
    client, conn, settings = env
    as_user(client, "alex")
    publish(client, "0.2.0", body=b"v2", make_current=1)
    publish(client, "0.3.0", body=b"v3")
    assert client.delete("/api/v1/admin/packages/windows/0.2.0").status_code == 409
    assert client.delete("/api/v1/admin/packages/windows/0.3.0").status_code == 200
    assert dbmod.get_package(conn, "windows", "0.3.0") is None
    assert not (settings.packages_path() / "windows" / "ccsync-companion-0.3.0.exe").exists()
    assert client.delete("/api/v1/admin/packages/windows/0.3.0").status_code == 404


def test_prune_keeps_current_plus_two(env):
    client, conn, settings = env
    as_user(client, "alex")
    publish(client, "0.1.0", body=b"v1", make_current=1)
    for i, v in enumerate(["0.2.0", "0.3.0", "0.4.0", "0.5.0"]):
        publish(client, v, body=f"v{i + 2}".encode())
    rows = dbmod.fetch_companion_packages(conn, "windows")
    versions = {r["version"] for r in rows}
    # current (0.1.0, oldest!) survives; the 2 newest non-current survive.
    assert versions == {"0.1.0", "0.4.0", "0.5.0"}
    assert not (settings.packages_path() / "windows" / "ccsync-companion-0.2.0.exe").exists()
    assert (settings.packages_path() / "windows" / "ccsync-companion-0.5.0.exe").exists()


# -- download ----------------------------------------------------------


def test_download_auth_and_integrity(env):
    client, _conn, _settings = env
    body = b"the-exe"
    publish(as_user(client, "alex"), "0.2.0", body=body, make_current=1)
    clear_user(client)

    url = "/api/v1/companion/package/windows/0.2.0"
    assert client.get(url).status_code == 401                       # anonymous: middleware
    resp = client.get(url, headers={"X-CCSync-Token": "sekrit"})    # companion token
    assert resp.status_code == 200
    assert resp.content == body
    assert resp.headers["X-CCSync-SHA256"] == hashlib.sha256(body).hexdigest()
    assert resp.headers["X-CCSync-Version"] == "0.2.0"
    resp = as_user(client, "jsmith").get(url)                       # any session works
    assert resp.status_code == 200
    clear_user(client)
    assert client.get(
        "/api/v1/companion/package/windows/9.9.9", headers={"X-CCSync-Token": "sekrit"}
    ).status_code == 404


# -- advertisement -----------------------------------------------------


def test_report_advertises_upgrade_only_when_outdated(env):
    client, _conn, _settings = env
    headers = {"X-CCSync-Token": "sekrit"}
    # nothing published yet -> no key
    resp = client.post("/api/v1/report", json=report_payload("0.1.0"), headers=headers)
    assert "upgrade" not in resp.json()

    publish(as_user(client, "alex"), "0.2.0", body=b"v2", make_current=1)
    clear_user(client)

    resp = client.post("/api/v1/report", json=report_payload("0.1.0"), headers=headers)
    upgrade = resp.json()["upgrade"]
    assert upgrade["version"] == "0.2.0"
    assert upgrade["url"] == "/api/v1/companion/package/windows/0.2.0"
    assert upgrade["sha256"] == hashlib.sha256(b"v2").hexdigest()

    # up to date -> no key; version unreported -> no key
    resp = client.post("/api/v1/report", json=report_payload("0.2.0"), headers=headers)
    assert "upgrade" not in resp.json()
    payload = report_payload()
    del payload["companion_version"]
    resp = client.post("/api/v1/report", json=payload, headers=headers)
    assert "upgrade" not in resp.json()


def test_verify_advertises_upgrade(env):
    client, _conn, _settings = env
    publish(as_user(client, "alex"), "0.2.0", body=b"v2", make_current=1)
    clear_user(client)

    resp = client.post("/api/v1/verify", json={
        "username": "jsmith", "password": "pw",
        "companion_version": "0.1.0", "platform": "windows",
    })
    body = resp.json()
    assert body["ok"] is True
    assert body["role"] == "editor"
    assert body["upgrade"]["version"] == "0.2.0"

    resp = client.post("/api/v1/verify", json={
        "username": "alex", "password": "pw",
        "companion_version": "0.2.0", "platform": "windows",
    })
    body = resp.json()
    assert body["role"] == "base"
    assert "upgrade" not in body

    # older companion sending no version fields still verifies
    resp = client.post("/api/v1/verify", json={"username": "jsmith", "password": "pw"})
    assert resp.json()["ok"] is True


def test_editors_view_outdated_flag(env):
    client, conn, _settings = env
    headers = {"X-CCSync-Token": "sekrit"}
    client.post("/api/v1/report", json=report_payload("0.1.0"), headers=headers)

    view = build_editors_view(conn)
    assert view["current_companion_version"] is None
    assert view["editors"][0]["companion_outdated"] is False

    publish(as_user(client, "alex"), "0.2.0", body=b"v2", make_current=1)
    view = build_editors_view(conn)
    assert view["current_companion_version"] == "0.2.0"
    assert view["editors"][0]["companion_outdated"] is True


def test_migration_reaches_v7(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='companion_packages'"
    ).fetchone() is not None
