"""EULA acceptance — has the person using this machine agreed to the licence?

Added 2026-08-17 for docs/COMMERCIAL_READINESS.md item 3: shipping this to
paying customers means the software must be able to say, per machine, that
its licence was presented and accepted, and which version of it.

Who writes the record, who reads it:

    onboarding/steps.py (the setup wizard) WRITES ~/.ccsync/eula_accepted.json
    on ACCEPT -- it runs before the companion is installed, so the wizard is
    the only party that can have got consent by the time the tray first
    starts. This module READS that same file and gates the sync lanes on it
    (app.py's _start_lanes). The two halves are written against the schema
    below and MUST stay byte-compatible -- see the twin comment in
    onboarding/steps.py's EULA section.

The on-disk schema (~/.ccsync/eula_accepted.json), version 1:

    {
      "version":     "1.0",              # the EULA-VERSION marker accepted
      "accepted_at": "2026-08-17T09:15:00.123456+00:00",  # ISO-8601, UTC
      "eula_sha256": "<64 hex chars>"    # informational; see _text_sha256
    }

Unknown keys are ignored on read, so either half may add one without
breaking the other. `eula_sha256` is NOT checked by anything: it exists so a
support session can tell "accepted a document that has since been edited"
from "accepted the document we ship", without this module being able to
brick a machine over a whitespace change.

The bundled document is assets/EULA.md, a verbatim copy of docs/legal/EULA.md
(tests/test_eula.py pins them byte-identical, because a drifted copy means
the editor accepted something other than what counsel signed off). Its
version comes from the `<!-- EULA-VERSION: x.y -->` marker in that file --
parsed, never hardcoded, so bumping the marker is the whole of a re-consent.

FAIL OPEN when the bundled asset is missing entirely. A packaging mistake
(a build.spec datas entry forgotten -- exactly how assets/ works here, one
explicit file per line) would otherwise stop the sync lanes on EVERY editor
in the fleet at once, and this repo's standing rule is that a feature must
fail absent, never fatal: "the dashboard is what tells everyone whether
their footage is syncing" outranks a licence check the operator can chase
by other means. A MISSING ACCEPTANCE still blocks -- that is a real answer
("nobody agreed"), not an absence of one.

Never-raise ethos, as in identity.py/reporter.py: nothing here raises out to
callers on filesystem or parse failure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config as config_mod

log = logging.getLogger("ccsync.eula")

ACCEPTANCE_FILENAME = "eula_accepted.json"
EULA_ASSET_NAME = "EULA.md"

# The one place the marker's shape is written down in this component.
_VERSION_MARKER_RE = re.compile(r"<!--\s*EULA-VERSION:\s*([0-9][0-9A-Za-z.\-]*)\s*-->")

# What EULA_VERSION reads as when the bundled document could not be found or
# carries no marker: "we cannot verify anything", which acceptance_ok() turns
# into a pass (see the module docstring).
UNKNOWN_VERSION = ""


def asset_path() -> Optional[Path]:
    """Path to the bundled assets/EULA.md, or None if this build hasn't got
    it. Same lookup (and same None-not-raise contract) as theme.asset_path();
    duplicated rather than imported so a licence check never depends on the
    theme module."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "ccsync_companion" / "assets" / EULA_ASSET_NAME)
    candidates.append(Path(__file__).resolve().parent / "assets" / EULA_ASSET_NAME)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def bundled_text() -> str:
    """The bundled EULA as text, or "" when this build hasn't got it."""
    path = asset_path()
    if path is None:
        return ""
    try:
        # utf-8 (not ascii): the document uses em dashes and typographic
        # quotes throughout.
        return path.read_text(encoding="utf-8")
    except OSError:
        log.warning("could not read the bundled EULA at %s", path)
        return ""


def parse_version(text: str) -> str:
    """The `<!-- EULA-VERSION: x.y -->` marker's value, or UNKNOWN_VERSION."""
    match = _VERSION_MARKER_RE.search(text or "")
    return match.group(1) if match else UNKNOWN_VERSION


def _text_sha256(text: str) -> str:
    """sha256 of the document with newlines normalised to \\n.

    The wizard's copy and the companion's copy of the same document can
    differ in line endings (git's `* text=auto` checks .md out as CRLF on
    Windows, and a PyInstaller bundle carries whatever the build machine
    had), so hashing raw bytes would make the wizard and the tray disagree
    about a file they both got from docs/legal/EULA.md.
    """
    normalised = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


BUNDLED_TEXT = bundled_text()
# Parsed once at import: the document is baked into the build and cannot
# change under a running process.
EULA_VERSION = parse_version(BUNDLED_TEXT)


def acceptance_path() -> Path:
    """~/.ccsync/eula_accepted.json -- config_mod.CONFIG_DIR, the same
    directory identity.json lives in, and the exact path the onboarding
    wizard writes (steps.eula_acceptance_path())."""
    return config_mod.CONFIG_DIR / ACCEPTANCE_FILENAME


def read_acceptance(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """The acceptance record, or None when there isn't a usable one.
    Tolerant read -- missing, unreadable, or malformed all return None
    rather than raising (identity.load_identity's contract)."""
    target = Path(path) if path is not None else acceptance_path()
    try:
        # utf-8-sig for the same reason identity.load_identity uses it: a
        # Windows tool (PowerShell Set-Content, some editors) writing this
        # file prepends a BOM that a plain utf-8 read leaves in front of the
        # opening brace, and json rejects it.
        text = target.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        log.warning("EULA acceptance record at %s is not valid JSON -- ignoring it", target)
        return None
    if not isinstance(data, dict):
        return None
    return data


def record_acceptance(version: Optional[str] = None, *, path: Optional[Path] = None) -> None:
    """Write the acceptance record for `version` (defaults to the bundled
    EULA_VERSION). Temp file + replace, like identity.save_identity: not
    fsync-durable, but no reader ever sees a half-written record.

    Raises nothing the caller must handle beyond OSError -- a failure to
    persist is the one case worth surfacing, since silently "accepting"
    nothing would show the editor the same dialog forever."""
    target = Path(path) if path is not None else acceptance_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": str(version if version is not None else EULA_VERSION),
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "eula_sha256": _text_sha256(BUNDLED_TEXT),
    }
    tmp_path = target.with_name(target.name + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(target)


def version_tuple(version: Optional[str]) -> tuple[int, ...]:
    """"1.10" -> (1, 10). Numeric, NOT string, comparison: as strings
    "1.10" < "1.9", so a tenth bump of the document would read as older than
    its predecessor and silently stop asking anyone to re-accept. Unparseable
    components count as 0 rather than raising."""
    parts: list[int] = []
    for chunk in str(version or "").strip().split("."):
        digits = ""
        for char in chunk.strip():
            if not char.isdigit():
                break
            digits += char
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def version_at_least(have: Optional[str], want: Optional[str]) -> bool:
    """True when `have` >= `want`, compared component-wise with the shorter
    of the two zero-padded ("1.0" == "1.0.0")."""
    a, b = version_tuple(have), version_tuple(want)
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    return a >= b


def acceptance_problem(path: Optional[Path] = None) -> Optional[str]:
    """None when this machine may sync, else one sentence saying why not,
    written to be shown to the editor verbatim (identity._http_error_message
    sets that precedent)."""
    if not EULA_VERSION:
        # No document, or one with no marker: cannot verify. Fail open --
        # see the module docstring.
        log.warning(
            "no bundled licence agreement in this build (assets/%s) -- the acceptance "
            "check cannot run and is being SKIPPED so syncing is not blocked by a "
            "packaging fault", EULA_ASSET_NAME,
        )
        return None
    record = read_acceptance(path)
    if not record:
        return ("The CC Sync licence agreement has not been accepted on this machine. "
                "Re-run the CCSync setup wizard to read and accept it.")
    accepted = str(record.get("version") or "").strip()
    if not accepted:
        return ("The licence acceptance record on this machine is unreadable. "
                "Re-run the CCSync setup wizard to accept the agreement again.")
    if not version_at_least(accepted, EULA_VERSION):
        return (f"The CC Sync licence agreement has been updated (version {EULA_VERSION}; "
                f"this machine accepted {accepted}). Re-run the CCSync setup wizard to "
                "read and accept it.")
    return None


def acceptance_ok(path: Optional[Path] = None) -> bool:
    """True when the lanes may run: a record exists whose version is at
    least the bundled one -- or the bundled document is missing, which fails
    open on purpose."""
    return acceptance_problem(path) is None
