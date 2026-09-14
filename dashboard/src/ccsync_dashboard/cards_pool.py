"""One Timeline Cards engine per EPISODE, keyed by a slug in the URL.

docs/CARDS_TWO_PROJECTS.md phase 1 (2026-09-14). Until now `cards.py` built
ONE `ProjectAgentEngine` at boot and every login looked through it at one
file: `project_engine.open_project()` switches `self.path` in place and says
so in its own docstring ("the answer IS 'the cards are B's now'"), and
`library_engine.set_root()` is the same act one level up. Two people could
edit one cut list together -- the version checks and `_order_check` make that
safe, and that is how the phone and the laptop already work -- but two people
could not be in two different episodes at once.

They can now. This module is the pool and nothing else: it mints the slug,
remembers which roots have an engine, builds them one at a time in a
background thread, and refuses the third.

FOUR THINGS DECIDE THE SHAPE HERE, each of them the hard way:

  * **THE URL IS THE KEY, NOT THE SESSION.** One account on a laptop and a
    phone must be able to sit in two different episodes -- that is the
    everyday pair, not an edge case -- so the slug travels in the path
    (`/cards/p/<slug>/`) and the session only REMEMBERS the last one, to
    offer it at the top of the landing page.
  * **A PATH IS NOT A KEY** (CR-90). Roots are
    `X:/Vault/2026/FF5/Civil Defence`-shaped: spaces, CJK, and a Mac's NFD
    against everyone else's NFC. The slug is minted from the NFC-normalised,
    case-folded path through `root_key` -- the same normalise-to-compare rule
    `db.media_rel_key` follows -- and the readable half of it is decoration.
  * **NO EVICTION.** `ProjectAgentEngine.stop()` sets a flag that almost
    nothing reads: `project_agent.py:685` sets `_stop`, the only reader is
    `project_engine.py:1632`, and the library worker, the tokens worker and
    the translator thread are all `while True`. An LRU would leak a sweep
    and a translator per evicted engine. So the cap is a REFUSAL with a
    sentence naming who is where, and an admin drops one deliberately.
    Eviction arrives when a real `stop()` does, not before.
  * **BUILDING IS NOT A REQUEST.** An engine's construction reads an episode
    off a network share; doing it inside the ASGI call would hold the event
    loop for as long as that takes. `open()` starts a thread and answers
    `loading` immediately, and the landing page waits, which is also what
    makes "loading" a state a person can see rather than a spinner.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
import unicodedata
from typing import Any, Callable

log = logging.getLogger("ccsync.dashboard.cards")

# How many episodes may be open at once. Two is the measured fleet: one
# person in Reproductive Rights and one in Framing Formosa. Raised only
# against a memory measurement (docs/CARDS_TWO_PROJECTS.md §5) -- the
# dashboard is what tells everyone whether their footage is syncing, and it
# outranks this feature.
DEFAULT_CAP = 2

# States an entry can be in. `loading` and `failed` are as real as `ready`:
# the landing page draws all three, because "nothing happened when I clicked"
# is the failure this feature would otherwise ship with.
LOADING = "loading"
READY = "ready"
FAILED = "failed"

# An editor counts as "in" an episode for this long after their last request.
# Only used for the sentence the cap refusal and the landing page show; it
# holds no seat and frees nothing when it lapses.
ACTIVE_SECONDS = 15 * 60

_SLUG_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"


# ------------------------------------------------------------------ the slug

def root_key(root: str) -> str:
    """The comparison form of an episode root. NEVER open a file with this.

    NFC first (CR-90: a Mac's listdir is NFD, the NAS and Windows are NFC,
    and `Matej Simalcik` in the two spellings is two byte strings), then
    separators and case, because the same share is `X:\\Vault` here and
    `/vault` there and neither cares which slash or which case was typed.
    """
    text = unicodedata.normalize("NFC", str(root or "").strip())
    text = text.replace("\\", "/").rstrip("/")
    return text.casefold()


def _label(root: str) -> str:
    """The readable half of a slug: the episode folder's name, ascii-ised.

    Decoration only -- the digest is what makes it unique -- so a root whose
    basename is entirely CJK simply has none, and the slug is the digest.
    """
    base = unicodedata.normalize("NFKD", os.path.basename(root_key(root)))
    out = []
    for ch in base:
        if ch in _SLUG_CHARS:
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:32]


def slug_for(root: str) -> str:
    """A stable, opaque-enough id for one episode root.

    Stable across restarts and across machines (it is a hash of the key, not
    a counter), which is what lets a phone keep an installed app pointed at
    `/cards/p/<slug>/` and lets a link into an episode still work tomorrow.
    """
    digest = hashlib.sha256(root_key(root).encode("utf-8")).hexdigest()[:8]
    label = _label(root)
    return f"{label}-{digest}" if label else digest


def is_slug(text: str) -> bool:
    """Cheap shape check, so a junk path segment never reaches the registry."""
    text = str(text or "")
    if not text or len(text) > 48:
        return False
    return all(ch in _SLUG_CHARS or ch == "-" for ch in text)


# -------------------------------------------------------------- the registry

def has_transcripts(path: str) -> bool:
    """A folder is an episode if it has transcripts in it.

    `multicam_pipeline.cards.roots.has_transcripts`, copied for the reason
    `parse_media_map` is copied in cards.py: importing that module pulls in
    the whole cards config to answer a two-line question, and this one is
    asked from the landing page before any engine exists.
    """
    return any(os.path.isdir(os.path.join(path, d))
               for d in ("Interviewees", "Clips"))


def episodes(vault: str, depth: int = 3) -> list[dict]:
    """Every episode root under the vault: [{root, name, show, slug}, ...].

    Walks at most `depth` levels down (`<vault>/<year>/<show>/<episode>` is
    the shape, and the vault root may be the year itself), stopping at any
    folder that IS an episode rather than descending into its Interviewees.
    Every OSError is a folder skipped, never a raise: an offline share must
    leave the landing page drawable.
    """
    found: dict[str, dict] = {}

    def walk(path: str, left: int) -> None:
        try:
            entries = sorted(os.scandir(path), key=lambda d: d.name.lower())
        except OSError:
            return
        for entry in entries:
            try:
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
            except OSError:
                continue
            if has_transcripts(entry.path):
                key = root_key(entry.path)
                if key not in found:
                    found[key] = {
                        "root": os.path.abspath(entry.path),
                        "name": entry.name,
                        "show": os.path.basename(os.path.dirname(entry.path)),
                        "slug": slug_for(entry.path),
                    }
            elif left > 1:
                walk(entry.path, left - 1)

    vault = str(vault or "").strip()
    if not vault:
        return []
    if has_transcripts(vault):
        found[root_key(vault)] = {
            "root": os.path.abspath(vault),
            "name": os.path.basename(os.path.abspath(vault)),
            "show": os.path.basename(os.path.dirname(os.path.abspath(vault))),
            "slug": slug_for(vault),
        }
    walk(vault, max(1, int(depth)))
    return sorted(found.values(),
                  key=lambda r: (r["show"].lower(), r["name"].lower()))


# --------------------------------------------------------------- the entries

class Entry:
    """One episode's engine, or the attempt at one."""

    def __init__(self, slug: str, root: str, name: str = "", show: str = ""):
        self.slug = slug
        self.root = root
        self.name = name or os.path.basename(root)
        self.show = show
        self.state = LOADING
        self.detail = "opening this episode"
        self.engine: Any = None
        self.asgi: Any = None
        self.opened_at = time.time()
        self.ready_at: float | None = None
        # editor -> the last time a request of theirs was served here. The
        # sentence the cap refusal shows, and nothing else: it holds no seat.
        self.seen: dict[str, float] = {}

    def occupants(self, within: float = ACTIVE_SECONDS) -> list[str]:
        now = time.time()
        return sorted(who for who, when in self.seen.items()
                      if now - when <= within)

    def as_dict(self) -> dict:
        return {"slug": self.slug, "root": self.root, "name": self.name,
                "show": self.show, "state": self.state, "detail": self.detail,
                "occupants": self.occupants(),
                "opened_at": self.opened_at, "ready_at": self.ready_at}


class EnginePool:
    """`{slug: Entry}`, a cap, and the thread that builds one.

    `build(root)` is handed in rather than imported so this module knows
    nothing about the other repo: `cards.py` gives it a callable that
    answers `(engine, asgi)` and raises whatever construction raises.
    """

    def __init__(self, build: Callable[[str], tuple[Any, Any]],
                 cap: int = DEFAULT_CAP) -> None:
        self._build = build
        self.cap = max(1, int(cap or DEFAULT_CAP))
        self._lock = threading.Lock()
        self._entries: dict[str, Entry] = {}
        # editor -> slug, for the agent tunnel: a state push from a companion
        # goes to the engine that editor is in (docs/CARDS_TWO_PROJECTS.md
        # phase 1a). Set from the page's own requests, which is the only
        # place we ever learn it.
        self._where: dict[str, str] = {}

    # -- reading

    def get(self, slug: str) -> Entry | None:
        with self._lock:
            return self._entries.get(slug)

    def entries(self) -> list[Entry]:
        with self._lock:
            return list(self._entries.values())

    def ready_asgi(self, slug: str) -> Any:
        """The mounted app for this slug, or None if it is not ready yet."""
        entry = self.get(slug)
        if entry is None or entry.state != READY:
            return None
        return entry.asgi

    def any_engine(self) -> Any:
        """Any ready engine, or None.

        What `cards_exec.PinnedExecutor` asks through its provider: a pinned
        media job's paths are (root name, relative path) pairs resolved
        against this CONTAINER's mounts -- `vault` / `media` / `tree` -- not
        against an episode root, and `fleet_execute` takes absolute paths. So
        any engine's ffmpeg worker can run any pinned job, and which one it
        is does not matter. What matters is that there may be NONE, which is
        why this is asked when a job needs it and not once at boot.
        """
        for entry in self.entries():
            if entry.state == READY and entry.engine is not None:
                return entry.engine
        return None

    def engine_for(self, editor: str) -> Any:
        """The engine that editor is in, or None. -> phase 1a.

        A companion's `/agent/*` push belongs to the project its owner is
        looking at, and the tunnel already knows who is calling: it
        overwrites the agent's self-asserted hostname with the identity
        `api._require_fleet_caller` verified. With one engine that question
        never had to be asked; with a pool it does, or Alex's sweep lands in
        Ruskin's episode.
        """
        with self._lock:
            slug = self._where.get(str(editor or "").strip().lower())
            entry = self._entries.get(slug or "")
        if entry is not None and entry.state == READY:
            return entry.engine
        return None

    def where(self, editor: str) -> str:
        with self._lock:
            return self._where.get(str(editor or "").strip().lower(), "")

    # -- writing

    def note_visit(self, slug: str, editor: str) -> None:
        """That editor is in that episode. Best effort, never raises."""
        editor = str(editor or "").strip().lower()
        if not editor:
            return
        with self._lock:
            entry = self._entries.get(slug)
            if entry is None:
                return
            entry.seen[editor] = time.time()
            self._where[editor] = slug

    def open(self, root: str, name: str = "", show: str = "") -> tuple[Entry | None, str]:
        """Open an episode. -> (entry, refusal). Exactly one is set.

        Idempotent: an episode already open (or opening) comes back as it is.
        The refusal is a SENTENCE naming who is where, because "the cap is
        two" tells the person at the keyboard nothing they can act on.
        """
        slug = slug_for(root)
        with self._lock:
            entry = self._entries.get(slug)
            if entry is not None:
                return entry, ""
            live = [e for e in self._entries.values() if e.state != FAILED]
            if len(live) >= self.cap:
                return None, self._full_sentence(live)
            entry = Entry(slug, os.path.abspath(root), name=name, show=show)
            self._entries[slug] = entry
        thread = threading.Thread(target=self._run_build, args=(entry,),
                                  name=f"cards-open-{slug}", daemon=True)
        thread.start()
        return entry, ""

    def _full_sentence(self, live: list[Entry]) -> str:
        bits = []
        for entry in live:
            who = ", ".join(entry.occupants()) or "nobody in the last 15 min"
            bits.append(f"{entry.name} ({who})")
        return (f"{self.cap} episodes are already open: " + " and ".join(bits)
                + ". Ask one of them to leave it, or an admin can close an "
                  "idle one on Settings > Timeline Cards.")

    def _run_build(self, entry: Entry) -> None:
        try:
            engine, asgi = self._build(entry.root)
        except Exception as exc:  # noqa: BLE001 - a failed episode is a state
            log.warning("Timeline Cards: %s did not open (%s: %s)",
                        entry.root, type(exc).__name__, exc)
            with self._lock:
                entry.state = FAILED
                entry.detail = f"{type(exc).__name__}: {exc}"
            return
        with self._lock:
            # CLOSED WHILE IT WAS OPENING. `drop()` and `stop_all()` take the
            # entry out of the registry, and the builder thread is still
            # holding a half-built episode: published here it would be an
            # engine with running threads that nothing has a reference to,
            # for the life of the container (the shape dash-release-jobs-1
            # cost us once already, one layer down).
            orphaned = self._entries.get(entry.slug) is not entry
            entry.engine = engine
        if orphaned:
            log.info("Timeline Cards: %s was closed while it was opening",
                     entry.root)
            _stop(entry)                       # outside the lock: it is theirs
            return
        with self._lock:
            entry.asgi = asgi
            entry.state = READY
            entry.ready_at = time.time()
            entry.detail = f"serving {entry.root}"
        log.info("Timeline Cards: %s is open at /cards/p/%s/",
                 entry.root, entry.slug)

    def drop(self, slug: str) -> str:
        """Close one episode deliberately. -> what happened, for the log.

        THIS IS NOT EVICTION AND IT IS NOT FREE. `stop()` in the other repo
        sets a flag the library worker, the tokens worker and the translator
        thread do not read, so those three threads stay for the life of the
        container and their memory with them. What it does buy is the SEAT:
        the cap counts entries, so dropping one lets a third episode open.
        An admin doing this knowingly is the whole of the eviction story
        until a real `stop()` lands (docs/CARDS_TWO_PROJECTS.md §6.1).
        """
        with self._lock:
            entry = self._entries.pop(slug, None)
            for who, where in list(self._where.items()):
                if where == slug:
                    self._where.pop(who, None)
        if entry is None:
            return "that episode is not open"
        _stop(entry)
        return f"closed {entry.name}"

    def stop_all(self) -> None:
        """App shutdown. Never raises."""
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
            self._where.clear()
        for entry in entries:
            _stop(entry)


def _stop(entry: Entry) -> None:
    engine = entry.engine
    entry.engine = None
    entry.asgi = None
    entry.state = FAILED
    entry.detail = "closed"
    if engine is None:
        return
    try:
        stop = getattr(engine, "stop", None)
        if callable(stop):
            stop()
    except Exception:  # noqa: BLE001 - shutdown is not the place to raise
        log.exception("the Timeline Cards engine did not stop cleanly")
