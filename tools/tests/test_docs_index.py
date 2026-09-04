"""The docs index promises to be complete, so something has to check it.

SYS-12 (sweep 2026-09-03): `docs/README.md` says "Every document in `docs/`,
one line each" and was missing ten files, two of which CLAUDE.md names as
required reading before touching their code paths. The promise is
machine-checkable, and until this test existed nothing checked it -- the
index was written once, on 2026-08-17, and every document added since was
invisible to a reader who trusted it.

Run:  cd tools; python -m pytest tests -q       (any interpreter with pytest)
"""

from __future__ import annotations

from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"
INDEX = DOCS / "README.md"

# README.md IS the index; it does not list itself.
EXEMPT = {"README.md"}


def _index_text() -> str:
    return INDEX.read_text(encoding="utf-8")


def _documents() -> list[str]:
    """Every doc the index promises to carry, as a path relative to docs/."""
    found = [p.name for p in sorted(DOCS.glob("*.md"))]
    found += [f"legal/{p.name}" for p in sorted((DOCS / "legal").glob("*.md"))]
    return [name for name in found if name not in EXEMPT]


def test_every_doc_is_listed():
    text = _index_text()
    missing = [name for name in _documents() if f"({name})" not in text]
    assert not missing, (
        "docs/README.md says it lists every document in docs/ and is missing: "
        + ", ".join(missing)
    )


def test_index_links_resolve():
    """A row pointing at a file that is gone is the same defect backwards."""
    import re

    broken = []
    for target in re.findall(r"\]\(([^)]+)\)", _index_text()):
        if target.startswith(("http://", "https://", "#")):
            continue
        if not (INDEX.parent / target).exists():
            broken.append(target)
    assert not broken, "docs/README.md links nothing at: " + ", ".join(broken)
