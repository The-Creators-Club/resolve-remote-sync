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
    business -- on ruskin's machine that was 297 of 431 clips.
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
from typing import Any, Callable, Iterable, Optional

from . import canon

log = logging.getLogger("ccsync.proxy_relink")

# Blackmagic Proxy Generator writes H.264 in a QuickTime container next to
# the original (SPEC.md:38). .mp4 is accepted too for non-BPG proxies.
PROXY_EXTENSIONS = (".mov", ".mp4")

PROXY_DIR_NAME = "Proxy"


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
    own spelling -- or None. Never raises."""
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


def plan_relinks(
    items: Iterable[dict[str, Any]],
    local_root: str,
    canonical_prefix: str,
    exists_fn: Optional[Callable[[str], bool]] = None,
    is_windows: Optional[bool] = None,
) -> list[dict[str, Any]]:
    """Decide which clips need their proxy repointed. Pure -- no Resolve calls.

    `items` are resolve_bridge.get_media_pool_items() dicts, which carry
    "proxy_path"/"proxy_state" alongside "file_path".

    Each op: {"media_pool_item", "clip_name", "file_path", "old_proxy",
    "new_proxy", "reason"} where reason is "stale" (a proxy was attached but
    unreachable) or "unlinked" (none attached and auto-link never fired).
    """
    ops: list[dict[str, Any]] = []
    for item in items or []:
        try:
            file_path = str(item.get("file_path") or "").strip()
            if not file_path:
                continue
            if not is_in_tree(file_path, local_root, canonical_prefix, is_windows):
                continue  # the editor's own local/BM-Cloud media -- not ours
            state = item.get("proxy_state")
            if proxy_is_working(state):
                continue
            new_proxy = find_proxy_on_disk(
                file_path, local_root, canonical_prefix, exists_fn, is_windows
            )
            if not new_proxy:
                continue  # nothing synced down yet -- lane B's problem, not ours
            old_proxy = str(item.get("proxy_path") or "").strip()
            plat = _plat_for(file_path, is_windows)
            if old_proxy and _norm(old_proxy, plat) == _norm(new_proxy, plat):
                # Already pointed here and still not working: the file is
                # unreadable, not mis-addressed. Relinking would change
                # nothing, so don't churn the project every 120 s.
                continue
            ops.append(
                {
                    "media_pool_item": item.get("media_pool_item"),
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


def apply_relinks(ops: Iterable[dict[str, Any]], link_fn: Callable[[Any, str], dict[str, Any]]
                  ) -> dict[str, Any]:
    """Run the plan through `link_fn` (resolve_bridge.link_proxy_media).

    Returns {"ok", "relinked", "failed", "message", "failures": [...]}. Never
    raises: one clip Resolve refuses must not stop the rest.
    """
    relinked = 0
    failures: list[str] = []
    for op in ops or []:
        name = op.get("clip_name") or "clip"
        try:
            result = link_fn(op.get("media_pool_item"), op["new_proxy"])
        except Exception:
            log.warning("proxy relink: link failed for %s", name, exc_info=True)
            failures.append(name)
            continue
        if result and result.get("ok"):
            relinked += 1
            log.info(
                "proxy relink: %s -> %s (was %s)",
                name, op["new_proxy"], op.get("old_proxy") or "<unlinked>",
            )
        else:
            failures.append(name)
            log.warning(
                "proxy relink: Resolve refused %s -> %s (%s)",
                name, op["new_proxy"],
                (result or {}).get("message", "no reason given"),
            )
    message = ""
    if relinked or failures:
        message = f"repointed {relinked} proxy link(s)"
        if failures:
            message += f", {len(failures)} refused by Resolve"
    return {
        "ok": not failures,
        "relinked": relinked,
        "failed": len(failures),
        "failures": failures,
        "message": message,
    }
