"""Rule-based category assignment: one subject folder per clip.

The archive has 8,899 distinct themes across 2,093 videos, 75% of them on
exactly one video. Folders built from themes directly would be thousands of
one-clip categories. These rules collapse many themes onto ~30 real subjects.
"""
from __future__ import annotations

import textwrap

import pytest

from broll_index.storage.sqlite_backend import SqliteBackend
from broll_index.taxonomy import (
    assign_categories,
    compile_patterns,
    pick_category,
    score_categories,
)

CATS = [
    {"slug": "energy/nuclear", "label": "Nuclear", "match": ["nuclear", "reactor*"]},
    {"slug": "society/government-politics", "label": "Politics",
     "match": ["government*", "policy"]},
    {"slug": "leisure/animals-pets", "label": "Pets", "match": ["cat", "cats", "dog"]},
    {"slug": "society/transport-safety", "label": "Transport", "match": ["transport*"]},
    {"slug": "leisure/sport-outdoor", "label": "Sport", "match": ["sport", "sports"]},
]


# --- word boundaries ----------------------------------------------------------

def test_a_pattern_matches_whole_words_not_substrings():
    """Plain substring matching put 314 videos in animals-pets because `cat`
    matches "education" and "category". The true count is 37."""
    rx = compile_patterns(["cat"])
    assert any(r.search("cat cafe") for r in rx)
    assert not any(r.search("education") for r in rx)
    assert not any(r.search("category") for r in rx)
    assert not any(r.search("advocate") for r in rx)


def test_sport_does_not_match_transport():
    rx = compile_patterns(["sport"])
    assert any(r.search("water sport") for r in rx)
    assert not any(r.search("public transport") for r in rx)
    assert not any(r.search("transportation") for r in rx)


def test_a_trailing_star_is_a_prefix_match():
    rx = compile_patterns(["recycl*"])
    assert any(r.search("recycling plant") for r in rx)
    assert any(r.search("recyclable waste") for r in rx)
    assert not any(r.search("bicycle") for r in rx), "prefix still respects the word start"


# --- picking one home ---------------------------------------------------------

def test_score_counts_matching_themes_per_category():
    scores = score_categories(["nuclear power", "reactor safety", "government policy"], CATS)
    assert scores["energy/nuclear"] == 2
    assert scores["society/government-politics"] == 1


def test_the_dominant_subject_wins():
    assert pick_category(["nuclear waste", "reactor", "government"], CATS) == "energy/nuclear"


def test_a_tie_goes_to_the_narrower_category():
    """The whole design of one-home-per-clip. A reactor clip tagged both
    `nuclear` and `government-politics` belongs in nuclear: "politics" (416
    videos archive-wide) tells an editor far less than "nuclear" (161)."""
    breadth = {"energy/nuclear": 161, "society/government-politics": 416}
    got = pick_category(["nuclear plant", "government"], CATS, breadth=breadth)
    assert got == "energy/nuclear"


def test_the_tie_break_is_deterministic_without_breadth():
    themes = ["nuclear plant", "government"]
    assert pick_category(themes, CATS) == pick_category(themes, CATS)


def test_no_matching_rule_returns_none():
    assert pick_category(["knitting", "philately"], CATS) is None


# --- end to end ---------------------------------------------------------------

RULES = textwrap.dedent("""\
    categories:
      - slug: energy/nuclear
        label: Nuclear
        description: Nuclear power.
        match: [nuclear, reactor*]
      - slug: society/government-politics
        label: Politics
        description: Government and politics.
        match: [government*, policy]
    descriptors:
      format:
        news: [news broadcast]
    """)


@pytest.fixture()
def rules_file(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text(RULES, encoding="utf-8")
    return p


def _index(db, video_id, themes):
    db.write_index_result(
        video_id, themes=themes, quality_flags=[], category_hint=None,
        segments=[], model="test",
    )


def _seed(db):
    a = db.upsert_video("s", "a.mov", status="discovered")
    _index(db, a, ["nuclear waste", "reactor"])
    b = db.upsert_video("s", "b.mov", status="discovered")
    _index(db, b, ["government policy"])
    c = db.upsert_video("s", "c.mov", status="discovered")
    _index(db, c, ["knitting"])
    return a, b, c


def test_assign_writes_one_category_per_video(tmp_path, schema_path, rules_file):
    db = SqliteBackend(tmp_path / "t.db", schema_path=schema_path)
    a, b, c = _seed(db)

    r = assign_categories(db, rules_file)

    assert r["assigned"] == 2
    assert r["unmatched"] == 1
    assert db.get_video(a)["category"] == "energy/nuclear"
    assert db.get_video(b)["category"] == "society/government-politics"
    assert db.get_video(c)["category"] is None, "no rule matched — left uncategorised, not guessed"


def test_assign_also_loads_the_categories_table(tmp_path, schema_path, rules_file):
    db = SqliteBackend(tmp_path / "t2.db", schema_path=schema_path)
    _seed(db)
    assign_categories(db, rules_file)
    slugs = {c["slug"] for c in db.get_categories()}
    assert slugs == {"energy/nuclear", "society/government-politics"}


def test_dry_run_changes_nothing(tmp_path, schema_path, rules_file):
    db = SqliteBackend(tmp_path / "t3.db", schema_path=schema_path)
    a, _, _ = _seed(db)

    r = assign_categories(db, rules_file, dry_run=True)

    assert r["assigned"] == 2, "still reports what it would do"
    assert db.get_video(a)["category"] is None
    assert db.get_categories() == []


def test_a_second_run_assigns_nothing_and_moves_nothing(tmp_path, schema_path, rules_file):
    """Categories are STABLE. The category is part of a clip's path in the
    shared archive and editors' timelines point at it, so re-running must never
    re-file a clip that already has one -- that would move a file out from
    under a cut already using it."""
    db = SqliteBackend(tmp_path / "t4.db", schema_path=schema_path)
    a, _, _ = _seed(db)
    first = assign_categories(db, rules_file)
    second = assign_categories(db, rules_file)

    assert first["assigned"] == 2
    assert second["assigned"] == 0, "nothing left to assign"
    assert second["kept"] == 2, "both left exactly where they were"
    assert db.get_video(a)["category"] == "energy/nuclear"


def test_better_rules_never_move_an_already_filed_clip(tmp_path, schema_path, rules_file):
    """Improving the rules only ever affects clips with no category yet."""
    db = SqliteBackend(tmp_path / "t6.db", schema_path=schema_path)
    a, _, _ = _seed(db)
    assign_categories(db, rules_file)
    db.update_video(a, category="society/government-politics")  # a deliberate hand-file

    assign_categories(db, rules_file)

    assert db.get_video(a)["category"] == "society/government-politics"


def test_reassign_is_the_explicit_escape_hatch(tmp_path, schema_path, rules_file):
    """Available for a supervised migration, off by default."""
    db = SqliteBackend(tmp_path / "t7.db", schema_path=schema_path)
    a, _, _ = _seed(db)
    assign_categories(db, rules_file)
    db.update_video(a, category="society/government-politics")

    assign_categories(db, rules_file, reassign=True)

    assert db.get_video(a)["category"] == "energy/nuclear", "re-derived from the rules"


def test_only_indexed_videos_are_considered(tmp_path, schema_path, rules_file):
    """A skipped or excluded row must never be filed into a browsable folder."""
    db = SqliteBackend(tmp_path / "t5.db", schema_path=schema_path)
    _seed(db)
    sk = db.upsert_video("s", "Proxy/skip.mov", status="skipped")
    _index(db, sk, ["nuclear"])
    db.update_video(sk, status="skipped")  # write_index_result sets 'indexed'

    assign_categories(db, rules_file)

    assert db.get_video(sk)["category"] is None
