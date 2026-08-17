#!/usr/bin/env python3
"""Licence gate for the SHIPPED components. Exit 1 on anything we may not convey.

COMMERCIAL_READINESS.md item 13 ("a licence gate"), 2026-08-17. The companion
doc is `docs/legal/THIRD_PARTY_NOTICES.md`, produced by `tools/gen_notices.py`:
that script INVENTORIES everything, for counsel; this one JUDGES the subset that
actually leaves the building, for CI.

    python tools\\check_licenses.py            # judge; exit 1 on a violation
    python tools\\check_licenses.py --strict   # also fail on packages we could not scan
    python tools\\check_licenses.py --json     # machine-readable, for a CI annotation

WHAT "SHIPPED" MEANS HERE, AND WHY IT IS NOT "EVERY VENV"

Only two artefacts reach a customer as our own product:

  companion            frozen into a single-file exe/app by companion/build.spec.
                       Static linking is the strong reading of copyleft, so this
                       is the strict target.
  dashboard-container  installed into the container venv by deploy/run.sh (or
                       baked by deploy/Dockerfile). Conveyed as a running
                       service on the customer's own NAS.

Everything else -- bench, the two indexers, the test extras -- runs on OUR
machines and is not conveyed. It is in the notices inventory and not in this
gate, deliberately: a gate that fails on a developer tool gets switched off.

WHERE THE PACKAGE LIST COMES FROM

The `requirements.lock` files, not `pip freeze`: the lock is the exact,
hash-pinned closure the artefact is built from, and a venv on a developer
machine has whatever else that developer installed. Markers are evaluated
against the TARGET platform, which is the whole reason it matters -- python-xlib
(pystray's Linux backend, LGPL) is in the companion lock and is never in a
Windows or macOS build, and colorama is never in the Linux container.

WHERE THE LICENCE STRINGS COME FROM

`pip-licenses` run inside each venv, via tools/gen_notices.py's helpers (one
implementation of "install pip-licenses on demand and read its JSON", not two).
That means a package in a lock but not installed in any scanned venv has no
licence string at all. Locally that is normal -- the macOS-only pyobjc wheels do
not install on the Windows base rig -- so it is a WARNING here and a FAILURE
under --strict, which is what CI runs after installing every lock.

THIS IS NOT LEGAL ADVICE. It is a mechanical check against package metadata,
and package metadata is frequently wrong. It exists to stop a NEW copyleft
dependency arriving unnoticed, which is a different job from being right about
the ones already known (see docs/legal/THIRD_PARTY_NOTICES.md for those).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = Path(__file__).resolve().parent / "license_allowlist.toml"

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from gen_notices import run_piplicenses, venv_python
except ImportError as exc:  # pragma: no cover - a broken checkout, not a state
    sys.stderr.write(
        f"check_licenses: cannot import tools/gen_notices.py ({exc}). The two "
        f"share one pip-licenses implementation on purpose; restore that file.\n")
    raise SystemExit(2)

# Substring match, upper-cased, against the metadata licence string. Ordered
# most-specific first: "GPL" matches "LGPL" and "AGPL" as substrings, so a plain
# GPL verdict must be the LAST thing tried or every LGPL package is reported as
# GPL. gen_notices.ATTENTION_LABELS solves the same problem the same way.
#
# The SPELLED-OUT names are not belt-and-braces. "GNU Affero General Public
# License v3" -- which is what several projects put in their metadata, verbatim
# -- contains neither "AGPL" nor "GPL" as a substring, so an acronym-only gate
# waves the single most restrictive licence in the list straight through. Found
# by tests/test_check_licenses.py, 2026-08-17.
DENY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AGPL", ("AGPL", "AFFERO")),
    ("SSPL", ("SSPL", "SERVER SIDE PUBLIC")),
    # "LESSER GENERAL PUBLIC" also matches inside a GPL string's own text, which
    # is why LGPL is tried before GPL and not after. "LIBRARY GENERAL PUBLIC" is
    # LGPLv2's original name and still appears in old metadata.
    ("LGPL", ("LGPL", "LESSER GENERAL PUBLIC", "LIBRARY GENERAL PUBLIC")),
    ("GPL", ("GPL", "GENERAL PUBLIC LICENSE", "GENERAL PUBLIC LICENCE")),
)
# Verdicts that are a hard no with no allowlist path at all. A copyleft licence
# CAN be shipped compliantly (dynamic linking, an offer of source); "we have no
# idea what this is" cannot.
UNKNOWN_STRINGS = ("UNKNOWN", "", "NONE")

# Licences that need a human decision but not a refusal: an LGPL entry is
# allowed ONLY with an explicit justification in the allowlist. AGPL/SSPL/GPL
# entries are allowed by the same mechanism but the allowlist file says, at
# length, why you should not.
NEEDS_JUSTIFICATION = ("LGPL", "GPL", "AGPL", "SSPL")


def normalize(name: str) -> str:
    """PEP 503 normalisation. `pip-licenses` says "pyobjc-framework-Cocoa" and a
    lock says "pyobjc-framework-cocoa"; without this they are two packages."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


# The marker environments the two targets are built for. Only the keys markers
# in these locks actually use are listed; packaging fills the rest with the
# running interpreter's values, which is right for python_version and wrong for
# nothing that appears here.
PLATFORM_ENVS = {
    "win32": {"sys_platform": "win32", "platform_system": "Windows",
              "os_name": "nt", "platform_machine": "AMD64"},
    "darwin": {"sys_platform": "darwin", "platform_system": "Darwin",
               "os_name": "posix", "platform_machine": "arm64"},
    "linux": {"sys_platform": "linux", "platform_system": "Linux",
              "os_name": "posix", "platform_machine": "x86_64"},
}


@dataclass
class Target:
    label: str
    lock: Path
    platforms: list[str]
    venvs: list[Path]
    why: str
    names: set[str] = field(default_factory=set)


TARGETS = [
    Target(
        label="companion",
        lock=REPO / "companion" / "requirements.lock",
        # Both, because one lock feeds two frozen builds and the macOS one is
        # produced on a Mac we do not have here (docs/RELEASE.md).
        platforms=["win32", "darwin"],
        venvs=[REPO / "companion" / ".venv"],
        why="frozen into ccsync-companion.exe / CCSync Companion.app "
            "(companion/build.spec) and self-updated onto every editor machine",
    ),
    Target(
        label="dashboard-container",
        lock=REPO / "dashboard" / "deploy" / "requirements.lock",
        platforms=["linux"],
        # The container's venv has no local twin, so the licence strings are
        # read from the venvs that DO have these packages. Names not found in
        # any of them come back unscanned rather than silently clean.
        venvs=[REPO / "dashboard" / ".venv",
               REPO / "music" / "web" / ".venv",
               REPO / "ytdl" / "web" / ".venv",
               Path("E:/Projects/broll-platform/web/.venv")],
        why="installed into the container venv by dashboard/deploy/run.sh, or "
            "baked in by dashboard/deploy/Dockerfile, and run on the customer's NAS",
    ),
]


def parse_lock(path: Path, platform: str) -> set[str]:
    """The normalised package names a lock installs on one platform.

    Reads the `name==version ; marker` heads and ignores the --hash continuation
    lines. Marker evaluation needs `packaging`; without it every marked package
    is INCLUDED, which errs towards over-reporting -- the safe direction for a
    gate.
    """
    try:
        from packaging.markers import Marker
    except ImportError:  # pragma: no cover - only on a bare interpreter
        Marker = None

    env = PLATFORM_ENVS[platform]
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip().rstrip("\\").strip()
        if not line or line.startswith("-"):
            continue
        head = re.match(r"^([A-Za-z0-9._-]+)\s*==\s*[^\s;]+\s*(?:;\s*(.*))?$", line)
        if not head:
            continue
        name, marker = head.group(1), (head.group(2) or "").strip()
        if marker and Marker is not None:
            try:
                if not Marker(marker).evaluate(env):
                    continue
            except Exception:  # noqa: BLE001 - an unparsable marker must not hide a package
                pass
        names.add(normalize(name))
    return names


def scan_venvs(venvs: list[Path]) -> tuple[dict[str, dict], list[str]]:
    """{normalised name: pip-licenses row} across every venv that exists."""
    rows: dict[str, dict] = {}
    warnings: list[str] = []
    for venv in venvs:
        python = venv_python(venv)
        if not python.exists():
            warnings.append(f"no venv at {venv} -- its packages are unscanned")
            continue
        try:
            packages = run_piplicenses(python)
        except Exception as exc:  # noqa: BLE001 - every failure means "no data"
            warnings.append(f"pip-licenses failed in {venv}: {exc}")
            continue
        for row in packages:
            rows.setdefault(normalize(row.get("Name", "")), row)
    return rows, warnings


def verdict(license_string: str) -> str:
    """"" | "AGPL" | "SSPL" | "LGPL" | "GPL" | "UNKNOWN"."""
    text = (license_string or "").strip().upper()
    if text in UNKNOWN_STRINGS:
        return "UNKNOWN"
    for label, patterns in DENY:
        if any(pattern in text for pattern in patterns):
            return label
    return ""


def load_allowlist(path: Path) -> dict:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8")).get("allow", {})


@dataclass
class Finding:
    target: str
    package: str
    version: str
    license: str
    verdict: str
    status: str          # FAIL | ALLOWED | UNSCANNED | XFAIL
    detail: str = ""


def check(strict: bool = False) -> tuple[list[Finding], list[str]]:
    allow = load_allowlist(ALLOWLIST_PATH)
    findings: list[Finding] = []
    warnings: list[str] = []

    for target in TARGETS:
        if not target.lock.exists():
            warnings.append(
                f"{target.label}: {target.lock.relative_to(REPO)} does not exist -- "
                f"regenerate it (docs/RELEASE.md, 'refreshing the lockfiles')")
            continue
        for platform in target.platforms:
            target.names |= parse_lock(target.lock, platform)

        rows, venv_warnings = scan_venvs(target.venvs)
        warnings.extend(f"{target.label}: {w}" for w in venv_warnings)

        for name in sorted(target.names):
            row = rows.get(name)
            entry = allow.get(name, {})
            allowed_targets = entry.get("targets", [])
            entry_applies = bool(entry) and (not allowed_targets
                                             or target.label in allowed_targets)

            if row is None:
                if entry_applies and entry.get("reason"):
                    findings.append(Finding(target.label, name, "?",
                                            entry.get("license", "?"), "UNSCANNED",
                                            "ALLOWED", entry["reason"]))
                else:
                    findings.append(Finding(
                        target.label, name, "?", "", "UNSCANNED",
                        "FAIL" if strict else "UNSCANNED",
                        "not installed in any scanned venv, so its licence is "
                        "unread; install this target's requirements.lock and re-run"))
                continue

            license_string = row.get("License", "") or ""
            v = verdict(license_string)
            if not v:
                # An expected-to-disappear allowlist entry that no longer has
                # anything to excuse: say so loudly rather than rot in the file.
                if entry_applies and entry.get("expect_removed"):
                    warnings.append(
                        f"{target.label}: allowlist entry for {name} is STALE -- "
                        f"its licence now reads {license_string!r}; delete the entry")
                continue

            if not entry_applies:
                findings.append(Finding(
                    target.label, name, row.get("Version", "?"), license_string, v,
                    "FAIL",
                    f"{v} in a conveyed artefact with no allowlist entry. Add one to "
                    f"tools/license_allowlist.toml WITH a justification, replace the "
                    f"dependency, or stop shipping it."))
            elif v in NEEDS_JUSTIFICATION and not entry.get("reason"):
                findings.append(Finding(
                    target.label, name, row.get("Version", "?"), license_string, v,
                    "FAIL",
                    "allowlisted but with no `reason` -- a copyleft entry needs one "
                    "sentence saying HOW we ship it compliantly"))
            elif entry.get("expect_removed"):
                # The pystray case: allowed for now, but the plan says it goes.
                # Deleting the allowlist entry is what turns this into a FAIL,
                # so the gate cleans itself up the day the dependency does.
                findings.append(Finding(
                    target.label, name, row.get("Version", "?"), license_string, v,
                    "XFAIL", entry.get("expect_removed")))
            else:
                findings.append(Finding(
                    target.label, name, row.get("Version", "?"), license_string, v,
                    "ALLOWED", entry.get("reason", "")))

    return findings, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strict", action="store_true",
                    help="treat a package we could not scan as a failure (what CI "
                         "runs, after installing every requirements.lock)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    findings, warnings = check(strict=args.strict)
    failures = [f for f in findings if f.status == "FAIL"]

    if args.json:
        print(json.dumps({
            "findings": [f.__dict__ for f in findings],
            "warnings": warnings,
            "failed": len(failures),
        }, indent=2))
        return 1 if failures else 0

    for target in TARGETS:
        rows = [f for f in findings if f.target == target.label]
        print(f"\n=== {target.label} ===")
        print(f"    {target.why}")
        print(f"    lock: {target.lock.relative_to(REPO)}  "
              f"platforms: {', '.join(target.platforms)}  packages: {len(target.names)}")
        if not rows:
            print("    nothing to report")
        for f in sorted(rows, key=lambda r: (r.status, r.package)):
            # ASCII only in the printed report: a Windows CI runner's console is
            # cp1252 and an em dash there is a UnicodeEncodeError, i.e. a gate
            # that fails for the wrong reason.
            print(f"    [{f.status:9s}] {f.package} {f.version} -- {f.license or f.verdict}")
            if f.detail:
                print(f"                {f.detail}")

    for w in warnings:
        print(f"\nWARNING: {w}")

    if failures:
        print(f"\nFAILED: {len(failures)} licence problem(s) in a conveyed artefact.")
        return 1
    print("\nOK: no unexcused copyleft or unknown licence in the shipped set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
