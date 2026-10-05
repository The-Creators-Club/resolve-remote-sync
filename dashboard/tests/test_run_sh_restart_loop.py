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
import time
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
    app_pypath_log = tmp_path / "app_pypath.log"
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
        # The yt-dlp nightly boot install (CR-361) is `-m ytdlweb.ytdlp_nightly
        # install --root R`: answered here for the same reason as the marker.
        # With STUB_NIGHTLY set it stages that version the way the real module
        # does (versions/<v>/yt_dlp/version.py + `current`); STUB_NIGHTLY_EXIT
        # makes it fail, which run.sh must shrug off.
        'if [ "$1" = "-m" ] && [ "$2" = "ytdlweb.ytdlp_nightly" ]; then\n'
        f'  echo "NIGHTLY $3 root=$5 PYTHONPATH=$PYTHONPATH" >> "{log}"\n'
        # STUB_NIGHTLY_SLEEP: a slow PyPI (146 s live, 2026-10-05).
        '  if [ -n "${STUB_NIGHTLY_SLEEP:-}" ]; then sleep "$STUB_NIGHTLY_SLEEP"; fi\n'
        '  if [ -n "${STUB_NIGHTLY:-}" ]; then\n'
        '    mkdir -p "$5/versions/$STUB_NIGHTLY/yt_dlp"\n'
        '    echo "__version__ = \'$STUB_NIGHTLY\'" > "$5/versions/$STUB_NIGHTLY/yt_dlp/version.py"\n'
        '    echo "$STUB_NIGHTLY" > "$5/current"\n'
        '  fi\n'
        '  exit "${STUB_NIGHTLY_EXIT:-0}"\n'
        'fi\n'
        f'echo "PYTHONPATH=$PYTHONPATH" >> "{pypath_log}"\n'
        'case "$1" in\n'
        f'  *select_code_root.py) echo "{tmp_path}/selected-root"; exit 0 ;;\n'
        "esac\n"
        # Past the selection: from here on this IS an app launch, and
        # app_pypath_log records only those (CR-361's tests read it).
        f'echo "PYTHONPATH=$PYTHONPATH" >> "{app_pypath_log}"\n'
        f'n=$(cat "{counter}")\n'
        f'n=$((n + 1)); echo "$n" > "{counter}"\n'
        # A one-shot hook run by the first app launch: how a test makes the
        # running app "stage" something between two passes of the loop.
        f'if [ -f "{tmp_path}/launch_hook.sh" ]; then\n'
        f'  . "{tmp_path}/launch_hook.sh"; rm -f "{tmp_path}/launch_hook.sh"\n'
        'fi\n'
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
            "app_pypath_log": app_pypath_log,
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


# ---------------------------------------------------------------------------
# CR-361 (2026-10-05): the yt-dlp nightly beside the image's pinned copy
# ---------------------------------------------------------------------------

NIGHTLY = "2026.09.27.232945"


def _app_paths(world) -> list[str]:
    log = world["app_pypath_log"]
    return [line for line in (log.read_text().splitlines() if log.exists() else [])
            if line.startswith("PYTHONPATH=")]


@pytest.mark.parametrize("image_mode", [True, False])
def test_the_nightly_is_installed_at_boot_and_put_on_the_apps_path(tmp_path, image_mode):
    """Installed under /data (a read-only /venv cannot take it, CR-84) and
    LAST on PYTHONPATH -- every PYTHONPATH entry is ahead of site-packages,
    so it shadows the pinned yt-dlp without getting a vote on where `app`,
    `musicweb` or `ytdlweb` come from. The RESOLVED versions/<v> directory,
    never the `current` pointer: a refresh while the app runs must not move
    files under a live import."""
    world = build_world(tmp_path, image_mode=image_mode, exits=["0"])
    proc = run(world, DASH_SITE_YOUTUBE_DOWNLOAD="1", STUB_NIGHTLY=NIGHTLY)
    assert proc.returncode == 0, proc.stderr
    root = world["data"] / "ytdlp-nightly"
    nightly_dir = f"{root.as_posix()}/versions/{NIGHTLY}"

    # The install runs in the BACKGROUND since its first live boot took 146 s
    # with the dashboard down for all of it (2026-10-05), so it may still be
    # finishing when run.sh's own stub app has exited.
    deadline = time.monotonic() + 15
    calls = []
    while time.monotonic() < deadline:
        calls = [c for c in world["log"].read_text().splitlines()
                 if c.startswith("NIGHTLY ")]
        if calls and (root / "current").exists():
            break
        time.sleep(0.2)
    assert len(calls) == 1, calls
    assert f"install root={root.as_posix()}" in calls[0]
    # the image's own module, with nothing but /ytdl-app on the path
    assert calls[0].endswith("PYTHONPATH=/ytdl-app"), calls[0]
    paths = _app_paths(world)
    assert paths, "the app was never started"
    # This boot did not wait for it: the app's path either has no nightly yet
    # or (if the background install won the race) the resolved directory.
    for line in paths:
        assert "current" not in line
        assert "ytdlp-nightly" not in line or line.endswith(f":{nightly_dir}"), line

    # The NEXT start imports it.
    proc = run(world, DASH_SITE_YOUTUBE_DOWNLOAD="1", STUB_NIGHTLY=NIGHTLY)
    assert proc.returncode == 0, proc.stderr
    last = _app_paths(world)[-1]
    assert last.endswith(f":{nightly_dir}"), last


def test_the_boot_never_waits_for_the_nightly_install(tmp_path):
    """2026-10-05: the first live boot waited 146 s on pip with the dashboard
    down. A slow install must not delay the app's start."""
    world = build_world(tmp_path, image_mode=True, exits=["0"])
    # run() returns only once the background install lets go of the output
    # pipe, so the proof is ORDER: the app started long before the slow
    # install wrote `current`.
    proc = run(world, timeout=90.0, DASH_SITE_YOUTUBE_DOWNLOAD="1",
               STUB_NIGHTLY=NIGHTLY, STUB_NIGHTLY_SLEEP="12")
    assert proc.returncode == 0, proc.stderr
    assert _app_paths(world), "the app was never started"
    current = world["data"] / "ytdlp-nightly" / "current"
    assert current.exists()
    started = world["app_pypath_log"].stat().st_mtime
    assert current.stat().st_mtime - started > 8, (started, current.stat().st_mtime)
    # and that boot ran without it
    assert "ytdlp-nightly" not in _app_paths(world)[0]


def test_no_youtube_signal_means_no_install_but_an_installed_nightly_still_counts(tmp_path):
    """The vendor build asks PyPI for nothing. A nightly the app's daily
    refresh staged earlier (a site that turned the downloader on from
    Settings, which sets no env var) is still what the next start imports."""
    world = build_world(tmp_path, image_mode=True, exits=["0"])
    root = world["data"] / "ytdlp-nightly"
    (root / "versions" / NIGHTLY / "yt_dlp").mkdir(parents=True)
    (root / "versions" / NIGHTLY / "yt_dlp" / "version.py").write_text("x\n")
    (root / "current").write_text(NIGHTLY + "\n")
    proc = run(world, DASH_SITE_YOUTUBE_DOWNLOAD="0", DASH_SITE_YOUTUBE_UNBLOCK="0")
    assert proc.returncode == 0, proc.stderr
    assert not any(c.startswith("NIGHTLY ")
                   for c in world["log"].read_text().splitlines())
    assert all(p.endswith(f"/versions/{NIGHTLY}") for p in _app_paths(world))


def test_the_switch_turns_it_all_off(tmp_path):
    world = build_world(tmp_path, image_mode=True, exits=["0"])
    root = world["data"] / "ytdlp-nightly"
    (root / "versions" / NIGHTLY / "yt_dlp").mkdir(parents=True)
    (root / "versions" / NIGHTLY / "yt_dlp" / "version.py").write_text("x\n")
    (root / "current").write_text(NIGHTLY + "\n")
    proc = run(world, DASH_SITE_YOUTUBE_DOWNLOAD="1", YTDL_YTDLP_NIGHTLY="0",
               STUB_NIGHTLY=NIGHTLY)
    assert proc.returncode == 0, proc.stderr
    assert not any(c.startswith("NIGHTLY ")
                   for c in world["log"].read_text().splitlines())
    assert not any("ytdlp-nightly" in p for p in _app_paths(world))


@pytest.mark.parametrize("pointer", ["../../etc", ".", "..", "2026.09.27/../x", "", "abc"])
def test_a_pointer_that_is_not_a_bare_version_is_ignored(tmp_path, pointer):
    world = build_world(tmp_path, image_mode=True, exits=["0"])
    root = world["data"] / "ytdlp-nightly"
    root.mkdir(parents=True)
    (root / "current").write_text(pointer + "\n")
    proc = run(world)
    assert proc.returncode == 0, proc.stderr
    assert not any("ytdlp-nightly" in p for p in _app_paths(world))


def test_a_pointer_to_a_missing_build_is_ignored(tmp_path):
    """`current` naming a directory that is not there (or holds no yt_dlp)
    must leave the app on the pinned copy, not on an empty path entry."""
    world = build_world(tmp_path, image_mode=True, exits=["0"])
    root = world["data"] / "ytdlp-nightly"
    root.mkdir(parents=True)
    (root / "current").write_text(NIGHTLY + "\n")
    proc = run(world)
    assert proc.returncode == 0, proc.stderr
    assert not any("ytdlp-nightly" in p for p in _app_paths(world))
    assert not any(p.endswith(":") or "::" in p for p in _app_paths(world))


def test_a_failed_nightly_install_never_stops_the_boot(tmp_path):
    world = build_world(tmp_path, image_mode=True, exits=["0"])
    proc = run(world, DASH_SITE_YOUTUBE_DOWNLOAD="1", STUB_NIGHTLY_EXIT="1")
    assert proc.returncode == 0, proc.stderr
    assert _app_paths(world), "the app must still start on the pinned yt-dlp"
    assert not any("ytdlp-nightly" in p for p in _app_paths(world))


def test_an_exit_75_restart_picks_up_a_nightly_staged_while_the_app_ran(tmp_path):
    """The restart semantics, end to end: the running app's daily refresh
    moves `current`; the app is NOT restarted for it; the next start the
    loop makes (an OTA's exit 75 here) imports the new build."""
    world = build_world(tmp_path, image_mode=True, exits=["75", "0"])
    root = world["data"] / "ytdlp-nightly"
    newer = "2026.10.04.232901"
    (tmp_path / "launch_hook.sh").write_text(
        f'mkdir -p "{root.as_posix()}/versions/{newer}/yt_dlp"\n'
        f'echo x > "{root.as_posix()}/versions/{newer}/yt_dlp/version.py"\n'
        f'echo {newer} > "{root.as_posix()}/current"\n',
        encoding="utf-8", newline="\n")
    proc = run(world, DASH_SITE_YOUTUBE_DOWNLOAD="1", STUB_NIGHTLY=NIGHTLY)
    assert proc.returncode == 0, proc.stderr
    paths = _app_paths(world)
    assert len(paths) == 2, paths
    assert paths[0].endswith(f"/versions/{NIGHTLY}"), paths[0]
    assert paths[1].endswith(f"/versions/{newer}"), paths[1]
