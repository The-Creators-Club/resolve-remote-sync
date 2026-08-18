"""deploy/run.sh's restart loop (ZERO_TOUCH_PLAN.md WP K, 2026-08-18).

Exit 75 from the app means "I have staged new code, re-select the root and
exec me again"; anything else has to exit exactly as it always did, or a
`docker stop` and a crash-loop both stop behaving the way every runbook says
they do.

Executed with a REAL `sh` against a copied-and-rewritten run.sh and a stub
`python`, the same shape server/tests uses for the generated remote scripts.
Skipped cleanly where there is no POSIX shell (this suite also runs from
PowerShell on a machine without Git Bash).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUN_SH = REPO / "dashboard" / "deploy" / "run.sh"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None,
                                reason="no POSIX sh on this machine")


def build_world(tmp_path: Path, *, image_mode: bool, exits: list[str]) -> dict:
    """A rewritten run.sh plus a stub python that answers both of the things
    the script asks it: the code-root selection, and uvicorn."""
    app = tmp_path / "app"
    (app / "deploy").mkdir(parents=True)
    (app / "deploy" / "requirements.lock").write_text("fastapi==0.1\n")
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    if image_mode:
        (venv / ".image-baked").write_text("")
    # The stamp file run.sh compares requirements.lock's md5 against, so the
    # bind-mount branch does not try to pip install in this test either.
    import hashlib
    (venv / ".requirements-hash").write_text(
        hashlib.md5((app / "deploy" / "requirements.lock").read_bytes()).hexdigest())

    # POSIX-form paths everywhere below: MSYS's sh understands "C:/..." but
    # not "C:\...", and this suite runs on Windows.
    log = tmp_path / "calls.log"
    counter = tmp_path / "counter"
    counter.write_text("0")
    # A shell stub rather than a python one: this test must not depend on a
    # python being on PATH inside the sh it found.
    stub = venv / "bin" / "python"
    stub.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'case "$1" in\n'
        f'  *select_code_root.py) echo "{tmp_path}/selected-root"; exit 0 ;;\n'
        "esac\n"
        f'n=$(cat "{counter}")\n'
        f'n=$((n + 1)); echo "$n" > "{counter}"\n'
        + "".join(f'if [ "$n" = "{i + 1}" ]; then exit {code}; fi\n'
                  for i, code in enumerate(exits))
        + "exit 0\n",
        newline="\n")
    stub.chmod(0o755)

    script = tmp_path / "run.sh"
    text = RUN_SH.read_text(encoding="utf-8")
    text = text.replace("/venv", venv.as_posix()).replace("/app/", app.as_posix() + "/")
    script.write_text(text, encoding="utf-8", newline="\n")
    return {"script": script, "log": log, "venv": venv, "app": app}


def run(world, timeout: float = 30.0) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DASH_PORT"] = "8480"
    return subprocess.run(["sh", world["script"].as_posix()], capture_output=True, text=True,
                          timeout=timeout, env=env)


def test_exit_75_re_runs_the_selection_and_the_app(tmp_path):
    world = build_world(tmp_path, image_mode=True, exits=["75", "0"])
    proc = run(world)
    assert proc.returncode == 0, proc.stderr
    calls = world["log"].read_text().splitlines()
    # select, uvicorn(75), select again, uvicorn(0): the selection is re-run
    # on purpose, so a watchdog revert between two boots is honoured.
    assert sum(1 for c in calls if "select_code_root.py" in c) == 2
    assert sum(1 for c in calls if "uvicorn" in c) == 2
    assert "asked to restart (exit 75)" in proc.stdout


def test_any_other_exit_code_is_final(tmp_path):
    """A crash must still crash: the loop is for one code and one code only."""
    world = build_world(tmp_path, image_mode=True, exits=["3"])
    proc = run(world)
    assert proc.returncode == 3
    calls = world["log"].read_text().splitlines()
    assert sum(1 for c in calls if "uvicorn" in c) == 1


def test_the_selected_root_becomes_pythonpath(tmp_path):
    world = build_world(tmp_path, image_mode=True, exits=["0"])
    proc = run(world)
    assert f"PYTHONPATH={tmp_path}/selected-root" in proc.stdout


def test_bind_mount_mode_never_runs_the_selection(tmp_path):
    """The live fleet's shape: no /venv/.image-baked, no OTA path at all, and
    the same single exec run.sh has always done."""
    world = build_world(tmp_path, image_mode=False, exits=["0"])
    proc = run(world)
    assert proc.returncode == 0
    calls = world["log"].read_text().splitlines()
    assert not any("select_code_root.py" in c for c in calls)
    assert sum(1 for c in calls if "uvicorn" in c) == 1


def test_run_sh_has_no_carriage_returns():
    """A CRLF run.sh once took the dashboard down ("Illegal option -"), and
    MSYS grep strips a CR before matching -- so this is a byte scan
    (.gitattributes, 2026-08-10)."""
    assert b"\r" not in RUN_SH.read_bytes()
