"""SYS-7 (resilience sweep 2026-08-28): the diagnostics channel.

`build_diagnostics()` on the companion answers "why is my footage not syncing"
in full, and it went to the CLIPBOARD, with the instruction "paste them to your
admin in a message" -- and silently to the log instead if any CCSync window was
open. So the one artefact that answers the question existed only if a
non-technical editor performed a manual step at the right moment, on the machine
that was broken.

What is pinned here: the upload authenticates exactly as a report does, an
oversized bundle is TRUNCATED rather than dropped (B6's rule -- the bundle from
the machine that is broken is the one you must not throw away), only the newest
five per computer are kept, the request/ack round trip is bounded by the ARRIVAL
and not by the reply, and both halves land in the audit ledger.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"


def headers(editor="leso", token="sekrit"):
    return {"X-CCSync-Token": token,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def bundle(text="=== CCSYNC DIAGNOSTICS ===\nroot: missing", trigger="button",
           editor="leso", machine="LESO-MBP"):
    return {"editor_name": editor, "machine": machine, "machine_id": "mid-1",
            "at": "2026-08-28T10:00:00+00:00", "trigger": trigger, "text": text}


def report(editor="leso", machine="LESO-MBP", version="0.9.55"):
    return {
        "editor_name": editor, "machine": machine, "companion_version": version,
        "reported_at": "2026-08-28T10:00:00+00:00",
        "lanes": [{"name": "lane_a_video_up", "state": "idle", "queued": 0,
                   "transferring": 0, "last_error": None, "last_sync": None,
                   "detail": None}],
    }


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "dash.db"
    app = create_app(Settings(db_path=str(db_path), report_token="sekrit",
                              session_secret=SECRET,
                              admin_users=frozenset({"admin"})))
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        yield client, conn
        conn.close()


def admin_session(client):
    client.cookies.set("ccsync_session", auth.make_session_cookie(SECRET, "admin"))


# ------------------------------------------------------------------- auth

def test_a_bundle_needs_the_report_token(env):
    client, _conn = env
    assert client.post("/api/v1/diagnostics", json=bundle()).status_code == 401
    assert client.post("/api/v1/diagnostics", json=bundle(),
                       headers={"X-CCSync-Token": "wrong"}).status_code == 401


def test_a_bundle_needs_a_matching_identity(env):
    """A bundle names an editor's paths, their Resolve project and their tree,
    so it may not be filed under a name the caller cannot prove (SEC-5)."""
    client, _conn = env
    assert client.post("/api/v1/diagnostics", json=bundle(),
                       headers={"X-CCSync-Token": "sekrit"}).status_code == 401
    resp = client.post("/api/v1/diagnostics", json=bundle(editor="leso"),
                       headers=headers(editor="ruskin"))
    assert resp.status_code == 401
    assert "does not match" in resp.json()["detail"]


def test_a_good_bundle_is_stored(env):
    client, conn = env
    resp = client.post("/api/v1/diagnostics", json=bundle(), headers=headers())
    assert resp.status_code == 200
    rows = dbmod.fetch_diagnostics(conn)
    assert len(rows) == 1
    assert rows[0]["editor"] == "leso"
    assert rows[0]["machine"] == "LESO-MBP"
    assert rows[0]["trigger"] == "button"
    assert rows[0]["machine_id"] == "mid-1"
    assert "CCSYNC DIAGNOSTICS" in rows[0]["text"]
    assert rows[0]["received_at"]


def test_an_unknown_trigger_is_recorded_not_refused(env):
    """A trigger this build does not know is a NEWER companion. Losing the
    bundle over the label on it would be SYS-3 in a new place."""
    client, conn = env
    assert client.post("/api/v1/diagnostics",
                       json=bundle(trigger="watchdog_restart"),
                       headers=headers()).status_code == 200
    assert dbmod.fetch_diagnostics(conn)[0]["trigger"] == "watchdog_restart"


# ------------------------------------------------------------------- caps

def test_an_oversized_body_is_refused_by_the_gate(env):
    """The declared-length ceiling, before anything is parsed: the container is
    single-worker, and a token holder must not be able to spend its memory."""
    from ccsync_dashboard import app as appmod

    client, _conn = env
    assert appmod._BODY_LIMITS["/api/v1/diagnostics"][1] == 256 * 1024
    huge = client.post("/api/v1/diagnostics", json=bundle(text="x" * (400 * 1024)),
                       headers=headers())
    assert huge.status_code == 413


def test_a_bundle_at_the_edge_is_truncated_not_dropped(env):
    """B6's rule: the bundle from the machine that is broken is the one that
    must not be thrown away, so the TEXT is cut and the row still lands."""
    client, conn = env
    text = "y" * (dbmod.DIAGNOSTICS_MAX_CHARS + 500)
    # Posted directly to the route so the body gate is not the thing under test.
    from ccsync_dashboard.api import DiagnosticsIn

    parsed = DiagnosticsIn.model_validate(bundle(text=text))
    assert len(parsed.text) == dbmod.DIAGNOSTICS_MAX_CHARS
    dbmod.record_diagnostics(
        conn, editor="leso", machine="LESO-MBP", machine_id="", trigger="button",
        at="", received_at=dbmod.utcnow_iso(), text=text)
    conn.commit()
    assert len(dbmod.fetch_diagnostics(conn)[0]["text"]) == dbmod.DIAGNOSTICS_MAX_CHARS


def test_only_the_newest_five_per_machine_are_kept(env):
    """Bounded at WRITE time, not only in prune(): the lane-error trigger fires
    on a machine that fails every pass, which is exactly the machine whose
    bundles you want and exactly the one that would fill /data with them."""
    client, conn = env
    for i in range(8):
        assert client.post("/api/v1/diagnostics", json=bundle(text=f"bundle {i}"),
                           headers=headers()).status_code == 200
    rows = dbmod.fetch_diagnostics(conn, editor="leso", machine="LESO-MBP")
    assert len(rows) == dbmod.DIAGNOSTICS_KEEP_PER_MACHINE
    assert rows[0]["text"] == "bundle 7"
    assert rows[-1]["text"] == "bundle 3"
    # ...and another computer's bundles are not touched by that pass.
    assert client.post("/api/v1/diagnostics",
                       json=bundle(machine="LESO-STUDIO", text="other"),
                       headers=headers()).status_code == 200
    assert len(dbmod.fetch_diagnostics(conn)) == 6


def test_bundles_are_pruned_at_thirty_days(env):
    client, conn = env
    dbmod.record_diagnostics(
        conn, editor="leso", machine="OLD-PC", machine_id="", trigger="button",
        at="", received_at="2026-06-01T00:00:00+00:00", text="ancient")
    dbmod.record_diagnostics(
        conn, editor="leso", machine="NEW-PC", machine_id="", trigger="button",
        at="", received_at="2026-08-27T00:00:00+00:00", text="recent")
    conn.commit()
    dbmod.prune(conn, "2026-08-28T00:00:00+00:00")
    conn.commit()
    kept = [r["text"] for r in dbmod.fetch_diagnostics(conn)]
    assert kept == ["recent"]


# -------------------------------------------------- the request round trip

def test_the_ask_rides_the_next_report_and_clears_on_the_bundle(env):
    """The ask is answered by the ARRIVAL, not by the reply that carried it.

    Opposite to resume_lane_b on purpose: a standing resume re-armed the
    breaker every cycle, so that one had to be one-shot; a standing ask costs
    one upload of a text file, and the failure that matters here is an admin
    clicking, nothing arriving, and no way to tell a lost reply from a machine
    with nothing to say.
    """
    client, conn = env
    # The machine has to exist in the registry, which its first report creates.
    assert client.post("/api/v1/report", json=report(),
                       headers=headers()).status_code == 200
    admin_session(client)
    assert client.post("/api/v1/admin/machines/leso/LESO-MBP/ask-why").status_code == 200

    reply = client.post("/api/v1/report", json=report(), headers=headers()).json()
    command = reply["commands"]["diagnostics"]
    assert command["requested_by"] == "admin"
    assert command["requested_at"]
    # STILL THERE on the next report: nothing has arrived yet.
    again = client.post("/api/v1/report", json=report(), headers=headers()).json()
    assert again["commands"]["diagnostics"]["requested_at"] == command["requested_at"]

    assert client.post("/api/v1/diagnostics", json=bundle(trigger="admin_request"),
                       headers=headers()).status_code == 200
    done = client.post("/api/v1/report", json=report(), headers=headers()).json()
    assert "diagnostics" not in done["commands"]


def test_a_bundle_from_the_button_does_not_answer_an_admins_ask(env):
    """An editor happening to click Copy diagnostics is not the answer to the
    question the admin asked, which may be about a state that has since
    changed."""
    client, conn = env
    client.post("/api/v1/report", json=report(), headers=headers())
    admin_session(client)
    client.post("/api/v1/admin/machines/leso/LESO-MBP/ask-why")
    client.post("/api/v1/diagnostics", json=bundle(trigger="button"),
                headers=headers())
    reply = client.post("/api/v1/report", json=report(), headers=headers()).json()
    assert "diagnostics" in reply["commands"]


def test_asking_an_unknown_machine_is_a_refusal_not_a_silent_success(env):
    client, _conn = env
    admin_session(client)
    resp = client.post("/api/v1/admin/machines/leso/NO-SUCH-PC/ask-why")
    assert resp.status_code == 404


def test_only_an_admin_may_ask_or_read(env):
    client, _conn = env
    client.post("/api/v1/report", json=report(), headers=headers())
    client.cookies.set("ccsync_session", auth.make_session_cookie(SECRET, "leso"))
    assert client.post(
        "/api/v1/admin/machines/leso/LESO-MBP/ask-why").status_code == 403
    assert client.get("/api/v1/admin/diagnostics").status_code == 403


# ------------------------------------------------------------------ audit

def test_both_halves_are_audited(env):
    """SYS-11's ledger: "who asked this machine why, and when did it answer"
    has to outlive the machine it happened on."""
    client, conn = env
    client.post("/api/v1/report", json=report(), headers=headers())
    admin_session(client)
    client.post("/api/v1/admin/machines/leso/LESO-MBP/ask-why")
    client.post("/api/v1/diagnostics", json=bundle(trigger="admin_request"),
                headers=headers())
    actions = [r["action"] for r in dbmod.fetch_audit(conn)]
    assert "diagnostics.request" in actions
    assert "diagnostics.received" in actions
    received = next(r for r in dbmod.fetch_audit(conn)
                    if r["action"] == "diagnostics.received")
    assert received["subject"] == "LESO-MBP"
    assert received["detail"]["trigger"] == "admin_request"
    assert received["detail"]["chars"] > 0
    requested = next(r for r in dbmod.fetch_audit(conn)
                     if r["action"] == "diagnostics.request")
    assert requested["actor"] == "admin"


# ------------------------------------------------- what the report stores

def test_the_blocked_section_reaches_the_grid_and_can_clear(env):
    """SYNC-15 + the LATCH rule: an ABSENT `blocked` is how the companion
    spells "nothing is blocking me now", so it has to be able to clear this
    morning's sentence rather than preserve it for ever."""
    client, conn = env
    payload = report()
    payload["sync_guard"] = {
        "blocked": {"reason": "root_not_answering",
                    "detail": "P:\\ timed out after 5 s",
                    "since": "2026-08-28T09:00:00+00:00"},
        "restarts": {"sequencer": {"count_24h": 3, "last_at": "2026-08-28T09:30:00+00:00",
                                   "last_error": "OSError: [WinError 53]"},
                     "watcher": {"count_24h": 1}},
    }
    assert client.post("/api/v1/report", json=payload,
                       headers=headers()).status_code == 200
    guard = dbmod.fetch_sync_guard_map(conn)[("leso", "LESO-MBP")]
    assert guard["blocked_reason"] == "root_not_answering"
    assert guard["blocked_detail"] == "P:\\ timed out after 5 s"
    assert guard["blocked_since"] == "2026-08-28T09:00:00+00:00"
    assert guard["restarts_count_24h"] == 4
    assert guard["restarts_last_at"] == "2026-08-28T09:30:00+00:00"
    assert "WinError" in guard["restarts_last_error"]

    healthy = report()
    healthy["sync_guard"] = {"halt": {"active": False}}
    client.post("/api/v1/report", json=healthy, headers=headers())
    guard = dbmod.fetch_sync_guard_map(conn)[("leso", "LESO-MBP")]
    assert guard["blocked_reason"] is None
    assert guard["restarts_count_24h"] is None


def test_a_companion_with_no_guard_section_clears_nothing(env):
    """A build too old to send sync_guard has no opinion to record, and
    clearing another build's alarm on its behalf is what must not happen."""
    client, conn = env
    payload = report()
    payload["sync_guard"] = {"blocked": {"reason": "disk_full", "detail": "8 GB"}}
    client.post("/api/v1/report", json=payload, headers=headers())
    client.post("/api/v1/report", json=report(), headers=headers())
    guard = dbmod.fetch_sync_guard_map(conn)[("leso", "LESO-MBP")]
    assert guard["blocked_reason"] == "disk_full"


def test_the_sentence_is_on_the_fleet_grid(env):
    """The whole finding: the owner opens this page and reads the reason, in
    words, instead of an amber dot."""
    client, _conn = env
    payload = report()
    payload["sync_guard"] = {"blocked": {"reason": "root_absent", "detail": ""}}
    client.post("/api/v1/report", json=payload, headers=headers())
    admin_session(client)
    page = client.get("/")
    assert page.status_code == 200
    assert "Not syncing: the sync drive is not there on this computer" in page.text
    assert "[ ASK THIS MACHINE WHY ]" in page.text


def test_the_admin_partial_shows_the_newest_bundle_per_machine(env):
    client, _conn = env
    client.post("/api/v1/report", json=report(), headers=headers())
    client.post("/api/v1/diagnostics", json=bundle(text="BUNDLE-OLDER"),
                headers=headers())
    client.post("/api/v1/diagnostics", json=bundle(text="BUNDLE-NEWEST"),
                headers=headers())
    admin_session(client)
    resp = client.get("/partials/admin/diagnostics")
    assert resp.status_code == 200
    assert "BUNDLE-NEWEST" in resp.text
    assert "BUNDLE-OLDER" not in resp.text
    assert "<pre" in resp.text
    # ...and the per-machine view keeps the history for that one computer.
    one = client.get("/partials/admin/diagnostics?editor=leso&machine=LESO-MBP")
    assert "BUNDLE-OLDER" in one.text and "BUNDLE-NEWEST" in one.text


def test_the_ask_button_becomes_asked(env):
    client, _conn = env
    client.post("/api/v1/report", json=report(), headers=headers())
    admin_session(client)
    resp = client.post("/partials/admin/machines/ask-why",
                       data={"editor": "leso", "machine": "LESO-MBP"})
    assert resp.status_code == 200
    assert "[ ASKED WHY ]" in resp.text
    assert "[ ASK THIS MACHINE WHY ]" not in resp.text


def test_the_contracts_editor_key_is_accepted_too(env):
    """`editor_name` is the report channel's spelling and what the companion
    sends; the wire contract wrote `editor`. A bundle refused over the name of
    a key would be the one bundle nobody could get."""
    client, conn = env
    body = bundle()
    body["editor"] = body.pop("editor_name")
    assert client.post("/api/v1/diagnostics", json=body,
                       headers=headers()).status_code == 200
    assert dbmod.fetch_diagnostics(conn)[0]["editor"] == "leso"
