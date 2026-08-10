from __future__ import annotations

from app.search import sanitize_fts_query


def test_empty_query_returns_none():
    assert sanitize_fts_query("") is None
    assert sanitize_fts_query("   ") is None


def test_single_term_is_quoted():
    assert sanitize_fts_query("pier") == '"pier"'


def test_multiple_terms_anded_and_quoted():
    assert sanitize_fts_query("sailors pier") == '"sailors" AND "pier"'


def test_quoted_phrase_preserved_as_single_term():
    assert sanitize_fts_query('"harbor exercise"') == '"harbor exercise"'


def test_mixed_phrase_and_bare_terms():
    assert (
        sanitize_fts_query('naval "harbor exercise" ship')
        == '"naval" AND "harbor exercise" AND "ship"'
    )


def test_special_characters_are_escaped_not_interpreted():
    # A raw colon/asterisk/paren would be FTS5 query syntax if not quoted;
    # here it must just be literal text inside a quoted term.
    assert sanitize_fts_query("pier:") == '"pier:"'
    assert sanitize_fts_query("pier*") == '"pier*"'
    assert sanitize_fts_query("()") == '"()"'


def test_embedded_double_quote_is_escaped_by_doubling():
    assert sanitize_fts_query('say "hi" there') == '"say" AND "hi" AND "there"'
