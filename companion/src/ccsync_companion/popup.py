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
import threading
from typing import Any, Callable, Optional

from . import fixer, resolve_bridge

log = logging.getLogger("ccsync.popup")


def dedupe_out_of_tree_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse timeline items that share the same source file (normalized
    case-insensitive path — same rule as fixer.IgnoreTracker/resolve_bridge)
    into one merged item per unique path.

    The same source clip is often cut onto several places in the timeline,
    which used to produce one popup row per *timeline item* rather than per
    *file* — duplicate rows, and (worse) a real bug: each row keyed its
    tk.StringVar by file_path, so when duplicates collided, the earlier
    row's StringVar lost its only Python reference and was garbage
    collected, which un-set the Tcl variable its (still-visible) Combobox
    was bound to, leaving that dropdown blank. Deduping up front means
    every row has a unique key and every StringVar stays alive.

    All of a path's original media pool items are preserved under
    "media_pool_items" (order preserved, first-seen order) so fixing the
    one merged row can relink every timeline item that referenced it, not
    just the first one seen.
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in items:
        path = item.get("file_path", "")
        key = resolve_bridge._norm_path(path)
        if key not in merged:
            order.append(key)
            new_item = dict(item)
            mpi = item.get("media_pool_item")
            new_item["media_pool_items"] = [mpi] if mpi is not None else []
            merged[key] = new_item
        else:
            mpi = item.get("media_pool_item")
            if mpi is not None:
                merged[key]["media_pool_items"].append(mpi)
    return [merged[key] for key in order]


def build_popup_rows(
    out_of_tree_items: list[dict[str, Any]], local_root: str, editor_name: str,
    project_prefix: str = "",
    server_roots: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    """Turn watcher OUT_OF_TREE items into popup row dicts — one row per
    unique source path (see dedupe_out_of_tree_items).

    Each row: {file_path, media_pool_items, clip_name, suggested_dest}.

    Per-row destination resolution order:
      1. `server_roots` (the dashboard's STICKY per-Resolve-project
         destination mapping — see selection.SelectionClient.get_project_roots)
         looked up by the item's "resolve_project_name", case-insensitively.
      2. The project actually open in Resolve matched locally against the
         tree's Projects/<year>/<series>/<project> dirs
         (fixer.match_project_dir).
      3. The static `project_prefix` (active_project config).
      4. The tree root (no prefix).
    Steps 2-4 are fixer.pick_project_prefix; step 1 short-circuits it when a
    server mapping exists for the open project.
    """
    project_dirs = fixer.list_project_dirs(local_root)
    deduped = dedupe_out_of_tree_items(out_of_tree_items)

    rows = []
    for item in deduped:
        path = item.get("file_path", "")
        resolve_project_name = item.get("resolve_project_name", "")
        server_prefix = None
        if server_roots:
            server_prefix = server_roots.get(resolve_project_name.strip().lower())
        if server_prefix is not None:
            effective_prefix = server_prefix
        else:
            effective_prefix = fixer.pick_project_prefix(resolve_project_name, project_dirs, project_prefix)
        rows.append(
            {
                "file_path": path,
                "media_pool_items": item.get("media_pool_items", []),
                "clip_name": item.get("clip_name") or os.path.basename(path),
                "suggested_dest": fixer.suggest_destination(path, editor_name, effective_prefix),
            }
        )
    return rows


def perform_fix_all(
    rows: list[dict[str, Any]],
    selections: dict[str, str],
    local_root: str,
    fix_clip_fn: Callable[..., dict[str, Any]] = fixer.fix_clip,
    progress_fn: Optional[Callable[[int, int, dict[str, Any]], None]] = None,
) -> list[dict[str, Any]]:
    """Run fixer.fix_clip for every row, using `selections[file_path]` as the
    chosen destination (falling back to the row's suggested_dest if a path
    is somehow missing from selections — every row must always resolve to a
    non-empty default). Returns one result dict per row, each with
    "file_path" added for the caller to match back up.

    `progress_fn(done, total, result)` is called after each row completes, so
    a caller running this on a worker thread can report progress. It must not
    touch UI directly from that thread — marshal back to the UI thread.
    """
    results = []
    total = len(rows)
    for row in rows:
        path = row["file_path"]
        dest_rel = selections.get(path) or row["suggested_dest"]
        media_pool_items = row.get("media_pool_items")
        if media_pool_items is None:
            # back-compat with any caller still building rows the old way.
            media_pool_items = [row["media_pool_item"]] if "media_pool_item" in row else []
        outcome = fix_clip_fn(path, dest_rel, local_root, media_pool_items)
        outcome = dict(outcome)
        outcome["file_path"] = path
        results.append(outcome)
        if progress_fn is not None:
            try:
                progress_fn(len(results), total, outcome)
            except Exception:
                log.exception("fix-all progress callback failed")
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
        self.root.grid_columnconfigure(0, weight=1)

        combo_style = theme.style_combobox(ttk)
        # dropdown list (a separate Listbox popdown) has to be themed globally
        self.root.option_add("*TCombobox*Listbox.background", theme.FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", theme.TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", theme.RED_DIM)
        self.root.option_add("*TCombobox*Listbox.selectForeground", theme.TEXT)
        self.root.option_add("*TCombobox*Listbox.font", theme.mono(9))

        dest_options = fixer.list_destination_dirs(local_root, "")
        # One (file_path, StringVar) pair per row, kept as a list rather than
        # a dict keyed by file_path: build_popup_rows already guarantees
        # unique paths (see dedupe_out_of_tree_items), but a list is
        # collision-proof by construction, and collisions here are exactly
        # what caused the real "dest dropdown goes blank" bug — a later
        # row's StringVar silently replacing (and thereby garbage-collecting
        # and un-setting) an earlier row's, even though that row's Combobox
        # widget was still on screen bound to it.
        self._vars: list[tuple[str, "tk.StringVar"]] = []

        def _label(parent, text, **kw):
            defaults = dict(bg=theme.BG, fg=theme.TEXT, font=theme.mono(10),
                            justify="left", anchor="w")
            defaults.update(kw)
            return tk.Label(parent, text=text, **defaults)

        r = 0
        _label(self.root, "► MEDIA OUTSIDE PROJECT TREE", fg=theme.RED,
               font=theme.mono(12, bold=True)).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        _label(self.root, theme.RULE, fg=theme.RED_DIM).grid(row=r, column=0, columnspan=2, sticky="we")
        r += 1
        _label(
            self.root,
            f"{len(rows)} timeline clip(s) live outside {local_root} and will NOT sync.\n"
            "Pick a destination — FIX ALL copies them in and relinks Resolve.",
            fg=theme.MUTED, wraplength=620,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 10))
        r += 1

        # FIX ALL / IGNORE at the TOP: with dozens of rows the button bar
        # scrolled off the bottom of the screen and was unreachable.
        btn_bar = tk.Frame(self.root, bg=theme.BG)
        btn_bar.grid(row=r, column=0, columnspan=2, sticky="e", pady=(0, 6))
        self._ignore_btn = theme.neon_button(tk, btn_bar, "IGNORE", self._on_ignore, primary=False)
        self._ignore_btn.pack(side="left", padx=(0, 18))
        self._fix_btn = theme.neon_button(tk, btn_bar, "FIX ALL", self._on_fix_all, primary=True)
        self._fix_btn.pack(side="left")
        self._fixing = False
        r += 1

        self.status_label = _label(self.root, "", fg=theme.AMBER, font=theme.mono(9), wraplength=620)
        self.status_label.grid(row=r, column=0, columnspan=2, sticky="w", pady=(0, 6))
        r += 1

        _label(self.root, theme.RULE, fg=theme.RED_DIM).grid(row=r, column=0, columnspan=2, sticky="we")
        r += 1

        # Scrollable row list (Canvas + inner Frame + Scrollbar — tkinter has
        # no built-in scrollable frame): everything above stays fixed/visible,
        # only the (potentially 30+ row) clip list scrolls.
        list_row = r
        self.root.grid_rowconfigure(list_row, weight=1)
        canvas_frame = tk.Frame(self.root, bg=theme.BG)
        canvas_frame.grid(row=list_row, column=0, columnspan=2, sticky="nsew")
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(canvas_frame, bg=theme.BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        rows_frame = tk.Frame(canvas, bg=theme.BG)
        rows_window = canvas.create_window((0, 0), window=rows_frame, anchor="nw")

        def _sync_scrollregion(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_inner_width(event):
            canvas.itemconfigure(rows_window, width=event.width)

        rows_frame.bind("<Configure>", _sync_scrollregion)
        canvas.bind("<Configure>", _sync_inner_width)

        def _on_mousewheel(event):
            delta = event.delta
            if delta:
                canvas.yview_scroll(-1 * int(delta / 120) or (-1 if delta > 0 else 1), "units")
            elif getattr(event, "num", None) == 4:
                canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(1, "units")

        canvas.bind("<MouseWheel>", _on_mousewheel)          # Windows / macOS
        canvas.bind("<Button-4>", _on_mousewheel)             # X11 scroll up
        canvas.bind("<Button-5>", _on_mousewheel)             # X11 scroll down

        rr = 0
        for row in rows:
            _label(rows_frame, f"▌ {row['clip_name'] or row['file_path']}",
                   font=theme.mono(10, bold=True)).grid(row=rr, column=0, columnspan=2, sticky="w")
            rr += 1
            _label(rows_frame, f"  {row['file_path']}", fg=theme.MUTED, font=theme.mono(8)).grid(
                row=rr, column=0, columnspan=2, sticky="w")
            rr += 1
            _label(rows_frame, "  dest:", fg=theme.RED_DIM).grid(row=rr, column=0, sticky="w")
            var = tk.StringVar(value=row["suggested_dest"])
            combo = ttk.Combobox(rows_frame, textvariable=var, values=dest_options,
                                 width=52, style=combo_style, font=theme.mono(9))
            combo.grid(row=rr, column=1, sticky="w", pady=(0, 8))
            self._vars.append((row["file_path"], var))
            rr += 1

        # Cap the window at ~80% of screen height (36+ rows would otherwise
        # render off-screen). Canvas widgets don't propagate their child's
        # size to their own requested size, so start the canvas sized to
        # the row list's full natural height (i.e. "as if" unscrolled) to
        # get an honest total window height, then -- only if that's over
        # budget -- shrink just the canvas (leaving the header/buttons/
        # status full size) and let the scrollbar take up the rest.
        rows_frame.update_idletasks()
        content_width = rows_frame.winfo_reqwidth()
        content_height = rows_frame.winfo_reqheight()
        canvas.configure(width=content_width, height=content_height)

        self.root.update_idletasks()
        max_total_height = int(self.root.winfo_screenheight() * 0.8)
        total_height = self.root.winfo_reqheight()
        if total_height > max_total_height:
            chrome_height = total_height - content_height  # everything but the row list
            canvas.configure(height=max(120, max_total_height - chrome_height))
            self.root.update_idletasks()

        self.root.geometry(f"{self.root.winfo_reqwidth()}x{self.root.winfo_reqheight()}")

    def _on_fix_all(self) -> None:
        # Copying originals (multi-GB BRAW over SMB) is slow; doing it on the
        # UI thread froze the window ("Not Responding") until the OS killed
        # it. Run the copy+relink on a worker thread and marshal progress and
        # the final result back to the UI thread via root.after (the only
        # thread-safe way to touch tk widgets).
        if self._fixing:
            return
        self._fixing = True
        selections = {path: var.get() for path, var in self._vars}
        try:
            self._fix_btn.config(state="disabled")
            self._ignore_btn.config(state="disabled")
        except Exception:
            pass
        self.status_label.config(text=f"FIXING 0/{len(self.rows)} — copying media, do not close…")

        def _progress(done, total, result):
            def _ui():
                tail = "" if result["ok"] else "  (last: FAILED)"
                self.status_label.config(text=f"FIXING {done}/{total} — copying media…{tail}")
            self._safe_after(_ui)

        def _worker():
            results = perform_fix_all(self.rows, selections, self.local_root, progress_fn=_progress)
            self._safe_after(lambda: self._fix_done(results))

        threading.Thread(target=_worker, name="ccsync-fixall", daemon=True).start()

    def _fix_done(self, results: list[dict[str, Any]]) -> None:
        self._fixing = False
        failures = [r for r in results if not r["ok"]]
        if failures:
            try:
                self._fix_btn.config(state="normal")
                self._ignore_btn.config(state="normal")
            except Exception:
                pass
            shown = "\n".join(f"✗ {os.path.basename(r['file_path'])}: {r['message']}"
                              for r in failures[:8])
            more = f"\n… and {len(failures) - 8} more" if len(failures) > 8 else ""
            ok_count = len(results) - len(failures)
            self.status_label.config(
                text=f"{ok_count}/{len(results)} fixed, {len(failures)} failed:\n{shown}{more}")
            log.warning("fix all: %d/%d failed", len(failures), len(results))
        else:
            self.status_label.config(text="")
            if self.on_done is not None:
                self.on_done(results)
            self.root.destroy()

    def _safe_after(self, fn: Callable[[], None]) -> None:
        """Schedule fn on the tk thread; ignore if the window is already gone."""
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def _on_ignore(self) -> None:
        perform_ignore_all(self.rows, self.ignore_tracker)
        if self.on_done is not None:
            self.on_done([])
        self.root.destroy()

    def show(self) -> None:
        self.root.mainloop()


def confirm_dialog(title: str, body: str, ok_label: str = "PROCEED") -> bool:
    """Modal neon confirm dialog. Returns True if the user clicked the OK
    button, False on cancel/close. Falls back to False (safe default: do
    nothing) if no display is available."""
    try:
        import tkinter as tk

        from . import theme
    except Exception as exc:
        log.warning("confirm dialog unavailable (%s) — defaulting to cancel", exc)
        return False

    result = {"ok": False}
    # tk.Tk() itself can raise/wedge when other Tk roots have run on sibling
    # threads in this process (Tcl is thread-touchy) -- treat ANY dialog
    # failure like "no display": log + safe-default False, never a silent
    # dead thread (that failure mode was seen live on the update dialog,
    # 2026-07-25).
    try:
        root = tk.Tk()
        root.title(title)
        root.attributes("-topmost", True)
        root.configure(bg=theme.BG, padx=18, pady=14)

        tk.Label(root, text=f"► {title}", bg=theme.BG, fg=theme.RED,
                 font=theme.mono(12, bold=True), justify="left", anchor="w").pack(anchor="w")
        tk.Label(root, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w")
        tk.Label(root, text=body, bg=theme.BG, fg=theme.TEXT, font=theme.mono(10),
                 justify="left", anchor="w").pack(anchor="w", pady=(6, 12))

        btn_bar = tk.Frame(root, bg=theme.BG)
        btn_bar.pack(anchor="e")

        def _ok():
            result["ok"] = True
            root.destroy()

        def _cancel():
            root.destroy()

        theme.neon_button(tk, btn_bar, "CANCEL", _cancel, primary=False).pack(side="left", padx=(0, 18))
        theme.neon_button(tk, btn_bar, ok_label, _ok, primary=True).pack(side="left")
        root.protocol("WM_DELETE_WINDOW", _cancel)
        root.mainloop()
    except Exception as exc:
        log.warning("confirm dialog failed (%s) — defaulting to cancel", exc)
        return False
    return result["ok"]


def show_popup(
    out_of_tree_items: list[dict[str, Any]],
    local_root: str,
    editor_name: str,
    ignore_tracker: "fixer.IgnoreTracker",
    project_prefix: str = "",
    server_roots: Optional[dict[str, str]] = None,
) -> None:
    """Build and show the popup, falling back to a console listing (with the
    items auto-ignored so we don't spin forever re-popping the same clips)
    if tkinter can't create a window in this environment.
    """
    rows = build_popup_rows(out_of_tree_items, local_root, editor_name, project_prefix, server_roots)
    try:
        dialog = PopupDialog(rows, local_root, ignore_tracker)
        dialog.show()
    except Exception as exc:
        log.warning("popup unavailable (%s) — falling back to console listing", exc)
        print("[ccsync] clips outside synced project folder (no display available):")
        for row in rows:
            print(f"  - {row['clip_name']}: {row['file_path']} (suggested: {row['suggested_dest']})")
        print("[ccsync] fix these manually in Resolve, or configure a display for the popup.")
