"""stills: putting every machine's Resolve gallery in the same place.

The gallery directory is <media storage entry [FileSys]>/<Folder>, so this
is really a test of inserting a media storage entry correctly -- the
delicate part, because entry 1 is the scratch disk that render caching
points at by index, and Resolve expects its own trailing entry last.
"""
from __future__ import annotations

import pytest

from ccsync_companion import resolve_prefs as rp
from ccsync_companion import stills

from test_resolve_prefs import (
    MAC_CONFIG_DAT, MAC_CONFIG_DATA, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA,
)


def _prefs_dir(tmp_path, dat, data):
    directory = tmp_path / "prefs"
    directory.mkdir()
    (directory / rp.CONFIG_DAT_NAME).write_text(dat, encoding="utf-8")
    (directory / rp.CONFIG_DATA_NAME).write_text(data, encoding="utf-8")
    return directory


@pytest.fixture
def resolve_quit(monkeypatch):
    monkeypatch.setattr(rp, "resolve_is_running", lambda: False)


# -- what each platform should end up with ---------------------------------

def test_windows_uses_the_canonical_path_with_no_mapping(tmp_path):
    """P: IS the real path on Windows -- adding a MappedRoot would map a
    drive onto itself."""
    root, mapped = stills.desired_entry({"canonical_prefix": "P:\\"}, tmp_path, windows=True)
    assert root == "P:\\Assets\\Stills"
    assert mapped == ""


def test_mac_maps_the_real_path_to_the_canonical_one(tmp_path):
    """The shared project database has to see the same P:\\ string from
    every machine -- that is the whole point."""
    root, mapped = stills.desired_entry({"canonical_prefix": "P:\\"}, tmp_path, windows=False)
    assert root == str(tmp_path / "Assets" / "Stills")
    assert mapped == "P:\\Assets\\Stills"


# -- media storage insertion -----------------------------------------------

def test_appends_in_front_of_resolves_own_trailing_entry(tmp_path, resolve_quit):
    """Resolve expects ResolveVirtual (Windows) / /Volumes (macOS) last."""
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    prefs = rp.ResolvePrefs(directory)
    status, index = prefs.ensure_media_storage("P:\\Assets\\Stills")

    assert status == rp.OK
    entries = rp.ResolvePrefs(directory).media_storage()
    assert [e["root"] for e in entries] == [
        "G:\\Resolve Media", "P:\\Assets\\Stills", "ResolveVirtual",
    ]
    assert index == 2


def test_never_touches_entry_one(tmp_path, resolve_quit):
    """Entry 1 is the scratch disk, and RenderCaching.FsNo points at it by
    index -- moving it would silently relocate the render cache."""
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    rp.ResolvePrefs(directory).ensure_media_storage("P:\\Assets\\Stills")
    after = rp.ResolvePrefs(directory).media_storage()
    assert after[0]["index"] == 1
    assert after[0]["root"] == "G:\\Resolve Media"


def test_writes_the_mapped_root_into_both_files(tmp_path, resolve_quit):
    directory = _prefs_dir(tmp_path, MAC_CONFIG_DAT, MAC_CONFIG_DATA)
    rp.ResolvePrefs(directory).ensure_media_storage(
        "/Volumes/SAMDISK/Creators_Club/Assets/Stills", "P:\\Assets\\Stills"
    )
    dat = (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8")
    data = (directory / rp.CONFIG_DATA_NAME).read_text(encoding="utf-8")
    assert "/Volumes/SAMDISK/Creators_Club/Assets/Stills" in dat
    assert "/Volumes/SAMDISK/Creators_Club/Assets/Stills" in data
    # The GUI form must carry the mapping too, or Resolve rebuilds
    # config.dat from it on the next launch and the mapping is lost.
    assert "IoFsMappedMount_3 = P:\\Assets\\Stills" in data


def test_mac_insertion_keeps_volumes_last(tmp_path, resolve_quit):
    directory = _prefs_dir(tmp_path, MAC_CONFIG_DAT, MAC_CONFIG_DATA)
    rp.ResolvePrefs(directory).ensure_media_storage(
        "/Volumes/SAMDISK/Creators_Club/Assets/Stills", "P:\\Assets\\Stills"
    )
    roots = [e["root"] for e in rp.ResolvePrefs(directory).media_storage()]
    assert roots[-1] == "/Volumes"
    assert roots == [
        "/Users/leso/Movies",
        "/Volumes/SAMDISK/Creators_Club",
        "/Volumes/SAMDISK/Creators_Club/Assets/Stills",
        "/Volumes",
    ]


def test_adding_an_existing_entry_is_a_no_op(tmp_path, resolve_quit):
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    rp.ResolvePrefs(directory).ensure_media_storage("P:\\Assets\\Stills")
    before = (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8")

    status, index = rp.ResolvePrefs(directory).ensure_media_storage("P:\\Assets\\Stills")
    assert status == rp.ALREADY and index == 2
    assert (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8") == before


# -- the manager -----------------------------------------------------------

def _manager(tmp_path, directory, make_dir=True):
    if make_dir:
        (tmp_path / "root" / "Assets" / "Stills").mkdir(parents=True)
    return stills.StillsManager(
        {"canonical_prefix": "P:\\"},
        tmp_path / "root",
        prefs_factory=lambda: rp.ResolvePrefs(directory),
    )


def test_points_the_gallery_at_the_shared_folder(tmp_path, resolve_quit):
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    result = _manager(tmp_path, directory).check()

    assert result["changed"] is True
    gallery = rp.ResolvePrefs(directory).gallery_location()
    assert gallery["root"] == "P:\\Assets\\Stills"
    assert gallery["path"] == "P:\\Assets\\Stills\\.gallery"


def test_waits_until_the_shared_folder_has_synced(tmp_path, resolve_quit):
    """Repointing the gallery at a directory that isn't there would take an
    editor's stills offline -- worse than the mismatch warning."""
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    before = (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8")

    result = _manager(tmp_path, directory, make_dir=False).check()
    assert result["status"] == "no-library"
    assert (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8") == before


def test_is_a_no_op_once_the_gallery_is_already_shared(tmp_path, resolve_quit):
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    manager = _manager(tmp_path, directory)
    manager.check()
    before = (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8")

    assert manager.check()["changed"] is False
    assert (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8") == before


def test_defers_while_resolve_is_running(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "resolve_is_running", lambda: True)
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    before = (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8")

    result = _manager(tmp_path, directory).check()
    assert result["status"] == rp.RESOLVE_RUNNING
    assert "closed" in result["message"]
    assert (directory / rp.CONFIG_DAT_NAME).read_text(encoding="utf-8") == before


def test_disabled_does_nothing(tmp_path, resolve_quit):
    directory = _prefs_dir(tmp_path, WINDOWS_CONFIG_DAT, WINDOWS_CONFIG_DATA)
    (tmp_path / "root" / "Assets" / "Stills").mkdir(parents=True)
    manager = stills.StillsManager(
        {"stills_sync_enabled": False}, tmp_path / "root",
        prefs_factory=lambda: rp.ResolvePrefs(directory),
    )
    assert manager.check()["status"] == "disabled"
