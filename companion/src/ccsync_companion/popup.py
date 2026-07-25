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
import time
from collections import deque
from typing import Any, Callable, Optional

from . import fixer, resolve_bridge

log = logging.getLogger("ccsync.popup")


def human_bytes(n: Optional[int]) -> str:
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "?"


def human_eta(seconds: Optional[float]) -> str:
    try:
        secs = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if secs <= 0:
        return "almost done"
    if secs < 60:
        return f"~{secs} sec left"
    if secs < 3600:
        return f"~{secs // 60} min left"
    return f"~{secs // 3600}h {(secs % 3600) // 60}m left"


class RateEstimator:
    """Bytes/sec over a short rolling window, NOT a cumulative average.

    A cumulative average takes minutes to react when SMB throughput changes,
    which is the opposite of what an editor staring at a stalled-looking
    dialog needs (AUDIT_2 UX-9). Thread-safe enough for one writer.
    """

    def __init__(self, window_seconds: float = 6.0, clock: Callable[[], float] = time.monotonic):
        self.window_seconds = window_seconds
        self._clock = clock
        self._samples: deque[tuple[float, int]] = deque()

    def observe(self, total_bytes_done: int) -> None:
        now = self._clock()
        self._samples.append((now, int(total_bytes_done)))
        cutoff = now - self.window_seconds
        while len(self._samples) > 2 and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def speed_bps(self) -> Optional[float]:
        if len(self._samples) < 2:
            return None
        (t0, b0), (t1, b1) = self._samples[0], self._samples[-1]
        elapsed = t1 - t0
        if elapsed <= 0 or b1 < b0:
            return None
        return (b1 - b0) / elapsed

    def eta_seconds(self, done: int, total: int) -> Optional[float]:
        speed = self.speed_bps()
        if not speed or total <= 0 or done >= total:
            return None
        return (total - done) / speed


def format_file_progress(name: str, done: int, total: int, speed_bps: Optional[float],
                         eta_seconds: Optional[float], placeholder: bool = False) -> str:
    """e.g. Copying "A001_C012.braw" — 4.1 GB of 12.7 GB · 33 MB/s · ~4 min left

    While a cloud placeholder is still hydrating (`placeholder` set and no
    bytes moved yet) it says so INSTEAD, because the byte bar is honestly at
    0% and "Copying ... 0 B of 1.2 GB" for ten minutes is precisely the
    display that destroys trust and gets the window force-quit."""
    if not name:
        return ""
    if placeholder and done <= 0:
        size = f" ({human_bytes(total)})" if total else ""
        return (f'Waiting for your cloud drive to download "{name}"{size} — '
                f'this can take a while')
    parts = [f'Copying "{name}"']
    detail = [f"{human_bytes(done)} of {human_bytes(total)}"] if total else []
    if speed_bps:
        detail.append(f"{human_bytes(int(speed_bps))}/s")
    eta = human_eta(eta_seconds)
    if eta:
        detail.append(eta)
    if detail:
        parts.append(" · ".join(detail))
    return " — ".join(parts)


def format_batch_progress(index: int, total: int, done: int, total_bytes: int) -> str:
    """e.g. File 35 of 69 — 128 GB of 402 GB done"""
    head = f"File {max(index, 1)} of {total}"
    if not total_bytes:
        return head
    return f"{head} — {human_bytes(done)} of {human_bytes(total_bytes)} done"


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
                # Carried through so the dialog's dropdown can be built from
                # the SAME prefix the suggestion used, instead of offering
                # un-prefixed destinations that never sync (AUDIT_2 CORE-H3).
                "effective_prefix": effective_prefix,
            }
        )
    return rows


def _safe_size(path: str) -> int:
    try:
        return int(os.path.getsize(path))
    except OSError:
        return 0


def batch_total_bytes(rows: list[dict[str, Any]]) -> int:
    """Sum of the selected rows' source sizes -- the denominator for the
    overall progress bar (UX-9)."""
    return sum(_safe_size(row.get("file_path", "")) for row in rows)


def placeholder_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows whose SOURCE is a cloud placeholder (Google Drive online-only,
    OneDrive Files On-Demand, ...) and must be downloaded before it can be
    copied. See fixer.is_placeholder."""
    return [row for row in rows if fixer.is_placeholder(row.get("file_path", ""))]


def preflight_summary(rows: list[dict[str, Any]]) -> str:
    """The warning shown BEFORE the copy starts.

    Measured root cause of the live 2026-07-25 incident: the sources were
    Google Drive online-only placeholders, so every open() blocked while
    Drive downloaded the file. This one line would have prevented the whole
    confusion -- the copy wasn't stuck, it was waiting on a cloud download
    that nothing mentioned."""
    online_only = placeholder_rows(rows)
    if not online_only:
        return ""
    return (
        f"{len(online_only)} of {len(rows)} files are online-only in your cloud drive "
        f"and have to download before they can be copied. That happens automatically, "
        f"but it can be slow — the bar will sit at 0% for those while they download."
    )


def perform_fix_all(
    rows: list[dict[str, Any]],
    selections: dict[str, str],
    local_root: str,
    fix_clip_fn: Callable[..., dict[str, Any]] = fixer.fix_clip,
    progress_fn: Optional[Callable[[int, int, dict[str, Any]], None]] = None,
    state_fn: Optional[Callable[[dict[str, Any]], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> list[dict[str, Any]]:
    """Run fixer.fix_clip for every row, using `selections[file_path]` as the
    chosen destination (falling back to the row's suggested_dest if a path
    is somehow missing from selections — every row must always resolve to a
    non-empty default). Returns one result dict per row, each with
    "file_path" added for the caller to match back up.

    `progress_fn(done, total, result)` is called after each row completes, so
    a caller running this on a worker thread can report progress.

    `state_fn(info)` is the RICH per-chunk channel added for UX-9 (kept
    separate from progress_fn rather than widening it, so every existing
    3-arg caller and test keeps working). `info` carries:
        index, total, name, file_bytes_done, file_bytes_total,
        batch_bytes_done, batch_bytes_total, stopped
    It fires several times per second during a large copy -- the whole point
    is that a 40 GB BRAW no longer parks the UI on one number for twenty
    minutes.

    `should_stop()` is checked BETWEEN files only ([ STOP AFTER THIS FILE ]).
    Never mid-file: aborting a copy in flight is exactly what leaves an
    orphaned multi-GB .ccsync-tmp for lane C to fan out (CORE-H5).

    NEITHER CALLBACK MAY TOUCH TK. This runs on a worker thread; Tk is not
    thread-safe and this process has already shown Tk instability
    (CORE-H8/CORE-M3). Publish to a shared dict and let a root.after tick
    read it.
    """
    results: list[dict[str, Any]] = []
    total = len(rows)
    batch_total = batch_total_bytes(rows)
    batch_done = 0
    stopped = False

    def publish(**kw: Any) -> None:
        if state_fn is None:
            return
        try:
            state_fn(kw)
        except Exception:
            log.exception("fix-all state callback failed")

    for index, row in enumerate(rows, start=1):
        if should_stop is not None:
            try:
                if should_stop():
                    stopped = True
                    log.info("fix all: stopped by the user after %d/%d", len(results), total)
                    break
            except Exception:
                log.exception("fix-all should_stop callback failed")

        path = row["file_path"]
        dest_rel = selections.get(path) or row["suggested_dest"]
        media_pool_items = row.get("media_pool_items")
        if media_pool_items is None:
            # back-compat with any caller still building rows the old way.
            media_pool_items = [row["media_pool_item"]] if "media_pool_item" in row else []

        name = row.get("clip_name") or os.path.basename(path)
        file_total = _safe_size(path)
        completed_before = batch_done
        # Checked ONCE per file, before the copy: a cloud placeholder makes
        # open()/read() block for the whole hydration, during which the
        # per-file bar legitimately reads 0% (see fixer.is_placeholder).
        placeholder = fixer.is_placeholder(path)
        if placeholder:
            log.info("fix all: %s is an online-only cloud file -- waiting for it to "
                     "download before copying", path)

        def _on_bytes(copied: int, file_bytes_total: int, _n=name, _i=index,
                      _before=completed_before, _ph=placeholder) -> None:
            publish(index=_i, total=total, name=_n,
                    file_bytes_done=copied, file_bytes_total=file_bytes_total,
                    batch_bytes_done=_before + copied, batch_bytes_total=batch_total,
                    placeholder=_ph, stopped=False)

        publish(index=index, total=total, name=name, file_bytes_done=0,
                file_bytes_total=file_total, batch_bytes_done=batch_done,
                batch_bytes_total=batch_total, placeholder=placeholder, stopped=False)

        try:
            outcome = fix_clip_fn(path, dest_rel, local_root, media_pool_items,
                                  on_bytes=_on_bytes)
        except TypeError:
            # A fix_clip double that predates on_bytes (tests, and any
            # caller injecting its own). Progress just stays coarse.
            outcome = fix_clip_fn(path, dest_rel, local_root, media_pool_items)

        outcome = dict(outcome)
        outcome["file_path"] = path
        results.append(outcome)
        batch_done += file_total

        if progress_fn is not None:
            try:
                progress_fn(len(results), total, outcome)
            except Exception:
                log.exception("fix-all progress callback failed")

    publish(index=len(results), total=total, name="", file_bytes_done=0,
            file_bytes_total=0, batch_bytes_done=batch_done,
            batch_bytes_total=batch_total, stopped=stopped)
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
        editor_name: str = "",
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        from . import theme

        self.rows = rows
        self.local_root = local_root
        self.ignore_tracker = ignore_tracker
        self.on_done = on_done
        self.editor_name = editor_name
        self._fixing = False
        # Progress state published BY THE WORKER, read only by the Tk timer
        # tick. Tk is not thread-safe and this process has already shown Tk
        # instability under cross-thread use (CORE-H8/CORE-M3), so the worker
        # never touches a widget -- it only assigns into this dict.
        self._progress_lock = threading.Lock()
        self._progress: dict[str, Any] = {}
        self._stop_requested = False
        self._rate = RateEstimator()
        self._tick_job = None
        # Rows of the run in flight, and the ones that failed (kept as ROWS,
        # not just names, so RETRY FAILED can re-run them with the same
        # destinations).
        self._batch_rows: list[dict[str, Any]] = []
        self._failed_rows: list[dict[str, Any]] = []

        self.root = tk.Tk()
        try:
            self._build(tk, ttk, theme, rows, local_root)
        except Exception:
            # A partially-built root that is never destroy()ed is exactly the
            # state that makes every SUBSEQUENT tk.Tk() in this process fail
            # -- which is what strands the sign-in and update dialogs
            # (AUDIT_2 CORE-M3 -> CORE-H8). show_popup()'s except branch only
            # sees the exception; it never had a handle on the root.
            try:
                self.root.destroy()
            except Exception:
                pass
            raise

    def _build(self, tk, ttk, theme, rows, local_root) -> None:
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

        # Per-row dropdown options, built from THAT row's project prefix and
        # the real editor name -- see fixer.list_destination_dirs / CORE-H3.
        # Cached per prefix: the tree walk is the expensive part and a batch
        # normally shares one prefix.
        options_cache: dict[str, list[str]] = {}

        def _dest_options_for(row: dict[str, Any]) -> list[str]:
            prefix = str(row.get("effective_prefix", "") or "")
            if prefix not in options_cache:
                options_cache[prefix] = fixer.list_destination_dirs(
                    local_root, self.editor_name, prefix
                )
            return options_cache[prefix]

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
            "Pick a destination — FIX ALL copies them in and relinks Resolve.\n"
            "Your original file is left exactly where it is — nothing is moved or deleted.",
            fg=theme.MUTED, wraplength=620,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 10))
        r += 1

        # FIX ALL / IGNORE at the TOP: with dozens of rows the button bar
        # scrolled off the bottom of the screen and was unreachable.
        btn_bar = tk.Frame(self.root, bg=theme.BG)
        btn_bar.grid(row=r, column=0, columnspan=2, sticky="e", pady=(0, 6))
        # "IGNORE" never said what its scope was (per-session only, see
        # fixer.IgnoreTracker) -- editors read it as "never show me this
        # again", or worse, as doing something to the file (AUDIT_2 UX-13).
        self._ignore_btn = theme.neon_button(
            tk, btn_bar, "SKIP FOR NOW (this session)", self._on_ignore, primary=False)
        self._ignore_btn.pack(side="left", padx=(0, 18))
        self._fix_btn = theme.neon_button(tk, btn_bar, "FIX ALL", self._on_fix_all, primary=True)
        self._fix_btn.pack(side="left")
        # Present only after a run that left failures behind -- a failed file
        # must be easy to retry, and until now the user couldn't even see
        # WHICH files failed (AUDIT_2 UX-9 + the 2026-07-25 incident).
        self._retry_btn = theme.neon_button(
            tk, btn_bar, "RETRY FAILED", self._on_retry_failed, primary=True)
        self._retry_btn.pack(side="left", padx=(18, 0))
        self._retry_btn.pack_forget()
        r += 1

        # Pre-flight: cloud placeholders have to download before they can be
        # read, which is what made a working FIX ALL look hung for twenty
        # minutes on 2026-07-25. Say it BEFORE the user clicks.
        self.status_label = _label(self.root, preflight_summary(rows), fg=theme.AMBER,
                                   font=theme.mono(9), wraplength=620)
        self.status_label.grid(row=r, column=0, columnspan=2, sticky="w", pady=(0, 6))
        r += 1

        # -- progress (UX-9) ------------------------------------------------
        # Hidden until FIX ALL starts. Two determinate bars: the per-file one
        # is the one that matters -- a single 40 GB BRAW used to leave the
        # batch counter frozen on one number for twenty-plus minutes, which
        # is indistinguishable from a hang and is what makes people
        # force-quit (and per CORE-H5 a force-quit mid-copy strands a
        # multi-GB partial).
        bar_style = theme.style_progressbar(ttk)
        self._progress_frame = tk.Frame(self.root, bg=theme.BG)
        self._progress_frame.grid(row=r, column=0, columnspan=2, sticky="we")
        self._progress_frame.grid_columnconfigure(0, weight=1)
        self._progress_frame.grid_remove()
        r += 1

        self._file_label = _label(self._progress_frame, "", fg=theme.TEXT,
                                  font=theme.mono(9), wraplength=620)
        self._file_label.grid(row=0, column=0, sticky="w")
        self._file_bar = ttk.Progressbar(self._progress_frame, style=bar_style,
                                         mode="determinate", maximum=1000)
        self._file_bar.grid(row=1, column=0, sticky="we", pady=(2, 8))
        self._batch_label = _label(self._progress_frame, "", fg=theme.MUTED,
                                   font=theme.mono(9), wraplength=620)
        self._batch_label.grid(row=2, column=0, sticky="w")
        self._batch_bar = ttk.Progressbar(self._progress_frame, style=bar_style,
                                          mode="determinate", maximum=1000)
        self._batch_bar.grid(row=3, column=0, sticky="we", pady=(2, 8))
        self._stop_btn = theme.neon_button(
            tk, self._progress_frame, "STOP AFTER THIS FILE", self._on_stop_after_file,
            primary=False,
        )
        self._stop_btn.grid(row=4, column=0, sticky="w", pady=(0, 6))

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
            combo = ttk.Combobox(rows_frame, textvariable=var, values=_dest_options_for(row),
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
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)

    def _on_close_request(self) -> None:
        """Refuse the X while a FIX ALL is in flight.

        Destroying the root ends mainloop(), so show_popup() returns and
        app._show_out_of_tree_popup()'s `finally` RELEASES _popup_active_lock
        -- while the daemon worker is still copying multi-GB files and
        calling ReplaceClip. A second popup, Scan whole project, or a
        consolidate could then start its own copy/relink pass over the same
        clips (AUDIT_2 CORE-M1)."""
        if self._fixing:
            try:
                self.status_label.config(
                    text="Still copying — closing now would leave half-copied files. "
                         "This window closes itself when it's done.")
                self.root.bell()
            except Exception:
                pass
            return
        self.root.destroy()

    def _on_retry_failed(self) -> None:
        """Re-run only the rows that failed. Same destinations, same rows --
        the usual cause is a cloud file that hadn't finished downloading, so
        a retry a minute later genuinely works."""
        if self._fixing or not self._failed_rows:
            return
        rows, self._failed_rows = self._failed_rows, []
        log.info("fix all: retrying %d failed file(s)", len(rows))
        self._run_fix(rows)

    def _on_fix_all(self) -> None:
        self._run_fix(self.rows)

    def _run_fix(self, rows: list[dict[str, Any]]) -> None:
        # Copying originals (multi-GB BRAW over SMB) is slow; doing it on the
        # UI thread froze the window ("Not Responding") until the OS killed
        # it. Run the copy+relink on a worker thread and marshal progress and
        # the final result back to the UI thread via root.after (the only
        # thread-safe way to touch tk widgets).
        if self._fixing or not rows:
            return
        self._fixing = True
        self._stop_requested = False
        self._batch_rows = rows
        self._rate = RateEstimator()
        selections = {path: var.get() for path, var in self._vars}
        try:
            self._fix_btn.config(state="disabled")
            self._ignore_btn.config(state="disabled")
            self._retry_btn.pack_forget()
            self._progress_frame.grid()
            self._stop_btn.config(state="normal")
        except Exception:
            pass
        preflight = preflight_summary(rows)
        self.status_label.config(
            text=(f"Copying {len(rows)} file(s) in. Your originals stay exactly where "
                  f"they are — nothing is moved or deleted."
                  + ("\n" + preflight if preflight else "")))

        def _publish(info):
            with self._progress_lock:
                self._progress = info

        def _worker():
            results = perform_fix_all(
                rows, selections, self.local_root,
                state_fn=_publish, should_stop=lambda: self._stop_requested,
            )
            self._safe_after(lambda: self._fix_done(results))

        threading.Thread(target=_worker, name="ccsync-fixall", daemon=True).start()
        self._schedule_tick()

    # -- progress rendering (Tk thread only) -------------------------------
    def _on_stop_after_file(self) -> None:
        """UX-9's cancel. Deliberately "after this file", never mid-file:
        aborting a copy in flight is exactly what leaves an orphaned multi-GB
        .ccsync-tmp for lane C to fan out to the fleet (CORE-H5)."""
        self._stop_requested = True
        try:
            self._stop_btn.config(state="disabled")
            self.status_label.config(
                text="Stopping after the current file finishes — please wait.")
        except Exception:
            pass

    def _schedule_tick(self) -> None:
        try:
            self._tick_job = self.root.after(250, self._tick)
        except Exception:
            self._tick_job = None

    def _tick(self) -> None:
        """Read the worker's published state and repaint. Runs on the Tk
        thread via root.after -- the worker never touches a widget."""
        try:
            with self._progress_lock:
                info = dict(self._progress)
            if info:
                self._render_progress(info)
        except Exception:
            log.exception("progress tick failed")
        if self._fixing:
            self._schedule_tick()

    def _render_progress(self, info: dict[str, Any]) -> None:
        batch_done = int(info.get("batch_bytes_done") or 0)
        batch_total = int(info.get("batch_bytes_total") or 0)
        self._rate.observe(batch_done)
        speed = self._rate.speed_bps()

        file_done = int(info.get("file_bytes_done") or 0)
        file_total = int(info.get("file_bytes_total") or 0)
        file_eta = self._rate.eta_seconds(file_done, file_total)
        self._file_label.config(
            text=format_file_progress(info.get("name", ""), file_done, file_total,
                                      speed, file_eta, bool(info.get("placeholder"))))
        self._batch_label.config(
            text=format_batch_progress(int(info.get("index") or 0),
                                       int(info.get("total") or 0),
                                       batch_done, batch_total))
        self._file_bar["value"] = int(1000 * file_done / file_total) if file_total else 0
        self._batch_bar["value"] = int(1000 * batch_done / batch_total) if batch_total else 0

    def _fix_done(self, results: list[dict[str, Any]]) -> None:
        self._fixing = False
        try:
            self._progress_frame.grid_remove()
        except Exception:
            pass
        batch = self._batch_rows or self.rows
        failures = [r for r in results if not r["ok"]]
        stopped_early = self._stop_requested and len(results) < len(batch)

        # Keep the actual ROWS, so RETRY FAILED can re-run exactly these with
        # the same destinations. The user could previously see only a count.
        by_path = {row["file_path"]: row for row in batch}
        self._failed_rows = [by_path[r["file_path"]] for r in failures if r["file_path"] in by_path]
        for r in failures:
            log.warning("fix all: FAILED %s -- %s", r["file_path"], r["message"])

        if failures or stopped_early:
            try:
                self._fix_btn.config(state="normal")
                self._ignore_btn.config(state="normal")
                if self._failed_rows:
                    self._retry_btn.pack(side="left", padx=(18, 0))
            except Exception:
                pass
            ok_count = len(results) - len(failures)
            if stopped_early and not failures:
                self.status_label.config(
                    text=f"Stopped — {ok_count} of {len(batch)} copied in, the rest "
                         f"were left alone. Nothing was moved or deleted.")
                log.info("fix all: stopped early at %d/%d", ok_count, len(batch))
                return
            # Name every failure (up to a readable cap) with its REASON, not
            # a bare "FAILED" -- the destination lives on an SMB share whose
            # metadata isn't refreshed until the handle closes, so nothing
            # outside this process can tell the user which files failed.
            shown = "\n".join(f"✗ {os.path.basename(r['file_path'])} — {r['message']}"
                              for r in failures[:12])
            more = f"\n… and {len(failures) - 12} more (see tray → Open log)" \
                if len(failures) > 12 else ""
            head = (f"Stopped — {ok_count} of {len(batch)} copied in"
                    if stopped_early else f"{ok_count} of {len(results)} copied in")
            hint = ""
            if any(r.get("placeholder") for r in failures):
                hint = ("\nThese are online-only cloud files. Make them available offline "
                        "in your cloud drive, then press RETRY FAILED.")
            self.status_label.config(
                text=f"{head}, {len(failures)} failed:\n{shown}{more}{hint}")
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


class ProgressWindow:
    """A standalone two-bar progress window driven by a worker thread.

    Consolidate's entire user-visible surface used to be four toasts, with a
    potentially MULTI-HOUR silence between the third and the fourth, no
    progress and no cancel -- even though run_consolidation already accepted
    a progress_fn and rclone_lane already populates bytes_done/speed_bps/
    eta_seconds every 10 s (AUDIT_2 UX-10).

    Threading contract, identical to PopupDialog's: `worker(publish, stop)`
    runs on a daemon thread and may ONLY call `publish(dict)`. Every widget
    touch happens on the Tk thread via root.after.

    `publish` accepts the same keys perform_fix_all's state_fn emits, plus an
    optional "headline" string for phases with no file list (e.g. the lane A
    upload). Falls back to headless (worker still runs, progress logged) when
    no display is available -- the copy must never depend on the window.
    """

    def __init__(self, title: str, subtitle: str = "") -> None:
        self.title = title
        self.subtitle = subtitle
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {}
        self._stop_requested = False
        self._rate = RateEstimator()
        self._done = threading.Event()
        self.root = None

    # -- worker-facing (thread-safe, never touches Tk) ------------------
    def publish(self, info: dict[str, Any]) -> None:
        with self._lock:
            self._state = dict(info)

    def should_stop(self) -> bool:
        return self._stop_requested

    def run(self, worker: Callable[[Callable[[dict], None], Callable[[], bool]], None]) -> None:
        """Start `worker` on a daemon thread and show the window until it
        finishes. Returns after the worker completes and the window closes."""
        def _worker_wrapper() -> None:
            try:
                worker(self.publish, self.should_stop)
            except Exception:
                log.exception("progress worker failed")
            finally:
                self._done.set()

        thread = threading.Thread(target=_worker_wrapper, name="ccsync-progress-worker",
                                  daemon=True)
        thread.start()
        try:
            self._show()
        except Exception as exc:
            log.warning("progress window unavailable (%s) -- continuing without it", exc)
            # The work MUST still complete; the window is decoration.
            while not self._done.wait(5.0):
                with self._lock:
                    info = dict(self._state)
                if info:
                    log.info("progress: %s | %s",
                             format_batch_progress(int(info.get("index") or 0),
                                                   int(info.get("total") or 0),
                                                   int(info.get("batch_bytes_done") or 0),
                                                   int(info.get("batch_bytes_total") or 0)),
                             info.get("headline") or info.get("name") or "")
        thread.join(timeout=1.0)

    def _show(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        from . import theme

        root = tk.Tk()
        self.root = root
        try:
            root.title(self.title)
            root.attributes("-topmost", True)
            root.configure(bg=theme.BG, padx=18, pady=14)
            bar_style = theme.style_progressbar(ttk)

            tk.Label(root, text=f"► {self.title}", bg=theme.BG, fg=theme.RED,
                     font=theme.mono(12, bold=True), anchor="w", justify="left").pack(anchor="w")
            tk.Label(root, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w")
            if self.subtitle:
                tk.Label(root, text=self.subtitle, bg=theme.BG, fg=theme.MUTED,
                         font=theme.mono(9), anchor="w", justify="left",
                         wraplength=560).pack(anchor="w", pady=(4, 8))

            self._file_label = tk.Label(root, text="", bg=theme.BG, fg=theme.TEXT,
                                        font=theme.mono(9), anchor="w", justify="left",
                                        wraplength=560)
            self._file_label.pack(anchor="w", fill="x")
            self._file_bar = ttk.Progressbar(root, style=bar_style, mode="determinate",
                                             maximum=1000, length=560)
            self._file_bar.pack(anchor="w", fill="x", pady=(2, 8))

            self._batch_label = tk.Label(root, text="", bg=theme.BG, fg=theme.MUTED,
                                         font=theme.mono(9), anchor="w", justify="left",
                                         wraplength=560)
            self._batch_label.pack(anchor="w", fill="x")
            self._batch_bar = ttk.Progressbar(root, style=bar_style, mode="determinate",
                                              maximum=1000, length=560)
            self._batch_bar.pack(anchor="w", fill="x", pady=(2, 8))

            self._stop_btn = theme.neon_button(tk, root, "STOP AFTER THIS FILE",
                                               self._on_stop, primary=False)
            self._stop_btn.pack(anchor="w", pady=(4, 0))

            # Closing the window must not abandon the copy -- it keeps
            # running either way, so refuse and point at the stop button.
            root.protocol("WM_DELETE_WINDOW", self._on_stop)
            root.after(250, self._tick)
            root.mainloop()
        finally:
            try:
                root.destroy()
            except Exception:
                pass
            self.root = None

    def _on_stop(self) -> None:
        self._stop_requested = True
        try:
            self._stop_btn.config(state="disabled")
            self._batch_label.config(text="Stopping after the current file finishes…")
        except Exception:
            pass

    def _tick(self) -> None:
        root = self.root
        if root is None:
            return
        try:
            with self._lock:
                info = dict(self._state)
            if info:
                batch_done = int(info.get("batch_bytes_done") or 0)
                batch_total = int(info.get("batch_bytes_total") or 0)
                self._rate.observe(batch_done)
                speed = info.get("speed_bps") or self._rate.speed_bps()
                file_done = int(info.get("file_bytes_done") or 0)
                file_total = int(info.get("file_bytes_total") or 0)
                eta = info.get("eta_seconds")
                if eta is None:
                    eta = self._rate.eta_seconds(file_done, file_total)
                headline = info.get("headline")
                self._file_label.config(
                    text=headline or format_file_progress(
                        info.get("name", ""), file_done, file_total, speed, eta,
                        bool(info.get("placeholder"))))
                self._batch_label.config(
                    text=format_batch_progress(int(info.get("index") or 0),
                                               int(info.get("total") or 0),
                                               batch_done, batch_total))
                self._file_bar["value"] = int(1000 * file_done / file_total) if file_total else 0
                self._batch_bar["value"] = (
                    int(1000 * batch_done / batch_total) if batch_total else 0)
        except Exception:
            log.exception("progress window tick failed")
        if self._done.is_set():
            try:
                root.quit()
            except Exception:
                pass
            return
        try:
            root.after(250, self._tick)
        except Exception:
            pass


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
        dialog = PopupDialog(rows, local_root, ignore_tracker, editor_name=editor_name)
        dialog.show()
    except Exception as exc:
        log.warning("popup unavailable (%s) — falling back to console listing", exc)
        # The docstring above promised the items are auto-ignored; the
        # fallback only print()ed them -- a no-op in the windowed build where
        # sys.stdout is None -- and never touched ignore_tracker, so the same
        # batch re-popped (and re-failed) every 300 s forever (AUDIT_2
        # CORE-M3). LOG it, and actually honour the promise.
        for row in rows:
            log.warning(
                "out of tree (no display): %s -> %s (suggested: %s)",
                row["clip_name"], row["file_path"], row["suggested_dest"],
            )
        log.warning(
            "%d clip(s) auto-skipped for this session -- fix them in Resolve, or use "
            "tray → Scan whole project once a display is available", len(rows),
        )
        try:
            perform_ignore_all(rows, ignore_tracker)
        except Exception:
            log.exception("fallback: could not record the skipped clips")
