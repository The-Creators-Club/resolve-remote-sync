"""The terminal everyday pages (UI redesign port phase 3, group `everyday`,
2026-09-25): transfers, project setup, installer, sign in, help and the
account page restyle, plus the person queue and the `view=none` answers.

docs/UI_REDESIGN_PORT_PLAN.md 1.2, 3.1, 5.1, 7.1 row 3, R15. Since
2026-09-25 the terminal look is the only look (the switch, the classic pages
and the `ui_variant` fixture are gone), so every test asserts the terminal
shape, and htmx requests carry conftest.HX the way a real page does.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from conftest import HX

SECRET = "e" * 32
DASH = Path(__file__).resolve().parents[1]
CC = DASH / "templates"
EVERYDAY_FILES = [
    "transfers.html", "partials/transfers.html", "project_setup.html",
    "partials/project_setup_panel.html", "installer.html", "login.html", "help.html",
    "account.html", "partials/account_you.html", "partials/account_password.html",
    "partials/account_computer.html", "partials/account_jobs.html",
    "partials/account_sessions.html", "partials/account_sync_keys.html",
    "partials/account_result.html", "partials/person_queue.html",
    "partials/person_fix_root.html", "partials/ev_macros.html",
]
EM_DASH = chr(0x2014)
BRACKET = re.compile(r"\[ [A-Z][A-Z ,.:'/0-9-]* \]")


def _cookie(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "Projects"
    (projects / "2026" / "FF5").mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "ev.db"), session_secret=SECRET,
                        report_token="tok", admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = db.connect(tmp_path / "ev.db")
        now = db.utcnow_iso()
        db.upsert_project(conn, "2026-ff5-elections", "2026/FF5/Elections", "/x", now)
        db.upsert_project(conn, "2026-ff5-civil", "2026/FF5/Civil Defence", "/y", now)
        for editor, machine in (("owen", "OWEN-LAPTOP"), ("tchen", "TCHEN-PC")):
            db.record_known_editor(conn, editor, "admin")
            db.upsert_machine(conn, editor, machine, now, platform="windows")
            db.upsert_machine_state(conn, editor, machine, None, now, platform="windows",
                                    companion_version="0.9.80",
                                    resolve_project="Elections cut")
            db.add_selection(conn, editor, "2026-ff5-elections", "admin", now,
                             machine=machine)
        conn.commit()
        yield client, conn
        conn.close()


def _hx(url="http://testserver/account"):
    return {**HX, "HX-Current-URL": url}


# ------------------------------------------------------------ static facts

def test_every_everyday_template_exists():
    for name in EVERYDAY_FILES:
        assert (CC / name).is_file(), name


@pytest.mark.parametrize("name", EVERYDAY_FILES)
def test_no_em_dash_and_no_bracket_control_in_the_terminal_templates(name):
    text = (CC / name).read_text(encoding="utf-8")
    assert EM_DASH not in text
    # Comments may cite the classic labels they replace; the markup may not.
    markup = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    assert not BRACKET.search(markup), BRACKET.search(markup).group(0)


def test_the_everyday_assets_exist_and_carry_no_em_dash():
    for rel in ("everyday.css", "everyday.js", "account.js"):
        text = (DASH / "static" / "cc" / rel).read_text(encoding="utf-8")
        assert EM_DASH not in text, rel


def test_the_terminal_account_script_asks_for_an_empty_answer():
    js = (DASH / "static" / "cc" / "account.js").read_text(encoding="utf-8")
    assert "/toggle?view=none&machine=" in js
    # the classic script went with the classic page (2026-09-25)
    assert not (DASH / "static" / "account.js").exists()


# ------------------------------------------------------------ the pages

@pytest.mark.parametrize("path", ["/transfers", "/installer", "/help", "/account",
                                  "/project-setup?resolve_project=Elections%20cut"])
def test_each_page_draws_the_terminal_look(env, path):
    client, _conn = env
    page = _cookie(client, "owen").get(path)
    assert page.status_code == 200, page.text[:300]
    assert 'data-ui="cc"' in page.text
    assert "cc/everyday.css" in page.text
    assert 'class="win' in page.text and 'class="fold"' in page.text
    # D17: no classic projects sidebar on an everyday page
    assert 'class="sidebar"' not in page.text
    assert not BRACKET.search(re.sub(r"<!--.*?-->", "", page.text, flags=re.S)) or \
        "[ " not in page.text.split('class="shell"', 1)[-1].split("hint-sheet", 1)[0]


def test_the_signed_out_sign_in_page(env):
    client, _conn = env
    page = client.get("/login")
    assert page.status_code == 200
    assert "ev-gate" in page.text
    assert 'name="username"' in page.text and 'name="password"' in page.text
    # there is no other look to go back to (2026-09-25)
    assert "/ui/preview" not in page.text
    assert "classic" not in page.text.lower()
    assert 'class="hud' not in page.text


def test_transfers_poll_selects_ids_every_state_renders(env):
    client, _conn = env
    page = _cookie(client, "owen").get("/transfers").text
    m = re.search(r'hx-select-oob="([^"]+)"', page)
    assert m, "the terminal transfers page polls with hx-select-oob"
    ids = [part.split(":")[0].lstrip("#") for part in m.group(1).split(",")]
    frag = client.get("/partials/transfers",
                      headers=_hx("http://testserver/transfers")).text
    for i in ids:
        assert f'id="{i}"' in page, i
        assert f'id="{i}"' in frag, i
    # the fragment is the terminal one, not the classic panel
    assert "[ LIVE ]" not in frag


def test_the_account_page_keeps_every_classic_hook(env):
    client, _conn = env
    page = _cookie(client, "tchen").get("/account").text
    for hook in ('id="account-you"', 'id="account-pw-form"', 'id="account-pw-result"',
                 'id="account-sessions-wrap"', "/partials/account/sessions",
                 "/partials/account/sync-keys", "account-refresh", "TCHEN-PC"):
        assert hook in page, hook
    assert "cc/account.js" in page
    assert "/static/account.js" not in page
    assert "/partials/person-queue" in page
    # the swap-none buttons ask for an empty answer (R15)
    assert "toggle?view=none&amp;machine=TCHEN-PC" in page
    # the computer's frame is static: its poll takes only the body
    assert 'hx-select-oob="#' in page and '-body:outerHTML"' in page


def test_account_partials_answer_in_the_terminal_look(env):
    client, _conn = env
    _cookie(client, "owen")
    h = _hx()
    pc = client.get("/partials/account/computer?machine=OWEN-LAPTOP", headers=h)
    assert pc.status_code == 200 and "OWEN-LAPTOP" in pc.text
    sess = client.get("/partials/account/sessions", headers=h)
    keys = client.get("/partials/account/sync-keys", headers=h)
    name = client.post("/partials/account/display-name", data={"display_name": "Owen B"},
                       headers=h)
    pw = client.post("/partials/account/password",
                     data={"current_password": "x", "new_password": "short",
                           "new_password_again": "short"}, headers=h)
    jobs = client.post("/partials/account/machines/settings",
                       data={"editor": "owen", "machine": "OWEN-LAPTOP",
                             "jobs_enabled": ["0", "1"]}, headers=h)
    for resp in (sess, keys, name, pw, jobs):
        assert resp.status_code == 200, resp.text[:300]
    assert '-body"' in pc.text
    assert 'class="win acct-pc' in pc.text
    assert "[ " not in sess.text
    assert 'class="note' in pw.text
    assert 'id="account-you"' in name.text and "Owen B" in name.text
    assert "[ SAVE ]" not in name.text


def test_the_legal_gap_controls_reach_the_account_page(env):
    """LG-1 / LG-2 / LG-5 carried from the classic partials (2026-09-25): the
    licence line and the not-reported tags on a computer, and the person's
    own download, a plain POST form carrying the CSRF field."""
    client, conn = env
    conn.execute("UPDATE machine_state SET report_optouts=?, eula_json=? "
                 "WHERE editor_username='tchen' AND machine='TCHEN-PC'",
                 ('["input_idle"]', '{"version": "1.0", "accepted_at": "2026-09-25T09:00:00+00:00"}'))
    conn.commit()
    page = _cookie(client, "tchen").get("/account").text
    assert "<dt>licence</dt>" in page and "eula-line" in page
    assert "<dt>not reported</dt>" in page
    assert 'action="/api/v1/me/export"' in page and 'name="csrf"' in page
    assert re.search(r'<span class="tag mute" title="[^"]*">IDLE TIME</span>', page)
    assert '<span class="t">Download</span>' in page
    assert "[ DOWNLOAD ]" not in page and "[ IDLE TIME ]" not in page


def test_the_person_queue(env):
    client, _conn = env
    _cookie(client, "owen")
    resp = client.get("/partials/person-queue", headers=_hx())
    assert resp.status_code == 200
    assert "2026/FF5/Elections" in resp.text
    assert "toggle?view=person-queue" in resp.text
    assert 'data-machine="OWEN-LAPTOP"' in resp.text      # its fix root
    assert "Elections cut" in resp.text


def test_an_untick_from_the_person_queue_gets_the_person_queue_back(env):
    client, conn = env
    _cookie(client, "owen")
    resp = client.post("/partials/selection/owen/2026-ff5-elections/toggle?view=person-queue",
                       headers=_hx())
    assert resp.status_code == 200
    assert "Nothing ticked" in resp.text
    assert "led off" in resp.text and "note err" not in resp.text
    assert not [s for s in db.fetch_selections(conn, "owen")
                if s["slug"] == "2026-ff5-elections"]


@pytest.mark.parametrize("url", [
    "/partials/selection/owen/2026-ff5-civil/toggle?view=none&machine=OWEN-LAPTOP&mode=upload_only",
    "/partials/admin/machines/ask-why?view=none",
    "/partials/admin/machines/update?view=none",
])
def test_the_account_swap_none_writes_answer_empty(env, url):
    client, _conn = env
    _cookie(client, "owen")
    resp = client.post(url, data={"editor": "owen", "machine": "OWEN-LAPTOP"},
                       headers=_hx())
    assert resp.status_code == 200, resp.text[:300]
    assert resp.text == ""
    assert "hx-swap-oob" not in resp.text
