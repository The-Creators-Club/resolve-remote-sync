"""The report fields each telemetry switch withholds: the dashboard's copy.

LG-1, `telemetry-opt-out-switches` (docs/LEGAL_GAP_FEATURES_PLAN.md section
4.1, 2026-09-25). The companion owns the table (`telemetry_policy.FIELDS`) and
withholds these fields before it sends; the dashboard strips the SAME fields
on arrival, from every companion version, while the site switch is off. That
second half is what makes a site switch true for a machine whose companion
predates the switches (correctness H3), so the two tables must never drift:
`tests/test_report_optouts.py` pins this copy equal to the companion's, and
the companion's own test pins it from the other side.

Format (the contract with the companion's copy): category -> tuple of dotted
paths into the report body. A segment ending in `[]` is a list, and the rest
of the path applies to each element. A path that ENDS at a key removes that
key (a model field goes back to its default, which is None or "").

Deliberate choices (the companion's, 2026-09-25; this copy follows them):
- Note J, answered: the dashboard's undo keys on the journal ID, but the id is
  `<project slug>/<file>` and the slug is the Resolve project name, lightly
  sanitised (companion `resolve_journal.project_slug`). So under
  `resolve_project` the journal's `project` is removed AND its `id` is MASKED
  to `withheld:project/<file>` (`opaque_journal_id`, the paths in MASKED),
  which names no project and which a companion with the switches maps back
  to its own journal. The same mask is applied here to a report from an older
  build, whose companion answers "not found" to such an id: undo from the
  dashboard stops working for that computer, and its project name is not
  stored, which is the direction the site switch promises.
- `sync_guard.sync_conflicts.count` stays: absent is how "no conflicts" is
  spelled, and a conflict is worth an admin's attention without its file
  name. `stray_projects` and `moved_project_dirs` go whole, so their counts
  read as "not reported", never zero.
- `media_tree` sits under `resolve_project` as well as its own category: the
  bin structure is keyed by project name, so switching off the name switches
  it off (the rule `db.clean_report_categories` also applies).
- Not listed, because sync or the editor's own action needs them (PRIVACY /
  TELEMETRY "still sent"): transfer names (`lanes[].transfers`, `completed`),
  `file_moves_applied`, and the Timeline Cards agent's `timeline`.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

log = logging.getLogger(__name__)

CATEGORIES = ("resolve_project", "local_manifest", "media_tree", "input_idle")

FIELDS: dict[str, tuple[str, ...]] = {
    "resolve_project": (
        "resolve_project",
        "capabilities.resolve.project",
        "sync_guard.resolve_health.open_project",
        "sync_guard.resolve_health.project_open",
        "resolve_journals[].project",
        "resolve_journals[].id",
        # G1a review round 1 (2026-09-25): an undo's answer quotes the
        # journal's project and the open one (resolve_bridge's retry and
        # refusal sentences), and the dashboard stores and shows it. MASKED,
        # not removed: state and ok still say what happened.
        "resolve_undo_applied[].detail",
        "media_tree",
    ),
    "local_manifest": (
        "local_manifest",
        "sync_guard.resolve_health.missing_clips",
        "sync_guard.resolve_health.non_canonical_refused",
        "sync_guard.sync_conflicts.paths",
        "sync_guard.stray_projects",
        "sync_guard.moved_project_dirs",
        # G1a review round 1: lane A's "skipped, exists" samples are file
        # names from that computer's tree. The counts stay.
        "sync_guard.skipped_exists.samples",
    ),
    "media_tree": (
        "media_tree",
    ),
    "input_idle": (
        "capabilities.idle_seconds",
    ),
}

# Paths whose value is REWRITTEN rather than removed, and how (the
# companion's MASKED, same keys, same function names).
OPAQUE_JOURNAL_PREFIX = "withheld:project/"
MASKED = {
    "resolve_journals[].id": "opaque_journal_id",
    "resolve_undo_applied[].detail": "undo_detail",
}

# What an undo answer says when it cannot be redacted at all (the
# companion's UNDO_DETAIL_WITHHELD, byte for byte).
UNDO_DETAIL_WITHHELD = "(detail withheld: this computer does not report project names)"
PROJECT_TOKEN = "<project>"

# resolve_bridge quotes a project name in curly quotes in every undo sentence
# that names one; a journal id is "<slug>/<stamp>.json" and follows "record ".
# Copied verbatim from the companion's telemetry_policy (G1a hand-off, landed
# by the final review 2026-09-25): name-agnostic on purpose, so it can be
# applied here to an OLDER build's answer, which never redacted its own.
_QUOTED_NAME = re.compile("“[^”]*”")
_JOURNAL_IN_TEXT = re.compile(r"(record )[^\r\n]*?([^/\\:\r\n]+\.json)(?=:|\s|$)")


def redact_undo_detail(detail: Any) -> str:
    """An undo answer's sentence with every quoted project name replaced and
    every journal id masked. Byte for byte the companion's."""
    try:
        text = str(detail or "")
        text = _QUOTED_NAME.sub("“" + PROJECT_TOKEN + "”", text)
        return _JOURNAL_IN_TEXT.sub(
            lambda m: m.group(1) + OPAQUE_JOURNAL_PREFIX + m.group(2), text)
    except Exception:
        return UNDO_DETAIL_WITHHELD


def opaque_journal_id(journal_id: Any) -> str:
    """"FF5 Civil Defence/20260925-101010.json" ->
    "withheld:project/20260925-101010.json". Idempotent, and byte for byte the
    companion's telemetry_policy.opaque_journal_id."""
    text = str(journal_id or "").replace("\\", "/")
    name = [p for p in text.split("/") if p]
    tail = name[-1] if name else ""
    if text.startswith(OPAQUE_JOURNAL_PREFIX):
        return text
    return OPAQUE_JOURNAL_PREFIX + tail


_MASKS = {"opaque_journal_id": opaque_journal_id, "undo_detail": redact_undo_detail}


def clean(names: Any) -> list[str]:
    """The known category names in `names`, sorted, with `resolve_project`
    implying `media_tree`. Anything else (a newer companion's fifth name, a
    non-string) is dropped. The same rule as db.clean_report_categories,
    kept here so this module stays importable without the database."""
    if isinstance(names, (str, bytes)) or not isinstance(names, Iterable):
        return []
    out = {str(n).strip() for n in names
           if isinstance(n, str) and n.strip() in CATEGORIES}
    if "resolve_project" in out:
        out.add("media_tree")
    return sorted(out)


def paths_for(withheld: Iterable[str]) -> list[str]:
    """Every dotted path the categories in `withheld` cover, de-duplicated."""
    seen: list[str] = []
    for name in clean(withheld):
        for path in FIELDS[name]:
            if path not in seen:
                seen.append(path)
    return seen


_MISSING = object()


def _is_model(obj: Any) -> bool:
    return hasattr(type(obj), "model_fields") and not isinstance(obj, dict)


def _get(obj: Any, key: str) -> Any:
    if obj is None:
        return _MISSING
    if isinstance(obj, dict):
        return obj.get(key, _MISSING)
    if _is_model(obj) and key in type(obj).model_fields:
        return getattr(obj, key, _MISSING)
    return _MISSING


def _field_default(model: Any, key: str) -> Any:
    field = type(model).model_fields.get(key)
    default = getattr(field, "default", None) if field is not None else None
    # A required field has pydantic's sentinel as its default; nothing on
    # these paths is required, but None is the safe answer if one ever is.
    if default is None or type(default).__name__ == "PydanticUndefinedType":
        return None
    return default


def _mask(obj: Any, key: str, mask: str) -> bool:
    current = _get(obj, key)
    if current is _MISSING or current is None:
        return False
    masked = _MASKS[mask](current)
    if masked == current:
        return False
    if isinstance(obj, dict):
        obj[key] = masked
    else:
        setattr(obj, key, masked)
    return True


def _remove(obj: Any, key: str) -> bool:
    if isinstance(obj, dict):
        if key in obj:
            del obj[key]
            return True
        return False
    if _is_model(obj) and key in type(obj).model_fields:
        current = getattr(obj, key, None)
        default = _field_default(obj, key)
        if current is None or current == default:
            return False
        setattr(obj, key, default)
        return True
    return False


def _strip_path(obj: Any, segments: list[str], mask: str | None = None) -> bool:
    if obj is None or not segments:
        return False
    head, rest = segments[0], segments[1:]
    is_list = head.endswith("[]")
    key = head[:-2] if is_list else head
    if not rest:
        if is_list:
            return False
        return _mask(obj, key, mask) if mask else _remove(obj, key)
    child = _get(obj, key)
    if child is _MISSING or child is None:
        return False
    if is_list:
        if not isinstance(child, list):
            return False
        hit = False
        for item in child:
            hit = _strip_path(item, rest, mask) or hit
        return hit
    return _strip_path(child, rest, mask)


class StripFailed(Exception):
    """A withheld field could be neither stripped nor dropped with its whole
    section. The caller must not write the payload."""


def _drop_section(payload: Any, head: str) -> None:
    """Take the whole top-level section `head` out, bypassing a model's
    __setattr__ (a `validate_assignment` or frozen model is exactly what
    made the per-field strip fail). Raises StripFailed when even that is
    impossible."""
    key = head[:-2] if head.endswith("[]") else head
    try:
        if isinstance(payload, dict):
            payload.pop(key, None)
            return
        if _is_model(payload) and key in type(payload).model_fields:
            field = type(payload).model_fields[key]
            factory = getattr(field, "default_factory", None)
            empty = factory() if callable(factory) else _field_default(payload, key)
            payload.__dict__[key] = empty
            if payload.__dict__.get(key) is empty:
                return
    except Exception as exc:  # noqa: BLE001
        raise StripFailed(f"section {key!r} could not be dropped") from exc
    raise StripFailed(f"section {key!r} could not be dropped")


def strip(payload: Any, withheld: Iterable[str]) -> list[str]:
    """Remove (or, for a MASKED path, rewrite) IN PLACE every field the
    categories in `withheld` cover, in a report body (a dict) or a parsed
    ReportIn (a pydantic model). Returns the paths that actually held
    something. A path the report does not carry is simply not there.

    FAILS CLOSED (G2a review round, point 5, 2026-09-25): the first build
    swallowed an exception on one path and carried on, so the value it could
    not strip was then written by api_report while the wording said it was
    withheld. Now a path that raises takes its whole top-level section with
    it, logged at ERROR; if even that fails, StripFailed propagates and the
    report is refused rather than stored with withheld data in it."""
    stripped: list[str] = []
    for path in paths_for(withheld):
        segments = path.split(".")
        try:
            if _strip_path(payload, segments, MASKED.get(path)):
                stripped.append(path)
        except Exception as exc:  # noqa: BLE001
            log.error("could not strip %s (%s: %s); dropping its whole section",
                      path, type(exc).__name__, exc)
            _drop_section(payload, segments[0])
            stripped.append(path)
    return stripped
