"""What a clip is CALLED in the archive tree, decided server-side.

Lifted from the indexer's `build_archive.py` (`safe_name`, `claim_key`,
`claim_name`) on 2026-08-18 for dashboard ingest
(docs/BROLL_INGEST_PLAN.md §3.1). Not vendored under a byte-identical marker
like `normalize.py`/`identity.py`: `build_archive` is a script that imports
`broll_index.config`, `broll_index.inplace_fixes` and PyYAML, none of which the
dashboard container has, and only three functions out of ~600 lines are
wanted. `tests/test_archive_names.py` pins them against the indexer's copy
where a checkout is present, and re-states the rules where it is not.

WHY THE SERVER ALLOCATES THE NAME AT ALL, rather than the companion that is
about to write the file: two editors dropping the same camera card into the
same shoot on two machines would both pick `A001_C003.mp4`, and the second
upload would land on top of the first -- a file already recorded on another
row, already served by the search UI and already cut into someone's timeline.
That is BROLL-IDX-5 (2026-08-14) with a second machine instead of a second
run. The database is the only place that can see both claims, so the database
decides, once, inside the claim transaction.

The `_2` rule and its "claimed names, never what is on disk" discipline come
straight from build_archive and the comments below are its lessons, not
restated theory.
"""
from __future__ import annotations

import re

# Exactly the characters Windows forbids in a filename, and nothing else: the
# archive is full of Chinese titles and they must survive intact. Replacing
# more than this is how a shoot folder becomes unreadable to the person who
# named it.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Windows MAX_PATH is 260. Three clips failed the indexer's first archive build
# outright with WinError 123 because their CJK news headlines ran past it once
# the archive root and category folders were prepended. Cap the stem well short
# of it.
MAX_STEM = 90


def safe_name(name: str, cap: int = MAX_STEM) -> str:
    """A filename Windows will accept, without mangling CJK.

    The archive is full of Chinese titles and they must survive: only the
    characters Windows actually forbids are replaced. Over-long names are
    truncated rather than dropped -- a shortened title still identifies the
    clip, and the DB holds the full one.
    """
    cleaned = _UNSAFE.sub("_", name).rstrip(". ")
    if len(cleaned) > cap:
        cleaned = cleaned[:cap].rstrip(". ")
    return cleaned or "untitled"


def claim_key(folder: str, stem: str) -> str:
    """The name two clips contend for: a folder and a stem, extension aside.

    Claimed per stem rather than per full path so a clip's top slot and the
    preview under `Proxy/` always resolve to the SAME name. Keying on the whole
    path let them diverge whenever the two files had different extensions --
    `<folder>/name.mov` (base name free) beside `<folder>/Proxy/name_2.mp4`
    (taken) -- which is how a newcomer could still land on top of an already
    published clip's original (BROLL-IDX-5, 2026-08-14).
    """
    return f"{folder}/{stem}".lower()


def claim_name(folder: str, stem: str, taken: set[str]) -> str:
    """This clip's name in `folder`, suffixed `_2`.. only if it must be.

    Collisions are settled against claimed names, never against what is on
    disk. That distinction is the whole point: a file already at the target
    path is almost always this clip's own copy from an earlier run, and
    treating it as a collision renamed all 2,093 clips to `_2` on the indexer's
    second archive build.

    `taken` is MUTATED -- the caller seeds it with every name already published
    in that folder (and with what the rest of this batch has claimed) and the
    allocator adds to it as it goes, so two items of one drop cannot both take
    the same slot.

    build_archive's `published=` argument is deliberately absent here: it
    exists for a clip that ALREADY holds a name and must keep it across
    re-runs, and an ingest item is by definition new to the archive. If a
    re-claim of the same batch ever needs it, the item's stored
    `archive_stem` is the answer, not a re-derivation.
    """
    if claim_key(folder, stem) not in taken:
        taken.add(claim_key(folder, stem))
        return stem
    n = 2
    while True:
        cand = f"{stem}_{n}"
        if claim_key(folder, cand) not in taken:
            taken.add(claim_key(folder, cand))
            return cand
        n += 1


def split_stem(name: str) -> tuple[str, str]:
    """('A001_C003', '.MP4') -- the last dot only, and never a leading one.

    `os.path.splitext` on its own calls `.hidden` an extension, which would
    hand `claim_name` an empty stem and produce a file literally called
    `_2.hidden`. A camera never writes such a name, but a drop is whatever the
    editor's disk holds.
    """
    dot = name.rfind(".")
    if dot <= 0:
        return name, ""
    return name[:dot], name[dot:]
