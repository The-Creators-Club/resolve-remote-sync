"""One deploy script, two shapes -- and the migration between them (2026-08-18).

`server/install_dashboard_app.py` deployed exactly one thing until now: a stock
python:3.12.7-slim with the four code trees and a /venv bind-mounted off the
host. docs/DOCKER.md's own "Not done here" section said so, and that is why
this studio never moved to image mode and why ZERO_TOUCH_PLAN.md WP K -- the
dashboard updating its own code over the air -- has been dark on every
deployment: WP K only exists inside an image.

`--mode image` / `--mode bind` makes the migration and its rollback one command
each. The claim these tests hold it to:

  * image mode drops the FIVE CODE MOUNTS and nothing else. Every data mount,
    /opt/ffmpeg and /opt/deno are byte-for-byte bind mode's -- the data is the
    half that cannot be rebuilt, and ffmpeg/deno are out of the image on
    licence grounds (COMMERCIAL_READINESS.md item 3), not by oversight.
  * image mode ships no code, and DELETES NOTHING. The host trees stay where
    they are because they are the rollback.
  * the refusals happen before anything moves.
  * neither mode turns a feature on that the other does not.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
import install_dashboard_app as ida  # noqa: E402

IMAGE_TEMPLATE = ida.LOCAL_DASHBOARD_DIR / "deploy" / "compose.image.yaml"
HOST_ROOT = "/mnt/tank/apps/ccsync-dashboard"


def _service(mode: str, **kw) -> dict:
    return ida.compose_config(8480, HOST_ROOT, "http://gui:8384", "k", "t",
                              mode=mode, **kw)["services"]["dashboard"]


# --------------------------------------------------------------------------
# The two bodies, side by side
# --------------------------------------------------------------------------

def test_image_mode_drops_the_five_code_mounts_and_only_those():
    """The whole difference between the modes, asserted as a set difference.

    Written this way rather than as a literal expected list so that a mount
    ADDED to compose_config in future is automatically covered: it will show up
    in both modes unless it is a code mount, and a data mount that quietly
    stopped being mounted in image mode is a feature that disappears when a
    site migrates.
    """
    bind = {ida.mount_target(v) for v in _service("bind")["volumes"]}
    image = {ida.mount_target(v) for v in _service("image")["volumes"]}
    assert bind - image == set(ida.IMAGE_MODE_CODE_MOUNTS)
    assert image - bind == set(), "image mode invented a mount bind mode does not have"
    # ...and the data half is really there, not merely "not missing".
    for data_mount in ("/data", "/projects", "/broll-data", "/music-data",
                       "/music-encoder", "/music-proxies", "/music-share",
                       "/ytdl-data", "/opt/ffmpeg"):
        assert data_mount in image, data_mount


def test_the_b_roll_archive_mount_survives_its_space():
    """`<tree>/Assets/B-roll Archive:/broll-data:rw` has a space in the HOST
    half, so the filter that drops the code mounts has to split positionally.
    Anything cleverer drops the archive and /broll answers 'unable to open
    database file' on a migrated site."""
    assert ida.mount_target(
        "/mnt/tank/x/Assets/B-roll Archive:/broll-data:rw") == "/broll-data"
    assert any(v.endswith("/Assets/B-roll Archive:/broll-data:rw")
               for v in _service("image")["volumes"])


def test_image_mode_runs_the_vendor_image_and_bind_mode_the_python_base():
    assert _service("bind")["image"] == ida.DEFAULT_IMAGE
    assert _service("image")["image"] == ida.SITE_CONTAINER_IMAGE
    assert _service("image", ccsync_image="ghcr.io/x/y@sha256:abc")["image"] == \
        "ghcr.io/x/y@sha256:abc"
    # --image is bind mode's base image and must not leak into image mode:
    # deploying `python:3.12.7-slim` as if it were the app is a container that
    # starts, finds no /app, and exits.
    assert _service("image", image="python:3.12.7-slim")["image"] != "python:3.12.7-slim"


def test_the_entrypoint_healthcheck_ports_user_and_restart_are_identical():
    """One entrypoint in both modes is what keeps every DEPLOY.md in the repo
    true (docs/DOCKER.md). The healthcheck reads the BODY, not the status code
    (DASH-2), in both."""
    bind, image = _service("bind"), _service("image")
    for key in ("command", "healthcheck", "ports", "user", "restart"):
        assert bind[key] == image[key], key


def test_image_mode_adds_only_the_two_uid_variables_to_the_environment():
    """An env key present in one mode and not the other is a feature that
    appears or disappears with the deploy shape. APP_UID/APP_GID are the one
    exception, and they exist because an unprivileged container cannot setuid:
    run.sh reads them and shouts, which is the only honest thing it can do."""
    bind, image = set(_service("bind")["environment"]), set(_service("image")["environment"])
    assert image - bind == {"APP_UID", "APP_GID"}
    assert bind - image == set()
    env = _service("image", app_uid=1027, app_gid=1028)["environment"]
    assert (env["APP_UID"], env["APP_GID"]) == ("1027", "1028")


def test_the_release_feed_and_pubkeys_reach_the_container_in_image_mode(monkeypatch):
    """Both are what make image mode worth migrating to: WP K's over-the-air
    code updates need a feed to find a bundle and keys to verify it."""
    monkeypatch.setenv("DASH_RELEASE_PUBKEYS", "base64key==")
    env = _service("image")["environment"]
    assert env["DASH_RELEASE_PUBKEYS"] == "base64key=="
    assert env["DASH_RELEASE_FEED_URL"] == common.site_value("releases", "feed_url")
    assert "DASH_RELEASE_FEED_POLICY" in env


def test_image_mode_does_not_turn_the_unblock_half_on_or_off():
    """Picking a deploy mode must never change which features a customer has
    (COMMERCIAL_READINESS.md item 3). The deno mount and the PO-token sidecar
    follow [features] youtube_unblock in BOTH modes -- and deno stays a mount
    in image mode because it is GPLv3 and must not be baked in."""
    for mode in ("bind", "image"):
        off = ida.compose_config(8480, HOST_ROOT, "http://gui:8384", "k", "t",
                                 mode=mode)
        assert set(off["services"]) == {"dashboard"}
        assert not any("/opt/deno" in v
                       for v in off["services"]["dashboard"]["volumes"])
        on = ida.compose_config(8480, HOST_ROOT, "http://gui:8384", "k", "t",
                                mode=mode, youtube_download="1", youtube_unblock="1")
        assert set(on["services"]) == {"dashboard", ida.POT_PROVIDER_SERVICE}
        assert f"{HOST_ROOT}/deno:/opt/deno:ro" in on["services"]["dashboard"]["volumes"]


# --------------------------------------------------------------------------
# The dict the TrueNAS middleware stores vs the file a Synology stack reads
# --------------------------------------------------------------------------

def _rendered_image() -> str:
    return ida.render_compose_yaml(ida.compose_variables(),
                                   template=ida.IMAGE_COMPOSE_TEMPLATE)


def _list_block(text: str, service: str, key: str) -> list[str]:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line == f"  {service}:")
    block = []
    for line in lines[start + 1:]:
        if line and not line.startswith("   ") and not line.startswith("#"):
            break
        block.append(line)
    block = "\n".join(block)
    if f"\n    {key}:" not in block:
        return []
    out = []
    for line in block.split(f"\n    {key}:", 1)[1].splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            out.append(stripped[2:].strip().strip('"').strip("'"))
        elif stripped and not stripped.startswith("#"):
            break
    return out


def test_the_image_template_and_the_image_dict_describe_the_same_mounts():
    """The same drift test compose.yaml/compose_config() has had for a while
    (test_safety.test_volumes_match_compose), for the other mode. TrueNAS POSTs
    the dict and a Synology stack reads the file, so two descriptions that
    disagree are two different deployments of the same command."""
    assert _list_block(_rendered_image(), "dashboard", "volumes") == \
        _service("image")["volumes"]


def test_the_image_template_takes_the_site_image_and_keeps_composes_own_override():
    """`${CCSYNC_IMAGE:-<site value>}` -- the shape the bind addresses use, and
    for the same reason: a re-pin should be a variable edit, not a file edit."""
    line = next(line for line in _rendered_image().splitlines()
                if line.strip().startswith("image: "))
    assert line.strip() == f'image: "${{CCSYNC_IMAGE:-{ida.SITE_CONTAINER_IMAGE}}}"'
    custom = ida.render_compose_yaml(
        ida.compose_variables(ccsync_image="ghcr.io/x/y@sha256:deadbeef"),
        template=ida.IMAGE_COMPOSE_TEMPLATE)
    assert "ghcr.io/x/y@sha256:deadbeef" in custom
    assert ida._COMPOSE_VAR_RE.findall(custom) == []


def test_compose_template_for_picks_the_file_the_mode_deploys():
    assert ida.compose_template_for("image") == IMAGE_TEMPLATE
    assert ida.compose_template_for("bind") == ida.COMPOSE_TEMPLATE
    assert IMAGE_TEMPLATE.is_file() and ida.COMPOSE_TEMPLATE.is_file()


# --------------------------------------------------------------------------
# Where the mode and the image come from
# --------------------------------------------------------------------------

def test_the_mode_defaults_to_bind_which_is_what_every_fleet_runs():
    assert ida.DEFAULT_STACK_MODE == "bind"
    assert ida.resolve_stack_mode("") == ida.SITE_STACK_MODE
    assert ida.SITE_STACK_MODE == "bind", \
        "the fixture site must stay on bind -- it stands in for the live fleet"
    # ...and the SIGNATURE default is the literal too, so a helper's shape
    # cannot change with whichever manifest is on $CCSYNC_SITE.
    assert _service("bind")["volumes"] == \
        ida.compose_config(8480, HOST_ROOT, "http://gui:8384", "k",
                           "t")["services"]["dashboard"]["volumes"]


def test_the_flag_beats_the_manifest():
    assert ida.resolve_stack_mode("image") == "image"
    assert ida.resolve_stack_mode("bind") == "bind"
    assert ida.resolve_stack_mode(" IMAGE ") == "image"


def test_a_manifest_that_says_image_is_honoured_without_a_flag(monkeypatch):
    monkeypatch.setattr(ida, "SITE_STACK_MODE", "image")
    assert ida.resolve_stack_mode("") == "image"


def test_an_unknown_mode_is_refused_rather_than_silently_deploying_bind(monkeypatch):
    """A typo in the manifest that quietly deployed the OTHER shape is a
    migration that reports success and changes nothing."""
    monkeypatch.setattr(ida, "SITE_STACK_MODE", "iamge")
    with pytest.raises(common.EnvError) as excinfo:
        ida.resolve_stack_mode("")
    assert "iamge" in str(excinfo.value) and "bind" in str(excinfo.value)


def test_the_image_comes_from_the_flag_then_the_env_then_the_manifest(monkeypatch):
    monkeypatch.delenv("CCSYNC_IMAGE", raising=False)
    assert ida.resolve_container_image("") == ida.SITE_CONTAINER_IMAGE
    monkeypatch.setenv("CCSYNC_IMAGE", "ghcr.io/env/img:2")
    assert ida.resolve_container_image("") == "ghcr.io/env/img:2"
    assert ida.resolve_container_image("ghcr.io/flag/img:3") == "ghcr.io/flag/img:3"


def test_the_default_image_is_the_tag_ci_publishes():
    """.github/workflows/image.yml's deliberately fixed `:1` -- the one
    long-lived tag compose.appliance.yaml pins too."""
    assert ida.DEFAULT_CONTAINER_IMAGE == "ghcr.io/the-creators-club/ccsync:1"


# --------------------------------------------------------------------------
# The pre-flight: everything image mode refuses BEFORE anything moves
# --------------------------------------------------------------------------

def test_image_mode_refuses_an_empty_release_pubkey_set(monkeypatch, capsys):
    """ZERO_TOUCH_PLAN.md WP K: the image's own select_code_root.py verifies
    every /data/code tree against these keys before booting it, so with none
    the image ALWAYS wins and no over-the-air update can ever apply. A site
    that migrated to get self-updating dashboards would have migrated for
    nothing, and nothing in the running system would say so."""
    monkeypatch.delenv("DASH_RELEASE_PUBKEYS", raising=False)
    problem = ida.image_mode_preflight("ghcr.io/x/y:1", dry_run=True)
    assert problem
    assert "DASH_RELEASE_PUBKEYS" in problem
    assert "release_key.py pubkey" in problem


def test_a_blank_release_feed_is_a_warning_not_a_refusal(monkeypatch, capsys):
    """Image mode without a feed is a valid deployment -- it just updates from
    the base rig, like bind mode does. Refusing it would make the migration
    conditional on a second, unrelated decision."""
    monkeypatch.setenv("DASH_RELEASE_PUBKEYS", "key==")
    assert ida.image_mode_preflight("ghcr.io/x/y:1", dry_run=True) == ""
    err = capsys.readouterr().err
    assert "feed_url is blank" in err


def test_the_preflight_prints_the_runtime_id_the_deploy_expects(monkeypatch, capsys):
    """So `docker exec <c> cat /venv/.runtime-id` has something to be compared
    against -- that comparison is what decides whether the Packages page offers
    a code update or says 'runtime update'."""
    monkeypatch.setenv("DASH_RELEASE_PUBKEYS", "key==")
    ida.image_mode_preflight("ghcr.io/x/y:1", dry_run=True)
    out = capsys.readouterr().out
    assert "expected runtime id: " in out
    assert "cat /venv/.runtime-id" in out
    assert re.search(r"expected runtime id: [0-9a-f]{64}", out), \
        "the id should be a sha256 hex digest computed from this checkout"


def test_the_expected_runtime_id_matches_the_dockerfile_and_the_lock():
    """One recipe, three callers (runtime_id.py's own docstring). If this
    drifts, every bundle built here is refused by every image built here."""
    import importlib.util

    repo = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "_rid", repo / "dashboard" / "src" / "ccsync_dashboard" / "runtime_id.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert ida.expected_runtime_id() == module.runtime_id_from_paths(
        repo / "dashboard" / "deploy" / "requirements.lock",
        repo / "dashboard" / "deploy" / "Dockerfile")


def test_a_tag_gets_a_digest_note_and_a_digest_does_not(monkeypatch, capsys):
    monkeypatch.setenv("DASH_RELEASE_PUBKEYS", "key==")
    ida.image_mode_preflight("ghcr.io/x/y:1", dry_run=True)
    assert "is a TAG, not a digest" in capsys.readouterr().err
    ida.image_mode_preflight("ghcr.io/x/y@sha256:abc", dry_run=True)
    assert "is a TAG, not a digest" not in capsys.readouterr().err


# --------------------------------------------------------------------------
# The post-deploy check's parsers
# --------------------------------------------------------------------------

IMAGE_BOOT_LOG = """\
run.sh: WARNING: running as uid 3000, but APP_UID says 3001.
select_code_root: no current.json -- using the image
run.sh: PYTHONPATH=/app/src:/broll-app:/music-app:/ytdl-app
INFO:     Uvicorn running on http://0.0.0.0:8480
"""

VOLUME_BOOT_LOG = """\
select_code_root: /data/code/0.6.1 verified (runtime_id matches)
run.sh: PYTHONPATH=/data/code/0.6.1/src:/data/code/0.6.1/broll-app
INFO:     Uvicorn running on http://0.0.0.0:8480
"""

BIND_BOOT_LOG = """\
run.sh: installing dependencies from /app/deploy/requirements.lock
INFO:     Uvicorn running on http://0.0.0.0:8480
"""


def test_the_boot_parser_says_the_image_won():
    boot = ida.parse_image_boot(IMAGE_BOOT_LOG)
    assert boot["source"] == "image"
    assert boot["code_root"] == "/app/src"
    assert boot["select_lines"] == ["select_code_root: no current.json -- using the image"]


def test_the_boot_parser_says_when_a_bundle_won():
    """Not a failure: a code bundle applied over the air is the FEATURE image
    mode exists for. It is reported because a deploy that just installed an
    image and finds a volume tree running is a fact the operator must be told
    -- the image is the runtime under it."""
    boot = ida.parse_image_boot(VOLUME_BOOT_LOG)
    assert boot["source"] == "volume"
    assert boot["code_root"] == "/data/code/0.6.1/src"


def test_the_boot_parser_reports_nothing_when_the_container_is_not_in_image_mode():
    """No `run.sh: PYTHONPATH=` line at all means run.sh took the single-exec
    path -- i.e. /venv/.image-baked is missing, i.e. a /venv MOUNT is shadowing
    the image's layer (docs/DOCKER.md, "What to check after either switch")."""
    boot = ida.parse_image_boot(BIND_BOOT_LOG)
    assert boot["source"] == "" and boot["pythonpath"] == ""


def test_the_boot_parser_takes_the_LAST_pythonpath_line():
    """run.sh's exit-75 loop re-selects and re-prints on every restart, so the
    first line is history and the last one is what is running."""
    boot = ida.parse_image_boot(IMAGE_BOOT_LOG + VOLUME_BOOT_LOG)
    assert boot["source"] == "volume"


def test_the_boot_parser_surfaces_run_sh_fatals():
    boot = ida.parse_image_boot("run.sh: FATAL: /venv is not mounted.\n")
    assert boot["fatal"] == ["run.sh: FATAL: /venv is not mounted."]


def test_the_health_parser_ignores_whatever_sudo_and_ssh_prepend():
    """This value comes back through docker exec, through sudo, through SSH,
    and every one of those can put a line in front of it."""
    assert ida.parse_health_line(
        '[sudo] password for admin:\n{"ok": true, "version": "0.6.0"}\n'
    ) == {"ok": True, "version": "0.6.0"}
    assert ida.parse_health_line("") == {}
    assert ida.parse_health_line("not json at all") == {}
    assert ida.parse_health_line("{broken") == {}


# --------------------------------------------------------------------------
# The whole deploy, in --dry-run, in both modes
# --------------------------------------------------------------------------

def _dry_run(monkeypatch, capsys, extra_argv=()):
    """Copied in shape from test_deploy_resilience._dry_run -- same fakes, same
    "everything an admin would see" transcript."""
    cmds: list = []

    def record(cmd, dry_run=False, timeout=120):
        cmds.append(cmd)
        return 0, "", ""

    for name, value in (("SYNCTHING_API_KEY", "k"), ("DASH_REPORT_TOKEN", "t"),
                        ("DASH_SESSION_SECRET", "s"), ("TRUENAS_PW", "pw"),
                        ("DASH_RELEASE_PUBKEYS", "testkey=="),
                        ("BROLL_INGEST_TOKEN", "ingestTOKENsentinel4b7d1e9a03c6")):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(ida, "run_ssh", record)
    monkeypatch.setattr(sys, "argv", ["install_dashboard_app.py", "--dry-run",
                                      "--music-data", "none", *extra_argv])
    rc = ida.main()
    captured = capsys.readouterr()
    return rc, "\n".join([captured.out, captured.err, *cmds])


def test_a_dry_run_in_image_mode_ships_no_code_and_deletes_nothing(monkeypatch, capsys):
    shipped: list = []
    monkeypatch.setattr(ida, "install_tree",
                        lambda root, target, *a, **k: shipped.append(target) or True)
    rc, transcript = _dry_run(monkeypatch, capsys, ("--mode", "image"))
    assert rc == 0
    assert shipped == [], f"image mode uploaded code trees: {shipped}"
    assert "image mode: shipping no code" in transcript
    assert ida.DEFAULT_CONTAINER_IMAGE in transcript
    # The host dirs are still CREATED (they hold the data, and the unused code
    # trees are the rollback) and nothing removes them.
    assert "host dirs ready" in transcript
    assert "rm -rf" not in transcript.split("host dirs ready")[0]


def test_a_dry_run_in_image_mode_posts_the_image_body(monkeypatch, capsys):
    rc, transcript = _dry_run(monkeypatch, capsys, ("--mode", "image"))
    assert rc == 0
    assert "'image': 'ghcr.io/the-creators-club/ccsync:1'" in transcript
    # the five code mounts are gone from the body the middleware would store
    for mount in ida.IMAGE_MODE_CODE_MOUNTS:
        assert f":{mount}:" not in transcript and f":{mount}'" not in transcript, mount
    # ...and the data mounts are not
    assert "/broll-data:rw" in transcript and ":/data'" in transcript


def test_passing_the_mode_flag_implies_recreate(monkeypatch, capsys):
    """The mode is baked in at CREATE time like every other compose-level
    setting: switching without re-creating changes nothing and says it did."""
    # A dry run reports every app as absent (backend().app_installed), so the
    # delete branch is only reachable with an INSTALLED app -- which is the
    # state a migration actually happens in.
    monkeypatch.setattr(ida, "app_installed", lambda dry_run: True)
    monkeypatch.setattr(ida, "install_tree", lambda *a, **k: True)
    monkeypatch.setattr(ida, "verify_image_boot", lambda *a, **k: True)
    rc, transcript = _dry_run(monkeypatch, capsys, ("--mode", "image"))
    assert rc == 0
    assert "implying --recreate" in transcript
    assert "would delete app ccsync-dashboard and re-create it" in transcript


def test_the_rollback_command_is_the_same_command_with_the_other_mode(monkeypatch,
                                                                     capsys):
    """`--mode bind` re-renders the bind compose and re-ships the code. The
    host trees were never touched by the migration, so this is a rollback and
    not a rebuild."""
    shipped: list = []
    monkeypatch.setattr(ida, "install_tree",
                        lambda root, target, *a, **k: shipped.append(target) or True)
    rc, transcript = _dry_run(monkeypatch, capsys, ("--mode", "bind"))
    assert rc == 0
    assert shipped == ["app", "broll-web", "music-web", "ytdl-web"]
    assert "stack mode: bind" in transcript
    assert "implying --recreate" in transcript
    assert "'image': 'python:3.12.7-slim'" in transcript


def test_image_mode_still_provisions_ffmpeg_because_the_image_does_not_carry_it(
        monkeypatch, capsys):
    """docs/DOCKER.md, "What image mode does NOT bake in": the static ffmpeg is
    GPLv3 and putting it in a vendor image is conveying it. So it stays a host
    mount in BOTH modes, and a migration that stopped provisioning it would
    give /music's queued ingest a 503 nobody expected."""
    monkeypatch.setattr(ida, "install_tree", lambda *a, **k: True)
    calls: list = []
    monkeypatch.setattr(ida, "provision_ffmpeg",
                        lambda root, fetch, dry: calls.append(fetch))
    rc, transcript = _dry_run(monkeypatch, capsys, ("--mode", "image"))
    assert rc == 0 and calls == ["remote"]
    assert f"{ida.DEFAULT_HOST_ROOT}/ffmpeg" in transcript


def test_image_mode_refuses_before_anything_moves_without_release_keys(monkeypatch,
                                                                      capsys):
    """A real run returns 1; a --dry-run says "would FAIL" and carries on, so
    the rest of the plan is still inspectable. Same shape as the b-roll
    ingest-token pre-flight beside it."""
    monkeypatch.setattr(ida, "install_tree", lambda *a, **k: True)
    monkeypatch.delenv("DASH_RELEASE_PUBKEYS", raising=False)
    cmds: list = []

    def record(cmd, dry_run=False, timeout=120):
        cmds.append(cmd)
        return 0, "", ""

    for name, value in (("SYNCTHING_API_KEY", "k"), ("DASH_REPORT_TOKEN", "t"),
                        ("DASH_SESSION_SECRET", "s"), ("TRUENAS_PW", "pw"),
                        ("BROLL_INGEST_TOKEN", "ingestTOKENsentinel4b7d1e9a03c6")):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(ida, "run_ssh", record)
    monkeypatch.setattr(sys, "argv", ["install_dashboard_app.py", "--dry-run",
                                      "--music-data", "none", "--mode", "image"])
    assert ida.main() == 0
    err = capsys.readouterr().err
    assert "[dry-run] would FAIL" in err and "DASH_RELEASE_PUBKEYS" in err


def test_image_mode_does_not_need_the_sub_app_checkouts(monkeypatch, capsys):
    """The three sub-app trees are image layers in image mode, so a checkout
    without broll/web is not a broken deploy -- there is no host mount for it
    to leave empty. In BIND mode that same absence is still a refusal, because
    DASH_BROLL_ENABLED=1 is an operator saying they want the feature."""
    monkeypatch.setattr(ida, "install_tree", lambda *a, **k: True)
    monkeypatch.setenv("BROLL_WEB_SRC", str(Path(__file__).parent / "nope"))
    rc, transcript = _dry_run(monkeypatch, capsys, ("--mode", "image"))
    assert rc == 0
    assert "no b-roll app at" not in transcript
    rc_bind, transcript_bind = _dry_run(monkeypatch, capsys, ("--mode", "bind"))
    assert "no b-roll app at" in transcript_bind


def test_image_mode_pulls_the_image_onto_the_nas(monkeypatch, capsys):
    """A create job pulls by itself; a RESTART never does, which is the path a
    routine redeploy takes -- so a floating tag that moved upstream would
    otherwise reach nothing."""
    monkeypatch.setattr(ida, "install_tree", lambda *a, **k: True)
    _rc, transcript = _dry_run(monkeypatch, capsys, ("--mode", "image"))
    assert f"docker pull '{ida.DEFAULT_CONTAINER_IMAGE}'" in transcript
    _rc2, no_pull = _dry_run(monkeypatch, capsys,
                             ("--mode", "image", "--no-image-pull"))
    assert "docker pull" not in no_pull


def test_a_restart_in_image_mode_says_it_keeps_the_current_image(monkeypatch, capsys):
    """The OPS-4 class of failure this file keeps getting bitten by: "the
    deploy succeeded and the code did not change". `docker restart` re-uses the
    existing container, image id and all, so the image just pulled reaches
    nothing until the app is re-created."""
    monkeypatch.setattr(ida, "install_tree", lambda *a, **k: True)
    monkeypatch.setattr(ida, "app_installed", lambda dry_run: True)
    monkeypatch.setattr(ida, "restart_dashboard_container", lambda dry_run: (True, ""))
    monkeypatch.setattr(ida, "verify_image_boot", lambda *a, **k: True)
    monkeypatch.setattr(ida, "SITE_STACK_MODE", "image")
    # No --mode flag, so --recreate is NOT implied: a site that LIVES in image
    # mode must not delete and re-create its app on every routine redeploy.
    rc, transcript = _dry_run(monkeypatch, capsys)
    assert rc == 0
    assert "a restart keeps the container's CURRENT image" in transcript
    assert "would delete app" not in transcript


def test_bind_mode_pulls_nothing(monkeypatch, capsys):
    monkeypatch.setattr(ida, "install_tree", lambda *a, **k: True)
    _rc, transcript = _dry_run(monkeypatch, capsys, ("--mode", "bind"))
    assert "docker pull" not in transcript
