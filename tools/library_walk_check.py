"""Live check: the project library's answers against Resolve's own API.

NOT a pytest -- it needs a running Resolve with a project open, so it can
only ever be run by hand on a rig. Run it before trusting the library walk
on a new library, a new Resolve version, or a machine whose paths are
spelled differently (a Mac reading a Windows-authored library).

    E:\\Projects\\resolve-remote-sync\\companion\\.venv\\Scripts\\python.exe ^
        tools\\library_walk_check.py

Strictly read-only. It never moves the playhead, never opens or closes a
project or timeline, never writes to the library. Every library statement
is a SELECT and every API call is a getter -- deliberately, because this
runs against an editor's live session.

Exit 1 on any path DISAGREEMENT. Item-count differences are reported, not
failed: the library legitimately sees more than the API does (a multicam
answers "" to GetClipProperty("File Path") and hides its angles), which is
the entire reason the walk exists.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "companion" / "src"))

from ccsync_companion import library, resolve_bridge, script_server  # noqa: E402


def _timed(label, work):
    start = time.monotonic()
    result = work()
    return result, time.monotonic() - start


def connect():
    """Resolve, or None. The script-server guard is resolve_bridge's, verbatim.

    Calling scriptapp() while Resolve is still registering with its script
    server takes the server down and kills scripting for the whole session
    -- for every client on the machine, not just this one (CR-68). Going
    through resolve_bridge.connect() means this tool cannot be the poller
    that does it.
    """
    phase, why = script_server.state()
    print("script server: %s (%s)" % (phase, why))
    if phase not in (script_server.READY, script_server.UNKNOWN):
        return None
    return resolve_bridge.connect()


def api_timeline_paths(timeline):
    """{pool uid: File Path} for every item of every track. The slow walk."""
    paths = {}
    items = 0
    for track_type in ("video", "audio"):
        for index in range(1, int(timeline.GetTrackCount(track_type) or 0) + 1):
            for item in timeline.GetItemListInTrack(track_type, index) or []:
                items += 1
                try:
                    clip = item.GetMediaPoolItem()
                except Exception:
                    clip = None
                if not clip:
                    continue
                try:
                    uid = clip.GetUniqueId()
                    paths[str(uid).lower()] = str(clip.GetClipProperty("File Path") or "")
                except Exception:
                    continue
    return items, paths


def api_pool(folder, bin_path="", out=None):
    """One-arg recursive pool walk: {uid: (path, name, bin_path)}."""
    if out is None:
        out = {}
    for clip in folder.GetClipList() or []:
        try:
            out[str(clip.GetUniqueId()).lower()] = (
                str(clip.GetClipProperty("File Path") or ""),
                str(clip.GetName() or ""),
                bin_path,
            )
        except Exception:
            continue
    for sub in folder.GetSubFolderList() or []:
        try:
            name = str(sub.GetName() or "")
        except Exception:
            continue
        api_pool(sub, (bin_path + "/" + name) if bin_path else name, out)
    return out


def report(title, rows):
    width = max(len(str(a)) for a, _b in rows)
    print("\n== %s" % title)
    for name, value in rows:
        print("   %-*s  %s" % (width, name, value))


def compare(title, api_map, lib_map, describe):
    """Path agreement over the uids both sides saw. Returns the mismatches."""
    shared = sorted(set(api_map) & set(lib_map))
    mismatched = [uid for uid in shared if describe(api_map[uid]) != lib_map[uid]]
    report(title, [
        ("uids from the API", len(api_map)),
        ("uids from the library", len(lib_map)),
        ("compared", len(shared)),
        ("agree", len(shared) - len(mismatched)),
        ("disagree", len(mismatched)),
        ("API only", len(set(api_map) - set(lib_map))),
        ("library only", len(set(lib_map) - set(api_map))),
    ])
    for uid in mismatched[:10]:
        print("   ! %s" % uid)
        print("     API     %r" % describe(api_map[uid]))
        print("     library %r" % lib_map[uid])
    if len(mismatched) > 10:
        print("   ... and %d more" % (len(mismatched) - 10))
    return mismatched


def main() -> int:
    resolve = connect()
    if resolve is None:
        print("Resolve is not answering the scripting API; nothing to compare.")
        return 2
    manager = resolve.GetProjectManager()
    project = manager.GetCurrentProject() if manager else None
    if project is None:
        print("no project is open.")
        return 2
    project_name = str(project.GetName() or "")
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print("no timeline is open.")
        return 2
    timeline_name = str(timeline.GetName() or "")
    timeline_uid = str(timeline.GetUniqueId() or "").lower()

    info = library.locate(resolve, project_name, {})
    if info is None:
        print("could not work out which project library %r lives in." % project_name)
        return 2
    report("session", [
        ("project", project_name),
        ("timeline", "%s (%s)" % (timeline_name, timeline_uid)),
        ("library", info.describe()),
    ])

    lib, connect_seconds = _timed("open", lambda: library.ProjectLibrary(info, project_name))
    try:
        api_items, api_paths = None, None
        (api_items, api_paths), api_timeline_seconds = _timed(
            "api timeline", lambda: api_timeline_paths(timeline))
        lib_items, lib_timeline_seconds = _timed(
            "lib timeline", lambda: lib.timeline_items(timeline_uid))
        pool_paths, _ = _timed("paths", lib.pool_paths)

        report("timeline items", [
            ("API items walked", api_items),
            ("API items with a pool clip", len(api_paths)),
            ("API items with a non-empty path", sum(1 for p in api_paths.values() if p)),
            ("library items", len(lib_items)),
            ("library items with a path", sum(1 for i in lib_items if i["file_path"])),
            ("library angles (via_multicam)", sum(1 for i in lib_items if i["via_multicam"])),
            ("API walk", "%.2f s" % api_timeline_seconds),
            ("library walk", "%.3f s (+%.3f s connect)" % (lib_timeline_seconds, connect_seconds)),
            ("speedup", "%.0fx" % (api_timeline_seconds / max(lib_timeline_seconds, 1e-6))),
        ])

        # Only the uids the API could actually resolve a path for: a
        # multicam reports "" and comparing that to the library's answer
        # would be comparing the library against a known API blind spot.
        api_timeline_real = {uid: path for uid, path in api_paths.items() if path}
        bad = compare("timeline paths", api_timeline_real,
                      {uid: pool_paths.get(uid, "") for uid in api_timeline_real
                       if uid in pool_paths},
                      lambda value: value)

        root = project.GetMediaPool().GetRootFolder()
        api_clips, api_pool_seconds = _timed("api pool", lambda: api_pool(root))
        lib_pool, lib_pool_seconds = _timed("lib pool", lib.pool_items)
        by_uid = {item["media_pool_uid"]: item for item in lib_pool}

        report("media pool", [
            ("API clips", len(api_clips)),
            ("library clips", len(lib_pool)),
            ("API walk", "%.2f s" % api_pool_seconds),
            ("library walk", "%.3f s" % lib_pool_seconds),
            ("speedup", "%.0fx" % (api_pool_seconds / max(lib_pool_seconds, 1e-6))),
        ])
        api_pool_real = {uid: value for uid, value in api_clips.items() if value[0]}
        bad += compare("pool paths", api_pool_real,
                       {uid: by_uid[uid]["file_path"] for uid in api_pool_real if uid in by_uid},
                       lambda value: value[0])
        bad += compare("pool bins", api_pool_real,
                       {uid: by_uid[uid]["bin_path"] for uid in api_pool_real if uid in by_uid},
                       lambda value: value[2])
    finally:
        lib.close()

    print("\n%s" % ("DISAGREEMENTS: %d" % len(bad) if bad else "all compared paths agree."))
    return 1 if bad else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
