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


# bug-hunt-2026-09-03 comp-resolve-5: lsof truncates COMMAND to 9 characters
# unless it is told not to, so this is what a Mac really reported. fuscript is
# re-parented here (R1), which is the case the name check is the fallback for.
LSOF_TRUNCATED = """p300
cfuscript
R1
f7
n*:1144
TST=LISTEN
p200
cDaVinci r
R1
f120
n127.0.0.1:50413->127.0.0.1:1144
TST=ESTABLISHED
"""


def test_a_clipped_resolve_command_is_still_recognised_as_the_host():
    rows, procs = ss.parse_lsof(LSOF_TRUNCATED)
    assert procs[200] == ("davinci r", 1)
    # The parent arm cannot answer here (fuscript's parent is 1), so this is
    # the name arm alone: before the fix it said STARTING for ever.
    assert ss.classify(rows, procs, 999)[0] == ss.READY


def test_a_short_name_is_not_mistaken_for_a_clipped_resolve():
    assert ss.is_resolve_name("res") is False
    assert ss.is_resolve_name("") is False
    assert ss.is_resolve_name("resolve") is True
    assert ss.is_resolve_name("DaVinci Resolve") is True
    assert ss.is_resolve_name("python.exe") is False


def test_the_darwin_probe_asks_lsof_not_to_truncate(monkeypatch):
    seen = {}

    class _Out:
        stdout = LSOF_TRUNCATED
        returncode = 0

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        return _Out()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    rows, procs = ss._darwin_tables()
    assert "+c" in seen["argv"]
    assert seen["argv"][seen["argv"].index("+c") + 1] == "0"
    assert ss.classify(rows, procs, 999)[0] == ss.READY


# CR-385 (2026-11-17): an editor's Windows reported fuscript's listener with
# state 0, sshd's with 1 and others with 6, while all of them were listening.
# These rows are the measured ones (ports and states), with the test's pids.
def _cr346_tables(fuscript_state=0, host_state=ss._ESTABLISHED):
    listeners = [
        (fuscript_state, 1144, 0, FUSCRIPT),
        (1, 22, 0, OTHER),          # sshd, serving the session that measured it
        (6, 135, 0, OTHER),
        (2, 15000, 0, RESOLVE),
    ]
    connections = [
        (ss._ESTABLISHED, 1144, 59459, FUSCRIPT),
        (host_state, 59459, 1144, RESOLVE),
        (11, 50413, 1144, 0),       # TIME_WAIT from a past poll, owner pid 0
    ]
    return listeners, connections


def test_a_listener_with_a_wrong_state_still_counts_as_listening():
    """CR-385: the old reader filtered on state == LISTEN and answered ABSENT
    for a script server with Resolve registered; the companion then never
    connected again ("isn't accepting scripting connections")."""
    rows, odd = ss.normalize_windows_rows(*_cr346_tables())
    assert odd == {0: 1, 1: 1, 6: 1}
    phase, why = ss.classify(rows, PROCS, ME)
    assert phase == ss.READY, why


def test_unreliable_states_still_hold_off_in_the_launch_window():
    """CR-68 must survive CR-385: server up, Resolve's registration still a
    handshake in flight (or absent) is STARTING, never READY."""
    for host_state in (3, 4):   # SYN_SENT, SYN_RCVD
        rows, _ = ss.normalize_windows_rows(*_cr346_tables(host_state=host_state))
        assert ss.classify(rows, PROCS, ME)[0] == ss.STARTING
    listeners, connections = _cr346_tables()
    rows, _ = ss.normalize_windows_rows(listeners, connections[:1])
    assert ss.classify(rows, PROCS, ME)[0] == ss.STARTING


def test_unreliable_states_take_a_misread_registration_as_established():
    """On the measured machine connection states read right, but a machine
    that mislabels listeners has shown its state field cannot be trusted;
    a non-handshake value on Resolve's own row to 1144 is its registration."""
    rows, _ = ss.normalize_windows_rows(*_cr346_tables(host_state=0))
    assert ss.classify(rows, PROCS, ME)[0] == ss.READY


def test_a_healthy_machine_classifies_exactly_as_before():
    """Every listener reads LISTEN: nothing is reinterpreted, so a Resolve
    row in SYN_SENT or an odd state is still not a registration."""
    listeners = [(ss._LISTEN, 1144, 0, FUSCRIPT), (ss._LISTEN, 22, 0, OTHER)]
    for host_state, expected in ((ss._ESTABLISHED, ss.READY), (3, ss.STARTING), (6, ss.STARTING)):
        rows, odd = ss.normalize_windows_rows(listeners, [(host_state, 59459, 1144, RESOLVE)])
        assert odd == {}
        assert ss.classify(rows, PROCS, ME)[0] == expected


def test_no_listener_is_still_absent_with_unreliable_states():
    listeners, connections = _cr346_tables()
    rows, odd = ss.normalize_windows_rows(listeners[1:], [])
    assert odd and ss.classify(rows, PROCS, ME)[0] == ss.ABSENT


def test_an_unreadable_windows_table_fails_open(monkeypatch):
    """The reader used to skip a failed GetExtendedTcpTable and answer ABSENT,
    contradicting the documented fail-open; now it raises into UNKNOWN."""
    monkeypatch.setattr(ss.platform, "system", lambda: "Windows")

    def boom(_cls):
        raise OSError("GetExtendedTcpTable(class 3, af 2) failed: 122")

    monkeypatch.setattr(ss, "_windows_table", boom)
    assert ss._probe_uncached()[0] == ss.UNKNOWN
