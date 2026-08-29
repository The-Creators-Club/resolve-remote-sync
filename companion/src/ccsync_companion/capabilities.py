"""What this computer can do, for the fleet job scheduler.

docs/TIMELINE-CARDS-INTO-CCSYNC.md §4.3, phase 0 (2026-08-29). One section on
the report every companion already sends, for the same reason b-roll ingest
added one (BROLL_INGEST_PLAN.md §3.2): the dashboard has never known what any
machine is CAPABLE of. `_nvidia_smi`'s answer has existed on this side since
the b-roll indexer shipped and reached the dashboard only as a refusal string
in `ingest_warning`; "which machines have a GPU" was not an answerable
question about a fleet built to use them.

EVERY FIELD COMES FROM A SEAM THAT ALREADY EXISTS. Nothing here probes
anything new:

    gpu_*      broll_vlm_sidecar.gpu()      (cached; nvidia-smi, no console)
    nvenc      ffmpeg_tools.encoders_if_known
    ffmpeg     ffmpeg_tools.ffmpeg_available (cached 300 s on success)
    ffprobe    the same probe on ffmpeg_tools.ffprobe_for's answer
    whisper    two configured paths, both present on disk
    mounts     job_paths.mounts()            (root NAMES, never paths)
    idle_*     idle.IdleProbe.seconds_idle()
    resolve    resolve_prefs.resolve_is_running + the watcher's project name

Two rules that are not negotiable:

  * **None means cannot tell means NOT IDLE.** `idle_seconds` is reported as
    null when the probe cannot answer, the dashboard's scheduler reads null as
    busy, and the companion's own gate does the same. A section that quietly
    turned "unknown" into a number would be the difference between harnessing
    idle compute and transcoding under the editor's hands.
  * **NOTHING HERE TOUCHES RESOLVE'S SCRIPTING API.** `resolve.running` is a
    process check (resolve_prefs, which fails CLOSED) and `resolve.project` is
    whatever the watcher last saw. A capability probe on a 30 s cadence must
    never be the thing that calls scriptapp() (CR-68, GOTCHAS §15) -- and the
    two job kinds that would need the version, the timeline uid or the
    unlocked flag (`conform`, `resolve-edit`) are pinned to the machine
    they belong to and are never scheduled at all.

Never raises: this is a report section, and B6's rule holds -- a diagnostic
must never be the reason a machine drops off the fleet grid.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod
from . import ffmpeg_tools, job_paths, jobs_media

log = logging.getLogger("ccsync.capabilities")

# The expensive halves (the GPU probe, the ffmpeg/encoder probes) are cached
# by their own modules; this caches the ASSEMBLY, so a 30 s report does not
# re-stat four paths and re-read the config every tick. Short enough that
# plugging a drive in shows up within a minute.
CACHE_SECONDS = 45.0

NVENC_ENCODERS = ("h264_nvenc", "hevc_nvenc")

# The kinds a `jobs_kinds` allow-list may name. `conform` and `resolve-edit`
# are absent and must stay absent (§4.2): every edit is a synthetic keystroke
# into whatever Resolve has open on ONE machine.
KNOWN_KINDS = ("whisper",) + tuple(jobs_media.MEDIA_KINDS)

_lock = threading.Lock()
_cache: Optional[tuple[float, dict[str, Any]]] = None


def reset_cache() -> None:
    """Forget the assembled answer (tests, and a config change)."""
    global _cache
    with _lock:
        _cache = None


def _exists(raw: Any) -> bool:
    text = str(raw or "").strip()
    if not text:
        return False
    try:
        return Path(text).expanduser().exists()
    except (TypeError, ValueError, OSError):
        return False


def whisper_ready(cfg: dict[str, Any]) -> tuple[bool, str]:
    """Can this machine run a `whisper` job? -> (ready, why not).

    BOTH paths or nothing: the venv does the inference and the pipeline
    checkout is what knows how to call it (corpus stage, sidecar format,
    where the transcript goes). One without the other is a machine that would
    claim a job and fail it, which is worse than a machine that never claims.
    """
    python = str(cfg.get("jobs_whisper_python", "") or "").strip()
    pipeline = str(cfg.get("jobs_mulcam_pipeline", "") or "").strip()
    if not python or not pipeline:
        return False, ("jobs_whisper_python and jobs_mulcam_pipeline are not "
                       "both set in this machine's config")
    if not _exists(python):
        return False, f"jobs_whisper_python does not exist here: {python}"
    if not _exists(pipeline):
        return False, f"jobs_mulcam_pipeline does not exist here: {pipeline}"
    if not _exists(Path(pipeline).expanduser() / "pipeline.py"):
        return False, f"there is no pipeline.py under {pipeline}"
    return True, ""


def job_kinds(cfg: dict[str, Any]) -> list[str]:
    """`jobs_kinds` from this machine's config, cleaned. [] = every kind.

    A list, a comma string, or nothing -- config.toml is edited by hand and
    `jobs_kinds = "whisper, peaks"` is what a person writes when the example
    line is out of sight. An entry that is not a kind this build knows is
    DROPPED with a warning rather than obeyed: a typo'd name in an allow-list
    is a machine that silently takes no work at all, which looks exactly like
    a machine that is offline.
    """
    raw = cfg.get("jobs_kinds", None)
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        names = [part.strip() for part in raw.replace(";", ",").split(",")]
    else:
        try:
            names = [str(part).strip() for part in raw]
        except TypeError:
            log.warning("capabilities: jobs_kinds is not a list of kinds (%r); "
                        "this machine will take every kind", raw)
            return []
    out: list[str] = []
    for name in names:
        if not name:
            continue
        if name not in KNOWN_KINDS:
            log.warning("capabilities: jobs_kinds names %r, which is not a job "
                        "kind this build knows (%s) -- ignoring it",
                        name, ", ".join(KNOWN_KINDS))
            continue
        if name not in out:
            out.append(name)
    return out


def _nvenc(cfg: dict[str, Any]) -> bool:
    """proxy_gen._has_nvenc's question, asked without a generator in hand.

    `encoders_if_known` first (zero I/O, and on a machine that generates
    proxies it is already warm), then detect_encoders, which spawns
    `ffmpeg -encoders` ONCE and caches it without a TTL -- a binary's encoder
    list cannot change while it sits on disk. A machine with no proxy
    generator would otherwise report nvenc false for ever, which is a lie
    about hardware the fleet is trying to find.
    """
    path = str(cfg.get("ffmpeg_path", "ffmpeg"))
    try:
        known = ffmpeg_tools.encoders_if_known(path)
        if known is None:
            known = ffmpeg_tools.detect_encoders(path)
    except Exception:
        log.debug("capabilities: encoder probe failed", exc_info=True)
        return False
    if not known:
        return False
    return any(enc in known for enc in NVENC_ENCODERS)


def _ffmpeg(cfg: dict[str, Any]) -> bool:
    try:
        ok, _message = ffmpeg_tools.ffmpeg_available(
            str(cfg.get("ffmpeg_path", "ffmpeg")), use_cache=True)
        return bool(ok)
    except Exception:
        log.debug("capabilities: ffmpeg probe failed", exc_info=True)
        return False


def _ffprobe(cfg: dict[str, Any]) -> bool:
    """Is there a runnable ffprobe beside this machine's ffmpeg? (Phase 1.)

    ITS OWN CAPABILITY, not a corollary of `ffmpeg`, because the three media
    recipes need both and the two can genuinely be apart -- ffprobe is what
    decides a proxy's GOP from the source's frame rate and what proves an
    extracted audio track came out the length it went in. A machine that
    reported ffmpeg alone would claim the work and then guess.

    `ffmpeg_available` is the probe for both (it runs `<binary> -version` and
    caches the success for 300 s); only its message says "ffmpeg", and nothing
    here shows it.
    """
    try:
        path = ffmpeg_tools.ffprobe_for(str(cfg.get("ffmpeg_path", "ffmpeg")))
        ok, _message = ffmpeg_tools.ffmpeg_available(path, use_cache=True)
        return bool(ok)
    except Exception:
        log.debug("capabilities: ffprobe probe failed", exc_info=True)
        return False


def _gpu() -> dict[str, Any]:
    try:
        from . import broll_vlm_sidecar
        return dict(broll_vlm_sidecar.gpu())
    except Exception:
        log.debug("capabilities: GPU probe failed", exc_info=True)
        return {}


def _claude() -> bool:
    """Is there a Claude credential ON THIS MACHINE?

    ADVISORY ONLY in phase 0, and deliberately narrow: the answer that will
    matter is the dashboard's `ai_providers` (decision 7.6 -- we bundle no CLI
    and never will, COMMERCIAL_READINESS item 1), and no `claude-run` job kind
    exists yet. This reports what is here so the fleet grid can show it, and
    nothing schedules on it.
    """
    if str(os.environ.get("ANTHROPIC_API_KEY", "") or "").strip():
        return True
    try:
        return shutil.which("claude") is not None
    except Exception:
        return False


def _load() -> Optional[float]:
    """One-minute load average, or None on a platform without one (Windows).
    None is honest here: a made-up number would be ranked on."""
    try:
        return round(os.getloadavg()[0], 2)          # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None


def build(
    cfg: dict[str, Any],
    idle_probe: Any = None,
    resolve_running_fn: Optional[Callable[[], bool]] = None,
    resolve_project_fn: Optional[Callable[[], Optional[str]]] = None,
    cards_agent_fn: Optional[Callable[[], dict[str, Any]]] = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """The `capabilities` report section. Never raises.

    Every seam arrives as a parameter, the way proxy_gen's do, so the whole
    thing is testable without a GPU, an ffmpeg, a Resolve or a keyboard.
    """
    global _cache
    now = time.monotonic()
    if use_cache:
        with _lock:
            cached = _cache
        if cached is not None and (now - cached[0]) < CACHE_SECONDS:
            answer = dict(cached[1])
            # ...except the two that are the whole point of asking every
            # tick. Idleness changes second by second, and a cached "away"
            # is exactly the stale answer the claim path re-checks against.
            answer["idle_seconds"] = _idle_seconds(idle_probe)
            answer["resolve"] = _resolve_block(resolve_running_fn, resolve_project_fn)
            # ...and the cards role, for the same reason: it starts, refuses
            # and stops while a cached hardware answer sits still, and the
            # grid chip is meant to say which timeline is on screen NOW.
            answer["cards_agent"] = _cards_block(cards_agent_fn)
            return answer

    cfg = cfg or {}
    gpu = _gpu()
    whisper, whisper_detail = whisper_ready(cfg)
    section: dict[str, Any] = {
        "gpu_present": bool(gpu.get("present")),
        "gpu_name": str(gpu.get("name") or ""),
        "gpu_vram_gb": gpu.get("vram_gb"),
        "nvenc": _nvenc(cfg),
        "ffmpeg": _ffmpeg(cfg),
        "ffprobe": _ffprobe(cfg),
        "whisper": whisper,
        # Why not, in the words an admin can act on -- the [ VRAM ] chip's
        # lesson: a capability that is OFF because of a missing setting must
        # say so somewhere other than a log on the machine nobody is at.
        "whisper_detail": whisper_detail,
        "claude": _claude(),
        "mounts": job_paths.mounts(cfg),
        "cpu_count": os.cpu_count(),
        "load": _load(),
        "companion_version": config_mod.VERSION,
        # The runner's own gate, reported so the dashboard's idle floor and
        # this machine's can be compared when they disagree.
        "jobs_enabled": bool(cfg.get("jobs_enabled", True)),
        "jobs_idle_seconds": config_mod.coerce_numeric(cfg, "jobs_idle_seconds", 300),
        # WHICH KINDS THIS MACHINE WILL TAKE (phase 4, 2026-08-30). Empty is
        # ALL KINDS, and it is the default: the only way to be excluded from
        # a kind is to name the kinds you do want. Phase 1 left this open --
        # an editor's laptop could only be taken out of the fleet ENTIRELY
        # (`jobs_enabled = false`), and "this laptop may make a proxy
        # overnight but must never be handed a whisper pass" was unsayable.
        "job_kinds": job_kinds(cfg),
    }
    section["idle_seconds"] = _idle_seconds(idle_probe)
    section["resolve"] = _resolve_block(resolve_running_fn, resolve_project_fn)
    section["cards_agent"] = _cards_block(cards_agent_fn)
    with _lock:
        _cache = (now, dict(section))
    return section


def _idle_seconds(idle_probe: Any) -> Optional[float]:
    """idle.py's contract, unchanged: None means cannot tell, and every reader
    of this field must treat it as NOT IDLE."""
    if idle_probe is None:
        return None
    try:
        value = idle_probe.seconds_idle()
    except Exception:
        log.debug("capabilities: idle probe failed", exc_info=True)
        return None
    return None if value is None else float(value)


def _cards_block(fn: Optional[Callable[[], dict[str, Any]]]) -> dict[str, Any]:
    """Is this machine serving the Timeline Cards page from its Resolve?

    (TIMELINE-CARDS-INTO-CCSYNC.md phase 2.) Four small fields, from the
    role's own status -- no scripting call, no process probe, nothing that
    could make a 30 s capabilities tick expensive. `connected` false with a
    `state` is the interesting case: it names the refusal, which is the
    difference between "nobody turned it on" and "a standalone agent is
    still running there".
    """
    block: dict[str, Any] = {"connected": False, "state": "disabled",
                             "timeline": "", "version": 0, "since": None}
    if fn is None:
        return block
    try:
        answer = fn() or {}
    except Exception:
        log.debug("capabilities: cards_agent_fn failed", exc_info=True)
        return block
    block.update({k: answer.get(k, block[k]) for k in block})
    return block


def _resolve_block(
    running_fn: Optional[Callable[[], bool]],
    project_fn: Optional[Callable[[], Optional[str]]],
) -> dict[str, Any]:
    """What is knowable about Resolve WITHOUT talking to it.

    `installed` is deliberately absent rather than guessed: the only cheap
    answer here is "is it running", and a job kind that needs Resolve is
    pinned to its own machine anyway (§4.2's last two rows, which must never
    become schedulable).
    """
    block: dict[str, Any] = {"running": False, "project": ""}
    if running_fn is not None:
        try:
            block["running"] = bool(running_fn())
        except Exception:
            # resolve_is_running fails CLOSED, and so does this: a probe that
            # cannot answer must not read as "the GPU is free".
            log.debug("capabilities: resolve_running_fn failed", exc_info=True)
            block["running"] = True
    if project_fn is not None:
        try:
            block["project"] = str(project_fn() or "")
        except Exception:
            log.debug("capabilities: resolve_project_fn failed", exc_info=True)
    return block
