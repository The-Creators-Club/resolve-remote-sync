#!/usr/bin/env python3
"""Generate docs/legal/THIRD_PARTY_NOTICES.md from the component venvs.

DRAFT FOR COUNSEL — NOT LEGAL ADVICE. Written 2026-08-17 for
docs/COMMERCIAL_READINESS.md item 3 ("the repo has no LICENSE, NOTICE, EULA,
privacy policy or telemetry disclosure"). The file this produces is an
engineer's inventory of what is installed and what its own metadata claims,
shaped so a lawyer has something concrete to review. It is not a legal
opinion and the licence identifiers in it are only as good as the packages'
own metadata.

    python tools\\gen_notices.py            # rewrite docs/legal/THIRD_PARTY_NOTICES.md
    python tools\\gen_notices.py --check    # exit 1 if that file is out of date
    python tools\\gen_notices.py --out -    # print to stdout

Stdlib only, on purpose: this script must run from ANY of the interpreters on
this machine (system python, the dashboard venv, a CI runner) without adding a
dependency to a repo whose dependency list is itself the thing being audited.
pip-licenses is installed INTO each component venv on demand instead, because
a package list is only true for the interpreter that owns it.

WHAT IT CANNOT DO. Everything conveyed to a customer that is not a pip
package — rclone, Syncthing, ffmpeg, deno, yt-dlp, the models, htmx, Tcl/Tk,
the vendored yt-credit-downloader — is invisible to pip and is maintained BY
HAND between the sentinels:

    <!-- BEGIN HAND-MAINTAINED -->  ...  <!-- END HAND-MAINTAINED -->

This script reads that block out of the existing file and writes it back
verbatim. Do not remove the sentinels; without them a regeneration silently
drops the half of the inventory that carries the actual copyleft obligations.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_PATH = REPO / "docs" / "legal" / "THIRD_PARTY_NOTICES.md"

BEGIN_SENTINEL = "<!-- BEGIN HAND-MAINTAINED -->"
END_SENTINEL = "<!-- END HAND-MAINTAINED -->"

# (label, venv dir, what this venv is). The b-roll web app still borrows the
# pre-fold standalone repo's venv -- the in-repo copy has none yet (CLAUDE.md,
# "Running tests"), so the path deliberately points OUTSIDE this repo. A
# missing venv is a WARNING: this script has to work on a machine that only
# has some of the components checked out.
COMPONENTS: list[tuple[str, Path, str]] = [
    ("companion", REPO / "companion" / ".venv",
     "editor tray app; the frozen build ships a SUBSET of this (see build.spec)"),
    ("dashboard", REPO / "dashboard" / ".venv",
     "FastAPI fleet dashboard; the deployed container installs "
     "dashboard/deploy/requirements.txt, not this venv"),
    ("music/web", REPO / "music" / "web" / ".venv",
     "music search UI mounted at /music; deliberately no torch"),
    ("broll/web", Path("E:/Projects/broll-platform/web/.venv"),
     "b-roll search UI mounted at /broll; borrowed from the pre-fold repo"),
    ("ytdl/web", REPO / "ytdl" / "web" / ".venv",
     "YouTube downloader UI mounted at /ytdl; no venv of its own as of "
     "2026-08-17 -- its deps are in dashboard/deploy/requirements.txt"),
]

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
    """
    argv = [
        str(python), "-m", "piplicenses",
        "--format=json", "--with-urls", "--with-license-file", "--no-license-path",
    ]
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(f"  installing pip-licenses into {python.parent.parent}\n")
        install = subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "pip-licenses"],
            capture_output=True, text=True,
        )
        if install.returncode != 0:
            raise RuntimeError(
                f"pip install pip-licenses failed: {install.stderr.strip()[:400]}")
        proc = subprocess.run(argv, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"pip-licenses failed: {proc.stderr.strip()[:400]}")
    return json.loads(proc.stdout)


def collect() -> tuple[dict[str, list[dict]], list[str]]:
    """-> ({label: [package, ...]}, [warning, ...]). Never raises for a
    missing component; a site that has not checked one out still gets a
    notices file for the rest."""
    per_component: dict[str, list[dict]] = {}
    warnings: list[str] = []
    for label, venv, _desc in COMPONENTS:
        python = venv_python(venv)
        if not python.exists():
            warnings.append(f"{label}: no venv at {venv} — SKIPPED, its packages are "
                            f"not in this inventory")
            sys.stderr.write(f"WARNING: {label}: no venv at {venv}\n")
            continue
        sys.stderr.write(f"  scanning {label} ({venv})\n")
        try:
            packages = run_piplicenses(python)
        except (RuntimeError, json.JSONDecodeError) as exc:
            warnings.append(f"{label}: pip-licenses failed — {exc}")
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
            key = (pkg.get("Name", ""), pkg.get("Version", ""))
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
    return str(value if value is not None else "").replace("|", "\\|").strip() or "—"


def render(per_component: dict[str, list[dict]], warnings: list[str],
           hand_block: str) -> str:
    rows = merged(per_component)
    flagged = attention(rows)
    lines: list[str] = []
    add = lines.append

    add("<!-- DRAFT FOR COUNSEL — NOT LEGAL ADVICE. Generated 2026-08-17 for")
    add("     docs/COMMERCIAL_READINESS.md item 3.")
    add("     GENERATED FILE — the pip sections below are produced by")
    add("     `python tools/gen_notices.py`. Edit that script, not these tables.")
    add("     The block between <!-- BEGIN HAND-MAINTAINED --> and")
    add("     <!-- END HAND-MAINTAINED --> is written by hand and is preserved")
    add("     verbatim across regeneration — it carries the components pip")
    add("     cannot see, which is where every copyleft obligation actually is.")
    add("     TODO(legal): replace \"Cablewrap Creative\" with the registered")
    add("     legal entity name. The placeholder was inferred from the")
    add("     operator's email domain and is almost")
    add("     certainly NOT the correct contracting entity — confirm before use.")
    add("     TODO(legal): confirm which of these components are actually")
    add("     CONVEYED to a customer versus merely present in a developer venv;")
    add("     the tables below are the venvs, not the shipped artefacts. -->")
    add("")
    add("# CC Sync — third-party notices")
    add("")
    add("**Draft of 2026-08-17. DRAFT FOR COUNSEL — not legal advice.**")
    add("")
    add("CC Sync is proprietary software (see `LICENSE`). It incorporates, links")
    add("against, or arranges the download of the third-party components listed")
    add("here. Each remains licensed by its own author under its own terms, which")
    add("prevail over `LICENSE` for that component.")
    add("")
    add("**How to read the verification column.** `metadata` means the fact came")
    add("out of the installed distribution's own metadata via `pip-licenses`, and")
    add("`+text` means the distribution also ships the licence text on disk — both")
    add("are VERIFIED. Anything in the hand-maintained section marked *stated from")
    add("knowledge — confirm* was not verified against an artefact on this machine")
    add("and must be checked before this document is relied on.")
    add("")

    if flagged:
        add("## LICENCES NEEDING ATTENTION")
        add("")
        add("Copyleft or otherwise non-permissive licences found in the venvs. Being")
        add("listed here is not a finding of non-compliance — it means a human must")
        add("decide whether the way we ship this one is compliant. See the")
        add("\"LGPL components that remain\" subsection for the ones already reasoned")
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
        add(f"{desc}. Venv: `{venv}` — {len(packages)} package(s).")
        add("")
        add("| Package | Version | Licence | Home page |")
        add("|---|---|---|---|")
        for pkg in packages:
            add(f"| `{esc(pkg.get('Name'))}` | {esc(pkg.get('Version'))} | "
                f"{esc(pkg.get('License'))} | {esc(pkg.get('URL'))} |")
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
    add(BEGIN_SENTINEL)
    add(hand_block)
    add(END_SENTINEL)
    add("")
    return "\n".join(lines)


DEFAULT_HAND_BLOCK = """
## Non-pip components (hand-maintained)

TODO(legal): this section has never been filled in. Everything conveyed to a
customer that is not a pip package belongs here — rclone, Syncthing, ffmpeg,
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
    args = ap.parse_args(argv)

    out_path = OUT_PATH if args.out == "-" else Path(args.out)
    hand_block = existing_hand_block(out_path)
    per_component, warnings = collect()
    if not per_component:
        sys.stderr.write("ERROR: no venv could be scanned; nothing to generate\n")
        return 2
    rendered = render(per_component, warnings, hand_block)

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
        # Through the BUFFER: this document is full of em-dashes, and a
        # Windows console stdout defaults to cp1252, which turns `--out -`
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
