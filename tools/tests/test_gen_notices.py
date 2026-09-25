"""Tests for tools/gen_notices.py — the notices generator.

Run from the repo root with any interpreter that has pytest:

    dashboard\\.venv\\Scripts\\python.exe -m pytest tools/tests -q

Nothing here touches a venv, pip, or the network: `collect()` is the only
function that shells out and it is never called. What IS pinned is the
hand-maintained block's survival, because that block carries the ffmpeg
written offer and the "no licence grant" finding — losing it silently is the
one failure mode of this tool that matters (2026-08-17,
docs/COMMERCIAL_READINESS.md item 3).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gen_notices  # noqa: E402


PKG = {"Name": "somepkg", "Version": "1.0", "License": "MIT",
       "URL": "https://example.invalid", "LicenseText": "MIT License ..."}


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "THIRD_PARTY_NOTICES.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_hand_block_is_read_back_verbatim(tmp_path):
    path = _write(tmp_path, "\n".join([
        "# notices", "",
        gen_notices.BEGIN_SENTINEL,
        "## Non-pip components",
        "",
        "ffmpeg is GPLv3.",
        gen_notices.END_SENTINEL,
        "",
    ]))
    assert gen_notices.existing_hand_block(path) == (
        "## Non-pip components\n\nffmpeg is GPLv3.")


def test_sentinels_mentioned_in_prose_do_not_match():
    """The generated header EXPLAINS the sentinels, so it contains both
    strings mid-sentence. A substring search matched those and wiped the whole
    hand-maintained section on the first regeneration (2026-08-17) -- this is
    that bug."""
    rendered = gen_notices.render({"companion": [PKG]}, [], "KEEP ME")
    header_line = next(line for line in rendered.splitlines()
                       if gen_notices.BEGIN_SENTINEL in line
                       and line.strip() != gen_notices.BEGIN_SENTINEL)
    assert header_line  # the trap exists in the real output, not just in theory
    assert rendered.count(gen_notices.BEGIN_SENTINEL) >= 2


def test_render_round_trips_the_hand_block(tmp_path):
    path = _write(tmp_path, gen_notices.render(
        {"companion": [PKG]}, [], "## Non-pip components\n\nffmpeg is GPLv3."))
    assert gen_notices.existing_hand_block(path) == (
        "## Non-pip components\n\nffmpeg is GPLv3.")
    # ...and a second generation off that file keeps it.
    again = gen_notices.render({"companion": [PKG]}, [],
                               gen_notices.existing_hand_block(path))
    assert "ffmpeg is GPLv3." in again


def test_missing_file_yields_the_placeholder(tmp_path):
    assert gen_notices.existing_hand_block(
        tmp_path / "nope.md") == gen_notices.DEFAULT_HAND_BLOCK


def test_file_without_sentinels_yields_the_placeholder(tmp_path):
    path = _write(tmp_path, "# notices\n\nnothing here\n")
    assert gen_notices.existing_hand_block(path) == gen_notices.DEFAULT_HAND_BLOCK


def test_half_applied_sentinels_refuse_rather_than_wipe(tmp_path):
    path = _write(tmp_path, "\n".join([
        gen_notices.BEGIN_SENTINEL, "irreplaceable text", ""]))
    with pytest.raises(SystemExit):
        gen_notices.existing_hand_block(path)


def test_copyleft_is_flagged_and_permissive_is_not():
    rows = gen_notices.merged({
        "companion": [
            {**PKG, "Name": "pystray", "License": "GNU Lesser General Public "
                                                  "License v3 (LGPLv3)"},
            {**PKG, "Name": "certifi", "License": "Mozilla Public License 2.0 (MPL 2.0)"},
            {**PKG, "Name": "watchdog", "License": "Apache Software License"},
        ]})
    flagged = {row["Name"]: kind for row, kind in gen_notices.attention(rows)}
    assert flagged == {"pystray": "LGPL", "certifi": "MPL"}


def test_lgpl_is_not_reported_as_plain_gpl():
    """'GPL' is a substring of 'LGPL'; reporting an LGPL package as GPL would
    overstate the obligation, which is the opposite of useful in a document
    counsel reads."""
    rows = gen_notices.merged({"dashboard": [{**PKG, "Name": "paramiko",
                                              "License": "LGPL-2.1"}]})
    assert gen_notices.attention(rows)[0][1] == "LGPL"


def test_same_package_in_two_venvs_merges_but_two_versions_do_not():
    rows = gen_notices.merged({
        "dashboard": [{**PKG, "Name": "numpy", "Version": "2.5.2"}],
        "music/web": [{**PKG, "Name": "numpy", "Version": "2.5.2"},
                      {**PKG, "Name": "uvicorn", "Version": "0.52.1"}],
        "broll/web": [{**PKG, "Name": "uvicorn", "Version": "0.51.0"}],
    })
    by_key = {(r["Name"], r["Version"]): r["_components"] for r in rows}
    assert by_key[("numpy", "2.5.2")] == ["dashboard", "music/web"]
    # A licence can change between versions, so these must stay separate rows.
    assert by_key[("uvicorn", "0.52.1")] == ["music/web"]
    assert by_key[("uvicorn", "0.51.0")] == ["broll/web"]


def test_pipe_in_a_licence_string_cannot_open_a_table_column():
    rendered = gen_notices.render(
        {"companion": [{**PKG, "License": "MIT | Apache-2.0"}]}, [], "x")
    assert "MIT \\| Apache-2.0" in rendered


def test_scan_warnings_are_stated_in_the_document():
    """A component that could not be scanned must say so IN the notices file.
    A missing venv silently producing a shorter inventory is how a licence
    goes unlisted."""
    rendered = gen_notices.render({"companion": [PKG]}, ["ytdl/web: no venv"], "x")
    assert "## Scan warnings" in rendered
    assert "ytdl/web: no venv" in rendered


# ------------------------------------------------------------ server-tools-1
# The CONTAINER's lock is what a customer is conveyed, and it was in no table:
# psycopg2-binary (LGPL) entered dashboard/deploy/requirements.lock, was
# excused in license_allowlist.toml on the written promise of a notice, and
# the notice did not exist.

LOCK = """\
# generated by uv
a2wsgi==1.10.10 \
    --hash=sha256:aaaa
    # via -r requirements.txt
psycopg2-binary==2.9.12 \
    --hash=sha256:bbbb
    # via -r requirements.txt
"""


def test_a_hash_pinned_lock_is_read_as_names_and_versions(tmp_path):
    path = tmp_path / "requirements.lock"
    path.write_text(LOCK, encoding="utf-8")
    assert gen_notices.read_lock(path) == [("a2wsgi", "1.10.10"),
                                           ("psycopg2-binary", "2.9.12")]


def test_an_absent_lock_is_not_an_exception(tmp_path):
    assert gen_notices.read_lock(tmp_path / "nope.lock") == []


def test_the_container_lock_is_licence_scanned_and_flagged(tmp_path,
                                                           monkeypatch):
    path = tmp_path / "requirements.lock"
    path.write_text(LOCK, encoding="utf-8")
    monkeypatch.setattr(gen_notices, "CONTAINER_LOCKS",
                        [("dashboard-container", path, "the shipped image")])
    monkeypatch.setattr(gen_notices, "REPO", tmp_path)
    venv = {"dashboard": [dict(PKG, Name="psycopg2-binary", Version="2.9.13",
                               License="GNU Library or Lesser General Public "
                                       "License (LGPL)")]}

    out = gen_notices.render(venv, [], "hand")

    assert "dashboard-container" in out
    # The conveyed VERSION, and it reaches the attention table.
    assert "2.9.12" in out
    head = out[out.index("## LICENCES NEEDING ATTENTION"):]
    attention = head[:head.index(chr(10) + "## ", 1)]
    assert "psycopg2-binary" in attention
    assert "dashboard-container" in attention


def test_a_locked_package_no_venv_holds_is_unknown_not_permissive(tmp_path):
    rows = gen_notices.lock_rows({}, _lock_at(tmp_path))
    assert [r["License"] for r in rows] == ["UNKNOWN", "UNKNOWN"]
    assert all("not installed" in r["_licence_source"] for r in rows)


def _lock_at(tmp_path: Path) -> Path:
    path = tmp_path / "requirements.lock"
    path.write_text(LOCK, encoding="utf-8")
    return path


# ------------------------------------------------------------------ LG-13
# docs/LEGAL_GAP_FEATURES_PLAN.md section 5, 2026-09-25: PEP 503 names on both
# sides, no ytdl/web row, and a download table read from the code by symbol.

REPO = Path(__file__).resolve().parents[2]


def test_lock_and_venv_spellings_meet_after_normalisation(tmp_path):
    path = tmp_path / "requirements.lock"
    path.write_text("pyobjc-framework-cocoa==12.2.2 \\\n    --hash=sha256:aa\n",
                    encoding="utf-8")
    venv = {"companion": [dict(PKG, Name="pyobjc_framework.Cocoa",
                               Version="12.2.2", License="MIT")]}
    rows = gen_notices.lock_rows(venv, path)
    assert rows[0]["License"] == "MIT"
    assert "not installed" not in rows[0]["_licence_source"]


def test_one_distribution_spelt_two_ways_is_one_merged_row():
    rows = gen_notices.merged({
        "dashboard": [dict(PKG, Name="Pygments", Version="2.21.0")],
        "music/web": [dict(PKG, Name="pygments", Version="2.21.0")],
    })
    assert len(rows) == 1
    assert rows[0]["_components"] == ["dashboard", "music/web"]


def test_ytdl_web_is_not_a_component_row():
    """It never had a venv; its row was a permanent scan warning."""
    assert "ytdl/web" not in [label for label, _v, _d in gen_notices.COMPONENTS]


def test_venv_paths_are_printed_repo_relative():
    assert gen_notices.shown_path(REPO / "companion" / ".venv") == "companion/.venv"


def test_the_download_pins_are_read_from_the_code():
    rows = gen_notices.fetched_binaries()
    by = {(r["component"], r["platform"]): r for r in rows}
    ps1 = (REPO / "installer" / "windows_bootstrap.ps1").read_text(encoding="utf-8")
    assert by[("rclone", "Windows x64")]["sha256"] in ps1
    assert by[("Syncthing", "macOS arm64")]["asset"].startswith("syncthing-macos-arm64-")
    assert by[("ffmpeg", "Windows x64")]["asset"] == "ffmpeg-win32-x64.gz"
    assert by[("deno", "macOS arm64")]["version"].startswith("v")
    assert any(r["component"] == "ffmpeg (NAS side)" for r in rows)
    for row in rows:
        assert len(row["sha256"]) == 64, row
        assert all(c in "0123456789abcdef" for c in row["sha256"]), row


def _fake_repo(tmp_path: Path, rename: tuple[str, str]) -> Path:
    for rel in ("installer/windows_bootstrap.ps1", "installer/macos_bootstrap.sh",
                "companion/src/ccsync_companion/sidecar_tools.py",
                "server/install_dashboard_app.py"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (REPO / rel).read_text(encoding="utf-8")
        if rel.endswith(rename[0]):
            text = text.replace(rename[1], rename[1] + "_RENAMED")
        target.write_text(text, encoding="utf-8")
    return tmp_path


def test_a_renamed_pin_symbol_is_an_error_not_a_missing_row(tmp_path):
    repo = _fake_repo(tmp_path, ("windows_bootstrap.ps1", "$RcloneZipSha256"))
    with pytest.raises(gen_notices.PinNotFound):
        gen_notices.fetched_binaries(repo)


def test_a_moved_pin_changes_the_rendered_notice():
    """What makes --check fail when a pin moves and the notice does not."""
    rows = gen_notices.fetched_binaries()
    moved = [dict(r) for r in rows]
    moved[0]["sha256"] = "0" * 64
    before = gen_notices.render({"companion": [PKG]}, [], "x", rows)
    after = gen_notices.render({"companion": [PKG]}, [], "x", moved)
    assert "## Binaries the installer fetches" in before
    assert before != after
    # ...and it is in the GENERATED half, never inside the hand block.
    assert before.index("## Binaries the installer fetches") < before.index(
        gen_notices.BEGIN_SENTINEL + "\n")


# ------------------------------------------------------------------ LG-12

def test_the_companion_runtime_set_is_the_lock_minus_dev():
    graph = gen_notices.lock_graph(REPO / "companion" / "requirements.lock")
    label, _lock, roots, _extras, _embeds = gen_notices.FROZEN[0]
    assert label == "companion"
    closure = gen_notices.runtime_closure(graph, roots())
    assert "psycopg2-binary" in closure          # LG-11
    assert "packaging" in closure                # via onnxruntime
    assert "pyobjc-core" in closure              # via the tray extra
    for dev_only in ("pytest", "pluggy", "iniconfig", "colorama", "pygments"):
        assert dev_only not in closure


def test_a_root_missing_from_the_lock_is_refused():
    with pytest.raises(SystemExit):
        gen_notices.runtime_closure({"a": ("1", {"<project>"})}, {"a", "b"})


def _site_with(tmp_path: Path) -> Path:
    site = tmp_path / "venv" / "Lib" / "site-packages"
    good = site / "goodpkg-1.0.dist-info"
    (good / "licenses").mkdir(parents=True)
    (good / "METADATA").write_text("Name: goodpkg\nVersion: 1.0\nLicense: MIT\n\n",
                                   encoding="utf-8")
    (good / "licenses" / "LICENSE").write_text("MIT text\n", encoding="utf-8")
    bare = site / "barepkg-2.0.dist-info"
    bare.mkdir()
    (bare / "METADATA").write_text("Name: barepkg\nVersion: 2.0\n\n", encoding="utf-8")
    (bare / "RECORD").write_text(
        "barepkg/copying.cpython-312-darwin.so,,\nbarepkg/__init__.py,,\n",
        encoding="utf-8")
    (site / "barepkg").mkdir()
    (site / "barepkg" / "copying.cpython-312-darwin.so").write_bytes(b"\x00ELF")
    return site


def test_licence_files_are_read_from_the_dist_info(tmp_path):
    site = _site_with(tmp_path)
    version, texts = gen_notices.dist_licence_texts(site, "goodpkg")
    assert version == "1.0"
    assert texts == [("goodpkg-1.0.dist-info/licenses/LICENSE", "MIT text\n")]


def test_a_compiled_file_named_copying_is_not_a_licence(tmp_path):
    """pyobjc's test suite ships copying.cpython-312-darwin.so."""
    site = _site_with(tmp_path)
    assert gen_notices.dist_licence_texts(site, "barepkg") == ("2.0", [])


def test_write_texts_bundles_extras_then_dists_and_says_what_is_missing(
        tmp_path, monkeypatch):
    site = _site_with(tmp_path)
    assert site.exists()
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "goodpkg==1.0 \\\n    # via demo (pyproject.toml)\n"
        "barepkg==2.0 \\\n    # via goodpkg\n", encoding="utf-8")
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "cpython.txt").write_text("CPython 3.12\n============\nPSF\n",
                                       encoding="utf-8")
    monkeypatch.setattr(gen_notices, "EXTRA_DIR", extra)
    monkeypatch.setattr(gen_notices, "DIST_FALLBACK_DIR", tmp_path / "nofallback")
    monkeypatch.setattr(gen_notices, "REPO", tmp_path)
    monkeypatch.setattr(gen_notices, "FROZEN", [
        ("demo", lock, lambda: {"goodpkg"}, ("cpython.txt",), ())])
    monkeypatch.setattr(gen_notices, "VENV_OVERRIDES", {"demo": tmp_path / "venv"})
    out = tmp_path / "licenses"
    (out / "demo").mkdir(parents=True)
    (out / "demo" / "goodpkg-0.9.txt").write_text("stale", encoding="utf-8")
    (out / "demo" / gen_notices.BUNDLE_NAME).write_text(
        "the committed bundle\n", encoding="utf-8")

    warnings = gen_notices.write_texts(out)

    # Review round 2026-09-25: one missing text writes NOTHING for the
    # component. The old code wrote goodpkg's text, deleted the stale file
    # and rewrote the bundle without barepkg -- a bundle the specs accept.
    assert any("barepkg 2.0: NO TEXT" in w for w in warnings)
    assert any("NOTHING WRITTEN" in w for w in warnings)
    assert not (out / "demo" / "goodpkg-1.0.txt").exists()
    assert (out / "demo" / "goodpkg-0.9.txt").exists()
    assert (out / "demo" / gen_notices.BUNDLE_NAME).read_text(
        encoding="utf-8") == "the committed bundle\n"

    # A wheel with no licence file takes its text from the fallback dir, and
    # then the whole component is written.
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    (fallback / "barepkg.txt").write_text("the bare licence\n", encoding="utf-8")
    monkeypatch.setattr(gen_notices, "DIST_FALLBACK_DIR", fallback)
    assert gen_notices.write_texts(out) == []
    assert "the bare licence" in (out / "demo" / "barepkg-2.0.txt").read_text(
        encoding="utf-8")
    assert (out / "demo" / "goodpkg-1.0.txt").exists()
    assert not (out / "demo" / "goodpkg-0.9.txt").exists()   # stale removed
    bundle = (out / "demo" / gen_notices.BUNDLE_NAME).read_text(encoding="utf-8")
    assert bundle.index("CPython 3.12") < bundle.index("goodpkg 1.0")
    assert "MIT text" in bundle and "  - barepkg 2.0" in bundle


def test_a_binary_that_embeds_another_carries_its_texts(tmp_path, monkeypatch):
    """Review round 2026-09-25: onboard.exe carries the whole companion exe
    (COMPANION_EXE in build_onboard.spec), so its bundle must carry the
    companion's distribution texts -- and must not be written at all when
    the companion's could not be."""
    site = _site_with(tmp_path)
    assert site.exists()
    lock = tmp_path / "requirements.lock"
    lock.write_text("goodpkg==1.0 \\\n    # via demo (pyproject.toml)\n",
                    encoding="utf-8")
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "cpython.txt").write_text("CPython 3.12\n", encoding="utf-8")
    monkeypatch.setattr(gen_notices, "EXTRA_DIR", extra)
    monkeypatch.setattr(gen_notices, "REPO", tmp_path)
    frozen = [("app", lock, lambda: {"goodpkg"}, ("cpython.txt",), ()),
              ("wizard", tmp_path / "wizard.lock", lambda: set(),
               ("cpython.txt",), ("app",))]
    monkeypatch.setattr(gen_notices, "FROZEN", frozen)
    monkeypatch.setattr(gen_notices, "VENV_OVERRIDES", {
        "app": tmp_path / "venv", "wizard": tmp_path / "venv"})
    out = tmp_path / "licenses"

    assert gen_notices.write_texts(out) == []
    wizard = (out / "wizard" / gen_notices.BUNDLE_NAME).read_text(encoding="utf-8")
    assert "  - goodpkg 1.0" in wizard and "MIT text" in wizard
    assert "program it" in wizard            # the intro says why
    assert not (out / "wizard" / "goodpkg-1.0.txt").exists()  # no duplicate file

    # The embedded component's text goes missing: neither bundle is rewritten.
    (out / "wizard" / gen_notices.BUNDLE_NAME).write_text("kept\n", encoding="utf-8")
    monkeypatch.setattr(gen_notices, "VENV_OVERRIDES", {
        "app": tmp_path / "empty", "wizard": tmp_path / "empty"})
    (out / "app" / "goodpkg-1.0.txt").unlink()
    warnings = gen_notices.write_texts(out)
    assert any("wizard: NO TEXT for the embedded app" in w for w in warnings)
    assert (out / "wizard" / gen_notices.BUNDLE_NAME).read_text(
        encoding="utf-8") == "kept\n"


def test_a_venv_outside_the_repo_is_never_printed_absolute(tmp_path):
    """Review round 2026-09-25: THIRD_PARTY_NOTICES.md is bundled into every
    binary, and `--venv companion=<scratch>` used to put the scratch path in
    it verbatim."""
    shown = gen_notices.shown_path(tmp_path / "scratch-venv")
    assert shown == "<outside the repository>/scratch-venv"
    assert str(tmp_path) not in shown


def test_the_committed_bundles_exist_and_carry_psycopg2_and_libpq():
    """companion/build.spec and the onboarding specs refuse to build without
    these; regenerate with `python tools/gen_notices.py --write-texts`."""
    companion = (REPO / "docs" / "legal" / "licenses" / "companion"
                 / gen_notices.BUNDLE_NAME).read_text(encoding="utf-8")
    for title in ("PyInstaller bootloader", "CPython 3.12", "Tcl/Tk 8.6",
                  "OpenSSL 3", "libpq (PostgreSQL client library)",
                  "psycopg2-binary 2.9.", "pyobjc-core 12."):
        assert f"  - {title}" in companion, title
    onboarding = (REPO / "docs" / "legal" / "licenses" / "onboarding"
                  / gen_notices.BUNDLE_NAME).read_text(encoding="utf-8")
    # The wizard carries the companion executable, so everything the
    # companion conveys is in its bundle too (review round 2026-09-25).
    for title in ("CPython 3.12", "libpq (PostgreSQL client library)",
                  "psycopg2-binary 2.9.", "numpy ", "onnxruntime "):
        assert f"  - {title}" in onboarding, title
    companion_titles = [line for line in companion.splitlines()
                        if line.startswith("  - ")]
    for line in companion_titles:
        assert line in onboarding, line


def test_the_wizard_row_embeds_the_companion():
    rows = {row[0]: row for row in gen_notices.FROZEN}
    assert rows["onboarding"][4] == ("companion",)
    assert "libpq.txt" in rows["onboarding"][3]
    labels = [row[0] for row in gen_notices.FROZEN]
    assert labels.index("companion") < labels.index("onboarding")


@pytest.mark.parametrize("spec,dest", [
    ("companion/build.spec", '"ccsync_companion/assets"'),
    ("onboarding/build_onboard.spec", '"assets"'),
    ("onboarding/build_onboard_macos.spec", '"assets"'),
])
def test_every_spec_bundles_the_licence_texts(spec, dest):
    text = (REPO / spec).read_text(encoding="utf-8")
    assert "THIRD_PARTY_LICENSES.txt" in text
    assert "THIRD_PARTY_NOTICES.md" in text
    assert "gen_notices.py --write-texts" in text   # the refusal names the fix
    assert dest in text
