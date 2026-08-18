"""The b-roll ingest orchestrator: this machine crunching its editor's drop.

docs/BROLL_INGEST_PLAN.md §1, §5-§6 (2026-08-18). An editor drags clips onto
the dashboard's b-roll page; the browser creates a batch and hands the uid to
this companion over the loopback; THIS object claims it on the fleet routes,
receives the work order, and then does the whole job locally -- ffmpeg proxy,
sprite, poster, scene detection, frames, a local Qwen3-VL describe -- before
rclone puts the results on the NAS and the server flips the rows live.

Shaped after `proxy_gen.ProxyGenerator` deliberately, because it is the same
kind of thing: a 15 s tick, a gate in priority order, injected seams for
everything that touches the world, `status()`/`block_reason()` as cached
zero-I/O reads for the tray and the reporter, and a background thread that
must never take the companion down with it. What it does NOT share is
proxy_gen's `_gate` itself -- that method reads a dozen fields of instance
state and is pinned by ~2,300 lines of tests; the genuinely reusable part is
about twenty-five lines, and copying those is cheaper than a shared base class
both files would then have to agree with (plan §3.3).

Four rules this file exists to keep:

  * **Indexing beats proxy generation.** The owner reversed the original
    priority on 2026-08-18: while a batch is crunching, `ProxyGenerator` is
    blocked through its `blocked_fn` seam ("waiting: indexing b-roll first"),
    not the other way round. `blocking_reason()` is that seam's answer.
  * **The browser never dictates the work.** `run()` takes a batch uid, a
    staging id and a run mode. Names, tiers, taxonomy, archive paths and the
    lease all come back from `claim` under the fleet token.
  * **Every transition is on disk before it is believed.** The state file is
    rewritten atomically at each checkpoint, so a companion killed mid-batch
    re-claims and resumes at the stage the item had reached rather than at
    zero. A latch that lives only in memory is not a latch (SYNC_SAFETY.md's
    lesson, applied to a feature that runs for hours unattended).
  * **410 means stop, quietly.** The server answers 410 to every way a claim
    can end -- expired, cancelled, taken, finished -- and the answer to all of
    them is the same one.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional

from . import broll_ingest_media as media_mod
from . import broll_server
from . import broll_upload
from . import broll_vlm_sidecar as sidecar_mod
from . import config as config_mod
from . import ingest_kinds
from . import popup
from . import root_guard
from . import upgrade as upgrade_mod

log = logging.getLogger("ccsync.brollingest")


class _KindLog:
    """`log`, with the kind stamped on every line.

    Every line in this module used to begin `broll ingest:` as a literal.
    Music runs the SAME methods (docs/MUSIC_INGEST_PLAN.md §2), so a literal
    would have an operator reading "broll ingest: track 4 failed" while
    debugging a music batch. Prefixing here rather than at 65 call sites keeps
    the diff against the b-roll implementation to the word `self`, which is
    what makes "the b-roll behaviour is exactly preserved" checkable.
    """

    def __init__(self, logger: logging.Logger, tag: str) -> None:
        self._log = logger
        self._tag = f"{tag} ingest: "

    def debug(self, message, *args, **kwargs):
        self._log.debug(self._tag + message, *args, **kwargs)

    def info(self, message, *args, **kwargs):
        self._log.info(self._tag + message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        self._log.warning(self._tag + message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        self._log.error(self._tag + message, *args, **kwargs)

    def exception(self, message, *args, **kwargs):
        self._log.exception(self._tag + message, *args, **kwargs)

# Where the fleet routes live under the dashboard (docs/API.md §6a). The
# dashboard's login_gate carves exactly this prefix out for a companion token,
# so it is not a string to tidy. The music kind's own prefix (§6b) is carved
# out by a SEPARATE regex, which is why the value travels on the kind
# (`ingest_kinds.py`) rather than being derived from it here.
API_PREFIX = ingest_kinds.BROLL_KIND.api_prefix

TICK_SECONDS = 15.0
HEARTBEAT_SECONDS = 30.0
HTTP_TIMEOUT_SECONDS = 20.0

# Long enough for a 40 GB original on a slow card reader, short enough that a
# vanished drive does not hold the worker thread for ever.
MEDIA_TIMEOUT_SECONDS = media_mod.RUN_TIMEOUT_SECONDS

STATE_FILENAME = ingest_kinds.BROLL_KIND.state_filename

# How many times one clip may fail before it is left alone. Two, not three:
# the second attempt is already the CPU fallback for a proxy NVENC refused,
# and a third would only be a third identical failure with an hour of the
# editor's evening in it.
MAX_ITEM_ATTEMPTS = 2

# How many times an item's uploads may be re-sent after the server has looked
# for them and not found them. Three: rclone writes a .partial and renames, so
# a file the server cannot stat is a transfer that really did not land, and the
# fourth attempt would be the fourth identical one.
MAX_UPLOAD_ATTEMPTS = 3

# The verify gate on a finished proxy: a file that decodes to less than this
# much of the source's duration is not a proxy, it is the first few seconds of
# one (proxy_gen.VERIFY_DURATION_RATIO, same number for the same reason).
VERIFY_DURATION_RATIO = 0.97

# -- gate states. proxy_gen's vocabulary plus the three this feature adds. ---
STATE_DISABLED = "disabled"
STATE_DRIVE_ABSENT = "drive-absent"
STATE_PAUSED = "paused"
STATE_MISCONFIGURED = "misconfigured"
STATE_NO_FFMPEG = "no-ffmpeg"
STATE_NO_MODEL = "no-model"
STATE_TIER_UNFIT = "tier-unfit"
STATE_NOTHING_TO_DO = "nothing-to-do"
STATE_USER_ACTIVE = "user-active"
STATE_RESOLVE_OPEN = "resolve-open"
STATE_RUNNING = "running"

RUN_MODE_IDLE = "idle"
RUN_MODE_FOREGROUND = "foreground"

# -- item stages, mirroring ingest_batches.ITEM_STATES exactly. A stage this
# side invents is a 400 from the server's transition check.
ITEM_PENDING = "pending"
ITEM_PROXYING = "proxying"
ITEM_FRAMING = "framing"
ITEM_DESCRIBING = "describing"
ITEM_INDEXED = "indexed"
ITEM_UPLOADING = "uploading"
ITEM_LIVE = "live"
ITEM_FAILED = "failed"
ITEM_DUPLICATE = "duplicate"
ITEM_CANCELLED = "cancelled"
ITEM_SKIPPED = "skipped"
ITEM_FINISHED = frozenset({ITEM_LIVE, ITEM_DUPLICATE, ITEM_CANCELLED, ITEM_SKIPPED})

# Staging item states, which are NOT the server's: they describe a file on its
# way INTO staging, before any batch exists.
STAGED_WAITING = "waiting"
STAGED_READY = "ready"
STAGED_FAILED = "failed"

MAX_PREPARE_ITEMS = ingest_kinds.BROLL_KIND.max_prepare_items


class LeaseLost(Exception):
    """The server answered 410: this batch is no longer ours to index.

    Its own exception because every caller does the same thing with it and
    nothing else -- stop. Copied from ytdl_executor for that reason, not
    imported: the two features' fleet clients share a shape, not a lifetime.
    """


# ---------------------------------------------------------------------------
# http
# ---------------------------------------------------------------------------

def default_request(method: str, url: str, body: Optional[dict],
                    headers: dict, timeout: float) -> tuple[int, Any]:
    """One fleet API call -> (status_code, parsed_json_or_None).

    An HTTP error status is an ANSWER here, not an exception: 409 and 410 are
    ordinary outcomes this orchestrator branches on. Transport failures still
    raise -- those are not answers, and the claim path treats them as "not
    today". No redirects, for reporter.default_http_post's reason: `headers`
    carries the fleet token and urlopen follows 3xx while stripping only
    Authorization.
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with upgrade_mod.build_no_redirect_opener().open(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except Exception:
            raw = b""
        status = exc.code
    try:
        return status, (json.loads(raw.decode("utf-8")) if raw else None)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return status, None


RequestFn = Callable[[str, str, Optional[dict], dict, float], tuple[int, Any]]


def _detail_of(parsed: Any) -> str:
    """FastAPI's error body -> one readable line. Never raises."""
    try:
        detail = parsed.get("detail") if isinstance(parsed, dict) else None
        if isinstance(detail, dict):
            return str(detail.get("detail") or detail)
        return str(detail or "")
    except Exception:
        return ""


class IngestDeps:
    """Everything the orchestrator needs from the running companion.

    ytdl_executor.Deps' shape and its reasoning: `editor_fn` is
    app.editor_identity rather than cfg["editor_name"], because a lease needs
    the VERIFIED holder; `identity_token_fn` is the dashboard-signed token the
    fleet routes check (H5) -- the shared report token proves "a fleet
    machine", this proves whose; `machine_name` is the SAME string the reporter
    sends, because the server compares it against the batch's leaseholder on
    every call after the claim (docs/API.md §6a).

    Absent seams degrade to "no capability", never to a guess.
    """

    def __init__(self, cfg: dict[str, Any],
                 editor_fn: Optional[Callable[[], Optional[str]]] = None,
                 identity_token_fn: Optional[Callable[[], Optional[str]]] = None,
                 request_fn: Optional[RequestFn] = None,
                 sidecar: Any = None,
                 uploader: Any = None,
                 machine_name: str = "",
                 ingestor: Any = None,
                 kind: Any = None) -> None:
        self.cfg = cfg or {}
        # Which ingest this dependency bundle is for. b-roll by default, so
        # every existing caller (app.py, the loopback, the tests) is unchanged;
        # `broll_server` reads it to answer the right capability route.
        self.kind = kind or ingest_kinds.BROLL_KIND
        self.log = _KindLog(log, self.kind.name)
        self._editor_fn = editor_fn
        self._identity_token_fn = identity_token_fn
        self.request = request_fn or default_request
        self.sidecar = sidecar or sidecar_mod
        self.uploader = uploader
        self._machine_name = machine_name
        # Set by the app once the orchestrator exists; broll_server reads it
        # off here exactly as it reads ytdl's manager off ytdl_deps.
        self.ingestor = ingestor

    @property
    def dashboard_url(self) -> str:
        return str(self.cfg.get("dashboard_url", "") or "").strip().rstrip("/")

    @property
    def token(self) -> str:
        """The shared fleet token, read from cfg PER CALL -- IdentityManager
        republishes a rotated one into this same dict at sign-in."""
        return str(self.cfg.get("dashboard_token", "") or "").strip()

    @property
    def machine(self) -> str:
        if self._machine_name:
            return self._machine_name
        import platform
        return platform.node()

    def editor(self) -> str:
        if self._editor_fn is not None:
            try:
                return str(self._editor_fn() or "").strip()
            except Exception:
                self.log.debug("editor_fn failed", exc_info=True)
                return ""
        return str(self.cfg.get("editor_name", "") or "").strip()

    def identity_token(self) -> str:
        if self._identity_token_fn is not None:
            try:
                return str(self._identity_token_fn() or "").strip()
            except Exception:
                self.log.debug("identity_token_fn failed", exc_info=True)
                return ""
        return ""


class FleetClient:
    """routes_fleet (broll/web), from the other end. Token-authed, browser-free.

    Every call after the claim also sends **X-CCSync-Machine** -- the same
    string the claim body carried. It is what proves the caller is still THIS
    editor's leaseholding machine rather than another of their companions
    waking up with a stale state file (docs/API.md §6a); a server that does not
    read it behaves exactly as before.
    """

    def __init__(self, deps: IngestDeps, timeout: float = HTTP_TIMEOUT_SECONDS,
                 prefix: str = "") -> None:
        self.deps = deps
        self.timeout = timeout
        # The kind's prefix, defaulting to the deps' own kind and then to
        # b-roll's: a client built by an older caller reaches exactly the
        # routes it always did.
        self.prefix = prefix or getattr(
            getattr(deps, "kind", None), "api_prefix", "") or API_PREFIX
        self.log = getattr(deps, "log", None) or _KindLog(log, ingest_kinds.BROLL)

    def _url(self, suffix: str) -> str:
        return f"{self.deps.dashboard_url}{self.prefix}{suffix}"

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "X-CCSync-Token": self.deps.token,
            "X-CCSync-Identity": self.deps.identity_token(),
            "X-CCSync-Machine": self.deps.machine,
        }

    def _call(self, method: str, suffix: str,
              body: Optional[dict] = None) -> tuple[int, Any]:
        status, parsed = self.deps.request(
            method, self._url(suffix), body, self._headers(), self.timeout)
        if status == 410:
            raise LeaseLost(_detail_of(parsed) or "this batch is no longer yours")
        return status, parsed

    # -- the calls ---------------------------------------------------------
    def claim(self, batch_uid: str, tier: str, capabilities: dict) -> tuple[int, Any]:
        """Take the batch and receive the whole work order. NOT via _call: a
        403 ("another editor's batch") and a 409 ("another of your machines has
        it") are answers the run route reports differently, and a 410 here is
        not a lost lease but a batch that was over before we started."""
        return self.deps.request(
            "POST", self._url(f"/batches/{batch_uid}/claim"),
            {"machine": self.deps.machine,
             "companion_version": config_mod.VERSION,
             "tier": tier, "capabilities": capabilities},
            self._headers(), self.timeout)

    def heartbeat(self, batch_uid: str) -> dict:
        status, parsed = self._call("POST", f"/batches/{batch_uid}/heartbeat", {})
        return parsed if isinstance(parsed, dict) else {}

    def item_status(self, batch_uid: str, item_uid: str, state: str, **fields) -> dict:
        body = {"state": state}
        body.update({k: v for k, v in fields.items() if v is not None})
        status, parsed = self._call(
            "POST", f"/batches/{batch_uid}/items/{item_uid}/status", body)
        if status != 200:
            self.log.warning("the server refused item %s -> %s (HTTP %s: %s)",
                        item_uid, state, status, _detail_of(parsed) or "no detail")
        return parsed if isinstance(parsed, dict) else {}

    def item_result(self, batch_uid: str, item_uid: str, body: dict) -> tuple[int, Any]:
        return self._call("POST", f"/batches/{batch_uid}/items/{item_uid}/result", body)

    def item_uploaded(self, batch_uid: str, item_uid: str, files: list,
                      original_uploaded: bool) -> tuple[int, Any]:
        return self._call(
            "POST", f"/batches/{batch_uid}/items/{item_uid}/uploaded",
            {"files": files, "original_uploaded": bool(original_uploaded)})

    def item_uploaded_size(self, batch_uid: str, item_uid: str,
                           size: Optional[int]) -> tuple[int, Any]:
        """The MUSIC kind's `uploaded` body (docs/API.md §6b): one size and no
        paths at all.

        A music item owns exactly one file and the SERVER allocated its name at
        `result`, so there is nothing about where to look coming off the wire
        -- which is why this is a different call rather than the same one with
        an empty list.
        """
        return self._call(
            "POST", f"/batches/{batch_uid}/items/{item_uid}/uploaded",
            {"size": int(size) if size is not None else None})

    def release(self, batch_uid: str, state: str, summary: Any = None) -> None:
        """Finish the batch. A LOST LEASE here is not an error: the cancel path
        expires the lease before this call is made, and the server accepts a
        `cancelled` release from a companion it would otherwise 410."""
        try:
            self._call("POST", f"/batches/{batch_uid}/release",
                       {"state": state, "summary": summary})
        except LeaseLost:
            self.log.info("the server had already taken batch %s back",
                     batch_uid)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("could not release batch %s (%s)", batch_uid, exc)


# ---------------------------------------------------------------------------
# shims: running the vendored describe_video unmodified
# ---------------------------------------------------------------------------

class _IndexerShim:
    """`cfg.indexer.*` as `local_vlm.describe_video` reads it."""

    def __init__(self, tier: str, cache_dir: str, server_path: str,
                 gpu_layers: int = 99, frames_per_call: int = 8,
                 merge_similar_segments: bool = True) -> None:
        self.model_tier = tier
        self.local_cache_dir = cache_dir
        self.llama_server_path = server_path
        self.gpu_layers = gpu_layers
        self.frames_per_call = frames_per_call
        self.merge_similar_segments = merge_similar_segments


class _EmbeddingShim:
    def __init__(self, cache_dir: str = "") -> None:
        self.cache_dir = cache_dir


class ConfigShim:
    """The indexer's config object, reduced to the seven attributes the
    vendored backend actually reads.

    A shim rather than a vendored copy of the indexer's Config: that class
    parses a YAML file describing a base rig's whole pipeline (DB path, API
    keys, share table), none of which exists on an editor's machine, and
    dragging it in would make the companion carry pyyaml for seven fields.
    """

    def __init__(self, data_root: str, tier: str, cache_dir: str,
                 server_path: str = "", gpu_layers: int = 99,
                 frames_per_call: int = 8) -> None:
        self.data_root = data_root
        self.indexer = _IndexerShim(tier, cache_dir, server_path,
                                    gpu_layers=gpu_layers,
                                    frames_per_call=frames_per_call)
        self.embedding = _EmbeddingShim()


class StorageShim:
    """The indexer's storage object, reduced to the two methods the vendored
    backend calls -- and NEITHER of them touches a database here.

    `write_index_result` captures the result in memory; the orchestrator then
    POSTs it to the fleet route, which is the only writer of the b-roll index
    in this design. The taxonomy comes from the claim manifest, so the category
    assignment an editor's machine makes is against the same list the server
    holds rather than one it invented.
    """

    def __init__(self, taxonomy: list) -> None:
        self._taxonomy = list(taxonomy or [])
        self.result: dict[str, Any] = {}

    def get_categories(self) -> list:
        return list(self._taxonomy)

    def write_index_result(self, video_id: Any, *, themes=None, quality_flags=None,
                           category_hint=None, segments=None, model=None) -> None:
        self.result = {
            "video_id": video_id,
            "themes": list(themes or []),
            "quality_flags": list(quality_flags or []),
            "category_hint": category_hint,
            "segments": list(segments or []),
            "model": model,
        }


# ---------------------------------------------------------------------------
# the orchestrator
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class BrollIngestor:
    """One machine's b-roll ingest: staging, the gate, the crunch, the upload.

    start()/stop()/join() plus zero-I/O readers, exactly like ProxyGenerator.
    Everything that touches the world is an injected seam so the state machine
    can be tested with no ffmpeg, no GPU and no dashboard anywhere.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        state_dir: Any,
        *,
        deps: Optional[IngestDeps] = None,
        root_present_fn: Optional[Callable[[], bool]] = None,
        paused_fn: Optional[Callable[[], bool]] = None,
        blocked_fn: Optional[Callable[[], bool]] = None,
        idle_probe: Any = None,
        resolve_running_fn: Optional[Callable[[], bool]] = None,
        notify: Optional[Callable[..., None]] = None,
        show_window: Optional[Callable[[], None]] = None,
        sidecar: Any = None,
        media: Any = None,
        uploader: Any = None,
        describe_fn: Optional[Callable[..., dict]] = None,
        available_fn: Optional[Callable[[str], tuple]] = None,
        encoders_fn: Optional[Callable[[str], Any]] = None,
        probe_fn: Optional[Callable[[str, Any], dict]] = None,
        run_media_fn: Optional[Callable[..., tuple]] = None,
        hash_fn: Optional[Callable[[Any], str]] = None,
        clock: Callable[[], float] = time.monotonic,
        kind: Any = None,
    ) -> None:
        self.cfg = cfg or {}
        # WHICH ingest this is (docs/MUSIC_INGEST_PLAN.md §2). b-roll by
        # default and in every existing call site, so this class behaves
        # exactly as it did; `MusicIngestor` passes the music kind and
        # overrides the per-item pipeline, which is the only part that is
        # genuinely a different job.
        self.kind = kind or ingest_kinds.BROLL_KIND
        # What "nothing left to do with this item" means. b-roll's four, plus
        # whatever the kind adds: music has `queued_for_base_rig`, the fallback
        # for a companion that could not embed (MUSIC_INGEST_PLAN.md 1), and an
        # item in it is finished HERE while the work goes on elsewhere.
        self.item_finished = frozenset(
            getattr(self.kind, "finished_states", None) or ITEM_FINISHED)
        self.log = _KindLog(log, self.kind.name)
        self.state_path = Path(state_dir) / self.kind.state_filename
        self.deps = deps if deps is not None else IngestDeps(self.cfg, kind=self.kind)
        self.deps.ingestor = self

        self._root_present_fn = root_present_fn
        self._paused_fn = paused_fn
        self._blocked_fn = blocked_fn
        self._idle_probe = idle_probe
        self._resolve_running_fn = resolve_running_fn
        self._notify = notify
        # "Show me what it is doing", called ONCE when a batch first starts
        # crunching or downloading. An injected seam rather than a direct
        # popup call: a window is the app's business, not the orchestrator's,
        # and an object that could open one on a background thread is an
        # object a test can leave a real Tk window behind with (seen live
        # 2026-08-18 -- a "MAKING PROXIES" window outliving the suite that
        # opened it). Absent = no window, which is what every test gets.
        self._show_window = show_window
        self._window_shown_for = ""
        self.sidecar = sidecar if sidecar is not None else self.deps.sidecar
        self.media = media if media is not None else media_mod
        self._describe_fn = describe_fn
        self._available_fn = available_fn
        self._encoders_fn = encoders_fn
        self._probe_fn = probe_fn
        # Resolved per call, not bound here: `media` is a module (or a double)
        # and binding its function at construction would pin whichever
        # implementation existed then -- which is also how a test that swaps
        # one in mid-run silently measures the old one.
        self._run_media_fn = run_media_fn
        self._hash_fn = hash_fn or self.media.hash_partial
        self._clock = clock

        # -- config. coerce_numeric everywhere, never float(): this object is
        # constructed inside CompanionApp.__init__, where a hand-edited
        # `broll_ingest_idle_seconds = "5m"` would take the windowed exe down
        # with no tray and no log line (proxy_gen's note, same trap).
        self.enabled = bool(self.cfg.get(self.kind.cfg_key("enabled"), True))
        self.ffmpeg_path = str(self.cfg.get("ffmpeg_path", "ffmpeg")
                               or "ffmpeg").strip() or "ffmpeg"
        self.idle_seconds = config_mod.coerce_numeric(
            self.cfg, self.kind.cfg_key("idle_seconds"),
            config_mod.coerce_numeric(self.cfg, "proxy_gen_idle_seconds", 300))
        self.skip_while_resolve = bool(
            self.cfg.get(self.kind.cfg_key("skip_while_resolve"), True))
        self.free_space_floor_gb = config_mod.coerce_numeric(
            self.cfg, self.kind.cfg_key("free_space_floor_gb"), 20)
        self.max_concurrent_ffmpeg = int(config_mod.coerce_numeric(
            self.cfg, self.kind.cfg_key("max_concurrent_ffmpeg"), 2))

        # -- state, ALL of it guarded by _lock: status() is called from the
        # tray's refresh thread and the reporter's tick while this thread
        # rewrites it.
        self._lock = threading.RLock()
        self._save_lock = threading.Lock()
        self._state = STATE_NOTHING_TO_DO
        self._batch: Optional[dict[str, Any]] = None
        self._staging: dict[str, dict[str, Any]] = {}
        self._warning = ""
        self._model_note = ""
        self._forced = False
        self._paused = False
        self._upload_paused = False
        self._current: dict[str, Any] = {}
        self._eta = popup.EmaEta()
        self._uploader = uploader

        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._child: Optional[Any] = None

        # Resume: a companion killed mid-batch must come back to the same
        # batch at the same checkpoint. Never fatal -- a state file we cannot
        # read is a batch the server's lease expiry hands back anyway.
        try:
            self._resume()
        except Exception:
            self.log.exception("could not resume the saved batch")

    # -- staging paths -----------------------------------------------------
    def staging_root(self) -> Optional[Path]:
        return self.kind.staging_root(self.cfg)

    def staging_dir(self, staging_id: str) -> Optional[Path]:
        root = self.staging_root()
        if root is None or not staging_id:
            return None
        candidate = root / staging_id
        # The id came off the wire. A traversal here would let a page name any
        # directory on the machine as "staging" and then read a thumbnail out
        # of it (loopback_guard.is_within is realpath-based on purpose).
        if not _safe_id(staging_id):
            return None
        return candidate

    def archive_root(self) -> Optional[Path]:
        mount = broll_server.default_broll_mount(self.cfg)
        return Path(mount) if mount else None

    # -- persistence -------------------------------------------------------
    def _save(self) -> None:
        """Write the state file atomically. Called at EVERY transition.

        Never raises: a machine that cannot write its state file still
        finishes the batch it is on -- it just cannot resume one.
        """
        with self._lock:
            snapshot = {
                "version": 1,
                "batch": self._batch,
                "staging": self._staging,
                "paused": self._paused,
                "forced": self._forced,
                "upload_paused": self._upload_paused,
                "warning": self._warning,
                "updated_at": _iso_now(),
            }
        # ONE WRITER AT A TIME, and a per-thread temp name. Three threads reach
        # this -- the tick, the prepare worker and whatever answered a loopback
        # POST -- and on Windows a second thread's os.replace over a .tmp the
        # first still has open is a PermissionError, i.e. a state file that
        # silently stops being written at exactly the moment there is most to
        # record.
        tmp = self.state_path.with_name(
            f"{self.state_path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with self._save_lock:
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
                os.replace(str(tmp), str(self.state_path))
        except Exception:
            self.log.warning("could not write %s", self.state_path,
                        exc_info=True)
            _unlink(tmp)

    def _resume(self) -> None:
        """Reload the saved batch, re-stat what is staged, re-claim on the
        next tick. Items whose staged file has gone are failed rather than
        retried for ever: an editor who deleted the card is not coming back."""
        if not self.state_path.is_file():
            return
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            self.log.warning("%s is unreadable -- starting clean",
                        self.state_path)
            return
        if not isinstance(saved, dict):
            return
        batch = saved.get("batch")
        self._staging = saved.get("staging") if isinstance(saved.get("staging"), dict) else {}
        self._paused = bool(saved.get("paused"))
        self._forced = bool(saved.get("forced"))
        self._upload_paused = bool(saved.get("upload_paused"))
        self._warning = str(saved.get("warning") or "")
        if not isinstance(batch, dict) or not batch.get("uid"):
            return
        for item in batch.get("items") or []:
            local = item.get("local_path")
            if item.get("stage") in self.item_finished:
                continue
            if local and not os.path.isfile(local):
                item["stage"] = ITEM_FAILED
                item["error"] = ("the source file is no longer on this machine "
                                 "(the drive was unplugged, or it was moved)")
        # `claimed`, not whatever it was: the lease is certainly stale after a
        # restart, and the first tick re-issues the (idempotent) claim.
        batch["needs_claim"] = True
        self._batch = batch
        self.log.info("resuming batch %s (%d clip(s), %d already live)",
                 batch.get("uid"), len(batch.get("items") or []),
                 sum(1 for i in batch.get("items") or [] if i.get("stage") == ITEM_LIVE))

    # -- seams -------------------------------------------------------------
    def _root_present(self) -> bool:
        try:
            if self._root_present_fn is not None:
                return bool(self._root_present_fn())
            root = str(self.cfg.get("local_root", "") or "")
            return bool(root) and os.path.isdir(root)
        except Exception:
            # "Can't tell" is present, matching proxy_gen: an unanswerable
            # probe must not switch a feature off.
            self.log.debug("could not check local_root", exc_info=True)
            return True

    def _is_paused(self) -> bool:
        if self._paused:
            return True
        try:
            return bool(self._paused_fn()) if self._paused_fn is not None else False
        except Exception:
            self.log.debug("paused_fn failed", exc_info=True)
            return False

    def _is_blocked(self) -> bool:
        try:
            return bool(self._blocked_fn()) if self._blocked_fn is not None else False
        except Exception:
            self.log.debug("blocked_fn failed", exc_info=True)
            return False

    def _resolve_running(self) -> bool:
        """Fails CLOSED (True), like proxy_gen's: this gate exists for the
        machine that leaves unattended renders going, and a check that cannot
        answer must not be read as "the GPU is free"."""
        if self._resolve_running_fn is None:
            return False
        try:
            return bool(self._resolve_running_fn())
        except Exception:
            self.log.debug("resolve_running_fn failed", exc_info=True)
            return True

    def _user_is_away(self) -> bool:
        """None (cannot tell) is NOT away. See idle.py's contract."""
        if self._idle_probe is None:
            return False
        try:
            value = self._idle_probe.seconds_idle()
        except Exception:
            self.log.debug("idle probe failed", exc_info=True)
            return False
        return value is not None and float(value) >= self.idle_seconds

    def _check_ffmpeg(self) -> bool:
        try:
            probe = self._available_fn
            if probe is None:
                from . import ffmpeg_tools
                probe = ffmpeg_tools.ffmpeg_available
            ok, _message = probe(self.ffmpeg_path)
            return bool(ok)
        except Exception:
            self.log.debug("ffmpeg probe failed", exc_info=True)
            return False

    def _nvenc(self) -> bool:
        try:
            probe = self._encoders_fn
            if probe is None:
                from . import ffmpeg_tools
                probe = ffmpeg_tools.detect_encoders
            return "h264_nvenc" in probe(self.ffmpeg_path)
        except Exception:
            self.log.debug("encoder detection failed", exc_info=True)
            return False

    def _probe(self, path: Any) -> dict:
        if self._probe_fn is not None:
            return self._probe_fn(self.ffmpeg_path, path)
        return self.media.probe(self.ffmpeg_path, path)

    # -- the gate ----------------------------------------------------------
    def _tier(self) -> str:
        with self._lock:
            batch = self._batch or {}
            return str((batch.get("settings") or {}).get("tier") or "good")

    def _run_mode(self) -> str:
        with self._lock:
            batch = self._batch or {}
            mode = str((batch.get("settings") or {}).get("run_mode") or RUN_MODE_IDLE)
            forced = self._forced
        if forced:
            return RUN_MODE_FOREGROUND
        return mode if mode in (RUN_MODE_IDLE, RUN_MODE_FOREGROUND) else RUN_MODE_IDLE

    def _has_work(self) -> bool:
        with self._lock:
            batch = self._batch
        if not batch:
            return False
        return any(item.get("stage") not in self.item_finished
                   and not (item.get("stage") == ITEM_FAILED
                            and int(item.get("attempts") or 0) >= MAX_ITEM_ATTEMPTS)
                   for item in batch.get("items") or [])

    def _gate(self) -> str:
        """Why this machine is or is not crunching right now, in priority
        order (plan §5). proxy_gen's order, with three states of its own:

            disabled -> drive absent -> paused -> misconfigured -> no ffmpeg
            -> no model -> the tier does not fit -> nothing to do
            -> [idle mode only: user active -> Resolve open] -> running

        The one deviation from the plan's literal ordering is inside `no
        model`: a tier this GPU cannot run is reported as `tier-unfit` even
        when the weights are missing, because "download 3.9 GB and then refuse
        to use it" is not a thing to do to an editor's connection.
        """
        if not self.enabled:
            return STATE_DISABLED
        if not self._root_present():
            return STATE_DRIVE_ABSENT
        if self._is_paused():
            return STATE_PAUSED
        if self._is_blocked():
            return STATE_MISCONFIGURED
        if not self._check_ffmpeg():
            return STATE_NO_FFMPEG
        tier = self._tier()
        fits, _why = self._fits(tier)
        if not self._model_ready(tier):
            return STATE_NO_MODEL if fits else STATE_TIER_UNFIT
        if not fits:
            return STATE_TIER_UNFIT
        if not self._has_work():
            return STATE_NOTHING_TO_DO
        if self._run_mode() == RUN_MODE_IDLE:
            if not self._user_is_away():
                return STATE_USER_ACTIVE
            if self.skip_while_resolve and self._resolve_running():
                return STATE_RESOLVE_OPEN
        return STATE_RUNNING

    def _fits(self, tier: str) -> tuple[bool, str]:
        try:
            return self.sidecar.fits(tier)
        except Exception:
            self.log.debug("the tier fit check failed", exc_info=True)
            return False, "this machine could not be checked for the indexing model"

    def _model_ready(self, tier: str) -> bool:
        try:
            snapshot = self.sidecar.status()
            return bool((snapshot.get("model_ready") or {}).get(tier)
                        and snapshot.get("runtime_ready"))
        except Exception:
            self.log.debug("the sidecar snapshot failed", exc_info=True)
            return False

    def _publish_state(self, state: str) -> None:
        with self._lock:
            previous = self._state
            self._state = state
        if state == STATE_TIER_UNFIT and previous != STATE_TIER_UNFIT:
            _fits, why = self._fits(self._tier())
            self._warn(why)

    def _warn(self, message: str) -> None:
        """Publish a refusal that the tray balloons ONCE and then shows as a
        menu line until it changes (plan §6, owner review (c))."""
        if not message:
            return
        with self._lock:
            same = self._warning == message
            self._warning = message
        if same:
            return
        self.log.warning("%s", message)
        if self._notify is not None:
            try:
                self._notify(message, f"ccsync-companion: {self.kind.label}")
            except Exception:
                self.log.debug("the tray notification failed", exc_info=True)

    def _clear_warning(self) -> None:
        with self._lock:
            self._warning = ""

    # -- public, zero-I/O readers -----------------------------------------
    def status(self) -> dict[str, Any]:
        """What the tray, the reporter and the progress window all read.

        Cached, lock-guarded, no filesystem: it is called on the tray's
        refresh thread, which on the win32 backend can stall the message loop.
        """
        with self._lock:
            batch = dict(self._batch or {})
            items = list(batch.get("items") or [])
            current = dict(self._current)
            state = self._state
            warning = self._warning
            model_note = self._model_note
            paused = self._paused
            upload_paused = self._upload_paused
            eta = self._eta
        done = sum(1 for i in items if i.get("stage") == ITEM_LIVE)
        failed = sum(1 for i in items if i.get("stage") == ITEM_FAILED)
        total = len(items)
        settings = batch.get("settings") or {}
        uploads = self._upload_snapshot()
        download = self._download_snapshot()
        return {
            "active": bool(batch.get("uid")) and state not in (
                STATE_DISABLED, STATE_NOTHING_TO_DO),
            "working": state == STATE_RUNNING,
            "batch_uid": str(batch.get("uid") or ""),
            "state": str(batch.get("state") or ""),
            "gate": state,
            "done": done,
            "failed": failed,
            "total": total,
            "clip": str(current.get("name") or ""),
            "stage": str(current.get("stage") or ""),
            "percent": int(current.get("percent") or 0),
            "tier": str(settings.get("tier") or ""),
            "run_mode": self._run_mode() if batch.get("uid") else "",
            "uploading": bool(uploads.get("queued") or uploads.get("active")),
            "upload_left": int(uploads.get("queued") or 0)
            + (1 if uploads.get("active") else 0),
            "upload_paused": bool(upload_paused),
            "model_download_percent": download.get("percent"),
            "model_download_name": download.get("name") or "",
            "model_download_rate": download.get("rate_bytes_per_s"),
            "model_download_eta": download.get("eta_seconds"),
            "model_note": model_note,
            "warning": warning,
            "paused": bool(paused),
            "eta_seconds": eta.eta_seconds(max(total - done - failed, 0)),
            "at": _iso_now(),
        }

    def report(self) -> dict[str, Any]:
        """The reporter's `broll_ingest` section -- the dashboard's
        BrollIngestIn fields and NOTHING else.

        A strict subset on purpose: the section rides every tick of every
        machine, pydantic drops what it does not declare, and a getter that
        sent the tray's whole view would be paying for fields no column exists
        for. Empty when there is nothing to say, which is how the reporter
        spells "this machine is not indexing" (an absent section clears the
        grid's chip).
        """
        snap = self.status()
        if not snap["batch_uid"] and not snap["warning"]:
            return {}
        # NOTE the absence of a `kind` field: this is b-roll's section, and the
        # dashboard's BrollIngestIn declares exactly these keys. The music
        # subclass adds its own (`music_ingest.MusicIngestor.report`) -- the
        # two sections ride the same report and land in different columns.
        return {
            "active": bool(snap["active"]),
            "batch_uid": snap["batch_uid"],
            "state": snap["state"],
            "gate": snap["gate"],
            "done": snap["done"],
            "failed": snap["failed"],
            "total": snap["total"],
            "clip": snap["clip"][:255],
            "percent": max(0, min(100, int(snap["percent"] or 0))),
            "tier": snap["tier"],
            "run_mode": snap["run_mode"],
            "uploading": bool(snap["uploading"]),
            "upload_paused": bool(snap["upload_paused"]),
            "model_download_percent": snap["model_download_percent"],
            "warning": snap["warning"][:255],
            "at": snap["at"],
        }

    def busy(self) -> dict[str, Any]:
        """What the capability route publishes: which batch this machine is
        holding, if any."""
        with self._lock:
            batch = self._batch or {}
            return {"batch_uid": batch.get("uid") or None, "state": self._state}

    def is_working(self) -> bool:
        """True while this machine is actually crunching or fetching a model.

        The proxy generator's `blocked_fn` is derived from this: indexing takes
        precedence (owner review (a), 2026-08-18).
        """
        with self._lock:
            state = self._state
        return state in (STATE_RUNNING, STATE_NO_MODEL) and bool(self.busy()["batch_uid"])

    def blocking_reason(self) -> Optional[str]:
        """The sentence the PROXY generator shows while it stands aside."""
        if not self.is_working():
            return None
        return self.kind.blocking_sentence()

    def block_reason(self) -> Optional[str]:
        """Shutdown-screen text while a batch is in flight, else None.

        Read by app._shutdown_block_reason and, through it, by the keep-awake
        guard: a machine must not idle-sleep in the middle of a two-hour batch
        that only runs BECAUSE the editor is away.
        """
        snap = self.status()
        if snap["gate"] not in (STATE_RUNNING, STATE_NO_MODEL):
            return None
        left = max(snap["total"] - snap["done"] - snap["failed"], 0)
        if snap["gate"] == STATE_NO_MODEL:
            return f"still downloading the {self.kind.label} indexing model"
        return (f"still indexing {self.kind.label} "
                f"({left} {self.kind.unit}(s) left)")

    def progress_model(self) -> popup.ProgressModel:
        """This batch as the shared work window draws it (popup.py).

        Order is the plan's: what is being FETCHED above what is being
        crunched, because until a 3.9 GB model lands nothing else can start and
        a still per-clip bar reads as a hang.
        """
        snap = self.status()
        actions = ["cancel"]
        if snap["paused"]:
            actions.append("resume")
        else:
            actions.append("pause")
        if snap["gate"] in (STATE_USER_ACTIVE, STATE_RESOLVE_OPEN):
            actions.append("start_now")
        note = snap["warning"] or _gate_note(snap["gate"])
        return popup.ProgressModel(
            title=self.kind.window_title,
            phase=snap["gate"],
            headline=_download_headline(
                snap["model_download_name"], snap["model_download_percent"],
                snap["model_download_rate"], snap["model_download_eta"]),
            headline_percent=snap["model_download_percent"],
            item_label=(f"{snap['clip']} - {snap['stage']}" if snap["clip"]
                        else ""),
            item_percent=snap["percent"] or None,
            done=snap["done"], total=snap["total"], failed=snap["failed"],
            eta_seconds=snap["eta_seconds"],
            note=note,
            unit=self.kind.unit,
            actions=tuple(actions),
            finished=bool(snap["total"]) and snap["done"] + snap["failed"] >= snap["total"],
        )

    # -- tray/loopback actions --------------------------------------------
    def request_run(self) -> None:
        """"Index the b-roll batch now (don't wait until I'm away)"."""
        with self._lock:
            self._forced = True
            self._paused = False
        self._cancel.clear()
        self._save()
        self._wake.set()
        self.log.info("a foreground run was requested from the tray")

    def pause(self) -> None:
        with self._lock:
            self._paused = True
            self._forced = False
        self._save()
        self._wake.set()

    def resume(self) -> None:
        with self._lock:
            self._paused = False
        self._save()
        self._wake.set()

    def pause_upload(self, paused: bool = True) -> None:
        with self._lock:
            self._upload_paused = bool(paused)
        uploader = self._uploader
        if uploader is not None:
            try:
                uploader.pause() if paused else uploader.resume()
            except Exception:
                self.log.debug("could not pause the upload queue",
                          exc_info=True)
        self._save()

    def cancel(self, reason: str = "cancelled on this machine") -> None:
        """Stop the batch and tell the server. Staged files stay (plan §6):
        an editor who cancels by accident has not lost their drop."""
        with self._lock:
            batch = dict(self._batch or {})
        self._cancel.set()
        self._kill_child()
        self._stop_uploads()
        self._stop_model_server()
        uid = batch.get("uid")
        if uid:
            self._client().release(uid, "cancelled", {"reason": reason})
            self.log.info("batch %s cancelled (%s)", uid, reason)
        with self._lock:
            self._batch = None
            self._current = {}
            self._forced = False
        self._publish_state(STATE_NOTHING_TO_DO)
        self._save()

    def control(self, action: str) -> tuple[int, dict]:
        """POST /broll/ingest/control. One verb per call, and every one of them
        is also a tray item -- the page and the menu drive the same object."""
        verbs = {
            "pause": self.pause,
            "resume": self.resume,
            "start_now": self.request_run,
            "cancel": self.cancel,
            "pause_upload": lambda: self.pause_upload(True),
            "resume_upload": lambda: self.pause_upload(False),
        }
        verb = verbs.get(str(action or "").strip())
        if verb is None:
            return 400, {"ok": False, "message": f"unknown action {action!r}"}
        verb()
        return 200, {"ok": True, "state": self.status()["gate"],
                     "batch": self.status()["batch_uid"]}

    def note_report_response(self, resp: Any) -> None:
        """`commands.<kind>_ingest.cancel` from the report reply.

        The heartbeat's 410 remains the authoritative stop; this only makes a
        cancel arrive within one report interval instead of one heartbeat.
        Best effort, and never raises into the reporter's loop.

        The block is looked up by the KIND's section name, so a music
        orchestrator cannot be stopped by a b-roll cancel and vice versa --
        one editor can be running one of each at the same time.
        """
        try:
            commands = (resp or {}).get("commands") if isinstance(resp, dict) else None
            block = ((commands or {}).get(self.kind.report_section)
                     if isinstance(commands, dict) else None)
            uids = (block or {}).get("cancel") if isinstance(block, dict) else None
            if not uids:
                return
            with self._lock:
                uid = (self._batch or {}).get("uid")
            if uid and uid in list(uids):
                self.log.info("the dashboard asked for batch %s to stop", uid)
                self.cancel("cancelled from the dashboard")
        except Exception:
            self.log.debug("could not read the report response",
                      exc_info=True)

    # -- staging (the loopback's prepare/upload/progress/thumb) ------------
    def prepare(self, body: dict) -> tuple[int, dict]:
        """Make a staging directory and a slot for every item.

        Refusals are per ITEM where they can be (a path outside the allowed
        roots, a file that is not a video) and for the whole request where they
        cannot (no tree, no space): a folder drop with one .txt in it should
        stage 399 clips, not fail.
        """
        raw_items = body.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            return 400, {"ok": False, "message": "no clips were offered"}
        if len(raw_items) > self.kind.max_prepare_items:
            return 413, {"ok": False, "message": (
                f"that is {len(raw_items)} {self.kind.unit}s; "
                f"{self.kind.max_prepare_items} is the most one batch can hold")}
        root = self.staging_root()
        if root is None:
            return 503, {"ok": False, "message": (
                "this machine has no synced tree, so there is nowhere to stage "
                f"the {self.kind.unit}s")}
        refusal = self._space_refusal(root)
        if refusal:
            return 507, {"ok": False, "message": refusal}

        staging_id = uuid.uuid4().hex[:16]
        directory = root / staging_id
        try:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "out").mkdir(exist_ok=True)
        except OSError as exc:
            self.log.warning("could not create %s (%s)", directory, exc)
            return 507, {"ok": False, "message": (
                "the companion could not create its staging folder -- "
                f"{exc.strerror or exc}")}

        answers = []
        items: dict[str, Any] = {}
        for index, raw in enumerate(raw_items):
            if not isinstance(raw, dict):
                continue
            local_id = _clean_local_id(raw.get("local_id"), index)
            name = str(raw.get("name") or "").strip() or f"clip{index}"
            source = "path" if str(raw.get("source") or "") == "path" else "upload"
            ext = os.path.splitext(name)[1].lower()
            entry = {
                "local_id": local_id, "name": name, "ord": index,
                "source": source, "rel_dir": _clean_rel_dir(raw.get("rel_dir")),
                "size": _int_or_none(raw.get("size")),
                "state": STAGED_WAITING, "hash": None, "probe": None, "error": "",
                "path": "", "thumb": "",
            }
            if ext not in self.kind.exts:
                entry.update(state=STAGED_FAILED,
                             error=f"{ext or 'that file'} is not "
                                   f"{self.kind.media_word}")
                answers.append({"local_id": local_id, "accepted": False,
                                "reason": entry["error"]})
                items[local_id] = entry
                continue
            if source == "path":
                path = str(raw.get("path") or "")
                problem = self._path_refusal(path)
                if problem:
                    entry.update(state=STAGED_FAILED, error=problem)
                    answers.append({"local_id": local_id, "accepted": False,
                                    "reason": problem})
                    items[local_id] = entry
                    continue
                entry["path"] = os.path.abspath(path)
                answers.append({"local_id": local_id, "accepted": True})
            else:
                entry["path"] = str(directory / f"{local_id}{ext}")
                answers.append({
                    "local_id": local_id, "accepted": True,
                    "upload_url": self.kind.upload_url(staging_id, local_id),
                })
            items[local_id] = entry

        with self._lock:
            self._staging[staging_id] = {"id": staging_id, "dir": str(directory),
                                         "items": items, "at": _iso_now()}
        self._save()
        self._start_prepare_worker(staging_id)
        self.log.info("staged %d %s(s) as %s", len(items), self.kind.unit,
                      staging_id)
        return 202, {"ok": True, "staging_id": staging_id, "items": answers}

    def upload_slot(self, staging_id: str, local_id: str) -> tuple[int, dict]:
        """Where PUT /broll/ingest/upload/... may write, or a refusal."""
        with self._lock:
            staging = self._staging.get(staging_id)
            entry = (staging or {}).get("items", {}).get(local_id)
        directory = self.staging_dir(staging_id)
        if staging is None or entry is None or directory is None:
            return 404, {"ok": False, "message": "no such upload slot -- prepare first"}
        if entry.get("source") != "upload":
            return 409, {"ok": False, "message": (
                "that clip is being indexed where it already is, not uploaded")}
        path = Path(str(entry.get("path") or ""))
        if path.is_file():
            # 409 = already staged, which the page reads as SUCCESS (the SPA
            # retries a dropped file after a reconnect and must not re-send
            # 40 GB it already sent).
            return 409, {"ok": False, "already": True,
                         "message": "that clip is already staged"}
        return 200, {"path": str(path), "staging_root": str(self.staging_root()),
                     "size": int(entry.get("size") or 0)}

    def note_upload(self, staging_id: str, local_id: str,
                    written: int) -> tuple[int, dict]:
        """The bytes landed: probe and hash them, so the page's pre-check can
        ask the server whether this clip is already in the archive."""
        with self._lock:
            entry = (self._staging.get(staging_id) or {}).get("items", {}).get(local_id)
        if entry is None:
            return 404, {"ok": False, "message": "no such upload slot"}
        entry["size"] = int(written)
        result = self._probe_and_hash(entry)
        self._save()
        return 200, {"ok": True, "size": int(written), "hash": entry.get("hash"),
                     "probe": entry.get("probe"), "state": entry.get("state"),
                     "error": entry.get("error") or "", **result}

    def progress(self, staging_id: Optional[str] = None) -> dict[str, Any]:
        """What the SPA polls every 1.5 s: the staging half and the batch half
        in one answer. Zero I/O -- everything here is already in memory."""
        with self._lock:
            staging = dict(self._staging.get(staging_id) or {}) if staging_id else {}
            items = list((staging.get("items") or {}).values())
        snap = self.status()
        return {
            "staging": {
                "id": staging_id or "",
                "items": [{"local_id": i.get("local_id"), "state": i.get("state"),
                           "name": i.get("name"), "size": i.get("size"),
                           "hash": i.get("hash"), "probe": i.get("probe"),
                           "rel_dir": i.get("rel_dir"),
                           "error": i.get("error") or ""} for i in items],
            },
            "batch": {
                "uid": snap["batch_uid"] or None,
                "state": snap["state"], "gate": snap["gate"],
                "forced": snap["run_mode"] == RUN_MODE_FOREGROUND,
                "paused": snap["paused"], "upload_paused": snap["upload_paused"],
                "done": snap["done"], "failed": snap["failed"], "total": snap["total"],
                "warning": snap["warning"],
                "eta_seconds": snap["eta_seconds"],
                "current": {"name": snap["clip"], "stage": snap["stage"],
                            "percent": snap["percent"]},
                "upload": self._upload_snapshot(),
                # rate_bytes_per_s/eta_seconds (2026-08-18): the SPA draws
                # "38 MB/s, about 1 min left" beside the percent, because a bar
                # that moves slowly with no number beside it reads as a hang.
                "model": {"tier": snap["tier"],
                          "ready": self._model_ready(snap["tier"] or self._tier()),
                          "percent": snap["model_download_percent"],
                          "rate_bytes_per_s": snap["model_download_rate"],
                          "eta_seconds": snap["model_download_eta"],
                          "note": snap["model_note"]},
            },
        }

    def thumb(self, staging_id: str, local_id: str) -> tuple[int, Any]:
        """A staging thumbnail, and ONLY from inside staging.

        The bytes are read here rather than the path handed out, because a
        route that returns a path is a route that can be talked into returning
        somebody's tax return.
        """
        directory = self.staging_dir(staging_id)
        with self._lock:
            entry = (self._staging.get(staging_id) or {}).get("items", {}).get(local_id)
        if directory is None or entry is None:
            return 404, {"ok": False, "message": "no such clip"}
        thumb = Path(str(entry.get("thumb") or ""))
        if not entry.get("thumb"):
            return 404, {"ok": False, "message": "no preview for that clip yet"}
        from . import loopback_guard
        if not loopback_guard.is_within(thumb, directory):
            self.log.warning("refusing a thumb outside staging: %s", thumb)
            return 403, {"ok": False, "message": "refused"}
        try:
            return 200, thumb.read_bytes()
        except OSError:
            return 404, {"ok": False, "message": "no preview for that clip yet"}

    # -- run ---------------------------------------------------------------
    def run(self, batch_uid: str, staging_id: str,
            run_mode: str = "") -> tuple[int, dict]:
        """Claim `batch_uid` and start indexing it. POST /broll/ingest/run.

        The claim is what turns a browser's uid into a work order: video ids,
        archive folder and stem, taxonomy, lease. Nothing about what happens to
        the editor's footage is read out of the request.
        """
        if not _safe_uid(batch_uid):
            return 400, {"ok": False, "message": "that is not a batch id"}
        with self._lock:
            current = (self._batch or {}).get("uid")
        if current and current != batch_uid:
            return 409, {"ok": False, "message": (
                "this machine is already indexing another batch")}
        if not self.enabled:
            return 503, {"ok": False, "message": (
                f"{self.kind.label} indexing is switched off on this machine")}
        if not self.deps.dashboard_url or not self.deps.token:
            return 503, {"ok": False, "message": (
                "this machine has no dashboard URL or token configured")}
        if not self.deps.identity_token():
            return 503, {"ok": False, "message": (
                "nobody is signed in on this machine")}
        staging = None
        if staging_id:
            with self._lock:
                staging = self._staging.get(staging_id)
            if staging is None:
                return 409, {"ok": False, "message": (
                    f"those {self.kind.unit}s are no longer staged on this "
                    "machine - drop them again")}

        capabilities = broll_server.build_ingest_capabilities(
            self.cfg, self, self.deps, kind=self.kind)
        try:
            status, parsed = self._client().claim(batch_uid, self._tier(), capabilities)
        except Exception as exc:  # noqa: BLE001 - an unreachable dashboard is an answer
            self.log.warning("could not claim batch %s (%s)", batch_uid, exc)
            return 503, {"ok": False, "message": (
                "this machine could not reach the dashboard to claim the batch")}
        if status != 200 or not isinstance(parsed, dict):
            message = _detail_of(parsed) or "the dashboard would not hand over this batch"
            self.log.warning("claim of %s refused (HTTP %s: %s)",
                        batch_uid, status, message)
            return (status if status in (403, 409, 410) else 503), {
                "ok": False, "message": message}

        settings = dict(parsed.get("settings") or {})
        if run_mode in (RUN_MODE_IDLE, RUN_MODE_FOREGROUND):
            # The page's choice wins over the stored one for THIS machine: the
            # editor made it in the same form, seconds ago, and the stored copy
            # is what another machine would resume under.
            settings["run_mode"] = run_mode
        tier = str(settings.get("tier") or "good") if self.kind.uses_tier else ""

        fits, why = self._fits(tier)
        if not fits:
            # Never claimed for long: the lease expires and another of this
            # editor's machines can take the batch. Releasing it `failed` here
            # would make them re-create it instead (plan §6).
            self._warn(why)
            self.log.warning("refusing batch %s -- %s", batch_uid, why)
            return 503, {"ok": False, "message": why, "reason": "tier_unfit"}
        self._clear_warning()

        batch = {
            "uid": batch_uid,
            "staging_id": staging_id,
            "staging_dir": str(self.staging_dir(staging_id) or ""),
            "settings": settings,
            "state": "claimed",
            "share": (parsed.get("batch") or {}).get("share") or "",
            "archive_remote_rel": self._remote_rel(parsed),
            "taxonomy": parsed.get("taxonomy") or [],
            "heartbeat_seconds": parsed.get("heartbeat_seconds") or HEARTBEAT_SECONDS,
            "items": [self._item_from_manifest(entry, staging)
                      for entry in parsed.get("items") or []],
            "claimed_at": _iso_now(),
        }
        with self._lock:
            self._batch = batch
            self._forced = settings.get("run_mode") == RUN_MODE_FOREGROUND
            self._paused = False
            self._upload_paused = bool(
                (parsed.get("batch") or {}).get("upload_paused"))
            self._eta = popup.EmaEta()
        self._cancel.clear()
        self._save()
        self._start_heartbeat()
        self._wake.set()

        state = "claimed" if self._model_ready(tier) else "waiting-for-model"
        self.log.info("claimed batch %s - %d %s(s), tier %s, %s",
                      batch_uid, len(batch["items"]), self.kind.unit,
                      tier or "n/a", settings.get("run_mode"))
        return 202, {"ok": True, "batch_uid": batch_uid, "state": state,
                     "run_mode": settings.get("run_mode"), "tier": tier}

    def _remote_rel(self, parsed: dict) -> str:
        """Where this kind's uploads hang off the remote root.

        The SERVER says (`archive_remote_rel` for b-roll, `library_remote_rel`
        for music); the constant is only the fallback for a dashboard too old
        to have said, and it is never a local path -- only this machine knows
        what the remote root is mounted at (the /music/send principle, applied
        to a work order).
        """
        return (parsed.get("archive_remote_rel")
                or broll_upload.ARCHIVE_REMOTE_REL)

    def _item_from_manifest(self, entry: dict, staging: Optional[dict]) -> dict:
        """One manifest row plus whatever this machine knows about the file."""
        local_path = ""
        thumb = ""
        items = (staging or {}).get("items") or {}
        for candidate in items.values():
            if (candidate.get("name") == entry.get("orig_name")
                    and candidate.get("rel_dir", "") == (entry.get("rel_dir") or "")):
                local_path = str(candidate.get("path") or "")
                thumb = str(candidate.get("thumb") or "")
                break
        rel_path = entry.get("rel_path") or ""
        return {
            "uid": entry.get("uid"), "video_id": entry.get("video_id"),
            "ord": entry.get("ord"), "name": entry.get("orig_name") or "",
            "rel_dir": entry.get("rel_dir") or "",
            "source": entry.get("source") or "upload",
            "local_path": local_path, "thumb": thumb,
            "hash": entry.get("hash"), "probe": None,
            "archive_dir": entry.get("archive_dir") or "",
            "archive_stem": entry.get("archive_stem") or "",
            "rel_path": rel_path,
            "final_name": PurePosixPath(rel_path).name if rel_path else "",
            "duplicate_of": entry.get("duplicate_of"),
            "stage": (ITEM_DUPLICATE if entry.get("state") == ITEM_DUPLICATE
                      else entry.get("state") or ITEM_PENDING),
            "outputs": {}, "uploads": {}, "uploaded": [],
            "original_uploaded": False,
            "attempts": int(entry.get("attempts") or 0), "error": "",
            "seconds": None,
        }

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        if not self.enabled:
            self.log.info("disabled by config")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="ccsync-broll-ingest",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Told before the rest of teardown: setting this is what kills the
        ffmpeg (or llama-server) child. Never blocks."""
        self._stop_event.set()
        self._wake.set()
        self._kill_child()
        self._stop_uploads()
        self._stop_model_server()

    def join(self, timeout: float = 5.0) -> None:
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        try:
            thread.join(timeout=timeout)
            if thread.is_alive():
                self.log.warning("the worker did not stop within %.0fs",
                            timeout)
        except Exception:
            self.log.exception("failed to join the worker thread")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                # One bad tick must not end the thread: a batch that stops
                # silently is the failure this feature cannot afford.
                self.log.exception("tick failed")
            self._wake.wait(TICK_SECONDS)
            self._wake.clear()

    def tick(self) -> str:
        """One pass: gate, maybe fetch the model, maybe crunch, pump uploads."""
        state = self._gate()
        self._publish_state(state)

        if state == STATE_NO_MODEL and self._has_work():
            self._fetch_model()
            state = self._gate()
            self._publish_state(state)

        if state in (STATE_RUNNING, STATE_NO_MODEL):
            self._offer_window()
        if state == STATE_RUNNING:
            state = self._drain()
        if state != STATE_RUNNING:
            # The editor is back (or the batch is over): the VRAM goes back to
            # them AT ONCE, including when the drain is what noticed. That is
            # the whole promise of the idle gate -- llama-server holds 4-12 GB
            # and the timeline they just sat down in front of wants it (§5).
            self._stop_model_server()
        self._publish_state(state)
        self._pump_uploads()
        self._maybe_finish()
        return state

    def _offer_window(self) -> None:
        """Open the progress window once per batch, when it starts working.

        Once, not per tick: an editor who closed it means it, and a window
        that reappeared every fifteen seconds would be the thing they turn the
        feature off to escape.
        """
        with self._lock:
            uid = (self._batch or {}).get("uid") or ""
            if not uid or self._window_shown_for == uid or self._show_window is None:
                return
            self._window_shown_for = uid
            show = self._show_window
        try:
            show()
        except Exception:
            self.log.debug("could not open the progress window",
                      exc_info=True)

    # -- the model ---------------------------------------------------------
    def _fetch_model(self) -> None:
        """Download the runtime and this batch's tier, with progress.

        Blocking, on the tick thread, because there is nothing else for that
        thread to do until it lands -- and `stop_event` is passed down so a
        shutdown mid-download is a resumable partial rather than a wait.
        """
        tier = self._tier()
        # Say so BEFORE the bytes start: a multi-GB fetch with no visible
        # sign is read as "nothing happened" (owner, 2026-08-18: ten minutes
        # of a silent 3.3 GB download, reported as broken). One balloon at the
        # start, one when the model is in; the per-second numbers live in the
        # progress window the balloon points at, never in more balloons.
        fetching = not self._model_ready(tier)
        if fetching:
            self._say(self._download_started_text(tier))
        with self._lock:
            self._model_note = "downloading"
        ok, message = self.sidecar.ensure(tier, stop_event=self._stop_event)
        with self._lock:
            self._model_note = "" if ok else message
        if ok:
            self.log.info("%s", message)
            self._clear_warning()
            if fetching:
                self._say(f"The {self.kind.label} indexing model is ready. "
                          f"Indexing starts now.")
        else:
            self.log.warning("the model is not ready -- %s", message)

    def _download_started_text(self, tier: str) -> str:
        """The balloon for a model fetch: what, how big, where to watch."""
        size = ""
        try:
            n = int(self.sidecar.required_bytes(tier) if tier else self.sidecar.required_bytes())
            if n > 0:
                size = f" ({n / 1e9:.1f} GB)"
        except Exception:
            size = ""
        which = f"{tier.capitalize()} " if tier in ("good", "best") else ""
        return (f"Downloading the {which}{self.kind.label} indexing model{size}. "
                f"Right-click the tray icon to see progress.")

    def _say(self, message: str) -> None:
        """A tray balloon, best-effort: never a reason the tick fails."""
        if self._notify is None:
            return
        try:
            self._notify(message, f"ccsync-companion: {self.kind.label}")
        except Exception:
            self.log.debug("the tray notification failed", exc_info=True)

    def _download_snapshot(self) -> dict[str, Any]:
        try:
            downloading = self.sidecar.status().get("downloading") or {}
        except Exception:
            return {}
        # rate/eta are absent on an older sidecar (and while the first bytes
        # are still being measured): every reader treats them as optional.
        return {"percent": downloading.get("percent"), "name": downloading.get("name"),
                "rate_bytes_per_s": downloading.get("rate_bytes_per_s"),
                "eta_seconds": downloading.get("eta_seconds")}

    def _stop_model_server(self) -> None:
        try:
            self.sidecar.stop_server()
        except Exception:
            self.log.debug("could not stop the model server", exc_info=True)

    # -- the drain ---------------------------------------------------------
    def _should_stop(self) -> bool:
        """Between every stage: has anything happened that means this machine
        must put the clip down? The gate is re-run rather than cached, because
        "the editor came back" is exactly the event this has to notice."""
        if self._stop_event.is_set() or self._cancel.is_set():
            return True
        return self._gate() != STATE_RUNNING

    def _drain(self) -> str:
        """Crunch items until the queue is empty or the gate closes."""
        while not self._should_stop():
            item = self._next_item()
            if item is None:
                return STATE_NOTHING_TO_DO
            started = self._clock()
            try:
                self._crunch_item(item)
            except LeaseLost as exc:
                self._lease_lost(str(exc))
                return STATE_NOTHING_TO_DO
            except Exception as exc:  # noqa: BLE001 - one clip, not the batch
                self.log.exception("%s failed", item.get("name"))
                self._fail_item(item, f"this clip could not be indexed: {exc}")
            else:
                if item.get("stage") in (ITEM_UPLOADING, ITEM_LIVE):
                    with self._lock:
                        self._eta.observe(self._clock() - started)
                    item["seconds"] = round(self._clock() - started, 1)
            self._save()
            self._pump_uploads()
        with self._lock:
            self._current = {}
        return self._gate()

    def _next_item(self) -> Optional[dict]:
        with self._lock:
            batch = self._batch
            if not batch:
                return None
            for item in batch.get("items") or []:
                stage = item.get("stage")
                if stage in self.item_finished or stage == ITEM_UPLOADING:
                    continue
                if stage == ITEM_FAILED and int(item.get("attempts") or 0) >= MAX_ITEM_ATTEMPTS:
                    continue
                return item
        return None

    def _crunch_item(self, item: dict) -> None:
        """One clip, checkpointed at every stage (plan §1 step 6).

        Each stage checks `_should_stop()` FIRST, so an editor coming back
        costs at most the stage in flight -- and the stage in flight leaves
        either a finished artifact or nothing (never a half-written one that a
        later run would trust).
        """
        uid = item.get("uid")
        name = item.get("name") or ""
        self._set_current(name, item.get("stage") or ITEM_PENDING, 0)
        item["attempts"] = int(item.get("attempts") or 0) + 1

        source = item.get("local_path") or ""
        if not source or not os.path.isfile(source):
            self._fail_item(item, "the source file is not on this machine any more")
            return

        # 1. probe (needed by the sprite geometry and the result POST)
        probe = item.get("probe")
        if not probe:
            probe = self._probe(source)
            item["probe"] = probe
            item["hash"] = item.get("hash") or self._hash_fn(source)
        duration = float((probe or {}).get("duration_s") or 0)

        outputs = item.setdefault("outputs", {})
        out_dir = self._out_dir(item)

        # 2. proxy
        if not outputs.get("proxy") or not os.path.isfile(outputs["proxy"]):
            if self._should_stop():
                return
            self._stage(item, ITEM_PROXYING, 10)
            proxy = self._make_proxy(item, source, out_dir, probe)
            if proxy is None:
                return
            outputs["proxy"] = proxy
            self._save()

        # 3. stills off the proxy -- never off the original: a 10-bit FX3 file
        # decodes at a fraction of the speed, and the proxy is what the web UI
        # will show beside them anyway.
        if not outputs.get("poster") or not outputs.get("sprite"):
            if self._should_stop():
                return
            self._stage(item, ITEM_PROXYING, 40)
            self._make_stills(item, outputs["proxy"], out_dir, duration)
            self._save()

        # 4. frames
        if not outputs.get("frames"):
            if self._should_stop():
                return
            self._stage(item, ITEM_FRAMING, 55)
            self._make_frames(item, outputs["proxy"], duration)
            self._save()

        # 5. describe
        if not item.get("described"):
            if self._should_stop():
                return
            self._stage(item, ITEM_DESCRIBING, 70)
            result = self._describe(item)
            if result is None:
                return
            item["described"] = True
            self._post_result(item, result)
            self._save()

        # 6. hand to the upload queue
        self._stage(item, ITEM_UPLOADING, 90)
        self._enqueue_uploads(item)

    def _out_dir(self, item: dict) -> Path:
        with self._lock:
            batch = self._batch or {}
        base = Path(batch.get("staging_dir") or "") if batch.get("staging_dir") else None
        if base is None or not str(base):
            base = Path(self.staging_root() or Path.home()) / "loose"
        directory = base / "out"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _make_proxy(self, item: dict, source: str, out_dir: Path,
                    probe: dict) -> Optional[str]:
        """540p browsing proxy, NVENC with one CPU retry, `.partial` first.

        The verify step is proxy_gen's and is not optional: NVENC on a machine
        whose sessions are all taken exits 0 having written a few seconds, and
        a proxy that plays for four of a ninety-second clip is worse than none
        (the whole point of the archive is that other editors can SEE it).
        """
        dest = out_dir / f"{item.get('video_id') or item.get('uid')}.mp4"
        partial = dest.with_suffix(".mp4.partial")
        timecode = (probe or {}).get("timecode")
        for nvenc in ([True, False] if self._nvenc() else [False]):
            cmd = self.media.preview_proxy_cmd(self.ffmpeg_path, source, partial,
                                               nvenc=nvenc, timecode=timecode)
            code, stderr = self._run_media(cmd)
            if code == 0 and partial.is_file() and partial.stat().st_size > 0:
                if self._verify_proxy(partial, probe):
                    try:
                        os.replace(str(partial), str(dest))
                    except OSError as exc:
                        self._fail_item(item, f"the proxy could not be published: {exc}")
                        return None
                    return str(dest)
                self.log.warning("%s produced a short proxy on %s",
                            item.get("name"), "NVENC" if nvenc else "the CPU")
            _unlink(partial)
            if self._should_stop():
                return None
        self._fail_item(item, "the proxy did not decode -- this clip was skipped")
        return None

    def _verify_proxy(self, path: Path, probe: dict) -> bool:
        expected = float((probe or {}).get("duration_s") or 0)
        if expected <= 0:
            return True
        try:
            made = float(self._probe(path).get("duration_s") or 0)
        except Exception:
            self.log.debug("could not verify %s", path, exc_info=True)
            return True
        return made >= expected * VERIFY_DURATION_RATIO

    def _make_stills(self, item: dict, proxy: str, out_dir: Path,
                     duration: float) -> None:
        video_id = item.get("video_id") or item.get("uid")
        outputs = item.setdefault("outputs", {})
        poster = out_dir / f"{video_id}.poster.jpg"
        code, _err = self._run_media(
            self.media.poster_cmd(self.ffmpeg_path, proxy, poster,
                                  duration_s=duration))
        if code == 0 and poster.is_file():
            outputs["poster"] = str(poster)

        sprite = out_dir / f"{video_id}.sprite.jpg"
        geometry = self.media.sprite_geometry(duration)
        code, _err = self._run_media(
            self.media.sprite_cmd(self.ffmpeg_path, proxy, sprite, geometry))
        if code == 0 and sprite.is_file():
            outputs["sprite"] = str(sprite)
            item["sprite"] = {**geometry, **_measure_sprite_cells(sprite, geometry)}

        # The page's preview grid reads this one out of staging; a clip whose
        # browser-side canvas thumbnail failed (10-bit HEVC, most of them)
        # gets it from here instead.
        if not item.get("thumb"):
            thumb = out_dir / f"{video_id}.thumb.jpg"
            code, _err = self._run_media(
                self.media.thumb_cmd(self.ffmpeg_path, proxy, thumb,
                                     duration_s=duration))
            if code == 0 and thumb.is_file():
                item["thumb"] = str(thumb)

    def _make_frames(self, item: dict, proxy: str, duration: float) -> None:
        """Scene-detect, fill the gaps, extract the stills the model reads.

        Into `<staging>/sheets/{video_id}/`, because that is the layout the
        VENDORED `load_frame_list` reconstructs -- timestamps in frames.json,
        `frames/frame_{i:04d}.jpg` beside it, holes left where ffmpeg produced
        nothing (broll_ingest_media.frame_path's contract).
        """
        video_id = item.get("video_id") or item.get("uid")
        sheets = Path(self._sheets_root()) / "sheets" / str(video_id)
        frames_dir = sheets / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        _code, stderr = self._run_media(
            self.media.scene_detect_cmd(self.ffmpeg_path, proxy))
        timestamps = self.media.fill_gaps(
            self.media.parse_scene_timestamps(stderr), duration)

        # `broll_ingest_max_concurrent_ffmpeg` binds HERE and only here. One
        # clip is crunched at a time (the describe stage owns the GPU and a
        # second encode beside it just makes both slower), but a 90-second clip
        # is 20-plus independent one-frame seeks and each is a process spawn --
        # the slowest ffmpeg stage of the six, and the only one where a second
        # child is free rather than contended.
        width = max(1, min(int(self.max_concurrent_ffmpeg or 1), 8))
        done = 0

        def _extract(pair) -> None:
            index, timestamp = pair
            if self._should_stop():
                return
            self._run_media(self.media.extract_frame_cmd(
                self.ffmpeg_path, proxy, timestamp,
                self.media.frame_path(frames_dir, index), duration_s=duration))

        if width == 1:
            for pair in enumerate(timestamps):
                _extract(pair)
                done += 1
                if timestamps:
                    self._set_current(item.get("name") or "", ITEM_FRAMING,
                                      55 + int(10 * done / len(timestamps)))
        else:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=width,
                                    thread_name_prefix="ccsync-broll-frames") as pool:
                for _ in pool.map(_extract, list(enumerate(timestamps))):
                    done += 1
                    if timestamps:
                        self._set_current(item.get("name") or "", ITEM_FRAMING,
                                          55 + int(10 * done / len(timestamps)))
        if self._should_stop():
            # No frames.json: a partial sheet written now would be read on the
            # next run as a complete one, and the clip would be described from
            # half its frames.
            return
        self.media.write_frames_json(sheets, timestamps)
        item.setdefault("outputs", {})["frames"] = str(sheets)

    def _sheets_root(self) -> str:
        with self._lock:
            batch = self._batch or {}
        return batch.get("staging_dir") or str(self.staging_root() or Path.home())

    def _describe(self, item: dict) -> Optional[dict]:
        """The vendored `describe_video`, unmodified, against our own server.

        The shims are what make "unmodified" true: it wants a config object
        with seven attributes and a storage object with two methods, and it
        gets exactly those -- no DB, no YAML, no anthropic.
        """
        tier = self._tier()
        with self._lock:
            taxonomy = list((self._batch or {}).get("taxonomy") or [])
        try:
            handle = self.sidecar.server(tier, self.cfg)
        except Exception as exc:  # noqa: BLE001 - SidecarError and anything else
            self._fail_item(item, str(exc))
            return None

        storage = StorageShim(taxonomy)
        cfg_shim = ConfigShim(
            data_root=self._sheets_root(), tier=tier,
            cache_dir=str(getattr(self.sidecar, "cache_dir", lambda: "")()),
        )
        describe = self._describe_fn
        if describe is None:
            from .broll_vlm import local_vlm
            describe = local_vlm.describe_video
        try:
            describe(cfg_shim, storage, {"id": item.get("video_id") or item.get("uid")},
                     server_url=getattr(handle, "url", None))
        except Exception as exc:  # noqa: BLE001
            self.log.warning("the local model failed on %s (%s)",
                        item.get("name"), exc)
            self._fail_item(item, (
                f"the local model could not describe this clip ({exc}) -- see "
                f"{self.sidecar.server_log_path(self.cfg)}"))
            return None
        return storage.result

    def _post_result(self, item: dict, result: dict) -> None:
        """Hand the description to the server, which writes the segments AND
        computes `search_norm` -- the thing that makes a CJK on-screen-text
        term findable at all (PR-D, app/normalize.py)."""
        with self._lock:
            uid = (self._batch or {}).get("uid")
        probe = item.get("probe") or {}
        sprite = item.get("sprite") or {}
        body = {
            "segments": result.get("segments") or [],
            "themes": result.get("themes") or [],
            "quality_flags": result.get("quality_flags") or [],
            "category_hint": result.get("category_hint"),
            "model": result.get("model"),
            "duration_s": probe.get("duration_s"),
            "fps": probe.get("fps"),
            "width": probe.get("width"),
            "height": probe.get("height"),
            "codec": probe.get("codec"),
            "shot_date": probe.get("shot_date"),
            # MEASURED off the sheet this machine just wrote, never derived
            # from the source's aspect ratio: `scale=w:-2` rounds to an even
            # number, and on the live archive 6,783 of 7,117 sheets came out a
            # pixel taller than the prediction (BROLL-1/BROLL-2).
            "sprite_cell_w": sprite.get("sprite_cell_w"),
            "sprite_cell_h": sprite.get("sprite_cell_h"),
            "sprite_cols": sprite.get("sprite_cols"),
            "sprite_cells": sprite.get("sprite_cells"),
            "sprite_interval_s": sprite.get("sprite_interval_s"),
        }
        status, parsed = self._client().item_result(uid, item["uid"], body)
        if status != 200:
            self.log.warning("the server refused the result for %s "
                        "(HTTP %s: %s)", item.get("name"), status,
                        _detail_of(parsed) or "no detail")
        item["stage"] = ITEM_INDEXED

    # -- uploads -----------------------------------------------------------
    def _queue(self) -> Any:
        if self._uploader is None:
            self._uploader = broll_upload.UploadQueue(lambda: self.cfg)
            if self._upload_paused:
                self._uploader.pause()
        return self._uploader

    def _enqueue_uploads(self, item: dict) -> None:
        """Stills, then proxy, then the original last (UploadQueue's order).

        The original is last for a reason that is not politeness: it is 40 GB
        against the proxy's 40 MB, and an editor who reopens the page wants to
        SEE the clip -- which needs the poster, the sprite and the proxy, and
        not one byte of the camera file.
        """
        outputs = item.get("outputs") or {}
        video_id = item.get("video_id")
        archive_dir = item.get("archive_dir") or ""
        stem = item.get("archive_stem") or ""
        rels: dict[str, str] = {}
        queue = self._queue()

        if outputs.get("poster") and video_id:
            rels[f"posters/{video_id}.jpg"] = broll_upload.KIND_POSTER
        if outputs.get("sprite") and video_id:
            rels[f"sprites/{video_id}.jpg"] = broll_upload.KIND_SPRITE
        if outputs.get("proxy") and archive_dir and stem:
            rels[f"{archive_dir}/Proxy/{stem}.mp4"] = broll_upload.KIND_PROXY
        with self._lock:
            upload_originals = bool(
                ((self._batch or {}).get("settings") or {}).get("upload_originals", True))
        if upload_originals and archive_dir and item.get("final_name"):
            rels[f"{archive_dir}/{item['final_name']}"] = broll_upload.KIND_ORIGINAL

        locals_for = {
            broll_upload.KIND_POSTER: outputs.get("poster"),
            broll_upload.KIND_SPRITE: outputs.get("sprite"),
            broll_upload.KIND_PROXY: outputs.get("proxy"),
            broll_upload.KIND_ORIGINAL: item.get("local_path"),
        }
        item["uploads"] = rels
        for rel, kind in rels.items():
            local = locals_for.get(kind)
            if not local or not os.path.isfile(local):
                continue
            try:
                queue.enqueue(local, rel, kind, item_uid=item["uid"],
                              size_bytes=os.path.getsize(local))
            except Exception:
                self.log.exception("could not queue %s", rel)
        item["stage"] = ITEM_UPLOADING
        self._stage(item, ITEM_UPLOADING, 90)

    def _upload_snapshot(self) -> dict[str, Any]:
        queue = self._uploader
        if queue is None:
            return {"queued": 0, "active": None, "done": 0, "failed": 0,
                    "paused": self._upload_paused}
        try:
            return queue.progress()
        except Exception:
            self.log.debug("the upload snapshot failed", exc_info=True)
            return {"queued": 0, "active": None}

    def _pump_uploads(self) -> None:
        """Turn "rclone finished" into "the server says it is live".

        The server believes NOTHING here: `mark_uploaded` stats every declared
        file under BROLL_DATA_ROOT and answers 409 with exactly which ones are
        missing, which is what lets an interrupted upload retry those files
        rather than the clip.
        """
        queue = self._uploader
        with self._lock:
            batch = self._batch
        if queue is None or not batch:
            return
        try:
            landed = {entry["rel"]: entry for entry in queue.uploaded()}
            failures = {entry["rel"]: entry for entry in queue.failures()}
        except Exception:
            self.log.debug("could not read the upload queue", exc_info=True)
            return
        for item in list(batch.get("items") or []):
            if item.get("stage") != ITEM_UPLOADING:
                continue
            rels = item.get("uploads") or {}
            if not rels:
                continue
            missing = [rel for rel in rels if rel not in landed]
            if missing:
                broken = [rel for rel in missing if rel in failures]
                if broken:
                    item["error"] = failures[broken[0]].get("error") or "the upload failed"
                continue
            files = [{"rel": rel, "size": landed[rel].get("size")} for rel in rels]
            original_uploaded = any(
                kind == broll_upload.KIND_ORIGINAL for kind in rels.values())
            try:
                status, parsed = self._post_uploaded(
                    batch["uid"], item, files, original_uploaded)
            except LeaseLost as exc:
                self._lease_lost(str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                self.log.warning("could not report %s as uploaded (%s)",
                            item.get("name"), exc)
                continue
            if status == 200:
                item["stage"] = self._final_state(item)
                item["error"] = "" if item["stage"] == ITEM_LIVE else item.get("error", "")
                item["original_uploaded"] = original_uploaded
                self._mirror_locally(item)
                self.log.info("%s finished as %s", item.get("name"), item["stage"])
            elif status == 409:
                # The server could not see some of the files. Re-queue exactly
                # those -- the item STAYS in `uploading`, which is the whole
                # difference between a retried upload and a re-indexed clip
                # (and, since _drain re-picks anything not uploading, between
                # a retry and an infinite loop).
                detail = parsed.get("detail") if isinstance(parsed, dict) else {}
                gone = list((detail or {}).get("missing") or [])
                tries = int(item.get("upload_attempts") or 0) + 1
                item["upload_attempts"] = tries
                self.log.warning("the NAS is missing %d file(s) for %s "
                            "-- retry %d of %d", len(gone), item.get("name"),
                            tries, MAX_UPLOAD_ATTEMPTS)
                if tries >= MAX_UPLOAD_ATTEMPTS:
                    item["error"] = ("the archive never saw these files: "
                                     + ", ".join(gone[:3]))
                    self._fail_item(item, item["error"])
                    continue
                self._enqueue_uploads(item)
            else:
                self.log.warning("the server would not mark %s live "
                            "(HTTP %s)", item.get("name"), status)
        self._save()

    def _final_state(self, item: dict) -> str:
        """What an item becomes once its files are on the NAS.

        `live` for b-roll, always: an uploaded clip with an index row IS live.
        Music has one other ending (`queued_for_base_rig`, the fallback for a
        machine that could not embed), so it overrides this rather than having
        the shared pump hardcode a happy ending it cannot always deliver.
        """
        return ITEM_LIVE

    def _post_uploaded(self, batch_uid: str, item: dict, files: list,
                       original_uploaded: bool) -> tuple[int, Any]:
        """Tell the server the files landed. The ONE call whose BODY differs
        between the kinds (docs/API.md 6a vs 6b): b-roll declares a list of
        archive-relative files, music declares one size, because the server
        allocated the only name involved and nothing about it came off the
        wire."""
        return self._client().item_uploaded(batch_uid, item["uid"], files,
                                            original_uploaded)

    def _mirror_locally(self, item: dict) -> None:
        """Put this machine's own copy of the preview where the archive keeps
        it, so "Send to Resolve" on the machine that indexed the clip needs no
        fetch at all (plan §9.9). Best effort: a failure here costs a download
        later, nothing more."""
        archive = self.archive_root()
        outputs = item.get("outputs") or {}
        if archive is None or not outputs.get("proxy"):
            return
        rel = f"{item.get('archive_dir') or ''}/Proxy/{item.get('archive_stem') or ''}.mp4"
        dest = archive / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                return
            shutil.move(outputs["proxy"], str(dest))
            outputs["proxy"] = str(dest)
        except Exception:
            self.log.debug("could not mirror %s locally", rel, exc_info=True)

    def _stop_uploads(self) -> None:
        queue = self._uploader
        if queue is None:
            return
        try:
            queue.stop_all()
        except Exception:
            self.log.debug("could not stop the upload queue", exc_info=True)

    # -- finishing ---------------------------------------------------------
    def _maybe_finish(self) -> None:
        with self._lock:
            batch = self._batch
        if not batch:
            return
        items = batch.get("items") or []
        if not items:
            return
        outstanding = [i for i in items
                       if i.get("stage") not in self.item_finished
                       and not (i.get("stage") == ITEM_FAILED
                                and int(i.get("attempts") or 0) >= MAX_ITEM_ATTEMPTS)]
        if outstanding:
            return
        failed = sum(1 for i in items if i.get("stage") == ITEM_FAILED)
        summary = {"done": sum(1 for i in items if i.get("stage") == ITEM_LIVE),
                   "failed": failed, "total": len(items)}
        self._client().release(batch["uid"], "failed" if failed == len(items) else "done",
                               summary)
        self.log.info("batch %s finished -- %s", batch["uid"], summary)
        with self._lock:
            self._batch = None
            self._current = {}
            self._forced = False
        self._stop_model_server()
        self._publish_state(STATE_NOTHING_TO_DO)
        self._save()

    def _lease_lost(self, why: str) -> None:
        """410, however it arrived: stop, keep everything staged, forget the
        batch. Not an error -- the server has taken it back and either another
        machine will finish it or the editor cancelled it."""
        with self._lock:
            uid = (self._batch or {}).get("uid")
            self._batch = None
            self._current = {}
        self.log.info("batch %s is no longer ours (%s)", uid, why)
        self._kill_child()
        self._stop_uploads()
        self._stop_model_server()
        self._publish_state(STATE_NOTHING_TO_DO)
        self._save()

    # -- heartbeat ---------------------------------------------------------
    def _start_heartbeat(self) -> None:
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="ccsync-broll-heartbeat", daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        """Every 30 s: keep the lease, and learn whether to stop.

        The reply carries `cancel_requested` and `upload_paused` rather than
        two more routes, so an admin's cancel lands within one heartbeat --
        which is the whole budget the plan gives it.
        """
        while not self._stop_event.is_set():
            with self._lock:
                batch = self._batch
                interval = float((batch or {}).get("heartbeat_seconds")
                                 or HEARTBEAT_SECONDS)
            if not batch:
                return
            try:
                reply = self._client().heartbeat(batch["uid"])
            except LeaseLost as exc:
                self._lease_lost(str(exc))
                return
            except Exception as exc:  # noqa: BLE001 - a NAS blip is not a stop
                self.log.debug("heartbeat failed (%s)", exc)
            else:
                if reply.get("cancel_requested"):
                    self.cancel("cancelled from the dashboard")
                    return
                if reply.get("upload_paused") != self._upload_paused:
                    self.pause_upload(bool(reply.get("upload_paused")))
            if self._stop_event.wait(interval):
                return

    # -- small helpers -----------------------------------------------------
    def _client(self) -> FleetClient:
        return FleetClient(self.deps, prefix=self.kind.api_prefix)

    def _run_media(self, cmd: list) -> tuple:
        runner = self._run_media_fn or self.media.run_ffmpeg
        try:
            return runner(cmd)
        except self.media.UnreadableMediaError as exc:
            self.log.warning("ffmpeg refused (%s)", exc)
            return 1, str(exc)

    def _kill_child(self) -> None:
        child = self._child
        self._child = None
        if child is None:
            return
        try:
            child.kill()
        except Exception:
            self.log.debug("could not kill the media child", exc_info=True)

    def _set_current(self, name: str, stage: str, percent: int) -> None:
        with self._lock:
            self._current = {"name": name, "stage": stage, "percent": percent}

    def _stage(self, item: dict, stage: str, percent: int) -> None:
        """Checkpoint: local first, then the server, then the state file.

        Local first because the state file is what a restart reads and a
        network hiccup must not lose a stage that really happened; the server
        POST is best effort for the same reason (its own recount is driven by
        the item rows, and the next checkpoint carries the newer stage anyway).
        """
        item["stage"] = stage
        self._set_current(item.get("name") or "", stage, percent)
        with self._lock:
            batch = self._batch
        if not batch:
            return
        batch["state"] = "running"
        try:
            self._client().item_status(
                batch["uid"], item["uid"], stage, stage_percent=percent,
                **self._status_fields(item))
        except LeaseLost:
            raise
        except Exception as exc:  # noqa: BLE001
            self.log.debug("checkpoint %s for %s did not reach the "
                      "dashboard (%s)", stage, item.get("name"), exc)
        self._save()

    def _status_fields(self, item: dict) -> dict[str, Any]:
        """What a checkpoint carries besides the stage and its percentage.

        A hook rather than a literal because the two kinds' status models
        declare different fields (docs/API.md 6a vs 6b) and pydantic silently
        DROPS one it does not declare -- so a music checkpoint sending b-roll's
        `hash` would post a content hash the server never records, and nothing
        would say so.
        """
        return {"attempts": item.get("attempts"), "hash": item.get("hash"),
                "probe": item.get("probe")}

    def _fail_item(self, item: dict, why: str) -> None:
        item["stage"] = ITEM_FAILED
        item["error"] = why
        self.log.warning("%s -- %s", item.get("name"), why)
        with self._lock:
            batch = self._batch
        if batch:
            try:
                self._client().item_status(batch["uid"], item["uid"], ITEM_FAILED,
                                           error=why[:2000],
                                           attempts=item.get("attempts"))
            except LeaseLost:
                raise
            except Exception:
                self.log.debug("could not report the failure", exc_info=True)
        self._save()

    def _space_refusal(self, directory: Path) -> Optional[str]:
        """Editor-facing text, or None. A disk we cannot measure is NOT a
        refusal (sidecar_tools' rule): "I could not tell" must never read
        as "no"."""
        floor = int(max(0.0, float(self.free_space_floor_gb)) * 1_000_000_000)
        free = broll_server._free_bytes_at(directory)
        if free is None or free >= floor:
            return None
        return (f"Not enough space where the {self.kind.unit}s would be staged "
                f"({directory}): {free / 1_000_000_000:.1f} GB free, and "
                f"{floor / 1_000_000_000:.0f} GB is the floor. Free some space "
                "and it will continue")

    def _path_refusal(self, path: str) -> str:
        """Why this machine may not index a picked path in place, or ""."""
        if not path:
            return "no path was given for that clip"
        try:
            if not os.path.isfile(path):
                return "that file is not on this machine"
        except OSError:
            return "that file could not be read"
        if os.path.splitext(path)[1].lower() not in self.kind.exts:
            return f"that is not {self.kind.media_word}"
        return ""

    def _probe_and_hash(self, entry: dict) -> dict:
        """ffprobe + xxh64 for one staged file, recording the refusal rather
        than raising: one unreadable clip must not fail a 400-clip drop."""
        path = str(entry.get("path") or "")
        if not path or not os.path.isfile(path):
            entry.update(state=STAGED_FAILED, error="the file is not there")
            return {}
        try:
            entry["probe"] = self._probe(path)
        except Exception as exc:  # noqa: BLE001
            entry.update(state=STAGED_FAILED,
                         error=f"this file could not be read ({exc})")
            return {}
        try:
            entry["hash"] = self._hash_fn(path)
        except Exception as exc:  # noqa: BLE001
            self.log.debug("could not hash %s (%s)", path, exc)
        entry["state"] = STAGED_READY
        entry.setdefault("size", None)
        if not entry.get("size"):
            try:
                entry["size"] = os.path.getsize(path)
            except OSError:
                pass
        return {}

    def _start_prepare_worker(self, staging_id: str) -> None:
        """Probe and hash everything already on disk, off the request thread.

        A 400-clip folder pick is 400 ffprobes and 400 hashes of 16 MiB each;
        doing that inside the prepare POST would hold a request thread for
        minutes and the page would give up long before it finished.
        """
        def _work() -> None:
            with self._lock:
                staging = dict(self._staging.get(staging_id) or {})
            for entry in list((staging.get("items") or {}).values()):
                if self._stop_event.is_set():
                    return
                if entry.get("state") != STAGED_WAITING:
                    continue
                if entry.get("source") == "path":
                    self._probe_and_hash(entry)
            self._save()

        threading.Thread(target=_work, name="ccsync-broll-prepare",
                         daemon=True).start()


def _measure_sprite_cells(path: Path, geometry: dict) -> dict[str, Any]:
    """The finished sheet's cell size, measured. {} when it cannot be.

    Measured and not computed for BROLL-1/BROLL-2's reason (see `_post_result`).
    Pillow is already in the companion's `tray` extra; a build without it still
    ingests, the browser just falls back to its own guess for the hover overlay.
    """
    try:
        from PIL import Image  # noqa: PLC0415 - optional, and only per clip

        with Image.open(path) as image:
            width, height = image.size
    except Exception:  # noqa: BLE001
        log.debug("broll ingest: could not measure %s", path, exc_info=True)
        return {}
    cols = max(int(geometry.get("sprite_cols") or 1), 1)
    rows = max(int(geometry.get("sprite_rows") or 1), 1)
    return {"sprite_cell_w": int(width // cols), "sprite_cell_h": int(height // rows)}


def _gate_note(gate: str) -> str:
    """The gate, in the sentence the progress window shows under the bars."""
    return {
        STATE_USER_ACTIVE: "waiting until you're away from the keyboard",
        STATE_RESOLVE_OPEN: "waiting: DaVinci Resolve is open",
        STATE_PAUSED: "paused",
        STATE_NO_MODEL: "fetching the local indexing model",
        STATE_NO_FFMPEG: "waiting for ffmpeg to be installed",
        STATE_DRIVE_ABSENT: "waiting: the sync drive is not connected",
        STATE_MISCONFIGURED: "waiting: this machine's sync config needs fixing",
        STATE_RUNNING: "",
        STATE_NOTHING_TO_DO: "",
    }.get(gate, gate)


def _time_left_phrase(seconds: Optional[float]) -> str:
    """"about 1 min left". Deliberately vaguer than popup.human_eta's "~12 min
    left": a model download's remaining time swings with the CDN, and a number
    that looks precise and then doubles is worse than one that never claimed
    to be."""
    try:
        secs = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if secs <= 0:
        return "almost done"
    if secs < 60:
        return f"about {secs} sec left"
    if secs < 3600:
        return f"about {secs // 60} min left"
    return f"about {secs // 3600}h {(secs % 3600) // 60}m left"


def _download_headline(name: str, percent: Optional[int],
                       rate: Optional[float], eta: Optional[float]) -> str:
    """The progress window's top line while a model is being fetched.

    "Downloading Qwen3-VL 4B (Good): 61% at 38 MB/s, about 1 min left"
    (2026-08-18) -- the speed and the time left are the whole point of the
    line, because a multi-GB fetch with only a percentage on it is
    indistinguishable from a hang. Both are optional: the first seconds of a
    download have no rate to quote yet, and then the line is just the name.
    """
    if percent is None:
        return ""
    headline = f"Downloading {name}" if name else "Downloading the indexing model"
    detail = f"{max(0, min(100, int(percent)))}%"
    if rate and rate > 0:
        detail += f" at {popup.human_bytes(rate)}/s"
    left = _time_left_phrase(eta) if eta else ""
    if left:
        detail += f", {left}"
    return f"{headline}: {detail}"


def _safe_id(value: Any) -> bool:
    text = str(value or "")
    return bool(text) and all(c.isalnum() or c in "-_" for c in text) and len(text) <= 64


def _safe_uid(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 32 and all(c in "0123456789abcdef" for c in text)


def _clean_local_id(value: Any, index: int) -> str:
    text = "".join(c for c in str(value or "") if c.isalnum() or c in "-_.")
    return text[:64] or f"item{index}"


def _clean_rel_dir(value: Any) -> str:
    """A sub-folder path below the shoot root, with no way out of the tree.
    The server sanitises it again -- this side does it too because the value
    reaches os.path.join here first."""
    raw = str(value or "").replace("\\", "/")
    parts = [p for p in raw.split("/") if p and p not in (".", "..")]
    return "/".join(parts)[:255]


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        log.debug("ingest: could not remove %s (%s)", path, exc)
