"""GET /api/v1/site publishes the NAS SSH host key editors pin (GL-19, CR-368,
2026-10-07). It is public-key material, a deploy-time fact, and not editable
from Settings."""
from __future__ import annotations

from fastapi.testclient import TestClient

from ccsync_dashboard import site_store
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPINNEDKEYPINNEDKEYPINNEDKEYPINNEDKEY00"


def _get(tmp_path, env):
    settings = Settings.from_env({"DASH_DB_PATH": str(tmp_path / "d.db"), **env})
    with TestClient(create_app(settings)) as client:
        return client.get("/api/v1/site").json()


def test_the_manifest_carries_the_published_host_key(tmp_path):
    assert _get(tmp_path, {"DASH_SITE_SFTP_HOSTKEY": KEY})["sftp_hostkey"] == KEY


def test_whitespace_is_normalised_so_a_wrapped_value_still_parses(tmp_path):
    body = _get(tmp_path, {"DASH_SITE_SFTP_HOSTKEY": f"  {KEY.replace(' ', '   ')}\n"})
    assert body["sftp_hostkey"] == KEY


def test_an_unpublished_key_is_a_blank_never_another_value(tmp_path):
    assert _get(tmp_path, {})["sftp_hostkey"] == ""


def test_it_is_not_a_settings_key():
    # A pin an admin can retype from a browser is not much of a pin.
    assert "sftp_hostkey" not in site_store.KEYS


def test_an_appliance_serves_the_sidecars_published_key(tmp_path, monkeypatch):
    """The appliance has no deploy to set DASH_SITE_SFTP_HOSTKEY; its sftp
    sidecar publishes the public half into a read-only mount (CR-368 follow-up,
    2026-10-07), so the lane pin exists on the main customer path too."""
    pub = tmp_path / "ssh_host_ed25519_key.pub"
    pub.write_text(KEY + " ccsync-sftp\n", encoding="utf-8")
    monkeypatch.setenv("DASH_SFTP_HOSTKEY_FILE", str(pub))
    assert _get(tmp_path, {})["sftp_hostkey"] == KEY
    # the deploy-time value still wins
    other = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOTHEROTHEROTHEROTHEROTHEROTHER000"
    assert _get(tmp_path, {"DASH_SITE_SFTP_HOSTKEY": other})["sftp_hostkey"] == other


def test_a_garbled_published_key_is_unpinned_not_half_parsed(tmp_path, monkeypatch):
    pub = tmp_path / "k.pub"
    pub.write_text("ssh-rsa AAAA\n", encoding="utf-8")
    monkeypatch.setenv("DASH_SFTP_HOSTKEY_FILE", str(pub))
    assert _get(tmp_path, {})["sftp_hostkey"] == ""
    monkeypatch.setenv("DASH_SFTP_HOSTKEY_FILE", str(tmp_path / "missing"))
    assert _get(tmp_path, {})["sftp_hostkey"] == ""
