"""Repair an unreadable ~/.ccsync on Windows (GL-27 / CR-372, 2026-10-07).

Every Windows wizard install before this date ran
``icacls ~/.ccsync /inheritance:r /grant:r me:(F) ...`` with no ``(OI)(CI)``.
A file or folder that already existed inside (``eula_accepted.json``,
``logs\\``, ``state\\``) had only ACEs it had INHERITED from that folder, so it
was left with an empty permission list: the EULA re-asked, the install log
stopped, and the safety latches under ``state\\`` (lane B breaker, fleet halt,
drive reminder) could no longer be saved - which `lane_guard` answers by
falling back to in-memory, i.e. a latch that a restart forgets.

The installers repair it (``windows_bootstrap.ps1``, ``windows_upgrade.ps1``)
but a machine that upgrades from the tray never runs either, so the companion
looks at its own folder at start and repairs what it finds. The probe is cheap
(a bounded walk that tries to OPEN things) and the repair only runs when the
probe finds a denial, so a healthy machine pays nothing and a machine this bug
never touched is never changed.

Never raises: a permissions repair must not stop a sync tool from starting.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("ccsync.state_acl")

_CREATE_NO_WINDOW = 0x08000000
_ICACLS_TIMEOUT = 60.0
# The probe is bounded so a state dir that grew large costs a few ms, not a
# scan. The directories that matter (state\, the top level) are tiny; a
# crashes\ or logs\ tree is sampled, not walked to the end.
_PROBE_LIMIT = 400


def _owner() -> str:
    user = os.environ.get("USERNAME", "").strip()
    if not user:
        return ""
    domain = os.environ.get("USERDOMAIN", "").strip()
    return f"{domain}\\{user}" if domain else user


def find_denied(root: Path, limit: int = _PROBE_LIMIT) -> list[Path]:
    """Entries under ``root`` this process cannot open (read), up to ``limit``
    looked at. A directory is probed by listing it, a file by opening it."""
    denied: list[Path] = []
    seen = 0
    stack = [root]
    while stack and seen < limit:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except PermissionError:
            denied.append(d)
            continue
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if seen > limit:
                break
            path = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(path)
                else:
                    with open(path, "rb"):
                        pass
            except PermissionError:
                denied.append(path)
            except OSError:
                continue
    return denied


def _icacls(args: list[str]) -> int:
    try:
        proc = subprocess.run(
            ["icacls", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=_ICACLS_TIMEOUT, creationflags=_CREATE_NO_WINDOW,
        )
        return proc.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("icacls could not run (%s)", exc)
        return -1


def repair(root: Path | str) -> bool:
    """Re-grant ``root`` with (OI)(CI) and reset everything inside it to
    inherit. True when both icacls calls took. The folder itself is never
    reset: that would hand the fleet token in config.toml back to the
    profile's default ACL."""
    root = Path(root)
    owner = _owner()
    if not owner:
        log.warning("could not repair %s: no USERNAME to grant it to", root)
        return False
    grant = [str(root), "/inheritance:r", "/grant:r", f"{owner}:(OI)(CI)(F)",
             "*S-1-5-18:(OI)(CI)(F)", "*S-1-5-32-544:(OI)(CI)(F)"]
    if _icacls(grant) != 0:
        log.warning("could not re-grant %s", root)
        return False
    if _icacls([str(root / "*"), "/reset", "/T", "/C", "/Q"]) != 0:
        log.warning("could not reset every file inside %s", root)
        return False
    return True


def repair_if_needed(root: Path | str) -> str:
    """The companion's start-up call. Returns ``"skipped"`` (not Windows, or
    no such folder), ``"ok"`` (nothing denied), ``"repaired"`` or ``"failed"``."""
    try:
        if sys.platform != "win32":
            return "skipped"
        root = Path(root)
        if not root.is_dir():
            return "skipped"
        denied = find_denied(root)
        if not denied:
            return "ok"
        log.warning(
            "%d item(s) under %s cannot be opened (first: %s) - the signature of the "
            "pre-2026-10-07 installer's ACL bug (GL-27). Repairing the folder's permissions.",
            len(denied), root, denied[0],
        )
        if repair(root):
            left = find_denied(root)
            if left:
                log.warning("%d item(s) under %s are still unreadable after the repair (first: %s)",
                            len(left), root, left[0])
                return "failed"
            log.info("repaired the permissions inside %s", root)
            return "repaired"
        return "failed"
    except Exception:  # noqa: BLE001 - never-raise: see the module docstring
        log.debug("state ACL check failed unexpectedly", exc_info=True)
        return "failed"
