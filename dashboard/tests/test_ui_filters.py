"""The template filters must never be the reason a page does not render."""
from __future__ import annotations

import datetime as dt

from ccsync_dashboard import ui


def test_ago_reads_a_naive_timestamp_as_utc():
    """A hand-minted auth_sessions row from the 2026-08-24 ship carried
    `2026-08-24 03:16:18` (no offset) and every render of the Sessions page
    500'd for three days on the aware-minus-naive subtraction."""
    naive = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).replace(tzinfo=None)
    assert ui.ago(naive.strftime("%Y-%m-%d %H:%M:%S")) == "3h ago"
    assert ui.ago(naive.isoformat()) == "3h ago"


def test_ago_still_handles_the_normal_shapes():
    aware = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    assert ui.ago(aware.isoformat()) == "5m ago"
    assert ui.ago(None) == "never"
    assert ui.ago("") == "never"
    assert ui.ago("not a date") == "not a date"
