"""The home and project findings of the UI port review (docs/UI_PORT_REVIEW_2026-09-25.md,
home-project-1 to -11), fixed 2026-09-25 by fix builder F-home.

The terminal look replaced the classic one outright (owner, 2026-09-25): it
is the only look, so these tests run a plain app, and htmx requests carry
conftest.HX the way a real page does.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db, ui_home
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from conftest import HX

SECRET = "f" * 32
DASH = Path(__file__).resolve().parents[1]
CC_T = DASH / "templates"
CC_S = DASH / "static" / "cc"
SLUG = "2026-ff5-elections"
CIVIL = "2026-ff5-civil"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _strip_css_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _media_blocks(css: str, query_part: str) -> list[str]:
    """The bodies of every @media block whose query contains `query_part`."""
    out = []
    for m in re.finditer(r"@media([^{]*)\{", css):
        if query_part not in m.group(1):
            continue
        depth, i = 1, m.end()
        while depth and i < len(css):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append(css[m.end():i - 1])
    return out


# ------------------------------------------------------------ the app


def _hx(client, url="http://testserver/") -> dict:
    return {**HX, "HX-Current-URL": url}


def _csrf(client) -> str:
    sid = auth.session_id_for(SECRET, client.cookies.get(auth.COOKIE_NAME))
    return hmac.new(SECRET.encode(), b"csrf|" + sid.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "Projects"
    (projects / "2026" / "FF5" / "Elections").mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "home.db"), session_secret=SECRET,
                        report_token="tok", admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = db.connect(tmp_path / "home.db")
        now = db.utcnow_iso()
        db.upsert_project(conn, SLUG, "2026/FF5/Elections", "/x", now)
        db.upsert_project(conn, CIVIL, "2026/FF5/Civil Defence", "/y", now)
        for editor, machine in (("owen", "OWEN-LAPTOP"), ("jsmith", "JSMITH-STUDIO")):
            db.record_known_editor(conn, editor, "admin")
            db.upsert_machine(conn, editor, machine, now, platform="windows")
            db.upsert_machine_state(conn, editor, machine, None, now, platform="windows",
                                    companion_version="0.9.80")
        db.add_selection(conn, "jsmith", SLUG, "admin", now, machine="JSMITH-STUDIO")
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield client, conn
        conn.close()


def _ticked(conn, editor, slug) -> bool:
    return conn.execute("SELECT 1 FROM selections WHERE editor_username=? AND project_slug=?",
                        (editor, slug)).fetchone() is not None


def _post(client, url, page="http://testserver/"):
    return client.post(url, headers={**_hx(client, page), "X-CSRF-Token": _csrf(client)})


# ------------------------------------------------------------ home-project-1


def test_hp1_no_table_row_carries_the_off_canvas_drawer_class():
    """components.css's `.drawer` is the fixed, full-screen side sheet. A
    `<tr class="drawer">` was hidden on desktop and, on a phone, a 390 x 844
    opaque box over the project page. Row drawers are `row-drawer` now."""
    for path in CC_T.rglob("*.html"):
        for m in re.finditer(r"<tr\b[^>]*\bclass=\"([^\"]*)\"", _read(path)):
            assert "drawer" not in m.group(1).split(), (path.name, m.group(0))
    for name in ("components.css", "phone.css", "home.css"):
        css = _strip_css_comments(_read(CC_S / name))
        assert not re.search(r"\btr\.drawer\b", css), name
    # the off-canvas sheet rule is still what it was: fixed and full height
    comp = _strip_css_comments(_read(CC_S / "components.css"))
    assert re.search(r"(?m)^\.drawer \{[^}]*position: fixed", comp)


def test_hp1_the_project_page_draws_row_drawers(env):
    client, conn = env
    did = db.upsert_device(conn, "D" * 56, "jsmith", False, db.utcnow_iso())
    pid = conn.execute("SELECT id FROM projects WHERE slug=?", (SLUG,)).fetchone()["id"]
    db.upsert_completion(conn, pid, did, completion=50.0, need_items=1, need_bytes=1,
                         need_deletes=0, global_items=2, global_bytes=2, now=db.utcnow_iso())
    conn.commit()
    html = client.get(f"/project/{SLUG}").text
    assert 'class="row-drawer"' in html
    assert '<tr class="drawer"' not in html


# ------------------------------------------------------------ home-project-2


def test_hp2_the_tree_and_the_queue_send_the_state_they_mean(env):
    client, _conn = env
    html = client.get("/?as=jsmith&machine=JSMITH-STUDIO").text
    posts = re.findall(r'hx-post="(/partials/selection/jsmith/[^"]*toggle\?view=tree[^"]*)"', html)
    by_slug = {re.search(r"jsmith/([^/]+)/toggle", p).group(1): p for p in posts}
    assert "mode=off" in by_slug[SLUG], by_slug[SLUG]       # ticked: the key unticks
    assert "mode=on" in by_slug[CIVIL], by_slug[CIVIL]      # unticked: the key ticks
    q = re.findall(r'hx-post="([^"]*toggle\?view=home-queue[^"]*)"', html)
    assert q and all("mode=off" in u for u in q), q


def test_hp2_a_stale_untick_after_a_queue_untick_is_a_no_op_never_a_tick(env):
    """The review's scenario: untick in sync_queue, then the tree row (still
    drawn ticked) is unticked too. It used to send a blind toggle that ticked
    the project back on."""
    client, conn = env
    base = f"/partials/selection/jsmith/{SLUG}/toggle"
    r = _post(client, f"{base}?view=home-queue&mode=off&as=jsmith")
    assert r.status_code == 200, r.text[:300]
    assert not _ticked(conn, "jsmith", SLUG)
    audits = conn.execute("SELECT COUNT(*) FROM fleet_audit").fetchone()[0] \
        if conn.execute("SELECT name FROM sqlite_master WHERE name='fleet_audit'").fetchone() else None
    # the stale tree row: drawn ticked, so it asks for OFF
    r = _post(client, f"{base}?view=tree&mode=off&machine=JSMITH-STUDIO&as=jsmith")
    assert r.status_code == 200, r.text[:300]
    assert not _ticked(conn, "jsmith", SLUG), "a confirmed removal ticked the project back"
    if audits is not None:
        assert conn.execute("SELECT COUNT(*) FROM fleet_audit").fetchone()[0] == audits
    # and the answer is the truth: the row is drawn unticked
    row = re.search(r'data-name="2026/FF5/Elections".*?</label>', r.text, re.S).group(0)
    assert "checked" not in row.replace("proj-check", "")


def test_hp2_a_stale_tick_on_a_ticked_project_keeps_its_mode(env):
    client, conn = env
    conn.execute("UPDATE selections SET sync_mode=? WHERE editor_username='jsmith'",
                 (db.SYNC_MODE_UPLOAD_ONLY,))
    conn.commit()
    r = _post(client, f"/partials/selection/jsmith/{SLUG}/toggle?view=tree&mode=on"
                      "&machine=JSMITH-STUDIO&as=jsmith")
    assert r.status_code == 200, r.text[:300]
    rows = conn.execute("SELECT sync_mode FROM selections WHERE editor_username='jsmith'").fetchall()
    assert [x["sync_mode"] for x in rows] == [db.SYNC_MODE_UPLOAD_ONLY]
    # a real tick still ticks
    r = _post(client, f"/partials/selection/jsmith/{CIVIL}/toggle?view=tree&mode=on"
                      "&machine=JSMITH-STUDIO&as=jsmith")
    assert r.status_code == 200 and _ticked(conn, "jsmith", CIVIL)


def test_hp2_every_plan_answer_tells_the_sibling_windows_to_re_read(env):
    client, _conn = env
    base = f"/partials/selection/jsmith/{CIVIL}/toggle"
    for url in (f"{base}?view=tree&mode=on&machine=JSMITH-STUDIO&as=jsmith",
                f"{base}?view=home-queue&mode=off&as=jsmith",
                f"{base}?view=project&mode=on&slug_page={CIVIL}&as=jsmith"):
        r = _post(client, url)
        assert r.status_code == 200, (url, r.text[:300])
        assert r.headers.get("HX-Trigger") == ui_home.PLAN_CHANGED, url
    home = client.get("/?as=jsmith").text
    for cls in ("tree-body", "queue-box"):
        tag = re.search(r'<div class="[^"]*\b' + cls + r'\b[^>]*>', home).group(0)
        assert "cc-plan-changed from:body" in tag, tag
    proj = client.get(f"/project/{SLUG}?as=jsmith").text
    tag = re.search(r'<div id="project-detail"[^>]*>', proj).group(0)
    assert "cc-plan-changed from:body" in tag
    # a re-read on that event is a poll: it must never unfold a folded window
    js = _read(CC_S / "cc.js")
    assert re.search(r'POLL_EVENTS = \{ "cc-plan-changed": 1 \}', js)
    assert "POLL_EVENTS[trig.type]" in js


def test_hp2_the_project_page_keys_send_the_state_they_mean(env):
    client, _conn = env
    html = client.get(f"/project/{SLUG}?as=jsmith").text
    main = re.search(r'hx-post="([^"]*toggle\?view=project[^"]*)"[^>]*\s+data-confirm-key="project-tick', html)
    assert main and "mode=off" in main.group(1), main and main.group(1)
    html = client.get(f"/project/{CIVIL}?as=jsmith").text
    main = re.search(r'hx-post="([^"]*toggle\?view=project[^"]*)"[^>]*\s+data-confirm-key="project-tick', html)
    assert main and "mode=on" in main.group(1), main and main.group(1)


# ------------------------------------------------------------ home-project-3


def test_hp3_cancelling_a_confirm_puts_a_checkbox_back():
    js = _read(CC_S / "cc.js")
    close = re.search(r'dialog\.addEventListener\("close", function \(\) \{(.*?)\n    \}\);', js, re.S)
    assert close, "the confirm dialog's close handler moved"
    body = close.group(1)
    assert 'p.elt.type === "checkbox"' in body
    assert "p.elt.checked = !p.elt.checked" in body
    # OK clears `pending` before it closes, so the restore is Cancel/Escape only
    ok = re.search(r"function onOk\(\) \{(.*?)\n  \}", js, re.S).group(1)
    assert ok.index("pending = null") < ok.index("closeDialog()")


# ------------------------------------------------------------ home-project-4


def _row(machine, *, plan=None, why="ok", headline="ok", status_reason="", mode="editor",
         received_at="2026-09-25T00:00:00+00:00"):
    row = {"machine": machine, "editor_username": machine.lower(), "why": {"reason": why},
           "headline": {"reason": headline, "level": "red" if headline != "ok" else "muted"},
           "status_reason": status_reason, "received_at": received_at, "lanes": [],
           "status": "amber", "mode": mode}
    if plan is not None:
        row["plan"] = plan
    return row


def test_hp4_nothing_ticked_is_left_out_even_behind_another_why():
    fleet = {"editors": [
        _row("TCHEN-RIG", plan={"count": 0}, why="not_signed_in", headline="not_signed_in"),
        _row("RIVERA", plan={"count": 2}),
        _row("BASE", plan={"count": 1}, mode="base"),
    ]}
    online = ui_home.home_readouts(None, fleet, {})["readouts"][0]
    assert online["total"] == 1 and online["n"] == 1, online
    assert online["tone"] != "warn"


def test_hp4_a_silent_computer_with_a_fault_headline_is_not_online():
    fleet = {"editors": [
        _row("JSMITH-MBP", plan={"count": 1}, why="breaker_tripped", headline="breaker_tripped",
             status_reason="no report since 2026-09-25T00:00:00+00:00 (8h)"),
        _row("RIVERA", plan={"count": 1}),
    ]}
    online = ui_home.home_readouts(None, fleet, {})["readouts"][0]
    assert (online["n"], online["total"]) == (1, 2), online
    assert "JSMITH-MBP not heard from" in online["foot"]
    assert online["tone"] == "warn"


# ------------------------------------------------------------ home-project-5


def test_hp5_ticks_count_from_the_selections_not_folder_completion(env):
    """No completion rows at all (Syncthing unreachable, not shared yet, or
    upload-only): the page still has ticks and must not say otherwise."""
    _client, conn = env
    facts = ui_home.plan_facts(conn, None)
    ro = ui_home.home_readouts(None, {"editors": []}, {"projects": []}, facts=facts)
    in_sync = next(r for r in ro["readouts"] if r["k"] == "in sync")
    assert in_sync["total"] == 1, in_sync
    assert "no project is ticked anywhere" not in in_sync["foot"]


def test_hp5_moving_counts_the_lane_transfers(env):
    _client, conn = env
    db.replace_active_transfers(conn, "jsmith", "JSMITH-STUDIO", [{
        "lane": "lane_a_rclone", "name": "A001.mov", "direction": "up",
        "bytes_done": 10 * 2**20, "bytes_total": 50 * 2**20, "percentage": 20.0,
        "speed_bps": 40 * 2**20, "eta_seconds": 1, "project_slug": SLUG}], db.utcnow_iso())
    conn.commit()
    facts = ui_home.plan_facts(conn, None)
    assert facts["owed_bytes"] >= 40 * 2**20 and facts["moving_files"] == 1
    ro = ui_home.home_readouts(None, {"editors": []}, {"projects": []}, facts=facts)
    moving = next(r for r in ro["readouts"] if r["k"] == "moving")
    assert moving["n"] == 1 and moving["foot"] != "nothing waiting", moving
    # and the page itself draws it (the readouts read the facts through the request)
    html = _client.get("/").text
    block = re.search(r'id="win-ro-moving".*?class="foot">([^<]*)<', html, re.S)
    assert block and block.group(1) != "nothing waiting", block and block.group(1)


# ------------------------------------------------------------ home-project-6


def test_hp6_the_tree_comes_first_on_a_narrow_screen():
    css = _strip_css_comments(_read(CC_S / "home.css"))
    narrow = "".join(_media_blocks(css, "max-width: 1100px"))
    assert re.search(r"\.home-page > \.side \{[^}]*order: 0", narrow), narrow
    assert re.search(r"\.home-page > \.main \{[^}]*order: 1", narrow), narrow
    # and it outranks terminal.css's `.side { order: 2 }` (two classes beat one)
    term = _strip_css_comments(_read(CC_S / "terminal.css"))
    assert re.search(r"\.side \{[^}]*order: 2", term)


def test_hp6_the_empty_queue_links_to_the_tree(env):
    client, conn = env
    conn.execute("DELETE FROM selections")
    conn.commit()
    r = client.get("/partials/home-queue?as=jsmith", headers=_hx(client))
    assert r.status_code == 200, r.text[:300]
    assert '<a href="#win-projects">the projects list</a>' in r.text
    assert 'id="win-projects"' in client.get("/?as=jsmith").text


# ------------------------------------------------------------ home-project-7


def test_hp7_the_headline_is_the_sentence_and_wraps(env):
    client, _conn = env
    r = client.get("/partials/fleet", headers=_hx(client))
    assert r.status_code == 200
    assert "reason code" not in r.text
    for m in re.finditer(r'<div class="hl [^"]*" title="([^"]*)">([^<]*)</div>', r.text):
        assert m.group(1) == m.group(2)
    css = _strip_css_comments(_read(CC_S / "home.css"))
    hl = re.search(r"\.home-page \.pc \.hl \{([^}]*)\}", css).group(1)
    assert "nowrap" not in hl and "white-space: normal" in hl
    coarse = "".join(_media_blocks(css, "pointer: coarse"))
    assert re.search(r"\.home-page \.pc \.hl \{[^}]*-webkit-line-clamp: unset", coarse)


# ------------------------------------------------------------ home-project-8


def test_hp8_the_grid_and_transfers_polls_keep_the_pages_as(env):
    client, _conn = env
    html = client.get("/?as=jsmith").text
    assert 'hx-get="/partials/fleet?as=jsmith"' in html
    assert 'hx-get="/partials/home-transfers?as=jsmith"' in html
    plain = client.get("/").text
    assert 'hx-get="/partials/fleet"' in plain
    # the poll as jsmith answers with jsmith's computers only
    r = client.get("/partials/fleet?as=jsmith", headers=_hx(client, "http://testserver/?as=jsmith"))
    assert "JSMITH-STUDIO" in r.text and "OWEN-LAPTOP" not in r.text


# ------------------------------------------------------------ home-project-9


def test_hp9_the_hud_meta_row_can_shrink():
    """At 768 the meta row (flex: none, nowrap) made home 1282 px wide. The
    fix is everyday-apps-2's (hud.css): the row shrinks and clips, the stamp
    gives way first. Pinned here because home was one of its two pages."""
    css = _strip_css_comments(_read(CC_S / "hud.css"))
    meta = re.search(r"(?m)^\.hud-meta \{([^}]*)\}", css).group(1)
    assert "flex: none" not in meta and "min-width: 0" in meta and "overflow: hidden" in meta
    assert re.search(r"\.hud-meta > \.hud-stamp \{[^}]*min-width: 0", css)


# ------------------------------------------------------------ home-project-10


def test_hp10_home_touch_targets_are_44px():
    css = _strip_css_comments(_read(CC_S / "home.css"))
    coarse = "".join(_media_blocks(css, "pointer: coarse"))
    for sel in (r"\.tree \.row\.proj \.tick", r"\.tree \.row\.proj a\.nm",
                r"details\.more > summary", r"button\.fold", r"\.key\.sm"):
        rule = re.search(r"([^{}]*" + sel + r"[^{}]*)\{([^}]*)\}", coarse)
        assert rule and "min-height: var(--cc-tap" in rule.group(2), sel
    tick = re.search(r"\.tree \.row\.proj \.tick \{([^}]*)\}", coarse)
    assert tick and "min-width: var(--cc-tap" in tick.group(1)
    fold = re.search(r"button\.fold \{([^}]*)\}", coarse)
    assert fold and "min-width: var(--cc-tap" in fold.group(1)


# ------------------------------------------------------------ home-project-11


def test_hp11_read_the_answer_is_brought_on_screen(env):
    client, _conn = env
    html = client.get("/").text
    assert re.search(r'<div class="body" id="fleet-diagnostics" data-reveal>', html)
    grid = _read(CC_T / "partials" / "fleet_grid.html")
    assert 'hx-target="#fleet-diagnostics"' in grid
    js = _read(CC_S / "cc.js")
    assert re.search(r'if \(!isPoll\(evt\) && target\.hasAttribute && target\.hasAttribute\("data-reveal"\)\) reveal\(target\);', js)
    reveal = re.search(r"function reveal\(target\) \{(.*?)\n  \}", js, re.S).group(1)
    assert "scrollIntoView" in reveal and "focus(" in reveal
