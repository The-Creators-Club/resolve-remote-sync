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


def publish(client, version, body=b"exe-bytes", sha=None, make_current=0, prune=0):
    return publish_platform(client, "windows", version, body=body, sha=sha,
                            make_current=make_current, prune=prune)


def publish_platform(client, platform, version, body=b"exe-bytes", sha=None,
                     make_current=0, prune=0):
    sha = sha or hashlib.sha256(body).hexdigest()
    return client.put(
        f"/api/v1/admin/packages/{platform}/{version}"
        f"?sha256={sha}&make_current={make_current}&prune={prune}",
        content=body,
        headers={"Content-Type": "application/octet-stream"},
    )


def report_headers(editor="jsmith"):
    """Both companion headers -- X-CCSync-Identity is required on reports."""
    return {"X-CCSync-Token": "sekrit",
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


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


def test_publish_does_not_prune_by_default(env):
    """Publishing must never destroy older build artifacts as a side effect:
    they are the rollback material, and the standing rule is that nothing is
    deleted without being asked (see the package auto-prune finding)."""
    client, conn, settings = env
    as_user(client, "alex")
    publish(client, "0.1.0", body=b"v1", make_current=1)
    for i, v in enumerate(["0.2.0", "0.3.0", "0.4.0", "0.5.0"]):
        publish(client, v, body=f"v{i + 2}".encode())
    versions = {r["version"] for r in dbmod.fetch_companion_packages(conn, "windows")}
    assert versions == {"0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0"}
    assert (settings.packages_path() / "windows" / "ccsync-companion-0.2.0.exe").exists()


def test_prune_opt_in_keeps_current_plus_two(env):
    client, conn, settings = env
    as_user(client, "alex")
    publish(client, "0.1.0", body=b"v1", make_current=1)
    for i, v in enumerate(["0.2.0", "0.3.0", "0.4.0"]):
        publish(client, v, body=f"v{i + 2}".encode())
    # only the explicitly opted-in publish prunes
    publish(client, "0.5.0", body=b"v5", prune=1)
    rows = dbmod.fetch_companion_packages(conn, "windows")
    versions = {r["version"] for r in rows}
    # current (0.1.0, oldest!) survives; the 2 newest non-current survive.
    assert versions == {"0.1.0", "0.4.0", "0.5.0"}
    assert not (settings.packages_path() / "windows" / "ccsync-companion-0.2.0.exe").exists()
    assert (settings.packages_path() / "windows" / "ccsync-companion-0.5.0.exe").exists()
    # every surviving row still has its file: the DB commit happens BEFORE any
    # unlink, so a failed commit can never leave a row pointing at a gone exe.
    for row in rows:
        assert (settings.packages_path() / "windows" / row["filename"]).exists()


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
    headers = report_headers()
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
    headers = report_headers()
    client.post("/api/v1/report", json=report_payload("0.1.0"), headers=headers)

    view = build_editors_view(conn)
    assert view["current_companion_version"] is None
    assert view["editors"][0]["companion_outdated"] is False

    publish(as_user(client, "alex"), "0.2.0", body=b"v2", make_current=1)
    view = build_editors_view(conn)
    assert view["current_companion_version"] == "0.2.0"
    assert view["editors"][0]["companion_outdated"] is True


def test_migration_reaches_v7(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == dbmod.SCHEMA_VERSION


def test_editors_view_outdated_flag_is_per_platform(env):
    """X-5: a machine's out-of-date flag must compare its companion_version
    against the CURRENT PACKAGE FOR ITS OWN REPORTED PLATFORM -- a macOS
    companion must never be compared against the Windows release (and an
    unreported platform falls back to windows, preserving old behaviour for
    pre-platform-field companions)."""
    client, conn, _settings = env
    headers = report_headers()

    mac_payload = report_payload("1.0.0")
    mac_payload["editor_name"] = "mchan"
    mac_payload["machine"] = "MAC-1"
    mac_payload["platform"] = "macos"
    client.post("/api/v1/report", json=mac_payload, headers=report_headers("mchan"))

    win_payload = report_payload("0.1.0")  # jsmith / EDIT-PC / windows
    client.post("/api/v1/report", json=win_payload, headers=headers)

    # Publish a new WINDOWS current version only -- the mac machine is on a
    # perfectly current macOS build that simply has no published counterpart.
    publish(as_user(client, "alex"), "0.2.0", body=b"winv2", make_current=1)
    clear_user(client)

    view = build_editors_view(conn)
    by_machine = {e["machine"]: e for e in view["editors"]}
    assert by_machine["EDIT-PC"]["companion_outdated"] is True     # windows, 0.1.0 != 0.2.0
    assert by_machine["MAC-1"]["companion_outdated"] is False      # macos: no macos package published

    # Now publish a MATCHING macOS current version -- the mac machine is
    # up to date; publishing a macos package must not affect the windows
    # comparison either.
    publish_platform(as_user(client, "alex"), "macos", "1.0.0", body=b"macv1", make_current=1)
    clear_user(client)
    view = build_editors_view(conn)
    by_machine = {e["machine"]: e for e in view["editors"]}
    assert by_machine["MAC-1"]["companion_outdated"] is False
    assert by_machine["EDIT-PC"]["companion_outdated"] is True

    # A newer macos release flips it.
    publish_platform(as_user(client, "alex"), "macos", "1.1.0", body=b"macv1b", make_current=1)
    clear_user(client)
    view = build_editors_view(conn)
    by_machine = {e["machine"]: e for e in view["editors"]}
    assert by_machine["MAC-1"]["companion_outdated"] is True
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='companion_packages'"
    ).fetchone() is not None


# -- upload bounds (the publish route streams a raw body) -------------------


def test_publish_body_is_capped_by_content_length(env):
    """The publish route streamed an unbounded body straight onto the /data
    dataset -- an admin session, but a filled dataset takes the SQLite DB
    down with it. Rejected from Content-Length, before anything is written."""
    from ccsync_dashboard.app import MAX_PACKAGE_BODY_BYTES

    client, _conn, settings = env
    as_user(client, "alex")
    resp = client.put(
        "/api/v1/admin/packages/windows/9.9.9?sha256=" + "a" * 64,
        content=b"x" * 16,
        headers={"Content-Type": "application/octet-stream",
                 "Content-Length": str(MAX_PACKAGE_BODY_BYTES + 1)},
    )
    assert resp.status_code == 413
    # rejected in the middleware, so the destination dir was never even made
    assert not (settings.packages_path() / "windows").exists()


def test_publish_counts_the_bytes_it_actually_receives(env, monkeypatch):
    """Content-Length is advisory for a chunked request, so the running
    total is the real ceiling. Nothing is published and no .part survives."""
    from ccsync_dashboard import app as appmod

    client, conn, settings = env
    monkeypatch.setattr(appmod, "MAX_PACKAGE_BODY_BYTES", 8)
    as_user(client, "alex")
    resp = publish(client, "9.9.9", body=b"far too many bytes for this cap")
    assert resp.status_code == 413
    assert dbmod.get_package(conn, "windows", "9.9.9") is None
    assert list((settings.packages_path() / "windows").glob("*.part")) == []


def test_publish_still_works_at_the_default_cap(env):
    client, conn, _settings = env
    as_user(client, "alex")
    assert publish(client, "0.3.0", body=b"a normal little exe").status_code == 200
    assert dbmod.get_package(conn, "windows", "0.3.0") is not None


# -- per-machine version on the fleet view (release hygiene) ---------------


def test_fleet_view_flags_a_stale_per_machine_version(env):
    """machine_state carries the per-machine build (schema v10) and outlives
    a lane_report_current prune, so a stale machine cannot go invisible
    exactly when you most want to see it."""
    client, conn, _settings = env
    client.post("/api/v1/report", json=report_payload("0.1.0"), headers=report_headers())
    publish(as_user(client, "alex"), "0.2.0", body=b"v2", make_current=1)
    clear_user(client)

    versions = dbmod.fetch_companion_version_map(conn)
    assert versions[("jsmith", "EDIT-PC")]["companion_version"] == "0.1.0"
    assert versions[("jsmith", "EDIT-PC")]["platform"] == "windows"

    entry = build_editors_view(conn)["editors"][0]
    assert entry["companion_version"] == "0.1.0"
    assert entry["current_companion_version"] == "0.2.0"
    assert entry["companion_outdated"] is True
    assert entry["companion_version_unknown"] is False

    # ...and the fleet grid says so, per machine
    as_user(client, "alex")
    page = client.get("/partials/fleet")
    assert page.status_code == 200
    assert "[ OUT OF DATE: 0.2.0 ]" in page.text
    assert "EDIT-PC" in page.text


def test_fleet_view_keeps_a_machine_whose_lane_rows_were_pruned(env):
    client, conn, _settings = env
    client.post("/api/v1/report", json=report_payload("0.1.0"), headers=report_headers())
    conn.execute("DELETE FROM lane_report_current")     # what db.prune does after 30 days
    conn.commit()

    (entry,) = build_editors_view(conn)["editors"]
    assert entry["machine"] == "EDIT-PC"
    assert entry["companion_version"] == "0.1.0"
    assert entry["lanes"] == []


def test_fleet_view_tolerates_a_report_without_a_version(env):
    """Companions predating the upgrade channel send no companion_version:
    flag it as unknown, never as up to date."""
    client, conn, _settings = env
    payload = report_payload()
    payload.pop("companion_version")
    client.post("/api/v1/report", json=payload, headers=report_headers())
    publish(as_user(client, "alex"), "0.2.0", body=b"v2", make_current=1)
    clear_user(client)

    (entry,) = build_editors_view(conn)["editors"]
    assert entry["companion_version"] is None
    assert entry["companion_version_unknown"] is True
    assert entry["companion_outdated"] is False        # unknown != "differs"

    as_user(client, "alex")
    assert "[ VERSION UNKNOWN ]" in client.get("/partials/fleet").text


# -- kind=onboard: the [ INSTALLER ] download --------------------------


def publish_onboard(client, version, body=b"onboard-bytes", sha=None,
                    make_current=0, platform="windows"):
    sha = sha or hashlib.sha256(body).hexdigest()
    return client.put(
        f"/api/v1/admin/packages/{platform}/{version}"
        f"?kind=onboard&sha256={sha}&make_current={make_current}",
        content=body,
        headers={"Content-Type": "application/octet-stream"},
    )


def test_migration_v11_preserves_published_rows(tmp_path):
    """A live pre-v11 database's package rows (including which one is
    current) must survive the kind-column table rebuild as kind=companion."""
    connection = dbmod.connect(tmp_path / "mig.db")
    dbmod.migrate(connection, [s for s in dbmod._MIGRATION_STEPS if s[0] <= 10])
    connection.execute(
        """INSERT INTO companion_packages
             (version, platform, filename, sha256, size_bytes,
              published_at, published_by, is_current)
           VALUES ('0.4.3', 'windows', 'ccsync-companion-0.4.3.exe', ?,
                   123, '2026-07-25T00:00:00+00:00', 'alex', 1)""",
        ("a" * 64,),
    )
    connection.commit()
    dbmod.migrate(connection)
    row = dbmod.get_current_package(connection, "windows")
    assert row is not None
    assert row["version"] == "0.4.3"
    assert row["kind"] == "companion"
    connection.close()


def test_onboard_kind_versions_and_currency_are_separate(env):
    client, conn, _settings = env
    as_user(client, "alex")
    assert publish(client, "1.0.0", body=b"companion", make_current=1).status_code == 200
    # The same (platform, version) under the other kind is NOT a duplicate...
    assert publish_onboard(client, "1.0.0", body=b"installer", make_current=1).status_code == 200
    # ...but within a kind it still is.
    assert publish_onboard(client, "1.0.0").status_code == 409

    assert dbmod.get_current_package(conn, "windows")["version"] == "1.0.0"
    onboard = dbmod.get_current_package(conn, "windows", kind="onboard")
    assert onboard["filename"] == "ccsync-onboard-1.0.0.exe"

    # Flipping the onboard current never touches which companion the fleet
    # is offered.
    publish_onboard(client, "1.0.1", body=b"installer2", make_current=1)
    assert dbmod.get_current_package(conn, "windows")["version"] == "1.0.0"
    assert dbmod.get_current_package(conn, "windows", kind="onboard")["version"] == "1.0.1"

    # macOS onboard packages are scripts, not exes.
    assert publish_onboard(client, "1.0.0", platform="macos").status_code == 200
    assert dbmod.get_package(conn, "macos", "1.0.0", kind="onboard")["filename"] == "ccsync-onboard-1.0.0.sh"


def test_upgrade_never_offers_the_onboard_package(env):
    """upgrade.py renames whatever it downloads over the running companion
    exe -- offering onboard.exe there would brick the machine."""
    client, _conn, _settings = env
    publish_onboard(as_user(client, "alex"), "1.0.0", make_current=1)
    clear_user(client)
    resp = client.post("/api/v1/report", json=report_payload("0.1.0"),
                       headers=report_headers())
    assert "upgrade" not in resp.json()


def test_installer_download_route(env):
    client, _conn, _settings = env
    body = b"the-installer"
    publish_onboard(as_user(client, "alex"), "1.0.4", body=body, make_current=1)
    clear_user(client)

    # Anonymous browser: bounced to login with the destination preserved.
    resp = client.get("/download", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]

    # Any signed-in user, Windows UA: lands on the windows package.
    as_user(client, "jsmith")
    resp = client.get("/download", follow_redirects=False, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/download/windows"
    resp = client.get("/download/windows")
    assert resp.status_code == 200
    assert resp.content == body
    assert "ccsync-onboard-1.0.4.exe" in resp.headers["content-disposition"]
    assert resp.headers["X-CCSync-Version"] == "1.0.4"

    # Mac UA routes to the macos package, which is not published yet: a
    # plain 404 with the publish command, not a broken download.
    resp = client.get("/download", follow_redirects=False, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    assert resp.headers["location"] == "/download/macos"
    assert client.get("/download/macos").status_code == 404
    assert client.get("/download/amiga").status_code == 404


# -- version="current": discovery for a fresh bootstrap ----------------


def test_download_current_serves_the_current_package(env):
    """A fresh machine has no version to ask for, so it asks for "current"
    and verifies the bytes against the headers."""
    client, _conn, _settings = env
    publish(as_user(client, "alex"), "0.2.0", body=b"v2-bytes", make_current=1)
    publish(client, "0.3.0", body=b"v3-bytes", make_current=1)
    clear_user(client)

    resp = client.get("/api/v1/companion/package/windows/current",
                      headers={"X-CCSync-Token": "sekrit"})
    assert resp.status_code == 200
    assert resp.content == b"v3-bytes"
    assert resp.headers["X-CCSync-Version"] == "0.3.0"
    assert resp.headers["X-CCSync-SHA256"] == hashlib.sha256(b"v3-bytes").hexdigest()
    assert "ccsync-companion-0.3.0.exe" in resp.headers["content-disposition"]

    # An admin rollback moves "current" backwards, and so does this route.
    as_user(client, "alex").post("/api/v1/admin/packages/windows/0.2.0/current")
    clear_user(client)
    resp = client.get("/api/v1/companion/package/windows/current",
                      headers={"X-CCSync-Token": "sekrit"})
    assert resp.content == b"v2-bytes"
    assert resp.headers["X-CCSync-Version"] == "0.2.0"


def test_download_current_404_when_nothing_is_current(env):
    client, _conn, _settings = env
    # Published but never made current -- discovery must not guess.
    publish(as_user(client, "alex"), "0.2.0", body=b"v2-bytes", make_current=0)
    clear_user(client)
    token = {"X-CCSync-Token": "sekrit"}

    resp = client.get("/api/v1/companion/package/windows/current", headers=token)
    assert resp.status_code == 404
    assert "current" in resp.json()["detail"]
    # Nothing at all published for the other platform/kind either.
    assert client.get("/api/v1/companion/package/macos/current",
                      headers=token).status_code == 404
    assert client.get("/api/v1/companion/package/windows/current?kind=onboard",
                      headers=token).status_code == 404


def test_download_current_is_per_platform_and_per_kind(env):
    """kind=onboard&platform=macos is exactly what the mac bootstrap asks
    for: it must get the .sh, never the Windows exe or the companion."""
    client, _conn, _settings = env
    as_user(client, "alex")
    publish(client, "0.2.0", body=b"win-companion", make_current=1)
    publish_onboard(client, "1.0.4", body=b"win-installer", make_current=1)
    publish_platform(client, "macos", "0.2.0", body=b"mac-companion", make_current=1)
    publish_onboard(client, "1.0.4", body=b"#!/bin/sh\necho hi\n",
                    make_current=1, platform="macos")
    clear_user(client)
    token = {"X-CCSync-Token": "sekrit"}

    resp = client.get("/api/v1/companion/package/macos/current?kind=onboard",
                      headers=token)
    assert resp.status_code == 200
    assert resp.content == b"#!/bin/sh\necho hi\n"
    assert resp.headers["X-CCSync-Version"] == "1.0.4"
    assert resp.headers["X-CCSync-SHA256"] == hashlib.sha256(b"#!/bin/sh\necho hi\n").hexdigest()
    assert "ccsync-onboard-1.0.4.sh" in resp.headers["content-disposition"]

    # The three neighbouring channels stay distinct.
    assert client.get("/api/v1/companion/package/macos/current",
                      headers=token).content == b"mac-companion"
    assert client.get("/api/v1/companion/package/windows/current",
                      headers=token).content == b"win-companion"
    assert client.get("/api/v1/companion/package/windows/current?kind=onboard",
                      headers=token).content == b"win-installer"


def test_download_current_is_token_gated(env):
    """The middleware's path-prefix gate covers "current" like any other
    version -- no anonymous discovery of the installer."""
    client, _conn, _settings = env
    publish_onboard(as_user(client, "alex"), "1.0.4", make_current=1, platform="macos")
    clear_user(client)

    url = "/api/v1/companion/package/macos/current?kind=onboard"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"X-CCSync-Token": "wrong"}).status_code == 401
    assert client.get(url, headers={"X-CCSync-Token": "sekrit"}).status_code == 200
    assert as_user(client, "jsmith").get(url).status_code == 200
