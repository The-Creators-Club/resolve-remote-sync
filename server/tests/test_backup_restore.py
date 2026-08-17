"""The backup floor: snapshots, snapshot-before-privileged-ops, and the DB publish.

docs/COMMERCIAL_READINESS.md item 8. Three groups, in the order they would cost
you if they broke:

  1. **The publish never overwrites a live database in place.** broll.db and
     music.db are WAL-mode SQLite files the dashboard container holds OPEN
     READ-WRITE; the only safe replacement is a rename, and a rename is only
     safe if the candidate passed `PRAGMA quick_check` first. The shell-level
     tests here run the GENERATED remote script under a stub sudo (the harness
     test_safety.py uses) with stub `docker`/`python3`, so the actual
     semantics are exercised -- swap, refusal, rollback -- without a NAS.
  2. **Nothing privileged and recursive runs without a point-in-time behind
     it**, and the failure to take one is a warning rather than a wall unless
     the operator asked for a wall (`--require-snapshot`).
  3. **The schedule is idempotent.** A runbook that says "run this" is only
     honest if a second run says "unchanged" instead of stacking a duplicate
     hourly task on a customer's pool.

Everything is offline. Run with:
    cd E:\\Projects\\resolve-remote-sync\\server
    python -m pytest tests -q          # from GIT BASH -- see CLAUDE.md
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
import install_dashboard_app as ida  # noqa: E402
import publish_db  # noqa: E402
import setup_snapshots  # noqa: E402
from backends.base import UnsupportedOnBackend  # noqa: E402
from backends.synology import SynologyBackend  # noqa: E402
from backends.truenas import TrueNASBackend  # noqa: E402
from tests.fake_dsm import FakeDsmApi, FakeSsh  # noqa: E402
from test_safety import _Resp, needs_bash, run_remote_script  # noqa: E402

TREE = "/mnt/tank/TheCreatorsPool"
APPS = "/mnt/tank/apps/ccsync-dashboard"


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------

class FakeApi:
    """Callable with common.truenas_api's signature, recording every call."""

    def __init__(self, get=None, fail=()):
        self.calls = []                 # [(method, path, body)]
        self.get = list(get or [])      # what GET /pool/snapshottask answers
        self.fail = set(fail)           # methods that answer 500

    def __call__(self, method, path, json_body=None, dry_run=False, params=None):
        self.calls.append((method, path, json_body))
        if method in self.fail:
            return _Resp(500, text="boom")
        if method == "GET" and path == "/pool/snapshottask":
            return _Resp(200, payload=self.get)
        return _Resp(200, payload=1)

    def bodies(self, method):
        return [b for m, _p, b in self.calls if m == method]


def truenas(ssh=None, api=None):
    """A TrueNASBackend wired to fakes through ScriptCalls, as a script does."""
    module = type(sys)("fake_script")
    module.run_ssh = ssh or FakeSsh()
    module.truenas_api = api or FakeApi()
    return TrueNASBackend(calls=common.ScriptCalls(module))


def synology(ssh=None, dsm=None):
    module = type(sys)("fake_script")
    module.run_ssh = ssh or FakeSsh()
    module.synology_api = dsm or FakeDsmApi()
    return SynologyBackend(calls=common.ScriptCalls(module))


# --------------------------------------------------------------------------
# 1. Taking one snapshot
# --------------------------------------------------------------------------

def test_truenas_takes_a_zfs_snapshot_of_the_dataset_the_path_is_in():
    ssh = FakeSsh(answers=[("df --output=source", (0, "Filesystem\ntank/apps\n", ""))])
    ok, ident = truenas(ssh).snapshot_now(f"{APPS}", "ccsync-20260817-1400", False)
    assert ok and ident == "tank/apps@ccsync-20260817-1400"
    assert "zfs snapshot 'tank/apps@ccsync-20260817-1400'" in ssh.text


def test_truenas_falls_back_to_the_path_when_df_cannot_answer():
    """df is how a DIRECTORY inside a dataset is resolved to its dataset. When
    it cannot answer, the string form is still a legitimate guess -- and `zfs
    snapshot` says so plainly if it is wrong, which is better than not trying."""
    ssh = FakeSsh(answers=[("df --output=source", (1, "", "no such file"))])
    ok, ident = truenas(ssh).snapshot_now(TREE, "ccsync-x", False)
    assert ok and ident == "tank/TheCreatorsPool@ccsync-x"


def test_truenas_refuses_a_path_that_is_not_under_mnt():
    ok, ident = truenas().snapshot_now("/var/tmp", "ccsync-x", False)
    assert not ok and ident == ""


def test_an_already_taken_snapshot_name_is_success_not_failure():
    """Two deploys inside the same clock second is an ordinary thing to do, and
    `zfs snapshot` errors on an existing name. The point-in-time the operator
    asked for exists either way."""
    ssh = FakeSsh(answers=[("zfs snapshot", (1, "", "cannot create snapshot: dataset already exists"))])
    ok, _ident = truenas(ssh).snapshot_now(TREE, "ccsync-x", False)
    assert ok


def test_a_real_zfs_failure_is_a_failure():
    ssh = FakeSsh(answers=[("zfs snapshot", (1, "", "cannot open 'tank/nope': no such pool"))])
    ok, _ident = truenas(ssh).snapshot_now(TREE, "ccsync-x", False)
    assert not ok


def test_dry_run_takes_no_snapshot_and_opens_no_socket(capsys):
    ssh = FakeSsh()
    ok, _ = truenas(ssh).snapshot_now(TREE, "ccsync-x", True)
    assert ok
    assert "[dry-run] would take a ZFS snapshot" in capsys.readouterr().out


def test_synology_snapshots_the_share_the_path_lives_in():
    dsm = FakeDsmApi()
    ok, ident = synology(dsm=dsm).snapshot_now(
        "/volume1/CCSyncTest/Creators_Club/Projects", "pre-deploy", False)
    assert ok and ident.startswith("CCSyncTest@")
    assert dsm.snapshots["CCSyncTest"]


# --------------------------------------------------------------------------
# 2. The schedule
# --------------------------------------------------------------------------

def policy():
    return setup_snapshots.schedules(24, 30)


def test_the_schedule_is_created_when_the_dataset_has_none():
    api = FakeApi(get=[])
    states = truenas(api=api).ensure_snapshot_schedule(TREE, policy(), False)
    assert [s for s, _ in states] == ["created", "created"]
    posted = api.bodies("POST")
    assert {b["naming_schema"] for b in posted} == {
        setup_snapshots.HOURLY_SCHEMA, setup_snapshots.DAILY_SCHEMA}
    hourly = next(b for b in posted if b["lifetime_unit"] == "HOUR")
    assert hourly["dataset"] == "tank/TheCreatorsPool"
    assert hourly["lifetime_value"] == 24
    assert hourly["recursive"] is True
    assert hourly["schedule"] == {"minute": "0", "hour": "*", "dom": "*",
                                  "month": "*", "dow": "*"}


def test_a_second_run_changes_nothing():
    """The idempotency the runbook promises. A duplicate hourly task on a
    customer's pool is not a cosmetic problem: two tasks writing the same
    naming schema collide on every snapshot name."""
    api = FakeApi(get=[])
    backend = truenas(api=api)
    backend.ensure_snapshot_schedule(TREE, policy(), False)
    api.get = [dict(b, id=i) for i, b in enumerate(api.bodies("POST"), start=1)]
    api.calls.clear()
    states = truenas(api=api).ensure_snapshot_schedule(TREE, policy(), False)
    assert [s for s, _ in states] == ["unchanged", "unchanged"]
    assert not api.bodies("POST") and not api.bodies("PUT")


def test_extra_fields_the_middleware_adds_are_not_read_as_drift():
    """GET returns the schedule with begin/end fields the create payload never
    sets; treating those as drift would make every re-run a PUT."""
    task = dict(policy()[0], id=7, dataset="tank/TheCreatorsPool", enabled=True,
                allow_empty=True)
    task["schedule"] = dict(task["schedule"], begin="00:00", end="23:59")
    task.pop("label")
    api = FakeApi(get=[task])
    states = truenas(api=api).ensure_snapshot_schedule(TREE, policy()[:1], False)
    assert states == [("unchanged", "hourly")]


def test_a_retention_change_is_an_update_not_a_second_task():
    task = dict(policy()[0], id=7, dataset="tank/TheCreatorsPool")
    task["lifetime_value"] = 6
    task.pop("label")
    api = FakeApi(get=[task])
    states = truenas(api=api).ensure_snapshot_schedule(TREE, policy()[:1], False)
    assert states == [("updated", "hourly")]
    assert api.bodies("PUT")[0]["lifetime_value"] == 24
    assert not api.bodies("POST")


def test_scheduling_a_bare_pool_is_refused():
    """`zfs snapshot -r tank@...` hourly is somebody's whole NAS, not this
    tree."""
    states = truenas().ensure_snapshot_schedule("/mnt/tank", policy(), False)
    assert states[0][0] == "failed" and "pool, not a dataset" in states[0][1]


def test_synology_says_exactly_what_to_click_when_it_cannot_schedule():
    """DSM can TAKE a share snapshot from base DSM but SCHEDULING one belongs
    to the Snapshot Replication package (403 without it). "printed some advice"
    must never be mistakable for "backups are configured"."""
    states = synology().ensure_snapshot_schedule(
        "/volume1/CCSyncTest/Creators_Club", policy(), False)
    assert [s for s, _ in states] == ["manual", "manual"]
    assert "Snapshot Replication" in states[0][1]
    assert "keep 24 hourly" in states[0][1]


def test_setup_snapshots_exits_non_zero_when_a_step_is_still_manual(monkeypatch,
                                                                   capsys):
    class ManualBackend:
        kind = "synology"

        def list_snapshots(self, path, dry_run):
            return []

        def ensure_snapshot_schedule(self, path, schedules, dry_run):
            return [("manual", "do it in DSM")]

        def snapshot_now(self, path, name, dry_run):
            return True, "x"

    monkeypatch.setattr(setup_snapshots, "get_backend", lambda args: ManualBackend())
    monkeypatch.setattr(setup_snapshots, "set_host_key_pin", lambda v: None)
    monkeypatch.setattr(sys, "argv", ["setup_snapshots.py", "--apply"])
    assert setup_snapshots.main() == 1
    assert "MANUAL STEP REQUIRED" in capsys.readouterr().err


# --------------------------------------------------------------------------
# 3. snapshot_before -- the rule, and its escape hatch
# --------------------------------------------------------------------------

class RefusingBackend:
    kind = "truenas"

    def snapshot(self, path, label, dry_run):
        raise UnsupportedOnBackend("no snapshots here")


class FailingBackend:
    kind = "truenas"

    def snapshot(self, path, label, dry_run):
        return False


class WorkingBackend:
    kind = "truenas"

    def __init__(self):
        self.taken = []

    def snapshot(self, path, label, dry_run):
        self.taken.append((path, label, dry_run))
        return True


def test_snapshot_before_is_best_effort_by_default(capsys):
    """A NAS whose snapshot API is unreachable must not be a NAS where projects
    cannot be created."""
    assert common.snapshot_before("setup_tree", TREE,
                                  backend=RefusingBackend()) is False
    err = capsys.readouterr().err
    assert "WARNING" in err and "nothing behind it" in err


def test_require_snapshot_turns_the_warning_into_a_refusal():
    with pytest.raises(common.EnvError) as exc:
        common.snapshot_before("deploy", APPS, require=True, backend=FailingBackend())
    assert "without a snapshot" in str(exc.value)


def test_the_env_var_is_the_same_switch_for_a_script_with_no_flag(monkeypatch):
    monkeypatch.setenv(common.REQUIRE_SNAPSHOT_ENV, "1")
    with pytest.raises(common.EnvError):
        common.snapshot_before("deploy", APPS, backend=FailingBackend())


def test_a_taken_snapshot_is_reported_and_passes_the_label_through():
    backend = WorkingBackend()
    assert common.snapshot_before("recreate", APPS, backend=backend) is True
    assert backend.taken == [(APPS, "recreate", False)]


def test_setup_tree_snapshots_before_it_chowns(monkeypatch):
    """setup_tree's remote script ends in `chown -R` + a recursive chmod, as
    root, on a path assembled from free text. The snapshot must precede the
    ssh, not follow it."""
    import setup_tree  # noqa: PLC0415

    order = []
    monkeypatch.setattr(setup_tree, "snapshot_before",
                        lambda *a, **k: order.append("snapshot") or True)
    monkeypatch.setattr(setup_tree, "run_ssh",
                        lambda *a, **k: (order.append("ssh"), (0, "", ""))[1])
    monkeypatch.setattr(setup_tree, "set_host_key_pin", lambda v: None)
    monkeypatch.setattr(sys, "argv",
                        ["setup_tree.py", "--project-rel-path", "2026/CCT/S1"])
    setup_tree.main()
    assert order == ["snapshot", "ssh"]


# --------------------------------------------------------------------------
# 4. The DB publish -- the shell that actually runs on the NAS
# --------------------------------------------------------------------------

DOCKER_OK = """#!/bin/sh
# `docker exec <container> python3 -c <prog>`: run the program here instead.
shift 2 2>/dev/null
exec python3 "$@"
"""

DOCKER_ABSENT = """#!/bin/sh
echo "docker: command not found" >&2
exit 127
"""

# The NAS has a python3; this machine's Git Bash may not, and the interpreter
# is not what these tests are about. Point it at the one running pytest.
PYTHON3_STUB = f"""#!/bin/sh
exec "{Path(sys.executable).as_posix()}" "$@"
"""


def make_db(path: Path, rows: int = 3) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE videos (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO videos (name) VALUES (?)",
                     [(f"clip{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


def stub(workdir: Path, name: str, body: str) -> None:
    bindir = workdir / "stubbin"
    bindir.mkdir(exist_ok=True)
    path = bindir / name
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def publish_script(workdir: Path, data_root: Path, staging: Path,
                   verify: str = "") -> str:
    target = str(data_root / "broll.db")
    return ida.build_db_swap_script(
        str(data_root), str(staging), target, target + ".prev-20260817T120000",
        (staging / "broll.db").stat().st_size,
        filename="broll.db", owner="", mode="", extra_verify=verify)


@needs_bash
def test_the_publish_installs_the_new_index_and_keeps_the_previous_one(tmp_path):
    data_root = tmp_path / "archive"
    staging = tmp_path / "staging"
    data_root.mkdir()
    staging.mkdir()
    make_db(data_root / "broll.db", rows=2)
    (data_root / "broll.db-wal").write_text("stale wal", encoding="utf-8")
    make_db(staging / "broll.db", rows=9)

    proc = run_remote_script(publish_script(tmp_path, data_root, staging), tmp_path)
    assert proc.returncode == 0, proc.stderr

    prev = data_root / "broll.db.prev-20260817T120000"
    assert prev.is_file()
    # THE WAL point (SERVER-7): the live file's -wal belongs to the file it sat
    # beside, and leaving it next to a replaced database is how a working index
    # becomes a corrupt one. Asserted before anything OPENS the new database --
    # SQLite deletes a -wal when the last connection to its .db closes.
    assert not (data_root / "broll.db-wal").exists()
    assert (data_root / "broll.db.prev-20260817T120000-wal").is_file()
    conn = sqlite3.connect(str(data_root / "broll.db"))
    assert conn.execute("SELECT count(*) FROM videos").fetchone()[0] == 9
    conn.close()


@needs_bash
def test_a_candidate_that_fails_quick_check_never_becomes_live(tmp_path):
    data_root = tmp_path / "archive"
    staging = tmp_path / "staging"
    data_root.mkdir()
    staging.mkdir()
    make_db(data_root / "broll.db", rows=2)
    # A file of the right SIZE that is not a database -- exactly what a copy
    # over a live WAL-mode file produces, and exactly what the byte check on
    # its own waves through.
    good = staging / "broll.db"
    make_db(good, rows=9)
    good.write_bytes(b"\x00" * good.stat().st_size)

    stub(tmp_path, "docker", DOCKER_OK)
    stub(tmp_path, "python3", PYTHON3_STUB)
    new = (data_root / "broll.db.new").as_posix()
    verify = publish_db.quick_check_snippet(
        "ix-ccsync-dashboard-dashboard-1", new, new, "broll.db")
    proc = run_remote_script(publish_script(tmp_path, data_root, staging, verify),
                             tmp_path)

    assert proc.returncode == publish_db.RC_INTEGRITY, proc.stdout + proc.stderr
    assert "quick_check" in proc.stderr and "UNTOUCHED" in proc.stderr
    conn = sqlite3.connect(str(data_root / "broll.db"))
    assert conn.execute("SELECT count(*) FROM videos").fetchone()[0] == 2
    conn.close()
    assert not (data_root / "broll.db.prev-20260817T120000").exists()


@needs_bash
def test_a_good_candidate_passes_the_on_nas_quick_check_and_swaps(tmp_path):
    data_root = tmp_path / "archive"
    staging = tmp_path / "staging"
    data_root.mkdir()
    staging.mkdir()
    make_db(data_root / "broll.db", rows=2)
    make_db(staging / "broll.db", rows=9)

    stub(tmp_path, "docker", DOCKER_OK)
    stub(tmp_path, "python3", PYTHON3_STUB)
    new = (data_root / "broll.db.new").as_posix()
    verify = publish_db.quick_check_snippet("c", new, new, "broll.db")
    proc = run_remote_script(publish_script(tmp_path, data_root, staging, verify),
                             tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "quick_check ok" in proc.stdout
    conn = sqlite3.connect(str(data_root / "broll.db"))
    assert conn.execute("SELECT count(*) FROM videos").fetchone()[0] == 9
    conn.close()


@needs_bash
def test_no_docker_and_no_host_python_is_a_refusal_not_a_silent_publish(tmp_path):
    """Fail closed. A publish that could not be verified must not become the
    live index -- that is the whole of item 8."""
    data_root = tmp_path / "archive"
    staging = tmp_path / "staging"
    data_root.mkdir()
    staging.mkdir()
    make_db(data_root / "broll.db", rows=2)
    make_db(staging / "broll.db", rows=9)

    stub(tmp_path, "docker", DOCKER_ABSENT)
    stub(tmp_path, "python3", "#!/bin/sh\nexit 127\n")
    verify = publish_db.quick_check_snippet(
        "c", str(data_root / "broll.db.new"), str(data_root / "broll.db.new"),
        "broll.db")
    proc = run_remote_script(publish_script(tmp_path, data_root, staging, verify),
                             tmp_path)

    assert proc.returncode == publish_db.RC_INTEGRITY
    conn = sqlite3.connect(str(data_root / "broll.db"))
    assert conn.execute("SELECT count(*) FROM videos").fetchone()[0] == 2
    conn.close()


@needs_bash
def test_rollback_puts_the_previous_index_back_with_its_wal(tmp_path):
    data_root = tmp_path / "archive"
    data_root.mkdir()
    target = data_root / "broll.db"
    prev = data_root / "broll.db.prev-20260817T120000"
    make_db(target, rows=9)
    make_db(prev, rows=2)
    (prev.parent / (prev.name + "-wal")).write_text("prev wal", encoding="utf-8")

    script = publish_db.build_rollback_script(
        str(target), str(prev), str(data_root / "broll.db.rolledback-1"))
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == 0, proc.stderr
    # Checked BEFORE anything opens the database: SQLite deletes a -wal when
    # the last connection to its .db closes, so a test that reads the rows
    # first proves nothing about the sidecar (learned here, 2026-08-17).
    assert (data_root / "broll.db-wal").is_file()
    assert (data_root / "broll.db.rolledback-1").is_file()
    conn = sqlite3.connect(str(target))
    assert conn.execute("SELECT count(*) FROM videos").fetchone()[0] == 2
    conn.close()


@needs_bash
def test_rollback_with_nothing_to_roll_back_to_changes_nothing(tmp_path):
    data_root = tmp_path / "archive"
    data_root.mkdir()
    target = data_root / "broll.db"
    make_db(target, rows=9)
    script = publish_db.build_rollback_script(
        str(target), str(data_root / "nope"), str(data_root / "aside"))
    proc = run_remote_script(script, tmp_path)
    assert proc.returncode == 6
    assert target.is_file() and not (data_root / "aside").exists()


# --------------------------------------------------------------------------
# 5. The refusals that live in python
# --------------------------------------------------------------------------

def test_a_surprise_shrink_is_refused():
    live = {"videos": 5000, "segments": 20000, "embeddings": 5000}
    new = {"videos": 4000, "segments": 20001, "embeddings": 5000}
    refusals = publish_db.shrink_refusals(live, new, publish_db.DEFAULT_SHRINK_PCT)
    assert len(refusals) == 1 and "videos" in refusals[0]


def test_growth_and_small_wobble_are_not_refusals():
    live = {"videos": 5000}
    assert publish_db.shrink_refusals(live, {"videos": 9000}, 10.0) == []
    assert publish_db.shrink_refusals(live, {"videos": 4800}, 10.0) == []


def test_a_table_the_new_index_does_not_have_is_not_a_shrink():
    """A schema difference is a schema difference; only a table present in both
    can shrink."""
    assert publish_db.shrink_refusals({"videos": 10}, {"videos": None}, 10.0) == []
    assert publish_db.shrink_refusals({"videos": 0}, {"videos": 0}, 10.0) == []


def test_the_dsm_publish_never_chowns_or_chmods_inside_the_tree_share():
    """Spike 1, restated for the publish path: a chmod DESTROYS a Synology
    path's ACL, and broll.db lives inside the tree share on DSM. Owner and ACL
    are carried across with synoacltool -copy instead."""
    target = "/volume1/CCSyncTest/Creators_Club/Assets/B-roll Archive/broll.db"
    owner, mode, acl = publish_db.install_identity("broll", synology(), target)
    assert owner == "" and mode == ""
    assert "synoacltool -copy" in acl
    script = ida.build_db_swap_script(
        "/volume1/CCSyncTest/x", "/tmp/s", target, target + ".prev-1", 10,
        filename="broll.db", owner=owner, mode=mode, extra_verify=acl)
    assert "chown" not in script and "chmod" not in script


def test_music_keeps_the_deploys_container_ownership():
    """music.db is under the app root, not the tree share, and the container
    must be able to write queued ingest rows into it."""
    owner, mode, acl = publish_db.install_identity(
        "music", truenas(), "/mnt/tank/apps/ccsync-dashboard/music-data/music.db")
    assert (owner, mode, acl) == ("3000:3000", "660", "")


def test_the_swap_script_refuses_an_owner_that_is_not_an_owner():
    with pytest.raises(common.EnvError):
        ida.build_db_swap_script("/r", "/tmp/s", "/r/x.db", "/r/x.db.prev", 1,
                                 owner="root; rm -rf /")


def test_an_apostrophe_in_the_path_is_refused_rather_than_mangled():
    """The path is interpolated into a python string literal inside a
    shell-quoted argument; the python layer has no escaping."""
    with pytest.raises(common.EnvError):
        publish_db.quick_check_snippet("c", "/broll-data/o'brien.db",
                                       "/mnt/o'brien.db", "broll.db")


def test_the_local_half_checkpoints_and_snapshots_consistently(tmp_path):
    src = tmp_path / "broll.db"
    make_db(src, rows=4)
    conn = sqlite3.connect(str(src))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("INSERT INTO videos (name) VALUES ('late')")
    conn.commit()
    conn.close()
    assert "checkpointed" in publish_db.checkpoint_source(src)

    dest = tmp_path / "snap.db"
    publish_db.local_snapshot(src, dest)
    state, counts = publish_db.local_verify(dest, ("videos", "nosuchtable"))
    assert state == "ok"
    assert counts["videos"] == 5          # the WAL commit came with it
    assert counts["nosuchtable"] is None


def test_publish_db_knows_where_each_database_lives():
    """Both paths come from site.toml, so this works on a site that is not
    this one -- and they are deliberately different worlds: the archive is in
    the tree (editors browse it over SMB), the music index is in the app's own
    data root."""
    assert publish_db.remote_dir_for("broll", truenas()).endswith(
        "/Creators_Club/Assets/B-roll Archive")
    assert publish_db.remote_dir_for("music", truenas()).endswith(
        "/apps/ccsync-dashboard/music-data")


def test_every_spec_names_its_content_tables():
    """The shrink check is only a check if it has a subject. music's
    ingest_queue is deliberately NOT in the list: those rows exist only on the
    NAS, so counting them would make every publish look catastrophic."""
    for which, spec in publish_db.SPECS.items():
        assert spec["tables"], which
        assert "ingest_queue" not in spec["tables"]
