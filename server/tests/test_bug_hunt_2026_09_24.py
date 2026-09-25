"""Regressions for the 2026-09-24 bug hunt, server/ half (webapps-ops group).

One group per finding, named by its id. Offline; run from GIT BASH (see
CLAUDE.md).

    cd E:\Projects\Editing\ccsync\server
    ../dashboard/.venv/Scripts/python.exe -m pytest tests/test_bug_hunt_2026_09_24.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import install_dashboard_app as ida  # noqa: E402
import publish_db  # noqa: E402
from test_bug_hunt_2026_08_21 import _Args, _backend  # noqa: E402

# What the NAS really holds after two publishes of an index the container had
# open in WAL mode: each .prev carries the -wal/-shm the swap moved with it.
_LISTING = ("/d/broll.db.prev-20260819T090000\n"
            "/d/broll.db.prev-20260819T090000-shm\n"
            "/d/broll.db.prev-20260819T090000-wal\n"
            "/d/broll.db.prev-20260821T101500\n"
            "/d/broll.db.prev-20260821T101500-shm\n"
            "/d/broll.db.prev-20260821T101500-wal\n")


# --------------------------------------------------------------------------
# bug-ops-1: --rollback renamed the .prev's WAL journal over the live index

def test_the_newest_prev_is_a_database_never_its_wal(monkeypatch):
    monkeypatch.setattr(ida, "run_ssh",
                        lambda cmd, dry_run=False, timeout=120: (0, _LISTING, ""))
    prev, why = publish_db.newest_prev(_backend(), "/d", "broll.db", False)
    assert why == ""
    assert prev == "/d/broll.db.prev-20260821T101500", prev


def test_the_rollback_script_moves_the_database_over_the_live_path(
        monkeypatch, capsys):
    """Driven end to end through do_rollback: the script it hands the NAS is
    what decides which file becomes the live index."""
    monkeypatch.setattr(publish_db, "remote_dir_for", lambda which, b: "/d")
    ran = []

    def guarded(cmd, dry_run, timeout):
        ran.append(cmd)
        return (0, _LISTING, "") if len(ran) == 1 else (0, "rolled back\n", "")

    monkeypatch.setattr(ida, "run_ssh_guarded", guarded)
    rc = publish_db.do_rollback(_Args(), _backend(), publish_db.SPECS["broll"])
    assert rc == 0, capsys.readouterr().err
    script = ran[1]
    # The echo at the end names the file that was renamed over the live path,
    # unquoted, so it survives the sh -c quoting intact.
    assert "restored from /d/broll.db.prev-20260821T101500 (" in script, script


def test_a_sidecar_named_by_hand_is_refused_before_the_nas_is_touched(
        monkeypatch, capsys):
    monkeypatch.setattr(publish_db, "remote_dir_for", lambda which, b: "/d")

    def guarded(cmd, dry_run, timeout):
        raise AssertionError("nothing may run for a sidecar --from-prev")

    monkeypatch.setattr(ida, "run_ssh_guarded", guarded)
    args = _Args()
    args.from_prev = "/d/broll.db.prev-20260821T101500-wal"
    assert publish_db.do_rollback(args, _backend(),
                                  publish_db.SPECS["broll"]) == 1
    assert "sidecar" in capsys.readouterr().err
