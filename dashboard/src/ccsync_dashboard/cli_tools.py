"""The AI CLI setup wizard: install the publisher's binary, then sign it in.

Added 2026-08-18, on the owner's reading of the Settings page: "Claude Code:
not installed. no `claude` on this container's PATH. Install it on the
dashboard host, or set its full path below." is a sentence with a shell in it.
The customers this product is being packaged for do not have one, and the
appliance direction (`docs/ZERO_TOUCH_PLAN.md`) is the whole reason the
manifest and the keys moved onto a web page in the first place. So the two CLI
rows get a stepper: notice, install, sign in, test.

**This is not a walk-back of COMMERCIAL_READINESS.md item 1.** That finding
named three things, and only one of them was the vendor's: REDISTRIBUTING the
Claude Code binary inside our own artefacts. Nothing here does that. No CLI is
bundled in the image (`docs/DOCKER.md`, "What image mode does NOT bake in"),
in an installer, in a package record or in a release. What this module does is
fetch, at the customer's click, from the PUBLISHER'S OWN distribution
(`downloads.claude.ai` for Claude Code, `github.com/openai/codex` releases for
Codex), verified against the PUBLISHER'S OWN checksum, into the customer's own
data volume, for the customer's own account. That checksum is a CONDITION, not
a nice-to-have (trust-model-7, 2026-08-21): a release with no published
checksum for the asset is refused rather than installed unverified, and the
admin is pointed at the "type its full path" fallback for a copy they
installed and vouch for themselves. That is the same act as the
customer typing the publisher's install command on their host, which the
previous design required of them; it is not us shipping a copy. The
subscription question is unchanged and still theirs: the whole CLI half stays
behind `[features] ai_cli_providers` (off in the vendor build), and the wizard
opens on the notice that says so.

**Where things live.** Everything is under `<data>/tools/<tool>/`, which is a
volume the customer already backs up and which survives an image update:

    <data>/tools/claude-code/state.json      installed_version, sha256, when
    <data>/tools/claude-code/current         a POINTER FILE (see below)
    <data>/tools/claude-code/2.1.234/claude  the binary itself, 0755
    <data>/tools/claude-code/home/           $HOME for every run of it, 0700

`current` is a file holding a relative path, NOT a symlink. Two reasons: a
DSM/Synology data volume can be on a filesystem where the container's uid
cannot make one, and a DANGLING symlink answers `Path.is_file()` the same way
a missing file does only by luck of resolution order -- a plain file we read
and then check is a state we can describe to an admin ("installed but the
binary is gone") rather than one that reads as "not installed" and silently
re-downloads 313 MB.

**$HOME is ours, never the container's.** The CLIs persist credentials under
`$HOME/.claude` / `$HOME/.codex`. The container's default HOME is inside the
image on some deployments and on a tmpfs on others, so a sign-in done through
this wizard would evaporate at the next `docker compose up`. Every run of a
WIZARD-INSTALLED CLI -- the probe, the Test button and the real ytdl call --
therefore gets `HOME=<data>/tools/<tool>/home`, through `cli_env()`, so all
three agree about which account they are using. A CLI the customer installed
themselves the old way keeps the environment it always had (see
`_home_active`): overriding HOME for a binary that was signed in on the host
would break a working deployment to tidy up a path.

**The sign-in is a pty, not a shell.** `claude auth login` prints an
authorisation URL and waits for a code on its TERMINAL; there is no
`--print-url` and no JSON mode. So the session below allocates a pty
(`pty.openpty`), runs the CLI attached to it, reads the output on a thread,
lifts the first `https://` URL out of it and hands that to the browser; the
admin pastes the code back into the page and it is written to the pty. This is
the same shape as the companion's YouTube sign-in (`ytdl_browser_login.py`):
URL out, code back, nothing else crosses. **The code is never logged**, and
neither is the long-lived token the `setup-token` fallback prints.

Verified against Claude Code 2.1.234 (2026-08-18): `claude auth login
[--claudeai|--console]`, `claude auth logout`, `claude auth status --json`
({loggedIn, authMethod, apiProvider, apiKeySource, email, orgId, orgName,
subscriptionType}) and `claude setup-token` all exist with those spellings.
What could NOT be verified from Windows is whether `auth login` accepts a pty
as a terminal inside the container -- hence both strategies, login first, and
`KNOWN_BUGS.md` CR-24.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from . import release_feed, secrets_boot
from .api import get_conn

log = logging.getLogger("ccsync.dashboard.cli_tools")

router = APIRouter(prefix="/api/v1")

CLAUDE_CODE = "claude_code"
CODEX = "codex"


class ToolError(RuntimeError):
    """A refusal an admin reads verbatim. Never carries a credential, a code
    or a token -- everything that reaches one of these goes through
    `_redact()` first."""


class ToolBusy(ToolError):
    """Something is already running. A distinct type because the route answers
    409 for it and 400 for every other refusal."""


class UnsupportedPlatform(ToolError):
    """This host is not one the wizard can install for. Names what it saw."""


@dataclass(frozen=True)
class ToolSpec:
    """One installable CLI: where its bytes come from, and what to run."""

    name: str
    label: str
    dir_name: str
    binary: str
    # Where the binary sits INSIDE its version directory once installed.
    # Claude Code is a single file; Codex ships a package tree with sidecars
    # (`rg`, `codex-code-mode-host`) its own installer chmods, so it keeps the
    # publisher's layout rather than being flattened.
    rel_binary: str
    publisher: str
    # What `HOME=<ours>` makes the CLI write, used to tell "this wizard signed
    # it in" from "an empty directory".
    home_marker: str


TOOLS: dict[str, ToolSpec] = {
    CLAUDE_CODE: ToolSpec(
        name=CLAUDE_CODE, label="Claude Code", dir_name="claude-code",
        binary="claude", rel_binary="claude",
        publisher="Anthropic (downloads.claude.ai)", home_marker=".claude",
    ),
    CODEX: ToolSpec(
        name=CODEX, label="Codex", dir_name="codex",
        binary="codex", rel_binary="bin/codex",
        publisher="OpenAI (github.com/openai/codex releases)", home_marker=".codex",
    ),
}

# ---------------------------------------------------------------- publishers
# Claude Code. Confirmed live 2026-08-18: `/latest` answers the bare version
# string ("2.1.234"), `/<version>/manifest.json` carries
# platforms["linux-x64"].checksum (sha256 hex) and .size, and the binary is at
# `/<version>/<platform>/claude`. This is the same distribution the publisher's
# own install.sh reads; we skip its `claude install` step on purpose (that sets
# up a launcher in a human's ~/.local/bin, which is not what a container wants
# -- we run the binary by absolute path).
CLAUDE_BASE = "https://downloads.claude.ai/claude-code-releases"

# Codex. The publisher's install.sh (read 2026-08-18) picks
# `codex-package-<arch>-unknown-linux-musl.tar.gz` on EVERY Linux, glibc or
# not -- the Linux builds are static musl binaries -- and verifies it against
# the `codex-package_SHA256SUMS` asset in the same release. We do exactly that,
# rather than the `codex-<triple>.tar.gz` asset the task described: that name
# does not exist in the release (checked against rust-v0.147.0's 200 assets)
# and it is not covered by the checksum file.
CODEX_RELEASE_API = "https://api.github.com/repos/openai/codex/releases/latest"
CODEX_SUMS_ASSET = "codex-package_SHA256SUMS"

# Caps. The Claude Code linux-x64 binary MEASURED 328,358,192 bytes (313 MiB)
# on 2.1.234, so the 300 MiB ceiling this was first specified with would have
# refused the real download on day one. The cap here is a runaway-response
# guard, not a size policy: the manifest also declares an exact `size` and a
# sha256, both of which are enforced, so a hostile server cannot spend our
# disk quietly either way.
CLAUDE_MAX_BYTES = 512 * 1024 * 1024
CODEX_MAX_BYTES = 400 * 1024 * 1024
CODEX_MAX_UNPACKED_BYTES = 1536 * 1024 * 1024
JSON_MAX_BYTES = 8 * 1024 * 1024
FETCH_TIMEOUT = 60.0
DOWNLOAD_TIMEOUT = 900.0

# How long the whole browser sign-in may take before the child is killed. Five
# minutes is the publisher's own OAuth window and comfortably longer than
# "open a tab, log in, copy a code".
SIGNIN_TIMEOUT = 300.0
STATUS_TIMEOUT = 30.0
LOGOUT_TIMEOUT = 60.0

_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
# A version string becomes both a URL segment and a directory name. Anything
# that is not digits and dots is refused before either happens.


# ------------------------------------------------------------------- layout

def tools_root(settings: Any) -> Path:
    """`<data>/tools`. Beside `<data>/secrets`, for the same reason: one
    directory the deployment backs up, one to lock down."""
    return Path(settings.db_path).parent / "tools"


def tool_root(settings: Any, name: str) -> Path:
    return tools_root(settings) / spec(name).dir_name


def home_dir(settings: Any, name: str) -> Path:
    return tool_root(settings, name) / "home"


def state_path(settings: Any, name: str) -> Path:
    return tool_root(settings, name) / "state.json"


def pointer_path(settings: Any, name: str) -> Path:
    return tool_root(settings, name) / "current"


def token_path(settings: Any, name: str) -> Path:
    """The long-lived OAuth token the `setup-token` fallback prints, if that
    is the strategy that worked. Under `<data>/secrets/ai/` with the API keys,
    0600, written through the same helper -- it IS a credential, and a
    directory an operator has already been told to protect is where it
    belongs."""
    return Path(settings.db_path).parent / "secrets" / "ai" / f"{name}_oauth_token"


def spec(name: str) -> ToolSpec:
    try:
        return TOOLS[name]
    except KeyError:
        raise ToolError(f"{name!r} is not an installable CLI") from None


def installed_binary(settings: Any, name: str) -> str:
    """The absolute path of the wizard-installed CLI, or "".

    Reads the pointer FILE and then checks the target, so "the pointer says
    2.1.234 but the file is gone" is a state we can report rather than one
    that silently reads as "never installed"."""
    try:
        rel = pointer_path(settings, name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not rel:
        return ""
    target = tool_root(settings, name) / rel
    return str(target) if target.is_file() else ""


def read_state(settings: Any, name: str) -> dict:
    """`state.json`, or {}. A corrupt file reads as {} -- an install record
    that will not parse must not be able to 500 the Settings page."""
    try:
        raw = state_path(settings, name).read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        log.warning("%s state.json is not JSON -- ignoring it", name)
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(settings: Any, name: str, data: dict) -> None:
    path = state_path(settings, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _utcnow() -> str:
    from . import db as dbmod

    return dbmod.utcnow_iso()


# --------------------------------------------------------------- environment
# ONE helper, three callers: ai_providers.probe_cli (the status chip), the
# Test button (which is the same probe, forced) and the real ytdl call
# (ytdlweb.ai_backend, through the lookup payload's `cli_env`). They MUST
# agree: a probe that answers "signed in" about a different $HOME than the job
# uses is worse than no probe at all.

# Removed from every CLI run. A CLI provider is chosen because the customer
# wants their SUBSCRIPTION spent; Claude Code prefers ANTHROPIC_API_KEY when it
# finds one, so an inherited key would bill the wrong account and the page
# would report "signed in" about the key rather than the login.
STRIPPED_ENV_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
                     "ANTHROPIC_AUTH_TOKEN")

# Passed THROUGH (not stripped) when we hold one: the token the setup-token
# strategy produced is the credential the customer signed in with.
CLAUDE_TOKEN_VAR = "CLAUDE_CODE_OAUTH_TOKEN"


def read_token(settings: Any, name: str) -> str:
    try:
        return token_path(settings, name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _home_active(settings: Any, name: str) -> bool:
    """Whether OUR $HOME is the one this CLI should get.

    False for a deployment whose admin installed and signed in `claude` on the
    host the pre-2026-08-18 way: pointing that binary at an empty HOME would
    log it out from the dashboard's point of view and break a working site to
    tidy a path. The directory only exists once the wizard has installed or
    signed something in.
    """
    try:
        return home_dir(settings, name).is_dir()
    except OSError:
        return False


def cli_env_overlay(settings: Any, name: str) -> dict:
    """Just the variables this module sets: {} when the wizard is not in play.

    Separate from `cli_env` because this is what crosses to the mounted ytdl
    app in the lookup payload -- it builds its own base environment from the
    same `os.environ` (same container, same process), so sending the whole
    thing would be a large dict of duplicates carrying a token through more
    hands than it needs.
    """
    if name not in TOOLS or settings is None:
        return {}
    if not _home_active(settings, name):
        return {}
    overlay = {"HOME": str(home_dir(settings, name))}
    if name == CLAUDE_CODE:
        token = read_token(settings, name)
        if token:
            overlay[CLAUDE_TOKEN_VAR] = token
    return overlay


def cli_env(settings: Any, name: str, base: dict | None = None) -> dict:
    """The complete environment a CLI subprocess gets."""
    env = dict(os.environ if base is None else base)
    for var in STRIPPED_ENV_VARS:
        env.pop(var, None)
    env.update(cli_env_overlay(settings, name))
    return env


# ------------------------------------------------------------ platform facts

def _machine_key(machine: str) -> str:
    machine = (machine or "").lower()
    if machine in ("x86_64", "amd64", "x64"):
        return "x64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return ""


def _is_musl() -> bool:
    """A musl userland (Alpine). The publisher ships a separate `-musl` build
    of Claude Code and we deliberately do not choose between them by guessing:
    the shipped image is `python:3.12-slim` (bookworm, glibc), so a musl host
    is somebody else's container and gets a refusal that says so."""
    try:
        return any(Path("/lib").glob("ld-musl-*"))
    except OSError:
        return False


def platform_key(machine: str | None = None, system: str | None = None) -> str:
    """The key into the Claude Code manifest's `platforms` map.

    Raises UnsupportedPlatform with a detail naming what it actually saw --
    "not supported" with no nouns in it is the kind of message that costs a
    support call.
    """
    system = (system or sys.platform or "").lower()
    machine = machine if machine is not None else platform.machine()
    if not system.startswith("linux"):
        raise UnsupportedPlatform(
            f"this dashboard is running on {system or 'an unknown OS'}, and the "
            f"wizard installs the Linux build the container uses. On a dev "
            f"machine, install the CLI yourself and type its path below.")
    arch = _machine_key(machine)
    if not arch:
        raise UnsupportedPlatform(
            f"this host reports the CPU architecture {machine!r}, and the "
            f"publisher builds x86_64 and arm64 only.")
    if _is_musl():
        raise UnsupportedPlatform(
            "this container has a musl C library (Alpine). The wizard installs "
            "the glibc build only, which is what the shipped image uses. "
            "Install the CLI in the container yourself and type its path below.")
    return f"linux-{arch}"


def codex_target(machine: str | None = None, system: str | None = None) -> str:
    """The Rust target triple Codex's own installer picks on Linux. musl for
    both arches, glibc host or not: the Linux builds are static."""
    key = platform_key(machine, system)
    return ("x86_64-unknown-linux-musl" if key.endswith("x64")
            else "aarch64-unknown-linux-musl")


def install_supported(settings: Any) -> tuple[bool, str]:
    """(can the wizard install here, why not). Never raises."""
    try:
        platform_key()
    except UnsupportedPlatform as exc:
        return False, str(exc)
    # Checked, never CREATED: this runs on every render of the Settings page,
    # including for a site whose CLI providers are off, and a status call has
    # no business making directories or writing probe files in somebody's data
    # volume. The install itself does the mkdir and reports a real OSError if
    # the check was too optimistic.
    root = tools_root(settings)
    existing = root
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    if not os.access(existing, os.W_OK | os.X_OK):
        return False, (f"{existing} is not writable by this container. The data "
                       f"volume has to be writable to install anything into it.")
    return True, ""


# ------------------------------------------------------------- fetch helpers
# Every byte comes through release_feed's opener: https only, no credential on
# any hop, at most 5 redirects, each one re-checked for a scheme downgrade.
# GitHub answers a release asset with a 302 to release-assets.githubusercontent
# .com, which is exactly the case that carve-out was written for (CLAUDE.md,
# docs/GOTCHAS.md 12).

def _fetch_bytes(url: str, cap: int, timeout: float = FETCH_TIMEOUT) -> bytes:
    try:
        with release_feed.open_https_stream(url, timeout=timeout) as resp:
            data = bytearray()
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                data += chunk
                if len(data) > cap:
                    raise ToolError(f"{url} sent more than {cap} bytes - refused")
            return bytes(data)
    except release_feed.FeedError as exc:
        raise ToolError(str(exc)) from None
    except OSError as exc:
        raise ToolError(f"could not reach {url} ({type(exc).__name__})") from None


def _fetch_json(url: str) -> Any:
    raw = _fetch_bytes(url, JSON_MAX_BYTES)
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise ToolError(f"{url} did not answer JSON") from None


def _download(url: str, dest: Path, *, cap: int, expected_sha: str,
              expected_size: int, progress) -> tuple[str, int]:
    """Stream `url` to `dest`, hashing as it goes. Returns (sha256, size).

    `dest` is UNLINKED on every failure. Nothing downstream ever sees a
    half-written binary: the pointer file is flipped only after this returns
    and the digest has matched, so a failed or killed install leaves the
    previously installed version exactly as it was.
    """
    digest = hashlib.sha256()
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with release_feed.open_https_stream(url, timeout=DOWNLOAD_TIMEOUT) as resp, \
                dest.open("wb") as fh:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > cap:
                    raise ToolError(f"the download exceeded {cap} bytes - refused")
                fh.write(chunk)
                digest.update(chunk)
                progress(size)
    except release_feed.FeedError as exc:
        dest.unlink(missing_ok=True)
        raise ToolError(str(exc)) from None
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise ToolError(f"could not write the download ({exc.strerror or exc})") from None
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    sha = digest.hexdigest()
    if expected_sha and sha != expected_sha:
        dest.unlink(missing_ok=True)
        raise ToolError(
            "the download does not match the publisher's sha256 - refused. "
            "Nothing was installed.")
    if expected_size and size != expected_size:
        dest.unlink(missing_ok=True)
        raise ToolError(
            f"the download is {size} bytes and the publisher's manifest says "
            f"{expected_size} - refused. Nothing was installed.")
    return sha, size


# --------------------------------------------------- Claude Code: the source

def latest_claude_version(fetch=None) -> str:
    fetch = fetch or (lambda url: _fetch_bytes(url, 1024))
    raw = fetch(f"{CLAUDE_BASE}/latest")
    version = (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)).strip()
    return validate_version(version)


def validate_version(version: str) -> str:
    version = (version or "").strip()
    if not _VERSION_RE.match(version):
        # This string becomes a URL segment AND a directory name. A publisher
        # that starts answering "latest: 2.2" or something with a slash in it
        # is a refusal, never a path we join.
        raise ToolError(f"the publisher answered {version[:40]!r} where a version "
                        f"number was expected - refused")
    return version


def claude_platform_entry(manifest: Any, key: str) -> dict:
    """{binary, checksum, size} for one platform, or a refusal that names the
    platforms the manifest DOES carry (which is what tells an operator whether
    the publisher dropped their architecture or we asked wrongly)."""
    if not isinstance(manifest, dict):
        raise ToolError("the publisher's manifest is not a JSON object")
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        raise ToolError("the publisher's manifest carries no platforms")
    entry = platforms.get(key)
    if not isinstance(entry, dict):
        raise ToolError(
            f"the publisher's manifest has no {key} build. It carries: "
            + ", ".join(sorted(str(k) for k in platforms)))
    checksum = str(entry.get("checksum") or "").strip().lower()
    if not _SHA_RE.match(checksum):
        raise ToolError(f"the {key} entry has no usable sha256 checksum - refused")
    try:
        size = int(entry.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return {"binary": str(entry.get("binary") or "claude"),
            "checksum": checksum, "size": size}


def claude_binary_url(version: str, key: str, binary: str = "claude") -> str:
    return f"{CLAUDE_BASE}/{validate_version(version)}/{key}/{binary}"


# --------------------------------------------------------- Codex: the source

def codex_release(fetch=None) -> dict:
    data = (fetch or _fetch_json)(CODEX_RELEASE_API)
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        raise ToolError("the Codex release API did not answer a release")
    return data


def codex_version(release: dict) -> str:
    """`rust-v0.147.0` -> `0.147.0`. The tag is the publisher's; the directory
    name has to be something we validated."""
    tag = str(release.get("tag_name") or release.get("name") or "").strip()
    match = re.search(r"([0-9]+\.[0-9]+\.[0-9]+)", tag)
    if not match:
        raise ToolError(f"the Codex release tag {tag[:40]!r} has no version number in it")
    return match.group(1)


def codex_asset(release: dict, wanted: str) -> str:
    for asset in release.get("assets") or []:
        if isinstance(asset, dict) and str(asset.get("name")) == wanted:
            url = str(asset.get("browser_download_url") or "")
            if url.startswith("https://"):
                return url
    return ""


def parse_sha256sums(text: str, wanted: str) -> str:
    """The digest for one file out of a `sha256sum`-format list, or ""."""
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == wanted:
            digest = parts[0].strip().lower()
            if _SHA_RE.match(digest):
                return digest
    return ""


def _extract_codex_package(archive: Path, dest: Path) -> None:
    """Unpack the publisher's package tarball into `dest`.

    `filter="data"` (Python 3.12) is what refuses an absolute path, a `..`
    member, a device node or a symlink pointing out of the tree -- a tarball
    is attacker-shaped input even when the attacker would have to be the
    publisher. The uncompressed total is capped as well, because a filter does
    not stop a bomb.
    """
    total = 0
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                total += max(0, int(member.size or 0))
                if total > CODEX_MAX_UNPACKED_BYTES:
                    raise ToolError("the Codex archive unpacks to more than "
                                    f"{CODEX_MAX_UNPACKED_BYTES} bytes - refused")
            dest.mkdir(parents=True, exist_ok=True)
            tar.extractall(dest, members=members, filter="data")
    except tarfile.TarError as exc:
        # The filter REFUSES the whole archive rather than skipping a member,
        # and so do we: a package that contains a `..` path is not a package
        # with one bad file in it, it is a package to walk away from.
        shutil.rmtree(dest, ignore_errors=True)
        raise ToolError(f"the Codex archive was refused ({type(exc).__name__}: "
                        f"{str(exc)[:160]}) - nothing was installed") from None
    # The publisher's own install.sh chmods these; a tar `data` filter drops
    # the executable bit on the way in.
    for rel in ("bin/codex", "bin/codex-code-mode-host", "codex-path/rg",
                "codex-resources/bwrap"):
        target = dest / rel
        if target.is_file():
            try:
                target.chmod(0o755)
            except OSError:
                pass


# ------------------------------------------------------------ the installer
# One at a time, in a background thread, with a status a poller can render.
# Global rather than per-tool: these are 100-330 MB downloads onto a NAS that
# is also serving footage, and two at once is never what anybody meant.

_install_lock = threading.Lock()
_install_status: dict[str, dict] = {}
_install_running: str = ""


def _blank_status(name: str) -> dict:
    return {"tool": name, "state": "idle", "step": "", "detail": "", "version": "",
            "bytes": 0, "total": 0, "percent": 0, "error": "",
            "started_at": "", "finished_at": "", "checksum_source": ""}


def _set_status(name: str, **fields) -> None:
    with _install_lock:
        status = _install_status.setdefault(name, _blank_status(name))
        status.update(fields)
        total = status.get("total") or 0
        got = status.get("bytes") or 0
        status["percent"] = int(got * 100 / total) if total else 0


def install_status(settings: Any, name: str) -> dict:
    """What the poller sees: the live run if there is one, else the installed
    record. Never raises."""
    spec(name)
    with _install_lock:
        status = dict(_install_status.get(name) or _blank_status(name))
    state = read_state(settings, name)
    binary = installed_binary(settings, name)
    status["installed"] = bool(binary)
    status["installed_path"] = binary
    status["installed_version"] = str(state.get("installed_version") or "")
    status["installed_at"] = str(state.get("installed_at") or "")
    status["installed_sha256"] = str(state.get("sha256") or "")
    status["checksum_source"] = status.get("checksum_source") or str(
        state.get("checksum_source") or "")
    status["publisher"] = spec(name).publisher
    if status["state"] == "idle" and binary:
        status["state"] = "done"
        status["step"] = "installed"
        status["version"] = status["installed_version"]
    if state.get("installed_version") and not state.get("checksum_verified", True):
        status["unverified"] = True
    else:
        status["unverified"] = False
    return status


def start_install(settings: Any, name: str) -> dict:
    """Kick off an install on a background thread. Raises ToolError/ToolBusy.

    The refusals happen HERE, on the request thread, so an admin gets a 4xx
    with a sentence in it rather than a spinner that ends in an error field.
    """
    global _install_running
    spec(name)
    ok, why = install_supported(settings)
    if not ok:
        raise ToolError(why)
    with _install_lock:
        if _install_running:
            raise ToolBusy(f"an install of {TOOLS[_install_running].label} is already "
                           f"running. Wait for it to finish.")
        _install_running = name
        _install_status[name] = _blank_status(name)
        _install_status[name].update({"state": "running", "step": "checking the publisher",
                                      "started_at": _utcnow()})
    thread = threading.Thread(target=_install_worker, args=(settings, name),
                              name=f"install-{name}", daemon=True)
    thread.start()
    return install_status(settings, name)


def _install_worker(settings: Any, name: str) -> None:
    global _install_running
    try:
        if name == CLAUDE_CODE:
            _install_claude(settings)
        else:
            _install_codex(settings)
    except ToolError as exc:
        _set_status(name, state="error", error=_redact(str(exc)), finished_at=_utcnow())
        log.warning("install of %s failed: %s", name, exc)
    except Exception as exc:                                    # noqa: BLE001
        # A background thread that dies with a traceback leaves the page
        # spinning forever; every failure has to become a status.
        _set_status(name, state="error", finished_at=_utcnow(),
                    error=f"{type(exc).__name__} while installing {name}")
        log.exception("install of %s crashed", name)
    finally:
        with _install_lock:
            _install_running = ""
        # A new binary means every cached "is it installed / signed in" answer
        # is stale.
        _reset_probe_cache()


def _reset_probe_cache() -> None:
    from . import ai_providers

    ai_providers.reset_probe_cache()


def _install_claude(settings: Any) -> None:
    name = CLAUDE_CODE
    key = platform_key()
    _set_status(name, step="asking the publisher for the latest version")
    version = latest_claude_version()
    _set_status(name, version=version, step="reading the publisher's manifest")
    manifest = _fetch_json(f"{CLAUDE_BASE}/{version}/manifest.json")
    entry = claude_platform_entry(manifest, key)
    url = claude_binary_url(version, key, entry["binary"])
    _set_status(name, step=f"downloading {version} ({key})", total=entry["size"], bytes=0)

    staging = tool_root(settings, name) / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    part = staging / f"{version}.part"
    sha, size = _download(url, part, cap=CLAUDE_MAX_BYTES,
                          expected_sha=entry["checksum"],
                          expected_size=entry["size"],
                          progress=lambda got: _set_status(name, bytes=got))
    _set_status(name, step="verified, installing", bytes=size)

    target_dir = tool_root(settings, name) / version
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(tool_root(settings, name), 0o700)
        os.chmod(target_dir, 0o700)
    except OSError:
        pass
    target = target_dir / spec(name).rel_binary
    os.replace(part, target)
    try:
        target.chmod(0o755)
    except OSError:
        pass
    _finish_install(settings, name, version=version, rel=spec(name).rel_binary,
                    sha=sha, size=size, url=url, checksum_source="publisher_manifest")


def _install_codex(settings: Any) -> None:
    name = CODEX
    target_triple = codex_target()
    _set_status(name, step="asking the publisher for the latest release")
    release = codex_release()
    version = codex_version(release)
    asset_name = f"codex-package-{target_triple}.tar.gz"
    url = codex_asset(release, asset_name)
    if not url:
        raise ToolError(
            f"the latest Codex release has no {asset_name}. That is the asset "
            f"the publisher's own installer uses on Linux, so this build of the "
            f"wizard cannot install Codex until the naming settles. Install it "
            f"on the host and type its path below.")
    _set_status(name, version=version, step="reading the publisher's checksums")
    sums_url = codex_asset(release, CODEX_SUMS_ASSET)
    expected = ""
    checksum_source = "downloaded_bytes"
    if sums_url:
        expected = parse_sha256sums(
            _fetch_bytes(sums_url, JSON_MAX_BYTES).decode("utf-8", "replace"), asset_name)
        if expected:
            checksum_source = "publisher_checksums"
    if not expected:
        # trust-model-7 (2026-08-21): this used to fall through with
        # `expected_sha=""`, install, and record `checksum_verified: False` in
        # a state file nobody reads - while this module's docstring, the page
        # and CLAUDE.md all describe the fetch as verified against the
        # publisher's own checksum. A binary this dashboard will then EXECUTE
        # with fleet ytdl prompts either gets that check or does not get
        # installed by us; the admin still has the "type its path" fallback
        # for a copy they installed themselves and vouch for.
        raise ToolError(
            f"the publisher published no checksum for {asset_name} in Codex "
            f"{version}, so this install cannot be verified and was not done. "
            f"Install Codex on the dashboard host yourself and type its full "
            f"path below, or try again when the publisher ships "
            f"{CODEX_SUMS_ASSET} with the release.")
    _set_status(name, step=f"downloading {version} ({target_triple})",
                checksum_source=checksum_source, bytes=0, total=0, detail="")
    staging = tool_root(settings, name) / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    part = staging / f"{version}.tar.gz"
    sha, size = _download(url, part, cap=CODEX_MAX_BYTES, expected_sha=expected,
                          expected_size=0,
                          progress=lambda got: _set_status(name, bytes=got))
    _set_status(name, step="unpacking", bytes=size)
    target_dir = tool_root(settings, name) / version
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    try:
        _extract_codex_package(part, target_dir)
    finally:
        part.unlink(missing_ok=True)
    binary = target_dir / spec(name).rel_binary
    if not binary.is_file():
        shutil.rmtree(target_dir, ignore_errors=True)
        raise ToolError(f"the Codex archive did not contain {spec(name).rel_binary} "
                        f"- nothing was installed")
    _finish_install(settings, name, version=version, rel=spec(name).rel_binary,
                    sha=sha, size=size, url=url, checksum_source=checksum_source)


def _finish_install(settings: Any, name: str, *, version: str, rel: str, sha: str,
                    size: int, url: str, checksum_source: str) -> None:
    """Record it, THEN flip the pointer. In that order: a pointer flipped
    before the record exists is an installed binary nobody can name a version
    for, and the flip is the single atomic act that makes a version live."""
    _write_state(settings, name, {
        "installed_version": version,
        "sha256": sha,
        "size": size,
        "installed_at": _utcnow(),
        "source_url": url,
        "checksum_source": checksum_source,
        "checksum_verified": checksum_source != "downloaded_bytes",
        "binary": rel,
    })
    pointer = pointer_path(settings, name)
    tmp = pointer.with_name("current.tmp")
    tmp.write_text(f"{version}/{rel}", encoding="utf-8")
    os.replace(tmp, pointer)
    _prune_old_versions(settings, name, keep=version)
    home_dir(settings, name).mkdir(parents=True, exist_ok=True)
    try:
        home_dir(settings, name).chmod(0o700)
    except OSError:
        pass
    _set_status(name, state="done", step="installed", version=version,
                finished_at=_utcnow(), checksum_source=checksum_source, error="")
    log.info("installed %s %s from %s (sha256 %s, %s)", name, version, url, sha[:12],
             checksum_source)


def _prune_old_versions(settings: Any, name: str, *, keep: str) -> None:
    """One version on disk. These are 100-330 MB each and the appliance target
    is a NAS with tens of gigabytes free, so keeping every version an admin
    ever clicked UPDATE for is how the data volume fills up."""
    root = tool_root(settings, name)
    children = list(root.iterdir()) if root.is_dir() else []
    for child in children:
        if (child.is_dir() and child.name not in (keep, "home", ".staging")
                and _VERSION_RE.match(child.name)):
            shutil.rmtree(child, ignore_errors=True)
    shutil.rmtree(root / ".staging", ignore_errors=True)


def remove_install(settings: Any, name: str) -> dict:
    """Delete the tree: the binary, the record, AND the $HOME the sign-in
    lives in. REMOVE means removed -- leaving a signed-in credential behind
    for the next install to inherit is not what an admin who clicked this
    asked for. The stored OAuth token goes too."""
    spec(name)
    with _install_lock:
        if _install_running == name:
            raise ToolBusy("that install is still running. Cancel it by waiting "
                           "for it to finish, then remove.")
    cancel_signin(name)
    root = tool_root(settings, name)
    shutil.rmtree(root, ignore_errors=True)
    token_path(settings, name).unlink(missing_ok=True)
    with _install_lock:
        _install_status.pop(name, None)
    _reset_probe_cache()
    log.info("removed the %s install and its home directory", name)
    return install_status(settings, name)


# ------------------------------------------------------------- the sign-in
# URL out, code back. The same shape as the companion's YouTube sign-in
# (companion/src/ccsync_companion/ytdl_browser_login.py): the dashboard never
# sees a password, the browser never sees the CLI, and the only thing that
# crosses in the other direction is a one-time code.

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_URL_RE = re.compile(r"https://[^\s\"'<>\\)\]]+")
# Anthropic's long-lived tokens, and anything else shaped like one. Matched so
# it can be CAPTURED (setup-token) and, everywhere else, REDACTED.
_TOKEN_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}")
# A device-authorisation user code, e.g. "ABCD-EFGH". Only used to SHOW the
# admin what to type into the publisher's page.
_USER_CODE_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")
_CODE_PROMPT_RE = re.compile(
    r"paste .*code|enter .*code|authorization code|authorisation code|code\s*[:>]",
    re.I)
# What a CLI says when it will not do an interactive login on this stdin. Any
# of these BEFORE a URL appears is what makes the wizard try the next strategy.
_NO_TTY_MARKERS = ("raw mode", "not a tty", "requires a terminal", "no tty",
                   "stdin is not interactive", "not interactive",
                   "unsupported terminal", "ink requires")

MAX_CODE_CHARS = 512
_BUFFER_CAP = 64 * 1024


def _clean(text: str) -> str:
    return _ANSI_RE.sub("", (text or "").replace("\r", "\n"))


def _redact(text: str) -> str:
    """Everything that reaches an admin, a log line or a status field goes
    through here. A sign-in transcript contains, at minimum, a one-time code
    and possibly a long-lived token; neither may ever be written down."""
    return _TOKEN_RE.sub("sk-ant-…", text or "")


def mask_email(value: str) -> str:
    """`a…x@example.com`. Enough for an admin to recognise which account they
    signed in, not enough to be a directory of the customer's staff in a
    screenshot."""
    value = str(value or "").strip()
    if "@" not in value:
        return "…" if value else ""
    local, _, domain = value.partition("@")
    if len(local) <= 2:
        return f"…@{domain}"
    return f"{local[0]}…{local[-1]}@{domain}"


@dataclass
class SignInStrategy:
    """One way to sign this CLI in, and what it is called in the status."""

    key: str
    argv_tail: list[str]
    expects_code: bool = True
    captures_token: bool = False


def _strategies(name: str, mode: str, binary: str) -> list[SignInStrategy]:
    if name == CLAUDE_CODE:
        login = ["auth", "login"] + (["--console"] if mode == "console" else [])
        # LOGIN FIRST, always: it is the flow that stores a credential the CLI
        # refreshes by itself. `setup-token` is the fallback because its output
        # is a long-lived token we then have to hold (in a 0600 file, passed
        # back as CLAUDE_CODE_OAUTH_TOKEN) -- a credential in one more place
        # than the publisher intended, and worth avoiding when the first
        # strategy works.
        return [SignInStrategy("auth-login", login),
                SignInStrategy("setup-token", ["setup-token"], captures_token=True)]
    # Codex: `--device-auth` if this build has it (verified at runtime from the
    # binary's own --help, never assumed), else the plain login.
    tail = ["login"]
    if _codex_supports_device_auth(binary):
        return [SignInStrategy("codex-device-auth", ["login", "--device-auth"],
                               expects_code=False),
                SignInStrategy("codex-login", tail)]
    return [SignInStrategy("codex-login", tail)]


def _codex_supports_device_auth(binary: str) -> bool:
    if not binary:
        return False
    try:
        proc = subprocess.run([binary, "login", "--help"],       # noqa: S603
                              capture_output=True, text=True, timeout=STATUS_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return False
    return "--device-auth" in ((proc.stdout or "") + (proc.stderr or ""))


@dataclass
class SignInSession:
    """One browser sign-in, start to finish.

    States: `starting` -> `awaiting_url` -> `awaiting_code` (or
    `awaiting_browser` for a device-code flow) -> `verifying` -> `signed_in` |
    `failed` | `cancelled`. One at a time, process-wide: two of these would be
    two pty children writing into the same `$HOME/.claude`.
    """

    tool: str
    mode: str = "subscription"
    state: str = "starting"
    url: str = ""
    user_code: str = ""
    strategy: str = ""
    detail: str = ""
    account: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    _buffer: str = ""
    _proc: Any = None
    _master: int = -1
    _cancel: bool = False
    _lock: Any = field(default_factory=threading.Lock)

    # ------------------------------------------------------------- reading
    def feed(self, text: str) -> None:
        with self._lock:
            self._buffer = (self._buffer + _clean(text))[-_BUFFER_CAP:]
            buf = self._buffer
            if not self.url:
                found = _URL_RE.search(buf)
                # ONLY A TERMINATED MATCH. `os.read` returns whatever the CLI
                # has flushed, which can be half a URL: taking the first match
                # as it stands would hand the admin's browser
                # "https://claude.ai/oauth/aut" and there is no second chance
                # at an authorisation link. A match with anything after it in
                # the buffer is complete; the CLI always writes a newline or a
                # prompt next, so this costs one more read, not a timeout.
                if found and found.end() < len(buf):
                    self.url = found.group(0).rstrip(".,)")
                    self.state = ("awaiting_code" if self._expects_code
                                  else "awaiting_browser")
            if not self.user_code:
                code = _USER_CODE_RE.search(buf)
                if code:
                    self.user_code = code.group(1)
            if self.url and self.state == "awaiting_browser" and _CODE_PROMPT_RE.search(buf):
                # A device-auth build that turns out to want a paste anyway.
                self.state = "awaiting_code"

    _expects_code: bool = True

    def tail(self) -> str:
        """The last of the transcript, redacted and collapsed, for an error
        message. Never the whole buffer, and never a token."""
        with self._lock:
            text = _redact(self._buffer)
        return " ".join(text.split())[-400:]

    # ------------------------------------------------------------- writing
    def write_code(self, code: str) -> None:
        """Never logged, never stored, never echoed back in a status."""
        code = str(code or "").strip()
        if not code:
            raise ToolError("that code is blank")
        if len(code) > MAX_CODE_CHARS:
            raise ToolError("that code is too long to be one")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in code):
            raise ToolError("that code contains control characters - paste it again")
        with self._lock:
            if self.state not in ("awaiting_code", "awaiting_browser"):
                raise ToolError(f"this sign-in is {self.state}, not waiting for a code")
            fd = self._master
            if fd < 0:
                raise ToolError("this sign-in is no longer running")
            try:
                os.write(fd, (code + "\n").encode("utf-8"))
            except OSError as exc:
                raise ToolError(f"could not hand the code to the CLI "
                                f"({exc.strerror or exc})") from None
            self.state = "verifying"
            self.detail = "checking the sign-in"

    def status(self) -> dict:
        with self._lock:
            return {"state": self.state, "url": self.url, "user_code": self.user_code,
                    "strategy": self.strategy, "detail": _redact(self.detail),
                    "account": dict(self.account), "tool": self.tool,
                    "mode": self.mode,
                    "expires_in": max(0, int(SIGNIN_TIMEOUT -
                                             (time.monotonic() - self.started_at)))}


_signin_lock = threading.Lock()
_signin: SignInSession | None = None
_signin_last: dict[str, dict] = {}


def signin_status(settings: Any, name: str) -> dict:
    """The live session for this tool, else the last one's outcome, else the
    installed truth. Cheap: no subprocess."""
    spec(name)
    with _signin_lock:
        session = _signin
    if session is not None and session.tool == name:
        return session.status()
    last = dict(_signin_last.get(name) or {})
    if last:
        return last
    return {"state": "idle", "url": "", "user_code": "", "strategy": "",
            "detail": "", "account": {}, "tool": name, "mode": "", "expires_in": 0}


def start_signin(settings: Any, name: str, mode: str = "subscription") -> dict:
    """Spawn the CLI's login under a pty. Raises ToolError/ToolBusy."""
    global _signin
    spec(name)
    binary = cli_binary(settings, name)
    if not binary:
        raise ToolError(f"{spec(name).label} is not installed yet. Install it first.")
    if not _pty_available():
        raise ToolError(
            "signing in from this page needs a Linux host with a pty, which is "
            "what the container is. This dashboard is running somewhere else, so "
            "run the CLI's own login command on the host instead.")
    mode = "console" if str(mode or "").strip() == "console" else "subscription"
    with _signin_lock:
        if _signin is not None and _signin.state in _LIVE_SIGNIN_STATES:
            raise ToolBusy(f"a sign-in for {TOOLS[_signin.tool].label} is already "
                           f"open. Finish or cancel it first.")
        session = SignInSession(tool=name, mode=mode)
        _signin = session
    thread = threading.Thread(target=_signin_worker, args=(settings, name, session, binary),
                              name=f"signin-{name}", daemon=True)
    thread.start()
    # Give the CLI a moment to print its URL, so the common case answers the
    # first POST with the link instead of making the page poll for it.
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline and session.state == "starting":
        time.sleep(0.15)
    return session.status()


_LIVE_SIGNIN_STATES = ("starting", "awaiting_url", "awaiting_code",
                       "awaiting_browser", "verifying")


def submit_code(settings: Any, name: str, code: str) -> dict:
    with _signin_lock:
        session = _signin
    if session is None or session.tool != name:
        raise ToolError("there is no sign-in waiting for a code. Start one first.")
    session.write_code(code)
    return session.status()


def cancel_signin(name: str | None = None) -> dict:
    """Kill the child and forget the session. Safe to call when there is
    none."""
    global _signin
    with _signin_lock:
        session = _signin
        if session is None or (name is not None and session.tool != name):
            return {"state": "idle"}
        _signin = None
    session._cancel = True
    _kill(session)
    with session._lock:
        if session.state in _LIVE_SIGNIN_STATES:
            session.state = "cancelled"
            session.detail = "cancelled"
    _signin_last[session.tool] = session.status()
    return session.status()


def sign_out(settings: Any, name: str) -> dict:
    """`auth logout`, plus the token file. Best-effort on the CLI half: an
    admin who clicks SIGN OUT must end up signed out even if the binary is
    gone, so the credential we hold is deleted either way."""
    spec(name)
    cancel_signin(name)
    binary = cli_binary(settings, name)
    detail = ""
    if binary:
        argv = [binary, "auth", "logout"] if name == CLAUDE_CODE else [binary, "logout"]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,   # noqa: S603
                                  timeout=LOGOUT_TIMEOUT,
                                  env=cli_env(settings, name))
            if proc.returncode != 0:
                detail = _redact((proc.stderr or proc.stdout or "").strip())[:200]
        except (OSError, subprocess.SubprocessError) as exc:
            detail = f"could not run the CLI's logout ({type(exc).__name__})"
    token_path(settings, name).unlink(missing_ok=True)
    _signin_last[name] = {"state": "idle", "url": "", "user_code": "", "strategy": "",
                          "detail": detail, "account": {}, "tool": name, "mode": "",
                          "expires_in": 0}
    _reset_probe_cache()
    log.info("signed %s out", name)
    return _signin_last[name]


def _pty_available() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        import pty  # noqa: F401
        import termios  # noqa: F401
    except Exception:                                           # noqa: BLE001
        return False
    return True


def _spawn_pty(argv: list[str], env: dict, cwd: str):
    """(proc, master_fd). The CLI gets a REAL terminal on all three streams,
    because its login UI refuses a pipe.

    The window is set wide (200 columns) before the child starts: a narrow
    terminal makes the CLI WRAP the authorisation URL, and a URL broken across
    two lines is a URL the regex below cannot lift out again.
    """
    import fcntl
    import pty
    import struct
    import termios

    master, slave = pty.openpty()
    try:
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 200, 0, 0))
    except OSError:
        pass
    try:
        proc = subprocess.Popen(                                 # noqa: S603
            argv, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=cwd,
            close_fds=True, start_new_session=True)
    finally:
        os.close(slave)
    return proc, master


def _kill(session: SignInSession) -> None:
    proc = session._proc
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass
    fd = session._master
    session._master = -1
    if fd >= 0:
        try:
            os.close(fd)
        except OSError:
            pass


def _signin_worker(settings: Any, name: str, session: SignInSession, binary: str) -> None:
    global _signin
    try:
        strategies = _strategies(name, session.mode, binary)
        last_detail = ""
        for index, strategy in enumerate(strategies):
            if session._cancel:
                break
            outcome, detail = _run_strategy(settings, name, session, binary, strategy)
            if outcome == "signed_in":
                return
            last_detail = detail or last_detail
            more = index + 1 < len(strategies)
            if outcome == "no_tty" and more:
                # The whole reason both strategies exist: if `auth login` will
                # not treat a pty as a terminal in this container, `setup-token`
                # is the same URL/code shape and does.
                log.info("%s: %s did not take the pty (%s) -- trying %s",
                         name, strategy.key, detail[:120], strategies[index + 1].key)
                with session._lock:
                    session.state = "starting"
                    session.url = ""
                    session.user_code = ""
                    session._buffer = ""
                continue
            break
        with session._lock:
            if session.state in _LIVE_SIGNIN_STATES:
                session.state = "failed"
                session.detail = last_detail or "the sign-in did not complete"
    except Exception as exc:                                    # noqa: BLE001
        log.exception("%s sign-in crashed", name)
        with session._lock:
            session.state = "failed"
            session.detail = f"{type(exc).__name__} during sign-in"
    finally:
        _kill(session)
        _signin_last[name] = session.status()
        with _signin_lock:
            if _signin is session:
                _signin = None
        _reset_probe_cache()


def _run_strategy(settings: Any, name: str, session: SignInSession, binary: str,
                  strategy: SignInStrategy) -> tuple[str, str]:
    """-> (outcome, detail). outcome is signed_in | failed | no_tty | cancelled."""
    argv = [binary] + list(strategy.argv_tail)
    env = cli_env(settings, name)
    # Logging IN must not be able to succeed against a token we already hold:
    # the point of the exercise is a new credential.
    env.pop(CLAUDE_TOKEN_VAR, None)
    env.setdefault("TERM", "xterm-256color")
    home = home_dir(settings, name)
    home.mkdir(parents=True, exist_ok=True)
    try:
        home.chmod(0o700)
    except OSError:
        pass
    env["HOME"] = str(home)
    with session._lock:
        session.strategy = strategy.key
        session._expects_code = strategy.expects_code
        session.state = "awaiting_url"
    try:
        proc, master = _spawn_pty(argv, env, str(home))
    except OSError as exc:
        return "failed", f"could not start {spec(name).label} ({exc.strerror or exc})"
    session._proc = proc
    session._master = master

    reader = threading.Thread(target=_read_pty, args=(session, master), daemon=True,
                              name=f"signin-read-{name}")
    reader.start()

    deadline = session.started_at + SIGNIN_TIMEOUT
    while proc.poll() is None:
        if session._cancel:
            _kill(session)
            return "cancelled", "cancelled"
        if time.monotonic() > deadline:
            _kill(session)
            with session._lock:
                session.state = "failed"
                session.detail = (f"the sign-in was not finished within "
                                  f"{int(SIGNIN_TIMEOUT / 60)} minutes and was "
                                  f"stopped")
            return "failed", "timed out"
        time.sleep(0.2)
    reader.join(timeout=2)
    text = session.tail()
    rc = proc.returncode
    _kill(session)

    if strategy.captures_token:
        token = _extract_token(session)
        if token:
            secrets_boot.write_secret_file(token_path(settings, name), token)
            log.info("%s: stored a long-lived token from %s", name, strategy.key)
            return _confirm(settings, name, session, strategy)
        if rc == 0:
            return "failed", "the CLI finished but printed no token"

    if rc != 0 and not session.url and _looks_like_no_tty(text):
        return "no_tty", text
    if rc != 0 and not session.url:
        return "failed", text or f"{spec(name).label} exited {rc}"
    return _confirm(settings, name, session, strategy)


def _looks_like_no_tty(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in _NO_TTY_MARKERS)


def _extract_token(session: SignInSession) -> str:
    with session._lock:
        buf = session._buffer
    found = _TOKEN_RE.search(buf)
    if not found:
        return ""
    token = found.group(0)
    # The transcript is kept for its ERROR text; the token must not survive in
    # it. (`status()` redacts too -- both, because either alone is one edit
    # away from being the only one.)
    with session._lock:
        session._buffer = _redact(buf)
    return token


def _confirm(settings: Any, name: str, session: SignInSession,
             strategy: SignInStrategy) -> tuple[str, str]:
    """Ask the CLI itself whether it is signed in. The exit code is not
    enough: `auth login` can exit 0 having printed a URL nobody opened."""
    with session._lock:
        session.state = "verifying"
    account = auth_status(settings, name)
    if account.get("logged_in"):
        with session._lock:
            session.state = "signed_in"
            session.account = account
            session.detail = ""
        log.info("%s signed in via %s", name, strategy.key)
        return "signed_in", ""
    detail = account.get("detail") or session.tail() or "the CLI still reports signed out"
    with session._lock:
        session.state = "failed"
        session.detail = detail
    return "failed", detail


def _read_pty(session: SignInSession, master: int) -> None:
    while True:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            return
        if not chunk:
            return
        session.feed(chunk.decode("utf-8", "replace"))


def auth_status(settings: Any, name: str) -> dict:
    """{logged_in, account, method, detail} straight from the CLI.

    Claude Code answers `auth status --json` with {loggedIn, authMethod,
    apiProvider, apiKeySource, email, orgId, orgName, subscriptionType}
    (verified on 2.1.234, 2026-08-18). Codex has no documented equivalent, so
    its answer is best-effort and an unparseable one reads as "unknown", never
    as "signed in".
    """
    binary = cli_binary(settings, name)
    if not binary:
        return {"logged_in": False, "detail": "not installed"}
    argv = ([binary, "auth", "status", "--json"] if name == CLAUDE_CODE
            else [binary, "login", "status"])
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,      # noqa: S603
                              timeout=STATUS_TIMEOUT, env=cli_env(settings, name))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"logged_in": False, "detail": f"could not run the CLI ({type(exc).__name__})"}
    out = (proc.stdout or "").strip()
    err = _redact((proc.stderr or "").strip())[:200]
    if name == CLAUDE_CODE:
        try:
            data = json.loads(out or "{}")
        except ValueError:
            return {"logged_in": False,
                    "detail": _redact(out or err)[:200] or "the CLI answered no JSON"}
        if not isinstance(data, dict) or not data.get("loggedIn"):
            return {"logged_in": False, "detail": "the CLI reports signed out"}
        return {
            "logged_in": True,
            "account": mask_email(str(data.get("email") or "")),
            "method": str(data.get("authMethod") or ""),
            "org": str(data.get("orgName") or ""),
            "plan": str(data.get("subscriptionType") or ""),
            "detail": "",
        }
    if proc.returncode == 0 and out:
        return {"logged_in": True, "account": mask_email(_first_email(out)),
                "method": "codex", "detail": ""}
    return {"logged_in": proc.returncode == 0, "account": "", "method": "codex",
            "detail": _redact(out or err)[:200]}


def _first_email(text: str) -> str:
    found = re.search(r"[^\s<>@]+@[^\s<>@]+\.[A-Za-z]{2,}", text or "")
    return found.group(0) if found else ""


# ---------------------------------------------------------- what the UI asks

def cli_binary(settings: Any, name: str) -> str:
    """The wizard-installed binary. `ai_providers.cli_path` is the one that
    decides what a PROVIDER runs (an admin's typed path still wins); this is
    the narrower question the wizard asks about its own install."""
    if name not in TOOLS or settings is None:
        return ""
    return installed_binary(settings, name)


# Step 0's copy. It is the customer-facing half of
# docs/legal/YOUTUBE_FEATURE_NOTICE.md, held here so the page, the API and
# that document cannot drift apart quietly. Plain sentences, no em dash
# (house style 2026-08-18).
SETUP_NOTICE_TITLE = "This uses YOUR subscription, on a shared server"
SETUP_NOTICE = (
    "Claude Code and Codex are signed in with a personal Claude or ChatGPT "
    "subscription. Every YouTube search this dashboard runs, for every editor, "
    "will be spent on the account you are about to sign in. Using a personal "
    "subscription to power a service may breach its terms: that is your "
    "decision, not ours.\n\n"
    "CC Sync does not ship, bundle or update either tool. When you click "
    "INSTALL, this container downloads the publisher's own build, from the "
    "publisher's own servers, and checks it against the publisher's own "
    "checksum before it is used. Nothing is installed until you click.\n\n"
    "The supported alternative is an API key (Claude API, OpenAI, DeepSeek) "
    "entered on this page, billed to your own account, with no subscription "
    "terms in question."
)
SETUP_NOTICE_CHECKBOX = "I understand this uses my own subscription for a shared server"


def setup_snapshot(conn, settings: Any, name: str) -> dict:
    """Everything the stepper needs, in one poll, WITHOUT a probe.

    No subprocess: this route is polled once a second while a 300 MB download
    runs, and a login probe per poll would be a fork bomb on the customer's
    NAS. The provider row's live status still comes from
    `GET /api/v1/admin/ai-providers`, which is where probing belongs.
    """
    from . import ai_providers

    spec(name)
    supported, why = install_supported(settings)
    install = install_status(settings, name)
    signin = signin_status(settings, name)
    token = bool(read_token(settings, name))
    return {
        "tool": name,
        "label": TOOLS[name].label,
        "publisher": TOOLS[name].publisher,
        "supported": supported,
        "unsupported_detail": why,
        "cli_enabled": ai_providers.cli_enabled(conn, settings),
        "notice": {"title": SETUP_NOTICE_TITLE, "text": SETUP_NOTICE,
                   "checkbox": SETUP_NOTICE_CHECKBOX},
        "install": install,
        "signin": signin,
        "signed_in": signin.get("state") == "signed_in" or token,
        "home": str(home_dir(settings, name)),
        "modes": ([{"value": "subscription", "label": "Claude subscription"},
                   {"value": "console", "label": "Anthropic Console (API billing)"}]
                  if name == CLAUDE_CODE else []),
    }


# ------------------------------------------------------------------- routes
# Admin-only and CSRF-gated exactly like the AI provider routes beside them
# (app.csrf_gate covers /api/v1 with no exemption). Nothing here takes a
# credential in a query string, and nothing here answers with one.

def _admin(request: Request) -> str:
    from . import ai_providers

    return ai_providers._require_admin(request)


def _tool(name: str) -> ToolSpec:
    if name not in TOOLS:
        raise HTTPException(status_code=404,
                            detail=f"{name!r} is not a CLI this wizard can set up")
    return TOOLS[name]


def _require_cli_enabled(conn, settings: Any) -> None:
    from . import ai_providers

    if not ai_providers.cli_enabled(conn, settings):
        raise HTTPException(
            status_code=409,
            detail=("CLI providers are off for this site. Accept the notice in "
                    "step 1 (or tick 'Allow CLI providers') before installing "
                    "anything."))


def _refusal(exc: ToolError) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(exc, ToolBusy) else 400,
                         detail=str(exc))


@router.get("/admin/ai-providers/{name}/setup")
async def api_setup_state(name: str, request: Request, conn=Depends(get_conn)) -> dict:
    _admin(request)
    _tool(name)
    settings = request.app.state.settings
    return await run_in_threadpool(setup_snapshot, conn, settings, name)


@router.post("/admin/ai-providers/{name}/install")
async def api_install(name: str, request: Request, conn=Depends(get_conn)) -> dict:
    """Install (or update to) the publisher's latest build. Returns the first
    status; the page polls `install-status` from there."""
    admin = _admin(request)
    _tool(name)
    settings = request.app.state.settings
    _require_cli_enabled(conn, settings)
    try:
        status = start_install(settings, name)
    except ToolError as exc:
        raise _refusal(exc) from None
    log.info("admin %r started an install of %s", admin, name)
    return status


@router.get("/admin/ai-providers/{name}/install-status")
async def api_install_status(name: str, request: Request) -> dict:
    _admin(request)
    _tool(name)
    return install_status(request.app.state.settings, name)


@router.delete("/admin/ai-providers/{name}/install")
async def api_remove(name: str, request: Request) -> dict:
    admin = _admin(request)
    _tool(name)
    settings = request.app.state.settings
    try:
        status = await run_in_threadpool(remove_install, settings, name)
    except ToolError as exc:
        raise _refusal(exc) from None
    log.info("admin %r removed the %s install", admin, name)
    return status


class SignInIn(BaseModel):
    # "subscription" (the default) or "console" for Anthropic Console billing.
    mode: str = Field(default="subscription", max_length=32)


@router.post("/admin/ai-providers/{name}/signin")
async def api_signin_start(name: str, payload: SignInIn, request: Request,
                           conn=Depends(get_conn)) -> dict:
    admin = _admin(request)
    _tool(name)
    settings = request.app.state.settings
    _require_cli_enabled(conn, settings)
    try:
        status = await run_in_threadpool(start_signin, settings, name, payload.mode)
    except ToolError as exc:
        raise _refusal(exc) from None
    log.info("admin %r started a %s sign-in", admin, name)
    return status


@router.get("/admin/ai-providers/{name}/signin")
async def api_signin_status(name: str, request: Request) -> dict:
    _admin(request)
    _tool(name)
    return signin_status(request.app.state.settings, name)


class CodeIn(BaseModel):
    # In the BODY, never a query string: this is a one-time credential and a
    # query string lands in access logs, browser history and every proxy in
    # between. It is not logged here either.
    code: str = Field(max_length=MAX_CODE_CHARS * 2)


@router.post("/admin/ai-providers/{name}/signin/code")
async def api_signin_code(name: str, payload: CodeIn, request: Request) -> dict:
    _admin(request)
    _tool(name)
    settings = request.app.state.settings
    try:
        return await run_in_threadpool(submit_code, settings, name, payload.code)
    except ToolError as exc:
        raise _refusal(exc) from None


@router.post("/admin/ai-providers/{name}/signin/cancel")
async def api_signin_cancel(name: str, request: Request) -> dict:
    _admin(request)
    _tool(name)
    return await run_in_threadpool(cancel_signin, name)


@router.delete("/admin/ai-providers/{name}/signin")
async def api_sign_out(name: str, request: Request) -> dict:
    admin = _admin(request)
    _tool(name)
    settings = request.app.state.settings
    try:
        status = await run_in_threadpool(sign_out, settings, name)
    except ToolError as exc:
        raise _refusal(exc) from None
    log.info("admin %r signed %s out", admin, name)
    return status
