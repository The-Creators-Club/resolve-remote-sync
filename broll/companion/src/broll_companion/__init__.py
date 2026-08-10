"""BRoll Companion — local agent that inserts b-roll clips into DaVinci Resolve.

Listens on 127.0.0.1:8899 for requests from the broll-platform web UI. See
SPEC.md at the repo root, section "Companion API contract", for the binding
behaviour this package implements.
"""

from .config import VERSION

__all__ = ["VERSION"]
