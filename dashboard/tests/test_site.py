"""GET /api/v1/site -- the site manifest (SYNOLOGY_PORT_PLAN.md WP0 step 3).

The contract other components code against: an installer, the onboarding
wizard and the companion all read this BEFORE anyone has logged in, so it is
open, and every value is either this site's own or an empty string -- never
another tenant's.
"""
from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from ccsync_dashboard import provision
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from fake_syncthing import FakeSyncthing

EXPECTED_KEYS = {
    "schema", "org_name", "tree_name", "canonical_prefix", "remote_root", "smb_unc",
    "sftp_host", "sftp_port", "sftp_chunk_size", "sftp_concurrency", "sftp_shell_type",
    "rclone_remote",
    "nas_syncthing_id", "dashboard_url", "template_folders", "shared_asset_folders",
    "nas_kind",
}

SITE_ENV = {
    "DASH_SITE_ORG_NAME": "Creators Club",
    "DASH_SITE_TREE_NAME": "Creators_Club",
    "DASH_SITE_REMOTE_ROOT": "/mnt/tank/TheCreatorsPool/Creators_Club",
    "DASH_SITE_SMB_UNC": r"\\nas.example\TheCreatorsPool\Creators_Club",
    "DASH_SITE_SFTP_HOST": "nas.example",
    "DASH_SITE_SFTP_PORT": "2222",
    "DASH_SITE_RCLONE_REMOTE": "creators_club_sftp",
    "DASH_SITE_NAS_SYNCTHING_ID": "AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA",
    "DASH_SITE_DASHBOARD_URL": "https://nas.example.ts.net/",
}


def test_site_is_readable_without_logging_in(tmp_path):
    """Same posture as /api/v1/health: the wizard has no session yet, and the
    installer runs before the editor has an account at all."""
    settings = replace(Settings.from_env(SITE_ENV),
                       db_path=str(tmp_path / "s.db"), session_secret="secret")
    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/v1/site")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == EXPECTED_KEYS
    assert body["schema"] == 1
    assert body["org_name"] == "Creators Club"
    assert body["remote_root"] == "/mnt/tank/TheCreatorsPool/Creators_Club"
    assert body["smb_unc"] == r"\\nas.example\TheCreatorsPool\Creators_Club"
    assert body["sftp_host"] == "nas.example" and body["sftp_port"] == 2222
    assert body["rclone_remote"] == "creators_club_sftp"
    assert body["dashboard_url"] == "https://nas.example.ts.net"      # no trailing slash
    assert body["nas_kind"] == "truenas"
    assert body["canonical_prefix"] == "P:\\"


def test_unset_values_are_empty_strings_not_another_tenants(tmp_path):
    """The whole reason this route exists: a deployment that has not been
    told its own addresses must say so, not hand out the first fleet's."""
    settings = Settings(db_path=str(tmp_path / "s.db"))
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/v1/site").json()

    for key in ("org_name", "tree_name", "remote_root", "smb_unc", "sftp_host",
                "rclone_remote", "nas_syncthing_id", "dashboard_url"):
        assert body[key] == "", key
    # ...except the two that are conventions of this product rather than of a
    # site: the P: mapping (deliberately hardcoded, 2026-07-26) and SSH's port.
    assert body["canonical_prefix"] == "P:\\"
    assert body["sftp_port"] == 22
    # SFTP tuning is the server's to state only when it knows better than the
    # companion default (Synology's OpenSSH 8.2 chunk ceiling); unset = silent.
    assert body["sftp_chunk_size"] == "" and body["sftp_concurrency"] == 0
    assert body["sftp_shell_type"] == ""
    assert body["schema"] == 1


def test_folder_lists_come_from_provision_so_they_cannot_drift(tmp_path):
    settings = Settings(db_path=str(tmp_path / "s.db"))
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/v1/site").json()

    assert body["template_folders"] == provision.TEMPLATE_FOLDERS
    assert body["shared_asset_folders"] == [
        {"id": fid, "rel": rel, "label": label}
        for fid, rel, label in provision.SHARED_ASSET_FOLDERS
    ]


def test_the_live_syncthing_id_beats_the_configured_one(tmp_path):
    """A re-created Syncthing config regenerates the device ID, and a stale
    DASH_SITE_NAS_SYNCTHING_ID would point every new editor at a device that
    no longer exists (the "stuck lane C" incident). Ask the live one."""
    syncthing = FakeSyncthing().start()
    try:
        settings = Settings(
            db_path=str(tmp_path / "s.db"),
            syncthing_url=syncthing.url, syncthing_api_key="fake-key",
            site_nas_syncthing_id="STALEID-STALEID-STALEID-STALEID-STALEID-STALEID-STALEID-STALEID",
        )
        with TestClient(create_app(settings)) as client:
            body = client.get("/api/v1/site").json()
    finally:
        syncthing.stop()

    assert body["nas_syncthing_id"] == syncthing.state["my_id"]


def test_an_unreachable_syncthing_falls_back_to_the_configured_id(tmp_path):
    """Fails soft, and only pays the timeout once a minute: this route is
    open, so an unreachable Syncthing must not make it expensive to call."""
    configured = "CONFIGD-CONFIGD-CONFIGD-CONFIGD-CONFIGD-CONFIGD-CONFIGD-CONFIGD"
    settings = Settings(db_path=str(tmp_path / "s.db"),
                        syncthing_url="http://127.0.0.1:9",      # discard port
                        syncthing_api_key="fake-key",
                        site_nas_syncthing_id=configured)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/site").json()["nas_syncthing_id"] == configured
        assert client.get("/api/v1/site").json()["nas_syncthing_id"] == configured


def test_site_carries_no_credential_and_no_fleet_inventory(tmp_path):
    """This response is readable by anyone who can reach the port. Nothing in
    it may name a user, a project or a secret."""
    settings = Settings(db_path=str(tmp_path / "s.db"), session_secret="secret",
                        report_token="super-secret-token", nas_pw="nas-password",
                        broll_ingest_token="ingest-secret", smb_host="nas.example")
    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/v1/site")

    for secret in ("super-secret-token", "nas-password", "ingest-secret"):
        assert secret not in resp.text
    assert set(resp.json()) == EXPECTED_KEYS


def test_smb_host_falls_back_to_the_nas_host_for_pre_manifest_containers():
    """A TrueNAS container deployed before 2026-08-17 has TRUENAS_HOST in its
    env but no DASH_SMB_HOST (that used to be a code default). Landing this
    code there without --recreate must not refuse every login."""
    fallback = Settings.from_env({"TRUENAS_HOST": "192.0.2.10", "TRUENAS_PW": "x"})
    assert fallback.smb_host == "192.0.2.10"
    explicit = Settings.from_env({"TRUENAS_HOST": "192.0.2.10", "DASH_SMB_HOST": "smb.example"})
    assert explicit.smb_host == "smb.example"
    neither = Settings.from_env({})
    assert neither.smb_host == ""
