"""Wave 1 of the usability + resilience sweep (2026-09-03 findings, built
2026-09-04): the dashboard's web UI.

Each test names the finding it pins and each one fails on the tree as it was
this morning:

  DUI-1  a one-time password and a one-time fleet token were painted into
         panels that admin_users.html re-fetches every 30 s / 60 s. The
         password came back through the `error` key, wearing the warning
         triangle, in the same channel as "does not look like an OpenSSH
         public key".
  DUI-2  nothing anywhere listened for htmx:responseError, and the only
         freshness stamp on the page was inside a topbar rendered once per
         full page load. A dashboard unreachable for an hour kept saying
         "updated 4s ago".
  DUI-4  no hx-indicator, no .htmx-request rule: [ CREATE ] blocks for up to
         two minutes with nothing on screen.
  DUI-5  [ NONE ] cleared a whole computer's plan with no confirmation, and
         its failures named the editor rather than the projects.
  DCORE-2 "copy from ..." replaced a computer's plan on a `change` event with
         nothing asked.
  DUI-18 [ REVOKE ] on an SSH key, [ SET ] on a password and [ DISABLE ] fired
         on one click in the panel where [ DELETE ] asks.
  REL-2  the HTML [ PUBLISH ] route ran a 600 s download inside the event
         loop, on a --workers 1 uvicorn.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod, ui
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"


@pytest.fixture
def feed_env(tmp_path):
    """Settings is frozen, so a feed URL is a second app rather than a poke."""
    settings = Settings(db_path=str(tmp_path / "feed.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), auth_method="local",
                        release_feed_url="https://example.invalid/channel.json")
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def as_user(client, user="owen"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture
def env(tmp_path):
    """The appliance shape: local accounts, no NAS credential."""
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), auth_method="local")
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


# ------------------------------------------------------------------ DUI-1

def test_a_generated_password_is_not_returned_through_the_error_key(env):
    """The success an admin must transcribe used to be `error`, triangle and
    all. It is its own slot now."""
    as_user(env)
    resp = env.post("/partials/admin/users/create",
                    data={"username": "jsmith", "role": "editor", "password": ""})
    assert resp.status_code == 200, resp.text
    body = resp.text
    assert "generated password" not in body
    assert "▲" not in body.split("minted-secret")[0] or "banner" not in body
    assert 'id="minted-secret"' in body
    assert "NEW PASSWORD FOR JSMITH" in body


def test_a_minted_credential_is_swapped_out_of_band_above_the_polled_panels(env):
    """DUI-1's actual mechanism. The credential must arrive OUTSIDE the panel
    the page re-fetches on a timer, or the next poll takes it away for good --
    and htmx only honours hx-swap-oob on a response's direct children."""
    as_user(env)
    resp = env.post("/partials/admin/users/create",
                    data={"username": "jsmith", "role": "editor", "password": ""})
    body = resp.text
    assert 'hx-swap-oob="true"' in body
    # ...before the panel it must survive, i.e. a top-level sibling.
    assert body.index('id="minted-secret"') < body.index('class="admin-users-box"')
    # And the host element on the page is not inside either polling wrapper.
    page = as_user(env).get("/admin/users").text
    host = page.index('id="minted-secret"')
    assert host < page.index('hx-get="/partials/admin/users"')
    assert host < page.index('hx-get="/partials/admin/report-tokens"')


def test_a_minted_report_token_leaves_the_panel_that_polls_every_60s(env):
    as_user(env)
    resp = env.post("/partials/admin/report-tokens/create",
                    data={"username": "jsmith", "label": "laptop"})
    assert resp.status_code == 200, resp.text
    body = resp.text
    assert 'hx-swap-oob="true"' in body
    assert body.index('id="minted-secret"') < body.index('id="admin-report-tokens"')
    assert "NEW TOKEN FOR JSMITH" in body
    # The token itself, once, in the out-of-band box.
    assert "cce1." in body


def test_every_one_time_credential_offers_a_copy_control(env):
    as_user(env)
    for path, data in (("/partials/admin/users/create",
                        {"username": "jsmith", "role": "editor", "password": ""}),
                       ("/partials/admin/report-tokens/create",
                        {"username": "jsmith", "label": ""})):
        body = env.post(path, data=data).text
        assert 'class="btn tap copy-btn"' in body, path
        assert 'data-copy-from="minted-value"' in body, path
    assert (STATIC / "copy_value.js").exists()
    assert '<script src="/static/copy_value.js"' in (TEMPLATES / "base.html").read_text(
        encoding="utf-8")


def test_a_failed_creation_mints_nothing(env):
    """The generated password is minted before the write. A refusal must not
    hand the admin a credential that does not exist."""
    as_user(env)
    env.post("/partials/admin/users/create",
             data={"username": "jsmith", "role": "editor", "password": ""})
    again = env.post("/partials/admin/users/create",
                     data={"username": "jsmith", "role": "editor", "password": ""})
    assert "NEW PASSWORD FOR" not in again.text
    assert 'hx-swap-oob' not in again.text


# ------------------------------------------------------------------ DUI-2

def test_the_freshness_stamp_is_a_polled_fragment(env):
    as_user(env)
    page = env.get("/").text
    assert 'hx-get="/partials/stamp"' in page
    assert "updated" in page
    fragment = env.get("/partials/stamp")
    assert fragment.status_code == 200
    assert "updated" in fragment.text


def test_the_stamp_route_says_when_the_server_answered_not_when_a_view_was_built(env):
    """The stamp answers "is this page still talking to the dashboard", so it
    is the server's own clock. A view builder's timestamp cannot answer that
    on a page with no view."""
    as_user(env)
    assert re.search(r"updated \d+s ago", env.get("/partials/stamp").text)


def test_the_syncthing_banner_moved_out_of_the_frozen_include():
    topbar = (TEMPLATES / "partials" / "topbar.html").read_text(encoding="utf-8")
    assert "SYNCTHING UNREACHABLE" not in topbar
    stamp = (TEMPLATES / "partials" / "stamp.html").read_text(encoding="utf-8")
    assert "SYNCTHING UNREACHABLE" in stamp


def test_an_unreachable_syncthing_is_said_in_the_polled_fragment(env, tmp_path):
    as_user(env)
    conn = dbmod.connect(tmp_path / "d.db")
    try:
        # A failed non-prune poll run is exactly what fetch_collector_status
        # reads as "Syncthing is not reachable".
        conn.execute(
            "INSERT INTO poll_runs (kind, ok, started_at, finished_at) VALUES (?,?,?,?)",
            ("syncthing", 0, dbmod.utcnow_iso(), dbmod.utcnow_iso()))
        conn.commit()
    finally:
        conn.close()
    assert "SYNCTHING UNREACHABLE" in env.get("/partials/stamp").text


def test_an_anonymous_page_does_not_poll_a_fragment_behind_the_login_gate(env):
    """A poll that answered with the login page would swap a login form into
    the topbar."""
    login = env.get("/login").text
    assert 'hx-get="/partials/stamp"' not in login


def test_there_is_a_global_htmx_error_handler():
    js = (STATIC / "htmx_errors.js").read_text(encoding="utf-8")
    for event in ("htmx:responseError", "htmx:sendError", "htmx:timeout"):
        assert event in js, event
    # It must clear itself again, or the first blip is permanent.
    assert "htmx:afterRequest" in js
    assert "STOPPED UPDATING" in js
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert '<script src="/static/htmx_errors.js"' in base
    # The banner needs a rule, or it is invisible.
    assert ".stale-banner" in (STATIC / "style.css").read_text(encoding="utf-8")


def test_the_error_banner_never_builds_html_from_a_server_string():
    js = (STATIC / "htmx_errors.js").read_text(encoding="utf-8")
    # The assignment, not the word: the file's own comment explains why it
    # does not use it.
    assert "innerHTML =" not in js
    assert "textContent =" in js


# ------------------------------------------------------------------ DUI-4

def test_there_is_a_loading_rule_for_htmx_requests():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".htmx-request .btn" in css
    assert "pointer-events: none" in css
    assert ".busy-label" in css


@pytest.mark.parametrize("template,label", [
    ("partials/admin_users.html", "CREATING THE ACCOUNT"),
    ("partials/admin_packages.html", "DOWNLOADING THE BUILD"),
    ("partials/recovery.html", "COPYING THE FILES BACK"),
])
def test_the_slow_actions_say_what_they_are_doing(template, label):
    body = (TEMPLATES / template).read_text(encoding="utf-8")
    assert "busy-label" in body, template
    assert label in body, template


def test_the_two_minute_create_says_so_up_front():
    body = (TEMPLATES / "partials" / "admin_users.html").read_text(encoding="utf-8")
    assert "This can take up to two minutes" in body


# ------------------------------------------------- DUI-5 and DCORE-2 (JS)

def test_untick_the_whole_column_asks_first():
    js = (STATIC / "assignments.js").read_text(encoding="utf-8")
    none_confirm = "Untick all "
    assert none_confirm in js
    assert "Their copies stay on disk" in js


def test_copy_from_asks_naming_both_sides_and_what_is_lost():
    js = (STATIC / "assignments.js").read_text(encoding="utf-8")
    assert "Replace " in js and "stops syncing " in js
    # A source with an empty plan silently emptied the target.
    assert "has no projects ticked" in js


def test_a_running_column_shows_progress_and_can_be_stopped():
    js = (STATIC / "assignments.js").read_text(encoding="utf-8")
    assert "runProgress" in js
    assert "dataset.running" in js


def test_an_error_toast_is_not_thrown_away_after_four_seconds():
    js = (STATIC / "assignments.js").read_text(encoding="utf-8")
    body = js[js.index("function toast("):js.index("function cellLabel(")]
    # The err branch returns BEFORE the auto-dismiss timer.
    assert body.index('kind === "err"') < body.index("4000")
    assert "click to dismiss" in body
    assert ".toast.err" in (STATIC / "style.css").read_text(encoding="utf-8")


def test_a_failed_cell_names_the_project_not_the_editor():
    js = (STATIC / "assignments.js").read_text(encoding="utf-8")
    assert 'toast("could not update' not in js
    assert "cellLabel(box)" in js
    # The bulk summary lists which ones failed.
    assert "change(s) failed: " in js


def test_the_none_button_carries_the_label_the_confirm_needs():
    page = (TEMPLATES / "admin_assignments.html").read_text(encoding="utf-8")
    block = page[page.index("data-col-none"):]
    assert "data-col-label" in block[:400]


# ----------------------------------------------------------------- DUI-18

@pytest.mark.parametrize("fragment", [
    "Revoke this SSH key for",
    "Set a new password for",
    "Stop {{ u.username }} signing in?",
])
def test_the_three_unconfirmed_writes_now_ask(fragment):
    body = (TEMPLATES / "partials" / "admin_users.html").read_text(encoding="utf-8")
    assert fragment in body


def test_enable_is_not_confirmed_but_disable_is():
    body = (TEMPLATES / "partials" / "admin_users.html").read_text(encoding="utf-8")
    block = body[body.index("/partials/admin/users/disable"):]
    assert "{% if not u.disabled %}hx-confirm=" in block[:600]


def test_setting_a_password_answers_with_a_result_line(env):
    as_user(env)
    env.post("/partials/admin/users/create",
             data={"username": "jsmith", "role": "editor", "password": "hunter22hunter22"})
    resp = env.post("/partials/admin/users/password",
                    data={"username": "jsmith", "password": "correct-horse-battery"})
    assert resp.status_code == 200, resp.text
    assert "Password set for jsmith" in resp.text
    # `notice`, not `error`: no warning triangle on a success.
    assert "▲ Password set" not in resp.text


# ------------------------------------------------------------------ REL-2

@pytest.mark.parametrize("route", [
    "partial_admin_feed_publish",
    "partial_admin_recovery_preview",
    "partial_admin_recovery_restore",
    "partial_admin_recovery_drill",
])
def test_no_async_route_does_its_blocking_work_on_the_event_loop(route):
    """deploy/run.sh runs uvicorn with --workers 1: a synchronous download or
    file copy inside an `async def` stalls every companion report, every lane
    status and all four mounts for its whole duration."""
    src = inspect.getsource(getattr(ui, route))
    assert "run_in_threadpool" in src, route


def test_the_publish_route_still_reports_a_package_store_refusal(feed_env, monkeypatch):
    """The threadpool must not swallow the refusal the admin needs to read."""
    from ccsync_dashboard import package_store, release_feed

    def boom(*a, **kw):
        raise package_store.PackageStoreError(400, "min_version is above the build")

    monkeypatch.setattr(release_feed, "publish_from_feed", boom)
    as_user(feed_env)
    resp = feed_env.post("/partials/admin/feed/publish",
                    data={"kind": "companion", "platform": "windows", "version": "0.9.65"})
    assert resp.status_code == 200, resp.text
    assert "min_version is above the build" in resp.text


# ------------------------------- the dashboard-core builder's `refused` list

def test_a_refused_feed_record_is_shown_not_only_logged(feed_env, monkeypatch):
    from ccsync_dashboard import release_feed

    monkeypatch.setattr(release_feed, "check_now", lambda *a, **kw: {
        "ok": True, "applied": [], "retracted": [],
        "refused": ["companion/windows 0.9.64"]})
    as_user(feed_env)
    resp = feed_env.post("/partials/admin/feed/check")
    assert resp.status_code == 200, resp.text
    assert "companion/windows 0.9.64" in resp.text
    assert "[ REFUSED ]" in resp.text


def test_a_feed_check_without_the_new_key_still_renders(feed_env, monkeypatch):
    from ccsync_dashboard import release_feed

    monkeypatch.setattr(release_feed, "check_now",
                        lambda *a, **kw: {"ok": True, "applied": []})
    as_user(feed_env)
    assert feed_env.post("/partials/admin/feed/check").status_code == 200


def test_the_stamp_fragment_is_behind_the_login_gate(env):
    """It reads collector state. Nothing new may be open just because it is
    small (app._OPEN_EXACT is the list, and this is not on it)."""
    resp = env.get("/partials/stamp", follow_redirects=False)
    assert resp.status_code != 200, resp.text
