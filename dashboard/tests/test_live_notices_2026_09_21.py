"""The five cards the live dashboard could not get rid of (2026-09-21).

Every condition behind them was already fixed in the build that was running
-- the naive session stamp (live-3), the overlapping publish (dash-api-6),
the busy database (2026-09-17), the collector's slow-pass claim (dash-db-1).
What was left was two ways a card outlives its cause:

1. [ DISMISS ] on an ERROR notice was `color: var(--red)` on
   `background: var(--red)`. Invisible, and it is the only way to close one.
2. dash-db-1 renamed a notice kind. `clear_slow_poll` clears the NEW kind, so
   the two `slow_write` cards the old writer had already opened were orphans
   that nothing would ever re-assert or clear.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from ccsync_dashboard import db as dbmod

# The terminal look is the only look (2026-09-25): an error notice is a
# `.prob` row in problems.log (home) and on Health, and its dismiss is a
# `.key.quiet`. The rule the classic `.banner.alarm .btn` pin guarded is the
# same: the one control that closes an error card must never be painted in
# the colour it sits on.
CSS = Path(__file__).resolve().parents[1] / "static" / "cc" / "terminal.css"
NOTICE_PARTIALS = ("partials/home_problems.html", "partials/health_notices.html")


def _rule(css: str, selector: str) -> str:
    """The declaration blocks of every rule whose selector list carries
    EXACTLY this selector (never its `:hover`), joined -- last wins in the
    cascade and both are read here, so a later rule cannot hide an earlier
    one from the test."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)   # a comment is not a selector
    blocks = [
        m.group(2)
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
        if any(part.strip() == selector for part in m.group(1).split(","))
    ]
    assert blocks, f"no rule for {selector}"
    return "\n".join(blocks)


def _error_notice_html(template: str) -> str:
    from ccsync_dashboard import ui
    notice = {"id": 7, "severity": "error", "subject": "the disk is full",
              "kind": "disk_full", "body": "writes are refused", "fix": "free space",
              "href": "", "href_label": "", "first_seen": dbmod.utcnow_iso(),
              "last_seen": dbmod.utcnow_iso()}
    return ui.templates.env.get_template(template).render(
        notices=[notice], notice_kinds=[], open_kinds=set(), checked_kinds=set(),
        notice_checks_ran=0, notice_checks_total=0, notice_checks_never_ran=0)


@pytest.mark.parametrize("template", NOTICE_PARTIALS)
def test_a_dismiss_button_on_an_error_notice_is_not_red_on_red(template):
    html = _error_notice_html(template)
    # The red paint is the severity TAG, never the row the dismiss sits in.
    assert '<span class="tag solid err"' in html
    assert '<div class="prob">' in html
    assert re.search(r'<button class="key quiet sm" type="submit"[^>]*>'
                     r'<span class="t">dismiss</span>', html)
    css = CSS.read_text(encoding="utf-8")
    assert "background" not in _rule(css, ".prob")
    assert "var(--k-bg)" in _rule(css, ".key")          # the key's own paint
    assert "--k-bg: transparent" in _rule(css, ".key")
    quiet = _rule(css, ".key.quiet")
    assert "color: var(--text-2)" in quiet
    assert "var(--red)" not in quiet and "background" not in quiet


def test_the_banner_action_still_reads_as_something_to_click():
    """The quiet key drops its border; the pointer glyph in front of it is
    what still says "press me"."""
    css = CSS.read_text(encoding="utf-8")
    assert "content:" in _rule(css, ".key.quiet::before")
    assert "color: var(--hi)" in _rule(css, ".key.quiet:hover")


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "dash.db")
    yield c
    c.close()


def _collector_cards(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT kind, subject, cleared_at FROM notices "
        "WHERE subject LIKE 'collector poll %' ORDER BY subject")]


def test_the_migration_retires_the_orphaned_collector_slow_write_cards(conn):
    dbmod.migrate(conn, steps=[(v, s) for v, s in dbmod._MIGRATION_STEPS
                               if v < 56])
    now = dbmod.utcnow_iso()
    for subject in ("collector poll inventory", "collector poll alerts"):
        dbmod.notice(conn, "slow_write", "warn", subject,
                     body="held the database's write lock", fix="", now=now)
    # The live writer's own subjects, and a slow_poll card, must survive.
    dbmod.notice(conn, "slow_write", "warn", "a report from alex/BASE-RIG",
                 body="held the write lock", fix="", now=now)
    dbmod.notice(conn, "slow_poll", "warn", "collector poll inventory",
                 body="took longer than a cycle", fix="", now=now)
    conn.commit()

    dbmod.migrate(conn)

    by_key = {(r["kind"], r["subject"]): r["cleared_at"]
              for r in _collector_cards(conn)}
    assert by_key[("slow_write", "collector poll inventory")] is not None
    assert by_key[("slow_write", "collector poll alerts")] is not None
    assert by_key[("slow_poll", "collector poll inventory")] is None
    kept = conn.execute(
        "SELECT cleared_at FROM notices WHERE kind='slow_write' "
        "AND subject='a report from alex/BASE-RIG'").fetchone()
    assert kept["cleared_at"] is None


def test_replaying_the_step_is_a_no_op(conn):
    dbmod.migrate(conn)
    dbmod.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == dbmod.SCHEMA_VERSION
