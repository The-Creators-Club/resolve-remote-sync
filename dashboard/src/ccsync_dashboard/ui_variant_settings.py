"""The look's two site settings, written on their own path (UI port R24).

`ui_terminal_groups` and `ui_preview` are site_settings rows like any other,
but a change to either is NOT a site_history entry: that history's undo arms
on its newest entry and sends `expected_at`, it keeps only ten entries, and
an older build rolled back to would refuse the unknown key on every undo
click. So look changes go into their own capped meta list,
`ui_groups_history`, which the classic groups form shows.
"""
from __future__ import annotations

import sqlite3
from typing import Mapping

from fastapi import HTTPException

from . import db, site_store, ui_variant


def history(conn: sqlite3.Connection) -> list[dict]:
    entries = db.meta_get_json(conn, ui_variant.UI_GROUPS_HISTORY_KEY) or []
    return [e for e in entries if isinstance(e, dict)]


def apply(conn: sqlite3.Connection, admin: str, values: Mapping[str, str]) -> dict[str, str]:
    """Validate then write `values` (only UI keys). `site` deletes the row
    (back to the vendor default). Raises 422 naming the refusal. Caller
    commits and invalidates the manifest cache."""
    current = site_store.get_all(conn)
    plan: dict[str, str | None] = {}
    for key, raw in values.items():
        if key not in site_store.UI_KEYS:
            raise HTTPException(status_code=422, detail=f"{key}: not a look setting")
        text = str(raw or "").strip().lower()
        if text == "site":
            plan[key] = None
            continue
        try:
            plan[key] = site_store.validate(key, text)
        except site_store.SiteValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    now = db.utcnow_iso()
    written: dict[str, str] = {}
    for key, value in plan.items():
        before = current.get(key)
        if value is None:
            site_store.delete_key(conn, key)
            written[key] = "site"
        else:
            site_store.set_many(conn, {key: value}, updated_by=admin)
            written[key] = value
        if before != value:
            entries = history(conn)
            entries.insert(0, {"at": now, "by": admin, "key": key,
                               "from": before if before is not None else "site",
                               "to": value if value is not None else "site"})
            db.meta_set_json(conn, ui_variant.UI_GROUPS_HISTORY_KEY,
                             entries[:ui_variant.UI_GROUPS_HISTORY_KEEP])
    db.audit(conn, admin, "site.ui_look", "site", {"keys": sorted(written)})
    return written
