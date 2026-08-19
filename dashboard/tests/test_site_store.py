"""site_store.py -- the site manifest as DB data, and its precedence over
DASH_SITE_* env (ZERO_TOUCH_PLAN.md WP D, 2026-08-17)."""
from __future__ import annotations

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import provision, site_store
from ccsync_dashboard.settings import Settings


@pytest.fixture
def conn(tmp_path):
    connection = dbmod.connect(tmp_path / "s.db")
    dbmod.migrate(connection)
    yield connection
    connection.close()


# --------------------------------------------------------------- validate()

def test_canonical_prefix_accepts_a_drive_letter():
    assert site_store.validate("canonical_prefix", "P:") == "P:\\"
    assert site_store.validate("canonical_prefix", "p:\\") == "p:\\"


def test_canonical_prefix_accepts_a_posix_path():
    assert site_store.validate("canonical_prefix", "/mnt/tree") == "/mnt/tree"


def test_canonical_prefix_rejects_garbage():
    for bad in ("", "not-a-path", "PP:\\", "../etc"):
        with pytest.raises(site_store.SiteValidationError):
            site_store.validate("canonical_prefix", bad)


def test_int_fields_reject_non_numeric():
    assert site_store.validate("sftp_port", "2222") == "2222"
    assert site_store.validate("sftp_port", "") == ""
    with pytest.raises(site_store.SiteValidationError):
        site_store.validate("sftp_port", "not-a-number")
    with pytest.raises(site_store.SiteValidationError):
        site_store.validate("sftp_port", "-1")


def test_bool_fields_are_one_or_zero_only():
    assert site_store.validate("features.youtube_download", "1") == "1"
    assert site_store.validate("features.youtube_download", "0") == "0"
    assert site_store.validate("features.youtube_download", "") == "0"
    for bad in ("true", "yes", "on"):
        with pytest.raises(site_store.SiteValidationError):
            site_store.validate("features.youtube_download", bad)


def test_indexer_model_tier_accepts_good_and_best():
    assert site_store.validate("indexer_model_tier", "good") == "good"
    assert site_store.validate("indexer_model_tier", "BEST") == "best"


def test_indexer_model_tier_rejects_anything_else():
    for bad in ("", "medium", "qwen3-vl-8b", "1"):
        with pytest.raises(site_store.SiteValidationError):
            site_store.validate("indexer_model_tier", bad)


def test_unknown_key_is_refused():
    with pytest.raises(site_store.SiteValidationError):
        site_store.validate("not_a_real_key", "x")


def test_control_characters_are_refused():
    with pytest.raises(site_store.SiteValidationError):
        site_store.validate("org_name", "bad\x00name")


# ----------------------------------------------------------- set_many/get_all

def test_set_many_validates_everything_before_writing_anything(conn):
    with pytest.raises(site_store.SiteValidationError):
        site_store.set_many(conn, {"org_name": "Studio", "sftp_port": "nope"}, updated_by="admin")
    conn.commit()
    assert site_store.get_all(conn) == {}


def test_set_many_then_get_all_round_trips(conn):
    site_store.set_many(conn, {"org_name": "Studio", "sftp_port": "2222"}, updated_by="admin")
    conn.commit()
    values = site_store.get_all(conn)
    assert values["org_name"] == "Studio"
    assert values["sftp_port"] == "2222"


def test_set_many_upserts_on_repeat(conn):
    site_store.set_many(conn, {"org_name": "First"}, updated_by="admin")
    conn.commit()
    site_store.set_many(conn, {"org_name": "Second"}, updated_by="admin2")
    conn.commit()
    assert site_store.get_all(conn)["org_name"] == "Second"
    row = conn.execute("SELECT updated_by FROM site_settings WHERE key='org_name'").fetchone()
    assert row["updated_by"] == "admin2"


# ------------------------------------------------------------- precedence

def test_an_env_only_deployment_is_unaffected_by_an_empty_table(conn):
    """The whole point: existing sites keep serving exactly what they do
    today until Settings is written."""
    settings = Settings.from_env({
        "DASH_SITE_ORG_NAME": "Creators Club",
        "DASH_SITE_TREE_NAME": "Creators_Club",
    })
    manifest = site_store.resolved_manifest(conn, settings)
    assert manifest["org_name"] == "Creators Club"
    assert manifest["tree_name"] == "Creators_Club"
    assert manifest["canonical_prefix"] == "P:\\"   # the built-in default
    assert manifest["_from_db"] == []


def test_a_db_row_wins_over_the_env_value(conn):
    settings = Settings.from_env({"DASH_SITE_ORG_NAME": "Env Studio"})
    site_store.set_many(conn, {"org_name": "DB Studio"}, updated_by="admin")
    conn.commit()
    manifest = site_store.resolved_manifest(conn, settings)
    assert manifest["org_name"] == "DB Studio"
    assert "org_name" in manifest["_from_db"]


def test_a_fresh_appliance_with_no_env_serves_built_in_defaults(conn):
    settings = Settings()
    manifest = site_store.resolved_manifest(conn, settings)
    assert manifest["org_name"] == ""
    assert manifest["product_name"] == "CC Sync"
    assert manifest["canonical_prefix"] == "P:\\"
    assert manifest["template_folders"] == provision.TEMPLATE_FOLDERS


def test_brand_logo_is_blank_until_a_site_says(conn):
    """The VENDOR default. A fresh install must wear the product's own mark
    rather than inherit whichever tenant's logo the build happened to ship
    (2026-08-18) -- and a blank is also how a fleet turns its own logo back
    off, so it has to survive the round trip as a blank."""
    settings = Settings()
    assert site_store.resolved_manifest(conn, settings)["brand_logo"] == ""


def test_brand_logo_db_row_wins_over_env(conn):
    """The Settings page rebrands a fleet with no container --recreate: the
    env var is only the deploy-time seed (server/install_dashboard_app.py)."""
    settings = Settings.from_env({"DASH_SITE_BRAND_LOGO": "cc_mark_white.png"})
    assert settings.site_brand_logo == "cc_mark_white.png"
    manifest = site_store.resolved_manifest(conn, settings)
    assert manifest["brand_logo"] == "cc_mark_white.png"    # env, no DB row yet

    site_store.set_many(conn, {"brand_logo": "acme_mark.png"}, updated_by="admin")
    conn.commit()
    manifest = site_store.resolved_manifest(conn, settings)
    assert manifest["brand_logo"] == "acme_mark.png"
    assert "brand_logo" in manifest["_from_db"]


def test_indexer_model_tier_defaults_to_good(conn):
    settings = Settings()
    manifest = site_store.resolved_manifest(conn, settings)
    assert manifest["indexer"] == {"model_tier": "good"}


def test_indexer_model_tier_db_row_wins_over_env(conn):
    settings = Settings.from_env({"DASH_SITE_INDEXER_MODEL_TIER": "best"})
    assert settings.site_indexer_model_tier == "best"
    manifest = site_store.resolved_manifest(conn, settings)
    assert manifest["indexer"]["model_tier"] == "best"      # env, no DB row yet

    site_store.set_many(conn, {"indexer_model_tier": "good"}, updated_by="admin")
    conn.commit()
    manifest = site_store.resolved_manifest(conn, settings)
    assert manifest["indexer"]["model_tier"] == "good"      # DB now wins
    assert "indexer_model_tier" in manifest["_from_db"]


def test_settings_falls_back_to_good_for_an_unrecognised_env_tier():
    """Mirrors DASH_RELEASE_FEED_POLICY's own rule: a typo must not silently
    hand every indexing machine the heavier model it never asked for."""
    settings = Settings.from_env({"DASH_SITE_INDEXER_MODEL_TIER": "ultra"})
    assert settings.site_indexer_model_tier == "good"


def test_template_folders_override_from_db(conn):
    settings = Settings()
    site_store.set_many(conn, {"template_folders": "Footage, Audio"}, updated_by="admin")
    conn.commit()
    manifest = site_store.resolved_manifest(conn, settings)
    assert manifest["template_folders"] == ["Footage", "Audio"]


def test_shared_asset_folders_override_from_db_derives_ids_and_labels(conn):
    settings = Settings()
    site_store.set_many(conn, {"shared_asset_folders": "Assets/Luts,Assets/SFX"}, updated_by="admin")
    conn.commit()
    manifest = site_store.resolved_manifest(conn, settings)
    assert manifest["shared_asset_folders"] == [
        {"id": "assets-luts", "rel": "Assets/Luts", "label": "Assets/Luts (LUT library)"},
        {"id": "assets-sfx", "rel": "Assets/SFX", "label": "Assets/SFX"},
    ]


def test_features_block_shape(conn):
    settings = Settings()
    site_store.set_many(conn, {"features.youtube_download": "1"}, updated_by="admin")
    conn.commit()
    manifest = site_store.resolved_manifest(conn, settings)
    # ai_cli_providers joined the block 2026-08-18 (ai_providers.py) and is
    # false unless a site says otherwise, like both YouTube flags. It is NOT
    # in `GET /api/v1/site` -- see test_site.py, which pins that the open
    # manifest still carries exactly the two.
    assert manifest["features"] == {"youtube_download": True,
                                    "youtube_unblock": False,
                                    "ai_cli_providers": False,
                                    "auto_update": False}


# ------------------------------------------------------------------- seed

def test_seed_is_a_no_op_with_no_dash_site_env(conn, monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("DASH_SITE_"):
            monkeypatch.delenv(key, raising=False)
    settings = Settings()
    seeded = site_store.seed_from_env_once(conn, settings)
    assert seeded is False
    assert site_store.table_is_empty(conn)


def test_seed_copies_env_into_the_table_once(conn, monkeypatch):
    monkeypatch.setenv("DASH_SITE_ORG_NAME", "Creators Club")
    settings = Settings.from_env({"DASH_SITE_ORG_NAME": "Creators Club"})
    seeded = site_store.seed_from_env_once(conn, settings)
    assert seeded is True
    assert site_store.get_all(conn)["org_name"] == "Creators Club"


def test_seed_never_runs_a_second_time_even_if_env_changes(conn, monkeypatch):
    monkeypatch.setenv("DASH_SITE_ORG_NAME", "First Studio")
    settings1 = Settings.from_env({"DASH_SITE_ORG_NAME": "First Studio"})
    site_store.seed_from_env_once(conn, settings1)

    monkeypatch.setenv("DASH_SITE_ORG_NAME", "Second Studio")
    settings2 = Settings.from_env({"DASH_SITE_ORG_NAME": "Second Studio"})
    seeded_again = site_store.seed_from_env_once(conn, settings2)

    assert seeded_again is False
    assert site_store.get_all(conn)["org_name"] == "First Studio"
    # And the manifest itself now ignores the changed env, because the DB is
    # authoritative once seeded -- the documented rule.
    manifest = site_store.resolved_manifest(conn, settings2)
    assert manifest["org_name"] == "First Studio"


def test_seed_does_not_run_if_the_table_already_has_rows(conn, monkeypatch):
    site_store.set_many(conn, {"org_name": "Manual"}, updated_by="admin")
    conn.commit()
    monkeypatch.setenv("DASH_SITE_ORG_NAME", "From Env")
    settings = Settings.from_env({"DASH_SITE_ORG_NAME": "From Env"})
    seeded = site_store.seed_from_env_once(conn, settings)
    assert seeded is False
    assert site_store.get_all(conn)["org_name"] == "Manual"


# --------------------------------------------------------------- export/import

def test_export_toml_round_trips_through_import(conn):
    settings = Settings()
    site_store.set_many(conn, {
        "org_name": "Studio", "tree_name": "Studio_Tree",
        "sftp_port": "2222", "features.youtube_download": "1",
        "template_folders": "AE,B-roll", "indexer_model_tier": "best",
        "brand_logo": "cc_mark_white.png",
    }, updated_by="admin")
    conn.commit()

    text = site_store.export_toml(conn, settings)
    assert "[site]" in text
    assert 'org_name = "Studio"' in text
    assert 'brand_logo = "cc_mark_white.png"' in text
    assert "[features]" in text
    assert "youtube_download = true" in text
    assert "[indexer]" in text
    assert 'model_tier = "best"' in text

    parsed = site_store.import_toml(text)
    assert parsed["org_name"] == "Studio"
    assert parsed["sftp_port"] == "2222"
    assert parsed["features.youtube_download"] == "1"
    assert parsed["template_folders"] == "AE,B-roll"
    assert parsed["indexer_model_tier"] == "best"
    assert parsed["brand_logo"] == "cc_mark_white.png"


def test_import_ignores_unrecognised_sections():
    text = """
[apps]
root = "/mnt/tank/apps/ccsync-dashboard"

[site]
org_name = "Studio"
"""
    parsed = site_store.import_toml(text)
    assert parsed == {"org_name": "Studio"}


def test_import_rejects_unparseable_toml():
    with pytest.raises(site_store.SiteValidationError):
        site_store.import_toml("not = [valid toml")


def test_export_never_includes_a_secret(conn):
    """Export shares the same manifest as GET /api/v1/site -- nothing this
    store owns is a secret, but pin it anyway since this text is meant to be
    pasted/downloaded."""
    settings = Settings(report_token="super-secret", session_secret="also-secret")
    text = site_store.export_toml(conn, settings)
    assert "super-secret" not in text
    assert "also-secret" not in text
