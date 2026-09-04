"""A tab opens where you left it (CR-188, Alex, 2026-09-04).

"when you switch tabs it should remember your position from the last time you
were in X or Y tab." Every topbar destination and every Settings strip page is
a full page navigation, so the scroll position and the open <details> were
gone on every hop; `static/tab_memory.js` remembers them per page.

Two halves, the same shape test_static_js_syntax.py uses:

  * the SERVER half -- the file is served, base.html includes it after htmx,
    and the pages the owner switches between actually carry it. Always runs.
  * the BEHAVIOUR half -- the real, unmodified file executed in a `vm` context
    with a ~120 line DOM/storage/clock stub, so "the polled panels had not
    arrived yet and the page was 900 px tall" is a scenario here rather than a
    Tuesday on a phone. **node is not a dependency of this venv or of CI's
    python job**, so these SKIP when node is absent, exactly like the
    node --check in test_static_js_syntax.py.

The clock and the timers are FAKE: `attempt()` is driven from the events the
scenario fires, which is what makes the 3 s give-up deterministic.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = DASHBOARD_ROOT / "static" / "tab_memory.js"
BASE = DASHBOARD_ROOT / "templates" / "base.html"
FLEET = DASHBOARD_ROOT / "templates" / "fleet.html"
MOBILE_CSS = DASHBOARD_ROOT / "static" / "mobile.css"
NODE = shutil.which("node")

SECRET = "s" * 32

# The pages the owner switches between: the fleet page, and one Settings strip
# page from each of the three runs the strip renders.
PAGES = ("/", "/transfers", "/admin/settings", "/admin/packages", "/admin/jobs")


@pytest.fixture
def client(tmp_path):
    settings = Settings(db_path=str(tmp_path / "tab.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), auth_method="local")
    app = create_app(settings)
    with TestClient(app) as c:
        conn = dbmod.connect(settings.db_path)
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, "2026-ff5", "2026/FF5", "/data/2026-ff5", now)
        dbmod.record_known_editor(conn, "jsmith", source="admin", now=now)
        dbmod.upsert_machine(conn, "jsmith", "EDIT-PC", now, platform="windows")
        conn.commit()
        c.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield c
        conn.close()


# ------------------------------------------------------------- the server half


def test_the_script_is_served(client):
    r = client.get("/static/tab_memory.js")
    assert r.status_code == 200
    assert "ccsync.tab:" in r.text


def test_base_html_includes_it_after_htmx(client):
    """Deferred scripts run in document order: its htmx:afterSettle listener
    must be registered on a page htmx already owns."""
    src = BASE.read_text(encoding="utf-8")
    assert '<script src="/static/tab_memory.js" defer></script>' in src
    assert src.index("/static/htmx.min.js") < src.index("/static/tab_memory.js")


@pytest.mark.parametrize("url", PAGES)
def test_every_switchable_page_carries_it(client, url):
    r = client.get(url)
    assert r.status_code == 200, url
    assert "/static/tab_memory.js" in r.text, url


def test_the_login_page_carries_it_harmlessly(client):
    """base.html is base.html: an anonymous render must not 500 because a
    script that reads storage is on it."""
    fresh = client
    fresh.cookies.clear()
    r = fresh.get("/login")
    assert r.status_code == 200


def test_the_polled_containers_still_swap_innerhtml(client):
    """CR-188 point 2: the 15 s grid poll must not fight the restore. An
    innerHTML swap leaves the wrapper itself in place, so neither the browser's
    scroll anchoring nor the reader's position moves; an outerHTML swap of a
    tall container is what makes a page jump every fifteen seconds. Pinned on
    the fleet page's own markup because that is the page left open longest."""
    src = FLEET.read_text(encoding="utf-8")
    for line in src.splitlines():
        if "every " not in line or "hx-get" not in line:
            continue
        assert 'hx-swap="innerHTML"' in line or "hx-swap" not in line, line


def test_the_css_pins_the_two_properties_the_script_depends_on():
    css = MOBILE_CSS.read_text(encoding="utf-8")
    section = css[css.index("== tab memory =="):]
    assert "scroll-behavior: auto" in section
    assert "overflow-anchor: auto" in section
    assert ".fleet-grid-wrap" in section


def test_no_em_dash_in_what_cr188_wrote():
    """CLAUDE.md's rule, on this feature's own files."""
    for path in (SCRIPT, BASE, MOBILE_CSS, Path(__file__)):
        assert chr(0x2014) not in path.read_text(encoding="utf-8"), path.name


# ---------------------------------------------------------- the behaviour half

# One string, deliberately: this file owns it, it is an input to a subprocess
# rather than source of the app, and a checked-in .mjs would be one more thing
# to keep in step with tab_memory.js.
HARNESS = r"""
'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const SRC = fs.readFileSync(process.argv[2], 'utf8');

let NOW = 1700000000000;
const HOUR = 3600 * 1000;

function Store(blocked) {
  const m = new Map();
  return {
    _m: m,
    getItem(k) { if (blocked) throw new Error('blocked'); return m.has(k) ? m.get(k) : null; },
    setItem(k, v) { if (blocked) throw new Error('blocked'); m.set(k, String(v)); },
    removeItem(k) { if (blocked) throw new Error('blocked'); m.delete(k); },
  };
}

function El(tag, attrs, top) {
  const a = Object.assign({}, attrs || {});
  return {
    tagName: tag,
    id: a.id || '',
    _attrs: a,
    _top: top || 0,
    _scrolled: false,
    _env: null,
    hasAttribute(k) { return k in this._attrs; },
    getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; },
    setAttribute(k, v) { this._attrs[k] = String(v); },
    removeAttribute(k) { delete this._attrs[k]; },
    getBoundingClientRect() { return { top: this._top - this._env.win.scrollY }; },
    scrollIntoView() { this._scrolled = true; this._env.win.scrollY = this._top; },
  };
}

function makeEnv(opts) {
  opts = opts || {};
  const env = {
    docHeight: opts.docHeight === undefined ? 2000 : opts.docHeight,
    details: opts.details || [],
    sections: opts.sections || [],
    listeners: { doc: {}, win: {} },
    intervals: [],
  };
  env.details.concat(env.sections).forEach(e => { e._env = env; });

  const doc = {
    readyState: 'complete',
    visibilityState: 'visible',
    documentElement: { get scrollHeight() { return env.docHeight; } },
    body: { get scrollHeight() { return env.docHeight; } },
    addEventListener(t, fn) { (env.listeners.doc[t] = env.listeners.doc[t] || []).push(fn); },
    querySelectorAll(sel) {
      if (sel === 'details') return env.details.slice();
      if (sel.indexOf('h1[id]') === 0) return env.sections.slice();
      return [];
    },
    getElementById(id) {
      return env.details.concat(env.sections).filter(e => e.id === id)[0] || null;
    },
  };
  const win = {
    scrollY: opts.scrollY || 0,
    pageYOffset: 0,
    innerHeight: 800,
    sessionStorage: opts.session,
    localStorage: opts.local,
    _scrolls: [],
    scrollTo(x, y) { win.scrollY = y; win._scrolls.push(y); },
    addEventListener(t, fn) { (env.listeners.win[t] = env.listeners.win[t] || []).push(fn); },
  };
  env.doc = doc;
  env.win = win;
  env.fire = (where, type, evt) => {
    (env.listeners[where][type] || []).forEach(fn => fn(evt || {}));
  };
  const sandbox = {
    window: win,
    document: doc,
    location: {
      pathname: opts.pathname || '/',
      search: opts.search || '',
      hash: opts.hash || '',
    },
    setInterval(fn, ms) { env.intervals.push(fn); return env.intervals.length; },
    clearInterval() {},
    Date: { now: () => NOW },
    console: console,
  };
  win.window = win;
  vm.runInNewContext(SRC, sandbox);
  env.api = win.__ccsyncTabMemory;
  return env;
}

function entryFor(store, key, obj) {
  store._m.set(key, JSON.stringify(Object.assign({ t: NOW }, obj)));
}

const out = {};

// 1. What a page leaves behind when the reader navigates away.
{
  const session = Store(false), local = Store(false);
  const d1 = El('details', { id: 'd1', open: '' }, 100);
  const d2 = El('details', { id: 'd2' }, 400);
  const env = makeEnv({ session, local, scrollY: 500, pathname: '/admin/packages',
                        details: [d1, d2] });
  env.fire('win', 'pagehide');
  const key = 'ccsync.tab:/admin/packages';
  const saved = JSON.parse(session._m.get(key));
  out.save = { y: saved.y, details: saved.details, inLocal: local._m.has(key) };
}

// 2. And what the next visit to that page does with it.
{
  const session = Store(false), local = Store(false);
  entryFor(session, 'ccsync.tab:/admin/packages', { y: 500, details: ['d1'], section: null });
  const d1 = El('details', { id: 'd1' }, 100);
  const env = makeEnv({ session, local, pathname: '/admin/packages', details: [d1] });
  out.restore = { y: env.win.scrollY, d1open: d1.hasAttribute('open') };
}

// 3. A deep link wins over the remembered position.
{
  const session = Store(false), local = Store(false);
  entryFor(session, 'ccsync.tab:/admin/users', { y: 500, details: [] });
  const env = makeEnv({ session, local, pathname: '/admin/users', hash: '#admin-fleet-halt' });
  out.hashWins = { y: env.win.scrollY, scrolls: env.win._scrolls.length };
}

// 4. Storage blocked outright: the page behaves as it did before this file.
{
  const env = makeEnv({ session: Store(true), local: Store(true), scrollY: 300,
                        pathname: '/admin/users' });
  env.fire('win', 'pagehide');
  env.fire('doc', 'htmx:afterSettle');
  out.blocked = { y: env.win.scrollY, scrolls: env.win._scrolls.length, api: !!env.api };
}

// 5. The polled panels arrive late: too short now, tall enough after a settle.
{
  const session = Store(false), local = Store(false);
  entryFor(session, 'ccsync.tab:/', { y: 500, details: [] });
  const env = makeEnv({ session, local, pathname: '/', docHeight: 900 });
  const before = env.win.scrollY;
  env.docHeight = 2000;
  env.fire('doc', 'htmx:afterSettle');
  out.late = { before: before, after: env.win.scrollY };
}

// 6. The page never grows back: the nearest heading is the fallback, once the
//    3 s window is spent.
{
  const session = Store(false), local = Store(false);
  entryFor(session, 'ccsync.tab:/', { y: 500, details: [], section: 's1' });
  const s1 = El('h2', { id: 's1' }, 300);
  const env = makeEnv({ session, local, pathname: '/', docHeight: 900, sections: [s1] });
  const before = env.win.scrollY;
  NOW += 4000;
  env.fire('doc', 'htmx:afterSettle');
  out.giveUp = { before: before, scrolledToSection: s1._scrolled, y: env.win.scrollY };
  NOW -= 4000;
}

// 7. The key: the path, plus only the query keys that SELECT a view.
{
  const env = makeEnv({ session: Store(false), local: Store(false),
                        pathname: '/admin/jobs', search: '?finished=1&q=abc&v=7' });
  out.key = env.api.key();
}

// 8. The mounted SPAs are a no-op.
{
  const env = makeEnv({ session: Store(false), local: Store(false), pathname: '/broll/' });
  out.spa = { api: !!env.api, listeners: Object.keys(env.listeners.doc).length };
}

// 9. Yesterday's position is not a position.
{
  const session = Store(false), local = Store(false);
  const key = 'ccsync.tab:/transfers';
  session._m.set(key, JSON.stringify({ y: 500, details: [], t: NOW - 9 * HOUR }));
  const env = makeEnv({ session, local, pathname: '/transfers' });
  out.expired = { y: env.win.scrollY };
}

// 10. The installed PWA: relaunched with no sessionStorage, restored from the
//     local copy.
{
  const session = Store(false), local = Store(false);
  entryFor(local, 'ccsync.tab:/transfers', { y: 640, details: [] });
  const env = makeEnv({ session, local, pathname: '/transfers' });
  out.pwa = { y: env.win.scrollY };
}

// 11. A 15 s grid poll on a page with nothing pending never scrolls anything.
{
  const session = Store(false), local = Store(false);
  const env = makeEnv({ session, local, pathname: '/', scrollY: 220 });
  env.fire('doc', 'htmx:afterSettle');
  env.fire('doc', 'htmx:afterSettle');
  out.poll = { y: env.win.scrollY, scrolls: env.win._scrolls.length };
}

console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def scenarios(tmp_path_factory):
    if not NODE:
        pytest.skip("node is not on PATH; the server half above is the gate here")
    harness = tmp_path_factory.mktemp("tabmem") / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    proc = subprocess.run([NODE, str(harness), str(SCRIPT)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_node_parses_the_script():
    if not NODE:
        pytest.skip("node is not on PATH")
    proc = subprocess.run([NODE, "--check", str(SCRIPT)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def test_leaving_a_page_records_the_position_and_the_open_sections(scenarios):
    assert scenarios["save"]["y"] == 500
    assert scenarios["save"]["details"] == ["d1"]
    # Written to BOTH stores: the installed app is killed by the OS, and a
    # relaunch has no sessionStorage at all.
    assert scenarios["save"]["inLocal"] is True


def test_coming_back_restores_both(scenarios):
    assert scenarios["restore"]["y"] == 500
    assert scenarios["restore"]["d1open"] is True


def test_a_deep_link_wins(scenarios):
    """/#server-notices and /admin/users#admin-fleet-halt are the product's own
    links (DUI-7): the reader asked for that anchor, not for last time."""
    assert scenarios["hashWins"] == {"y": 0, "scrolls": 0}


def test_blocked_storage_does_nothing_at_all(scenarios):
    assert scenarios["blocked"]["scrolls"] == 0
    assert scenarios["blocked"]["y"] == 300
    assert scenarios["blocked"]["api"] is True


def test_it_waits_for_the_polled_panels_to_make_the_page_tall_enough(scenarios):
    """Half of what makes these pages tall arrives from hx-trigger="load"
    fragments. Scrolling to 500 in a 900 px document clamps to 100 and the
    reader lands somewhere they never were."""
    assert scenarios["late"]["before"] == 0
    assert scenarios["late"]["after"] == 500


def test_it_gives_up_on_the_nearest_heading(scenarios):
    assert scenarios["giveUp"]["before"] == 0
    assert scenarios["giveUp"]["scrolledToSection"] is True
    assert scenarios["giveUp"]["y"] == 300


def test_the_key_is_the_path_plus_the_view_selecting_query(scenarios):
    assert scenarios["key"] == "ccsync.tab:/admin/jobs?finished=1"


def test_the_mounted_spas_are_a_no_op(scenarios):
    """They are single-page, they keep their own state, and they do not render
    base.html: a restore aimed at a view they have already replaced would be a
    jump to nowhere."""
    assert scenarios["spa"] == {"api": False, "listeners": 0}


def test_a_position_from_yesterday_is_not_a_position(scenarios):
    assert scenarios["expired"]["y"] == 0


def test_the_installed_app_restores_from_the_local_copy(scenarios):
    assert scenarios["pwa"]["y"] == 640


def test_a_grid_poll_never_moves_the_page(scenarios):
    assert scenarios["poll"] == {"y": 220, "scrolls": 0}
