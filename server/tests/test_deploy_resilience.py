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
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import install_dashboard_app as ida  # noqa: E402

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

    assert "find /tmp" in sent["cmd"] and ida.STAGING_GLOB in sent["cmd"]
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


def test_a_staging_dir_outside_the_parent_we_asked_for_is_refused(monkeypatch):
    """mktemp's answer is what everything below cp -a's from, as root."""
    monkeypatch.setattr(ida, "run_ssh",
                        lambda *a, **k: (0, "/etc\n", ""))
    with pytest.raises(SystemExit):
        ida.make_staging_dir(False, "ccsync-musicdb-upload", "/mnt/tank/x/staging")


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
