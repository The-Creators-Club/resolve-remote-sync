"""dashboard/deploy/select_code_root.py -- which code tree the container boots
(ZERO_TOUCH_PLAN.md WP K, 2026-08-18).

Run as a real SUBPROCESS against a temp /data, /app and /venv, the way
server/tests executes its generated remote scripts: this script's whole job
is to be the thing that decides BEFORE the app exists, so importing it into
the test process would test something else. Its stdout is a PYTHONPATH that
run.sh exports verbatim, so every case asserts on that string.

The decision table these cases cover, in one place:

    current.json absent/blank      -> the image
    good tree, verified, newer     -> the volume tree
    record.json missing            -> the image (an unsigned tree never boots)
    record signed by another key   -> the image
    runtime_id != /venv/.runtime-id-> the image
    version <= the image's own     -> the image
    two failed boots already       -> revert current.json, then the image
    DASH_RELEASE_PUBKEYS unset     -> the image
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ccsync_dashboard import ed25519, release_trust

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "dashboard" / "deploy" / "select_code_root.py"

TEST_SEED = bytes(range(32))
TEST_PUBKEY = base64.b64encode(ed25519.public_key(TEST_SEED)).decode("ascii")
OTHER_SEED = bytes(range(32, 64))

IMAGE_VERSION = "0.5.0"
NEW_VERSION = "0.9.0"
RUNTIME_ID = "a" * 64


def sign(record: dict, seed: bytes = TEST_SEED) -> dict:
    out = dict(record)
    out["signature"] = base64.b64encode(
        ed25519.sign(seed, release_trust.canonical_record(record))).decode("ascii")
    return out


def make_record(*, version=NEW_VERSION, runtime_id=RUNTIME_ID, seed=TEST_SEED, kind="dashboard"):
    return sign({
        "kind": kind, "platform": "linux", "version": version,
        "filename": f"ccsync-dashboard-{version}.tar.gz",
        "sha256": "0" * 64, "size_bytes": 1234, "min_version": "0.0.0",
        "published_at": "2026-08-18T00:00:00Z", "signed_binary": False,
        "runtime_id": runtime_id,
    }, seed)


@pytest.fixture
def world(tmp_path):
    """A temp /app (the image), /venv and /data (the volume)."""
    app = tmp_path / "app"
    (app / "src").mkdir(parents=True)
    # A REAL copy of the package, because the script imports the image's own
    # release_trust out of <app>/src to verify with; a stub would exercise a
    # fallback that does not exist in a container. Only __init__.py is
    # replaced, to give this "image" a version the fixture controls.
    shutil.copytree(REPO / "dashboard" / "src" / "ccsync_dashboard",
                    app / "src" / "ccsync_dashboard",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (app / "src" / "ccsync_dashboard" / "__init__.py").write_text(
        f'VERSION = "{IMAGE_VERSION}"\n', encoding="utf-8")
    venv = tmp_path / "venv"
    venv.mkdir()
    (venv / ".runtime-id").write_text(RUNTIME_ID, encoding="utf-8")
    data = tmp_path / "data"
    (data / "code").mkdir(parents=True)
    return {"app": app, "venv": venv, "data": data, "code": data / "code"}


def install_tree(world, *, version=NEW_VERSION, runtime_id=RUNTIME_ID,
                 record: dict | None = None, manifest_runtime: str | None = None,
                 with_record=True):
    root = world["code"] / version
    for name in ("src", "broll-app", "music-app", "ytdl-app"):
        (root / name).mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "kind": "dashboard", "version": version,
        "runtime_id": manifest_runtime if manifest_runtime is not None else runtime_id,
        "files_sha256": {},
    }), encoding="utf-8")
    if with_record:
        (root / "record.json").write_text(
            json.dumps(record or make_record(version=version, runtime_id=runtime_id)),
            encoding="utf-8")
    return root


def set_current(world, version, previous=""):
    (world["code"] / "current.json").write_text(
        json.dumps({"version": version, "previous": previous}), encoding="utf-8")


def run(world, *, pubkeys: str = TEST_PUBKEY) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({
        "CCSYNC_DATA_DIR": str(world["data"]),
        "CCSYNC_APP_ROOT": str(world["app"]),
        "CCSYNC_VENV_DIR": str(world["venv"]),
        "DASH_RELEASE_PUBKEYS": pubkeys,
        # Nothing else on the path: the script has to find its verifier under
        # CCSYNC_APP_ROOT, exactly as it does in the image.
        "PYTHONPATH": "",
    })
    return subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env=env)


def image_path(world) -> str:
    # str(Path(...)) rather than the literals: the script builds these with
    # pathlib, and this suite runs on Windows where that renders "\broll-app".
    # In the container -- the only place it matters -- they are identical.
    return os.pathsep.join([str(world["app"] / "src")]
                           + [str(Path(p)) for p in ("/broll-app", "/music-app", "/ytdl-app")])


def volume_path(world, version=NEW_VERSION) -> str:
    root = world["code"] / version
    return os.pathsep.join([str(root / "src"), str(root / "broll-app"),
                            str(root / "music-app"), str(root / "ytdl-app")])


# ------------------------------------------------------------- the happy path


def test_no_current_json_boots_the_image_quietly(world):
    proc = run(world)
    assert proc.returncode == 0
    assert proc.stdout.strip() == image_path(world)
    assert "WARNING" not in proc.stderr


def test_a_verified_newer_tree_is_booted(world):
    install_tree(world)
    set_current(world, NEW_VERSION)
    proc = run(world)
    assert proc.stdout.strip() == volume_path(world)
    assert "booting the installed code tree 0.9.0" in proc.stderr


def test_booting_a_tree_counts_an_attempt(world):
    install_tree(world)
    set_current(world, NEW_VERSION)
    run(world)
    state = json.loads((world["code"] / "boot_attempts.json").read_text())
    assert state == {"version": NEW_VERSION, "attempts": 1}
    run(world)
    state = json.loads((world["code"] / "boot_attempts.json").read_text())
    assert state["attempts"] == 2


# ----------------------------------------------------------------- refusals


def test_a_tree_with_no_record_is_never_booted(world):
    install_tree(world, with_record=False)
    set_current(world, NEW_VERSION)
    proc = run(world)
    assert proc.stdout.strip() == image_path(world)
    assert "record.json is missing" in proc.stderr


def test_a_record_signed_by_another_key_is_refused(world):
    install_tree(world, record=make_record(seed=OTHER_SEED))
    set_current(world, NEW_VERSION)
    proc = run(world)
    assert proc.stdout.strip() == image_path(world)
    assert "does not verify" in proc.stderr


def test_a_tampered_runtime_id_is_refused(world):
    """The runtime_id is INSIDE the signature, so editing it in record.json
    breaks the signature -- which is the property that makes the two-tier
    rule enforceable rather than advisory."""
    record = make_record()
    record["runtime_id"] = "b" * 64
    install_tree(world, record=record)
    set_current(world, NEW_VERSION)
    proc = run(world)
    assert proc.stdout.strip() == image_path(world)
    assert "does not verify" in proc.stderr


def test_a_bundle_for_another_runtime_is_refused(world):
    """Correctly signed, but built against a different image: its
    dependencies are not in this container's venv."""
    install_tree(world, runtime_id="c" * 64, record=make_record(runtime_id="c" * 64))
    set_current(world, NEW_VERSION)
    proc = run(world)
    assert proc.stdout.strip() == image_path(world)
    assert "was built for runtime" in proc.stderr


def test_a_manifest_that_disagrees_with_the_image_is_refused(world):
    install_tree(world, manifest_runtime="d" * 64)
    set_current(world, NEW_VERSION)
    proc = run(world)
    assert proc.stdout.strip() == image_path(world)
    assert "manifest.json's runtime_id does not match" in proc.stderr


def test_an_older_tree_loses_to_the_image(world):
    """A code bundle can never roll the image backwards: after an image
    update the installed tree is stale, and the image wins until a newer
    bundle is applied."""
    install_tree(world, version="0.4.0", record=make_record(version="0.4.0"))
    set_current(world, "0.4.0")
    proc = run(world)
    assert proc.stdout.strip() == image_path(world)
    assert "not newer than the image" in proc.stderr


def test_an_equal_version_loses_to_the_image(world):
    install_tree(world, version=IMAGE_VERSION, record=make_record(version=IMAGE_VERSION))
    set_current(world, IMAGE_VERSION)
    proc = run(world)
    assert proc.stdout.strip() == image_path(world)


def test_no_pubkeys_configured_means_nothing_can_be_verified(world):
    install_tree(world)
    set_current(world, NEW_VERSION)
    proc = run(world, pubkeys="")
    assert proc.stdout.strip() == image_path(world)
    assert "DASH_RELEASE_PUBKEYS is not set" in proc.stderr


def test_a_missing_root_directory_is_refused(world):
    root = install_tree(world)
    set_current(world, NEW_VERSION)
    (root / "music-app").rmdir()
    proc = run(world)
    assert proc.stdout.strip() == image_path(world)
    assert "music-app is missing" in proc.stderr


def test_a_creative_version_string_is_refused(world):
    (world["code"] / "current.json").write_text(
        json.dumps({"version": "../../etc", "previous": ""}), encoding="utf-8")
    proc = run(world)
    assert proc.stdout.strip() == image_path(world)


def test_no_runtime_id_in_the_image_refuses_every_tree(world):
    """An image built before WP K (or a bind-mount deployment that somehow
    ran this) can match no bundle at all."""
    install_tree(world)
    set_current(world, NEW_VERSION)
    (world["venv"] / ".runtime-id").unlink()
    proc = run(world)
    assert proc.stdout.strip() == image_path(world)
    assert "no /venv/.runtime-id" in proc.stderr


# ----------------------------------------------------------------- watchdog


def test_two_failed_boots_revert_to_the_previous_tree(world):
    install_tree(world, version="0.8.0", record=make_record(version="0.8.0"))
    install_tree(world, version=NEW_VERSION)
    set_current(world, NEW_VERSION, previous="0.8.0")

    # Two boots that never reach healthy (nothing clears boot_attempts.json).
    assert run(world).stdout.strip() == volume_path(world, NEW_VERSION)
    assert run(world).stdout.strip() == volume_path(world, NEW_VERSION)

    proc = run(world)
    assert proc.stdout.strip() == volume_path(world, "0.8.0")
    assert "REVERTED to 0.8.0" in proc.stderr
    current = json.loads((world["code"] / "current.json").read_text())
    assert current["version"] == "0.8.0"
    assert current["reverted_from"] == NEW_VERSION
    assert "failed to reach a healthy boot" in current["reverted_reason"]
    # The failed tree's files are LEFT ALONE: they are the evidence.
    assert (world["code"] / NEW_VERSION / "manifest.json").is_file()


def test_two_failed_boots_with_no_previous_tree_revert_to_the_image(world):
    install_tree(world)
    set_current(world, NEW_VERSION)
    run(world)
    run(world)
    proc = run(world)
    assert proc.stdout.strip() == image_path(world)
    assert "REVERTED to the image" in proc.stderr


def test_a_cleared_counter_is_a_fresh_start(world):
    """What the app does once it has been up long enough
    (dashboard_update.clear_boot_attempts): the counter goes, and the tree is
    not one boot away from being reverted forever after."""
    install_tree(world)
    set_current(world, NEW_VERSION)
    run(world)
    run(world)
    (world["code"] / "boot_attempts.json").unlink()
    proc = run(world)
    assert proc.stdout.strip() == volume_path(world)


def test_a_read_only_data_volume_still_boots(world):
    """Nothing in this script may stop the container starting. A /data it
    cannot write means no watchdog bookkeeping, not a dead dashboard."""
    install_tree(world)
    set_current(world, NEW_VERSION)
    (world["code"] / "boot_attempts.json").mkdir()   # a directory: writes fail
    proc = run(world)
    assert proc.returncode == 0
    assert proc.stdout.strip() == volume_path(world)
    assert "WARNING: could not write" in proc.stderr
