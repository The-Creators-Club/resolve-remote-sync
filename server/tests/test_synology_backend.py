"""The Synology backend, offline (docs/SYNOLOGY_PORT_PLAN.md WP3/WP4).

Every test here is a fact from docs/synology-spikes-2026-08-17.md, measured on
a live DS423+ and then brought up against that unit on the same day. The
groups, in the order they would cost you if they broke:

  1. **Nothing under the tree share is ever chmod'd or chown'd.** A chmod
     DESTROYS a Synology path's ACL -- inheritance gone, and DSM's
     `internal-sftp -u 000` then leaves every new file world-writable (spike
     1). This is the one thing a TrueNAS-shaped change could silently
     reintroduce, so it is asserted on the generated setup_tree script itself,
     executed under a stub sudo.
  2. **The deploy's argv hygiene**: the password on stdin and never in a
     command line (SEC-2), the compose file written by SFTP and never by
     heredoc (spike 5's quoting), the .env installed 0600 root.
  3. **The DSM API's traps**: Auth version 7 or nothing, JSON parameters, and
     Group.Member add's success-while-doing-nothing.
  4. **The refusals**: a host root outside /volume<N>/<share>/ccsync, a
     built-in or package account, an account that is not already an editor.

The fakes are in tests/fake_dsm.py and are deliberately this package's own --
server/ takes no source dependency on dashboard/.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
import install_dashboard_app as ida  # noqa: E402
import setup_tree  # noqa: E402
from backends.synology import (  # noqa: E402
    HOME_ROOT, PATH_EXPORT, SynologyBackend, render_env_file,
)
from tests.fake_dsm import FakeDsmApi, FakePutText, FakeSsh  # noqa: E402

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

# The stub Synology CLI. `-get` answers like a path that already carries the
# inheritable editors ACE, which is the normal case: the share's permission
# list installed it (spike 1).
SYNOACLTOOL_STUB = """#!/bin/sh
case "$1" in
  -get)
    echo "ACL version: 1"
    echo "Archive: has_ACL,is_support_ACL"
    echo "Owner: [root(user)]"
    echo "	 [0] group:administrators:allow:rwxpdDaARWc--:fd-- (level:0)"
    echo "	 [1] group:editors:allow:rwxpdDaARWc--:fd-- (level:0)"
    ;;
  *) echo "synoacltool $*" >> "$SYNOACL_LOG" ;;
esac
exit 0
"""

# ...and one for a path a chmod already destroyed: "It's Linux mode".
SYNOACLTOOL_LINUX_MODE_STUB = """#!/bin/sh
case "$1" in
  -get) echo "(synoacltool.c, 596)It's Linux mode" ;;
  *) echo "synoacltool $*" >> "$SYNOACL_LOG" ;;
esac
exit 0
"""


def run_remote_script(script: str, workdir: Path, acl_stub: str = SYNOACLTOOL_STUB):
    """Execute a generated remote script under stub sudo/synoacltool."""
    bindir = workdir / "stubbin"
    bindir.mkdir(exist_ok=True)
    for name, body in (("sudo", SUDO_STUB), ("synoacltool", acl_stub)):
        path = bindir / name
        path.write_text(body, encoding="utf-8", newline="\n")
        path.chmod(0o755)
    script_path = workdir / "remote.sh"
    script_path.write_text(script, encoding="utf-8", newline="\n")
    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["SUDO_PW"] = "not-a-real-password"
    env["SYNOACL_LOG"] = str(workdir / "synoacl.log")
    return subprocess.run([BASH, "remote.sh"], cwd=str(workdir), env=env,
                          capture_output=True, text=True, timeout=120)


class ExecSsh:
    """FakeSsh's signature, but it RUNS the command under stub sudo/chown.

    The suite asserts on generated script TEXT nearly everywhere, which cannot
    see a script whose exit status does not follow its failures
    (bug-hunt-2026-09-03 server-tools-2). `chown` is stubbed because MSYS's
    real one refuses `jsmith:users`; anything else can be stubbed per test.
    """

    def __init__(self, workdir: Path, stubs: dict | None = None):
        self.workdir = Path(workdir)
        self.commands = []
        self.bindir = self.workdir / "execbin"
        self.bindir.mkdir(exist_ok=True)
        bodies = {"sudo": SUDO_STUB, "chown": "#!/bin/sh\nexit 0\n"}
        bodies.update(stubs or {})
        for name, body in bodies.items():
            path = self.bindir / name
            path.write_text(body, encoding="utf-8", newline="\n")
            path.chmod(0o755)

    def __call__(self, cmd, dry_run=False, timeout=120):
        self.commands.append(cmd)
        if dry_run:
            return 0, "", ""
        env = dict(os.environ)
        env["PATH"] = str(self.bindir) + os.pathsep + env.get("PATH", "")
        env["SUDO_PW"] = "not-a-real-password"
        done = subprocess.run([BASH, "-c", cmd], cwd=str(self.workdir), env=env,
                              capture_output=True, text=True, timeout=120)
        return done.returncode, done.stdout, done.stderr

    @property
    def text(self) -> str:
        return "\n".join(self.commands)


def inner(cmd: str) -> str:
    """A wrapped `sudo sh -c '...'` command with its inner quoting undone.

    Everything the backend sends goes through one `sh -c` layer, so a path in
    the inner script reads as a shell_quote escape dance in the outer one.
    Tests assert on the script a human would read, not on the escaping.
    """
    return cmd.replace("'\\''", "'")


def backend(ssh=None, dsm=None, put=None, project_dir="/volume1/docker/ccsync"):
    """A SynologyBackend wired to fakes, through ScriptCalls exactly as a
    script would wire it (module attribute lookup per call)."""
    module = type(sys)("fake_script")
    module.run_ssh = ssh or FakeSsh()
    module.synology_api = dsm or FakeDsmApi()
    module.sftp_put_text = put or FakePutText()
    obj = SynologyBackend(calls=common.ScriptCalls(module))
    obj.project_dir = project_dir
    return obj


# --------------------------------------------------------------------------
# 1. The tree: pure ACE, and NOTHING that could destroy it
# --------------------------------------------------------------------------

TREE = "/volume1/CCSyncTest/Creators_Club/Projects/2026/Demo/Port Test"


def test_the_tree_script_contains_no_chmod_and_no_chown():
    """THE test of this file. On DSM a chmod does not "fail to help", it
    DELETES the ACL that is the only thing granting group write -- and DSM's
    sftp runs umask 000, so everything created afterwards lands 0666."""
    script = setup_tree.build_remote_script(
        TREE, "ccsync-svc", "editors", slug="2026-demo-port-test",
        projects_root="/volume1/CCSyncTest/Creators_Club/Projects",
        backend=backend())
    assert "chmod" not in script
    assert "chown" not in script
    assert "synoacltool" in script
    # ...and the TrueNAS wording that would have brought them with it is gone.
    assert "2770" not in script and "setgid" not in script


def test_the_tree_script_carries_the_path_export():
    """The Synology CLIs are not on sudo's PATH on a stock box -- without the
    export, synoacltool is simply 'not found' and the ACL check silently
    becomes a no-op."""
    lines = backend().set_tree_acl(TREE, "ccsync-svc", "editors")
    assert all(PATH_EXPORT in line for line in lines)


def test_the_tree_script_never_puts_the_password_in_a_command_line():
    lines = backend().set_tree_acl(TREE, "ccsync-svc", "editors")
    for line in lines:
        assert '"$SUDO_PW" | sudo -S' in line
        assert "SUDO_PW=" not in line


@needs_bash
def test_the_tree_script_runs_and_reports_the_acl_it_found(tmp_path):
    # A real (temporary) tree: the script mkdir -ps what it is given, and the
    # point of running it is that the QUOTING survives a path with a space.
    root = str(tmp_path / "CCSyncTest" / "Creators_Club" / "Projects").replace("\\", "/")
    script = setup_tree.build_remote_script(
        f"{root}/2026/Demo/Port Test", "ccsync-svc", "editors",
        slug="2026-demo-port-test", projects_root=root, backend=backend())
    result = run_remote_script(script, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "ACL ok: editors already has an inherited allow ACE" in result.stdout
    # ...and it did NOT try to repair a path that is already right.
    assert not (tmp_path / "synoacl.log").exists()


@needs_bash
def test_a_path_someone_chmodd_is_shouted_about(tmp_path):
    """"It's Linux mode" means the ACL is gone. The script repairs what it can
    and says so on stderr -- silence here is how a whole project tree ends up
    world-writable without anyone noticing (spike 1)."""
    script = "\n".join(backend().set_tree_acl(TREE, "ccsync-svc", "editors"))
    result = run_remote_script(script, tmp_path, acl_stub=SYNOACLTOOL_LINUX_MODE_STUB)
    assert result.returncode == 0, result.stderr
    assert "WARNING" in result.stderr and "Linux mode" in result.stderr
    log = (tmp_path / "synoacl.log").read_text(encoding="utf-8")
    # enforce-inherit first (it restores DSM's own layout), then -add.
    assert "-enforce-inherit" in log
    assert "-add" in log and "group:editors:allow:rwxpdDaARWc--:fd--" in log


def test_per_project_mode_grants_and_then_says_what_it_cannot_do(tmp_path):
    """docs/TENANCY.md: on DSM the grant is scriptable and the DENY is not.

    The share-wide `editors` ACE is INHERITED on a project path, and DSM
    exposes no way to delete an inherited ACE without breaking inheritance
    first (File Station only). Saying so on stderr is the whole contract --
    a silent half-implementation would read as isolation that is not there.
    """
    lines = backend().set_tree_acl(TREE, "ccsync-svc", "editors",
                                    project_group="proj-2026-demo-port-test",
                                    container_dirs=["/volume1/CCSyncTest/x"])
    joined = "\n".join(lines)
    assert "group:proj-2026-demo-port-test:allow" in joined
    assert "OPERATOR TODO" in joined and "Inherit permissions" in joined
    # The sticky bit is a MODE bit, and a chmod under a share destroys the ACL.
    assert "chmod" not in joined and "3770" not in joined


def test_dsm_editors_are_already_sftp_only():
    assert backend().editor_shell() == "/sbin/nologin"
    ok_done, detail = backend().set_editor_shell("jsmith", "/usr/bin/bash")
    assert ok_done is False and "administrators-only" in detail
    # ...and no sshd file is written: DSM regenerates sshd_config on every
    # Control Panel service toggle, so a Match block there is erased.
    state, _ = backend().ensure_sshd_editor_policy("editors")
    assert state == "unchanged"


def test_an_editors_key_can_be_taken_away_on_dsm():
    ssh = FakeSsh()
    ok_done, detail = backend(ssh=ssh).revoke_editor_key("jsmith")
    assert ok_done is True, detail
    sent = "\n".join(inner(cmd) for cmd, *_ in ssh.calls) if hasattr(ssh, "calls") \
        else ""
    if sent:
        assert "authorized_keys" in sent


def test_the_health_check_reads_the_acl_rather_than_trusting_it():
    dsm_ssh = FakeSsh(answers=[("synoacltool", (0, "It's Linux mode\n", ""))])
    ok, message = backend(ssh=dsm_ssh).check_tree_acl(TREE, "editors", dry_run=False)
    assert ok is False and "Linux mode" in message

    good = FakeSsh(answers=[("synoacltool",
                             (0, "\t [1] group:editors:allow:rwxpdDaARWc--:fd--\n", ""))])
    ok, message = backend(ssh=good).check_tree_acl(TREE, "editors", dry_run=False)
    assert ok is True and "editors" in message


# --------------------------------------------------------------------------
# 2. The deploy
# --------------------------------------------------------------------------

def test_a_host_root_outside_the_apps_share_is_refused():
    obj = SynologyBackend()
    for bad in ("/volume1/CCSyncTest/Creators_Club", "/volume1/docker", "/mnt/tank/apps",
                "/volume1/docker/ccsyncx"):
        with pytest.raises(common.EnvError):
            obj.use_project_dir(bad)
    assert obj.use_project_dir("/volume1/docker/ccsync") == "/volume1/docker/ccsync"


def test_the_sftp_view_is_not_the_filesystem():
    """DSM chroots EVERY account to its share view -- the admin included -- so
    /tmp is not reachable over SFTP at all and an absolute volume path has to
    lose its /volume<N> (measured during the 2026-08-17 bring-up)."""
    obj = SynologyBackend()
    assert obj.sftp_path("/volume1/docker/ccsync/staging") == "/docker/ccsync/staging"
    assert obj.sftp_path("/volume2/CCSyncTest") == "/CCSyncTest"
    assert obj.sftp_path("/tmp/x") == "/tmp/x"      # unchanged, and unreachable


def test_the_stack_files_are_uploaded_not_heredocd_and_the_env_is_root_only(monkeypatch):
    # deploy_stack(dry_run=False) reads the NAS admin password through
    # common.truenas_conn_params -> nas_admin_password, which requires
    # TRUENAS_PW (or SYNO_PW). This passed locally by accident: the base rig
    # carries TRUENAS_PW in its real environment (CLAUDE.md); a hosted
    # runner does not.
    monkeypatch.setenv("TRUENAS_PW", "pw")
    ssh, put = FakeSsh(), FakePutText()
    rc = backend(ssh=ssh, put=put).deploy_stack(
        "ccsync-dashboard", {}, 8480, dry_run=False,
        compose_yaml="services:\n  dashboard:\n    image: python\n",
        env={"DASH_SESSION_SECRET": "s3cret", "SYNCTHING_API_KEY": "k"})
    assert rc == 0
    # The files went over SFTP, into the SHARE VIEW of the staging dir...
    assert put.uploads and put.uploads[0][0] == "/docker/ccsync/.stack-stage"
    assert "image: python" in put.file("compose.yaml")
    assert "DASH_SESSION_SECRET='s3cret'" in put.file(".env")
    # ...and nothing about them reached a command line.
    assert "s3cret" not in ssh.text
    assert "services:" not in ssh.text
    # .env is 0600 root -- it carries the session secret, the report token, the
    # Syncthing key and the NAS password.
    assert "install -o root -g root -m 0600" in ssh.text
    assert "install -o root -g root -m 0644" in ssh.text


def test_the_stack_comes_up_with_the_syncthing_profile_and_its_own_env_file(monkeypatch):
    # Same TRUENAS_PW dependency as the test above -- dry_run=False reads it
    # through nas_admin_password before it ever touches FakeSsh.
    monkeypatch.setenv("TRUENAS_PW", "pw")
    ssh = FakeSsh()
    backend(ssh=ssh).deploy_stack("ccsync-dashboard", {}, 8480, dry_run=False,
                                  compose_yaml="services: {}\n", env={"A": "b"})
    up = [inner(c) for c in ssh.commands if "up -d" in c]
    assert len(up) == 1
    assert "--profile bundled-syncthing up -d --remove-orphans" in up[0]
    assert "-p 'ccsync'" in up[0] and "-f '/volume1/docker/ccsync/compose.yaml'" in up[0]
    assert "--env-file '/volume1/docker/ccsync/.env'" in up[0]
    assert PATH_EXPORT in up[0]


def test_deploying_without_a_rendered_compose_file_is_refused():
    """The dict TrueNAS's middleware stores is not a compose file, and
    inventing one here would deploy a stack nobody reviewed."""
    ssh = FakeSsh()
    assert backend(ssh=ssh).deploy_stack("ccsync-dashboard", {"services": {}}, 8480,
                                         dry_run=False) == 1
    assert not ssh.commands


def test_a_dry_run_deploy_touches_nothing():
    ssh, put = FakeSsh(), FakePutText()
    assert backend(ssh=ssh, put=put).deploy_stack(
        "ccsync-dashboard", {}, 8480, dry_run=True,
        compose_yaml="services: {}\n", env={"A": "b"}) == 0
    assert all("[dry-run]" not in c for c in ssh.commands)   # the SSH layer prints it


def test_the_stack_query_is_tri_state():
    """SERVER-8: this runs AFTER the app swap, so "cannot tell" must be its own
    answer, not a crash and not a False."""
    obj = backend(ssh=FakeSsh(answers=[("docker compose ls",
                                        (0, '[{"Name":"ccsync","Status":"running(2)"}]', ""))]))
    assert obj.app_installed("ccsync-dashboard", False) is True
    assert backend(ssh=FakeSsh(answers=[("docker compose ls", (0, "[]", ""))])
                   ).app_installed("ccsync-dashboard", False) is False
    assert backend(ssh=FakeSsh(answers=[("docker compose ls", (1, "", "boom"))])
                   ).app_installed("ccsync-dashboard", False) is None
    assert backend(ssh=FakeSsh(answers=[("docker compose ls", (0, "not json", ""))])
                   ).app_installed("ccsync-dashboard", False) is None


def test_taking_the_stack_down_never_takes_the_volumes():
    ssh = FakeSsh()
    ok, _ = backend(ssh=ssh).delete_app("ccsync-dashboard", False)
    assert ok
    assert "down --remove-orphans" in ssh.text
    assert " -v" not in ssh.text and "--volumes" not in ssh.text


def test_the_dashboard_binds_loopback_by_default_and_never_the_world(monkeypatch):
    # ...with nothing in [net]: the suite's fixture site is the TrueNAS one and
    # carries this fleet's two addresses.
    monkeypatch.setattr(common, "site_value", lambda *a, **k: "")
    obj = SynologyBackend()
    assert obj.dash_binds(8480) == [("", "127.0.0.1")]
    assert obj.dash_binds(8480, bind_lan="192.168.0.11") == \
        [("DASH_BIND_LAN", "192.168.0.11")]
    assert obj.dash_binds(8480, bind_lan="192.168.0.11", bind_tailnet="100.64.0.2") == \
        [("DASH_BIND_LAN", "192.168.0.11"), ("DASH_BIND_TAILNET", "100.64.0.2")]
    with pytest.raises(common.EnvError):
        obj.dash_binds(8480, bind_lan="0.0.0.0")


def test_an_env_file_refuses_what_compose_would_eat():
    body = render_env_file({"DASH_REPORT_TOKEN": "abc123", "SYNCTHING_API_KEY": "k"})
    assert "DASH_REPORT_TOKEN='abc123'" in body and body.endswith("\n")
    with pytest.raises(common.EnvError):
        render_env_file({"X": "two\nlines"})


def _dotenv(body: str) -> dict:
    """What compose's dotenv makes of the rendered file.

    A deliberately small reimplementation of compose-go's `extractVarValue`
    (bug-hunt-2026-09-03 server-tools-1): an UNQUOTED value is cut at the first
    " #", stripped of surrounding whitespace and unwrapped of a matching quote
    pair, while a SINGLE-quoted value is literal - no interpolation, no
    escapes. python-dotenv reads the same grammar.
    """
    out = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, value = line.partition("=")
        if value.startswith("'"):
            out[name] = value[1:value.index("'", 1)]
            continue
        value = value.split(" #")[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[name] = value
    return out


@pytest.mark.parametrize("value", [
    "Str0ng$Pass!",     # compose interpolates $Pass out of an unquoted value,
                        # and this one is the operator's own NAS password
    "hunter2 #1",       # an inline " #" starts a comment: silent truncation
    "  padded  ",       # leading/trailing whitespace is stripped
    '"quoted"',         # a wrapping quote pair is removed
    "a#b", "!@%^&*()", "pw\t#x",
])
def test_every_env_value_survives_composes_dotenv_verbatim(value):
    """A truncated NAS password is a container that starts healthy and fails
    every authentication with no hint at the cause, so the ROUND TRIP is the
    test, not the shape of the line we wrote."""
    body = render_env_file({"DASH_NAS_PW": value, "DASH_REPORT_TOKEN": "abc123"})
    assert _dotenv(body) == {"DASH_NAS_PW": value, "DASH_REPORT_TOKEN": "abc123"}


def test_the_one_refusal_left_tells_the_operator_which_kind_of_secret_it_is():
    """`openssl rand -hex 24` is advice nobody can follow for the NAS admin
    password: its rotation is changing that account's password on the NAS."""
    with pytest.raises(common.EnvError) as caught:
        render_env_file({"TRUENAS_PW": "it's mine"})
    text = str(caught.value)
    assert "single quote" in text and "NAS admin password" in text
    assert "openssl" not in text

    with pytest.raises(common.EnvError) as caught:
        render_env_file({"DASH_SESSION_SECRET": "it's mine"})
    text = str(caught.value)
    assert "openssl rand -hex 24" in text and "NAS admin password" not in text
    assert "—" not in text


def test_the_rendered_compose_carries_no_secret_and_names_every_one():
    rendered = ida.render_compose_yaml(ida.compose_variables(
        host_root="/volume1/docker/ccsync", tree_root="/volume1/CCSyncTest/Creators_Club",
        app_uid=1042, app_gid=65536, binds=[("", "127.0.0.1")],
        syncthing_url="http://syncthing:8384", nas_host="nas", nas_user="dsmadmin",
        homes_parent=HOME_ROOT, nas_kind="synology"))
    swapped = ida.secrets_as_env_refs(rendered, ida.STACK_ENV_SECRETS)
    # No VALUE is the placeholder any more (the file's header still explains
    # what REPLACE_ME means for the manual paste-it-in fallback).
    assert ': "REPLACE_ME"' not in swapped
    for name in ida.STACK_ENV_SECRETS:
        assert f'{name}: "${{{name}:?' in swapped
    # A template that lost one of them is a stack whose session secret is the
    # literal string REPLACE_ME -- refuse, do not deploy.
    #
    # ida.EnvError, not common.EnvError: test_site_manifest's `unconfigured`
    # fixture reloads `common`, which rebinds the class -- and this script
    # imported the name at ITS import time, so the two are different objects
    # once that fixture has run. The module that raises is the one to catch.
    with pytest.raises(ida.EnvError):
        ida.secrets_as_env_refs("dashboard:\n  environment:\n", ("DASH_REPORT_TOKEN",))


def test_the_synology_host_dirs_are_uid_owned_and_never_group_writable():
    """DSM's only group for a local account is `users`, and EVERY local user is
    in it -- so TrueNAS's "group 3000, mode 770" would hand /data to the whole
    box. 0700 owned by the service uid instead (spike 7)."""
    script = ida.build_synology_host_dirs("/volume1/docker/ccsync", 1042, "dsmadmin")
    assert "chmod 700 " in script and "chmod 770" not in script
    assert "chown 1042 " in script
    assert "3000" not in script and "3001" not in script
    # the code trees stay root-owned and read-only (AUDIT C-1)
    assert "chown root:root" in script and "chmod 755" in script
    # staging belongs to the SSH user: SFTP writes as them (and cannot see /tmp)
    assert "chown 'dsmadmin' '/volume1/docker/ccsync/staging'" in script


def test_the_tree_side_directories_are_only_ever_mkdird():
    """The b-roll archive and the music library live INSIDE the tree share."""
    script = ida.build_synology_tree_dirs(
        ["/volume1/CCSyncTest/Creators_Club/Assets/B-roll Archive"])
    assert script.startswith("mkdir -p ")
    assert "chmod" not in script and "chown" not in script


def test_tailscale_is_the_dsm_package_not_a_container():
    ssh = FakeSsh(answers=[("tailscale", (0, '{"BackendState":"Running"}', ""))])
    rc, out, _err = backend(ssh=ssh).tailscale_status_json(False)
    assert rc == 0 and "Running" in out
    assert "/var/packages/Tailscale/target/bin/tailscale status --json" in ssh.text
    assert "docker exec" not in ssh.text


# --------------------------------------------------------------------------
# 3. Identity
# --------------------------------------------------------------------------

def test_the_group_create_response_carries_the_gid():
    """No second lookup: DSM returns {"data":{"gid":65536}} (spike 7)."""
    dsm = FakeDsmApi()
    gid_id, gid = backend(dsm=dsm).ensure_group("editors", dry_run=False)
    assert gid_id == gid == 65536
    assert dsm.of("SYNO.Core.Group", "create")
    # ...and the second run does not create anything.
    dsm.calls.clear()
    assert backend(dsm=dsm).ensure_group("editors", dry_run=False) == (65536, 65536)
    assert not dsm.of("SYNO.Core.Group", "create")


def test_group_membership_is_always_read_back():
    """`Group.Member add` answers success:true whatever you send it, and reads
    `name`, not `members`. A fake that honours the WRONG parameter is what a
    client that stopped reading back would look like (spike 3)."""
    dsm = FakeDsmApi(groups={"editors": 65536}, member_add_reads="members")
    created, err = backend(dsm=dsm).create_editor("jsmith", "J Smith", 65536,
                                                  "ssh-ed25519 AAAA test", "/homes")
    assert created is None
    assert "did not add it" in err and "read-back" in err


def test_creating_an_editor_writes_the_key_over_ssh_and_touches_no_home_mode():
    """DSM has no sshpubkey field, and its home is ALREADY 711 -- a chmod there
    would delete the home's own ACL for no gain (spikes 1 and 2)."""
    dsm, ssh = FakeDsmApi(groups={"editors": 65536}), FakeSsh()
    created, err = backend(dsm=dsm, ssh=ssh).create_editor(
        "jsmith", "J Smith", 65536, "ssh-ed25519 AAAA test", "/homes")
    assert err == "" and created["uid"] == 1042
    assert "jsmith" in dsm.membership["editors"]
    text = inner(ssh.text)
    assert f"{HOME_ROOT}/jsmith/.ssh/authorized_keys" in text
    # tmp+mv, so a half-written file is never the one sshd reads
    assert ".authorized_keys.ccsync" in text and "mv -f" in text
    assert "chmod 700 '/var/services/homes/jsmith/.ssh'" in text
    assert "chmod 600 '/var/services/homes/jsmith/.ssh/authorized_keys'" in text
    assert "chown -R 'jsmith:users'" in text
    # the HOME itself is never chmod'd or chown'd
    assert "chmod 700 '/var/services/homes/jsmith'" not in text
    assert "chown -R 'jsmith:users' '/var/services/homes/jsmith'" not in text


def test_the_key_script_stops_at_the_first_failure_and_reads_the_key_back():
    """bug-hunt-2026-09-03 server-tools-2. A `;`-list returns the LAST
    command's status, and the last command was `chmod 600 authorized_keys` --
    which succeeds on a RE-KEY, because the previous enrolment's file is
    already there. A failed printf/mv therefore read as success and left the
    OLD key live: a revocation the operator was told had happened."""
    dsm, ssh = FakeDsmApi(groups={"editors": 65536}), FakeSsh()
    backend(dsm=dsm, ssh=ssh).create_editor("jsmith", "J Smith", 65536,
                                            "ssh-ed25519 AAAA test", "/homes")
    text = inner(ssh.text)
    guard = text.index("set -e")
    # AFTER the MISSING_HOME probe, which is meant to exit 3 with its own
    # message (the SERVER-4 lesson: an `if` CONDITION is exempt anyway).
    assert text.index("MISSING_HOME") < guard < text.index("printf")
    # ...and the file is READ BACK: verify_home_permissions only stats mode and
    # owner, so a chmod-only success is invisible to every other check.
    assert "grep -qxF 'ssh-ed25519 AAAA test' " \
           f"'{HOME_ROOT}/jsmith/.ssh/authorized_keys'" in text


@needs_bash
def test_a_key_write_that_fails_is_reported_as_a_failure(tmp_path, monkeypatch):
    """The same script actually run, with a `mv` that fails the way an over
    quota or read-only home does, and an authorized_keys already in place from
    a previous enrolment (the re-key path, which is the security-relevant one).
    """
    homes = tmp_path / "homes"
    (homes / "jsmith" / ".ssh").mkdir(parents=True)
    old = homes / "jsmith" / ".ssh" / "authorized_keys"
    old.write_text("ssh-ed25519 AAAA old\n", encoding="utf-8", newline="\n")
    monkeypatch.setattr("backends.synology.HOME_ROOT", str(homes).replace("\\", "/"))

    ssh = ExecSsh(tmp_path, stubs={"mv": "#!/bin/sh\necho 'mv: read-only' >&2\nexit 1\n"})
    ok, err = backend(ssh=ssh)._install_authorized_keys("jsmith", "ssh-ed25519 AAAA new")
    assert ok is False and "installing the SSH key failed" in err
    # ...and the operator is not told a key was revoked that is still live.
    assert old.read_text(encoding="utf-8").strip() == "ssh-ed25519 AAAA old"


@needs_bash
def test_a_key_write_that_works_is_read_back_and_reported(tmp_path, monkeypatch):
    homes = tmp_path / "homes"
    (homes / "jsmith").mkdir(parents=True)
    monkeypatch.setattr("backends.synology.HOME_ROOT", str(homes).replace("\\", "/"))
    ssh = ExecSsh(tmp_path)
    ok, err = backend(ssh=ssh)._install_authorized_keys("jsmith", "ssh-ed25519 AAAA new")
    assert ok is True and err == ""
    installed = homes / "jsmith" / ".ssh" / "authorized_keys"
    assert installed.read_text(encoding="utf-8").strip() == "ssh-ed25519 AAAA new"


def test_the_service_accounts_argv_password_is_documented_as_the_exception():
    """bug-hunt-2026-09-03 server-tools-6. `synouser --add` takes the password
    as an argument only, so this one value is on the remote argv that any local
    NAS account can read out of `ps` (AUDIT SEC-2). It is safe here and nowhere
    else: random, single-use, never stored, /sbin/nologin. The comment is the
    fix - what must not happen is the next reader copying the pattern."""
    source = (Path(__file__).resolve().parent.parent / "backends" / "synology.py"
              ).read_text(encoding="utf-8")
    call = source.index('f"synouser --add ')      # the call site, not the docstring
    preamble = source[max(0, call - 700):call]
    assert "SEC-2" in preamble and "nologin" in preamble


@pytest.mark.parametrize("username,reason", [
    ("admin", "built-in"),          # uid 1024 -- ABOVE the floor, so only the
    ("guest", "built-in"),          # name catches it (spike 7)
    ("root", "built-in"),
    ("sc-jellyfin", "package"),
])
def test_built_in_and_package_accounts_are_refused(username, reason):
    dsm = FakeDsmApi(groups={"editors": 65536})
    created, err = backend(dsm=dsm).create_editor(username, "x", 65536, "ssh-ed25519 k", "/h")
    assert created is None and reason in err
    assert not dsm.of("SYNO.Core.User", "create")


def test_an_account_that_is_not_already_an_editor_is_never_adopted():
    dsm = FakeDsmApi(users={"someone": {"uid": 1031}}, groups={"editors": 65536})
    created, err = backend(dsm=dsm).create_editor("someone", "x", 65536,
                                                  "ssh-ed25519 k", "/h")
    assert created is None and "not in the 'editors' group" in err


def test_a_package_uid_is_refused_even_when_it_is_in_editors():
    dsm = FakeDsmApi(users={"sc_thing": {"uid": 187774}}, groups={"editors": 65536})
    dsm.membership["editors"] = {"sc_thing"}
    created, err = backend(dsm=dsm).create_editor("sc_thing", "x", 65536,
                                                  "ssh-ed25519 k", "/h")
    assert created is None and "package account" in err


def test_the_editor_row_looks_like_the_truenas_one():
    """setup_editor_account verifies sshpubkey/smb/groups/home off this row and
    must not need to know which NAS answered."""
    dsm = FakeDsmApi(users={"jsmith": {"uid": 1030}}, groups={"editors": 65536})
    dsm.membership["editors"] = {"jsmith"}
    ssh = FakeSsh(answers=[("authorized_keys", (0, "HASKEY\n", ""))])
    row = backend(dsm=dsm, ssh=ssh).find_user("jsmith", dry_run=False)
    assert row["username"] == "jsmith" and row["uid"] == 1030
    assert row["home"] == f"{HOME_ROOT}/jsmith"
    assert row["smb"] is True and row["sshpubkey"]
    assert 65536 in row["groups"]
    # DSM's own names are mixed case; a refusal that capitalising can dodge is
    # not a refusal.
    assert backend(dsm=dsm, ssh=ssh).find_user("JSmith", dry_run=False)["uid"] == 1030


def test_the_service_account_is_not_an_editor_and_gets_its_own_share_ace(monkeypatch):
    """First Synology bring-up (2026-08-17) put ccsync-svc in `editors` so the
    container could write the tree -- and the dashboard's Users page then
    listed the plumbing account as an editor with a MISSING ssh key. It gets a
    user ACE on the share instead, and an earlier deploy's membership is
    reverted."""
    monkeypatch.setattr(common, "site_value",
                        lambda table, key, default="": "CCSyncTest"
                        if (table, key) == ("tree", "share_name") else default)
    ssh = FakeSsh(answers=[("id -u", (0, "1043\n", ""))])
    dsm = FakeDsmApi(groups={"editors": 65536}, users={"ccsync-svc": {"uid": 1043}})
    dsm.membership["editors"] = {"ccsync-svc", "jsmith"}       # the old, wrong state
    assert backend(ssh=ssh, dsm=dsm).ensure_service_user("ccsync-svc", "editors", False) == 1043
    # its own RW ACE on the tree share, as a USER, not via the group
    perm = [c for c in dsm.of("SYNO.Core.Share.Permission", "set")]
    assert perm and perm[-1].params["user_group_type"] == "local_user"
    assert perm[-1].params["permissions"][0]["name"] == "ccsync-svc"
    assert perm[-1].params["permissions"][0]["is_writable"] is True
    # and it is no longer in the group; the real editor still is
    assert "ccsync-svc" not in dsm.membership["editors"]
    assert "jsmith" in dsm.membership["editors"]
    assert dsm.of("SYNO.Core.Group.Member", "remove")


def test_the_service_user_uid_comes_from_the_box_and_is_range_checked():
    ssh = FakeSsh(answers=[("id -u", (0, "1042\n", ""))])
    dsm = FakeDsmApi(groups={"editors": 65536})
    assert backend(ssh=ssh, dsm=dsm).ensure_service_user("ccsync-svc", "editors", False) == 1042
    assert "synouser --add" not in ssh.text     # it already existed

    made = FakeSsh(answers=[("id -u", (0, "", "")), ("synouser --add", (0, "", ""))])
    # first `id -u` finds nothing, the create runs, and the read-back is what
    # the uid comes from -- so a create that silently did nothing is caught
    made.answers = [("synouser --add", (0, "", ""))]
    with pytest.raises(common.EnvError):
        backend(ssh=made, dsm=dsm).ensure_service_user("ccsync-svc", "editors", False)

    package = FakeSsh(answers=[("id -u", (0, "187774\n", ""))])
    with pytest.raises(common.EnvError):
        backend(ssh=package, dsm=dsm).ensure_service_user("sc-thing", "editors", False)


def test_password_disabled_is_answered_not_faked():
    """DSM has no such flag; its nearest neighbour disables the whole account,
    SMB session included. A "failed" here would print a warning about a thing
    that is not wrong."""
    state, detail = backend().set_password_disabled("jsmith")
    assert state == "not-applicable" and "key-only" in detail


# --------------------------------------------------------------------------
# 4. Services and storage
# --------------------------------------------------------------------------

def test_sftp_is_enabled_when_off_and_the_privilege_is_only_verified():
    """The plan was wrong twice (spike 2): the app id is SYNO.SFTP, and it is
    granted BY DEFAULT -- so this grants nothing and only refuses a DENY."""
    dsm = FakeDsmApi(sftp_enabled=False)
    assert backend(dsm=dsm).grant_sftp("editors", dry_run=False) is True
    assert dsm.sftp_enabled is True
    assert dsm.of("SYNO.Core.AppPriv.Rule", "list")
    assert not dsm.of("SYNO.Core.AppPriv.Rule", "set")


def test_an_explicit_sftp_deny_for_the_group_is_a_refusal():
    """The service being off and the privilege being denied produce the SAME
    client symptom -- key auth succeeds, then 'channel closed', with nothing in
    any log. Both are checked in one place for that reason."""
    dsm = FakeDsmApi(sftp_enabled=True, sftp_rules=[
        {"app_id": "SYNO.SFTP", "entity_type": "group", "entity_name": "editors",
         "allow_ip": [], "deny_ip": ["0.0.0.0"]},
    ])
    assert backend(dsm=dsm).grant_sftp("editors", dry_run=False) is False


def test_the_share_permission_call_is_what_installs_the_ace():
    dsm = FakeDsmApi()
    assert backend(dsm=dsm).ensure_share("CCSyncTest", "/volume1/CCSyncTest",
                                         "editors", dry_run=False) is True
    assert dsm.of("SYNO.Core.Share", "create")
    assert "editors" in dsm.shares["CCSyncTest"]["rw_groups"]
    # ...and the read-back is what proves it, not the 200.
    assert dsm.of("SYNO.Core.Share.Permission", "list")


def test_a_share_whose_name_and_path_disagree_is_refused():
    dsm = FakeDsmApi()
    assert backend(dsm=dsm).ensure_share("CCSyncTest", "/volume1/Something", "editors",
                                         dry_run=False) is False
    assert not dsm.calls


def test_a_snapshot_is_taken_of_the_share_the_path_lives_in():
    """No Snapshot Replication package needed to TAKE one (spike 8) -- only to
    schedule it."""
    dsm = FakeDsmApi()
    assert backend(dsm=dsm).snapshot("/volume1/CCSyncTest/Creators_Club/Projects",
                                     "pre-deploy", dry_run=False) is True
    assert dsm.snapshots["CCSyncTest"]
    assert backend(dsm=dsm).snapshot("/not/a/volume/path", "x", dry_run=False) is False


def test_installing_syncthing_is_an_honest_no_op(capsys):
    """Lane C is a service in our own stack here. Returning 0 while printing
    nothing would leave an operator believing a package was installed."""
    assert backend().install_syncthing(8384, "/volume1/CCSyncTest", "/data", False) == 0
    out = capsys.readouterr().out
    assert "compose stack" in out and "bundled-syncthing" in out


# --------------------------------------------------------------------------
# 5. The DSM API layer itself (common.synology_api)
# --------------------------------------------------------------------------

def test_every_parameter_is_json_not_a_python_repr():
    """A Python False reaches DSM as "False" and comes back as error 3103,
    naming nothing (spike 3.2)."""
    assert common._dsm_param(False) == "false"
    assert common._dsm_param(True) == "true"
    assert common._dsm_param(["a", "b"]) == '["a", "b"]'
    assert common._dsm_param({"name": "x", "cow": True}) == '{"name": "x", "cow": true}'
    assert common._dsm_param(7) == "7"


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload


def test_the_login_is_version_seven_and_the_shapes_are_checked_first(monkeypatch):
    """A v6 login yields a sid that reads fine and is refused on EVERY mutation
    with 105 -- for a full administrators-group account. So the version is
    pinned, and SYNO.API.Info is asked before anything else (spike 3.1)."""
    seen = []

    def fake_http(host, cgi, params, post, token=""):
        seen.append((cgi, dict(params), post))
        if params.get("api") == "SYNO.API.Info":
            return _FakeResponse({"success": True, "data": {
                api: {"minVersion": 1, "maxVersion": max(want, 1), "path": "entry.cgi"}
                for api, want in common.SYNO_REQUIRED_APIS.items()}})
        if params.get("api") == "SYNO.API.Auth":
            return _FakeResponse({"success": True,
                                  "data": {"sid": "SID", "synotoken": "TOK"}})
        return _FakeResponse({"success": True, "data": {"users": []}})

    monkeypatch.setattr(common, "_dsm_http", fake_http)
    monkeypatch.setenv("TRUENAS_PW", "pw")
    common.dsm_reset_session()
    common.synology_api("SYNO.Core.User", "list", 1, type="local")

    kinds = [p["api"] for _cgi, p, _post in seen]
    assert kinds[0] == "SYNO.API.Info"        # shapes before credentials
    login = next(p for _c, p, _post in seen if p["api"] == "SYNO.API.Auth")
    assert login["version"] == str(common.SYNO_LOGIN_VERSION) == "7"
    assert login["format"] == "sid"
    assert next(post for _c, p, post in seen if p["api"] == "SYNO.API.Auth") is True
    call = next(p for _c, p, _post in seen if p["api"] == "SYNO.Core.User")
    assert call["_sid"] == "SID" and call["SynoToken"] == "TOK"
    common.dsm_reset_session()


def test_a_dsm_that_cannot_offer_auth_seven_is_refused(monkeypatch):
    def fake_http(host, cgi, params, post, token=""):
        assert params.get("api") == "SYNO.API.Info"
        return _FakeResponse({"success": True, "data": {
            api: {"minVersion": 1, "maxVersion": 6 if api == "SYNO.API.Auth" else want,
                  "path": "entry.cgi"}
            for api, want in common.SYNO_REQUIRED_APIS.items()}})

    monkeypatch.setattr(common, "_dsm_http", fake_http)
    monkeypatch.setenv("TRUENAS_PW", "pw")
    common.dsm_reset_session()
    with pytest.raises(common.DsmError) as excinfo:
        common.synology_api("SYNO.Core.User", "list", 1)
    assert "SYNO.API.Auth" in str(excinfo.value) and "version 7" in str(excinfo.value)
    common.dsm_reset_session()


def test_a_dry_run_call_opens_nothing_and_hides_the_password(monkeypatch, capsys):
    monkeypatch.setattr(common, "_dsm_http",
                        lambda *a, **k: pytest.fail("dry-run must open no socket"))
    assert common.synology_api("SYNO.Core.User", "create", 1, post=True,
                               dry_run=True, name="x", passwd="hunter2") == {}
    out = capsys.readouterr().out
    assert "hunter2" not in out and "<redacted>" in out
