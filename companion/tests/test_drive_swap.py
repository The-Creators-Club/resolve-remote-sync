"""P: grade-swap tests: target detection/classification, the swap command
sequences (scripted run_fn -- no real net use / subst) and, since R1
(2026-08-11), the in-process Win32 credential paths with mpr.dll/advapi32
replaced by fake function pointers.

NOTHING here may reach a live Win32 call: a real WNetAddConnection2W would
remap the developer machine's own P:, and the base rig's P: is its whole tree.
The _no_live_win32 fixture is autouse for exactly that reason.
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import threading
import time

import pytest

from ccsync_companion import drive_swap


def _proc(rc=0, out="", err=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=out, stderr=err)


# -- the Win32 seam ---------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_live_win32(monkeypatch):
    """R1: patch the FUNCTION POINTERS, never ctypes itself. Any test that
    reaches mpr.dll or advapi32 without installing its own fake fails loudly
    instead of touching this machine's mapping or Credential Manager."""
    def _forbidden(*_args, **_kw):
        raise AssertionError("a live Win32 credential call escaped the test")

    monkeypatch.setattr(drive_swap, "_WNET_ADD", _forbidden)
    monkeypatch.setattr(drive_swap, "_CRED_WRITE", _forbidden)


def _fake_wnet(monkeypatch, code=0):
    """Install a WNetAddConnection2W stand-in; returns the recorded call list
    of (remote, local, username, password, flags)."""
    calls = []

    def _add(netresource, password, username, flags):
        calls.append((netresource.lpRemoteName, netresource.lpLocalName,
                      username, password, flags))
        return code

    monkeypatch.setattr(drive_swap, "_WNET_ADD", _add)
    return calls


def _fake_credwrite(monkeypatch, result=1, raises=None):
    """Install a CredWriteW stand-in; returns the recorded call list of
    (target, username, password, type, persist)."""
    calls = []

    def _write(cred, flags):
        if raises is not None:
            raise raises
        blob = ""
        if cred.CredentialBlob and cred.CredentialBlobSize:
            blob = ctypes.string_at(
                cred.CredentialBlob, cred.CredentialBlobSize).decode("utf-16-le")
        calls.append((cred.TargetName, cred.UserName, blob, cred.Type, cred.Persist))
        return result

    monkeypatch.setattr(drive_swap, "_CRED_WRITE", _write)
    return calls


def test_classify_p_target():
    f = drive_swap.classify_p_target
    assert f("\\\\localhost\\CCSync_P", r"D:\Creators_Club", "") == "local"
    assert f(r"D:\Creators_Club", r"D:\Creators_Club", "") == "local"   # legacy subst
    unc = "\\\\100.65.15.123\\TheCreatorsPool\\Creators_Club"
    assert f(unc, r"D:\Creators_Club", unc) == "server"
    assert f(unc + "\\", r"D:\Creators_Club", unc) == "server"
    assert f("\\\\OTHER\\Share", r"D:\Creators_Club", unc) == "other"
    assert f("", r"D:\Creators_Club", unc) == "none"


def test_current_p_target_parses_net_use_then_subst():
    def net_use_run(args):
        if args[:2] == ["net", "use"]:
            return _proc(0, "Remote name  \\\\localhost\\CCSync_P\nStatus OK\n")
        raise AssertionError("should not reach subst")

    assert drive_swap.current_p_target(net_use_run) == "\\\\localhost\\CCSync_P"

    def subst_run(args):
        if args[:2] == ["net", "use"]:
            return _proc(2, "", "The network connection could not be found.")
        return _proc(0, "P:\\: => D:\\Creators_Club\n")

    assert drive_swap.current_p_target(subst_run) == "D:\\Creators_Club"


def test_swap_to_server_sequence_and_auth_hint(monkeypatch):
    calls = []
    unc = "\\\\nas\\TheCreatorsPool\\Creators_Club"

    def ok_run(args):
        calls.append(args)
        return _proc(0, "")

    connects = _fake_wnet(monkeypatch, code=0)
    ok, msg = drive_swap.swap_to_server(unc, ok_run)
    assert ok and "SERVER" in msg
    # unmap both styles (still subprocess -- no secret on those)...
    assert calls == [["net", "use", "P:", "/delete", "/y"], ["subst", "P:", "/D"]]
    # ...then the connect, in-process (R1). No credentials given == NULL user
    # and NULL password: "use whatever this logon session already has".
    assert connects == [(unc, "P:", None, None, drive_swap.CONNECT_TEMPORARY)]

    # ERROR_ACCESS_DENIED -- the tray reacts by asking for the server login.
    _fake_wnet(monkeypatch, code=5)
    ok, msg = drive_swap.swap_to_server(unc, ok_run)
    assert not ok
    assert drive_swap.is_auth_failure(msg)


def test_the_connect_never_asks_windows_to_prompt(monkeypatch):
    """The 2026-07-26 half-hang was net use PROMPTING on a console this
    windowed exe doesn't have. WNetAddConnection2W only prompts when handed
    CONNECT_INTERACTIVE (0x8), so the flags word must never carry it."""
    connects = _fake_wnet(monkeypatch)
    drive_swap.swap_to_server("\\\\nas\\Pool\\CC", lambda args: _proc(0),
                              username="alex", password="pw")
    flags = connects[0][-1]
    assert not flags & 0x00000008           # CONNECT_INTERACTIVE
    assert not flags & 0x00000010           # CONNECT_PROMPT
    assert flags & drive_swap.CONNECT_TEMPORARY   # == /persistent:no


def test_is_auth_failure_recognises_console_prompt_cancel():
    # The live 2026-07-26 failure: net use tried to prompt with no console.
    assert drive_swap.is_auth_failure(
        "System error 1223 has occurred. The operation was canceled by the "
        "user. Enter the username for '100.71.216.3':")
    assert drive_swap.is_auth_failure("The user name or password is incorrect.")
    assert not drive_swap.is_auth_failure("System error 53: network path not found")


@pytest.mark.parametrize("code", [86, 1326, 1223, 5])
def test_bad_credentials_codes_are_classified_as_auth(monkeypatch, code):
    """These four must keep meaning "the server wants credentials" -- that
    classification is what makes the tray offer login-and-retry."""
    _fake_wnet(monkeypatch, code=code)
    ok, msg = drive_swap.swap_to_server("\\\\nas\\Pool\\CC", lambda a: _proc(0),
                                        username="alex", password="pw")
    assert not ok
    assert str(code) in msg
    assert drive_swap.is_auth_failure(msg)


@pytest.mark.parametrize("code,fragment", [(53, "network path"), (67, "network name")])
def test_unreachable_and_bad_share_are_not_auth(monkeypatch, code, fragment):
    _fake_wnet(monkeypatch, code=code)
    ok, msg = drive_swap.swap_to_server("\\\\nas\\Pool\\CC", lambda a: _proc(0))
    assert not ok
    assert fragment in msg
    assert not drive_swap.is_auth_failure(msg)   # no point asking for a login


def test_1219_credential_conflict_reads_as_a_conflict_not_an_auth_failure(monkeypatch):
    """ERROR_SESSION_CREDENTIAL_CONFLICT: Windows already holds a session to
    the host as somebody else. A login prompt + retry cannot fix it (the retry
    returns 1219 again), so the message must carry no _AUTH_HINTS word --
    which net use's own localised text did, incidentally, via "user name"."""
    _fake_wnet(monkeypatch, code=1219)
    ok, msg = drive_swap.swap_to_server("\\\\nas\\Pool\\CC", lambda a: _proc(0),
                                        username="alex", password="pw")
    assert not ok
    assert "1219" in msg and "disconnect" in msg.lower()
    assert not drive_swap.is_auth_failure(msg)


def test_an_unmapped_win32_code_still_reports_something_usable(monkeypatch):
    _fake_wnet(monkeypatch, code=1234)
    ok, msg = drive_swap.swap_to_server("\\\\nas\\Pool\\CC", lambda a: _proc(0))
    assert not ok and "1234" in msg


def test_swap_to_server_with_credentials_and_persist(monkeypatch):
    unc = "\\\\nas\\TheCreatorsPool\\Creators_Club"
    spawned = []

    def run(args):
        spawned.append(args)
        return _proc(0, "")

    connects = _fake_wnet(monkeypatch)
    ok, _ = drive_swap.swap_to_server(unc, run, username="alex", password="pw")
    assert ok
    # R1: the login rides the CALL, not an argv.
    assert connects == [(unc, "P:", "alex", "pw", drive_swap.CONNECT_TEMPORARY)]

    writes = _fake_credwrite(monkeypatch)
    drive_swap.persist_credentials(unc, "alex", "pw", run)
    assert writes == [("nas", "alex", "pw",
                       drive_swap.CRED_TYPE_DOMAIN_PASSWORD,
                       drive_swap.CRED_PERSIST_LOCAL_MACHINE)]

    # missing host/username -> silently does nothing
    writes.clear()
    drive_swap.persist_credentials("", "alex", "pw", run)
    drive_swap.persist_credentials(unc, "", "pw", run)
    assert writes == []

    # ...and none of that spawned anything but the two unmap steps.
    assert spawned == [["net", "use", "P:", "/delete", "/y"], ["subst", "P:", "/D"]]


def test_swap_to_local_prefers_loopback_then_subst():
    calls = []

    def no_loopback_run(args):
        calls.append(args)
        if args[:2] == ["net", "use"] and "CCSync_P" in " ".join(args):
            return _proc(2, "", "share not found")
        return _proc(0, "")

    ok, msg = drive_swap.swap_to_local(r"D:\Creators_Club", no_loopback_run)
    assert ok and "subst" in msg
    assert calls[-1] == ["subst", "P:", r"D:\Creators_Club"]

    # loopback works -> no subst attempted
    calls.clear()

    def loopback_run(args):
        calls.append(args)
        return _proc(0, "")

    ok, msg = drive_swap.swap_to_local(r"D:\Creators_Club", loopback_run)
    assert ok and "subst" not in msg
    # the unmap step's `subst P: /D` is fine; a subst MAPPING (path arg) is not
    assert not any(a[0] == "subst" and a[-1] != "/D" for a in calls)


def test_swap_to_server_unconfigured_refuses():
    ok, msg = drive_swap.swap_to_server("", lambda args: _proc(0))
    assert not ok and "not configured" in msg


def test_derive_server_unc_from_existing_config():
    """Zero-config fleet rollout: host from dashboard_url, share path from
    remote_root's post-pool tail."""
    f = drive_swap.derive_server_unc
    assert f("http://192.168.0.102:8480",
             "/mnt/tank/TheCreatorsPool/Creators_Club") == \
        "\\\\192.168.0.102\\TheCreatorsPool\\Creators_Club"
    assert f("http://100.71.216.3:8480",
             "/mnt/tank/TheCreatorsPool/Creators_Club/") == \
        "\\\\100.71.216.3\\TheCreatorsPool\\Creators_Club"
    # underivable inputs -> "" (feature hidden, never a broken UNC)
    assert f("", "/mnt/tank/X") == ""
    assert f("http://host:1", "") == ""
    assert f("http://host:1", "relative/path") == ""
    assert f("http://host:1", "/mnt/tank") == ""


# -- R1: the 30 s ceiling, now enforced by not waiting ----------------------

def test_a_blocked_connect_is_abandoned_after_the_timeout(monkeypatch):
    """WNetAddConnection2W cannot be cancelled, so the ceiling is a daemon
    thread we stop joining. The call must return promptly and the orphan's
    eventual result must be discarded, not raised at anybody."""
    released = threading.Event()
    finished = threading.Event()

    def _blocking(netresource, password, username, flags):
        released.wait(5)
        finished.set()
        return 0                      # a LATE success -- must change nothing

    monkeypatch.setattr(drive_swap, "_WNET_ADD", _blocking)

    started = time.monotonic()
    code = drive_swap._connect_p_drive_timed(
        "\\\\nas\\Pool\\CC", "alex", _SECRET, timeout=0.1)
    elapsed = time.monotonic() - started

    assert code is None               # "timed out", not an error code
    assert elapsed < 2.0
    released.set()
    assert finished.wait(5)           # the orphan finishes on its own time


def test_an_unreachable_server_times_out_without_leaking_the_password(
        monkeypatch, caplog):
    """SYNC-4 lives on through R1: an SMB connect to a sleeping tailnet host
    reaches the ceiling routinely, and app.swap_p_to_server logs the returned
    message at INFO, shows it as a tray balloon and copy_diagnostics() sweeps
    it to the clipboard."""
    released = threading.Event()
    monkeypatch.setattr(drive_swap, "_TIMEOUT_S", 0.1)
    monkeypatch.setattr(drive_swap, "_WNET_ADD",
                        lambda nr, pw, user, flags: released.wait(10) or 0)

    try:
        with caplog.at_level(logging.DEBUG, logger="ccsync.drive_swap"):
            ok, msg = drive_swap.swap_to_server(
                "\\\\nas\\Pool\\Creators_Club", lambda args: _proc(0),
                username="alex", password=_SECRET,
            )
    finally:
        released.set()      # let the orphan finish now, not in 10 s

    assert not ok
    assert "did not answer" in msg
    assert _SECRET not in msg
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert _SECRET not in logged


def test_a_raising_connect_reports_only_the_exception_type(monkeypatch, caplog):
    """A ctypes ArgumentError repr's the arguments it was handed -- the
    password among them. SYNC-4's rule stands: the type, never the exception."""
    def _boom(netresource, password, username, flags):
        raise ctypes.ArgumentError(f"argument 2: bad value {password!r}")

    monkeypatch.setattr(drive_swap, "_WNET_ADD", _boom)

    with caplog.at_level(logging.DEBUG, logger="ccsync.drive_swap"):
        ok, msg = drive_swap.swap_to_server(
            "\\\\nas\\Pool\\Creators_Club", lambda args: _proc(0),
            username="alex", password=_SECRET)

    assert not ok
    assert "ArgumentError" in msg
    assert _SECRET not in msg
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert _SECRET not in logged
    assert "alex" in logged           # ...but enough context to diagnose with


# -- SYNC-4: the editor's TrueNAS password must never leave this module -----

_SECRET = "hunter2-CreatorsClub"


def test_no_swap_path_puts_the_password_on_an_argv(monkeypatch):
    """R1, the whole point: any process on the box can enumerate command
    lines. Every spawn this module makes during a full credentialed swap +
    persist is recorded here, and none of them may carry the secret."""
    spawned = []

    def recording_run(args):
        spawned.append(list(args))
        return _proc(0, "")

    unc = "\\\\nas\\Pool\\Creators_Club"
    _fake_wnet(monkeypatch)
    _fake_credwrite(monkeypatch)
    drive_swap.swap_to_server(unc, recording_run, username="alex", password=_SECRET)
    drive_swap.persist_credentials(unc, "alex", _SECRET, recording_run)
    drive_swap.swap_to_local(r"D:\Creators_Club", recording_run)

    flat = " ".join(" ".join(a) for a in spawned)
    assert _SECRET not in flat
    assert "/pass" not in flat
    assert "cmdkey" not in flat        # gone entirely -- CredWriteW now
    assert "/user:" not in flat        # ...and so is net use's credential form
    assert spawned                     # the unmap/loopback steps did run


def test_a_failed_credwrite_is_non_fatal_and_silent_about_the_password(
        monkeypatch, caplog):
    """persist_credentials is a convenience -- the swap already succeeded. A
    CredWriteW that returns FALSE, or one that raises, must both be swallowed
    (and neither may print the blob)."""
    _fake_credwrite(monkeypatch, result=0)
    with caplog.at_level(logging.DEBUG, logger="ccsync.drive_swap"):
        assert drive_swap.persist_credentials(
            "\\\\nas\\Pool\\CC", "alex", _SECRET) is None

    _fake_credwrite(monkeypatch, raises=OSError("advapi32 exploded"))
    with caplog.at_level(logging.DEBUG, logger="ccsync.drive_swap"):
        assert drive_swap.persist_credentials(
            "\\\\nas\\Pool\\CC", "alex", _SECRET) is None

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert _SECRET not in logged
    assert "nas" in logged             # the host, for diagnosis
    assert "OSError" in logged


def test_the_redactor_masks_both_shapes_the_password_arrives_in():
    r = drive_swap._redacted
    assert r(["cmdkey", "/add:nas", "/user:alex", f"/pass:{_SECRET}"]) == \
        "cmdkey /add:nas /user:alex /pass:***"
    assert r(["net", "use", "P:", "\\\\nas\\X", "/user:alex", _SECRET], _SECRET) == \
        "net use P: \\\\nas\\X /user:alex ***"
    # No password given (the uncredentialed swap) -- nothing to mask.
    assert r(["net", "use", "P:", "\\\\nas\\X", "/persistent:no"]) == \
        "net use P: \\\\nas\\X /persistent:no"


def test_a_failing_unmap_logs_a_redacted_argv(monkeypatch, caplog):
    """The remaining shell-outs keep the SYNC-4 discipline: TimeoutExpired's
    str() is the whole argv, and _unmap's failure used to log it with
    exc_info=True."""
    def timing_out(args):
        raise subprocess.TimeoutExpired(cmd=list(args), timeout=30)

    _fake_wnet(monkeypatch)
    with caplog.at_level(logging.DEBUG, logger="ccsync.drive_swap"):
        drive_swap.swap_to_server("\\\\nas\\Pool\\CC", timing_out,
                                  username="alex", password=_SECRET)

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert _SECRET not in logged
    assert "net use P: /delete /y" in logged     # redacted, still diagnosable
    assert "TimeoutExpired" in logged


def test_a_credentialed_timeout_is_not_mistaken_for_an_auth_failure():
    """is_auth_failure() drives the tray's ask-for-your-login retry. The
    redacted message must not accidentally read as one."""
    assert not drive_swap.is_auth_failure("net use failed: TimeoutExpired")
    assert not drive_swap.is_auth_failure(drive_swap._CONNECT_TIMEOUT_MSG)
    assert not drive_swap.is_auth_failure("mapping P: failed: ArgumentError")
