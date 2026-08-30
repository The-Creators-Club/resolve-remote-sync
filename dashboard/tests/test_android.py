"""android.py + tools/android -- the TWA's asset links and its build tools
(MOBILE_PLAN.md §4 M5, 2026-08-30).

The property under all of this: a Trusted Web Activity that cannot verify
against the origin opens with a URL bar and says NOTHING. So every refusal
here is pinned as a refusal an admin can see -- an empty statement, a rejected
fingerprint, a `[ CHECK ]` that reads back what is actually being served --
rather than as a 500 nobody would connect to the symptom.
"""
from __future__ import annotations

import http.server
import json
import socket
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import android, auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import site_store
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "android"))

import check_assetlinks                                             # noqa: E402
import twa_manifest                                                 # noqa: E402

SECRET = "test-secret"
PACKAGE = "net.ts.example.nas.ccsync"
# 32 hex pairs, which is what keytool prints. Built rather than typed so a
# short one cannot creep in unnoticed.
FP1 = ":".join(f"{i:02X}" for i in range(32))
FP2 = ":".join(f"{(i * 3) % 256:02X}" for i in range(32))

FIXTURE = REPO_ROOT / "tools" / "android" / "fixture" / "manifest.webmanifest"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "android.db"
    settings = Settings(
        db_path=str(db_path),
        session_secret=SECRET,
        admin_users=frozenset({"owen"}),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        yield client, conn, settings
        conn.close()


def configure(client, package=PACKAGE, fingerprints=FP1):
    return client.post("/api/v1/setup/android", data={
        "package_name": package,
        "sha256_cert_fingerprints": fingerprints,
    })


# ------------------------------------------------- /.well-known/assetlinks.json

def test_assetlinks_is_open_and_empty_by_default(env):
    """No session, and no Android app configured: an empty array, not a 401
    and not a half-statement. Chrome fetches this with no cookie jar."""
    client, conn, settings = env
    resp = client.get("/.well-known/assetlinks.json")
    assert resp.status_code == 200
    assert resp.json() == []


def test_assetlinks_content_type_and_cache_header(env):
    client, conn, settings = env
    resp = client.get("/.well-known/assetlinks.json")
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers["cache-control"] == "max-age=3600"


def test_assetlinks_serves_the_configured_statement(env):
    client, conn, settings = env
    as_user(client, "owen")
    assert configure(client).status_code == 200

    resp = TestClient(client.app).get("/.well-known/assetlinks.json")
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": PACKAGE,
                "sha256_cert_fingerprints": [FP1],
            },
        }
    ]


def test_assetlinks_carries_every_fingerprint_in_order(env):
    """A key hand-over has two valid signers at once; dropping the old one
    mid-rollout breaks every installed copy."""
    client, conn, settings = env
    as_user(client, "owen")
    configure(client, fingerprints=f"{FP1}\n{FP2}\n")
    body = TestClient(client.app).get("/.well-known/assetlinks.json").json()
    assert body[0]["target"]["sha256_cert_fingerprints"] == [FP1, FP2]


def test_a_package_with_no_fingerprint_is_still_an_empty_statement(env):
    """Half a statement verifies nothing; serving one would only make a
    broken setup look configured."""
    client, conn, settings = env
    as_user(client, "owen")
    configure(client, fingerprints="")
    assert TestClient(client.app).get("/.well-known/assetlinks.json").json() == []


def test_statements_for_is_the_pure_shape():
    assert android.statements_for(None) == []
    assert android.statements_for({"package_name": "", "sha256_cert_fingerprints": [FP1]}) == []
    doc = android.statements_for(
        {"package_name": PACKAGE, "sha256_cert_fingerprints": [FP1.lower()]})
    assert doc[0]["target"]["sha256_cert_fingerprints"] == [FP1]


# --------------------------------------------------------- the manifest fields

def test_the_two_fields_validate(env):
    assert site_store.validate("android.package_name", " com.example.app ") == "com.example.app"
    assert site_store.validate("android.package_name", "") == ""
    with pytest.raises(site_store.SiteValidationError):
        site_store.validate("android.package_name", "notapackage")
    with pytest.raises(site_store.SiteValidationError):
        site_store.validate("android.package_name", "1bad.example")

    assert site_store.validate("android.sha256_cert_fingerprints", "") == ""
    assert site_store.validate(
        "android.sha256_cert_fingerprints", f"SHA256: {FP1.lower()}") == FP1
    assert site_store.validate(
        "android.sha256_cert_fingerprints", f"{FP1}\n{FP2}") == f"{FP1},{FP2}"
    # the same key pasted twice is one entry, not a duplicated statement
    assert site_store.validate(
        "android.sha256_cert_fingerprints", f"{FP1}\n{FP1}") == FP1
    with pytest.raises(site_store.SiteValidationError):
        site_store.validate("android.sha256_cert_fingerprints", "AA:BB:CC")


def test_the_manifest_carries_an_android_block(env):
    client, conn, settings = env
    manifest = site_store.resolved_manifest(conn, settings)
    assert manifest["android"] == {"package_name": "", "sha256_cert_fingerprints": []}


def test_the_open_site_manifest_does_not_publish_them(env):
    """`GET /api/v1/site` is the installer/companion contract; nothing there
    needs the app's identity, and a field is added to it only when a client
    needs one (api.api_site)."""
    client, conn, settings = env
    as_user(client, "owen")
    configure(client)
    body = TestClient(client.app).get("/api/v1/site").json()
    assert "android" not in body


def test_export_and_import_round_trip_the_android_block(env):
    """A NAS migration that lost the asset links would relaunch every
    editor's app with a URL bar and nothing saying why."""
    client, conn, settings = env
    as_user(client, "owen")
    configure(client, fingerprints=f"{FP1}\n{FP2}")

    text = client.get("/api/v1/admin/site/export").text
    assert "[android]" in text
    assert f'package_name = "{PACKAGE}"' in text

    parsed = site_store.import_toml(text)
    assert parsed["android.package_name"] == PACKAGE
    assert parsed["android.sha256_cert_fingerprints"] == f"{FP1},{FP2}"


def test_the_admin_site_route_writes_them_too(env):
    """The two fields ride the same manifest as every other one, so the JSON
    route, the history and the undo all reach them without a second path."""
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.put("/api/v1/admin/site", json={"values": {
        "android.package_name": PACKAGE,
        "android.sha256_cert_fingerprints": FP1,
    }})
    assert resp.status_code == 200
    assert resp.json()["android"]["package_name"] == PACKAGE


# ------------------------------------------------------------ the settings API

def test_save_requires_a_session(env):
    client, conn, settings = env
    assert configure(client).status_code == 401


def test_save_refuses_a_non_admin(env):
    client, conn, settings = env
    as_user(client, "editor1")
    assert configure(client).status_code == 403


def test_save_renders_the_panel_back(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = configure(client)
    assert resp.status_code == 200
    assert 'id="android-settings"' in resp.text
    assert PACKAGE in resp.text
    assert FP1 in resp.text


def test_a_bad_fingerprint_writes_nothing_and_says_so(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.post("/api/v1/setup/android", data={
        "package_name": PACKAGE, "sha256_cert_fingerprints": "AA:BB:CC"})
    assert resp.status_code == 200               # the panel, with a banner
    assert "not a SHA-256 fingerprint" in resp.text
    assert TestClient(client.app).get("/.well-known/assetlinks.json").json() == []


def test_check_reads_back_what_is_served(env):
    client, conn, settings = env
    as_user(client, "owen")
    configure(client)
    resp = client.post("/api/v1/setup/android/check")
    assert resp.status_code == 200
    assert "[ SERVING ]" in resp.text
    assert PACKAGE in resp.text and FP1 in resp.text


def test_check_says_empty_when_nothing_is_configured(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.post("/api/v1/setup/android/check")
    assert "[ EMPTY ]" in resp.text


def test_check_requires_admin(env):
    client, conn, settings = env
    assert client.post("/api/v1/setup/android/check").status_code == 401


def test_check_prints_googles_url_rather_than_calling_it(env):
    """The container runs --workers 1: a self-request from inside a handler is
    a deadlock, and a check that silently failed open would be worse than no
    check. So the panel prints the URL the admin opens themselves."""
    client, conn, settings = env
    as_user(client, "owen")
    client.put("/api/v1/admin/site",
               json={"values": {"dashboard_url": "https://nas.example.ts.net:9443"}})
    configure(client)
    resp = client.post("/api/v1/setup/android/check")
    assert "digitalassetlinks.googleapis.com" in resp.text
    assert "nas.example.ts.net" in resp.text


def test_check_url_needs_an_origin():
    assert android.check_url("") == ""
    assert android.check_url("nas.example") == ""
    assert android.check_url("https://nas.example/").startswith(
        "https://digitalassetlinks.googleapis.com/v1/statements:list?")


# --------------------------------------------------------------- the settings page

def test_the_settings_page_includes_the_panel_once(env):
    client, conn, settings = env
    as_user(client, "owen")
    page = client.get("/admin/settings")
    assert page.status_code == 200
    assert page.text.count('id="android-settings"') == 1
    assert "[ ANDROID ]" in page.text


# --------------------------------------------------- tools/android/twa_manifest

def test_package_from_origin_reverses_the_host():
    assert twa_manifest.package_from_origin(
        "https://nas.example.ts.net:9443") == "net.ts.example.nas.ccsync"


def test_package_from_origin_repairs_labels_java_would_refuse():
    """A DNS label may start with a digit and carry hyphens; an Android
    application id may do neither -- and aapt2 refuses a LEADING UNDERSCORE
    too, which is a perfectly good Java identifier (measured on a runner
    2026-08-30, the first android.yml run: "'_1._0._0._127.ccsync' is not a
    valid Android package name")."""
    assert twa_manifest.package_from_origin(
        "https://9-lives.studio.example") == "example.studio.n9_lives.ccsync"
    assert twa_manifest.package_from_origin(
        "http://127.0.0.1:8765") == "n1.n0.n0.n127.ccsync"
    for origin in ("https://9-lives.studio.example", "http://127.0.0.1:8765"):
        for segment in twa_manifest.package_from_origin(origin).split("."):
            assert "a" <= segment[0] <= "z"
            assert all(ch.isalnum() or ch == "_" for ch in segment)


def test_twa_manifest_is_written_from_the_fixture(tmp_path):
    rc = twa_manifest.main([
        "--origin", "https://nas.example.ts.net:9443",
        "--manifest", str(FIXTURE),
        "--out", str(tmp_path),
    ])
    assert rc == 0
    doc = json.loads((tmp_path / "twa-manifest.json").read_text(encoding="utf-8"))
    assert doc["packageId"] == "net.ts.example.nas.ccsync"
    assert doc["host"] == "nas.example.ts.net"
    assert doc["startUrl"] == "/"
    assert doc["display"] == "standalone"
    assert doc["enableNotifications"] is False
    assert doc["fallbackType"] == "customtabs"
    assert doc["shortcuts"] == []
    assert doc["themeColor"] == "#0a0a0d"
    # the BIGGEST icon of each purpose, resolved against the manifest's own URL
    assert doc["iconUrl"].endswith("icon-512.png")
    assert doc["maskableIconUrl"].endswith("icon-512-maskable.png")


def test_twa_manifest_takes_a_package_override(tmp_path):
    twa_manifest.main([
        "--origin", "https://nas.example.ts.net:9443", "--manifest", str(FIXTURE),
        "--package", "com.studio.ccsync", "--out", str(tmp_path),
    ])
    doc = json.loads((tmp_path / "twa-manifest.json").read_text(encoding="utf-8"))
    assert doc["packageId"] == "com.studio.ccsync"


def test_twa_manifest_never_writes_a_password(tmp_path):
    """A keystore path and an alias are configuration; the two passwords are
    the environment's, and this file is committed-shaped text."""
    twa_manifest.main([
        "--origin", "https://nas.example.ts.net", "--manifest", str(FIXTURE),
        "--out", str(tmp_path),
    ])
    text = (tmp_path / "twa-manifest.json").read_text(encoding="utf-8")
    assert "assword" not in text
    assert json.loads(text)["signingKey"] == {
        "path": "./android.keystore", "alias": "android"}


def test_the_fixture_manifest_is_what_bubblewrap_needs():
    """The CI job builds against this file. Bubblewrap refuses a manifest with
    no 512px icon, so a fixture that lost one would fail on the runner and
    nowhere else."""
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert doc["start_url"] == "/" and doc["display"] == "standalone"
    sizes = {icon["sizes"] for icon in doc["icons"]}
    assert "512x512" in sizes
    for icon in doc["icons"]:
        assert (FIXTURE.parent / icon["src"]).is_file(), icon["src"]


# ------------------------------------------------ tools/android/check_assetlinks

def test_checker_verdicts():
    doc = android.statements_for(
        {"package_name": PACKAGE, "sha256_cert_fingerprints": [FP1]})
    ok, line = check_assetlinks.evaluate(doc, FP1)
    assert ok and PACKAGE in line
    ok, line = check_assetlinks.evaluate(doc, FP2)
    assert not ok and "not in the statement" in line
    ok, line = check_assetlinks.evaluate([], FP1)
    assert not ok and "empty" in line
    ok, line = check_assetlinks.evaluate({"nope": 1}, FP1)
    assert not ok and "not an asset-links document" in line


def test_checker_accepts_a_keytool_shaped_fingerprint():
    doc = android.statements_for(
        {"package_name": PACKAGE, "sha256_cert_fingerprints": [FP1]})
    assert check_assetlinks.evaluate(doc, f"SHA256: {FP1.lower()}")[0]


def test_checker_against_a_served_fixture():
    """The whole tool, over a real socket. Ephemeral port, daemon thread, shut
    down in the finally -- nothing here goes near a port anything else uses."""
    doc = android.statements_for(
        {"package_name": PACKAGE, "sha256_cert_fingerprints": [FP1]})
    body = json.dumps(doc).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                                   # noqa: N802
            if self.path != check_assetlinks.PATH:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):                       # keep pytest quiet
            pass

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{port}"
        assert check_assetlinks.main([origin, FP1]) == 0
        assert check_assetlinks.main([origin, FP2]) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_checker_reports_an_unreachable_site():
    with socket.socket() as probe:                  # a port with nothing on it
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert check_assetlinks.main([f"http://127.0.0.1:{port}", FP1]) == 2
