"""TrueNAS JSON-RPC transport (CR-365, GL-11 + GL-46, 2026-10-07).

TrueNAS 26 removed REST /api/v2.0. These tests hold: the two copies of
truenas_rpc.py are one file; every REST route this product calls maps to a
JSON-RPC method; the websocket client speaks real RFC 6455 against an
in-process peer; common.truenas_api uses it, falls back to REST only when the
NAS has no /api/current, and never sends a key over plaintext ws://.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import common  # noqa: E402
import create_api_key  # noqa: E402
import truenas_rpc as rpc  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "fake_truenas_rpc", HERE.parent.parent / "dashboard" / "tests" / "fake_truenas_rpc.py")
fake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fake)


def test_the_two_copies_are_byte_identical():
    a = (HERE.parent / "truenas_rpc.py").read_bytes()
    b = (HERE.parent.parent / "dashboard" / "src" / "ccsync_dashboard" / "nas"
         / "truenas_rpc.py").read_bytes()
    assert a == b, "edit server/truenas_rpc.py and the dashboard's nas/truenas_rpc.py together"


@pytest.mark.parametrize("method,path,params,body,expect", [
    ("GET", "/group", {"group": "editors"}, None, ("group.query", [[["group", "=", "editors"]]])),
    ("POST", "/group", None, {"name": "editors"}, ("group.create", [{"name": "editors"}])),
    ("GET", "/user", None, None, ("user.query", [[]])),
    ("GET", "/user", {"username": "bob"}, None, ("user.query", [[["username", "=", "bob"]]])),
    ("GET", "/user/id/7", None, None, ("user.get_instance", [7])),
    ("POST", "/user", None, {"username": "bob"}, ("user.create", [{"username": "bob"}])),
    ("PUT", "/user/id/7", None, {"smb": True}, ("user.update", [7, {"smb": True}])),
    ("DELETE", "/user/id/7", None, {"delete_group": False}, ("user.delete", [7, {"delete_group": False}])),
    ("POST", "/filesystem/setperm", None, {"path": "/x"}, ("filesystem.setperm", [{"path": "/x"}])),
    ("GET", "/core/get_jobs", {"id": 5}, None, ("core.get_jobs", [[["id", "=", 5]]])),
    ("GET", "/system/info", None, None, ("system.info", [])),
    ("GET", "/pool/snapshottask", None, None, ("pool.snapshottask.query", [[]])),
    ("POST", "/pool/snapshottask", None, {"a": 1}, ("pool.snapshottask.create", [{"a": 1}])),
    ("PUT", "/pool/snapshottask/id/3", None, {"a": 1}, ("pool.snapshottask.update", [3, {"a": 1}])),
    ("POST", "/api_key", None, {"name": "k"}, ("api_key.create", [{"name": "k"}])),
    ("GET", "/app", None, None, ("app.query", [[]])),
    ("POST", "/app", None, {"app_name": "x"}, ("app.create", [{"app_name": "x"}])),
    ("DELETE", "/app/id/dash", None, {"remove_ix_volumes": False},
     ("app.delete", ["dash", {"remove_ix_volumes": False}])),
    ("GET", "/ssh", None, None, ("ssh.config", [])),
    ("PUT", "/ssh", None, {"options": "x"}, ("ssh.update", [{"options": "x"}])),
    ("GET", "/app/available", {"catalog": "TRUENAS"}, None, ("app.available", [[["catalog", "=", "TRUENAS"]]])),
    ("GET", "/catalog/apps", {"train": "stable"}, None, ("catalog.apps", [])),
    ("POST", "/app/redeploy", None, {"app_name": "dash"}, ("app.redeploy", ["dash"])),
    # dashboard_update's pre-update snapshot (CR-365 overseer 4)
    ("POST", "/zfs/snapshot", None, {"dataset": "tank/apps", "name": "x"},
     ("pool.snapshot.create", [{"dataset": "tank/apps", "name": "x"}])),
])
def test_every_rest_route_this_product_uses_maps_to_a_method(method, path, params, body, expect):
    assert rpc.route(method, path, params, body) == expect


def test_a_route_nobody_mapped_is_a_named_refusal_not_a_guess():
    with pytest.raises(rpc.UnmappedRoute):
        rpc.route("POST", "/service/restart", None, {})


def test_every_route_the_api_key_script_lists_is_mapped():
    """create_api_key.ALLOWLIST is the dashboard's call list; a route added
    there with no JSON-RPC mapping would work on 25.x REST and 404 on 26."""
    probes = {"/user": [("GET", None), ("POST", {}), ("PUT", None)],
              "/group": [("GET", None), ("POST", {})],
              "/filesystem/setperm": [("POST", {})],
              "/core/get_jobs": [("GET", None)]}
    for entry in create_api_key.ALLOWLIST:
        assert entry["resource"] in probes, entry
        assert entry["method"] in [m for m, _ in probes[entry["resource"]]]
    for resource, calls in probes.items():
        for method, body in calls:
            path = resource + ("/id/1" if method == "PUT" else "")
            rpc.route(method, path, None, {} if method == "PUT" else body)


def test_the_version_statement():
    assert rpc.version_note("TrueNAS-25.10.0.1") == ""
    assert rpc.version_note("TrueNAS-SCALE-25.04.2") == ""
    assert rpc.version_note("26.04.0") == ""
    assert "predates 25.04" in rpc.version_note("TrueNAS-SCALE-24.10.2")
    assert "newer than" in rpc.version_note("TrueNAS-31.01")
    assert "cannot tell" in rpc.version_note("")


# ------------------------------------------------------------ over the wire

@pytest.fixture(autouse=True)
def _fresh_transport_state():
    """The pool, the REST-only memory and the good-path memory are process
    state (CR-365 overseer 3/7); a test must not inherit another's."""
    rpc.reset_pool()
    rpc._REST_ONLY.clear()
    rpc._GOOD_PATH.clear()
    yield
    rpc.reset_pool()
    rpc._REST_ONLY.clear()
    rpc._GOOD_PATH.clear()


@pytest.fixture
def nas():
    users = [{"id": 7, "username": "bob", "uid": 3001}]
    n = fake.FakeRpcNas({
        "user.query": lambda p: [u for u in users if all(
            u.get(f[0]) == f[2] for f in (p[0] if p else []))],
        "user.get_instance": lambda p: next(u for u in users if u["id"] == p[0]),
        "user.update": lambda p: (_ for _ in ()).throw(fake.Fail(
            errname="EINVAL", message="Validation", reason="SMB users cannot disable password")),
        "filesystem.setperm": lambda p: 99,
        "core.get_jobs": lambda p: [{"id": p[0][0][2], "state": "SUCCESS", "error": None}],
        "big": lambda p: ["x" * 70000],
    })
    yield n
    n.close()


def _call(nas, method, path, **kw):
    kw.setdefault("user", "admin")
    kw.setdefault("password", "pw")
    return rpc.rest_call("127.0.0.1", method, path, url=nas.url, timeout=5, **kw)


def test_a_query_over_the_websocket_looks_like_a_rest_response(nas):
    resp = _call(nas, "GET", "/user", params={"username": "bob"})
    assert resp.status_code == 200
    assert resp.json()[0]["id"] == 7
    assert "bob" in resp.text
    assert nas.logins[0][0] == "auth.login_ex"


def test_a_large_fragmented_reply_with_notifications_and_pings(nas):
    sess = rpc.RpcSession(rpc.WebSocket(nas.url, timeout=5))
    try:
        sess.login("admin", "pw", "")
        # "big" is not a TrueNAS method; the peer's handler table answers it.
        assert len(sess.call("big")[0]) == 70000
    finally:
        sess.close()


def test_a_job_method_returns_its_job_id_and_get_jobs_reports_it(nas):
    assert _call(nas, "POST", "/filesystem/setperm", json_body={"path": "/x"}).json() == 99
    jobs = _call(nas, "GET", "/core/get_jobs", params={"id": 99}).json()
    assert jobs[0]["state"] == "SUCCESS"


def test_a_validation_error_is_a_422_whose_text_carries_the_reason(nas):
    resp = _call(nas, "PUT", "/user/id/7", json_body={"password_disabled": True})
    assert resp.status_code == 422
    assert "SMB" in resp.text      # the dashboard's expected-422 test reads this


def test_an_unknown_method_is_a_404(nas):
    assert _call(nas, "GET", "/ssh").status_code == 404


def test_a_wrong_password_is_a_named_auth_error(nas):
    with pytest.raises(rpc.RpcAuthError):
        _call(nas, "GET", "/user", password="nope")


def test_api_key_acts_as_its_own_account_not_the_admin():
    n = fake.FakeRpcNas({"user.query": lambda p: []}, key_user="ccsync-api")
    try:
        resp = _call(n, "GET", "/user", api_key="1-key", user="admin", password="")
        assert resp.status_code == 200
        methods = [m for m, _ in n.logins]
        assert methods == ["auth.login_ex", "auth.login_with_api_key"]
    finally:
        n.close()


def test_legacy_login_methods_are_the_fallback():
    n = fake.FakeRpcNas({"user.query": lambda p: []}, legacy_login=True)
    try:
        assert _call(n, "GET", "/user").status_code == 200
        assert [m for m, _ in n.logins] == ["auth.login_ex", "auth.login"]
    finally:
        n.close()


def test_no_endpoint_is_rpc_unavailable_so_rest_can_take_over():
    n = fake.FakeRpcNas(endpoint=False)
    try:
        with pytest.raises(rpc.RpcUnavailable):
            _call(n, "GET", "/user")
    finally:
        n.close()


def test_a_refused_connection_is_a_named_transport_error_not_unavailable():
    with pytest.raises(rpc.RpcTransportError):
        rpc.rest_call("127.0.0.1", "GET", "/user", url="ws://127.0.0.1:9/api/current",
                      user="a", password="b", timeout=2)


def test_plaintext_ws_to_a_real_host_is_refused():
    with pytest.raises(rpc.RpcTransportError, match="plaintext"):
        rpc.WebSocket("ws://nas.example.com/api/current")


def test_verify_maps_to_the_tls_context():
    import ssl
    assert rpc._ssl_context(False).verify_mode == ssl.CERT_NONE
    assert rpc._ssl_context(True).verify_mode == ssl.CERT_REQUIRED


# ------------------------------------------------------ common.truenas_api

@pytest.fixture
def env(monkeypatch, nas):
    monkeypatch.setenv("TRUENAS_HOST", "127.0.0.1")
    monkeypatch.setenv("TRUENAS_USER", "admin")
    monkeypatch.setenv("TRUENAS_PW", "pw")
    monkeypatch.delenv("TRUENAS_API_KEY", raising=False)
    monkeypatch.setenv("TRUENAS_WS_URL", nas.url)
    monkeypatch.setenv("TRUENAS_VERIFY_SSL", "1")


def test_truenas_api_uses_jsonrpc_by_default(env, nas, monkeypatch):
    import requests

    def boom(*a, **k):
        raise AssertionError("REST must not be used when /api/current answers")
    monkeypatch.setattr(requests, "request", boom)
    resp = common.truenas_api("GET", "/user", params={"username": "bob"})
    assert common.ok(resp) and resp.json()[0]["username"] == "bob"


def test_truenas_api_falls_back_to_rest_when_the_nas_has_no_endpoint(env, monkeypatch):
    import requests
    dead = fake.FakeRpcNas(endpoint=False)
    monkeypatch.setenv("TRUENAS_WS_URL", dead.url)
    seen = []

    class R:
        status_code = 200

    monkeypatch.setattr(requests, "request", lambda m, url, **k: (seen.append(url), R())[1])
    try:
        common.truenas_api("GET", "/user")
        common.truenas_api("GET", "/user")
    finally:
        dead.close()
    assert seen == ["https://127.0.0.1/api/v2.0/user"] * 2
    assert rpc.rest_only("127.0.0.1")


def test_pinned_jsonrpc_never_falls_back(env, monkeypatch):
    import requests
    dead = fake.FakeRpcNas(endpoint=False)
    monkeypatch.setenv("TRUENAS_WS_URL", dead.url)
    monkeypatch.setenv("TRUENAS_API_TRANSPORT", "jsonrpc")
    try:
        with pytest.raises(requests.exceptions.ConnectionError, match="forbids"):
            common.truenas_api("GET", "/user")
    finally:
        dead.close()


def test_wait_for_job_runs_over_the_websocket(env, nas, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    state, err = common.wait_for_job(99, timeout=5, poll=0)
    assert state == "SUCCESS" and err is None


def test_an_unmapped_route_raises_a_named_connection_error(env, monkeypatch):
    import requests
    # auto falls back to REST for it (overseer 4); the pinned transport refuses.
    monkeypatch.setenv("TRUENAS_API_TRANSPORT", "jsonrpc")
    with pytest.raises(requests.exceptions.ConnectionError, match="no JSON-RPC|UnmappedRoute|POST /nope"):
        common.truenas_api("POST", "/nope", json_body={})
