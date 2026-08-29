"""The connection Timeline Cards' engine borrows instead of owning one.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 2 (2026-08-30), §7c "the engine's
bridge contract".

ONE PROCESS, ONE RESOLVE CLIENT, ONE CR-68 GUARD. That is the whole reason
this file exists. `multicam_pipeline/cards/resolve_engine.py` today calls
`mt.connect_resolve()` and carries its own copy of `script_server.py`; run
beside the companion on creator-1 that is two pollers on one machine, and
GOTCHAS §15 says one unguarded poller is enough to kill scripting for both of
them for the whole Resolve session. So the engine stops owning a connection
and is handed one:

    bridge.resolve()          the connected object, or None
    bridge.lock               a context manager -- resolve_bridge's _API_LOCK
    bridge.ready()            CR-68: may scriptapp() be called right now
    bridge.on_edit_start(k)   an edit is about to synthesise keystrokes
    bridge.on_edit_end(k, ok) ...and it is over
    bridge.sweep_items(uid)   the timeline's clips FROM THE PROJECT LIBRARY

The engine never imports DaVinciResolveScript and never calls scriptapp().

**The lock is the hard part** (§3.1). Two schedulers meet on one lock: the
companion's watcher every 3 s, and the engine's 1 s sweep with a 0.1 s
playhead read. The lock is therefore held for the SHORT calls only, and the
expensive per-clip walk -- the one that made a card click take 7 s
(LIBRARY_WALK_PLAN.md) -- comes out of the project library instead, with
_API_LOCK released. Every take is timed (`stats()`), so "the tray went quiet"
has a number attached to it rather than an argument.

**What sweep_items is and is not.** It is the per-clip facts: media pool uid,
clip name, the file on this machine, which track it sits on, and the
multicam it was reached through -- exactly the answers `_learn_media_path`
and `_tokens_for` buy today with one GetClipProperty per clip per sweep. It
is NOT the item geometry: the project library's Sm2TiItem rows carry no
Resolve item UniqueId and their MediaFilePath is a stale snapshot (GOTCHAS
§16), so the item uid, its start and its duration stay API reads -- three
cheap calls a sweep, under the lock, which is the cadence budget in §7c.
None means "no library here": the engine falls back to the API walk it does
today, which is slower and correct.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from . import resolve_bridge, script_server

log = logging.getLogger("ccsync.cards")

# Bumped when anything above changes shape. The role refuses to start an
# engine built against a different one, rather than discovering the
# difference as an AttributeError in the middle of a conform.
CONTRACT_VERSION = 1

# What one take of the API lock should cost. Nothing enforces it -- a native
# call cannot be interrupted (resolve_bridge's BRIDGE_WEDGE_SECONDS says so)
# -- but a take that goes past it is logged with its name, because the whole
# risk of this phase is one scheduler starving the other.
SLOW_TAKE_SECONDS = 0.5
# One line per slow take would be one line per sweep on a busy project.
SLOW_TAKE_REPEAT_SECONDS = 60.0


class _Take:
    """One named take of the companion's API lock, timed.

    Both spellings work, so the engine can be written either way:

        with bridge.lock:                 # the plain context manager
        with bridge.lock("conform"):      # ...named, for the wedge log
    """

    __slots__ = ("_owner", "_name", "_started", "_inner")

    def __init__(self, owner: "CardsBridge", name: str) -> None:
        self._owner = owner
        self._name = name
        self._started = 0.0

    def __call__(self, name: str) -> "_Take":
        return _Take(self._owner, str(name or self._name))

    def __enter__(self) -> "_Take":
        self._inner = resolve_bridge.api_call(self._name)   # type: ignore[attr-defined]
        self._inner.__enter__()
        self._started = time.monotonic()
        return self

    def __exit__(self, *exc: Any) -> bool:
        held = time.monotonic() - self._started
        try:
            return bool(self._inner.__exit__(*exc))
        finally:
            self._owner._note_take(self._name, held)


class CardsBridge:
    """resolve_bridge + library.ProjectLibrary, in the shape the engine wants.

    Every seam is a constructor parameter, so the whole contract can be
    exercised with no Resolve, no database and no keyboard -- which is how
    the companion suite tests everything else that touches Resolve.
    """

    contract_version = CONTRACT_VERSION

    def __init__(
        self,
        cfg: Optional[dict[str, Any]] = None,
        connect_fn: Optional[Callable[[], Any]] = None,
        ready_fn: Optional[Callable[[], bool]] = None,
        items_fn: Optional[Callable[[str], Optional[list[dict]]]] = None,
    ) -> None:
        self.cfg = cfg or {}
        self._connect = connect_fn or resolve_bridge.connect
        self._ready = ready_fn or script_server.ready_to_connect
        self._items = items_fn
        self._stats_lock = threading.Lock()
        self._takes = 0
        self._total_held = 0.0
        self._max_held = 0.0
        self._max_name = ""
        self._slow_logged_at = 0.0
        self._edits = 0
        self._edit: Optional[dict[str, Any]] = None
        self.lock = _Take(self, "timeline-cards")

    # -- the connection ----------------------------------------------------

    def resolve(self) -> Any:
        """The connected scriptapp object, or None. Never raises.

        THE ONE CHOKEPOINT: resolve_bridge.connect(), which asks
        script_server.state() before it touches fusionscript. An engine that
        called scriptapp() itself would be the second unguarded client on
        this machine, which is the failure CR-68 is named after.
        """
        try:
            return self._connect()
        except Exception:
            log.debug("cards: connect failed", exc_info=True)
            return None

    def ready(self) -> bool:
        """May Resolve be talked to at all right now? (CR-68, fails OPEN.)"""
        try:
            return bool(self._ready())
        except Exception:
            # script_server.ready_to_connect never raises; if a future one
            # does, the honest answer is the one it gives itself: fail open,
            # because the only thing this can withhold is a connection.
            return True

    # -- the edits ---------------------------------------------------------

    def on_edit_start(self, kind: str) -> None:
        """An edit is about to drive Resolve with synthetic keystrokes.

        The companion is told rather than asked: nothing here may refuse an
        edit the page has already accepted. What it is FOR is the report and
        the log -- "this machine was mid-conform" is the first question of
        every incident where a timeline ended up wrong, and today it is
        answerable only from the cards server's own stdout.
        """
        with self._stats_lock:
            self._edits += 1
            self._edit = {"kind": str(kind or "?"), "since": time.time()}
        log.info("cards: applying a %s to the open timeline", kind)

    def on_edit_end(self, kind: str, ok: bool = True, note: str = "") -> None:
        with self._stats_lock:
            self._edit = None
        if ok:
            log.info("cards: the %s finished%s", kind, f" ({note})" if note else "")
        else:
            log.warning("cards: the %s failed: %s", kind, note or "no reason given")

    # -- the sweep ---------------------------------------------------------

    def sweep_items(self, tl_uid: str) -> Optional[list[dict]]:
        """The open timeline's clips, read from the PROJECT LIBRARY.

        None means "ask Resolve yourself": the walk is switched off, no
        library could be located, or the one we had stopped answering. That
        is not an error -- it is the state every machine is in until a
        library is found, and the engine's API path is the fallback.

        _API_LOCK is NOT held for this. The read has a 5 s statement timeout
        and five seconds of that lock is five seconds of frozen tray menu and
        of every other scripting client on the machine queueing.
        """
        if self._items is not None:
            return self._items(tl_uid)
        try:
            answer = resolve_bridge.get_timeline_items(allow_cached=True)
        except Exception:
            log.debug("cards: the library sweep failed", exc_info=True)
            return None
        if not isinstance(answer, dict) or not answer.get("ok"):
            return None
        items = answer.get("items") or []
        # Only a LIBRARY answer counts. resolve_bridge falls back to the API
        # walk on its own, and that walk is the 11-95 s per-clip property
        # crawl this whole design exists to keep off the sweep's hot path --
        # taking it here would be slower than the engine's own.
        if any(str(item.get("source") or "") != "library" for item in items):
            return None
        return list(items)

    def library_available(self) -> bool:
        """Is the project library answering? For the refusal message only."""
        try:
            return str(resolve_bridge.library_status().get("source") or "") == "library"
        except Exception:
            return False

    # -- what the report and the log see -----------------------------------

    def _note_take(self, name: str, held: float) -> None:
        with self._stats_lock:
            self._takes += 1
            self._total_held += held
            if held > self._max_held:
                self._max_held, self._max_name = held, name
            slow_at = self._slow_logged_at
            if held >= SLOW_TAKE_SECONDS:
                self._slow_logged_at = time.monotonic()
        if held >= SLOW_TAKE_SECONDS and (time.monotonic() - slow_at) >= SLOW_TAKE_REPEAT_SECONDS:
            log.warning(
                "cards: %s held the Resolve lock for %.2fs -- the watcher and "
                "the tray queue behind it", name, held)

    def stats(self) -> dict[str, Any]:
        """Lock hold times, for the diagnostics bundle and the suite.

        Cumulative and never reset: the number that matters is the WORST
        take since this companion started, not the worst in the last minute.
        """
        with self._stats_lock:
            takes = self._takes
            return {
                "takes": takes,
                "held_total": round(self._total_held, 4),
                "held_max": round(self._max_held, 4),
                "held_max_call": self._max_name,
                "held_mean": round(self._total_held / takes, 4) if takes else 0.0,
                "edits": self._edits,
                "editing": dict(self._edit) if self._edit else None,
            }
