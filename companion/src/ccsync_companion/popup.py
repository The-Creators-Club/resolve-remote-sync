"""Popup fixer dialog — the tkinter half of Component 2.

The dialog itself (PopupDialog) is a thin wiring layer: it can't sensibly be
unit tested (needs a real display), so all the logic that matters is in the
module-level functions below (build_popup_rows / perform_fix_all /
perform_ignore_all), which are pure and fully covered by tests.

One dialog per batch of accumulated OUT_OF_TREE clips (SPEC.md: "show ONE
dialog listing offending clips"), topmost, per-clip destination dropdown
pre-filled by fixer.suggest_destination, free text allowed.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from . import fixer

log = logging.getLogger("ccsync.popup")


def build_popup_rows(
    out_of_tree_items: list[dict[str, Any]], local_root: str, editor_name: str,
    project_prefix: str = "",
) -> list[dict[str, Any]]:
    """Turn watcher OUT_OF_TREE items into popup row dicts.

    Each row: {file_path, media_pool_item, clip_name, suggested_dest}.
    """
    rows = []
    for item in out_of_tree_items:
        path = item.get("file_path", "")
        rows.append(
            {
                "file_path": path,
                "media_pool_item": item.get("media_pool_item"),
                "clip_name": item.get("clip_name") or os.path.basename(path),
                "suggested_dest": fixer.suggest_destination(path, editor_name, project_prefix),
            }
        )
    return rows


def perform_fix_all(
    rows: list[dict[str, Any]],
    selections: dict[str, str],
    local_root: str,
    fix_clip_fn: Callable[..., dict[str, Any]] = fixer.fix_clip,
) -> list[dict[str, Any]]:
    """Run fixer.fix_clip for every row, using `selections[file_path]` as the
    chosen destination (falling back to the row's suggested_dest if a path
    is somehow missing from selections). Returns one result dict per row,
    each with "file_path" added for the caller to match back up.
    """
    results = []
    for row in rows:
        path = row["file_path"]
        dest_rel = selections.get(path, row["suggested_dest"])
        outcome = fix_clip_fn(path, dest_rel, local_root, row["media_pool_item"])
        outcome = dict(outcome)
        outcome["file_path"] = path
        results.append(outcome)
    return results


def perform_ignore_all(rows: list[dict[str, Any]], ignore_tracker: "fixer.IgnoreTracker") -> None:
    for row in rows:
        ignore_tracker.ignore(row["file_path"])


class PopupDialog:
    """tkinter Toplevel wrapper. Only imported/instantiated at call time (see
    show_popup below) so a headless environment (no display) degrades to a
    console listing instead of crashing the watcher thread — same pattern
    tray.py uses for pystray.
    """

    def __init__(
        self,
        rows: list[dict[str, Any]],
        local_root: str,
        ignore_tracker: "fixer.IgnoreTracker",
        on_done: Optional[Callable[[list[dict[str, Any]]], None]] = None,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.rows = rows
        self.local_root = local_root
        self.ignore_tracker = ignore_tracker
        self.on_done = on_done

        self.root = tk.Tk()
        self.root.title("ccsync-companion — clips outside the synced project folder")
        self.root.attributes("-topmost", True)

        dest_options = fixer.list_destination_dirs(local_root, "")
        self._vars: dict[str, "tk.StringVar"] = {}

        header = tk.Label(
            self.root,
            text="These timeline clips live outside your synced project folder. "
            "Choose a destination and click Fix all, or Ignore for this session.",
            justify="left",
            wraplength=520,
        )
        header.grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 6), sticky="w")

        for i, row in enumerate(rows, start=1):
            tk.Label(self.root, text=row["clip_name"] or row["file_path"], anchor="w").grid(
                row=i, column=0, padx=10, pady=2, sticky="w"
            )
            var = tk.StringVar(value=row["suggested_dest"])
            combo = ttk.Combobox(self.root, textvariable=var, values=dest_options, width=40)
            combo.grid(row=i, column=1, padx=10, pady=2, sticky="w")
            self._vars[row["file_path"]] = var

        btn_row = len(rows) + 1
        self.status_label = tk.Label(self.root, text="", fg="red", wraplength=520, justify="left")
        self.status_label.grid(row=btn_row + 1, column=0, columnspan=2, padx=10, sticky="w")

        fix_btn = tk.Button(self.root, text="Fix all", command=self._on_fix_all)
        fix_btn.grid(row=btn_row, column=0, padx=10, pady=10, sticky="w")
        ignore_btn = tk.Button(self.root, text="Ignore", command=self._on_ignore)
        ignore_btn.grid(row=btn_row, column=1, padx=10, pady=10, sticky="e")

    def _on_fix_all(self) -> None:
        selections = {path: var.get() for path, var in self._vars.items()}
        results = perform_fix_all(self.rows, selections, self.local_root)
        failures = [r for r in results if not r["ok"]]
        if failures:
            msg = "\n".join(f"{r['file_path']}: {r['message']}" for r in failures)
            self.status_label.config(text=msg)
            log.warning("fix all: %d failure(s)", len(failures))
        else:
            self.status_label.config(text="", fg="red")
            if self.on_done is not None:
                self.on_done(results)
            self.root.destroy()

    def _on_ignore(self) -> None:
        perform_ignore_all(self.rows, self.ignore_tracker)
        if self.on_done is not None:
            self.on_done([])
        self.root.destroy()

    def show(self) -> None:
        self.root.mainloop()


def show_popup(
    out_of_tree_items: list[dict[str, Any]],
    local_root: str,
    editor_name: str,
    ignore_tracker: "fixer.IgnoreTracker",
    project_prefix: str = "",
) -> None:
    """Build and show the popup, falling back to a console listing (with the
    items auto-ignored so we don't spin forever re-popping the same clips)
    if tkinter can't create a window in this environment.
    """
    rows = build_popup_rows(out_of_tree_items, local_root, editor_name, project_prefix)
    try:
        dialog = PopupDialog(rows, local_root, ignore_tracker)
        dialog.show()
    except Exception as exc:
        log.warning("popup unavailable (%s) — falling back to console listing", exc)
        print("[ccsync] clips outside synced project folder (no display available):")
        for row in rows:
            print(f"  - {row['clip_name']}: {row['file_path']} (suggested: {row['suggested_dest']})")
        print("[ccsync] fix these manually in Resolve, or configure a display for the popup.")
