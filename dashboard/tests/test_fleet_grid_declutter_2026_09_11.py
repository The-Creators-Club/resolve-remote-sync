"""The COMPANIONS section of the fleet page, decluttered (2026-09-11).

The owner, looking at the section: "this whole section is also very visually
cluttered, clean it up", and about his own laptop: "also having no projects
synced should not be an error. Alex laptop just happens to have no synced
projects, not an error".

What a row was: a red sentence (on one machine the SAME sentence nested three
times), a line of lane chips, a "direct:1" chip, a Resolve line, a second line
of a dozen chips with two buttons in among them, an expander, a version.

What a row is: ONE headline, the three lanes in one fixed order, everything
else behind one collapsed details expander with a count of the things in
there that are actually wrong, and the buttons in a column of their own. The
terminal look (the only look since 2026-09-25) lists the problems themselves
inline, worst first (UI port D11), and keeps the rest behind that expander.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, health, ui
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32
FF5 = "2026-ff5-elections"

# The exact string the owner read on the grid on 2026-09-11: this dashboard's
# sentence, wrapped around the companion's sentence, wrapped around the
# sequencer's. One fact, three times, two sets of brackets.
NESTED_DETAIL = ("No projects are ticked for this computer "
                 "(Nothing to sync yet: no projects are ticked for this computer)")


# --------------------------------------------------------------- the nesting

def test_a_detail_that_only_says_the_sentence_again_is_dropped():
    row = {"guard": {"blocked_reason": "no_selection",
                     "blocked_detail": NESTED_DETAIL}}
    code, sentence = health.why_not_syncing(row, dbmod.utcnow_iso())
    assert code == "no_selection"
    assert sentence == "Nothing ticked for this computer"
    assert "(" not in sentence
    # The failure mode in one assertion: no clause of it appears twice.
    assert sentence.lower().count("ticked") == 1


def test_a_detail_nested_in_itself_is_unnested_not_repeated():
    """The general rule, not the no_selection special case: a companion that
    wraps its own sentence in brackets around a restatement of itself keeps
    the head, loses the echo, and is still appended once."""
    echoed = ("Proxy download is stopped as a safety measure: 412 files "
              "vanished (proxy download is stopped as a safety measure: "
              "412 files vanished)")
    row = {"guard": {"blocked_reason": "breaker_tripped",
                     "blocked_detail": echoed}}
    _code, sentence = health.why_not_syncing(row, dbmod.utcnow_iso())
    assert sentence.lower().count("412 files vanished") == 1
    assert sentence.lower().count("as a safety measure") == 1


def test_a_detail_that_adds_something_is_still_appended():
    """The guard must not swallow the machine's own evidence: a path, an
    errno, a count is exactly what the detail is for."""
    row = {"guard": {
        "blocked_reason": "breaker_tripped",
        "blocked_detail": ("Proxy download is stopped as a safety measure: "
                           "412 files vanished from the server"),
    }}
    _code, sentence = health.why_not_syncing(row, dbmod.utcnow_iso())
    assert "412 files vanished from the server" in sentence


# -------------------------------------------------------- the headline's rank

def _row(**over):
    row = {"lanes": [{"lane": "lane_a_video_up", "state": "idle", "chip": "green"}],
           "companion_version": "0.9.71", "current_companion_version": "0.9.72"}
    row.update(over)
    return row


def test_a_tripped_breaker_beats_out_of_date_beats_nothing_ticked():
    """The priority is the owner's, and it is the whole point of ONE headline:
    a row can be three things at once and only one of them is worth the line."""
    breaker = health.why_not_syncing(
        {"guard": {"breaker_tripped": 1}}, dbmod.utcnow_iso())
    everything = _row(
        companion_outdated=True,
        why={"reason": breaker[0], "sentence": breaker[1], "informational": False})
    assert health.fleet_headline(everything)["reason"] == "breaker_tripped"
    assert health.fleet_headline(everything)["level"] == health.RED

    # Take the breaker away and the old build is the headline.
    outdated = _row(companion_outdated=True, why=None)
    assert health.fleet_headline(outdated)["reason"] == "out_of_date"
    assert health.fleet_headline(outdated)["level"] == health.AMBER
    assert "0.9.72" in health.fleet_headline(outdated)["text"]

    # Take that away and nothing ticked is the headline, MUTED.
    nothing = _row(why={"reason": "no_selection",
                        "sentence": "Nothing ticked for this computer",
                        "informational": True})
    assert health.fleet_headline(nothing)["reason"] == "no_selection"
    assert health.fleet_headline(nothing)["level"] == health.HEADLINE_MUTED


def test_a_lane_in_error_is_the_headline_when_nothing_outranks_it():
    row = _row(lanes=[{"lane": "lane_b_proxy_down", "state": "error",
                       "chip": "red", "last_error": "connection refused"}])
    headline = health.fleet_headline(row)
    assert headline["reason"] == "lane_error"
    assert headline["text"].startswith("Proxy download has stopped")
    assert "connection refused" in headline["text"]


def test_a_row_with_nothing_wrong_says_so_quietly():
    # logic-sync-truth-5 (2026-09-25): "nothing owed" is said only from a
    # counted backlog; a row nobody counted is plain "Idle".
    assert health.fleet_headline(_row())["text"] == "Idle"
    assert health.fleet_headline(_row(owed_files=0))["text"] == "Idle, nothing owed"
    assert health.fleet_headline(_row())["level"] == health.HEADLINE_MUTED
    busy = _row(lanes=[{"lane": "lane_a_video_up", "state": "syncing",
                        "chip": "amber"}])
    assert health.fleet_headline(busy)["text"] == "Syncing"
    assert health.fleet_headline(busy)["level"] == health.HEADLINE_MUTED


def test_the_three_lanes_are_always_the_same_three_in_the_same_order():
    """A lane that moves with what a machine happened to report is a lane the
    reader has to find again on every row."""
    strip = health.lane_strip([{"lane": "lane_c_syncthing", "state": "idle",
                                "chip": "green"}])
    assert [l["label"] for l in strip] == ["upload", "proxy download", "folder sync"]
    assert [l["reported"] for l in strip] == [False, False, True]
    # A lane nobody reported says so; it is never dropped and never green-washed.
    assert strip[0]["state"] == "not reported"


# ------------------------------------------------------------------- the page

@pytest.fixture
def env(tmp_path):
    """One project, one computer, one report with all three lanes idle."""
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
            "companion_version": "0.9.72", "reported_at": now,
            "lanes": [{"name": name, "state": "idle", "queued": 0,
                       "transferring": 0, "last_error": None, "last_sync": now}
                      for name in ("lane_a_video_up", "lane_b_proxy_down",
                                   "lane_c_syncthing")],
        }, headers={"X-CCSync-Token": "sekrit",
                    "X-CCSync-Identity": auth.make_identity_token(SECRET, "owen")})
        assert resp.status_code == 200, resp.text
        yield client, conn
        conn.close()


def render_grid(conn, mutate=None) -> str:
    """The grid on a real row, with the headline recomputed AFTER the mutation.

    build_editors_view composes the headline, the lane strip and (in
    ui._fleet_view) the note count; a test that mutates the row has to put
    them back or it is testing the row it did not build.
    """
    from ccsync_dashboard.api import build_editors_view

    fleet = build_editors_view(conn)
    entry = fleet["editors"][0]
    if mutate:
        mutate(entry)
    entry["lane_strip"] = health.lane_strip(entry["lanes"])
    entry["headline"] = health.fleet_headline(entry)
    entry["notes"] = health.detail_notes(entry)
    template = ui.templates.env.get_template("partials/fleet_grid.html")
    return template.render(
        fleet=fleet, view={"fleet_status": "green", "projects": []},
        session_is_admin=True, error=None,
    )


def companions(body: str) -> str:
    """Just the computers' rows. The banners above them and the lost
    computers and projects sub-windows below carry tags of their own, and
    none of them is this row."""
    assert 'class="pc head-row"' in body
    rows = body.split('class="pc head-row"', 1)[1]
    for tail in ('data-key="fleet:lost"', 'data-key="fleet:projects"'):
        rows = rows.split(tail, 1)[0]
    return rows


def issues(body: str) -> str:
    """The row's issues column (the chips that sat behind classic DETAILS,
    drawn inline worst first, D11)."""
    return body.split('<div class="issues"', 1)[1].split("</div>", 1)[0]


# Every class a fault colour can arrive through on a terminal row: the row's
# own tone, its LED, its headline, a lane line and an issue tag.
FAULT_CLASSES = ('class="pc home-pc err"', 'class="pc home-pc warn"',
                 'class="led err', 'class="led warn',
                 'class="hl err"', 'class="hl warn"',
                 'class="lane err"', 'class="lane warn"',
                 'class="tag err"', 'class="tag warn"',
                 'class="tag solid err"', 'class="tag solid warn"')


def test_a_healthy_row_carries_no_coloured_chip(env):
    """The page's job is "is anything red". A healthy row draws no fault
    colour anywhere, and its headline is muted."""
    _client, conn = env
    body = companions(render_grid(conn))
    for cls in FAULT_CLASSES:
        assert cls not in body, cls
    # The lanes are there, quietly, all three of them, in the fixed order.
    lanes = re.findall(r'<span class="k">([^<]+)</span>.*?<span class="s">([^<]+)</span>', body)
    assert lanes == [("upload", "idle"), ("proxy download", "idle"), ("folder sync", "idle")]
    assert 'class="hl muted"' in body
    assert '<span class="none">nothing wrong</span>' in issues(body)


def test_nothing_ticked_is_not_an_error(env):
    """Owner, 2026-09-11: "Alex laptop just happens to have no synced
    projects, not an error". Muted headline, calm LED, no fault colour."""
    _client, conn = env

    def unticked(e):
        e["plan"] = {"count": 0, "full": 0, "upload_only": 0}
        e["why"] = None
        why = health.why_not_syncing(e, dbmod.utcnow_iso())
        e["why"] = {"reason": why[0], "sentence": why[1],
                    "informational": why[0] in health.WHY_INFORMATIONAL}

    body = companions(render_grid(conn, unticked))
    assert "Nothing ticked for this computer" in body
    assert 'class="hl muted"' in body
    for cls in FAULT_CLASSES:
        assert cls not in body, cls


def test_the_clutter_is_behind_one_collapsed_expander_with_a_count(env):
    """Folded away, but never in silence: the count is what says there is
    something in there, and its title names each one. The terminal row
    lists the problems themselves inline (D11); the rest of the detail is
    behind one collapsed expander that carries the count."""
    _client, conn = env

    def problems(e):
        e["guard"].update({"crash_count": 3, "resolve_out_of_tree": 68,
                           "stray_projects_count": 2})
        e["youtube_import"] = {"state": "no-project-match", "pending": 0,
                               "reason": "this project has no server folder yet",
                               "at": dbmod.utcnow_iso()}

    body = companions(render_grid(conn, problems))
    # ONE expander per row, collapsed: a <details> with no `open` attribute.
    expanders = re.findall(r'<details class="more"[^>]*>', body)
    assert len(expanders) == 1 and " open" not in expanders[0]
    summary = body.split('<details class="more"', 1)[1].split("</summary>", 1)[0]
    assert "4 notes" in summary
    assert "3 crashes" in summary and "68 clips outside the tree" in summary
    # ...and each problem is still on the row, in its issues column.
    row_issues = issues(body)
    assert '<span class="w">crashes: 3</span>' in row_issues
    assert '<span class="w">68 clips outside the tree</span>' in row_issues
    assert '<span class="w">youtube import gave up</span>' in row_issues
    assert '<span class="w">2 stray project dirs</span>' in row_issues


def test_the_buttons_are_a_column_and_not_a_word_between_two_chips(env):
    """"Ask this computer why" used to sit in the middle of the chip line.
    Every route, target and form field is the one it was."""
    _client, conn = env
    body = companions(render_grid(conn, lambda e: e["guard"].update({"breaker_tripped": 1})))
    assert '<div class="acts row-actions">' in body
    assert 'hx-post="/partials/admin/machines/ask-why"' in body
    assert 'hx-post="/partials/admin/machines/resume-lane-b"' in body
    assert 'hx-target="closest .fleet-grid-wrap"' in body
    actions = body.split('<div class="acts row-actions">', 1)[1]
    assert '<span class="t">Ask this computer why</span>' in actions
    assert '<span class="t">Resume</span>' in actions
    # ...and neither key is among the issue tags.
    row_issues = issues(body)
    assert "ask-why" not in row_issues and "resume-lane-b" not in row_issues
    for field in ('name="editor" value="owen"', 'name="machine" value="EDIT-PC"'):
        assert field in actions
