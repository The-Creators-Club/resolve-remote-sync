"""Which report fields this computer withholds, and the one rule for it.

LG-1, docs/LEGAL_GAP_FEATURES_PLAN.md section 4.1 (2026-09-25). The cleared
PRIVACY and TELEMETRY documents promise four switches, per computer and for
the whole site: `resolve_project`, `local_manifest`, `media_tree` and
`input_idle`. This module is where each switch is turned into "these report
fields do not leave the machine".

THE FIELDS TABLE BELOW IS THE CONTRACT. The dashboard strips the same fields
on arrival (its copy is `dashboard/.../telemetry_fields.py`, pinned equal to
this one by a test on each side), because the site switch has to be true for
companions that predate this module too. Adding a report key that carries any
of the four kinds of data means adding a row here, then TELEMETRY.md's payload
table, then `tests/test_telemetry_disclosure.py`'s list; that test fails until
all three agree.

COLLECT, THEN WITHHOLD (plan ground rule, safety audit H2). Nothing here stops
a pass from running. The media-pool walk is the only caller of the stale-bridge
recovery (2026-08-12) and the proxy relink; the manifest walk is what
`sync_conflicts` is counted from. A switch only keeps their RESULTS out of the
report.

A LEAF MODULE: no import from the package, so the dashboard's parity test and
the setup wizard can load it by path, the way `transport.py` is loaded.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

RESOLVE_PROJECT = "resolve_project"
LOCAL_MANIFEST = "local_manifest"
MEDIA_TREE = "media_tree"
INPUT_IDLE = "input_idle"
CATEGORIES = (RESOLVE_PROJECT, LOCAL_MANIFEST, MEDIA_TREE, INPUT_IDLE)

# config.toml keys, one per category. Handed to the wizard (G8) by name.
# NEVER remote-controlled: these are not in machine_settings.ACCEPTS nor in the
# dashboard's MACHINE_SETTING_KEYS (safety audit L2), so the dashboard can
# never switch an editor's privacy switch back on.
CONFIG_KEYS = {name: f"report_{name}" for name in CATEGORIES}

# Paths into the report payload, per category. `a.b` walks dicts; `a[]`
# walks every element of a list. A path whose value is absent is a no-op.
# Each path is REMOVED from the payload (every one of these is optional on
# the dashboard's model, so absent reads as "not reported"), except the paths
# in MASKED, whose values are rewritten instead.
FIELDS: dict[str, tuple[str, ...]] = {
    RESOLVE_PROJECT: (
        "resolve_project",
        "capabilities.resolve.project",
        "sync_guard.resolve_health.open_project",
        "sync_guard.resolve_health.project_open",
        "resolve_journals[].project",
        "resolve_journals[].id",
        # G1a review round 1 (2026-09-25): the undo's answer names the
        # journal's project and the open one (resolve_bridge.undo_last_relink
        # refusals), and the dashboard stores and shows it. MASKED, not
        # removed: the state and ok still say what happened.
        "resolve_undo_applied[].detail",
        # The bin structure is keyed by project name, so this category
        # implies media_tree (effective() also switches it off).
        "media_tree",
    ),
    LOCAL_MANIFEST: (
        "local_manifest",
        "sync_guard.resolve_health.missing_clips",
        "sync_guard.resolve_health.non_canonical_refused",
        # The COUNT stays: absent-is-never-zero, and a conflict is still
        # worth an admin's attention without its file name.
        "sync_guard.sync_conflicts.paths",
        "sync_guard.stray_projects",
        "sync_guard.moved_project_dirs",
        # G1a review round 1 (2026-09-25): lane A's "skipped, exists" samples
        # are file names from this computer's tree. The counts stay.
        "sync_guard.skipped_exists.samples",
    ),
    MEDIA_TREE: (
        "media_tree",
    ),
    INPUT_IDLE: (
        # null already means "cannot tell, so NOT idle" end to end
        # (capabilities.py's first rule), so withholding it can only ever
        # cost this computer background work, never hand it some.
        "capabilities.idle_seconds",
    ),
}

# Note J (plan 4.1): the dashboard's undo route keys on the journal ID, and
# the id is "<project slug>/<file>", i.e. it carries the project name. So the
# id is rewritten to a form that names no project and that the companion can
# still map back (app._apply_resolve_undo). The prefix contains ':', which
# resolve_journal.project_slug never produces, so it can never be read as a
# real journal by a build that does not know it.
#
# THE COST (G1a review round 1, 2026-09-25): a companion older than the build
# carrying this module cannot map the id back. Handed a masked id it answers
# "failed: this computer no longer has the record withheld:project/...", and
# the dashboard retires the request. So while the SITE withholds
# resolve_project (the dashboard masks an older build's ids on arrival), undo
# from the dashboard needs a companion that carries this module; an older one
# can still undo from its own tray. Not masking would send the project name.
OPAQUE_JOURNAL_PREFIX = "withheld:project/"
MASKED = {
    "resolve_journals[].id": "opaque_journal_id",
    "resolve_undo_applied[].detail": "undo_detail",
}

# What an undo answer says when it cannot be redacted at all.
UNDO_DETAIL_WITHHELD = "(detail withheld: this computer does not report project names)"

# The report key that says which categories were withheld. Always sent by a
# build that knows it (empty when nothing is withheld), so "nothing withheld"
# can be told apart from "an older build".
OPTOUTS_KEY = "report_optouts"


def opaque_journal_id(journal_id: Any) -> str:
    """"FF5 Civil Defence/20260925-101010.json" -> "withheld:project/20260925-101010.json"."""
    text = str(journal_id or "").replace("\\", "/")
    name = [p for p in text.split("/") if p]
    tail = name[-1] if name else ""
    if text.startswith(OPAQUE_JOURNAL_PREFIX):
        return text
    return OPAQUE_JOURNAL_PREFIX + tail


# resolve_bridge quotes a project name in curly quotes in every undo sentence
# that names one; a journal id is "<slug>/<stamp>.json" and follows "record ".
_QUOTED_NAME = re.compile("\u201c[^\u201d]*\u201d")
_JOURNAL_IN_TEXT = re.compile(r"(record )[^\r\n]*?([^/\\:\r\n]+\.json)(?=:|\s|$)")


def redact_undo_detail(detail: Any) -> str:
    """An undo answer's sentence with every quoted project name replaced and
    every journal id masked. Name-agnostic on purpose, so the dashboard can
    apply it to an older build's answer; the companion first replaces the
    names it knows (app._withheld_undo_detail)."""
    try:
        text = str(detail or "")
        text = _QUOTED_NAME.sub("\u201c" + PROJECT_TOKEN + "\u201d", text)
        return _JOURNAL_IN_TEXT.sub(
            lambda m: m.group(1) + OPAQUE_JOURNAL_PREFIX + m.group(2), text)
    except Exception:
        return UNDO_DETAIL_WITHHELD


_MASKS = {"opaque_journal_id": opaque_journal_id, "undo_detail": redact_undo_detail}


def _switch_value(value: Any) -> bool:
    """A local switch's value. Absent keeps today's behaviour (on). A value
    that is present but not a bool is read as OFF: the wrong-typed direction
    that withholds is the one that cannot surprise the person who wrote it,
    and withholding never stops sync. config.validate_config warns about it."""
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return False


def local_switches(cfg: Optional[Mapping[str, Any]]) -> dict[str, bool]:
    """This computer's own four switches, True = reported."""
    cfg = cfg or {}
    return {name: _switch_value(cfg.get(CONFIG_KEYS[name])) for name in CATEGORIES}


def site_switches(site: Optional[Mapping[str, Any]]) -> dict[str, bool]:
    """The site's four switches from a normalised manifest, True = reported.

    Only a real JSON `false` switches a category off. Absent, a lost cache or
    a manifest from an older dashboard is "all on", which is safe because the
    dashboard enforces the site policy on arrival as well (plan 3.3)."""
    block = (site or {}).get("telemetry") if isinstance(site, Mapping) else None
    block = block if isinstance(block, Mapping) else {}
    return {name: block.get(name) is not False for name in CATEGORIES}


def effective(cfg: Optional[Mapping[str, Any]],
              site: Optional[Mapping[str, Any]]) -> dict[str, bool]:
    """local AND site, with resolve_project off forcing media_tree off. THE
    only copy of the rule on this side."""
    local = local_switches(cfg)
    remote = site_switches(site)
    eff = {name: bool(local[name] and remote[name]) for name in CATEGORIES}
    if not eff[RESOLVE_PROJECT]:
        eff[MEDIA_TREE] = False
    return eff


def withheld(eff: Mapping[str, bool]) -> list[str]:
    """The sorted names of the categories that are off."""
    return sorted(name for name in CATEGORIES if not eff.get(name, True))


def site_withheld(site: Optional[Mapping[str, Any]]) -> list[str]:
    """What the site alone has switched off (the settings window greys these)."""
    remote = site_switches(site)
    return sorted(name for name in CATEGORIES if not remote[name])


def _parse(path: str) -> list[tuple[str, bool]]:
    out = []
    for part in path.split("."):
        if part.endswith("[]"):
            out.append((part[:-2], True))
        else:
            out.append((part, False))
    return out


def _apply(node: Any, steps: list[tuple[str, bool]], mask: Optional[str]) -> Any:
    """Return `node` with the path removed or masked. Copy-on-write: a getter's
    cached dict (capabilities keeps one) must not be edited in place."""
    if not isinstance(node, dict) or not steps:
        return node
    (key, is_list), rest = steps[0], steps[1:]
    if key not in node:
        return node
    new = dict(node)
    if not rest:
        if is_list:
            return new
        if mask in _MASKS:
            new[key] = _MASKS[mask](new[key])
        else:
            new.pop(key, None)
        return new
    child = new[key]
    if is_list:
        if isinstance(child, list):
            new[key] = [_apply(item, rest, mask) for item in child]
        return new
    new[key] = _apply(child, rest, mask)
    return new


def strip(payload: Mapping[str, Any], eff: Mapping[str, bool]) -> dict[str, Any]:
    """The payload without the fields of every category that is off. Never
    raises (a report section must never be the reason a machine drops off
    the fleet grid, B6): on an unexpected shape the field is left alone and
    the dashboard's own strip still applies."""
    out: dict[str, Any] = dict(payload)
    for name in withheld(eff):
        for path in FIELDS[name]:
            try:
                out = _apply(out, _parse(path), MASKED.get(path))
            except Exception:
                continue
    return out


# -- diagnostics redaction ---------------------------------------------------
#
# A NEW helper (plan 4.1): crash_report.redact and drive_swap._redacted do
# other jobs. A diagnostics bundle is free text built from a dozen producers
# and the log tail, so a field table cannot reach into it; replacing the names
# and the paths is the only way to keep it useful and honest at once.

PROJECT_TOKEN = "<project>"
FILE_TOKEN = "<file>"
# A path under a root runs to the end of the line or to a delimiter a log
# line or a repr() puts after it.
_PATH_TAIL = r"[\\/][^\r\n'\"<>|,;)\]}]+"


def redact_text(text: str, names: Iterable[Any] = (),
                roots: Iterable[Any] = ()) -> str:
    """`text` with every path under one of `roots` cut to `<root>/<file>` and
    every whole-word occurrence of one of `names` replaced by `<project>`.

    Roots are matched case-insensitively and with either slash, because the
    same root is written `P:\\` by Windows and `P:/` by Python's own reprs.
    Names shorter than three characters are skipped: a project called "A"
    would otherwise eat every article in the bundle."""
    out = str(text or "")
    root_list = []
    for root in roots or ():
        raw = str(root or "").strip().rstrip("\\/")
        if len(raw) >= 2:
            root_list.append(raw)
    # Longest first, so a root nested in another is cut at its own depth.
    for raw in sorted(set(root_list), key=len, reverse=True):
        body = "".join(r"[\\/]" if ch in "\\/" else re.escape(ch) for ch in raw)
        # Not preceded by a word character: the drive root "P:" must not
        # match the end of "http:" in a dashboard address.
        out = re.sub(r"(?<!\w)" + body + _PATH_TAIL, lambda m, r=raw: r + "/" + FILE_TOKEN, out,
                     flags=re.IGNORECASE)
    name_list = sorted({str(n).strip() for n in (names or ()) if str(n or "").strip()},
                       key=len, reverse=True)
    for name in name_list:
        if len(name) < 3:
            continue
        out = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", PROJECT_TOKEN, out,
                     flags=re.IGNORECASE)
    return out
