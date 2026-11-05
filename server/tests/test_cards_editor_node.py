"""Node for the new Timeline Cards editor: pinned, verified, mounted :ro.

2026-11-05, MulticamPipeline `editor/docs/NAS-CUTOVER.md` phase 2. The deploy
provisions an official Node build into `<host-root>/node` (mounted read-only
at /opt/node) the way it provisions ffmpeg and deno, and only on a site whose
site.toml says `[timeline_cards] editor = true`. The properties defended:

  * NO CHECKSUM, NO INSTALL. nodejs.org's published SHASUMS256.txt must be
    fetchable, list the pinned tarball, and AGREE with the pin; otherwise
    nothing is fetched or sent. The remote script refuses to be built without
    a digest, checks it before unpacking, and runs the candidate before it
    replaces anything.
  * THE DEFAULT DEPLOY DOES NOT CHANGE. No editor flag: no mount, no env key,
    no download (test_safety diffs the env key set against compose.yaml).
  * IT IS A DRY RUN THAT SAYS SO. `--dry-run` lists the Node step.

Nothing here touches a NAS or the network: the published list and the
download are stubbed, and the remote script runs under a stub sudo against a
temp directory with a tarball made in the test.
"""
from __future__ import annotations

import hashlib
import io
import re
import shutil
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import install_dashboard_app as ida  # noqa: E402

from test_music_deploy import _dry_run  # noqa: E402
from test_safety import run_remote_script  # noqa: E402

BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="a POSIX shell is required")
HOST_ROOT = "/mnt/tank/apps/ccsync-dashboard"

PUBLISHED = (
    f"{'a' * 64}  node-v{ida.NODE_VERSION}-linux-arm64.tar.xz\n"
    f"{ida.NODE_SHA256}  {ida.NODE_TARBALL}\n"
    f"{'b' * 64}  {ida.NODE_TARBALL}.sig\n")


# ------------------------------------------------------------------- the pin

def test_the_pin_is_a_versioned_official_linux_x64_tarball():
    assert re.fullmatch(r"24\.\d+\.\d+", ida.NODE_VERSION)
    assert ida.NODE_URL == (f"https://nodejs.org/dist/v{ida.NODE_VERSION}/"
                            f"node-v{ida.NODE_VERSION}-linux-x64.tar.xz")
    assert ida.NODE_SHASUMS_URL.endswith(f"v{ida.NODE_VERSION}/SHASUMS256.txt")
    assert re.fullmatch(r"[0-9a-f]{64}", ida.NODE_SHA256)
    assert "latest" not in ida.NODE_URL        # a rolling pointer cannot be pinned


def test_shasums_are_matched_on_the_exact_file_name():
    assert ida.parse_shasums(PUBLISHED, ida.NODE_TARBALL) == ida.NODE_SHA256
    assert ida.parse_shasums(PUBLISHED, "node-v1-win-x64.zip") == ""
    assert ida.parse_shasums("not a list", ida.NODE_TARBALL) == ""
    assert ida.parse_shasums(f"nothex{'z' * 59}  {ida.NODE_TARBALL}\n", ida.NODE_TARBALL) == ""


def test_the_published_digest_is_read_or_refused():
    assert ida.node_published_digest(lambda url: PUBLISHED) == (ida.NODE_SHA256, "")
    digest, err = ida.node_published_digest(lambda url: f"{'c' * 64}  other.tar.xz\n")
    assert digest == "" and "no checksum" in err

    def down(url):
        raise OSError("network is down")

    digest, err = ida.node_published_digest(down)
    assert digest == "" and "could not be fetched" in err


# --------------------------------------------------------- no checksum, no install

@pytest.fixture
def nothing_moves(monkeypatch):
    """Any fetch, any push, any ssh at all is a test failure."""
    def boom(*a, **k):
        raise AssertionError("something moved before the checksum was settled")

    monkeypatch.setattr(ida, "fetch_pinned_file", boom)
    monkeypatch.setattr(ida, "install_binary_over_lan", boom)
    monkeypatch.setattr(ida, "run_ssh_guarded", boom)


def test_an_unreachable_checksum_list_installs_nothing(nothing_moves, capsys):
    def down(url):
        raise OSError("no route")

    assert ida.provision_node(HOST_ROOT, False, fetch_text=down) is False
    err = capsys.readouterr().err
    assert "Node was NOT provisioned" in err and "never installed" in err
    assert "/cards/edit" in err                      # what it costs, in words


def test_a_list_with_no_line_for_the_tarball_installs_nothing(nothing_moves, capsys):
    assert ida.provision_node(HOST_ROOT, False,
                              fetch_text=lambda u: f"{'d' * 64}  x.tar.xz\n") is False
    assert "no checksum" in capsys.readouterr().err


def test_a_list_that_disagrees_with_the_pin_installs_nothing(nothing_moves, capsys):
    bad = f"{'e' * 64}  {ida.NODE_TARBALL}\n"
    assert ida.provision_node(HOST_ROOT, False, fetch_text=lambda u: bad) is False
    err = capsys.readouterr().err
    assert "not the pinned" in err and "nothing was fetched" in err


def test_a_download_that_fails_the_pin_installs_nothing(monkeypatch, capsys):
    monkeypatch.setattr(ida, "run_ssh_guarded", lambda *a, **k: (0, "none\n", ""))
    monkeypatch.setattr(ida, "fetch_pinned_file",
                        lambda *a, **k: (None, "the download does not match the supplied sha256"))
    pushed = []
    monkeypatch.setattr(ida, "install_binary_over_lan",
                        lambda *a, **k: pushed.append(a) or (True, ""))
    assert ida.provision_node(HOST_ROOT, False, fetch_text=lambda u: PUBLISHED) is False
    assert pushed == []
    assert "could not be fetched here" in capsys.readouterr().err


def test_a_good_run_pushes_the_pinned_tarball_with_the_node_script(monkeypatch, tmp_path):
    monkeypatch.setattr(ida, "run_ssh_guarded", lambda *a, **k: (0, "none\n", ""))
    tarball = tmp_path / ida.NODE_TARBALL
    tarball.write_bytes(b"x")
    seen = {}
    monkeypatch.setattr(ida, "fetch_pinned_file",
                        lambda url, sha, override, label: seen.update(
                            url=url, sha=sha) or (tarball, ""))

    def push(root, host_dir, binary, local, url, sha, dry, build_script=None):
        seen.update(root=root, host_dir=host_dir, build=build_script, push_sha=sha)
        return True, ""

    monkeypatch.setattr(ida, "install_binary_over_lan", push)
    assert ida.provision_node(HOST_ROOT, False, fetch_text=lambda u: PUBLISHED) is True
    assert seen["url"] == ida.NODE_URL and seen["sha"] == ida.NODE_SHA256
    assert seen["push_sha"] == ida.NODE_SHA256
    assert seen["host_dir"] == "node" and seen["build"] is ida.build_node_install_script


def test_an_already_provisioned_host_is_left_alone(monkeypatch, capsys):
    monkeypatch.setattr(ida, "run_ssh_guarded",
                        lambda *a, **k: (0, f"v{ida.NODE_VERSION}\n", ""))

    def boom(*a, **k):
        raise AssertionError("a provisioned host must not be re-downloaded")

    monkeypatch.setattr(ida, "fetch_pinned_file", boom)
    assert ida.provision_node(HOST_ROOT, False, fetch_text=lambda u: PUBLISHED) is True
    assert "already provisioned" in capsys.readouterr().out


# ---------------------------------------------------------- the remote script

def test_the_script_cannot_be_built_without_a_digest():
    with pytest.raises(ValueError, match="no checksum, no install"):
        ida.build_node_install_script("/r/node", "node", "/tmp/s/n.tar.xz", "/tmp/s", "")


def test_the_script_verifies_before_it_unpacks_and_runs_before_it_replaces():
    script = ida.build_node_install_script(
        f"{HOST_ROOT}/node", "node", f"/tmp/s/{ida.NODE_TARBALL}", "/tmp/s",
        ida.NODE_SHA256)
    assert "\n" not in script                     # one `sh -c` string like the others
    assert ida.NODE_SHA256 in script and "sha256sum -c" in script
    assert script.index("sha256sum -c") < script.index("tar -xJf")
    assert script.index("--version") < script.index("mv -f") < script.rindex("mv ")
    assert "already provisioned" in script and "does not run on this host" in script
    assert "rm -rf" in script and "node.prev" in script   # replaced, never deleted
    assert f"v{ida.NODE_VERSION}" in script


def _tarball(tmp_path, version=ida.NODE_VERSION, name=None):
    """A real .tar.xz with node-vX-linux-x64/bin/node, a shell script that
    prints its version, standing in for the 100 MB binary."""
    name = name or ida.NODE_TARBALL
    path = tmp_path / name
    payload = f"#!/bin/sh\necho v{version}\n".encode()
    with tarfile.open(path, "w:xz") as tar:
        info = tarfile.TarInfo(f"node-v{version}-linux-x64/bin/node")
        info.size, info.mode = len(payload), 0o755
        tar.addfile(info, io.BytesIO(payload))
        other = tarfile.TarInfo(f"node-v{version}-linux-x64/include/node/node.h")
        other.size = 0
        tar.addfile(other, io.BytesIO(b""))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _posix(path) -> str:
    """A Windows drive path as its MSYS form: GNU tar reads `C:` as a remote host, so the script
    under test must be handed the MSYS form of every path on a Windows rig."""
    return re.sub(r"^([A-Za-z]):", lambda m: "/" + m.group(1).lower(),
                  Path(path).as_posix())


def _run_install(tmp_path, tarball, sha, target, version=ida.NODE_VERSION, monkeypatch=None):
    # `install -o root -g root` needs root; a stub that drops the ownership
    # flags keeps everything else (mode, copy) real.
    bindir = tmp_path / "stubbin"
    bindir.mkdir(exist_ok=True)
    real = "/usr/bin/install"          # the POSIX shell's own, not the Windows PATH's
    (bindir / "install").write_text(
        "#!/bin/sh\nargs=\"\"\nwhile [ $# -gt 0 ]; do case \"$1\" in "
        "-o|-g) shift 2;; *) args=\"$args '$1'\"; shift;; esac; done\n"
        f"eval exec '{real}' $args\n", encoding="utf-8", newline="\n")
    (bindir / "install").chmod(0o755)
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)
    script = ida.build_node_install_script(_posix(target), "node", _posix(tarball),
                                           _posix(staging), sha)
    return run_remote_script(script, tmp_path)


@needs_bash
def test_the_script_installs_only_bin_node_and_is_idempotent(tmp_path):
    if not shutil.which("xz") or not shutil.which("install"):
        pytest.skip("xz and install are needed to run the script for real")
    tarball, sha = _tarball(tmp_path)
    target = tmp_path / "node"
    proc = _run_install(tmp_path, tarball, sha, target)
    assert proc.returncode == 0, proc.stderr
    assert (target / "bin" / "node").is_file()
    assert not (target / "bin" / "node.new").exists()
    assert not (target / "include").exists()               # just the binary
    assert f"v{ida.NODE_VERSION} provisioned" in proc.stdout
    again = _run_install(tmp_path, tarball, sha, target)
    assert again.returncode == 0 and "already provisioned" in again.stdout


@needs_bash
def test_a_corrupted_transfer_installs_nothing(tmp_path):
    if not shutil.which("xz") or not shutil.which("install"):
        pytest.skip("xz and install are needed")
    tarball, _sha = _tarball(tmp_path)
    target = tmp_path / "node"
    proc = _run_install(tmp_path, tarball, "f" * 64, target)
    assert proc.returncode == 7 and "transfer was corrupted" in proc.stderr
    assert not target.exists()


@needs_bash
def test_a_binary_that_is_not_the_pinned_version_never_replaces_the_good_one(tmp_path):
    if not shutil.which("xz") or not shutil.which("install"):
        pytest.skip("xz and install are needed")
    target = tmp_path / "node"
    (target / "bin").mkdir(parents=True)
    old = target / "bin" / "node"
    old.write_text("#!/bin/sh\necho v1.0.0\n", encoding="utf-8", newline="\n")
    old.chmod(0o755)
    tarball, sha = _tarball(tmp_path, version="99.0.0")     # runs, but the wrong version
    proc = _run_install(tmp_path, tarball, sha, target)
    assert proc.returncode == 1 and "does not run on this host" in proc.stderr
    assert "v1.0.0" in old.read_text(encoding="utf-8")       # untouched
    assert not (target / "bin" / "node.new").exists()


# ----------------------------------------------------------- compose wiring

def _service(**kw):
    return ida.compose_config(8480, HOST_ROOT, "http://gui:8384", "k", "t",
                              **kw)["services"]["dashboard"]


@pytest.mark.parametrize("mode", ["bind", "image"])
def test_the_default_deploy_carries_no_editor_and_no_node(mode):
    svc = _service(mode=mode, cards_enabled="1")
    assert not any("/opt/node" in v for v in svc["volumes"])
    assert "DASH_CARDS_EDITOR" not in svc["environment"]
    assert "DASH_NODE" not in svc["environment"]


@pytest.mark.parametrize("mode", ["bind", "image"])
def test_the_editor_adds_the_node_mount_and_two_env_keys_and_nothing_else(mode):
    base = _service(mode=mode, cards_enabled="1")
    on = _service(mode=mode, cards_enabled="1", cards_editor="1")
    assert f"{HOST_ROOT}/node:/opt/node:ro" in on["volumes"]
    assert set(on["volumes"]) - set(base["volumes"]) == {f"{HOST_ROOT}/node:/opt/node:ro"}
    assert on["environment"]["DASH_CARDS_EDITOR"] == "1"
    assert on["environment"]["DASH_NODE"] == "/opt/node/bin/node"
    assert set(on["environment"]) - set(base["environment"]) == {
        "DASH_CARDS_EDITOR", "DASH_NODE"}


def test_the_editor_needs_cards_itself(monkeypatch):
    monkeypatch.setattr(ida, "SITE_CARDS_EDITOR", True)
    assert ida.cards_editor_for_site("1") == "1"
    assert ida.cards_editor_for_site("0") == "0"
    monkeypatch.setattr(ida, "SITE_CARDS_EDITOR", False)
    assert ida.cards_editor_for_site("1") == "0"


# --------------------------------------------------------------- the dry run

def test_a_dry_run_lists_node_when_the_site_turns_the_editor_on(monkeypatch, capsys):
    monkeypatch.setattr(ida, "SITE_CARDS_EDITOR", True)
    monkeypatch.setattr(ida, "cards_enabled_for_site", lambda ship: "1")
    cmds: list = []
    transcript = _dry_run(monkeypatch, capsys, cmds)
    assert f"would provision Node v{ida.NODE_VERSION}" in transcript
    assert ida.NODE_URL in transcript and "/opt/node" in transcript
    assert ida.NODE_SHA256[:12] in transcript
    # the host dir exists on every site; it is only MOUNTED with the editor on
    dirs_cmd = next(c for c in cmds if "ytdl-data" in c and "mkdir -p" in c)
    assert "/node" in dirs_cmd


def test_a_dry_run_without_the_flag_says_nothing_about_node(monkeypatch, capsys):
    monkeypatch.setattr(ida, "SITE_CARDS_EDITOR", False)
    cmds: list = []
    transcript = _dry_run(monkeypatch, capsys, cmds)
    assert "would provision Node" not in transcript


def test_no_node_skips_the_step(monkeypatch, capsys):
    monkeypatch.setattr(ida, "SITE_CARDS_EDITOR", True)
    monkeypatch.setattr(ida, "cards_enabled_for_site", lambda ship: "1")
    cmds: list = []
    transcript = _dry_run(monkeypatch, capsys, cmds, extra_argv=["--no-node"])
    assert "would provision Node" not in transcript
