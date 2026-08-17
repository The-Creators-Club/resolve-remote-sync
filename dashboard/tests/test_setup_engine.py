"""setup_engine.py -- the SetupEngine task registry (ZERO_TOUCH_PLAN.md WP D,
2026-08-17)."""
from __future__ import annotations

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import setup_engine, site_store
from ccsync_dashboard.settings import Settings

from fake_syncthing import FakeSyncthing


@pytest.fixture
def conn(tmp_path):
    connection = dbmod.connect(tmp_path / "s.db")
    dbmod.migrate(connection)
    yield connection
    connection.close()


class _FakeApp:
    class State:
        pass

    def __init__(self):
        self.state = _FakeApp.State()


def ctx(conn, settings, app=None):
    return setup_engine.SetupContext(conn=conn, settings=settings, app=app or _FakeApp())


# --------------------------------------------------------------- registry

def test_every_task_id_is_unique():
    ids = [t.id for t in setup_engine.TASKS]
    assert len(ids) == len(set(ids))


def test_placeholders_are_optional_and_report_not_implemented(conn):
    settings = Settings()
    for task_id in ("tailnet", "nas_connect", "snapshots", "editors", "software"):
        task = setup_engine.get(task_id)
        assert task is not None and task.optional
        state = task.check(ctx(conn, settings))
        assert state.status == "todo"
        assert "not implemented" in state.detail


def test_required_tasks_are_not_optional():
    for task_id in ("eula", "admin", "studio", "storage", "secrets", "syncthing", "done"):
        assert setup_engine.get(task_id).optional is False


def test_double_registering_the_same_id_is_refused():
    with pytest.raises(ValueError):
        setup_engine.register(setup_engine.Task(
            id="eula", title="dup", description="", check=lambda c: setup_engine.TaskState("ok")
        ))


def test_replace_swaps_in_place_keeping_order():
    before = [t.id for t in setup_engine.TASKS]
    idx = before.index("tailnet")
    setup_engine.replace(setup_engine.Task(
        id="tailnet", title="real", description="",
        check=lambda c: setup_engine.TaskState("ok"), optional=True,
    ))
    after = [t.id for t in setup_engine.TASKS]
    assert after == before
    assert setup_engine.TASKS[idx].title == "real"
    # restore, so other tests in this process see the placeholder again
    setup_engine.replace(setup_engine.Task(
        id="tailnet", title="Connect to your tailnet",
        description="Sign this node into your Tailscale network.",
        check=lambda c: setup_engine.TaskState("todo", detail="not implemented in this build"),
        optional=True,
    ))


# ----------------------------------------------------------- run_check/run_do_it/skip

def test_run_check_persists_state(conn):
    settings = Settings()
    state = setup_engine.run_check(ctx(conn, settings), "studio")
    assert state.status == "todo"
    loaded = setup_engine.load_state(conn, "studio")
    assert loaded.status == "todo"
    assert loaded.at is not None


def test_run_check_unknown_task_raises_keyerror(conn):
    with pytest.raises(KeyError):
        setup_engine.run_check(ctx(conn, Settings()), "not-a-real-task")


def test_run_do_it_without_a_run_action_raises(conn):
    with pytest.raises(NotImplementedError):
        setup_engine.run_do_it(ctx(conn, Settings()), "admin")


def test_run_skip_refuses_a_required_task(conn):
    with pytest.raises(ValueError):
        setup_engine.run_skip(ctx(conn, Settings()), "studio")


def test_run_skip_marks_an_optional_task_skipped(conn):
    state = setup_engine.run_skip(ctx(conn, Settings()), "tailnet")
    assert state.status == "skipped"
    assert setup_engine.load_state(conn, "tailnet").status == "skipped"


def test_a_task_that_raises_is_reported_as_fail_not_a_500(conn):
    task = setup_engine.Task(
        id="_boom", title="boom", description="",
        check=lambda c: (_ for _ in ()).throw(RuntimeError("kaboom")),
    )
    setup_engine.register(task)
    try:
        state = setup_engine.run_check(ctx(conn, Settings()), "_boom")
        assert state.status == "fail"
        assert "kaboom" in state.detail
    finally:
        setup_engine.TASKS.remove(task)
        del setup_engine._BY_ID["_boom"]


def test_outstanding_required_excludes_optional_and_ok(conn):
    settings = Settings()
    outstanding = setup_engine.outstanding_required(conn)
    assert "tailnet" not in outstanding    # optional
    assert "eula" in outstanding           # required, todo


# --------------------------------------------------------------------- eula

def test_eula_check_ok_when_no_eula_shipped(conn, monkeypatch, tmp_path):
    monkeypatch.setattr(setup_engine, "EULA_PATH", tmp_path / "missing.md")
    state = setup_engine.run_check(ctx(conn, Settings()), "eula")
    assert state.status == "ok"


def test_eula_accept_records_the_marker_version(conn, monkeypatch, tmp_path):
    eula = tmp_path / "EULA.md"
    eula.write_text("Terms...\n<!-- EULA-VERSION: 2.0 -->\n", encoding="utf-8")
    monkeypatch.setattr(setup_engine, "EULA_PATH", eula)

    before = setup_engine.run_check(ctx(conn, Settings()), "eula")
    assert before.status == "todo"
    assert "2.0" in before.detail

    accepted = setup_engine.run_do_it(ctx(conn, Settings()), "eula")
    assert accepted.status == "ok"
    assert accepted.detail == "accepted v2.0"

    after = setup_engine.run_check(ctx(conn, Settings()), "eula")
    assert after.status == "ok"


def test_eula_re_prompts_after_a_version_bump(conn, monkeypatch, tmp_path):
    eula = tmp_path / "EULA.md"
    eula.write_text("v1\n<!-- EULA-VERSION: 1.0 -->\n", encoding="utf-8")
    monkeypatch.setattr(setup_engine, "EULA_PATH", eula)
    setup_engine.run_do_it(ctx(conn, Settings()), "eula")

    eula.write_text("v2\n<!-- EULA-VERSION: 2.0 -->\n", encoding="utf-8")
    state = setup_engine.run_check(ctx(conn, Settings()), "eula")
    assert state.status == "todo"


# -------------------------------------------------------------------- admin

def test_admin_check_is_todo_when_the_identity_module_is_absent(conn):
    state = setup_engine.run_check(ctx(conn, Settings()), "admin")
    assert state.status == "todo"
    assert state.detail == "awaiting identity module"


def test_admin_check_uses_the_monkeypatchable_probe(conn):
    app = _FakeApp()
    app.state.setup_status_probe = lambda c: {"users_exist": True}
    state = setup_engine.run_check(ctx(conn, Settings(), app=app), "admin")
    assert state.status == "ok"

    app2 = _FakeApp()
    app2.state.setup_status_probe = lambda c: {"users_exist": False}
    state2 = setup_engine.run_check(ctx(conn, Settings(), app=app2), "admin")
    assert state2.status == "todo"
    assert state2.detail == "no admin account yet"


# ------------------------------------------------------------------- studio

def test_studio_check_todo_until_required_fields_set(conn):
    settings = Settings()
    state = setup_engine.run_check(ctx(conn, settings), "studio")
    assert state.status == "todo"

    site_store.set_many(conn, {
        "org_name": "Studio", "tree_name": "Studio_Tree",
        "canonical_prefix": "P:\\", "template_folders": "AE,B-roll",
    }, updated_by="admin")
    conn.commit()
    state2 = setup_engine.run_check(ctx(conn, settings), "studio")
    assert state2.status == "ok"


# ------------------------------------------------------------------ storage

def test_storage_check_todo_when_projects_dir_unset(conn):
    state = setup_engine.run_check(ctx(conn, Settings()), "storage")
    assert state.status == "todo"


def test_storage_run_probes_and_creates_shared_asset_folders(conn, tmp_path):
    tree_root = tmp_path / "tree"
    projects = tree_root / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(projects_dir=str(projects))

    state = setup_engine.run_do_it(ctx(conn, settings), "storage")
    assert state.status == "ok"
    assert not (projects / setup_engine.PROBE_FILENAME).exists()   # cleaned up, no litter
    assert (tree_root / "Assets" / "Luts").is_dir()
    assert (tree_root / "Assets" / "Stills").is_dir()

    # check() reflects the durable evidence (the asset folders), not the
    # ephemeral probe file -- re-checking right after a successful "Do it"
    # must report ok, not revert to todo.
    check_state = setup_engine.run_check(ctx(conn, settings), "storage")
    assert check_state.status == "ok"


def test_storage_run_fails_when_projects_dir_missing(conn, tmp_path):
    settings = Settings(projects_dir=str(tmp_path / "does-not-exist"))
    state = setup_engine.run_do_it(ctx(conn, settings), "storage")
    assert state.status == "fail"


# ------------------------------------------------------------------ secrets

def test_secrets_check_todo_when_missing(tmp_path, conn, monkeypatch):
    from ccsync_dashboard import secrets_boot

    for name in secrets_boot.SECRET_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(db_path=str(tmp_path / "d.db"))
    state = setup_engine.run_check(ctx(conn, settings), "secrets")
    assert state.status == "todo"


def test_secrets_check_ok_when_all_present_in_env(tmp_path, conn, monkeypatch):
    from ccsync_dashboard import secrets_boot

    for name in secrets_boot.SECRET_ENV_VARS:
        monkeypatch.setenv(name, f"value-for-{name}")
    settings = Settings(db_path=str(tmp_path / "d.db"))
    state = setup_engine.run_check(ctx(conn, settings), "secrets")
    assert state.status == "ok"


def test_secrets_run_backfills_missing_ones(tmp_path, conn, monkeypatch):
    from ccsync_dashboard import secrets_boot

    for name in secrets_boot.SECRET_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(db_path=str(tmp_path / "d.db"))
    state = setup_engine.run_do_it(ctx(conn, settings), "secrets")
    assert state.status == "ok"
    assert "generated" in state.detail


# ---------------------------------------------------------------- syncthing

def test_syncthing_check_todo_when_unconfigured(conn):
    state = setup_engine.run_check(ctx(conn, Settings()), "syncthing")
    assert state.status == "todo"


def test_syncthing_run_fills_a_blank_nas_syncthing_id(conn):
    syncthing = FakeSyncthing().start()
    try:
        settings = Settings(syncthing_url=syncthing.url, syncthing_api_key="fake-key")
        state = setup_engine.run_do_it(ctx(conn, settings), "syncthing")
        assert state.status == "ok"
        assert site_store.get_all(conn)["nas_syncthing_id"] == syncthing.state["my_id"]
    finally:
        syncthing.stop()


def test_syncthing_run_never_overwrites_an_existing_db_value(conn):
    site_store.set_many(conn, {"nas_syncthing_id": "EXISTING-ID"}, updated_by="admin")
    conn.commit()
    syncthing = FakeSyncthing().start()
    try:
        settings = Settings(syncthing_url=syncthing.url, syncthing_api_key="fake-key")
        setup_engine.run_do_it(ctx(conn, settings), "syncthing")
        assert site_store.get_all(conn)["nas_syncthing_id"] == "EXISTING-ID"
    finally:
        syncthing.stop()


# -------------------------------------------------------------------- done

def test_done_ok_only_once_every_required_task_is_ok(conn, tmp_path, monkeypatch):
    from ccsync_dashboard import secrets_boot

    settings = Settings(db_path=str(tmp_path / "d.db"))
    assert setup_engine.run_check(ctx(conn, settings), "done").status == "todo"

    # Satisfy every required task by hand.
    setup_engine.save_state(conn, "eula", setup_engine.TaskState("ok", "accepted v1", setup_engine.now_iso()))
    app = _FakeApp()
    app.state.setup_status_probe = lambda c: {"users_exist": True}
    setup_engine.run_check(ctx(conn, settings, app=app), "admin")
    site_store.set_many(conn, {
        "org_name": "S", "tree_name": "T", "canonical_prefix": "P:\\",
        "template_folders": "AE",
    }, updated_by="admin")
    conn.commit()
    setup_engine.run_check(ctx(conn, settings), "studio")
    for name in secrets_boot.SECRET_ENV_VARS:
        monkeypatch.setenv(name, "x" * 20)
    setup_engine.run_check(ctx(conn, settings), "secrets")
    tree_root = tmp_path / "tree"
    (tree_root / "Projects").mkdir(parents=True)
    settings2 = Settings(db_path=str(tmp_path / "d.db"), projects_dir=str(tree_root / "Projects"))
    setup_engine.run_do_it(ctx(conn, settings2), "storage")
    setup_engine.save_state(conn, "syncthing", setup_engine.TaskState("ok", "device id x", setup_engine.now_iso()))

    final = setup_engine.run_check(ctx(conn, settings), "done")
    assert final.status == "ok"
