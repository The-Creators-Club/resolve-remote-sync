"""GL-34 / CR-374 (2026-10-07): the support contact in the companion."""
from __future__ import annotations

from ccsync_companion import site as site_mod

GOOD = {"schema": 1, "org_name": "Example Post", "support_contact": "help@example.test"}


def test_normalise_keeps_the_contact():
    assert site_mod.normalise(dict(GOOD))["support_contact"] == "help@example.test"


def test_an_older_dashboard_without_the_key_gets_the_vendor_default():
    data = site_mod.normalise({"schema": 1, "org_name": "Example Post"})
    assert data["support_contact"] == ""
    assert site_mod.support_contact(data) == site_mod.DEFAULT_SUPPORT_CONTACT


def test_support_contact_is_never_blank():
    assert site_mod.support_contact({}) == site_mod.DEFAULT_SUPPORT_CONTACT
    assert site_mod.support_contact({"support_contact": "  "}) == site_mod.DEFAULT_SUPPORT_CONTACT
    assert site_mod.support_contact(site_mod.normalise(dict(GOOD))) == "help@example.test"


def test_the_default_matches_the_dashboards():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "dashboard" / "src"
           / "ccsync_dashboard" / "site_store.py").read_text(encoding="utf-8")
    assert f'DEFAULT_SUPPORT_CONTACT = "{site_mod.DEFAULT_SUPPORT_CONTACT}"' in src


def test_the_help_section_names_the_contact():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src" / "ccsync_companion"
           / "settings_window.py").read_text(encoding="utf-8")
    assert "site_mod.support_contact()" in src
