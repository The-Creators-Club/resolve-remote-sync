"""The Resolve door for originals on request: the request-file inbox.

docs/SELECTIVE_ORIGINALS.md section 12.2 (2026-10-31). The Lua menu scripts
(resolve_menu/, installed by resolve_menu_install.py) cannot make an HTTP call
and must not be handed the loopback token, so they write a request file into
`~/.ccsync/requests/originals/` and this module does the rest: validate it,
turn each clip's `File Path` into (project slug, rel inside the project), ask
the dashboard to record the pick (`PUT /api/v1/selection/{editor}/{slug}/
originals`, 12.3), say what happened in ONE balloon, and delete the file.

CR-68: nothing here calls Resolve. A multicam or compound clip has no File
Path of its own, and the script never descends into it; its angles come from
the timeline walk the watcher ALREADY does every poll (ClipPathMemory, fed by
a wrapper around the watcher's own getter). A clip that walk has not seen
cannot be resolved, and the balloon says so rather than guessing.

D9 (owner, 2026-10-31): a pick on an upload-only tick is refused by the
dashboard with a sentence saying how to fix it, and that sentence reaches the
editor VERBATIM. No em dashes in any copy here (owner's rule, 2026-08-18).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import canon
from . import ui_copy
from .sync import originals_lane

log = logging.getLogger("ccsync.originals")

SCHEMA_VERSION = 1
ACTIONS = ("add", "remove")
SOURCES = ("media_pool", "timeline_range", "timeline_playhead", "timeline_all")

# Bounds. A whole-timeline request on a long multicam edit is the largest
# honest one: a few thousand distinct pool clips at most.
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_CLIPS = 10000
MAX_PATH_CHARS = 4096
MAX_TEXT_CHARS = 1024
# 12.2: a request older than this is logged and deleted, never acted on. A
# pick an editor made an hour ago and has heard nothing about is one they
# have stopped expecting, and acting on it now would surprise them.
MAX_AGE_SECONDS = 3600.0
POLL_SECONDS = 2.0
# How many clip uids ClipPathMemory keeps. A big library project is ~4,000
# pool clips; the bound only stops a session of many projects growing it.
MAX_REMEMBERED = 50000

# Transient answers keep the file for the next poll (until MAX_AGE_SECONDS).
_TRANSIENT = 0


def request_dir() -> Path:
    """Read at call time, so a test's HOME redirection is honoured."""
    return Path.home() / ".ccsync" / "requests" / "originals"


class RequestError(ValueError):
    """The request file is malformed; the message is for the log."""


def _text(value: Any, field: str, limit: int, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise RequestError(f"{field} is not a string")
    if len(value) > limit:
        raise RequestError(f"{field} is longer than {limit} characters")
    if "\x00" in value:
        raise RequestError(f"{field} holds a NUL")
    return value


def parse_request(raw: bytes) -> dict:
    """Validate one request file's bytes STRICTLY (12.2). Raises RequestError.

    Returns {"action", "source", "project", "timeline", "created_at",
    "clips": [{"file_path", "unique_id", "name", "type"}]}."""
    if len(raw) > MAX_REQUEST_BYTES:
        raise RequestError(f"larger than {MAX_REQUEST_BYTES} bytes")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RequestError(f"not UTF-8 JSON ({exc})") from None
    if not isinstance(data, dict):
        raise RequestError("not a JSON object")
    version = data.get("v")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise RequestError(f"v is {version!r}, this build reads v {SCHEMA_VERSION}")
    action = data.get("action")
    if action not in ACTIONS:
        raise RequestError(f"action {action!r} is not one of {ACTIONS}")
    source = data.get("source")
    if source not in SOURCES:
        raise RequestError(f"source {source!r} is not one of {SOURCES}")
    clips = data.get("clips")
    if not isinstance(clips, list) or not clips:
        raise RequestError("clips is not a non-empty list")
    if len(clips) > MAX_CLIPS:
        raise RequestError(f"more than {MAX_CLIPS} clips")
    out_clips = []
    for index, clip in enumerate(clips):
        if not isinstance(clip, dict):
            raise RequestError(f"clips[{index}] is not an object")
        out_clips.append({
            "file_path": _text(clip.get("file_path"), f"clips[{index}].file_path",
                               MAX_PATH_CHARS),
            "unique_id": _text(clip.get("unique_id"), f"clips[{index}].unique_id",
                               MAX_TEXT_CHARS),
            "name": _text(clip.get("name"), f"clips[{index}].name", MAX_TEXT_CHARS,
                          required=False),
            "type": _text(clip.get("type"), f"clips[{index}].type", MAX_TEXT_CHARS,
                          required=False),
        })
    return {
        "action": action,
        "source": source,
        "project": _text(data.get("project"), "project", MAX_TEXT_CHARS, required=False),
        "timeline": _text(data.get("timeline"), "timeline", MAX_TEXT_CHARS, required=False),
        "created_at": _text(data.get("created_at"), "created_at", 64),
        "clips": out_clips,
    }


def _created_epoch(stamp: str) -> Optional[float]:
    text = str(stamp or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


class ClipPathMemory:
    """uid -> file paths, remembered from the timeline walks the watcher does.

    The library walk expands a multicam or compound to its ANGLES and tags
    each with `via_multicam`, the container's pool uid (resolve_bridge.
    get_timeline_items); a plain item carries its own `media_pool_uid`. Kept
    across polls and timelines, bounded, so a multicam seen on any timeline
    this session can be answered. Fed by app.py's wrapper around the
    watcher's getter: no Resolve call of its own (CR-68)."""

    def __init__(self, limit: int = MAX_REMEMBERED) -> None:
        self._limit = int(limit)
        self._lock = threading.Lock()
        self._containers: dict[str, list[str]] = {}
        self._plain: dict[str, str] = {}

    def remember(self, result: Any) -> Any:
        """Fold one walk result in; hands `result` back untouched. Never raises."""
        try:
            items = result.get("items") if isinstance(result, dict) else None
            if not isinstance(items, list):
                return result
            fresh: dict[str, list[str]] = {}
            plain: dict[str, str] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("file_path") or "")
                if not path:
                    continue
                via = item.get("via_multicam")
                if via:
                    paths = fresh.setdefault(str(via), [])
                    if path not in paths:
                        paths.append(path)
                uid = str(item.get("media_pool_uid") or "")
                if uid:
                    plain[uid] = path
            if not fresh and not plain:
                return result
            with self._lock:
                for uid, paths in fresh.items():
                    self._containers.pop(uid, None)
                    self._containers[uid] = paths
                for uid, path in plain.items():
                    self._plain.pop(uid, None)
                    self._plain[uid] = path
                for table in (self._containers, self._plain):
                    while len(table) > self._limit:
                        table.pop(next(iter(table)))
        except Exception:
            log.debug("originals: could not remember the timeline walk", exc_info=True)
        return result

    def paths_for(self, uid: str) -> list[str]:
        if not uid:
            return []
        with self._lock:
            if uid in self._containers:
                return list(self._containers[uid])
            path = self._plain.get(uid)
        return [path] if path else []


def tree_rel_for(file_path: str, local_root: str, canonical_prefix: str) -> Optional[str]:
    """`P:\\Projects\\2026\\X\\a.braw` (or the same file by its physical path,
    a Mac's `/Volumes/T7/Creators_Club/Projects/...`) -> `Projects/2026/X/a.braw`.

    canon.py's rules: the canonical spelling is judged in the prefix's own
    spelling whatever the host is, and anything not under the prefix or the
    local root maps to nothing."""
    path = str(file_path or "").strip()
    if not path:
        return None
    parts: Optional[list[str]] = None
    if canonical_prefix and canon.is_canonical(path, canonical_prefix):
        plat = canon.plat_for(canonical_prefix)
        rest = plat.normpath(path)[len(plat.normpath(str(canonical_prefix))):]
        parts = [p for p in rest.replace("\\", "/").split("/") if p]
    elif local_root:
        plat = canon.plat_for(path)
        root = str(local_root)
        try:
            norm_path = plat.normcase(plat.normpath(path))
            norm_root = plat.normcase(plat.normpath(root))
        except Exception:
            return None
        if norm_path.startswith(norm_root.rstrip("\\/") + plat.sep):
            rest = plat.normpath(path)[len(plat.normpath(root).rstrip("\\/")):]
            parts = [p for p in rest.replace("\\", "/").split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        return None
    return "/".join(parts)


def _project_map(selection: Optional[Iterable[Any]]) -> list[tuple[list[str], str, bool]]:
    """[(folded components of `Projects/<rel>`, slug, upload_only)], longest first.

    Upload-only ticks are KEPT: a pick on one goes to the dashboard, whose 409
    sentence is what tells the editor how to fix it (D9). A silent drop here
    would leave them wondering why nothing came."""
    from .sync.sequencer import _item_is_valid, _item_rel, _item_upload_only

    out = []
    for item in selection or []:
        try:
            if not isinstance(item, dict) or not _item_is_valid(item):
                continue
            rel = _item_rel(item)
        except Exception:
            continue
        if not rel:
            continue
        comps = [originals_lane.nfc(p) for p in f"Projects/{rel}".replace("\\", "/").split("/") if p]
        out.append((comps, str(item.get("slug")), bool(_item_upload_only(item))))
    out.sort(key=lambda row: len(row[0]), reverse=True)
    return out


def map_to_projects(tree_rels: Iterable[str], selection: Optional[Iterable[Any]]):
    """Group tree rels by project: ({slug: [rel inside project]}, outside, skipped).

    `outside` counts paths in no project ticked for this computer (the inbox
    refuses those: a pick is about a tick). `skipped` counts files inside one
    that are not camera originals lane B leaves behind (a proxy, an audio
    file, a partial), which nothing would ever download. The rel is NFC: it
    is only ever a pick KEY on the dashboard, which compares in NFC anyway
    (CR-90); the download re-lists the NAS for the real spelling."""
    projects = _project_map(selection)
    grouped: dict[str, list[str]] = {}
    outside = skipped = 0
    for tree_rel in tree_rels:
        parts = [p for p in str(tree_rel).split("/") if p]
        folded = [originals_lane.nfc(p) for p in parts]
        match = None
        for comps, slug, _upload_only in projects:
            if len(folded) > len(comps) and folded[:len(comps)] == comps:
                match = (len(comps), slug)
                break
        if match is None:
            outside += 1
            continue
        inner = unicodedata.normalize("NFC", "/".join(parts[match[0]:]))
        if originals_lane.list_rule_reason(inner) is not None:
            skipped += 1
            continue
        bucket = grouped.setdefault(match[1], [])
        if inner not in bucket:
            bucket.append(inner)
    return grouped, outside, skipped


def _human_bytes(n: Any) -> str:
    return originals_lane._human_bytes(n)


# put_fn(slug, add, remove) -> (http status, parsed body or None, error text).
# Status 0 means the dashboard could not be reached.
PutFn = Callable[[str, list, list], tuple]


class OriginalsInbox:
    """Polls the request folder; one balloon per request answered."""

    def __init__(
        self,
        cfg: dict[str, Any],
        selection_fn: Callable[[], Optional[list]],
        put_fn: PutFn,
        notify_fn: Callable[[str], None],
        memory: Optional[ClipPathMemory] = None,
        on_queued: Optional[Callable[[], None]] = None,
        inbox: Optional[Path] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.cfg = cfg
        self._selection_fn = selection_fn
        self._put = put_fn
        self._notify = notify_fn
        self.memory = memory or ClipPathMemory()
        self._on_queued = on_queued
        self._inbox = inbox
        self._clock = clock
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # request name -> {slug: answer}, so a request kept for a transient
        # failure does not re-send the projects that were already answered.
        self._answered: dict[str, dict[str, tuple]] = {}

    @property
    def inbox(self) -> Path:
        return self._inbox or request_dir()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ccsync-originals-inbox",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                log.exception("originals: inbox poll failed")
            self._stop.wait(POLL_SECONDS)

    def poll_once(self) -> int:
        """Answer every request waiting. Returns how many were finished."""
        try:
            names = sorted(p for p in self.inbox.iterdir() if p.is_file())
        except FileNotFoundError:
            return 0
        except OSError:
            log.debug("originals: cannot read %s", self.inbox, exc_info=True)
            return 0
        finished = 0
        for path in names:
            if path.suffix.lower() == ".json":
                if self._handle(path):
                    finished += 1
            elif path.name.endswith(".tmp") and self._age(path) > MAX_AGE_SECONDS:
                # A script that died between write and rename.
                self._delete(path, "a half-written request older than an hour")
        return finished

    def _age(self, path: Path) -> float:
        try:
            return self._clock() - path.stat().st_mtime
        except OSError:
            return 0.0

    def _delete(self, path: Path, why: str) -> None:
        self._answered.pop(path.name, None)
        try:
            path.unlink()
            log.info("originals: removed request %s (%s)", path.name, why)
        except FileNotFoundError:
            pass
        except OSError:
            log.warning("originals: could not remove request %s", path, exc_info=True)

    def _handle(self, path: Path) -> bool:
        try:
            raw = path.read_bytes()
        except OSError:
            log.debug("originals: cannot read %s yet", path, exc_info=True)
            return False
        try:
            request = parse_request(raw)
        except RequestError as exc:
            log.warning("originals: request %s is malformed (%s) -- deleting it",
                        path.name, exc)
            self._delete(path, "malformed")
            return True
        created = _created_epoch(request["created_at"])
        age = max(self._age(path),
                  (self._clock() - created) if created is not None else 0.0)
        if age > MAX_AGE_SECONDS:
            log.warning("originals: request %s is %.0f minutes old -- deleting it "
                        "unanswered", path.name, age / 60.0)
            self._delete(path, "older than an hour")
            return True
        done, message = self.answer(path.name, request)
        if not done:
            return False
        if message:
            try:
                self._notify(message)
            except Exception:
                log.debug("originals: balloon failed", exc_info=True)
        self._delete(path, "answered")
        return True

    def _clip_paths(self, clip: dict) -> list[str]:
        path = clip["file_path"]
        if path:
            return [path]
        return self.memory.paths_for(clip["unique_id"])

    def answer(self, name: str, request: dict) -> tuple[bool, str]:
        """(finished, balloon text). Not finished = keep the file, ask again."""
        local_root = str(self.cfg.get("local_root") or "")
        prefix = str(self.cfg.get("canonical_prefix") or "")
        unresolved = 0
        tree_rels: list[str] = []
        for clip in request["clips"]:
            paths = self._clip_paths(clip)
            if not paths:
                unresolved += 1
                continue
            mapped = [rel for rel in (tree_rel_for(p, local_root, prefix) for p in paths) if rel]
            if not mapped:
                tree_rels.append("")  # counted as outside below
                continue
            tree_rels.extend(mapped)
        try:
            selection = self._selection_fn()
        except Exception:
            log.debug("originals: selection read failed", exc_info=True)
            selection = None
        grouped, outside, skipped = map_to_projects([r for r in tree_rels if r], selection)
        outside += sum(1 for r in tree_rels if not r)

        adding = request["action"] == "add"
        answered = self._answered.setdefault(name, {})
        transient = False
        for slug, rels in grouped.items():
            if slug in answered:
                continue
            add = [{"rel": rel, "is_dir": False} for rel in rels] if adding else []
            remove = [] if adding else list(rels)
            try:
                status, body, error = self._put(slug, add, remove)
            except Exception as exc:
                status, body, error = _TRANSIENT, None, str(exc)
            if status == _TRANSIENT or status >= 500:
                log.warning("originals: the dashboard did not answer for %s (%s) -- "
                            "keeping request %s", slug, error or status, name)
                transient = True
                continue
            answered[slug] = (status, body, error, len(rels))
        if transient:
            return False, ""
        self._answered.pop(name, None)
        if any(a[0] == 200 for a in answered.values()) and self._on_queued is not None:
            try:
                self._on_queued()
            except Exception:
                log.debug("originals: wake failed", exc_info=True)
        return True, self.balloon(adding, answered, unresolved, outside, skipped)

    @staticmethod
    def balloon(adding: bool, answered: dict, unresolved: int, outside: int,
                skipped: int) -> str:
        """One sentence set per request. A dashboard refusal comes FIRST and
        VERBATIM (D9): it is the one part that tells the editor what to do,
        and a balloon is cut at 250 characters."""
        refusals: list[str] = []
        ok_files = 0
        total_bytes = 0
        for status, body, error, count in answered.values():
            detail = body.get("detail") if isinstance(body, dict) else None
            if status == 200:
                ok_files += count
                try:
                    total_bytes += int((body or {}).get("total_bytes") or 0)
                except (TypeError, ValueError, AttributeError):
                    pass
            elif status == 409 and isinstance(detail, str) and detail.strip():
                if detail.strip() not in refusals:
                    refusals.append(detail.strip())
            else:
                text = (f"The server refused part of this request (HTTP {status})"
                        + (f": {detail.strip()}" if isinstance(detail, str) and detail.strip()
                           else "."))
                if text not in refusals:
                    refusals.append(text)
        parts: list[str] = list(refusals)
        if ok_files:
            noun = ui_copy.count(ok_files, "original")
            if adding:
                size = f" ({_human_bytes(total_bytes)})" if total_bytes else ""
                parts.append(f"Bringing {noun} to this computer{size}. "
                             "The tray shows progress.")
            else:
                parts.append(f"Stopped bringing {noun}. Files already on this computer stay.")
        if unresolved:
            parts.append(f"{ui_copy.count(unresolved, 'clip')} could not be matched to a "
                         "file (a multicam or compound clip this computer has not seen on "
                         "a timeline yet).")
        if outside:
            parts.append(f"{ui_copy.count(outside, 'clip')} {_is_are(outside)} not in a "
                         "project this computer syncs.")
        if skipped:
            parts.append(f"{ui_copy.count(skipped, 'clip')} {_is_are(skipped)} not camera "
                         "originals.")
        if not refusals and not ok_files:
            parts.insert(0, "Nothing was queued:" if parts else "Nothing was queued.")
        return " ".join(parts)


def _is_are(n: int) -> str:
    return "is" if n == 1 else "are"
