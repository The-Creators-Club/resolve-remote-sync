"""Point Resolve's per-clip proxy attachment at the proxy lane B just synced.

WHY THIS EXISTS (incident 2026-08-01). A clip carries TWO independent paths:
`File Path` (the original) and `Proxy Media Path`. Only the first is what
"Reveal in Folder" and the Media Offline prompt show, so a clip can look
perfectly linked while its proxy points somewhere that has never existed on
this machine.

When a project is built on a machine whose proxies live on a local or
temporary drive -- `G:\\Temp Transfer\\...`, `F:\\Resolve Renders in Place\\...`,
the base rig's legacy `T:\\Creators_Club` -- those ABSOLUTE proxy paths are
baked into the project and travel to every editor who opens it. There the
drive doesn't exist, so `Proxy` reads "Offline". Resolve then falls back to
the original, which on an editor rig is legitimately absent (lane A is
originals-up-only), and the clip shows Media Offline -- with a byte-perfect
proxy sitting right beside it in the tree, unused.

Crucially, SPEC.md:40's adjacent-`Proxy/` auto-link does NOT rescue this: an
explicit stored proxy path wins, so Resolve never looks next to the original.
That is what this module fixes. It only ever REPOINTS a clip at a proxy that
lane B has already put on disk; it copies, moves and deletes nothing.

Scope rules, deliberately narrow:
  - Only clips whose ORIGINAL is inside the tree (under local_root or on the
    canonical prefix). An editor's own local/BM-Cloud media is none of our
    business -- on one editor's machine that was 297 of 431 clips.
  - Only when the proxy is not already working. Resolve reports a working
    proxy as its RESOLUTION ("1920x1080"); "Offline" means attached but
    unreachable, "None"/"" means nothing attached.
  - Only when the replacement proxy actually exists on disk right now.
  - The new path is derived from the original's OWN spelling, so a clip
    stored canonically (`P:\\...`) gets a canonical proxy path and stays
    portable to every other machine in the fleet.

Resolve itself validates the link (LinkProxyMedia returns False on a
timecode/frame-count mismatch), so a wrong-but-similarly-named file is
refused rather than silently attached.

Never-raise ethos and injectable collaborators, same as the rest of the
package.
"""

from __future__ import annotations

import logging
import ntpath
import os
import posixpath
import threading
import unicodedata
from typing import Any, Callable, Iterable, Optional

from . import canon

log = logging.getLogger("ccsync.proxy_relink")

# Blackmagic Proxy Generator writes H.264 in a QuickTime container next to
# the original (SPEC.md:38). .mp4 is accepted too for non-BPG proxies.
PROXY_EXTENSIONS = (".mov", ".mp4")

PROXY_DIR_NAME = "Proxy"

# -- what the editor is told (RES-3, 2026-09-04) -----------------------------
#
# Until now the attach half of the proxy feature had no user-visible surface
# at all: apply_relinks built "repointed 3 proxy link(s), 12 refused by
# Resolve" and app.py dropped it, the one sentence that answers "why is my
# proxy not attached" was a WARNING in a 5 MB-rotating log, and the per-clip
# reason was DEBUG. These are the same diagnoses in the words an editor can
# act on; apply_relinks returns them as `why` and per-clip `details`, and the
# log lines stay exactly where they were for the people who read logs.
REASON_REFUSED = (
    "Resolve would not attach this proxy. Usually the proxy's timecode does "
    "not match the original."
)
REASON_NO_ANSWER = (
    "Resolve did not answer about this clip, so CCSync will try it again."
)
REASON_NOT_IN_POOL = (
    "This clip is not in the project's media pool any more, so there was "
    "nothing to attach the proxy to."
)
# The case that logged nothing at all: the clip already points at this exact
# proxy file and Resolve still says it is not working, so the file itself is
# unreadable rather than mis-addressed. Relinking it would change nothing,
# which is why plan_relinks skips it -- and why nobody could ever find out.
REASON_UNREADABLE = (
    "Resolve already points at this proxy and still cannot play it, so the "
    "proxy file itself is damaged. Delete it and CCSync will make it again."
)
# comp-resolve-3 (2026-09-18b mediums): the refusal that said nothing. In the
# b-roll archive a `Proxy/<stem>.mp4` is the browser preview, not an editing
# proxy, so it is deliberately left off a clip whose real original is on this
# machine. Without a note the editor saw no proxy, no op and no reason.
REASON_ARCHIVE_PREVIEW = (
    "This file is the b-roll browser preview, not an editing proxy, and the "
    "full quality original is already on this computer. CCSync left the clip "
    "on the original so you are not cutting at preview quality."
)


def proxy_is_working(state: Any) -> bool:
    """Whether Resolve's `Proxy` clip property means "attached and usable".

    Resolve puts the proxy's RESOLUTION in this field when it resolves
    ("1920x1080", "1620x1080", "1080x1920"); "Offline" means a proxy is
    attached but its file isn't reachable, "None"/"" mean none is attached.
    Testing for a leading digit is what distinguishes the three without
    hardcoding a resolution list.
    """
    text = str(state or "").strip()
    return bool(text) and text[0].isdigit()


def _plat(is_windows: Optional[bool]):
    windows = is_windows if is_windows is not None else (os.name == "nt")
    return ntpath if windows else posixpath


def _plat_for(path: str, is_windows: Optional[bool]):
    """The path module for THIS string, falling back to the caller's/host's.

    A canonically-spelled `P:\\...` is handled with ntpath whatever the host
    is: on a Mac, posixpath.dirname("P:\\...\\a.braw") answers the whole
    string and posixpath.join would emit `P:\\...\\Proxy/a.mov` -- a mixed
    spelling that goes into every other machine's project database (see this
    module's rule at the top: the new path is derived from the original's own
    spelling and must stay fleet-portable).
    """
    plat = canon.plat_for(path)
    return plat if plat is ntpath else _plat(is_windows)


def _norm(path: str, plat) -> str:
    return plat.normcase(plat.normpath(str(path)))


def _is_under(path: str, root: str, plat) -> bool:
    if not root:
        return False
    norm_path, norm_root = _norm(path, plat), _norm(root, plat)
    if norm_path == norm_root:
        return True
    sep = plat.sep
    return norm_path.startswith(norm_root if norm_root.endswith(sep) else norm_root + sep)


def is_in_tree(path: str, local_root: str, canonical_prefix: str,
               is_windows: Optional[bool] = None) -> bool:
    """Is this original one of OURS -- in the synced tree, by either spelling?

    On an editor the same file is reachable as both `P:\\Projects\\...` (the
    canonical, fleet-portable form Resolve stores) and
    `F:\\Creators_Club\\Projects\\...` (local_root). Either counts.
    """
    if not path:
        return False
    return (
        _is_under(path, local_root, _plat_for(local_root, is_windows))
        or canon.is_canonical(path, canonical_prefix)
    )


def expected_proxy_paths(original_path: str, is_windows: Optional[bool] = None) -> list[str]:
    """Candidate proxy paths for an original: an adjacent `Proxy/` folder,
    same stem, one of PROXY_EXTENSIONS -- the BPG/Resolve convention the
    whole tree is built on (SPEC.md:13)."""
    if not original_path:
        return []
    plat = _plat_for(original_path, is_windows)
    parent = plat.dirname(str(original_path))
    stem = plat.splitext(plat.basename(str(original_path)))[0]
    if not stem:
        return []
    return [plat.join(parent, PROXY_DIR_NAME, stem + ext) for ext in PROXY_EXTENSIONS]


def _local_twin(path: str, local_root: str, canonical_prefix: str) -> Optional[str]:
    """The same file expressed under local_root instead of the canonical
    prefix. Only used to ANSWER "does it exist" on a process that can't see
    the P: mapping -- it is per-logon-session, so a service or a remote shell
    has no P: even though the editor's own Resolve does, and a macOS editor
    has no P: at all. The linked path is always the canonical one."""
    return canon.canonical_to_local(path, local_root, canonical_prefix)


def find_proxy_on_disk(
    original_path: str,
    local_root: str,
    canonical_prefix: str,
    exists_fn: Optional[Callable[[str], bool]] = None,
    is_windows: Optional[bool] = None,
) -> Optional[str]:
    """The proxy that exists on disk for `original_path`, in the original's
    own spelling -- or None. Never raises.

    PROXY_EXTENSIONS order decides ties, so this prefers the `.mov` editing
    proxy over the `.mp4`. WHETHER a `.mp4` answer may be used is not decided
    here (audit F1, 2026-09-17): in the b-roll archive that file is the
    browser PREVIEW, and plan_relinks is the caller that knows whether the
    clip's real original is on this machine.
    """
    check = exists_fn if exists_fn is not None else os.path.exists
    for candidate in expected_proxy_paths(original_path, is_windows):
        for probe in (candidate, _local_twin(candidate, local_root, canonical_prefix)):
            if not probe:
                continue
            try:
                if check(probe):
                    # Return the candidate, NOT the probe: a canonical
                    # original keeps a canonical proxy path, so the project
                    # stays portable across the fleet.
                    return candidate
            except Exception:
                continue
    return None


# -- the wired rig's refresh (audit F1, plan section 6) ----------------------
#
# A clip born from a stand-in on ANOTHER machine arrives here with the
# stand-in's geometry baked in: 1920x1080 and the preview's frame count, over
# a file that is a 6K ProRes original. Measured in the phase 0 spike
# (2026-09-17): replacing the bytes and reopening the project changes nothing,
# because Resolve does not re-read a file that changed under a clip.
# `ReplaceClip(<the same path>)` is the one call that does.
#
# The ledger is per machine, so "was it born from a stand-in" cannot be asked
# of another machine's history. What CAN be asked is whether the clip's stored
# frame count matches the file on disk, which is the same question with an
# answer this machine can produce.


def _original_on_disk(path: str, local_root: str, canonical_prefix: str,
                      exists: Callable[[str], bool]) -> bool:
    """Is the clip's own file here, by either spelling? Never raises."""
    for probe in (path, _local_twin(path, local_root, canonical_prefix)):
        if not probe:
            continue
        try:
            if exists(probe):
                return True
        except Exception:
            continue
    return False


def _fleet_key(path: str, local_root: str, canonical_prefix: str) -> Optional[str]:
    """This clip's archive-relative, NFC key for the fleet answer, or None.
    Imported lazily, never raises (proxy-tiers-4)."""
    try:
        from . import broll_standins

        return broll_standins.archive_rel_of(path, local_root, canonical_prefix)
    except Exception:
        return None


def _under_archive(path: str, local_root: str, canonical_prefix: str) -> bool:
    """Is this clip in the b-roll archive? Imported lazily, never raises."""
    try:
        from . import broll_standins

        return broll_standins.is_under_archive(path, local_root, canonical_prefix)
    except Exception:
        return False


def _openable_path(path: str, local_root: str, canonical_prefix: str,
                   exists: Callable[[str], bool]) -> Optional[str]:
    """The spelling of this clip a probe can actually open on this machine.

    Never normalised, never re-cased: ffprobe is handed the bytes on disk
    (CR-90's rule for a path something OPENS).
    """
    for probe in (path, _local_twin(path, local_root, canonical_prefix)):
        if not probe:
            continue
        try:
            if exists(probe):
                return probe
        except Exception:
            continue
    return None


def stored_frames(item: dict[str, Any]) -> Optional[int]:
    """The clip's own `Frames` property as an int, or None.

    A dict key rather than a Resolve call: get_media_pool_items does not read
    `Frames` today (three one-arg reads per clip were measured at 0.3 ms
    each, and the pool is thousands of clips), so a caller that wants the
    refresh has to enrich its items first. None everywhere else, which means
    no refresh -- never a guess.
    """
    try:
        value = item.get("frames")
        if value in (None, ""):
            return None
        count = int(round(float(value)))
        return count if count > 0 else None
    except (TypeError, ValueError):
        return None


def frame_counter(ffmpeg_path: str) -> Callable[[str], Optional[int]]:
    """A per-pass memoised ffprobe frame count. Never raises.

    Cached per PASS, not globally: a file whose frame count changed is the
    whole point of asking, and a process-lifetime cache would answer with the
    stand-in's number for ever.
    """
    from . import ffmpeg_tools

    cache: dict[str, Optional[int]] = {}

    def count(path: str) -> Optional[int]:
        key = canon.norm(path)
        if key in cache:
            return cache[key]
        try:
            answer = ffmpeg_tools.count_frames(ffmpeg_path, path)
        except Exception:
            log.debug("proxy relink: could not count the frames of %s", path,
                      exc_info=True)
            answer = None
        cache[key] = answer
        return answer

    return count


def header_frame_estimate(ffmpeg_path: str) -> Callable[[str], Optional[int]]:
    """A HEADER-ONLY frame estimate (duration x fps), or None. Never raises.

    comp-resolve-2 (2026-09-18): the cheap question, asked before the
    expensive one. `ffmpeg_tools.probe_video` reads the container header
    (`-show_streams`, no `-count_packets`), so it costs one open and a few
    kilobytes instead of a full demux of a 2 GB file over SMB. It is an
    ESTIMATE and is only ever used to answer "these two are nowhere near each
    other"; anything closer still goes to the exact count.
    """
    from . import ffmpeg_tools

    def estimate(path: str) -> Optional[int]:
        try:
            info = ffmpeg_tools.probe_video(ffmpeg_path, path)
            duration = float(info.get("duration_s") or 0.0)
            fps = float(info.get("fps") or 0.0)
        except Exception:
            return None
        if duration <= 0 or fps <= 0:
            return None
        frames = int(round(duration * fps))
        return frames if frames > 0 else None

    return estimate


# comp-resolve-2 (2026-09-18): what the geometry question answered about one
# FILE, keyed by its (mtime, size).
#
# `_geometry_disagrees` used to run `ffprobe -count_packets` -- a full demux,
# 60 s timeout, serial, on the media-tree thread -- against every in-tree
# archive clip whose original is present, on every 120 s pass, cached per pass
# only. On the wired rig the archive IS the pool and every original IS
# present: fifty 2 GB clips is ~100 GB read off the share every two minutes,
# competing with lanes A and B for the same link, and the lane watchdog then
# restarts the thread mid-probe so neither the library walk nor the relink
# ever finishes.
#
# The verdict cannot go stale silently: the key is the file's own (mtime,
# size), so the moment the bytes change -- which is the entire event this
# feature exists to notice -- the answer is thrown away and asked again.
# In-process only, for _REFUSALS' reason verbatim: a disk cache would turn one
# bad probe into a permanent verdict, and a restart is the intended way to
# clear it.
_GEOMETRY_LOCK = threading.Lock()
_GEOMETRY_VERDICTS: dict[str, tuple[Optional[tuple[float, int]], bool]] = {}


def _geometry_key(path: Any, stored: Optional[int] = None) -> str:
    """The identity of one question: this file, and the frame count the CLIP
    believes. Two media pool clips can point at one file with different
    stored geometry (one born from a stand-in, one not), and the answer is
    about the pair, not about the file alone."""
    text = str(path or "")
    base = _norm(text, _plat_for(text, None)) if text else ""
    return f"{base}|{stored if stored is not None else ''}"


def remembered_geometry_verdict(
    path: str, stat_fn: Callable[[str], Any] = os.stat,
    stored: Optional[int] = None,
) -> Optional[bool]:
    """The verdict already reached about this exact file, or None."""
    key = _geometry_key(path, stored)
    if not key:
        return None
    with _GEOMETRY_LOCK:
        remembered = _GEOMETRY_VERDICTS.get(key)
    if remembered is None:
        return None
    fingerprint, verdict = remembered
    return verdict if _proxy_fingerprint(str(path), stat_fn) == fingerprint else None


def note_geometry_verdict(path: str, disagrees: bool,
                          stat_fn: Callable[[str], Any] = os.stat,
                          stored: Optional[int] = None) -> None:
    """Remember what the probe (or the refresh) said about this file."""
    key = _geometry_key(path, stored)
    if not key:
        return
    with _GEOMETRY_LOCK:
        _GEOMETRY_VERDICTS[key] = (_proxy_fingerprint(str(path), stat_fn), bool(disagrees))


def reset_geometry_verdicts() -> None:
    """Tests only, exactly as reset_refusals()."""
    with _GEOMETRY_LOCK:
        _GEOMETRY_VERDICTS.clear()


# proxy-tiers-4 (2026-09-18): what the FLEET knows about stand-ins, off the
# report reply.
#
# `broll_standins` is per machine, about an event that happened on another one:
# a stand-in is placed on the REMOTE editor's machine, so the wired rig - the
# only machine the plan's last table row is for, and the one that holds the
# real 6K files - has an empty ledger for exactly those clips by construction.
# What remained there was `_geometry_disagrees`' demux of the whole archive.
#
# The dashboard now holds the fact per (machine, archive rel) and answers
# `standins_known: {rels: [...]}` on the report REPLY for the rels this
# machine listed (the contract is in
# docs/bug-hunt-2026-09-18/ledger/dashboard.md, "proxy-tiers-4 contract").
# THREE STATES, and the third is the one that matters: a reply that carries
# the key is knowledge, a rel in it is "somebody placed a stand-in here", and
# an ABSENT key means THIS DASHBOARD DOES NOT KNOW - which must behave exactly
# as before (ask the probe), never as "there are no stand-ins". Older
# knowledge is kept rather than cleared on an absent key: at worst it costs
# one ReplaceClip that changes nothing, which CR-284R remembers.
_FLEET_LOCK = threading.Lock()
_FLEET_STANDINS: set[str] = set()
_FLEET_KNOWN = False


def note_fleet_standins(resp: Any) -> bool:
    """Read `standins_known` off a report reply. True when it said anything.

    Never raises: this runs on the reporter thread inside the report-response
    fan-out, where an exception would cost the whole reply.
    """
    global _FLEET_KNOWN
    try:
        block = (resp or {}).get("standins_known") if isinstance(resp, dict) else None
        if not isinstance(block, dict):
            return False
        rels = block.get("rels")
        if not isinstance(rels, list):
            return False
        known = set()
        for rel in rels:
            if not isinstance(rel, str) or not rel.strip():
                continue
            text = rel.strip().replace("\\", "/")
            try:
                text = unicodedata.normalize("NFC", text)
            except Exception:
                pass
            known.add(text)
        with _FLEET_LOCK:
            _FLEET_STANDINS.clear()
            _FLEET_STANDINS.update(known)
            _FLEET_KNOWN = True
        log.debug("proxy relink: the fleet knows of %d stand-in(s) among the "
                  "archive clips this machine listed", len(known))
        return True
    except Exception:                                          # noqa: BLE001
        log.debug("proxy relink: could not read standins_known", exc_info=True)
        return False


def fleet_says_standin(archive_rel: Optional[str]) -> Optional[bool]:
    """Has some machine in this fleet placed a stand-in at this archive rel?

    None is "nobody has told us", which is NOT False: the caller must fall
    through to the probe it would have run anyway.
    """
    if not archive_rel:
        return None
    with _FLEET_LOCK:
        if not _FLEET_KNOWN:
            return None
        return archive_rel in _FLEET_STANDINS


def reset_fleet_standins() -> None:
    """Tests only, as reset_refusals()."""
    global _FLEET_KNOWN
    with _FLEET_LOCK:
        _FLEET_STANDINS.clear()
        _FLEET_KNOWN = False


def _geometry_disagrees(
    file_path: str, item: dict[str, Any], local_root: str, canonical_prefix: str,
    frames_fn: Optional[Callable[[dict[str, Any]], Optional[int]]],
    count_frames_fn: Optional[Callable[[str], Optional[int]]],
    exists: Callable[[str], bool],
    is_stale_fn: Optional[Callable[[str], bool]] = None,
    header_frames_fn: Optional[Callable[[str], Optional[int]]] = None,
    stat_fn: Callable[[str], Any] = os.stat,
    on_probe: Optional[Callable[[], None]] = None,
) -> bool:
    """Does this clip's stored frame count disagree with its file's?

    False whenever either side cannot be read: a check that cannot run must
    not condemn good media (ffmpeg_tools.count_frames' own rule).

    THE CHEAP QUESTIONS COME FIRST (comp-resolve-2, 2026-09-18), in this
    order, and the answer is remembered per (path, mtime, size) either way:

      1. a verdict already reached about these exact bytes;
      2. the stand-in ledger: a path it has an entry for whose file is no
         longer the size we placed is a stand-in that has been replaced, and
         needs no probe at all. (It is not sufficient on its own -- the
         ledger is per machine, about an event that happened on another one,
         so the wired rig's ledger is empty for exactly these clips:
         proxy-tiers-4. It is a free short-circuit, not the test.);
      3. a HEADER-only estimate: duration x fps, one open instead of a full
         demux. Used only to answer "nowhere near", which is the shape a
         stand-in's geometry over a real original has;
      4. and only then the exact packet count, once per version of the file.

    `on_probe` is called immediately before any probe that can take seconds,
    so the caller can stamp its watchdog heartbeat PER CLIP rather than per
    pass -- a 30-minute wedge test cannot tell a serial probe run from a
    thread that has stopped.
    """
    if frames_fn is None or count_frames_fn is None:
        return False
    try:
        stored = frames_fn(item)
        if not isinstance(stored, int) or stored <= 0:
            return False
        probe = _openable_path(file_path, local_root, canonical_prefix, exists)
        if not probe:
            return False
        remembered = remembered_geometry_verdict(probe, stat_fn, stored)
        if remembered is not None:
            return remembered
        if is_stale_fn is not None:
            try:
                if is_stale_fn(probe):
                    note_geometry_verdict(probe, True, stat_fn, stored)
                    log.info(
                        "proxy relink: %s held a stand-in this machine placed and "
                        "no longer does -- one ReplaceClip on its own path, no "
                        "probe needed", probe)
                    return True
            except Exception:
                log.debug("proxy relink: the stand-in ledger could not be asked "
                          "about %s", probe, exc_info=True)
        # proxy-tiers-4: the FLEET's answer, before either probe. One dict
        # lookup against a set the last report reply filled, and it is the
        # only mechanism that can work on a wired rig, whose own ledger is
        # empty for exactly these clips. True is conclusive (a clip born from
        # a stand-in somewhere needs one ReplaceClip on its own path, and
        # CR-284R stops that repeating); False is NOT - the dashboard only
        # knows what machines have told it - so a "no" falls through to the
        # questions below exactly as before.
        fleet = fleet_says_standin(
            _fleet_key(file_path, local_root, canonical_prefix))
        if fleet is True:
            note_geometry_verdict(probe, True, stat_fn, stored)
            log.info("proxy relink: the fleet says %s was placed as a stand-in "
                     "by one of its machines -- one ReplaceClip on its own "
                     "path, no probe needed", probe)
            return True
        if header_frames_fn is not None:
            if on_probe is not None:
                try:
                    on_probe()
                except Exception:
                    pass
            estimate = header_frames_fn(probe)
            if isinstance(estimate, int) and estimate > 0 and abs(estimate - stored) <= 1:
                # The header says the file is the length the clip believes.
                # Nothing a stand-in could be hiding behind is this close, and
                # the exact count would cost a full read of the whole file.
                note_geometry_verdict(probe, False, stat_fn, stored)
                return False
        if on_probe is not None:
            try:
                on_probe()
            except Exception:
                pass
        actual = count_frames_fn(probe)
        if not isinstance(actual, int) or actual <= 0:
            return False
        if actual == stored:
            note_geometry_verdict(probe, False, stat_fn, stored)
            return False
        note_geometry_verdict(probe, True, stat_fn, stored)
        log.info(
            "proxy relink: %s reports %d frames and the file has %d -- the clip "
            "was born from a stand-in and needs one ReplaceClip on its own path "
            "(plan section 6, 2026-09-17)", file_path, stored, actual,
        )
        return True
    except Exception:
        log.debug("proxy relink: the geometry check failed for %s", file_path,
                  exc_info=True)
        return False


# -- what Resolve has already refused ---------------------------------------
#
# A refusal leaves NOTHING on the clip: `proxy_path` stays "" and `proxy_state`
# stays "None", so the identical op is planned again on the very next pass.
# app._relink_proxies_once runs off the media-tree thread every 120 s over the
# whole media pool, so 200 clips whose adjacent proxies Resolve won't accept
# (a timecode mismatch -- COMP-MEDIA-1's old output, or the timecode-less
# archive previews R10 describes) cost 200 _API_LOCK'd LinkProxyMedia calls
# and 200 WARNING lines every two minutes: ~144,000 lines a day into the one
# 5 MB-rotating companion.log, plus a permanent stream of GIL-holding native
# calls competing with the tray and the watcher (COMP-MEDIA-5, 2026-08-14).
#
# Every other repeating path in this companion already has this brake --
# proxy_gen's `_failures` cap, the watcher's warn-once, R15 fix 4's per-watcher
# dedupe, app._classify_pool_once's _pool_offered_non_canonical ("a refusal
# must not retry every pass").
#
# IN-PROCESS ONLY, deliberately, and for proxy_gen._failures' reason verbatim:
# "a blacklist persisted to disk turns one bad night for the GPU into a
# permanent refusal to ever proxy those clips again". Here it would be worse --
# the usual repair is a re-encoded or re-synced proxy, and that is exactly what
# re-arms this: the value is the proxy file's (mtime, size) at refusal time, so
# a changed file is a new question and gets asked again.
_REFUSAL_LOCK = threading.Lock()
_REFUSALS: dict[tuple[str, str], Optional[tuple[float, int]]] = {}


def _refusal_key(file_path: Any, new_proxy: Any) -> tuple[str, str]:
    """The identity of one (clip, proxy) pairing.

    Both halves are normalized with the path module that fits the STRING (a
    canonical `P:\\...` is ntpath even on a Mac), so the key a refusal is
    stored under is the key the next pass looks up.
    """
    original, proxy = str(file_path or ""), str(new_proxy or "")
    return (
        _norm(original, _plat_for(original, None)) if original else "",
        _norm(proxy, _plat_for(proxy, None)) if proxy else "",
    )


def _proxy_fingerprint(
    path: str, stat_fn: Callable[[str], Any] = os.stat
) -> Optional[tuple[float, int]]:
    """(mtime, size) of the proxy, or None when it cannot be read.

    None is a legitimate value to STORE and to compare: a proxy that could not
    be statted at refusal time and still cannot be is the same file as far as
    anyone here can tell, and re-offering it would be the churn this exists to
    stop. It becomes a real fingerprint the moment the file is reachable,
    which re-arms the pairing.
    """
    try:
        stat = stat_fn(str(path))
        return (float(stat.st_mtime), int(stat.st_size))
    except Exception:
        return None


def note_refusal(op: dict[str, Any], stat_fn: Callable[[str], Any] = os.stat) -> None:
    """Remember that Resolve refused this pairing. Never raises."""
    try:
        new_proxy = str(op.get("new_proxy") or "")
        if not new_proxy:
            return
        key = _refusal_key(op.get("file_path"), new_proxy)
        with _REFUSAL_LOCK:
            _REFUSALS[key] = _proxy_fingerprint(new_proxy, stat_fn)
    except Exception:
        log.debug("proxy relink: could not record a refusal", exc_info=True)


def is_refused(
    file_path: str, new_proxy: str, stat_fn: Callable[[str], Any] = os.stat
) -> bool:
    """Has Resolve already refused THIS proxy file for this clip?

    False once the proxy's (mtime, size) differ from the ones recorded: a
    re-encoded proxy (proxy_gen), one lane B re-delivered, or one the archive
    sweep remuxed with a corrected timecode is a different file and deserves
    the attempt. Never raises -- a refusal memory that throws would take the
    whole relink pass with it.
    """
    try:
        key = _refusal_key(file_path, new_proxy)
        with _REFUSAL_LOCK:
            if key not in _REFUSALS:
                return False
            remembered = _REFUSALS[key]
        return _proxy_fingerprint(str(new_proxy), stat_fn) == remembered
    except Exception:
        log.debug("proxy relink: refusal check failed", exc_info=True)
        return False


def reset_refusals() -> None:
    """Forget every refusal -- tests only; the companion has one session and
    a restart is the intended (and only) way to clear this in the field."""
    with _REFUSAL_LOCK:
        _REFUSALS.clear()


def plan_relinks(
    items: Iterable[dict[str, Any]],
    local_root: str,
    canonical_prefix: str,
    exists_fn: Optional[Callable[[str], bool]] = None,
    is_windows: Optional[bool] = None,
    stat_fn: Optional[Callable[[str], Any]] = None,
    notes: Optional[list[dict[str, Any]]] = None,
    is_standin_fn: Optional[Callable[[str], bool]] = None,
    frames_fn: Optional[Callable[[dict[str, Any]], Optional[int]]] = None,
    count_frames_fn: Optional[Callable[[str], Optional[int]]] = None,
    header_frames_fn: Optional[Callable[[str], Optional[int]]] = None,
    is_stale_fn: Optional[Callable[[str], bool]] = None,
    on_probe: Optional[Callable[[], None]] = None,
) -> list[dict[str, Any]]:
    """Decide which clips need their proxy repointed. Pure -- no Resolve calls.

    `items` are resolve_bridge.get_media_pool_items() dicts, which carry
    "proxy_path"/"proxy_state" alongside "file_path".

    Each op: {"media_pool_item", "media_pool_uid", "clip_name", "file_path",
    "old_proxy", "new_proxy", "reason"} where reason is "stale" (a proxy was
    attached but unreachable) or "unlinked" (none attached and auto-link
    never fired). "media_pool_item" is None for an item a walk produced with
    no objects; apply_relinks looks it up by uid at the moment of the
    LinkProxyMedia (library walk, 2026-08-26).

    `stat_fn` is the seam `is_refused` reads the proxy's (mtime, size)
    through, alongside `exists_fn` -- the pass keeps NO Resolve calls and no
    real filesystem in a test.

    `notes`, when a caller passes a list, collects {"clip", "path", "reason"}
    for the clips this pass DECIDES NOT TO TOUCH and could not otherwise
    account for -- today the unreadable-proxy case, which logged nothing at
    all before RES-3. Optional so no existing caller changes; ops are
    unaffected either way.

    Three arguments are phase 3's (audit F1, docs/BROLL_PROXY_TIERS_PLAN.md
    section 6, 2026-09-17):

      * `is_standin_fn` answers "is the file at this path the b-roll
        preview's bytes under the original's name". A `.mp4` candidate is
        offered only to a clip whose original is ABSENT or is a stand-in;
        without this rule the 120 s pass would re-attach a 1080p preview to
        every archive clip whose real original is on this machine, two
        minutes after the insert deliberately linked nothing.
      * `frames_fn` reads the clip's STORED frame count and `count_frames_fn`
        counts the file's, and a disagreement plans a REFRESH: a clip born
        from a stand-in keeps the stand-in's geometry for ever, because
        Resolve does not re-read a file that changed under it. Only
        `ReplaceClip(<the same path>)` does (spike, section 3). Both default
        to None, which means "no refresh" -- an answer nobody can give is not
        a disagreement.

    `header_frames_fn`, `is_stale_fn` and `on_probe` are comp-resolve-2
    (2026-09-18): the cheap questions asked before the expensive one, and the
    hook that lets the caller stamp its watchdog heartbeat per CLIP while a
    probe run is in progress. All optional; without them the geometry check
    behaves as 0.9.74 did except that its verdict is now remembered per
    (path, mtime, size) instead of per pass.
    """
    ops: list[dict[str, Any]] = []
    stat = stat_fn if stat_fn is not None else os.stat
    exists = exists_fn if exists_fn is not None else os.path.exists
    standin_of = is_standin_fn
    if standin_of is None:
        # Imported here, not at module scope: plan_relinks is pure, and the
        # ledger is a file the tests inject rather than a dependency this
        # module's own suite should carry.
        from . import broll_standins

        standin_of = broll_standins.is_standin
    for item in items or []:
        try:
            file_path = str(item.get("file_path") or "").strip()
            if not file_path:
                continue
            if not is_in_tree(file_path, local_root, canonical_prefix, is_windows):
                continue  # the editor's own local/BM-Cloud media -- not ours
            # LAZY, and that is ops-efficiency-8 (CR-66/CR-67 item 9): a wired
            # rig's pool is on the SMB share, and a stat per clip per 120 s is
            # the thousand round trips a minute that the media-presence cache
            # exists to stop. Neither of these is asked unless a `.mp4` is the
            # only proxy on offer, or the clip is in the archive.
            answers: dict[str, bool] = {}

            def original_present(path=file_path) -> bool:
                if "present" not in answers:
                    answers["present"] = _original_on_disk(
                        path, local_root, canonical_prefix, exists)
                return answers["present"]

            def is_standin(path=file_path) -> bool:
                if "standin" not in answers:
                    answers["standin"] = bool(original_present()) and bool(
                        standin_of(path))
                return answers["standin"]

            state = item.get("proxy_state")
            # The refresh is scoped to the ARCHIVE, where stand-ins are the
            # only thing that can produce a clip whose stored geometry is not
            # its file's. Project footage is imported on the machine that
            # holds the original, and asking ffprobe about every clip in a
            # 1,300-clip pool every 120 s would cost more than the whole pass.
            under_archive = _under_archive(file_path, local_root,
                                           canonical_prefix)
            refresh = (under_archive
                       and original_present() and not is_standin()
                       and _geometry_disagrees(
                           file_path, item, local_root, canonical_prefix,
                           frames_fn, count_frames_fn, exists,
                           is_stale_fn=is_stale_fn,
                           header_frames_fn=header_frames_fn,
                           stat_fn=stat, on_probe=on_probe))
            if proxy_is_working(state) and not refresh:
                continue
            new_proxy = None
            if not proxy_is_working(state):
                # PROXY_EXTENSIONS is (.mov, .mp4), so this answers with the
                # editing proxy whenever there is one -- and only a `.mp4`
                # answer costs a question about the original.
                new_proxy = find_proxy_on_disk(
                    file_path, local_root, canonical_prefix, exists_fn, is_windows)
                if (new_proxy and str(new_proxy).lower().endswith(".mp4")
                        and under_archive
                        and original_present() and not is_standin()):
                    # In the archive that file is the browser PREVIEW, and
                    # attaching it to a clip whose real original is here makes
                    # the editor cut at preview quality with nothing on screen
                    # to say so (audit F1).
                    #
                    # comp-resolve-3 (2026-09-18b mediums): scoped to the
                    # archive, which is the only place the rule's own comment
                    # is true. OUTSIDE it a `Proxy/<stem>.mp4` is a perfectly
                    # good proxy - proxy_scan.py's fleet invariant is that
                    # existing `.mp4` proxies stay valid and are never re-made
                    # (GENERATED_EXT became `.mov` at R14 only) - so every
                    # pre-R14 project proxy was silently never attached, with
                    # no op AND no note to explain it.
                    clip_name = (item.get("clip_name")
                                 or _plat_for(file_path, is_windows)
                                 .basename(file_path))
                    if notes is not None:
                        notes.append({"clip": clip_name, "path": str(new_proxy),
                                      "reason": REASON_ARCHIVE_PREVIEW})
                    log.debug("proxy relink: %s is the archive preview for %s "
                              "and the original is here -- not attached",
                              new_proxy, clip_name)
                    new_proxy = None
            if refresh:
                plat = _plat_for(file_path, is_windows)
                ops.append({
                    "media_pool_item": item.get("media_pool_item"),
                    "media_pool_uid": item.get("media_pool_uid", ""),
                    "clip_name": item.get("clip_name") or plat.basename(file_path),
                    "file_path": file_path,
                    "old_proxy": str(item.get("proxy_path") or "").strip(),
                    # What the CLIP believes, carried so apply_relinks can
                    # remember the verdict under the same key the probe used
                    # (comp-resolve-2).
                    "stored_frames": frames_fn(item) if frames_fn else None,
                    # comp-resolve-1 = regression-1 (2026-09-18b): the OTHER
                    # half of that same key, and the half that was missed.
                    # `_geometry_disagrees` keys its memory on the spelling
                    # this process can actually open, which on a machine with
                    # no P: mapping (a service, a remote shell, every macOS
                    # editor) is the local twin, not the clip's linked path.
                    # apply_relinks wrote its verdict under `file_path`, so
                    # wherever the two differ nothing ever read it back and
                    # the refresh was re-planned every 120 s for ever, each
                    # pass spending one of the eight allow_automatic grants a
                    # day. Carried rather than re-derived so both sides use
                    # the one answer.
                    "probe_path": _openable_path(
                        file_path, local_root, canonical_prefix, exists) or "",
                    # comp-resolve-6 (2026-09-18): the proxy this clip is
                    # PLAYING right now, carried so apply_relinks can put it
                    # back if the ReplaceClip drops it. Only for a clip whose
                    # proxy works: there is nothing to restore otherwise, and
                    # the `.mp4` rule below (audit F1) must not be routed
                    # around by a re-attach.
                    "reattach_proxy": (str(item.get("proxy_path") or "").strip()
                                       if proxy_is_working(state) else ""),
                    # A refresh may carry a proxy link too (the same clip can
                    # need both), and may carry none at all.
                    "new_proxy": new_proxy,
                    "refresh": True,
                    "reason": "refresh",
                })
                continue
            if not new_proxy:
                continue  # nothing synced down yet -- lane B's problem, not ours
            old_proxy = str(item.get("proxy_path") or "").strip()
            plat = _plat_for(file_path, is_windows)
            if old_proxy and _norm(old_proxy, plat) == _norm(new_proxy, plat):
                # Already pointed here and still not working: the file is
                # unreadable, not mis-addressed. Relinking would change
                # nothing, so don't churn the project every 120 s.
                clip_name = item.get("clip_name") or plat.basename(file_path)
                if notes is not None:
                    notes.append({"clip": clip_name, "path": new_proxy,
                                  "reason": REASON_UNREADABLE})
                log.debug("proxy relink: %s already points at %s and is still not "
                          "working -- the proxy file is unreadable",
                          clip_name, new_proxy)
                continue
            if is_refused(file_path, new_proxy, stat):
                # Resolve has already said no to this exact file, and a
                # refusal leaves nothing on the clip to suppress the retry --
                # so without this the identical op is re-planned, re-locked
                # and re-logged every 120 s for ever (COMP-MEDIA-5).
                continue
            ops.append(
                {
                    "media_pool_item": item.get("media_pool_item"),
                    "media_pool_uid": item.get("media_pool_uid", ""),
                    "clip_name": item.get("clip_name") or plat.basename(file_path),
                    "file_path": file_path,
                    "old_proxy": old_proxy,
                    "new_proxy": new_proxy,
                    "reason": "stale" if old_proxy else "unlinked",
                }
            )
        except Exception:
            log.debug("proxy relink: skipped an unreadable media pool item", exc_info=True)
            continue
    return ops


def _why(relinked: int, refused: list[str], failures: list[str]) -> Optional[str]:
    """One sentence about the pass for the editor, or None (RES-3).

    None rather than "" for a pass with nothing to say: a status reader that
    renders whatever it is given must not put an empty line on the tray.
    """
    parts: list[str] = []
    if relinked:
        parts.append(
            f"Repointed {relinked} proxy file(s) to the copies in your sync folder."
        )
    if refused:
        parts.append(
            f"{len(refused)} could not be attached: usually the proxy's timecode "
            "does not match the original."
        )
    other = len(failures) - len(refused)
    if other > 0:
        parts.append(f"{other} got no answer from Resolve and will be tried again.")
    return " ".join(parts) if parts else None


def apply_relinks(ops: Iterable[dict[str, Any]], link_fn: Callable[[Any, str], dict[str, Any]],
                  stat_fn: Optional[Callable[[str], Any]] = None,
                  resolve_fn: Optional[Callable[[Any], Any]] = None,
                  replace_fn: Optional[Callable[[Any, str], dict[str, Any]]] = None,
                  proxy_state_fn: Optional[Callable[[Any], str]] = None,
                  ) -> dict[str, Any]:
    """Run the plan through `link_fn` (resolve_bridge.link_proxy_media).

    Returns {"ok", "relinked", "refreshed", "attached", "failed", "message",
    "why", "failures": [...], "details": [{"clip", "reason"}]}. Never raises:
    one clip Resolve refuses must not stop the rest.

    An op carrying `refresh` is run through `replace_fn`
    (resolve_bridge.replace_clip, save point and undo journal) on its OWN
    path first: the one call that makes Resolve re-read a file that changed
    underneath a clip (spike, plan section 3).

    `attached`, `why` and `details` are RES-3 (2026-09-04): the counts were
    already here and thrown away by the only caller, and the reasons only
    ever existed as log lines. `attached` is `relinked` under the name a
    status reader uses; `why` is the one sentence that answers "why is my
    proxy not attached", or None when there is nothing to say. The old keys
    stay because a status reader is not the only caller a build may have.

    Every refusal is REMEMBERED (note_refusal) so the next pass does not
    re-offer the same file, and the per-clip line is DEBUG with one WARNING
    summarising the pass -- 200 refused clips used to write 200 WARNINGs every
    120 s (COMP-MEDIA-5, 2026-08-14; R15 fix 4 did the same for the watcher).
    Only a real refusal is remembered: a result whose `reason` is anything
    other than "refused" (link_proxy_media's "scripting_error") counts as a
    failure for this pass and nothing more.
    """
    stat = stat_fn if stat_fn is not None else os.stat
    if resolve_fn is None or replace_fn is None:
        # Imported HERE, not at module scope: plan_relinks is pure and this
        # module's tests stay free of the bridge (and of Resolve).
        from . import resolve_bridge

        if resolve_fn is None:
            resolve_fn = resolve_bridge.resolve_media_pool_item
        if proxy_state_fn is None:
            proxy_state_fn = resolve_bridge.clip_proxy_state
        if replace_fn is None:
            # The sanctioned mutation, save point and undo journal included.
            replace_fn = resolve_bridge.replace_clip
    relinked = 0
    refreshed = 0
    failures: list[str] = []
    refused: list[str] = []
    details: list[dict[str, str]] = []
    for op in ops or []:
        name = op.get("clip_name") or "clip"
        # The op carries the uid; the OBJECT is found here, at the native
        # call, so a walk that produced none still ends in a real
        # LinkProxyMedia (library walk, 2026-08-26). Not a refusal -- there
        # is no pairing to remember -- so note_refusal is not called.
        media_pool_item = resolve_fn(op)
        if media_pool_item is None:
            log.warning(
                "proxy relink: no media pool item for %s (uid %r) -- skipped",
                name, op.get("media_pool_uid", ""),
            )
            failures.append(name)
            details.append({"clip": name, "reason": REASON_NOT_IN_POOL})
            continue
        if op.get("refresh"):
            # comp-resolve-1 = regression-1 (2026-09-18b): the key the PROBE
            # used, which is the only key `_geometry_disagrees` ever reads.
            # `file_path` is the fallback for an op built by an older caller
            # (or by a test that injects its own ops), where the two
            # spellings are the same by construction.
            verdict_path = str(op.get("probe_path") or "") or op["file_path"]
            # BEFORE the proxy link, and the link is skipped when it fails:
            # Resolve would be judging the new proxy against the stand-in's
            # frame count, and a refusal on those terms would be REMEMBERED
            # (note_refusal) and never asked again (plan section 6,
            # 2026-09-17).
            try:
                # comp-resolve-1 (2026-09-18): FORCED. The refresh asks for
                # the clip's OWN path, and without `force` replace_clip
                # short-circuits on exactly that and answers "Already
                # linked" -- so phase 3's one mechanism never ran, while
                # `refreshed` and the INFO line below said it had, and the
                # same op was re-planned every 120 s pass, each one spending
                # an allow_automatic grant out of the 8-per-day budget.
                refresh = replace_fn(media_pool_item, op["file_path"], force=True)
            except TypeError:
                # A caller that injected a two-argument replace_fn (older
                # tests, any other caller of this module).
                refresh = replace_fn(media_pool_item, op["file_path"])
            except Exception:
                log.warning("proxy relink: refresh failed for %s", name, exc_info=True)
                refresh = None
            if not (refresh or {}).get("ok"):
                failures.append(name)
                details.append({"clip": name, "reason": REASON_NO_ANSWER})
                continue
            if refresh.get("changed") is False:
                # Resolve took the call and the geometry did not move. Asking
                # again next pass answers the same and costs another grant,
                # so this file's verdict is remembered until its bytes change
                # (comp-resolve-1's fourth condition, comp-resolve-2's
                # memory). It is not a failure and it is not a refresh.
                #
                # comp-resolve-2 (2026-09-18b mediums): but only when the
                # pass was CLEAN. `retryable` means some ReplaceClip attempt
                # raised, so "the geometry did not move" is Resolve having a
                # bad two seconds, not an answer - and remembering it would
                # disarm phase 3 for this clip for the life of the process,
                # since a file whose original has already arrived never
                # changes its (mtime, size) again.
                if refresh.get("retryable"):
                    log.info("proxy relink: %s was re-read but Resolve did not "
                             "answer cleanly -- asking again next pass",
                             op["file_path"])
                else:
                    note_geometry_verdict(verdict_path, False, stat,
                                          op.get("stored_frames"))
                    log.info("proxy relink: %s was re-read and its geometry did "
                             "not change -- not asked again until the file does",
                             op["file_path"])
                if not op.get("new_proxy"):
                    continue
            else:
                refreshed += 1
                log.info("proxy relink: re-read %s from its own file -- the clip "
                         "was carrying a stand-in's geometry", op["file_path"])
                # comp-resolve-3 / res-companion-5 (2026-09-18): remembered
                # under the frame count the clip believed BEFORE the call.
                # A ReplaceClip Resolve took but that does not move the
                # stored number -- an mp4 with an edit list, a file Resolve
                # reads at a different rate, a clip it will not re-read --
                # otherwise re-plans this op every pass for ever, each one
                # spending one of the 8 allow_automatic grants a day, so
                # genuine proxy relinks are rate-limited out for the rest of
                # it. If the geometry DID move, the next pass reads a
                # different stored count, which is a different key, and asks
                # again as it should.
                note_geometry_verdict(verdict_path, False, stat,
                                      op.get("stored_frames"))
                reattach = str(op.get("reattach_proxy") or "")
                if reattach and proxy_state_fn is not None:
                    # comp-resolve-6: ReplaceClip is the API's re-import
                    # path and may drop the clip's proxy attachment. The
                    # clip had a WORKING proxy before this call, so a blank
                    # one after it is this call's doing, and waiting 120 s
                    # (or a whole allow_automatic interval) to notice would
                    # drop the editor's timeline to the original in the
                    # meantime. Costs one property read per refresh.
                    try:
                        state_now = str(proxy_state_fn(media_pool_item) or "")
                    except Exception:
                        state_now = ""
                    if state_now and not proxy_is_working(state_now):
                        log.info("proxy relink: the refresh left %s with no "
                                 "proxy -- re-attaching %s", name, reattach)
                        try:
                            link_fn(media_pool_item, reattach)
                        except Exception:
                            log.warning("proxy relink: could not put %s back as "
                                        "the proxy for %s", reattach, name,
                                        exc_info=True)
                if not op.get("new_proxy"):
                    continue
        try:
            result = link_fn(media_pool_item, op["new_proxy"])
        except Exception:
            # NOT a refusal: fusionscript going away says nothing about this
            # pairing, and remembering it would skip a clip that never got an
            # answer. It stays a WARNING for the same reason.
            log.warning("proxy relink: link failed for %s", name, exc_info=True)
            failures.append(name)
            details.append({"clip": name, "reason": REASON_NO_ANSWER})
            continue
        if result and result.get("ok"):
            relinked += 1
            log.info(
                "proxy relink: %s -> %s (was %s)",
                name, op["new_proxy"], op.get("old_proxy") or "<unlinked>",
            )
        elif str((result or {}).get("reason") or "refused") != "refused":
            # bug-hunt-2026-09-03 comp-resolve-2: link_proxy_media never
            # raises -- it catches its own fusionscript exception and returns
            # reason="scripting_error" -- so the `except` above cannot be the
            # only place that spares a clip. A Resolve that goes away halfway
            # through a 200-op pass used to be remembered as a permanent
            # refusal of every remaining pairing, and the proxy file's
            # (mtime, size) never changes, so those clips stayed skipped until
            # the tray restarted. A missing reason still counts as a refusal:
            # that is what the pre-2026-09-03 shape meant.
            failures.append(name)
            details.append({"clip": name, "reason": REASON_NO_ANSWER})
            log.warning(
                "proxy relink: %s -> %s got no answer from Resolve (%s) -- not "
                "remembered as a refusal",
                name, op["new_proxy"],
                (result or {}).get("message", "no reason given"),
            )
        else:
            failures.append(name)
            refused.append(name)
            details.append({"clip": name, "reason": REASON_REFUSED})
            note_refusal(op, stat)
            log.debug(
                "proxy relink: Resolve refused %s -> %s (%s)",
                name, op["new_proxy"],
                (result or {}).get("message", "no reason given"),
            )
    if refused:
        log.warning(
            "proxy relink: %d proxy link(s) refused by Resolve (first: %s) -- not "
            "retried until the proxy file changes. A timecode that does not match "
            "the original is the usual cause (KNOWN_BUGS R10)",
            len(refused), refused[0],
        )
    message = ""
    if relinked or failures or refreshed:
        parts = []
        if relinked or not refreshed:
            parts.append(f"repointed {relinked} proxy link(s)")
        if refreshed:
            # comp-resolve-5 (2026-09-18): `refreshed` had one producer and
            # no consumer, so a pass that re-read 40 clips from their own
            # files -- phase 3's whole mechanism -- logged "nothing to do".
            # The operator diagnosing a wired rig had no signal that the
            # refresh was running at all, which is what hid comp-resolve-1.
            parts.append(f"re-read {refreshed} clip(s) from their own file")
        message = ", ".join(parts)
        if failures:
            message += f", {len(failures)} refused by Resolve"
    return {
        "ok": not failures,
        "relinked": relinked,
        # How many clips were re-read from their own file this pass (phase 3).
        # An ADDED key: every existing reader of this dict is unaffected.
        "refreshed": refreshed,
        # The same number under the name a status reader asks for. Two keys
        # rather than a rename: this dict is the whole contract app.py reads.
        "attached": relinked,
        "failed": len(failures),
        "failures": failures,
        "details": details,
        "message": message,
        "why": _why(relinked, refused, failures),
    }
