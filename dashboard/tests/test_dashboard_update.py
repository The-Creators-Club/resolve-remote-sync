"""The dashboard updating its own code over the air (ZERO_TOUCH_PLAN.md WP K,
2026-08-18): the refusals, the apply, the rollback and the watchdog.

No network: `release_feed._opener` is monkeypatched to the same table-driven
fake `test_release_feed.py` uses, so the channel and the bundle are both
served from bytes this file built. No container either -- `/app`, `/venv` and
`/data` are three directories under tmp_path, which is the same seam
`select_code_root.py` exposes and the only reason any of this is testable off
a NAS.

The end-to-end apply builds a REAL bundle with tools/build_dashboard_bundle.py
and lets the REAL stage-verify subprocess import it and migrate a copy of
dashboard.db. That is slow (a couple of seconds) and it is the point: the
thing that decides whether a customer's dashboard swaps its own code is the
subprocess, and a mocked one would prove nothing.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, dashboard_update
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import ed25519, release_feed, release_trust
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

SECRET = "test-secret"
TEST_SEED = bytes(range(32))
TEST_PUBKEY = base64.b64encode(ed25519.public_key(TEST_SEED)).decode("ascii")

FEED_BASE = "https://releases.example.test/v1"
CHANNEL_URL = f"{FEED_BASE}/channel.json"
SIG_URL = f"{FEED_BASE}/channel.json.sig"
PUBLISHED_AT = "2026-08-18T00:00:00Z"

IMAGE_VERSION = "0.5.0"
NEW_VERSION = "9.9.9"
RUNTIME_ID = "a" * 64

# The fake-opener machinery is test_release_feed's; imported rather than
# copied so the two suites cannot drift about what "the network" looks like.
from test_release_feed import as_user, patch_opener  # noqa: E402


def sign_record(record: dict, seed: bytes = TEST_SEED) -> dict:
    out = dict(record)
    out["signature"] = base64.b64encode(
        ed25519.sign(seed, release_trust.canonical_record(record))).decode("ascii")
    out["pubkey_id"] = release_trust.pubkey_id(
        base64.b64encode(ed25519.public_key(seed)).decode("ascii"))
    return out


def make_dashboard_record(body: bytes, *, version=NEW_VERSION, runtime_id=RUNTIME_ID,
                          seed=TEST_SEED) -> dict:
    record = sign_record({
        "kind": "dashboard", "platform": "linux", "version": version,
        "filename": f"ccsync-dashboard-{version}.tar.gz",
        "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body),
        "min_version": "0.0.0", "published_at": PUBLISHED_AT, "signed_binary": False,
        "runtime_id": runtime_id,
    }, seed)
    record["url"] = f"{FEED_BASE}/linux/{record['filename']}"
    record["notes"] = "a code update"
    return record


def make_channel(records: list[dict], *, seed=TEST_SEED) -> tuple[dict, str]:
    channel = {
        "schema": 1, "generated_at": PUBLISHED_AT, "channel": "stable",
        "pubkey_id": release_trust.pubkey_id(
            base64.b64encode(ed25519.public_key(seed)).decode("ascii")),
        "dashboard_image": {"tag": "", "digest": ""},
        "packages": records,
    }
    sig = base64.b64encode(
        ed25519.sign(seed, release_feed.canonical_channel_bytes(channel))).decode("ascii")
    return channel, sig


@pytest.fixture(scope="session")
def bundle(tmp_path_factory):
    """One real bundle for the whole module: building it hashes ~200 files."""
    import build_dashboard_bundle as bdb

    out = tmp_path_factory.mktemp("bundle")
    result = bdb.build(REPO, out, allow_dirty=True, version=NEW_VERSION,
                       out=open(out / "build.log", "w", encoding="utf-8"))
    return {"path": result["path"], "bytes": result["path"].read_bytes(),
            "manifest": result["manifest"]}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A temp /data + /app, an image runtime id, and no real restarts."""
    data = tmp_path / "data"
    data.mkdir()
    app_root = tmp_path / "app"
    (app_root / "src" / "ccsync_dashboard").mkdir(parents=True)
    (app_root / "src" / "ccsync_dashboard" / "__init__.py").write_text(
        f'VERSION = "{IMAGE_VERSION}"\n', encoding="utf-8")
    monkeypatch.setattr(dashboard_update, "IMAGE_APP_ROOT", app_root)
    rid = tmp_path / "runtime-id"
    rid.write_text(RUNTIME_ID, encoding="utf-8")
    monkeypatch.setenv("CCSYNC_RUNTIME_ID_FILE", str(rid))
    restarts: list[int] = []
    monkeypatch.setattr(dashboard_update, "_signal_restart", lambda: restarts.append(1))
    # ...and the OTHER end of the same wire: the lifespan's shutdown path
    # exits the process with 75 when an update asked for one, which inside a
    # suite ends pytest itself (measured: 20 tests in, no summary, exit 75).
    exits: list[int] = []
    monkeypatch.setattr(dashboard_update, "_exit_process", exits.append)
    # Only the dashboard's own database: whether the b-roll and music indexes
    # are wired up is _db_paths' own test, and a session-scoped music mount
    # would otherwise decide it for every test here.
    settings = Settings(
        db_path=str(data / "dashboard.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), packages_dir=str(tmp_path / "pkgs"),
        release_pubkeys=(TEST_PUBKEY,), release_feed_url=CHANNEL_URL,
    )
    monkeypatch.setattr(dashboard_update, "_db_paths",
                        lambda s: {"dashboard": Path(s.db_path)})
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "pw"
    with TestClient(app) as client:
        as_user(client, "owen")
        yield {"client": client, "settings": settings, "app": app,
               "restarts": restarts, "exits": exits, "data": data,
               "runtime_id_file": rid}


def finish_the_restart(world):
    """What the container does between an apply and the next request: the
    lifespan's shutdown path consumes the restart flag (clearing
    `in_progress`) and exits 75, run.sh re-execs, and the new process comes up
    on the new tree. `_signal_restart` and `_exit_process` are stubbed in this
    suite, so a test that wants the AFTER state has to run this step itself."""
    dashboard_update.finish_restart(world["settings"])


def check(world, records: list[dict], monkeypatch, extra: dict | None = None):
    channel, sig = make_channel(records)
    table = {CHANNEL_URL: json.dumps(channel).encode(), SIG_URL: sig.encode()}
    table.update(extra or {})
    opener = patch_opener(monkeypatch, table)
    assert world["client"].post("/api/v1/admin/feed/check").json()["ok"] is True
    return opener


# ---------------------------------------------------------------- the split


def test_a_dashboard_record_never_shows_up_as_a_package(world, monkeypatch):
    """The rule the two halves of the feed rest on: a dashboard bundle is
    APPLIED, never PUBLISHED. A row in companion_packages would offer the
    dashboard's tarball to an editor's companion as an upgrade."""
    record = make_dashboard_record(b"bundle-bytes")
    check(world, [record], monkeypatch)
    feed = world["client"].get("/api/v1/admin/feed").json()
    assert feed["available"] == []
    status = world["client"].get("/api/v1/admin/dashboard-update").json()
    assert [u["version"] for u in status["code_updates"]] == [NEW_VERSION]


def test_publishing_a_dashboard_record_is_refused(world, monkeypatch):
    check(world, [make_dashboard_record(b"bundle-bytes")], monkeypatch)
    r = world["client"].post("/api/v1/admin/feed/publish",
                             json={"kind": "dashboard", "platform": "linux",
                                   "version": NEW_VERSION})
    assert r.status_code == 400
    assert "applied, not published" in r.json()["detail"]


def test_auto_publish_policy_never_applies_a_dashboard_bundle(world, monkeypatch):
    """`stage`/`current` are a policy about EDITOR packages. Replacing the
    code this container runs is a ten-second outage and an admin's decision."""
    world["client"].post("/api/v1/admin/feed/policy", json={"policy": "current"})
    check(world, [make_dashboard_record(b"bundle-bytes")], monkeypatch)
    assert world["client"].get("/api/v1/admin/dashboard-update").json()["current"]["version"] == ""
    assert world["restarts"] == []


# ------------------------------------------------------------ the two tiers


def test_a_matching_runtime_is_a_code_update(world, monkeypatch):
    check(world, [make_dashboard_record(b"x")], monkeypatch)
    status = world["client"].get("/api/v1/admin/dashboard-update").json()
    assert [u["version"] for u in status["code_updates"]] == [NEW_VERSION]
    assert status["runtime_updates"] == []


def test_a_different_runtime_is_a_runtime_update_with_the_nas_click(world, monkeypatch):
    check(world, [make_dashboard_record(b"x", runtime_id="b" * 64)], monkeypatch)
    status = world["client"].get("/api/v1/admin/dashboard-update").json()
    assert status["code_updates"] == []
    assert [u["version"] for u in status["runtime_updates"]] == [NEW_VERSION]
    assert status["nas_hint"] == "Apps > ccsync > Update"     # nas_kind defaults to truenas


def test_applying_a_runtime_update_is_refused(world, monkeypatch):
    check(world, [make_dashboard_record(b"x", runtime_id="b" * 64)], monkeypatch)
    r = world["client"].post("/api/v1/admin/dashboard-update/apply",
                             json={"version": NEW_VERSION})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "RUNTIME update" in detail and "image" in detail


# -------------------------------------------------------------- the refusals


def test_bind_mount_mode_offers_nothing_and_refuses_everything(world, monkeypatch):
    world["runtime_id_file"].unlink()
    status = world["client"].get("/api/v1/admin/dashboard-update").json()
    assert status["image_mode"] is False
    r = world["client"].post("/api/v1/admin/dashboard-update/apply",
                             json={"version": NEW_VERSION})
    assert r.status_code == 409
    assert "updates from the base rig" in r.json()["detail"]


def test_an_unknown_version_is_a_404(world, monkeypatch):
    check(world, [make_dashboard_record(b"x")], monkeypatch)
    r = world["client"].post("/api/v1/admin/dashboard-update/apply", json={"version": "1.2.3"})
    assert r.status_code == 404
    assert "Check now" in r.json()["detail"]


def test_the_running_version_is_refused(world, monkeypatch):
    from ccsync_dashboard import VERSION

    check(world, [make_dashboard_record(b"x", version=VERSION)], monkeypatch)
    r = world["client"].post("/api/v1/admin/dashboard-update/apply", json={"version": VERSION})
    assert r.status_code == 409
    assert "already running" in r.json()["detail"]


def test_a_version_the_image_already_carries_is_neither_offered_nor_applied(world, monkeypatch):
    """select_code_root gives a tie (or better) to the image, so applying an
    older bundle would land right back on the image's own code. Offering that
    button would be offering a no-op with a ten-second outage attached."""
    check(world, [make_dashboard_record(b"x", version="0.4.0")], monkeypatch)
    status = world["client"].get("/api/v1/admin/dashboard-update").json()
    assert status["code_updates"] == [] and status["runtime_updates"] == []
    r = world["client"].post("/api/v1/admin/dashboard-update/apply", json={"version": "0.4.0"})
    assert r.status_code == 409
    assert "not newer than the code in this container image" in r.json()["detail"]


def test_a_creative_version_is_refused_before_anything_else(world):
    r = world["client"].post("/api/v1/admin/dashboard-update/apply",
                             json={"version": "../../etc/passwd"})
    assert r.status_code == 400
    assert "names a directory" in r.json()["detail"]


def test_a_second_apply_while_one_runs_is_a_409(world, monkeypatch):
    check(world, [make_dashboard_record(b"x")], monkeypatch)
    dashboard_update._set_state(world["settings"], in_progress=True, step="downloading",
                                version=NEW_VERSION)
    r = world["client"].post("/api/v1/admin/dashboard-update/apply",
                             json={"version": NEW_VERSION})
    assert r.status_code == 409
    assert "already in progress" in r.json()["detail"]


def test_a_running_ytdl_job_blocks_an_apply_unless_forced(world, monkeypatch):
    check(world, [make_dashboard_record(b"x")], monkeypatch)
    monkeypatch.setattr(dashboard_update, "active_ytdl_jobs", lambda: 2)
    r = world["client"].post("/api/v1/admin/dashboard-update/apply",
                             json={"version": NEW_VERSION})
    assert r.status_code == 409
    assert "2 YouTube job(s) are running" in r.json()["detail"]
    # ...and force gets past exactly that check (the download then fails,
    # because this test registered no artefact url).
    monkeypatch.setattr(dashboard_update, "preflight",
                        lambda *a, **k: make_dashboard_record(b"x"))
    r = world["client"].post("/api/v1/admin/dashboard-update/apply",
                             json={"version": NEW_VERSION, "force": True})
    assert r.status_code == 200


def test_a_full_data_volume_is_refused_with_both_numbers(world, monkeypatch):
    check(world, [make_dashboard_record(b"x")], monkeypatch)
    monkeypatch.setattr(dashboard_update, "_free_bytes", lambda p: 1024)
    r = world["client"].post("/api/v1/admin/dashboard-update/apply",
                             json={"version": NEW_VERSION})
    assert r.status_code == 507
    assert "free" in r.json()["detail"] and "safety margin" in r.json()["detail"]


def test_every_route_needs_an_admin(world):
    client = world["client"]
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "notanadmin"))
    assert client.get("/api/v1/admin/dashboard-update").status_code == 403
    assert client.post("/api/v1/admin/dashboard-update/apply",
                       json={"version": NEW_VERSION}).status_code == 403
    assert client.post("/api/v1/admin/dashboard-update/rollback", json={}).status_code == 403


# ------------------------------------------------------------- safe extraction


def _tar_with(tmp_path: Path, name: str, *, symlink=False, absolute=False) -> Path:
    import io
    import tarfile

    path = tmp_path / "evil.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo(name)
        if symlink:
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        else:
            data = b"x"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def test_extraction_refuses_a_path_escape(tmp_path):
    evil = _tar_with(tmp_path, "../../etc/cron.d/x")
    with pytest.raises(dashboard_update.DashboardUpdateError) as exc:
        dashboard_update.extract_bundle(evil, tmp_path / "dest")
    assert "escapes the bundle" in exc.value.detail


def test_extraction_refuses_an_absolute_path(tmp_path):
    evil = _tar_with(tmp_path, "/etc/cron.d/x")
    with pytest.raises(dashboard_update.DashboardUpdateError) as exc:
        dashboard_update.extract_bundle(evil, tmp_path / "dest")
    assert "absolute path" in exc.value.detail


def test_extraction_refuses_a_symlink(tmp_path):
    evil = _tar_with(tmp_path, "src/shortcut", symlink=True)
    with pytest.raises(dashboard_update.DashboardUpdateError) as exc:
        dashboard_update.extract_bundle(evil, tmp_path / "dest")
    assert "is a link" in exc.value.detail


def test_a_bundle_whose_manifest_disagrees_with_the_record_is_refused(bundle, tmp_path):
    dest = tmp_path / "staged"
    manifest = dashboard_update.extract_bundle(bundle["path"], dest)
    record = make_dashboard_record(bundle["bytes"], runtime_id="b" * 64)
    with pytest.raises(dashboard_update.DashboardUpdateError) as exc:
        dashboard_update.verify_extracted_tree(dest, manifest, record)
    assert "runtime_id does not match the signed record" in exc.value.detail


def test_a_tampered_file_fails_the_manifest_check(bundle, tmp_path):
    dest = tmp_path / "staged"
    manifest = dashboard_update.extract_bundle(bundle["path"], dest)
    record = make_dashboard_record(bundle["bytes"], version=bundle["manifest"]["version"],
                                   runtime_id=bundle["manifest"]["runtime_id"])
    (dest / "src" / "ccsync_dashboard" / "settings.py").write_text("# replaced\n")
    with pytest.raises(dashboard_update.DashboardUpdateError) as exc:
        dashboard_update.verify_extracted_tree(dest, manifest, record)
    assert "does not match the bundle manifest" in exc.value.detail


# ------------------------------------------------------------- end to end


@pytest.fixture
def real_bundle_world(world, bundle, monkeypatch):
    """The world, with the image's runtime id set to the REAL bundle's, so an
    apply of it is a code update rather than a runtime one."""
    world["runtime_id_file"].write_text(bundle["manifest"]["runtime_id"], encoding="utf-8")
    record = make_dashboard_record(bundle["bytes"], version=NEW_VERSION,
                                   runtime_id=bundle["manifest"]["runtime_id"])
    check(world, [record], monkeypatch, extra={record["url"]: bundle["bytes"]})
    return {**world, "record": record, "bundle": bundle}


def test_apply_stages_verifies_backs_up_swaps_and_asks_to_restart(real_bundle_world):
    settings = real_bundle_world["settings"]
    result = dashboard_update.apply(settings, real_bundle_world["app"].state,
                                    version=NEW_VERSION, started_by="owen")
    code = dashboard_update.code_dir(settings)

    # The tree is in place, with the SIGNED record beside it: without that
    # file select_code_root.py refuses to boot the tree at all.
    assert (code / NEW_VERSION / "src" / "ccsync_dashboard" / "app.py").is_file()
    assert (code / NEW_VERSION / "templates" / "base.html").is_file()
    saved = json.loads((code / NEW_VERSION / "record.json").read_text())
    ok, _detail = release_trust.verify_record(saved, saved["signature"], (TEST_PUBKEY,))
    assert ok

    current = json.loads((code / "current.json").read_text())
    assert current["version"] == NEW_VERSION
    assert current["previous"] == ""
    assert current["applied_by"] == "owen"

    # The real stage-verify subprocess ran and both checks passed.
    names = {c["check"]: c["ok"] for c in result["checks"]}
    assert names["import ccsync_dashboard.app"] is True
    assert names["migrate dashboard.db (copy)"] is True

    # The live database was backed up with the sqlite backup API, not copied.
    backups = dashboard_update.list_backups(settings)
    assert backups and backups[0]["databases"] == ["dashboard"]
    backed_up = Path(dashboard_update.backups_dir(settings) / backups[0]["name"] / "dashboard.db")
    assert backed_up.is_file()

    # Nothing left behind, and a restart was asked for.
    assert not list(code.glob("*.staging"))
    assert not list(code.glob("*.part"))
    assert real_bundle_world["restarts"] == [1]
    assert dashboard_update.read_state(settings)["restart_requested"] is True


def test_the_applied_tree_is_what_select_code_root_then_boots(real_bundle_world, tmp_path):
    """The two halves meet: what apply() writes is exactly what the boot-time
    verifier accepts. This is the seam a mistake would hide in -- an apply
    that "worked" and a tree that silently never boots."""
    import os
    import shutil
    import subprocess

    settings = real_bundle_world["settings"]
    dashboard_update.apply(settings, real_bundle_world["app"].state,
                           version=NEW_VERSION, started_by="owen")

    image = tmp_path / "image"
    (image / "src").mkdir(parents=True)
    shutil.copytree(REPO / "dashboard" / "src" / "ccsync_dashboard",
                    image / "src" / "ccsync_dashboard",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (image / "src" / "ccsync_dashboard" / "__init__.py").write_text(
        f'VERSION = "{IMAGE_VERSION}"\n', encoding="utf-8")
    venv = tmp_path / "venv"
    venv.mkdir()
    (venv / ".runtime-id").write_text(real_bundle_world["bundle"]["manifest"]["runtime_id"])

    env = dict(os.environ)
    env.update({"CCSYNC_DATA_DIR": str(real_bundle_world["data"]),
                "CCSYNC_APP_ROOT": str(image), "CCSYNC_VENV_DIR": str(venv),
                "DASH_RELEASE_PUBKEYS": TEST_PUBKEY, "PYTHONPATH": ""})
    proc = subprocess.run(
        [sys.executable, str(REPO / "dashboard" / "deploy" / "select_code_root.py")],
        capture_output=True, text=True, env=env)
    root = dashboard_update.code_dir(settings) / NEW_VERSION
    assert proc.stdout.strip().split(os.pathsep)[0] == str(root / "src")


def test_a_failed_download_leaves_the_running_dashboard_alone(world, monkeypatch, bundle):
    """Every failure before the swap has to be a no-op: the live tree is
    untouched until current.json is rewritten, which is the second-to-last
    step."""
    world["runtime_id_file"].write_text(bundle["manifest"]["runtime_id"], encoding="utf-8")
    record = make_dashboard_record(b"not the bundle bytes",
                                   runtime_id=bundle["manifest"]["runtime_id"])
    check(world, [record], monkeypatch, extra={record["url"]: b"something else entirely"})
    with pytest.raises(dashboard_update.DashboardUpdateError) as exc:
        dashboard_update.apply(world["settings"], world["app"].state, version=NEW_VERSION)
    assert "sha256 does not match" in exc.value.detail
    code = dashboard_update.code_dir(world["settings"])
    assert not (code / "current.json").exists()
    assert not list(code.glob("*.part"))
    assert world["restarts"] == []


def test_a_bundle_that_fails_its_checks_is_never_swapped_in(world, monkeypatch, bundle):
    world["runtime_id_file"].write_text(bundle["manifest"]["runtime_id"], encoding="utf-8")
    record = make_dashboard_record(bundle["bytes"], runtime_id=bundle["manifest"]["runtime_id"])
    check(world, [record], monkeypatch, extra={record["url"]: bundle["bytes"]})

    def fail(*args, **kwargs):
        raise dashboard_update.DashboardUpdateError(400, "the staged code failed its checks")

    monkeypatch.setattr(dashboard_update, "stage_verify", fail)
    with pytest.raises(dashboard_update.DashboardUpdateError):
        dashboard_update.apply(world["settings"], world["app"].state, version=NEW_VERSION)
    code = dashboard_update.code_dir(world["settings"])
    assert not (code / "current.json").exists()
    assert not (code / NEW_VERSION).exists()
    assert not list(code.glob("*.staging"))


# ---------------------------------------------------------------- rollback


def test_rollback_swaps_back_and_asks_to_restart(real_bundle_world):
    settings = real_bundle_world["settings"]
    dashboard_update.apply(settings, real_bundle_world["app"].state, version=NEW_VERSION)
    finish_the_restart(real_bundle_world)
    result = dashboard_update.rollback(settings, started_by="owen")
    current = json.loads((dashboard_update.current_json_path(settings)).read_text())
    assert result["version"] == "image"
    assert current["version"] == ""                 # "" is the image
    assert current["rolled_back_from"] == NEW_VERSION
    assert real_bundle_world["restarts"] == [1, 1]
    # The tree stays on disk: rolling forward again must not need a download.
    assert (dashboard_update.code_dir(settings) / NEW_VERSION / "manifest.json").is_file()


def test_rollback_while_an_update_runs_is_refused(real_bundle_world):
    settings = real_bundle_world["settings"]
    dashboard_update.apply(settings, real_bundle_world["app"].state, version=NEW_VERSION)
    finish_the_restart(real_bundle_world)
    dashboard_update._set_state(settings, in_progress=True, step="downloading",
                                version="9.9.10")
    with pytest.raises(dashboard_update.DashboardUpdateError) as exc:
        dashboard_update.rollback(settings)
    assert exc.value.status_code == 409
    assert "in progress" in exc.value.detail


def test_rollback_with_nothing_applied_is_refused(world):
    with pytest.raises(dashboard_update.DashboardUpdateError) as exc:
        dashboard_update.rollback(world["settings"])
    assert "already running the image" in exc.value.detail


def test_rollback_to_a_version_that_was_never_applied_is_a_404(real_bundle_world):
    settings = real_bundle_world["settings"]
    dashboard_update.apply(settings, real_bundle_world["app"].state, version=NEW_VERSION)
    finish_the_restart(real_bundle_world)
    with pytest.raises(dashboard_update.DashboardUpdateError) as exc:
        dashboard_update.rollback(settings, to_version="8.8.8")
    assert exc.value.status_code == 404


def test_rollback_can_restore_a_named_database_backup(real_bundle_world):
    """Deliberately opt-in: rolling the CODE back is cheap and reversible,
    restoring a database throws away everything since it was taken."""
    settings = real_bundle_world["settings"]
    conn = dbmod.connect(settings.db_path)
    dbmod.migrate(conn)
    conn.execute("INSERT INTO projects(slug, label, path, first_seen, last_seen) "
                 "VALUES('before','Before','/p','t','t')")
    conn.commit()
    conn.close()

    dashboard_update.apply(settings, real_bundle_world["app"].state, version=NEW_VERSION)
    finish_the_restart(real_bundle_world)
    name = dashboard_update.list_backups(settings)[0]["name"]

    conn = dbmod.connect(settings.db_path)
    conn.execute("INSERT INTO projects(slug, label, path, first_seen, last_seen) "
                 "VALUES('after','After','/p','t','t')")
    conn.commit()
    conn.close()

    dashboard_update.rollback(settings, restore_db=name)
    conn = dbmod.connect(settings.db_path)
    names = {r[0] for r in conn.execute("SELECT slug FROM projects")}
    conn.close()
    assert names == {"before"}


def test_restoring_an_unknown_backup_is_refused(world):
    with pytest.raises(dashboard_update.DashboardUpdateError) as exc:
        dashboard_update.restore_backup(world["settings"], "nope")
    assert exc.value.status_code == 404


def test_a_backup_name_with_a_separator_is_refused(world):
    with pytest.raises(dashboard_update.DashboardUpdateError) as exc:
        dashboard_update.restore_backup(world["settings"], "../../etc")
    assert "refusing" in exc.value.detail


# ------------------------------------------------------------ boot watchdog


def test_the_restart_flag_is_consumed_once(world):
    settings = world["settings"]
    dashboard_update.request_restart(settings)
    assert dashboard_update.finish_restart(settings) is True
    assert world["exits"] == [dashboard_update.RESTART_EXIT_CODE]
    # ...and a later ordinary shutdown is NOT a restart, or every `docker
    # stop` would exit 75 and run.sh would loop the container straight back up.
    assert dashboard_update.finish_restart(settings) is False
    assert world["exits"] == [dashboard_update.RESTART_EXIT_CODE]


def test_clearing_the_boot_counter_is_what_marks_a_boot_healthy(world):
    settings = world["settings"]
    path = dashboard_update.boot_attempts_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": NEW_VERSION, "attempts": 1}))
    dashboard_update.clear_boot_attempts(settings)
    assert not path.exists()
    dashboard_update.clear_boot_attempts(settings)          # idempotent


def test_status_reports_the_watchdog_counter(world):
    settings = world["settings"]
    path = dashboard_update.boot_attempts_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": NEW_VERSION, "attempts": 2}))
    assert dashboard_update.status(settings, world["app"].state)["boot_attempts"] == 2


# ------------------------------------------------------------------- health


def test_health_says_which_code_is_live(world):
    from ccsync_dashboard import VERSION

    body = world["client"].get("/api/v1/health").json()
    assert body["version"] == VERSION            # unchanged: the fleet reads this
    assert body["ok"] is True
    assert body["code"]["running"] == VERSION
    assert body["code"]["image"] == IMAGE_VERSION
    assert body["code"]["runtime_id"] == RUNTIME_ID
    assert body["code"]["source"] == "checkout"  # this suite runs from a checkout


def test_an_unauthenticated_health_is_unchanged(world):
    """`ok` and `version` and nothing else -- the client roster (and now the
    code layout) stay behind the session."""
    client = world["client"]
    client.cookies.clear()
    body = client.get("/api/v1/health").json()
    assert set(body) == {"ok", "version"}


# --------------------------------------------------------------- the UI page


def test_the_packages_page_carries_the_dashboard_section(world, monkeypatch):
    check(world, [make_dashboard_record(b"x")], monkeypatch)
    html = world["client"].get("/partials/admin/dashboard-update").text
    assert "[ DASHBOARD ]" in html
    assert "UPDATE NOW" in html
    assert NEW_VERSION in html


def test_the_section_says_so_in_bind_mount_mode(world):
    world["runtime_id_file"].unlink()
    html = world["client"].get("/partials/admin/dashboard-update").text
    assert "updates from your wired computer" in html
    assert "UPDATE NOW" not in html


def test_a_runtime_update_shows_the_nas_click_not_a_button(world, monkeypatch):
    check(world, [make_dashboard_record(b"x", runtime_id="b" * 64)], monkeypatch)
    html = world["client"].get("/partials/admin/dashboard-update").text
    assert "RUNTIME UPDATE" in html
    assert "Apps &gt; ccsync &gt; Update" in html or "Apps > ccsync > Update" in html
    assert "UPDATE NOW" not in html


# ------------------------------------------------------------- odds and ends


def test_active_ytdl_jobs_reads_the_real_table(world, tmp_path, monkeypatch):
    import sqlite3

    root = tmp_path / "ytdl"
    root.mkdir()
    conn = sqlite3.connect(root / "ytdl.db")
    conn.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, phase TEXT)")
    conn.executemany("INSERT INTO jobs(phase) VALUES(?)",
                     [("done",), ("ready_for_review",), ("downloading",), ("searching",)])
    conn.commit()
    conn.close()
    monkeypatch.delitem(sys.modules, "ytdlweb.config", raising=False)
    monkeypatch.setenv("YTDL_DATA_ROOT", str(root))
    # done and ready_for_review are NOT the worker's work in flight.
    assert dashboard_update.active_ytdl_jobs() == 2


def test_a_missing_ytdl_database_never_blocks_an_update(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "ytdlweb.config", raising=False)
    monkeypatch.setenv("YTDL_DATA_ROOT", str(tmp_path / "nothing-here"))
    assert dashboard_update.active_ytdl_jobs() == 0


def test_a_snapshot_is_skipped_with_a_reason_not_a_crash(world):
    result = dashboard_update.snapshot_before(world["settings"], "test")
    assert result["ok"] is False
    assert "NAS API key" in result["reason"]


def test_an_older_bundle_than_the_running_code_is_a_rollback_candidate_not_an_update(world, monkeypatch):
    """Live 2026-08-18: running 0.6.3 (applied from the volume) over image
    0.6.1, the feed held 0.6.2 and 0.6.4, and code_updates listed BOTH --
    0.6.2 passed the newer-than-image test. An update list must only hold
    versions newer than what is running; the rest is rollback material and
    is offered as exactly that. Newest first in every list."""
    from ccsync_dashboard import dashboard_update as du

    monkeypatch.setattr(du, "VERSION", "0.6.3")
    older = make_dashboard_record(b"older", version="0.6.2")
    newer = make_dashboard_record(b"newer", version="0.6.4")
    newest = make_dashboard_record(b"newest", version="0.6.5")
    check(world, [older, newest, newer], monkeypatch)
    status = world["client"].get("/api/v1/admin/dashboard-update").json()
    assert [u["version"] for u in status["code_updates"]] == ["0.6.5", "0.6.4"]
    assert [u["version"] for u in status["rollback_candidates"]] == ["0.6.2"]


# ------------------------------------------- the orphaned in-progress latch
# dash-release-ai-2 (2026-08-21): the flag is written to disk on purpose, but
# the worker THREAD that owned it lives in one process. A container stop or an
# OOM kill mid-download left in_progress=true with nobody to clear it, and
# every later apply AND rollback answered 409 for ever -- on the appliance
# shape, with no shell to edit /data/code/update_state.json with.


def _orphan_the_flag(settings, step="downloading", version=NEW_VERSION):
    """Exactly what a killed container leaves behind: in_progress, no restart
    requested, and an owner pid that is not this process."""
    dashboard_update._write_json(dashboard_update.update_state_path(settings), {
        "step": step, "in_progress": True, "version": version,
        "message": "downloading the bundle", "error": "", "owner_pid": 999999,
    })


def test_an_interrupted_update_does_not_wedge_the_channel(world, monkeypatch):
    check(world, [make_dashboard_record(b"x")], monkeypatch)
    settings = world["settings"]
    _orphan_the_flag(settings)

    state = dashboard_update.read_state(settings)
    assert state["in_progress"] is False
    assert state["step"] == "failed"
    assert "interrupted by a restart at step downloading" in state["error"]
    # ...and it is written down, not just returned: the next reader sees it.
    on_disk = json.loads(
        dashboard_update.update_state_path(settings).read_text(encoding="utf-8"))
    assert on_disk["in_progress"] is False

    r = world["client"].post("/api/v1/admin/dashboard-update/apply",
                             json={"version": NEW_VERSION})
    assert r.status_code != 409


def test_a_state_file_with_no_owner_pid_is_treated_as_interrupted(world, monkeypatch):
    """The shape written by a build from before this fix."""
    settings = world["settings"]
    dashboard_update._write_json(dashboard_update.update_state_path(settings), {
        "step": "extracting", "in_progress": True, "version": NEW_VERSION,
    })
    assert dashboard_update.read_state(settings)["in_progress"] is False


def test_an_update_running_in_THIS_process_still_refuses_a_second_one(world, monkeypatch):
    """The latch has to keep working for the case it was written for."""
    check(world, [make_dashboard_record(b"x")], monkeypatch)
    settings = world["settings"]
    dashboard_update._set_state(settings, in_progress=True, step="downloading",
                                version=NEW_VERSION)
    assert dashboard_update.read_state(settings)["in_progress"] is True
    r = world["client"].post("/api/v1/admin/dashboard-update/apply",
                             json={"version": NEW_VERSION})
    assert r.status_code == 409


def test_a_restart_this_update_asked_for_survives_the_process(world):
    """The ONE in-progress state that legitimately outlives its process:
    request_restart wants the NEXT process to see it, and
    consume_restart_request is what clears it."""
    settings = world["settings"]
    dashboard_update.request_restart(settings)
    raw = json.loads(dashboard_update.update_state_path(settings).read_text(encoding="utf-8"))
    raw["owner_pid"] = 999999          # as if a new process were reading it
    dashboard_update._write_json(dashboard_update.update_state_path(settings), raw)

    state = dashboard_update.read_state(settings)
    assert state["in_progress"] is True
    assert state["restart_requested"] is True
    assert dashboard_update.consume_restart_request(settings) is True
    assert dashboard_update.read_state(settings)["in_progress"] is False


def test_rollback_is_possible_again_after_an_interrupted_apply(real_bundle_world):
    settings = real_bundle_world["settings"]
    dashboard_update.apply(settings, real_bundle_world["app"].state, version=NEW_VERSION)
    finish_the_restart(real_bundle_world)
    _orphan_the_flag(settings, version="9.9.10")
    result = dashboard_update.rollback(settings)
    assert result["rolled_back_from"] == NEW_VERSION


# ------------------------------------- the resilience sweep (2026-08-28)
#
# REL-6 (the boot watchdog has to prove it can SERVE), REL-9 (a pid is not a
# process), REL-10 (rolling the code back leaves the database migrated
# forward) and REL-5 (nothing on this path ever pruned).


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self, _n: int = 0) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    """Stands in for the opener the probe builds -- never urlopen (GOTCHAS
    section 12: a test that patches urlopen does not exercise the opener the
    code actually builds)."""

    def __init__(self, answers) -> None:
        self.answers = list(answers)
        self.urls: list[str] = []

    def open(self, url, timeout=None):
        self.urls.append(url)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return _FakeResponse(*answer)


def _patch_probe(monkeypatch, opener):
    monkeypatch.setattr(dashboard_update, "_loopback_opener", lambda: opener)
    return opener


def test_a_served_health_route_is_what_marks_a_boot_healthy(world, monkeypatch):
    from ccsync_dashboard import VERSION

    body = json.dumps({"ok": True, "version": VERSION}).encode()
    opener = _patch_probe(monkeypatch, _FakeOpener([(200, body)]))
    ok, why = dashboard_update.probe_health(world["settings"])
    assert ok and why == ""
    assert opener.urls[0].startswith("http://127.0.0.1:")
    assert opener.urls[0].endswith("/api/v1/health")


def test_a_wedged_dashboard_leaves_the_boot_counter_standing(world, monkeypatch):
    """The REL-6 hole: the tree imported, bound the port and then 500'd every
    request. The old watchdog called that healthy for ever."""
    settings = world["settings"]
    path = dashboard_update.boot_attempts_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": NEW_VERSION, "attempts": 1}))
    _patch_probe(monkeypatch, _FakeOpener([(500, b"nope")]))
    monkeypatch.setattr(dashboard_update, "BOOT_HEALTHY_SECONDS", 0.0)
    monkeypatch.setattr(dashboard_update, "BOOT_HEALTH_PROBE_SECONDS", 0.0)

    thread = dashboard_update.start_boot_watchdog(settings)
    assert thread is not None
    thread.join(timeout=10)
    assert path.exists(), "a boot that never served must not clear the counter"


def test_a_health_route_answering_as_another_version_is_not_this_boot(world, monkeypatch):
    body = json.dumps({"ok": True, "version": "0.0.1"}).encode()
    _patch_probe(monkeypatch, _FakeOpener([(200, body)]))
    ok, why = dashboard_update.probe_health(world["settings"])
    assert ok is False
    assert "0.0.1" in why


def test_a_healthy_boot_clears_the_counter(world, monkeypatch):
    from ccsync_dashboard import VERSION

    settings = world["settings"]
    path = dashboard_update.boot_attempts_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": NEW_VERSION, "attempts": 1}))
    body = json.dumps({"ok": False, "version": VERSION}).encode()   # ok:False is fine
    _patch_probe(monkeypatch, _FakeOpener([(200, body)]))
    monkeypatch.setattr(dashboard_update, "BOOT_HEALTHY_SECONDS", 0.0)

    thread = dashboard_update.start_boot_watchdog(settings)
    thread.join(timeout=10)
    assert not path.exists()


def test_the_same_pid_in_a_new_process_is_still_an_interrupted_update(world):
    """REL-9: run.sh is pid 1 and uvicorn is its child, so a container that
    came back after a power cut handed the new worker the same small pid --
    and the dead latch then survived every apply and every rollback."""
    settings = world["settings"]
    dashboard_update._write_json(dashboard_update.update_state_path(settings), {
        "step": "downloading", "in_progress": True, "version": NEW_VERSION,
        "owner_pid": os.getpid(), "owner_nonce": "some-other-process",
    })
    assert dashboard_update.read_state(settings)["in_progress"] is False


def test_this_process_still_owns_its_own_flag(world):
    settings = world["settings"]
    dashboard_update._set_state(settings, in_progress=True, step="downloading",
                                version=NEW_VERSION)
    raw = json.loads(dashboard_update.update_state_path(settings).read_text(encoding="utf-8"))
    assert raw["owner_nonce"] == dashboard_update.PROCESS_NONCE
    assert dashboard_update.read_state(settings)["in_progress"] is True


def test_an_apply_records_the_live_schema_and_the_trees_own(real_bundle_world):
    settings = real_bundle_world["settings"]
    dashboard_update.apply(settings, real_bundle_world["app"].state, version=NEW_VERSION)
    current = json.loads(
        (dashboard_update.code_dir(settings) / "current.json").read_text(encoding="utf-8"))
    assert current["db_user_versions"]["dashboard"] == dbmod.SCHEMA_VERSION
    assert current["schema_version"] == dbmod.SCHEMA_VERSION
    manifest = json.loads(
        (dashboard_update.version_dir(settings, NEW_VERSION) / "manifest.json")
        .read_text(encoding="utf-8"))
    assert manifest["schema_version"] == dbmod.SCHEMA_VERSION


def test_rolling_back_past_a_migration_is_refused_and_names_the_backup(real_bundle_world):
    """REL-10: the admin's safe-looking choice (no restore_db, keep today's
    reports) is the one that leaves old code against a newer schema."""
    settings = real_bundle_world["settings"]
    dashboard_update.apply(settings, real_bundle_world["app"].state, version=NEW_VERSION)
    finish_the_restart(real_bundle_world)
    # As if the tree we are going back to knew an older schema than the live DB.
    manifest_path = dashboard_update.version_dir(settings, NEW_VERSION) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 1
    dashboard_update._write_json(manifest_path, manifest)

    with pytest.raises(dashboard_update.DashboardUpdateError) as exc:
        dashboard_update.rollback(settings, to_version=NEW_VERSION)
    assert exc.value.status_code == 409
    assert "schema v1" in exc.value.detail
    backup = dashboard_update.list_backups(settings)[0]["name"]
    assert backup in exc.value.detail

    # ...and it is not a wall: acknowledging it goes through.
    result = dashboard_update.rollback(settings, to_version=NEW_VERSION,
                                       acknowledge_schema=True)
    assert result["version"] == NEW_VERSION


def test_rolling_back_to_the_image_is_never_blocked_by_an_unknown_schema(real_bundle_world):
    """The image is the escape hatch of last resort: unknown is SAID (status()
    carries it), never a refusal."""
    settings = real_bundle_world["settings"]
    dashboard_update.apply(settings, real_bundle_world["app"].state, version=NEW_VERSION)
    finish_the_restart(real_bundle_world)
    result = dashboard_update.rollback(settings)
    assert result["version"] == "image"
    assert result["schema"]["unknown"] is True


def test_backups_are_bounded_per_label(world, monkeypatch):
    settings = world["settings"]
    monkeypatch.setattr(dashboard_update, "BACKUPS_KEEP_PER_LABEL", 2)
    for stamp in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z"):
        made = dashboard_update.backups_dir(settings) / f"{stamp}-before-9.9.9"
        made.mkdir(parents=True)
        dashboard_update._write_json(made / "backup.json", {"created_at": stamp})
    dashboard_update.prune_backups(settings)
    left = {b["name"] for b in dashboard_update.list_backups(settings)}
    assert left == {"20260103T000000Z-before-9.9.9", "20260102T000000Z-before-9.9.9"}


def test_old_code_trees_are_pruned_to_running_previous_and_one(world):
    settings = world["settings"]
    code = dashboard_update.code_dir(settings)
    for version in ("1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4"):
        (code / version).mkdir(parents=True)
        dashboard_update._write_json(code / version / "manifest.json", {"version": version})
    dashboard_update._write_json(dashboard_update.current_json_path(settings),
                                 {"version": "1.0.4", "previous": "1.0.1"})
    removed = dashboard_update.prune_code_trees(settings)
    left = {p.name for p in code.iterdir() if p.is_dir()}
    assert "1.0.4" in left and "1.0.1" in left
    assert len(left) == dashboard_update.CODE_TREES_KEEP
    assert removed


def test_health_carries_the_feed_age_and_the_data_gauge(world):
    body = world["client"].get("/api/v1/health").json()
    assert body["feed"]["configured"] is True
    # Never checked reads as stale, not as fine.
    assert body["feed"]["stale"] is True
    assert body["data"]["free_bytes"] > 0


def test_the_packages_page_shows_the_data_gauge(world):
    html = world["client"].get("/admin/packages").text
    assert "data volume:" in html or "FREE on the data volume" in html


def test_reload_panel_never_swaps_an_unchecked_response(world):
    """bug-hunt-2026-09-03 dash-mounts-ui-3, the DASH-4 shape in the one panel
    that deliberately does not use htmx: `reloadPanel` sends HX-Request, so
    login_gate answers an expired session with a 200 carrying HX-Redirect
    (never a 303). Plain fetch does not understand that header, so an
    unchecked `outerHTML =` wrote the LOGIN DOCUMENT into the packages panel.
    Asserted on the source, because the failure is somebody deleting the
    guard: the browser half has no harness here."""
    src = (REPO / "dashboard" / "static" / "dashboard_update.js").read_text(encoding="utf-8")
    body = src.split("function reloadPanel()", 1)[1].split("\n  }", 1)[0]
    assert "resp.ok" in body, "reloadPanel no longer checks the status"
    assert "HX-Redirect" in body, "reloadPanel no longer checks for HX-Redirect"
    guard = min(body.index("resp.ok"), body.index("HX-Redirect"))
    assert guard < body.index("outerHTML"), "the guard must precede the swap"


def test_the_login_gate_answers_an_hx_request_with_hx_redirect(world):
    """The premise of the test above: an expired session answers this fetch
    with a status only htmx knows what to do with."""
    client = world["client"]
    client.cookies.clear()
    res = client.get("/partials/admin/dashboard-update",
                     headers={"HX-Request": "true"}, follow_redirects=False)
    assert res.status_code == 401
    assert res.headers.get("HX-Redirect")
