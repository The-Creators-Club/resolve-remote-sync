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
    # The GPLv3 unblock lock (CR-73/CR-84). Present in every world so the
    # youtube_unblock branch is reachable; it only runs when the env says so.
    (app / "deploy" / "requirements-unblock.lock").write_text(
        "bgutil-ytdlp-pot-provider==1.3.1\n")
    data = tmp_path / "data"
    data.mkdir()
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
    pip_log = tmp_path / "pip.log"
    pypath_log = tmp_path / "pypath.log"
    counter = tmp_path / "counter"
    counter.write_text("0")

    # $VENV/bin/pip, for the youtube_unblock install (CR-84). Records its argv
    # and, in the --target shape, actually creates the directory so the test
    # can see where the plugin would have landed.
    pip = venv / "bin" / "pip"
    pip.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{pip_log}"\n'
        "target=\"\"\n"
        "while [ $# -gt 0 ]; do\n"
        '  if [ "$1" = "--target" ]; then target="$2"; fi\n'
        "  shift\n"
        "done\n"
        'if [ -n "$target" ]; then mkdir -p "$target/yt_dlp_plugins"; fi\n'
        "exit 0\n",
        newline="\n")
    pip.chmod(0o755)
    # A shell stub rather than a python one: this test must not depend on a
    # python being on PATH inside the sh it found.
    stub = venv / "bin" / "python"
    stub.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        # The unblock install's MARKER write (YTWEB-5, 2026-09-03) also runs
        # through $VENV/bin/python, with its script on stdin ("-" as argv[1]).
        # Answered and dropped here: it is neither a code-root selection nor an
        # app launch, so it must not consume one of this world's exit codes and
        # must not appear in the PYTHONPATH log, which is the record of what
        # the APP was started with.
        'case "$1" in\n'
        f'  -) echo "MARKER $2 ok=$3 attempts=$4" >> "{log}"; exit 0 ;;\n'
        'esac\n'
        f'echo "PYTHONPATH=$PYTHONPATH" >> "{pypath_log}"\n'
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
    text = (text.replace("/venv", venv.as_posix())
                .replace("/app/", app.as_posix() + "/")
                .replace("/data", data.as_posix()))
    script.write_text(text, encoding="utf-8", newline="\n")
    return {"script": script, "log": log, "pip_log": pip_log, "pypath_log": pypath_log,
            "venv": venv, "app": app, "data": data}


def run(world, timeout: float = 30.0, **env_extra) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DASH_PORT"] = "8480"
    env.update(env_extra)
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


def test_image_mode_installs_the_unblock_plugin_where_it_can_actually_write(tmp_path):
    """CR-84, 2026-08-26. In image mode /venv is an image layer chmod'd a+rX
    (AUDIT C-1) and the container is uid 3000, so `pip install ... -r
    requirements-unblock.lock` into /venv can never succeed -- the live NAS
    logged `[Errno 13] Permission denied: '.../yt_dlp_plugins'` four times per
    boot behind CR-73's "PyPI unreachable?" retries, and the only fix was a
    `docker exec -u 0` that the next image update discarded. It now installs
    into a uid-3000-owned directory under /data (which survives an image
    update, exactly like /data/code) and puts that on PYTHONPATH."""
    world = build_world(tmp_path, image_mode=True, exits=["0"])
    proc = run(world, DASH_SITE_YOUTUBE_UNBLOCK="1")
    assert proc.returncode == 0, proc.stderr

    site = world["data"] / "unblock-site"
    pip_calls = world["pip_log"].read_text().splitlines()
    assert len(pip_calls) == 1, pip_calls
    assert f"--target {site.as_posix()}" in pip_calls[0]
    # --no-deps is a condition of --target here: the lock is a closure of one
    # package whose only dependency is yt-dlp, already in the venv and NOT
    # hashed in this lock, so pip would refuse under --require-hashes.
    assert "--no-deps" in pip_calls[0]
    assert "--require-hashes" in pip_calls[0]
    # the stamp moves to /data with it -- a stamp in the read-only venv could
    # not be written either, so every boot would re-run the install
    assert (world["data"] / ".requirements-unblock-hash").exists()
    assert not (world["venv"] / ".requirements-unblock-hash").exists()

    # ...and yt-dlp finds a plugin by walking sys.path for `yt_dlp_plugins`
    # (yt_dlp/plugins.py, default_plugin_paths), so the directory has to be a
    # PYTHONPATH entry. Appended, never prepended.
    exported = [line for line in world["pypath_log"].read_text().splitlines()
                if line.startswith("PYTHONPATH=")]
    assert exported, "the stub was never called"
    for line in exported:
        assert line.endswith(":" + site.as_posix()), line
    assert f"PYTHONPATH={tmp_path}/selected-root:{site.as_posix()}" in proc.stdout

    # ...and the install wrote down what happened, beside the plugin (YTWEB-5,
    # 2026-09-03). CR-73 and CR-84 each ran for days with four WARNING lines in
    # a container log as the entire evidence of this step.
    marker = [c for c in world["log"].read_text().splitlines()
              if c.startswith("MARKER ")]
    assert marker, world["log"].read_text()
    assert "/unblock-site/plugin_install.json" in marker[0], marker
    assert "ok=1" in marker[0], marker


def test_bind_mount_mode_still_installs_the_unblock_plugin_into_the_venv(tmp_path):
    """The live fleet's shape is untouched: there /venv is a bind mount owned
    by uid 3000, the install has always worked, and moving it would strand the
    copy already installed."""
    world = build_world(tmp_path, image_mode=False, exits=["0"])
    proc = run(world, DASH_SITE_YOUTUBE_UNBLOCK="1")
    assert proc.returncode == 0, proc.stderr

    pip_calls = world["pip_log"].read_text().splitlines()
    assert len(pip_calls) == 1, pip_calls
    assert "--target" not in pip_calls[0]
    assert "--no-deps" not in pip_calls[0]
    assert (world["venv"] / ".requirements-unblock-hash").exists()
    assert not (world["data"] / "unblock-site").exists()

    exported = [line for line in world["pypath_log"].read_text().splitlines()
                if line.startswith("PYTHONPATH=")]
    assert exported == [f"PYTHONPATH={world['app'].as_posix()}/src:/broll-app:"
                        f"/music-app:/ytdl-app"], exported


def test_a_failed_unblock_install_prints_pips_own_error(tmp_path):
    """CR-84: the retry loop assumed the only cause was CR-73's boot-time
    network gap, so the log said "PyPI unreachable?" while pip was saying
    "Permission denied" -- a diagnosis nobody could reach from the log they
    had. It must never be fatal either: this dependency serves one optional
    feature and the dashboard has to keep booting."""
    world = build_world(tmp_path, image_mode=True, exits=["0"])
    (world["venv"] / "bin" / "pip").write_text(
        "#!/bin/sh\n"
        "echo \"ERROR: Could not install packages due to an OSError: \"\n"
        "echo \"[Errno 13] Permission denied: '/venv/lib/python3.12/\"\n"
        "exit 1\n",
        newline="\n")
    (world["venv"] / "bin" / "pip").chmod(0o755)
    # the retry sleeps are 5/15/30 s; this test pays them once, deliberately,
    # because "it gave up cleanly" is the behaviour being pinned.
    proc = run(world, timeout=120.0, DASH_SITE_YOUTUBE_UNBLOCK="1")
    assert proc.returncode == 0, proc.stderr        # never fatal
    assert "Permission denied" in proc.stderr
    assert "youtube_unblock dependency install FAILED" in proc.stderr
    assert not (world["data"] / ".requirements-unblock-hash").exists()

    # YTWEB-5: and it is written down, with pip's own words and how many tries
    # it took, where /ytdl's health route reads it. A marker that only ever
    # says "fine" is a marker nobody can tell from a run.sh too old to write
    # one, so the failure is recorded as loudly as the success.
    marker = [c for c in world["log"].read_text().splitlines()
              if c.startswith("MARKER ")]
    assert marker, world["log"].read_text()
    assert "ok=0" in marker[0], marker
    assert "attempts=4" in marker[0], marker


def test_run_sh_has_no_carriage_returns():
    """A CRLF run.sh once took the dashboard down ("Illegal option -"), and
    MSYS grep strips a CR before matching -- so this is a byte scan
    (.gitattributes, 2026-08-10)."""
    assert b"\r" not in RUN_SH.read_bytes()
