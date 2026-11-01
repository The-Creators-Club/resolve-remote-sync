"""resolve_prefs: reading and editing Resolve's two preference files.

The fixtures below are trimmed from REAL files: config.dat and .config.data
off the base rig (no LUT locations) and off an editor's Mac (one already set).
That is where the key names came from, so the tests are anchored to the same
evidence the module is.
"""
from __future__ import annotations

import pytest

from ccsync_companion import resolve_prefs as rp

# Base rig: no LUT locations, gallery on media storage entry 1.
WINDOWS_CONFIG_DAT = """Site.Count = 1

Site.1.FS.Count = 2

Site.1.FS.1.Type = IOFileSys
Site.1.FS.1.Root = G:\\Resolve Media
Site.1.FS.1.MappedRoot =
Site.1.FS.1.DIO = 1

Site.1.FS.2.Type = IOFileSys
Site.1.FS.2.Root = ResolveVirtual
Site.1.FS.2.MappedRoot =
Site.1.FS.2.DIO = 1

Custom.LUT.Path.Count = 0

System.Gallery.DtMgr.Guid = 50
System.Gallery.DtMgr.FileSys = 1
System.Gallery.Folder = .gallery

//Custom settings added by the user
"""

WINDOWS_CONFIG_DATA = """IoFsNum = 1
IoFsMount_1 = G:\\Resolve Media
IoFsMappedMount_1 =
IoFsDirectIO_1 = 1
CustomLutNum = 0
Panels = none
"""

# An editor's Mac: one LUT location already configured, and a mapped mount.
MAC_CONFIG_DAT = """Site.Count = 1

Site.1.FS.Count = 3

Site.1.FS.1.Type = IOFileSys
Site.1.FS.1.Root = /Users/editor1/Movies
Site.1.FS.1.MappedRoot =

Site.1.FS.2.Type = IOFileSys
Site.1.FS.2.Root = /Volumes/EXT-DISK/Creators_Club
Site.1.FS.2.MappedRoot = P:\\

Site.1.FS.3.Type = IOFileSys
Site.1.FS.3.Root = /Volumes
Site.1.FS.3.MappedRoot =

Custom.LUT.Path.Count = 1
Custom.LUT.Path.1 = /Users/editor1/Documents/GR FILM LUTS

System.Gallery.DtMgr.FileSys = 1
System.Gallery.Folder = .gallery
"""

MAC_CONFIG_DATA = """IoFsNum = 2
IoFsMount_1 = /Users/editor1/Movies
IoFsMappedMount_1 =
IoFsMount_2 = /Volumes/EXT-DISK/Creators_Club
IoFsMappedMount_2 = P:\\
CustomLutNum = 1
CustomLutPath_1 = /Users/editor1/Documents/GR FILM LUTS
"""


def _prefs_dir(tmp_path, dat: str, data: str):
    directory = tmp_path / "prefs"
    directory.mkdir()
    (directory / rp.CONFIG_DAT_NAME).write_text(dat, encoding="utf-8")
    (directory / rp.CONFIG_DATA_NAME).write_text(data, encoding="utf-8")
    return directory


@pytest.fixture
def resolve_quit(monkeypatch):
    monkeypatch.setattr(rp, "resolve_is_running", lambda: False)


# -- reading ---------------------------------------------------------------

def test_reads_an_empty_lut_location_list(tmp_path):
    prefs = rp.ResolvePrefs(_prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA))
    assert prefs.lut_locations() == []


def test_reads_an_existing_lut_location(tmp_path):
    prefs = rp.ResolvePrefs(_prefs_dir(tmp_path, MAC_CONFIG_DAT, MAC_CONFIG_DATA))
    assert prefs.lut_locations() == ["/Users/editor1/Documents/GR FILM LUTS"]


def test_gallery_location_resolves_through_the_media_storage_list(tmp_path):
    """The stills path is FS entry <FileSys> + <Folder> -- the indirection
    that makes two machines' stills locations differ."""
    prefs = rp.ResolvePrefs(_prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA))
    gallery = prefs.gallery_location()
    assert gallery["fs_index"] == 1
    assert gallery["root"] == "G:\\Resolve Media"
    assert gallery["path"] == "G:\\Resolve Media\\.gallery"
    # No mapped root on this entry, so nothing to show the shared database.
    assert gallery["mapped_path"] == ""


def test_gallery_mapped_path_uses_the_mapped_root(tmp_path):
    """A machine reaching the tree through a Mapped Mount presents the P:\\
    form to the shared project database -- which is what has to match
    between machines."""
    directory = _prefs_dir(tmp_path, MAC_CONFIG_DAT, MAC_CONFIG_DATA)
    prefs = rp.ResolvePrefs(directory)
    assert prefs.set_gallery_filesys(2, ".gallery") in (rp.OK, rp.RESOLVE_RUNNING)


# -- writing ---------------------------------------------------------------

def test_adds_a_lut_location_to_both_files(tmp_path, resolve_quit):
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    prefs = rp.ResolvePrefs(directory)
    assert prefs.add_lut_location("P:\\Assets\\Luts") == rp.OK

    dat = (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8")
    data = (directory / rp.CONFIG_DATA_NAME).read_text(encoding="utf-8")
    # BOTH files, or Resolve rebuilds config.dat from the GUI form on the
    # next launch and the entry vanishes.
    assert "Custom.LUT.Path.Count = 1" in dat
    assert "Custom.LUT.Path.1 = P:\\Assets\\Luts" in dat
    assert "CustomLutNum = 1" in data
    assert "CustomLutPath_1 = P:\\Assets\\Luts" in data


def test_appends_without_dropping_an_editors_own_location(tmp_path, resolve_quit):
    """The editor had a LUT location of their own. Replacing the list instead of
    appending would silently take away LUTs they are using."""
    directory = _prefs_dir(tmp_path, MAC_CONFIG_DAT, MAC_CONFIG_DATA)
    prefs = rp.ResolvePrefs(directory)
    assert prefs.add_lut_location("/Volumes/EXT-DISK/Creators_Club/Assets/Luts") == rp.OK

    reread = rp.ResolvePrefs(directory)
    assert reread.lut_locations() == [
        "/Users/editor1/Documents/GR FILM LUTS",
        "/Volumes/EXT-DISK/Creators_Club/Assets/Luts",
    ]
    data = (directory / rp.CONFIG_DATA_NAME).read_text(encoding="utf-8")
    assert "CustomLutNum = 2" in data
    assert "CustomLutPath_2 = /Volumes/EXT-DISK/Creators_Club/Assets/Luts" in data


def test_adding_the_same_location_twice_is_a_no_op(tmp_path, resolve_quit):
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    prefs = rp.ResolvePrefs(directory)
    prefs.add_lut_location("P:\\Assets\\Luts")
    before = (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8")

    again = rp.ResolvePrefs(directory)
    assert again.add_lut_location("P:/assets/luts/") == rp.ALREADY
    assert (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8") == before


def test_refuses_to_write_while_resolve_is_running(tmp_path, monkeypatch):
    """The whole point of the guard: Resolve rewrites both files from memory
    on exit, so an edit made now is silently thrown away."""
    monkeypatch.setattr(rp, "resolve_is_running", lambda: True)
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    before = (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8")

    prefs = rp.ResolvePrefs(directory)
    assert prefs.add_lut_location("P:\\Assets\\Luts") == rp.RESOLVE_RUNNING
    assert (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8") == before


def test_refuses_when_the_two_files_disagree(tmp_path, resolve_quit):
    """A count mismatch means something else is editing these files;
    appending to both would leave a different list in each."""
    directory = _prefs_dir(
        tmp_path, MAC_CONFIG_DAT, MAC_CONFIG_DATA.replace("CustomLutNum = 1", "CustomLutNum = 0")
    )
    prefs = rp.ResolvePrefs(directory)
    assert prefs.add_lut_location("/tmp/luts") == rp.FORMAT_UNRECOGNISED


def test_never_creates_config_dat(tmp_path):
    """A missing config.dat means Resolve has never completed a first run,
    and first-run onboarding regenerates the whole config anyway."""
    empty = tmp_path / "prefs"
    empty.mkdir()
    with pytest.raises(rp.PrefsError) as excinfo:
        rp.ResolvePrefs(empty)
    assert excinfo.value.status == rp.CONFIG_MISSING
    assert not (empty / rp.CONFIG_DAT_NAME).exists()


def test_the_edit_is_lossless(tmp_path, resolve_quit):
    """Everything the module does not understand survives: the trailing
    comment, the blank-line grouping, unrelated keys."""
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    rp.ResolvePrefs(directory).add_lut_location("P:\\Assets\\Luts")
    after = (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8")

    assert "//Custom settings added by the user" in after
    assert "Site.1.FS.1.Root = G:\\Resolve Media" in after
    assert "System.Gallery.Folder = .gallery" in after
    # Only the count line changed and one line was added.
    before_lines = WINDOWS_CONFIG_DAT.splitlines()
    after_lines = after.splitlines()
    assert len(after_lines) == len(before_lines) + 1


def test_backs_up_both_files_before_writing(tmp_path, resolve_quit):
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    rp.ResolvePrefs(directory).add_lut_location("P:\\Assets\\Luts", backup_suffix=".bak")
    assert (directory / (rp.CONFIG_DAT_NAME + ".bak")).read_text(
        encoding="utf-8") == WINDOWS_CONFIG_DAT
    assert (directory / (rp.CONFIG_DATA_NAME + ".bak")).read_text(
        encoding="utf-8") == WINDOWS_CONFIG_DATA


def test_resolve_is_running_fails_closed(monkeypatch):
    """An inconclusive check must report True: writing under a running
    Resolve loses the edit, a false positive only defers it."""
    def boom(*args, **kwargs):
        raise OSError("no tasklist here")

    monkeypatch.setattr(rp.subprocess, "run", boom)
    assert rp.resolve_is_running() is True


def test_an_inconclusive_probe_is_None_not_True(monkeypatch):
    """The three-valued answer behind the collapse above. A caller that
    NAGS on "Resolve is running" (app._maybe_warn_scripting_dead) must be
    able to tell a sighting from a failed probe -- given only the fail-closed
    bool, an unspawnable tasklist becomes a warning every 5 minutes, forever,
    on a machine with Resolve shut."""
    def boom(*args, **kwargs):
        raise OSError("no tasklist here")

    monkeypatch.setattr(rp.subprocess, "run", boom)
    assert rp.resolve_process_state() is None


def test_an_unsupported_platform_is_inconclusive_too(monkeypatch):
    monkeypatch.setattr(rp.platform, "system", lambda: "Linux")
    assert rp.resolve_process_state() is None
    assert rp.resolve_is_running() is True


# -- External scripting (CR-373 / GL-29, 2026-10-07) --------------------------

def test_scripting_mode_is_read_from_both_files(tmp_path):
    d = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT + "System.Scripting.Mode = 1\n",
                   WINDOWS_CONFIG_DATA)
    assert rp.ResolvePrefs(d).scripting_mode() == rp.SCRIPTING_LOCAL
    (tmp_path / "b").mkdir()
    d2 = _prefs_dir(tmp_path / "b", WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    assert rp.ResolvePrefs(d2).scripting_mode() is None


def test_ensure_scripting_local_writes_both_files_and_a_backup(tmp_path, resolve_quit):
    d = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    assert rp.ResolvePrefs(d).ensure_scripting_local() == rp.OK
    again = rp.ResolvePrefs(d)
    assert again.dat.get(rp.SCRIPTING_MODE_KEY) == "1"
    assert again.data.get(rp.SCRIPTING_MODE_KEY) == "1"
    assert again.ensure_scripting_local() == rp.ALREADY
    # Lossless: nothing else in the file moved.
    assert "Custom.LUT.Path.Count = 0" in (d / "config.dat").read_text()
    assert any(p.name.startswith("config.dat.ccsync-bak") for p in d.iterdir())


def test_ensure_scripting_local_replaces_an_existing_none(tmp_path, resolve_quit):
    d = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT + "System.Scripting.Mode = 0\n",
                   WINDOWS_CONFIG_DATA + "System.Scripting.Mode = 0\n")
    assert rp.ResolvePrefs(d).ensure_scripting_local() == rp.OK
    assert rp.ResolvePrefs(d).scripting_mode() == rp.SCRIPTING_LOCAL


def test_network_mode_is_left_alone(tmp_path, resolve_quit):
    d = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT + "System.Scripting.Mode = 2\n",
                   WINDOWS_CONFIG_DATA + "System.Scripting.Mode = 2\n")
    assert rp.ResolvePrefs(d).ensure_scripting_local() == rp.ALREADY
    assert rp.ResolvePrefs(d).scripting_mode() == rp.SCRIPTING_NETWORK


def test_ensure_scripting_local_refuses_while_resolve_runs(tmp_path, monkeypatch):
    d = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    monkeypatch.setattr(rp, "resolve_is_running", lambda: True)
    before = (d / "config.dat").read_text()
    assert rp.ResolvePrefs(d).ensure_scripting_local() == rp.RESOLVE_RUNNING
    assert (d / "config.dat").read_text() == before


def test_enable_scripting_never_creates_the_files(tmp_path, monkeypatch):
    monkeypatch.setenv("BMD_RESOLVE_CONFIG_DIR", str(tmp_path / "none"))
    assert rp.enable_scripting() == rp.CONFIG_MISSING
    assert not (tmp_path / "none").exists()
    assert rp.scripting_status()["prefs"] == rp.CONFIG_MISSING


def test_scripting_status_names_the_mode(tmp_path, monkeypatch):
    d = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT + "System.Scripting.Mode = 0\n",
                   WINDOWS_CONFIG_DATA)
    monkeypatch.setenv("BMD_RESOLVE_CONFIG_DIR", str(d))
    st = rp.scripting_status()
    assert st["mode"] == 0 and st["mode_name"] == "None" and st["prefs"] == "ok"


def _no_registry(monkeypatch):
    import sys

    class _Reg:
        HKEY_LOCAL_MACHINE = 0

        @staticmethod
        def OpenKey(*a, **k):
            raise OSError("no key")
    monkeypatch.setitem(sys.modules, "winreg", _Reg)


def test_ensure_scripting_local_needs_both_files(tmp_path, resolve_quit):
    # CR-373 round 2: config.dat alone is NOT CHECKED, never OK.
    d = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, "")
    (d / rp.CONFIG_DATA_NAME).unlink()
    assert rp.ResolvePrefs(d).ensure_scripting_local() == rp.FORMAT_UNRECOGNISED
    assert "System.Scripting.Mode" not in (d / "config.dat").read_text()


def test_ensure_scripting_local_rewrites_disagreeing_files(tmp_path, resolve_quit):
    d = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT + "System.Scripting.Mode = 1\n",
                   WINDOWS_CONFIG_DATA + "System.Scripting.Mode = 0\n")
    assert rp.ResolvePrefs(d).ensure_scripting_local() == rp.OK
    assert rp.ResolvePrefs(d).data.get(rp.SCRIPTING_MODE_KEY) == "1"


def test_detect_resolve_never_claims_an_edition(tmp_path, monkeypatch):
    exe = tmp_path / "Resolve.exe"
    exe.write_bytes(b"x")
    d = tmp_path / "prefs"
    d.mkdir()
    (d / ".version").write_text("Resolve.Version=21.0.0\nOnboarding.Version=16\n")
    monkeypatch.setattr(rp.platform, "system", lambda: "Windows")
    monkeypatch.setenv("CCSYNC_RESOLVE_EXE", str(exe))
    monkeypatch.setenv("BMD_RESOLVE_CONFIG_DIR", str(d))
    monkeypatch.setenv("ProgramData", str(tmp_path / "pd"))
    _no_registry(monkeypatch)
    got = rp.detect_resolve()
    assert got["installed"] is True and got["version"] == "21.0.0"
    assert got["edition"] is None
    monkeypatch.setenv("CCSYNC_RESOLVE_EXE", str(tmp_path / "missing.exe"))
    assert rp.detect_resolve()["installed"] is False


def test_detect_resolve_windows_default_path_present_and_absent(monkeypatch, tmp_path):
    # CR-373 / GL-29 (2026-10-07): a missing constant was swallowed and every
    # Windows seat answered installed=None. No env override here on purpose.
    from ccsync_companion import resolve_prefs as rp
    monkeypatch.setattr(rp.platform, "system", lambda: "Windows")
    monkeypatch.delenv("CCSYNC_RESOLVE_EXE", raising=False)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    _no_registry(monkeypatch)
    assert rp.detect_resolve()["installed"] is False
    exe = tmp_path / "Blackmagic Design" / "DaVinci Resolve" / "Resolve.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")
    got = rp.detect_resolve()
    assert got["installed"] is True and got["path"] == str(exe)
