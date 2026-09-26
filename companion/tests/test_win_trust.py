"""CR-350: expired certificates stay out of the trust Python builds on Windows.

The fixtures (inline below) are two real, public certificates from an editor's Windows
store (2026-09-26): the ISRG Root X2 cross-sign that expired 2025-09-16 and
broke his https reports, and the ISRG Root X1 root (valid to 2035). Nothing
here opens a socket or reads the machine's real stores: `enum` is injected.
"""

from __future__ import annotations

import ssl
from datetime import datetime, timezone

import pytest

from ccsync_companion import win_trust

# Inline, not a .pem file: the repo ignores *.pem (keys use that extension).
FIXTURES_PEM = """\n# isrg_x1_root_valid_2035 (public certificate, from an editor's Windows store 2026-09-26, CR-350)
-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAwTzELMAkGA1UE
BhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2VhcmNoIEdyb3VwMRUwEwYDVQQD
EwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQG
EwJVUzEpMCcGA1UEChMgSW50ZXJuZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMT
DElTUkcgUm9vdCBYMTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54r
Vygch77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+0TM8ukj1
3Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6UA5/TR5d8mUgjU+g4rk8K
b4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sWT8KOEUt+zwvo/7V3LvSye0rgTBIlDHCN
Aymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyHB5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ
4Q7e2RCOFvu396j3x+UCB5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf
1b0SHzUvKBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWnOlFu
hjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTnjh8BCNAw1FtxNrQH
usEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbwqHyGO0aoSCqI3Haadr8faqU9GY/r
OPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CIrU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4G
A1UdDwEB/wQEAwIBBjAPBgNVHRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY
9umbbjANBgkqhkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL
ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ3BebYhtF8GaV
0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KKNFtY2PwByVS5uCbMiogziUwt
hDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJw
TdwJx4nLCgdNbOhdjsnvzqvHu7UrTkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nx
e5AW0wdeRlN8NwdCjNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZA
JzVcoyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq4RgqsahD
YVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPAmRGunUHBcnWEvgJBQl9n
JEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57demyPxgcYxn/eR44/KJ4EBs+lVDR3veyJ
m+kXQ99b21/+jh5Xos1AnX5iItreGCc=
-----END CERTIFICATE-----
# isrg_x2_cross_expired_2025-09-16 (public certificate, from an editor's Windows store 2026-09-26, CR-350)
-----BEGIN CERTIFICATE-----
MIIEYDCCAkigAwIBAgIQB55JKIY3b9QISMI/xjHkYzANBgkqhkiG9w0BAQsFADBPMQswCQYDVQQG
EwJVUzEpMCcGA1UEChMgSW50ZXJuZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMT
DElTUkcgUm9vdCBYMTAeFw0yMDA5MDQwMDAwMDBaFw0yNTA5MTUxNjAwMDBaME8xCzAJBgNVBAYT
AlVTMSkwJwYDVQQKEyBJbnRlcm5ldCBTZWN1cml0eSBSZXNlYXJjaCBHcm91cDEVMBMGA1UEAxMM
SVNSRyBSb290IFgyMHYwEAYHKoZIzj0CAQYFK4EEACIDYgAEzZvVn4CDCuwJSvMWSj5cz3es3mcF
DR0HttwW+1qLFNvicWDEukWVEYmO6gbf9yoWHKS5xcUy4APgHoIYOIvXRdgKam7mAHf7AlF9ItgK
bppbd9/w+kHsOdx1ymgHDB/qo4HlMIHiMA4GA1UdDwEB/wQEAwIBBjAPBgNVHRMBAf8EBTADAQH/
MB0GA1UdDgQWBBR8Qpau3ktIO/qS+J6Mz22LqXI3lTAfBgNVHSMEGDAWgBR5tFnme7bl5AFzgAiI
yBpY9umbbjAyBggrBgEFBQcBAQQmMCQwIgYIKwYBBQUHMAKGFmh0dHA6Ly94MS5pLmxlbmNyLm9y
Zy8wJwYDVR0fBCAwHjAcoBqgGIYWaHR0cDovL3gxLmMubGVuY3Iub3JnLzAiBgNVHSAEGzAZMAgG
BmeBDAECATANBgsrBgEEAYLfEwEBATANBgkqhkiG9w0BAQsFAAOCAgEAG38lK5B6CHYAdxjhwy6K
NkxBfr8XS+Mw11sMfpyWmG97sGjAJETM4vL80erb0p8B+RdNDJ1V/aWtbdIvP0tywC6uc8clFlfC
PhWt4DHRCoSEbGJ4QjEiRhrtekC/lxaBRHfKbHtdIVwH8hGRIb/hL8Lvbv0FIOS093nzLbs3KvDG
saysUfUfs1oeZs5YBxg4f3GpPIO617yCnpp2D56wKf3L84kHSBv+q5MuFCENX6+Ot1SrXQ7UW0xx
0JLqPaM2m3wf4DtVudhTU8yDZrtK3IEGABiL9LPXSLETQbnEtp7PLHeOQiALgH6fxatI27xvBI1s
RikCDXCKHfESc7ZGJEKeKhcY46zHmMJyzG0tdm3dLCsmlqXPIQgb5dovy++fc5Ou+DZfR4+XKM6r
4pgmmIv97igyIintTJUJxCD6B+GGLET2gUfA5GIy7R3YPEiIlsNekbave1mk7uOGnMeIWMooKmZV
m4WAuR3YQCvJHBM8qevemcIWQPb1pK4qJWxSuscETLQyu/w4XKAMYXtX7HdOUM+vBqIPN4zhDtLT
Lxq9nHE+zOH40aijvQT2GcD5hq/1DhqqlWvvykdxS2McTZbbVSMKnQ+BdaDmQPVkRgNuzvpqfQbs
pDQGdNpT2Lm4xiN9qfgqLaSCpi4tEcrmzTFYeYXmchynn9NM0GbQp7s=
-----END CERTIFICATE-----
"""
NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


def _certs() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    name, lines = "", []
    for line in FIXTURES_PEM.splitlines():
        if line.startswith("# "):
            name = line[2:].split(" ")[0]
        elif line.startswith("-----BEGIN"):
            lines = [line]
        elif lines:
            lines.append(line)
            if line.startswith("-----END"):
                out[name] = ssl.PEM_cert_to_DER_cert("\n".join(lines) + "\n")
                lines = []
    return out


CERTS = _certs()
EXPIRED = CERTS["isrg_x2_cross_expired_2025-09-16"]
VALID = CERTS["isrg_x1_root_valid_2035"]


def test_not_after_reads_real_certificates():
    assert win_trust.not_after(VALID) == datetime(2035, 6, 4, 11, 4, 38, tzinfo=timezone.utc)
    assert win_trust.not_after(EXPIRED).date().isoformat() == "2025-09-15"


def test_only_a_provably_expired_certificate_is_expired():
    assert win_trust.is_expired(EXPIRED, NOW) is True
    assert win_trust.is_expired(VALID, NOW) is False
    # Unreadable is KEPT: a parser gap must never shrink trust.
    for junk in (b"", b"\x30", b"\x30\x03\x02\x01\x01", b"not der at all", VALID[:40]):
        assert win_trust.is_expired(junk, NOW) is False


class _Ctx:
    def __init__(self) -> None:
        self.loaded: list[bytes] = []

    def load_verify_locations(self, cadata=None):
        self.loaded.append(cadata)


def _loader(stores):
    return win_trust._make_loader(lambda name: iter(stores.get(name, [])), lambda: NOW)


def test_the_loader_leaves_expired_certificates_out_and_keeps_the_rest():
    ctx = _Ctx()
    _loader({"CA": [(EXPIRED, "x509_asn", True)],
             "ROOT": [(VALID, "x509_asn", True)]})(ctx, "CA", ssl.Purpose.SERVER_AUTH)
    assert ctx.loaded == []
    _loader({"ROOT": [(VALID, "x509_asn", True)]})(ctx, "ROOT", ssl.Purpose.SERVER_AUTH)
    assert ctx.loaded == [VALID]


def test_the_loader_keeps_the_stdlib_rules_for_everything_else():
    """Same trust-purpose test and encoding test as ssl.py's own loop."""
    ctx = _Ctx()
    _loader({"ROOT": [
        (VALID, "pkcs_7_asn", True),                                   # never a CA cert
        (VALID, "x509_asn", {"1.3.6.1.5.5.7.3.4"}),                     # email only
        (VALID, "x509_asn", {ssl.Purpose.SERVER_AUTH.oid}),              # server auth
    ]})(ctx, "ROOT", ssl.Purpose.SERVER_AUTH)
    assert ctx.loaded == [VALID]


def test_a_real_context_built_through_the_loader_trusts_only_the_valid_one():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    loader = _loader({"CA": [(EXPIRED, "x509_asn", True)],
                      "ROOT": [(VALID, "x509_asn", True)]})
    for store in ("CA", "ROOT"):
        loader(ctx, store, ssl.Purpose.SERVER_AUTH)
    names = [dict(x[0] for x in c["subject"])["commonName"] for c in ctx.get_ca_certs()]
    assert names == ["ISRG Root X1"]


def test_install_is_windows_only(monkeypatch):
    monkeypatch.setattr(win_trust, "_installed", False)
    before = getattr(ssl.SSLContext, "_load_windows_store_certs", None)
    assert win_trust.install(platform="darwin") is False
    assert getattr(ssl.SSLContext, "_load_windows_store_certs", None) is before


def test_install_replaces_the_stdlib_loader_once(monkeypatch):
    if not hasattr(ssl.SSLContext, "_load_windows_store_certs"):
        pytest.skip("this Python has no Windows store loader")
    monkeypatch.setattr(win_trust, "_installed", False)
    monkeypatch.setattr(ssl.SSLContext, "_load_windows_store_certs",
                        ssl.SSLContext._load_windows_store_certs)
    assert win_trust.install(platform="win32", enum=lambda name: iter(())) is True
    patched = ssl.SSLContext._load_windows_store_certs
    assert patched.__name__ == "_load_windows_store_certs"
    assert win_trust.install(platform="win32") is True
    assert ssl.SSLContext._load_windows_store_certs is patched
