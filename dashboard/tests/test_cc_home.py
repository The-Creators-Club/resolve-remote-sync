"""The terminal home and project pages (UI redesign port phase 2, group
`home`, 2026-09-25).

docs/UI_REDESIGN_PORT_PLAN.md 1.2, 3.1, 5.1, 7.1 row 2, R15. Since
2026-09-25 the terminal look is the only look (the switch, the classic pages
and the variant fixtures are gone): every test asserts the terminal shape,
with every former group on, and htmx requests carry conftest.HX the way a
real page does.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db, ui_home
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from conftest import HX

SECRET = "h" * 32
DASH = Path(__file__).resolve().parents[1]
CC = DASH / "templates"
DEV_OWEN = "OWENAAA-OWENAAA-OWENAAA-OWENAAA-OWENAAA-OWENAAA-OWENAAA-OWENAAA"
SLUG = "2026-ff5-elections"
HOME_FILES = [
    "fleet.html", "project.html", "partials/home_macros.html", "partials/fleet_grid.html",
    "partials/plan_changes.html", "partials/home_transfers.html",
    "partials/home_problems.html",
    "partials/home_queue.html", "partials/home_fix_root.html",
    "partials/computer_answer.html", "partials/projects_tree.html",
    "partials/project_detail.html", "partials/bins.html", "partials/missing_files.html",
    "partials/project_roots.html", "partials/project_roots_browse.html",
]
EM_DASH = chr(0x2014)
BRACKET = re.compile(r"\[ [A-Z][A-Z ,.:'/0-9-]* \]")
HOOKS = ("fleet-grid-wrap", "queue-box", "roots-box")
HOOK_IDS = ("server-notices", "plan-changes", "fleet-diagnostics", "project-detail",
            "media-presence", "roots")


def _cookie(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "Projects"
    (projects / "2026" / "FF5" / "Elections" / "Interviews").mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "home.db"), session_secret=SECRET,
                        report_token="tok", admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = db.connect(tmp_path / "home.db")
        now = db.utcnow_iso()
        pid = db.upsert_project(conn, SLUG, "2026/FF5/Elections", "/x", now)
        db.upsert_project(conn, "2026-ff5-civil", "2026/FF5/Civil Defence", "/y", now)
        for editor, machine in (("owen", "OWEN-LAPTOP"), ("tchen", "TCHEN-PC"),
                                ("tchen", "TCHEN-MBP")):
            db.record_known_editor(conn, editor, "admin")
            db.upsert_machine(conn, editor, machine, now, platform="windows")
            db.upsert_machine_state(conn, editor, machine, None, now, platform="windows",
                                    companion_version="0.9.80",
                                    resolve_project="Elections cut")
        db.add_selection(conn, "owen", SLUG, "admin", now, machine="OWEN-LAPTOP")
        did = db.upsert_device(conn, DEV_OWEN, "owen", False, now)
        db.upsert_completion(conn, pid, did, completion=50.0, need_items=2, need_bytes=10,
                             need_deletes=0, global_items=4, global_bytes=20, now=now)
        db.replace_missing_files(conn, pid, did, [("Audio/interview-01.wav", 1)], False, now)
        kind = db.notice_kinds()[0]["kind"]
        db.notice(conn, kind, "error", subject="probe", body="the probe notice",
                  fix="do the thing", now=now)
        conn.commit()
        yield client, conn
        conn.close()


def _hx(url="http://testserver/"):
    return {**HX, "HX-Current-URL": url}


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: list[str] = []
        self.wins: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        if "win" in (a.get("class") or "").split():
            self.wins.append(a)


def _parse(html: str) -> _Ids:
    p = _Ids()
    p.feed(html)
    return p


# ------------------------------------------------------------ static facts

def test_every_home_template_exists():
    for name in HOME_FILES:
        assert (CC / name).is_file(), name
    # the home grid's own collector went with the switch: it lives on Health (D7)
    assert not (CC / "partials" / "home_collector.html").exists()


@pytest.mark.parametrize("name", HOME_FILES)
def test_no_em_dash_and_no_bracket_control_in_the_terminal_templates(name):
    text = (CC / name).read_text(encoding="utf-8")
    assert EM_DASH not in text
    markup = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    assert not BRACKET.search(markup), BRACKET.search(markup).group(0)


def test_the_home_assets_exist_and_carry_no_em_dash():
    for rel in ("home.css", "home.js"):
        text = (DASH / "static" / "cc" / rel).read_text(encoding="utf-8")
        assert EM_DASH not in text, rel


def test_the_find_box_is_ime_safe_and_nfc():
    js = (DASH / "static" / "cc" / "home.js").read_text(encoding="utf-8")
    assert "isComposing" in js and "compositionend" in js
    assert 'normalize("NFC")' in js and "toLowerCase()" in js


def test_the_file_move_key_reads_computer_and_keeps_its_own_confirm():
    text = (CC / "partials" / "project_detail.html").read_text(encoding="utf-8")
    assert "Move on the server and on every computer" in text
    assert "hx-on::confirm=" in text and "window.confirm(msg)" in text
    assert "EVERY MACHINE" not in text


def test_no_version_behind_and_no_on_since():
    for name in ("partials/fleet_grid.html", "fleet.html"):
        text = (CC / name).read_text(encoding="utf-8")
        assert " behind</" not in text and "on since" not in text


# ------------------------------------------------------------ home

def test_home_draws_the_terminal_look(env):
    client, _conn = env
    page = _cookie(client, "owen").get("/")
    assert page.status_code == 200, page.text[:400]
    html = page.text
    assert 'data-ui="cc"' in html and "cc/home.css" in html
    p = _parse(html)
    dupes = {i for i in p.ids if p.ids.count(i) > 1}
    assert not dupes, dupes
    for w in p.wins:
        cls = (w.get("class") or "").split()
        assert not any(h in cls for h in HOOKS), w
        assert w.get("id", "") not in HOOK_IDS, w
        assert "hx-get" not in w and "hx-post" not in w, w
    for anchor in ("server-notices", "fleet-diagnostics", "home-readouts", "computers-meta"):
        assert p.ids.count(anchor) == 1, anchor
    # the readouts are drawn on first paint, never as an oob fragment
    assert "hx-swap-oob" not in html
    # the tree: real checkboxes, carrying machine and view=tree
    assert 'class="proj-check vh"' in html and "toggle?view=tree" in html
    assert "hx-get=\"/partials/projects-tree?current=" in html


def test_the_problems_readout_agrees_with_the_hud_count(env):
    client, _conn = env
    html = _cookie(client, "owen").get("/").text
    m = re.search(r'id="win-ro-problems".*?<div class="big">(\d+)<small>open', html, re.S)
    hud = re.search(r'class="hud-count" href="/go/notices"[^>]*>.*?<b>(\d+)</b>', html, re.S)
    assert m and hud and m.group(1) == hud.group(1) and int(m.group(1)) >= 1


def test_nothing_ticked_is_never_a_warning_in_the_readouts():
    fleet = {"editors": [
        {"machine": "A", "editor_username": "a", "why": {"reason": "no_selection"},
         "headline": {"reason": "not_reporting", "level": "muted"}},
        {"machine": "B", "editor_username": "b", "why": {"reason": "ok"},
         "headline": {"reason": "ok", "level": "muted"}},
    ]}
    ro = ui_home.home_readouts(None, fleet, {"projects": []})
    online = ro["readouts"][0]
    assert online["k"] == "online" and online["total"] == 1 and online["tone"] != "warn"
    assert "A" not in online["foot"]


def test_a_muted_headline_never_draws_a_warn_lane():
    lane = {"chip": "red", "state": "error", "reported": True}
    assert ui_home.lane_tone(lane, "muted") != "err"
    assert ui_home.lane_tone(lane, "red") == "err"


def test_the_grid_poll_answers_in_the_terminal_look(env):
    client, _conn = env
    _cookie(client, "owen")
    r = client.get("/partials/fleet", headers=_hx())
    assert r.status_code == 200
    assert 'class="pc home-pc' in r.text
    assert 'id="home-readouts" hx-swap-oob="innerHTML"' in r.text
    # the collector lives on Health (D7), never on the home grid
    assert 'id="fleet-collector"' not in r.text
    assert "[ DETAILS ]" not in r.text


def test_the_legal_gap_lines_reach_the_terminal_grid(env):
    """LG-1 / LG-5 carried from the classic grid (2026-09-25): a withheld
    section is a muted tag in the details, and the licence line sits under
    the version. (LG-17, the collector's "retention last ran" line, is on
    Health: test_ui_health_group.py.)"""
    client, conn = env
    conn.execute("UPDATE machine_state SET report_optouts=?, eula_json=? "
                 "WHERE editor_username='tchen' AND machine='TCHEN-PC'",
                 ('["local_manifest"]', '{"version": "1.0", "accepted_at": "2026-09-25T09:00:00+00:00"}'))
    conn.commit()
    _cookie(client, "owen")
    r = client.get("/partials/fleet", headers=_hx())
    assert r.status_code == 200
    assert "eula-line" in r.text
    assert "<dt>reporting</dt>" in r.text
    assert re.search(r'class="tag mute"[^>]*><span class="w">not reported by this computer: FILE LIST</span>', r.text)
    assert "NOT REPORTED BY THIS COMPUTER" not in r.text
    assert not BRACKET.search(re.sub(r"<[^>]+>", "", r.text))


@pytest.mark.parametrize("path", ["/partials/home-problems", "/partials/home-transfers",
                                  "/partials/home-queue", "/partials/computer-answer",
                                  "/partials/projects-tree"])
def test_each_new_named_route_answers_in_the_terminal_look(env, path):
    client, _conn = env
    _cookie(client, "owen")
    r = client.get(path, headers=_hx())
    assert r.status_code == 200, r.text[:300]
    assert "admin-users-box" not in r.text and "[ " not in r.text


def test_computer_answer_every_computer_link_targets_its_own_route(env):
    client, _conn = env
    _cookie(client, "owen")
    r = client.get("/partials/computer-answer?editor=owen&machine=OWEN-LAPTOP",
                   headers=_hx())
    assert r.status_code == 200
    assert "/partials/admin/diagnostics" not in r.text


def test_a_dismiss_from_problems_answers_with_the_problems_window(env):
    client, conn = env
    _cookie(client, "owen")
    nid = conn.execute("SELECT id FROM notices WHERE subject = 'probe'").fetchone()["id"]
    body = client.get("/partials/home-problems", headers=_hx()).text
    assert f"/partials/notices/{nid}/dismiss?view=home-problems" in body
    r = client.post(f"/partials/notices/{nid}/dismiss?view=home-problems",
                    headers={**_hx(), "X-CSRF-Token": _csrf(client)})
    assert r.status_code == 200, r.text[:300]
    assert "admin-users-box" not in r.text and "what the server checks" in r.text


def _csrf(client) -> str:
    import hashlib
    import hmac
    sid = auth.session_id_for(SECRET, client.cookies.get(auth.COOKIE_NAME))
    return hmac.new(SECRET.encode(), b"csrf|" + sid.encode(), hashlib.sha256).hexdigest()


def test_a_tick_from_the_tree_answers_with_the_tree_for_that_computer(env):
    client, _conn = env
    _cookie(client, "owen")
    url = ("/partials/selection/tchen/2026-ff5-civil/toggle?view=tree&machine=TCHEN-PC"
           "&as=tchen")
    r = client.post(url, headers={**_hx(), "X-CSRF-Token": _csrf(client)})
    assert r.status_code == 200, r.text[:300]
    assert 'class="tree-count"' in r.text and "proj-check" in r.text
    assert "machine=TCHEN-PC" in r.text
    assert re.search(r'data-name="2026/FF5/Civil Defence".*?checked', r.text, re.S) or \
        "checked" in r.text
    # the poll as that person and computer keeps showing their tick
    poll = client.get("/partials/projects-tree?current=&machine=TCHEN-PC&as=tchen",
                      headers=_hx())
    assert poll.status_code == 200, poll.text[:300]
    assert re.search(r'toggle\?view=tree&amp;machine=TCHEN-PC[^"]*as=tchen', poll.text), \
        re.findall(r'hx-post="[^"]*"', poll.text)[:2]


def test_an_untick_from_the_home_queue_answers_with_the_home_queue(env):
    client, _conn = env
    _cookie(client, "owen")
    r = client.post(f"/partials/selection/owen/{SLUG}/toggle?view=home-queue",
                    headers={**_hx(), "X-CSRF-Token": _csrf(client)})
    assert r.status_code == 200, r.text[:300]
    assert "fix destination root" in r.text and "queue-box" not in r.text


def test_plan_changes_always_answers_with_its_target(env):
    client, _conn = env
    _cookie(client, "owen")
    r = client.get("/partials/plan-changes", headers=_hx())
    assert r.status_code == 200
    assert r.text.count('id="plan-changes"') == 1
    assert "[ UNDO ]" not in r.text


# ------------------------------------------------------------ project

def test_the_project_page_draws_the_terminal_look(env):
    client, _conn = env
    page = _cookie(client, "owen").get(f"/project/{SLUG}")
    assert page.status_code == 200, page.text[:400]
    html = page.text
    assert 'data-ui="cc"' in html
    p = _parse(html)
    dupes = {i for i in p.ids if p.ids.count(i) > 1}
    assert not dupes, dupes
    for w in p.wins:
        assert w.get("id", "") not in HOOK_IDS, w
        assert "hx-get" not in w and "hx-post" not in w, w
    assert 'id="project-detail"' in html and 'id="roots"' in html
    assert f'id="missing-{DEV_OWEN}" hx-preserve="true"' in html
    assert "toggle?view=project" in html and 'hx-target="#project-detail"' in html
    assert "Move on the server and on every computer" in html


@pytest.mark.parametrize("path", [f"/partials/project/{SLUG}", f"/partials/project/{SLUG}/bins",
                                  f"/partials/project/{SLUG}/missing/{DEV_OWEN}",
                                  "/partials/project-roots",
                                  "/partials/project-roots/browse?resolve_project=Elections%20cut&rel=2026"])
def test_the_project_partials_answer_in_the_terminal_look(env, path):
    client, _conn = env
    _cookie(client, "owen")
    r = client.get(path, headers=_hx(f"http://testserver/project/{SLUG}"))
    assert r.status_code == 200, r.text[:300]
    markup = re.sub(r"<!--.*?-->", "", r.text, flags=re.S)
    assert not BRACKET.search(markup), BRACKET.search(markup).group(0)
