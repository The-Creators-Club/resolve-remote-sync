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
    # Brand + the read-only extension list (2026-08-17,
    # COMMERCIAL_READINESS.md items 10/11).
    "org_short", "product_name", "video_extensions",
    # The optional-feature switches (items 2/3), already served by api_site.
    "features",
    # Which local vision model the b-roll indexer should load (2026-08-18).
    "indexer",
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
    assert body["indexer"] == {"model_tier": "good"}


def test_indexer_model_tier_is_settable_via_env(tmp_path):
    settings = replace(Settings.from_env({"DASH_SITE_INDEXER_MODEL_TIER": "best"}),
                       db_path=str(tmp_path / "s.db"))
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/v1/site").json()
    assert body["indexer"] == {"model_tier": "best"}


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


# -- brand + the pinned lists (2026-08-17, COMMERCIAL_READINESS.md items 10/11)

def test_the_brand_is_site_data_with_a_product_default(tmp_path):
    settings = replace(Settings.from_env({**SITE_ENV, "DASH_SITE_ORG_SHORT": "CC"}),
                       db_path=str(tmp_path / "s.db"), session_secret="secret")
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/v1/site").json()
    assert body["org_name"] == "Creators Club"
    assert body["org_short"] == "CC"
    assert body["product_name"] == "CC Sync"


def test_org_short_falls_back_to_the_full_name(tmp_path):
    settings = replace(Settings.from_env(SITE_ENV), db_path=str(tmp_path / "s.db"),
                       session_secret="secret")
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/v1/site").json()
    assert body["org_short"] == "Creators Club"


def test_an_unbranded_deployment_publishes_the_product_not_a_tenant(tmp_path):
    """The whole point: a fresh install must show the PRODUCT's name, never
    the first customer's."""
    settings = Settings(db_path=str(tmp_path / "s.db"))
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/v1/site").json()
    assert body["org_name"] == "" and body["org_short"] == ""
    assert body["product_name"] == "CC Sync"


def test_a_reseller_can_rename_the_product(tmp_path):
    settings = replace(Settings.from_env({"DASH_SITE_PRODUCT_NAME": "Acme Sync"}),
                       db_path=str(tmp_path / "s.db"))
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/site").json()["product_name"] == "Acme Sync"


def test_the_topbar_wears_the_sites_brand_and_falls_back_to_the_product(tmp_path):
    from ccsync_dashboard import ui

    settings = replace(Settings.from_env({**SITE_ENV, "DASH_SITE_ORG_SHORT": "CC"}),
                       db_path=str(tmp_path / "s.db"), session_secret="secret",
                       dev_insecure=True)
    with TestClient(create_app(settings)) as client:
        assert "CC <span" in client.get("/partials/topbar").text

    plain = replace(Settings(db_path=str(tmp_path / "b.db")), dev_insecure=True)
    with TestClient(create_app(plain)) as client:
        assert "CC SYNC <span" in client.get("/partials/topbar").text
    assert ui is not None


def test_the_video_extension_list_is_served_read_only(tmp_path):
    """Published so a future client reads it instead of growing a fourth copy;
    NOT configurable -- server/tests/test_cross_component.py pins the three
    in-repo copies byte-identical to this one."""
    settings = Settings(db_path=str(tmp_path / "s.db"))
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/v1/site").json()
    assert body["video_extensions"] == provision.VIDEO_EXTENSIONS
    assert ".braw" in body["video_extensions"]


def test_the_tree_lists_can_be_overridden_by_the_site(monkeypatch):
    """site.toml [tree] template_folders / shared_assets reach the container
    as DASH_SITE_*; the DEFAULTS are what the cross-component test pins."""
    import importlib

    monkeypatch.setenv("DASH_SITE_TEMPLATE_FOLDERS", "Footage, Audio ,Graphics")
    monkeypatch.setenv("DASH_SITE_SHARED_ASSETS", "Assets/Luts,Assets/SFX")
    mod = importlib.reload(provision)
    try:
        assert mod.TEMPLATE_FOLDERS == ["Footage", "Audio", "Graphics"]
        assert mod.SHARED_ASSET_FOLDERS == [
            ("assets-luts", "Assets/Luts", "Assets/Luts (LUT library)"),
            ("assets-sfx", "Assets/SFX", "Assets/SFX"),
        ]
        # The defaults are untouched by an override -- they are the contract.
        assert mod.DEFAULT_TEMPLATE_FOLDERS[0] == "AE"
    finally:
        monkeypatch.delenv("DASH_SITE_TEMPLATE_FOLDERS")
        monkeypatch.delenv("DASH_SITE_SHARED_ASSETS")
        importlib.reload(provision)


def test_a_blank_override_is_not_an_empty_project_template(monkeypatch):
    """An empty list would create projects with no subfolders at all."""
    import importlib

    monkeypatch.setenv("DASH_SITE_TEMPLATE_FOLDERS", "  ,  ")
    mod = importlib.reload(provision)
    try:
        assert mod.TEMPLATE_FOLDERS == mod.DEFAULT_TEMPLATE_FOLDERS
    finally:
        monkeypatch.delenv("DASH_SITE_TEMPLATE_FOLDERS")
        importlib.reload(provision)


# --------------------------------------------------------------------------
# Optional features (COMMERCIAL_READINESS.md items 2 + 3, 2026-08-17)
# --------------------------------------------------------------------------
# The manifest is how every client -- companion, installer, wizard -- learns
# which optional features this customer turned on. BOTH DEFAULT FALSE, and the
# default is what the vendor build ships: the customer, not the vendor, decides
# whether downloading third-party YouTube material is lawful for them
# (docs/legal/YOUTUBE_FEATURE_NOTICE.md).

def _features(tmp_path, **flags):
    settings = Settings(db_path=str(tmp_path / "f.db"), **flags)
    with TestClient(create_app(settings)) as client:
        return client.get("/api/v1/site").json()["features"]


def test_the_manifest_publishes_both_feature_flags_off_by_default(tmp_path):
    assert _features(tmp_path) == {"youtube_download": False,
                                   "youtube_unblock": False}


def test_a_site_that_turned_the_downloader_on_says_so(tmp_path):
    assert _features(tmp_path, site_feature_youtube_download=True) == {
        "youtube_download": True, "youtube_unblock": False}


def test_unblock_is_never_published_without_the_downloader(tmp_path):
    """An {download: false, unblock: true} answer would tell every companion to
    install a JS challenge solver for a feature they cannot use."""
    assert _features(tmp_path, site_feature_youtube_unblock=True)[
        "youtube_unblock"] is False
    assert _features(tmp_path, site_feature_youtube_download=True,
                     site_feature_youtube_unblock=True)["youtube_unblock"] is True


def test_the_features_block_carries_no_secret(tmp_path):
    """The manifest is OPEN (app.py's _OPEN_EXACT). Whether a feature is on is
    not a secret; nothing else may join it here."""
    features = _features(tmp_path)
    assert set(features) == {"youtube_download", "youtube_unblock"}
    assert all(isinstance(v, bool) for v in features.values())


def test_the_env_spelling_is_one_and_nothing_else(tmp_path):
    """"1" and nothing else is on, matching DASH_BROLL_ENABLED: an unset,
    empty, misspelt or "true"-shaped value all mean OFF, because off is the
    state that is safe to be wrong about."""
    for value in ("", "0", "true", "True", "yes", "on"):
        s = Settings.from_env({"DASH_SITE_YOUTUBE_DOWNLOAD": value})
        assert s.site_feature_youtube_download is False, value
    assert Settings.from_env(
        {"DASH_SITE_YOUTUBE_DOWNLOAD": "1"}).site_feature_youtube_download is True
