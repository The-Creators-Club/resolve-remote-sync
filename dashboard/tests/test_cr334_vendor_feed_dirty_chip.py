"""CR-334 (2026-09-25): the Packages page's vendor-feed section stamped every
clean CI build (+dirty).

The owner's screenshot: 0.9.55 through 0.9.77, every one "(+dirty, <sha>)".
The vendor feed (`feed/channel.json`) records each of them as `git_dirty:
"0"`, a STRING, and `_vendor_rows` read it with `bool(...)`: bool("0") is
True. CR-267b (2026-09-11) fixed the same reading where a package is STORED
(`release_feed._feed_flag`) and missed this reader, which draws the feed's
own rows.
"""
from __future__ import annotations

from ccsync_dashboard import release_feed, ui


def _rows(monkeypatch, records):
    monkeypatch.setattr(release_feed, "verified_records", lambda state: records)
    monkeypatch.setattr(release_feed, "package_records", lambda recs: recs)
    return ui._vendor_rows(object(), {"packages": []})


def _record(version, dirty):
    return {"kind": "companion", "platform": "macos", "version": version,
            "git_dirty": dirty, "git_sha": "63d4290", "sha256": "ab" * 32,
            "size_bytes": 1, "filename": f"c-{version}.zip"}


def test_a_clean_feed_build_is_not_stamped_dirty(monkeypatch):
    rows = _rows(monkeypatch, [_record("0.9.77", "0")])
    assert rows and rows[0]["git_dirty"] is False


def test_a_dirty_feed_build_still_is(monkeypatch):
    rows = _rows(monkeypatch, [_record("0.9.77", "1")])
    assert rows[0]["git_dirty"] is True
