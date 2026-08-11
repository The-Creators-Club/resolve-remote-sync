"""P: grade-swap tests: target detection/classification and the swap
command sequences, with a scripted run_fn (no real net use / subst)."""

from __future__ import annotations

import logging
import subprocess

from ccsync_companion import drive_swap


def _proc(rc=0, out="", err=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=out, stderr=err)


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


def test_swap_to_server_sequence_and_auth_hint():
    calls = []
    unc = "\\\\nas\\TheCreatorsPool\\Creators_Club"

    def ok_run(args):
        calls.append(args)
        return _proc(0, "")

    ok, msg = drive_swap.swap_to_server(unc, ok_run)
    assert ok and "SERVER" in msg
    # unmap both styles, then map
    assert calls[0] == ["net", "use", "P:", "/delete", "/y"]
    assert calls[1] == ["subst", "P:", "/D"]
    assert calls[2] == ["net", "use", "P:", unc, "/persistent:no"]

    def denied_run(args):
        if "/persistent:no" in args:
            return _proc(2, "", "System error 5: Access is denied.")
        return _proc(0, "")

    ok, msg = drive_swap.swap_to_server(unc, denied_run)
    assert not ok
    assert drive_swap.is_auth_failure(msg)   # tray reacts by asking for login


def test_is_auth_failure_recognises_console_prompt_cancel():
    # The live 2026-07-26 failure: net use tried to prompt with no console.
    assert drive_swap.is_auth_failure(
        "System error 1223 has occurred. The operation was canceled by the "
        "user. Enter the username for '100.71.216.3':")
    assert drive_swap.is_auth_failure("The user name or password is incorrect.")
    assert not drive_swap.is_auth_failure("System error 53: network path not found")


def test_swap_to_server_with_credentials_and_persist():
    calls = []
    unc = "\\\\nas\\TheCreatorsPool\\Creators_Club"

    def run(args):
        calls.append(args)
        return _proc(0, "")

    ok, _ = drive_swap.swap_to_server(unc, run, username="alex", password="pw")
    assert ok
    assert calls[-1] == ["net", "use", "P:", unc, "/persistent:no", "/user:alex", "pw"]

    calls.clear()
    drive_swap.persist_credentials(unc, "alex", "pw", run)
    assert calls == [["cmdkey", "/add:nas", "/user:alex", "/pass:pw"]]

    # missing host/username -> silently does nothing
    calls.clear()
    drive_swap.persist_credentials("", "alex", "pw", run)
    drive_swap.persist_credentials(unc, "", "pw", run)
    assert calls == []


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


# -- SYNC-4: the editor's TrueNAS password must never leave this module -----

_SECRET = "hunter2-CreatorsClub"


def test_a_timed_out_net_use_never_reports_the_password(caplog):
    """SYNC-4. `net use` takes the password POSITIONALLY, and
    TimeoutExpired.__str__ embeds the whole argv -- app.swap_p_to_server logs
    the returned message at INFO, shows it as a tray balloon and
    copy_diagnostics() sweeps the log tail to the clipboard. An SMB connect to
    a sleeping tailnet host reaches the 30 s timeout routinely."""
    def timing_out(args):
        if "/persistent:no" in args:
            raise subprocess.TimeoutExpired(cmd=list(args), timeout=30)
        return _proc(0, "")

    with caplog.at_level(logging.DEBUG, logger="ccsync.drive_swap"):
        ok, msg = drive_swap.swap_to_server(
            "\\\\nas\\Pool\\Creators_Club", timing_out,
            username="alex", password=_SECRET,
        )

    assert not ok
    assert _SECRET not in msg
    assert "TimeoutExpired" in msg
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert _SECRET not in logged
    # ...but the argv is still there to diagnose with.
    assert "/user:alex" in logged and "***" in logged


def test_a_failed_cmdkey_never_reports_the_password(caplog):
    """The same exposure through the other door: `cmdkey /pass:<password>`
    under log.debug(..., exc_info=True), whose exception line is the argv."""
    def timing_out(args):
        raise subprocess.TimeoutExpired(cmd=list(args), timeout=30)

    with caplog.at_level(logging.DEBUG, logger="ccsync.drive_swap"):
        drive_swap.persist_credentials(
            "\\\\nas\\Pool\\Creators_Club", "alex", _SECRET, timing_out)

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert _SECRET not in logged
    assert "/pass:***" in logged


def test_the_redactor_masks_both_shapes_the_password_arrives_in():
    r = drive_swap._redacted
    assert r(["cmdkey", "/add:nas", "/user:alex", f"/pass:{_SECRET}"]) == \
        "cmdkey /add:nas /user:alex /pass:***"
    assert r(["net", "use", "P:", "\\\\nas\\X", "/user:alex", _SECRET], _SECRET) == \
        "net use P: \\\\nas\\X /user:alex ***"
    # No password given (the uncredentialed swap) -- nothing to mask.
    assert r(["net", "use", "P:", "\\\\nas\\X", "/persistent:no"]) == \
        "net use P: \\\\nas\\X /persistent:no"


def test_a_credentialed_timeout_is_not_mistaken_for_an_auth_failure():
    """is_auth_failure() drives the tray's ask-for-your-login retry. The
    redacted message must not accidentally read as one."""
    assert not drive_swap.is_auth_failure("net use failed: TimeoutExpired")
