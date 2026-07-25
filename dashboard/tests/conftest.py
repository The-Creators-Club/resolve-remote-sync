from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ccsync_dashboard import db as dbmod  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    connection = dbmod.connect(tmp_path / "test.db")
    dbmod.migrate(connection)
    yield connection
    connection.close()
