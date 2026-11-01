"""GL-34 / CR-374 (2026-10-07): the wizard's Done page says where to send a
problem, from the manifest this run fetched."""
from __future__ import annotations

import steps


def test_the_line_names_the_manifests_contact():
    assert steps.support_line({"support_contact": "help@example.test"}) == \
        "Problems? Contact help@example.test"


def test_the_line_falls_back_to_the_vendor_default():
    from ccsync_companion import site as site_mod
    assert steps.support_line({}).endswith(site_mod.DEFAULT_SUPPORT_CONTACT)
