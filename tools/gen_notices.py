#!/usr/bin/env python3
"""Generate docs/legal/THIRD_PARTY_NOTICES.md from the component venvs.

First written 2026-08-17 for docs/COMMERCIAL_READINESS.md item 3 ("the repo
has no LICENSE, NOTICE, EULA, privacy policy or telemetry disclosure"); the
document it produces was issued as final product text on 2026-09-25, after
the owner's legal review. The pip tables are an inventory of what is
installed and what each package's own metadata claims, so the licence
identifiers in them are only as good as that metadata.

    python tools\\gen_notices.py            # rewrite docs/legal/THIRD_PARTY_NOTICES.md
    python tools\\gen_notices.py --check    # exit 1 if that file is out of date
    python tools\\gen_notices.py --out -    # print to stdout
    python tools\\gen_notices.py --write-texts        # the licence TEXTS each binary carries
    python tools\\gen_notices.py --venv companion=PATH  # scan another venv (repeatable)

--write-texts (LG-12, docs/LEGAL_GAP_FEATURES_PLAN.md, 2026-09-25) writes
docs/legal/licenses/<component>/<dist>-<version>.txt for every distribution a
frozen component conveys at run time, and one THIRD_PARTY_LICENSES.txt per
frozen component that puts the non-pip texts in tools/notices_extra/
(CPython, Tcl/Tk, OpenSSL, libpq, the PyInstaller bootloader) ahead of them.
companion/build.spec and the onboarding specs bundle that file and refuse to
build without it. The texts are read out of each distribution's installed
.dist-info, not from pip-licenses: a wheel routinely carries more than one
licence file (numpy's bundled-library licences, onnxruntime's third-party
notices) and pip-licenses returns the first.

Stdlib only, on purpose: this script must run from ANY of the interpreters on
this machine (system python, the dashboard venv, a CI runner) without adding a
dependency to a repo whose dependency list is itself the thing being audited.
pip-licenses is installed INTO each component venv on demand instead, because
a package list is only true for the interpreter that owns it.

WHAT IT CANNOT DO. Everything conveyed to a customer that is not a pip
package (rclone, Syncthing, ffmpeg, deno, yt-dlp, the models, htmx, Tcl/Tk,
the vendored yt-credit-downloader) is invisible to pip and is maintained BY
HAND between the sentinels:

    <!-- BEGIN HAND-MAINTAINED -->  ...  <!-- END HAND-MAINTAINED -->

This script reads that block out of the existing file and writes it back
verbatim. Do not remove the sentinels; without them a regeneration silently
drops the half of the inventory that carries the actual copyleft obligations.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import tomllib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_PATH = REPO / "docs" / "legal" / "THIRD_PARTY_NOTICES.md"

BEGIN_SENTINEL = "<!-- BEGIN HAND-MAINTAINED -->"
END_SENTINEL = "<!-- END HAND-MAINTAINED -->"

# (label, venv dir, what this venv is). A missing venv is a WARNING: this
# script has to work on a machine that only has some of the components
# checked out.
#
# ytdl/web is NOT a row any more (LG-13, 2026-09-25). It never had a venv of
# its own -- its tests run on the dashboard's, and what the container installs
# for it is in dashboard/deploy/requirements.lock, which the
# dashboard-container table already covers -- so the row only ever produced a
# permanent "no venv: SKIPPED" line under Scan warnings in a document counsel
# reads. broll/web has had its own venv since 2026-09-11.
COMPONENTS: list[tuple[str, Path, str]] = [
    ("companion", REPO / "companion" / ".venv",
     "editor tray app; the frozen build ships a SUBSET of this (see build.spec)"),
    ("dashboard", REPO / "dashboard" / ".venv",
     "FastAPI fleet dashboard; the deployed container installs "
     "dashboard/deploy/requirements.txt, not this venv"),
    ("music/web", REPO / "music" / "web" / ".venv",
     "music search UI mounted at /music; deliberately no torch"),
    ("broll/web", REPO / "broll" / "web" / ".venv",
     "b-roll search UI mounted at /broll"),
]

# server-tools-1 (2026-09-18): the CONTAINER's own dependency list, which is
# what a customer is actually conveyed and which no venv describes. It was
# invisible here, so `psycopg2-binary` (LGPL) entered
# dashboard/deploy/requirements.lock on 2026-08-31, was excused in
# tools/license_allowlist.toml on the written promise that its notice lives in
# THIRD_PARTY_NOTICES.md, and that file has never carried a psycopg2 row. A
# lock is names and versions only: the licence is taken from whichever scanned
# venv holds the same package, and a package no venv holds is reported as
# unknown rather than as permissive, which is the safe direction for a
# document whose purpose is finding copyleft.
CONTAINER_LOCKS: list[tuple[str, Path, str]] = [
    ("dashboard-container", REPO / "dashboard" / "deploy" / "requirements.lock",
     "what the deployed dashboard image installs -- the artefact a customer "
     "receives, not a developer venv"),
]

_LOCK_PIN = "=="


def normalize(name: object) -> str:
    """PEP 503 normalisation (LG-13, 2026-09-25). pip-licenses reports a
    distribution's own spelling ("pyobjc-framework-Cocoa", "Pygments") and a
    lock the normalised one; matched with a bare .lower(), a name spelt with
    `_` or `.` on one side never met itself on the other, and its container
    row read "not installed anywhere". tools/check_licenses.py has the same
    function; it imports THIS module, so the dependency cannot run the other
    way."""
    return re.sub(r"[-_.]+", "-", str(name or "")).strip().lower()


def read_lock(path: Path) -> list[tuple[str, str]]:
    """[(name, version)] from a hash-pinned requirements lock. [] if absent."""
    out: list[tuple[str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        if _LOCK_PIN not in line:
            continue
        name, _, rest = line.partition(_LOCK_PIN)
        version = rest.split()[0].strip().rstrip("\\").strip()
        if name.strip() and version:
            out.append((name.strip(), version))
    return sorted(set(out), key=lambda p: p[0].lower())


def lock_rows(per_component: dict[str, list[dict]],
              path: Path) -> list[dict]:
    """Lock entries as package rows, with the licence borrowed from a venv.

    `_licence_source` records WHERE the licence string came from, because a
    lock pin and the venv's own copy are routinely different versions
    (2.9.12 in the container, 2.9.13 here) and a reader must not be told the
    container's version was inspected when it was not.
    """
    by_name: dict[str, dict] = {}
    for packages in per_component.values():
        for pkg in packages:
            by_name.setdefault(normalize(pkg.get("Name", "")), pkg)
    rows: list[dict] = []
    for name, version in read_lock(path):
        venv_pkg = by_name.get(normalize(name))
        rows.append({
            "Name": name,
            "Version": version,
            "License": (venv_pkg or {}).get("License", "UNKNOWN"),
            "URL": (venv_pkg or {}).get("URL", ""),
            "_licence_source": (
                f"a venv's {venv_pkg.get('Version')}" if venv_pkg
                else "not installed anywhere on this machine"),
        })
    return rows


# Substring match, upper-cased, against the metadata licence string. Anything
# that hits this list needs a human to decide whether the way we ship it is
# compliant -- it is not an assertion that it is not.
ATTENTION_TOKENS = ("GPL", "AGPL", "LGPL", "SSPL", "MPL", "EUPL", "CDDL", "EPL", "CC BY-SA")
# GPL matches LGPL/AGPL as a substring; these are reported under their own,
# more specific name rather than twice.
ATTENTION_LABELS = {"AGPL": "AGPL", "LGPL": "LGPL", "GPL": "GPL"}


def venv_python(venv: Path) -> Path:
    win = venv / "Scripts" / "python.exe"
    return win if win.exists() else venv / "bin" / "python"


def run_piplicenses(python: Path) -> list[dict]:
    """pip-licenses' JSON for one interpreter, installing it if absent.

    The module name is `piplicenses`, not `pip_licenses` and not the
    distribution name -- calling it wrong reads as "not installed" and sends
    this into a pointless reinstall loop.

    server-tools-3 (2026-09-18b mediums): every read here is decoded as UTF-8
    with `errors="replace"`, never by the console codec. `text=True` alone
    decodes with `locale.getpreferredencoding(False)` -- cp1252 on the base
    rig, whose 0x81/0x8D/0x8F/0x90/0x9D are undefined and are ordinary UTF-8
    continuation bytes -- and `--with-license-file` pulls whole licence TEXTS
    through this pipe, so one package with a CJK author or licence file killed
    the only document that must exist before a build is conveyed.
    """
    argv = [
        str(python), "-m", "piplicenses",
        "--format=json", "--with-urls", "--with-license-file", "--no-license-path",
    ]
    proc = subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        sys.stderr.write(f"  installing pip-licenses into {python.parent.parent}\n")
        install = subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "pip-licenses"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if install.returncode != 0:
            raise RuntimeError(
                f"pip install pip-licenses failed: {install.stderr.strip()[:400]}")
        proc = subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(f"pip-licenses failed: {proc.stderr.strip()[:400]}")
    return json.loads(proc.stdout)


# --venv LABEL=PATH (LG-11/LG-12, 2026-09-25): scan a venv built from the lock
# instead of the developer venv, e.g. the release build's own, whose
# psycopg2-binary a developer venv made before 2026-09-25 does not hold.
VENV_OVERRIDES: dict[str, Path] = {}


def shown_path(path: Path) -> str:
    """Repo-relative where possible (LG-13): a customer document used to
    print the base rig's own absolute venv paths.

    NEVER absolute (review round, 2026-09-25). THIRD_PARTY_NOTICES.md is
    bundled into every binary since LG-12, and `--venv companion=<scratch>`
    is a documented way to regenerate it, so the old `str(path)` fallback put
    a machine-local path (a user name, a temp dir) in front of every customer
    and made CI's `--check`, which renders from the repo's own venvs, fail on
    a path no runner has. Outside the repo only the directory's own name is
    shown."""
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return f"<outside the repository>/{path.name}"


def collect() -> tuple[dict[str, list[dict]], list[str]]:
    """-> ({label: [package, ...]}, [warning, ...]). Never raises for a
    missing component; a site that has not checked one out still gets a
    notices file for the rest."""
    per_component: dict[str, list[dict]] = {}
    warnings: list[str] = []
    for label, venv, _desc in COMPONENTS:
        venv = VENV_OVERRIDES.get(label, venv)
        python = venv_python(venv)
        if not python.exists():
            warnings.append(f"{label}: no venv at {shown_path(venv)}: SKIPPED, its packages are "
                            f"not in this inventory")
            sys.stderr.write(f"WARNING: {label}: no venv at {venv}\n")
            continue
        sys.stderr.write(f"  scanning {label} ({venv})\n")
        try:
            packages = run_piplicenses(python)
        # server-tools-3 (2026-09-18b mediums): ValueError, not the pair.
        # json.JSONDecodeError is a ValueError, and so is the UnicodeDecodeError
        # a byte the pipe's codec cannot map raises -- which used to escape
        # main() as a traceback and leave the notices file unregenerable.
        except (RuntimeError, ValueError) as exc:
            warnings.append(f"{label}: pip-licenses failed: {exc}")
            sys.stderr.write(f"WARNING: {label}: {exc}\n")
            continue
        packages.sort(key=lambda p: p.get("Name", "").lower())
        per_component[label] = packages
    return per_component, warnings


def merged(per_component: dict[str, list[dict]]) -> list[dict]:
    """De-duplicated by (name, version), carrying the components it appears in.

    A package installed at two DIFFERENT versions stays two rows: the licence
    can change between versions, and merging them would hide that.
    """
    out: dict[tuple[str, str], dict] = {}
    for label, packages in per_component.items():
        for pkg in packages:
            # Normalised (LG-13): one distribution spelt two ways by two
            # sources is one row, under the first spelling seen.
            key = (normalize(pkg.get("Name", "")), pkg.get("Version", ""))
            row = out.setdefault(key, {**pkg, "_components": []})
            row["_components"].append(label)
    return sorted(out.values(), key=lambda p: p.get("Name", "").lower())


def attention(rows: list[dict]) -> list[tuple[dict, str]]:
    flagged: list[tuple[dict, str]] = []
    for row in rows:
        text = str(row.get("License", "")).upper()
        hit = next((t for t in ATTENTION_TOKENS if t in text), None)
        if hit is None:
            continue
        for specific in ("AGPL", "LGPL"):
            if specific in text:
                hit = specific
                break
        flagged.append((row, ATTENTION_LABELS.get(hit, hit)))
    return flagged


def has_license_text(row: dict) -> bool:
    """Whether pip-licenses found a licence FILE in the installed
    distribution. That is the difference between "the package's own metadata
    says MIT" and "the package ships the text that proves it" -- the whole
    point of this exercise is keeping those two apart (pystray's LGPLv3 was
    confirmed exactly that way)."""
    text = str(row.get("LicenseText", "")).strip()
    return bool(text) and text.upper() not in ("UNKNOWN", "")


def esc(value: object) -> str:
    """Table-cell text. A pipe in a licence string ("MIT | Apache-2.0") would
    otherwise open a new column."""
    return str(value if value is not None else "").replace("|", "\\|").strip() or "-"


def render(per_component: dict[str, list[dict]], warnings: list[str],
           hand_block: str, binaries: list[dict] | None = None) -> str:
    # server-tools-1: the container lock's packages are part of the
    # attention scan, not a footnote. They are what is conveyed.
    container: dict[str, list[dict]] = {
        label: lock_rows(per_component, path)
        for label, path, _desc in CONTAINER_LOCKS
    }
    rows = merged({**per_component,
                   **{k: v for k, v in container.items() if v}})
    flagged = attention(rows)
    lines: list[str] = []
    add = lines.append

    # No run date in the header, deliberately: --check compares the rendered
    # text against the file, so a timestamp would make every check fail on the
    # day after a regeneration. 2026-08-17 is when this file was FIRST written;
    # what the tables say is true of whatever venvs the last run scanned, and
    # `git log docs/legal/THIRD_PARTY_NOTICES.md` is the honest answer to when
    # (2026-08-18).
    add("<!-- Maintainers: GENERATED FILE. The pip sections below are produced by")
    add("     `python tools/gen_notices.py`; edit that script, not these tables,")
    add("     and `git log` on this file is when they were last regenerated.")
    add("     The block between <!-- BEGIN HAND-MAINTAINED --> and")
    add("     <!-- END HAND-MAINTAINED --> is written by hand and is preserved")
    add("     verbatim across regeneration: it carries the components pip")
    add("     cannot see, which is where every copyleft obligation actually is.")
    add("     The developer-venv tables list what is installed for development;")
    add("     the dashboard-container table is the shipped image's own lock")
    add("     (server-tools-1, 2026-09-18), with its licences read from a venv. -->")
    add("")
    add("# CC Sync: third-party notices")
    add("")
    add("**Issued 2026-09-25 by Cablewrap Creative Ltd.**")
    add("")
    add("CC Sync is proprietary software, licensed under `docs/legal/EULA.md`. It")
    add("incorporates, links against, or arranges the download of the third-party")
    add("components listed here. Each remains licensed by its own author under its")
    add("own terms, which prevail over the EULA for that component.")
    add("")
    add("**How to read the verification column.** `metadata` means the fact came")
    add("out of the installed distribution's own metadata via `pip-licenses`, and")
    add("`+text` means the distribution also ships the licence text on disk. In the")
    add("hand-maintained section, *as published upstream* means the licence is the")
    add("one the component's publisher states, and was not re-read from a shipped")
    add("file.")
    add("")

    if flagged:
        add("## LICENCES NEEDING ATTENTION")
        add("")
        add("Copyleft or otherwise non-permissive licences found in the venvs. Being")
        add("listed here is not a finding of non-compliance: it means a human must")
        add("decide whether the way we ship this one is compliant. See the")
        add("\"LGPL and MPL components that remain\" subsection for the ones already reasoned")
        add("through.")
        add("")
        add("| Package | Version | Licence | Present in | Verification |")
        add("|---|---|---|---|---|")
        for row, kind in flagged:
            verification = "metadata+text" if has_license_text(row) else "metadata"
            add(f"| `{esc(row.get('Name'))}` | {esc(row.get('Version'))} | "
                f"**{esc(row.get('License'))}** ({kind}) | "
                f"{esc(', '.join(row['_components']))} | {verification} |")
        add("")
    else:
        add("## LICENCES NEEDING ATTENTION")
        add("")
        add("No GPL/AGPL/LGPL/SSPL/MPL/EUPL/CDDL/EPL string was found in the pip")
        add("metadata of any scanned venv. This says nothing about the")
        add("hand-maintained section below, which is where ffmpeg (GPLv3) and")
        add("Syncthing (MPL-2.0) live.")
        add("")

    if warnings:
        add("## Scan warnings")
        add("")
        add("These components were NOT scanned; their packages are missing from")
        add("every table below.")
        add("")
        for warning in warnings:
            add(f"- {warning}")
        add("")

    add("## Python dependencies by component")
    add("")
    add("What is installed in each component's development virtualenv. This is")
    add("**not** the same as what a customer receives: the frozen companion ships")
    add("only what `companion/build.spec` collects, and the deployed container")
    add("installs `dashboard/deploy/requirements.txt`.")
    add("")
    for label, venv, desc in COMPONENTS:
        packages = per_component.get(label)
        if packages is None:
            continue
        add(f"### {label}")
        add("")
        add(f"{desc}. Venv: `{shown_path(VENV_OVERRIDES.get(label, venv))}`, "
            f"{len(packages)} package(s).")
        add("")
        add("| Package | Version | Licence | Home page |")
        add("|---|---|---|---|")
        for pkg in packages:
            add(f"| `{esc(pkg.get('Name'))}` | {esc(pkg.get('Version'))} | "
                f"{esc(pkg.get('License'))} | {esc(pkg.get('URL'))} |")
        add("")

    for label, path, desc in CONTAINER_LOCKS:
        packages = container.get(label) or []
        if not packages:
            continue
        add(f"### {label}")
        add("")
        add(f"{desc}. Lock: `{path.relative_to(REPO).as_posix()}`, "
            f"{len(packages)} package(s). A lock carries no licence metadata, "
            f"so each licence below is the one the same package's metadata "
            f"declares in a developer venv on this machine; the version column "
            f"is the CONTAINER's.")
        add("")
        add("| Package | Version (container) | Licence | Licence read from |")
        add("|---|---|---|---|")
        for pkg in packages:
            add(f"| `{esc(pkg.get('Name'))}` | {esc(pkg.get('Version'))} | "
                f"{esc(pkg.get('License'))} | "
                f"{esc(pkg.get('_licence_source'))} |")
        add("")

    add("## All pip dependencies (merged)")
    add("")
    add(f"{len(rows)} distinct (package, version) pair(s) across every scanned venv.")
    add("")
    add("| Package | Version | Licence | Components | Licence text on disk |")
    add("|---|---|---|---|---|")
    for row in rows:
        add(f"| `{esc(row.get('Name'))}` | {esc(row.get('Version'))} | "
            f"{esc(row.get('License'))} | {esc(', '.join(row['_components']))} | "
            f"{'yes' if has_license_text(row) else 'no'} |")
    add("")
    render_binaries(add, fetched_binaries() if binaries is None else binaries)
    add(BEGIN_SENTINEL)
    add(hand_block)
    add(END_SENTINEL)
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------- LG-13 pins
# "Binaries the installer fetches" (LG-13, docs/LEGAL_GAP_FEATURES_PLAN.md,
# 2026-09-25). Every binary CC Sync downloads onto a customer's machine at
# install or run time is pinned by version and sha256 in code, and the
# hand-maintained inventory used to restate those pins by hand -- so a bump
# in the code left a notice naming a build nobody downloads any more, and a
# written offer naming the wrong build is not an offer. This table is READ
# FROM THE CODE BY SYMBOL NAME and is part of the generated half, so
# `--check` fails the moment a pin moves without this file being
# regenerated. A symbol that cannot be found is an error, never a missing
# row: a renamed constant must not quietly drop a download from the notice.

class PinNotFound(RuntimeError):
    pass


def _ps1_var(text: str, name: str, where: str) -> str:
    match = re.search(rf'^\s*\${re.escape(name)}\s*=\s*"([^"$]+)"', text, re.M)
    if not match:
        raise PinNotFound(f"{where}: ${name} not found")
    return match.group(1)


def _sh_var(text: str, name: str, where: str) -> str:
    match = re.search(rf'^{re.escape(name)}="([^"$]+)"', text, re.M)
    if not match:
        raise PinNotFound(f"{where}: {name} not found")
    return match.group(1)


def _py_assignments(text: str) -> dict[str, ast.AST]:
    """Module-level `NAME = value` and `NAME: T = value` (PINNED_ASSETS is
    annotated)."""
    out: dict[str, ast.AST] = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value
        elif (isinstance(node, ast.AnnAssign) and node.value is not None
              and isinstance(node.target, ast.Name)):
            out[node.target.id] = node.value
    return out


def _py_str(values: dict[str, ast.AST], name: str, where: str) -> str:
    node = values.get(name)
    try:
        value = ast.literal_eval(node) if node is not None else None
    except ValueError:
        value = None
    if not isinstance(value, str):
        raise PinNotFound(f"{where}: {name} not found as a string constant")
    return value


def _asset_name(node: ast.AST) -> str:
    """The file name at the end of an f-string URL such as
    f"{FFMPEG_BASE_URL}/ffmpeg-win32-x64.gz"."""
    if isinstance(node, ast.JoinedStr):
        tail = "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        tail = node.value
    else:
        tail = ""
    return tail.rsplit("/", 1)[-1]


def fetched_binaries(repo: Path | None = None) -> list[dict]:
    """[{component, version, platform, asset, sha256, source}], read from
    the four places that pin a download. Raises PinNotFound. Reads this
    checkout's own code, not REPO, which tests re-point for path display."""
    repo = repo or Path(__file__).resolve().parents[1]
    rows: list[dict] = []

    where = "installer/windows_bootstrap.ps1"
    text = (repo / where).read_text(encoding="utf-8")
    for component, stem in (("rclone", "Rclone"), ("Syncthing", "Syncthing")):
        version = _ps1_var(text, f"{stem}Version", where)
        url = re.search(rf'^\s*\${stem}ZipUrl\s*=\s*"([^"]+)"', text, re.M)
        rows.append({
            "component": component,
            "version": version,
            "platform": "Windows x64",
            "asset": (url.group(1).replace(f"${stem}Version", version)
                      .rsplit("/", 1)[-1] if url else "zip"),
            "sha256": _ps1_var(text, f"{stem}ZipSha256", where),
            "source": f"`{where}`: `${stem}Version`, `${stem}ZipSha256`",
            "fetched_by": "the editor installer",
        })

    where = "installer/macos_bootstrap.sh"
    text = (repo / where).read_text(encoding="utf-8")
    for component, stem in (("rclone", "RCLONE"), ("Syncthing", "SYNCTHING")):
        version = _sh_var(text, f"{stem}_VERSION", where)
        for arch, label in (("ARM64", "macOS arm64"), ("AMD64", "macOS x64")):
            asset = next((a for a in re.findall(rf'{stem}_ASSET="([^"]+)"', text)
                          if "${ASSET_ARCH}" in a or arch.lower() in a), "zip")
            asset = (asset.replace("${ASSET_ARCH}", arch.lower())
                     .replace(f"${{{stem}_VERSION}}", version)
                     .replace(f"${stem}_VERSION", version))
            rows.append({
                "component": component,
                "version": version,
                "platform": label,
                "asset": asset,
                "sha256": _sh_var(text, f"{stem}_SHA256_{arch}", where),
                "source": f"`{where}`: `{stem}_VERSION`, `{stem}_SHA256_{arch}`",
                "fetched_by": "the editor installer",
            })

    where = "companion/src/ccsync_companion/sidecar_tools.py"
    values = _py_assignments((repo / where).read_text(encoding="utf-8"))
    tags = {"ffmpeg": _py_str(values, "FFMPEG_RELEASE_TAG", where),
            "ffprobe": _py_str(values, "FFMPEG_RELEASE_TAG", where),
            "deno": _py_str(values, "DENO_RELEASE_TAG", where)}
    tag_symbol = {"ffmpeg": "FFMPEG_RELEASE_TAG", "ffprobe": "FFMPEG_RELEASE_TAG",
                  "deno": "DENO_RELEASE_TAG"}
    assets = values.get("PINNED_ASSETS")
    if not isinstance(assets, ast.Dict):
        raise PinNotFound(f"{where}: PINNED_ASSETS not found as a dict literal")
    platform_names = {("win32", "x64"): "Windows x64", ("darwin", "arm64"): "macOS arm64",
                      ("darwin", "x64"): "macOS x64"}
    for key_node, tools_node in zip(assets.keys, assets.values):
        key = ast.literal_eval(key_node)
        if not isinstance(tools_node, ast.Dict):
            raise PinNotFound(f"{where}: PINNED_ASSETS[{key!r}] is not a dict literal")
        for tool_node, spec_node in zip(tools_node.keys, tools_node.values):
            tool = ast.literal_eval(tool_node)
            if not (isinstance(spec_node, ast.Tuple) and len(spec_node.elts) >= 2):
                raise PinNotFound(f"{where}: PINNED_ASSETS[{key!r}][{tool!r}] is not a tuple")
            sha = ast.literal_eval(spec_node.elts[1])
            rows.append({
                "component": tool,
                "version": tags.get(tool, "?"),
                "platform": platform_names.get(tuple(key), "/".join(key)),
                "asset": _asset_name(spec_node.elts[0]),
                "sha256": sha,
                "source": f"`{where}`: `{tag_symbol.get(tool, '?')}`, `PINNED_ASSETS`",
                "fetched_by": "the companion, on first use",
            })

    where = "server/install_dashboard_app.py"
    values = _py_assignments((repo / where).read_text(encoding="utf-8"))
    url = _py_str(values, "DEFAULT_FFMPEG_URL", where)
    asset = url.rsplit("/", 1)[-1]
    rows.append({
        "component": "ffmpeg (NAS side)",
        "version": (re.search(r"ffmpeg-([0-9][0-9.]*)", asset) or [None, "?"])[1].rstrip("."),
        "platform": "Linux x64 (the dashboard container)",
        "asset": asset,
        "sha256": _py_str(values, "DEFAULT_FFMPEG_SHA256", where),
        "source": f"`{where}`: `DEFAULT_FFMPEG_URL`, `DEFAULT_FFMPEG_SHA256`",
        "fetched_by": "the dashboard deploy",
    })
    return rows


def render_binaries(add, binaries: list[dict]) -> None:
    add("## Binaries the installer fetches")
    add("")
    add("Generated from the pins in the code (LG-13, 2026-09-25): every binary")
    add("CC Sync downloads onto a customer's machine at install or run time, by")
    add("version and the sha256 of the asset as downloaded. A download whose")
    add("bytes do not match is deleted, not installed. The licence of each is in")
    add("the hand-maintained inventory below.")
    add("")
    add("| Component | Version | Platform | Asset | sha256 | Fetched by | Pinned in |")
    add("|---|---|---|---|---|---|---|")
    for row in binaries:
        add(f"| {esc(row['component'])} | `{esc(row['version'])}` | "
            f"{esc(row['platform'])} | `{esc(row['asset'])}` | "
            f"`{esc(row['sha256'])}` | {esc(row['fetched_by'])} | "
            f"{esc(row['source'])} |")
    add("")


# ---------------------------------------------------------------- LG-12 texts
LICENSES_DIR = REPO / "docs" / "legal" / "licenses"
EXTRA_DIR = Path(__file__).resolve().parent / "notices_extra"
BUNDLE_NAME = "THIRD_PARTY_LICENSES.txt"


def _pyproject_roots(pyproject: Path, extras: tuple[str, ...]) -> set[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    specs = list(project.get("dependencies", []))
    for extra in extras:
        specs += project.get("optional-dependencies", {}).get(extra, [])
    return {normalize(re.split(r"[\s;<>=!~\[]", spec.strip(), 1)[0])
            for spec in specs if spec.strip()}


# (label, lock, runtime roots, texts from tools/notices_extra/). The roots are
# what the frozen binary conveys: pyproject's dependencies plus the `tray`
# extra (Pillow, pyobjc), NOT `dev` (pytest and its closure, which the lock
# also carries). The rest of the runtime set is the lock's own `# via` graph
# walked down from them, so a transitive dependency (packaging via
# onnxruntime) is in and a dev-only one (colorama via pytest) is out.
#
# The onboarding wizard's OWN import graph conveys no third-party distribution
# (onboarding/requirements.in, and tools/scan_frozen.py fails its build if
# that stops being true) -- but onboard.exe and the Mac wizard carry the whole
# companion executable as a data file (COMPANION_EXE / COMPANION_BIN in the
# onboarding specs) and install it, so they CONVEY everything the companion
# does: psycopg2 and libpq (LGPL / PostgreSQL), numpy, onnxruntime and the
# rest. The fifth field names the components a binary embeds; their
# distribution texts are copied into its bundle. Until the 2026-09-25 review
# round the wizard's bundle listed four non-pip texts and claimed to be
# complete.
FROZEN: list[tuple[str, Path, callable, tuple[str, ...], tuple[str, ...]]] = [
    ("companion", REPO / "companion" / "requirements.lock",
     lambda: _pyproject_roots(REPO / "companion" / "pyproject.toml", ("tray",)),
     ("pyinstaller-bootloader.txt", "cpython.txt", "tcl-tk.txt",
      "openssl.txt", "libpq.txt"),
     ()),
    ("onboarding", REPO / "onboarding" / "requirements.lock",
     lambda: set(),
     ("pyinstaller-bootloader.txt", "cpython.txt", "tcl-tk.txt",
      "openssl.txt", "libpq.txt"),
     ("companion",)),
]


def lock_graph(path: Path) -> dict[str, tuple[str, set[str]]]:
    """{normalised name: (version, {normalised parents})} from a uv lock's
    `# via` comments. A parent that is the project itself is recorded as
    the literal "<project>"."""
    graph: dict[str, tuple[str, set[str]]] = {}
    current: str | None = None
    in_via = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        head = re.match(r"^([A-Za-z0-9._-]+)==([^\s;\\]+)", raw)
        if head:
            current = normalize(head.group(1))
            graph[current] = (head.group(2), set())
            in_via = False
            continue
        if current is None:
            continue
        stripped = raw.strip()
        if stripped.startswith("# via"):
            rest = stripped[len("# via"):].strip()
            in_via = not rest
            if rest:
                graph[current][1].add(_via_name(rest))
        elif in_via and stripped.startswith("#   "):
            graph[current][1].add(_via_name(stripped[4:].strip()))
        elif not stripped.startswith("--hash"):
            in_via = False
    return graph


def _via_name(text: str) -> str:
    return "<project>" if "(" in text else normalize(text.split()[0])


def runtime_closure(graph: dict[str, tuple[str, set[str]]],
                    roots: set[str]) -> dict[str, str]:
    """{name: version} for the roots and everything the lock says they pull
    in. A root absent from the lock is an error: it means the lock is stale
    against pyproject.toml, which is exactly LG-11's failure."""
    missing = sorted(r for r in roots if r not in graph)
    if missing:
        raise SystemExit(f"runtime dependencies missing from the lock: "
                         f"{', '.join(missing)} -- relock (docs/RELEASE.md, "
                         f"'Refreshing the lockfiles')")
    children: dict[str, set[str]] = {}
    for name, (_version, parents) in graph.items():
        for parent in parents:
            children.setdefault(parent, set()).add(name)
    out: dict[str, str] = {}
    todo = list(roots)
    while todo:
        name = todo.pop()
        if name in out:
            continue
        out[name] = graph[name][0]
        todo.extend(children.get(name, ()))
    return dict(sorted(out.items()))


_LICENCE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|AUTHORS|COPYRIGHT)", re.I)
# Inside a package (the RECORD fallback) only a plainly named text file
# counts: pyobjc's test suite ships a compiled `copying.cpython-312-darwin.so`.
_PACKAGE_LICENCE_FILE = re.compile(
    r"^(LICEN[CS]E|COPYING|NOTICE|COPYRIGHT|ThirdPartyNotices)([._-][A-Za-z0-9]+)?(\.(txt|md|rst))?$", re.I)
# A distribution whose wheel ships no licence file at all (pyobjc-core 12.2.2,
# checked 2026-09-25) gets its text from here, as <normalised name>.txt, with
# a header saying where it came from. Used only when the wheel has none.
DIST_FALLBACK_DIR = Path(__file__).resolve().parent / "notices_extra" / "dists"


def site_packages(venv: Path) -> Path | None:
    win = venv / "Lib" / "site-packages"
    if win.is_dir():
        return win
    found = sorted(venv.glob("lib/python3*/site-packages"))
    return found[0] if found else None


def dist_licence_texts(site: Path, name: str) -> tuple[str, list[tuple[str, str]]] | None:
    """(installed version, [(file name, text)]) for one distribution, or
    None when it is not installed there. Every licence-shaped file in the
    .dist-info (PEP 639's licenses/ directory included) is taken; when the
    dist-info carries none, RECORD is searched for one inside the package."""
    for info in sorted(site.glob("*.dist-info")):
        meta = info / "METADATA"
        if not meta.exists():
            continue
        header = meta.read_text(encoding="utf-8", errors="replace").split("\n\n", 1)[0]
        got = re.search(r"^Name:\s*(.+)$", header, re.M)
        if not got or normalize(got.group(1)) != name:
            continue
        version = (re.search(r"^Version:\s*(.+)$", header, re.M) or [None, "?"])[1].strip()
        files = [p for p in sorted(info.rglob("*"))
                 if p.is_file() and (_LICENCE_FILE.match(p.name)
                                     or "licenses" in p.relative_to(info).parts)]
        if not files and (info / "RECORD").exists():
            for line in (info / "RECORD").read_text(encoding="utf-8").splitlines():
                rel = line.split(",", 1)[0]
                if (_PACKAGE_LICENCE_FILE.match(rel.rsplit("/", 1)[-1])
                        and not rel.startswith("..")):
                    candidate = site / rel
                    if candidate.is_file():
                        files.append(candidate)
        texts = [(p.relative_to(site).as_posix(),
                  p.read_text(encoding="utf-8", errors="replace"))
                 for p in files]
        return version, texts
    return None


def _clean(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"


def dist_text_file(name: str, version: str, licence: str,
                   texts: list[tuple[str, str]]) -> str:
    title = f"{name} {version}"
    body = [title, "=" * len(title), "",
            f"Licence declared in its metadata: {licence or 'not declared'}",
            "Files: " + (", ".join(n for n, _ in texts) or "none shipped"), ""]
    for file_name, text in texts:
        body += [f"----- {file_name} -----", "", _clean(text)]
    return "\n".join(body).rstrip() + "\n"


def write_texts(out_root: Path = LICENSES_DIR) -> list[str]:
    """Write every frozen component's per-distribution texts and bundle.
    -> warnings. Deterministic (no dates), so a regeneration that changes
    nothing changes no byte."""
    warnings: list[str] = []
    # {label: its distribution sections} for every component whose texts were
    # all found; a component that embeds another reads them from here.
    done: dict[str, list[str]] = {}
    for label, lock, roots_fn, extras, embeds in FROZEN:
        comp_dir = out_root / label
        roots = roots_fn()
        closure = runtime_closure(lock_graph(lock), roots) if roots else {}
        venv = VENV_OVERRIDES.get(label) or next(
            (v for lab, v, _d in COMPONENTS if lab == label), None)
        site = site_packages(venv) if venv else None

        # PLAN first, write second (review round, 2026-09-25): this used to
        # write each text as it went, `continue` past a missing one, delete
        # the stale files and write a bundle without it, and only exit 1
        # afterwards -- so a run from a stale venv whose exit code was ignored
        # left a bundle the specs accept (they test existence) that omits a
        # conveyed package. Now one missing text writes NOTHING for the
        # component: the committed bundle, still naming every package it
        # named, stays until a complete run replaces it.
        planned: dict[Path, bytes | None] = {}   # None: keep the committed file
        missing: list[str] = []
        for name, version in closure.items():
            target = comp_dir / f"{name}-{version}.txt"
            found = dist_licence_texts(site, name) if site else None
            fallback = DIST_FALLBACK_DIR / f"{name}.txt"
            if found and found[0] == version and not found[1] and fallback.exists():
                found = (version, [(f"tools/notices_extra/dists/{fallback.name}",
                                    fallback.read_text(encoding="utf-8"))])
            if found and found[0] == version and found[1]:
                meta = _metadata_licence(site, name)
                planned[target] = dist_text_file(name, version, meta,
                                                 found[1]).encode("utf-8")
            elif target.exists():
                # Not installed here at the locked version (pyobjc on a
                # Windows rig): the text written where it WAS installed stays.
                planned[target] = None
                warnings.append(f"{label}: {name} {version} not installed in "
                                f"{venv}; kept the existing {target.name}")
            else:
                why = ("not installed" if not found else
                       f"installed at {found[0]}, locked at {version}"
                       if found[0] != version else "ships no licence file")
                missing.append(f"{label}: {name} {version}: NO TEXT ({why} in "
                               f"{venv}); re-run with --venv {label}=<a venv "
                               f"built from {lock.relative_to(REPO).as_posix()}>")
        for other in embeds:
            if other not in done:
                missing.append(f"{label}: NO TEXT for the embedded {other}: its "
                               f"texts were not written, so neither is this "
                               f"bundle")
        if missing:
            warnings += missing
            warnings.append(f"{label}: NOTHING WRITTEN for {label}; its "
                            f"committed texts and bundle are unchanged")
            continue

        comp_dir.mkdir(parents=True, exist_ok=True)
        for target, data in planned.items():
            if data is not None:
                target.write_bytes(data)
        keep = {p.name for p in planned} | {BUNDLE_NAME}
        for stale in comp_dir.glob("*.txt"):
            if stale.name not in keep:
                stale.unlink()
        own = [path.read_text(encoding="utf-8") for path in sorted(planned)]
        done[label] = own

        intro = [
            "CC Sync is proprietary software licensed under its End User Licence",
            "Agreement. This binary also contains the third-party components below,",
            "each licensed by its own authors under the terms reproduced here, which",
            "prevail over the EULA for that component. THIRD_PARTY_NOTICES.md, beside",
            "this file, is the inventory and carries the written offers.",
        ]
        if embeds:
            intro += [
                "",
                "It also carries the CC Sync " + ", ".join(embeds) + " program it "
                "installs, and with it",
                "every component that program contains; those are listed here too.",
            ]
        parts = [f"Third-party licences: CC Sync {label}", ""] + intro + [
            "", "Contents:"]
        sections: list[str] = []
        for extra in extras:
            sections.append(_clean((EXTRA_DIR / extra).read_text(encoding="utf-8")))
        seen: set[str] = set()
        dist_sections = own + [s for other in embeds for s in done[other]]
        for section in sorted(dist_sections, key=lambda s: s.split("\n", 1)[0]):
            title = section.split("\n", 1)[0]
            if title not in seen:
                seen.add(title)
                sections.append(section)
        for section in sections:
            parts.append("  - " + section.split("\n", 1)[0])
        parts.append("")
        for section in sections:
            parts += ["=" * 78, "", section.rstrip(), ""]
        (comp_dir / BUNDLE_NAME).write_bytes(("\n".join(parts).rstrip() + "\n")
                                             .encode("utf-8"))
    return warnings


def _metadata_licence(site: Path, name: str) -> str:
    for info in site.glob("*.dist-info"):
        meta = info / "METADATA"
        if not meta.exists():
            continue
        header = meta.read_text(encoding="utf-8", errors="replace").split("\n\n", 1)[0]
        got = re.search(r"^Name:\s*(.+)$", header, re.M)
        if got and normalize(got.group(1)) == name:
            for field_name in ("License-Expression", "License"):
                value = re.search(rf"^{field_name}:\s*(.+)$", header, re.M)
                if value and len(value.group(1)) < 120:
                    return value.group(1).strip()
            classifiers = re.findall(r"^Classifier:\s*License ::.*::\s*(.+)$", header, re.M)
            return "; ".join(c.strip() for c in classifiers)
    return ""


DEFAULT_HAND_BLOCK = """
## Non-pip components (hand-maintained)

This section has not been written for this file yet. Everything conveyed to
a customer that is not a pip package belongs here: rclone, Syncthing, ffmpeg,
deno, yt-dlp, the models, htmx, Tcl/Tk and the vendored yt-credit-downloader.
`tools/gen_notices.py` preserves whatever is between the sentinels; it cannot
write it.
""".strip("\n")


def existing_hand_block(path: Path) -> str:
    """The current hand-maintained block, or the placeholder if there is no
    file yet. A file that HAS the begin sentinel but not the end one is a
    hard error rather than a silent reset: that shape is a half-applied edit,
    and overwriting it would destroy the half that survived.

    LINE-ANCHORED, not `str.find`. The generated header explains the sentinels
    and therefore CONTAINS both strings mid-sentence; a substring search
    matched those, extracted the nothing between them, and silently wiped the
    whole hand-maintained section on the first regeneration (found and fixed
    2026-08-17, before this ever ran against a filled-in file twice). A
    sentinel counts only when it is the entire line.
    """
    if not path.exists():
        return DEFAULT_HAND_BLOCK
    lines = path.read_text(encoding="utf-8").splitlines()
    start = end = None
    for i, line in enumerate(lines):
        if line.strip() == BEGIN_SENTINEL and start is None:
            start = i
        elif line.strip() == END_SENTINEL and start is not None:
            end = i
            break
    if start is None:
        return DEFAULT_HAND_BLOCK
    if end is None:
        raise SystemExit(
            f"{path} has {BEGIN_SENTINEL} but no {END_SENTINEL} — refusing to "
            f"regenerate, because that would delete the hand-maintained section. "
            f"Repair the sentinels first.")
    return "\n".join(lines[start + 1:end]).strip("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the notices file is out of date; write nothing")
    ap.add_argument("--out", default=str(OUT_PATH),
                    help="output path, or '-' for stdout")
    ap.add_argument("--write-texts", action="store_true",
                    help="write docs/legal/licenses/ (the licence texts each "
                         "frozen binary carries) instead of the notices file")
    ap.add_argument("--venv", action="append", default=[], metavar="LABEL=PATH",
                    help="scan PATH instead of LABEL's usual venv (repeatable)")
    args = ap.parse_args(argv)

    for spec in args.venv:
        label, sep, path = spec.partition("=")
        if not sep or not path:
            ap.error(f"--venv takes LABEL=PATH, got {spec!r}")
        VENV_OVERRIDES[label.strip()] = Path(path.strip())

    if args.write_texts:
        text_warnings = write_texts()
        for warning in text_warnings:
            sys.stderr.write(f"WARNING: {warning}\n")
        sys.stderr.write(f"wrote {LICENSES_DIR}\n")
        # A distribution conveyed with NO text is the failure LG-12 exists to
        # prevent; everything else was still written, so the rest is usable.
        return 1 if any("NO TEXT" in w for w in text_warnings) else 0

    out_path = OUT_PATH if args.out == "-" else Path(args.out)
    hand_block = existing_hand_block(out_path)
    try:
        binaries = fetched_binaries()
    except (PinNotFound, OSError) as exc:
        sys.stderr.write(f"ERROR: cannot read a download pin ({exc}); the "
                         f"'Binaries the installer fetches' table would be "
                         f"missing a row, so nothing was written\n")
        return 2
    per_component, warnings = collect()
    if not per_component:
        sys.stderr.write("ERROR: no venv could be scanned; nothing to generate\n")
        return 2
    rendered = render(per_component, warnings, hand_block, binaries)

    if args.check:
        if not out_path.exists():
            sys.stderr.write(f"{out_path} does not exist — run tools/gen_notices.py\n")
            return 1
        if out_path.read_text(encoding="utf-8") != rendered:
            sys.stderr.write(
                f"{out_path} is out of date — run `python tools/gen_notices.py`\n")
            return 1
        sys.stderr.write(f"{out_path} is up to date\n")
        return 0

    if args.out == "-":
        # Through the BUFFER: this document carries non-ASCII (licence names,
        # package metadata, the hand block's symbols), and a Windows console stdout defaults to cp1252, which turns `--out -`
        # into a UnicodeEncodeError (or, redirected, mojibake that no longer
        # matches --check).
        sys.stdout.buffer.write(rendered.encode("utf-8"))
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" so Windows does not translate to CRLF: every other .md in
    # this repo is LF in both the index and the working tree (`* text=auto`,
    # .gitattributes), and a CRLF rewrite would show up as a whole-file diff
    # every time the generator ran.
    with open(out_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(rendered)
    sys.stderr.write(f"wrote {out_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
