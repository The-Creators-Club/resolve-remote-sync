# VENDORED VERBATIM from broll/indexer/broll_index/normalize.py -- DO NOT EDIT HERE.
# Edit the indexer's copy and re-copy it in BELOW THE MARKER LINE at the end of
# this header; everything under that line is byte-identical to the source on
# purpose, so the two trees can be compared mechanically -- and they ARE:
# server/tests/test_cross_component.py and tools/release.ps1 both strip this
# header and byte-compare the rest, the same gate ytdl_common.py already has.
#
# WHY A COPY AND NOT AN IMPORT (2026-08-18, docs/BROLL_INGEST_PLAN.md section
# 3.1). `search_norm` is the word-segmented, script-normalised CJK blob that
# makes a two-character on-screen-text term findable at all, and until now only
# the INDEXER computed it: the HTTP ingest path inserted segments with an empty
# one (http_backend.py -- search_norm "is not supported over the ingest API"),
# so anything indexed over HTTP was keyword-searchable only after somebody
# remembered to run a base-rig embed pass. Dashboard ingest has no base rig
# behind it, so the server computes it here -- and the server cannot import
# broll_index: the dashboard container has no anthropic, xxhash, pyyaml or
# requests, and must not grow ~50 MB and a licence surface for one pure
# function.
#
# THE TWO ENDS MUST AGREE CHARACTER FOR CHARACTER. A blob built by a different
# tokenisation than the one the query path normalises with does not match
# badly, it matches NOTHING -- and nothing is what the editor sees.
#
# jieba and opencc-python-reimplemented stay OPTIONAL exactly as they are
# upstream: absent, this returns raw text and logs once. The deployed container
# has both (dashboard/deploy/requirements.txt).
#
# The marker is the LAST line of this header and appears exactly once (both the
# gate and the test refuse an absent or ambiguous marker rather than skipping).
# Nothing but the source file's own bytes may follow it.
# --- vendored content below, byte-identical ---
"""CJK search normalization — the keyword-side fix for two measured gaps.

See migrations/004_hybrid_search.sql (header comment) and docs/indexing-findings.md
("Two remaining CJK search gaps, and the fix for both") for the full writeup. Short
version:

1. Two-character CJK terms (堵車, 檢調, 惡龍) fall below trigram's 3-character floor
   and, unlike a discrete `objects` entry, are not standalone tokens inside a run of
   unsegmented CJK prose — `unicode61` treats an unbroken CJK run as a single token.
2. Traditional/Simplified script variants don't cross-match: a Taiwan editor typing
   廈門堵車 will not find a mainland clip indexed as 厦门堵车.

Fix, measured: at index time, derive `search_norm` = raw text + both script variants
(OpenCC `s2twp` Simplified->Traditional, `tw2sp` Traditional->Simplified), each
word-segmented with jieba into space-separated tokens, deduplicated. Segmentation
inserts spaces jieba believes are word boundaries, so `unicode61` (which tokenizes on
whitespace/punctuation) can match a 2-character word like 堵車 exactly, below trigram's
floor; the OpenCC variants make that match script-agnostic in both directions.
`search_norm` is indexed alongside the raw columns (never replaces them) in both FTS
tables per the migration, so this is additive.

jieba and opencc-python-reimplemented are OPTIONAL imports: a machine without them
still indexes fine (English search, and whatever the raw-column FTS already reaches),
just without this enrichment — never a hard failure. Degradation logs once, not once
per call, since this runs at index time over every segment/transcript cue.
"""

from __future__ import annotations

import logging
import re
import threading

logger = logging.getLogger(__name__)

try:
    import jieba as _jieba

    _JIEBA_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised via monkeypatched flags in tests
    _jieba = None
    _JIEBA_AVAILABLE = False

try:
    from opencc import OpenCC

    _OPENCC_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised via monkeypatched flags in tests
    OpenCC = None  # type: ignore[assignment,misc]
    _OPENCC_AVAILABLE = False

_CJK_RE = re.compile(r"[一-鿿]")

_init_lock = threading.Lock()
_initialized = False
_s2twp = None  # OpenCC Simplified -> Traditional (Taiwan)
_tw2sp = None  # OpenCC Traditional (Taiwan) -> Simplified
_warned = False


def _warn_once(reason: str) -> None:
    global _warned
    if not _warned:
        logger.warning("normalize: %s — search_norm will fall back to raw text", reason)
        _warned = True


def _ensure_init() -> None:
    """Lazily build the jieba dictionary trie and OpenCC converters, once.

    jieba's first call builds its dictionary trie from disk (~1s) — expensive enough
    that it must not happen at import time or on every call, only lazily and once, the
    first time normalization is actually needed.
    """
    global _initialized, _s2twp, _tw2sp
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        if _JIEBA_AVAILABLE:
            _jieba.initialize()
        if _OPENCC_AVAILABLE:
            _s2twp = OpenCC("s2twp")
            _tw2sp = OpenCC("tw2sp")
        _initialized = True


def _segment(text: str) -> list[str]:
    """Word-segment `text` with jieba. Falls back to the whole string as one token
    when jieba is unavailable (still safe, just not as reachable below 3 characters)."""
    if not text:
        return []
    if not _JIEBA_AVAILABLE:
        return [text]
    return [tok.strip() for tok in _jieba.cut(text) if tok.strip()]


def searchable_blob(text: str) -> str:
    """Build the `search_norm` blob for `text`.

    raw + both script variants, each word-segmented, deduplicated, space-joined.
    Empty string in -> empty string out. Pure-ASCII/non-CJK input is returned
    unchanged (no segmentation applies, so there's nothing useful to add, and this
    guarantees English text is never damaged or pointlessly re-tokenized/deduped).
    """
    if not text:
        return ""

    if not _CJK_RE.search(text):
        return text

    if not _JIEBA_AVAILABLE and not _OPENCC_AVAILABLE:
        _warn_once("jieba and opencc-python-reimplemented are both unavailable")
        return text

    _ensure_init()

    variants = [text]
    if _OPENCC_AVAILABLE:
        try:
            variants.append(_s2twp.convert(text))
            variants.append(_tw2sp.convert(text))
        except Exception as e:  # noqa: BLE001 - never let OpenCC break indexing
            logger.warning("normalize: OpenCC conversion failed on %r: %s", text[:40], e)

    tokens: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        for tok in _segment(variant):
            if tok not in seen:
                seen.add(tok)
                tokens.append(tok)

    return " ".join(tokens)
