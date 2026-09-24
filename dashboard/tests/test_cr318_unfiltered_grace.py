"""CR-318 (2026-09-24): a folder ticked minutes ago is unfiltered for one
sync turn by construction (the companion keeps it paused until its
.stignore is confirmed), so "a shared folder has no filter" waits out a
grace period for a FRESH tick - and only for one.
"""

from __future__ import annotations

from ccsync_dashboard import alerts
from ccsync_dashboard import db as dbmod

TICKED = "2026-09-24T03:05:00+00:00"


class _Ctx:
    def __init__(self, conn, now, guard):
        self.conn, self.now, self._guard = conn, now, guard
        self.editors = [{"editor_username": "ruskin", "machine": "PC"}]

    def guard(self, e):
        return self._guard

    def name(self, who):
        return who


def _setup(conn, *slugs, at=TICKED):
    for slug in slugs:
        dbmod.upsert_project(conn, slug, slug, f"/data/{slug}", at)
        dbmod.add_selection(conn, "ruskin", slug, "alex", at, machine="PC")
    conn.commit()


def _found(conn, now, count, names):
    g = {"folders_unfiltered": count, "folders_unfiltered_names": names}
    return alerts._check_folders_unfiltered(_Ctx(conn, now, g))


def test_a_fresh_tick_is_not_an_alert(conn):
    _setup(conn, "2026-ff5-film-1-2")
    assert _found(conn, "2026-09-24T03:27:00+00:00", 1, "2026-ff5-film-1-2") == []


def test_it_alerts_once_the_grace_is_over(conn):
    _setup(conn, "2026-ff5-film-1-2")
    assert len(_found(conn, "2026-09-24T03:36:00+00:00", 1, "2026-ff5-film-1-2")) == 1


def test_an_old_tick_alerts_straight_away(conn):
    _setup(conn, "old", at="2026-09-01T00:00:00+00:00")
    assert len(_found(conn, "2026-09-24T03:27:00+00:00", 1, "old")) == 1


def test_one_old_folder_among_fresh_ones_alerts(conn):
    _setup(conn, "fresh")
    _setup(conn, "old", at="2026-09-01T00:00:00+00:00")
    assert len(_found(conn, "2026-09-24T03:27:00+00:00", 2, "fresh, old")) == 1


def test_no_names_means_cannot_tell_and_alerts(conn):
    _setup(conn, "fresh")
    assert len(_found(conn, "2026-09-24T03:27:00+00:00", 1, None)) == 1


def test_more_folders_than_names_alerts(conn):
    """The report carries ten names; an eleventh could be an old tick."""
    _setup(conn, "fresh")
    assert len(_found(conn, "2026-09-24T03:27:00+00:00", 11, "fresh")) == 1


def test_a_folder_with_no_tick_alerts(conn):
    _setup(conn, "fresh")
    assert len(_found(conn, "2026-09-24T03:27:00+00:00", 1, "never-ticked")) == 1
