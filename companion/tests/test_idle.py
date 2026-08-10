"""idle.py tests: "cannot tell" must always come out as None.

The factory is exercised from any host with the conftest `windows`/`darwin`
fixtures, and neither ctypes nor ioreg is ever executed there -- construction
is deliberately side-effect free, and the backends take injectable seams
(root_guard.py's run_fn style) so their arithmetic and parsing are testable
off-platform.
"""

from __future__ import annotations

import sys

import pytest

from ccsync_companion import idle


# -- the factory ---------------------------------------------------------------


def test_disabled_gets_the_inert_base():
    """Inert means "cannot tell" means "never idle" -- switching idle
    detection off switches idle-gated work off with it."""
    probe = idle.make_idle_probe(enabled=False)
    assert type(probe) is idle.IdleProbe
    assert probe.seconds_idle() is None


def test_windows_gets_the_windows_probe(windows):
    assert isinstance(idle.make_idle_probe(), idle._WindowsIdleProbe)


def test_macos_gets_the_darwin_probe(darwin):
    assert isinstance(idle.make_idle_probe(), idle._DarwinIdleProbe)


def test_disabled_wins_on_every_platform(windows):
    assert type(idle.make_idle_probe(enabled=False)) is idle.IdleProbe


def test_an_unsupported_platform_gets_the_inert_base(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert type(idle.make_idle_probe()) is idle.IdleProbe


def test_the_base_answers_none_forever():
    assert idle.IdleProbe().seconds_idle() is None


# -- Windows: the 32-bit tick arithmetic ---------------------------------------


def test_elapsed_ms_across_the_wrap():
    """GetTickCount rolls over every 49.7 days. A plain subtraction here
    answers -4294966796 ms, i.e. "not idle at all" on one side of the wrap
    and "idle for seven weeks" on the other."""
    assert idle._elapsed_ms(500, 2 ** 32 - 1000) == 1500


def test_elapsed_ms_in_the_normal_case():
    assert idle._elapsed_ms(300_000, 60_000) == 240_000
    assert idle._elapsed_ms(1000, 1000) == 0


def test_the_windows_probe_reports_seconds(windows):
    probe = idle._WindowsIdleProbe(
        tick_fn=lambda: 300_000, last_input_fn=lambda: 60_000
    )
    assert probe.seconds_idle() == pytest.approx(240.0)


def test_the_windows_probe_wraps_safely(windows):
    probe = idle._WindowsIdleProbe(
        tick_fn=lambda: 500, last_input_fn=lambda: 2 ** 32 - 1000
    )
    assert probe.seconds_idle() == pytest.approx(1.5)


def test_a_failed_getlastinputinfo_is_none(windows):
    """The API returning FALSE (a locked session, a hostile hook) is
    cannot-tell, not zero seconds idle."""
    probe = idle._WindowsIdleProbe(tick_fn=lambda: 300_000, last_input_fn=lambda: None)
    assert probe.seconds_idle() is None


def test_a_raising_windows_backend_is_none(windows):
    def boom():
        raise OSError("user32 went away")

    assert idle._WindowsIdleProbe(tick_fn=lambda: 1, last_input_fn=boom).seconds_idle() is None
    assert idle._WindowsIdleProbe(tick_fn=boom, last_input_fn=lambda: 1).seconds_idle() is None


def test_a_windows_probe_that_cannot_bind_is_none(monkeypatch):
    """No ctypes (or no user32) is not an error anywhere -- it just means no
    proxy generation on this machine.

    None in sys.modules makes the `import ctypes` inside _bind raise, which
    is the only way to reach that branch from a host that HAS a working
    ctypes (patching sys.platform would not: WinDLL is still right there).
    """
    monkeypatch.setitem(sys.modules, "ctypes", None)
    probe = idle._WindowsIdleProbe()
    assert probe.seconds_idle() is None
    assert probe._bind_failed is True
    # ...and it does not retry the import on every 15 s tick.
    assert probe.seconds_idle() is None


@pytest.mark.skipif(sys.platform != "win32", reason="needs real Win32 APIs")
def test_the_real_windows_probe_answers_a_number():
    """The ctypes half, which no injected fake can prove: GetLastInputInfo
    and GetTickCount actually binding and returning a sane pair."""
    seconds = idle.make_idle_probe().seconds_idle()
    assert seconds is not None
    # 49.7 days would mean the wrap arithmetic went wrong.
    assert 0.0 <= seconds < 49.0 * 24 * 3600


# -- macOS: the ioreg parser ----------------------------------------------------

# Trimmed from a real `ioreg -c IOHIDSystem -d 1 -w 0` dump.
IOREG_SAMPLE = """
+-o IOHIDSystem  <class IOHIDSystem, id 0x100000282, registered, matched, active, busy 0 (0 ms), retain 9>
    {
      "IOClass" = "IOHIDSystem"
      "IOProviderClass" = "IOResources"
      "HIDIdleTime" = 12300000000
      "IOMatchCategory" = "IOHIDSystem"
    }
"""


def test_the_ioreg_parser_reads_nanoseconds():
    assert idle.parse_hid_idle_seconds(IOREG_SAMPLE) == pytest.approx(12.3)


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "not ioreg output at all",
        '"HIDIdleTime" = ',            # truncated
        '"HIDIdleTime" = <not a number>',
        b"\x00\x01binary junk",
    ],
)
def test_the_ioreg_parser_gives_up_quietly(text):
    assert idle.parse_hid_idle_seconds(text) is None


def test_the_darwin_probe_runs_ioreg_and_parses_it(darwin):
    calls = []

    def run_fn(argv, timeout=None):
        calls.append((list(argv), timeout))
        return IOREG_SAMPLE

    assert idle._DarwinIdleProbe(run_fn=run_fn).seconds_idle() == pytest.approx(12.3)
    argv, timeout = calls[0]
    assert argv == ["/usr/sbin/ioreg", "-c", "IOHIDSystem", "-d", "1", "-w", "0"]
    assert timeout == idle.IOREG_TIMEOUT_SECONDS


def test_a_failed_ioreg_is_none(darwin):
    """A missing binary, a non-zero exit and a timeout all arrive here as
    None -- and stay None rather than becoming "idle"."""
    assert idle._DarwinIdleProbe(run_fn=lambda *_a, **_k: None).seconds_idle() is None


def test_a_raising_ioreg_is_none(darwin):
    def boom(*_args, **_kwargs):
        raise RuntimeError("no such process")

    assert idle._DarwinIdleProbe(run_fn=boom).seconds_idle() is None


def test_garbage_from_ioreg_is_none(darwin):
    probe = idle._DarwinIdleProbe(run_fn=lambda *_a, **_k: "kernel panic, sorry")
    assert probe.seconds_idle() is None


def test_default_ioreg_run_survives_a_missing_binary():
    """The real subprocess path, aimed at something that does not exist --
    the one failure every non-macOS host can exercise."""
    assert idle.default_ioreg_run(["/nonexistent/ccsync-test-ioreg"], timeout=5) is None
