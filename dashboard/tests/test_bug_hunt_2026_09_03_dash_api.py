"""bug-hunt 2026-09-03, territory dash-api.

The server half of comp-core-3: a `local_manifest` key from a Mac is
DECOMPOSED (NFD), `projects.label` is composed (NFC), and `_slug_for_rel`
compared the two as exact strings before falling through to
`provision.slugify` -- which does not merely fail to match, it invents a
DIFFERENT slug, because a combining mark is a separator to its `[^a-z0-9]+`
split. One project on one machine then had two `editor_media_project` rows,
one of them for a project that does not exist. The rule is CR-90 /
docs/GOTCHAS.md section 17: compare through a normaliser, and never
normalise a path something opens.
"""

from __future__ import annotations

import unicodedata

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import provision
from ccsync_dashboard.api import _slug_for_rel

NOW = "2026-09-03T10:00:00+00:00"

# The composed and decomposed spellings of one folder name. Written as
# explicit escapes rather than a literal, because a source file's own
# normalisation is not something this test may depend on.
REL_NFC = unicodedata.normalize("NFC", "2026/FF5/Français")
REL_NFD = unicodedata.normalize("NFD", "2026/FF5/Français")
SLUG = "2026-ff5-fran-ais"


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "dash.db")
    dbmod.migrate(c)
    yield c
    c.close()


def test_the_two_spellings_of_one_rel_are_two_slugs_when_slugified_raw():
    """The premise. If this ever stops being true the finding is gone, and a
    test that only asserted the fix would pass for the wrong reason."""
    assert REL_NFC != REL_NFD
    assert provision.slugify(REL_NFC) != provision.slugify(REL_NFD)


def test_an_nfd_rel_finds_the_registered_project_by_its_nfc_label(conn):
    dbmod.upsert_project(conn, SLUG, REL_NFC, f"/data/{SLUG}", NOW)
    conn.commit()
    assert _slug_for_rel(conn, REL_NFC) == SLUG
    # comp-core-3: this is the one that used to miss the label, fall through
    # to slugify and answer "2026-ff5-franc-ais".
    assert _slug_for_rel(conn, REL_NFD) == SLUG


def test_an_unregistered_rel_slugifies_the_same_either_way(conn):
    """The fallback half. A report about a directory no project is registered
    for still has to produce ONE slug, or the phantom row comes back the
    moment a Mac reports a project the dashboard has not adopted yet."""
    assert _slug_for_rel(conn, REL_NFD) == _slug_for_rel(conn, REL_NFC) == SLUG


def test_a_manifest_in_either_spelling_writes_one_media_row(conn):
    """End to end over the write the report handler actually makes."""
    dbmod.upsert_project(conn, SLUG, REL_NFC, f"/data/{SLUG}", NOW)
    for rel in (REL_NFC, REL_NFD):
        dbmod.upsert_editor_media_project(
            conn, editor="leso", machine="LESO-MBP", slug=_slug_for_rel(conn, rel),
            mode="editor", n_originals=1, bytes_originals=10, n_proxies=0,
            bytes_proxies=0, truncated=False, now=NOW)
    conn.commit()
    slugs = [r["project_slug"] for r in conn.execute(
        "SELECT project_slug FROM editor_media_project WHERE editor_username='leso'")]
    assert slugs == [SLUG]
