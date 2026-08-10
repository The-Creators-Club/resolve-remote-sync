"""app.fuzzy: vocabulary building (fts5vocab) + rapidfuzz typo correction +
FTS5 prefix query construction. See its module docstring for why prefix
matching and typo correction are separate, additive mechanisms.
"""
from __future__ import annotations

from app import fuzzy
from tests.factories import insert_segment, insert_video


def _seed_vocab(conn):
    v = insert_video(conn, share="broll", rel_path="clip.mov")
    insert_segment(
        conn,
        v,
        description="An ambulance rushes past a harbor exercise drill",
        objects="ambulance, emergency vehicle, siren",
        setting="urban, daytime",
    )
    return v


def test_vocabulary_contains_corpus_words(conn):
    _seed_vocab(conn)
    vocab = fuzzy.get_vocabulary_cache().get(conn)
    assert "ambulance" in vocab
    assert "harbor" in vocab


def test_correct_terms_fixes_a_transposed_misspelling(conn):
    _seed_vocab(conn)
    corrected = fuzzy.correct_terms(conn, ["ambluance"])
    assert corrected == ["ambulance"]


def test_correct_terms_leaves_exact_vocabulary_hits_alone(conn):
    _seed_vocab(conn)
    corrected = fuzzy.correct_terms(conn, ["ambulance", "harbor"])
    assert corrected is None  # nothing needed correction -> no pointless re-query


def test_correct_terms_returns_none_when_nothing_improves(conn):
    _seed_vocab(conn)
    # "xyzzy" is nowhere near anything in the vocabulary.
    corrected = fuzzy.correct_terms(conn, ["xyzzy"])
    assert corrected is None


def test_vocabulary_cache_invalidates_on_new_data(conn):
    _seed_vocab(conn)
    first = fuzzy.get_vocabulary_cache().get(conn)
    assert "submarine" not in first

    v2 = insert_video(conn, share="broll", rel_path="clip2.mov")
    insert_segment(conn, v2, description="A submarine surfaces near the coast")

    second = fuzzy.get_vocabulary_cache().get(conn)
    assert "submarine" in second


def test_prefix_query_quotes_terms_and_appends_star():
    q = fuzzy.prefix_query(["police", "shoot"])
    assert q == '"police"* AND "shoot"*'


def test_prefix_query_neutralizes_fts_reserved_words():
    # A bare "OR"/"AND"/"NOT" would be parsed as an FTS5 boolean operator if
    # left unquoted -- quoting prevents that, with or without the '*' suffix.
    # Both terms here are below _MIN_TERM_LEN_FOR_PREFIX so neither is
    # expanded (see test_short_terms_are_not_prefix_expanded), but the
    # quoting -- which is what this test is about -- still applies.
    q = fuzzy.prefix_query(["pier", "OR"])
    assert q == '"pier" AND "OR"'

    # ...and a long-enough term is still quoted when it IS expanded.
    assert fuzzy.prefix_query(["harbour", "OR"]) == '"harbour"* AND "OR"'


def test_short_terms_are_not_prefix_expanded():
    """Prefix expansion applies to the Porter STEM, not the word typed, so a
    short term over-reaches badly: "mars" stems to "mar" and `mar*` matched
    "marriage", making the nonsense query "wedding on mars" return same-sex
    marriage footage on the real archive.
    """
    assert fuzzy.prefix_query(["mars"]) == '"mars"'
    assert fuzzy.prefix_query(["surfing"]) == '"surfing"*'
    # mixed: only the long term expands
    assert fuzzy.prefix_query(["mars", "surfing"]) == '"mars" AND "surfing"*'


def test_prefix_query_strips_unsafe_characters():
    # Non-word punctuation (quotes, semicolons, parens) is replaced with
    # whitespace rather than deleted outright, so two words separated only
    # by punctuation don't get silently glued into one token.
    q = fuzzy.prefix_query(['pier";DROP', "()"])
    assert q == '"pier DROP"*'


def test_prefix_query_empty_for_all_punctuation():
    assert fuzzy.prefix_query(["()", ":::"]) is None


def test_correction_does_not_pick_a_contained_substring(monkeypatch):
    """Regression, measured on the real corpus: with rapidfuzz's WRatio the
    term "ambluance" corrected to "Blu" -- WRatio blends in partial-ratio
    scoring, which rates a short string as a perfect match of any longer
    string containing it ("am-BLU-ance"). Rewriting a term into an unrelated
    shorter one silently changes what the user searched for, which is worse
    than not correcting at all.
    """
    if not fuzzy.available():
        import pytest

        pytest.skip("rapidfuzz not installed")

    class FakeCache:
        def get(self, conn):
            return {"ambulance", "ambulances", "Blu", "blues", "nuclear", "marshall"}

    monkeypatch.setattr(fuzzy, "get_vocabulary_cache", lambda: FakeCache())

    out = fuzzy.correct_terms(object(), ["ambluance"])
    assert out is not None
    assert out[0].lower().startswith("ambulance"), out


def test_correction_leaves_a_real_word_alone(monkeypatch):
    """"mars" became "Marshall" under WRatio. A term that is not a near-typo
    of any vocabulary entry must pass through untouched."""
    if not fuzzy.available():
        import pytest

        pytest.skip("rapidfuzz not installed")

    class FakeCache:
        def get(self, conn):
            return {"marshall", "marriage", "married", "surfing"}

    monkeypatch.setattr(fuzzy, "get_vocabulary_cache", lambda: FakeCache())

    # length-delta guard plus edit-distance scoring both reject "marshall"
    assert fuzzy.correct_terms(object(), ["mars"]) is None
