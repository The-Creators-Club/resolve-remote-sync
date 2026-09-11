"""Regression tests for the 2026-09-11 bug hunt, server-tools territory
(CR-247): the NAS-side deploy in server/install_dashboard_app.py.

server-tools-4: install_tree walked the source tree a SECOND time after the
upload and verified the staged copy against that later snapshot, so a file
created or removed under dashboard/ mid-transfer aborted a finished SFTP.
The suite found it before an operator did: two test_music_deploy tests failed
with "internal manifest mismatch (297 vs 296)" on one run of the full server
suite and passed on the next.

server-tools-3: `.zfs/snapshot` is an automount root, and a docker bind is
rprivate, so a snapshot first traversed after the container started mounts on
the HOST and the container keeps seeing an empty trigger directory.

Offline, like the rest of this suite; run from GIT BASH (see CLAUDE.md).

    cd E:\\Projects\\resolve-remote-sync\\server
    ../dashboard/.venv/Scripts/python.exe -m pytest \\
        tests/test_bug_hunt_2026_09_11_server_tools.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import install_dashboard_app as ida  # noqa: E402

HOST_ROOT = "/mnt/tank/apps/ccsync-dashboard"


# --------------------------------------------------------------------------
# server-tools-4: one walk, and the upload sends exactly it
# --------------------------------------------------------------------------

class _Attrs:
    def __init__(self, size):
        self.st_size = size


class _Sftp:
    """A fake SFTP channel that writes the files it is given into a dict, and
    optionally lets a hook run after each put -- which is how "an editor saved
    a file under dashboard/ while the deploy was uploading" is reproduced."""

    def __init__(self, after_put=None):
        self.landed: dict[str, bytes] = {}
        self.after_put = after_put

    def stat(self, path):
        raise FileNotFoundError(path)

    def mkdir(self, path):
        return None

    def put(self, local, remote):
        data = Path(local).read_bytes()
        self.landed[remote] = data
        if self.after_put:
            self.after_put()
        return _Attrs(len(data))

    def close(self):
        return None


class _Client:
    def __init__(self, sftp):
        self._sftp = sftp

    def open_sftp(self):
        return self._sftp

    def close(self):
        return None


class _Backend:
    dashboard_container = "ccsync-dashboard"

    def sftp_path(self, path):
        return path


def _wire(monkeypatch, sftp, calls):
    """install_tree with the NAS replaced by `sftp`: the staged-tree check is
    answered with WHAT ACTUALLY LANDED, which is the whole point -- a test that
    answered with a fresh local walk would mock away the defect."""
    monkeypatch.setattr(ida, "make_staging_dir",
                        lambda *a, **kw: "/tmp/ccsync-dashboard-upload.AbC")
    monkeypatch.setattr(ida, "truenas_conn_params", lambda: ("h", "u", "pw"))
    monkeypatch.setattr(ida, "ssh_client", lambda *a, **kw: _Client(sftp))
    monkeypatch.setattr(ida, "backend", lambda: _Backend())

    def fake_ssh(cmd, dry_run, timeout=None, *a, **kw):
        calls.append(cmd)
        if cmd.startswith('echo "$SUDO_PW"'):
            return 0, "", ""
        total = sum(len(v) for v in sftp.landed.values())
        return 0, f"{len(sftp.landed)}\n{total}\n", ""

    monkeypatch.setattr(ida, "run_ssh_guarded", fake_ssh)


def _seed(tmp_path: Path) -> Path:
    source = tmp_path / "dashboard"
    (source / "src").mkdir(parents=True)
    (source / "src" / "main.py").write_text("app = 1\n", encoding="utf-8")
    (source / "schema.sql").write_text("-- schema\n", encoding="utf-8")
    return source


def test_a_file_appearing_under_the_source_does_not_abort_a_finished_upload(
        monkeypatch, tmp_path, capsys):
    """An editor saving, a build, a stray tool: anything that adds a file to
    dashboard/ while the SFTP is running used to abort the deploy after the
    whole transfer with "internal manifest mismatch", because the manifest was
    taken afterwards and described a tree that was never uploaded."""
    source = _seed(tmp_path)
    state = {"n": 0}

    def an_editor_saves():
        state["n"] += 1
        if state["n"] == 1:
            (source / "src" / "notes.py").write_text("x = 1\n", encoding="utf-8")

    sftp = _Sftp(after_put=an_editor_saves)
    calls: list = []
    _wire(monkeypatch, sftp, calls)

    ok = ida.install_tree(HOST_ROOT, "app", source, False)
    out = capsys.readouterr()
    assert ok, out.err
    assert "internal manifest mismatch" not in out.err
    assert "staged tree does not match" not in out.err
    # The tree that went up is the tree that was measured: the late file is
    # simply not in this deploy, and the next one carries it.
    assert len(sftp.landed) == 2


def test_a_file_removed_under_the_source_does_not_abort_it_either(
        monkeypatch, tmp_path, capsys):
    source = _seed(tmp_path)
    victim = source / "schema.sql"
    removed = {"done": False}

    def something_cleans_up():
        if not removed["done"] and victim.exists():
            victim.unlink()
            removed["done"] = True

    sftp = _Sftp(after_put=something_cleans_up)
    calls: list = []
    _wire(monkeypatch, sftp, calls)

    ok = ida.install_tree(HOST_ROOT, "app", source, False)
    out = capsys.readouterr()
    assert ok, out.err
    assert "manifest" not in out.err


def test_the_byte_total_is_what_the_nas_confirmed_not_a_later_local_stat(
        monkeypatch, tmp_path, capsys):
    """A file rewritten under us is compared as the bytes that arrived."""
    source = _seed(tmp_path)
    grown = source / "schema.sql"

    def rewrite_it():
        grown.write_text("-- schema, much longer now\n" * 50, encoding="utf-8")

    sftp = _Sftp(after_put=rewrite_it)
    calls: list = []
    _wire(monkeypatch, sftp, calls)

    ok = ida.install_tree(HOST_ROOT, "app", source, False)
    assert ok, capsys.readouterr().err
    landed = sum(len(v) for v in sftp.landed.values())
    # the swap script is verified against the same numbers
    swap = [c for c in calls if c.startswith('echo "$SUDO_PW"')][0]
    assert str(landed) in swap


def test_upload_tree_reports_what_it_sent(monkeypatch, tmp_path):
    source = _seed(tmp_path)
    sftp = _Sftp()
    monkeypatch.setattr(ida, "truenas_conn_params", lambda: ("h", "u", "pw"))
    monkeypatch.setattr(ida, "ssh_client", lambda *a, **kw: _Client(sftp))
    monkeypatch.setattr(ida, "backend", lambda: _Backend())
    sent: dict = {}
    n = ida.upload_tree("/tmp/stage", False, source, ida.EXCLUDE_DIRS, sent=sent)
    assert n == 2
    assert sent["count"] == 2
    assert sent["bytes"] == sum(len(v) for v in sftp.landed.values())


def test_a_dry_run_still_reports_a_manifest(tmp_path, capsys):
    source = _seed(tmp_path)
    sent: dict = {}
    assert ida.upload_tree("/tmp/stage", True, source, ida.EXCLUDE_DIRS,
                           sent=sent) == 2
    capsys.readouterr()
    assert sent == {"count": 2,
                    "bytes": sum(p.stat().st_size
                                 for p, _ in ida.iter_local_files(
                                     source, ida.EXCLUDE_DIRS))}


# --------------------------------------------------------------------------
# server-tools-3: the snapshot bind has to follow the host's automounts
# --------------------------------------------------------------------------

def test_the_snapshot_mount_follows_the_hosts_automounts():
    """Each name under `.zfs/snapshot` is mounted by the kernel in the HOST's
    namespace on first traversal. An rprivate bind never sees those, so the
    recovery page reports every project as missing from the snapshot."""
    vols = ida.snapshot_volumes(("/mnt/tank/.zfs/snapshot", "Projects"))
    assert vols == [f"/mnt/tank/.zfs/snapshot:{ida.SNAPSHOT_MOUNT}:ro,rslave"]
    # still a plain string: the whole compose body is rendered by hand and
    # every other reader of `volumes` splits on ":".
    assert ida.mount_target(vols[0]) == ida.SNAPSHOT_MOUNT


def test_the_compose_body_carries_the_propagation_option():
    body = ida.compose_config(
        8480, HOST_ROOT, "http://gui:8384", "k", "t",
        snapshot=("/mnt/tank/.zfs/snapshot", "Creators_Club/Projects"),
    )["services"]["dashboard"]
    assert f"/mnt/tank/.zfs/snapshot:{ida.SNAPSHOT_MOUNT}:ro,rslave" in body["volumes"]
    # read-only is not negotiable: a write there is a rollback of footage
    assert all(":rw" not in v for v in body["volumes"]
               if v.startswith("/mnt/tank/.zfs/snapshot"))


def test_the_deploy_names_the_host_side_half_of_it():
    """rslave alone is not enough if the host mount is private, and that is a
    change to the NAS's mount namespace a deploy may not make silently."""
    lines = ida.snapshot_propagation_note(("/mnt/tank/.zfs/snapshot", "Projects"))
    text = "\n".join(lines)
    assert "findmnt -no PROPAGATION /mnt/tank" in text
    assert "mount --make-rshared /mnt/tank" in text
    # ...and how to prove it, which is the only way to know: an already
    # mounted snapshot is visible either way.
    assert f"ls {ida.SNAPSHOT_MOUNT}/<snapshot>/" in text


def test_no_snapshot_source_is_no_note_at_all():
    assert ida.snapshot_propagation_note(("", "")) == []
    assert ida.snapshot_propagation_note(None) == []
