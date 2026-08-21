"""comp-app-core-3 / comp-app-core-5 (2026-08-21): two ways the downgrade
floor could freeze a fleet.

  * a signed record whose min_version is ABOVE its own version raised every
    reporting machine's floor past the build being offered -- refusing that
    build, the corrected republish, and every later one below the typo, with
    no click anywhere and hands-on recovery per machine;
  * the floor file followed `log_path`, so on a machine whose log had been
    redirected the documented "delete ~/.ccsync/upgrade_floor.json" recovery
    removed nothing -- and editing log_path silently reset the floor.

Offers here are signed with a throwaway key, as in test_upgrade.py.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from ccsync_companion import config as config_mod
from ccsync_companion import ed25519
from ccsync_companion import release_pubkey
from ccsync_companion import upgrade as upgrade_mod
from ccsync_companion.upgrade import UpgradeManager

TEST_SEED = bytes(range(32))
TEST_PUBKEY = base64.b64encode(ed25519.public_key(TEST_SEED)).decode("ascii")


@pytest.fixture(autouse=True)
def _trust_the_test_key(monkeypatch):
    monkeypatch.setattr(release_pubkey, "RELEASE_PUBKEYS", (TEST_PUBKEY,))


# Offers use 0.9.99 so they stay NEWER than config.VERSION across bumps
# (the first run after the 0.9.44 bump found the offer was the running build).
def _info(version="0.9.99", min_version="0.0.0", body=b"new-exe-bytes"):
    record = {
        "kind": "companion",
        "platform": "windows",
        "version": version,
        "filename": f"ccsync-companion-{version}.exe",
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "min_version": min_version,
        "published_at": "2026-08-21T00:00:00Z",
        "signed_binary": False,
    }
    info = dict(record)
    info["url"] = f"/api/v1/companion/package/windows/{version}"
    info["signature"] = base64.b64encode(
        ed25519.sign(TEST_SEED, release_pubkey.canonical_record(record))
    ).decode("ascii")
    info["pubkey_id"] = release_pubkey.pubkey_id(TEST_PUBKEY)
    return info


def _cfg(tmp_path, **overrides):
    cfg = {"dashboard_url": "http://dash.example.com",
           "log_path": str(tmp_path / ".ccsync" / "companion.log")}
    cfg.update(overrides)
    return cfg


# -- comp-app-core-3 --------------------------------------------------------


def test_a_record_demanding_more_than_it_offers_never_raises_the_floor(tmp_path, caplog):
    """One stale CCSYNC_MIN_VERSION in the environment is signed, published
    and remembered by every machine that merely RECEIVES the offer."""
    floor = tmp_path / "floor.json"
    mgr = UpgradeManager(_cfg(tmp_path), floor_file=floor)

    with caplog.at_level("ERROR"):
        mgr.note_report_response({"upgrade": _info(version="0.9.99",
                                                   min_version="0.10.5")})
    assert mgr.available is None
    assert upgrade_mod.read_floor(floor) == ""
    assert not floor.exists()

    # ...and the corrected republish is taken, which is the whole point: the
    # fleet is not frozen until someone visits every machine.
    mgr.note_report_response({"upgrade": _info(version="0.9.99",
                                               min_version="0.9.0")})
    assert mgr.available["version"] == "0.9.99"
    assert upgrade_mod.read_floor(floor) == "0.9.0"


def test_a_record_whose_floor_is_its_own_version_is_still_fine(tmp_path):
    """"You may not go below this build" is the ordinary, intended shape."""
    floor = tmp_path / "floor.json"
    mgr = UpgradeManager(_cfg(tmp_path), floor_file=floor)
    mgr.note_report_response({"upgrade": _info(version="0.9.99",
                                               min_version="0.9.99")})
    assert mgr.available["version"] == "0.9.99"
    assert upgrade_mod.read_floor(floor) == "0.9.99"


def test_an_unrankable_min_version_is_not_this_check(tmp_path):
    """below_floor and note_floor already handle a version string nobody can
    rank; this guard must not start refusing offers on their behalf."""
    assert upgrade_mod._min_version_above_own({"version": "0.9.99",
                                               "min_version": "nightly"}) is False
    assert upgrade_mod._min_version_above_own({"version": "nightly",
                                               "min_version": "0.9.99"}) is False
    assert upgrade_mod._min_version_above_own({"version": "0.9.99"}) is False
    assert upgrade_mod._min_version_above_own(None) is False


# -- comp-app-core-5 --------------------------------------------------------


def test_the_floor_lives_beside_identity_not_beside_the_log(tmp_path):
    redirected = _cfg(tmp_path, log_path=str(tmp_path / "logs" / "ccsync.log"))
    assert upgrade_mod.floor_path(redirected) == (
        config_mod.CONFIG_DIR / upgrade_mod.FLOOR_FILENAME)
    # ...which is where docs/RELEASE.md has always told the operator to look.
    assert upgrade_mod.floor_path(redirected).name == "upgrade_floor.json"


def test_a_floor_written_beside_a_redirected_log_is_carried_forward(tmp_path):
    """The floor only ever goes up: moving the file must not lower it to
    nothing on the machines the move was made for."""
    redirected = _cfg(tmp_path, log_path=str(tmp_path / "logs" / "ccsync.log"))
    legacy = upgrade_mod.legacy_floor_path(redirected)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"min_version": "0.9.41"}), encoding="utf-8")

    mgr = UpgradeManager(redirected)
    assert upgrade_mod.read_floor(mgr._floor_file) == "0.9.41"
    # And the rollback it was remembering is still refused.
    mgr.note_report_response({"upgrade": _info(version="0.9.3", min_version="0.0.0")})
    assert mgr.available is None
