"""Hybrid (keyword + semantic) + fuzzy search backing /api/search.

Four keyword sources, on purpose (see SPEC.md "Database" and
docs/indexing-findings.md):

- segments_fts          -- porter unicode61 over description/objects/setting/
                            onscreen_text_en/search_norm. English stemming
                            and precision, visual index.
- segments_cjk_fts      -- trigram over onscreen_text/objects/search_norm.
                            Substring matching for Chinese, visual index.
- transcript_fts        -- porter unicode61 over text/search_norm. English
                            stemming, spoken-word index (SPEC.md "Database",
                            docs/indexing-findings.md's "audio is a better
                            index than pictures" finding).
- transcript_cjk_fts    -- trigram over text/search_norm. Chinese substring
                            matching, spoken-word index.

...plus a fifth, non-keyword source:

- semantic (app.semantic) -- brute-force cosine similarity over pre-computed
  multilingual sentence embeddings (schema v4). Finds meaning rather than
  characters/stems -- "bulletproof vest" <-> 防彈衣, English <-> Chinese,
  paraphrase <-> literal description -- entirely orthogonal to what any FTS
  tokenizer can do. Optional: degrades to no contribution if fastembed isn't
  installed or no embeddings exist yet (see app/semantic.py).

Within each of these two groups, sources are combined with Reciprocal Rank
Fusion (RRF) rather than by comparing scores directly -- see
reciprocal_rank_fusion()'s docstring for why that is not a minor
implementation detail but the load-bearing reason this works at all: bm25
magnitudes and cosine similarities are not on comparable scales, so anything
that tries to combine the numbers themselves (weighted sum, min-max rescale,
the old v2 "rank-position" merge extended naively to a 5th source) would be
asserting an exchange rate between "token match quality" and "semantic
closeness" with no principled basis. RRF only ever looks at rank position
within each source's own list.

IMPORTANT, and the reason for the word "groups" above -- keyword and semantic
are NOT equal-weight peers in mode="hybrid". Measured in
docs/indexing-findings.md ("Semantic search cannot prove absence"):
nearest-neighbour retrieval always has neighbours, so treating semantic as an
equal source meant every query -- including ones for footage that plainly
does not exist in the archive ("wedding ceremony", "snow mountain skiing")
-- returned 15-17 videos, confidently ranked. Neither an absolute cosine
floor nor a relative z-score gate separates genuine matches from noise
cleanly enough on their own (the doc's measured table). So in mode="hybrid":

1. Keyword determines the result set and its ordering. The four FTS sources
   are fused via RRF exactly as before, and that fusion alone decides which
   videos exist in the results and in what order.
2. Semantic may ADD videos the keyword pass missed entirely, floored at
   SEMANTIC_COSINE_FLOOR and capped at SEMANTIC_ONLY_MAX_VIDEOS extra videos
   (ranked by cosine score) -- never more than a handful of suggestions, and
   never enough to turn "we don't have that" into a full page of results.
3. Semantic hits on a video the keyword pass ALREADY found are dropped
   entirely rather than fused in: semantic must not re-rank or otherwise
   touch a confident keyword result, only append videos keyword missed.
4. Each result row carries "match": "keyword" or "semantic" (semantic =
   surfaced only by the vector side) so the extra videos can be grouped and
   visually distinguished by the frontend, always listed after the keyword
   results.

mode="semantic" is unaffected by any of the above except the floor, which
still applies -- it is an explicit user choice to search by meaning alone,
so nothing here caps or reorders it, but a hit under SEMANTIC_COSINE_FLOOR
still isn't a hit. mode="keyword" never touches app.semantic at all.

An empty result set remains possible, and is the correct, honest answer to a
query that matches nothing in the archive -- see SEMANTIC_ONLY_MAX_VIDEOS
and SEMANTIC_COSINE_FLOOR above.

A `fuzzy` fallback (app.fuzzy) kicks in when the exact keyword pass returns
too few video results: FTS5 prefix retry for partial words, and rapidfuzz
typo correction against the corpus vocabulary for actual misspellings
("ambluance" -> "ambulance"). Both are additive ranked sources fed through
the same RRF fusion, gated so a query that already works well is never
touched (see FUZZY_MIN_VIDEO_RESULTS).
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from app import config, fuzzy, semantic

_TOKEN_RE = re.compile(r'"([^"]*)"|(\S+)')

# Sentinel markers used for snippet() highlighting instead of raw HTML tags.
# The frontend HTML-escapes the surrounding text and only then swaps these
# sentinels for real <mark>/</mark> elements, so a description/objects value
# that happens to contain "<" or "&" can never be interpreted as markup.
SNIPPET_START = "\x01"
SNIPPET_END = "\x02"

# trigram tokenization needs at least 3 characters to produce any trigrams
# at all; below that the CJK table's MATCH is meaningless (and can raise on
# some builds rather than just miss), so we skip it entirely rather than
# relying solely on the try/except around the query. See
# docs/indexing-findings.md's measured table for why 2-char CJK terms (惡龍,
# 台北) are reachable only via discrete `objects` entries in the unicode61
# table, never via trigram.
_TRIGRAM_MIN_LEN = 3

# Standard RRF constant (Cormack, Clarke & Buettcher 2009). Large enough
# that a single source's #1 result doesn't automatically dominate a result
# ranked, say, 3rd-5th by several independent sources; the fusion is
# insensitive to the exact value in practice, this is the widely-used
# default and not something this corpus's scale calls for retuning.
RRF_K = 60

# Rows one FTS table may contribute to one pass. Uncapped, a broad query
# dragged its whole match set into Python -- full description/text column plus
# a snippet() per row -- and every one of those rows became a meta entry, an
# RRF rank-list entry and, for the paged videos, a serialized hit: measured
# 2026-08-14 on the live 15k-clip archive, q="the" pulled 9,663 transcript +
# 3,375 segment rows and produced 1.01 MB of `hits` for one 24-card page
# (BROLL-WEB-3). RRF only ever reads rank POSITION, and a row ranked past this
# contributes 1/(60+1000) -- ~6% of a top hit, i.e. noise -- so the cut cannot
# meaningfully reorder anything. It DOES cap `total` on a query broad enough to
# hit the limit: an exact "how many of the 15,103 clips contain 'the'" is worth
# less than the search coming back promptly over a Tailscale link.
FTS_SOURCE_ROW_LIMIT = 1000

# Hits serialized per video by search_videos. The grid reads hits[0] (card
# thumbnail + seek target) and the detail seekbar draws one yellow band per
# hit; on the real archive a single video carried 193 of them, transferred and
# parsed for nothing. Twenty bands is already past what the bar can
# distinguish, and the clip that actually gets opened still gets every segment
# and cue from /api/videos/{id} (BROLL-WEB-3, 2026-08-14).
MAX_HITS_PER_VIDEO = 20

# Only retry with fuzzy matching when the exact keyword pass is this thin on
# distinct videos. Keeps fuzzy matching from ever touching a query that
# already works -- see test requirement "an exact query with plenty of
# results is NOT altered by fuzzy expansion".
FUZZY_MIN_VIDEO_RESULTS = 5

# Minimum cosine similarity for a semantic hit to count at all, in EITHER
# mode="hybrid" or mode="semantic". Measured in
# docs/indexing-findings.md ("Semantic search cannot prove absence"):
# genuine matches ranged 0.477-0.641 (median 0.641) and queries for footage
# that does not exist in the archive still scored up to 0.642 -- the
# distributions overlap, so no floor can perfectly separate them. 0.50 was
# the specific value measured to keep 13/14 genuine matches from the
# calibration set while cutting most (not all) of the false ones; it is
# deliberately paired with the keyword-first design below rather than relied
# on alone -- see the module docstring's "Semantic search cannot prove
# absence" reasoning.
SEMANTIC_COSINE_FLOOR = 0.50

# In mode="hybrid", semantic search is a booster, not a parallel authority
# (see module docstring and docs/indexing-findings.md): it may surface videos
# the keyword pass missed entirely, but only up to this many extra videos, so
# a query with no real keyword support returns a small number of suggestions
# rather than nearest-neighbour retrieval's "always finds something" handing
# back a large fraction of the archive. Ranked by cosine score, best first.
# Has no effect on mode="semantic" (no keyword pass exists there to be
# "extra" relative to) or mode="keyword" (no semantic contribution at all).
SEMANTIC_ONLY_MAX_VIDEOS = 5

# In mode="hybrid", a CJK query that the keyword pass could not match at all
# gets NO semantic contribution (mode="semantic" is an explicit request for
# meaning-only retrieval and is exempt -- BROLL-WEB-1, 2026-08-14, where this
# gate ran before the mode split and emptied every CJK semantic search).
# Measured on the real archive: a multilingual embedding places
# any Chinese string near any Chinese content, so the score reflects script
# identity rather than meaning. Two strings absent from the corpus scored
# HIGHER than every genuine cross-lingual match --
#
#   李宗盛      0.882   (a singer who appears nowhere in the archive)
#   字幕志愿者   0.797   (a whisper hallucination artifact)
#   surfing big waves      0.743  <- best genuine match
#   military conscript death 0.552
#
# so no threshold separates them. Keyword search over CJK is strong once
# search_norm exists (10/10 on the archive query set), which is why dropping
# the semantic contribution here costs recall almost nothing and removes the
# whole class of leak. English queries are unaffected: they still reach
# Mandarin speech semantically, which is the cross-lingual feature.
_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def is_cjk_query(q: str) -> bool:
    """True when the query is predominantly CJK characters."""
    stripped = [ch for ch in (q or "") if not ch.isspace()]
    if not stripped:
        return False
    cjk = sum(1 for ch in stripped if _CJK_RE.match(ch))
    return cjk / len(stripped) >= 0.5


_VALID_MODES = {"hybrid", "keyword", "semantic"}

# "all" (default) searches every source and fuses as usual. "visual"
# restricts to what's SEEN (segments_fts/segments_cjk_fts + embeddings.source
# = 'segment'); "transcript" restricts to what's SAID
# (transcript_fts/transcript_cjk_fts + embeddings.source = 'transcript').
# Falls back to "all" for an unrecognized value, matching `mode`'s posture
# above -- see search_videos's docstring.
_VALID_SOURCES = {"all", "visual", "transcript"}

# Maps a validated `sources` value to the embeddings.source value semantic
# search should restrict to, or None for no restriction ("all").
_SOURCES_TO_EMBEDDING_SOURCE = {"all": None, "visual": "segment", "transcript": "transcript"}


def _segment_cjk_term(term: str) -> list[str]:
    """Word-segment an unquoted CJK term, mirroring what the indexer does.

    `search_norm` stores jieba-segmented text, so the index has 同志 and 伴侶 as
    separate tokens — but a user typing 同志伴侶 sends one unbroken token, which
    matches neither. Segmenting the QUERY the same way the INDEX was segmented
    is the missing half of that symmetry: 同志伴侶 becomes 同志 AND 伴侶 and hits.

    Falls back to the term unchanged if jieba is unavailable, so search still
    works (just without this rescue) on a machine without it.
    """
    try:
        import jieba
    except ImportError:
        return [term]
    parts = [p.strip() for p in jieba.cut(term) if p.strip()]
    # Only useful if it actually split into several real tokens.
    return parts if len(parts) > 1 else [term]


def _extract_terms(raw: str) -> list[str]:
    """Split free-text user input into literal terms/phrases (unquoting
    "phrases in quotes", stripping whitespace). Returns [] for blank input.

    An unquoted CJK run is additionally word-segmented — see
    _segment_cjk_term. A quoted "phrase" is left intact, so quoting remains
    the way to demand an exact unbroken match.
    """
    raw = raw.strip()
    if not raw:
        return []
    terms: list[str] = []
    for m in _TOKEN_RE.finditer(raw):
        phrase, word = m.group(1), m.group(2)
        text = phrase if phrase is not None else word
        text = (text or "").strip()
        if text:
            terms.append(text)
    return terms


def segmented_cjk_terms(terms: list[str]) -> list[str] | None:
    """Word-segmented form of a CJK query, or None if it changes nothing.

    Deliberately an ADDITIONAL pass rather than a rewrite of the primary
    query: segmenting up front breaks trigram substring matching, because
    激烈槍 (a deliberate substring probe) becomes 激烈 AND 槍 and the 1-char
    half can't form a trigram. Run both and let RRF fuse them — the exact
    term keeps substring matching, the segmented form rescues compounds like
    同志伴侶 that exist in the index only as separate tokens.
    """
    out: list[str] = []
    changed = False
    for t in terms:
        if is_cjk_query(t) and len(t) > 2:
            parts = _segment_cjk_term(t)
            if len(parts) > 1:
                out.extend(parts)
                changed = True
                continue
        out.append(t)
    return out if changed else None


def _terms_to_fts_query(terms: list[str]) -> str:
    quoted = [f'"{t.replace(chr(34), chr(34) * 2)}"' for t in terms]
    return " AND ".join(quoted)


def sanitize_fts_query(raw: str) -> str | None:
    """Turn free-text user input into a safe FTS5 MATCH query string.

    - Quoted phrases in the input ("naval exercise") are preserved as phrase
      matches (tokens must appear adjacent, in order).
    - Bare words are treated as individual literal terms.
    - Every term/phrase is re-quoted for the FTS5 query so that special
      characters (``-columnfilter:``, ``*``, ``(``, ``)``, etc.) typed by a
      user can never be interpreted as FTS5 query syntax -- they just become
      part of a quoted string, escaped by doubling any embedded quote.
    - Multiple terms are ANDed together (a hit must match all of them).

    Returns None if there is nothing meaningful to search on (empty/blank
    query), in which case callers should skip the MATCH clause entirely.
    """
    terms = _extract_terms(raw)
    if not terms:
        return None
    return _terms_to_fts_query(terms)


def _all_terms_too_short_for_trigram(terms: list[str]) -> bool:
    return all(len(t) < _TRIGRAM_MIN_LEN for t in terms)


def _snippet_around_term(text: str, terms: list[str], max_len: int) -> str | None:
    """Find the first literal (case-insensitive) occurrence of any of
    `terms` in `text` and wrap it with the same sentinel markers snippet()
    uses, trimming to roughly `max_len` characters around the match. Returns
    None if none of the terms occur literally in this text.
    """
    if not text:
        return None
    lowered = text.lower()
    for term in terms:
        idx = lowered.find(term.lower())
        if idx == -1:
            continue
        end_idx = idx + len(term)
        start = max(0, idx - max_len // 2)
        end = min(len(text), end_idx + max_len // 2)
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(text) else ""
        return (
            prefix
            + text[start:idx]
            + SNIPPET_START
            + text[idx:end_idx]
            + SNIPPET_END
            + text[end_idx:end]
            + suffix
        )
    return None


def _fallback_snippet(fields: list[str], terms: list[str], max_len: int = 80) -> str:
    """Build a usable snippet for a hit that didn't come through a table's
    own snippet() call (trigram-only hits, and semantic-only hits which have
    no FTS match at all). Prefers a highlighted excerpt around a literal
    term match in the first of `fields` that contains one, then falls back
    to a plain truncation of the first non-empty field (same
    sentinel-escaping approach, just no highlighted span).
    """
    for text in fields:
        snippet = _snippet_around_term(text, terms, max_len)
        if snippet is not None:
            return snippet
    for text in fields:
        if text:
            return text[:max_len] + "…" if len(text) > max_len else text
    return ""


# Reserved pseudo-slug for clips with no subject at all. Real slugs are
# lowercase words joined by "/", so a leading underscore cannot collide.
UNCATEGORISED = "_uncategorised"


def build_category_clause(category: str | None) -> tuple[str, list[Any]]:
    """category is a taxonomy slug prefix, e.g. 'military' also matches
    'military/naval'.

    UNCATEGORISED selects clips with no category. 163 of the archive's videos
    describe only format, place and look ("news broadcast", "daytime",
    "interior") with no subject to file them under, and inventing one would be
    worse than admitting it — but without a way to select them they would be
    reachable by search and invisible to browsing.
    """
    if not category:
        return "", []
    if category == UNCATEGORISED:
        # `status = 'indexed'` is load-bearing, not decoration. Without it this
        # also matches every clip not yet through the indexer -- proxied,
        # discovered, excluded -- because none of those has a category either.
        # On the real archive that was 1,414 videos behind a folder labelled
        # 163. "No subject was found in this clip" and "this clip has not been
        # described yet" are different facts and must not share a folder.
        return " AND v.category IS NULL AND v.status = 'indexed'", []
    return " AND (v.category = ? OR v.category LIKE ? || '/%')", [category, category]


def _like_escape(text: str) -> str:
    """Escape a literal for a LIKE pattern using ESCAPE '\\'.

    `_` matters as much as `%` here: it is a single-character wildcard and this
    archive's folder names are full of underscores, so an unescaped one silently
    widens the match.
    """
    return text.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


def build_shoot_clause(shoot: str | None) -> tuple[str, list[Any]]:
    """Select a Creators_Club shoot folder: `<share>` or `<share>::<Day / Cam>`.

    Own footage is browsed by where it was shot, not by subject, because it is
    deliberately not model-indexed and has no subject to browse by.

    Matched on DIRECTORY BOUNDARIES, like build_path_clause below. It used to
    join the components with `%`, i.e. "any rel_path containing these in order",
    which is not what the sidebar counted: _shoot_tree counts by exact rel_path
    components, so a node could promise N and a click return more (BROLL-9,
    2026-08-11) -- and `Day 1` also dragged in `Day 10`.

    The one thing a plain prefix cannot express is the `Proxy` component
    _shoot_tree folds out of the label, which may sit anywhere in the stored
    rel_path. So the prefix is offered with `Proxy/` reinserted at each position
    it could have been folded from -- exact, and still no assumption about where
    it sat. A trailing `Proxy/` (the usual shape, `Day 1/Fx3/Proxy/x.mov`) needs
    no alternative: it already falls inside the prefix's own wildcard.
    """
    if not shoot:
        return "", []
    share, _, leaf = shoot.partition("::")
    if not leaf:
        return " AND v.share = ?", [share]
    parts = [_like_escape(p) for p in leaf.split(" / ") if p]
    if not parts:
        return " AND v.share = ?", [share]
    prefixes = ["/".join(parts)]
    prefixes += ["/".join([*parts[:i], "Proxy", *parts[i:]]) for i in range(len(parts))]
    ors = " OR ".join("v.rel_path LIKE ? ESCAPE '\\'" for _ in prefixes)
    return (
        f" AND v.share = ? AND ({ors})",
        [share, *[f"{p}/%" for p in prefixes]],
    )


def build_path_clause(path: str | None) -> tuple[str, list[Any]]:
    """Select one folder of one share: `<share>` or `<share>::<rel/prefix>`.

    Deliberately NOT build_shoot_clause, which joins its parts with `%` and so
    matches any rel_path merely CONTAINING them in order. That looseness is
    fine for the two-level shoot browser it was written for and wrong for
    clicking a folder crumb: "Erosion/Interviewees" must mean that folder, at
    that depth, not every path where those words happen to appear in sequence.

    The prefix is matched as an exact directory boundary -- `prefix/%` -- so
    clicking `B-roll` cannot also drag in a sibling called `B-roll Archive`.
    Depth is whatever the caller sends: the crumb UI builds one of these per
    component, so every level of the path is selectable.
    """
    if not path:
        return "", []
    share, _, prefix = path.partition("::")
    if not share:
        return "", []
    prefix = prefix.strip("/")
    if not prefix:
        return " AND v.share = ?", [share]
    escaped = _like_escape(prefix)
    return (
        " AND v.share = ? AND v.rel_path LIKE ? ESCAPE '\\'",
        [share, f"{escaped}/%"],
    )


def creators_shares(conn: sqlite3.Connection | None = None) -> set[str]:
    """Every share holding our own footage.

    Two sources, unioned. BROLL_CREATORS_SHARES stays as the deploy-time
    override, but the authoritative signal is the share_roots table the indexer
    pushes: a source='proxies' share IS our own shot footage by definition
    (that is what the flag means — see indexer ShareConfig.source). Deriving it
    here is what keeps a newly indexed shoot share (ff4, ff3) from silently
    filing under Downloads until someone remembers to edit an env var on the
    NAS — which is exactly what happened to the FF4 shoot footage (2026-08-10).

    A THIRD source since 2026-08-18 (docs/BROLL_INGEST_PLAN.md §2):
    `share_roots.collection`, said outright. Deriving membership from
    `source='proxies'` works for the indexer's shares and fails for a shoot
    dropped onto the dashboard, which archives its ORIGINALS -- so without this
    column the customer's own camera footage would file itself under Downloads,
    which is the same class of mistake as the FF4 shoot above and one nobody
    could fix from the UI. NULL keeps the old rule for every share that
    predates the column.

    A pre-v6 DB has no share_roots table, and a pre-v11 one has no `collection`
    column; both fall back rather than 500. This is on the query path, which
    must not fail (see the module docstring).
    """
    shares = set(config.get_creators_shares())
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT share FROM share_roots WHERE source = 'proxies' "
                "OR collection = ?", (config.COLLECTION_CREATORS,)
            ).fetchall()
            shares.update(r["share"] for r in rows)
        except sqlite3.OperationalError:
            try:
                rows = conn.execute(
                    "SELECT share FROM share_roots WHERE source = 'proxies'"
                ).fetchall()
                shares.update(r["share"] for r in rows)
            except sqlite3.OperationalError:
                pass
    return shares


def build_collection_clause(
    collection: str | None, conn: sqlite3.Connection | None = None
) -> tuple[str, list[Any]]:
    """Restrict to one of the two browse roots, by share membership.

    'creators_club' is the derived share set (see creators_shares); 'downloads'
    is its complement, expressed as NOT IN rather than an enumerated list so a
    share added to the archive but not yet known still appears somewhere (as a
    download) instead of vanishing from both roots.

    An empty creators set makes 'creators_club' match nothing and 'downloads'
    match everything, which is the correct unconfigured behaviour.
    """
    # normalise_collection maps the legacy `creators_club` spelling onto this
    # deployment's own-footage slug and turns anything unknown into "" (=no
    # filter), so a bookmarked URL from before the slug became site data still
    # browses the same root (2026-08-17, COMMERCIAL_READINESS.md item 4).
    collection = config.normalise_collection(collection)
    if not collection:
        return "", []
    creators = sorted(creators_shares(conn))
    if not creators:
        return (" AND 1=0", []) if collection == config.COLLECTION_CREATORS else ("", [])
    placeholders = ", ".join("?" for _ in creators)
    op = "IN" if collection == config.COLLECTION_CREATORS else "NOT IN"
    return f" AND v.share {op} ({placeholders})", creators


def build_flags_exclude_clause(flags_csv: str | None) -> tuple[str, list[Any]]:
    """flags is a CSV of quality flag names to EXCLUDE (defect flags) -- any
    video that has ANY of these flags is dropped from the result set."""
    if not flags_csv:
        return "", []
    flags = [f.strip() for f in flags_csv.split(",") if f.strip()]
    if not flags:
        return "", []
    placeholders = ", ".join("?" for _ in flags)
    clause = (
        " AND v.id NOT IN (SELECT video_id FROM quality_flags "
        f"WHERE flag IN ({placeholders}))"
    )
    return clause, flags


def reciprocal_rank_fusion(
    rank_lists: dict[str, list[Any]], k: int = RRF_K
) -> dict[Any, float]:
    """Combine several independently-ranked lists of the same kind of key
    into one fused score per key, via Reciprocal Rank Fusion:

        score(key) = sum over sources containing key of  1 / (k + rank)

    with rank counted from 1 for the best item in that source's own list.

    WHY RRF and not any combination of the raw scores: the sources fused
    here are bm25 rankings from two different tokenizers over two different
    content types, plus a cosine similarity from brute-force semantic search
    (see module docstring). bm25 and cosine similarity are not merely on
    different scales, they measure fundamentally different things -- there
    is no principled exchange rate between "how well these query tokens
    matched this document" and "how close these two sentence embeddings
    are", so weighting or min-max-rescaling the numbers together would
    silently encode an arbitrary preference. RRF sidesteps that entirely: it
    only ever looks at a key's *position* within each source's own ranking,
    never the value behind it, so a document ranked #1 by bm25 and one
    ranked #1 by cosine contribute the exact same 1/(k+1) regardless of
    what their underlying scores were. This is also what makes a segment
    ranked modestly (say 3rd-5th) by several independent sources able to
    outrank one that is ranked #1 by only a single source -- several
    partial-but-independent votes accumulate, one strong vote does not
    automatically win.

    Deterministic and safe on empty input: an empty or absent rank list for
    a source simply contributes nothing to any key's score (the sum only
    ever runs over the sources that actually mention that key), and the
    computation itself has no randomness or dict-ordering dependence --
    equal keys always get the identical score for the identical input.
    """
    scores: dict[Any, float] = {}
    for ordered_keys in rank_lists.values():
        for i, key in enumerate(ordered_keys):
            rank = i + 1
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return scores


def _ordered_by_rank(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """Sort a table's flat hit rows ascending by raw bm25 (lower = better
    match in SQLite's bm25()), i.e. best match first."""
    return sorted(rows, key=lambda r: r["rank"])


# ---------------------------------------------------------------------------
# Per-table FTS queries. Each returns flat (non-aggregated) rows -- bm25()/
# snippet() cannot be used together with GROUP BY in the same statement
# ("unable to use function bm25 in the requested context"), so grouping by
# video and merging across tables happens in Python instead (search_videos).
#
# Each is capped at FTS_SOURCE_ROW_LIMIT best-ranked rows (BROLL-WEB-3,
# 2026-08-14). The ORDER BY names bm25(<table>) explicitly rather than the
# `rank` alias: `rank` is also a real column of every FTS5 table joined here,
# and which of the two a bare `ORDER BY rank` resolves to is not worth
# depending on. The id tie-break is what makes the cut deterministic -- bm25
# ties are common on short documents, and an arbitrary cut inside a tie would
# make the same query page differently on consecutive requests.
# ---------------------------------------------------------------------------


def _search_segments_en(
    conn: sqlite3.Connection,
    fts_query: str,
    cat_clause: str,
    cat_params: list[Any],
    flags_clause: str,
    flags_params: list[Any],
) -> list[sqlite3.Row]:
    where = "segments_fts MATCH ?" + cat_clause + flags_clause
    sql = (
        "SELECT s.id AS segment_id, s.video_id AS video_id, "
        "s.t_start, s.t_end, s.description, "
        "snippet(segments_fts, 0, ?, ?, '…', 10) AS snippet, "
        "bm25(segments_fts) AS rank "
        "FROM segments s "
        "JOIN segments_fts ON segments_fts.rowid = s.id "
        "JOIN videos v ON v.id = s.video_id "
        f"WHERE {where} "
        "ORDER BY bm25(segments_fts), s.id LIMIT ?"
    )
    # snippet()'s two '?' placeholders appear first (textually, in the
    # SELECT list) so their bind values must come first too -- sqlite3 binds
    # params in left-to-right order of '?' occurrence.
    params = [
        SNIPPET_START, SNIPPET_END, fts_query, *cat_params, *flags_params,
        FTS_SOURCE_ROW_LIMIT,
    ]
    return conn.execute(sql, params).fetchall()


def _search_segments_cjk(
    conn: sqlite3.Connection,
    fts_query: str,
    cat_clause: str,
    cat_params: list[Any],
    flags_clause: str,
    flags_params: list[Any],
) -> list[sqlite3.Row]:
    where = "segments_cjk_fts MATCH ?" + cat_clause + flags_clause
    sql = (
        "SELECT s.id AS segment_id, s.video_id AS video_id, "
        "s.t_start, s.t_end, s.description, s.onscreen_text, s.objects, "
        "bm25(segments_cjk_fts) AS rank "
        "FROM segments s "
        "JOIN segments_cjk_fts ON segments_cjk_fts.rowid = s.id "
        "JOIN videos v ON v.id = s.video_id "
        f"WHERE {where} "
        "ORDER BY bm25(segments_cjk_fts), s.id LIMIT ?"
    )
    params = [fts_query, *cat_params, *flags_params, FTS_SOURCE_ROW_LIMIT]
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        # Belt-and-suspenders on top of the trigram-length guard in callers
        # -- never let a pathological trigram query take down search.
        return []


def _search_transcript_en(
    conn: sqlite3.Connection,
    fts_query: str,
    cat_clause: str,
    cat_params: list[Any],
    flags_clause: str,
    flags_params: list[Any],
) -> list[sqlite3.Row]:
    where = "transcript_fts MATCH ?" + cat_clause + flags_clause
    sql = (
        "SELECT ts.id AS transcript_id, ts.video_id AS video_id, "
        "ts.t_start, ts.t_end, ts.text, "
        "snippet(transcript_fts, 0, ?, ?, '…', 10) AS snippet, "
        "bm25(transcript_fts) AS rank "
        "FROM transcript_segments ts "
        "JOIN transcript_fts ON transcript_fts.rowid = ts.id "
        "JOIN videos v ON v.id = ts.video_id "
        f"WHERE {where} "
        "ORDER BY bm25(transcript_fts), ts.id LIMIT ?"
    )
    params = [
        SNIPPET_START, SNIPPET_END, fts_query, *cat_params, *flags_params,
        FTS_SOURCE_ROW_LIMIT,
    ]
    return conn.execute(sql, params).fetchall()


def _search_transcript_cjk(
    conn: sqlite3.Connection,
    fts_query: str,
    cat_clause: str,
    cat_params: list[Any],
    flags_clause: str,
    flags_params: list[Any],
) -> list[sqlite3.Row]:
    where = "transcript_cjk_fts MATCH ?" + cat_clause + flags_clause
    sql = (
        "SELECT ts.id AS transcript_id, ts.video_id AS video_id, "
        "ts.t_start, ts.t_end, ts.text, "
        "bm25(transcript_cjk_fts) AS rank "
        "FROM transcript_segments ts "
        "JOIN transcript_cjk_fts ON transcript_cjk_fts.rowid = ts.id "
        "JOIN videos v ON v.id = ts.video_id "
        f"WHERE {where} "
        "ORDER BY bm25(transcript_cjk_fts), ts.id LIMIT ?"
    )
    params = [fts_query, *cat_params, *flags_params, FTS_SOURCE_ROW_LIMIT]
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def _run_fts_pass(
    conn: sqlite3.Connection,
    fts_query: str,
    raw_terms_for_snippet: list[str],
    cat_clause: str,
    cat_params: list[Any],
    flags_clause: str,
    flags_params: list[Any],
    rank_lists: dict[str, list[tuple[str, int]]],
    meta: dict[tuple[str, int], dict[str, Any]],
    *,
    source_prefix: str,
    include_cjk: bool,
    sources: str = "all",
) -> None:
    """Run `fts_query` against segments_fts + transcript_fts (and, if
    `include_cjk`, the two trigram tables) and fold the results into
    `rank_lists` (one new ranked source per table hit) and `meta` (display
    data for each (kind, id) key).

    `sources` ("all" default, or "visual"/"transcript") skips querying the
    excluded kind's tables entirely rather than querying and discarding --
    "visual" runs only segments_fts/segments_cjk_fts, "transcript" only
    transcript_fts/transcript_cjk_fts. See search_videos's docstring.

    `meta.setdefault` throughout, never overwrite: within one pass, this
    means a segment matched by both segments_fts and segments_cjk_fts keeps
    the real snippet()-highlighted text (segments_fts is queried first)
    rather than the cjk table's manually-built fallback. Across passes
    (search_videos calls this for the exact query first, then optionally for
    the fuzzy-prefix and typo-corrected retries), it means an exact hit's
    metadata is never clobbered by a later, looser fuzzy pass -- only the
    ranked-source list (used for RRF) grows, not the exact match's display.
    """
    include_segments = sources != "transcript"
    include_transcript = sources != "visual"

    if include_segments:
        en_rows = _ordered_by_rank(
            _search_segments_en(conn, fts_query, cat_clause, cat_params, flags_clause, flags_params)
        )
        if en_rows:
            rank_lists[f"{source_prefix}segments_fts"] = [
                ("segment", r["segment_id"]) for r in en_rows
            ]
            for r in en_rows:
                meta.setdefault(
                    ("segment", r["segment_id"]),
                    {
                        "video_id": r["video_id"],
                        "t_start": r["t_start"],
                        "t_end": r["t_end"],
                        "description": r["description"],
                        "snippet": r["snippet"],
                    },
                )

    if include_transcript:
        t_en_rows = _ordered_by_rank(
            _search_transcript_en(conn, fts_query, cat_clause, cat_params, flags_clause, flags_params)
        )
        if t_en_rows:
            rank_lists[f"{source_prefix}transcript_fts"] = [
                ("transcript", r["transcript_id"]) for r in t_en_rows
            ]
            for r in t_en_rows:
                meta.setdefault(
                    ("transcript", r["transcript_id"]),
                    {
                        "video_id": r["video_id"],
                        "t_start": r["t_start"],
                        "t_end": r["t_end"],
                        "description": r["text"],
                        "snippet": r["snippet"],
                    },
                )

    if not include_cjk or _all_terms_too_short_for_trigram(raw_terms_for_snippet):
        return

    if include_segments:
        cjk_rows = _ordered_by_rank(
            _search_segments_cjk(conn, fts_query, cat_clause, cat_params, flags_clause, flags_params)
        )
        if cjk_rows:
            rank_lists[f"{source_prefix}segments_cjk_fts"] = [
                ("segment", r["segment_id"]) for r in cjk_rows
            ]
            for r in cjk_rows:
                meta.setdefault(
                    ("segment", r["segment_id"]),
                    {
                        "video_id": r["video_id"],
                        "t_start": r["t_start"],
                        "t_end": r["t_end"],
                        "description": r["description"],
                        "snippet": _fallback_snippet(
                            [r["onscreen_text"], r["objects"]], raw_terms_for_snippet
                        ),
                    },
                )

    if include_transcript:
        t_cjk_rows = _ordered_by_rank(
            _search_transcript_cjk(conn, fts_query, cat_clause, cat_params, flags_clause, flags_params)
        )
        if t_cjk_rows:
            rank_lists[f"{source_prefix}transcript_cjk_fts"] = [
                ("transcript", r["transcript_id"]) for r in t_cjk_rows
            ]
            for r in t_cjk_rows:
                meta.setdefault(
                    ("transcript", r["transcript_id"]),
                    {
                        "video_id": r["video_id"],
                        "t_start": r["t_start"],
                        "t_end": r["t_end"],
                        "description": r["text"],
                        "snippet": _fallback_snippet([r["text"]], raw_terms_for_snippet),
                    },
                )


def _run_fuzzy_pass(
    conn: sqlite3.Connection,
    raw_terms: list[str],
    cat_clause: str,
    cat_params: list[Any],
    flags_clause: str,
    flags_params: list[Any],
    rank_lists: dict[str, list[tuple[str, int]]],
    meta: dict[tuple[str, int], dict[str, Any]],
    *,
    sources: str = "all",
) -> None:
    """Two additive fuzzy retries, both fed into the same RRF fusion as
    extra ranked sources -- see app/fuzzy.py's module docstring for why each
    exists and why prefix matching is restricted to the porter/unicode61
    tables.

    `sources` is threaded straight through to `_run_fts_pass` so a fuzzy
    retry never reaches into the excluded kind's tables either.
    """
    prefix_q = fuzzy.prefix_query(raw_terms)
    # BROLL-WEB-5, 2026-08-14: terms under fuzzy._MIN_TERM_LEN_FOR_PREFIX are
    # passed through unexpanded, so an all-short-term query ("surf pier",
    # 槍戰現場) comes back byte-identical to the exact pass. Re-running it costs
    # two pointless FTS queries AND registers fuzzy_prefix_segments_fts /
    # fuzzy_prefix_transcript_fts as extra RRF sources holding exactly the
    # exact pass's ranking -- doubling the porter tables' vote while the
    # trigram tables (include_cjk=False below) keep one, which demotes a CJK
    # substring hit only the trigram table could find.
    if prefix_q and prefix_q != _terms_to_fts_query(raw_terms):
        _run_fts_pass(
            conn,
            prefix_q,
            raw_terms,
            cat_clause,
            cat_params,
            flags_clause,
            flags_params,
            rank_lists,
            meta,
            source_prefix="fuzzy_prefix_",
            include_cjk=False,
            sources=sources,
        )

    # CJK compound rescue: 同志伴侶 exists in the index only as 同志 + 伴侶
    # (search_norm is jieba-segmented), so the unbroken query matches neither.
    # Additive, so the exact term still gets its trigram substring pass.
    seg_terms = segmented_cjk_terms(raw_terms)
    if seg_terms:
        _run_fts_pass(
            conn,
            _terms_to_fts_query(seg_terms),
            seg_terms,
            cat_clause,
            cat_params,
            flags_clause,
            flags_params,
            rank_lists,
            meta,
            source_prefix="cjk_seg_",
            include_cjk=True,
            sources=sources,
        )

    corrected_terms = fuzzy.correct_terms(conn, raw_terms)
    if corrected_terms:
        corrected_query = _terms_to_fts_query(corrected_terms)
        _run_fts_pass(
            conn,
            corrected_query,
            corrected_terms,
            cat_clause,
            cat_params,
            flags_clause,
            flags_params,
            rank_lists,
            meta,
            source_prefix="fuzzy_typo_",
            include_cjk=True,
            sources=sources,
        )


def _allowed_video_ids(
    conn: sqlite3.Connection,
    cat_clause: str,
    cat_params: list[Any],
    flags_clause: str,
    flags_params: list[Any],
) -> set[int] | None:
    """None means "no filter" -- distinguished from an empty set (filter
    active, nothing matches) so callers don't need a separate has-a-filter
    flag. search_videos always passes a non-empty cat_clause since 2026-08-14
    (BROWSE_PREDICATE is folded into it there, BROLL-WEB-2), so on the search
    path this now always runs; the None case remains for any other caller."""
    if not cat_clause and not flags_clause:
        return None
    rows = conn.execute(
        f"SELECT id FROM videos v WHERE 1=1{cat_clause}{flags_clause}",
        [*cat_params, *flags_params],
    ).fetchall()
    return {r[0] for r in rows}


def _fill_semantic_meta(
    conn: sqlite3.Connection,
    semantic_hits: list[dict[str, Any]],
    raw_terms: list[str],
    meta: dict[tuple[str, int], dict[str, Any]],
) -> None:
    """Semantic hits carry no display data of their own (the embeddings
    table stores only vectors + ids) -- batch-fetch t_start/t_end/text for
    whichever hits aren't already covered by a keyword pass's meta.
    """
    seg_ids = sorted(
        {
            h["source_id"]
            for h in semantic_hits
            if h["source"] == "segment" and ("segment", h["source_id"]) not in meta
        }
    )
    if seg_ids:
        placeholders = ", ".join("?" for _ in seg_ids)
        rows = conn.execute(
            "SELECT id, video_id, t_start, t_end, description, onscreen_text, objects "
            f"FROM segments WHERE id IN ({placeholders})",
            seg_ids,
        ).fetchall()
        for r in rows:
            meta.setdefault(
                ("segment", r["id"]),
                {
                    "video_id": r["video_id"],
                    "t_start": r["t_start"],
                    "t_end": r["t_end"],
                    "description": r["description"],
                    "snippet": _fallback_snippet(
                        [r["description"], r["onscreen_text"], r["objects"]], raw_terms
                    ),
                },
            )

    tr_ids = sorted(
        {
            h["source_id"]
            for h in semantic_hits
            if h["source"] == "transcript" and ("transcript", h["source_id"]) not in meta
        }
    )
    if tr_ids:
        placeholders = ", ".join("?" for _ in tr_ids)
        rows = conn.execute(
            "SELECT id, video_id, t_start, t_end, text "
            f"FROM transcript_segments WHERE id IN ({placeholders})",
            tr_ids,
        ).fetchall()
        for r in rows:
            meta.setdefault(
                ("transcript", r["id"]),
                {
                    "video_id": r["video_id"],
                    "t_start": r["t_start"],
                    "t_end": r["t_end"],
                    "description": r["text"],
                    "snippet": _fallback_snippet([r["text"]], raw_terms),
                },
            )


# Which rows browsing can reach at all, as a bare `v.`-qualified SQL fragment.
# Named rather than inlined because /api/tree has to count the SAME rows for a
# folder's badge: a root that promised `status='indexed'` only and then returned
# everything browsable read N and delivered N + the discovered/probed/proxied/
# error rows (BROLL-10, 2026-08-11). A count that disagrees with the click is
# worse than no count -- see get_tree's own docstring.
#
# 'ingesting' joined the list 2026-08-18 (docs/BROLL_INGEST_PLAN.md §2): a
# dashboard ingest mints its `videos` rows at CLAIM, hours before the media
# reaches the NAS, so the row is a name reservation and a place to put segments
# -- there is no proxy, poster or sprite behind it yet. Browsing one is the
# broken-thumbnail grid 'skipped' and 'excluded' were added to prevent, and
# search would offer a clip that cannot be played or sent to Resolve. The row
# becomes visible when ingest_batches.mark_uploaded has stat'ed the files.
BROWSE_PREDICATE = (
    "v.status != 'skipped' AND v.status != 'excluded' AND v.status != 'ingesting' "
    "AND v.duplicate_of IS NULL"
)


def _browse(
    conn: sqlite3.Connection,
    cat_clause: str,
    cat_params: list[Any],
    flags_clause: str,
    flags_params: list[Any],
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """No search text: browse mode. List videos (subject to the same
    category/flag filters) with no scoring, most recently added first.

    Excludes rows that exist in the table but are not archive footage: the
    editor proxy folders (status 'skipped'), the camera originals of a proxies
    share (status 'excluded' -- recorded for the conform manifest, never
    indexed, never copied), and confirmed byte-duplicates of another row. None
    of these is ever indexed, so none has a proxy, poster or sprite -- browsing
    them produced a grid that was mostly broken thumbnails (2,254 of 4,482 rows
    on the real archive) and a total that overstated the library by 2x.
    'excluded' joined the list 2026-08-10: the FF4 shoot's camera .MP4s sat as
    ghost no-preview cards beside their own indexed proxies.

    The search path applies the same predicate (see search_videos). It did not
    until 2026-08-14, on the since-disproved reasoning that these rows "cannot
    match anyway, having no segments and no transcript": a row marked
    `duplicate_of` keeps every segment, cue, embedding and FTS entry it had --
    pick_canonical ranks group members BY segment count, i.e. the losing copy
    is normally already indexed (BROLL-WEB-2)."""
    where = BROWSE_PREDICATE + cat_clause + flags_clause
    base_params = [*cat_params, *flags_params]

    count_sql = f"SELECT COUNT(*) FROM videos v WHERE {where}"
    total = conn.execute(count_sql, base_params).fetchone()[0]

    page_sql = (
        f"SELECT v.* FROM videos v WHERE {where} "
        "ORDER BY v.id DESC LIMIT ? OFFSET ?"
    )
    rows = conn.execute(page_sql, [*base_params, limit, offset]).fetchall()
    results = [{"video": dict(row), "score": None, "hits": []} for row in rows]
    return results, total


def _select_semantic_only_hits(
    semantic_hits: list[dict[str, Any]], keyword_video_ids: set[int]
) -> list[dict[str, Any]]:
    """In mode="hybrid": semantic is a booster, not a parallel authority (see
    module docstring). Drop any hit on a video the keyword pass already
    found -- those must not influence keyword ranking at all -- then keep
    only the top SEMANTIC_ONLY_MAX_VIDEOS *videos* (ranked by their best
    cosine score), so a query with no keyword support gets a handful of
    suggestions rather than the whole archive. Returns the (possibly
    multi-hit-per-video) subset of `semantic_hits` belonging to those videos,
    already sorted best-first -- ready to feed into a rank list.
    """
    extra_hits = [h for h in semantic_hits if h["video_id"] not in keyword_video_ids]
    if not extra_hits:
        return []

    best_by_video: dict[int, dict[str, Any]] = {}
    for h in extra_hits:
        current = best_by_video.get(h["video_id"])
        if current is None or h["score"] > current["score"]:
            best_by_video[h["video_id"]] = h
    allowed_ids = {
        h["video_id"]
        for h in sorted(
            best_by_video.values(), key=lambda h: (-h["score"], h["video_id"])
        )[:SEMANTIC_ONLY_MAX_VIDEOS]
    }
    return [h for h in extra_hits if h["video_id"] in allowed_ids]


def search_videos(
    conn: sqlite3.Connection,
    *,
    q: str,
    category: str | None,
    flags: str | None,
    limit: int,
    offset: int,
    mode: str = "hybrid",
    fuzzy: bool = True,
    sources: str = "all",
    collection: str | None = None,
    shoot: str | None = None,
    path: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Run the search and return (page_of_results, total_video_count).

    Each result is {"video": row_dict, "score": float|None, "hits": [...],
    "match": "keyword"|"semantic"}. "match" is "semantic" only for a video
    that the keyword pass never found at all (mode="hybrid") or when there
    was no keyword pass to begin with (mode="semantic") -- see module
    docstring. Each hit carries "source": "visual" (from a segment -- the
    on-screen index) or "transcript" (from transcript_segments -- the
    spoken-word index), plus its own t_start/t_end, so the UI can
    distinguish "seen" from "said".

    `mode`: "hybrid" (default) -- keyword search (the four FTS sources,
    fused via RRF) determines the result set and its order; semantic search
    may additionally surface up to SEMANTIC_ONLY_MAX_VIDEOS videos the
    keyword pass missed entirely (floored at SEMANTIC_COSINE_FLOOR),
    appended after the keyword results. "keyword" -- FTS only, no semantic
    contribution at all -- for exact matching when an editor wants it.
    "semantic" -- embeddings only (still floored at SEMANTIC_COSINE_FLOOR),
    no FTS contribution, no cap -- an explicit user choice to search by
    meaning alone. Falls back to "hybrid" for an unrecognized value rather
    than erroring.

    `fuzzy`: when True (default) and the exact keyword pass returns fewer
    than FUZZY_MIN_VIDEO_RESULTS distinct videos, retry with FTS5 prefix
    matching and rapidfuzz typo correction (app.fuzzy) as additional RRF
    sources. Has no effect in mode="semantic" (there is no keyword pass to
    retry) and never runs at all when the exact pass already found enough
    videos, so an already-working query is untouched regardless of this
    flag -- see FUZZY_MIN_VIDEO_RESULTS.

    `sources`: "all" (default) -- every source is searched, unchanged from
    the above. "visual" -- restricts to what's SEEN: only
    segments_fts/segments_cjk_fts are queried (transcript_fts/
    transcript_cjk_fts are skipped entirely, not queried-and-discarded), and
    semantic hits are restricted to embeddings.source = 'segment'. "transcript"
    -- restricts to what's SAID: only transcript_fts/transcript_cjk_fts, and
    semantic hits restricted to embeddings.source = 'transcript'. Falls back
    to "all" for an unrecognized value, same posture as `mode`. Composes with
    `mode` and `fuzzy` exactly as documented above -- e.g.
    sources="transcript", mode="semantic" only ever considers transcript
    embeddings, never segment ones. A video with no surviving hit after this
    filter is dropped from the result set entirely, never returned with an
    empty "hits" list.
    """
    if mode not in _VALID_MODES:
        mode = "hybrid"
    if sources not in _VALID_SOURCES:
        sources = "all"

    cat_clause, cat_params = build_category_clause(category)
    # Folded into the category pair rather than threaded as a third clause: both
    # are ` AND v.…` fragments appended at the same point in every one of the
    # dozen-odd query builders below, so merging them here keeps the parameter
    # order correct everywhere without touching any of those signatures.
    coll_clause, coll_params = build_collection_clause(collection, conn)
    shoot_clause, shoot_params = build_shoot_clause(shoot)
    path_clause, path_params = build_path_clause(path)
    cat_clause += coll_clause + shoot_clause + path_clause
    cat_params = [*cat_params, *coll_params, *shoot_params, *path_params]
    flags_clause, flags_params = build_flags_exclude_clause(flags)

    raw_terms = _extract_terms(q)
    if not raw_terms:
        return _browse(conn, cat_clause, cat_params, flags_clause, flags_params, limit, offset)

    # BROLL-WEB-2, 2026-08-14: everything past this point is the search path,
    # which filtered on category/collection/shoot/path/flags and nothing else
    # -- so a row the browse path hides came back as its own card. That matters
    # most for `duplicate_of`: marking a duplicate writes ONLY that column, so
    # the losing copy keeps its segments, cues, embeddings and FTS entries and
    # matches everything the kept copy does. It has no archive_path, so its
    # /media/proxy 404s (black player) and "Send to Resolve" falls back to the
    # ingest share no companion has a mount for -- the exact 2026-08-12 failure
    # R12 exists to prevent -- and the sidebar count disagrees with the click.
    # Appended to cat_clause rather than threaded as another parameter because
    # every FTS builder and _allowed_video_ids already join `videos v` and
    # splice this fragment in at the same point. _browse is unaffected: it
    # returned above, and applies BROWSE_PREDICATE itself.
    cat_clause += " AND " + BROWSE_PREDICATE

    rank_lists: dict[str, list[tuple[str, int]]] = {}
    meta: dict[tuple[str, int], dict[str, Any]] = {}
    keyword_video_ids: set[int] = set()

    if mode in ("hybrid", "keyword"):
        fts_query = _terms_to_fts_query(raw_terms)
        _run_fts_pass(
            conn,
            fts_query,
            raw_terms,
            cat_clause,
            cat_params,
            flags_clause,
            flags_params,
            rank_lists,
            meta,
            source_prefix="",
            include_cjk=True,
            sources=sources,
        )

        exact_video_ids = {m["video_id"] for m in meta.values()}
        if fuzzy and len(exact_video_ids) < FUZZY_MIN_VIDEO_RESULTS:
            _run_fuzzy_pass(
                conn,
                raw_terms,
                cat_clause,
                cat_params,
                flags_clause,
                flags_params,
                rank_lists,
                meta,
                sources=sources,
            )

        keyword_video_ids = {m["video_id"] for m in meta.values()}

    if mode in ("hybrid", "semantic"):
        allowed_video_ids = _allowed_video_ids(
            conn, cat_clause, cat_params, flags_clause, flags_params
        )
        embedding_source_filter = _SOURCES_TO_EMBEDDING_SOURCE[sources]
        semantic_hits = semantic.get_semantic_search().search(
            conn, q, allowed_video_ids=allowed_video_ids, source_filter=embedding_source_filter
        )
        # Floor applies in BOTH modes -- see SEMANTIC_COSINE_FLOOR. Nearest-
        # neighbour retrieval always returns *something*; a hit below the
        # floor is discarded rather than treated as a match of any kind.
        semantic_hits = [h for h in semantic_hits if h["score"] >= SEMANTIC_COSINE_FLOOR]

        if mode == "semantic":
            # Explicit user choice to search by meaning alone: no keyword
            # pass to be "extra" relative to, so no cap either -- and no CJK
            # gate either. That gate lived one branch up until 2026-08-14,
            # where `keyword_video_ids` is empty BY CONSTRUCTION in this mode
            # (the keyword branch never ran), so it fired for every
            # predominantly-CJK query and /api/search answered
            # {"results": [], "total": 0} -- the archive's entire
            # Chinese-language corpus unreachable in the one mode that exists
            # to search it by meaning, while the same query in hybrid worked
            # (BROLL-WEB-1). The leak it guards is specific to hybrid: there,
            # "keyword found nothing" is evidence the corpus has nothing, and
            # a multilingual embedding will still confidently rank any Chinese
            # string near any Chinese content. Here the editor asked for
            # meaning-only retrieval; the floor is the only gate that applies.
            if semantic_hits:
                rank_lists["semantic"] = [
                    (h["source"], h["source_id"]) for h in semantic_hits
                ]
                _fill_semantic_meta(conn, semantic_hits, raw_terms, meta)
        else:
            # A CJK query the keyword pass could not match at all: drop the
            # semantic contribution entirely. Its score reflects script
            # identity, not meaning — see is_cjk_query for the measurements.
            # Only applies when there is NO keyword corroboration; a CJK query
            # that did match still gets semantic hits fused normally.
            if semantic_hits and not keyword_video_ids and is_cjk_query(q):
                semantic_hits = []

            # mode == "hybrid": semantic only ever ADDS videos keyword
            # missed, capped -- see _select_semantic_only_hits. A hit on a
            # video keyword already found is dropped entirely, not fused in,
            # so it can never re-rank or otherwise touch a keyword result.
            semantic_only_hits = _select_semantic_only_hits(semantic_hits, keyword_video_ids)
            if semantic_only_hits:
                rank_lists["semantic"] = [
                    (h["source"], h["source_id"]) for h in semantic_only_hits
                ]
                _fill_semantic_meta(conn, semantic_only_hits, raw_terms, meta)

    if not rank_lists:
        return [], 0

    fused = reciprocal_rank_fusion(rank_lists, k=RRF_K)
    if not fused:
        return [], 0

    hits_by_video: dict[int, list[tuple[float, tuple[str, int]]]] = {}
    for key, score in fused.items():
        m = meta.get(key)
        if m is None:
            continue  # defensive: never crash on a rank-list key with no metadata
        hits_by_video.setdefault(m["video_id"], []).append((score, key))

    best_score_by_video = {
        vid: max(score for score, _ in items) for vid, items in hits_by_video.items()
    }
    total = len(best_score_by_video)

    # Keyword-matched videos always sort ahead of semantic-only ones,
    # regardless of numeric score -- "match" the field's group, not the raw
    # RRF value, decides ordering, so a semantic-only video's score (drawn
    # from a differently-sized rank list) can never leapfrog a confident
    # keyword result. Within each group, best score first.
    def _sort_key(vid: int) -> tuple[int, float, int]:
        group = 0 if vid in keyword_video_ids else 1
        return (group, -best_score_by_video[vid], vid)

    ordered_video_ids = sorted(best_score_by_video, key=_sort_key)
    page_video_ids = ordered_video_ids[offset : offset + limit]

    if not page_video_ids:
        return [], total

    placeholders = ", ".join("?" for _ in page_video_ids)
    video_rows = conn.execute(
        f"SELECT * FROM videos WHERE id IN ({placeholders})", page_video_ids
    ).fetchall()
    video_by_id = {row["id"]: dict(row) for row in video_rows}

    results: list[dict[str, Any]] = []
    for vid in page_video_ids:
        items = sorted(hits_by_video[vid], key=lambda pair: (-pair[0], pair[1][0], pair[1][1]))
        # Best-fused first, then cut -- see MAX_HITS_PER_VIDEO (BROLL-WEB-3).
        items = items[:MAX_HITS_PER_VIDEO]
        hits = []
        for score, key in items:
            kind, obj_id = key
            m = meta[key]
            hits.append(
                {
                    "segment_id": obj_id if kind == "segment" else None,
                    "transcript_id": obj_id if kind == "transcript" else None,
                    "t_start": m["t_start"],
                    "t_end": m["t_end"],
                    "description": m["description"],
                    "snippet": m["snippet"],
                    "source": "visual" if kind == "segment" else "transcript",
                }
            )
        results.append(
            {
                "video": video_by_id[vid],
                "score": best_score_by_video[vid],
                "hits": hits,
                "match": "keyword" if vid in keyword_video_ids else "semantic",
            }
        )
    return results, total


def count_in_scope(
    conn: sqlite3.Connection,
    *,
    category: str | None = None,
    flags: str | None = None,
    collection: str | None = None,
    shoot: str | None = None,
    path: str | None = None,
) -> int:
    """How many clips a search under these filters even looked at.

    The honest half of "nothing matched": an empty grid is the same picture
    whether the archive holds four clips or forty thousand, and whether the
    folder filter narrowed it to eleven (BROLL-9, 2026-09-04). Composed from
    the same clause builders search_videos uses, in the same order, so the
    number cannot describe a different scope than the one that was searched.

    Called only when a query returned nothing, so it costs a COUNT on the
    empty-result path and nothing on every other search.
    """
    cat_clause, cat_params = build_category_clause(category)
    coll_clause, coll_params = build_collection_clause(collection, conn)
    shoot_clause, shoot_params = build_shoot_clause(shoot)
    path_clause, path_params = build_path_clause(path)
    flags_clause, flags_params = build_flags_exclude_clause(flags)
    where = (BROWSE_PREDICATE + cat_clause + coll_clause + shoot_clause
             + path_clause + flags_clause)
    params = [*cat_params, *coll_params, *shoot_params, *path_params, *flags_params]
    return conn.execute(
        f"SELECT COUNT(*) FROM videos v WHERE {where}", params).fetchone()[0]
