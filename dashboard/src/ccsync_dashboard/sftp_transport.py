"""Which rclone SFTP window the NAS's own sshd can serve (GL-10, CR-364,
2026-10-07).

DSM 7.2's OpenSSH 8.2 has no `limits@openssh.com`, so a lane-B download at the
companion's 255Ki x 64 TRUNCATES at 539,000,832 bytes while rclone reports
success: every proxy over 514 MiB arrives short on a green lane
(docs/synology-spikes-2026-08-17.md spike 6). Until now only comments
protected it and `site.example.toml` shipped the unsafe value.

The rule depends on WHICH sshd serves the lanes, not on `nas_kind` alone: the
appliance's own ccsync-sftp sidecar (OpenSSH 9.6) is fine at 255Ki, and its
dashboard runs with `vendor_defaults` on. A copy of the same numbers lives in
`server/common.py` for the deploy scripts (this container cannot import
server/); `server/tests` pins the two equal.
"""
from __future__ import annotations

import re
from typing import Any

SYNOLOGY_SAFE_CHUNK_BYTES = 64 * 1024
SYNOLOGY_SAFE_CHUNK = "64Ki"
SYNOLOGY_SAFE_CONCURRENCY = 16


def parse_size(raw: Any) -> int | None:
    """rclone's size syntax as bytes; None for blank or unparseable."""
    text = str(raw or "").strip().lower().replace(" ", "")
    if not text:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmgt]?)(i?b?)", text)
    if not m:
        return None
    mult = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}[m.group(2)]
    return int(float(m.group(1)) * mult)


def limited(nas_kind: Any, vendor_defaults: bool = False) -> bool:
    """True when the sshd that serves lanes A/B is DSM's own."""
    return str(nas_kind or "").strip().lower() == "synology" and not vendor_defaults


def problem(nas_kind: Any, chunk_size: Any, concurrency: Any,
            vendor_defaults: bool = False) -> str:
    """"" when safe, else a sentence naming what to set."""
    if not limited(nas_kind, vendor_defaults):
        return ""
    out = []
    size = parse_size(chunk_size)
    if str(chunk_size or "").strip() and size is None:
        out.append(f"sftp_chunk_size {chunk_size!r} is not a size (use \"64Ki\")")
    elif size is not None and size > SYNOLOGY_SAFE_CHUNK_BYTES:
        out.append(f"sftp_chunk_size {chunk_size!r} is above {SYNOLOGY_SAFE_CHUNK}: this "
                   "NAS's sshd silently cuts downloads over 514 MiB short at that size")
    try:
        conc = int(concurrency or 0)
    except (TypeError, ValueError):
        conc = 0
    if conc > SYNOLOGY_SAFE_CONCURRENCY:
        out.append(f"sftp_concurrency {conc} is above {SYNOLOGY_SAFE_CONCURRENCY}")
    return "; ".join(out)


def derive(nas_kind: Any, chunk_size: Any, concurrency: Any,
           vendor_defaults: bool = False) -> tuple[str, int]:
    """What the manifest publishes: the stored pair, with a BLANK on a limited
    NAS filled by the safe values, and anything above the limit lowered to
    them (a pre-existing bad row must stop hurting the fleet the moment this
    build serves the manifest; `problem` is what tells the admin).
    Companions older than this change read the same two keys, so nothing on
    the wire changes shape."""
    chunk = str(chunk_size or "").strip()
    try:
        conc = int(concurrency or 0)
    except (TypeError, ValueError):
        conc = 0
    if not limited(nas_kind, vendor_defaults):
        return chunk, conc
    size = parse_size(chunk)
    if not chunk or size is None or size > SYNOLOGY_SAFE_CHUNK_BYTES:
        chunk = SYNOLOGY_SAFE_CHUNK
    if conc <= 0 or conc > SYNOLOGY_SAFE_CONCURRENCY:
        conc = SYNOLOGY_SAFE_CONCURRENCY
    return chunk, conc
