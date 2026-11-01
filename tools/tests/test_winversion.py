"""CR-373 / GL-30 (2026-10-07): the VERSIONINFO resource for the two frozen
exes, so an unsigned beta build names itself in Explorer and SmartScreen."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("winversion", ROOT / "tools" / "winversion.py")
wv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wv)


def test_version_tuple():
    assert wv.version_tuple("0.9.85") == (0, 9, 85, 0)
    assert wv.version_tuple("1.0.46+dirty") == (1, 0, 46, 0)
    assert wv.version_tuple("junk") == (0, 0, 0, 0)


def test_company_is_the_vendor_entity_unless_overridden(monkeypatch):
    monkeypatch.delenv("CCSYNC_LEGAL_ENTITY", raising=False)
    text = wv.render("0.9.85", "CC Sync companion", "ccsync-companion", "ccsync-companion.exe")
    assert "StringStruct('CompanyName', 'Cablewrap Creative Ltd')" in text
    assert "Copyright (c) 2026 Cablewrap Creative Ltd" in text
    assert "StringStruct('ProductName', 'CC Sync')" in text
    assert "StringStruct('FileVersion', '0.9.85')" in text
    monkeypatch.setenv("CCSYNC_LEGAL_ENTITY", "Example Co")
    assert "StringStruct('CompanyName', 'Example Co')" in wv.render(
        "1.0.0", "d", "i", "o.exe")


def test_rendered_text_is_a_valid_vsversioninfo_literal():
    text = wv.render("0.9.85", "CC Sync companion", "x", "x.exe")
    # PyInstaller evals it with these names in scope.
    ns = {n: (lambda *a, _n=n, **k: (_n, a, k)) for n in (
        "VSVersionInfo", "FixedFileInfo", "StringFileInfo", "StringTable",
        "StringStruct", "VarFileInfo", "VarStruct")}
    body = re.sub(r"^#.*\n", "", text)
    assert eval(body, ns)[0] == "VSVersionInfo"


def test_both_specs_wire_the_version_resource():
    comp = (ROOT / "companion" / "build.spec").read_text(encoding="utf-8")
    onb = (ROOT / "onboarding" / "build_onboard.spec").read_text(encoding="utf-8")
    assert "version=exe_version" in comp and "winversion" in comp
    assert "version=_version_file" in onb and "winversion" in onb


def test_reads_the_version_without_importing(tmp_path):
    f = tmp_path / "c.py"
    f.write_text('X = 1\nVERSION = "0.9.85"\n')
    assert wv.read_assigned_version(f, "VERSION") == "0.9.85"
    assert wv.read_assigned_version(f, "MISSING") == "0.0.0"
    assert wv.read_assigned_version(ROOT / "companion/src/ccsync_companion/config.py",
                                    "VERSION") != "0.0.0"
    assert wv.read_assigned_version(ROOT / "onboarding/steps.py",
                                    "INSTALLER_VERSION") != "0.0.0"


def test_apps_and_features_publisher_is_the_vendor_not_the_customer():
    # COM-M59 / GL-30: Publisher must not follow the site manifest's org_name.
    ps1 = (ROOT / "installer" / "windows_bootstrap.ps1").read_text(encoding="utf-8")
    assert f'$VendorPublisher = "{wv.VENDOR_LEGAL_ENTITY}"' in ps1
    assert "-Publisher $VendorPublisher" in ps1
    assert "-Publisher $(if ($brandOrg)" not in ps1
