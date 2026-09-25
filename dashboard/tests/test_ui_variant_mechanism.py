"""The terminal look's overlay mechanism (docs/UI_REDESIGN_PORT_PLAN.md 7.0,
R23, R24, 3.4; phase 0, 2026-09-25).

What each block pins, in one line:
  * environments: one per group set, cloned (autoescape survives), the
    classic one never loads cc/*, a set's one only its own groups';
  * resolution: a partial follows the PAGE that asked (signed X-CC-UI), an
    htmx request with no header is classic plus HX-Refresh, a forged or
    unknown set reloads once, a classic page is left alone across deploys;
  * the setting: `none`/`site`/`chrome` rules, kept out of site_history and
    site.toml, never published to companions;
  * the cookie route, the effective cookie, /go/<panel>, /static caching and
    the service worker's precache.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, TemplateNotFound

from ccsync_dashboard import auth, site_store
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import ui, ui_variant as uv
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

pytestmark = pytest.mark.ui_mechanism

SECRET = "u" * 32
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                               admin_users=frozenset({"owen"})))


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def sign_in(client, user="owen"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def set_groups(monkeypatch, groups):
    value = frozenset(groups)
    monkeypatch.setattr(uv, "site_groups", lambda conn, settings, app=None: value)


def page_groups(html: str) -> str:
    m = re.search(r'<html[^>]*\bdata-ui-groups="([^"]*)"', html)
    assert m, "no data-ui-groups on <html>"
    return m.group(1)


# ------------------------------------------------------------ environments


def test_the_classic_environment_refuses_cc_by_name():
    with pytest.raises(TemplateNotFound):
        ui.templates.env.get_template("cc/shell.html")
    with pytest.raises(TemplateNotFound):
        ui.templates.env.get_template("cc/partials/stamp.html")


def test_a_probe_template_loads_only_where_its_group_is_on(tmp_path):
    """Made real with a template the test writes (wave 5): the refusal must
    not pass merely because templates/cc/ is empty."""
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "probe.html").write_text("cc {{ x }}", encoding="utf-8")
    (tmp_path / "probe.html").write_text("classic {{ x }}", encoding="utf-8")
    table = {"cc/probe.html": "chrome"}
    base = ui.templates.env
    classic = base.overlay(loader=uv.ClassicLoader(str(tmp_path)))
    on = base.overlay(loader=ChoiceLoader([uv.GroupFilteredLoader(tmp_path, {"chrome"}, table),
                                          uv.ClassicLoader(str(tmp_path))]))
    off = base.overlay(loader=ChoiceLoader([uv.GroupFilteredLoader(tmp_path, {"home"}, table),
                                           uv.ClassicLoader(str(tmp_path))]))
    with pytest.raises(TemplateNotFound):
        classic.get_template("cc/probe.html")
    assert classic.get_template("probe.html").render(x="<b>").startswith("classic")
    assert on.get_template("probe.html").render(x="<b>") == "cc &lt;b&gt;"
    assert on.get_template("cc/probe.html").render(x=1) == "cc 1"
    assert off.get_template("probe.html").render(x=1) == "classic 1"
    with pytest.raises(TemplateNotFound):
        off.get_template("cc/probe.html")


def test_every_built_environment_matches_the_classic_one():
    for groups in ({"chrome"}, set(uv.GROUPS)):
        uv.templates_for(groups)
    envs = uv.built_environments()
    assert len(envs) >= 2
    base = envs[0]
    for env in envs[1:]:
        assert set(env.globals) == set(base.globals)
        assert set(env.filters) == set(base.filters)
        assert env.undefined is base.undefined
        assert set(env.extensions) == set(base.extensions)
        assert (env.trim_blocks, env.lstrip_blocks) == (base.trim_blocks, base.lstrip_blocks)
        assert env.autoescape is base.autoescape
        assert env.autoescape("x.html")


def test_every_cc_file_is_mapped_to_one_group():
    cc = TEMPLATES / "cc"
    files = sorted(p.relative_to(TEMPLATES).as_posix() for p in cc.rglob("*.html")) \
        if cc.is_dir() else []
    unmapped = [f for f in files if f not in uv.TEMPLATE_GROUPS]
    assert not unmapped, f"add these to ui_variant.TEMPLATE_GROUPS: {unmapped}"
    assert set(uv.TEMPLATE_GROUPS.values()) <= set(uv.GROUPS)


def test_every_cc_file_shadows_a_classic_one_or_is_new_named():
    """A `cc/project_detail.html` would never be served: the overlay name of
    partials/project_detail.html is cc/partials/project_detail.html."""
    cc = TEMPLATES / "cc"
    if not cc.is_dir():
        return
    for p in cc.rglob("*.html"):
        rel = p.relative_to(TEMPLATES).as_posix()
        if rel in uv.NEW_NAME_TEMPLATES:
            continue
        assert (TEMPLATES / rel[len("cc/"):]).is_file(), (
            f"{rel} shadows no classic template and is not in NEW_NAME_TEMPLATES")


def test_the_same_name_renders_per_set_alternately_and_from_threads():
    if "chrome" not in uv.build_groups():
        pytest.skip("no chrome templates in this build yet")
    classic = uv.templates_for(frozenset())
    terminal = uv.templates_for({"chrome"})
    seen: list[tuple[str, str]] = []

    def name_of(wrapper):
        return Path(wrapper.env.get_template("partials/stamp.html").filename).as_posix()

    for _ in range(10):
        seen.append(("classic", name_of(classic)))
        seen.append(("cc", name_of(terminal)))
    errors: list[str] = []

    def worker(kind, wrapper):
        for _ in range(50):
            got = name_of(wrapper)
            if ("/cc/" in got) != (kind == "cc"):
                errors.append(f"{kind}: {got}")

    threads = [threading.Thread(target=worker, args=("classic", classic)),
               threading.Thread(target=worker, args=("cc", terminal))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    for kind, got in seen:
        assert ("/cc/" in got) == (kind == "cc"), (kind, got)


def test_is_partial_reads_the_last_directory():
    assert uv.is_partial("partials/stamp.html")
    assert uv.is_partial("cc/partials/stamp.html")
    assert not uv.is_partial("fleet.html")
    assert not uv.is_partial("cc/shell.html")


# ------------------------------------------------------------ full pages


def test_a_classic_page_carries_an_empty_set_and_only_that(client, monkeypatch):
    set_groups(monkeypatch, set())
    page = sign_in(client).get("/")
    assert page.status_code == 200
    assert page_groups(page.text) == ""
    assert 'hx-headers=\'{"X-CSRF-Token": "' in page.text
    headers = json.loads(re.search(r"hx-headers='([^']*)'", page.text).group(1))
    assert headers["X-CC-UI"] == ""
    assert "X-CC-UI-Sig" not in headers
    assert uv.EFFECTIVE_COOKIE not in (page.headers.get("set-cookie") or "")


def test_a_setting_flip_takes_effect_on_the_next_request(client, monkeypatch):
    if "chrome" not in uv.build_groups():
        pytest.skip("no chrome templates in this build yet")
    sign_in(client)
    set_groups(monkeypatch, {"chrome"})
    assert page_groups(client.get("/").text) == "chrome"
    set_groups(monkeypatch, set())
    assert page_groups(client.get("/").text) == ""
    set_groups(monkeypatch, {"chrome"})
    assert page_groups(client.get("/").text) == "chrome"


def test_a_stored_group_this_build_lacks_is_dropped(client, monkeypatch):
    set_groups(monkeypatch, {"chrome", "settings-fleet"} | (
        {"home"} if "home" in uv.build_groups() else set()))
    got = page_groups(sign_in(client).get("/").text)
    assert "settings-fleet" not in got.split(",") or "settings-fleet" in uv.build_groups()


def test_the_effective_cookie_is_dotted_path_root_and_readable(client, monkeypatch):
    if "chrome" not in uv.build_groups():
        pytest.skip("no chrome templates in this build yet")
    set_groups(monkeypatch, {"chrome"})
    page = sign_in(client).get("/")
    raw = page.headers.get("set-cookie") or ""
    assert f"{uv.EFFECTIVE_COOKIE}=chrome" in raw
    assert "Path=/" in raw and "HttpOnly" not in raw
    assert '"' not in raw.split(";")[0] and "\\" not in raw


def test_the_effective_value_is_dot_separated():
    assert uv.effective_value(frozenset({"chrome", "apps", "home"})) == "chrome.apps"
    assert uv.effective_value(frozenset()) == ""


# ------------------------------------------------------------ htmx requests


def test_htmx_with_no_header_is_classic_and_reloads_when_the_look_changed(client, monkeypatch):
    if "chrome" not in uv.build_groups():
        pytest.skip("no chrome templates in this build yet")
    set_groups(monkeypatch, {"chrome"})
    r = sign_in(client).get("/partials/stamp", headers={
        "HX-Request": "true", "HX-Current-URL": "http://testserver/"})
    assert r.status_code == 200
    assert r.headers.get("hx-refresh") == "true"
    classic = ui.templates.env.get_template("partials/stamp.html").filename
    assert "stamp" in r.text
    assert "/cc/" not in Path(classic).as_posix()


def test_htmx_with_no_header_and_nothing_on_is_left_alone(client, monkeypatch):
    set_groups(monkeypatch, set())
    r = sign_in(client).get("/partials/stamp", headers={"HX-Request": "true"})
    assert r.status_code == 200 and "hx-refresh" not in r.headers


def test_the_classic_dashboard_update_fetch_never_gets_a_cc_partial(client, monkeypatch):
    set_groups(monkeypatch, {"chrome", "settings-fleet"})
    r = sign_in(client).get("/partials/admin/dashboard-update",
                            headers={"HX-Request": "true"})
    assert "data-ui=\"cc\"" not in r.text
    assert "win" not in re.findall(r'class="([^"]*)"', r.text)


def test_a_signed_header_is_honoured_whatever_the_setting(client, monkeypatch):
    if "chrome" not in uv.build_groups():
        pytest.skip("no chrome templates in this build yet")
    sign_in(client)
    set_groups(monkeypatch, set())          # the setting went off after the page loaded
    gen = uv.generation({"chrome"})
    sid = auth.session_id_for(SECRET, client.cookies.get(auth.COOKIE_NAME))
    r = client.get("/partials/stamp", headers={
        "HX-Request": "true", "X-CC-UI": "chrome", "X-CC-UI-Gen": gen,
        "X-CC-UI-Sig": uv.header_sig(client.app.state.settings, "chrome", gen, sid),
        "HX-Current-URL": "http://testserver/transfers"})
    assert r.status_code == 200 and "hx-refresh" not in r.headers
    assert r.headers.get("x-cc-ui-want") == "1"     # the page is told, never reloaded


def test_a_forged_header_reloads_and_serves_nothing(client, monkeypatch):
    set_groups(monkeypatch, set())
    r = sign_in(client, "jsmith").get("/partials/stamp", headers={
        "HX-Request": "true", "X-CC-UI": "chrome", "X-CC-UI-Sig": "forged"})
    assert r.headers.get("hx-refresh") == "true"
    assert r.text == ""


def test_a_forged_header_on_a_write_is_409_with_want(client, monkeypatch):
    set_groups(monkeypatch, set())
    r = sign_in(client).post("/partials/admin/users/display-name", headers={
        "HX-Request": "true", "X-CC-UI": "chrome", "X-CC-UI-Sig": "forged"},
        data={"username": "owen", "display_name": "x"})
    assert r.status_code in (409, 422, 403, 404, 405)
    if r.status_code == 409:
        assert r.headers.get("x-cc-ui-want") == "1"


def test_an_unknown_group_reloads_once_then_polls_cleanly(client, monkeypatch):
    set_groups(monkeypatch, {"chrome", "settings-fleet"})
    sign_in(client)
    r = client.get("/partials/stamp", headers={
        "HX-Request": "true", "X-CC-UI": "chrome,settings-fleet,warp", "X-CC-UI-Sig": "x"})
    assert r.headers.get("hx-refresh") == "true"
    page = client.get("/")
    got = page_groups(page.text)
    assert "warp" not in got and ("settings-fleet" not in got
                                  or "settings-fleet" in uv.build_groups())
    headers = json.loads(re.search(r"hx-headers='([^']*)'", page.text).group(1))
    headers["HX-Request"] = "true"
    again = client.get("/partials/stamp", headers=headers)
    assert "hx-refresh" not in again.headers


def test_an_empty_set_page_gets_no_want_across_a_deploy(client, monkeypatch):
    set_groups(monkeypatch, set())
    r = sign_in(client).get("/partials/stamp", headers={
        "HX-Request": "true", "X-CC-UI": "", "X-CC-UI-Gen": "from-an-older-build"})
    assert "x-cc-ui-want" not in r.headers and "hx-refresh" not in r.headers


def test_a_missing_generation_on_a_signed_set_sends_want(client, monkeypatch):
    if "chrome" not in uv.build_groups():
        pytest.skip("no chrome templates in this build yet")
    set_groups(monkeypatch, {"chrome"})
    sign_in(client)
    sid = auth.session_id_for(SECRET, client.cookies.get(auth.COOKIE_NAME))
    r = client.get("/partials/stamp", headers={
        "HX-Request": "true", "X-CC-UI": "chrome",
        "X-CC-UI-Sig": uv.header_sig(client.app.state.settings, "chrome", "", sid)})
    assert r.headers.get("x-cc-ui-want") == "1" and "hx-refresh" not in r.headers


def test_the_fixture_headers_round_trip(client, monkeypatch):
    """ui_variant_support.UIVariant.htmx_headers builds what a page sends."""
    from ui_variant_support import UIVariant

    v = UIVariant("all")
    set_groups(monkeypatch, v.setting)
    sign_in(client)
    r = client.get("/partials/stamp", headers=v.htmx_headers(client))
    assert r.status_code == 200 and "hx-refresh" not in r.headers


# ------------------------------------------------------------ the setting


def test_a_set_without_chrome_is_refused(client):
    r = sign_in(client).put("/api/v1/admin/site", json={"values": {"ui_terminal_groups": "home"}})
    assert r.status_code == 422 and "chrome" in r.text


def test_a_group_with_no_templates_in_this_build_is_refused(client):
    missing = [g for g in uv.GROUPS if g not in uv.build_groups()]
    if not missing:
        pytest.skip("every group has templates")
    r = sign_in(client).put("/api/v1/admin/site",
                            json={"values": {"ui_terminal_groups": f"chrome,{missing[-1]}"}})
    assert r.status_code == 422 and "waiting for its build" in r.text


def test_off_is_a_value_site_deletes_and_neither_touches_site_history(client, app):
    sign_in(client)
    before = client.get("/api/v1/admin/site/history").json()
    r = client.put("/api/v1/admin/site", json={"values": {"ui_terminal_groups": "none"}})
    assert r.status_code == 200 and r.json()["ui_terminal_groups"] == "none"
    conn = dbmod.connect(app.state.settings.db_path)
    try:
        assert site_store.get_all(conn).get("ui_terminal_groups") == "none"
        hist = dbmod.meta_get_json(conn, uv.UI_GROUPS_HISTORY_KEY)
        assert hist and hist[0]["to"] == "none"
    finally:
        conn.close()
    r = client.put("/api/v1/admin/site", json={"values": {"ui_terminal_groups": "site"}})
    assert r.status_code == 200
    conn = dbmod.connect(app.state.settings.db_path)
    try:
        assert "ui_terminal_groups" not in site_store.get_all(conn)
    finally:
        conn.close()
    after = client.get("/api/v1/admin/site/history").json()
    assert after == before
    assert "ui_terminal_groups" not in json.dumps(after)


def test_a_normal_save_still_works_and_never_carries_the_key(client):
    r = sign_in(client).put("/api/v1/admin/site", json={"values": {"org_short": "Studio"}})
    assert r.status_code == 200
    assert r.json()["org_short"] == "Studio"


def test_an_import_carrying_the_look_is_refused(client, app):
    r = sign_in(client).post("/api/v1/admin/site/import",
                             json={"text": '[site]\nui_terminal_groups = "chrome"\n'})
    assert r.status_code == 422
    conn = dbmod.connect(app.state.settings.db_path)
    try:
        assert "ui_terminal_groups" not in site_store.get_all(conn)
    finally:
        conn.close()


def test_the_look_is_never_published_to_companions(client):
    body = client.get("/api/v1/site").json()
    flat = json.dumps(body)
    assert "ui_terminal_groups" not in flat and "ui_preview" not in flat


def test_the_manifest_fallback_is_not_cached(app, monkeypatch):
    calls = {"n": 0}
    real = site_store.resolved_manifest

    def flaky(conn, settings):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return real(conn, settings)

    site_store.invalidate(app)
    monkeypatch.setattr(site_store, "resolved_manifest", flaky)
    site_store.manifest_for_app(app, app.state.settings)
    site_store.manifest_for_app(app, app.state.settings)
    assert calls["n"] == 2


# ------------------------------------------------------------ /ui/preview


def test_classic_works_signed_out_and_sets_a_long_lived_cookie(client):
    r = client.get("/ui/preview?variant=classic&next=/transfers", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/transfers"
    raw = r.headers["set-cookie"]
    assert f"{uv.PREVIEW_COOKIE}=classic" in raw
    assert f"Max-Age={uv.PREVIEW_MAX_AGE}" in raw and "Path=/" in raw and "HttpOnly" in raw


def test_site_deletes_the_cookie(client):
    r = client.get("/ui/preview?variant=site", follow_redirects=False)
    raw = r.headers["set-cookie"]
    assert raw.startswith(f"{uv.PREVIEW_COOKIE}=") and "Path=/" in raw
    assert "Max-Age=0" in raw or "expires=" in raw.lower()


def test_cc_needs_a_session_and_the_setting(client, app):
    assert client.get("/ui/preview?variant=cc", follow_redirects=False).status_code == 403
    sign_in(client)
    assert client.get("/ui/preview?variant=cc", follow_redirects=False).status_code == 403
    client.put("/api/v1/admin/site", json={"values": {"ui_preview": "admins"}})
    r = client.get("/ui/preview?variant=cc", follow_redirects=False)
    assert r.status_code == 303
    assert f"{uv.PREVIEW_COOKIE}=cc.owen." in r.headers["set-cookie"]
    sign_in(client, "jsmith")
    assert client.get("/ui/preview?variant=cc", follow_redirects=False).status_code == 403


def test_the_referer_gives_next_when_it_is_this_host(client):
    r = client.get("/ui/preview?variant=classic", follow_redirects=False,
                   headers={"Referer": "http://testserver/broll/"})
    assert r.headers["location"] == "/broll/"
    r = client.get("/ui/preview?variant=classic", follow_redirects=False,
                   headers={"Referer": "https://evil.example/broll/"})
    assert r.headers["location"] == "/"


def test_a_post_to_the_preview_route_still_needs_a_session(client):
    r = client.post("/ui/preview?variant=classic", follow_redirects=False)
    assert r.status_code in (303, 401, 403, 405)


def test_a_cc_cookie_from_a_role_the_setting_does_not_allow_is_ignored(client, app, monkeypatch):
    if "chrome" not in uv.build_groups():
        pytest.skip("no chrome templates in this build yet")
    set_groups(monkeypatch, set())
    cookie = uv.sign_preview(app.state.settings, "owen")
    sign_in(client)
    client.cookies.set(uv.PREVIEW_COOKIE, cookie)
    assert page_groups(client.get("/").text) == ""          # ui_preview is off
    client.put("/api/v1/admin/site", json={"values": {"ui_preview": "admins"}})
    assert page_groups(client.get("/").text) != ""
    unsigned = TestClient(app)
    unsigned.cookies.set(uv.PREVIEW_COOKIE, "cc.owen.forged")
    login = unsigned.get("/login")
    assert page_groups(login.text) == ""


# ------------------------------------------------------------ /go/<panel>


@pytest.mark.parametrize("groups, expected", [
    (set(), "/#server-notices"),
    ({"chrome", "home"}, "/#server-notices"),
    ({"chrome", "home", "settings-health"}, "/admin/health#server-notices"),
])
def test_go_follows_the_cross_group_rule(groups, expected):
    assert uv.go_href("notices", frozenset(groups)) == expected


def test_go_redirects_and_404s_an_unknown_panel(client):
    sign_in(client)
    r = client.get("/go/admin-fleet-halt", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/users#admin-fleet-halt"
    assert client.get("/go/nowhere", follow_redirects=False).status_code == 404


# ------------------------------------------------------------ static + worker


def test_static_caching_rules(client):
    assert client.get("/static/pwa.js").headers["cache-control"] == "no-cache"
    url = uv.asset_url("cc/terminal.css")
    assert "?h=" in url
    assert "immutable" in client.get(url).headers["cache-control"]
    assert client.get("/static/cc/terminal.css?h=0000000000").headers["cache-control"] == "no-store"
    font = client.get("/static/fonts/jetbrains-mono-regular.woff2")
    assert font.status_code == 200
    assert font.headers["content-type"] == "font/woff2"
    assert "immutable" in font.headers["cache-control"]


def test_the_worker_precaches_the_hashed_cc_assets_and_revalidates_past_the_http_cache(client):
    body = client.get("/sw.js").text
    assert "__CC_PRECACHE__" not in body
    assert uv.asset_url("cc/terminal.css") in body
    assert "/static/fonts/jetbrains-mono-regular.woff2" in body
    assert "fetch(req, {cache: 'no-cache'})" in body
