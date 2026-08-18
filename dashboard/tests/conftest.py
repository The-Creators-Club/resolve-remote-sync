from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# THE dev/test flag (settings.Settings.dev_insecure, 2026-08-17). Set at import
# time, before any test module builds a Settings, because Settings.__post_init__
# reads it: without it every `Settings(session_secret="test-secret")` in this
# suite would be refused at create_app by the secret-strength floor, and every
# hand-minted session cookie would be rejected as a session this server never
# issued. It relaxes exactly those two rules plus the CSRF token (see
# app.csrf_gate); a deployment that sets it gets a WARNING on every boot.
os.environ["DASH_DEV_INSECURE"] = "1"

# The AI providers' keys (ai_providers.py, 2026-08-18). Removed at import
# time, for the same reason ytdl/web's conftest blanks DASH_REPORT_TOKEN: the
# base rig genuinely exports ANTHROPIC_API_KEY, "the environment always wins"
# is a real rule of this module, and a suite that resolved a live provider on
# one machine and nothing on CI would hide the property that matters most --
# a dashboard with no key configured must report NO provider, not somebody's
# shell's. Tests that are about the env path set it themselves (monkeypatch).
for _ai_key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
    os.environ.pop(_ai_key, None)

from ccsync_dashboard import db as dbmod  # noqa: E402


class NasCase:
    """One backend the admin-user call sites must work through.

    `kwargs` go into Settings; `provisions` says whether this backend can
    actually create accounts (a backend that cannot must answer with a banner
    or a 502 -- never a traceback, and never a silent success). `seed_editor`
    exists because "an editor already on the NAS" is spelled differently in
    each fake's state, and no test should have to know which.
    """

    def __init__(self, kind: str, kwargs: dict, fake=None, provisions: bool = True,
                 error_fragment: str = "", seed=None):
        self.kind = kind
        self.kwargs = kwargs
        self.fake = fake
        self.provisions = provisions
        self.error_fragment = error_fragment
        self._seed = seed

    def seed_editor(self, username: str = "jsmith", uid: int = 3010) -> None:
        """Put an existing editor account into the fake NAS."""
        if self._seed is not None:
            self._seed(username, uid)

    def __repr__(self) -> str:                      # readable -k selection
        return f"<NasCase {self.kind}>"


@pytest.fixture(params=("truenas", "synology"))
def nas_case(request, monkeypatch):
    """Parametrises a test over every NAS backend the dashboard can be
    configured with (SYNOLOGY_PORT_PLAN.md WP1/WP2). Kept in conftest so
    test_nas_backend.py and any future admin-user test share one definition of
    "every backend"; a third backend is a third param here.

    Both cases drive the REAL client against an HTTP fake of the NAS's API,
    reached through Settings.nas_base_url -- so the factory, the settings and
    the client are all in the path, not just the Protocol.
    """
    if request.param == "truenas":
        from fake_truenas import FakeTrueNAS

        fake = FakeTrueNAS().start()

        def seed(username: str, uid: int) -> None:
            if not any(g["group"] == "editors" for g in fake.state["groups"]):
                fake.state["groups"].append({"id": 111, "group": "editors", "gid": 3001})
            fake.state["users"].append({
                "id": len(fake.state["users"]) + 5, "uid": uid, "username": username,
                "full_name": username, "home": f"/h/{username}", "group": {"id": 111},
                "groups": [111], "sshpubkey": "ssh-ed25519 AAAA", "smb": True,
                "locked": False, "password_disabled": False,
            })

        try:
            yield NasCase(
                "truenas",
                {"nas_kind": "truenas", "nas_user": "truenas_admin", "nas_pw": "fake-pw",
                 "nas_base_url": fake.base_url},
                fake=fake, seed=seed,
            )
        finally:
            fake.stop()
        return

    from fake_synology import FakeDSM
    from ccsync_dashboard.nas.synology import SynologyClient

    fake = FakeDSM().start()
    # The SSH half has no Settings knob to point at a fake (it is paramiko, not
    # a URL), so the client's one SSH seam is redirected for the whole case.
    monkeypatch.setattr(SynologyClient, "_paramiko_run",
                        lambda self, command, stdin_text: fake.ssh(command, stdin_text))

    def seed(username: str, uid: int) -> None:
        if not any(g["name"] == "editors" for g in fake.state["groups"]):
            fake.state["groups"].append({"name": "editors", "gid": 65536})
        fake.state["users"].append({"name": username, "uid": uid, "description": username,
                                    "email": "", "expired": "normal"})
        fake.state["members"].setdefault("editors", []).append(username)
        fake.state["members"].setdefault("users", []).append(username)
        fake.state["authorized_keys"][username] = "ssh-ed25519 AAAA"

    try:
        yield NasCase(
            "synology",
            {"nas_kind": "synology", "nas_host": "dsm.example", "nas_user": "ccsync",
             "nas_pw": "fake-pw", "nas_base_url": fake.base_url},
            fake=fake, seed=seed,
        )
    finally:
        fake.stop()


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
