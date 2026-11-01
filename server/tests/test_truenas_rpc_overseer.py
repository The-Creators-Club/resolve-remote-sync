"""CR-365 overseer round (2026-10-07): the defects the first JSON-RPC build had.

Each test pins one: the key's own account at login, a login failure that is an
auth error and nothing rawer, one login per wait loop, the snapshot route, the
fallbacks to REST, the versioned endpoint, and the certificate pin.
"""
import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import common  # noqa: E402
import truenas_rpc as rpc  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "fake_truenas_rpc", HERE.parent.parent / "dashboard" / "tests" / "fake_truenas_rpc.py")
fake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fake)


@pytest.fixture(autouse=True)
def _fresh_transport_state():
    rpc.reset_pool()
    rpc._REST_ONLY.clear()
    rpc._GOOD_PATH.clear()
    yield
    rpc.reset_pool()
    rpc._REST_ONLY.clear()
    rpc._GOOD_PATH.clear()


@pytest.fixture
def nas():
    n = fake.FakeRpcNas({
        "user.query": lambda p: [],
        "core.get_jobs": lambda p: [{"id": p[0][0][2], "state": "RUNNING", "error": None}],
    })
    yield n
    n.close()


@pytest.fixture
def env(monkeypatch, nas):
    monkeypatch.setenv("TRUENAS_HOST", "127.0.0.1")
    monkeypatch.setenv("TRUENAS_USER", "admin")
    monkeypatch.setenv("TRUENAS_PW", "pw")
    monkeypatch.delenv("TRUENAS_API_KEY", raising=False)
    monkeypatch.delenv("TRUENAS_API_KEY_USER", raising=False)
    monkeypatch.delenv("TRUENAS_API_TRANSPORT", raising=False)
    monkeypatch.delenv("DASH_NAS_API_TRANSPORT", raising=False)
    monkeypatch.setenv("TRUENAS_WS_URL", nas.url)
    monkeypatch.setenv("TRUENAS_VERIFY_SSL", "1")


def _call(n, method, path, **kw):
    kw.setdefault("user", "admin")
    kw.setdefault("password", "pw")
    return rpc.rest_call("127.0.0.1", method, path, url=n.url, timeout=5, **kw)


# ---- 1: the key logs in as ITS account

def test_the_key_logs_in_as_its_own_account_with_no_legacy_method():
    """compose carries the ADMIN as DASH_NAS_USER, the key was minted for
    ccsync-svc, and a 26-like NAS has no auth.login_with_api_key."""
    n = fake.FakeRpcNas({"user.query": lambda p: []}, key_user="ccsync-svc",
                        no_legacy_key=True)
    try:
        resp = _call(n, "GET", "/user", api_key="1-key", user="truenas_admin",
                     password="", api_key_user="ccsync-svc")
        assert resp.status_code == 200
        assert [m for m, _ in n.logins] == ["auth.login_ex"]
        assert n.logins[0][1][0]["username"] == "ccsync-svc"
    finally:
        n.close()


def test_a_key_with_no_account_name_says_so_instead_of_blaming_revocation():
    n = fake.FakeRpcNas({"user.query": lambda p: []}, key_user="ccsync-svc",
                        no_legacy_key=True)
    try:
        with pytest.raises(rpc.RpcAuthError) as ei:
            _call(n, "GET", "/user", api_key="1-key", user="truenas_admin", password="")
        msg = str(ei.value)
        assert "truenas_admin" in msg and "TRUENAS_API_KEY_USER" in msg
    finally:
        n.close()


def test_truenas_api_sends_the_key_user_from_the_environment(env, monkeypatch):
    n = fake.FakeRpcNas({"user.query": lambda p: []}, key_user="ccsync-svc",
                        no_legacy_key=True)
    monkeypatch.setenv("TRUENAS_WS_URL", n.url)
    monkeypatch.setenv("TRUENAS_API_KEY", "1-key")
    monkeypatch.setenv("TRUENAS_API_KEY_USER", " ccsync-svc ")
    assert common.truenas_api_key_user() == "ccsync-svc"
    try:
        assert common.ok(common.truenas_api("GET", "/user"))
        assert n.logins[0][1][0]["username"] == "ccsync-svc"
    finally:
        n.close()


# ---- 2: a login failure is an auth error, never a raw RpcError

@pytest.mark.parametrize("with_key", [False, True])
def test_a_login_rpc_error_is_an_auth_error_never_a_raw_rpc_error(with_key):
    busy = fake.Fail(code=-32001, message="Rate Limit Exceeded", errname="EBUSY")
    n = fake.FakeRpcNas({}, login_error=busy)
    try:
        kw = {"api_key": "1-key", "api_key_user": "admin", "password": ""} if with_key else {}
        with pytest.raises(rpc.RpcAuthError, match="Rate Limit Exceeded"):
            _call(n, "GET", "/user", **kw)
    finally:
        n.close()


def test_truenas_api_turns_a_login_rate_limit_into_a_connection_error(env, monkeypatch):
    import requests
    busy = fake.Fail(code=-32001, message="Rate Limit Exceeded", errname="EBUSY")
    n = fake.FakeRpcNas({}, login_error=busy)
    monkeypatch.setenv("TRUENAS_WS_URL", n.url)
    try:
        with pytest.raises(requests.exceptions.ConnectionError, match="Rate Limit"):
            common.truenas_api("GET", "/user")
    finally:
        n.close()


# ---- 3: one login, reused

def test_a_wait_loop_logs_in_once(env, nas, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    common.wait_for_job(99, timeout=0.3, poll=0)
    assert len(nas.calls) > 3
    assert len(nas.logins) == 1 and nas.connections == 1


def test_a_connection_the_nas_closed_is_replaced_for_a_read(nas):
    assert _call(nas, "GET", "/user").status_code == 200
    nas.drop_connections()
    assert _call(nas, "GET", "/user").status_code == 200
    assert nas.connections == 2


def test_a_write_is_never_replayed_after_the_request_left(nas):
    """The NAS took the request and the reply was lost: replaying a POST on a
    fresh login could run it twice."""
    assert _call(nas, "GET", "/user").status_code == 200
    runs = []

    def create(p):
        runs.append(p)
        nas.drop_connections()
        return 1
    nas.handlers["user.create"] = create
    with pytest.raises(rpc.RpcTransportError):
        _call(nas, "POST", "/user", json_body={"username": "x"})
    assert len(runs) == 1


def test_an_idle_session_is_dropped_before_the_nas_can_close_it(nas, monkeypatch):
    assert _call(nas, "GET", "/user").status_code == 200
    real = rpc.time.monotonic
    monkeypatch.setattr(rpc.time, "monotonic", lambda: real() + rpc.IDLE_LIMIT + 1)
    assert _call(nas, "GET", "/user").status_code == 200
    assert nas.connections == 2


# ---- 4: the snapshot route and the REST fallbacks

def test_the_snapshot_route_is_mapped():
    assert rpc.route("POST", "/zfs/snapshot", None, {"dataset": "d", "name": "n"}) == (
        "pool.snapshot.create", [{"dataset": "d", "name": "n"}])


def test_the_snapshot_route_falls_back_to_the_pre_25_method_name(nas):
    nas.handlers["zfs.snapshot.create"] = lambda p: {"name": p[0]["dataset"] + "@" + p[0]["name"]}
    resp = _call(nas, "POST", "/zfs/snapshot", json_body={"dataset": "tank/apps", "name": "s1"})
    assert resp.status_code == 200 and resp.json()["name"] == "tank/apps@s1"
    assert [m for m, _ in nas.calls] == ["pool.snapshot.create", "zfs.snapshot.create"]


def test_an_unmapped_route_falls_back_to_rest_where_rest_still_answers(env, monkeypatch):
    import requests
    seen = []

    class R:
        status_code = 200

    monkeypatch.setattr(requests, "request", lambda m, url, **k: (seen.append(url), R())[1])
    assert common.truenas_api("POST", "/nope", json_body={}).status_code == 200
    assert seen == ["https://127.0.0.1/api/v2.0/nope"]


def test_a_pinned_jsonrpc_transport_still_refuses_an_unmapped_route(env, monkeypatch):
    import requests
    monkeypatch.setenv("TRUENAS_API_TRANSPORT", "jsonrpc")
    with pytest.raises(requests.exceptions.ConnectionError, match="/nope"):
        common.truenas_api("POST", "/nope", json_body={})


# ---- 7: handshake answers, REST-only memory

@pytest.mark.parametrize("status", [200, 400, 405, 301])
def test_any_non_upgrade_http_answer_means_no_jsonrpc_here(status):
    n = fake.FakeRpcNas(endpoint=False, endpoint_status=status)
    try:
        with pytest.raises(rpc.RpcUnavailable):
            _call(n, "GET", "/user")
    finally:
        n.close()


def test_a_busy_nas_at_the_handshake_is_a_transport_error_not_unavailable():
    n = fake.FakeRpcNas(endpoint=False, endpoint_status=503)
    try:
        with pytest.raises(rpc.RpcTransportError):
            _call(n, "GET", "/user")
    finally:
        n.close()


def test_the_rest_only_memory_expires(monkeypatch):
    rpc.mark_rest_only("h")
    assert rpc.rest_only("h")
    real = rpc.time.monotonic
    monkeypatch.setattr(rpc.time, "monotonic", lambda: real() + rpc.REST_ONLY_TTL + 1)
    assert not rpc.rest_only("h")


def test_a_rest_404_after_fallback_clears_the_memory(env, monkeypatch):
    import requests
    dead = fake.FakeRpcNas(endpoint=False)
    monkeypatch.setenv("TRUENAS_WS_URL", dead.url)

    class R:
        status_code = 404

    monkeypatch.setattr(requests, "request", lambda m, url, **k: R())
    try:
        assert common.truenas_api("GET", "/user").status_code == 404
    finally:
        dead.close()
    assert not rpc.rest_only("127.0.0.1")


# ---- 8: the versioned endpoint

def test_no_version_pin_by_default_the_nas_own_current_schema_is_used(monkeypatch):
    """CR-365 round 2: a pin to 25.04.2 would move a 25.10 NAS onto models
    its payloads never ran on. Only /api/current is asked for."""
    monkeypatch.delenv("DASH_NAS_API_PATH", raising=False)
    monkeypatch.delenv("TRUENAS_API_PATH", raising=False)
    assert rpc.api_paths() == ("/api/current",)
    n = fake.FakeRpcNas({"user.query": lambda p: []}, paths={"/api/current"})
    monkeypatch.setattr(rpc, "ws_url_for", lambda host, path=rpc.API_PATH:
                        f"ws://127.0.0.1:{n.port}{path}")
    try:
        assert rpc.rest_call("127.0.0.1", "GET", "/user", user="admin", password="pw",
                             timeout=5).status_code == 200
        assert n.request_paths == ["/api/current"]
    finally:
        n.close()


def test_the_catalog_filters_survive_the_route():
    m, args = rpc.route("GET", "/app/available", {"catalog": "TRUENAS", "train": "stable"}, None)
    assert m == "app.available"
    assert args == [[["catalog", "=", "TRUENAS"], ["train", "=", "stable"]]]


def test_a_write_after_the_nas_closed_the_pooled_socket_still_works(nas):
    """CR-365 round 2: the send into a dead TCP connection succeeds locally, so
    request_sent blocked the retry; a liveness call first replaces the socket."""
    runs = []
    nas.handlers["group.create"] = lambda p: runs.append(p) or 7
    nas.handlers["core.ping"] = lambda p: "pong"
    assert _call(nas, "GET", "/user").status_code == 200
    nas.drop_connections()
    r = _call(nas, "POST", "/group", json_body={"name": "g"})
    assert r.status_code == 200 and len(runs) == 1
    assert nas.connections == 2


def test_the_api_path_can_be_overridden(monkeypatch):
    monkeypatch.setenv("TRUENAS_API_PATH", "current")
    assert rpc.api_paths() == ("/api/current",)
    monkeypatch.setenv("TRUENAS_API_PATH", "v26.04.0")
    assert rpc.api_paths() == ("/api/v26.04.0",)


# ---- 5: the certificate pin

def test_a_sha256_pin_is_honoured_by_the_rpc_client(monkeypatch):
    cert = b"fake-der-certificate"
    good = "sha256:" + hashlib.sha256(cert).hexdigest()

    class FakeTls:
        def getpeercert(self, binary_form=False):
            return cert

        def close(self):
            pass

        def settimeout(self, t):
            pass

        def sendall(self, data):
            raise OSError("fake socket")

    class Ctx:
        def wrap_socket(self, raw, server_hostname=None):
            return FakeTls()

    monkeypatch.setattr(rpc.socket, "create_connection", lambda *a, **k: object())
    monkeypatch.setattr(rpc, "_ssl_context", lambda verify: Ctx())
    with pytest.raises(rpc.RpcTransportError, match="does not match the pinned"):
        rpc.WebSocket("wss://nas.example.com/api/current", verify="sha256:" + "0" * 64)
    with pytest.raises(rpc.RpcTransportError) as ei:
        rpc.WebSocket("wss://nas.example.com/api/current", verify=good)
    assert "pinned" not in str(ei.value)       # past the pin, failed on the fake socket


def test_a_pin_builds_a_no_chain_context_not_a_cafile():
    import ssl
    ctx = rpc._ssl_context("sha256:" + "ab" * 32)
    assert ctx.verify_mode == ssl.CERT_NONE and ctx.check_hostname is False


# ---- round 2: the server scripts print the version note once

def test_the_version_note_is_printed_once_for_an_unsupported_release(monkeypatch, capsys):
    class R:
        def json(self):
            return {"version": "TrueNAS-SCALE-24.10.2"}
    calls = []
    monkeypatch.setattr(common, "_VERSION_NOTE_PRINTED", False)
    monkeypatch.setattr(common, "nas_kind", lambda args=None: "truenas")

    def api(m, p, *a, **k):
        calls.append((m, p))
        return R()
    assert "25.04" in common.print_truenas_version_note(api, args=None)
    assert common.print_truenas_version_note(api, args=None) == ""
    assert calls == [("GET", "/system/info")]
    assert "NOTE:" in capsys.readouterr().err


def test_the_version_note_never_raises(monkeypatch):
    monkeypatch.setattr(common, "_VERSION_NOTE_PRINTED", False)
    monkeypatch.setattr(common, "nas_kind", lambda args=None: "truenas")

    def api(*a, **k):
        raise RuntimeError("no network")
    assert common.print_truenas_version_note(api, args=None) == ""


def test_the_version_note_makes_no_call_on_dry_run_or_another_platform(monkeypatch):
    import types
    monkeypatch.setattr(common, "_VERSION_NOTE_PRINTED", False)
    monkeypatch.delenv(common.NAS_KIND_ENV, raising=False)
    calls = []

    def api(*a, **k):
        calls.append(a)
        raise AssertionError("must not call the NAS")
    ns = types.SimpleNamespace
    assert common.print_truenas_version_note(api, args=ns(dry_run=True, nas_kind="")) == ""
    assert common.print_truenas_version_note(api, args=ns(dry_run=False, nas_kind="synology")) == ""
    assert calls == []


def test_setup_editor_account_main_with_nas_kind_synology_calls_no_truenas_api(monkeypatch):
    import setup_editor_account as sea
    monkeypatch.setattr(common, "_VERSION_NOTE_PRINTED", False)
    calls = []
    monkeypatch.setattr(sea, "truenas_api", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(sys, "argv", ["x", "--dry-run", "--nas-kind", "synology", "--name", "probe"])
    with pytest.raises(SystemExit):
        sea.main()
    assert calls == []
