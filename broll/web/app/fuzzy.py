"""Fuzzy keyword fallback: FTS5 prefix retry + rapidfuzz typo correction.

Two independent, additive mechanisms, both gated by app.search on "the exact
query returned too few video results" (see FUZZY_MIN_VIDEO_RESULTS there) --
fuzzy matching is inherently looser than exact FTS5, so applying it
unconditionally would quietly reorder/pollute queries that already work
fine. Neither mechanism fires unless the exact pass under-delivered.

- prefix_query(): turns each raw term into a `term*` prefix match, for
  partial/truncated words FTS5's exact tokenizer would otherwise miss.
  Only meaningful against the porter/unicode61 tables (segments_fts,
  transcript_fts) -- prefix queries against a trigram-tokenized table would
  just get re-shredded into trigrams of the literal string including the
  '*', which is not a prefix query at all.

- correct_terms(): fixes actual misspellings/typos ("ambluance") that no
  prefix of the original string would ever reach, by matching each term
  against the corpus vocabulary with rapidfuzz and substituting the closest
  match above a confidence cutoff. The corrected terms then go back through
  the normal exact/quoted query path (sanitize_fts_query), so a corrected
  query is just an ordinary AND-of-terms search, no new query syntax needed.

Vocabulary source: the raw text columns of segments/transcript_segments,
word-split in Python -- deliberately NOT SQLite's fts5vocab virtual table
(vocabulary from segments_fts/transcript_fts would be Porter-STEMMED, e.g.
"ambulance" -> "ambul", "emergency" -> "emerg", since porter unicode61 stems
both index and query text; matching a typo against stems would frequently
"correct" a term that already matches fine into a different, non-word
stem). Scanning the literal column text instead keeps the vocabulary made of
real corpus words, exactly what an editor would type and what rapidfuzz's
scoring is calibrated against.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from app.db import read_search_generation

try:
    from rapidfuzz import fuzz, process
except ImportError:  # pragma: no cover -- rapidfuzz is a pyproject
    fuzz = None        # dependency; this guard matches the "never 500"
    process = None      # posture used throughout this feature.

# Columns scanned to build the vocabulary. search_norm is included since it
# already carries word-segmented CJK tokens (see migrations/
# 004_hybrid_search.sql); harmless to mix in alongside the Latin vocabulary
# since rapidfuzz's edit-distance scoring naturally won't rank a CJK token
# close to a misspelled Latin one.
_SEGMENT_VOCAB_COLUMNS = (
    "description", "objects", "setting", "onscreen_text", "onscreen_text_en", "search_norm",
)
_TRANSCRIPT_VOCAB_COLUMNS = ("text", "search_norm")

# A token must be made only of word characters to enter the vocabulary --
# this is a *source* of correction candidates, not user input, but keeping
# it to real word-shaped tokens avoids polluting the vocabulary with stray
# punctuation fragments.
_WORD_RE = re.compile(r"[\w]+", re.UNICODE)

# Strip everything except word characters and whitespace (Python's \w is
# unicode-aware, so this keeps CJK ideographs too) before quoting for the
# FTS5 prefix operator. Quoting (rather than a bare `term*`) matters beyond
# injection-safety: an unquoted term that happens to spell a reserved FTS5
# keyword (OR/AND/NOT) is parsed as that operator even with a trailing '*'
# and breaks the query syntax -- quoting sidesteps keyword parsing entirely,
# the same reason sanitize_fts_query() quotes every term for the exact path.
_TERM_CLEAN_RE = re.compile(r"[^\w\s]+", re.UNICODE)

_MIN_TERM_LEN_FOR_CORRECTION = 3
# rapidfuzz `ratio` (pure edit distance) cutoff — see correct_terms for why NOT
# WRatio. High enough that unrelated words are not "corrected" into each other,
# low enough to catch a couple of transposed letters: measured on the real
# corpus, "ambluance" -> "ambulance" scores 89 and "nucelar" -> "nuclear" 86,
# while "mars" -> "marshall" scores 50 and is correctly left alone.
_CORRECTION_SCORE_CUTOFF = 82
# A typo is roughly the same length as the word meant. Restricting candidates
# by length is what stops a short vocabulary entry being proposed for a long
# query term (and vice versa) regardless of how the scorer behaves.
_MAX_LEN_DELTA_FOR_CORRECTION = 3
# Minimum raw term length before prefix expansion is allowed — see
# prefix_query. Below this the Porter stem is short enough that `stem*`
# matches an unrelated class of words.
_MIN_TERM_LEN_FOR_PREFIX = 5


@dataclass(frozen=True)
class CorrectionIndex:
    """The vocabulary in the shape correct_terms actually consumes it.

    Both members used to be rebuilt per request from the cached word list
    (BROLL-WEB-6, 2026-08-14): measured on the live 15k-clip archive, the
    lowercase map is 315,562 entries and ~80 ms to build, and the length-window
    candidate list for a 9-character term was a 167,093-entry scan of it at
    ~19 ms per query term -- ~110 ms of pure re-derivation added to exactly the
    queries that already under-delivered (fuzzy only runs when the exact pass
    returned fewer than FUZZY_MIN_VIDEO_RESULTS videos). Nothing about either
    depends on the query, so both are derived once per vocabulary generation
    and `candidates` becomes a concat of a handful of length buckets.

    `lower_to_original` maps a lowercased vocabulary word to the corpus casing
    to substitute back in; `by_length` buckets those lowercased keys by their
    length, so the _MAX_LEN_DELTA_FOR_CORRECTION window is a slice of buckets
    rather than a full scan.
    """

    lower_to_original: dict[str, str]
    by_length: dict[int, list[str]]

    def candidates(self, length: int, max_delta: int) -> list[str]:
        out: list[str] = []
        for n in range(length - max_delta, length + max_delta + 1):
            out.extend(self.by_length.get(n, ()))
        return out


def _build_correction_index(vocab: Any) -> CorrectionIndex:
    """Derive a CorrectionIndex from a vocabulary of corpus words.

    Very short candidates (1-2 chars) are dropped here, as they always were:
    rapidfuzz's WRatio rates a short substring match (e.g. "an" inside
    "ambluance") above the actual intended word purely because the short
    string matches "completely" within the longer one. Same length floor
    already applied to query terms in correct_terms.
    """
    lower_to_original: dict[str, str] = {}
    for term in vocab:
        if len(term) >= _MIN_TERM_LEN_FOR_CORRECTION:
            lower_to_original[term.lower()] = term
    by_length: dict[int, list[str]] = {}
    for lower in lower_to_original:
        by_length.setdefault(len(lower), []).append(lower)
    return CorrectionIndex(lower_to_original=lower_to_original, by_length=by_length)


class VocabularyCache:
    """Process-wide cache of the distinct word tokens present in the corpus's
    text columns (see _SEGMENT_VOCAB_COLUMNS/_TRANSCRIPT_VOCAB_COLUMNS).
    Keyed by (db file path, write generation, segments+transcript row count,
    each table's highest id) -- the same cheap-staleness trick as
    app.semantic.SemanticSearch's matrix cache -- so it is rebuilt only when the
    underlying data actually changes, not on every request.

    The count and high-water marks came first (BROLL-17, 2026-08-11): a re-index
    that replaces a clip's segments with the same NUMBER of rows leaves the
    count untouched, and the vocabulary then keeps correcting typos towards
    words that are no longer in the corpus. They still miss the case where the
    replacement lands back on the very same ids, which is what the generation
    counter closes -- meta.search_generation, bumped in-transaction by every
    write path that touches segments/transcript_segments (migration 010,
    KNOWN_BUGS R2). That counter depends on those write paths remembering to
    bump it, so each is pinned by a test and the older, data-derived components
    stay in the key as belt and braces.
    """

    def __init__(self) -> None:
        self._vocab: list[str] | None = None
        self._key: tuple[str, int, int, int, int] | None = None
        self._index: CorrectionIndex | None = None
        self._index_of: Any = None
        self._lock = threading.Lock()

    def reset(self) -> None:
        self._vocab = None
        self._key = None
        self._index = None
        self._index_of = None

    def _cache_key(self, conn: sqlite3.Connection) -> tuple[str, int, int, int, int]:
        db_row = conn.execute("PRAGMA database_list").fetchone()
        db_path = db_row[2] if db_row else ""
        count, max_seg, max_cue = conn.execute(
            "SELECT (SELECT COUNT(*) FROM segments) "
            "+ (SELECT COUNT(*) FROM transcript_segments), "
            "COALESCE((SELECT MAX(id) FROM segments), 0), "
            "COALESCE((SELECT MAX(id) FROM transcript_segments), 0)"
        ).fetchone()
        return (db_path, read_search_generation(conn), count, max_seg, max_cue)

    def get(self, conn: sqlite3.Connection) -> list[str]:
        key = self._cache_key(conn)
        with self._lock:
            if self._vocab is not None and self._key == key:
                return self._vocab
            vocab = self._build(conn)
            self._vocab = vocab
            self._key = key
            return vocab

    def get_correction_index(self, conn: sqlite3.Connection) -> CorrectionIndex:
        """The same vocabulary, derived into what correct_terms needs -- see
        CorrectionIndex (BROLL-WEB-6, 2026-08-14).

        Cached against the IDENTITY of the list get() handed back rather than
        against a second copy of the cache key: get() returns the very same
        list object for as long as its key holds and a brand-new one the moment
        it rebuilds, so identity tracks the existing invalidation exactly, with
        no way for the two caches to disagree about which generation they are
        on. A subclass whose get() returns a fresh object each call (the test
        doubles) simply rebuilds each call -- correct, just uncached.
        """
        vocab = self.get(conn)
        with self._lock:
            if self._index is not None and self._index_of is vocab:
                return self._index
            index = _build_correction_index(vocab)
            self._index = index
            self._index_of = vocab
            return index

    def _build(self, conn: sqlite3.Connection) -> list[str]:
        terms: set[str] = set()

        seg_cols = ", ".join(_SEGMENT_VOCAB_COLUMNS)
        for row in conn.execute(f"SELECT {seg_cols} FROM segments").fetchall():
            for field in row:
                if field:
                    terms.update(_WORD_RE.findall(field))

        tr_cols = ", ".join(_TRANSCRIPT_VOCAB_COLUMNS)
        for row in conn.execute(f"SELECT {tr_cols} FROM transcript_segments").fetchall():
            for field in row:
                if field:
                    terms.update(_WORD_RE.findall(field))

        return sorted(terms)


_default_vocab_cache: VocabularyCache | None = None


def get_vocabulary_cache() -> VocabularyCache:
    global _default_vocab_cache
    if _default_vocab_cache is None:
        _default_vocab_cache = VocabularyCache()
    return _default_vocab_cache


def available() -> bool:
    return process is not None


def correct_terms(conn: sqlite3.Connection, terms: list[str]) -> list[str] | None:
    """Return a copy of `terms` with obvious typos corrected against the
    corpus vocabulary, or None if rapidfuzz is unavailable, there is no
    vocabulary yet, or no term could be improved (so callers can skip a
    pointless re-query rather than re-running an identical search).
    """
    if not available() or not terms:
        return None
    index = get_vocabulary_cache().get_correction_index(conn)
    vocab_lower = index.lower_to_original
    if not vocab_lower:
        return None

    corrected: list[str] = []
    changed = False
    for term in terms:
        lower = term.lower()
        if len(term) < _MIN_TERM_LEN_FOR_CORRECTION or lower in vocab_lower:
            # Already an exact vocabulary hit (or too short to safely
            # correct) -- leave it alone, only touch terms that would
            # otherwise miss entirely.
            corrected.append(term)
            continue
        # fuzz.ratio, NOT WRatio. WRatio blends in partial-ratio scoring, which
        # rates a short substring as a perfect match of the longer string that
        # contains it: measured on the real corpus, "ambluance" corrected to
        # "Blu" (it sits inside am-BLU-ance) and "mars" became "Marshall".
        # Rewriting a term the user actually meant is worse than not correcting
        # at all, because it silently changes what was searched for. Plain ratio
        # is edit-distance based and symmetric, so containment earns nothing.
        candidates = index.candidates(len(lower), _MAX_LEN_DELTA_FOR_CORRECTION)
        match = process.extractOne(
            lower,
            candidates,
            scorer=fuzz.ratio,
            score_cutoff=_CORRECTION_SCORE_CUTOFF,
        )
        if match is None:
            corrected.append(term)
            continue
        best_lower = match[0]
        corrected.append(vocab_lower[best_lower])
        changed = True
    return corrected if changed else None


def prefix_query(terms: list[str]) -> str | None:
    """Build an FTS5 prefix-match query ('"term"*' per token/phrase, ANDed)
    from raw user terms, for the porter/unicode61 tables only (see module
    docstring). Returns None only if no term survives sanitization (e.g. the
    query was entirely punctuation).

    A query whose terms are ALL too short to expand therefore comes back as a
    plain quoted AND-of-terms, i.e. byte-identical to the exact pass's query.
    That is the caller's problem to notice, not this function's: app.search's
    _run_fuzzy_pass compares the two and skips the redundant pass, because
    running it would register duplicate RRF sources (BROLL-WEB-5,
    2026-08-14). This docstring promised the None until then and did not
    deliver it; returning None here instead would also swallow the mixed
    punctuation case, where the sanitized form is a genuinely different query.

    Short terms are NOT prefix-expanded. The index is Porter-stemmed, so the
    stem is expanded rather than the word typed: measured, "mars" stems to
    "mar" and `mar*` then matches "marriage"/"married", which made the
    nonsense query "wedding on mars" return same-sex-marriage footage. The
    longer the term, the less its stem over-reaches — and stemming already
    covers the common case prefix matching was meant for ("surf" and
    "surfing" share a stem without any prefix expansion at all).
    """
    parts: list[str] = []
    for term in terms:
        safe = " ".join(_TERM_CLEAN_RE.sub(" ", term).split())
        if not safe:
            continue
        if len(safe) < _MIN_TERM_LEN_FOR_PREFIX:
            parts.append(f'"{safe}"')  # exact, no expansion
        else:
            parts.append(f'"{safe}"*')
    return " AND ".join(parts) if parts else None
