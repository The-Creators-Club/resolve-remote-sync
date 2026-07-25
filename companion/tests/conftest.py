"""Shared fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

COMPANION_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _isolate_ccsync_home(tmp_path, monkeypatch):
    """Point config.CONFIG_DIR at a per-test temp dir so no test ever reads
    (or writes) the REAL ~/.ccsync. Without this, tests constructing a
    CompanionApp load whatever identity.json the developer's own live
    companion has -- e.g. a signed-in role="base" identity flips
    _sync_enabled at construction and test_role fails only on that machine,
    only while signed in. (Observed 2026-07-25.)"""
    from ccsync_companion import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".ccsync")


def _find_rclone() -> str | None:
    """Look for a runnable rclone: PATH first, then the test-only portable
    binary at companion/.tools/rclone.exe (see README.md's "Tests" section —
    this binary is NOT installed system-wide and isn't on PATH; it's only
    used by these tests so the filter-rule integration tests can actually
    invoke rclone rather than being permanently skipped).
    """
    found = shutil.which("rclone")
    if found:
        return found
    local = COMPANION_ROOT / ".tools" / "rclone.exe"
    if local.exists():
        return str(local)
    return None


@pytest.fixture(scope="session")
def rclone_binary() -> str:
    path = _find_rclone()
    if path is None:
        pytest.skip("rclone not found on PATH or at companion/.tools/rclone.exe")
    return path


def make_timeline_item(
    file_path: str,
    clip_name: str | None = None,
    track_type: str = "video",
    track_index: int = 1,
    item_index: int = 0,
    media_pool_item=None,
) -> dict:
    """Build a fake resolve_bridge.get_timeline_items()-style item dict."""

    class _FakeMediaPoolItem:
        def __init__(self, path: str, name: str):
            self._path = path
            self._name = name
            self.replace_calls: list[str] = []
            self.replace_result = True

        def GetClipProperty(self):
            return {"File Path": self._path}

        def GetName(self):
            return self._name

        def ReplaceClip(self, new_path: str):
            self.replace_calls.append(new_path)
            return self.replace_result

    mpi = media_pool_item if media_pool_item is not None else _FakeMediaPoolItem(
        file_path, clip_name or Path(file_path).name
    )
    return {
        "file_path": file_path,
        "media_pool_item": mpi,
        "clip_name": clip_name or Path(file_path).name,
        "track_type": track_type,
        "track_index": track_index,
        "item_index": item_index,
    }
