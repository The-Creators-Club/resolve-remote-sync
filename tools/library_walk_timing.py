"""Live proof that the library walk keeps Resolve's API lock free.

NOT a pytest -- it needs a running Resolve with a project open, and it calls
the REAL resolve_bridge.poll_timeline_items() / get_media_pool_items(), so it
can only be run by hand on a rig.

    E:\\Projects\\resolve-remote-sync\\companion\\.venv\\Scripts\\python.exe ^
        tools\\library_walk_timing.py

Strictly read-only, like tools/library_walk_check.py beside it: no playhead
moves, no project or timeline is opened or closed, nothing is written to the
pool or to the library, and the connection is made only through
resolve_bridge.connect(), which carries the CR-68 script-server guard.

What it prints, per call: which walk answered (library or API), how many
items came back and how many carry a media path, the wall time, and -- the
number this whole exercise is about -- how long _API_LOCK was held. The API
walk holds it for the WHOLE walk; the library walk holds it only for the
handful of cheap calls that name the project and the timeline.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "companion" / "src"))

from ccsync_companion import config as config_mod, resolve_bridge, script_server  # noqa: E402

# Every _API_LOCK hold this process makes, as (call name, seconds).
HOLDS: list[tuple[str, float]] = []


class _TimedBridgeCall(resolve_bridge._bridge_call):
    """resolve_bridge._bridge_call, timed. Measures the HOLD, not the wait:
    the clock starts once the lock is ours."""

    __slots__ = ("_held_from",)

    def __enter__(self):
        entered = super().__enter__()
        self._held_from = time.perf_counter()
        return entered

    def __exit__(self, *exc_info):
        # Only TOP-LEVEL takes are recorded. connect() takes the lock again
        # from inside every public entry point (it is an RLock), so counting
        # nested holds would report the same milliseconds twice.
        if not self._nested:
            HOLDS.append((self._name, time.perf_counter() - self._held_from))
        return super().__exit__(*exc_info)


def guarded_connect():
    """Resolve, or None -- the CR-68 guard, exactly as the check tool does it.

    scriptapp() during Resolve's script-server registration window kills
    scripting for the whole session, for every client on the machine.
    """
    phase, why = script_server.state()
    print("script server: %s (%s)" % (phase, why))
    if phase not in (script_server.READY, script_server.UNKNOWN):
        return None
    return resolve_bridge.connect()


def report(label: str, result: dict, seconds: float, holds: list[tuple[str, float]]) -> None:
    items = result.get("items") or []
    with_path = sum(1 for item in items if str(item.get("file_path") or "").strip())
    sources = sorted({str(item.get("source") or "?") for item in items}) or ["-"]
    held = sum(hold for _name, hold in holds)
    print("  %-26s ok=%-5s source=%-8s items=%-5d with a path=%-5d "
          "wall=%7.1f ms  _API_LOCK held=%7.1f ms  (%s)"
          % (label, result.get("ok"), ",".join(sources), len(items), with_path,
             seconds * 1000.0, held * 1000.0,
             ", ".join("%s %.1f ms" % (name, hold * 1000.0) for name, hold in holds)
             or "no calls"))
    if not result.get("ok"):
        print("      message: %s" % result.get("message"))


def timed(label: str, work) -> dict:
    del HOLDS[:]
    started = time.perf_counter()
    result = work()
    elapsed = time.perf_counter() - started
    report(label, result, elapsed, list(HOLDS))
    return result


def main() -> int:
    resolve_bridge._bridge_call = _TimedBridgeCall

    cfg = config_mod.load_config()
    resolve_bridge.configure_library(cfg)
    print("library_walk = %r  host = %r" % (cfg.get("library_walk"),
                                            cfg.get("library_db_host") or "(from Resolve)"))

    if guarded_connect() is None:
        print("no Resolve to talk to -- nothing measured")
        return 1

    print("\npoll_timeline_items() x3 -- the watcher's own entry point:")
    for attempt in range(3):
        timed("poll #%d" % (attempt + 1), resolve_bridge.poll_timeline_items)
        time.sleep(0.2)

    print("\nget_media_pool_items() x1 -- the media-tree refresh's:")
    timed("pool walk", resolve_bridge.get_media_pool_items)

    print("\nlibrary_status(): %r" % (resolve_bridge.library_status(),))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
