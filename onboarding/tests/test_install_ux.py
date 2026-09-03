"""The wizard's four usability defects from the 2026-09-03 sweep, fixed
2026-09-04: OPS-4 (the install shows nothing while it runs), OPS-5 (the log
dies with the window), OPS-6 (a scheme-less dashboard URL is "not reachable
yet", forever) and OPS-25's two finish-page half-truths.

Everything here is in steps.py rather than onboard.py on purpose: onboard.py
is page layout and wiring, with no automated tests by design (its own module
docstring says so), so anything that decides something lives on this side of
the seam and is checked here. No tkinter, no real child process, no network.
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error

import pytest

import steps


# -- OPS-6: a dashboard URL typed without a scheme -----------------------------
# The admin says "the dashboard is nas.tail26290e.ts.net" and the editor types
# exactly that. urlopen raised ValueError("unknown url type"), swallowed into
# False, so the tailscale page said "wait a few seconds and retry" forever.

@pytest.mark.parametrize("typed,expected", [
    # A tailnet name is served by Tailscale Serve, which is https only.
    ("nas.tail26290e.ts.net", "https://nas.tail26290e.ts.net"),
    ("NAS.tail26290e.ts.net/", "https://NAS.tail26290e.ts.net/"),
    # A LAN address is the container's own port, with no certificate on it.
    ("192.168.0.104:8480", "http://192.168.0.104:8480"),
    ("100.65.15.123", "http://100.65.15.123"),
    ("localhost:8480", "http://localhost:8480"),
    ("nas.local:8480", "http://nas.local:8480"),
    # A name with an explicit non-443 port is somebody's own deployment.
    ("dash.example.com:8480", "http://dash.example.com:8480"),
    ("dash.example.com:443", "https://dash.example.com:443"),
    # Scheme-less but protocol-relative, which a copy-paste can produce.
    ("//nas.tail26290e.ts.net", "https://nas.tail26290e.ts.net"),
])
def test_normalise_dashboard_url_guesses_the_scheme(typed, expected):
    assert steps.normalise_dashboard_url(typed) == expected


@pytest.mark.parametrize("already", [
    "https://nas.tail26290e.ts.net",
    "http://192.168.0.104:8480",
    "http://192.168.0.104:8480/",
])
def test_normalise_dashboard_url_never_touches_a_real_url(already):
    """The editor's own answer beats our guess, and the helper is called on
    every path, so it has to be idempotent."""
    assert steps.normalise_dashboard_url(already) == already
    assert steps.normalise_dashboard_url(steps.normalise_dashboard_url(already)) == already


def test_normalise_dashboard_url_keeps_blank_blank():
    assert steps.normalise_dashboard_url("") == ""
    assert steps.normalise_dashboard_url(None) == ""
    assert steps.normalise_dashboard_url("   ") == ""


def test_dashboard_reachable_accepts_a_bare_hostname():
    """The regression itself: the wizard's gate used to be False for a
    perfectly good address that simply had no scheme in front of it."""
    seen = {}

    def fake_get(url, timeout):
        seen["url"] = url
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"unknown url type: '{url}'")
        return {"ok": True}

    assert steps.dashboard_reachable("nas.tail26290e.ts.net", http_get=fake_get) is True
    assert seen["url"] == "https://nas.tail26290e.ts.net/api/v1/health"


def test_dashboard_probe_tells_a_typo_from_a_slow_tailnet():
    """"that address does not exist" and "nothing answered yet" are different
    problems: one is a wait that never ends. The wizard printed the second for
    both."""
    import socket

    def dns_failure(url, timeout):
        raise urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))

    def refused(url, timeout):
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    def slow(url, timeout):
        raise urllib.error.URLError(TimeoutError("timed out"))

    unknown = steps.dashboard_probe("nas.tial26290e.ts.net", http_get=dns_failure)
    assert unknown["ok"] is False
    assert unknown["kind"] == steps.DASHBOARD_REACH_UNKNOWN_HOST
    assert "does not exist" in unknown["message"]
    # and it names what was tried, scheme included, so the guess is visible
    assert "https://nas.tial26290e.ts.net" in unknown["message"]

    assert steps.dashboard_probe("http://nas:8480", http_get=refused)["kind"] == \
        steps.DASHBOARD_REACH_REFUSED
    assert steps.dashboard_probe("http://nas:8480", http_get=slow)["kind"] == \
        steps.DASHBOARD_REACH_TIMEOUT


def test_dashboard_probe_says_the_address_is_right_on_an_http_error():
    """A 502 is the dashboard's problem, not the editor's, and telling them to
    check the spelling sends them round a loop they cannot win."""
    def http_error(url, timeout):
        raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)

    probe = steps.dashboard_probe("https://nas.ts.net", http_get=http_error)
    assert probe["ok"] is False
    assert probe["kind"] == steps.DASHBOARD_REACH_HTTP
    assert "502" in probe["message"]


def test_verify_account_normalises_before_signing_in():
    """The base-rig path never sees the tailscale page, so this is where a
    scheme-less address used to surface as "unknown url type"."""
    seen = {}

    def fake_post(url, payload, headers, timeout):
        seen["url"] = url
        return {"ok": True, "username": "jsmith", "token": "t"}

    result = steps.verify_account("nas.tail26290e.ts.net", "jsmith", "pw",
                                  http_post=fake_post)
    assert result["ok"] is True
    assert seen["url"] == "https://nas.tail26290e.ts.net/api/v1/verify"


# -- OPS-4: the bootstrap's output, as it happens ------------------------------

def test_run_bootstrap_streams_each_line_and_still_returns_the_aggregate(tmp_path):
    """The whole install used to be captured to a pipe and printed in one block
    at the end: two to thirty minutes of an empty window with both buttons
    disabled. The aggregate still has to come back -- parse_device_id and
    bootstrap_capability_warnings read it after the fact."""
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    lines = []
    output = "[ccsync] step one\n[ccsync] step two\n"

    def fake_run(cmd, **kwargs):
        on_line = kwargs.get("on_line")
        assert on_line is not None, "run_bootstrap did not pass the sink through"
        for line in output.splitlines():
            on_line(line)

        class _R:
            returncode = 0
            stdout = output
            stderr = ""
        return _R()

    exit_code, aggregate = steps.run_bootstrap(
        editor_name="jsmith", dashboard_token="x", tailnet_host="h",
        run=fake_run, script_path=script, platform="win32",
        on_line=lines.append,
    )
    assert exit_code == 0
    assert lines == ["[ccsync] step one", "[ccsync] step two"]
    assert "step two" in aggregate


def test_run_bootstrap_without_a_sink_keeps_the_old_signature(tmp_path):
    """Every injected runner in this suite takes (cmd, **kwargs); on_line must
    not appear when nobody asked for streaming, or a hand-rolled runner with a
    strict signature breaks on a machine, not in a test."""
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()

    steps.run_bootstrap(editor_name="jsmith", dashboard_token="x", tailnet_host="h",
                        run=fake_run, script_path=script, platform="win32")
    assert "on_line" not in captured


def test_run_bootstrap_timeout_tells_a_streamed_caller_what_happened(tmp_path):
    """The partial output has already been shown line by line, so only the
    verdict is news -- but it must be said, or the log simply stops."""
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    lines = []

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"),
                                        output="half an install", stderr="")

    exit_code, output = steps.run_bootstrap(
        editor_name="jsmith", dashboard_token="x", tailnet_host="h",
        run=fake_run, script_path=script, platform="win32", on_line=lines.append,
    )
    assert exit_code != 0
    assert any("timed out" in line for line in lines)
    # and the returned text still carries everything, for the capability scan
    assert "half an install" in output and "timed out" in output


def test_default_bootstrap_run_reads_a_real_child_line_by_line():
    """The default runner, against a real process: the lines must arrive
    BEFORE it exits, which is the entire point (a fake runner cannot prove
    it)."""
    seen = []
    arrival = []
    code = (
        "import time\n"
        "print('first', flush=True)\n"
        "time.sleep(0.6)\n"
        "print('second', flush=True)\n"
    )

    def sink(line):
        seen.append(line)
        arrival.append(time.monotonic())

    started = time.monotonic()
    result = steps.default_bootstrap_run(
        [sys.executable, "-c", code], timeout=60, env=None, on_line=sink,
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0
    assert seen == ["first", "second"]
    assert "first" in result.stdout and "second" in result.stdout
    # "first" arrived while the child was still sleeping, i.e. before it
    # exited. That is the whole fix: communicate() could only ever hand the
    # wizard both lines at once, at the end.
    assert arrival[0] - started < 0.5
    assert arrival[1] - arrival[0] > 0.3


def test_default_bootstrap_run_merges_stderr_into_the_stream():
    """The bootstrap's warnings go to stderr, and a warning shown somewhere
    other than under the step that produced it is worse than no warning."""
    seen = []
    code = (
        "import sys\n"
        "print('step', flush=True)\n"
        "print('WARNING: something', file=sys.stderr, flush=True)\n"
    )
    steps.default_bootstrap_run([sys.executable, "-c", code], timeout=60, env=None,
                                on_line=seen.append, encoding="utf-8", errors="replace")
    assert "step" in seen
    assert any("WARNING" in line for line in seen)


# -- OPS-5: the install log on disk --------------------------------------------

def test_install_log_is_written_as_it_goes(tmp_path, monkeypatch):
    """A frozen windowed build has no stderr and the log widget dies with the
    window: on failure the editor was told "send them this list" with no file,
    no path and no copy button."""
    path = steps.start_install_log(home=tmp_path, now="20260904-101500")
    try:
        assert path is not None
        assert path == tmp_path / ".ccsync" / "logs" / "onboard-20260904-101500.log"
        assert steps.install_log_path() == path

        steps.append_install_log("clean slate done.")
        steps.append_install_log("running bootstrap\n")
        # On disk NOW, not at the end: the interesting failures are the ones
        # that take the process with them.
        on_disk = path.read_text(encoding="utf-8")
        assert on_disk == "clean slate done.\nrunning bootstrap\n"
        assert steps.read_install_log() == on_disk
    finally:
        steps._install_log_path = None


def test_the_wizard_installs_when_the_log_cannot_be_opened(tmp_path):
    """Never fatal: a home directory that will not take the file must not stop
    an install, and every caller has to get a usable answer."""
    blocker = tmp_path / ".ccsync"
    blocker.write_text("not a directory")
    assert steps.start_install_log(home=tmp_path) is None
    assert steps.install_log_path() is None
    steps.append_install_log("this must not raise")
    assert steps.read_install_log() == ""


# -- OPS-25: the finish page's two half-truths ---------------------------------

def test_finish_warning_lines_says_when_it_truncated():
    warnings = [f"warning {n}" for n in range(1, 8)]
    lines = steps.finish_warning_lines(warnings)
    assert lines[:6] == warnings[:6]
    assert len(lines) == 7
    assert "and 1 more" in lines[-1]
    # The heading counts all seven, so the list may not silently show six.
    assert "warning 7" not in " ".join(lines[:6])


def test_finish_warning_lines_adds_nothing_when_everything_fits():
    warnings = ["a", "b"]
    assert steps.finish_warning_lines(warnings) == warnings
    assert steps.finish_warning_lines([]) == []


def test_finish_copy_field_refuses_to_copy_a_placeholder():
    """[ COPY ] used to put "(not found automatically ...)" on the clipboard,
    from where it was pasted into the message to the admin as if it were an
    ID."""
    text, copyable = steps.finish_copy_field(None, "(not found automatically)")
    assert text == "(not found automatically)"
    assert copyable is False

    text, copyable = steps.finish_copy_field("  DEVICE-ID-1234  ", "(not found)")
    assert text == "DEVICE-ID-1234"
    assert copyable is True
