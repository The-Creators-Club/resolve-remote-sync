"""The dashboard's TrueNAS client over JSON-RPC (CR-365, GL-11/GL-46, 2026-10-07).

TrueNAS 26 has no /api/v2.0, so TrueNASClient defaults to the websocket at
/api/current. These tests drive the real client against an in-process peer
(fake_truenas_rpc.py) and pin: the account flows still work end to end, the
expected-422 on password_disabled still reads as expected, REST remains the
fallback for a NAS with no /api/current, and a pinned transport never falls back.
"""
import pytest

from ccsync_dashboard.nas import truenas as tn
from ccsync_dashboard.nas.truenas import TrueNASClient, TrueNASError

from fake_truenas_rpc import Fail, FakeRpcNas


class State:
    def __init__(self):
        self.users = [{"id": 5, "username": "ed", "uid": 3001, "groups": [10],
                       "group": {"id": 10}, "home": "/mnt/tank/homes/ed",
                       "sshpubkey": "ssh-ed25519 AAAA", "smb": True},
                      {"id": 1, "username": "root", "uid": 0, "groups": [], "group": {"id": 1}}]
        self.groups = [{"id": 10, "group": "editors", "gid": 3000}]
        self.updates = []

    def _delete(self, p):
        self.users = [u for u in self.users if u["id"] != p[0]]
        return p[0]

    def handlers(self):
        def uq(p):
            fl = p[0] if p else []
            return [u for u in self.users if all(u.get(f[0]) == f[2] for f in fl)]

        def gq(p):
            fl = p[0] if p else []
            return [g for g in self.groups if all(g.get(f[0]) == f[2] for f in fl)]

        def uu(p):
            self.updates.append(p)
            if p[1].get("password_disabled"):
                raise Fail(errname="EINVAL", message="Validation",
                           reason="SMB users cannot have password disabled")
            return p[0]
        return {
            "user.query": uq, "group.query": gq, "user.update": uu,
            "user.get_instance": lambda p: next(u for u in self.users if u["id"] == p[0]),
            "user.delete": self._delete,
            "filesystem.setperm": lambda p: 42,
            "core.get_jobs": lambda p: [{"id": 42, "state": "SUCCESS", "error": None}],
            "system.info": lambda p: {"version": "TrueNAS-26.04.0", "hostname": "nas26"},
        }


@pytest.fixture(autouse=True)
def _fresh_transport_state():
    """Pool and REST-only memory are process state (CR-365 overseer 3/7)."""
    tn.truenas_rpc.reset_pool()
    tn.truenas_rpc._REST_ONLY.clear()
    tn.truenas_rpc._GOOD_PATH.clear()
    yield
    tn.truenas_rpc.reset_pool()
    tn.truenas_rpc._REST_ONLY.clear()
    tn.truenas_rpc._GOOD_PATH.clear()


@pytest.fixture
def peer():
    st = State()
    n = FakeRpcNas(st.handlers())
    n.state = st
    yield n
    n.close()


def _client(peer, **kw):
    kw.setdefault("verify_ssl", False)
    return TrueNASClient("127.0.0.1", "admin", "pw", ws_url=peer.url,
                         homes_parent="/mnt/tank/homes", api_key="", **kw)


def test_ping_and_find_run_over_jsonrpc_with_no_rest(peer, monkeypatch):
    def no_rest(*a, **k):
        raise AssertionError("REST used although /api/current answers")
    monkeypatch.setattr("requests.Session.request", no_rest)
    c = _client(peer)
    c.ping()
    assert c.find_user("ed")["id"] == 5
    assert c.is_editor("ed") is True
    assert c.is_editor("root") is False


def test_set_password_and_delete_use_the_mapped_methods(peer):
    c = _client(peer)
    c.set_known_password("ed", "hunter2hunter2")
    assert peer.state.updates[-1] == [5, {"password": "hunter2hunter2"}]
    out = c.delete_editor("ed")
    assert out["deleted"] is True
    assert ("user.delete", [5, {"delete_group": False}]) in peer.calls


def test_update_flow_waits_on_the_setperm_job_and_tolerates_the_smb_422(peer, monkeypatch):
    monkeypatch.setattr(tn.time, "sleep", lambda s: None)
    out = _client(peer).create_or_update_editor("ed", "ssh-ed25519 AAAA")
    assert out["created"] is False
    assert out["home_ok"] is True
    # password_disabled -> 422 mentioning SMB is the expected answer, no warning
    assert not [w for w in out["warnings"] if "password_disabled" in w]


def test_system_info_names_an_unsupported_release(peer):
    info = _client(peer).system_info()
    assert info["version"] == "TrueNAS-26.04.0"
    assert info["support_note"] == ""
    peer.handlers["system.info"] = lambda p: {"version": "TrueNAS-SCALE-24.10.1", "hostname": "old"}
    assert "predates 25.04" in _client(peer).system_info()["support_note"]


def test_a_nas_without_the_endpoint_falls_back_to_rest_once(monkeypatch):
    dead = FakeRpcNas(endpoint=False)
    urls = []

    class R:
        status_code = 200
        text = "[]"
        headers = {}

        def json(self):
            return []

    c = TrueNASClient("127.0.0.1", "admin", "pw", ws_url=dead.url, api_key="")
    monkeypatch.setattr(c.session, "request", lambda m, url, **k: (urls.append(url), R())[1])
    try:
        c.ping()
        c.ping()
    finally:
        dead.close()
    assert urls == ["https://127.0.0.1/api/v2.0/group"] * 2


def test_a_pinned_jsonrpc_transport_never_falls_back(monkeypatch):
    dead = FakeRpcNas(endpoint=False)
    c = TrueNASClient("127.0.0.1", "admin", "pw", ws_url=dead.url, transport="jsonrpc", api_key="")
    try:
        with pytest.raises(TrueNASError, match="no JSON-RPC API"):
            c.ping()
    finally:
        dead.close()


def test_a_wrong_credential_is_a_truenas_error_not_a_traceback(peer):
    c = TrueNASClient("127.0.0.1", "admin", "bad", ws_url=peer.url, api_key="")
    with pytest.raises(TrueNASError, match="refused"):
        c.ping()


def test_base_url_clients_stay_on_rest(monkeypatch):
    """The tests' plain-http fake (and any operator override) is a REST address."""
    c = TrueNASClient("h", "u", "p", base_url="http://127.0.0.1:9/api/v2.0", api_key="")

    def no_ws(*a, **k):
        raise AssertionError("websocket attempted for a base_url client")
    monkeypatch.setattr(tn.truenas_rpc, "rest_call", no_ws)
    with pytest.raises(TrueNASError):
        c.ping()      # discard port: a connection error, from REST
