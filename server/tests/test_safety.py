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


def run_remote_script(script: str, workdir: Path):
    """Execute a generated remote script with a stub sudo. Returns CompletedProcess."""
    bindir = workdir / "stubbin"
    bindir.mkdir(exist_ok=True)
    sudo = bindir / "sudo"
    sudo.write_text(SUDO_STUB, encoding="utf-8", newline="\n")
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


def test_syncthing_folder_refuses_id_collision(monkeypatch, capsys):
    monkeypatch.setattr(
        setup_syncthing_folder, "find_folder",
        lambda *a, **k: {"id": "2026-cct-season-1", "path": "/data/Projects/2026/CCT/Season-1"},
    )
    monkeypatch.setattr(sys, "argv", [
        "setup_syncthing_folder.py", "--project-rel-path", "2026/CCT/Season 1",
        "--gui-url", "http://example.invalid:8384", "--api-key", "k",
    ])
    rc = setup_syncthing_folder.main()
    err = capsys.readouterr().err

    assert rc == 1
    assert "REFUSING" in err
    assert "/data/Projects/2026/CCT/Season-1" in err   # existing
    assert "/data/Projects/2026/CCT/Season 1" in err   # requested


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
    # and the verification covers bytes, not just file count
    assert "wc -c" in joined


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

    assert "3000:3001" not in joined, "the editors group must not own data/ or venv/"
    assert "chown -R 3000:3000" in joined
    assert "/data" in joined and "chmod 770" in joined
    assert "/venv" in joined and "chmod 700" in joined
    # a pre-C-2 deployment's editor-writable venv is MOVED aside, never
    # deleted (standing no-deletion rule)
    retire = next(c for c in cmds if "venv.quarantined." in c)
    assert "/data/venv" in retire and " mv " in retire
    assert "rm -rf" not in retire

    volumes = _dashboard_service()["volumes"]
    assert any(v.endswith("/venv:/venv") for v in volumes)
    assert not any("/data/venv" in v for v in volumes)


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
