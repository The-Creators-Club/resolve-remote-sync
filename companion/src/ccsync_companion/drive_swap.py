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
  server = WNetAddConnection2W(P:, <server unc>) -- the API `net use` itself
           calls, because this one carries the editor's password (R1 below);
           the UNC comes from derive_server_unc() or the server_p_unc config
           override, e.g. \\\\100.65.15.123\\TheCreatorsPool\\Creators_Club
           over the tailnet

Sync is UNAFFECTED by the swap: every lane works on the physical
local_root, never through P:. Only Resolve's view changes. The companion
suppresses its mapping-health warnings while the server map is active --
the watcher would otherwise cry BAD_PREFIX about a state the user chose
(see app._handle_mapping_warning).

All functions take an injectable run_fn and never raise. Since R1 the run_fn
no longer sees the credentialed connect (it is a Win32 call, mocked in tests
by swapping the function pointer) -- it still drives every unmap, query and
loopback remap, so the seam and the signatures are unchanged.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import subprocess
import threading
from typing import Callable, Optional

log = logging.getLogger("ccsync.drive_swap")

P_DRIVE = "P:"
LOOPBACK_SHARE = "CCSync_P"

# Every subprocess AND the Win32 connect share one ceiling: an SMB connect to
# a sleeping tailnet host routinely runs long, and the editor is watching a
# tray menu the whole time.
_TIMEOUT_S = 30

# Text fragments that mean "the server wants credentials". These used to have
# to survive net use's LOCALISED output, which is why they are fuzzy; since R1
# the connect failures are our own English strings (_CONNECT_ERRORS below), but
# the fuzziness stays -- swap_to_local and the unmap steps still shell out.
# 1223/"canceled by the user"/"Enter the username" was net use trying to PROMPT
# on a console this windowed exe doesn't have (seen live 2026-07-26): same root
# cause, no credentials stored for the host.
_AUTH_HINTS = ("denied", "logon", "credential", "password", "1326", "user name",
               "1223", "canceled", "cancelled", "username")

RunFn = Callable[..., "subprocess.CompletedProcess"]


def _default_run(args: list[str]) -> "subprocess.CompletedProcess":
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    # stdin=DEVNULL: net use PROMPTS for a username when the host wants
    # credentials it doesn't have. There is no console to answer on, so
    # without this the prompt half-hangs then dies as 1223 "canceled by the
    # user". With it, the failure is immediate and classified as auth.
    # (R1 moved the credentialed connect off net use entirely -- but the
    # uncredentialed unmap/query/loopback calls still run through here, and a
    # `net use P: \\localhost\CCSync_P` against a broken loopback can prompt
    # just the same. The flag stays.)
    return subprocess.run(
        args, capture_output=True, encoding="utf-8", errors="replace",
        timeout=_TIMEOUT_S, creationflags=creationflags, stdin=subprocess.DEVNULL,
    )


# -- R1 (2026-08-11): the password paths are in-process Win32, not argv ------
#
# `net use <unc> /user:<u> <password>` and `cmdkey /add /pass:<password>` put
# the editor's TrueNAS login on a command line that ANY process on the box can
# enumerate (KNOWN_BUGS R1). SYNC-4 (2026-08-11) closed the other half of that
# exposure -- logs, tray balloons, copy_diagnostics() -- via _redacted(); this
# closes the argv half by calling the APIs those two tools call themselves:
#
#   connect P: -> mpr.dll!WNetAddConnection2W  (user/password are ARGUMENTS)
#   persist    -> advapi32.dll!CredWriteW      (password is a struct field)
#
# Feeding the password to net use on STDIN was the obvious cheaper fix and is
# barred: net use only reads stdin when it is prompting, and prompting is the
# 2026-07-26 error-1223 half-hang that stdin=DEVNULL exists to prevent.
# WNetAddConnection2W is passed no CONNECT_INTERACTIVE, so it never prompts at
# all -- the whole failure mode stops existing on this path.
#
# ctypes types are spelled out (c_uint32/c_wchar_p) rather than imported from
# ctypes.wintypes: importing wintypes raises on non-Windows, and this module
# is imported by app.py on macOS too (where p_swap_available() is False and
# none of this ever runs).

RESOURCETYPE_DISK = 0x00000001
CONNECT_TEMPORARY = 0x00000004          # == net use /persistent:no
CRED_TYPE_DOMAIN_PASSWORD = 2           # what cmdkey /add:<host> writes
CRED_PERSIST_LOCAL_MACHINE = 2


class NETRESOURCEW(ctypes.Structure):
    _fields_ = [
        ("dwScope", ctypes.c_uint32),
        ("dwType", ctypes.c_uint32),
        ("dwDisplayType", ctypes.c_uint32),
        ("dwUsage", ctypes.c_uint32),
        ("lpLocalName", ctypes.c_wchar_p),
        ("lpRemoteName", ctypes.c_wchar_p),
        ("lpComment", ctypes.c_wchar_p),
        ("lpProvider", ctypes.c_wchar_p),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32),
                ("dwHighDateTime", ctypes.c_uint32)]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.c_uint32),
        ("Type", ctypes.c_uint32),
        ("TargetName", ctypes.c_wchar_p),
        ("Comment", ctypes.c_wchar_p),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", ctypes.c_uint32),
        ("CredentialBlob", ctypes.c_void_p),
        ("Persist", ctypes.c_uint32),
        ("AttributeCount", ctypes.c_uint32),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


# The two entry points, resolved once and cached. Tests replace THESE (the
# function pointers) -- never ctypes itself, and never by letting a real call
# through: a live WNetAddConnection2W would remap the developer's own P:.
_WNET_ADD: Optional[Callable[..., int]] = None
_CRED_WRITE: Optional[Callable[..., int]] = None


def _wnet_add_fn() -> Callable[..., int]:
    global _WNET_ADD
    if _WNET_ADD is None:
        fn = ctypes.WinDLL("mpr.dll").WNetAddConnection2W
        fn.argtypes = [ctypes.POINTER(NETRESOURCEW), ctypes.c_wchar_p,
                       ctypes.c_wchar_p, ctypes.c_uint32]
        fn.restype = ctypes.c_uint32     # returns the error code, not a BOOL
        _WNET_ADD = fn
    return _WNET_ADD


def _cred_write_fn() -> Callable[..., int]:
    global _CRED_WRITE
    if _CRED_WRITE is None:
        fn = ctypes.WinDLL("advapi32.dll").CredWriteW
        fn.argtypes = [ctypes.POINTER(CREDENTIALW), ctypes.c_uint32]
        fn.restype = ctypes.c_int32      # BOOL; 0 == failed, see GetLastError
        _CRED_WRITE = fn
    return _CRED_WRITE


# Win32 connect failures, in the words the editor should read. Deliberately
# our own English rather than FormatMessageW's: net use's localised output was
# why is_auth_failure() had to keyword-match at all, and these strings are
# themselves what is_auth_failure() now classifies -- so which ones carry an
# _AUTH_HINTS word decides whether the tray offers "enter your server login
# and retry". Codes 86/1326/1223/5 must; 53/67/1219 must NOT.
_CONNECT_ERRORS = {
    5: "System error 5: access is denied -- the server refused this logon",
    53: "System error 53: the network path was not found -- is the server up "
        "and reachable from here?",
    55: "System error 55: the share is no longer available on the server",
    66: "System error 66: the server offered the wrong resource type for a drive",
    67: "System error 67: the network name was not found -- check the share path",
    85: f"System error 85: {P_DRIVE} is already in use by another mapping",
    86: "System error 86: that password is not correct for this server",
    # 1219: a credential prompt cannot fix this one -- Windows already holds a
    # session to the host as somebody else and refuses a second identity. Its
    # message must therefore avoid every _AUTH_HINTS word, or the tray would
    # ask for a login and retry into the identical error.
    1219: "System error 1219: Windows already holds a connection to this "
          "server as a different account -- disconnect it (or sign out) and "
          "try again",
    # 1223 was net use's console-prompt half-hang (2026-07-26). WNet cannot
    # prompt, so seeing it now means the connect was refused outright -- still
    # "the server wants credentials", still the retry path.
    1223: "System error 1223: the connection was cancelled -- the server "
          "wants credentials for this share",
    1200: f"System error 1200: {P_DRIVE} is not a valid device name",
    1203: "System error 1203: no network provider accepted the path",
    1326: "System error 1326: the user name or password is incorrect",
    1327: "System error 1327: this account cannot log on with a blank password",
}

_CONNECT_TIMEOUT_MSG = (
    f"the server did not answer within {_TIMEOUT_S}s -- P: was not remapped"
)


def _connect_message(code: int) -> str:
    return _CONNECT_ERRORS.get(int(code), f"System error {int(code)} mapping {P_DRIVE}")


def _connect_p_drive(server_unc: str, username: str, password: str) -> int:
    """One WNetAddConnection2W call. Returns the Win32 error code (0 = ok).

    NULL user/password (username="" here) means "use whatever this logon
    session already has stored" -- exactly what an uncredentialed `net use`
    did, including falling back to the Credential Manager entry
    persist_credentials() writes."""
    nr = NETRESOURCEW()
    nr.dwType = RESOURCETYPE_DISK
    nr.lpLocalName = P_DRIVE
    nr.lpRemoteName = str(server_unc)
    return int(_wnet_add_fn()(nr, password or None, username or None,
                              CONNECT_TEMPORARY))


def _connect_p_drive_timed(
    server_unc: str, username: str, password: str, timeout: float = _TIMEOUT_S,
) -> Optional[int]:
    """The connect under the same 30 s ceiling subprocess.run(timeout=30) gave
    `net use`. Returns the error code, or None when the call outlived it.

    WNetAddConnection2W blocks for however long the SMB client takes to give
    up on an unreachable host (a sleeping tailnet peer is the ROUTINE case for
    remote editors), and there is no portable way to cancel a call already in
    flight -- no handle, no CancelSynchronousIo we could aim reliably. So the
    ceiling comes from not waiting: the call runs on a daemon thread we stop
    joining after `timeout` and whose eventual result is discarded. Daemon so
    an orphan can never hold up process exit. If the connect does land later,
    P: simply ends up on the server -- the same loose end a timed-out `net
    use` left behind, and app.swap_p_to_server's restore-to-local puts it
    right on the next swap."""
    outcome: list[tuple[str, object]] = []

    def _call() -> None:
        try:
            outcome.append(("code", _connect_p_drive(server_unc, username, password)))
        except BaseException as exc:      # noqa: BLE001 -- reported on the caller's thread
            outcome.append(("exc", exc))

    worker = threading.Thread(target=_call, name="ccsync-p-connect", daemon=True)
    worker.start()
    worker.join(timeout)
    if not outcome:
        return None                        # still running (or gone) -- give up
    kind, value = outcome[0]
    if kind == "exc":
        raise value                        # type: ignore[misc]
    return int(value)                      # type: ignore[arg-type]


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
        except Exception as exc:
            log.debug("unmap step [%s] failed: %s", _redacted(args), type(exc).__name__)


def _error_tail(proc: "subprocess.CompletedProcess") -> str:
    text = ((proc.stderr or "") + " " + (proc.stdout or "")).strip()
    return " ".join(text.split())[-200:]


def _redacted(args: list[str], password: str = "") -> str:
    """An argv safe to log. SYNC-4 (2026-08-11): the grade-swap handed the
    editor's TrueNAS password to `net use` POSITIONALLY and to cmdkey as
    `/pass:`, and both `TimeoutExpired.__str__` and a CalledProcessError
    traceback embed the whole argv -- which app.swap_p_to_server logs at INFO,
    shows as a tray balloon, and copy_diagnostics() sweeps to the clipboard.
    An SMB connect to a sleeping tailnet host reaches the 30 s timeout
    routinely, so this was the common path, not the exotic one.

    R1 (2026-08-11) removed both producers -- no argv carries the password any
    more -- but every remaining shell-out (unmap, the loopback remap, the
    queries) still goes through here: the invariant is "no argv reaches a log
    unredacted", not "this particular argv was dangerous". Anything reinstated
    with a credential on it inherits the guard instead of re-learning it."""
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
    not roll back. username/password (the editor's TrueNAS login) go to
    WNetAddConnection2W when given -- the retry path after is_auth_failure().

    R1 (2026-08-11): the connect itself no longer spawns anything, so the
    password touches no argv. run_fn still drives the unmap steps (nothing
    secret on those) and stays in the signature -- app.py and the tray call
    this exact shape."""
    if not str(server_unc or "").strip():
        return False, "server_p_unc is not configured"
    _unmap(run_fn)
    try:
        # _TIMEOUT_S passed rather than defaulted so the ceiling is read at
        # call time -- one knob for the subprocess and the Win32 halves alike.
        code = _connect_p_drive_timed(str(server_unc), username, password, _TIMEOUT_S)
    except Exception as exc:
        # SYNC-4 (2026-08-11): the exception must NEVER be interpolated here.
        # There is no argv left to leak (R1), but a ctypes ArgumentError
        # repr's the arguments it was handed -- the password among them.
        log.debug("WNetAddConnection2W raised %s (target %s, user %s)",
                  type(exc).__name__, server_unc, username or "<stored>")
        return False, f"mapping P: failed: {type(exc).__name__}"
    if code is None:
        return False, _CONNECT_TIMEOUT_MSG
    if code != 0:
        return False, _connect_message(code)
    return True, "P: now shows the SERVER originals"


def persist_credentials(
    server_unc: str, username: str, password: str, run_fn: RunFn = _default_run,
) -> None:
    """Best-effort: store the server login in Windows Credential Manager so
    every future swap (and Explorer itself) authenticates silently.

    R1 (2026-08-11): this was `cmdkey /add:<host> /user:<u> /pass:<password>`
    -- the password on an argv, and (before SYNC-4) in the traceback of any
    failure. CredWriteW is what cmdkey calls; the blob is a struct field.
    run_fn is now unused and kept only because the signature is public (app.py
    and test_app.py both patch/call it with a runner slot)."""
    host = _unc_host(server_unc)
    if not (host and username):
        return
    try:
        stored = _cred_write(host, username, password or "")
    except Exception as exc:
        # Never fatal, and never with exc_info: a ctypes traceback's exception
        # line carries the arguments, password included (SYNC-4).
        log.debug("CredWriteW raised %s for %s", type(exc).__name__, host)
        return
    if not stored:
        # GetLastError is deliberately not read: it is per-thread state that
        # anything between the call and here could have reset, and this is a
        # best-effort convenience -- the swap already worked.
        log.debug("CredWriteW declined to store the login for %s", host)


def _cred_write(target: str, username: str, password: str) -> bool:
    """One CredWriteW of a CRED_TYPE_DOMAIN_PASSWORD entry -- the shape
    `cmdkey /add:<host>` writes, so Explorer and a later uncredentialed
    connect find it exactly as before."""
    blob = str(password or "").encode("utf-16-le")
    buffer = ctypes.create_string_buffer(blob, len(blob)) if blob else None
    cred = CREDENTIALW()
    cred.Type = CRED_TYPE_DOMAIN_PASSWORD
    cred.TargetName = str(target)
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buffer, ctypes.c_void_p) if buffer else None
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = str(username)
    # `buffer` must outlive the call -- it is the memory CredentialBlob points
    # at, and ctypes frees it with the last reference.
    return bool(_cred_write_fn()(cred, 0))


def swap_to_local(local_root: str, run_fn: RunFn = _default_run) -> tuple[bool, str]:
    """Map P: back to this machine's copy: loopback share first (the
    bootstrap's primary), subst fallback (its legacy)."""
    _unmap(run_fn)
    # Still a subprocess on purpose (R1): the loopback share is this machine's
    # own, authenticated by the caller's token -- there is no secret to keep
    # off an argv here, and net use is the shape the bootstrap already uses.
    loopback = ["net", "use", P_DRIVE, f"\\\\localhost\\{LOOPBACK_SHARE}",
                "/persistent:yes"]
    try:
        proc = run_fn(loopback)
        if proc.returncode == 0:
            return True, "P: is back to your local copy (proxies)"
    except Exception as exc:
        log.debug("loopback remap [%s] failed: %s", _redacted(loopback),
                  type(exc).__name__)
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
