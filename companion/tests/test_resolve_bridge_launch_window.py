"""CR-68: connect() must never touch fusionscript during Resolve's launch
window -- the server is up, Resolve has not registered with it, and a client
connection in that state takes the server down for the session."""

from __future__ import annotations

import logging

import pytest

from ccsync_companion import resolve_bridge, script_server

# conftest's _no_live_resolve replaces resolve_bridge.connect with a stub;
# these tests want the real one, captured at import time.
_real_connect = resolve_bridge.connect


@pytest.fixture
def real_connect(monkeypatch):
    monkeypatch.setattr(resolve_bridge, "connect", _real_connect)
    monkeypatch.setattr(resolve_bridge, "_starting_since", None)
    return _real_connect


def _stop():
    raise RuntimeError("stop here: went past the guard")


def test_connect_holds_off_while_resolve_is_starting(monkeypatch, caplog, real_connect):
    touched = {"env": False}
    monkeypatch.setattr(resolve_bridge, "_ensure_env_and_syspath",
                        lambda: touched.__setitem__("env", True))
    monkeypatch.setattr(script_server, "state", lambda: (script_server.STARTING, "no host yet"))
    with caplog.at_level(logging.INFO, logger="ccsync.resolve"):
        assert real_connect() is None
        assert real_connect() is None
    assert touched["env"] is False
    # One line per window, not one per poll.
    assert sum("holding off" in r.message for r in caplog.records) == 1

    monkeypatch.setattr(script_server, "state", lambda: (script_server.READY, "host"))
    monkeypatch.setattr(resolve_bridge, "_ensure_env_and_syspath", _stop)
    with caplog.at_level(logging.INFO, logger="ccsync.resolve"):
        assert real_connect() is None  # past the guard, into env setup, which we stopped
    assert any("held off for" in r.message for r in caplog.records)


def test_no_server_at_all_holds_off_too(monkeypatch, caplog, real_connect):
    """The 0.9.45 hole: scriptapp() with no server blocks ~4 s retrying, so a
    'just checking' call made before the server appears is the killer."""
    touched = {"env": False}
    monkeypatch.setattr(resolve_bridge, "_ensure_env_and_syspath",
                        lambda: touched.__setitem__("env", True))
    monkeypatch.setattr(script_server, "state", lambda: (script_server.ABSENT, "no listener"))
    with caplog.at_level(logging.INFO, logger="ccsync.resolve"):
        assert real_connect() is None
    assert touched["env"] is False
    # Quiet: Resolve being closed is the normal state for hours.
    assert not any("holding off" in r.message for r in caplog.records)


def test_an_unknown_probe_fails_open(monkeypatch, real_connect):
    """An unreadable table, a foreign process on the port: the old path,
    unchanged."""
    reached = {"env": False}

    def env():
        reached["env"] = True
        _stop()

    monkeypatch.setattr(resolve_bridge, "_ensure_env_and_syspath", env)
    monkeypatch.setattr(script_server, "state", lambda: (script_server.UNKNOWN, "table unreadable"))
    assert real_connect() is None
    assert reached["env"] is True


def test_a_probe_that_raises_fails_open(monkeypatch, real_connect):
    reached = {"env": False}

    def env():
        reached["env"] = True
        _stop()

    def boom():
        raise RuntimeError("table")

    monkeypatch.setattr(resolve_bridge, "_ensure_env_and_syspath", env)
    monkeypatch.setattr(script_server, "state", boom)
    assert real_connect() is None
    assert reached["env"] is True


def test_the_launch_window_is_described_as_starting_not_as_a_dead_server(monkeypatch):
    """Before CR-68 this window produced the NO_SCRIPTING advice -- and
    following that advice (restart everything) was the only cure, because
    the advice-giver was what had broken it."""
    from ccsync_companion import resolve_prefs

    monkeypatch.setattr(resolve_bridge, "_probe_cache", None)
    monkeypatch.setattr(resolve_prefs, "resolve_is_running", lambda: True)
    monkeypatch.setattr(resolve_bridge, "script_server_starting", lambda: True)
    assert resolve_bridge.describe_disconnection() == resolve_bridge.STARTING_MESSAGE
    assert resolve_bridge.is_disconnection_message(resolve_bridge.STARTING_MESSAGE)
    monkeypatch.setattr(resolve_bridge, "script_server_starting", lambda: False)
    monkeypatch.setattr(resolve_bridge, "_no_server_since", None)
    # No server + a Resolve process: launching or shutting down, for a while.
    assert resolve_bridge.describe_disconnection() == resolve_bridge.NO_SERVER_MESSAGE
    assert resolve_bridge.is_disconnection_message(resolve_bridge.NO_SERVER_MESSAGE)
    # ...and only once it has stayed that way is scripting declared dead.
    monkeypatch.setattr(resolve_bridge, "_no_server_since",
                        resolve_bridge.time.monotonic() - resolve_bridge.NO_SERVER_GRACE_SECONDS - 1)
    assert resolve_bridge.describe_disconnection() == resolve_bridge.NO_SCRIPTING_MESSAGE
    # A successful enumeration resets the clock.
    resolve_bridge._explain_disconnection({"ok": True})
    assert resolve_bridge._no_server_since is None
    # Resolve gone entirely resets it too.
    monkeypatch.setattr(resolve_prefs, "resolve_is_running", lambda: False)
    monkeypatch.setattr(resolve_bridge, "_probe_cache", None)
    assert resolve_bridge.describe_disconnection() == resolve_bridge.NOT_RUNNING_MESSAGE


def test_starting_message_has_no_em_dash():
    assert "—" not in resolve_bridge.STARTING_MESSAGE
