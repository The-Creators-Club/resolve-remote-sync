"""Config file tests: first-run creation, TOML parsing, malformed fallback,
and DEFAULTS/DEFAULT_TOML_TEXT key parity."""

from __future__ import annotations

import logging
import re

import pytest

from ccsync_companion import config as config_mod


def test_ensure_config_exists_writes_default_toml(tmp_path):
    path = tmp_path / "config.toml"
    assert not path.exists()
    config_mod.ensure_config_exists(path)
    assert path.exists()
    assert path.read_text(encoding="utf-8") == config_mod.DEFAULT_TOML_TEXT


def test_ensure_config_exists_does_not_overwrite(tmp_path):
    path = tmp_path / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('editor_name = "custom"\n', encoding="utf-8")
    config_mod.ensure_config_exists(path)
    assert path.read_text(encoding="utf-8") == 'editor_name = "custom"\n'


def test_load_config_creates_defaults_on_first_run(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    cfg = config_mod.load_config(path)
    assert path.exists()
    for key, value in config_mod.DEFAULTS.items():
        assert cfg[key] == value


def test_load_config_merges_user_overrides(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'editor_name = "alex"\n'
        'local_root = "C:\\\\Creators_Club"\n'
        "poll_interval = 5\n",
        encoding="utf-8",
    )
    cfg = config_mod.load_config(path)
    assert cfg["editor_name"] == "alex"
    assert cfg["local_root"] == "C:\\Creators_Club"
    assert cfg["poll_interval"] == 5
    # Untouched keys still fall back to DEFAULTS.
    assert cfg["remote"] == config_mod.DEFAULTS["remote"]


def test_load_config_malformed_toml_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("this is not valid TOML [[[", encoding="utf-8")
    cfg = config_mod.load_config(path)
    for key, value in config_mod.DEFAULTS.items():
        assert cfg[key] == value


def test_load_config_malformed_toml_logs_loudly_and_marks_load_error(tmp_path, caplog):
    # S-2: a malformed config used to be silently indistinguishable from a
    # never-configured install -- no log line at all. Now it must log an
    # ERROR and leave a trail validate_config() can surface.
    path = tmp_path / "config.toml"
    path.write_text("this is not valid TOML [[[", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="ccsync.config"):
        cfg = config_mod.load_config(path)
    assert cfg["_config_load_error"]
    assert any(r.levelno == logging.ERROR for r in caplog.records)

    errors, _warnings = config_mod.validate_config(cfg)
    assert any("config.toml failed to load" in e for e in errors)


def test_load_config_tolerates_utf8_bom(tmp_path):
    # S-2: PowerShell's Set-Content prepends a UTF-8 BOM even when
    # overwriting a BOM-less file (windows_bootstrap.ps1 / windows_upgrade
    # .ps1) -- a config written that way must still parse cleanly, the same
    # way identity.py's load_identity() already tolerates a BOM.
    path = tmp_path / "config.toml"
    text = 'editor_name = "alex"\nlocal_root = "C:\\\\Creators_Club"\n'
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    cfg = config_mod.load_config(path)
    assert cfg["editor_name"] == "alex"
    assert cfg["local_root"] == "C:\\Creators_Club"
    assert cfg["_config_load_error"] is None


def test_load_config_clean_file_has_no_load_error(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config_mod.load_config(path)
    assert cfg["_config_load_error"] is None
    errors, _warnings = config_mod.validate_config(cfg)
    assert not any("config.toml failed to load" in e for e in errors)


def test_load_config_coerces_bad_list_fields(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('projects = "not-a-list"\n', encoding="utf-8")
    cfg = config_mod.load_config(path)
    assert cfg["projects"] == []


def test_resolved_log_path_expands_user(monkeypatch, tmp_path):
    cfg = {"log_path": "~/.ccsync/companion.log"}
    result = config_mod.resolved_log_path(cfg)
    assert not str(result).startswith("~")


def test_resolved_local_root(tmp_path):
    cfg = {"local_root": str(tmp_path)}
    assert config_mod.resolved_local_root(cfg) == tmp_path


def test_default_toml_text_documents_every_default_key():
    # Every key in DEFAULTS should appear as a `key =` assignment somewhere
    # in DEFAULT_TOML_TEXT, so the shipped template never drifts from the
    # code's actual fallback values -- EXCEPT keys a MODE_PROFILES entry
    # controls (currently just sync_enabled): those are deliberately left
    # commented out in the template (see S-7) so a first-run file doesn't
    # pin an explicit value that would make mode="base"'s profile dead.
    profile_controlled = {key for profile in config_mod.MODE_PROFILES.values() for key in profile}
    for key in config_mod.DEFAULTS:
        if key in profile_controlled:
            pattern = rf"^#\s*{re.escape(key)} = "
        else:
            pattern = rf"^{re.escape(key)} = "
        assert re.search(pattern, config_mod.DEFAULT_TOML_TEXT, re.MULTILINE), (
            f"DEFAULT_TOML_TEXT is missing an assignment for '{key}'"
        )


def _good_cfg(tmp_path, **overrides):
    cfg = {
        "editor_name": "ruskin",
        "local_root": str(tmp_path),
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/TheCreatorsPool/Creators_Club",
        "projects": ["Projects/2026/Creator Profiles/Season 1"],
        "active_project": "Projects/2026/Creator Profiles/Season 1",
    }
    cfg.update(overrides)
    return cfg


def test_validate_config_accepts_a_fully_configured_install(tmp_path):
    errors, warnings = config_mod.validate_config(_good_cfg(tmp_path))
    assert errors == []
    assert warnings == []


def test_validate_config_flags_blank_remote_root(tmp_path):
    errors, _ = config_mod.validate_config(_good_cfg(tmp_path, remote_root=""))
    assert any("remote_root is blank" in p for p in errors)


def test_validate_config_flags_relative_remote_root(tmp_path):
    # The bug this exists for: "Creators_Club" looks configured but resolves
    # to ~/Creators_Club on the NAS, so nothing lands in the shared tree.
    errors, _ = config_mod.validate_config(_good_cfg(tmp_path, remote_root="Creators_Club"))
    assert any("not absolute" in p for p in errors)


def test_validate_config_flags_missing_local_root(tmp_path):
    errors, _ = config_mod.validate_config(
        _good_cfg(tmp_path, local_root=str(tmp_path / "does-not-exist"))
    )
    assert any("local_root does not exist" in p for p in errors)


def test_validate_config_flags_a_default_first_run_config(tmp_path):
    # Whatever the companion writes on first run must NOT look valid â€” that
    # silence is exactly what made a broken install hard to diagnose.
    path = tmp_path / "config.toml"
    cfg = config_mod.load_config(path)
    errors, _ = config_mod.validate_config(cfg)
    assert errors, "a blank first-run config must report errors"


def test_blank_projects_is_not_an_error(tmp_path):
    # Lanes A and B sync local_root <-> remote_root as whole trees, so every
    # year/series/project replicates regardless of what `projects` says.
    # Treating these as blockers would flag a working install as broken.
    errors, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, projects=[], active_project="")
    )
    assert errors == []
    assert any("active_project is blank" in w for w in warnings)


def test_validate_config_flags_mismatched_folder_id_pairing(tmp_path):
    _, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, projects=["a", "b"], syncthing_folder_ids=["only-one"])
    )
    assert any("positional pairs" in w for w in warnings)


def test_project_paths_with_spaces_are_accepted(tmp_path):
    # Real series/project names have spaces ("Creator Profiles", "Season 1").
    errors, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, active_project="Projects/2026/Creator Profiles/Season 1")
    )
    assert errors == []
    assert warnings == []


def test_validate_config_warns_on_non_http_dashboard_url(tmp_path):
    _, warnings = config_mod.validate_config(_good_cfg(tmp_path, dashboard_url="dash.example.com"))
    assert any("http:// or https://" in w for w in warnings)


def test_validate_config_accepts_https_dashboard_url(tmp_path):
    _, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, dashboard_url="https://dash.example.com", dashboard_token="tok")
    )
    assert not any("http:// or https://" in w for w in warnings)


def test_validate_config_warns_on_blank_dashboard_token(tmp_path):
    _, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, dashboard_url="https://dash.example.com", dashboard_token="")
    )
    assert any("dashboard_token is blank" in w for w in warnings)


def test_validate_config_no_dashboard_warnings_when_url_blank(tmp_path):
    _, warnings = config_mod.validate_config(_good_cfg(tmp_path, dashboard_url=""))
    assert not any("dashboard" in w for w in warnings)


def test_validate_config_flags_non_positive_dashboard_report_interval(tmp_path):
    errors, _ = config_mod.validate_config(_good_cfg(tmp_path, dashboard_report_interval=0))
    assert any("dashboard_report_interval must be a positive number" in e for e in errors)


def test_validate_config_flags_non_numeric_dashboard_report_interval(tmp_path):
    errors, _ = config_mod.validate_config(_good_cfg(tmp_path, dashboard_report_interval="soon"))
    assert any("dashboard_report_interval must be a positive number" in e for e in errors)


def test_default_remote_matches_installer_remote_name():
    # Both bootstrap scripts write an rclone stanza named creators_club_sftp;
    # if the default here drifts, lane A/B point at a nonexistent remote.
    from pathlib import Path

    installer_dir = Path(__file__).resolve().parents[2] / "installer"
    ps1 = (installer_dir / "windows_bootstrap.ps1").read_text(encoding="utf-8")
    sh = (installer_dir / "macos_bootstrap.sh").read_text(encoding="utf-8")
    assert '$RemoteName = "creators_club_sftp"' in ps1
    assert 'REMOTE_NAME="creators_club_sftp"' in sh
    assert config_mod.DEFAULTS["remote"] == "creators_club_sftp"


def test_config_example_toml_matches_default_keys():
    # config.example.toml (shipped alongside pyproject.toml) should also
    # document every key â€” catches the file drifting from config.py.
    example_path = config_mod.CONFIG_DIR.parent  # not used; see below
    from pathlib import Path

    companion_root = Path(__file__).resolve().parent.parent
    example_text = (companion_root / "config.example.toml").read_text(encoding="utf-8")
    for key in config_mod.DEFAULTS:
        pattern = rf"^{re.escape(key)} = "
        assert re.search(pattern, example_text, re.MULTILINE), (
            f"config.example.toml is missing an assignment for '{key}'"
        )


def test_mode_base_profile_disables_sync_but_keeps_popup(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('mode = "base"\n', encoding="utf-8")
    cfg = config_mod.load_config(p)
    # popup stays ON: base editors can still cut in media from outside the
    # tree, and those clips need fixing into the project directory.
    assert cfg["sync_enabled"] is False and cfg["popup_enabled"] is True


def test_mode_base_explicit_keys_win(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('mode = "base"\npopup_enabled = false\nsync_enabled = true\n', encoding="utf-8")
    cfg = config_mod.load_config(p)
    assert cfg["sync_enabled"] is True and cfg["popup_enabled"] is False


def test_mode_editor_defaults_unchanged(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('mode = "editor"\n', encoding="utf-8")
    cfg = config_mod.load_config(p)
    assert cfg["sync_enabled"] is True and cfg["popup_enabled"] is True


def test_unknown_mode_warns_and_acts_as_editor(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('mode = "banana"\n', encoding="utf-8")
    cfg = config_mod.load_config(p)
    assert cfg["sync_enabled"] is True
    _, warnings = config_mod.validate_config(cfg)
    assert any("unknown mode" in w for w in warnings)


def test_mode_base_profile_is_not_dead_from_a_real_first_run_template(tmp_path):
    # S-7 regression: DEFAULT_TOML_TEXT used to contain a literal
    # `sync_enabled = true`, which -- because load_config only applies a
    # MODE_PROFILES entry when the key is ABSENT from the file -- made
    # mode="base" a no-op for any config seeded from the companion's own
    # template (as opposed to the bare one-line files the older tests here
    # use). Write a config that mirrors the real first-run template, only
    # with mode flipped to "base", and confirm the profile still applies.
    p = tmp_path / "config.toml"
    text = config_mod.DEFAULT_TOML_TEXT.replace('mode = "editor"', 'mode = "base"')
    assert 'mode = "base"' in text  # sanity: the replace actually matched
    p.write_text(text, encoding="utf-8")
    cfg = config_mod.load_config(p)
    assert cfg["sync_enabled"] is False


# -- dashboard_report_interval_active / manifest_refresh_interval /
# media_tree_refresh_interval -----------------------------------------------


def test_new_reporting_keys_have_expected_defaults():
    assert config_mod.DEFAULTS["dashboard_report_interval_active"] == 5
    assert config_mod.DEFAULTS["manifest_refresh_interval"] == 300
    assert config_mod.DEFAULTS["media_tree_refresh_interval"] == 120


def test_load_config_creates_defaults_includes_new_reporting_keys(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config_mod.load_config(path)
    assert cfg["dashboard_report_interval_active"] == 5
    assert cfg["manifest_refresh_interval"] == 300
    assert cfg["media_tree_refresh_interval"] == 120


@pytest.mark.parametrize(
    "key", ["dashboard_report_interval_active", "manifest_refresh_interval", "media_tree_refresh_interval"]
)
def test_validate_config_flags_non_positive_new_interval_keys(tmp_path, key):
    errors, _ = config_mod.validate_config(_good_cfg(tmp_path, **{key: 0}))
    assert any(f"{key} must be a positive number" in e for e in errors)


@pytest.mark.parametrize(
    "key", ["dashboard_report_interval_active", "manifest_refresh_interval", "media_tree_refresh_interval"]
)
def test_validate_config_flags_non_numeric_new_interval_keys(tmp_path, key):
    errors, _ = config_mod.validate_config(_good_cfg(tmp_path, **{key: "soon"}))
    assert any(f"{key} must be a positive number" in e for e in errors)


# -- popup_snooze_seconds -----------------------------------------------


def test_popup_snooze_seconds_has_expected_default():
    assert config_mod.DEFAULTS["popup_snooze_seconds"] == 300


def test_load_config_creates_defaults_includes_popup_snooze_seconds(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config_mod.load_config(path)
    assert cfg["popup_snooze_seconds"] == 300


def test_validate_config_flags_non_positive_popup_snooze_seconds(tmp_path):
    errors, _ = config_mod.validate_config(_good_cfg(tmp_path, popup_snooze_seconds=0))
    assert any("popup_snooze_seconds must be a positive number" in e for e in errors)


def test_validate_config_flags_non_numeric_popup_snooze_seconds(tmp_path):
    errors, _ = config_mod.validate_config(_good_cfg(tmp_path, popup_snooze_seconds="soon"))
    assert any("popup_snooze_seconds must be a positive number" in e for e in errors)


def test_version_matches_pyproject():
    """config.VERSION is the single source of truth, but pyproject.toml
    duplicates it (packaging requires a literal) -- publishing refuses on
    drift, and this test catches it at development time."""
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["project"]["version"] == config_mod.VERSION


def test_ignored_resolve_projects_default_and_coercion(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('editor_name = "x"\n', encoding="utf-8")
    cfg = config_mod.load_config(path)
    assert "Untitled Project" in cfg["ignored_resolve_projects"]
    assert "New Doc" in cfg["ignored_resolve_projects"]

    path.write_text('ignored_resolve_projects = "oops-not-a-list"\n', encoding="utf-8")
    cfg = config_mod.load_config(path)
    assert isinstance(cfg["ignored_resolve_projects"], list)
