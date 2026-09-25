"""The 2026-09-24 hunt's fix pass, wave 2 (mediums and lows), group d-api.

bug-dash-api-1..4 and bug-wire-3/4/5, all in api.py. Every test here fails on
HEAD 4462a2a's api.py.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import api, auth, local_users, provision
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "a-test-session-secret-of-length"
TOKEN = "sekrit"
NOW = "2026-09-25T12:00:00+00:00"
K1 = "ssh-ed25519 QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE= ruskin@desk"
K2 = "ssh-ed25519 QkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkI= ruskin@laptop"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def report_headers(editor="ruskin"):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def report(**extra):
    body = {
        "editor_name": "Ruskin", "machine": "EDIT-PC",
        "companion_version": "0.9.77", "reported_at": NOW,
        "lanes": [{"name": "lane_a_rclone_up", "state": "idle", "queued": 0,
                   "transferring": 0, "last_error": None, "last_sync": None}],
    }
    body.update(extra)
    return body


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "Projects"
    projects.mkdir()
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token=TOKEN,
        session_secret=SECRET, admin_users=frozenset({"owen"}),
        projects_dir=str(projects),
    ))
    with TestClient(app) as client:
        client.app.state.collector.stop()
        connection = dbmod.connect(tmp_path / "dash.db")
        try:
            yield client, connection, projects
        finally:
            connection.close()


# ---------------------------------------------------------------------------
# bug-dash-api-1: approving a second computer's key kept the first one
# ---------------------------------------------------------------------------


class FakeNas:
    """The TrueNAS shape: `sshpubkey` carries the key TEXT, and
    create_or_update_editor WRITES exactly what it is handed."""

    def __init__(self, keys: str | None):
        self.keys = keys
        self.writes: list[str] = []

    def find_user(self, username):
        return {"username": username, "uid": 3001, "sshpubkey": self.keys}

    def create_or_update_editor(self, username, ssh_pubkey, full_name=None):
        self.writes.append(ssh_pubkey)
        self.keys = ssh_pubkey
        return {"created": False, "username": username, "home_ok": True, "warnings": []}


def _approve(tmp_path, monkeypatch, nas):
    conn = dbmod.connect(tmp_path / "keys.db")
    dbmod.migrate(conn)
    fp = local_users.pubkey_fingerprint(K2)
    dbmod.add_pending_ssh_key(conn, "ruskin", fp, K2, machine="LAPTOP")
    conn.commit()
    monkeypatch.setattr(api.nas_factory, "nas_configured", lambda s: True)
    monkeypatch.setattr(api.nas_factory, "make_nas_client", lambda s: nas)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        settings=SimpleNamespace(auth_method="smb", nas_kind="truenas"))))
    try:
        return api.approve_pending_ssh_key(request, conn, "ruskin", fp, admin="owen")
    finally:
        conn.close()


def test_approving_a_second_computers_key_keeps_the_first(tmp_path, monkeypatch):
    nas = FakeNas(K1)
    assert _approve(tmp_path, monkeypatch, nas)["ok"] is True
    lines = nas.keys.splitlines()
    assert K1 in lines and K2 in lines, nas.keys


def test_approving_a_key_already_installed_does_not_duplicate_it(tmp_path, monkeypatch):
    # The same key under a different comment is the same key.
    nas = FakeNas(K1 + "\n" + K2.replace("ruskin@laptop", "old-comment"))
    _approve(tmp_path, monkeypatch, nas)
    assert len(nas.keys.splitlines()) == 2


def test_approving_on_an_account_with_no_key_installs_just_that_key(tmp_path, monkeypatch):
    nas = FakeNas(None)
    _approve(tmp_path, monkeypatch, nas)
    assert nas.writes == [K2]


def test_existing_key_lines_of_unlisted_types_are_kept_verbatim(tmp_path, monkeypatch):
    # Review round: a hardware-key line, a certificate line and an options
    # prefix are not in SSH_KEY_PREFIXES, and the first cut dropped them.
    sk = "sk-ssh-ed25519@openssh.com AAAAGnNrLXNzaC1lZDI1NTE5QG9wZW5zc2guY29t ruskin@yubikey"
    cert = "ssh-ed25519-cert-v01@openssh.com AAAAIHNzaC1lZDI1NTE5LWNlcnQ= ruskin@ca"
    opts = 'from="10.0.0.0/8" ' + K1
    nas = FakeNas("\n".join(["# a comment", sk, "", cert, opts]))
    _approve(tmp_path, monkeypatch, nas)
    lines = nas.keys.splitlines()
    assert lines == [sk, cert, opts, K2], nas.keys


def test_the_dsm_installed_marker_is_not_written_back_as_a_key(tmp_path, monkeypatch):
    nas = FakeNas("(installed)")
    _approve(tmp_path, monkeypatch, nas)
    assert nas.writes == [K2]


def test_a_key_already_installed_behind_options_is_not_duplicated(tmp_path, monkeypatch):
    nas = FakeNas('no-pty ' + K2)
    _approve(tmp_path, monkeypatch, nas)
    assert nas.keys == 'no-pty ' + K2


def test_a_backend_that_can_append_is_asked_to(tmp_path, monkeypatch):
    nas = FakeNas(K1)
    added = []
    nas.add_editor_ssh_key = lambda username, key: added.append((username, key))
    _approve(tmp_path, monkeypatch, nas)
    assert added == [("ruskin", K2)] and nas.writes == []


# ---------------------------------------------------------------------------
# bug-dash-api-2: a renaming move renames the proxy too
# ---------------------------------------------------------------------------


def _clip(tmp_path, name="A001.mov"):
    folder = tmp_path / "A"
    (folder / "Proxy").mkdir(parents=True)
    (folder / name).write_bytes(b"orig")
    stem = name.rsplit(".", 1)[0]
    (folder / "Proxy" / f"{stem}.mp4").write_bytes(b"proxy")
    return folder


def test_a_same_folder_rename_renames_the_proxy_and_is_not_partial(tmp_path):
    folder = _clip(tmp_path)
    src, dest = folder / "A001.mov", folder / "Renamed.mov"
    src.rename(dest)
    moved, failed = api._move_proxy_siblings(src, dest)
    assert (moved, failed) == (1, [])
    assert sorted(p.name for p in (folder / "Proxy").iterdir()) == ["Renamed.mp4"]


def test_a_rename_into_another_folder_pairs_the_proxy_with_the_new_name(tmp_path):
    folder = _clip(tmp_path)
    other = tmp_path / "B"
    other.mkdir()
    src, dest = folder / "A001.mov", other / "Other.mov"
    src.rename(dest)
    assert api._move_proxy_siblings(src, dest) == (1, [])
    assert (other / "Proxy" / "Other.mp4").read_bytes() == b"proxy"
    assert not (folder / "Proxy" / "A001.mp4").exists()


def test_a_case_only_rename_renames_the_proxys_spelling(tmp_path):
    folder = _clip(tmp_path)
    src, dest = folder / "A001.mov", folder / "a001.mov"
    staging = folder / "tmp.mov"
    src.rename(staging)
    staging.rename(dest)
    assert api._move_proxy_siblings(src, dest) == (1, [])
    assert [p.name for p in (folder / "Proxy").iterdir()] == ["a001.mp4"]


def test_a_plain_move_keeps_the_proxys_name(tmp_path):
    folder = _clip(tmp_path)
    other = tmp_path / "B"
    other.mkdir()
    src, dest = folder / "A001.mov", other / "A001.mov"
    src.rename(dest)
    assert api._move_proxy_siblings(src, dest) == (1, [])
    assert (other / "Proxy" / "A001.mp4").exists()


def test_a_real_collision_is_still_refused(tmp_path):
    folder = _clip(tmp_path)
    (folder / "Proxy" / "Renamed.mp4").write_bytes(b"someone else")
    src, dest = folder / "A001.mov", folder / "Renamed.mov"
    src.rename(dest)
    moved, failed = api._move_proxy_siblings(src, dest)
    assert moved == 0 and failed and "already at the destination" in failed[0]
    assert (folder / "Proxy" / "Renamed.mp4").read_bytes() == b"someone else"


def test_an_nfd_stem_finds_its_proxy(tmp_path):
    import unicodedata

    nfc = "Matěj"
    nfd = unicodedata.normalize("NFD", nfc)
    folder = tmp_path / "A"
    (folder / "Proxy").mkdir(parents=True)
    (folder / "Proxy" / f"{nfd}.mp4").write_bytes(b"proxy")
    (folder / f"{nfc}.mov").write_bytes(b"orig")
    src, dest = folder / f"{nfc}.mov", folder / "Renamed.mov"
    src.rename(dest)
    assert api._move_proxy_siblings(src, dest) == (1, [])


# ---------------------------------------------------------------------------
# bug-wire-3: a long lane error truncates rather than 422 the report
# ---------------------------------------------------------------------------


def test_a_long_lane_error_does_not_422_the_whole_report(env):
    client, conn, _ = env
    lane = {"name": "lane_c_syncthing", "state": "error", "queued": 0,
            "transferring": 0, "last_error": "x" * 5000, "detail": "d" * 900,
            "current_project": "p" * 900, "last_sync": None,
            "transfers": [{"name": "n" * 900, "direction": "down"}]}
    resp = client.post("/api/v1/report", json=report(lanes=[lane]),
                       headers=report_headers())
    assert resp.status_code == 200, resp.text[:300]
    row = conn.execute(
        "SELECT last_error FROM lane_report_current WHERE lane='lane_c_syncthing'").fetchone()
    assert row is not None and len(row["last_error"]) == 2000


def test_the_other_report_sub_models_truncate_too():
    assert len(api.CompletedIn.model_validate({"name": "n" * 900}).name) == 512
    assert len(api.TransferIn.model_validate({"name": "n" * 900}).name) == 512
    assert len(api.MediaClipIn.model_validate(
        {"clip_name": "c" * 900, "file_path": "f" * 2000}).file_path) == 1024


# ---------------------------------------------------------------------------
# bug-wire-4: /verify reads the arch and says why nothing is offered
# ---------------------------------------------------------------------------


def test_verify_declares_arch():
    body = api.VerifyIn.model_validate({"username": "a", "password": "b",
                                        "arch": "x86_64" * 20})
    assert body.arch == ("x86_64" * 20)[:32]


def test_verify_passes_the_arch_and_a_withheld_sink(monkeypatch):
    seen = {}

    def fake_upgrade_info(conn, platform, running, arch=None, editor=None,
                          machine=None, withheld=None):
        seen["arch"] = arch
        if withheld is not None:
            withheld.append("that build was made for a different processor than this computer")
        return None

    monkeypatch.setattr(api, "_upgrade_info", fake_upgrade_info)
    monkeypatch.setattr(api, "_require_fleet_member", lambda *a, **k: None)
    settings = SimpleNamespace(session_secret=SECRET, report_token="",
                               shared_report_token_enabled=False, admin_users=frozenset())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        settings=settings, credential_verifier=lambda s, u, p: True)))
    monkeypatch.setattr(api.auth, "login_throttled", lambda r, u: 0)
    monkeypatch.setattr(api.auth, "clear_login_failures", lambda r, u: None)
    monkeypatch.setattr(api.auth, "is_admin", lambda s, u: False)
    payload = api.VerifyIn.model_validate({
        "username": "ruskin", "password": "pw", "platform": "macos",
        "companion_version": "0.9.77", "arch": "x86_64"})
    result = api.api_verify(payload, request, conn=None)
    assert seen["arch"] == "x86_64"
    assert "upgrade" not in result
    assert result["upgrade_none_reason"].startswith("that build was made for")


# ---------------------------------------------------------------------------
# bug-wire-5: standins_known is sent empty too
# ---------------------------------------------------------------------------


def test_standins_known_is_sent_when_the_fleet_has_none(env):
    client, _, _ = env
    answer = client.post("/api/v1/report", json=report(),
                         headers=report_headers()).json()
    assert answer["standins_known"] == {"rels": []}


# ---------------------------------------------------------------------------
# bug-dash-api-3: creating or linking over an ARCHIVED project is refused
# ---------------------------------------------------------------------------


def _archived_shoot(client, conn, projects):
    as_user(client, "owen")
    resp = client.post("/api/v1/projects", json={"parent_rel": "", "name": "Shoot"})
    assert resp.status_code == 200, resp.text
    slug = resp.json()["slug"]
    assert dbmod.archive_project(conn, slug, by="owen")
    conn.commit()
    return slug


def test_new_project_over_an_archived_one_is_refused_and_names_unarchive(env):
    client, conn, projects = env
    slug = _archived_shoot(client, conn, projects)
    resp = client.post("/api/v1/projects", json={"parent_rel": "", "name": "Shoot"})
    assert resp.status_code == 422, resp.text
    assert "\"Unarchive\"" in resp.json()["detail"]  # D8 wording, UI port phase 7
    assert "—" not in resp.json()["detail"]
    row = conn.execute("SELECT active, archived_at FROM projects WHERE slug=?",
                       (slug,)).fetchone()
    assert (row["active"], bool(row["archived_at"])) == (0, True)


def test_use_this_folder_on_an_archived_project_is_refused(env):
    client, conn, projects = env
    _archived_shoot(client, conn, projects)
    assert provision.read_marker(projects / "Shoot") is not None
    resp = client.post("/api/v1/projects/link", json={"rel": "Shoot"})
    assert resp.status_code == 422, resp.text
    assert "\"Unarchive\"" in resp.json()["detail"]  # D8 wording, UI port phase 7


def test_an_unmarked_folder_whose_slug_is_archived_is_refused_before_the_marker(env):
    client, conn, projects = env
    _archived_shoot(client, conn, projects)
    (projects / "Shoot" / provision.MARKER_FILENAME).unlink()
    resp = client.post("/api/v1/projects/link", json={"rel": "Shoot"})
    assert resp.status_code == 422, resp.text
    assert provision.read_marker(projects / "Shoot") is None


# ---------------------------------------------------------------------------
# bug-dash-api-4: an admin's password reset signs the account out
# ---------------------------------------------------------------------------


@pytest.fixture
def local_env(tmp_path):
    app = create_app(Settings(
        db_path=str(tmp_path / "local.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), auth_method="local",
    ))
    with TestClient(app) as client:
        client.app.state.collector.stop()
        conn = dbmod.connect(tmp_path / "local.db")
        local_users.create_user(conn, "jsmith", "leaked-password-123", "editor")
        conn.commit()
        conn.close()
        yield client


def test_a_password_reset_revokes_the_accounts_sessions(local_env):
    client = local_env
    resp = client.post("/api/v1/login", json={"username": "jsmith",
                                              "password": "leaked-password-123"})
    assert resp.status_code == 200, resp.text
    cookie = client.cookies.get(auth.COOKIE_NAME)
    store = client.app.state.session_store
    sid = auth.session_id_for(SECRET, cookie)
    assert store.validate(sid) == "jsmith"

    as_user(client, "owen")
    resp = client.post("/api/v1/admin/users/jsmith/password",
                       json={"password": "a-new-password-456"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["sessions_revoked"] == 1
    assert store.validate(sid) is None



# ===========================================================================
# OWED round (2026-09-25): items other groups left for api.py / docs/API.md
# ===========================================================================

LENDER = ("2025-ff4-nuclear", "2025/FF4/Nuclear")
BORROWER_A = ("2026-ff5-energy", "2026/FF5/Energy")
BORROWER_B = ("2026-ff5-civil", "2026/FF5/Civil")


def _projects_and_links(conn, *borrowers):
    now = dbmod.utcnow_iso()
    for slug, label in (LENDER, BORROWER_A, BORROWER_B):
        dbmod.upsert_project(conn, slug, label, f"/data/{slug}", now)
    for borrower in borrowers:
        dbmod.replace_project_links(conn, borrower, [
            {"declared_path": f"Projects/{LENDER[1]}/Interviewees",
             "lender_slug": LENDER[0], "sub_rel": "Interviewees",
             "status": "ok", "detail": None}], now)
    conn.commit()


def _row(slug, mode):
    return {"slug": slug, "sync_mode": mode}


def test_an_upload_only_borrower_gets_no_includes_and_claims_nothing(env):
    # bug-comp-syncthing-2: HEAD gave the upload-only borrower the include
    # AND let it claim the subpath, so the FULL borrower after it lost it to
    # the longest-prefix dedupe.
    _client, conn, _projects = env
    _projects_and_links(conn, BORROWER_A[0], BORROWER_B[0])
    out = api._expand_includes(conn, [_row(BORROWER_A[0], "upload_only"),
                                      _row(BORROWER_B[0], "full")])
    assert BORROWER_A[0] not in out
    assert [e["subpath"] for e in out[BORROWER_B[0]]] == [f"{LENDER[1]}/Interviewees"]


def test_an_upload_only_lender_does_not_cover_a_full_borrower(env):
    # bug-comp-syncthing-3: HEAD answered covered true for a lender ticked
    # in any mode; an upload-only lender brings nothing down.
    _client, conn, _projects = env
    _projects_and_links(conn, BORROWER_A[0])
    out = api._expand_includes(conn, [_row(BORROWER_A[0], "full"),
                                      _row(LENDER[0], "upload_only")])
    assert [e["covered"] for e in out[BORROWER_A[0]]] == [False]
    # Control: a FULL lender still covers (the removal gate's relationship).
    out = api._expand_includes(conn, [_row(BORROWER_A[0], None),
                                      _row(LENDER[0], "full")])
    assert [e["covered"] for e in out[BORROWER_A[0]]] == [True]


def _tick(conn, machine, slug=LENDER[0], editor="ruskin"):
    now = dbmod.utcnow_iso()
    for m in ("OLD-PC", "NEW-PC", "LAPTOP"):
        dbmod.upsert_machine(conn, editor, m, now)
    dbmod.upsert_project(conn, slug, LENDER[1], f"/data/{slug}", now)
    if machine is not None:
        dbmod.add_selection(conn, editor, slug, "test", now, machine=machine)
    conn.commit()


def _held(conn, slug=LENDER[0]):
    return sorted(r[0] for r in conn.execute(
        "SELECT machine FROM selections WHERE project_slug=?", (slug,)))


def test_a_companion_untick_that_misses_a_standing_tick_is_refused(env):
    # logic-plans-5: a renamed PC (NEW-PC, registered) whose tick stands under
    # OLD-PC. HEAD answered 200 changed:false, which a companion <= 0.9.78
    # reads as "unticked" and deletes the local copy.
    client, conn, _projects = env
    _tick(conn, "OLD-PC")
    r = client.delete(f"/api/v1/selection/ruskin/{LENDER[0]}?machine=NEW-PC",
                      headers=report_headers())
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "NEW-PC" in detail and "renamed" in detail
    assert " -- " not in detail and "—" not in detail
    assert _held(conn) == ["OLD-PC"]


def test_a_companion_untick_of_a_tick_gone_everywhere_is_still_ok(env):
    # A stale tray plan: nothing can bring it back, so the disk may be freed.
    client, conn, _projects = env
    _tick(conn, None)
    r = client.delete(f"/api/v1/selection/ruskin/{LENDER[0]}?machine=NEW-PC",
                      headers=report_headers())
    assert r.status_code == 200 and r.json()["changed"] is False


def test_a_companion_untick_of_its_own_tick_is_unchanged(env):
    client, conn, _projects = env
    _tick(conn, "NEW-PC")
    dbmod.add_selection(conn, "ruskin", LENDER[0], "test", dbmod.utcnow_iso(),
                        machine="LAPTOP")
    conn.commit()
    r = client.delete(f"/api/v1/selection/ruskin/{LENDER[0]}?machine=NEW-PC",
                      headers=report_headers())
    assert r.status_code == 200 and r.json()["changed"] is True
    assert _held(conn) == ["LAPTOP"]


def test_the_signed_in_untick_stays_idempotent(env):
    client, conn, _projects = env
    _tick(conn, "OLD-PC")
    as_user(client, "owen")
    r = client.delete(f"/api/v1/selection/ruskin/{LENDER[0]}?machine=NEW-PC")
    assert r.status_code == 200 and r.json()["changed"] is False
    assert _held(conn) == ["OLD-PC"]


def _fleet_row(conn, editor="ruskin", machine="EDIT-PC"):
    view = api.build_editors_view(conn)
    for row in view["editors"]:
        if row.get("editor_username") == editor and row.get("machine") == machine:
            return row
    raise AssertionError(f"no row for {editor}/{machine}: {view['editors']!r}")


def _manifest(conn, mode="editor"):
    conn.execute(
        "INSERT INTO editor_media_project (editor_username, machine, project_slug,"
        " mode, reported_at) VALUES ('ruskin', 'EDIT-PC', 'p', ?, ?)", (mode, NOW))
    conn.commit()


def test_the_fleet_row_carries_the_owed_file_count(env, monkeypatch):
    # logic-sync-truth-5: HEAD never set owed_files, so the grid's idle line
    # could not use the count the transfers page already had.
    client, conn, _projects = env
    assert client.post("/api/v1/report", json=report(),
                       headers=report_headers()).status_code == 200
    _manifest(conn)
    monkeypatch.setattr(api.db, "fetch_sync_backlog", lambda c, **kw: [
        {"editor": "ruskin", "machine": "EDIT-PC", "n_files": 40, "uncertain": False},
        {"editor": "ruskin", "machine": "EDIT-PC", "n_files": 20, "uncertain": False},
        {"editor": "other", "machine": "X", "n_files": 5, "uncertain": False},
    ])
    row = _fleet_row(conn)
    assert row["owed_files"] == 60
    # The headline half is d-diag's (health.fleet_headline reads the key);
    # this row leads with its why-sentence, so only the key is pinned here.


def test_a_manifest_with_nothing_owed_counts_zero(env, monkeypatch):
    client, conn, _projects = env
    client.post("/api/v1/report", json=report(), headers=report_headers())
    _manifest(conn)
    monkeypatch.setattr(api.db, "fetch_sync_backlog", lambda c, **kw: [])
    assert _fleet_row(conn)["owed_files"] == 0


def test_no_count_is_claimed_without_data_or_on_failure(env, monkeypatch):
    client, conn, _projects = env
    client.post("/api/v1/report", json=report(), headers=report_headers())
    monkeypatch.setattr(api.db, "fetch_sync_backlog", lambda c, **kw: [])
    # No manifest ever: "no backlog rows" is "no data", not "nothing owed".
    assert "owed_files" not in _fleet_row(conn)
    _manifest(conn)
    # An uncertain zero (capped originals list) proves nothing either.
    monkeypatch.setattr(api.db, "fetch_sync_backlog", lambda c, **kw: [
        {"editor": "ruskin", "machine": "EDIT-PC", "n_files": 0, "uncertain": True}])
    assert "owed_files" not in _fleet_row(conn)

    def boom(c, **kw):
        raise RuntimeError("db locked")
    monkeypatch.setattr(api.db, "fetch_sync_backlog", boom)
    assert "owed_files" not in _fleet_row(conn)


def test_a_base_rig_row_claims_no_count(env, monkeypatch):
    client, conn, _projects = env
    client.post("/api/v1/report", json=report(), headers=report_headers())
    _manifest(conn, mode="base")
    conn.execute("UPDATE machine_state SET mode='base' WHERE machine='EDIT-PC'")
    conn.commit()
    monkeypatch.setattr(api.db, "fetch_sync_backlog", lambda c, **kw: [])
    assert "owed_files" not in _fleet_row(conn)


def _typewriter_dashes_in(path):
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                skip.add(id(first.value))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("debug", "info", "warning", "error",
                                       "exception", "critical")):
            skip.update(id(n) for n in ast.walk(node))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in skip and " -- " in n.value]


def test_api_py_copy_has_no_typewriter_em_dash():
    # ui-copy-6: HEAD had 24 (HTTP details, the transfers row name).
    from pathlib import Path
    hits = _typewriter_dashes_in(Path(api.__file__))
    assert not hits, hits


def test_api_md_names_the_silent_machines_reason_code():
    # logic-ytdl-jobs-1: jobs.py answers it; the contract table must list it.
    from pathlib import Path
    from ccsync_dashboard import jobs
    doc = (Path(__file__).resolve().parents[2] / "docs" / "API.md").read_text(encoding="utf-8")
    assert f"| `{jobs.REASON_SILENT}` |" in doc
    assert jobs.REFUSE_SILENT in doc


# ===========================================================================
# Owed round 3 (2026-09-25)
# ===========================================================================

class _PasswordNas:
    """create-or-update succeeds; a password write is recorded; anything the
    Users view asks the NAS for is a NasError, which that view tolerates."""

    def __init__(self):
        self.passwords: list[tuple[str, str]] = []

    def create_or_update_editor(self, username, ssh_pubkey, full_name=None):
        return {"created": False, "username": username, "home_ok": True, "warnings": []}

    def set_known_password(self, username, password):
        self.passwords.append((username, password))

    def __getattr__(self, name):
        raise api.NasError(f"fake NAS: {name} not modelled")


def _json_create(env, monkeypatch, body):
    client, _conn, _projects = env
    nas = _PasswordNas()
    monkeypatch.setattr(api.nas_factory, "nas_configured", lambda s: True)
    monkeypatch.setattr(api.nas_factory, "make_nas_client", lambda s: nas)
    store = client.app.state.session_store
    store.create("sid-leaked", "ruskin")
    assert store.validate("sid-leaked") == "ruskin"
    as_user(client, "owen")
    resp = client.post("/api/v1/admin/users", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json(), nas, store


def test_the_json_create_setting_a_password_signs_the_account_out(env, monkeypatch):
    out, nas, store = _json_create(env, monkeypatch, {
        "username": "ruskin", "ssh_pubkey": K1, "password": "a-new-password-456"})
    assert nas.passwords == [("ruskin", "a-new-password-456")]
    # HEAD: the password changed through create-or-update and the session
    # signed in with the old one still validated (the page twin revoked it).
    assert store.validate("sid-leaked") is None
    assert out["sessions_revoked"] == 1


def test_the_json_create_without_a_password_signs_nobody_out(env, monkeypatch):
    out, nas, store = _json_create(env, monkeypatch, {
        "username": "ruskin", "ssh_pubkey": K1})
    assert nas.passwords == []
    assert store.validate("sid-leaked") == "ruskin"
    assert "sessions_revoked" not in out


# ---------------------------------------------------------------------------
# logic-sync-truth-5, Fable round M1 (2026-09-25): the owed-files diff is
# cached against its inputs, and a change to any of them is seen next build
# ---------------------------------------------------------------------------


def _backlog_fleet(env, monkeypatch):
    """A real backlog: the NAS holds three proxies of project `p`, EDIT-PC
    holds one and is ticked for it. The diff is counted, not stubbed."""
    client, conn, _projects = env
    assert client.post("/api/v1/report", json=report(),
                       headers=report_headers()).status_code == 200
    pid = dbmod.upsert_project(conn, "p", "P", "/projects/p", NOW)
    dbmod.replace_nas_media(conn, pid, [
        (f"Proxy/{n}.mov", "proxy", ".mov", 10, 1) for n in ("a", "b", "c")],
        "sig1", 1, NOW, force=True)
    dbmod.add_selection(conn, "ruskin", "p", "test", NOW, machine="EDIT-PC")
    dbmod.upsert_editor_media_project(
        conn, editor="ruskin", machine="EDIT-PC", slug="p", mode="editor",
        n_originals=0, bytes_originals=0, n_proxies=1, bytes_proxies=10,
        truncated=False, now=NOW)
    dbmod.replace_editor_media(conn, "ruskin", "EDIT-PC", "p",
                               [("Proxy/a.mov", "proxy", 10)], NOW)
    conn.commit()
    calls = []
    real = dbmod.fetch_sync_backlog

    def counted(c, **kw):
        calls.append(1)
        return real(c, **kw)
    monkeypatch.setattr(api.db, "fetch_sync_backlog", counted)
    return conn, pid, calls


def test_two_builds_with_nothing_changed_diff_once(env, monkeypatch):
    conn, _pid, calls = _backlog_fleet(env, monkeypatch)
    assert _fleet_row(conn)["owed_files"] == 2
    assert _fleet_row(conn)["owed_files"] == 2
    assert len(calls) == 1
    # The TTL is a backstop for a writer the fingerprint does not know: past
    # it, the diff runs again even with nothing changed.
    later = api.time.monotonic() + api._OWED_CACHE_TTL_SECONDS + 1
    monkeypatch.setattr(api.time, "monotonic", lambda: later)
    assert _fleet_row(conn)["owed_files"] == 2
    assert len(calls) == 2


def test_a_new_manifest_is_seen_on_the_next_build(env, monkeypatch):
    conn, _pid, calls = _backlog_fleet(env, monkeypatch)
    assert _fleet_row(conn)["owed_files"] == 2
    later = "2026-09-25T12:05:00+00:00"
    dbmod.upsert_editor_media_project(
        conn, editor="ruskin", machine="EDIT-PC", slug="p", mode="editor",
        n_originals=0, bytes_originals=0, n_proxies=2, bytes_proxies=20,
        truncated=False, now=later)
    dbmod.replace_editor_media(conn, "ruskin", "EDIT-PC", "p",
                               [("Proxy/a.mov", "proxy", 10),
                                ("Proxy/b.mov", "proxy", 10)], later)
    conn.commit()
    assert _fleet_row(conn)["owed_files"] == 1
    assert len(calls) == 2


def test_a_nas_walk_and_a_mode_change_are_seen_on_the_next_build(env, monkeypatch):
    conn, pid, calls = _backlog_fleet(env, monkeypatch)
    assert _fleet_row(conn)["owed_files"] == 2
    dbmod.replace_nas_media(conn, pid, [
        (f"Proxy/{n}.mov", "proxy", ".mov", 10, 1) for n in ("a", "b", "c", "d")],
        "sig2", 1, "2026-09-25T12:10:00+00:00")
    conn.commit()
    assert _fleet_row(conn)["owed_files"] == 3
    # Upload-only: lane B never runs, so the proxies are no longer owed.
    dbmod.add_selection(conn, "ruskin", "p", "test", NOW, machine="EDIT-PC",
                        sync_mode=dbmod.SYNC_MODE_UPLOAD_ONLY)
    conn.commit()
    assert _fleet_row(conn)["owed_files"] == 0
    assert len(calls) == 3
