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

# dash-cards-2 (2026-09-18): how long a FAILED entry refuses to be rebuilt.
# `open()` now treats a failed entry as absent, which is what makes [ OPEN ]
# mean something again -- but a build that fails SLOWLY (a share that hangs
# before it refuses) plus a landing page somebody keeps clicking is a thread
# per click, so the retry has a floor.
RETRY_FLOOR_SECONDS = 20.0

# bug-dash-cards-jobs-2 (2026-09-25): how long an editor's agent stays with
# the episode they last ENTERED while another of their pages keeps polling a
# different one. `_where` used to be overwritten by every served request, so
# one account with a laptop in episode A and a phone in episode B (the
# module docstring's everyday pair) flipped it several times a second, and
# the agent's `/pending` and `/result` for ONE edit landed on two engines.
# Now only a navigation moves it, or a request into another episode once the
# entered one has had no page request from that person for this long (a
# closed tab, a page served from a service worker's cache with no navigation
# ever reaching us). Two minutes clears Chrome's once-a-minute throttling of
# a background tab, so a hidden page still counts as being there.
WHERE_STALE_SECONDS = 120.0

# logic-cards-7 (2026-09-25): how long an episode may stay LOADING before
# the pool calls it failed. Only the builder thread could ever leave LOADING,
# so a build blocked in a scandir on a share that HANGS rather than refuses
# (RETRY_FLOOR_SECONDS' own shape) held a seat for the life of the container
# and every open landing page polled "opening" all afternoon. Generous on
# purpose: a real build reads an episode off the share and a slow one must
# not be thrown away, which is also why a build that finishes after the
# deadline is still published if its entry is still there and a seat is free
# (`_run_build`).
BUILD_DEADLINE_SECONDS = 10 * 60

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


def _mtime(entry: Any) -> float | None:
    """The folder's own mtime for the picker's DATE sort, or None.

    2026-09-24: one stat per EPISODE (not per file), read while the scan is
    already standing in the parent folder. cards_catalog's walker replaces it
    with the newest mtime anywhere under the episode once it has sized it.
    """
    try:
        if isinstance(entry, str):
            return os.stat(entry).st_mtime
        return entry.stat().st_mtime
    except OSError:
        return None


def episodes(vault: str, depth: int = 4) -> list[dict]:
    """Every episode root under the vault: [{root, name, show, slug}, ...].

    Walks at most `depth` levels down, stopping at any folder that IS an
    episode rather than descending into its Interviewees. Every OSError is a
    folder skipped, never a raise: an offline share must leave the landing
    page drawable.

    FOUR, BECAUSE THE LIVE TREE IS FOUR DEEP (2026-09-14, before the first
    deploy of this page). `DASH_CARDS_VAULT_ROOT` is `/vault` in the
    container -- `install_dashboard_app.py:CARDS_VAULT_MOUNT`, the whole
    `vault_host` share -- and the episode `site.toml` already names is
    `/vault/Vault/2026/FF5/Civil Defence`: `Vault`, `2026`, `FF5`, then the
    episode. At three this scan answered an EMPTY LIST on the real share,
    which is a landing page with nothing on it and no error to explain why.
    `has_transcripts` prunes at the episode, so the extra level costs one
    scandir per show, once every `SCAN_TTL_SECONDS`.
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
                        "mtime": _mtime(entry),
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
            "mtime": _mtime(vault),
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
        # dash-cards-2: when the build gave up, for the retry floor.
        self.failed_at: float | None = None
        # editor -> the last time a request of theirs was served here. The
        # sentence the cap refusal shows, and nothing else: it holds no seat.
        self.seen: dict[str, float] = {}
        # editor -> the last PAGE request of theirs served here. `seen` also
        # takes the agent's stamps (security-1); this one does not, so it can
        # say whether a browser is still in the episode (bug-dash-cards-jobs-2).
        self.page_seen: dict[str, float] = {}

    def occupants(self, within: float = ACTIVE_SECONDS) -> list[str]:
        now = time.time()
        return sorted(who for who, when in self.seen.items()
                      if now - when <= within)

    def last_in_other_than(self, editor: str) -> tuple[str, float | None]:
        """`last_in()` with `editor` left out. ("", None) if nobody else.

        logic-cards-1 (2026-09-25): the close confirm was built from
        `last_in()`, which is whoever sent the newest request - usually the
        person about to press [ CLOSE ] - so "ruskin is in it now" was shown to
        ruskin while alex was editing in it. The confirm has to name the
        person the press takes the episode from.
        """
        me = str(editor or "").strip().lower()
        others = [(who, when) for who, when in self.seen.items() if who != me]
        if not others:
            return "", None
        who, when = max(others, key=lambda kv: kv[1])
        return who, max(0.0, time.time() - when)

    def last_in(self) -> tuple[str, float | None]:
        """(who was in here last, how many seconds ago) - ("", None) if never.

        security-1 (2026-09-18b mediums): the idle release measures SERVED
        REQUESTS, and a person editing OFFLINE in Cards serves none, so after
        ACTIVE_SECONDS their episode reads as empty to everybody else. We
        cannot invent a beat a disconnected browser did not send, so the close
        is made an INFORMED act instead: the landing row and the confirm both
        name who was last in and how long ago, which is the fact the presser
        needs and did not have.
        """
        if not self.seen:
            return "", None
        who, when = max(self.seen.items(), key=lambda kv: kv[1])
        return who, max(0.0, time.time() - when)

    def as_dict(self) -> dict:
        who, ago = self.last_in()
        return {"slug": self.slug, "root": self.root, "name": self.name,
                "show": self.show, "state": self.state, "detail": self.detail,
                "occupants": self.occupants(),
                "last_in": who, "last_in_seconds": ago,
                "opened_at": self.opened_at, "ready_at": self.ready_at,
                # logic-cards-7: how long a LOADING entry has been at it, so
                # the page can say so instead of an unchanging "opening".
                "opening_seconds": (max(0.0, time.time() - self.opened_at)
                                    if self.state == LOADING else None)}


class EnginePool:
    """`{slug: Entry}`, a cap, and the thread that builds one.

    `build(root)` is handed in rather than imported so this module knows
    nothing about the other repo: `cards.py` gives it a callable that
    answers `(engine, asgi)` and raises whatever construction raises.
    """

    def __init__(self, build: Callable[[str], tuple[Any, Any]],
                 cap: int = DEFAULT_CAP,
                 on_evict: Callable[[str], None] | None = None) -> None:
        self._build = build
        # dash-cards-5 (2026-09-18): the dispatcher's `_gates[slug]` holds the
        # a2wsgi middleware, which builds a ThreadPoolExecutor(max_workers=24)
        # in its own __init__. Dropping the pool's reference to the engine left
        # that tuple reachable from the mounted dispatcher for the life of the
        # container, so a deliberate close leaked whatever WSGI threads that
        # episode had used. The pool has no reference to the dispatcher, so the
        # eviction comes in as a callback rather than an import.
        self._on_evict = on_evict
        self.cap = max(1, int(cap or DEFAULT_CAP))
        self._lock = threading.Lock()
        self._entries: dict[str, Entry] = {}
        # editor -> slug, for the agent tunnel: a state push from a companion
        # goes to the engine that editor is in (docs/CARDS_TWO_PROJECTS.md
        # phase 1a). Set from the page's own requests, which is the only
        # place we ever learn it.
        self._where: dict[str, str] = {}
        # editor -> (slug, request id) of the last edit their agent was
        # handed, so its result goes back there (bug-dash-cards-jobs-2).
        self._handed: dict[str, tuple[str, str]] = {}

    def set_evict_hook(self, on_evict: Callable[[str], None] | None) -> None:
        """Wire the dispatcher in after both exist (dash-cards-5)."""
        self._on_evict = on_evict

    # -- reading

    def get(self, slug: str) -> Entry | None:
        with self._lock:
            self._expire_stalled()
            return self._entries.get(slug)

    def entries(self) -> list[Entry]:
        with self._lock:
            self._expire_stalled()
            return list(self._entries.values())

    def _expire_stalled(self) -> None:
        """LOADING past BUILD_DEADLINE_SECONDS -> FAILED. Call under the lock.

        logic-cards-7 (2026-09-25). Lazy, on every read, because nothing else
        in the pool ticks: the landing page's own poll is what notices, and
        the entry then frees its seat and stops the page refreshing. The
        thread is not killed (a thread stuck in a share read cannot be); its
        result is judged when it arrives (`_run_build`).
        """
        now = time.time()
        for entry in self._entries.values():
            if (entry.state == LOADING
                    and now - entry.opened_at > BUILD_DEADLINE_SECONDS):
                entry.state = FAILED
                entry.failed_at = now
                entry.detail = (
                    f"the vault did not answer for "
                    f"{int(BUILD_DEADLINE_SECONDS // 60)} min, so this episode "
                    f"did not open. Press \"Open\" to try again.")
                log.warning("Timeline Cards: %s was still opening after %d s; "
                            "marked failed", entry.root,
                            int(BUILD_DEADLINE_SECONDS))

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

    def slug_of(self, engine: Any) -> str:
        """The slug whose READY entry holds this engine, or "".

        By identity: a slug outlives its engine (close and reopen is a new
        engine behind the same slug), and an edit handed out by the old one
        must not be routed to the new one.
        """
        if engine is None:
            return ""
        with self._lock:
            for slug, entry in self._entries.items():
                if entry.engine is engine and entry.state == READY:
                    return slug
        return ""

    def note_handed(self, editor: str, engine: Any, request_id: Any) -> None:
        """This editor's agent was just handed edit `request_id` by `engine`.

        bug-dash-cards-jobs-2 (2026-09-25): `/pending` and `/result` were
        routed independently, each through `_where`, so an edit taken from
        engine A could have its result posted to engine B. B answered "that
        request is no longer open", and A's next poll published "the Resolve
        agent went away with that edit" for an edit Resolve HAD applied, which
        is an invitation to press it again. The result now goes back to the
        engine that handed the edit out. Best effort, never raises.
        """
        editor = str(editor or "").strip().lower()
        if not editor or request_id is None:
            return
        slug = self.slug_of(engine)
        if not slug:
            return
        with self._lock:
            self._handed[editor] = (slug, str(request_id))

    def handed_engine(self, editor: str, request_id: Any) -> Any:
        """The READY engine that handed this editor's agent `request_id`, or
        None when it was not handed out here (or that episode has closed)."""
        editor = str(editor or "").strip().lower()
        if not editor or request_id is None:
            return None
        with self._lock:
            slug, handed = self._handed.get(editor, ("", ""))
            if not slug or handed != str(request_id):
                return None
            entry = self._entries.get(slug)
        if entry is not None and entry.state == READY:
            return entry.engine
        return None

    # -- writing

    def note_visit(self, slug: str, editor: str, enter: bool = True) -> None:
        """That editor is in that episode. Best effort, never raises.

        `enter` is "they opened it" (a navigation to the page, or the landing
        page's OPEN), which is what moves their agent there. Every other
        request (state polls, media ranges) stamps the seat and moves the
        agent only if the episode it is attached to has had no page request
        from them for WHERE_STALE_SECONDS (bug-dash-cards-jobs-2, 2026-09-25).
        """
        editor = str(editor or "").strip().lower()
        if not editor:
            return
        with self._lock:
            entry = self._entries.get(slug)
            if entry is None:
                return
            now = time.time()
            entry.seen[editor] = now
            entry.page_seen[editor] = now
            # logic-cards-3 (2026-09-25): only a READY episode takes the agent.
            # `/cards/open` notes the presser on an entry that is still
            # LOADING, and pointing `_where` at it detached their Resolve from
            # the episode they were working in for the whole build ("alex is
            # not in a Timeline Cards episode", while he was). Opening one is
            # not moving your Resolve into it; entering its page is.
            if entry.state != READY:
                return
            current = self._where.get(editor, "")
            there = self._entries.get(current) if current else None
            if (enter or there is None or current == slug
                    or now - there.page_seen.get(editor, 0.0)
                    > WHERE_STALE_SECONDS):
                self._where[editor] = slug

    def note_agent(self, editor: str, engine: Any = None) -> None:
        """That editor's Timeline Cards AGENT just drove their episode.

        security-1 (2026-09-18b mediums): `seen` was stamped only by a request
        SERVED THROUGH THE MOUNT, so an editor whose phone or laptop is
        offline - the shipped offline session the sw.js kill switch was
        narrowed to protect - held no seat at all, and any other signed-in
        session could close the engine their companion is driving Resolve
        against. The agent's poll is a second liveness signal for exactly that
        person, on the identity `api._require_fleet_caller` verified, and it
        reaches the container even when their browser cannot. Best effort,
        never raises: `_where` is where the tunnel already routed it, unless
        the call names the `engine` it was actually served by (a result that
        went back to the engine that handed the edit out).

        logic-cards-2 (2026-09-25): the tunnel calls this for an agent doing
        WORK only (a swept timeline, a playhead that moved, a result), never
        for the 25-second `/pending` long poll or a heartbeat ping. The Cards
        role polls from sign-in to shutdown, so stamping every call made
        "occupant" mean "their companion is running", and the idle release,
        the cap sentence and the Who column never lapsed for anyone with the
        role on.
        """
        editor = str(editor or "").strip().lower()
        if not editor:
            return
        slug = self.slug_of(engine) if engine is not None else ""
        with self._lock:
            slug = slug or self._where.get(editor) or ""
            entry = self._entries.get(slug)
            if entry is not None:
                entry.seen[editor] = time.time()

    def open(self, root: str, name: str = "", show: str = "") -> tuple[Entry | None, str]:
        """Open an episode. -> (entry, refusal). Exactly one is set.

        Idempotent: an episode already open (or opening) comes back as it is.
        The refusal is a SENTENCE naming who is where, because "the cap is
        two" tells the person at the keyboard nothing they can act on.
        """
        slug = slug_for(root)
        with self._lock:
            self._expire_stalled()
            entry = self._entries.get(slug)
            if entry is not None and entry.state != FAILED:
                return entry, ""
            # dash-cards-2 (2026-09-18): a FAILED entry is ABSENT, not open.
            # `open()` used to be idempotent on the slug alone, so an episode
            # whose build raised once (the vault share not up yet, Postgres
            # refusing) was handed back for the life of the container: the
            # landing page drew [ FAILED ], offered [ OPEN ], and the click
            # changed nothing, for ever. A failed entry already holds no seat
            # (the `live` count below skips it), so replacing it costs nothing
            # a fresh open would not. The retry floor is what stops a page
            # somebody keeps clicking from starting a build a second.
            if entry is not None:
                since = time.time() - (entry.failed_at or 0.0)
                if since < RETRY_FLOOR_SECONDS:
                    return None, (
                        f"{entry.name} did not open a moment ago. Wait "
                        f"{max(1, int(RETRY_FLOOR_SECONDS - since))} s and "
                        f"press \"Open\" again.")
                self._entries.pop(slug, None)
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
        # dash-cards-3 (2026-09-18): this sentence named a page that does not
        # exist (there is no Settings > Timeline Cards; the only close control
        # in the tree is the form on THIS page) and an act that frees nothing
        # (a seat is held by the ENTRY; closing a tab and letting `occupants()`
        # lapse changes the wording and nothing else). Both halves sent a
        # blocked editor off to do something that could not work. With
        # security-2's self-close in the same change, "close it" is now true:
        # whoever is in an episode can close it themselves, and so can anybody
        # when nobody has been in it for 15 minutes.
        bits = []
        for entry in live:
            who = ", ".join(entry.occupants()) or "nobody in the last 15 min"
            bits.append(f"{entry.name} ({who})")
        return (f"{self.cap} episodes are already open: " + " and ".join(bits)
                + ". Ask whoever is in one to press \"Close\" beside it here, "
                  "or close an idle one yourself. An admin can close any of "
                  "them.")

    def may_close(self, slug: str, editor: str, is_admin: bool) -> str:
        """May this person close that episode? -> "" to allow, else a refusal.

        security-2 (2026-09-18). Opening was available to every session and
        closing was admin-only, with no self-close and no idle release: two
        mistaken opens by one editor parked the whole feature until an admin
        was found or the container restarted, and the refusal told them to do
        the one thing that frees nothing. An admin may still close anything.
        Everyone else may close an episode they are the ONLY occupant of,
        or one nobody has been in for ACTIVE_SECONDS - which is exactly the
        "idle one" the cap refusal now names. Closing is not free (`drop`'s
        docstring: the upstream threads stay), which is why it stays a
        deliberate act with a button and not an eviction.
        """
        if is_admin:
            return ""
        editor = str(editor or "").strip().lower()
        entry = self.get(slug)
        if entry is None:
            return ""
        occupants = entry.occupants()
        # logic-cards-1 (2026-09-25): being ONE of the occupants used to be
        # enough, so ruskin could close the engine alex was editing in, behind
        # a confirm that named ruskin. Your own episode means nobody else is
        # in it.
        if not occupants or occupants == [editor]:
            return ""
        return ("somebody else is in that episode. Ask them to close it, or "
                "an admin can.")

    def _run_build(self, entry: Entry) -> None:
        try:
            engine, asgi = self._build(entry.root)
        except Exception as exc:  # noqa: BLE001 - a failed episode is a state
            log.warning("Timeline Cards: %s did not open (%s: %s)",
                        entry.root, type(exc).__name__, exc)
            with self._lock:
                entry.state = FAILED
                # dash-cards-7 (2026-09-18): the page gets a SHORT reason, not
                # the exception's text. This is the one place in the dashboard
                # that rendered another repo's exception into a browser: a
                # psycopg OperationalError carries host, port, database and
                # user, and an OSError carries container paths. `app.py`'s
                # `unhandled_error` derives nothing from an exception for the
                # same reason. The warning above already has the full text, so
                # nothing is lost to whoever can read the log.
                entry.detail = (f"this episode did not open ({type(exc).__name__}). "
                                f"The dashboard log has the detail.")
                entry.failed_at = time.time()
            return
        with self._lock:
            # CLOSED WHILE IT WAS OPENING. `drop()` and `stop_all()` take the
            # entry out of the registry, and the builder thread is still
            # holding a half-built episode: published here it would be an
            # engine with running threads that nothing has a reference to,
            # for the life of the container (the shape dash-release-jobs-1
            # cost us once already, one layer down).
            orphaned = self._entries.get(entry.slug) is not entry
            late = ""
            if not orphaned and entry.state == FAILED:
                # logic-cards-7 (2026-09-25): the deadline called it failed
                # while this thread was still reading the share. Still the
                # registered entry and a seat free: publish it, because a slow
                # build thrown away is a person waiting another ten minutes.
                # No seat (somebody opened another episode meanwhile): an
                # orphan, exactly as a close would have made it.
                live = [e for e in self._entries.values()
                        if e is not entry and e.state != FAILED]
                if len(live) >= self.cap:
                    late = ("this episode opened too late: every seat was "
                            "taken by then. Press \"Open\" to try again.")
            entry.engine = engine
            if not (orphaned or late):
                # Published under the SAME lock as the checks above: now that
                # a deadline-failed entry can be replaced by a fresh `open()`
                # (logic-cards-7), a gap between deciding and publishing
                # would be a window to publish an engine nothing holds.
                entry.asgi = asgi
                entry.state = READY
                entry.ready_at = time.time()
                entry.detail = f"serving {entry.root}"
        if orphaned or late:
            log.info("Timeline Cards: %s was closed while it was opening",
                     entry.root)
            _stop(entry)                       # outside the lock: it is theirs
            if late:
                entry.detail = late
            return
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
            for who, (where, _rid) in list(self._handed.items()):
                if where == slug:
                    self._handed.pop(who, None)
        if entry is None:
            return "that episode is not open"
        _stop(entry)
        self._evict(slug)
        return f"closed {entry.name}"

    def stop_all(self) -> None:
        """App shutdown. Never raises."""
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
            self._where.clear()
            self._handed.clear()
        for entry in entries:
            _stop(entry)
            self._evict(entry.slug)

    def _evict(self, slug: str) -> None:
        """Tell the dispatcher this slug's gate is dead (dash-cards-5)."""
        if self._on_evict is None:
            return
        try:
            self._on_evict(slug)
        except Exception:  # noqa: BLE001 - a close must not fail on its tidy-up
            log.exception("Timeline Cards: could not evict the gate for %s", slug)


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
