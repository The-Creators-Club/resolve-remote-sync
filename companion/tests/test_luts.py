"""luts: registering the shared library with Resolve, and finding strays."""
from __future__ import annotations

from pathlib import Path

import pytest

from ccsync_companion import luts
from ccsync_companion import resolve_prefs as rp


class FakePrefs:
    """A ResolvePrefs stand-in. Tracks what was asked of it."""

    def __init__(self, existing=None, add_result=rp.OK):
        self.locations = list(existing or [])
        self.add_result = add_result
        self.added: list[str] = []

    def has_lut_location(self, path):
        want = path.replace("\\", "/").rstrip("/").lower()
        return any(p.replace("\\", "/").rstrip("/").lower() == want for p in self.locations)

    def add_lut_location(self, path, backup_suffix=""):
        self.added.append(path)
        if self.add_result == rp.OK:
            self.locations.append(path)
        return self.add_result

    def lut_locations(self):
        return list(self.locations)


def _library(tmp_path: Path) -> Path:
    library = tmp_path / "root" / "Assets" / "Luts"
    library.mkdir(parents=True)
    return library


def _manager(tmp_path, prefs=None, cfg=None):
    return luts.LutLinkManager(
        cfg if cfg is not None else {},
        tmp_path / "root",
        prefs_factory=lambda: prefs or FakePrefs(),
        refresh_fn=lambda: True,
    )


# -- the location string ---------------------------------------------------

def test_windows_uses_the_canonical_prefix(tmp_path):
    """Every Windows editor writes the SAME string, which is what makes a
    LUT applied on one machine resolvable on the next."""
    assert luts.library_location_string(
        {"canonical_prefix": "P:\\"}, tmp_path, windows=True
    ) == "P:\\Assets\\Luts"


def test_non_windows_uses_the_real_local_path(tmp_path):
    """A Mac has no P: -- the Mapped Mount preference covers media paths,
    not this one."""
    result = luts.library_location_string(
        {"canonical_prefix": "P:\\"}, tmp_path, windows=False
    )
    assert result == str(tmp_path / "Assets" / "Luts")


def test_override_wins(tmp_path):
    assert luts.library_location_string(
        {"canonical_prefix": "P:\\", "lut_location_override": "Q:\\Luts"},
        tmp_path, windows=True,
    ) == "Q:\\Luts"


# -- check() ---------------------------------------------------------------

def test_adds_the_location_when_the_library_exists(tmp_path):
    _library(tmp_path)
    prefs = FakePrefs()
    result = _manager(tmp_path, prefs).check()
    assert result["changed"] is True
    assert len(prefs.added) == 1


def test_waits_for_the_library_to_sync(tmp_path):
    """Pointing Resolve at a directory that is not there yet is worse than
    waiting: the entry would sit in the UI resolving to nothing."""
    prefs = FakePrefs()
    result = _manager(tmp_path, prefs).check()   # no library on disk
    assert result["status"] == "no-library"
    assert prefs.added == []


def test_is_a_no_op_once_the_location_is_present(tmp_path):
    _library(tmp_path)
    prefs = FakePrefs(existing=["P:\\Assets\\Luts"])
    manager = luts.LutLinkManager(
        {"canonical_prefix": "P:\\", "lut_location_override": "P:\\Assets\\Luts"},
        tmp_path / "root",
        prefs_factory=lambda: prefs,
    )
    result = manager.check()
    assert result["changed"] is False
    assert prefs.added == []


def test_reports_resolve_running_without_failing(tmp_path):
    _library(tmp_path)
    prefs = FakePrefs(add_result=rp.RESOLVE_RUNNING)
    result = _manager(tmp_path, prefs).check()
    assert result["status"] == rp.RESOLVE_RUNNING
    assert result["changed"] is False
    assert "closed" in result["message"]


def test_disabled_does_nothing(tmp_path):
    _library(tmp_path)
    prefs = FakePrefs()
    manager = _manager(tmp_path, prefs, cfg={"lut_sync_enabled": False})
    assert manager.check()["status"] == "disabled"
    assert prefs.added == []


# -- strays ----------------------------------------------------------------

def test_finds_a_lut_the_library_does_not_have(tmp_path):
    library = _library(tmp_path)
    (library / "Ruskin").mkdir()
    (library / "Ruskin" / "shared.cube").write_text("x" * 10)

    lut_dir = tmp_path / "resolve-lut"
    lut_dir.mkdir()
    (lut_dir / "mine.cube").write_text("y" * 20)

    found = luts.stray_luts([lut_dir], library)
    assert [f["name"] for f in found] == ["mine.cube"]


def test_matches_by_basename_so_a_regrouped_lut_is_not_offered_again(tmp_path):
    """The library keeps LUTs in pack folders; an editor's copy is often
    loose. Same name and size means same LUT -- prompting forever would be
    noise."""
    library = _library(tmp_path)
    (library / "Ruskin").mkdir()
    (library / "Ruskin" / "CC Base.cube").write_text("x" * 10)

    lut_dir = tmp_path / "resolve-lut"
    lut_dir.mkdir()
    (lut_dir / "CC Base.cube").write_text("x" * 10)

    assert luts.stray_luts([lut_dir], library) == []


def test_ignores_non_lut_files_and_dctls(tmp_path):
    """.dctl is excluded deliberately: Resolve loads DCTLs only from its own
    LUT/DCTL directory, never from an additional LUT location, so copying one
    into the library puts it where Resolve does not look."""
    library = _library(tmp_path)
    lut_dir = tmp_path / "resolve-lut"
    (lut_dir / "DCTL").mkdir(parents=True)
    (lut_dir / "DCTL" / "thing.dctl").write_text("code")
    (lut_dir / "readme.txt").write_text("hi")

    assert luts.stray_luts([lut_dir], library) == []


def test_never_offers_the_library_back_to_itself(tmp_path):
    library = _library(tmp_path)
    (library / "a.cube").write_text("x")
    assert luts.stray_luts([library], library) == []


def test_copy_into_library_preserves_the_pack_folder(tmp_path):
    library = _library(tmp_path)
    lut_dir = tmp_path / "resolve-lut"
    (lut_dir / "GR FILM").mkdir(parents=True)
    (lut_dir / "GR FILM" / "one.cube").write_text("data")

    entries = luts.stray_luts([lut_dir], library)
    result = luts.copy_into_library(entries, library)

    assert result["copied"] == 1
    assert (library / "GR FILM" / "one.cube").read_text() == "data"
    # The editor's own copy is untouched -- Resolve already knows about it.
    assert (lut_dir / "GR FILM" / "one.cube").exists()


def test_copy_never_overwrites(tmp_path):
    library = _library(tmp_path)
    (library / "one.cube").write_text("library version")
    lut_dir = tmp_path / "resolve-lut"
    lut_dir.mkdir()
    (lut_dir / "one.cube").write_text("my version")

    result = luts.copy_into_library(
        [{"path": str(lut_dir / "one.cube"), "dest_rel": "one.cube"}], library
    )
    assert result["copied"] == 0 and result["skipped"] == 1
    assert (library / "one.cube").read_text() == "library version"


def test_copy_leaves_no_partial_file_visible(tmp_path, monkeypatch):
    """Syncthing is watching this directory: a half-copied LUT must never be
    indexed, which is why the copy lands on .ccsync-tmp first (a name the
    folder's .stignore excludes)."""
    library = _library(tmp_path)
    lut_dir = tmp_path / "resolve-lut"
    lut_dir.mkdir()
    (lut_dir / "one.cube").write_text("data")

    seen = {}

    real_copy = luts.shutil.copy2

    def spy(src, dst, *args, **kwargs):
        seen["dst"] = str(dst)
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(luts.shutil, "copy2", spy)
    luts.copy_into_library(
        [{"path": str(lut_dir / "one.cube"), "dest_rel": "one.cube"}], library
    )
    assert seen["dst"].endswith(".ccsync-tmp")
    assert (library / "one.cube").exists()
    assert not list(library.glob("*.ccsync-tmp"))
