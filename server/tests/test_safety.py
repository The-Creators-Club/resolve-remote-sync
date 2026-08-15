"""Tests for the refuse-rather-than-destroy behaviour of the server scripts.

Everything here is offline: the shell-level tests run the *generated* remote
script under a stub `sudo` in a temp directory, so the actual semantics are
exercised (marker preserved, refusals, no injection) without a NAS.

Run with:
    cd E:\\Projects\\resolve-remote-sync\\server
    python -m pytest tests -v
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import accept_device  # noqa: E402
import check_health  # noqa: E402
import common  # noqa: E402
import install_dashboard_app  # noqa: E402
import setup_editor_account  # noqa: E402
import setup_syncthing_folder  # noqa: E402
import setup_tree  # noqa: E402
import write_marker  # noqa: E402
from common import MARKER_FILENAME, build_marker_write_cmd, validate_slug  # noqa: E402
from setup_tree import (  # noqa: E402
    RC_ANCESTOR_MARKER,
    RC_DESCENDANT_MARKER,
    ancestor_dirs,
    build_remote_script,
)

BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="a POSIX shell is required")

SUDO_STUB = """#!/bin/sh
# Stand-in for sudo: drop -S / -p <prompt> and run the rest as the test user.
while [ $# -gt 0 ]; do
  case "$1" in
    -S) shift ;;
    -p) shift 2 ;;
    *) break ;;
  esac
done
exec "$@"
"""

# A sudo that REFUSES -- the shape of a revoked sudoer, a lockout after failed
# attempts, requiretty, or a policy change. SERVER-4 (2026-08-14): the marker
# read used to put `sudo test -e` in an `if` CONDITION, which is exempt from
# the exit status, so this stub made the remote command print MARKER-ABSENT and
# exit 0 -- "this project has no identity" for a project that has one.
SUDO_REFUSING_STUB = """#!/bin/sh
echo "sudo: a password is required" >&2
exit 1
"""


def single_quoted_mask(script: str) -> list[bool]:
    """Per-character 'is inside a single-quoted region' mask for a sh script.

    Models exactly what shell_quote produces, including its '\\'' escape
    dance, so a test can prove that a free-text value is never exposed to the
    shell's expansions.
    """
    mask = []
    in_single = False
    escaped = False
    for ch in script:
        if in_single:
            if ch == "'":
                in_single = False
                mask.append(False)
            else:
                mask.append(True)
            continue
        if escaped:
            escaped = False
            mask.append(False)
            continue
        if ch == "\\":
            escaped = True
            mask.append(False)
            continue
        if ch == "'":
            in_single = True
            mask.append(False)
            continue
        mask.append(False)
    return mask


def unquoted_occurrences(script: str, needle: str) -> int:
    """How many times `needle` appears outside single quotes (0 is the goal)."""
    mask = single_quoted_mask(script)
    count = 0
    start = script.find(needle)
    while start != -1:
        if not all(mask[start:start + len(needle)]):
            count += 1
        start = script.find(needle, start + 1)
    return count


# Ownership is a NAS concept (root / broll:editors); these tests care about
# control flow, so chown is a no-op here.
CHOWN_STUB = "#!/bin/sh\nexit 0\n"


class _Resp:
    """Minimal stand-in for a requests.Response, enough for common.ok()."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def run_remote_script(script: str, workdir: Path, sudo_stub: str = SUDO_STUB):
    """Execute a generated remote script with a stub sudo. Returns CompletedProcess.

    `sudo_stub` is SUDO_REFUSING_STUB for the tests that ask what a script does
    when the privileged half cannot run at all (SERVER-4).
    """
    bindir = workdir / "stubbin"
    bindir.mkdir(exist_ok=True)
    sudo = bindir / "sudo"
    sudo.write_text(sudo_stub, encoding="utf-8", newline="\n")
    sudo.chmod(0o755)
    chown = bindir / "chown"
    chown.write_text(CHOWN_STUB, encoding="utf-8", newline="\n")
    chown.chmod(0o755)
    script_path = workdir / "remote.sh"
    script_path.write_text(script, encoding="utf-8", newline="\n")
    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["SUDO_PW"] = "not-a-real-password"
    return subprocess.run(
        [BASH, "remote.sh"], cwd=str(workdir), env=env,
        capture_output=True, text=True, timeout=120,
    )


# --------------------------------------------------------------------------
# DEL-8 -- setup_tree must never overwrite an existing project marker
# --------------------------------------------------------------------------

def test_setup_tree_marker_write_is_guarded_by_test_e():
    base = "/p/2026/CCT/Season 1"
    script = build_remote_script(base, "broll", "editors",
                                 slug="2026-cct-season-1", projects_root="/p")
    guarded = build_marker_write_cmd(base, "2026-cct-season-1", only_if_absent=True)
    unconditional = build_marker_write_cmd(base, "2026-cct-season-1")

    assert guarded in script
    # the unconditional write only ever appears inside the guard's else branch
    assert unconditional in guarded
    assert script.count(unconditional) == 1
    assert f"test -e '{base}/{MARKER_FILENAME}'" in guarded
    # the write is inside the else branch of that test
    write_at = guarded.index("printf")
    assert guarded.index("test -e") < guarded.rindex("else", 0, write_at) < write_at


def test_build_marker_write_cmd_stays_unconditional_by_default():
    # write_marker.py is the deliberate-change tool and still writes outright.
    cmd = build_marker_write_cmd("/p/x", "the-slug")
    assert "test -e" not in cmd
    assert cmd.strip().startswith("echo \"$SUDO_PW\"")


@needs_bash
def test_existing_marker_survives_setup_tree_rerun(tmp_path):
    base_rel = "Projects/2026/CCT/Season 1"
    target = tmp_path / base_rel
    target.mkdir(parents=True)
    marker = target / MARKER_FILENAME
    marker.write_text(json.dumps({"slug": "2025-ff4-nuclear", "created_by": "setup_tree"}),
                      encoding="utf-8")

    script = build_remote_script(base_rel, "broll", "editors",
                                 slug="2026-cct-season-1", projects_root="Projects")
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == 0, proc.stderr
    # identity untouched
    assert json.loads(marker.read_text(encoding="utf-8"))["slug"] == "2025-ff4-nuclear"
    assert "NOT overwriting" in proc.stdout
    assert "2025-ff4-nuclear" in proc.stdout
    # and it still did its actual job
    assert (target / "Audio" / "Music").is_dir()


@needs_bash
def test_marker_is_written_when_absent(tmp_path):
    base_rel = "Projects/2026/CCT/Season 1"
    script = build_remote_script(base_rel, "broll", "editors",
                                 slug="2026-cct-season-1", projects_root="Projects")
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == 0, proc.stderr
    marker = tmp_path / base_rel / MARKER_FILENAME
    assert json.loads(marker.read_text(encoding="utf-8"))["slug"] == "2026-cct-season-1"
    assert "marker written" in proc.stdout


@needs_bash
def test_same_slug_marker_is_reported_not_rewritten(tmp_path):
    base_rel = "Projects/2026/CCT/Season 1"
    target = tmp_path / base_rel
    target.mkdir(parents=True)
    (target / MARKER_FILENAME).write_text(
        json.dumps({"slug": "2026-cct-season-1", "created_by": "write_marker"}),
        encoding="utf-8")

    script = build_remote_script(base_rel, "broll", "editors",
                                 slug="2026-cct-season-1", projects_root="Projects")
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "same identity" in proc.stdout
    # created_by preserved => the file really was left alone
    assert json.loads((target / MARKER_FILENAME).read_text(encoding="utf-8"))["created_by"] \
        == "write_marker"


# --------------------------------------------------------------------------
# INST-13 -- refuse to mark a container, or a dir inside an existing project
# --------------------------------------------------------------------------

def test_ancestor_dirs_between_root_and_target():
    assert ancestor_dirs("/p", "/p/2026/CCT/Season 1") == ["/p/2026", "/p/2026/CCT"]
    assert ancestor_dirs("/p/", "/p/2026") == []
    assert ancestor_dirs("/p", "/other/2026/x") == []


@needs_bash
def test_refuses_when_an_ancestor_is_already_a_project(tmp_path):
    (tmp_path / "Projects/2026/CCT").mkdir(parents=True)
    (tmp_path / "Projects/2026/CCT" / MARKER_FILENAME).write_text(
        json.dumps({"slug": "2026-cct"}), encoding="utf-8")

    base_rel = "Projects/2026/CCT/Season 1"
    script = build_remote_script(base_rel, "broll", "editors",
                                 slug="2026-cct-season-1", projects_root="Projects")
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == RC_ANCESTOR_MARKER
    assert "REFUSING" in proc.stderr
    assert not (tmp_path / base_rel).exists()


@needs_bash
def test_refuses_when_target_already_contains_a_project(tmp_path):
    inner = tmp_path / "Projects/2026/CCT/Season 1"
    inner.mkdir(parents=True)
    (inner / MARKER_FILENAME).write_text(json.dumps({"slug": "2026-cct-season-1"}),
                                         encoding="utf-8")

    script = build_remote_script("Projects/2026/CCT", "broll", "editors",
                                 slug="2026-cct", projects_root="Projects")
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == RC_DESCENDANT_MARKER
    assert "REFUSING" in proc.stderr
    assert "CONTAINS" in proc.stderr
    # the container did NOT get a marker of its own
    assert not (tmp_path / "Projects/2026/CCT" / MARKER_FILENAME).exists()
    # ...and the real project's identity is untouched
    assert json.loads((inner / MARKER_FILENAME).read_text(encoding="utf-8"))["slug"] \
        == "2026-cct-season-1"


@needs_bash
def test_sibling_project_does_not_block(tmp_path):
    # A marker somewhere else under Projects/ is none of this run's business.
    other = tmp_path / "Projects/2026/CCT/Season 1"
    other.mkdir(parents=True)
    (other / MARKER_FILENAME).write_text(json.dumps({"slug": "a"}), encoding="utf-8")

    script = build_remote_script("Projects/2026/CCT/Season 2", "broll", "editors",
                                 slug="2026-cct-season-2", projects_root="Projects")
    proc = run_remote_script(script, tmp_path)
    assert proc.returncode == 0, proc.stderr


# --------------------------------------------------------------------------
# SEC-8 -- free-text names must not be substituted by the root-run shell
# --------------------------------------------------------------------------

@needs_bash
def test_project_name_is_not_shell_substituted(tmp_path):
    evil = "A$(touch pwned)`touch pwned2`"
    base_rel = f"Projects/2026/CCT/{evil}"
    script = build_remote_script(base_rel, "broll", "editors",
                                 slug="2026-cct-a", projects_root="Projects")
    # never pasted into a double-quoted echo
    assert f'echo "exists: {evil}' not in script
    assert f'echo "created: {evil}' not in script

    proc = run_remote_script(script, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "pwned").exists()
    assert not (tmp_path / "pwned2").exists()
    # the literal directory name was created instead
    assert (tmp_path / base_rel).is_dir()


def test_owner_and_group_are_quoted_in_messages():
    script = build_remote_script("/p/2026/x", "own$(id)er", "editors", projects_root="/p")
    assert 'echo "ownership set' not in script
    assert "own$(id)er" in script          # present...
    assert unquoted_occurrences(script, "own$(id)er") == 0   # ...but never exposed


def test_every_free_text_value_stays_single_quoted():
    base = "/p/2026/CCT/A$(id)`whoami` 1"
    script = build_remote_script(base, "broll", "editors", slug="2026-cct-a-1",
                                 projects_root="/p")
    for needle in ("A$(id)`whoami` 1", "$(id)", "`whoami`"):
        assert unquoted_occurrences(script, needle) == 0


# --------------------------------------------------------------------------
# INST-12 -- write_marker must not reassign an identity without --force
# --------------------------------------------------------------------------

def test_validate_slug_accepts_and_rejects():
    assert validate_slug("2026-cct-season-1") == "2026-cct-season-1"
    for bad in ("", "Season 1", "2026/CCT", "UPPER", "under_score", "semi;colon"):
        with pytest.raises(ValueError):
            validate_slug(bad)


def test_parse_marker_slug_variants():
    assert write_marker.parse_marker_slug('{"slug": "a-b", "created_by": "x"}') == "a-b"
    assert write_marker.parse_marker_slug('  {"slug":"a-b"}  ') == "a-b"
    # hand-mangled marker: still recognisably an identity
    assert write_marker.parse_marker_slug('{"slug": "a-b",') == "a-b"
    assert write_marker.parse_marker_slug("") == ""


def _fake_marker_ssh(slug: str, calls: list):
    def fake_run_ssh(cmd, dry_run=False, timeout=120):
        calls.append(cmd)
        if "MARKER-PRESENT" in cmd:
            return 0, f'MARKER-PRESENT\n{{"slug": "{slug}", "created_by": "setup_tree"}}\n', ""
        return 0, "marker written: .ccsync-project\n", ""
    return fake_run_ssh


def test_write_marker_refuses_slug_change_without_force(monkeypatch, capsys):
    calls: list = []
    monkeypatch.setattr(write_marker, "run_ssh", _fake_marker_ssh("2025-ff4-nuclear", calls))
    monkeypatch.setattr(sys, "argv", [
        "write_marker.py", "--project-rel-path", "2026/CCT/Nuclear",
    ])
    rc = write_marker.main()
    out = capsys.readouterr()

    assert rc == 3
    assert "REFUSING" in out.err
    assert "2025-ff4-nuclear" in out.err
    assert "--force" in out.err
    # nothing was written: only the read happened
    assert len(calls) == 1


def test_write_marker_allows_slug_change_with_force(monkeypatch, capsys):
    calls: list = []
    monkeypatch.setattr(write_marker, "run_ssh", _fake_marker_ssh("2025-ff4-nuclear", calls))
    monkeypatch.setattr(sys, "argv", [
        "write_marker.py", "--project-rel-path", "2026/CCT/Nuclear", "--force",
    ])
    rc = write_marker.main()
    out = capsys.readouterr()

    assert rc == 0
    assert "2025-ff4-nuclear -> 2026-cct-nuclear" in out.out
    assert len(calls) == 2  # read, then write


def test_write_marker_same_slug_needs_no_force(monkeypatch, capsys):
    calls: list = []
    monkeypatch.setattr(write_marker, "run_ssh", _fake_marker_ssh("2026-cct-nuclear", calls))
    monkeypatch.setattr(sys, "argv", [
        "write_marker.py", "--project-rel-path", "2026/CCT/Nuclear",
    ])
    rc = write_marker.main()
    assert rc == 0
    assert "identity unchanged" in capsys.readouterr().out


def test_write_marker_rejects_invalid_slug(monkeypatch, capsys):
    monkeypatch.setattr(write_marker, "run_ssh",
                        _fake_marker_ssh("x", []))  # must never be reached
    monkeypatch.setattr(sys, "argv", [
        "write_marker.py", "--project-rel-path", "2026/CCT/Nuclear", "--slug", "Season 1",
    ])
    assert write_marker.main() == 1
    assert "invalid slug" in capsys.readouterr().err


# --------------------------------------------------------------------------
# §9 slug collisions -- a folder id that points elsewhere is a refusal
# --------------------------------------------------------------------------

def test_paths_differ_ignores_trailing_slash():
    assert not setup_syncthing_folder.paths_differ("/data/Projects/x/", "/data/Projects/x")
    assert setup_syncthing_folder.paths_differ("/data/Projects/x", "/data/Projects/y")
    assert setup_syncthing_folder.paths_differ("", "/data/Projects/x")


def test_syncthing_folder_refuses_id_collision(no_ssh, capsys):
    # --no-marker-read: this test is about the slugify id-collision, and
    # without it the marker read runs first -- live SSH where paramiko +
    # TRUENAS_PW exist, a MARKER_UNAVAILABLE refusal where they don't --
    # either way never reaching the guard under test.
    monkeypatch = no_ssh
    monkeypatch.setattr(
        setup_syncthing_folder, "find_folder",
        lambda *a, **k: {"id": "2026-cct-season-1", "path": "/data/Projects/2026/CCT/Season-1"},
    )
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", "2026/CCT/Season 1",
        "--no-marker-read",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
    ])
    rc = setup_syncthing_folder.main()
    err = capsys.readouterr().err

    assert rc == 1
    assert "REFUSING" in err
    assert "/data/Projects/2026/CCT/Season-1" in err   # existing
    assert "/data/Projects/2026/CCT/Season 1" in err   # requested


@pytest.fixture
def no_ssh(monkeypatch):
    """Make any real SSH from a unit test a hard failure.

    TRUENAS_PW is set on the maintainer's own workstation (ship.ps1 requires
    it), so a test that reaches setup_syncthing_folder's marker read without
    monkeypatching it would silently open a LIVE connection to the NAS and
    pass -- while proving nothing and depending on the state of a real
    project directory.
    """
    def boom(*a, **k):
        raise AssertionError("this test must not open an SSH connection")

    monkeypatch.setattr(common, "ssh_client", boom)
    return monkeypatch


def test_syncthing_folder_force_keeps_the_wan_puller_tuning(no_ssh, capsys):
    """B19: a --force PUT sends a COMPLETE folder object, so every key absent
    from it is reset to the Syncthing default. Omitting the tuning left the
    project pulling at maxConcurrentWrites=2 over the WAN forever, with
    nothing logged and no repair pass anywhere to notice."""
    monkeypatch = no_ssh
    sent = {}

    def fake_api(method, gui_url, path, api_key, **kwargs):
        sent.setdefault(method, []).append((path, kwargs.get("json_body")))
        return _Resp(200, {})

    monkeypatch.setattr(
        setup_syncthing_folder, "find_folder",
        lambda *a, **k: {"id": "2026-cct-season-1",
                         "path": "/data/Projects/2026/CCT/OldName",
                         "devices": [{"deviceID": "AAA", "introducedBy": ""}]},
    )
    monkeypatch.setattr(setup_syncthing_folder, "find_folder_by_path", lambda *a, **k: None)
    monkeypatch.setattr(setup_syncthing_folder, "syncthing_api", fake_api)
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", "2026/CCT/Season 1",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k", "--force",
        # this test is about the folder object, not the identity
        "--slug", "2026-cct-season-1",
    ])

    assert setup_syncthing_folder.main() == 0
    put_path, folder = sent["PUT"][0]
    assert put_path == "/rest/config/folders/2026-cct-season-1"
    assert folder["maxConcurrentWrites"] == 32
    assert folder["pullerMaxPendingKiB"] == 65536
    # existing device shares are still preserved by the retarget
    assert folder["devices"] == [{"deviceID": "AAA", "introducedBy": ""}]


def test_syncthing_folder_create_carries_the_wan_puller_tuning(no_ssh, capsys):
    monkeypatch = no_ssh
    sent = {}

    def fake_api(method, gui_url, path, api_key, **kwargs):
        sent.setdefault(method, []).append((path, kwargs.get("json_body")))
        return _Resp(200, {})

    monkeypatch.setattr(setup_syncthing_folder, "find_folder", lambda *a, **k: None)
    monkeypatch.setattr(setup_syncthing_folder, "find_folder_by_path", lambda *a, **k: None)
    monkeypatch.setattr(setup_syncthing_folder, "syncthing_api", fake_api)
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", "2026/CCT/Season 1",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
        "--no-marker-read",
    ])

    assert setup_syncthing_folder.main() == 0
    _path, folder = sent["POST"][0]
    assert folder["maxConcurrentWrites"] == 32
    assert folder["pullerMaxPendingKiB"] == 65536


def test_syncthing_folder_create_and_force_carry_ignore_delete(no_ssh):
    """delete-protection (2026-08-11, docs/delete-protection-ignoredelete.md):
    the NAS copy is the authority and must never apply a delete an editor
    made. Asserted on the --force PUT too: that replaces the whole folder
    object, so a reconfigure would otherwise silently drop the protection --
    the same way it once dropped the WAN puller tuning (B19)."""
    monkeypatch = no_ssh
    sent = {}

    def fake_api(method, gui_url, path, api_key, **kwargs):
        sent.setdefault(method, []).append((path, kwargs.get("json_body")))
        return _Resp(200, {})

    monkeypatch.setattr(setup_syncthing_folder, "find_folder", lambda *a, **k: None)
    monkeypatch.setattr(setup_syncthing_folder, "find_folder_by_path", lambda *a, **k: None)
    monkeypatch.setattr(setup_syncthing_folder, "syncthing_api", fake_api)
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", "2026/CCT/Season 1",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
        "--no-marker-read",
    ])
    assert setup_syncthing_folder.main() == 0
    _path, created = sent["POST"][0]
    assert created["ignoreDelete"] is True

    monkeypatch.setattr(
        setup_syncthing_folder, "find_folder",
        lambda *a, **k: {"id": "2026-cct-season-1", "path": "/data/Projects/2026/CCT/Season 1",
                         "devices": [{"deviceID": "AAA", "introducedBy": ""}]})
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", "2026/CCT/Season 1",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k", "--force",
        "--slug", "2026-cct-season-1",
    ])
    assert setup_syncthing_folder.main() == 0
    _put_path, forced = sent["PUT"][0]
    assert forced["ignoreDelete"] is True


def test_syncthing_folder_tuning_matches_the_dashboard_collector():
    """The canonical values live in the dashboard's provision.build_folder_config
    (AUDIT_2 P6/§4.2). Two copies with no cross-check is how they drift."""
    provision = (Path(__file__).resolve().parents[2] /
                 "dashboard" / "src" / "ccsync_dashboard" / "provision.py").read_text(encoding="utf-8")
    for key, value in setup_syncthing_folder.FOLDER_PULL_TUNING.items():
        assert f'"{key}": {value}' in provision, f"{key} drifted from provision.py"


@pytest.mark.parametrize("rel", [
    "../../etc",
    "2026/../../../etc",
    "2026/./CCT",
    "2026//CCT",
    ".ssh",
])
def test_syncthing_folder_refuses_a_traversing_rel_path(rel, no_ssh, capsys):
    """`--project-rel-path "../../etc"` used to produce folder id "etc" at
    /data/Projects/../../etc and sendreceive-sync the container's /etc. Every
    sibling script routes through common.project_path_rel; this one didn't."""
    monkeypatch = no_ssh
    monkeypatch.setattr(
        setup_syncthing_folder, "syncthing_api",
        lambda *a, **k: pytest.fail("a rejected path must reach no API call"))
    monkeypatch.setattr(
        setup_syncthing_folder, "find_folder",
        lambda *a, **k: pytest.fail("a rejected path must reach no API call"))
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", rel,
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
    ])

    assert setup_syncthing_folder.main() == 1
    assert "invalid --project-rel-path" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Folder-ID derivation -- the id is the project's IMMUTABLE marker slug, not
# slugify(current path). A moved project used to get a SECOND folder.
# --------------------------------------------------------------------------

SSF = setup_syncthing_folder  # this section names it a lot


def _fake_run_ssh(marker_body, rc=0, err=""):
    """Stand in for common.run_ssh against the marker-read command. `marker_body`
    None means the directory carries no marker."""
    def run_ssh(cmd, dry_run=False, timeout=120):
        assert "MARKER-PRESENT" in cmd and ".ccsync-project" in cmd
        if rc != 0:
            return rc, "", err
        if marker_body is None:
            return 0, "MARKER-ABSENT\n", ""
        return 0, "MARKER-PRESENT\n" + marker_body + "\n", ""
    return run_ssh


class TestReadMarkerSlug:
    def test_reads_and_validates_a_real_marker(self, monkeypatch):
        monkeypatch.setattr(SSF, "run_ssh", _fake_run_ssh(
            '{"slug": "2026-cct-season-1", "created_by": "setup_tree"}'))
        status, detail = SSF.read_marker_slug("/mnt/tank/x/Projects", "2027/Moved/Elsewhere")
        assert status == SSF.MARKER_PRESENT
        # the slug travels with the DIRECTORY: it does not match the new path
        assert detail == "2026-cct-season-1"
        assert detail != common.slugify("2027/Moved/Elsewhere")

    def test_absent_marker_is_absent_not_a_failure(self, monkeypatch):
        monkeypatch.setattr(SSF, "run_ssh", _fake_run_ssh(None))
        status, _detail = SSF.read_marker_slug("/mnt/tank/x/Projects", "2026/CCT/Season 1")
        assert status == SSF.MARKER_ABSENT

    def test_marker_with_no_slug_is_invalid(self, monkeypatch):
        monkeypatch.setattr(SSF, "run_ssh", _fake_run_ssh('{"created_by": "someone"}'))
        status, detail = SSF.read_marker_slug("/mnt/tank/x/Projects", "2026/CCT/Season 1")
        assert status == SSF.MARKER_INVALID
        assert "no slug" in detail

    def test_marker_slug_failing_slug_re_is_invalid(self, monkeypatch):
        # provision.read_marker enforces the same charset for the same reason:
        # the slug becomes a Syncthing folder id and a dashboard URL segment.
        monkeypatch.setattr(SSF, "run_ssh", _fake_run_ssh('{"slug": "../../etc"}'))
        status, _detail = SSF.read_marker_slug("/mnt/tank/x/Projects", "2026/CCT/Season 1")
        assert status == SSF.MARKER_INVALID

    def test_ssh_failure_is_unavailable_not_absent(self, monkeypatch):
        monkeypatch.setattr(SSF, "run_ssh",
                            _fake_run_ssh(None, rc=1, err="Permission denied"))
        status, detail = SSF.read_marker_slug("/mnt/tank/x/Projects", "2026/CCT/Season 1")
        assert status == SSF.MARKER_UNAVAILABLE
        assert "Permission denied" in detail

    def test_a_refused_sudo_is_unavailable_not_absent(self, monkeypatch):
        """SERVER-4 (2026-08-14): the answer the REAL remote shell gives when
        sudo is revoked or locked out -- MARKER_READ_RC and the sentinel on
        stderr, and in particular NOT a clean MARKER-ABSENT."""
        def run_ssh(cmd, dry_run=False, timeout=120):
            return (common.MARKER_READ_RC, "",
                    "sudo: a password is required\n"
                    + common.MARKER_UNREADABLE_SENTINEL + "\n")

        monkeypatch.setattr(SSF, "run_ssh", run_ssh)
        status, detail = SSF.read_marker_slug("/mnt/tank/x/Projects",
                                              "2026/CCT/Season 1")
        assert status == SSF.MARKER_UNAVAILABLE
        assert common.MARKER_UNREADABLE_SENTINEL in detail

    def test_an_answer_with_no_sentinel_at_all_is_unavailable(self, monkeypatch):
        """The belt to the shell's braces: rc 0 and nothing recognisable means
        we do not know whether this project has an identity, and the one thing
        we must not do is guess one from the current path."""
        monkeypatch.setattr(SSF, "run_ssh",
                            lambda *a, **k: (0, "sudo: a password is required\n", ""))
        status, detail = SSF.read_marker_slug("/mnt/tank/x/Projects",
                                              "2026/CCT/Season 1")
        assert status == SSF.MARKER_UNAVAILABLE
        assert "neither MARKER-PRESENT nor MARKER-ABSENT" in detail

    def test_the_sentinels_are_printed_by_the_privileged_shell(self):
        """The whole defect in one assertion: `if sudo test -e ...; then` puts
        the privileged command in a CONDITION, where its exit status is
        discarded, so a sudo failure fell out of the ELSE branch as
        MARKER-ABSENT with a clean exit 0."""
        cmd = common.build_marker_read_cmd("/mnt/tank/x/Projects/2026/CCT/Season 1")
        assert 'if echo "$SUDO_PW" | sudo -S -p "" test -e' not in cmd
        assert "sh -c" in cmd
        assert cmd.index("sudo -S") < cmd.index("MARKER-ABSENT")
        assert common.MARKER_UNREADABLE_SENTINEL in cmd
        assert f"exit {common.MARKER_READ_RC}" in cmd

    def test_a_raising_run_ssh_never_escapes(self, monkeypatch):
        def boom(*a, **k):
            raise common.EnvError("Required environment variable TRUENAS_PW is not set.")

        monkeypatch.setattr(SSF, "run_ssh", boom)
        status, detail = SSF.read_marker_slug("/mnt/tank/x/Projects", "2026/CCT/Season 1")
        assert status == SSF.MARKER_UNAVAILABLE
        assert "TRUENAS_PW" in detail


class TestChooseFolderId:
    REL = "2027/Moved/Elsewhere"

    def test_explicit_slug_wins_over_everything(self):
        fid, source, refusal = SSF.choose_folder_id(
            self.REL, "2026-cct-season-1", SSF.MARKER_PRESENT, "something-else")
        assert (fid, refusal) == ("2026-cct-season-1", "")
        assert source == "--slug"

    def test_invalid_explicit_slug_refuses(self):
        fid, _source, refusal = SSF.choose_folder_id(
            self.REL, "Not A Slug", SSF.MARKER_ABSENT, "")
        assert fid == "" and "invalid --slug" in refusal

    def test_marker_beats_the_current_path(self):
        # THE regression: a moved project keeps its identity.
        fid, source, refusal = SSF.choose_folder_id(
            self.REL, "", SSF.MARKER_PRESENT, "2026-cct-season-1")
        assert (fid, refusal) == ("2026-cct-season-1", "")
        assert ".ccsync-project" in source
        assert fid != common.slugify(self.REL)

    def test_absent_marker_falls_back_to_slugify(self):
        fid, source, refusal = SSF.choose_folder_id(
            self.REL, "", SSF.MARKER_ABSENT, "/mnt/tank/x/Projects/2027/Moved/Elsewhere")
        assert (fid, refusal) == (common.slugify(self.REL), "")
        assert "slugify" in source

    def test_unreadable_marker_refuses_rather_than_falling_back(self):
        fid, _source, refusal = SSF.choose_folder_id(
            self.REL, "", SSF.MARKER_INVALID, "marker at /p/.ccsync-project carries no slug")
        assert fid == ""
        assert "REFUSING" in refusal
        assert "--slug" in refusal            # tells you how to proceed
        assert "write_marker.py" in refusal   # ...and how to repair it

    def test_unavailable_marker_refuses_and_names_all_three_ways_out(self):
        fid, _source, refusal = SSF.choose_folder_id(
            self.REL, "", SSF.MARKER_UNAVAILABLE, "TRUENAS_PW is not set")
        assert fid == ""
        assert "REFUSING" in refusal
        for escape in ("--slug", "TRUENAS_PW", "--no-marker-read"):
            assert escape in refusal


def test_syncthing_folder_uses_the_marker_slug_for_a_moved_project(no_ssh, capsys):
    """End-to-end: the project moved from 2026/CCT/Season 1 to 2027/Archive/S1
    but kept its identity. The script must operate on the EXISTING folder,
    not create a second one under slugify(new path)."""
    monkeypatch = no_ssh
    sent = {}

    def fake_api(method, gui_url, path, api_key, **kwargs):
        sent.setdefault(method, []).append((path, kwargs.get("json_body")))
        return _Resp(200, {})

    seen_ids = []

    def fake_find_folder(gui_url, api_key, folder_id, dry_run):
        seen_ids.append(folder_id)
        if folder_id == "2026-cct-season-1":
            return {"id": "2026-cct-season-1",
                    "path": "/data/Projects/2027/Archive/S1",
                    "devices": [{"deviceID": "AAA", "introducedBy": ""}]}
        return None

    monkeypatch.setattr(SSF, "run_ssh", _fake_run_ssh('{"slug": "2026-cct-season-1"}'))
    monkeypatch.setattr(SSF, "find_folder", fake_find_folder)
    monkeypatch.setattr(SSF, "syncthing_api", fake_api)
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", "2027/Archive/S1",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
    ])

    assert SSF.main() == 0
    out = capsys.readouterr().out
    # looked the folder up by its marker slug, never by slugify(new path)
    assert seen_ids == ["2026-cct-season-1"]
    assert "2027-archive-s1" not in seen_ids
    assert "folder id: 2026-cct-season-1" in out
    assert ".ccsync-project marker" in out
    # nothing was created: the existing folder already points at this path
    assert "POST" not in sent or all(p != "/rest/config/folders" for p, _ in sent.get("POST", []))


def test_syncthing_folder_refuses_a_second_folder_over_the_same_path(no_ssh, capsys):
    """Belt-and-braces: whatever the id came from, never put a second folder
    over a directory that already has one. This is the moved-project failure
    in its final form -- the collector's marker-slug folder is already there
    and we are about to add a slugify(rel) twin beside it."""
    monkeypatch = no_ssh

    def fake_api(method, gui_url, path, api_key, **kwargs):
        pytest.fail(f"a refused duplicate must write nothing ({method} {path})")

    monkeypatch.setattr(SSF, "find_folder", lambda *a, **k: None)
    monkeypatch.setattr(
        SSF, "find_folder_by_path",
        lambda gui_url, api_key, path, folder_id, dry_run: {
            "id": "2026-cct-season-1", "path": path})
    monkeypatch.setattr(SSF, "syncthing_api", fake_api)
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", "2027/Archive/S1",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
        "--no-marker-read",
    ])

    assert SSF.main() == 1
    err = capsys.readouterr().err
    assert "REFUSING" in err
    assert "2026-cct-season-1" in err                    # the real identity
    assert "--slug 2026-cct-season-1" in err             # the way forward
    assert "/data/Projects/2027/Archive/S1" in err


def test_syncthing_folder_duplicate_guard_also_applies_to_force(no_ssh, capsys):
    monkeypatch = no_ssh
    monkeypatch.setattr(
        SSF, "find_folder",
        lambda *a, **k: {"id": "2027-archive-s1", "path": "/data/Projects/Somewhere/Else"})
    monkeypatch.setattr(
        SSF, "find_folder_by_path",
        lambda gui_url, api_key, path, folder_id, dry_run: {
            "id": "2026-cct-season-1", "path": path})
    monkeypatch.setattr(
        SSF, "syncthing_api",
        lambda *a, **k: pytest.fail("a refused duplicate must write nothing"))
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", "2027/Archive/S1",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
        "--no-marker-read", "--force",
    ])

    assert SSF.main() == 1
    assert "REFUSING" in capsys.readouterr().err


def test_find_folder_by_path_ignores_our_own_id_and_trailing_slashes(monkeypatch):
    folders = [
        {"id": "ours", "path": "/data/Projects/A"},
        {"id": "theirs", "path": "/data/Projects/B/"},
    ]
    monkeypatch.setattr(SSF, "syncthing_api", lambda *a, **k: _Resp(200, folders))

    # our own folder at that path is not a duplicate
    assert SSF.find_folder_by_path("u", "k", "/data/Projects/A", "ours", False) is None
    # ...but somebody else's is, trailing slash and all
    twin = SSF.find_folder_by_path("u", "k", "/data/Projects/B", "ours", False)
    assert twin and twin["id"] == "theirs"
    # and an unoccupied path is clear
    assert SSF.find_folder_by_path("u", "k", "/data/Projects/C", "ours", False) is None


def test_syncthing_folder_refuses_when_the_marker_cannot_be_read(no_ssh, capsys):
    """No TRUENAS_PW / NAS unreachable must NOT silently degrade to
    slugify(rel) -- that is precisely how the divergent id gets created."""
    monkeypatch = no_ssh

    def boom(*a, **k):
        raise common.EnvError("Required environment variable TRUENAS_PW is not set.")

    monkeypatch.setattr(SSF, "run_ssh", boom)
    monkeypatch.setattr(
        SSF, "find_folder",
        lambda *a, **k: pytest.fail("must refuse before touching Syncthing"))
    monkeypatch.setattr(
        SSF, "syncthing_api",
        lambda *a, **k: pytest.fail("must refuse before touching Syncthing"))
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", "2026/CCT/Season 1",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
    ])

    assert SSF.main() == 1
    err = capsys.readouterr().err
    assert "REFUSING" in err and "TRUENAS_PW" in err


def test_syncthing_folder_marker_read_needs_no_ssh_when_slug_is_given(no_ssh, capsys):
    """--slug is the documented escape hatch for "I know the identity but
    cannot reach the NAS" -- it must not try SSH at all (the no_ssh fixture
    turns any attempt into a failure)."""
    monkeypatch = no_ssh
    sent = {}

    def fake_api(method, gui_url, path, api_key, **kwargs):
        sent.setdefault(method, []).append((path, kwargs.get("json_body")))
        return _Resp(200, {})

    monkeypatch.setattr(SSF, "find_folder", lambda *a, **k: None)
    monkeypatch.setattr(SSF, "find_folder_by_path", lambda *a, **k: None)
    monkeypatch.setattr(SSF, "syncthing_api", fake_api)
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", "2027/Archive/S1",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
        "--slug", "2026-cct-season-1",
    ])

    assert SSF.main() == 0
    _path, folder = sent["POST"][0]
    assert folder["id"] == "2026-cct-season-1"
    assert folder["path"] == "/data/Projects/2027/Archive/S1"
    # the LABEL stays the rel path: collector.py writes it to projects.label
    # and sequencer.py makes it the editor's on-disk dir + rclone subpath.
    assert folder["label"] == "2027/Archive/S1"


def test_syncthing_folder_same_path_still_skips(monkeypatch, capsys):
    monkeypatch.setattr(
        setup_syncthing_folder, "find_folder",
        lambda *a, **k: {"id": "2026-cct-season-1", "path": "/data/Projects/2026/CCT/Season 1"},
    )
    monkeypatch.setattr(setup_syncthing_folder, "syncthing_api",
                        lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", "2026/CCT/Season 1",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k", "--dry-run",
    ])
    rc = setup_syncthing_folder.main()
    assert rc == 0
    assert "already points at the requested path" in capsys.readouterr().out


# --------------------------------------------------------------------------
# DEL-9 / INST-31 -- host-root validation and the staged swap
# --------------------------------------------------------------------------

def test_host_root_pattern():
    assert install_dashboard_app.HOST_ROOT_RE.match("/mnt/tank/apps/ccsync-dashboard")
    assert install_dashboard_app.HOST_ROOT_RE.match("/mnt/pool2/apps/ccsync-dashboard/alt")
    for bad in ("/mnt/tank/TheCreatorsPool/Creators_Club", "/mnt/tank/apps", "/",
                "/mnt/tank/apps/ccsync-dashboard-old"):
        assert not install_dashboard_app.HOST_ROOT_RE.match(bad)


def test_install_dashboard_refuses_unvalidated_host_root(monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("must not touch the NAS with an unvalidated --host-root")
    monkeypatch.setattr(install_dashboard_app, "run_ssh", boom)
    monkeypatch.setattr(sys, "argv", [
        "install_dashboard_app.py", "--dry-run",
        "--host-root", "/mnt/tank/TheCreatorsPool/Creators_Club",
    ])
    rc = install_dashboard_app.main()
    err = capsys.readouterr().err

    assert rc == 1
    assert "REFUSING" in err
    assert "--allow-any-host-root" in err


def test_install_dashboard_swap_never_guts_app(monkeypatch, capsys):
    cmds: list = []

    def record(cmd, dry_run=False, timeout=120):
        cmds.append(cmd)
        return 0, "", ""

    monkeypatch.setattr(install_dashboard_app, "run_ssh", record)
    monkeypatch.setattr(sys, "argv", ["install_dashboard_app.py", "--dry-run"])
    rc = install_dashboard_app.main()
    capsys.readouterr()

    assert rc == 0
    joined = "\n".join(cmds)
    # the old "empty it, then copy into it" sequence is gone
    assert "-mindepth 1 -delete" not in joined
    # replaced by build-aside + rename, with a rollback
    assert "/app.new" in joined
    assert "/app.old." in joined
    assert "mv " in joined
    # and the verification covers bytes, not just file count -- read off the
    # directory entries rather than by cat-ing the whole tree (SERVER-6)
    assert "-printf '%s" in joined


def _fake_health(monkeypatch, payload, seen):
    """Stand in for requests.get inside check_health.check_dashboard."""
    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return payload

    def fake_get(url, timeout=None, headers=None):
        seen["url"], seen["headers"] = url, headers or {}
        return _Resp()

    import types
    fake_requests = types.ModuleType("requests")
    fake_requests.get = fake_get
    monkeypatch.setitem(sys.modules, "requests", fake_requests)


def test_check_dashboard_handles_the_trimmed_unauthenticated_health_body(monkeypatch, capsys):
    """/api/v1/health answers an unauthenticated caller with {"ok","version"}
    only -- its full body is the client roster and the route is open by
    design. This check must report liveness, not invent a verdict about a
    collector it was not allowed to see."""
    seen: dict = {}
    _fake_health(monkeypatch, {"ok": True, "version": "0.4.4"}, seen)
    monkeypatch.delenv("DASH_REPORT_TOKEN", raising=False)

    check_health.check_dashboard("http://nas:8480", dry_run=False)
    out = capsys.readouterr().out
    assert "0.4.4" in out
    assert "DASH_REPORT_TOKEN" in out          # tells the operator how to get more
    assert "OK" in out.upper()
    assert seen["headers"] == {}

    # ok=False (collector blind) still fails the check
    _fake_health(monkeypatch, {"ok": False, "version": "0.4.4"}, seen)
    check_health.check_dashboard("http://nas:8480", dry_run=False)
    assert "FAIL" in capsys.readouterr().out.upper()


def test_check_dashboard_sends_the_report_token_when_it_has_one(monkeypatch, capsys):
    seen: dict = {}
    _fake_health(monkeypatch, {"ok": True, "version": "0.4.4",
                               "syncthing_reachable": True}, seen)
    monkeypatch.setenv("DASH_REPORT_TOKEN", "sekrit")

    check_health.check_dashboard("http://nas:8480", dry_run=False)
    assert seen["headers"]["X-CCSync-Token"] == "sekrit"
    assert "syncthing reachable" in capsys.readouterr().out


def test_install_dashboard_keeps_editors_out_of_data_and_the_venv(monkeypatch, capsys):
    """AUDIT C-2: `chown -R 3000:3001 <root>/data` + `chmod 770` handed
    group `editors` -- every one of whom has a real shell account on the NAS
    -- write access to the directory run.sh exec'd `venv/bin/python` out of.
    That is arbitrary code execution as the dashboard user in a container
    holding TRUENAS_PW. data/ is now group 3000, and the venv has its own
    volume at mode 700."""
    cmds: list = []

    def record(cmd, dry_run=False, timeout=120):
        cmds.append(cmd)
        return 0, "", ""

    monkeypatch.setattr(install_dashboard_app, "run_ssh", record)
    monkeypatch.setattr(sys, "argv", ["install_dashboard_app.py", "--dry-run"])
    assert install_dashboard_app.main() == 0
    capsys.readouterr()
    joined = "\n".join(cmds)

    # Per-command, not over the whole run: the b-roll ARCHIVE root is prepared
    # by its own later command and is deliberately broll:EDITORS 2770, exactly
    # like Projects/ -- editors browse it over SMB as P:\Assets\B-roll Archive.
    # This assertion is about the app's private dirs, which is where C-2 was.
    dirs_cmd = next(c for c in cmds if "/venv" in c and "mkdir -p" in c)
    assert "3000:3001" not in dirs_cmd, "the editors group must not own data/ or venv/"
    assert "chown -R 3000:3000" in dirs_cmd
    assert "/data" in dirs_cmd and "chmod 770" in dirs_cmd
    assert "/venv" in dirs_cmd and "chmod 700" in dirs_cmd
    # ...and the archive root that IS mounted gets prepared, with the editors
    # group and without the 770 that would lock them out of their own archive.
    archive = next(c for c in cmds if common.DEFAULT_BROLL_ARCHIVE_ROOT in c)
    assert "chown 3000:3001" in archive and "chmod 2770" in archive
    assert "chmod 770 " not in archive
    assert "broll-data" not in joined, (
        "<host-root>/broll-data was never mounted by anything"
    )
    # a pre-C-2 deployment's editor-writable venv is MOVED aside, never
    # deleted (standing no-deletion rule)
    retire = next(c for c in cmds if "venv.quarantined." in c)
    assert "/data/venv" in retire and " mv " in retire
    assert "rm -rf" not in retire

    volumes = _dashboard_service()["volumes"]
    assert any(v.endswith("/venv:/venv") for v in volumes)
    assert not any("/data/venv" in v for v in volumes)


# --------------------------------------------------------------------------
# --dry-run prints the whole compose body -- and must print no secret in it
# --------------------------------------------------------------------------

# Distinctive, and each one a plausible real value for its variable: the point
# is to grep the ENTIRE dry-run transcript for them afterwards.
DRY_RUN_SECRETS = {
    "SYNCTHING_API_KEY": "syncthingKEYsentinel7Xq2",
    "DASH_REPORT_TOKEN": "reportTOKENsentinel5f0c7dd7ab034350",
    "DASH_SESSION_SECRET": "sessionSECRETsentinel0f34e25168de40",
    # Strong on purpose: a weak one is legitimately quoted back in the refusal
    # message (it is a placeholder from a published list), which would make
    # this test assert the wrong thing.
    "BROLL_INGEST_TOKEN": "ingestTOKENsentinel4b7d1e9a03c6",
    "TRUENAS_PW": "truenasPWsentinelHunter2xyz",
}


def _dry_run_transcript(monkeypatch, capsys, env=None) -> str:
    """Everything a --dry-run puts in front of the admin: stdout, stderr, and
    every command it would have sent over SSH."""
    cmds: list = []

    def record(cmd, dry_run=False, timeout=120):
        cmds.append(cmd)
        return 0, "", ""

    for name, value in (env if env is not None else DRY_RUN_SECRETS).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(install_dashboard_app, "run_ssh", record)
    monkeypatch.setattr(sys, "argv", ["install_dashboard_app.py", "--dry-run"])
    assert install_dashboard_app.main() == 0
    captured = capsys.readouterr()
    return "\n".join([captured.out, captured.err, *cmds])


def test_dry_run_never_prints_a_secret(monkeypatch, capsys):
    """--dry-run exists so an admin can eyeball the compose body before a real
    deploy, and it printed four live credentials in the clear to do it: only
    TRUENAS_PW was masked. Terminal scrollback and pasted bug reports are not
    where the fleet's report token belongs."""
    transcript = _dry_run_transcript(monkeypatch, capsys)

    for name, value in DRY_RUN_SECRETS.items():
        assert value not in transcript, f"{name} leaked into --dry-run output"
        assert f"<{name}-not-shown-in-dry-run>" in transcript, (
            f"{name} is not represented in the compose body at all"
        )


def test_dry_run_still_shows_the_configuration_it_exists_to_show(monkeypatch, capsys):
    """Masking the class, not the body: everything that is not a credential
    stays readable, or the dry-run cannot do its job."""
    transcript = _dry_run_transcript(monkeypatch, capsys)

    for visible in (install_dashboard_app.LAN_BIND_IP,
                    install_dashboard_app.TAILNET_BIND_IP,
                    install_dashboard_app.DEFAULT_IMAGE,
                    install_dashboard_app.DEFAULT_HOST_ROOT,
                    common.DEFAULT_BROLL_ARCHIVE_ROOT,
                    "/api/v1/health", "DASH_DB_PATH", "3000:3001"):
        assert visible in transcript, f"--dry-run no longer shows {visible!r}"


def test_dry_run_says_whether_a_secret_is_set_without_saying_what_it_is(monkeypatch, capsys):
    """Whether DASH_SESSION_SECRET is configured is not itself a secret -- and
    a blank one logs the whole fleet out on deploy, so the dry-run must still
    distinguish the two states."""
    env = dict(DRY_RUN_SECRETS)
    monkeypatch.delenv("SYNCTHING_API_KEY", raising=False)
    env.pop("SYNCTHING_API_KEY")
    transcript = _dry_run_transcript(monkeypatch, capsys, env)

    assert "<SYNCTHING_API_KEY-unset-dry-run>" in transcript
    assert "<DASH_REPORT_TOKEN-not-shown-in-dry-run>" in transcript


def test_every_secret_bearing_compose_key_is_masked(monkeypatch, capsys):
    """The list is the fix, not the four instances. A new credential added to
    compose_config and not to SECRET_ENV_VARS is a new leak, so check the
    membership rather than trusting the list to be maintained."""
    env_keys = set(_dashboard_service()["environment"])
    assert set(install_dashboard_app.SECRET_ENV_VARS) <= env_keys, (
        "SECRET_ENV_VARS names an env var the compose body no longer carries"
    )
    # Every value that came in through a secret-shaped parameter is masked --
    # i.e. nothing in SECRET_ENV_VARS is passed through raw somewhere else too.
    transcript = _dry_run_transcript(monkeypatch, capsys)
    for name in install_dashboard_app.SECRET_ENV_VARS:
        assert transcript.count(f"<{name}-") >= 1


def test_masking_happens_after_validation_not_before(monkeypatch, capsys):
    """Order matters: the placeholder is 38 characters and would sail past the
    length check the real value was meant to face. Validation must see the real
    token, so a placeholder BROLL_INGEST_TOKEN is still refused."""
    # The mask itself would pass a naive strength check -- which is exactly why
    # it must never reach one.
    mask = install_dashboard_app.dry_run_mask("BROLL_INGEST_TOKEN", "anything")
    assert install_dashboard_app.weak_ingest_token(mask) is None

    env = dict(DRY_RUN_SECRETS, BROLL_INGEST_TOKEN="REPLACE_ME")
    monkeypatch.setenv("DASH_BROLL_ENABLED", "1")
    transcript = _dry_run_transcript(monkeypatch, capsys, env)

    assert "would FAIL" in transcript and "BROLL_INGEST_TOKEN" in transcript
    assert "REPLACE_ME" in transcript, (
        "the refusal names the placeholder it found -- a published constant, "
        "and the only way the message is actionable"
    )
    # ...and the compose body still carries the mask, not the placeholder value
    assert "'BROLL_INGEST_TOKEN': '<BROLL_INGEST_TOKEN-" in transcript


def test_a_real_deploy_still_receives_the_actual_secrets(monkeypatch):
    """The masking is for the printed body only. A real deploy must hand the
    container the real values, and must still refuse to run without the three
    mandatory ones."""
    for name, value in DRY_RUN_SECRETS.items():
        monkeypatch.setenv(name, value)

    real = install_dashboard_app.resolve_compose_secrets(
        False, DRY_RUN_SECRETS["BROLL_INGEST_TOKEN"])
    assert real == DRY_RUN_SECRETS, "a real deploy would ship masked placeholders"

    masked = install_dashboard_app.resolve_compose_secrets(
        True, DRY_RUN_SECRETS["BROLL_INGEST_TOKEN"])
    assert all(v.startswith("<") and v.endswith(">") for v in masked.values())

    monkeypatch.delenv("DASH_SESSION_SECRET")
    with pytest.raises(common.EnvError):
        install_dashboard_app.resolve_compose_secrets(False, "x")


# --------------------------------------------------------------------------
# compose.yaml and the compose dict must not drift apart
# --------------------------------------------------------------------------

COMPOSE_YAML = (Path(__file__).resolve().parents[2] / "dashboard" / "deploy"
                / "compose.yaml")


def _compose_text() -> str:
    return COMPOSE_YAML.read_text(encoding="utf-8")


def _dashboard_service() -> dict:
    return install_dashboard_app.compose_config(
        8480, "/mnt/tank/apps/ccsync-dashboard", "http://gui:8384", "k", "t",
        "s", "truenas_admin", "h", "u", "pw",
    )["services"]["dashboard"]


def test_compose_yaml_exists():
    assert COMPOSE_YAML.is_file(), f"{COMPOSE_YAML} moved -- update this test"


def test_image_tag_matches_compose():
    m = re.search(r"^\s*image:\s*(\S+)\s*$", _compose_text(), re.M)
    assert m, "no image: line in compose.yaml"
    assert m.group(1) == install_dashboard_app.DEFAULT_IMAGE
    assert m.group(1) != "python:3.12-slim", "the base image must stay pinned"
    assert _dashboard_service()["image"] == m.group(1)


def test_bind_defaults_match_compose():
    text = _compose_text()
    lan = re.search(r"\$\{DASH_BIND_LAN:-([^}]+)\}", text)
    tail = re.search(r"\$\{DASH_BIND_TAILNET:-([^}]+)\}", text)
    assert lan and tail, "compose.yaml no longer takes the bind IPs from env"
    assert lan.group(1) == install_dashboard_app.LAN_BIND_IP
    assert tail.group(1) == install_dashboard_app.TAILNET_BIND_IP
    # ...and the dict resolves them rather than shipping a literal ${...}
    ports = _dashboard_service()["ports"]
    assert ports == [f"{lan.group(1)}:8480:8480", f"{tail.group(1)}:8480:8480"]
    assert not any("${" in p for p in ports)


def test_bind_addresses_are_overridable(monkeypatch):
    svc = install_dashboard_app.compose_config(
        8480, "/root", "http://gui:8384", "k", "t", bind_lan="10.0.0.5",
        bind_tailnet="100.64.1.2",
    )["services"]["dashboard"]
    assert svc["ports"] == ["10.0.0.5:8480:8480", "100.64.1.2:8480:8480"]


def test_env_keys_match_compose():
    text = _compose_text()
    env_block = text.split("environment:", 1)[1].split("\n    ports:", 1)[0]
    yaml_keys = set(re.findall(r"^\s{6}([A-Z][A-Z0-9_]*):", env_block, re.M))
    dict_keys = set(_dashboard_service()["environment"])
    assert yaml_keys == dict_keys, (
        f"compose.yaml and compose_config() env drifted: "
        f"only in yaml={sorted(yaml_keys - dict_keys)}, "
        f"only in dict={sorted(dict_keys - yaml_keys)}"
    )
    assert "TRUENAS_VERIFY_SSL" in dict_keys


def test_volumes_match_compose():
    """The env keys have had a drift test for a while; the volume list did not,
    and that is precisely where the b-roll deploy broke. Two bind mounts were
    added to both files, one of which was never populated and one of which
    pointed at a directory nothing prepared -- neither visible from the outside,
    because a missing mount just makes the feature quietly absent.
    """
    text = _compose_text()
    vol_block = text.split("\n    volumes:", 1)[1].split("\n    restart:", 1)[0]
    yaml_vols = [
        line.strip().lstrip("- ").strip().strip('"').strip("'")
        for line in vol_block.splitlines()
        if line.strip().startswith("- ")
    ]
    dict_vols = _dashboard_service()["volumes"]
    assert yaml_vols == dict_vols, (
        f"compose.yaml and compose_config() volumes drifted:\n"
        f"  only in yaml={[v for v in yaml_vols if v not in dict_vols]}\n"
        f"  only in dict={[v for v in dict_vols if v not in yaml_vols]}"
    )
    # ...and the two b-roll mounts are the ones with a history: the code mount
    # must be read-only like /app, and the data mount must be the shared
    # archive (common.DEFAULT_BROLL_ARCHIVE_ROOT), not some private directory
    # under the app root that nothing ever writes to.
    assert "/mnt/tank/apps/ccsync-dashboard/broll-web:/broll-app:ro" in dict_vols
    assert f"{common.DEFAULT_BROLL_ARCHIVE_ROOT}:/broll-data:rw" in dict_vols
    assert not any("broll-data:/broll-data" in v for v in dict_vols), (
        "the b-roll data mount is the shared archive, not <host-root>/broll-data"
    )


def test_truenas_verify_ssl_defaults_to_current_behaviour():
    assert _dashboard_service()["environment"]["TRUENAS_VERIFY_SSL"] == "0"
    on = install_dashboard_app.compose_config(
        8480, "/root", "http://gui:8384", "k", "t", truenas_verify_ssl="1",
    )["services"]["dashboard"]
    assert on["environment"]["TRUENAS_VERIFY_SSL"] == "1"


def test_healthcheck_matches_compose():
    text = _compose_text()
    assert "healthcheck:" in text, "compose.yaml lost its healthcheck"
    hc = _dashboard_service()["healthcheck"]
    assert hc["test"][0] == "CMD-SHELL"
    assert "/api/v1/health" in hc["test"][1]
    # the probe itself, character for character (YAML double-quoted scalar)
    m = re.search(r'test:\s*\["CMD-SHELL",\s*"(.*)"\]', text)
    assert m, "compose.yaml healthcheck is no longer a CMD-SHELL list"
    assert m.group(1).replace('\\"', '"') == hc["test"][1]
    for field, value in (("interval", hc["interval"]), ("timeout", hc["timeout"]),
                         ("retries", str(hc["retries"])),
                         ("start_period", hc["start_period"])):
        assert re.search(rf"^\s*{field}:\s*{re.escape(str(value))}\s*$", text, re.M), (
            f"healthcheck {field} drifted from compose.yaml"
        )


def test_healthcheck_follows_the_port():
    hc = install_dashboard_app.healthcheck_config(9999)
    assert "127.0.0.1:9999/api/v1/health" in hc["test"][1]


def test_local_manifest_counts_bytes():
    count, size = install_dashboard_app.local_manifest()
    assert count > 0 and size > 0


def _seed_install_dirs(tmp_path):
    """(root, staging, count, bytes) -- a populated staging tree, a live app/."""
    root = tmp_path / "root"
    (root / "app" / "deploy").mkdir(parents=True)
    (root / "app" / "deploy" / "run.sh").write_text("OLD CODE\n", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "dashboard.db").write_text("PRECIOUS\n", encoding="utf-8")
    staging = tmp_path / "staging"
    (staging / "deploy").mkdir(parents=True)
    (staging / "deploy" / "run.sh").write_text("NEW CODE\n", encoding="utf-8")
    (staging / "src.py").write_text("x = 1\n", encoding="utf-8")
    files = [p for p in staging.rglob("*") if p.is_file()]
    return root, staging, len(files), sum(p.stat().st_size for p in files)


@needs_bash
def test_swap_script_installs_and_keeps_previous_code(tmp_path):
    root, staging, count, size = _seed_install_dirs(tmp_path)
    script = install_dashboard_app.build_swap_script(
        str(root), str(staging), str(root / "app.new"), str(root / "app.old.20260725120000"),
        expected_count=count, expected_bytes=size,
    )
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert (root / "app" / "deploy" / "run.sh").read_text() == "NEW CODE\n"
    # previous code preserved, not deleted
    assert (root / "app.old.20260725120000" / "deploy" / "run.sh").read_text() == "OLD CODE\n"
    # data/ never involved
    assert (root / "data" / "dashboard.db").read_text() == "PRECIOUS\n"
    assert not staging.exists()
    assert not (root / "app.new").exists()


@needs_bash
def test_swap_script_leaves_app_intact_when_verification_fails(tmp_path):
    root, staging, count, size = _seed_install_dirs(tmp_path)
    # a truncated last file: right count, wrong bytes -- the case a count-only
    # check used to wave through (AUDIT INST-31)
    (staging / "src.py").write_text("", encoding="utf-8")
    script = install_dashboard_app.build_swap_script(
        str(root), str(staging), str(root / "app.new"), str(root / "app.old.20260725120000"),
        expected_count=count, expected_bytes=size,
    )
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == 8
    assert "incomplete" in proc.stderr
    # the live app is exactly as it was
    assert (root / "app" / "deploy" / "run.sh").read_text() == "OLD CODE\n"
    assert not (root / "app.old.20260725120000").exists()


@needs_bash
def test_swap_script_rolls_back_when_the_swap_in_fails(tmp_path):
    root, staging, count, size = _seed_install_dirs(tmp_path)
    script = install_dashboard_app.build_swap_script(
        str(root), str(staging), str(root / "app.new"), str(root / "app.old.20260725120000"),
        expected_count=count, expected_bytes=size,
    )
    # Make the swap-in mv fail: remove the verified candidate tree in the
    # instant between the two renames.
    live = install_dashboard_app.shell_quote(str(root) + "/app")
    candidate = install_dashboard_app.shell_quote(str(root / "app.new"))
    assert f"mv {live}" in script
    sabotage = script.replace(f"mv {live}", f"rm -rf {candidate}; mv {live}", 1)
    proc = run_remote_script(sabotage, tmp_path)

    assert proc.returncode == 9
    assert "previous code restored" in proc.stderr
    assert (root / "app" / "deploy" / "run.sh").read_text() == "OLD CODE\n"


# --------------------------------------------------------------------------
# SEC-2 -- the sudo password reaches the NAS on stdin, not on the command line
# --------------------------------------------------------------------------

def test_host_key_pin_reads_env_and_flag(monkeypatch):
    monkeypatch.setattr(common, "_HOST_KEY_PIN", "")
    monkeypatch.setenv("CCSYNC_SSH_HOSTKEY", "ssh-ed25519 FROMENV")
    assert common.host_key_pin() == "ssh-ed25519 FROMENV"
    common.set_host_key_pin("ssh-ed25519 FROMFLAG")
    try:
        assert common.host_key_pin() == "ssh-ed25519 FROMFLAG"   # flag wins
    finally:
        common.set_host_key_pin("")


def test_parse_host_key_accepts_the_shapes_admins_paste():
    paramiko = pytest.importorskip("paramiko")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    pub = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    for variant in (pub, f"{pub} comment@host", f"192.168.0.102 {pub}"):
        keytype, key = common._parse_host_key(variant)
        assert keytype == "ssh-ed25519"
        assert isinstance(key, paramiko.PKey)
    for bad in ("", "garbage", "ssh-ed25519 !!notbase64!!", "ssh-magic AAAA"):
        with pytest.raises(common.EnvError):
            common._parse_host_key(bad)


def test_run_ssh_never_puts_the_password_in_the_command():
    assert "SUDO_PW=" not in common.SUDO_PW_PREAMBLE
    assert "read -r SUDO_PW" in common.SUDO_PW_PREAMBLE


@needs_bash
def test_sudo_pw_preamble_consumes_exactly_one_stdin_line(tmp_path):
    script = common.SUDO_PW_PREAMBLE + 'echo "got:$SUDO_PW"\ncat\n'
    script_path = tmp_path / "remote.sh"
    script_path.write_text(script, encoding="utf-8", newline="\n")
    proc = subprocess.run([BASH, "remote.sh"], cwd=str(tmp_path),
                          input="s3cr3t p/w\nleftover\n",
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    # the password line was consumed by the preamble, verbatim, and only it
    assert proc.stdout.splitlines()[0] == "got:s3cr3t p/w"
    assert "leftover" in proc.stdout


# --------------------------------------------------------------------------
# B24 -- the 25.10 filtered GET /app returns [] even when the app exists
# --------------------------------------------------------------------------

def test_install_syncthing_app_does_not_use_query_filters(monkeypatch):
    """The middleware was observed returning [] for a filtered GET /app on a
    NAS that HAD the app (2026-07-24 live). With the filter, a re-run
    concluded "not installed", POSTed a create for the live production app,
    got an opaque 422, and told the admin to delete the healthy app.
    install_dashboard_app fetches the full list and filters client-side."""
    import install_syncthing_app

    seen = {}

    def fake_api(method, path, **kwargs):
        seen["method"] = method
        seen["path"] = path
        seen["params"] = kwargs.get("params")
        return _Resp(200, [{"name": "syncthing"}, {"name": "ccsync-dashboard"}])

    monkeypatch.setattr(install_syncthing_app, "truenas_api", fake_api)

    assert install_syncthing_app.app_already_installed(dry_run=False) is True
    assert seen["path"] == "/app"
    assert not seen["params"], "query-filters is the broken call (B24)"


def test_install_syncthing_app_reports_absent_when_the_list_lacks_it(monkeypatch):
    import install_syncthing_app

    monkeypatch.setattr(install_syncthing_app, "truenas_api",
                        lambda *a, **k: _Resp(200, [{"name": "ccsync-dashboard"}]))
    assert install_syncthing_app.app_already_installed(dry_run=False) is False


def test_no_server_script_reintroduces_the_filtered_app_query():
    # Same defect, same fix -- keep every /app caller in step. Comments may
    # mention query-filters (they explain why it is gone); code may not.
    server_dir = Path(__file__).resolve().parents[1]
    for name in ("install_syncthing_app.py", "install_dashboard_app.py"):
        for lineno, line in enumerate((server_dir / name).read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            assert "query-filters" not in line, f"{name}:{lineno} {line.strip()}"


# --------------------------------------------------------------------------
# setup_editor_account -- never setperm/stripacl a SHARED parent dataset
# --------------------------------------------------------------------------

def test_forbidden_home_paths_include_the_shared_homes_dataset():
    """`filesystem.setperm mode:700 stripacl:True` against the homes dataset
    root breaks every other editor's SMB path in. A hand-created account whose
    `home` points at the parent (instead of <parent>/<username>) is exactly how
    you get there -- the create body in main() passes the PARENT by design."""
    for path in ("/", "/nonexistent", "/var/empty", "",
                 setup_editor_account.HOMES_PARENT,
                 setup_editor_account.HOMES_PARENT + "/",
                 "/mnt", "/home", "/root"):
        assert setup_editor_account.is_forbidden_home(path), path


def test_a_real_editor_home_is_not_forbidden():
    assert not setup_editor_account.is_forbidden_home(
        setup_editor_account.HOMES_PARENT + "/jsmith")
    assert not setup_editor_account.is_forbidden_home(
        setup_editor_account.HOMES_PARENT + "/jsmith/")


def test_ensure_home_permissions_refuses_the_shared_parent(monkeypatch, capsys):
    monkeypatch.setattr(
        setup_editor_account, "truenas_api",
        lambda *a, **k: pytest.fail("setperm must never reach the API for a shared parent"))

    assert setup_editor_account.ensure_home_permissions(
        setup_editor_account.HOMES_PARENT, 3010, 3001, "jsmith") is False
    assert "refusing to touch permissions" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Low items: username + device id validation
# --------------------------------------------------------------------------

def test_normalize_username_lowercases_and_validates():
    assert setup_editor_account.normalize_username("JSmith") == "jsmith"
    assert setup_editor_account.normalize_username(" jsmith ") == "jsmith"
    for bad in ("", "1abc", "j smith", "j/smith", "j;rm -rf", "x" * 40):
        with pytest.raises(ValueError):
            setup_editor_account.normalize_username(bad)


def test_normalize_device_id():
    good = "P56IOI7-MZJNU2Y-IQGDREY-DM2MGTI-MGL3BXN-PQ6W5BM-TBBZ4TJ-XZWICQ2"
    assert accept_device.normalize_device_id(good.lower()) == good
    for bad in ("", "ABCD1234-...", good[:-1], good + "-AAAAAAA",
                good.replace("P", "0", 1), good.replace("-", "")):
        with pytest.raises(ValueError):
            accept_device.normalize_device_id(bad)


def test_device_name_warnings_spell_out_the_editor_mapping_contract():
    """KNOWN_BUGS B16: the device NAME is what the dashboard maps to an editor
    account, and that mapping decides which projects the device is shared
    with. A machine name ("alex-laptop") is username-SHAPED, so it used to
    resolve to an editor with no selections and get the device unshared from
    every folder. The dashboard is the only component holding the account
    list, so it does the real check -- this script's job is to make the
    contract impossible to miss."""
    good = "P56IOI7-MZJNU2Y-IQGDREY-DM2MGTI-MGL3BXN-PQ6W5BM-TBBZ4TJ-XZWICQ2"

    # no name at all -> unmapped, said plainly
    [note] = accept_device.check_device_name(good, good)
    assert "UNMAPPED" in note

    # not a username at all -> unmapped
    [note] = accept_device.check_device_name("Alex's Laptop", good)
    assert "UNMAPPED" in note and "username" in note

    # username-shaped -> the contract, because this is the ambiguous case
    [note] = accept_device.check_device_name("alex-laptop", good)
    assert "TrueNAS USERNAME" in note
    assert "machine name" in note
    [note] = accept_device.check_device_name("jsmith", good)
    assert "TrueNAS USERNAME" in note


def test_accept_device_without_folder_id_touches_no_folders(monkeypatch, capsys):
    calls: list = []

    class Resp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_api(method, gui_url, path, api_key, json_body=None, dry_run=False, params=None):
        calls.append((method, path))
        if path == "/rest/cluster/pending/devices":
            return Resp({})
        if path == "/rest/config/devices":
            return Resp([])
        return Resp({})

    monkeypatch.setattr(accept_device, "syncthing_api", fake_api)
    monkeypatch.setattr(sys, "argv", [
        "accept_device.py", "--device-id",
        "P56IOI7-MZJNU2Y-IQGDREY-DM2MGTI-MGL3BXN-PQ6W5BM-TBBZ4TJ-XZWICQ2",
        "--device-name", "jsmith",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
    ])
    rc = accept_device.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "added device" in out
    assert not any("/rest/config/folders" in path for _, path in calls)
    assert "no folder was touched" in out


def test_accept_device_still_shares_when_folder_id_given(monkeypatch, capsys):
    calls: list = []

    class Resp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_api(method, gui_url, path, api_key, json_body=None, dry_run=False, params=None):
        calls.append((method, path, json_body))
        if path == "/rest/cluster/pending/devices":
            return Resp({})
        if path == "/rest/config/devices":
            return Resp([])
        if path.startswith("/rest/config/folders/") and method == "GET":
            return Resp({"id": "2026-cct-season-1", "devices": []})
        return Resp({})

    monkeypatch.setattr(accept_device, "syncthing_api", fake_api)
    monkeypatch.setattr(sys, "argv", [
        "accept_device.py", "--device-id",
        "P56IOI7-MZJNU2Y-IQGDREY-DM2MGTI-MGL3BXN-PQ6W5BM-TBBZ4TJ-XZWICQ2",
        "--folder-id", "2026-cct-season-1",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
    ])
    rc = accept_device.main()
    out = capsys.readouterr().out

    assert rc == 0
    put = [c for c in calls if c[0] == "PUT" and c[1].startswith("/rest/config/folders/")]
    assert len(put) == 1
    assert put[0][2]["devices"][0]["deviceID"].startswith("P56IOI7-")
    assert "enforcement will reconcile" in out


def test_accept_device_renames_an_existing_device(monkeypatch, capsys):
    calls: list = []
    device_id = "P56IOI7-MZJNU2Y-IQGDREY-DM2MGTI-MGL3BXN-PQ6W5BM-TBBZ4TJ-XZWICQ2"

    class Resp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_api(method, gui_url, path, api_key, json_body=None, dry_run=False, params=None):
        calls.append((method, path, json_body))
        if path == "/rest/config/devices":
            return Resp([{"deviceID": device_id, "name": "DESKTOP-7F2K"}])
        return Resp({})

    monkeypatch.setattr(accept_device, "syncthing_api", fake_api)
    monkeypatch.setattr(sys, "argv", [
        "accept_device.py", "--device-id", device_id, "--device-name", "jsmith",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
    ])
    rc = accept_device.main()
    out = capsys.readouterr().out

    assert rc == 0
    renames = [c for c in calls if c[0] == "PUT" and c[1].endswith(device_id)]
    assert renames and renames[0][2]["name"] == "jsmith"
    assert "renamed device" in out


def test_accept_device_rejects_malformed_id(monkeypatch, capsys):
    monkeypatch.setattr(accept_device, "syncthing_api",
                        lambda *a, **k: pytest.fail("must not call Syncthing"))
    monkeypatch.setattr(sys, "argv", [
        "accept_device.py", "--device-id", "not-a-device", "--folder-id", "x", "--dry-run",
    ])
    assert accept_device.main() == 1
    assert "not a Syncthing device ID" in capsys.readouterr().err


# --------------------------------------------------------------------------
# --dry-run opens no connection, in every script
# --------------------------------------------------------------------------

DRY_RUN_ARGVS = [
    ["setup_tree.py", "--project-rel-path", "2026/CCT/Season 1", "--dry-run"],
    ["write_marker.py", "--project-rel-path", "2026/CCT/Season 1", "--dry-run"],
    ["setup_syncthing_folder.py", "--project-rel-path", "2026/CCT/Season 1", "--dry-run"],
    ["accept_device.py", "--device-id",
     "P56IOI7-MZJNU2Y-IQGDREY-DM2MGTI-MGL3BXN-PQ6W5BM-TBBZ4TJ-XZWICQ2",
     "--folder-id", "2026-cct-season-1", "--dry-run"],
    ["accept_device.py", "--device-id",
     "P56IOI7-MZJNU2Y-IQGDREY-DM2MGTI-MGL3BXN-PQ6W5BM-TBBZ4TJ-XZWICQ2", "--dry-run"],
    ["install_syncthing_app.py", "--dry-run"],
    ["install_dashboard_app.py", "--dry-run"],
    ["check_health.py", "--dry-run"],
    ["setup_editor_account.py", "--name", "jsmith", "--ssh-pubkey-file", "nope.pub",
     "--dry-run"],
]


@pytest.mark.parametrize("argv", DRY_RUN_ARGVS, ids=[a[0] for a in DRY_RUN_ARGVS])
def test_dry_run_opens_no_connection(argv, monkeypatch, capsys):
    import importlib

    def no_ssh(*a, **k):
        raise AssertionError("--dry-run must not open an SSH connection")

    def no_http(*a, **k):
        raise AssertionError("--dry-run must not make an HTTP call")

    monkeypatch.setattr(common, "ssh_client", no_ssh)
    import requests
    monkeypatch.setattr(requests, "request", no_http)
    monkeypatch.setattr(requests, "get", no_http)
    monkeypatch.setattr(sys, "argv", argv)

    mod = importlib.import_module(argv[0][:-3])
    rc = mod.main()
    capsys.readouterr()
    assert rc == 0


# --- the PO-token provider is one component in two processes ----------------

def test_the_pot_provider_plugin_and_image_are_the_same_version():
    """The yt-dlp plugin (pip, in the dashboard venv) and the server it talks
    to (a sidecar image) are one component split across two processes, and
    bgutil ships them as a matched pair. They are pinned in two different
    files, so nothing but this test stops a bump to one from silently leaving
    the other behind -- which would fail at runtime as "no formats found",
    indistinguishable from the bot check it exists to defeat (2026-08-11).
    """
    import re

    reqs = (Path(install_dashboard_app.__file__).resolve().parents[1]
            / "dashboard" / "deploy" / "requirements.txt").read_text(encoding="utf-8")
    m = re.search(r"^bgutil-ytdlp-pot-provider==([0-9][^\s#]*)", reqs, re.M)
    assert m, "requirements.txt no longer pins bgutil-ytdlp-pot-provider exactly"
    pinned = m.group(1)

    assert pinned == install_dashboard_app.POT_PROVIDER_VERSION, (
        f"plugin pin {pinned} != POT_PROVIDER_VERSION "
        f"{install_dashboard_app.POT_PROVIDER_VERSION}")
    assert install_dashboard_app.POT_PROVIDER_IMAGE.startswith(
        f"brainicism/bgutil-ytdlp-pot-provider:{pinned}"), (
        f"image tag {install_dashboard_app.POT_PROVIDER_IMAGE} does not carry {pinned}")


def test_the_pot_provider_is_reachable_only_from_inside_the_compose_network():
    """It mints tokens for anyone who asks. Publishing a port would offer that
    to the whole LAN and tailnet; the dashboard reaches it by service name on
    the compose network instead."""
    svc = install_dashboard_app.compose_config(
        8480, "/mnt/tank/apps/ccsync-dashboard", "http://x:8384", "k", "t",
    )["services"][install_dashboard_app.POT_PROVIDER_SERVICE]
    assert "ports" not in svc, "the PO-token provider must not publish a port"


# --------------------------------------------------------------------------
# The 2026-08-14 bug hunt -- the privileged half of three remote reads
# --------------------------------------------------------------------------

# SERVER-4 -- a marker that cannot be READ is not a marker that is ABSENT

@needs_bash
def test_the_marker_read_answers_present_and_absent(tmp_path):
    """The two ordinary states, through the real generated shell."""
    base = tmp_path / "Season 1"
    base.mkdir()
    cmd = common.build_marker_read_cmd("Season 1")

    proc = run_remote_script(cmd, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "MARKER-ABSENT" in proc.stdout
    assert "MARKER-PRESENT" not in proc.stdout

    (base / MARKER_FILENAME).write_text(
        json.dumps({"slug": "2026-cct-season-1"}), encoding="utf-8", newline="\n")
    proc = run_remote_script(cmd, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "MARKER-PRESENT" in proc.stdout
    assert "2026-cct-season-1" in proc.stdout


@needs_bash
def test_a_refused_sudo_never_reports_the_marker_absent(tmp_path):
    """SERVER-4 (2026-08-14): THE regression. The SSH account can log in but
    its sudo is revoked or locked out. The old shell put `sudo test -e` in an
    `if` CONDITION -- exempt from the exit status -- so this printed
    MARKER-ABSENT and exited 0, choose_folder_id took the slugify(rel) branch,
    and a moved project got a SECOND Syncthing folder over the same directory:
    shared with nobody, failing the collector every cycle, cleaned up by
    nothing."""
    base = tmp_path / "Season 1"
    base.mkdir()
    (base / MARKER_FILENAME).write_text(
        json.dumps({"slug": "2026-cct-season-1"}), encoding="utf-8", newline="\n")

    proc = run_remote_script(common.build_marker_read_cmd("Season 1"), tmp_path,
                             sudo_stub=SUDO_REFUSING_STUB)

    assert proc.returncode == common.MARKER_READ_RC
    assert "MARKER-ABSENT" not in proc.stdout
    assert "MARKER-PRESENT" not in proc.stdout
    assert common.MARKER_UNREADABLE_SENTINEL in proc.stderr


@needs_bash
def test_the_refused_read_reaches_choose_folder_id_as_a_refusal(tmp_path, monkeypatch):
    """End to end from the shell's real answer: a script that cannot read the
    marker must refuse, not derive an identity from the current path."""
    proc = run_remote_script(common.build_marker_read_cmd("Season 1"), tmp_path,
                             sudo_stub=SUDO_REFUSING_STUB)
    monkeypatch.setattr(
        setup_syncthing_folder, "run_ssh",
        lambda cmd, dry_run=False, timeout=120: (proc.returncode, proc.stdout,
                                                 proc.stderr))
    status, detail = setup_syncthing_folder.read_marker_slug(
        "/mnt/tank/x/Projects", "2027/Moved/Elsewhere")
    assert status == setup_syncthing_folder.MARKER_UNAVAILABLE

    fid, _source, refusal = setup_syncthing_folder.choose_folder_id(
        "2027/Moved/Elsewhere", "", status, detail)
    assert fid == "" and "REFUSING" in refusal


def test_write_marker_refuses_rather_than_writing_a_fresh_identity_blind(monkeypatch,
                                                                         capsys):
    """write_marker's remote write is UNCONDITIONAL -- only the Python side
    guards a change behind --force -- so a read that wrongly says "absent"
    reassigns a live project's slug without ever showing the `old -> new`
    line."""
    monkeypatch.setattr(write_marker, "run_ssh",
                        lambda *a, **k: (0, "sudo: a password is required\n", ""))
    with pytest.raises(SystemExit):
        write_marker.read_existing_marker("/mnt/tank/x/Projects/2026/CCT/Season 1",
                                          dry_run=False)
    assert "REFUSING to write a fresh one" in capsys.readouterr().err


def test_both_marker_readers_use_the_one_builder():
    """A second copy of "how do I read a marker" is how one of them keeps the
    `if sudo test -e` shape after the other loses it."""
    server_dir = Path(__file__).resolve().parents[1]
    for name in ("setup_syncthing_folder.py", "write_marker.py"):
        text = (server_dir / name).read_text(encoding="utf-8")
        assert "build_marker_read_cmd" in text, name
        assert 'sudo -S -p "" test -e' not in text, name


# SERVER-9 -- setup_tree's idempotency probe must see what root sees

def test_setup_tree_probes_with_the_same_privilege_as_the_mkdir():
    """TRUENAS_USER has no traverse rights on the 770 dataset (check_health
    and setup_syncthing_folder both say so), so a bare `[ -d ]` false-negatived
    on every template folder and a re-run printed eight `created:` lines --
    indistinguishable from having just built a fresh tree at a mistyped path."""
    base = "/p/2026/CCT/Season 1"
    script = build_remote_script(base, "broll", "editors",
                                 slug="2026-cct-season-1", projects_root="/p")
    assert "if [ -d '" not in script, "an unprivileged probe is back"
    for rel in setup_tree.project_relative_dirs():
        probe = f'sudo -S -p "" test -d {common.shell_quote(base + "/" + rel)}'
        assert probe in script, rel


@needs_bash
def test_a_setup_tree_rerun_reports_exists_not_created(tmp_path):
    base_rel = "Projects/2026/CCT/Season 1"
    script = build_remote_script(base_rel, "broll", "editors",
                                 slug="2026-cct-season-1", projects_root="Projects")

    first = run_remote_script(script, tmp_path)
    assert first.returncode == 0, first.stderr
    assert "created: Audio/Music" in first.stdout

    second = run_remote_script(script, tmp_path)
    assert second.returncode == 0, second.stderr
    assert "created:" not in second.stdout, second.stdout
    assert "exists: Audio/Music" in second.stdout


# SERVER-3 -- /user's group fields hold DATABASE ids, not unix gids

def _fake_group_and_users(monkeypatch, group_row, users):
    def fake_api(method, path, **kwargs):
        if path == "/group":
            return _Resp(200, [group_row])
        return _Resp(200, users)

    monkeypatch.setattr(check_health, "truenas_api", fake_api)


def test_editor_accounts_are_found_by_the_groups_database_id(monkeypatch, capsys):
    """The unix gid and the database id are different numbers, and
    setup_editor_account.ensure_group returns them as two values for exactly
    this reason ("passing the gid fails validation with 'This group does not
    exist'"). Testing the gid found no members on a fully provisioned NAS, so
    check 6 always FAILed and check_health -- whose whole contract is "exit
    code = number of failed checks" -- could never exit 0."""
    check_health.RESULTS.clear()
    _fake_group_and_users(
        monkeypatch,
        {"group": check_health.EDITORS_GROUP, "id": 41, "gid": 3001},
        [{"username": "jsmith", "groups": [41],
          "group": {"id": 3010, "bsdgrp_gid": 3010}},
         {"username": "rusk", "groups": [],
          "group": {"id": 41, "bsdgrp_gid": 3001}},
         {"username": "nobody", "groups": [], "group": {"id": 1, "bsdgrp_gid": 0}}],
    )

    check_health.check_editor_accounts(dry_run=False)
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "jsmith" in out and "rusk" in out
    assert "nobody" not in out
    assert all(passed for passed, _ in check_health.RESULTS)


def test_the_unix_gid_is_never_used_as_a_membership_key(monkeypatch, capsys):
    """The exact live shape: every editor's row carries the DB id, never the
    gid, and `group` is a nested object that can never equal an int."""
    check_health.RESULTS.clear()
    _fake_group_and_users(
        monkeypatch,
        {"group": check_health.EDITORS_GROUP, "id": 41, "gid": 3001},
        [{"username": "jsmith", "groups": [3001],
          "group": {"id": 3010, "bsdgrp_gid": 3010}}],
    )

    check_health.check_editor_accounts(dry_run=False)
    assert "no members yet" in capsys.readouterr().out
