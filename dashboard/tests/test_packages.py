"""Upgrade-channel tests: publish auth + integrity, current/rollback/delete,
prune, the token-or-session download route, and the conditional `upgrade`
advertisement on the report/verify responses."""
from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import ed25519, release_trust
from ccsync_dashboard.api import build_editors_view, build_packages_view
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"

# The release key this suite signs with (item 4, 2026-08-17). Fixed seed, not
# random: a signature test that fails should fail identically twice.
TEST_SEED = bytes(range(32))
TEST_PUBKEY = base64.b64encode(ed25519.public_key(TEST_SEED)).decode("ascii")
OTHER_SEED = bytes(range(32, 64))
# published_at is part of the signed record, so it cannot be the server's
# clock -- the signer's value is what gets stored and served.
PUBLISHED_AT = "2026-08-17T12:00:00Z"


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
        admin_users=frozenset({"owen"}),
        packages_dir=str(tmp_path / "pkgs"),
        release_pubkeys=(TEST_PUBKEY,),
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


def signed_query(kind, platform, version, body, *, sha=None, min_version="0.0.0",
                 published_at=PUBLISHED_AT, signed_binary=False, seed=TEST_SEED,
                 filename=None):
    """The &signature=... suffix tools/sign_release.py produces, built here so
    the whole suite publishes the way a real ship does (item 4, 2026-08-17).
    `filename` is overridable so a test can prove that signing one name and
    uploading another is refused."""
    record = {
        "kind": kind,
        "platform": platform,
        "version": version,
        "filename": filename or package_filename(kind, platform, version, body[:4]),
        "sha256": sha or hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "min_version": min_version,
        "published_at": published_at,
        "signed_binary": signed_binary,
    }
    signature = base64.b64encode(
        ed25519.sign(seed, release_trust.canonical_record(record))
    ).decode("ascii")
    return (
        f"&signature={quote(signature, safe='')}"
        f"&pubkey_id={release_trust.pubkey_id(TEST_PUBKEY)}"
        f"&min_version={min_version}&published_at={quote(published_at, safe='')}"
        f"&signed_binary={'1' if signed_binary else '0'}"
    )


def package_filename(kind, platform, version, head=b""):
    """The server's own naming rule, mirrored (see api._package_filename)."""
    if kind == "onboard":
        if platform == "windows":
            return f"ccsync-onboard-{version}.exe"
        return f"ccsync-onboard-{version}" + (".zip" if head[:2] == b"PK" else ".sh")
    return f"ccsync-companion-{version}" + (".exe" if platform == "windows" else "")


def publish_platform(client, platform, version, body=b"exe-bytes", sha=None,
                     make_current=0, prune=0, signature_query=None, **sign_kwargs):
    sha = sha or hashlib.sha256(body).hexdigest()
    if signature_query is None:
        signature_query = signed_query("companion", platform, version, body,
                                       sha=sha, **sign_kwargs)
    return client.put(
        f"/api/v1/admin/packages/{platform}/{version}"
        f"?sha256={sha}&make_current={make_current}&prune={prune}{signature_query}",
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
    resp = publish(as_user(client, "owen"), "0.2.0", body=b"v2-bytes")
    assert resp.status_code == 200
    row = dbmod.get_package(conn, "windows", "0.2.0")
    assert row is not None
    assert row["published_by"] == "owen"
    assert row["size_bytes"] == len(b"v2-bytes")
    stored = settings.packages_path() / "windows" / "ccsync-companion-0.2.0.exe"
    assert stored.read_bytes() == b"v2-bytes"


def test_publish_validation(env):
    client, conn, _settings = env
    as_user(client, "owen")
    assert publish(client, "not-a-version").status_code == 422
    assert client.put(
        "/api/v1/admin/packages/windows/0.2.0?sha256=zzz", content=b"x"
    ).status_code == 422
    assert client.put(
        "/api/v1/admin/packages/amiga/0.2.0?sha256=" + "0" * 64, content=b"x"
    ).status_code == 422


def test_publish_sha_mismatch_leaves_nothing(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = publish(client, "0.2.0", body=b"real-bytes", sha="0" * 64)
    assert resp.status_code == 400
    assert dbmod.get_package(conn, "windows", "0.2.0") is None
    pkg_dir = settings.packages_path() / "windows"
    assert not any(pkg_dir.glob("*")) if pkg_dir.is_dir() else True


def test_publish_duplicate_version_409(env):
    client, _conn, _settings = env
    as_user(client, "owen")
    assert publish(client, "0.2.0").status_code == 200
    assert publish(client, "0.2.0").status_code == 409


def test_make_current_and_rollback(env):
    client, conn, _settings = env
    as_user(client, "owen")
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
    as_user(client, "owen")
    publish(client, "0.2.0", body=b"v2", make_current=1)
    publish(client, "0.3.0", body=b"v3")
    assert client.delete("/api/v1/admin/packages/windows/0.2.0").status_code == 409
    assert client.delete("/api/v1/admin/packages/windows/0.3.0").status_code == 200
    assert dbmod.get_package(conn, "windows", "0.3.0") is None
    assert not (settings.packages_path() / "windows" / "ccsync-companion-0.3.0.exe").exists()
    assert client.delete("/api/v1/admin/packages/windows/0.3.0").status_code == 404


def test_prune_can_be_opted_out_of(env):
    """`?prune=0` still keeps everything. It was the DEFAULT until REL-5
    (resilience sweep 2026-08-28) on the standing no-deletion rule -- and
    since neither writer ever passed prune=1, a year of shipping left 50
    companion exes and 50 onboard exes on the dataset the SQLite database
    lives on. A full /data is the dashboard going down, which is worse than
    losing a rollback artefact that can be re-published from the feed."""
    client, conn, settings = env
    as_user(client, "owen")
    publish(client, "0.1.0", body=b"v1", make_current=1)
    for i, v in enumerate(["0.2.0", "0.3.0", "0.4.0", "0.5.0"]):
        publish(client, v, body=f"v{i + 2}".encode())
    versions = {r["version"] for r in dbmod.fetch_companion_packages(conn, "windows")}
    assert versions == {"0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0"}
    assert (settings.packages_path() / "windows" / "ccsync-companion-0.2.0.exe").exists()


def test_publish_prunes_by_default(env):
    """REL-5: the query param is not sent at all, which is what ship and the
    feed's unattended publisher both do."""
    client, conn, settings = env
    as_user(client, "owen")
    publish(client, "0.1.0", body=b"v1", make_current=1)
    for i, v in enumerate(["0.2.0", "0.3.0", "0.4.0"]):
        publish(client, v, body=f"v{i + 2}".encode())
    body = b"v5"
    sha = hashlib.sha256(body).hexdigest()
    r = client.put(
        f"/api/v1/admin/packages/windows/0.5.0?sha256={sha}"
        + signed_query("companion", "windows", "0.5.0", body, sha=sha),
        content=body, headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    versions = {r["version"] for r in dbmod.fetch_companion_packages(conn, "windows")}
    assert versions == {"0.1.0", "0.4.0", "0.5.0"}


def test_a_publish_is_refused_when_the_volume_is_nearly_full(env, monkeypatch):
    """REL-5: dashboard_update.preflight has refused an APPLY at 507 since WP
    K, and the route that actually fills /data, 40 MB at a time, had no check
    at all."""
    from ccsync_dashboard import dashboard_update

    client, _conn, _settings = env
    as_user(client, "owen")
    monkeypatch.setattr(dashboard_update, "data_space",
                        lambda s: {"free_bytes": 1024, "total_bytes": 10 ** 9,
                                   "path": "/data", "error": ""})
    r = publish(client, "0.9.0", body=b"exe")
    assert r.status_code == 507
    assert "free" in r.json()["detail"]


def test_an_unmeasurable_volume_does_not_block_a_publish(env, monkeypatch):
    """"Could not measure" must not become "refuse everything": the dashboard
    is what tells everyone whether their footage is syncing, and it has to
    keep being updatable."""
    from ccsync_dashboard import dashboard_update

    client, _conn, _settings = env
    as_user(client, "owen")
    monkeypatch.setattr(dashboard_update, "data_space",
                        lambda s: {"free_bytes": -1, "total_bytes": -1,
                                   "path": "/data", "error": "no"})
    assert publish(client, "0.9.0", body=b"exe").status_code == 200


def test_prune_opt_in_keeps_current_plus_two(env):
    client, conn, settings = env
    as_user(client, "owen")
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
    publish(as_user(client, "owen"), "0.2.0", body=body, make_current=1)
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

    publish(as_user(client, "owen"), "0.2.0", body=b"v2", make_current=1)
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
    publish(as_user(client, "owen"), "0.2.0", body=b"v2", make_current=1)
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
        "username": "owen", "password": "pw",
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

    publish(as_user(client, "owen"), "0.2.0", body=b"v2", make_current=1)
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
    publish(as_user(client, "owen"), "0.2.0", body=b"winv2", make_current=1)
    clear_user(client)

    view = build_editors_view(conn)
    by_machine = {e["machine"]: e for e in view["editors"]}
    assert by_machine["EDIT-PC"]["companion_outdated"] is True     # windows, 0.1.0 != 0.2.0
    assert by_machine["MAC-1"]["companion_outdated"] is False      # macos: no macos package published

    # Now publish a MATCHING macOS current version -- the mac machine is
    # up to date; publishing a macos package must not affect the windows
    # comparison either.
    publish_platform(as_user(client, "owen"), "macos", "1.0.0", body=b"macv1", make_current=1)
    clear_user(client)
    view = build_editors_view(conn)
    by_machine = {e["machine"]: e for e in view["editors"]}
    assert by_machine["MAC-1"]["companion_outdated"] is False
    assert by_machine["EDIT-PC"]["companion_outdated"] is True

    # A newer macos release flips it.
    publish_platform(as_user(client, "owen"), "macos", "1.1.0", body=b"macv1b", make_current=1)
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
    as_user(client, "owen")
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
    as_user(client, "owen")
    resp = publish(client, "9.9.9", body=b"far too many bytes for this cap")
    assert resp.status_code == 413
    assert dbmod.get_package(conn, "windows", "9.9.9") is None
    assert list((settings.packages_path() / "windows").glob("*.part")) == []


def test_each_publish_stages_under_its_own_name(env, monkeypatch):
    """DASH-3: the staging name was `filename + '.part'` -- derived only from
    (kind, platform, version), so every attempt at the same version shared it.
    Two in-flight PUTs interleaved into one file handle while each hashed only
    its own bytes (the sha256 gate then passing for a file matching neither),
    and the `except: part.unlink()` of an ABANDONED upload -- ClientDisconnect
    is an Exception like any other -- deleted the live one's staging file."""
    from ccsync_dashboard import api as apimod

    client, _conn, _settings = env
    staged: list[str] = []
    real_run_in_threadpool = apimod.run_in_threadpool

    async def recording(func, *args, **kwargs):
        # the route writes the body as `run_in_threadpool(fh.write, chunk)`
        if getattr(func, "__name__", "") == "write":
            staged.append(getattr(func.__self__, "name", ""))
        return await real_run_in_threadpool(func, *args, **kwargs)

    monkeypatch.setattr(apimod, "run_in_threadpool", recording)
    as_user(client, "owen")

    # a first attempt that fails its integrity gate leaves nothing published,
    # so the version is still free for the retry
    assert publish(client, "0.5.0", body=b"one", sha="b" * 64).status_code == 400
    assert publish(client, "0.5.0", body=b"two").status_code == 200

    names = {Path(p).name for p in staged}
    assert len(names) == 2, names                      # never the same path twice
    for name in names:
        assert name.startswith("ccsync-companion-0.5.0.exe.") and name.endswith(".part")


def test_a_failed_publish_only_deletes_its_own_staging_file(env):
    """The other half of DASH-3: an upload that dies must not take a
    concurrent one's staging file with it."""
    client, conn, settings = env
    as_user(client, "owen")
    dest_dir = settings.packages_path() / "windows"
    dest_dir.mkdir(parents=True, exist_ok=True)
    # what the OLD code called its staging file -- i.e. exactly the path a
    # second, still-streaming publish of this version would have owned
    in_flight = dest_dir / "ccsync-companion-0.6.0.exe.part"
    in_flight.write_bytes(b"another request is streaming into this")

    assert publish(client, "0.6.0", body=b"mine", sha="c" * 64).status_code == 400

    assert in_flight.read_bytes() == b"another request is streaming into this"
    assert dbmod.get_package(conn, "windows", "0.6.0") is None
    # ...and the failed request cleaned up after itself
    assert len(list(dest_dir.glob("*.part"))) == 1


def test_publish_sweeps_abandoned_staging_files(env):
    """A unique staging name means a publish the process never got to clean up
    (SIGKILL, container restart) is no longer overwritten by the retry, so
    ~40 MB orphans would accumulate on the dataset the SQLite DB lives on."""
    import os
    import time

    from ccsync_dashboard.api import STALE_PART_SECONDS

    client, _conn, settings = env
    as_user(client, "owen")
    dest_dir = settings.packages_path() / "windows"
    dest_dir.mkdir(parents=True, exist_ok=True)
    orphan = dest_dir / "ccsync-companion-0.1.0.exe.deadbeef.part"
    orphan.write_bytes(b"x" * 32)
    old = time.time() - STALE_PART_SECONDS - 60
    os.utime(orphan, (old, old))
    fresh = dest_dir / "ccsync-companion-0.1.0.exe.cafebabe.part"
    fresh.write_bytes(b"x" * 32)

    assert publish(client, "0.7.0", body=b"a build").status_code == 200

    assert not orphan.exists()
    assert fresh.exists()        # young enough to still be somebody's upload


def test_publish_still_works_at_the_default_cap(env):
    client, conn, _settings = env
    as_user(client, "owen")
    assert publish(client, "0.3.0", body=b"a normal little exe").status_code == 200
    assert dbmod.get_package(conn, "windows", "0.3.0") is not None


# -- per-machine version on the fleet view (release hygiene) ---------------


def test_fleet_view_flags_a_stale_per_machine_version(env):
    """machine_state carries the per-machine build (schema v10) and outlives
    a lane_report_current prune, so a stale machine cannot go invisible
    exactly when you most want to see it."""
    client, conn, _settings = env
    client.post("/api/v1/report", json=report_payload("0.1.0"), headers=report_headers())
    publish(as_user(client, "owen"), "0.2.0", body=b"v2", make_current=1)
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
    as_user(client, "owen")
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
    publish(as_user(client, "owen"), "0.2.0", body=b"v2", make_current=1)
    clear_user(client)

    (entry,) = build_editors_view(conn)["editors"]
    assert entry["companion_version"] is None
    assert entry["companion_version_unknown"] is True
    assert entry["companion_outdated"] is False        # unknown != "differs"

    as_user(client, "owen")
    assert "[ VERSION UNKNOWN ]" in client.get("/partials/fleet").text


# -- kind=onboard: the [ INSTALLER ] download --------------------------


def publish_onboard(client, version, body=b"onboard-bytes", sha=None,
                    make_current=0, platform="windows", **sign_kwargs):
    sha = sha or hashlib.sha256(body).hexdigest()
    suffix = signed_query("onboard", platform, version, body, sha=sha, **sign_kwargs)
    return client.put(
        f"/api/v1/admin/packages/{platform}/{version}"
        f"?kind=onboard&sha256={sha}&make_current={make_current}{suffix}",
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
                   123, '2026-07-25T00:00:00+00:00', 'owen', 1)""",
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
    as_user(client, "owen")
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

    # macOS onboard packages are named by CONTENT: the zipped wizard gets
    # .zip, anything else (the Terminal bootstrap script, and every
    # pre-1.0.17 row) gets .sh -- a zip served as .sh, or a script served
    # as .zip, breaks a Mac editor's very first contact with the system.
    assert publish_onboard(client, "1.0.0", platform="macos",
                           body=b"#!/usr/bin/env bash\necho hi\n").status_code == 200
    assert dbmod.get_package(conn, "macos", "1.0.0", kind="onboard")["filename"] == "ccsync-onboard-1.0.0.sh"
    assert publish_onboard(client, "1.0.1", platform="macos",
                           body=b"PK\x03\x04zipzipzip").status_code == 200
    assert dbmod.get_package(conn, "macos", "1.0.1", kind="onboard")["filename"] == "ccsync-onboard-1.0.1.zip"


def test_upgrade_never_offers_the_onboard_package(env):
    """upgrade.py renames whatever it downloads over the running companion
    exe -- offering onboard.exe there would brick the machine."""
    client, _conn, _settings = env
    publish_onboard(as_user(client, "owen"), "1.0.0", make_current=1)
    clear_user(client)
    resp = client.post("/api/v1/report", json=report_payload("0.1.0"),
                       headers=report_headers())
    assert "upgrade" not in resp.json()


def test_installer_download_route(env):
    client, _conn, _settings = env
    body = b"the-installer"
    publish_onboard(as_user(client, "owen"), "1.0.4", body=body, make_current=1)
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
    # plain 404 that says so, not a broken download.
    resp = client.get("/download", follow_redirects=False, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    assert resp.headers["location"] == "/download/macos"
    resp = client.get("/download/macos")
    assert resp.status_code == 404
    # ...and the 404 is written for whoever clicked it, naming THIS platform
    # and an admin step that does not need a repo checkout on a base rig
    # (release-pipeline-11 / CR-59, 2026-08-21).
    assert "No macos installer has been published" in resp.text
    assert "publish_latest.py --kind onboard --platform macos" in resp.text
    assert "build_editor_package.ps1" not in resp.text
    assert client.get("/download/amiga").status_code == 404


def test_installer_download_serves_the_mac_wizard_zip(env):
    """A Mac's [ INSTALLER ] click downloads the zipped onboarding wizard
    (since installer 1.0.17) under its .zip name -- what lands in the
    editor's Downloads folder must unzip to CCSync Onboarding.app, not open
    as a mystery .sh."""
    client, _conn, _settings = env
    wizard_zip = b"PK\x03\x04" + b"wizard-bytes"
    publish_onboard(as_user(client, "owen"), "1.0.17", body=wizard_zip,
                    make_current=1, platform="macos")
    clear_user(client)

    as_user(client, "editor1")
    resp = client.get("/download/macos")
    assert resp.status_code == 200
    assert resp.content == wizard_zip
    assert "ccsync-onboard-1.0.17.zip" in resp.headers["content-disposition"]
    assert resp.headers["X-CCSync-Version"] == "1.0.17"


# -- version="current": discovery for a fresh bootstrap ----------------


def test_download_current_serves_the_current_package(env):
    """A fresh machine has no version to ask for, so it asks for "current"
    and verifies the bytes against the headers."""
    client, _conn, _settings = env
    publish(as_user(client, "owen"), "0.2.0", body=b"v2-bytes", make_current=1)
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
    as_user(client, "owen").post("/api/v1/admin/packages/windows/0.2.0/current")
    clear_user(client)
    resp = client.get("/api/v1/companion/package/windows/current",
                      headers={"X-CCSync-Token": "sekrit"})
    assert resp.content == b"v2-bytes"
    assert resp.headers["X-CCSync-Version"] == "0.2.0"


def test_download_current_404_when_nothing_is_current(env):
    client, _conn, _settings = env
    # Published but never made current -- discovery must not guess.
    publish(as_user(client, "owen"), "0.2.0", body=b"v2-bytes", make_current=0)
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
    as_user(client, "owen")
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
    publish_onboard(as_user(client, "owen"), "1.0.4", make_current=1, platform="macos")
    clear_user(client)

    url = "/api/v1/companion/package/macos/current?kind=onboard"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"X-CCSync-Token": "wrong"}).status_code == 401
    assert client.get(url, headers={"X-CCSync-Token": "sekrit"}).status_code == 200
    assert as_user(client, "jsmith").get(url).status_code == 200


# ======================================================================
# COMMERCIAL_READINESS.md item 4 (2026-08-17): the signed upgrade channel.
# The dashboard stores and serves a signature it cannot produce.
# ======================================================================


def test_an_unsigned_publish_is_refused_loudly(env):
    """Publish tooling that predates signing must FAIL, not warn: the whole
    point is that nothing unverifiable can reach the channel."""
    client, conn, _settings = env
    as_user(client, "owen")
    body = b"exe-bytes"
    r = client.put(
        f"/api/v1/admin/packages/windows/9.9.9?sha256={hashlib.sha256(body).hexdigest()}",
        content=body, headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 422
    assert "unsigned publish REFUSED" in r.json()["detail"]
    assert dbmod.get_package(conn, "windows", "9.9.9") is None


def test_a_signature_from_an_untrusted_key_is_refused(env):
    client, conn, settings = env
    as_user(client, "owen")
    r = publish_platform(client, "windows", "9.9.9", seed=OTHER_SEED)
    assert r.status_code == 400
    assert "signature REJECTED" in r.json()["detail"]
    assert dbmod.get_package(conn, "windows", "9.9.9") is None
    # And nothing was left behind in the packages dir.
    assert not list((Path(settings.packages_dir) / "windows").glob("*"))


def test_a_signature_for_different_bytes_is_refused(env):
    """The signed sha256 has to be the sha256 of what actually arrived."""
    client, conn, _settings = env
    as_user(client, "owen")
    body = b"the-real-build"
    suffix = signed_query("companion", "windows", "9.9.9", b"a-different-build")
    r = client.put(
        f"/api/v1/admin/packages/windows/9.9.9"
        f"?sha256={hashlib.sha256(body).hexdigest()}{suffix}",
        content=body, headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 400
    assert dbmod.get_package(conn, "windows", "9.9.9") is None


def test_signed_filename_must_match_the_server_choice(env):
    """A record signed for one filename cannot be published under another --
    this is what stops a companion build being re-labelled as the onboard
    installer (or a Windows exe as the macOS one) after signing."""
    client, conn, _settings = env
    as_user(client, "owen")
    r = publish_platform(client, "windows", "9.9.9",
                         filename="ccsync-onboard-9.9.9.exe")
    assert r.status_code == 400
    assert "filename=ccsync-companion-9.9.9.exe" in r.json()["detail"]
    assert dbmod.get_package(conn, "windows", "9.9.9") is None


def test_a_record_signed_for_another_kind_is_refused(env):
    client, _conn, _settings = env
    as_user(client, "owen")
    body = b"onboard-bytes"
    suffix = signed_query("companion", "windows", "9.9.9", body)   # wrong kind
    r = client.put(
        f"/api/v1/admin/packages/windows/9.9.9?kind=onboard"
        f"&sha256={hashlib.sha256(body).hexdigest()}{suffix}",
        content=body, headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 400


def test_a_dashboard_with_no_configured_key_publishes_nothing(tmp_path):
    """Fail closed at the deployment level too: an operator who never set
    DASH_RELEASE_PUBKEYS gets a 503 that says so, not an unsigned channel."""
    settings = Settings(
        db_path=str(tmp_path / "nokey.db"),
        report_token="sekrit",
        session_secret=SECRET,
        admin_users=frozenset({"owen"}),
        packages_dir=str(tmp_path / "pkgs"),
    )
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "pw"
    with TestClient(app) as client:
        as_user(client, "owen")
        r = publish_platform(client, "windows", "9.9.9")
        assert r.status_code == 503
        assert "DASH_RELEASE_PUBKEYS" in r.json()["detail"]


def test_min_version_must_be_rankable(env):
    """A record carrying min_version="nightly" would be rejected by every
    companion (upgrade.parse_version refuses what it cannot rank) while
    looking fine on the server."""
    client, _conn, _settings = env
    as_user(client, "owen")
    r = publish_platform(client, "windows", "9.9.9", min_version="nightly")
    assert r.status_code == 422
    assert "dotted-numeric" in r.json()["detail"]


def test_a_min_version_above_the_version_is_refused(env):
    """dash-release-ai-3, 2026-08-21: `--min-version 0.9.54` on a 0.9.44 build
    is a validly signed record that raises every companion's PERMANENT
    downgrade floor above the build it offers, and then refuses that build,
    the corrected republish and the rollback. One typo, fleet-wide."""
    client, conn, _settings = env
    as_user(client, "owen")
    r = publish_platform(client, "windows", "0.9.44", min_version="0.9.54")
    assert r.status_code == 400
    assert "higher than the version being published" in r.json()["detail"]
    assert dbmod.get_package(conn, "windows", "0.9.44") is None

    # ...and the same build with a sane floor publishes normally.
    assert publish_platform(client, "windows", "0.9.44",
                            min_version="0.9.34").status_code == 200


def test_a_signed_publish_stores_and_serves_every_field(env):
    client, conn, _settings = env
    as_user(client, "owen")
    body = b"exe-bytes"
    assert publish_platform(client, "windows", "9.9.9", body=body, make_current=1,
                            min_version="0.7.12", signed_binary=True).status_code == 200

    row = dbmod.get_package(conn, "windows", "9.9.9")
    assert row["min_version"] == "0.7.12"
    assert row["signed_binary"] == 1
    assert row["pubkey_id"] == release_trust.pubkey_id(TEST_PUBKEY)
    # The SIGNER's timestamp, not the server's clock -- it is a signed field.
    assert row["published_at"] == PUBLISHED_AT

    view = client.get("/api/v1/admin/packages").json()
    entry = next(p for p in view["packages"] if p["version"] == "9.9.9")
    assert entry["signed"] is True
    assert entry["signed_binary"] is True
    assert entry["min_version"] == "0.7.12"
    assert entry["pubkey_id"] == release_trust.pubkey_id(TEST_PUBKEY)

    # And the record the dashboard serves back verifies against the same key.
    ok, _detail = release_trust.verify_record(
        {
            "kind": "companion", "platform": "windows", "version": "9.9.9",
            "filename": row["filename"], "sha256": row["sha256"],
            "size_bytes": row["size_bytes"], "min_version": row["min_version"],
            "published_at": row["published_at"], "signed_binary": True,
        },
        row["signature"], [TEST_PUBKEY],
    )
    assert ok


def test_the_upgrade_advertisement_carries_the_signed_record(env):
    """MIGRATION: every field 0.7.11 already reads stays exactly where it
    was; the signature fields are ADDED beside them."""
    client, _conn, _settings = env
    as_user(client, "owen")
    body = b"exe-bytes"
    publish_platform(client, "windows", "9.9.9", body=body, make_current=1,
                     min_version="0.7.12")
    clear_user(client)

    resp = client.post("/api/v1/report", json=report_payload("0.1.0"),
                       headers=report_headers()).json()
    up = resp["upgrade"]
    # the pre-signing shape, untouched
    assert up["version"] == "9.9.9"
    assert up["url"] == "/api/v1/companion/package/windows/9.9.9"
    assert up["sha256"] == hashlib.sha256(body).hexdigest()
    assert up["size_bytes"] == len(body)
    # the added record
    assert up["min_version"] == "0.7.12"
    assert up["kind"] == "companion" and up["platform"] == "windows"
    assert up["filename"] == "ccsync-companion-9.9.9.exe"
    assert up["published_at"] == PUBLISHED_AT
    ok, _detail = release_trust.verify_record(up, up["signature"], [TEST_PUBKEY])
    assert ok


def test_the_download_route_advertises_the_signature_to_the_mac_bootstrap(env):
    """installer/macos_bootstrap.sh cannot verify ed25519, but it can refuse
    a channel that carries no signature at all."""
    client, _conn, _settings = env
    as_user(client, "owen")
    publish_platform(client, "macos", "9.9.9", body=b"macos-bytes", make_current=1,
                     min_version="0.7.12")
    r = client.get("/api/v1/companion/package/macos/current")
    assert r.status_code == 200
    assert r.headers["x-ccsync-signature"]
    assert r.headers["x-ccsync-min-version"] == "0.7.12"
    assert r.headers["x-ccsync-pubkey-id"] == release_trust.pubkey_id(TEST_PUBKEY)


def test_migration_v14_keeps_pre_signing_rows_and_marks_them_unsigned(tmp_path):
    """A live database published before signing existed keeps its rows -- the
    [ INSTALLER ] download must not 404 the morning after the upgrade -- and
    they show up plainly as unsigned rather than silently trusted."""
    connection = dbmod.connect(tmp_path / "mig14.db")
    dbmod.migrate(connection, [s for s in dbmod._MIGRATION_STEPS if s[0] <= 13])
    connection.execute(
        """INSERT INTO companion_packages
             (kind, version, platform, filename, sha256, size_bytes,
              published_at, published_by, is_current)
           VALUES ('companion','0.7.11','windows','ccsync-companion-0.7.11.exe',
                   'aa','10','2026-08-01T00:00:00Z','owen',1)"""
    )
    connection.commit()
    dbmod.migrate(connection)

    row = dbmod.get_current_package(connection, "windows")
    assert row["version"] == "0.7.11"
    assert row["signature"] is None
    settings = Settings(db_path=str(tmp_path / "mig14.db"),
                        packages_dir=str(tmp_path / "pkgs"))
    entry = next(p for p in build_packages_view(connection, settings)["packages"]
                 if p["version"] == "0.7.11")
    assert entry["signed"] is False and entry["signed_binary"] is False
    connection.close()


def test_the_companion_carries_an_identical_ed25519_copy():
    """Drift between the two copies means a build the dashboard accepts and
    the fleet refuses -- discovered at ship time, on the fleet."""
    here = Path(release_trust.__file__).resolve().parent
    theirs = here.parents[2] / "companion" / "src" / "ccsync_companion" / "ed25519.py"
    if not theirs.is_file():
        pytest.skip("no companion checkout beside this one")
    assert theirs.read_bytes() == (here / "ed25519.py").read_bytes()


def test_the_two_canonical_record_formats_agree():
    """The bytes the dashboard verifies must be the bytes the companion
    verifies -- they are separate implementations of one format."""
    sys.path.insert(0, str(
        Path(release_trust.__file__).resolve().parents[3]
        / "companion" / "src"))
    try:
        from ccsync_companion import release_pubkey as companion_side
    except ImportError:
        pytest.skip("no companion checkout beside this one")
    record = {
        "kind": "companion", "platform": "macos", "version": "1.2.3",
        "filename": "ccsync-companion-1.2.3", "sha256": "ab" * 32,
        "size_bytes": 123, "min_version": "1.0.0",
        "published_at": PUBLISHED_AT, "signed_binary": True,
    }
    assert (companion_side.canonical_record(record)
            == release_trust.canonical_record(record))
    assert companion_side.RECORD_FIELDS == release_trust.RECORD_FIELDS


def test_a_placeholder_release_pubkey_counts_as_none_configured():
    """The shipped compose sets DASH_RELEASE_PUBKEYS="REPLACE_ME". Left in
    place it must produce "no release key configured" (a 503 naming the
    variable), not "signature rejected" on every publish -- which would read
    like a broken signing key rather than an unfinished deployment."""
    assert Settings.from_env({"DASH_RELEASE_PUBKEYS": "REPLACE_ME"}).release_pubkeys == ()
    assert Settings.from_env(
        {"DASH_RELEASE_PUBKEYS": f"{TEST_PUBKEY}, REPLACE_ME"}
    ).release_pubkeys == (TEST_PUBKEY,)
