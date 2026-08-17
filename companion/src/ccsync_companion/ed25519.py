"""Pure-Python Ed25519 (RFC 8032), used to verify signed release records.

WHY PURE PYTHON, AND WHY A COPY IN TWO PACKAGES (2026-08-17, COMMERCIAL_
READINESS.md item 4):

The companion is a frozen PyInstaller binary that RENAMES A DOWNLOADED FILE
OVER ITSELF AND EXECUTES IT. Whatever verifies that download has to be inside
the binary, on every platform, with no wheel to install and nothing for
PyInstaller to fail to collect. `cryptography` would add a compiled OpenSSL
backend (~8 MB, a second signature surface, and a hook that has broken across
PyInstaller majors before); `pynacl` the same with libsodium. Verifying one
64-byte signature over a ~250-byte record costs ~15 ms here, once per upgrade
OFFER -- not per report -- so the cost of the pure-Python route is invisible
and the cost of the dependency is not.

This file is byte-identical to dashboard/src/ccsync_dashboard/ed25519.py on
purpose. They are three deployment units (the frozen companion, the NAS
container, and the base rig's tools/ which imports the companion copy) and
none of them can import the others, so the code is duplicated and pinned:
companion/tests/test_upgrade.py compares the two files and fails on drift.
Do not "refactor" one copy without the other.

The implementation is the reference one from RFC 8032 section 6, kept close
to the RFC so it can be diffed against the spec. It is NOT constant-time --
it does not need to be: it only ever touches PUBLIC keys and PUBLIC
signatures. The private half never comes near a fleet machine (it lives
offline at %USERPROFILE%\\.ccsync-release\\release.key on the release rig);
sign() exists here only so the two copies stay identical and so tools/ has
one implementation to import.
"""
from __future__ import annotations

import hashlib

# Curve parameters (RFC 8032 §5.1).
p = 2 ** 255 - 19
q = 2 ** 252 + 27742317777372353535851937790883648493


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _modp_inv(x: int) -> int:
    return pow(x, p - 2, p)


# d = -121665/121666, and the square root of -1.
_d = -121665 * _modp_inv(121666) % p
_modp_sqrt_m1 = pow(2, (p - 1) // 4, p)


def _recover_x(y: int, sign: int) -> int | None:
    """The x matching a compressed point's y and sign bit, or None."""
    if y >= p:
        return None
    x2 = (y * y - 1) * _modp_inv(_d * y * y + 1)
    if x2 == 0:
        if sign:
            return None
        return 0
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p != 0:
        x = x * _modp_sqrt_m1 % p
    if (x * x - x2) % p != 0:
        return None
    if (x & 1) != sign:
        x = p - x
    return x


# Points are (X, Y, Z, T) in extended homogeneous coordinates: x = X/Z, y = Y/Z,
# x*y = T/Z.
_g_y = 4 * _modp_inv(5) % p
_g_x = _recover_x(_g_y, 0)
G = (_g_x, _g_y, 1, _g_x * _g_y % p)


def _point_add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % p
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % p
    C = 2 * P[3] * Q[3] * _d % p
    D = 2 * P[2] * Q[2] % p
    E, F, G_, H = B - A, D - C, D + C, B + A
    return (E * F, G_ * H, F * G_, E * H)


def _point_mul(s: int, P):
    Q = (0, 1, 1, 0)  # the neutral element
    while s > 0:
        if s & 1:
            Q = _point_add(Q, P)
        P = _point_add(P, P)
        s >>= 1
    return Q


def _point_equal(P, Q) -> bool:
    if (P[0] * Q[2] - Q[0] * P[2]) % p != 0:
        return False
    if (P[1] * Q[2] - Q[1] * P[2]) % p != 0:
        return False
    return True


def _point_compress(P) -> bytes:
    zinv = _modp_inv(P[2])
    x = P[0] * zinv % p
    y = P[1] * zinv % p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _point_decompress(s: bytes):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % p)


def _sha512_modq(data: bytes) -> int:
    return int.from_bytes(_sha512(data), "little") % q


def _secret_expand(secret: bytes):
    if len(secret) != 32:
        raise ValueError("an ed25519 private key is exactly 32 bytes")
    h = _sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= (1 << 254)
    return (a, h[32:])


def public_key(secret: bytes) -> bytes:
    """The 32-byte public key for a 32-byte private key."""
    a, _ = _secret_expand(secret)
    return _point_compress(_point_mul(a, G))


def sign(secret: bytes, msg: bytes) -> bytes:
    """A 64-byte detached signature. Release-tooling only -- see the module
    docstring: no fleet machine ever holds the private half."""
    a, prefix = _secret_expand(secret)
    A = _point_compress(_point_mul(a, G))
    r = _sha512_modq(prefix + msg)
    R = _point_mul(r, G)
    Rs = _point_compress(R)
    h = _sha512_modq(Rs + A + msg)
    s = (r + h * a) % q
    return Rs + int.to_bytes(s, 32, "little")


def verify(public: bytes, msg: bytes, signature: bytes) -> bool:
    """True iff `signature` is a valid Ed25519 signature of `msg` under
    `public`. NEVER RAISES: every malformed input is simply False. The one
    caller that matters decides whether to overwrite a running binary, and a
    TypeError escaping into that decision is not a safe failure mode."""
    try:
        if len(public) != 32 or len(signature) != 64:
            return False
        A = _point_decompress(public)
        if A is None:
            return False
        Rs = signature[:32]
        R = _point_decompress(Rs)
        if R is None:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= q:
            return False
        h = _sha512_modq(Rs + public + msg)
        sB = _point_mul(s, G)
        hA = _point_mul(h, A)
        return _point_equal(sB, _point_add(R, hA))
    except Exception:
        return False
