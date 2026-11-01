"""NAS TLS verification by certificate fingerprint (PR-GL19 / GL-18, CR-368,
2026-10-07).

Both NAS platforms ship a self-signed certificate, so "verify by default" cannot
mean "verify against the system CA bundle" for a customer who has not replaced
it. The secure default is therefore a PIN: `TRUENAS_VERIFY_SSL=sha256:<64 hex>`
(colons and case are ignored) accepts exactly the certificate with that SHA-256
fingerprint and nothing else. The install records the fingerprint of the NAS's
certificate once (server/common.py) and passes it to the container; a changed
certificate is a refusal, never a re-trust.

The three other spellings stay as they were: "1" (verify against the CA
bundle), a CA bundle path, and "0" (off, loud, and what the studio's own
site.toml keeps).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Any, Callable

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger("ccsync.dashboard.nas.tls_pin")

PREFIX = "sha256:"
# What an UNSET verify setting resolves to (CR-368 follow-up, GL-19 defect 2,
# 2026-10-07). A self-installed appliance has no base-rig deploy to hand it a
# pin, and "verify against the system CA bundle" cannot work against the
# self-signed certificate every NAS ships, so unset means: record the NAS's
# certificate fingerprint on the first connect, then refuse any other.
TOFU = "tofu"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def parse_pin(raw: Any) -> str:
    """The normalised lowercase 64-hex fingerprint in `raw`, or "".

    Only a str starting with `sha256:` is a pin; a bool or a CA path is not.
    A malformed pin raises ValueError rather than quietly meaning "off": a typo
    in a security setting must not turn verification into trust-everything.
    """
    if not isinstance(raw, str) or not raw.strip().lower().startswith(PREFIX):
        return ""
    digest = raw.strip()[len(PREFIX):].replace(":", "").replace(" ", "").lower()
    if not _HEX64.match(digest):
        raise ValueError(
            "a NAS certificate pin must be 'sha256:' followed by 64 hex digits "
            "(`openssl x509 -noout -fingerprint -sha256 -in cert.pem`)")
    return digest


class PinnedAdapter(HTTPAdapter):
    """An https adapter that accepts only the certificate with `fingerprint`.

    urllib3 checks `assert_fingerprint` after the handshake and counts the
    connection as verified when it matches, so no InsecureRequestWarning is
    raised and no CA is consulted. Use it with `verify=False` on the request
    (the chain is deliberately not walked: the pin is the whole trust).
    """

    def __init__(self, fingerprint: str, **kwargs: Any) -> None:
        self._fingerprint = fingerprint
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["assert_fingerprint"] = self._fingerprint
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def apply_verify(session: requests.Session, verify: Any) -> Any:
    """Make `session` honour `verify`; return what to pass as `verify=`.

    For a fingerprint pin this mounts the pinned adapter on https:// and returns
    False; for every other value it changes nothing and returns it as given.
    """
    digest = parse_pin(verify)
    if not digest:
        return verify
    session.mount("https://", PinnedAdapter(digest))
    return False


# ------------------------------------------------------------ first-use record

PIN_FILE = "nas_cert_pins.json"
_FAIL_COOLDOWN = 60.0
_failed: dict[str, float] = {}
_lock = threading.Lock()


def pin_path(data_dir: Path | None = None) -> Path:
    base = Path(data_dir) if data_dir is not None else Path(
        os.environ.get("DASH_DB_PATH", "/data/dashboard.db")).parent
    return base / "secrets" / PIN_FILE


def _load(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def recorded_pin(host: str, port: int, data_dir: Path | None = None) -> str:
    """The pin recorded for host:port, or ""."""
    return _load(pin_path(data_dir)).get(f"{host}:{port}", "")


def forget_pin(host: str, port: int, data_dir: Path | None = None) -> bool:
    """Drop the record so the next connect records afresh: the admin's explicit
    act after a deliberate certificate change. Never done automatically."""
    path = pin_path(data_dir)
    with _lock:
        pins = _load(path)
        if pins.pop(f"{host}:{port}", None) is None:
            return False
        from ..secrets_boot import write_secret_file
        write_secret_file(path, json.dumps(pins, sort_keys=True) + "\n")
        return True


def fetch_fingerprint(host: str, port: int, timeout: float = 4.0) -> str:
    """`sha256:<hex>` of the certificate the NAS presents right now. Reads the
    certificate only; nothing is sent and nothing is trusted by this call."""
    pem = ssl.get_server_certificate((host, port), timeout=timeout)
    der = ssl.PEM_cert_to_DER_cert(pem)
    return PREFIX + hashlib.sha256(der).hexdigest()


def split_host(host: str, default_port: int) -> tuple[str, int]:
    h = (host or "").strip()
    if h.count(":") == 1:
        name, _, port = h.partition(":")
        if port.isdigit():
            return name, int(port)
    return h, default_port


def resolve_first_use(host: str, verify: Any, default_port: int = 443,
                      data_dir: Path | None = None,
                      fetch: Callable[[str, int], str] | None = None) -> Any:
    """Turn the TOFU sentinel into a `sha256:` pin; anything else is returned
    as given. First call for a NAS records its fingerprint (0600, under
    <data>/secrets) and logs it; every later call returns the recorded pin, so
    a CHANGED certificate is a refusal in the client, never a re-record. If the
    NAS cannot be reached to read a certificate, the answer is True (verify
    against the system CA bundle): the connection then fails closed on its own
    rather than being trusted on no evidence."""
    if verify != TOFU:
        return verify
    name, port = split_host(host, default_port)
    key = f"{name}:{port}"
    path = pin_path(data_dir)
    with _lock:
        have = _load(path).get(key, "")
        if have:
            return have
        if time.monotonic() < _failed.get(key, 0.0):
            return True
        try:
            pin = (fetch or fetch_fingerprint)(name, port)
            parse_pin(pin)
            from ..secrets_boot import write_secret_file
            pins = _load(path)
            pins[key] = pin
            write_secret_file(path, json.dumps(pins, sort_keys=True) + "\n")
        except Exception as exc:                                       # noqa: BLE001
            _failed[key] = time.monotonic() + _FAIL_COOLDOWN
            log.warning("could not record the NAS certificate for %s (%s): "
                        "verifying against the system CA bundle until it answers", key, exc)
            return True
        log.warning("recorded the NAS certificate for %s on first use: %s. A different "
                    "certificate is refused from now on; to accept a replaced one, remove "
                    "that entry from %s", key, pin, path)
        return pin
