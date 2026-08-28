#!/usr/bin/env python3
"""The offline release key: generate it, read its public half, bake that half
into the companion.

COMMERCIAL_READINESS.md item 4, 2026-08-17. The private key is the one secret
in this system that must never reach the NAS, the dashboard, a container, an
editor machine, or this repo. It lives in a file OUTSIDE the working tree --
%USERPROFILE%\\.ccsync-release\\release.key by default, 0600 -- and only
tools/sign_release.py ever reads it, on the release rig, at publish time.

    python tools/release_key.py new         # create it (refuses to clobber)
    python tools/release_key.py pubkey      # print the public half + its id
    python tools/release_key.py bake        # write the public half into the
                                            # companion's RELEASE_PUBKEYS
    python tools/release_key.py bake --add  # keep the existing keys (rotation)

Storage format is one line of base64 over the raw 32-byte Ed25519 seed, with
`#` comments allowed above it -- deliberately boring so it can be copied to
an offline medium, printed, or held in a password manager. There is no
passphrase: a passphrase that has to be typed at every ship gets written into
a script within a month. Protect the FILE (and back it up: losing it means
the fleet can never be offered another build until every companion is
reinstalled with a new baked key).
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import secrets
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# The companion's copy of the primitives is the one implementation; tools
# import it rather than carrying a third copy (see ed25519.py's docstring).
sys.path.insert(0, str(REPO_ROOT / "companion" / "src"))

from ccsync_companion import ed25519  # noqa: E402
from ccsync_companion import release_pubkey  # noqa: E402

DEFAULT_KEY_PATH = Path.home() / ".ccsync-release" / "release.key"
BAKE_TARGET = REPO_ROOT / "companion" / "src" / "ccsync_companion" / "release_pubkey.py"
_HEADER = "ccsync-release-key-v1"


def key_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("CCSYNC_RELEASE_KEY", "").strip()
    if env:
        return Path(env).expanduser()
    return DEFAULT_KEY_PATH


def read_secret(path: Path) -> bytes:
    """The raw 32-byte seed. Raises with an actionable message."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(
            f"no release key at {path} ({exc}).\n"
            f"Generate one:  python tools/release_key.py new\n"
            f"or point CCSYNC_RELEASE_KEY at the file you already have."
        )
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(_HEADER):
            line = line[len(_HEADER):].strip()
        try:
            raw = base64.b64decode(line, validate=True)
        except Exception:
            continue
        if len(raw) == 32:
            return raw
    raise SystemExit(f"{path} does not contain a 32-byte base64 ed25519 seed")


def write_secret(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "# CCSync release signing key -- PRIVATE. Never commit, never copy to the\n"
        "# NAS, the dashboard container, or an editor machine. Back it up offline:\n"
        "# without it no further build can be published to the fleet.\n"
        f"{_HEADER} {base64.b64encode(raw).decode('ascii')}\n"
    )
    # Create with 0600 from the start rather than chmod-after: on POSIX the
    # window between creating a world-readable file and tightening it is the
    # whole point of the permission. On Windows the mode bits are close to
    # meaningless (NTFS ACLs decide), which is why the path is under the
    # user profile in the first place.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, body.encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.chmod(str(path), stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def cmd_new(args) -> int:
    path = key_path(args.path)
    if path.exists():
        if not args.force:
            print(f"a release key already exists at {path} -- NOT overwriting it.")
            print("Overwriting it orphans every build the fleet was ever offered.")
            print("Pass --force only if you are deliberately starting a new key,")
            print("and read the rotation note in docs/RELEASE.md first.")
            return 1
        backup = path.with_suffix(path.suffix + ".superseded")
        path.replace(backup)
        print(f"moved the previous key aside: {backup}")
    raw = secrets.token_bytes(32)
    write_secret(path, raw)
    pub = base64.b64encode(ed25519.public_key(raw)).decode("ascii")
    print(f"wrote {path} (mode 0600)")
    print(f"public key : {pub}")
    print(f"pubkey_id  : {release_pubkey.pubkey_id(pub)}")
    print("")
    print("Next: python tools/release_key.py bake   (puts the PUBLIC half into")
    print("      companion/src/ccsync_companion/release_pubkey.py), then rebuild")
    print("      and ship -- companions only trust keys baked into their own binary.")
    return 0


def cmd_pubkey(args) -> int:
    raw = read_secret(key_path(args.path))
    pub = base64.b64encode(ed25519.public_key(raw)).decode("ascii")
    if args.quiet:
        print(pub)
        return 0
    print(f"public key : {pub}")
    print(f"pubkey_id  : {release_pubkey.pubkey_id(pub)}")
    print("")
    print("The dashboard verifies publishes against DASH_RELEASE_PUBKEYS")
    print("(comma-separated). Set it in the container env to exactly this value.")
    return 0


_TUPLE_RE = re.compile(
    r"(RELEASE_PUBKEYS:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\()(.*?)(\n\))",
    re.DOTALL,
)


def cmd_bake(args) -> int:
    raw = read_secret(key_path(args.path))
    pub = base64.b64encode(ed25519.public_key(raw)).decode("ascii")
    target = Path(args.target) if args.target else BAKE_TARGET
    text = target.read_text(encoding="utf-8")
    match = _TUPLE_RE.search(text)
    if not match:
        print(f"could not find RELEASE_PUBKEYS in {target} -- edit it by hand")
        return 1
    existing = re.findall(r'"([A-Za-z0-9+/=]{40,})"', match.group(2))
    keys = [pub] if not args.add else ([pub] + [k for k in existing if k != pub])
    if existing == keys:
        print(f"{target} already bakes exactly {pub} -- nothing to do")
        return 0
    body = "".join(f'\n    "{k}",' for k in keys)
    text = text[:match.start()] + match.group(1) + body + match.group(3) + text[match.end():]
    target.write_text(text, encoding="utf-8")
    print(f"baked {pub} ({release_pubkey.pubkey_id(pub)}) into {target}")
    if existing and not args.add:
        # Warning, not a refusal (REL-7, resilience sweep 2026-08-28): baking a
        # replacement is a legitimate thing to do BEFORE the first customer
        # ship, and refusing here would make that impossible. What was missing
        # is that the cost was never stated in the terms the operator will
        # meet it in -- the ship and publish_latest now refuse the PUBLISH
        # with the same sentence, which is the last moment it can be undone.
        print(f"REPLACED {len(existing)} previously trusted key(s): {', '.join(existing)}")
        print("EVERY MACHINE ON THE CURRENT BUILD WILL REFUSE THIS BUILD: a companion")
        print("trusts only the keys baked into the binary it is already running, the")
        print("refusal is silent, and the recovery is a hands-on reinstall per machine.")
        print("Use --add for a rotation: ship a build that trusts BOTH keys first, and")
        print("drop the old one a release later. The publish will refuse this without")
        print("-AllowKeyRotation / --allow-key-rotation (docs/RELEASE.md, key rotation).")
    print("Rebuild the companion (tools/release.ps1) -- the baked list only")
    print("changes for a machine once it installs a build containing it.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", default="", help="key file (default ~/.ccsync-release/release.key)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="generate a release key")
    p_new.add_argument("--force", action="store_true", help="replace an existing key")
    p_new.set_defaults(func=cmd_new)

    p_pub = sub.add_parser("pubkey", help="print the public half")
    p_pub.add_argument("--quiet", action="store_true", help="just the base64 key")
    p_pub.set_defaults(func=cmd_pubkey)

    p_bake = sub.add_parser("bake", help="write the public half into the companion")
    p_bake.add_argument("--add", action="store_true",
                        help="keep the keys already baked (rotation overlap)")
    p_bake.add_argument("--target", default="", help="file to edit (default release_pubkey.py)")
    p_bake.set_defaults(func=cmd_bake)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
