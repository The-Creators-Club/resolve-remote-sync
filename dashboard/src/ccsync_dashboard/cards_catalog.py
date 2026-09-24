"""What the `/cards` picker knows about an episode beyond its folder name.

2026-09-24 (Alex: "ordered by most recently opened instead of date, and
filterable by year, by last opened, by largest, by date, alphabetically, and
also searchable"). Three facts the vault scan in `cards_pool.episodes` does
not carry, each with its own cost, and none of them allowed to slow the page:

  * **LAST OPENED** - who entered which episode and when, per person. The
    pool's `Entry.seen` is in memory and dies with the engine (and with every
    container restart), so it cannot be the key for "most recently opened":
    an episode closed yesterday would sort as never opened today. This is a
    small JSON file beside the per-episode data dirs, written only when a
    person ENTERS an episode page (a navigation, never a media range request,
    which arrive several a second) or presses [ OPEN ], and throttled per
    (person, episode) so a reload loop cannot turn into a write loop.
  * **SIZE** - bytes on disk under the episode root. That is a walk of every
    file in a folder on a network share, so it is NEVER done in a request: one
    background thread sizes episodes one at a time, oldest answer first, and
    the page shows "sizing" until it has a number. A walk that fails keeps the
    last good number rather than dropping to zero, because "0 B" sorts a
    300 GB episode to the bottom of LARGEST for no reason anybody can see.
  * **MODIFIED** - the newest mtime anywhere under the episode, found by the
    same walk (the root folder's own mtime, which the vault scan reads for
    free, stands in until then: a folder's mtime only moves when an entry
    directly in it is added or removed, so on its own it is a weak "date").

Every read and write is best effort. The picker is the page that must draw
when everything else is broken (cards_landing's docstring), so a missing,
corrupt or unwritable file here is an empty answer, never a 500.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("ccsync.dashboard.cards")

OPENED_FILE = "landing_opened.json"
SIZES_FILE = "landing_sizes.json"

# One write per (person, episode) per this long. Entering the page is a
# navigation, but a phone that reloads on every wake would otherwise write
# the file on every wake.
OPENED_THROTTLE_SECONDS = 60.0

# How stale a size may get before the walker takes it again. Episodes grow by
# whole interviews, not by the minute; a day-old size is a fine sort key.
SIZE_MAX_AGE_SECONDS = 12 * 3600

# A walk that has counted this many entries stops and records what it has,
# flagged partial. A runaway tree (a render cache someone parked inside an
# episode) must not keep the only walker busy for an hour.
SIZE_MAX_ENTRIES = 400_000

# The per-person map is trimmed to this many episodes each, newest kept.
OPENED_PER_PERSON = 200

_YEAR = re.compile(r"^(19|20)\d\d$")


def _catalog_dir(settings: Any) -> Path | None:
    try:
        path = Path(settings.db_path).parent / "cards"
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:  # noqa: BLE001 - no data dir means no catalogue
        return None


def _read_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    """Atomic, and with a tmp name of its own: two threads never share one."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError as e:
        log.warning("Timeline Cards picker: could not write %s (%s)", path, e)
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ------------------------------------------------------------- last opened

_lock = threading.Lock()
_last_write: dict[tuple[str, str], float] = {}


def note_opened(settings: Any, slug: str, user: str) -> None:
    """`user` entered (or opened) episode `slug` just now. Never raises."""
    user = str(user or "").strip().lower()
    slug = str(slug or "").strip()
    if not user or not slug:
        return
    now = time.time()
    with _lock:
        if now - _last_write.get((user, slug), 0.0) < OPENED_THROTTLE_SECONDS:
            return
        _last_write[(user, slug)] = now
        folder = _catalog_dir(settings)
        if folder is None:
            return
        path = folder / OPENED_FILE
        data = _read_json(path)
        episodes = data.get("episodes")
        users = data.get("users")
        if not isinstance(episodes, dict):
            episodes = {}
        if not isinstance(users, dict):
            users = {}
        episodes[slug] = {"at": now, "by": user}
        mine = users.get(user)
        if not isinstance(mine, dict):
            mine = {}
        mine[slug] = now
        if len(mine) > OPENED_PER_PERSON:
            keep = sorted(mine.items(), key=lambda kv: kv[1],
                          reverse=True)[:OPENED_PER_PERSON]
            mine = dict(keep)
        users[user] = mine
        _write_json(path, {"episodes": episodes, "users": users})


def opened(settings: Any, user: str) -> tuple[dict[str, dict], dict[str, float]]:
    """-> ({slug: {"at", "by"}} for anybody, {slug: at} for `user`)."""
    folder = _catalog_dir(settings)
    if folder is None:
        return {}, {}
    data = _read_json(folder / OPENED_FILE)
    anyone = data.get("episodes") if isinstance(data.get("episodes"), dict) else {}
    users = data.get("users") if isinstance(data.get("users"), dict) else {}
    mine = users.get(str(user or "").strip().lower())
    clean_any = {k: v for k, v in anyone.items()
                 if isinstance(v, dict) and isinstance(v.get("at"), (int, float))}
    clean_mine = {k: float(v) for k, v in (mine or {}).items()
                  if isinstance(v, (int, float))}
    return clean_any, clean_mine


# ------------------------------------------------------------------- sizes

class _Sizer:
    """One background walker per catalogue file. See the module docstring."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.wanted: dict[str, str] = {}      # slug -> root, the latest scan
        self.thread: threading.Thread | None = None
        self.cache = _read_json(path)

    def sizes(self) -> dict[str, dict]:
        with self.lock:
            return {k: dict(v) for k, v in self.cache.items()
                    if isinstance(v, dict)}

    def want(self, rows: list[dict]) -> None:
        with self.lock:
            self.wanted = {r["slug"]: r["root"] for r in rows
                           if r.get("slug") and r.get("root")}
            if self.thread is not None and self.thread.is_alive():
                return
            if not self._next_locked():
                return
            self.thread = threading.Thread(target=self._run, daemon=True,
                                           name="cards-picker-sizer")
            self.thread.start()

    def _next_locked(self) -> tuple[str, str] | None:
        now = time.time()
        stale = []
        for slug, root in self.wanted.items():
            got = self.cache.get(slug)
            at = got.get("at", 0.0) if isinstance(got, dict) else 0.0
            if now - at >= SIZE_MAX_AGE_SECONDS:
                stale.append((at, slug, root))
        if not stale:
            return None
        stale.sort()
        _, slug, root = stale[0]
        return slug, root

    def _run(self) -> None:
        while True:
            with self.lock:
                nxt = self._next_locked()
            if nxt is None:
                return
            slug, root = nxt
            result = walk_size(root)
            with self.lock:
                old = self.cache.get(slug) if isinstance(self.cache.get(slug), dict) else {}
                if result is None:
                    # Unreadable right now: keep the last good number and try
                    # again after the usual interval, not in a hot loop.
                    self.cache[slug] = {**old, "at": time.time()}
                else:
                    self.cache[slug] = {**result, "at": time.time()}
                snapshot = dict(self.cache)
            _write_json(self.path, snapshot)


def walk_size(root: str) -> dict | None:
    """{"bytes", "files", "newest", "partial"} for one episode, or None.

    None only when the root itself cannot be read; a subfolder that fails is
    skipped and the answer is marked partial. Symlinks are not followed.
    """
    total = files = seen = 0
    newest = 0.0
    partial = False
    stack = [root]
    try:
        newest = os.stat(root).st_mtime
    except OSError:
        return None
    while stack:
        path = stack.pop()
        try:
            with os.scandir(path) as it:
                for entry in it:
                    seen += 1
                    if seen > SIZE_MAX_ENTRIES:
                        partial = True
                        stack.clear()
                        break
                    try:
                        if entry.is_symlink():
                            continue
                        st = entry.stat(follow_symlinks=False)
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += st.st_size
                            files += 1
                        if st.st_mtime > newest:
                            newest = st.st_mtime
                    except OSError:
                        partial = True
        except OSError:
            if path == root:
                return None
            partial = True
    return {"bytes": total, "files": files, "newest": newest, "partial": partial}


_sizers: dict[str, _Sizer] = {}
_sizers_lock = threading.Lock()


def sizes(settings: Any, rows: list[dict]) -> dict[str, dict]:
    """The sizes known now; asks the walker for any that are missing or old."""
    folder = _catalog_dir(settings)
    if folder is None:
        return {}
    key = str(folder / SIZES_FILE)
    with _sizers_lock:
        sizer = _sizers.get(key)
        if sizer is None:
            sizer = _sizers[key] = _Sizer(folder / SIZES_FILE)
    try:
        sizer.want(rows)
    except Exception:  # noqa: BLE001 - a thread that will not start is no size
        log.exception("Timeline Cards picker: the size walker did not start")
    return sizer.sizes()


# ---------------------------------------------------------------- the tree

def year_of(parts: list[str], mtime: float | None) -> str:
    """The episode's year: a `20xx` folder above it, else its mtime's year."""
    for part in reversed(parts):
        if _YEAR.match(part):
            return part
    if mtime:
        try:
            return time.strftime("%Y", time.localtime(mtime))
        except (OverflowError, OSError, ValueError):
            return ""
    return ""


def folder_parts(vault: str, root: str) -> list[str]:
    """The folders between the vault and the episode, vault excluded."""
    try:
        rel = os.path.relpath(os.path.dirname(root), vault)
    except ValueError:  # another drive on Windows
        return []
    if rel in (".", ""):
        return []
    parts = [p for p in re.split(r"[\\/]+", rel) if p and p != "."]
    return [] if any(p == ".." for p in parts) else parts


def strip_common(paths: list[list[str]]) -> int:
    """How many leading folders EVERY episode shares (`Vault`, usually).

    Those levels carry no choice, so the tree starts below them. At least one
    level is always kept when there is any path at all, so a vault with a
    single year still shows that year as a folder to fold.
    """
    if not paths or any(not p for p in paths):
        return 0
    n = 0
    shortest = min(len(p) for p in paths)
    while n < shortest - 1 and len({p[n] for p in paths}) == 1:
        n += 1
    return n


def build_tree(rows: list[dict]) -> list[dict]:
    """Nest episode rows under their folders. Each row carries `parts`.

    -> [{"kind": "folder", "name", "key", "children", "count", "hot"} | row],
    folders first, both alphabetical: the page reorders by the chosen sort,
    this is only the no-JS order.
    """
    root: dict = {"children": {}, "episodes": []}
    for row in rows:
        node = root
        for part in row.get("parts") or []:
            node = node["children"].setdefault(part, {"children": {}, "episodes": []})
        node["episodes"].append(row)

    def emit(node: dict, prefix: str) -> list[dict]:
        out: list[dict] = []
        for name in sorted(node["children"], key=str.lower):
            key = f"{prefix}/{name}" if prefix else name
            child = node["children"][name]
            kids = emit(child, key)
            out.append({"kind": "folder", "name": name, "key": key,
                        "children": kids, "count": _count(kids),
                        "hot": any(_hot(k) for k in kids)})
        out.extend(sorted(node["episodes"], key=lambda r: str(r.get("name", "")).lower()))
        return out

    return emit(root, "")


def _hot(item: dict) -> bool:
    """Drawn unfolded before any script runs: it holds something live or
    something the reader has opened, which is where they are going next."""
    if item.get("kind") == "folder":
        return bool(item.get("hot"))
    return bool(item.get("opened_mine")) or item.get("state") in ("loading", "ready")


def _count(items: list[dict]) -> int:
    return sum(i["count"] if i.get("kind") == "folder" else 1 for i in items)


def human_bytes(n: float | None) -> str:
    if n is None:
        return ""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit in ("B", "KB") else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def ago_phrase(seconds: float | None) -> str:
    """'just now', '14 min ago', '3 h ago', '5 d ago', '4 mo ago'."""
    if seconds is None:
        return ""
    s = max(0.0, seconds)
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        return f"{int(s // 3600)} h ago"
    if s < 60 * 86400:
        return f"{int(s // 86400)} d ago"
    return f"{int(s // (30 * 86400))} mo ago"


__all__ = ["note_opened", "opened", "sizes", "walk_size", "build_tree",
           "folder_parts", "strip_common", "year_of", "human_bytes",
           "ago_phrase"]
