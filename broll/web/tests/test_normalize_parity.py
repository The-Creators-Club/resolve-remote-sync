"""The two vendored files, and the one hand-lifted pair, must not drift.

`app/normalize.py` is `broll_index/normalize.py` byte for byte below its header
marker; `app/identity.py` is `ytdlweb/identity.py` the same way (2026-08-18,
docs/BROLL_INGEST_PLAN.md §3.1). This is the b-roll suite's half of a gate that
also runs in `server/tests/test_cross_component.py` and in `tools/release.ps1`
-- three copies of one comparison, deliberately, because the release gate only
runs on Windows at release time and a suite that skips silently is worse than
no suite.

WHY THE DRIFT MATTERS, in one line each:

  - normalize: `search_norm` is what makes a two-character CJK term findable.
    A blob built by a different tokenisation than the one the query path
    normalises with does not match badly, it matches NOTHING -- so a clip is in
    the archive, indexed, and unreachable by the words on its own screen.
  - identity: it decides WHICH editor a companion is. Two verifiers that
    disagree about a token shape are two answers to that question, and one of
    them is wrong.
"""
from __future__ import annotations

from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = WEB_DIR.parents[1]

VENDOR_MARKER = b"# --- vendored content below, byte-identical ---"

PAIRS = {
    "normalize.py": (WEB_DIR / "app" / "normalize.py",
                     REPO_ROOT / "broll" / "indexer" / "broll_index" / "normalize.py"),
    "identity.py": (WEB_DIR / "app" / "identity.py",
                    REPO_ROOT / "ytdl" / "web" / "ytdlweb" / "identity.py"),
}


def _vendored_body(path: Path) -> bytes:
    """The bytes below the header marker line.

    Bytes, not text: this is the byte comparison the contract is written in, so
    nothing may decode or newline-translate on the way in. An absent or
    repeated marker fails here rather than degrading to "no header found,
    compare the whole file" -- the same fail-safe rule release.ps1 follows.
    """
    raw = path.read_bytes()
    assert raw.count(VENDOR_MARKER) == 1, (
        f"{path} must carry {VENDOR_MARKER.decode()!r} exactly once, as the last "
        f"line of its header (found {raw.count(VENDOR_MARKER)})")
    rest = raw.split(VENDOR_MARKER, 1)[1]
    if rest.startswith(b"\r\n"):
        return rest[2:]
    return rest[1:] if rest.startswith(b"\n") else rest


@pytest.mark.parametrize("name", sorted(PAIRS))
def test_the_vendored_copy_is_byte_identical_to_its_source(name):
    """Fix a drift by editing the SOURCE and re-copying it in below the marker
    -- never by editing broll/web's copy, which is what the header says and
    what the release gate prints."""
    vendored, source = PAIRS[name]
    if not source.exists():
        pytest.skip(f"{source} is not in this checkout")
    assert vendored.exists(), f"missing vendored copy: {vendored}"
    body = _vendored_body(vendored)
    assert body == source.read_bytes(), (
        f"{vendored} has drifted from {source}: {len(body)} bytes below the marker "
        f"vs {len(source.read_bytes())} in the source. Edit the source, then "
        f"re-copy it below the marker line.")


def test_the_vendored_normalize_still_behaves_like_the_indexers():
    """The bytes are equal, so this is really a smoke test of the IMPORT --
    that `app.normalize` loads on its own, with none of broll_index's tree
    around it. It is vendored precisely because the container has no anthropic,
    xxhash or pyyaml, and an accidental `from broll_index import ...` in the
    source would make the copy unusable in the one place it exists to run."""
    from app import normalize

    assert normalize.searchable_blob("") == ""
    # Pure-ASCII in, unchanged out -- English text is never re-tokenised.
    assert normalize.searchable_blob("harbour at dawn") == "harbour at dawn"


def test_the_search_norm_field_set_matches_the_indexers():
    """`segment_search_text` is the indexer's `pipeline._segment_search_text`.

    Compared as SOURCE TEXT, not by importing broll_index.pipeline (which pulls
    in the whole indexer). Crude on purpose: what has to hold is that both read
    the same five fields in the same order, and a field added to one and not
    the other is exactly the drift that leaves half an archive un-findable.
    """
    from app.ingest_batches import segment_search_text

    fields = ["description", "objects", "setting", "onscreen_text", "onscreen_text_en"]
    seg = dict.fromkeys(fields, "")
    for i, f in enumerate(fields):
        seg[f] = f"w{i}"
    assert segment_search_text(seg) == "w0 w1 w2 w3 w4"
    # Empty fields drop out entirely rather than leaving double spaces, which
    # is what the indexer's `" ".join(p for p in parts if p)` does.
    assert segment_search_text({"description": "a", "objects": "", "setting": "b"}) == "a b"

    pipeline = (REPO_ROOT / "broll" / "indexer" / "broll_index" / "pipeline.py")
    if not pipeline.exists():
        pytest.skip("the indexer is not in this checkout")
    source = pipeline.read_text(encoding="utf-8")
    body = source.split("def _segment_search_text", 1)[1].split("\ndef ", 1)[0]
    for f in fields:
        assert f'seg.get("{f}")' in body, (
            f"the indexer's _segment_search_text no longer reads {f!r}; "
            "app.ingest_batches.segment_search_text has drifted from it")
