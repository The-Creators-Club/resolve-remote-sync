"""The everyday-apps findings of the UI port review (docs/UI_PORT_REVIEW_2026-09-25.md,
fix builder F-everyday, 2026-09-25). One block per finding; each test fails
on the code the review measured.

everyday-apps-3 asked for a test that computes the HUD elements' display,
not only the rule text: `_display()` below is a small cascade over the
hud-common block (specificity, source order, width media queries), enough
for the flat class selectors that block is written in.
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

SECRET = "f" * 32
DASH = Path(__file__).resolve().parents[1]
CC = DASH / "templates"
STATIC = DASH / "static" / "cc"


# ------------------------------------------------------------------ fixture

@pytest.fixture
def env(tmp_path):
    """The dashboard (the terminal look is the only one since 2026-09-25),
    owen with a laptop that has Elections ticked."""
    projects = tmp_path / "Projects"
    (projects / "2026" / "FF5").mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "ev.db"), session_secret=SECRET,
                        report_token="tok", admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    with TestClient(create_app(settings)) as client:
        conn = db.connect(tmp_path / "ev.db")
        now = db.utcnow_iso()
        db.upsert_project(conn, "2026-ff5-elections", "2026/FF5/Elections", "/x", now)
        db.upsert_project(conn, "2026-ff5-civil", "2026/FF5/Civil Defence", "/y", now)
        db.record_known_editor(conn, "owen", "admin")
        db.upsert_machine(conn, "owen", "OWEN-LAPTOP", now, platform="windows")
        db.upsert_machine_state(conn, "owen", "OWEN-LAPTOP", None, now,
                                platform="windows", companion_version="0.9.80")
        db.add_selection(conn, "owen", "2026-ff5-elections", "admin", now,
                         machine="OWEN-LAPTOP")
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))

        def hx(url="http://testserver/account"):
            return {**HX, "HX-Current-URL": url}

        yield client, conn, hx
        conn.close()


def _ticked(conn, machine=None):
    return {s["slug"] for s in db.fetch_selections(conn, "owen", machine=machine)}


# ------------------------------------------------------ everyday-apps-1

def test_everyday_apps_1_untick_off_never_ticks_an_unticked_project(env):
    """The stale-key case: Civil Defence is NOT ticked, and the computer
    window's Untick (drawn before another window's untick) is pressed. The
    plain toggle ticked it; `mode=off` must leave it off."""
    client, conn, hx = env
    url = ("/partials/selection/owen/2026-ff5-civil/toggle"
           "?view=none&machine=OWEN-LAPTOP&mode=off")
    resp = client.post(url, headers=hx())
    assert resp.status_code == 200, resp.text[:300]
    assert "2026-ff5-civil" not in _ticked(conn, "OWEN-LAPTOP")
    assert "2026-ff5-civil" not in _ticked(conn)


def test_everyday_apps_1_untick_off_removes_a_ticked_project(env):
    client, conn, hx = env
    url = ("/partials/selection/owen/2026-ff5-elections/toggle"
           "?view=none&machine=OWEN-LAPTOP&mode=off")
    assert client.post(url, headers=hx()).status_code == 200
    assert "2026-ff5-elections" not in _ticked(conn, "OWEN-LAPTOP")
    # and a second press (the stale key again) stays off
    assert client.post(url, headers=hx()).status_code == 200
    assert "2026-ff5-elections" not in _ticked(conn, "OWEN-LAPTOP")


def test_everyday_apps_1_queue_untick_refreshes_every_computer_window(env):
    client, conn, hx = env
    resp = client.post(
        "/partials/selection/owen/2026-ff5-elections/toggle?view=person-queue&mode=off",
        headers=hx())
    assert resp.status_code == 200, resp.text[:300]
    assert resp.headers.get("HX-Trigger") == "account-refresh-all"
    assert "2026-ff5-elections" not in _ticked(conn)
    # a stale queue key pressed again does not tick it back for the person
    client.post(
        "/partials/selection/owen/2026-ff5-elections/toggle?view=person-queue&mode=off",
        headers=hx())
    assert "2026-ff5-elections" not in _ticked(conn)


def test_everyday_apps_1_the_untick_keys_and_the_poll(env):
    computer = (CC / "partials" / "account_computer.html").read_text(encoding="utf-8")
    queue = (CC / "partials" / "person_queue.html").read_text(encoding="utf-8")
    assert 'hx-post="{{ base }}&mode=off"' in computer
    assert "account-refresh-all from:body" in computer
    assert "toggle?view=person-queue&mode=off" in queue
    # and the account page really draws them
    client, _conn, hx = env
    page = client.get("/account").text
    assert "account-refresh-all from:body" in page
    assert "&amp;mode=off" in page or "&mode=off" in page


# ------------------------------------------ everyday-apps-2 and -3: the cascade

_HUD_BEGIN = "/* ==== hud-common BEGIN"
_HUD_END = re.compile(r"/\* ==== hud-common END =+ \*/")


def _hud_common() -> str:
    text = (STATIC / "hud.css").read_text(encoding="utf-8")
    start = text.index(_HUD_BEGIN)
    return text[start:_HUD_END.search(text, start).end()]


def _split_top(text: str):
    """Split a selector list on commas outside parentheses (:is(a, b))."""
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def _rules(css: str):
    """(media, selectors, declarations) in source order. Handles one level of
    @media; skips @keyframes and anything else nested."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, i, n = [], 0, len(css)

    def block_end(pos):
        depth = 0
        for k in range(pos, n):
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
                if depth == 0:
                    return k
        raise AssertionError("unbalanced css")

    def flat(body, media):
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", body):
            sels = [s.strip() for s in _split_top(m.group(1)) if s.strip()]
            decls = dict((d.split(":", 1)[0].strip(), d.split(":", 1)[1].strip())
                         for d in m.group(2).split(";") if ":" in d)
            out.append((media, sels, decls))

    while i < n:
        j = css.find("{", i)
        if j < 0:
            break
        head = css[i:j].strip()
        if head.startswith("@"):
            end = block_end(j)
            if head.startswith("@media"):
                flat(css[j + 1:end], head[len("@media"):].strip())
            i = end + 1
        else:
            end = css.index("}", j)
            flat(css[i:end + 1], "")
            i = end + 1
    return out


def _media_ok(media: str, width: int) -> bool:
    if not media:
        return True
    for part in re.findall(r"\(([^)]*)\)", media):
        feat, _, val = (x.strip() for x in part.partition(":"))
        if feat == "min-width":
            if width < int(val.rstrip("px")):
                return False
        elif feat == "max-width":
            if width > int(val.rstrip("px")):
                return False
        else:           # pointer, display-mode, forced-colors, reduced motion
            return False
    return True


_COMPOUND = re.compile(r"^([a-z]*)((?:[.#\[][^.#\[]+)*)$")


def _parse_compound(text: str):
    """(tag, classes, attrs) or None when the compound has a pseudo-class
    or anything else this little matcher does not model."""
    if ":" in text or "*" == text:
        return None if text != "*" else ("", set(), set())
    m = _COMPOUND.match(text)
    if not m:
        return None
    classes = set(re.findall(r"\.([\w-]+)", m.group(2)))
    attrs = set(re.findall(r"\[([^\]]+)\]", m.group(2)))
    return m.group(1), classes, attrs


def _matches(selector: str, path):
    """path = [(tag, classes)] root to element. Descendant and child
    combinators. Returns specificity or None."""
    parts = selector.replace(">", " > ").split()
    compounds, child_flags = [], []
    for p in parts:
        if p == ">":
            child_flags[-1] = True
            continue
        c = _parse_compound(p)
        if c is None:
            return None
        compounds.append(c)
        child_flags.append(False)

    def fits(c, el):
        tag, classes, attrs = c
        return (not tag or tag == el[0]) and classes <= el[1] and not attrs

    # match right to left
    if not fits(compounds[-1], path[-1]):
        return None
    k = len(path) - 2
    for idx in range(len(compounds) - 2, -1, -1):
        child = child_flags[idx]
        while k >= 0 and not fits(compounds[idx], path[k]):
            if child:
                return None
            k -= 1
        if k < 0:
            return None
        k -= 1
    spec_b = sum(len(c[1]) + len(c[2]) for c in compounds)
    spec_c = sum(1 for c in compounds if c[0])
    return (0, spec_b, spec_c)


def _display(path, width: int) -> str | None:
    best = None
    for order, (media, sels, decls) in enumerate(_rules(_hud_common())):
        if "display" not in decls or not _media_ok(media, width):
            continue
        for sel in sels:
            spec = _matches(sel, path)
            if spec is not None and (best is None or (spec, order) >= best[0]):
                best = ((spec, order), decls["display"])
    return best[1] if best else None


def _el(tag, *classes):
    return (tag, set(classes))


HUD = _el("div", "hud")
META = _el("div", "hud-meta")
NAV = _el("nav", "hud-nav")


def test_the_cascade_helper_sees_the_base_rules():
    assert _display([HUD], 1440) == "flex"
    assert _display([HUD, NAV], 1440) == "flex"
    assert _display([HUD, NAV], 390) == "none"


@pytest.mark.parametrize("classes", [
    ("hud-count", "hud-hide-sm"),            # the alert count
    ("hud-user", "hud-hide-sm"),             # "owen @admin"
])
def test_everyday_apps_3_phone_bar_hides_hide_sm_links(classes):
    path = [HUD, META, _el("a", *classes)]
    assert _display(path, 390) == "none"
    assert _display(path, 1440) == "inline-flex"


def test_everyday_apps_3_phone_bar_hides_the_menu_key():
    assert _display([HUD, META, _el("button", "hud-key", "hud-hide-sm")], 390) == "none"


@pytest.mark.parametrize("width,shown", [(1920, False), (1440, False), (1100, False),
                                         (901, False), (900, True), (768, True),
                                         (601, True)])
def test_everyday_apps_3_more_key_is_tablet_only(width, shown):
    path = [HUD, NAV, _el("button", "hud-key", "hud-more-btn")]
    assert (_display(path, width) != "none") is shown, _display(path, width)


def test_everyday_apps_2_the_meta_row_can_shrink():
    rules = [(sels, decls) for media, sels, decls in _rules(_hud_common()) if not media]
    meta = [d for s, d in rules if s == [".hud-meta"]]
    assert meta and meta[0].get("flex") == "0 1 auto"
    assert meta[0].get("min-width") == "0"
    assert meta[0].get("justify-content") == "flex-end"      # the menu stays
    brand = [d for s, d in rules if s == [".hud-brand"]]
    assert brand and brand[0].get("min-width") not in (None, "0")


@pytest.mark.parametrize("width,shown", [(1920, True), (1600, True), (1599, False),
                                         (1440, False), (1024, False), (768, False),
                                         (390, False)])
def test_everyday_apps_2_the_long_stale_sentence_only_on_wide_screens(width, shown):
    path = [HUD, META, _el("span", "hud-stamp"), _el("span", "hud-stale"), _el("span"),
            _el("span", "hud-stale-long", "hud-hide-sm")]
    assert (_display(path, width) != "none") is shown


@pytest.mark.parametrize("classes", [
    ("hud-count", "hud-hide-sm", "hud-lowpri"),
    ("hud-user", "hud-hide-sm", "hud-lowpri"),
])
def test_everyday_apps_2_tablet_bar_drops_what_the_more_sheet_carries(classes):
    path = [HUD, META, _el("a", *classes)]
    assert _display(path, 768) == "none"
    assert _display(path, 1024) == "inline-flex"


def test_everyday_apps_2_the_markup_carries_the_classes():
    stamp = (CC / "partials" / "stamp.html").read_text(encoding="utf-8")
    topbar = (CC / "partials" / "topbar.html").read_text(encoding="utf-8")
    assert 'class="hud-stale-long hud-hide-sm"' in stamp
    # "stale" and its sentence are ONE flex item, so the gap cannot draw
    # "stale : syncthing"
    assert "<span>stale<span class=\"hud-stale-long" in stamp
    assert 'class="hud-stamp-at hud-hide-sm hud-lowpri"' in stamp
    assert 'class="hud-count hud-hide-sm hud-lowpri" href="/admin/health"' in topbar
    assert 'class="hud-user hud-hide-sm hud-lowpri"' in topbar


# ------------------------------------------------------ everyday-apps-5

def test_everyday_apps_5_help_code_blocks_scroll_inside_themselves():
    rules = _rules((STATIC / "components.css").read_text(encoding="utf-8"))
    pre = [d for media, sels, d in rules if ".doc pre" in sels]
    assert pre and pre[0].get("overflow-x") == "auto"
    assert pre[0].get("max-width") == "100%"
    table = [d for media, sels, d in rules if ".doc table" in sels]
    assert table and table[0].get("overflow-x") == "auto"


def test_everyday_apps_5_help_contents_and_title_wrap():
    """Verifier, 2026-09-25: with the pre fix in, a contents entry that is one
    long path and the title bar of a deep document still widened the phone
    page (407 and 533 px at 390). The contents break anywhere; the title
    stays one line and ends in an ellipsis."""
    rules = _rules((STATIC / "everyday.css").read_text(encoding="utf-8"))
    toc = [d for media, sels, d in rules if ".ev-help .help-toc" in sels]
    assert toc and toc[0].get("overflow-wrap") == "anywhere"
    title = [d for media, sels, d in rules if ".ev-help .win > .bar h2.t" in sels]
    assert title and title[0].get("overflow") == "hidden"
    assert title[0].get("text-overflow") == "ellipsis"
    sub = [d for media, sels, d in rules if ".ev-help .head .sub" in sels]
    assert sub and sub[0].get("overflow-wrap") == "anywhere"
    assert title[0].get("min-width") == "0"


# ------------------------------------------------------ everyday-apps-6

def test_everyday_apps_6_tap_rule_survives_adopt_tips():
    """cc.js adoptTips turns title into data-tip and removes title, so the
    44 px rule has to match data-tip as well."""
    phone = (STATIC / "phone.css").read_text(encoding="utf-8")
    cc_js = (STATIC / "cc.js").read_text(encoding="utf-8")
    assert 'el.removeAttribute("title")' in cc_js          # the reason
    coarse = [d for media, sels, d in _rules(phone)
              if "pointer: coarse" in media and d.get("min-height") == "var(--tap)"
              for _ in [0] if any("[data-tip]" in s and ".tag" in s for s in sels)]
    assert coarse, "no pointer:coarse tap rule keyed on .tag[data-tip]"
    led = [sels for media, sels, d in _rules(phone)
           if "pointer: coarse" in media and any(".led" in s and "[data-tip]" in s for s in sels)]
    assert led
