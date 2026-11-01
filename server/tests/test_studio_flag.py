"""GL-31 / CR-374 (2026-10-07): the deploy projects the studio's CLI opt-in
from site.toml `[studio] allow_cli_providers` and from nothing else."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import install_dashboard_app  # noqa: E402


def _env(**kw):
    return install_dashboard_app.compose_config(
        8480, "/mnt/tank/apps/ccsync-dashboard", "http://x:8384", "k", "t", **kw
    )["services"]["dashboard"]["environment"]


def test_the_vendor_deploy_is_locked():
    assert _env()["DASH_STUDIO_CLI_PROVIDERS"] == "0"


def test_ai_cli_providers_alone_does_not_open_the_lock():
    env = _env(ai_cli_providers="1")
    assert env["DASH_SITE_AI_CLI_PROVIDERS"] == "1"
    assert env["DASH_STUDIO_CLI_PROVIDERS"] == "0"


def test_the_studio_block_opens_it():
    assert _env(studio_cli_providers="1")["DASH_STUDIO_CLI_PROVIDERS"] == "1"


def test_support_contact_reaches_the_env_and_the_compose_dict():
    # blank is a supported state: the dashboard then shows the vendor default
    assert install_dashboard_app.site_env(8480)["DASH_SITE_SUPPORT_CONTACT"] == ""
    assert _env()["DASH_SITE_SUPPORT_CONTACT"] == ""
