"""Standalone DaVinci Resolve worker for the music library. One op, then exit.

REHOMED from `music/web/musicweb/resolve_worker.py` (port step 8, 2026-08-10),
near-verbatim. Only three things changed, all forced by the move:

  * connect() bootstraps the scripting environment through resolve_bridge
    instead of hardcoding the Windows Modules path -- this companion also
    ships on macOS (where the path is different) and inside a PyInstaller
    bundle (where fusionscript has to be pointed at our own python3.dll).
  * the result goes out on FILE DESCRIPTOR 1, not sys.stdout: in the windowed
    (console=False) frozen build sys.stdout can be None, which would turn
    every answer into a traceback the parent reads as "no output".
  * main() takes an argv list, so the frozen exe can re-enter itself with
    --music-resolve-worker (see app.run) rather than needing a Python on the
    editor's machine.

Run as a CHILD PROCESS, never in the tray app: scriptapp() returns None (or
blocks for minutes) when Resolve is sitting on the Project Manager window, and
a hung Resolve must not take the companion with it. The parent (music_server)
kills us on a timeout.

    python -m ccsync_companion.music_worker '<json request>'
    ccsync-companion.exe --music-resolve-worker '<json request>'
    -> one line of JSON on stdout

Request: {"action": "status"|"bin"|"under"|"insert", "path": "...", "bin": "Music"}
`path` is already a LOCAL absolute path -- music_server does the
(share, rel_path) translation before it ever gets here, because over Tailscale
the web app's W:\\... and the editor's P:\\... are different machines.

Landmines this code is written around, all learned the hard way in
MulticamPipeline (see its reorder_web.py header):
  * AppendToTimeline WITHOUT trackIndex obeys the timeline's destination-track
    buttons in the UI -- with the destination toggled off it places NOTHING and
    reports no error. Always pass explicit trackIndex + mediaType.
  * Appending to a track that does not exist returns an item yet places
    nothing. AddTrack first.
  * AppendToTimeline always lands on the CURRENT timeline, whatever object you
    hold. Re-read and guard.
  * GetSourceStartFrame/GetSourceEndFrame come back a hair under the integer
    (1299.9999 for 1300). round(), never int().
  * A returned item is not proof of placement -- verify GetStart().
  * endFrame is EXCLUSIVE (placed length = endFrame - startFrame). dur-1 makes
    a clip one frame short and every ripple computed from it is then wrong.
"""
import json
import os
import re
import sys

from . import resolve_bridge

# The argv token the frozen exe re-enters itself with. In a PyInstaller build
# sys.executable IS the companion, so there is no interpreter to hand a script
# path to -- app.run() checks for this before it takes the single-instance
# lock or starts a tray.
WORKER_FLAG = "--music-resolve-worker"

MUSIC_BIN = "Music"
FIRST_MUSIC_TRACK = 2      # keep A1 free for sync/dialogue audio


# ---------------------------------------------------------------- connection
def connect():
    resolve = resolve_bridge.connect()
    if resolve is None:
        # describe_disconnection() tells "Resolve isn't running" apart from
        # "Resolve is running but its script server never came up", which need
        # different actions from the editor (item 19).
        raise RuntimeError(
            "could not reach DaVinci Resolve (%s). Is it running, with "
            "Preferences > System > General > External scripting = Local?"
            % resolve_bridge.describe_disconnection())
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject() if pm else None
    if project is None:
        raise RuntimeError("no project is open in Resolve "
                           "(the Project Manager window counts as no project)")
    return resolve, project, project.GetMediaPool()


def exact_fps(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 24.0
    return f


def tc_to_frame(tc, base):
    drop = ";" in (tc or "")
    parts = [int(p) for p in re.split(r"[:;]", tc or "")]
    if len(parts) != 4:
        return None
    h, m, s, f = parts
    frame = (3600 * h + 60 * m + s) * base + f
    if drop:
        dropped = 4 if base == 60 else 2
        total_min = 60 * h + m
        frame -= dropped * (total_min - total_min // 10)
    return frame


def playhead(tl):
    base = int(round(exact_fps(tl.GetSetting("timelineFrameRate"))))
    fr = tc_to_frame(tl.GetCurrentTimecode(), base)
    return fr if fr is not None else int(tl.GetStartFrame())


# ---------------------------------------------------------------- media pool
def find_folder(folder, name):
    if folder.GetName() == name:
        return folder
    for sub in folder.GetSubFolderList():
        hit = find_folder(sub, name)
        if hit:
            return hit
    return None


def ensure_bin(pool, name):
    root = pool.GetRootFolder()
    if not name:
        return pool.GetCurrentFolder() or root
    return find_folder(root, name) or pool.AddSubFolder(root, name) or root


def existing_item(pool, path):
    """Find a media pool item already pointing at this file, anywhere."""
    target = os.path.normcase(os.path.abspath(path))

    def walk(folder):
        for clip in folder.GetClipList():
            p = clip.GetClipProperty("File Path")
            if p and os.path.normcase(os.path.abspath(p)) == target:
                return clip
        for sub in folder.GetSubFolderList():
            hit = walk(sub)
            if hit:
                return hit
        return None

    return walk(pool.GetRootFolder())


def import_clip(pool, path, bin_name=MUSIC_BIN):
    """Return (MediaPoolItem, already_present). Import is idempotent."""
    have = existing_item(pool, path)
    if have is not None:
        return have, True
    folder = ensure_bin(pool, bin_name)
    previous = pool.GetCurrentFolder()
    pool.SetCurrentFolder(folder)
    try:
        items = pool.ImportMedia([path]) or []
    finally:
        if previous:
            pool.SetCurrentFolder(previous)
    if not items:
        raise RuntimeError("Resolve refused to import %s" % os.path.basename(path))
    return items[0], False


def clip_frames(mp, tl):
    """Source length of the clip in TIMELINE frames."""
    try:
        n = int(round(float(mp.GetClipProperty("Frames") or 0)))
    except (TypeError, ValueError):
        n = 0
    if n > 0:
        return n
    # audio-only clips can report no frame count; derive it from duration
    tl_fps = exact_fps(tl.GetSetting("timelineFrameRate"))
    try:
        secs = float(mp.GetClipProperty("Duration") or 0)
    except (TypeError, ValueError):
        secs = 0.0
    if secs <= 0:
        tc = mp.GetClipProperty("Duration")
        base = int(round(tl_fps))
        got = tc_to_frame(tc, base) if isinstance(tc, str) else None
        return got or base
    return max(1, int(round(secs * tl_fps)))


# ---------------------------------------------------------------- placement
def free_audio_track(tl, rec, dur, first=FIRST_MUSIC_TRACK):
    """Lowest audio track with nothing across [rec, rec+dur). (track, is_new)"""
    for ti in range(first, int(tl.GetTrackCount("audio")) + 1):
        items = tl.GetItemListInTrack("audio", ti) or []
        if not any(int(i.GetStart()) < rec + dur and int(i.GetEnd()) > rec
                   for i in items):
            return ti, False
    return int(tl.GetTrackCount("audio")) + 1, True


def place(tl, pool, mp, rec, track, dur):
    """Append one audio clip at an exact record frame on an exact track.

    endFrame is EXCLUSIVE -- the placed length is endFrame - startFrame. Passing
    dur-1 silently produces a clip one frame short, which then desyncs every
    ripple computed from it.
    """
    res = pool.AppendToTimeline([{
        "mediaPoolItem": mp,
        "startFrame": 0,
        "endFrame": max(1, dur),
        "recordFrame": rec,
        "trackIndex": track,
        "mediaType": 2,                 # audio only
    }]) or []
    item = res[0] if res else None
    # a returned item is not proof it landed -- verify, and clean up if not
    if item is None or int(item.GetStart()) != rec:
        if item is not None:
            tl.DeleteClips([item], False)
        raise RuntimeError(
            "placement failed on A%d at frame %d -- something already occupies "
            "that span, or the track is locked" % (track, rec))
    return item


def guard_current(resolve, project, tl):
    cur = project.GetCurrentTimeline()
    if cur is None:
        raise RuntimeError("no timeline is open")
    if cur.GetUniqueId() != tl.GetUniqueId():
        raise RuntimeError("the current timeline changed -- nothing was placed")
    return cur


# ---------------------------------------------------------------- actions
def act_status(_req):
    resolve, project, pool = connect()
    tl = project.GetCurrentTimeline()
    out = {"ok": True, "project": project.GetName(), "timeline": None}
    if tl is not None:
        out["timeline"] = tl.GetName()
        out["fps"] = tl.GetSetting("timelineFrameRate")
        out["audio_tracks"] = int(tl.GetTrackCount("audio"))
        out["timecode"] = tl.GetCurrentTimecode()
    return out


def act_bin(req):
    resolve, project, pool = connect()
    mp, had = import_clip(pool, req["path"], req.get("bin", MUSIC_BIN))
    return {"ok": True,
            "note": ("already in the media pool (%s)" if had
                     else "imported to the %s bin") % req.get("bin", MUSIC_BIN),
            "clip": mp.GetName()}


def act_under(req):
    """Place on the first free audio track at the playhead. Nothing moves.

    'Place on top' from the timeline cards; for audio the equivalent of a free
    track above the edit is a free track BELOW it, so this starts at A2 and
    leaves A1 for sync audio.
    """
    resolve, project, pool = connect()
    tl = project.GetCurrentTimeline()
    if tl is None:
        raise RuntimeError("no timeline is open")
    mp, _had = import_clip(pool, req["path"], req.get("bin", MUSIC_BIN))

    rec = playhead(tl)
    dur = clip_frames(mp, tl)
    track, is_new = free_audio_track(tl, rec, dur)
    if is_new and not tl.AddTrack("audio", "stereo"):
        raise RuntimeError("could not add an audio track")

    guard_current(resolve, project, tl)
    item = place(tl, pool, mp, rec, track, dur)
    return {"ok": True, "clip": mp.GetName(), "track": "A%d" % track,
            "frame": rec,
            "note": "placed on A%d at the playhead%s -- nothing moved"
                    % (track, " (new track)" if is_new else "")}


def act_insert(req):
    """Ripple insert at the playhead on one audio track.

    Everything at or after the playhead ON THAT TRACK shifts later by the cue's
    length; the cue lands at the playhead. There is no move-clip call in the
    API, so this is delete + re-append at shifted record frames -- the same
    rebuild the multicam pipeline uses.

    Refuses when any affected item is linked to video: rippling one audio track
    under locked picture would silently desync sync sound, which is exactly the
    failure that is expensive to notice late. Use 'place underneath' there.
    """
    resolve, project, pool = connect()
    tl = project.GetCurrentTimeline()
    if tl is None:
        raise RuntimeError("no timeline is open")
    mp, _had = import_clip(pool, req["path"], req.get("bin", MUSIC_BIN))

    rec = playhead(tl)
    dur = clip_frames(mp, tl)
    track = int(req.get("track") or FIRST_MUSIC_TRACK)
    if track > int(tl.GetTrackCount("audio")):
        if not tl.AddTrack("audio", "stereo"):
            raise RuntimeError("could not add an audio track")

    items = tl.GetItemListInTrack("audio", track) or []
    affected = [i for i in items if int(i.GetEnd()) > rec]

    snapshot = []
    for it in affected:
        src = it.GetMediaPoolItem()
        if src is None:
            raise RuntimeError(
                "A%d holds a clip with no media pool source (compound, fusion "
                "or generator) at frame %d -- it cannot be safely re-appended. "
                "Use 'place underneath'." % (track, int(it.GetStart())))
        if it.GetLinkedItems():
            raise RuntimeError(
                "A%d is linked to video at frame %d -- rippling it alone would "
                "desync sync sound. Use 'place underneath'."
                % (track, int(it.GetStart())))
        snapshot.append({
            "mp": src,
            "start": int(it.GetStart()),
            # these come back a hair under the integer -- round, never int
            "src_in": int(round(float(it.GetLeftOffset()))),
            "dur": int(it.GetDuration()),
            "item": it,
        })

    guard_current(resolve, project, tl)

    if snapshot:
        tl.DeleteClips([s["item"] for s in snapshot], False)

    placed = []
    try:
        new_item = place(tl, pool, mp, rec, track, dur)
        placed.append(new_item)
        # shift by what ACTUALLY landed, not by the requested length: a clip
        # whose reported frame count disagrees with the placement by even one
        # frame would otherwise leave a gap or an overlap on every ripple
        shift = int(new_item.GetDuration())
        for s in snapshot:
            res = pool.AppendToTimeline([{
                "mediaPoolItem": s["mp"],
                "startFrame": s["src_in"],
                "endFrame": s["src_in"] + s["dur"],
                "recordFrame": s["start"] + shift,
                "trackIndex": track,
                "mediaType": 2,
            }]) or []
            got = res[0] if res else None
            if got is None or int(got.GetStart()) != s["start"] + shift:
                raise RuntimeError("ripple failed re-placing a clip at frame %d"
                                   % (s["start"] + shift))
            placed.append(got)
    except Exception:
        # put the track back the way it was, then verify the rollback landed
        for p in placed:
            try:
                tl.DeleteClips([p], False)
            except Exception:                                  # noqa: BLE001
                pass
        restored = 0
        for s in snapshot:
            res = pool.AppendToTimeline([{
                "mediaPoolItem": s["mp"],
                "startFrame": s["src_in"],
                "endFrame": s["src_in"] + s["dur"],
                "recordFrame": s["start"],
                "trackIndex": track,
                "mediaType": 2,
            }]) or []
            if res and int(res[0].GetStart()) == s["start"]:
                restored += 1
        raise RuntimeError(
            "insert failed; rolled back %d/%d clip(s) on A%d"
            % (restored, len(snapshot), track))

    return {"ok": True, "clip": mp.GetName(), "track": "A%d" % track,
            "frame": rec,
            "note": "inserted at the playhead on A%d, %d clip(s) rippled later"
                    % (track, len(snapshot))}


ACTIONS = {"status": act_status, "bin": act_bin,
           "under": act_under, "insert": act_insert}


def run_request(req):
    """Dispatch one request dict. Never raises -- the parent parses stdout."""
    try:
        fn = ACTIONS.get(req.get("action"))
        if fn is None:
            raise RuntimeError("unknown action %r" % req.get("action"))
        return fn(req)
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def request_from_argv(argv):
    """The JSON request in `argv` (a list WITHOUT the program name).

    Two spellings, one meaning: a bare positional (source runs, `-m`) and
    `--music-resolve-worker <json>` (the frozen exe re-entering itself, where
    argv also carries whatever else the launcher passed).
    """
    if WORKER_FLAG in argv:
        index = argv.index(WORKER_FLAG)
        payload = argv[index + 1] if len(argv) > index + 1 else ""
    else:
        payload = argv[0] if argv else ""
    if not payload:
        return {}
    return json.loads(payload)


def _emit(payload: str) -> None:
    """Write the answer to FD 1.

    Not sys.stdout: in the windowed (console=False) PyInstaller build it can
    be None -- the same trap broll_server.log_message is written around -- and
    an AttributeError here reads to the parent as "the worker produced no
    output", which names nothing.
    """
    data = payload.encode("utf-8", errors="replace")
    try:
        os.write(1, data)
        return
    except OSError:
        pass
    try:
        if sys.stdout is not None:
            sys.stdout.write(payload)
            sys.stdout.flush()
    except Exception:                                          # noqa: BLE001
        pass


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        req = request_from_argv(argv)
    except Exception as exc:                                   # noqa: BLE001
        out = {"ok": False, "error": "bad worker request: %s" % exc}
    else:
        out = run_request(req)
    _emit(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
