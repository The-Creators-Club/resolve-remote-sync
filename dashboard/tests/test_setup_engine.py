"""setup_engine.py -- the SetupEngine task registry (ZERO_TOUCH_PLAN.md WP D,
2026-08-17; the five optional checks made real 2026-08-18)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import setup_engine, site_store, tailscale_local
from ccsync_dashboard.nas import NasError, TrueNASClient
from ccsync_dashboard.settings import Settings

from fake_syncthing import FakeSyncthing
from fake_truenas import FakeTrueNAS


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


def test_required_tasks_are_not_optional():
    for task_id in ("eula", "admin", "studio", "storage", "secrets", "syncthing", "done"):
        assert setup_engine.get(task_id).optional is False


def test_double_registering_the_same_id_is_refused():
    with pytest.raises(ValueError):
        setup_engine.register(setup_engine.Task(
            id="eula", title="dup", description="", check=lambda c: setup_engine.TaskState("ok")
        ))


def test_replace_swaps_in_place_keeping_order():
    original = setup_engine.get("tailnet")
    before = [t.id for t in setup_engine.TASKS]
    idx = before.index("tailnet")
    setup_engine.replace(setup_engine.Task(
        id="tailnet", title="real", description="",
        check=lambda c: setup_engine.TaskState("ok"), optional=True,
    ))
    after = [t.id for t in setup_engine.TASKS]
    assert after == before
    assert setup_engine.TASKS[idx].title == "real"
    # restore the REAL task object, not a stand-in: every other test in this
    # process runs against the registry this one just mutated.
    setup_engine.replace(original)


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

def test_admin_ok_on_a_nas_auth_deployment(conn):
    """The bug the owner photographed: this site authenticates admins against
    the NAS, so no local account will ever exist and `admin` sat on "awaiting
    identity module" forever, holding `Done` hostage (2026-08-18)."""
    settings = Settings(admin_users=frozenset({"alex"}))     # auth_method defaults to smb
    state = setup_engine.run_check(ctx(conn, settings), "admin")
    assert state.status == "ok"
    assert "NAS accounts (truenas)" in state.detail
    assert "alex" in state.detail


def test_admin_names_the_backend_the_admins_live_on(conn):
    settings = Settings(admin_users=frozenset({"alex"}), nas_kind="synology")
    assert "synology" in setup_engine.run_check(ctx(conn, settings), "admin").detail


def test_admin_todo_when_nobody_can_administer_a_nas_auth_site(conn):
    state = setup_engine.run_check(ctx(conn, Settings()), "admin")
    assert state.status == "todo"
    assert "DASH_ADMIN_USERS" in state.detail


def test_admin_ok_when_oidc_maps_admins_from_a_claim(conn):
    settings = Settings(auth_method="oidc", oidc_admin_claim="groups",
                        oidc_admin_values=frozenset({"ccsync-admins"}))
    state = setup_engine.run_check(ctx(conn, settings), "admin")
    assert state.status == "ok"
    assert "groups" in state.detail


def test_admin_under_local_login_reads_the_accounts_table(conn):
    """No DASH_ADMIN_USERS shortcut here: local login needs a password hash,
    so an env var alone would report a dashboard nobody can sign in to as
    done."""
    from ccsync_dashboard import local_users

    settings = Settings(auth_method="local", admin_users=frozenset({"alex"}))
    assert setup_engine.run_check(ctx(conn, settings), "admin").status == "todo"
    local_users.create_user(conn, "alex", "correct-horse-battery", "admin", created_by="test")
    conn.commit()
    state = setup_engine.run_check(ctx(conn, settings), "admin")
    assert state.status == "ok"
    assert "alex" in state.detail


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

def satisfy_required_tasks(conn, tmp_path, monkeypatch, settings, app=None):
    """Everything `done` waits on, except `admin` -- the callers differ only
    in how THAT one is satisfied."""
    from ccsync_dashboard import secrets_boot

    setup_engine.save_state(conn, "eula",
                            setup_engine.TaskState("ok", "accepted v1", setup_engine.now_iso()))
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
    storage_settings = Settings(db_path=settings.db_path,
                                projects_dir=str(tree_root / "Projects"))
    setup_engine.run_do_it(ctx(conn, storage_settings), "storage")
    setup_engine.save_state(conn, "syncthing",
                            setup_engine.TaskState("ok", "device id x", setup_engine.now_iso()))


def test_done_is_ok_on_a_nas_auth_deployment(conn, tmp_path, monkeypatch):
    """The screenshot said `Done: TODO waiting on: admin` on a site whose
    admins are NAS accounts. It must reach ok there without a single local
    account being created (2026-08-18)."""
    settings = Settings(db_path=str(tmp_path / "d.db"), admin_users=frozenset({"alex"}))
    satisfy_required_tasks(conn, tmp_path, monkeypatch, settings)
    assert setup_engine.run_check(ctx(conn, settings), "admin").status == "ok"
    final = setup_engine.run_check(ctx(conn, settings), "done")
    assert final.status == "ok", setup_engine.outstanding_required(conn)


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


# ------------------------------------------------- the five optional tasks
#
# `tailnet`, `nas_connect`, `snapshots`, `editors` and `software` were
# PLACEHOLDERS answering "not implemented in this build" until 2026-08-18.
# The owner saw all five of them, in that wording, on a live dashboard.


def test_the_five_optional_tasks_are_real_checks(conn, tmp_path):
    settings = Settings(db_path=str(tmp_path / "d.db"))
    for task_id in ("tailnet", "nas_connect", "snapshots", "editors", "software"):
        task = setup_engine.get(task_id)
        assert task is not None and task.optional, task_id
        state = task.check(ctx(conn, settings))
        assert state.status in setup_engine.VALID_STATUSES, task_id
        assert state.detail, f"{task_id} answered with an empty detail"
        assert "not implemented" not in state.detail, task_id


def test_the_five_optional_tasks_can_still_be_skipped(conn):
    for task_id in ("tailnet", "nas_connect", "snapshots", "editors", "software"):
        assert setup_engine.run_skip(ctx(conn, Settings()), task_id).status == "skipped"


# ------------------------------------------------------------------ tailnet

def tailnet_check(conn, settings, monkeypatch, raw):
    """Drive the check with a canned LocalAPI answer. `raw` is the shape
    `GET /localapi/v0/status` returns, or None for "no sidecar here"."""
    monkeypatch.setattr(tailscale_local, "status", lambda *a, **k: raw)
    return setup_engine.get("tailnet").check(ctx(conn, settings))


def test_tailnet_ok_when_the_bundled_node_is_signed_in(conn, monkeypatch):
    state = tailnet_check(conn, Settings(), monkeypatch, {
        "BackendState": "Running",
        "AuthURL": "",
        "Self": {"DNSName": "ccsync-studio.tail1234.ts.net."},
        "TailscaleIPs": ["100.101.102.103"],
    })
    assert state.status == "ok"
    assert "ccsync-studio.tail1234.ts.net" in state.detail


def test_tailnet_todo_shows_the_sign_in_link(conn, monkeypatch):
    state = tailnet_check(conn, Settings(), monkeypatch, {
        "BackendState": "NeedsLogin",
        "AuthURL": "https://login.tailscale.com/a/abc123",
        "Self": {"DNSName": ""},
        "TailscaleIPs": None,
    })
    assert state.status == "todo"
    assert "https://login.tailscale.com/a/abc123" in state.detail


def test_tailnet_falls_back_to_the_published_url(conn, monkeypatch):
    site_store.set_many(conn, {"dashboard_url": "https://ccsync.tail1234.ts.net"},
                        updated_by="admin")
    conn.commit()
    state = tailnet_check(conn, Settings(), monkeypatch, None)
    assert state.status == "ok"
    assert "ccsync.tail1234.ts.net" in state.detail


def test_tailnet_accepts_a_cgnat_address(conn, monkeypatch):
    site_store.set_many(conn, {"dashboard_url": "http://100.66.62.41:8480"}, updated_by="admin")
    conn.commit()
    assert tailnet_check(conn, Settings(), monkeypatch, None).status == "ok"


def test_tailnet_todo_when_the_published_url_is_not_a_tailnet_address(conn, monkeypatch):
    site_store.set_many(conn, {"dashboard_url": "http://192.168.0.10:8480"}, updated_by="admin")
    conn.commit()
    state = tailnet_check(conn, Settings(), monkeypatch, None)
    assert state.status == "todo"
    assert "http://192.168.0.10:8480" in state.detail
    assert "not a tailnet address" in state.detail
    assert "docs/INSTALL.md" in state.detail


def test_tailnet_todo_when_nothing_is_published_at_all(conn, monkeypatch):
    state = tailnet_check(conn, Settings(), monkeypatch, None)
    assert state.status == "todo"
    assert "dashboard_url" in state.detail


def test_tailnet_survives_a_broken_localapi(conn, monkeypatch):
    """A raising socket read is not a checklist that says "internal error"."""
    def boom(*_a, **_k):
        raise OSError("connection reset by peer")

    monkeypatch.setattr(tailscale_local, "status", boom)
    state = setup_engine.run_check(ctx(conn, Settings()), "tailnet")
    assert state.status == "todo"
    assert "internal error" not in state.detail


def test_is_tailnet_address_knows_the_two_shapes():
    assert setup_engine._is_tailnet_address("nas.tail26290e.ts.net")
    assert setup_engine._is_tailnet_address("100.64.0.1")
    assert setup_engine._is_tailnet_address("100.127.255.254")
    assert not setup_engine._is_tailnet_address("100.128.0.1")   # just outside the CGNAT range
    assert not setup_engine._is_tailnet_address("192.168.0.10")
    assert not setup_engine._is_tailnet_address("dashboard.example.com")
    assert not setup_engine._is_tailnet_address("")


def test_the_localapi_client_is_quiet_when_there_is_no_socket(tmp_path):
    env = {"TS_SOCKET": str(tmp_path / "nope" / "tailscaled.sock")}
    assert tailscale_local.socket_present(env) is False
    assert tailscale_local.get("/localapi/v0/status", env=env) is None
    assert tailscale_local.summarise(None) is None


def test_the_localapi_summary_flattens_what_the_wizard_reads():
    summary = tailscale_local.summarise({
        "BackendState": "Running", "AuthURL": "",
        "Self": {"DNSName": "a.b.ts.net."}, "TailscaleIPs": ["100.1.2.3"],
    })
    assert summary == {"backend_state": "Running", "auth_url": "",
                       "dns_name": "a.b.ts.net", "ips": ["100.1.2.3"]}


# -------------------------------------------------------------- nas_connect

@pytest.fixture
def truenas():
    fake = FakeTrueNAS().start()
    yield fake
    fake.stop()


def truenas_settings(fake, **extra):
    return Settings(nas_kind="truenas", nas_host="nas.example", nas_user="truenas_admin",
                    nas_pw="fake-pw", nas_base_url=fake.base_url, **extra)


def test_nas_connect_todo_names_the_truenas_key(conn):
    state = setup_engine.run_check(ctx(conn, Settings()), "nas_connect")
    assert state.status == "todo"
    assert "DASH_NAS_HOST" in state.detail
    assert "TRUENAS_API_KEY" in state.detail


def test_nas_connect_todo_names_the_dsm_key(conn):
    state = setup_engine.run_check(ctx(conn, Settings(nas_kind="synology")), "nas_connect")
    assert state.status == "todo"
    assert "DASH_NAS_PW" in state.detail


def test_nas_connect_ok_reports_kind_version_and_hostname(conn, truenas):
    state = setup_engine.run_check(ctx(conn, truenas_settings(truenas)), "nas_connect")
    assert state.status == "ok"
    assert "truenas" in state.detail
    assert "TrueNAS-SCALE-25.10.4" in state.detail
    assert "fake-nas" in state.detail


def test_nas_connect_still_ok_when_system_info_is_out_of_scope(conn, truenas, monkeypatch):
    """A scoped API key that cannot read /system/info has still PROVED the
    NAS answers, which is the whole question this task asks."""
    monkeypatch.setattr(TrueNASClient, "system_info",
                        lambda self: (_ for _ in ()).throw(NasError("403")))
    state = setup_engine.run_check(ctx(conn, truenas_settings(truenas)), "nas_connect")
    assert state.status == "ok"
    assert "answered" in state.detail


def test_nas_connect_fails_in_one_line_when_the_nas_is_unreachable(conn):
    settings = Settings(nas_kind="truenas", nas_host="nas.example", nas_user="u", nas_pw="p",
                        nas_base_url="http://127.0.0.1:9/api/v2.0")
    state = setup_engine.run_check(ctx(conn, settings), "nas_connect")
    assert state.status == "fail"
    assert "\n" not in state.detail
    assert "internal error" not in state.detail


def test_nas_connect_refuses_an_unknown_kind(conn):
    settings = Settings(nas_kind="qnap", nas_host="nas.example", nas_pw="p")
    state = setup_engine.run_check(ctx(conn, settings), "nas_connect")
    assert state.status == "fail"
    assert "qnap" in state.detail


# ---------------------------------------------------------------- snapshots

def write_backup(tmp_path, name, created_at):
    """What dashboard_update.backup_databases leaves behind."""
    folder = tmp_path / "backups" / name
    folder.mkdir(parents=True)
    (folder / "backup.json").write_text(
        json.dumps({"created_at": created_at, "label": "test", "from_version": "0.6.0",
                    "databases": {"dashboard": "dashboard.db"}, "skipped": {}}),
        encoding="utf-8",
    )


def test_snapshots_todo_when_there_is_neither(conn, tmp_path):
    state = setup_engine.run_check(ctx(conn, Settings(db_path=str(tmp_path / "d.db"))), "snapshots")
    assert state.status == "todo"
    assert "no NAS snapshot schedule" in state.detail
    assert "docs/BACKUP_RESTORE.md" in state.detail


def test_snapshots_ok_when_the_nas_holds_a_periodic_task(conn, tmp_path, truenas):
    truenas.state["snapshot_tasks"] = [
        {"id": 1, "dataset": "tank/tree", "naming_schema": "ccsync-%Y%m%d-%H%M", "enabled": True},
    ]
    settings = truenas_settings(truenas, db_path=str(tmp_path / "d.db"))
    state = setup_engine.run_check(ctx(conn, settings), "snapshots")
    assert state.status == "ok"
    assert "1 periodic snapshot task" in state.detail


def test_snapshots_ok_on_a_recent_data_backup(conn, tmp_path):
    write_backup(tmp_path, "20260818T090000Z-manual", dbmod.utcnow_iso())
    state = setup_engine.run_check(ctx(conn, Settings(db_path=str(tmp_path / "d.db"))), "snapshots")
    assert state.status == "ok"
    assert "20260818T090000Z-manual" in state.detail


def test_snapshots_ignores_a_backup_older_than_a_week(conn, tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(days=8)).replace(microsecond=0).isoformat()
    write_backup(tmp_path, "20260801T090000Z-manual", old)
    state = setup_engine.run_check(ctx(conn, Settings(db_path=str(tmp_path / "d.db"))), "snapshots")
    assert state.status == "todo"
    assert "no /data backup in the last 7 days" in state.detail


def test_snapshots_says_dsm_cannot_be_asked(conn, tmp_path):
    settings = Settings(nas_kind="synology", nas_host="dsm.example", nas_user="admin",
                        nas_pw="pw", db_path=str(tmp_path / "d.db"))
    state = setup_engine.run_check(ctx(conn, settings), "snapshots")
    assert state.status == "todo"
    assert "synology snapshot schedules cannot be read over its API" in state.detail


# ------------------------------------------------------------------ editors

def test_editors_todo_when_none_are_known(conn):
    state = setup_engine.run_check(ctx(conn, Settings()), "editors")
    assert state.status == "todo"
    assert "Users page" in state.detail


def test_editors_counts_every_editor_the_dashboard_knows(conn):
    dbmod.record_known_editor(conn, "alex", "seed")
    dbmod.record_known_editor(conn, "ben", "report")
    conn.commit()
    state = setup_engine.run_check(ctx(conn, Settings()), "editors")
    assert state.status == "ok"
    assert state.detail.startswith("2 editor(s):")
    assert "alex" in state.detail and "ben" in state.detail


def test_editors_includes_local_accounts_under_local_login(conn):
    from ccsync_dashboard import local_users

    local_users.create_user(conn, "cal", "correct-horse-battery", "editor", created_by="test")
    conn.commit()
    assert setup_engine.run_check(ctx(conn, Settings()), "editors").status == "todo"
    state = setup_engine.run_check(ctx(conn, Settings(auth_method="local")), "editors")
    assert state.status == "ok"
    assert "cal" in state.detail


# ----------------------------------------------------------------- software

def publish(conn, platform, version, current=True):
    dbmod.insert_companion_package(
        conn, version=version, platform=platform, filename=f"ccsync-{version}.exe",
        sha256="0" * 64, size_bytes=1, published_by="test", now=dbmod.utcnow_iso(),
    )
    if current:
        dbmod.set_current_package(conn, platform, version)
    conn.commit()


def test_software_todo_when_nothing_is_published(conn):
    state = setup_engine.run_check(ctx(conn, Settings()), "software")
    assert state.status == "todo"
    assert "PUBLISHED PACKAGES" in state.detail


def test_software_warns_when_only_one_platform_has_a_build(conn):
    publish(conn, "windows", "0.9.0")
    state = setup_engine.run_check(ctx(conn, Settings()), "software")
    assert state.status == "warn"
    assert state.detail == "windows 0.9.0 current, macos: none published"


def test_software_ok_when_both_platforms_are_current(conn):
    publish(conn, "windows", "0.9.0")
    publish(conn, "macos", "0.9.0")
    state = setup_engine.run_check(ctx(conn, Settings()), "software")
    assert state.status == "ok"
    assert "windows 0.9.0 current" in state.detail
    assert "macos 0.9.0 current" in state.detail


def test_software_run_is_labelled_check_now():
    assert setup_engine.get("software").run_label == "CHECK NOW"


def test_software_run_says_so_when_no_feed_is_configured(conn):
    publish(conn, "windows", "0.9.0")
    publish(conn, "macos", "0.9.0")
    state = setup_engine.run_do_it(ctx(conn, Settings()), "software")
    assert state.status == "ok"
    assert "DASH_RELEASE_FEED_URL" in state.detail


def test_software_run_checks_the_vendor_feed(conn, monkeypatch):
    from ccsync_dashboard import release_feed

    publish(conn, "windows", "0.9.0")
    publish(conn, "macos", "0.9.0")
    seen = {}

    def fake_check_now(_conn, settings, _app_state):
        seen["url"] = settings.release_feed_url
        return {"ok": True, "error": None, "applied": ["companion/macos/0.9.1"]}

    monkeypatch.setattr(release_feed, "check_now", fake_check_now)
    settings = Settings(release_feed_url="https://releases.example/v1/channel.json")
    state = setup_engine.run_do_it(ctx(conn, settings), "software")
    assert seen["url"] == "https://releases.example/v1/channel.json"
    assert state.status == "ok"
    assert "companion/macos/0.9.1" in state.detail


def test_software_run_reports_a_feed_outage_without_failing_the_page(conn, monkeypatch):
    from ccsync_dashboard import release_feed

    publish(conn, "windows", "0.9.0")
    publish(conn, "macos", "0.9.0")
    monkeypatch.setattr(release_feed, "check_now",
                        lambda *a, **k: {"ok": False, "error": "name or service not known"})
    state = setup_engine.run_do_it(
        ctx(conn, Settings(release_feed_url="https://releases.example/v1/channel.json")),
        "software")
    assert state.status == "warn"
    assert "name or service not known" in state.detail


def test_software_run_survives_a_raising_feed_client(conn, monkeypatch):
    from ccsync_dashboard import release_feed

    def boom(*_a, **_k):
        raise RuntimeError("feed exploded")

    monkeypatch.setattr(release_feed, "check_now", boom)
    state = setup_engine.run_do_it(
        ctx(conn, Settings(release_feed_url="https://releases.example/v1/channel.json")),
        "software")
    assert state.status in ("todo", "warn")
    assert "feed exploded" in state.detail
