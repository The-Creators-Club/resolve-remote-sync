"""dashboard/deploy/compose.yaml is a template -- and TrueNAS must not notice.

WP0 step 2 of docs/SYNOLOGY_PORT_PLAN.md turned 17 hardcoded /mnt/tank bind
mounts, `user: "3000:3001"` and this fleet's two bind addresses into
`{{NAME}}` placeholders. The whole claim of that change is "nothing moves for
the existing deployment", and the only way to hold someone to it is to keep
the pre-templating file and diff against it: fixtures/compose.truenas.golden.yaml
is dashboard/deploy/compose.yaml as it stood at commit b9053b1 (2026-08-16).

If a legitimate change is later made to compose.yaml, update the golden in the
SAME commit -- and read the diff first: it is the only place a wrong bind
mount is visible before a container starts serving nothing.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
import install_dashboard_app as ida  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "compose.truenas.golden.yaml"


def _golden_text() -> str:
    return GOLDEN.read_text(encoding="utf-8")


def _rendered() -> str:
    return ida.render_compose_yaml()


def _service_block(text: str, name: str) -> str:
    """The YAML lines of one service, without parsing YAML (no yaml dep here,
    deliberately -- server/requirements.txt is paramiko/requests only)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line == f"  {name}:")
    out = []
    for line in lines[start + 1:]:
        if line and not line.startswith("   ") and not line.startswith("#"):
            break
        out.append(line)
    return "\n".join(out)


def _list_block(text: str, service: str, key: str) -> list[str]:
    block = _service_block(text, service)
    if f"\n    {key}:" not in block:
        return []
    tail = block.split(f"\n    {key}:", 1)[1]
    out = []
    for line in tail.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            out.append(stripped[2:].strip().strip('"').strip("'"))
        elif stripped and not stripped.startswith("#"):
            break
    return out


def test_the_golden_is_the_file_this_repo_used_to_ship():
    assert GOLDEN.is_file(), (
        "the pre-templating compose.yaml is the only evidence the template did "
        "not change the deployment -- do not delete it"
    )
    assert "{{" not in _golden_text(), "the golden must stay UN-templated"


def test_rendering_leaves_no_placeholder_behind():
    left = ida._COMPOSE_VAR_RE.findall(_rendered())
    assert left == [], (
        f"unrendered placeholder(s) {left}: one in a bind mount is a container "
        f"that starts and serves nothing"
    )


def test_an_unknown_placeholder_is_a_hard_error(tmp_path):
    template = tmp_path / "compose.yaml"
    template.write_text("services:\n  dashboard:\n    image: {{NOPE}}\n",
                        encoding="utf-8")
    with pytest.raises(common.EnvError) as excinfo:
        ida.render_compose_yaml(ida.compose_variables(), template=template)
    assert "NOPE" in str(excinfo.value)


@pytest.mark.parametrize("key", ["volumes", "ports"])
def test_the_dashboard_service_renders_identically_to_the_old_file(key):
    """The mounts and the published ports, line for line."""
    assert _list_block(_rendered(), "dashboard", key) == \
        _list_block(_golden_text(), "dashboard", key)


def test_the_container_still_runs_as_the_same_uid_gid():
    def user_line(text):
        m = re.search(r'^\s*user:\s*"(.*)"\s*$', _service_block(text, "dashboard"), re.M)
        assert m, "the dashboard service lost its user: line"
        return m.group(1)

    assert user_line(_rendered()) == user_line(_golden_text()) == "3000:3001"


def test_every_environment_line_is_unchanged():
    def env_block(text):
        block = _service_block(text, "dashboard")
        body = block.split("\n    environment:", 1)[1].split("\n    ports:", 1)[0]
        return [line.strip() for line in body.splitlines()
                if line.strip() and not line.strip().startswith("#")]

    assert env_block(_rendered()) == env_block(_golden_text())


def test_the_pot_provider_sidecar_is_untouched():
    assert (_service_block(_rendered(), "bgutil").rstrip()
            == _service_block(_golden_text(), "bgutil").rstrip())


def test_the_services_section_is_byte_identical_down_to_the_new_ones():
    """From `services:` to the first optional service -- comments included,
    since those comments are the documentation.

    The FILE HEADER above `services:` deliberately differs: it now explains the
    template. Everything a container is built from does not.
    """
    def body(text):
        return text.split("\nservices:\n", 1)[1].split("  # --- OPTIONAL:", 1)[0].rstrip()

    assert body(_rendered()) == body(_golden_text())


def test_the_rendered_file_is_valid_yaml_and_matches_the_golden_structurally():
    """The text diffs above are the load-bearing ones; this is the same claim
    made by a parser, plus the only check that the two services the template
    ADDS did not break the document. Skipped where PyYAML is absent -- it is
    deliberately not a server/ dependency (paramiko + requests only), and the
    dashboard venv these tests usually run in has no yaml either."""
    yaml = pytest.importorskip("yaml")

    rendered = yaml.safe_load(_rendered())
    golden = yaml.safe_load(_golden_text())
    assert rendered["services"]["dashboard"] == golden["services"]["dashboard"]
    assert rendered["services"]["bgutil"] == golden["services"]["bgutil"]
    assert set(rendered["services"]) - set(golden["services"]) == {"syncthing", "postgres"}


# --------------------------------------------------------------------------
# What the template ADDS: two services that are inert until asked for
# --------------------------------------------------------------------------

def test_the_new_services_are_profiled_so_this_deploy_never_sees_them():
    """A profiled service is not created, started or stopped unless its
    profile is named -- which is what makes it safe to carry a bundled
    Syncthing in the file while this site runs the TrueNAS catalog app."""
    rendered = _rendered()
    assert 'profiles: ["bundled-syncthing"]' in _service_block(rendered, "syncthing")
    assert 'profiles: ["project-server"]' in _service_block(rendered, "postgres")
    # ...and compose_config(), which is what TrueNAS actually deploys, carries
    # neither: the middleware stores that dict verbatim.
    services = ida.compose_config(8480, "/mnt/tank/apps/ccsync-dashboard",
                                  "http://gui:8384", "k", "t")["services"]
    assert set(services) == {"dashboard", ida.POT_PROVIDER_SERVICE}


def test_the_bundled_syncthing_is_pinned_and_mounts_the_tree():
    block = _service_block(_rendered(), "syncthing")
    m = re.search(r"image:\s*syncthing/syncthing:(\S+)", block)
    assert m, "the bundled Syncthing lost its image line"
    assert m.group(1) != "latest", "an unpinned Syncthing changes lane C underneath a redeploy"
    assert re.match(r"^1\.\d+\.\d+$", m.group(1)), m.group(1)
    # /data is the prefix setup_syncthing_folder.py builds folder paths from.
    assert f"{common.DEFAULT_CC_ROOT}:/data" in block
    assert "STGUIAPIKEY" in block
    # The GUI is an unauthenticated admin surface over every folder in the
    # fleet: loopback only. The sync ports themselves must NOT be.
    ports = _list_block(_rendered(), "syncthing", "ports")
    assert "127.0.0.1:8384:8384" in ports
    assert "22000:22000/tcp" in ports and "22000:22000/udp" in ports
    assert "21027:21027/udp" in ports


def test_the_optional_postgres_port_is_configurable():
    """5432 is frequently taken on a Synology (DSM's own PostgreSQL, Drive,
    Note Station), and a stack that cannot start is worse than one on another
    port."""
    ports = _list_block(_rendered(), "postgres", "ports")
    assert ports == ["${DASH_PG_PORT:-5432}:5432"]
    assert "image: postgres:13" in _service_block(_rendered(), "postgres")


# --------------------------------------------------------------------------
# The variables themselves
# --------------------------------------------------------------------------

def test_the_site_block_comes_from_the_manifest():
    """GET /api/v1/site serves whatever the deploy put in the container's
    environment, and until 2026-08-17 the deploy put NOTHING there -- so a
    deployed dashboard answered blanks and every client fell back to flags.

    The two SFTP values are the ones that are not cosmetic: 255Ki loses
    footage on DSM 7.2 and `shell_type = unix` cannot work for a nologin
    editor (synology-spikes-2026-08-17 spike 6).
    """
    env = ida.site_env(8480)
    assert env["DASH_SITE_TREE_NAME"] == common.TREE_NAME
    assert env["DASH_SITE_REMOTE_ROOT"] == common.DEFAULT_CC_ROOT
    assert env["DASH_SITE_SMB_UNC"] == common.site_value("tree", "smb_unc")
    assert env["DASH_SITE_SFTP_CHUNK_SIZE"] == "255Ki"
    assert env["DASH_SITE_SFTP_SHELL_TYPE"] == "unix"
    assert env["DASH_SITE_CANONICAL_PREFIX"] == "P:\\"
    # ...and every one of them reaches BOTH the file and the dict.
    rendered = _rendered()
    service = ida.compose_config(8480, "/mnt/tank/apps/ccsync-dashboard",
                                 "http://gui:8384", "k", "t")["services"]["dashboard"]
    for name, value in env.items():
        assert service["environment"][name] == value
        assert f"{name}: " in rendered, name


def test_the_nas_block_names_the_backend_and_its_ssh_channel():
    """The runtime seam's own settings (WP1/WP2): which backend to build, and
    the SSH channel the Synology one needs for authorized_keys."""
    service = ida.compose_config(8480, "/mnt/tank/apps/ccsync-dashboard",
                                 "http://gui:8384", "k", "t",
                                 truenas_host="nas", truenas_user="admin",
                                 truenas_pw="pw")["services"]["dashboard"]
    env = service["environment"]
    assert env["DASH_NAS_KIND"] == "truenas"
    # Both spellings, same value: DASH_NAS_* is what settings.py prefers, and
    # TRUENAS_* stays so a rollback to an older image still finds credentials.
    assert env["DASH_NAS_HOST"] == env["TRUENAS_HOST"] == "nas"
    assert env["DASH_NAS_PW"] == env["TRUENAS_PW"] == "pw"
    assert env["DASH_NAS_SSH_PORT"] == "22"
    assert "DASH_NAS_SSH_HOSTKEY" in env and "DASH_NAS_SSH_KEY_PROBE" in env


def test_the_variables_come_from_the_site_not_from_literals():
    variables = ida.compose_variables()
    assert variables["NAS_APPS_ROOT"] == common.DEFAULT_APPS_ROOT
    assert variables["NAS_TREE_ROOT"] == common.DEFAULT_CC_ROOT
    assert variables["APP_UID"] == "3000" and variables["APP_GID"] == "3001"
    assert variables["SYNCTHING_URL"] == ida.DEFAULT_SYNCTHING_GUI_URL


def test_a_synology_style_render_moves_every_path_and_binds_loopback():
    """The point of the exercise: a different site is a variable change, not a
    fork.

    The DASH_SITE_* block is deliberately NOT among the arguments: it comes
    from site.toml, so this render (which passes Synology-shaped paths while
    the fixture site is still the TrueNAS one) keeps the fixture's smb_unc and
    dashboard_url. A second site means a second site.toml, which is the whole
    design -- test_the_site_block_comes_from_the_manifest below pins it.
    """
    rendered = ida.render_compose_yaml(ida.compose_variables(
        port=8480,
        host_root="/volume1/docker/ccsync",
        tree_root="/volume1/CreatorsClub/Creators_Club",
        app_uid=1027, app_gid=1028,
        binds=[("", "127.0.0.1")],
        syncthing_url="http://syncthing:8384",
        nas_host="nas.example", nas_user="ccsync",
        homes_parent="/var/services/homes",
    ))
    assert "/mnt/tank" not in rendered
    assert '- "127.0.0.1:8480:8480"' in rendered
    assert 'user: "1027:1028"' in rendered
    volumes = _list_block(rendered, "dashboard", "volumes")
    assert "/volume1/docker/ccsync/app:/app:ro" in volumes
    assert "/volume1/CreatorsClub/Creators_Club/Projects:/projects:rw" in volumes
    # and the same values reach the dict the deploy actually posts
    service = ida.compose_config(
        8480, "/volume1/docker/ccsync", "http://syncthing:8384", "k", "t",
        tree_root="/volume1/CreatorsClub/Creators_Club", app_uid=1027, app_gid=1028,
        binds=[("", "127.0.0.1")],
    )["services"]["dashboard"]
    assert service["user"] == "1027:1028"
    assert service["ports"] == ["127.0.0.1:8480:8480"]
    assert all("/mnt/tank" not in v for v in service["volumes"])
