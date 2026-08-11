"""Momentary P: remap -- local copy <-> the server's own tree.

Colour-grading remotely wants full-res frames, but editors hold proxies
only. Because every Resolve-stored path is canonical (P:\\...), remapping
the P: DRIVE is enough: point it at the server's SMB tree and every clip
resolves against the camera originals (frames stream over the network);
point it back at the local copy and proxy life resumes. No relinking, no
Resolve project changes -- the path canon does all the work.

Mechanics mirror windows_bootstrap.ps1's own mapping:
  local  = net use P: \\\\localhost\\CCSync_P   (loopback share of local_root)
           or the legacy `subst P: <local_root>` fallback
  server = net use P: <server unc>              (derive_server_unc() below,
           or the server_p_unc config override; e.g.
           \\\\100.65.15.123\\TheCreatorsPool\\Creators_Club over the tailnet)

Sync is UNAFFECTED by the swap: every lane works on the physical
local_root, never through P:. Only Resolve's view changes. The companion
suppresses its mapping-health warnings while the server map is active --
the watcher would otherwise cry BAD_PREFIX about a state the user chose
(see app._handle_mapping_warning).

All functions take an injectable run_fn and never raise.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Callable, Optional

log = logging.getLogger("ccsync.drive_swap")

P_DRIVE = "P:"
LOOPBACK_SHARE = "CCSync_P"

# Windows error text fragments that mean "the server wants credentials".
# 1223/"canceled by the user"/"Enter the username" is net use trying to
# PROMPT on a console this windowed exe doesn't have (seen live 2026-07-26):
# same root cause, no credentials stored for the host.
_AUTH_HINTS = ("denied", "logon", "credential", "password", "1326", "user name",
               "1223", "canceled", "cancelled", "username")

RunFn = Callable[..., "subprocess.CompletedProcess"]


def _default_run(args: list[str]) -> "subprocess.CompletedProcess":
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    # stdin=DEVNULL: net use PROMPTS for a username when the host wants
    # credentials it doesn't have. There is no console to answer on, so
    # without this the prompt half-hangs then dies as 1223 "canceled by the
    # user". With it, the failure is immediate and classified as auth.
    return subprocess.run(
        args, capture_output=True, encoding="utf-8", errors="replace",
        timeout=30, creationflags=creationflags, stdin=subprocess.DEVNULL,
    )


def current_p_target(run_fn: RunFn = _default_run) -> str:
    """Where P: points right now: a UNC path, a subst directory, or ""."""
    try:
        proc = run_fn(["net", "use", P_DRIVE])
        if proc.returncode == 0:
            # Locale-proof: take the first UNC-shaped token in the output.
            m = re.search(r"(\\\\\S+)", proc.stdout or "")
            if m:
                return m.group(1).rstrip()
    except Exception:
        log.debug("net use query failed", exc_info=True)
    try:
        proc = run_fn(["subst"])
        if proc.returncode == 0:
            for line in (proc.stdout or "").splitlines():
                if line.upper().startswith(P_DRIVE.upper()):
                    m = re.search(r"=>\s*(.+)$", line)
                    if m:
                        return m.group(1).strip()
    except Exception:
        log.debug("subst query failed", exc_info=True)
    return ""


def classify_p_target(target: str, local_root: str, server_unc: str) -> str:
    """"local" | "server" | "other" | "none" for a current_p_target() value."""
    t = str(target or "").strip()
    if not t:
        return "none"
    norm = os.path.normcase(t.rstrip("\\/"))
    if norm.endswith(os.path.normcase("\\" + LOOPBACK_SHARE)):
        return "local"
    if local_root and norm == os.path.normcase(str(local_root).rstrip("\\/")):
        return "local"  # legacy subst mapping
    if server_unc and norm == os.path.normcase(str(server_unc).rstrip("\\/")):
        return "server"
    return "other"


def _unmap(run_fn: RunFn) -> None:
    """Remove whatever P: currently is. /y answers the open-files prompt --
    Resolve holds handles on P: paths, and the whole point of the swap is
    doing it under a running Resolve."""
    for args in (["net", "use", P_DRIVE, "/delete", "/y"], ["subst", P_DRIVE, "/D"]):
        try:
            run_fn(args)
        except Exception:
            log.debug("unmap step %s failed", args, exc_info=True)


def _error_tail(proc: "subprocess.CompletedProcess") -> str:
    text = ((proc.stderr or "") + " " + (proc.stdout or "")).strip()
    return " ".join(text.split())[-200:]


def _redacted(args: list[str], password: str = "") -> str:
    """An argv safe to log. SYNC-4 (2026-08-11): the grade-swap hands the
    editor's TrueNAS password to `net use` POSITIONALLY and to cmdkey as
    `/pass:`, and both `TimeoutExpired.__str__` and a CalledProcessError
    traceback embed the whole argv -- which app.swap_p_to_server logs at INFO,
    shows as a tray balloon, and copy_diagnostics() sweeps to the clipboard.
    An SMB connect to a sleeping tailnet host reaches the 30 s timeout
    routinely, so this is the common path, not the exotic one."""
    out = []
    for arg in args:
        text = str(arg)
        if text.lower().startswith("/pass:"):
            text = "/pass:***"
        elif password and text == str(password):
            text = "***"
        out.append(text)
    return " ".join(out)


def is_auth_failure(message: str) -> bool:
    """True when a swap_to_server failure message means "the server wants
    credentials" -- the tray reacts by asking for the editor's server login
    and retrying (tray._confirm_grade_swap)."""
    return any(h in str(message or "").lower() for h in _AUTH_HINTS)


def swap_to_server(
    server_unc: str,
    run_fn: RunFn = _default_run,
    username: str = "",
    password: str = "",
) -> tuple[bool, str]:
    """Map P: to the server tree. On failure the caller MUST restore the
    local map (see app.swap_p_to_server) -- this function reports, it does
    not roll back. username/password (the editor's TrueNAS login) are passed
    to net use when given -- the retry path after is_auth_failure()."""
    if not str(server_unc or "").strip():
        return False, "server_p_unc is not configured"
    _unmap(run_fn)
    args = ["net", "use", P_DRIVE, str(server_unc), "/persistent:no"]
    if username:
        args += [f"/user:{username}", password or ""]
    try:
        proc = run_fn(args)
    except Exception as exc:
        # SYNC-4 (2026-08-11): the exception must NEVER be interpolated here --
        # see _redacted(). The type alone is what the editor sees; the redacted
        # argv goes to the log for diagnosis.
        log.debug("net use raised %s: %s", type(exc).__name__, _redacted(args, password))
        return False, f"net use failed: {type(exc).__name__}"
    if proc.returncode != 0:
        message = _error_tail(proc) or f"net use exited {proc.returncode}"
        return False, message
    return True, "P: now shows the SERVER originals"


def persist_credentials(
    server_unc: str, username: str, password: str, run_fn: RunFn = _default_run,
) -> None:
    """Best-effort: store the server login in Windows Credential Manager so
    every future swap (and Explorer itself) authenticates silently."""
    host = _unc_host(server_unc)
    if not (host and username):
        return
    args = ["cmdkey", f"/add:{host}", f"/user:{username}", f"/pass:{password or ''}"]
    try:
        proc = run_fn(args)
        if proc.returncode != 0:
            log.debug("cmdkey /add failed: %s", _error_tail(proc))
    except Exception as exc:
        # SYNC-4 (2026-08-11): exc_info=True printed a traceback whose
        # exception line carries this argv -- /pass:<the editor's password>.
        log.debug("cmdkey /add raised %s: %s", type(exc).__name__, _redacted(args))


def swap_to_local(local_root: str, run_fn: RunFn = _default_run) -> tuple[bool, str]:
    """Map P: back to this machine's copy: loopback share first (the
    bootstrap's primary), subst fallback (its legacy)."""
    _unmap(run_fn)
    try:
        proc = run_fn(["net", "use", P_DRIVE, f"\\\\localhost\\{LOOPBACK_SHARE}",
                       "/persistent:yes"])
        if proc.returncode == 0:
            return True, "P: is back to your local copy (proxies)"
    except Exception:
        log.debug("loopback remap failed", exc_info=True)
    if not str(local_root or "").strip():
        return False, "local_root is not configured -- P: is currently UNMAPPED"
    try:
        proc = run_fn(["subst", P_DRIVE, str(local_root)])
    except Exception as exc:
        return False, f"P: could not be restored ({exc}) -- remap it by hand or re-run the installer"
    if proc.returncode != 0:
        return False, (
            f"P: could not be restored ({_error_tail(proc)}) -- remap it by hand "
            "or re-run the installer"
        )
    return True, "P: is back to your local copy (proxies, via subst)"


def derive_server_unc(dashboard_url: str, remote_root: str) -> str:
    """The server tree's SMB path, derived from config every machine
    already has -- so the grade-swap needs NO per-machine setup:

      host  = dashboard_url's host (whichever address THIS machine uses to
              reach the server: LAN for local editors, tailnet for remote)
      share = remote_root beyond /mnt/<pool>/ (TrueNAS shares a dataset
              under its own name: /mnt/tank/TheCreatorsPool/Creators_Club
              serves as \\\\host\\TheCreatorsPool\\Creators_Club)

    Returns "" when either part can't be derived."""
    try:
        from urllib.parse import urlparse

        host = (urlparse(str(dashboard_url or "")).hostname or "").strip()
        m = re.match(r"^/mnt/[^/]+/(.+)$", str(remote_root or "").strip().rstrip("/"))
        if not host or not m:
            return ""
        share_path = m.group(1).replace("/", "\\")
        return "\\\\" + host + "\\" + share_path
    except Exception:
        return ""


def _unc_host(unc: str) -> str:
    m = re.match(r"^\\\\([^\\]+)", str(unc or ""))
    return m.group(1) if m else ""
