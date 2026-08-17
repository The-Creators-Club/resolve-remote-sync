"""Owner-only permissions for the files under ~/.ccsync that hold credentials.

`identity.json` carries a signed machine-identity token and a fleet report
token; `config.toml` carries the report token as installed. Both were written
at the process default umask -- 0644 on POSIX, and on Windows whatever the
profile directory's inherited ACL says, which on a domain-joined or
multi-account machine is routinely readable by other local users and by
anything running as them (COMMERCIAL_READINESS.md item 15, 2026-08-17).

POSIX is one chmod. Windows has no mode bits at all, so `os.chmod` there only
toggles the read-only attribute and does nothing whatsoever about who may read
the file -- the companion's ytdl cookie install says as much in a comment and
leaves it there. The fix on Windows is an ACL: strip inheritance and grant the
file's owner alone. `icacls` is the tool every Windows admin already knows, it
ships in the base OS, needs no pywin32 (which the frozen build does not
bundle), and its arguments are all list-argv here -- no shell, no format
string reaching a command line.

NEVER RAISES. A companion that cannot tighten a permission must still run: the
alternative is an editor whose tray will not start because their profile lives
on a filesystem with no ACL support. Every failure is one WARNING naming the
file, which is the thing an operator can act on.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("ccsync.secretfile")

# Same flag every other subprocess in this package passes on Windows: without
# it a frozen (windowed) build flashes a console for each call.
_CREATE_NO_WINDOW = 0x08000000

# icacls is slow-ish (~30 ms) and these files are rewritten on every sign-in,
# but never in a loop -- no caching, deliberately: a cache that says "already
# hardened" is wrong the moment a file is replaced by a restore or an
# installer, which is exactly when the permission matters.
_ICACLS_TIMEOUT = 15.0


def _windows_owner() -> str:
    """The account to grant. USERNAME is what icacls expects and what the
    file's own owner will be -- this process created it."""
    domain = os.environ.get("USERDOMAIN", "").strip()
    user = os.environ.get("USERNAME", "").strip()
    if not user:
        return ""
    return f"{domain}\\{user}" if domain else user


def _harden_windows(path: Path) -> bool:
    owner = _windows_owner()
    if not owner:
        log.warning("could not restrict %s: neither USERNAME nor USERDOMAIN is set, "
                    "so there is no account to grant it to", path)
        return False
    # /inheritance:r FIRST, in the same call: removing inherited entries and
    # granting the owner as two calls leaves a window where the file has no
    # ACEs at all, and a crash in between leaves it unreadable by its own
    # owner -- which for identity.json means a companion that cannot sign in
    # and cannot be fixed from the tray.
    cmd = ["icacls", str(path), "/inheritance:r", "/grant:r", f"{owner}:(R,W)"]
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=_ICACLS_TIMEOUT, creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("could not restrict %s to %s (%s); it keeps the permissions it "
                    "inherited from your profile directory", path, owner, exc)
        return False
    if proc.returncode != 0:
        detail = (proc.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        log.warning("icacls refused to restrict %s to %s (exit %s): %s",
                    path, owner, proc.returncode, detail[-1] if detail else "")
        return False
    return True


def harden(path: Path | str) -> bool:
    """Make `path` readable by its owner only. True if it took.

    Call it on the TEMP file of a write-then-replace, before the rename, so the
    secret is never on disk under wider permissions even briefly.
    """
    path = Path(path)
    try:
        if sys.platform == "win32":
            return _harden_windows(path)
        os.chmod(path, 0o600)
        return True
    except OSError as exc:
        log.warning("could not restrict %s to owner-only (%s); it keeps the default "
                    "permissions", path, exc)
        return False
    except Exception:  # noqa: BLE001 - never-raise: see the module docstring
        log.debug("hardening %s failed unexpectedly", path, exc_info=True)
        return False
