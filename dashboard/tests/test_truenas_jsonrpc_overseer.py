"""CR-365 overseer round (2026-10-07), the dashboard half.

The first JSON-RPC build logged a key in as the admin, let a login failure
escape as a raw error, logged in once per poll, left the pre-update snapshot
route unmapped, ignored the certificate pin, and shipped no rollback switch.
Each test here pins one.
"""
import hashlib
import re
from pathlib import Path

import pytest

from ccsync_dashboard.nas import truenas as tn
from ccsync_dashboard.nas import truenas_rpc as rpc
from ccsync_dashboard.nas.truenas import TrueNASClient, TrueNASError

from fake_truenas_rpc import Fail, FakeRpcNas

SRC = Path(__file__).resolve().parent.parent / "src" / "ccsync_dashboard"
DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


@pytest.fixture(autouse=True)
def _fresh_transport_state(monkeypatch):
    for name in ("DASH_NAS_API_TRANSPORT", "TRUENAS_API_TRANSPORT",
                 "DASH_NAS_API_KEY_USER", "TRUENAS_API_KEY_USER"):
        monkeypatch.delenv(name, raising=False)
    rpc.reset_pool()
    rpc._REST_ONLY.clear()
    rpc._GOOD_PATH.clear()
    yield
    rpc.reset_pool()
    rpc._REST_ONLY.clear()
    rpc._GOOD_PATH.clear()


def _keyed(peer, **kw):
    return TrueNASClient("127.0.0.1", "truenas_admin", "", ws_url=peer.url,
                         api_key="1-key", verify_ssl=False, **kw)


# ---- 1: the key's own account

def test_the_client_logs_the_key_in_as_its_own_account_not_the_admin():
    """DASH_NAS_USER is the admin (compose NAS_USER); the key belongs to
    ccsync-svc; 26 has no auth.login_with_api_key."""
    peer = FakeRpcNas({"group.query": lambda p: []}, key_user="ccsync-svc",
                      no_legacy_key=True)
    try:
        _keyed(peer, api_key_user="ccsync-svc").ping()
        assert [m for m, _ in peer.logins] == ["auth.login_ex"]
        assert peer.logins[0][1][0]["username"] == "ccsync-svc"
    finally:
        peer.close()


def test_the_key_user_defaults_from_the_environment(monkeypatch):
    monkeypatch.setenv("DASH_NAS_API_KEY_USER", "ccsync-svc")
    assert TrueNASClient("h", "admin", "", api_key="k").api_key_user == "ccsync-svc"
    monkeypatch.delenv("DASH_NAS_API_KEY_USER")
    monkeypatch.setenv("TRUENAS_API_KEY_USER", "other")
    assert TrueNASClient("h", "admin", "", api_key="k").api_key_user == "other"


def test_a_key_with_no_account_names_the_mismatch_not_revocation():
    peer = FakeRpcNas({"group.query": lambda p: []}, key_user="ccsync-svc",
                      no_legacy_key=True)
    try:
        with pytest.raises(TrueNASError) as ei:
            _keyed(peer).ping()
        assert "DASH_NAS_API_KEY_USER" in str(ei.value)
        assert "truenas_admin" in str(ei.value)
    finally:
        peer.close()


def test_settings_and_factory_carry_the_key_user():
    from ccsync_dashboard.nas.factory import make_nas_client
    from ccsync_dashboard.settings import Settings

    s = Settings(nas_kind="truenas", nas_host="nas", nas_user="truenas_admin",
                 nas_api_key="k", nas_api_key_user="ccsync-svc")
    c = make_nas_client(s)
    assert c.api_key_user == "ccsync-svc" and c.user == "truenas_admin"


# ---- 2: a login failure is a TrueNASError

@pytest.mark.parametrize("key", ["", "1-key"])
def test_a_login_rate_limit_is_a_truenas_error_not_a_raw_rpc_error(key):
    busy = Fail(code=-32001, message="Rate Limit Exceeded", errname="EBUSY")
    peer = FakeRpcNas({}, login_error=busy)
    try:
        c = TrueNASClient("127.0.0.1", "admin", "pw", ws_url=peer.url, api_key=key,
                          api_key_user="admin", verify_ssl=False)
        with pytest.raises(TrueNASError, match="Rate Limit Exceeded"):
            c.ping()
    finally:
        peer.close()


# ---- 3: one login per wait loop

def test_the_job_wait_loop_logs_in_once(monkeypatch):
    monkeypatch.setattr(tn.time, "sleep", lambda s: None)
    peer = FakeRpcNas({"core.get_jobs": lambda p: [{"id": 9, "state": "RUNNING"}]})
    try:
        c = TrueNASClient("127.0.0.1", "admin", "pw", ws_url=peer.url, api_key="",
                          verify_ssl=False)
        state, _ = c._wait_for_job(9, timeout=0.3, poll=0)
        assert state == "TIMEOUT"
        assert len(peer.calls) > 3
        assert len(peer.logins) == 1 and peer.connections == 1
    finally:
        peer.close()


# ---- 4: every route the dashboard sends is mapped

def test_the_pre_update_snapshot_goes_over_jsonrpc():
    peer = FakeRpcNas({"pool.snapshot.create": lambda p: {"name": "tank/apps@x"}})
    try:
        c = TrueNASClient("127.0.0.1", "admin", "pw", ws_url=peer.url, api_key="",
                          verify_ssl=False)
        resp = c.post("/zfs/snapshot", {"dataset": "tank/apps", "name": "x"})
        assert 200 <= resp.status_code < 300
        assert peer.calls == [("pool.snapshot.create", [{"dataset": "tank/apps", "name": "x"}])]
    finally:
        peer.close()


def _paths_used_in(*files):
    """Every REST path literal a TrueNASClient is asked for, found in source."""
    pat = re.compile(
        r'(?:(?<!router)(?<!app)\.(?:get|post|put)\(|_request\(\s*"[A-Z]+",\s*)f?"(/[^"]*)"')
    found = []
    for rel in files:
        for m in pat.finditer((SRC / rel).read_text(encoding="utf-8")):
            found.append((rel, m.group(1)))
    return found


@pytest.mark.parametrize("rel,path", sorted(set(_paths_used_in(
    "nas/truenas.py", "dashboard_update.py", "invariants.py"))))
def test_every_path_the_dashboard_sends_a_truenas_client_is_mapped(rel, path):
    concrete = re.sub(r"\{[^}]*\}", "7", path)
    methods = ("GET", "POST", "PUT", "DELETE")
    mapped = []
    for m in methods:
        try:
            rpc.route(m, concrete, None, {"app_name": "x"} if "redeploy" in concrete else {})
            mapped.append(m)
        except rpc.UnmappedRoute:
            pass
    assert mapped, f"{rel} sends {path}, which has no JSON-RPC mapping on any method"


def test_the_source_scan_actually_finds_the_known_routes():
    found = {p for _, p in _paths_used_in("nas/truenas.py", "dashboard_update.py", "invariants.py")}
    assert {"/group", "/user", "/zfs/snapshot", "/pool/snapshottask",
            "/core/get_jobs", "/filesystem/setperm"} <= found


def test_an_unmapped_route_falls_back_to_rest_and_a_pinned_transport_refuses(monkeypatch):
    peer = FakeRpcNas({})
    urls = []

    class R:
        status_code = 200
        text = "[]"
        headers = {}

        def json(self):
            return []

    try:
        c = TrueNASClient("127.0.0.1", "admin", "pw", ws_url=peer.url, api_key="",
                          verify_ssl=False)
        monkeypatch.setattr(c.session, "request", lambda m, url, **k: (urls.append(url), R())[1])
        assert c.get("/not-mapped").status_code == 200
        assert urls == ["https://127.0.0.1/api/v2.0/not-mapped"]
        pinned = TrueNASClient("127.0.0.1", "admin", "pw", ws_url=peer.url, api_key="",
                               verify_ssl=False, transport="jsonrpc")
        with pytest.raises(TrueNASError, match="not-mapped"):
            pinned.get("/not-mapped")
    finally:
        peer.close()


# ---- 5: the certificate pin on the RPC path

def test_the_rpc_client_honours_a_sha256_pin(monkeypatch):
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
    bad = TrueNASClient("nas.example.com", "u", "p", api_key="", verify_ssl="sha256:" + "0" * 64)
    with pytest.raises(TrueNASError, match="does not match the pinned"):
        bad.get("/group")
    ok_pin = TrueNASClient("nas.example.com", "u", "p", api_key="", verify_ssl=good)
    with pytest.raises(TrueNASError) as ei:
        ok_pin.get("/group")
    assert "pinned" not in str(ei.value)      # past the pin; died on the fake socket


def test_a_pin_is_not_read_as_a_ca_file():
    import ssl
    ctx = rpc._ssl_context("sha256:" + "ab" * 32)
    assert ctx.verify_mode == ssl.CERT_NONE


# ---- 6: the rollback switch is plumbed

@pytest.mark.parametrize("name", ["compose.yaml", "compose.image.yaml", "compose.appliance.yaml"])
def test_every_compose_template_passes_the_transport_switch(name):
    text = (DEPLOY / name).read_text(encoding="utf-8")
    assert "DASH_NAS_API_TRANSPORT:" in text


@pytest.mark.parametrize("name", ["compose.yaml", "compose.image.yaml"])
def test_the_truenas_templates_pass_the_key_user(name):
    text = (DEPLOY / name).read_text(encoding="utf-8")
    assert "DASH_NAS_API_KEY_USER:" in text and "TRUENAS_API_KEY_USER:" in text


def test_the_wizard_form_takes_the_key_account():
    from ccsync_dashboard import appliance_config as ac

    assert "DASH_NAS_API_KEY_USER" in ac.ALLOWED
    assert ac.FORMS["nas_connect"][0].env == "DASH_NAS_KIND"
    with pytest.raises(ac.ConfigError):
        ac._VALIDATORS["DASH_NAS_API_KEY_USER"]("bad name; rm")
    assert ac._VALIDATORS["DASH_NAS_API_KEY_USER"]("ccsync-svc") == "ccsync-svc"


def test_the_installer_writes_both_new_names_into_the_container_env():
    root = Path(__file__).resolve().parents[2]
    text = (root / "server" / "install_dashboard_app.py").read_text(encoding="utf-8")
    for name in ("TRUENAS_API_KEY_USER", "DASH_NAS_API_KEY_USER", "DASH_NAS_API_TRANSPORT"):
        assert f'"{name}"' in text, name


# ---- 7: the REST-only memory

def test_the_rest_only_memory_expires_and_a_rest_404_clears_it(monkeypatch):
    dead = FakeRpcNas(endpoint=False, endpoint_status=200)

    class R:
        status_code = 404
        text = ""
        headers = {}

    c = TrueNASClient("127.0.0.1", "admin", "pw", ws_url=dead.url, api_key="",
                      verify_ssl=False)
    monkeypatch.setattr(c.session, "request", lambda m, url, **k: R())
    try:
        assert c.get("/group").status_code == 404
    finally:
        dead.close()
    assert not rpc.rest_only("127.0.0.1")        # cleared by the 404
    rpc.mark_rest_only("h")
    real = rpc.time.monotonic
    monkeypatch.setattr(rpc.time, "monotonic", lambda: real() + rpc.REST_ONLY_TTL + 1)
    assert not rpc.rest_only("h")


def test_a_ui_catch_all_answer_at_the_endpoint_is_no_jsonrpc_not_a_transport_error():
    dead = FakeRpcNas(endpoint=False, endpoint_status=200)
    try:
        with pytest.raises(rpc.RpcUnavailable):
            rpc.rest_call("127.0.0.1", "GET", "/group", url=dead.url, user="a", password="b")
    finally:
        dead.close()


# ---- round 2 (2026-10-07): a TrueNAS key needs its account named

def test_the_wizard_requires_the_key_account_with_a_truenas_key(tmp_path):
    from ccsync_dashboard import appliance_config
    with pytest.raises(appliance_config.ConfigError, match="account"):
        appliance_config.save("nas_connect", {"DASH_NAS_HOST": "nas.local",
                                              "DASH_NAS_API_KEY": "1-k"}, data_dir=tmp_path)
    appliance_config.save("nas_connect", {"DASH_NAS_HOST": "nas.local",
                                          "DASH_NAS_API_KEY": "1-k",
                                          "DASH_NAS_API_KEY_USER": "ccsync-svc"},
                          data_dir=tmp_path)
    for f in appliance_config.view("nas_connect", data_dir=tmp_path):
        if f["env"] == "DASH_NAS_API_KEY_USER":
            assert "blank" not in f.get("help", "").lower()


def test_the_catalog_route_keeps_its_filters_and_pin_is_gone():
    m, args = rpc.route("GET", "/app/available", {"catalog": "TRUENAS", "train": "stable"}, None)
    assert args == [[["catalog", "=", "TRUENAS"], ["train", "=", "stable"]]]
    assert rpc.api_paths() == ("/api/current",)


def test_a_write_after_the_nas_closed_the_pooled_socket_still_works():
    runs = []
    peer = FakeRpcNas({"group.query": lambda p: [],
                       "core.ping": lambda p: "pong",
                       "group.create": lambda p: runs.append(p) or 5})
    try:
        c = _keyed(peer)
        c.get("/group")
        peer.drop_connections()
        assert c.post("/group", {"name": "g"}) is not None
        assert len(runs) == 1
    finally:
        peer.close()
