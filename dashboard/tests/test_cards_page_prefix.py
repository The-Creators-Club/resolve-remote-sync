"""The page's URLs must be DOCUMENT-RELATIVE, or the mount serves a dead page.

docs/TIMELINE-CARDS-INTO-CCSYNC.md §7e (2026-08-30). `broll/web` and
`music/web` each carry a `test_mounted_prefix.py` pinning this, because a
root-relative `/api|/audio|/static` breaks under a prefix -- the page loads,
polls `/api/state` on the DASHBOARD, gets a 404 or a login page, and says
"connecting..." for ever.

THIS FILE IS THE DASHBOARD'S OWN COPY OF THAT CHECK, run against the REAL
Timeline Cards checkout when one is reachable, and skipped otherwise (nothing
in this repo ships that tree; §7e is the spec for the builder over there, and
this is what tells us the day it stops being true).

WHAT THE AUDIT FOUND, 2026-08-30, and it is the good surprise of phase 3: the
page is ALREADY relative. Every fetch in `page/01-state.js`..`10-look.js` is
`fetch('api/...')`, every media src is `'audio?mp='` / `'video?mp='`, and
`cards.html` links `manifest.webmanifest` with no leading slash. The plan's
§3.2 problem 2 ("a real, mechanical, boring day of work") does not exist. The
count this file asserts is therefore ZERO, and the one absolute URL left in
the whole page is in `page.py`'s manifest -- `"scope": "/"` -- which is the
only xfail below.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from ccsync_dashboard import cards

# Where the checkout is, in order: what a caller set, then the one this
# machine has. NEVER a fallback that reaches the network or writes anything --
# the tree is read, and only read.
FORK_CHECKOUT = Path(r"E:\Projects\_worktrees\Editing-fork\Resolve\MulticamPipeline")

# The page is a document at `/cards/`, so an absolute URL is one that starts
# with a slash and names a route this server serves. Quoted or backticked,
# which is every way the page writes one.
ABSOLUTE_URL = re.compile(
    r"""["'`(]\s*(/(?:api|audio|video|peaks|agent|icon\.svg|manifest\.webmanifest)"""
    r"""[A-Za-z0-9_./?=&-]*)""")

PAGE_FILES = ("cards.html", "cards.css",
              "01-state.js", "02-markers.js", "03-lane.js", "04-lane-keys.js",
              "05-keys.js", "06-trim.js", "07-conform.js", "08-places.js",
              "09-edit.js", "10-look.js")


def real_checkout() -> Path | None:
    raw = (os.environ.get("CARDS_REAL_SRC") or os.environ.get("CARDS_SRC") or "").strip()
    root = Path(raw) if raw else FORK_CHECKOUT
    return root if (root / "multicam_pipeline" / "cards" / "page").is_dir() else None


@pytest.fixture
def page_dir():
    root = real_checkout()
    if root is None:
        pytest.skip("no Timeline Cards checkout here (set CARDS_REAL_SRC)")
    return root / "multicam_pipeline" / "cards" / "page"


def test_the_page_files_are_all_there(page_dir):
    """If this fails the audit below is auditing nothing -- a renamed slice
    would make every count zero and every assertion pass."""
    missing = [name for name in PAGE_FILES if not (page_dir / name).is_file()]
    assert missing == [], f"page/ has changed shape: {missing} are gone"


def test_no_page_file_carries_an_absolute_url(page_dir):
    """§7e's audit, file by file. Zero, today and every day after."""
    found: dict[str, list[str]] = {}
    for name in PAGE_FILES:
        text = (page_dir / name).read_text(encoding="utf-8")
        hits = [m.group(1) for m in ABSOLUTE_URL.finditer(text)]
        if hits:
            found[name] = hits
    assert found == {}, (
        "these URLs are root-relative and would resolve against the DASHBOARD "
        f"root under /cards/: {found}. Make them document-relative "
        "(`api/state`, not `/api/state`) -- docs/TIMELINE-CARDS-INTO-CCSYNC.md §7e")


def test_the_manifest_link_is_relative(page_dir):
    html = (page_dir / "cards.html").read_text(encoding="utf-8")
    assert 'href="manifest.webmanifest"' in html


@pytest.mark.xfail(strict=False, reason=(
    "§7e, the ONE absolute URL left: page.render_manifest() says "
    '`"scope": "/"`, which claims this whole origin for the installed app '
    "instead of the page under /cards/. One character on the Timeline Cards "
    "side ('.'), and this flips green."))
def test_the_manifest_scope_is_relative():
    root = real_checkout()
    if root is None:
        pytest.skip("no Timeline Cards checkout here (set CARDS_REAL_SRC)")
    text = (root / "multicam_pipeline" / "cards" / "page.py").read_text(encoding="utf-8")
    assert '"scope": "/"' not in text


def test_our_media_map_parser_agrees_with_the_real_one():
    """`cards.parse_media_map` is a COPY (see its docstring). This is the
    diff, taken against the real function rather than against a memory of it.

    In a SUBPROCESS on purpose: `multicam_pipeline` is a top-level package and
    test_cards_mount.py puts a fake one of those in this interpreter, so
    importing the real one here would get whichever ran first.
    """
    root = real_checkout()
    if root is None:
        pytest.skip("no Timeline Cards checkout here (set CARDS_REAL_SRC)")
    cases = ["P:\\=/media/;X:\\=/vault/", "P:/=/media", "", "nonsense",
             "P:=//host/share", " A = /b ; C=/d/ "]
    script = (
        "import json,sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from multicam_pipeline.cards.fleet_jobs import split_pairs\n"
        "print(json.dumps([split_pairs(c, seps=';') for c in json.loads(sys.argv[2])]))\n"
    )
    import json

    proc = subprocess.run(
        [sys.executable, "-c", script, str(root), json.dumps(cases)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-800:]
    theirs = [[tuple(pair) for pair in answer] for answer in json.loads(proc.stdout)]
    ours = [cards.parse_media_map(c) for c in cases]
    assert ours == theirs
