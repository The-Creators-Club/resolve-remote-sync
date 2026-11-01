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
    python tools/release_key.py trusted     # every public half this rig's dashboard
                                            # must trust (a rotation keeps two)
    python tools/release_key.py bake        # write the public half into the
                                            # companion's RELEASE_PUBKEYS
    python tools/release_key.py bake --add  # keep the existing keys (rotation)
    python tools/release_key.py backup --to D:/release.key     # a copy, offline
    python tools/release_key.py backup --print                 # for a password manager

    python tools/release_key.py encrypt     # one-time: passphrase-protect the key in place
    python tools/release_key.py status      # encrypted | plaintext | missing (no passphrase)

Two storage formats, each one line behind `#` comments:

  v1 (plaintext): `ccsync-release-key-v1 <base64 of the 32-byte Ed25519 seed>`.
  v2 (encrypted, GL-17 / GL-42 beta decision, CR-378, 2026-10-07):
     `ccsync-release-key-v2 <base64 of a JSON envelope>` holding the PUBLIC key
     in the clear (so pubkey / trusted / bake / the release rig's probes never
     need the passphrase), a scrypt salt + cost, and the seed encrypted with
     an encrypt-then-MAC construction over keys scrypt derives from the
     passphrase. Stdlib only on purpose: the release rig's interpreters do
     not all carry `cryptography`, and the release tooling must not grow a
     dependency for this (docs/RELEASE.md, lockfile procedure). The seed is one
     32-byte message under a fresh random salt per file, which is the case the
     HMAC-SHA256 counter keystream + HMAC-SHA256 tag is sound for.

A plaintext key still loads, and says so loudly on stderr every run. The
passphrase is asked ONCE per process (getpass, never echoed); a release run
spans several processes, so tools/ship.ps1 asks once and hands the children
CCSYNC_RELEASE_KEY_PASSPHRASE for that run only (docs/SECRETS.md). It is never
printed or logged. Losing the FILE or the PASSPHRASE is losing the key: the
fleet can never be offered another build until every companion is reinstalled
with a new baked key (docs/RELEASE.md, "Encrypting the release key").
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import sys
import unicodedata
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


# ---- the encrypted format (CR-378) ---------------------------------------

_HEADER_ENC = "ccsync-release-key-v2"
PASSPHRASE_ENV = "CCSYNC_RELEASE_KEY_PASSPHRASE"
MIN_PASSPHRASE = 12
# 2**17 * 8 * 128 B = 128 MiB, ~0.3 s: cheap to the owner, ruinous to a
# guesser. Stored in the file, so raising it later does not strand old files.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 17, 8, 1

_passphrase_cache: dict[str, str] = {}
_warned_plaintext: set[str] = set()


def _norm_pass(passphrase: str) -> bytes:
    return unicodedata.normalize("NFC", passphrase).encode("utf-8")


def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> tuple[bytes, bytes]:
    keys = hashlib.scrypt(_norm_pass(passphrase), salt=salt, n=n, r=r, p=p,
                          dklen=64, maxmem=n * r * 160 + (1 << 20))
    return keys[:32], keys[32:]


def _keystream_xor(enc_key: bytes, nonce: bytes, data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 32):
        block = hmac.new(enc_key, nonce + (i // 32).to_bytes(8, "big"),
                         hashlib.sha256).digest()
        out += bytes(x ^ y for x, y in zip(data[i:i + 32], block))
    return bytes(out)


def _aad(env: dict) -> bytes:
    return "|".join(str(env[k]) for k in ("v", "n", "r", "p", "salt", "nonce", "pub")).encode()


def encrypt_seed(raw: bytes, passphrase: str, n: int | None = None) -> str:
    """The v2 line (without comments) for `raw` under `passphrase`."""
    n = n or SCRYPT_N
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(16)
    enc_key, mac_key = _derive(passphrase, salt, n, SCRYPT_R, SCRYPT_P)
    env = {
        "v": 2, "n": n, "r": SCRYPT_R, "p": SCRYPT_P,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "pub": base64.b64encode(ed25519.public_key(raw)).decode("ascii"),
    }
    ct = _keystream_xor(enc_key, nonce, raw)
    env["ct"] = base64.b64encode(ct).decode("ascii")
    env["tag"] = base64.b64encode(
        hmac.new(mac_key, _aad(env) + ct, hashlib.sha256).digest()).decode("ascii")
    blob = base64.b64encode(json.dumps(env, sort_keys=True).encode("ascii")).decode("ascii")
    return f"{_HEADER_ENC} {blob}"


def _parse_envelope(line: str) -> dict:
    env = json.loads(base64.b64decode(line[len(_HEADER_ENC):].strip(), validate=True))
    if not isinstance(env, dict) or env.get("v") != 2:
        raise ValueError("unknown envelope version")
    return env


def decrypt_seed(env: dict, passphrase: str) -> bytes:
    """Raises ValueError on a wrong passphrase OR a tampered file (one answer:
    the MAC cannot tell them apart, and must not)."""
    n, r, p = int(env["n"]), int(env["r"]), int(env["p"])
    if n > 2 ** 22 or r > 32 or p > 8:      # a file must not pick our memory bill
        raise ValueError("implausible scrypt cost in the key file")
    salt = base64.b64decode(env["salt"])
    nonce = base64.b64decode(env["nonce"])
    ct = base64.b64decode(env["ct"])
    enc_key, mac_key = _derive(passphrase, salt, n, r, p)
    want = hmac.new(mac_key, _aad(env) + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(want, base64.b64decode(env["tag"])):
        raise ValueError("wrong passphrase, or the key file was altered")
    raw = _keystream_xor(enc_key, nonce, ct)
    if len(raw) != 32 or base64.b64encode(ed25519.public_key(raw)).decode("ascii") != env["pub"]:
        raise ValueError("decrypted seed does not match the recorded public key")
    return raw


def _read_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(
            f"no release key at {path} ({exc}).\n"
            f"Generate one:  python tools/release_key.py new\n"
            f"or point CCSYNC_RELEASE_KEY at the file you already have."
        )
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def _find_envelope(path: Path) -> dict | None:
    for line in _read_lines(path):
        if line.startswith(_HEADER_ENC):
            try:
                return _parse_envelope(line)
            except Exception:
                raise SystemExit(f"{path} looks like an encrypted release key but is damaged "
                                 f"-- restore it from your offline backup")
    return None


def is_encrypted(path: Path) -> bool:
    return _find_envelope(path) is not None


def _has_console() -> bool:
    """isatty() is True for NUL on Windows, and getpass then blocks on
    msvcrt with no console; ask the console device itself."""
    if not sys.stdin or not sys.stdin.isatty():
        return False
    if os.name == "nt":
        try:
            import ctypes
            mode = ctypes.c_uint32()
            h = ctypes.windll.kernel32.GetStdHandle(-10)   # STD_INPUT_HANDLE
            if not ctypes.windll.kernel32.GetConsoleMode(h, ctypes.byref(mode)):
                return False
        except Exception:
            return False
    return True


def ask_passphrase(path: Path, *, confirm: bool = False) -> str:
    """Once per process per file. Env first (ship.ps1 / an unattended run on
    this rig), then the terminal. Never echoed, never logged."""
    key = str(path)
    if key in _passphrase_cache and not confirm:
        return _passphrase_cache[key]
    given = os.environ.get(PASSPHRASE_ENV, "") if not confirm else ""
    if given:
        _passphrase_cache[key] = given
        return given
    if not _has_console():
        raise SystemExit(
            f"{path} is passphrase-protected and there is no terminal to ask on. "
            f"Run from an interactive terminal (tools\\ship.cmd asks once), or set "
            f"{PASSPHRASE_ENV} for this run only (docs/SECRETS.md).")
    first = getpass.getpass(f"release key passphrase for {path.name}: ")
    if confirm:
        if getpass.getpass("type it again: ") != first:
            raise SystemExit("the two passphrases differ -- nothing was changed")
    _passphrase_cache[key] = first
    return first


def read_secret(path: Path, warn: bool = True) -> bytes:
    """The raw 32-byte seed. Raises with an actionable message. Encrypted keys
    ask for the passphrase (once per process); a plaintext key loads but warns."""
    lines = _read_lines(path)
    env = _find_envelope(path)
    if env is not None:
        try:
            return decrypt_seed(env, ask_passphrase(path))
        except ValueError as exc:
            _passphrase_cache.pop(str(path), None)
            raise SystemExit(f"cannot unlock {path}: {exc}")
    for line in lines:
        if line.startswith(_HEADER):
            line = line[len(_HEADER):].strip()
        try:
            raw = base64.b64decode(line, validate=True)
        except Exception:
            continue
        if len(raw) == 32:
            if warn and str(path) not in _warned_plaintext:
                _warned_plaintext.add(str(path))
                print(f"WARNING: the release key {path} is UNENCRYPTED. Anyone who can read "
                      f"that file can publish a build every editor's computer runs. Protect "
                      f"it now:  python tools/release_key.py encrypt", file=sys.stderr)
            return raw
    raise SystemExit(f"{path} does not contain a 32-byte base64 ed25519 seed")


def unlock_for_run(path: Path) -> bool:
    """Ask ONCE, check it, and export it to this process's children.

    A release run is several processes (sign_release, publish_feed ...), each
    of which would otherwise prompt. Called at the top of a run (publish_latest
    preflight); tools/ship.ps1 does the same in PowerShell. A wrong passphrase
    fails HERE, before anything is built or uploaded. Returns True when the key
    is encrypted. The value lives in this process's environment only."""
    if not path.exists() or not is_encrypted(path):
        return False
    read_secret(path)                      # prompts / checks / may SystemExit
    os.environ[PASSPHRASE_ENV] = _passphrase_cache[str(path)]
    return True


def read_public(path: Path) -> bytes:
    """The raw public key. An encrypted key carries it in the clear, so this
    never asks for the passphrase; a plaintext one derives it."""
    env = _find_envelope(path)
    if env is not None:
        return base64.b64decode(env["pub"])
    # CR-378 round 2 (2026-10-07): no warning here. release.ps1's key-parity
    # probe runs `pubkey` under EAP=Stop, where ANY stderr is a terminating
    # NativeCommandError; only the signing path warns.
    return ed25519.public_key(read_secret(path, warn=False))


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
    # logic-release-1 (2026-09-24): the runbook's rotation used to start with
    # `new --force`, which is THIS branch: the new key lands at the path every
    # signer reads, so the "overlap" build that followed was signed by a key
    # the fleet did not trust yet, and the publish refusal then invited the
    # override. A rotation now generates the new key at a SIDE path, and this
    # says so at the one moment the wrong order can still be undone.
    signer = key_path("")      # what sign_release/publish_feed will read
    if args.force and path == signer:
        print("THE NEW KEY NOW SIGNS EVERYTHING. If this is a ROTATION, that is the")
        print("wrong order: the overlap release must be signed by the OLD key. Put it")
        print(f"back now (move {path.name}.superseded over {path.name}) and follow")
        print("docs/RELEASE.md \"Rotating\", which makes the new key at a side path.")
        print("")
    if path != signer and signer.exists():
        print("A SIDE key: nothing signs with it yet. For a rotation (docs/RELEASE.md):")
        print(f"  python tools/release_key.py --path \"{path}\" bake --add")
        print(f"then ship as usual; {signer} (the OLD key) signs the overlap build.")
        print("")
    elif not (args.force and path == signer):
        # logic-release-1 review (2026-09-24): after the warning above, a
        # "Next: bake" (no --add) is the stranding step itself, printed as an
        # instruction to someone who has just been told to undo this. The
        # one legitimate --force (starting over before anything shipped) is
        # in the runbook and does not need the prompt.
        print("Next: python tools/release_key.py bake   (puts the PUBLIC half into")
        print("      companion/src/ccsync_companion/release_pubkey.py), then rebuild")
        print("      and ship -- companions only trust keys baked into their own binary.")
        print("")
    # REL-14 (usability sweep 2026-09-04): the same voice `bake` uses for a
    # replaced key, because this is the same fact seen from the other end.
    # Losing these 32 bytes is unrecoverable for every fleet that exists, and
    # the strongest statement of that used to be line 668 of a 1200-line
    # runbook. Not a refusal and not a prompt: `new` runs once, on a rig with
    # no key, and stopping to ask a question there helps nobody.
    print("THEN PROTECT IT:  python tools/release_key.py encrypt   (passphrase; CR-378)")
    print("BACK IT UP NOW. This file is 32 bytes on one profile on one computer.")
    print("If it is lost, no fleet anywhere can ever be offered another build: every")
    print("companion trusts only the keys baked into the binary it is running, and the")
    print("recovery is a hands-on reinstall on every machine.")
    print("  python tools/release_key.py backup --to <path on a USB stick or a vault>")
    print("  python tools/release_key.py backup --print    (paste into a password manager)")
    return 0


BACKUP_RECORD_NAME = "backup.json"


def backup_record_path(path: Path) -> Path:
    """`backed_up_at` lives BESIDE the key, not inside it: the key file's
    format is one line of base64 that gets copied to an offline medium and
    read back by read_secret, and a JSON blob in it would break every copy
    anybody has already made."""
    # logic-release-1 review (2026-09-24): the rotation's side key
    # (`release-next.key`) lives in the same directory as the signing key, and
    # one shared `backup.json` meant backing up the side key overwrote the
    # signing key's record with another key's id. The signing key keeps the
    # plain name (ship.ps1 reads it by that path); any other key file gets its
    # own `<name>.backup.json`.
    if path.name == DEFAULT_KEY_PATH.name:
        return path.parent / BACKUP_RECORD_NAME
    return path.parent / f"{path.name}.{BACKUP_RECORD_NAME}"


def read_backup_record(path: Path) -> dict:
    try:
        import json

        data = json.loads(backup_record_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _record_backup(path: Path, where: str) -> None:
    import datetime
    import json

    record = {
        "backed_up_at": datetime.datetime.now(datetime.timezone.utc)
                                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "where": where,
        "pubkey_id": "",
    }
    try:
        record["pubkey_id"] = release_pubkey.pubkey_id(
            base64.b64encode(read_public(path)).decode("ascii"))
    except SystemExit:
        pass
    try:
        backup_record_path(path).write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        print("NOTE: could not record the backup date beside the key -- the copy "
              "itself is what matters.")


def cmd_backup(args) -> int:
    """Copy the key somewhere the owner keeps it, and record that it happened.

    NO PASSPHRASE WRAP, deliberately (REL-14, usability sweep 2026-09-04). The
    in-tree crypto is `ccsync_companion.ed25519`, which signs and verifies and
    does not encrypt; a scrypt+XOR construction written here would be homemade
    cryptography protecting the one secret in this product that must never be
    guessable, and adding a dependency to the release tooling for it is worse
    than the problem. What actually protects a non-technical owner is a copy
    they will really make -- a printed base64 line in a password manager, or a
    file on a USB stick in a drawer -- so that is what this writes, and it says
    plainly that the copy IS the key.
    """
    path = key_path(args.path)
    if is_encrypted(path):
        # CR-378: an encrypted key is backed up as the ENCRYPTED file, byte for
        # byte: no passphrase needed, and a lost USB stick is not a lost key.
        return _backup_encrypted(path, args)
    raw = read_secret(path, warn=False)
    line = base64.b64encode(raw).decode("ascii")
    if args.print_only:
        print("")
        print("THIS LINE IS THE PRIVATE KEY. Anyone holding it can publish a build every")
        print("editor's companion trusts and runs at logon. Paste it into a password")
        print("manager, then clear this terminal's scrollback.")
        print("")
        print(f"{_HEADER} {line}")
        print("")
        _record_backup(path, "printed for a password manager")
    else:
        dest = Path(args.to).expanduser()
        if dest.is_dir():
            dest = dest / path.name
        if dest.exists() and not args.force:
            print(f"{dest} already exists -- NOT overwriting it. Pass --force if that "
                  f"copy is stale.")
            return 1
        try:
            # O_EXCL in write_secret is what makes the --force path need this:
            # the point of that flag is that a key file is never created
            # world-readable, and an overwrite the operator asked for is a
            # different question from a clobber they did not.
            if args.force:
                dest.unlink(missing_ok=True)
            write_secret(dest, raw)
        except OSError as exc:
            print(f"could not write {dest}: {exc}")
            return 1
        print(f"wrote {dest}")
        print("THAT FILE IS THE PRIVATE KEY, not an encrypted backup: keep it offline "
              "(a USB stick in a drawer, a safe), never on the NAS, never in this repo,")
        print("never in a cloud folder that syncs to a machine an editor uses.")
        _record_backup(path, str(dest))
    print("")
    # The protection page's `release_key_backup` line is an ADMIN-SESSION htmx
    # form (ui.partial_admin_protection_ack) with no JSON twin, and this script
    # has no dashboard credential and no business acquiring one. So it prints
    # the instruction rather than posting it.
    print("Record it on the dashboard so the PROTECTION page turns green:")
    print("  SETTINGS > PROTECTION > [ I HAVE BACKED IT UP ], with today's date.")
    return 0


def _backup_encrypted(path: Path, args) -> int:
    body = path.read_text(encoding="utf-8")
    if args.print_only:
        print("")
        print("This is the ENCRYPTED key line. It is useless without the passphrase, so")
        print("keep the passphrase written down in a DIFFERENT place.")
        print("")
        print(next(ln for ln in body.splitlines() if ln.startswith(_HEADER_ENC)))
        print("")
        _record_backup(path, "printed for a password manager")
    else:
        dest = Path(args.to).expanduser()
        if dest.is_dir():
            dest = dest / path.name
        if dest.exists() and not args.force:
            print(f"{dest} already exists -- NOT overwriting it. Pass --force if that "
                  f"copy is stale.")
            return 1
        try:
            if args.force:
                dest.unlink(missing_ok=True)
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(dest), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, body.encode("utf-8"))
            finally:
                os.close(fd)
        except OSError as exc:
            print(f"could not write {dest}: {exc}")
            return 1
        print(f"wrote {dest} (encrypted; keep it offline, and the passphrase elsewhere)")
        _record_backup(path, str(dest))
    print("")
    print("Record it on the dashboard so the PROTECTION page turns green:")
    print("  SETTINGS > PROTECTION > [ I HAVE BACKED IT UP ], with today's date.")
    return 0


def cmd_check(args) -> int:
    """Decrypt (asking once, or from the env) and exit 0/1. No output of the
    secret. ship.ps1 calls it right after its prompt so a typo stops the run
    before step 1 deploys anything."""
    path = key_path(args.path)
    if not path.exists():
        print("missing")
        return 1
    try:
        read_secret(path, warn=False)
    except SystemExit as exc:
        print(str(exc.code), file=sys.stderr)
        return 1
    print("ok")
    return 0


def cmd_status(args) -> int:
    path = key_path(args.path)
    if not path.exists():
        print("missing")
        return 1
    print("encrypted" if is_encrypted(path) else "plaintext")
    return 0


def _scrub(path: Path) -> None:
    """Best-effort overwrite of a plaintext file before it is replaced. On an
    SSD or a journalling filesystem this is not a guarantee -- the docs say
    so and tell the owner to destroy old plaintext USB copies."""
    try:
        size = path.stat().st_size
        with open(path, "r+b") as fh:
            fh.write(secrets.token_bytes(max(size, 1)))
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass


def cmd_encrypt(args) -> int:
    path = key_path(args.path)
    if is_encrypted(path):
        print(f"{path} is already encrypted -- nothing to do.")
        return 0
    seed = read_secret(path)
    pub = ed25519.public_key(seed)
    passphrase = ask_passphrase(path, confirm=True)
    if len(passphrase) < MIN_PASSPHRASE:
        print(f"passphrase too short (minimum {MIN_PASSPHRASE} characters; a sentence is best). "
              f"Nothing was changed.")
        return 1
    line = encrypt_seed(seed, passphrase)
    tmp = path.with_name(path.name + ".enc.tmp")
    tmp.unlink(missing_ok=True)
    body = (
        "# CCSync release signing key -- PRIVATE, PASSPHRASE-PROTECTED (CR-378).\n"
        "# Without BOTH this file and its passphrase no further build can be published.\n"
        "# Keep two offline copies of the file and the passphrase written down elsewhere.\n"
        f"{line}\n"
    )
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, body.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    # Verify BEFORE the plaintext is touched: the encrypted file must decrypt,
    # with the passphrase just typed, to the same seed and the same public key.
    try:
        ok = decrypt_seed(_find_envelope(tmp), passphrase) == seed and read_public(tmp) == pub
    except (ValueError, SystemExit):
        ok = False
    if not ok:
        tmp.unlink(missing_ok=True)
        print("the encrypted copy did not verify -- the plaintext key is UNTOUCHED.")
        return 1
    # Swap first, scrub the moved-aside plaintext after: a failed replace
    # leaves the plaintext key where it was, never random bytes (K1 round 2).
    aside = path.with_name(path.name + ".plain.old")
    aside.unlink(missing_ok=True)
    try:
        os.replace(str(path), str(aside))
        os.replace(str(tmp), str(path))
    except OSError as exc:
        if aside.exists() and not path.exists():
            os.replace(str(aside), str(path))
        tmp.unlink(missing_ok=True)
        print(f"could not swap the encrypted file in ({exc}); the plaintext key is UNTOUCHED.")
        return 1
    _scrub(aside)
    aside.unlink(missing_ok=True)
    _passphrase_cache[str(path)] = passphrase
    print(f"encrypted {path}; public key unchanged "
          f"({release_pubkey.pubkey_id(base64.b64encode(pub).decode('ascii'))}).")
    print("NOW: (1) make two offline copies:  python tools/release_key.py backup --to <USB>")
    print("     (2) write the passphrase down and keep it somewhere ELSE than the USB sticks;")
    print("     (3) DESTROY every older plaintext copy of the key (USB sticks, password-manager")
    print("         entries, `backup --print` lines): they are the unencrypted key. Overwriting")
    print("         a file is not guaranteed on an SSD.")
    print("     Other key files beside it (release-next.key, release.key.superseded): run")
    print("     `release_key.py --path <file> encrypt` on each. docs/RELEASE.md.")
    return 0


def cmd_pubkey(args) -> int:
    pub = base64.b64encode(read_public(key_path(args.path))).decode("ascii")
    if args.quiet:
        print(pub)
        return 0
    print(f"public key : {pub}")
    print(f"pubkey_id  : {release_pubkey.pubkey_id(pub)}")
    print("")
    print("The dashboard verifies publishes against DASH_RELEASE_PUBKEYS")
    print("(comma-separated). Set it in the container env to exactly this value.")
    return 0


# The keys a rotation keeps on this rig beside release.key (RELEASE.md,
# Rotating): the side key of steps 1-2, and the old key step 3 moves aside.
ROTATION_NEIGHBOURS = ("release-next.key", "release.key.superseded")


def trusted_key_paths(signing: Path) -> list[Path]:
    """release.key first, then whichever rotation neighbours exist beside it.

    logic-release-1 round 2 (2026-09-25): load_secrets.ps1 used to set
    DASH_RELEASE_PUBKEYS to release.key's public half ONLY, and ship.cmd's
    dashboard deploy writes that value into the container. So every ship in
    a rotation's window redeployed THIS studio's dashboard trusting one key:
    before the switch it could not verify anything the side key signed, and
    after the switch it stopped trusting the old key the current build, the
    vendor channel and the OTA code trees are still signed by - the exact
    state RELEASE.md step 2 exists to prevent. The window is defined by the
    files on disk, so the trust list is derived from them too, and dropping
    the old key from the dashboard is moving release.key.superseded off the
    rig (step 4)."""
    out = [signing]
    for name in ROTATION_NEIGHBOURS:
        cand = signing.parent / name
        if cand != signing and cand.exists():
            out.append(cand)
    return out


def cmd_trusted(args) -> int:
    pubs: list[tuple[Path, str]] = []
    for path in trusted_key_paths(key_path(args.path)):
        # An unreadable neighbour is a refusal, not a skip: a trust list
        # quietly missing one half of a rotation is the stranding it exists
        # to prevent.
        pub = base64.b64encode(read_public(path)).decode("ascii")
        if pub not in (p for _, p in pubs):
            pubs.append((path, pub))
    if args.quiet:
        print(",".join(p for _, p in pubs))
        return 0
    for path, pub in pubs:
        print(f"{release_pubkey.pubkey_id(pub)}  {path.name}  {pub}")
    print("")
    print("DASH_RELEASE_PUBKEYS for this studio's dashboard (load_secrets.ps1 sets it):")
    print(",".join(p for _, p in pubs))
    return 0


_TUPLE_RE = re.compile(
    r"(RELEASE_PUBKEYS:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\()(.*?)(\n\))",
    re.DOTALL,
)


def cmd_bake(args) -> int:
    pub = base64.b64encode(read_public(key_path(args.path))).decode("ascii")
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

    p_tr = sub.add_parser(
        "trusted",
        help="the public halves the studio dashboard must trust: release.key plus "
             "release-next.key / release.key.superseded while a rotation is under way")
    p_tr.add_argument("--quiet", action="store_true", help="just the comma-separated keys")
    p_tr.set_defaults(func=cmd_trusted)

    p_backup = sub.add_parser("backup", help="copy the key somewhere safe (REL-14)")
    p_backup.add_argument("--to", default="",
                          help="write a copy here (a file, or a directory to write "
                               "release.key into)")
    p_backup.add_argument("--print", dest="print_only", action="store_true",
                          help="print the base64 line instead, for a password manager")
    p_backup.add_argument("--force", action="store_true",
                          help="overwrite an existing copy at --to")
    p_backup.set_defaults(func=cmd_backup)

    p_st = sub.add_parser("status", help="encrypted | plaintext | missing (no passphrase asked)")
    p_st.set_defaults(func=cmd_status)
    p_ck = sub.add_parser("check", help="decrypt once to prove the passphrase; exit 1 if wrong")
    p_ck.set_defaults(func=cmd_check)

    p_enc = sub.add_parser("encrypt", help="passphrase-protect the key file in place (CR-378)")
    p_enc.set_defaults(func=cmd_encrypt)

    p_bake = sub.add_parser("bake", help="write the public half into the companion")
    p_bake.add_argument("--add", action="store_true",
                        help="keep the keys already baked (rotation overlap)")
    p_bake.add_argument("--target", default="", help="file to edit (default release_pubkey.py)")
    p_bake.set_defaults(func=cmd_bake)

    args = ap.parse_args(argv)
    if args.cmd == "backup" and not args.to and not args.print_only:
        ap.error("backup needs --to <path> or --print")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
