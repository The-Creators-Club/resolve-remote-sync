"""Companion self-upgrade (notify + one-click).

The dashboard advertises the published "current" build in its report/verify
responses as a conditional `upgrade` key (absent = up to date -- see the
dashboard's api._upgrade_info). The reporter hands every report response to
UpgradeManager.note_report_response(); when an upgrade is available the tray
grows an "Update now" item, and apply() does the whole swap:

    download to <exe dir>/ccsync-companion.new[.exe] -> sha256 verify
    -> chmod 0o755                   (POSIX only -- see _make_executable)
    -> os.replace(exe, exe.old)      (a RUNNING exe can't be overwritten on
                                      Windows, but it CAN be renamed on the
                                      same volume -- hence same-dir download.
                                      macOS needs the same dance for a
                                      different reason: overwriting a running
                                      Mach-O in place breaks its pages and
                                      its ad-hoc signature)
    -> os.replace(new, exe)
    -> spawn the new exe detached    (failure here ROLLS BACK both renames
                                      and keeps the current build running)
    -> request_shutdown()

Platform shape: Windows ships `ccsync-companion.exe`; macOS ships a bare
single-file Mach-O called `ccsync-companion` (no extension, no .app bundle),
ad-hoc signed by PyInstaller -- the signature is part of the file, so it
travels through os.replace untouched. Every name and every spawn flag below
is therefore platform-derived, never hardcoded to the Windows shape.

The stale `.old` is deleted on the NEXT startup (cleanup_old_exe) because the
new process may start while the old one still holds its own image briefly.

"Different, not newer": the server only advertises when the current published
version differs from what we reported, so an admin rollback is offered to the
fleet exactly like an upgrade. The DOWNLOAD/SWAP machinery still compares
nothing -- but the WORDING must (see compare_to_running / offer_label): a
rollback offer that reads "Update available" is a one-click downgrade.

Never-raise ethos throughout, injectable I/O for tests (same conventions as
reporter.py).
"""
from __future__ import annotations

import hashlib
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

log = logging.getLogger("ccsync.upgrade")

# (url, headers, timeout) -> file-like response usable as a context manager.
HttpOpenFn = Callable[[str, dict, float], Any]
ReplaceFn = Callable[[Path, Path], Any]
SpawnFn = Callable[[Path], Any]

# Generous: editors may be on slow links and the exe is ~20 MB.
DOWNLOAD_TIMEOUT = 600.0
_NEW_STEM = "ccsync-companion.new"
# Platform-neutral: appended to whatever the running binary is called, so it
# is `ccsync-companion.exe.old` on Windows and `ccsync-companion.old` on macOS
# without any per-platform spelling.
_OLD_SUFFIX = ".old"
# The published exe is ~20 MB. A ceiling stops a hostile or broken response
# filling the editor's disk (there was none at all), and the free-space check
# stops a download that cannot possibly complete (AUDIT_2 §2-low).
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
MIN_FREE_BYTES_MARGIN = 200 * 1024 * 1024
_VERSION_MARKER = "last_version.txt"


def note_version_start(state_dir: Path) -> bool:
    """Record the running version and report whether it CHANGED.

    "Is this the first start on a freshly-upgraded build?" used to be derived
    from whether cleanup_old_exe() managed to unlink an `.old`. That is wrong
    twice over: it forced the rollback copy to be destroyed before the new
    build had proven anything, and when an AV hold deferred the unlink it
    fired the "Update complete. Now running vX" toast on an unrelated later
    restart (AUDIT_2 CORE-H6). Never raises; a marker that can't be read or
    written just means no toast."""
    try:
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        marker = state_dir / _VERSION_MARKER
        try:
            previous = marker.read_text(encoding="utf-8").strip()
        except OSError:
            previous = ""
        if previous != config_mod.VERSION:
            tmp = marker.with_name(marker.name + ".tmp")
            tmp.write_text(config_mod.VERSION, encoding="utf-8")
            os.replace(tmp, marker)
        # A first-ever run (no marker) is not an upgrade.
        return bool(previous) and previous != config_mod.VERSION
    except Exception:
        log.debug("note_version_start failed", exc_info=True)
        return False


def same_origin(url: str, base_url: str) -> bool:
    """True when `url` is relative, or shares scheme+host+port with `base_url`.

    `upgrade.url` arrives inside a plain-HTTP /api/v1/report response, and
    the sha256 that "verifies" the download comes from that SAME response --
    so anyone able to answer or alter one report response could hand the
    companion an arbitrary exe plus its matching hash, which is then renamed
    over the running companion and launched detached. Tailnet-only limits
    exposure; there was no origin check at all (AUDIT_2 CORE-M10)."""
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme and not parsed.netloc:
        return True  # relative -- resolved against dashboard_url below
    base = urllib.parse.urlparse(str(base_url or "").strip())
    if not base.netloc:
        return False
    return (parsed.scheme.lower(), parsed.netloc.lower()) == (
        base.scheme.lower(), base.netloc.lower()
    )


def platform_key() -> str:
    """The dashboard's platform discriminator for this machine."""
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def new_download_name() -> str:
    """The temp filename the update is streamed to, beside the running binary.

    This was hardcoded to `ccsync-companion.new.exe`, which on macOS would
    have written a Windows-shaped name next to (and then renamed it over) an
    extensionless Mach-O. Harmless on its own -- os.replace does not care what
    a file is called -- but it is the same "the exe is a .exe" assumption that
    hid the missing chmod, and a leftover `.new.exe` on a Mac is a support
    call. Derived from sys.platform, never from the advertised URL: the URL is
    server-supplied and the dashboard's macOS package path has no extension at
    all."""
    return _NEW_STEM + (".exe" if sys.platform == "win32" else "")


class _RedirectRefused(Exception):
    """An injected http_open handed us an already-followed/3xx response."""

    def __init__(self, code: int) -> None:
        super().__init__(f"update URL answered HTTP {code} (redirect) -- refused")
        self.code = code


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A redirect handler that refuses every redirect.

    Returning None from redirect_request() makes urllib fall through to the
    default error handler, i.e. the 3xx surfaces as an HTTPError instead of
    being followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def build_no_redirect_opener(*handlers) -> urllib.request.OpenerDirector:
    """An opener that will NOT follow redirects.

    same_origin() is checked once, BEFORE the request -- but
    urllib.request.urlopen follows 3xx automatically, so a dashboard answer
    of `302 Location: http://attacker/build.exe` bounced the download
    off-origin AND re-sent the X-CCSync-Token header to whatever host the
    redirect chose (urllib only strips credentials, not custom headers). The
    sha256 is no defence: it comes from the same response that supplied the
    URL, so it proves the integrity of exactly the file the redirect chose.
    The result is renamed over the running companion and launched detached
    (AUDIT_3 H-1, tightening AUDIT_2 CORE-M10).

    Extra `handlers` exist so a test can drive the real chain."""
    return urllib.request.build_opener(NoRedirectHandler, *handlers)


def default_http_open(url: str, headers: dict, timeout: float):
    req = urllib.request.Request(url, headers=headers, method="GET")
    return build_no_redirect_opener().open(req, timeout=timeout)


def redirect_status(resp: Any) -> Optional[int]:
    """The 3xx status of an already-open response, or None.

    Belt to build_no_redirect_opener's braces: `http_open` is injectable
    (tests, and any future transport), so download_and_verify checks what it
    was actually handed rather than trusting the opener alone."""
    for attr in ("status", "code"):
        value = getattr(resp, attr, None)
        try:
            if value is not None and 300 <= int(value) < 400:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def cleanup_old_exe(exe_path: Optional[Path] = None) -> bool:
    """Delete the `<exe>.old` a previous apply() left behind. Swallows
    OSError entirely -- an AV scanner may still hold the file; we simply try
    again on the next start. At most one `.old` ever exists.

    Returns True when an `.old` was actually removed. NOTE: callers must not
    use that as "we just upgraded" -- see note_version_start(), which is what
    app.run() uses now (AUDIT_2 CORE-H6). Retries a few times because the
    usual cause of failure is a transient AV/indexer hold seconds after the
    rename."""
    try:
        if exe_path is None:
            if not is_frozen():
                return False
            exe_path = Path(sys.executable)
        old = exe_path.with_name(exe_path.name + _OLD_SUFFIX)
        if not old.exists():
            return False
        for attempt in range(3):
            try:
                old.unlink()
                log.info("upgrade: removed the previous build at %s", old)
                return True
            except OSError as exc:
                log.debug("cleanup_old_exe: attempt %d failed (%s)", attempt + 1, exc)
                time.sleep(1.0)
        log.info("cleanup_old_exe: %s is still locked; will retry next start", old)
        return False
    except Exception:
        log.debug("cleanup_old_exe failed", exc_info=True)
        return False


def parse_upgrade(resp: Any) -> Optional[dict[str, Any]]:
    """Extract + validate the `upgrade` dict from a report/verify response.

    None for anything unusable, and None when the advertised version equals
    the running one (the server omits the key then, but belt and braces --
    offering a "downgrade" to the version already running would loop)."""
    if not isinstance(resp, dict):
        return None
    info = resp.get("upgrade")
    if not isinstance(info, dict):
        return None
    version = str(info.get("version") or "").strip()
    url = str(info.get("url") or "").strip()
    sha256 = str(info.get("sha256") or "").strip().lower()
    if not version or not url or len(sha256) != 64:
        return None
    if version == config_mod.VERSION:
        return None
    return {"version": version, "url": url, "sha256": sha256,
            "size_bytes": info.get("size_bytes")}


def advertised_size(info: Any) -> Optional[int]:
    """`size_bytes` as a usable positive int, or None.

    None for anything unusable -- absent (an older dashboard), zero, negative,
    non-numeric, or larger than the hard ceiling. Callers must treat None as
    "unknown size", never as zero: a bogus value must not be able to refuse a
    legitimate update or wave a huge one through. Never raises."""
    try:
        size = int((info or {}).get("size_bytes") or 0)
    except (AttributeError, TypeError, ValueError):
        return None
    if size <= 0 or size > MAX_DOWNLOAD_BYTES:
        return None
    return size


# --------------------------------------------------------------- wording
#
# The offer is "different, not newer" by design (see the module docstring),
# so the SAME machinery advertises an admin rollback and a genuine upgrade.
# Calling both of them "Update available" is what made the tray on this rig
# offer "Update available -> v0.4.3 (install)" while it was running v0.4.5
# (seen live 2026-07-25): one click would have DOWNGRADED the machine and
# reintroduced a whole round of security fixes. The install path is
# unchanged -- only the words, which are the only thing the human has.

_NUMERIC_PART = re.compile(r"^\d+$")

VERSION_NEWER = "newer"
VERSION_OLDER = "older"
VERSION_SAME = "same"
VERSION_UNKNOWN = "unknown"


def parse_version(text: Any) -> Optional[tuple[int, ...]]:
    """A plain dotted-numeric version string as a tuple of ints.

    "0.4.5" -> (0, 4, 5); "v1.2" -> (1, 2). None for ANYTHING else ("",
    "nightly", "0.4.5-hotfix", None), which callers must treat as "ordering
    unknown" and word neutrally.

    Deliberately strict rather than "compare the numeric prefix and ignore
    the rest": truncating "0.4.5-hotfix" to (0, 4) makes it compare OLDER
    than the 0.4.5 it is a hotfix for, and this function's only consumer is
    the sentence that tells an editor whether they are about to upgrade or
    downgrade. Refusing to rank a string we don't fully understand costs a
    neutral label; ranking it wrong costs the wrong click. Never raises."""
    try:
        raw = str(text or "").strip()
        if raw[:1] in ("v", "V"):
            raw = raw[1:]
        parts = raw.split(".")
        if not parts or not all(_NUMERIC_PART.match(part) for part in parts):
            return None
        return tuple(int(part) for part in parts)
    except Exception:
        log.debug("parse_version(%r) failed", text, exc_info=True)
        return None


def compare_to_running(version: Any, running: Optional[str] = None) -> str:
    """"newer" / "older" / "same" / "unknown" for `version` vs the build we
    are running. Never raises -- anything unparseable on either side is
    "unknown", which the labels below render in neutral wording rather than
    guessing a direction."""
    try:
        offered = parse_version(version)
        current = parse_version(config_mod.VERSION if running is None else running)
        if offered is None or current is None:
            return VERSION_UNKNOWN
        if offered > current:
            return VERSION_NEWER
        if offered < current:
            return VERSION_OLDER
        return VERSION_SAME
    except Exception:
        log.debug("compare_to_running(%r) failed", version, exc_info=True)
        return VERSION_UNKNOWN


def offer_label(version: Any, running: Optional[str] = None) -> str:
    """The tray menu item for an available build. The word "update" appears
    ONLY when the offered build really is newer."""
    order = compare_to_running(version, running)
    if order == VERSION_NEWER:
        return f"Update available → v{version} (install)"
    if order == VERSION_OLDER:
        return f"Roll back to v{version} (older build, install)"
    return f"Switch to v{version} (install)"


def offer_toast(version: Any, running: Optional[str] = None) -> str:
    """The tray balloon raised once when a new offer appears (app.py's
    on_available). Same three cases as offer_label."""
    order = compare_to_running(version, running)
    current = config_mod.VERSION if running is None else running
    if order == VERSION_NEWER:
        return f"Update available → v{version}. Use the tray menu to install"
    if order == VERSION_OLDER:
        return (f"Roll back to v{version} offered. That is OLDER than the v{current} "
                f"you are running. Only install it if your admin asked you to.")
    return f"Switch to v{version}. Use the tray menu to install"


def offer_dialog_text(version: Any, running: Optional[str] = None) -> tuple[str, str, str]:
    """(title, body, ok-button label) for the confirmation dialog, so the
    LAST thing shown before the swap agrees with the menu item that opened
    it."""
    order = compare_to_running(version, running)
    current = config_mod.VERSION if running is None else running
    if order == VERSION_OLDER:
        return (
            "CCSYNC.EXE: roll back",
            f"Roll back to v{version}? That is OLDER than the v{current} on this "
            f"machine. You would LOSE whatever v{current} fixed. The companion "
            f"will restart itself.",
            "ROLL BACK",
        )
    if order == VERSION_NEWER:
        return (
            "CCSYNC.EXE: update",
            f"Update to v{version}? The companion will restart itself.",
            "UPDATE",
        )
    return (
        "CCSYNC.EXE: switch build",
        f"Switch to v{version}? You are running v{current}. The companion will "
        f"restart itself.",
        "SWITCH",
    )


class UpgradeManager:
    """Holds the "is an update available" state and performs the swap.

    Thread model: note_report_response() is called from the reporter thread,
    available/apply() from tray-spawned threads -- everything touching
    _available goes through _lock. apply() itself is serialized by the
    _applying flag (a second click while one is in flight is a no-op)."""

    def __init__(
        self,
        cfg: dict[str, Any],
        http_open: Optional[HttpOpenFn] = None,
        replace_fn: ReplaceFn = os.replace,
        spawn_fn: Optional[SpawnFn] = None,
        request_shutdown: Optional[Callable[[], None]] = None,
        on_available: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self.cfg = cfg
        self._http_open = http_open or default_http_open
        self._replace = replace_fn
        self._spawn = spawn_fn or self._default_spawn
        self._request_shutdown = request_shutdown
        self._on_available = on_available
        self._lock = threading.Lock()
        self._available: Optional[dict[str, Any]] = None
        self._applying = False

    @property
    def available(self) -> Optional[dict[str, Any]]:
        with self._lock:
            return dict(self._available) if self._available else None

    def note_report_response(self, resp: Any) -> None:
        """Feed a parsed report/verify response. Sets the available state on
        a valid `upgrade` key, CLEARS it when a well-formed response has none
        (the admin rolled current back to our version, or unpublished it).
        Never raises."""
        try:
            info = parse_upgrade(resp)
        except Exception:
            info = None
        newly: Optional[dict[str, Any]] = None
        with self._lock:
            if info is not None:
                if self._available is None or self._available["version"] != info["version"]:
                    newly = info
                self._available = info
            elif isinstance(resp, dict):
                self._available = None
        if newly is not None and self._on_available is not None:
            try:
                self._on_available(newly)
            except Exception:
                log.exception("on_available callback failed")

    # -- download ------------------------------------------------------
    def download_and_verify(self, info: dict[str, Any], dest_dir: Path) -> Optional[Path]:
        """Stream the advertised build to dest_dir/<new_download_name()> and
        verify its sha256. Returns the path, or None on any failure (temp file
        removed). Never raises."""
        url = str(info.get("url") or "")
        base = str(self.cfg.get("dashboard_url", "")).strip().rstrip("/")
        # ORIGIN PINNING (CORE-M10): an absolute URL is only followed when it
        # points at the same dashboard we already trust for config/tokens.
        if not same_origin(url, base):
            log.error(
                "upgrade: REFUSING an update URL that isn't on the dashboard's own host "
                "(%r vs dashboard_url %r)", url, base,
            )
            return None
        if url.startswith("/"):
            if not base:
                log.warning("upgrade: dashboard_url is not configured -- cannot download")
                return None
            url = base + url
        headers = {}
        token = str(self.cfg.get("dashboard_token", "")).strip()
        if token:
            headers["X-CCSync-Token"] = token

        # The dashboard publishes size_bytes as the byte count it actually
        # wrote (api.py's publish handler), and it was parsed by parse_upgrade
        # and then read by nothing: neither the flat 200 MB free-space margin
        # nor the download ceiling consulted it. A 250 MB build downloaded
        # onto 210 MB of free space still passed the check and only failed at
        # the last write.
        advertised = advertised_size(info)

        try:
            free = shutil.disk_usage(str(dest_dir)).free
            needed = MIN_FREE_BYTES_MARGIN + (advertised or 0)
            if free < needed:
                log.warning(
                    "upgrade: %.0f MB free at %s but the update needs %.0f MB "
                    "(+ margin) -- refusing to download it",
                    free / 1_000_000, dest_dir, needed / 1_000_000,
                )
                return None
        except Exception:
            log.debug("upgrade: free-space check failed; continuing", exc_info=True)

        # The advertised size is the tighter of the two ceilings whenever the
        # server gave us one: a body that outgrows it is not the build we were
        # offered, and there is no reason to write the rest of it to disk.
        ceiling = min(MAX_DOWNLOAD_BYTES, advertised) if advertised else MAX_DOWNLOAD_BYTES

        tmp = dest_dir / new_download_name()
        digest = hashlib.sha256()
        written = 0
        try:
            with self._http_open(url, headers, DOWNLOAD_TIMEOUT) as resp:
                status = redirect_status(resp)
                if status is not None:
                    raise _RedirectRefused(status)
                with tmp.open("wb") as fh:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > ceiling:
                            raise ValueError(
                                f"update exceeded the "
                                f"{ceiling // (1024 * 1024)} MB ceiling"
                            )
                        fh.write(chunk)
                        digest.update(chunk)
        except Exception as exc:
            code = getattr(exc, "code", None)
            try:
                is_redirect = isinstance(exc, _RedirectRefused) or (
                    isinstance(exc, urllib.error.HTTPError) and 300 <= int(code) < 400
                )
            except (TypeError, ValueError):
                # Nothing in this handler may raise: it runs on the path where
                # the running exe is about to be renamed.
                is_redirect = False
            if is_redirect:
                # NOT followed, deliberately -- see build_no_redirect_opener.
                # The origin check above is worthless if a redirect can move
                # the download (and the X-CCSync-Token header) elsewhere
                # afterwards (AUDIT_3 H-1).
                log.error(
                    "upgrade: REFUSING the update download -- %s answered with a "
                    "redirect (HTTP %s). The update must be served by the dashboard "
                    "itself; nothing was downloaded and no token was re-sent.",
                    url, code or "3xx",
                )
            else:
                log.warning("upgrade: download failed: %s", exc)
            self._unlink_quietly(tmp)
            return None
        if digest.hexdigest() != info.get("sha256"):
            log.warning("upgrade: sha256 mismatch on downloaded build -- discarding it")
            self._unlink_quietly(tmp)
            return None
        self._make_executable(tmp)
        return tmp

    @staticmethod
    def _make_executable(path: Path) -> None:
        """Give the verified download the execute bit on POSIX.

        A file created by open("wb") is 0644 under the usual umask, and macOS
        will not exec it -- so the swap would rename a non-executable file
        over the companion and the respawn would fail with EACCES. Windows has
        no execute bit and os.chmod there only toggles read-only, so it is
        never called on win32.

        AFTER the sha256 check, deliberately: an unverified download must
        never be made runnable, however briefly. os.replace preserves the
        mode, so setting it here carries through both renames to the installed
        path -- no chmod is needed once the binary is in place.

        Never raises, and a failure does NOT abort the upgrade: chmod can be a
        no-op-with-EPERM on exotic mounts where the file is already executable,
        and refusing a working update over that would be worse than the
        alternative -- if the file really cannot be executed, _apply_inner's
        spawn fails and rolls the whole swap back."""
        if sys.platform == "win32":
            return
        try:
            os.chmod(path, 0o755)
        except OSError as exc:
            log.warning(
                "upgrade: could not set the execute bit on %s (%s) -- continuing; "
                "if the new build cannot start, the swap rolls back", path, exc,
            )

    # -- the swap ------------------------------------------------------
    def apply(self) -> bool:
        """Download + swap + restart. Never raises; False means "nothing
        happened / rolled back, the current build keeps running"."""
        info = self.available
        if info is None:
            return False
        if not is_frozen():
            log.info("upgrade: not a frozen exe (source run) -- self-upgrade skipped")
            return False
        with self._lock:
            if self._applying:
                return False
            self._applying = True
        try:
            return self._apply_inner(info)
        finally:
            with self._lock:
                self._applying = False

    def _apply_inner(self, info: dict[str, Any]) -> bool:
        exe = Path(sys.executable)
        new = self.download_and_verify(info, exe.parent)
        if new is None:
            return False

        old = exe.with_name(exe.name + _OLD_SUFFIX)
        # `except Exception` throughout: _replace is injectable and os.replace
        # is not limited to OSError (CORE-H7). Anything escaping here kills
        # the tray daemon thread while the exe may not exist.
        try:
            self._replace(exe, old)
        except Exception as exc:
            log.warning("upgrade: could not move the running exe aside: %s", exc)
            self._unlink_quietly(new)
            return False
        try:
            self._replace(new, exe)
        except Exception as exc:
            log.warning("upgrade: could not move the new exe into place: %s -- rolling back", exc)
            self._rollback(old, exe, aside=None)
            # The new build is still parked at the .new download and we are not going
            # to run it -- don't leave 20 MB behind.
            self._unlink_quietly(new)
            return False
        try:
            self._spawn(exe)
        except Exception as exc:
            log.warning("upgrade: could not launch the new build: %s -- rolling back", exc)
            self._rollback(old, exe, aside=new)
            return False

        log.info("upgrade: v%s launched; shutting down v%s", info["version"], config_mod.VERSION)
        if self._request_shutdown is not None:
            try:
                self._request_shutdown()
            except Exception:
                log.exception("upgrade: request_shutdown failed (exit manually)")
        return True

    def _rollback(self, old: Path, exe: Path, aside: Optional[Path]) -> None:
        """Restore `old` to `exe`; if the failed new build currently sits at
        `exe`, park it back at `aside` first so the restore can land.

        `except Exception`, not `except OSError`: `_replace` is an injectable
        callable and os.replace can raise TypeError/ValueError (surrogate
        path) or anything a wrapper raises. A raise here escaped
        _apply_inner -> apply() -> app.apply_upgrade() -> the tray's dialog
        handler, killing the tray daemon thread to invisible stderr WHILE
        `exe` did not exist -- renamed to `.old`, with the new build parked
        at the `.new` download (AUDIT_2 CORE-H7). Rollback is the last line of
        defence; it may not have a failure mode of its own."""
        restored = False
        try:
            if aside is not None:
                self._replace(exe, aside)
            self._replace(old, exe)
            restored = True
        except Exception:
            log.exception(
                "upgrade: ROLLBACK FAILED -- the previous build is at %s; "
                "rename it back to %s by hand", old, exe.name,
            )
        if not restored:
            return
        log.info("upgrade: rolled back to the previous build at %s", exe)
        # The rollback SUCCEEDED, so `aside` now holds ~20 MB of a build we
        # just refused to run. It was never unlinked (AUDIT_2 CORE-H7) and
        # would be silently truncated by the next apply()'s "wb" open.
        if aside is not None:
            self._unlink_quietly(aside)

    @staticmethod
    def _unlink_quietly(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _default_spawn(exe: Path) -> None:
        # DETACHED_PROCESS decouples from this soon-dead process;
        # CREATE_NO_WINDOW stops Windows allocating a fresh (empty, killable)
        # console if the exe is ever a console build again -- closing that
        # mystery window kills the companion (seen live 2026-07-25). All std
        # handles to DEVNULL; build.spec is console=False since 0.3.2.
        detach: dict[str, Any] = {}
        if sys.platform == "win32":
            detach["creationflags"] = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            # POSIX has no creationflags at all (passing one raises), so the
            # detach is start_new_session=True: setsid() gives the child its
            # own session and process group, so it outlives this process and
            # never takes a signal aimed at the dying parent's group. This
            # matters more on macOS than on Windows -- the LaunchAgent is
            # RunAtLoad-only with no KeepAlive, so nothing else will ever
            # bring the new build up if this spawn dies with us.
            detach["start_new_session"] = True
        # CRITICAL for onefile self-restart on EVERY platform: without this,
        # PyInstaller >=6 has the spawned copy REUSE this process's _MEI dir --
        # which our bootloader deletes on exit moments later, leaving the
        # new instance running from a vanished directory (broken tkinter,
        # broken lazy imports, or an outright Tcl crash at startup -- all
        # three seen live 2026-07-25). PYINSTALLER_RESET_ENVIRONMENT makes
        # the child a fully independent instance with its own extraction.
        env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("_PYI") and not k.startswith("_MEI")
        }
        # Same reasoning one level up: resolve_bridge pins PYTHONHOME/
        # PYTHON3HOME at THIS process's _MEI... dir so fusionscript.dll loads
        # our python3.dll. The bootloader deletes that dir seconds from now,
        # so inheriting them points the new instance's Python at a vanished
        # directory (AUDIT_2 CORE-M6).
        from . import resolve_bridge

        env = resolve_bridge.sanitized_child_env(env)
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        subprocess.Popen(
            [str(exe)],
            cwd=str(exe.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=env,
            **detach,
        )
