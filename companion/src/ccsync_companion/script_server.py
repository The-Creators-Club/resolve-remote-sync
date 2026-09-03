"""Is Resolve's script server ready to take a client? Asked WITHOUT connecting.

Why this exists (2026-08-21, CR-68). Resolve's scripting API is brokered by
a child process, `fuscript.exe` (`fuscript` on macOS), that Resolve spawns
late in its own launch -- 90 s to 470 s after the process starts on the base
rig, because the project library comes first. The server listens on TCP
1144; Resolve then connects to it and registers itself as the "HostApp";
a client such as fusionscript.dll's `scriptapp("Resolve")` connects to 1144
and is handed Resolve's own port. The server EXITS when its last connection
closes. So a client that connects in the window between the server starting
and Resolve registering -- and then disconnects, because there is no host to
be handed -- takes the server down with it. Resolve's own log shows exactly
that (Support/logs/davinci_resolve.log):

    Started script server: 30320
    Failed to connect to script server, retrying
    Started script server: 27240
    Failed to connect to script server, retrying
    Started script server: 8392
    Failed to connect to script server
    Script server log:
    90.859 Script Server Started
    91.125 Incoming connection            <- the companion's 3 s poll
    91.125 HostApp create
    91.234 HostApp destroy
    91.234 Script Server Terminated: done: 1, err: 0

Resolve tries three times, each costing it seconds of its launch (the
"Resolve hangs for 10-20 s" every editor reported), and then gives up FOR
THE WHOLE SESSION: nothing retries a script server that failed at launch.
Every client on the machine is dark until Resolve is quit and reopened with
no client polling. That is the "close Resolve, close the companion, open
Resolve, open the companion" dance.

Any poller can trip it -- the timeline watcher, the media-tree refresh, the
MCP server, a second product on the same machine -- which is why the answer
is not "poll slower" but "never connect until Resolve has registered". The
kernel already knows whether it has: a LISTENING socket on 1144 owned by the
script server, and an ESTABLISHED connection to 1144 owned by the server's
PARENT process (Resolve). Reading the TCP table costs ~6 ms on Windows and
opens nothing, so it can be asked before every `scriptapp` call.

Four answers:

    READY     host registered        -> connect
    STARTING  server up, no host yet -> DO NOT connect; this is the window
    ABSENT    no server listening    -> DO NOT connect either (see below)
    UNKNOWN   the table could not be read / the listener is not fuscript /
              unsupported platform -> fail OPEN, i.e. the old behaviour

ABSENT holds off too, and that is the lesson of the first shipped version
(0.9.45, same evening): `scriptapp("Resolve")` with no server present does
not fail fast -- measured 4.0 s per call on the base rig, 8 s when a second
thread queues behind it, retrying its connect the whole time. A client that
"just checked whether Resolve is up" is therefore INSIDE a connect loop at
the very moment the server appears, and a table snapshot taken before the
call cannot see that. 0.9.45 failed open on "no listener", went into that
4 s loop, and killed the server exactly as before (two launches, 17:56 and
17:57 on 2026-08-21); the test harness that had proven the idea skipped on
"no listener" as well, which is why it passed. So: connect only when there
is positively something registered to connect to. Fail-open is kept for the
cases where the probe itself is the thing in doubt.
"""

from __future__ import annotations

import logging
import os
import platform
import struct
import subprocess
import threading
import time
from typing import Any, Callable, Iterable, Optional

log = logging.getLogger("ccsync.resolve.script_server")

READY = "ready"
STARTING = "starting"
ABSENT = "absent"
UNKNOWN = "unknown"

# Fusion's script server port. Fixed in every Resolve release to date (it is
# the same 1144 FusionScript has used since Fusion 5); there is no preference
# for it in Resolve. If it ever moved, the listener check below simply never
# matches and the module fails open.
SCRIPT_SERVER_PORT = 1144

# The script-server binary's process name, used to make sure a listener on
# 1144 is actually Fusion's and not some unrelated service that happens to
# hold the port (fail open in that case, rather than waiting for a host that
# will never register).
_SERVER_NAMES = {"fuscript.exe", "fuscript"}
_RESOLVE_NAMES = {"resolve.exe", "resolve", "davinci resolve"}

# The shortest observed name that may be matched as a truncated spelling of
# one of the above. "resolve" is 7 characters; anything shorter is somebody
# else's process, not a clipped Resolve.
_NAME_PREFIX_MIN = 7


def is_resolve_name(name: str) -> bool:
    """Is this process name Resolve's, allowing for a clipped one?

    bug-hunt-2026-09-03 comp-resolve-5: lsof truncates COMMAND to 9
    characters by default (`+c w`, w=9), including in -F output, so
    `DaVinci Resolve` arrives as `davinci r` and an exact-set test can never
    match on a Mac. The probe passes `+c 0` now, but a machine whose lsof
    ignores it (or any other clipping producer) must still be recognised, or
    READY on macOS rests entirely on the parent-pid arm and this documented
    fallback is dead code.
    """
    name = (name or "").strip().lower()
    if not name:
        return False
    if name in _RESOLVE_NAMES:
        return True
    if len(name) < _NAME_PREFIX_MIN:
        return False
    return any(known.startswith(name) for known in _RESOLVE_NAMES)


# A snapshot survives this long. Four companion threads poll the bridge and
# the watcher alone asks every 3 s; the table is cheap but not free, and two
# asks within a quarter second cannot see a different Resolve.
_CACHE_SECONDS = 0.25
_cache_lock = threading.Lock()
_cache: Optional[tuple[float, tuple[str, str]]] = None

# TCP states as MIB_TCP_STATE (Windows) -- lsof's names are mapped onto these.
_LISTEN = 2
_ESTABLISHED = 5


# -- the platform-independent decision ---------------------------------------

def classify(
    tcp_rows: Iterable[tuple[int, int, int, int]],
    processes: dict[int, tuple[str, int]],
    own_pid: int,
) -> tuple[str, str]:
    """Decide from a TCP table and a process table. Pure; unit-tested.

    `tcp_rows`: (state, local_port, remote_port, owning_pid).
    `processes`: pid -> (lowercase exe name, parent pid).
    Returns (READY | STARTING | UNKNOWN, human reason).
    """
    listeners = [pid for state, lport, _rport, pid in tcp_rows
                 if state == _LISTEN and lport == SCRIPT_SERVER_PORT]
    if not listeners:
        return ABSENT, "no script server listening on %d" % SCRIPT_SERVER_PORT
    server_pids = [pid for pid in listeners
                   if processes.get(pid, ("", 0))[0] in _SERVER_NAMES]
    if not server_pids:
        return UNKNOWN, ("port %d is held by %s, not Fusion's script server"
                         % (SCRIPT_SERVER_PORT,
                            ", ".join(processes.get(p, ("pid %d" % p, 0))[0]
                                      for p in listeners)))
    parents = {processes[pid][1] for pid in server_pids if pid in processes}
    clients = [pid for state, _lport, rport, pid in tcp_rows
               if state == _ESTABLISHED and rport == SCRIPT_SERVER_PORT
               and pid != own_pid and pid not in server_pids]
    for pid in clients:
        name = processes.get(pid, ("", 0))[0]
        if pid in parents or is_resolve_name(name):
            return READY, "Resolve (pid %d) is registered with its script server" % pid
    return STARTING, ("script server pid %s is up but Resolve has not registered "
                      "with it yet" % ",".join(str(p) for p in server_pids))


# -- Windows: GetExtendedTcpTable + Toolhelp32, no subprocess ----------------

def _windows_tcp_rows() -> list[tuple[int, int, int, int]]:
    import ctypes
    import ctypes.wintypes as wt
    import socket

    iphlp = ctypes.windll.iphlpapi  # type: ignore[attr-defined]
    iphlp.GetExtendedTcpTable.restype = wt.DWORD
    iphlp.GetExtendedTcpTable.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wt.DWORD), wt.BOOL, wt.ULONG, ctypes.c_int, wt.ULONG,
    ]
    rows: list[tuple[int, int, int, int]] = []
    # (address family, row struct size, unpack format, field index of
    # lport/rport/state/pid). MIB_TCPROW_OWNER_PID: state, laddr, lport,
    # raddr, rport, pid. MIB_TCP6ROW_OWNER_PID: laddr[16], lscope, lport,
    # raddr[16], rscope, rport, state, pid.
    for family, fmt, idx in (
        (2, "IIIIII", (2, 4, 0, 5)),
        (23, "16sII16sIIII", (2, 5, 6, 7)),
    ):
        size = wt.DWORD(0)
        iphlp.GetExtendedTcpTable(None, ctypes.byref(size), False, family, 5, 0)
        if size.value == 0:
            continue
        buf = ctypes.create_string_buffer(size.value)
        if iphlp.GetExtendedTcpTable(buf, ctypes.byref(size), False, family, 5, 0) != 0:
            continue
        count = struct.unpack_from("I", buf, 0)[0]
        rowsize = struct.calcsize(fmt)
        for i in range(count):
            fields = struct.unpack_from(fmt, buf, 4 + i * rowsize)
            lport = socket.ntohs(fields[idx[0]] & 0xFFFF)
            rport = socket.ntohs(fields[idx[1]] & 0xFFFF)
            rows.append((int(fields[idx[2]]), lport, rport, int(fields[idx[3]])))
    return rows


def _windows_processes() -> dict[int, tuple[str, int]]:
    import ctypes
    import ctypes.wintypes as wt

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
            ("th32ProcessID", wt.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(wt.ULONG)),
            ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
            ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG),
            ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_char * 260),
        ]

    k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    # Explicit HANDLE types: ctypes' default c_int return would truncate a
    # 64-bit handle before Process32First ever saw it.
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k32.Process32First.argtypes = [wt.HANDLE, ctypes.c_void_p]
    k32.Process32Next.argtypes = [wt.HANDLE, ctypes.c_void_p]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    out: dict[int, tuple[str, int]] = {}
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    if snap is None or snap == wt.HANDLE(-1).value:
        return out
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if k32.Process32First(snap, ctypes.byref(entry)):
            while True:
                name = entry.szExeFile.decode("mbcs", errors="replace").lower()
                out[int(entry.th32ProcessID)] = (name, int(entry.th32ParentProcessID))
                if not k32.Process32Next(snap, ctypes.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snap)
    return out


# -- macOS: lsof, with fail-open parsing --------------------------------------
#
# Untested against a live Mac when written (the studio Mac was off the
# tailnet on 2026-08-21); every parse failure returns UNKNOWN, which is the
# pre-existing behaviour. `fuscript` on macOS binds the same 1144.

_LSOF_STATES = {"LISTEN": _LISTEN, "ESTABLISHED": _ESTABLISHED}


def parse_lsof(text: str) -> tuple[list[tuple[int, int, int, int]], dict[int, tuple[str, int]]]:
    """`lsof -nP -iTCP:1144 -F pcRnT` output -> (tcp rows, processes).

    -F emits one field per line: p<pid>, c<command>, R<parent pid>, then
    per file n<name> and T<ST=state>. Pure; unit-tested.
    """
    rows: list[tuple[int, int, int, int]] = []
    procs: dict[int, tuple[str, int]] = {}
    pid = 0
    name = ""
    parent = 0
    endpoint: Optional[str] = None
    for line in text.splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p":
            try:
                pid = int(value)
            except ValueError:
                pid = 0
            name, parent, endpoint = "", 0, None
            procs[pid] = (name, parent)
        elif tag == "c":
            name = value.strip().lower()
            procs[pid] = (name, parent)
        elif tag == "R":
            try:
                parent = int(value)
            except ValueError:
                parent = 0
            procs[pid] = (name, parent)
        elif tag == "n":
            endpoint = value
        elif tag == "T" and value.startswith("ST=") and endpoint is not None:
            state = _LSOF_STATES.get(value[3:].strip())
            if state is None:
                continue
            local, _, remote = endpoint.partition("->")
            try:
                lport = int(local.rsplit(":", 1)[1])
                rport = int(remote.rsplit(":", 1)[1]) if remote else 0
            except (IndexError, ValueError):
                continue
            rows.append((state, lport, rport, pid))
    return rows, procs


def _darwin_tables() -> tuple[list[tuple[int, int, int, int]], dict[int, tuple[str, int]]]:
    out = subprocess.run(
        # `+c 0` turns off lsof's 9-character COMMAND truncation, which
        # otherwise reports `DaVinci Resolve` as `davinci r` and makes the
        # name half of classify() unmatchable (bug-hunt-2026-09-03
        # comp-resolve-5). is_resolve_name still tolerates a clipped name for
        # an lsof that does not honour it.
        ["lsof", "-nP", "+c", "0", "-iTCP:%d" % SCRIPT_SERVER_PORT, "-F", "pcRnT"],
        capture_output=True, text=True, timeout=5,
    )
    # lsof exits 1 when nothing matches -- that is "no listener", not an
    # error, and parse_lsof of an empty string says exactly that.
    return parse_lsof(out.stdout or "")


# -- the entry point ----------------------------------------------------------

def _probe_uncached() -> tuple[str, str]:
    system = platform.system()
    try:
        if system == "Windows":
            rows = _windows_tcp_rows()
            procs = _windows_processes()
        elif system == "Darwin":
            rows, procs = _darwin_tables()
        else:
            return UNKNOWN, "no script-server probe on %s" % system
    except Exception as exc:
        log.debug("script server probe failed (%s) -- failing open", exc)
        return UNKNOWN, "probe failed: %s" % exc
    return classify(rows, procs, os.getpid())


def state() -> tuple[str, str]:
    """(READY | STARTING | UNKNOWN, reason). Never raises; cached 250 ms."""
    global _cache
    now = time.monotonic()
    with _cache_lock:
        if _cache is not None and (now - _cache[0]) < _CACHE_SECONDS:
            return _cache[1]
    try:
        answer = _probe_uncached()
    except Exception as exc:  # pragma: no cover -- _probe_uncached catches
        answer = (UNKNOWN, "probe failed: %s" % exc)
    with _cache_lock:
        _cache = (time.monotonic(), answer)
    return answer


def is_starting() -> bool:
    """True only in the window where connecting would kill the script server."""
    return state()[0] == STARTING


def ready_to_connect() -> bool:
    """May scriptapp() be called right now? READY, or UNKNOWN (fail open).

    STARTING and ABSENT both say no: in the first a connection kills the
    server, in the second scriptapp() sits in a multi-second retry loop that
    becomes the first case the moment the server appears. Never raises."""
    try:
        return state()[0] in (READY, UNKNOWN)
    except Exception:
        return True


def reset_cache() -> None:
    """Tests only."""
    global _cache
    with _cache_lock:
        _cache = None
