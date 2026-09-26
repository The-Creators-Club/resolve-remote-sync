"""Leave EXPIRED certificates out of the Windows trust Python builds (CR-350).

Python's `ssl.create_default_context()` on Windows loads every certificate in
the machine's and the user's "CA" (intermediate) and "ROOT" stores as a TRUST
ANCHOR, expired or not. Windows itself never chains through an expired one;
OpenSSL can. On 2026-09-26 Ruskin's companion was switched to the dashboard's
https address (Tailscale Serve, a Let's Encrypt YE2 certificate valid until
November) and every report failed with "certificate verify failed:
certificate has expired", while curl.exe on the same machine (Schannel)
connected fine. The cause was one cached intermediate in his
CurrentUser\\CA store: "ISRG Root X2, issued by ISRG Root X1", which expired
2025-09-16. OpenSSL picked it while building the chain and stopped at its
date. Removing that single certificate fixed it (reproduced by exporting his
stores to PEM and testing with `cafile=`), but Windows re-caches
intermediates it meets, and every editor's machine can carry its own.

So `install()` replaces `ssl.SSLContext._load_windows_store_certs` with the
same loop minus any certificate whose notAfter is in the past. Nothing else
changes: the same stores, the same trust-purpose test, the same per-cert
error handling. A certificate whose date cannot be read is KEPT (the
stdlib's own behaviour), so a parser gap can never shrink trust. Windows
only, idempotent, never raises; it must run before the first HTTPS call,
which is why app.run calls it next to sidecar_tools.ensure_ca_bundle.

`_load_windows_store_certs` is private but has had this shape since Python
3.4; if a future Python drops it, `install()` does nothing and says so.
"""

from __future__ import annotations

import logging
import ssl
import sys
import warnings
from datetime import datetime, timezone
from typing import Any, Callable, Optional

log = logging.getLogger("ccsync.win_trust")

_installed = False


# -- a DER walk to notAfter, stdlib only (the vendor build has no cryptography)


def _read_tlv(data: bytes, pos: int) -> tuple[int, int, int]:
    """-> (tag, start of value, end of value). Raises ValueError."""
    if pos + 2 > len(data):
        raise ValueError("truncated")
    tag = data[pos]
    length = data[pos + 1]
    pos += 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4 or pos + count > len(data):
            raise ValueError("bad length")
        length = int.from_bytes(data[pos:pos + count], "big")
        pos += count
    end = pos + length
    if end > len(data):
        raise ValueError("truncated value")
    return tag, pos, end


def _parse_time(tag: int, raw: bytes) -> datetime:
    text = raw.decode("ascii")
    if tag == 0x17:                                   # UTCTime YYMMDDHHMMSSZ
        year = int(text[:2])
        year += 2000 if year < 50 else 1900           # RFC 5280 4.1.2.5.1
        text = f"{year:04d}{text[2:]}"
    elif tag != 0x18:                                 # GeneralizedTime
        raise ValueError("not a time")
    if not text.endswith("Z"):
        raise ValueError("not UTC")
    return datetime.strptime(text[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def not_after(der: bytes) -> Optional[datetime]:
    """The certificate's notAfter, or None when it cannot be read."""
    try:
        tag, pos, _end = _read_tlv(der, 0)            # Certificate
        if tag != 0x30:
            return None
        tag, pos, tbs_end = _read_tlv(der, pos)       # TBSCertificate
        if tag != 0x30:
            return None
        if der[pos] == 0xA0:                          # [0] version, optional
            _t, _s, pos = _read_tlv(der, pos)
        for _field in ("serial", "signature", "issuer"):
            _t, _s, pos = _read_tlv(der, pos)
        tag, pos, _vend = _read_tlv(der, pos)         # Validity
        if tag != 0x30 or pos >= tbs_end:
            return None
        _t, _s, pos = _read_tlv(der, pos)             # notBefore
        tag, start, end = _read_tlv(der, pos)         # notAfter
        return _parse_time(tag, der[start:end])
    except Exception:  # noqa: BLE001 - unreadable: the caller keeps the cert
        return None


def is_expired(der: bytes, now: Optional[datetime] = None) -> bool:
    """True only for a certificate we can PROVE has expired."""
    when = not_after(der)
    if when is None:
        return False
    return when < (now or datetime.now(timezone.utc))


# -- the replacement loader --------------------------------------------------


def _make_loader(enum: Callable[[str], Any],
                 clock: Callable[[], datetime]) -> Callable[..., None]:
    def _load_windows_store_certs(self: ssl.SSLContext, storename: str, purpose: Any) -> None:
        skipped = 0
        try:
            for cert, encoding, trust in enum(storename):
                # CA certs are never PKCS#7 encoded (the stdlib's own note).
                if encoding != "x509_asn":
                    continue
                if not (trust is True or purpose.oid in trust):
                    continue
                if is_expired(cert, clock()):
                    skipped += 1
                    continue
                try:
                    self.load_verify_locations(cadata=cert)
                except ssl.SSLError as exc:
                    warnings.warn(f"Bad certificate in Windows certificate store: {exc!s}")
        except PermissionError:
            warnings.warn("unable to enumerate Windows certificate store")
        if skipped:
            log.debug("left %d expired certificate(s) out of the Windows %s store",
                      skipped, storename)
    return _load_windows_store_certs


def install(*, platform: Optional[str] = None,
            enum: Optional[Callable[[str], Any]] = None,
            clock: Optional[Callable[[], datetime]] = None) -> bool:
    """Patch the loader for this process. -> whether it is (now) in place."""
    global _installed
    if (sys.platform if platform is None else platform) != "win32":
        return False
    if _installed:
        return True
    try:
        if not hasattr(ssl.SSLContext, "_load_windows_store_certs"):
            log.warning("this Python has no SSLContext._load_windows_store_certs: "
                        "expired Windows certificates are still trusted (CR-350)")
            return False
        enum_fn = enum or getattr(ssl, "enum_certificates")
        ssl.SSLContext._load_windows_store_certs = _make_loader(  # type: ignore[method-assign]
            enum_fn, clock or (lambda: datetime.now(timezone.utc)))
        _installed = True
        return True
    except Exception:  # noqa: BLE001 - trust is the stdlib's as before
        log.debug("could not install the expired-certificate filter", exc_info=True)
        return False
