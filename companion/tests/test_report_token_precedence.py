"""Which fleet credential this machine presents, and that it survives sign-in.

COMMERCIAL_READINESS.md item 15 (2026-08-17). Every companion in the field
holds ONE shared DASH_REPORT_TOKEN; an admin can now mint a per-editor token
("cce1.<id>.<secret>") that is revocable for that editor alone. The companion
prefers it wherever it finds it.

The failure this guards against is subtle and total: /api/v1/verify only ever
answers with the SHARED token, so a tray sign-in that rewrote identity.json
from that response alone would silently demote a machine an admin had already
migrated -- and it would keep working, so nobody would notice until the shared
token was turned off.
"""

from __future__ import annotations

import base64
import time

import pytest

from ccsync_companion import identity as identity_mod
from ccsync_companion.identity import (
    IdentityManager,
    load_identity,
    preferred_report_token,
    save_identity,
)

EDITOR_TOKEN = "cce1." + "0" * 16 + "." + "a" * 48
OTHER_EDITOR_TOKEN = "cce1." + "1" * 16 + "." + "b" * 48


def _b64u(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).rstrip(b"=").decode("ascii")


def _token(username="owen"):
    return f"v2.identity.{_b64u(username)}.{int(time.time()) + 3600}.deadbeef"


# ------------------------------------------------------------- precedence

def test_the_per_editor_token_in_identity_json_wins_over_everything():
    cfg = {"dashboard_token": "shared-installed", "report_token": OTHER_EDITOR_TOKEN}
    identity = {"report_token": "shared-signed-in", "editor_report_token": EDITOR_TOKEN}
    token, source = preferred_report_token(cfg, identity)
    assert token == EDITOR_TOKEN
    assert source == "identity.json"


def test_config_report_token_beats_both_shared_values():
    cfg = {"dashboard_token": "shared-installed", "report_token": EDITOR_TOKEN}
    identity = {"report_token": "shared-signed-in"}
    assert preferred_report_token(cfg, identity)[0] == EDITOR_TOKEN


def test_the_signed_in_shared_token_beats_a_stale_config_one():
    """The pre-existing rule, unchanged: config.toml is written by the
    installer and goes stale, identity.json is rewritten at every sign-in."""
    cfg = {"dashboard_token": "stale"}
    identity = {"report_token": "fresh"}
    assert preferred_report_token(cfg, identity)[0] == "fresh"


def test_no_credential_anywhere_is_an_empty_string_not_a_crash():
    assert preferred_report_token({}, None) == ("", "none")


def test_blank_values_are_skipped_rather_than_adopted():
    cfg = {"dashboard_token": "shared", "report_token": "   "}
    assert preferred_report_token(cfg, {"editor_report_token": ""})[0] == "shared"


# --------------------------------------------------------- identity.json

def test_the_per_editor_token_round_trips_through_the_file(tmp_path):
    path = tmp_path / "identity.json"
    save_identity(path, "owen", _token(), report_token="shared",
                  editor_report_token=EDITOR_TOKEN)
    assert load_identity(path)["editor_report_token"] == EDITOR_TOKEN


def test_save_identity_hardens_the_file_before_the_rename(tmp_path, monkeypatch):
    """The secret must never exist on disk under wider permissions, not even
    for the instant between the write and the replace."""
    hardened = []
    monkeypatch.setattr(identity_mod.secretfile, "harden",
                        lambda p: hardened.append(str(p)) or True)
    path = tmp_path / "identity.json"
    save_identity(path, "owen", _token())
    assert hardened == [str(path) + ".tmp"]


# ------------------------------------------------------- IdentityManager

class FakePost:
    """/api/v1/verify's success shape. It NEVER returns a per-editor token --
    the dashboard has none to give; an admin hands it over out of band."""

    def __init__(self, username="owen"):
        self.username = username

    def __call__(self, url, data, headers, timeout):
        return {"ok": True, "username": self.username, "token": _token(self.username),
                "role": "editor", "report_token": "shared-from-verify"}


@pytest.fixture
def manager_cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(identity_mod.config_mod, "CONFIG_DIR", tmp_path)
    return {"dashboard_url": "http://dash.example", "dashboard_token": "shared-installed"}


def test_the_manager_publishes_the_per_editor_token_into_cfg(manager_cfg, tmp_path):
    save_identity(tmp_path / "identity.json", "owen", _token(),
                  report_token="shared-signed-in", editor_report_token=EDITOR_TOKEN)
    manager = IdentityManager(manager_cfg, http_post=FakePost())
    assert manager.editor_report_token == EDITOR_TOKEN
    assert manager_cfg["dashboard_token"] == EDITOR_TOKEN


def test_signing_in_does_not_demote_a_migrated_machine(manager_cfg, tmp_path):
    save_identity(tmp_path / "identity.json", "owen", _token(),
                  report_token="shared-signed-in", editor_report_token=EDITOR_TOKEN)
    manager = IdentityManager(manager_cfg, http_post=FakePost())

    ok, error = manager.sign_in("owen", "pw")
    assert (ok, error) == (True, None)
    # The shared token was refreshed from the response...
    assert manager.report_token == "shared-from-verify"
    # ...and the per-editor one survived, in memory AND on disk.
    assert manager.editor_report_token == EDITOR_TOKEN
    assert load_identity(tmp_path / "identity.json")["editor_report_token"] == EDITOR_TOKEN
    assert manager_cfg["dashboard_token"] == EDITOR_TOKEN


def test_a_machine_with_no_per_editor_token_still_uses_the_shared_one(manager_cfg):
    manager = IdentityManager(manager_cfg, http_post=FakePost())
    assert manager.sign_in("owen", "pw") == (True, None)
    assert manager.editor_report_token is None
    assert manager_cfg["dashboard_token"] == "shared-from-verify"


def test_the_per_editor_token_survives_an_expired_identity(manager_cfg, tmp_path):
    """A credential is not an identity: reports must still carry the token
    when the signed identity has lapsed, which is when it matters most."""
    expired = f"v2.identity.{_b64u('owen')}.{int(time.time()) - 10}.deadbeef"
    save_identity(tmp_path / "identity.json", "owen", expired,
                  editor_report_token=EDITOR_TOKEN)
    manager = IdentityManager(manager_cfg, http_post=FakePost())
    assert manager.valid() is False
    assert manager.editor_report_token == EDITOR_TOKEN
