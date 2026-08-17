"""Import-compatibility shim. The code moved to ccsync_dashboard.nas.

2026-08-17 (SYNOLOGY_PORT_PLAN.md WP1): the TrueNAS client became one
implementation of `nas.base.NasBackend` and now lives in `nas/truenas.py`;
the backend-neutral pieces (EDITORS_GROUP, is_valid_username,
looks_like_ssh_pubkey) live in `nas/base.py`. This module re-exports both so
that anything still importing `ccsync_dashboard.truenas_client` -- a running
container mid-deploy, an out-of-tree script, a branch another agent has open
-- keeps working.

KEPT FOR ONE RELEASE. New code imports from `ccsync_dashboard.nas` and never
names a concrete backend; delete this file once nothing does.
"""
from __future__ import annotations

from .nas.base import (  # noqa: F401
    EDITORS_GROUP,
    NasError,
    SSH_KEY_PREFIXES,
    USERNAME_RE,
    is_valid_username,
    looks_like_ssh_pubkey,
)
from .nas.truenas import (  # noqa: F401
    HOME_MODE,
    HOME_PARENT,
    MIN_EDITOR_UID,
    TrueNASClient,
    TrueNASError,
    _verify_setting,
    ok,
)

__all__ = [
    "EDITORS_GROUP",
    "HOME_MODE",
    "HOME_PARENT",
    "MIN_EDITOR_UID",
    "NasError",
    "SSH_KEY_PREFIXES",
    "USERNAME_RE",
    "TrueNASClient",
    "TrueNASError",
    "is_valid_username",
    "looks_like_ssh_pubkey",
    "ok",
]
