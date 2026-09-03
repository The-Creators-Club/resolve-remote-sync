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

from . import canon, fixer, resolve_bridge, ui_copy, ui_dispatch
from . import site as site_mod

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
    """e.g. Copying "A001_C012.braw": 4.1 GB of 12.7 GB · 33 MB/s · ~4 min left

    While a cloud placeholder is still hydrating (`placeholder` set and no
    bytes moved yet) it says so INSTEAD, because the byte bar is honestly at
    0% and "Copying ... 0 B of 1.2 GB" for ten minutes is precisely the
    display that destroys trust and gets the window force-quit."""
    if not name:
        return ""
    if placeholder and done <= 0:
        size = f" ({human_bytes(total)})" if total else ""
        return (f'Waiting for your cloud drive to download "{name}"{size}. '
                f'This can take a while')
    parts = [f'Copying "{name}"']
    detail = [f"{human_bytes(done)} of {human_bytes(total)}"] if total else []
    if speed_bps:
        detail.append(f"{human_bytes(int(speed_bps))}/s")
    eta = human_eta(eta_seconds)
    if eta:
        detail.append(eta)
    if detail:
        parts.append(" · ".join(detail))
    return ": ".join(parts)


def format_batch_progress(index: int, total: int, done: int, total_bytes: int) -> str:
    """e.g. File 35 of 69: 128 GB of 402 GB done"""
    head = f"File {max(index, 1)} of {total}"
    if not total_bytes:
        return head
    return f"{head}: {human_bytes(done)} of {human_bytes(total_bytes)} done"


class BatchControl:
    """The three user controls over a running copy batch, shared between the
    Tk thread (which SETS them from a button) and the copy worker (which only
    POLLS them).

    Plain threading.Events, same pattern as the older `_stop_requested` flag:
    the worker must never touch Tk and the Tk thread must never block on the
    worker, so a set/is_set pair is the entire handshake.

      STOP AFTER THIS FILE -> finish the file in flight, then stop (graceful;
                              the only control that existed before).
      SKIP THIS FILE       -> abandon the file in flight, CONTINUE the batch.
      CANCEL ALL           -> abandon the file in flight, stop the batch.

    The skip flag is per-file and is re-armed (cleared) by the batch loop
    before each file starts: a click that lands in the gap BETWEEN files
    would otherwise abandon the next file the user never saw copying.
    """

    def __init__(self) -> None:
        self._skip = threading.Event()
        self._cancel = threading.Event()
        self._stop_after_file = threading.Event()

    # -- Tk thread ------------------------------------------------------
    def request_skip_current(self) -> None:
        self._skip.set()

    def request_cancel_all(self) -> None:
        self._cancel.set()

    def request_stop_after_file(self) -> None:
        self._stop_after_file.set()

    def reset(self) -> None:
        """Re-arm for a fresh run (RETRY FAILED reuses the same control)."""
        self._skip.clear()
        self._cancel.clear()
        self._stop_after_file.clear()

    # -- worker thread --------------------------------------------------
    def should_abort_current(self) -> bool:
        """Poll handed to fixer.copy_with_progress -- true for either of the
        two mid-file controls."""
        return self._skip.is_set() or self._cancel.is_set()

    def cancel_all_requested(self) -> bool:
        return self._cancel.is_set()

    def should_stop(self) -> bool:
        """The between-files predicate: an explicit stop, or a cancel-all
        (which also has to end the batch, not just the current file)."""
        return self._stop_after_file.is_set() or self._cancel.is_set()

    def begin_file(self) -> None:
        self._skip.clear()


def summarize_fix_results(
    results: list[dict[str, Any]], batch_size: int, stopped_early: bool = False
) -> str:
    """The one-line headline over a finished batch.

    Skipped-by-the-user is a THIRD outcome, distinct from fixed and failed:
    reporting "3 fixed, 1 failed" for a file the user deliberately abandoned
    reads as a malfunction, and reporting it as fixed is a lie about a file
    that was never copied or relinked. Pure so the wording is testable
    without Tk."""
    fixed = sum(1 for r in results if r.get("ok"))
    skipped = sum(1 for r in results if r.get("aborted"))
    failed = len(results) - fixed - skipped
    parts = [f"{fixed} of {batch_size} copied in"]
    if skipped:
        parts.append(f"{skipped} skipped by you")
    if failed:
        parts.append(f"{failed} failed")
    head = ", ".join(parts)
    if stopped_early:
        head = f"Stopped: {head}"
        if len(results) < batch_size:
            head += f", {batch_size - len(results)} left alone"
    return head


def _relink_entry(item: dict[str, Any]) -> Any:
    """What to carry through a batch so the relink can still be made.

    The MediaPoolItem when the walk carried one -- so a batch built from the
    API walk is byte-identical to what it always was -- and otherwise the
    ITEM DICT, which carries "media_pool_uid" for
    resolve_bridge.resolve_media_pool_item() to look the object up with at
    the moment of the ReplaceClip. None when there is neither, i.e. nothing
    that could ever be relinked (library walk, 2026-08-26).
    """
    media_pool_item = item.get("media_pool_item")
    if media_pool_item is not None:
        return media_pool_item
    if str(item.get("media_pool_uid") or ""):
        return item
    return None


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
    just the first one seen. See _relink_entry for what an entry is: an
    object when the walk had one, the item dict (uid inside) when it did not.
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in items:
        path = item.get("file_path", "")
        key = resolve_bridge._norm_path(path)
        entry = _relink_entry(item)
        if key not in merged:
            order.append(key)
            new_item = dict(item)
            new_item["media_pool_items"] = [entry] if entry is not None else []
            merged[key] = new_item
        elif entry is not None:
            merged[key]["media_pool_items"].append(entry)
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
                # canon.basename, not os.path.basename: `path` is Resolve's
                # own "File Path", which on a Mac can be a canonical P:\
                # spelling -- posixpath.basename would answer the WHOLE path
                # and the row would show it where a filename belongs (MAC-3).
                "clip_name": item.get("clip_name") or canon.basename(path),
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


def destination_free_bytes(local_root: str) -> int:
    """Free space on the destination, or 0 when it cannot be measured.

    0 means "no answer", never "the disk is full": UX-9's line is dropped
    entirely rather than telling an editor their drive is empty because a
    stat failed."""
    if not local_root:
        return 0
    try:
        import shutil

        return int(shutil.disk_usage(local_root).free)
    except Exception:
        log.debug("could not measure free space on %s", local_root, exc_info=True)
        return 0


# UX-9 (usability sweep 2026-09-04): the point at which the batch is close
# enough to the free space that the editor is told in red rather than amber.
# Not a refusal -- FIX ALL never refuses, and a destination whose free space
# we cannot read gets no line at all rather than a guess.
SPACE_TIGHT_FRACTION = 0.9


def space_summary(rows: list[dict[str, Any]], local_root: str) -> tuple[str, bool]:
    """(sentence, tight) for the line above [ FIX ALL ] (UX-9, 2026-09-04).

    FIX ALL was the editor's first real decision and it stated no total at
    all: a first-day editor with a 900 GB card dump on their desktop clicked
    it and found out mid-batch, one file at a time, that the disk was full,
    with part of the batch already copied and the tree holding a mixture.
    fixer.py's "Your disk is full" was the only space handling anywhere and
    it arrives after the copy has begun.

    ("", False) when there is nothing to say -- no rows, or a destination
    that cannot be measured."""
    if not rows:
        return "", False
    total = batch_total_bytes(rows)
    free = destination_free_bytes(local_root)
    if not total:
        return "", False
    line = f"{ui_copy.count(len(rows), 'clip')}, {human_bytes(total)} in total."  # UX-10
    if not free:
        return line, False
    tight = total > free * SPACE_TIGHT_FRACTION
    line += f" This computer has {human_bytes(free)} free."
    if tight:
        # Said in the editor's terms, and it says what happens NEXT: a copy
        # into the tree is also an upload, which is the part nobody expects.
        line += (" That is not much room. Everything copied in is also uploaded "
                 "to the server.")
    return line, tight


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
        f"but it can be slow, so the bar will sit at 0% for those while they download."
    )


def call_fix_clip(
    fix_clip_fn: Callable[..., dict[str, Any]],
    args: tuple,
    on_bytes: Optional[Callable[[int, int], None]] = None,
    should_abort: Optional[Callable[[], bool]] = None,
    canonical_prefix: Optional[str] = None,
) -> dict[str, Any]:
    """Call `fix_clip_fn` with as many of the optional keyword arguments as it
    actually accepts, newest first.

    fix_clip has grown two optional callbacks (on_bytes for UX-9, should_abort
    for [ SKIP THIS FILE ]), and both the tests and any injected copier are
    full of doubles written against the older signatures. Dropping one kwarg
    at a time on TypeError keeps every existing caller working; the final
    call is made OUTSIDE the loop so a genuine TypeError from inside fix_clip
    still surfaces instead of being retried into silence."""
    base: dict[str, Any] = {"on_bytes": on_bytes}
    if should_abort is not None:
        base["should_abort"] = should_abort
    if canonical_prefix is not None:
        base["canonical_prefix"] = canonical_prefix
    # Strip the NEWEST kwarg first on TypeError, so doubles written against
    # each older signature keep working.
    attempts: list[dict[str, Any]] = [dict(base)]
    for newest in ("canonical_prefix", "should_abort"):
        if newest in base:
            base = {k: v for k, v in base.items() if k != newest}
            attempts.append(dict(base))
    for kwargs in attempts:
        try:
            return fix_clip_fn(*args, **kwargs)
        except TypeError:
            continue
    return fix_clip_fn(*args)


def perform_fix_all(
    rows: list[dict[str, Any]],
    selections: dict[str, str],
    local_root: str,
    fix_clip_fn: Callable[..., dict[str, Any]] = fixer.fix_clip,
    progress_fn: Optional[Callable[[int, int, dict[str, Any]], None]] = None,
    state_fn: Optional[Callable[[dict[str, Any]], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    control: Optional[BatchControl] = None,
    canonical_prefix: str = "",
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

    `should_stop()` is checked BETWEEN files ([ STOP AFTER THIS FILE ]): the
    file in flight is finished, then the batch ends.

    `control` (a BatchControl) adds the two MID-FILE controls,
    [ SKIP THIS FILE ] and [ CANCEL ALL ]. Mid-file abort used to be
    forbidden outright because an abandoned copy strands a multi-GB partial
    for lane C to fan out (CORE-H5); it is allowed now only because
    fixer.fix_clip deletes both artifacts of the attempt before returning
    {"ok": False, "aborted": True}. An aborted file is NOT relinked and is
    counted separately from both fixed and failed (see summarize_fix_results).

    The final state_fn publish carries the counts the summary needs --
    `fixed`, `skipped`, `failed`, `cancelled` -- ADDED alongside the existing
    keys, never in place of them (existing readers keep working).

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
    cancelled = False

    def publish(**kw: Any) -> None:
        if state_fn is None:
            return
        try:
            state_fn(kw)
        except Exception:
            log.exception("fix-all state callback failed")

    for index, row in enumerate(rows, start=1):
        if control is not None and control.cancel_all_requested():
            stopped = True
            cancelled = True
            log.info("fix all: cancelled by the user after %d/%d", len(results), total)
            break
        if should_stop is not None:
            try:
                if should_stop():
                    stopped = True
                    log.info("fix all: stopped by the user after %d/%d", len(results), total)
                    break
            except Exception:
                log.exception("fix-all should_stop callback failed")
        if control is not None:
            # Re-arm the per-file skip: a click that landed in the gap
            # between two files must not abandon a file the user never saw
            # start (see BatchControl).
            control.begin_file()

        path = row["file_path"]
        dest_rel = selections.get(path) or row["suggested_dest"]
        media_pool_items = row.get("media_pool_items")
        if media_pool_items is None:
            # back-compat with any caller still building rows the old way.
            # Through _relink_entry so a row whose walk carried no object
            # still hands the uid on (library walk, 2026-08-26).
            entry = _relink_entry(row) if "media_pool_item" in row else None
            media_pool_items = [entry] if entry is not None else []

        name = row.get("clip_name") or canon.basename(path)
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

        outcome = call_fix_clip(
            fix_clip_fn, (path, dest_rel, local_root, media_pool_items),
            on_bytes=_on_bytes,
            should_abort=control.should_abort_current if control is not None else None,
            canonical_prefix=canonical_prefix or None,
        )

        outcome = dict(outcome)
        outcome["file_path"] = path
        results.append(outcome)
        if outcome.get("ok"):
            batch_done += file_total
        # else: nothing was copied that still exists. fixer.fix_clip deletes
        # both artifacts of an aborted or failed attempt before returning, so
        # counting file_total here credited the batch with bytes that are no
        # longer on disk -- inflating the bar, the "X of Y done" text and
        # RateEstimator's speed/ETA, on exactly the runs (skips, failures)
        # where the editor is most likely to be reading them.

        if progress_fn is not None:
            try:
                progress_fn(len(results), total, outcome)
            except Exception:
                log.exception("fix-all progress callback failed")

        if outcome.get("aborted"):
            # The user abandoned this ONE copy. fix_clip has already deleted
            # the partial and relinked nothing; nothing is added to any
            # ignore list either -- skipping a copy attempt is not the same
            # as telling CCSync to stop offering the clip.
            log.info("fix all: %s skipped by the user (%s)", path, outcome.get("message"))
            if control is not None and control.cancel_all_requested():
                stopped = True
                cancelled = True
                log.info("fix all: cancelled by the user during %s (%d/%d attempted)",
                         path, len(results), total)
                break

    fixed = sum(1 for r in results if r.get("ok"))
    skipped = sum(1 for r in results if r.get("aborted"))
    publish(index=len(results), total=total, name="", file_bytes_done=0,
            file_bytes_total=0, batch_bytes_done=batch_done,
            batch_bytes_total=batch_total, stopped=stopped,
            # ADDED keys, never replacing the ones above (existing readers).
            fixed=fixed, skipped=skipped, failed=len(results) - fixed - skipped,
            cancelled=cancelled)
    return results


def perform_ignore_all(rows: list[dict[str, Any]], ignore_tracker: "fixer.IgnoreTracker",
                       how: str = "skip") -> None:
    """SKIP FOR NOW for every row. `how` is recorded in the persisted ledger
    (UX-4) so "the editor dismissed these" and "no display existed, so we
    dismissed them for him" are not the same entry."""
    for row in rows:
        ignore_tracker.ignore(row["file_path"], how=how)


def _folder_button_label(rows: list[dict[str, Any]]) -> str:
    """The third button's caption, which has to name its own scope: one
    folder or several is the difference between a safe click and a surprise."""
    count = len(folders_of(rows))
    if count > 1:
        return f"ALWAYS LEAVE THESE {count} FOLDERS ALONE ON THIS COMPUTER"
    return "ALWAYS LEAVE THIS FOLDER ALONE ON THIS COMPUTER"


def folders_of(rows: list[dict[str, Any]]) -> list[str]:
    """The distinct parent folders of `rows`, first-seen order.

    Pure and separately testable because the dialog that calls it cannot be
    driven in the suite (no real Tk, per tests/conftest.py)."""
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        folder = fixer._folder_of(str(row.get("file_path") or ""))
        if not folder:
            continue
        key = canon.norm(folder)
        if key in seen:
            continue
        seen.add(key)
        out.append(folder)
    return out


def perform_ignore_folders(rows: list[dict[str, Any]],
                           ignore_tracker: "fixer.IgnoreTracker",
                           reason: str = "") -> tuple[list[str], list[str]]:
    """"Always leave clips in this folder alone on this machine" (RES-12).

    Returns (persisted, failed). A folder that could not be written is
    reported rather than swallowed: the editor pressed a button that says
    "always", and a decision that quietly lasts until the next restart is the
    thing this finding exists to stop."""
    persisted: list[str] = []
    failed: list[str] = []
    for folder in folders_of(rows):
        try:
            ok = ignore_tracker.ignore_folder(folder, reason=reason)
        except Exception:
            log.exception("could not record the folder ignore for %s", folder)
            ok = False
        (persisted if ok else failed).append(folder)
    # Whatever happened to the file, the clips in front of the editor go away
    # now: they pressed a button whose weakest possible meaning is SKIP.
    perform_ignore_all(rows, ignore_tracker, how="folder")
    return persisted, failed


# -- RES-8 (usability sweep 2026-09-04): is a FIX ALL copy live RIGHT NOW? ---
#
# The tray's Quit tore the process down mid-write() with no question asked,
# stranding a multi-GB .ccsync-tmp that is reported an hour later and never
# deleted, and (if the kill lands between os.replace and ReplaceClip) a copy
# Resolve is not pointed at. `_popup_active_lock.locked()` is the wrong
# question for that: it is true for every dialog this process opens, including
# the sign-in box. This is the narrow one, and it is deliberately MODULE state
# rather than something hung off the dialog: the asker is the tray thread, the
# dialog belongs to another thread and its widgets may not be touched from
# here at all (CORE-H8/CORE-M3, CR-93).
_copy_state_lock = threading.Lock()
_copy_state: dict[str, Any] = {}


def copy_in_progress() -> dict[str, Any]:
    """{} when no FIX ALL copy is running, else {"index", "total", "name"}.

    Written by the ccsync-fixall worker's own lifetime (see _run_fix), so
    "empty" means the copy thread has actually finished, not that the window
    has closed. Never raises: a caller deciding whether to warn must never be
    the thing that fails."""
    with _copy_state_lock:
        return dict(_copy_state)


def _set_copy_state(info: Optional[dict[str, Any]]) -> None:
    with _copy_state_lock:
        _copy_state.clear()
        if info:
            _copy_state.update(info)


class PopupDialog:
    """tkinter Toplevel wrapper. Only imported/instantiated at call time (see
    show_popup below) so a headless environment (no display) degrades to a
    console listing instead of crashing the watcher thread — same pattern
    tray.py uses for pystray.
    """

    # Class-level defaults for the completion handoff, so a dialog built
    # without __init__ (the widget-free one the tests drive) still answers
    # "nothing pending" instead of raising out of a button callback.
    _pending_results: Optional[list[dict[str, Any]]] = None
    _finished: bool = False

    def __init__(
        self,
        rows: list[dict[str, Any]],
        local_root: str,
        ignore_tracker: "fixer.IgnoreTracker",
        on_done: Optional[Callable[[list[dict[str, Any]]], None]] = None,
        editor_name: str = "",
        canonical_prefix: str = "",
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        from . import theme

        self.rows = rows
        self.local_root = local_root
        self.ignore_tracker = ignore_tracker
        self.on_done = on_done
        self.editor_name = editor_name
        self.canonical_prefix = canonical_prefix
        self._fixing = False
        # Progress state published BY THE WORKER, read only by the Tk timer
        # tick. Tk is not thread-safe and this process has already shown Tk
        # instability under cross-thread use (CORE-H8/CORE-M3), so the worker
        # never touches a widget -- it only assigns into this dict.
        self._progress_lock = threading.Lock()
        self._progress: dict[str, Any] = {}
        self._stop_requested = False
        # SKIP THIS FILE / CANCEL ALL / STOP AFTER THIS FILE. Set on the Tk
        # thread by the buttons below, polled by the worker (and, per chunk,
        # by fixer.copy_with_progress) -- see BatchControl.
        self._control = BatchControl()
        self._rate = RateEstimator()
        self._tick_job = None
        # Rows of the run in flight, and the ones that failed (kept as ROWS,
        # not just names, so RETRY FAILED can re-run them with the same
        # destinations).
        self._batch_rows: list[dict[str, Any]] = []
        self._failed_rows: list[dict[str, Any]] = []
        # The worker's FINAL handoff, published the same way progress is (a
        # plain assignment under the lock, no Tk) and picked up by the timer
        # tick on the Tk thread. `_safe_after` is still tried first because it
        # is instant, but it must not be the only route: it is the single
        # cross-thread Tk call in this dialog, and when it fails the window is
        # left permanently unclosable -- see _fix_done/_deliver_results (MAC-11).
        self._pending_results: Optional[list[dict[str, Any]]] = None
        self._finished = False

        self.root = tk.Tk()
        try:
            self._build(tk, ttk, theme, rows, local_root)
        except Exception:
            # A partially-built root that is never destroy()ed is exactly the
            # state that makes every SUBSEQUENT tk.Tk() in this process fail
            # -- which is what strands the sign-in and update dialogs
            # (AUDIT_2 CORE-M3 -> CORE-H8). show_popup()'s except branch only
            # sees the exception; it never had a handle on the root.
            root, self.root = self.root, None
            self._drop_widgets()
            ui_dispatch.release_root(root, "the fixer popup (failed build)")
            del root
            raise

    def _build(self, tk, ttk, theme, rows, local_root) -> None:
        self.root.title(site_mod.notify_title())
        # Every other root in this process sets the app icon; the one an
        # editor sees most often -- the media-outside-tree dialog -- showed
        # the default Tk feather, which reads as "some random program is
        # asking about my media".
        theme.apply_window_icon(tk, self.root)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=theme.BG, padx=18, pady=14)
        self.root.grid_columnconfigure(0, weight=1)

        combo_style = theme.style_combobox(ttk, self.root)
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
            f"{ui_copy.count(len(rows), 'timeline clip')} live outside "  # UX-10
            f"{local_root} and will NOT sync.\n"
            "Pick a destination. FIX ALL copies them in and relinks Resolve.\n"
            "Your original file is left exactly where it is. Nothing is moved or deleted.",
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
        # RES-12 (resilience sweep 2026-08-28): the third answer. An editor
        # who keeps a personal stock-footage folder outside the tree was
        # offered the same 300 clips at every start and pressed SKIP every
        # time, which trains them to dismiss the one dialog that also catches
        # a genuinely un-synced card dump. Undone from Settings, never from
        # here -- an "always" you can set by accident and cannot see is worse
        # than the nagging.
        self._folder_btn = theme.neon_button(
            tk, btn_bar, _folder_button_label(rows), self._on_ignore_folder,
            primary=False)
        self._folder_btn.pack(side="left", padx=(0, 18))
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

        # UX-9 (2026-09-04): how much this click is about to move, and whether
        # it fits. Its own label, above the pre-flight line and below the
        # buttons, because status_label is overwritten the moment the copy
        # starts and this is the number the editor needed BEFORE the click.
        space_text, space_tight = space_summary(rows, local_root)
        self._space_label = _label(
            self.root, space_text, fg=theme.RED if space_tight else theme.MUTED,
            font=theme.mono(9), wraplength=620)
        if space_text:
            self._space_label.grid(row=r, column=0, columnspan=2, sticky="w",
                                   pady=(0, 6))
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
        bar_style = theme.style_progressbar(ttk, self.root)
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
        # Three controls, weakest to strongest. SKIP and CANCEL ALL abandon
        # the file being copied right now, which is only safe because
        # fixer.fix_clip deletes the partial before returning (CORE-H5) --
        # without that cleanup neither button may exist.
        controls_bar = tk.Frame(self._progress_frame, bg=theme.BG)
        controls_bar.grid(row=4, column=0, sticky="w", pady=(0, 6))
        self._stop_btn = theme.neon_button(
            tk, controls_bar, "STOP AFTER THIS FILE", self._on_stop_after_file,
            primary=False,
        )
        self._stop_btn.pack(side="left", padx=(0, 18))
        self._skip_btn = theme.neon_button(
            tk, controls_bar, "SKIP THIS FILE", self._on_skip_current_file, primary=False,
        )
        self._skip_btn.pack(side="left", padx=(0, 18))
        self._cancel_btn = theme.neon_button(
            tk, controls_bar, "CANCEL ALL", self._on_cancel_all, primary=True,
        )
        self._cancel_btn.pack(side="left")

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
            # master=self.root: a masterless var binds to ui_dispatch's hidden
            # root on macOS, so every combobox would read back empty and the
            # fixer would file media at the tree root (see _build_sign_in_dialog).
            var = tk.StringVar(master=self.root, value=row["suggested_dest"])
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
        """The X during a FIX ALL means CANCEL ALL -- it does NOT close the
        window.

        Clicking X is "stop this", so it now abandons the file in flight and
        the rest of the batch, with the same cleanup as the button (the
        partial is deleted by fixer.fix_clip; leaving it orphaned is CORE-H5).
        What it must never do is destroy the root: that ends mainloop(), so
        show_popup() returns and app._show_out_of_tree_popup()'s `finally`
        RELEASES _popup_active_lock -- while the daemon worker is still
        copying multi-GB files and calling ReplaceClip. A second popup, Scan
        whole project, or a consolidate could then start its own copy/relink
        pass over the same clips (AUDIT_2 CORE-M1). The window closes itself
        once the worker has actually stopped."""
        # If the worker HAS stopped and its result is still sitting unread,
        # this X is not a cancel -- there is nothing left to cancel. Finish
        # now (which may destroy the window) rather than bouncing the click
        # off a batch that ended minutes ago (MAC-11).
        self._deliver_results()
        if self._fixing:
            self._on_cancel_all()
            return
        try:
            self.root.destroy()
        except Exception:
            # _deliver_results may have destroyed it a moment ago; destroying
            # a dead window raises and there is nothing left to do about it.
            log.debug("popup: destroy on close request failed", exc_info=True)

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
        # _deliver_results' exactly-once latch is PER BATCH, not per dialog
        # (UI-1, 2026-08-11). Left set from the previous batch, both delivery
        # routes no-op on the next one: _fix_done never runs, `_fixing` stays
        # True forever, every button is disabled or ignored, the X routes back
        # into _on_cancel_all -- and app._popup_active_lock, held across
        # show_popup, is never released, so every later dialog in the session
        # dies on "Another CCSync window is already open". RETRY FAILED (and
        # FIX ALL after a stopped batch) is exactly that second batch.
        with self._progress_lock:
            self._finished = False
            self._pending_results = None
        self._control.reset()
        self._batch_rows = rows
        self._rate = RateEstimator()
        selections = {path: var.get() for path, var in self._vars}
        try:
            self._fix_btn.config(state="disabled")
            self._ignore_btn.config(state="disabled")
            # RES-2 (usability sweep 2026-09-04): the folder button was the
            # one control this bar forgot, and its handler ends in
            # root.destroy() -- which ends mainloop(), returns show_popup()
            # and releases app._popup_active_lock while the ccsync-fixall
            # daemon is still copying multi-GB files and calling ReplaceClip.
            # Exactly the second-pass-over-the-same-clips shape CORE-M1
            # closed for the X, and the destroy-under-a-live-worker shape
            # CR-93 aborts on.
            self._folder_btn.config(state="disabled")
            self._retry_btn.pack_forget()
            self._progress_frame.grid()
            for btn in (self._stop_btn, self._skip_btn, self._cancel_btn):
                btn.config(state="normal")
        except Exception:
            pass
        preflight = preflight_summary(rows)
        self.status_label.config(
            text=(f"Copying {ui_copy.count(len(rows), 'file')} in. Your originals "  # UX-10
                  f"stay exactly where they are. Nothing is moved or deleted."
                  + ("\n" + preflight if preflight else "")))

        # RES-8: registered BEFORE the thread starts and cleared in its
        # `finally`, so the window between "the editor clicked FIX ALL" and
        # "the worker is really gone" is covered at both ends.
        _set_copy_state({"index": 0, "total": len(rows), "name": ""})

        def _publish(info):
            with self._progress_lock:
                self._progress = info
            _set_copy_state({"index": int(info.get("index") or 0),
                             "total": int(info.get("total") or 0),
                             "name": str(info.get("name") or "")})

        def _worker():
            results: list[dict[str, Any]] = []
            try:
                results = perform_fix_all(
                    rows, selections, self.local_root,
                    state_fn=_publish, should_stop=lambda: self._stop_requested,
                    control=self._control,
                    canonical_prefix=self.canonical_prefix,
                )
            finally:
                # PUBLISH FIRST, marshal second. The assignment is plain
                # Python and cannot fail; root.after() is a Tk call from a
                # non-Tk thread and can. Whichever arrives first wins --
                # _deliver_results runs the finisher exactly once.
                with self._progress_lock:
                    self._pending_results = list(results)
                # RES-8: nothing is being written any more, whatever the
                # window does next. Cleared before the marshal, which is the
                # one call here that can fail.
                _set_copy_state(None)
                self._safe_after(self._deliver_results)

        threading.Thread(target=_worker, name="ccsync-fixall", daemon=True).start()
        self._schedule_tick()

    # -- progress rendering (Tk thread only) -------------------------------
    def _on_stop_after_file(self) -> None:
        """The graceful stop: the file in flight is COMPLETED, then the batch
        ends. Unchanged behaviour -- the two abandon-mid-file controls below
        are separate buttons precisely so this one stays lossless."""
        self._stop_requested = True
        self._control.request_stop_after_file()
        try:
            self._stop_btn.config(state="disabled")
            self.status_label.config(
                text="Stopping after the current file finishes. Please wait.")
        except Exception:
            pass

    def _on_skip_current_file(self) -> None:
        """Abandon the file copying right now and CARRY ON with the rest.

        Safe only because fixer.fix_clip deletes the partial copy and the
        reserved name before it returns, and relinks nothing (CORE-H5). The
        clip is not added to any ignore list: the user skipped one copy
        attempt, not the clip forever."""
        self._control.request_skip_current()
        try:
            self.status_label.config(
                text="Skipping the file being copied now. The half-copied file is "
                     "deleted and the rest of the list carries on.")
        except Exception:
            pass

    def _on_cancel_all(self) -> None:
        """Abandon the file copying right now AND the rest of the batch.

        The window stays open until the worker actually stops (see
        _on_close_request) -- files already copied in stay copied and
        relinked; nothing is moved or deleted except the half-copied file."""
        self._stop_requested = True
        self._control.request_cancel_all()
        try:
            for btn in (self._stop_btn, self._skip_btn, self._cancel_btn):
                btn.config(state="disabled")
            self.status_label.config(
                text="Cancelling. The file being copied now is abandoned and its "
                     "half-copied file deleted. Everything already copied in stays.")
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
        # The worker's completion, picked up ON THIS THREAD -- the tick is the
        # only handoff that needs no cross-thread Tk call at all (MAC-11).
        self._deliver_results()
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

    def _deliver_results(self) -> None:
        """Run the finisher once, on the Tk thread, whoever got here first.

        Reached two ways on purpose: `_safe_after` from the worker (instant),
        and the timer tick (250 ms later, same thread as everything else). The
        second exists because the first is the ONE cross-thread Tk call in this
        dialog, and its failure used to be swallowed whole -- leaving a window
        whose FIX ALL and IGNORE buttons are disabled by _run_fix, whose STOP/
        SKIP/CANCEL only set flags a finished worker will never read, and whose
        X is turned into "cancel all" by _on_close_request while `_fixing` is
        still True. Nothing on screen could close it, the work having already
        succeeded, and the log said nothing (MAC-11, hit live 2026-08-05).
        """
        with self._progress_lock:
            if self._finished or self._pending_results is None:
                return
            results, self._pending_results = self._pending_results, None
            self._finished = True
        try:
            self._fix_done(results)
        except Exception:
            # The finisher itself failed. The window must still not become a
            # dead modal: drop `_fixing` so the X works, and say so.
            log.exception("fix all: could not finish cleanly -- the window is closable")
            self._fixing = False

    def _fix_done(self, results: list[dict[str, Any]]) -> None:
        self._fixing = False
        try:
            self._progress_frame.grid_remove()
        except Exception:
            pass
        batch = self._batch_rows or self.rows
        # THREE outcomes since [ SKIP THIS FILE ]: fixed, failed, and
        # skipped-by-the-user. A skipped file is not a failure -- nothing
        # malfunctioned, the partial has already been deleted by fix_clip and
        # nothing was relinked -- so it must not be counted as one, or the
        # summary accuses CCSync of breaking what the user chose to abandon.
        aborted = [r for r in results if r.get("aborted")]
        failures = [r for r in results if not r.get("ok") and not r.get("aborted")]
        stopped_early = self._stop_requested and len(results) < len(batch)

        # Keep the actual ROWS, so RETRY FAILED can re-run exactly these with
        # the same destinations. The user could previously see only a count.
        # Skipped rows are retryable TOO: skipping a copy is not "never offer
        # this clip again" (nothing goes into the IgnoreTracker either), and
        # a file abandoned by mistake must be one click from being redone.
        by_path = {row["file_path"]: row for row in batch}
        self._failed_rows = [by_path[r["file_path"]] for r in failures + aborted
                             if r["file_path"] in by_path]
        for r in failures:
            log.warning("fix all: FAILED %s -- %s", r["file_path"], r["message"])

        if failures or aborted or stopped_early:
            try:
                self._fix_btn.config(state="normal")
                self._ignore_btn.config(state="normal")
                # RES-2: re-enabled with the other two, on the same thread
                # and in the same batch-is-over branch.
                self._folder_btn.config(state="normal")
                if self._failed_rows:
                    self._retry_btn.pack(side="left", padx=(18, 0))
            except Exception:
                pass
            head = summarize_fix_results(results, len(batch), stopped_early)
            blocks: list[str] = []
            if aborted:
                names = ", ".join(canon.basename(r["file_path"]) for r in aborted[:6])
                blocks.append(
                    f"You skipped: {names}. Nothing was copied in or relinked for "
                    f"them, and the half-copied files were deleted. "
                    f"Press RETRY FAILED to try them again.")
                leftovers = [p for r in aborted for p in (r.get("leftover_paths") or [])]
                if leftovers:
                    # The one case where a skip is NOT clean: say so, because
                    # the orphan is on the user's disk inside the sync folder
                    # (CORE-H5) and only this process ever knew about it.
                    blocks.append(
                        "⚠ CCSync could NOT delete the half-copied file(s): "
                        + "; ".join(leftovers[:6]) + ". Please delete them by hand.")
            if failures:
                # Name every failure (up to a readable cap) with its REASON,
                # not a bare "FAILED" -- the destination lives on an SMB share
                # whose metadata isn't refreshed until the handle closes, so
                # nothing outside this process can tell the user which failed.
                shown = "\n".join(f"✗ {canon.basename(r['file_path'])}: {r['message']}"
                                  for r in failures[:12])
                if len(failures) > 12:
                    # bug-hunt-2026-09-03 comp-ui-2: Open log moved into Settings on
                    # 2026-08-27; the copy must name a row the tray menu still has.
                    shown += (f"\n… and {len(failures) - 12} more "
                              f"(see {ui_copy.OPEN_LOG})")
                if any(r.get("placeholder") for r in failures):
                    shown += ("\nThese are online-only cloud files. Make them available "
                              "offline in your cloud drive, then press RETRY FAILED.")
                blocks.append(shown)
            if not failures and not aborted:
                blocks.append("Nothing was moved or deleted.")
            self.status_label.config(text="\n".join([head + ":"] + blocks))
            if failures:
                log.warning("fix all: %d/%d failed", len(failures), len(results))
            else:
                log.info("fix all: %s", head)
        else:
            self.status_label.config(text="")
            # on_done in a try: it is the app's callback (ignore-tracker
            # bookkeeping, lock release, a manifest nudge), and an exception in
            # it must not cost the user a window that can no longer be closed.
            # The destroy is what ends run_dialog()'s `tkwait window`.
            if self.on_done is not None:
                try:
                    self.on_done(results)
                except Exception:
                    log.exception("fix all: the on_done callback failed")
            self.root.destroy()

    def _safe_after(self, fn: Callable[[], None]) -> None:
        """Schedule fn on the tk thread; ignore if the window is already gone.

        Called from the worker thread, so this is a Tk call from a non-Tk
        thread: legal only while the interpreter is threaded and someone is
        pumping, and it raises "main thread is not in main loop" when it is
        not. Still best-effort -- the timer tick delivers the same result a
        quarter-second later either way -- but it is logged now, because a
        silent failure here was invisible for the whole life of the macOS
        build (MAC-11).
        """
        try:
            self.root.after(0, fn)
        except Exception:
            log.debug("could not marshal %r to the Tk thread -- the timer tick will "
                      "pick it up", getattr(fn, "__name__", fn), exc_info=True)

    def _on_ignore(self) -> None:
        # RES-2 (2026-09-04): disabling a button is a hint, not a lock -- a
        # keyboard activation, an accessibility tool or a stale click already
        # queued can still reach the handler, and every route out of this
        # dialog that ends in destroy() has to make the same check
        # _on_close_request makes.
        if self._fixing:
            return
        perform_ignore_all(self.rows, self.ignore_tracker)
        if self.on_done is not None:
            self.on_done([])
        self.root.destroy()

    def _on_ignore_folder(self) -> None:
        # RES-2 (2026-09-04): see _on_ignore. This one is the reason the guard
        # exists -- it is the route that destroyed the window mid-copy.
        if self._fixing:
            return
        persisted, failed = perform_ignore_folders(
            self.rows, self.ignore_tracker, reason="the editor chose it in the fixer")
        if failed:
            # Fail in a named direction: the clips are skipped for this
            # session either way, and the editor is told that the "always"
            # half did not stick rather than discovering it next Monday.
            log.error("could not persist the folder ignore for: %s", ", ".join(failed))
            try:
                self.status_label.config(
                    text="CCSync could not save that choice, so these clips are only "
                         f"skipped until you restart. {ui_copy.DIAGNOSTICS}"
                         "FOR YOUR ADMIN.")
            except Exception:
                log.debug("could not update the popup status line", exc_info=True)
            return
        log.info("fixer: leaving %d folder(s) alone on this machine: %s",
                 len(persisted), ", ".join(persisted))
        if self.on_done is not None:
            self.on_done([])
        self.root.destroy()

    # Every widget this dialog keeps a handle on. Cleared on the Tk thread
    # when the window closes -- see show() (CR-93).
    WIDGET_ATTRS = (
        "status_label", "_space_label", "_progress_frame", "_file_label", "_file_bar",
        "_batch_label", "_batch_bar", "_fix_btn", "_ignore_btn", "_folder_btn",
        "_retry_btn", "_stop_btn", "_skip_btn", "_cancel_btn",
    )

    def _drop_widgets(self) -> None:
        # `_vars` first and by name: a tk.StringVar holds the interpreter just
        # as firmly as a widget does, and there is one per row -- this dialog
        # opens with 40 of them on a bad day.
        self._vars = []
        for name in self.WIDGET_ATTRS:
            try:
                setattr(self, name, None)
            except Exception:
                pass

    def show(self) -> None:
        """Run the dialog, then let its interpreter die HERE.

        The teardown is not tidiness. FIX ALL runs on a daemon thread that
        holds bound methods of this dialog (`_publish`, `_fix_done`), so this
        object routinely outlives the thread that built its window -- and
        whichever thread drops it last would otherwise free the Tcl
        interpreter, which is the CR-93 abort: no traceback, no log, the
        whole tray gone. After this returns the dialog holds no Tk at all,
        so a late worker callback finds `self.root is None` and takes the
        same path it already takes for a closed window.
        """
        try:
            ui_dispatch.run_dialog(self.root)
        finally:
            root, self.root = self.root, None
            self._drop_widgets()
            if root is not None:
                ui_dispatch.release_root(root, "the fixer popup")
            del root


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

    `.control` is the same BatchControl the fixer dialog uses; a worker that
    drives a per-file copy loop (consolidate.run_consolidation) passes it
    down so [ SKIP THIS FILE ] and [ CANCEL ALL ] work mid-file here too. The
    worker signature stays `(publish, should_stop)` -- existing callers and
    their tests are untouched.
    """

    def __init__(self, title: str, subtitle: str = "") -> None:
        self.title = title
        self.subtitle = subtitle
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {}
        self._stop_requested = False
        self.control = BatchControl()
        self._rate = RateEstimator()
        self._done = threading.Event()
        self.root = None
        # Declared here so _drop_widgets has something to clear even when the
        # build never got as far as making them (CR-93).
        self._file_label = self._file_bar = None
        self._batch_label = self._batch_bar = None
        self._stop_btn = self._skip_btn = self._cancel_btn = None

    def _drop_widgets(self) -> None:
        """Forget every widget reference, ON the thread that made them.

        This object outlives its window: `run()` joins the worker with a
        TIMEOUT, and the worker holds `self.publish`/`self.should_stop`, so
        the last reference to this ProgressWindow can easily be a frame on
        the worker thread. If the widgets were still attached, the Tcl
        interpreter would be freed there -- the CR-93 abort.
        """
        for name in ("_file_label", "_file_bar", "_batch_label", "_batch_bar",
                     "_stop_btn", "_skip_btn", "_cancel_btn"):
            try:
                setattr(self, name, None)
            except Exception:
                pass

    # -- worker-facing (thread-safe, never touches Tk) ------------------
    def publish(self, info: dict[str, Any]) -> None:
        with self._lock:
            self._state = dict(info)

    def should_stop(self) -> bool:
        return self._stop_requested or self.control.should_stop()

    def cancelled(self) -> bool:
        """True when the user hit [ CANCEL ALL ] (or the X) rather than the
        graceful stop -- the caller words its summary differently."""
        return self.control.cancel_all_requested()

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

        # Root, widgets and mainloop all on ONE thread: the caller's on
        # Windows, the main thread on macOS (ui_dispatch). The worker started
        # by run() keeps publishing from its own thread either way -- it only
        # touches self._state, never a widget.
        def _build_and_show() -> None:
            root = tk.Tk()
            self.root = root
            try:
                root.title(self.title)
                theme.apply_window_icon(tk, root)
                root.attributes("-topmost", True)
                root.configure(bg=theme.BG, padx=18, pady=14)
                bar_style = theme.style_progressbar(ttk, root)

                tk.Label(root, text=f"► {self.title}", bg=theme.BG, fg=theme.RED,
                         font=theme.mono(12, bold=True), anchor="w",
                         justify="left").pack(anchor="w")
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

                # Same three controls as the fixer dialog, same order and same
                # safety rule: SKIP/CANCEL ALL abandon the file in flight, which
                # is only allowed because fixer.fix_clip deletes the partial
                # before returning (CORE-H5).
                controls_bar = tk.Frame(root, bg=theme.BG)
                controls_bar.pack(anchor="w", pady=(4, 0))
                self._stop_btn = theme.neon_button(tk, controls_bar, "STOP AFTER THIS FILE",
                                                   self._on_stop, primary=False)
                self._stop_btn.pack(side="left", padx=(0, 18))
                self._skip_btn = theme.neon_button(tk, controls_bar, "SKIP THIS FILE",
                                                   self._on_skip_current_file, primary=False)
                self._skip_btn.pack(side="left", padx=(0, 18))
                self._cancel_btn = theme.neon_button(tk, controls_bar, "CANCEL ALL",
                                                     self._on_cancel_all, primary=True)
                self._cancel_btn.pack(side="left")

                # The X means "stop this" -- it cancels the batch (with the
                # partial cleaned up) instead of silently leaving the copy
                # running behind a closed window. The window itself closes when
                # the worker has actually stopped.
                root.protocol("WM_DELETE_WINDOW", self._on_cancel_all)
                root.after(250, self._tick)
                ui_dispatch.run_dialog(root)
            finally:
                self._drop_widgets()
                self.root = None
                ui_dispatch.release_root(root, "the copy progress window")
                del root

        ui_dispatch.dispatch(_build_and_show)

    def _on_stop(self) -> None:
        """Graceful: the file in flight is finished first."""
        self._stop_requested = True
        self.control.request_stop_after_file()
        try:
            self._stop_btn.config(state="disabled")
            self._batch_label.config(text="Stopping after the current file finishes…")
        except Exception:
            pass

    def _on_skip_current_file(self) -> None:
        """Abandon the file being copied now, carry on with the rest. The
        half-copied file is deleted by fixer.fix_clip (CORE-H5)."""
        self.control.request_skip_current()
        try:
            self._batch_label.config(
                text="Skipping the file being copied now. Carrying on with the rest…")
        except Exception:
            pass

    def _on_cancel_all(self) -> None:
        """Abandon the file being copied now AND the rest of the batch."""
        self._stop_requested = True
        self.control.request_cancel_all()
        try:
            for btn in (self._stop_btn, self._skip_btn, self._cancel_btn):
                btn.config(state="disabled")
            self._batch_label.config(
                text="Cancelling. The half-copied file is deleted; everything already "
                     "copied in stays…")
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
            # DESTROY, never quit (UI-2, 2026-08-11). This window is shown
            # under ui_dispatch.run_dialog, which on darwin parks in `tkwait
            # window`; _tkinter's quit flag is process-global and
            # Tk_WaitWindow never consults it, so quit() left the finished
            # window on screen with the dispatcher's pump parked inside the
            # tkwait -- every later dialog queued forever, serve()'s mainloop
            # could not return and SIGTERM could not finish (MAC-11's shape).
            # The `finally: root.destroy()` in _show is only reached AFTER
            # run_dialog returns, so it never ran. destroy() ends both
            # tkwait (darwin) and mainloop (win32); _show's finally destroying
            # a dead root again is already guarded.
            try:
                root.destroy()
            except Exception:
                log.debug("progress window: destroy on completion failed", exc_info=True)
            return
        try:
            root.after(250, self._tick)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# the generic work window (b-roll ingest + proxy generation, 2026-08-18)
# ---------------------------------------------------------------------------
#
# ProgressWindow above OWNS its worker: it starts one, shows a window until it
# finishes, and returns. That is right for a copy an editor asked for and is
# waiting on, and wrong for everything else this companion does in the
# background -- a proxy run and a b-roll batch are hours long, started by a
# gate rather than a click, and must survive the window being closed. So this
# is the other shape: a MONITOR. It owns no work, polls a snapshot function,
# and its buttons are the same actions the tray menu offers.
#
# The owner's complaint that produced it (2026-08-18): "the lack of feedback
# is disturbing" -- the proxy generator could encode for six hours behind two
# tray lines. One window, one model, three producers (ingest, proxies, and
# music ingest when it exists), because three windows would be three sets of
# the same ETA bug.


class EmaEta:
    """Seconds per item, smoothed, and what that means for the clips left.

    An exponential moving average rather than a plain mean: a b-roll batch
    holds 4-second cutaways and 3-minute interviews, and after 40 of the
    former one of the latter must not read as "3 minutes left" for a quarter
    of an hour. Alpha 0.4 follows a change within ~4 clips.

    Answers None until `min_samples` items are done, and the window shows
    "estimating…" for exactly that long: a number derived from one clip is a
    number that will be wrong by an order of magnitude, and the first estimate
    an editor sees is the one they remember.
    """

    def __init__(self, alpha: float = 0.4, min_samples: int = 2) -> None:
        self.alpha = alpha
        self.min_samples = min_samples
        self._value: Optional[float] = None
        self._samples = 0

    def observe(self, seconds: Optional[float]) -> None:
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return
        if value <= 0:
            return
        self._samples += 1
        self._value = value if self._value is None else (
            self.alpha * value + (1.0 - self.alpha) * self._value)

    @property
    def samples(self) -> int:
        return self._samples

    def per_item_seconds(self) -> Optional[float]:
        if self._value is None or self._samples < self.min_samples:
            return None
        return self._value

    def eta_seconds(self, remaining: int) -> Optional[float]:
        per_item = self.per_item_seconds()
        if per_item is None or remaining <= 0:
            return None
        return per_item * remaining


class ProgressModel:
    """One snapshot of a background job, in the words the window draws.

    Plain attributes and no behaviour: it is built on the producer's thread
    (the tray's snapshot, the ingest tick) and read on the Tk thread, so
    anything with a lock or a live handle in it would be a deadlock waiting to
    happen. `actions` is the set of buttons that should be LIVE -- the window
    never decides that for itself, because only the producer knows whether a
    paused batch can be resumed.
    """

    ACTIONS = ("pause", "resume", "start_now", "cancel")

    def __init__(self, title: str = "", phase: str = "", headline: str = "",
                 headline_percent: Optional[int] = None, item_label: str = "",
                 item_percent: Optional[int] = None, done: int = 0, total: int = 0,
                 failed: int = 0, eta_seconds: Optional[float] = None,
                 note: str = "", actions: Any = (), finished: bool = False,
                 unit: str = "clip") -> None:
        self.title = title
        self.phase = phase
        self.headline = headline
        self.headline_percent = headline_percent
        self.item_label = item_label
        self.item_percent = item_percent
        self.done = int(done or 0)
        self.total = int(total or 0)
        self.failed = int(failed or 0)
        self.eta_seconds = eta_seconds
        self.note = note
        self.actions = tuple(actions or ())
        self.finished = bool(finished)
        # The noun the overall line counts in. "clip" by default because that
        # is what this window has always said and what the proxy generator
        # still means; music ingest passes "track" (MUSIC_INGEST_PLAN.md §2),
        # since "12 of 40 clips" over an album is the kind of wrong that makes
        # an editor doubt the rest of the window.
        self.unit = str(unit or "clip")

    def overall_line(self) -> str:
        """"12 of 40 clips · 1 failed"."""
        if not self.total:
            return "" if not self.done else f"{self.done} done"
        word = self.unit if self.total == 1 else f"{self.unit}s"
        line = f"{min(self.done, self.total)} of {self.total} {word}"
        if self.failed:
            line += f" · {self.failed} failed"
        return line

    def eta_line(self) -> str:
        """"~12 min left", or "estimating…" until the rate is worth quoting."""
        if self.finished:
            return ""
        if self.eta_seconds is None:
            return "estimating…" if self.total else ""
        return human_eta(self.eta_seconds)

    def item_line(self) -> str:
        if not self.item_label:
            return ""
        if self.item_percent is None:
            return self.item_label
        return f"{self.item_label} - {max(0, min(100, int(self.item_percent)))}%"

    def headline_line(self) -> str:
        if not self.headline:
            return ""
        if self.headline_percent is None:
            return self.headline
        # A headline that already states a percentage keeps it and only it:
        # since 2026-08-18 a model download says "Downloading X: 61% at 38 MB/s,
        # about 1 min left" in one sentence, and appending " - 61%" to that
        # reads as two different numbers about the same bar.
        if "%" in self.headline:
            return self.headline
        return f"{self.headline} - {max(0, min(100, int(self.headline_percent)))}%"


class WorkProgressWindow:
    """A window that WATCHES a background job. Never owns it, never blocks.

    `snapshot_fn()` must be cheap and lock-free (it is called on the Tk thread
    two to four times a second) and return a ProgressModel; `action_fn(name)`
    is called on a helper thread, never on the Tk thread, because "cancel"
    reaches a fleet API and a UI that froze mid-cancel would be worse than no
    button at all.

    Closing it stops nothing: the batch (or the proxy run) carries on, and the
    tray's "Show … progress…" item opens it again. That is the whole
    difference from ProgressWindow above, and it is why the X is not wired to
    a cancel here.
    """

    POLL_MS = 400

    def __init__(self, title: str, subtitle: str,
                 snapshot_fn: Callable[[], ProgressModel],
                 action_fn: Optional[Callable[[str], None]] = None) -> None:
        self.title = title
        self.subtitle = subtitle
        self._snapshot_fn = snapshot_fn
        self._action_fn = action_fn
        self.root = None
        self._open = threading.Event()
        self._closed = threading.Event()
        self._closed.set()
        self._thread: Optional[threading.Thread] = None
        self._buttons: dict[str, Any] = {}
        self._closing = False
        self._headline_label = self._headline_bar = None
        self._item_label = self._item_bar = None
        self._overall_label = self._overall_bar = self._note_label = None

    # -- lifecycle ---------------------------------------------------------
    def is_open(self) -> bool:
        return self._open.is_set()

    def open(self) -> bool:
        """Show the window. Returns at once -- the Tk loop runs on its own
        thread (via ui_dispatch, so on macOS that is the main thread's queue).

        False when there is no display, or the dispatcher has stopped, or one
        is already up: none of those is an error worth surfacing, because the
        window is decoration over work that is happening either way.
        """
        if self._open.is_set():
            return False
        self._closed.clear()
        self._closing = False
        self._open.set()
        self._thread = threading.Thread(target=self._serve, name="ccsync-work-window",
                                        daemon=True)
        self._thread.start()
        return True

    def close(self) -> None:
        """Ask the window to go away. Safe from any thread, and safe to call
        on a window that never opened."""
        root = self.root
        if root is None:
            self._open.clear()
            self._closed.set()
            return
        try:
            root.after(0, root.destroy)
        except Exception:
            log.debug("work window: could not marshal the close", exc_info=True)
            self._open.clear()

    def wait_closed(self, timeout: float = 5.0) -> bool:
        return self._closed.wait(timeout)

    def _serve(self) -> None:
        try:
            ui_dispatch.dispatch(self._build_and_show)
        except Exception as exc:  # noqa: BLE001 - no display is not an error
            log.info("work progress window unavailable (%s) -- the job carries "
                     "on without it", exc)
        finally:
            self.root = None
            self._open.clear()
            self._closed.set()

    # -- the window --------------------------------------------------------
    def _build_and_show(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        from . import theme

        root = tk.Tk()
        self.root = root
        try:
            root.title(self.title)
            theme.apply_window_icon(tk, root)
            root.configure(bg=theme.BG, padx=18, pady=14)
            bar_style = theme.style_progressbar(ttk, root)

            tk.Label(root, text=f"► {self.title}", bg=theme.BG, fg=theme.RED,
                     font=theme.mono(12, bold=True), anchor="w",
                     justify="left").pack(anchor="w")
            tk.Label(root, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w")
            if self.subtitle:
                tk.Label(root, text=self.subtitle, bg=theme.BG, fg=theme.MUTED,
                         font=theme.mono(9), anchor="w", justify="left",
                         wraplength=560).pack(anchor="w", pady=(4, 8))

            # Order matters and is the plan's: what is being FETCHED (a model,
            # a runtime) above what is being crunched, because until the
            # download finishes nothing else can start and an editor watching
            # a still per-clip bar would think it had hung.
            self._headline_label = tk.Label(root, text="", bg=theme.BG, fg=theme.TEXT,
                                            font=theme.mono(9), anchor="w",
                                            justify="left", wraplength=560)
            self._headline_label.pack(anchor="w", fill="x")
            self._headline_bar = ttk.Progressbar(root, style=bar_style,
                                                 mode="determinate", maximum=1000,
                                                 length=560)
            self._headline_bar.pack(anchor="w", fill="x", pady=(2, 8))

            self._item_label = tk.Label(root, text="", bg=theme.BG, fg=theme.TEXT,
                                        font=theme.mono(9), anchor="w",
                                        justify="left", wraplength=560)
            self._item_label.pack(anchor="w", fill="x")
            self._item_bar = ttk.Progressbar(root, style=bar_style, mode="determinate",
                                             maximum=1000, length=560)
            self._item_bar.pack(anchor="w", fill="x", pady=(2, 8))

            self._overall_label = tk.Label(root, text="", bg=theme.BG, fg=theme.MUTED,
                                           font=theme.mono(9), anchor="w",
                                           justify="left", wraplength=560)
            self._overall_label.pack(anchor="w", fill="x")
            self._overall_bar = ttk.Progressbar(root, style=bar_style,
                                                mode="determinate", maximum=1000,
                                                length=560)
            self._overall_bar.pack(anchor="w", fill="x", pady=(2, 8))

            self._note_label = tk.Label(root, text="", bg=theme.BG, fg=theme.MUTED,
                                        font=theme.mono(9), anchor="w",
                                        justify="left", wraplength=560)
            self._note_label.pack(anchor="w", fill="x", pady=(0, 6))

            bar = tk.Frame(root, bg=theme.BG)
            bar.pack(anchor="w", pady=(4, 0))
            for name, label, primary in (
                ("pause", "PAUSE", False),
                ("resume", "RESUME", False),
                ("start_now", "START NOW", False),
                ("cancel", "CANCEL", True),
            ):
                button = theme.neon_button(
                    tk, bar, label, lambda n=name: self._fire(n), primary=primary)
                button.pack(side="left", padx=(0, 18))
                self._buttons[name] = button

            # The X CLOSES THE WINDOW AND NOTHING ELSE -- see the class
            # docstring. Cancelling a two-hour batch because someone tidied
            # their desktop is not a thing this window may do.
            root.protocol("WM_DELETE_WINDOW", root.destroy)
            root.after(self.POLL_MS, self._tick)
            ui_dispatch.run_dialog(root)
        finally:
            # Every Tk object this window made dies HERE, on the thread that
            # made it. The 2026-08-18 crash: the b-roll window closed, the
            # music window opened on a fresh thread, and its build overwrote
            # self._buttons / the label attributes -- so the OLD widgets (and
            # through them the old interpreter) were finalised on the NEW
            # thread. Tcl answers that with Tcl_Panic ("Tcl_AsyncDelete: async
            # handler deleted by the wrong thread"), exception 0x80000003 in
            # tcl86t.dll, and the whole tray exits with no Python traceback.
            # Attributes first, THEN the root: release_root reads what is
            # still holding the interpreter and parks the root if anything
            # is, so a reference we could have dropped ourselves would show
            # up as a leak we cannot explain (CR-93).
            self._drop_widgets()
            self.root = None
            ui_dispatch.release_root(root, "the work progress window")
            del root

    def _drop_widgets(self) -> None:
        """Forget every widget reference so nothing Tk-owned survives the
        window thread. Runs ON that thread (see _build_and_show)."""
        self._buttons = {}
        for name in ("_headline_label", "_headline_bar", "_item_label", "_item_bar",
                     "_overall_label", "_overall_bar", "_note_label"):
            try:
                setattr(self, name, None)
            except Exception:
                pass

    def _fire(self, name: str) -> None:
        """Run one button's action OFF the Tk thread."""
        if self._action_fn is None:
            return
        threading.Thread(target=self._fire_now, args=(name,),
                         name="ccsync-work-action", daemon=True).start()

    def _fire_now(self, name: str) -> None:
        try:
            self._action_fn(name)
        except Exception:
            log.exception("work window: the %r action failed", name)

    # How long a finished job stays on screen before the window closes itself
    # (owner, 2026-08-18: "the indexing window should automatically close when
    # it is completed"). Long enough to read the final line, short enough
    # that nobody has to reach for the X.
    AUTO_CLOSE_MS = 4000

    def _tick(self) -> None:
        root = self.root
        if root is None:
            return
        try:
            model = self._snapshot_fn()
        except Exception:
            log.debug("work window: the snapshot failed", exc_info=True)
            model = None
        if model is not None:
            try:
                self._render(model)
            except Exception:
                log.exception("work window: render failed")
            if getattr(model, "finished", False) and not self._closing:
                self._closing = True
                try:
                    root.after(self.AUTO_CLOSE_MS, root.destroy)
                except Exception:
                    pass
                return
        try:
            root.after(self.POLL_MS, self._tick)
        except Exception:
            pass

    def _render(self, model: ProgressModel) -> None:
        if self._headline_label is None:
            return  # torn down (see _drop_widgets); a late tick must not touch Tk
        self._headline_label.config(text=model.headline_line())
        self._headline_bar["value"] = (
            int(10 * max(0, min(100, int(model.headline_percent))))
            if model.headline_percent is not None else 0)
        self._item_label.config(text=model.item_line())
        self._item_bar["value"] = (
            int(10 * max(0, min(100, int(model.item_percent))))
            if model.item_percent is not None else 0)
        overall = model.overall_line()
        eta = model.eta_line()
        self._overall_label.config(text=" · ".join(p for p in (overall, eta) if p))
        self._overall_bar["value"] = (
            int(1000 * min(model.done, model.total) / model.total) if model.total else 0)
        self._note_label.config(text=model.note or model.phase)
        for name, button in self._buttons.items():
            try:
                button.config(state=("normal" if name in model.actions else "disabled"))
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
        log.warning("confirm dialog unavailable (%s) -- defaulting to cancel", exc)
        return False

    result = {"ok": False}

    # The root and its mainloop go through ui_dispatch: inline on Windows
    # (same thread, same behaviour as always), on the MAIN thread on macOS,
    # where Tk-Aqua may not be touched from anywhere else.
    def _build_and_show() -> None:
        root = tk.Tk()
        root.title(title)
        theme.apply_window_icon(tk, root)
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
        # No release_root() here on purpose: every Tk object this dialog makes
        # is a LOCAL of this frame, so they all die together on this thread
        # when it returns. See ui_dispatch's CR-93 note -- the guard is for
        # windows that keep widgets in ATTRIBUTES and outlive their thread.
        ui_dispatch.run_dialog(root)

    # tk.Tk() itself can raise/wedge when other Tk roots have run on sibling
    # threads in this process (Tcl is thread-touchy) -- treat ANY dialog
    # failure like "no display": log + safe-default False, never a silent
    # dead thread (that failure mode was seen live on the update dialog,
    # 2026-07-25). A stopped dispatcher (shutdown) raises here too, and lands
    # on the same safe default.
    try:
        ui_dispatch.dispatch(_build_and_show)
    except Exception as exc:
        log.warning("confirm dialog failed (%s) -- defaulting to cancel", exc)
        return False
    return result["ok"]


def show_popup(
    out_of_tree_items: list[dict[str, Any]],
    local_root: str,
    editor_name: str,
    ignore_tracker: "fixer.IgnoreTracker",
    project_prefix: str = "",
    server_roots: Optional[dict[str, str]] = None,
    canonical_prefix: str = "",
) -> None:
    """Build and show the popup, falling back to a console listing (with the
    items auto-ignored so we don't spin forever re-popping the same clips)
    if tkinter can't create a window in this environment.
    """
    rows = build_popup_rows(out_of_tree_items, local_root, editor_name, project_prefix, server_roots)

    # Construction AND mainloop on one thread: the caller's on Windows, the
    # main one on macOS (ui_dispatch). PopupDialog.__init__ builds the root,
    # so both halves have to be inside the same dispatched call.
    def _build_and_show() -> None:
        dialog = PopupDialog(rows, local_root, ignore_tracker, editor_name=editor_name,
                             canonical_prefix=canonical_prefix)
        dialog.show()

    try:
        ui_dispatch.dispatch(_build_and_show)
    except Exception as exc:
        log.warning("popup unavailable (%s) -- falling back to console listing", exc)
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
            "%s once a display is available", len(rows), ui_copy.SCAN_WHOLE_PROJECT,
        )
        try:
            # how="headless" (UX-4, resilience sweep 2026-08-28): this batch
            # was dismissed by the ABSENCE of a display, not by anybody's
            # judgement, and the persisted ledger says which -- otherwise a
            # machine whose Tk is wedged looks exactly like an editor who
            # keeps pressing SKIP.
            perform_ignore_all(rows, ignore_tracker, how="headless")
        except Exception:
            log.exception("fallback: could not record the skipped clips")


def licence_dialog(title: str, intro: str, document: str,
                   accept_label: str = "ACCEPT") -> bool:
    """The licence agreement, scrollable, with ACCEPT / DECLINE. True only if
    the person clicked ACCEPT; close and DECLINE are both False.

    Same shape as confirm_dialog -- one Tk root through ui_dispatch, ANY
    failure defaulting to False -- but the body is a real scrolling Text
    widget rather than a Label: this is the one dialog in the companion whose
    body is a nine-thousand-character document, and a Label would render it
    as one unreadable column taller than the screen.

    THE DOCUMENT IS SHOWN, NOT SUMMARISED. An "accept" recorded against text
    the person could not read is not consent -- so the widget holds the
    verbatim assets/EULA.md this build bundles (eula.BUNDLED_TEXT), and the
    caller passes it rather than this module inventing one.

    ACCEPT is deliberately NOT the default-focused button and there is no
    Return binding: every other dialog here is a yes/no about the editor's own
    files, and this is the only one where a stray keypress would record a
    legal agreement.
    """
    try:
        import tkinter as tk

        from . import theme
    except Exception as exc:
        log.warning("licence dialog unavailable (%s) -- defaulting to decline", exc)
        return False

    result = {"ok": False}

    def _build_and_show() -> None:
        root = tk.Tk()
        root.title(title)
        theme.apply_window_icon(tk, root)
        root.attributes("-topmost", True)
        root.configure(bg=theme.BG, padx=18, pady=14)

        tk.Label(root, text=f"► {title}", bg=theme.BG, fg=theme.RED,
                 font=theme.mono(12, bold=True), justify="left", anchor="w").pack(anchor="w")
        tk.Label(root, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w")
        tk.Label(root, text=intro, bg=theme.BG, fg=theme.TEXT, font=theme.mono(10),
                 justify="left", anchor="w").pack(anchor="w", pady=(6, 10))

        body = tk.Frame(root, bg=theme.BG)
        body.pack(fill="both", expand=True)
        scroll = tk.Scrollbar(body, orient="vertical")
        scroll.pack(side="right", fill="y")
        text = tk.Text(
            body, width=84, height=24, wrap="word",
            bg=theme.PANEL, fg=theme.TEXT, font=theme.mono(9),
            insertbackground=theme.TEXT, relief="flat",
            highlightthickness=1, highlightbackground=theme.RED_DIM,
            padx=10, pady=8, yscrollcommand=scroll.set,
        )
        text.pack(side="left", fill="both", expand=True)
        scroll.config(command=text.yview)
        text.insert("1.0", document)
        # DISABLED, not readonly-by-convention: an editable licence would let
        # someone alter the text above the button that records they agreed to
        # it. Insert first -- a disabled Text refuses writes from us too.
        text.configure(state="disabled")

        btn_bar = tk.Frame(root, bg=theme.BG)
        btn_bar.pack(anchor="e", pady=(12, 0))

        def _ok():
            result["ok"] = True
            root.destroy()

        def _cancel():
            root.destroy()

        theme.neon_button(tk, btn_bar, "DECLINE", _cancel, primary=False).pack(
            side="left", padx=(0, 18))
        theme.neon_button(tk, btn_bar, accept_label, _ok, primary=True).pack(side="left")
        root.protocol("WM_DELETE_WINDOW", _cancel)
        # Frame-local widgets only, like confirm_dialog above (CR-93).
        ui_dispatch.run_dialog(root)

    try:
        ui_dispatch.dispatch(_build_and_show)
    except Exception as exc:
        log.warning("licence dialog failed (%s) -- defaulting to decline", exc)
        return False
    return result["ok"]


# ---------------------------------------------------------------------------
# the native "choose from this computer..." picker (b-roll ingest, 2026-08-18)
# ---------------------------------------------------------------------------

# The same ceiling the page and the prepare route hold: a card with 6,000
# clips on it is a batch nobody meant to start.
PICK_MAX_FILES = 2000


def _walk_folder_for_media(folder: Any, exts) -> list[dict[str, Any]]:
    """Every video under `folder`, with the sub-folder path the archive keeps.
    Sorted, so a picked card is offered in the order it was shot."""
    root = os.path.abspath(str(folder))
    top = os.path.basename(root.rstrip(os.sep)) or root
    out: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() not in exts:
                continue
            full = os.path.join(dirpath, name)
            rel_dir = os.path.relpath(dirpath, root)
            rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            out.append({"path": full, "name": name, "size": size,
                        "rel_dir": rel_dir, "top": top})
            if len(out) >= PICK_MAX_FILES:
                log.warning("ingest picker: %s holds more than %d clips -- "
                            "offering the first %d", root, PICK_MAX_FILES,
                            PICK_MAX_FILES)
                return out
    return out


def _tk_pick(kind: str) -> Any:
    """The real dialog, on the UI thread (ui_dispatch) like every other window
    in this package: a request thread that opened its own Tk root would be the
    second one in the process, which is CORE-M3's wedged interpreter."""
    import tkinter as tk
    from tkinter import filedialog

    from . import theme

    def _ask() -> Any:
        root = tk.Tk()
        try:
            root.withdraw()
            theme.apply_window_icon(tk, root)
            root.attributes("-topmost", True)
            if kind == "folder":
                return filedialog.askdirectory(
                    parent=root, title="Choose a folder of clips to index",
                    mustexist=True)
            return filedialog.askopenfilenames(
                parent=root, title="Choose clips to index")
        finally:
            ui_dispatch.release_root(root, "the ingest file picker")

    return ui_dispatch.dispatch(_ask)


def pick_media_sources(kind: str, timeout: float = 300.0,
                       dialog_fn: Optional[Callable[[str], Any]] = None,
                       exts: Optional[Any] = None) -> list[dict[str, Any]]:
    """"Choose from this computer…" -> [{path, name, size, rel_dir, top}].

    The ONE place this companion learns a local path from a person rather than
    from a server, and the reason the feature can index a 400-clip card in
    place instead of copying it into staging first (plan §1 step 1).

    Runs the dialog on a helper thread and waits `timeout` for it. An editor
    who opens the picker and wanders off must not park the request thread --
    or, on macOS, the UI dispatcher's main thread -- for the life of the
    process; after the timeout this answers "nothing was picked" and the
    dialog's eventual result is dropped. `dialog_fn` is the tests' seam.
    """
    from .broll_server import INGEST_VIDEO_EXTS

    wanted = exts if exts is not None else INGEST_VIDEO_EXTS
    ask = dialog_fn or _tk_pick
    box: dict[str, Any] = {}
    done = threading.Event()

    def _run() -> None:
        try:
            box["value"] = ask(kind)
        except Exception as exc:  # noqa: BLE001 - a picker is never fatal
            log.warning("ingest picker: the dialog failed (%s)", exc, exc_info=True)
        finally:
            done.set()

    thread = threading.Thread(target=_run, name="ccsync-ingest-picker", daemon=True)
    thread.start()
    if not done.wait(timeout):
        log.warning("ingest picker: nothing chosen within %.0fs -- treating it "
                    "as cancelled", timeout)
        return []
    chosen = box.get("value")
    if not chosen:
        return []

    if kind == "folder":
        return _walk_folder_for_media(chosen, wanted)
    out: list[dict[str, Any]] = []
    for path in list(chosen)[:PICK_MAX_FILES]:
        name = os.path.basename(str(path))
        if os.path.splitext(name)[1].lower() not in wanted:
            continue
        try:
            size = os.path.getsize(str(path))
        except OSError:
            continue
        out.append({"path": os.path.abspath(str(path)), "name": name,
                    "size": size, "rel_dir": "", "top": ""})
    return out
