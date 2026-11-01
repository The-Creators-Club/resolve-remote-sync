"""The appliance wizard enforces what the base-rig deploy enforces (CR-368
follow-up, GL-18/GL-19, 2026-10-07): admin separate from the NAS admin, no
TrueNAS password, and a NAS certificate pin the customer can reach."""
from __future__ import annotations

import pytest

from ccsync_dashboard import appliance_config as ac


def _save(tmp_path, task, values, env=None):
    return ac.save(task, values, env=env if env is not None else {}, data_dir=tmp_path)


def test_the_dashboard_admin_cannot_be_the_nas_admin(tmp_path):
    _save(tmp_path, "nas_connect", {"DASH_NAS_KIND": "synology", "DASH_NAS_HOST": "nas.local",
                                    "DASH_NAS_USER": "Admin"})
    with pytest.raises(ac.ConfigError, match="must not be the NAS"):
        _save(tmp_path, "admin", {"DASH_ADMIN_USERS": "alex, admin"})
    assert _save(tmp_path, "admin", {"DASH_ADMIN_USERS": "alex"}) == ["DASH_ADMIN_USERS"]


def test_the_order_of_the_two_forms_does_not_matter(tmp_path):
    _save(tmp_path, "admin", {"DASH_ADMIN_USERS": "admin"})
    with pytest.raises(ac.ConfigError, match="must not be the NAS"):
        _save(tmp_path, "nas_connect", {"DASH_NAS_KIND": "synology", "DASH_NAS_USER": "admin"})


def test_an_env_set_nas_user_counts_too(tmp_path):
    with pytest.raises(ac.ConfigError, match="must not be the NAS"):
        _save(tmp_path, "admin", {"DASH_ADMIN_USERS": "root"}, env={"DASH_NAS_USER": "root"})


def test_a_truenas_site_cannot_store_the_admin_password(tmp_path):
    with pytest.raises(ac.ConfigError, match="API key"):
        _save(tmp_path, "nas_connect", {"DASH_NAS_KIND": "truenas", "DASH_NAS_PW": "hunter2"})
    # Synology legitimately needs the account password
    assert "DASH_NAS_PW" in _save(tmp_path, "nas_connect", {
        "DASH_NAS_KIND": "synology", "DASH_NAS_USER": "svc", "DASH_NAS_PW": "hunter2"})


def test_a_certificate_pin_can_be_entered_and_verification_cannot_be_turned_off(tmp_path):
    pin = "sha256:" + "AB:" * 31 + "AB"
    assert "DASH_NAS_VERIFY_SSL" in _save(tmp_path, "nas_connect", {
        "DASH_NAS_KIND": "synology", "DASH_NAS_VERIFY_SSL": pin})
    assert ac.load({}, tmp_path)["DASH_NAS_VERIFY_SSL"] == "sha256:" + "ab" * 32
    for bad in ("0", "false", "sha256:abc", "no"):
        with pytest.raises(ac.ConfigError):
            _save(tmp_path, "nas_connect", {"DASH_NAS_KIND": "synology",
                                            "DASH_NAS_VERIFY_SSL": bad})


def test_the_stored_pin_reaches_settings_through_the_overlay(tmp_path):
    from ccsync_dashboard.settings import Settings

    _save(tmp_path, "nas_connect", {"DASH_NAS_KIND": "synology",
                                    "DASH_NAS_VERIFY_SSL": "sha256:" + "cd" * 32})
    env: dict[str, str] = {}
    ac.apply_overlay(env, tmp_path)
    assert Settings.from_env(env).nas_verify_ssl == "sha256:" + "cd" * 32
