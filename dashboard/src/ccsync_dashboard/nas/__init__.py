"""The runtime NAS seam: identity/provisioning against whatever NAS this
site runs on (SYNOLOGY_PORT_PLAN.md WP1, 2026-08-17).

`base` holds the backend-neutral surface (the `NasBackend` Protocol,
`NasError`, the username/key shape checks and the group name); `truenas` and
`synology` implement it; `factory.make_nas_client` picks one from
`DASH_NAS_KIND`. Nothing outside this package may import a concrete backend
by name -- that is the whole point of the seam.
"""
from __future__ import annotations

from .base import (
    EDITORS_GROUP,
    NasBackend,
    NasError,
    SSH_KEY_PREFIXES,
    USERNAME_RE,
    capability,
    is_valid_username,
    looks_like_ssh_pubkey,
)
from .factory import NAS_KINDS, make_nas_client, nas_configured
from .synology import SynologyClient
from .truenas import TrueNASClient, TrueNASError

__all__ = [
    "EDITORS_GROUP",
    "NAS_KINDS",
    "NasBackend",
    "NasError",
    "SSH_KEY_PREFIXES",
    "USERNAME_RE",
    "SynologyClient",
    "TrueNASClient",
    "TrueNASError",
    "capability",
    "is_valid_username",
    "looks_like_ssh_pubkey",
    "make_nas_client",
    "nas_configured",
]
