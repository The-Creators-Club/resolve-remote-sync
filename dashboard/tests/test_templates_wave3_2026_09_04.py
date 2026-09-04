"""Wave 3 of the usability + resilience sweep, the dashboard's own pages
(findings 2026-09-03, built 2026-09-04): "the machine says what it knows".

One test per finding, each of which fails on the tree as it was this morning:

  DUI-3   every chip explained itself in `title=` alone, which a phone cannot
          show, and eighteen of them can stack in one LANES cell.
  DUI-6   the error always rendered at the top of a panel that swaps
          outerHTML; the button that earned it is at the bottom.
  DUI-19  the editor's own page never answered "am I safe to close my laptop".
  DUI-20  a wired computer's cells were greyed out with no route to the
          setting that made them so (CR-88: it is that computer's own).
  REL-11  the feed panel said when it last checked and never when it will
          check again, on a default interval of a DAY.
  REL-12  none of the four long-running controls on Packages showed that
          anything was happening.
  REL-16  [ ROLL THE FLEET BACK ] was offered for companions only.
  RES-6   the cards chip was green whenever `connected` was true, including
          while the role's loop was dead or had been 401-ing for hours.
  DCORE-16 a HELD sharing change was recorded and rendered nowhere.
  CYT-3   YouTube clips that land on disk and never reach Resolve reached
          nobody at either end.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, ui
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"

SECRET = "s" * 32
FF5 = "2026-ff5-elections"


@pytest.fixture
def env(tmp_path):
    """One project, one computer that has reported, one file going UP."""
    app = create_app(Settings(
        db_path=str(tmp_path / "d.db"), session_secret=SECRET,
        report_token="sekrit", admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "d.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, FF5, "2026/FF5/Elections", f"/data/{FF5}", now)
        dbmod.add_selection(conn, "owen", FF5, created_by="owen", now=now)
        conn.commit()
        resp = client.post("/api/v1/report", json={
            "editor_name": "owen", "machine": "EDIT-PC",
            "companion_version": "0.9.66", "reported_at": now,
            "lanes": [{"name": "lane_a_originals_up", "state": "syncing",
                       "queued": 3, "transferring": 1, "last_error": None,
                       "last_sync": None}],
        }, headers={"X-CCSync-Token": "sekrit",
                    "X-CCSync-Identity": auth.make_identity_token(SECRET, "owen")})
        assert resp.status_code == 200, resp.text
        yield client, conn
        conn.close()


def as_owner(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def page(client, url: str) -> str:
    resp = as_owner(client).get(url)
    assert resp.status_code == 200, resp.text
    return resp.text


def render_grid(conn, mutate=None) -> str:
    """The fleet grid on a fabricated row.

    Rendered through ui.templates so the real filters and the real chip_help
    global are in play, and mutated in the VIEW rather than in the report, so
    a test for a chip does not also depend on the day a companion field lands
    in the ingest model.
    """
    from ccsync_dashboard.api import build_editors_view

    fleet = build_editors_view(conn)
    if mutate:
        mutate(fleet["editors"][0])
    template = ui.templates.env.get_template("partials/fleet_grid.html")
    return template.render(
        fleet=fleet, view={"fleet_status": "green", "projects": []},
        session_is_admin=True, error=None,
    )


# ------------------------------------------------------------------- DUI-3

def test_a_chip_explains_itself_from_one_dict_and_a_tap_opens_it(env):
    """The prose has ONE home (ui.CHIP_HELP) and the phone can reach it: the
    tooltip and the sheet are the same sentence, so they cannot drift."""
    client, conn = env
    body = render_grid(conn, lambda e: e["transport"].update(
        {"relayed": 2, "direct": 0, "at": dbmod.utcnow_iso()}))
    # The chip's explanation on the page is the dict's, filled in.
    assert "limited to relay speed (1-5 MB/s)" in ui.CHIP_HELP["relayed"]
    assert "2 Syncthing peer(s) connected via a RELAY" in body
    # ...and the template does not carry a second copy of it.
    source = (TEMPLATES / "partials" / "fleet_grid.html").read_text(encoding="utf-8")
    assert "limited to relay speed" not in source
    assert "chip_help('relayed'" in source
    # The sheet is on every page and outside the 15 s swap.
    assert '{% include "partials/chip_sheet.html" %}' in (
        TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert 'id="chip-sheet"' in page(client, "/")
    js = (STATIC / "htmx_errors.js").read_text(encoding="utf-8")
    assert "chip-sheet" in js and "data-chip-detail" in js
    # A coarse pointer has no hover, which is the whole finding.
    assert ".chip[title]" in (STATIC / "mobile.css").read_text(encoding="utf-8")


# ------------------------------------------------------------------- DUI-6

def test_a_refusal_renders_beside_the_button_that_caused_it(env):
    """Every panel in the finding marks its error banner, and the mover in
    htmx_errors.js matches it to the control whose request it answered."""
    client, _ = env
    panels = ["admin_users", "admin_packages", "admin_jobs", "fleet_halt",
              "admin_report_tokens", "fleet_grid"]
    for name in panels:
        source = (TEMPLATES / "partials" / f"{name}.html").read_text(encoding="utf-8")
        assert 'class="banner error-banner">▲ {{ error }}' in source, name
    assert 'class="banner error-banner"' in (
        TEMPLATES / "setup.html").read_text(encoding="utf-8")
    js = (STATIC / "htmx_errors.js").read_text(encoding="utf-8")
    assert ".error-banner" in js and "form-error" in js
    # The setup wizard clears an error on success, which it never did: there
    # was no showError(null) call site anywhere in the file.
    setup = (STATIC / "setup.js").read_text(encoding="utf-8")
    assert "function clearErrors()" in setup
    assert setup.count("clearErrors();") >= 5
    assert "showError(\"could not accept the EULA: \" + err.message, acceptBtn)" in setup


# ------------------------------------------------------------------ DUI-19

def test_the_editor_is_told_whether_the_laptop_can_be_closed(env):
    """One sentence, on the editor's own page, from what the panel already
    holds. An admin's fleet-wide view has no `this computer`, so it says
    nothing rather than guessing."""
    client, conn = env
    quiet = ui.safe_to_close({"transfers": [], "queues": []}, "owen")
    assert quiet["safe"] and quiet["sentence"] == "Safe to close: nothing is transferring."
    busy = ui.safe_to_close({
        "transfers": [{"editor": "owen", "direction": "up", "speed_bps": 1_000_000,
                       "bytes_total": 8_000_000, "bytes_done": 0}],
        "queues": [{"editor": "owen", "direction": "up", "n_files": 3,
                    "bytes": 4_000_000}],
    }, "owen")
    assert not busy["safe"]
    assert "4 file(s) still uploading from this computer" in busy["sentence"]
    # An ADMIN's view is the fleet's, which has no "this computer" in it.
    assert ui.safe_to_close({"transfers": [], "queues": []}, None) is None
    assert "Safe to close" not in page(client, "/transfers")
    # ...and the editor's own page carries it, not only the helper.
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen-ed"))
    resp = client.get("/transfers")
    assert resp.status_code == 200, resp.text
    assert "Safe to close: nothing is transferring." in resp.text
    for name in ("partials/transfers.html", "partials/my_queue.html"):
        assert "safe_to_close.sentence" in (TEMPLATES / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ DUI-20

def test_a_wired_computer_says_where_the_setting_lives(env):
    """CR-88: wired or remote is that COMPUTER's own setting, and the greyed
    grid never said so. CR-95's rule is untouched - only a wired cell that is
    NOT ticked is disabled."""
    grid = (TEMPLATES / "admin_assignments.html").read_text(encoding="utf-8")
    assert grid.count("Change it on that computer: tray, Settings, THIS COMPUTER.") == 3
    assert '<span class="muted mono-sm">set on that computer</span>' in grid
    assert "{% if wired and not ticked %}disabled" in grid
    rail = (TEMPLATES / "partials" / "sidebar.html").read_text(encoding="utf-8")
    assert "Change it on that computer: tray, Settings, THIS COMPUTER." in rail


# ------------------------------------------------------------------ REL-11

def test_the_feed_panel_says_when_it_will_check_again(tmp_path):
    """"last checked 19 hours ago" with no cadence beside it cannot answer
    "would waiting five minutes help"."""
    settings = Settings(db_path=str(tmp_path / "f.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), auth_method="local",
                        release_feed_url="https://example.invalid/channel.json",
                        release_feed_interval=86400.0)
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "f.db")
        dbmod.set_feed_state(conn, last_checked_at=dbmod.utcnow_iso(),
                             last_error=None)
        conn.commit()
        conn.close()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        body = client.get("/admin/packages").text
        assert "checks every" in body
        assert "next in about" in body
    # An unchecked feed says nothing rather than counting down from nowhere.
    assert ui._feed_next_check_seconds(None, 86400.0) is None
    assert ui._feed_next_check_seconds("2000-01-01T00:00:00Z", 86400.0) == 0


# ------------------------------------------------------------------ REL-12

def test_the_four_long_controls_on_packages_show_that_they_are_working():
    """A button that looks dead for a 60 MB download gets clicked twice."""
    source = (TEMPLATES / "partials" / "admin_packages.html").read_text(encoding="utf-8")
    for route in ("/partials/admin/feed/check", "/partials/admin/feed/publish",
                  "/partials/admin/packages/push-one"):
        for form in [f for f in source.split("<form") if route in f.split(">")[0]]:
            head = form.split(">")[0]
            assert 'hx-indicator="this"' in head, route
            assert 'hx-disabled-elt="this"' in head, route
    assert source.count('hx-indicator="this"') == 4
    assert "[ ASKING THAT COMPUTER... ]" in source
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".htmx-request .btn" in css and "form.htmx-request" in css


# ------------------------------------------------------------------ REL-16

def test_a_recalled_build_of_any_kind_can_be_rolled_back(env):
    """The recovery button used to be reachable only for `companion`, so a
    recalled build of any other kind that machines are still running had no
    control at all."""
    _, conn = env
    template = ui.templates.env.get_template("partials/admin_packages.html")
    packages = {
        "packages": [{"kind": "onboard", "platform": "windows", "version": "1.0.39",
                      "is_current": True, "retracted": False, "size_bytes": 10,
                      "sha256": "a" * 64, "published_at": None, "published_by": "owen",
                      "signature": "sig", "signed_binary": True, "soak": None,
                      "notes": "", "min_version": "", "arch": ""}],
        "retracted": [{"kind": "onboard", "platform": "windows", "version": "1.0.40",
                       "retracted_reason": "it wipes the LUT folder",
                       "machines_running": 2}],
        "arch_gaps": [], "machines_by_platform": {}, "outdated": [],
        "rollout": None, "data": None,
    }
    body = template.render(packages=packages, feed={"configured": False},
                           feed_refused=[], nas_kind="", error=None,
                           session_is_admin=True,
                           feed_interval_seconds=86400.0,
                           feed_next_check_seconds=None)
    assert "[ ROLL THE FLEET BACK ]" in body
    assert 'value="1.0.39"' in body  # the option list is that kind's, not companion's


# ------------------------------------------------------------------- RES-6

@pytest.mark.parametrize("state,colour,label", [
    ("running", "green", "[ CARDS"),
    ("refused", "amber", "[ CARDS REFUSED"),
    ("unreachable", "amber", "[ CARDS OFFLINE"),
    ("stopped", "red", "[ CARDS STOPPED"),
    ("credential_refused", "red", "[ CARDS SIGNED OUT"),
])
def test_the_cards_chip_reads_the_state_not_the_connection(env, state, colour, label):
    """`connected` stayed true through a dead loop and through hours of 401s,
    so the chip stayed green on the one machine whose page had stopped
    updating."""
    _, conn = env

    def mutate(e):
        e["capabilities"]["cards_agent"] = {
            "connected": True, "state": state, "timeline": "FF5 CUT",
            "version": 5, "gate_state": "", "detail": "the dashboard answered HTTP 401",
            "last_poll_at": dbmod.utcnow_iso(), "last_http_status": 401,
        }

    body = render_grid(conn, mutate)
    assert label in body
    assert f'class="chip {colour}"' in body
    assert "the dashboard answered HTTP 401" in body


def test_an_older_companion_still_reads_as_running(env):
    """No `state` at all is a build that predates RES-6: `connected` is all it
    ever sent, and it must render as it did rather than as an alarm."""
    _, conn = env

    def mutate(e):
        e["capabilities"]["cards_agent"] = {"connected": True, "state": "",
                                            "timeline": "FF5 CUT", "version": 5}

    body = render_grid(conn, mutate)
    assert "[ CARDS: FF5 CUT v5 ]" in body
    assert 'class="chip green"' in body


@pytest.mark.parametrize("block", [
    {"connected": False, "state": "disabled"},
    {"connected": False, "state": ""},
    {"connected": False, "state": "disabled", "detail": None, "gate_state": ""},
])
def test_a_machine_with_no_cards_role_gets_no_chip(env, block):
    """`disabled` is the companion's default block for a machine that runs no
    cards role, which is MOST of a fleet: a chip on every one of them is noise
    on the page whose job is "is anything red". Only the five health words
    (C5, 2026-09-04) put a chip on the grid, and a detail of '' or None is the
    same answer as no detail at all."""
    _, conn = env
    body = render_grid(conn, lambda e: e["capabilities"].update({"cards_agent": block}))
    assert "[ CARDS" not in body


# ---------------------------------------------------------------- DCORE-16

def test_a_held_sharing_change_is_rendered(env):
    """record_enforce_plan wrote the note and the alert fired on it; the two
    pages an admin opens said nothing at all."""
    _, conn = env
    notes = [{"at": dbmod.utcnow_iso(),
              "note": "applied 9 of 40; syncthing refused the rest"}]
    grid = ui.templates.env.get_template("partials/collector_health.html").render(
        fleet={"collector": {"kinds": [], "enforce_plan": None,
                             "enforce_notes": notes, "collector_stale": False}},
        session_is_admin=True)
    assert "Sharing change held: applied 9 of 40" in grid
    source = (TEMPLATES / "partials" / "project_detail.html").read_text(encoding="utf-8")
    assert "Sharing change held:" in source
    assert "enforce_notes | default([])" in source


# ------------------------------------------------------------------- CYT-3

def test_clips_waiting_for_resolve_are_on_the_grid(env):
    """The importer computed a full status and it reached NOBODY: the clips
    are on the disk, they are not in the media pool, and `no-project-match` is
    a per-machine misconfiguration only an admin can fix."""
    _, conn = env

    def waiting(e):
        e["youtube_import"] = {"state": "resolve-closed", "reason": "Resolve is closed",
                               "pending": 8, "at": dbmod.utcnow_iso()}

    body = render_grid(conn, waiting)
    assert "[ YOUTUBE CLIPS WAITING FOR RESOLVE: 8 ]" in body
    assert "waiting to go into Resolve (Resolve is closed)" in body

    def gave_up(e):
        e["youtube_import"] = {"state": "no-project-match", "pending": 0,
                               "reason": "this project has no server folder yet",
                               "at": dbmod.utcnow_iso()}

    body = render_grid(conn, gave_up)
    assert "[ YOUTUBE IMPORT GAVE UP ]" in body
    assert "this project has no server folder yet" in body

    # A companion that does not send the section renders nothing at all.
    assert "YOUTUBE" not in render_grid(conn)
