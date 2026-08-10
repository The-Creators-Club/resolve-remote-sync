"""Push share -> source-root facts to the web app.

The web app cannot derive them. `share`, its filesystem root, and whether it
archives originals or proxies all live in this side's config.queue.yaml, and
web/app/config.py says explicitly that it does not read that file and may not
even be on the same machine.

They matter at the far end of the workflow: a remote editor cuts against a
proxy, and at final export the TRUE original has to be relinked from wherever it
now lives — most likely a backup external drive. Without these facts the B-roll
origin manifest can record a share name and a relative path with nothing to
resolve them against.

Pushing beats sharing the file: config.queue.yaml edits flow on the next run
with nothing to keep in sync by hand.
"""

from __future__ import annotations

import logging

from .config import Config
from .storage.base import Storage

logger = logging.getLogger(__name__)


def share_payload(cfg: Config) -> list[dict]:
    """The config's shares, in the shape POST /api/ingest/shares expects."""
    return [
        {
            "share": name,
            "root": s.root,
            "source": getattr(s, "source", "originals"),
            "description": getattr(s, "description", "") or "",
            "indexed": bool(getattr(s, "index", True)),
        }
        for name, s in sorted(cfg.shares.items())
    ]


def push_shares(cfg: Config, storage: Storage) -> int:
    """Best-effort. Returns how many shares were pushed, 0 if unsupported.

    NEVER fatal: this is bookkeeping for a conform that happens weeks later, and
    failing a whole indexing run over it would trade a large amount of real work
    for a small amount of metadata. A storage backend with no push (plain
    SQLite, where the indexer already writes the table directly) is not an
    error either — hence the getattr rather than an abstract method that every
    backend would have to stub.
    """
    payload = share_payload(cfg)
    if not payload:
        return 0
    push = getattr(storage, "push_shares", None)
    if push is None:
        return 0
    try:
        push(payload)
    except Exception as e:  # noqa: BLE001 — see docstring
        logger.warning("could not push share roots (%s); the origin manifest may "
                       "not be able to resolve originals at conform time", e)
        return 0
    return len(payload)
