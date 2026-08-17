"""secrets_boot.ensure_secrets -- first-boot secrets bootstrap
(ZERO_TOUCH_PLAN.md WP D, 2026-08-17)."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from ccsync_dashboard import secrets_boot


def test_all_env_set_is_a_no_op(tmp_path):
    """Today's deployments (every DASH_SITE_* secret already in compose env)
    must see no behaviour change: nothing generated, nothing rotated, none
    of the five per-secret files created."""
    env = {
        "DASH_DB_PATH": str(tmp_path / "dashboard.db"),
        "DASH_SESSION_SECRET": "session-secret-value",
        "DASH_REPORT_TOKEN": "report-token-value",
        "BROLL_INGEST_TOKEN": "broll-ingest-token-value",
        "SYNCTHING_API_KEY": "syncthing-api-key-value",
        "CCSYNC_INTERNAL_TOKEN": "internal-token-value",
    }
    before = dict(env)
    provenance = secrets_boot.ensure_secrets(env)

    assert env == before, "ensure_secrets must not mutate an already-fully-configured env"
    assert provenance == {name: "env" for name in secrets_boot.SECRET_ENV_VARS}
    for name in secrets_boot.SECRET_ENV_VARS:
        assert not (tmp_path / "secrets" / name.lower()).exists()


def test_missing_secrets_are_generated_and_persisted(tmp_path):
    env = {"DASH_DB_PATH": str(tmp_path / "dashboard.db")}
    provenance = secrets_boot.ensure_secrets(env)

    assert provenance == {name: "generated" for name in secrets_boot.SECRET_ENV_VARS}
    for name in secrets_boot.SECRET_ENV_VARS:
        assert env[name]
        path = tmp_path / "secrets" / name.lower()
        assert path.is_file()
        assert path.read_text(encoding="utf-8").strip() == env[name]


def test_a_second_boot_loads_the_same_secrets_from_file(tmp_path):
    env1 = {"DASH_DB_PATH": str(tmp_path / "dashboard.db")}
    secrets_boot.ensure_secrets(env1)

    env2 = {"DASH_DB_PATH": str(tmp_path / "dashboard.db")}
    provenance2 = secrets_boot.ensure_secrets(env2)

    assert provenance2 == {name: "file" for name in secrets_boot.SECRET_ENV_VARS}
    for name in secrets_boot.SECRET_ENV_VARS:
        assert env1[name] == env2[name]


def test_env_always_wins_over_a_file_on_disk(tmp_path):
    """Rotation by setting the env var stays possible -- a stale file must
    never override a value the operator just set."""
    env1 = {"DASH_DB_PATH": str(tmp_path / "dashboard.db")}
    secrets_boot.ensure_secrets(env1)   # writes files

    env2 = {"DASH_DB_PATH": str(tmp_path / "dashboard.db"),
            "DASH_SESSION_SECRET": "an-operator-rotated-this-value"}
    secrets_boot.ensure_secrets(env2)

    assert env2["DASH_SESSION_SECRET"] == "an-operator-rotated-this-value"


def test_each_generated_secret_is_unique(tmp_path):
    env = {"DASH_DB_PATH": str(tmp_path / "dashboard.db")}
    secrets_boot.ensure_secrets(env)
    values = [env[name] for name in secrets_boot.SECRET_ENV_VARS]
    assert len(set(values)) == len(values)


def test_never_logs_a_secret_value(tmp_path, caplog):
    import logging

    caplog.set_level(logging.DEBUG, logger="ccsync.dashboard.secrets_boot")
    env = {"DASH_DB_PATH": str(tmp_path / "dashboard.db")}
    secrets_boot.ensure_secrets(env)
    for name in secrets_boot.SECRET_ENV_VARS:
        assert env[name] not in caplog.text


def test_sidecar_env_files_reflect_the_current_values(tmp_path):
    env = {
        "DASH_DB_PATH": str(tmp_path / "dashboard.db"),
        "SYNCTHING_API_KEY": "syncthing-key-abc",
        "CCSYNC_INTERNAL_TOKEN": "internal-token-xyz",
        "APP_UID": "3000",
        "APP_GID": "3001",
    }
    secrets_boot.ensure_secrets(env)

    syncthing_env = (tmp_path / "secrets" / "syncthing.env").read_text(encoding="utf-8")
    assert "STGUIAPIKEY=syncthing-key-abc" in syncthing_env

    sftp_env = (tmp_path / "secrets" / "sftp.env").read_text(encoding="utf-8")
    assert "CCSYNC_INTERNAL_TOKEN=internal-token-xyz" in sftp_env
    assert "APP_UID=3000" in sftp_env
    assert "APP_GID=3001" in sftp_env


def test_sidecar_env_files_are_rewritten_every_call_to_track_rotation(tmp_path):
    env1 = {"DASH_DB_PATH": str(tmp_path / "dashboard.db"), "SYNCTHING_API_KEY": "key-one"}
    secrets_boot.ensure_secrets(env1)
    env2 = {"DASH_DB_PATH": str(tmp_path / "dashboard.db"), "SYNCTHING_API_KEY": "key-two"}
    secrets_boot.ensure_secrets(env2)

    syncthing_env = (tmp_path / "secrets" / "syncthing.env").read_text(encoding="utf-8")
    assert "STGUIAPIKEY=key-two" in syncthing_env
    assert "key-one" not in syncthing_env


def test_data_dir_derives_from_dash_db_path(tmp_path):
    nested = tmp_path / "nested" / "data"
    env = {"DASH_DB_PATH": str(nested / "dashboard.db")}
    secrets_boot.ensure_secrets(env)
    assert (nested / "secrets").is_dir()


def test_default_data_dir_is_slash_data_when_unset():
    assert secrets_boot._secrets_dir({}) == Path("/data") / "secrets"


def test_a_blank_env_value_is_treated_as_unset(tmp_path):
    """An empty string in the environment (e.g. a compose var set to "")
    must not be mistaken for "already configured"."""
    env = {"DASH_DB_PATH": str(tmp_path / "dashboard.db"), "DASH_SESSION_SECRET": "   "}
    provenance = secrets_boot.ensure_secrets(env)
    assert provenance["DASH_SESSION_SECRET"] == "generated"


def test_create_app_bootstraps_only_when_settings_is_none(tmp_path, monkeypatch):
    """Every test in this suite passes an explicit Settings(...) -- confirming
    that path never touches secrets_boot at all is what makes the whole
    suite a no-op by construction, per the module's own docstring."""
    calls = []
    monkeypatch.setattr(secrets_boot, "ensure_secrets", lambda *a, **k: calls.append(1))

    from ccsync_dashboard.app import create_app
    from ccsync_dashboard.settings import Settings

    create_app(Settings(db_path=str(tmp_path / "s.db"), session_secret="x" * 24))
    assert calls == []
