"""Windows version resource for the two frozen exes (CR-373, GL-30, 2026-10-07).

Without a VERSIONINFO resource Explorer's Details tab and SmartScreen's
"More info" show a blank file description and no product; with one, an
UNSIGNED beta build at least names itself truthfully. CompanyName and
LegalCopyright default to the vendor legal entity the owner settled on
2026-10-07 (GL-35/GL-41: "Cablewrap Creative Ltd signs and contracts"); only
the certificate purchase is deferred by the unsigned-beta decision.
CCSYNC_LEGAL_ENTITY overrides it at build time. This is the vendor, not a
customer, so "No customer's name in code" does not apply. The Apps & features
Publisher in installer/windows_bootstrap.ps1 uses the same value.

Stdlib only: both PyInstaller specs import it by path, and it must not need
the companion package importable. PyInstaller's `version=` takes the TEXT of
a VSVersionInfo file, which this renders.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

PRODUCT_NAME = "CC Sync"
VENDOR_LEGAL_ENTITY = "Cablewrap Creative Ltd"


def legal_entity() -> str:
    return (os.environ.get("CCSYNC_LEGAL_ENTITY") or "").strip() or VENDOR_LEGAL_ENTITY


def version_tuple(version: str) -> tuple[int, int, int, int]:
    """'0.9.85' -> (0, 9, 85, 0); anything non-numeric counts as 0."""
    nums = []
    for part in re.split(r"[.+\-]", str(version))[:4]:
        m = re.match(r"\d+", part)
        nums.append(int(m.group(0)) if m else 0)
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums[:4])  # type: ignore[return-value]


def read_assigned_version(path: Path, name: str) -> str:
    """The string literal assigned to `name` in a source file, without
    importing it (the specs run before the package is importable)."""
    m = re.search(rf'^{re.escape(name)}\s*=\s*["\']([^"\']+)["\']',
                  Path(path).read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "0.0.0"


def render(version: str, file_description: str, internal_name: str,
           original_filename: str) -> str:
    """The text of a PyInstaller version file."""
    v = version_tuple(version)
    company = legal_entity()
    year = 2026
    copyright_ = f"Copyright (c) {year} {company}"
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v!r},
    prodvers={v!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', {company!r}),
         StringStruct('FileDescription', {file_description!r}),
         StringStruct('FileVersion', {version!r}),
         StringStruct('InternalName', {internal_name!r}),
         StringStruct('LegalCopyright', {copyright_!r}),
         StringStruct('OriginalFilename', {original_filename!r}),
         StringStruct('ProductName', {PRODUCT_NAME!r}),
         StringStruct('ProductVersion', {version!r})])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def write(dest: Path, **kw) -> str:
    """Render to `dest` and return its path as a string (what EXE(version=)
    takes)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render(**kw), encoding="utf-8")
    return str(dest)
