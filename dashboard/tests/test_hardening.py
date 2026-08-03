"""Round-2 hardening regressions that don't belong to one feature area:
credential-probe limits, REST path encoding, report field caps, the
project-page swap target, and deploy/pyproject dependency parity."""
from __future__ import annotations

import re
import threading
import time
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
DASHBOARD_ROOT = Path(__file__).resolve().parents[1]


# -- credential probes ---------------------------------------------------


def test_smb_probe_rejects_a_guest_mapped_session(monkeypatch):
    """smbprotocol does NOT reject a session the server mapped to guest or
    null. If the NAS ever maps bad passwords to guest, every password would
    authenticate for every username -- including DASH_ADMIN_USERS."""
    import sys
    import types

    calls = {"flags": 0x0001}

    class FakeSession:
        def __init__(self, *_a, **_kw):
            self.session_flags = calls["flags"]

        def connect(self):
            return None

        def disconnect(self):
            return None

    class FakeConnection:
        def __init__(self, *_a, **_kw):
            pass

        def connect(self, timeout=None):
            return None

        def disconnect(self):
            return None

    conn_mod = types.ModuleType("smbprotocol.connection")
    conn_mod.Connection = FakeConnection
    sess_mod = types.ModuleType("smbprotocol.session")
    sess_mod.Session = FakeSession
    pkg = types.ModuleType("smbprotocol")
    monkeypatch.setitem(sys.modules, "smbprotocol", pkg)
    monkeypatch.setitem(sys.modules, "smbprotocol.connection", conn_mod)
    monkeypatch.setitem(sys.modules, "smbprotocol.session", sess_mod)

    settings = Settings(smb_host="nas.example")
    assert auth.verify_credentials(settings, "jsmith", "anything") is False  # guest-mapped
    calls["flags"] = 0x0002                                                  # null session
    assert auth.verify_credentials(settings, "jsmith", "anything") is False
    calls["flags"] = 0                                                       # real session
    assert auth.verify_credentials(settings, "jsmith", "pw") is True


def test_smb_probes_are_concurrency_capped(monkeypatch):
    """Both auth endpoints are unauthenticated and spend up to 10s inside
    smbprotocol; without a cap, a burst against a blackholing SMB host
    consumes every anyio worker and queues every other route (including
    companions' reports) behind them."""
    monkeypatch.setattr(auth, "SMB_PROBE_QUEUE_SECONDS", 0.05)
    release = threading.Event()
    started = threading.Semaphore(0)

    def slow_probe(host, username, password, timeout=10.0):
        started.release()
        release.wait(5)
        return True

    monkeypatch.setattr(auth, "_verify_smb", slow_probe)
    settings = Settings(smb_host="nas.example")
    threads = [
        threading.Thread(target=auth.verify_credentials, args=(settings, f"u{i}", "pw"),
                         daemon=True)
        for i in range(auth.MAX_CONCURRENT_SMB_PROBES)
    ]
    for t in threads:
        t.start()
    for _ in threads:                       # every slot is occupied
        assert started.acquire(timeout=5)

    try:
        with pytest.raises(auth.CredentialProbeBusy):
            auth.verify_credentials(settings, "one-too-many", "pw")
    finally:
        release.set()
        for t in threads:
            t.join(timeout=5)

    # slots are returned afterwards
    assert auth.verify_credentials(settings, "later", "pw") is True


def test_login_endpoints_answer_503_when_probes_are_saturated(tmp_path):
    settings = Settings(db_path=str(tmp_path / "busy.db"), session_secret=SECRET)
    app = create_app(settings)

    def busy(*_a, **_kw):
        raise auth.CredentialProbeBusy("saturated")

    app.state.credential_verifier = busy
    with TestClient(app) as client:
        assert client.post("/api/v1/login",
                           json={"username": "j", "password": "p"}).status_code == 503
        assert client.post("/api/v1/verify",
                           json={"username": "j", "password": "p"}).status_code == 503
        page = client.post("/login", data={"username": "j", "password": "p"})
        assert "busy checking sign-ins" in page.text
        # a saturated pool is not a failed password, so it must not throttle
        assert auth.login_throttled("j") is False


# -- syncthing REST path encoding ---------------------------------------


def test_folder_ids_are_percent_encoded_in_rest_paths():
    """Slugs come from an editor-writable marker file with no charset
    validation: a slug containing '/', '?' or '#' would otherwise address a
    different endpoint entirely."""
    from ccsync_dashboard.syncthing_client import SyncthingClient

    seen = {}

    class FakeSession:
        def request(self, method, url, **kwargs):
            seen["method"], seen["url"] = method, url

            class R:
                status_code = 200
                content = b"{}"

                @staticmethod
                def json():
                    return {}
            return R()

    client = SyncthingClient("http://st.local", "key", session=FakeSession())
    client.put_folder("weird/slug?x#y", {"id": "weird/slug?x#y"})
    assert seen["url"] == "http://st.local/rest/config/folders/weird%2Fslug%3Fx%23y"
    client.get_folder("a b")
    assert seen["url"] == "http://st.local/rest/config/folders/a%20b"


# -- report field caps ---------------------------------------------------


@pytest.fixture
def report_client(tmp_path):
    settings = Settings(db_path=str(tmp_path / "caps.db"), session_secret=SECRET,
                        report_token="tok")
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def report_headers(editor="jsmith"):
    return {"X-CCSync-Token": "tok",
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def base_payload(**extra):
    p = {"editor_name": "jsmith", "machine": "PC",
         "reported_at": "2026-07-25T10:00:00+00:00",
         "lanes": [{"name": "lane_a_video_up", "state": "idle"}]}
    p.update(extra)
    return p


@pytest.mark.parametrize("mutate", [
    lambda p: p["lanes"][0].update(last_error="E" * 2001),
    lambda p: p["lanes"][0].update(detail="D" * 501),
    lambda p: p["lanes"][0].update(last_sync="S" * 65),
    lambda p: p["lanes"][0].update(current_project="C" * 513),
    lambda p: p["lanes"][0].update(transfers=[{"name": "n" * 513}]),
    lambda p: p.update(media_tree={"P": [{"clip_name": "c" * 513}]}),
    lambda p: p.update(local_manifest={"p": {"n_originals": -5}}),
    lambda p: p.update(local_manifest={"p": {"n_originals": 10_000_001}}),
])
def test_report_fields_are_capped(report_client, mutate):
    """Per-VALUE caps still reject: a 513-char clip name or a negative file
    count is a broken companion, not a big one. The per-COLLECTION caps
    (projects/queue/clips/manifest files) truncate instead -- see
    test_a_sixty_fifth_project_does_not_take_the_machine_off_the_grid."""
    payload = base_payload()
    mutate(payload)
    resp = report_client.post("/api/v1/report", json=payload, headers=report_headers())
    assert resp.status_code == 422


def test_report_machine_is_stripped(report_client):
    """`machine` is half the primary key in four tables: ' PC' and 'PC' must
    never become two machines."""
    report_client.post("/api/v1/report", json=base_payload(machine="  PC  "),
                       headers=report_headers())
    report_client.post("/api/v1/report", json=base_payload(machine="PC"),
                       headers=report_headers())
    body = report_client.post("/api/v1/report", json=base_payload(machine="   "),
                              headers=report_headers())
    assert body.status_code == 422           # blank after stripping

    conn = dbmod.connect(report_client.app.state.settings.db_path)
    machines = {r[0] for r in conn.execute("SELECT DISTINCT machine FROM lane_report_current")}
    conn.close()
    assert machines == {"PC"}


# -- B6: an oversized report is truncated, never rejected -------------------


def test_a_sixty_fifth_project_does_not_take_the_machine_off_the_grid(report_client):
    """B6: MAX_REPORT_PROJECTS was a RAISING pydantic validator, and pydantic
    runs before the route body -- so the 65th project 422'd the whole HEAVY
    report and took lane status, transfers, machine_state, presence and the
    upgrade advertisement with it. An idle companion only ever sends heavy
    ticks, so the machine vanished from the fleet grid entirely. Worst placed
    is the base rig, whose local_root is the whole NAS tree."""
    payload = base_payload(
        local_manifest={f"2026/FF5/P{i}": {"n_originals": i} for i in range(200)},
        media_tree={f"Project {i}": [] for i in range(70)},
        queue=[f"slug-{i}" for i in range(100)],
    )
    resp = report_client.post("/api/v1/report", json=payload, headers=report_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    # ...and the truncation is REPORTED, not silent
    assert body["truncated"]["local_manifest"] == 200 - 64
    assert body["truncated"]["media_tree"] == 70 - 64
    assert body["truncated"]["queue"] == 100 - 64

    # the machine is on the grid, with its lane row intact
    conn = dbmod.connect(report_client.app.state.settings.db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM lane_report_current").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM machine_state").fetchone()[0] == 1
        # the surviving 64 are the FIRST 64 the companion sent (it prioritises)
        kept = {r[0] for r in conn.execute(
            "SELECT DISTINCT project_slug FROM editor_media_project")}
        assert len(kept) == 64
    finally:
        conn.close()


def test_an_oversized_clip_list_is_trimmed_not_rejected(report_client):
    """A Resolve project with more than MAX_MEDIA_CLIPS clips in its media
    pool must lose the tail of its bin tree, not the whole report."""
    payload = base_payload(media_tree={
        "Big": [{"clip_name": f"c{i}", "present": True} for i in range(4100)]})
    resp = report_client.post("/api/v1/report", json=payload, headers=report_headers())
    assert resp.status_code == 200
    assert resp.json()["truncated"]["media_clips"] == 100


def test_an_oversized_manifest_file_list_is_trimmed_not_rejected(report_client):
    payload = base_payload(local_manifest={"2026/FF5/Huge": {
        "n_originals": 5000,
        "originals": [[f"a/{i}.braw", 10] for i in range(4200)],
    }})
    resp = report_client.post("/api/v1/report", json=payload, headers=report_headers())
    assert resp.status_code == 200
    assert resp.json()["truncated"]["manifest_files"] == 200


def test_a_report_within_the_ceilings_reports_no_truncation(report_client):
    payload = base_payload(
        local_manifest={f"2026/FF5/P{i}": {"n_originals": 1} for i in range(64)},
        queue=[f"slug-{i}" for i in range(64)])
    body = report_client.post("/api/v1/report", json=payload,
                              headers=report_headers()).json()
    assert "truncated" not in body


def test_truncation_slices_the_raw_body_before_pydantic_builds_models():
    """The slice runs as a mode='before' validator: truncating AFTER
    validation would mean parsing the whole oversized payload first, which is
    the cost this bounds."""
    from ccsync_dashboard.api import MAX_REPORT_PROJECTS, _truncate_report_sections

    raw = {"local_manifest": {f"p{i}": {"n_originals": 1} for i in range(100)}}
    out, dropped = _truncate_report_sections(raw)
    assert len(out["local_manifest"]) == MAX_REPORT_PROJECTS
    assert dropped == {"local_manifest": 100 - MAX_REPORT_PROJECTS}
    assert len(raw["local_manifest"]) == 100      # the input is not mutated


# -- B15: the report body gate is unbypassable and pre-auth -----------------


def _chunks(count, size, counter=None):
    """A body httpx sends with Transfer-Encoding: chunked (no Content-Length),
    recording how many chunks were actually pulled off it."""
    def gen():
        for _ in range(count):
            if counter is not None:
                counter["pulled"] += 1
            yield b"x" * size
    return gen()


def test_a_chunked_body_cannot_bypass_the_report_size_cap(report_client):
    """B15: body_size_gate read Content-Length and nothing else, so a chunked
    request -- which has none -- skipped the check entirely. uvicorn then
    buffered the whole thing and the single-worker container was OOM-killed,
    taking the fleet's only sync-status view down with it."""
    from ccsync_dashboard.app import MAX_REPORT_BODY_BYTES

    resp = report_client.post(
        "/api/v1/report",
        content=_chunks(12, 1024 * 1024),          # 12 MB, no Content-Length
        headers={**report_headers(), "Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    assert str(MAX_REPORT_BODY_BYTES) in resp.json()["detail"]


def test_a_declared_oversize_body_is_still_refused_up_front(report_client):
    """The cheap Content-Length rejection stays: an honest client is told to
    stop before it sends 8 MB."""
    resp = report_client.post(
        "/api/v1/report",
        content=b"x" * 16,
        headers={**report_headers(), "Content-Type": "application/json",
                 "Content-Length": "99999999"},
    )
    assert resp.status_code == 413
    # an unparseable length is refused rather than guessed at
    resp = report_client.post(
        "/api/v1/report", content=b"x" * 16,
        headers={**report_headers(), "Content-Type": "application/json",
                 "Content-Length": "not-a-number"},
    )
    assert resp.status_code in (400, 413)


def test_a_bad_token_never_reaches_the_body(report_client):
    """B15's other half: /api/v1/report is in _OPEN_EXACT with
    `payload: ReportIn`, so FastAPI read and pydantic-validated the entire
    body before api_report checked X-CCSync-Token. An unauthenticated caller
    got to spend the container's memory and CPU at will."""
    counter = {"pulled": 0}
    resp = report_client.post(
        "/api/v1/report",
        content=_chunks(12, 1024 * 1024, counter),
        headers={"X-CCSync-Token": "wrong", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401
    assert counter["pulled"] == 0            # not one byte was read

    # ...and the token check beats VALIDATION too: a body that would 422 if
    # parsed answers 401, because it is never parsed.
    resp = report_client.post("/api/v1/report", json={"garbage": True},
                              headers={"X-CCSync-Token": "wrong"})
    assert resp.status_code == 401


def test_an_unconfigured_report_token_is_refused_before_the_body_too(tmp_path):
    settings = Settings(db_path=str(tmp_path / "notok.db"), session_secret=SECRET)
    with TestClient(create_app(settings)) as client:
        counter = {"pulled": 0}
        resp = client.post("/api/v1/report", content=_chunks(4, 1024, counter),
                           headers={"Content-Type": "application/json"})
        assert resp.status_code == 401
        assert "DASH_REPORT_TOKEN" in resp.json()["detail"]
        assert counter["pulled"] == 0


def test_a_legal_report_still_round_trips_through_the_gate(report_client):
    """The gate replays the buffered body into the route; a normal report must
    be entirely unaffected by it."""
    payload = base_payload(local_manifest={
        f"2026/FF5/P{i}": {"n_originals": 3, "bytes_originals": 999}
        for i in range(8)
    })
    resp = report_client.post("/api/v1/report", json=payload, headers=report_headers())
    assert resp.status_code == 200 and resp.json()["ok"] is True


def test_the_package_route_is_not_buffered_by_the_gate():
    """api_publish_package streams its 200 MB body to disk and counts bytes as
    it goes; buffering it in the middleware would make the memory ceiling the
    thing it was added to remove. Only exact-matched (in-memory) routes are
    buffered."""
    from ccsync_dashboard import app as appmod

    assert set(appmod._BODY_LIMITS) == {"/api/v1/report"}
    assert appmod._BODY_LIMIT_PREFIXES[0][0] == "/api/v1/admin/packages/"


def test_upgrade_is_not_offered_for_an_unreported_platform(tmp_path):
    """X-5's other half: coercing an absent/unknown platform to 'windows' is
    how a macOS companion got offered a Windows .exe."""
    from ccsync_dashboard.api import _upgrade_info

    conn = dbmod.connect(tmp_path / "u.db")
    dbmod.migrate(conn)
    dbmod.insert_companion_package(
        conn, version="0.2.0", platform="windows", filename="c.exe", sha256="a" * 64,
        size_bytes=1, published_by="alex", now=dbmod.utcnow_iso())
    dbmod.set_current_package(conn, "windows", "0.2.0")
    assert _upgrade_info(conn, "windows", "0.1.0")["version"] == "0.2.0"
    assert _upgrade_info(conn, None, "0.1.0") is None
    assert _upgrade_info(conn, "amiga", "0.1.0") is None
    conn.close()


def test_slug_for_rel_ignores_inactive_and_prefers_the_path_match(tmp_path):
    """`label` has no uniqueness constraint: two projects sharing one (or a
    deactivated project) used to yield an arbitrary slug."""
    from ccsync_dashboard.api import _slug_for_rel

    conn = dbmod.connect(tmp_path / "s.db")
    dbmod.migrate(conn)
    now = dbmod.utcnow_iso()
    dbmod.upsert_project(conn, "old-dead-slug", "2026/CCT/Season 1", "/data/Projects/elsewhere", now)
    dbmod.upsert_project(conn, "real-slug", "2026/CCT/Season 1",
                         "/data/Projects/2026/CCT/Season 1", now)
    assert _slug_for_rel(conn, "2026/CCT/Season 1") == "real-slug"

    conn.execute("UPDATE projects SET active=0 WHERE slug='real-slug'")
    # only inactive rows remain for that label -> fall back to slugify, never
    # to the arbitrary deactivated row
    assert _slug_for_rel(conn, "2026/CCT/Season 1") == "old-dead-slug"
    conn.execute("UPDATE projects SET active=0")
    assert _slug_for_rel(conn, "2026/CCT/Season 1") == "2026-cct-season-1"
    conn.close()


def test_safe_next_rejects_backslash_host():
    from ccsync_dashboard.ui import _safe_next

    assert _safe_next("/project/x") == "/project/x"
    assert _safe_next("//evil.com") == "/"
    assert _safe_next("/\\evil.com") == "/"
    assert _safe_next("https://evil.com") == "/"
    assert _safe_next("") == "/"


# -- templates ------------------------------------------------------------


def test_project_detail_tick_targets_only_its_own_fragment():
    """hx-target='closest main' replaced <main>'s children wholesale,
    destroying project.html's every-10s polling wrapper AND the entire MEDIA
    PRESENCE panel: after one tick the page was frozen and the bins section
    gone until a manual reload."""
    detail = (DASHBOARD_ROOT / "templates" / "partials" / "project_detail.html").read_text(
        encoding="utf-8")
    page = (DASHBOARD_ROOT / "templates" / "project.html").read_text(encoding="utf-8")
    assert 'hx-target="closest main"' not in detail
    assert 'hx-target="#project-detail"' in detail
    assert 'id="project-detail"' in page
    # the polling wrapper and the bins panel are still separate elements
    assert 'hx-trigger="every 10s"' in page
    assert "/bins" in page


def test_project_detail_renders_a_syncthing_folder_error(tmp_path):
    """A folder Syncthing has STOPPED ('folder marker missing' after a move)
    must say so instead of showing a stale-but-plausible completion %."""
    settings = Settings(db_path=str(tmp_path / "fe.db"), session_secret=SECRET,
                        admin_users=frozenset({"alex"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        now = dbmod.utcnow_iso()
        pid = dbmod.upsert_project(conn, "p", "2026/CCT/Season 1", "/data/Projects/x", now)
        dbmod.set_folder_status(conn, pid, "stopped", "folder marker missing", now)
        conn.commit()
        conn.close()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "alex"))
        page = client.get("/project/p")
        assert page.status_code == 200
        assert "[ SYNCTHING FOLDER STOPPED ]" in page.text
        assert "folder marker missing" in page.text
        health = client.get("/api/v1/health").json()
        assert health["folder_errors"][0]["slug"] == "p"


# -- deploy parity --------------------------------------------------------


def _requirement_name(line: str) -> str:
    return re.split(r"[<>=!~\[ ]", line.strip(), 1)[0].lower()


def test_deploy_requirements_match_pyproject_dependencies():
    """run.sh installs deploy/requirements.txt into the persistent venv and
    hash-stamps it -- so a dependency added only to pyproject.toml makes the
    container boot and then fail at import, without even re-running pip."""
    pyproject = tomllib.loads((DASHBOARD_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    # The optional `broll` group counts as declared: those packages are not
    # imported by ccsync_dashboard, but the container mounts the b-roll app
    # in-process and its imports fail without them. Both directions still
    # matter -- something in requirements.txt and in neither list is
    # unaccounted-for, which is what this test exists to catch.
    declared = {_requirement_name(d): d.strip() for d in pyproject["project"]["dependencies"]}
    declared.update({
        _requirement_name(d): d.strip()
        for d in pyproject["project"].get("optional-dependencies", {}).get("broll", [])
    })
    deployed = {
        _requirement_name(line): line.strip()
        for line in (DASHBOARD_ROOT / "deploy" / "requirements.txt").read_text(
            encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert deployed == declared, (
        "deploy/requirements.txt and pyproject.toml [project.dependencies] have drifted: "
        f"only in pyproject={sorted(set(declared) - set(deployed))}, "
        f"only in requirements={sorted(set(deployed) - set(declared))}"
    )


def test_dashboard_version_does_not_drift():
    """__init__.VERSION is what release.ps1 and check_deploy_drift.ps1 read,
    and what /api/v1/health reports; pyproject's version is what a pip install
    of this package would carry. They had drifted three releases apart (0.3.5
    vs 0.2.0) with nothing checking -- cosmetic only while the container runs
    from PYTHONPATH, and a wrong answer the moment it doesn't."""
    from ccsync_dashboard import VERSION

    pyproject = tomllib.loads((DASHBOARD_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == VERSION, (
        f"dashboard/pyproject.toml version={pyproject['project']['version']} but "
        f"ccsync_dashboard.VERSION={VERSION} -- bump both"
    )
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)


def test_shared_secrets_are_compared_in_constant_time():
    """`==` on a shared secret leaks its length and matching prefix through
    timing. Every token check in the app goes through api.token_ok."""
    from ccsync_dashboard.api import token_ok

    assert token_ok("sekrit", "sekrit") is True
    assert token_ok("sekrit", "sekrix") is False
    assert token_ok("sekrit", "sek") is False
    assert token_ok("", "") is False          # unconfigured never authenticates
    assert token_ok("sekrit", "") is False
    assert token_ok("", "sekrit") is False


def test_the_venv_is_not_inside_the_editor_reachable_data_volume():
    """AUDIT C-2: /data was 3000:3001 mode 770 -- group `editors`, and every
    editor has a real shell account on the NAS -- while run.sh exec'd
    /data/venv/bin/python, guarded by nothing but an md5 stamp file in the
    same writable directory. Swapping that interpreter was code execution as
    the dashboard user with TRUENAS_PW in the environment."""
    run_sh = (DASHBOARD_ROOT / "deploy" / "run.sh").read_text(encoding="utf-8")
    compose = (DASHBOARD_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")

    code = "\n".join(
        line for line in run_sh.splitlines() if not line.lstrip().startswith("#")
    )
    assert "VENV=/venv" in code
    assert "/data/venv" not in code      # comments may still name the incident
    # the interpreter that gets exec'd comes from the dedicated volume
    assert '"$VENV/bin/python" -m uvicorn' in code
    # ...which is mounted, and NOT under /data
    assert re.search(r"^\s*- \S+/venv:/venv\s*$", compose, re.M)
    assert not re.search(r"^\s*- \S*/data/venv", compose, re.M)
    # anything the app writes under /data stays owner-only: its egid is 3001
    # (editors, needed for the setgid /projects tree)
    assert "umask 077" in code


def test_compose_binds_are_env_driven_and_image_is_pinned():
    """Two hardcoded IPs in the port bindings made a NAS DHCP change or a
    tailnet IP rotation a hard outage ('cannot assign requested address'),
    and an unpinned base image changes underneath a redeploy."""
    compose = (DASHBOARD_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    assert "${DASH_BIND_LAN:-192.168.0.102}:8480:8480" in compose
    assert "${DASH_BIND_TAILNET:-100.71.216.3}:8480:8480" in compose
    assert re.search(r"image: python:3\.12\.\d+-slim", compose)
    assert "healthcheck:" in compose and "/api/v1/health" in compose
