"""Self-tests of the `ui_variant` fixture and its coverage recorder (UI port
phase 0, R11). A fixture that silently rendered classic under every
parameter would make every terminal assertion built on it vacuous."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import ui_variant as uv
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "f" * 32


@pytest.fixture
def client(tmp_path, ui_variant):
    app = create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                              admin_users=frozenset({"owen"})))
    with TestClient(app) as c:
        yield c


def test_an_editor_page_carries_the_parameters_set(client, ui_variant):
    """File-local create_app, an EDITOR session: the setting seam alone must
    decide the look (a cc cookie from a non-admin is read as absent)."""
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    page = client.get("/")
    assert page.status_code == 200
    ui_variant.check_page(page.text)
    if ui_variant.name == "all" and uv.build_groups():
        assert ui_variant.page_groups(page.text) != ""


def test_its_htmx_headers_are_honoured(client, ui_variant):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    r = client.get("/partials/stamp", headers=ui_variant.htmx_headers(client))
    assert r.status_code == 200
    assert "hx-refresh" not in r.headers


def test_a_classic_render_records_no_coverage(client, ui_variant):
    if not ui_variant.is_classic:
        pytest.skip("the classic parameter only")
    before = set(uv.RENDERED_CC_FILES)
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    client.get("/")
    assert uv.RENDERED_CC_FILES == before


def test_a_terminal_render_records_the_files_it_included(client, ui_variant):
    """Include-only partials count: the recorder sees every {% include %}."""
    if "chrome" not in ui_variant.groups:
        pytest.skip("needs chrome in this build and this parameter")
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    client.get("/")
    assert "cc/partials/topbar.html" in uv.RENDERED_CC_FILES
