"""CR-373 / GL-29 (2026-10-07): the sentence an editor is shown when Resolve
is open but not scriptable depends on whether this computer EVER connected and
on what the 'External scripting using' preference says. "Quit and reopen
Resolve" was the only advice before, and it cannot fix a None preference or a
Free edition."""
from __future__ import annotations

from ccsync_companion import resolve_bridge


def _st(mode, name, prefs="ok"):
    return {"mode": mode, "mode_name": name, "prefs": prefs}


def test_never_connected_with_scripting_none_names_the_preference():
    msg = resolve_bridge.scripting_advice(False, _st(0, "None"))
    assert "External scripting using" in msg and "Local" in msg
    assert "Studio" in msg
    assert "never had a scripting connection" in msg


def test_a_missing_key_counts_as_none():
    msg = resolve_bridge.scripting_advice(False, _st(None, "not set"))
    assert "set to None" in msg


def test_never_connected_with_local_set_points_at_studio():
    msg = resolve_bridge.scripting_advice(False, _st(1, "Local"))
    assert "already Local" in msg and "Studio" in msg
    assert "free" in msg.lower()


def test_unreadable_prefs_still_name_both_causes():
    msg = resolve_bridge.scripting_advice(
        False, _st(None, "unknown", prefs="config-missing"))
    assert "External scripting using" in msg and "Studio" in msg


def test_a_machine_that_connected_before_keeps_the_restart_advice():
    assert resolve_bridge.scripting_advice(True, _st(1, "Local")) == \
        resolve_bridge.NO_SCRIPTING_MESSAGE


def test_session_state_is_the_default_source(monkeypatch):
    resolve_bridge.reset_session_state()
    try:
        monkeypatch.setattr(resolve_bridge.resolve_prefs, "scripting_status",
                            lambda: _st(0, "None"))
        assert "set to None" in resolve_bridge.scripting_advice()
        resolve_bridge.note_connection(True)
        assert resolve_bridge.scripting_advice() == resolve_bridge.NO_SCRIPTING_MESSAGE
    finally:
        resolve_bridge.reset_session_state()


def test_advice_has_no_em_dash_and_never_calls_scriptapp(monkeypatch):
    # CR-68: the advice reads a preference FILE; it must not open the API.
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: (_ for _ in ()).throw(AssertionError("connect")))
    for mode in (0, None, 1):
        assert "—" not in resolve_bridge.scripting_advice(False, _st(mode, "x"))


# -- the install-time CLI writes the preference (CR-373 / GL-29) -------------

class _Mgr:
    def __init__(self, *a, **k):
        pass

    def check(self):
        return {"status": "no-change", "message": "x", "changed": False}


def _run_cli(monkeypatch, scripting_result, capsys):
    from ccsync_companion import app as app_mod
    monkeypatch.setattr(app_mod.config_mod, "load_config", lambda: {})
    monkeypatch.setattr(app_mod, "setup_logging", lambda cfg: None)
    monkeypatch.setattr(app_mod.config_mod, "resolved_local_root", lambda cfg: "")
    monkeypatch.setattr(app_mod.resolve_prefs_mod, "resolve_is_running", lambda: False)
    monkeypatch.setattr(app_mod.resolve_prefs_mod, "enable_scripting",
                        lambda: scripting_result)
    monkeypatch.setattr(app_mod.luts_mod, "LutLinkManager", _Mgr)
    monkeypatch.setattr(app_mod.stills_mod, "StillsManager", _Mgr)
    rc = app_mod.setup_resolve_prefs_cli(["--setup-resolve-prefs"])
    return rc, capsys.readouterr().out


def test_the_install_cli_sets_scripting_and_counts_it(monkeypatch, capsys):
    rc, out = _run_cli(monkeypatch, "ok", capsys)
    # Scripting is reported on its own line and is NOT part of the exit code
    # (windows_bootstrap.ps1 warns on non-zero about LUT/stills).
    assert rc == 1 and "External scripting: set to Local" in out


def test_the_install_cli_says_what_to_do_when_it_could_not(monkeypatch, capsys):
    rc, out = _run_cli(monkeypatch, "config-missing", capsys)
    assert rc == 1
    assert "External scripting using: Local" in out


def test_a_restart_does_not_forget_that_this_machine_connected(monkeypatch):
    # The companion restarts itself after every Resolve quit, so the session
    # flag is False at the next launch; the marker file must carry the fact.
    monkeypatch.setattr(resolve_bridge.resolve_prefs, "scripting_status",
                        lambda: _st(1, "Local"))
    assert "never had a scripting connection" in resolve_bridge.scripting_advice()
    resolve_bridge.note_connection(True)
    resolve_bridge.reset_session_state()   # what a restart looks like
    assert resolve_bridge.session_state()["ever_connected"] is False
    assert resolve_bridge.scripting_advice() == resolve_bridge.NO_SCRIPTING_MESSAGE
