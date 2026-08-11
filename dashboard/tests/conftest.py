from __future__ import annotations

import os
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


@pytest.fixture(scope="session", autouse=True)
def _music_data_root_off_the_real_library(tmp_path_factory):
    """Keep the music mount's data root out of the checkout, for every test.

    mount_music runs on every create_app (it takes no flag; see music.py), and
    its dev fallback puts this repo's music/web on sys.path -- so with numpy in
    the venv the mount would open the REAL music/web/data/music.db and apply
    schema.sql to it. Harmless (the schema is IF NOT EXISTS) but it writes a WAL
    beside a 20 MB index that no test has any business touching. musicweb.config
    reads DATA_ROOT at IMPORT time, so this has to be set before the first
    create_app, which is why it is session-scoped and autouse.
    """
    root = tmp_path_factory.mktemp("musicdata")
    os.environ["DATA_ROOT"] = str(root)
    os.environ.setdefault("MUSIC_ROOT", str(root / "library"))
    yield root


@pytest.fixture(scope="session", autouse=True)
def _ytdl_data_root_off_the_checkout(tmp_path_factory):
    """The same guard for the ytdl mount, which is one degree more dangerous.

    mount_ytdl runs on every create_app (no flag, see ytdl.py) and its dev
    fallback puts this repo's ytdl/web on sys.path -- so on a machine with
    yt-dlp installed, every create_app in this suite would open the REAL
    ytdl.db AND start the pipeline worker THREAD, which downloads video into
    the Projects tree. YTDL_WORKER=0 is the sub-app's own test guard for that
    thread; the data root is redirected for the same reason music's is.
    ytdlweb.config reads both at IMPORT time, so this has to be set before the
    first create_app: session-scoped and autouse.
    """
    root = tmp_path_factory.mktemp("ytdldata")
    os.environ["YTDL_DATA_ROOT"] = str(root)
    os.environ.setdefault("YTDL_PROJECTS_ROOT", str(root / "projects"))
    os.environ.setdefault("YTDL_WORKER", "0")
    yield root
