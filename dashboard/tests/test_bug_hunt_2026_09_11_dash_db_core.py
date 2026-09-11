"""bug-hunt 2026-09-11, territory dash-db-core (CR-240).

Nine findings, most of them a rule this repo already states applied to one
more place: "no dashboard call follows a redirect" on the two clients CR-111
missed (dash-core-1/-2), the uid/gid pair a narrow env mapping dropped
(dash-core-3), the one Origin value that is unambiguous (dash-core-4), `..`
in the second site path list (dash-core-5), a required wizard task with no
action that clears it (dash-core-6), a session lifetime of zero (dash-core-7),
"a base rig holds no tick" on the `own` branch (dash-db-1), a locked database
read as an admin control being off (dash-db-2), and a cap that capped the work
but not the rows (dash-db-3).

The redirect tests drive the REAL clients against two loopback servers, one
307ing to the other, because the credential exposure is in what `requests`
replays - a test that stubs the session away cannot see it.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import links, provision, secrets_boot, setup_engine
from ccsync_dashboard.app import create_app
from ccsync_dashboard.nas import NasError
from ccsync_dashboard.nas.synology import SynologyClient
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient, SyncthingError

NOW = "2026-09-11T10:00:00+00:00"


# ------------------------------------------------- the two loopback servers

class _Sink(BaseHTTPRequestHandler):
    """Records everything it is handed, so a test can assert that a secret
    did NOT arrive here."""

    received: list[dict] = []

    def _record(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        _Sink.received.append({
            "path": self.path,
            "body": self.rfile.read(length).decode("utf-8", "replace") if length else "",
            "headers": {k.lower(): v for k, v in self.headers.items()},
        })
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"success": true}')

    do_GET = _record
    do_POST = _record

    def log_message(self, *args) -> None:      # keep pytest output clean
        pass


def _serve(handler_cls) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.fixture
def redirector():
    """(base_url_of_the_redirector, the recorded requests of the SINK)."""
    _Sink.received = []
    sink, sink_url = _serve(_Sink)

    class Redirect(BaseHTTPRequestHandler):
        def _go(self) -> None:
            # 307 preserves method AND body verbatim, which is the whole
            # exposure: every DSM credential rides in a POST body.
            self.send_response(307)
            self.send_header("Location", f"{sink_url}/steal")
            self.end_headers()

        do_GET = _go
        do_POST = _go

        def log_message(self, *args) -> None:
            pass

    redir, redir_url = _serve(Redirect)
    try:
        yield redir_url, _Sink.received
    finally:
        redir.shutdown()
        sink.shutdown()


# ------------------------------------------------------------- dash-core-1

def test_the_synology_client_refuses_a_redirect_instead_of_replaying_the_password(
        redirector):
    """CR-111 put allow_redirects=False on the OIDC token POST and every
    TrueNAS request and missed this backend. A 307 replayed the DSM admin
    password - it is in the login POST's BODY, and `requests` strips an
    Authorization header across a host change but never a body."""
    redir_url, stolen = redirector
    client = SynologyClient("dsm.example", "ccsync", "SUPER-SECRET", False,
                            base_url=redir_url)
    with pytest.raises(NasError) as exc:
        client.ping()
    assert "307" in str(exc.value)
    assert "Nothing was sent on" in str(exc.value)
    assert stolen == [], "the DSM password was replayed to the redirect target"


# ------------------------------------------------------------- dash-core-2

def test_the_syncthing_client_refuses_a_redirect_instead_of_handing_over_the_api_key(
        redirector):
    """X-API-Key is a CUSTOM header, so `requests` re-sends it verbatim across
    a host change. The `>= 300` refusal used to run after the chain had
    already resolved, so it never saw a 3xx that worked."""
    redir_url, stolen = redirector
    client = SyncthingClient(gui_url=redir_url, api_key="fleet-syncthing-key")
    with pytest.raises(SyncthingError) as exc:
        client.ping()
    assert "307" in str(exc.value)
    assert stolen == [], "the Syncthing API key followed the redirect"
    assert not any("fleet-syncthing-key" in (r["headers"].get("x-api-key") or "")
                   for r in stolen)


# ------------------------------------------------------------- dash-core-3

def test_a_narrow_env_mapping_cannot_drop_app_uid_from_internal_env(
        tmp_path, monkeypatch):
    """The Secrets wizard task passes a snapshot of the five SECRET_ENV_VARS
    only, deliberately, so it does not mutate the running process's
    environment. `_write_sidecar_env_files` then wrote internal.env with the
    token line alone and silently dropped the APP_UID/APP_GID pair boot had
    written - the ownership pair whose absence is the dash-admin-2 shape."""
    monkeypatch.setenv("APP_UID", "3000")
    monkeypatch.setenv("APP_GID", "3001")
    for name in secrets_boot.SECRET_ENV_VARS:
        monkeypatch.setenv(name, "x" * 40)
    boot_env = {name: "x" * 40 for name in secrets_boot.SECRET_ENV_VARS}
    boot_env["APP_UID"] = "3000"
    boot_env["APP_GID"] = "3001"
    secrets_boot.ensure_secrets(boot_env, data_dir=tmp_path)
    internal = tmp_path / "secrets" / "internal.env"
    assert "APP_UID=3000" in internal.read_text(encoding="utf-8")

    # ... and now the wizard task's narrow snapshot, same directory.
    wizard_env = {name: "x" * 40 for name in secrets_boot.SECRET_ENV_VARS}
    secrets_boot.ensure_secrets(wizard_env, data_dir=tmp_path)
    after = internal.read_text(encoding="utf-8")
    assert "APP_UID=3000" in after
    assert "APP_GID=3001" in after


# ------------------------------------------------------------- dash-core-4

SECRET = "test-secret-that-is-long-enough-1234"


@pytest.fixture
def app_client(tmp_path):
    """Signed in: the CSRF gate runs INSIDE the login gate, so an anonymous
    POST never reaches the origin check at all."""
    settings = Settings(db_path=str(tmp_path / "csrf.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    with TestClient(create_app(settings)) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield c


def test_origin_null_is_refused_on_the_cards_prefix(app_client):
    """`null` is an OPAQUE origin - a sandboxed iframe, a data:/blob:
    document - and means the opposite of same-origin. It used to fall into
    the absent-Origin branch and pass the one gate the ~70 Cards POST routes
    have (they are exempt from the CSRF token because they drive a Resolve
    timeline)."""
    res = app_client.post("/cards/api/move", headers={"Origin": "null"},
                          json={}, follow_redirects=False)
    assert res.status_code == 403
    assert "another site" in res.text


def test_an_absent_origin_still_passes_the_cards_gate(app_client):
    """The carve-out that must survive: some browsers omit Origin on a
    same-origin form post, which is why an ABSENT header is not a refusal.
    Anything but 403 means the gate let it through to routing."""
    res = app_client.post("/cards/api/move", json={}, follow_redirects=False)
    assert res.status_code != 403


# ------------------------------------------------------------- dash-core-5

def test_the_template_folders_env_door_drops_dotdot(monkeypatch):
    """api.create_tree_project mkdirs each of these under the project. The
    sibling list (DASH_SITE_SHARED_ASSETS) already dropped `..` for exactly
    this reason; the environment is the door no validator sees."""
    monkeypatch.setenv("DASH_SITE_TEMPLATE_FOLDERS", "../../Assets, AE, Audio/../Music")
    assert provision._site_list("DASH_SITE_TEMPLATE_FOLDERS", ["X"]) == [
        "Assets", "AE", "Audio/Music"]


# ------------------------------------------------------------- dash-core-6

def test_a_build_with_no_eula_does_not_wall_the_wizard(conn, monkeypatch, tmp_path):
    """REL-5 made the no-EULA state `warn`, rightly. But `eula` is a REQUIRED
    task: run_skip refuses it, _accept_eula returns the same warn, and
    outstanding_required therefore held it for ever - a Setup badge with no
    button anywhere that clears it."""
    monkeypatch.setattr(setup_engine, "EULA_PATH", tmp_path / "missing.md")
    ctx = setup_engine.SetupContext(conn, Settings())
    state = setup_engine.run_check(ctx, "eula")
    assert state.status == "warn"           # still visibly wrong
    assert "eula" not in setup_engine.outstanding_required(conn)
    assert "eula" not in dict(setup_engine.outstanding_for_done(conn))


def test_a_required_task_that_is_merely_warn_still_gates(conn, monkeypatch, tmp_path):
    """The other direction: only `eula` is exempt. A required task that warns
    for a reason an admin can act on must keep the badge lit."""
    assert setup_engine.WARN_SATISFIES_IDS == frozenset({"eula"})


def test_eula_path_is_re_resolved_when_the_import_time_answer_is_missing(monkeypatch):
    """EULA_PATH was resolved once at import, so an OTA bundle that adds
    docs/legal/EULA.md could not be seen without restarting the process."""
    monkeypatch.setattr(setup_engine, "EULA_PATH",
                        setup_engine.Path("/nowhere/EULA.md"))
    monkeypatch.setattr(setup_engine, "_EULA_AT_IMPORT", setup_engine.EULA_PATH)
    calls = []

    def fake_find():
        calls.append(1)
        return setup_engine.Path("/found/EULA.md")

    monkeypatch.setattr(setup_engine, "_find_eula", fake_find)
    assert setup_engine.eula_path() == setup_engine.Path("/found/EULA.md")
    assert calls == [1]


def test_a_deliberately_set_eula_path_is_left_alone(monkeypatch, tmp_path):
    """A path something set on purpose (a test's monkeypatch, DASH_EULA_DOC)
    is the answer, missing or not: re-resolving it would silently substitute
    the checkout's real licence file."""
    missing = tmp_path / "missing.md"
    monkeypatch.setattr(setup_engine, "EULA_PATH", missing)
    assert setup_engine.eula_path() == missing


# ------------------------------------------------------------- dash-core-7

def test_a_zero_session_lifetime_falls_back_instead_of_bricking_sign_in(caplog):
    """The two readers disagreed about 0: start_session's `or` gave the
    COOKIE the seven-day default while SessionStore stored 0.0 and deleted the
    row on the next request, which reads as a revocation - sign in, then
    straight back to /login, with nothing logged."""
    with caplog.at_level(logging.ERROR):
        settings = Settings(session_secret="test-secret",
                            session_absolute_seconds=0, session_idle_seconds=0)
    assert settings.session_absolute_seconds == 7 * 24 * 3600
    assert settings.session_idle_seconds == 12 * 3600
    assert "SESSION_ABSOLUTE_SECONDS" in caplog.text


def test_a_negative_session_lifetime_is_treated_the_same():
    settings = Settings(session_secret="test-secret", session_absolute_seconds=-1)
    assert settings.session_absolute_seconds == 7 * 24 * 3600


# --------------------------------------------------------------- dash-db-1

def _wired_machine_with_its_own_tick(conn):
    """An ordinary editing machine that was ticked for a project and LATER
    flipped to wired in the tray (CR-88 made that the computer's own one
    click). Nothing deletes its selections rows."""
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "RIG", NOW)
    dbmod.upsert_machine_state(conn, "ed", "RIG", None, NOW, mode="base")
    dbmod.upsert_project(conn, "ff5", "2026/FF5", "/ff5", NOW)
    dbmod.add_selection(conn, "ed", "ff5", "seed", NOW, machine="RIG")
    conn.commit()


def test_a_wired_machines_own_tick_is_not_in_the_enforce_view(conn):
    """CR-110 taught the bucket branch that a base rig holds no tick and left
    the `own` branch alone, so every reader that decides what an admin is TOLD
    (notices._check_plan_without_share, invariants._check_plan_has_share) saw
    a full tick with no share and wrote a permanent, uncleanable error notice
    about a correct configuration."""
    _wired_machine_with_its_own_tick(conn)
    assert dbmod.fetch_machine_selections(
        conn, sync_modes=(dbmod.SYNC_MODE_FULL,), for_enforce=True) == {}


def test_the_admin_grid_still_sees_that_stale_tick(conn):
    """The other direction, and the reason this is a parameter rather than
    the default: assignments.py builds the tick grid from the same map. A cell
    filtered out of the grid is a row in the table with no button left to
    clear it."""
    _wired_machine_with_its_own_tick(conn)
    assert dbmod.fetch_machine_selections(conn) == {"ff5": [("ed", "RIG")]}


def test_an_editor_machines_own_tick_survives_the_enforce_view(conn):
    """Under-sharing is the safe direction for a REMOVAL, never for a machine
    that is supposed to be syncing (the B16 shape)."""
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    dbmod.upsert_machine_state(conn, "ed", "LAP", None, NOW, mode="editor")
    dbmod.upsert_project(conn, "ff5", "2026/FF5", "/ff5", NOW)
    dbmod.add_selection(conn, "ed", "ff5", "seed", NOW, machine="LAP")
    conn.commit()
    assert dbmod.fetch_machine_selections(conn, for_enforce=True) == {
        "ff5": [("ed", "LAP")]}


# --------------------------------------------------------------- dash-db-2

_V50_TABLES = (
    "CREATE TABLE known_editors (editor_username TEXT PRIMARY KEY, suspended_at TEXT,"
    " suspended_by TEXT, suspended_reason TEXT)",
    "CREATE TABLE projects (slug TEXT PRIMARY KEY, label TEXT, archived_at TEXT,"
    " archived_by TEXT)",
    "CREATE TABLE selections (editor_username TEXT, machine TEXT, project_slug TEXT)",
    "CREATE TABLE pending_ssh_keys (username TEXT, fingerprint TEXT, key_text TEXT,"
    " machine TEXT, submitted_at TEXT, source TEXT)",
)


def _lock_the_database(tmp_path):
    """A REAL `database is locked`, not a simulated one: a rollback-journal
    database (WAL readers do not block, which is why the dashboard uses it)
    with a second connection holding an exclusive write transaction."""
    path = tmp_path / "locked.db"
    writer = sqlite3.connect(path, isolation_level=None)
    for statement in _V50_TABLES:
        writer.execute(statement)
    reader = sqlite3.connect(path, timeout=0.05)
    reader.row_factory = sqlite3.Row
    writer.execute("BEGIN EXCLUSIVE")
    writer.execute("INSERT INTO projects (slug, label) VALUES ('x', 'X')")
    return writer, reader


@pytest.mark.parametrize("call", [
    lambda c: dbmod.suspended_editors(c),
    lambda c: dbmod.editor_suspension(c, "ed"),
    lambda c: dbmod.archived_project_slugs(c),
    lambda c: dbmod.fetch_archived_projects(c),
    lambda c: dbmod.fetch_pending_ssh_keys(c),
])
def test_a_locked_database_raises_instead_of_answering_empty(tmp_path, call):
    """These five swallowed EVERY OperationalError and answered the empty
    value, justified as tolerating a pre-v50 database. What that actually
    caught was `database is locked`, and for suspension/archive an empty
    answer is a fail-OPEN: the enforce cycle filters its plan with them, so
    one exceeded busy timeout re-shares every folder the admin just
    suspended, silently."""
    writer, reader = _lock_the_database(tmp_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            call(reader)
    finally:
        writer.rollback()
        writer.close()
        reader.close()


def test_a_pre_v50_database_is_still_tolerated(tmp_path):
    """The compat case the bare except was written for stays tolerated: a
    missing column or table is answered, not raised."""
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.execute("CREATE TABLE known_editors (editor_username TEXT PRIMARY KEY)")
    old.execute("CREATE TABLE projects (slug TEXT PRIMARY KEY)")
    old.commit()
    assert dbmod.suspended_editors(old) == set()
    assert dbmod.editor_suspension(old, "ed") is None
    assert dbmod.archived_project_slugs(old) == set()
    assert dbmod.fetch_archived_projects(old) == []
    assert dbmod.fetch_pending_ssh_keys(old) == []       # no such table
    old.close()


# --------------------------------------------------------------- dash-db-3

def test_a_marker_with_thousands_of_includes_yields_a_bounded_number_of_rows(tmp_path):
    """MAX_INCLUDES' comment promises a tampered marker cannot make this
    unbounded, but the loop appended one `invalid` result per remaining entry
    - so 10,000 includes became up to 10,000 project_links rows, rewritten
    every provision cycle and rendered on the admin page. The marker is a
    plain JSON file on a share every editor can write."""
    projects = tmp_path / "Projects"
    projects.mkdir()
    raw = [f"Projects/Lender/Sub/n{i}" for i in range(links.MAX_INCLUDES + 5000)]
    results = links.resolve_marker_includes(projects, "Projects/Borrower", raw)
    assert len(results) == links.MAX_INCLUDES + 1
    over = [r for r in results if "too many includes" in r.detail]
    assert len(over) == 1
    assert over[0].status == links.STATUS_INVALID
    assert "5000 ignored" in over[0].detail


# --------------------------------------- comp-app-2 (owed by dash-api-jobs)

GUARD_AT = {"at": NOW}


def _machine_row(conn):
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "RIG", NOW)
    dbmod.upsert_machine_state(conn, "ed", "RIG", None, NOW, mode="editor")
    conn.commit()


def test_the_wave_three_resolve_fields_are_stored(conn):
    """`app.resolve_health()` has put these nine on the wire since
    2026-09-04; the model declared them and store_resolve_health's fixed
    column list carried only the v38 counters, so "Resolve is wedged on this
    call for 40 seconds" arrived every report and was dropped."""
    _machine_row(conn)
    dbmod.store_resolve_health(conn, "ed", "RIG", dict(GUARD_AT, **{
        "resolve_health_detail": {
            "connected": True, "project_open": "2026/FF5", "wedged_seconds": 40.5,
            "wedged_call": "GetMediaPool", "missing_clips": [{"name": "a.mov"}],
            "non_canonical_refused": [], "proxy_attach": {"attached": 3},
            "proxy_gaps": {"count": 2}, "stills": {"count": 9},
            "out_of_tree": 12,          # not one of the nine: not kept here
        },
    }))
    conn.commit()
    stored = dbmod.resolve_health_detail(conn, "ed", "RIG")
    assert stored["connected"] is True
    assert stored["wedged_seconds"] == 40.5
    assert stored["wedged_call"] == "GetMediaPool"
    assert stored["proxy_attach"] == {"attached": 3}
    assert stored["stills"] == {"count": 9}
    assert "out_of_tree" not in stored
    # An EMPTY list is kept: "the pass ran and refused nothing" is an answer,
    # and only None (the field was absent) is silence.
    assert stored["non_canonical_refused"] == []


def test_a_companion_that_stops_sending_the_detail_clears_it(conn):
    """THE LATCH RULE, as everywhere else in this group: a section that says
    nothing DELETES the row. A wedged-call sentence from last Tuesday is
    worse than silence."""
    _machine_row(conn)
    dbmod.store_resolve_health(conn, "ed", "RIG", dict(GUARD_AT, **{
        "resolve_health_detail": {"wedged_seconds": 12.0}}))
    conn.commit()
    assert dbmod.resolve_health_detail(conn, "ed", "RIG")
    dbmod.store_resolve_health(conn, "ed", "RIG", dict(GUARD_AT))
    conn.commit()
    assert dbmod.resolve_health_detail(conn, "ed", "RIG") == {}


# ------------------------------------ comp-resolve-3 (owed by dash-api-jobs)

def test_the_cards_gate_detail_is_not_truncated_below_what_the_model_accepts(conn):
    """CardsAgentIn.detail accepts 1000; this stored 255, cutting off the one
    sentence that names the other program holding the Resolve client and its
    path."""
    _machine_row(conn)
    detail = "a standalone reorder_web.py --agent is running: " + ("C:/long/path" * 100)
    dbmod.store_machine_capabilities(conn, "ed", "RIG", {
        "cards_agent": {"connected": False, "gate_state": "refused",
                        "detail": detail}}, NOW)
    conn.commit()
    stored = conn.execute(
        "SELECT cap_cards_detail FROM machine_state WHERE machine='RIG'").fetchone()[0]
    assert len(stored) == 1000
    assert stored == detail[:1000]


# ------------------------------------------------- dash-collector-alerts-3

def test_a_collector_whose_cycles_fail_is_still_reported_stale_when_it_stops(conn):
    """`collector_stale` used to be computed only inside `if reachable and
    finished_at`, and `reachable` is the `ok` of the newest non-Syncthing-free
    run - so a collector whose last cycle FAILED could never be stale, and
    neither could a Syncthing-less deployment. The home page and
    /api/v1/health showed a dead collector as fresh."""
    long_ago = "2026-09-11T09:00:00+00:00"
    dbmod.record_poll_run(conn, "syncthing", long_ago, long_ago, False, "boom")
    conn.commit()
    status = dbmod.fetch_collector_status(conn, now=NOW)
    assert status["collector_stale"] is True


def test_a_collector_that_started_a_cycle_just_now_is_not_stale(conn):
    """Liveness is the START of a cycle, whatever the cycle then made of
    itself: anything starting proves the thread is turning."""
    dbmod.record_poll_run(conn, "syncthing", NOW, None, False, "still running")
    conn.commit()
    assert dbmod.fetch_collector_status(conn, now=NOW)["collector_stale"] is False


def test_a_fresh_container_with_no_runs_is_not_stale(conn):
    """No rows at all is "cannot tell", never "stopped"."""
    assert dbmod.fetch_collector_status(conn, now=NOW)["collector_stale"] is False


# ------------------------------------------------- dash-collector-alerts-6

def test_prune_ages_out_cleared_notices_but_never_an_open_one(conn):
    """`notices` had no retention at all. A cleared row about a computer
    nobody owns any more lived for ever; an OPEN one is a problem the server
    has found and no cleanup pass may take it off the home page."""
    old = "2026-01-01T00:00:00+00:00"
    dbmod.notice(conn, "server_error", "error", "/api/old", body="b", now=old)
    dbmod.clear_notice(conn, "server_error", "/api/old", now=old)
    dbmod.notice(conn, "server_error", "error", "/api/live", body="b", now=old)
    conn.commit()

    dbmod.prune(conn, NOW)
    conn.commit()
    subjects = {r["subject"] for r in conn.execute("SELECT subject FROM notices")}
    assert subjects == {"/api/live"}


def test_prune_keeps_a_recently_cleared_notice(conn):
    dbmod.notice(conn, "server_error", "error", "/api/recent", body="b", now=NOW)
    dbmod.clear_notice(conn, "server_error", "/api/recent", now=NOW)
    conn.commit()
    dbmod.prune(conn, NOW)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 1


def test_a_500_is_recorded_under_the_route_template_not_the_concrete_path(tmp_path):
    """A raw path with an id in it is an unbounded row count in `notices`
    (upserted on (kind, subject)), and a raw path under /broll/share is a
    client's live credential written where a page will show it."""
    settings = Settings(db_path=str(tmp_path / "err.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    app = create_app(settings)

    @app.get("/api/v1/boom/{thing_id}")
    def boom(thing_id: str):                                   # noqa: ANN202
        raise RuntimeError("no")

    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        assert client.get("/api/v1/boom/12345").status_code == 500

    conn = dbmod.connect(tmp_path / "err.db")
    subjects = [r["subject"] for r in conn.execute(
        "SELECT subject FROM notices WHERE kind='server_error'")]
    conn.close()
    assert subjects == ["/api/v1/boom/{thing_id} (RuntimeError)"]
