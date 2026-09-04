"""SYS-20: `[tree] projects_dir` is refused, not silently dropped.

The key is read by `server/common.py` and by nothing else -- not the
manifest, not the companion, not a single lane -- so a customer who sets it
gets a NAS tree under one name and a fleet that syncs nothing, with no
message anywhere. Until `docs/TREE_LAYOUT_PLAN.md` lands, the answer is a
refusal at the two places the value can arrive: a pasted `site.toml` (here)
and the container's environment at boot (`test_settings_projects_dir.py`).
"""
from __future__ import annotations

import pytest

from ccsync_dashboard import site_store
from ccsync_dashboard.settings import projects_dir_is_supported


def test_import_refuses_a_projects_dir_that_is_not_projects():
    with pytest.raises(site_store.SiteValidationError) as excinfo:
        site_store.import_toml('[tree]\nprojects_dir = "Clients"\ntree_name = "Studio"\n')
    assert excinfo.value.key == "projects_dir"
    message = str(excinfo.value)
    assert "only supports a tree whose projects live in `Projects`" in message
    # The refusal has to say what to do about it, like every other one here.
    assert "rename the folder on the server" in message.lower()


def test_import_accepts_the_supported_name_and_keeps_the_rest():
    parsed = site_store.import_toml(
        '[tree]\nprojects_dir = "Projects"\ntree_name = "Studio"\n')
    assert parsed["tree_name"] == "Studio"
    # It is still not a key this store owns: accepted, never stored.
    assert "projects_dir" not in parsed


def test_import_is_unaffected_when_the_key_is_absent():
    parsed = site_store.import_toml('[tree]\ntree_name = "Studio"\n')
    assert parsed == {"tree_name": "Studio"}


@pytest.mark.parametrize("value", ["", "   ", "Projects", "Projects/", "/Projects"])
def test_supported_values(value):
    assert projects_dir_is_supported(value)


@pytest.mark.parametrize("value", ["Clients", "projects", "Projects2", "Work/Projects"])
def test_unsupported_values(value):
    assert not projects_dir_is_supported(value)
