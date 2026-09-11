"""WHICH DOCUMENTS LEAVE THIS REPOSITORY (dash-mounts-ui-1 / server-tools-2).

2026-09-04 widened /help from one customer explainer to "every markdown file
the repository carries", and all three shipping routes were widened with it:
the image's `COPY docs`, the OTA bundle's `TREES`, and bind mode's
`_stage_docs_tree`. The bug hunt of 2026-09-11 found the other half of that
change: `help.resolve_document` allow-lists the SHAPE of a path and never the
AUDIENCE, and the route sits behind the login gate only. So every editor on
every customer's fleet could read KNOWN_BUGS.md, CLAUDE.md, SECRETS.md,
PRODUCT_REPO.md, every plan doc and every bug-hunt report - documents that
name this studio's editors, their machines and its infrastructure addresses,
which is CLAUDE.md's "no customer's name in code" broken by the shipping
change rather than by the code.

This module is the ONE list. Four places read it and none of them may hold a
second copy:
  - `help.resolve_document` / `help.document_groups` (what may be READ),
  - `tools/build_dashboard_bundle.py` (the OTA bundle),
  - `server/install_dashboard_app.py` (bind mode), by path, because server/
    deliberately does not import the dashboard package,
  - `dashboard/deploy/Dockerfile` + `.dockerignore` (the image), which cannot
    import anything: they restate the list in COPY lines, and
    `dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py` fails the
    moment those lines and this tuple disagree.

ADDING A DOCUMENT HERE PUBLISHES IT TO EVERY CUSTOMER. The test is not "is it
useful", it is "would I hand this to a stranger who bought the product":
no incident ledger, no plan, no runbook that names a host, no sweep report.
Everything else still renders in the same viewer on a DEV CHECKOUT, where the
docs tree is the repository's own, and only for an admin: that is what keeps
the owner's 2026-09-04 ask (read every document in this viewer) working on
the base rig without shipping it to a customer's image.
"""
from __future__ import annotations

import posixpath

# Documents under `docs/`, as posix paths relative to it. These are the
# customer-facing set: the explainer an editor is pointed at, the editor's own
# setup guide, and the legal paperwork the first-run wizard makes an admin
# accept (that one is REQUIRED - see SHIPPED_DOCS in install_dashboard_app).
PUBLISHED_DOCS: tuple[str, ...] = (
    "HOW_IT_WORKS.md",
    "EDITOR_SETUP.md",
)

# Whole directories under `docs/`, markdown only. `legal` is the EULA, the
# privacy note, the telemetry note, the YouTube feature notice and the
# generated third-party notices: all five are things a customer is entitled
# to read, and the wizard links two of them.
PUBLISHED_TREES: tuple[str, ...] = (
    "legal",
)

# The repository's top-level documents (README / SPEC / KNOWN_BUGS /
# CLAUDE.md) travelled under `_root/` until 2026-09-11. NONE of them ship
# now: KNOWN_BUGS.md and CLAUDE.md are the two worst documents in the tree to
# hand a customer. The `_root/` shape stays in help.py because a dev checkout
# still has them beside `docs/` and an admin there may read them.
ROOT_DOCS: tuple[str, ...] = ()

# The subset without which a dashboard is BROKEN, not merely thinner: the
# guide /help opens on, and the legal tree the first-run wizard reads the EULA
# from. A build that cannot find these is refused (build_dashboard_bundle) and
# a deploy that cannot find them says so (install_dashboard_app.SHIPPED_DOCS);
# everything else on the list is best effort, because a missing document is
# not a reason to refuse to ship a dashboard.
REQUIRED_DOCS: tuple[str, ...] = ("HOW_IT_WORKS.md",)
REQUIRED_TREES: tuple[str, ...] = ("legal",)

SUFFIX = ".md"


def is_published(rel: str) -> bool:
    """Is `rel` (a browser path under the docs root) customer-facing?

    Fails CLOSED: anything this function does not recognise is not published.
    """
    rel = (rel or "").strip().replace("\\", "/").lstrip("/")
    if not rel or not rel.lower().endswith(SUFFIX):
        return False
    rel = posixpath.normpath(rel)
    if rel.startswith("..") or rel.startswith("/"):
        return False
    if rel in PUBLISHED_DOCS:
        return True
    head = rel.split("/", 1)[0]
    return "/" in rel and head in PUBLISHED_TREES


def published_sources(required_only: bool = False) -> tuple[tuple[str, ...],
                                                           tuple[str, ...]]:
    """(files, trees) as paths relative to the REPO root, for the shippers.

    Returned rather than exposed as constants so the three routes cannot
    drift into three different prefixes.
    """
    docs = REQUIRED_DOCS if required_only else PUBLISHED_DOCS
    trees = REQUIRED_TREES if required_only else PUBLISHED_TREES
    return (tuple(f"docs/{name}" for name in docs),
            tuple(f"docs/{name}" for name in trees))
