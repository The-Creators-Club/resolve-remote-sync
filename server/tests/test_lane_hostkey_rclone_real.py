"""The editor-lane host-key pin against a REAL rclone and a multi-key sshd
(CR-368 follow-up, GL-19, 2026-10-07).

The first build wrote ONE ed25519 line into known_hosts and no
host_key_algorithms. rclone's Go ssh client prefers ECDSA, the NAS sshd offers
ecdsa, rsa and ed25519, so it negotiated ECDSA, found the host under a
different key type and aborted with `knownhosts: key mismatch` on every new
site's lanes. Text-matching tests could not see that; this one runs rclone.
"""
from __future__ import annotations

import glob
import os
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest

paramiko = pytest.importorskip("paramiko")


def _rclone() -> str | None:
    found = shutil.which("rclone")
    if found:
        return found
    pats = [os.path.expanduser(
        "~/AppData/Local/Microsoft/WinGet/Packages/Rclone.Rclone*/rclone-*/rclone.exe")]
    for pat in pats:
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    return None


RCLONE = _rclone()
pytestmark = pytest.mark.skipif(RCLONE is None, reason="needs rclone")


class _Reject(paramiko.ServerInterface):
    def check_auth_publickey(self, username, key):
        return paramiko.AUTH_FAILED

    def check_auth_password(self, username, password):
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "publickey"


@pytest.fixture()
def sshd():
    ecdsa = paramiko.ECDSAKey.generate(bits=256)
    rsa = paramiko.RSAKey.generate(2048)
    ed = _ed25519()
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(0.5)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            t = paramiko.Transport(conn)
            for k in (ecdsa, rsa, ed):
                t.add_server_key(k)
            try:
                t.start_server(server=_Reject())
            except Exception:
                pass

    th = threading.Thread(target=loop, daemon=True)
    th.start()
    yield srv.getsockname()[1], ed
    stop.set()
    srv.close()


def _ed25519():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import io
    pem = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption()).decode()
    return paramiko.Ed25519Key.from_private_key(io.StringIO(pem))


def _try(tmp_path: Path, port: int, ed, with_algo: bool) -> str:
    kh = tmp_path / "nas_known_hosts"
    kh.write_text(f"[127.0.0.1]:{port} ssh-ed25519 {ed.get_base64()}\n", encoding="utf-8")
    client_key = tmp_path / "id"
    paramiko.RSAKey.generate(2048).write_private_key_file(str(client_key))
    stanza = (f"[lane]\ntype = sftp\nhost = 127.0.0.1\nuser = e\nport = {port}\n"
              f"key_file = {client_key}\nshell_type = unix\nknown_hosts_file = {kh}\n")
    if with_algo:
        stanza += "host_key_algorithms = ssh-ed25519\n"
    conf = tmp_path / "rclone.conf"
    conf.write_text(stanza, encoding="utf-8")
    r = subprocess.run([RCLONE, "--config", str(conf), "lsd", "lane:", "--retries", "1",
                        "--low-level-retries", "1", "--contimeout", "10s"],
                       capture_output=True, encoding="utf-8", errors="replace", timeout=90)
    return r.stdout + r.stderr


def test_without_the_algorithm_pin_rclone_hits_a_key_mismatch(sshd, tmp_path):
    port, ed = sshd
    assert "key mismatch" in _try(tmp_path, port, ed, with_algo=False)


def test_with_the_algorithm_pin_rclone_passes_the_host_key_check(sshd, tmp_path):
    port, ed = sshd
    out = _try(tmp_path, port, ed, with_algo=True)
    assert "key mismatch" not in out and "knownhosts" not in out, out
    assert "authenticate" in out or "publickey" in out, out


def test_a_different_ed25519_key_is_still_refused(sshd, tmp_path):
    port, _ = sshd
    out = _try(tmp_path, port, _ed25519(), with_algo=True)
    assert "knownhosts" in out or "key mismatch" in out, out
