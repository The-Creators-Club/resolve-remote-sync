#!/usr/bin/env python3
"""Fail a release build that froze a package its lock does not name.

LG-11 (docs/LEGAL_GAP_FEATURES_PLAN.md section 4.5, 2026-09-25). Until this
existed, `tools/release.ps1` built the Windows companion from `pip install -e
.` while CI and the vendor feed built it from `companion/requirements.lock`,
and `psycopg2-binary` was in pyproject.toml and build.spec but not in the lock
-- so ship.cmd builds and feed builds were different bytes, the feed builds'
Cards role failed with "No module named 'psycopg2'", and
`tools/check_licenses.py` (which reads the lock) could not see an LGPL
package that the base-rig build froze. THIRD_PARTY_NOTICES now promises that
"a release build fails if it freezes a package that list does not name";
this script is that failure.

    python tools/scan_frozen.py --component companion  --workpath companion/build/build
    python tools/scan_frozen.py --component onboarding --workpath onboarding/build/build_onboard

WHAT IT READS. The TOC files PyInstaller leaves in its workpath (`PKG-00.toc`,
`PYZ-00.toc`, `COLLECT-00.toc` for a onedir build, ...). They are Python
literals, and every frozen file appears in them as a `(dest, source, typecode)`
triple. A source path inside a `site-packages` directory is owned by exactly
one installed distribution, and that distribution's `*.dist-info/RECORD` says
so -- so the answer to "which distributions went into this binary" is read
off the build, not guessed from import names.

WHAT FAILS (exit 1):
  * a frozen distribution the component's lock does not name (markers
    ignored: a package locked for another platform is still locked);
  * a frozen distribution whose own metadata reads copyleft (LGPL/GPL/AGPL/
    SSPL, check_licenses.verdict) unless tools/license_allowlist.toml has an
    entry for it with a `reason` whose `targets` name this component (or has
    no `targets`). psycopg2-binary passes in the companion only because its
    entry names `companion` (decision D6);
  * a file under site-packages that no installed distribution's RECORD
    claims -- a build whose provenance cannot be read is not passed on trust;
  * (LG-12, review round 2026-09-25) a judged distribution with no committed
    docs/legal/licenses/<component>/<name>-<version>.txt at the version
    FROZEN, or missing from the Contents list of the THIRD_PARTY_LICENSES.txt
    the build froze; a build that froze no such bundle at all; and, for the
    wizard, a bundle that does not list every text of the companion
    executable it carries.

Exit 2 when there is nothing to scan (no workpath, no TOC, a TOC that does not
parse): a scan that found nothing must never look like a scan that passed.

EXEMPT, on purpose: the freezer itself (`pyinstaller`,
`pyinstaller-hooks-contrib`). What of it lands in the binary is the bootloader
and the runtime hooks, conveyed under the GPL's Bootloader exception, which
exists for exactly this; THIRD_PARTY_NOTICES carries its row. And the
component's own first-party distribution.

Stdlib only, like gen_notices.py and check_licenses.py: it runs under the
build venv's python, under a CI runner's python or under any python on the
base rig, and it reads files rather than importing what it judges.
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import re
import sys
import tomllib
from dataclasses import dataclass, field
from email.parser import HeaderParser
from pathlib import Path, PurePath

REPO = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
ALLOWLIST_PATH = TOOLS / "license_allowlist.toml"
LICENSES_DIR = REPO / "docs" / "legal" / "licenses"
BUNDLE_NAME = "THIRD_PARTY_LICENSES.txt"

sys.path.insert(0, str(TOOLS))
from check_licenses import NEEDS_JUSTIFICATION, normalize, verdict  # noqa: E402


@dataclass(frozen=True)
class Component:
    label: str            # the allowlist `targets` name
    lock: Path
    first_party: frozenset[str]
    default_workpath: Path
    # LG-12 texts (review round, 2026-09-25): docs/legal/licenses/<label>/,
    # where gen_notices.py --write-texts puts <name>-<version>.txt for every
    # distribution the binary conveys. None skips the texts check; only the
    # fixture components in tools/tests do that, and a test pins that every
    # real component sets it.
    texts_dir: Path | None = None
    # Components whose whole executable this one carries and installs (the
    # wizard carries the companion); its bundle must list their texts too.
    embeds: tuple[str, ...] = ()


# The onboarding wizard is frozen from the COMPANION's venv (release-windows.yml
# builds it with ../companion/.venv), but its own lock is the one judged: the
# wizard is stdlib + a handful of ccsync_companion modules
# (onboarding/requirements.in says so, and says a runtime dependency added
# there must be locked first), so a third-party wheel in onboard.exe is a leak
# out of the companion's venv, which is precisely what this is for.
COMPONENTS: dict[str, Component] = {
    "companion": Component(
        label="companion",
        lock=REPO / "companion" / "requirements.lock",
        first_party=frozenset({"ccsync-companion"}),
        default_workpath=REPO / "companion" / "build" / "build",
        texts_dir=LICENSES_DIR / "companion",
    ),
    "onboarding": Component(
        label="onboarding",
        lock=REPO / "onboarding" / "requirements.lock",
        first_party=frozenset({"ccsync-companion"}),
        default_workpath=REPO / "onboarding" / "build" / "build_onboard",
        texts_dir=LICENSES_DIR / "onboarding",
        embeds=("companion",),
    ),
}

BUILD_TOOLS = frozenset({"pyinstaller", "pyinstaller-hooks-contrib"})

# Import name -> distribution, for the hidden imports build.spec names by
# module. Only third-party top-level names appear here; stdlib and
# ccsync_companion are recognised without it. A hidden import whose top level
# is in neither is a test failure (tools/tests/test_scan_frozen.py) until a row
# is added, so this table cannot silently fall behind build.spec.
IMPORT_TO_DIST: dict[str, str] = {
    "watchdog": "watchdog",
    "PIL": "pillow",
    "numpy": "numpy",
    "onnxruntime": "onnxruntime",
    "psycopg2": "psycopg2-binary",
    "zstandard": "zstandard",
    "pg8000": "pg8000",
    "scramp": "scramp",
    "asn1crypto": "asn1crypto",
    "dateutil": "python-dateutil",
    "AppKit": "pyobjc-framework-cocoa",
    "Foundation": "pyobjc-framework-cocoa",
    "objc": "pyobjc-core",
}

_TOC_TYPECODES = frozenset({
    "PYMODULE", "PYSOURCE", "EXTENSION", "BINARY", "DATA", "DEPENDENCY",
    "SYMLINK", "ZIPFILE", "EXECUTABLE", "SPLASH",
})


def lock_names(path: Path) -> set[str]:
    """Every normalised name in a lock, whatever its marker."""
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        match = re.match(r"^([A-Za-z0-9._-]+)\s*==", line)
        if match:
            names.add(normalize(match.group(1)))
    return names


def read_tocs(workpath: Path) -> list[tuple[str, str, str]]:
    """Every (dest, source, typecode) triple in the workpath's TOC files.

    Raises SystemExit(2) when there is no TOC or one does not parse."""
    tocs = sorted(workpath.glob("*.toc")) if workpath.is_dir() else []
    if not tocs:
        raise SystemExit(_die(f"no PyInstaller TOC files in {workpath} -- "
                              f"did the build run, and with this --workpath?"))
    entries: list[tuple[str, str, str]] = []
    for toc in tocs:
        try:
            data = ast.literal_eval(toc.read_text(encoding="utf-8"))
        except (ValueError, SyntaxError, OSError) as exc:
            raise SystemExit(_die(f"{toc} did not parse as a TOC ({exc})"))
        _walk(data, entries)
    return entries


def _walk(node: object, out: list[tuple[str, str, str]]) -> None:
    if isinstance(node, tuple) and len(node) == 3 and all(
            isinstance(x, str) for x in node) and node[2] in _TOC_TYPECODES:
        out.append(node)  # type: ignore[arg-type]
        return
    if isinstance(node, (list, tuple)):
        for child in node:
            _walk(child, out)
    elif isinstance(node, dict):
        for child in node.values():
            _walk(child, out)


def site_packages_root(source: str) -> tuple[Path, str] | None:
    """(site-packages dir, path relative to it, '/'-separated) or None."""
    parts = PurePath(source).parts
    for i, part in enumerate(parts):
        if part.lower() == "site-packages":
            rel = "/".join(parts[i + 1:])
            return Path(*parts[:i + 1]), rel
    return None


@dataclass
class Dist:
    name: str            # as the metadata spells it
    version: str
    license: str
    files: set[str] = field(default_factory=set)


def _key(rel: str) -> str:
    # Windows paths compare case-insensitively; a RECORD written on one case
    # must still own the file the TOC names in another.
    return rel.replace("\\", "/").lower()


def index_site_packages(root: Path) -> dict[str, Dist]:
    """{relative file key: owning Dist} for one site-packages directory."""
    owners: dict[str, Dist] = {}
    for info in sorted(root.glob("*.dist-info")):
        meta_path = info / "METADATA"
        record_path = info / "RECORD"
        if not meta_path.exists() or not record_path.exists():
            continue
        meta = HeaderParser().parsestr(
            meta_path.read_text(encoding="utf-8", errors="replace"))
        dist = Dist(name=str(meta.get("Name", info.name.split("-")[0])),
                    version=str(meta.get("Version", "?")),
                    license=licence_string(meta))
        for row in csv.reader(io.StringIO(
                record_path.read_text(encoding="utf-8", errors="replace"))):
            if not row or row[0].startswith(".."):
                continue
            owners[_key(row[0])] = dist
    return owners


def licence_string(meta) -> str:
    """The licence a distribution declares, preferring the most specific
    field. Long `License:` values are licence TEXTS pasted into metadata, and
    are judged by their classifiers instead."""
    expression = str(meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    plain = str(meta.get("License") or "").strip()
    if plain and len(plain) < 120 and "\n" not in plain:
        return plain
    classifiers = [c.split("::")[-1].strip()
                   for c in (meta.get_all("Classifier") or [])
                   if c.startswith("License ::")]
    return "; ".join(classifiers) or plain[:120]


@dataclass
class Result:
    frozen: dict[str, Dist]
    failures: list[str]
    notes: list[str]


def scan(component: Component, workpath: Path,
         allowlist: dict | None = None) -> Result:
    entries = read_tocs(workpath)
    locked = lock_names(component.lock)
    allow = allowlist if allowlist is not None else load_allowlist()

    indexes: dict[Path, dict[str, Dist]] = {}
    frozen: dict[str, Dist] = {}
    unowned: set[str] = set()
    for _dest, source, _typecode in entries:
        located = site_packages_root(source)
        if located is None:
            continue
        root, rel = located
        if root not in indexes:
            indexes[root] = index_site_packages(root)
        owner = indexes[root].get(_key(rel))
        if owner is None:
            # PyInstaller reads a package's .py and records the .py; RECORD
            # may list only the .py too. A compiled-cache path is the one
            # shape that legitimately has no RECORD row of its own.
            if "__pycache__" in rel:
                continue
            unowned.add(f"{root}{'/' if rel else ''}{rel}")
            continue
        frozen[normalize(owner.name)] = owner

    failures: list[str] = []
    notes: list[str] = []
    for name in sorted(frozen):
        dist = frozen[name]
        if name in BUILD_TOOLS:
            notes.append(f"{name} {dist.version}: the freezer's bootloader and "
                         f"runtime hooks (Bootloader exception), not judged")
            continue
        if name in component.first_party:
            continue
        if name not in locked:
            failures.append(
                f"{name} {dist.version} is frozen into {component.label} but "
                f"{component.lock.relative_to(REPO).as_posix()} does not name "
                f"it. Either lock it (docs/RELEASE.md, 'Refreshing the "
                f"lockfiles') or stop it being frozen; a venv that holds "
                f"packages the lock does not is rebuilt from the lock "
                f"(delete the venv and re-run the release script).")
            continue
        kind = verdict(dist.license)
        if kind in NEEDS_JUSTIFICATION:
            entry = allow.get(name) or {}
            targets = entry.get("targets") or []
            applies = bool(entry) and (not targets or component.label in targets)
            if not applies or not entry.get("reason"):
                failures.append(
                    f"{name} {dist.version} is {kind} ({dist.license!r}) and "
                    f"frozen into {component.label}, but "
                    f"tools/license_allowlist.toml has no entry with a reason "
                    f"whose targets include {component.label!r}.")
                continue
            notes.append(f"{name} {dist.version}: {kind}, allowlisted for "
                         f"{component.label}")
        elif kind == "UNKNOWN":
            notes.append(f"{name} {dist.version}: licence not declared in its "
                         f"metadata (tools/check_licenses.py judges it from "
                         f"the lock)")
    for path in sorted(unowned):
        failures.append(f"{path} is frozen from site-packages but no installed "
                        f"distribution's RECORD claims it")
    if component.texts_dir is not None:
        judged = {n: d for n, d in frozen.items()
                  if n not in BUILD_TOOLS and n not in component.first_party
                  and n in locked}
        failures += check_texts(component, entries, judged)
    return Result(frozen=frozen, failures=failures, notes=notes)


def bundle_contents(text: str) -> list[str]:
    """The titles under a bundle's `Contents:` heading, as gen_notices.py
    writes them ("  - numpy 2.5.2")."""
    out: list[str] = []
    lines = text.splitlines()
    try:
        start = lines.index("Contents:") + 1
    except ValueError:
        return out
    for line in lines[start:]:
        if not line.startswith("  - "):
            break
        out.append(line[4:].strip())
    return out


def check_texts(component: Component, entries: list[tuple[str, str, str]],
                judged: dict[str, "Dist"]) -> list[str]:
    """LG-12, tied to the build (review round, 2026-09-25). The specs only
    tested that THIRD_PARTY_LICENSES.txt EXISTS and gen_notices --check never
    reads docs/legal/licenses/, so a lock bump without --write-texts built
    and shipped a binary carrying the old version's text, or none for a new
    dependency. This scan is the one place that knows the exact name and
    version frozen, so it is where that is refused: every judged
    distribution needs its committed <name>-<version>.txt AND a line in the
    bundle the build actually froze; a component that embeds another needs
    every line of that one's bundle too."""
    failures: list[str] = []
    rel = (component.texts_dir.relative_to(REPO).as_posix()
           if component.texts_dir.is_relative_to(REPO) else str(component.texts_dir))
    fix = "run `python tools/gen_notices.py --write-texts` and commit the result"
    bundles = sorted({source for dest, source, _t in entries
                      if PurePath(dest.replace("\\", "/")).name == BUNDLE_NAME})
    if not bundles:
        return [f"the build carries no {BUNDLE_NAME}: the licence texts do "
                f"not travel with this binary ({fix})"]
    contents: set[str] = set()
    for source in bundles:
        try:
            contents |= set(bundle_contents(Path(source).read_text(encoding="utf-8")))
        except OSError as exc:
            failures.append(f"cannot read the frozen {BUNDLE_NAME} at {source} ({exc})")
    for name in sorted(judged):
        dist = judged[name]
        title = f"{name} {dist.version}"
        if not (component.texts_dir / f"{name}-{dist.version}.txt").exists():
            failures.append(f"{title} is frozen into {component.label} but "
                            f"{rel}/{name}-{dist.version}.txt does not exist ({fix})")
        if title not in contents:
            failures.append(f"{title} is frozen into {component.label} but the "
                            f"{BUNDLE_NAME} it carries does not list it ({fix})")
    for other in component.embeds:
        theirs = component.texts_dir.parent / other / BUNDLE_NAME
        try:
            wanted = bundle_contents(theirs.read_text(encoding="utf-8"))
        except OSError:
            failures.append(f"{component.label} embeds {other}, whose {BUNDLE_NAME} "
                            f"is missing ({fix})")
            continue
        lacking = [t for t in wanted if t not in contents]
        if lacking:
            failures.append(f"{component.label} carries the {other} executable but "
                            f"its {BUNDLE_NAME} does not list {', '.join(lacking)} "
                            f"({fix})")
    return failures


def load_allowlist(path: Path = ALLOWLIST_PATH) -> dict:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8")).get("allow", {})


def _die(message: str) -> int:
    sys.stdout.write(f"[scan_frozen] CANNOT SCAN: {message}\n")
    return 2


def spec_hidden_imports(spec_path: Path) -> list[str]:
    """Every string build.spec feeds into `hidden_imports`, read with ast so
    a spec edit cannot hide one behind formatting."""
    tree = ast.parse(spec_path.read_text(encoding="utf-8"))
    found: list[str] = []

    def strings(node: ast.AST) -> list[str]:
        if isinstance(node, (ast.List, ast.Tuple)):
            return [e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "hidden_imports"
                for t in node.targets):
            found += strings(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(
                node.target, ast.Name) and node.target.id == "hidden_imports":
            found += strings(node.value)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == "append"
              and isinstance(node.func.value, ast.Name)
              and node.func.value.id == "hidden_imports"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append(arg.value)
        elif isinstance(node, ast.keyword) and node.arg == "hiddenimports":
            found += strings(node.value)
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--component", required=True, choices=sorted(COMPONENTS))
    ap.add_argument("--workpath", default=None,
                    help="PyInstaller's workpath for this build (default: the "
                         "component's usual build/<spec name> directory)")
    args = ap.parse_args(argv)

    component = COMPONENTS[args.component]
    workpath = Path(args.workpath) if args.workpath else component.default_workpath
    try:
        result = scan(component, workpath)
    except SystemExit as exc:
        return int(exc.code or 2)

    # ASCII only: a Windows runner's console is cp1252 (check_licenses.py).
    judged = [n for n in result.frozen
              if n not in BUILD_TOOLS and n not in component.first_party]
    print(f"[scan_frozen] {component.label}: {len(judged)} third-party "
          f"distribution(s) frozen, judged against "
          f"{component.lock.relative_to(REPO).as_posix()}")
    for name in sorted(judged):
        print(f"[scan_frozen]   {name} {result.frozen[name].version}")
    for note in result.notes:
        print(f"[scan_frozen] note: {note}")
    if result.failures:
        for failure in result.failures:
            print(f"[scan_frozen] FAIL: {failure}")
        print(f"[scan_frozen] FAILED: {len(result.failures)} problem(s); this "
              f"build must not be released.")
        return 1
    print(f"[scan_frozen] OK: every frozen distribution is in the lock and "
          f"its licence text travels with the binary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
