"""The admin-side Resolve undo, companion half (SYS-15b, wave 5, 2026-08-29).

Until this, undoing a clip-path change CC Sync had made was a tray click on
the editor's own machine, so a relink pass that went wrong on somebody else's
computer stayed wrong until that person was next at their keyboard.

What is pinned here: the journal id from the wire never becomes a path
outside `~/.ccsync/resolve_edits`; the replay is the SAME
`resolve_bridge.undo_last_relink` the tray calls, not a second
implementation; a refusal that will clear itself is answered `retrying` and
the command therefore keeps coming back; and a command redelivered after a
restart is answered from the ledger rather than replayed.
"""
from __future__ import annotations

import json
from pathlib import Path

from ccsync_companion import resolve_journal, resolve_undo


def _command(**over):
    cmd = {"id": 7, "journal": "Season 1 EP3/20260829-1042.json",
           "project": "Season 1 EP3", "requested_by": "owen",
           "requested_at": "2026-08-29T10:45:00+00:00"}
    cmd.update(over)
    return cmd


def _write_journal(project="Season 1 EP3", name="20260829-1042.json", entries=2):
    root = resolve_journal.journal_root() / resolve_journal.project_slug(project)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(json.dumps({
        "project": project, "started": "2026-08-29T10:42:00+00:00",
        "entries": [{"kind": "replace_clip", "old": f"F:/a{i}.braw",
                     "new": f"P:/a{i}.braw", "source": "auto_canonical"}
                    for i in range(entries)],
    }), encoding="utf-8")
    return path


# -- the command off the wire ----------------------------------------------


def test_parse_command_refuses_anything_it_cannot_act_on():
    assert resolve_undo.parse_command(_command()) is not None
    assert resolve_undo.parse_command(_command(id="x")) is None
    assert resolve_undo.parse_command(_command(id=0)) is None
    assert resolve_undo.parse_command(_command(journal="")) is None
    assert resolve_undo.parse_command("nope") is None


def test_a_journal_id_from_the_wire_never_leaves_the_journal_directory():
    """The file this names is about to be read and replayed against Resolve's
    media pool: `..`, an absolute path and a drive letter must resolve to
    nothing at all."""
    _write_journal()
    assert resolve_journal.session_by_id("Season 1 EP3/20260829-1042.json") is not None
    for bad in ("../../etc/passwd", "/etc/passwd", "C:/Windows/x.json",
                "Season 1 EP3/../../x.json", "..", "one/two/three.json",
                "Season 1 EP3/20260829-1042.txt", ""):
        assert resolve_journal.session_by_id(bad) is None, bad


def test_the_journals_this_machine_reports_are_names_and_counts_only():
    """The entries name this editor's own paths and the dashboard has no use
    for them: an admin picks a change to undo by project and time."""
    _write_journal()
    summaries = resolve_journal.summaries()
    assert summaries[0]["id"] == "Season 1 EP3/20260829-1042.json"
    assert summaries[0]["project"] == "Season 1 EP3"
    assert summaries[0]["entries"] == 2
    assert summaries[0]["sources"] == "auto_canonical"
    assert "P:/a0.braw" not in json.dumps(summaries)


def test_summaries_survive_a_damaged_journal():
    _write_journal()
    root = resolve_journal.journal_root() / "Broken"
    root.mkdir(parents=True, exist_ok=True)
    (root / "20260829-1200.json").write_text("{not json", encoding="utf-8")
    ids = [s["id"] for s in resolve_journal.summaries()]
    assert "Season 1 EP3/20260829-1042.json" in ids


# -- the replay -------------------------------------------------------------


def test_the_undo_replays_the_journal_the_tray_would_replay():
    """One place in this product writes to a media pool. This is not a second
    one: it hands the journal to the bridge's own undo."""
    path = _write_journal()
    seen = {}

    def fake_undo(session_path=None):
        seen["path"] = session_path
        return {"ok": True, "undone": 158, "skipped": 0,
                "message": "Put 158 clip path(s) back the way they were."}

    ok, detail, state = resolve_undo.apply_undo(
        resolve_undo.parse_command(_command()), undo_fn=fake_undo)

    assert ok and state == "done"
    assert Path(seen["path"]) == path
    assert "158" in detail


def test_a_journal_this_machine_no_longer_has_is_a_failure_not_a_retry():
    """A journal that has been swept (60 days) is not going to appear, and a
    command that retried for ever would be a request nobody sees the end of."""
    ok, detail, state = resolve_undo.apply_undo(
        resolve_undo.parse_command(_command()), undo_fn=lambda **_kw: {"ok": True})
    assert not ok and state == "failed"
    assert "no longer has" in detail


def test_the_wrong_project_being_open_is_a_retry():
    """The condition clears itself when the editor switches project. Retiring
    the command there would leave the wrong paths in place with the admin
    believing they had been put back."""
    _write_journal()
    message = ("That change was made in \u201cSeason 1 EP3\u201d but \u201cFF4\u201d is "
               "open. Open \u201cSeason 1 EP3\u201d and undo there.")
    ok, detail, state = resolve_undo.apply_undo(
        resolve_undo.parse_command(_command()),
        undo_fn=lambda **_kw: {"ok": False, "message": message})
    assert not ok and state == "retrying" and "Season 1 EP3" in detail


def test_a_bridge_that_raises_is_a_retry_not_a_crash():
    _write_journal()

    def boom(session_path=None):
        raise RuntimeError("scripting is not answering")

    ok, _detail, state = resolve_undo.apply_undo(
        resolve_undo.parse_command(_command()), undo_fn=boom)
    assert not ok and state == "retrying"


# -- the ledger -------------------------------------------------------------


def test_the_ledger_answers_a_redelivered_command_without_replaying_it(tmp_path):
    ledger = resolve_undo.UndoLedger(tmp_path)
    ledger.record(7, True, "put 158 clip path(s) back", "done")

    reopened = resolve_undo.UndoLedger(tmp_path)
    entry = reopened.entry(7)
    assert entry["ok"] is True and entry["state"] == "done"


def test_a_retry_counts_its_attempts_and_eventually_gives_up(tmp_path):
    ledger = resolve_undo.UndoLedger(tmp_path)
    entry = ledger.record(7, False, "Resolve is not running", "retrying")
    entry = ledger.record(7, False, "Resolve is not running", "retrying")
    assert entry["attempts"] == 2
    assert ledger.gave_up(entry) is False

    entry["first_at"] = 0.0
    assert ledger.gave_up(entry) is True


def test_an_unreadable_ledger_does_not_stop_an_undo(tmp_path):
    (tmp_path / resolve_undo.LEDGER_FILENAME).write_text("{not json", encoding="utf-8")
    ledger = resolve_undo.UndoLedger(tmp_path)
    assert ledger.entry(7) is None
    assert ledger.record(7, True, "done", "done")["ok"] is True


# -- the wiring into the report reply ---------------------------------------


class _App:
    """The three methods `_apply_resolve_undo` needs, on the real class.

    Bound off CompanionApp rather than reimplemented, so this exercises the
    code that ships rather than a copy of it."""

    def __init__(self, tmp_path):
        from ccsync_companion.app import CompanionApp

        self.resolve_undos = resolve_undo.UndoLedger(tmp_path)
        self._resolve_undo_answers = []
        self.notified = []
        self._apply_resolve_undo = CompanionApp._apply_resolve_undo.__get__(self)
        self._queue_resolve_undo_answer = \
            CompanionApp._queue_resolve_undo_answer.__get__(self)
        self._resolve_undo_results = CompanionApp._resolve_undo_results.__get__(self)

    def _notify_tray(self, text, title=""):
        self.notified.append(text)


def _reply(**over):
    command = {"id": 7, "journal": "Season 1 EP3/20260829-1042.json",
               "project": "Season 1 EP3", "requested_by": "owen",
               "requested_at": "2026-08-29T10:45:00+00:00"}
    command.update(over)
    return {"commands": {"resolve_undo": [command]}}


def test_the_reply_is_applied_and_answered(tmp_path, monkeypatch):
    _write_journal()
    monkeypatch.setattr(
        resolve_undo, "apply_undo",
        lambda command, **_kw: (True, "put 158 clip path(s) back", "done"))
    app = _App(tmp_path)

    app._apply_resolve_undo(_reply())

    answers = app._resolve_undo_results()
    assert answers == [{"id": 7, "ok": True, "detail": "put 158 clip path(s) back",
                        "state": "done", "attempts": 1}]
    assert app.notified and "owen" in app.notified[0]
    # ...and drained: an answer already sent is not sent again.
    assert app._resolve_undo_results() == []


def test_a_redelivered_command_is_answered_from_the_ledger(tmp_path, monkeypatch):
    _write_journal()
    calls = []

    def once(command, **_kw):
        calls.append(command["id"])
        return True, "put 158 clip path(s) back", "done"

    monkeypatch.setattr(resolve_undo, "apply_undo", once)
    app = _App(tmp_path)
    app._apply_resolve_undo(_reply())
    app._resolve_undo_results()
    app._apply_resolve_undo(_reply())

    assert calls == [7], "a redelivered undo was replayed a second time"
    assert app._resolve_undo_results()[0]["ok"] is True


def test_a_retrying_answer_is_tried_again_next_time(tmp_path, monkeypatch):
    _write_journal()
    calls = []

    def blocked(command, **_kw):
        calls.append(command["id"])
        return False, "Resolve is not running on this computer", "retrying"

    monkeypatch.setattr(resolve_undo, "apply_undo", blocked)
    app = _App(tmp_path)
    app._apply_resolve_undo(_reply())
    assert app._resolve_undo_results()[0]["state"] == "retrying"
    app._apply_resolve_undo(_reply())

    assert calls == [7, 7]
    assert app._resolve_undo_results()[0]["attempts"] == 2


def test_a_reply_with_no_undo_in_it_does_nothing(tmp_path):
    app = _App(tmp_path)
    for reply in ({}, {"commands": {}}, {"commands": {"resolve_undo": []}},
                  {"commands": {"resolve_undo": "nope"}}, None):
        app._apply_resolve_undo(reply)
    assert app._resolve_undo_results() == []


def test_a_malformed_command_is_ignored_and_the_rest_survive(tmp_path, monkeypatch):
    _write_journal()
    monkeypatch.setattr(resolve_undo, "apply_undo",
                        lambda command, **_kw: (True, "done", "done"))
    app = _App(tmp_path)
    reply = _reply()
    reply["commands"]["resolve_undo"] = ["rubbish", {"id": "x"},
                                         reply["commands"]["resolve_undo"][0]]

    app._apply_resolve_undo(reply)

    assert [a["id"] for a in app._resolve_undo_results()] == [7]


# -- RES-4 (2026-09-04): Resolve at the Project Manager is not a failure ------


def test_no_project_open_parks_the_undo_instead_of_failing_it():
    """The commonest state of all: Resolve open at the Project Manager, or
    between projects. It matched none of the old prose tests, so an undo an
    admin asked for was recorded FAILED and never offered again -- although
    the editor opening their project is exactly what clears it."""
    _write_journal()
    ok, detail, state = resolve_undo.apply_undo(
        resolve_undo.parse_command(_command()),
        undo_fn=lambda **_kw: {"ok": False, "message": "no project open in Resolve"})

    assert not ok
    assert state == resolve_undo.STATE_RETRYING, "it must still be offered again"
    assert "Parked" in detail and "no project open in Resolve" in detail
    assert "as soon as that project is open" in detail or "next time that project is open" in detail
    assert "—" not in detail


def test_the_scripting_error_message_is_a_retry_too():
    """"Resolve didn't answer. Make sure a project is open, then try again."
    is explicitly transient, and "didn't" contains no "not"."""
    _write_journal()
    from ccsync_companion import resolve_bridge

    ok, _detail, state = resolve_undo.apply_undo(
        resolve_undo.parse_command(_command()),
        undo_fn=lambda **_kw: {"ok": False,
                               "message": resolve_bridge._SCRIPTING_ERROR_MESSAGE})
    assert not ok and state != "failed"


def test_the_finer_word_is_available_but_off_the_wire_by_default():
    """`parked` is the honest state and the dashboard's ResolveUndoResultIn
    accepts done/failed/retrying only (v40): an unknown value fails
    validation for the WHOLE report, so the wire keeps "retrying" until a
    dashboard that knows the word is deployed."""
    _write_journal()
    _, _detail, state = resolve_undo.apply_undo(
        resolve_undo.parse_command(_command()), allow_parked=True,
        undo_fn=lambda **_kw: {"ok": False, "message": "no timeline open in Resolve"})
    assert state == resolve_undo.STATE_PARKED


def test_a_parked_undo_is_stored_as_an_open_one(tmp_path):
    """The ledger is what decides whether this machine is asked again, and
    it tests for "retrying" -- so a state nobody recognises would retire the
    command: RES-4's own bug, moved one file along."""
    ledger = resolve_undo.UndoLedger(tmp_path)
    entry = ledger.record(7, False, resolve_undo.PARKED_DETAIL,
                          resolve_undo.STATE_PARKED)
    assert entry["state"] == resolve_undo.STATE_RETRYING
    assert entry["parked"] is True
    entry = ledger.record(7, False, resolve_undo.PARKED_DETAIL,
                          resolve_undo.STATE_PARKED)
    assert entry["attempts"] == 2
