"""The admin assignment matrix (/admin/assignments, 2026-08-17): projects x
editors in one grid, each cell a checkbox that writes through the SAME
PUT/DELETE /api/v1/selection/{editor}/{slug} the ?as= editor switcher's
checkboxes use -- see assignments.py's module docstring. These tests pin
that the matrix is admin-only, that its cells mean exactly what an editor's
own tick means (compared directly against test_admin_tick_for_editor.py's
?as= behaviour), and that a non-admin still cannot write another editor's
selection through the underlying route.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"

FF5 = "2026-ff5-elections"
DRONE = "2026-base-drone"


@pytest.fixture
def env(tmp_path):
    settings = Settings(db_path=str(tmp_path / "sw.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "sw.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, FF5, "2026/FF5/Elections", f"/data/{FF5}", now)
        dbmod.upsert_project(conn, DRONE, "2026/Base Drone", f"/data/{DRONE}", now)
        for name in ("editor1", "jsmith"):
            dbmod.record_known_editor(conn, name, source="admin", now=now)
        conn.commit()
        yield client, conn
        conn.close()


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def matrix_checkbox(body: str, slug: str, editor: str) -> str:
    for tag in re.findall(r"<input[^>]*>", body, re.S):
        if ("matrix-check" in tag and f'data-slug="{slug}"' in tag
                and f'data-editor="{editor}"' in tag):
            return tag
    return ""


# --------------------------------------------------------------- page gate


def test_assignments_page_requires_admin(env):
    client, _ = env
    # anonymous -> redirected to login (page route), never a bare 200
    resp = client.get("/admin/assignments", follow_redirects=False)
    assert resp.status_code in (302, 303, 307, 401)

    as_user(client, "jsmith")   # signed in, not an admin
    resp = client.get("/admin/assignments")
    assert resp.status_code == 403

    as_user(client, "owen")     # admin
    resp = client.get("/admin/assignments")
    assert resp.status_code == 200
    assert "[ ASSIGNMENTS ]" in resp.text


def test_grid_renders_projects_editors_and_existing_ticks(env):
    client, conn = env
    dbmod.add_selection(conn, "editor1", FF5, created_by="editor1", now=dbmod.utcnow_iso())
    conn.commit()
    as_user(client, "owen")

    body = client.get("/admin/assignments").text
    assert "2026/FF5/Elections" in body
    assert "2026/Base Drone" in body
    assert "editor1" in body and "jsmith" in body

    ticked = matrix_checkbox(body, FF5, "editor1")
    assert ticked and "checked" in ticked
    unticked = matrix_checkbox(body, DRONE, "editor1")
    assert unticked and "checked" not in unticked
    # jsmith never ticked anything -- their column starts empty
    assert "checked" not in matrix_checkbox(body, FF5, "jsmith")

    # real checkbox markup, not a div stand-in (style.css restyles the
    # element, it does not replace it)
    assert '<input type="checkbox"' in ticked


def test_admin_never_gets_a_self_column_by_accident(env):
    """The admin has no selections, no known_editors row and no companion
    report -- so 'owen' must not appear as a column just because they are
    signed in as the viewer."""
    client, _ = env
    as_user(client, "owen")
    body = client.get("/admin/assignments").text
    assert 'data-editor="owen"' not in body


# ------------------------------------------------- cell writes == ?as= flow


def test_cell_toggle_is_the_same_write_the_as_flow_makes(env):
    """No new selection store: ticking editor1's cell in the matrix must
    change EXACTLY what POST /partials/selection/editor1/{slug}/toggle (the
    ?as= flow, see test_admin_tick_for_editor.py) would have changed."""
    client, conn = env
    as_user(client, "owen")

    # the matrix cell calls PUT directly (assignments.js), acting as admin
    r = client.put(f"/api/v1/selection/editor1/{FF5}")
    assert r.status_code == 200
    assert [s["slug"] for s in dbmod.fetch_selections(conn, "editor1")] == [FF5]
    assert dbmod.fetch_selections(conn, "owen") == []
    # created_by still records the admin who actually clicked it, exactly
    # like the ?as= toggle route does
    row = conn.execute(
        "SELECT created_by FROM selections WHERE editor_username='editor1'"
    ).fetchone()
    assert row[0] == "owen"

    # unticking the same cell (DELETE, what a click on a checked box sends)
    r = client.delete(f"/api/v1/selection/editor1/{FF5}")
    assert r.status_code == 200
    assert dbmod.fetch_selections(conn, "editor1") == []


def test_grid_reflects_a_tick_made_through_the_as_switcher(env):
    """The inverse: a tick made the OLD way (?as=) shows up ticked in the
    matrix -- one selection table, viewed two ways."""
    client, conn = env
    as_user(client, "owen")
    client.post(f"/partials/selection/editor1/{FF5}/toggle?as=editor1")
    assert [s["slug"] for s in dbmod.fetch_selections(conn, "editor1")] == [FF5]

    body = client.get("/admin/assignments").text
    assert "checked" in matrix_checkbox(body, FF5, "editor1")


# --------------------------------------------------------------- isolation


def test_non_admin_cannot_write_another_editors_selection(env):
    """Scope isolation the matrix relies on: nothing about this page loosens
    the underlying route's rule that only self-or-admin may PUT/DELETE a
    selection."""
    client, conn = env
    as_user(client, "jsmith")
    resp = client.put(f"/api/v1/selection/editor1/{FF5}")
    assert resp.status_code == 403
    assert dbmod.fetch_selections(conn, "editor1") == []

    # jsmith may still act on their own selection
    resp = client.put(f"/api/v1/selection/jsmith/{FF5}")
    assert resp.status_code == 200


def test_unknown_editor_in_url_is_not_silently_created(env):
    """Typing/crafting a name that has never touched the system: the write
    still goes through can_manage() and add_selection() untouched by this
    page, so it behaves exactly as it always has (accepted for an admin --
    known_editor_usernames just won't show a column for them until they
    show real evidence)."""
    client, conn = env
    as_user(client, "owen")
    resp = client.put(f"/api/v1/selection/ghost/{FF5}")
    assert resp.status_code == 200
    assert [s["slug"] for s in dbmod.fetch_selections(conn, "ghost")] == [FF5]
