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

    # internal.env, the file compose.appliance.yaml's sftp service actually
    # env_files (dash-admin-2, 2026-08-21) -- it used to be written to
    # sftp.env, which nothing has ever read.
    sftp_env = (tmp_path / "secrets" / "internal.env").read_text(encoding="utf-8")
    assert "CCSYNC_INTERNAL_TOKEN=internal-token-xyz" in sftp_env
    assert "APP_UID=3000" in sftp_env
    assert "APP_GID=3001" in sftp_env
    assert not (tmp_path / "secrets" / "sftp.env").exists()


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


# ------------------------------------------- agreeing with the sidecars' files
# dash-admin-2 (2026-08-21): compose.appliance.yaml's secrets-init writes
# syncthing.env / internal.env BEFORE this container starts, because the two
# sidecars read an env_file at their own startup and have no generator. This
# module used to look only at <data>/secrets/<lower env name>, generate a
# SECOND value, and overwrite syncthing.env with it -- so Syncthing 403'd
# until its container was restarted and the sftp sidecar presented a token the
# dashboard had never heard of: every AuthorizedKeysCommand call 401'd and no
# editor could authenticate to lanes A/B at all.


def _seed_like_secrets_init(secrets_dir):
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "syncthing.env").write_text("STGUIAPIKEY=from-secrets-init\n",
                                               encoding="utf-8")
    (secrets_dir / "internal.env").write_text(
        "CCSYNC_INTERNAL_TOKEN=sidecar-token-abc\n", encoding="utf-8")


def test_the_dashboard_adopts_the_tokens_the_sidecars_already_hold(tmp_path):
    secrets_dir = tmp_path / "secrets"
    _seed_like_secrets_init(secrets_dir)
    env = {"DASH_DB_PATH": str(tmp_path / "dashboard.db")}

    provenance = secrets_boot.ensure_secrets(env)

    assert env["SYNCTHING_API_KEY"] == "from-secrets-init"
    assert env["CCSYNC_INTERNAL_TOKEN"] == "sidecar-token-abc"
    assert provenance["CCSYNC_INTERNAL_TOKEN"] == "sidecar-file"
    # ...and the sidecars' own files are left saying the same thing, so the
    # running sftp sidecar's bearer token still matches what the dashboard
    # expects on /internal/sftp/keys/<user>.
    internal_env = (secrets_dir / "internal.env").read_text(encoding="utf-8")
    assert "CCSYNC_INTERNAL_TOKEN=sidecar-token-abc" in internal_env
    syncthing_env = (secrets_dir / "syncthing.env").read_text(encoding="utf-8")
    assert "STGUIAPIKEY=from-secrets-init" in syncthing_env
    # The canonical file name every other reader uses now exists too.
    assert (secrets_dir / "ccsync_internal_token").read_text(
        encoding="utf-8").strip() == "sidecar-token-abc"


def test_the_environment_still_beats_a_sidecar_file(tmp_path):
    secrets_dir = tmp_path / "secrets"
    _seed_like_secrets_init(secrets_dir)
    env = {"DASH_DB_PATH": str(tmp_path / "dashboard.db"),
           "CCSYNC_INTERNAL_TOKEN": "rotated-by-the-operator"}
    provenance = secrets_boot.ensure_secrets(env)
    assert provenance["CCSYNC_INTERNAL_TOKEN"] == "env"
    assert "CCSYNC_INTERNAL_TOKEN=rotated-by-the-operator" in (
        secrets_dir / "internal.env").read_text(encoding="utf-8")


def test_a_comment_or_an_export_prefix_in_a_sidecar_file_is_tolerated(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "internal.env").write_text(
        "# written by secrets-init\nexport CCSYNC_INTERNAL_TOKEN=\"quoted-token\"\n",
        encoding="utf-8")
    env = {"DASH_DB_PATH": str(tmp_path / "dashboard.db")}
    secrets_boot.ensure_secrets(env)
    assert env["CCSYNC_INTERNAL_TOKEN"] == "quoted-token"
