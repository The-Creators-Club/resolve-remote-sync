"""The page an editor's first click lands on (OPS-20, sweep 2026-09-03).

With no Authenticode certificate yet, `onboard.exe` from this page meets
"Windows protected your PC", whose default button is **Don't run** and whose
way through is hidden behind "More info". That was documented for the
DEVELOPER in three places (KNOWN_BUGS, RELEASE.md, a drift check) and for the
EDITOR nowhere, while START_HERE.md explained the macOS quarantine equivalent
in detail.

    cd E:\\Projects\\resolve-remote-sync\\dashboard
    .venv\\Scripts\\python.exe -m pytest tests/test_installer_page.py -q
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from test_packages import TEST_PUBKEY, signed_query

SECRET = "s" * 32


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "pkg.db"),
        report_token="sekrit",
        session_secret=SECRET,
        admin_users=frozenset({"owen"}),
        packages_dir=str(tmp_path / "pkgs"),
        release_pubkeys=(TEST_PUBKEY,),
    )
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "pw"
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "pkg.db")
        yield client, conn, settings
        conn.close()


def _publish(client, platform="windows", version="1.0.4", body=b"installer"):
    sha = hashlib.sha256(body).hexdigest()
    suffix = signed_query("onboard", platform, version, body, sha=sha)
    resp = client.put(
        f"/api/v1/admin/packages/{platform}/{version}"
        f"?kind=onboard&sha256={sha}&make_current=1{suffix}",
        content=body, headers={"Content-Type": "application/octet-stream"})
    assert resp.status_code == 200, resp.text
    return sha


def _page(client):
    resp = client.get("/installer")
    assert resp.status_code == 200, resp.text
    return resp.text


def test_the_windows_pick_prepares_the_editor_for_smartscreen(env):
    client, _conn, _settings = env
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    sha = _publish(client)

    page = _page(client)
    windows = page.split("[ WINDOWS ]", 1)[1].split("[ MACOS ]", 1)[0]
    assert "Windows protected your PC" in windows
    assert "More info" in windows and "Run anyway" in windows
    # The fingerprint is already on the page; the paragraph points at it
    # rather than asking anyone to find it.
    assert sha[:16] in windows


def test_the_mac_pick_does_not_carry_the_windows_warning(env):
    """macOS meets Gatekeeper, not SmartScreen, and START_HERE.md is where
    that one is explained."""
    client, _conn, _settings = env
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    _publish(client, platform="macos", body=b"mac-installer")

    macos = _page(client).split("[ MACOS ]", 1)[1]
    assert "Windows protected your PC" not in macos
