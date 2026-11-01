"""Warn the editor when the open Resolve timeline uses VP9 source media (CR-380).

Why (incident 2026-10-31/11-01, FF5 submission renders). Resolve Studio 21 on
Windows refuses a full-resolution render with "Error decoding full resolution
media for <clip>.mp4 ... Please check that the file is accessible and has a
valid codec" when a timeline clip's ORIGINAL is VP9 (a YouTube download in an
MP4: VP9 + Opus). Editing looks fine, because every such folder also holds
H.264 proxies, so nobody finds out until the render. AV1 and HEVC originals
rendered fine on the same rig; only VP9 failed. The cure is converting the
original to H.264 and relinking (or remaking the proxy). Write-up:
Editing/Resolve/MontagePipeline/docs/VP9_MONTAGE_DOWNLOADS_2026-11-01.md.

Shape of the guard, and the constraints behind it:

  * The watcher hands `observe()` each successful poll's items. observe() does
    NO file I/O and no subprocess: it hashes the video clips it was given,
    and only when that signature changes (or `interval` passes) does it wake
    a worker thread of its own. The watcher thread is the one the popup
    fixer's latency depends on, and ffprobe on a network file can take
    seconds.
  * The worker stats and ffprobes each DISTINCT original path once. The codec
    is cached by (path, size, mtime), in memory and in
    ~/.ccsync/state/vp9_codec_cache.json, so a restart does not walk a
    300-clip timeline over SMB again.
  * A probe that fails, times out or names no codec is UNKNOWN: never VP9
    (no false alarm), and never remembered as "fine" -- an unknown answer
    expires after UNKNOWN_RETRY_SECONDS and is asked again. A remote rig
    whose originals are not on disk by design (proxies only) lands here for
    every clip, which is correct: the guard cannot tell, so it says nothing.
  * The popup runs on the worker thread (Tk through ui_dispatch, the same
    door every other dialog uses, CR-93), never on the watcher's.
  * "Stop warning for this timeline" is stored per project + timeline uid in
    ~/.ccsync/state/vp9_guard.json as the SET of VP9 paths the editor has
    been told about. A VP9 clip whose path is not in that set re-warns, so the
    suppression never hides a clip added later.
  * Never calls Resolve. It reads only what the watcher already walked
    (CR-68: scriptapp() has exactly one caller).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("ccsync.vp9_guard")

STATE_FILENAME = "vp9_guard.json"
CODEC_CACHE_FILENAME = "vp9_codec_cache.json"

# ffprobe's codec_name for VP9.
VP9_CODEC = "vp9"

# How often an UNCHANGED timeline is re-checked. The check is cached lookups,
# so this mostly exists to retry paths whose probe came back unknown (a drive
# that was asleep, a file still being written).
CHECK_INTERVAL_SECONDS = 120.0
# How long an unknown answer is believed before the file is asked about again.
UNKNOWN_RETRY_SECONDS = 600.0

MAX_CODEC_CACHE = 5000
MAX_SUPPRESSED_TIMELINES = 500
# Popup list caps: a project can hold hundreds of clips and the dialog has to
# fit a screen.
MAX_LISTED_FILES = 12
MAX_LISTED_POSITIONS = 4

# Results of one decision, as returned by the show function.
SUPPRESS = "suppress"
DISMISS = "dismiss"

TITLE_SUFFIX = "VP9 media in this timeline"
SUPPRESS_LABEL = "STOP WARNING FOR THIS TIMELINE"
DISMISS_LABEL = "CLOSE"


def enabled(cfg: dict[str, Any]) -> bool:
    """The `vp9_guard` config key; anything but an explicit false is ON."""
    value = cfg.get("vp9_guard", True)
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off")
    return bool(value)


def _norm(path: str) -> str:
    # Lazy: resolve_bridge is heavy and tests that stub the guard should not
    # need it. Same key the watcher uses for its warn-once sets.
    try:
        from . import resolve_bridge
        return resolve_bridge._norm_path(path)
    except Exception:
        return os.path.normcase(os.path.normpath(path))


def _timeline_key(project: str, timeline_uid: str) -> str:
    return f"{project}|{timeline_uid}"


def _video_clips(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Light copies of the VIDEO items: no media-pool objects are kept, so
    the snapshot is safe to hand to another thread."""
    out: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict) or item.get("track_type") != "video":
            continue
        path = str(item.get("file_path") or "")
        if not path:
            continue
        out.append({
            "path": path,
            "clip_name": str(item.get("clip_name") or ""),
            "track_index": item.get("track_index"),
            "item_index": item.get("item_index"),
        })
    return out


def _position(clip: dict[str, Any]) -> str:
    track = clip.get("track_index")
    index = clip.get("item_index")
    where = f"V{track}" if isinstance(track, int) else "video track"
    if isinstance(index, int):
        where += f" clip {index + 1}"
    return where


def build_message(project: str, groups: list[dict[str, Any]]) -> str:
    """The popup body. `groups` is one dict per VP9 file: {path, clip_name,
    positions}. No em dashes: this is user-visible text (owner's rule,
    2026-08-18)."""
    count = len(groups)
    noun = "file is" if count == 1 else "files are"
    lines = [
        f"{count} source media {noun} VP9"
        + (f" in project “{project}”" if project else "")
        + ", and DaVinci Resolve cannot render VP9 originals at full "
        "resolution. This timeline WILL FAIL to render with “Error "
        "decoding full resolution media”.",
        "",
        "It plays fine now only because Resolve is using the H.264 proxies.",
        "",
        "Affected clips:",
    ]
    for group in groups[:MAX_LISTED_FILES]:
        name = group.get("clip_name") or os.path.basename(group["path"])
        file_name = os.path.basename(group["path"])
        positions = group.get("positions") or []
        shown = ", ".join(positions[:MAX_LISTED_POSITIONS])
        if len(positions) > MAX_LISTED_POSITIONS:
            shown += f" and {len(positions) - MAX_LISTED_POSITIONS} more"
        label = f"{name} ({file_name})" if name != file_name else file_name
        lines.append(f"  - {label}" + (f": {shown}" if shown else ""))
    if count > MAX_LISTED_FILES:
        lines.append(f"  ... and {count - MAX_LISTED_FILES} more files")
    lines += [
        "",
        "How to fix it: convert each original to H.264, then relink the clip "
        "to the converted file or remake its proxy. For a folder of "
        "downloads, MontagePipeline's montage_editready.py does the "
        "conversion.",
        "",
        f"{SUPPRESS_LABEL} keeps this quiet until a new VP9 clip is added to "
        "this timeline.",
    ]
    return "\n".join(lines)


class VP9Guard:
    """See the module docstring. Every public method is safe to call from the
    watcher thread and never raises."""

    def __init__(
        self,
        enabled_fn: Callable[[], bool],
        ffmpeg_path_fn: Callable[[], str],
        state_dir: Path,
        show_fn: Callable[[str, str], Optional[str]],
        probe_fn: Optional[Callable[[str, str], dict]] = None,
        stat_fn: Optional[Callable[[str], os.stat_result]] = None,
        clock: Callable[[], float] = time.monotonic,
        interval: float = CHECK_INTERVAL_SECONDS,
        start_thread: bool = True,
    ) -> None:
        self._enabled_fn = enabled_fn
        self._ffmpeg_path_fn = ffmpeg_path_fn
        self._state_path = Path(state_dir) / STATE_FILENAME
        self._cache_path = Path(state_dir) / CODEC_CACHE_FILENAME
        # show_fn(title, body) -> SUPPRESS | DISMISS | None. None = the
        # dialog could not be shown (another window open, no display): the
        # warning stays owed and is retried on the next check.
        self._show_fn = show_fn
        self._probe_fn = probe_fn
        self._stat_fn = stat_fn or os.stat
        self._clock = clock
        self._interval = float(interval)
        self._start_thread = start_thread

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._pending: Optional[dict[str, Any]] = None
        self._last_signature: Optional[tuple] = None
        self._last_check = 0.0
        # codec cache: "path|size|mtime_ns" -> codec name (str). Only
        # KNOWN answers live here and on disk.
        self._codecs: dict[str, str] = self._load_codec_cache()
        self._codecs_dirty = False
        # key -> monotonic time before which an unknown answer is believed.
        self._unknown_until: dict[str, float] = {}
        # timeline key -> VP9 path keys already shown this session.
        self._warned: dict[str, set[str]] = {}
        self.probe_count = 0

    # -- watcher side -------------------------------------------------------
    def observe(self, result: dict[str, Any]) -> None:
        """Called by the watcher after every successful poll."""
        try:
            if not self._enabled_fn():
                return
            clips = _video_clips(result.get("items") or [])
            if not clips:
                return
            project = str(result.get("project_name") or "")
            uid = str(result.get("timeline_uid") or "")
            signature = (project, uid, hash(tuple(
                (c["path"], c["track_index"], c["item_index"]) for c in clips)))
            now = self._clock()
            with self._lock:
                if (signature == self._last_signature
                        and now - self._last_check < self._interval):
                    return
                self._last_signature = signature
                self._last_check = now
                self._pending = {"project": project, "timeline_uid": uid,
                                 "clips": clips}
            self._wake.set()
            self._ensure_thread()
        except Exception:
            log.exception("vp9 guard: observe failed")

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # -- worker side --------------------------------------------------------
    def _ensure_thread(self) -> None:
        if not self._start_thread:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._loop, name="ccsync-vp9-guard", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._stop.is_set():
                return
            self.run_pending()

    def run_pending(self) -> None:
        """Evaluate the newest queued snapshot, if any. The worker's body;
        tests call it directly."""
        with self._lock:
            snapshot, self._pending = self._pending, None
        if snapshot is None:
            return
        try:
            self._evaluate(snapshot)
        except Exception:
            log.exception("vp9 guard: check failed")

    def _evaluate(self, snapshot: dict[str, Any]) -> None:
        if not self._enabled_fn():
            return
        project = snapshot["project"]
        uid = snapshot["timeline_uid"]
        key = _timeline_key(project, uid)

        by_path: dict[str, dict[str, Any]] = {}
        for clip in snapshot["clips"]:
            group = by_path.setdefault(clip["path"], {
                "path": clip["path"], "clip_name": clip["clip_name"],
                "positions": []})
            group["positions"].append(_position(clip))

        vp9: dict[str, dict[str, Any]] = {}
        known_other: set[str] = set()
        for path, group in by_path.items():
            if self._stop.is_set() or not self._enabled_fn():
                return
            codec = self._codec_for(path)
            if codec is None:
                continue
            if codec == VP9_CODEC:
                vp9[_norm(path)] = group
            else:
                known_other.add(_norm(path))
        self._save_codec_cache()

        state = self._load_state()
        record = state["timelines"].get(key) or {}
        acked = set(record.get("paths") or [])
        # A file converted in place is no longer VP9: forget the
        # acknowledgement so a later VP9 file at the same path warns again.
        stale = acked & known_other
        if stale:
            acked -= stale
            self._store_ack(state, key, project, uid, acked)

        current = set(vp9)
        previous = self._warned.get(key, set())
        owed = (current - acked) - previous
        if not owed:
            self._warned[key] = current
            return

        groups = [vp9[k] for k in sorted(vp9)]
        body = build_message(project, groups)
        title = _title()
        log.warning("vp9 guard: %d VP9 source file(s) in project %r timeline %r",
                    len(groups), project, uid)
        try:
            answer = self._show_fn(title, body)
        except Exception:
            log.exception("vp9 guard: could not show the warning")
            answer = None
        if answer is None:
            # Still owed. Make the next poll's signature check pass so the
            # warning is retried within the interval.
            with self._lock:
                self._last_signature = None
            return
        self._warned[key] = current
        if answer == SUPPRESS:
            self._store_ack(state, key, project, uid, acked | current)

    def _codec_for(self, path: str) -> Optional[str]:
        """The video codec of `path`, or None for "cannot tell"."""
        now = self._clock()
        try:
            st = self._stat_fn(path)
            cache_key = f"{path}|{st.st_size}|{getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9))}"
        except OSError:
            # Not on this computer (a proxy-only rig) or the drive is out.
            # A stat is cheap, so it is simply asked again next check.
            return None
        known = self._codecs.get(cache_key)
        if known:
            return known
        if self._unknown_until.get(cache_key, 0.0) > now:
            return None
        codec = self._probe(path)
        if codec is None:
            self._unknown_until[cache_key] = now + UNKNOWN_RETRY_SECONDS
            return None
        self._unknown_until.pop(cache_key, None)
        self._codecs[cache_key] = codec
        self._codecs_dirty = True
        return codec

    def _probe(self, path: str) -> Optional[str]:
        self.probe_count += 1
        try:
            probe = self._probe_fn
            if probe is None:
                from . import ffmpeg_tools
                probe = ffmpeg_tools.probe_video
            info = probe(str(self._ffmpeg_path_fn() or "ffmpeg"), path)
        except Exception as exc:
            log.debug("vp9 guard: could not probe %s: %s", path, exc)
            return None
        codec = info.get("codec") if isinstance(info, dict) else None
        if not isinstance(codec, str) or not codec.strip():
            return None
        return codec.strip().lower()

    # -- persistence --------------------------------------------------------
    def _load_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("timelines"), dict):
                return data
        except (OSError, ValueError):
            pass
        return {"version": 1, "timelines": {}}

    def _store_ack(self, state: dict[str, Any], key: str, project: str,
                   uid: str, paths: set[str]) -> None:
        timelines = state["timelines"]
        timelines[key] = {
            "project": project, "timeline_uid": uid, "paths": sorted(paths),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if len(timelines) > MAX_SUPPRESSED_TIMELINES:
            oldest = sorted(timelines, key=lambda k: timelines[k].get("at", ""))
            for stale in oldest[:len(timelines) - MAX_SUPPRESSED_TIMELINES]:
                timelines.pop(stale, None)
        self._write_json(self._state_path, state)

    def _load_codec_cache(self) -> dict[str, str]:
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items() if v}
        except (OSError, ValueError):
            pass
        return {}

    def _save_codec_cache(self) -> None:
        if not self._codecs_dirty:
            return
        if len(self._codecs) > MAX_CODEC_CACHE:
            for stale in list(self._codecs)[:len(self._codecs) - MAX_CODEC_CACHE]:
                self._codecs.pop(stale, None)
        self._codecs_dirty = False
        self._write_json(self._cache_path, self._codecs)

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        # Best-effort: losing either file costs one repeat warning or one
        # re-probe, never data.
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            log.debug("vp9 guard: could not write %s: %s", path, exc)


def _title() -> str:
    try:
        from . import site as site_mod
        return site_mod.notify_title(TITLE_SUFFIX)
    except Exception:
        return "CC Sync: " + TITLE_SUFFIX
