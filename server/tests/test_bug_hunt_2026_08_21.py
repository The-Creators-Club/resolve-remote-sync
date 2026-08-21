"""Regressions for the 2026-08-21 bug hunt, server/ half.

One group per finding, named by its id. Everything here is offline; run from
GIT BASH (see CLAUDE.md -- 18 of this suite's tests mean something different
when pytest is launched from PowerShell).

    cd E:\\Projects\\resolve-remote-sync\\server
    ../dashboard/.venv/Scripts/python.exe -m pytest tests -q
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
import install_dashboard_app as ida  # noqa: E402
import publish_db  # noqa: E402
from backends.truenas import TrueNASBackend  # noqa: E402
from tests.fake_dsm import FakeSsh  # noqa: E402
from test_hardening import _sample_key  # noqa: E402


def _backend(kind="truenas", ssh=None):
    """A backend whose NAS access is a FakeSsh, wired the way a script wires it."""
    module = type(sys)("fake_script")
    module.run_ssh = ssh or FakeSsh()
    if kind == "truenas":
        return TrueNASBackend(calls=common.ScriptCalls(module))
    from backends.synology import SynologyBackend  # noqa: PLC0415

    return SynologyBackend(calls=common.ScriptCalls(module))


# --------------------------------------------------------------------------
# server-1: --rollback could not find the .prev it was told about
# --------------------------------------------------------------------------

def test_the_prev_listing_runs_as_root_and_does_not_pipe_its_exit_code_away():
    """Both target directories are group-only (2770 archive, 770 music-data)
    and TRUENAS_USER cannot traverse either, so an unprivileged `ls` gets
    EACCES -- and `| tail` made the pipeline's rc 0, which is how "I could not
    read it" became indistinguishable from "there is nothing there"."""
    cmd = publish_db.list_prev_command("/mnt/tank/x/Assets/B-roll Archive",
                                       "broll.db")
    assert "sudo -S" in cmd, "every other filesystem probe here runs as root"
    assert "| tail" not in cmd and "| sort" not in cmd, (
        "a pipeline's rc is the LAST command's; the sort belongs in Python")
    assert "'broll.db.prev-*'" in cmd


def _listing(monkeypatch, rc, out="", err=""):
    """publish_db drives the NAS through install_dashboard_app's own names
    (run_ssh_guarded), not through the backend -- see common.ScriptCalls."""
    monkeypatch.setattr(ida, "run_ssh",
                        lambda cmd, dry_run=False, timeout=120: (rc, out, err))


def test_an_unreadable_directory_is_not_reported_as_an_empty_one(monkeypatch):
    _listing(monkeypatch, 1, err="find: Permission denied")
    prev, why = publish_db.newest_prev(_backend(), "/d", "broll.db", False)
    assert prev == ""
    assert "Permission denied" in why


def test_the_newest_prev_is_the_last_one_by_name(monkeypatch):
    _listing(monkeypatch, 0, out=("/d/broll.db.prev-20260819T090000\n"
                                  "/d/broll.db.prev-20260821T101500\n"
                                  "/d/broll.db.prev-20260820T120000\n"))
    prev, why = publish_db.newest_prev(_backend(), "/d", "broll.db", False)
    assert prev == "/d/broll.db.prev-20260821T101500"
    assert why == ""


def test_nothing_there_is_still_nothing_there(monkeypatch):
    _listing(monkeypatch, 0)
    assert publish_db.newest_prev(_backend(), "/d", "broll.db", False) == ("", "")


class _Args:
    which = "broll"
    from_prev = ""
    dry_run = False


def _rollback(monkeypatch, guarded, dry_run=False):
    """do_rollback with install_dashboard_app.run_ssh_guarded stubbed."""
    monkeypatch.setattr(ida, "run_ssh_guarded", guarded)
    args = _Args()
    args.dry_run = dry_run
    return publish_db.do_rollback(args, _backend(), publish_db.SPECS["broll"])


def test_rollback_says_it_could_not_look_rather_than_that_there_is_nothing(
        monkeypatch, capsys):
    """The documented first-line recovery (BACKUP_RESTORE 4d) used to tell the
    operator the .prev does not exist while it was sitting right there."""
    ran = []

    def guarded(cmd, dry_run, timeout):
        ran.append(cmd)
        return 13, "", "find: '/mnt/tank/x/Assets/B-roll Archive': Permission denied"

    assert _rollback(monkeypatch, guarded) == 1
    err = capsys.readouterr().err
    assert "could not list" in err
    assert "nothing to roll back to" not in err
    assert len(ran) == 1, "nothing on the NAS may be renamed after a failed listing"


def test_a_dry_run_rollback_describes_itself_instead_of_failing(monkeypatch, capsys):
    """args.dry_run is `not --apply`, so this is what an operator gets from the
    command BACKUP_RESTORE tells them to type first."""
    def guarded(cmd, dry_run, timeout):
        raise AssertionError("a dry-run must not touch the NAS")

    assert _rollback(monkeypatch, guarded, dry_run=True) == 0
    out = capsys.readouterr()
    assert "FAILED" not in out.err
    assert "[dry-run]" in out.out
    assert "sudo -S" in out.out, "it should show the listing it would run"


def test_an_empty_directory_still_refuses_with_apply(monkeypatch, capsys):
    def guarded(cmd, dry_run, timeout):
        return 0, "", ""

    assert _rollback(monkeypatch, guarded) == 1
    assert "nothing to roll back to" in capsys.readouterr().err


# --------------------------------------------------------------------------
# server-2: the pre-chown snapshot was never taken
# --------------------------------------------------------------------------

def test_the_dataset_probe_runs_as_root():
    """statfs needs search permission on every component, and TRUENAS_USER has
    no traverse on the 2770 tree -- so the unprivileged df was refused for
    setup_tree's own path on every run, and the chown -R that followed had
    nothing behind it."""
    ssh = FakeSsh(answers=[("df", (0, "tank/TheCreatorsPool\n", ""))])
    backend = _backend(ssh=ssh)
    assert backend.resolve_dataset("/mnt/tank/TheCreatorsPool/Creators_Club/Projects",
                                   False) == "tank/TheCreatorsPool"
    probe = next(c for c in ssh.commands if "df --output=source" in c)
    assert "sudo -S" in probe


def test_a_refused_probe_still_falls_back_to_the_naive_name():
    """The fallback is not what was wrong; running the probe unprivileged was."""
    ssh = FakeSsh(answers=[("df", (1, "", "df: Permission denied"))])
    assert _backend(ssh=ssh).resolve_dataset("/mnt/tank/apps", False) == "tank/apps"


# --------------------------------------------------------------------------
# server-3 / server-4: the fresh-install host and tree dirs
# --------------------------------------------------------------------------

def _deploy_commands(monkeypatch):
    cmds: list = []

    def record(cmd, dry_run=False, timeout=120):
        cmds.append(cmd)
        return 0, "", ""

    monkeypatch.setattr(ida, "run_ssh", record)
    monkeypatch.setattr(sys, "argv", ["install_dashboard_app.py", "--dry-run"])
    assert ida.main() == 0
    return cmds


def test_the_shared_assets_parent_is_created_and_owned(monkeypatch, capsys):
    """Nothing in this repo ever created <tree>/Assets. `mkdir -p` of the
    archive leaf made it as root:root 0755, and Syncthing (the service uid)
    then could not create Assets/Luts or Assets/Stills under it -- both folders
    sat in "folder path missing" on every provision cycle."""
    cmds = _deploy_commands(monkeypatch)
    capsys.readouterr()
    assets = f"{common.DEFAULT_CC_ROOT}/{common.SHARED_ASSETS_REL}"
    cmd = next(c for c in cmds if f"{common.DEFAULT_CC_ROOT}/{common.LUTS_REL}" in c)
    # the PARENT, not only the leaves -- that is the whole finding
    assert f"'{assets}'" in cmd
    assert cmd.index("mkdir -p") < cmd.index(f"'{assets}'")
    assert "chown 3000:3001" in cmd, "same posture as Projects/ and the archive"
    assert "chmod 2770" in cmd
    for _fid, rel, _label in common.SHARED_ASSET_FOLDERS:
        assert f"'{common.DEFAULT_CC_ROOT}/{rel}'" in cmd, rel


def test_the_assets_step_cannot_fail_a_deploy(monkeypatch, capsys):
    """It prepares a directory nothing MOUNTS. A deploy must not die over it."""
    def record(cmd, dry_run=False, timeout=120):
        if common.LUTS_REL in cmd:
            return 1, "", "chown: invalid user"
        return 0, "", ""

    monkeypatch.setattr(ida, "run_ssh", record)
    monkeypatch.setattr(sys, "argv", ["install_dashboard_app.py", "--dry-run"])
    assert ida.main() == 0
    assert "could not prepare the shared asset folders" in capsys.readouterr().err


def test_every_chown_follows_the_uid_the_container_runs_as(monkeypatch, capsys):
    """The container has run as site.toml's [stack] uid/gid since 2026-08-17
    and the TrueNAS step-1 chain still said 3000:3000 / 3000:3001, so a site
    that set those keys got a green "host dirs ready" and a container that
    could not open /data."""
    monkeypatch.setattr(ida, "APP_UID", 4000)
    monkeypatch.setattr(ida, "APP_GID", 4001)
    monkeypatch.setattr(ida, "APP_PRIVATE_GID", 4000)
    cmds = _deploy_commands(monkeypatch)
    capsys.readouterr()
    joined = "\n".join(cmds)
    assert "3000:3000" not in joined and "3000:3001" not in joined

    dirs_cmd = next(c for c in cmds if "/venv" in c and "mkdir -p" in c)
    assert "chown -R 4000:4000" in dirs_cmd
    assert "4000:4001" not in dirs_cmd, "the editors group must not own data/ or venv/"
    archive = next(c for c in cmds if common.DEFAULT_BROLL_ARCHIVE_ROOT in c)
    assert "chown 4000:4001" in archive


def test_the_db_swap_script_installs_for_the_configured_uid(monkeypatch):
    monkeypatch.setattr(ida, "APP_UID", 4000)
    monkeypatch.setattr(ida, "APP_PRIVATE_GID", 4000)
    script = ida.build_db_swap_script("/r", "/tmp/s", "/r/music.db",
                                      "/r/music.db.prev", 10)
    assert "chown 4000:4000" in script
    owner, mode, _acl = publish_db.install_identity("music", _backend(), "/r/music.db")
    assert (owner, mode) == ("4000:4000", "660")


def test_a_blank_owner_still_means_no_chown_at_all():
    """The DSM tree-share case: a chown or chmod there DESTROYS the ACL, so ""
    and "the default" have to stay different answers."""
    script = ida.build_db_swap_script("/r", "/tmp/s", "/r/broll.db",
                                      "/r/broll.db.prev", 10,
                                      filename="broll.db", owner="", mode="")
    assert "chown" not in script and "chmod" not in script


# --------------------------------------------------------------------------
# server-5: publish_db staged in /tmp, which DSM's SFTP channel cannot reach
# --------------------------------------------------------------------------

def test_a_synology_publish_stages_inside_the_apps_root(monkeypatch):
    # A Synology backend reads the NAS password at construction; CI has no
    # secrets (the base rig always does, which is how this passed locally).
    monkeypatch.setenv("TRUENAS_PW", "test-only")
    calls = []

    def guarded(cmd, dry_run, timeout):
        calls.append(cmd)
        return 0, "", ""

    monkeypatch.setattr(ida, "run_ssh_guarded", guarded)
    backend = _backend("synology")
    parent = publish_db.staging_parent(backend, False)
    assert parent.startswith(common.DEFAULT_APPS_ROOT.rstrip("/") + "/")
    assert parent.endswith("/" + ida.SYNOLOGY_STAGING_DIRNAME)
    # ...and the SFTP channel can actually see it: DSM chroots to the share
    # view, where /tmp does not exist at all.
    assert not backend.sftp_path(parent).startswith("/volume")
    assert calls and "mkdir -p" in calls[0]


def test_truenas_keeps_staging_in_tmp(monkeypatch):
    monkeypatch.setattr(ida, "run_ssh_guarded",
                        lambda *a, **kw: pytest.fail("no probe needed on TrueNAS"))
    assert publish_db.staging_parent(_backend(), False) == "/tmp"


# --------------------------------------------------------------------------
# server-6: the apps target could never be scheduled, and said the wrong thing
# --------------------------------------------------------------------------

def test_the_pool_refusal_names_the_path_and_the_remedy():
    """On this fleet /mnt/tank/apps is a plain directory in `tank`, so df
    answers "tank" and this refusal is what the app target ALWAYS got -- while
    BACKUP_RESTORE said the apps dataset was snapshotted on the same schedule.
    The old text pointed at [tree] pool_root, which has nothing to do with it."""
    ssh = FakeSsh(answers=[("df", (0, "tank\n", ""))])
    result = _backend(ssh=ssh).ensure_snapshot_schedule(
        "/mnt/tank/apps/ccsync-dashboard", [], False)
    assert len(result) == 1
    state, detail = result[0]
    assert state == "failed"
    assert "/mnt/tank/apps/ccsync-dashboard" in detail
    assert "zfs create -p tank/apps/ccsync-dashboard" in detail
    assert "[apps] root" in detail


def test_the_listing_reports_a_target_that_cannot_be_scheduled(monkeypatch, capsys):
    """--list is what BACKUP_RESTORE calls the check that backups work, and it
    used to say nothing at all about the apps target that has never had a
    schedule on this fleet."""
    import setup_snapshots  # noqa: PLC0415

    class _Backend:
        kind = "truenas"

        def list_snapshots(self, path, dry_run):
            return [{"name": "ccsync-20260821-1000", "created": "now"}]

        def ensure_snapshot_schedule(self, path, schedules, dry_run):
            if "/apps/" in path:
                return [("failed", f"refusing to schedule snapshots on 'tank': "
                                   f"{path} is a plain directory in it")]
            return []

    monkeypatch.setattr(setup_snapshots, "get_backend", lambda args: _Backend())
    monkeypatch.setattr(sys, "argv",
                        ["setup_snapshots.py", "--list", "--apply"])
    assert setup_snapshots.main() == 1
    err = capsys.readouterr().err
    assert "CANNOT BE SCHEDULED" in err
    assert "Backups are NOT fully configured" in err


# --------------------------------------------------------------------------
# server-7: every script reached the NAS on port 22, whatever the site said
# --------------------------------------------------------------------------

def test_the_ssh_port_comes_from_the_site_then_falls_back(monkeypatch):
    monkeypatch.delenv("CCSYNC_SSH_PORT", raising=False)
    values = {}
    monkeypatch.setattr(common, "site_value",
                        lambda s, k, d="": values.get((s, k), d))
    assert common.nas_ssh_port() == 22
    values[("net", "sftp_port")] = "2222"
    assert common.nas_ssh_port() == 2222
    values[("nas", "ssh_port")] = "2022"
    assert common.nas_ssh_port() == 2022
    monkeypatch.setenv("CCSYNC_SSH_PORT", "2202")
    assert common.nas_ssh_port() == 2202
    monkeypatch.setenv("CCSYNC_SSH_PORT", "not-a-port")
    assert common.nas_ssh_port() == 22


def test_a_non_default_port_is_keyed_the_way_known_hosts_keys_it():
    """OpenSSH (and paramiko's parser) spells it [host]:port; a bare `host`
    entry does not match, so recording under the wrong name would quietly
    un-pin a site that moved sshd."""
    assert common.host_key_id("nas.example", 22) == "nas.example"
    assert common.host_key_id("nas.example", 2222) == "[nas.example]:2222"


def test_ssh_client_connects_on_the_configured_port(monkeypatch, tmp_path):
    import paramiko  # noqa: PLC0415

    monkeypatch.setattr(common, "_HOST_KEY_PIN", "", raising=False)
    monkeypatch.setattr(common, "_TRUST_ON_FIRST_USE", False, raising=False)
    monkeypatch.delenv("CCSYNC_SSH_HOSTKEY", raising=False)
    monkeypatch.delenv(common.TOFU_ENV, raising=False)
    monkeypatch.setenv(common.KNOWN_HOSTS_ENV, str(tmp_path / "known_hosts"))
    monkeypatch.setenv("CCSYNC_SSH_PORT", "2222")
    monkeypatch.setattr(sys, "argv", ["pytest"])

    # No key anywhere: the refusal must name the port, and the keyscan it
    # prints must carry -p or it produces a pin that will never match.
    with pytest.raises(common.EnvError) as excinfo:
        common.ssh_client("nas.example", "admin", "pw")
    assert "2222" in str(excinfo.value)
    assert "ssh-keyscan -t ed25519 -p 2222 nas.example" in str(excinfo.value)

    # Pinned: it connects, on the port, and pins under the [host]:port name.
    key = _sample_key()
    common.set_host_key_pin(f"{key.get_name()} {key.get_base64()}")
    seen = {}
    try:
        def fake_connect(self, hostname, **kw):
            seen["port"] = kw.get("port")
            seen["known"] = self.get_host_keys().lookup("[nas.example]:2222")

        monkeypatch.setattr(paramiko.SSHClient, "connect", fake_connect)
        common.ssh_client("nas.example", "admin", "pw")
    finally:
        common.set_host_key_pin("")
    assert seen["port"] == 2222
    assert seen["known"] is not None


# --------------------------------------------------------------------------
# trust-model-3: the whole fleet shared one login-throttle IP bucket
# --------------------------------------------------------------------------

def test_the_deploy_names_the_bridge_the_proxied_request_arrives_from(monkeypatch):
    monkeypatch.delenv("DASH_TRUSTED_PROXIES", raising=False)
    monkeypatch.setattr(ida, "site_value", lambda s, k, d="": "")
    spec = ida.trusted_proxies_for("100.64.0.1")
    entries = spec.split(",")
    assert entries[:3] == ["127.0.0.1", "::1", ida.DEFAULT_DOCKER_BRIDGE_CIDR]
    assert "100.64.0.1" in entries
    # the studio LAN is in docker's default pool too, and must NOT be trusted
    assert "192.168.0.0/16" not in spec


def test_the_site_and_the_environment_can_both_replace_the_list(monkeypatch):
    monkeypatch.setattr(ida, "site_value",
                        lambda s, k, d="": ("10.1.2.3" if (s, k) == ("net", "trusted_proxies")
                                            else d))
    monkeypatch.delenv("DASH_TRUSTED_PROXIES", raising=False)
    assert ida.trusted_proxies_for("100.64.0.1") == "10.1.2.3"
    monkeypatch.setenv("DASH_TRUSTED_PROXIES", "127.0.0.1")
    assert ida.trusted_proxies_for("100.64.0.1") == "127.0.0.1"


def test_the_compose_body_carries_the_trusted_proxy_list():
    """Unset, auth.client_ip answered the docker bridge gateway for everybody:
    five wrong passwords from anyone 429'd /login AND /api/v1/verify for the
    whole fleet, and every admin session row showed one address."""
    svc = ida.compose_config(8480, "/mnt/tank/apps/ccsync-dashboard",
                             "http://gui:8384", "k", "t",
                             bind_lan="10.0.0.5", bind_tailnet="100.64.1.2",
                             )["services"]["dashboard"]
    spec = svc["environment"]["DASH_TRUSTED_PROXIES"]
    assert ida.DEFAULT_DOCKER_BRIDGE_CIDR in spec
    assert "100.64.1.2" in spec


# --------------------------------------------------------------------------
# ops-efficiency-7: container stdout was unbounded
# --------------------------------------------------------------------------

def test_every_service_caps_its_json_file_log():
    """Several access-log lines a second, forever, into a driver with no cap
    of its own, on a dataset that is also snapshotted hourly."""
    services = ida.compose_config(
        8480, "/mnt/tank/apps/ccsync-dashboard", "http://gui:8384", "k", "t",
        youtube_download="1", youtube_unblock="1")["services"]
    assert len(services) >= 2, "the unblock sidecar should be in this body"
    for name, svc in services.items():
        assert svc["logging"]["driver"] == "json-file", name
        assert svc["logging"]["options"]["max-size"] == "20m", name
        assert svc["logging"]["options"]["max-file"] == "5", name


# --------------------------------------------------------------------------
# CR-67 seam 5: the halves wave 1 could not land on its own
#
# trust-model-3's DASH_TRUSTED_PROXIES, ops-efficiency-7's log cap and
# product-surface-3's own-footage keys were all fixed in the DICT the TrueNAS
# path POSTs, while the compose TEMPLATE files -- the manual "Install via
# YAML" fallback and the Synology deploy path -- belonged to another
# territory. These are the file halves (2026-08-21).
# --------------------------------------------------------------------------

DEPLOY_DIR = ida.LOCAL_DASHBOARD_DIR / "deploy"
COMPOSE_FILES = ("compose.yaml", "compose.image.yaml", "compose.appliance.yaml")


def _deploy_text(name: str) -> str:
    return (DEPLOY_DIR / name).read_text(encoding="utf-8")


def _service_bodies(text: str) -> dict:
    """{service name: its YAML lines}, without a YAML parser -- server/ depends
    on paramiko and requests only, and the dashboard venv these tests run in
    has no yaml either (test_compose_template.py makes the same choice)."""
    body = text.split("\nservices:\n", 1)[1]
    out, current, lines = {}, None, []
    for line in body.splitlines():
        if re.match(r"^  ([a-z][a-z0-9_-]*):$", line):
            if current:
                out[current] = "\n".join(lines)
            current, lines = line.strip().rstrip(":"), []
        elif line.startswith("#") or line.startswith("{{"):
            # A between-services comment, or {{DASH_PORT_BINDS}} -- the one
            # placeholder that renders its own indentation, so it sits at
            # column 0 in the template and is not a new top-level key.
            continue
        elif line and not line.startswith(" "):
            break                      # a new top-level key: volumes:, networks:
        elif current:
            lines.append(line)
    if current:
        out[current] = "\n".join(lines)
    return out


@pytest.fixture
def site_manifest(monkeypatch):
    """Swap the loaded site manifest for a literal table, and put it back.

    common caches it in a module global because the values are argparse
    defaults (common.load_site) -- so a test that changes one has to restore
    it or every later test in the process reads the fake.
    """
    def use(table):
        monkeypatch.setattr(common, "_SITE", table)

    return use


def test_the_trusted_proxies_line_reaches_both_compose_templates():
    """trust-model-3 shipped in the dict only, so a Synology deploy and every
    hand-pasted compose.yaml still gave the whole fleet ONE login-throttle IP
    bucket. The rendered files carry a real list now, not a placeholder."""
    for name in ("compose.yaml", "compose.image.yaml"):
        rendered = ida.render_compose_yaml(ida.compose_variables(),
                                           template=DEPLOY_DIR / name)
        line = next(l for l in rendered.splitlines()
                    if l.strip().startswith("DASH_TRUSTED_PROXIES:"))
        assert ida.DEFAULT_DOCKER_BRIDGE_CIDR in line, (name, line)
        assert "127.0.0.1" in line, (name, line)


def test_the_env_drift_carve_out_is_empty_again():
    """COMPOSE_ENV_ONLY_IN_DICT narrowed test_env_keys_match_compose for one
    release. With both templates carrying the key it has to be empty again --
    an entry that outlives its fix is a drift guarantee quietly switched off."""
    assert ida.COMPOSE_ENV_ONLY_IN_DICT == ()


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_every_service_in_every_template_caps_its_stdout(name):
    """ops-efficiency-7's file half. compose_config()'s dict has had the cap
    since this pass; a service in a template without one is a container whose
    json-file log grows until the customer's disk is full."""
    bodies = _service_bodies(_deploy_text(name))
    assert bodies, name
    for service, body in bodies.items():
        assert 'driver: "json-file"' in body, f"{name}: {service} has no log cap"
        assert 'max-size: "20m"' in body, f"{name}: {service}"
        assert 'max-file: "5"' in body, f"{name}: {service}"


def test_run_sh_does_not_log_every_poll():
    """The other half of ops-efficiency-7: uvicorn's access log is one line per
    request on paths nothing reads back (/api/v1/report every 5 s per machine,
    /partials/* every 2 s per open tab, /api/v1/health every 60 s). BOTH
    invocations take the flag -- the OTA restart loop and the plain exec -- or
    the two deploy modes log differently."""
    text = (DEPLOY_DIR / "run.sh").read_text(encoding="utf-8")
    assert 'ACCESS_LOG_FLAG="--no-access-log"' in text
    invocations = [l for l in text.splitlines() if "-m uvicorn" in l]
    assert len(invocations) == 2, invocations
    assert text.count("$ACCESS_LOG_FLAG") >= 2
    # ...and it is still switchable for a debugging session.
    assert "DASH_ACCESS_LOG" in text


def test_the_appliance_no_longer_claims_rclone_checks_the_host_key():
    """trust-model-4. Editors' lanes A and B pass no known_hosts_file and
    /api/v1/site publishes no host key, so NOTHING on an editor machine
    notices a changed one. A comment promising otherwise is worse than no
    comment: it is what an operator reads while deciding whether a key
    rotation is safe. docs/SERVER.md carries the exposure and the shape of the
    real fix."""
    text = _deploy_text("compose.appliance.yaml")
    claim = "a changed host key makes every editor's"
    assert text.count(claim) == 1, "quote the retracted claim exactly once"
    assert "IT DOES NOT" in text
    assert "known_hosts_file" in text


# --------------------------------------------------------------------------
# product-surface-3: one customer's project name, as a default, in four places
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", ("compose.yaml", "compose.image.yaml"))
def test_no_customer_project_name_is_hardcoded_in_a_compose_template(name):
    """CLAUDE.md: no customer's name in code. `mofa-disaster` was the literal
    value of BROLL_CREATORS_SHARES in the file every operator pastes."""
    text = _deploy_text(name)
    code = "\n".join(l for l in text.splitlines()
                     if l.strip() and not l.strip().startswith("#"))
    assert ida.LEGACY_BROLL_CREATORS_SHARES not in code, name
    assert 'BROLL_CREATORS_SHARES: "{{BROLL_CREATORS_SHARES}}"' in text
    assert 'BROLL_ARCHIVE_CREATORS_DIR: "{{BROLL_ARCHIVE_CREATORS_DIR}}"' in text


def test_the_own_footage_shares_come_from_the_manifest(site_manifest):
    site_manifest({"broll": {"creators_shares": "north-ridge,harbour-2025"}})
    assert ida.broll_creators_shares_default() == "north-ridge,harbour-2025"
    svc = ida.compose_config(8480, "/mnt/tank/apps/x", "http://gui:8384", "k", "t",
                             bind_lan="10.0.0.5", bind_tailnet="100.64.1.2")
    assert svc["services"]["dashboard"]["environment"]["BROLL_CREATORS_SHARES"] \
        == "north-ridge,harbour-2025"


def test_a_site_that_wrote_a_broll_table_gets_the_empty_default(site_manifest):
    """EMPTY is the product default: an unconfigured archive browses entirely
    as Downloads, which is safer than filing bought footage as the customer's
    own. A [broll] table with other keys in it counts as having answered."""
    site_manifest({"broll": {"default_collection": "studio"}})
    assert ida.broll_creators_shares_default() == ""


def test_a_manifest_with_no_broll_table_keeps_the_historical_value(site_manifest):
    """The transitional half. This studio's site.toml predates the key, and a
    redeploy that emptied its own-footage collection would read as "the archive
    lost 7,000 clips". Adding [broll] creators_shares to site.toml ends it."""
    site_manifest({"tree": {"tree_name": "Creators_Club"}})
    assert ida.broll_creators_shares_default() == ida.LEGACY_BROLL_CREATORS_SHARES


def test_the_archive_creators_dir_reaches_both_the_dict_and_the_file(site_manifest):
    """A second customer's NEW shoots file under their own folder name; the
    ~7,000 already published under the historical one do not move, which is
    why blank still means broll/web's own default."""
    site_manifest({"broll": {"archive_creators_dir": "North Ridge Shoots"},
                   "tree": {"pool_root": "/mnt/tank/p", "tree_name": "T"},
                   "apps": {"root": "/mnt/tank/apps/x"}})
    assert ida.site_env(8480)["BROLL_ARCHIVE_CREATORS_DIR"] == "North Ridge Shoots"
    rendered = ida.render_compose_yaml(ida.compose_variables(
        host_root="/mnt/tank/apps/x", tree_root="/mnt/tank/p/T",
        binds=[("DASH_BIND_TAILNET", "100.64.1.2")]))
    assert 'BROLL_ARCHIVE_CREATORS_DIR: "North Ridge Shoots"' in rendered


def test_site_example_documents_the_keys_an_operator_has_to_find():
    """CR-67 seam 11. Every one of these is read by code that ships, and
    site.example.toml is where an operator learns a key exists at all -- an
    undocumented key is a key nobody sets."""
    text = (common.REPO_ROOT / "site.example.toml").read_text(encoding="utf-8")
    for key in ("ssh_port", "trusted_proxies", "docker_bridge_cidr",
                "private_gid", "creators_shares", "archive_creators_dir"):
        assert key in text, key


# --------------------------------------------------------------------------
# The thing that actually happened while closing seam 5 (2026-08-21)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", COMPOSE_FILES + ("run.sh", "sftp/sshd_config"))
def test_the_files_the_nas_parses_have_no_carriage_returns(name):
    """`.gitattributes` pins `dashboard/deploy/*.yaml` and `*.sh` to `eol=lf`
    and CLAUDE.md says why: a CRLF `run.sh` took the dashboard down on
    2026-07-26, because dash read the CR on `set -eu` as an option character.

    The rule protects a CHECKOUT. It does not protect an EDIT: writing any of
    these from Python on Windows in text mode rewrites the whole file to CRLF,
    which is exactly what happened to all three compose templates while these
    seams were being closed, and the suite noticed nothing -- every reader
    here goes through `read_text`, which translates the line endings away
    before any assertion sees them.

    So this reads BYTES. Do not "simplify" it to a string search, and do not
    grep for a CR from MSYS: it strips them before matching (CLAUDE.md,
    2026-08-10).
    """
    raw = (DEPLOY_DIR / name).read_bytes()
    assert b"\r" not in raw, (
        f"dashboard/deploy/{name} has carriage returns. Git will normalise them "
        f"on commit, but the DEPLOY reads this working copy: rewrite it with "
        f"newline='' / write_bytes and check `git ls-files --eol`")
