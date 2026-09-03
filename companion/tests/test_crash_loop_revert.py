"""The crash-loop revert path out of CompanionApp.run().

bug-hunt-2026-09-03 comp-core-4: that path returns BEFORE run()'s try/finally,
so shutdown() -- and with it crash_report.mark_clean_exit() -- never runs. The
run marker written for this pid was therefore left on disk, and the restored
build read it as an UncleanExit: a crash report describing a rollback the
companion performed on purpose, beside the real ones an admin is reading.
"""

from __future__ import annotations

from typing import Any

from ccsync_companion import app as app_mod
from ccsync_companion import crash_report
from ccsync_companion.app import CompanionApp


def _cfg(tmp_path, **overrides) -> dict[str, Any]:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg = {
        "editor_name": "owen",
        "local_root": str(root),
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "active_project": "",
        "poll_interval": 3,
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "popup_enabled": True,
        "sync_enabled": False,
        "lane_b_enabled": False,
    }
    cfg.update(overrides)
    return cfg


def test_a_crash_loop_revert_clears_the_run_marker(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    app = CompanionApp(cfg)
    app.start = lambda: None  # nothing may actually start on this path

    monkeypatch.setattr(app_mod.upgrade_mod, "note_version_start",
                        lambda state_dir: {"upgraded": False, "starts": 3,
                                           "crash_loop": True})
    monkeypatch.setattr(app_mod.upgrade_mod, "revert_to_previous_build",
                        lambda *a, **kw: ("0.9.54", ""))
    marker = crash_report.write_run_marker(cfg)
    assert marker is not None and marker.exists()

    app.run()

    assert not marker.exists(), (
        "the restored build reads a surviving marker as an UncleanExit crash"
    )


def test_a_normal_start_is_not_diverted_by_the_marker_clear(tmp_path, monkeypatch):
    """The clear belongs to the revert branch only: a start that is NOT in a
    crash loop must keep its marker, which is the whole UncleanExit net."""
    cfg = _cfg(tmp_path)
    app = CompanionApp(cfg)
    started = []
    app.start = lambda: started.append(True)

    monkeypatch.setattr(app_mod.upgrade_mod, "note_version_start",
                        lambda state_dir: {"upgraded": False, "starts": 1,
                                           "crash_loop": False})
    monkeypatch.setattr(app_mod.ui_dispatch, "start", lambda *a, **kw: None)
    from ccsync_companion import tray as tray_mod

    monkeypatch.setattr(tray_mod, "start_tray",
                        lambda *a, **kw: app._stop_event.set())
    marker = crash_report.write_run_marker(cfg)
    assert marker is not None

    app.run()

    assert started, "a non-crash-loop start must go on and start the companion"
