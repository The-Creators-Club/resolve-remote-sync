"""Test setup: make `steps` (this package) and `ccsync_companion` (the
companion app's package, imported for identity.py/config.py reuse -- see
steps.py's module docstring) importable without requiring either package to
be pip-installed."""

from __future__ import annotations

import sys
from pathlib import Path

ONBOARDING_DIR = Path(__file__).resolve().parent.parent
COMPANION_SRC = ONBOARDING_DIR.parent / "companion" / "src"

for path in (str(ONBOARDING_DIR), str(COMPANION_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)
