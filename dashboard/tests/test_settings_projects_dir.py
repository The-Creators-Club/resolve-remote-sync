"""SYS-20: a `projects_dir` this build cannot honour refuses at BOOT.

The posture is `check_boot_secrets`': refuse to serve, name the key, say what
to do, and leave exactly one hatch (`DASH_DEV_INSECURE=1`) that is loud in
the log when it is taken. What made this worth a refusal is that the failure
it replaces is silent -- the server scripts build the tree under the
customer's name, every companion looks for `Projects`, and nothing anywhere
says why no project ever syncs.
"""
from __future__ import annotations

import logging

import pytest

from ccsync_dashboard import settings as settings_mod
from ccsync_dashboard.settings import Settings


@pytest.fixture
def strict_env(monkeypatch):
    """The suite sets DASH_DEV_INSECURE=1 at import time (conftest); a boot
    refusal can only be exercised with the hatch shut."""
    monkeypatch.delenv("DASH_DEV_INSECURE", raising=False)
    return monkeypatch


def test_boot_refuses_a_projects_dir_other_than_projects(strict_env):
    strict_env.setenv("DASH_SITE_PROJECTS_DIR", "Clients")
    with pytest.raises(RuntimeError) as excinfo:
        Settings.from_env()
    message = str(excinfo.value)
    assert "only supports a tree whose projects live in `Projects`" in message
    assert "DASH_SITE_PROJECTS_DIR" in message
    assert "Clients" in message


def test_boot_is_silent_for_the_supported_name(strict_env):
    strict_env.setenv("DASH_SITE_PROJECTS_DIR", "Projects")
    assert Settings.from_env() is not None


def test_boot_is_silent_when_the_key_is_unset(strict_env):
    strict_env.delenv("DASH_SITE_PROJECTS_DIR", raising=False)
    assert Settings.from_env() is not None


def test_dev_insecure_bypasses_it_loudly(monkeypatch, caplog):
    monkeypatch.setenv("DASH_DEV_INSECURE", "1")
    monkeypatch.setenv("DASH_SITE_PROJECTS_DIR", "Clients")
    with caplog.at_level(logging.WARNING, logger="ccsync.dashboard.settings"):
        assert Settings.from_env() is not None
    assert any("bypassed a boot refusal" in record.getMessage()
               for record in caplog.records)


def test_the_refusal_names_the_plan_that_would_make_it_real():
    # A refusal that offers no future is a dead end; TREE_LAYOUT_PLAN.md is
    # the work that turns this key into a real one.
    assert "TREE_LAYOUT_PLAN.md" in settings_mod.UNSUPPORTED_PROJECTS_DIR_MESSAGE
