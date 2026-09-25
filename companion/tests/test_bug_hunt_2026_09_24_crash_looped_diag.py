"""bug-comp-core-1, round 2 (2026-09-25): the diagnostics dump reads a
crash-loop revert's give-up record as "kept crashing", not as a failed
download.

The revert writes REL-8's give-up record (attempts at the cap, last_error
"crash-looped") so that the restored build stops taking the build it fled.
The dump then said "GIVEN UP on that build: it has failed 8 times", which
reads as a download problem whose fix is installing that build by hand.
"""
from __future__ import annotations

from typing import Any

from ccsync_companion.app import CompanionApp


def _make_app(tmp_path) -> CompanionApp:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg: dict[str, Any] = {
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
    return CompanionApp(cfg)


def test_the_dump_says_the_fled_build_kept_crashing(tmp_path):
    from ccsync_companion import upgrade as upgrade_mod

    app = _make_app(tmp_path)
    upgrade_mod.note_reverted_from(app._upgrade_attempts_path(), "9.9.9")
    app._load_upgrade_state()

    text = app.build_diagnostics()

    assert "GIVEN UP on that build: it kept crashing" in text
    assert "has failed 8 times" not in text


def test_a_download_give_up_keeps_its_own_words(tmp_path):
    from ccsync_companion import upgrade as upgrade_mod

    app = _make_app(tmp_path)
    for _ in range(upgrade_mod.MAX_UPGRADE_ATTEMPTS):
        upgrade_mod.note_upgrade_attempt(
            app._upgrade_attempts_path(), "9.9.9", upgrade_mod.ERROR_DOWNLOAD)
    app._load_upgrade_state()

    text = app.build_diagnostics()

    assert (f"GIVEN UP on that build: it has failed "
            f"{upgrade_mod.MAX_UPGRADE_ATTEMPTS} times") in text
    assert "kept crashing and was rolled back" not in text
