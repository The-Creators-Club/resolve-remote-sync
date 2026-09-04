"""tools/build_dashboard_bundle.py -- the dashboard's own code bundle
(ZERO_TOUCH_PLAN.md WP K, 2026-08-18), plus the runtime_id recipe both it and
the Dockerfile use, and the `dashboard` kind's signed record.

Every test builds from a FAKE repo tree in tmp_path rather than this
checkout: what matters is the layout rule (which trees, which exclusions,
which manifest), and a test that packed the real 200-file tree would be slow
and would change every time anything in the repo did. One test at the end
does use the real checkout, because "the version in the bundle is the version
/api/v1/health reports" is a claim about THIS repo."""
from __future__ import annotations

import base64
import json
import sys
import tarfile
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "companion" / "src"))
sys.path.insert(0, str(REPO / "dashboard" / "src"))

import build_dashboard_bundle as bdb  # noqa: E402
import release_key as release_key_mod  # noqa: E402
import sign_release  # noqa: E402

from ccsync_companion import ed25519, release_pubkey  # noqa: E402
from ccsync_dashboard import runtime_id as runtime_id_mod  # noqa: E402


def make_repo(tmp_path: Path) -> Path:
    """A minimal checkout with one file per tree plus everything the builder
    is supposed to leave behind."""
    root = tmp_path / "repo"
    for rel in ("dashboard/src/ccsync_dashboard", "dashboard/templates", "dashboard/static",
                "dashboard/deploy", "broll/web/app", "music/web/musicweb", "ytdl/web/ytdlweb",
                # REL-5 (usability sweep 2026-09-04): the legal paperwork and
                # the help guide travel with the code now, so a checkout
                # without them is a checkout this builder refuses.
                "docs/legal"):
        (root / rel).mkdir(parents=True)
    (root / "docs/legal/EULA.md").write_text("<!-- EULA-VERSION: 1.0 -->\n")
    (root / "docs/HOW_IT_WORKS.md").write_text("# How it works\n")
    (root / "dashboard/src/ccsync_dashboard/__init__.py").write_text('VERSION = "9.9.9"\n')
    (root / "dashboard/templates/base.html").write_text("<html></html>\n")
    (root / "dashboard/static/style.css").write_text("body{}\n")
    (root / "dashboard/deploy/requirements.lock").write_text("fastapi==0.1\n")
    (root / "dashboard/deploy/Dockerfile").write_text(
        "ARG BASE_IMAGE=python:3.12.7-slim@sha256:deadbeef\nFROM ${BASE_IMAGE}\n")
    (root / "broll/web/app/main.py").write_text("x = 1\n")
    (root / "music/web/musicweb/main.py").write_text("x = 2\n")
    (root / "ytdl/web/ytdlweb/main.py").write_text("x = 3\n")

    # ...and the things that must NOT travel.
    (root / "dashboard/src/ccsync_dashboard/__pycache__").mkdir()
    (root / "dashboard/src/ccsync_dashboard/__pycache__/x.cpython-312.pyc").write_bytes(b"\x00")
    (root / "dashboard/tests").mkdir()
    (root / "dashboard/tests/test_x.py").write_text("assert True\n")
    (root / "music/web/data").mkdir()
    (root / "music/web/data/music.db").write_bytes(b"SQLite format 3\x00" + b"x" * 100)
    (root / "music/web/.venv/lib").mkdir(parents=True)
    (root / "music/web/.venv/lib/thing.py").write_text("x = 4\n")
    (root / "dashboard/static/style.css.map").write_text("{}\n")
    return root


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path)


def read_bundle(path: Path) -> tuple[dict, list[str]]:
    with tarfile.open(path, "r:gz") as tar:
        manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
        return manifest, sorted(n for n in tar.getnames() if n != "manifest.json")


# ------------------------------------------------------------------ layout


def test_bundle_carries_exactly_the_seven_trees_and_the_two_documents(repo, tmp_path):
    result = bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9")
    manifest, names = read_bundle(result["path"])
    assert result["path"].name == "ccsync-dashboard-9.9.9.tar.gz"
    assert names == [
        "broll-app/app/main.py",
        "deploy/Dockerfile",
        "deploy/requirements.lock",
        # REL-5 (usability sweep 2026-09-04): the licence agreement the
        # first-run wizard makes an admin accept, and the guide /help renders.
        # An over-the-air dashboard that arrived without them showed an empty
        # licence box with a disabled [ ACCEPT ] and ticked `eula` green.
        "docs/HOW_IT_WORKS.md",
        "docs/legal/EULA.md",
        "music-app/musicweb/main.py",
        "src/ccsync_dashboard/__init__.py",
        "static/style.css",
        "templates/base.html",
        "ytdl-app/ytdlweb/main.py",
    ]
    assert set(manifest["files_sha256"]) == set(names)


def test_a_checkout_with_no_licence_agreement_is_refused(repo, tmp_path):
    """REL-5: not "warn and build". A bundle is what a customer's dashboard
    installs over the air, and one that quietly dropped the EULA would put
    every OTA site straight back into the state this wave found."""
    import shutil

    shutil.rmtree(repo / "docs" / "legal")
    with pytest.raises(bdb.BundleError) as exc:
        bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9")
    assert "docs/legal" in str(exc.value)

    (repo / "docs" / "legal").mkdir()
    (repo / "docs" / "legal" / "EULA.md").write_text("<!-- EULA-VERSION: 1.0 -->\n")
    (repo / "docs" / "HOW_IT_WORKS.md").unlink()
    with pytest.raises(bdb.BundleError) as exc:
        bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9")
    assert "HOW_IT_WORKS" in str(exc.value)


def test_templates_and_static_are_in_the_bundle(repo, tmp_path):
    """Not decoration: ui.py resolves TEMPLATES_DIR as parents[2] of the
    package, i.e. the bundle root. A tree without these two renders a 500 on
    every page while /api/v1/health stays perfectly green."""
    result = bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9")
    _manifest, names = read_bundle(result["path"])
    assert "templates/base.html" in names
    assert "static/style.css" in names


def test_excluded_things_never_travel(repo, tmp_path):
    result = bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9")
    _manifest, names = read_bundle(result["path"])
    joined = "\n".join(names)
    for forbidden in ("__pycache__", ".pyc", "tests/", "music-app/data", ".venv", ".map"):
        assert forbidden not in joined, forbidden


def test_manifest_shape(repo, tmp_path):
    result = bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9",
                       built_at="2026-08-18T00:00:00Z")
    manifest = result["manifest"]
    assert manifest["kind"] == "dashboard"
    assert manifest["version"] == "9.9.9"
    assert manifest["built_at"] == "2026-08-18T00:00:00Z"
    assert manifest["git_dirty"] is True          # tmp_path is not a git repo
    assert len(manifest["runtime_id"]) == 64
    assert all(len(v) == 64 for v in manifest["files_sha256"].values())


def test_the_bundle_verifies_itself(repo, tmp_path):
    result = bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9")
    ok, report = bdb.verify(result["path"])
    assert ok, report


def test_verify_catches_a_tampered_member(repo, tmp_path):
    """The manifest's per-file hashes are what the container re-checks at
    every boot; a bundle whose bytes and manifest disagree must be caught
    here, not by a customer."""
    result = bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9")
    with tarfile.open(result["path"], "r:gz") as tar:
        members = {m.name: (m, tar.extractfile(m).read() if m.isfile() else b"")
                   for m in tar.getmembers()}
    tampered = tmp_path / "tampered.tar.gz"
    import io
    with tarfile.open(tampered, "w:gz") as tar:
        for name, (member, data) in members.items():
            if name == "src/ccsync_dashboard/__init__.py":
                data = b'VERSION = "9.9.9"  # and something else\n'
                member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    ok, report = bdb.verify(tampered)
    assert not ok
    assert any("sha256 mismatch" in line for line in report)


def test_a_dirty_tree_is_refused_without_the_flag(repo, tmp_path, capsys):
    rc = bdb.main(["--repo-root", str(repo), "--out", str(tmp_path / "out")])
    assert rc == bdb.EXIT_DIRTY
    assert "DIRTY" in capsys.readouterr().err


def test_a_missing_tree_is_named(repo, tmp_path):
    import shutil

    shutil.rmtree(repo / "music/web")
    with pytest.raises(bdb.BundleError) as exc:
        bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9")
    assert "music/web" in str(exc.value)


# --------------------------------------------------------------- runtime_id


def test_runtime_id_depends_on_the_lock_and_the_base_image(repo, tmp_path):
    lock = repo / "dashboard/deploy/requirements.lock"
    dockerfile = repo / "dashboard/deploy/Dockerfile"
    first = runtime_id_mod.runtime_id_from_paths(lock, dockerfile)
    assert first == runtime_id_mod.runtime_id_from_paths(lock, dockerfile)   # deterministic

    lock.write_text("fastapi==0.2\n")
    assert runtime_id_mod.runtime_id_from_paths(lock, dockerfile) != first

    lock.write_text("fastapi==0.1\n")
    dockerfile.write_text("ARG BASE_IMAGE=python:3.13-slim@sha256:feedface\nFROM ${BASE_IMAGE}\n")
    assert runtime_id_mod.runtime_id_from_paths(lock, dockerfile) != first


def test_runtime_id_is_not_moved_by_a_comment(repo, tmp_path):
    """Only two inputs, on purpose: if every Dockerfile edit changed the id,
    every comment would become a runtime update the customer has to click
    through their NAS UI for."""
    lock = repo / "dashboard/deploy/requirements.lock"
    dockerfile = repo / "dashboard/deploy/Dockerfile"
    before = runtime_id_mod.runtime_id_from_paths(lock, dockerfile)
    dockerfile.write_text(dockerfile.read_text() + "# a new comment\nRUN echo hello\n")
    assert runtime_id_mod.runtime_id_from_paths(lock, dockerfile) == before


def test_a_build_arg_override_wins_over_the_file(repo):
    """The Dockerfile passes its OWN `ARG BASE_IMAGE` so a `--build-arg`
    override is reflected: an override changes what `import` can find, so it
    has to change the id."""
    lock = repo / "dashboard/deploy/requirements.lock"
    dockerfile = repo / "dashboard/deploy/Dockerfile"
    assert (runtime_id_mod.runtime_id_from_paths(lock, base_image="python:3.13-slim")
            != runtime_id_mod.runtime_id_from_paths(lock, dockerfile))


def test_a_dockerfile_with_no_base_image_arg_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        runtime_id_mod.base_image_from_dockerfile("FROM python:3.12-slim\n")


def test_the_real_dockerfile_declares_one():
    text = (REPO / "dashboard/deploy/Dockerfile").read_text(encoding="utf-8")
    assert runtime_id_mod.base_image_from_dockerfile(text).startswith("python:")


def test_the_dockerfile_bakes_the_runtime_id_and_the_two_missing_trees():
    """The image has to write /venv/.runtime-id (nothing can be applied
    without it) and it has to carry templates/ and static/ (found 2026-08-18:
    it did not, so every page 500'd in image mode)."""
    text = (REPO / "dashboard/deploy/Dockerfile").read_text(encoding="utf-8")
    assert "/venv/.runtime-id" in text
    assert "runtime_id_from_paths" in text
    assert "COPY dashboard/templates /app/templates" in text
    assert "COPY dashboard/static /app/static" in text


# ------------------------------------------------------- the signed record


@pytest.fixture
def key(tmp_path, monkeypatch):
    path = tmp_path / "release.key"
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(path))
    assert release_key_mod.main(["new"]) == 0
    return path


def _pubkeys_for(key_path) -> list[str]:
    secret = release_key_mod.read_secret(key_path)
    return [base64.b64encode(ed25519.public_key(secret)).decode("ascii")]


def test_sign_release_covers_the_runtime_id(key, repo, tmp_path):
    result = bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9")
    out = tmp_path / "record.json"
    rc = sign_release.main([
        "--artifact", str(result["path"]), "--kind", "dashboard", "--platform", "linux",
        "--version", "9.9.9", "--runtime-id", result["manifest"]["runtime_id"],
        "--out", str(out),
    ])
    assert rc == 0
    record = json.loads(out.read_text())
    assert record["kind"] == "dashboard"
    assert record["filename"] == "ccsync-dashboard-9.9.9.tar.gz"
    assert record["runtime_id"] == result["manifest"]["runtime_id"]

    pubkeys = _pubkeys_for(release_key_mod.key_path(""))
    ok, detail = release_pubkey.verify_record(record, record["signature"], pubkeys=pubkeys)
    assert ok, detail

    # ...and the signature does NOT survive a changed runtime_id, which is
    # the whole reason it is inside the record.
    tampered = dict(record)
    tampered["runtime_id"] = "0" * 64
    ok, _detail = release_pubkey.verify_record(tampered, record["signature"], pubkeys=pubkeys)
    assert not ok


def test_sign_release_refuses_a_dashboard_record_with_no_runtime_id(key, repo, tmp_path):
    result = bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9")
    with pytest.raises(SystemExit) as exc:
        sign_release.main([
            "--artifact", str(result["path"]), "--kind", "dashboard",
            "--platform", "linux", "--version", "9.9.9",
        ])
    assert "--runtime-id" in str(exc.value)


def test_companion_records_are_byte_identical_to_before(key, tmp_path):
    """The kind-scoped extra field must not have moved the bytes every
    companion in the field verifies. Signed with the OLD nine-field list by
    hand, verified with the new code."""
    artifact = tmp_path / "ccsync-companion.exe"
    artifact.write_bytes(b"MZ" + b"x" * 100)
    record = sign_release.build_record(
        artifact=artifact, kind="companion", platform="windows", version="0.8.0",
        min_version="0.7.0", published_at="2026-08-18T00:00:00Z", signed_binary=False)
    assert "runtime_id" not in record
    assert set(record) == set(release_pubkey.RECORD_FIELDS)
    assert release_pubkey.record_fields("companion") == release_pubkey.RECORD_FIELDS


def test_publish_feed_carries_the_runtime_id_into_the_channel(key, repo, tmp_path):
    import publish_feed as pf

    result = bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9")
    feed_dir = tmp_path / "feed"
    rc = pf.main([
        "--artifact", str(result["path"]), "--kind", "dashboard", "--platform", "linux",
        "--version", "9.9.9", "--feed-dir", str(feed_dir),
        "--base-url", "https://releases.example.test/v1",
    ])
    assert rc == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    record = channel["packages"][0]
    # ...read out of the bundle, not typed twice.
    assert record["runtime_id"] == result["manifest"]["runtime_id"]
    ok, report = pf.verify_feed_dir(feed_dir, pubkeys=_pubkeys_for(release_key_mod.key_path("")))
    assert ok, report


def test_publish_feed_refuses_a_runtime_id_that_disagrees(key, repo, tmp_path):
    import publish_feed as pf

    result = bdb.build(repo, tmp_path / "out", allow_dirty=True, version="9.9.9")
    rc = pf.main([
        "--artifact", str(result["path"]), "--kind", "dashboard", "--platform", "linux",
        "--version", "9.9.9", "--runtime-id", "0" * 64,
        "--feed-dir", str(tmp_path / "feed"), "--base-url", "https://releases.example.test/v1",
    ])
    assert rc == pf.EXIT_USAGE


# ------------------------------------------------------------ the real repo


def test_the_bundle_version_is_the_version_health_reports():
    """The claim the whole feature rests on: the version in a bundle's
    manifest is the version /api/v1/health answers with, so an admin can see
    the update land."""
    from ccsync_dashboard import VERSION

    assert bdb.DASHBOARD_VERSION == VERSION
    assert bdb.bundle_filename(VERSION) == f"ccsync-dashboard-{VERSION}.tar.gz"
    assert sign_release.package_filename("dashboard", "linux", VERSION) == bdb.bundle_filename(VERSION)
