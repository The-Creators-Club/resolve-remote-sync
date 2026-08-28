"""Config file tests: first-run creation, TOML parsing, malformed fallback,
and DEFAULTS/DEFAULT_TOML_TEXT key parity."""

from __future__ import annotations

import logging
import re
from pathlib import Path

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
        'editor_name = "owen"\n'
        'local_root = "C:\\\\Creators_Club"\n'
        "poll_interval = 5\n",
        encoding="utf-8",
    )
    cfg = config_mod.load_config(path)
    assert cfg["editor_name"] == "owen"
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
    text = 'editor_name = "owen"\nlocal_root = "C:\\\\Creators_Club"\n'
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    cfg = config_mod.load_config(path)
    assert cfg["editor_name"] == "owen"
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


@pytest.mark.parametrize("value", [5, True, ["D:/x"], None, {"a": 1}])
def test_resolved_local_root_never_raises_on_a_non_string(value):
    """COMP-CORE-4: `local_root = 5` is valid TOML, and this is the first
    statement of _start_lut_link() -- which start() used to call outside any
    try, so Path(5)'s TypeError killed the windowed exe before the tray icon
    existed. Same guard resolved_log_path has carried since CORE-H2."""
    assert config_mod.resolved_local_root({"local_root": value}) == Path("")


def test_validate_config_flags_a_non_string_local_root(tmp_path):
    errors, _ = config_mod.validate_config(_good_cfg(tmp_path, local_root=5))
    assert any("local_root must be a path string" in p for p in errors)
    # ...and does not ALSO claim it does not exist / is blank: str()-ing the
    # value reported "local_root does not exist: 5", which names the wrong
    # fault (COMP-CORE-4, 2026-08-14).
    assert not any("does not exist" in p or "is blank" in p for p in errors)


def test_default_toml_text_documents_every_default_key():
    # Every key in DEFAULTS should appear as a `key =` assignment somewhere
    # in DEFAULT_TOML_TEXT, so the shipped template never drifts from the
    # code's actual fallback values -- EXCEPT keys a MODE_PROFILES entry
    # controls (currently just sync_enabled): those are deliberately left
    # commented out in the template (see S-7) so a first-run file doesn't
    # pin an explicit value that would make mode="base"'s profile dead.
    profile_controlled = {key for profile in config_mod.MODE_PROFILES.values() for key in profile}
    # Transport tuning (added 0.4.5) is documented COMMENTED OUT for the same
    # class of reason: writing explicit values into every first-run file
    # PINS them, so a later re-tune of a measured-good default would never
    # reach any existing install. They stay discoverable in the template and
    # are filled in for real in config.example.toml.
    commented_out = profile_controlled | {
        "sftp_chunk_size", "sftp_concurrency", "sftp_connections", "checkers",
        "rclone_ignore_checksum", "order_by_up", "order_by_down", "concurrent_lanes",
        "structure_clone_every_n_passes", "lane_c_pause_scheme",
        "lane_c_max_folder_concurrency", "orphan_scan_every_n_passes",
        "express_upload_enabled", "express_debounce_seconds", "express_max_batch",
        "server_p_unc",
        # Power-guard liveness thresholds: same class again. They exist so a
        # machine can be tuned in the field without a rebuild, but the shipped
        # numbers are measured defaults -- pinning them in every first-run file
        # is how a later re-tune reaches nobody.
        "keep_awake_stale_seconds", "keep_awake_max_hold_seconds",
        # The sync-drive reminder cadence (CR-92): same class, a field knob
        # whose shipped value must stay re-tunable.
        "drive_reminder_minutes",
        # The proxy generator's tuning, same class again -- plus
        # proxy_gen_enabled, which CANNOT be written live at all: its default
        # is None ("derive it from lane_b_enabled"), TOML has no null, and an
        # explicit value in every first-run file would kill the derivation the
        # same way an explicit sync_enabled kills mode="base".
        "proxy_gen_enabled", "proxy_gen_max_height", "proxy_gen_bitrate",
        "proxy_gen_max_failures", "proxy_notify_cooldown_seconds",
        "proxy_gen_skip_while_resolve_running",
        # Same class again, and bpg_enabled for the same reason as
        # proxy_gen_enabled specifically: its default is None ("derive it"),
        # TOML has no null, and an explicit value in every first-run file
        # would kill the derivation.
        "bpg_enabled", "bpg_path",
        # An override for a path that is otherwise %APPDATA%-derived -- writing
        # one in pins a location that only ever needs pinning by hand.
        "bpg_settings_path",
        # The YouTube importer's tuning, same class as the generator's: the
        # feature switch and the two windows an editor might actually want to
        # change are written live, the batch/failure knobs are documented
        # commented out so a later re-tune still reaches existing installs.
        "youtube_import_batch_limit", "youtube_import_max_failures",
        # The lane B circuit breaker's thresholds and the .ccsync-trash
        # retention window (COMMERCIAL_READINESS.md item 9, 2026-08-17).
        # Same class as the transport tuning above: the shipped numbers are
        # the measured-safe defaults, and pinning them in every first-run
        # file is how a later re-tune reaches nobody.
        "lane_b_max_deletes_per_pass", "lane_b_max_delete_fraction",
        "lane_b_remote_shrink_fraction", "lane_b_min_free_bytes",
        "trash_max_age_days", "trash_max_bytes", "trash_prune_interval_seconds",
        # The proxy generator's free-space floor and stability window, and the
        # two rehearsal switches (COMMERCIAL_READINESS.md item 9, 2026-08-17).
        # Same class: measured-safe defaults that a later re-tune must be able
        # to reach, and two switches whose ON state is a deliberate one-off.
        "proxy_gen_free_space_floor_gb", "proxy_gen_free_space_floor_pct",
        "proxy_gen_stability_seconds", "proxy_dry_run", "fixer_dry_run",
        # B-roll ingest (BROLL_INGEST_PLAN.md, 2026-08-18). Same class again:
        # every one of these is a measured default a later re-tune has to be
        # able to reach, and broll_ingest_staging_dir is an override only the
        # base rig sets.
        "broll_ingest_enabled", "broll_ingest_idle_seconds",
        "broll_ingest_skip_while_resolve", "broll_ingest_free_space_floor_gb",
        "broll_ingest_max_concurrent_ffmpeg", "broll_ingest_staging_dir",
        # The Syncthing supervisor's kill switch (SYNC-17, 2026-08-18). ON is
        # the shipped behaviour and the only one anybody should want; writing
        # `supervise_syncthing = true` into every first-run file would make
        # the day we need to change that default a fleet-wide edit.
        "supervise_syncthing",
        # The project-library walk (docs/LIBRARY_WALK_PLAN.md, 2026-08-26) --
        # same class: the walk falls back to the API on its own, so pinning
        # `library_walk = true` in every first-run file only makes a later
        # default change unreachable, and the library_db_* keys are overrides
        # for what Resolve normally tells us (plus one secret).
        "library_walk", "library_db_host", "library_db_port",
        "library_db_name", "library_db_user", "library_db_password",
    }
    for key in config_mod.DEFAULTS:
        if key in commented_out:
            pattern = rf"^#\s*{re.escape(key)} = "
        else:
            pattern = rf"^{re.escape(key)} = "
        assert re.search(pattern, config_mod.DEFAULT_TOML_TEXT, re.MULTILINE), (
            f"DEFAULT_TOML_TEXT is missing an assignment for '{key}'"
        )


# config.example.toml is the third way a config.toml comes into existence
# (its own header says so: copy it and edit it), and nothing checked it
# against DEFAULTS at all -- the DEFAULT_TOML_TEXT check above only compares
# the code to the file the COMPANION writes on first run. A key that exists
# in neither form here is a documented feature an editor cannot discover.
#
# These three are documented COMMENTED OUT on purpose:
#   * sync_enabled / lane_b_enabled -- an explicit key in the file always
#     beats MODE_PROFILES, so a copied-and-edited example carrying
#     `sync_enabled = true` makes mode = "base" dead, and the base rig's
#     local_root IS the NAS share (AUDIT_2 CORE-M5 / the S-7 twin).
#   * server_p_unc -- an OVERRIDE for a value that is otherwise derived, so
#     writing one in pins a host that only ever needs pinning by hand.
#   * keep_awake_stale_seconds / keep_awake_max_hold_seconds -- tunable in
#     the field (editors run a prebuilt exe), but the shipped values are the
#     measured defaults, and an explicit copy in every config.toml is how a
#     later re-tune reaches nobody.
#   * proxy_gen_enabled -- tri-state: its default is None, meaning "derive it
#     from lane_b_enabled" (see config.proxy_generation_enabled), and TOML has
#     no way to write None. A copied-in explicit value kills the derivation,
#     which on an editor means generating proxies lane B then sweeps into
#     .ccsync-trash. The generator's other knobs are commented for the same
#     reason as the keep_awake pair above.
EXAMPLE_COMMENTED_OUT = {
    "sync_enabled", "lane_b_enabled", "server_p_unc",
    "keep_awake_stale_seconds", "keep_awake_max_hold_seconds",
    "drive_reminder_minutes",
    "proxy_gen_enabled", "proxy_gen_max_height", "proxy_gen_bitrate",
    "proxy_gen_max_failures", "proxy_notify_cooldown_seconds",
    "proxy_gen_skip_while_resolve_running",
    # The BPG hand-off, same reasoning: bpg_enabled derives from
    # proxy_generation_enabled AND whether Resolve is installed, and bpg_path
    # is empty by default because the answer is "look where Resolve installs".
    # bpg_settings_path is an override for a %APPDATA%-derived path, so it is
    # documented the way server_p_unc is: there to be found, not to be copied.
    "bpg_enabled", "bpg_path", "bpg_settings_path",
    # The YouTube importer's batch/failure knobs -- tunable in the field,
    # shipped values are the measured defaults (see DEFAULT_TOML_TEXT above).
    "youtube_import_batch_limit", "youtube_import_max_failures",
    # The lane B circuit breaker + .ccsync-trash retention, same class again
    # (COMMERCIAL_READINESS.md item 9, 2026-08-17).
    "lane_b_max_deletes_per_pass", "lane_b_max_delete_fraction",
    "lane_b_remote_shrink_fraction", "lane_b_min_free_bytes",
    "trash_max_age_days", "trash_max_bytes", "trash_prune_interval_seconds",
    # The proxy generator's free-space floor and stability window, and the two
    # rehearsal switches (COMMERCIAL_READINESS.md item 9, 2026-08-17).
    "proxy_gen_free_space_floor_gb", "proxy_gen_free_space_floor_pct",
    "proxy_gen_stability_seconds", "proxy_dry_run", "fixer_dry_run",
    # B-roll ingest (BROLL_INGEST_PLAN.md, 2026-08-18), same class as the
    # proxy generator's knobs above: the shipped values are the measured
    # defaults, and broll_ingest_staging_dir is an override exactly like
    # server_p_unc -- there to be FOUND (the base rig needs it) and not to be
    # copied onto every editor's machine.
    "broll_ingest_enabled", "broll_ingest_idle_seconds",
    "broll_ingest_skip_while_resolve", "broll_ingest_free_space_floor_gb",
    "broll_ingest_max_concurrent_ffmpeg", "broll_ingest_staging_dir",
    # The Syncthing supervisor's kill switch, same class (SYNC-17).
    "supervise_syncthing",
    # The project-library walk (docs/LIBRARY_WALK_PLAN.md, 2026-08-26).
    # library_walk is ON and self-healing -- every failure falls back to the
    # API walk by itself -- so an explicit `library_walk = true` copied into
    # every config.toml buys nothing and is how a later default change
    # reaches nobody. The five library_db_* keys are overrides for a value
    # Resolve normally supplies, documented exactly the way server_p_unc is;
    # library_db_password additionally must not be pre-seeded into a file
    # anyone might copy about.
    "library_walk", "library_db_host", "library_db_port", "library_db_name",
    "library_db_user", "library_db_password",
}

# Read straight off the loaded config with .get() and DELIBERATELY absent from
# DEFAULTS (loopback_guard.py's module docstring): they are escape hatches, not
# settings anyone should be setting routinely, and a DEFAULTS entry would make
# ensure_config write them into every first-run file. They are still documented
# -- commented out -- because broll_server names loopback_extra_origins in the
# refusal an editor actually reads, and a key that only the source mentions is
# not a setting (2026-08-17, COMMERCIAL_READINESS.md item 5).
EXAMPLE_ESCAPE_HATCHES = {"loopback_extra_origins", "loopback_dev_origins"}

# Documented in config.example.toml, read straight off cfg by a subsystem that
# carries its own default, and NOT in config.py's DEFAULTS. Unlike the escape
# hatches above these are ordinary settings -- they are simply owned by the
# module that reads them (sequencer.py's coerce_count call and
# DEFAULT_LANE_C_SETTLE_SECONDS), so DEFAULTS would be a second place for the
# number to drift. Documenting them is still required: a key that only the
# source mentions is not a setting (CR-62, CR-67 item 12, 2026-08-21).
EXAMPLE_MODULE_OWNED_KEYS = {"lane_c_settle_seconds"}


def _example_toml_text() -> str:
    from pathlib import Path

    path = Path(config_mod.__file__).resolve().parents[2] / "config.example.toml"
    return path.read_text(encoding="utf-8")


def test_config_example_documents_every_default_key():
    text = _example_toml_text()
    missing = []
    for key in config_mod.DEFAULTS:
        if key in EXAMPLE_COMMENTED_OUT:
            pattern = rf"^#\s*{re.escape(key)} = "
        else:
            pattern = rf"^{re.escape(key)} = "
        if not re.search(pattern, text, re.MULTILINE):
            missing.append(key)
    assert missing == [], f"config.example.toml is missing: {missing}"


def test_config_example_invents_no_keys_the_code_does_not_read():
    """The other drift direction: a typo'd or retired key in the example is
    a setting an editor can write, restart for, and watch do nothing."""
    text = _example_toml_text()
    assignments = set(re.findall(r"^#?\s*([a-z_][a-z0-9_]*) = ", text, re.MULTILINE))
    unknown = sorted(assignments - set(config_mod.DEFAULTS) - EXAMPLE_ESCAPE_HATCHES
                     - EXAMPLE_MODULE_OWNED_KEYS)
    assert unknown == [], f"config.example.toml documents keys nothing reads: {unknown}"


def test_the_module_owned_keys_are_documented_and_actually_read():
    """The deal for a key whose default lives in its own module: the example
    file documents it (CR-62/CR-67 item 12 -- lane_c_settle_seconds shipped
    undocumented, so the one knob that stops a project's turn parking the
    sequencer for ten minutes was invisible to the operator), and something
    in the tree really reads it."""
    from pathlib import Path

    text = _example_toml_text()
    src = Path(config_mod.__file__).resolve().parent
    for key in EXAMPLE_MODULE_OWNED_KEYS:
        assert key not in config_mod.DEFAULTS, (
            f"{key} is now a DEFAULTS key -- drop it from EXAMPLE_MODULE_OWNED_KEYS"
        )
        assert re.search(rf"^{re.escape(key)} = ", text, re.MULTILINE), \
            f"config.example.toml never documents {key}"
        readers = [p for p in src.rglob("*.py")
                   if f'"{key}"' in p.read_text(encoding="utf-8")]
        assert readers, f"nothing in ccsync_companion reads {key}"


def test_the_loopback_escape_hatches_are_documented_but_never_defaults():
    """Both halves of the deal: absent from DEFAULTS (so ensure_config never
    writes them into a first-run file and pins them), present in both
    templates as COMMENTED-OUT lines (so the editor reading broll_server's
    "set dashboard_url (or loopback_extra_origins)" refusal can find one)."""
    text = _example_toml_text()
    for key in EXAMPLE_ESCAPE_HATCHES:
        assert key not in config_mod.DEFAULTS, \
            f"{key} is an escape hatch -- see loopback_guard.py's docstring"
        assert re.search(rf"^#\s*{re.escape(key)} = ", text, re.MULTILINE), \
            f"config.example.toml never documents {key}"
        assert re.search(rf"^#\s*{re.escape(key)} = ", config_mod.DEFAULT_TOML_TEXT,
                         re.MULTILINE), f"DEFAULT_TOML_TEXT never documents {key}"


def test_the_keep_awake_thresholds_match_the_guard_module():
    """DEFAULTS and shutdown_guard's constants are two copies of the same two
    numbers (the constants are the fallback when a config dict predates the
    keys). Drift would mean a machine tuned by config and a machine falling
    back to the code disagreeing about when a lane is stalled."""
    from ccsync_companion import shutdown_guard

    assert config_mod.DEFAULTS["keep_awake_stale_seconds"] == \
        shutdown_guard.PROGRESS_STALE_SECONDS
    assert config_mod.DEFAULTS["keep_awake_max_hold_seconds"] == \
        shutdown_guard.MAX_HOLD_SECONDS


def test_the_example_documents_the_real_default_values():
    """A commented-out default that has drifted from the code is worse than
    no documentation: it is a number an admin will copy and trust."""
    text = _example_toml_text()
    for key in ("keep_awake_stale_seconds", "keep_awake_max_hold_seconds"):
        match = re.search(rf"^#\s*{key} = ([0-9.]+)$", text, re.MULTILINE)
        assert match, f"{key} is not documented with a value"
        assert float(match.group(1)) == float(config_mod.DEFAULTS[key])


@pytest.mark.parametrize("bad", ["3 minutes", 0, -5, None, [180]])
def test_a_bad_keep_awake_threshold_warns_but_never_stops_syncing(tmp_path, bad):
    """These only tune how patient the power guards are. Making them errors
    would set config_problems -- which stops every lane (DEL-3) and, because
    _shutdown_block_reason() returns None on config_problems, switches off the
    very guard the key was being tuned for."""
    errors, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, keep_awake_stale_seconds=bad))
    assert errors == []
    assert any("keep_awake_stale_seconds" in w for w in warnings)

    errors, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, keep_awake_max_hold_seconds=bad))
    assert errors == []
    assert any("keep_awake_max_hold_seconds" in w for w in warnings)


def test_good_keep_awake_thresholds_are_silent(tmp_path):
    errors, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, keep_awake_stale_seconds=45,
                  keep_awake_max_hold_seconds=3600))
    assert errors == []
    assert warnings == []


def test_config_example_parses_as_toml_and_loads():
    """It is meant to be copied to ~/.ccsync/config.toml verbatim."""
    import tomllib

    data = tomllib.loads(_example_toml_text())
    assert data["local_root"]
    assert set(data) <= set(config_mod.DEFAULTS) | EXAMPLE_MODULE_OWNED_KEYS


def _good_cfg(tmp_path, **overrides):
    # "Fully configured" gained dashboard_url + dashboard_token on 2026-08-17:
    # with no compiled-in dashboard default left, an install that names no
    # dashboard is an install nobody finished, and validate_config says so.
    cfg = {
        "editor_name": "editor2",
        "local_root": str(tmp_path),
        "remote": "ccsync_sftp",
        "remote_root": "/mnt/pool/share/Tree",
        "dashboard_url": "http://dash.example:8480",
        "dashboard_token": "tok",
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


def test_a_blank_dashboard_url_is_named_but_never_stops_the_lanes(tmp_path):
    """Inverted on 2026-08-17 (WP0). Blank used to mean "the admin turned
    reporting off", so nagging about it was noise; with the compiled-in
    default gone it much more often means "nobody pointed this install at a
    dashboard", and with require_login on that is an install where no lane
    will ever start. It stays a WARNING: app.py already refuses to start on
    config errors, and the lanes themselves work fine without a dashboard."""
    errors, warnings = config_mod.validate_config(_good_cfg(tmp_path, dashboard_url=""))
    assert errors == []
    blank = [w for w in warnings if "dashboard_url is blank" in w]
    assert len(blank) == 1
    assert "require_login" in blank[0]
    # and NOT the token/scheme nags, which only make sense once a URL is set
    assert not any("dashboard_token is blank" in w for w in warnings)

    off = config_mod.validate_config(
        _good_cfg(tmp_path, dashboard_url="", require_login=False))[1]
    assert any("dashboard_url is blank" in w for w in off)
    assert not any("require_login" in w for w in off if "dashboard_url is blank" in w)


def test_validate_config_flags_non_positive_dashboard_report_interval(tmp_path):
    errors, _ = config_mod.validate_config(_good_cfg(tmp_path, dashboard_report_interval=0))
    assert any("dashboard_report_interval must be a positive number" in e for e in errors)


def test_validate_config_flags_non_numeric_dashboard_report_interval(tmp_path):
    errors, _ = config_mod.validate_config(_good_cfg(tmp_path, dashboard_report_interval="soon"))
    assert any("dashboard_report_interval must be a positive number" in e for e in errors)


def test_default_remote_matches_installer_remote_name():
    # This used to pin one customer's rclone remote name in three files at
    # once. Since 2026-08-17 (WP0) the name comes from the dashboard's site
    # manifest, and the thing that must not drift is the FALLBACK the three
    # of them share when the manifest has none -- a lane pointed at a
    # nonexistent remote is still the failure being prevented.
    from pathlib import Path

    installer_dir = Path(__file__).resolve().parents[2] / "installer"
    ps1 = (installer_dir / "windows_bootstrap.ps1").read_text(encoding="utf-8")
    sh = (installer_dir / "macos_bootstrap.sh").read_text(encoding="utf-8")
    assert config_mod.NEUTRAL_REMOTE_NAME == "ccsync_sftp"
    assert f'$RemoteName = "{config_mod.NEUTRAL_REMOTE_NAME}"' in ps1
    assert f'REMOTE_NAME="{config_mod.NEUTRAL_REMOTE_NAME}"' in sh
    # ...and the compiled-in default is blank: a companion that nobody
    # configured must name no tenant at all.
    assert config_mod.DEFAULTS["remote"] == ""


def test_config_example_toml_matches_default_keys():
    # config.example.toml (shipped alongside pyproject.toml) should also
    # document every key â€” catches the file drifting from config.py.
    example_path = config_mod.CONFIG_DIR.parent  # not used; see below
    from pathlib import Path

    companion_root = Path(__file__).resolve().parent.parent
    example_text = (companion_root / "config.example.toml").read_text(encoding="utf-8")
    for key in config_mod.DEFAULTS:
        # Keys that MODE_PROFILES applies must be documented COMMENTED OUT,
        # exactly as DEFAULT_TOML_TEXT does. An explicit key in the file
        # always beats the profile, so a live `sync_enabled = true` in a file
        # whose header invites hand-copying makes mode="base" dead and gives
        # a machine whose local_root is the NAS share full sync lanes
        # (AUDIT_2 CORE-M5). The next assertion checks they're commented.
        pattern = rf"^#? ?{re.escape(key)} = "
        assert re.search(pattern, example_text, re.MULTILINE), (
            f"config.example.toml is missing an assignment for '{key}'"
        )
    for key in ("sync_enabled", "lane_b_enabled"):
        assert not re.search(rf"^{re.escape(key)} = ", example_text, re.MULTILINE), (
            f"config.example.toml must keep '{key}' COMMENTED OUT so MODE_PROFILES applies"
        )
        assert re.search(rf"^# {re.escape(key)} = ", example_text, re.MULTILINE)


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
    drift, and this test catches it at development time.

    Reads utf-8-sig, not a binary tomllib.load: this test is about VERSION
    PARITY, and it should not be the thing that fails when someone's editor
    leaves a BOM behind (it was, at 0f5d99d -- see
    test_no_pyproject_carries_a_utf8_bom below, which owns that job now, and
    config.py's load_config for the same reasoning)."""
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8-sig"))
    assert data["project"]["version"] == config_mod.VERSION


def test_no_pyproject_carries_a_utf8_bom():
    """Every pyproject.toml in the repo must parse as RAW BYTES.

    pip/setuptools reads pyproject.toml with a binary tomllib.load, and
    tomllib rejects a leading BOM -- so a BOM here is not a cosmetic
    encoding wart, it is "pip install -e . cannot run on this repo at all".
    That is exactly what happened at 0f5d99d: the 0.4.20 version bump was
    written by PowerShell's Set-Content, which prepends a BOM even when
    overwriting a BOM-less file (the same hazard config.py:539 documents for
    config.toml), and no Windows code path noticed because every Windows
    consumer of pyproject.toml reads it with a regex and tools/release.ps1
    never installs the package. A Mac running the first clean editable
    install found it in step 3/6 of the release.

    Deliberately binary: reading utf-8-sig here would defeat the point.

    Scope note: a BOM on *companion's own* pyproject.toml never reaches this
    assertion -- pytest reads [tool.pytest.ini_options] out of that same file
    and dies at startup with "Invalid statement (at line 1, column 1)" and
    exit code 4, which the release scripts' `|| fail` already catches. What
    this test adds is the SIBLING projects (bench/, dashboard/), whose
    pyprojects nothing else parses strictly, plus a named, greppable failure
    for the next person instead of a bare usage error.
    """
    import tomllib
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    pyprojects = sorted(repo_root.glob("*/pyproject.toml"))
    # A glob that silently found nothing would make this test vacuously green.
    assert pyprojects, f"no */pyproject.toml under {repo_root} -- has the layout moved?"

    for path in pyprojects:
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), (
            f"{path.relative_to(repo_root)} starts with a UTF-8 BOM -- "
            "pip's binary tomllib.load will reject it and nothing can build. "
            "Re-save the file as UTF-8 WITHOUT BOM."
        )
        # Not just the BOM: prove the file is actually loadable the way pip
        # loads it, so any other byte-level breakage fails here too.
        with path.open("rb") as fh:
            tomllib.load(fh)


def test_ignored_resolve_projects_default_and_coercion(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('editor_name = "x"\n', encoding="utf-8")
    cfg = config_mod.load_config(path)
    assert "Untitled Project" in cfg["ignored_resolve_projects"]
    assert "New Doc" in cfg["ignored_resolve_projects"]

    path.write_text('ignored_resolve_projects = "oops-not-a-list"\n', encoding="utf-8")
    cfg = config_mod.load_config(path)
    assert isinstance(cfg["ignored_resolve_projects"], list)


# -- the ignore matcher (shared by watcher.py and app.py) -------------------


def test_normalize_ignored_projects_drops_blanks_and_normalizes():
    assert config_mod.normalize_ignored_projects(
        ["Untitled Project", "  New  Doc ", "", "   ", None]
    ) == {"untitled project", "new doc"}
    # never raises on garbage -- "ignore nothing" is the safe answer
    assert config_mod.normalize_ignored_projects(None) == set()
    assert config_mod.normalize_ignored_projects(5) == set()


@pytest.mark.parametrize(
    "name",
    [
        "New Doc", "new doc", " NEW DOC ", "New  Doc",
        # Resolve's own duplicate suffixes -- what the Blackmagic Proxy
        # Generator's helper project actually looks like after a while.
        "New Doc 1", "New Doc 2", "new doc 17", "New Doc(2)", "New Doc (3)",
        "New Doc [4]", "New Doc-5", "New Doc_6",
        "Untitled Project", "Untitled Project 2",
    ],
)
def test_is_ignored_project_matches_scratch_projects_and_their_duplicates(name):
    assert config_mod.is_ignored_project(name, ["Untitled Project", "New Doc"])


@pytest.mark.parametrize(
    "name",
    ["New Doc Final", "New Documentary", "New Docs 2026", "A New Doc",
     "Untitled Project Reel", "", "   ", None],
)
def test_is_ignored_project_leaves_real_projects_alone(name):
    assert not config_mod.is_ignored_project(name, ["Untitled Project", "New Doc"])


def test_is_ignored_project_accepts_a_prenormalized_set_and_never_raises():
    normalized = config_mod.normalize_ignored_projects(["New Doc"])
    assert config_mod.is_ignored_project("New Doc 9", normalized)
    assert not config_mod.is_ignored_project("New Doc 9", set())
    assert not config_mod.is_ignored_project("New Doc 9", None)
    assert not config_mod.is_ignored_project(object(), ["new doc"])


# -- coerce_count: the "every N passes, 0 disables" knobs (AUDIT_3 M-5/M-6) --


def test_coerce_count_accepts_zero_and_falls_back_on_garbage(caplog):
    """coerce_numeric's positive-only gate is wrong for these keys: 0 means
    "disable this behaviour entirely" and is a legal, documented value."""
    assert config_mod.coerce_count({"orphan_scan_every_n_passes": 0}, "orphan_scan_every_n_passes", 20) == 0
    assert config_mod.coerce_count({"orphan_scan_every_n_passes": 5}, "orphan_scan_every_n_passes", 20) == 5
    assert config_mod.coerce_count({}, "orphan_scan_every_n_passes", 20) == 20
    with caplog.at_level(logging.ERROR, logger="ccsync.config"):
        assert config_mod.coerce_count({"k": "never"}, "k", 10) == 10
        assert config_mod.coerce_count({"k": -1}, "k", 10) == 10
        assert config_mod.coerce_count({"k": None}, "k", 10) == 10
    assert len(caplog.records) == 3


# -- missing-proxy notifier + ffmpeg proxy generator ------------------------


def test_proxy_keys_have_expected_defaults():
    assert config_mod.DEFAULTS["proxy_notify_enabled"] is True
    # None, not False: "derive it from lane_b_enabled" (proxy_generation_enabled).
    assert config_mod.DEFAULTS["proxy_gen_enabled"] is None
    assert config_mod.DEFAULTS["ffmpeg_path"] == "ffmpeg"
    assert config_mod.DEFAULTS["proxy_scan_interval"] == 900
    assert config_mod.DEFAULTS["proxy_gen_idle_seconds"] == 300
    assert config_mod.DEFAULTS["proxy_gen_min_age_seconds"] == 120
    assert config_mod.DEFAULTS["proxy_gen_max_height"] == 1080
    assert config_mod.DEFAULTS["proxy_gen_bitrate"] == "7M"
    assert config_mod.DEFAULTS["proxy_gen_max_failures"] == 3
    assert config_mod.DEFAULTS["proxy_notify_cooldown_seconds"] == 86400
    assert config_mod.DEFAULTS["proxy_gen_skip_while_resolve_running"] is False


def test_proxy_gen_enabled_derives_from_lane_b_when_absent():
    """The whole point of the tri-state. Lane B is `rclone sync` -- the one
    verb that deletes local files -- so a proxy generated on a machine lane B
    serves gets swept into .ccsync-trash on the next pass. Generation is on
    only where the result survives and reaches the fleet: the base rig, which
    is exactly the machine that runs lane_b_enabled=false."""
    assert config_mod.proxy_generation_enabled({"lane_b_enabled": True}) is False
    assert config_mod.proxy_generation_enabled({"lane_b_enabled": False}) is True
    # Absent entirely = the packaged lane_b_enabled default (true) = editor.
    assert config_mod.proxy_generation_enabled({}) is False


def test_mode_base_derives_generation_ON():
    """The regression that made the whole generator inert where it matters.

    `mode = "base"` used to bring only sync_enabled=False, so lane_b_enabled
    kept its packaged default of True and the derivation turned generation
    OFF on the one machine whose local_root IS the NAS tree. Seen live on the
    base rig 2026-08-10: 1046 clips scanned, 1040 queued, none encoded, and a
    toast telling the admin to ask their admin.

    Asserted through MODE_PROFILES rather than through a hand-built dict, so
    it fails if the profile is ever trimmed back.
    """
    profile = config_mod.MODE_PROFILES["base"]
    assert profile["lane_b_enabled"] is False
    assert profile["sync_enabled"] is False
    assert config_mod.proxy_generation_enabled(dict(profile)) is True
    # ...and an editor is still off, which is the half that must not regress.
    assert config_mod.proxy_generation_enabled(
        dict(config_mod.MODE_PROFILES["editor"])) is False


def test_sync_enabled_alone_does_not_turn_generation_on():
    """Deliberately NOT derived from sync_enabled: "sync is off" is not the
    same claim as "lane B will never sweep this tree". An editor who disables
    sync for a week, generates while away and re-enables it hands the next
    lane-B pass a tree of files the NAS has never seen."""
    assert config_mod.proxy_generation_enabled(
        {"sync_enabled": False, "lane_b_enabled": True}) is False


@pytest.mark.parametrize("lane_b", [True, False])
def test_explicit_proxy_gen_enabled_beats_the_derivation(lane_b):
    for explicit in (True, False):
        cfg = {"lane_b_enabled": lane_b, "proxy_gen_enabled": explicit}
        assert config_mod.proxy_generation_enabled(cfg) is explicit


@pytest.mark.parametrize("bad", ["yes", "false", 1, [], 0.0])
def test_a_garbage_proxy_gen_enabled_falls_back_to_the_derivation(bad, caplog):
    """bool("false") is True, so a hand-edited string cannot be coerced
    honestly -- and guessing wrong in the "on" direction is the direction that
    throws away encodes. Log it and derive."""
    with caplog.at_level(logging.ERROR, logger="ccsync.config"):
        assert config_mod.proxy_generation_enabled(
            {"lane_b_enabled": False, "proxy_gen_enabled": bad}) is True
        assert config_mod.proxy_generation_enabled(
            {"lane_b_enabled": True, "proxy_gen_enabled": bad}) is False
    assert len(caplog.records) == 2


def test_load_config_carries_the_proxy_keys(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config_mod.load_config(path)
    assert cfg["proxy_notify_enabled"] is True
    assert cfg["proxy_gen_enabled"] is None
    assert cfg["ffmpeg_path"] == "ffmpeg"
    assert cfg["proxy_scan_interval"] == 900
    # A first-run file on an editor (lane_b_enabled = true in the template)
    # must not switch generation on by itself.
    assert config_mod.proxy_generation_enabled(cfg) is False


@pytest.mark.parametrize("value", ["7M", "700k", "2.5M", "300K", "8000000"])
def test_coerce_bitrate_accepts_ffmpeg_bitrates(value):
    assert config_mod.coerce_bitrate({"proxy_gen_bitrate": value},
                                     "proxy_gen_bitrate", "7M") == value


@pytest.mark.parametrize("bad", ["fast", "", "7 Mbps", "M7", None, [7], True, -1])
def test_coerce_bitrate_falls_back_and_logs_on_garbage(bad, caplog):
    """ffmpeg offers no protection here: a bogus -b:v either kills the spawn
    (one failed encode per clip, forever) or is read as something else --
    "fast" parses as 0 bits/s, i.e. an unwatchable proxy rather than an
    error."""
    with caplog.at_level(logging.ERROR, logger="ccsync.config"):
        assert config_mod.coerce_bitrate({"proxy_gen_bitrate": bad},
                                         "proxy_gen_bitrate", "7M") == "7M"
    assert len(caplog.records) == 1


def test_coerce_bitrate_missing_key_is_silent(caplog):
    with caplog.at_level(logging.ERROR, logger="ccsync.config"):
        assert config_mod.coerce_bitrate({}, "proxy_gen_bitrate", "7M") == "7M"
    assert caplog.records == []


def test_missing_ffmpeg_warns_but_never_stops_syncing(tmp_path):
    """A machine with no ffmpeg syncs perfectly well and merely cannot make
    its own proxies -- the notifier still tells it which clips the fleet
    cannot see. An error here would stop every lane (DEL-3)."""
    cfg = _good_cfg(tmp_path, lane_b_enabled=False,
                    ffmpeg_path=str(tmp_path / "nowhere" / "ffmpeg"))
    errors, warnings = config_mod.validate_config(cfg)
    assert errors == []
    assert any("ffmpeg not found" in w for w in warnings)


def test_blank_ffmpeg_path_warns_when_generation_is_on(tmp_path):
    errors, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, lane_b_enabled=False, ffmpeg_path=""))
    assert errors == []
    assert any("ffmpeg_path is blank" in w for w in warnings)


def test_missing_ffmpeg_is_silent_when_generation_is_off(tmp_path):
    """An editor is never warned about a binary this machine was never going
    to run: lane_b_enabled=true derives generation off."""
    _errors, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, lane_b_enabled=True,
                  ffmpeg_path=str(tmp_path / "nowhere" / "ffmpeg")))
    assert not any("ffmpeg" in w for w in warnings)

    _errors, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, lane_b_enabled=False, proxy_gen_enabled=False,
                  ffmpeg_path=str(tmp_path / "nowhere" / "ffmpeg")))
    assert not any("ffmpeg" in w for w in warnings)


def test_a_resolvable_ffmpeg_is_silent(tmp_path):
    binary = tmp_path / "ffmpeg.exe"
    binary.write_text("not really ffmpeg", encoding="utf-8")
    errors, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, lane_b_enabled=False, ffmpeg_path=str(binary)))
    assert errors == []
    assert warnings == []


def test_an_editor_forcing_generation_on_still_gets_the_ffmpeg_warning(tmp_path):
    errors, warnings = config_mod.validate_config(
        _good_cfg(tmp_path, lane_b_enabled=True, proxy_gen_enabled=True,
                  ffmpeg_path=str(tmp_path / "nowhere" / "ffmpeg")))
    assert errors == []
    assert any("ffmpeg not found" in w for w in warnings)


def test_selection_ttl_keys_are_documented_and_validated(tmp_path):
    """Both were read via cfg.get(..., 30/300) with no entry in DEFAULTS, the
    template or validate_config -- undiscoverable, and a hand-edited value
    raised inside CompanionApp construction."""
    assert config_mod.DEFAULTS["selection_fetch_ttl"] == 30
    assert config_mod.DEFAULTS["project_roots_ttl"] == 300

    good = _good_cfg(tmp_path)
    errors, _warnings = config_mod.validate_config(good)
    assert errors == []

    for key in ("selection_fetch_ttl", "project_roots_ttl"):
        errors, _warnings = config_mod.validate_config(_good_cfg(tmp_path, **{key: "soon"}))
        assert any(key in e for e in errors), errors
        errors, _warnings = config_mod.validate_config(_good_cfg(tmp_path, **{key: 0}))
        assert any(key in e for e in errors), errors


# -- set_value: the Settings window's role-switch writer (2026-08-27) -------


def test_set_value_creates_the_file_and_writes_the_key(tmp_path):
    path = tmp_path / "config.toml"
    assert not path.exists()
    config_mod.set_value(path, "mode", "base")
    assert path.exists()
    reloaded = config_mod.load_config(path)
    assert reloaded["mode"] == "base"


def test_set_value_updates_an_existing_key_in_place(tmp_path):
    path = tmp_path / "config.toml"
    config_mod.ensure_config_exists(path)
    before = path.read_text(encoding="utf-8")
    assert 'editor_name = ""' in before

    config_mod.set_value(path, "mode", "base")
    after = path.read_text(encoding="utf-8")

    # The key changed...
    assert config_mod.load_config(path)["mode"] == "base"
    # ...and every OTHER line survived untouched, comments included.
    assert 'editor_name = ""' in after
    assert "# ccsync-companion config" in after


def test_set_value_round_trips_and_can_be_flipped_back(tmp_path):
    path = tmp_path / "config.toml"
    config_mod.set_value(path, "mode", "base")
    assert config_mod.load_config(path)["mode"] == "base"

    config_mod.set_value(path, "mode", "editor")
    assert config_mod.load_config(path)["mode"] == "editor"


def test_set_value_appends_a_key_that_is_not_in_the_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("editor_name = \"alex\"\n", encoding="utf-8")
    config_mod.set_value(path, "mode", "base")
    reloaded = config_mod.load_config(path)
    assert reloaded["mode"] == "base"
    assert reloaded["editor_name"] == "alex"


def test_set_value_hardens_a_freshly_created_file(tmp_path, monkeypatch):
    """Every other path to config.toml goes through ensure_config_exists's
    owner-only hardening (secretfile.harden) the moment the file is created;
    set_value must not be a side door around that."""
    from ccsync_companion import secretfile

    path = tmp_path / "config.toml"
    hardened = []
    monkeypatch.setattr(secretfile, "harden", lambda p: hardened.append(p))
    config_mod.set_value(path, "mode", "base")
    # The file itself when ensure_config_exists created it, and then the
    # .tmp BEFORE each rename -- set_value's own write and the config.toml.bak
    # load_config refreshes (APP-4, 2026-08-28). Never the live file after a
    # write, which would leave a window where it is world-readable.
    assert path in hardened
    assert hardened[0] == path
    assert all(p == path or p.name.endswith(".tmp") for p in hardened), hardened


# -- APP-4 / APP-11: the atomic write, the backup, and the read-back --------


def test_set_value_writes_through_a_tmp_file_and_never_truncates_the_live_one(
        tmp_path, monkeypatch):
    """A kill between truncate and rewrite used to leave config.toml empty,
    which on the next start is load_config falling back to ALL DEFAULTS --
    no local_root, no remote, and no dashboard_url, so the machine also
    stops reporting and vanishes from the fleet grid (APP-4)."""
    path = tmp_path / "config.toml"
    config_mod.ensure_config_exists(path)
    before = path.read_text(encoding="utf-8")

    real_replace = config_mod.os.replace

    def _die(src, dst):
        raise OSError("no space left on device")

    monkeypatch.setattr(config_mod.os, "replace", _die)
    assert config_mod.set_value(path, "mode", "base") is False
    # The live file is untouched, and no .tmp is left lying around.
    assert path.read_text(encoding="utf-8") == before
    assert not (tmp_path / "config.toml.tmp").exists()

    monkeypatch.setattr(config_mod.os, "replace", real_replace)
    assert config_mod.set_value(path, "mode", "base") is True


def test_load_config_keeps_a_backup_of_the_last_file_that_parsed(tmp_path):
    path = tmp_path / "config.toml"
    config_mod.set_value(path, "editor_name", "owen")
    config_mod.load_config(path)
    backup = config_mod.backup_path(path)
    assert backup.exists()
    assert 'editor_name = "owen"' in backup.read_text(encoding="utf-8")


def test_a_corrupt_config_loads_the_backup_instead_of_all_defaults(tmp_path, caplog):
    path = tmp_path / "config.toml"
    config_mod.set_value(path, "editor_name", "owen")
    config_mod.set_value(path, "dashboard_url", "http://nas:8081")
    config_mod.load_config(path)  # seeds config.toml.bak

    path.write_text("", encoding="utf-8")  # the truncated-write shape
    path.write_text('editor_name = "ow', encoding="utf-8")  # ...or a torn one
    with caplog.at_level("ERROR"):
        cfg = config_mod.load_config(path)

    assert cfg["editor_name"] == "owen"
    assert cfg["dashboard_url"] == "http://nas:8081"
    assert cfg["_config_from_backup"] is True
    assert cfg["_config_load_error"]
    assert "last good copy" in caplog.text
    # ...and the editor/admin is still told, so this is never silent.
    errors, _warnings = config_mod.validate_config(cfg)
    assert any("last good copy" in e for e in errors)


def test_a_corrupt_config_with_no_backup_still_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("editor_name = \"ow", encoding="utf-8")
    cfg = config_mod.load_config(path)
    assert cfg["_config_load_error"]
    assert cfg["_config_from_backup"] is False
    assert cfg["editor_name"] == config_mod.DEFAULTS["editor_name"]


def test_set_value_inserts_before_a_table_header_not_at_eof(tmp_path):
    """APP-11: an appended key landed INSIDE the last table, so `mode`
    parsed as `proxy.mode`, top-level `mode` stayed absent, and the Settings
    role button appeared to do nothing at all, every time."""
    path = tmp_path / "config.toml"
    path.write_text(
        '\n'.join(['editor_name = "owen"', '', '[proxy]', 'mode = "keep"', '']),
        encoding="utf-8")

    assert config_mod.set_value(path, "mode", "base") is True
    cfg = config_mod.load_config(path)
    assert cfg["mode"] == "base"
    assert cfg["editor_name"] == "owen"
    # The table's own key is untouched.
    assert cfg["proxy"]["mode"] == "keep"


def test_set_value_reports_false_when_the_value_cannot_be_read_back(tmp_path,
                                                                    monkeypatch):
    path = tmp_path / "config.toml"
    config_mod.ensure_config_exists(path)

    real_load = config_mod.load_config

    def _lies(p=config_mod.CONFIG_PATH):
        data = dict(real_load(p))
        data["mode"] = "editor"
        return data

    monkeypatch.setattr(config_mod, "load_config", _lies)
    assert config_mod.set_value(path, "mode", "base") is False


# -- project_rotation_seconds is the watchdog's budget (SYS-17, CR-91) -------


@pytest.mark.parametrize("value", [0, -1, "off", None])
def test_validate_config_refuses_a_non_positive_project_rotation(tmp_path, value):
    """A hand-edited `project_rotation_seconds = 0` silently removed
    --max-duration from every lane command (`_max_duration_flags` returns []),
    i.e. it removed the only time budget a pass had. SYS-17 asks for the
    refusal to be explicit rather than implicit; this pins it, because the
    stall watchdog's two ceilings are derived from the same number."""
    errors, _warnings = config_mod.validate_config(
        _good_cfg(tmp_path, project_rotation_seconds=value))
    assert any("project_rotation_seconds must be a positive number" in e for e in errors)


def test_a_valid_project_rotation_is_not_flagged(tmp_path):
    errors, _warnings = config_mod.validate_config(
        _good_cfg(tmp_path, project_rotation_seconds=900))
    assert not any("project_rotation_seconds" in e for e in errors)
