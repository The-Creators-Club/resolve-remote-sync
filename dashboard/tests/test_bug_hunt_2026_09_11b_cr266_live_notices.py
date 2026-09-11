"""The live dashboard's open notices, 2026-09-11 (CR-266b, CR-266c).

Two findings read off the live dashboard's own PROBLEMS panel rather than out
of a hunt report:

* a `server_error` notice whose body sent the reader to a log that a container
  recreate had already deleted, so the one TypeError the live server recorded
  has no surviving account of itself anywhere (CR-266b), and
* twenty `invariant_broken` notices for a folder somebody moved on the NAS two
  days earlier, which the check can no longer see to re-raise and which the
  truncated-pass keep-list therefore held open for the life of the container
  (CR-266c).
"""

from __future__ import annotations

import dataclasses

import pytest

from ccsync_dashboard import alerts, invariants, notices
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.settings import Settings

SECRET = "s"
NOW = "2026-09-11T12:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "dash.db")
    dbmod.migrate(c)
    yield c
    c.close()


def _settings(tmp_path):
    return Settings(db_path=str(tmp_path / "dash.db"), session_secret=SECRET,
                    report_token="sekrit", admin_users=frozenset({"owen"}))


def _open_body(conn, subject_fragment: str) -> str:
    for row in conn.execute(
            "SELECT subject, body FROM notices WHERE kind='server_error' "
            "AND cleared_at IS NULL"):
        if subject_fragment in str(row["subject"]):
            return str(row["body"])
    raise AssertionError(f"no open server_error notice matching {subject_fragment}")


# ------------------------------------------------------------------ CR-266b

def _raise_like_the_live_one(message: str = "expected str, got NoneType"):
    """A TypeError raised through two of our own frames, so the record has a
    traceback with a shape worth asserting on."""
    def install(tool):
        return _download(tool)

    def _download(tool):
        raise TypeError(message)

    try:
        install("claude_code")
    except TypeError as exc:
        return exc
    raise AssertionError("unreachable")


def test_a_server_error_notice_carries_the_exception_and_its_frames(conn):
    """The body used to name only the exception CLASS and point at the log.

    In image mode `/data` survives a container recreate and the container's
    log does not, so "the full error is in the server log" described a file
    that no longer existed: the live dashboard's one TypeError, recorded
    2026-09-10T06:55Z from the Claude Code SET UP wizard, has no traceback
    anywhere.
    """
    exc = _raise_like_the_live_one()
    notices.record_server_error(
        conn, "/api/v1/admin/ai-providers/claude_code/install", exc, now=NOW,
        route="/api/v1/admin/ai-providers/{tool}/install")
    body = _open_body(conn, "ai-providers")
    assert "TypeError: expected str, got NoneType" in body
    # The frame that raised comes first, and it is repo-relative with a line
    # number and a function name.
    assert "test_bug_hunt_2026_09_11b_cr266_live_notices.py:" in body
    assert ": _download" in body
    assert body.index(": _download") < body.index(": install")
    # The subject is the de-dup key and must not have moved.
    subjects = [str(r["subject"]) for r in conn.execute(
        "SELECT subject FROM notices WHERE kind='server_error'")]
    assert subjects == ["/api/v1/admin/ai-providers/{tool}/install (TypeError)"]
    # And the fix no longer sends anybody to a log that is not there.
    fix = str(conn.execute(
        "SELECT fix FROM notices WHERE kind='server_error'").fetchone()["fix"])
    assert "container recreate" in fix


def test_the_counter_still_reads_back_out_of_the_longer_body(conn):
    """The occurrence count is the first digit token of the previous body.

    The detail is appended AFTER the sentence for exactly this reason: a
    traceback in front of it would be counted instead.
    """
    for _ in range(3):
        notices.record_server_error(conn, "/api/v1/x/y",
                                    _raise_like_the_live_one(), now=NOW)
    assert _open_body(conn, "/api/v1/").startswith("3 time(s)")


def test_only_three_frames_and_a_bounded_body(conn):
    """A crash dump in a table nothing prunes is not a diagnosis."""
    def deep(n):
        if n:
            return deep(n - 1)
        raise TypeError("x" * 5000)

    try:
        deep(40)
    except TypeError as exc:
        detail = notices.error_detail(exc)
    assert len(detail) <= notices.SERVER_ERROR_DETAIL_CHARS
    # The frames survive a message that would otherwise spend the budget.
    assert detail.count(" <- ") == notices.SERVER_ERROR_FRAMES - 1
    assert "Where:" in detail


def test_a_secret_in_the_exception_message_is_masked(conn):
    """`crash_report.redact` is the masking helper, and the bare key shapes
    that turn up in a message with no `key=` in front of them are in it."""
    exc = _raise_like_the_live_one(
        "Invalid API key: sk-ant-api03-AAAABBBBCCCCDDDDEEEE "
        "token=hunter2 Bearer abc.def.ghi cce1.AAAABBBBCCCCDDDD")
    notices.record_server_error(
        conn, "/api/v1/admin/ai-providers/claude_code/install", exc, now=NOW,
        route="/api/v1/admin/ai-providers/{tool}/install")
    body = _open_body(conn, "ai-providers")
    for secret in ("sk-ant-api03-AAAABBBBCCCCDDDDEEEE", "hunter2",
                   "abc.def.ghi", "cce1.AAAABBBBCCCCDDDD"):
        assert secret not in body, f"{secret} reached a notice body"
    assert "sk-<redacted>" in body


def test_an_exception_with_no_traceback_is_still_described(conn):
    """Never raises: this runs inside the 500 handler."""
    detail = notices.error_detail(TypeError("built by hand"))
    assert detail.startswith("What went wrong: TypeError: built by hand")
    assert "Where:" not in detail


def test_the_daily_digest_quotes_the_traceback_under_the_subject(conn, tmp_path):
    """`notice_error` is what carries a server_error off this machine.

    The body is the diagnosis of the finding, so the mail an owner reads at
    07:00 holds the same three facts the panel does.
    """
    notices.record_server_error(
        conn, "/api/v1/admin/ai-providers/claude_code/install",
        _raise_like_the_live_one(), now=NOW,
        route="/api/v1/admin/ai-providers/{tool}/install")
    conn.commit()
    findings = [f for f in alerts.scan(conn, _settings(tmp_path), NOW)
                if f.get("kind") == "notice_error"]
    assert findings, "the notice did not reach the scan"
    items = [alerts._digest_item(f, "new") for f in findings]
    subject, text = alerts.compose_digest(items)
    assert "TypeError: expected str, got NoneType" in text
    assert "/api/v1/admin/ai-providers/{tool}/install (TypeError)" in subject or \
        "/api/v1/admin/ai-providers/{tool}/install (TypeError)" in text


# ------------------------------------------------------------------ CR-266c

def _seed_vanished(conn, key: str, subject: str):
    """One open notice, and its ledger row, for a subject that is about to
    stop existing: the Gold Card Meetup Proxy folder as the live server held
    it on 2026-09-09, before the footage was moved to Projects/2026/FF5."""
    dbmod.notice(conn, "invariant_broken", "warn", f"{key}: {subject}",
                 body="this proxy has no original beside it on the server",
                 fix="put the original back", now="2026-09-09T00:00:00+00:00")
    dbmod.record_invariant_result(conn, key, dbmod.INVARIANT_BROKEN, "1 subject(s)",
                                  subjects=[(subject, "no original")],
                                  now="2026-09-09T00:00:00+00:00")
    conn.commit()


def _run_with(conn, tmp_path, monkeypatch, outcome_fn, passes: int = 2):
    inv = invariants.INVARIANTS[0]
    monkeypatch.setattr(invariants, "INVARIANTS",
                        [dataclasses.replace(inv, check=outcome_fn)])
    invariants._TRUNCATED_CARRY.clear()
    try:
        for _ in range(passes):
            invariants.run_cycle(conn, _settings(tmp_path), NOW)
    finally:
        invariants._TRUNCATED_CARRY.clear()
    return inv.key


VANISHED = ("2026-creator-profiles-season-1/Interviewees/Interviews/"
            "Gold Card Meetup/Proxy/A001_C003.mp4")


def _is_open(conn, subject: str) -> bool:
    row = conn.execute(
        "SELECT cleared_at FROM notices WHERE kind='invariant_broken' AND subject=?",
        (subject,)).fetchone()
    assert row is not None, f"{subject} lost its row altogether"
    return row["cleared_at"] is None


def test_a_subject_that_has_vanished_is_cleared_by_a_capped_pass(
        conn, tmp_path, monkeypatch):
    """The live shape: twenty open `proxy_pairs` notices, first_seen
    2026-09-09, for a folder that was moved on the NAS.

    `run_cycle` only ever recorded the subjects it SAW, and the keep-list a
    truncated pass builds (CR-241, made durable by CR-256d) held everything
    the ledger remembered - so while ANY pass of that invariant is capped, and
    a fleet with more than twenty orphaned proxies caps every pass, a subject
    that has stopped existing is neither re-raised nor cleared and rides the
    daily digest for ever.
    """
    key = None
    _seed_vanished(conn, invariants.INVARIANTS[0].key, VANISHED)

    def check(_ctx):
        # The cap is a REPORTING cap: this pass walked everything and found
        # 25 broken subjects, none of them the moved folder's.
        return invariants.broken([(f"other/clip-{i}.mp4", "no original")
                                  for i in range(25)])

    key = _run_with(conn, tmp_path, monkeypatch, check)
    assert not _is_open(conn, f"{key}: {VANISHED}")
    # The twenty it did report are open, and the pass is still truncated.
    assert _is_open(conn, f"{key}: other/clip-0.mp4")


def test_a_pass_that_cannot_name_its_whole_set_clears_nothing(
        conn, tmp_path, monkeypatch):
    """CR-256d's keep-list stays for an outcome that cannot say.

    A truncated verdict with no `found` set has said NOTHING about subject 21
    onward, so closing their notices would mail "this has cleared" about
    something nobody looked at.
    """
    _seed_vanished(conn, invariants.INVARIANTS[0].key, VANISHED)

    def check(_ctx):
        return invariants.Outcome(
            invariants.BROKEN, "45 subject(s)",
            [(f"other/clip-{i}.mp4", "no original") for i in range(20)],
            truncated=True)

    key = _run_with(conn, tmp_path, monkeypatch, check)
    assert _is_open(conn, f"{key}: {VANISHED}")


def test_a_check_that_could_not_run_clears_nothing_either(
        conn, tmp_path, monkeypatch):
    """The bug-hunt-2026-09-03 dash-collector-2 rule, unchanged: NOT CHECKED
    is not OK."""
    _seed_vanished(conn, invariants.INVARIANTS[0].key, VANISHED)
    key = _run_with(conn, tmp_path, monkeypatch,
                    lambda _ctx: invariants.not_checked("nothing walked yet"))
    assert _is_open(conn, f"{key}: {VANISHED}")


def test_an_uncapped_pass_still_clears_what_it_did_not_find(
        conn, tmp_path, monkeypatch):
    """The direction that already worked, pinned: a complete verdict is
    authoritative about every subject of its own invariant."""
    _seed_vanished(conn, invariants.INVARIANTS[0].key, VANISHED)
    key = _run_with(conn, tmp_path, monkeypatch,
                    lambda _ctx: invariants.broken(
                        [("other/clip-0.mp4", "no original")]))
    assert not _is_open(conn, f"{key}: {VANISHED}")


def test_the_found_set_is_names_only_and_bounded(conn):
    """`found` is a pass-local list of names, never stored and never
    unbounded: an invariant broken on a hundred thousand subjects must not
    carry a hundred thousand strings through the cycle."""
    outcome = invariants.broken(
        [(f"s-{i}", "d") for i in range(invariants.MAX_FOUND_SUBJECTS + 1)])
    assert outcome.truncated is True
    assert outcome.found == ()
    fits = invariants.broken([(f"s-{i}", "d") for i in range(30)])
    assert len(fits.found) == 30
    assert all(isinstance(name, str) for name in fits.found)
