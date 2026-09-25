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

Converted 2026-09-25 when the CC Terminal look replaced the classic one: the
same findings, pinned on the terminal markup (tags, not [ BRACKET ] chips;
shell.html, not base.html; the terminal sheets, not style.css/mobile.css).
"""
from __future__ import annotations

from pathlib import Path

import re

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
    # ...rendered as the tag's title, which is what a tap opens.
    assert re.search(r'<span class="tag warn" title="2 Syncthing peer\(s\) connected via a RELAY[^"]*">'
                     r'<span class="w">relayed: 2</span>', body)
    # The sheet is on every page and outside the 15 s swap.
    assert '{% include "partials/hint_sheet.html" %}' in (
        TEMPLATES / "shell.html").read_text(encoding="utf-8")
    assert 'id="chip-sheet"' in page(client, "/")
    js = (STATIC / "htmx_errors.js").read_text(encoding="utf-8")
    assert "chip-sheet" in js and "data-chip-detail" in js and ".tag[title]" in js
    # A coarse pointer has no hover, which is the whole finding: a tag that
    # explains itself is a full tap target there.
    phone = (STATIC / "cc" / "phone.css").read_text(encoding="utf-8")
    coarse = phone[phone.index("@media (pointer: coarse)"):]
    coarse = coarse[:coarse.index("}")]
    assert ".tag:is([title], [data-tip])" in coarse


# ------------------------------------------------------------------- DUI-6

def test_a_refusal_renders_beside_the_button_that_caused_it(env):
    """Every panel in the finding marks its error banner, and the mover in
    htmx_errors.js matches it to the control whose request it answered."""
    client, _ = env
    panels = ["admin_users", "admin_packages", "admin_jobs", "fleet_halt",
              "admin_report_tokens", "fleet_grid"]
    for name in panels:
        source = (TEMPLATES / "partials" / f"{name}.html").read_text(encoding="utf-8")
        assert re.search(r'class="note err error-banner"[^>]*>(<span class="grow">)?'
                         r'\{\{ error \}\}', source), name
    assert 'class="note err error-banner"' in (
        TEMPLATES / "setup.html").read_text(encoding="utf-8")
    js = (STATIC / "htmx_errors.js").read_text(encoding="utf-8")
    assert ".error-banner" in js and "form-error" in js
    # The setup wizard clears an error on success, which it never did: there
    # was no showError(null) call site anywhere in the file.
    setup = (STATIC / "cc" / "setup.js").read_text(encoding="utf-8")
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
    # No machine on either row (an older companion's report), so the sentence
    # names none: it never claims to know which computer the browser is on
    # (dash-mounts-ui-2, 2026-09-11).
    assert "4 files still uploading (" in busy["sentence"]  # ui-dash-main-10 (2026-09-25)
    assert "this computer" not in busy["sentence"]
    # An ADMIN's view is the fleet's, which has no "this computer" in it.
    assert ui.safe_to_close({"transfers": [], "queues": []}, None) is None
    assert "Safe to close" not in page(client, "/transfers")
    # ...and the editor's own page carries it, not only the helper.
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen-ed"))
    resp = client.get("/transfers")
    assert resp.status_code == 200, resp.text
    assert "Safe to close: nothing is transferring." in resp.text
    # The terminal's four homes for the sentence: the transfers page, the
    # home page's live transfers and queue, and a person's own queue.
    for name in ("partials/transfers.html", "partials/home_transfers.html",
                 "partials/home_queue.html", "partials/person_queue.html"):
        assert "safe_to_close.sentence" in (TEMPLATES / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ DUI-20

def test_a_wired_computer_says_where_the_setting_lives(env):
    """CR-88: wired or remote is that COMPUTER's own setting, and the greyed
    grid never said so. CR-95's rule is untouched - only a wired cell that is
    NOT ticked is disabled."""
    route = "Change it on that computer: tray, Settings, This computer."
    grid = (TEMPLATES / "admin_assignments.html").read_text(encoding="utf-8")
    # The column head, the disabled cell and the stale-tick cell.
    assert grid.count(route) == 3
    assert "<b>wired</b>: set on that computer</span>" in grid
    assert "{% if wired and not ticked %}disabled" in grid
    # The classic sidebar's rail is the home page's project tree now.
    tree = (TEMPLATES / "partials" / "projects_tree.html").read_text(encoding="utf-8")
    assert route in tree


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
    # CR-335 (2026-09-25) gave every MAKE CURRENT form (the held row, its
    # MAKE CURRENT ANYWAY, the vendor row and its override) the same busy
    # state, so the panel carried eight, not four; the terminal row's "roll
    # back to" shortcut (5.3, wave 6) is the ninth.
    assert source.count('hx-indicator="this"') == 9
    assert '<span class="busy-t">asking that computer</span>' in source
    # The busy word is shown by the in-flight class htmx puts on the form.
    css = (STATIC / "cc" / "settings_fleet.css").read_text(encoding="utf-8")
    assert ".sf-pkg form.htmx-request .key .busy-t { display: inline; }" in css
    assert ".sf-pkg form.htmx-request .key .t { display: none; }" in css
    assert '<div class="admin-packages-box sf-pkg' in source


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
    assert '<span class="t">roll the fleet back</span>' in body
    assert 'value="1.0.39"' in body  # the option list is that kind's, not companion's


# ------------------------------------------------------------------- RES-6

# The terminal tag tones: green -> ok, amber -> warn, red -> err.
@pytest.mark.parametrize("state,colour,label", [
    ("running", "ok", "cards: FF5 CUT"),
    ("refused", "warn", "cards refused"),
    ("unreachable", "warn", "cards offline"),
    ("stopped", "err", "cards stopped"),
    ("credential_refused", "err", "cards signed out"),
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
    tag = re.search(r'<span class="tag ' + colour + r'" title="([^"]*)"><span class="w">'
                    + re.escape(label), body)
    assert tag, (state, colour, label)
    assert "the dashboard answered HTTP 401" in tag.group(1)


def test_an_older_companion_still_reads_as_running(env):
    """No `state` at all is a build that predates RES-6: `connected` is all it
    ever sent, and it must render as it did rather than as an alarm."""
    _, conn = env

    def mutate(e):
        e["capabilities"]["cards_agent"] = {"connected": True, "state": "",
                                            "timeline": "FF5 CUT", "version": 5}

    body = render_grid(conn, mutate)
    assert re.search(r'<span class="tag ok" title="[^"]*"><span class="w">cards: FF5 CUT v5</span>',
                     body)


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
    assert '<span class="w">cards' not in body


# ---------------------------------------------------------------- DCORE-16

def test_a_held_sharing_change_is_rendered(env):
    """record_enforce_plan wrote the note and the alert fired on it; the two
    pages an admin opens said nothing at all."""
    _, conn = env
    notes = [{"at": dbmod.utcnow_iso(),
              "note": "applied 9 of 40; syncthing refused the rest"}]
    # The collector's panel is on Health now (partials/health_collector.html,
    # the terminal twin of the classic collector_health.html).
    health = ui.templates.env.get_template("partials/health_collector.html").render(
        collector={"kinds": [], "enforce_plan": None,
                   "enforce_notes": notes, "collector_stale": False},
        session_is_admin=True)
    assert "Sharing change held: applied 9 of 40" in health
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
    assert '<span class="w">youtube clips waiting for resolve: 8</span>' in body
    assert "waiting to go into Resolve (Resolve is closed)" in body

    def gave_up(e):
        e["youtube_import"] = {"state": "no-project-match", "pending": 0,
                               "reason": "this project has no server folder yet",
                               "at": dbmod.utcnow_iso()}

    body = render_grid(conn, gave_up)
    assert '<span class="w">youtube import gave up</span>' in body
    assert "this project has no server folder yet" in body

    # A companion that does not send the section renders nothing at all.
    assert "youtube" not in render_grid(conn).lower()
