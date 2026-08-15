"""What a dashboard deploy does when a step FAILS, and what it costs when it
does not.

The install script's happy path is covered by test_safety.py and
test_music_deploy.py. This file covers the four ops findings of 2026-08-11,
all of which are about the deploy's behaviour AROUND the staged-verify-swap
rather than inside it:

  OPS-2  a deploy that fails after the `app` swap left the container serving
         the inode that is now app.old.<ts>; two runs later the prune deleted
         it out from under the live dashboard.
  OPS-3  the 1.4 GB music trees were staged, verified and swapped under
         run_ssh's 120 s default channel timeout, and a socket.timeout
         escaped main() as a traceback.
  OPS-5  the --music-data auto presence probe ran unprivileged, so the index
         was re-pushed over the live one on EVERY deploy.
  OPS-8  1.4 GB of staging left in the NAS's (possibly RAM-backed) /tmp per
         failed attempt.

Everything is offline: the shell-level tests run the generated scripts against
temp directories, and the install-path tests drive main() in --dry-run with a
recording fake in place of run_ssh, so no NAS is touched.

Run with:
    cd E:\\Projects\\resolve-remote-sync\\server
    python -m pytest tests -q
"""
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import install_dashboard_app as ida  # noqa: E402

# The same minimal requests.Response stand-in the rest of the suite uses; the
# API-shaped findings of 2026-08-14 need it here too.
from test_safety import _Resp  # noqa: E402

BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="a POSIX shell is required")


def _run_sh(script: str, workdir: Path):
    return subprocess.run([BASH, "-c", script], cwd=str(workdir),
                          capture_output=True, text=True, timeout=60)


def _seed_backups(base: Path, *stamps: str) -> None:
    """<base>/app plus one <base>/app.old.<stamp> per stamp.

    Callers drive the script with paths RELATIVE to tmp_path: the prune globs
    (`ls -1d <target>.old.*`), and a Windows drive path with backslashes in it
    is not something MSYS bash can expand -- the shape being tested is the
    globbing and the word splitting, neither of which cares.
    """
    (base / "app").mkdir(parents=True)
    for stamp in stamps:
        old = base / f"app.old.{stamp}"
        old.mkdir()
        (old / "marker").write_text(stamp, encoding="utf-8")


# --------------------------------------------------------------------------
# OPS-2 -- the prune must not delete code a container is still reading
# --------------------------------------------------------------------------

@needs_bash
def test_prune_keeps_the_most_recent_backup_and_deletes_the_rest(tmp_path):
    _seed_backups(tmp_path, "20260810120000", "20260811090000")
    # a mountinfo glob that matches nothing: the ordinary case
    script = ida.build_prune_script("app", "no-such/*/mountinfo")
    proc = _run_sh(script, tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "app.old.20260810120000").exists()
    assert (tmp_path / "app.old.20260811090000").exists(), "the copy of the code we just replaced"


@needs_bash
def test_prune_skips_a_backup_a_container_still_has_bind_mounted(tmp_path):
    """OPS-2: the swap changes app/'s inode and a bind mount follows the
    directory, so after a deploy that failed before the restart the LIVE
    dashboard is reading app.old.<ts>. rm -rf'ing it 500s every page."""
    _seed_backups(tmp_path, "20260809120000", "20260810120000", "20260811090000")
    mountinfo = tmp_path / "proc" / "1" / "mountinfo"
    mountinfo.parent.mkdir(parents=True)
    mountinfo.write_text(
        "846 66 0:24 /apps/ccsync-dashboard/app.old.20260809120000 /app ro,relatime\n",
        encoding="utf-8")
    script = ida.build_prune_script("app", "proc/*/mountinfo")
    proc = _run_sh(script, tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "app.old.20260809120000").exists(), "the LIVE code was pruned"
    assert "still bind-mounted" in proc.stderr
    # the one that is neither newest nor mounted still goes
    assert not (tmp_path / "app.old.20260810120000").exists()
    assert (tmp_path / "app.old.20260811090000").exists()


@needs_bash
def test_prune_survives_a_space_in_the_host_root(tmp_path):
    """HOST_ROOT_RE permits a space; word splitting on one would hand rm -rf
    path fragments (the reason the old prune used xargs -d '\\n')."""
    root = tmp_path / "host root"
    _seed_backups(root, "20260810120000", "20260811090000")
    script = ida.build_prune_script("host root/app", "nope/*/mountinfo")
    proc = _run_sh(script, tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert not (root / "app.old.20260810120000").exists()
    assert (root / "app.old.20260811090000").exists()


def test_a_failure_after_the_app_swap_restarts_the_container(monkeypatch, capsys):
    """The whole point: the container must not be left on the previous code
    directory, because the NEXT deploy's prune deletes it."""
    seen = []
    monkeypatch.setattr(ida, "run_ssh",
                        lambda cmd, dry_run=False, timeout=120: (seen.append(cmd), (0, "", ""))[1])
    assert ida.fail_after_app_swap(False) == 1
    assert any("docker restart" in c and f"ix-{ida.APP_NAME}-dashboard-1" in c
               for c in seen)
    assert "restarted the container" in capsys.readouterr().out


def test_a_failed_restart_after_the_swap_says_what_the_operator_must_do(monkeypatch,
                                                                       capsys):
    monkeypatch.setattr(ida, "run_ssh",
                        lambda *a, **k: (1, "", "No such container"))
    assert ida.fail_after_app_swap(False) == 1
    err = capsys.readouterr().err
    assert "PREVIOUS code" in err and "next deploy" in err


# --------------------------------------------------------------------------
# OPS-3 -- the timeout has to scale with what is being pushed
# --------------------------------------------------------------------------

def test_the_timeout_floor_covers_the_small_code_trees():
    assert ida.tree_ssh_timeout(0) == ida.MIN_TREE_SSH_TIMEOUT
    assert ida.tree_ssh_timeout(1_000_000) == ida.MIN_TREE_SSH_TIMEOUT


def test_the_timeout_scales_past_the_default_for_the_music_artefacts():
    """906 MB of proxies through cp -a + chown -R + a full re-read is not a
    120 s job, and run_ssh's default is an INACTIVITY timeout, so silence
    while it works reads as a dead channel."""
    proxies = ida.tree_ssh_timeout(906 * 1024 * 1024)
    encoder = ida.tree_ssh_timeout(482 * 1024 * 1024)
    assert proxies > 600 and encoder > 300
    assert proxies > encoder


def test_a_dropped_transport_is_an_error_result_not_a_traceback(monkeypatch):
    """It used to escape main() unhandled: the container was never restarted
    and the deploy stopped between the two halves of the swap (OPS-2)."""
    def boom(cmd, dry_run=False, timeout=120):
        raise socket.timeout("timed out")

    monkeypatch.setattr(ida, "run_ssh", boom)
    rc, out, err = ida.run_ssh_guarded("true", False, 300)
    assert rc != 0 and out == ""
    assert "SSH channel dropped" in err and "timeout" in err.lower()


def test_install_tree_gives_every_remote_step_the_size_derived_timeout(monkeypatch,
                                                                      tmp_path):
    source = tmp_path / "tree"
    source.mkdir()
    (source / "a.bin").write_bytes(b"x" * 4096)
    timeouts = []

    def record(cmd, dry_run=False, timeout=120):
        timeouts.append(timeout)
        # the verify's two lines: file count, then total bytes
        return 0, "1\n4096\n", ""

    monkeypatch.setattr(ida, "run_ssh", record)
    monkeypatch.setattr(ida, "make_staging_dir",
                        lambda dry_run, slug="s", parent="/tmp": f"{parent}/{slug}.abc123")
    monkeypatch.setattr(ida, "upload_tree", lambda *a, **k: 1)

    assert ida.install_tree("/mnt/tank/apps/ccsync-dashboard", "app", source, False)
    assert timeouts, "no remote step ran"
    assert all(t >= ida.MIN_TREE_SSH_TIMEOUT for t in timeouts), timeouts


# --------------------------------------------------------------------------
# OPS-5 -- the presence probe has to be able to SEE the music data root
# --------------------------------------------------------------------------

def test_the_presence_probe_runs_privileged(monkeypatch):
    """music-data is 3000:3000 mode 770 and TRUENAS_USER cannot traverse it,
    so an unprivileged probe reported `db no` every time and re-pushed the
    index over the live one on every routine ship."""
    sent = {}

    def fake_run_ssh(cmd, dry_run=False, timeout=120):
        sent["cmd"] = cmd
        return 0, "db yes\nencoder yes\nproxies yes\n", ""

    monkeypatch.setattr(ida, "run_ssh", fake_run_ssh)
    present = ida.music_components_present("/mnt/tank/apps/ccsync-dashboard", False)

    assert present == {"db": True, "encoder": True, "proxies": True}
    assert 'echo "$SUDO_PW" | sudo -S' in sent["cmd"]


def test_an_unreadable_path_counts_as_absent_not_present(monkeypatch):
    """The masking `|| echo x` turned a permission error into "present" and
    skipped a push that was needed. Re-pushing is the safe direction."""
    sent = {}

    def fake_run_ssh(cmd, dry_run=False, timeout=120):
        sent["cmd"] = cmd
        return 0, "db no\nencoder no\nproxies no\n", ""

    monkeypatch.setattr(ida, "run_ssh", fake_run_ssh)
    ida.music_components_present("/r", False)
    assert "echo x" not in sent["cmd"]


# --------------------------------------------------------------------------
# OPS-8 -- 1.4 GB of staging must not pile up in the NAS's /tmp
# --------------------------------------------------------------------------

def test_orphaned_staging_is_reclaimed_before_this_run_adds_its_own(monkeypatch,
                                                                   capsys):
    sent = {}

    def fake_run_ssh(cmd, dry_run=False, timeout=120):
        sent["cmd"] = cmd
        return 0, "/tmp/ccsync-musicproxies-upload.AbC123\n", ""

    monkeypatch.setattr(ida, "run_ssh", fake_run_ssh)
    ida.prune_orphaned_staging(False)

    assert "'/tmp'" in sent["cmd"] and ida.STAGING_GLOB in sent["cmd"]
    # only debris: anything younger than the cutoff could belong to this run
    assert f"-mmin +{ida.STAGING_ORPHAN_MINUTES}" in sent["cmd"]
    assert "sudo" not in sent["cmd"], "the staging dirs belong to the SSH user"
    assert "reclaimed 1 orphaned staging dir" in capsys.readouterr().out


def test_reclaiming_staging_is_never_fatal(monkeypatch, capsys):
    monkeypatch.setattr(ida, "run_ssh", lambda *a, **k: (1, "", "find: no /tmp"))
    ida.prune_orphaned_staging(False)  # must not raise
    assert "reclaimed" not in capsys.readouterr().out


def test_staging_can_be_asked_for_somewhere_other_than_tmp(monkeypatch):
    root = "/mnt/tank/apps/ccsync-dashboard/staging"
    monkeypatch.setattr(
        ida, "run_ssh",
        lambda cmd, dry_run=False, timeout=120: (0, f"{root}/ccsync-musicproxies-upload.XyZ\n", ""))
    got = ida.make_staging_dir(False, "ccsync-musicproxies-upload", root)
    assert got.startswith(root + "/")


def test_a_staging_dir_outside_the_parent_we_asked_for_is_refused(monkeypatch, capsys):
    """mktemp's answer is what everything below cp -a's from, as root.

    SERVER-8 (2026-08-14): the refusal is a "" RESULT, not sys.exit(1) -- this
    is reached from steps 2b/2c/2d/2f, i.e. after the `app` swap, where an exit
    walks past fail_after_app_swap's container restart.
    """
    monkeypatch.setattr(ida, "run_ssh",
                        lambda *a, **k: (0, "/etc\n", ""))
    assert ida.make_staging_dir(False, "ccsync-musicdb-upload",
                                "/mnt/tank/x/staging") == ""
    assert "FAILED to create staging dir" in capsys.readouterr().err


# --------------------------------------------------------------------------
# The whole deploy, in --dry-run, against a recording fake
# --------------------------------------------------------------------------

def _dry_run(monkeypatch, capsys, cmds, extra_argv=()):
    def record(cmd, dry_run=False, timeout=120):
        cmds.append(cmd)
        return 0, "", ""

    for name, value in (("SYNCTHING_API_KEY", "k"), ("DASH_REPORT_TOKEN", "t"),
                        ("DASH_SESSION_SECRET", "s"), ("TRUENAS_PW", "pw"),
                        ("BROLL_INGEST_TOKEN", "ingestTOKENsentinel4b7d1e9a03c6")):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(ida, "run_ssh", record)
    monkeypatch.setattr(sys, "argv", ["install_dashboard_app.py", "--dry-run",
                                      *extra_argv])
    rc = ida.main()
    captured = capsys.readouterr()
    return rc, "\n".join([captured.out, captured.err, *cmds])


def _real_run(monkeypatch, capsys, cmds, extra_argv=("--music-data", "none")):
    """main() WITHOUT --dry-run, against fakes for everything that leaves the
    process. --dry-run returns at the compose body (that is the point of it),
    so the step-3 findings of 2026-08-14 -- the create job nobody waits on
    (SERVER-2) and the queries that used to sys.exit past the container restart
    (SERVER-8) -- are only reachable from a real run. Nothing here opens a
    socket: run_ssh, the tree installs and both binary-provisioning steps are
    stubbed, and the caller supplies truenas_api/app_installed.
    """
    def record(cmd, dry_run=False, timeout=120):
        cmds.append(cmd)
        return 0, "", ""

    for name, value in (("SYNCTHING_API_KEY", "k"), ("DASH_REPORT_TOKEN", "t"),
                        ("DASH_SESSION_SECRET", "s"), ("TRUENAS_PW", "pw"),
                        ("BROLL_INGEST_TOKEN", "ingestTOKENsentinel4b7d1e9a03c6")):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(ida, "run_ssh", record)
    monkeypatch.setattr(ida, "install_tree", lambda *a, **k: True)
    monkeypatch.setattr(ida, "provision_ffmpeg", lambda *a, **k: None)
    monkeypatch.setattr(ida, "provision_ytdl_binaries", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["install_dashboard_app.py", *extra_argv])
    rc = ida.main()
    captured = capsys.readouterr()
    return rc, "\n".join([captured.out, captured.err, *cmds])


def test_a_deploy_prepares_a_staging_root_on_the_same_pool(monkeypatch, capsys):
    cmds: list = []
    rc, transcript = _dry_run(monkeypatch, capsys, cmds)
    assert rc == 0
    assert any("/staging" in c and "chmod 700" in c for c in cmds), \
        "the music artefacts would be staged in a possibly RAM-backed /tmp"
    assert "ccsync-*-upload.*" in transcript, "orphaned staging is never reclaimed"


def test_a_failed_music_push_restarts_the_container_before_returning(monkeypatch,
                                                                    capsys):
    """OPS-2 end to end: the app tree is in, the music data push (the newest,
    least-proven step) fails, and the container must not be left on the
    directory the next deploy will prune."""
    cmds: list = []
    real_install_tree = ida.install_tree

    def fail_on_music(root, target_name, source, dry_run, **kw):
        if target_name.startswith("music"):
            return False
        return real_install_tree(root, target_name, source, dry_run, **kw)

    monkeypatch.setattr(ida, "install_tree", fail_on_music)
    rc, transcript = _dry_run(monkeypatch, capsys, cmds)

    assert rc == 1
    assert any("docker restart" in c for c in cmds), \
        "the container was left serving the previous code directory"


# --------------------------------------------------------------------------
# The 2026-08-14 bug hunt: the same four questions, asked of the halves of
# the deploy that OPS-2/3/5/8 did not reach.
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# SERVER-1 -- the SFTP is the longest-lived step and had no error path at all
# --------------------------------------------------------------------------

class _Boom(Exception):
    """Stands in for paramiko.SSHException / socket.timeout out of sftp.put."""


def _seed_tree(tmp_path: Path) -> Path:
    source = tmp_path / "tree"
    source.mkdir()
    (source / "a.bin").write_bytes(b"x" * 4096)
    return source


def test_a_dropped_sftp_is_a_failure_result_not_a_traceback(monkeypatch, tmp_path,
                                                            capsys):
    """906 MB of proxies is the likeliest place in the whole script for the
    transport to go, and it was the only major step with no `except`."""
    monkeypatch.setenv("TRUENAS_PW", "pw")

    def boom(*a, **k):
        raise _Boom("Server connection dropped")

    monkeypatch.setattr(ida, "ssh_client", boom)
    assert ida.upload_tree("/tmp/ccsync-musicproxies-upload.AbC",
                           False, _seed_tree(tmp_path)) == -1
    err = capsys.readouterr().err
    assert "SFTP transfer" in err and "_Boom" in err
    # the operator is told where the debris is, like every other failure here
    assert "ccsync-musicproxies-upload.AbC" in err


def test_install_tree_refuses_after_a_dropped_sftp_and_moves_nothing(monkeypatch,
                                                                     tmp_path,
                                                                     capsys):
    """The exact OPS-2 precondition: this runs after `mv app app.old.<ts>`, so
    an escaping exception skips fail_after_app_swap and the container is never
    restarted. A False return is what every call site already routes."""
    cmds: list = []

    def record(cmd, dry_run=False, timeout=120):
        cmds.append(cmd)
        return 0, "1\n4096\n", ""

    monkeypatch.setattr(ida, "run_ssh", record)
    monkeypatch.setattr(ida, "make_staging_dir",
                        lambda dry_run, slug="s", parent="/tmp": f"{parent}/{slug}.abc")
    monkeypatch.setattr(ida, "upload_tree", lambda *a, **k: -1)

    assert ida.install_tree("/mnt/tank/apps/ccsync-dashboard", "music-proxies",
                            _seed_tree(tmp_path), False) is False
    assert not any("sudo" in c for c in cmds), "the swap ran on a broken upload"
    assert "untouched" in capsys.readouterr().err


def test_the_restart_that_ends_the_exposure_survives_a_dropped_transport(monkeypatch,
                                                                         capsys):
    """fail_after_app_swap calls the restart ON a failure path. If the drop
    that caused the failure also raises out of `docker restart`, the fix for
    OPS-2 becomes the traceback OPS-2 was."""
    def boom(cmd, dry_run=False, timeout=120):
        raise _Boom("Socket is closed")

    monkeypatch.setattr(ida, "run_ssh", boom)
    assert ida.fail_after_app_swap(False) == 1
    err = capsys.readouterr().err
    assert "PREVIOUS code" in err and "next deploy" in err


def test_the_transfer_guard_covers_the_whole_client_not_just_the_put(monkeypatch,
                                                                    tmp_path):
    """ssh_client() itself raises on a refused/timed-out connect, which is the
    same answer -- it must not escape either."""
    monkeypatch.setenv("TRUENAS_PW", "pw")

    class _Client:
        def open_sftp(self):
            raise _Boom("channel open failed")

        def close(self):
            pass

    monkeypatch.setattr(ida, "ssh_client", lambda *a, **k: _Client())
    assert ida.upload_tree("/tmp/s", False, _seed_tree(tmp_path)) == -1


# --------------------------------------------------------------------------
# SERVER-5 -- the sweep must look where the 1.4 GB actually stages
# --------------------------------------------------------------------------

def test_the_sweep_covers_both_staging_parents(monkeypatch):
    """OPS-8 moved the music pushes to <host-root>/staging and left the reclaim
    pointed at /tmp, so it ran against the location the big pushes no longer
    use and never against the one they do. Nothing else in this repo deletes
    those dirs."""
    sent = {}

    def fake_run_ssh(cmd, dry_run=False, timeout=120):
        sent["cmd"] = cmd
        return 0, "", ""

    monkeypatch.setattr(ida, "run_ssh", fake_run_ssh)
    ida.prune_orphaned_staging(False, ("/tmp", "/mnt/tank/apps/ccsync-dashboard/staging"))

    assert "'/tmp'" in sent["cmd"]
    assert "'/mnt/tank/apps/ccsync-dashboard/staging'" in sent["cmd"]
    assert sent["cmd"].count("find") == 2
    assert "sudo" not in sent["cmd"], "the staging dirs belong to the SSH user"


def test_a_parent_that_does_not_exist_does_not_break_the_sweep(monkeypatch, capsys,
                                                               tmp_path):
    """<host-root>/staging is created lazily, so on a first install it is not
    there -- and a `find` on a missing dir must not cost the /tmp half."""
    sent = {}

    def fake_run_ssh(cmd, dry_run=False, timeout=120):
        sent["cmd"] = cmd
        return 0, "", ""

    monkeypatch.setattr(ida, "run_ssh", fake_run_ssh)
    ida.prune_orphaned_staging(False, ("/tmp", str(tmp_path / "nope")))
    assert '[ -d "$d" ]' in sent["cmd"]


@needs_bash
def test_the_sweep_deletes_only_old_staging_dirs(tmp_path):
    """Run the generated shell for real: the glob and the age cutoff decide
    what a root-owned 906 MB dir on the pool loses."""
    parent = tmp_path / "staging"
    parent.mkdir()
    old = parent / "ccsync-musicproxies-upload.AbC123"
    old.mkdir()
    (old / "big").write_bytes(b"x" * 16)
    young = parent / "ccsync-musicdb-upload.XyZ789"
    young.mkdir()
    keep = parent / "not-ours"
    keep.mkdir()
    # backdate the orphan past the cutoff; utime touches mtime, which -mmin reads
    stale = os.path.getmtime(old) - (ida.STAGING_ORPHAN_MINUTES + 60) * 60
    os.utime(old, (stale, stale))

    sent = {}

    def fake_run_ssh(cmd, dry_run=False, timeout=120):
        sent["cmd"] = cmd
        return 0, "", ""

    ida_run_ssh = ida.run_ssh
    try:
        ida.run_ssh = fake_run_ssh
        ida.prune_orphaned_staging(False, (str(parent),))
    finally:
        ida.run_ssh = ida_run_ssh

    proc = _run_sh(sent["cmd"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert not old.exists(), "the orphan survived"
    assert young.exists(), "a dir that could belong to THIS run was deleted"
    assert keep.exists(), "the glob is not ours to widen"


def test_a_deploy_sweeps_the_host_root_staging_parent(monkeypatch, capsys):
    cmds: list = []
    rc, _transcript = _dry_run(monkeypatch, capsys, cmds)
    assert rc == 0
    prunes = [c for c in cmds if ida.STAGING_GLOB in c]
    assert prunes, "nothing reclaims orphaned staging"
    assert any(f"{ida.DEFAULT_HOST_ROOT}/staging" in c for c in prunes), \
        "the ~900 MB-per-retry parent is never swept"


# --------------------------------------------------------------------------
# SERVER-6 -- verifying two integers must not re-read 906 MB to do it
# --------------------------------------------------------------------------

def test_the_verify_reads_metadata_not_every_shipped_byte():
    cmd = ida.count_and_size_cmd("/mnt/tank/apps/ccsync-dashboard/music-proxies")
    assert "-exec cat" not in cmd, "the whole tree is being re-read to size it"
    assert "-printf '%s" in cmd


def test_the_candidate_tree_is_sized_the_same_cheap_way():
    """It ran TWICE per tree -- once on staging, once inside the swap script."""
    swap = ida.build_swap_script("/r", "/tmp/s", "/r/music-proxies.new",
                                 "/r/music-proxies.old.20260810120000", 3, 99,
                                 target_dir="/r/music-proxies")
    assert "-exec cat" not in swap
    assert "-printf '%s" in swap


@needs_bash
def test_the_metadata_size_agrees_with_the_local_manifest(tmp_path):
    """The numbers still have to be the SAME two numbers: a transfer that wrote
    every file but truncated the last one must still fail the check."""
    tree = tmp_path / "tree"
    (tree / "sub").mkdir(parents=True)
    (tree / "a.bin").write_bytes(b"x" * 4096)
    (tree / "sub" / "b.bin").write_bytes(b"y" * 7)
    (tree / "sub" / "empty.bin").write_bytes(b"")
    count, size = ida.local_manifest(tree, ida.EXCLUDE_DIRS)

    proc = _run_sh(ida.count_and_size_cmd(str(tree)), tmp_path)
    assert proc.returncode == 0, proc.stderr
    nums = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip().isdigit()]
    assert [int(nums[0]), int(nums[1])] == [count, size]


# --------------------------------------------------------------------------
# SERVER-8 -- no post-swap path may sys.exit past fail_after_app_swap
# --------------------------------------------------------------------------

def test_a_failed_mktemp_is_a_result_and_uploads_nothing(monkeypatch, tmp_path,
                                                         capsys):
    """An empty staging path reaching upload_tree would SFTP into relative
    paths, i.e. the SSH user's home, so it must stop before that."""
    monkeypatch.setattr(ida, "run_ssh", lambda *a, **k: (1, "", "No space left"))
    monkeypatch.setattr(ida, "upload_tree",
                        lambda *a, **k: pytest.fail("uploaded with no staging dir"))

    assert ida.install_tree("/mnt/tank/apps/ccsync-dashboard", "music-proxies",
                            _seed_tree(tmp_path), False) is False
    assert "no staging dir" in capsys.readouterr().err


def test_a_failed_mktemp_does_not_kill_the_optional_binary_steps(monkeypatch):
    """provision_ffmpeg promises "NON-FATAL throughout"; a sys.exit inside
    make_staging_dir made that untrue for the LAN push."""
    monkeypatch.setattr(ida, "make_staging_dir", lambda *a, **k: "")
    ok_, err = ida.install_ffmpeg_over_lan("/r", None, "d" * 64, False)
    assert ok_ is False and "staging" in err


def test_an_unanswerable_app_query_is_not_an_exit(monkeypatch, capsys):
    """app_installed runs in step 3, after the swap. sys.exit(1) there left the
    container on app.old.<ts> with no restart and no NOTE."""
    monkeypatch.setattr(ida, "truenas_api",
                        lambda *a, **k: _Resp(500, text="middleware error"))
    assert ida.app_installed(False) is None
    assert "FAILED to query installed apps" in capsys.readouterr().err


def test_a_step_3_query_failure_restarts_the_container(monkeypatch, capsys):
    cmds: list = []
    monkeypatch.setattr(ida, "app_installed", lambda dry_run: None)
    rc, _transcript = _real_run(monkeypatch, capsys, cmds)
    assert rc == 1
    assert any("docker restart" in c for c in cmds), \
        "the container was left serving the previous code directory"


# --------------------------------------------------------------------------
# SERVER-2 -- POST /app returns a JOB ID, not a finished install
# --------------------------------------------------------------------------

def test_the_create_job_is_waited_on_and_a_failed_one_fails_the_deploy(monkeypatch,
                                                                       capsys):
    """A stale --bind-lan makes Docker refuse to start the app with "cannot
    assign requested address" -- asynchronously, long after the 200 on the
    POST. Printing "installed custom app" and exiting 0 for that is the
    exit-code-lies class of OPS-4."""
    cmds: list = []
    waited = {}

    def fake_wait(job_id, timeout=900, poll=5):
        waited["job_id"] = job_id
        return "FAILED", "cannot assign requested address"

    monkeypatch.setattr(ida, "app_installed", lambda dry_run: False)
    monkeypatch.setattr(ida, "wait_for_job", fake_wait)
    monkeypatch.setattr(ida, "truenas_api",
                        lambda method, path, **k: _Resp(200, payload=4242))

    rc, transcript = _real_run(monkeypatch, capsys, cmds)
    assert rc == 1
    assert waited["job_id"] == 4242
    assert "installed custom app" not in transcript
    assert "cannot assign requested address" in transcript


def test_a_successful_create_job_still_reports_success(monkeypatch, capsys):
    cmds: list = []
    monkeypatch.setattr(ida, "app_installed", lambda dry_run: False)
    monkeypatch.setattr(ida, "wait_for_job", lambda *a, **k: ("SUCCESS", ""))
    monkeypatch.setattr(ida, "truenas_api",
                        lambda method, path, **k: _Resp(200, payload=7))

    rc, transcript = _real_run(monkeypatch, capsys, cmds)
    assert rc == 0
    assert "installed custom app" in transcript


def test_a_create_with_no_job_id_says_it_could_not_be_waited_on(monkeypatch, capsys):
    """The middleware's answer shape is ASSUMED here; saying so out loud is
    what install_syncthing_app already does."""
    cmds: list = []
    monkeypatch.setattr(ida, "app_installed", lambda dry_run: False)
    monkeypatch.setattr(ida, "wait_for_job",
                        lambda *a, **k: pytest.fail("nothing to wait on"))
    monkeypatch.setattr(ida, "truenas_api",
                        lambda method, path, **k: _Resp(200, payload={"result": None}))

    rc, transcript = _real_run(monkeypatch, capsys, cmds)
    assert rc == 0
    assert "could not be waited on" in transcript
