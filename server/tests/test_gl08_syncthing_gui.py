"""GL-08 / CR-363 (2026-10-07; bug-server-3): the TrueNAS install secures the
Syncthing GUI itself instead of printing "run this by hand"."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import secure_syncthing_gui  # noqa: E402
from backends.truenas import TrueNASBackend  # noqa: E402,F401  (the class under test lives here)


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = ""

    def json(self):
        return self._body


def fake_api(state, put_status=200):
    def api(method, gui_url, path, api_key, json_body=None, dry_run=False, params=None):
        assert path == "/rest/config/gui"
        if method == "GET":
            return Resp(200, dict(state))
        state.update(json_body)
        state["_put"] = True
        return Resp(put_status)
    return api


def test_an_open_gui_gets_a_login(monkeypatch, tmp_path):
    monkeypatch.setenv("CCSYNC_SYNCTHING_CREDS", str(tmp_path / "creds.txt"))
    state = {"address": "0.0.0.0:8384", "user": "", "password": "", "insecureAdminAccess": True}
    monkeypatch.setattr(secure_syncthing_gui, "syncthing_api", fake_api(state))
    ok, message, password = secure_syncthing_gui.secure_gui("http://nas:8384", "key")
    assert ok and password
    assert state["user"] == secure_syncthing_gui.DEFAULT_GUI_USER
    assert state["insecureAdminAccess"] is False
    assert "creds.txt" in message
    assert (tmp_path / "creds.txt").read_text().count(password) == 1


def test_a_gui_that_already_has_a_login_is_left_alone(monkeypatch):
    state = {"address": "x", "user": "studio", "password": "$2a$hash", "insecureAdminAccess": False}
    monkeypatch.setattr(secure_syncthing_gui, "syncthing_api", fake_api(state))
    ok, message, password = secure_syncthing_gui.secure_gui("http://nas:8384", "key")
    assert ok and password == "" and "_put" not in state


def test_a_refused_change_is_a_message_not_an_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("CCSYNC_SYNCTHING_CREDS", str(tmp_path / "c.txt"))
    state = {"address": "x", "user": "", "password": ""}
    monkeypatch.setattr(secure_syncthing_gui, "syncthing_api", fake_api(state, put_status=500))
    ok, message, password = secure_syncthing_gui.secure_gui("http://nas:8384", "key")
    assert not ok and "500" in message and password == ""
    assert not (tmp_path / "c.txt").exists()


def test_the_installer_only_secures_when_it_has_a_key_and_an_address(monkeypatch):
    monkeypatch.delenv("SYNCTHING_API_KEY", raising=False)
    monkeypatch.delenv("SYNCTHING_GUI_URL", raising=False)
    assert TrueNASBackend._secure_gui_now(8384) is False      # nothing to go on: says so, does not guess
    monkeypatch.setenv("SYNCTHING_API_KEY", "k")
    monkeypatch.setenv("SYNCTHING_GUI_URL", "http://nas:8384")
    monkeypatch.setattr(secure_syncthing_gui, "secure_gui",
                        lambda url, key: (True, "done", "pw"))
    assert TrueNASBackend._secure_gui_now(8384) is True
    monkeypatch.setattr(secure_syncthing_gui, "secure_gui",
                        lambda url, key: (_ for _ in ()).throw(RuntimeError("down")))
    assert TrueNASBackend._secure_gui_now(8384) is False


def test_an_existing_login_keeps_its_password_when_only_insecure_access_is_on(monkeypatch):
    """Overseer fix (2026-10-07): do not replace an admin's own password."""
    state = {"address": "x", "user": "studio", "password": "$2a$mine", "insecureAdminAccess": True}
    monkeypatch.setattr(secure_syncthing_gui, "syncthing_api", fake_api(state))
    ok, message, password = secure_syncthing_gui.secure_gui("http://nas:8384", "key")
    assert ok and password == ""
    assert state["password"] == "$2a$mine" and state["insecureAdminAccess"] is False


def test_the_password_is_recorded_before_the_engine_holds_it(monkeypatch, tmp_path):
    """Round 2: a failed credentials write must leave the GUI untouched, and
    must return a message rather than raise."""
    monkeypatch.setenv("CCSYNC_SYNCTHING_CREDS", str(tmp_path / "creds.txt"))
    state = {"address": "x", "user": "", "password": "", "insecureAdminAccess": True}
    monkeypatch.setattr(secure_syncthing_gui, "syncthing_api", fake_api(state))

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(secure_syncthing_gui, "write_credentials", boom)
    ok, message, password = secure_syncthing_gui.secure_gui("http://nas:8384", "key")
    assert not ok and "NOT changed" in message and password == ""
    assert "_put" not in state                      # the PUT never happened


def test_the_credentials_file_is_written_before_the_put(monkeypatch, tmp_path):
    creds = tmp_path / "creds.txt"
    monkeypatch.setenv("CCSYNC_SYNCTHING_CREDS", str(creds))
    seen = {}
    state = {"address": "x", "user": "", "password": ""}
    inner = fake_api(state)

    def api(method, *a, **k):
        if method == "PUT":
            seen["file_existed"] = creds.exists()
        return inner(method, *a, **k)
    monkeypatch.setattr(secure_syncthing_gui, "syncthing_api", api)
    ok, _m, _p = secure_syncthing_gui.secure_gui("http://nas:8384", "key")
    assert ok and seen["file_existed"] is True
