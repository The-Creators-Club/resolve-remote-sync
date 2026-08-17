from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from broll_index.storage.sqlite_backend import SqliteBackend

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema.sql"


@pytest.fixture(scope="session")
def schema_path() -> Path:
    assert SCHEMA_PATH.exists(), f"schema.sql not found at {SCHEMA_PATH}"
    return SCHEMA_PATH


@pytest.fixture
def sqlite_storage(tmp_path, schema_path):
    backend = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    yield backend
    backend.close()


@pytest.fixture(scope="session")
def schema_path_v4(schema_path) -> Path:
    """Fresh-install DDL with hybrid search (search_norm + embeddings) present.

    This is now simply schema.sql: the repo-root schema was brought to (at least) v4
    once the hybrid-search migration landed, so fresh installs and migrated databases
    end at the same place (verified column-for-column, both paths). The fixture is kept
    as a distinct name so tests that specifically need hybrid-search support say so, and
    so it has somewhere to hang if the versions ever diverge again. Asserted against
    migrate.LATEST_VERSION rather than a literal so a future schema bump can't silently
    make this fixture's own guard stale — see test_storage_sqlite.py's
    test_schema_applied_once for the same pattern.
    """
    from broll_index.migrate import LATEST_VERSION

    conn = sqlite3.connect(":memory:")
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION
    # fts5 virtual tables are easy to break silently; confirm they resolve.
    conn.execute("SELECT * FROM segments_fts LIMIT 0")
    conn.execute("SELECT * FROM embeddings LIMIT 0")
    conn.close()
    return schema_path


@pytest.fixture
def sqlite_storage_v4(tmp_path, schema_path_v4):
    backend = SqliteBackend(tmp_path / "broll_v4.db", schema_path=schema_path_v4)
    yield backend
    backend.close()


@pytest.fixture(scope="session")
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture(scope="session")
def require_ffmpeg() -> None:
    """A real ffmpeg/ffprobe on PATH, or a skip -- unless the caller insists.

    Mirrors companion/tests/conftest.py's `rclone_binary` fixture (CLAUDE.md,
    2026-08-17 CI run 32041222871): a runner with no ffmpeg on PATH must not
    silently turn "these prove real proxies/scenes/10-bit-forcing decode
    correctly" into a green suite that ran nothing. Set
    CCSYNC_REQUIRE_FFMPEG=1 to turn the skip into a hard failure -- pytest
    exits 0 when tests skip, so that is the only way a missing binary reads
    as red rather than green. `ci.yml`'s linux job installs ffmpeg with apt
    before this suite runs precisely so the skip path is normally never
    taken there; the env var is the belt-and-braces half, for anyone running
    these tests on a machine that has not.
    """
    if shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None:
        return
    message = "ffmpeg/ffprobe not found on PATH"
    if os.environ.get("CCSYNC_REQUIRE_FFMPEG") == "1":
        pytest.fail(
            f"{message}\n\nCCSYNC_REQUIRE_FFMPEG=1 is set, so this is a failure "
            "rather than a skip -- these tests invoke a real ffmpeg/ffprobe to prove "
            "proxy/sprite/scene-detection behaviour against real codecs, and a "
            "release must not be cut without them."
        )
    pytest.skip(message)


@pytest.fixture(scope="session")
def tiny_clip(tmp_path_factory, require_ffmpeg) -> Path:
    """A 2s, 320x240 testsrc clip generated with ffmpeg lavfi — used for real ffprobe/ffmpeg tests."""
    out_dir = tmp_path_factory.mktemp("media")
    out_path = out_dir / "tiny_clip.mp4"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    return out_path
