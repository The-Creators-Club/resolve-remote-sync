"""The yt-dlp sidecar: a standalone binary the companion keeps current itself.

WHY A SIDECAR AND NOT A DEPENDENCY (docs/YTDL_LOCAL_DOWNLOAD.md §6). The
companion is a frozen PyInstaller build on a release cadence of weeks, and
editors sit on whatever build they last accepted -- ruskin ran 0.4.22 for a
month, and on 2026-08-13 a machine was still a day behind a published fix.
yt-dlp needs updating every few weeks because YouTube breaks it deliberately.
Bundling it as an importable library would tie "can this editor download a
clip today" to "did this editor take the last companion release", i.e. the one
variable this fleet has never been able to control. So the companion manages
the STANDALONE BINARY instead: it lives beside the install, it is updated
out-of-band by its own self-updater, and a companion from March can drive a
yt-dlp from this morning.

    Windows:  %LOCALAPPDATA%\\ccsync\\tools\\yt-dlp.exe
    macOS:    ~/Library/Application Support/ccsync/tools/yt-dlp_macos

Everything here is BEST-EFFORT and quiet. A missing, broken or stale binary is
not an error state to nag about -- it means this machine has no local-download
capability, the capability handshake says so, and the fleet degrades to the
server-side downloader that has done the job all along (plan §1/§6). Nothing
in this module may raise into the tray, and nothing in it may hold up startup.

Never-raise ethos and injectable I/O throughout, same conventions as
upgrade.py / reporter.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod
from . import resolve_bridge
from . import upgrade as upgrade_mod

log = logging.getLogger("ccsync.ytdlp")

# (url, headers, timeout) -> file-like response usable as a context manager.
# Deliberately upgrade.HttpOpenFn's signature: two download seams in one
# codebase that disagree about their arguments is how a test stubs the wrong
# one and proves nothing.
HttpOpenFn = Callable[[str, dict, float], Any]
# (argv, timeout) -> object with .returncode / .stdout, i.e. CompletedProcess.
RunFn = Callable[[list, float], Any]

TOOLS_DIR_NAME = "tools"

# yt-dlp's own release asset names. Not derived from anything: these are the
# literal filenames in the GitHub release, and the checksum file is keyed on
# them.
BINARY_NAMES = {"win32": "yt-dlp.exe", "darwin": "yt-dlp_macos"}
DEFAULT_BINARY_NAME = "yt-dlp"

# The official release. `latest/download/<name>` always resolves to the newest
# published release, so no GitHub API call (and no rate limit) is involved.
RELEASE_BASE_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download"
CHECKSUM_ASSET = "SHA2-256SUMS"

# Where a release download is allowed to end up. github.com answers the
# `latest/download` URL with a 302 into its asset CDN, so unlike upgrade.py --
# which refuses every redirect, because there the URL comes from a report
# response an attacker could have written -- this download MUST follow one.
# The pinning that replaces "no redirects at all" is: https only, and only
# into GitHub's own hosts. The sha256 is the real guarantee either way, and it
# is checked before the file is trusted (see install()).
ALLOWED_DOWNLOAD_HOSTS = ("github.com", "www.github.com")
ALLOWED_DOWNLOAD_HOST_SUFFIXES = (".githubusercontent.com",)

# `yt-dlp --version` prints one line: "2026.08.11", or "2026.08.11.232703" for
# a nightly. Anything else is a binary we do not understand, and claiming a
# version we cannot read is worse than reporting none (the capability
# handshake would offer a downloader that may not work).
_VERSION_RE = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}(\.\d+)*$")

# A few seconds, not one: yt-dlp.exe is itself a PyInstaller one-file build, so
# its FIRST run unpacks ~30 MB into %TEMP% before it prints anything, and on a
# cold disk behind an AV scanner that is not instant. Still bounded -- this
# runs on a background thread but a wedged probe would stall the daily check
# forever.
VERSION_TIMEOUT_SECONDS = 15.0
# The dashboard being down must never matter here, so this is short and its
# failure is a shrug (see fetch_client_config).
CONFIG_TIMEOUT_SECONDS = 5.0
# yt-dlp.exe is ~17 MB, yt-dlp_macos ~40 MB (universal2). Generous for an
# editor on a hotel link, bounded so a stalled CDN connection cannot pin the
# thread until the process exits.
DOWNLOAD_TIMEOUT_SECONDS = 300.0
# `yt-dlp -U` downloads a full replacement binary and swaps it, so it gets the
# download budget rather than the probe's.
UPDATE_TIMEOUT_SECONDS = 300.0

# Hard ceilings on what a response may write to the editor's disk, the same
# defence (and the same reasoning) as upgrade.MAX_DOWNLOAD_BYTES: nothing here
# is told a size up front, so without a ceiling a broken or hostile response
# fills the disk.
MAX_DOWNLOAD_BYTES = 150 * 1024 * 1024
MAX_CHECKSUM_BYTES = 1 * 1024 * 1024
MAX_CONFIG_BYTES = 256 * 1024
# What we assume the binary weighs for the pre-flight free-space check. GitHub
# does not advertise a size on the download URL the way the dashboard does
# (upgrade.advertised_size), and a HEAD to find out would be a second request
# down the same redirect chain for a number this check can safely round up.
NOMINAL_BINARY_BYTES = 60 * 1024 * 1024
# upgrade.MIN_FREE_BYTES_MARGIN, imported rather than re-typed: it is the
# margin the 0.7.x free-space work settled on, and two copies of a number that
# means "don't be the thing that fills an editor's disk" would drift. The
# CHECK is mirrored inline below rather than reused, because upgrade's lives
# inside UpgradeManager.download_and_verify and is welded to the dashboard's
# advertised-size handling.
MIN_FREE_BYTES_MARGIN = upgrade_mod.MIN_FREE_BYTES_MARGIN

# On tray start, then daily (plan §6). The delay is the reporter's
# INITIAL_DELAY reasoning: the first seconds after launch belong to the lanes
# and the watcher, and a 17 MB download racing them buys nothing -- nobody can
# ask for a local download before the b-roll page is even open.
INITIAL_DELAY_SECONDS = 30.0
CHECK_INTERVAL_SECONDS = 24 * 3600.0

# ensure()'s `action`, i.e. what it DID. Small and closed on purpose: the
# capability endpoint (later wave) and the tray log both read this.
ACTION_DISABLED = "disabled"    # ytdl_local_downloads = false
ACTION_CHECKED = "checked"      # ytdlp_path override: version read, nothing touched
ACTION_NONE = "none"            # present and current
ACTION_INSTALLED = "installed"
ACTION_UPDATED = "updated"
ACTION_FAILED = "failed"        # needed an install/update and did not get one


# ---------------------------------------------------------------------------
# where it lives
# ---------------------------------------------------------------------------


def binary_name(platform: Optional[str] = None) -> str:
    """yt-dlp's release asset name for this platform."""
    plat = platform if platform is not None else sys.platform
    return BINARY_NAMES.get(plat, DEFAULT_BINARY_NAME)


def tools_dir() -> Path:
    """`ccsync/tools` beside the install -- created by ensure_tools_dir().

    The same derivation the rest of the companion uses for its own directories
    (sync/syncthing_lane.ccsync_config_xml_path, and the `%LOCALAPPDATA%\\ccsync
    \\bin` the installers write the exe into): LOCALAPPDATA with a home-relative
    fallback on Windows, a fixed home-relative path elsewhere. There is no
    second platform-paths scheme here and there must not be one.

    NOTE the macOS answer is `~/Library/Application Support/ccsync/tools`,
    which is NOT beside the macOS install (`~/.local/ccsync/bin`, per
    macos_bootstrap.sh). That is the plan's explicit choice
    (YTDL_LOCAL_DOWNLOAD.md §6) and it is written down here rather than
    quietly "corrected", because the two paths are read by different things:
    this one only ever has to agree with itself.

    sys.platform, not platform.system(): every other platform branch in this
    module (the binary name, CREATE_NO_WINDOW, the chmod) reads sys.platform,
    and one module answering "which OS is this" two ways is how a fake-macOS
    test exercises half a code path.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(base) / "ccsync" / TOOLS_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ccsync" / TOOLS_DIR_NAME
    return Path.home() / ".local" / "ccsync" / TOOLS_DIR_NAME


def configured_override(cfg: Optional[dict[str, Any]]) -> str:
    """`ytdlp_path` from config, or "".

    Set = an editor manages their own yt-dlp (a brew install, a nightly they
    are testing). We then only ever READ its version -- see ensure()."""
    try:
        return str((cfg or {}).get("ytdlp_path", "") or "").strip()
    except Exception:
        return ""


def binary_path(cfg: Optional[dict[str, Any]] = None) -> Path:
    """THE accessor: where this machine's yt-dlp is, managed or overridden.

    Existence is not checked -- callers want the path in order to ask whether
    anything is there (version() returns None when nothing is)."""
    override = configured_override(cfg)
    if override:
        try:
            return Path(override).expanduser()
        except Exception:
            # A path so malformed that Path() itself refuses it. Fall through
            # to the managed location rather than raise out of an accessor;
            # version() will then report None and ensure() says why.
            log.warning("ytdlp: ytdlp_path=%r is not a usable path -- ignoring it", override)
    return tools_dir() / binary_name()


def ensure_tools_dir() -> Optional[Path]:
    """Create the tools dir and return it, or None if it cannot be made."""
    directory = tools_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        return directory
    except OSError as exc:
        log.warning("ytdlp: could not create %s (%s)", directory, exc)
        return None


def local_downloads_enabled(cfg: Optional[dict[str, Any]]) -> bool:
    """The master opt-out (`ytdl_local_downloads`, plan §13 Q3).

    Absent means opted IN -- the feature is the fleet default and the key
    exists for the editor on a metered or tethered link. Anything that isn't a
    bool is treated as on and logged, exactly as proxy_generation_enabled
    treats a hand-edited non-boolean: bool("false") is True, so a string here
    cannot be coerced honestly."""
    value = (cfg or {}).get(
        "ytdl_local_downloads", config_mod.DEFAULTS.get("ytdl_local_downloads", True)
    )
    if isinstance(value, bool):
        return value
    if value is not None:
        log.error(
            "config: ytdl_local_downloads=%r is not true/false -- treating it as true",
            value,
        )
    return True


# ---------------------------------------------------------------------------
# versions
# ---------------------------------------------------------------------------


def parse_version_output(text: Any) -> Optional[str]:
    """The YYYY.MM.DD string out of `yt-dlp --version` output, or None.

    First non-blank line only, and it must look like a yt-dlp version. A
    binary that prints a banner, an error, or nothing at all is reported as
    "no version", which the whole module treats as "no capability"."""
    try:
        for line in str(text or "").splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            return candidate if _VERSION_RE.match(candidate) else None
    except Exception:
        log.debug("ytdlp: could not parse a version out of %r", text, exc_info=True)
    return None


def version_is_older(current: Any, minimum: Any) -> bool:
    """True when `current` is a yt-dlp older than `minimum`.

    upgrade.parse_version does the ranking: it is strict (it refuses to order
    anything it does not fully understand) and returning False for an
    unrankable pair is the safe direction -- it means "don't touch the
    binary", never "replace it on a guess".

    THIS IS THE CORRECT ORDERING and the dashboard's is not (COMP-BROLL-9,
    2026-08-14): routes_fleet._version_at_least compares the two strings raw,
    which is exact for yt-dlp's own zero-padded YYYY.MM.DD output and wrong for
    the free-text YTDL_MIN_YTDLP_VERSION an operator types -- '2026.08.11' >=
    '2026.8.5' is False lexicographically and True by version. See
    version_floor_is_rankable for what this side does about it."""
    left = upgrade_mod.parse_version(current)
    right = upgrade_mod.parse_version(minimum)
    if left is None or right is None:
        return False
    return left < right


def version_floor_is_rankable(minimum: Any) -> bool:
    """Can the fleet's yt-dlp floor be ordered against a real version at all?

    A floor this returns False for is a floor that silently means "never
    update" on this side -- version_is_older refuses to rank it -- while the
    dashboard, which compares raw strings, may be 403-ing every claim in the
    fleet with it (COMP-BROLL-9). Nothing here can fix a value that lives in
    the container's environment, so ensure() says so out loud instead."""
    return upgrade_mod.parse_version(minimum) is not None


def _win_creationflags() -> int:
    """CREATE_NO_WINDOW. The companion is a windowed build (build.spec,
    console=False), so an unflagged spawn flashes a console window on the
    editor's desktop -- and this one runs unattended, daily, plus once per
    capability probe. Same one-line copy, for the same reason, as
    ffmpeg_tools._win_creationflags (:79-92) and rclone_lane's. A no-op off
    Windows."""
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def _default_run(argv: list, timeout: float) -> Any:
    """Run a yt-dlp command, captured, windowless, with a sanitized env.

    resolve_bridge.sanitized_child_env() is not optional here: PYTHONHOME /
    PYTHON3HOME are pinned process-wide at OUR _MEIPASS so fusionscript loads
    our python3.dll (AUDIT_2 CORE-M6), and yt-dlp.exe is ITSELF a frozen
    Python. Inheriting them points the child's interpreter at our extraction
    dir, which is the same class of failure as music_server.call's child and
    the self-upgrade's spawn.

    stdin is closed: a windowed build has no console, and a yt-dlp that
    decided to prompt would otherwise block until the timeout."""
    return subprocess.run(
        argv,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        creationflags=_win_creationflags(),
        env=resolve_bridge.sanitized_child_env(),
    )


def version(
    binary: Optional[Any] = None,
    cfg: Optional[dict[str, Any]] = None,
    run_fn: Optional[RunFn] = None,
    timeout: float = VERSION_TIMEOUT_SECONDS,
) -> Optional[str]:
    """`<binary> --version`, parsed. None for every failure there is.

    Missing, not executable, non-zero exit, timeout, garbage on stdout, a
    binary quarantined by an AV scanner -- all of them mean the same thing to
    every caller (no capability), so they are all None rather than five
    exception types nobody would branch on differently."""
    path = Path(binary) if binary is not None else binary_path(cfg)
    run = run_fn or _default_run
    try:
        if not path.exists():
            return None
    except OSError:
        return None
    try:
        proc = run([str(path), "--version"], timeout)
    except subprocess.TimeoutExpired:
        log.warning("ytdlp: %s did not answer --version within %.0fs", path, timeout)
        return None
    except Exception as exc:
        log.info("ytdlp: %s could not be run (%s)", path, exc)
        return None
    if getattr(proc, "returncode", 1) != 0:
        log.info("ytdlp: %s --version exited %s", path, getattr(proc, "returncode", "?"))
        return None
    return parse_version_output(getattr(proc, "stdout", ""))


# ---------------------------------------------------------------------------
# http
# ---------------------------------------------------------------------------


def default_dashboard_open(url: str, headers: dict, timeout: float):
    """GET the dashboard, following NO redirects.

    upgrade.build_no_redirect_opener's chain verbatim (AUDIT_3 H-1): the
    dashboard is plain HTTP on the tailnet, and a 302 in one of its answers
    would move this request -- and any header on it -- to a host of the
    redirect's choosing. Nothing here needs a redirect to work."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    return upgrade_mod.build_no_redirect_opener().open(req, timeout=timeout)


def is_allowed_release_url(url: Any) -> bool:
    """True for an https URL on GitHub or its asset CDN. Never raises."""
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
    except Exception:
        return False
    if parsed.scheme.lower() != "https":
        return False
    host = (parsed.hostname or "").lower()
    if host in ALLOWED_DOWNLOAD_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in ALLOWED_DOWNLOAD_HOST_SUFFIXES)


class GithubRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow GitHub's release redirect, and only GitHub's.

    `releases/latest/download/<asset>` is a 302 into GitHub's asset CDN, so
    unlike the dashboard opener above this chain has to be followed. What is
    pinned instead is where it may land: https, on github.com or
    *.githubusercontent.com. A redirect anywhere else raises rather than being
    fetched -- the sha256 below would catch a swapped artifact anyway, but
    "the check would have caught it" is not a reason to make the request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        if not is_allowed_release_url(newurl):
            log.error(
                "ytdlp: REFUSING a yt-dlp download redirect off GitHub (%s) -- "
                "nothing was downloaded", newurl,
            )
            raise urllib.error.HTTPError(
                newurl, code, "refused an off-origin redirect", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_github_open(url: str, headers: dict, timeout: float):
    if not is_allowed_release_url(url):
        raise ValueError(f"refusing a non-GitHub yt-dlp URL: {url!r}")
    req = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(GithubRedirectHandler)
    return opener.open(req, timeout=timeout)


def _read_capped(resp: Any, ceiling: int) -> bytes:
    """Read a response body, refusing to write more than `ceiling` bytes."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = resp.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > ceiling:
            raise ValueError(f"response exceeded the {ceiling // (1024 * 1024)} MB ceiling")
        chunks.append(chunk)
    return b"".join(chunks)


def parse_checksums(text: Any, name: str) -> Optional[str]:
    """`<sha256>  <filename>` lines -> the digest for `name`, lowercased.

    None when the asset is not listed, which install() treats as a refusal:
    a release whose SHA2-256SUMS does not mention the file we are about to
    write over an editor's downloader is not a release we can verify."""
    try:
        for line in str(text or "").splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            digest, filename = parts[0].strip().lower(), parts[-1].strip().lstrip("*")
            if filename == name and len(digest) == 64:
                return digest
    except Exception:
        log.debug("ytdlp: could not parse the checksum list", exc_info=True)
    return None


# ---------------------------------------------------------------------------
# the manager
# ---------------------------------------------------------------------------


class YtDlpManager:
    """Keeps this machine's yt-dlp present and current. Never raises.

    Thread model: ensure() is called from the manager's own daily thread and
    (later) from the capability endpoint's handler, so the cached status goes
    through _lock and the work itself through _work_lock -- two ensures at
    once would race the same rename."""

    def __init__(
        self,
        cfg: dict[str, Any],
        http_open: Optional[HttpOpenFn] = None,
        github_open: Optional[HttpOpenFn] = None,
        run_fn: Optional[RunFn] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.cfg = cfg or {}
        self._http_open = http_open or default_dashboard_open
        self._github_open = github_open or default_github_open
        self._run = run_fn or _default_run
        self._clock = clock
        self._lock = threading.Lock()
        self._work_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._status: dict[str, Any] = {
            "ok": False,
            "version": None,
            "action": None,
            "message": "not checked yet",
        }

    # -- config-derived, zero-I/O ----------------------------------------
    @property
    def enabled(self) -> bool:
        return local_downloads_enabled(self.cfg)

    @property
    def override_path(self) -> str:
        return configured_override(self.cfg)

    def binary(self) -> Path:
        return binary_path(self.cfg)

    def status(self) -> dict[str, Any]:
        """The last ensure() result. Lock-guarded and does NO I/O -- the rule
        youtube_import.status() and proxy_gen.gap() obey, because the tray's
        refresh thread reads these and must never block on a subprocess."""
        with self._lock:
            return dict(self._status)

    def _publish(self, ok: bool, version_str: Optional[str], action: str,
                 message: str) -> dict[str, Any]:
        status = {"ok": bool(ok), "version": version_str, "action": action,
                  "message": message, "checked_at": self._clock()}
        with self._lock:
            self._status = dict(status)
        return status

    # -- the dashboard's floor -------------------------------------------
    def fetch_client_config(self) -> Optional[dict[str, Any]]:
        """GET {dashboard_url}/ytdl/api/config/ytdl-client, or None.

        None for everything: no dashboard_url, a connection error, a 500, a
        body that isn't JSON. The dashboard being down must never matter here
        -- it only means we cannot learn today's floor, and ensure() then
        leaves a working binary alone rather than guessing.

        Unauthenticated on purpose (plan §4: "nothing secret"). Sending the
        report token would put it on a request whose only job is to read a
        version number, for no gain."""
        base = str(self.cfg.get("dashboard_url", "") or "").strip().rstrip("/")
        if not base:
            log.debug("ytdlp: no dashboard_url -- no min_ytdlp_version to fetch")
            return None
        url = f"{base}/ytdl/api/config/ytdl-client"
        try:
            with self._http_open(url, {}, CONFIG_TIMEOUT_SECONDS) as resp:
                raw = _read_capped(resp, MAX_CONFIG_BYTES)
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as exc:
            log.debug("ytdlp: could not read the ytdl client config (%s)", exc)
            return None
        return data if isinstance(data, dict) else None

    def fetch_min_version(self) -> Optional[str]:
        """`min_ytdlp_version` from the dashboard, or None."""
        data = self.fetch_client_config()
        if not data:
            return None
        value = str(data.get("min_ytdlp_version") or "").strip()
        return value or None

    def _floor(self, min_version: Optional[str]) -> Optional[str]:
        """The version floor to compare against, with a word when it is junk.

        COMP-BROLL-9 (2026-08-14): an unrankable floor ('2026.8', 'latest',
        '2026.08.11-nightly') is not harmless. This side refuses to rank it and
        therefore never updates, while the dashboard -- which ranks the raw
        strings -- can be refusing every claim in the fleet with the same
        value. Left unsaid, the only evidence anywhere is a 403 whose message
        contradicts the daily "yt-dlp X is current" in every companion's log.
        """
        floor = min_version if min_version is not None else self.fetch_min_version()
        if floor and not version_floor_is_rankable(floor):
            log.error(
                "ytdlp: the dashboard's minimum yt-dlp version %r is not a "
                "version this can rank, so nothing here will ever update to "
                "meet it -- and the dashboard may be refusing every local "
                "download in the fleet over it. Set YTDL_MIN_YTDLP_VERSION to "
                "a zero-padded YYYY.MM.DD.", floor,
            )
        return floor

    # -- install ---------------------------------------------------------
    def _free_space_ok(self, directory: Path) -> bool:
        """Refuse the download when the disk cannot take it.

        BEFORE the download, and the 0.7.x upgrade lesson is why: the check
        that runs after the bytes are already on disk is not a check. Mirrors
        upgrade.download_and_verify's margin + expected-size arithmetic; a
        check that cannot be made at all (an exotic mount, a path that has
        gone away) is not treated as a failure, exactly as it isn't there."""
        try:
            free = shutil.disk_usage(str(directory)).free
        except Exception:
            log.debug("ytdlp: free-space check failed; continuing", exc_info=True)
            return True
        needed = MIN_FREE_BYTES_MARGIN + NOMINAL_BINARY_BYTES
        if free < needed:
            log.warning(
                "ytdlp: %.0f MB free at %s but yt-dlp needs about %.0f MB (+ margin) "
                "-- not downloading it. Local YouTube downloads stay off on this "
                "machine; the server downloads instead.",
                free / 1_000_000, directory, needed / 1_000_000,
            )
            return False
        return True

    def _fetch_expected_sha256(self, name: str) -> Optional[str]:
        url = f"{RELEASE_BASE_URL}/{CHECKSUM_ASSET}"
        try:
            with self._github_open(url, {}, CONFIG_TIMEOUT_SECONDS * 4) as resp:
                raw = _read_capped(resp, MAX_CHECKSUM_BYTES)
        except Exception as exc:
            log.info("ytdlp: could not fetch %s (%s)", CHECKSUM_ASSET, exc)
            return None
        digest = parse_checksums(raw.decode("utf-8", "replace"), name)
        if digest is None:
            log.warning(
                "ytdlp: %s does not list %s -- refusing to install an artifact "
                "the release does not vouch for", CHECKSUM_ASSET, name,
            )
        return digest

    @staticmethod
    def _make_executable(path: Path) -> None:
        """The execute bit on POSIX, AFTER the sha256 check.

        Same rule and the same ordering as upgrade.UpgradeManager
        ._make_executable (:574-602) -- an unverified download must never be
        made runnable, however briefly -- written out here rather than
        reaching into that class's private staticmethod. open("wb") leaves
        0644 under the usual umask and macOS will not exec that. Windows has
        no execute bit (chmod there only toggles read-only), so it is never
        called on win32. Never raises: a chmod that fails on an exotic mount
        must not throw away a verified download -- version() will report None
        if the file genuinely cannot run."""
        if sys.platform == "win32":
            return
        try:
            os.chmod(path, 0o755)
        except OSError as exc:
            log.warning("ytdlp: could not set the execute bit on %s (%s)", path, exc)

    def install(self) -> bool:
        """Download the platform binary, verify it, and put it in place.

        Order is load-bearing: make the directory, check free space, fetch the
        release's own SHA2-256SUMS, stream the asset to a TEMP name in the
        same directory, compare the digest, and only then os.replace() it onto
        the real name. A mismatch, a short read, a full disk or a killed
        process therefore leaves the previous binary exactly as it was and no
        partial file behind -- the rename is the only moment anything visible
        changes, and it is atomic within the directory.

        False on every failure, never an exception."""
        directory = ensure_tools_dir()
        if directory is None:
            return False
        name = binary_name()
        if not self._free_space_ok(directory):
            return False
        expected = self._fetch_expected_sha256(name)
        if expected is None:
            return False

        url = f"{RELEASE_BASE_URL}/{name}"
        # ".new", beside the destination: a rename is only atomic within one
        # filesystem, and %TEMP% is routinely on another volume.
        tmp = directory / (name + ".new")
        digest = hashlib.sha256()
        written = 0
        try:
            with self._github_open(url, {}, DOWNLOAD_TIMEOUT_SECONDS) as resp:
                status = upgrade_mod.redirect_status(resp)
                if status is not None:
                    # An injected opener handed back an unfollowed 3xx --
                    # belt to GithubRedirectHandler's braces, same check and
                    # the same reason as upgrade.download_and_verify's.
                    raise ValueError(f"yt-dlp download answered HTTP {status}")
                with tmp.open("wb") as fh:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_DOWNLOAD_BYTES:
                            raise ValueError(
                                f"yt-dlp download exceeded the "
                                f"{MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB ceiling"
                            )
                        fh.write(chunk)
                        digest.update(chunk)
        except Exception as exc:
            log.info("ytdlp: download failed (%s) -- no local downloader on this machine", exc)
            _unlink_quietly(tmp)
            return False

        if digest.hexdigest() != expected:
            log.warning(
                "ytdlp: sha256 mismatch on the downloaded %s -- discarding it and "
                "keeping whatever was already installed", name,
            )
            _unlink_quietly(tmp)
            return False

        self._make_executable(tmp)
        try:
            os.replace(tmp, directory / name)
        except Exception as exc:
            log.warning("ytdlp: could not move the verified download into place (%s)", exc)
            _unlink_quietly(tmp)
            return False
        log.info("ytdlp: installed %s", directory / name)
        return True

    def self_update(self) -> bool:
        """`yt-dlp -U`: its OWN self-updater, which handles the in-place swap
        on all three platforms (plan §6). Deliberately not a re-download +
        rename of our own: yt-dlp knows how to replace a running binary on
        each OS, and a second mechanism doing the same job differently is one
        more thing to be wrong on the one platform nobody tested."""
        path = self.binary()
        try:
            proc = self._run([str(path), "-U"], UPDATE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            log.warning("ytdlp: -U did not finish within %.0fs", UPDATE_TIMEOUT_SECONDS)
            return False
        except Exception as exc:
            log.info("ytdlp: -U could not be run (%s)", exc)
            return False
        if getattr(proc, "returncode", 1) != 0:
            log.info(
                "ytdlp: -U exited %s (%s)", getattr(proc, "returncode", "?"),
                str(getattr(proc, "stderr", "") or "").strip()[:200],
            )
            return False
        return True

    # -- the one entry point ---------------------------------------------
    def ensure(self, min_version: Optional[str] = None) -> dict[str, Any]:
        """Make this machine's yt-dlp present and current, if it should be.

        The whole decision table:

            opt-out (ytdl_local_downloads=false) -> nothing, action=disabled
            ytdlp_path override                  -> version check ONLY
            binary missing                       -> install
            binary older than min_version        -> yt-dlp -U
            otherwise                            -> nothing

        `min_version` defaults to the dashboard's `min_ytdlp_version`; when
        that cannot be fetched it stays None and a PRESENT binary is left
        alone -- an unreachable dashboard is not evidence that anything is
        stale.

        Returns {ok, version, action, message}: `ok` means "there is a yt-dlp
        here whose version we could read, and it is not below the floor", i.e.
        exactly what the capability handshake will answer with. Never raises.
        """
        if not self.enabled:
            return self._publish(
                False, None, ACTION_DISABLED,
                "local YouTube downloads are switched off in config "
                "(ytdl_local_downloads = false)",
            )

        with self._work_lock:
            override = self.override_path
            if override:
                # NEVER install or update over a hand-managed binary. An
                # editor who put yt-dlp somewhere themselves owns it, and a
                # background thread replacing it -- or running `-U` against a
                # brew-managed copy, which fights brew for the file -- is the
                # kind of surprise that gets a companion uninstalled.
                current = version(cfg=self.cfg, run_fn=self._run)
                floor = self._floor(min_version)
                if current is None:
                    return self._publish(
                        False, None, ACTION_CHECKED,
                        f"ytdlp_path is set to {override} but nothing runnable is "
                        f"there -- leaving it alone (nothing is installed over an "
                        f"override)",
                    )
                if floor and version_is_older(current, floor):
                    return self._publish(
                        False, current, ACTION_CHECKED,
                        f"your own yt-dlp at {override} is {current}, older than the "
                        f"{floor} the dashboard asks for -- update it yourself, or "
                        f"clear ytdlp_path to let the companion manage one",
                    )
                return self._publish(
                    True, current, ACTION_CHECKED,
                    f"using your own yt-dlp at {override} ({current})",
                )

            current = version(cfg=self.cfg, run_fn=self._run)
            floor = self._floor(min_version)

            if current is None:
                if not self.install():
                    return self._publish(
                        False, None, ACTION_FAILED,
                        "no yt-dlp on this machine and it could not be installed "
                        "-- YouTube downloads stay on the server",
                    )
                current = version(cfg=self.cfg, run_fn=self._run)
                ok = current is not None and not (floor and version_is_older(current, floor))
                return self._publish(
                    ok, current, ACTION_INSTALLED,
                    f"installed yt-dlp {current or '(version unreadable)'}",
                )

            if floor and version_is_older(current, floor):
                updated = self.self_update()
                after = version(cfg=self.cfg, run_fn=self._run) if updated else current
                ok = after is not None and not version_is_older(after, floor)
                if not updated:
                    return self._publish(
                        False, current, ACTION_FAILED,
                        f"yt-dlp {current} is older than the {floor} the dashboard "
                        f"asks for and it could not update itself -- YouTube "
                        f"downloads stay on the server",
                    )
                return self._publish(
                    ok, after, ACTION_UPDATED,
                    f"updated yt-dlp {current} -> {after or '(version unreadable)'}",
                )

            return self._publish(True, current, ACTION_NONE, f"yt-dlp {current} is current")

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """One background thread: ensure() now, then daily (plan §6).

        Nothing about this may block or crash the tray, so it is a daemon
        thread whose loop swallows everything, exactly like the LUT link
        thread (app._lut_link_loop) it sits next to. A machine that never
        manages to get a yt-dlp simply keeps the behaviour it has always had:
        the server downloads."""
        if self._thread is not None:
            return
        if not self.enabled:
            log.info("ytdlp: local YouTube downloads are disabled by config")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="ccsync-ytdlp", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Never blocks -- join() is the caller's separate decision."""
        self._stop_event.set()

    def join(self, timeout: float = 5.0) -> None:
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        try:
            thread.join(timeout=timeout)
        except Exception:
            log.exception("ytdlp: failed to join the sidecar thread")

    def _loop(self) -> None:
        if self._stop_event.wait(INITIAL_DELAY_SECONDS):
            return
        while not self._stop_event.is_set():
            try:
                status = self.ensure()
                # INFO, once a day, and never a dialog: a machine without the
                # capability is not broken, it is a machine that downloads on
                # the server like every machine did before this existed.
                log.info("ytdlp: %s", status.get("message"))
            except Exception:
                log.exception("ytdlp: the daily check failed")
            try:
                # ffmpeg + deno on the same thread and cadence (sidecar_tools,
                # 2026-08-16): yt-dlp without a merger refuses every rung this
                # fleet uses, and without a JS runtime it refuses every
                # signed-in request -- and no editor machine had either. Its
                # own try: a failed sidecar install must not be mistaken for
                # a yt-dlp failure, and vice versa. Same opt-out, checked
                # inside.
                from . import sidecar_tools
                status = sidecar_tools.ensure(self.cfg, github_open=self._github_open)
                log.info("sidecar: %s", status.get("message"))
            except Exception:
                log.exception("sidecar: the daily check failed")
            if self._stop_event.wait(CHECK_INTERVAL_SECONDS):
                return


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
