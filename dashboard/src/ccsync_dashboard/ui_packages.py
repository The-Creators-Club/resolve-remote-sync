"""The terminal Packages page's one server-side helper (UI redesign port,
phase 4, builder P4a, 2026-09-25; docs/UI_REDESIGN_PORT_PLAN.md 1.3, 5.3).

Kept out of ui.py because several builders edit that file at once during the
port. It adds no route and changes no data: the classic panel's context
(`ui._packages_and_feed`) is what both looks render.

``pkg_rollback_choices(rows, current)`` is a Jinja global for the "roll back
to" select on each served row. It is a SHORTCUT, not a replacement (wave 6):
it lists only the builds a plain MAKE CURRENT would accept, so the select
needs no typed override and no signature confirm, which a select option
cannot carry. The rule mirrors package_store.make_current_refusal's order:
not recalled, not blocked on the dashboard version, signed, the file on disk,
and for a companion either ever current (a rollback skips the soak) or soaked.
Every held build still has its own folded row with the full set of actions.
"""
from __future__ import annotations

from . import ui


def pkg_rollback_choices(rows, current) -> list[dict]:
    """The held builds of `current`'s kind and platform, older than it,
    newest first, that a plain MAKE CURRENT accepts."""
    if not current:
        return []
    kind = str(current.get("kind") or "")
    platform = str(current.get("platform") or "")
    cur_key = ui._version_sort_key(current.get("version"))
    out = []
    for p in rows or []:
        if p.get("is_current") or p.get("kind") != kind or p.get("platform") != platform:
            continue
        if p.get("retracted") or p.get("ordering_blocked"):
            continue
        if not p.get("signature") or not p.get("file_exists"):
            continue
        if kind == "companion" and not p.get("ever_current"):
            soak = p.get("soak") or {}
            if not soak.get("ok"):
                continue
        key = ui._version_sort_key(p.get("version"))
        if key == (-1,) or cur_key == (-1,) or key >= cur_key:
            continue
        out.append(p)
    out.sort(key=lambda r: ui._version_sort_key(r.get("version")), reverse=True)
    return out


ui.templates.env.globals["pkg_rollback_choices"] = pkg_rollback_choices
