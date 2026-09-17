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


def _geometry_disagrees(
    file_path: str, item: dict[str, Any], local_root: str, canonical_prefix: str,
    frames_fn: Optional[Callable[[dict[str, Any]], Optional[int]]],
    count_frames_fn: Optional[Callable[[str], Optional[int]]],
    exists: Callable[[str], bool],
) -> bool:
    """Does this clip's stored frame count disagree with its file's?

    False whenever either side cannot be read: a check that cannot run must
    not condemn good media (ffmpeg_tools.count_frames' own rule).
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
        actual = count_frames_fn(probe)
        if not isinstance(actual, int) or actual <= 0:
            return False
        if actual == stored:
            return False
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
            refresh = (_under_archive(file_path, local_root, canonical_prefix)
                       and original_present() and not is_standin()
                       and _geometry_disagrees(file_path, item, local_root,
                                               canonical_prefix, frames_fn,
                                               count_frames_fn, exists))
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
                        and original_present() and not is_standin()):
                    # In the archive that file is the browser PREVIEW, and
                    # attaching it to a clip whose real original is here makes
                    # the editor cut at preview quality with nothing on screen
                    # to say so (audit F1).
                    new_proxy = None
            if refresh:
                plat = _plat_for(file_path, is_windows)
                ops.append({
                    "media_pool_item": item.get("media_pool_item"),
                    "media_pool_uid": item.get("media_pool_uid", ""),
                    "clip_name": item.get("clip_name") or plat.basename(file_path),
                    "file_path": file_path,
                    "old_proxy": str(item.get("proxy_path") or "").strip(),
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
            # BEFORE the proxy link, and the link is skipped when it fails:
            # Resolve would be judging the new proxy against the stand-in's
            # frame count, and a refusal on those terms would be REMEMBERED
            # (note_refusal) and never asked again (plan section 6,
            # 2026-09-17).
            try:
                refresh = replace_fn(media_pool_item, op["file_path"])
            except Exception:
                log.warning("proxy relink: refresh failed for %s", name, exc_info=True)
                refresh = None
            if not (refresh or {}).get("ok"):
                failures.append(name)
                details.append({"clip": name, "reason": REASON_NO_ANSWER})
                continue
            refreshed += 1
            log.info("proxy relink: re-read %s from its own file -- the clip was "
                     "carrying a stand-in's geometry", op["file_path"])
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
    if relinked or failures:
        message = f"repointed {relinked} proxy link(s)"
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
