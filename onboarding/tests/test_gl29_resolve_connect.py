"""CR-373 / GL-29 (2026-10-07): the wizard no longer says DONE and leaves the
Resolve half to a scrolling log box. It writes the scripting preference while
Resolve is closed and both finish pages carry a connect-Resolve checklist."""
from __future__ import annotations

import pytest

import steps
from ccsync_companion import resolve_prefs as rp

DAT = "Site.Count = 1\n\nCustom.LUT.Path.Count = 0\n"
DATA = "CustomLutNum = 0\nPanels = none\n"


@pytest.fixture
def prefs_dir(tmp_path, monkeypatch):
    d = tmp_path / "prefs"
    d.mkdir()
    (d / "config.dat").write_text(DAT)
    (d / ".config.data").write_text(DATA)
    monkeypatch.setenv("BMD_RESOLVE_CONFIG_DIR", str(d))
    exe = tmp_path / "Resolve.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(rp.platform, "system", lambda: "Windows")
    monkeypatch.setenv("CCSYNC_RESOLVE_EXE", str(exe))
    return d


def test_the_install_switches_scripting_on_when_resolve_is_closed(prefs_dir, monkeypatch):
    monkeypatch.setattr(rp, "resolve_is_running", lambda: False)
    got = steps.enable_resolve_scripting()
    assert got["status"] == rp.OK and got["note"] is None
    assert rp.ResolvePrefs(prefs_dir).scripting_mode() == rp.SCRIPTING_LOCAL


def test_an_open_resolve_is_left_alone_and_the_page_says_what_to_do(prefs_dir, monkeypatch):
    monkeypatch.setattr(rp, "resolve_is_running", lambda: True)
    before = (prefs_dir / "config.dat").read_text()
    got = steps.enable_resolve_scripting()
    assert got["status"] == rp.RESOLVE_RUNNING
    assert "External scripting using" in got["note"] and "Local" in got["note"]
    assert (prefs_dir / "config.dat").read_text() == before


@pytest.fixture
def no_registry(monkeypatch):
    class _Reg:
        HKEY_LOCAL_MACHINE = 0

        @staticmethod
        def OpenKey(*a, **k):
            raise OSError("no key")
    monkeypatch.setitem(__import__("sys").modules, "winreg", _Reg)


def test_no_resolve_found_and_never_run_names_the_studio_requirement(
        monkeypatch, tmp_path, no_registry):
    monkeypatch.setenv("BMD_RESOLVE_CONFIG_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(rp.platform, "system", lambda: "Windows")
    monkeypatch.setenv("CCSYNC_RESOLVE_EXE", str(tmp_path / "gone.exe"))
    got = steps.enable_resolve_scripting()
    assert got["installed"] is False and got["status"] == "skipped"
    assert "Studio" in got["note"] and "free edition" in got["note"]
    assert "not installed" not in got["note"]


def test_exe_not_at_the_usual_place_does_not_block_the_write_when_prefs_exist(
        prefs_dir, monkeypatch, tmp_path, no_registry):
    """CR-373 round 2: a custom install path must not leave scripting off."""
    monkeypatch.setattr(rp, "resolve_is_running", lambda: False)
    monkeypatch.setenv("CCSYNC_RESOLVE_EXE", str(tmp_path / "gone.exe"))
    got = steps.enable_resolve_scripting()
    assert got["status"] == rp.OK
    assert rp.ResolvePrefs(prefs_dir).scripting_mode() == rp.SCRIPTING_LOCAL


def test_a_studio_licence_is_a_positive_sighting(monkeypatch, tmp_path, no_registry):
    lic = tmp_path / "pd" / "Blackmagic Design" / "DaVinci Resolve" / "Support" / ".license"
    lic.mkdir(parents=True)
    monkeypatch.setenv("ProgramData", str(tmp_path / "pd"))
    monkeypatch.setattr(rp.platform, "system", lambda: "Windows")
    monkeypatch.setenv("CCSYNC_RESOLVE_EXE", str(tmp_path / "gone.exe"))
    assert rp.detect_resolve()["edition"] is None
    (lic / ".davinciresolvestudio_14.0.lic").write_text("x")
    assert rp.detect_resolve()["edition"] == "studio"


def test_scripting_is_not_reported_on_without_both_preference_files(
        prefs_dir, monkeypatch):
    monkeypatch.setattr(rp, "resolve_is_running", lambda: False)
    (prefs_dir / ".config.data").unlink()
    got = steps.enable_resolve_scripting()
    assert got["status"] == rp.FORMAT_UNRECOGNISED and got["note"]
    # Disagreeing files are rewritten, not ALREADY.
    (prefs_dir / ".config.data").write_text(DATA + "System.Scripting.Mode = 0\n")
    (prefs_dir / "config.dat").write_text(DAT + "System.Scripting.Mode = 1\n")
    assert rp.enable_scripting() == rp.OK
    assert rp.ResolvePrefs(prefs_dir).data.get(rp.SCRIPTING_MODE_KEY) == "1"


def test_never_raises_without_a_prefs_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("BMD_RESOLVE_CONFIG_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(rp.platform, "system", lambda: "Windows")
    monkeypatch.setenv("CCSYNC_RESOLVE_EXE", str(tmp_path / "x.exe"))
    (tmp_path / "x.exe").write_bytes(b"x")
    got = steps.enable_resolve_scripting()
    assert got["status"] == rp.CONFIG_MISSING
    assert "first launch" in got["note"]


def test_checklist_carries_the_manifest_host():
    lines = steps.resolve_finish_lines(
        {"sftp_host": "nas.example.ts.net"}, "https://dash.example/",
        {"status": rp.OK, "note": None})
    text = "\n".join(lines)
    assert "Host: nas.example.ts.net" in text
    assert "already set to Local" in text
    assert "Studio" in lines[0]


def test_host_falls_back_to_the_dashboard_url_then_to_the_admin():
    assert steps.resolve_library_host({}, "http://100.1.2.3:8080") == "100.1.2.3"
    lines = steps.resolve_finish_lines({}, "", None)
    assert "Host: ask your admin" in "\n".join(lines)


def test_checklist_repeats_the_manual_step_when_the_install_could_not_do_it():
    lines = steps.resolve_finish_lines(
        {"sftp_host": "h"}, "", {"status": rp.RESOLVE_RUNNING, "note": "QUIT FIRST"})
    joined = "\n".join(lines)
    assert "External scripting using: Local" in joined and "QUIT FIRST" in joined


def test_no_em_dash_in_the_new_copy():
    texts = steps.resolve_finish_lines({"sftp_host": "h"}, "", None)
    texts += [v for v in steps._SCRIPTING_NOTES.values() if v]
    texts.append(steps._SCRIPTING_NOTE_DEFAULT)
    assert all("—" not in t for t in texts)
