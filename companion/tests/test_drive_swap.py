"""P: grade-swap tests: target detection/classification and the swap
command sequences, with a scripted run_fn (no real net use / subst)."""

from __future__ import annotations

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
    assert "cmdkey /add:nas" in msg          # actionable credentials hint


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
