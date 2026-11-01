"""tools/ suite fixtures.

GL-25b (CR-371, 2026-10-07): the signers now stamp tools/release_floor.json
into a companion/onboard record instead of 0.0.0, and refuse a floorless one.
The real launch floor (0.9.75) is above the made-up versions most tests sign,
so every test runs against a floor file of its own, low enough never to matter.
The tests that are ABOUT the floor point the variable somewhere else.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _low_release_floor(tmp_path_factory, monkeypatch):
    path = tmp_path_factory.mktemp("floor") / "release_floor.json"
    path.write_text(json.dumps({
        "companion": {"windows": "0.0.1", "macos": "0.0.1"},
        "onboard": {"windows": "0.0.1", "macos": "0.0.1"},
    }), encoding="utf-8")
    monkeypatch.setenv("CCSYNC_RELEASE_FLOOR_FILE", str(path))


@pytest.fixture(autouse=True)
def _no_live_ci_gate(monkeypatch):
    """CR-371 round 2: publish_feed asks GitHub whether CI vouches for the
    commit before a --github-upload --make-current. The older tests drive that
    path with made-up commits and a fake runner; the gate has its own tests
    (TestOverseerRound2 calls _ci_gate_impl directly)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import publish_feed
    monkeypatch.setattr(publish_feed, "ci_gate_refusal", lambda args: "")
