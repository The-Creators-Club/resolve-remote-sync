"""app.fuzzy: vocabulary building (fts5vocab) + rapidfuzz typo correction +
FTS5 prefix query construction. See its module docstring for why prefix
matching and typo correction are separate, additive mechanisms.
"""
from __future__ import annotations

from app import fuzzy, search
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

    # Subclassed rather than duck-typed: correct_terms consumes the derived
    # CorrectionIndex (BROLL-WEB-6), which the base class builds from whatever
    # get() hands back -- so overriding get() alone still injects the exact
    # vocabulary this test is about.
    class FakeCache(fuzzy.VocabularyCache):
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

    class FakeCache(fuzzy.VocabularyCache):
        def get(self, conn):
            return {"marshall", "marriage", "married", "surfing"}

    monkeypatch.setattr(fuzzy, "get_vocabulary_cache", lambda: FakeCache())

    # length-delta guard plus edit-distance scoring both reject "marshall"
    assert fuzzy.correct_terms(object(), ["mars"]) is None


# ---------------------------------------------------------------------------
# BROLL-WEB-5: the pass level, which the string-level tests above cannot see.
# ---------------------------------------------------------------------------


def _fuzzy_sources(conn, terms):
    rank_lists: dict = {}
    meta: dict = {}
    search._run_fuzzy_pass(conn, terms, "", [], "", [], rank_lists, meta)
    return set(rank_lists)


def test_an_all_short_term_query_does_not_re_run_the_exact_query(conn):
    """prefix_query leaves a term under its length floor unexpanded, so for an
    all-short-term query it hands back the exact pass's query verbatim. Running
    it again is not merely two wasted FTS queries: fuzzy_prefix_segments_fts
    and fuzzy_prefix_transcript_fts register as separate RRF sources carrying
    the exact pass's own ranking, so the porter tables vote twice while the
    trigram tables (which the prefix pass skips entirely) vote once -- and a
    CJK substring hit that only the trigram table can find gets demoted for it.
    """
    _seed_vocab(conn)
    assert fuzzy.prefix_query(["past"]) == '"past"', (
        "premise of this test: nothing expanded, so the query is unchanged"
    )

    sources = _fuzzy_sources(conn, ["past"])

    assert not {s for s in sources if s.startswith("fuzzy_prefix_")}


def test_a_term_long_enough_to_expand_still_gets_its_prefix_pass(conn):
    """The other side of the guard -- this is a real, different query."""
    _seed_vocab(conn)
    assert fuzzy.prefix_query(["harbor"]) == '"harbor"*'

    sources = _fuzzy_sources(conn, ["harbor"])

    assert "fuzzy_prefix_segments_fts" in sources


# ---------------------------------------------------------------------------
# BROLL-WEB-6: the derived structures are cached with the vocabulary, not
# rebuilt per request.
# ---------------------------------------------------------------------------


def test_the_correction_index_is_built_once_per_generation(conn):
    """Measured on the live archive: the lowercase map is 315,562 entries and
    ~80 ms, and the length-window candidate list was a 167,093-entry scan of it
    per query TERM -- ~110 ms of pure re-derivation on every fuzzy-triggered
    search, i.e. on exactly the queries that were already the slowest."""
    _seed_vocab(conn)
    cache = fuzzy.get_vocabulary_cache()

    first = cache.get_correction_index(conn)
    assert cache.get_correction_index(conn) is first


def test_the_correction_index_follows_the_vocabulary_invalidation(conn):
    """Same key, same invalidation -- a derived cache that outlived the
    vocabulary would keep correcting typos towards words the corpus no longer
    has, which is the BROLL-17/R2 staleness this must not reintroduce."""
    _seed_vocab(conn)
    cache = fuzzy.get_vocabulary_cache()
    first = cache.get_correction_index(conn)
    assert "submarine" not in first.lower_to_original

    v2 = insert_video(conn, share="broll", rel_path="clip2.mov")
    insert_segment(conn, v2, description="A submarine surfaces near the coast")

    second = cache.get_correction_index(conn)
    assert second is not first
    assert "submarine" in second.lower_to_original


def test_the_length_buckets_agree_with_a_full_scan(conn):
    """The buckets replaced a per-term filter over the whole map; they have to
    select exactly what that filter did, or a correction quietly changes."""
    _seed_vocab(conn)
    index = fuzzy.get_vocabulary_cache().get_correction_index(conn)

    for length in range(1, 12):
        expected = {
            v for v in index.lower_to_original
            if abs(len(v) - length) <= fuzzy._MAX_LEN_DELTA_FOR_CORRECTION
        }
        got = index.candidates(length, fuzzy._MAX_LEN_DELTA_FOR_CORRECTION)
        assert len(got) == len(set(got)), "no word may be scored twice"
        assert set(got) == expected


def test_the_index_keeps_the_short_word_floor(conn):
    """1-2 char candidates are excluded here exactly as they were in the
    per-request comprehension -- see _build_correction_index."""
    _seed_vocab(conn)
    index = fuzzy.get_vocabulary_cache().get_correction_index(conn)

    assert all(
        len(v) >= fuzzy._MIN_TERM_LEN_FOR_CORRECTION for v in index.lower_to_original
    )
    assert "an" not in index.lower_to_original  # "An ambulance rushes past ..."
