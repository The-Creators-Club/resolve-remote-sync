"""Admins ticking projects for another editor, from the UI.

The ?as=<editor> focus existed before this, but only as a URL an admin had to
type by hand -- and the sidebar's 30s refresh dropped it, so the checkboxes
reverted to the admin's own ticks while still looking like the other editor's.
The next click then ticked the project onto the ADMIN'S machine. These cover
the switcher control and the propagation that makes it trustworthy.
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
                        admin_users=frozenset({"alex"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "sw.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, FF5, "2026/FF5/Elections", f"/data/{FF5}", now)
        dbmod.upsert_project(conn, DRONE, "2026/Base Drone", f"/data/{DRONE}", now)
        for name in ("leso", "jsmith"):
            dbmod.record_known_editor(conn, name, source="admin", now=now)
        conn.commit()
        yield client, conn
        conn.close()


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def checkbox_for(body: str, slug: str) -> str:
    """The sidebar <input> tag for `slug` -- it spans several lines, so this
    matches the whole tag rather than a line."""
    for tag in re.findall(r"<input[^>]*>", body, re.S):
        if "proj-check" in tag and f"/{slug}/toggle" in tag:
            return tag
    return ""


def test_switcher_offers_editors_to_admins_only(env):
    client, _ = env
    as_user(client, "alex")
    body = client.get("/").text
    assert "[ TICKING FOR ]" in body
    assert '<option value="leso"' in body
    assert '<option value="jsmith"' in body
    # the admin's own name is the empty-value "me" option, not a duplicate row
    assert '<option value="alex"' not in body

    as_user(client, "jsmith")
    body = client.get("/").text
    assert "[ TICKING FOR ]" not in body
    assert '<option value="leso"' not in body


def test_as_focus_binds_the_checkboxes_to_that_editor(env):
    client, conn = env
    dbmod.add_selection(conn, "leso", FF5, created_by="leso", now=dbmod.utcnow_iso())
    conn.commit()
    as_user(client, "alex")

    body = client.get("/?as=leso").text
    # posts go to leso's toggle path, and leso's existing tick renders checked
    assert f"/partials/selection/leso/{FF5}/toggle" in body
    assert f"/partials/selection/alex/{FF5}/toggle" not in body
    assert "acting as" in body
    assert "checked" in checkbox_for(body, FF5)
    assert "checked" not in checkbox_for(body, DRONE)


def test_sidebar_refresh_keeps_the_focus(env):
    """Regression: the every-30s refresh used to drop ?as=."""
    client, _ = env
    as_user(client, "alex")
    body = client.get("/?as=leso").text
    # &amp; is Jinja autoescaping inside the attribute; htmx decodes it
    assert 'hx-get="/partials/sidebar?current=&amp;as=leso"' in body

    # and the refresh endpoint itself honours it
    refreshed = client.get("/partials/sidebar?current=&as=leso").text
    assert f"/partials/selection/leso/{FF5}/toggle" in refreshed
    assert f"/partials/selection/alex/{FF5}/toggle" not in refreshed


def test_admin_tick_lands_on_the_target_editor(env):
    client, conn = env
    as_user(client, "alex")
    r = client.post(
        f"/partials/selection/leso/{FF5}/toggle?view=sidebar&as=leso")
    assert r.status_code == 200
    assert [s["slug"] for s in dbmod.fetch_selections(conn, "leso")] == [FF5]
    assert dbmod.fetch_selections(conn, "alex") == []
    # the fragment that comes back is still leso's, not the admin's
    assert f"/partials/selection/leso/{FF5}/toggle" in r.text
    assert f"/partials/selection/alex/{FF5}/toggle" not in r.text

    # created_by records who really did it
    row = conn.execute(
        "SELECT created_by FROM selections WHERE editor_username='leso'").fetchone()
    assert row[0] == "alex"


def test_project_page_tick_button_follows_the_focus(env):
    client, _ = env
    as_user(client, "alex")
    body = client.get(f"/project/{FF5}?as=leso").text
    assert "[ TICK FOR LESO ]" in body
    assert "[ TICK FOR ME ]" not in body
    assert f'hx-post="/partials/selection/leso/{FF5}/toggle' in body
    # the 10s detail refresh keeps the focus too
    assert f'hx-get="/partials/project/{FF5}?as=leso"' in body

    body = client.get(f"/project/{FF5}").text
    assert "[ TICK FOR ME ]" in body


def test_non_admin_cannot_borrow_another_queue(env):
    client, conn = env
    as_user(client, "jsmith")
    # ?as= is ignored for non-admins: the checkboxes stay their own
    body = client.get("/?as=leso").text
    assert f"/partials/selection/jsmith/{FF5}/toggle" in body
    assert f"/partials/selection/leso/{FF5}/toggle" not in body
    # and the toggle itself is refused server-side
    assert client.post(f"/partials/selection/leso/{FF5}/toggle").status_code == 403
    assert dbmod.fetch_selections(conn, "leso") == []
