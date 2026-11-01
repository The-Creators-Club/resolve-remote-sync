#!/usr/bin/env python3
r"""Pin the appliance compose file's vendor images to an exact digest.

    python tools/pin_compose_images.py --version 0.7.74 \
        --dashboard-digest sha256:... --sftp-digest sha256:...
    python tools/pin_compose_images.py --check       # exit 1 while a vendor ref floats

GL-50 / GL-24 (CR-371, 2026-10-07). The owner's decision: customers are pinned
BY DIGEST, with the vendor's own studio soaking a build first. A customer's
compose that says `ccsync:1` re-resolves a MOVING tag on every pull, so a
tag push (or a stolen token) reaches every site unoffered. A reference of the
form `repo:<version>@sha256:<digest>` is immutable: the digest is what is
pulled, the version is only for the human reading the file. The release command
(tools/release_customers.py) runs this after the image build, from the digests
image.yml published, and the result is committed.

Only the two vendor images (CCSYNC_IMAGE, CCSYNC_SFTP_IMAGE) are touched; the
syncthing and tailscale pins are third-party and already exact.

Stdlib only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE = REPO_ROOT / "dashboard" / "deploy" / "compose.appliance.yaml"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# `"${CCSYNC_IMAGE:-ghcr.io/the-creators-club/ccsync}:1"` and the digest form.
_REF = re.compile(
    r'(?P<head>image:\s*"\$\{(?P<var>CCSYNC_IMAGE|CCSYNC_SFTP_IMAGE):-[^}"]+\})'
    r'(?P<tail>(?::[A-Za-z0-9._-]+)?(?:@sha256:[0-9a-f]{64})?)"')


class PinError(Exception):
    pass


def pin(text: str, *, version: str, dashboard_digest: str, sftp_digest: str) -> str:
    if not VERSION_RE.match(version):
        raise PinError(f"version {version!r} must look like 0.7.74 (an immutable tag)")
    for label, digest in (("dashboard", dashboard_digest), ("sftp", sftp_digest)):
        if not DIGEST_RE.match(digest):
            raise PinError(f"{label} digest {digest!r} must look like sha256:<64 hex>")
    digests = {"CCSYNC_IMAGE": dashboard_digest, "CCSYNC_SFTP_IMAGE": sftp_digest}

    def repl(m: re.Match) -> str:
        return f'{m.group("head")}:{version}@{digests[m.group("var")]}"'

    out, n = _REF.subn(repl, text)
    if n == 0:
        raise PinError("no CCSYNC_IMAGE / CCSYNC_SFTP_IMAGE image: line found to pin")
    return out


def unpinned(text: str) -> list[str]:
    """The vendor image references that do not carry a digest."""
    bad = []
    for m in _REF.finditer(text):
        if "@sha256:" not in m.group("tail"):
            bad.append(f'{m.group("var")}{m.group("tail") or " (no tag)"}')
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--compose", default=str(COMPOSE))
    ap.add_argument("--version", default="")
    ap.add_argument("--dashboard-digest", default="")
    ap.add_argument("--sftp-digest", default="")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any vendor image reference floats (no digest)")
    args = ap.parse_args(argv)
    path = Path(args.compose)
    text = path.read_text(encoding="utf-8")
    if args.check:
        bad = unpinned(text)
        if bad:
            print("[pin-compose] vendor images NOT pinned by digest: " + ", ".join(bad))
            return 1
        print("[pin-compose] every vendor image is pinned by digest")
        return 0
    try:
        new = pin(text, version=args.version, dashboard_digest=args.dashboard_digest,
                  sftp_digest=args.sftp_digest)
    except PinError as exc:
        print(f"[pin-compose] FAILED: {exc}", file=sys.stderr)
        return 2
    if new != text:
        path.write_text(new, encoding="utf-8", newline="")
    print(f"[pin-compose] {path.name} pinned to {args.version} ({args.dashboard_digest[:19]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
