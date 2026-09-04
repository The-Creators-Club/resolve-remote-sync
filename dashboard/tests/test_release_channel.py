"""The release channel's rollout controls (resilience sweep 2026-08-28).

REL-1/SYS-6 (publish staged, the soak gate, push to one machine, roll back),
REL-3 (the vendor recall), REL-4/SYS-13 (`requires_dashboard` ordering),
REL-16 (`arch`) and REL-13 (the git provenance columns).

The signature compatibility tests at the top are the ones to read first: the
two new signed fields are OPTIONAL kind-scoped extras, and the whole reason
they are shaped that way is that a record published before this wave -- and
every companion in the field -- must keep verifying byte for byte.
"""
from __future__ import annotations

import base64
import hashlib
import json
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import VERSION, auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import ed25519, package_store, release_feed, release_trust
from ccsync_dashboard.api import _arch_matches, _upgrade_info, build_packages_view
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
TEST_SEED = bytes(range(32))
TEST_PUBKEY = base64.b64encode(ed25519.public_key(TEST_SEED)).decode("ascii")
PUBLISHED_AT = "2026-08-28T12:00:00Z"


def as_user(client, user="owen"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "channel.db"
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
        as_user(client)
        yield client, conn, settings
        conn.close()


def package_filename(kind, platform, version):
    if kind == "onboard":
        return f"ccsync-onboard-{version}" + (".exe" if platform == "windows" else ".sh")
    return f"ccsync-companion-{version}" + (".exe" if platform == "windows" else "")


def publish(client, version, *, platform="windows", kind="companion",
            body=None, make_current=0, requires_dashboard="", arch="",
            git_sha="", git_dirty=0, min_version="0.0.0"):
    body = body if body is not None else f"exe-{version}-{platform}".encode()
    sha = hashlib.sha256(body).hexdigest()
    record = {
        "kind": kind, "platform": platform, "version": version,
        "filename": package_filename(kind, platform, version),
        "sha256": sha, "size_bytes": len(body), "min_version": min_version,
        "published_at": PUBLISHED_AT, "signed_binary": False,
    }
    if requires_dashboard:
        record["requires_dashboard"] = requires_dashboard
    if arch:
        record["arch"] = arch
    signature = base64.b64encode(
        ed25519.sign(TEST_SEED, release_trust.canonical_record(record))
    ).decode("ascii")
    url = (
        f"/api/v1/admin/packages/{platform}/{version}"
        f"?kind={kind}&sha256={sha}&make_current={make_current}"
        f"&signature={quote(signature, safe='')}"
        f"&pubkey_id={release_trust.pubkey_id(TEST_PUBKEY)}"
        f"&min_version={min_version}&published_at={quote(PUBLISHED_AT, safe='')}"
        f"&signed_binary=0"
    )
    if requires_dashboard:
        url += f"&requires_dashboard={requires_dashboard}"
    if arch:
        url += f"&arch={arch}"
    if git_sha:
        url += f"&git_sha={git_sha}"
    if git_dirty:
        url += "&git_dirty=1"
    return client.put(url, content=body,
                      headers={"Content-Type": "application/octet-stream"})


def report(client, *, editor="jsmith", machine="EDIT-PC", version="0.1.0",
           platform="windows", crashes=None, extra=None):
    payload = {
        "editor_name": editor,
        "machine": machine,
        "companion_version": version,
        "platform": platform,
        "reported_at": "2026-08-28T10:00:00+00:00",
        "lanes": [{"name": "lane_a_video_up", "state": "idle"}],
    }
    if crashes is not None:
        payload["sync_guard"] = {"crashes": {"count": crashes, "newest": None}}
    payload.update(extra or {})
    return client.post(
        "/api/v1/report", json=payload,
        headers={"X-CCSync-Token": "sekrit",
                 "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)},
    )


def backdate_soak(conn, minutes, editor="jsmith", machine="EDIT-PC"):
    """Pretend this machine has been on its reported version for `minutes`."""
    when = dbmod._iso_minus(dbmod.utcnow_iso(), int(minutes * 60))
    conn.execute(
        "UPDATE machine_state SET companion_version_since=? "
        "WHERE editor_username=? AND machine=?", (when, editor, machine))
    conn.commit()


# ------------------------------------------------- signature compatibility


def test_a_pre_wave_record_canonicalises_exactly_as_it_did():
    """The nine-field shape every record published before 2026-08-28 has, and
    every companion in the field verifies. One character of drift here is
    "the whole fleet refuses every build"."""
    record = {
        "kind": "companion", "platform": "windows", "version": "0.9.54",
        "filename": "ccsync-companion-0.9.54.exe", "sha256": "a" * 64,
        "size_bytes": 123, "min_version": "0.0.0",
        "published_at": PUBLISHED_AT, "signed_binary": False,
    }
    expected = release_trust.RECORD_PREFIX + json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    assert release_trust.canonical_record(record) == expected
    sig = base64.b64encode(ed25519.sign(TEST_SEED, expected)).decode("ascii")
    assert release_trust.verify_record(record, sig, (TEST_PUBKEY,))[0]


def test_a_record_carrying_the_new_fields_verifies_and_is_tamper_evident():
    record = {
        "kind": "companion", "platform": "macos", "version": "0.9.55",
        "filename": "ccsync-companion-0.9.55", "sha256": "b" * 64,
        "size_bytes": 9, "min_version": "0.0.0", "published_at": PUBLISHED_AT,
        "signed_binary": False, "requires_dashboard": "0.7.17", "arch": "arm64",
    }
    sig = base64.b64encode(
        ed25519.sign(TEST_SEED, release_trust.canonical_record(record))).decode("ascii")
    assert release_trust.verify_record(record, sig, (TEST_PUBKEY,))[0]
    # Editing either new field breaks the signature: they are INSIDE it, which
    # is the point of signing them at all.
    for field, value in (("requires_dashboard", "0.0.1"), ("arch", "x86_64")):
        tampered = dict(record, **{field: value})
        assert not release_trust.verify_record(tampered, sig, (TEST_PUBKEY,))[0]
    # ...and so does dropping one, so a feed host cannot strip the ordering
    # requirement off a build.
    stripped = {k: v for k, v in record.items() if k != "requires_dashboard"}
    assert not release_trust.verify_record(stripped, sig, (TEST_PUBKEY,))[0]


def test_a_blank_optional_field_canonicalises_as_absent():
    """A stray empty query param must not change the bytes: the signer omits
    an empty field, so `arch=""` has to read as "no arch"."""
    base = {
        "kind": "companion", "platform": "windows", "version": "0.9.54",
        "filename": "ccsync-companion-0.9.54.exe", "sha256": "c" * 64,
        "size_bytes": 5, "min_version": "0.0.0", "published_at": PUBLISHED_AT,
        "signed_binary": False,
    }
    assert (release_trust.canonical_record(dict(base, arch="", requires_dashboard=""))
            == release_trust.canonical_record(base))


def test_the_companion_and_the_dashboard_canonicalise_identically():
    """Two copies of one format (release_pubkey.py / release_trust.py), which
    is only safe while they agree byte for byte."""
    import sys
    from pathlib import Path

    companion_src = Path(__file__).resolve().parents[2] / "companion" / "src"
    sys.path.insert(0, str(companion_src))
    try:
        from ccsync_companion import release_pubkey
    finally:
        sys.path.remove(str(companion_src))
    record = {
        "kind": "companion", "platform": "macos", "version": "0.9.55",
        "filename": "ccsync-companion-0.9.55", "sha256": "d" * 64,
        "size_bytes": 7, "min_version": "0.0.0", "published_at": PUBLISHED_AT,
        "signed_binary": True, "arch": "universal2", "requires_dashboard": "0.7.17",
    }
    assert release_pubkey.canonical_record(record) == release_trust.canonical_record(record)
    plain = {k: v for k, v in record.items()
             if k not in ("arch", "requires_dashboard")}
    assert release_pubkey.canonical_record(plain) == release_trust.canonical_record(plain)


# ------------------------------------------------------------- staged publish


def test_publish_defaults_to_staged(env):
    client, conn, settings = env
    assert publish(client, "0.2.0").status_code == 200
    row = dbmod.get_package(conn, "windows", "0.2.0")
    assert row["is_current"] == 0
    assert row["rollout"] == "staged"
    assert row["staged_at"]
    view = build_packages_view(conn, settings)
    entry = [p for p in view["packages"] if p["version"] == "0.2.0"][0]
    assert entry["rollout"] == "staged"
    assert entry["soak"]["machines"] == 0


def test_git_provenance_is_stored_and_shown(env):
    client, conn, settings = env
    assert publish(client, "0.2.0", git_sha="abc1234", git_dirty=1).status_code == 200
    entry = [p for p in build_packages_view(conn, settings)["packages"]
             if p["version"] == "0.2.0"][0]
    assert entry["git_sha"] == "abc1234"
    assert entry["git_dirty"] is True


# ------------------------------------------------------------- the soak gate


def test_make_current_is_refused_until_a_machine_has_run_the_build(env):
    client, conn, _settings = env
    publish(client, "0.2.0")
    r = client.post("/api/v1/admin/packages/windows/0.2.0/current")
    assert r.status_code == 409
    assert "no computer has reported 0.2.0" in r.json()["detail"]
    assert dbmod.get_current_package(conn, "windows") is None

    report(client, version="0.2.0", crashes=0)
    # Reported, but only just: the soak is 30 minutes by default.
    r = client.post("/api/v1/admin/packages/windows/0.2.0/current")
    assert r.status_code == 409
    assert "soak is 30 min" in r.json()["detail"]

    backdate_soak(conn, 45)
    assert client.post("/api/v1/admin/packages/windows/0.2.0/current").status_code == 200
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.2.0"


def test_a_crashing_canary_never_satisfies_the_soak(env):
    client, conn, _settings = env
    publish(client, "0.2.0")
    report(client, version="0.2.0", crashes=3)
    backdate_soak(conn, 120)
    r = client.post("/api/v1/admin/packages/windows/0.2.0/current")
    assert r.status_code == 409
    assert "3 crash" in r.json()["detail"]


def test_the_override_needs_the_version_typed(env):
    client, conn, _settings = env
    publish(client, "0.2.0")
    r = client.post("/api/v1/admin/packages/windows/0.2.0/current?force=1")
    assert r.status_code == 409
    assert "type the version number" in r.json()["detail"]
    assert dbmod.get_current_package(conn, "windows") is None

    r = client.post("/api/v1/admin/packages/windows/0.2.0/current?force=1&confirm=0.2.0")
    assert r.status_code == 200
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.2.0"
    forced = [a for a in dbmod.fetch_audit(conn) if a["action"] == "package.make_current"]
    assert forced[0]["detail"]["forced"] is True


def test_rolling_back_to_a_build_the_fleet_already_ran_is_not_gated(env):
    """The soak asks for evidence a NEW build works. A build that was current
    before has produced it; gating the way back is the gate working against
    the recovery it exists for."""
    client, conn, _settings = env
    publish(client, "0.2.0")
    publish(client, "0.3.0")
    client.post("/api/v1/admin/packages/windows/0.2.0/current?force=1&confirm=0.2.0")
    client.post("/api/v1/admin/packages/windows/0.3.0/current?force=1&confirm=0.3.0")
    assert client.post("/api/v1/admin/packages/windows/0.2.0/current").status_code == 200
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.2.0"


def test_a_machine_that_never_reported_its_crash_counter_does_not_soak(env):
    """"Could not tell" must never render as "fine": a companion too old to
    send `sync_guard.crashes` has said nothing about whether the build stays
    up, which is not the same answer as zero crashes."""
    client, conn, _settings = env
    publish(client, "0.2.0")
    report(client, version="0.2.0")          # no sync_guard section at all
    backdate_soak(conn, 120)
    r = client.post("/api/v1/admin/packages/windows/0.2.0/current")
    assert r.status_code == 409
    assert "crash counter" in r.json()["detail"]


def test_a_zero_soak_turns_the_gate_off(env):
    client, conn, _settings = env
    dbmod.meta_set(conn, "release_soak_minutes", "0")
    conn.commit()
    publish(client, "0.2.0")
    report(client, version="0.2.0", crashes=0)
    assert client.post("/api/v1/admin/packages/windows/0.2.0/current").status_code == 200


def test_push_to_one_machine_writes_the_per_machine_request(env):
    client, conn, _settings = env
    publish(client, "0.2.0")
    report(client, version="0.1.0")
    r = client.post("/partials/admin/packages/push-one",
                    data={"platform": "windows", "version": "0.2.0",
                          "target": "jsmith/EDIT-PC"})
    assert r.status_code == 200
    req = dbmod.machine_update_request(conn, "jsmith", "EDIT-PC")
    assert req["version"] == "0.2.0"
    assert any(a["action"] == "package.push_one" for a in dbmod.fetch_audit(conn))


def test_push_to_one_machine_refuses_an_unpublished_version(env):
    client, conn, _settings = env
    report(client, version="0.1.0")
    r = client.post("/partials/admin/packages/push-one",
                    data={"platform": "windows", "version": "9.9.9",
                          "target": "jsmith/EDIT-PC"})
    assert r.status_code == 200          # the partial re-renders with the error
    assert "no published windows companion package 9.9.9" in r.text
    assert dbmod.machine_update_request(conn, "jsmith", "EDIT-PC") is None


# ------------------------------------------------- ordering (REL-4 / SYS-13)


def test_a_build_needing_a_newer_dashboard_cannot_be_made_current(env):
    client, conn, _settings = env
    assert publish(client, "0.2.0", requires_dashboard="99.0.0").status_code == 200
    r = client.post("/api/v1/admin/packages/windows/0.2.0/current"
                    "?force=1&confirm=0.2.0")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "99.0.0" in detail and VERSION in detail
    assert dbmod.get_current_package(conn, "windows") is None


def test_publishing_straight_to_current_is_staged_on_the_same_rule(env):
    """REL-1 (usability sweep 2026-09-04): the ORDERING violation used to
    refuse the whole publish with a 409 and unlink the .part. It stages now
    and says why -- which is what the 08-28 comment always said should
    happen, and what stopped the feed re-downloading 40 MB on every check
    only to throw it away again. The bytes are fine; only the flip is in
    question."""
    client, conn, _settings = env
    r = publish(client, "0.2.0", requires_dashboard="99.0.0", make_current=1)
    assert r.status_code == 200
    note = r.json()["note"]
    assert package_store.STAGED_SENTENCE in note
    assert "Update the dashboard first" in note
    # Published, and NOT what anybody is offered.
    assert dbmod.get_package(conn, "windows", "0.2.0") is not None
    assert dbmod.get_current_package(conn, "windows") is None


def test_a_build_needing_this_dashboard_or_older_is_fine(env):
    client, conn, _settings = env
    assert publish(client, "0.2.0", requires_dashboard=VERSION,
                   make_current=1).status_code == 200
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.2.0"


def test_an_unreadable_requirement_blocks_rather_than_passes():
    assert package_store.blocks_on_dashboard_version("companion", "nightly") is True
    assert package_store.blocks_on_dashboard_version("companion", "") is False
    assert package_store.blocks_on_dashboard_version("onboard", "99.0.0") is False


def test_a_build_needing_a_newer_dashboard_is_never_advertised(env):
    """A row that became current before the dashboard was rolled BACK is the
    case the offer-side check exists for."""
    client, conn, _settings = env
    publish(client, "0.2.0", requires_dashboard="99.0.0")
    assert dbmod.set_current_package(conn, "windows", "0.2.0") is True
    conn.commit()
    assert _upgrade_info(conn, "windows", "0.1.0") is None
    r = report(client, version="0.1.0")
    assert "upgrade" not in r.json()


# ------------------------------------------------------------ arch (REL-16)


def test_arch_matching_rules():
    assert _arch_matches("", "x86_64")           # pre-wave record: offer it
    assert _arch_matches("arm64", "")            # old companion: offer it
    assert _arch_matches("universal2", "x86_64")
    assert _arch_matches("arm64", "arm64")
    assert not _arch_matches("arm64", "x86_64")


def test_an_intel_mac_is_offered_nothing_rather_than_an_arm64_binary(env):
    client, conn, _settings = env
    publish(client, "0.2.0", platform="macos", arch="arm64")
    assert dbmod.set_current_package(conn, "macos", "0.2.0") is True
    conn.commit()
    assert _upgrade_info(conn, "macos", "0.1.0", "x86_64") is None
    assert _upgrade_info(conn, "macos", "0.1.0", "arm64")["version"] == "0.2.0"
    # A companion too old to report its arch keeps the pre-2026-08-28
    # behaviour: it is offered the build.
    assert _upgrade_info(conn, "macos", "0.1.0")["version"] == "0.2.0"
    r = report(client, version="0.1.0", platform="macos",
               machine="MACBOOK", extra={"arch": "x86_64"})
    assert "upgrade" not in r.json()


def test_the_offer_carries_the_signed_extras_verbatim(env):
    client, conn, _settings = env
    publish(client, "0.2.0", platform="macos", arch="universal2",
            requires_dashboard=VERSION)
    dbmod.set_current_package(conn, "macos", "0.2.0")
    conn.commit()
    offer = _upgrade_info(conn, "macos", "0.1.0", "arm64")
    assert offer["arch"] == "universal2"
    assert offer["requires_dashboard"] == VERSION
    # ...and the record the companion rebuilds from the offer still verifies.
    record = {k: offer[k] for k in release_trust.record_fields("companion", offer)}
    assert release_trust.verify_record(record, offer["signature"], (TEST_PUBKEY,))[0]


def test_an_offer_for_a_plain_record_gains_no_new_keys(env):
    client, conn, _settings = env
    publish(client, "0.2.0", make_current=1)
    offer = _upgrade_info(conn, "windows", "0.1.0")
    assert "arch" not in offer and "requires_dashboard" not in offer


# ---------------------------------------------------------- recall (REL-3)


def test_a_retracted_build_is_uncurrented_never_offered_and_chipped(env):
    client, conn, settings = env
    publish(client, "0.2.0", make_current=1)
    report(client, version="0.2.0")
    assert dbmod.retract_package(conn, "companion", "windows", "0.2.0",
                                 "it corrupts proxies", dbmod.utcnow_iso())
    conn.commit()
    assert dbmod.get_current_package(conn, "windows") is None
    assert _upgrade_info(conn, "windows", "0.1.0") is None
    # Re-currenting it is refused from the route AND from the db helper.
    r = client.post("/api/v1/admin/packages/windows/0.2.0/current?force=1&confirm=0.2.0")
    assert r.status_code == 409
    assert "RECALLED" in r.json()["detail"]
    assert dbmod.set_current_package(conn, "windows", "0.2.0") is False
    view = build_packages_view(conn, settings)
    assert view["retracted"][0]["retracted_reason"] == "it corrupts proxies"
    assert view["retracted"][0]["machines_running"] == 1
    # ...and the fleet grid says so on the machine that is running it.
    page = client.get("/partials/fleet")
    assert page.status_code == 200
    assert "RECALLED BUILD" in page.text


def test_retracting_twice_keeps_the_first_stamp(env):
    client, conn, _settings = env
    publish(client, "0.2.0", make_current=1)
    now = "2026-08-28T09:00:00+00:00"
    assert dbmod.retract_package(conn, "companion", "windows", "0.2.0", "bad", now)
    assert dbmod.retract_package(conn, "companion", "windows", "0.2.0", "bad",
                                 dbmod.utcnow_iso()) is False
    conn.commit()
    assert dbmod.get_package(conn, "windows", "0.2.0")["retracted_at"] == now


def test_roll_the_fleet_back_asks_every_machine_on_the_recalled_build(env):
    client, conn, _settings = env
    publish(client, "0.1.0")
    publish(client, "0.2.0", make_current=1)
    report(client, editor="jsmith", machine="EDIT-PC", version="0.2.0")
    report(client, editor="jsmith", machine="LAPTOP", version="0.2.0")
    report(client, editor="jsmith", machine="OLD-PC", version="0.1.0")
    dbmod.retract_package(conn, "companion", "windows", "0.2.0", "bad",
                          dbmod.utcnow_iso())
    conn.commit()
    r = client.post("/api/v1/admin/packages/windows/0.2.0/roll-fleet-back?to=0.1.0")
    assert r.status_code == 200
    assert sorted(r.json()["machines"]) == ["jsmith/EDIT-PC", "jsmith/LAPTOP"]
    assert dbmod.machine_update_request(conn, "jsmith", "EDIT-PC")["version"] == "0.1.0"
    assert dbmod.machine_update_request(conn, "jsmith", "LAPTOP")["version"] == "0.1.0"
    # The machine that never took the bad build is left alone.
    assert dbmod.machine_update_request(conn, "jsmith", "OLD-PC") is None
    assert any(a["action"] == "package.roll_fleet_back" for a in dbmod.fetch_audit(conn))


def test_rolling_back_to_another_recalled_build_is_refused(env):
    client, conn, _settings = env
    publish(client, "0.1.0")
    publish(client, "0.2.0", make_current=1)
    for version in ("0.1.0", "0.2.0"):
        dbmod.retract_package(conn, "companion", "windows", version, "bad",
                              dbmod.utcnow_iso())
    conn.commit()
    r = client.post("/api/v1/admin/packages/windows/0.2.0/roll-fleet-back?to=0.1.0")
    assert r.status_code == 409
    assert "recalled too" in r.json()["detail"]


def test_rolling_back_to_an_unpublished_build_is_refused(env):
    client, conn, _settings = env
    publish(client, "0.2.0", make_current=1)
    r = client.post("/api/v1/admin/packages/windows/0.2.0/roll-fleet-back?to=0.0.9")
    assert r.status_code == 404


# ------------------------------------------- recall arriving from the feed

FEED_BASE = "https://releases.example.test/v1"
CHANNEL_URL = f"{FEED_BASE}/channel.json"
SIG_URL = f"{FEED_BASE}/channel.json.sig"


class _FakeResp:
    def __init__(self, data: bytes):
        self._data, self._pos = data, 0
        self.status, self.headers = 200, {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass

    def read(self, n: int = -1) -> bytes:
        chunk = self._data[self._pos:] if n is None or n < 0 else self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


class _FakeOpener:
    def __init__(self, table):
        self.table = table

    def open(self, req, timeout=None):
        import urllib.error

        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url not in self.table:
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        return _FakeResp(self.table[url])


def signed_channel(records, retracted=None):
    channel = {
        "schema": 1, "generated_at": PUBLISHED_AT, "channel": "stable",
        "pubkey_id": release_trust.pubkey_id(TEST_PUBKEY),
        "dashboard_image": {"tag": "", "digest": ""},
        "packages": records,
    }
    if retracted is not None:
        channel["retracted"] = retracted
    sig = base64.b64encode(
        ed25519.sign(TEST_SEED, release_feed.canonical_channel_bytes(channel))
    ).decode("ascii")
    return channel, sig


def feed_record(version="0.2.0", platform="windows", body=b"feed-bytes"):
    record = {
        "kind": "companion", "platform": platform, "version": version,
        "filename": package_filename("companion", platform, version),
        "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body),
        "min_version": "0.0.0", "published_at": PUBLISHED_AT, "signed_binary": False,
    }
    signature = base64.b64encode(
        ed25519.sign(TEST_SEED, release_trust.canonical_record(record))).decode("ascii")
    out = dict(record, signature=signature,
               pubkey_id=release_trust.pubkey_id(TEST_PUBKEY),
               url=f"{FEED_BASE}/{platform}/{record['filename']}", notes="")
    return out, body


@pytest.fixture
def feed_env(tmp_path):
    db_path = tmp_path / "feed-channel.db"
    settings = Settings(
        db_path=str(db_path), report_token="sekrit", session_secret=SECRET,
        admin_users=frozenset({"owen"}), packages_dir=str(tmp_path / "pkgs"),
        release_pubkeys=(TEST_PUBKEY,), release_feed_url=CHANNEL_URL,
    )
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "pw"
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        as_user(client)
        yield client, conn, settings
        conn.close()


def test_a_recall_in_the_feed_is_honoured_under_the_manual_policy(feed_env, monkeypatch):
    """`manual` is the DEFAULT policy, and it governs whether new builds are
    taken -- never whether a withdrawn one keeps being offered."""
    client, conn, _settings = feed_env
    publish(client, "0.2.0", make_current=1)
    report(client, version="0.2.0")
    record, body = feed_record()
    channel, sig = signed_channel([], retracted=[
        {"kind": "companion", "platform": "windows", "version": "0.2.0",
         "reason": "it corrupts proxies", "at": PUBLISHED_AT}])
    monkeypatch.setattr(release_feed, "_opener", lambda: _FakeOpener({
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(),
        record["url"]: body,
    }))
    r = client.post("/api/v1/admin/feed/check")
    assert r.status_code == 200
    assert r.json()["retracted"] == ["companion/windows 0.2.0"]
    row = dbmod.get_package(conn, "windows", "0.2.0")
    assert row["is_current"] == 0
    assert row["retracted_reason"] == "it corrupts proxies"
    assert _upgrade_info(conn, "windows", "0.1.0") is None
    # Idempotent: the same channel tomorrow re-stamps nothing.
    assert client.post("/api/v1/admin/feed/check").json()["retracted"] == []


def test_a_recalled_record_is_never_published_from_the_feed(feed_env, monkeypatch):
    client, conn, _settings = feed_env
    assert client.post("/api/v1/admin/feed/policy",
                       json={"policy": "current"}).status_code == 200
    record, body = feed_record()
    channel, sig = signed_channel([record], retracted=[
        {"kind": "companion", "platform": "windows", "version": "0.2.0",
         "reason": "withdrawn", "at": PUBLISHED_AT}])
    monkeypatch.setattr(release_feed, "_opener", lambda: _FakeOpener({
        CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode(),
        record["url"]: body,
    }))
    r = client.post("/api/v1/admin/feed/check")
    assert r.status_code == 200
    assert r.json()["applied"] == []
    assert dbmod.get_package(conn, "windows", "0.2.0") is None
    view = release_feed.build_feed_view(conn, _settings, client.app.state)
    assert view["available"] == []
    assert view["retracted"][0]["reason"] == "withdrawn"


def test_a_malformed_retraction_entry_does_not_lose_the_good_ones():
    channel = {"retracted": [
        {"kind": "companion", "platform": "windows"},          # no version
        "not a dict",
        {"kind": "companion", "platform": "WINDOWS", "version": "0.2.0",
         "reason": "bad"},
    ]}
    out = release_feed.channel_retractions(channel)
    assert out == [{"kind": "companion", "platform": "windows", "version": "0.2.0",
                    "reason": "bad", "at": ""}]
    assert release_feed.channel_retractions({"retracted": "nope"}) == []
    assert release_feed.channel_retractions({}) == []


# ------------------------------------------- soak against v35's revert column


def test_a_machine_the_crash_guard_rolled_back_never_soaks(env):
    """`machine_state.upgrade_reverted_from` is the dashboard-self-update work
    package's column (v35). A build the guard had to undo has not soaked, no
    matter how long the machine has been sitting on it."""
    client, conn, _settings = env
    publish(client, "0.2.0")
    report(client, version="0.2.0", crashes=0)
    backdate_soak(conn, 240)
    conn.execute("UPDATE machine_state SET upgrade_reverted_from='0.2.0' "
                 "WHERE editor_username='jsmith'")
    conn.commit()
    r = client.post("/api/v1/admin/packages/windows/0.2.0/current")
    assert r.status_code == 409
    assert "rolled back" in r.json()["detail"]


def test_the_packages_page_names_an_arch_with_no_build(env):
    client, conn, settings = env
    publish(client, "0.2.0", platform="macos", arch="arm64")
    dbmod.set_current_package(conn, "macos", "0.2.0")
    conn.commit()
    report(client, machine="MACBOOK", version="0.1.0", platform="macos")
    conn.execute("UPDATE machine_state SET arch='x86_64' WHERE machine='MACBOOK'")
    conn.commit()
    view = build_packages_view(conn, settings)
    assert {"platform": "macos", "arch": "x86_64", "machines": 1} in view["arch_gaps"]
    page = client.get("/partials/admin/packages")
    assert "no macos/x86_64 build published" in page.text


# --------------------------------------------- the soak gate at the PUBLISH door
#
# REL-1 (usability sweep 2026-09-04). The 08-28 gate stood at three doors and
# all three were HTTP routes; the two that are not -- the feed's `current`
# policy and `./tools/release_macos.sh --publish --make-current` -- reached
# store_verified_package(make_current=True) and handed the whole fleet a build
# no computer anywhere had run. The gate lives in package_store now, so a
# publish that ASKS to be made current is published STAGED instead, with the
# refusal as a note.


def test_a_publish_that_asks_for_current_is_staged_when_it_has_not_soaked(env):
    client, conn, _settings = env
    # A first build becomes current: nothing is current yet, so there is no
    # fleet to protect and every computer is being offered nothing at all.
    assert publish(client, "0.2.0", make_current=1).status_code == 200
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.2.0"

    r = publish(client, "0.3.0", make_current=1)
    assert r.status_code == 200
    note = r.json()["note"]
    assert package_store.STAGED_SENTENCE in note
    assert "no computer has reported 0.3.0" in note
    # Published, on the shelf, and NOT what the fleet is offered.
    assert dbmod.get_package(conn, "windows", "0.3.0") is not None
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.2.0"

    # ...and the canary is still the way through, unchanged.
    report(client, version="0.3.0", crashes=0)
    backdate_soak(conn, 45)
    assert client.post("/api/v1/admin/packages/windows/0.3.0/current").status_code == 200
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.3.0"


def test_a_publish_that_does_not_ask_for_current_gets_no_note(env):
    client, _conn, _settings = env
    r = publish(client, "0.2.0")
    assert r.status_code == 200
    assert r.json()["note"] == ""


def test_soak_minutes_zero_is_the_way_back_to_the_old_behaviour(env):
    """The escape the 08-28 comment promised and the code did not give: with
    the gate at the publish door, `soak_minutes = 0` had to mean NO SOAK, not
    "zero minutes of a soak that also requires a computer to have reported"."""
    client, conn, _settings = env
    dbmod.meta_set(conn, "release_soak_minutes", "0")
    conn.commit()
    assert publish(client, "0.2.0", make_current=1).status_code == 200
    r = publish(client, "0.3.0", make_current=1)
    assert r.json()["note"] == ""
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.3.0"


def test_the_gate_at_the_publish_door_never_refuses_the_bytes(env):
    """A staged publish is a PUBLISH: the file is on disk and the row is
    there, so [ MAKE CURRENT ] and the per-computer push both work. The
    ordering refusal used to unlink the .part and 409 the whole thing, which
    is what made the feed re-download the same 40 MB on every check."""
    client, conn, settings = env
    publish(client, "0.2.0", make_current=1)
    publish(client, "0.3.0", make_current=1, body=b"v3-bytes")
    row = dbmod.get_package(conn, "windows", "0.3.0")
    path = settings.packages_path() / "windows" / row["filename"]
    assert path.read_bytes() == b"v3-bytes"
