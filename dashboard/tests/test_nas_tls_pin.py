"""NAS TLS verification by default and by fingerprint pin (PR-GL19 / GL-18,
CR-368, 2026-10-07), plus the Synology SSH host key being RECORDED on first use
(bug-dash-ops-5).

The pin tests talk to a real TLS server on loopback with a self-signed
certificate: a mocked adapter would pass whether or not urllib3 really checks
the fingerprint, which is the one thing that matters.
"""
from __future__ import annotations

import datetime
import hashlib
import http.server
import logging
import ssl
import threading

import pytest

from ccsync_dashboard.nas import synology as syn
from ccsync_dashboard.nas import tls_pin
from ccsync_dashboard.nas.base import NasError
from ccsync_dashboard.nas.synology import SynologyClient
from ccsync_dashboard.nas.truenas import TrueNASClient, TrueNASError
from ccsync_dashboard.settings import Settings

cryptography = pytest.importorskip("cryptography")


def _self_signed(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "nas.test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "c.pem", tmp_path / "k.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    fp = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    return str(cert_path), str(key_path), fp


@pytest.fixture()
def tls_nas(tmp_path):
    cert, key, fp = _self_signed(tmp_path)

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"[]"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"https://127.0.0.1:{server.server_address[1]}/api/v2.0", fp
    server.shutdown()


def _client(base, verify):
    return TrueNASClient("127.0.0.1", "u", "p", base_url=base, verify_ssl=verify)


def test_a_matching_pin_is_accepted_and_a_self_signed_cert_is_otherwise_refused(tls_nas):
    base, fp = tls_nas
    assert _client(base, "sha256:" + fp).get("/user").status_code == 200
    # the colon-separated upper-case spelling `openssl x509 -fingerprint` prints
    spelled = ":".join(fp[i:i + 2] for i in range(0, 64, 2)).upper()
    assert _client(base, "sha256:" + spelled).get("/user").status_code == 200
    # verify on, no pin: the self-signed cert is not in any CA bundle
    with pytest.raises(TrueNASError):
        _client(base, True).get("/user")


def test_a_different_pin_is_a_refusal_not_a_fallback(tls_nas):
    base, fp = tls_nas
    wrong = "sha256:" + ("0" * 64 if fp != "0" * 64 else "1" * 64)
    with pytest.raises(TrueNASError):
        _client(base, wrong).get("/user")


def test_a_malformed_pin_raises_instead_of_meaning_off():
    with pytest.raises(ValueError, match="64 hex"):
        tls_pin.parse_pin("sha256:abc")
    with pytest.raises(ValueError):
        _client("https://x/api", "sha256:nothex" + "z" * 60)
    # a bool or a CA path is not a pin
    assert tls_pin.parse_pin(True) == "" and tls_pin.parse_pin("/certs/ca.pem") == ""


def test_the_pin_applies_to_the_synology_client_too(tls_nas):
    base, fp = tls_nas
    client = SynologyClient("127.0.0.1", "u", "p", "sha256:" + fp, base_url=base)
    assert client._verify_arg is False
    assert any(isinstance(a, tls_pin.PinnedAdapter) for a in client.session.adapters.values())
    other = SynologyClient("127.0.0.1", "u", "p", True, base_url=base)
    assert other._verify_arg is True


def test_unset_means_first_use_pinning_everywhere(monkeypatch):
    for name in ("DASH_NAS_VERIFY_SSL", "TRUENAS_VERIFY_SSL"):
        monkeypatch.delenv(name, raising=False)
    assert Settings.from_env({}).nas_verify_ssl == tls_pin.TOFU
    assert Settings.from_env({"TRUENAS_VERIFY_SSL": "0"}).nas_verify_ssl is False
    pin = "sha256:" + "ab" * 32
    assert Settings.from_env({"TRUENAS_VERIFY_SSL": pin}).nas_verify_ssl == pin
    from ccsync_dashboard.nas import synology, truenas
    assert truenas._verify_setting() == tls_pin.TOFU
    assert synology._verify_setting() == tls_pin.TOFU
    monkeypatch.setenv("TRUENAS_VERIFY_SSL", "0")
    assert TrueNASClient("h", "u", "p").verify_ssl is False


def test_first_use_records_the_certificate_then_refuses_a_different_one(
        tls_nas, tmp_path, monkeypatch):
    """CR-368 follow-up (2026-10-07), appliance path: no pin source exists for a
    self-installing customer, and system-CA verification fails against the NAS's
    self-signed certificate, so the dashboard records it on first connect."""
    base, fp = tls_nas
    port = int(base.split(":")[2].split("/")[0])
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "data" / "dashboard.db"))
    tls_pin._failed.clear()
    pin = tls_pin.resolve_first_use("127.0.0.1", tls_pin.TOFU, port)
    assert pin == "sha256:" + fp
    assert tls_pin.recorded_pin("127.0.0.1", port) == pin
    # the recorded pin now actually works end to end ...
    assert _client(base, pin).get("/user") is not None
    # ... and a later certificate cannot replace it: the record wins over a fetch
    calls = []
    assert tls_pin.resolve_first_use(
        "127.0.0.1", tls_pin.TOFU, port,
        fetch=lambda h, p: calls.append(1) or "sha256:" + "00" * 32) == pin
    assert calls == []
    # an admin's explicit forget is the only way to re-record
    assert tls_pin.forget_pin("127.0.0.1", port) is True
    assert tls_pin.recorded_pin("127.0.0.1", port) == ""


def test_first_use_with_an_unreachable_nas_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "d" / "dashboard.db"))
    tls_pin._failed.clear()

    def boom(h, p):
        raise OSError("unreachable")
    assert tls_pin.resolve_first_use("10.255.255.1", tls_pin.TOFU, 443, fetch=boom) is True
    assert tls_pin.recorded_pin("10.255.255.1", 443) == ""


def test_the_clients_resolve_first_use_at_construction(tls_nas, tmp_path, monkeypatch):
    base, fp = tls_nas
    port = int(base.split(":")[2].split("/")[0])
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "d" / "dashboard.db"))
    monkeypatch.delenv("DASH_NAS_VERIFY_SSL", raising=False)
    monkeypatch.delenv("TRUENAS_VERIFY_SSL", raising=False)
    tls_pin._failed.clear()
    syn = SynologyClient("127.0.0.1", "u", "p", port=port)
    assert syn.verify_ssl == "sha256:" + fp
    tn = TrueNASClient("127.0.0.1:%d" % port, "u", "p")
    assert tn.verify_ssl == "sha256:" + fp
    # a plain-http test fake has no certificate to record
    assert TrueNASClient("h", "u", "p", base_url="http://x/api").verify_ssl is True


# ------------------------------------------------------- SSH host key (DSM)


def test_the_first_unpinned_ssh_host_key_is_recorded_then_a_change_is_refused(
        monkeypatch, tmp_path, caplog):
    paramiko = pytest.importorskip("paramiko")
    monkeypatch.delenv("DASH_NAS_SSH_HOSTKEY", raising=False)
    monkeypatch.setenv("DASH_NAS_KNOWN_HOSTS", str(tmp_path / "secrets" / "nas_known_hosts"))
    monkeypatch.setattr(paramiko.SSHClient, "connect", lambda self, **kw: None)

    client = SynologyClient("dsm.example", "ccsync", "pw")
    with caplog.at_level(logging.WARNING, logger="ccsync.dashboard.nas.synology"):
        ssh = client._ssh_client()
    assert "recorded" in "\n".join(r.getMessage() for r in caplog.records)

    first = paramiko.Ed25519Key.generate() if hasattr(paramiko.Ed25519Key, "generate") \
        else paramiko.RSAKey.generate(2048)
    ssh._policy.missing_host_key(ssh, "dsm.example", first)
    saved = tmp_path / "secrets" / "nas_known_hosts"
    assert saved.exists() and first.get_base64() in saved.read_text()

    # A later connection (a fresh client) loads that file...
    again = SynologyClient("dsm.example", "ccsync", "pw")._ssh_client()
    assert again.get_host_keys().lookup("dsm.example") is not None
    # ...and a DIFFERENT key for the same host is a refusal, even of another type.
    other = paramiko.RSAKey.generate(2048)
    with pytest.raises(paramiko.SSHException, match="refusing"):
        again._policy.missing_host_key(again, "dsm.example", other)


def test_the_known_hosts_file_lives_under_the_data_secrets_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("DASH_NAS_KNOWN_HOSTS", raising=False)
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "dashboard.db"))
    assert syn._known_hosts_path() == str(tmp_path / "secrets" / "nas_known_hosts")
    monkeypatch.delenv("DASH_DB_PATH")
    assert syn._known_hosts_path() == ""


# ---------------------------------------------- the JSON-RPC websocket twin


def test_the_jsonrpc_websocket_honours_a_pin_too(tls_nas):
    """truenas_rpc.py is byte-identical in server/ and here; both must refuse
    a certificate that is not the pinned one BEFORE any frame is sent."""
    from ccsync_dashboard.nas import truenas_rpc

    base, fp = tls_nas
    url = base.replace("https://", "wss://").replace("/api/v2.0", "/api/current")
    with pytest.raises(truenas_rpc.RpcTransportError, match="does not match the pinned"):
        truenas_rpc.WebSocket(url, verify="sha256:" + "0" * 64, timeout=5)
    # the right pin passes the TLS check and fails LATER, at the websocket
    # handshake this plain-HTTP fixture cannot answer
    with pytest.raises((truenas_rpc.RpcTransportError, truenas_rpc.RpcUnavailable)) as exc:
        truenas_rpc.WebSocket(url, verify="sha256:" + fp, timeout=5)
    assert "does not match the pinned" not in str(exc.value)
    with pytest.raises(truenas_rpc.RpcTransportError, match="not a sha256"):
        truenas_rpc.WebSocket(url, verify="sha256:short", timeout=5)
