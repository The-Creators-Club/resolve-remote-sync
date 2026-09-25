"""Tests for tools/scan_frozen.py -- LG-11 (docs/LEGAL_GAP_FEATURES_PLAN.md
section 4.5, 2026-09-25).

THIRD_PARTY_NOTICES promises that "a release build fails if it freezes a
package that list does not name". These pin that failure against fixture
PyInstaller TOCs: a real build is minutes and needs PyInstaller, but the
TOC format (Python literals of (dest, source, typecode) triples) and the
.dist-info RECORD that owns each source file are all the scan reads.

The last class checks the REAL build.spec against the REAL lock: every hidden
import must be satisfiable from companion/requirements.lock. psycopg2 was a
hidden import from 2026-08-31 to 2026-09-25 with no row in the lock, which is
the whole of LG-11. (The plan puts this test in the companion suite; it
lives here because it reads only tools/ and two text files, and G6 owns this
file.)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scan_frozen  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------- fixtures

def _dist(site: Path, name: str, version: str, files: list[str],
          licence: str = "MIT") -> None:
    info = site / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        f"License: {licence}\n\n", encoding="utf-8")
    rows = [f"{f},sha256=x,1" for f in files]
    rows.append(f"{info.name}/METADATA,,")
    rows.append(f"{info.name}/RECORD,,")
    (info / "RECORD").write_text("\n".join(rows) + "\n", encoding="utf-8")
    for rel in files:
        path = site / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


def _toc(workpath: Path, entries: list[tuple[str, str, str]]) -> None:
    workpath.mkdir(parents=True, exist_ok=True)
    # PKG-00.toc's real shape: (path, {options}, [entries], ...).
    (workpath / "PKG-00.toc").write_text(
        repr((str(workpath / "x.pkg"), {"PYZ": False}, entries, "x", False)),
        encoding="utf-8")


def _world(tmp_path: Path, lock_names: list[str]):
    site = tmp_path / "venv" / "Lib" / "site-packages"
    site.mkdir(parents=True)
    lock = tmp_path / "requirements.lock"
    lock.write_text("".join(f"{n}==1.0 \\\n    --hash=sha256:aa\n"
                            for n in lock_names), encoding="utf-8")
    component = scan_frozen.Component(
        label="companion", lock=lock,
        first_party=frozenset({"ccsync-companion"}),
        default_workpath=tmp_path / "work")
    return site, component


def _scan(component, tmp_path, allow=None):
    old = scan_frozen.REPO
    scan_frozen.REPO = tmp_path
    try:
        return scan_frozen.scan(component, tmp_path / "work",
                                allowlist=allow if allow is not None else {})
    finally:
        scan_frozen.REPO = old


# ------------------------------------------------------------------ tests

class TestTheLockIsTheList:
    def test_a_frozen_package_in_the_lock_passes(self, tmp_path):
        site, component = _world(tmp_path, ["watchdog"])
        _dist(site, "watchdog", "1.0", ["watchdog/__init__.py"])
        _toc(tmp_path / "work", [
            ("watchdog", str(site / "watchdog" / "__init__.py"), "PYMODULE"),
            # stdlib and first-party sources are not in site-packages at all
            ("json", str(tmp_path / "Python312" / "Lib" / "json.py"), "PYMODULE"),
        ])
        result = _scan(component, tmp_path)
        assert result.failures == []
        assert set(result.frozen) == {"watchdog"}

    def test_a_frozen_package_not_in_the_lock_fails(self, tmp_path):
        """setuptools, measured 2026-09-25: PyInstaller's own dependency,
        frozen because config.py's dead `import tomli` resolved to its
        vendored copy."""
        site, component = _world(tmp_path, ["watchdog"])
        _dist(site, "setuptools", "84.0.0", ["setuptools/__init__.py"])
        _toc(tmp_path / "work", [
            ("setuptools", str(site / "setuptools" / "__init__.py"), "PYMODULE")])
        result = _scan(component, tmp_path)
        assert len(result.failures) == 1
        assert "setuptools" in result.failures[0]
        assert "does not name" in result.failures[0]

    def test_lock_names_are_pep503_normalised(self, tmp_path):
        site, component = _world(tmp_path, ["python-dateutil"])
        _dist(site, "python_dateutil", "1.0", ["dateutil/parser.py"])
        _toc(tmp_path / "work", [
            ("dateutil.parser", str(site / "dateutil" / "parser.py"), "PYMODULE")])
        assert _scan(component, tmp_path).failures == []

    def test_a_binary_carried_by_a_wheel_is_owned_by_that_wheel(self, tmp_path):
        """libpq sits in psycopg2_binary.libs/, outside the package dir; the
        RECORD still names it, and that is what attributes it."""
        site, component = _world(tmp_path, ["psycopg2-binary"])
        _dist(site, "psycopg2-binary", "2.9.13",
              ["psycopg2_binary.libs/libpq-57ae.dll"])
        _toc(tmp_path / "work", [
            ("libpq-57ae.dll", str(site / "psycopg2_binary.libs" / "libpq-57ae.dll"),
             "BINARY")])
        result = _scan(component, tmp_path)
        assert set(result.frozen) == {"psycopg2-binary"}


class TestCopyleftNeedsTheComponentAsATarget:
    LGPL = "GNU Library or Lesser General Public License (LGPL)"

    def _psycopg(self, tmp_path):
        site, component = _world(tmp_path, ["psycopg2-binary"])
        _dist(site, "psycopg2-binary", "2.9.13", ["psycopg2/_psycopg.pyd"],
              licence="LGPL with exceptions")
        _toc(tmp_path / "work", [
            ("psycopg2._psycopg", str(site / "psycopg2" / "_psycopg.pyd"),
             "EXTENSION")])
        return component

    def test_lgpl_with_no_entry_fails(self, tmp_path):
        result = _scan(self._psycopg(tmp_path), tmp_path, allow={})
        assert any("LGPL" in f for f in result.failures)

    def test_lgpl_allowlisted_only_for_the_container_fails(self, tmp_path):
        """The shape the allowlist had until 2026-09-25."""
        allow = {"psycopg2-binary": {"targets": ["dashboard-container"],
                                     "reason": "container only"}}
        result = _scan(self._psycopg(tmp_path), tmp_path, allow=allow)
        assert any("'companion'" in f for f in result.failures)

    def test_lgpl_allowlisted_for_the_component_passes(self, tmp_path):
        allow = {"psycopg2-binary": {
            "targets": ["dashboard-container", "companion"], "reason": "why"}}
        result = _scan(self._psycopg(tmp_path), tmp_path, allow=allow)
        assert result.failures == []

    def test_an_entry_without_a_reason_is_not_an_excuse(self, tmp_path):
        allow = {"psycopg2-binary": {"targets": ["companion"]}}
        result = _scan(self._psycopg(tmp_path), tmp_path, allow=allow)
        assert result.failures


class TestNothingPassesOnTrust:
    def test_the_freezer_itself_is_exempt(self, tmp_path):
        site, component = _world(tmp_path, [])
        _dist(site, "pyinstaller", "6.21.0",
              ["PyInstaller/hooks/rthooks/pyi_rth_inspect.py"],
              licence="GPL-2.0-or-later WITH Bootloader-exception")
        _toc(tmp_path / "work", [
            ("pyi_rth_inspect",
             str(site / "PyInstaller" / "hooks" / "rthooks" / "pyi_rth_inspect.py"),
             "PYSOURCE")])
        assert _scan(component, tmp_path).failures == []

    def test_a_site_packages_file_no_record_claims_fails(self, tmp_path):
        site, component = _world(tmp_path, [])
        stray = site / "mystery.py"
        stray.write_text("", encoding="utf-8")
        _toc(tmp_path / "work", [("mystery", str(stray), "PYMODULE")])
        result = _scan(component, tmp_path)
        assert any("no installed distribution" in f for f in result.failures)

    def test_no_toc_is_cannot_scan_not_ok(self, tmp_path):
        _site, component = _world(tmp_path, [])
        (tmp_path / "work").mkdir()
        with pytest.raises(SystemExit) as exc:
            _scan(component, tmp_path)
        assert exc.value.code == 2

    def test_main_exit_codes(self, tmp_path, monkeypatch, capsys):
        site, component = _world(tmp_path, [])
        _dist(site, "numpy", "2.5.2", ["numpy/__init__.py"])
        _toc(tmp_path / "work", [
            ("numpy", str(site / "numpy" / "__init__.py"), "PYMODULE")])
        monkeypatch.setitem(scan_frozen.COMPONENTS, "companion", component)
        monkeypatch.setattr(scan_frozen, "REPO", tmp_path)
        monkeypatch.setattr(scan_frozen, "load_allowlist", lambda: {})
        assert scan_frozen.main(["--component", "companion",
                                 "--workpath", str(tmp_path / "work")]) == 1
        assert "[scan_frozen] FAIL" in capsys.readouterr().out
        assert scan_frozen.main(["--component", "companion",
                                 "--workpath", str(tmp_path / "nowhere")]) == 2


class TestTheTextsTravelWithTheBinary:
    """Review round 2026-09-25 (LG-12). The specs only tested that the
    bundle EXISTS and gen_notices --check never reads docs/legal/licenses/,
    so a lock bump without --write-texts shipped the old version's text, or
    none for a new dependency, and every check passed."""

    def _build(self, tmp_path, bundle_lines, text_files, embeds=(),
               embedded_bundle=None):
        site, component = _world(tmp_path, ["numpy"])
        texts = tmp_path / "licenses" / "companion"
        texts.mkdir(parents=True)
        for name in text_files:
            (texts / name).write_text("text", encoding="utf-8")
        if embedded_bundle is not None:
            (tmp_path / "licenses" / "other").mkdir()
            (tmp_path / "licenses" / "other" / scan_frozen.BUNDLE_NAME).write_text(
                "Contents:\n" + "".join(f"  - {t}\n" for t in embedded_bundle)
                + "\n", encoding="utf-8")
        component = scan_frozen.Component(
            label=component.label, lock=component.lock,
            first_party=component.first_party,
            default_workpath=component.default_workpath,
            texts_dir=texts, embeds=embeds)
        _dist(site, "numpy", "2.5.3", ["numpy/__init__.py"])
        entries = [("numpy", str(site / "numpy" / "__init__.py"), "PYMODULE")]
        if bundle_lines is not None:
            bundle = tmp_path / "bundle" / scan_frozen.BUNDLE_NAME
            bundle.parent.mkdir()
            bundle.write_text("Third-party licences\n\nContents:\n"
                              + "".join(f"  - {t}\n" for t in bundle_lines)
                              + "\n=====\n", encoding="utf-8")
            entries.append(("ccsync_companion\\assets\\THIRD_PARTY_LICENSES.txt",
                            str(bundle), "DATA"))
        _toc(tmp_path / "work", entries)
        return component

    def test_a_current_text_and_bundle_line_pass(self, tmp_path):
        component = self._build(tmp_path, ["CPython 3.12", "numpy 2.5.3"],
                                ["numpy-2.5.3.txt"])
        assert _scan(component, tmp_path).failures == []

    def test_a_lock_bump_without_write_texts_fails(self, tmp_path):
        """numpy 2.5.2 -> 2.5.3 in the venv; the committed texts still say
        2.5.2."""
        component = self._build(tmp_path, ["numpy 2.5.2"], ["numpy-2.5.2.txt"])
        failures = _scan(component, tmp_path).failures
        assert any("numpy-2.5.3.txt does not exist" in f for f in failures)
        assert any("does not list it" in f for f in failures)

    def test_a_build_with_no_bundle_fails(self, tmp_path):
        component = self._build(tmp_path, None, ["numpy-2.5.3.txt"])
        failures = _scan(component, tmp_path).failures
        assert any("carries no THIRD_PARTY_LICENSES.txt" in f for f in failures)

    def test_an_embedding_binary_must_list_the_embedded_texts(self, tmp_path):
        component = self._build(
            tmp_path, ["numpy 2.5.3", "CPython 3.12"], ["numpy-2.5.3.txt"],
            embeds=("other",),
            embedded_bundle=["CPython 3.12", "psycopg2-binary 2.9.13"])
        failures = _scan(component, tmp_path).failures
        assert len(failures) == 1
        assert "psycopg2-binary 2.9.13" in failures[0]

    def test_bundle_contents_parser(self):
        text = "x\n\nContents:\n  - A 1\n  - B 2\n\n====\n  - not me\n"
        assert scan_frozen.bundle_contents(text) == ["A 1", "B 2"]


class TestTheRealTree:
    def test_every_real_component_checks_its_texts(self):
        for label, component in scan_frozen.COMPONENTS.items():
            assert component.texts_dir == scan_frozen.LICENSES_DIR / label
        assert scan_frozen.COMPONENTS["onboarding"].embeds == ("companion",)

    def test_release_ps1_scans_the_real_workpath(self):
        """Review round 2026-09-25: the workpath was written `build<BS>uild`
        with a literal backspace byte (0x08), so the scan found no TOC, exited
        2, and every Windows release stopped before signing."""
        raw = (REPO / "tools" / "release.ps1").read_bytes()
        controls = sorted({b for b in raw if b < 0x20 and b not in (9, 10, 13)})
        assert controls == [], f"control bytes in release.ps1: {controls}"
        text = raw.decode("utf-8")
        assert '"--workpath", (Join-Path $CompanionDir "build\\build")' in text

    @pytest.mark.parametrize("path", [
        "tools/release_macos.sh", "tools/build_onboard_macos.sh",
        ".github/workflows/release-windows.yml", "tools/scan_frozen.py",
        "tools/gen_notices.py", "companion/build.spec",
        "onboarding/build_onboard.spec", "onboarding/build_onboard_macos.spec",
        # ship.cmd's own build path, scanned since the final review (2026-09-25)
        # put the same workpath argument in it and hit the same 0x08 (a backspace).
        "installer/build_editor_package.ps1",
    ])
    def test_no_control_bytes_in_the_other_release_files(self, path):
        raw = (REPO / path).read_bytes()
        assert not {b for b in raw if b < 0x20 and b not in (9, 10, 13)}, path

    def test_every_scan_call_names_its_components_workpath(self):
        """Each workpath is build/<spec name>: a wrong one is exit 2 at
        release time, never at test time."""
        calls = {
            "tools/release_macos.sh": ("companion", "build/build"),
            "tools/build_onboard_macos.sh": ("onboarding", "build/build_onboard_macos"),
            ".github/workflows/release-windows.yml": (
                "onboarding", "onboarding/build/build_onboard"),
        }
        for path, (component, workpath) in calls.items():
            text = (REPO / path).read_text(encoding="utf-8")
            assert f"scan_frozen.py --component {component}" in text or (
                "scan_frozen.py" in text and f"--component {component}" in text), path
            assert workpath in text, (path, workpath)


    def test_every_build_spec_hidden_import_is_satisfiable_from_the_lock(self):
        spec = REPO / "companion" / "build.spec"
        locked = scan_frozen.lock_names(REPO / "companion" / "requirements.lock")
        stdlib = set(sys.stdlib_module_names)
        unmapped, missing = [], []
        for name in scan_frozen.spec_hidden_imports(spec):
            top = name.split(".")[0]
            if top in stdlib or top == "ccsync_companion":
                continue
            dist = scan_frozen.IMPORT_TO_DIST.get(top)
            if dist is None:
                unmapped.append(name)
            elif dist not in locked:
                missing.append(f"{name} -> {dist}")
        assert not unmapped, (
            f"build.spec hidden imports with no IMPORT_TO_DIST row in "
            f"tools/scan_frozen.py: {unmapped}")
        assert not missing, (
            f"build.spec hidden imports whose distribution is not in "
            f"companion/requirements.lock (relock, docs/RELEASE.md): {missing}")

    def test_the_parser_sees_psycopg2_in_the_spec(self):
        """Guards the test above against passing because it read nothing."""
        names = scan_frozen.spec_hidden_imports(REPO / "companion" / "build.spec")
        assert "psycopg2" in names and "pg8000.native" in names

    @pytest.mark.parametrize("spec", ["build_onboard.spec", "build_onboard_macos.spec"])
    def test_the_wizard_hidden_imports_are_all_first_party(self, spec):
        names = scan_frozen.spec_hidden_imports(REPO / "onboarding" / spec)
        assert names
        assert all(n.split(".")[0] == "ccsync_companion" for n in names)

    def test_the_allowlist_names_the_companion_for_psycopg2(self):
        """Without this every companion build fails the scan (D6)."""
        entry = scan_frozen.load_allowlist()["psycopg2-binary"]
        assert "companion" in entry["targets"]
        assert "dashboard-container" in entry["targets"]
        assert entry["reason"].strip()

    def test_psycopg2_is_in_the_companion_lock_for_both_platforms(self):
        text = (REPO / "companion" / "requirements.lock").read_text(encoding="utf-8")
        head = next(line for line in text.splitlines()
                    if line.startswith("psycopg2-binary=="))
        # No marker: one lock feeds the Windows exe and the Mac binary.
        assert ";" not in head

    def test_every_component_lock_exists(self):
        for component in scan_frozen.COMPONENTS.values():
            assert component.lock.exists(), component.lock
