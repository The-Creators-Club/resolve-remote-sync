from __future__ import annotations

import sys
from pathlib import Path

# Ensure the in-repo package is importable even if the venv install is stale
# (editable install already handles this, but keep tests robust either way).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
