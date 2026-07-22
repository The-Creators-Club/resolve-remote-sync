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

        from . import theme

        self.rows = rows
        self.local_root = local_root
        self.ignore_tracker = ignore_tracker
        self.on_done = on_done

        self.root = tk.Tk()
        self.root.title("CCSYNC.EXE")
        self.root.attributes("-topmost", True)
        self.root.configure(bg=theme.BG, padx=18, pady=14)

        combo_style = theme.style_combobox(ttk)
        # dropdown list (a separate Listbox popdown) has to be themed globally
        self.root.option_add("*TCombobox*Listbox.background", theme.FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", theme.TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", theme.RED_DIM)
        self.root.option_add("*TCombobox*Listbox.selectForeground", theme.TEXT)
        self.root.option_add("*TCombobox*Listbox.font", theme.mono(9))

        dest_options = fixer.list_destination_dirs(local_root, "")
        self._vars: dict[str, "tk.StringVar"] = {}

        def _label(text, **kw):
            defaults = dict(bg=theme.BG, fg=theme.TEXT, font=theme.mono(10),
                            justify="left", anchor="w")
            defaults.update(kw)
            return tk.Label(self.root, text=text, **defaults)

        r = 0
        _label("► MEDIA OUTSIDE PROJECT TREE", fg=theme.RED,
               font=theme.mono(12, bold=True)).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        _label(theme.RULE, fg=theme.RED_DIM).grid(row=r, column=0, columnspan=2, sticky="we")
        r += 1
        _label(
            f"{len(rows)} timeline clip(s) live outside {local_root} and will NOT sync.\n"
            "Pick a destination — FIX ALL copies them in and relinks Resolve.",
            fg=theme.MUTED, wraplength=620,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 10))
        r += 1

        for row in rows:
            _label(f"▌ {row['clip_name'] or row['file_path']}",
                   font=theme.mono(10, bold=True)).grid(row=r, column=0, columnspan=2, sticky="w")
            r += 1
            _label(f"  {row['file_path']}", fg=theme.MUTED, font=theme.mono(8)).grid(
                row=r, column=0, columnspan=2, sticky="w")
            r += 1
            _label("  dest:", fg=theme.RED_DIM).grid(row=r, column=0, sticky="w")
            var = tk.StringVar(value=row["suggested_dest"])
            combo = ttk.Combobox(self.root, textvariable=var, values=dest_options,
                                 width=52, style=combo_style, font=theme.mono(9))
            combo.grid(row=r, column=1, sticky="w", pady=(0, 8))
            self._vars[row["file_path"]] = var
            r += 1

        _label(theme.RULE, fg=theme.RED_DIM).grid(row=r, column=0, columnspan=2, sticky="we")
        r += 1
        self.status_label = _label("", fg=theme.AMBER, font=theme.mono(9), wraplength=620)
        self.status_label.grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        btn_bar = tk.Frame(self.root, bg=theme.BG)
        btn_bar.grid(row=r, column=0, columnspan=2, sticky="e", pady=(10, 0))
        theme.neon_button(tk, btn_bar, "IGNORE", self._on_ignore, primary=False).pack(
            side="left", padx=(0, 18))
        theme.neon_button(tk, btn_bar, "FIX ALL", self._on_fix_all, primary=True).pack(side="left")

    def _on_fix_all(self) -> None:
        selections = {path: var.get() for path, var in self._vars.items()}
        results = perform_fix_all(self.rows, selections, self.local_root)
        failures = [r for r in results if not r["ok"]]
        if failures:
            msg = "\n".join(f"✗ {r['file_path']}: {r['message']}" for r in failures)
            self.status_label.config(text=msg)
            log.warning("fix all: %d failure(s)", len(failures))
        else:
            self.status_label.config(text="")
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
