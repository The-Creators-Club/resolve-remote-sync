"""The CR-68 launch-window probe: decide from tables, never by connecting."""

from __future__ import annotations

import os

import pytest

from ccsync_companion import script_server as ss

FUSCRIPT, RESOLVE, ME, OTHER = 300, 200, 999, 42
PROCS = {
    FUSCRIPT: ("fuscript.exe", RESOLVE),
    RESOLVE: ("resolve.exe", 1),
    ME: ("ccsync-companion.exe", 1),
    OTHER: ("python.exe", 1),
}
LISTEN = (ss._LISTEN, 1144, 0, FUSCRIPT)


def test_no_listener_is_absent_and_holds_off():
    """0.9.45 failed open here and died for it: scriptapp() with no server
    blocks ~4 s retrying, and greets the server the moment it appears."""
    phase, why = ss.classify([], PROCS, ME)
    assert phase == ss.ABSENT
    assert "no script server" in why


@pytest.mark.parametrize("phase,expected", [
    (ss.READY, True), (ss.UNKNOWN, True), (ss.STARTING, False), (ss.ABSENT, False),
])
def test_ready_to_connect_only_for_ready_or_fail_open(monkeypatch, phase, expected):
    monkeypatch.setattr(ss, "state", lambda: (phase, "x"))
    assert ss.ready_to_connect() is expected


def test_server_up_with_no_host_is_the_launch_window():
    """The state that used to kill the API: fuscript listening, Resolve not
    yet connected to it. The one answer that withholds a connection."""
    phase, why = ss.classify([LISTEN], PROCS, ME)
    assert phase == ss.STARTING
    assert "not registered" in why


def test_resolve_registered_is_ready():
    rows = [LISTEN, (ss._ESTABLISHED, 50413, 1144, RESOLVE)]
    assert ss.classify(rows, PROCS, ME)[0] == ss.READY


def test_the_host_is_recognised_by_parentage_not_only_by_name():
    """Resolve's exe name differs by platform and install; being the script
    server's parent is the property that matters."""
    procs = dict(PROCS)
    procs[RESOLVE] = ("someothername", 1)
    rows = [LISTEN, (ss._ESTABLISHED, 50413, 1144, RESOLVE)]
    assert ss.classify(rows, procs, ME)[0] == ss.READY


def test_another_client_connected_does_not_count_as_the_host():
    """A second client (the MCP server, the companion's own other thread)
    sitting on 1144 is not Resolve registering. Before Resolve does, it is
    exactly the connection that kills the server."""
    rows = [LISTEN, (ss._ESTABLISHED, 50500, 1144, OTHER),
            (ss._ESTABLISHED, 50501, 1144, ME)]
    assert ss.classify(rows, PROCS, ME)[0] == ss.STARTING


def test_a_foreign_listener_on_1144_fails_open():
    """Something that is not fuscript holding the port must not park the
    bridge for ever behind a host that will never register."""
    rows = [(ss._LISTEN, 1144, 0, OTHER)]
    phase, why = ss.classify(rows, PROCS, ME)
    assert phase == ss.UNKNOWN
    assert "python.exe" in why


def test_a_listener_whose_process_is_unknown_fails_open():
    """A pid the process snapshot missed (raced its exit) is doubt, not a
    verdict."""
    assert ss.classify([(ss._LISTEN, 1144, 0, 12345)], PROCS, ME)[0] == ss.UNKNOWN


def test_time_wait_and_other_states_are_ignored():
    """The table is full of TIME_WAIT rows to 1144 from every past poll;
    only LISTEN and ESTABLISHED say anything about now."""
    rows = [LISTEN, (11, 50413, 1144, RESOLVE), (3, 50414, 1144, RESOLVE)]
    assert ss.classify(rows, PROCS, ME)[0] == ss.STARTING


LSOF = """p300
cfuscript
R200
f7
n*:1144
TST=LISTEN
f9
n127.0.0.1:1144->127.0.0.1:50413
TST=ESTABLISHED
p200
cResolve
R1
f120
n127.0.0.1:50413->127.0.0.1:1144
TST=ESTABLISHED
"""


def test_lsof_output_parses_to_the_same_tables():
    rows, procs = ss.parse_lsof(LSOF)
    assert procs[300] == ("fuscript", 200)
    assert procs[200] == ("resolve", 1)
    assert (ss._LISTEN, 1144, 0, 300) in rows
    assert (ss._ESTABLISHED, 50413, 1144, 200) in rows
    assert ss.classify(rows, procs, 999)[0] == ss.READY


def test_lsof_with_nothing_matching_is_absent():
    rows, procs = ss.parse_lsof("")
    assert ss.classify(rows, procs, 999)[0] == ss.ABSENT


def test_garbled_lsof_is_absent_not_an_exception():
    rows, procs = ss.parse_lsof("pabc\nngarbage\nTST=ESTABLISHED\nTST=WEIRD\n")
    assert ss.classify(rows, procs, 999)[0] == ss.ABSENT


def test_state_caches_briefly_and_never_raises(monkeypatch):
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        return (ss.STARTING, "x")

    # conftest pins state() itself; this test wants the real one.
    monkeypatch.setattr(ss, "state", ss.state.__wrapped__ if hasattr(ss.state, "__wrapped__") else _real_state)
    monkeypatch.setattr(ss, "_probe_uncached", probe)
    ss.reset_cache()
    assert ss.state()[0] == ss.STARTING
    assert ss.is_starting()
    assert calls["n"] == 1
    ss.reset_cache()

    def boom():
        raise RuntimeError("no table")

    monkeypatch.setattr(ss, "_probe_uncached", boom)
    assert ss.state()[0] == ss.UNKNOWN
    ss.reset_cache()


# The module-level function object, captured at import before conftest's
# autouse fixture replaces the attribute.
_real_state = ss.state


@pytest.mark.skipif(not hasattr(__import__("ctypes"), "windll"), reason="Windows only")
def test_the_windows_tables_read_without_error():
    """Real GetExtendedTcpTable + Toolhelp32 on this machine: shapes only."""
    rows = ss._windows_tcp_rows()
    procs = ss._windows_processes()
    assert rows and all(len(r) == 4 for r in rows)
    assert os.getpid() in procs
    assert ss._probe_uncached()[0] in (ss.READY, ss.STARTING, ss.ABSENT, ss.UNKNOWN)
