"""/admin/health: one ranked list over four sources (SYS-6, wave 4).

Four pages answered "is my fleet all right" and nothing composed them, so an
owner who is not an engineer had no way to know which one was authoritative.
This page reads notices, the alert scan, the invariants and the protection
lines through their existing public functions and prints each row's own
`diagnosis` and `fix` VERBATIM. The tests below are mostly about that word:
a composed page that paraphrases its sources is a second place for the
wording to be wrong.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod, protection, ui
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-value-health-1234567890"


@pytest.fixture
def env(tmp_path):
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as c:
        conn = dbmod.connect(settings.db_path)
        try:
            yield c, conn
        finally:
            conn.close()


def as_user(client, user="owen"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def test_the_page_is_admin_only(env):
    client, _conn = env
    assert as_user(client, "jsmith").get("/admin/health").status_code == 403


def test_a_fresh_server_reports_what_it_has_not_checked(env):
    """NOT the empty state: on a server no pass has run on, every invariant
    and every protection line is [ NOT CHECKED ], and the page says so rather
    than reading as a clean bill of health (docs/SELF_DIAGNOSIS.md)."""
    client, _conn = env
    page = as_user(client).get("/admin/health")
    assert page.status_code == 200
    assert "[ HEALTH ]" in page.text
    assert "NOT CHECKED ]" in page.text
    assert "Nothing is open" not in page.text


def test_the_empty_state_says_nothing_is_open(env, monkeypatch):
    client, _conn = env
    monkeypatch.setattr(ui, "_health_rows", lambda *_a, **_kw: [])
    page = as_user(client).get("/admin/health")
    assert page.status_code == 200
    assert "Nothing is open" in page.text


def test_an_open_notice_appears_with_its_own_diagnosis_and_fix(env):
    client, conn = env
    dbmod.notice(conn, "project_container_marker", "error", "2026/CCT",
                 "A project marker was dropped on a folder that contains "
                 "projects, so all of them are hidden.",
                 "Delete the marker in that folder.")
    conn.commit()
    page = as_user(client).get("/admin/health")
    assert page.status_code == 200
    # VERBATIM: both sentences, exactly as the notice wrote them.
    assert "so all of them are hidden." in page.text
    assert "Delete the marker in that folder." in page.text
    assert "PROBLEM THE SERVER FOUND" in page.text
    # ...and a way back to the panel that owns it.
    assert "/#server-notices" in page.text


def test_a_notice_carries_its_take_me_there_link(env):
    """DDIAG-8's href, reused rather than re-derived: the destination is a
    property of the KIND and is written down once, in db.NOTICE_KINDS."""
    client, conn = env
    kind = next((k for k in dbmod.notice_kinds()
                 if dbmod.notice_href(k["kind"], "x")[0]), None)
    assert kind is not None, "no notice kind offers a destination any more"
    href, label = dbmod.notice_href(kind["kind"], "x")
    dbmod.notice(conn, kind["kind"], kind["severity"], "x",
                 "something happened", "do the thing")
    conn.commit()
    page = as_user(client).get("/admin/health")
    assert href in page.text and label in page.text


def test_a_broken_protection_line_reaches_the_page(env):
    client, conn = env
    line = protection.LINES[0]
    dbmod.meta_set_json(conn, protection.RESULTS_META, {
        "checked_at": dbmod.utcnow_iso(),
        "lines": [{"key": line.key, "state": protection.BROKEN,
                   "detail": "no snapshot task exists on this server",
                   "subjects": []}],
    })
    conn.commit()
    rows = ui._health_rows(_FakeRequest(client), conn)
    mine = [r for r in rows if r["source"] == "protection"]
    assert mine, "the protection lines are not on the health page"
    first = next(r for r in mine if r["title"] == line.title)
    assert first["diagnosis"] == line.consequence
    assert first["fix"] == line.fix
    assert first["detail_page"] == "/admin/protection"


def test_not_checked_is_its_own_band_and_never_ok(env):
    """The rule the 2026-08-28 sweep exists to hold: an unverified check is
    not a passing one, and it must not be counted with the failures either."""
    client, conn = env
    rows = ui._health_rows(_FakeRequest(client), conn)
    bands = {r["band"] for r in rows}
    assert bands <= set(ui.HEALTH_BAND_ORDER)
    # Nothing on a fresh server has been checked, so every protection and
    # invariant row is in the third band, not the first two.
    assert all(r["band"] == "unknown"
               for r in rows if r["source"] in ("protection", "invariant"))
    page = as_user(client).get("/admin/health")
    assert "[ NOT CHECKED ] is not [ OK ]" in page.text


def test_the_worst_comes_first(env):
    client, conn = env
    dbmod.notice(conn, "provision_failed", "warn", "b", "a warning body", "fix b")
    dbmod.notice(conn, "project_container_marker", "error", "a",
                 "an error body", "fix a")
    conn.commit()
    rows = ui._health_rows(_FakeRequest(client), conn)
    bands = [r["band"] for r in rows]
    assert bands == sorted(bands, key=ui.HEALTH_BAND_ORDER.index)
    assert rows[0]["band"] == "error"


def test_one_broken_source_costs_its_own_rows_and_not_the_page(env, monkeypatch):
    """This is the page an owner opens when something is already wrong."""
    client, conn = env
    from ccsync_dashboard import alerts as alerts_mod

    def boom(*_a, **_kw):
        raise RuntimeError("the scan is broken")

    monkeypatch.setattr(alerts_mod, "scan", boom)
    dbmod.notice(conn, "project_container_marker", "error", "a",
                 "an error body", "fix a")
    conn.commit()
    page = as_user(client).get("/admin/health")
    assert page.status_code == 200
    assert "an error body" in page.text


def test_health_is_the_settings_landing_and_the_alert_chip_target(env):
    client, _conn = env
    assert ui.SETTINGS_LANDING == "/admin/health"
    topbar = (ui.TEMPLATES_DIR / "partials" / "topbar.html").read_text(encoding="utf-8")
    # SYS-6(c): the chip points at the composed page, not at one of its four
    # sources.
    assert 'href="/admin/alerts"' not in topbar
    assert topbar.count('href="/admin/health"') >= 2
    assert "SETTINGS_LANDING" in topbar


class _FakeRequest:
    """Just enough Request for _health_rows: it reads app.state.settings."""

    def __init__(self, client):
        self.app = client.app


# ------------------------------------------------- SYS-7: [ WHAT IS RUNNING ]

def test_the_health_page_says_what_is_running_and_who_is_on_it(env):
    """SYS-7 (usability sweep 2026-09-04). The drift doctor is a PowerShell
    script on the base rig, and a second customer has no base rig and no repo,
    so for them it does not exist. This box is the four numbers this server
    already holds, with a verdict."""
    from ccsync_dashboard import VERSION, package_store

    client, conn = env
    dbmod.insert_companion_package(
        conn, version="0.9.60", platform="windows", filename="ccsync-companion-0.9.60.exe",
        sha256="a" * 64, size_bytes=10, published_by="owen",
        now="2026-09-01T10:00:00Z", kind="companion")
    dbmod.set_current_package(conn, "windows", "0.9.60")
    conn.commit()
    running = package_store.what_is_running(conn, client.app.state.settings,
                                            client.app.state)
    assert running["dashboard"]["running"] == VERSION
    windows = [c for c in running["companions"] if c["platform"] == "windows"]
    assert windows and windows[0]["current"] == "0.9.60"
    assert windows[0]["current_published_at"] == "2026-09-01T10:00:00Z"

    page = as_user(client).get("/admin/health")
    assert page.status_code == 200
    assert "[ WHAT IS RUNNING ]" in page.text
    assert "0.9.60" in page.text


def test_the_box_says_not_checked_rather_than_up_to_date(env):
    """A vendor channel nobody has checked is UNKNOWN. The one thing this box
    must never do is render silence as agreement."""
    client, _conn = env
    page = as_user(client).get("/admin/health")
    assert "[ VENDOR: NOT CHECKED ]" in page.text
    assert "the vendor channel has never been checked here" in page.text


def test_the_box_carries_the_reason_this_dashboard_has_not_updated_itself(env):
    """SYS-2: on a bind-mount site the container cannot replace its own code
    at all, and the note the feed poller wrote is the exact command to run."""
    from ccsync_dashboard import release_feed

    client, conn = env
    dbmod.meta_set(conn, release_feed.AUTO_UPDATE_NOTE_KEY,
                   "this deployment updates from your wired computer, not over the "
                   "air: run  tools\\ship.cmd -DashboardOnly  there to update it")
    conn.commit()
    page = as_user(client).get("/admin/health")
    assert "ship.cmd -DashboardOnly" in page.text
