"""GL-27 / CR-372 (2026-10-07): repair of a ~/.ccsync an old wizard locked."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ccsync_companion import state_acl

win_only = pytest.mark.skipif(sys.platform != "win32", reason="icacls")


def _old_bootstrap_acl(d: Path) -> None:
    """The exact command the pre-2026-10-07 Protect-CCSyncPath ran."""
    me = f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"
    subprocess.run(
        ["icacls", str(d), "/inheritance:r", "/grant:r", f"{me}:(F)",
         "*S-1-5-18:(F)", "*S-1-5-32-544:(F)"],
        check=True, capture_output=True,
    )


@win_only
def test_old_command_locks_existing_children_and_repair_unlocks(tmp_path):
    d = tmp_path / "dot-ccsync"
    (d / "state").mkdir(parents=True)
    (d / "state" / "lane_b_breaker.json").write_text("{}")
    (d / "eula_accepted.json").write_text("{}")
    _old_bootstrap_acl(d)
    denied = state_acl.find_denied(d)
    if not denied:
        # 2026-11-08: the old command grants *S-1-5-32-544 (Administrators)
        # full control, so on an account that runs elevated -- the GitHub
        # Windows runner's runneradmin -- the lock it reproduces never takes,
        # and this assertion failed every release build since 2026-11-01.
        # Nothing was locked, so there is nothing for repair to prove here;
        # an editor's ordinary account (and this rig) still runs it.
        pytest.skip("this account still reads the children after the old "
                    "icacls call (elevated administrator): the lock never took")
    assert denied, "the old icacls call should have left children unreadable"
    assert state_acl.repair_if_needed(d) == "repaired"
    assert state_acl.find_denied(d) == []
    # the latch can be written again, and a NEW child inherits too
    (d / "state" / "lane_b_breaker.json").write_text('{"x": 1}')
    (d / "state" / "new.json").write_text("{}")
    assert (d / "eula_accepted.json").read_text() == "{}"


@win_only
def test_healthy_folder_is_left_alone(tmp_path, monkeypatch):
    d = tmp_path / "ok"
    d.mkdir()
    (d / "a.json").write_text("{}")
    called = []
    monkeypatch.setattr(state_acl, "repair", lambda r: called.append(r) or True)
    assert state_acl.repair_if_needed(d) == "ok"
    assert called == []


def test_not_windows_or_missing_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert state_acl.repair_if_needed(tmp_path) == "skipped"
    monkeypatch.setattr(sys, "platform", "win32")
    assert state_acl.repair_if_needed(tmp_path / "nope") == "skipped"


def test_repair_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(state_acl, "find_denied", lambda r: (_ for _ in ()).throw(RuntimeError("x")))
    assert state_acl.repair_if_needed(tmp_path) == "failed"


def test_repair_grants_inheritably_and_resets_children_not_the_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("USERNAME", "u")
    monkeypatch.setenv("USERDOMAIN", "D")
    calls = []
    monkeypatch.setattr(state_acl, "_icacls", lambda a: calls.append(a) or 0)
    assert state_acl.repair(tmp_path)
    assert "(OI)(CI)" in " ".join(calls[0]) and "/inheritance:r" in calls[0]
    assert calls[1][0].endswith("*") and "/reset" in calls[1] and "/T" in calls[1]
    assert str(tmp_path) != calls[1][0]
