"""The Resolve Mapped Mount helper embedded in installer/macos_bootstrap.sh.

The module under test is not a file in this package: it is the python block
between the CCSYNC-MAPPING-HELPER sentinels inside the macOS bootstrap
script, which the installer extracts with sed at run time. These tests
extract the SAME range and import it, so what is covered here is
byte-for-byte what runs on an editor's Mac -- and the extraction itself is
the first assertion (a stray edit to the sentinels breaks the installer
silently otherwise).

Everything is driven through $BMD_RESOLVE_CONFIG_DIR and an injected
"is Resolve running" probe, so nothing here needs a Mac, a Resolve install,
or a real preference file.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

SENTINEL_BEGIN = "# ---CCSYNC-MAPPING-HELPER-BEGIN---"
SENTINEL_END = "# ---CCSYNC-MAPPING-HELPER-END---"

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "installer" / "macos_bootstrap.sh"

# A real Windows config.dat's filesystem block, verbatim -- the format the
# parser has to round-trip without touching anything it does not own.
WINDOWS_SAMPLE = """Site.1.FS.Count = 2

Site.1.FS.1.Type = IOFileSys
Site.1.FS.1.Root = G:\\Resolve Media
Site.1.FS.1.MappedRoot =
Site.1.FS.1.DIO = 1
Site.1.FS.1.BrightClip = 0

Site.1.FS.2.Type = IOFileSys
Site.1.FS.2.Root = ResolveVirtual
Site.1.FS.2.MappedRoot =
Site.1.FS.2.DIO = 1
Site.1.FS.2.BrightClip = 0
"""

# The macOS shape: Resolve appends its own /Volumes entry and expects it last.
MAC_DAT = """Site.1.Name = Local
Site.1.FS.Count = 2

Site.1.FS.1.Type = IOFileSys
Site.1.FS.1.Root = /Users/ed/Movies
Site.1.FS.1.MappedRoot =
Site.1.FS.1.MacDIO = 1
Site.1.FS.1.BrightClip = 0

Site.1.FS.2.Type = IOFileSys
Site.1.FS.2.Root = /Volumes
Site.1.FS.2.MappedRoot =
Site.1.FS.2.MacDIO = 1
Site.1.FS.2.BrightClip = 0

Site.1.Trailing = keep-me
"""

MAC_DATA = """IoFsNum = 2
IoFsMount_0 = /Users/ed/Movies
IoFsMappedMount_0 =
IoFsDirectIO_0 = 1
IoFsMount_1 = /Volumes
IoFsMappedMount_1 =
IoFsDirectIO_1 = 1
SomeOtherSetting = 7
"""

LOCAL_ROOT = "/Volumes/RigSSD/Creators_Club"
MAPPED_ROOT = "P:" + "\\"


def _extract_helper_source() -> str:
    text = BOOTSTRAP.read_text(encoding="utf-8")
    lines = text.split("\n")
    begins = [i for i, line in enumerate(lines) if line == SENTINEL_BEGIN]
    ends = [i for i, line in enumerate(lines) if line == SENTINEL_END]
    assert len(begins) == 1, (
        f"{BOOTSTRAP} must contain exactly one {SENTINEL_BEGIN} line, found "
        f"{len(begins)} -- installer/macos_bootstrap.sh seds between these "
        "sentinels to extract the helper"
    )
    assert len(ends) == 1, f"expected exactly one {SENTINEL_END} line, found {len(ends)}"
    assert begins[0] < ends[0]
    return "\n".join(lines[begins[0] + 1:ends[0]]) + "\n"


@pytest.fixture(scope="module")
def helper(tmp_path_factory):
    """The embedded module, extracted and imported. Doubles as the
    "is it still extractable and loadable" smoke test."""
    source = _extract_helper_source()
    path = tmp_path_factory.mktemp("mapping-helper") / "ccsync_resolve_mapping.py"
    path.write_text(source, encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location("ccsync_resolve_mapping", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_prefs(directory: Path, dat: str = MAC_DAT, data: str = MAC_DATA,
                newline: str = "\n") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, body in ((".config.data", data), ("config.dat", dat)):
        with open(directory / name, "w", encoding="utf-8", newline="") as handle:
            handle.write(body.replace("\n", newline))
    return directory


def run(helper, monkeypatch, config_dir, *args, running=False):
    monkeypatch.setenv("BMD_RESOLVE_CONFIG_DIR", str(config_dir))
    return helper.main(list(args), running_probe=lambda: running)


def apply(helper, monkeypatch, config_dir, local_root=LOCAL_ROOT, running=False):
    return run(helper, monkeypatch, config_dir, "apply",
               "--local-root", local_root, "--mapped-root", MAPPED_ROOT,
               running=running)


def read(config_dir, name):
    return (config_dir / name).read_text(encoding="utf-8")


def raw(config_dir, name):
    return (config_dir / name).read_bytes()


def backups(config_dir):
    return sorted(p.name for p in config_dir.iterdir() if ".ccsync-backup-" in p.name)


# ----------------------------------------------------------------- structure


def test_the_helper_is_extractable_and_exposes_its_exit_codes(helper):
    assert helper.EXIT_OK == 0
    # Distinct, documented, and none of them argparse's own 2.
    codes = {
        "resolve running": helper.EXIT_RESOLVE_RUNNING,
        "config missing": helper.EXIT_CONFIG_MISSING,
        "format": helper.EXIT_FORMAT_UNRECOGNISED,
        "verify absent": helper.EXIT_MAPPING_ABSENT,
        "verify wrong": helper.EXIT_MAPPING_WRONG,
        "io": helper.EXIT_IO_ERROR,
    }
    assert len(set(codes.values())) == len(codes), codes
    assert 2 not in codes.values(), "2 is argparse's usage error"
    assert 0 not in codes.values()
    for name, code in codes.items():
        assert f"  {code}  " in helper.__doc__, f"exit code {code} ({name}) is undocumented"


def test_the_helper_needs_no_third_party_imports(helper):
    source = _extract_helper_source()
    imported = {
        line.split()[1].split(".")[0]
        for line in source.splitlines()
        if line.startswith("import ") or line.startswith("from ")
    }
    assert imported <= {
        "argparse", "os", "re", "shutil", "stat", "subprocess", "sys",
        "tempfile", "time", "__future__",
    }, imported


# --------------------------------------------------------------------- apply


def test_apply_adds_the_mapping_to_both_files(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs")

    assert apply(helper, monkeypatch, config_dir) == helper.EXIT_OK

    dat = read(config_dir, "config.dat")
    assert "Site.1.FS.Count = 3" in dat
    assert f"Site.1.FS.2.Root = {LOCAL_ROOT}" in dat
    assert "Site.1.FS.2.Type = IOFileSys" in dat
    assert "Site.1.FS.2.MappedRoot = P:\\" in dat
    # MacDIO, not DIO: the key is platform-specific.
    assert "Site.1.FS.2.MacDIO = 1" in dat
    assert "Site.1.FS.2.DIO = 1" not in dat
    assert "Site.1.FS.2.BrightClip = 0" in dat

    data = read(config_dir, ".config.data")
    assert "IoFsNum = 3" in data
    # Ours takes slot 1, in FRONT of the /Volumes auto-entry, exactly as in
    # config.dat above. This assertion used to read `IoFsMount_2` -- i.e. it
    # enshrined our entry being appended AFTER /Volumes, because
    # insert_position() was a ConfigDat-only override. The two files ended up
    # with different orderings for the same mapping, and the docs claimed
    # otherwise. MAC-D5, first real Mac 2026-08-04.
    assert f"IoFsMount_1 = {LOCAL_ROOT}" in data
    assert "IoFsMappedMount_1 = P:\\" in data
    assert "IoFsDirectIO_1 = 1" in data
    assert "IoFsMount_2 = /Volumes" in data


def test_the_volumes_auto_entry_stays_last_after_renumbering(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs")

    apply(helper, monkeypatch, config_dir)

    dat = read(config_dir, "config.dat")
    # Ours took slot 2, /Volumes was renumbered to 3 and is still last.
    assert "Site.1.FS.3.Root = /Volumes\n" in dat
    assert dat.index("Site.1.FS.2.Root") < dat.index("Site.1.FS.3.Root = /Volumes")
    roots = [line for line in dat.splitlines() if ".Root = " in line]
    assert roots[-1] == "Site.1.FS.3.Root = /Volumes"
    # ...and the pre-existing first entry kept its number and its values.
    assert "Site.1.FS.1.Root = /Users/ed/Movies" in dat


def test_the_volumes_auto_entry_stays_last_in_config_data_too(helper, monkeypatch, tmp_path):
    """The .config.data half of the same rule -- the one that was missing.

    ConfigData inherited the base insert_position() (plain append), so our
    entry landed after Resolve's trailing /Volumes entry while config.dat put
    it in front. Both files now share the base-class implementation.
    """
    config_dir = write_prefs(tmp_path / "prefs")

    apply(helper, monkeypatch, config_dir)

    data = read(config_dir, ".config.data")
    mounts = [line for line in data.splitlines() if line.startswith("IoFsMount_")]
    assert mounts[-1].endswith("/Volumes"), mounts
    assert mounts == [
        "IoFsMount_0 = /Users/ed/Movies",
        f"IoFsMount_1 = {LOCAL_ROOT}",
        "IoFsMount_2 = /Volumes",
    ]
    # Unknown keys are still untouched and still in place.
    assert "SomeOtherSetting = 7" in data


def test_a_config_data_without_a_volumes_entry_just_appends(helper, monkeypatch, tmp_path):
    """The shape the first real Mac actually had (2026-08-04): config.dat
    carried a /Volumes auto-entry, .config.data carried none. With nothing to
    step over, the new entry appends -- and the count still matches."""
    no_volumes = """IoFsNum = 1
IoFsMount_1 = /Users/editor1/Movies
IoFsMappedMount_1 =
IoFsDirectIO_1 = 1
SomeOtherSetting = 7
"""
    config_dir = write_prefs(tmp_path / "prefs", data=no_volumes)

    assert apply(helper, monkeypatch, config_dir) == helper.EXIT_OK

    data = read(config_dir, ".config.data")
    assert "IoFsNum = 2" in data
    # 1-based in, 1-based out -- the file's own numbering is preserved.
    assert "IoFsMount_1 = /Users/editor1/Movies" in data
    assert f"IoFsMount_2 = {LOCAL_ROOT}" in data
    assert "IoFsMappedMount_2 = P:\\" in data


def test_windows_style_trailing_entry_also_stays_last(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs", dat=WINDOWS_SAMPLE)

    apply(helper, monkeypatch, config_dir)

    dat = read(config_dir, "config.dat")
    assert "Site.1.FS.Count = 3" in dat
    assert "Site.1.FS.1.Root = G:\\Resolve Media" in dat
    assert f"Site.1.FS.2.Root = {LOCAL_ROOT}" in dat
    assert "Site.1.FS.3.Root = ResolveVirtual" in dat
    # The untouched entry keeps its Windows DIO key -- no gratuitous rewrites.
    assert "Site.1.FS.1.DIO = 1" in dat


def test_a_zero_based_config_dat_keeps_its_own_numbering(helper, monkeypatch, tmp_path):
    # Every sample seen so far numbers Site.N.FS from 1, but the helper reads
    # the base from the file (as it already did for .config.data's IoFs_N):
    # renumbering a 0-based file from 1 would silently rewrite Resolve's own
    # entries.
    zero_based = (
        MAC_DAT.replace("Site.1.FS.2.", "Site.1.FS.TMP.")
        .replace("Site.1.FS.1.", "Site.1.FS.0.")
        .replace("Site.1.FS.TMP.", "Site.1.FS.1.")
    )
    config_dir = write_prefs(tmp_path / "prefs", dat=zero_based)

    assert apply(helper, monkeypatch, config_dir) == helper.EXIT_OK

    dat = read(config_dir, "config.dat")
    assert "Site.1.FS.Count = 3" in dat
    # Resolve's first entry kept its number; ours slotted in at 1; the
    # /Volumes auto-entry is still last, still in the file's own base.
    assert "Site.1.FS.0.Root = /Users/ed/Movies" in dat
    assert f"Site.1.FS.1.Root = {LOCAL_ROOT}" in dat
    assert "Site.1.FS.1.MappedRoot = P:\\" in dat
    assert "Site.1.FS.2.Root = /Volumes" in dat
    assert "Site.1.FS.3." not in dat


def test_apply_repoints_an_existing_mapping_at_the_new_root(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(
        tmp_path / "prefs",
        dat=MAC_DAT.replace("Site.1.FS.1.MappedRoot =", "Site.1.FS.1.MappedRoot = P:\\"),
        data=MAC_DATA.replace("IoFsMappedMount_0 =", "IoFsMappedMount_0 = P:\\"),
    )

    assert apply(helper, monkeypatch, config_dir) == helper.EXIT_OK

    dat = read(config_dir, "config.dat")
    # Updated IN PLACE: still two entries, still slot 1, new Root.
    assert "Site.1.FS.Count = 2" in dat
    assert f"Site.1.FS.1.Root = {LOCAL_ROOT}" in dat
    assert "Site.1.FS.1.MappedRoot = P:\\" in dat
    assert "/Users/ed/Movies" not in dat
    data = read(config_dir, ".config.data")
    assert "IoFsNum = 2" in data
    assert f"IoFsMount_0 = {LOCAL_ROOT}" in data


def test_apply_maps_an_existing_entry_that_already_has_our_root(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(
        tmp_path / "prefs",
        dat=MAC_DAT.replace("Site.1.FS.1.Root = /Users/ed/Movies",
                            f"Site.1.FS.1.Root = {LOCAL_ROOT}"),
        data=MAC_DATA.replace("IoFsMount_0 = /Users/ed/Movies",
                              f"IoFsMount_0 = {LOCAL_ROOT}"),
    )

    assert apply(helper, monkeypatch, config_dir) == helper.EXIT_OK

    dat = read(config_dir, "config.dat")
    assert "Site.1.FS.Count = 2" in dat, "no new entry should have been added"
    assert "Site.1.FS.1.MappedRoot = P:\\" in dat
    data = read(config_dir, ".config.data")
    assert "IoFsNum = 2" in data
    assert "IoFsMappedMount_0 = P:\\" in data


def test_a_trailing_slash_on_the_local_root_is_normalised(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs")

    apply(helper, monkeypatch, config_dir, local_root=LOCAL_ROOT + "/")

    assert f"Site.1.FS.2.Root = {LOCAL_ROOT}\n" in read(config_dir, "config.dat")


def test_a_second_apply_writes_nothing_at_all(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs")
    apply(helper, monkeypatch, config_dir)
    first = (raw(config_dir, "config.dat"), raw(config_dir, ".config.data"))
    made = backups(config_dir)
    assert len(made) == 2

    assert apply(helper, monkeypatch, config_dir) == helper.EXIT_OK

    assert (raw(config_dir, "config.dat"), raw(config_dir, ".config.data")) == first
    assert backups(config_dir) == made, "an already-correct run must not spam backups"


def test_a_site_2_only_file_is_patched_under_site_2(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(
        tmp_path / "prefs",
        dat="Site.2.Name = Only\nSite.2.FS.Count = 0\n",
        data="IoFsNum = 0\n",
    )

    assert apply(helper, monkeypatch, config_dir) == helper.EXIT_OK

    dat = read(config_dir, "config.dat")
    assert "Site.2.FS.Count = 1" in dat
    assert f"Site.2.FS.1.Root = {LOCAL_ROOT}" in dat
    assert "Site.1." not in dat
    data = read(config_dir, ".config.data")
    assert "IoFsNum = 1" in data
    assert f"IoFsMount_0 = {LOCAL_ROOT}" in data


def test_only_the_first_site_with_a_count_is_patched_and_extras_are_warned_about(
        helper, monkeypatch, tmp_path, capsys):
    second_site = MAC_DAT + "\nSite.2.FS.Count = 1\n\nSite.2.FS.1.Root = /elsewhere\n"
    config_dir = write_prefs(tmp_path / "prefs", dat=second_site)

    apply(helper, monkeypatch, config_dir)

    dat = read(config_dir, "config.dat")
    assert "Site.1.FS.Count = 3" in dat, "Site.1 is the one that got the mapping"
    assert "Site.2.FS.Count = 1" in dat, "Site.2 must be left exactly as it was"
    assert "Site.2.FS.1.Root = /elsewhere" in dat
    assert f"Site.2.FS.1.Root = {LOCAL_ROOT}" not in dat
    stderr = capsys.readouterr().err
    assert "2 Sites" in stderr and "only Site.1 was patched" in stderr, stderr


# -------------------------------------------------------------------- remove


def test_remove_deletes_the_entry_and_renumbers(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs")
    apply(helper, monkeypatch, config_dir)

    assert run(helper, monkeypatch, config_dir, "remove",
               "--mapped-root", MAPPED_ROOT) == helper.EXIT_OK

    dat = read(config_dir, "config.dat")
    assert "Site.1.FS.Count = 2" in dat
    assert LOCAL_ROOT not in dat
    assert "P:\\" not in dat
    assert "Site.1.FS.1.Root = /Users/ed/Movies" in dat
    assert "Site.1.FS.2.Root = /Volumes" in dat
    assert "Site.1.Trailing = keep-me" in dat
    data = read(config_dir, ".config.data")
    assert "IoFsNum = 2" in data
    assert LOCAL_ROOT not in data
    assert "IoFsMount_1 = /Volumes" in data
    assert "SomeOtherSetting = 7" in data


def test_remove_is_a_clean_no_op_when_the_mapping_is_absent(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs")
    before = (raw(config_dir, "config.dat"), raw(config_dir, ".config.data"))

    assert run(helper, monkeypatch, config_dir, "remove",
               "--mapped-root", MAPPED_ROOT) == helper.EXIT_OK

    assert (raw(config_dir, "config.dat"), raw(config_dir, ".config.data")) == before
    assert backups(config_dir) == []


# ------------------------------------------------------------------- refusal


def test_apply_refuses_while_resolve_is_running(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs")
    before = (raw(config_dir, "config.dat"), raw(config_dir, ".config.data"))

    assert apply(helper, monkeypatch, config_dir,
                 running=True) == helper.EXIT_RESOLVE_RUNNING

    assert (raw(config_dir, "config.dat"), raw(config_dir, ".config.data")) == before
    assert backups(config_dir) == []


def test_remove_refuses_while_resolve_is_running(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs")

    assert run(helper, monkeypatch, config_dir, "remove", "--mapped-root",
               MAPPED_ROOT, running=True) == helper.EXIT_RESOLVE_RUNNING


def test_a_missing_config_directory_defers_and_creates_nothing(helper, monkeypatch, tmp_path):
    absent = tmp_path / "never-launched"

    assert apply(helper, monkeypatch, absent) == helper.EXIT_CONFIG_MISSING

    assert not absent.exists(), "a missing preference directory must not be created"


def test_a_config_directory_without_config_dat_defers(helper, monkeypatch, tmp_path):
    config_dir = tmp_path / "prefs"
    config_dir.mkdir()

    assert apply(helper, monkeypatch, config_dir) == helper.EXIT_CONFIG_MISSING

    assert list(config_dir.iterdir()) == [], "Resolve's first run writes these, not us"


def test_a_half_present_config_directory_defers(helper, monkeypatch, tmp_path):
    config_dir = tmp_path / "prefs"
    config_dir.mkdir()
    (config_dir / "config.dat").write_text(MAC_DAT, encoding="utf-8")

    assert apply(helper, monkeypatch, config_dir) == helper.EXIT_CONFIG_MISSING

    assert not (config_dir / ".config.data").exists()
    assert (config_dir / "config.dat").read_text(encoding="utf-8") == MAC_DAT


@pytest.mark.parametrize("dat,data", [
    ("Site.1.Name = no filesystems here\n", MAC_DATA),
    ("Site.1.FS.Count = not-a-number\n", MAC_DATA),
    (MAC_DAT, "SomeOtherSetting = 7\n"),
    (MAC_DAT, "IoFsNum = many\n"),
])
def test_an_unrecognised_format_touches_nothing(helper, monkeypatch, tmp_path, dat, data):
    config_dir = write_prefs(tmp_path / "prefs", dat=dat, data=data)
    before = (raw(config_dir, "config.dat"), raw(config_dir, ".config.data"))

    assert apply(helper, monkeypatch, config_dir) == helper.EXIT_FORMAT_UNRECOGNISED

    assert (raw(config_dir, "config.dat"), raw(config_dir, ".config.data")) == before
    assert backups(config_dir) == []


# --------------------------------------------------------------- preservation


def test_unknown_lines_and_blank_structure_survive_byte_for_byte(helper, monkeypatch, tmp_path):
    dat = (
        "# a comment Resolve never wrote\n"
        "Site.1.Name = Local\n"
        "\n"
        "\n"
        "Site.1.FS.Count = 1\n"
        "\n"
        "Site.1.FS.1.Type = IOFileSys\n"
        "Site.1.FS.1.Root = /Volumes\n"
        "Site.1.FS.1.MappedRoot = \n"
        "Site.1.FS.1.MacDIO = 1\n"
        "Site.1.FS.1.BrightClip = 0\n"
        "\n"
        "Site.1.SomethingElse = 42\n"
        "Site.1.NoTrailingNewlineAfterThis = yes"
    )
    config_dir = write_prefs(tmp_path / "prefs", dat=dat)

    apply(helper, monkeypatch, config_dir)

    after = read(config_dir, "config.dat")
    for line in ("# a comment Resolve never wrote", "Site.1.Name = Local",
                 "Site.1.SomethingElse = 42"):
        assert line + "\n" in after
    assert after.startswith("# a comment Resolve never wrote\nSite.1.Name = Local\n\n\n")
    # The file had no trailing newline; it still has none.
    assert after.endswith("Site.1.NoTrailingNewlineAfterThis = yes")
    # Our entry went in ahead of the /Volumes auto-entry, blank-separated.
    assert "\n\nSite.1.FS.1.Type = IOFileSys\n" in after
    assert f"Site.1.FS.1.Root = {LOCAL_ROOT}\n" in after
    assert "Site.1.FS.2.Root = /Volumes\n" in after


def test_indentation_and_spacing_of_untouched_lines_are_preserved(helper, monkeypatch, tmp_path):
    dat = (
        "Site.1.FS.Count=1\n"
        "  Site.1.FS.1.Type   =   IOFileSys\n"
        "  Site.1.FS.1.Root   =   /Volumes\n"
    )
    config_dir = write_prefs(tmp_path / "prefs", dat=dat)

    apply(helper, monkeypatch, config_dir)

    after = read(config_dir, "config.dat")
    assert "Site.1.FS.Count=2" in after, "the count keeps the file's own spacing"
    # The /Volumes entry moved to slot 2 but kept its odd spacing verbatim.
    assert "  Site.1.FS.2.Type   =   IOFileSys\n" in after
    assert "  Site.1.FS.2.Root   =   /Volumes\n" in after


def test_a_crlf_file_stays_crlf(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs", newline="\r\n")

    apply(helper, monkeypatch, config_dir)

    for name in ("config.dat", ".config.data"):
        body = raw(config_dir, name)
        assert b"\r\n" in body
        assert body.count(b"\n") == body.count(b"\r\n"), f"{name} gained a bare LF"


def test_an_lf_file_stays_lf(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs")

    apply(helper, monkeypatch, config_dir)

    for name in ("config.dat", ".config.data"):
        assert b"\r" not in raw(config_dir, name)


def test_both_files_are_backed_up_before_the_first_write(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs")
    original = (raw(config_dir, "config.dat"), raw(config_dir, ".config.data"))

    apply(helper, monkeypatch, config_dir)

    made = backups(config_dir)
    assert len(made) == 2, made
    restored = tuple(
        (config_dir / name).read_bytes()
        for name in sorted(made, key=lambda n: n.startswith(".config.data"))
    )
    assert restored == original


# -------------------------------------------------------------------- verify


def test_verify_is_read_only_and_reports_correct_absent_and_wrong(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs")

    def verify(local_root):
        return run(helper, monkeypatch, config_dir, "verify",
                   "--local-root", local_root, "--mapped-root", MAPPED_ROOT)

    assert verify(LOCAL_ROOT) == helper.EXIT_MAPPING_ABSENT
    before = (raw(config_dir, "config.dat"), raw(config_dir, ".config.data"))

    apply(helper, monkeypatch, config_dir)
    assert verify(LOCAL_ROOT) == helper.EXIT_OK
    assert verify("/Volumes/SomeOtherDisk/Creators_Club") == helper.EXIT_MAPPING_WRONG

    # ...and none of those verify calls changed a byte (the absent-state
    # snapshot is the only one taken before an apply).
    assert before != (raw(config_dir, "config.dat"), raw(config_dir, ".config.data"))
    after = (raw(config_dir, "config.dat"), raw(config_dir, ".config.data"))
    verify(LOCAL_ROOT)
    verify("/nowhere")
    assert (raw(config_dir, "config.dat"), raw(config_dir, ".config.data")) == after


def test_verify_flags_a_mapping_present_in_only_one_file(helper, monkeypatch, tmp_path):
    """config.dat alone has no lasting effect -- Resolve rewrites it from the
    GUI form. A half-applied mapping must not read as correct."""
    config_dir = write_prefs(
        tmp_path / "prefs",
        dat=MAC_DAT.replace("Site.1.FS.1.MappedRoot =",
                            f"Site.1.FS.1.MappedRoot = {MAPPED_ROOT}").replace(
            "Site.1.FS.1.Root = /Users/ed/Movies", f"Site.1.FS.1.Root = {LOCAL_ROOT}"),
    )

    assert run(helper, monkeypatch, config_dir, "verify", "--local-root", LOCAL_ROOT,
               "--mapped-root", MAPPED_ROOT) == helper.EXIT_MAPPING_WRONG


def test_verify_needs_a_local_root(helper, monkeypatch, tmp_path):
    config_dir = write_prefs(tmp_path / "prefs")
    with pytest.raises(SystemExit) as excinfo:
        run(helper, monkeypatch, config_dir, "verify")
    assert excinfo.value.code == 2


# ------------------------------------------------------------------ discovery


def test_the_env_override_wins_over_the_standard_directories(helper, monkeypatch, tmp_path):
    monkeypatch.setenv("BMD_RESOLVE_CONFIG_DIR", str(tmp_path / "chosen"))
    assert helper.find_config_dir() == str(tmp_path / "chosen")


def test_the_standard_directory_holding_config_dat_wins(helper, monkeypatch, tmp_path):
    monkeypatch.delenv("BMD_RESOLVE_CONFIG_DIR", raising=False)
    home = tmp_path / "home"
    plain, container = helper.candidate_config_dirs(str(home))
    # No "Preferences" subfolder on macOS, and the container path is the Mac
    # App Store build's.
    expected_tail = os.path.join("Library", "Preferences", "Blackmagic Design",
                                 "DaVinci Resolve")
    assert plain.endswith(expected_tail)
    assert "Preferences" not in plain.rsplit("DaVinci Resolve", 1)[-1]
    assert "com.blackmagic-design.DaVinciResolve" in container

    assert helper.find_config_dir(home=str(home)) is None

    Path(container).mkdir(parents=True)
    (Path(container) / "config.dat").write_text(MAC_DAT, encoding="utf-8")
    assert helper.find_config_dir(home=str(home)) == container

    Path(plain).mkdir(parents=True)
    (Path(plain) / "config.dat").write_text(MAC_DAT, encoding="utf-8")
    assert helper.find_config_dir(home=str(home)) == plain
